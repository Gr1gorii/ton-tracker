"""Small dependency-free Prometheus metrics registry."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import threading
import time


_STARTED_AT = time.time()
_LOCK = threading.Lock()
_REQUESTS: dict[tuple[str, str, int], int] = defaultdict(int)
_DURATION_SUM: dict[tuple[str, str], float] = defaultdict(float)
_DURATION_COUNT: dict[tuple[str, str], int] = defaultdict(int)
_BACKUP_NAME = re.compile(r"^ton-check-[0-9]{8}T[0-9]{6}Z\.sqlite3$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_REVISION = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_MAX_BACKUP_RECORD_BYTES = 16_384
_BACKUP_RECORD_KEYS = {
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
class BackupHealthMetrics:
    configured: bool
    ready: bool
    age_seconds: float | None = None
    last_success_timestamp_seconds: float | None = None
    size_bytes: int | None = None


def observe_http_request(
    method: str,
    route: str,
    status: int,
    duration_seconds: float,
) -> None:
    route = route if route.startswith("/") else "unmatched"
    with _LOCK:
        _REQUESTS[(method, route, status)] += 1
        _DURATION_SUM[(method, route)] += max(0.0, duration_seconds)
        _DURATION_COUNT[(method, route)] += 1


def read_backup_health_metrics(
    health_file: str,
    *,
    maximum_age_seconds: int,
    now: float | None = None,
) -> BackupHealthMetrics:
    """Read a bounded, fail-closed backup heartbeat without opening SQLite."""
    if not health_file:
        return BackupHealthMetrics(configured=False, ready=False)
    path = Path(health_file)
    try:
        record = _read_bounded_json(path)
        if not isinstance(record, dict) or set(record) != _BACKUP_RECORD_KEYS:
            return BackupHealthMetrics(configured=True, ready=False)
        completed_at = record["completed_at"]
        if not isinstance(completed_at, str) or not completed_at.endswith("Z"):
            return BackupHealthMetrics(configured=True, ready=False)
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        if completed.tzinfo is None or completed.utcoffset() is None:
            return BackupHealthMetrics(configured=True, ready=False)
        timestamp = completed.astimezone(timezone.utc).timestamp()
        current = time.time() if now is None else now
        age = current - timestamp
        size_bytes = record["size_bytes"]
        backup_name = record["backup_file"]
        if (
            record["schema_version"] != 1
            or record["status"] != "verified"
            or record["integrity_check"] != "ok"
            or not isinstance(backup_name, str)
            or _BACKUP_NAME.fullmatch(backup_name) is None
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 1
            or not isinstance(record["sha256"], str)
            or _SHA256.fullmatch(record["sha256"]) is None
            or not isinstance(record["schema_revision"], str)
            or _SCHEMA_REVISION.fullmatch(record["schema_revision"]) is None
        ):
            return BackupHealthMetrics(configured=True, ready=False)
        artifact_matches = _backup_artifact_matches(
            path.parent / backup_name,
            expected_size=size_bytes,
            expected_sha256=record["sha256"],
        )
        ready = (
            artifact_matches
            and age >= -300
            and age <= maximum_age_seconds
        )
        return BackupHealthMetrics(
            configured=True,
            ready=ready,
            age_seconds=max(0.0, age),
            last_success_timestamp_seconds=timestamp,
            size_bytes=size_bytes,
        )
    except (OSError, UnicodeError, ValueError, TypeError, OverflowError, json.JSONDecodeError):
        return BackupHealthMetrics(configured=True, ready=False)


def _read_bounded_json(path: Path) -> object:
    """Read one regular file without following replacements or unbounded growth."""
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > _MAX_BACKUP_RECORD_BYTES:
        raise ValueError("Backup heartbeat must be a bounded regular file.")
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        opened = os.fstat(descriptor)
        if (
            not stat.S_ISREG(opened.st_mode)
            or opened.st_dev != before.st_dev
            or opened.st_ino != before.st_ino
            or opened.st_size > _MAX_BACKUP_RECORD_BYTES
        ):
            raise ValueError("Backup heartbeat changed while it was opened.")
        payload = bytearray()
        while len(payload) <= _MAX_BACKUP_RECORD_BYTES:
            chunk = os.read(
                descriptor,
                _MAX_BACKUP_RECORD_BYTES + 1 - len(payload),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > _MAX_BACKUP_RECORD_BYTES:
            raise ValueError("Backup heartbeat exceeds the size limit.")
        return json.loads(payload.decode("utf-8"))
    finally:
        os.close(descriptor)


def _backup_artifact_matches(
    path: Path,
    *,
    expected_size: int,
    expected_sha256: str,
) -> bool:
    """Validate an immutable backup once per filesystem identity."""
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != expected_size:
            return False
        return _cached_backup_digest_matches(
            str(path),
            metadata.st_dev,
            metadata.st_ino,
            metadata.st_size,
            metadata.st_mtime_ns,
            metadata.st_ctime_ns,
            expected_sha256,
        )
    except OSError:
        return False


@lru_cache(maxsize=16)
def _cached_backup_digest_matches(
    path: str,
    device: int,
    inode: int,
    size: int,
    modified_ns: int,
    changed_ns: int,
    expected_sha256: str,
) -> bool:
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_dev != device
            or metadata.st_ino != inode
            or metadata.st_size != size
            or metadata.st_mtime_ns != modified_ns
            or metadata.st_ctime_ns != changed_ns
        ):
            return False
        digest = hashlib.sha256()
        while chunk := os.read(descriptor, 1024 * 1024):
            digest.update(chunk)
        return digest.hexdigest() == expected_sha256
    finally:
        os.close(descriptor)


def render_prometheus_metrics(
    *,
    version: str,
    database_ready: bool,
    backup: BackupHealthMetrics | None = None,
) -> str:
    backup = backup or BackupHealthMetrics(configured=False, ready=False)
    with _LOCK:
        request_rows = list(_REQUESTS.items())
        duration_sums = list(_DURATION_SUM.items())
        duration_counts = list(_DURATION_COUNT.items())
    lines = [
        "# HELP ton_tracker_build_info Application build information.",
        "# TYPE ton_tracker_build_info gauge",
        f'ton_tracker_build_info{{version="{_escape(version)}"}} 1',
        "# HELP ton_tracker_process_start_time_seconds Process start time.",
        "# TYPE ton_tracker_process_start_time_seconds gauge",
        f"ton_tracker_process_start_time_seconds {_STARTED_AT:.3f}",
        "# HELP ton_tracker_database_ready Database readiness state.",
        "# TYPE ton_tracker_database_ready gauge",
        f"ton_tracker_database_ready {1 if database_ready else 0}",
        "# HELP ton_tracker_backup_monitoring_configured Backup heartbeat monitoring configuration state.",
        "# TYPE ton_tracker_backup_monitoring_configured gauge",
        f"ton_tracker_backup_monitoring_configured {1 if backup.configured else 0}",
        "# HELP ton_tracker_backup_ready Latest backup heartbeat and artifact readiness state.",
        "# TYPE ton_tracker_backup_ready gauge",
        f"ton_tracker_backup_ready {1 if backup.ready else 0}",
    ]
    if backup.last_success_timestamp_seconds is not None:
        lines.extend((
            "# HELP ton_tracker_backup_last_success_timestamp_seconds Latest verified backup completion time.",
            "# TYPE ton_tracker_backup_last_success_timestamp_seconds gauge",
            f"ton_tracker_backup_last_success_timestamp_seconds {backup.last_success_timestamp_seconds:.3f}",
        ))
    if backup.age_seconds is not None:
        lines.extend((
            "# HELP ton_tracker_backup_age_seconds Age of the latest verified backup heartbeat.",
            "# TYPE ton_tracker_backup_age_seconds gauge",
            f"ton_tracker_backup_age_seconds {backup.age_seconds:.3f}",
        ))
    if backup.size_bytes is not None:
        lines.extend((
            "# HELP ton_tracker_backup_size_bytes Size of the latest verified backup artifact.",
            "# TYPE ton_tracker_backup_size_bytes gauge",
            f"ton_tracker_backup_size_bytes {backup.size_bytes}",
        ))
    lines.extend((
        "# HELP ton_tracker_http_requests_total HTTP requests by route and status.",
        "# TYPE ton_tracker_http_requests_total counter",
    ))
    for (method, route, status), count in sorted(request_rows):
        lines.append(
            "ton_tracker_http_requests_total"
            f'{{method="{_escape(method)}",route="{_escape(route)}",'
            f'status="{status}"}} {count}'
        )
    lines.extend(
        (
            "# HELP ton_tracker_http_request_duration_seconds_sum "
            "Cumulative request duration.",
            "# TYPE ton_tracker_http_request_duration_seconds_sum counter",
        )
    )
    for (method, route), value in sorted(duration_sums):
        lines.append(
            "ton_tracker_http_request_duration_seconds_sum"
            f'{{method="{_escape(method)}",route="{_escape(route)}"}} '
            f"{value:.9f}"
        )
    lines.extend(
        (
            "# HELP ton_tracker_http_request_duration_seconds_count "
            "Observed request duration count.",
            "# TYPE ton_tracker_http_request_duration_seconds_count counter",
        )
    )
    for (method, route), count in sorted(duration_counts):
        lines.append(
            "ton_tracker_http_request_duration_seconds_count"
            f'{{method="{_escape(method)}",route="{_escape(route)}"}} {count}'
        )
    return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
