from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from fastapi import HTTPException
from pydantic import ValidationError
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
from app.workbench.permissions import WorkbenchAccess, employee_for_user
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


def validate_employee_values(db: Session, tenant_id: str, values: dict[str, Any]) -> None:
    department_id = values.get("department_id")
    if department_id:
        department_for_tenant(db, tenant_id, department_id)
    for key in ("manager_user_id",):
        if values.get(key):
            user_for_tenant(db, tenant_id, values[key])
    if values.get("assistant_agent_id"):
        agent_for_tenant(db, tenant_id, values["assistant_agent_id"])


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


def update_employee(
    db: Session, employee: EmployeeProfile, values: dict[str, Any]
) -> EmployeeProfile:
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
    project = project_for_tenant(db, plan.tenant_id, plan.project_id)
    if (
        access.can_view_all
        or plan.created_by_user_id == actor_user_id
        or project.owner_user_id == actor_user_id
        or _managed_project(access, project)
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


def _visible_task(
    db: Session, access: WorkbenchAccess, task: WorkTask, project: WorkProject | None = None
) -> bool:
    if (
        access.can_view_all
        or task.assignee_user_id == access.user_id
        or task.reviewer_user_id == access.user_id
    ):
        return True
    project = project or project_for_tenant(db, access.tenant_id, task.project_id)
    return project.owner_user_id == access.user_id or _managed_project(access, project)


def ensure_task_visible(
    db: Session, access: WorkbenchAccess, task: WorkTask, project: WorkProject | None = None
) -> None:
    if not _visible_task(db, access, task, project):
        raise HTTPException(status_code=403, detail="Cannot view this task")


def _ensure_project_manager(access: WorkbenchAccess, project: WorkProject) -> None:
    if project.owner_user_id != access.user_id and not _managed_project(access, project):
        raise HTTPException(status_code=403, detail="Cannot manage this project")


def create_project(
    db: Session, tenant_id: str, values: dict[str, Any], actor_user_id: str
) -> WorkProject:
    values = dict(values)
    access = WorkbenchAccess.for_user(db, tenant_id, actor_user_id)
    department_id = values.get("department_id")
    if not access.can_manage_department(department_id):
        raise HTTPException(status_code=403, detail="Cannot create a project for this department")
    if department_id:
        department_for_tenant(db, tenant_id, department_id)
    owner_user_id = values.pop("owner_user_id", None) or actor_user_id
    user_for_tenant(db, tenant_id, owner_user_id)
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
    if values.get("department_id"):
        department_for_tenant(db, project.tenant_id, values["department_id"])
        if not access.can_manage_department(values["department_id"]):
            raise HTTPException(status_code=403, detail="Cannot move project to this department")
    if values.get("owner_user_id"):
        user_for_tenant(db, project.tenant_id, values["owner_user_id"])
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


def list_visible_projects(db: Session, tenant_id: str, user_id: str) -> list[WorkProject]:
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    projects = list(db.exec(select(WorkProject).where(WorkProject.tenant_id == tenant_id)).all())
    if access.can_view_all:
        return projects
    visible_task_project_ids = set(
        db.exec(
            select(WorkTask.project_id).where(
                WorkTask.tenant_id == tenant_id,
                (WorkTask.assignee_user_id == user_id) | (WorkTask.reviewer_user_id == user_id),
            )
        ).all()
    )
    return [
        project
        for project in projects
        if project.owner_user_id == user_id
        or project.department_id in access.managed_department_ids
        or project.id in visible_task_project_ids
    ]


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
        if values.get(key):
            user_for_tenant(db, tenant_id, values[key])
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
            db, tenant_id, project, values, dependency_ids
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
    employees = list(
        db.exec(
            select(EmployeeProfile).where(
                EmployeeProfile.tenant_id == tenant_id,
                EmployeeProfile.status == "active",
                EmployeeProfile.department_id == project.department_id,
            )
        ).all()
    )
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


def dispatch_plan(
    db: Session,
    plan_id: str,
    variant_key: str,
    idempotency_key: str,
    current_user: User,
) -> list[WorkTask]:
    plan = plan_for_tenant(db, current_user.tenant_id, plan_id)
    project = project_for_tenant(db, plan.tenant_id, plan.project_id)
    access = WorkbenchAccess.for_user(db, plan.tenant_id, current_user.id)
    _ensure_project_manager(access, project)

    if plan.status == "dispatched":
        if plan.dispatch_idempotency_key == idempotency_key:
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

    try:
        variant = PlanVariant.model_validate(
            next(item for item in plan.variants_json if item.get("key") == variant_key)
        )
    except (StopIteration, ValidationError, AttributeError) as exc:
        raise HTTPException(status_code=422, detail="Plan variant is invalid") from exc
    task_keys = {task.key for task in variant.tasks}
    if len(task_keys) != len(variant.tasks) or any(
        dependency not in task_keys for task in variant.tasks for dependency in task.depends_on
    ):
        raise HTTPException(status_code=422, detail="Plan variant dependencies are invalid")
    try:
        validate_planning_tasks(variant.tasks)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Plan variant dependencies are invalid") from exc

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
                dispatch_idempotency_key=idempotency_key,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if claim.rowcount != 1:
            db.rollback()
            latest = plan_for_tenant(db, current_user.tenant_id, plan_id)
            if latest.status == "dispatched" and latest.dispatch_idempotency_key == idempotency_key:
                return _DispatchTasks(_tasks_for_plan(db, latest), created=False)
            raise HTTPException(status_code=409, detail="Plan dispatch conflict")
        plan.status = "approved"
        plan.selected_variant = variant_key
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
                start_date=planned.start_date,
                due_date=planned.due_date,
                estimate_days=planned.estimate_days,
                acceptance_criteria=planned.acceptance_criteria or None,
            )
            db.add(row)
            db.flush()
            tasks_by_key[planned.key] = row
            _event(db, row, "task_created", current_user.id, None, row.status)
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
    if task.assignee_user_id != access.user_id and not (
        project.owner_user_id == access.user_id or _managed_project(access, project)
    ):
        raise HTTPException(
            status_code=403, detail="Only the assignee or manager can execute this task"
        )


