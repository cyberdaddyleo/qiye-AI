from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace
from typing import ClassVar

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import EmployeeProfile, WorkTask
from app.workbench import planner as planner_module
from app.workbench.planner import (
    PlanningTask,
    build_variants,
    fallback_wbs,
    generate_wbs,
)


def _valid_wbs() -> dict[str, object]:
    tasks: list[dict[str, object]] = []
    for index in range(1, 7):
        tasks.append(
            {
                "key": f"T{index}",
                "title": f" Stage {index} ",
                "description": f"Deliver stage {index}",
                "required_role": "Backend Engineer" if index == 2 else "Analyst",
                "skills": "Python，FastAPI、SQL" if index == 2 else ["Excel"],
                "estimate_days": index,
                "priority": "high" if index == 1 else "normal",
                "depends_on": [] if index == 1 else [f"T{index - 1}", f"T{index - 1}"],
                "acceptance_criteria": f"Stage {index} is accepted",
            }
        )
    return {"tasks": tasks}


def _numeric_dependency_wbs() -> dict[str, object]:
    tasks = [dict(task) for task in _valid_wbs()["tasks"]]
    tasks[0]["key"] = "1"
    tasks[1]["depends_on"] = [1]
    return {"tasks": tasks}


class _FakeLLMClient:
    response: object = _valid_wbs()
    calls: ClassVar[list[dict[str, object]]] = []

    def __init__(self, model_config: object) -> None:
        self.model_config = model_config

    def generate_json(self, prompt: str, payload: dict[str, object]) -> object:
        self.calls.append({"prompt": prompt, "payload": payload})
        if isinstance(self.response, BaseException):
            raise self.response
        return self.response


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def fake_model(monkeypatch: pytest.MonkeyPatch) -> None:
    _FakeLLMClient.response = _valid_wbs()
    _FakeLLMClient.calls = []
    monkeypatch.setattr(planner_module, "LLMClient", _FakeLLMClient)
    monkeypatch.setattr(
        planner_module,
        "model_for_agent",
        lambda db, tenant_id, agent_id, role="default": SimpleNamespace(id="model_default"),
    )


def test_generate_wbs_normalizes_valid_model_output_and_caps_inputs(db: Session) -> None:
    result = generate_wbs(
        db,
        "tenant_a",
        "G" * 4_500,
        {"notes": "C" * 2_500},
    )

    assert result.source == "model"
    assert len(result.tasks) == 6
    assert result.tasks[0].title == "Stage 1"
    assert result.tasks[1].skills == ["python", "fastapi", "sql"]
    assert result.tasks[1].depends_on == ["t1"]
    assert result.tasks[1].key == "t2"
    payload = _FakeLLMClient.calls[0]["payload"]
    assert len(payload["goal"]) == 4_000
    assert len(payload["constraints"]) == 2_000
    assert "6–16" in _FakeLLMClient.calls[0]["prompt"]


