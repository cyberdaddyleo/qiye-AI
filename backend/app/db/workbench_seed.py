from __future__ import annotations

import errno
import os
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from threading import Lock
from typing import Any, BinaryIO

from sqlalchemy import event
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import SessionTransaction
from sqlmodel import Session, SQLModel, select

from app.db.models import (
    Department,
    EmployeeProfile,
    PersonaConfig,
    Tenant,
    User,
    WorkPlan,
    WorkProject,
    WorkTask,
    WorkTaskDependency,
    WorkTaskEvent,
)

TENANT_ID = "tenant_demo"
PROJECT_ID = "project_quantxy_delivery_example"
DEFAULT_PERSONA_PROMPT = (
    "你是面壁智能的智能客服，语气专业、清晰、友好。"
    "你需要先理解用户诉求，再基于已配置的技能和工具帮助用户完成业务办理。"
    "不要暴露内部路由、技能 ID、步骤 ID 或工具实现细节。"
)
_SEED_LOCK = Lock()
_SESSION_LOCK_KEY = "quantxy_workbench_seed_lock"
_PREEXISTING_TRANSACTION_ERROR = (
    "QuantXY seed transaction lock must be acquired before the Session starts a transaction"
)
_WINDOWS_LOCK_RETRY_SECONDS = 0.01
_WINDOWS_LOCK_CONTENTION_ERRNOS = {errno.EACCES, errno.EAGAIN}
_WINDOWS_LOCK_CONTENTION_WINERRORS = {32, 33}
_DEMO_TENANT_IDENTITY = (TENANT_ID, "Demo Enterprise")
_DEMO_USER_IDENTITIES = {
    "admin": ("admin", "admin", "admin", "web", {None, "Administrator"}),
    "user_demo": ("user_demo", "user_demo", "member", "web", {None, "Demo User"}),
}
_WORKBENCH_BUSINESS_MODELS = (
    Department,
    EmployeeProfile,
    WorkProject,
    WorkPlan,
    WorkTask,
    WorkTaskDependency,
    WorkTaskEvent,
)
_PRISTINE_IDENTITY_TABLES = {"tenants", "users", "persona_configs"}


def ensure_workbench_admin_profiles(session: Session) -> None:
    """Enroll existing web administrators without importing the demo organization.

    Called inside the startup seed transaction and its cross-process lock. An
    existing profile (including an inactive one) always wins. System authority
    continues to come from User.role; no CEO/manager grant is stored here.
    """
    admins = session.exec(
        select(User).where(User.role == "admin", User.source == "web")
    ).all()
    for user in admins:
        profile = session.exec(
            select(EmployeeProfile).where(
                EmployeeProfile.tenant_id == user.tenant_id,
                EmployeeProfile.user_id == user.id,
            )
        ).first()
        if profile is None:
            session.add(EmployeeProfile(
                tenant_id=user.tenant_id,
                user_id=user.id,
                job_title="系统管理员",
                business_role="member",
            ))
    session.flush()


@dataclass(frozen=True)
class _SeedLockState:
    file_handle: BinaryIO | None


def _sqlite_main_database_path(dbapi_connection: Any) -> Path | None:
    cursor = dbapi_connection.cursor()
    try:
        cursor.execute("PRAGMA database_list")
        filename = next(
            (row[2] for row in cursor.fetchall() if row[1] == "main"),
            "",
        )
    finally:
        cursor.close()
    if not filename:
        return None
    return Path(filename).resolve()


def _sqlite_seed_lock_path(session: Session) -> Path | None:
    bind = session.get_bind()
    if bind.dialect.name != "sqlite":
        return None

    if isinstance(bind, Connection):
        pool_connection = bind.connection
        dbapi_connection = getattr(
            pool_connection,
            "driver_connection",
            pool_connection,
        )
        database_path = _sqlite_main_database_path(dbapi_connection)
    else:
        raw_connection = bind.raw_connection()
        try:
            database_path = _sqlite_main_database_path(raw_connection)
        finally:
            raw_connection.close()

    if database_path is None:
        return None
    return database_path.with_name(f"{database_path.name}.quantxy-seed.lock")


