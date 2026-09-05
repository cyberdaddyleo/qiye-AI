from __future__ import annotations

import json
import math
import re
from datetime import date, datetime
from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator

BusinessRole = Literal["admin", "ceo", "manager", "member"]
DirectoryScope = Literal["all", "department", "self"]
DepartmentStatus = Literal["active", "archived"]
EmployeeStatus = Literal["active", "inactive"]
ProjectStatus = Literal["active", "on_hold", "completed", "archived"]
ProjectHealth = Literal["on_track", "at_risk", "off_track"]
PlanStatus = Literal["draft", "approved", "dispatched", "failed"]
PlanSource = Literal["model", "fallback"]
TaskStatus = Literal["backlog", "blocked", "in_progress", "review", "done", "canceled"]
TaskPriority = Literal["low", "normal", "high", "urgent"]
ReviewVerdict = Literal["approve", "rework"]

_PLAN_GOAL_MAX_LENGTH = 4_000
_PLAN_CONSTRAINTS_MAX_BYTES = 2_000
_PLAN_CONSTRAINTS_MAX_DEPTH = 8
_PLAN_CONSTRAINTS_MAX_KEYS = 100
_PLAN_CONSTRAINTS_MAX_LIST_LENGTH = 100


def _validate_plan_constraint_value(
    value: Any,
    *,
    depth: int,
    key_count: list[int],
) -> None:
    if isinstance(value, dict):
        if depth > _PLAN_CONSTRAINTS_MAX_DEPTH:
            raise ValueError(
                f"constraints nesting must not exceed {_PLAN_CONSTRAINTS_MAX_DEPTH} levels"
            )
        key_count[0] += len(value)
        if key_count[0] > _PLAN_CONSTRAINTS_MAX_KEYS:
            raise ValueError(
                f"constraints must not contain more than {_PLAN_CONSTRAINTS_MAX_KEYS} keys"
            )
        for nested in value.values():
            _validate_plan_constraint_value(
                nested,
                depth=depth + 1,
                key_count=key_count,
            )
        return

    if isinstance(value, list):
        if depth > _PLAN_CONSTRAINTS_MAX_DEPTH:
            raise ValueError(
                f"constraints nesting must not exceed {_PLAN_CONSTRAINTS_MAX_DEPTH} levels"
            )
        if len(value) > _PLAN_CONSTRAINTS_MAX_LIST_LENGTH:
            raise ValueError(
                "constraint lists must not contain more than "
                f"{_PLAN_CONSTRAINTS_MAX_LIST_LENGTH} items"
            )
        for nested in value:
            _validate_plan_constraint_value(
                nested,
                depth=depth + 1,
                key_count=key_count,
            )
        return

    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("constraints must contain only finite numbers")
    if value is not None and not isinstance(value, (str, int, float, bool)):
        raise ValueError("constraints must contain only JSON-compatible values")


class WorkbenchAccessRead(BaseModel):
    tenant_id: str
    user_id: str
    business_role: BusinessRole
    directory_scope: DirectoryScope
    can_create_project: bool
    can_view_all: bool
    managed_department_ids: list[str] = Field(default_factory=list)


