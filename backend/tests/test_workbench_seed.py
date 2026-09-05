from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    Department,
    EmployeeProfile,
    ModelConfig,
    Tenant,
    User,
    WorkPlan,
    WorkProject,
    WorkTask,
    WorkTaskDependency,
    WorkTaskEvent,
)
from app.db.seed import seed_demo_data
from app.db.workbench_seed import seed_quantxy_workbench
from app.workbench.schema import PlanPreviewRequest
from app.workbench.service import build_plan, dispatch_plan

EXPECTED_DEPARTMENTS = {
    "dept_quantxy_sales": ("销售部", "SALES"),
    "dept_quantxy_operations": ("运营部", "OPERATIONS"),
    "dept_quantxy_delivery": ("交付部", "DELIVERY"),
    "dept_quantxy_technology": ("技术部", "TECHNOLOGY"),
    "dept_quantxy_administration": ("行政部", "ADMINISTRATION"),
    "dept_quantxy_finance": ("财务部", "FINANCE"),
}

EXPECTED_EMPLOYEES = {
    "employee_quantxy_ceo": "admin",
    "employee_quantxy_sales": "user_demo",
    "employee_quantxy_operations": "user_quantxy_operations_example",
    "employee_quantxy_delivery": "user_quantxy_delivery_example",
    "employee_quantxy_technology": "user_quantxy_technology_example",
    "employee_quantxy_administration": "user_quantxy_administration_example",
    "employee_quantxy_finance": "user_quantxy_finance_example",
}

EXPECTED_TASK_IDS = {
    "task_quantxy_requirements_example",
    "task_quantxy_technical_example",
    "task_quantxy_delivery_example",
    "task_quantxy_administration_example",
    "task_quantxy_finance_example",
    "task_quantxy_sales_example",
}

EXPECTED_TASK_EVENT_IDS = {
    "task_quantxy_requirements_example": (
        "taskevent_quantxy_requirements_created_example",
        "taskevent_quantxy_requirements_assigned_example",
    ),
    "task_quantxy_technical_example": (
        "taskevent_quantxy_technical_created_example",
        "taskevent_quantxy_technical_assigned_example",
    ),
    "task_quantxy_delivery_example": (
        "taskevent_quantxy_delivery_created_example",
        "taskevent_quantxy_delivery_assigned_example",
    ),
    "task_quantxy_administration_example": (
        "taskevent_quantxy_administration_created_example",
        "taskevent_quantxy_administration_assigned_example",
    ),
    "task_quantxy_finance_example": (
        "taskevent_quantxy_finance_created_example",
        "taskevent_quantxy_finance_assigned_example",
    ),
    "task_quantxy_sales_example": (
        "taskevent_quantxy_sales_created_example",
        "taskevent_quantxy_sales_assigned_example",
    ),
}

EXPECTED_DEPENDENCIES = {
    ("task_quantxy_technical_example", "task_quantxy_requirements_example"),
    ("task_quantxy_delivery_example", "task_quantxy_requirements_example"),
    ("task_quantxy_delivery_example", "task_quantxy_technical_example"),
    ("task_quantxy_finance_example", "task_quantxy_requirements_example"),
    ("task_quantxy_sales_example", "task_quantxy_delivery_example"),
    ("task_quantxy_sales_example", "task_quantxy_administration_example"),
    ("task_quantxy_sales_example", "task_quantxy_finance_example"),
}


def _model_ids(db: Session, model: type) -> tuple[str, ...]:
    return tuple(sorted(row.id for row in db.exec(select(model)).all()))


