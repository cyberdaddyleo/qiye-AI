# FastAPI's dependency declarations intentionally use call expressions as defaults.
# ruff: noqa: B008
from __future__ import annotations

import base64
import secrets
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session, select

from app.db import get_session
from app.db.models import (
    AgentProfile,
    Department,
    EmployeeProfile,
    User,
    UserAvatar,
    WorkPlan,
    WorkProject,
    WorkTask,
    WorkTaskEvent,
    utc_now,
)
from app.security.auth import ensure_current_user_tenant, get_current_user, hash_password
from app.security.tenant import ensure_tenant
from app.workbench.importer import (
    EmployeeImportArchiveLimit,
    EmployeeImportRow,
    EmployeeImportTooManyRows,
    parse_employee_upload,
)
from app.workbench.permissions import (
    WorkbenchAccess,
    can_manage_employee,
    can_view_employee,
    can_view_employee_sensitive,
    project_colleague_user_ids,
    require_global_manager,
)
from app.workbench.schema import (
    PlanDispatchTask,
    PlanPreviewRequest,
    PlanRead,
    TaskRead,
    TaskReviewRequest,
    WorkbenchAccessRead,
    WorkTaskEventRead,
)
from app.workbench.service import (
    active_employee_for_user,
    add_task_comment,
    build_plan,
    create_employee,
    create_project,
    create_task,
    dashboard_for_user,
    delete_employee,
    department_for_tenant,
    dispatch_plan,
    employee_for_tenant,
    ensure_task_visible,
    list_visible_projects,
    list_visible_tasks,
    plan_for_tenant,
    plan_values_for_user,
    project_for_tenant,
    project_progress,
    project_progresses,
    review_task,
    submit_task,
    task_dependencies,
    task_dependencies_bulk,
    task_events,
    task_events_bulk,
    task_for_tenant,
    update_department,
    update_employee,
    update_project,
    update_task,
    user_for_tenant,
)

router = APIRouter(prefix="/api/enterprise/workbench", tags=["enterprise:workbench"])
MAX_IMPORT_BYTES = 5 * 1024 * 1024
MAX_IMPORT_ROWS = 2_000


class DepartmentCreate(BaseModel):
    tenant_id: str
    name: str = Field(min_length=1, max_length=120)
    code: str = Field(min_length=1, max_length=40)
    parent_id: str | None = None
    manager_user_id: str | None = None


class DepartmentUpdate(BaseModel):
    tenant_id: str
    name: str | None = Field(default=None, min_length=1, max_length=120)
    code: str | None = Field(default=None, min_length=1, max_length=40)
    parent_id: str | None = None
    manager_user_id: str | None = None
    status: Literal["active", "archived"] | None = None


class EmployeeCreate(BaseModel):
    tenant_id: str
    user_id: str
    employee_no: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    business_role: Literal["ceo", "manager", "member"] = "member"
    level: str | None = None
    skills: list[str] = Field(default_factory=list)
    capacity_percent: int = Field(default=100, ge=0, le=100)
    daily_cost: float | None = Field(default=None, ge=0)
    manager_user_id: str | None = None
    assistant_agent_id: str | None = None


class EmployeeUpdate(BaseModel):
    tenant_id: str
    employee_no: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    business_role: Literal["ceo", "manager", "member"] | None = None
    level: str | None = None
    skills: list[str] | None = None
    capacity_percent: int | None = Field(default=None, ge=0, le=100)
    daily_cost: float | None = Field(default=None, ge=0)
    manager_user_id: str | None = None
    assistant_agent_id: str | None = None
    status: Literal["active", "inactive"] | None = None


class ProjectCreate(BaseModel):
    tenant_id: str
    name: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4_000)
    description: str | None = Field(default=None, max_length=10_000)
    owner_user_id: str | None = None
    department_id: str
    status: Literal["active", "on_hold", "completed", "archived"] = "active"
    health: Literal["on_track", "at_risk", "off_track"] = "on_track"
    start_date: date | None = None
    due_date: date | None = None
    budget: float | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")