@pytest.mark.parametrize(
    "bad_output",
    [
        "not-json",
        {"tasks": _valid_wbs()["tasks"] * 7},
        {
            "tasks": [
                *list(_valid_wbs()["tasks"])[:-1],
                {**list(_valid_wbs()["tasks"])[-1], "depends_on": ["missing"]},
            ]
        },
        {
            "tasks": [
                {**next(iter(_valid_wbs()["tasks"])), "depends_on": ["T1"]},
                *list(_valid_wbs()["tasks"])[1:],
            ]
        },
        {
            "tasks": [
                {**next(iter(_valid_wbs()["tasks"])), "depends_on": ["T6"]},
                *list(_valid_wbs()["tasks"])[1:],
            ]
        },
        {"api_key": "sk-do-not-leak", "tasks": _valid_wbs()["tasks"]},
        {
            "tasks": [
                {
                    **next(iter(_valid_wbs()["tasks"])),
                    "assignee_user_id": "attacker",
                    "unassigned_reason": "sk-task-secret",
                },
                *list(_valid_wbs()["tasks"])[1:],
            ]
        },
        {
            "tasks": [
                *list(_valid_wbs()["tasks"])[:1],
                {**list(_valid_wbs()["tasks"])[1], "depends_on": "T1"},
                *list(_valid_wbs()["tasks"])[2:],
            ]
        },
        {
            "tasks": [
                *list(_valid_wbs()["tasks"])[:1],
                {**list(_valid_wbs()["tasks"])[1], "depends_on": None},
                *list(_valid_wbs()["tasks"])[2:],
            ]
        },
        _numeric_dependency_wbs(),
        {
            "tasks": [
                *list(_valid_wbs()["tasks"])[:1],
                {**list(_valid_wbs()["tasks"])[1], "depends_on": [""]},
                *list(_valid_wbs()["tasks"])[2:],
            ]
        },
        TimeoutError("provider secret sk-timeout"),
    ],
    ids=[
        "malformed-json",
        "too-many-tasks",
        "unknown-dependency",
        "self-dependency",
        "cycle",
        "unexpected-secret-field",
        "model-controlled-assignment",
        "dependency-string-not-list",
        "dependency-null",
        "dependency-number",
        "dependency-empty-string",
        "provider-timeout",
    ],
)
def test_generate_wbs_falls_back_for_invalid_or_failed_model_output(
    db: Session, bad_output: object
) -> None:
    _FakeLLMClient.response = bad_output

    result = generate_wbs(db, "tenant_a", "Ship secure platform", {"token": "secret"})

    assert result.source == "fallback"
    assert result.tasks == fallback_wbs("Ship secure platform")
    serialized = json.dumps(result.model_dump(mode="json"), ensure_ascii=False)
    assert "sk-do-not-leak" not in serialized
    assert "sk-timeout" not in serialized
    assert "sk-task-secret" not in serialized
    assert "model_default" not in serialized


def _employee(
    user_id: str,
    title: str,
    skills: list[str],
    capacity: int,
    cost: float,
) -> EmployeeProfile:
    return EmployeeProfile(
        tenant_id="tenant_a",
        user_id=user_id,
        department_id="dept_engineering",
        job_title=title,
        business_role="member",
        skills_json=skills,
        capacity_percent=capacity,
        daily_cost=cost,
    )


def _planning_tasks() -> list[PlanningTask]:
    return [
        PlanningTask(
            key="research",
            title="Research",
            required_role="Analyst",
            skills=["Excel"],
            estimate_days=2,
            priority="high",
            acceptance_criteria="Findings approved",
        ),
        PlanningTask(
            key="api",
            title="Build API",
            required_role="Engineer",
            skills=["PYTHON，FASTAPI"],
            estimate_days=6,
            priority="high",
            depends_on=["research"],
            acceptance_criteria="API tests pass",
        ),
        PlanningTask(
            key="design",
            title="Design UI",
            required_role="Designer",
            skills=["Figma"],
            estimate_days=3,
            depends_on=["research"],
            acceptance_criteria="Design approved",
        ),
        PlanningTask(
            key="qa",
            title="Test release",
            required_role="QA",
            skills=["Playwright"],
            estimate_days=2,
            depends_on=["api", "design"],
            acceptance_criteria="Release checks pass",
        ),
        PlanningTask(
            key="analysis",
            title="Measure impact",
            required_role="Analyst",
            skills=["Excel"],
            estimate_days=2,
            depends_on=["qa"],
            acceptance_criteria="Metrics published",
        ),
        PlanningTask(
            key="sap",
            title="Configure SAP",
            required_role="SAP Architect",
            skills=["S/4HANA"],
            estimate_days=4,
            depends_on=["research"],
            acceptance_criteria="SAP configured",
        ),
    ]


