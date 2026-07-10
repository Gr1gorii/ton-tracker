"""Add replay-safe TON wallet ownership challenges.

Revision ID: 20260710_0010
Revises: 20260710_0009
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0010"
down_revision = "20260710_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Ownership challenge migration requires online validation.")
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    table = "wallet_ownership_challenges"
    if table in tables:
        raise RuntimeError("Revision 0010 refuses a pre-existing ownership table.")
    op.create_table(
        table,
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("challenge_id", sa.String(36), nullable=False),
        sa.Column("payload", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("expected_wallet_account_canonical", sa.String(76), nullable=True),
        sa.Column("expected_domain", sa.String(255), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("consumed_at", sa.DateTime(), nullable=True),
        sa.Column("verified_wallet_account_canonical", sa.String(76), nullable=True),
        sa.Column("signature_digest_sha256", sa.String(64), nullable=True),
    )
    op.create_index("uq_wallet_ownership_challenge_id", table, ["challenge_id"], unique=True)
    op.create_index("uq_wallet_ownership_payload_hash", table, ["payload_hash"], unique=True)
    op.create_index("ix_wallet_ownership_challenge_expiry", table, ["expires_at"])


def downgrade() -> None:
    raise RuntimeError("Ownership challenge downgrade would discard proof evidence.")
