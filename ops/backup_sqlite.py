"""Create verified, atomic SQLite backups with retention."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import unquote


def database_path() -> Path:
    url = os.environ.get("TON_CHECK_DB_URL", "sqlite:////data/ton_check.db")
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise RuntimeError("Backup sidecar supports SQLite database URLs only.")
    raw = unquote(url[len(prefix) :])
    return Path("/" + raw.lstrip("/")) if raw.startswith("/") else Path(raw)


def create_backup(source: Path, destination_dir: Path, retention: int) -> Path:
    if not source.is_file():
        raise RuntimeError(f"SQLite source database does not exist: {source}")
    destination_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = destination_dir / f"ton-check-{timestamp}.sqlite3"
    temporary = final.with_suffix(".sqlite3.tmp")
    temporary.unlink(missing_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(temporary) as backup_db:
        source_db.backup(backup_db)
    verify_backup(temporary)
    temporary.replace(final)
    _apply_retention(destination_dir, max(1, retention))
    return final


def verify_backup(path: Path) -> None:
    if not path.is_file():
        raise RuntimeError(f"Backup does not exist: {path}")
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        result = connection.execute("PRAGMA quick_check").fetchone()
        if result != ("ok",):
            raise RuntimeError(f"SQLite backup integrity check failed: {result!r}")
        version = connection.execute(
            "SELECT version_num FROM alembic_version"
        ).fetchone()
        if version is None or not str(version[0]).strip():
            raise RuntimeError("Backup has no Alembic schema revision.")


def _apply_retention(directory: Path, retention: int) -> None:
    backups = sorted(
        directory.glob("ton-check-*.sqlite3"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for expired in backups[retention:]:
        expired.unlink()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--verify", type=Path)
    args = parser.parse_args()
    if args.verify is not None:
        verify_backup(args.verify)
        print(f"verified {args.verify}", flush=True)
        return
    source = database_path()
    directory = Path(os.environ.get("BACKUP_DIR", "/backups"))
    retention = int(os.environ.get("BACKUP_RETENTION", "14"))
    interval = max(300, int(os.environ.get("BACKUP_INTERVAL_SECONDS", "86400")))
    while True:
        backup = create_backup(source, directory, retention)
        print(f"created {backup}", flush=True)
        if not args.loop:
            return
        time.sleep(interval)


if __name__ == "__main__":
    main()
