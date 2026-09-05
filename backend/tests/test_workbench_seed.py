from __future__ import annotations

import errno
import multiprocessing
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy import text
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
from app.db.workbench_seed import (
    acquire_quantxy_seed_transaction_lock,
    seed_quantxy_workbench,
)
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


def _seed_demo_data_in_process(
    database_url: str,
    data_dir: str,
    start: Any,
    results: Any,
) -> None:
    os.environ["DATABASE_URL"] = database_url
    os.environ["ULTRARAG_DATA_DIR"] = data_dir
    os.environ["ULTRARAG_DOTENV"] = "/dev/null"
    from app.config import get_settings

    get_settings.cache_clear()
    process_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 0.001},
    )
    try:
        start.wait(timeout=15)
        with Session(process_engine) as db:
            seed_demo_data(db)
        results.put(("ok", None))
    except Exception as exc:  # noqa: BLE001 - report child failures to the parent process
        results.put(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        process_engine.dispose()


def _fail_seed_then_wait_in_process(
    database_url: str,
    cleanup: str,
    cleaned_up: Any,
    finish: Any,
    results: Any,
) -> None:
    process_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 0.001},
    )
    db = Session(process_engine)
    try:
        try:
            seed_quantxy_workbench(db)
        except RuntimeError as exc:
            if cleanup == "rollback":
                db.rollback()
            else:
                db.close()
            results.put(("holder_cleaned", type(exc).__name__))
        else:
            results.put(("holder_error", "seed unexpectedly succeeded"))
        cleaned_up.set()
        finish.wait(timeout=15)
    except Exception as exc:  # noqa: BLE001 - report child failures to the parent process
        results.put(("holder_error", f"{type(exc).__name__}: {exc}"))
        cleaned_up.set()
    finally:
        db.close()
        process_engine.dispose()


def _seed_quantxy_workbench_in_process(database_url: str, results: Any) -> None:
    process_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 0.001},
    )
    try:
        with Session(process_engine) as db:
            seed_quantxy_workbench(db)
            db.commit()
        results.put(("contender_ok", None))
    except Exception as exc:  # noqa: BLE001 - report child failures to the parent process
        results.put(("contender_error", f"{type(exc).__name__}: {exc}"))
    finally:
        process_engine.dispose()


def _prewritten_seed_in_process(
    database_url: str,
    write_locked: Any,
    file_locked: Any,
    results: Any,
) -> None:
    process_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    try:
        with Session(process_engine) as db:
            db.add(Tenant(id="prewritten_transaction_marker", name="Prewritten marker"))
            db.flush()
            write_locked.set()
            if not file_locked.wait(timeout=15):
                raise RuntimeError("normal seed did not acquire its file lock")

            started_at = time.monotonic()
            try:
                seed_quantxy_workbench(db)
            except RuntimeError as exc:
                elapsed = time.monotonic() - started_at
                db.rollback()
                results.put(("prewritten_rejected", str(exc), elapsed))
            else:
                db.rollback()
                results.put(("prewritten_error", "seed unexpectedly succeeded", None))
    except Exception as exc:  # noqa: BLE001 - report child failures to the parent process
        results.put(("prewritten_error", f"{type(exc).__name__}: {exc}", None))
        write_locked.set()
    finally:
        process_engine.dispose()


def _external_prewritten_seed_in_process(
    database_url: str,
    write_locked: Any,
    file_locked: Any,
    results: Any,
) -> None:
    process_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    connection = process_engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(
            Tenant.__table__.insert().values(
                id="external_prewritten_transaction_marker",
                name="External prewritten marker",
            )
        )
        write_locked.set()
        if not file_locked.wait(timeout=15):
            raise RuntimeError("normal seed did not acquire its file lock")

        with Session(bind=connection) as db:
            started_at = time.monotonic()
            try:
                seed_quantxy_workbench(db)
            except RuntimeError as exc:
                elapsed = time.monotonic() - started_at
                results.put(
                    (
                        "external_prewritten_rejected",
                        str(exc),
                        elapsed,
                        connection.in_transaction(),
                    )
                )
            else:
                results.put(
                    (
                        "external_prewritten_error",
                        "seed unexpectedly succeeded",
                        None,
                        connection.in_transaction(),
                    )
                )
    except Exception as exc:  # noqa: BLE001 - report child failures to the parent process
        results.put(
            (
                "external_prewritten_error",
                f"{type(exc).__name__}: {exc}",
                None,
                connection.in_transaction(),
            )
        )
        write_locked.set()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection.close()
        process_engine.dispose()


