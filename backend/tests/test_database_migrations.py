"""Migration-runner tests for fresh and legacy SQLite databases."""

from __future__ import annotations

import importlib
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import Column, Integer, MetaData, Table, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateTable

import database
import models  # noqa: F401 - register every table on database.Base.metadata
from main import app
from migrations.legacy_baseline import BASELINE_REVISION
from services.database_migrations import (
    MigrationBootstrapError,
    MigrationReport,
    _config as migration_config,
    run_database_migrations,
)


LEGACY_FIXTURE = Path(__file__).parent / "fixtures" / "legacy_v0_22_0.sql"
DOMAIN_TABLES = tuple(sorted(database.Base.metadata.tables))
WALLET_IDENTITY_REVISION = "20260710_0002"
TRANSACTION_IDENTITY_REVISION = "20260710_0003"
ACQUISITION_EVIDENCE_REVISION = "20260710_0004"
EVENT_ACTION_IDENTITY_REVISION = "20260710_0005"
TRACE_EVIDENCE_REVISION = "20260710_0006"
TRACE_BOC_VERIFICATION_REVISION = "20260710_0007"
NATIVE_ACTIVITY_LEDGER_REVISION = "20260710_0008"
JETTON_CONTRACT_VERIFICATION_REVISION = "20260710_0009"
WALLET_OWNERSHIP_CHALLENGE_REVISION = "20260710_0010"
ACCOUNT_STATE_INCLUSION_REVISION = "20260710_0011"
TRANSACTION_INCLUSION_REVISION = "20260710_0012"
DEX_PROTOCOL_IDENTITY_REVISION = "20260710_0013"
OWNERSHIP_NETWORK_SCOPE_REVISION = "20260710_0014"
WALLET_CASES_REVISION = "20260710_0015"
WALLET_CASE_COMPACT_RESULTS_REVISION = "20260710_0016"
CASE_SYNC_JOBS_REVISION = "20260710_0017"
CASE_ACTIVITY_INDEXES_REVISION = "20260710_0018"
CASE_EVIDENCE_VERIFICATIONS_REVISION = "20260710_0019"
TRANSACTION_INCLUSION_TRUST_REVISION = "20260710_0020"
TRANSACTION_INCLUSION_CHECKPOINT_REVISION = "20260710_0021"
STRICT_TRANSACTION_INCLUSION_POLICY_REVISION = "20260710_0022"
CASE_REPORT_REVISIONS_REVISION = "20260710_0023"
WALLET_CASE_LIFECYCLE_REVISION = "20260710_0024"
CURRENT_REVISION = WALLET_CASE_LIFECYCLE_REVISION

ACQUISITION_STREAMS_TABLE = "wallet_acquisition_streams"
ACQUISITION_PAGES_TABLE = "wallet_acquisition_pages"
TRACE_CAPTURES_TABLE = "wallet_trace_evidence_captures"
TRACE_NODES_TABLE = "wallet_trace_evidence_nodes"
TRACE_MESSAGES_TABLE = "wallet_trace_evidence_messages"
TRACE_BOC_VERIFICATIONS_TABLE = "wallet_trace_boc_verifications"
TRACE_BOC_TRANSACTIONS_TABLE = "wallet_trace_boc_transactions"
JETTON_CONTRACT_VERIFICATIONS_TABLE = (
    "wallet_jetton_contract_verifications"
)
WALLET_CASES_TABLE = "wallet_cases"
WALLET_CASE_SYNCS_TABLE = "wallet_case_syncs"
CASE_EVIDENCE_VERIFICATIONS_TABLE = "wallet_case_evidence_verifications"
CASE_SYNC_JOB_PARTIAL_COLUMNS = (
    "status_version INTEGER DEFAULT 1 NOT NULL",
    "idempotency_key VARCHAR(36)",
    "request_fingerprint VARCHAR(64)",
    "attempt_count INTEGER DEFAULT 0 NOT NULL",
    "max_attempts INTEGER DEFAULT 4 NOT NULL",
    "next_attempt_at DATETIME",
    "cancel_requested_at DATETIME",
    "lease_token VARCHAR(64)",
    "lease_expires_at DATETIME",
    "heartbeat_at DATETIME",
    "checkpoint_json TEXT DEFAULT '{}' NOT NULL",
)

WALLET_CASE_CHECKS = {
    (
        "ck_wallet_cases_network",
        "network IN ('ton-mainnet', 'ton-testnet')",
    ),
    (
        "ck_wallet_cases_data_environment",
        "data_environment IN ('demo', 'live')",
    ),
}
WALLET_CASE_SYNC_CHECKS = {
    (
        "ck_wallet_case_syncs_time_window",
        "time_window IN ('24h', '3d', '7d', 'custom')",
    ),
    (
        "ck_wallet_case_syncs_data_mode",
        "data_mode IN ('mock', 'real')",
    ),
    (
        "ck_wallet_case_syncs_state",
        "state IN ('queued', 'running', 'partial', 'succeeded', 'failed', 'cancelled')",
    ),
    (
        "ck_wallet_case_syncs_requested_bounds",
        "requested_start < requested_end",
    ),
    (
        "ck_wallet_case_syncs_progress_current",
        "progress_current >= 0",
    ),
    (
        "ck_wallet_case_syncs_progress_total",
        "progress_total IS NULL OR progress_total >= 0",
    ),
    (
        "ck_wallet_case_syncs_progress_bounds",
        "progress_total IS NULL OR progress_current <= progress_total",
    ),
}

ACCOUNT_ID = "ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e"
RAW_ADDRESS = f"0:{ACCOUNT_ID}"
BOUNCEABLE_MAINNET = "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF"
NON_BOUNCEABLE_MAINNET = "UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA"
BOUNCEABLE_TESTNET = "kQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPgpP"
INVALID_CHECKSUM = "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHG"

PRE_0002_COLUMNS: dict[str, tuple[str, ...]] = {
    "analysis_runs": (
        "id",
        "pool_url",
        "time_window",
        "created_at",
        "result_json",
    ),
    "wallet_ingestion_runs": (
        "id",
        "wallet_address",
        "time_window",
        "custom_start",
        "custom_end",
        "data_mode",
        "status",
        "requested_surfaces_json",
        "provider_summary_json",
        "created_at",
        "updated_at",
    ),
    "wallet_transfers": (
        "id",
        "run_id",
        "tx_hash",
        "logical_time",
        "timestamp",
        "asset",
        "amount",
        "direction",
        "counterparty",
        "provider",
        "source_status",
        "raw_json",
    ),
    "wallet_transactions": (
        "id",
        "run_id",
        "tx_hash",
        "logical_time",
        "timestamp",
        "fee_ton",
        "success",
        "provider",
        "source_status",
        "raw_json",
    ),
    "wallet_swaps": (
        "id",
        "run_id",
        "tx_hash",
        "timestamp",
        "dex",
        "token_in",
        "amount_in",
        "token_out",
        "amount_out",
        "estimated_usd",
        "provider",
        "source_status",
        "raw_json",
    ),
    "wallet_balance_snapshots": (
        "id",
        "run_id",
        "asset",
        "balance",
        "balance_usd",
        "provider",
        "source_status",
        "snapshot_at",
        "raw_json",
    ),
    "wallet_ingestion_warnings": (
        "id",
        "run_id",
        "severity",
        "provider",
        "message",
        "evidence_key",
        "created_at",
    ),
}

IDENTITY_COLUMNS = (
    "wallet_identity_status",
    "wallet_identity_version",
    "wallet_network",
    "wallet_address_canonical",
    "wallet_workchain_id",
    "wallet_account_id_hex",
    "wallet_address_format",
    "wallet_address_bounceable",
    "wallet_address_testnet_only",
)

TRANSACTION_IDENTITY_COLUMNS = (
    "transaction_identity_status",
    "transaction_identity_version",
    "transaction_network",
    "transaction_account_canonical",
    "transaction_logical_time_canonical",
    "transaction_hash_canonical",
    "transaction_identity_key",
)

EVENT_ACTION_IDENTITY_COLUMNS = (
    "event_action_identity_status",
    "event_action_identity_version",
    "event_action_network",
    "event_action_account_canonical",
    "event_action_event_id_canonical",
    "event_action_logical_time_canonical",
    "event_action_index",
    "event_action_type",
    "event_action_identity_key",
)

EVENT_ACTION_IDENTITY_COLUMN_DEFINITIONS = (
    "event_action_identity_status VARCHAR(20) DEFAULT 'unavailable' NOT NULL",
    "event_action_identity_version VARCHAR(32) DEFAULT 'unavailable' NOT NULL",
    "event_action_network VARCHAR(16) DEFAULT 'ton-unknown' NOT NULL",
    "event_action_account_canonical VARCHAR(76)",
    "event_action_event_id_canonical VARCHAR(64)",
    "event_action_logical_time_canonical VARCHAR(20)",
    "event_action_index INTEGER",
    "event_action_type VARCHAR(32)",
    "event_action_identity_key VARCHAR(256)",
)

TRANSACTION_HASH = "cd" * 32
SECOND_TRANSACTION_HASH = "ef" * 32
TRANSACTION_LT = "89089355000001"
TRANSACTION_IDENTITY_VERSION = "ton_account_tx_v1"
EVENT_ACTION_ID = "ab" * 32
SECOND_EVENT_ACTION_ID = "12" * 32
EVENT_ACTION_LT = "89089355000002"
EVENT_ACTION_IDENTITY_VERSION = "tonapi_event_action_obs_v1"


def _engine(path: Path) -> Engine:
    return database.create_database_engine(f"sqlite:///{path}")


def _wallet_case_values(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "network": "ton-mainnet",
        "data_environment": "live",
        "canonical_wallet_key": RAW_ADDRESS,
        "canonical_identity_version": "ton_account_v1",
        "display_address": BOUNCEABLE_MAINNET,
    }
    values.update(overrides)
    return values


def _wallet_case_sync_values(case_id: int, **overrides: Any) -> dict[str, Any]:
    requested_start = datetime(2026, 8, 8, tzinfo=timezone.utc)
    values: dict[str, Any] = {
        "case_id": case_id,
        "time_window": "24h",
        "data_mode": "real",
        "provider": "tonapi",
        "requested_start": requested_start,
        "requested_end": requested_start + timedelta(days=1),
        "progress_total": 1,
    }
    values.update(overrides)
    return values


def _upgrade_to_revision(engine: Engine, revision: str) -> None:
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), revision)


def _create_model_table_without_indexes(connection, table_name: str) -> None:
    table = database.Base.metadata.tables[table_name]
    connection.execute(CreateTable(table))


def _create_wallet_case_sync_0015_without_indexes(connection) -> None:
    """Create the frozen 0015 sync table while current models target 0016."""
    migration = importlib.import_module(
        "migrations.versions.20260710_0015_wallet_cases"
    )
    metadata = MetaData()
    Table("wallet_cases", metadata, Column("id", Integer, primary_key=True))
    Table(
        "wallet_ingestion_runs",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    table = Table(
        WALLET_CASE_SYNCS_TABLE,
        metadata,
        *migration._sync_columns(),
        *migration._constraints(migration._SYNC_CHECKS),
    )
    connection.execute(CreateTable(table))


def _rewrite_table_sql(
    engine: Engine,
    table_name: str,
    old: str,
    new: str,
) -> None:
    """Inject deterministic SQLite schema drift without changing table data."""
    with engine.begin() as connection:
        schema_sql = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).scalar_one()
        assert old in schema_sql
        rewritten = schema_sql.replace(old, new, 1)
        connection.exec_driver_sql("PRAGMA writable_schema=ON")
        connection.exec_driver_sql(
            "UPDATE sqlite_master SET sql=? WHERE type='table' AND name=?",
            (rewritten, table_name),
        )
        schema_version = connection.exec_driver_sql(
            "PRAGMA schema_version"
        ).scalar_one()
        connection.exec_driver_sql(f"PRAGMA schema_version={schema_version + 1}")
        connection.exec_driver_sql("PRAGMA writable_schema=OFF")


def _load_legacy_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_FIXTURE.read_text(encoding="utf-8"))


def _insert_legacy_address_rows(path: Path) -> None:
    addresses = (
        (8, BOUNCEABLE_MAINNET),
        (9, NON_BOUNCEABLE_MAINNET),
        (10, RAW_ADDRESS.upper()),
        (11, BOUNCEABLE_TESTNET),
        (12, INVALID_CHECKSUM),
    )
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO wallet_ingestion_runs ("
            "id, wallet_address, time_window, custom_start, custom_end, "
            "data_mode, status, requested_surfaces_json, provider_summary_json, "
            "created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    run_id,
                    address,
                    "24h",
                    None,
                    None,
                    "real",
                    "success",
                    "[]",
                    '{"message":"identity backfill fixture"}',
                    "2026-06-02 00:00:00.000000",
                    "2026-06-02 00:00:00.000000",
                )
                for run_id, address in addresses
            ],
        )


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _data_snapshot(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    """Snapshot only the frozen columns that existed before revision 0002."""
    snapshot: dict[str, list[tuple[Any, ...]]] = {}
    with engine.connect() as connection:
        for table_name in sorted(PRE_0002_COLUMNS):
            columns = ", ".join(
                _quote(column) for column in PRE_0002_COLUMNS[table_name]
            )
            rows = connection.exec_driver_sql(
                f"SELECT {columns} FROM {_quote(table_name)} ORDER BY id"
            ).fetchall()
            snapshot[table_name] = [tuple(row) for row in rows]
    return snapshot


def _acquisition_evidence_counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        stream_count = connection.exec_driver_sql(
            f"SELECT COUNT(*) FROM {ACQUISITION_STREAMS_TABLE}"
        ).scalar_one()
        page_count = connection.exec_driver_sql(
            f"SELECT COUNT(*) FROM {ACQUISITION_PAGES_TABLE}"
        ).scalar_one()
    return int(stream_count), int(page_count)


def _trace_evidence_counts(engine: Engine) -> tuple[int, int, int]:
    with engine.connect() as connection:
        return tuple(
            int(
                connection.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {_quote(table_name)}"
                ).scalar_one()
            )
            for table_name in (
                TRACE_CAPTURES_TABLE,
                TRACE_NODES_TABLE,
                TRACE_MESSAGES_TABLE,
            )
        )


def _trace_boc_verification_counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        return tuple(
            int(
                connection.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {_quote(table_name)}"
                ).scalar_one()
            )
            for table_name in (
                TRACE_BOC_VERIFICATIONS_TABLE,
                TRACE_BOC_TRANSACTIONS_TABLE,
            )
        )


def _wallet_case_counts(engine: Engine) -> tuple[int, int]:
    with engine.connect() as connection:
        return tuple(
            int(
                connection.exec_driver_sql(
                    f"SELECT COUNT(*) FROM {_quote(table_name)}"
                ).scalar_one()
            )
            for table_name in (WALLET_CASES_TABLE, WALLET_CASE_SYNCS_TABLE)
        )


def _identity_snapshot(engine: Engine) -> dict[int, tuple[Any, ...]]:
    selected = ("id", "wallet_address", *IDENTITY_COLUMNS)
    columns = ", ".join(_quote(column) for column in selected)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"SELECT {columns} FROM wallet_ingestion_runs ORDER BY id"
        ).fetchall()
    return {int(row[0]): tuple(row[1:]) for row in rows}


def _transaction_identity_snapshot(engine: Engine) -> dict[int, tuple[Any, ...]]:
    selected = (
        "id",
        "run_id",
        "tx_hash",
        "logical_time",
        *TRANSACTION_IDENTITY_COLUMNS,
    )
    columns = ", ".join(_quote(column) for column in selected)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"SELECT {columns} FROM wallet_transactions ORDER BY id"
        ).fetchall()
    return {int(row[0]): tuple(row[1:]) for row in rows}


def _event_action_identity_snapshot(
    engine: Engine,
    table_name: str,
) -> dict[int, tuple[Any, ...]]:
    selected = ("id", *EVENT_ACTION_IDENTITY_COLUMNS)
    columns = ", ".join(_quote(column) for column in selected)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"SELECT {columns} FROM {_quote(table_name)} ORDER BY id"
        ).fetchall()
    return {int(row[0]): tuple(row[1:]) for row in rows}


def _transaction_legacy_snapshot(engine: Engine) -> list[tuple[Any, ...]]:
    columns = PRE_0002_COLUMNS["wallet_transactions"]
    selected = ", ".join(_quote(column) for column in columns)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"SELECT {selected} FROM wallet_transactions ORDER BY id"
        ).fetchall()
    return [tuple(row) for row in rows]


def _insert_scoped_run(
    connection,
    *,
    run_id: int,
    network: str = "ton-mainnet",
    data_mode: str = "real",
) -> None:
    wallet_address = (
        BOUNCEABLE_TESTNET if network == "ton-testnet" else BOUNCEABLE_MAINNET
    )
    connection.exec_driver_sql(
        "INSERT INTO wallet_ingestion_runs ("
        "id, wallet_address, time_window, custom_start, custom_end, "
        "data_mode, status, requested_surfaces_json, provider_summary_json, "
        "created_at, updated_at, wallet_identity_status, "
        "wallet_identity_version, wallet_network, wallet_address_canonical, "
        "wallet_workchain_id, wallet_account_id_hex, wallet_address_format, "
        "wallet_address_bounceable, wallet_address_testnet_only"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            wallet_address,
            "24h",
            None,
            None,
            data_mode,
            "success",
            '["transactions"]',
            '{"message":"transaction identity fixture"}',
            "2026-07-10 10:00:00.000000",
            "2026-07-10 10:01:00.000000",
            "network_scoped",
            "ton_std_address_v1",
            network,
            RAW_ADDRESS,
            0,
            ACCOUNT_ID,
            "user_friendly",
            1,
            1 if network == "ton-testnet" else 0,
        ),
    )


def _insert_transaction(
    connection,
    *,
    transaction_id: int,
    run_id: int,
    tx_hash: str = TRANSACTION_HASH,
    logical_time: str | None = TRANSACTION_LT,
    provider: str = "tonapi",
    source_status: str = "live",
    raw: Any | None = None,
) -> None:
    if raw is None:
        raw = {
            "provider": "tonapi",
            "surface": "transactions",
            "tx_hash": tx_hash,
            "logical_time": logical_time,
        }
    connection.exec_driver_sql(
        "INSERT INTO wallet_transactions ("
        "id, run_id, tx_hash, logical_time, timestamp, fee_ton, success, "
        "provider, source_status, raw_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            transaction_id,
            run_id,
            tx_hash,
            logical_time,
            "2026-07-10 10:02:00.000000",
            "0.0042",
            "success",
            provider,
            source_status,
            json.dumps(raw, separators=(",", ":"), sort_keys=True),
        ),
    )


def _insert_event_action_transfer(
    connection,
    *,
    transfer_id: int,
    run_id: int,
    event_id: str = EVENT_ACTION_ID,
    logical_time: str = EVENT_ACTION_LT,
    action_index: Any = 2,
    action_type: str = "TonTransfer",
    provider: str = "tonapi",
    source_status: str = "live",
    raw: Any | None = None,
) -> None:
    if raw is None:
        raw = {
            "provider": "tonapi",
            "source": "tonapi",
            "surface": "transfers",
            "event_id": event_id,
            "lt": logical_time,
            "action_index": action_index,
            "action_type": action_type,
        }
    connection.exec_driver_sql(
        "INSERT INTO wallet_transfers ("
        "id, run_id, tx_hash, logical_time, timestamp, asset, amount, "
        "direction, counterparty, provider, source_status, raw_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            transfer_id,
            run_id,
            event_id,
            logical_time,
            "2026-07-10 10:03:00.000000",
            "TON",
            "1.25",
            "out",
            RAW_ADDRESS,
            provider,
            source_status,
            json.dumps(raw, separators=(",", ":"), sort_keys=True),
        ),
    )


