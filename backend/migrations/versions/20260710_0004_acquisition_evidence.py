"""Add durable wallet acquisition stream and page evidence.

Revision ID: 20260710_0004
Revises: 20260710_0003
Create Date: 2026-07-10
"""

from __future__ import annotations

from typing import Any, Callable

from alembic import op
import sqlalchemy as sa


revision = "20260710_0004"
down_revision = "20260710_0003"
branch_labels = None
depends_on = None


_STREAMS_TABLE = "wallet_acquisition_streams"
_PAGES_TABLE = "wallet_acquisition_pages"

_STREAM_INDEX = (
    "uq_wallet_acquisition_streams_run_provider_key",
    ("run_id", "provider", "stream_key"),
    True,
)
_PAGE_INDEX = (
    "uq_wallet_acquisition_pages_stream_page",
    ("stream_id", "page_index"),
    True,
)


def _stream_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("wallet_ingestion_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("stream_key", sa.String(length=40), nullable=False),
        sa.Column("contract_version", sa.String(length=48), nullable=False),
        sa.Column("scope_kind", sa.String(length=24), nullable=False),
        sa.Column("resolved_start_at", sa.DateTime(), nullable=True),
        sa.Column("resolved_end_at", sa.DateTime(), nullable=True),
        sa.Column(
            "request_query_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("page_size", sa.Integer(), nullable=False),
        sa.Column("max_pages", sa.Integer(), nullable=False),
        sa.Column("max_items", sa.Integer(), nullable=False),
        sa.Column(
            "completion_state",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'incomplete'"),
        ),
        sa.Column("termination_reason", sa.String(length=48), nullable=True),
        sa.Column(
            "pages_attempted",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "pages_succeeded",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "raw_item_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "normalized_item_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "duplicate_item_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("first_cursor", sa.String(length=128), nullable=True),
        sa.Column("terminal_cursor", sa.String(length=128), nullable=True),
        sa.Column(
            "bounds_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_json", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )


def _page_columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column(
            "stream_id",
            sa.Integer(),
            sa.ForeignKey(f"{_STREAMS_TABLE}.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("page_index", sa.Integer(), nullable=False),
        sa.Column("request_cursor", sa.String(length=128), nullable=True),
        sa.Column("response_cursor", sa.String(length=128), nullable=True),
        sa.Column("request_offset", sa.Integer(), nullable=True),
        sa.Column("requested_limit", sa.Integer(), nullable=False),
        sa.Column(
            "request_query_json",
            sa.Text(),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column(
            "raw_item_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "normalized_item_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "duplicate_item_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("newest_logical_time", sa.String(length=20), nullable=True),
        sa.Column("oldest_logical_time", sa.String(length=20), nullable=True),
        sa.Column("newest_activity_at", sa.DateTime(), nullable=True),
        sa.Column("oldest_activity_at", sa.DateTime(), nullable=True),
        sa.Column("response_digest_sha256", sa.String(length=64), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("fetch_status", sa.String(length=16), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_json", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
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
    if table_name == _STREAMS_TABLE:
        return {
            (
                ("run_id",),
                None,
                "wallet_ingestion_runs",
                ("id",),
                (("ondelete", "CASCADE"),),
            )
        }
    return {
        (
            ("stream_id",),
            None,
            _STREAMS_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        )
    }


def _validate_existing_table(
    table_name: str,
    column_factory: Callable[[], tuple[sa.Column, ...]],
    expected_index: tuple[Any, ...],
    *,
    allow_missing_index: bool,
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
            f"Existing {table_name} columns do not match revision 0004: "
            f"expected={expected_columns}, actual={actual_columns}."
        )

    actual_pk = tuple(
        inspector.get_pk_constraint(table_name).get("constrained_columns") or ()
    )
    if actual_pk != ("id",):
        raise RuntimeError(
            f"Existing {table_name} primary key does not match revision 0004: "
            f"expected={('id',)}, actual={actual_pk}."
        )

    actual_foreign_keys = {
        _foreign_key_signature(foreign_key)
        for foreign_key in inspector.get_foreign_keys(table_name)
    }
    expected_foreign_keys = _expected_foreign_keys(table_name)
    if actual_foreign_keys != expected_foreign_keys:
        raise RuntimeError(
            f"Existing {table_name} foreign keys do not match revision 0004: "
            f"expected={expected_foreign_keys}, actual={actual_foreign_keys}."
        )

    expected_index_signature = _expected_index_signature(expected_index)
    expected_index_name = str(expected_index[0])
    indexes = {
        str(index.get("name")): _index_signature(index)
        for index in inspector.get_indexes(table_name)
    }
    unexpected_indexes = sorted(set(indexes) - {expected_index_name})
    if unexpected_indexes:
        raise RuntimeError(
            f"Existing {table_name} has unexpected indexes for revision 0004: "
            f"{unexpected_indexes}."
        )
    actual_index = indexes.get(expected_index_name)
    if actual_index is not None and actual_index != expected_index_signature:
        raise RuntimeError(
            f"Existing {table_name} index does not match revision 0004: "
            f"expected={expected_index_signature}, actual={actual_index}."
        )
    if not allow_missing_index and actual_index is None:
        raise RuntimeError(
            f"Existing {table_name} is missing the revision 0004 index "
            f"{expected_index_name}."
        )

    unique_constraints = inspector.get_unique_constraints(table_name)
    if unique_constraints:
        raise RuntimeError(
            f"Existing {table_name} has unexpected unique constraints for "
            f"revision 0004: {unique_constraints}."
        )
    check_constraints = inspector.get_check_constraints(table_name)
    if check_constraints:
        raise RuntimeError(
            f"Existing {table_name} has unexpected check constraints for "
            f"revision 0004: {check_constraints}."
        )

    row_count = connection.exec_driver_sql(
        f'SELECT COUNT(*) FROM "{table_name}"'
    ).scalar_one()
    if row_count:
        raise RuntimeError(
            f"Existing {table_name} contains unexpected pre-revision data; "
            f"row_count={row_count}."
        )


def _validate_preexisting_state() -> set[str]:
    connection = op.get_bind()
    existing = set(sa.inspect(connection).get_table_names())
    acquisition_tables = existing & {_STREAMS_TABLE, _PAGES_TABLE}
    if _PAGES_TABLE in acquisition_tables and _STREAMS_TABLE not in acquisition_tables:
        raise RuntimeError(
            "Existing wallet_acquisition_pages without its parent stream table "
            "is not a valid revision 0004 retry state."
        )
    if _STREAMS_TABLE in acquisition_tables:
        _validate_existing_table(
            _STREAMS_TABLE,
            _stream_columns,
            _STREAM_INDEX,
            allow_missing_index=True,
        )
    if _PAGES_TABLE in acquisition_tables:
        _validate_existing_table(
            _PAGES_TABLE,
            _page_columns,
            _PAGE_INDEX,
            allow_missing_index=True,
        )
    return acquisition_tables


def _create_streams_table() -> None:
    op.create_table(_STREAMS_TABLE, *_stream_columns())


def _create_pages_table() -> None:
    op.create_table(_PAGES_TABLE, *_page_columns())


def _ensure_index(table_name: str, index: tuple[Any, ...]) -> None:
    name, columns, unique = index
    reflected = {
        str(item.get("name")): _index_signature(item)
        for item in sa.inspect(op.get_bind()).get_indexes(table_name)
    }
    expected = _expected_index_signature(index)
    actual = reflected.get(name)
    if actual is not None and actual != expected:
        raise RuntimeError(
            f"Existing {table_name} index does not match revision 0004: "
            f"expected={expected}, actual={actual}."
        )
    if actual is None:
        op.create_index(name, table_name, list(columns), unique=unique)


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Acquisition evidence schema validation requires an online "
            "database connection; offline SQL generation is unsupported."
        )

    # SQLite DDL can survive a failed migration transaction. Validate every
    # pre-existing fragment before creating anything, then create only the
    # missing tables/indexes and validate the exact final state.
    existing = _validate_preexisting_state()
    if _STREAMS_TABLE not in existing:
        _create_streams_table()
    _validate_existing_table(
        _STREAMS_TABLE,
        _stream_columns,
        _STREAM_INDEX,
        allow_missing_index=True,
    )
    _ensure_index(_STREAMS_TABLE, _STREAM_INDEX)

    if _PAGES_TABLE not in existing:
        _create_pages_table()
    _validate_existing_table(
        _PAGES_TABLE,
        _page_columns,
        _PAGE_INDEX,
        allow_missing_index=True,
    )
    _ensure_index(_PAGES_TABLE, _PAGE_INDEX)

    _validate_existing_table(
        _STREAMS_TABLE,
        _stream_columns,
        _STREAM_INDEX,
        allow_missing_index=False,
    )
    _validate_existing_table(
        _PAGES_TABLE,
        _page_columns,
        _PAGE_INDEX,
        allow_missing_index=False,
    )


def downgrade() -> None:
    raise RuntimeError(
        "Acquisition evidence downgrade would discard persisted pagination "
        "contracts and is intentionally unsupported. Restore a verified "
        "backup instead."
    )