def test_quantxy_workbench_seed_serializes_two_real_sessions(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'concurrent-seed.db'}",
        connect_args={"timeout": 5},
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id="tenant_demo", name="Demo Enterprise"))
        db.add_all(
            [
                User(
                    id="admin",
                    tenant_id="tenant_demo",
                    username="admin",
                    display_name="Administrator",
                    role="admin",
                    password_hash="admin-hash",
                ),
                User(
                    id="user_demo",
                    tenant_id="tenant_demo",
                    username="user_demo",
                    display_name="Demo User",
                    password_hash="demo-hash",
                ),
            ]
        )
        db.commit()

    start = Barrier(2)

    def run_seed() -> bool:
        with Session(engine) as db:
            start.wait()
            seed_quantxy_workbench(db)
            db.commit()
        return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(run_seed) for _ in range(2)]
        assert [future.result(timeout=10) for future in futures] == [True, True]

    with Session(engine) as db:
        assert _model_ids(db, Department) == tuple(sorted(EXPECTED_DEPARTMENTS))
        assert _model_ids(db, EmployeeProfile) == tuple(sorted(EXPECTED_EMPLOYEES))
        assert _model_ids(db, WorkProject) == ("project_quantxy_delivery_example",)
        assert set(_model_ids(db, WorkTask)) == EXPECTED_TASK_IDS
        assert len(_model_ids(db, WorkTaskDependency)) == len(EXPECTED_DEPENDENCIES)
        assert set(_model_ids(db, WorkTaskEvent)) == {
            event_id
            for event_ids in EXPECTED_TASK_EVENT_IDS.values()
            for event_id in event_ids
        }


def test_quantxy_workbench_seed_does_not_commit_the_callers_transaction() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id="tenant_demo", name="Demo Enterprise"))
        db.add_all(
            [
                User(
                    id="admin",
                    tenant_id="tenant_demo",
                    username="admin",
                    role="admin",
                    password_hash="admin-hash",
                ),
                User(
                    id="user_demo",
                    tenant_id="tenant_demo",
                    username="user_demo",
                    password_hash="demo-hash",
                ),
            ]
        )
        db.commit()

        db.add(Tenant(id="outer_transaction_marker", name="Outer transaction marker"))
        seed_quantxy_workbench(db)
        db.rollback()

    with Session(engine) as db:
        assert db.get(Tenant, "outer_transaction_marker") is None
        assert _model_ids(db, Department) == ()
        assert _model_ids(db, EmployeeProfile) == ()
        assert _model_ids(db, WorkProject) == ()
        assert _model_ids(db, WorkTask) == ()


def test_demo_seed_creates_an_idempotent_quantxy_workbench_with_real_users() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db:
        seed_demo_data(db)

        departments = db.exec(
            select(Department).where(Department.tenant_id == "tenant_demo")
        ).all()
        assert {
            row.id: (row.name, row.code) for row in departments
        } == EXPECTED_DEPARTMENTS

        employees = db.exec(
            select(EmployeeProfile).where(EmployeeProfile.tenant_id == "tenant_demo")
        ).all()
        assert {row.id: row.user_id for row in employees} == EXPECTED_EMPLOYEES
        assert all("示例" in (row.job_title or "") for row in employees)
        assert all(row.daily_cost is None for row in employees)

        users = {
            row.id: row
            for row in db.exec(select(User).where(User.tenant_id == "tenant_demo")).all()
        }
        assert set(EXPECTED_EMPLOYEES.values()) <= set(users)
        assert all(users[row.user_id].source == "web" for row in employees)
        assert {row.manager_user_id for row in departments} == {
            "user_demo",
            "user_quantxy_operations_example",
            "user_quantxy_delivery_example",
            "user_quantxy_technology_example",
            "user_quantxy_administration_example",
            "user_quantxy_finance_example",
        }

        projects = db.exec(
            select(WorkProject).where(WorkProject.tenant_id == "tenant_demo")
        ).all()
        assert len(projects) == 1
        assert projects[0].id == "project_quantxy_delivery_example"
        assert "示例" in projects[0].name
        assert projects[0].budget is None

        tasks = db.exec(select(WorkTask).where(WorkTask.tenant_id == "tenant_demo")).all()
        assert {row.id for row in tasks} == EXPECTED_TASK_IDS
        assert all("示例" in row.title for row in tasks)
        assert all(row.assignee_user_id in users for row in tasks)
        assert all(row.reviewer_user_id == "admin" for row in tasks)

        dependencies = db.exec(
            select(WorkTaskDependency).where(WorkTaskDependency.tenant_id == "tenant_demo")
        ).all()
        assert {
            (row.task_id, row.depends_on_task_id) for row in dependencies
        } == EXPECTED_DEPENDENCIES

        events = db.exec(
            select(WorkTaskEvent).where(WorkTaskEvent.tenant_id == "tenant_demo")
        ).all()
        assert len(events) == 12
        assert {row.event_type for row in events} == {"task_created", "task_assigned"}

        first_ids = {
            model.__name__: _model_ids(db, model)
            for model in (
                User,
                Department,
                EmployeeProfile,
                WorkProject,
                WorkTask,
                WorkTaskDependency,
                WorkTaskEvent,
            )
        }
        seed_demo_data(db)
        second_ids = {
            model.__name__: _model_ids(db, model)
            for model in (
                User,
                Department,
                EmployeeProfile,
                WorkProject,
                WorkTask,
                WorkTaskDependency,
                WorkTaskEvent,
            )
        }

        assert second_ids == first_ids


