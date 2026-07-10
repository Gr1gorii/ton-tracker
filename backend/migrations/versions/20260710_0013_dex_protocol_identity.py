"""Add canonical multi-protocol DEX identities to swap observations.

Revision ID: 20260710_0013
Revises: 20260710_0012
"""

import re

from alembic import op
import sqlalchemy as sa


revision = "20260710_0013"
down_revision = "20260710_0012"
branch_labels = None
depends_on = None


_ALIASES = {
    "stonfi": "stonfi_v1",
    "stonfiv1": "stonfi_v1",
    "stonfiv2": "stonfi_v2",
    "dedust": "dedust",
    "dedustv2": "dedust",
    "dedustv3": "dedust_v3",
    "dedustv3memepad": "dedust_v3_memepad",
    "tonco": "tonco",
    "memeslab": "memeslab",
    "tonfun": "tonfun",
}


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("DEX protocol migration requires online validation.")
    connection = op.get_bind()
    columns = {column["name"] for column in sa.inspect(connection).get_columns("wallet_swaps")}
    if {"dex_protocol_id", "dex_protocol_status"} & columns:
        raise RuntimeError("Revision 0013 refuses partial DEX protocol columns.")
    op.add_column("wallet_swaps", sa.Column("dex_protocol_id", sa.String(32)))
    op.add_column("wallet_swaps", sa.Column("dex_protocol_status", sa.String(16)))
    rows = connection.exec_driver_sql("SELECT id, dex FROM wallet_swaps").fetchall()
    for row_id, label in rows:
        cleaned = str(label).strip() if label is not None else ""
        key = re.sub(r"[^a-z0-9]", "", cleaned.lower())
        protocol_id = _ALIASES.get(key)
        status = "recognized" if protocol_id else ("unknown" if cleaned else "missing")
        connection.execute(
            sa.text(
                "UPDATE wallet_swaps SET dex_protocol_id=:protocol_id, "
                "dex_protocol_status=:status WHERE id=:row_id"
            ),
            {"protocol_id": protocol_id, "status": status, "row_id": row_id},
        )


def downgrade() -> None:
    raise RuntimeError("DEX protocol downgrade would discard normalized identities.")
