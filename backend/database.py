"""SQLAlchemy engine, sessions, and versioned schema initialization.

The default database is a local SQLite file. ``TON_CHECK_DB_URL`` can select
an alternative SQLite SQLAlchemy URL. Runtime startup delegates schema changes
to the checked-in migration runner; it never repairs drift with
``create_all()``.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

if TYPE_CHECKING:
    from services.database_migrations import MigrationReport

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


def init_db() -> MigrationReport:
    """Upgrade the configured database to the checked-in migration head."""
    from services.database_migrations import run_database_migrations

    return run_database_migrations(engine)


def get_session():
    """FastAPI dependency yielding a scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
