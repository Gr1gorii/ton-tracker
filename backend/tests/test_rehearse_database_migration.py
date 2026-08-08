"""Target-image database migration rehearsal tests."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sqlite3
import sys

import pytest
from alembic import command

from database import create_database_engine
from ops.backup_sqlite import BACKUP_HEALTH_RECORD, create_backup, sha256_file
from ops.rehearse_database_migration import main, rehearse_database_migration
from services.database_migrations import (
    MigrationBootstrapError,
    _config as migration_config,
    run_database_migrations,
)


def _current_database(path: Path) -> str:
    engine = create_database_engine(f"sqlite:///{path}")
    try:
        report = run_database_migrations(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE rehearsal_sentinel (value TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO rehearsal_sentinel VALUES ('preserved')"
            )
        return report.revision_after
    finally:
        engine.dispose()


def _database_at_revision(path: Path, revision: str) -> None:
    engine = create_database_engine(f"sqlite:///{path}")
    try:
        with engine.begin() as connection:
            command.upgrade(migration_config(connection), revision)
    finally:
        engine.dispose()


def test_rehearsal_migrates_verified_copy_and_discards_workspace(tmp_path):
    source = tmp_path / "source.sqlite3"
    backups = tmp_path / "backups"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    revision = _current_database(source)
    backup = create_backup(source, backups, retention=2)
    digest_before = sha256_file(backup)

    result = rehearse_database_migration(
        backups / BACKUP_HEALTH_RECORD,
        workspace=workspace,
    )

    assert result.source_revision == revision
    assert result.target_revision == revision
    assert result.action == "already_current"
    assert result.applied_revisions == ()
    assert sha256_file(backup) == digest_before
    assert list(workspace.iterdir()) == []
    with sqlite3.connect(f"file:{backup}?mode=ro", uri=True) as connection:
        assert connection.execute(
            "SELECT value FROM rehearsal_sentinel"
        ).fetchone() == ("preserved",)


def test_rehearsal_rejects_future_schema_and_removes_restored_copy(tmp_path):
    source = tmp_path / "future.sqlite3"
    backups = tmp_path / "backups"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with sqlite3.connect(source) as connection:
        connection.execute(
            "CREATE TABLE alembic_version (version_num TEXT NOT NULL)"
        )
        connection.execute(
            "INSERT INTO alembic_version VALUES ('future_revision')"
        )
    backup = create_backup(source, backups, retention=2)
    digest_before = sha256_file(backup)

    with pytest.raises(MigrationBootstrapError, match="unknown"):
        rehearse_database_migration(
            backups / BACKUP_HEALTH_RECORD,
            workspace=workspace,
        )

    assert sha256_file(backup) == digest_before
    assert list(workspace.iterdir()) == []


def test_rehearsal_applies_pending_target_image_revision(tmp_path):
    source = tmp_path / "previous.sqlite3"
    backups = tmp_path / "backups"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _database_at_revision(source, "20260710_0013")
    backup = create_backup(source, backups, retention=2)
    digest_before = sha256_file(backup)

    result = rehearse_database_migration(
        backups / BACKUP_HEALTH_RECORD,
        workspace=workspace,
    )

    assert result.source_revision == "20260710_0013"
    assert result.target_revision == "20260710_0014"
    assert result.action == "upgraded"
    assert result.applied_revisions == ("20260710_0014",)
    assert sha256_file(backup) == digest_before
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("changed_revision", ["source", "target"])
def test_rehearsal_rejects_incoherent_migration_report(
    tmp_path,
    changed_revision,
):
    source = tmp_path / "source.sqlite3"
    backups = tmp_path / "backups"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _current_database(source)
    backup = create_backup(source, backups, retention=2)
    digest_before = sha256_file(backup)

    def inconsistent_runner(engine):
        report = run_database_migrations(engine)
        if changed_revision == "source":
            return replace(report, revision_before="wrong_source")
        return replace(report, revision_after="wrong_target")

    with pytest.raises(RuntimeError, match="revision"):
        rehearse_database_migration(
            backups / BACKUP_HEALTH_RECORD,
            workspace=workspace,
            migration_runner=inconsistent_runner,
        )

    assert sha256_file(backup) == digest_before
    assert list(workspace.iterdir()) == []


def test_rehearsal_rejects_symlink_workspace_before_reading_backup(tmp_path):
    real_workspace = tmp_path / "real-workspace"
    real_workspace.mkdir()
    linked_workspace = tmp_path / "linked-workspace"
    linked_workspace.symlink_to(real_workspace, target_is_directory=True)

    with pytest.raises(RuntimeError, match="workspace"):
        rehearse_database_migration(
            tmp_path / "missing-heartbeat.json",
            workspace=linked_workspace,
        )

    assert list(real_workspace.iterdir()) == []


def test_cli_failure_does_not_expose_database_diagnostics(monkeypatch, capsys):
    def fail(*_args, **_kwargs):
        raise RuntimeError("private database diagnostic")

    monkeypatch.setattr(
        "ops.rehearse_database_migration.rehearse_database_migration",
        fail,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["rehearse_database_migration.py", "--heartbeat", "/missing"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "database migration rehearsal failed\n"
    assert "private" not in captured.err
