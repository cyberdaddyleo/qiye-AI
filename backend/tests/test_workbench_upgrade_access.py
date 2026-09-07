from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.db.models import AgentProfile, Department, EmployeeProfile, Tenant, User, WorkProject
from app.db.seed import seed_demo_data
from app.main import app
from app.security.auth import create_access_token


@pytest.fixture
def upgraded_db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(Tenant(id="tenant_demo", name="QuantXY"))
        db.add_all([
            User(id="admin", tenant_id="tenant_demo", username="admin", role="admin", password_hash="hash"),
            User(id="user_demo", tenant_id="tenant_demo", username="user_demo", password_hash="hash"),
            AgentProfile(id="existing_ceo", tenant_id="tenant_demo", name="CEO", metadata_json={"owner_user_id": "admin"}),
        ])
        db.commit()
    yield engine
    engine.dispose()


def test_upgrade_enables_existing_admin_without_inventing_staff_or_projects(upgraded_db):
    with Session(upgraded_db) as db:
        seed_demo_data(db)
        profiles = db.exec(select(EmployeeProfile)).all()
        assert len(profiles) == 1
        assert profiles[0].user_id == "admin"
        assert profiles[0].status == "active"
        # Global access still comes from the system account, not a fabricated CEO role.
        assert profiles[0].business_role == "member"
        assert profiles[0].assistant_agent_id is None
        profile_id = profiles[0].id
        assert db.exec(select(Department)).all() == []
        assert db.exec(select(WorkProject)).all() == []
        assert db.get(AgentProfile, "existing_ceo").name == "CEO"
        db.rollback()
        seed_demo_data(db)
        assert [row.id for row in db.exec(select(EmployeeProfile)).all()] == [profile_id]
        admin = db.get(User, "admin")
        headers = {"Authorization": f"Bearer {create_access_token(admin)}"}

    def session_override():
        with Session(upgraded_db) as db:
            yield db

    app.dependency_overrides[get_session] = session_override
    try:
        client = TestClient(app)
        base = "/api/enterprise/workbench"
        for path in ("access", "projects", "tasks", "dashboard", "employees", "departments"):
            response = client.get(f"{base}/{path}?tenant_id=tenant_demo", headers=headers)
            assert response.status_code == 200, (path, response.text)
        access = client.get(f"{base}/access?tenant_id=tenant_demo", headers=headers).json()
        assert access["can_create_project"] is True
        department = client.post(f"{base}/departments", headers=headers, json={
            "tenant_id": "tenant_demo", "name": "Management", "code": "MGMT",
        })
        assert department.status_code == 201, department.text
        response = client.post(f"{base}/projects", headers=headers, json={
            "tenant_id": "tenant_demo", "name": "First project", "objective": "Deliver work",
            "department_id": department.json()["id"], "owner_user_id": "admin",
        })
        assert response.status_code == 201, response.text
        assert response.json()["owner_user_id"] == "admin"
    finally:
        app.dependency_overrides.pop(get_session, None)


def test_upgrade_never_reactivates_existing_employee_or_enrolls_channel_accounts(upgraded_db):
    with Session(upgraded_db) as db:
        db.add(EmployeeProfile(
            id="inactive_admin", tenant_id="tenant_demo", user_id="admin", status="inactive",
            business_role="manager", job_title="原始职位", capacity_percent=35,
        ))
        db.add(User(
            id="channel_admin", tenant_id="tenant_demo", username="channel_admin",
            source="wechat", role="admin", password_hash="hash",
        ))
        db.commit()
        seed_demo_data(db)
        profiles = db.exec(select(EmployeeProfile)).all()
        assert len(profiles) == 1
        assert profiles[0].id == "inactive_admin"
        assert profiles[0].status == "inactive"
        assert profiles[0].business_role == "manager"
        assert profiles[0].job_title == "原始职位"
        assert profiles[0].capacity_percent == 35