def test_matching_scheduling_and_three_variants_are_explainable_and_distinct() -> None:
    employees = [
        _employee("expert", "Backend Engineer", ["Python", "FastAPI"], 100, 900),
        _employee("cheap_platform", "Platform Engineer", ["Python", "FastAPI"], 80, 250),
        _employee("analyst", "Data Analyst", ["Excel", "SQL"], 100, 400),
        _employee("designer", "Product Designer", ["Figma"], 60, 500),
        _employee("qa", "QA Engineer", ["Playwright"], 100, 200),
    ]
    current_work = [
        WorkTask(
            tenant_id="tenant_a",
            project_id="project_old",
            title="Migration",
            assignee_user_id="cheap_platform",
            status="in_progress",
            estimate_days=20,
            progress=0,
            due_date=date(2026, 10, 2),
        )
    ]

    variants = build_variants(
        _planning_tasks(),
        employees,
        current_work,
        project_id="project_new",
        start_date=date(2026, 9, 7),
        deadline=date(2026, 9, 30),
        budget=20_000,
    )

    assert [variant.key for variant in variants] == ["A", "B", "C"]
    by_key = {variant.key: variant for variant in variants}
    balanced_api = next(task for task in by_key["A"].tasks if task.key == "api")
    cost_api = next(task for task in by_key["C"].tasks if task.key == "api")
    assert balanced_api.assignee_user_id == "expert"
    assert cost_api.assignee_user_id == "cheap_platform"
    assert balanced_api.assignment["score_components"] == {
        "role": 40.0,
        "skills": 30.0,
        "capacity": 20.0,
        "continuity": 0.0,
    }
    assert "角色匹配" in balanced_api.assignment["rationale"]
    assert by_key["C"].metrics["cost"] < by_key["A"].metrics["cost"]
    assert by_key["B"].metrics["duration_workdays"] < by_key["A"].metrics["duration_workdays"]
    assert len({json.dumps(v.model_dump(mode="json"), sort_keys=True) for v in variants}) == 3

    unstaffed = next(task for task in by_key["A"].tasks if task.key == "sap")
    assert unstaffed.assignee_user_id is None
    assert unstaffed.unassigned_reason == "没有满足角色与技能要求的可用员工"
    assert any("未分配" in risk for risk in by_key["A"].risks)

    tasks = {task.key: task for task in by_key["A"].tasks}
    assert tasks["api"].start_date > tasks["research"].due_date
    assert tasks["qa"].start_date > max(tasks["api"].due_date, tasks["design"].due_date)
    assert by_key["A"].metrics["critical_path"] == ["research", "api", "qa", "analysis"]
    assert by_key["A"].metrics["peak_parallelism"] >= 2
    assert by_key["A"].utilization["expert"]["assigned_days"] == 6.0


def test_overloaded_employee_loses_capacity_score() -> None:
    employees = [
        _employee("free", "Platform Engineer", ["Python"], 80, 500),
        _employee("busy", "Backend Engineer", ["Python"], 100, 500),
    ]
    current_work = [
        WorkTask(
            tenant_id="tenant_a",
            project_id="other",
            title="Existing delivery",
            assignee_user_id="busy",
            status="in_progress",
            estimate_days=20,
            progress=0,
        )
    ]
    tasks = [
        PlanningTask(
            key="api",
            title="API",
            required_role="Engineer",
            skills=["python"],
            estimate_days=2,
            acceptance_criteria="Done",
        )
    ]

    balanced = build_variants(
        tasks,
        employees,
        current_work,
        project_id="new",
        start_date=date(2026, 9, 7),
    )[0]

    assignment = balanced.tasks[0].assignment
    assert balanced.tasks[0].assignee_user_id == "free"
    assert assignment["score_components"]["capacity"] == 16.0
    assert assignment["candidate_scores"]["busy"]["capacity"] == 0.0


def test_cost_variant_does_not_match_go_inside_django() -> None:
    employees = [
        _employee("go", "Backend Engineer", ["Go"], 100, 500),
        _employee("django", "Backend Engineer", ["Django"], 100, 10),
    ]
    task = PlanningTask(
        key="service",
        title="Build service",
        required_role="Engineer",
        skills=["go"],
        estimate_days=2,
        acceptance_criteria="Done",
    )

    cost = build_variants(
        [task], employees, [], project_id="new", start_date=date(2026, 9, 7)
    )[2]

    assert cost.tasks[0].assignee_user_id == "go"


def test_cost_variant_does_not_match_sql_inside_nosql() -> None:
    employee = _employee("nosql", "Data Engineer", ["NoSQL"], 100, 10)
    task = PlanningTask(
        key="warehouse",
        title="Build warehouse",
        required_role="Engineer",
        skills=["sql"],
        estimate_days=2,
        acceptance_criteria="Done",
    )

    cost = build_variants(
        [task], [employee], [], project_id="new", start_date=date(2026, 9, 7)
    )[2]

    assert cost.tasks[0].assignee_user_id is None
    assert cost.tasks[0].unassigned_reason == "没有满足角色与技能要求的可用员工"


