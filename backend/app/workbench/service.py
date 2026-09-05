from __future__ import annotations

from collections.abc import Iterable
from copy import deepcopy
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, case, func, or_
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from app.db.models import (
    AgentProfile,
    Department,
    EmployeeProfile,
    User,
    WorkPlan,
    WorkProject,
    WorkTask,
    WorkTaskDependency,
    WorkTaskEvent,
    utc_now,
)
from app.workbench.permissions import WorkbenchAccess
from app.workbench.planner import (
    PlanVariant,
    build_variants,
    generate_wbs,
    validate_planning_tasks,
)

WORK_TASK_TRANSITIONS: dict[str, set[str]] = {
    "blocked": {"backlog", "canceled"},
    "backlog": {"in_progress", "canceled"},
    "in_progress": {"review", "canceled"},
    "review": {"done", "in_progress"},
    "done": set(),
    "canceled": set(),
}


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


def active_employee_for_user(
    db: Session,
    tenant_id: str,
    user_id: str,
    *,
    label: str = "Employee",
) -> EmployeeProfile:
    user_for_tenant(db, tenant_id, user_id)
    row = db.exec(
        select(EmployeeProfile).where(
            EmployeeProfile.tenant_id == tenant_id,
            EmployeeProfile.user_id == user_id,
            EmployeeProfile.status == "active",
        )
    ).first()
    if row is None:
        raise HTTPException(status_code=422, detail=f"{label} must be an active employee")
    return row


def user_for_tenant(db: Session, tenant_id: str, user_id: str) -> User:
    row = db.get(User, user_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="User not found")
    return row


