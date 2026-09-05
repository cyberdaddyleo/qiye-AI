from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.db.models import (
    Department,
    EmployeeProfile,
    Tenant,
    User,
    UserAvatar,
    WorkPlan,
    WorkProject,
    WorkTask,
    WorkTaskDependency,
    WorkTaskEvent,
)
from app.main import app
from app.security.auth import create_access_token
from app.workbench.service import update_department


def _headers(user: dict[str, str]) -> dict[str, str]:
    token_user = User(
        id=user["id"],
        tenant_id=user["tenant_id"],
        username=user["username"],
        password_hash="hash",
    )
    return {"Authorization": f"Bearer {create_access_token(token_user)}"}


def _variant(key: str, member_id: str, colleague_id: str, hidden_id: str) -> dict[str, object]:
    tasks = [
        {
            "key": "dependency",
            "title": "Dependency context",
            "description": "context needed by the assignee",
            "required_role": "engineer",
            "skills": ["python"],
            "estimate_days": 1,
            "priority": "normal",
            "depends_on": [],
            "acceptance_criteria": "Dependency complete",
            "assignee_user_id": colleague_id,
            "start_date": "2026-09-07",
            "due_date": "2026-09-07",
            "assignment": {
                "candidate_scores": {
                    member_id: {"capacity": 20},
                    colleague_id: {"capacity": 18},
                    hidden_id: {"capacity": 15},
                },
                "effective_capacity_percent": 65,
                "rationale": "internal assignment explanation",
            },
            "unassigned_reason": None,
        },
        {
            "key": "mine",
            "title": "My planned task",
            "description": "participant context",
            "required_role": "engineer",
            "skills": ["python"],
            "estimate_days": 2,
            "priority": "normal",
            "depends_on": ["dependency"],
            "acceptance_criteria": "Own task complete",
            "assignee_user_id": member_id,
            "start_date": "2026-09-08",
            "due_date": "2026-09-09",
            "assignment": {
                "candidate_scores": {
                    member_id: {"capacity": 20},
                    colleague_id: {"capacity": 18},
                },
                "effective_capacity_percent": 73,
                "rationale": "internal assignment explanation",
            },
            "unassigned_reason": None,
        },
        {
            "key": "unrelated",
            "title": "Unrelated task",
            "description": "not needed by the participant",
            "required_role": "designer",
            "skills": ["design"],
            "estimate_days": 3,
            "priority": "normal",
            "depends_on": [],
            "acceptance_criteria": "Unrelated complete",
            "assignee_user_id": hidden_id,
            "start_date": "2026-09-07",
            "due_date": "2026-09-09",
            "assignment": {
                "candidate_scores": {hidden_id: {"capacity": 20}},
                "effective_capacity_percent": 100,
                "rationale": "internal assignment explanation",
            },
            "unassigned_reason": None,
        },
    ]
    return {
        "key": key,
        "name": f"Variant {key}",
        "strategy": {"A": "balanced", "B": "fast", "C": "cost"}[key],
        "tasks": tasks,
        "metrics": {
            "start_date": "2026-09-07",
            "finish_date": "2026-09-09",
            "duration_workdays": 3,
            "critical_path": ["mine", "unrelated"],
            "cost": 9999,
            "internal_assignment": {
                "candidate_scores": {hidden_id: {"capacity_percent": 100}},
                "assignee_user_id": hidden_id,
            },
            "effective_capacity_percent": {
                member_id: 73,
                colleague_id: 65,
                hidden_id: 100,
            },
        },
        "risks": ["internal capacity warning"],
        "utilization": {
            member_id: {"capacity_percent": 73, "utilization_percent": 80},
            colleague_id: {"capacity_percent": 65, "utilization_percent": 90},
            hidden_id: {"capacity_percent": 100, "utilization_percent": 40},
        },
    }