class ProjectUpdate(BaseModel):
    tenant_id: str
    version: int
    name: str | None = Field(default=None, min_length=1, max_length=200)
    objective: str | None = Field(default=None, min_length=1, max_length=4_000)
    description: str | None = Field(default=None, max_length=10_000)
    owner_user_id: str | None = None
    department_id: str | None = None
    status: Literal["active", "on_hold", "completed", "archived"] | None = None
    health: Literal["on_track", "at_risk", "off_track"] | None = None
    start_date: date | None = None
    due_date: date | None = None
    budget: float | None = Field(default=None, ge=0)

    model_config = ConfigDict(extra="forbid")

    @field_validator("name", "objective", "status", "health", mode="before")
    @classmethod
    def reject_null_required_fields(cls, value: object) -> object:
        if value is None:
            raise ValueError("field cannot be null")
        return value


class TaskCreate(BaseModel):
    tenant_id: str
    project_id: str
    plan_id: str | None = None
    parent_task_id: str | None = None
    title: str = Field(min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10_000)
    required_role: str | None = None
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    status: Literal["backlog", "blocked"] = "backlog"
    assignee_user_id: str | None = None
    reviewer_user_id: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate_days: float | None = Field(default=None, ge=0)
    acceptance_criteria: str | None = None
    dependencies: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class TaskMutation(BaseModel):
    tenant_id: str
    version: int
    title: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = Field(default=None, max_length=10_000)
    priority: Literal["low", "normal", "high", "urgent"] | None = None
    status: Literal["backlog", "blocked", "in_progress", "review", "done", "canceled"] | None = None
    assignee_user_id: str | None = None
    reviewer_user_id: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate_days: float | None = Field(default=None, ge=0)
    progress: int | None = Field(default=None, ge=0, le=100)
    acceptance_criteria: str | None = None
    dependencies: list[str] | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("title", "priority", "status", "progress", "dependencies", mode="before")
    @classmethod
    def reject_null_required_fields(cls, value: object) -> object:
        if value is None:
            raise ValueError("field cannot be null")
        return value


class TaskComment(BaseModel):
    tenant_id: str
    version: int
    comment: str = Field(min_length=1, max_length=10_000)

    model_config = ConfigDict(extra="forbid")


class TaskSubmit(BaseModel):
    tenant_id: str
    version: int
    result_summary: str = Field(min_length=1, max_length=20_000)
    artifact_refs: list[str] = Field(default_factory=list, max_length=100)

    model_config = ConfigDict(extra="forbid")


class PlanDispatchRequest(BaseModel):
    tenant_id: str
    variant_key: Literal["A", "B", "C"]
    idempotency_key: str = Field(min_length=1, max_length=200)
    tasks: list[PlanDispatchTask] = Field(min_length=1, max_length=100)

    model_config = ConfigDict(extra="forbid")


class DepartmentResponse(BaseModel):
    id: str
    tenant_id: str
    name: str
    code: str
    parent_id: str | None
    manager_user_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


class EmployeeResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    username: str
    display_name: str | None
    avatar_url: str | None = None
    employee_no: str | None
    department_id: str | None
    job_title: str | None
    business_role: str
    level: str | None
    skills: list[str]
    capacity_percent: int
    daily_cost: float | None
    manager_user_id: str | None
    assistant_agent_id: str | None
    status: str
    created_at: datetime
    updated_at: datetime


def _department_response(row: Department) -> DepartmentResponse:
    return DepartmentResponse.model_validate(row, from_attributes=True)


