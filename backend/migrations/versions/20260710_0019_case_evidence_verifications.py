"""Add durable Wallet Case evidence-verification jobs.

Revision ID: 20260710_0019
Revises: 20260710_0018
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0019"
down_revision = "20260710_0018"
branch_labels = None
depends_on = None


_TABLE = "wallet_case_evidence_verifications"
_REQUIRED_TABLES = {
    "wallet_cases",
    "wallet_case_syncs",
    "wallet_transactions",
    "wallet_trace_evidence_captures",
    "wallet_trace_boc_verifications",
    "wallet_native_activity_ledgers",
}
_INDEXES = (
    ("uq_wallet_case_evidence_public_id", ("public_id",), True, None),
    (
        "uq_wallet_case_evidence_idempotency",
        ("case_id", "idempotency_key"),
        True,
        None,
    ),
    (
        "uq_wallet_case_evidence_active_selection",
        ("case_id", "snapshot_sync_id", "activity_public_id", "policy"),
        True,
        "state IN ('queued', 'running')",
    ),
    (
        "ix_wallet_case_evidence_catalog",
        ("case_id", "snapshot_sync_id", "created_at", "id"),
        False,
        None,
    ),
    (
        "ix_wallet_case_evidence_queue",
        ("state", "next_attempt_at", "created_at", "id"),
        False,
        None,
    ),
    (
        "ix_wallet_case_evidence_source_transaction",
        ("source_transaction_id", "state"),
        False,
        None,
    ),
)


def _columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_sync_id", sa.Integer(), nullable=False),
        sa.Column("source_sync_id", sa.Integer(), nullable=False),
        sa.Column("source_transaction_id", sa.Integer(), nullable=False),
        sa.Column("activity_public_id", sa.String(68), nullable=False),
        sa.Column("activity_semantic_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "policy",
            sa.String(40),
            nullable=False,
            server_default="transaction_inclusion_v1",
        ),
        sa.Column("state", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(32), nullable=False, server_default="queued"),
        sa.Column(
            "progress_current", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "status_version", sa.Integer(), nullable=False, server_default=sa.text("1")
        ),
        sa.Column(
            "highest_evidence_level",
            sa.String(24),
            nullable=False,
            server_default="normalized",
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("wallet_account_canonical", sa.String(76), nullable=False),
        sa.Column("transaction_hash", sa.String(64), nullable=False),
        sa.Column("transaction_logical_time", sa.String(20), nullable=False),
        sa.Column("idempotency_key", sa.String(36), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column(
            "max_attempts", sa.Integer(), nullable=False, server_default=sa.text("4")
        ),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("lease_token", sa.String(64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column("checkpoint_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("trace_capture_id", sa.Integer(), nullable=True),
        sa.Column("trace_digest_sha256", sa.String(64), nullable=True),
        sa.Column("trace_completed_at", sa.DateTime(), nullable=True),
        sa.Column("boc_verification_id", sa.Integer(), nullable=True),
        sa.Column("boc_digest_sha256", sa.String(64), nullable=True),
        sa.Column("boc_completed_at", sa.DateTime(), nullable=True),
        sa.Column("inclusion_catalog_digest_sha256", sa.String(64), nullable=True),
        sa.Column("inclusion_completed_at", sa.DateTime(), nullable=True),
        sa.Column("native_ledger_id", sa.Integer(), nullable=True),
        sa.Column("native_ledger_digest_sha256", sa.String(64), nullable=True),
        sa.Column("native_ledger_completed_at", sa.DateTime(), nullable=True),
        sa.Column("result_digest_sha256", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("error_detail_safe", sa.Text(), nullable=True),
        sa.Column("message_safe", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )


def _checks() -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "policy = 'transaction_inclusion_v1'",
            name="ck_wallet_case_evidence_policy",
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'partial', 'succeeded', 'failed', 'cancelled')",
            name="ck_wallet_case_evidence_state",
        ),
        sa.CheckConstraint(
            "stage IN ('queued', 'validating', 'capturing_trace', 'verifying_bocs', "
            "'proving_inclusion', 'building_native_ledger', 'finalizing', "
            "'retry_wait', 'terminal')",
            name="ck_wallet_case_evidence_stage",
        ),
        sa.CheckConstraint(
            "highest_evidence_level IN ('normalized', 'locally_verified', "
            "'chain_inclusion_proven')",
            name="ck_wallet_case_evidence_level",
        ),
        sa.CheckConstraint(
            "progress_current >= 0 AND progress_current <= 4",
            name="ck_wallet_case_evidence_progress",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts >= 1 AND attempt_count <= max_attempts",
            name="ck_wallet_case_evidence_attempts",
        ),
        sa.CheckConstraint(
            "(state != 'failed' OR progress_current = 0) AND "
            "(state != 'partial' OR progress_current > 0) AND "
            "(state != 'succeeded' OR progress_current = 4)",
            name="ck_wallet_case_evidence_state_progress",
        ),
        sa.CheckConstraint(
            "(state = 'cancelled' AND cancel_requested_at IS NOT NULL) OR "
            "(state = 'running') OR "
            "(state IN ('queued', 'partial', 'succeeded', 'failed') AND "
            "cancel_requested_at IS NULL)",
            name="ck_wallet_case_evidence_cancel_state",
        ),
        sa.CheckConstraint(
            "(state = 'queued' AND stage IN ('queued', 'retry_wait') AND "
            "next_attempt_at IS NOT NULL AND lease_token IS NULL AND "
            "lease_expires_at IS NULL AND completed_at IS NULL) OR "
            "(state = 'running' AND stage IN ('validating', 'capturing_trace', "
            "'verifying_bocs', 'proving_inclusion', 'building_native_ledger', "
            "'finalizing') AND "
            "next_attempt_at IS NULL AND lease_token IS NOT NULL AND "
            "lease_expires_at IS NOT NULL AND started_at IS NOT NULL AND "
            "completed_at IS NULL) OR "
            "(state IN ('partial', 'succeeded', 'failed', 'cancelled') AND "
            "stage = 'terminal' AND next_attempt_at IS NULL AND "
            "lease_token IS NULL AND lease_expires_at IS NULL AND "
            "completed_at IS NOT NULL)",
            name="ck_wallet_case_evidence_lifecycle",
        ),
        sa.CheckConstraint(
            "(progress_current = 0 AND trace_capture_id IS NULL AND "
            "trace_digest_sha256 IS NULL AND trace_completed_at IS NULL AND "
            "boc_verification_id IS NULL AND boc_digest_sha256 IS NULL AND "
            "boc_completed_at IS NULL AND inclusion_catalog_digest_sha256 IS NULL AND "
            "inclusion_completed_at IS NULL AND native_ledger_id IS NULL AND "
            "native_ledger_digest_sha256 IS NULL AND native_ledger_completed_at IS NULL "
            "AND highest_evidence_level = 'normalized') OR "
            "(progress_current = 1 AND trace_capture_id IS NOT NULL AND "
            "trace_digest_sha256 IS NOT NULL AND trace_completed_at IS NOT NULL AND "
            "boc_verification_id IS NULL AND boc_digest_sha256 IS NULL AND "
            "boc_completed_at IS NULL AND inclusion_catalog_digest_sha256 IS NULL AND "
            "inclusion_completed_at IS NULL AND native_ledger_id IS NULL AND "
            "native_ledger_digest_sha256 IS NULL AND native_ledger_completed_at IS NULL "
            "AND highest_evidence_level = 'normalized') OR "
            "(progress_current = 2 AND trace_capture_id IS NOT NULL AND "
            "trace_digest_sha256 IS NOT NULL AND trace_completed_at IS NOT NULL AND "
            "boc_verification_id IS NOT NULL AND boc_digest_sha256 IS NOT NULL AND "
            "boc_completed_at IS NOT NULL AND inclusion_catalog_digest_sha256 IS NULL AND "
            "inclusion_completed_at IS NULL AND native_ledger_id IS NULL AND "
            "native_ledger_digest_sha256 IS NULL AND native_ledger_completed_at IS NULL "
            "AND highest_evidence_level = 'locally_verified') OR "
            "(progress_current = 3 AND trace_capture_id IS NOT NULL AND "
            "trace_digest_sha256 IS NOT NULL AND trace_completed_at IS NOT NULL AND "
            "boc_verification_id IS NOT NULL AND boc_digest_sha256 IS NOT NULL AND "
            "boc_completed_at IS NOT NULL AND inclusion_catalog_digest_sha256 IS NOT NULL AND "
            "inclusion_completed_at IS NOT NULL AND native_ledger_id IS NULL AND "
            "native_ledger_digest_sha256 IS NULL AND native_ledger_completed_at IS NULL "
            "AND highest_evidence_level = 'chain_inclusion_proven') OR "
            "(progress_current = 4 AND trace_capture_id IS NOT NULL AND "
            "trace_digest_sha256 IS NOT NULL AND trace_completed_at IS NOT NULL AND "
            "boc_verification_id IS NOT NULL AND boc_digest_sha256 IS NOT NULL AND "
            "boc_completed_at IS NOT NULL AND inclusion_catalog_digest_sha256 IS NOT NULL AND "
            "inclusion_completed_at IS NOT NULL AND native_ledger_id IS NOT NULL AND "
            "native_ledger_digest_sha256 IS NOT NULL AND native_ledger_completed_at IS NOT NULL "
            "AND highest_evidence_level = 'chain_inclusion_proven')",
            name="ck_wallet_case_evidence_artifact_prefix",
        ),
    )


def _create_table() -> None:
    op.create_table(
        _TABLE,
        *_columns(),
        *_checks(),
        sa.ForeignKeyConstraint(["case_id"], ["wallet_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["snapshot_sync_id"], ["wallet_case_syncs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_sync_id"], ["wallet_case_syncs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_transaction_id"], ["wallet_transactions.id"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["trace_capture_id"],
            ["wallet_trace_evidence_captures.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["boc_verification_id"],
            ["wallet_trace_boc_verifications.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["native_ledger_id"],
            ["wallet_native_activity_ledgers.id"],
            ondelete="RESTRICT",
        ),
    )


def _normalize(value: Any) -> str | None:
    return None if value is None else "".join(str(value).upper().split())


def _default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    value = column.server_default.arg
    if isinstance(value, str):
        return _normalize(repr(value))
    return _normalize(value.compile(compile_kwargs={"literal_binds": True}))


def _column_signature(column: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(column.get("name")),
        _normalize(column.get("type")),
        bool(column.get("nullable")),
        _normalize(column.get("default")),
        bool(column.get("primary_key")),
    )


def _expected_column_signature(column: sa.Column) -> tuple[Any, ...]:
    return (
        str(column.name),
        _normalize(column.type),
        bool(column.nullable),
        _default(column),
        bool(column.primary_key),
    )


def _validate_existing() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    actual = tuple(_column_signature(row) for row in inspector.get_columns(_TABLE))
    expected = tuple(_expected_column_signature(row) for row in _columns())
    if actual != expected:
        raise RuntimeError(
            "Existing Wallet Case evidence table does not match revision 0019."
        )
    actual_foreign_keys = {
        (
            tuple(item.get("constrained_columns") or ()),
            item.get("referred_table"),
            tuple(item.get("referred_columns") or ()),
            (item.get("options") or {}).get("ondelete"),
        )
        for item in inspector.get_foreign_keys(_TABLE)
    }
    expected_foreign_keys = {
        (("case_id",), "wallet_cases", ("id",), "CASCADE"),
        (("snapshot_sync_id",), "wallet_case_syncs", ("id",), "CASCADE"),
        (("source_sync_id",), "wallet_case_syncs", ("id",), "CASCADE"),
        (("source_transaction_id",), "wallet_transactions", ("id",), "RESTRICT"),
        (
            ("trace_capture_id",),
            "wallet_trace_evidence_captures",
            ("id",),
            "RESTRICT",
        ),
        (
            ("boc_verification_id",),
            "wallet_trace_boc_verifications",
            ("id",),
            "RESTRICT",
        ),
        (
            ("native_ledger_id",),
            "wallet_native_activity_ledgers",
            ("id",),
            "RESTRICT",
        ),
    }
    if actual_foreign_keys != expected_foreign_keys:
        raise RuntimeError(
            "Existing Wallet Case evidence foreign keys do not match revision 0019."
        )
    actual_checks = {
        (
            str(item.get("name")),
            " ".join(str(item.get("sqltext")).split()),
        )
        for item in inspector.get_check_constraints(_TABLE)
    }
    expected_checks = {
        (
            str(item.name),
            " ".join(str(item.sqltext).split()),
        )
        for item in _checks()
    }
    if actual_checks != expected_checks:
        raise RuntimeError(
            "Existing Wallet Case evidence checks do not match revision 0019."
        )
    if int(
        bind.execute(sa.text(f'SELECT COUNT(*) FROM "{_TABLE}"')).scalar_one()
    ) != 0:
        raise RuntimeError(
            "Pre-revision Wallet Case evidence rows cannot be adopted by revision 0019."
        )


def _index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    where = (index.get("dialect_options") or {}).get("sqlite_where")
    return (
        tuple(index.get("column_names") or ()),
        bool(index.get("unique")),
        " ".join(str(where).split()) if where is not None else None,
    )


def _ensure_indexes() -> None:
    for name, columns, unique, where in _INDEXES:
        indexes = {
            str(item["name"]): item
            for item in sa.inspect(op.get_bind()).get_indexes(_TABLE)
        }
        existing = indexes.get(name)
        expected = (columns, unique, where)
        if existing is None:
            options = {"sqlite_where": sa.text(where)} if where else {}
            op.create_index(name, _TABLE, list(columns), unique=unique, **options)
        elif _index_signature(existing) != expected:
            raise RuntimeError(f"Existing index {name} does not match revision 0019.")


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case evidence schema validation requires an online database."
        )
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    missing = sorted(_REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError(f"Revision 0019 requires evidence source tables: {missing}.")
    if _TABLE not in tables:
        _create_table()
    else:
        _validate_existing()
    _ensure_indexes()
    _validate_existing()


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case evidence downgrade would discard durable proof-job provenance "
        "and is intentionally unsupported. Restore a verified backup instead."
    )
