from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.db.models import Department, EmployeeProfile, Tenant, User, UserAvatar
from app.main import app
from app.security.auth import create_access_token
from app.workbench.permissions import WorkbenchAccess, can_view_employee


def _client(engine) -> TestClient:
    def override_get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    return TestClient(app)


def _headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user)}"}


def _seed(engine) -> dict[str, object]:
    with Session(engine) as db:
        db.add_all([Tenant(id="tenant_a", name="A"), Tenant(id="tenant_b", name="B")])
        ceo = User(tenant_id="tenant_a", username="ceo", password_hash="hash")
        manager = User(tenant_id="tenant_a", username="manager", password_hash="hash")
        member = User(tenant_id="tenant_a", username="member", password_hash="hash")
        other = User(tenant_id="tenant_a", username="other", password_hash="hash")
        outsider = User(tenant_id="tenant_b", username="outsider", password_hash="hash")
        db.add_all([ceo, manager, member, other, outsider])
        db.flush()
        engineering = Department(tenant_id="tenant_a", name="Engineering", code="ENG")
        design = Department(tenant_id="tenant_a", name="Design", code="DES")
        db.add_all([engineering, design])
        db.flush()
        engineering.manager_user_id = manager.id
        profiles = {
            "ceo": EmployeeProfile(tenant_id="tenant_a", user_id=ceo.id, business_role="ceo"),
            "manager": EmployeeProfile(
                tenant_id="tenant_a", user_id=manager.id, department_id=engineering.id, business_role="manager"
            ),
            "member": EmployeeProfile(
                tenant_id="tenant_a", user_id=member.id, department_id=engineering.id, business_role="member"
            ),
            "other": EmployeeProfile(
                tenant_id="tenant_a", user_id=other.id, department_id=design.id, business_role="member"
            ),
        }
        db.add_all([*profiles.values(), UserAvatar(user_id=ceo.id, data_url="data:image/png;base64,aQ==")])
        db.commit()
        return {
            "ceo": {"id": ceo.id, "tenant_id": ceo.tenant_id, "username": ceo.username},
            "manager": {"id": manager.id, "tenant_id": manager.tenant_id, "username": manager.username},
            "member": {"id": member.id, "tenant_id": member.tenant_id, "username": member.username},
            "other": {"id": other.id, "tenant_id": other.tenant_id, "username": other.username},
            "outsider": {"id": outsider.id, "tenant_id": outsider.tenant_id, "username": outsider.username},
            "engineering": {"id": engineering.id},
            "profiles": {
                name: {"id": profile.id, "department_id": profile.department_id}
                for name, profile in profiles.items()
            },
        }


def _engine():
    return create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


def test_workbench_access_permission_matrix() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    rows = _seed(engine)
    with Session(engine) as db:
        ceo_access = WorkbenchAccess.for_user(db, "tenant_a", rows["ceo"]["id"])
        manager_access = WorkbenchAccess.for_user(db, "tenant_a", rows["manager"]["id"])
        member_access = WorkbenchAccess.for_user(db, "tenant_a", rows["member"]["id"])
        assert ceo_access.can_view_all
        assert manager_access.can_manage_department(rows["engineering"]["id"])
        assert not member_access.can_manage_department(rows["profiles"]["member"]["department_id"])
        other_profile = db.get(EmployeeProfile, rows["profiles"]["other"]["id"])
        assert other_profile is not None
        assert not can_view_employee(db, "tenant_a", rows["member"]["id"], other_profile)


def test_organization_api_auth_scope_and_tenant_isolation() -> None:
    engine = _engine()
    SQLModel.metadata.create_all(engine)
    rows = _seed(engine)
    client = _client(engine)
    try:
        assert client.get("/api/enterprise/workbench/departments", params={"tenant_id": "tenant_a"}).status_code == 401

        ceo_response = client.get(
            f"/api/enterprise/workbench/employees/{rows['profiles']['ceo']['id']}",
            params={"tenant_id": "tenant_a"},
            headers=_headers(User(**rows["ceo"], password_hash="hash")),
        )
        assert ceo_response.status_code == 200
        assert ceo_response.json()["username"] == "ceo"
        assert ceo_response.json()["avatar_url"].endswith("/avatar?tenant_id=tenant_a")

        member_response = client.get(
            "/api/enterprise/workbench/employees",
            params={"tenant_id": "tenant_a"},
            headers=_headers(User(**rows["member"], password_hash="hash")),
        )
        assert member_response.status_code == 403

        hidden_response = client.get(
            f"/api/enterprise/workbench/employees/{rows['profiles']['other']['id']}",
            params={"tenant_id": "tenant_b"},
            headers=_headers(User(**rows["outsider"], password_hash="hash")),
        )
        assert hidden_response.status_code == 404

        manager_response = client.post(
            "/api/enterprise/workbench/employees",
            headers=_headers(User(**rows["manager"], password_hash="hash")),
            json={
                "tenant_id": "tenant_a",
                "user_id": rows["other"]["id"],
                "department_id": rows["profiles"]["other"]["department_id"],
            },
        )
        assert manager_response.status_code == 403
    finally:
        app.dependency_overrides.clear()
