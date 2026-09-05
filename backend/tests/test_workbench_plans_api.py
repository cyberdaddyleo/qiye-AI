from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.api import workbench as workbench_api
from app.db import get_session
from app.db.models import (
    Department,
    EmployeeProfile,
    Tenant,
    User,
    WorkPlan,
    WorkProject,
    WorkTask,
    WorkTaskDependency,
)
from app.main import app
from app.security.auth import create_access_token
from app.workbench import service as workbench_service
from app.workbench.service import dispatch_plan


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


@pytest.fixture
def workbench() -> tuple[TestClient, object, dict[str, User], WorkProject]:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id="tenant_a", name="Tenant A"))
        users = {
            "manager": User(
                tenant_id="tenant_a", username="manager-plan", password_hash="hash"
            ),
            "member": User(
                tenant_id="tenant_a", username="member-plan", password_hash="hash"
            ),
            "engineer": User(
                tenant_id="tenant_a", username="engineer-plan", password_hash="hash"
            ),
            "analyst": User(
                tenant_id="tenant_a", username="analyst-plan", password_hash="hash"
            ),
        }
        db.add_all(users.values())
        db.flush()
        user_ids = {name: user.id for name, user in users.items()}
        department = Department(
            tenant_id="tenant_a",
            name="Delivery",
            code="DELIVERY",
            manager_user_id=users["manager"].id,
        )
        db.add(department)
        db.flush()
        db.add_all(
            [
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["manager"].id,
                    department_id=department.id,
                    job_title="Delivery Manager",
                    business_role="manager",
                    skills_json=["planning"],
                ),
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["member"].id,
                    department_id=department.id,
                    job_title="Observer",
                    business_role="member",
                    skills_json=[],
                ),
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["engineer"].id,
                    department_id=department.id,
                    job_title="Backend Engineer",
                    business_role="member",
                    skills_json=["Python", "FastAPI", "testing"],
                    daily_cost=500,
                ),
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["analyst"].id,
                    department_id=department.id,
                    job_title="Business Analyst",
                    business_role="member",
                    skills_json=["research", "planning", "analysis"],
                    daily_cost=300,
                ),
            ]
        )
        project = WorkProject(
            tenant_id="tenant_a",
            name="Workbench launch",
            objective="Launch the enterprise workbench",
            owner_user_id=users["manager"].id,
            department_id=department.id,
            start_date=date(2026, 9, 7),
            due_date=date(2026, 10, 2),
            budget=25_000,
        )
        db.add(project)
        db.commit()
        db.refresh(project)
        project_id = project.id

    def override_get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    with Session(engine) as db:
        detached_users = {name: db.get(User, user_id) for name, user_id in user_ids.items()}
        detached_project = db.get(WorkProject, project_id)
    try:
        yield TestClient(app), engine, detached_users, detached_project
    finally:
        app.dependency_overrides.clear()