def agent_for_tenant(db: Session, tenant_id: str, agent_id: str) -> AgentProfile:
    row = db.get(AgentProfile, agent_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Assistant agent not found")
    return row


def validate_employee_manager_assignment(
    db: Session,
    tenant_id: str,
    manager_user_id: str | None,
    access: WorkbenchAccess,
) -> EmployeeProfile | None:
    if manager_user_id is None:
        return None
    manager = active_employee_for_user(
        db,
        tenant_id,
        manager_user_id,
        label="Direct manager",
    )
    if not access.can_manage_department(manager.department_id):
        raise HTTPException(
            status_code=403,
            detail="Direct manager is outside the actor's staffing scope",
        )
    return manager


def validate_employee_values(
    db: Session,
    tenant_id: str,
    values: dict[str, Any],
    *,
    employee_user_id: str | None = None,
    access: WorkbenchAccess,
) -> None:
    department_id = values.get("department_id")
    if department_id:
        department_for_tenant(db, tenant_id, department_id)
    if values.get("manager_user_id"):
        validate_employee_manager_assignment(
            db,
            tenant_id,
            values["manager_user_id"],
            access,
        )
    if values.get("assistant_agent_id"):
        agent_for_tenant(db, tenant_id, values["assistant_agent_id"])
    if values.get("business_role") == "admin":
        raise HTTPException(
            status_code=422,
            detail="System administrator is not an employee business role",
        )
    if employee_user_id is None:
        return
    managed_department_ids = set(
        db.exec(
            select(Department.id).where(
                Department.tenant_id == tenant_id,
                Department.status == "active",
                Department.manager_user_id == employee_user_id,
            )
        ).all()
    )
    existing = db.exec(
        select(EmployeeProfile).where(
            EmployeeProfile.tenant_id == tenant_id,
            EmployeeProfile.user_id == employee_user_id,
        )
    ).first()
    business_role = values.get(
        "business_role",
        existing.business_role if existing is not None else "member",
    )
    department_id = values.get(
        "department_id",
        existing.department_id if existing is not None else None,
    )
    status = values.get(
        "status",
        existing.status if existing is not None else "active",
    )
    if business_role == "manager" and not managed_department_ids:
        raise HTTPException(
            status_code=422,
            detail="Manager role requires active department management",
        )
    if managed_department_ids and business_role != "manager":
        raise HTTPException(
            status_code=422,
            detail="A department manager must retain the manager role",
        )
    if managed_department_ids and status != "active":
        raise HTTPException(
            status_code=422,
            detail="An active department manager cannot be deactivated directly",
        )
    if managed_department_ids and department_id not in managed_department_ids:
        raise HTTPException(
            status_code=422,
            detail="A department manager must belong to a managed department",
        )


def create_employee(
    db: Session,
    tenant_id: str,
    values: dict[str, Any],
    *,
    access: WorkbenchAccess,
) -> EmployeeProfile:
    user_id = values["user_id"]
    user_for_tenant(db, tenant_id, user_id)
    if db.exec(
        select(EmployeeProfile).where(
            EmployeeProfile.tenant_id == tenant_id, EmployeeProfile.user_id == user_id
        )
    ).first():
        raise HTTPException(status_code=409, detail="Employee already exists")
    validate_employee_values(
        db,
        tenant_id,
        values,
        employee_user_id=user_id,
        access=access,
    )
    row = EmployeeProfile(tenant_id=tenant_id, **values)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def update_employee(
    db: Session,
    employee: EmployeeProfile,
    values: dict[str, Any],
    *,
    access: WorkbenchAccess,
) -> EmployeeProfile:
    validate_employee_values(
        db,
        employee.tenant_id,
        values,
        employee_user_id=employee.user_id,
        access=access,
    )
    for key, value in values.items():
        setattr(employee, key, value)
    employee.updated_at = utc_now()
    db.add(employee)
    db.commit()
    db.refresh(employee)
    return employee


def delete_employee(db: Session, employee: EmployeeProfile) -> bool:
    managed_departments = db.exec(
        select(Department).where(
            Department.tenant_id == employee.tenant_id,
            Department.manager_user_id == employee.user_id,
        )
    ).all()
    for department in managed_departments:
        department.manager_user_id = None
        department.updated_at = utc_now()
        db.add(department)
    if employee.business_role == "manager":
        employee.business_role = "member"
    employee.status = "inactive"
    employee.updated_at = utc_now()
    db.add(employee)
    db.commit()
    return True


def update_department(
    db: Session,
    department: Department,
    values: dict[str, Any],
) -> Department:
    values = dict(values)
    old_manager_user_id = department.manager_user_id
    manager_changed = "manager_user_id" in values
    new_manager_user_id = values.get("manager_user_id", old_manager_user_id)
    target_status = values.get("status", department.status)
    new_manager: EmployeeProfile | None = None
    if manager_changed and new_manager_user_id and target_status != "active":
        raise HTTPException(
            status_code=422,
            detail="Cannot assign a manager to an archived department",
        )
    if target_status == "active" and new_manager_user_id:
        new_manager = active_employee_for_user(
            db,
            department.tenant_id,
            new_manager_user_id,
            label="Department manager",
        )
        if new_manager.department_id != department.id:
            raise HTTPException(
                status_code=422,
                detail="Department manager must be an active employee in this department",
            )
        if new_manager.business_role in {"admin", "ceo"}:
            raise HTTPException(
                status_code=422,
                detail="A global employee role cannot be replaced by department manager",
            )

    now = utc_now()
    if manager_changed:
        result = db.exec(
            sa_update(Department)
            .where(
                Department.id == department.id,
                Department.tenant_id == department.tenant_id,
                Department.manager_user_id == old_manager_user_id,
            )
            .values(**values, updated_at=now)
            .execution_options(synchronize_session=False)
        )
        if result.rowcount != 1:
            db.rollback()
            raise HTTPException(status_code=409, detail="Department manager conflict")
        db.refresh(department)
    else:
        for key, value in values.items():
            setattr(department, key, value)
        department.updated_at = now
        db.add(department)

    if new_manager is not None:
        new_manager.business_role = "manager"
        new_manager.updated_at = utc_now()
        db.add(new_manager)

    old_manager_lost_scope = old_manager_user_id and (
        target_status != "active" or old_manager_user_id != new_manager_user_id
    )
    if old_manager_lost_scope:
        still_manages = db.exec(
            select(Department.id).where(
                Department.tenant_id == department.tenant_id,
                Department.status == "active",
                Department.manager_user_id == old_manager_user_id,
                Department.id != department.id,
            )
        ).first()
        old_manager = db.exec(
            select(EmployeeProfile).where(
                EmployeeProfile.tenant_id == department.tenant_id,
                EmployeeProfile.user_id == old_manager_user_id,
            )
        ).first()
        if old_manager is not None and not still_manages and old_manager.business_role == "manager":
            old_manager.business_role = "member"
            old_manager.updated_at = utc_now()
            db.add(old_manager)

    db.commit()
    db.refresh(department)
    return department


def project_for_tenant(db: Session, tenant_id: str, project_id: str) -> WorkProject:
    row = db.get(WorkProject, project_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Project not found")
    return row


def task_for_tenant(db: Session, tenant_id: str, task_id: str) -> WorkTask:
    row = db.get(WorkTask, task_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Task not found")
    return row


def plan_for_tenant(db: Session, tenant_id: str, plan_id: str) -> WorkPlan:
    row = db.get(WorkPlan, plan_id)
    if row is None or row.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Plan not found")
    return row


def ensure_plan_visible(db: Session, plan: WorkPlan, actor_user_id: str) -> None:
    access = WorkbenchAccess.for_user(db, plan.tenant_id, actor_user_id)
    access.require_active_employee()
    project = project_for_tenant(db, plan.tenant_id, plan.project_id)
    if (
        access.can_view_all
        or project.owner_user_id == actor_user_id
        or _managed_project(access, project)
        or (plan.status != "dispatched" and plan.created_by_user_id == actor_user_id)
    ):
        return
    assigned = db.exec(
        select(WorkTask.id).where(
            WorkTask.tenant_id == plan.tenant_id,
            WorkTask.plan_id == plan.id,
            (WorkTask.assignee_user_id == actor_user_id)
            | (WorkTask.reviewer_user_id == actor_user_id),
        )
    ).first()
    if not assigned:
        raise HTTPException(status_code=403, detail="Cannot view this plan")


def _full_plan_visibility(
    access: WorkbenchAccess,
    plan: WorkPlan,
    project: WorkProject,
) -> bool:
    return bool(
        access.can_view_all
        or project.owner_user_id == access.user_id
        or _managed_project(access, project)
        or (plan.status != "dispatched" and plan.created_by_user_id == access.user_id)
    )


def _participant_plan_variant(
    plan: WorkPlan,
    actor_user_id: str,
    participant_task_keys: Iterable[str],
) -> dict[str, Any] | None:
    if not plan.selected_variant:
        return None
    selected = plan.selected_variant_json
    if selected is None:
        selected = next(
            (item for item in plan.variants_json if item.get("key") == plan.selected_variant),
            None,
        )
    if not isinstance(selected, dict):
        return None

    safe = deepcopy(selected)
    raw_tasks = safe.get("tasks")
    if not isinstance(raw_tasks, list):
        safe["tasks"] = []
        raw_tasks = []
    tasks_by_key = {
        task.get("key"): task
        for task in raw_tasks
        if isinstance(task, dict) and isinstance(task.get("key"), str)
    }
    included_keys = {key for key in participant_task_keys if key in tasks_by_key}
    pending = list(included_keys)
    while pending:
        task = tasks_by_key[pending.pop()]
        for dependency_key in task.get("depends_on") or []:
            if dependency_key in tasks_by_key and dependency_key not in included_keys:
                included_keys.add(dependency_key)
                pending.append(dependency_key)

    visible_tasks: list[dict[str, Any]] = []
    for task in raw_tasks:
        if not isinstance(task, dict) or task.get("key") not in included_keys:
            continue
        task["assignment"] = {}
        task["unassigned_reason"] = None
        if task.get("assignee_user_id") != actor_user_id:
            task["assignee_user_id"] = None
        visible_tasks.append(task)
    safe["tasks"] = visible_tasks
    safe["utilization"] = {}
    safe["risks"] = []
    metrics = safe.get("metrics")
    critical_path = metrics.get("critical_path") if isinstance(metrics, dict) else None
    safe["metrics"] = (
        {
            "critical_path": [
                key for key in critical_path if isinstance(key, str) and key in included_keys
            ]
        }
        if isinstance(critical_path, list)
        else {}
    )
    return safe


def plan_values_for_user(
    db: Session,
    plan: WorkPlan,
    actor_user_id: str,
) -> WorkPlan | dict[str, Any]:
    ensure_plan_visible(db, plan, actor_user_id)
    access = WorkbenchAccess.for_user(db, plan.tenant_id, actor_user_id)
    project = project_for_tenant(db, plan.tenant_id, plan.project_id)
    if _full_plan_visibility(access, plan, project):
        return plan
    participant_task_ids = list(
        db.exec(
            select(WorkTask.id).where(
                WorkTask.tenant_id == plan.tenant_id,
                WorkTask.plan_id == plan.id,
                (WorkTask.assignee_user_id == actor_user_id)
                | (WorkTask.reviewer_user_id == actor_user_id),
            )
        ).all()
    )
    creation_events = (
        db.exec(
            select(WorkTaskEvent).where(
                WorkTaskEvent.tenant_id == plan.tenant_id,
                WorkTaskEvent.task_id.in_(participant_task_ids),
                WorkTaskEvent.event_type == "task_created",
            )
        ).all()
        if participant_task_ids
        else []
    )
    participant_task_keys = {
        task_key
        for event in creation_events
        if isinstance(event.payload_json, dict)
        and isinstance(task_key := event.payload_json.get("plan_task_key"), str)
    }
    safe_variant = _participant_plan_variant(
        plan,
        actor_user_id,
        participant_task_keys,
    )
    values = plan.model_dump()
    values["created_by_user_id"] = ""
    values["budget"] = None
    values["constraints_json"] = {}
    values["variants_json"] = [safe_variant] if safe_variant is not None else []
    values["selected_variant_json"] = safe_variant
    values["dispatch_overrides_json"] = []
    values["dispatch_idempotency_key"] = None
    return values


def _event(
    db: Session,
    task: WorkTask,
    event_type: str,
    actor_user_id: str | None,
    old_status: str | None,
    new_status: str | None,
    payload: dict[str, Any] | None = None,
    *,
    actor_type: str = "user",
) -> WorkTaskEvent:
    values = {"old_status": old_status, "new_status": new_status}
    values.update(payload or {})
    event = WorkTaskEvent(
        tenant_id=task.tenant_id,
        task_id=task.id,
        actor_user_id=actor_user_id,
        actor_type=actor_type,
        event_type=event_type,
        payload_json=values,
    )
    db.add(event)
    return event


def _project_event(
    db: Session, project: WorkProject, event_type: str, actor_user_id: str, old_status: str | None
) -> WorkTaskEvent:
    event = WorkTaskEvent(
        tenant_id=project.tenant_id,
        task_id=project.id,
        actor_user_id=actor_user_id,
        actor_type="user",
        event_type=event_type,
        payload_json={"old_status": old_status, "new_status": project.status},
    )
    db.add(event)
    return event


def _managed_project(access: WorkbenchAccess, project: WorkProject) -> bool:
    return access.can_manage_department(project.department_id)


def _ensure_selectable_employee(
    access: WorkbenchAccess,
    project_department_id: str | None,
    employee: EmployeeProfile,
) -> None:
    access.require_active_employee()
    if access.can_view_all:
        return
    if access.business_role == "manager":
        if employee.department_id in access.managed_department_ids:
            return
        raise HTTPException(
            status_code=403,
            detail="Employee is outside the manager's departments",
        )
    if employee.department_id != project_department_id:
        raise HTTPException(
            status_code=403,
            detail="Project owner can select only employees in the project department",
        )


def _active_selectable_employee(
    db: Session,
    access: WorkbenchAccess,
    project_department_id: str | None,
    user_id: str,
    *,
    label: str,
) -> EmployeeProfile:
    employee = active_employee_for_user(db, access.tenant_id, user_id, label=label)
    _ensure_selectable_employee(access, project_department_id, employee)
    return employee


def _participates_in_project(
    db: Session,
    access: WorkbenchAccess,
    project_id: str,
) -> bool:
    return bool(
        db.exec(
            select(WorkTask.id).where(
                WorkTask.tenant_id == access.tenant_id,
                WorkTask.project_id == project_id,
                (WorkTask.assignee_user_id == access.user_id)
                | (WorkTask.reviewer_user_id == access.user_id),
            )
        ).first()
    )


def _visible_task(
    db: Session, access: WorkbenchAccess, task: WorkTask, project: WorkProject | None = None
) -> bool:
    if not access.is_active_employee:
        return False
    if (
        access.can_view_all
        or task.assignee_user_id == access.user_id
        or task.reviewer_user_id == access.user_id
    ):
        return True
    project = project or project_for_tenant(db, access.tenant_id, task.project_id)
    return (
        project.owner_user_id == access.user_id
        or _managed_project(access, project)
        or _participates_in_project(db, access, project.id)
    )


def ensure_task_visible(
    db: Session, access: WorkbenchAccess, task: WorkTask, project: WorkProject | None = None
) -> None:
    if not _visible_task(db, access, task, project):
        raise HTTPException(status_code=403, detail="Cannot view this task")


def _ensure_project_manager(access: WorkbenchAccess, project: WorkProject) -> None:
    access.require_active_employee()
    if project.owner_user_id != access.user_id and not _managed_project(access, project):
        raise HTTPException(status_code=403, detail="Cannot manage this project")


def create_project(
    db: Session, tenant_id: str, values: dict[str, Any], actor_user_id: str
) -> WorkProject:
    values = dict(values)
    access = WorkbenchAccess.for_user(db, tenant_id, actor_user_id)
    access.require_active_employee()
    department_id = values.get("department_id")
    if not access.can_manage_department(department_id):
        raise HTTPException(status_code=403, detail="Cannot create a project for this department")
    if department_id:
        department_for_tenant(db, tenant_id, department_id)
    owner_user_id = values.pop("owner_user_id", None) or actor_user_id
    _active_selectable_employee(
        db,
        access,
        department_id,
        owner_user_id,
        label="Project owner",
    )
    row = WorkProject(tenant_id=tenant_id, owner_user_id=owner_user_id, **values)
    db.add(row)
    db.flush()
    _project_event(db, row, "project_created", actor_user_id, None)
    db.commit()
    db.refresh(row)
    return row


def _claim_project_version(db: Session, project: WorkProject, version: int) -> None:
    if project.version != version:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project version conflict")
    now = utc_now()
    result = db.exec(
        sa_update(WorkProject)
        .where(
            WorkProject.id == project.id,
            WorkProject.tenant_id == project.tenant_id,
            WorkProject.version == version,
        )
        .values(version=version + 1, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Project version conflict")
    project.version = version + 1
    project.updated_at = now


def update_project(
    db: Session,
    project: WorkProject,
    values: dict[str, Any],
    version: int,
    actor_user_id: str,
) -> WorkProject:
    access = WorkbenchAccess.for_user(db, project.tenant_id, actor_user_id)
    _ensure_project_manager(access, project)
    target_department_id = values.get("department_id", project.department_id)
    if "department_id" in values:
        if not values["department_id"]:
            raise HTTPException(status_code=422, detail="Project department is required")
        department_for_tenant(db, project.tenant_id, values["department_id"])
        if not access.can_manage_department(values["department_id"]):
            raise HTTPException(status_code=403, detail="Cannot move project to this department")
    target_owner_user_id = values.get("owner_user_id", project.owner_user_id)
    if not target_owner_user_id:
        raise HTTPException(status_code=422, detail="Project owner is required")
    _active_selectable_employee(
        db,
        access,
        target_department_id,
        target_owner_user_id,
        label="Project owner",
    )
    old_status = project.status
    _claim_project_version(db, project, version)
    for key, value in values.items():
        setattr(project, key, value)
    project.updated_at = utc_now()
    db.add(project)
    _project_event(db, project, "project_updated", actor_user_id, old_status)
    db.commit()
    db.refresh(project)
    return project


def _visible_project_predicate(
    access: WorkbenchAccess,
    tenant_id: str,
    user_id: str,
) -> Any:
    if access.can_view_all:
        return WorkProject.tenant_id == tenant_id
    participant_projects = (
        select(WorkTask.project_id)
        .where(
            WorkTask.tenant_id == tenant_id,
            (WorkTask.assignee_user_id == user_id) | (WorkTask.reviewer_user_id == user_id),
        )
        .distinct()
    )
    conditions = [
        WorkProject.owner_user_id == user_id,
        WorkProject.id.in_(participant_projects),
    ]
    if access.managed_department_ids:
        conditions.append(WorkProject.department_id.in_(access.managed_department_ids))
    return and_(
        WorkProject.tenant_id == tenant_id,
        or_(*conditions),
    )


def list_visible_projects(db: Session, tenant_id: str, user_id: str) -> list[WorkProject]:
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    access.require_active_employee()
    statement = select(WorkProject).where(_visible_project_predicate(access, tenant_id, user_id))
    return list(db.exec(statement.order_by(WorkProject.created_at, WorkProject.id)).all())


def project_progress(db: Session, project: WorkProject) -> dict[str, int]:
    tasks = list(
        db.exec(
            select(WorkTask).where(
                WorkTask.tenant_id == project.tenant_id,
                WorkTask.project_id == project.id,
                WorkTask.status != "canceled",
            )
        ).all()
    )
    total = len(tasks)
    done = sum(task.status == "done" for task in tasks)
    progress = round(sum(task.progress for task in tasks) / total) if total else 0
    return {"task_total": total, "task_done": done, "progress": progress}


def _validate_task_references(
    db: Session,
    tenant_id: str,
    project: WorkProject,
    access: WorkbenchAccess,
    values: dict[str, Any],
    dependencies: Iterable[str],
) -> list[WorkTask]:
    plan_id = values.get("plan_id")
    if plan_id:
        plan = db.get(WorkPlan, plan_id)
        if plan is None or plan.tenant_id != tenant_id or plan.project_id != project.id:
            raise HTTPException(status_code=404, detail="Plan not found")
    parent_task_id = values.get("parent_task_id")
    if parent_task_id:
        parent = task_for_tenant(db, tenant_id, parent_task_id)
        if parent.project_id != project.id:
            raise HTTPException(status_code=422, detail="Parent task must belong to the project")
    for key in ("assignee_user_id", "reviewer_user_id"):
        if key in values and values[key] is not None:
            _active_selectable_employee(
                db,
                access,
                project.department_id,
                values[key],
                label="Task assignee" if key == "assignee_user_id" else "Task reviewer",
            )
    dependency_rows: list[WorkTask] = []
    for dependency_id in dict.fromkeys(dependencies):
        dependency = task_for_tenant(db, tenant_id, dependency_id)
        if dependency.project_id != project.id:
            raise HTTPException(status_code=422, detail="Dependencies must belong to the project")
        dependency_rows.append(dependency)
    return dependency_rows


def _dependency_ids(db: Session, tenant_id: str, task_id: str) -> list[str]:
    return list(
        db.exec(
            select(WorkTaskDependency.depends_on_task_id).where(
                WorkTaskDependency.tenant_id == tenant_id,
                WorkTaskDependency.task_id == task_id,
            )
        ).all()
    )


def _dependencies_are_ready(db: Session, task: WorkTask) -> bool:
    dependency_ids = _dependency_ids(db, task.tenant_id, task.id)
    if not dependency_ids:
        return True
    dependencies = db.exec(
        select(WorkTask).where(
            WorkTask.tenant_id == task.tenant_id,
            WorkTask.id.in_(dependency_ids),
        )
    ).all()
    return len(dependencies) == len(dependency_ids) and all(
        dependency.status == "done" for dependency in dependencies
    )


def _would_cycle(db: Session, tenant_id: str, task_id: str, dependency_ids: Iterable[str]) -> bool:
    graph: dict[str, set[str]] = {}
    rows = db.exec(
        select(WorkTaskDependency).where(WorkTaskDependency.tenant_id == tenant_id)
    ).all()
    for row in rows:
        if row.task_id != task_id:
            graph.setdefault(row.task_id, set()).add(row.depends_on_task_id)
    graph[task_id] = set(dependency_ids)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> bool:
        if node in visiting:
            return True
        if node in visited:
            return False
        visiting.add(node)
        if any(visit(next_node) for next_node in graph.get(node, set())):
            return True
        visiting.remove(node)
        visited.add(node)
        return False

    return any(visit(node) for node in graph)


def _replace_dependencies(db: Session, task: WorkTask, dependency_rows: list[WorkTask]) -> None:
    dependency_ids = [row.id for row in dependency_rows]
    if task.id in dependency_ids or _would_cycle(db, task.tenant_id, task.id, dependency_ids):
        raise HTTPException(status_code=422, detail="Task dependency cycle detected")
    existing = db.exec(
        select(WorkTaskDependency).where(
            WorkTaskDependency.tenant_id == task.tenant_id,
            WorkTaskDependency.task_id == task.id,
        )
    ).all()
    for row in existing:
        db.delete(row)
    for dependency_id in dependency_ids:
        db.add(
            WorkTaskDependency(
                tenant_id=task.tenant_id,
                task_id=task.id,
                depends_on_task_id=dependency_id,
            )
        )


def create_task(
    db: Session, tenant_id: str, values: dict[str, Any], actor_user_id: str
) -> WorkTask:
    values = dict(values)
    dependency_ids = list(values.pop("dependencies", []))
    project = project_for_tenant(db, tenant_id, values["project_id"])
    access = WorkbenchAccess.for_user(db, tenant_id, actor_user_id)
    _ensure_project_manager(access, project)
    _claim_project_version(db, project, project.version)
    try:
        dependencies = _validate_task_references(
            db, tenant_id, project, access, values, dependency_ids
        )
        status = values.pop("status", None)
        if dependencies and any(dependency.status != "done" for dependency in dependencies):
            status = "blocked"
    except HTTPException:
        db.rollback()
        raise
    row = WorkTask(tenant_id=tenant_id, status=status or "backlog", **values)
    db.add(row)
    db.flush()
    _replace_dependencies(db, row, dependencies)
    _event(db, row, "task_created", actor_user_id, None, row.status)
    if row.assignee_user_id:
        _event(
            db,
            row,
            "task_assigned",
            actor_user_id,
            row.status,
            row.status,
            {"assignee_user_id": row.assignee_user_id},
        )
    db.commit()
    db.refresh(row)
    return row


def build_plan(db: Session, request: Any, current_user: User) -> WorkPlan:
    tenant_id = request.tenant_id
    project = project_for_tenant(db, tenant_id, request.project_id)
    access = WorkbenchAccess.for_user(db, tenant_id, current_user.id)
    _ensure_project_manager(access, project)

    goal = (request.goal or project.objective).strip()
    deadline = request.deadline or project.due_date
    budget = request.budget if request.budget is not None else project.budget
    constraints = dict(request.constraints or {})
    generated = generate_wbs(db, tenant_id, goal, constraints)
    employee_statement = select(EmployeeProfile).where(
        EmployeeProfile.tenant_id == tenant_id,
        EmployeeProfile.status == "active",
    )
    if access.business_role == "manager":
        employee_statement = employee_statement.where(
            EmployeeProfile.department_id.in_(access.managed_department_ids)
        )
    elif not access.can_view_all:
        employee_statement = employee_statement.where(
            EmployeeProfile.department_id == project.department_id
        )
    employees = list(db.exec(employee_statement).all())
    current_work = list(
        db.exec(
            select(WorkTask).where(
                WorkTask.tenant_id == tenant_id,
                WorkTask.status.in_(("blocked", "backlog", "in_progress", "review")),
            )
        ).all()
    )
    today = utc_now().date()
    start_date = max(today, project.start_date) if project.start_date else today
    variants = build_variants(
        generated.tasks,
        employees,
        current_work,
        project_id=project.id,
        start_date=start_date,
        deadline=deadline,
        budget=budget,
    )
    plan = WorkPlan(
        tenant_id=tenant_id,
        project_id=project.id,
        created_by_user_id=current_user.id,
        goal=goal,
        deadline=deadline,
        budget=budget,
        constraints_json=constraints,
        status="draft",
        source=generated.source,
        variants_json=[variant.model_dump(mode="json") for variant in variants],
    )
    try:
        db.add(plan)
        db.commit()
        db.refresh(plan)
        return plan
    except Exception:
        db.rollback()
        raise


def _tasks_for_plan(db: Session, plan: WorkPlan) -> list[WorkTask]:
    return list(
        db.exec(
            select(WorkTask)
            .where(
                WorkTask.tenant_id == plan.tenant_id,
                WorkTask.plan_id == plan.id,
            )
            .order_by(WorkTask.created_at, WorkTask.id)
        ).all()
    )


class _DispatchTasks(list[WorkTask]):
    def __init__(self, tasks: Iterable[WorkTask], *, created: bool) -> None:
        super().__init__(tasks)
        self.created = created


_DISPATCH_EDITABLE_FIELDS = (
    "assignee_user_id",
    "start_date",
    "due_date",
    "acceptance_criteria",
    "depends_on",
)


def _dispatch_variant(
    plan: WorkPlan,
    variant_key: str,
    task_overrides: Iterable[Any] | None,
) -> tuple[PlanVariant, list[dict[str, Any]]]:
    try:
        original = PlanVariant.model_validate(
            next(item for item in plan.variants_json if item.get("key") == variant_key)
        )
    except (StopIteration, ValidationError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Plan variant is invalid") from exc
    if task_overrides is None:
        return original, []

    try:
        override_values = [
            item.model_dump(mode="python") if hasattr(item, "model_dump") else dict(item)
            for item in task_overrides
        ]
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Dispatch task overrides are invalid") from exc
    override_keys = [str(item.get("key") or "") for item in override_values]
    original_keys = [task.key for task in original.tasks]
    if len(override_keys) != len(set(override_keys)) or set(override_keys) != set(original_keys):
        raise HTTPException(
            status_code=422,
            detail="Dispatch tasks must contain each selected variant task exactly once",
        )

    by_key = {str(item["key"]): item for item in override_values}
    effective_tasks = []
    audit: list[dict[str, Any]] = []
    try:
        for planned in original.tasks:
            requested = by_key[planned.key]
            update = {field: requested.get(field) for field in _DISPATCH_EDITABLE_FIELDS}
            if update["assignee_user_id"] != planned.assignee_user_id:
                update["assignment"] = {
                    "provenance": "manual",
                    "manual_assignment_kind": (
                        "reassigned" if planned.assignee_user_id else "assigned"
                    ),
                    "previous_assignee_user_id": planned.assignee_user_id,
                }
                update["unassigned_reason"] = (
                    None if update["assignee_user_id"] else "负责人已由管理者人工取消指派"
                )
            effective = type(planned).model_validate(
                {**planned.model_dump(mode="python"), **update}
            )
            effective_tasks.append(effective)
            changes: dict[str, dict[str, Any]] = {}
            original_json = planned.model_dump(mode="json")
            effective_json = effective.model_dump(mode="json")
            for field in _DISPATCH_EDITABLE_FIELDS:
                if original_json[field] != effective_json[field]:
                    changes[field] = {
                        "from": original_json[field],
                        "to": effective_json[field],
                    }
            if changes:
                audit.append({"key": planned.key, "changes": changes})
        effective_variant = PlanVariant.model_validate(
            {**original.model_dump(mode="python"), "tasks": effective_tasks}
        )
    except (ValidationError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail="Dispatch task overrides are invalid") from exc
    return effective_variant, audit


def _validate_dispatch_variant(
    db: Session,
    access: WorkbenchAccess,
    project: WorkProject,
    variant: PlanVariant,
) -> None:
    try:
        validate_planning_tasks(variant.tasks)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Plan variant schedule or dependencies are invalid",
        ) from exc

    assignee_ids = {task.assignee_user_id for task in variant.tasks if task.assignee_user_id}
    if not assignee_ids:
        return
    for assignee_id in sorted(assignee_ids):
        _active_selectable_employee(
            db,
            access,
            project.department_id,
            assignee_id,
            label="Plan assignee",
        )


def dispatch_plan(
    db: Session,
    plan_id: str,
    variant_key: str,
    idempotency_key: str,
    current_user: User,
    task_overrides: Iterable[Any] | None = None,
) -> list[WorkTask]:
    plan = plan_for_tenant(db, current_user.tenant_id, plan_id)
    project = project_for_tenant(db, plan.tenant_id, plan.project_id)
    access = WorkbenchAccess.for_user(db, plan.tenant_id, current_user.id)
    _ensure_project_manager(access, project)
    variant, dispatch_overrides = _dispatch_variant(plan, variant_key, task_overrides)
    selected_snapshot = variant.model_dump(mode="json")

    if plan.status == "dispatched":
        if plan.dispatch_idempotency_key == idempotency_key:
            stored_snapshot = plan.selected_variant_json
            if stored_snapshot is None:
                try:
                    stored_snapshot = PlanVariant.model_validate(
                        next(
                            item
                            for item in plan.variants_json
                            if item.get("key") == plan.selected_variant
                        )
                    ).model_dump(mode="json")
                except (StopIteration, ValidationError, AttributeError):
                    stored_snapshot = None
            if plan.selected_variant != variant_key or stored_snapshot != selected_snapshot:
                raise HTTPException(
                    status_code=409,
                    detail="Idempotency key was used with a different dispatch payload",
                )
            return _DispatchTasks(_tasks_for_plan(db, plan), created=False)
        raise HTTPException(status_code=409, detail="Plan was already dispatched")
    if plan.status != "draft":
        raise HTTPException(status_code=409, detail="Plan is not dispatchable")
    collision = db.exec(
        select(WorkPlan.id).where(
            WorkPlan.tenant_id == plan.tenant_id,
            WorkPlan.dispatch_idempotency_key == idempotency_key,
            WorkPlan.id != plan.id,
        )
    ).first()
    if collision:
        raise HTTPException(status_code=409, detail="Idempotency key is already in use")

    _active_selectable_employee(
        db,
        access,
        project.department_id,
        project.owner_user_id or "",
        label="Task reviewer",
    )
    _validate_dispatch_variant(db, access, project, variant)

    now = utc_now()
    try:
        claim = db.exec(
            sa_update(WorkPlan)
            .where(
                WorkPlan.id == plan.id,
                WorkPlan.tenant_id == plan.tenant_id,
                WorkPlan.status == "draft",
                WorkPlan.dispatch_idempotency_key.is_(None),
            )
            .values(
                status="approved",
                selected_variant=variant_key,
                selected_variant_json=selected_snapshot,
                dispatch_overrides_json=dispatch_overrides,
                dispatch_idempotency_key=idempotency_key,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if claim.rowcount != 1:
            db.rollback()
            latest = plan_for_tenant(db, current_user.tenant_id, plan_id)
            if latest.status == "dispatched" and latest.dispatch_idempotency_key == idempotency_key:
                if (
                    latest.selected_variant != variant_key
                    or latest.selected_variant_json != selected_snapshot
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Idempotency key was used with a different dispatch payload",
                    )
                return _DispatchTasks(_tasks_for_plan(db, latest), created=False)
            raise HTTPException(status_code=409, detail="Plan dispatch conflict")
        plan.status = "approved"
        plan.selected_variant = variant_key
        plan.selected_variant_json = selected_snapshot
        plan.dispatch_overrides_json = dispatch_overrides
        plan.dispatch_idempotency_key = idempotency_key
        plan.updated_at = now

        _claim_project_version(db, project, project.version)
        tasks_by_key: dict[str, WorkTask] = {}
        for planned in variant.tasks:
            row = WorkTask(
                tenant_id=plan.tenant_id,
                project_id=plan.project_id,
                plan_id=plan.id,
                title=planned.title,
                description=planned.description or None,
                required_role=planned.required_role or None,
                priority=planned.priority,
                status="blocked" if planned.depends_on else "backlog",
                assignee_user_id=planned.assignee_user_id,
                reviewer_user_id=project.owner_user_id,
                start_date=planned.start_date,
                due_date=planned.due_date,
                estimate_days=planned.estimate_days,
                acceptance_criteria=planned.acceptance_criteria or None,
            )
            db.add(row)
            db.flush()
            tasks_by_key[planned.key] = row
            _event(
                db,
                row,
                "task_created",
                current_user.id,
                None,
                row.status,
                {"plan_task_key": planned.key},
            )
            if row.assignee_user_id:
                _event(
                    db,
                    row,
                    "task_assigned",
                    current_user.id,
                    row.status,
                    row.status,
                    {"assignee_user_id": row.assignee_user_id},
                )
        for planned in variant.tasks:
            for dependency_key in planned.depends_on:
                db.add(
                    WorkTaskDependency(
                        tenant_id=plan.tenant_id,
                        task_id=tasks_by_key[planned.key].id,
                        depends_on_task_id=tasks_by_key[dependency_key].id,
                    )
                )

        plan.status = "dispatched"
        plan.dispatched_at = now
        plan.updated_at = now
        db.add(plan)
        db.commit()
        db.expire_all()
        return _DispatchTasks(
            _tasks_for_plan(db, plan_for_tenant(db, current_user.tenant_id, plan_id)),
            created=True,
        )
    except HTTPException:
        db.rollback()
        raise
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Plan dispatch conflict") from exc
    except Exception:
        db.rollback()
        raise


def _claim_version(db: Session, task: WorkTask, version: int) -> None:
    """Atomically reserve the requested version before writing task state and its event."""
    if task.version != version:
        db.rollback()
        raise HTTPException(status_code=409, detail="Task version conflict")
    result = db.exec(
        sa_update(WorkTask)
        .where(
            WorkTask.id == task.id,
            WorkTask.tenant_id == task.tenant_id,
            WorkTask.version == version,
        )
        .values(version=version + 1)
        .execution_options(synchronize_session=False)
    )
    if result.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Task version conflict")
    task.version = version + 1


def _ensure_executor(access: WorkbenchAccess, project: WorkProject, task: WorkTask) -> None:
    del project
    access.require_active_employee()
    if task.assignee_user_id != access.user_id:
        raise HTTPException(status_code=403, detail="Only the assignee can execute this task")


def _ensure_reviewer(access: WorkbenchAccess, project: WorkProject, task: WorkTask) -> None:
    access.require_active_employee()
    if task.reviewer_user_id != access.user_id and not (
        project.owner_user_id == access.user_id or _managed_project(access, project)
    ):
        raise HTTPException(
            status_code=403, detail="Only the reviewer or manager can review this task"
        )


def update_task(
    db: Session,
    task: WorkTask,
    values: dict[str, Any],
    version: int,
    actor_user_id: str,
) -> WorkTask:
    values = dict(values)
    dependency_ids = values.pop("dependencies", None)
    project = project_for_tenant(db, task.tenant_id, task.project_id)
    access = WorkbenchAccess.for_user(db, task.tenant_id, actor_user_id)
    ensure_task_visible(db, access, task, project)
    old_status = task.status
    old_progress = task.progress
    old_assignee_user_id = task.assignee_user_id
    requested_status = values.get("status")

    if task.status in {"done", "canceled"}:
        raise HTTPException(status_code=422, detail="Terminal tasks are immutable")
    review_frozen_fields = {
        "assignee_user_id",
        "start_date",
        "due_date",
        "estimate_days",
        "progress",
        "acceptance_criteria",
    }
    if task.status == "review" and (
        review_frozen_fields.intersection(values) or dependency_ids is not None
    ):
        raise HTTPException(
            status_code=422,
            detail="Execution fields are frozen while a task is in review",
        )
    if "progress" in values and (
        task.status != "in_progress" or requested_status not in {None, task.status}
    ):
        raise HTTPException(
            status_code=422,
            detail="Progress can be changed only while a task remains in progress",
        )
    if dependency_ids is None and (
        not values or all(getattr(task, key) == value for key, value in values.items())
    ):
        raise HTTPException(status_code=422, detail="Task update contains no changes")

    manager_fields = {
        "title",
        "description",
        "priority",
        "assignee_user_id",
        "reviewer_user_id",
        "start_date",
        "due_date",
        "estimate_days",
        "acceptance_criteria",
    }
    if manager_fields.intersection(values) or dependency_ids is not None:
        _ensure_project_manager(access, project)
    if "progress" in values:
        _ensure_executor(access, project, task)
    if requested_status is not None and requested_status != task.status:
        if requested_status not in WORK_TASK_TRANSITIONS.get(task.status, set()):
            raise HTTPException(status_code=422, detail="Invalid task status transition")
        if task.status == "backlog" and requested_status == "in_progress":
            _ensure_executor(access, project, task)
        elif (
            task.status == "blocked" and requested_status == "backlog"
        ) or requested_status == "canceled":
            _ensure_project_manager(access, project)
        else:
            raise HTTPException(status_code=422, detail="Use submit or review for this transition")

    if dependency_ids is not None and requested_status not in {None, task.status}:
        raise HTTPException(
            status_code=422,
            detail="Change task status and dependencies in separate requests",
        )
    graph_mutation = dependency_ids is not None or (
        old_status == "blocked" and requested_status == "backlog"
    )
    if graph_mutation:
        _claim_project_version(db, project, project.version)
    try:
        if (
            old_status == "blocked"
            and requested_status == "backlog"
            and not _dependencies_are_ready(db, task)
        ):
            raise HTTPException(status_code=422, detail="Task dependencies are not complete")
        dependencies = _validate_task_references(
            db, task.tenant_id, project, access, values, dependency_ids or []
        )
        if dependency_ids is not None and (
            task.id in dependency_ids or _would_cycle(db, task.tenant_id, task.id, dependency_ids)
        ):
            raise HTTPException(status_code=422, detail="Task dependency cycle detected")
    except HTTPException:
        if graph_mutation:
            db.rollback()
        raise
    _claim_version(db, task, version)
    if dependency_ids is not None:
        _replace_dependencies(db, task, dependencies)
        if task.status in {"backlog", "blocked"}:
            task.status = (
                "blocked"
                if dependencies and any(row.status != "done" for row in dependencies)
                else "backlog"
            )
    for key, value in values.items():
        setattr(task, key, value)
    if task.status == "in_progress" and old_status == "backlog" and task.start_date is None:
        task.start_date = utc_now().date()
    task.updated_at = utc_now()
    db.add(task)

    event_written = False
    if task.status == "in_progress" and old_status == "backlog":
        _event(db, task, "task_started", actor_user_id, old_status, task.status)
        event_written = True
    if task.status == "backlog" and old_status == "blocked":
        _event(db, task, "task_unblocked", actor_user_id, old_status, task.status)
        event_written = True
    if task.status == "canceled" and old_status != "canceled":
        _event(db, task, "task_canceled", actor_user_id, old_status, task.status)
        event_written = True
    if task.progress != old_progress:
        _event(
            db,
            task,
            "progress_updated",
            actor_user_id,
            old_status,
            task.status,
            {"old_progress": old_progress, "new_progress": task.progress},
        )
        event_written = True
    if "assignee_user_id" in values and task.assignee_user_id != old_assignee_user_id:
        event_type = "task_unassigned" if task.assignee_user_id is None else "task_assigned"
        _event(
            db,
            task,
            event_type,
            actor_user_id,
            old_status,
            task.status,
            {
                "assignee_user_id": task.assignee_user_id,
                "previous_assignee_user_id": old_assignee_user_id,
                "new_assignee_user_id": task.assignee_user_id,
            },
        )
        event_written = True
    if dependency_ids is not None:
        _event(
            db,
            task,
            "dependencies_updated",
            actor_user_id,
            old_status,
            task.status,
            {"dependencies": dependency_ids},
        )
        event_written = True
    if not event_written:
        _event(db, task, "task_updated", actor_user_id, old_status, task.status)
    db.commit()
    db.refresh(task)
    return task


def add_task_comment(
    db: Session, task: WorkTask, comment: str, version: int, actor_user_id: str
) -> WorkTask:
    access = WorkbenchAccess.for_user(db, task.tenant_id, actor_user_id)
    ensure_task_visible(db, access, task)
    if task.status in {"done", "canceled"}:
        raise HTTPException(status_code=422, detail="Terminal tasks are immutable")
    old_status = task.status
    _claim_version(db, task, version)
    task.updated_at = utc_now()
    db.add(task)
    _event(
        db,
        task,
        "comment_added",
        actor_user_id,
        old_status,
        task.status,
        {"comment": comment},
    )
    db.commit()
    db.refresh(task)
    return task


def submit_task(
    db: Session,
    task: WorkTask,
    version: int,
    result_summary: str,
    artifact_refs: list[str],
    actor_user_id: str,
) -> WorkTask:
    project = project_for_tenant(db, task.tenant_id, task.project_id)
    access = WorkbenchAccess.for_user(db, task.tenant_id, actor_user_id)
    _ensure_executor(access, project, task)
    if "review" not in WORK_TASK_TRANSITIONS.get(task.status, set()):
        raise HTTPException(
            status_code=422, detail="Task cannot be submitted from its current status"
        )
    old_status = task.status
    _claim_version(db, task, version)
    task.status = "review"
    task.result_summary = result_summary
    task.updated_at = utc_now()
    db.add(task)
    _event(
        db,
        task,
        "result_submitted",
        actor_user_id,
        old_status,
        task.status,
        {"result_summary": result_summary, "artifact_refs": list(artifact_refs)},
    )
    db.commit()
    db.refresh(task)
    return task


def _activate_ready_tasks(
    db: Session, tenant_id: str, project_id: str | None = None
) -> list[WorkTask]:
    statement = select(WorkTask).where(
        WorkTask.tenant_id == tenant_id, WorkTask.status == "blocked"
    )
    if project_id:
        statement = statement.where(WorkTask.project_id == project_id)
    blocked = db.exec(statement).all()
    activated: list[WorkTask] = []
    for task in blocked:
        dependency_ids = _dependency_ids(db, tenant_id, task.id)
        if not dependency_ids:
            continue
        dependencies = db.exec(
            select(WorkTask).where(WorkTask.tenant_id == tenant_id, WorkTask.id.in_(dependency_ids))
        ).all()
        if len(dependencies) == len(dependency_ids) and all(
            row.status == "done" for row in dependencies
        ):
            old_status = task.status
            next_version = task.version + 1
            now = utc_now()
            result = db.exec(
                sa_update(WorkTask)
                .where(
                    WorkTask.id == task.id,
                    WorkTask.tenant_id == tenant_id,
                    WorkTask.status == "blocked",
                    WorkTask.version == task.version,
                )
                .values(status="backlog", version=next_version, updated_at=now)
                .execution_options(synchronize_session=False)
            )
            if result.rowcount != 1:
                continue
            task.status = "backlog"
            task.version = next_version
            task.updated_at = now
            db.add(task)
            _event(
                db,
                task,
                "dependency_unblocked",
                None,
                old_status,
                task.status,
                actor_type="system",
            )
            activated.append(task)
    return activated


def activate_ready_tasks(db: Session, tenant_id: str) -> list[WorkTask]:
    project_ids = list(
        db.exec(
            select(WorkTask.project_id)
            .where(WorkTask.tenant_id == tenant_id, WorkTask.status == "blocked")
            .distinct()
        ).all()
    )
    activated: list[WorkTask] = []
    for project_id in project_ids:
        project = project_for_tenant(db, tenant_id, project_id)
        _claim_project_version(db, project, project.version)
        activated.extend(_activate_ready_tasks(db, tenant_id, project_id))
    db.commit()
    for task in activated:
        db.refresh(task)
    return activated


def review_task(
    db: Session,
    task: WorkTask,
    version: int,
    verdict: str,
    comment: str | None,
    actor_user_id: str,
) -> WorkTask:
    project = project_for_tenant(db, task.tenant_id, task.project_id)
    access = WorkbenchAccess.for_user(db, task.tenant_id, actor_user_id)
    _ensure_reviewer(access, project, task)
    new_status = "done" if verdict == "approve" else "in_progress"
    if new_status not in WORK_TASK_TRANSITIONS.get(task.status, set()):
        raise HTTPException(
            status_code=422, detail="Task cannot be reviewed from its current status"
        )
    old_status = task.status
    if verdict == "approve":
        _claim_project_version(db, project, project.version)
    _claim_version(db, task, version)
    task.status = new_status
    if verdict == "approve":
        task.progress = 100
        task.completed_at = utc_now()
    else:
        task.completed_at = None
    task.updated_at = utc_now()
    db.add(task)
    _event(
        db,
        task,
        "review_approved" if verdict == "approve" else "review_returned",
        actor_user_id,
        old_status,
        task.status,
        {"comment": comment},
    )
    if verdict == "approve":
        _activate_ready_tasks(db, task.tenant_id, project.id)
    db.commit()
    db.refresh(task)
    return task


def task_dependencies(db: Session, task: WorkTask) -> list[str]:
    return _dependency_ids(db, task.tenant_id, task.id)


def task_events(db: Session, task: WorkTask) -> list[WorkTaskEvent]:
    return list(
        db.exec(
            select(WorkTaskEvent)
            .where(
                WorkTaskEvent.tenant_id == task.tenant_id,
                WorkTaskEvent.task_id == task.id,
            )
            .order_by(WorkTaskEvent.created_at, WorkTaskEvent.id)
        ).all()
    )


def task_dependencies_bulk(
    db: Session,
    tasks: Iterable[WorkTask],
) -> dict[str, list[str]]:
    rows = list(tasks)
    result: dict[str, list[str]] = {task.id: [] for task in rows}
    if not rows:
        return result
    task_ids = list(result)
    dependencies = db.exec(
        select(WorkTaskDependency)
        .where(
            WorkTaskDependency.tenant_id == rows[0].tenant_id,
            WorkTaskDependency.task_id.in_(task_ids),
        )
        .order_by(WorkTaskDependency.created_at, WorkTaskDependency.id)
    ).all()
    for dependency in dependencies:
        result[dependency.task_id].append(dependency.depends_on_task_id)
    return result


def task_events_bulk(
    db: Session,
    tasks: Iterable[WorkTask],
) -> dict[str, list[WorkTaskEvent]]:
    rows = list(tasks)
    result: dict[str, list[WorkTaskEvent]] = {task.id: [] for task in rows}
    if not rows:
        return result
    events = db.exec(
        select(WorkTaskEvent)
        .where(
            WorkTaskEvent.tenant_id == rows[0].tenant_id,
            WorkTaskEvent.task_id.in_(list(result)),
        )
        .order_by(WorkTaskEvent.created_at, WorkTaskEvent.id)
    ).all()
    for row in events:
        result[row.task_id].append(row)
    return result


def _visible_tasks_statement(
    db: Session,
    tenant_id: str,
    user_id: str,
    scope: str,
    status: str | None = None,
    project_id: str | None = None,
) -> Any:
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    access.require_active_employee()
    statement = select(WorkTask).where(WorkTask.tenant_id == tenant_id)
    if status:
        statement = statement.where(WorkTask.status == status)
    if project_id:
        project_for_tenant(db, tenant_id, project_id)
        statement = statement.where(WorkTask.project_id == project_id)
    if scope == "mine":
        statement = statement.where(
            (WorkTask.assignee_user_id == user_id) | (WorkTask.reviewer_user_id == user_id)
        )
    elif scope == "department":
        if not access.managed_department_ids:
            raise HTTPException(status_code=403, detail="Cannot view department tasks")
        project_ids = select(WorkProject.id).where(
            WorkProject.tenant_id == tenant_id,
            WorkProject.department_id.in_(access.managed_department_ids),
        )
        statement = statement.where(WorkTask.project_id.in_(project_ids))
    elif scope == "all":
        if not access.can_view_all:
            raise HTTPException(status_code=403, detail="Cannot view all tasks")
    else:
        raise HTTPException(status_code=422, detail="Invalid task scope")
    return statement


def list_visible_tasks(
    db: Session,
    tenant_id: str,
    user_id: str,
    scope: str,
    status: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[WorkTask]:
    statement = _visible_tasks_statement(
        db,
        tenant_id,
        user_id,
        scope,
        status=status,
        project_id=project_id,
    )
    return list(
        db.exec(
            statement.order_by(WorkTask.created_at, WorkTask.id).offset(offset).limit(limit)
        ).all()
    )


def list_visible_tasks_page(
    db: Session,
    tenant_id: str,
    user_id: str,
    scope: str,
    status: str | None = None,
    project_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[WorkTask], int]:
    statement = _visible_tasks_statement(
        db,
        tenant_id,
        user_id,
        scope,
        status=status,
        project_id=project_id,
    )
    total = int(db.exec(select(func.count()).select_from(statement.subquery())).one())
    rows = list(
        db.exec(
            statement.order_by(WorkTask.created_at, WorkTask.id).offset(offset).limit(limit)
        ).all()
    )
    return rows, total


def project_progresses(
    db: Session,
    projects: Iterable[WorkProject],
) -> dict[str, dict[str, int]]:
    rows = list(projects)
    result = {project.id: {"task_total": 0, "task_done": 0, "progress": 0} for project in rows}
    if not rows:
        return result
    aggregates = db.exec(
        select(
            WorkTask.project_id,
            func.count(WorkTask.id),
            func.sum(case((WorkTask.status == "done", 1), else_=0)),
            func.sum(WorkTask.progress),
        )
        .where(
            WorkTask.tenant_id == rows[0].tenant_id,
            WorkTask.project_id.in_(list(result)),
            WorkTask.status != "canceled",
        )
        .group_by(WorkTask.project_id)
    ).all()
    for project_id, total, done, progress_sum in aggregates:
        task_total = int(total or 0)
        result[project_id] = {
            "task_total": task_total,
            "task_done": int(done or 0),
            "progress": round(float(progress_sum or 0) / task_total) if task_total else 0,
        }
    return result


DASHBOARD_DETAIL_LIMIT = 20


def dashboard_for_user(
    db: Session,
    tenant_id: str,
    user_id: str,
    *,
    access: WorkbenchAccess | None = None,
) -> dict[str, Any]:
    access = access or WorkbenchAccess.for_user(db, tenant_id, user_id)
    access.require_active_employee()
    project_predicate = _visible_project_predicate(access, tenant_id, user_id)
    visible_project_ids = select(WorkProject.id).where(project_predicate)
    project_rows = list(
        db.exec(
            select(
                WorkProject,
                func.count(WorkProject.id).over(),
                func.sum(
                    case((WorkProject.health.in_({"at_risk", "off_track"}), 1), else_=0)
                ).over(),
            )
            .where(project_predicate)
            .order_by(WorkProject.created_at, WorkProject.id)
            .limit(DASHBOARD_DETAIL_LIMIT)
        ).all()
    )
    projects = [row[0] for row in project_rows]
    project_count = int(project_rows[0][1]) if project_rows else 0
    at_risk_project_count = int(project_rows[0][2] or 0) if project_rows else 0
    progress_by_project = project_progresses(db, projects)
    project_summaries = [
        {**_project_values(project), **progress_by_project[project.id]} for project in projects
    ]

    task_conditions = (
        WorkTask.tenant_id == tenant_id,
        WorkTask.project_id.in_(visible_project_ids),
    )
    if access.can_view_all:
        review_condition = WorkTask.id.is_not(None)
    else:
        review_project_conditions = [WorkProject.owner_user_id == user_id]
        if access.managed_department_ids:
            review_project_conditions.append(
                WorkProject.department_id.in_(access.managed_department_ids)
            )
        review_project_ids = select(WorkProject.id).where(
            WorkProject.tenant_id == tenant_id,
            or_(*review_project_conditions),
        )
        review_condition = or_(
            WorkTask.reviewer_user_id == user_id,
            WorkTask.project_id.in_(review_project_ids),
        )
    task_count_rows = db.exec(
        select(
            WorkTask.status,
            func.count(WorkTask.id),
            func.sum(
                case(
                    (
                        and_(WorkTask.status == "review", review_condition),
                        1,
                    ),
                    else_=0,
                )
            ),
        )
        .where(*task_conditions)
        .group_by(WorkTask.status)
    ).all()
    task_counts = {status: int(count) for status, count, _ in task_count_rows}
    pending_review_count = sum(int(review_count or 0) for _, _, review_count in task_count_rows)

    visible_task_ids = select(WorkTask.id).where(*task_conditions)
    recent_events = list(
        db.exec(
            select(WorkTaskEvent)
            .where(
                WorkTaskEvent.tenant_id == tenant_id,
                or_(
                    WorkTaskEvent.task_id.in_(visible_task_ids),
                    WorkTaskEvent.task_id.in_(visible_project_ids),
                ),
            )
            .order_by(WorkTaskEvent.created_at.desc(), WorkTaskEvent.id.desc())
            .limit(DASHBOARD_DETAIL_LIMIT)
        ).all()
    )
    incomplete = {"blocked", "backlog", "in_progress", "review"}
    today = utc_now().date()
    at_risk_tasks = list(
        db.exec(
            select(WorkTask)
            .where(
                *task_conditions,
                WorkTask.status.in_(incomplete),
                WorkTask.due_date.is_not(None),
                WorkTask.due_date < today,
            )
            .order_by(WorkTask.due_date, WorkTask.created_at, WorkTask.id)
            .limit(DASHBOARD_DETAIL_LIMIT)
        ).all()
    )
    pending_reviews = list(
        db.exec(
            select(WorkTask)
            .where(
                *task_conditions,
                WorkTask.status == "review",
                review_condition,
            )
            .order_by(WorkTask.created_at, WorkTask.id)
            .limit(DASHBOARD_DETAIL_LIMIT)
        ).all()
    )

    employee_conditions = [
        EmployeeProfile.tenant_id == tenant_id,
        EmployeeProfile.status == "active",
    ]
    if not access.can_view_all:
        if access.managed_department_ids:
            employee_conditions.append(
                EmployeeProfile.department_id.in_(access.managed_department_ids)
            )
        else:
            employee_conditions.append(EmployeeProfile.user_id == user_id)
    employee_rows = list(
        db.exec(
            select(EmployeeProfile, func.count(EmployeeProfile.id).over())
            .where(*employee_conditions)
            .order_by(EmployeeProfile.created_at, EmployeeProfile.id)
            .limit(DASHBOARD_DETAIL_LIMIT)
        ).all()
    )
    employees = [row[0] for row in employee_rows]
    employee_count = int(employee_rows[0][1]) if employee_rows else 0
    workload_by_user: dict[str, tuple[int, float]] = {}
    if employees:
        workload_aggregates = db.exec(
            select(
                WorkTask.assignee_user_id,
                func.count(WorkTask.id),
                func.sum(WorkTask.estimate_days),
            )
            .where(
                *task_conditions,
                WorkTask.status.in_(incomplete),
                WorkTask.assignee_user_id.in_([employee.user_id for employee in employees]),
            )
            .group_by(WorkTask.assignee_user_id)
        ).all()
        workload_by_user = {
            assignee_user_id: (int(active_count), float(estimate_days or 0))
            for assignee_user_id, active_count, estimate_days in workload_aggregates
            if assignee_user_id is not None
        }
    workload_rows: list[dict[str, Any]] = []
    for employee in employees:
        active_count, estimate_days = workload_by_user.get(employee.user_id, (0, 0.0))
        workload_rows.append(
            {
                "user_id": employee.user_id,
                "department_id": employee.department_id,
                "capacity_percent": employee.capacity_percent,
                "active_task_count": active_count,
                "estimate_days": estimate_days,
            }
        )
    return {
        "tenant_id": tenant_id,
        "project_count": project_count,
        "task_counts": task_counts,
        "employee_count": employee_count,
        "pending_review_count": pending_review_count,
        "at_risk_project_count": at_risk_project_count,
        "department_loads": workload_rows,
        "workload_rows": workload_rows,
        "pending_reviews": pending_reviews,
        "at_risk_tasks": at_risk_tasks,
        "project_summaries": project_summaries,
        "recent_events": recent_events,
    }


def _project_values(project: WorkProject) -> dict[str, Any]:
    return {
        "id": project.id,
        "tenant_id": project.tenant_id,
        "name": project.name,
        "objective": project.objective,
        "description": project.description,
        "owner_user_id": project.owner_user_id,
        "department_id": project.department_id,
        "status": project.status,
        "health": project.health,
        "start_date": project.start_date,
        "due_date": project.due_date,
        "budget": project.budget,
        "version": project.version,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
    }
