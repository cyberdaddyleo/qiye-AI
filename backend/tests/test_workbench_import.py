from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.db.models import AgentProfile, Department, EmployeeProfile, Tenant, User
from app.main import app
from app.security.auth import create_access_token
from app.workbench.importer import parse_employee_upload


def test_parse_employee_csv_accepts_chinese_headers_and_normalizes_skills() -> None:
    content = (
        "用户名,姓名,部门,技能,产能,负责人账号\n"
        "li,李雷,研发部,Python； FastAPI、SQL,80,manager\n"
    ).encode()

    parsed = parse_employee_upload("employees.csv", content)
    rows = parsed.rows

    assert len(rows) == 1
    assert rows[0].row_number == 2
    assert rows[0].username == "li"
    assert rows[0].display_name == "李雷"
    assert rows[0].department == "研发部"
    assert rows[0].skills == ["Python", "FastAPI", "SQL"]
    assert rows[0].capacity_percent == 80


def test_parse_employee_xlsx_reads_supported_columns() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["username", "display_name", "department", "employee_no", "daily_cost"])
    sheet.append(["wang", "王芳", "销售", "E-02", 1234.5])
    file = BytesIO()
    workbook.save(file)

    parsed = parse_employee_upload("employees.xlsx", file.getvalue())
    rows = parsed.rows

    assert rows[0].username == "wang"
    assert rows[0].employee_no == "E-02"
    assert rows[0].daily_cost == 1234.5


def test_parse_employee_upload_returns_row_errors_and_keeps_valid_rows() -> None:
    content = (
        "username,display_name,department,capacity_percent,business_role\n"
        "valid,有效,研发,80,member\n"
        ",缺账号,研发,80,member\n"
        "bad_capacity,错误,研发,101,member\n"
        "bad_role,错误,研发,80,owner\n"
        "valid,重复,研发,80,member\n"
    ).encode()

    parsed = parse_employee_upload("employees.csv", content)

    assert [row.username for row in parsed.rows] == ["valid"]
    assert [(error.row_number, error.code) for error in parsed.errors] == [
        (3, "missing_username"),
        (4, "invalid_capacity_percent"),
        (5, "invalid_business_role"),
        (6, "duplicate_username"),
    ]


def test_parse_employee_xlsx_stops_at_2001_rows() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(["username", "display_name", "department"])
    for number in range(2_001):
        sheet.append([f"user_{number}", f"用户{number}", "研发"])
    file = BytesIO()
    workbook.save(file)

    with pytest.raises(ValueError, match="too_many_rows"):
        parse_employee_upload("employees.xlsx", file.getvalue())


def test_parse_employee_upload_rejects_unreadable_xlsx() -> None:
    with pytest.raises(ValueError, match="unreadable"):
        parse_employee_upload("employees.xlsx", b"not an xlsx file")


@pytest.mark.parametrize("kind", ["declared_size", "entry_count"])
def test_parse_employee_upload_rejects_bounded_xlsx_archives(kind: str) -> None:
    archive = BytesIO()
    with ZipFile(archive, "w") as zip_file:
        if kind == "entry_count":
            for number in range(513):
                zip_file.writestr(f"entry-{number}", b"")
        else:
            zip_file.writestr("small.txt", b"x")
    content = bytearray(archive.getvalue())
    if kind == "declared_size":
        central_offset = content.index(b"PK\x01\x02")
        content[central_offset + 24 : central_offset + 28] = (50 * 1024 * 1024 + 1).to_bytes(4, "little")

    with pytest.raises(ValueError, match="xlsx_archive_limit"):
        parse_employee_upload("employees.xlsx", bytes(content))


def test_parse_employee_upload_accepts_2000_rows() -> None:
    content = "username,display_name,department\n" + "".join(
        f"user_{number},用户{number},研发\n" for number in range(2_000)
    )

    parsed = parse_employee_upload("employees.csv", content.encode())

    assert len(parsed.rows) == 2_000
    assert parsed.errors == []