def _locked_normal_seed_in_process(
    database_url: str,
    write_locked: Any,
    file_locked: Any,
    results: Any,
) -> None:
    process_engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False, "timeout": 10},
    )
    try:
        if not write_locked.wait(timeout=15):
            raise RuntimeError("prewritten transaction did not acquire its database lock")
        with Session(process_engine) as db:
            acquire_quantxy_seed_transaction_lock(db)
            file_locked.set()
            seed_quantxy_workbench(db)
            db.commit()
        results.put(("normal_ok", None, None))
    except Exception as exc:  # noqa: BLE001 - report child failures to the parent process
        results.put(("normal_error", f"{type(exc).__name__}: {exc}", None))
        file_locked.set()
    finally:
        process_engine.dispose()


def test_demo_seed_serializes_two_spawned_processes_on_one_wal_database(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "multiprocess-seed.db"
    database_url = f"sqlite:///{database_path}"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ULTRARAG_DOTENV", "/dev/null")

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        journal_mode = connection.execute(text("PRAGMA journal_mode=WAL")).scalar_one()
    assert journal_mode == "wal"
    engine.dispose()

    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_seed_demo_data_in_process,
            args=(database_url, str(data_dir), start, results),
        )
        for _ in range(2)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        outcomes = [results.get(timeout=5) for _ in processes]

        assert [process.exitcode for process in processes] == [0, 0]
        assert outcomes == [("ok", None), ("ok", None)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()

    verification_engine = create_engine(database_url)
    with Session(verification_engine) as db:
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
    verification_engine.dispose()
    assert database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    ).is_file()


def test_demo_seed_serializes_spawned_processes_using_real_and_symlink_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "real-multiprocess-seed.db"
    symlink_path = tmp_path / "absolute-symlink-seed.db"
    database_url = f"sqlite:///{database_path}"
    symlink_url = f"sqlite:///{symlink_path}"
    data_dir = tmp_path / "symlink-data"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ULTRARAG_DOTENV", "/dev/null")

    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        journal_mode = connection.execute(text("PRAGMA journal_mode=WAL")).scalar_one()
    assert journal_mode == "wal"
    engine.dispose()
    symlink_path.symlink_to(database_path)

    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_seed_demo_data_in_process,
            args=(url, str(data_dir), start, results),
        )
        for url in (database_url, symlink_url)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        outcomes = [results.get(timeout=5) for _ in processes]

        assert [process.exitcode for process in processes] == [0, 0]
        assert outcomes == [("ok", None), ("ok", None)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()

    verification_engine = create_engine(database_url)
    with Session(verification_engine) as db:
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
    verification_engine.dispose()

    canonical_lock_path = database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    )
    symlink_lock_path = symlink_path.with_name(
        f"{symlink_path.name}.quantxy-seed.lock"
    )
    assert canonical_lock_path.is_file()
    assert not symlink_lock_path.exists()


def test_sqlite_seed_lock_uses_the_url_database_not_its_query(tmp_path: Path) -> None:
    database_path = tmp_path / "query-identity.db"
    database_url = f"sqlite:///{database_path}?timeout=5"
    engine = create_engine(database_url)

    with Session(engine) as db:
        acquire_quantxy_seed_transaction_lock(db)
        db.rollback()

    expected_lock_path = database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    )
    assert expected_lock_path.is_file()
    assert list(tmp_path.glob("*.quantxy-seed.lock")) == [expected_lock_path]
    engine.dispose()


def test_sqlite_file_uri_uses_its_real_file_for_lock_identity(tmp_path: Path) -> None:
    from app.db import workbench_seed

    database_path = tmp_path / "uri-identity.db"
    engine = create_engine(f"sqlite:///file:{database_path}?timeout=5&uri=true")
    with Session(engine) as db:
        assert workbench_seed._sqlite_seed_lock_path(db) == database_path.with_name(
            f"{database_path.name}.quantxy-seed.lock"
        )
    engine.dispose()


