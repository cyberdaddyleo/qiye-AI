from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import Department, EmployeeProfile, User, WorkTask, utc_now


def department_for_tenant(db: Session, tenant_id: str, department_id: str) -> Department:
    row = db.get(Department, department_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Department not found")
    return row


def employee_for_tenant(db: Session, tenant_id: str, employee_id: str) -> EmployeeProfile:
    row = db.get(EmployeeProfile, employee_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Employee not found")
    return row


def user_for_tenant(db: Session, tenant_id: str, user_id: str) -> User:
    row = db.get(User, user_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    return row


def validate_employee_values(db: Session, tenant_id: str, values: dict[str, Any]) -> None:
    department_id = values.get("department_id")
    if department_id:
        department_for_tenant(db, tenant_id, department_id)
    for key in ("manager_user_id",):
        if values.get(key):
            user_for_tenant(db, tenant_id, values[key])


def create_employee(db: Session, tenant_id: str, values: dict[str, Any]) -> EmployeeProfile:
    user_id = values["user_id"]
    user_for_tenant(db, tenant_id, user_id)
    if db.exec(
        select(EmployeeProfile).where(
            EmployeeProfile.tenant_id == tenant_id, EmployeeProfile.user_id == user_id
        )
    ).first():
        raise HTTPException(status_code=409, detail="Employee already exists")
    validate_employee_values(db, tenant_id, values)
    row = EmployeeProfile(tenant_id=tenant_id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_employee(db: Session, employee: EmployeeProfile, values: dict[str, Any]) -> EmployeeProfile:
    validate_employee_values(db, employee.tenant_id, values)
    for key, value in values.items():
        setattr(employee, key, value)
    employee.updated_at = utc_now()
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def delete_employee(db: Session, employee: EmployeeProfile) -> bool:
    active_assignment = db.exec(
        select(WorkTask.id).where(
            WorkTask.tenant_id == employee.tenant_id,
            WorkTask.status.not_in(("done", "canceled")),
            (WorkTask.assignee_user_id == employee.user_id)
            | (WorkTask.reviewer_user_id == employee.user_id),
        )
    ).first()
    if active_assignment:
        employee.status = "inactive"
        employee.updated_at = utc_now()
        db.add(employee)
        db.commit()
        return True
    db.delete(employee)
    db.commit()
    return False