def _preview(client: TestClient, manager: User, project: WorkProject) -> dict:
    response = client.post(
        "/api/enterprise/workbench/plans/preview",
        headers=_headers(manager),
        json={
            "tenant_id": "tenant_a",
            "project_id": project.id,
            "goal": "Ship a secure production release",
            "deadline": "2026-10-02",
            "budget": 25_000,
            "constraints": {"compliance": "SOC2"},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _dispatch_tasks(variant: dict) -> list[dict]:
    return [
        {
            "key": task["key"],
            "assignee_user_id": task["assignee_user_id"],
            "start_date": task["start_date"],
            "due_date": task["due_date"],
            "acceptance_criteria": task["acceptance_criteria"],
            "depends_on": list(task["depends_on"]),
        }
        for task in variant["tasks"]
    ]


def test_preview_persists_one_plan_without_creating_tasks_and_get_is_tenant_safe(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, engine, users, project = workbench

    preview = _preview(client, users["manager"], project)

    assert preview["source"] == "fallback"
    assert [variant["key"] for variant in preview["variants"]] == ["A", "B", "C"]
    with Session(engine) as db:
        assert len(db.exec(select(WorkPlan)).all()) == 1
        assert db.exec(select(WorkTask)).all() == []

    fetched = client.get(
        f"/api/enterprise/workbench/plans/{preview['id']}?tenant_id=tenant_a",
        headers=_headers(users["manager"]),
    )
    assert fetched.status_code == 200
    assert fetched.json() == preview
    hidden = client.get(
        f"/api/enterprise/workbench/plans/{preview['id']}?tenant_id=tenant_a",
        headers=_headers(users["member"]),
    )
    assert hidden.status_code == 403


def test_dispatch_is_atomic_preserves_schedule_and_is_idempotent(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, engine, users, project = workbench
    preview = _preview(client, users["manager"], project)
    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")

    response = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["manager"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "dispatch-launch-v1",
            "tasks": _dispatch_tasks(selected),
        },
    )

    assert response.status_code == 201, response.text
    dispatched = response.json()
    expected_by_title = {task["title"]: task for task in selected["tasks"]}
    assert len(dispatched) == len(selected["tasks"])
    for task in dispatched:
        planned = expected_by_title[task["title"]]
        assert task["assignee_user_id"] == planned["assignee_user_id"]
        assert task["reviewer_user_id"] == users["manager"].id
        assert task["start_date"] == planned["start_date"]
        assert task["due_date"] == planned["due_date"]

    repeated = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["manager"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "dispatch-launch-v1",
            "tasks": _dispatch_tasks(selected),
        },
    )
    assert repeated.status_code == 200, repeated.text
    assert [task["id"] for task in repeated.json()] == [task["id"] for task in dispatched]

    with Session(engine) as db:
        stored_plan = db.get(WorkPlan, preview["id"])
        assert stored_plan.status == "dispatched"
        assert stored_plan.selected_variant == "A"
        assert stored_plan.selected_variant_json["tasks"][0]["assignment"] == selected[
            "tasks"
        ][0]["assignment"]
        assert stored_plan.dispatch_overrides_json == []
        assert stored_plan.dispatch_idempotency_key == "dispatch-launch-v1"
        dependencies = db.exec(select(WorkTaskDependency)).all()
        assert dependencies
        assert {dependency.tenant_id for dependency in dependencies} == {"tenant_a"}


def test_dispatch_uses_edited_variant_and_audits_overrides_with_payload_safe_replay(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, engine, users, project = workbench
    preview = _preview(client, users["manager"], project)
    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")
    edited = _dispatch_tasks(selected)
    replacement = (
        users["engineer"]
        if selected["tasks"][0]["assignee_user_id"] != users["engineer"].id
        else users["analyst"]
    )
    edited[0]["assignee_user_id"] = replacement.id
    edited[0]["acceptance_criteria"] = "人工确认：访谈记录与范围清单均已签字"
    edited[-1]["depends_on"] = [edited[0]["key"]]
    edited[-1]["due_date"] = (
        date.fromisoformat(edited[-1]["due_date"]) + timedelta(days=1)
    ).isoformat()
    payload = {
        "tenant_id": "tenant_a",
        "variant_key": "A",
        "idempotency_key": "edited-a-intent",
        "tasks": edited,
    }

    response = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["manager"]),
        json=payload,
    )

    assert response.status_code == 201, response.text
    created = response.json()
    created_by_title = {task["title"]: task for task in created}
    original_by_key = {task["key"]: task for task in selected["tasks"]}
    first_created = created_by_title[original_by_key[edited[0]["key"]]["title"]]
    last_created = created_by_title[original_by_key[edited[-1]["key"]]["title"]]
    assert first_created["assignee_user_id"] == replacement.id
    assert first_created["acceptance_criteria"] == edited[0]["acceptance_criteria"]
    assert last_created["due_date"] == edited[-1]["due_date"]
    assert last_created["dependencies"] == [first_created["id"]]

    with Session(engine) as db:
        stored = db.get(WorkPlan, preview["id"])
        assert stored.selected_variant_json["key"] == "A"
        assert stored.selected_variant_json["tasks"][0]["assignee_user_id"] == replacement.id
        assert stored.selected_variant_json["tasks"][0]["assignment"] == {
            "provenance": "manual",
            "manual_assignment_kind": "reassigned",
            "previous_assignee_user_id": selected["tasks"][0]["assignee_user_id"],
        }
        assert {item["key"] for item in stored.dispatch_overrides_json} == {
            edited[0]["key"],
            edited[-1]["key"],
        }

    fetched = client.get(
        f"/api/enterprise/workbench/plans/{preview['id']}?tenant_id=tenant_a",
        headers=_headers(users["manager"]),
    )
    assert fetched.status_code == 200
    assert fetched.json()["selected_variant_snapshot"]["tasks"][0][
        "acceptance_criteria"
    ] == edited[0]["acceptance_criteria"]
    assert {item["key"] for item in fetched.json()["dispatch_overrides"]} == {
        edited[0]["key"],
        edited[-1]["key"],
    }

    replay = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["manager"]),
        json=payload,
    )
    assert replay.status_code == 200, replay.text
    assert [task["id"] for task in replay.json()] == [task["id"] for task in created]

    changed_payload = {**payload, "tasks": [dict(task) for task in edited]}
    changed_payload["tasks"][0]["acceptance_criteria"] = "不同的同 key 请求"
    conflict = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["manager"]),
        json=changed_payload,
    )
    assert conflict.status_code == 409