def _ensure_reviewer(access: WorkbenchAccess, project: WorkProject, task: WorkTask) -> None:
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
    requested_status = values.get("status")
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
            raise HTTPException(
                status_code=422, detail="Task dependencies are not complete"
            )
        dependencies = _validate_task_references(
            db, task.tenant_id, project, values, dependency_ids or []
        )
        if dependency_ids is not None and (
            task.id in dependency_ids
            or _would_cycle(db, task.tenant_id, task.id, dependency_ids)
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
    if values.get("assignee_user_id") is not None:
        _event(
            db,
            task,
            "task_assigned",
            actor_user_id,
            old_status,
            task.status,
            {"assignee_user_id": task.assignee_user_id},
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


def list_visible_tasks(
    db: Session,
    tenant_id: str,
    user_id: str,
    scope: str,
    status: str | None = None,
    project_id: str | None = None,
) -> list[WorkTask]:
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
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
        project_ids = db.exec(
            select(WorkProject.id).where(
                WorkProject.tenant_id == tenant_id,
                WorkProject.department_id.in_(access.managed_department_ids),
            )
        ).all()
        statement = statement.where(WorkTask.project_id.in_(project_ids))
    elif scope == "all":
        if not access.can_view_all:
            raise HTTPException(status_code=403, detail="Cannot view all tasks")
    else:
        raise HTTPException(status_code=422, detail="Invalid task scope")
    return list(db.exec(statement.order_by(WorkTask.created_at, WorkTask.id)).all())


def dashboard_for_user(db: Session, tenant_id: str, user_id: str) -> dict[str, Any]:
    access = WorkbenchAccess.for_user(db, tenant_id, user_id)
    tenant_tasks = list(
        db.exec(select(WorkTask).where(WorkTask.tenant_id == tenant_id)).all()
    )
    tasks = [task for task in tenant_tasks if _visible_task(db, access, task)]
    if access.can_view_all:
        employees = list(
            db.exec(
                select(EmployeeProfile).where(
                    EmployeeProfile.tenant_id == tenant_id,
                    EmployeeProfile.status == "active",
                )
            ).all()
        )
    elif access.managed_department_ids:
        employees = list(
            db.exec(
                select(EmployeeProfile).where(
                    EmployeeProfile.tenant_id == tenant_id,
                    EmployeeProfile.status == "active",
                    EmployeeProfile.department_id.in_(access.managed_department_ids),
                )
            ).all()
        )
    else:
        profile = employee_for_user(db, tenant_id, user_id)
        employees = [profile] if profile and profile.status == "active" else []

    projects = list_visible_projects(db, tenant_id, user_id)
    project_summaries = [
        {**_project_values(project), **project_progress(db, project)} for project in projects
    ]
    task_counts: dict[str, int] = {}
    for task in tasks:
        task_counts[task.status] = task_counts.get(task.status, 0) + 1
    visible_task_ids = {task.id for task in tasks}
    visible_event_ids = visible_task_ids | {project.id for project in projects}
    recent_events = (
        list(
            db.exec(
                select(WorkTaskEvent)
                .where(
                    WorkTaskEvent.tenant_id == tenant_id,
                    WorkTaskEvent.task_id.in_(visible_event_ids),
                )
                .order_by(WorkTaskEvent.created_at.desc(), WorkTaskEvent.id.desc())
                .limit(20)
            ).all()
        )
        if visible_event_ids
        else []
    )
    incomplete = {"blocked", "backlog", "in_progress", "review"}
    today = utc_now().date()
    at_risk_tasks = [
        task
        for task in tasks
        if task.status in incomplete and task.due_date and task.due_date < today
    ]
    pending_reviews = [
        task
        for task in tasks
        if task.status == "review"
        and (
            access.can_view_all
            or task.reviewer_user_id == user_id
            or (
                project_for_tenant(db, tenant_id, task.project_id).owner_user_id == user_id
            )
            or (
                project_for_tenant(db, tenant_id, task.project_id).department_id
                in access.managed_department_ids
            )
        )
    ]
    workload_rows: list[dict[str, Any]] = []
    for employee in employees:
        active = [
            task
            for task in tasks
            if task.assignee_user_id == employee.user_id and task.status in incomplete
        ]
        workload_rows.append(
            {
                "user_id": employee.user_id,
                "department_id": employee.department_id,
                "capacity_percent": employee.capacity_percent,
                "active_task_count": len(active),
                "estimate_days": sum(task.estimate_days or 0 for task in active),
            }
        )
    return {
        "tenant_id": tenant_id,
        "project_count": len(projects),
        "task_counts": task_counts,
        "employee_count": len(employees),
        "pending_review_count": len(pending_reviews),
        "at_risk_project_count": sum(
            project.health in {"at_risk", "off_track"} for project in projects
        ),
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
