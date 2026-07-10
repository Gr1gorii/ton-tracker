"""Add immutable native TON activity ledger.

Revision ID: 20260710_0008
Revises: 20260710_0007
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0008"
down_revision = "20260710_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Native activity ledger migration requires online validation.")
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    required = {
        "wallet_trace_evidence_captures",
        "wallet_trace_boc_verifications",
        "wallet_trace_boc_transactions",
    }
    missing = sorted(required - tables)
    if missing:
        raise RuntimeError(f"Revision 0008 requires exact revision 0007 tables; missing={missing}.")
    ledger_table = "wallet_native_activity_ledgers"
    rows_table = "wallet_native_activity_rows"
    existing = tables & {ledger_table, rows_table}
    if existing:
        raise RuntimeError(
            "Revision 0008 refuses pre-existing native activity ledger fragments; "
            f"existing={sorted(existing)}."
        )
    op.create_table(
        ledger_table,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("capture_id", sa.Integer(), sa.ForeignKey("wallet_trace_evidence_captures.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contract_version", sa.String(48), nullable=False),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("wallet_account_canonical", sa.String(76), nullable=False),
        sa.Column("source_message_evidence_digest_sha256", sa.String(64), nullable=False),
        sa.Column("activity_count", sa.Integer(), nullable=False),
        sa.Column("incoming_nanoton", sa.String(32), nullable=False),
        sa.Column("outgoing_nanoton", sa.String(32), nullable=False),
        sa.Column("self_nanoton", sa.String(32), nullable=False),
        sa.Column("evidence_digest_sha256", sa.String(64), nullable=False),
        sa.Column("built_at", sa.DateTime(), nullable=False),
    )
    op.create_index("uq_wallet_native_activity_ledgers_capture_contract", ledger_table, ["capture_id", "contract_version"], unique=True)
    op.create_index("ix_wallet_native_activity_ledgers_digest", ledger_table, ["evidence_digest_sha256"])
    op.create_table(
        rows_table,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("ledger_id", sa.Integer(), sa.ForeignKey(f"{ledger_table}.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("activity_identity_key", sa.String(64), nullable=False),
        sa.Column("source_flow_observation_identity", sa.String(64), nullable=False),
        sa.Column("transaction_hash", sa.String(64), nullable=False),
        sa.Column("message_hash", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(12), nullable=False),
        sa.Column("activity_kind", sa.String(32), nullable=False),
        sa.Column("asset_identity_key", sa.String(96), nullable=False),
        sa.Column("counterparty_identity_key", sa.String(180), nullable=False),
        sa.Column("counterparty_account_canonical", sa.String(76), nullable=False),
        sa.Column("amount_base_units", sa.String(32), nullable=False),
        sa.Column("created_logical_time", sa.String(20), nullable=False),
        sa.Column("unix_time", sa.Integer(), nullable=False),
        sa.Column("body_hash", sa.String(64), nullable=False),
        sa.Column("opcode_hex", sa.String(10), nullable=True),
        sa.Column("bounce", sa.Boolean(), nullable=False),
        sa.Column("bounced", sa.Boolean(), nullable=False),
    )
    op.create_index("uq_wallet_native_activity_rows_ledger_identity", rows_table, ["ledger_id", "activity_identity_key"], unique=True)
    op.create_index("uq_wallet_native_activity_rows_ledger_message", rows_table, ["ledger_id", "message_hash"], unique=True)
    op.create_index("ix_wallet_native_activity_rows_identity", rows_table, ["activity_identity_key"])
    op.create_index("ix_wallet_native_activity_rows_counterparty", rows_table, ["counterparty_identity_key"])


def downgrade() -> None:
    raise RuntimeError("Native activity ledger downgrade would discard immutable semantic evidence.")
