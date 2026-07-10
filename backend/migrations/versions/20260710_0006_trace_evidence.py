"""Add finalized relational wallet trace evidence captures.

Revision ID: 20260710_0006
Revises: 20260710_0005
Create Date: 2026-07-10
"""

from __future__ import annotations

from typing import Any, Callable

from alembic import op
import sqlalchemy as sa


revision = "20260710_0006"
down_revision = "20260710_0005"
branch_labels = None
depends_on = None


_CAPTURES_TABLE = "wallet_trace_evidence_captures"
_NODES_TABLE = "wallet_trace_evidence_nodes"
_MESSAGES_TABLE = "wallet_trace_evidence_messages"

_CAPTURE_INDEXES = (
    (
        "uq_wallet_trace_captures_run_root",
        ("run_id", "provider", "contract_version", "root_transaction_hash"),
        True,
    ),
    (
        "uq_wallet_trace_captures_run_anchor",
        ("run_id", "captured_via_transaction_id", "contract_version"),
        True,
    ),
    (
        "uq_wallet_trace_captures_run_slot",
        ("run_id", "capture_slot"),
        True,
    ),
)
_NODE_INDEXES = (
    (
        "uq_wallet_trace_nodes_capture_preorder",
        ("capture_id", "preorder_index"),
        True,
    ),
    (
        "uq_wallet_trace_nodes_capture_hash",
        ("capture_id", "transaction_hash"),
        True,
    ),
    (
        "uq_wallet_trace_nodes_capture_coordinate",
        ("capture_id", "account_canonical", "logical_time"),
        True,
    ),
)
_MESSAGE_INDEXES = (
    (
        "uq_wallet_trace_messages_node_role_ordinal",
        ("node_id", "role", "ordinal"),
        True,
    ),
    (
        "ix_wallet_trace_messages_observation",
        ("observation_identity_key",),
        False,
    ),
    (
        "ix_wallet_trace_messages_hash",
        ("message_hash",),
        False,
    ),
)


