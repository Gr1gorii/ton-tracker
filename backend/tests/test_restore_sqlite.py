"""Fail-closed SQLite recovery drill tests."""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3

import pytest

from ops.backup_sqlite import BACKUP_HEALTH_RECORD, create_backup
from ops.restore_sqlite import (
    RECOVERY_HEALTH_RECORD,
    check_recovery_health,
    invalidate_recovery_health_record,
    restore_from_heartbeat,
    run_recovery_drill,
)


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('20260710_0014')")
        connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence VALUES ('recovery-proof')")


def test_recovery_drill_restores_verified_backup_without_overwrite(tmp_path):
    source = tmp_path / "source.sqlite3"
    backups = tmp_path / "backups"
    restored = tmp_path / "restored.sqlite3"
    _database(source)
    backup = create_backup(source, backups, retention=2)

    result = restore_from_heartbeat(
        backups / BACKUP_HEALTH_RECORD,
        restored,
    )

    assert result.source == backup
    assert result.restored == restored
    assert result.schema_revision == "20260710_0014"
    assert result.size_bytes == backup.stat().st_size
    assert len(result.sha256) == 64
    assert restored.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob(".*.restore.tmp")) == []
    with sqlite3.connect(f"file:{restored}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT value FROM evidence").fetchone() == (
            "recovery-proof",
        )

    original = restored.read_bytes()
    with pytest.raises(RuntimeError, match="already exists"):
        restore_from_heartbeat(backups / BACKUP_HEALTH_RECORD, restored)
    assert restored.read_bytes() == original


def test_recovery_drill_rejects_same_size_backup_tampering(tmp_path):
    source = tmp_path / "source.sqlite3"
    backups = tmp_path / "backups"
    _database(source)
    backup = create_backup(source, backups, retention=2)
    payload = bytearray(backup.read_bytes())
    payload[-1] ^= 1
    backup.write_bytes(payload)

    with pytest.raises(RuntimeError, match="digest"):
        restore_from_heartbeat(
            backups / BACKUP_HEALTH_RECORD,
            tmp_path / "restored.sqlite3",
        )


def test_recovery_drill_rejects_symlink_and_path_traversal_heartbeat(tmp_path):
    target = tmp_path / "heartbeat.json"
    target.write_text("{}", encoding="utf-8")
    heartbeat = tmp_path / BACKUP_HEALTH_RECORD
    heartbeat.symlink_to(target)
    with pytest.raises(RuntimeError, match="regular file"):
        restore_from_heartbeat(heartbeat, tmp_path / "restored.sqlite3")

    heartbeat.unlink()
    record = {
        "schema_version": 1,
        "status": "verified",
        "backup_file": "../source.sqlite3",
        "completed_at": "2026-07-30T12:00:00Z",
        "size_bytes": 1,
        "sha256": "a" * 64,
        "schema_revision": "20260710_0014",
        "integrity_check": "ok",
    }
    heartbeat.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(RuntimeError, match="fields"):
        restore_from_heartbeat(heartbeat, tmp_path / "restored.sqlite3")

    record["backup_file"] = "ton-check-20260730T120000Z.sqlite3"
    record["completed_at"] = "2026-99-30T12:00:00Z"
    heartbeat.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(RuntimeError, match="fields"):
        restore_from_heartbeat(heartbeat, tmp_path / "restored.sqlite3")

    heartbeat.write_bytes(b"{" + (b"x" * 20_000))
    with pytest.raises(RuntimeError, match="bounded"):
        restore_from_heartbeat(heartbeat, tmp_path / "restored.sqlite3")


def test_recovery_drill_requires_private_new_destination(tmp_path):
    source = tmp_path / "source.sqlite3"
    backups = tmp_path / "backups"
    _database(source)
    create_backup(source, backups, retention=2)
    destination = tmp_path / "missing" / "restored.sqlite3"

    with pytest.raises(RuntimeError, match="directory"):
        restore_from_heartbeat(backups / BACKUP_HEALTH_RECORD, destination)
    assert not destination.exists()
    assert not os.path.lexists(destination)

    protected = tmp_path / "protected.sqlite3"
    protected.write_bytes(b"do-not-overwrite")
    linked_destination = tmp_path / "linked.sqlite3"
    linked_destination.symlink_to(protected)
    with pytest.raises(RuntimeError, match="already exists"):
        restore_from_heartbeat(
            backups / BACKUP_HEALTH_RECORD,
            linked_destination,
        )
    assert protected.read_bytes() == b"do-not-overwrite"


def test_scheduled_recovery_drill_publishes_bounded_health_and_cleans_workspace(
    tmp_path,
):
    source = tmp_path / "source.sqlite3"
    backups = tmp_path / "backups"
    recovery = tmp_path / "recovery"
    recovery.mkdir()
    _database(source)
    backup = create_backup(source, backups, retention=2)
    completed = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
    status_file = recovery / RECOVERY_HEALTH_RECORD

    result = run_recovery_drill(
        backups / BACKUP_HEALTH_RECORD,
        workspace=tmp_path,
        status_file=status_file,
        completed_at=completed,
    )

    assert result.source == backup
    assert not result.restored.exists()
    assert status_file.stat().st_mode & 0o777 == 0o600
    assert list(tmp_path.glob("restore-drill-*.sqlite3")) == []
    record = check_recovery_health(
        status_file,
        maximum_age_seconds=900,
        now=completed.timestamp() + 899,
    )
    assert record == {
        "schema_version": 1,
        "status": "passed",
        "completed_at": "2026-07-30T12:00:00Z",
        "backup_file": backup.name,
        "backup_size_bytes": backup.stat().st_size,
        "backup_sha256": result.sha256,
        "schema_revision": "20260710_0014",
        "integrity_check": "ok",
        "restore_check": "ok",
    }
    with pytest.raises(RuntimeError, match="stale"):
        check_recovery_health(
            status_file,
            maximum_age_seconds=900,
            now=completed.timestamp() + 901,
        )

    invalidate_recovery_health_record(status_file)
    assert not status_file.exists()
