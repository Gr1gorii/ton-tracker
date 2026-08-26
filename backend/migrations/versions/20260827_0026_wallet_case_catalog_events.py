"""Add frozen Wallet Case catalog positions.

Revision ID: 20260827_0026
Revises: 20260710_0025
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260827_0026"
down_revision = "20260710_0025"
branch_labels = None
depends_on = None


_TABLE = "wallet_case_catalog_events"
_REQUIRED_TABLE = "wallet_cases"
_INDEX = (
    "ix_wallet_case_catalog_events_case_position",
    ("case_id", "id"),
    False,
)


def _columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Column("visible", sa.Boolean(), nullable=False),
    )


def _create_table() -> None:
    op.create_table(
        _TABLE,
        *_columns(),
        sa.ForeignKeyConstraint(
            ["case_id"],
            ["wallet_cases.id"],
            ondelete="CASCADE",
        ),
    )


def _normalize(value: Any) -> str | None:
    return None if value is None else "".join(str(value).upper().split())


def _column_signature(column: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(column.get("name")),
        _normalize(column.get("type")),
        bool(column.get("nullable")),
        bool(column.get("primary_key")),
    )


def _expected_column_signature(column: sa.Column) -> tuple[Any, ...]:
    return (
        str(column.name),
        _normalize(column.type),
        bool(column.nullable),
        bool(column.primary_key),
    )


def _validate_existing(*, require_empty: bool) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    actual_columns = tuple(
        _column_signature(column) for column in inspector.get_columns(_TABLE)
    )
    expected_columns = tuple(
        _expected_column_signature(column) for column in _columns()
    )
    if actual_columns != expected_columns:
        raise RuntimeError(
            "Existing Wallet Case catalog event columns differ from revision 0026."
        )
    foreign_keys = inspector.get_foreign_keys(_TABLE)
    if len(foreign_keys) != 1:
        raise RuntimeError(
            "Existing Wallet Case catalog event foreign key differs from revision 0026."
        )
    foreign_key = foreign_keys[0]
    actual_foreign_key = (
        tuple(foreign_key.get("constrained_columns") or ()),
        str(foreign_key.get("referred_table")),
        tuple(foreign_key.get("referred_columns") or ()),
        str((foreign_key.get("options") or {}).get("ondelete", "")).upper(),
    )
    if actual_foreign_key != (("case_id",), "wallet_cases", ("id",), "CASCADE"):
        raise RuntimeError(
            "Existing Wallet Case catalog event foreign key differs from revision 0026."
        )
    if require_empty and int(
        bind.execute(sa.text(f'SELECT COUNT(*) FROM "{_TABLE}"')).scalar_one()
    ):
        raise RuntimeError(
            "Pre-revision Wallet Case catalog events cannot be adopted by revision 0026."
        )


def _ensure_index() -> None:
    name, columns, unique = _INDEX
    indexes = {
        str(item["name"]): item
        for item in sa.inspect(op.get_bind()).get_indexes(_TABLE)
    }
    existing = indexes.get(name)
    if existing is None:
        op.create_index(name, _TABLE, list(columns), unique=unique)
        return
    actual = (
        tuple(existing.get("column_names") or ()),
        bool(existing.get("unique")),
    )
    if actual != (columns, unique):
        raise RuntimeError(f"Existing index {name} differs from revision 0026.")


def _seed_existing_cases() -> None:
    op.execute(
        sa.text(
            'INSERT INTO "wallet_case_catalog_events" '
            '(case_id, recorded_at, visible) '
            'SELECT id, updated_at, '
            'CASE WHEN archived_at IS NULL THEN TRUE ELSE FALSE END '
            'FROM "wallet_cases"'
        )
    )


def _validate_seed() -> None:
    bind = op.get_bind()
    missing_or_duplicate = int(
        bind.execute(
            sa.text(
                'SELECT COUNT(*) FROM ('
                'SELECT wc.id FROM "wallet_cases" AS wc '
                'LEFT JOIN "wallet_case_catalog_events" AS event '
                'ON event.case_id = wc.id '
                'GROUP BY wc.id HAVING COUNT(event.id) <> 1'
                ') AS invalid'
            )
        ).scalar_one()
    )
    orphaned = int(
        bind.execute(
            sa.text(
                'SELECT COUNT(*) FROM "wallet_case_catalog_events" AS event '
                'LEFT JOIN "wallet_cases" AS wc ON wc.id = event.case_id '
                'WHERE wc.id IS NULL'
            )
        ).scalar_one()
    )
    if missing_or_duplicate or orphaned:
        raise RuntimeError("Wallet Case catalog event seed validation failed.")


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case catalog event validation requires an online database."
        )
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _REQUIRED_TABLE not in tables:
        raise RuntimeError("Revision 0026 requires the Wallet Case table.")
    existed = _TABLE in tables
    if not existed:
        _create_table()
    else:
        _validate_existing(require_empty=True)
    _ensure_index()
    _seed_existing_cases()
    _validate_existing(require_empty=False)
    _validate_seed()


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case catalog event downgrade would discard stable pagination state "
        "and is intentionally unsupported. Restore a verified backup instead."
    )
