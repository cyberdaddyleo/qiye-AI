from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.db.models import (
    Department,
    EmployeeProfile,
    Tenant,
    User,
    WorkProject,
    WorkTask,
    WorkTaskEvent,
    utc_now,
)
from app.main import app
from app.security.auth import create_access_token
from app.workbench.service import (
    WORK_TASK_TRANSITIONS,
    review_task,
    update_project,
    update_task,
)


def _headers(user: dict[str, str]) -> dict[str, str]:
    token_user = User(
        id=user["id"],
        tenant_id=user["tenant_id"],
        username=user["username"],
        password_hash="hash",
    )
    return {"Authorization": f"Bearer {create_access_token(token_user)}"}


def _seed(engine) -> dict[str, dict[str, str]]:
    with Session(engine) as db:
        db.add_all([Tenant(id="tenant_a", name="A"), Tenant(id="tenant_b", name="B")])
        users = {
            "ceo": User(tenant_id="tenant_a", username="ceo", password_hash="hash"),
            "manager": User(tenant_id="tenant_a", username="manager", password_hash="hash"),
            "member": User(tenant_id="tenant_a", username="member", password_hash="hash"),
            "reviewer": User(tenant_id="tenant_a", username="reviewer", password_hash="hash"),
            "other": User(tenant_id="tenant_a", username="other", password_hash="hash"),
            "outsider": User(tenant_id="tenant_b", username="outsider", password_hash="hash"),
        }
        db.add_all(users.values())
        db.flush()
        engineering = Department(tenant_id="tenant_a", name="Engineering", code="ENG")
        design = Department(tenant_id="tenant_a", name="Design", code="DES")
        foreign = Department(tenant_id="tenant_b", name="Foreign", code="FOR")
        db.add_all([engineering, design, foreign])
        db.flush()
        engineering.manager_user_id = users["manager"].id
        db.add_all(
            [
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["ceo"].id,
                    business_role="ceo",
                ),
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["manager"].id,
                    department_id=engineering.id,
                    business_role="manager",
                ),
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["member"].id,
                    department_id=engineering.id,
                    business_role="member",
                ),
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["reviewer"].id,
                    department_id=engineering.id,
                    business_role="member",
                ),
                EmployeeProfile(
                    tenant_id="tenant_a",
                    user_id=users["other"].id,
                    department_id=design.id,
                    business_role="member",
                ),
                EmployeeProfile(
                    tenant_id="tenant_b",
                    user_id=users["outsider"].id,
                    department_id=foreign.id,
                    business_role="member",
                ),
            ]
        )
        db.commit()
        result = {
            name: {
                "id": user.id,
                "tenant_id": user.tenant_id,
                "username": user.username,
            }
            for name, user in users.items()
        }
        result["engineering"] = {"id": engineering.id}
        result["design"] = {"id": design.id}
        result["foreign"] = {"id": foreign.id}
        return result


def _client_and_rows():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    rows = _seed(engine)

    def override_get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app), engine, rows