def _employee_response(
    db: Session,
    row: EmployeeProfile,
    *,
    restricted: bool = False,
) -> EmployeeResponse:
    user = user_for_tenant(db, row.tenant_id, row.user_id)
    avatar = db.get(UserAvatar, user.id)
    return EmployeeResponse(
        id=row.id,
        tenant_id=row.tenant_id,
        user_id=row.user_id,
        username=user.username,
        display_name=user.display_name,
        avatar_url=(
            f"/api/enterprise/workbench/employees/{row.id}/avatar?tenant_id={row.tenant_id}"
            if avatar
            else None
        ),
        employee_no=None if restricted else row.employee_no,
        department_id=row.department_id,
        job_title=row.job_title,
        business_role=row.business_role,
        level=None if restricted else row.level,
        skills=[] if restricted else list(row.skills_json or []),
        capacity_percent=0 if restricted else row.capacity_percent,
        daily_cost=None if restricted else row.daily_cost,
        manager_user_id=None if restricted else row.manager_user_id,
        assistant_agent_id=None if restricted else row.assistant_agent_id,
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _event_response(row: WorkTaskEvent) -> WorkTaskEventRead:
    return WorkTaskEventRead(
        id=row.id,
        task_id=row.task_id,
        tenant_id=row.tenant_id,
        actor_user_id=row.actor_user_id,
        actor_type=row.actor_type,
        event_type=row.event_type,
        payload=row.payload_json,
        created_at=row.created_at,
    )


def _task_response(
    db: Session,
    row: WorkTask,
    *,
    dependencies: list[str] | None = None,
    events: list[WorkTaskEvent] | None = None,
) -> TaskRead:
    values = row.model_dump()
    values["dependencies"] = (
        task_dependencies(db, row) if dependencies is None else dependencies
    )
    values["events"] = [
        _event_response(event)
        for event in (task_events(db, row) if events is None else events)
    ]
    return TaskRead.model_validate(values)


def _task_responses(db: Session, rows: list[WorkTask]) -> list[TaskRead]:
    dependencies = task_dependencies_bulk(db, rows)
    events = task_events_bulk(db, rows)
    return [
        _task_response(
            db,
            row,
            dependencies=dependencies[row.id],
            events=events[row.id],
        )
        for row in rows
    ]


def _plan_response(db: Session, row: WorkPlan, actor_user_id: str) -> PlanRead:
    values = plan_values_for_user(db, row, actor_user_id)
    return PlanRead.model_validate(values, from_attributes=True)


def _project_response(db: Session, row: WorkProject) -> dict[str, object]:
    return {**row.model_dump(), **project_progress(db, row)}


def _project_responses(
    db: Session,
    rows: list[WorkProject],
) -> list[dict[str, object]]:
    progress = project_progresses(db, rows)
    return [{**row.model_dump(), **progress[row.id]} for row in rows]


def _access(db: Session, tenant_id: str, user: User) -> WorkbenchAccess:
    ensure_tenant(db, tenant_id)
    ensure_current_user_tenant(tenant_id, user)
    return WorkbenchAccess.for_user(db, tenant_id, user.id)


def _ensure_department_manage(access: WorkbenchAccess, department_id: str | None) -> None:
    if not access.can_manage_department(department_id):
        raise HTTPException(status_code=403, detail="Cannot manage this department")


def _ensure_global_role_assignment(access: WorkbenchAccess, business_role: str | None) -> None:
    if business_role == "ceo" and not access.can_manage_organization:
        raise HTTPException(
            status_code=403, detail="Only administrator or CEO can grant global employee roles"
        )


@router.get("/access", response_model=WorkbenchAccessRead)
def get_access_endpoint(
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> WorkbenchAccessRead:
    access = _access(db, tenant_id, current_user)
    return WorkbenchAccessRead(
        tenant_id=tenant_id,
        user_id=current_user.id,
        business_role=access.business_role,
        directory_scope=access.directory_scope,
        can_create_project=access.can_create_project,
        can_view_all=access.can_view_all,
        managed_department_ids=sorted(access.managed_department_ids),
    )


@router.post("/projects", status_code=201)
def create_project_endpoint(
    request: ProjectCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    _access(db, request.tenant_id, current_user)
    values = request.model_dump(exclude={"tenant_id"})
    row = create_project(db, request.tenant_id, values, current_user.id)
    return _project_response(db, row)


@router.get("/projects")
def list_projects_endpoint(
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[dict[str, object]]:
    _access(db, tenant_id, current_user)
    rows = list_visible_projects(db, tenant_id, current_user.id)
    return _project_responses(db, rows)


@router.get("/projects/{project_id}")
def get_project_endpoint(
    project_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    _access(db, tenant_id, current_user)
    row = project_for_tenant(db, tenant_id, project_id)
    visible_ids = {project.id for project in list_visible_projects(db, tenant_id, current_user.id)}
    if row.id not in visible_ids:
        raise HTTPException(status_code=403, detail="Cannot view this project")
    return _project_response(db, row)


@router.put("/projects/{project_id}")
def update_project_endpoint(
    project_id: str,
    request: ProjectUpdate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    _access(db, request.tenant_id, current_user)
    row = project_for_tenant(db, request.tenant_id, project_id)
    values = request.model_dump(exclude_unset=True, exclude={"tenant_id", "version"})
    return _project_response(
        db,
        update_project(db, row, values, request.version, current_user.id),
    )


@router.post("/plans/preview", response_model=PlanRead, status_code=201)
def preview_plan_endpoint(
    request: PlanPreviewRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PlanRead:
    _access(db, request.tenant_id, current_user)
    return _plan_response(db, build_plan(db, request, current_user), current_user.id)


@router.get("/plans/{plan_id}", response_model=PlanRead)
def get_plan_endpoint(
    plan_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> PlanRead:
    _access(db, tenant_id, current_user)
    row = plan_for_tenant(db, tenant_id, plan_id)
    return _plan_response(db, row, current_user.id)


@router.post("/plans/{plan_id}/dispatch", response_model=list[TaskRead], status_code=201)
def dispatch_plan_endpoint(
    plan_id: str,
    request: PlanDispatchRequest,
    response: Response,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[TaskRead]:
    _access(db, request.tenant_id, current_user)
    plan_for_tenant(db, request.tenant_id, plan_id)
    rows = dispatch_plan(
        db,
        plan_id,
        request.variant_key,
        request.idempotency_key,
        current_user,
        request.tasks,
    )
    if not getattr(rows, "created", False):
        response.status_code = 200
    return _task_responses(db, list(rows))


@router.post("/tasks", response_model=TaskRead, status_code=201)
def create_task_endpoint(
    request: TaskCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskRead:
    _access(db, request.tenant_id, current_user)
    row = create_task(
        db,
        request.tenant_id,
        request.model_dump(exclude={"tenant_id"}),
        current_user.id,
    )
    return _task_response(db, row)


@router.get("/tasks", response_model=list[TaskRead])
def list_tasks_endpoint(
    tenant_id: str = Query(...),
    scope: Literal["mine", "department", "all"] = Query("mine"),
    status: Literal["backlog", "blocked", "in_progress", "review", "done", "canceled"]
    | None = Query(None),
    project_id: str | None = Query(None),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[TaskRead]:
    _access(db, tenant_id, current_user)
    rows = list_visible_tasks(
        db,
        tenant_id,
        current_user.id,
        scope,
        status=status,
        project_id=project_id,
        limit=limit,
        offset=offset,
    )
    return _task_responses(db, rows)


@router.get("/tasks/{task_id}", response_model=TaskRead)
def get_task_endpoint(
    task_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskRead:
    access = _access(db, tenant_id, current_user)
    row = task_for_tenant(db, tenant_id, task_id)
    ensure_task_visible(db, access, row)
    return _task_response(db, row)


@router.put("/tasks/{task_id}", response_model=TaskRead)
def update_task_endpoint(
    task_id: str,
    request: TaskMutation,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskRead:
    _access(db, request.tenant_id, current_user)
    row = task_for_tenant(db, request.tenant_id, task_id)
    values = request.model_dump(exclude_unset=True, exclude={"tenant_id", "version"})
    return _task_response(db, update_task(db, row, values, request.version, current_user.id))


@router.post("/tasks/{task_id}/comments", response_model=TaskRead)
def comment_task_endpoint(
    task_id: str,
    request: TaskComment,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskRead:
    _access(db, request.tenant_id, current_user)
    row = task_for_tenant(db, request.tenant_id, task_id)
    return _task_response(
        db, add_task_comment(db, row, request.comment, request.version, current_user.id)
    )


@router.post("/tasks/{task_id}/submit", response_model=TaskRead)
def submit_task_endpoint(
    task_id: str,
    request: TaskSubmit,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskRead:
    _access(db, request.tenant_id, current_user)
    row = task_for_tenant(db, request.tenant_id, task_id)
    return _task_response(
        db,
        submit_task(
            db,
            row,
            request.version,
            request.result_summary,
            request.artifact_refs,
            current_user.id,
        ),
    )


@router.post("/tasks/{task_id}/review", response_model=TaskRead)
def review_task_endpoint(
    task_id: str,
    request: TaskReviewRequest,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> TaskRead:
    _access(db, request.tenant_id, current_user)
    row = task_for_tenant(db, request.tenant_id, task_id)
    return _task_response(
        db,
        review_task(
            db,
            row,
            request.version,
            request.verdict,
            request.comment,
            current_user.id,
        ),
    )


@router.get("/dashboard")
def dashboard_endpoint(
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    _access(db, tenant_id, current_user)
    data = dashboard_for_user(db, tenant_id, current_user.id)
    pending_reviews = list(data["pending_reviews"])
    at_risk_tasks = list(data["at_risk_tasks"])
    detail_rows = list({row.id: row for row in [*pending_reviews, *at_risk_tasks]}.values())
    detail_by_id = {row.id: detail for row, detail in zip(detail_rows, _task_responses(db, detail_rows))}
    data["pending_reviews"] = [detail_by_id[row.id].model_dump() for row in pending_reviews]
    data["at_risk_tasks"] = [detail_by_id[row.id].model_dump() for row in at_risk_tasks]
    data["recent_events"] = [_event_response(row).model_dump() for row in data["recent_events"]]
    return data


@router.post("/departments", response_model=DepartmentResponse, status_code=201)
def create_department_endpoint(
    request: DepartmentCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DepartmentResponse:
    require_global_manager(db, request.tenant_id, current_user.id)
    if request.parent_id:
        department_for_tenant(db, request.tenant_id, request.parent_id)
    if request.manager_user_id:
        active_employee_for_user(
            db,
            request.tenant_id,
            request.manager_user_id,
            label="Department manager",
        )
        raise HTTPException(
            status_code=422,
            detail="Create the department before assigning its manager",
        )
    row = Department(**request.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return _department_response(row)


@router.get("/departments", response_model=list[DepartmentResponse])
def list_departments(
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[DepartmentResponse]:
    access = _access(db, tenant_id, current_user)
    if access.can_view_all:
        rows = db.exec(select(Department).where(Department.tenant_id == tenant_id)).all()
    elif access.managed_department_ids:
        rows = db.exec(
            select(Department).where(
                Department.tenant_id == tenant_id, Department.id.in_(access.managed_department_ids)
            )
        ).all()
    else:
        raise HTTPException(status_code=403, detail="Cannot view departments")
    return [_department_response(row) for row in rows]


@router.get("/departments/{department_id}", response_model=DepartmentResponse)
def get_department(
    department_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DepartmentResponse:
    access = _access(db, tenant_id, current_user)
    row = department_for_tenant(db, tenant_id, department_id)
    if not access.can_manage_department(row.id):
        raise HTTPException(status_code=403, detail="Cannot view this department")
    return _department_response(row)


@router.patch("/departments/{department_id}", response_model=DepartmentResponse)
def update_department_endpoint(
    department_id: str,
    request: DepartmentUpdate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> DepartmentResponse:
    access = _access(db, request.tenant_id, current_user)
    row = department_for_tenant(db, request.tenant_id, department_id)
    _ensure_department_manage(access, row.id)
    values = request.model_dump(exclude_unset=True, exclude={"tenant_id"})
    if values.get("parent_id"):
        department_for_tenant(db, request.tenant_id, values["parent_id"])
    return _department_response(update_department(db, row, values))


@router.delete("/departments/{department_id}", status_code=204)
def delete_department_endpoint(
    department_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    require_global_manager(db, tenant_id, current_user.id)
    row = department_for_tenant(db, tenant_id, department_id)
    update_department(db, row, {"status": "archived"})
    return Response(status_code=204)


@router.post("/employees", response_model=EmployeeResponse, status_code=201)
def create_employee_endpoint(
    request: EmployeeCreate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> EmployeeResponse:
    access = _access(db, request.tenant_id, current_user)
    _ensure_department_manage(access, request.department_id)
    _ensure_global_role_assignment(access, request.business_role)
    values = request.model_dump(exclude={"tenant_id", "skills"})
    values["skills_json"] = request.skills
    row = create_employee(db, request.tenant_id, values)
    return _employee_response(db, row)


@router.get("/employees", response_model=list[EmployeeResponse])
def list_employees(
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> list[EmployeeResponse]:
    access = _access(db, tenant_id, current_user)
    if access.can_view_all:
        rows = db.exec(select(EmployeeProfile).where(EmployeeProfile.tenant_id == tenant_id)).all()
    elif access.managed_department_ids:
        rows = db.exec(
            select(EmployeeProfile).where(
                EmployeeProfile.tenant_id == tenant_id,
                EmployeeProfile.department_id.in_(access.managed_department_ids),
            )
        ).all()
    else:
        colleague_ids = project_colleague_user_ids(db, tenant_id, current_user.id)
        if not colleague_ids:
            raise HTTPException(status_code=403, detail="Cannot list employees")
        rows = db.exec(
            select(EmployeeProfile).where(
                EmployeeProfile.tenant_id == tenant_id,
                EmployeeProfile.status == "active",
                EmployeeProfile.user_id.in_(colleague_ids),
            )
        ).all()
    can_view_sensitive = access.can_manage_organization
    return [
        _employee_response(
            db,
            row,
            restricted=not (
                can_view_sensitive
                or row.user_id == current_user.id
                or row.department_id in access.managed_department_ids
            ),
        )
        for row in rows
    ]


@router.get("/employees/{employee_id}", response_model=EmployeeResponse)
def get_employee(
    employee_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> EmployeeResponse:
    _access(db, tenant_id, current_user)
    row = employee_for_tenant(db, tenant_id, employee_id)
    if not can_view_employee(db, tenant_id, current_user.id, row):
        raise HTTPException(status_code=403, detail="Cannot view this employee")
    return _employee_response(
        db,
        row,
        restricted=not can_view_employee_sensitive(
            db,
            tenant_id,
            current_user.id,
            row,
        ),
    )


@router.get("/employees/{employee_id}/avatar")
def get_employee_avatar(
    employee_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    _access(db, tenant_id, current_user)
    employee = employee_for_tenant(db, tenant_id, employee_id)
    if not can_view_employee(db, tenant_id, current_user.id, employee):
        raise HTTPException(status_code=403, detail="Cannot view this employee")
    avatar = db.get(UserAvatar, employee.user_id)
    if avatar is None:
        raise HTTPException(status_code=404, detail="Avatar not found")
    try:
        meta, encoded = avatar.data_url.split(",", 1)
        content_type = meta.removeprefix("data:").removesuffix(";base64")
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=404, detail="Avatar not found") from exc
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=404, detail="Avatar not found")
    return Response(
        content=data, media_type=content_type, headers={"Cache-Control": "private, no-cache"}
    )


@router.patch("/employees/{employee_id}", response_model=EmployeeResponse)
def update_employee_endpoint(
    employee_id: str,
    request: EmployeeUpdate,
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> EmployeeResponse:
    _access(db, request.tenant_id, current_user)
    row = employee_for_tenant(db, request.tenant_id, employee_id)
    if not can_manage_employee(db, request.tenant_id, current_user.id, row):
        raise HTTPException(status_code=403, detail="Cannot manage this employee")
    _ensure_global_role_assignment(
        WorkbenchAccess.for_user(db, request.tenant_id, current_user.id), request.business_role
    )
    values = request.model_dump(exclude_unset=True, exclude={"tenant_id", "skills"})
    if request.skills is not None:
        values["skills_json"] = request.skills
    if "department_id" in values:
        access = WorkbenchAccess.for_user(db, request.tenant_id, current_user.id)
        _ensure_department_manage(access, values["department_id"])
    return _employee_response(db, update_employee(db, row, values))


@router.delete("/employees/{employee_id}", status_code=204)
def delete_employee_endpoint(
    employee_id: str,
    tenant_id: str = Query(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> Response:
    _access(db, tenant_id, current_user)
    row = employee_for_tenant(db, tenant_id, employee_id)
    if not can_manage_employee(db, tenant_id, current_user.id, row):
        raise HTTPException(status_code=403, detail="Cannot manage this employee")
    delete_employee(db, row)
    return Response(status_code=204)


@router.post("/employees/import")
async def import_employees(
    tenant_id: str = Query(...),
    file: UploadFile = File(...),
    db: Session = Depends(get_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, object]:
    require_global_manager(db, tenant_id, current_user.id)
    content = await file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(status_code=413, detail="Import file exceeds 5 MiB")
    try:
        parsed = parse_employee_upload(file.filename or "", content)
    except EmployeeImportArchiveLimit as exc:
        raise HTTPException(
            status_code=413, detail="XLSX archive exceeds import safety limits"
        ) from exc
    except EmployeeImportTooManyRows as exc:
        raise HTTPException(status_code=413, detail="Import contains more than 2,000 rows") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rows = parsed.rows

    created = 0
    updated = 0
    errors: list[dict[str, object]] = [
        {"row": error.row_number, "code": error.code, "message": error.message}
        for error in parsed.errors
    ]
    results: list[dict[str, object]] = []
    for row in rows:
        error = _import_row_error(db, tenant_id, row)
        if error:
            errors.append({"row": row.row_number, **error})
            continue
        department = db.exec(
            select(Department).where(
                Department.tenant_id == tenant_id,
                Department.name == row.department,
                Department.status == "active",
            )
        ).first()
        assert department is not None
        manager = (
            _user_by_username(db, tenant_id, row.manager_username) if row.manager_username else None
        )
        user = _user_by_username(db, tenant_id, row.username)
        generated_password: str | None = None
        if user is None:
            generated_password = secrets.token_urlsafe(18)
            user = User(
                tenant_id=tenant_id,
                username=row.username,
                display_name=row.display_name,
                role="member",
                password_hash=hash_password(generated_password),
            )
            db.add(user)
            db.flush()
        else:
            user.display_name = row.display_name
            user.updated_at = utc_now()
            db.add(user)

        profile = db.exec(
            select(EmployeeProfile).where(
                EmployeeProfile.tenant_id == tenant_id, EmployeeProfile.user_id == user.id
            )
        ).first()
        values = _import_profile_values(row, department.id, manager.id if manager else None)
        if profile is None:
            profile = EmployeeProfile(tenant_id=tenant_id, user_id=user.id, **values)
            db.add(profile)
            created += 1
            result: dict[str, object] = {
                "row": row.row_number,
                "username": row.username,
                "status": "created",
            }
            if generated_password:
                result["password"] = generated_password
        else:
            for key, value in values.items():
                if value is not None:
                    setattr(profile, key, value)
            profile.updated_at = utc_now()
            db.add(profile)
            updated += 1
            result = {"row": row.row_number, "username": row.username, "status": "updated"}
        db.commit()
        results.append(result)
    return {"created": created, "updated": updated, "errors": errors, "results": results}


def _user_by_username(db: Session, tenant_id: str, username: str | None) -> User | None:
    if not username:
        return None
    return db.exec(
        select(User).where(User.tenant_id == tenant_id, User.username == username)
    ).first()


def _import_row_error(db: Session, tenant_id: str, row: EmployeeImportRow) -> dict[str, str] | None:
    department = db.exec(
        select(Department).where(
            Department.tenant_id == tenant_id,
            Department.name == row.department,
            Department.status == "active",
        )
    ).first()
    if department is None:
        return {"code": "unknown_department", "message": "部门不存在"}
    if row.business_role == "admin":
        return {"code": "invalid_business_role", "message": "business_role is invalid"}
    user = _user_by_username(db, tenant_id, row.username)
    if row.business_role == "manager" and (
        user is None or department.manager_user_id != user.id
    ):
        return {
            "code": "manager_scope_required",
            "message": "manager role requires department management",
        }
    if user is not None:
        managed_department_ids = set(
            db.exec(
                select(Department.id).where(
                    Department.tenant_id == tenant_id,
                    Department.status == "active",
                    Department.manager_user_id == user.id,
                )
            ).all()
        )
        if managed_department_ids and (
            "business_role" in row.provided_fields
            and row.business_role != "manager"
        ):
            return {
                "code": "manager_role_required",
                "message": "department manager must retain manager role",
            }
        if managed_department_ids and department.id not in managed_department_ids:
            return {
                "code": "manager_department_required",
                "message": "department manager must remain in a managed department",
            }
    if row.manager_username and _user_by_username(db, tenant_id, row.manager_username) is None:
        return {"code": "unknown_manager", "message": "负责人账号不存在"}
    if row.assistant_agent_id:
        assistant = db.get(AgentProfile, row.assistant_agent_id)
        if assistant is None or assistant.tenant_id != tenant_id:
            return {"code": "unknown_assistant_agent", "message": "助理智能体不存在"}
    return None


def _import_profile_values(
    row: EmployeeImportRow, department_id: str, manager_user_id: str | None
) -> dict[str, object]:
    values: dict[str, object] = {"department_id": department_id}
    optional_values = {
        "employee_no": row.employee_no,
        "job_title": row.job_title,
        "business_role": row.business_role,
        "level": row.level,
        "skills_json": row.skills,
        "capacity_percent": row.capacity_percent,
        "daily_cost": row.daily_cost,
        "manager_user_id": manager_user_id,
        "assistant_agent_id": row.assistant_agent_id,
    }
    for field, value in optional_values.items():
        input_field = "skills" if field == "skills_json" else field
        if input_field in row.provided_fields and value is not None:
            values[field] = value
    return values
