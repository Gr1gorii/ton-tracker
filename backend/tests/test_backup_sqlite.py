"""Verified SQLite backup retention tests."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3

import pytest

from ops.backup_sqlite import (
    BACKUP_HEALTH_RECORD,
    check_backup_health,
    create_backup,
    verify_backup,
    write_backup_health_record,
)


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('20260710_0013')")
        connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence VALUES ('proof')")


def test_backup_is_atomic_verified_and_retained(tmp_path):
    source = tmp_path / "source.db"
    backups = tmp_path / "backups"
    _database(source)
    first = create_backup(source, backups, retention=1)
    assert verify_backup(first) == "20260710_0013"
    with sqlite3.connect(source) as connection:
        connection.execute("INSERT INTO evidence VALUES ('second')")
    second = create_backup(source, backups, retention=1)
    assert verify_backup(second) == "20260710_0013"
    assert list(backups.glob("*.tmp")) == []
    assert list(backups.glob(".*.tmp")) == []
    assert len(list(backups.glob("ton-check-*.sqlite3"))) == 1
    heartbeat = json.loads((backups / BACKUP_HEALTH_RECORD).read_text())
    assert heartbeat["schema_version"] == 1
    assert heartbeat["status"] == "verified"
    assert heartbeat["backup_file"] == second.name
    assert heartbeat["size_bytes"] == second.stat().st_size
    assert heartbeat["sha256"] == hashlib.sha256(second.read_bytes()).hexdigest()
    assert heartbeat["schema_revision"] == "20260710_0013"
    assert heartbeat["integrity_check"] == "ok"
    assert datetime.fromisoformat(heartbeat["completed_at"].replace("Z", "+00:00")).tzinfo == timezone.utc


def test_backup_health_record_rejects_invalid_revision_and_naive_time(tmp_path):
    backup = tmp_path / "ton-check-20260730T120000Z.sqlite3"
    backup.write_bytes(b"backup")
    with pytest.raises(RuntimeError, match="revision"):
        write_backup_health_record(backup, schema_revision="bad revision")
    with pytest.raises(RuntimeError, match="timezone-aware"):
        write_backup_health_record(
            backup,
            schema_revision="20260710_0013",
            completed_at=datetime(2026, 7, 30, 12, 0),
        )


def test_backup_healthcheck_accepts_the_newest_verified_backup(tmp_path):
    source = tmp_path / "source.sqlite3"
    _database(source)
    backups = tmp_path / "backups"
    backup = create_backup(source, backups, retention=2)
    modified = backup.stat().st_mtime

    assert check_backup_health(
        backups,
        maximum_age_seconds=900,
        now=modified + 899,
    ) == backup


def test_backup_healthcheck_rejects_missing_stale_and_corrupt_backups(tmp_path):
    backups = tmp_path / "backups"
    backups.mkdir()
    with pytest.raises(RuntimeError, match="No completed"):
        check_backup_health(backups, maximum_age_seconds=900, now=1_000)

    source = tmp_path / "source.sqlite3"
    _database(source)
    backup = create_backup(source, backups, retention=2)
    modified = backup.stat().st_mtime
    with pytest.raises(RuntimeError, match="stale"):
        check_backup_health(
            backups,
            maximum_age_seconds=900,
            now=modified + 901,
        )
    with pytest.raises(RuntimeError, match="future"):
        check_backup_health(
            backups,
            maximum_age_seconds=900,
            now=modified - 301,
        )

    backup.write_bytes(b"not a sqlite database")
    with pytest.raises(sqlite3.DatabaseError):
        check_backup_health(
            backups,
            maximum_age_seconds=900,
            now=modified + 1,
        )
