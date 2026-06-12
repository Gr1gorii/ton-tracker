"""SQLAlchemy models.

v0.1 persists a lightweight record of each analysis run. The full result is
stored as a JSON blob so the schema does not need to change as the analysis
payload evolves.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import relationship

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


class WalletIngestionRun(Base):
    """Source-aware wallet activity ingestion run scaffold.

    v0.11.1 defines persistence boundaries only. Provider calls and analytics
    wiring are intentionally deferred to later milestones.
    """

    __tablename__ = "wallet_ingestion_runs"

    id = Column(Integer, primary_key=True, index=True)
    wallet_address = Column(String, nullable=False, index=True)
    time_window = Column(String, nullable=False)
    custom_start = Column(DateTime, nullable=True)
    custom_end = Column(DateTime, nullable=True)
    data_mode = Column(String, nullable=False, default="mock")
    status = Column(String, nullable=False, default="planned")
    requested_surfaces_json = Column(Text, nullable=False, default="[]")
    provider_summary_json = Column(Text, nullable=False, default="{}")
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )
    updated_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    transfers = relationship(
        "WalletTransfer",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    transactions = relationship(
        "WalletTransaction",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    swaps = relationship(
        "WalletSwap",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    balance_snapshots = relationship(
        "WalletBalanceSnapshot",
        back_populates="run",
        cascade="all, delete-orphan",
    )
    warnings = relationship(
        "WalletIngestionWarning",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class WalletTransfer(Base):
    __tablename__ = "wallet_transfers"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("wallet_ingestion_runs.id"),
        nullable=False,
        index=True,
    )
    tx_hash = Column(String, nullable=True, index=True)
    logical_time = Column(String, nullable=True, index=True)
    timestamp = Column(DateTime, nullable=True)
    asset = Column(String, nullable=False)
    amount = Column(Numeric(38, 18), nullable=True)
    direction = Column(String, nullable=False)
    counterparty = Column(String, nullable=True)
    provider = Column(String, nullable=False)
    source_status = Column(String, nullable=False)
    raw_json = Column(Text, nullable=True)

    run = relationship("WalletIngestionRun", back_populates="transfers")


class WalletTransaction(Base):
    __tablename__ = "wallet_transactions"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("wallet_ingestion_runs.id"),
        nullable=False,
        index=True,
    )
    tx_hash = Column(String, nullable=False, index=True)
    logical_time = Column(String, nullable=True, index=True)
    timestamp = Column(DateTime, nullable=True)
    fee_ton = Column(Numeric(38, 18), nullable=True)
    success = Column(String, nullable=False, default="unknown")
    provider = Column(String, nullable=False)
    source_status = Column(String, nullable=False)
    raw_json = Column(Text, nullable=True)

    run = relationship("WalletIngestionRun", back_populates="transactions")


class WalletSwap(Base):
    __tablename__ = "wallet_swaps"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("wallet_ingestion_runs.id"),
        nullable=False,
        index=True,
    )
    tx_hash = Column(String, nullable=True, index=True)
    timestamp = Column(DateTime, nullable=True)
    dex = Column(String, nullable=True)
    token_in = Column(String, nullable=True)
    amount_in = Column(Numeric(38, 18), nullable=True)
    token_out = Column(String, nullable=True)
    amount_out = Column(Numeric(38, 18), nullable=True)
    estimated_usd = Column(Numeric(24, 8), nullable=True)
    provider = Column(String, nullable=False)
    source_status = Column(String, nullable=False)
    raw_json = Column(Text, nullable=True)

    run = relationship("WalletIngestionRun", back_populates="swaps")


class WalletBalanceSnapshot(Base):
    __tablename__ = "wallet_balance_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("wallet_ingestion_runs.id"),
        nullable=False,
        index=True,
    )
    asset = Column(String, nullable=False)
    balance = Column(Numeric(38, 18), nullable=True)
    balance_usd = Column(Numeric(24, 8), nullable=True)
    provider = Column(String, nullable=False)
    source_status = Column(String, nullable=False)
    snapshot_at = Column(DateTime, nullable=True)
    raw_json = Column(Text, nullable=True)

    run = relationship("WalletIngestionRun", back_populates="balance_snapshots")


class WalletIngestionWarning(Base):
    __tablename__ = "wallet_ingestion_warnings"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(
        Integer,
        ForeignKey("wallet_ingestion_runs.id"),
        nullable=False,
        index=True,
    )
    severity = Column(String, nullable=False)
    provider = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    evidence_key = Column(String, nullable=True)
    created_at = Column(
        DateTime, default=lambda: datetime.now(timezone.utc), nullable=False
    )

    run = relationship("WalletIngestionRun", back_populates="warnings")
