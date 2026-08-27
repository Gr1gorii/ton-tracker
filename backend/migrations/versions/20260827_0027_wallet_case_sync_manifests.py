"""Add immutable Wallet Case sync acquisition manifests.

Revision ID: 20260827_0027
Revises: 20260827_0026
Create Date: 2026-08-27
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260827_0027"
down_revision = "20260827_0026"
branch_labels = None
depends_on = None


_TABLE = "wallet_case_sync_manifests"
_REQUIRED_TABLE = "wallet_case_syncs"
_INDEXES = (
    ("uq_wallet_case_sync_manifests_public_id", ("public_id",), True),
    ("uq_wallet_case_sync_manifests_sync", ("case_sync_id",), True),
)


def _columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(68), nullable=False),
        sa.Column("case_sync_id", sa.Integer(), nullable=False),
        sa.Column(
            "contract_version",
            sa.String(36),
            nullable=False,
            server_default="wallet_case_sync_manifest_v1",
        ),
        sa.Column("content_hash_sha256", sa.String(64), nullable=False),
        sa.Column("manifest_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def _checks() -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "contract_version = 'wallet_case_sync_manifest_v1'",
            name="ck_wallet_case_sync_manifests_contract",
        ),
        sa.CheckConstraint(
            "length(content_hash_sha256) = 64 AND "
            "public_id = 'smf_' || content_hash_sha256",
            name="ck_wallet_case_sync_manifests_identity",
        ),
        sa.CheckConstraint(
            "length(manifest_json) > 2",
            name="ck_wallet_case_sync_manifests_payload",
        ),
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


def _create_table() -> None:
    op.create_table(
        _TABLE,
        *_columns(),
        *_checks(),
        sa.ForeignKeyConstraint(
            ["case_sync_id"],
            ["wallet_case_syncs.id"],
            ondelete="CASCADE",
        ),
    )


def _validate_existing(*, require_empty: bool) -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    actual_columns = tuple(
        _column_signature(item) for item in inspector.get_columns(_TABLE)
    )
    expected_columns = tuple(
        _expected_column_signature(item) for item in _columns()
    )
    if actual_columns != expected_columns:
        raise RuntimeError(
            "Existing Wallet Case sync manifest columns differ from revision 0027."
        )
    foreign_keys = inspector.get_foreign_keys(_TABLE)
    if len(foreign_keys) != 1:
        raise RuntimeError(
            "Existing Wallet Case sync manifest foreign key differs from revision 0027."
        )
    foreign_key = foreign_keys[0]
    if (
        tuple(foreign_key.get("constrained_columns") or ()),
        str(foreign_key.get("referred_table")),
        tuple(foreign_key.get("referred_columns") or ()),
        str((foreign_key.get("options") or {}).get("ondelete", "")).upper(),
    ) != (("case_sync_id",), "wallet_case_syncs", ("id",), "CASCADE"):
        raise RuntimeError(
            "Existing Wallet Case sync manifest foreign key differs from revision 0027."
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
            "Existing Wallet Case sync manifest checks differ from revision 0027."
        )
    if require_empty and int(
        bind.execute(sa.text(f'SELECT COUNT(*) FROM "{_TABLE}"')).scalar_one()
    ):
        raise RuntimeError(
            "Pre-revision Wallet Case sync manifests cannot be adopted by revision 0027."
        )


def _ensure_indexes() -> None:
    for name, columns, unique in _INDEXES:
        indexes = {
            str(item["name"]): item
            for item in sa.inspect(op.get_bind()).get_indexes(_TABLE)
        }
        existing = indexes.get(name)
        if existing is None:
            op.create_index(name, _TABLE, list(columns), unique=unique)
        elif (
            tuple(existing.get("column_names") or ()),
            bool(existing.get("unique")),
        ) != (columns, unique):
            raise RuntimeError(f"Existing index {name} differs from revision 0027.")


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case sync manifest validation requires an online database."
        )
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _REQUIRED_TABLE not in tables:
        raise RuntimeError("Revision 0027 requires the Wallet Case sync table.")
    existed = _TABLE in tables
    if not existed:
        _create_table()
    else:
        _validate_existing(require_empty=True)
    _ensure_indexes()
    _validate_existing(require_empty=False)


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case sync manifest downgrade would discard immutable acquisition "
        "evidence and is intentionally unsupported. Restore a verified backup instead."
    )
