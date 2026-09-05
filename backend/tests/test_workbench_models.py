from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import (
    Department,
    EmployeeProfile,
    User,
    WorkPlan,
    WorkProject,
    WorkTask,
    WorkTaskDependency,
    WorkTaskEvent,
)
from app.workbench.schema import (
    PlanPreviewRequest,
    PlanRead,
    ProjectRead,
    TaskRead,
    TaskUpdateRequest,
)


@pytest.fixture
def db() -> Session:
    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture
def user(db: Session) -> User:
    row = User(tenant_id="tenant_1", username="lee", password_hash="hashed")
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_workbench_models_round_trip_and_constraints(db: Session, user: User) -> None:
    dept = Department(tenant_id=user.tenant_id, name="技术部", code="TECH")
    db.add(dept)
    db.flush()
    employee = EmployeeProfile(
        tenant_id=user.tenant_id,
        user_id=user.id,
        department_id=dept.id,
        job_title="后端工程师",
        business_role="member",
        skills_json=["Python", "FastAPI"],
    )
    db.add(employee)
    db.commit()
    assert employee.status == "active"
    assert employee.skills_json == ["Python", "FastAPI"]

    project = WorkProject(
        tenant_id=user.tenant_id,
        name="企业工作台",
        objective="交付首版",
        owner_user_id=user.id,
        department_id=dept.id,
        budget=1000.0,
        start_date=date(2026, 9, 1),
    )
    plan = WorkPlan(
        tenant_id=user.tenant_id,
        project_id=project.id,
        created_by_user_id=user.id,
        goal="交付",
        constraints_json={"deadline": "2026-09-30"},
        variants_json=[{"name": "稳健", "model_api_key": "secret"}],
    )
    task_one = WorkTask(
        tenant_id=user.tenant_id,
        project_id=project.id,
        plan_id=plan.id,
        title="建模",
        required_role="engineer",
    )
    task_two = WorkTask(
        tenant_id=user.tenant_id,
        project_id=project.id,
        plan_id=plan.id,
        title="开发",
        required_role="engineer",
    )
    db.add_all([project, plan, task_one, task_two])
    db.flush()
    dependency = WorkTaskDependency(
        tenant_id=user.tenant_id,
        task_id=task_two.id,
        depends_on_task_id=task_one.id,
    )
    event = WorkTaskEvent(
        tenant_id=user.tenant_id,
        task_id=task_one.id,
        actor_user_id=user.id,
        actor_type="user",
        event_type="created",
        payload_json={"source": "test"},
    )
    db.add_all([dependency, event])
    db.commit()

    project_id = project.id
    plan_id = plan.id
    task_one_id = task_one.id
    dependency_id = dependency.id
    event_id = event.id
    db.expire_all()
    assert db.get(WorkProject, project_id).status == "active"
    assert db.get(WorkProject, project_id).version == 0
    assert db.get(WorkPlan, plan_id).status == "draft"
    persisted_task = db.get(WorkTask, task_one_id)
    assert persisted_task.status == "backlog"
    assert persisted_task.progress == 0
    assert persisted_task.version == 0
    assert db.get(WorkPlan, plan_id).variants_json == [{"name": "稳健", "model_api_key": "secret"}]
    assert db.get(WorkTaskEvent, event_id).payload_json == {"source": "test"}
    assert db.get(WorkTaskDependency, dependency_id).tenant_id == user.tenant_id

    db.add(EmployeeProfile(tenant_id=user.tenant_id, user_id=user.id, business_role="member"))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    db.add(
        WorkTaskDependency(
            tenant_id=user.tenant_id,
            task_id=task_two.id,
            depends_on_task_id=task_one.id,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_employee_capacity_has_database_invariant(db: Session, user: User) -> None:
    db.add(
        EmployeeProfile(
            tenant_id=user.tenant_id,
            user_id="user_invalid_capacity",
            business_role="member",
            capacity_percent=101,
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()


def test_workbench_dtos_are_strict_and_normalize_plan_credentials() -> None:
    with pytest.raises(ValidationError):
        PlanPreviewRequest(tenant_id="tenant_1", project_id="project_1", unexpected=True)
    with pytest.raises(ValidationError):
        TaskUpdateRequest(tenant_id="tenant_1", unexpected=True)

    plan = PlanRead(
        id="plan_1",
        tenant_id="tenant_1",
        project_id="project_1",
        created_by_user_id="user_1",
        goal="交付",
        status="draft",
        source="model",
        variants=[
            {
                "name": "稳健",
                "openai_api_key": "secret",
                "authorization": "Bearer secret",
                "assignment": {"access_token": "secret", "assignee": "lee"},
                "tasks": [{"apiKey": "secret", "title": "建模"}],
            }
        ],
        selected_variant=None,
        dispatch_idempotency_key=None,
        created_at="2026-09-04T00:00:00",
        updated_at="2026-09-04T00:00:00",
    )
    task = TaskRead(
        id="task_1",
        tenant_id="tenant_1",
        project_id="project_1",
        plan_id="plan_1",
        title="开发",
        priority="normal",
        status="backlog",
        progress=0,
        version=0,
        created_at="2026-09-04T00:00:00",
        updated_at="2026-09-04T00:00:00",
    )
    assert plan.variants == [
        {
            "name": "稳健",
            "assignment": {"assignee": "lee"},
            "tasks": [{"title": "建模"}],
        }
    ]
    assert task.dependencies == []
    assert task.events == []

    project = ProjectRead(
        id="project_1",
        tenant_id="tenant_1",
        name="Delivery",
        objective="Ship",
        status="active",
        health="on_track",
        version=3,
        created_at="2026-09-04T00:00:00",
        updated_at="2026-09-04T00:00:00",
    )
    assert project.version == 3


def test_workbench_project_and_dispatch_audit_migrate_existing_sqlite_tables() -> None:
    from app.db.database import _migrate_workbench_schema

    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE workbench_projects ("
                "id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, "
                "name VARCHAR NOT NULL, objective VARCHAR NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workbench_projects (id, tenant_id, name, objective) "
                "VALUES ('project_old', 'tenant_1', 'Old', 'Ship')"
            )
        )
        connection.execute(
            text(
                "CREATE TABLE workbench_plans ("
                "id VARCHAR PRIMARY KEY, tenant_id VARCHAR NOT NULL, "
                "project_id VARCHAR NOT NULL, goal VARCHAR NOT NULL)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO workbench_plans (id, tenant_id, project_id, goal) "
                "VALUES ('plan_old', 'tenant_1', 'project_old', 'Ship')"
            )
        )
        _migrate_workbench_schema(
            connection,
            inspect(connection),
            {"workbench_projects", "workbench_plans"},
        )
        _migrate_workbench_schema(
            connection,
            inspect(connection),
            {"workbench_projects", "workbench_plans"},
        )
        version = connection.execute(
            text("SELECT version FROM workbench_projects WHERE id = 'project_old'")
        ).scalar_one()
        assert version == 0
        plan = connection.execute(
            text(
                "SELECT selected_variant_json, dispatch_overrides_json "
                "FROM workbench_plans WHERE id = 'plan_old'"
            )
        ).one()
        assert plan.selected_variant_json is None
        assert plan.dispatch_overrides_json == "[]"