def test_employee_import_keeps_valid_rows_when_manager_is_unknown() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(tenant_id="tenant_a", username="admin", role="admin", password_hash="hash")
        existing = User(tenant_id="tenant_a", username="existing", password_hash="hash")
        foreign_agent = AgentProfile(tenant_id="tenant_b", name="foreign")
        department = Department(tenant_id="tenant_a", name="研发", code="DEV")
        db.add_all([Tenant(id="tenant_a", name="A"), admin, existing, department, foreign_agent])
        db.flush()
        db.add(
            EmployeeProfile(
                tenant_id="tenant_a",
                user_id=existing.id,
                department_id=department.id,
                business_role="manager",
                skills_json=["Python"],
                capacity_percent=60,
            )
        )
        db.commit()
        token = create_access_token(admin)
        existing_id = existing.id
        foreign_agent_id = foreign_agent.id

    def override_get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        content = (
            "username,display_name,department,capacity_percent,manager_username,assistant_agent_id\n"
            "new_user,新员工,研发,80,\n"
            "existing,已存在,研发,,,\n"
            "bad_capacity,容量错误,研发,101,,\n"
            "broken,错误行,研发,100,ghost,\n"
            f"bad_agent,错误智能体,研发,100,,{foreign_agent_id}\n"
        ).encode()
        response = client.post(
            "/api/enterprise/workbench/employees/import",
            params={"tenant_id": "tenant_a"},
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("employees.csv", content, "text/csv")},
        )

        assert response.status_code == 200
        assert response.json()["created"] == 1
        assert response.json()["updated"] == 1
        assert response.json()["errors"] == [
            {
                "row": 4,
                "code": "invalid_capacity_percent",
                "message": "capacity_percent must be between 0 and 100",
            },
            {"row": 5, "code": "unknown_manager", "message": "负责人账号不存在"},
            {"row": 6, "code": "unknown_assistant_agent", "message": "助理智能体不存在"},
        ]
        assert response.json()["results"][0]["password"]
        assert "password" not in response.json()["results"][1]
        with Session(engine) as db:
            assert db.exec(select(User).where(User.username == "new_user")).one().tenant_id == "tenant_a"
            existing_profile = db.exec(
                select(EmployeeProfile).where(EmployeeProfile.user_id == existing_id)
            ).one()
            assert existing_profile.business_role == "manager"
            assert existing_profile.skills_json == ["Python"]
            assert existing_profile.capacity_percent == 60
            assert db.exec(select(User).where(User.username == "bad_agent")).first() is None
    finally:
        app.dependency_overrides.clear()


def test_employee_import_rejects_more_than_five_mebibytes() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(tenant_id="tenant_a", username="admin", role="admin", password_hash="hash")
        db.add_all([Tenant(id="tenant_a", name="A"), admin])
        db.commit()
        token = create_access_token(admin)

    def override_get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    try:
        response = TestClient(app).post(
            "/api/enterprise/workbench/employees/import",
            params={"tenant_id": "tenant_a"},
            headers={"Authorization": f"Bearer {token}"},
            files={"file": ("employees.csv", b"x" * (5 * 1024 * 1024 + 1), "text/csv")},
        )
        assert response.status_code == 413
    finally:
        app.dependency_overrides.clear()


def test_employee_import_preserves_existing_profile_when_optional_headers_are_absent() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(tenant_id="tenant_a", username="admin", role="admin", password_hash="hash")
        employee = User(tenant_id="tenant_a", username="existing", password_hash="hash")
        manager = User(tenant_id="tenant_a", username="manager", password_hash="hash")
        department = Department(tenant_id="tenant_a", name="研发", code="DEV")
        agent = AgentProfile(tenant_id="tenant_a", name="assistant")
        db.add_all([Tenant(id="tenant_a", name="A"), admin, employee, manager, department, agent])
        db.flush()
        db.add(
            EmployeeProfile(
                tenant_id="tenant_a",
                user_id=employee.id,
                employee_no="E-01",
                department_id=department.id,
                job_title="工程师",
                business_role="manager",
                level="P7",
                skills_json=["Python", "SQL"],
                capacity_percent=65,
                daily_cost=1234.5,
                manager_user_id=manager.id,
                assistant_agent_id=agent.id,
            )
        )
        db.commit()
        token = create_access_token(admin)
        employee_id = employee.id

    def override_get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    try:
        response = TestClient(app).post(
            "/api/enterprise/workbench/employees/import",
            params={"tenant_id": "tenant_a"},
            headers={"Authorization": f"Bearer {token}"},
            files={
                "file": (
                    "employees.csv",
                    "username,display_name,department\nexisting,改名,研发\n".encode(),
                    "text/csv",
                )
            },
        )
        assert response.status_code == 200
        assert response.json()["created"] == 0
        assert response.json()["updated"] == 1
        with Session(engine) as db:
            profile = db.exec(select(EmployeeProfile).where(EmployeeProfile.user_id == employee_id)).one()
            assert profile.employee_no == "E-01"
            assert profile.job_title == "工程师"
            assert profile.business_role == "manager"
            assert profile.level == "P7"
            assert profile.skills_json == ["Python", "SQL"]
            assert profile.capacity_percent == 65
            assert profile.daily_cost == 1234.5
            assert profile.manager_user_id is not None
            assert profile.assistant_agent_id is not None
    finally:
        app.dependency_overrides.clear()