def test_dispatch_marks_an_originally_unassigned_task_as_manually_assigned(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, engine, users, project = workbench
    preview = _preview(client, users["manager"], project)
    with Session(engine) as db:
        stored = db.get(WorkPlan, preview["id"])
        variants = deepcopy(stored.variants_json)
        selected = next(variant for variant in variants if variant["key"] == "A")
        selected["tasks"][0]["assignee_user_id"] = None
        selected["tasks"][0]["assignment"] = {"candidate_scores": {}}
        selected["tasks"][0]["unassigned_reason"] = "AI 原方案未找到合适员工"
        stored.variants_json = variants
        db.add(stored)
        db.commit()

    edited = _dispatch_tasks(selected)
    edited[0]["assignee_user_id"] = users["engineer"].id
    response = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["manager"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "originally-unassigned-owner",
            "tasks": edited,
        },
    )

    assert response.status_code == 201, response.text
    with Session(engine) as db:
        stored = db.get(WorkPlan, preview["id"])
        effective_task = stored.selected_variant_json["tasks"][0]
        assert effective_task["assignee_user_id"] == users["engineer"].id
        assert effective_task["assignment"] == {
            "provenance": "manual",
            "manual_assignment_kind": "assigned",
            "previous_assignee_user_id": None,
        }
        assignee_override = next(
            item for item in stored.dispatch_overrides_json if item["key"] == effective_task["key"]
        )["changes"]["assignee_user_id"]
        assert assignee_override == {"from": None, "to": users["engineer"].id}