def test_sqlite_seed_lock_uses_sqlites_identity_for_literal_percent_paths(
    tmp_path: Path,
) -> None:
    from app.db import workbench_seed

    database_path = tmp_path / "literal%20identity.db"
    ordinary_url = f"sqlite:///{database_path}"
    sqlite_uri_url = (
        f"sqlite:///file:{str(database_path).replace('%', '%25')}?uri=true"
    )
    expected_lock_path = database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    )
    engines = [create_engine(ordinary_url), create_engine(sqlite_uri_url)]
    try:
        lock_paths = []
        for engine in engines:
            with Session(engine) as db:
                lock_paths.append(workbench_seed._sqlite_seed_lock_path(db))
        assert lock_paths == [expected_lock_path, expected_lock_path]
    finally:
        for engine in engines:
            engine.dispose()


def test_sqlite_seed_lock_treats_memory_syntax_according_to_sqlite_uri_mode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import workbench_seed

    monkeypatch.chdir(tmp_path)
    disk_cases = {
        "sqlite:///file::memory:": tmp_path / "file::memory:",
        "sqlite:///mode-false.db?mode=memory": tmp_path / "mode-false.db",
    }
    for database_url, database_path in disk_cases.items():
        engine = create_engine(database_url)
        try:
            with Session(engine) as db:
                assert workbench_seed._sqlite_seed_lock_path(
                    db
                ) == database_path.resolve().with_name(
                    f"{database_path.name}.quantxy-seed.lock"
                )
        finally:
            engine.dispose()

    memory_urls = (
        "sqlite:///file::memory:?cache=shared&uri=true",
        "sqlite:///file:quantxy-named?mode=memory&cache=shared&uri=true",
    )
    for database_url in memory_urls:
        engine = create_engine(database_url)
        try:
            with Session(engine) as db:
                assert workbench_seed._sqlite_seed_lock_path(db) is None
        finally:
            engine.dispose()


def test_sqlite_seed_lock_ignores_uri_fragments_in_physical_identity(
    tmp_path: Path,
) -> None:
    from app.db import workbench_seed

    database_path = tmp_path / "fragment-identity.db"
    expected_lock_path = database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    )
    engines = [
        create_engine(f"sqlite:///file:{database_path}#{fragment}?uri=true")
        for fragment in ("first", "second")
    ]
    try:
        lock_paths = []
        for engine in engines:
            with Session(engine) as db:
                lock_paths.append(workbench_seed._sqlite_seed_lock_path(db))
        assert lock_paths == [expected_lock_path, expected_lock_path]
    finally:
        for engine in engines:
            engine.dispose()


def test_sqlite_seed_lock_follows_an_existing_relative_engine_connection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import workbench_seed

    original_directory = tmp_path / "original"
    later_directory = tmp_path / "later"
    original_directory.mkdir()
    later_directory.mkdir()
    monkeypatch.chdir(original_directory)
    engine = create_engine("sqlite:///relative-identity.db")
    raw_connection = engine.raw_connection()
    try:
        cursor = raw_connection.cursor()
        cursor.execute("PRAGMA database_list")
        sqlite_filename = next(
            row[2] for row in cursor.fetchall() if row[1] == "main"
        )
        cursor.close()
    finally:
        raw_connection.close()

    monkeypatch.chdir(later_directory)
    try:
        with Session(engine) as db:
            assert workbench_seed._sqlite_seed_lock_path(
                db
            ) == (original_directory / "relative-identity.db").resolve().with_name(
                "relative-identity.db.quantxy-seed.lock"
            )
            assert not db.in_transaction()
        assert Path(sqlite_filename).resolve() == (
            original_directory / "relative-identity.db"
        ).resolve()
    finally:
        engine.dispose()


def test_sqlite_lock_identity_probe_does_not_start_sqlalchemy_transactions(
    tmp_path: Path,
) -> None:
    from app.db import workbench_seed

    database_path = tmp_path / "transaction-free-probe.db"
    expected_lock_path = database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    )
    engine = create_engine(f"sqlite:///{database_path}")
    try:
        with Session(engine) as db:
            assert not db.in_transaction()
            assert workbench_seed._sqlite_seed_lock_path(db) == expected_lock_path
            assert not db.in_transaction()

        with engine.connect() as connection:
            assert not connection.in_transaction()
            with Session(bind=connection) as db:
                assert not db.in_transaction()
                assert workbench_seed._sqlite_seed_lock_path(db) == expected_lock_path
                assert not db.in_transaction()
                assert not connection.in_transaction()
    finally:
        engine.dispose()