def _create_project(client: TestClient, rows: dict[str, dict[str, str]]) -> dict:
    response = client.post(
        "/api/enterprise/workbench/projects",
        headers=_headers(rows["manager"]),
        json={
            "tenant_id": "tenant_a",
            "name": "Launch",
            "objective": "Ship the workbench",
            "department_id": rows["engineering"]["id"],
            "owner_user_id": rows["manager"]["id"],
            "due_date": (datetime.now(UTC).date() + timedelta(days=14)).isoformat(),
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _create_task(
    client: TestClient,
    rows: dict[str, dict[str, str]],
    project_id: str,
    title: str,
    dependencies: list[str] | None = None,
) -> dict:
    response = client.post(
        "/api/enterprise/workbench/tasks",
        headers=_headers(rows["manager"]),
        json={
            "tenant_id": "tenant_a",
            "project_id": project_id,
            "title": title,
            "assignee_user_id": rows["member"]["id"],
            "reviewer_user_id": rows["reviewer"]["id"],
            "dependencies": dependencies or [],
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _finish_task(
    client: TestClient,
    rows: dict[str, dict[str, str]],
    task: dict,
) -> dict:
    started = client.put(
        f"/api/enterprise/workbench/tasks/{task['id']}",
        headers=_headers(rows["member"]),
        json={"tenant_id": "tenant_a", "version": task["version"], "status": "in_progress"},
    )
    assert started.status_code == 200, started.text
    submitted = client.post(
        f"/api/enterprise/workbench/tasks/{task['id']}/submit",
        headers=_headers(rows["member"]),
        json={
            "tenant_id": "tenant_a",
            "version": started.json()["version"],
            "result_summary": f"Finished {task['title']}",
            "artifact_refs": [f"resource:{task['id']}"],
        },
    )
    assert submitted.status_code == 200, submitted.text
    reviewed = client.post(
        f"/api/enterprise/workbench/tasks/{task['id']}/review",
        headers=_headers(rows["reviewer"]),
        json={
            "tenant_id": "tenant_a",
            "version": submitted.json()["version"],
            "verdict": "approve",
            "comment": "accepted",
        },
    )
    assert reviewed.status_code == 200, reviewed.text
    return reviewed.json()


def test_transition_graph_and_audited_submit_review_workflow() -> None:
    assert WORK_TASK_TRANSITIONS == {
        "blocked": {"backlog", "canceled"},
        "backlog": {"in_progress", "canceled"},
        "in_progress": {"review", "canceled"},
        "review": {"done", "in_progress"},
        "done": set(),
        "canceled": set(),
    }
    client, engine, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        task = _create_task(client, rows, project["id"], "Implement API")
        assert task["status"] == "backlog"
        assert [event["event_type"] for event in task["events"]] == [
            "task_created",
            "task_assigned",
        ]

        forbidden_start = client.put(
            f"/api/enterprise/workbench/tasks/{task['id']}",
            headers=_headers(rows["reviewer"]),
            json={"tenant_id": "tenant_a", "version": 0, "status": "in_progress"},
        )
        assert forbidden_start.status_code == 403

        started = client.put(
            f"/api/enterprise/workbench/tasks/{task['id']}",
            headers=_headers(rows["member"]),
            json={"tenant_id": "tenant_a", "version": 0, "status": "in_progress"},
        )
        assert started.status_code == 200, started.text
        assert started.json()["version"] == 1

        progressed = client.put(
            f"/api/enterprise/workbench/tasks/{task['id']}",
            headers=_headers(rows["manager"]),
            json={"tenant_id": "tenant_a", "version": 1, "progress": 60},
        )
        assert progressed.status_code == 200, progressed.text

        comment = client.post(
            f"/api/enterprise/workbench/tasks/{task['id']}/comments",
            headers=_headers(rows["reviewer"]),
            json={"tenant_id": "tenant_a", "version": 2, "comment": "Looks close"},
        )
        assert comment.status_code == 200, comment.text
        hidden_comment = client.post(
            f"/api/enterprise/workbench/tasks/{task['id']}/comments",
            headers=_headers(rows["other"]),
            json={"tenant_id": "tenant_a", "version": 3, "comment": "I should not see this"},
        )
        assert hidden_comment.status_code == 403

        forbidden_submit = client.post(
            f"/api/enterprise/workbench/tasks/{task['id']}/submit",
            headers=_headers(rows["reviewer"]),
            json={
                "tenant_id": "tenant_a",
                "version": 3,
                "result_summary": "wrong actor",
                "artifact_refs": [],
            },
        )
        assert forbidden_submit.status_code == 403

        submitted = client.post(
            f"/api/enterprise/workbench/tasks/{task['id']}/submit",
            headers=_headers(rows["member"]),
            json={
                "tenant_id": "tenant_a",
                "version": 3,
                "result_summary": "Implemented and verified",
                "artifact_refs": ["resource:report", "upload:screenshot"],
            },
        )
        assert submitted.status_code == 200, submitted.text
        assert submitted.json()["status"] == "review"
        assert submitted.json()["result_summary"] == "Implemented and verified"

        forbidden_review = client.post(
            f"/api/enterprise/workbench/tasks/{task['id']}/review",
            headers=_headers(rows["member"]),
            json={
                "tenant_id": "tenant_a",
                "version": 4,
                "verdict": "approve",
                "comment": "self approval",
            },
        )
        assert forbidden_review.status_code == 403
        reviewed = client.post(
            f"/api/enterprise/workbench/tasks/{task['id']}/review",
            headers=_headers(rows["reviewer"]),
            json={
                "tenant_id": "tenant_a",
                "version": 4,
                "verdict": "approve",
                "comment": "accepted",
            },
        )
        assert reviewed.status_code == 200, reviewed.text
        detail = reviewed.json()
        assert detail["status"] == "done"
        assert detail["progress"] == 100

        events = detail["events"]
        by_type = {event["event_type"]: event for event in events}
        assert by_type["task_started"]["payload"] == {
            "old_status": "backlog",
            "new_status": "in_progress",
        }
        assert by_type["progress_updated"]["payload"] == {
            "old_status": "in_progress",
            "new_status": "in_progress",
            "old_progress": 0,
            "new_progress": 60,
        }
        assert by_type["result_submitted"]["payload"] == {
            "old_status": "in_progress",
            "new_status": "review",
            "result_summary": "Implemented and verified",
            "artifact_refs": ["resource:report", "upload:screenshot"],
        }
        assert by_type["review_approved"]["payload"]["old_status"] == "review"
        assert by_type["review_approved"]["payload"]["new_status"] == "done"
        for event in events:
            assert event["actor_user_id"]
            assert "old_status" in event["payload"]
            assert "new_status" in event["payload"]

        with Session(engine) as db:
            project_event = db.exec(
                select(WorkTaskEvent).where(
                    WorkTaskEvent.task_id == project["id"],
                    WorkTaskEvent.event_type == "project_created",
                )
            ).one()
            assert project_event.actor_user_id == rows["manager"]["id"]
            assert project_event.payload_json["new_status"] == "active"
    finally:
        app.dependency_overrides.clear()


def test_review_return_and_manager_actions_follow_state_machine() -> None:
    client, _, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        task = _create_task(client, rows, project["id"], "Draft plan")
        started = client.put(
            f"/api/enterprise/workbench/tasks/{task['id']}",
            headers=_headers(rows["manager"]),
            json={"tenant_id": "tenant_a", "version": 0, "status": "in_progress"},
        ).json()
        submitted = client.post(
            f"/api/enterprise/workbench/tasks/{task['id']}/submit",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": started["version"],
                "result_summary": "draft",
                "artifact_refs": [],
            },
        ).json()
        returned = client.post(
            f"/api/enterprise/workbench/tasks/{task['id']}/review",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": submitted["version"],
                "verdict": "rework",
                "comment": "add evidence",
            },
        )
        assert returned.status_code == 200, returned.text
        assert returned.json()["status"] == "in_progress"
        event = returned.json()["events"][-1]
        assert event["event_type"] == "review_returned"
        assert event["payload"]["comment"] == "add evidence"

        invalid = client.put(
            f"/api/enterprise/workbench/tasks/{task['id']}",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": returned.json()["version"],
                "status": "done",
            },
        )
        assert invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_dependencies_activate_one_level_reject_cycles_and_preserve_stale_updates() -> None:
    client, engine, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        task_a = _create_task(client, rows, project["id"], "A")
        task_b = _create_task(client, rows, project["id"], "B", [task_a["id"]])
        task_c = _create_task(client, rows, project["id"], "C", [task_b["id"]])
        assert task_a["status"] == "backlog"
        assert task_b["status"] == "blocked"
        assert task_c["status"] == "blocked"

        cycle = client.put(
            f"/api/enterprise/workbench/tasks/{task_a['id']}",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": task_a["version"],
                "dependencies": [task_c["id"]],
            },
        )
        assert cycle.status_code == 422

        updated = client.put(
            f"/api/enterprise/workbench/tasks/{task_a['id']}",
            headers=_headers(rows["manager"]),
            json={"tenant_id": "tenant_a", "version": 0, "title": "A updated"},
        )
        assert updated.status_code == 200, updated.text
        stale = client.put(
            f"/api/enterprise/workbench/tasks/{task_a['id']}",
            headers=_headers(rows["manager"]),
            json={"tenant_id": "tenant_a", "version": 0, "title": "stale overwrite"},
        )
        assert stale.status_code == 409
        assert (
            client.get(
                f"/api/enterprise/workbench/tasks/{task_a['id']}",
                params={"tenant_id": "tenant_a"},
                headers=_headers(rows["manager"]),
            ).json()["title"]
            == "A updated"
        )

        done_a = _finish_task(client, rows, updated.json())
        assert done_a["status"] == "done"
        b_detail = client.get(
            f"/api/enterprise/workbench/tasks/{task_b['id']}",
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["manager"]),
        ).json()
        c_detail = client.get(
            f"/api/enterprise/workbench/tasks/{task_c['id']}",
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["manager"]),
        ).json()
        assert b_detail["status"] == "backlog"
        assert c_detail["status"] == "blocked"
        assert b_detail["events"][-1]["event_type"] == "dependency_unblocked"

        done_b = _finish_task(client, rows, b_detail)
        assert done_b["status"] == "done"
        c_detail = client.get(
            f"/api/enterprise/workbench/tasks/{task_c['id']}",
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["manager"]),
        ).json()
        assert c_detail["status"] == "backlog"

        with Session(engine) as db:
            events = db.exec(
                select(WorkTaskEvent).where(WorkTaskEvent.event_type == "dependency_unblocked")
            ).all()
            assert [event.task_id for event in events] == [task_b["id"], task_c["id"]]
            assert all(event.actor_type == "system" for event in events)
    finally:
        app.dependency_overrides.clear()


