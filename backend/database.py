"""SQLite database setup for v0.1.

A single local SQLite file is used to persist analysis runs so they can be
listed / re-exported later. The engine + session factory live here; models
live in ``models.py``.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Store the SQLite file next to the backend package.
_DB_PATH = os.path.join(os.path.dirname(__file__), "ton_check.db")
DATABASE_URL = os.environ.get("TON_CHECK_DB_URL", f"sqlite:///{_DB_PATH}")

# check_same_thread=False is required for SQLite under the FastAPI worker model.
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False}
    if DATABASE_URL.startswith("sqlite")
    else {},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def init_db() -> None:
    """Create tables. Import models for side-effect registration first."""
    import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_session():
    """FastAPI dependency yielding a scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
