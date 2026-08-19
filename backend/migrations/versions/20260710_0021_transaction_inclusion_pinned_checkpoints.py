"""Version transaction inclusion proofs by an application-owned checkpoint.

Revision ID: 20260710_0021
Revises: 20260710_0020
Create Date: 2026-08-11
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0021"
down_revision = "20260710_0020"
branch_labels = None
depends_on = None


_TABLE = "wallet_transaction_inclusion_proofs"
_OLD_INDEX = "uq_wallet_transaction_inclusion_boc_transaction_trust"
_NEW_INDEX = "uq_wallet_transaction_inclusion_boc_transaction_trust_policy"
_DIGEST_INDEX = "ix_wallet_transaction_inclusion_digest"
_LEGACY_POLICY = "legacy_unpinned_v1"
_CURRENT_POLICY = "ton_liteserver_checkpoint_2026_08_v1"
_INSERT_TRIGGER = "ck_wallet_transaction_inclusion_checkpoint_insert"
_UPDATE_TRIGGER = "ck_wallet_transaction_inclusion_checkpoint_update"
_ADDITIONS = (
    ("verifier_policy_id", "VARCHAR(64)", False, "'legacy_unpinned_v1'"),
    ("trusted_checkpoint_workchain", "INTEGER", True, None),
    ("trusted_checkpoint_shard", "VARCHAR(24)", True, None),
    ("trusted_checkpoint_seqno", "INTEGER", True, None),
    ("trusted_checkpoint_root_hash", "VARCHAR(64)", True, None),
    ("trusted_checkpoint_file_hash", "VARCHAR(64)", True, None),
)


def _normalize(value: Any) -> str | None:
    return None if value is None else "".join(str(value).upper().split())


def _index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    where = (index.get("dialect_options") or {}).get("sqlite_where")
    return (
        tuple(index.get("column_names") or ()),
        bool(index.get("unique")),
        None if where is None else " ".join(str(where).split()),
    )


def _validate_column_prefix() -> int:
    columns = sa.inspect(op.get_bind()).get_columns(_TABLE)
    names = [str(item["name"]) for item in columns]
    expected_names = [name for name, *_ in _ADDITIONS]
    actual = [name for name in expected_names if name in names]
    if actual != expected_names[: len(actual)]:
        raise RuntimeError(
            "Transaction inclusion checkpoint columns have no resumable revision 0021 prefix."
        )
    for name, expected_type, nullable, default in _ADDITIONS[: len(actual)]:
        column = next(item for item in columns if item["name"] == name)
        signature = (
            _normalize(column.get("type")),
            bool(column.get("nullable")),
            _normalize(column.get("default")),
        )
        expected = (_normalize(expected_type), nullable, _normalize(default))
        if signature != expected:
            raise RuntimeError(
                f"Transaction inclusion checkpoint column {name} does not match revision 0021."
            )
    return len(actual)


def _add_remaining_columns(prefix: int) -> None:
    for name, _type, nullable, default in _ADDITIONS[prefix:]:
        if name == "verifier_policy_id":
            column = sa.Column(
                name,
                sa.String(64),
                nullable=False,
                server_default=_LEGACY_POLICY,
            )
        elif name in {"trusted_checkpoint_workchain", "trusted_checkpoint_seqno"}:
            column = sa.Column(name, sa.Integer(), nullable=nullable)
        else:
            length = 24 if name == "trusted_checkpoint_shard" else 64
            column = sa.Column(name, sa.String(length), nullable=nullable)
        op.add_column(_TABLE, column)


def _validate_rows() -> None:
    bind = op.get_bind()
    condition = _invalid_new_row().replace("NEW.", "")
    invalid = bind.execute(sa.text(
        f'SELECT COUNT(*) FROM "{_TABLE}" WHERE {condition}'
    )).scalar_one()
    if int(invalid) != 0:
        raise RuntimeError(
            "Transaction inclusion checkpoint provenance does not match revision 0021."
        )


def _invalid_new_row(prefix: str = "NEW") -> str:
    return (
        f"{prefix}.verifier_policy_id NOT IN ('{_LEGACY_POLICY}', '{_CURRENT_POLICY}') OR "
        f"({prefix}.verifier_policy_id = '{_LEGACY_POLICY}' AND ("
        f"{prefix}.trusted_checkpoint_workchain IS NOT NULL OR "
        f"{prefix}.trusted_checkpoint_shard IS NOT NULL OR "
        f"{prefix}.trusted_checkpoint_seqno IS NOT NULL OR "
        f"{prefix}.trusted_checkpoint_root_hash IS NOT NULL OR "
        f"{prefix}.trusted_checkpoint_file_hash IS NOT NULL)) OR "
        f"({prefix}.verifier_policy_id = '{_CURRENT_POLICY}' AND ("
        f"{prefix}.trusted_checkpoint_workchain IS NULL OR "
        f"{prefix}.trusted_checkpoint_shard IS NULL OR "
        f"{prefix}.trusted_checkpoint_seqno IS NULL OR "
        f"{prefix}.trusted_checkpoint_root_hash IS NULL OR "
        f"{prefix}.trusted_checkpoint_file_hash IS NULL OR NOT ("
        f"({prefix}.network = 'ton-mainnet' AND "
        f"{prefix}.trusted_checkpoint_workchain = -1 AND "
        f"{prefix}.trusted_checkpoint_shard = '-9223372036854775808' AND "
        f"{prefix}.trusted_checkpoint_seqno = 46894135 AND "
        f"{prefix}.trusted_checkpoint_root_hash = '3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f' AND "
        f"{prefix}.trusted_checkpoint_file_hash = 'bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed') OR "
        f"({prefix}.network = 'ton-testnet' AND "
        f"{prefix}.trusted_checkpoint_workchain = -1 AND "
        f"{prefix}.trusted_checkpoint_shard = '-9223372036854775808' AND "
        f"{prefix}.trusted_checkpoint_seqno = 58834988 AND "
        f"{prefix}.trusted_checkpoint_root_hash = '8c711614c06a513e026dd1456f2f01a3b5b412f5a99ff1b050e23e9b103231d9' AND "
        f"{prefix}.trusted_checkpoint_file_hash = '898c25a4599a33bea0b442e80ec3877461eaac824b497ebbbc670f7d077925d7'))))"
    )


def _trigger_sql(name: str, event: str) -> str:
    return (
        f'CREATE TRIGGER "{name}" BEFORE {event} ON "{_TABLE}" '
        f"FOR EACH ROW WHEN {_invalid_new_row()} BEGIN "
        "SELECT RAISE(ABORT, 'invalid transaction inclusion checkpoint provenance'); "
        "END"
    )


def _normalize_sql(value: Any) -> str:
    return " ".join(str(value or "").replace("\n", " ").split()).rstrip(";")


def _ensure_triggers() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        raise RuntimeError(
            "Revision 0021 checkpoint provenance enforcement requires SQLite."
        )
    rows = bind.execute(sa.text(
        "SELECT name, sql FROM sqlite_master WHERE type = 'trigger' "
        "AND tbl_name = :table"
    ), {"table": _TABLE}).all()
    existing = {str(name): str(sql) for name, sql in rows}
    expected = {
        _INSERT_TRIGGER: _trigger_sql(_INSERT_TRIGGER, "INSERT"),
        _UPDATE_TRIGGER: _trigger_sql(_UPDATE_TRIGGER, "UPDATE"),
    }
    unexpected = set(existing) - set(expected)
    if unexpected:
        raise RuntimeError(
            "Transaction inclusion checkpoint triggers do not match revision 0021."
        )
    for name, sql in existing.items():
        if _normalize_sql(sql) != _normalize_sql(expected[name]):
            raise RuntimeError(
                f"Transaction inclusion checkpoint trigger {name} does not match revision 0021."
            )
    for name, sql in expected.items():
        if name not in existing:
            bind.exec_driver_sql(sql)
    duplicates = bind.execute(sa.text(
        "SELECT COUNT(*) FROM ("
        f'SELECT boc_transaction_id, trust_level, verifier_policy_id FROM "{_TABLE}" '
        "GROUP BY boc_transaction_id, trust_level, verifier_policy_id "
        "HAVING COUNT(*) > 1)"
    )).scalar_one()
    if int(duplicates) != 0:
        raise RuntimeError(
            "Transaction inclusion checkpoint identities are duplicated."
        )


def _validated_indexes(*, transition: bool) -> dict[str, dict[str, Any]]:
    indexes = {
        str(item["name"]): item
        for item in sa.inspect(op.get_bind()).get_indexes(_TABLE)
    }
    allowed = {_DIGEST_INDEX, _OLD_INDEX, _NEW_INDEX}
    if set(indexes) - allowed:
        raise RuntimeError(
            "Transaction inclusion checkpoint indexes do not match revision 0021."
        )
    expected = {
        _DIGEST_INDEX: (("evidence_digest_sha256",), False, None),
        _OLD_INDEX: (("boc_transaction_id", "trust_level"), True, None),
        _NEW_INDEX: (
            ("boc_transaction_id", "trust_level", "verifier_policy_id"),
            True,
            None,
        ),
    }
    for name, index in indexes.items():
        if _index_signature(index) != expected[name]:
            raise RuntimeError(
                f"Existing transaction inclusion checkpoint index {name} does not match revision 0021."
            )
    if _DIGEST_INDEX not in indexes:
        raise RuntimeError(
            "Transaction inclusion digest index is missing before revision 0021."
        )
    if transition:
        if _OLD_INDEX not in indexes and _NEW_INDEX not in indexes:
            raise RuntimeError(
                "Transaction inclusion checkpoint index has no resumable revision 0021 state."
            )
    elif set(indexes) != {_DIGEST_INDEX, _NEW_INDEX}:
        raise RuntimeError(
            "Transaction inclusion checkpoint indexes did not reach revision 0021."
        )
    return indexes


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Transaction inclusion checkpoint migration requires online validation."
        )
    if _TABLE not in set(sa.inspect(op.get_bind()).get_table_names()):
        raise RuntimeError(
            "Revision 0021 requires the transaction inclusion proof table."
        )
    prefix = _validate_column_prefix()
    if prefix < len(_ADDITIONS):
        indexes = _validated_indexes(transition=True)
        if _NEW_INDEX in indexes:
            raise RuntimeError(
                "Revision 0021 cannot add missing columns after its final index exists."
            )
        _add_remaining_columns(prefix)
    if _validate_column_prefix() != len(_ADDITIONS):
        raise RuntimeError(
            "Transaction inclusion checkpoint columns did not reach revision 0021."
        )
    _validate_rows()
    _ensure_triggers()
    indexes = _validated_indexes(transition=True)
    if _NEW_INDEX not in indexes:
        op.create_index(
            _NEW_INDEX,
            _TABLE,
            ["boc_transaction_id", "trust_level", "verifier_policy_id"],
            unique=True,
        )
    indexes = _validated_indexes(transition=True)
    if _OLD_INDEX in indexes:
        op.drop_index(_OLD_INDEX, table_name=_TABLE)
    _validate_rows()
    _ensure_triggers()
    _validated_indexes(transition=False)


def downgrade() -> None:
    raise RuntimeError(
        "Transaction inclusion checkpoint downgrade could discard immutable "
        "proof provenance and is intentionally unsupported."
    )