def _insert_event_action_swap(
    connection,
    *,
    swap_id: int,
    run_id: int,
    event_id: str = SECOND_EVENT_ACTION_ID,
    logical_time: str = EVENT_ACTION_LT,
    action_index: Any = 4,
    action_type: str = "JettonSwap",
    provider: str = "tonapi",
    source_status: str = "live",
    raw: Any | None = None,
) -> None:
    if raw is None:
        raw = {
            "provider": "tonapi",
            "source": "tonapi",
            "surface": "swaps",
            "event_id": event_id,
            "lt": logical_time,
            "action_index": action_index,
            "action_type": action_type,
        }
    connection.exec_driver_sql(
        "INSERT INTO wallet_swaps ("
        "id, run_id, tx_hash, timestamp, dex, token_in, amount_in, "
        "token_out, amount_out, estimated_usd, provider, source_status, "
        "raw_json"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            swap_id,
            run_id,
            event_id,
            "2026-07-10 10:04:00.000000",
            "stonfi",
            "TON",
            "2.5",
            "JETTON",
            "25",
            None,
            provider,
            source_status,
            json.dumps(raw, separators=(",", ":"), sort_keys=True),
        ),
    )


def _add_event_action_identity_columns(
    connection,
    table_name: str,
    *,
    count: int | None = None,
) -> None:
    definitions = EVENT_ACTION_IDENTITY_COLUMN_DEFINITIONS[:count]
    for definition in definitions:
        connection.exec_driver_sql(
            f"ALTER TABLE {table_name} ADD COLUMN {definition}"
        )


def _schema_snapshot(engine: Engine) -> list[tuple[Any, ...]]:
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT type, name, tbl_name, sql "
            "FROM sqlite_master "
            "WHERE name NOT LIKE 'sqlite_%' "
            "ORDER BY type, name"
        ).fetchall()
    return [tuple(row) for row in rows]


def _type_signature(value: Any) -> str:
    return str(value).upper().replace(" ", "")


def _metadata_column_signature(table) -> dict[str, tuple[str, bool, bool]]:
    return {
        column.name: (
            _type_signature(column.type),
            bool(column.nullable),
            bool(column.primary_key),
        )
        for column in table.columns
    }


def _reflected_column_signature(
    inspector,
    table_name: str,
) -> dict[str, tuple[str, bool, bool]]:
    return {
        column["name"]: (
            _type_signature(column["type"]),
            bool(column["nullable"]),
            bool(column["primary_key"]),
        )
        for column in inspector.get_columns(table_name)
    }


def _metadata_index_signature(table) -> set[tuple[str, tuple[str, ...], bool]]:
    return {
        (
            index.name,
            tuple(expression.name for expression in index.expressions),
            bool(index.unique),
        )
        for index in table.indexes
    }


def _reflected_index_signature(
    inspector,
    table_name: str,
) -> set[tuple[str, tuple[str, ...], bool]]:
    return {
        (
            index["name"],
            tuple(index["column_names"]),
            bool(index["unique"]),
        )
        for index in inspector.get_indexes(table_name)
    }


def _metadata_foreign_key_signature(
    table,
) -> set[tuple[tuple[str, ...], str, tuple[str, ...], tuple[tuple[str, str], ...]]]:
    signatures: set[
        tuple[
            tuple[str, ...],
            str,
            tuple[str, ...],
            tuple[tuple[str, str], ...],
        ]
    ] = set()
    for constraint in table.foreign_key_constraints:
        elements = list(constraint.elements)
        options = {
            "onupdate": constraint.onupdate,
            "ondelete": constraint.ondelete,
            "deferrable": constraint.deferrable,
            "initially": constraint.initially,
            "match": constraint.match,
        }
        signatures.add(
            (
                tuple(element.parent.name for element in elements),
                elements[0].column.table.name,
                tuple(element.column.name for element in elements),
                tuple(
                    sorted(
                        (key, str(value))
                        for key, value in options.items()
                        if value is not None
                    )
                ),
            )
        )
    return signatures


def _reflected_foreign_key_signature(
    inspector,
    table_name: str,
) -> set[
    tuple[
        tuple[str, ...],
        str,
        tuple[str, ...],
        tuple[tuple[str, str], ...],
    ]
]:
    return {
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
            tuple(
                sorted(
                    (str(key), str(value))
                    for key, value in (foreign_key.get("options") or {}).items()
                )
            ),
        )
        for foreign_key in inspector.get_foreign_keys(table_name)
    }


def _assert_schema_matches_models(
    engine: Engine,
    *,
    allowed_extra_tables: set[str] | None = None,
) -> None:
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())
    assert set(DOMAIN_TABLES).issubset(table_names)
    expected_extra_tables = {"alembic_version"} | (allowed_extra_tables or set())
    assert table_names - set(DOMAIN_TABLES) == expected_extra_tables

    for table_name in DOMAIN_TABLES:
        table = database.Base.metadata.tables[table_name]
        assert _reflected_column_signature(
            inspector, table_name
        ) == _metadata_column_signature(table)
        assert _reflected_index_signature(
            inspector, table_name
        ) == _metadata_index_signature(table)
        assert _reflected_foreign_key_signature(
            inspector, table_name
        ) == _metadata_foreign_key_signature(table)

    with engine.connect() as connection:
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
    assert violations == []


def _assert_wallet_case_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {WALLET_CASES_TABLE, WALLET_CASE_SYNCS_TABLE}.issubset(
        inspector.get_table_names()
    )
    assert {
        (check.get("name"), " ".join(str(check.get("sqltext")).split()))
        for check in inspector.get_check_constraints(WALLET_CASES_TABLE)
    } == WALLET_CASE_CHECKS
    assert {
        (check.get("name"), " ".join(str(check.get("sqltext")).split()))
        for check in inspector.get_check_constraints(WALLET_CASE_SYNCS_TABLE)
    } == WALLET_CASE_SYNC_CHECKS
    assert inspector.get_unique_constraints(WALLET_CASES_TABLE) == []
    assert inspector.get_unique_constraints(WALLET_CASE_SYNCS_TABLE) == []

    case_defaults = {
        column["name"]: column.get("default")
        for column in inspector.get_columns(WALLET_CASES_TABLE)
    }
    sync_defaults = {
        column["name"]: column.get("default")
        for column in inspector.get_columns(WALLET_CASE_SYNCS_TABLE)
    }
    assert case_defaults["owner_scope_id"] == "'local-single-user'"
    assert sync_defaults["requested_surfaces_json"] == "'[]'"
    assert sync_defaults["state"] == "'queued'"
    assert sync_defaults["stage"] == "'queued'"
    assert sync_defaults["progress_current"] == "0"
    assert sync_defaults["progress_total"] is None
    assert sync_defaults["coverage_summary_json"] == "'{}'"
    assert sync_defaults["result_summary_json"] == "'{}'"
    assert sync_defaults["message_safe"] == "''"
    if "status_version" in sync_defaults:
        assert sync_defaults["status_version"] == "1"
        assert sync_defaults["attempt_count"] == "0"
        assert sync_defaults["max_attempts"] == "4"
        assert sync_defaults["checkpoint_json"] == "'{}'"


def _assert_wallet_identity_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {column["name"] for column in inspector.get_columns("wallet_ingestion_runs")}
    assert set(IDENTITY_COLUMNS).issubset(columns)
    indexes = {
        (
            index["name"],
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
        )
        for index in inspector.get_indexes("wallet_ingestion_runs")
    }
    assert (
        "ix_wallet_ingestion_runs_wallet_identity",
        ("wallet_network", "wallet_address_canonical"),
        False,
    ) in indexes


def _assert_transaction_identity_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    columns = {
        column["name"]
        for column in inspector.get_columns("wallet_transactions")
    }
    assert set(TRANSACTION_IDENTITY_COLUMNS).issubset(columns)
    indexes = {
        (
            index["name"],
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
        )
        for index in inspector.get_indexes("wallet_transactions")
    }
    assert {
        (
            "uq_wallet_transactions_run_identity",
            ("run_id", "transaction_identity_key"),
            True,
        ),
        (
            "ix_wallet_transactions_identity_key",
            ("transaction_identity_key",),
            False,
        ),
        (
            "ix_wallet_transactions_identity_tuple",
            (
                "transaction_network",
                "transaction_account_canonical",
                "transaction_logical_time_canonical",
                "transaction_hash_canonical",
            ),
            False,
        ),
    }.issubset(indexes)


def _assert_acquisition_evidence_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {
        ACQUISITION_STREAMS_TABLE,
        ACQUISITION_PAGES_TABLE,
    }.issubset(inspector.get_table_names())

    stream_indexes = {
        (
            index["name"],
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
        )
        for index in inspector.get_indexes(ACQUISITION_STREAMS_TABLE)
    }
    assert stream_indexes == {
        (
            "uq_wallet_acquisition_streams_run_provider_key",
            ("run_id", "provider", "stream_key"),
            True,
        )
    }

    page_indexes = {
        (
            index["name"],
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
        )
        for index in inspector.get_indexes(ACQUISITION_PAGES_TABLE)
    }
    assert page_indexes == {
        (
            "uq_wallet_acquisition_pages_stream_page",
            ("stream_id", "page_index"),
            True,
        )
    }

    stream_foreign_keys = inspector.get_foreign_keys(
        ACQUISITION_STREAMS_TABLE
    )
    assert len(stream_foreign_keys) == 1
    assert stream_foreign_keys[0]["constrained_columns"] == ["run_id"]
    assert stream_foreign_keys[0]["referred_table"] == "wallet_ingestion_runs"
    assert stream_foreign_keys[0]["referred_columns"] == ["id"]
    assert stream_foreign_keys[0]["options"] == {"ondelete": "CASCADE"}

    page_foreign_keys = inspector.get_foreign_keys(ACQUISITION_PAGES_TABLE)
    assert len(page_foreign_keys) == 1
    assert page_foreign_keys[0]["constrained_columns"] == ["stream_id"]
    assert page_foreign_keys[0]["referred_table"] == ACQUISITION_STREAMS_TABLE
    assert page_foreign_keys[0]["referred_columns"] == ["id"]
    assert page_foreign_keys[0]["options"] == {"ondelete": "CASCADE"}


