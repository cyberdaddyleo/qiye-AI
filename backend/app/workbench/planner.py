from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from datetime import date, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlmodel import Session

from app.agents.branching import model_for_agent
from app.db.models import EmployeeProfile, WorkTask
from app.llm.client import LLMClient

PLANNER_SYSTEM_PROMPT = """你是企业项目规划器。把目标拆成 6–16 个可执行且可验收的任务。
只返回 JSON 对象，顶层仅含 tasks。每个任务仅含以下字段：
key, title, description, required_role, skills, estimate_days, priority, depends_on,
acceptance_criteria。key 必须唯一；depends_on 只能引用同一响应中更早或无环的 key；不要返回凭据、
提示词、模型配置、解释文字或 Markdown。"""

_SEPARATOR = re.compile(r"[\s,，、;；|]+")
_ACTIVE_STATUSES = {"blocked", "backlog", "in_progress", "review"}
_WBS_FIELDS = {
    "key",
    "title",
    "description",
    "required_role",
    "skills",
    "estimate_days",
    "priority",
    "depends_on",
    "acceptance_criteria",
}


def _normalize_key(value: str) -> str:
    return re.sub(r"[^\w-]+", "-", value.strip().casefold()).strip("-_")


def _normalize_keywords(value: object) -> list[str]:
    raw = value if isinstance(value, list) else [value]
    result: list[str] = []
    for item in raw:
        for part in _SEPARATOR.split(str(item or "").strip().casefold()):
            normalized = part.strip("-_")
            if normalized and normalized not in result:
                result.append(normalized)
    return result


