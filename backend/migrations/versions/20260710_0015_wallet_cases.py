"""Add durable wallet cases and bounded synchronization attempts.

Revision ID: 20260710_0015
Revises: 20260710_0014
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Any, Callable

from alembic import op
import sqlalchemy as sa


revision = "20260710_0015"
down_revision = "20260710_0014"
branch_labels = None
depends_on = None


_CASES_TABLE = "wallet_cases"
_SYNCS_TABLE = "wallet_case_syncs"
_REQUIRED_TABLES = {"wallet_ingestion_runs"}
_LOCAL_SINGLE_USER_SCOPE = "local-single-user"

_CASE_INDEXES = (
    ("uq_wallet_cases_public_id", ("public_id",), True),
    (
        "uq_wallet_cases_scope_identity",
        (
            "owner_scope_id",
            "network",
            "data_environment",
            "canonical_wallet_key",
        ),
        True,
    ),
    (
        "ix_wallet_cases_scope_updated",
        ("owner_scope_id", "updated_at"),
        False,
    ),
)
_SYNC_INDEXES = (
    ("uq_wallet_case_syncs_public_id", ("public_id",), True),
    (
        "uq_wallet_case_syncs_ingestion_run",
        ("ingestion_run_id",),
        True,
    ),
    (
        "ix_wallet_case_syncs_case_created",
        ("case_id", "created_at"),
        False,
    ),
)

_CASE_CHECKS = (
    (
        "ck_wallet_cases_network",
        "network IN ('ton-mainnet', 'ton-testnet')",
    ),
    (
        "ck_wallet_cases_data_environment",
        "data_environment IN ('demo', 'live')",
    ),
)
_SYNC_CHECKS = (
    (
        "ck_wallet_case_syncs_time_window",
        "time_window IN ('24h', '3d', '7d', 'custom')",
    ),
    (
        "ck_wallet_case_syncs_data_mode",
        "data_mode IN ('mock', 'real')",
    ),
    (
        "ck_wallet_case_syncs_state",
        "state IN ('queued', 'running', 'partial', 'succeeded', 'failed', 'cancelled')",
    ),
    (
        "ck_wallet_case_syncs_requested_bounds",
        "requested_start < requested_end",
    ),
    (
        "ck_wallet_case_syncs_progress_current",
        "progress_current >= 0",
    ),
    (
        "ck_wallet_case_syncs_progress_total",
        "progress_total IS NULL OR progress_total >= 0",
    ),
    (
        "ck_wallet_case_syncs_progress_bounds",
        "progress_total IS NULL OR progress_current <= progress_total",
    ),
)


def _case_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column(
            "owner_scope_id",
            sa.String(length=64),
            nullable=False,
            server_default=_LOCAL_SINGLE_USER_SCOPE,
        ),
        sa.Column("network", sa.String(length=16), nullable=False),
        sa.Column("data_environment", sa.String(length=8), nullable=False),
        sa.Column("canonical_wallet_key", sa.String(length=76), nullable=False),
        sa.Column(
            "canonical_identity_version",
            sa.String(length=24),
            nullable=False,
        ),
        sa.Column("display_address", sa.String(length=128), nullable=False),
        sa.Column("label", sa.String(length=120), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
    )


def _sync_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(length=36), nullable=False),
        sa.Column(
            "case_id",
            sa.Integer(),
            sa.ForeignKey(f"{_CASES_TABLE}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ingestion_run_id",
            sa.Integer(),
            sa.ForeignKey("wallet_ingestion_runs.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("time_window", sa.String(length=12), nullable=False),
        sa.Column("data_mode", sa.String(length=8), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("requested_start", sa.DateTime(), nullable=False),
        sa.Column("requested_end", sa.DateTime(), nullable=False),
        sa.Column(
            "requested_surfaces_json",
            sa.Text(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "state",
            sa.String(length=16),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "stage",
            sa.String(length=32),
            nullable=False,
            server_default="queued",
        ),
        sa.Column(
            "progress_current",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("progress_total", sa.Integer(), nullable=True),
        sa.Column(
            "coverage_summary_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_detail_safe", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )


def _constraints(
    checks: tuple[tuple[str, str], ...],
) -> tuple[sa.CheckConstraint, ...]:
    return tuple(
        sa.CheckConstraint(expression, name=name) for name, expression in checks
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
    argument = column.server_default.arg
    if isinstance(argument, str):
        return _default_signature(repr(argument))
    return _default_signature(
        argument.compile(compile_kwargs={"literal_binds": True})
    )


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
    if table_name == _CASES_TABLE:
        return set()
    return {
        (
            ("case_id",),
            None,
            _CASES_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
        (
            ("ingestion_run_id",),
            None,
            "wallet_ingestion_runs",
            ("id",),
            (("ondelete", "RESTRICT"),),
        ),
    }


def _check_signature(check: dict[str, Any]) -> tuple[str, str]:
    return (
        str(check.get("name")),
        " ".join(str(check.get("sqltext")).split()),
    )


def _validate_existing_table(
    table_name: str,
    column_factory: Callable[[], tuple[sa.Column, ...]],
    expected_indexes: tuple[tuple[Any, ...], ...],
    expected_checks: tuple[tuple[str, str], ...],
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
            f"Existing {table_name} columns do not match revision 0015: "
            f"expected={expected_columns}, actual={actual_columns}."
        )

    actual_pk = tuple(
        inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
    )
    if actual_pk != ("id",):
        raise RuntimeError(
            f"Existing {table_name} primary key does not match revision 0015: "
            f"actual={actual_pk}."
        )

    actual_foreign_keys = {
        _foreign_key_signature(foreign_key)
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    expected_foreign_keys = _expected_foreign_keys(table_name)
    if actual_foreign_keys != expected_foreign_keys:
        raise RuntimeError(
            f"Existing {table_name} foreign keys do not match revision 0015: "
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
            f"Existing {table_name} has unexpected indexes for revision 0015: "
            f"{unexpected_indexes}."
        )
    for name, expected in expected_by_name.items():
        actual = actual_by_name.get(name)
        if actual is not None and actual != expected:
            raise RuntimeError(
                f"Existing {table_name} index does not match revision 0015: "
                f"expected={expected}, actual={actual}."
            )
        if actual is None and not allow_missing_indexes:
            raise RuntimeError(
                f"Existing {table_name} is missing revision 0015 index {name}."
            )

    unique_constraints = inspector.get_unique_constraints(table_name)
    if unique_constraints:
        raise RuntimeError(
            f"Existing {table_name} has unexpected unique constraints for "
            f"revision 0015: {unique_constraints}."
        )

    actual_checks = {
        _check_signature(check)
        for check in inspector.get_check_constraints(table_name)
    }
    if actual_checks != set(expected_checks):
        raise RuntimeError(
            f"Existing {table_name} check constraints do not match revision "
            f"0015: expected={set(expected_checks)}, actual={actual_checks}."
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
        (_CASES_TABLE, _case_columns, _CASE_INDEXES, _CASE_CHECKS),
        (_SYNCS_TABLE, _sync_columns, _SYNC_INDEXES, _SYNC_CHECKS),
    )


def _validate_preexisting_state() -> set[str]:
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    missing_required = sorted(_REQUIRED_TABLES - tables)
    if missing_required:
        raise RuntimeError(
            "Revision 0015 requires the exact revision 0014 ingestion schema; "
            f"missing={missing_required}."
        )

    case_tables = tables & {_CASES_TABLE, _SYNCS_TABLE}
    if _SYNCS_TABLE in case_tables and _CASES_TABLE not in case_tables:
        raise RuntimeError(
            "Existing wallet_case_syncs without its wallet_cases parent is not "
            "a valid revision 0015 retry state."
        )
    for table_name, factory, indexes, checks in _table_specs():
        if table_name in case_tables:
            _validate_existing_table(
                table_name,
                factory,
                indexes,
                checks,
                allow_missing_indexes=True,
            )
    return case_tables


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
                f"Existing {table_name} index does not match revision 0015: "
                f"expected={expected}, actual={actual}."
            )
        if actual is None:
            op.create_index(name, table_name, list(columns), unique=unique)


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case schema validation requires an online database "
            "connection; offline SQL generation is unsupported."
        )

    # SQLite DDL may survive a failed migration transaction. Accept only the
    # exact, empty table fragments this revision itself can leave behind, then
    # repair missing tables/indexes and validate the exact final contract.
    existing = _validate_preexisting_state()
    for table_name, factory, indexes, checks in _table_specs():
        if table_name not in existing:
            op.create_table(
                table_name,
                *factory(),
                *_constraints(checks),
            )
        _validate_existing_table(
            table_name,
            factory,
            indexes,
            checks,
            allow_missing_indexes=True,
        )
        _ensure_indexes(table_name, indexes)

    for table_name, factory, indexes, checks in _table_specs():
        _validate_existing_table(
            table_name,
            factory,
            indexes,
            checks,
            allow_missing_indexes=False,
        )


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case downgrade would discard durable case identity and sync "
        "history and is intentionally unsupported. Restore a verified backup "
        "instead."
    )
