from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import Department, EmployeeProfile, User, WorkProject, WorkTask
from app.security.permissions import is_admin_user


@dataclass(frozen=True)
class WorkbenchAccess:
    tenant_id: str
    user_id: str
    business_role: str = "member"
    can_view_all: bool = False
    is_active_employee: bool = False
    is_system_admin: bool = False
    managed_department_ids: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def for_user(cls, db: Session, tenant_id: str, user_id: str) -> WorkbenchAccess:
        user = db.get(User, user_id)
        if user is None or user.tenant_id != tenant_id:
            return cls(tenant_id=tenant_id, user_id=user_id)
        profile = db.exec(
            select(EmployeeProfile).where(
                EmployeeProfile.tenant_id == tenant_id,
                EmployeeProfile.user_id == user_id,
                EmployeeProfile.status == "active",
            )
        ).first()
        system_admin = is_admin_user(user)
        business_role = "admin" if system_admin else (profile.business_role if profile else "member")
        can_view_all = system_admin or bool(profile and profile.business_role == "ceo")
        managed_ids: list[str] = []
        if profile and business_role == "manager":
            managed_ids = db.exec(
                select(Department.id).where(
                    Department.tenant_id == tenant_id,
                    Department.status == "active",
                    Department.manager_user_id == user_id,
                )
            ).all()
        return cls(
            tenant_id=tenant_id,
            user_id=user_id,
            business_role=business_role,
            can_view_all=can_view_all,
            is_active_employee=profile is not None,
            is_system_admin=system_admin,
            managed_department_ids=frozenset(managed_ids),
        )

    @property
    def directory_scope(self) -> str:
        if self.can_view_all:
            return "all"
        if self.managed_department_ids:
            return "department"
        return "self"

    @property
    def can_create_project(self) -> bool:
        return self.is_active_employee and (
            self.can_view_all or bool(self.managed_department_ids)
        )

    @property
    def can_manage_organization(self) -> bool:
        return self.is_system_admin or (
            self.is_active_employee and self.business_role == "ceo"
        )

    def require_active_employee(self) -> None:
        if not self.is_active_employee:
            raise HTTPException(
                status_code=403,
                detail="An active employee profile is required for workbench tasks",
            )

    def can_manage_department(self, department_id: str | None) -> bool:
        return self.can_view_all or bool(department_id and department_id in self.managed_department_ids)


def employee_for_user(db: Session, tenant_id: str, user_id: str) -> EmployeeProfile | None:
    return db.exec(
        select(EmployeeProfile).where(
            EmployeeProfile.tenant_id == tenant_id,
            EmployeeProfile.user_id == user_id,
        )
    ).first()


def require_global_manager(db: Session, tenant_id: str, user_id: str) -> WorkbenchAccess:
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    if not access.can_manage_organization:
        raise HTTPException(status_code=403, detail="Only administrator or CEO can manage all employees")
    return access


def can_view_employee_sensitive(
    db: Session, tenant_id: str, user_id: str, employee: EmployeeProfile
) -> bool:
    if employee.tenant_id != tenant_id:
        return False
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    return (
        access.can_manage_organization
        or employee.user_id == user_id
        or employee.department_id in access.managed_department_ids
    )


def participant_project_ids(db: Session, tenant_id: str, user_id: str) -> frozenset[str]:
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    if not access.is_active_employee:
        return frozenset()
    owned = db.exec(
        select(WorkProject.id).where(
            WorkProject.tenant_id == tenant_id,
            WorkProject.owner_user_id == user_id,
        )
    ).all()
    assigned = db.exec(
        select(WorkTask.project_id)
        .where(
            WorkTask.tenant_id == tenant_id,
            (WorkTask.assignee_user_id == user_id)
            | (WorkTask.reviewer_user_id == user_id),
        )
        .distinct()
    ).all()
    return frozenset([*owned, *assigned])


def project_colleague_user_ids(db: Session, tenant_id: str, user_id: str) -> frozenset[str]:
    project_ids = participant_project_ids(db, tenant_id, user_id)
    if not project_ids:
        return frozenset()
    owners = db.exec(
        select(WorkProject.owner_user_id).where(
            WorkProject.tenant_id == tenant_id,
            WorkProject.id.in_(project_ids),
            WorkProject.owner_user_id.is_not(None),
        )
    ).all()
    task_users = db.exec(
        select(WorkTask.assignee_user_id, WorkTask.reviewer_user_id).where(
            WorkTask.tenant_id == tenant_id,
            WorkTask.project_id.in_(project_ids),
        )
    ).all()
    user_ids = {user_id, *owners}
    for assignee_user_id, reviewer_user_id in task_users:
        if assignee_user_id:
            user_ids.add(assignee_user_id)
        if reviewer_user_id:
            user_ids.add(reviewer_user_id)
    return frozenset(user_ids)


def can_view_employee(
    db: Session, tenant_id: str, user_id: str, employee: EmployeeProfile
) -> bool:
    return can_view_employee_sensitive(
        db, tenant_id, user_id, employee
    ) or (
        employee.tenant_id == tenant_id
        and employee.status == "active"
        and employee.user_id in project_colleague_user_ids(db, tenant_id, user_id)
    )


def can_manage_employee(
    db: Session, tenant_id: str, user_id: str, employee: EmployeeProfile
) -> bool:
    if employee.tenant_id != tenant_id:
        return False
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    if access.can_manage_organization:
        return True
    employee_user = db.get(User, employee.user_id)
    if (
        employee.business_role in {"admin", "ceo"}
        or employee_user is None
        or is_admin_user(employee_user)
    ):
        return False
    return access.is_active_employee and (
        employee.department_id in access.managed_department_ids
    )
