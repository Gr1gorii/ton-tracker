"""Migration-runner tests for fresh and legacy SQLite databases."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import Engine

import database
import models  # noqa: F401 - register every table on database.Base.metadata
from main import app
from migrations.legacy_baseline import BASELINE_REVISION
from services.database_migrations import (
    MigrationBootstrapError,
    MigrationReport,
    run_database_migrations,
)


LEGACY_FIXTURE = Path(__file__).parent / "fixtures" / "legacy_v0_22_0.sql"
DOMAIN_TABLES = tuple(sorted(database.Base.metadata.tables))


def _engine(path: Path) -> Engine:
    return create_engine(
        f"sqlite:///{path}",
        connect_args={"check_same_thread": False},
    )


def _load_legacy_fixture(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.executescript(LEGACY_FIXTURE.read_text(encoding="utf-8"))


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _data_snapshot(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    snapshot: dict[str, list[tuple[Any, ...]]] = {}
    with engine.connect() as connection:
        for table_name in DOMAIN_TABLES:
            rows = connection.exec_driver_sql(
                f"SELECT * FROM {_quote(table_name)} ORDER BY id"
            ).fetchall()
            snapshot[table_name] = [tuple(row) for row in rows]
    return snapshot


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
    assert report.revision_after == BASELINE_REVISION
    assert report.applied_revisions == (BASELINE_REVISION,)
    _assert_schema_matches_models(engine)

    engine.dispose()
    reopened = _engine(tmp_path / "fresh.db")
    _assert_schema_matches_models(reopened)
    reopened.dispose()


def test_exact_unversioned_legacy_database_preserves_all_data(tmp_path):
    path = tmp_path / "legacy.db"
    _load_legacy_fixture(path)
    engine = _engine(path)
    before = _data_snapshot(engine)

    report = run_database_migrations(engine)

    assert isinstance(report, MigrationReport)
    assert report.action == "adopted_legacy"
    assert report.revision_before is None
    assert report.revision_after == BASELINE_REVISION
    assert report.applied_revisions == ()
    assert _data_snapshot(engine) == before
    _assert_schema_matches_models(engine)
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
    _assert_schema_matches_models(engine, allowed_extra_tables={"user_notes"})
    with engine.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT id, note FROM user_notes"
        ).one() == (1, "keep this unrelated table")
    engine.dispose()


def test_runner_is_idempotent_at_head(tmp_path):
    path = tmp_path / "idempotent.db"
    _load_legacy_fixture(path)
    engine = _engine(path)
    first = run_database_migrations(engine)
    schema_after_first = _schema_snapshot(engine)
    data_after_first = _data_snapshot(engine)

    second = run_database_migrations(engine)

    assert isinstance(second, MigrationReport)
    assert second.action == "already_current"
    assert second.revision_before == first.revision_after
    assert second.revision_after == first.revision_after
    assert not second.applied_revisions
    assert _schema_snapshot(engine) == schema_after_first
    assert _data_snapshot(engine) == data_after_first
    engine.dispose()


def test_incompatible_unversioned_database_fails_closed_without_mutation(tmp_path):
    path = tmp_path / "incompatible.db"
    _load_legacy_fixture(path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "ALTER TABLE wallet_transactions RENAME COLUMN fee_ton TO legacy_fee"
        )
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


def test_database_init_db_delegates_without_using_create_all(tmp_path, monkeypatch):
    target_engine = _engine(tmp_path / "init-db.db")

    def forbidden_create_all(*args, **kwargs):
        raise AssertionError("init_db must delegate to the migration runner")

    monkeypatch.setattr(database, "engine", target_engine)
    monkeypatch.setattr(database.Base.metadata, "create_all", forbidden_create_all)

    report = database.init_db()

    assert isinstance(report, MigrationReport)
    assert report.action == "created"
    assert report.revision_after == BASELINE_REVISION
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