@pytest.mark.parametrize(
    "database_url",
    [
        "sqlite:///:memory:",
        "sqlite+pysqlite:///:memory:",
        "sqlite:///file:quantxy-memory?mode=memory&cache=shared&uri=true",
        "sqlite+pysqlite:///file:quantxy-memory?mode=memory&cache=shared&uri=true",
    ],
)
def test_sqlite_memory_urls_do_not_have_a_file_lock_path(database_url: str) -> None:
    from app.db import workbench_seed

    engine = create_engine(database_url)
    with Session(engine) as db:
        assert workbench_seed._sqlite_seed_lock_path(db) is None
    engine.dispose()


def test_demo_seed_serializes_plain_and_driver_urls_with_queries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "driver-query-multiprocess.db"
    plain_url = f"sqlite:///{database_path}?timeout=0.001"
    driver_url = f"sqlite+pysqlite:///{database_path}?timeout=0.001"
    data_dir = tmp_path / "driver-query-data"
    monkeypatch.setenv("DATABASE_URL", plain_url)
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ULTRARAG_DOTENV", "/dev/null")

    engine = create_engine(plain_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode=WAL")).scalar_one() == "wal"
    engine.dispose()

    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_seed_demo_data_in_process,
            args=(url, str(data_dir), start, results),
        )
        for url in (plain_url, driver_url)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        outcomes = [results.get(timeout=5) for _ in processes]

        assert [process.exitcode for process in processes] == [0, 0]
        assert outcomes == [("ok", None), ("ok", None)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()

    verification_engine = create_engine(plain_url)
    with Session(verification_engine) as db:
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
    verification_engine.dispose()

    canonical_lock_path = database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    )
    assert canonical_lock_path.is_file()
    assert list(tmp_path.glob("*.quantxy-seed.lock")) == [canonical_lock_path]


def test_demo_seed_serializes_literal_percent_and_equivalent_uri_urls(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_path = tmp_path / "weird%20multiprocess.db"
    ordinary_url = f"sqlite:///{database_path}?timeout=0.001"
    sqlite_uri_url = (
        f"sqlite:///file:{str(database_path).replace('%', '%25')}"
        "?timeout=0.001&uri=true"
    )
    data_dir = tmp_path / "weird-url-data"
    monkeypatch.setenv("DATABASE_URL", ordinary_url)
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ULTRARAG_DOTENV", "/dev/null")

    engine = create_engine(ordinary_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode=WAL")).scalar_one() == "wal"
    engine.dispose()

    context = multiprocessing.get_context("spawn")
    start = context.Barrier(2)
    results = context.Queue()
    processes = [
        context.Process(
            target=_seed_demo_data_in_process,
            args=(url, str(data_dir), start, results),
        )
        for url in (ordinary_url, sqlite_uri_url)
    ]
    try:
        for process in processes:
            process.start()
        for process in processes:
            process.join(timeout=30)
        outcomes = [results.get(timeout=5) for _ in processes]

        assert [process.exitcode for process in processes] == [0, 0]
        assert outcomes == [("ok", None), ("ok", None)]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()

    verification_engine = create_engine(ordinary_url)
    with Session(verification_engine) as db:
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
    verification_engine.dispose()

    canonical_lock_path = database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    )
    assert canonical_lock_path.is_file()
    assert list(tmp_path.glob("*.quantxy-seed.lock")) == [canonical_lock_path]


@pytest.mark.parametrize("cleanup", ["rollback", "close"])
def test_sqlite_seed_lock_releases_after_failed_session_cleanup(
    cleanup: str,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / f"failed-{cleanup}.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode=WAL")).scalar_one() == "wal"
    engine.dispose()

    context = multiprocessing.get_context("spawn")
    cleaned_up = context.Event()
    finish = context.Event()
    results = context.Queue()
    holder = context.Process(
        target=_fail_seed_then_wait_in_process,
        args=(database_url, cleanup, cleaned_up, finish, results),
    )
    contender: multiprocessing.Process | None = None
    try:
        holder.start()
        assert cleaned_up.wait(timeout=15)
        assert results.get(timeout=5) == ("holder_cleaned", "RuntimeError")

        setup_engine = create_engine(database_url)
        with Session(setup_engine) as db:
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
        setup_engine.dispose()

        contender = context.Process(
            target=_seed_quantxy_workbench_in_process,
            args=(database_url, results),
        )
        contender.start()
        contender.join(timeout=15)
        assert contender.exitcode == 0
        assert results.get(timeout=5) == ("contender_ok", None)
    finally:
        finish.set()
        holder.join(timeout=5)
        for process in (holder, contender):
            if process is not None and process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()

    assert holder.exitcode == 0
    assert database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    ).is_file()