def _has_preexisting_transaction(session: Session) -> bool:
    if session.in_transaction():
        return True
    bind = session.get_bind()
    return isinstance(bind, Connection) and bind.in_transaction()


def _lock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                break
            except OSError as exc:
                if (
                    exc.errno not in _WINDOWS_LOCK_CONTENTION_ERRNOS
                    and getattr(exc, "winerror", None) not in _WINDOWS_LOCK_CONTENTION_WINERRORS
                ):
                    raise
                time.sleep(_WINDOWS_LOCK_RETRY_SECONDS)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)


def _unlock_file(handle: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _close_file_lock(handle: BinaryIO) -> None:
    try:
        _unlock_file(handle)
    except OSError:
        # Closing the descriptor also releases an advisory lock.
        pass
    finally:
        handle.close()


def _open_file_lock(lock_path: Path) -> BinaryIO:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    try:
        if os.name == "nt" and os.fstat(handle.fileno()).st_size == 0:
            # msvcrt cannot lock a byte beyond EOF. Appending avoids reading a
            # byte that another process may already have locked.
            handle.seek(0, os.SEEK_END)
            handle.write(b"0")
            handle.flush()
        _lock_file(handle)
    except BaseException:
        handle.close()
        raise
    return handle


@event.listens_for(Session, "after_transaction_end")
def _release_seed_lock(session: Session, transaction: SessionTransaction) -> None:
    if transaction.parent is not None:
        return
    state = session.info.pop(_SESSION_LOCK_KEY, None)
    if isinstance(state, _SeedLockState):
        try:
            if state.file_handle is not None:
                _close_file_lock(state.file_handle)
        finally:
            _SEED_LOCK.release()
    elif state:
        _SEED_LOCK.release()


def acquire_quantxy_seed_transaction_lock(session: Session) -> None:
    """Serialize demo seed writes until the caller's transaction ends.

    File-backed SQLite also uses a lock beside that database. This is not a
    cross-process advisory-lock implementation for other database engines.
    """
    if session.info.get(_SESSION_LOCK_KEY):
        return
    if _has_preexisting_transaction(session):
        raise RuntimeError(_PREEXISTING_TRANSACTION_ERROR)
    _SEED_LOCK.acquire()
    file_handle: BinaryIO | None = None
    try:
        lock_path = _sqlite_seed_lock_path(session)
        if lock_path is not None:
            file_handle = _open_file_lock(lock_path)
        if not session.in_transaction():
            session.begin()
        session.info[_SESSION_LOCK_KEY] = _SeedLockState(file_handle=file_handle)
    except BaseException:
        if file_handle is not None:
            _close_file_lock(file_handle)
        _SEED_LOCK.release()
        raise


def _has_workbench_organization(session: Session, tenant_id: str) -> bool:
    has_departments = session.exec(
        select(Department.id).where(Department.tenant_id == tenant_id).limit(1)
    ).first()
    has_employees = session.exec(
        select(EmployeeProfile.id).where(EmployeeProfile.tenant_id == tenant_id).limit(1)
    ).first()
    return has_departments is not None or has_employees is not None


def _user_by_username(session: Session, tenant_id: str, username: str) -> User | None:
    return session.exec(
        select(User).where(User.tenant_id == tenant_id, User.username == username)
    ).first()


def _is_pristine_demo_database(session: Session, tenant_id: str) -> bool:
    tenants = session.exec(select(Tenant)).all()
    if {(tenant.id, tenant.name) for tenant in tenants} != {_DEMO_TENANT_IDENTITY}:
        return False

    users = session.exec(select(User)).all()
    if {user.id for user in users} != set(_DEMO_USER_IDENTITIES):
        return False
    for user in users:
        user_id, username, role, source, display_names = _DEMO_USER_IDENTITIES[user.id]
        if (
            user.tenant_id != tenant_id
            or user.id != user_id
            or user.username != username
            or user.role != role
            or user.source != source
            or user.display_name not in display_names
        ):
            return False

    personas = session.exec(select(PersonaConfig)).all()
    if len(personas) != 1:
        return False
    persona = personas[0]
    if persona.tenant_id != tenant_id or persona.system_prompt != DEFAULT_PERSONA_PROMPT:
        return False

    has_workbench_data = any(
        session.exec(select(model.id).limit(1)).first() is not None
        for model in _WORKBENCH_BUSINESS_MODELS
    )
    if has_workbench_data:
        return False

    allowed_tables = _PRISTINE_IDENTITY_TABLES | {
        model.__tablename__ for model in _WORKBENCH_BUSINESS_MODELS
    }
    for table_name, table in SQLModel.metadata.tables.items():
        if table_name in allowed_tables:
            continue
        identity_column = next(iter(table.primary_key.columns), None)
        if identity_column is None:
            identity_column = next(iter(table.columns))
        if session.exec(select(identity_column).limit(1)).first() is not None:
            return False
    return True


def _seed_users(session: Session, tenant_id: str) -> dict[str, User]:
    admin = _user_by_username(session, tenant_id, "admin")
    demo_user = _user_by_username(session, tenant_id, "user_demo")
    if admin is None or demo_user is None:
        raise RuntimeError("QuantXY workbench seed requires the demo admin and user")

    users = {"ceo": admin, "sales": demo_user}
    for role, user_id, username, display_name in (
        (
            "operations",
            "user_quantxy_operations_example",
            "operations_example",
            "运营负责人（示例）",
        ),
        (
            "delivery",
            "user_quantxy_delivery_example",
            "delivery_example",
            "交付负责人（示例）",
        ),
        (
            "technology",
            "user_quantxy_technology_example",
            "technology_example",
            "技术负责人（示例）",
        ),
        (
            "administration",
            "user_quantxy_administration_example",
            "administration_example",
            "行政负责人（示例）",
        ),
        (
            "finance",
            "user_quantxy_finance_example",
            "finance_example",
            "财务负责人（示例）",
        ),
    ):
        user = _user_by_username(session, tenant_id, username)
        if user is None:
            user = User(
                id=user_id,
                tenant_id=tenant_id,
                username=username,
                display_name=display_name,
                role="member",
                source="web",
                password_hash=demo_user.password_hash,
            )
            session.add(user)
        users[role] = user
    session.flush()
    return users


def seed_quantxy_workbench(session: Session, tenant_id: str = TENANT_ID) -> None:
    if tenant_id != TENANT_ID:
        raise ValueError("QuantXY workbench seed only supports tenant_demo")

    if not session.info.get(_SESSION_LOCK_KEY) and _has_preexisting_transaction(session):
        # An already-populated workbench is a read-only no-op. An empty one
        # must not wait for the seed file lock while its caller may already
        # hold a database write lock in the opposite order.
        with session.no_autoflush:
            if _has_workbench_organization(session, tenant_id):
                return
        raise RuntimeError(_PREEXISTING_TRANSACTION_ERROR)

    acquire_quantxy_seed_transaction_lock(session)
    # Keep caller-owned pending writes outside the seed savepoint and its conflict recovery.
    session.flush()
    try:
        with session.begin_nested():
            _seed_quantxy_workbench_once(session, tenant_id)
    except IntegrityError:
        session.expire_all()
        if _has_workbench_organization(session, tenant_id):
            return
        raise


def _seed_quantxy_workbench_once(session: Session, tenant_id: str) -> None:
    if _has_workbench_organization(session, tenant_id):
        return

    if (
        _user_by_username(session, tenant_id, "admin") is None
        or _user_by_username(session, tenant_id, "user_demo") is None
    ):
        raise RuntimeError("QuantXY workbench seed requires the demo admin and user")
    if not _is_pristine_demo_database(session, tenant_id):
        return

    users = _seed_users(session, tenant_id)
    department_specs = (
        ("sales", "dept_quantxy_sales", "销售部", "SALES"),
        ("operations", "dept_quantxy_operations", "运营部", "OPERATIONS"),
        ("delivery", "dept_quantxy_delivery", "交付部", "DELIVERY"),
        ("technology", "dept_quantxy_technology", "技术部", "TECHNOLOGY"),
        (
            "administration",
            "dept_quantxy_administration",
            "行政部",
            "ADMINISTRATION",
        ),
        ("finance", "dept_quantxy_finance", "财务部", "FINANCE"),
    )
    departments = {
        role: Department(
            id=department_id,
            tenant_id=tenant_id,
            name=name,
            code=code,
            manager_user_id=users[role].id,
        )
        for role, department_id, name, code in department_specs
    }
    session.add_all(list(departments.values()))

    employee_specs = (
        (
            "employee_quantxy_ceo",
            "ceo",
            None,
            "QXY-CEO-001",
            "首席执行官（示例）",
            "ceo",
            ["战略协同", "资源协调"],
        ),
        (
            "employee_quantxy_sales",
            "sales",
            "sales",
            "QXY-SALES-001",
            "销售负责人（示例）",
            "manager",
            ["客户沟通", "需求澄清"],
        ),
        (
            "employee_quantxy_operations",
            "operations",
            "operations",
            "QXY-OPS-001",
            "运营负责人（示例） Business Analyst",
            "manager",
            ["运营策划", "跨部门协同", "research", "analysis"],
        ),
        (
            "employee_quantxy_delivery",
            "delivery",
            "delivery",
            "QXY-DELIVERY-001",
            "交付负责人（示例） Delivery Manager",
            "manager",
            ["项目交付", "风险管理", "planning"],
        ),
        (
            "employee_quantxy_technology",
            "technology",
            "technology",
            "QXY-TECH-001",
            "技术负责人（示例） Backend Engineer QA Engineer",
            "manager",
            ["技术方案", "质量保障", "python", "fastapi", "testing"],
        ),
        (
            "employee_quantxy_administration",
            "administration",
            "administration",
            "QXY-ADMIN-001",
            "行政负责人（示例）",
            "manager",
            ["行政协调", "会议保障"],
        ),
        (
            "employee_quantxy_finance",
            "finance",
            "finance",
            "QXY-FINANCE-001",
            "财务负责人（示例）",
            "manager",
            ["资料核对", "流程合规"],
        ),
    )
    session.add_all(
        [
            EmployeeProfile(
                id=employee_id,
                tenant_id=tenant_id,
                user_id=users[user_role].id,
                employee_no=employee_no,
                department_id=(departments[department_role].id if department_role else None),
                job_title=job_title,
                business_role=business_role,
                skills_json=skills,
                capacity_percent=100,
                daily_cost=None,
                manager_user_id=None if user_role == "ceo" else users["ceo"].id,
            )
            for (
                employee_id,
                user_role,
                department_role,
                employee_no,
                job_title,
                business_role,
                skills,
            ) in employee_specs
        ]
    )

    project = WorkProject(
        id=PROJECT_ID,
        tenant_id=tenant_id,
        name="客户交付协同（示例）",
        objective="完成一次跨部门交付演练，明确责任、依赖与验收标准。",
        description="用于演示企业工作台协作流程的示例项目。",
        owner_user_id=users["ceo"].id,
        department_id=departments["delivery"].id,
        status="active",
        health="on_track",
        start_date=date(2026, 9, 1),
        due_date=date(2026, 9, 30),
        budget=None,
    )
    session.add(project)

    task_specs = (
        (
            "task_quantxy_requirements_example",
            "梳理交付范围（示例）",
            "operations",
            "backlog",
            0,
            date(2026, 9, 1),
            date(2026, 9, 8),
            "形成经相关负责人确认的范围与约束清单。",
        ),
        (
            "task_quantxy_technical_example",
            "准备技术方案（示例）",
            "technology",
            "blocked",
            0,
            date(2026, 9, 9),
            date(2026, 9, 12),
            "方案说明关键组件、接口、验证方式与主要风险。",
        ),
        (
            "task_quantxy_delivery_example",
            "编排交付计划（示例）",
            "delivery",
            "blocked",
            0,
            date(2026, 9, 14),
            date(2026, 9, 16),
            "交付计划列出阶段、责任人、依赖与验收节点。",
        ),
        (
            "task_quantxy_administration_example",
            "准备协作保障（示例）",
            "administration",
            "backlog",
            0,
            date(2026, 9, 1),
            date(2026, 9, 10),
            "会议、沟通与资料归档安排清晰可执行。",
        ),
        (
            "task_quantxy_finance_example",
            "核对商务资料（示例）",
            "finance",
            "blocked",
            0,
            date(2026, 9, 9),
            date(2026, 9, 15),
            "商务资料与内部审批节点完整，待确认事项有明确责任人。",
        ),
        (
            "task_quantxy_sales_example",
            "确认客户沟通清单（示例）",
            "sales",
            "blocked",
            0,
            date(2026, 9, 17),
            date(2026, 9, 18),
            "沟通清单说明范围、里程碑、责任人与升级路径。",
        ),
    )
    tasks = [
        WorkTask(
            id=task_id,
            tenant_id=tenant_id,
            project_id=project.id,
            title=title,
            description="该任务属于 QuantXY 企业工作台演示数据。",
            required_role=role,
            priority="normal",
            status=status,
            assignee_user_id=users[role].id,
            reviewer_user_id=users["ceo"].id,
            start_date=start_date,
            due_date=due_date,
            estimate_days=2.0,
            progress=progress,
            acceptance_criteria=acceptance_criteria,
        )
        for (
            task_id,
            title,
            role,
            status,
            progress,
            start_date,
            due_date,
            acceptance_criteria,
        ) in task_specs
    ]
    session.add_all(tasks)

    dependency_specs = (
        (
            "taskdep_quantxy_technical_requirements_example",
            "task_quantxy_technical_example",
            "task_quantxy_requirements_example",
        ),
        (
            "taskdep_quantxy_delivery_requirements_example",
            "task_quantxy_delivery_example",
            "task_quantxy_requirements_example",
        ),
        (
            "taskdep_quantxy_delivery_technical_example",
            "task_quantxy_delivery_example",
            "task_quantxy_technical_example",
        ),
        (
            "taskdep_quantxy_finance_requirements_example",
            "task_quantxy_finance_example",
            "task_quantxy_requirements_example",
        ),
        (
            "taskdep_quantxy_sales_delivery_example",
            "task_quantxy_sales_example",
            "task_quantxy_delivery_example",
        ),
        (
            "taskdep_quantxy_sales_administration_example",
            "task_quantxy_sales_example",
            "task_quantxy_administration_example",
        ),
        (
            "taskdep_quantxy_sales_finance_example",
            "task_quantxy_sales_example",
            "task_quantxy_finance_example",
        ),
    )
    session.add_all(
        [
            WorkTaskDependency(
                id=dependency_id,
                tenant_id=tenant_id,
                task_id=task_id,
                depends_on_task_id=depends_on_task_id,
            )
            for dependency_id, task_id, depends_on_task_id in dependency_specs
        ]
    )
    for task in tasks:
        task_slug = task.id.removeprefix("task_quantxy_").removesuffix("_example")
        session.add_all(
            [
                WorkTaskEvent(
                    id=f"taskevent_quantxy_{task_slug}_created_example",
                    tenant_id=tenant_id,
                    task_id=task.id,
                    actor_user_id=users["ceo"].id,
                    actor_type="user",
                    event_type="task_created",
                    payload_json={"old_status": None, "new_status": task.status},
                ),
                WorkTaskEvent(
                    id=f"taskevent_quantxy_{task_slug}_assigned_example",
                    tenant_id=tenant_id,
                    task_id=task.id,
                    actor_user_id=users["ceo"].id,
                    actor_type="user",
                    event_type="task_assigned",
                    payload_json={
                        "old_status": task.status,
                        "new_status": task.status,
                        "assignee_user_id": task.assignee_user_id,
                    },
                ),
            ]
        )
    session.flush()