def _assert_trace_evidence_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {
        TRACE_CAPTURES_TABLE,
        TRACE_NODES_TABLE,
        TRACE_MESSAGES_TABLE,
    }.issubset(inspector.get_table_names())

    def indexes(table_name: str):
        return {
            (
                index["name"],
                tuple(index.get("column_names") or ()),
                bool(index.get("unique")),
            )
            for index in inspector.get_indexes(table_name)
        }

    assert indexes(TRACE_CAPTURES_TABLE) == {
        (
            "uq_wallet_trace_captures_run_root",
            (
                "run_id",
                "provider",
                "contract_version",
                "root_transaction_hash",
            ),
            True,
        ),
        (
            "uq_wallet_trace_captures_run_anchor",
            ("run_id", "captured_via_transaction_id", "contract_version"),
            True,
        ),
        (
            "uq_wallet_trace_captures_run_slot",
            ("run_id", "capture_slot"),
            True,
        ),
    }
    assert indexes(TRACE_NODES_TABLE) == {
        (
            "uq_wallet_trace_nodes_capture_preorder",
            ("capture_id", "preorder_index"),
            True,
        ),
        (
            "uq_wallet_trace_nodes_capture_hash",
            ("capture_id", "transaction_hash"),
            True,
        ),
        (
            "uq_wallet_trace_nodes_capture_coordinate",
            ("capture_id", "account_canonical", "logical_time"),
            True,
        ),
    }
    assert indexes(TRACE_MESSAGES_TABLE) == {
        (
            "uq_wallet_trace_messages_node_role_ordinal",
            ("node_id", "role", "ordinal"),
            True,
        ),
        (
            "ix_wallet_trace_messages_observation",
            ("observation_identity_key",),
            False,
        ),
        (
            "ix_wallet_trace_messages_hash",
            ("message_hash",),
            False,
        ),
    }

    assert _reflected_foreign_key_signature(
        inspector, TRACE_CAPTURES_TABLE
    ) == {
        (
            ("run_id",),
            "wallet_ingestion_runs",
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
        (
            ("captured_via_transaction_id",),
            "wallet_transactions",
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
    }
    assert _reflected_foreign_key_signature(
        inspector, TRACE_NODES_TABLE
    ) == {
        (
            ("capture_id",),
            TRACE_CAPTURES_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
        (
            ("parent_node_id",),
            TRACE_NODES_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
    }
    assert _reflected_foreign_key_signature(
        inspector, TRACE_MESSAGES_TABLE
    ) == {
        (
            ("node_id",),
            TRACE_NODES_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        )
    }


def _assert_trace_boc_verification_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    assert {
        TRACE_BOC_VERIFICATIONS_TABLE,
        TRACE_BOC_TRANSACTIONS_TABLE,
    }.issubset(inspector.get_table_names())

    def indexes(table_name: str):
        return {
            (
                index["name"],
                tuple(index.get("column_names") or ()),
                bool(index.get("unique")),
            )
            for index in inspector.get_indexes(table_name)
        }

    assert indexes(TRACE_BOC_VERIFICATIONS_TABLE) == {
        (
            "uq_wallet_trace_boc_verifications_capture_contract",
            ("capture_id", "contract_version"),
            True,
        ),
        (
            "ix_wallet_trace_boc_verifications_digest",
            ("evidence_digest_sha256",),
            False,
        ),
    }
    assert indexes(TRACE_BOC_TRANSACTIONS_TABLE) == {
        (
            "uq_wallet_trace_boc_transactions_verification_node",
            ("verification_id", "node_id"),
            True,
        ),
        (
            "uq_wallet_trace_boc_transactions_verification_preorder",
            ("verification_id", "preorder_index"),
            True,
        ),
        (
            "uq_wallet_trace_boc_transactions_verification_hash",
            ("verification_id", "transaction_hash"),
            True,
        ),
    }
    assert _reflected_foreign_key_signature(
        inspector, TRACE_BOC_VERIFICATIONS_TABLE
    ) == {
        (
            ("capture_id",),
            TRACE_CAPTURES_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        )
    }
    assert _reflected_foreign_key_signature(
        inspector, TRACE_BOC_TRANSACTIONS_TABLE
    ) == {
        (
            ("verification_id",),
            TRACE_BOC_VERIFICATIONS_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
        (
            ("node_id",),
            TRACE_NODES_TABLE,
            ("id",),
            (("ondelete", "CASCADE"),),
        ),
    }


def _expected_event_action_identity_indexes(
    table_name: str,
) -> set[tuple[str, tuple[str, ...], bool]]:
    surface = "transfers" if table_name == "wallet_transfers" else "swaps"
    return {
        (
            f"uq_wallet_{surface}_run_event_action_identity",
            ("run_id", "event_action_identity_key"),
            True,
        ),
        (
            f"ix_wallet_{surface}_event_action_identity_key",
            ("event_action_identity_key",),
            False,
        ),
        (
            f"ix_wallet_{surface}_event_action_identity_tuple",
            (
                "provider",
                "event_action_network",
                "event_action_account_canonical",
                "event_action_event_id_canonical",
                "event_action_logical_time_canonical",
                "event_action_index",
            ),
            False,
        ),
    }


def _assert_event_action_identity_schema(engine: Engine) -> None:
    inspector = inspect(engine)
    for table_name in ("wallet_transfers", "wallet_swaps"):
        columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        assert set(EVENT_ACTION_IDENTITY_COLUMNS).issubset(columns)
        assert "event_action_provider" not in columns
        identity_indexes = {
            (
                index["name"],
                tuple(index.get("column_names") or ()),
                bool(index.get("unique")),
            )
            for index in inspector.get_indexes(table_name)
            if "event_action" in str(index.get("name"))
        }
        assert identity_indexes == _expected_event_action_identity_indexes(
            table_name
        )


def _assert_event_action_identity_schema_absent(engine: Engine) -> None:
    inspector = inspect(engine)
    for table_name in ("wallet_transfers", "wallet_swaps"):
        columns = {
            column["name"] for column in inspector.get_columns(table_name)
        }
        assert columns.isdisjoint(EVENT_ACTION_IDENTITY_COLUMNS)
        assert all(
            "event_action" not in str(index.get("name"))
            for index in inspector.get_indexes(table_name)
        )


def _assert_legacy_identity_backfill(engine: Engine) -> None:
    rows = _identity_snapshot(engine)

    # The original frozen fixture intentionally contains an invalid fake address.
    assert rows[7] == (
        "EQlegacyWallet",
        "unavailable",
        "unavailable",
        "ton-unknown",
        None,
        None,
        None,
        "unrecognized",
        None,
        None,
    )
    assert rows[8] == (
        BOUNCEABLE_MAINNET,
        "network_scoped",
        "ton_std_address_v1",
        "ton-mainnet",
        RAW_ADDRESS,
        0,
        ACCOUNT_ID,
        "user_friendly",
        True,
        False,
    )
    assert rows[9] == (
        NON_BOUNCEABLE_MAINNET,
        "network_scoped",
        "ton_std_address_v1",
        "ton-mainnet",
        RAW_ADDRESS,
        0,
        ACCOUNT_ID,
        "user_friendly",
        False,
        False,
    )
    assert rows[10] == (
        RAW_ADDRESS.upper(),
        "unscoped",
        "ton_raw_address_v1",
        "ton-unknown",
        RAW_ADDRESS,
        0,
        ACCOUNT_ID,
        "raw",
        None,
        None,
    )
    assert rows[11] == (
        BOUNCEABLE_TESTNET,
        "network_scoped",
        "ton_std_address_v1",
        "ton-testnet",
        RAW_ADDRESS,
        0,
        ACCOUNT_ID,
        "user_friendly",
        True,
        True,
    )
    assert rows[12] == (
        INVALID_CHECKSUM,
        "unavailable",
        "unavailable",
        "ton-unknown",
        None,
        None,
        None,
        "unrecognized",
        None,
        None,
    )


def _assert_legacy_transaction_identity_backfill(engine: Engine) -> None:
    rows = _transaction_identity_snapshot(engine)
    assert rows[102] == (
        7,
        "legacy-transaction-hash",
        "46000000000002",
        "unavailable",
        "unavailable",
        "ton-unknown",
        None,
        None,
        None,
        None,
    )


def _assert_legacy_event_action_identity_backfill(engine: Engine) -> None:
    unavailable = (
        "unavailable",
        "unavailable",
        "ton-unknown",
        None,
        None,
        None,
        None,
        None,
        None,
    )
    assert _event_action_identity_snapshot(engine, "wallet_transfers")[101] == (
        unavailable
    )
    assert _event_action_identity_snapshot(engine, "wallet_swaps")[103] == (
        unavailable
    )


def _revision_cell(
    engine: Engine,
    expected_revision: str,
) -> tuple[str, str]:
    inspector = inspect(engine)
    marker_tables = set(inspector.get_table_names()) - set(DOMAIN_TABLES)
    assert len(marker_tables) == 1
    marker_table = marker_tables.pop()

    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            f"SELECT * FROM {_quote(marker_table)}"
        ).fetchall()
    columns = [column["name"] for column in inspector.get_columns(marker_table)]
    for row in rows:
        for column, value in zip(columns, row):
            if value == expected_revision:
                return marker_table, column
    raise AssertionError(
        f"Revision {expected_revision!r} was not found in marker table {marker_table!r}."
    )


def test_fresh_sqlite_reaches_head_with_full_schema_parity(tmp_path):
    engine = _engine(tmp_path / "fresh.db")

    report = run_database_migrations(engine)

    assert isinstance(report, MigrationReport)
    assert report.action == "created"
    assert report.revision_before is None
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        BASELINE_REVISION,
        WALLET_IDENTITY_REVISION,
        TRANSACTION_IDENTITY_REVISION,
        ACQUISITION_EVIDENCE_REVISION,
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    _assert_wallet_identity_schema(engine)
    _assert_transaction_identity_schema(engine)
    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema(engine)
    _assert_trace_evidence_schema(engine)
    _assert_trace_boc_verification_schema(engine)
    assert _acquisition_evidence_counts(engine) == (0, 0)
    assert _trace_evidence_counts(engine) == (0, 0, 0)
    assert _trace_boc_verification_counts(engine) == (0, 0)

    engine.dispose()
    reopened = _engine(tmp_path / "fresh.db")
    _assert_schema_matches_models(reopened)
    reopened.dispose()


def test_exact_unversioned_legacy_database_preserves_all_data(tmp_path):
    path = tmp_path / "legacy.db"
    _load_legacy_fixture(path)
    _insert_legacy_address_rows(path)
    engine = _engine(path)
    before = _data_snapshot(engine)

    report = run_database_migrations(engine)

    assert isinstance(report, MigrationReport)
    assert report.action == "adopted_legacy"
    assert report.revision_before is None
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        WALLET_IDENTITY_REVISION,
        TRANSACTION_IDENTITY_REVISION,
        ACQUISITION_EVIDENCE_REVISION,
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _data_snapshot(engine) == before
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    _assert_wallet_identity_schema(engine)
    _assert_transaction_identity_schema(engine)
    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema(engine)
    _assert_trace_evidence_schema(engine)
    assert _acquisition_evidence_counts(engine) == (0, 0)
    assert _trace_evidence_counts(engine) == (0, 0, 0)
    _assert_legacy_identity_backfill(engine)
    _assert_legacy_transaction_identity_backfill(engine)
    _assert_legacy_event_action_identity_backfill(engine)
    engine.dispose()


def test_legacy_adoption_preserves_unrelated_user_tables(tmp_path):
    path = tmp_path / "legacy-with-user-table.db"
    _load_legacy_fixture(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE user_notes (id INTEGER PRIMARY KEY, note TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO user_notes (id, note) VALUES (?, ?)",
            (1, "keep this unrelated table"),
        )
    engine = _engine(path)

    report = run_database_migrations(engine)

    assert report.action == "adopted_legacy"
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        WALLET_IDENTITY_REVISION,
        TRANSACTION_IDENTITY_REVISION,
        ACQUISITION_EVIDENCE_REVISION,
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    _assert_schema_matches_models(engine, allowed_extra_tables={"user_notes"})
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT id, note FROM user_notes"
        ).one() == (1, "keep this unrelated table")
    engine.dispose()


def test_runner_is_idempotent_at_head(tmp_path):
    path = tmp_path / "idempotent.db"
    _load_legacy_fixture(path)
    _insert_legacy_address_rows(path)
    engine = _engine(path)
    first = run_database_migrations(engine)
    schema_after_first = _schema_snapshot(engine)
    data_after_first = _data_snapshot(engine)
    identities_after_first = _identity_snapshot(engine)
    transaction_identities_after_first = _transaction_identity_snapshot(engine)
    transfer_identities_after_first = _event_action_identity_snapshot(
        engine, "wallet_transfers"
    )
    swap_identities_after_first = _event_action_identity_snapshot(
        engine, "wallet_swaps"
    )
    acquisition_counts_after_first = _acquisition_evidence_counts(engine)
    trace_counts_after_first = _trace_evidence_counts(engine)

    second = run_database_migrations(engine)

    assert isinstance(second, MigrationReport)
    assert second.action == "already_current"
    assert second.revision_before == first.revision_after
    assert second.revision_after == first.revision_after
    assert not second.applied_revisions
    assert _schema_snapshot(engine) == schema_after_first
    assert _data_snapshot(engine) == data_after_first
    assert _identity_snapshot(engine) == identities_after_first
    assert (
        _transaction_identity_snapshot(engine)
        == transaction_identities_after_first
    )
    assert (
        _event_action_identity_snapshot(engine, "wallet_transfers")
        == transfer_identities_after_first
    )
    assert (
        _event_action_identity_snapshot(engine, "wallet_swaps")
        == swap_identities_after_first
    )
    assert _acquisition_evidence_counts(engine) == acquisition_counts_after_first
    assert _trace_evidence_counts(engine) == trace_counts_after_first
    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema(engine)
    _assert_trace_evidence_schema(engine)
    _assert_legacy_identity_backfill(engine)
    _assert_legacy_transaction_identity_backfill(engine)
    _assert_legacy_event_action_identity_backfill(engine)
    engine.dispose()


def test_interrupted_wallet_identity_migration_retries_partial_sqlite_ddl(tmp_path):
    engine = _engine(tmp_path / "interrupted-identity.db")
    _upgrade_to_revision(engine, BASELINE_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO wallet_ingestion_runs ("
            "id, wallet_address, time_window, custom_start, custom_end, "
            "data_mode, status, requested_surfaces_json, provider_summary_json, "
            "created_at, updated_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                BOUNCEABLE_MAINNET,
                "24h",
                None,
                None,
                "real",
                "success",
                "[]",
                '{"message":"interrupted migration fixture"}',
                "2026-06-02 00:00:00.000000",
                "2026-06-02 00:00:00.000000",
            ),
        )
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_identity_update "
            "BEFORE UPDATE ON wallet_ingestion_runs "
            "BEGIN SELECT RAISE(ABORT, 'forced backfill failure'); END"
        )
    data_before = _data_snapshot(engine)

    with pytest.raises(IntegrityError, match="forced backfill failure"):
        run_database_migrations(engine)

    assert _data_snapshot(engine) == data_before
    inspector = inspect(engine)
    columns_after_failure = {
        column["name"]
        for column in inspector.get_columns("wallet_ingestion_runs")
    }
    assert set(IDENTITY_COLUMNS).issubset(columns_after_failure)
    assert "ix_wallet_ingestion_runs_wallet_identity" not in {
        index["name"]
        for index in inspector.get_indexes("wallet_ingestion_runs")
    }
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == BASELINE_REVISION

    # Simulate interruption after index creation as well. A retry must accept
    # both the already-added columns and an already-correct index.
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER reject_identity_update")
        connection.exec_driver_sql(
            "CREATE INDEX ix_wallet_ingestion_runs_wallet_identity "
            "ON wallet_ingestion_runs "
            "(wallet_network, wallet_address_canonical)"
        )

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == BASELINE_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        WALLET_IDENTITY_REVISION,
        TRANSACTION_IDENTITY_REVISION,
        ACQUISITION_EVIDENCE_REVISION,
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _data_snapshot(engine) == data_before
    identity = _identity_snapshot(engine)[1]
    assert identity[0] == BOUNCEABLE_MAINNET
    assert identity[1:5] == (
        "network_scoped",
        "ton_std_address_v1",
        "ton-mainnet",
        RAW_ADDRESS,
    )
    _assert_schema_matches_models(engine)
    _assert_wallet_identity_schema(engine)
    _assert_transaction_identity_schema(engine)
    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema(engine)
    engine.dispose()


def test_partial_identity_column_with_wrong_shape_fails_before_more_ddl(tmp_path):
    engine = _engine(tmp_path / "malformed-partial-identity.db")
    _upgrade_to_revision(engine, BASELINE_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE wallet_ingestion_runs ADD COLUMN "
            "wallet_identity_status TEXT DEFAULT 'unavailable' NOT NULL"
        )

    with pytest.raises(RuntimeError, match="do not match revision 0002"):
        run_database_migrations(engine)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("wallet_ingestion_runs")
    }
    assert columns & set(IDENTITY_COLUMNS) == {"wallet_identity_status"}
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == BASELINE_REVISION
    engine.dispose()


def test_transaction_identity_backfill_is_strict_and_preserves_source_rows(
    tmp_path,
):
    engine = _engine(tmp_path / "transaction-identity-vectors.db")
    _upgrade_to_revision(engine, WALLET_IDENTITY_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_scoped_run(connection, run_id=2, network="ton-testnet")
        _insert_scoped_run(connection, run_id=3, data_mode="mock")
        _insert_scoped_run(connection, run_id=4)
        _insert_scoped_run(connection, run_id=5)
        connection.exec_driver_sql(
            "UPDATE wallet_ingestion_runs SET "
            "wallet_identity_status='unavailable', "
            "wallet_identity_version='unavailable', "
            "wallet_network='ton-unknown', "
            "wallet_address_canonical=NULL, wallet_workchain_id=NULL, "
            "wallet_account_id_hex=NULL, wallet_address_format='unrecognized', "
            "wallet_address_bounceable=NULL, "
            "wallet_address_testnet_only=NULL WHERE id=4"
        )
        connection.exec_driver_sql(
            "UPDATE wallet_ingestion_runs SET "
            "wallet_identity_version='unknown_wallet_identity_v9' "
            "WHERE id=5"
        )

        # The same low-level tuple on different networks must remain distinct.
        _insert_transaction(
            connection,
            transaction_id=1,
            run_id=1,
            tx_hash=TRANSACTION_HASH.upper(),
        )
        _insert_transaction(
            connection,
            transaction_id=2,
            run_id=2,
            tx_hash=TRANSACTION_HASH.upper(),
        )
        _insert_transaction(
            connection,
            transaction_id=3,
            run_id=1,
            tx_hash=SECOND_TRANSACTION_HASH,
            logical_time="01",
        )
        _insert_transaction(
            connection,
            transaction_id=4,
            run_id=1,
            tx_hash=SECOND_TRANSACTION_HASH,
            raw={
                "provider": "tonapi",
                "surface": "transactions",
                "tx_hash": TRANSACTION_HASH,
                "logical_time": TRANSACTION_LT,
            },
        )
        _insert_transaction(connection, transaction_id=5, run_id=3)
        _insert_transaction(
            connection,
            transaction_id=6,
            run_id=1,
            provider="stonfi",
        )
        _insert_transaction(
            connection,
            transaction_id=7,
            run_id=1,
            source_status="mock",
        )
        _insert_transaction(connection, transaction_id=8, run_id=4)
        _insert_transaction(
            connection,
            transaction_id=9,
            run_id=1,
            tx_hash="g" * 64,
        )
        _insert_transaction(
            connection,
            transaction_id=10,
            run_id=1,
            raw=[],
        )
        _insert_transaction(connection, transaction_id=11, run_id=5)
    source_before = _transaction_legacy_snapshot(engine)

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == WALLET_IDENTITY_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        TRANSACTION_IDENTITY_REVISION,
        ACQUISITION_EVIDENCE_REVISION,
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _transaction_legacy_snapshot(engine) == source_before
    rows = _transaction_identity_snapshot(engine)

    mainnet_key = (
        f"{TRANSACTION_IDENTITY_VERSION}|ton-mainnet|{RAW_ADDRESS}|"
        f"{TRANSACTION_LT}|{TRANSACTION_HASH}"
    )
    testnet_key = (
        f"{TRANSACTION_IDENTITY_VERSION}|ton-testnet|{RAW_ADDRESS}|"
        f"{TRANSACTION_LT}|{TRANSACTION_HASH}"
    )
    assert rows[1] == (
        1,
        TRANSACTION_HASH.upper(),
        TRANSACTION_LT,
        "network_scoped",
        TRANSACTION_IDENTITY_VERSION,
        "ton-mainnet",
        RAW_ADDRESS,
        TRANSACTION_LT,
        TRANSACTION_HASH,
        mainnet_key,
    )
    assert rows[2] == (
        2,
        TRANSACTION_HASH.upper(),
        TRANSACTION_LT,
        "network_scoped",
        TRANSACTION_IDENTITY_VERSION,
        "ton-testnet",
        RAW_ADDRESS,
        TRANSACTION_LT,
        TRANSACTION_HASH,
        testnet_key,
    )
    unavailable_suffix = (
        "unavailable",
        "unavailable",
        "ton-unknown",
        None,
        None,
        None,
        None,
    )
    assert all(
        row[3:] == unavailable_suffix
        for transaction_id, row in rows.items()
        if transaction_id > 2
    )
    assert mainnet_key != testnet_key
    with engine.connect() as connection:
        statuses = connection.exec_driver_sql(
            "SELECT transaction_identity_status, COUNT(*) "
            "FROM wallet_transactions GROUP BY transaction_identity_status "
            "ORDER BY transaction_identity_status"
        ).fetchall()
    assert statuses == [("network_scoped", 2), ("unavailable", 9)]
    _assert_schema_matches_models(engine)
    _assert_transaction_identity_schema(engine)
    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema(engine)
    engine.dispose()


def test_interrupted_transaction_identity_migration_retries_partial_sqlite_ddl(
    tmp_path,
):
    engine = _engine(tmp_path / "interrupted-transaction-identity.db")
    _upgrade_to_revision(engine, WALLET_IDENTITY_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_transaction(connection, transaction_id=1, run_id=1)
        connection.exec_driver_sql(
            "CREATE TRIGGER reject_transaction_identity_update "
            "BEFORE UPDATE ON wallet_transactions "
            "BEGIN SELECT RAISE(ABORT, 'forced transaction backfill failure'); END"
        )
    source_before = _transaction_legacy_snapshot(engine)

    with pytest.raises(
        IntegrityError,
        match="forced transaction backfill failure",
    ):
        run_database_migrations(engine)

    assert _transaction_legacy_snapshot(engine) == source_before
    inspector = inspect(engine)
    columns_after_failure = {
        column["name"]
        for column in inspector.get_columns("wallet_transactions")
    }
    assert set(TRANSACTION_IDENTITY_COLUMNS).issubset(columns_after_failure)
    identity_index_names = {
        name for name, _, _ in (
            (
                "uq_wallet_transactions_run_identity",
                ("run_id", "transaction_identity_key"),
                True,
            ),
            (
                "ix_wallet_transactions_identity_key",
                ("transaction_identity_key",),
                False,
            ),
            (
                "ix_wallet_transactions_identity_tuple",
                (
                    "transaction_network",
                    "transaction_account_canonical",
                    "transaction_logical_time_canonical",
                    "transaction_hash_canonical",
                ),
                False,
            ),
        )
    }
    assert identity_index_names.isdisjoint(
        {index["name"] for index in inspector.get_indexes("wallet_transactions")}
    )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_IDENTITY_REVISION

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP TRIGGER reject_transaction_identity_update"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_wallet_transactions_identity_key "
            "ON wallet_transactions (transaction_identity_key)"
        )

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == WALLET_IDENTITY_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        TRANSACTION_IDENTITY_REVISION,
        ACQUISITION_EVIDENCE_REVISION,
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _transaction_legacy_snapshot(engine) == source_before
    assert _transaction_identity_snapshot(engine)[1][3] == "network_scoped"
    _assert_schema_matches_models(engine)
    _assert_transaction_identity_schema(engine)
    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema(engine)
    engine.dispose()


def test_partial_transaction_identity_column_with_wrong_shape_fails_closed(
    tmp_path,
):
    engine = _engine(tmp_path / "malformed-partial-transaction-identity.db")
    _upgrade_to_revision(engine, WALLET_IDENTITY_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE wallet_transactions ADD COLUMN "
            "transaction_identity_status TEXT DEFAULT 'unavailable' NOT NULL"
        )

    with pytest.raises(RuntimeError, match="do not match revision 0003"):
        run_database_migrations(engine)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns("wallet_transactions")
    }
    assert columns & set(TRANSACTION_IDENTITY_COLUMNS) == {
        "transaction_identity_status"
    }
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_IDENTITY_REVISION
    engine.dispose()


def test_duplicate_transaction_identity_in_one_run_fails_before_indexes(
    tmp_path,
):
    engine = _engine(tmp_path / "duplicate-transaction-identity.db")
    _upgrade_to_revision(engine, WALLET_IDENTITY_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_transaction(connection, transaction_id=1, run_id=1)
        _insert_transaction(connection, transaction_id=2, run_id=1)
    source_before = _transaction_legacy_snapshot(engine)

    for _ in range(2):
        with pytest.raises(
            RuntimeError,
            match="Duplicate canonical transaction identities",
        ):
            run_database_migrations(engine)
        assert _transaction_legacy_snapshot(engine) == source_before
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == WALLET_IDENTITY_REVISION

    indexes = {
        index["name"]
        for index in inspect(engine).get_indexes("wallet_transactions")
    }
    assert "uq_wallet_transactions_run_identity" not in indexes
    assert "ix_wallet_transactions_identity_key" not in indexes
    assert "ix_wallet_transactions_identity_tuple" not in indexes
    engine.dispose()


def test_partial_unique_transaction_index_is_rejected_before_other_indexes(
    tmp_path,
):
    engine = _engine(tmp_path / "partial-transaction-identity-index.db")
    _upgrade_to_revision(engine, WALLET_IDENTITY_REVISION)
    column_definitions = (
        "transaction_identity_status VARCHAR(20) DEFAULT 'unavailable' NOT NULL",
        "transaction_identity_version VARCHAR(24) DEFAULT 'unavailable' NOT NULL",
        "transaction_network VARCHAR(16) DEFAULT 'ton-unknown' NOT NULL",
        "transaction_account_canonical VARCHAR(76)",
        "transaction_logical_time_canonical VARCHAR(20)",
        "transaction_hash_canonical VARCHAR(64)",
        "transaction_identity_key VARCHAR(192)",
    )
    with engine.begin() as connection:
        for definition in column_definitions:
            connection.exec_driver_sql(
                f"ALTER TABLE wallet_transactions ADD COLUMN {definition}"
            )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_wallet_transactions_run_identity "
            "ON wallet_transactions (run_id, transaction_identity_key) "
            "WHERE transaction_identity_key IS NULL"
        )

    with pytest.raises(RuntimeError, match="index does not match revision 0003"):
        run_database_migrations(engine)

    indexes = {
        index["name"]: index
        for index in inspect(engine).get_indexes("wallet_transactions")
    }
    assert indexes["uq_wallet_transactions_run_identity"][
        "dialect_options"
    ]
    assert "ix_wallet_transactions_identity_key" not in indexes
    assert "ix_wallet_transactions_identity_tuple" not in indexes
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_IDENTITY_REVISION
    engine.dispose()


def test_current_schema_rejects_partial_unique_transaction_index(tmp_path):
    engine = _engine(tmp_path / "current-partial-transaction-index.db")
    run_database_migrations(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP INDEX uq_wallet_transactions_run_identity"
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_wallet_transactions_run_identity "
            "ON wallet_transactions (run_id, transaction_identity_key) "
            "WHERE transaction_identity_key IS NULL"
        )

    with pytest.raises(MigrationBootstrapError, match="current indexes differ"):
        run_database_migrations(engine)

    engine.dispose()


def test_acquisition_evidence_migration_repairs_correct_partial_sqlite_ddl(
    tmp_path,
):
    engine = _engine(tmp_path / "partial-acquisition-evidence.db")
    _upgrade_to_revision(engine, TRANSACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            ACQUISITION_STREAMS_TABLE,
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX "
            "uq_wallet_acquisition_streams_run_provider_key "
            "ON wallet_acquisition_streams (run_id, provider, stream_key)"
        )

    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)

    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema_absent(engine)
    assert _acquisition_evidence_counts(engine) == (0, 0)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == ACQUISITION_EVIDENCE_REVISION
    engine.dispose()


def test_acquisition_evidence_migration_repairs_missing_page_index(tmp_path):
    engine = _engine(tmp_path / "partial-acquisition-page-index.db")
    _upgrade_to_revision(engine, TRANSACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            ACQUISITION_STREAMS_TABLE,
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX "
            "uq_wallet_acquisition_streams_run_provider_key "
            "ON wallet_acquisition_streams (run_id, provider, stream_key)"
        )
        _create_model_table_without_indexes(
            connection,
            ACQUISITION_PAGES_TABLE,
        )

    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)

    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema_absent(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == ACQUISITION_EVIDENCE_REVISION
    engine.dispose()


def test_partial_acquisition_table_shape_fails_before_more_ddl(tmp_path):
    engine = _engine(tmp_path / "malformed-acquisition-evidence.db")
    _upgrade_to_revision(engine, TRANSACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE wallet_acquisition_streams ("
            "id INTEGER NOT NULL, "
            "run_id INTEGER NOT NULL, "
            "provider TEXT NOT NULL, "
            "PRIMARY KEY (id), "
            "FOREIGN KEY(run_id) REFERENCES wallet_ingestion_runs (id) "
            "ON DELETE CASCADE"
            ")"
        )

    with pytest.raises(RuntimeError, match="columns do not match revision 0004"):
        _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)

    assert ACQUISITION_PAGES_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRANSACTION_IDENTITY_REVISION
    engine.dispose()


def test_wrong_partial_acquisition_index_fails_before_page_table(tmp_path):
    engine = _engine(tmp_path / "malformed-acquisition-index.db")
    _upgrade_to_revision(engine, TRANSACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            ACQUISITION_STREAMS_TABLE,
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX "
            "uq_wallet_acquisition_streams_run_provider_key "
            "ON wallet_acquisition_streams (run_id, stream_key, provider)"
        )

    with pytest.raises(RuntimeError, match="index does not match revision 0004"):
        _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)

    assert ACQUISITION_PAGES_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRANSACTION_IDENTITY_REVISION
    engine.dispose()


