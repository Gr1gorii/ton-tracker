"""Version transaction inclusion proofs by liteserver trust level.

Revision ID: 20260710_0020
Revises: 20260710_0019
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0020"
down_revision = "20260710_0019"
branch_labels = None
depends_on = None


_TABLE = "wallet_transaction_inclusion_proofs"
_OLD_INDEX = "uq_wallet_transaction_inclusion_boc_transaction"
_NEW_INDEX = "uq_wallet_transaction_inclusion_boc_transaction_trust"
_DIGEST_INDEX = "ix_wallet_transaction_inclusion_digest"
_EXPECTED_COLUMNS = (
    ("id", "INTEGER", False, None, True),
    ("boc_transaction_id", "INTEGER", False, None, False),
    ("network", "VARCHAR(16)", False, None, False),
    ("trust_level", "INTEGER", False, None, False),
    ("account_address_canonical", "VARCHAR(76)", False, None, False),
    ("logical_time", "VARCHAR(20)", False, None, False),
    ("transaction_hash", "VARCHAR(64)", False, None, False),
    ("block_workchain", "INTEGER", False, None, False),
    ("block_shard", "VARCHAR(24)", False, None, False),
    ("block_seqno", "INTEGER", False, None, False),
    ("block_root_hash", "VARCHAR(64)", False, None, False),
    ("block_file_hash", "VARCHAR(64)", False, None, False),
    ("anchor_workchain", "INTEGER", False, None, False),
    ("anchor_shard", "VARCHAR(24)", False, None, False),
    ("anchor_seqno", "INTEGER", False, None, False),
    ("anchor_root_hash", "VARCHAR(64)", False, None, False),
    ("anchor_file_hash", "VARCHAR(64)", False, None, False),
    ("block_proof_boc_hex", "TEXT", False, None, False),
    ("transaction_boc_sha256", "VARCHAR(64)", False, None, False),
    ("block_proof_boc_sha256", "VARCHAR(64)", False, None, False),
    ("evidence_digest_sha256", "VARCHAR(64)", False, None, False),
    ("verified_at", "DATETIME", False, None, False),
)


def _normalize(value: Any) -> str | None:
    return None if value is None else "".join(str(value).upper().split())


def _column_signature(column: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(column.get("name")),
        _normalize(column.get("type")),
        bool(column.get("nullable")),
        _normalize(column.get("default")),
        bool(column.get("primary_key")),
    )


def _index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    where = (index.get("dialect_options") or {}).get("sqlite_where")
    return (
        tuple(index.get("column_names") or ()),
        bool(index.get("unique")),
        None if where is None else " ".join(str(where).split()),
    )


def _validate_table() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    actual_columns = tuple(
        _column_signature(column) for column in inspector.get_columns(_TABLE)
    )
    if actual_columns != _EXPECTED_COLUMNS:
        raise RuntimeError(
            "Transaction inclusion proof columns do not match revision 0020."
        )
    foreign_keys = {
        (
            tuple(item.get("constrained_columns") or ()),
            item.get("referred_table"),
            tuple(item.get("referred_columns") or ()),
            (item.get("options") or {}).get("ondelete"),
        )
        for item in inspector.get_foreign_keys(_TABLE)
    }
    if foreign_keys != {
        (
            ("boc_transaction_id",),
            "wallet_trace_boc_transactions",
            ("id",),
            "CASCADE",
        )
    }:
        raise RuntimeError(
            "Transaction inclusion proof foreign key does not match revision 0020."
        )
    invalid_trust_levels = bind.execute(
        sa.text(
            f'SELECT COUNT(*) FROM "{_TABLE}" '
            "WHERE trust_level NOT IN (0, 1)"
        )
    ).scalar_one()
    if int(invalid_trust_levels) != 0:
        raise RuntimeError(
            "Transaction inclusion proof trust levels are unsupported by revision 0020."
        )
    duplicate_versions = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM ("
            f'SELECT boc_transaction_id, trust_level FROM "{_TABLE}" '
            "GROUP BY boc_transaction_id, trust_level HAVING COUNT(*) > 1"
            ")"
        )
    ).scalar_one()
    if int(duplicate_versions) != 0:
        raise RuntimeError(
            "Transaction inclusion proof trust identities are duplicated."
        )


def _validated_indexes(*, transition: bool) -> dict[str, dict[str, Any]]:
    indexes = {
        str(item["name"]): item
        for item in sa.inspect(op.get_bind()).get_indexes(_TABLE)
    }
    allowed_names = {_DIGEST_INDEX, _OLD_INDEX, _NEW_INDEX}
    if set(indexes) - allowed_names:
        raise RuntimeError(
            "Transaction inclusion proof indexes do not match revision 0020."
        )
    expected = {
        _DIGEST_INDEX: (("evidence_digest_sha256",), False, None),
        _OLD_INDEX: (("boc_transaction_id",), True, None),
        _NEW_INDEX: (("boc_transaction_id", "trust_level"), True, None),
    }
    for name, index in indexes.items():
        if _index_signature(index) != expected[name]:
            raise RuntimeError(
                f"Existing transaction inclusion index {name} does not match revision 0020."
            )
    if _DIGEST_INDEX not in indexes:
        raise RuntimeError(
            "Transaction inclusion digest index is missing before revision 0020."
        )
    if transition:
        if _OLD_INDEX not in indexes and _NEW_INDEX not in indexes:
            raise RuntimeError(
                "Transaction inclusion trust index has no resumable revision 0020 state."
            )
    elif set(indexes) != {_DIGEST_INDEX, _NEW_INDEX}:
        raise RuntimeError(
            "Transaction inclusion proof indexes did not reach revision 0020."
        )
    return indexes


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Transaction inclusion trust migration requires online validation."
        )
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _TABLE not in tables:
        raise RuntimeError(
            "Revision 0020 requires the transaction inclusion proof table."
        )
    _validate_table()
    indexes = _validated_indexes(transition=True)
    # Create the relaxed versioned uniqueness first. This keeps every crash
    # point restartable without opening an unindexed write window.
    if _NEW_INDEX not in indexes:
        op.create_index(
            _NEW_INDEX,
            _TABLE,
            ["boc_transaction_id", "trust_level"],
            unique=True,
        )
    indexes = _validated_indexes(transition=True)
    if _OLD_INDEX in indexes:
        op.drop_index(_OLD_INDEX, table_name=_TABLE)
    _validate_table()
    _validated_indexes(transition=False)


def downgrade() -> None:
    raise RuntimeError(
        "Transaction inclusion trust downgrade could discard immutable proof "
        "versions and is intentionally unsupported."
    )
