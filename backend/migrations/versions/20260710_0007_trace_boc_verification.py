"""Add locally verified transaction BOC evidence.

Revision ID: 20260710_0007
Revises: 20260710_0006
Create Date: 2026-07-10
"""

from __future__ import annotations

from typing import Any, Callable

from alembic import op
import sqlalchemy as sa


revision = "20260710_0007"
down_revision = "20260710_0006"
branch_labels = None
depends_on = None


_VERIFICATIONS_TABLE = "wallet_trace_boc_verifications"
_TRANSACTIONS_TABLE = "wallet_trace_boc_transactions"
_REQUIRED_TABLES = {
    "wallet_trace_evidence_captures",
    "wallet_trace_evidence_messages",
    "wallet_trace_evidence_nodes",
}

_VERIFICATION_INDEXES = (
    (
        "uq_wallet_trace_boc_verifications_capture_contract",
        ("capture_id", "contract_version"),
        True,
    ),
    (
        "ix_wallet_trace_boc_verifications_digest",
        ("evidence_digest_sha256",),
        False,
    ),
)
_TRANSACTION_INDEXES = (
    (
        "uq_wallet_trace_boc_transactions_verification_node",
        ("verification_id", "node_id"),
        True,
    ),
    (
        "uq_wallet_trace_boc_transactions_verification_preorder",
        ("verification_id", "preorder_index"),
        True,
    ),
    (
        "uq_wallet_trace_boc_transactions_verification_hash",
        ("verification_id", "transaction_hash"),
        True,
    ),
)