def test_wrong_partial_acquisition_foreign_key_options_fail_closed(tmp_path):
    engine = _engine(tmp_path / "malformed-acquisition-foreign-key.db")
    _upgrade_to_revision(engine, TRANSACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            ACQUISITION_STREAMS_TABLE,
        )
    _rewrite_table_sql(
        engine,
        ACQUISITION_STREAMS_TABLE,
        " ON DELETE CASCADE",
        "",
    )

    with pytest.raises(
        RuntimeError,
        match="foreign keys do not match revision 0004",
    ):
        _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)

    assert ACQUISITION_PAGES_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRANSACTION_IDENTITY_REVISION
    engine.dispose()


def test_pre_revision_acquisition_evidence_rows_are_never_adopted(tmp_path):
    engine = _engine(tmp_path / "unexpected-acquisition-data.db")
    _upgrade_to_revision(engine, TRANSACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _create_model_table_without_indexes(
            connection,
            ACQUISITION_STREAMS_TABLE,
        )
        connection.exec_driver_sql(
            "INSERT INTO wallet_acquisition_streams ("
            "id, run_id, provider, stream_key, contract_version, scope_kind, "
            "page_size, max_pages, max_items, started_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                "tonapi",
                "blockchain_transactions",
                "wallet_activity_acquisition_v1",
                "bounded_history",
                100,
                20,
                2000,
                "2026-07-10 12:00:00.000000",
            ),
        )

    with pytest.raises(RuntimeError, match="unexpected pre-revision data"):
        _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)

    assert ACQUISITION_PAGES_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRANSACTION_IDENTITY_REVISION
    engine.dispose()


def test_acquisition_evidence_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "acquisition-forward-only.db")
    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)

    with engine.begin() as connection:
        with pytest.raises(
            RuntimeError,
            match="Acquisition evidence downgrade would discard",
        ):
            command.downgrade(
                migration_config(connection),
                TRANSACTION_IDENTITY_REVISION,
            )

    _assert_acquisition_evidence_schema(engine)
    _assert_event_action_identity_schema_absent(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == ACQUISITION_EVIDENCE_REVISION
    engine.dispose()


def test_event_action_identity_backfill_is_strict_and_legacy_rows_unavailable(
    tmp_path,
):
    engine = _engine(tmp_path / "event-action-identity-vectors.db")
    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_scoped_run(connection, run_id=2, network="ton-testnet")
        _insert_scoped_run(connection, run_id=3, data_mode="mock")

        _insert_event_action_transfer(
            connection,
            transfer_id=1,
            run_id=1,
            event_id=EVENT_ACTION_ID.upper(),
            action_index=2,
        )
        _insert_event_action_swap(
            connection,
            swap_id=1,
            run_id=2,
            event_id=SECOND_EVENT_ACTION_ID.upper(),
            action_index=4,
        )

        # v0.22.5 did not persist the original provider action ordinal. Even
        # otherwise coherent rows must remain explicitly unavailable.
        _insert_event_action_transfer(
            connection,
            transfer_id=2,
            run_id=1,
            raw={
                "provider": "tonapi",
                "source": "tonapi",
                "surface": "transfers",
                "event_id": EVENT_ACTION_ID,
                "lt": EVENT_ACTION_LT,
                "action_type": "TonTransfer",
            },
        )
        _insert_event_action_swap(
            connection,
            swap_id=2,
            run_id=1,
            raw={
                "provider": "tonapi",
                "source": "tonapi",
                "surface": "swaps",
                "event_id": SECOND_EVENT_ACTION_ID,
                "lt": EVENT_ACTION_LT,
                "action_type": "JettonSwap",
            },
        )

        # Missing exact raw.source provenance, mock data, and a boolean action
        # index cannot receive a provider-scoped identity.
        _insert_event_action_transfer(
            connection,
            transfer_id=3,
            run_id=1,
            event_id=SECOND_EVENT_ACTION_ID,
            raw={
                "provider": "tonapi",
                "surface": "transfers",
                "event_id": SECOND_EVENT_ACTION_ID,
                "lt": EVENT_ACTION_LT,
                "action_index": 1,
                "action_type": "JettonTransfer",
            },
        )
        _insert_event_action_swap(
            connection,
            swap_id=3,
            run_id=3,
        )
        _insert_event_action_swap(
            connection,
            swap_id=4,
            run_id=1,
            event_id="34" * 32,
            action_index=False,
        )
    source_before = _data_snapshot(engine)

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == ACQUISITION_EVIDENCE_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _data_snapshot(engine) == source_before

    mainnet_key = (
        f"{EVENT_ACTION_IDENTITY_VERSION}|tonapi|ton-mainnet|{RAW_ADDRESS}|"
        f"{EVENT_ACTION_ID}|{EVENT_ACTION_LT}|2"
    )
    testnet_key = (
        f"{EVENT_ACTION_IDENTITY_VERSION}|tonapi|ton-testnet|{RAW_ADDRESS}|"
        f"{SECOND_EVENT_ACTION_ID}|{EVENT_ACTION_LT}|4"
    )
    transfers = _event_action_identity_snapshot(engine, "wallet_transfers")
    swaps = _event_action_identity_snapshot(engine, "wallet_swaps")
    assert transfers[1] == (
        "provider_scoped",
        EVENT_ACTION_IDENTITY_VERSION,
        "ton-mainnet",
        RAW_ADDRESS,
        EVENT_ACTION_ID,
        EVENT_ACTION_LT,
        2,
        "TonTransfer",
        mainnet_key,
    )
    assert swaps[1] == (
        "provider_scoped",
        EVENT_ACTION_IDENTITY_VERSION,
        "ton-testnet",
        RAW_ADDRESS,
        SECOND_EVENT_ACTION_ID,
        EVENT_ACTION_LT,
        4,
        "JettonSwap",
        testnet_key,
    )
    unavailable = (
        "unavailable",
        "unavailable",
        "ton-unknown",
        None,
        None,
        None,
        None,
        None,
        None,
    )
    assert transfers[2] == unavailable
    assert transfers[3] == unavailable
    assert swaps[2] == unavailable
    assert swaps[3] == unavailable
    assert swaps[4] == unavailable
    _assert_schema_matches_models(engine)
    _assert_event_action_identity_schema(engine)
    engine.dispose()


def test_event_action_identity_migration_repairs_partial_columns_and_index(
    tmp_path,
):
    engine = _engine(tmp_path / "partial-event-action-identity.db")
    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_event_action_transfer(connection, transfer_id=1, run_id=1)
        _insert_event_action_swap(connection, swap_id=1, run_id=1)
        _add_event_action_identity_columns(
            connection,
            "wallet_transfers",
            count=4,
        )
        _add_event_action_identity_columns(connection, "wallet_swaps")
        connection.exec_driver_sql(
            "CREATE INDEX ix_wallet_swaps_event_action_identity_key "
            "ON wallet_swaps (event_action_identity_key)"
        )
    source_before = _data_snapshot(engine)

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == ACQUISITION_EVIDENCE_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _data_snapshot(engine) == source_before
    assert _event_action_identity_snapshot(
        engine, "wallet_transfers"
    )[1][0] == "provider_scoped"
    assert _event_action_identity_snapshot(
        engine, "wallet_swaps"
    )[1][0] == "provider_scoped"
    _assert_schema_matches_models(engine)
    _assert_event_action_identity_schema(engine)
    engine.dispose()


def test_partial_event_action_identity_column_shape_fails_before_other_table_ddl(
    tmp_path,
):
    engine = _engine(tmp_path / "malformed-event-action-column.db")
    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE wallet_transfers ADD COLUMN "
            "event_action_identity_status TEXT DEFAULT 'unavailable' NOT NULL"
        )

    with pytest.raises(RuntimeError, match="do not match revision 0005"):
        run_database_migrations(engine)

    transfer_columns = {
        column["name"]
        for column in inspect(engine).get_columns("wallet_transfers")
    }
    swap_columns = {
        column["name"]
        for column in inspect(engine).get_columns("wallet_swaps")
    }
    assert transfer_columns & set(EVENT_ACTION_IDENTITY_COLUMNS) == {
        "event_action_identity_status"
    }
    assert swap_columns.isdisjoint(EVENT_ACTION_IDENTITY_COLUMNS)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == ACQUISITION_EVIDENCE_REVISION
    engine.dispose()


def test_partial_event_action_identity_index_fails_before_other_indexes(
    tmp_path,
):
    engine = _engine(tmp_path / "malformed-event-action-index.db")
    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _add_event_action_identity_columns(connection, "wallet_transfers")
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX "
            "uq_wallet_transfers_run_event_action_identity "
            "ON wallet_transfers (run_id, event_action_identity_key) "
            "WHERE event_action_identity_key IS NULL"
        )

    with pytest.raises(RuntimeError, match="indexes do not match revision 0005"):
        run_database_migrations(engine)

    transfer_indexes = {
        index["name"]: index
        for index in inspect(engine).get_indexes("wallet_transfers")
    }
    assert transfer_indexes[
        "uq_wallet_transfers_run_event_action_identity"
    ]["dialect_options"]
    assert "ix_wallet_transfers_event_action_identity_key" not in transfer_indexes
    assert "ix_wallet_transfers_event_action_identity_tuple" not in transfer_indexes
    swap_columns = {
        column["name"]
        for column in inspect(engine).get_columns("wallet_swaps")
    }
    assert swap_columns.isdisjoint(EVENT_ACTION_IDENTITY_COLUMNS)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == ACQUISITION_EVIDENCE_REVISION
    engine.dispose()


def test_event_action_identity_rejects_same_table_duplicate_before_indexes(
    tmp_path,
):
    engine = _engine(tmp_path / "duplicate-event-action-identity.db")
    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_event_action_transfer(connection, transfer_id=1, run_id=1)
        _insert_event_action_transfer(connection, transfer_id=2, run_id=1)

    with pytest.raises(
        RuntimeError,
        match="Duplicate provider event-action observation identities",
    ):
        run_database_migrations(engine)

    for table_name in ("wallet_transfers", "wallet_swaps"):
        assert all(
            "event_action" not in str(index.get("name"))
            for index in inspect(engine).get_indexes(table_name)
        )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == ACQUISITION_EVIDENCE_REVISION
    engine.dispose()


