"""SQLAlchemy models.

v0.1 persists a lightweight record of each analysis run. The full result is
stored as a JSON blob so the schema does not need to change as the analysis
payload evolves.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
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

    v0.11.1 defined persistence boundaries; v0.11.2 stores deterministic
    mock-normalized rows. Provider calls and analytics wiring remain deferred.
    """

    __tablename__ = "wallet_ingestion_runs"
    __table_args__ = (
        Index(
            "ix_wallet_ingestion_runs_wallet_identity",
            "wallet_network",
            "wallet_address_canonical",
        ),
    )

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
    wallet_identity_status = Column(
        String(20), nullable=False, default="unavailable", server_default="unavailable"
    )
    wallet_identity_version = Column(
        String(24), nullable=False, default="unavailable", server_default="unavailable"
    )
    wallet_network = Column(
        String(16), nullable=False, default="ton-unknown", server_default="ton-unknown"
    )
    wallet_address_canonical = Column(String(76), nullable=True)
    wallet_workchain_id = Column(Integer, nullable=True)
    wallet_account_id_hex = Column(String(64), nullable=True)
    wallet_address_format = Column(
        String(16),
        nullable=False,
        default="unrecognized",
        server_default="unrecognized",
    )
    wallet_address_bounceable = Column(Boolean, nullable=True)
    wallet_address_testnet_only = Column(Boolean, nullable=True)

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
    acquisition_streams = relationship(
        "WalletAcquisitionStream",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class WalletAcquisitionStream(Base):
    """Persisted acquisition contract and aggregate evidence for one stream."""

    __tablename__ = "wallet_acquisition_streams"
    __table_args__ = (
        Index(
            "uq_wallet_acquisition_streams_run_provider_key",
            "run_id",
            "provider",
            "stream_key",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    run_id = Column(
        Integer,
        ForeignKey("wallet_ingestion_runs.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider = Column(String(32), nullable=False)
    stream_key = Column(String(40), nullable=False)
    contract_version = Column(String(48), nullable=False)
    scope_kind = Column(String(24), nullable=False)
    resolved_start_at = Column(DateTime, nullable=True)
    resolved_end_at = Column(DateTime, nullable=True)
    # Sanitized provider query metadata only; never headers or credentials.
    request_query_json = Column(
        Text,
        nullable=False,
        default="{}",
        server_default="{}",
    )
    page_size = Column(Integer, nullable=False)
    max_pages = Column(Integer, nullable=False)
    max_items = Column(Integer, nullable=False)
    completion_state = Column(
        String(24),
        nullable=False,
        default="incomplete",
        server_default="incomplete",
    )
    termination_reason = Column(String(48), nullable=True)
    pages_attempted = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    pages_succeeded = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    raw_item_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    normalized_item_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    duplicate_item_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    first_cursor = Column(String(128), nullable=True)
    terminal_cursor = Column(String(128), nullable=True)
    bounds_verified = Column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    # Structured sanitized diagnostics; raw provider exceptions do not belong here.
    error_json = Column(Text, nullable=True)
    started_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    finished_at = Column(DateTime, nullable=True)

    run = relationship("WalletIngestionRun", back_populates="acquisition_streams")
    pages = relationship(
        "WalletAcquisitionPage",
        back_populates="stream",
        cascade="all, delete-orphan",
    )


class WalletAcquisitionPage(Base):
    """Provider-safe evidence for one attempted page in an acquisition stream."""

    __tablename__ = "wallet_acquisition_pages"
    __table_args__ = (
        Index(
            "uq_wallet_acquisition_pages_stream_page",
            "stream_id",
            "page_index",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True)
    stream_id = Column(
        Integer,
        ForeignKey("wallet_acquisition_streams.id", ondelete="CASCADE"),
        nullable=False,
    )
    page_index = Column(Integer, nullable=False)
    request_cursor = Column(String(128), nullable=True)
    response_cursor = Column(String(128), nullable=True)
    request_offset = Column(Integer, nullable=True)
    requested_limit = Column(Integer, nullable=False)
    # Sanitized page query metadata only; never headers or credentials.
    request_query_json = Column(
        Text,
        nullable=False,
        default="{}",
        server_default="{}",
    )
    raw_item_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    normalized_item_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    duplicate_item_count = Column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    newest_logical_time = Column(String(20), nullable=True)
    oldest_logical_time = Column(String(20), nullable=True)
    newest_activity_at = Column(DateTime, nullable=True)
    oldest_activity_at = Column(DateTime, nullable=True)
    response_digest_sha256 = Column(String(64), nullable=True)
    attempt_count = Column(
        Integer,
        nullable=False,
        default=1,
        server_default=text("1"),
    )
    fetch_status = Column(String(16), nullable=False)
    error_code = Column(String(64), nullable=True)
    error_message = Column(Text, nullable=True)
    # Structured sanitized diagnostics for this page attempt.
    error_json = Column(Text, nullable=True)
    fetched_at = Column(
        DateTime,
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    stream = relationship("WalletAcquisitionStream", back_populates="pages")


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
    __table_args__ = (
        Index(
            "uq_wallet_transactions_run_identity",
            "run_id",
            "transaction_identity_key",
            unique=True,
        ),
        Index(
            "ix_wallet_transactions_identity_key",
            "transaction_identity_key",
        ),
        Index(
            "ix_wallet_transactions_identity_tuple",
            "transaction_network",
            "transaction_account_canonical",
            "transaction_logical_time_canonical",
            "transaction_hash_canonical",
        ),
    )

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
    transaction_identity_status = Column(
        String(20),
        nullable=False,
        default="unavailable",
        server_default="unavailable",
    )
    transaction_identity_version = Column(
        String(24),
        nullable=False,
        default="unavailable",
        server_default="unavailable",
    )
    transaction_network = Column(
        String(16),
        nullable=False,
        default="ton-unknown",
        server_default="ton-unknown",
    )
    transaction_account_canonical = Column(String(76), nullable=True)
    transaction_logical_time_canonical = Column(String(20), nullable=True)
    transaction_hash_canonical = Column(String(64), nullable=True)
    transaction_identity_key = Column(String(192), nullable=True)

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
