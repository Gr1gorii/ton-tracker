"""Add retained Wallet Case lifecycle audit receipts.

Revision ID: 20260710_0024
Revises: 20260710_0023
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0024"
down_revision = "20260710_0023"
branch_labels = None
depends_on = None


_TABLE = "wallet_case_lifecycle_events"
_REQUIRED_TABLES = {"wallet_cases"}
_INDEXES = (
    ("uq_wallet_case_lifecycle_events_public_id", ("public_id",), True),
    ("uq_wallet_case_lifecycle_events_case_id", ("case_public_id",), True),
    (
        "ix_wallet_case_lifecycle_events_scope_time",
        ("owner_scope_id", "occurred_at", "id"),
        False,
    ),
)


def _columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(36), nullable=False),
        sa.Column("owner_scope_id", sa.String(64), nullable=False),
        sa.Column("case_public_id", sa.String(36), nullable=False),
        sa.Column(
            "event_type",
            sa.String(16),
            nullable=False,
            server_default="deleted",
        ),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("details_json", sa.Text(), nullable=False),
    )


def _checks() -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "event_type = 'deleted'",
            name="ck_wallet_case_lifecycle_events_type",
        ),
        sa.CheckConstraint(
            "length(details_json) > 2",
            name="ck_wallet_case_lifecycle_events_details",
        ),
    )


def _create_table() -> None:
    op.create_table(_TABLE, *_columns(), *_checks())


def _normalize(value: Any) -> str | None:
    return None if value is None else "".join(str(value).upper().split())


def _default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    value = column.server_default.arg
    if isinstance(value, str):
        return _normalize(repr(value))
    return _normalize(value.compile(compile_kwargs={"literal_binds": True}))


def _column_signature(column: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(column.get("name")),
        _normalize(column.get("type")),
        bool(column.get("nullable")),
        _normalize(column.get("default")),
        bool(column.get("primary_key")),
    )


def _expected_column_signature(column: sa.Column) -> tuple[Any, ...]:
    return (
        str(column.name),
        _normalize(column.type),
        bool(column.nullable),
        _default(column),
        bool(column.primary_key),
    )


def _validate_existing(*, require_empty: bool) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    actual_columns = tuple(
        _column_signature(row) for row in inspector.get_columns(_TABLE)
    )
    expected_columns = tuple(
        _expected_column_signature(row) for row in _columns()
    )
    if actual_columns != expected_columns:
        raise RuntimeError(
            "Existing Wallet Case lifecycle event columns differ from revision 0024."
        )
    if inspector.get_foreign_keys(_TABLE):
        raise RuntimeError(
            "Wallet Case lifecycle events must survive deletion without foreign keys."
        )
    actual_checks = {
        (str(item.get("name")), " ".join(str(item.get("sqltext")).split()))
        for item in inspector.get_check_constraints(_TABLE)
    }
    expected_checks = {
        (str(item.name), " ".join(str(item.sqltext).split()))
        for item in _checks()
    }
    if actual_checks != expected_checks:
        raise RuntimeError(
            "Existing Wallet Case lifecycle event checks differ from revision 0024."
        )
    if require_empty and int(
        bind.execute(sa.text(f'SELECT COUNT(*) FROM "{_TABLE}"')).scalar_one()
    ) != 0:
        raise RuntimeError(
            "Pre-revision lifecycle event rows cannot be adopted by revision 0024."
        )


def _ensure_indexes() -> None:
    for name, columns, unique in _INDEXES:
        indexes = {
            str(item["name"]): item
            for item in sa.inspect(op.get_bind()).get_indexes(_TABLE)
        }
        existing = indexes.get(name)
        expected = (columns, unique)
        if existing is None:
            op.create_index(name, _TABLE, list(columns), unique=unique)
        elif (
            tuple(existing.get("column_names") or ()),
            bool(existing.get("unique")),
        ) != expected:
            raise RuntimeError(f"Existing index {name} differs from revision 0024.")


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case lifecycle event validation requires an online database."
        )
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    missing = sorted(_REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError(f"Revision 0024 requires Wallet Case tables: {missing}.")
    existed = _TABLE in tables
    if not existed:
        _create_table()
    else:
        _validate_existing(require_empty=True)
    _ensure_indexes()
    _validate_existing(require_empty=existed)


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case lifecycle event downgrade would discard deletion audit receipts "
        "and is intentionally unsupported. Restore a verified backup instead."
    )
