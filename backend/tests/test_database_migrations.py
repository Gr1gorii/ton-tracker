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
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

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
CURRENT_REVISION = TRANSACTION_IDENTITY_REVISION

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

TRANSACTION_HASH = "cd" * 32
SECOND_TRANSACTION_HASH = "ef" * 32
TRANSACTION_LT = "89089355000001"
TRANSACTION_IDENTITY_VERSION = "ton_account_tx_v1"


def _engine(path: Path) -> Engine:
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def _upgrade_to_revision(engine: Engine, revision: str) -> None:
    with engine.begin() as connection:
        command.upgrade(migration_config(connection), revision)


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
        for table_name in DOMAIN_TABLES:
            columns = ", ".join(
                _quote(column) for column in PRE_0002_COLUMNS[table_name]
            )
            rows = connection.exec_driver_sql(
                f"SELECT {columns} FROM {_quote(table_name)} ORDER BY id"
            ).fetchall()
            snapshot[table_name] = [tuple(row) for row in rows]
    return snapshot


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
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    signatures: set[tuple[tuple[str, ...], str, tuple[str, ...]]] = set()
    for constraint in table.foreign_key_constraints:
        elements = list(constraint.elements)
        signatures.add(
            (
                tuple(element.parent.name for element in elements),
                elements[0].column.table.name,
                tuple(element.column.name for element in elements),
            )
        )
    return signatures


def _reflected_foreign_key_signature(
    inspector,
    table_name: str,
) -> set[tuple[tuple[str, ...], str, tuple[str, ...]]]:
    return {
        (
            tuple(foreign_key["constrained_columns"]),
            foreign_key["referred_table"],
            tuple(foreign_key["referred_columns"]),
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
    )
    _assert_schema_matches_models(engine)
    _assert_wallet_identity_schema(engine)
    _assert_transaction_identity_schema(engine)

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
    )
    assert _data_snapshot(engine) == before
    _assert_schema_matches_models(engine)
    _assert_wallet_identity_schema(engine)
    _assert_transaction_identity_schema(engine)
    _assert_legacy_identity_backfill(engine)
    _assert_legacy_transaction_identity_backfill(engine)
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
    _assert_legacy_identity_backfill(engine)
    _assert_legacy_transaction_identity_backfill(engine)
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
    assert report.revision_after == TRANSACTION_IDENTITY_REVISION
    assert report.applied_revisions == (TRANSACTION_IDENTITY_REVISION,)
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
    assert report.revision_after == TRANSACTION_IDENTITY_REVISION
    assert report.applied_revisions == (TRANSACTION_IDENTITY_REVISION,)
    assert _transaction_legacy_snapshot(engine) == source_before
    assert _transaction_identity_snapshot(engine)[1][3] == "network_scoped"
    _assert_schema_matches_models(engine)
    _assert_transaction_identity_schema(engine)
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