@pytest.fixture
def workbench_boundary() -> Iterator[tuple[TestClient, Engine, dict[str, dict[str, str]]]]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([Tenant(id="tenant_a", name="A"), Tenant(id="tenant_b", name="B")])
        users = {
            "admin": User(
                tenant_id="tenant_a", username="admin-final", role="admin", password_hash="hash"
            ),
            "ceo": User(tenant_id="tenant_a", username="ceo-final", password_hash="hash"),
            "manager": User(tenant_id="tenant_a", username="manager-final", password_hash="hash"),
            "owner": User(tenant_id="tenant_a", username="owner-final", password_hash="hash"),
            "member": User(tenant_id="tenant_a", username="member-final", password_hash="hash"),
            "reviewer": User(tenant_id="tenant_a", username="reviewer-final", password_hash="hash"),
            "colleague": User(
                tenant_id="tenant_a", username="colleague-final", password_hash="hash"
            ),
            "design": User(tenant_id="tenant_a", username="design-final", password_hash="hash"),
            "inactive": User(tenant_id="tenant_a", username="inactive-final", password_hash="hash"),
            "delete_me": User(tenant_id="tenant_a", username="delete-final", password_hash="hash"),
            "unprofiled": User(
                tenant_id="tenant_a", username="unprofiled-final", password_hash="hash"
            ),
            "outsider": User(tenant_id="tenant_b", username="outsider-final", password_hash="hash"),
        }
        db.add_all(users.values())
        db.flush()
        engineering = Department(tenant_id="tenant_a", name="Engineering", code="ENG")
        design = Department(tenant_id="tenant_a", name="Design", code="DES")
        foreign = Department(tenant_id="tenant_b", name="Foreign", code="FOR")
        db.add_all([engineering, design, foreign])
        db.flush()
        engineering.manager_user_id = users["manager"].id
        profiles = {
            "ceo": EmployeeProfile(
                tenant_id="tenant_a", user_id=users["ceo"].id, business_role="ceo"
            ),
            "manager": EmployeeProfile(
                tenant_id="tenant_a",
                user_id=users["manager"].id,
                department_id=engineering.id,
                business_role="manager",
            ),
            "owner": EmployeeProfile(
                tenant_id="tenant_a",
                user_id=users["owner"].id,
                department_id=engineering.id,
            ),
            "member": EmployeeProfile(
                tenant_id="tenant_a",
                user_id=users["member"].id,
                department_id=engineering.id,
                capacity_percent=73,
                daily_cost=999,
            ),
            "reviewer": EmployeeProfile(
                tenant_id="tenant_a",
                user_id=users["reviewer"].id,
                department_id=engineering.id,
            ),
            "colleague": EmployeeProfile(
                tenant_id="tenant_a",
                user_id=users["colleague"].id,
                department_id=engineering.id,
                capacity_percent=65,
                daily_cost=888,
            ),
            "design": EmployeeProfile(
                tenant_id="tenant_a",
                user_id=users["design"].id,
                department_id=design.id,
                capacity_percent=91,
                daily_cost=777,
            ),
            "inactive": EmployeeProfile(
                tenant_id="tenant_a",
                user_id=users["inactive"].id,
                department_id=engineering.id,
                status="inactive",
            ),
            "delete_me": EmployeeProfile(
                tenant_id="tenant_a",
                user_id=users["delete_me"].id,
                department_id=engineering.id,
            ),
            "outsider": EmployeeProfile(
                tenant_id="tenant_b",
                user_id=users["outsider"].id,
                department_id=foreign.id,
            ),
        }
        db.add_all(
            [
                *profiles.values(),
                UserAvatar(user_id=users["colleague"].id, data_url="data:image/png;base64,aQ=="),
            ]
        )
        db.flush()
        project = WorkProject(
            tenant_id="tenant_a",
            name="Shared delivery",
            objective="Ship safely",
            owner_user_id=users["owner"].id,
            department_id=engineering.id,
        )
        other_project = WorkProject(
            tenant_id="tenant_a",
            name="Separate delivery",
            objective="Stay isolated",
            owner_user_id=users["manager"].id,
            department_id=engineering.id,
        )
        db.add_all([project, other_project])
        db.flush()
        variants = [
            _variant(key, users["member"].id, users["colleague"].id, users["design"].id)
            for key in ("A", "B", "C")
        ]
        dispatched_plan = WorkPlan(
            tenant_id="tenant_a",
            project_id=project.id,
            created_by_user_id=users["manager"].id,
            goal="Shared plan",
            budget=12345,
            constraints_json={
                "preferred_user_id": users["design"].id,
                "capacity_floor": 90,
                "note": "internal staffing rationale",
            },
            status="dispatched",
            source="fallback",
            variants_json=variants,
            selected_variant="A",
            selected_variant_json=variants[0],
            dispatch_overrides_json=[
                {
                    "key": "mine",
                    "changes": {
                        "assignee_user_id": {
                            "from": users["colleague"].id,
                            "to": users["member"].id,
                        }
                    },
                }
            ],
            dispatch_idempotency_key="sensitive-key",
        )
        draft_plan = WorkPlan(
            tenant_id="tenant_a",
            project_id=project.id,
            created_by_user_id=users["manager"].id,
            goal="Draft plan",
            status="draft",
            source="fallback",
            variants_json=variants,
        )
        db.add_all([dispatched_plan, draft_plan])
        db.flush()

        tasks = {
            "own": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                plan_id=dispatched_plan.id,
                title="My planned task",
                status="in_progress",
                assignee_user_id=users["member"].id,
                reviewer_user_id=users["reviewer"].id,
            ),
            "colleague": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                plan_id=dispatched_plan.id,
                title="Dependency context",
                assignee_user_id=users["colleague"].id,
                reviewer_user_id=users["owner"].id,
            ),
            "review": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title="Review task",
                status="review",
                assignee_user_id=users["colleague"].id,
                reviewer_user_id=users["reviewer"].id,
                result_summary="submitted",
            ),
            "cross": WorkTask(
                tenant_id="tenant_a",
                project_id=other_project.id,
                title="Cross-project task",
                assignee_user_id=users["manager"].id,
            ),
            "inactive_read": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title="Inactive read",
                assignee_user_id=users["inactive"].id,
            ),
            "inactive_update": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title="Inactive update",
                status="in_progress",
                assignee_user_id=users["inactive"].id,
            ),
            "inactive_comment": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title="Inactive comment",
                assignee_user_id=users["inactive"].id,
            ),
            "inactive_submit": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title="Inactive submit",
                status="in_progress",
                assignee_user_id=users["inactive"].id,
            ),
            "inactive_review": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title="Inactive review",
                status="review",
                assignee_user_id=users["colleague"].id,
                reviewer_user_id=users["inactive"].id,
                result_summary="submitted",
            ),
            "admin_assigned": WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title="Admin is not an employee",
                assignee_user_id=users["admin"].id,
            ),
        }
        for status in ("blocked", "backlog", "in_progress", "review", "done", "canceled"):
            tasks[f"state_{status}"] = WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title=f"State {status}",
                status=status,
                progress=100 if status == "done" else 0,
                assignee_user_id=users["member"].id,
                reviewer_user_id=users["reviewer"].id,
                result_summary="submitted" if status in {"review", "done"} else None,
            )
        db.add_all(tasks.values())
        db.flush()
        db.add(
            WorkTaskDependency(
                tenant_id="tenant_a",
                task_id=tasks["own"].id,
                depends_on_task_id=tasks["colleague"].id,
            )
        )
        plan_task_keys = {
            tasks["own"].id: "mine",
            tasks["colleague"].id: "dependency",
        }
        for task in tasks.values():
            payload = {"old_status": None, "new_status": task.status}
            if task.id in plan_task_keys:
                payload["plan_task_key"] = plan_task_keys[task.id]
            db.add(
                WorkTaskEvent(
                    tenant_id="tenant_a",
                    task_id=task.id,
                    actor_user_id=users["manager"].id,
                    actor_type="user",
                    event_type="task_created",
                    payload_json=payload,
                )
            )
        db.commit()

        rows = {
            name: {"id": row.id, "tenant_id": row.tenant_id, "username": row.username}
            for name, row in users.items()
        }
        rows.update(
            {
                "engineering": {"id": engineering.id},
                "design_department": {"id": design.id},
                "project": {"id": project.id},
                "other_project": {"id": other_project.id},
                "dispatched_plan": {"id": dispatched_plan.id},
                "draft_plan": {"id": draft_plan.id},
            }
        )
        rows.update({f"profile_{name}": {"id": profile.id} for name, profile in profiles.items()})
        rows.update({f"task_{name}": {"id": task.id} for name, task in tasks.items()})

    def override_get_session() -> Iterator[Session]:
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app), engine, rows
    finally:
        app.dependency_overrides.clear()


@pytest.mark.parametrize(
    ("task_key", "method", "suffix", "payload"),
    [
        ("inactive_read", "get", "", None),
        (
            "inactive_update",
            "put",
            "",
            {"tenant_id": "tenant_a", "version": 0, "progress": 10},
        ),
        (
            "inactive_comment",
            "post",
            "/comments",
            {"tenant_id": "tenant_a", "version": 0, "comment": "still here"},
        ),
        (
            "inactive_submit",
            "post",
            "/submit",
            {
                "tenant_id": "tenant_a",
                "version": 0,
                "result_summary": "must not submit",
                "artifact_refs": [],
            },
        ),
        (
            "inactive_review",
            "post",
            "/review",
            {"tenant_id": "tenant_a", "version": 0, "verdict": "approve"},
        ),
    ],
)
def test_inactive_employee_cannot_read_or_mutate_tasks(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    task_key: str,
    method: str,
    suffix: str,
    payload: dict[str, object] | None,
) -> None:
    client, _, rows = workbench_boundary
    kwargs: dict[str, object] = {"headers": _headers(rows["inactive"])}
    if method == "get":
        kwargs["params"] = {"tenant_id": "tenant_a"}
    else:
        kwargs["json"] = payload
    response = getattr(client, method)(
        f"/api/enterprise/workbench/tasks/{rows[f'task_{task_key}']['id']}{suffix}",
        **kwargs,
    )
    assert response.status_code == 403, response.text


def test_system_admin_without_employee_profile_can_manage_org_but_not_act_as_assignee(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    headers = _headers(rows["admin"])
    directory = client.get(
        "/api/enterprise/workbench/employees",
        params={"tenant_id": "tenant_a"},
        headers=headers,
    )
    assert directory.status_code == 200, directory.text

    task = client.get(
        f"/api/enterprise/workbench/tasks/{rows['task_admin_assigned']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=headers,
    )
    assert task.status_code == 403, task.text
    start = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_admin_assigned']['id']}",
        headers=headers,
        json={"tenant_id": "tenant_a", "version": 0, "status": "in_progress"},
    )
    assert start.status_code == 403, start.text


