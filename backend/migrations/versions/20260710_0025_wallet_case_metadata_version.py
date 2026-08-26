"""Add optimistic concurrency versioning to Wallet Case metadata.

Revision ID: 20260710_0025
Revises: 20260710_0024
Create Date: 2026-08-26
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0025"
down_revision = "20260710_0024"
branch_labels = None
depends_on = None


_TABLE = "wallet_cases"
_COLUMN = sa.Column(
    "metadata_version",
    sa.Integer(),
    nullable=False,
    server_default="1",
)


def _normalize(value: Any) -> str | None:
    return None if value is None else "".join(str(value).upper().split())


def _default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    value = column.server_default.arg
    if isinstance(value, str):
        return _normalize(repr(value))
    return _normalize(value.compile(compile_kwargs={"literal_binds": True}))


def _validate_existing() -> None:
    bind = op.get_bind()
    columns = {
        str(column["name"]): column
        for column in sa.inspect(bind).get_columns(_TABLE)
    }
    column = columns.get(str(_COLUMN.name))
    if column is None:
        raise RuntimeError("Wallet Case metadata version column is missing.")
    actual = (
        _normalize(column.get("type")),
        bool(column.get("nullable")),
        _normalize(column.get("default")),
    )
    expected = (
        _normalize(_COLUMN.type),
        bool(_COLUMN.nullable),
        _default(_COLUMN),
    )
    if actual != expected:
        raise RuntimeError(
            "Existing Wallet Case metadata version differs from revision 0025."
        )
    invalid = int(
        bind.execute(
            sa.text(
                'SELECT COUNT(*) FROM "wallet_cases" '
                'WHERE "metadata_version" IS NULL OR "metadata_version" < 1'
            )
        ).scalar_one()
    )
    if invalid:
        raise RuntimeError(
            "Existing Wallet Case metadata versions cannot be adopted by revision 0025."
        )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case metadata version validation requires an online database."
        )
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        raise RuntimeError("Revision 0025 requires the Wallet Case table.")
    columns = {str(column["name"]) for column in inspector.get_columns(_TABLE)}
    if str(_COLUMN.name) not in columns:
        op.add_column(_TABLE, _COLUMN)
    _validate_existing()


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case metadata version downgrade would remove concurrency state "
        "and is intentionally unsupported. Restore a verified backup instead."
    )
