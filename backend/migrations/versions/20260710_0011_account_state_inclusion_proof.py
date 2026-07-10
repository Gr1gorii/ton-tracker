"""Persist provider-free account-state Merkle inclusion evidence.

Revision ID: 20260710_0011
Revises: 20260710_0010
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0011"
down_revision = "20260710_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Account inclusion migration requires online validation.")
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    table = "wallet_account_state_inclusion_proofs"
    if table in tables:
        raise RuntimeError("Revision 0011 refuses a pre-existing inclusion table.")
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "verification_id",
            sa.Integer(),
            sa.ForeignKey(
                "wallet_jetton_contract_verifications.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("account_role", sa.String(24), nullable=False),
        sa.Column("account_address_canonical", sa.String(76), nullable=False),
        sa.Column("shard_workchain", sa.Integer(), nullable=False),
        sa.Column("shard", sa.String(24), nullable=False),
        sa.Column("shard_seqno", sa.Integer(), nullable=False),
        sa.Column("shard_root_hash", sa.String(64), nullable=False),
        sa.Column("shard_file_hash", sa.String(64), nullable=False),
        sa.Column("state_boc_hex", sa.Text(), nullable=False),
        sa.Column("account_proof_boc_hex", sa.Text(), nullable=False),
        sa.Column("shard_proof_boc_hex", sa.Text(), nullable=False),
        sa.Column("state_boc_sha256", sa.String(64), nullable=False),
        sa.Column("account_proof_boc_sha256", sa.String(64), nullable=False),
        sa.Column("shard_proof_boc_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_digest_sha256", sa.String(64), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "uq_wallet_account_state_inclusion_role",
        table,
        ["verification_id", "account_role"],
        unique=True,
    )
    op.create_index(
        "ix_wallet_account_state_inclusion_digest",
        table,
        ["evidence_digest_sha256"],
    )


def downgrade() -> None:
    raise RuntimeError("Account inclusion downgrade would discard proof evidence.")
