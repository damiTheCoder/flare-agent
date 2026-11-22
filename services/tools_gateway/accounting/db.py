"""SQL engine shared by every accounting tool.

Production reads ``DATABASE_URL`` (PostgreSQL). The engine is created lazily,
the schema is applied once on first use, and connections are pooled by
SQLAlchemy. Tests point :func:`reset_engine` at a throwaway SQLite file so the
suite stays hermetic without a Postgres server.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

_lock = threading.Lock()
_engine: Engine | None = None
_schema_ready = False


def _normalize(url: str) -> str:
    """Accept the URL shapes platforms hand out and pick a SQLAlchemy driver."""
    value = url.strip()
    if value.startswith("postgres://"):
        value = "postgresql://" + value[len("postgres://") :]
    if value.startswith("postgresql://"):
        value = "postgresql+psycopg://" + value[len("postgresql://") :]
    return value


def configured_url() -> str:
    raw = (
        os.environ.get("DATABASE_URL", "").strip()
        or os.environ.get("FLARE_DATABASE_URL", "").strip()
    )
    if not raw:
        raise RuntimeError(
            "DATABASE_URL is not set. Point it at PostgreSQL, for example "
            "postgresql://user:password@host:5432/microbalance"
        )
    return _normalize(raw)


def _build(url: str) -> Engine:
    if url.startswith("sqlite"):
        options: dict[str, Any] = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in url:
            options["poolclass"] = StaticPool
        return create_engine(url, **options)
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )


def get_engine() -> Engine:
    global _engine
    with _lock:
        if _engine is None:
            _engine = _build(configured_url())
        return _engine


def dialect_name() -> str:
    return get_engine().dialect.name


def reset_engine(url: str | None = None) -> None:
    """Swap (or forget) the engine; used by tests and by schema bootstrap."""
    global _engine, _schema_ready
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = _build(_normalize(url)) if url is not None else None
        _schema_ready = False


def ensure_schema(statements: list[str]) -> None:
    """Create tables and indexes if they are not there yet (idempotent)."""
    global _engine, _schema_ready
    with _lock:
        if _engine is None:
            _engine = _build(configured_url())
        if _schema_ready:
            return
        with _engine.begin() as connection:
            for statement in statements:
                connection.exec_driver_sql(statement)
        _schema_ready = True


def table_columns(table: str) -> set[str]:
    """Column names for a table, via SQLAlchemy reflection (any dialect)."""
    return {column["name"] for column in inspect(get_engine()).get_columns(table)}


def ping() -> None:
    """Raise if the database is unreachable."""
    with get_engine().connect() as connection:
        connection.exec_driver_sql("SELECT 1")
