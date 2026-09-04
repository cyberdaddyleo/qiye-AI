from __future__ import annotations

from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.db.models import Department, EmployeeProfile, Tenant, User
from app.main import app
from app.security.auth import create_access_token
from app.workbench.importer import parse_employee_upload


def test_parse_employee_csv_accepts_chinese_headers_and_normalizes_skills() -> None:
    content = (
        "用户名,姓名,部门,技能,产能,负责人账号\n"
        "li,李雷,研发部,Python； FastAPI、SQL,80,manager\n"
    ).encode()

    rows = parse_employee_upload("employees.csv", content)

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

    rows = parse_employee_upload("employees.xlsx", file.getvalue())

    assert rows[0].username == "wang"
    assert rows[0].employee_no == "E-02"
    assert rows[0].daily_cost == 1234.5


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("username,display_name,department,capacity_percent\nlee,李雷,研发,101\n", "capacity_percent"),
        ("username,display_name,department\n,李雷,研发\n", "username"),
        ("username,display_name,department\nlee,李雷,研发\nlee,李雷,研发\n", "duplicate username"),
    ],
)
def test_parse_employee_upload_rejects_invalid_required_values(content: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_employee_upload("employees.csv", content.encode("utf-8"))


def test_employee_import_keeps_valid_rows_when_manager_is_unknown() -> None:
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(tenant_id="tenant_a", username="admin", role="admin", password_hash="hash")
        existing = User(tenant_id="tenant_a", username="existing", password_hash="hash")
        department = Department(tenant_id="tenant_a", name="研发", code="DEV")
        db.add_all([Tenant(id="tenant_a", name="A"), admin, existing, department])
        db.flush()
        db.add(EmployeeProfile(tenant_id="tenant_a", user_id=existing.id, department_id=department.id))
        db.commit()
        token = create_access_token(admin)

    def override_get_session():
        with Session(engine) as db:
            yield db

    app.dependency_overrides[get_session] = override_get_session
    client = TestClient(app)
    try:
        content = (
            "username,display_name,department,capacity_percent,manager_username\n"
            "new_user,新员工,研发,80,\n"
            "existing,已存在,研发,90,\n"
            "broken,错误行,研发,100,ghost\n"
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
            {"row": 4, "code": "unknown_manager", "message": "负责人账号不存在"}
        ]
        assert response.json()["results"][0]["password"]
        with Session(engine) as db:
            assert db.exec(select(User).where(User.username == "new_user")).one().tenant_id == "tenant_a"
    finally:
        app.dependency_overrides.clear()
