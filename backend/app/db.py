from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC everywhere. Avoids tz drift between Postgres and SQLite (tests)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_engine(url: str):
    if url.startswith("sqlite"):
        args = {"connect_args": {"check_same_thread": False}}
        if url in {"sqlite://", "sqlite:///:memory:"}:
            # In-memory DB (tests only): one shared connection so every session sees the same data.
            # Never use StaticPool for file databases: concurrent requests would interleave on one connection.
            from sqlalchemy.pool import StaticPool
            args["poolclass"] = StaticPool
        return create_engine(url, **args)
    return create_engine(url, pool_pre_ping=True)


engine = make_engine(settings.database_url)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def configure(url: str) -> None:
    """Rebind the engine (used by tests)."""
    global engine
    engine = make_engine(url)
    SessionLocal.configure(bind=engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