def test_employee_delete_is_always_auditable_soft_deactivation(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    response = client.delete(
        f"/api/enterprise/workbench/employees/{rows['profile_delete_me']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["admin"]),
    )
    assert response.status_code == 204, response.text
    with Session(engine) as db:
        profile = db.get(EmployeeProfile, rows["profile_delete_me"]["id"])
        assert profile is not None
        assert profile.status == "inactive"


def test_deleting_department_manager_soft_deactivates_and_clears_live_role(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    response = client.delete(
        f"/api/enterprise/workbench/employees/{rows['profile_manager']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["admin"]),
    )
    assert response.status_code == 204, response.text
    with Session(engine) as db:
        profile = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        department = db.get(Department, rows["engineering"]["id"])
        assert profile is not None
        assert profile.status == "inactive"
        assert profile.business_role == "member"
        assert department is not None and department.manager_user_id is None


def test_assignment_targets_must_be_active_and_inside_actor_employee_scope(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    manager_headers = _headers(rows["manager"])

    inactive_owner = client.put(
        f"/api/enterprise/workbench/projects/{rows['project']['id']}",
        headers=manager_headers,
        json={
            "tenant_id": "tenant_a",
            "version": 0,
            "owner_user_id": rows["inactive"]["id"],
        },
    )
    assert inactive_owner.status_code == 422, inactive_owner.text

    outside_owner = client.put(
        f"/api/enterprise/workbench/projects/{rows['project']['id']}",
        headers=manager_headers,
        json={
            "tenant_id": "tenant_a",
            "version": 0,
            "owner_user_id": rows["design"]["id"],
        },
    )
    assert outside_owner.status_code == 403, outside_owner.text

    for field, user_name, expected_status in (
        ("assignee_user_id", "inactive", 422),
        ("reviewer_user_id", "unprofiled", 422),
        ("assignee_user_id", "design", 403),
        ("reviewer_user_id", "outsider", 404),
    ):
        response = client.post(
            "/api/enterprise/workbench/tasks",
            headers=manager_headers,
            json={
                "tenant_id": "tenant_a",
                "project_id": rows["project"]["id"],
                "title": f"invalid {field} {user_name}",
                field: rows[user_name]["id"],
            },
        )
        assert response.status_code == expected_status, response.text

    cross_department = client.post(
        "/api/enterprise/workbench/tasks",
        headers=_headers(rows["ceo"]),
        json={
            "tenant_id": "tenant_a",
            "project_id": rows["project"]["id"],
            "title": "CEO cross-department assignment",
            "assignee_user_id": rows["design"]["id"],
            "reviewer_user_id": rows["reviewer"]["id"],
        },
    )
    assert cross_department.status_code == 201, cross_department.text


def test_project_owner_and_dispatch_override_cannot_select_outside_project_scope(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    owner_create = client.post(
        "/api/enterprise/workbench/tasks",
        headers=_headers(rows["owner"]),
        json={
            "tenant_id": "tenant_a",
            "project_id": rows["project"]["id"],
            "title": "Owner cannot choose another department",
            "assignee_user_id": rows["design"]["id"],
        },
    )
    assert owner_create.status_code == 403, owner_create.text

    plan = client.get(
        f"/api/enterprise/workbench/plans/{rows['draft_plan']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["manager"]),
    ).json()
    selected = next(variant for variant in plan["variants"] if variant["key"] == "A")
    dispatch_tasks = [
        {
            "key": task["key"],
            "assignee_user_id": (
                rows["design"]["id"] if task["key"] == "mine" else task["assignee_user_id"]
            ),
            "start_date": task["start_date"],
            "due_date": task["due_date"],
            "acceptance_criteria": task["acceptance_criteria"],
            "depends_on": task["depends_on"],
        }
        for task in selected["tasks"]
    ]
    dispatch = client.post(
        f"/api/enterprise/workbench/plans/{rows['draft_plan']['id']}/dispatch",
        headers=_headers(rows["manager"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "outside-manager-scope",
            "tasks": dispatch_tasks,
        },
    )
    assert dispatch.status_code == 403, dispatch.text


def test_manager_without_an_explicit_department_cannot_fall_back_to_owner_scope(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        owner = db.get(EmployeeProfile, rows["profile_owner"]["id"])
        assert owner is not None
        owner.business_role = "manager"
        db.add(owner)
        db.commit()

    response = client.post(
        "/api/enterprise/workbench/tasks",
        headers=_headers(rows["owner"]),
        json={
            "tenant_id": "tenant_a",
            "project_id": rows["project"]["id"],
            "title": "Orphan manager cannot assign",
            "assignee_user_id": rows["member"]["id"],
        },
    )
    assert response.status_code == 403, response.text


def test_dispatched_plan_is_role_projected_for_participant_but_full_for_manager(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    endpoint = f"/api/enterprise/workbench/plans/{rows['dispatched_plan']['id']}"
    manager = client.get(
        endpoint,
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["manager"]),
    )
    assert manager.status_code == 200, manager.text
    assert len(manager.json()["variants"]) == 3
    assert manager.json()["variants"][0]["tasks"][0]["assignment"]["candidate_scores"]
    assert manager.json()["variants"][0]["utilization"]

    participant = client.get(
        endpoint,
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["member"]),
    )
    assert participant.status_code == 200, participant.text
    body = participant.json()
    assert [variant["key"] for variant in body["variants"]] == ["A"]
    assert [task["key"] for task in body["variants"][0]["tasks"]] == [
        "dependency",
        "mine",
    ]
    assert body["selected_variant_snapshot"] == body["variants"][0]
    assert body["dispatch_overrides"] == []
    assert body["dispatch_idempotency_key"] is None
    assert body["budget"] is None
    assert body["constraints"] == {}
    assert body["variants"][0]["utilization"] == {}
    assert all(task["assignment"] == {} for task in body["variants"][0]["tasks"])
    assert all(task["unassigned_reason"] is None for task in body["variants"][0]["tasks"])
    assert set(body["variants"][0]["metrics"]["critical_path"]) <= {
        task["key"] for task in body["variants"][0]["tasks"]
    }
    serialized = json.dumps(body, ensure_ascii=False)
    for secret in (
        "candidate_scores",
        "effective_capacity_percent",
        "internal assignment explanation",
        rows["colleague"]["id"],
        rows["design"]["id"],
        rows["manager"]["id"],
    ):
        assert secret not in serialized


def test_dispatched_plan_projection_keeps_reviewer_task_context(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.get(
        f"/api/enterprise/workbench/plans/{rows['dispatched_plan']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["reviewer"]),
    )
    assert response.status_code == 200, response.text
    variants = response.json()["variants"]
    assert len(variants) == 1
    assert [task["key"] for task in variants[0]["tasks"]] == ["dependency", "mine"]
    assert all(task["assignment"] == {} for task in variants[0]["tasks"])


def test_former_plan_creator_is_projected_after_losing_management_scope(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        department = db.get(Department, rows["engineering"]["id"])
        manager = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        task = db.get(WorkTask, rows["task_colleague"]["id"])
        assert department is not None and manager is not None and task is not None
        department.manager_user_id = None
        manager.business_role = "member"
        task.reviewer_user_id = rows["manager"]["id"]
        db.add_all([department, manager, task])
        db.commit()

    response = client.get(
        f"/api/enterprise/workbench/plans/{rows['dispatched_plan']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["manager"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [variant["key"] for variant in body["variants"]] == ["A"]
    assert [task["key"] for task in body["variants"][0]["tasks"]] == ["dependency"]
    assert "candidate_scores" not in json.dumps(body)
    assert body["dispatch_idempotency_key"] is None


def test_former_plan_creator_without_current_participation_cannot_read_dispatched_plan(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        department = db.get(Department, rows["engineering"]["id"])
        manager = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        assert department is not None and manager is not None
        department.manager_user_id = None
        manager.business_role = "member"
        db.add_all([department, manager])
        db.commit()

    response = client.get(
        f"/api/enterprise/workbench/plans/{rows['dispatched_plan']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["manager"]),
    )
    assert response.status_code == 403, response.text


def test_plan_projection_does_not_join_unrelated_tasks_by_duplicate_title(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        plan = db.get(WorkPlan, rows["dispatched_plan"]["id"])
        assert plan is not None
        variants = json.loads(json.dumps(plan.variants_json))
        variants[0]["tasks"][2]["title"] = "My planned task"
        plan.variants_json = variants
        plan.selected_variant_json = variants[0]
        db.add(plan)
        db.commit()

    response = client.get(
        f"/api/enterprise/workbench/plans/{rows['dispatched_plan']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["member"]),
    )
    assert response.status_code == 200, response.text
    assert [task["key"] for task in response.json()["variants"][0]["tasks"]] == [
        "dependency",
        "mine",
    ]


def test_reviewer_plan_projection_fails_closed_on_ambiguous_task_fingerprint(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        plan = db.get(WorkPlan, rows["dispatched_plan"]["id"])
        assert plan is not None
        variants = json.loads(json.dumps(plan.variants_json))
        variants[0]["tasks"][2]["title"] = "My planned task"
        variants[0]["tasks"][2]["assignee_user_id"] = rows["member"]["id"]
        plan.variants_json = variants
        plan.selected_variant_json = variants[0]
        db.add(plan)
        db.commit()

    response = client.get(
        f"/api/enterprise/workbench/plans/{rows['dispatched_plan']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["reviewer"]),
    )
    assert response.status_code == 200, response.text
    keys = [task["key"] for task in response.json()["variants"][0]["tasks"]]
    assert "unrelated" not in keys


def test_reviewer_plan_projection_does_not_trust_mutable_task_fingerprint(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        task = db.get(WorkTask, rows["task_own"]["id"])
        assert task is not None
        task.title = "Unrelated task"
        task.assignee_user_id = rows["design"]["id"]
        db.add(task)
        db.commit()

    response = client.get(
        f"/api/enterprise/workbench/plans/{rows['dispatched_plan']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["reviewer"]),
    )
    assert response.status_code == 200, response.text
    keys = [task["key"] for task in response.json()["variants"][0]["tasks"]]
    assert "unrelated" not in keys


@pytest.mark.parametrize(
    "status",
    ["blocked", "backlog", "in_progress", "review", "done", "canceled"],
)
def test_progress_mutation_is_allowed_only_while_in_progress(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    status: str,
) -> None:
    client, engine, rows = workbench_boundary
    response = client.put(
        f"/api/enterprise/workbench/tasks/{rows[f'task_state_{status}']['id']}",
        headers=_headers(rows["member"]),
        json={"tenant_id": "tenant_a", "version": 0, "progress": 37},
    )
    assert response.status_code == (200 if status == "in_progress" else 422), response.text
    with Session(engine) as db:
        task = db.get(WorkTask, rows[f"task_state_{status}"]["id"])
        assert task is not None
        assert task.progress == (
            37 if status == "in_progress" else (100 if status == "done" else 0)
        )
        assert task.version == (1 if status == "in_progress" else 0)


@pytest.mark.parametrize("status", ["done", "canceled"])
def test_terminal_tasks_reject_metadata_mutations(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    status: str,
) -> None:
    client, _, rows = workbench_boundary
    response = client.put(
        f"/api/enterprise/workbench/tasks/{rows[f'task_state_{status}']['id']}",
        headers=_headers(rows["manager"]),
        json={"tenant_id": "tenant_a", "version": 0, "title": "rewrite terminal task"},
    )
    assert response.status_code == 422, response.text


def test_terminal_task_rejects_version_only_noop_mutation(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_state_done']['id']}",
        headers=_headers(rows["manager"]),
        json={"tenant_id": "tenant_a", "version": 0},
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "mutation",
    [
        {"progress": 50},
        {"assignee_user_id": "USE_COLLEAGUE"},
        {"start_date": "2026-09-20"},
        {"estimate_days": 9},
        {"acceptance_criteria": "rewrite submitted work"},
        {"dependencies": []},
    ],
)
def test_review_tasks_freeze_execution_fields(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    mutation: dict[str, object],
) -> None:
    client, _, rows = workbench_boundary
    values = dict(mutation)
    if values.get("assignee_user_id") == "USE_COLLEAGUE":
        values["assignee_user_id"] = rows["colleague"]["id"]
    response = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_state_review']['id']}",
        headers=_headers(rows["manager"]),
        json={"tenant_id": "tenant_a", "version": 0, **values},
    )
    assert response.status_code == 422, response.text


def test_project_participant_can_read_and_comment_on_same_project_but_not_execute_others(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    headers = _headers(rows["member"])
    colleague_task = client.get(
        f"/api/enterprise/workbench/tasks/{rows['task_colleague']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=headers,
    )
    assert colleague_task.status_code == 200, colleague_task.text
    comment = client.post(
        f"/api/enterprise/workbench/tasks/{rows['task_colleague']['id']}/comments",
        headers=headers,
        json={"tenant_id": "tenant_a", "version": 0, "comment": "coordination note"},
    )
    assert comment.status_code == 200, comment.text

    execute = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_colleague']['id']}",
        headers=headers,
        json={
            "tenant_id": "tenant_a",
            "version": comment.json()["version"],
            "status": "in_progress",
        },
    )
    assert execute.status_code == 403, execute.text
    cross_project = client.get(
        f"/api/enterprise/workbench/tasks/{rows['task_cross']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=headers,
    )
    assert cross_project.status_code == 403, cross_project.text


@pytest.mark.parametrize(
    "payload",
    [
        {"version": 0},
        {"version": 0, "status": "backlog"},
    ],
)
def test_project_participant_cannot_write_noop_updates_to_colleague_task(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    payload: dict[str, object],
) -> None:
    client, engine, rows = workbench_boundary
    response = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_colleague']['id']}",
        headers=_headers(rows["member"]),
        json={"tenant_id": "tenant_a", **payload},
    )
    assert response.status_code == 422, response.text
    with Session(engine) as db:
        task = db.get(WorkTask, rows["task_colleague"]["id"])
        assert task is not None and task.version == 0


def test_project_manager_cannot_execute_or_submit_for_assignee(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    start = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_colleague']['id']}",
        headers=_headers(rows["manager"]),
        json={"tenant_id": "tenant_a", "version": 0, "status": "in_progress"},
    )
    assert start.status_code == 403, start.text
    submit = client.post(
        f"/api/enterprise/workbench/tasks/{rows['task_own']['id']}/submit",
        headers=_headers(rows["manager"]),
        json={
            "tenant_id": "tenant_a",
            "version": 0,
            "result_summary": "manager impersonation",
            "artifact_refs": [],
        },
    )
    assert submit.status_code == 403, submit.text


def test_project_participant_gets_only_safe_same_project_employee_directory_and_avatar(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    headers = _headers(rows["member"])
    response = client.get(
        "/api/enterprise/workbench/employees",
        params={"tenant_id": "tenant_a"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    by_user = {employee["user_id"]: employee for employee in response.json()}
    assert rows["member"]["id"] in by_user
    assert rows["colleague"]["id"] in by_user
    assert rows["design"]["id"] not in by_user
    assert rows["ceo"]["id"] not in by_user
    assert by_user[rows["colleague"]["id"]]["daily_cost"] is None
    assert by_user[rows["colleague"]["id"]]["capacity_percent"] == 0

    detail = client.get(
        f"/api/enterprise/workbench/employees/{rows['profile_colleague']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=headers,
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["daily_cost"] is None
    assert detail.json()["capacity_percent"] == 0
    avatar = client.get(
        f"/api/enterprise/workbench/employees/{rows['profile_colleague']['id']}/avatar",
        params={"tenant_id": "tenant_a"},
        headers=headers,
    )
    assert avatar.status_code == 200, avatar.text
    assert avatar.content == b"i"


def test_department_manager_patch_updates_both_roles_and_access_atomically(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    response = client.patch(
        f"/api/enterprise/workbench/departments/{rows['engineering']['id']}",
        headers=_headers(rows["admin"]),
        json={"tenant_id": "tenant_a", "manager_user_id": rows["member"]["id"]},
    )
    assert response.status_code == 200, response.text
    new_access = client.get(
        "/api/enterprise/workbench/access",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["member"]),
    )
    assert new_access.status_code == 200, new_access.text
    assert new_access.json()["business_role"] == "manager"
    assert new_access.json()["managed_department_ids"] == [rows["engineering"]["id"]]
    old_access = client.get(
        "/api/enterprise/workbench/access",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["manager"]),
    )
    assert old_access.status_code == 200, old_access.text
    assert old_access.json()["business_role"] == "member"
    assert old_access.json()["managed_department_ids"] == []
    with Session(engine) as db:
        new_profile = db.get(EmployeeProfile, rows["profile_member"]["id"])
        old_profile = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        assert new_profile is not None and new_profile.business_role == "manager"
        assert old_profile is not None and old_profile.business_role == "member"


def test_department_manager_cannot_demote_ceo_through_manager_assignment(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        ceo = db.get(EmployeeProfile, rows["profile_ceo"]["id"])
        assert ceo is not None
        ceo.department_id = rows["engineering"]["id"]
        db.add(ceo)
        db.commit()

    response = client.patch(
        f"/api/enterprise/workbench/departments/{rows['engineering']['id']}",
        headers=_headers(rows["manager"]),
        json={"tenant_id": "tenant_a", "manager_user_id": rows["ceo"]["id"]},
    )
    assert response.status_code == 422, response.text
    with Session(engine) as db:
        department = db.get(Department, rows["engineering"]["id"])
        ceo = db.get(EmployeeProfile, rows["profile_ceo"]["id"])
        assert department is not None
        assert department.manager_user_id == rows["manager"]["id"]
        assert ceo is not None and ceo.business_role == "ceo"


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_department_manager_cannot_update_or_deactivate_ceo_profile(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    operation: str,
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        ceo = db.get(EmployeeProfile, rows["profile_ceo"]["id"])
        assert ceo is not None
        ceo.department_id = rows["engineering"]["id"]
        db.add(ceo)
        db.commit()

    endpoint = f"/api/enterprise/workbench/employees/{rows['profile_ceo']['id']}"
    if operation == "update":
        response = client.patch(
            endpoint,
            headers=_headers(rows["manager"]),
            json={"tenant_id": "tenant_a", "business_role": "member"},
        )
    else:
        response = client.delete(
            endpoint,
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["manager"]),
        )
    assert response.status_code == 403, response.text
    with Session(engine) as db:
        ceo = db.get(EmployeeProfile, rows["profile_ceo"]["id"])
        assert ceo is not None
        assert ceo.business_role == "ceo"
        assert ceo.status == "active"


def test_archiving_department_demotes_manager_when_no_active_department_remains(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.patch(
        f"/api/enterprise/workbench/departments/{rows['engineering']['id']}",
        headers=_headers(rows["admin"]),
        json={"tenant_id": "tenant_a", "status": "archived"},
    )
    assert response.status_code == 200, response.text
    access = client.get(
        "/api/enterprise/workbench/access",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["manager"]),
    )
    assert access.status_code == 200, access.text
    assert access.json()["business_role"] == "member"
    assert access.json()["managed_department_ids"] == []


def test_deleting_department_uses_the_same_manager_role_cleanup(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    response = client.delete(
        f"/api/enterprise/workbench/departments/{rows['engineering']['id']}",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["admin"]),
    )
    assert response.status_code == 204, response.text
    with Session(engine) as db:
        department = db.get(Department, rows["engineering"]["id"])
        manager = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        assert department is not None and department.status == "archived"
        assert manager is not None and manager.business_role == "member"


def test_department_create_defers_manager_until_employee_belongs_to_new_department(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.post(
        "/api/enterprise/workbench/departments",
        headers=_headers(rows["admin"]),
        json={
            "tenant_id": "tenant_a",
            "name": "New department",
            "code": "NEW",
            "manager_user_id": rows["ceo"]["id"],
        },
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize("candidate", ["inactive", "design"])
def test_department_manager_patch_rejects_inactive_or_other_department_profile_atomically(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    candidate: str,
) -> None:
    client, engine, rows = workbench_boundary
    response = client.patch(
        f"/api/enterprise/workbench/departments/{rows['engineering']['id']}",
        headers=_headers(rows["admin"]),
        json={"tenant_id": "tenant_a", "manager_user_id": rows[candidate]["id"]},
    )
    assert response.status_code == 422, response.text
    with Session(engine) as db:
        department = db.get(Department, rows["engineering"]["id"])
        old_profile = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        candidate_profile = db.get(EmployeeProfile, rows[f"profile_{candidate}"]["id"])
        assert department is not None and department.manager_user_id == rows["manager"]["id"]
        assert old_profile is not None and old_profile.business_role == "manager"
        assert candidate_profile is not None
        assert candidate_profile.business_role == "member"


def test_employee_manager_role_requires_real_department_management(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.patch(
        f"/api/enterprise/workbench/employees/{rows['profile_owner']['id']}",
        headers=_headers(rows["admin"]),
        json={"tenant_id": "tenant_a", "business_role": "manager"},
    )
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "mutation",
    [
        {"department_id": "USE_DESIGN"},
        {"status": "inactive"},
    ],
)
def test_direct_employee_patch_preserves_active_department_manager_invariants(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    mutation: dict[str, str],
) -> None:
    client, engine, rows = workbench_boundary
    payload = dict(mutation)
    if payload.get("department_id") == "USE_DESIGN":
        payload["department_id"] = rows["design_department"]["id"]
    response = client.patch(
        f"/api/enterprise/workbench/employees/{rows['profile_manager']['id']}",
        headers=_headers(rows["admin"]),
        json={"tenant_id": "tenant_a", **payload},
    )
    assert response.status_code == 422, response.text
    with Session(engine) as db:
        profile = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        department = db.get(Department, rows["engineering"]["id"])
        assert profile is not None
        assert profile.status == "active"
        assert profile.business_role == "manager"
        assert profile.department_id == rows["engineering"]["id"]
        assert department is not None
        assert department.manager_user_id == rows["manager"]["id"]


@pytest.mark.parametrize("operation", ["create", "update"])
def test_system_admin_is_not_an_assignable_employee_business_role(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    operation: str,
) -> None:
    client, _, rows = workbench_boundary
    if operation == "create":
        response = client.post(
            "/api/enterprise/workbench/employees",
            headers=_headers(rows["admin"]),
            json={
                "tenant_id": "tenant_a",
                "user_id": rows["unprofiled"]["id"],
                "department_id": rows["engineering"]["id"],
                "business_role": "admin",
            },
        )
    else:
        response = client.patch(
            f"/api/enterprise/workbench/employees/{rows['profile_owner']['id']}",
            headers=_headers(rows["admin"]),
            json={"tenant_id": "tenant_a", "business_role": "admin"},
        )
    assert response.status_code == 422, response.text


def test_employee_import_cannot_assign_system_admin_as_business_role(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    response = client.post(
        "/api/enterprise/workbench/employees/import",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["admin"]),
        files={
            "file": (
                "employees.csv",
                (
                    b"username,display_name,department,business_role\n"
                    b"unprofiled-final,No profile,Engineering,admin\n"
                ),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 0
    assert response.json()["errors"] == [
        {
            "row": 2,
            "code": "invalid_business_role",
            "message": "business_role is invalid",
        }
    ]
    with Session(engine) as db:
        assert (
            db.exec(
                select(EmployeeProfile).where(
                    EmployeeProfile.tenant_id == "tenant_a",
                    EmployeeProfile.user_id == rows["unprofiled"]["id"],
                )
            ).first()
            is None
        )


def test_employee_import_manager_role_requires_existing_department_management(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    response = client.post(
        "/api/enterprise/workbench/employees/import",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["admin"]),
        files={
            "file": (
                "employees.csv",
                (
                    b"username,display_name,department,business_role\n"
                    b"unprofiled-final,No profile,Engineering,manager\n"
                ),
                "text/csv",
            )
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 0
    assert response.json()["errors"] == [
        {
            "row": 2,
            "code": "manager_scope_required",
            "message": "manager role requires department management",
        }
    ]
    with Session(engine) as db:
        assert (
            db.exec(
                select(EmployeeProfile).where(
                    EmployeeProfile.tenant_id == "tenant_a",
                    EmployeeProfile.user_id == rows["unprofiled"]["id"],
                )
            ).first()
            is None
        )


def test_employee_import_cannot_demote_an_active_department_manager(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    content = (
        b"username,display_name,department,business_role\n"
        b"manager-final,Manager,Engineering,member\n"
    )
    response = client.post(
        "/api/enterprise/workbench/employees/import",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["admin"]),
        files={"file": ("employees.csv", content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["updated"] == 0
    assert response.json()["errors"] == [
        {
            "row": 2,
            "code": "manager_role_required",
            "message": "department manager must retain manager role",
        }
    ]
    with Session(engine) as db:
        profile = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        assert profile is not None and profile.business_role == "manager"


@contextmanager
def _count_selects(engine: Engine) -> Iterator[list[str]]:
    statements: list[str] = []

    def count_statement(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: object,
    ) -> None:
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)

    event.listen(engine, "before_cursor_execute", count_statement)
    try:
        yield statements
    finally:
        event.remove(engine, "before_cursor_execute", count_statement)


def test_task_list_pagination_keeps_list_dto_and_bulk_loads_relations(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        for index in range(12):
            task = WorkTask(
                tenant_id="tenant_a",
                project_id=rows["project"]["id"],
                title=f"Paged {index:02d}",
                assignee_user_id=rows["member"]["id"],
            )
            db.add(task)
            db.flush()
            db.add(
                WorkTaskDependency(
                    tenant_id="tenant_a",
                    task_id=task.id,
                    depends_on_task_id=rows["task_colleague"]["id"],
                )
            )
            db.add(
                WorkTaskEvent(
                    tenant_id="tenant_a",
                    task_id=task.id,
                    actor_user_id=rows["manager"]["id"],
                    actor_type="user",
                    event_type="task_created",
                    payload_json={"old_status": None, "new_status": "backlog"},
                )
            )
        db.commit()

    base_params = {"tenant_id": "tenant_a", "scope": "mine", "status": "backlog"}
    with _count_selects(engine) as one_queries:
        one = client.get(
            "/api/enterprise/workbench/tasks",
            params={**base_params, "limit": 1},
            headers=_headers(rows["member"]),
        )
    with _count_selects(engine) as ten_queries:
        ten = client.get(
            "/api/enterprise/workbench/tasks",
            params={**base_params, "limit": 10, "offset": 1},
            headers=_headers(rows["member"]),
        )
    assert one.status_code == 200, one.text
    assert ten.status_code == 200, ten.text
    assert isinstance(ten.json(), list)
    assert len(ten.json()) == 10
    assert all(task["dependencies"] for task in ten.json())
    assert all(task["events"] for task in ten.json())
    assert len(ten_queries) <= len(one_queries) + 2
    assert len(ten_queries) <= 10
    assert (
        client.get(
            "/api/enterprise/workbench/tasks",
            params={**base_params, "limit": 0},
            headers=_headers(rows["member"]),
        ).status_code
        == 422
    )
    assert (
        client.get(
            "/api/enterprise/workbench/tasks",
            params={**base_params, "limit": 101},
            headers=_headers(rows["member"]),
        ).status_code
        == 422
    )


def test_dashboard_visibility_and_project_aggregates_have_constant_query_budget(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        for index in range(10):
            project = WorkProject(
                tenant_id="tenant_a",
                name=f"Dashboard {index:02d}",
                objective="query budget",
                owner_user_id=rows["manager"]["id"],
                department_id=rows["engineering"]["id"],
            )
            db.add(project)
            db.flush()
            task = WorkTask(
                tenant_id="tenant_a",
                project_id=project.id,
                title=f"Visible dashboard {index:02d}",
                assignee_user_id=rows["member"]["id"],
                reviewer_user_id=rows["reviewer"]["id"],
            )
            db.add(task)
            db.flush()
            db.add(
                WorkTaskEvent(
                    tenant_id="tenant_a",
                    task_id=task.id,
                    actor_user_id=rows["manager"]["id"],
                    actor_type="user",
                    event_type="task_created",
                    payload_json={"old_status": None, "new_status": "backlog"},
                )
            )
        db.commit()

    with _count_selects(engine) as queries:
        response = client.get(
            "/api/enterprise/workbench/dashboard",
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["member"]),
        )
    assert response.status_code == 200, response.text
    assert response.json()["project_count"] >= 11
    assert response.json()["task_counts"]["backlog"] >= 10
    assert len(queries) <= 14


def test_employee_create_rejects_direct_manager_outside_staffing_scope(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        target = User(
            tenant_id="tenant_a",
            username="new-report-final",
            password_hash="hash",
        )
        db.add(target)
        db.commit()
        target_id = target.id

    rejected = client.post(
        "/api/enterprise/workbench/employees",
        headers=_headers(rows["manager"]),
        json={
            "tenant_id": "tenant_a",
            "user_id": target_id,
            "department_id": rows["engineering"]["id"],
            "manager_user_id": rows["design"]["id"],
        },
    )
    assert rejected.status_code == 403, rejected.text
    with Session(engine) as db:
        assert (
            db.exec(select(EmployeeProfile).where(EmployeeProfile.user_id == target_id)).first()
            is None
        )

    accepted = client.post(
        "/api/enterprise/workbench/employees",
        headers=_headers(rows["admin"]),
        json={
            "tenant_id": "tenant_a",
            "user_id": target_id,
            "department_id": rows["engineering"]["id"],
            "manager_user_id": rows["design"]["id"],
        },
    )
    assert accepted.status_code == 201, accepted.text
    assert accepted.json()["manager_user_id"] == rows["design"]["id"]


@pytest.mark.parametrize(
    ("actor", "candidate", "expected_status"),
    [
        ("manager", "design", 403),
        ("manager", "inactive", 422),
        ("manager", "unprofiled", 422),
        ("ceo", "design", 200),
        ("admin", "design", 200),
    ],
)
def test_employee_update_direct_manager_requires_active_profile_in_actor_scope(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    actor: str,
    candidate: str,
    expected_status: int,
) -> None:
    client, engine, rows = workbench_boundary
    response = client.patch(
        f"/api/enterprise/workbench/employees/{rows['profile_member']['id']}",
        headers=_headers(rows[actor]),
        json={
            "tenant_id": "tenant_a",
            "manager_user_id": rows[candidate]["id"],
        },
    )
    assert response.status_code == expected_status, response.text
    with Session(engine) as db:
        profile = db.get(EmployeeProfile, rows["profile_member"]["id"])
        assert profile is not None
        assert profile.manager_user_id == (
            rows[candidate]["id"] if expected_status == 200 else None
        )


def test_employee_import_rejects_inactive_or_unprofiled_direct_managers_per_row(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    content = (
        b"username,display_name,department,manager_username\n"
        b"member-final,Member Changed,Engineering,inactive-final\n"
        b"colleague-final,Colleague Changed,Engineering,unprofiled-final\n"
        b"owner-final,Owner Changed,Engineering,design-final\n"
    )
    response = client.post(
        "/api/enterprise/workbench/employees/import",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["admin"]),
        files={"file": ("employees.csv", content, "text/csv")},
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 0
    assert response.json()["updated"] == 1
    assert response.json()["errors"] == [
        {
            "row": 2,
            "code": "inactive_manager",
            "message": "负责人必须是在职员工",
        },
        {
            "row": 3,
            "code": "inactive_manager",
            "message": "负责人必须是在职员工",
        },
    ]
    with Session(engine) as db:
        member = db.get(EmployeeProfile, rows["profile_member"]["id"])
        colleague = db.get(EmployeeProfile, rows["profile_colleague"]["id"])
        owner = db.get(EmployeeProfile, rows["profile_owner"]["id"])
        member_user = db.get(User, rows["member"]["id"])
        colleague_user = db.get(User, rows["colleague"]["id"])
        owner_user = db.get(User, rows["owner"]["id"])
        assert member is not None and member.manager_user_id is None
        assert colleague is not None and colleague.manager_user_id is None
        assert owner is not None and owner.manager_user_id == rows["design"]["id"]
        assert member_user is not None and member_user.display_name is None
        assert colleague_user is not None and colleague_user.display_name is None
        assert owner_user is not None and owner_user.display_name == "Owner Changed"


@pytest.mark.parametrize("field", ["name", "code", "status"])
def test_department_update_explicit_null_for_non_nullable_fields_returns_422(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    field: str,
) -> None:
    _, _, rows = workbench_boundary
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            f"/api/enterprise/workbench/departments/{rows['engineering']['id']}",
            headers=_headers(rows["admin"]),
            json={"tenant_id": "tenant_a", field: None},
        )
    assert response.status_code == 422, response.text
    assert any(item["loc"][-1] == field for item in response.json()["detail"])


@pytest.mark.parametrize(
    "field",
    ["business_role", "skills", "capacity_percent", "status"],
)
def test_employee_update_explicit_null_for_non_nullable_fields_returns_422(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    field: str,
) -> None:
    _, _, rows = workbench_boundary
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            f"/api/enterprise/workbench/employees/{rows['profile_member']['id']}",
            headers=_headers(rows["admin"]),
            json={"tenant_id": "tenant_a", field: None},
        )
    assert response.status_code == 422, response.text
    assert any(item["loc"][-1] == field for item in response.json()["detail"])


def test_update_dtos_still_allow_clearing_nullable_fields(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        profile = db.get(EmployeeProfile, rows["profile_member"]["id"])
        department = db.get(Department, rows["design_department"]["id"])
        assert profile is not None and department is not None
        profile.job_title = "Engineer"
        profile.manager_user_id = rows["design"]["id"]
        department.parent_id = rows["engineering"]["id"]
        db.add_all([profile, department])
        db.commit()

    employee_response = client.patch(
        f"/api/enterprise/workbench/employees/{rows['profile_member']['id']}",
        headers=_headers(rows["admin"]),
        json={
            "tenant_id": "tenant_a",
            "job_title": None,
            "daily_cost": None,
            "manager_user_id": None,
        },
    )
    department_response = client.patch(
        f"/api/enterprise/workbench/departments/{rows['design_department']['id']}",
        headers=_headers(rows["admin"]),
        json={"tenant_id": "tenant_a", "parent_id": None},
    )
    assert employee_response.status_code == 200, employee_response.text
    assert employee_response.json()["job_title"] is None
    assert employee_response.json()["daily_cost"] is None
    assert employee_response.json()["manager_user_id"] is None
    assert department_response.status_code == 200, department_response.text
    assert department_response.json()["parent_id"] is None


@pytest.mark.parametrize(
    "artifact_refs",
    [[""], ["resource:a", "   "], ["x" * 2_049]],
)
def test_task_submit_rejects_blank_or_oversized_artifact_references(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
    artifact_refs: list[str],
) -> None:
    client, _, rows = workbench_boundary
    response = client.post(
        f"/api/enterprise/workbench/tasks/{rows['task_own']['id']}/submit",
        headers=_headers(rows["member"]),
        json={
            "tenant_id": "tenant_a",
            "version": 0,
            "result_summary": "completed",
            "artifact_refs": artifact_refs,
        },
    )
    assert response.status_code == 422, response.text


def test_task_submit_strips_and_stably_deduplicates_artifact_references(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.post(
        f"/api/enterprise/workbench/tasks/{rows['task_own']['id']}/submit",
        headers=_headers(rows["member"]),
        json={
            "tenant_id": "tenant_a",
            "version": 0,
            "result_summary": "completed",
            "artifact_refs": [
                "  resource:report  ",
                "resource:report",
                " upload:screenshot ",
            ],
        },
    )
    assert response.status_code == 200, response.text
    submitted = next(
        event for event in response.json()["events"] if event["event_type"] == "result_submitted"
    )
    assert submitted["payload"]["artifact_refs"] == [
        "resource:report",
        "upload:screenshot",
    ]


def test_same_assignee_with_other_changes_does_not_emit_assignment_event(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_colleague']['id']}",
        headers=_headers(rows["manager"]),
        json={
            "tenant_id": "tenant_a",
            "version": 0,
            "title": "Dependency renamed",
            "assignee_user_id": rows["colleague"]["id"],
        },
    )
    assert response.status_code == 200, response.text
    assert [event["event_type"] for event in response.json()["events"]] == [
        "task_created",
        "task_updated",
    ]


def test_clearing_assignee_emits_task_unassigned_with_previous_and_new_values(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_colleague']['id']}",
        headers=_headers(rows["manager"]),
        json={
            "tenant_id": "tenant_a",
            "version": 0,
            "assignee_user_id": None,
        },
    )
    assert response.status_code == 200, response.text
    event = response.json()["events"][-1]
    assert event["event_type"] == "task_unassigned"
    assert event["payload"]["previous_assignee_user_id"] == rows["colleague"]["id"]
    assert event["payload"]["new_assignee_user_id"] is None


def test_real_reassignment_emits_task_assigned_with_previous_and_new_values(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, _, rows = workbench_boundary
    response = client.put(
        f"/api/enterprise/workbench/tasks/{rows['task_colleague']['id']}",
        headers=_headers(rows["manager"]),
        json={
            "tenant_id": "tenant_a",
            "version": 0,
            "assignee_user_id": rows["member"]["id"],
        },
    )
    assert response.status_code == 200, response.text
    event = response.json()["events"][-1]
    assert event["event_type"] == "task_assigned"
    assert event["payload"]["previous_assignee_user_id"] == rows["colleague"]["id"]
    assert event["payload"]["new_assignee_user_id"] == rows["member"]["id"]


def test_department_manager_update_uses_compare_and_swap_before_role_sync(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    _, engine, rows = workbench_boundary
    first = Session(engine)
    stale = Session(engine)
    try:
        first_department = first.get(Department, rows["engineering"]["id"])
        stale_department = stale.get(Department, rows["engineering"]["id"])
        assert first_department is not None and stale_department is not None
        assert first_department.manager_user_id == rows["manager"]["id"]
        assert stale_department.manager_user_id == rows["manager"]["id"]

        update_department(
            first,
            first_department,
            {"manager_user_id": rows["colleague"]["id"]},
        )
        with pytest.raises(HTTPException) as conflict:
            update_department(
                stale,
                stale_department,
                {"manager_user_id": rows["reviewer"]["id"]},
            )
        assert conflict.value.status_code == 409
    finally:
        first.close()
        stale.close()

    with Session(engine) as db:
        department = db.get(Department, rows["engineering"]["id"])
        old_manager = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        winning_manager = db.get(EmployeeProfile, rows["profile_colleague"]["id"])
        losing_manager = db.get(EmployeeProfile, rows["profile_reviewer"]["id"])
        assert department is not None
        assert old_manager is not None
        assert winning_manager is not None
        assert losing_manager is not None
        assert department.manager_user_id == rows["colleague"]["id"]
        assert old_manager.business_role == "member"
        assert winning_manager.business_role == "manager"
        assert losing_manager.business_role == "member"


def test_stale_active_department_cannot_assign_manager_after_archive(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    _, engine, rows = workbench_boundary
    archiver = Session(engine)
    stale = Session(engine)
    try:
        archived_department = archiver.get(Department, rows["engineering"]["id"])
        stale_department = stale.get(Department, rows["engineering"]["id"])
        assert archived_department is not None and stale_department is not None
        assert archived_department.status == "active"
        assert stale_department.status == "active"

        update_department(archiver, archived_department, {"status": "archived"})
        with pytest.raises(HTTPException) as conflict:
            update_department(
                stale,
                stale_department,
                {"manager_user_id": rows["colleague"]["id"]},
            )
        assert conflict.value.status_code == 409
    finally:
        archiver.close()
        stale.close()

    with Session(engine) as db:
        department = db.get(Department, rows["engineering"]["id"])
        previous_manager = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        losing_candidate = db.get(EmployeeProfile, rows["profile_colleague"]["id"])
        assert department is not None
        assert previous_manager is not None
        assert losing_candidate is not None
        assert department.status == "archived"
        assert department.manager_user_id == rows["manager"]["id"]
        assert previous_manager.business_role == "member"
        assert losing_candidate.business_role == "member"


def test_stale_department_cannot_archive_after_manager_change(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    _, engine, rows = workbench_boundary
    assigner = Session(engine)
    stale = Session(engine)
    try:
        assigned_department = assigner.get(Department, rows["engineering"]["id"])
        stale_department = stale.get(Department, rows["engineering"]["id"])
        assert assigned_department is not None and stale_department is not None
        assert assigned_department.manager_user_id == rows["manager"]["id"]
        assert stale_department.manager_user_id == rows["manager"]["id"]

        update_department(
            assigner,
            assigned_department,
            {"manager_user_id": rows["colleague"]["id"]},
        )
        with pytest.raises(HTTPException) as conflict:
            update_department(stale, stale_department, {"status": "archived"})
        assert conflict.value.status_code == 409
    finally:
        assigner.close()
        stale.close()

    with Session(engine) as db:
        department = db.get(Department, rows["engineering"]["id"])
        previous_manager = db.get(EmployeeProfile, rows["profile_manager"]["id"])
        winning_manager = db.get(EmployeeProfile, rows["profile_colleague"]["id"])
        assert department is not None
        assert previous_manager is not None
        assert winning_manager is not None
        assert department.status == "active"
        assert department.manager_user_id == rows["colleague"]["id"]
        assert previous_manager.business_role == "member"
        assert winning_manager.business_role == "manager"


def test_task_page_returns_exact_total_without_changing_legacy_list_contract(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        for index in range(12):
            db.add(
                WorkTask(
                    tenant_id="tenant_a",
                    project_id=rows["project"]["id"],
                    title=f"Envelope {index:02d}",
                    assignee_user_id=rows["member"]["id"],
                )
            )
        db.commit()

    params = {
        "tenant_id": "tenant_a",
        "scope": "mine",
        "status": "backlog",
        "limit": 5,
        "offset": 3,
    }
    legacy = client.get(
        "/api/enterprise/workbench/tasks",
        params=params,
        headers=_headers(rows["member"]),
    )
    page = client.get(
        "/api/enterprise/workbench/tasks/page",
        params=params,
        headers=_headers(rows["member"]),
    )
    assert legacy.status_code == 200, legacy.text
    assert isinstance(legacy.json(), list)
    assert len(legacy.json()) == 5
    assert page.status_code == 200, page.text
    assert page.json()["limit"] == 5
    assert page.json()["offset"] == 3
    assert page.json()["total"] == 13
    assert page.json()["items"] == legacy.json()


def test_dashboard_caps_details_but_keeps_full_query_side_aggregates(
    workbench_boundary: tuple[TestClient, Engine, dict[str, dict[str, str]]],
) -> None:
    client, engine, rows = workbench_boundary
    with Session(engine) as db:
        for index in range(25):
            project = WorkProject(
                tenant_id="tenant_a",
                name=f"Bounded dashboard {index:02d}",
                objective="bounded details",
                owner_user_id=rows["member"]["id"],
                department_id=rows["engineering"]["id"],
                health="at_risk",
            )
            db.add(project)
            db.flush()
            db.add(
                WorkTask(
                    tenant_id="tenant_a",
                    project_id=project.id,
                    title=f"Bounded review {index:02d}",
                    status="review",
                    assignee_user_id=rows["member"]["id"],
                    reviewer_user_id=rows["member"]["id"],
                    due_date=date(2026, 1, 1),
                    result_summary="ready",
                )
            )
        db.commit()

    response = client.get(
        "/api/enterprise/workbench/dashboard",
        params={"tenant_id": "tenant_a"},
        headers=_headers(rows["member"]),
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["project_count"] == 26
    assert sum(data["task_counts"].values()) == 40
    assert data["task_counts"]["review"] == 28
    assert data["pending_review_count"] == 25
    assert data["at_risk_project_count"] == 25
    assert len(data["pending_reviews"]) == 20
    assert len(data["at_risk_tasks"]) == 20
    assert len(data["project_summaries"]) == 20
    assert len(data["recent_events"]) <= 20
    assert len(data["workload_rows"]) <= 20
    assert len(data["department_loads"]) <= 20