def test_server_applies_task_project_dashboard_scope_and_tenant_checks() -> None:
    client, engine, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        task = _create_task(client, rows, project["id"], "Visible engineering task")

        member_mine = client.get(
            "/api/enterprise/workbench/tasks",
            params={"tenant_id": "tenant_a", "scope": "mine"},
            headers=_headers(rows["member"]),
        )
        assert member_mine.status_code == 200
        assert [item["id"] for item in member_mine.json()] == [task["id"]]
        assert (
            client.get(
                "/api/enterprise/workbench/tasks",
                params={"tenant_id": "tenant_a", "scope": "department"},
                headers=_headers(rows["member"]),
            ).status_code
            == 403
        )
        assert (
            client.get(
                "/api/enterprise/workbench/tasks",
                params={"tenant_id": "tenant_a", "scope": "all"},
                headers=_headers(rows["manager"]),
            ).status_code
            == 403
        )
        manager_department = client.get(
            "/api/enterprise/workbench/tasks",
            params={"tenant_id": "tenant_a", "scope": "department", "status": "backlog"},
            headers=_headers(rows["manager"]),
        )
        assert [item["id"] for item in manager_department.json()] == [task["id"]]
        ceo_all = client.get(
            "/api/enterprise/workbench/tasks",
            params={"tenant_id": "tenant_a", "scope": "all"},
            headers=_headers(rows["ceo"]),
        )
        assert [item["id"] for item in ceo_all.json()] == [task["id"]]
        assert (
            client.get(
                f"/api/enterprise/workbench/tasks/{task['id']}",
                params={"tenant_id": "tenant_a"},
                headers=_headers(rows["other"]),
            ).status_code
            == 403
        )

        visible_projects = client.get(
            "/api/enterprise/workbench/projects",
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["member"]),
        )
        assert visible_projects.status_code == 200
        assert visible_projects.json()[0]["task_total"] == 1
        assert visible_projects.json()[0]["task_done"] == 0
        assert visible_projects.json()[0]["progress"] == 0

        member_dashboard = client.get(
            "/api/enterprise/workbench/dashboard",
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["member"]),
        )
        assert member_dashboard.status_code == 200, member_dashboard.text
        member_data = member_dashboard.json()
        assert member_data["task_counts"] == {"backlog": 1}
        assert member_data["employee_count"] == 1
        assert member_data["pending_reviews"] == []
        assert all(
            event["task_id"] in {task["id"], project["id"]}
            for event in member_data["recent_events"]
        )

        ceo_dashboard = client.get(
            "/api/enterprise/workbench/dashboard",
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["ceo"]),
        )
        assert ceo_dashboard.status_code == 200
        assert ceo_dashboard.json()["employee_count"] == 5
        assert ceo_dashboard.json()["project_summaries"][0]["id"] == project["id"]
        assert ceo_dashboard.json()["workload_rows"]

        cross_tenant_user = client.post(
            "/api/enterprise/workbench/tasks",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "project_id": project["id"],
                "title": "Bad assignment",
                "assignee_user_id": rows["outsider"]["id"],
            },
        )
        assert cross_tenant_user.status_code == 404
        with Session(engine) as db:
            assert (
                db.exec(select(WorkTask).where(WorkTask.title == "Bad assignment")).first() is None
            )

        tenant_mismatch = client.get(
            f"/api/enterprise/workbench/tasks/{task['id']}",
            params={"tenant_id": "tenant_b"},
            headers=_headers(rows["outsider"]),
        )
        assert tenant_mismatch.status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_optimistic_lock_rejects_a_second_session_that_loaded_the_old_version() -> None:
    client, engine, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        task = _create_task(client, rows, project["id"], "Concurrent edit")
        with Session(engine) as first, Session(engine) as second:
            first_copy = first.get(WorkTask, task["id"])
            second_copy = second.get(WorkTask, task["id"])
            assert first_copy is not None
            assert second_copy is not None

            update_task(
                first,
                first_copy,
                {"title": "first writer"},
                0,
                rows["manager"]["id"],
            )
            with pytest.raises(HTTPException) as conflict:
                update_task(
                    second,
                    second_copy,
                    {"title": "second writer"},
                    0,
                    rows["manager"]["id"],
                )
            assert conflict.value.status_code == 409

        with Session(engine) as db:
            persisted = db.get(WorkTask, task["id"])
            assert persisted is not None
            assert persisted.title == "first writer"
            assert persisted.version == 1
    finally:
        app.dependency_overrides.clear()


