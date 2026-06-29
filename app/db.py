"""Database engine + session helpers."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, String, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from .config import get_settings

settings = get_settings()

# check_same_thread=False so the APScheduler background thread can share the
# SQLite engine with FastAPI's request threads.
connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, echo=False, connect_args=connect_args)


def init_db() -> None:
    # Import models so they register on SQLModel.metadata before create_all.
    from . import models  # noqa: F401

    SQLModel.metadata.create_all(engine)
    # create_all never ALTERs existing tables, so add columns introduced after
    # a DB was first created (e.g. snooze's muted_until on persisted volumes).
    _ensure_column(models.Incident.__tablename__, "muted_until", DateTime())
    _ensure_column(models.Incident.__tablename__, "resolved_by", String())


def _ensure_column(table: str, name: str, sa_type) -> None:
    """Add a column to an existing table if it's missing. Idempotent."""
    existing = {c["name"] for c in inspect(engine).get_columns(table)}
    if name in existing:
        return
    type_sql = sa_type.compile(dialect=engine.dialect)
    with engine.begin() as conn:
        conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {type_sql}"))


def get_session() -> Session:
    return Session(engine)


def utcnow() -> datetime:
    """Naive UTC 'now'. We keep all stored datetimes naive-UTC for SQLite."""
    return datetime.now(timezone.utc).replace(tzinfo=None)
