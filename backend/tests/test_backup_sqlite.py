"""Verified SQLite backup retention tests."""

from pathlib import Path
import sqlite3

from ops.backup_sqlite import create_backup, verify_backup


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
    verify_backup(first)
    with sqlite3.connect(source) as connection:
        connection.execute("INSERT INTO evidence VALUES ('second')")
    second = create_backup(source, backups, retention=1)
    verify_backup(second)
    assert list(backups.glob("*.tmp")) == []
    assert len(list(backups.glob("ton-check-*.sqlite3"))) == 1
