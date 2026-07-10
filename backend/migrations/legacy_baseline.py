"""Frozen v0.22.0 schema manifest for safe legacy database adoption.

The manifest is intentionally independent from ``models.py``. Future model
changes must not change what qualifies as the one legacy schema that may be
stamped at the baseline revision.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError


BASELINE_REVISION = "20260710_0001"


_LEGACY_SCHEMA: dict[str, dict[str, Any]] = {
    "analysis_runs": {
        "columns": (
            ("id", "INTEGER", False, None),
            ("pool_url", "VARCHAR", False, None),
            ("time_window", "VARCHAR", False, None),
            ("created_at", "DATETIME", False, None),
            ("result_json", "TEXT", False, None),
        ),
        "pk": ("id",),
        "pk_name": None,
        "fks": (),
        "indexes": (
            ("ix_analysis_runs_id", ("id",), False),
        ),
    },
    "wallet_ingestion_runs": {
        "columns": (
            ("id", "INTEGER", False, None),
            ("wallet_address", "VARCHAR", False, None),
            ("time_window", "VARCHAR", False, None),
            ("custom_start", "DATETIME", True, None),
            ("custom_end", "DATETIME", True, None),
            ("data_mode", "VARCHAR", False, None),
            ("status", "VARCHAR", False, None),
            ("requested_surfaces_json", "TEXT", False, None),
            ("provider_summary_json", "TEXT", False, None),
            ("created_at", "DATETIME", False, None),
            ("updated_at", "DATETIME", False, None),
        ),
        "pk": ("id",),
        "pk_name": None,
        "fks": (),
        "indexes": (
            ("ix_wallet_ingestion_runs_id", ("id",), False),
            (
                "ix_wallet_ingestion_runs_wallet_address",
                ("wallet_address",),
                False,
            ),
        ),
    },
    "wallet_transfers": {
        "columns": (
            ("id", "INTEGER", False, None),
            ("run_id", "INTEGER", False, None),
            ("tx_hash", "VARCHAR", True, None),
            ("logical_time", "VARCHAR", True, None),
            ("timestamp", "DATETIME", True, None),
            ("asset", "VARCHAR", False, None),
            ("amount", "NUMERIC(38,18)", True, None),
            ("direction", "VARCHAR", False, None),
            ("counterparty", "VARCHAR", True, None),
            ("provider", "VARCHAR", False, None),
            ("source_status", "VARCHAR", False, None),
            ("raw_json", "TEXT", True, None),
        ),
        "pk": ("id",),
        "pk_name": None,
        "fks": (
            (("run_id",), None, "wallet_ingestion_runs", ("id",), ()),
        ),
        "indexes": (
            ("ix_wallet_transfers_id", ("id",), False),
            ("ix_wallet_transfers_logical_time", ("logical_time",), False),
            ("ix_wallet_transfers_run_id", ("run_id",), False),
            ("ix_wallet_transfers_tx_hash", ("tx_hash",), False),
        ),
    },
    "wallet_transactions": {
        "columns": (
            ("id", "INTEGER", False, None),
            ("run_id", "INTEGER", False, None),
            ("tx_hash", "VARCHAR", False, None),
            ("logical_time", "VARCHAR", True, None),
            ("timestamp", "DATETIME", True, None),
            ("fee_ton", "NUMERIC(38,18)", True, None),
            ("success", "VARCHAR", False, None),
            ("provider", "VARCHAR", False, None),
            ("source_status", "VARCHAR", False, None),
            ("raw_json", "TEXT", True, None),
        ),
        "pk": ("id",),
        "pk_name": None,
        "fks": (
            (("run_id",), None, "wallet_ingestion_runs", ("id",), ()),
        ),
        "indexes": (
            ("ix_wallet_transactions_id", ("id",), False),
            (
                "ix_wallet_transactions_logical_time",
                ("logical_time",),
                False,
            ),
            ("ix_wallet_transactions_run_id", ("run_id",), False),
            ("ix_wallet_transactions_tx_hash", ("tx_hash",), False),
        ),
    },
    "wallet_swaps": {
        "columns": (
            ("id", "INTEGER", False, None),
            ("run_id", "INTEGER", False, None),
            ("tx_hash", "VARCHAR", True, None),
            ("timestamp", "DATETIME", True, None),
            ("dex", "VARCHAR", True, None),
            ("token_in", "VARCHAR", True, None),
            ("amount_in", "NUMERIC(38,18)", True, None),
            ("token_out", "VARCHAR", True, None),
            ("amount_out", "NUMERIC(38,18)", True, None),
            ("estimated_usd", "NUMERIC(24,8)", True, None),
            ("provider", "VARCHAR", False, None),
            ("source_status", "VARCHAR", False, None),
            ("raw_json", "TEXT", True, None),
        ),
        "pk": ("id",),
        "pk_name": None,
        "fks": (
            (("run_id",), None, "wallet_ingestion_runs", ("id",), ()),
        ),
        "indexes": (
            ("ix_wallet_swaps_id", ("id",), False),
            ("ix_wallet_swaps_run_id", ("run_id",), False),
            ("ix_wallet_swaps_tx_hash", ("tx_hash",), False),
        ),
    },
    "wallet_balance_snapshots": {
        "columns": (
            ("id", "INTEGER", False, None),
            ("run_id", "INTEGER", False, None),
            ("asset", "VARCHAR", False, None),
            ("balance", "NUMERIC(38,18)", True, None),
            ("balance_usd", "NUMERIC(24,8)", True, None),
            ("provider", "VARCHAR", False, None),
            ("source_status", "VARCHAR", False, None),
            ("snapshot_at", "DATETIME", True, None),
            ("raw_json", "TEXT", True, None),
        ),
        "pk": ("id",),
        "pk_name": None,
        "fks": (
            (("run_id",), None, "wallet_ingestion_runs", ("id",), ()),
        ),
        "indexes": (
            ("ix_wallet_balance_snapshots_id", ("id",), False),
            ("ix_wallet_balance_snapshots_run_id", ("run_id",), False),
        ),
    },
    "wallet_ingestion_warnings": {
        "columns": (
            ("id", "INTEGER", False, None),
            ("run_id", "INTEGER", False, None),
            ("severity", "VARCHAR", False, None),
            ("provider", "VARCHAR", True, None),
            ("message", "TEXT", False, None),
            ("evidence_key", "VARCHAR", True, None),
            ("created_at", "DATETIME", False, None),
        ),
        "pk": ("id",),
        "pk_name": None,
        "fks": (
            (("run_id",), None, "wallet_ingestion_runs", ("id",), ()),
        ),
        "indexes": (
            ("ix_wallet_ingestion_warnings_id", ("id",), False),
            ("ix_wallet_ingestion_warnings_run_id", ("run_id",), False),
        ),
    },
}

DOMAIN_TABLES = frozenset(_LEGACY_SCHEMA)


def _type_signature(value: Any) -> str:
    return "".join(str(value).upper().split())


def _column_signature(column: dict[str, Any]) -> tuple[str, str, bool, Any]:
    return (
        str(column.get("name")),
        _type_signature(column.get("type")),
        bool(column.get("nullable")),
        column.get("default"),
    )


def _options_signature(options: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted((str(key), str(value)) for key, value in (options or {}).items())
    )


def _foreign_key_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        tuple(item.get("constrained_columns") or ()),
        item.get("referred_schema"),
        item.get("referred_table"),
        tuple(item.get("referred_columns") or ()),
        _options_signature(item.get("options")),
    )


def _index_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("name"),
        tuple(item.get("column_names") or ()),
        bool(item.get("unique")),
    )


def _unique_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    return (
        item.get("name"),
        tuple(item.get("column_names") or ()),
    )


def _check_signature(item: dict[str, Any]) -> tuple[Any, ...]:
    return (item.get("name"), item.get("sqltext"))


def _sorted_signatures(items: Any) -> tuple[Any, ...]:
    """Sort reflected signatures even when optional names mix None and text."""
    return tuple(sorted(items, key=repr))


def validate_legacy_schema(connection: Connection) -> list[str]:
    """Return deterministic mismatches against the frozen v0.22.0 schema.

    Reflection is read-only. Tables outside ``DOMAIN_TABLES`` are deliberately
    ignored so an application database may coexist with unrelated user tables.
    """
    mismatches: list[str] = []
    schema_inspector = inspect(connection)

    try:
        actual_tables = set(schema_inspector.get_table_names())
    except SQLAlchemyError as exc:
        return [
            "Could not inspect database tables: "
            f"{exc.__class__.__name__}: {exc}"
        ]

    missing_tables = sorted(DOMAIN_TABLES - actual_tables)
    if missing_tables:
        mismatches.append(f"Missing domain tables: {missing_tables!r}")

    for table_name in sorted(DOMAIN_TABLES & actual_tables):
        expected = _LEGACY_SCHEMA[table_name]
        try:
            actual_columns = tuple(
                _column_signature(item)
                for item in schema_inspector.get_columns(table_name)
            )
            actual_pk_record = schema_inspector.get_pk_constraint(table_name)
            actual_pk = tuple(actual_pk_record.get("constrained_columns") or ())
            actual_pk_name = actual_pk_record.get("name")
            actual_fks = _sorted_signatures(
                _foreign_key_signature(item)
                for item in schema_inspector.get_foreign_keys(table_name)
            )
            actual_indexes = _sorted_signatures(
                _index_signature(item)
                for item in schema_inspector.get_indexes(table_name)
            )
            actual_uniques = _sorted_signatures(
                _unique_signature(item)
                for item in schema_inspector.get_unique_constraints(table_name)
            )
            actual_checks = _sorted_signatures(
                _check_signature(item)
                for item in schema_inspector.get_check_constraints(table_name)
            )
        except SQLAlchemyError as exc:
            mismatches.append(
                f"{table_name}: reflection failed with "
                f"{exc.__class__.__name__}: {exc}"
            )
            continue

        if actual_columns != expected["columns"]:
            mismatches.append(
                f"{table_name}: columns differ; expected "
                f"{expected['columns']!r}, found {actual_columns!r}"
            )
        if actual_pk != expected["pk"] or actual_pk_name != expected["pk_name"]:
            mismatches.append(
                f"{table_name}: primary key differs; expected "
                f"({expected['pk']!r}, {expected['pk_name']!r}), found "
                f"({actual_pk!r}, {actual_pk_name!r})"
            )
        if actual_fks != expected["fks"]:
            mismatches.append(
                f"{table_name}: foreign keys differ; expected "
                f"{expected['fks']!r}, found {actual_fks!r}"
            )
        if actual_indexes != expected["indexes"]:
            mismatches.append(
                f"{table_name}: indexes differ; expected "
                f"{expected['indexes']!r}, found {actual_indexes!r}"
            )
        if actual_uniques:
            mismatches.append(
                f"{table_name}: unexpected unique constraints {actual_uniques!r}"
            )
        if actual_checks:
            mismatches.append(
                f"{table_name}: unexpected check constraints {actual_checks!r}"
            )

    return mismatches