def test_fresh_demo_seed_fallback_plan_dispatches_every_task_to_active_real_users() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db:
        seed_demo_data(db)
        for model_config in db.exec(select(ModelConfig)).all():
            db.delete(model_config)
        db.commit()

        admin = db.get(User, "admin")
        project = db.get(WorkProject, "project_quantxy_delivery_example")
        assert admin is not None
        assert project is not None

        plan = build_plan(
            db,
            PlanPreviewRequest(
                tenant_id="tenant_demo",
                project_id=project.id,
                goal="完成跨部门交付演练（示例）",
                deadline=project.due_date,
            ),
            admin,
        )

        assert plan.source == "fallback"
        assert [variant["key"] for variant in plan.variants_json] == ["A", "B", "C"]
        selected = next(variant for variant in plan.variants_json if variant["key"] == "A")
        expected_assignees = {
            "user_quantxy_operations_example",
            "user_quantxy_technology_example",
            "user_quantxy_delivery_example",
        }
        assert {task["assignee_user_id"] for task in selected["tasks"]} == expected_assignees

        dispatched = dispatch_plan(
            db,
            plan.id,
            "A",
            "quantxy-seed-fallback-e2e",
            admin,
        )

        assert len(dispatched) == 6
        assert all(task.assignee_user_id for task in dispatched)
        dispatched_user_ids = {task.assignee_user_id for task in dispatched}
        active_profile_user_ids = set(
            db.exec(
                select(EmployeeProfile.user_id).where(
                    EmployeeProfile.tenant_id == "tenant_demo",
                    EmployeeProfile.status == "active",
                )
            ).all()
        )
        tenant_user_ids = set(
            db.exec(select(User.id).where(User.tenant_id == "tenant_demo")).all()
        )
        assert dispatched_user_ids == expected_assignees
        assert dispatched_user_ids <= active_profile_user_ids
        assert dispatched_user_ids <= tenant_user_ids
        stored_plan = db.get(WorkPlan, plan.id)
        assert stored_plan is not None
        assert stored_plan.status == "dispatched"


def test_quantxy_seed_task_schedule_respects_dependencies_and_project_window() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db:
        seed_demo_data(db)
        project = db.get(WorkProject, "project_quantxy_delivery_example")
        assert project is not None
        tasks = {
            row.id: row
            for row in db.exec(
                select(WorkTask).where(WorkTask.tenant_id == "tenant_demo")
            ).all()
        }
        dependencies = db.exec(
            select(WorkTaskDependency).where(
                WorkTaskDependency.tenant_id == "tenant_demo"
            )
        ).all()

        assert all(
            project.start_date <= task.start_date <= task.due_date <= project.due_date
            for task in tasks.values()
        )
        assert all(
            tasks[edge.task_id].start_date > tasks[edge.depends_on_task_id].due_date
            for edge in dependencies
        )