def _capture_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("wallet_ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "captured_via_transaction_id",
            sa.Integer(),
            sa.ForeignKey("wallet_transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("capture_slot", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("contract_version", sa.String(length=48), nullable=False),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("root_transaction_hash", sa.String(length=64), nullable=False),
        sa.Column("trace_state", sa.String(length=16), nullable=False),
        sa.Column("transaction_count", sa.Integer(), nullable=False),
        sa.Column("max_depth", sa.Integer(), nullable=False),
        sa.Column("message_count", sa.Integer(), nullable=False),
        sa.Column("root_inbound_message_count", sa.Integer(), nullable=False),
        sa.Column("child_internal_message_count", sa.Integer(), nullable=False),
        sa.Column("remaining_out_message_count", sa.Integer(), nullable=False),
        sa.Column("internal_message_count", sa.Integer(), nullable=False),
        sa.Column("external_in_message_count", sa.Integer(), nullable=False),
        sa.Column("external_out_message_count", sa.Integer(), nullable=False),
        sa.Column("successful_transaction_count", sa.Integer(), nullable=False),
        sa.Column("failed_transaction_count", sa.Integer(), nullable=False),
        sa.Column("aborted_transaction_count", sa.Integer(), nullable=False),
        sa.Column("unique_account_count", sa.Integer(), nullable=False),
        sa.Column("evidence_digest_sha256", sa.String(length=64), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
    )


def _node_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "capture_id",
            sa.Integer(),
            sa.ForeignKey(f"{_CAPTURES_TABLE}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("preorder_index", sa.Integer(), nullable=False),
        sa.Column(
            "parent_node_id",
            sa.Integer(),
            sa.ForeignKey(f"{_NODES_TABLE}.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("depth", sa.Integer(), nullable=False),
        sa.Column("transaction_hash", sa.String(length=64), nullable=False),
        sa.Column("account_canonical", sa.String(length=76), nullable=False),
        sa.Column("logical_time", sa.String(length=20), nullable=False),
        sa.Column("unix_time", sa.Integer(), nullable=False),
        sa.Column("success", sa.Boolean(), nullable=False),
        sa.Column("aborted", sa.Boolean(), nullable=False),
    )


def _message_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "node_id",
            sa.Integer(),
            sa.ForeignKey(f"{_NODES_TABLE}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("message_hash", sa.String(length=64), nullable=False),
        sa.Column("message_type", sa.String(length=16), nullable=False),
        sa.Column("source_account_canonical", sa.String(length=76), nullable=True),
        sa.Column(
            "destination_account_canonical",
            sa.String(length=76),
            nullable=True,
        ),
        sa.Column("created_logical_time", sa.String(length=20), nullable=False),
        sa.Column("unix_time", sa.Integer(), nullable=False),
        sa.Column("value_nanoton", sa.String(length=20), nullable=False),
        sa.Column("forward_fee_nanoton", sa.String(length=20), nullable=False),
        sa.Column("ihr_fee_nanoton", sa.String(length=20), nullable=False),
        sa.Column("import_fee_nanoton", sa.String(length=20), nullable=False),
        sa.Column("ihr_disabled", sa.Boolean(), nullable=False),
        sa.Column("bounce", sa.Boolean(), nullable=False),
        sa.Column("bounced", sa.Boolean(), nullable=False),
        sa.Column(
            "observation_identity_key",
            sa.String(length=256),
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
    if table_name == _CAPTURES_TABLE:
        return {
            (
                ("run_id",),
                None,
                "wallet_ingestion_runs",
                ("id",),
                (("ondelete", "CASCADE"),),
            ),
            (
                ("captured_via_transaction_id",),
                None,
                "wallet_transactions",
                ("id",),
                (("ondelete", "CASCADE"),),
            ),
        }
    if table_name == _NODES_TABLE:
        return {
            (
                ("capture_id",),
                None,
                _CAPTURES_TABLE,
                ("id",),
                (("ondelete", "CASCADE"),),
            ),
            (
                ("parent_node_id",),
                None,
                _NODES_TABLE,
                ("id",),
                (("ondelete", "CASCADE"),),
            ),
        }
    return {
        (
            ("node_id",),
            None,
            _NODES_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        )
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
            f"Existing {table_name} columns do not match revision 0006: "
            f"expected={expected_columns}, actual={actual_columns}."
        )

    actual_pk = tuple(
        inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
    )
    if actual_pk != ("id",):
        raise RuntimeError(
            f"Existing {table_name} primary key does not match revision 0006: "
            f"expected={('id',)}, actual={actual_pk}."
        )

    actual_foreign_keys = {
        _foreign_key_signature(foreign_key)
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    expected_foreign_keys = _expected_foreign_keys(table_name)
    if actual_foreign_keys != expected_foreign_keys:
        raise RuntimeError(
            f"Existing {table_name} foreign keys do not match revision 0006: "
            f"expected={expected_foreign_keys}, actual={actual_foreign_keys}."
        )

    expected_by_name = {
        str(index[0]): _expected_index_signature(index)
        for index in expected_indexes
    }
    actual_by_name = {
        str(index.get("name")): _index_signature(index)
        for index in inspector.get_indexes(table_name)
    }
    unexpected_indexes = sorted(set(actual_by_name) - set(expected_by_name))
    if unexpected_indexes:
        raise RuntimeError(
            f"Existing {table_name} has unexpected indexes for revision 0006: "
            f"{unexpected_indexes}."
        )
    for name, expected in expected_by_name.items():
        actual = actual_by_name.get(name)
        if actual is not None and actual != expected:
            raise RuntimeError(
                f"Existing {table_name} index does not match revision 0006: "
                f"expected={expected}, actual={actual}."
            )
        if not allow_missing_indexes and actual is None:
            raise RuntimeError(
                f"Existing {table_name} is missing the revision 0006 index "
                f"{name}."
            )

    unique_constraints = inspector.get_unique_constraints(table_name)
    if unique_constraints:
        raise RuntimeError(
            f"Existing {table_name} has unexpected unique constraints for "
            f"revision 0006: {unique_constraints}."
        )
    check_constraints = inspector.get_check_constraints(table_name)
    if check_constraints:
        raise RuntimeError(
            f"Existing {table_name} has unexpected check constraints for "
            f"revision 0006: {check_constraints}."
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
        (_CAPTURES_TABLE, _capture_columns, _CAPTURE_INDEXES),
        (_NODES_TABLE, _node_columns, _NODE_INDEXES),
        (_MESSAGES_TABLE, _message_columns, _MESSAGE_INDEXES),
    )


def _validate_preexisting_state() -> set[str]:
    connection = op.get_bind()
    existing_tables = set(sa.inspect(connection).get_table_names())
    evidence_tables = existing_tables & {
        _CAPTURES_TABLE,
        _NODES_TABLE,
        _MESSAGES_TABLE,
    }
    if _NODES_TABLE in evidence_tables and _CAPTURES_TABLE not in evidence_tables:
        raise RuntimeError(
            "Existing wallet_trace_evidence_nodes without its capture table "
            "is not a valid revision 0006 retry state."
        )
    if _MESSAGES_TABLE in evidence_tables and _NODES_TABLE not in evidence_tables:
        raise RuntimeError(
            "Existing wallet_trace_evidence_messages without its node table "
            "is not a valid revision 0006 retry state."
        )

    for table_name, column_factory, expected_indexes in _table_specs():
        if table_name in evidence_tables:
            _validate_existing_table(
                table_name,
                column_factory,
                expected_indexes,
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
                f"Existing {table_name} index does not match revision 0006: "
                f"expected={expected}, actual={actual}."
            )
        if actual is None:
            op.create_index(name, table_name, list(columns), unique=unique)


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Trace evidence schema validation requires an online database "
            "connection; offline SQL generation is unsupported."
        )

    # SQLite DDL fragments can survive a failed transaction. Validate every
    # existing fragment before mutation, repair only exact empty retry states,
    # and then require exact final schema parity.
    existing = _validate_preexisting_state()
    for table_name, column_factory, expected_indexes in _table_specs():
        if table_name not in existing:
            op.create_table(table_name, *column_factory())
        _validate_existing_table(
            table_name,
            column_factory,
            expected_indexes,
            allow_missing_indexes=True,
        )
        _ensure_indexes(table_name, expected_indexes)

    for table_name, column_factory, expected_indexes in _table_specs():
        _validate_existing_table(
            table_name,
            column_factory,
            expected_indexes,
            allow_missing_indexes=False,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Trace evidence downgrade would discard finalized persisted evidence "
        "and is intentionally unsupported. Restore a verified backup instead."
    )
