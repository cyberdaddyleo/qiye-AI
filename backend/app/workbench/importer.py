from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from pathlib import PurePath
from typing import Any
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


@dataclass(frozen=True)
class EmployeeImportRow:
    row_number: int
    username: str
    display_name: str
    department: str
    employee_no: str | None = None
    job_title: str | None = None
    business_role: str | None = None
    level: str | None = None
    skills: list[str] | None = None
    capacity_percent: int | None = None
    daily_cost: float | None = None
    manager_username: str | None = None
    assistant_agent_id: str | None = None
    provided_fields: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class EmployeeImportError:
    row_number: int
    code: str
    message: str


@dataclass(frozen=True)
class EmployeeImportResult:
    rows: list[EmployeeImportRow]
    errors: list[EmployeeImportError]


class EmployeeImportTooManyRows(ValueError):
    pass


class _RowValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


_HEADER_ALIASES = {
    "username": "username",
    "用户名": "username",
    "账号": "username",
    "display_name": "display_name",
    "displayname": "display_name",
    "姓名": "display_name",
    "显示名称": "display_name",
    "department": "department",
    "部门": "department",
    "employee_no": "employee_no",
    "employeeno": "employee_no",
    "工号": "employee_no",
    "job_title": "job_title",
    "jobtitle": "job_title",
    "职位": "job_title",
    "职务": "job_title",
    "business_role": "business_role",
    "businessrole": "business_role",
    "业务角色": "business_role",
    "角色": "business_role",
    "level": "level",
    "职级": "level",
    "skills": "skills",
    "技能": "skills",
    "capacity_percent": "capacity_percent",
    "capacitypercent": "capacity_percent",
    "产能": "capacity_percent",
    "容量": "capacity_percent",
    "daily_cost": "daily_cost",
    "dailycost": "daily_cost",
    "日成本": "daily_cost",
    "manager_username": "manager_username",
    "managerusername": "manager_username",
    "负责人账号": "manager_username",
    "直属负责人": "manager_username",
    "assistant_agent_id": "assistant_agent_id",
    "assistantagentid": "assistant_agent_id",
    "助理智能体id": "assistant_agent_id",
}
_REQUIRED_COLUMNS = {"username", "display_name", "department"}
_SUPPORTED_ROLES = {"admin", "ceo", "manager", "member"}


def parse_employee_upload(filename: str, content: bytes) -> EmployeeImportResult:
    suffix = PurePath(filename).suffix.lower()
    if suffix == ".csv":
        try:
            raw_rows = csv.reader(StringIO(content.decode("utf-8-sig")))
            header = next(raw_rows)
        except (StopIteration, UnicodeDecodeError) as exc:
            raise ValueError("upload is empty or unreadable") from exc
        return _parse_rows(header, raw_rows)
    elif suffix == ".xlsx":
        try:
            workbook = load_workbook(filename=BytesIO(content), read_only=True, data_only=True)
            raw_rows = workbook.active.iter_rows(values_only=True)
            header = next(raw_rows)
            return _parse_rows(list(header), raw_rows)
        except StopIteration as exc:
            raise ValueError("upload is empty") from exc
        except (BadZipFile, InvalidFileException, OSError, KeyError) as exc:
            raise ValueError("upload is unreadable") from exc
        finally:
            if "workbook" in locals():
                workbook.close()
    else:
        raise ValueError("only .csv and .xlsx files are supported")

def _parse_rows(raw_header: list[Any], raw_rows: Any) -> EmployeeImportResult:
    headers = _normalized_headers(raw_header)
    missing = _REQUIRED_COLUMNS - set(headers.values())
    if missing:
        raise ValueError(f"missing required columns: {', '.join(sorted(missing))}")

    seen_usernames: set[str] = set()
    rows: list[EmployeeImportRow] = []
    errors: list[EmployeeImportError] = []
    for data_index, raw_row in enumerate(raw_rows, start=1):
        if data_index > 2_000:
            raise EmployeeImportTooManyRows("too_many_rows")
        row_number = data_index + 1
        values = {
            field: _text(raw_row[index]) if index < len(raw_row) else ""
            for index, field in headers.items()
        }
        if not any(values.values()):
            continue
        try:
            row = _parse_row(row_number, values, frozenset(headers.values()), seen_usernames)
        except _RowValidationError as exc:
            errors.append(EmployeeImportError(row_number, exc.code, exc.message))
        else:
            seen_usernames.add(row.username)
            rows.append(row)
    return EmployeeImportResult(rows=rows, errors=errors)


def _parse_row(
    row_number: int,
    values: dict[str, str],
    provided_fields: frozenset[str],
    seen_usernames: set[str],
) -> EmployeeImportRow:
    username = values["username"]
    if not username:
        raise _RowValidationError("missing_username", "username is required")
    if username in seen_usernames:
        raise _RowValidationError("duplicate_username", "duplicate username")
    if not values["display_name"]:
        raise _RowValidationError("missing_display_name", "display_name is required")
    if not values["department"]:
        raise _RowValidationError("missing_department", "department is required")
    capacity_percent = _integer(values.get("capacity_percent"), "capacity_percent")
    if capacity_percent is not None and not 0 <= capacity_percent <= 100:
        raise _RowValidationError("invalid_capacity_percent", "capacity_percent must be between 0 and 100")
    daily_cost = _number(values.get("daily_cost"), "daily_cost")
    business_role = values.get("business_role") or None
    if business_role and business_role not in _SUPPORTED_ROLES:
        raise _RowValidationError("invalid_business_role", "business_role is invalid")
    return EmployeeImportRow(
        row_number=row_number,
        username=username,
        display_name=values["display_name"],
        department=values["department"],
        employee_no=values.get("employee_no") or None,
        job_title=values.get("job_title") or None,
        business_role=business_role,
        level=values.get("level") or None,
        skills=_skills(values.get("skills")) if "skills" in provided_fields else None,
        capacity_percent=capacity_percent,
        daily_cost=daily_cost,
        manager_username=values.get("manager_username") or None,
        assistant_agent_id=values.get("assistant_agent_id") or None,
        provided_fields=provided_fields,
    )


def _normalized_headers(raw_headers: list[Any]) -> dict[int, str]:
    headers: dict[int, str] = {}
    seen: set[str] = set()
    for index, header in enumerate(raw_headers):
        normalized = _HEADER_ALIASES.get(_header_key(_text(header)))
        if normalized and normalized not in seen:
            headers[index] = normalized
            seen.add(normalized)
    return headers


def _header_key(value: str) -> str:
    return re.sub(r"[\s_-]+", "", value.strip().lower())


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _skills(value: str | None) -> list[str]:
    if not value:
        return []
    return list(dict.fromkeys(part.strip() for part in re.split(r"[,，;；、\n]+", value) if part.strip()))


def _integer(value: str | None, field: str) -> int | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise _RowValidationError(f"invalid_{field}", f"{field} is invalid") from exc
    if not parsed.is_integer():
        raise _RowValidationError(f"invalid_{field}", f"{field} is invalid")
    return int(parsed)


def _number(value: str | None, field: str) -> float | None:
    if not value:
        return None
    try:
        parsed = float(value)
    except ValueError as exc:
        raise _RowValidationError(f"invalid_{field}", f"{field} is invalid") from exc
    if parsed < 0:
        raise _RowValidationError(f"invalid_{field}", f"{field} must be non-negative")
    return parsed
