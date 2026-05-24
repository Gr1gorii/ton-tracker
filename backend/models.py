"""SQLAlchemy models.

v0.1 persists a lightweight record of each analysis run. The full result is
stored as a JSON blob so the schema does not need to change as the analysis
payload evolves.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, Text

from database import Base


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"

    id = Column(Integer, primary_key=True, index=True)
    pool_url = Column(String, nullable=False)
    time_window = Column(String, nullable=False)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    # Full analysis payload as JSON text (mock in v0.1).
    result_json = Column(Text, nullable=False)