def test_event_action_identity_rejects_combined_transfer_swap_duplicate(
    tmp_path,
):
    engine = _engine(tmp_path / "cross-surface-event-action-identity.db")
    _upgrade_to_revision(engine, ACQUISITION_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_event_action_transfer(
            connection,
            transfer_id=1,
            run_id=1,
            event_id=EVENT_ACTION_ID,
            action_index=0,
        )
        _insert_event_action_swap(
            connection,
            swap_id=1,
            run_id=1,
            event_id=EVENT_ACTION_ID,
            action_index=0,
        )

    for _ in range(2):
        with pytest.raises(
            RuntimeError,
            match="appears in both wallet_transfers and wallet_swaps",
        ):
            run_database_migrations(engine)

    for table_name in ("wallet_transfers", "wallet_swaps"):
        assert all(
            "event_action" not in str(index.get("name"))
            for index in inspect(engine).get_indexes(table_name)
        )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == ACQUISITION_EVIDENCE_REVISION
    engine.dispose()


def test_event_action_identity_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "event-action-forward-only.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)

    with engine.begin() as connection:
        with pytest.raises(
            RuntimeError,
            match="Event-action identity downgrade would discard",
        ):
            command.downgrade(
                migration_config(connection),
                ACQUISITION_EVIDENCE_REVISION,
            )

    _assert_event_action_identity_schema(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == EVENT_ACTION_IDENTITY_REVISION
    engine.dispose()


def test_trace_evidence_upgrade_from_0005_is_empty_and_preserves_prior_data(
    tmp_path,
):
    engine = _engine(tmp_path / "trace-evidence-upgrade.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_transaction(connection, transaction_id=1, run_id=1)
    before = _data_snapshot(engine)

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == EVENT_ACTION_IDENTITY_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _data_snapshot(engine) == before
    assert _trace_evidence_counts(engine) == (0, 0, 0)
    assert _trace_boc_verification_counts(engine) == (0, 0)
    _assert_schema_matches_models(engine)
    _assert_trace_evidence_schema(engine)
    _assert_trace_boc_verification_schema(engine)
    engine.dispose()


def test_trace_evidence_migration_repairs_exact_empty_partial_sqlite_ddl(
    tmp_path,
):
    engine = _engine(tmp_path / "partial-trace-evidence.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, TRACE_CAPTURES_TABLE)
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_wallet_trace_captures_run_root "
            "ON wallet_trace_evidence_captures "
            "(run_id, provider, contract_version, root_transaction_hash)"
        )
        _create_model_table_without_indexes(connection, TRACE_NODES_TABLE)
        _create_model_table_without_indexes(connection, TRACE_MESSAGES_TABLE)

    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    _assert_trace_evidence_schema(engine)
    assert _trace_evidence_counts(engine) == (0, 0, 0)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRACE_EVIDENCE_REVISION
    engine.dispose()


def test_trace_evidence_orphan_partial_child_table_fails_before_more_ddl(
    tmp_path,
):
    engine = _engine(tmp_path / "orphan-partial-trace-node.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, TRACE_NODES_TABLE)

    with pytest.raises(RuntimeError, match="without its capture table"):
        _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    tables = set(inspect(engine).get_table_names())
    assert TRACE_CAPTURES_TABLE not in tables
    assert TRACE_MESSAGES_TABLE not in tables
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == EVENT_ACTION_IDENTITY_REVISION
    engine.dispose()


def test_trace_evidence_message_without_node_table_fails_closed(tmp_path):
    engine = _engine(tmp_path / "orphan-partial-trace-message.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, TRACE_CAPTURES_TABLE)
        _create_model_table_without_indexes(connection, TRACE_MESSAGES_TABLE)

    with pytest.raises(RuntimeError, match="without its node table"):
        _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    assert TRACE_NODES_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == EVENT_ACTION_IDENTITY_REVISION
    engine.dispose()


def test_trace_evidence_malformed_partial_columns_fail_before_child_ddl(
    tmp_path,
):
    engine = _engine(tmp_path / "malformed-partial-trace-columns.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, TRACE_CAPTURES_TABLE)
    _rewrite_table_sql(
        engine,
        TRACE_CAPTURES_TABLE,
        "provider VARCHAR(32)",
        "provider VARCHAR(64)",
    )

    with pytest.raises(RuntimeError, match="columns do not match revision 0006"):
        _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    tables = set(inspect(engine).get_table_names())
    assert TRACE_NODES_TABLE not in tables
    assert TRACE_MESSAGES_TABLE not in tables
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == EVENT_ACTION_IDENTITY_REVISION
    engine.dispose()


def test_trace_evidence_wrong_partial_index_fails_before_child_tables(
    tmp_path,
):
    engine = _engine(tmp_path / "wrong-partial-trace-index.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, TRACE_CAPTURES_TABLE)
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_wallet_trace_captures_run_root "
            "ON wallet_trace_evidence_captures "
            "(run_id, provider, root_transaction_hash, contract_version)"
        )

    with pytest.raises(RuntimeError, match="index does not match revision 0006"):
        _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    tables = set(inspect(engine).get_table_names())
    assert TRACE_NODES_TABLE not in tables
    assert TRACE_MESSAGES_TABLE not in tables
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == EVENT_ACTION_IDENTITY_REVISION
    engine.dispose()


def test_trace_evidence_wrong_partial_foreign_key_fails_closed(tmp_path):
    engine = _engine(tmp_path / "wrong-partial-trace-fk.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, TRACE_CAPTURES_TABLE)
    _rewrite_table_sql(
        engine,
        TRACE_CAPTURES_TABLE,
        " ON DELETE CASCADE",
        "",
    )

    with pytest.raises(
        RuntimeError,
        match="foreign keys do not match revision 0006",
    ):
        _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    assert TRACE_NODES_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == EVENT_ACTION_IDENTITY_REVISION
    engine.dispose()


def test_trace_evidence_pre_revision_rows_are_never_adopted(tmp_path):
    engine = _engine(tmp_path / "unexpected-trace-evidence-data.db")
    _upgrade_to_revision(engine, EVENT_ACTION_IDENTITY_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_transaction(connection, transaction_id=1, run_id=1)
        _create_model_table_without_indexes(connection, TRACE_CAPTURES_TABLE)
        connection.exec_driver_sql(
            "INSERT INTO wallet_trace_evidence_captures ("
            "id, run_id, captured_via_transaction_id, capture_slot, provider, "
            "contract_version, network, root_transaction_hash, trace_state, "
            "transaction_count, max_depth, message_count, "
            "root_inbound_message_count, child_internal_message_count, "
            "remaining_out_message_count, internal_message_count, "
            "external_in_message_count, external_out_message_count, "
            "successful_transaction_count, failed_transaction_count, "
            "aborted_transaction_count, unique_account_count, "
            "evidence_digest_sha256, captured_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?)",
            (
                1,
                1,
                1,
                0,
                "tonapi",
                "tonapi_low_level_trace_evidence_v1",
                "ton-mainnet",
                TRANSACTION_HASH,
                "finalized",
                1,
                0,
                1,
                1,
                0,
                0,
                1,
                0,
                0,
                1,
                0,
                0,
                1,
                "ab" * 32,
                "2026-07-10 12:00:00.000000",
            ),
        )

    with pytest.raises(RuntimeError, match="unexpected pre-revision data"):
        _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    assert TRACE_NODES_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == EVENT_ACTION_IDENTITY_REVISION
    engine.dispose()


def test_trace_evidence_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "trace-evidence-forward-only.db")
    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    with engine.begin() as connection:
        with pytest.raises(
            RuntimeError,
            match="Trace evidence downgrade would discard",
        ):
            command.downgrade(
                migration_config(connection),
                EVENT_ACTION_IDENTITY_REVISION,
            )

    _assert_trace_evidence_schema(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRACE_EVIDENCE_REVISION
    engine.dispose()


def test_trace_boc_verification_upgrade_from_0006_is_empty(tmp_path):
    engine = _engine(tmp_path / "trace-boc-verification-upgrade.db")
    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == TRACE_EVIDENCE_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _trace_boc_verification_counts(engine) == (0, 0)
    _assert_trace_boc_verification_schema(engine)
    engine.dispose()


def test_upgrade_from_0007_reaches_current_model_parity(tmp_path):
    engine = _engine(tmp_path / "native-activity-ledger-upgrade.db")
    _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == TRACE_BOC_VERIFICATION_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert {
        "wallet_native_activity_ledgers",
        "wallet_native_activity_rows",
    }.issubset(inspect(engine).get_table_names())
    engine.dispose()


def test_jetton_contract_verification_upgrade_from_0008_is_empty(tmp_path):
    engine = _engine(tmp_path / "jetton-contract-verification-upgrade.db")
    _upgrade_to_revision(engine, NATIVE_ACTIVITY_LEDGER_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == NATIVE_ACTIVITY_LEDGER_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert inspect(engine).get_table_names().count(
        JETTON_CONTRACT_VERIFICATIONS_TABLE
    ) == 1
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            f"SELECT COUNT(*) FROM {JETTON_CONTRACT_VERIFICATIONS_TABLE}"
        ).scalar_one() == 0
    assert JETTON_CONTRACT_VERIFICATIONS_TABLE in inspect(engine).get_table_names()
    engine.dispose()


def test_wallet_ownership_challenge_upgrade_from_0009_reaches_model_parity(tmp_path):
    engine = _engine(tmp_path / "wallet-ownership-challenge-upgrade.db")
    _upgrade_to_revision(engine, JETTON_CONTRACT_VERIFICATION_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == JETTON_CONTRACT_VERIFICATION_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    _assert_schema_matches_models(engine)
    engine.dispose()


def test_wallet_ownership_challenge_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "wallet-ownership-challenge-forward-only.db")
    _upgrade_to_revision(engine, WALLET_OWNERSHIP_CHALLENGE_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                JETTON_CONTRACT_VERIFICATION_REVISION,
            )
    assert "wallet_ownership_challenges" in inspect(engine).get_table_names()
    engine.dispose()


def test_account_state_inclusion_upgrade_from_0010_reaches_model_parity(tmp_path):
    engine = _engine(tmp_path / "account-state-inclusion-upgrade.db")
    _upgrade_to_revision(engine, WALLET_OWNERSHIP_CHALLENGE_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == WALLET_OWNERSHIP_CHALLENGE_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert "wallet_account_state_inclusion_proofs" in inspect(engine).get_table_names()
    engine.dispose()


def test_transaction_inclusion_upgrade_from_0011_reaches_model_parity(tmp_path):
    engine = _engine(tmp_path / "transaction-inclusion-upgrade.db")
    _upgrade_to_revision(engine, ACCOUNT_STATE_INCLUSION_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == ACCOUNT_STATE_INCLUSION_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert "wallet_transaction_inclusion_proofs" in inspect(engine).get_table_names()
    engine.dispose()


def test_dex_protocol_identity_upgrade_from_0012_reaches_model_parity(tmp_path):
    engine = _engine(tmp_path / "dex-protocol-identity-upgrade.db")
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == TRANSACTION_INCLUSION_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("wallet_swaps")
    }
    assert {"dex_protocol_id", "dex_protocol_status"}.issubset(columns)
    engine.dispose()


def test_ownership_network_scope_upgrade_from_0013_reaches_model_parity(tmp_path):
    engine = _engine(tmp_path / "ownership-network-scope-upgrade.db")
    _upgrade_to_revision(engine, DEX_PROTOCOL_IDENTITY_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == DEX_PROTOCOL_IDENTITY_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    engine.dispose()


def test_ownership_network_scope_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "ownership-network-scope-forward-only.db")
    _upgrade_to_revision(engine, OWNERSHIP_NETWORK_SCOPE_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would weaken"):
            command.downgrade(
                migration_config(connection),
                DEX_PROTOCOL_IDENTITY_REVISION,
            )
    assert WALLET_CASES_TABLE not in inspect(engine).get_table_names()
    assert WALLET_CASE_SYNCS_TABLE not in inspect(engine).get_table_names()
    engine.dispose()


def test_wallet_cases_upgrade_from_0014_preserves_runs_without_backfill(tmp_path):
    engine = _engine(tmp_path / "wallet-cases-upgrade.db")
    _upgrade_to_revision(engine, OWNERSHIP_NETWORK_SCOPE_REVISION)
    ingestion_runs = database.Base.metadata.tables["wallet_ingestion_runs"]
    with engine.begin() as connection:
        connection.execute(
            ingestion_runs.insert().values(
                wallet_address=BOUNCEABLE_MAINNET,
                time_window="24h",
                wallet_identity_status="network_scoped",
                wallet_identity_version="ton_account_v1",
                wallet_network="ton-mainnet",
                wallet_address_canonical=RAW_ADDRESS,
                wallet_workchain_id=0,
                wallet_account_id_hex=ACCOUNT_ID,
                wallet_address_format="friendly",
                wallet_address_bounceable=True,
                wallet_address_testnet_only=False,
            )
        )
    data_before = _data_snapshot(engine)

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == OWNERSHIP_NETWORK_SCOPE_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    assert _data_snapshot(engine) == data_before
    assert _wallet_case_counts(engine) == (0, 0)
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    engine.dispose()


def test_wallet_cases_migration_repairs_exact_empty_partial_sqlite_ddl(tmp_path):
    engine = _engine(tmp_path / "partial-wallet-cases.db")
    _upgrade_to_revision(engine, OWNERSHIP_NETWORK_SCOPE_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, WALLET_CASES_TABLE)
        _create_wallet_case_sync_0015_without_indexes(connection)

    _upgrade_to_revision(engine, WALLET_CASES_REVISION)

    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_CASES_REVISION
    assert _wallet_case_counts(engine) == (0, 0)
    sync_columns = {
        column["name"]
        for column in inspect(engine).get_columns(WALLET_CASE_SYNCS_TABLE)
    }
    assert "result_summary_json" not in sync_columns
    assert "message_safe" not in sync_columns

    _upgrade_to_revision(engine, CURRENT_REVISION)
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    engine.dispose()


def test_wallet_cases_malformed_partial_table_fails_before_sync_ddl(tmp_path):
    engine = _engine(tmp_path / "malformed-partial-wallet-cases.db")
    _upgrade_to_revision(engine, OWNERSHIP_NETWORK_SCOPE_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE wallet_cases (id INTEGER NOT NULL PRIMARY KEY)"
        )

    with pytest.raises(RuntimeError, match="columns do not match revision 0015"):
        _upgrade_to_revision(engine, WALLET_CASES_REVISION)

    assert WALLET_CASE_SYNCS_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == OWNERSHIP_NETWORK_SCOPE_REVISION
    engine.dispose()


def test_wallet_cases_migration_rejects_wrong_partial_index(tmp_path):
    engine = _engine(tmp_path / "wrong-partial-wallet-case-index.db")
    _upgrade_to_revision(engine, OWNERSHIP_NETWORK_SCOPE_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, WALLET_CASES_TABLE)
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_wallet_cases_public_id "
            "ON wallet_cases (canonical_wallet_key)"
        )

    with pytest.raises(RuntimeError, match="index does not match revision 0015"):
        _upgrade_to_revision(engine, WALLET_CASES_REVISION)

    assert WALLET_CASE_SYNCS_TABLE not in inspect(engine).get_table_names()
    engine.dispose()


def test_wallet_cases_migration_rejects_orphan_sync_fragment(tmp_path):
    engine = _engine(tmp_path / "orphan-wallet-case-sync.db")
    _upgrade_to_revision(engine, OWNERSHIP_NETWORK_SCOPE_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, WALLET_CASE_SYNCS_TABLE)

    with pytest.raises(RuntimeError, match="without its wallet_cases parent"):
        _upgrade_to_revision(engine, WALLET_CASES_REVISION)

    assert WALLET_CASES_TABLE not in inspect(engine).get_table_names()
    engine.dispose()


def test_wallet_cases_migration_rejects_pre_revision_case_rows(tmp_path):
    engine = _engine(tmp_path / "pre-revision-wallet-case-data.db")
    _upgrade_to_revision(engine, OWNERSHIP_NETWORK_SCOPE_REVISION)
    wallet_cases = database.Base.metadata.tables[WALLET_CASES_TABLE]
    with engine.begin() as connection:
        _create_model_table_without_indexes(connection, WALLET_CASES_TABLE)
        connection.execute(wallet_cases.insert().values(**_wallet_case_values()))

    with pytest.raises(RuntimeError, match="unexpected pre-revision data"):
        _upgrade_to_revision(engine, WALLET_CASES_REVISION)

    assert WALLET_CASE_SYNCS_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM wallet_cases"
        ).scalar_one() == 1
    engine.dispose()


def test_wallet_cases_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "wallet-cases-forward-only.db")
    _upgrade_to_revision(engine, WALLET_CASES_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                OWNERSHIP_NETWORK_SCOPE_REVISION,
            )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_CASES_REVISION
    sync_columns = {
        column["name"]
        for column in inspect(engine).get_columns(WALLET_CASE_SYNCS_TABLE)
    }
    assert "result_summary_json" not in sync_columns
    assert "message_safe" not in sync_columns
    engine.dispose()


def test_wallet_case_compact_results_upgrade_from_0015_preserves_rows(tmp_path):
    engine = _engine(tmp_path / "wallet-case-compact-results-upgrade.db")
    _upgrade_to_revision(engine, WALLET_CASES_REVISION)
    metadata = MetaData()
    wallet_cases = Table(
        WALLET_CASES_TABLE,
        metadata,
        autoload_with=engine,
    )
    case_syncs = Table(
        WALLET_CASE_SYNCS_TABLE,
        metadata,
        autoload_with=engine,
    )
    requested_start = datetime(2026, 8, 8, tzinfo=timezone.utc)
    requested_end = requested_start + timedelta(days=1)
    created_at = requested_end + timedelta(minutes=1)
    with engine.begin() as connection:
        case_id = connection.execute(
            wallet_cases.insert().values(
                public_id="11111111-1111-4111-8111-111111111111",
                **_wallet_case_values(),
                created_at=created_at,
                updated_at=created_at,
            )
        ).inserted_primary_key[0]
        connection.execute(
            case_syncs.insert().values(
                public_id="22222222-2222-4222-8222-222222222222",
                case_id=case_id,
                time_window="24h",
                data_mode="real",
                provider="tonapi_wallet_activity_live",
                requested_start=requested_start,
                requested_end=requested_end,
                requested_surfaces_json='["transactions"]',
                state="succeeded",
                stage="completed",
                progress_current=1,
                progress_total=1,
                coverage_summary_json='{"state":"unknown"}',
                created_at=created_at,
                updated_at=created_at,
                started_at=created_at,
                completed_at=created_at,
            )
        )

    report = run_database_migrations(engine)

    assert report.action == "upgraded"
    assert report.revision_before == WALLET_CASES_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT public_id, provider, coverage_summary_json, "
            "result_summary_json, message_safe "
            "FROM wallet_case_syncs"
        ).one()
    assert row == (
        "22222222-2222-4222-8222-222222222222",
        "tonapi_wallet_activity_live",
        '{"state":"unknown"}',
        "{}",
        (
            "Compact activity and portfolio summary is unavailable for this "
            "pre-0016 synchronization. Zero placeholders are not evidence of "
            "no activity."
        ),
    )
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    engine.dispose()


def test_wallet_case_compact_results_repairs_exact_partial_sqlite_ddl(tmp_path):
    engine = _engine(tmp_path / "partial-wallet-case-compact-results.db")
    _upgrade_to_revision(engine, WALLET_CASES_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE wallet_case_syncs ADD COLUMN "
            "result_summary_json TEXT DEFAULT '{}' NOT NULL"
        )

    _upgrade_to_revision(engine, WALLET_CASE_COMPACT_RESULTS_REVISION)

    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_CASE_COMPACT_RESULTS_REVISION
    _upgrade_to_revision(engine, CURRENT_REVISION)
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    engine.dispose()


@pytest.mark.parametrize(
    "partial_columns",
    [
        (
            "message_safe TEXT DEFAULT '' NOT NULL",
        ),
        (
            "message_safe TEXT DEFAULT '' NOT NULL",
            "result_summary_json TEXT DEFAULT '{}' NOT NULL",
        ),
    ],
)
def test_wallet_case_compact_results_rejects_impossible_column_order(
    tmp_path,
    partial_columns,
):
    engine = _engine(
        tmp_path / f"impossible-wallet-case-compact-{len(partial_columns)}.db"
    )
    _upgrade_to_revision(engine, WALLET_CASES_REVISION)
    with engine.begin() as connection:
        for definition in partial_columns:
            connection.exec_driver_sql(
                "ALTER TABLE wallet_case_syncs ADD COLUMN " + definition
            )

    with pytest.raises(RuntimeError, match="column order/state"):
        _upgrade_to_revision(engine, WALLET_CASE_COMPACT_RESULTS_REVISION)

    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_CASES_REVISION
    engine.dispose()


def test_wallet_case_compact_results_rejects_malformed_partial_column(tmp_path):
    engine = _engine(tmp_path / "malformed-wallet-case-compact-results.db")
    _upgrade_to_revision(engine, WALLET_CASES_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE wallet_case_syncs ADD COLUMN "
            "result_summary_json INTEGER DEFAULT 0 NOT NULL"
        )

    with pytest.raises(RuntimeError, match="do not match revision 0016"):
        _upgrade_to_revision(engine, WALLET_CASE_COMPACT_RESULTS_REVISION)

    columns = {
        column["name"]
        for column in inspect(engine).get_columns(WALLET_CASE_SYNCS_TABLE)
    }
    assert "message_safe" not in columns
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_CASES_REVISION
    engine.dispose()


def test_wallet_case_compact_results_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "wallet-case-compact-results-forward-only.db")
    _upgrade_to_revision(engine, WALLET_CASE_COMPACT_RESULTS_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                WALLET_CASES_REVISION,
            )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == WALLET_CASE_COMPACT_RESULTS_REVISION
    _assert_wallet_case_schema(engine)
    engine.dispose()


def test_case_sync_jobs_upgrade_normalizes_legacy_active_rows_and_enforces_slots(
    tmp_path,
):
    engine = _engine(tmp_path / "case-sync-jobs-upgrade.db")
    _upgrade_to_revision(engine, WALLET_CASE_COMPACT_RESULTS_REVISION)
    metadata = MetaData()
    wallet_cases = Table(WALLET_CASES_TABLE, metadata, autoload_with=engine)
    case_syncs = Table(WALLET_CASE_SYNCS_TABLE, metadata, autoload_with=engine)
    created_at = datetime(2026, 8, 9, tzinfo=timezone.utc)
    with engine.begin() as connection:
        case_id = connection.execute(
            wallet_cases.insert().values(
                public_id="33333333-3333-4333-8333-333333333333",
                **_wallet_case_values(),
                created_at=created_at,
                updated_at=created_at,
            )
        ).inserted_primary_key[0]
        connection.execute(
            case_syncs.insert().values(
                public_id="44444444-4444-4444-8444-444444444444",
                **_wallet_case_sync_values(
                    case_id,
                    state="running",
                    stage="ingesting",
                    created_at=created_at,
                    updated_at=created_at,
                ),
            )
        )

    report = run_database_migrations(engine)

    assert report.revision_before == WALLET_CASE_COMPACT_RESULTS_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    with engine.connect() as connection:
        legacy = connection.exec_driver_sql(
            "SELECT state, stage, error_code, completed_at, status_version "
            "FROM wallet_case_syncs WHERE public_id = ?",
            ("44444444-4444-4444-8444-444444444444",),
        ).one()
    assert legacy[0:3] == (
        "failed",
        "failed",
        "legacy_sync_not_resumable",
    )
    assert legacy.completed_at is not None
    assert legacy.status_version == 2

    current = database.Base.metadata.tables[WALLET_CASE_SYNCS_TABLE]
    active_values = _wallet_case_sync_values(
        case_id,
        public_id="55555555-5555-4555-8555-555555555555",
        state="queued",
        stage="queued",
        next_attempt_at=created_at,
        idempotency_key="66666666-6666-4666-8666-666666666666",
        request_fingerprint="ab" * 32,
        created_at=created_at,
        updated_at=created_at,
    )
    with engine.begin() as connection:
        connection.execute(current.insert().values(**active_values))
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                current.insert().values(
                    **{
                        **active_values,
                        "public_id": "77777777-7777-4777-8777-777777777777",
                        "idempotency_key": "88888888-8888-4888-8888-888888888888",
                    }
                )
            )
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                current.insert().values(
                    **{
                        **active_values,
                        "public_id": "99999999-9999-4999-8999-999999999999",
                        "state": "failed",
                        "stage": "failed",
                        "completed_at": created_at,
                    }
                )
            )
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    engine.dispose()


@pytest.mark.parametrize("prefix_count", range(1, 12))
def test_case_sync_jobs_repairs_each_exact_partial_column_prefix(
    tmp_path,
    prefix_count,
):
    engine = _engine(tmp_path / f"partial-case-sync-jobs-{prefix_count}.db")
    _upgrade_to_revision(engine, WALLET_CASE_COMPACT_RESULTS_REVISION)
    with engine.begin() as connection:
        for definition in CASE_SYNC_JOB_PARTIAL_COLUMNS[:prefix_count]:
            connection.exec_driver_sql(
                "ALTER TABLE wallet_case_syncs ADD COLUMN " + definition
            )

    _upgrade_to_revision(engine, CASE_ACTIVITY_INDEXES_REVISION)

    _upgrade_to_revision(engine, CURRENT_REVISION)
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    engine.dispose()


@pytest.mark.parametrize("index_prefix_count", range(1, 4))
def test_case_sync_jobs_repairs_each_exact_partial_index_prefix(
    tmp_path,
    index_prefix_count,
):
    engine = _engine(
        tmp_path / f"partial-case-sync-job-indexes-{index_prefix_count}.db"
    )
    _upgrade_to_revision(engine, WALLET_CASE_COMPACT_RESULTS_REVISION)
    index_statements = (
        "CREATE UNIQUE INDEX uq_wallet_case_syncs_case_idempotency "
        "ON wallet_case_syncs (case_id, idempotency_key)",
        "CREATE UNIQUE INDEX uq_wallet_case_syncs_one_active "
        "ON wallet_case_syncs (case_id) "
        "WHERE state IN ('queued', 'running')",
        "CREATE INDEX ix_wallet_case_syncs_queue "
        "ON wallet_case_syncs (state, next_attempt_at, created_at, id)",
    )
    with engine.begin() as connection:
        for definition in CASE_SYNC_JOB_PARTIAL_COLUMNS:
            connection.exec_driver_sql(
                "ALTER TABLE wallet_case_syncs ADD COLUMN " + definition
            )
        for statement in index_statements[:index_prefix_count]:
            connection.exec_driver_sql(statement)

    _upgrade_to_revision(engine, CASE_ACTIVITY_INDEXES_REVISION)

    _upgrade_to_revision(engine, CURRENT_REVISION)
    _assert_schema_matches_models(engine)
    _assert_wallet_case_schema(engine)
    engine.dispose()


def test_case_sync_jobs_rejects_malformed_partial_column_and_is_forward_only(
    tmp_path,
):
    malformed = _engine(tmp_path / "malformed-case-sync-jobs.db")
    _upgrade_to_revision(malformed, WALLET_CASE_COMPACT_RESULTS_REVISION)
    with malformed.begin() as connection:
        connection.exec_driver_sql(
            "ALTER TABLE wallet_case_syncs ADD COLUMN "
            "status_version TEXT DEFAULT 'wrong' NOT NULL"
        )
    with pytest.raises(RuntimeError, match="do not match revision 0017"):
        _upgrade_to_revision(malformed, CASE_SYNC_JOBS_REVISION)
    malformed.dispose()

    wrong_index = _engine(tmp_path / "wrong-case-sync-jobs-index.db")
    _upgrade_to_revision(wrong_index, WALLET_CASE_COMPACT_RESULTS_REVISION)
    with wrong_index.begin() as connection:
        for definition in CASE_SYNC_JOB_PARTIAL_COLUMNS:
            connection.exec_driver_sql(
                "ALTER TABLE wallet_case_syncs ADD COLUMN " + definition
            )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_wallet_case_syncs_case_idempotency "
            "ON wallet_case_syncs (idempotency_key, case_id)"
        )
    with pytest.raises(RuntimeError, match="does not match revision 0017"):
        _upgrade_to_revision(wrong_index, CASE_SYNC_JOBS_REVISION)
    wrong_index.dispose()

    forward_only = _engine(tmp_path / "case-sync-jobs-forward-only.db")
    _upgrade_to_revision(forward_only, CASE_SYNC_JOBS_REVISION)
    with forward_only.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                WALLET_CASE_COMPACT_RESULTS_REVISION,
            )
    with forward_only.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_SYNC_JOBS_REVISION
    forward_only.dispose()


CASE_ACTIVITY_INDEX_DEFINITIONS = (
    (
        "wallet_case_syncs",
        "ix_wallet_case_syncs_case_activity",
        ("case_id", "state", "id", "ingestion_run_id"),
    ),
    (
        "wallet_transactions",
        "ix_wallet_transactions_run_timeline",
        ("run_id", "timestamp", "id"),
    ),
    (
        "wallet_transfers",
        "ix_wallet_transfers_run_timeline",
        ("run_id", "timestamp", "id"),
    ),
    (
        "wallet_swaps",
        "ix_wallet_swaps_run_timeline",
        ("run_id", "timestamp", "id"),
    ),
)


def _create_case_activity_index(connection, definition):
    table, name, columns = definition
    rendered_columns = ", ".join(columns)
    connection.exec_driver_sql(
        f"CREATE INDEX {name} ON {table} ({rendered_columns})"
    )


@pytest.mark.parametrize("prefix_count", range(5))
def test_case_activity_indexes_resume_each_exact_partial_prefix(
    tmp_path,
    prefix_count,
):
    engine = _engine(tmp_path / f"partial-case-activity-{prefix_count}.db")
    _upgrade_to_revision(engine, CASE_SYNC_JOBS_REVISION)
    with engine.begin() as connection:
        for definition in CASE_ACTIVITY_INDEX_DEFINITIONS[:prefix_count]:
            _create_case_activity_index(connection, definition)

    _upgrade_to_revision(engine, CASE_ACTIVITY_INDEXES_REVISION)

    _upgrade_to_revision(engine, CURRENT_REVISION)
    _assert_schema_matches_models(engine)
    inspector = inspect(engine)
    for table, name, columns in CASE_ACTIVITY_INDEX_DEFINITIONS:
        reflected = {
            index["name"]: index for index in inspector.get_indexes(table)
        }
        assert tuple(reflected[name]["column_names"]) == columns
        assert bool(reflected[name]["unique"]) is False
    engine.dispose()


@pytest.mark.parametrize(
    ("table", "name", "statement"),
    (
        (
            "wallet_case_syncs",
            "ix_wallet_case_syncs_case_activity",
            "CREATE INDEX ix_wallet_case_syncs_case_activity "
            "ON wallet_case_syncs (case_id, id)",
        ),
        (
            "wallet_transactions",
            "ix_wallet_transactions_run_timeline",
            "CREATE UNIQUE INDEX ix_wallet_transactions_run_timeline "
            "ON wallet_transactions (run_id, timestamp, id)",
        ),
    ),
)
def test_case_activity_indexes_reject_wrong_existing_signatures(
    tmp_path,
    table,
    name,
    statement,
):
    engine = _engine(tmp_path / f"wrong-{table}.db")
    _upgrade_to_revision(engine, CASE_SYNC_JOBS_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(statement)

    with pytest.raises(RuntimeError, match=f"Existing index {name}"):
        _upgrade_to_revision(engine, CASE_ACTIVITY_INDEXES_REVISION)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_SYNC_JOBS_REVISION
    engine.dispose()


def test_case_activity_indexes_require_source_tables_and_are_forward_only(
    tmp_path,
):
    missing = _engine(tmp_path / "missing-case-activity-source.db")
    _upgrade_to_revision(missing, CASE_SYNC_JOBS_REVISION)
    with missing.begin() as connection:
        connection.exec_driver_sql("DROP TABLE wallet_swaps")
    with pytest.raises(RuntimeError, match="requires Wallet Case activity"):
        _upgrade_to_revision(missing, CASE_ACTIVITY_INDEXES_REVISION)
    missing.dispose()

    forward_only = _engine(tmp_path / "case-activity-forward-only.db")
    _upgrade_to_revision(forward_only, CASE_ACTIVITY_INDEXES_REVISION)
    with forward_only.begin() as connection:
        with pytest.raises(RuntimeError, match="intentionally unsupported"):
            command.downgrade(
                migration_config(connection),
                CASE_SYNC_JOBS_REVISION,
            )
    with forward_only.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_ACTIVITY_INDEXES_REVISION
    forward_only.dispose()


CASE_EVIDENCE_INDEX_DEFINITIONS = (
    (
        "uq_wallet_case_evidence_public_id",
        ("public_id",),
        True,
    ),
    (
        "uq_wallet_case_evidence_idempotency",
        ("case_id", "idempotency_key"),
        True,
    ),
    (
        "uq_wallet_case_evidence_active_selection",
        ("case_id", "snapshot_sync_id", "activity_public_id", "policy"),
        True,
    ),
    (
        "ix_wallet_case_evidence_catalog",
        ("case_id", "snapshot_sync_id", "created_at", "id"),
        False,
    ),
    (
        "ix_wallet_case_evidence_queue",
        ("state", "next_attempt_at", "created_at", "id"),
        False,
    ),
    (
        "ix_wallet_case_evidence_source_transaction",
        ("source_transaction_id", "state"),
        False,
    ),
)


def _stamp_revision(connection, revision: str) -> None:
    statement = "UPDATE alembic_version SET version_num=?"
    if hasattr(connection, "exec_driver_sql"):
        connection.exec_driver_sql(statement, (revision,))
    else:
        connection.execute(statement, (revision,))


def _insert_raw_case_evidence(
    connection: sqlite3.Connection,
    **overrides: Any,
) -> None:
    now = "2026-08-11 12:00:00.000000"
    values: dict[str, Any] = {
        "public_id": "11111111-1111-4111-8111-111111111111",
        "case_id": 991,
        "snapshot_sync_id": 992,
        "source_sync_id": 992,
        "source_transaction_id": 993,
        "activity_public_id": "tx:" + "ab" * 32,
        "activity_semantic_fingerprint": "cd" * 32,
        "provider": "tonapi",
        "network": "ton-mainnet",
        "wallet_account_canonical": RAW_ADDRESS,
        "transaction_hash": TRANSACTION_HASH,
        "transaction_logical_time": TRANSACTION_LT,
        "idempotency_key": "22222222-2222-4222-8222-222222222222",
        "request_fingerprint": "ef" * 32,
        "next_attempt_at": now,
        "created_at": now,
        "updated_at": now,
    }
    values.update(overrides)
    columns = ", ".join(values)
    placeholders = ", ".join("?" for _ in values)
    connection.execute(
        f"INSERT INTO {CASE_EVIDENCE_VERIFICATIONS_TABLE} "
        f"({columns}) VALUES ({placeholders})",
        tuple(values.values()),
    )


@pytest.mark.parametrize("index_prefix_count", range(7))
def test_case_evidence_migration_resumes_each_exact_partial_index_prefix(
    tmp_path,
    index_prefix_count,
):
    engine = _engine(
        tmp_path / f"partial-case-evidence-indexes-{index_prefix_count}.db"
    )
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    with engine.begin() as connection:
        for name, _columns, _unique in CASE_EVIDENCE_INDEX_DEFINITIONS[
            index_prefix_count:
        ]:
            connection.exec_driver_sql(f'DROP INDEX "{name}"')
        _stamp_revision(connection, CASE_ACTIVITY_INDEXES_REVISION)

    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)

    reflected = {
        str(item["name"]): item
        for item in inspect(engine).get_indexes(CASE_EVIDENCE_VERIFICATIONS_TABLE)
    }
    assert set(reflected) == {
        definition[0] for definition in CASE_EVIDENCE_INDEX_DEFINITIONS
    }
    for name, columns, unique in CASE_EVIDENCE_INDEX_DEFINITIONS:
        assert tuple(reflected[name]["column_names"]) == columns
        assert bool(reflected[name]["unique"]) is unique
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_EVIDENCE_VERIFICATIONS_REVISION
    engine.dispose()


def test_case_evidence_migration_rejects_wrong_partial_index(tmp_path):
    engine = _engine(tmp_path / "wrong-case-evidence-index.db")
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX uq_wallet_case_evidence_idempotency")
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_wallet_case_evidence_idempotency "
            "ON wallet_case_evidence_verifications (idempotency_key, case_id)"
        )
        _stamp_revision(connection, CASE_ACTIVITY_INDEXES_REVISION)

    with pytest.raises(RuntimeError, match="does not match revision 0019"):
        _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_ACTIVITY_INDEXES_REVISION
    engine.dispose()