def test_sqlite_seed_lock_closes_file_and_thread_lock_when_acquisition_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import workbench_seed

    engine = create_engine(f"sqlite:///{tmp_path / 'failed-acquisition.db'}")
    captured_handle: list[Any] = []

    def fail_lock(handle: Any) -> None:
        captured_handle.append(handle)
        raise OSError("lock acquisition failed")

    monkeypatch.setattr(workbench_seed, "_lock_file", fail_lock)
    with Session(engine) as db, pytest.raises(OSError, match="lock acquisition failed"):
        acquire_quantxy_seed_transaction_lock(db)

    assert len(captured_handle) == 1
    assert captured_handle[0].closed
    assert workbench_seed._SEED_LOCK.acquire(blocking=False)
    workbench_seed._SEED_LOCK.release()
    engine.dispose()


class _WindowsLockHandle:
    def __init__(self) -> None:
        self.read_calls = 0
        self.seek_offsets: list[int] = []

    def seek(self, offset: int, whence: int = 0) -> None:
        assert whence == 0
        self.seek_offsets.append(offset)

    def read(self, size: int = -1) -> bytes:
        self.read_calls += 1
        raise AssertionError("the locked byte must not be read before acquisition")

    def fileno(self) -> int:
        return 42


def test_windows_seed_lock_does_not_read_and_retries_only_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import workbench_seed

    handle = _WindowsLockHandle()
    calls: list[tuple[int, int, int]] = []

    def locking(file_descriptor: int, mode: int, byte_count: int) -> None:
        calls.append((file_descriptor, mode, byte_count))
        if len(calls) < 3:
            error = OSError(errno.EACCES, "lock contention")
            error.winerror = 33  # type: ignore[attr-defined]
            raise error

    fake_msvcrt = SimpleNamespace(
        LK_LOCK=1,
        LK_NBLCK=2,
        LK_UNLCK=3,
        locking=locking,
    )
    with monkeypatch.context() as patch:
        patch.setattr(workbench_seed.os, "name", "nt")
        patch.setitem(sys.modules, "msvcrt", fake_msvcrt)
        workbench_seed._lock_file(handle)  # type: ignore[arg-type]

    assert handle.read_calls == 0
    assert handle.seek_offsets == [0]
    assert calls == [(42, fake_msvcrt.LK_NBLCK, 1)] * 3


def test_windows_seed_lock_propagates_non_contention_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import workbench_seed

    handle = _WindowsLockHandle()
    calls: list[tuple[int, int, int]] = []

    def locking(file_descriptor: int, mode: int, byte_count: int) -> None:
        calls.append((file_descriptor, mode, byte_count))
        raise OSError(errno.EIO, "disk failure")

    fake_msvcrt = SimpleNamespace(
        LK_LOCK=1,
        LK_NBLCK=2,
        LK_UNLCK=3,
        locking=locking,
    )
    with monkeypatch.context() as patch:
        patch.setattr(workbench_seed.os, "name", "nt")
        patch.setitem(sys.modules, "msvcrt", fake_msvcrt)
        with pytest.raises(OSError, match="disk failure"):
            workbench_seed._lock_file(handle)  # type: ignore[arg-type]

    assert handle.read_calls == 0
    assert handle.seek_offsets == [0]
    assert calls == [(42, fake_msvcrt.LK_NBLCK, 1)]


def test_windows_seed_lock_initializes_a_lockable_byte_before_competing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.db import workbench_seed

    lock_path = tmp_path / "windows-seed.lock"
    captured_sizes: list[int] = []

    def capture_lock(handle: Any) -> None:
        captured_sizes.append(os.fstat(handle.fileno()).st_size)

    with monkeypatch.context() as patch:
        patch.setattr(workbench_seed.os, "name", "nt")
        patch.setattr(workbench_seed, "_lock_file", capture_lock)
        handle = workbench_seed._open_file_lock(lock_path)
    handle.close()

    assert captured_sizes == [1]
    assert lock_path.read_bytes() == b"0"


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