def test_unauthorized_dispatch_is_forbidden_and_second_key_conflicts(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, _, users, project = workbench
    preview = _preview(client, users["manager"], project)
    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")
    endpoint = f"/api/enterprise/workbench/plans/{preview['id']}/dispatch"

    forbidden = client.post(
        endpoint,
        headers=_headers(users["member"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "forbidden",
            "tasks": _dispatch_tasks(selected),
        },
    )
    assert forbidden.status_code == 403

    first = client.post(
        endpoint,
        headers=_headers(users["manager"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "first",
            "tasks": _dispatch_tasks(selected),
        },
    )
    assert first.status_code == 201
    conflict = client.post(
        endpoint,
        headers=_headers(users["manager"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "second",
            "tasks": _dispatch_tasks(selected),
        },
    )
    assert conflict.status_code == 409


def test_dispatch_rejects_invalid_task_sets_graph_dates_and_assignees(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, engine, users, project = workbench
    preview = _preview(client, users["manager"], project)
    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")
    base = _dispatch_tasks(selected)
    invalid_payloads: list[list[dict]] = []

    missing = [dict(task) for task in base[:-1]]
    invalid_payloads.append(missing)

    missing_editable_field = [dict(task) for task in base]
    missing_editable_field[0].pop("acceptance_criteria")
    invalid_payloads.append(missing_editable_field)

    unknown_dependency = [dict(task) for task in base]
    unknown_dependency[0]["depends_on"] = ["missing-task"]
    invalid_payloads.append(unknown_dependency)

    cycle = [dict(task) for task in base]
    cycle[0]["depends_on"] = [cycle[1]["key"]]
    cycle[1]["depends_on"] = [cycle[0]["key"]]
    invalid_payloads.append(cycle)

    backwards_dates = [dict(task) for task in base]
    backwards_dates[0]["start_date"] = "2026-09-12"
    backwards_dates[0]["due_date"] = "2026-09-11"
    invalid_payloads.append(backwards_dates)

    for index, tasks in enumerate(invalid_payloads):
        response = client.post(
            f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
            headers=_headers(users["manager"]),
            json={
                "tenant_id": "tenant_a",
                "variant_key": "A",
                "idempotency_key": f"invalid-graph-{index}",
                "tasks": tasks,
            },
        )
        assert response.status_code == 422, response.text

    with Session(engine) as db:
        member_profile = db.exec(
            select(EmployeeProfile).where(
                EmployeeProfile.tenant_id == "tenant_a",
                EmployeeProfile.user_id == users["member"].id,
            )
        ).one()
        member_profile.status = "inactive"
        db.add(member_profile)
        db.add(Tenant(id="tenant_b", name="Tenant B"))
        outsider = User(tenant_id="tenant_b", username="outsider-plan", password_hash="hash")
        db.add(outsider)
        db.flush()
        db.add(
            EmployeeProfile(
                tenant_id="tenant_b",
                user_id=outsider.id,
                business_role="member",
                status="active",
            )
        )
        db.commit()
        outsider_id = outsider.id

    for index, assignee_id in enumerate((users["member"].id, outsider_id)):
        tasks = [dict(task) for task in base]
        tasks[0]["assignee_user_id"] = assignee_id
        response = client.post(
            f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
            headers=_headers(users["manager"]),
            json={
                "tenant_id": "tenant_a",
                "variant_key": "A",
                "idempotency_key": f"invalid-assignee-{index}",
                "tasks": tasks,
            },
        )
        assert response.status_code == 422, response.text


def test_member_project_owner_can_preview_and_dispatch(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, engine, users, project = workbench
    with Session(engine) as db:
        stored_project = db.get(WorkProject, project.id)
        stored_project.owner_user_id = users["member"].id
        db.add(stored_project)
        db.commit()

    preview = _preview(client, users["member"], project)
    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")
    response = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["member"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "member-owner-intent",
            "tasks": _dispatch_tasks(selected),
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()


def test_manager_owner_plan_candidates_stay_inside_exact_managed_departments(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, engine, users, project = workbench
    with Session(engine) as db:
        project_department = db.get(Department, project.department_id)
        project_department.manager_user_id = users["analyst"].id
        db.add(project_department)
        managed_department = Department(
            tenant_id="tenant_a",
            name="Manager scope",
            code="MANAGER_SCOPE",
            manager_user_id=users["manager"].id,
        )
        managed_worker = User(
            tenant_id="tenant_a",
            username="managed-worker-plan",
            password_hash="hash",
        )
        db.add_all([managed_department, managed_worker])
        db.flush()
        db.add(
            EmployeeProfile(
                tenant_id="tenant_a",
                user_id=managed_worker.id,
                department_id=managed_department.id,
                job_title="Backend Engineer",
                business_role="member",
                skills_json=["python", "fastapi"],
            )
        )
        db.commit()
        managed_worker_id = managed_worker.id

    preview = _preview(client, users["manager"], project)

    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")
    assert {
        candidate_id
        for task in selected["tasks"]
        for candidate_id in task["assignment"]["candidate_scores"]
    } == {managed_worker_id}
    assert {
        task["assignee_user_id"] for task in selected["tasks"] if task["assignee_user_id"]
    } <= {managed_worker_id}


def test_member_owner_plan_candidates_stay_inside_the_project_department(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, engine, users, project = workbench
    with Session(engine) as db:
        stored_project = db.get(WorkProject, project.id)
        stored_project.owner_user_id = users["member"].id
        outside_department = Department(
            tenant_id="tenant_a",
            name="Outside owner scope",
            code="OUTSIDE_OWNER_SCOPE",
            manager_user_id=users["analyst"].id,
        )
        outside_worker = User(
            tenant_id="tenant_a",
            username="outside-owner-scope-plan",
            password_hash="hash",
        )
        db.add_all([stored_project, outside_department, outside_worker])
        db.flush()
        db.add(
            EmployeeProfile(
                tenant_id="tenant_a",
                user_id=outside_worker.id,
                department_id=outside_department.id,
                job_title="Business Analyst Backend Engineer QA Engineer Delivery Manager",
                business_role="member",
                skills_json=["research", "analysis", "python", "fastapi", "testing", "planning"],
            )
        )
        db.commit()

    preview = _preview(client, users["member"], project)

    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")
    assert {
        candidate_id
        for task in selected["tasks"]
        for candidate_id in task["assignment"]["candidate_scores"]
    } == {
        users["manager"].id,
        users["member"].id,
        users["engineer"].id,
        users["analyst"].id,
    }


def test_dispatch_rolls_back_all_side_effects_on_mid_transaction_failure(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, users, project = workbench
    preview = _preview(client, users["manager"], project)
    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")

    def fail_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("event store unavailable")

    monkeypatch.setattr(workbench_service, "_event", fail_event)
    with Session(engine) as db:
        current_user = db.get(User, users["manager"].id)
        with pytest.raises(RuntimeError, match="event store unavailable"):
            dispatch_plan(
                db,
                preview["id"],
                "A",
                "atomic-key",
                current_user,
                _dispatch_tasks(selected),
            )

    with Session(engine) as db:
        assert db.exec(select(WorkTask)).all() == []
        assert db.exec(select(WorkTaskDependency)).all() == []
        plan = db.get(WorkPlan, preview["id"])
        assert plan.status == "draft"
        assert plan.dispatch_idempotency_key is None


def test_dispatch_race_replay_returns_http_200(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _, users, project = workbench
    preview = _preview(client, users["manager"], project)
    selected = next(variant for variant in preview["variants"] if variant["key"] == "A")

    class ExistingDispatch(list[WorkTask]):
        created = False

    monkeypatch.setattr(
        workbench_api,
        "dispatch_plan",
        lambda *args, **kwargs: ExistingDispatch(),
    )
    response = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["manager"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "same-key-race",
            "tasks": _dispatch_tasks(selected),
        },
    )

    assert response.status_code == 200