@pytest.mark.parametrize(
    ("old", "new", "message"),
    (
        (
            "FOREIGN KEY(source_transaction_id) REFERENCES wallet_transactions (id) ON DELETE RESTRICT",
            "FOREIGN KEY(source_transaction_id) REFERENCES wallet_transfers (id) ON DELETE RESTRICT",
            "foreign keys do not match revision 0019",
        ),
        (
            "FOREIGN KEY(trace_capture_id) REFERENCES wallet_trace_evidence_captures (id) ON DELETE RESTRICT",
            "FOREIGN KEY(trace_capture_id) REFERENCES wallet_trace_evidence_captures (id) ON DELETE CASCADE",
            "foreign keys do not match revision 0019",
        ),
        (
            "FOREIGN KEY(native_ledger_id) REFERENCES wallet_native_activity_ledgers (id) ON DELETE RESTRICT",
            "CHECK (native_ledger_id IS NULL OR native_ledger_id >= 0)",
            "foreign keys do not match revision 0019",
        ),
        (
            "CONSTRAINT ck_wallet_case_evidence_state CHECK",
            "CONSTRAINT ck_wallet_case_evidence_state_missing CHECK",
            "checks do not match revision 0019",
        ),
        (
            "progress_current >= 0 AND progress_current <= 4",
            "progress_current >= 0 AND progress_current <= 5",
            "checks do not match revision 0019",
        ),
        (
            "stage IN ('queued', 'retry_wait')",
            "stage IN ('queued', 'retry_wait', 'validating')",
            "checks do not match revision 0019",
        ),
        (
            "progress_current = 4 AND trace_capture_id IS NOT NULL",
            "progress_current >= 4 AND trace_capture_id IS NOT NULL",
            "checks do not match revision 0019",
        ),
    ),
)
def test_case_evidence_migration_rejects_fk_and_named_check_drift(
    tmp_path,
    old,
    new,
    message,
):
    engine = _engine(tmp_path / f"case-evidence-drift-{abs(hash(old))}.db")
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    _rewrite_table_sql(
        engine,
        CASE_EVIDENCE_VERIFICATIONS_TABLE,
        old,
        new,
    )
    with engine.begin() as connection:
        _stamp_revision(connection, CASE_ACTIVITY_INDEXES_REVISION)

    with pytest.raises(RuntimeError, match=message):
        _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_ACTIVITY_INDEXES_REVISION
    engine.dispose()


def test_case_evidence_migration_never_adopts_pre_revision_rows(tmp_path):
    path = tmp_path / "pre-revision-case-evidence-data.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        _insert_raw_case_evidence(connection)
        _stamp_revision(connection, CASE_ACTIVITY_INDEXES_REVISION)

    engine = _engine(path)
    with pytest.raises(RuntimeError, match="cannot be adopted by revision 0019"):
        _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_ACTIVITY_INDEXES_REVISION
        assert connection.exec_driver_sql(
            "SELECT COUNT(*) FROM wallet_case_evidence_verifications"
        ).scalar_one() == 1
    engine.dispose()


@pytest.mark.parametrize(
    "overrides",
    (
        {"state": "queued", "stage": "validating"},
        {
            "state": "running",
            "stage": "queued",
            "next_attempt_at": None,
            "lease_token": "lease",
            "lease_expires_at": "2026-08-11 12:05:00.000000",
            "started_at": "2026-08-11 12:00:00.000000",
        },
        {
            "state": "running",
            "stage": "validating",
            "next_attempt_at": None,
            "started_at": "2026-08-11 12:00:00.000000",
        },
        {
            "state": "failed",
            "stage": "validating",
            "next_attempt_at": None,
            "completed_at": "2026-08-11 12:00:00.000000",
        },
        {"cancel_requested_at": "2026-08-11 12:00:00.000000"},
        {
            "state": "cancelled",
            "stage": "terminal",
            "next_attempt_at": None,
            "completed_at": "2026-08-11 12:00:00.000000",
        },
        {
            "progress_current": 2,
            "highest_evidence_level": "locally_verified",
            "boc_verification_id": 997,
            "boc_digest_sha256": "aa" * 32,
            "boc_completed_at": "2026-08-11 12:00:00.000000",
        },
    ),
)
def test_case_evidence_database_checks_reject_invalid_lifecycle_and_prefix(
    tmp_path,
    overrides,
):
    path = tmp_path / f"invalid-case-evidence-{abs(hash(repr(overrides)))}.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    engine.dispose()

    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_raw_case_evidence(connection, **overrides)


def test_case_evidence_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "case-evidence-forward-only.db")
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                CASE_ACTIVITY_INDEXES_REVISION,
            )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_EVIDENCE_VERIFICATIONS_REVISION
    engine.dispose()


def _insert_raw_transaction_inclusion_proof(
    connection: sqlite3.Connection,
    *,
    trust_level: int,
    boc_transaction_id: int = 995,
    digest: str = "ab" * 32,
) -> None:
    connection.execute(
        "INSERT INTO wallet_transaction_inclusion_proofs ("
        "boc_transaction_id, network, trust_level, account_address_canonical, "
        "logical_time, transaction_hash, block_workchain, block_shard, "
        "block_seqno, block_root_hash, block_file_hash, anchor_workchain, "
        "anchor_shard, anchor_seqno, anchor_root_hash, anchor_file_hash, "
        "block_proof_boc_hex, transaction_boc_sha256, "
        "block_proof_boc_sha256, evidence_digest_sha256, verified_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            boc_transaction_id,
            "ton-mainnet",
            trust_level,
            RAW_ADDRESS,
            TRANSACTION_LT,
            TRANSACTION_HASH,
            0,
            "-9223372036854775808",
            100,
            "01" * 32,
            "02" * 32,
            -1,
            "-9223372036854775808",
            200,
            "03" * 32,
            "04" * 32,
            "00",
            "05" * 32,
            "06" * 32,
            digest,
            "2026-08-11 12:00:00.000000",
        ),
    )


@pytest.mark.parametrize("resume_state", ("old_only", "both", "new_only"))
def test_transaction_inclusion_trust_migration_resumes_every_exact_index_state(
    tmp_path,
    resume_state,
):
    engine = _engine(tmp_path / f"transaction-trust-resume-{resume_state}.db")
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    with engine.begin() as connection:
        if resume_state in {"both", "new_only"}:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX "
                "uq_wallet_transaction_inclusion_boc_transaction_trust "
                "ON wallet_transaction_inclusion_proofs "
                "(boc_transaction_id, trust_level)"
            )
        if resume_state == "new_only":
            connection.exec_driver_sql(
                "DROP INDEX uq_wallet_transaction_inclusion_boc_transaction"
            )

    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_TRUST_REVISION)

    indexes = {
        item["name"]: item
        for item in inspect(engine).get_indexes(
            "wallet_transaction_inclusion_proofs"
        )
    }
    assert set(indexes) == {
        "ix_wallet_transaction_inclusion_digest",
        "uq_wallet_transaction_inclusion_boc_transaction_trust",
    }
    assert tuple(
        indexes["uq_wallet_transaction_inclusion_boc_transaction_trust"][
            "column_names"
        ]
    ) == ("boc_transaction_id", "trust_level")
    assert bool(
        indexes["uq_wallet_transaction_inclusion_boc_transaction_trust"][
            "unique"
        ]
    ) is True
    engine.dispose()


def test_transaction_inclusion_trust_migration_preserves_old_proof_and_versions_it(
    tmp_path,
):
    path = tmp_path / "transaction-trust-preserve.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        _insert_raw_transaction_inclusion_proof(connection, trust_level=1)

    engine = _engine(path)
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_TRUST_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT trust_level, evidence_digest_sha256 "
            "FROM wallet_transaction_inclusion_proofs"
        ).fetchall() == [(1, "ab" * 32)]
        _insert_raw_transaction_inclusion_proof(
            connection,
            trust_level=0,
            digest="cd" * 32,
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_raw_transaction_inclusion_proof(
                connection,
                trust_level=1,
                digest="ef" * 32,
            )
        assert connection.execute(
            "SELECT trust_level FROM wallet_transaction_inclusion_proofs "
            "ORDER BY trust_level"
        ).fetchall() == [(0,), (1,)]


@pytest.mark.parametrize(
    "mutation",
    ("wrong_new", "missing_both", "unsupported_trust"),
)
def test_transaction_inclusion_trust_migration_rejects_unresumable_schema(
    tmp_path,
    mutation,
):
    path = tmp_path / f"transaction-trust-reject-{mutation}.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, CASE_EVIDENCE_VERIFICATIONS_REVISION)
    if mutation == "wrong_new":
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX "
                "uq_wallet_transaction_inclusion_boc_transaction_trust "
                "ON wallet_transaction_inclusion_proofs "
                "(trust_level, boc_transaction_id)"
            )
    elif mutation == "missing_both":
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP INDEX uq_wallet_transaction_inclusion_boc_transaction"
            )
    else:
        engine.dispose()
        with sqlite3.connect(path) as connection:
            _insert_raw_transaction_inclusion_proof(
                connection,
                trust_level=2,
            )
        engine = _engine(path)

    with pytest.raises(RuntimeError, match="revision 0020|unsupported"):
        _upgrade_to_revision(engine, TRANSACTION_INCLUSION_TRUST_REVISION)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_EVIDENCE_VERIFICATIONS_REVISION
    engine.dispose()


def test_transaction_inclusion_trust_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "transaction-trust-forward-only.db")
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_TRUST_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="intentionally unsupported"):
            command.downgrade(
                migration_config(connection),
                CASE_EVIDENCE_VERIFICATIONS_REVISION,
            )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRANSACTION_INCLUSION_TRUST_REVISION
    # Model parity is defined at the current head. Preserve the exact 0020
    # forward-only assertion above, then apply the additive 0021 columns
    # before comparing the reflected schema with current metadata.
    _upgrade_to_revision(engine, CURRENT_REVISION)
    _assert_schema_matches_models(engine)
    engine.dispose()


CHECKPOINT_POLICY = "ton_liteserver_checkpoint_2026_08_v1"
STRICT_CHECKPOINT_POLICY = "ton_liteserver_checkpoint_strict_2026_08_v2"
LEGACY_CHECKPOINT_POLICY = "legacy_unpinned_v1"
MAINNET_CHECKPOINT = (
    -1,
    "-9223372036854775808",
    46894135,
    "3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f",
    "bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed",
)


def _checkpoint_column_sql() -> tuple[str, ...]:
    return (
        "verifier_policy_id VARCHAR(64) DEFAULT 'legacy_unpinned_v1' NOT NULL",
        "trusted_checkpoint_workchain INTEGER",
        "trusted_checkpoint_shard VARCHAR(24)",
        "trusted_checkpoint_seqno INTEGER",
        "trusted_checkpoint_root_hash VARCHAR(64)",
        "trusted_checkpoint_file_hash VARCHAR(64)",
    )