def test_quantxy_seed_rejects_an_empty_workbench_after_a_transaction_started(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "prewritten-contract.db"
    engine = create_engine(f"sqlite:///{database_path}")
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

        db.add(Tenant(id="prewritten_contract_marker", name="Prewritten marker"))
        db.flush()
        with pytest.raises(
            RuntimeError,
            match="seed transaction lock must be acquired before the Session starts",
        ):
            seed_quantxy_workbench(db)
        db.rollback()

    assert not database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    ).exists()
    engine.dispose()


def test_quantxy_lock_acquisition_rejects_a_preexisting_root_transaction(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'direct-lock-contract.db'}")
    with Session(engine) as db:
        db.begin()
        with pytest.raises(
            RuntimeError,
            match="seed transaction lock must be acquired before the Session starts",
        ):
            acquire_quantxy_seed_transaction_lock(db)
        db.rollback()
    engine.dispose()


def test_quantxy_lock_rejects_an_external_connection_write_transaction(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "external-connection-contract.db"
    engine = create_engine(f"sqlite:///{database_path}")
    SQLModel.metadata.create_all(engine)

    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            Tenant.__table__.insert().values(
                id="external_contract_marker",
                name="External contract marker",
            )
        )
        with Session(bind=connection) as db, pytest.raises(
            RuntimeError,
            match="seed transaction lock must be acquired before the Session starts",
        ):
            acquire_quantxy_seed_transaction_lock(db)
        assert connection.in_transaction()
        transaction.rollback()

    assert not database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    ).exists()
    engine.dispose()


def test_existing_workbench_is_a_noop_inside_an_external_connection_transaction(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "external-existing-noop.db"
    engine = create_engine(f"sqlite:///{database_path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as db:
        admin = User(
            id="admin",
            tenant_id="tenant_demo",
            username="admin",
            role="admin",
            password_hash="admin-hash",
        )
        db.add_all(
            [
                Tenant(id="tenant_demo", name="Demo Enterprise"),
                admin,
                User(
                    id="user_demo",
                    tenant_id="tenant_demo",
                    username="user_demo",
                    password_hash="demo-hash",
                ),
                Department(
                    id="user_owned_department",
                    tenant_id="tenant_demo",
                    name="User-owned department",
                    code="OWNED",
                    manager_user_id=admin.id,
                ),
            ]
        )
        db.commit()

    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            Tenant.__table__.insert().values(
                id="external_existing_marker",
                name="External existing marker",
            )
        )
        with Session(bind=connection) as db:
            seed_quantxy_workbench(db)
        assert connection.in_transaction()
        transaction.rollback()

    assert not database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    ).exists()
    with Session(engine) as db:
        assert _model_ids(db, Department) == ("user_owned_department",)
        assert _model_ids(db, EmployeeProfile) == ()
        assert _model_ids(db, WorkProject) == ()
        assert db.get(Tenant, "external_existing_marker") is None
    engine.dispose()


def test_existing_workbench_is_a_safe_noop_inside_a_preexisting_transaction(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'existing-noop.db'}")
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
        seed_quantxy_workbench(db)
        db.commit()

    with Session(engine) as db:
        db.add(Tenant(id="existing_noop_marker", name="Existing no-op marker"))
        db.flush()
        seed_quantxy_workbench(db)
        db.rollback()

    with Session(engine) as db:
        assert db.get(Tenant, "existing_noop_marker") is None
        assert _model_ids(db, Department) == tuple(sorted(EXPECTED_DEPARTMENTS))
        assert _model_ids(db, EmployeeProfile) == tuple(sorted(EXPECTED_EMPLOYEES))
    engine.dispose()


