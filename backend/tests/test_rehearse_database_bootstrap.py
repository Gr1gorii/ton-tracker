"""Fail-closed first-deployment database bootstrap tests."""

from __future__ import annotations

from pathlib import Path
import sqlite3
import sys

import pytest

from database import create_database_engine
from ops.backup_sqlite import BACKUP_HEALTH_RECORD
from ops.rehearse_database_bootstrap import main, rehearse_database_bootstrap
from ops.restore_sqlite import restore_from_heartbeat
from services.database_migrations import run_database_migrations


def _directories(tmp_path: Path) -> tuple[Path, Path, Path]:
    data = tmp_path / "data"
    backups = tmp_path / "backups"
    workspace = tmp_path / "workspace"
    data.mkdir()
    backups.mkdir()
    workspace.mkdir()
    return data, backups, workspace


def _current_database(path: Path) -> str:
    engine = create_database_engine(f"sqlite:///{path}")
    try:
        report = run_database_migrations(engine)
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "CREATE TABLE bootstrap_sentinel (value TEXT NOT NULL)"
            )
            connection.exec_driver_sql(
                "INSERT INTO bootstrap_sentinel VALUES ('preserved')"
            )
        return report.revision_after
    finally:
        engine.dispose()


@pytest.mark.parametrize("mode", ["fresh", "resume"])
def test_empty_volume_rehearses_current_schema_without_mutating_volume(
    tmp_path,
    mode,
):
    data, backups, workspace = _directories(tmp_path)

    result = rehearse_database_bootstrap(
        mode=mode,
        data_directory=data,
        backup_directory=backups,
        workspace=workspace,
        retention=14,
    )

    assert result.source == "empty"
    assert result.source_revision is None
    assert result.target_revision
    assert result.migration_action == "created"
    assert result.applied_revisions
    assert list(data.iterdir()) == []
    assert list(backups.iterdir()) == []
    assert list(workspace.iterdir()) == []


def test_fresh_mode_rejects_unmanaged_database_without_writing_backup(tmp_path):
    data, backups, workspace = _directories(tmp_path)
    unmanaged = data / "ton_check.db"
    unmanaged.write_bytes(b"unmanaged")

    with pytest.raises(RuntimeError, match="not empty"):
        rehearse_database_bootstrap(
            mode="fresh",
            data_directory=data,
            backup_directory=backups,
            workspace=workspace,
            retention=14,
        )

    assert unmanaged.read_bytes() == b"unmanaged"
    assert list(backups.iterdir()) == []
    assert list(workspace.iterdir()) == []


@pytest.mark.parametrize("mode", ["fresh", "resume"])
def test_empty_database_with_existing_backup_fails_closed(tmp_path, mode):
    data, backups, workspace = _directories(tmp_path)
    stale = backups / "ton-check-20260808T010203Z.sqlite3"
    stale.write_bytes(b"stale")

    with pytest.raises(RuntimeError, match="backup"):
        rehearse_database_bootstrap(
            mode=mode,
            data_directory=data,
            backup_directory=backups,
            workspace=workspace,
            retention=14,
        )

    assert stale.read_bytes() == b"stale"
    assert list(data.iterdir()) == []
    assert list(workspace.iterdir()) == []


def test_resume_mode_backs_up_and_rehearses_checkpointed_database(tmp_path):
    data, backups, workspace = _directories(tmp_path)
    database = data / "ton_check.db"
    revision = _current_database(database)

    result = rehearse_database_bootstrap(
        mode="resume",
        data_directory=data,
        backup_directory=backups,
        workspace=workspace,
        retention=14,
    )

    assert result.source == "checkpointed"
    assert result.source_revision == revision
    assert result.target_revision == revision
    assert result.migration_action == "already_current"
    assert result.applied_revisions == ()
    restored = tmp_path / "restored.sqlite3"
    restore_from_heartbeat(backups / BACKUP_HEALTH_RECORD, restored)
    with sqlite3.connect(f"file:{restored}?mode=ro", uri=True) as connection:
        assert connection.execute(
            "SELECT value FROM bootstrap_sentinel"
        ).fetchone() == ("preserved",)
    assert list(workspace.iterdir()) == []


def test_resume_mode_rejects_unexpected_backup_volume_entry(tmp_path):
    data, backups, workspace = _directories(tmp_path)
    _current_database(data / "ton_check.db")
    unexpected = backups / "operator-notes.txt"
    unexpected.write_text("unexpected", encoding="utf-8")

    with pytest.raises(RuntimeError, match="backup volume"):
        rehearse_database_bootstrap(
            mode="resume",
            data_directory=data,
            backup_directory=backups,
            workspace=workspace,
            retention=14,
        )

    assert unexpected.read_text(encoding="utf-8") == "unexpected"


@pytest.mark.parametrize("unexpected_name", ["unknown.db", "operator-notes.txt"])
def test_resume_mode_rejects_unexpected_volume_entries(
    tmp_path,
    unexpected_name,
):
    data, backups, workspace = _directories(tmp_path)
    _current_database(data / "ton_check.db")
    (data / unexpected_name).write_bytes(b"unexpected")

    with pytest.raises(RuntimeError, match="unexpected"):
        rehearse_database_bootstrap(
            mode="resume",
            data_directory=data,
            backup_directory=backups,
            workspace=workspace,
            retention=14,
        )

    assert list(backups.iterdir()) == []


def test_resume_mode_rejects_symlinked_database(tmp_path):
    data, backups, workspace = _directories(tmp_path)
    target = tmp_path / "outside.sqlite3"
    _current_database(target)
    (data / "ton_check.db").symlink_to(target)

    with pytest.raises(RuntimeError, match="regular file"):
        rehearse_database_bootstrap(
            mode="resume",
            data_directory=data,
            backup_directory=backups,
            workspace=workspace,
            retention=14,
        )

    assert list(backups.iterdir()) == []


def test_cli_failure_does_not_expose_bootstrap_diagnostics(
    monkeypatch,
    capsys,
):
    def fail(**_kwargs):
        raise RuntimeError("private bootstrap diagnostic")

    monkeypatch.setattr(
        "ops.rehearse_database_bootstrap.rehearse_database_bootstrap",
        fail,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        ["rehearse_database_bootstrap.py", "--mode", "fresh"],
    )

    with pytest.raises(SystemExit) as exc_info:
        main()

    assert exc_info.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "database bootstrap rehearsal failed\n"
    assert "private" not in captured.err
