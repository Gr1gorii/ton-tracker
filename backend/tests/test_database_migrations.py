"""Migration-runner tests for fresh and legacy SQLite databases."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from fastapi.testclient import TestClient
from sqlalchemy import inspect
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
CURRENT_REVISION = TRACE_BOC_VERIFICATION_REVISION

ACQUISITION_STREAMS_TABLE = "wallet_acquisition_streams"
ACQUISITION_PAGES_TABLE = "wallet_acquisition_pages"
TRACE_CAPTURES_TABLE = "wallet_trace_evidence_captures"
TRACE_NODES_TABLE = "wallet_trace_evidence_nodes"
TRACE_MESSAGES_TABLE = "wallet_trace_evidence_messages"
TRACE_BOC_VERIFICATIONS_TABLE = "wallet_trace_boc_verifications"
TRACE_BOC_TRANSACTIONS_TABLE = "wallet_trace_boc_transactions"

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


def _upgrade_to_revision(engine: Engine, revision: str) -> None:
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), revision)


def _create_model_table_without_indexes(connection, table_name: str) -> None:
    table = database.Base.metadata.tables[table_name]
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
    )
    _assert_schema_matches_models(engine)
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
    )
    assert _data_snapshot(engine) == before
    _assert_schema_matches_models(engine)
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
    assert report.revision_after == TRACE_BOC_VERIFICATION_REVISION
    assert report.applied_revisions == (TRACE_BOC_VERIFICATION_REVISION,)
    assert _trace_boc_verification_counts(engine) == (0, 0)
    _assert_schema_matches_models(engine)
    _assert_trace_boc_verification_schema(engine)
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

    _assert_schema_matches_models(engine)
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
