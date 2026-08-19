"""Add immutable Wallet Case Report revision captures.

Revision ID: 20260710_0023
Revises: 20260710_0022
Create Date: 2026-08-19
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0023"
down_revision = "20260710_0022"
branch_labels = None
depends_on = None


_TABLE = "wallet_case_report_revisions"
_REQUIRED_TABLES = {"wallet_cases", "wallet_case_syncs"}
_INDEXES = (
    ("uq_wallet_case_report_revisions_public_id", ("public_id",), True),
    (
        "uq_wallet_case_report_revisions_case_hash",
        ("case_id", "content_hash_sha256"),
        True,
    ),
    (
        "ix_wallet_case_report_revisions_catalog",
        ("case_id", "id"),
        False,
    ),
    (
        "ix_wallet_case_report_revisions_snapshot",
        ("case_id", "snapshot_sync_id", "id"),
        False,
    ),
)


def _columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(68), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("snapshot_sync_id", sa.Integer(), nullable=False),
        sa.Column(
            "contract_version",
            sa.String(32),
            nullable=False,
            server_default="wallet_case_report_v1",
        ),
        sa.Column("content_hash_sha256", sa.String(64), nullable=False),
        sa.Column("assurance_level", sa.String(24), nullable=False),
        sa.Column("activity_digest_sha256", sa.String(64), nullable=False),
        sa.Column("evidence_digest_sha256", sa.String(64), nullable=False),
        sa.Column("report_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def _checks() -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "contract_version = 'wallet_case_report_v1'",
            name="ck_wallet_case_report_revisions_contract",
        ),
        sa.CheckConstraint(
            "assurance_level IN ('observed', 'normalized', "
            "'partially_verified', 'canonical')",
            name="ck_wallet_case_report_revisions_assurance",
        ),
        sa.CheckConstraint(
            "length(content_hash_sha256) = 64 AND "
            "public_id = 'rpt_' || content_hash_sha256",
            name="ck_wallet_case_report_revisions_identity",
        ),
        sa.CheckConstraint(
            "length(activity_digest_sha256) = 64 AND "
            "length(evidence_digest_sha256) = 64",
            name="ck_wallet_case_report_revisions_digests",
        ),
        sa.CheckConstraint(
            "length(report_json) > 2",
            name="ck_wallet_case_report_revisions_payload",
        ),
    )


def _create_table() -> None:
    op.create_table(
        _TABLE,
        *_columns(),
        *_checks(),
        sa.ForeignKeyConstraint(
            ["case_id"], ["wallet_cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_sync_id"], ["wallet_case_syncs.id"], ondelete="CASCADE"
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
            "Existing Wallet Case Report revision columns differ from revision 0023."
        )
    foreign_keys = {
        (
            tuple(item.get("constrained_columns") or ()),
            item.get("referred_table"),
            tuple(item.get("referred_columns") or ()),
            (item.get("options") or {}).get("ondelete"),
        )
        for item in inspector.get_foreign_keys(_TABLE)
    }
    if foreign_keys != {
        (("case_id",), "wallet_cases", ("id",), "CASCADE"),
        (("snapshot_sync_id",), "wallet_case_syncs", ("id",), "CASCADE"),
    }:
        raise RuntimeError(
            "Existing Wallet Case Report revision foreign keys differ from 0023."
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
            "Existing Wallet Case Report revision checks differ from 0023."
        )
    if require_empty and int(
        bind.execute(sa.text(f'SELECT COUNT(*) FROM "{_TABLE}"')).scalar_one()
    ) != 0:
        raise RuntimeError(
            "Pre-revision Wallet Case Report rows cannot be adopted by revision 0023."
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
            raise RuntimeError(f"Existing index {name} differs from revision 0023.")


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case Report revision validation requires an online database."
        )
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    missing = sorted(_REQUIRED_TABLES - tables)
    if missing:
        raise RuntimeError(f"Revision 0023 requires Wallet Case tables: {missing}.")
    existed = _TABLE in tables
    if not existed:
        _create_table()
    else:
        _validate_existing(require_empty=True)
    _ensure_indexes()
    _validate_existing(require_empty=existed)


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case Report revision downgrade would discard captured public reports "
        "and is intentionally unsupported. Restore a verified backup instead."
    )
