"""Bind wallet ownership challenges to one TON network.

Revision ID: 20260710_0014
Revises: 20260710_0013
"""

from alembic import op
import sqlalchemy as sa


revision = "20260710_0014"
down_revision = "20260710_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Ownership network migration requires online validation.")
    connection = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(connection).get_columns(
            "wallet_ownership_challenges"
        )
    }
    if "expected_network" in columns:
        raise RuntimeError("Revision 0014 refuses a pre-existing network column.")
    op.add_column(
        "wallet_ownership_challenges",
        sa.Column(
            "expected_network",
            sa.String(16),
            nullable=False,
            server_default="ton-unknown",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Ownership network downgrade would weaken challenge scope.")
