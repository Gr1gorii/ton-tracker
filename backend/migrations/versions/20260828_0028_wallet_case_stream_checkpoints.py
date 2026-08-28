"""Add immutable Wallet Case provider-stream checkpoints.

Revision ID: 20260828_0028
Revises: 20260827_0027
Create Date: 2026-08-28
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260828_0028"
down_revision = "20260827_0027"
branch_labels = None
depends_on = None


_TABLE = "wallet_case_stream_checkpoints"
_REQUIRED_TABLES = {"wallet_cases", "wallet_case_syncs"}
_INDEXES = (
    ("uq_wallet_case_stream_checkpoints_public_id", ("public_id",), True),
    (
        "uq_wallet_case_stream_checkpoints_source_stream",
        ("source_sync_id", "provider", "stream_key"),
        True,
    ),
    (
        "ix_wallet_case_stream_checkpoints_case_stream",
        ("case_id", "provider", "stream_key", "id"),
        False,
    ),
)


def _columns() -> tuple[sa.Column, ...]:
    return (
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("public_id", sa.String(68), nullable=False),
        sa.Column("case_id", sa.Integer(), nullable=False),
        sa.Column("source_sync_id", sa.Integer(), nullable=False),
        sa.Column(
            "contract_version",
            sa.String(40),
            nullable=False,
            server_default="wallet_case_stream_checkpoint_v1",
        ),
        sa.Column("provider", sa.String(64), nullable=False),
        sa.Column("stream_key", sa.String(40), nullable=False),
        sa.Column("provider_contract_version", sa.String(48), nullable=False),
        sa.Column("resume_state", sa.String(16), nullable=False),
        sa.Column("continuation_cursor", sa.String(128), nullable=True),
        sa.Column("continuation_page_index", sa.Integer(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("pages_succeeded", sa.Integer(), nullable=False),
        sa.Column("checkpoint_hash_sha256", sa.String(64), nullable=False),
        sa.Column("checkpoint_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )


def _checks() -> tuple[sa.CheckConstraint, ...]:
    return (
        sa.CheckConstraint(
            "contract_version = 'wallet_case_stream_checkpoint_v1'",
            name="ck_wallet_case_stream_checkpoints_contract",
        ),
        sa.CheckConstraint(
            "length(checkpoint_hash_sha256) = 64 AND "
            "public_id = 'scp_' || checkpoint_hash_sha256",
            name="ck_wallet_case_stream_checkpoints_identity",
        ),
        sa.CheckConstraint(
            "resume_state IN ('ready', 'complete', 'blocked')",
            name="ck_wallet_case_stream_checkpoints_resume_state",
        ),
        sa.CheckConstraint(
            "page_count >= 0 AND pages_succeeded >= 0 AND "
            "pages_succeeded <= page_count",
            name="ck_wallet_case_stream_checkpoints_pages",
        ),
        sa.CheckConstraint(
            "(resume_state = 'ready' AND continuation_cursor IS NOT NULL AND "
            "continuation_page_index IS NOT NULL AND continuation_page_index >= 1) "
            "OR (resume_state IN ('complete', 'blocked') AND "
            "continuation_cursor IS NULL AND continuation_page_index IS NULL)",
            name="ck_wallet_case_stream_checkpoints_continuation",
        ),
        sa.CheckConstraint(
            "length(checkpoint_json) > 2",
            name="ck_wallet_case_stream_checkpoints_payload",
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
            ["case_id"], ["wallet_cases.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_sync_id"], ["wallet_case_syncs.id"], ondelete="CASCADE"
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
            "Existing Wallet Case stream checkpoint columns differ from revision 0028."
        )
    foreign_keys = {
        (
            tuple(item.get("constrained_columns") or ()),
            str(item.get("referred_table")),
            tuple(item.get("referred_columns") or ()),
            str((item.get("options") or {}).get("ondelete", "")).upper(),
        )
        for item in inspector.get_foreign_keys(_TABLE)
    }
    if foreign_keys != {
        (("case_id",), "wallet_cases", ("id",), "CASCADE"),
        (("source_sync_id",), "wallet_case_syncs", ("id",), "CASCADE"),
    }:
        raise RuntimeError(
            "Existing Wallet Case stream checkpoint foreign keys differ from revision 0028."
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
            "Existing Wallet Case stream checkpoint checks differ from revision 0028."
        )
    if require_empty and int(
        bind.execute(sa.text(f'SELECT COUNT(*) FROM "{_TABLE}"')).scalar_one()
    ):
        raise RuntimeError(
            "Pre-revision Wallet Case stream checkpoints cannot be adopted by revision 0028."
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
            raise RuntimeError(f"Existing index {name} differs from revision 0028.")


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case stream checkpoint validation requires an online database."
        )
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    missing = _REQUIRED_TABLES - tables
    if missing:
        raise RuntimeError(
            "Revision 0028 requires Wallet Case and sync tables."
        )
    existed = _TABLE in tables
    if not existed:
        _create_table()
    else:
        _validate_existing(require_empty=True)
    _ensure_indexes()
    _validate_existing(require_empty=False)


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case stream checkpoint downgrade would discard immutable "
        "continuation evidence and is intentionally unsupported. Restore a "
        "verified backup instead."
    )
