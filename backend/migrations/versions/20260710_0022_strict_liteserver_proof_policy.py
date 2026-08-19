"""Separate strict liteserver proof-chain policy from legacy checkpoint rows.

Revision ID: 20260710_0022
Revises: 20260710_0021
Create Date: 2026-08-11
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0022"
down_revision = "20260710_0021"
branch_labels = None
depends_on = None


_TABLE = "wallet_transaction_inclusion_proofs"
_INDEX = "uq_wallet_transaction_inclusion_boc_transaction_trust_policy"
_DIGEST_INDEX = "ix_wallet_transaction_inclusion_digest"
_LEGACY_UNPINNED_POLICY = "legacy_unpinned_v1"
_LEGACY_CHECKPOINT_POLICY = "ton_liteserver_checkpoint_2026_08_v1"
_CURRENT_POLICY = "ton_liteserver_checkpoint_strict_2026_08_v2"
_INSERT_TRIGGER = "ck_wallet_transaction_inclusion_checkpoint_insert"
_UPDATE_TRIGGER = "ck_wallet_transaction_inclusion_checkpoint_update"
_CHECKPOINT_COLUMNS = (
    "trusted_checkpoint_workchain",
    "trusted_checkpoint_shard",
    "trusted_checkpoint_seqno",
    "trusted_checkpoint_root_hash",
    "trusted_checkpoint_file_hash",
)


def _normalize_sql(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).rstrip(";")


def _checkpoint_mismatch(prefix: str) -> str:
    return (
        f"{prefix}.trusted_checkpoint_workchain IS NULL OR "
        f"{prefix}.trusted_checkpoint_shard IS NULL OR "
        f"{prefix}.trusted_checkpoint_seqno IS NULL OR "
        f"{prefix}.trusted_checkpoint_root_hash IS NULL OR "
        f"{prefix}.trusted_checkpoint_file_hash IS NULL OR NOT ("
        f"({prefix}.network = 'ton-mainnet' AND "
        f"{prefix}.trusted_checkpoint_workchain = -1 AND "
        f"{prefix}.trusted_checkpoint_shard = '-9223372036854775808' AND "
        f"{prefix}.trusted_checkpoint_seqno = 46894135 AND "
        f"{prefix}.trusted_checkpoint_root_hash = "
        "'3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f' AND "
        f"{prefix}.trusted_checkpoint_file_hash = "
        "'bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed') OR "
        f"({prefix}.network = 'ton-testnet' AND "
        f"{prefix}.trusted_checkpoint_workchain = -1 AND "
        f"{prefix}.trusted_checkpoint_shard = '-9223372036854775808' AND "
        f"{prefix}.trusted_checkpoint_seqno = 58834988 AND "
        f"{prefix}.trusted_checkpoint_root_hash = "
        "'8c711614c06a513e026dd1456f2f01a3b5b412f5a99ff1b050e23e9b103231d9' AND "
        f"{prefix}.trusted_checkpoint_file_hash = "
        "'898c25a4599a33bea0b442e80ec3877461eaac824b497ebbbc670f7d077925d7'))"
    )


def _invalid_new_row(prefix: str = "NEW") -> str:
    null_checkpoint = " OR ".join(
        f"{prefix}.{column} IS NOT NULL" for column in _CHECKPOINT_COLUMNS
    )
    return (
        f"{prefix}.verifier_policy_id NOT IN ("
        f"'{_LEGACY_UNPINNED_POLICY}', '{_LEGACY_CHECKPOINT_POLICY}', "
        f"'{_CURRENT_POLICY}') OR "
        f"({prefix}.verifier_policy_id = '{_LEGACY_UNPINNED_POLICY}' AND "
        f"({null_checkpoint})) OR "
        f"({prefix}.verifier_policy_id IN ("
        f"'{_LEGACY_CHECKPOINT_POLICY}', '{_CURRENT_POLICY}') AND "
        f"({_checkpoint_mismatch(prefix)}))"
    )


def _trigger_sql(name: str, event: str) -> str:
    return (
        f'CREATE TRIGGER "{name}" BEFORE {event} ON "{_TABLE}" '
        f"FOR EACH ROW WHEN {_invalid_new_row()} BEGIN "
        "SELECT RAISE(ABORT, 'invalid transaction inclusion checkpoint provenance'); "
        "END"
    )


def _validate_base_schema() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        raise RuntimeError("Revision 0022 requires transaction inclusion proofs.")
    columns = {str(item["name"]) for item in inspector.get_columns(_TABLE)}
    required = {"verifier_policy_id", *_CHECKPOINT_COLUMNS}
    if not required.issubset(columns):
        raise RuntimeError("Revision 0022 requires the complete checkpoint schema.")
    indexes = {
        str(item["name"]): (
            tuple(item.get("column_names") or ()),
            bool(item.get("unique")),
        )
        for item in inspector.get_indexes(_TABLE)
    }
    if indexes.get(_INDEX) != (
        ("boc_transaction_id", "trust_level", "verifier_policy_id"),
        True,
    ) or indexes.get(_DIGEST_INDEX) != (("evidence_digest_sha256",), False):
        raise RuntimeError("Revision 0022 transaction inclusion indexes differ.")


def _validate_rows() -> None:
    invalid = op.get_bind().execute(sa.text(
        f'SELECT COUNT(*) FROM "{_TABLE}" WHERE '
        f'{_invalid_new_row().replace("NEW.", "")}'
    )).scalar_one()
    if int(invalid) != 0:
        raise RuntimeError(
            "Transaction inclusion proof policy cannot be adopted by revision 0022."
        )


def _ensure_triggers() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError("Revision 0022 strict proof policy requires SQLite.")
    previous = import_module(
        "migrations.versions.20260710_0021_transaction_inclusion_pinned_checkpoints"
    )
    rows = bind.execute(sa.text(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
        "AND tbl_name=:table"
    ), {"table": _TABLE}).all()
    existing = {str(name): str(sql) for name, sql in rows}
    expected = {
        _INSERT_TRIGGER: _trigger_sql(_INSERT_TRIGGER, "INSERT"),
        _UPDATE_TRIGGER: _trigger_sql(_UPDATE_TRIGGER, "UPDATE"),
    }
    previous_expected = {
        _INSERT_TRIGGER: previous._trigger_sql(_INSERT_TRIGGER, "INSERT"),
        _UPDATE_TRIGGER: previous._trigger_sql(_UPDATE_TRIGGER, "UPDATE"),
    }
    if set(existing) - set(expected):
        raise RuntimeError("Revision 0022 checkpoint trigger set differs.")
    for name, sql in existing.items():
        normalized = _normalize_sql(sql)
        if normalized not in {
            _normalize_sql(expected[name]),
            _normalize_sql(previous_expected[name]),
        }:
            raise RuntimeError(
                f"Revision 0022 checkpoint trigger {name} is not resumable."
            )
    for name, sql in tuple(existing.items()):
        if _normalize_sql(sql) != _normalize_sql(expected[name]):
            bind.exec_driver_sql(f'DROP TRIGGER "{name}"')
    remaining = {
        str(name)
        for name, in bind.execute(sa.text(
            "SELECT name FROM sqlite_master WHERE type='trigger' "
            "AND tbl_name=:table"
        ), {"table": _TABLE}).all()
    }
    for name, sql in expected.items():
        if name not in remaining:
            bind.exec_driver_sql(sql)
    final_rows = bind.execute(sa.text(
        "SELECT name, sql FROM sqlite_master WHERE type='trigger' "
        "AND tbl_name=:table"
    ), {"table": _TABLE}).all()
    final = {str(name): _normalize_sql(sql) for name, sql in final_rows}
    if final != {name: _normalize_sql(sql) for name, sql in expected.items()}:
        raise RuntimeError("Revision 0022 checkpoint triggers did not converge.")


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError("Revision 0022 requires online validation.")
    _validate_base_schema()
    _validate_rows()
    _ensure_triggers()
    _validate_rows()


def downgrade() -> None:
    raise RuntimeError(
        "Strict liteserver proof policy downgrade could relabel unsafe evidence "
        "and is intentionally unsupported."
    )
