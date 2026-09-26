"""Database session management.

SQLite by default (one file under data/), Postgres by changing
BRANDGUARD_DATABASE_URL. SQLite is opened in WAL mode so the worker threads
can write while the API reads, and ``check_same_thread`` is relaxed because
requests and jobs run on different threads and each uses its own session.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from brandguard.config import database_url


class Base(DeclarativeBase):
    pass


_engine = None
_SessionLocal: sessionmaker[Session] | None = None


def get_engine():
    global _engine, _SessionLocal
    if _engine is None:
        url = database_url()
        kwargs = {}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
        _engine = create_engine(url, future=True, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _record):  # pragma: no cover - driver hook
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.close()
        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def reset_engine() -> None:
    """Drop the cached engine (tests point BRANDGUARD_DATABASE_URL at a temp file)."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine, _SessionLocal = None, None


def init_db() -> None:
    """Create tables. Alembic is deliberately not used yet: create_all is
    enough while the schema is young, and the SQLite file can be recreated."""
    from brandguard.api import models  # noqa: F401 - registers the tables

    engine = get_engine()
    Base.metadata.create_all(engine)
    _add_missing_columns(engine)


# Columns added after the first release, with the DDL that adds them to an
# existing SQLite/Postgres file. create_all never alters a table that exists.
_LATER_COLUMNS = {
    ("scans", "batch_id"): "VARCHAR(32)",
    ("scans", "trigger"): "VARCHAR(16) DEFAULT 'manual'",
    ("brands", "schedule"): "VARCHAR(16) DEFAULT 'off'",
    ("brands", "schedule_sources"): "JSON",
    ("brands", "schedule_depth"): "VARCHAR(16) DEFAULT 'normal'",
    ("brands", "next_run_at"): "DATETIME",
}


def _add_missing_columns(engine) -> None:
    from sqlalchemy import inspect, text

    inspector = inspect(engine)
    with engine.begin() as conn:
        for (table, column), ddl in _LATER_COLUMNS.items():
            if table in inspector.get_table_names():
                present = {c["name"] for c in inspector.get_columns(table)}
                if column not in present:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))


@contextmanager
def session_scope() -> Iterator[Session]:
    """A transaction per unit of work; rolls back on error."""
    get_engine()
    assert _SessionLocal is not None
    session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_session() -> Iterator[Session]:
    """FastAPI dependency."""
    with session_scope() as session:
        yield session
