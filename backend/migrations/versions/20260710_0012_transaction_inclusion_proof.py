"""Persist transaction BOC inclusion proofs.

Revision ID: 20260710_0012
Revises: 20260710_0011
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0012"
down_revision = "20260710_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Transaction inclusion migration requires online validation.")
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    table = "wallet_transaction_inclusion_proofs"
    if table in tables:
        raise RuntimeError("Revision 0012 refuses a pre-existing inclusion table.")
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "boc_transaction_id",
            sa.Integer(),
            sa.ForeignKey("wallet_trace_boc_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("network", sa.String(16), nullable=False),
        sa.Column("trust_level", sa.Integer(), nullable=False),
        sa.Column("account_address_canonical", sa.String(76), nullable=False),
        sa.Column("logical_time", sa.String(20), nullable=False),
        sa.Column("transaction_hash", sa.String(64), nullable=False),
        sa.Column("block_workchain", sa.Integer(), nullable=False),
        sa.Column("block_shard", sa.String(24), nullable=False),
        sa.Column("block_seqno", sa.Integer(), nullable=False),
        sa.Column("block_root_hash", sa.String(64), nullable=False),
        sa.Column("block_file_hash", sa.String(64), nullable=False),
        sa.Column("anchor_workchain", sa.Integer(), nullable=False),
        sa.Column("anchor_shard", sa.String(24), nullable=False),
        sa.Column("anchor_seqno", sa.Integer(), nullable=False),
        sa.Column("anchor_root_hash", sa.String(64), nullable=False),
        sa.Column("anchor_file_hash", sa.String(64), nullable=False),
        sa.Column("block_proof_boc_hex", sa.Text(), nullable=False),
        sa.Column("transaction_boc_sha256", sa.String(64), nullable=False),
        sa.Column("block_proof_boc_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_digest_sha256", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_wallet_transaction_inclusion_boc_transaction",
        table,
        ["boc_transaction_id"],
        unique=True,
    )
    op.create_index(
        "ix_wallet_transaction_inclusion_digest",
        table,
        ["evidence_digest_sha256"],
    )


def downgrade() -> None:
    raise RuntimeError("Transaction inclusion downgrade would discard proof evidence.")