def test_cost_variant_allows_cjk_skill_substring_matching() -> None:
    employee = _employee("analyst", "Data Engineer", ["数据分析"], 100, 100)
    task = PlanningTask(
        key="insight",
        title="Analyze data",
        required_role="Engineer",
        skills=["分析"],
        estimate_days=2,
        acceptance_criteria="Done",
    )

    cost = build_variants(
        [task], [employee], [], project_id="new", start_date=date(2026, 9, 7)
    )[2]

    assert cost.tasks[0].assignee_user_id == "analyst"


def test_fast_variant_scales_configured_capacity_by_twenty_percent() -> None:
    employee = _employee("part_time", "Backend Engineer", ["Python"], 60, 500)
    task = PlanningTask(
        key="api",
        title="Build API",
        required_role="Engineer",
        skills=["python"],
        estimate_days=6,
        acceptance_criteria="Done",
    )

    fast = build_variants(
        [task], [employee], [], project_id="new", start_date=date(2026, 9, 7)
    )[1]

    assert fast.tasks[0].assignment["effective_capacity_percent"] == 72.0
    assert fast.tasks[0].start_date == date(2026, 9, 7)
    assert fast.tasks[0].due_date == date(2026, 9, 17)
    assert fast.metrics["duration_workdays"] == 9
    assert any("60%→72%" in risk for risk in fast.risks)


def test_existing_unscheduled_work_accumulates_after_latest_committed_date() -> None:
    employee = _employee("engineer", "Backend Engineer", ["Python"], 100, 500)
    current_work = [
        WorkTask(
            tenant_id="tenant_a",
            project_id="old",
            title="Committed",
            assignee_user_id="engineer",
            status="in_progress",
            estimate_days=4,
            due_date=date(2026, 9, 18),
        ),
        WorkTask(
            tenant_id="tenant_a",
            project_id="old",
            title="Unscheduled one",
            assignee_user_id="engineer",
            status="backlog",
            estimate_days=10,
        ),
        WorkTask(
            tenant_id="tenant_a",
            project_id="old",
            title="Unscheduled two",
            assignee_user_id="engineer",
            status="backlog",
            estimate_days=10,
        ),
    ]
    task = PlanningTask(
        key="next",
        title="Next work",
        required_role="Engineer",
        skills=["python"],
        estimate_days=1,
        acceptance_criteria="Done",
    )

    balanced = build_variants(
        [task], current_work=current_work, employees=[employee],
        project_id="new", start_date=date(2026, 9, 7)
    )[0]

    assert balanced.tasks[0].start_date == date(2026, 10, 19)


def test_critical_path_uses_capacity_resource_serialization_and_availability_waits() -> None:
    employees = [
        _employee("designer", "Product Designer", ["Figma"], 25, 400),
        _employee("engineer", "Backend Engineer", ["Python"], 100, 400),
    ]
    current_work = [
        WorkTask(
            tenant_id="tenant_a",
            project_id="old",
            title="Committed design",
            assignee_user_id="designer",
            status="in_progress",
            estimate_days=5,
            due_date=date(2026, 9, 11),
        )
    ]
    tasks = [
        PlanningTask(
            key="slow_a", title="Slow A", required_role="Designer", skills=["figma"],
            estimate_days=3, acceptance_criteria="Done"
        ),
        PlanningTask(
            key="slow_b", title="Slow B", required_role="Designer", skills=["figma"],
            estimate_days=3, acceptance_criteria="Done"
        ),
        PlanningTask(
            key="fast_a", title="Fast A", required_role="Engineer", skills=["python"],
            estimate_days=8, acceptance_criteria="Done"
        ),
        PlanningTask(
            key="fast_b", title="Fast B", required_role="Engineer", skills=["python"],
            estimate_days=8, depends_on=["fast_a"], acceptance_criteria="Done"
        ),
    ]

    balanced = build_variants(
        tasks, employees, current_work, project_id="new", start_date=date(2026, 9, 7)
    )[0]

    assert balanced.metrics["critical_path"] == ["slow_a", "slow_b"]
    assert balanced.tasks[0].start_date == date(2026, 9, 14)
    assert balanced.tasks[1].start_date > balanced.tasks[0].due_date
