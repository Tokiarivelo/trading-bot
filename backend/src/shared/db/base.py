"""SQLAlchemy foundation: declarative base and session factory.

Module ORM models inherit from `Base`; alembic autogenerates migrations from
its metadata (see `migrations/env.py`).
"""

from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


def make_session_factory(database_url: str) -> sessionmaker[Session]:
    # Sync engine is fine at this scale; SQLite for dev, PostgreSQL later.
    sync_url = database_url.replace("+aiosqlite", "")
    engine = create_engine(sync_url, echo=False)
    return sessionmaker(bind=engine, expire_on_commit=False)
