from __future__ import annotations

from datetime import date

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
        },
    )

    assert response.status_code == 201, response.text
    dispatched = response.json()
    expected_by_title = {task["title"]: task for task in selected["tasks"]}
    assert len(dispatched) == len(selected["tasks"])
    for task in dispatched:
        planned = expected_by_title[task["title"]]
        assert task["assignee_user_id"] == planned["assignee_user_id"]
        assert task["start_date"] == planned["start_date"]
        assert task["due_date"] == planned["due_date"]

    repeated = client.post(
        f"/api/enterprise/workbench/plans/{preview['id']}/dispatch",
        headers=_headers(users["manager"]),
        json={
            "tenant_id": "tenant_a",
            "variant_key": "A",
            "idempotency_key": "dispatch-launch-v1",
        },
    )
    assert repeated.status_code == 200, repeated.text
    assert [task["id"] for task in repeated.json()] == [task["id"] for task in dispatched]

    with Session(engine) as db:
        stored_plan = db.get(WorkPlan, preview["id"])
        assert stored_plan.status == "dispatched"
        assert stored_plan.selected_variant == "A"
        assert stored_plan.dispatch_idempotency_key == "dispatch-launch-v1"
        dependencies = db.exec(select(WorkTaskDependency)).all()
        assert dependencies
        assert {dependency.tenant_id for dependency in dependencies} == {"tenant_a"}


def test_unauthorized_dispatch_is_forbidden_and_second_key_conflicts(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject]
) -> None:
    client, _, users, project = workbench
    preview = _preview(client, users["manager"], project)
    endpoint = f"/api/enterprise/workbench/plans/{preview['id']}/dispatch"

    forbidden = client.post(
        endpoint,
        headers=_headers(users["member"]),
        json={"tenant_id": "tenant_a", "variant_key": "A", "idempotency_key": "forbidden"},
    )
    assert forbidden.status_code == 403

    first = client.post(
        endpoint,
        headers=_headers(users["manager"]),
        json={"tenant_id": "tenant_a", "variant_key": "A", "idempotency_key": "first"},
    )
    assert first.status_code == 201
    conflict = client.post(
        endpoint,
        headers=_headers(users["manager"]),
        json={"tenant_id": "tenant_a", "variant_key": "A", "idempotency_key": "second"},
    )
    assert conflict.status_code == 409


def test_dispatch_rolls_back_all_side_effects_on_mid_transaction_failure(
    workbench: tuple[TestClient, object, dict[str, User], WorkProject],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, engine, users, project = workbench
    preview = _preview(client, users["manager"], project)

    def fail_event(*args: object, **kwargs: object) -> None:
        raise RuntimeError("event store unavailable")

    monkeypatch.setattr(workbench_service, "_event", fail_event)
    with Session(engine) as db:
        current_user = db.get(User, users["manager"].id)
        with pytest.raises(RuntimeError, match="event store unavailable"):
            dispatch_plan(db, preview["id"], "A", "atomic-key", current_user)

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
        },
    )

    assert response.status_code == 200
