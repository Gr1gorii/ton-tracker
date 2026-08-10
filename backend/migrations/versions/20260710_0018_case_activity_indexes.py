"""Add bounded-query indexes for the Wallet Case Activity facade.

Revision ID: 20260710_0018
Revises: 20260710_0017
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0018"
down_revision = "20260710_0017"
branch_labels = None
depends_on = None


_INDEXES = (
    (
        "wallet_case_syncs",
        "ix_wallet_case_syncs_case_activity",
        ("case_id", "state", "id", "ingestion_run_id"),
    ),
    (
        "wallet_transactions",
        "ix_wallet_transactions_run_timeline",
        ("run_id", "timestamp", "id"),
    ),
    (
        "wallet_transfers",
        "ix_wallet_transfers_run_timeline",
        ("run_id", "timestamp", "id"),
    ),
    (
        "wallet_swaps",
        "ix_wallet_swaps_run_timeline",
        ("run_id", "timestamp", "id"),
    ),
)


def _index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(index.get("column_names") or ()),
        bool(index.get("unique")),
    )


def _ensure_indexes() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    tables = set(inspector.get_table_names())
    required_tables = {table for table, _, _ in _INDEXES}
    missing_tables = sorted(required_tables - tables)
    if missing_tables:
        raise RuntimeError(
            "Revision 0018 requires Wallet Case activity source tables: "
            f"{missing_tables}."
        )

    for table, name, columns in _INDEXES:
        reflected = {
            str(index["name"]): index
            for index in sa.inspect(connection).get_indexes(table)
        }
        existing = reflected.get(name)
        if existing is None:
            op.create_index(name, table, list(columns), unique=False)
            continue
        actual = _index_signature(existing)
        expected = (columns, False)
        if actual != expected:
            raise RuntimeError(
                f"Existing index {name} does not match revision 0018: "
                f"expected={expected}, actual={actual}."
            )

    for table, name, _ in _INDEXES:
        reflected_names = {
            str(index["name"])
            for index in sa.inspect(connection).get_indexes(table)
        }
        if name not in reflected_names:
            raise RuntimeError(
                f"Wallet Case activity migration did not create index {name}."
            )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case activity index validation requires an online database."
        )
    _ensure_indexes()


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case activity index downgrade is intentionally unsupported. "
        "Restore a verified backup instead."
    )
