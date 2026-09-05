from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import Department, EmployeeProfile, User
from app.security.permissions import is_admin_user


@dataclass(frozen=True)
class WorkbenchAccess:
    tenant_id: str
    user_id: str
    business_role: str = "member"
    can_view_all: bool = False
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
        business_role = "admin" if is_admin_user(user) else (profile.business_role if profile else "member")
        can_view_all = is_admin_user(user) or bool(profile and profile.business_role == "ceo")
        managed_ids: list[str] = []
        if profile and business_role == "manager":
            managed_ids = db.exec(
                select(Department.id).where(
                    Department.tenant_id == tenant_id,
                    Department.status == "active",
                    Department.manager_user_id == user_id,
                )
            ).all()
            if profile.department_id:
                managed_ids.append(profile.department_id)
        return cls(
            tenant_id=tenant_id,
            user_id=user_id,
            business_role=business_role,
            can_view_all=can_view_all,
            managed_department_ids=frozenset(managed_ids),
        )

    @property
    def directory_scope(self) -> str:
        if self.can_view_all:
            return "all"
        if self.business_role == "manager":
            return "department"
        return "self"

    @property
    def can_create_project(self) -> bool:
        return self.can_view_all or bool(self.managed_department_ids)

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
    if not access.can_view_all:
        raise HTTPException(status_code=403, detail="Only administrator or CEO can manage all employees")
    return access


def can_view_employee(
    db: Session, tenant_id: str, user_id: str, employee: EmployeeProfile
) -> bool:
    if employee.tenant_id != tenant_id:
        return False
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    return (
        access.can_view_all
        or employee.user_id == user_id
        or employee.department_id in access.managed_department_ids
    )


def can_manage_employee(
    db: Session, tenant_id: str, user_id: str, employee: EmployeeProfile
) -> bool:
    if employee.tenant_id != tenant_id:
        return False
    return WorkbenchAccess.for_user(db, tenant_id, user_id).can_manage_department(employee.department_id)