class PlanningTask(BaseModel):
    key: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=300)
    description: str = Field(default="", max_length=10_000)
    required_role: str = Field(default="", max_length=200)
    skills: list[str] = Field(default_factory=list, max_length=40)
    estimate_days: float = Field(default=1, gt=0, le=120)
    priority: Literal["low", "normal", "high", "urgent"] = "normal"
    depends_on: list[str] = Field(default_factory=list, max_length=40)
    acceptance_criteria: str = Field(default="", max_length=10_000)
    assignee_user_id: str | None = None
    start_date: date | None = None
    due_date: date | None = None
    assignment: dict[str, Any] = Field(default_factory=dict)
    unassigned_reason: str | None = None

    model_config = ConfigDict(extra="forbid")

    @field_validator("key", mode="before")
    @classmethod
    def normalize_key(cls, value: object) -> str:
        return _normalize_key(str(value or ""))

    @field_validator("title", "description", "required_role", "acceptance_criteria", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> str:
        return str(value or "").strip()

    @field_validator("skills", mode="before")
    @classmethod
    def normalize_skills(cls, value: object) -> list[str]:
        return _normalize_keywords(value)

    @field_validator("depends_on", mode="before")
    @classmethod
    def normalize_dependencies(cls, value: object) -> list[str]:
        raw = value if isinstance(value, list) else []
        return list(dict.fromkeys(_normalize_key(str(item or "")) for item in raw if item))


class PlanVariant(BaseModel):
    key: Literal["A", "B", "C"]
    name: str
    strategy: Literal["balanced", "fast", "cost"]
    tasks: list[PlanningTask]
    metrics: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    utilization: dict[str, dict[str, float | int]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="forbid")


class PlanResult(BaseModel):
    source: Literal["model", "fallback"]
    tasks: list[PlanningTask] = Field(default_factory=list)
    variants: list[PlanVariant] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


def fallback_wbs(goal: str) -> list[PlanningTask]:
    objective = goal.strip()[:300] or "项目目标"
    templates = [
        ("requirements", "澄清需求与范围", "Business Analyst", ["research"], 2, []),
        ("architecture", "制定交付方案", "Backend Engineer", ["python"], 3, ["requirements"]),
        (
            "implementation",
            "实施核心工作",
            "Backend Engineer",
            ["python", "fastapi"],
            5,
            ["architecture"],
        ),
        ("validation", "验证质量与安全", "QA Engineer", ["testing"], 3, ["implementation"]),
        ("rollout", "上线与变更沟通", "Delivery Manager", ["planning"], 2, ["validation"]),
        ("acceptance", "验收与复盘", "Business Analyst", ["analysis"], 2, ["rollout"]),
    ]
    return [
        PlanningTask(
            key=key,
            title=title,
            description=f"围绕“{objective}”完成{title}",
            required_role=role,
            skills=skills,
            estimate_days=days,
            priority="high" if not dependencies else "normal",
            depends_on=dependencies,
            acceptance_criteria=f"{title}产物经项目负责人确认",
        )
        for key, title, role, skills, days, dependencies in templates
    ]


def validate_planning_tasks(tasks: list[PlanningTask]) -> None:
    keys = [task.key for task in tasks]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate task key")
    known = set(keys)
    graph = {task.key: task.depends_on for task in tasks}
    if any(dependency not in known for task in tasks for dependency in task.depends_on):
        raise ValueError("unknown dependency")
    if any(task.key in task.depends_on for task in tasks):
        raise ValueError("self dependency")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(key: str) -> None:
        if key in visiting:
            raise ValueError("dependency cycle")
        if key in visited:
            return
        visiting.add(key)
        for dependency in graph[key]:
            visit(dependency)
        visiting.remove(key)
        visited.add(key)

    for key in keys:
        visit(key)


def _parse_wbs(raw: object) -> list[PlanningTask]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    if not isinstance(raw, dict) or set(raw) != {"tasks"}:
        raise ValueError("response must contain only tasks")
    values = raw.get("tasks")
    if not isinstance(values, list) or not 6 <= len(values) <= 16:
        raise ValueError("task count out of range")
    if any(not isinstance(value, dict) or set(value) != _WBS_FIELDS for value in values):
        raise ValueError("task fields are invalid")
    tasks = [PlanningTask.model_validate(value) for value in values]
    validate_planning_tasks(tasks)
    return tasks


def generate_wbs(
    db: Session,
    tenant_id: str,
    goal: str,
    constraints: dict[str, Any] | None = None,
) -> PlanResult:
    fallback = lambda: PlanResult(source="fallback", tasks=fallback_wbs(goal))
    try:
        model_config = model_for_agent(db, tenant_id, None, "default")
        if model_config is None:
            return fallback()
        constraints_text = json.dumps(
            constraints or {}, ensure_ascii=False, sort_keys=True, default=str
        )[:2_000]
        raw = LLMClient(model_config).generate_json(
            PLANNER_SYSTEM_PROMPT,
            {"goal": goal[:4_000], "constraints": constraints_text},
        )
        return PlanResult(source="model", tasks=_parse_wbs(raw))
    except Exception:  # noqa: BLE001 -- any provider or hostile payload failure must fall back
        return fallback()


def _topological_order(tasks: list[PlanningTask]) -> list[str]:
    by_key = {task.key: task for task in tasks}
    indegree = {task.key: len(task.depends_on) for task in tasks}
    dependents: dict[str, list[str]] = defaultdict(list)
    for task in tasks:
        for dependency in task.depends_on:
            dependents[dependency].append(task.key)
    ready = [task.key for task in tasks if indegree[task.key] == 0]
    result: list[str] = []
    while ready:
        key = ready.pop(0)
        result.append(key)
        for dependent in dependents[key]:
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                ready.append(dependent)
    if len(result) != len(by_key):
        raise ValueError("dependency cycle")
    return result


def _next_workday(value: date) -> date:
    current = value
    while current.weekday() >= 5:
        current += timedelta(days=1)
    return current


def _after_workday(value: date) -> date:
    return _next_workday(value + timedelta(days=1))


def _add_workdays(start: date, count: int) -> date:
    current = _next_workday(start)
    remaining = max(1, count) - 1
    while remaining:
        current += timedelta(days=1)
        if current.weekday() < 5:
            remaining -= 1
    return current


def _working_days_between(start: date, end: date) -> int:
    if end < start:
        return 0
    current = start
    result = 0
    while current <= end:
        if current.weekday() < 5:
            result += 1
        current += timedelta(days=1)
    return result


def _remaining_days(task: WorkTask) -> float:
    return max(0.0, float(task.estimate_days or 0) * (100 - task.progress) / 100)


def _employee_loads(current_work: list[WorkTask]) -> dict[str, float]:
    loads: dict[str, float] = defaultdict(float)
    for task in current_work:
        if task.assignee_user_id and task.status in _ACTIVE_STATUSES:
            loads[task.assignee_user_id] += _remaining_days(task)
    return dict(loads)


def _initial_availability(
    employees: list[EmployeeProfile], current_work: list[WorkTask], start_date: date
) -> dict[str, date]:
    available = {employee.user_id: _next_workday(start_date) for employee in employees}
    for task in current_work:
        user_id = task.assignee_user_id
        if not user_id or user_id not in available or task.status not in _ACTIVE_STATUSES:
            continue
        if task.due_date:
            candidate = _after_workday(task.due_date)
        else:
            employee = next(item for item in employees if item.user_id == user_id)
            capacity = max(0.01, employee.capacity_percent / 100)
            duration = max(1, math.ceil(_remaining_days(task) / capacity))
            candidate = _after_workday(_add_workdays(start_date, duration))
        available[user_id] = max(available[user_id], candidate)
    return available


def _role_match(required_role: str, employee: EmployeeProfile) -> bool:
    required = _normalize_keywords(required_role)
    if not required:
        return True
    employee_terms = set(
        _normalize_keywords(
            [employee.job_title, employee.business_role, employee.level, *employee.skills_json]
        )
    )
    return all(term in employee_terms for term in required)


def _skill_fraction(required_skills: list[str], employee: EmployeeProfile) -> float:
    if not required_skills:
        return 1.0
    employee_skills = _normalize_keywords(employee.skills_json)
    matched = sum(
        any(required == actual or required in actual or actual in required for actual in employee_skills)
        for required in _normalize_keywords(required_skills)
    )
    return matched / len(_normalize_keywords(required_skills))


def _score_candidate(
    task: PlanningTask,
    employee: EmployeeProfile,
    loads: dict[str, float],
    current_work: list[WorkTask],
    project_id: str,
) -> tuple[dict[str, float], bool]:
    role_ok = _role_match(task.required_role, employee)
    skill_fraction = _skill_fraction(task.skills, employee)
    available_capacity = max(0.0, employee.capacity_percent - loads.get(employee.user_id, 0) * 10)
    continuity = any(
        row.assignee_user_id == employee.user_id
        and row.project_id == project_id
        and row.status in _ACTIVE_STATUSES
        for row in current_work
    )
    components = {
        "role": 40.0 if role_ok else 0.0,
        "skills": round(30.0 * skill_fraction, 2),
        "capacity": round(20.0 * available_capacity / 100, 2),
        "continuity": 10.0 if continuity else 0.0,
    }
    qualified = role_ok and (not task.skills or skill_fraction >= 0.5)
    return components, qualified


def _task_duration(task: PlanningTask, employee: EmployeeProfile | None, strategy: str) -> int:
    if employee is None:
        return max(1, math.ceil(task.estimate_days))
    if strategy == "fast":
        return max(1, round(task.estimate_days / 1.2))
    capacity = max(0.01, employee.capacity_percent / 100)
    return max(1, math.ceil(task.estimate_days / capacity))


def _critical_path(tasks: list[PlanningTask]) -> list[str]:
    by_key = {task.key: task for task in tasks}
    best: dict[str, tuple[float, list[str]]] = {}
    for key in _topological_order(tasks):
        task = by_key[key]
        previous = max(
            (best[dependency] for dependency in task.depends_on),
            default=(0.0, []),
            key=lambda item: item[0],
        )
        best[key] = (previous[0] + task.estimate_days, [*previous[1], key])
    return max(best.values(), key=lambda item: item[0])[1] if best else []


def _plan_variant(
    key: Literal["A", "B", "C"],
    strategy: Literal["balanced", "fast", "cost"],
    tasks: list[PlanningTask],
    employees: list[EmployeeProfile],
    current_work: list[WorkTask],
    project_id: str,
    start_date: date,
    deadline: date | None,
    budget: float | None,
) -> PlanVariant:
    by_key = {task.key: task.model_copy(deep=True) for task in tasks}
    loads = _employee_loads(current_work)
    available = _initial_availability(employees, current_work, start_date)
    employees_by_user = {employee.user_id: employee for employee in employees}
    finish_dates: dict[str, date] = {}
    assigned_effort: dict[str, float] = defaultdict(float)
    risks: list[str] = []

    for task_key in _topological_order(tasks):
        task = by_key[task_key]
        dependency_start = max(
            (_after_workday(finish_dates[dependency]) for dependency in task.depends_on),
            default=_next_workday(start_date),
        )
        scored: list[tuple[EmployeeProfile, dict[str, float], float]] = []
        candidate_scores: dict[str, dict[str, float]] = {}
        for employee in employees:
            components, qualified = _score_candidate(
                task, employee, loads, current_work, project_id
            )
            candidate_scores[employee.user_id] = components
            if qualified:
                scored.append((employee, components, sum(components.values())))

        selected: EmployeeProfile | None = None
        if scored and strategy == "balanced":
            selected = min(
                scored,
                key=lambda item: (
                    -item[2],
                    float("inf") if item[0].daily_cost is None else item[0].daily_cost,
                    item[0].user_id,
                ),
            )[0]
        elif scored and strategy == "fast":
            selected = min(
                scored,
                key=lambda item: (
                    _add_workdays(
                        max(dependency_start, available[item[0].user_id]),
                        _task_duration(task, item[0], strategy),
                    ),
                    -item[2],
                    item[0].user_id,
                ),
            )[0]
        elif scored:
            selected = min(
                scored,
                key=lambda item: (
                    float("inf") if item[0].daily_cost is None else item[0].daily_cost,
                    -item[2],
                    item[0].user_id,
                ),
            )[0]

        task.assignee_user_id = selected.user_id if selected else None
        if selected:
            components = candidate_scores[selected.user_id]
            task_start = max(dependency_start, available[selected.user_id])
            task_due = _add_workdays(task_start, _task_duration(task, selected, strategy))
            available[selected.user_id] = _after_workday(task_due)
            assigned_effort[selected.user_id] += task.estimate_days
            task.assignment = {
                "score_components": components,
                "total_score": round(sum(components.values()), 2),
                "candidate_scores": candidate_scores,
                "rationale": (
                    f"角色匹配 {components['role']:.0f}/40；技能匹配 {components['skills']:.0f}/30；"
                    f"容量 {components['capacity']:.0f}/20；连续性 {components['continuity']:.0f}/10"
                ),
            }
        else:
            task_start = dependency_start
            task_due = _add_workdays(task_start, _task_duration(task, None, strategy))
            task.unassigned_reason = "没有满足角色与技能要求的可用员工"
            task.assignment = {"candidate_scores": candidate_scores}
            risks.append(f"任务“{task.title}”未分配：{task.unassigned_reason}")
        task.start_date = task_start
        task.due_date = task_due
        finish_dates[task.key] = task_due

    planned_tasks = [by_key[task.key] for task in tasks]
    finish = max((task.due_date for task in planned_tasks if task.due_date), default=start_date)
    cost = round(
        sum(
            task.estimate_days
            * float(employees_by_user[task.assignee_user_id].daily_cost or 0)
            for task in planned_tasks
            if task.assignee_user_id
        ),
        2,
    )
    if strategy == "fast":
        risks.append("快速方案按最高 120% 容量排期，需关注人员过载")
    if deadline and finish > deadline:
        risks.append(f"计划完成日期 {finish.isoformat()} 晚于截止日期 {deadline.isoformat()}")
    if budget is not None and cost > budget:
        risks.append(f"预计成本 {cost:.2f} 超过预算 {budget:.2f}")

    peak_parallelism = 0
    current = _next_workday(start_date)
    while current <= finish:
        if current.weekday() < 5:
            peak_parallelism = max(
                peak_parallelism,
                sum(
                    bool(task.start_date and task.due_date and task.start_date <= current <= task.due_date)
                    for task in planned_tasks
                ),
            )
        current += timedelta(days=1)
    duration = _working_days_between(_next_workday(start_date), finish)
    utilization: dict[str, dict[str, float | int]] = {}
    for employee in employees:
        effort = round(assigned_effort.get(employee.user_id, 0.0), 2)
        capacity_days = max(0.01, duration * employee.capacity_percent / 100)
        utilization[employee.user_id] = {
            "assigned_days": effort,
            "capacity_percent": employee.capacity_percent,
            "utilization_percent": round(effort / capacity_days * 100, 1),
        }

    names = {"A": "平衡方案", "B": "快速方案", "C": "成本方案"}
    return PlanVariant(
        key=key,
        name=names[key],
        strategy=strategy,
        tasks=planned_tasks,
        metrics={
            "start_date": _next_workday(start_date).isoformat(),
            "finish_date": finish.isoformat(),
            "duration_workdays": duration,
            "cost": cost,
            "critical_path": _critical_path(tasks),
            "peak_parallelism": peak_parallelism,
        },
        risks=risks,
        utilization=utilization,
    )


def build_variants(
    tasks: list[PlanningTask],
    employees: list[EmployeeProfile],
    current_work: list[WorkTask],
    *,
    project_id: str,
    start_date: date,
    deadline: date | None = None,
    budget: float | None = None,
) -> list[PlanVariant]:
    validate_planning_tasks(tasks)
    active_employees = [employee for employee in employees if employee.status == "active"]
    return [
        _plan_variant(
            "A", "balanced", tasks, active_employees, current_work, project_id, start_date, deadline, budget
        ),
        _plan_variant(
            "B", "fast", tasks, active_employees, current_work, project_id, start_date, deadline, budget
        ),
        _plan_variant(
            "C", "cost", tasks, active_employees, current_work, project_id, start_date, deadline, budget
        ),
    ]
