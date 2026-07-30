"""Perform a fail-closed SQLite recovery drill from a backup heartbeat."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from urllib.parse import quote

try:
    from .backup_sqlite import sha256_file, verify_backup
except ImportError:  # pragma: no cover - direct script execution in the image
    from backup_sqlite import sha256_file, verify_backup


_MAX_HEARTBEAT_BYTES = 16_384
_BACKUP_NAME = re.compile(r"^ton-check-[0-9]{8}T[0-9]{6}Z\.sqlite3$")
_COMPLETED_AT = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?Z$"
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_REVISION = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_HEARTBEAT_KEYS = {
    "backup_file",
    "completed_at",
    "integrity_check",
    "schema_revision",
    "schema_version",
    "sha256",
    "size_bytes",
    "status",
}


@dataclass(frozen=True)
class RecoveryDrillResult:
    source: Path
    restored: Path
    schema_revision: str
    size_bytes: int
    sha256: str


def restore_from_heartbeat(heartbeat: Path, destination: Path) -> RecoveryDrillResult:
    """Restore the heartbeat-selected backup without overwriting any file."""
    record = _load_heartbeat(heartbeat)
    backup_name = record["backup_file"]
    expected_size = record["size_bytes"]
    expected_sha256 = record["sha256"]
    expected_revision = record["schema_revision"]
    source = heartbeat.parent / backup_name

    try:
        source_metadata = source.lstat()
    except OSError as exc:
        raise RuntimeError("Heartbeat-selected backup is unavailable.") from exc
    if not stat.S_ISREG(source_metadata.st_mode):
        raise RuntimeError("Heartbeat-selected backup must be a regular file.")
    if source_metadata.st_size != expected_size:
        raise RuntimeError("Heartbeat-selected backup size does not match.")
    if not hmac.compare_digest(sha256_file(source), expected_sha256):
        raise RuntimeError("Heartbeat-selected backup digest does not match.")
    source_revision = verify_backup(source)
    if source_revision != expected_revision:
        raise RuntimeError("Heartbeat-selected backup schema revision does not match.")

    restored_revision = _restore_without_overwrite(source, destination)
    if restored_revision != expected_revision:
        destination.unlink(missing_ok=True)
        raise RuntimeError("Restored database schema revision does not match.")
    if not hmac.compare_digest(sha256_file(source), expected_sha256):
        destination.unlink(missing_ok=True)
        raise RuntimeError("Backup changed during the recovery drill.")
    return RecoveryDrillResult(
        source=source,
        restored=destination,
        schema_revision=restored_revision,
        size_bytes=expected_size,
        sha256=expected_sha256,
    )


def _load_heartbeat(path: Path) -> dict[str, object]:
    record = _read_bounded_json(path)
    if not isinstance(record, dict) or set(record) != _HEARTBEAT_KEYS:
        raise RuntimeError("Backup heartbeat contract is invalid.")
    backup_name = record["backup_file"]
    completed_at = record["completed_at"]
    size_bytes = record["size_bytes"]
    sha256 = record["sha256"]
    schema_revision = record["schema_revision"]
    if (
        record["schema_version"] != 1
        or record["status"] != "verified"
        or record["integrity_check"] != "ok"
        or not isinstance(backup_name, str)
        or _BACKUP_NAME.fullmatch(backup_name) is None
        or not _is_utc_timestamp(completed_at)
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes < 1
        or not isinstance(sha256, str)
        or _SHA256.fullmatch(sha256) is None
        or not isinstance(schema_revision, str)
        or _SCHEMA_REVISION.fullmatch(schema_revision) is None
    ):
        raise RuntimeError("Backup heartbeat fields are invalid.")
    return record


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _COMPLETED_AT.fullmatch(value) is None:
        return False
    try:
        completed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return completed.utcoffset() == timedelta(0)


def _read_bounded_json(path: Path) -> object:
    try:
        before = path.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_HEARTBEAT_BYTES:
            raise RuntimeError("Backup heartbeat must be a bounded regular file.")
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError as exc:
        raise RuntimeError("Backup heartbeat is unavailable.") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_size > _MAX_HEARTBEAT_BYTES
        ):
            raise RuntimeError("Backup heartbeat changed while it was opened.")
        payload = bytearray()
        while len(payload) <= _MAX_HEARTBEAT_BYTES:
            chunk = os.read(descriptor, _MAX_HEARTBEAT_BYTES + 1 - len(payload))
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > _MAX_HEARTBEAT_BYTES:
            raise RuntimeError("Backup heartbeat exceeds the size limit.")
        try:
            return json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Backup heartbeat JSON is invalid.") from exc
    finally:
        os.close(descriptor)


def _restore_without_overwrite(source: Path, destination: Path) -> str:
    if destination.exists() or destination.is_symlink():
        raise RuntimeError("Recovery destination already exists.")
    if not destination.parent.is_dir():
        raise RuntimeError("Recovery destination directory does not exist.")
    temporary = destination.with_name(f".{destination.name}.restore.tmp")
    descriptor = None
    created_temporary = False
    linked_destination = False
    published = False
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        created_temporary = True
        os.close(descriptor)
        descriptor = None
        with sqlite3.connect(_readonly_uri(source), uri=True) as source_db:
            with sqlite3.connect(temporary) as restored_db:
                source_db.backup(restored_db)
        restored_revision = verify_backup(temporary)
        with temporary.open("rb") as handle:
            os.fsync(handle.fileno())
        os.link(temporary, destination)
        linked_destination = True
        temporary.unlink()
        _fsync_directory(destination.parent)
        published = True
        return restored_revision
    except FileExistsError as exc:
        raise RuntimeError("Recovery destination or temporary file already exists.") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if created_temporary:
            temporary.unlink(missing_ok=True)
        if linked_destination and not published:
            destination.unlink(missing_ok=True)


def _readonly_uri(path: Path) -> str:
    return f"file:{quote(str(path.resolve()), safe='/')}?mode=ro&immutable=1"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--heartbeat", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    result = restore_from_heartbeat(args.heartbeat, args.destination)
    print(
        "recovery drill passed "
        f"backup={result.source.name} schema={result.schema_revision} "
        f"bytes={result.size_bytes}",
        flush=True,
    )


if __name__ == "__main__":
    main()