def test_generic_update_handles_manual_unblock_cancel_and_illegal_transitions() -> None:
    client, _, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        blocked = client.post(
            "/api/enterprise/workbench/tasks",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "project_id": project["id"],
                "title": "Manual hold",
                "status": "blocked",
                "assignee_user_id": rows["member"]["id"],
            },
        ).json()

        unblocked = client.put(
            f"/api/enterprise/workbench/tasks/{blocked['id']}",
            headers=_headers(rows["manager"]),
            json={"tenant_id": "tenant_a", "version": 0, "status": "backlog"},
        )
        assert unblocked.status_code == 200, unblocked.text
        assert unblocked.json()["status"] == "backlog"

        illegal = client.put(
            f"/api/enterprise/workbench/tasks/{blocked['id']}",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": unblocked.json()["version"],
                "status": "done",
            },
        )
        assert illegal.status_code == 422

        canceled = client.put(
            f"/api/enterprise/workbench/tasks/{blocked['id']}",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": unblocked.json()["version"],
                "status": "canceled",
            },
        )
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["status"] == "canceled"

        invalid_terminal = client.put(
            f"/api/enterprise/workbench/tasks/{blocked['id']}",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": canceled.json()["version"],
                "status": "backlog",
            },
        )
        assert invalid_terminal.status_code == 422
    finally:
        app.dependency_overrides.clear()


