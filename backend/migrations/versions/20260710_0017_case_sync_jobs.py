"""Add durable execution metadata for Wallet Case synchronization jobs.

Revision ID: 20260710_0017
Revises: 20260710_0016
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0017"
down_revision = "20260710_0016"
branch_labels = None
depends_on = None


_SYNCS_TABLE = "wallet_case_syncs"
_BASE_COLUMN_NAMES = (
    "id",
    "public_id",
    "case_id",
    "ingestion_run_id",
    "time_window",
    "data_mode",
    "provider",
    "requested_start",
    "requested_end",
    "requested_surfaces_json",
    "state",
    "stage",
    "progress_current",
    "progress_total",
    "coverage_summary_json",
    "error_code",
    "error_detail_safe",
    "created_at",
    "updated_at",
    "started_at",
    "completed_at",
    "result_summary_json",
    "message_safe",
)
_JOB_COLUMN_NAMES = (
    "status_version",
    "idempotency_key",
    "request_fingerprint",
    "attempt_count",
    "max_attempts",
    "next_attempt_at",
    "cancel_requested_at",
    "lease_token",
    "lease_expires_at",
    "heartbeat_at",
    "checkpoint_json",
)
_INDEXES = (
    (
        "uq_wallet_case_syncs_case_idempotency",
        ("case_id", "idempotency_key"),
        True,
        None,
    ),
    (
        "uq_wallet_case_syncs_one_active",
        ("case_id",),
        True,
        "state IN ('queued', 'running')",
    ),
    (
        "ix_wallet_case_syncs_queue",
        ("state", "next_attempt_at", "created_at", "id"),
        False,
        None,
    ),
)


def _job_columns() -> tuple[sa.Column, ...]:
    """Return fresh columns for restart-safe SQLite additive DDL."""
    return (
        sa.Column(
            "status_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("idempotency_key", sa.String(length=36), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "max_attempts",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("4"),
        ),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("cancel_requested_at", sa.DateTime(), nullable=True),
        sa.Column("lease_token", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.Column(
            "checkpoint_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
    )


def _normalized(value: Any) -> str | None:
    if value is None:
        return None
    return "".join(str(value).upper().split())


def _column_signature(column: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(column.get("name")),
        _normalized(column.get("type")),
        bool(column.get("nullable")),
        _normalized(column.get("default")),
    )


def _expected_default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    argument = column.server_default.arg
    if isinstance(argument, str):
        return _normalized(repr(argument))
    return _normalized(argument.compile(compile_kwargs={"literal_binds": True}))


def _expected_signature(column: sa.Column) -> tuple[Any, ...]:
    return (
        str(column.name),
        _normalized(column.type),
        bool(column.nullable),
        _expected_default(column),
    )


def _reflected_columns() -> list[dict[str, Any]]:
    connection = op.get_bind()
    if _SYNCS_TABLE not in set(sa.inspect(connection).get_table_names()):
        raise RuntimeError(
            "Revision 0017 requires wallet_case_syncs from revision 0016."
        )
    return list(sa.inspect(connection).get_columns(_SYNCS_TABLE))


def _validate_columns(
    reflected: list[dict[str, Any]],
    expected: tuple[sa.Column, ...],
) -> None:
    by_name = {str(column["name"]): column for column in reflected}
    mismatches: list[str] = []
    for column in expected:
        actual = by_name.get(str(column.name))
        if actual is not None and _column_signature(actual) != _expected_signature(column):
            mismatches.append(
                f"{column.name}: expected={_expected_signature(column)}, "
                f"actual={_column_signature(actual)}"
            )
    if mismatches:
        raise RuntimeError(
            "Existing Wallet Case job columns do not match revision 0017: "
            + "; ".join(mismatches)
        )

    names = tuple(str(column["name"]) for column in reflected)
    allowed = {
        _BASE_COLUMN_NAMES + _JOB_COLUMN_NAMES[:count]
        for count in range(len(_JOB_COLUMN_NAMES) + 1)
    }
    if names not in allowed:
        raise RuntimeError(
            "Existing wallet_case_syncs column order/state cannot have been "
            "left by revision 0017."
        )


def _ensure_columns() -> None:
    expected = _job_columns()
    reflected = _reflected_columns()
    _validate_columns(reflected, expected)
    names = {str(column["name"]) for column in reflected}
    for column in expected:
        if column.name not in names:
            op.add_column(_SYNCS_TABLE, column)
    _validate_columns(_reflected_columns(), expected)


def _index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    where = (index.get("dialect_options") or {}).get("sqlite_where")
    normalized_where = " ".join(str(where).split()) if where is not None else None
    return (
        tuple(index.get("column_names") or ()),
        bool(index.get("unique")),
        normalized_where,
    )


def _ensure_indexes() -> None:
    connection = op.get_bind()
    reflected = {
        str(index["name"]): index
        for index in sa.inspect(connection).get_indexes(_SYNCS_TABLE)
    }
    expected_names = {item[0] for item in _INDEXES}
    for name, columns, unique, where in _INDEXES:
        existing = reflected.get(name)
        if existing is None:
            options = {"sqlite_where": sa.text(where)} if where else {}
            op.create_index(
                name,
                _SYNCS_TABLE,
                list(columns),
                unique=unique,
                **options,
            )
            continue
        actual = _index_signature(existing)
        expected = (columns, unique, where)
        if actual != expected:
            raise RuntimeError(
                f"Existing index {name} does not match revision 0017: "
                f"expected={expected}, actual={actual}."
            )

    refreshed_names = {
        str(index["name"])
        for index in sa.inspect(connection).get_indexes(_SYNCS_TABLE)
    }
    missing = sorted(expected_names - refreshed_names)
    if missing:
        raise RuntimeError(
            f"Wallet Case job migration did not create indexes: {missing}."
        )


def _normalize_legacy_active_rows() -> None:
    """Fail closed for pre-0017 states that have no resumable lease contract."""
    op.get_bind().exec_driver_sql(
            "UPDATE wallet_case_syncs "
            "SET state = 'failed', "
            "stage = 'failed', "
            "error_code = 'legacy_sync_not_resumable', "
            "error_detail_safe = "
            "'A pre-0017 active sync cannot be resumed safely.', "
            "message_safe = "
            "'A pre-0017 active sync was closed during migration.', "
            "completed_at = COALESCE(completed_at, CURRENT_TIMESTAMP), "
            "updated_at = CURRENT_TIMESTAMP, "
            "next_attempt_at = NULL, "
            "lease_token = NULL, "
            "lease_expires_at = NULL, "
            "heartbeat_at = NULL, "
            "checkpoint_json = "
            "'{\"version\":\"case_sync_monolithic_v1\","
            "\"phase\":\"legacy_closed\","
            "\"last_error_retryable\":false}', "
            "status_version = status_version + 1 "
            "WHERE state IN ('queued', 'running')"
    )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case job schema validation requires an online database."
    )
    _ensure_columns()
    _normalize_legacy_active_rows()
    _ensure_indexes()


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case job downgrade would discard durable execution state and "
        "is intentionally unsupported. Restore a verified backup instead."
    )