def _insert_raw_current_checkpoint_proof(
    connection: sqlite3.Connection,
    *,
    policy: str = CHECKPOINT_POLICY,
    network: str = "ton-mainnet",
    checkpoint: tuple[Any, ...] = MAINNET_CHECKPOINT,
    digest: str = "cd" * 32,
) -> None:
    connection.execute(
        "INSERT INTO wallet_transaction_inclusion_proofs ("
        "boc_transaction_id, network, trust_level, account_address_canonical, "
        "logical_time, transaction_hash, block_workchain, block_shard, "
        "block_seqno, block_root_hash, block_file_hash, anchor_workchain, "
        "anchor_shard, anchor_seqno, anchor_root_hash, anchor_file_hash, "
        "block_proof_boc_hex, transaction_boc_sha256, "
        "block_proof_boc_sha256, evidence_digest_sha256, verified_at, "
        "verifier_policy_id, trusted_checkpoint_workchain, "
        "trusted_checkpoint_shard, trusted_checkpoint_seqno, "
        "trusted_checkpoint_root_hash, trusted_checkpoint_file_hash"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            995,
            network,
            0,
            RAW_ADDRESS,
            TRANSACTION_LT,
            TRANSACTION_HASH,
            0,
            "-9223372036854775808",
            100,
            "01" * 32,
            "02" * 32,
            -1,
            "-9223372036854775808",
            200,
            "03" * 32,
            "04" * 32,
            "00",
            "05" * 32,
            "06" * 32,
            digest,
            "2026-08-11 12:00:00.000000",
            policy,
            *checkpoint,
        ),
    )


@pytest.mark.parametrize(
    ("prefix", "index_state", "one_trigger"),
    (
        (0, "old", False),
        (3, "old", False),
        (6, "old", False),
        (6, "both", False),
        (6, "new", False),
        (6, "new", True),
    ),
)
def test_transaction_checkpoint_migration_resumes_exact_prefix_states(
    tmp_path,
    prefix,
    index_state,
    one_trigger,
):
    engine = _engine(
        tmp_path / f"checkpoint-resume-{prefix}-{index_state}-{one_trigger}.db"
    )
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_TRUST_REVISION)
    with engine.begin() as connection:
        for ddl in _checkpoint_column_sql()[:prefix]:
            connection.exec_driver_sql(
                f"ALTER TABLE wallet_transaction_inclusion_proofs ADD COLUMN {ddl}"
            )
        if index_state in {"both", "new"}:
            connection.exec_driver_sql(
                "CREATE UNIQUE INDEX "
                "uq_wallet_transaction_inclusion_boc_transaction_trust_policy "
                "ON wallet_transaction_inclusion_proofs "
                "(boc_transaction_id, trust_level, verifier_policy_id)"
            )
        if index_state == "new":
            connection.exec_driver_sql(
                "DROP INDEX uq_wallet_transaction_inclusion_boc_transaction_trust"
            )
        if one_trigger:
            from importlib import import_module

            migration = import_module(
                "migrations.versions.20260710_0021_transaction_inclusion_pinned_checkpoints"
            )
            connection.exec_driver_sql(
                migration._trigger_sql(migration._INSERT_TRIGGER, "INSERT")
            )

    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_CHECKPOINT_REVISION)
    inspector = inspect(engine)
    columns = {row["name"] for row in inspector.get_columns(
        "wallet_transaction_inclusion_proofs"
    )}
    assert {value.split()[0] for value in _checkpoint_column_sql()}.issubset(columns)
    indexes = {
        row["name"]: tuple(row.get("column_names") or ())
        for row in inspector.get_indexes("wallet_transaction_inclusion_proofs")
    }
    assert indexes["uq_wallet_transaction_inclusion_boc_transaction_trust_policy"] == (
        "boc_transaction_id",
        "trust_level",
        "verifier_policy_id",
    )
    with engine.connect() as connection:
        assert {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND "
                "tbl_name='wallet_transaction_inclusion_proofs'"
            )
        } == {
            "ck_wallet_transaction_inclusion_checkpoint_insert",
            "ck_wallet_transaction_inclusion_checkpoint_update",
        }
    engine.dispose()


def test_transaction_checkpoint_migration_preserves_legacy_and_allows_pinned_upgrade(
    tmp_path,
):
    path = tmp_path / "checkpoint-preserve.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_TRUST_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        _insert_raw_transaction_inclusion_proof(connection, trust_level=0)

    engine = _engine(path)
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_CHECKPOINT_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT verifier_policy_id, trusted_checkpoint_root_hash FROM "
            "wallet_transaction_inclusion_proofs"
        ).fetchall() == [(LEGACY_CHECKPOINT_POLICY, None)]
        _insert_raw_current_checkpoint_proof(connection)
        with pytest.raises(sqlite3.IntegrityError):
            _insert_raw_current_checkpoint_proof(connection, digest="ef" * 32)
        assert connection.execute(
            "SELECT verifier_policy_id FROM wallet_transaction_inclusion_proofs "
            "ORDER BY verifier_policy_id"
        ).fetchall() == [
            (LEGACY_CHECKPOINT_POLICY,),
            (CHECKPOINT_POLICY,),
        ]


@pytest.mark.parametrize(
    ("policy", "network", "checkpoint"),
    (
        ("forged_policy", "ton-mainnet", MAINNET_CHECKPOINT),
        (
            CHECKPOINT_POLICY,
            "ton-mainnet",
            (-1, "-9223372036854775808", 46894135, "ff" * 32, "aa" * 32),
        ),
        (CHECKPOINT_POLICY, "ton-testnet", MAINNET_CHECKPOINT),
        (CHECKPOINT_POLICY, "ton-mainnet", (None, None, None, None, None)),
        (
            LEGACY_CHECKPOINT_POLICY,
            "ton-mainnet",
            MAINNET_CHECKPOINT,
        ),
    ),
)
def test_transaction_checkpoint_triggers_reject_impossible_provenance(
    tmp_path,
    policy,
    network,
    checkpoint,
):
    path = tmp_path / f"checkpoint-trigger-{abs(hash((policy, network, checkpoint)))}.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_CHECKPOINT_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_raw_current_checkpoint_proof(
                connection,
                policy=policy,
                network=network,
                checkpoint=checkpoint,
            )


@pytest.mark.parametrize("mutation", ("drop", "rewrite"))
def test_current_schema_rejects_checkpoint_trigger_drift(tmp_path, mutation):
    engine = _engine(tmp_path / f"checkpoint-trigger-drift-{mutation}.db")
    assert run_database_migrations(engine).revision_after == CURRENT_REVISION
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP TRIGGER ck_wallet_transaction_inclusion_checkpoint_insert"
        )
        if mutation == "rewrite":
            connection.exec_driver_sql(
                "CREATE TRIGGER ck_wallet_transaction_inclusion_checkpoint_insert "
                "BEFORE INSERT ON wallet_transaction_inclusion_proofs "
                "BEGIN SELECT 1; END"
            )
    with pytest.raises(MigrationBootstrapError, match="checkpoint triggers differ"):
        run_database_migrations(engine)
    engine.dispose()


def test_transaction_checkpoint_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "checkpoint-forward-only.db")
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_CHECKPOINT_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="intentionally unsupported"):
            command.downgrade(
                migration_config(connection),
                TRANSACTION_INCLUSION_TRUST_REVISION,
            )
    engine.dispose()


def test_strict_proof_policy_migration_preserves_v1_and_allows_v2_coexistence(
    tmp_path,
):
    path = tmp_path / "strict-proof-policy-preserve.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_CHECKPOINT_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        _insert_raw_current_checkpoint_proof(
            connection,
            policy=CHECKPOINT_POLICY,
            digest="ab" * 32,
        )

    engine = _engine(path)
    _upgrade_to_revision(engine, STRICT_TRANSACTION_INCLUSION_POLICY_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        assert connection.execute(
            "SELECT verifier_policy_id, trusted_checkpoint_root_hash FROM "
            "wallet_transaction_inclusion_proofs"
        ).fetchall() == [(CHECKPOINT_POLICY, MAINNET_CHECKPOINT[3])]
        _insert_raw_current_checkpoint_proof(
            connection,
            policy=STRICT_CHECKPOINT_POLICY,
            digest="cd" * 32,
        )
        with pytest.raises(sqlite3.IntegrityError):
            _insert_raw_current_checkpoint_proof(
                connection,
                policy=STRICT_CHECKPOINT_POLICY,
                digest="ef" * 32,
            )
        assert connection.execute(
            "SELECT verifier_policy_id FROM wallet_transaction_inclusion_proofs "
            "ORDER BY verifier_policy_id"
        ).fetchall() == [
            (CHECKPOINT_POLICY,),
            (STRICT_CHECKPOINT_POLICY,),
        ]


@pytest.mark.parametrize(
    ("policy", "network", "checkpoint"),
    (
        ("forged_policy", "ton-mainnet", MAINNET_CHECKPOINT),
        (
            STRICT_CHECKPOINT_POLICY,
            "ton-mainnet",
            (-1, "-9223372036854775808", 46894135, "ff" * 32, "aa" * 32),
        ),
        (STRICT_CHECKPOINT_POLICY, "ton-testnet", MAINNET_CHECKPOINT),
        (
            STRICT_CHECKPOINT_POLICY,
            "ton-mainnet",
            (None, None, None, None, None),
        ),
        (
            CHECKPOINT_POLICY,
            "ton-mainnet",
            (-1, "-9223372036854775808", 46894135, "ff" * 32, "aa" * 32),
        ),
    ),
)
def test_strict_proof_policy_triggers_reject_impossible_provenance(
    tmp_path,
    policy,
    network,
    checkpoint,
):
    path = tmp_path / f"strict-policy-trigger-{abs(hash(repr((policy, network, checkpoint))))}.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, STRICT_TRANSACTION_INCLUSION_POLICY_REVISION)
    engine.dispose()
    with sqlite3.connect(path) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            _insert_raw_current_checkpoint_proof(
                connection,
                policy=policy,
                network=network,
                checkpoint=checkpoint,
            )


@pytest.mark.parametrize(
    ("insert_trigger", "update_trigger"),
    (
        ("old", "old"),
        ("new", "old"),
        ("old", "new"),
        (None, "old"),
        ("new", None),
        (None, None),
    ),
)
def test_strict_proof_policy_migration_resumes_trigger_transition(
    tmp_path,
    insert_trigger,
    update_trigger,
):
    engine = _engine(
        tmp_path / f"strict-policy-resume-{insert_trigger}-{update_trigger}.db"
    )
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_CHECKPOINT_REVISION)
    old = importlib.import_module(
        "migrations.versions.20260710_0021_transaction_inclusion_pinned_checkpoints"
    )
    new = importlib.import_module(
        "migrations.versions.20260710_0022_strict_liteserver_proof_policy"
    )
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP TRIGGER ck_wallet_transaction_inclusion_checkpoint_insert"
        )
        connection.exec_driver_sql(
            "DROP TRIGGER ck_wallet_transaction_inclusion_checkpoint_update"
        )
        for name, event, state in (
            (new._INSERT_TRIGGER, "INSERT", insert_trigger),
            (new._UPDATE_TRIGGER, "UPDATE", update_trigger),
        ):
            if state is not None:
                source = old if state == "old" else new
                connection.exec_driver_sql(source._trigger_sql(name, event))

    _upgrade_to_revision(engine, STRICT_TRANSACTION_INCLUSION_POLICY_REVISION)
    with engine.connect() as connection:
        rows = connection.exec_driver_sql(
            "SELECT name, sql FROM sqlite_master WHERE type='trigger' AND "
            "tbl_name='wallet_transaction_inclusion_proofs'"
        ).fetchall()
    assert {
        name: new._normalize_sql(sql) for name, sql in rows
    } == {
        new._INSERT_TRIGGER: new._normalize_sql(
            new._trigger_sql(new._INSERT_TRIGGER, "INSERT")
        ),
        new._UPDATE_TRIGGER: new._normalize_sql(
            new._trigger_sql(new._UPDATE_TRIGGER, "UPDATE")
        ),
    }
    engine.dispose()


def test_strict_proof_policy_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "strict-proof-policy-forward-only.db")
    _upgrade_to_revision(engine, STRICT_TRANSACTION_INCLUSION_POLICY_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="intentionally unsupported"):
            command.downgrade(
                migration_config(connection),
                TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
            )
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == STRICT_TRANSACTION_INCLUSION_POLICY_REVISION
    engine.dispose()


def test_case_report_revision_migration_creates_exact_current_schema(tmp_path):
    engine = _engine(tmp_path / "case-report-revisions.db")
    _upgrade_to_revision(engine, STRICT_TRANSACTION_INCLUSION_POLICY_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == STRICT_TRANSACTION_INCLUSION_POLICY_REVISION
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    inspector = inspect(engine)
    assert [column["name"] for column in inspector.get_columns(
        "wallet_case_report_revisions"
    )] == [
        "id",
        "public_id",
        "case_id",
        "snapshot_sync_id",
        "contract_version",
        "content_hash_sha256",
        "assurance_level",
        "activity_digest_sha256",
        "evidence_digest_sha256",
        "report_json",
        "created_at",
    ]
    assert {
        item["name"]: (tuple(item["column_names"]), bool(item["unique"]))
        for item in inspector.get_indexes("wallet_case_report_revisions")
    } == {
        "uq_wallet_case_report_revisions_public_id": (("public_id",), True),
        "uq_wallet_case_report_revisions_case_hash": (
            ("case_id", "content_hash_sha256"),
            True,
        ),
        "ix_wallet_case_report_revisions_catalog": (
            ("case_id", "id"),
            False,
        ),
        "ix_wallet_case_report_revisions_snapshot": (
            ("case_id", "snapshot_sync_id", "id"),
            False,
        ),
    }
    _assert_schema_matches_models(engine)
    engine.dispose()


def test_case_report_revision_migration_resumes_exact_empty_table(tmp_path):
    engine = _engine(tmp_path / "case-report-revision-resume.db")
    _upgrade_to_revision(engine, STRICT_TRANSACTION_INCLUSION_POLICY_REVISION)
    models.WalletCaseReportRevision.__table__.create(bind=engine)

    report = run_database_migrations(engine)

    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    _assert_schema_matches_models(engine)
    engine.dispose()


def test_case_report_revision_migration_never_adopts_pre_revision_rows(tmp_path):
    path = tmp_path / "case-report-revision-row-adoption.db"
    engine = _engine(path)
    _upgrade_to_revision(engine, STRICT_TRANSACTION_INCLUSION_POLICY_REVISION)
    models.WalletCaseReportRevision.__table__.create(bind=engine)
    engine.dispose()
    digest = "ab" * 32
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO wallet_case_report_revisions "
            "(public_id, case_id, snapshot_sync_id, contract_version, "
            "content_hash_sha256, assurance_level, activity_digest_sha256, "
            "evidence_digest_sha256, report_json, created_at) "
            "VALUES (?, 999, 999, 'wallet_case_report_v1', ?, 'observed', ?, ?, "
            "'{\"x\":1}', '2026-08-19 00:00:00')",
            (f"rpt_{digest}", digest, "cd" * 32, "ef" * 32),
        )

    engine = _engine(path)
    with pytest.raises(RuntimeError, match="cannot be adopted"):
        run_database_migrations(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == STRICT_TRANSACTION_INCLUSION_POLICY_REVISION
    engine.dispose()


def test_case_report_revision_migration_rejects_wrong_index_signature(tmp_path):
    engine = _engine(tmp_path / "case-report-revision-wrong-index.db")
    _upgrade_to_revision(engine, STRICT_TRANSACTION_INCLUSION_POLICY_REVISION)
    models.WalletCaseReportRevision.__table__.create(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP INDEX uq_wallet_case_report_revisions_public_id"
        )
        connection.exec_driver_sql(
            "CREATE INDEX uq_wallet_case_report_revisions_public_id "
            "ON wallet_case_report_revisions(public_id)"
        )

    with pytest.raises(RuntimeError, match="differs from revision 0023"):
        run_database_migrations(engine)
    engine.dispose()


def test_case_report_revision_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "case-report-revision-forward-only.db")
    _upgrade_to_revision(engine, CASE_REPORT_REVISIONS_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="intentionally unsupported"):
            command.downgrade(
                migration_config(connection),
                STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
            )
    engine.dispose()


def test_wallet_case_lifecycle_migration_creates_retained_audit_table(tmp_path):
    engine = _engine(tmp_path / "wallet-case-lifecycle.db")
    _upgrade_to_revision(engine, CASE_REPORT_REVISIONS_REVISION)

    report = run_database_migrations(engine)

    assert report.revision_before == CASE_REPORT_REVISIONS_REVISION
    assert report.revision_after == WALLET_CASE_LIFECYCLE_REVISION
    assert report.applied_revisions == (WALLET_CASE_LIFECYCLE_REVISION,)
    inspector = inspect(engine)
    assert [
        column["name"]
        for column in inspector.get_columns("wallet_case_lifecycle_events")
    ] == [
        "id",
        "public_id",
        "owner_scope_id",
        "case_public_id",
        "event_type",
        "occurred_at",
        "details_json",
    ]
    assert inspector.get_foreign_keys("wallet_case_lifecycle_events") == []
    assert {
        item["name"]: (tuple(item["column_names"]), bool(item["unique"]))
        for item in inspector.get_indexes("wallet_case_lifecycle_events")
    } == {
        "uq_wallet_case_lifecycle_events_public_id": (("public_id",), True),
        "uq_wallet_case_lifecycle_events_case_id": (("case_public_id",), True),
        "ix_wallet_case_lifecycle_events_scope_time": (
            ("owner_scope_id", "occurred_at", "id"),
            False,
        ),
    }
    _assert_schema_matches_models(engine)
    engine.dispose()


def test_wallet_case_lifecycle_migration_resumes_exact_empty_table(tmp_path):
    engine = _engine(tmp_path / "wallet-case-lifecycle-resume.db")
    _upgrade_to_revision(engine, CASE_REPORT_REVISIONS_REVISION)
    models.WalletCaseLifecycleEvent.__table__.create(bind=engine)

    report = run_database_migrations(engine)

    assert report.revision_after == WALLET_CASE_LIFECYCLE_REVISION
    assert report.applied_revisions == (WALLET_CASE_LIFECYCLE_REVISION,)
    _assert_schema_matches_models(engine)
    engine.dispose()


def test_wallet_case_lifecycle_migration_never_adopts_existing_rows(tmp_path):
    engine = _engine(tmp_path / "wallet-case-lifecycle-row-adoption.db")
    _upgrade_to_revision(engine, CASE_REPORT_REVISIONS_REVISION)
    models.WalletCaseLifecycleEvent.__table__.create(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO wallet_case_lifecycle_events "
            "(public_id, owner_scope_id, case_public_id, event_type, "
            "occurred_at, details_json) VALUES (?, ?, ?, 'deleted', ?, ?)",
            (
                str(uuid4()),
                "local-single-user",
                str(uuid4()),
                "2026-08-26 12:00:00",
                '{"removed":{}}',
            ),
        )

    with pytest.raises(RuntimeError, match="cannot be adopted"):
        run_database_migrations(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == CASE_REPORT_REVISIONS_REVISION
    engine.dispose()


def test_wallet_case_lifecycle_migration_rejects_wrong_index_signature(tmp_path):
    engine = _engine(tmp_path / "wallet-case-lifecycle-wrong-index.db")
    _upgrade_to_revision(engine, CASE_REPORT_REVISIONS_REVISION)
    models.WalletCaseLifecycleEvent.__table__.create(bind=engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DROP INDEX uq_wallet_case_lifecycle_events_public_id"
        )
        connection.exec_driver_sql(
            "CREATE INDEX uq_wallet_case_lifecycle_events_public_id "
            "ON wallet_case_lifecycle_events(public_id)"
        )

    with pytest.raises(RuntimeError, match="differs from revision 0024"):
        run_database_migrations(engine)
    engine.dispose()


def test_wallet_case_lifecycle_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "wallet-case-lifecycle-forward-only.db")
    _upgrade_to_revision(engine, WALLET_CASE_LIFECYCLE_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="intentionally unsupported"):
            command.downgrade(
                migration_config(connection),
                CASE_REPORT_REVISIONS_REVISION,
            )
    engine.dispose()


