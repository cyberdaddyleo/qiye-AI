from __future__ import annotations

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    Department,
    EmployeeProfile,
    Tenant,
    User,
    WorkProject,
    WorkTask,
    WorkTaskDependency,
    WorkTaskEvent,
)
from app.db.seed import seed_demo_data
from app.db.workbench_seed import seed_quantxy_workbench

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
        assert [(row.id, row.task_id, row.event_type) for row in events] == [
            (
                "taskevent_quantxy_requirements_created_example",
                "task_quantxy_requirements_example",
                "task_created",
            )
        ]

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
