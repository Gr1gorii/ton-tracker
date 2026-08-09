"""Add compact Wallet Case sync result fields.

Revision ID: 20260710_0016
Revises: 20260710_0015
Create Date: 2026-08-09
"""

from __future__ import annotations

from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0016"
down_revision = "20260710_0015"
branch_labels = None
depends_on = None


_SYNCS_TABLE = "wallet_case_syncs"
_BASE_SYNC_COLUMN_NAMES = (
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
)
_COMPACT_RESULT_COLUMN_NAMES = ("result_summary_json", "message_safe")
_LEGACY_RESULT_MESSAGE = (
    "Compact activity and portfolio summary is unavailable for this "
    "pre-0016 synchronization. Zero placeholders are not evidence of no activity."
)


def _compact_result_columns() -> tuple[sa.Column, ...]:
    """Return fresh columns for restart-safe SQLite additive DDL."""
    return (
        sa.Column(
            "result_summary_json",
            sa.Text(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "message_safe",
            sa.Text(),
            nullable=False,
            server_default="",
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
    argument = column.server_default.arg
    if isinstance(argument, str):
        return _default_signature(repr(argument))
    return _default_signature(
        argument.compile(compile_kwargs={"literal_binds": True})
    )


def _column_signature(column: dict[str, Any]) -> tuple[str, str, bool, str | None]:
    return (
        str(column.get("name")),
        _type_signature(column.get("type")),
        bool(column.get("nullable")),
        _default_signature(column.get("default")),
    )


def _expected_column_signature(
    column: sa.Column,
) -> tuple[str, str, bool, str | None]:
    return (
        str(column.name),
        _type_signature(column.type),
        bool(column.nullable),
        _expected_default(column),
    )


def _reflected_columns() -> list[dict[str, Any]]:
    connection = op.get_bind()
    tables = set(sa.inspect(connection).get_table_names())
    if _SYNCS_TABLE not in tables:
        raise RuntimeError(
            "Revision 0016 requires the wallet_case_syncs table from revision 0015."
        )
    return list(sa.inspect(connection).get_columns(_SYNCS_TABLE))


def _validate_existing_columns(
    reflected: list[dict[str, Any]],
    expected: tuple[sa.Column, ...],
) -> None:
    reflected_by_name = {
        str(column["name"]): column for column in reflected
    }
    mismatches: list[str] = []
    for column in expected:
        actual = reflected_by_name.get(str(column.name))
        if actual is None:
            continue
        expected_signature = _expected_column_signature(column)
        actual_signature = _column_signature(actual)
        if actual_signature != expected_signature:
            mismatches.append(
                f"{column.name}: expected={expected_signature}, "
                f"actual={actual_signature}"
            )
    if mismatches:
        raise RuntimeError(
            "Existing wallet_case_syncs compact-result columns do not match "
            "revision 0016: " + "; ".join(mismatches)
        )

    names = tuple(str(column["name"]) for column in reflected)
    allowed_states = {
        _BASE_SYNC_COLUMN_NAMES,
        _BASE_SYNC_COLUMN_NAMES + _COMPACT_RESULT_COLUMN_NAMES[:1],
        _BASE_SYNC_COLUMN_NAMES + _COMPACT_RESULT_COLUMN_NAMES,
    }
    if names not in allowed_states:
        raise RuntimeError(
            "Existing wallet_case_syncs column order/state cannot have been "
            "left by revision 0016."
        )


def _ensure_columns() -> None:
    expected = _compact_result_columns()
    reflected = _reflected_columns()

    # Validate every surviving fragment before making another SQLite DDL change.
    _validate_existing_columns(reflected, expected)
    reflected_names = {str(column["name"]) for column in reflected}
    for column in expected:
        if column.name not in reflected_names:
            op.add_column(_SYNCS_TABLE, column)

    refreshed = _reflected_columns()
    refreshed_names = {str(column["name"]) for column in refreshed}
    missing = [
        column.name for column in expected if column.name not in refreshed_names
    ]
    if missing:
        raise RuntimeError(
            "Wallet Case compact-result migration did not add expected columns: "
            f"{missing}."
        )
    _validate_existing_columns(refreshed, expected)


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet Case compact-result schema validation requires an online "
            "database connection; offline SQL generation is unsupported."
        )

    # SQLite can retain an ADD COLUMN after an interrupted Alembic transaction.
    # Accept only exact column fragments from this revision and add what is missing.
    _ensure_columns()
    # Revision 0015 did not persist bounded summary/message provenance. Mark
    # those pre-existing rows explicitly instead of presenting default zeros as
    # evidence that no activity occurred. This update is restart-idempotent.
    op.execute(
        sa.text(
            "UPDATE wallet_case_syncs "
            "SET message_safe = :legacy_message "
            "WHERE result_summary_json = '{}' AND message_safe = ''"
        ).bindparams(legacy_message=_LEGACY_RESULT_MESSAGE)
    )


def downgrade() -> None:
    raise RuntimeError(
        "Wallet Case compact-result downgrade would discard durable summaries "
        "and safe result messages and is intentionally unsupported. Restore a "
        "verified backup instead."
    )