def test_dependency_edits_do_not_rewrite_active_or_terminal_state() -> None:
    client, engine, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        dependency = _create_task(client, rows, project["id"], "Dependency")
        task_ids: dict[str, str] = {}
        with Session(engine) as db:
            for status in ("in_progress", "review", "done", "canceled"):
                task = WorkTask(
                    tenant_id="tenant_a",
                    project_id=project["id"],
                    title=f"State {status}",
                    status=status,
                    assignee_user_id=rows["member"]["id"],
                    reviewer_user_id=rows["reviewer"]["id"],
                    completed_at=utc_now() if status == "done" else None,
                )
                db.add(task)
                db.flush()
                task_ids[status] = task.id
            db.commit()

        for status, task_id in task_ids.items():
            before = client.get(
                f"/api/enterprise/workbench/tasks/{task_id}",
                params={"tenant_id": "tenant_a"},
                headers=_headers(rows["manager"]),
            ).json()
            response = client.put(
                f"/api/enterprise/workbench/tasks/{task_id}",
                headers=_headers(rows["manager"]),
                json={
                    "tenant_id": "tenant_a",
                    "version": before["version"],
                    "dependencies": [dependency["id"]],
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["status"] == status
            assert response.json()["completed_at"] == before["completed_at"]
    finally:
        app.dependency_overrides.clear()


def test_project_update_uses_database_compare_and_swap() -> None:
    client, engine, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        assert project["version"] == 0
        with Session(engine) as first, Session(engine) as second:
            first_copy = first.get(WorkProject, project["id"])
            second_copy = second.get(WorkProject, project["id"])
            assert first_copy is not None
            assert second_copy is not None

            updated = update_project(
                first,
                first_copy,
                {"name": "first project writer"},
                0,
                rows["manager"]["id"],
            )
            assert updated.version == 1
            with pytest.raises(HTTPException) as conflict:
                update_project(
                    second,
                    second_copy,
                    {"name": "stale project writer"},
                    0,
                    rows["manager"]["id"],
                )
            assert conflict.value.status_code == 409

        with Session(engine) as db:
            persisted = db.get(WorkProject, project["id"])
            assert persisted is not None
            assert persisted.name == "first project writer"
            assert persisted.version == 1

        stale_response = client.put(
            f"/api/enterprise/workbench/projects/{project['id']}",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": 0,
                "objective": "stale API overwrite",
            },
        )
        assert stale_response.status_code == 409
        fresh_response = client.put(
            f"/api/enterprise/workbench/projects/{project['id']}",
            headers=_headers(rows["manager"]),
            json={
                "tenant_id": "tenant_a",
                "version": 1,
                "objective": "fresh API update",
            },
        )
        assert fresh_response.status_code == 200, fresh_response.text
        assert fresh_response.json()["version"] == 2
    finally:
        app.dependency_overrides.clear()


def test_parallel_prerequisite_completion_conflicts_then_unblocks_once() -> None:
    client, engine, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        task_a = _create_task(client, rows, project["id"], "Parallel A")
        task_b = _create_task(client, rows, project["id"], "Parallel B")
        successor = _create_task(
            client, rows, project["id"], "Parallel successor", [task_a["id"], task_b["id"]]
        )
        review_tasks = []
        for task in (task_a, task_b):
            started = client.put(
                f"/api/enterprise/workbench/tasks/{task['id']}",
                headers=_headers(rows["member"]),
                json={"tenant_id": "tenant_a", "version": 0, "status": "in_progress"},
            ).json()
            review_tasks.append(
                client.post(
                    f"/api/enterprise/workbench/tasks/{task['id']}/submit",
                    headers=_headers(rows["member"]),
                    json={
                        "tenant_id": "tenant_a",
                        "version": started["version"],
                        "result_summary": task["title"],
                        "artifact_refs": [],
                    },
                ).json()
            )

        with Session(engine) as first, Session(engine) as second:
            first_project = first.get(WorkProject, project["id"])
            second_project = second.get(WorkProject, project["id"])
            assert first_project is not None
            assert second_project is not None
            assert first_project.version == second_project.version
            first_task = first.get(WorkTask, review_tasks[0]["id"])
            second_task = second.get(WorkTask, review_tasks[1]["id"])
            assert first_task is not None
            assert second_task is not None
            review_task(
                first,
                first_task,
                review_tasks[0]["version"],
                "approve",
                None,
                rows["reviewer"]["id"],
            )
            with pytest.raises(HTTPException) as conflict:
                review_task(
                    second,
                    second_task,
                    review_tasks[1]["version"],
                    "approve",
                    None,
                    rows["reviewer"]["id"],
                )
            assert conflict.value.status_code == 409

        with Session(engine) as retry:
            retry_task = retry.get(WorkTask, review_tasks[1]["id"])
            assert retry_task is not None
            review_task(
                retry,
                retry_task,
                review_tasks[1]["version"],
                "approve",
                None,
                rows["reviewer"]["id"],
            )

        with Session(engine) as db:
            persisted_successor = db.get(WorkTask, successor["id"])
            assert persisted_successor is not None
            assert persisted_successor.status == "backlog"
            unblocked_events = db.exec(
                select(WorkTaskEvent).where(
                    WorkTaskEvent.task_id == successor["id"],
                    WorkTaskEvent.event_type == "dependency_unblocked",
                )
            ).all()
            assert len(unblocked_events) == 1
    finally:
        app.dependency_overrides.clear()


def test_dashboard_includes_cross_department_assignment_review_and_owned_project_tasks() -> None:
    client, _, rows = _client_and_rows()
    try:
        task_ids = []
        for relation in ("assignee", "reviewer", "owner"):
            project_response = client.post(
                "/api/enterprise/workbench/projects",
                headers=_headers(rows["manager"]),
                json={
                    "tenant_id": "tenant_a",
                    "name": f"Cross department {relation}",
                    "objective": "Verify dashboard scope",
                    "department_id": rows["engineering"]["id"],
                    "owner_user_id": (
                        rows["other"]["id"] if relation == "owner" else rows["manager"]["id"]
                    ),
                },
            )
            assert project_response.status_code == 201, project_response.text
            task_response = client.post(
                "/api/enterprise/workbench/tasks",
                headers=_headers(rows["manager"]),
                json={
                    "tenant_id": "tenant_a",
                    "project_id": project_response.json()["id"],
                    "title": relation,
                    "assignee_user_id": (
                        rows["other"]["id"] if relation == "assignee" else rows["member"]["id"]
                    ),
                    "reviewer_user_id": (
                        rows["other"]["id"]
                        if relation == "reviewer"
                        else rows["reviewer"]["id"]
                    ),
                },
            )
            assert task_response.status_code == 201, task_response.text
            task_ids.append(task_response.json()["id"])

        dashboard = client.get(
            "/api/enterprise/workbench/dashboard",
            params={"tenant_id": "tenant_a"},
            headers=_headers(rows["other"]),
        )
        assert dashboard.status_code == 200, dashboard.text
        assert dashboard.json()["task_counts"] == {"backlog": 3}
        recent_task_ids = {event["task_id"] for event in dashboard.json()["recent_events"]}
        assert set(task_ids).issubset(recent_task_ids)
    finally:
        app.dependency_overrides.clear()


def test_explicit_null_for_non_nullable_project_and_task_fields_returns_422() -> None:
    client, _, rows = _client_and_rows()
    try:
        project = _create_project(client, rows)
        task = _create_task(client, rows, project["id"], "Null guarded")
        project_response = client.put(
            f"/api/enterprise/workbench/projects/{project['id']}",
            headers=_headers(rows["manager"]),
            json={"tenant_id": "tenant_a", "version": 0, "name": None},
        )
        assert project_response.status_code == 422
        assert any(item["loc"][-1] == "name" for item in project_response.json()["detail"])

        task_response = client.put(
            f"/api/enterprise/workbench/tasks/{task['id']}",
            headers=_headers(rows["manager"]),
            json={"tenant_id": "tenant_a", "version": 0, "progress": None},
        )
        assert task_response.status_code == 422
        assert any(item["loc"][-1] == "progress" for item in task_response.json()["detail"])
    finally:
        app.dependency_overrides.clear()