def _verification_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "capture_id",
            sa.Integer(),
            sa.ForeignKey(
                "wallet_trace_evidence_captures.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column("contract_version", sa.String(length=48), nullable=False),
        sa.Column("verifier_name", sa.String(length=32), nullable=False),
        sa.Column("verifier_version", sa.String(length=24), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("total_boc_bytes", sa.Integer(), nullable=False),
        sa.Column(
            "normalized_external_in_hash_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column(
            "direct_cell_hash_message_count",
            sa.Integer(),
            nullable=False,
        ),
        sa.Column("body_hash_count", sa.Integer(), nullable=False),
        sa.Column("opcode_count", sa.Integer(), nullable=False),
        sa.Column("evidence_digest_sha256", sa.String(length=64), nullable=False),
        sa.Column("verified_at", sa.DateTime(), nullable=False),
    )


def _transaction_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "verification_id",
            sa.Integer(),
            sa.ForeignKey(
                f"{_VERIFICATIONS_TABLE}.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "node_id",
            sa.Integer(),
            sa.ForeignKey("wallet_trace_evidence_nodes.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("preorder_index", sa.Integer(), nullable=False),
        sa.Column("transaction_hash", sa.String(length=64), nullable=False),
        sa.Column("transaction_boc_hex", sa.Text(), nullable=False),
        sa.Column("transaction_boc_bytes", sa.Integer(), nullable=False),
        sa.Column("transaction_cell_hash", sa.String(length=64), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column(
            "message_evidence_digest_sha256",
            sa.String(length=64),
            nullable=False,
        ),
    )


def _type_signature(value: Any) -> str:
    return "".join(str(value).upper().split())


def _default_signature(value: Any) -> str | None:
    if value is None:
        return None
    return "".join(str(value).split())


def _expected_default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    return _default_signature(column.server_default.arg)


def _column_signature(column: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(column.get("name")),
        _type_signature(column.get("type")),
        bool(column.get("nullable")),
        _default_signature(column.get("default")),
        bool(column.get("primary_key")),
    )


def _expected_column_signature(column: sa.Column) -> tuple[Any, ...]:
    return (
        str(column.name),
        _type_signature(column.type),
        bool(column.nullable),
        _expected_default(column),
        bool(column.primary_key),
    )


def _options_signature(
    options: dict[str, Any] | None,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (str(key), " ".join(str(value).split()))
            for key, value in (options or {}).items()
            if value is not None
        )
    )


def _index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(index.get("name")),
        tuple(index.get("column_names") or ()),
        bool(index.get("unique")),
        _options_signature(index.get("dialect_options")),
    )


def _expected_index_signature(index: tuple[Any, ...]) -> tuple[Any, ...]:
    name, columns, unique = index
    return name, columns, unique, ()


def _foreign_key_signature(foreign_key: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(foreign_key.get("constrained_columns") or ()),
        foreign_key.get("referred_schema"),
        foreign_key.get("referred_table"),
        tuple(foreign_key.get("referred_columns") or ()),
        _options_signature(foreign_key.get("options")),
    )


def _expected_foreign_keys(table_name: str) -> set[tuple[Any, ...]]:
    if table_name == _VERIFICATIONS_TABLE:
        return {
            (
                ("capture_id",),
                None,
                "wallet_trace_evidence_captures",
                ("id",),
                (("ondelete", "CASCADE"),),
            )
        }
    return {
        (
            ("verification_id",),
            None,
            _VERIFICATIONS_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
        (
            ("node_id",),
            None,
            "wallet_trace_evidence_nodes",
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
    }


def _validate_existing_table(
    table_name: str,
    column_factory: Callable[[], tuple[sa.Column, ...]],
    expected_indexes: tuple[tuple[Any, ...], ...],
    *,
    allow_missing_indexes: bool,
) -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    actual_columns = tuple(
        _column_signature(column)
        for column in inspector.get_columns(table_name)
    )
    expected_columns = tuple(
        _expected_column_signature(column) for column in column_factory()
    )
    if actual_columns != expected_columns:
        raise RuntimeError(
            f"Existing {table_name} columns do not match revision 0007: "
            f"expected={expected_columns}, actual={actual_columns}."
        )
    actual_pk = tuple(
        inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
    )
    if actual_pk != ("id",):
        raise RuntimeError(
            f"Existing {table_name} primary key does not match revision 0007."
        )
    actual_foreign_keys = {
        _foreign_key_signature(value)
        for value in inspector.get_foreign_keys(table_name)
    }
    if actual_foreign_keys != _expected_foreign_keys(table_name):
        raise RuntimeError(
            f"Existing {table_name} foreign keys do not match revision 0007."
        )
    expected_by_name = {
        str(index[0]): _expected_index_signature(index)
        for index in expected_indexes
    }
    actual_by_name = {
        str(index.get("name")): _index_signature(index)
        for index in inspector.get_indexes(table_name)
    }
    unexpected = sorted(set(actual_by_name) - set(expected_by_name))
    if unexpected:
        raise RuntimeError(
            f"Existing {table_name} has unexpected indexes for revision 0007: "
            f"{unexpected}."
        )
    for name, expected in expected_by_name.items():
        actual = actual_by_name.get(name)
        if actual is not None and actual != expected:
            raise RuntimeError(
                f"Existing {table_name} index does not match revision 0007: "
                f"expected={expected}, actual={actual}."
            )
        if actual is None and not allow_missing_indexes:
            raise RuntimeError(
                f"Existing {table_name} is missing revision 0007 index {name}."
            )
    if inspector.get_unique_constraints(table_name):
        raise RuntimeError(
            f"Existing {table_name} has unexpected unique constraints."
        )
    if inspector.get_check_constraints(table_name):
        raise RuntimeError(
            f"Existing {table_name} has unexpected check constraints."
        )
    row_count = connection.exec_driver_sql(
        f'SELECT COUNT(*) FROM "{table_name}"'
    ).scalar_one()
    if row_count:
        raise RuntimeError(
            f"Existing {table_name} contains unexpected pre-revision data; "
            f"row_count={row_count}."
        )


def _table_specs() -> tuple[tuple[Any, ...], ...]:
    return (
        (_VERIFICATIONS_TABLE, _verification_columns, _VERIFICATION_INDEXES),
        (_TRANSACTIONS_TABLE, _transaction_columns, _TRANSACTION_INDEXES),
    )


def _validate_preexisting_state() -> set[str]:
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    missing_required = sorted(_REQUIRED_TABLES - tables)
    if missing_required:
        raise RuntimeError(
            "Revision 0007 requires the exact revision 0006 trace tables; "
            f"missing={missing_required}."
        )
    evidence_tables = tables & {_VERIFICATIONS_TABLE, _TRANSACTIONS_TABLE}
    if (
        _TRANSACTIONS_TABLE in evidence_tables
        and _VERIFICATIONS_TABLE not in evidence_tables
    ):
        raise RuntimeError(
            "Existing BOC transactions without their verification table are "
            "not a valid revision 0007 retry state."
        )
    for table_name, factory, indexes in _table_specs():
        if table_name in evidence_tables:
            _validate_existing_table(
                table_name,
                factory,
                indexes,
                allow_missing_indexes=True,
            )
    return evidence_tables


def _ensure_indexes(
    table_name: str,
    expected_indexes: tuple[tuple[Any, ...], ...],
) -> None:
    reflected = {
        str(index.get("name")): _index_signature(index)
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }
    for index in expected_indexes:
        name, columns, unique = index
        expected = _expected_index_signature(index)
        actual = reflected.get(name)
        if actual is not None and actual != expected:
            raise RuntimeError(
                f"Existing {table_name} index does not match revision 0007: "
                f"expected={expected}, actual={actual}."
            )
        if actual is None:
            op.create_index(name, table_name, list(columns), unique=unique)


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Trace BOC verification schema validation requires an online "
            "database connection; offline SQL generation is unsupported."
        )
    existing = _validate_preexisting_state()
    for table_name, factory, indexes in _table_specs():
        if table_name not in existing:
            op.create_table(table_name, *factory())
        _validate_existing_table(
            table_name,
            factory,
            indexes,
            allow_missing_indexes=True,
        )
        _ensure_indexes(table_name, indexes)
    for table_name, factory, indexes in _table_specs():
        _validate_existing_table(
            table_name,
            factory,
            indexes,
            allow_missing_indexes=False,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Trace BOC verification downgrade would discard locally verified raw "
        "evidence and is intentionally unsupported. Restore a verified backup instead."
    )