class DepartmentRead(BaseModel):
    id: str
    tenant_id: str
    name: str
    code: str
    parent_id: str | None = None
    manager_user_id: str | None = None
    status: DepartmentStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class EmployeeRead(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    employee_no: str | None = None
    department_id: str | None = None
    job_title: str | None = None
    business_role: BusinessRole
    level: str | None = None
    skills: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("skills", "skills_json")
    )
    capacity_percent: int
    daily_cost: float | None = None
    manager_user_id: str | None = None
    assistant_agent_id: str | None = None
    status: EmployeeStatus
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class ProjectRead(BaseModel):
    id: str
    tenant_id: str
    name: str
    objective: str
    description: str | None = None
    owner_user_id: str | None = None
    department_id: str | None = None
    status: ProjectStatus
    health: ProjectHealth
    start_date: date | None = None
    due_date: date | None = None
    budget: float | None = None
    version: int
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlanPreviewRequest(BaseModel):
    tenant_id: str
    project_id: str
    goal: str | None = Field(
        default=None,
        min_length=1,
        max_length=_PLAN_GOAL_MAX_LENGTH,
    )
    deadline: date | None = None
    budget: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    constraints: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")

    @field_validator("goal", mode="before")
    @classmethod
    def strip_goal(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("constraints")
    @classmethod
    def validate_constraints(cls, value: dict[str, Any]) -> dict[str, Any]:
        _validate_plan_constraint_value(value, depth=1, key_count=[0])
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        except (OverflowError, TypeError, ValueError) as exc:
            raise ValueError("constraints must be JSON serializable") from exc
        if len(encoded) > _PLAN_CONSTRAINTS_MAX_BYTES:
            raise ValueError(
                f"constraints JSON must not exceed {_PLAN_CONSTRAINTS_MAX_BYTES} UTF-8 bytes"
            )
        return value


class PlanDispatchTask(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    assignee_user_id: str | None
    start_date: date | None
    due_date: date | None
    acceptance_criteria: str = Field(min_length=1, max_length=10_000)
    depends_on: list[str] = Field(max_length=40)

    model_config = ConfigDict(extra="forbid")

    @field_validator("key", "acceptance_criteria", mode="before")
    @classmethod
    def strip_dispatch_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class WorkTaskEventRead(BaseModel):
    id: str
    task_id: str
    tenant_id: str
    actor_user_id: str | None = None
    actor_type: str
    event_type: str
    payload: dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("payload", "payload_json")
    )
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class PlanRead(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    created_by_user_id: str
    goal: str
    deadline: date | None = None
    budget: float | None = None
    constraints: dict[str, Any] = Field(
        default_factory=dict, validation_alias=AliasChoices("constraints", "constraints_json")
    )
    status: PlanStatus
    source: PlanSource
    variants: list[dict[str, Any]] = Field(
        default_factory=list, validation_alias=AliasChoices("variants", "variants_json")
    )
    selected_variant: str | None = None
    selected_variant_snapshot: dict[str, Any] | None = Field(
        default=None,
        validation_alias=AliasChoices("selected_variant_snapshot", "selected_variant_json"),
    )
    dispatch_overrides: list[dict[str, Any]] = Field(
        default_factory=list,
        validation_alias=AliasChoices("dispatch_overrides", "dispatch_overrides_json"),
    )
    dispatch_idempotency_key: str | None = None
    created_at: datetime
    updated_at: datetime
    dispatched_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)

    @field_validator("variants", mode="before")
    @classmethod
    def remove_model_credentials(cls, value: Any) -> Any:
        return _without_model_credentials(value)

    @field_validator("selected_variant_snapshot", "dispatch_overrides", mode="before")
    @classmethod
    def remove_dispatch_model_credentials(cls, value: Any) -> Any:
        return _without_model_credentials(value)


class TaskRead(BaseModel):
    id: str
    tenant_id: str
    project_id: str
    plan_id: str | None = None
    parent_task_id: str | None = None
    title: str
    description: str | None = None
    required_role: str | None = None
    priority: TaskPriority
    status: TaskStatus
    assignee_user_id: str | None = None
    reviewer_user_id: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate_days: float | None = None
    progress: int
    acceptance_criteria: str | None = None
    result_summary: str | None = None
    version: int
    dependencies: list[str] = Field(default_factory=list)
    events: list[WorkTaskEventRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class DashboardRead(BaseModel):
    tenant_id: str
    project_count: int = 0
    task_counts: dict[str, int] = Field(default_factory=dict)
    employee_count: int = 0
    pending_review_count: int = 0
    at_risk_project_count: int = 0
    department_loads: list[dict[str, Any]] = Field(default_factory=list)
    recent_events: list[WorkTaskEventRead] = Field(default_factory=list)

    model_config = ConfigDict(from_attributes=True)


class TaskUpdateRequest(BaseModel):
    tenant_id: str
    version: int | None = None
    title: str | None = None
    description: str | None = None
    priority: TaskPriority | None = None
    status: TaskStatus | None = None
    assignee_user_id: str | None = None
    reviewer_user_id: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    estimate_days: float | None = None
    progress: int | None = Field(default=None, ge=0, le=100)
    acceptance_criteria: str | None = None
    result_summary: str | None = None

    model_config = ConfigDict(extra="forbid")


class TaskReviewRequest(BaseModel):
    tenant_id: str
    version: int
    verdict: ReviewVerdict
    comment: str | None = None

    model_config = ConfigDict(extra="forbid")


def _without_model_credentials(value: Any) -> Any:
    if isinstance(value, list):
        return [_without_model_credentials(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _without_model_credentials(item)
        for key, item in value.items()
        if not _is_model_credential_key(key)
    }


def _is_model_credential_key(key: str) -> bool:
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", key).lower().replace("-", "_")
    credential_suffixes = ("_api_key", "_access_token", "_secret", "_password", "_credential")
    direct_credential_keys = {
        "api_key",
        "access_token",
        "authorization",
        "token",
        "secret",
        "password",
        "credential",
    }
    return normalized in direct_credential_keys or normalized.endswith(credential_suffixes)