def test_prewritten_transaction_fails_fast_without_deadlocking_normal_seed(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "prewritten-deadlock.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode=WAL")).scalar_one() == "wal"
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
    engine.dispose()

    context = multiprocessing.get_context("spawn")
    write_locked = context.Event()
    file_locked = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_prewritten_seed_in_process,
            args=(database_url, write_locked, file_locked, results),
        ),
        context.Process(
            target=_locked_normal_seed_in_process,
            args=(database_url, write_locked, file_locked, results),
        ),
    ]
    try:
        for process in processes:
            process.start()
        deadline = time.monotonic() + 12
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))

        assert [process.exitcode for process in processes] == [0, 0]
        outcomes = [results.get(timeout=5) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()

    by_name = {name: (detail, elapsed) for name, detail, elapsed in outcomes}
    assert set(by_name) == {"prewritten_rejected", "normal_ok"}
    message, elapsed = by_name["prewritten_rejected"]
    assert "seed transaction lock must be acquired before the Session starts" in message
    assert elapsed is not None and elapsed < 2

    verification_engine = create_engine(database_url)
    with Session(verification_engine) as db:
        assert db.get(Tenant, "prewritten_transaction_marker") is None
        assert _model_ids(db, Department) == tuple(sorted(EXPECTED_DEPARTMENTS))
        assert _model_ids(db, EmployeeProfile) == tuple(sorted(EXPECTED_EMPLOYEES))
    verification_engine.dispose()


def test_external_connection_transaction_does_not_invert_the_seed_lock(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "external-connection-deadlock.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA journal_mode=WAL")).scalar_one() == "wal"
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
    engine.dispose()

    context = multiprocessing.get_context("spawn")
    write_locked = context.Event()
    file_locked = context.Event()
    results = context.Queue()
    processes = [
        context.Process(
            target=_external_prewritten_seed_in_process,
            args=(database_url, write_locked, file_locked, results),
        ),
        context.Process(
            target=_locked_normal_seed_in_process,
            args=(database_url, write_locked, file_locked, results),
        ),
    ]
    try:
        for process in processes:
            process.start()
        deadline = time.monotonic() + 12
        for process in processes:
            process.join(timeout=max(0, deadline - time.monotonic()))

        assert [process.exitcode for process in processes] == [0, 0]
        outcomes = [results.get(timeout=5) for _ in processes]
    finally:
        for process in processes:
            if process.is_alive():
                process.terminate()
                process.join(timeout=5)
        results.close()
        results.join_thread()

    external = next(item for item in outcomes if item[0].startswith("external_"))
    normal = next(item for item in outcomes if item[0].startswith("normal_"))
    assert normal == ("normal_ok", None, None)
    assert external[0] == "external_prewritten_rejected"
    assert "seed transaction lock must be acquired before the Session starts" in external[1]
    assert external[2] is not None and external[2] < 2
    assert external[3] is True

    verification_engine = create_engine(database_url)
    with Session(verification_engine) as db:
        assert db.get(Tenant, "external_prewritten_transaction_marker") is None
        assert _model_ids(db, Department) == tuple(sorted(EXPECTED_DEPARTMENTS))
        assert _model_ids(db, EmployeeProfile) == tuple(sorted(EXPECTED_EMPLOYEES))
    verification_engine.dispose()


@pytest.mark.parametrize("cleanup", ["commit", "rollback", "close"])
def test_connection_bound_seed_cleanup_releases_transaction_and_lock_for_a_process(
    cleanup: str,
    tmp_path: Path,
) -> None:
    database_path = tmp_path / f"connection-bound-{cleanup}.db"
    database_url = f"sqlite:///{database_path}"
    engine = create_engine(database_url)
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

    with engine.connect() as connection:
        db = Session(bind=connection)
        seed_quantxy_workbench(db)
        assert connection.in_transaction()
        seed_quantxy_workbench(db)
        getattr(db, cleanup)()
        assert not connection.in_transaction()

        context = multiprocessing.get_context("spawn")
        results = context.Queue()
        contender = context.Process(
            target=_seed_quantxy_workbench_in_process,
            args=(database_url, results),
        )
        try:
            contender.start()
            contender.join(timeout=15)
            assert contender.exitcode == 0
            assert results.get(timeout=5) == ("contender_ok", None)
        finally:
            if contender.is_alive():
                contender.terminate()
                contender.join(timeout=5)
            results.close()
            results.join_thread()
            db.close()

    with Session(engine) as db:
        assert _model_ids(db, Department) == tuple(sorted(EXPECTED_DEPARTMENTS))
        assert _model_ids(db, EmployeeProfile) == tuple(sorted(EXPECTED_EMPLOYEES))
    assert database_path.with_name(
        f"{database_path.name}.quantxy-seed.lock"
    ).is_file()
    engine.dispose()


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

        acquire_quantxy_seed_transaction_lock(db)
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
        db.rollback()
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
