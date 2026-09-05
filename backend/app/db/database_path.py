from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote

from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app import paths


def normalize_database_url(url: str) -> str:
    if (
        not url.startswith("sqlite:///")
        or url.startswith("sqlite:////")
        or url == "sqlite:///:memory:"
    ):
        return url
    raw_path = unquote(url.removeprefix("sqlite:///"))
    if not raw_path or raw_path == ":memory:":
        return url
    path = Path(raw_path)
    if path.is_absolute():
        return url
    base_dir = (
        paths.user_data_dir()
        if paths.is_frozen()
        else Path(__file__).resolve().parents[2]
    )
    return f"sqlite:///{(base_dir / path).resolve()}"


def sqlite_database_path(url: str) -> Path | None:
    try:
        parsed_url = make_url(url)
    except ArgumentError:
        return None
    base_dir = (
        paths.user_data_dir()
        if paths.is_frozen()
        else Path(__file__).resolve().parents[2]
    )
    return _sqlite_database_path_from_url(parsed_url, relative_base=base_dir)


def sqlite_database_path_from_url(url: URL) -> Path | None:
    """Return the canonical file used by a SQLAlchemy SQLite URL.

    Driver and query components do not participate in file identity. SQLite
    in-memory URLs, including named URI memory databases, have no file path.
    """
    return _sqlite_database_path_from_url(url, relative_base=None)


def _sqlite_database_path_from_url(
    url: URL,
    *,
    relative_base: Path | None,
) -> Path | None:
    if url.get_backend_name() != "sqlite" or not url.database:
        return None

    database = unquote(url.database)
    mode = url.query.get("mode")
    modes = mode if isinstance(mode, tuple) else (mode,)
    if (
        database.casefold() == ":memory:"
        or database.casefold().startswith("file::memory:")
        or any(str(value).casefold() == "memory" for value in modes if value is not None)
    ):
        return None

    uri = url.query.get("uri")
    uri_values = uri if isinstance(uri, tuple) else (uri,)
    if database[:5].casefold() == "file:" and any(
        str(value).casefold() in {"1", "true", "yes", "on"}
        for value in uri_values
        if value is not None
    ):
        database = database[5:]

    path = Path(database).expanduser()
    if relative_base is not None and not path.is_absolute():
        path = relative_base / path
    return path.resolve()


__all__ = [
    "normalize_database_url",
    "sqlite_database_path",
    "sqlite_database_path_from_url",
]
