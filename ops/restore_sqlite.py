"""Perform a fail-closed SQLite recovery drill from a backup heartbeat."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from urllib.parse import quote

try:
    from .backup_sqlite import sha256_file, verify_backup
except ImportError:  # pragma: no cover - direct script execution in the image
    from backup_sqlite import sha256_file, verify_backup


_MAX_HEARTBEAT_BYTES = 16_384
RECOVERY_HEALTH_RECORD = ".recovery-health.json"
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
_RECOVERY_HEARTBEAT_KEYS = {
    "backup_file",
    "backup_sha256",
    "backup_size_bytes",
    "completed_at",
    "integrity_check",
    "restore_check",
    "schema_revision",
    "schema_version",
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


def run_recovery_drill(
    heartbeat: Path,
    *,
    workspace: Path,
    status_file: Path,
    completed_at: datetime | None = None,
) -> RecoveryDrillResult:
    """Restore into ephemeral storage and atomically publish a success record."""
    if not workspace.is_dir():
        raise RuntimeError("Recovery drill workspace does not exist.")
    if not status_file.parent.is_dir():
        raise RuntimeError("Recovery status directory does not exist.")
    destination = workspace / f"restore-drill-{secrets.token_hex(8)}.sqlite3"
    try:
        result = restore_from_heartbeat(heartbeat, destination)
        destination.unlink()
        write_recovery_health_record(
            status_file,
            result=result,
            completed_at=completed_at,
        )
        return result
    finally:
        destination.unlink(missing_ok=True)


def write_recovery_health_record(
    destination: Path,
    *,
    result: RecoveryDrillResult,
    completed_at: datetime | None = None,
) -> Path:
    completed = completed_at or datetime.now(timezone.utc)
    if completed.tzinfo is None or completed.utcoffset() is None:
        raise RuntimeError("Recovery completion time must be timezone-aware.")
    if (
        not isinstance(result.source, Path)
        or _BACKUP_NAME.fullmatch(result.source.name) is None
        or not isinstance(result.size_bytes, int)
        or isinstance(result.size_bytes, bool)
        or result.size_bytes < 1
        or not isinstance(result.sha256, str)
        or _SHA256.fullmatch(result.sha256) is None
        or not isinstance(result.schema_revision, str)
        or _SCHEMA_REVISION.fullmatch(result.schema_revision) is None
    ):
        raise RuntimeError("Recovery result fields are invalid.")
    record = {
        "schema_version": 1,
        "status": "passed",
        "completed_at": completed.astimezone(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "backup_file": result.source.name,
        "backup_size_bytes": result.size_bytes,
        "backup_sha256": result.sha256,
        "schema_revision": result.schema_revision,
        "integrity_check": "ok",
        "restore_check": "ok",
    }
    temporary = destination.with_name(
        f".{destination.name}.{secrets.token_hex(8)}.tmp"
    )
    descriptor = None
    try:
        descriptor = os.open(
            temporary,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            descriptor = None
            json.dump(record, handle, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(destination)
        _fsync_directory(destination.parent)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return destination


def invalidate_recovery_health_record(status_file: Path) -> None:
    """Make a failed latest drill visible instead of serving stale success."""
    status_file.unlink(missing_ok=True)
    _fsync_directory(status_file.parent)


def check_recovery_health(
    status_file: Path,
    *,
    maximum_age_seconds: int,
    now: float | None = None,
) -> dict[str, object]:
    if maximum_age_seconds < 1:
        raise ValueError("maximum_age_seconds must be positive")
    record = _load_recovery_status(status_file)
    completed = datetime.fromisoformat(
        str(record["completed_at"]).replace("Z", "+00:00")
    )
    current = time.time() if now is None else now
    age_seconds = current - completed.timestamp()
    if age_seconds < -300:
        raise RuntimeError("Recovery status timestamp is unexpectedly in the future.")
    if age_seconds > maximum_age_seconds:
        raise RuntimeError(
            f"Recovery drill status is stale ({int(age_seconds)} seconds old)."
        )
    return record


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


def _load_recovery_status(path: Path) -> dict[str, object]:
    record = _read_bounded_json(path)
    if not isinstance(record, dict) or set(record) != _RECOVERY_HEARTBEAT_KEYS:
        raise RuntimeError("Recovery status contract is invalid.")
    backup_name = record["backup_file"]
    backup_size = record["backup_size_bytes"]
    backup_sha256 = record["backup_sha256"]
    schema_revision = record["schema_revision"]
    if (
        record["schema_version"] != 1
        or record["status"] != "passed"
        or record["integrity_check"] != "ok"
        or record["restore_check"] != "ok"
        or not _is_utc_timestamp(record["completed_at"])
        or not isinstance(backup_name, str)
        or _BACKUP_NAME.fullmatch(backup_name) is None
        or not isinstance(backup_size, int)
        or isinstance(backup_size, bool)
        or backup_size < 1
        or not isinstance(backup_sha256, str)
        or _SHA256.fullmatch(backup_sha256) is None
        or not isinstance(schema_revision, str)
        or _SCHEMA_REVISION.fullmatch(schema_revision) is None
    ):
        raise RuntimeError("Recovery status fields are invalid.")
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--loop", action="store_true")
    mode.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--heartbeat", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--workspace", type=Path, default=Path("/tmp"))
    parser.add_argument("--status-file", type=Path)
    args = parser.parse_args()
    interval = max(3600, int(os.environ.get("RECOVERY_INTERVAL_SECONDS", "604800")))
    if args.healthcheck:
        if args.status_file is None:
            parser.error("--status-file is required with --healthcheck")
        record = check_recovery_health(
            args.status_file,
            maximum_age_seconds=interval + 86_400,
        )
        print(
            "recovery watchdog healthy "
            f"backup={record['backup_file']} schema={record['schema_revision']}",
            flush=True,
        )
        return
    if args.heartbeat is None:
        parser.error("--heartbeat is required")
    if args.loop:
        if args.status_file is None:
            parser.error("--status-file is required with --loop")
        retry = max(60, int(os.environ.get("RECOVERY_RETRY_SECONDS", "300")))
        while True:
            try:
                result = run_recovery_drill(
                    args.heartbeat,
                    workspace=args.workspace,
                    status_file=args.status_file,
                )
                print(
                    "scheduled recovery drill passed "
                    f"backup={result.source.name} schema={result.schema_revision}",
                    flush=True,
                )
                time.sleep(interval)
            except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
                try:
                    invalidate_recovery_health_record(args.status_file)
                except OSError as invalidation_error:
                    print(
                        "recovery status invalidation failed: "
                        f"{invalidation_error}",
                        flush=True,
                    )
                print(f"scheduled recovery drill failed: {exc}", flush=True)
                time.sleep(retry)
    if args.destination is None:
        parser.error("--destination is required unless --loop is used")
    result = restore_from_heartbeat(args.heartbeat, args.destination)
    print(
        "recovery drill passed "
        f"backup={result.source.name} schema={result.schema_revision} "
        f"bytes={result.size_bytes}",
        flush=True,
    )


if __name__ == "__main__":
    main()