def test_quantxy_seed_tasks_start_at_baseline_with_standard_stable_events() -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db:
        seed_demo_data(db)
        tasks = {
            row.id: row
            for row in db.exec(
                select(WorkTask).where(WorkTask.tenant_id == "tenant_demo")
            ).all()
        }
        events = db.exec(
            select(WorkTaskEvent).where(WorkTaskEvent.tenant_id == "tenant_demo")
        ).all()

        assert {
            task_id: (task.status, task.progress) for task_id, task in tasks.items()
        } == {
            "task_quantxy_requirements_example": ("backlog", 0),
            "task_quantxy_technical_example": ("blocked", 0),
            "task_quantxy_delivery_example": ("blocked", 0),
            "task_quantxy_administration_example": ("backlog", 0),
            "task_quantxy_finance_example": ("blocked", 0),
            "task_quantxy_sales_example": ("blocked", 0),
        }
        assert len(events) == 12
        events_by_task: dict[str, dict[str, WorkTaskEvent]] = {}
        for event in events:
            events_by_task.setdefault(event.task_id, {})[event.event_type] = event
        assert set(events_by_task) == EXPECTED_TASK_IDS

        for task_id, task in tasks.items():
            created = events_by_task[task_id]["task_created"]
            assigned = events_by_task[task_id]["task_assigned"]
            created_id, assigned_id = EXPECTED_TASK_EVENT_IDS[task_id]
            assert created.id == created_id
            assert created.actor_user_id == "admin"
            assert created.actor_type == "user"
            assert created.payload_json == {
                "old_status": None,
                "new_status": task.status,
            }
            assert assigned.id == assigned_id
            assert assigned.actor_user_id == "admin"
            assert assigned.actor_type == "user"
            assert assigned.payload_json == {
                "old_status": task.status,
                "new_status": task.status,
                "assignee_user_id": task.assignee_user_id,
            }


@pytest.mark.parametrize("existing_kind", ["department", "employee"])
def test_quantxy_workbench_seed_skips_tenants_with_an_existing_organization(
    existing_kind: str,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db:
        admin = User(
            id="existing_admin",
            tenant_id="tenant_demo",
            username="admin",
            display_name="用户自己的管理员",
            role="admin",
            password_hash="custom-admin-hash",
        )
        demo_user = User(
            id="existing_demo_user",
            tenant_id="tenant_demo",
            username="user_demo",
            display_name="用户自己的演示账号",
            password_hash="custom-demo-hash",
        )
        db.add_all([Tenant(id="tenant_demo", name="用户企业"), admin, demo_user])
        if existing_kind == "department":
            db.add(
                Department(
                    id="department_user_owned",
                    tenant_id="tenant_demo",
                    name="用户自建部门",
                    code="OWNED",
                    manager_user_id=admin.id,
                )
            )
        else:
            db.add(
                EmployeeProfile(
                    id="employee_user_owned",
                    tenant_id="tenant_demo",
                    user_id=demo_user.id,
                    job_title="用户自定义职位",
                    business_role="member",
                    capacity_percent=65,
                )
            )
        db.commit()

        seed_quantxy_workbench(db)
        db.commit()

        assert _model_ids(db, Department) == (
            ("department_user_owned",) if existing_kind == "department" else ()
        )
        assert _model_ids(db, EmployeeProfile) == (
            ("employee_user_owned",) if existing_kind == "employee" else ()
        )
        assert _model_ids(db, WorkProject) == ()
        assert _model_ids(db, WorkTask) == ()
        assert _model_ids(db, WorkTaskDependency) == ()
        assert _model_ids(db, WorkTaskEvent) == ()
        assert db.get(User, admin.id).display_name == "用户自己的管理员"
        assert db.get(User, demo_user.id).display_name == "用户自己的演示账号"


@pytest.mark.parametrize("tenant_id", ["tenant_a", "tenant_b"])
def test_quantxy_workbench_seed_rejects_non_demo_tenants_without_writing(
    tenant_id: str,
) -> None:
    engine = create_engine("sqlite:///:memory:")
    SQLModel.metadata.create_all(engine)

    with Session(engine) as db:
        db.add(Tenant(id=tenant_id, name="用户企业"))
        db.add_all(
            [
                User(
                    id=f"{tenant_id}_admin",
                    tenant_id=tenant_id,
                    username="admin",
                    role="admin",
                    password_hash="existing-hash",
                ),
                User(
                    id=f"{tenant_id}_demo",
                    tenant_id=tenant_id,
                    username="user_demo",
                    password_hash="existing-hash",
                ),
            ]
        )
        db.commit()

        with pytest.raises(
            ValueError,
            match="QuantXY workbench seed only supports tenant_demo",
        ):
            seed_quantxy_workbench(db, tenant_id)

        assert db.exec(select(Department)).all() == []
        assert db.exec(select(EmployeeProfile)).all() == []
        assert db.exec(select(WorkProject)).all() == []
        assert db.exec(select(WorkTask)).all() == []
        assert len(db.exec(select(User)).all()) == 2