def test_wallet_case_constraints_enforce_scope_bounds_progress_and_cascade(
    tmp_path,
):
    engine = _engine(tmp_path / "wallet-case-constraints.db")
    run_database_migrations(engine)
    wallet_cases = database.Base.metadata.tables[WALLET_CASES_TABLE]
    case_syncs = database.Base.metadata.tables[WALLET_CASE_SYNCS_TABLE]
    with engine.begin() as connection:
        case_id = connection.execute(
            wallet_cases.insert().values(**_wallet_case_values())
        ).inserted_primary_key[0]

    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                wallet_cases.insert().values(**_wallet_case_values())
            )

    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                wallet_cases.insert().values(
                    **_wallet_case_values(
                        canonical_wallet_key=f"0:{'11' * 32}",
                        network="ton-unknown",
                    )
                )
            )

    requested_at = datetime(2026, 8, 8, tzinfo=timezone.utc)
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                case_syncs.insert().values(
                    **_wallet_case_sync_values(
                        case_id,
                        requested_start=requested_at,
                        requested_end=requested_at,
                    )
                )
            )

    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                case_syncs.insert().values(
                    **_wallet_case_sync_values(
                        case_id,
                        progress_current=2,
                        progress_total=1,
                    )
                )
            )

    with engine.begin() as connection:
        connection.execute(
            case_syncs.insert().values(**_wallet_case_sync_values(case_id))
        )
    assert _wallet_case_counts(engine) == (1, 1)

    with engine.begin() as connection:
        connection.execute(wallet_cases.delete().where(wallet_cases.c.id == case_id))
    assert _wallet_case_counts(engine) == (0, 0)
    engine.dispose()


def test_dex_protocol_identity_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "dex-protocol-identity-forward-only.db")
    _upgrade_to_revision(engine, DEX_PROTOCOL_IDENTITY_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                TRANSACTION_INCLUSION_REVISION,
            )
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("wallet_swaps")
    }
    assert {"dex_protocol_id", "dex_protocol_status"}.issubset(columns)
    engine.dispose()


def test_transaction_inclusion_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "transaction-inclusion-forward-only.db")
    _upgrade_to_revision(engine, TRANSACTION_INCLUSION_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                ACCOUNT_STATE_INCLUSION_REVISION,
            )
    assert "wallet_transaction_inclusion_proofs" in inspect(engine).get_table_names()
    engine.dispose()


def test_account_state_inclusion_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "account-state-inclusion-forward-only.db")
    _upgrade_to_revision(engine, ACCOUNT_STATE_INCLUSION_REVISION)
    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                WALLET_OWNERSHIP_CHALLENGE_REVISION,
            )
    assert "wallet_account_state_inclusion_proofs" in inspect(engine).get_table_names()
    engine.dispose()


def test_jetton_contract_verification_rejects_partial_fragments(tmp_path):
    engine = _engine(tmp_path / "partial-jetton-contract-verification.db")
    _upgrade_to_revision(engine, NATIVE_ACTIVITY_LEDGER_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            JETTON_CONTRACT_VERIFICATIONS_TABLE,
        )

    with pytest.raises(RuntimeError, match="refuses a pre-existing"):
        _upgrade_to_revision(engine, JETTON_CONTRACT_VERIFICATION_REVISION)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == NATIVE_ACTIVITY_LEDGER_REVISION
    engine.dispose()


def test_jetton_contract_verification_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "jetton-contract-verification-forward-only.db")
    _upgrade_to_revision(engine, JETTON_CONTRACT_VERIFICATION_REVISION)

    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                NATIVE_ACTIVITY_LEDGER_REVISION,
            )

    assert JETTON_CONTRACT_VERIFICATIONS_TABLE in inspect(engine).get_table_names()
    engine.dispose()


def test_native_activity_ledger_rejects_partial_fragments(tmp_path):
    engine = _engine(tmp_path / "partial-native-activity-ledger.db")
    _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            "wallet_native_activity_ledgers",
        )

    with pytest.raises(RuntimeError, match="refuses pre-existing"):
        _upgrade_to_revision(engine, NATIVE_ACTIVITY_LEDGER_REVISION)
    assert "wallet_native_activity_rows" not in inspect(engine).get_table_names()
    engine.dispose()


def test_native_activity_ledger_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "native-activity-ledger-forward-only.db")
    _upgrade_to_revision(engine, NATIVE_ACTIVITY_LEDGER_REVISION)

    with engine.begin() as connection:
        with pytest.raises(RuntimeError, match="downgrade would discard"):
            command.downgrade(
                migration_config(connection),
                TRACE_BOC_VERIFICATION_REVISION,
            )

    assert {
        "wallet_native_activity_ledgers",
        "wallet_native_activity_rows",
    }.issubset(inspect(engine).get_table_names())
    engine.dispose()


def test_trace_boc_verification_repairs_exact_empty_partial_sqlite_ddl(
    tmp_path,
):
    engine = _engine(tmp_path / "partial-trace-boc-verification.db")
    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            TRACE_BOC_VERIFICATIONS_TABLE,
        )
        _create_model_table_without_indexes(
            connection,
            TRACE_BOC_TRANSACTIONS_TABLE,
        )

    _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)

    _assert_trace_boc_verification_schema(engine)
    assert _trace_boc_verification_counts(engine) == (0, 0)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRACE_BOC_VERIFICATION_REVISION
    engine.dispose()


def test_trace_boc_verification_orphan_transaction_table_fails_closed(
    tmp_path,
):
    engine = _engine(tmp_path / "orphan-trace-boc-transaction.db")
    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            TRACE_BOC_TRANSACTIONS_TABLE,
        )

    with pytest.raises(RuntimeError, match="without their verification table"):
        _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)

    assert TRACE_BOC_VERIFICATIONS_TABLE not in inspect(engine).get_table_names()
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRACE_EVIDENCE_REVISION
    engine.dispose()


def test_trace_boc_verification_requires_complete_0006_schema(tmp_path):
    engine = _engine(tmp_path / "incomplete-0006-for-boc-verification.db")
    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"DROP TABLE {TRACE_MESSAGES_TABLE}")

    with pytest.raises(RuntimeError, match="requires the exact revision 0006"):
        _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)

    tables = set(inspect(engine).get_table_names())
    assert TRACE_BOC_VERIFICATIONS_TABLE not in tables
    assert TRACE_BOC_TRANSACTIONS_TABLE not in tables
    engine.dispose()


def test_trace_boc_verification_malformed_partial_columns_fail_before_child_ddl(
    tmp_path,
):
    engine = _engine(tmp_path / "malformed-trace-boc-columns.db")
    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            TRACE_BOC_VERIFICATIONS_TABLE,
        )
    _rewrite_table_sql(
        engine,
        TRACE_BOC_VERIFICATIONS_TABLE,
        "contract_version VARCHAR(48)",
        "contract_version VARCHAR(64)",
    )

    with pytest.raises(RuntimeError, match="columns do not match revision 0007"):
        _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)

    assert TRACE_BOC_TRANSACTIONS_TABLE not in inspect(engine).get_table_names()
    engine.dispose()


def test_trace_boc_verification_wrong_partial_index_fails_closed(tmp_path):
    engine = _engine(tmp_path / "wrong-trace-boc-index.db")
    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _create_model_table_without_indexes(
            connection,
            TRACE_BOC_VERIFICATIONS_TABLE,
        )
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX "
            "uq_wallet_trace_boc_verifications_capture_contract "
            "ON wallet_trace_boc_verifications "
            "(contract_version, capture_id)"
        )

    with pytest.raises(RuntimeError, match="index does not match revision 0007"):
        _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)

    assert TRACE_BOC_TRANSACTIONS_TABLE not in inspect(engine).get_table_names()
    engine.dispose()


def test_trace_boc_verification_pre_revision_rows_are_never_adopted(tmp_path):
    engine = _engine(tmp_path / "unexpected-trace-boc-data.db")
    _upgrade_to_revision(engine, TRACE_EVIDENCE_REVISION)
    with engine.begin() as connection:
        _insert_scoped_run(connection, run_id=1)
        _insert_transaction(connection, transaction_id=1, run_id=1)
        connection.exec_driver_sql(
            "INSERT INTO wallet_trace_evidence_captures ("
            "id, run_id, captured_via_transaction_id, capture_slot, provider, "
            "contract_version, network, root_transaction_hash, trace_state, "
            "transaction_count, max_depth, message_count, "
            "root_inbound_message_count, child_internal_message_count, "
            "remaining_out_message_count, internal_message_count, "
            "external_in_message_count, external_out_message_count, "
            "successful_transaction_count, failed_transaction_count, "
            "aborted_transaction_count, unique_account_count, "
            "evidence_digest_sha256, captured_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, "
            "?, ?, ?, ?, ?, ?, ?)",
            (
                1, 1, 1, 0, "tonapi", "tonapi_low_level_trace_evidence_v1",
                "ton-mainnet", TRANSACTION_HASH, "finalized", 1, 0, 0, 0,
                0, 0, 0, 0, 0, 1, 0, 0, 1, "ab" * 32,
                "2026-07-10 12:00:00.000000",
            ),
        )
        _create_model_table_without_indexes(
            connection,
            TRACE_BOC_VERIFICATIONS_TABLE,
        )
        connection.exec_driver_sql(
            "INSERT INTO wallet_trace_boc_verifications ("
            "id, capture_id, contract_version, verifier_name, "
            "verifier_version, network, transaction_count, message_count, "
            "total_boc_bytes, normalized_external_in_hash_count, "
            "direct_cell_hash_message_count, body_hash_count, opcode_count, "
            "evidence_digest_sha256, verified_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                1, 1, "ton_boc_trace_verification_v1", "pytoniq-core",
                "0.1.46", "ton-mainnet", 1, 0, 1, 0, 0, 0, 0,
                "cd" * 32, "2026-07-10 13:00:00.000000",
            ),
        )

    with pytest.raises(RuntimeError, match="unexpected pre-revision data"):
        _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)

    assert TRACE_BOC_TRANSACTIONS_TABLE not in inspect(engine).get_table_names()
    engine.dispose()


def test_trace_boc_verification_migration_is_forward_only(tmp_path):
    engine = _engine(tmp_path / "trace-boc-verification-forward-only.db")
    _upgrade_to_revision(engine, TRACE_BOC_VERIFICATION_REVISION)

    with engine.begin() as connection:
        with pytest.raises(
            RuntimeError,
            match="Trace BOC verification downgrade would discard",
        ):
            command.downgrade(
                migration_config(connection),
                TRACE_EVIDENCE_REVISION,
            )

    _assert_trace_boc_verification_schema(engine)
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT version_num FROM alembic_version"
        ).scalar_one() == TRACE_BOC_VERIFICATION_REVISION
    engine.dispose()


def test_incompatible_unversioned_database_fails_closed_without_mutation(tmp_path):
    path = tmp_path / "incompatible.db"
    _load_legacy_fixture(path)
    with sqlite3.connect(path) as connection:
        connection.execute("DROP INDEX ix_wallet_transactions_tx_hash")
    engine = _engine(path)
    schema_before = _schema_snapshot(engine)
    data_before = _data_snapshot(engine)

    with pytest.raises(MigrationBootstrapError):
        run_database_migrations(engine)

    assert _schema_snapshot(engine) == schema_before
    assert _data_snapshot(engine) == data_before
    engine.dispose()


def test_unknown_revision_is_rejected_without_touching_domain_data(tmp_path):
    engine = _engine(tmp_path / "unknown-revision.db")
    initial = run_database_migrations(engine)
    assert initial.revision_after
    marker_table, revision_column = _revision_cell(engine, initial.revision_after)
    unknown_revision = "future_revision_not_known_to_this_build"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"UPDATE {_quote(marker_table)} "
            f"SET {_quote(revision_column)} = ?",
            (unknown_revision,),
        )
    domain_data_before = _data_snapshot(engine)
    schema_before = _schema_snapshot(engine)

    with pytest.raises(MigrationBootstrapError):
        run_database_migrations(engine)

    assert _data_snapshot(engine) == domain_data_before
    assert _schema_snapshot(engine) == schema_before
    with engine.connect() as connection:
        stored_revision = connection.exec_driver_sql(
            f"SELECT {_quote(revision_column)} FROM {_quote(marker_table)}"
        ).scalar_one()
    assert stored_revision == unknown_revision
    engine.dispose()


def test_clean_process_current_head_missing_schema_fails_closed(tmp_path):
    path = tmp_path / "current-head-without-domain-schema.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
        )
        connection.execute(
            "INSERT INTO alembic_version (version_num) VALUES (?)",
            (CURRENT_REVISION,),
        )

    environment = os.environ.copy()
    environment["TON_CHECK_DB_URL"] = f"sqlite:///{path}"
    completed = subprocess.run(
        [sys.executable, "-m", "services.database_migrations"],
        cwd=Path(__file__).resolve().parents[1],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode != 0
    output = completed.stdout + completed.stderr
    assert "Missing current domain tables" in output


@pytest.mark.parametrize(
    ("table_name", "old", "new"),
    [
        (
            "wallet_ingestion_runs",
            "wallet_identity_status VARCHAR(20)",
            "wallet_identity_status VARCHAR(200)",
        ),
        (
            "wallet_transfers",
            "amount NUMERIC(38, 18)",
            "amount NUMERIC(18, 4)",
        ),
        (
            "wallet_ingestion_runs",
            "wallet_identity_status VARCHAR(20) DEFAULT 'unavailable'",
            "wallet_identity_status VARCHAR(20) DEFAULT 'corrupt'",
        ),
    ],
)
def test_current_schema_rejects_column_type_and_default_drift(
    tmp_path,
    table_name,
    old,
    new,
):
    engine = _engine(tmp_path / f"column-drift-{table_name}.db")
    run_database_migrations(engine)
    _rewrite_table_sql(engine, table_name, old, new)

    with pytest.raises(MigrationBootstrapError, match="current columns differ"):
        run_database_migrations(engine)

    engine.dispose()


def test_current_schema_rejects_unique_and_check_constraint_drift(tmp_path):
    engine = _engine(tmp_path / "constraint-drift.db")
    run_database_migrations(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE analysis_runs")
        connection.exec_driver_sql(
            "CREATE TABLE analysis_runs ("
            "id INTEGER NOT NULL, "
            "pool_url VARCHAR NOT NULL, "
            "time_window VARCHAR NOT NULL, "
            "created_at DATETIME NOT NULL, "
            "result_json TEXT NOT NULL, "
            "PRIMARY KEY (id), "
            "UNIQUE (pool_url), "
            "CHECK (length(pool_url) > 0)"
            ")"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_analysis_runs_id ON analysis_runs (id)"
        )

    with pytest.raises(MigrationBootstrapError) as exc_info:
        run_database_migrations(engine)

    message = str(exc_info.value)
    assert "current unique constraints differ" in message
    assert "current check constraints differ" in message
    engine.dispose()


def test_current_schema_rejects_wallet_case_check_drift(tmp_path):
    engine = _engine(tmp_path / "wallet-case-check-drift.db")
    run_database_migrations(engine)
    _rewrite_table_sql(
        engine,
        WALLET_CASES_TABLE,
        "network IN ('ton-mainnet', 'ton-testnet')",
        "network IN ('ton-mainnet', 'ton-testnet', 'ton-unknown')",
    )

    with pytest.raises(
        MigrationBootstrapError,
        match="current check constraints differ",
    ):
        run_database_migrations(engine)

    engine.dispose()


def test_current_schema_rejects_wallet_case_sync_foreign_key_drift(tmp_path):
    engine = _engine(tmp_path / "wallet-case-sync-fk-drift.db")
    run_database_migrations(engine)
    _rewrite_table_sql(
        engine,
        WALLET_CASE_SYNCS_TABLE,
        "FOREIGN KEY(ingestion_run_id) REFERENCES wallet_ingestion_runs (id) ON DELETE RESTRICT",
        "FOREIGN KEY(ingestion_run_id) REFERENCES wallet_ingestion_runs (id) ON DELETE CASCADE",
    )

    with pytest.raises(
        MigrationBootstrapError,
        match="current foreign keys differ",
    ):
        run_database_migrations(engine)

    engine.dispose()


def test_current_schema_rejects_foreign_key_option_drift(tmp_path):
    engine = _engine(tmp_path / "foreign-key-option-drift.db")
    run_database_migrations(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE wallet_ingestion_warnings")
        connection.exec_driver_sql(
            "CREATE TABLE wallet_ingestion_warnings ("
            "id INTEGER NOT NULL, "
            "run_id INTEGER NOT NULL, "
            "severity VARCHAR NOT NULL, "
            "provider VARCHAR, "
            "message TEXT NOT NULL, "
            "evidence_key VARCHAR, "
            "created_at DATETIME NOT NULL, "
            "PRIMARY KEY (id), "
            "FOREIGN KEY(run_id) REFERENCES wallet_ingestion_runs (id) "
            "ON DELETE CASCADE"
            ")"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_wallet_ingestion_warnings_id "
            "ON wallet_ingestion_warnings (id)"
        )
        connection.exec_driver_sql(
            "CREATE INDEX ix_wallet_ingestion_warnings_run_id "
            "ON wallet_ingestion_warnings (run_id)"
        )

    with pytest.raises(
        MigrationBootstrapError,
        match="current foreign keys differ",
    ):
        run_database_migrations(engine)

    engine.dispose()


def test_database_init_db_delegates_without_using_create_all(tmp_path, monkeypatch):
    target_engine = _engine(tmp_path / "init-db.db")

    def forbidden_create_all(*args, **kwargs):
        raise AssertionError("init_db must delegate to the migration runner")

    monkeypatch.setattr(database, "engine", target_engine)
    monkeypatch.setattr(database.Base.metadata, "create_all", forbidden_create_all)

    report = database.init_db()

    assert isinstance(report, MigrationReport)
    assert report.action == "created"
    assert report.revision_after == CURRENT_REVISION
    assert report.applied_revisions == (
        BASELINE_REVISION,
        WALLET_IDENTITY_REVISION,
        TRANSACTION_IDENTITY_REVISION,
        ACQUISITION_EVIDENCE_REVISION,
        EVENT_ACTION_IDENTITY_REVISION,
        TRACE_EVIDENCE_REVISION,
        TRACE_BOC_VERIFICATION_REVISION,
        NATIVE_ACTIVITY_LEDGER_REVISION,
        JETTON_CONTRACT_VERIFICATION_REVISION,
        WALLET_OWNERSHIP_CHALLENGE_REVISION,
        ACCOUNT_STATE_INCLUSION_REVISION,
        TRANSACTION_INCLUSION_REVISION,
        DEX_PROTOCOL_IDENTITY_REVISION,
        OWNERSHIP_NETWORK_SCOPE_REVISION,
        WALLET_CASES_REVISION,
        WALLET_CASE_COMPACT_RESULTS_REVISION,
        CASE_SYNC_JOBS_REVISION,
        CASE_ACTIVITY_INDEXES_REVISION,
        CASE_EVIDENCE_VERIFICATIONS_REVISION,
        TRANSACTION_INCLUSION_TRUST_REVISION,
        TRANSACTION_INCLUSION_CHECKPOINT_REVISION,
        STRICT_TRANSACTION_INCLUSION_POLICY_REVISION,
        CASE_REPORT_REVISIONS_REVISION,
        WALLET_CASE_LIFECYCLE_REVISION,
    )
    _assert_schema_matches_models(target_engine)
    target_engine.dispose()


def test_app_startup_migrates_before_serving_requests(tmp_path, monkeypatch):
    target_engine = _engine(tmp_path / "startup.db")
    monkeypatch.setattr(database, "engine", target_engine)

    with TestClient(app) as client:
        _assert_schema_matches_models(target_engine)
        response = client.get("/api/health")

    assert response.status_code == 200
    assert run_database_migrations(target_engine).action == "already_current"
    target_engine.dispose()
