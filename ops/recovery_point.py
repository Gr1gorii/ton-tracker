"""Create and verify release-bound external SQLite recovery points."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import sys
import time
from typing import Any

try:
    from .backup_sqlite import sha256_file, verify_backup
    from .create_release_manifest import validate_release_manifest
    from .restore_sqlite import (
        restore_database_without_overwrite,
        restore_from_heartbeat,
    )
    from .verify_release_bundle import (
        AttestationVerifier,
        ReleaseBundleVerificationError,
        verify_release_bundle,
    )
except ImportError:  # pragma: no cover - direct script execution in the image
    from backup_sqlite import sha256_file, verify_backup
    from create_release_manifest import validate_release_manifest
    from restore_sqlite import restore_database_without_overwrite, restore_from_heartbeat
    from verify_release_bundle import (
        AttestationVerifier,
        ReleaseBundleVerificationError,
        verify_release_bundle,
    )


RECOVERY_POINT_MANIFEST = "recovery-point.json"
RECOVERY_POINT_DATABASE = "database.sqlite3"
RECOVERY_POINT_DEPLOYMENT = "deployment.json"
RECOVERY_POINT_HEALTH = ".recovery-point-health.json"
RECOVERY_POINT_LOCK = ".recovery-point.lock"
_MAX_JSON_BYTES = 65_536
_MAX_DATABASE_BYTES = 1024 * 1024 * 1024 * 1024
_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SCHEMA_REVISION = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")
_BACKUP_NAME = re.compile(
    r"^ton-check-[0-9]{8}T[0-9]{6}(?:[0-9]{6})?Z\.sqlite3$"
)
_POINT_NAME = re.compile(
    r"^recovery-point-v(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)-"
    r"[0-9]{8}T[0-9]{12}Z-[0-9a-f]{16}$"
)
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z$"
)
_POINT_KEYS = {
    "created_at",
    "database",
    "deployment_manifest",
    "release",
    "schema",
    "verification",
}
_DATABASE_KEYS = {
    "file",
    "schema_revision",
    "sha256",
    "size_bytes",
    "source_backup_file",
    "source_backup_completed_at",
    "source_backup_sha256",
}
_DEPLOYMENT_KEYS = {"file", "sha256"}
_RELEASE_KEYS = {"manifest_sha256", "source_commit", "tag"}
_VERIFICATION_KEYS = {"database_integrity", "restore_check"}
_HEALTH_KEYS = {
    "created_at",
    "database_sha256",
    "recovery_manifest_sha256",
    "recovery_point",
    "release",
    "schema",
    "status",
}


class RecoveryPointError(RuntimeError):
    """An external recovery point failed a bounded integrity gate."""


@dataclass(frozen=True)
class VerifiedRecoveryPoint:
    directory: Path
    database: Path
    deployment_manifest: Path
    tag: str
    source_commit: str
    manifest_sha256: str
    database_sha256: str
    database_size_bytes: int
    schema_revision: str
    created_at: str
    source_backup_completed_at: str


def validate_recovery_point_directory(directory: Path) -> None:
    """Require a private, operator-owned directory without following links."""
    try:
        metadata = directory.lstat()
    except OSError as exc:
        raise RecoveryPointError("Recovery point directory is unavailable.") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise RecoveryPointError("Recovery point path must be a directory.")
    if metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077:
        raise RecoveryPointError(
            "Recovery point directory must be private and owned by the operator."
        )


def create_recovery_point(
    *,
    heartbeat: Path,
    deployment_manifest: Path | None,
    destination_directory: Path,
    retention: int,
    created_at: datetime | None = None,
    maximum_source_age_seconds: int = 172_800,
) -> VerifiedRecoveryPoint:
    """Restore a verified backup and atomically publish one external point."""
    if (
        not isinstance(retention, int)
        or isinstance(retention, bool)
        or retention < 2
        or retention > 365
    ):
        raise RecoveryPointError("Recovery point retention is invalid.")
    if (
        maximum_source_age_seconds < 3_600
        or maximum_source_age_seconds > 2_592_000
    ):
        raise RecoveryPointError("Recovery point source age limit is invalid.")
    if not destination_directory.is_absolute():
        raise RecoveryPointError("Recovery point destination must be absolute.")
    validate_recovery_point_directory(destination_directory)
    with _locked_recovery_point_directory(destination_directory):
        return _create_recovery_point_unlocked(
            heartbeat=heartbeat,
            deployment_manifest=deployment_manifest,
            destination_directory=destination_directory,
            retention=retention,
            created_at=created_at,
            maximum_source_age_seconds=maximum_source_age_seconds,
        )


def _create_recovery_point_unlocked(
    *,
    heartbeat: Path,
    deployment_manifest: Path | None,
    destination_directory: Path,
    retention: int,
    created_at: datetime | None,
    maximum_source_age_seconds: int,
) -> VerifiedRecoveryPoint:
    _validate_root_entries(destination_directory)
    _preflight_retention(destination_directory, retention)

    if deployment_manifest is None:
        deployment_manifest = verify_recovery_point_health(
            destination_directory
        ).deployment_manifest

    raw_deployment = _read_regular_file(
        deployment_manifest,
        maximum_bytes=_MAX_JSON_BYTES,
        label="Deployment manifest",
        require_private=False,
    )
    release_manifest = _decode_deployment_manifest(raw_deployment)
    release = release_manifest["release"]
    manifest_sha256 = hashlib.sha256(raw_deployment).hexdigest()
    completed = created_at or datetime.now(timezone.utc)
    if (
        not isinstance(completed, datetime)
        or completed.tzinfo is None
        or completed.utcoffset() is None
    ):
        raise RecoveryPointError("Recovery point time must be timezone-aware.")
    completed = completed.astimezone(timezone.utc)
    point_name = (
        f"recovery-point-{release['tag']}-"
        f"{completed.strftime('%Y%m%dT%H%M%S%fZ')}-"
        f"{secrets.token_hex(8)}"
    )
    if _POINT_NAME.fullmatch(point_name) is None:
        raise RecoveryPointError("Recovery point name is invalid.")
    final_directory = destination_directory / point_name
    staging_directory = destination_directory / f".{point_name}.tmp"
    published = False
    try:
        os.mkdir(staging_directory, 0o700)
        _write_private_file(
            staging_directory / RECOVERY_POINT_DEPLOYMENT,
            raw_deployment,
        )
        restored = restore_from_heartbeat(
            heartbeat,
            staging_directory / RECOVERY_POINT_DATABASE,
        )
        source_completed = datetime.fromisoformat(
            restored.source_completed_at.replace("Z", "+00:00")
        )
        source_age_seconds = time.time() - source_completed.timestamp()
        if source_age_seconds < -300:
            raise RecoveryPointError(
                "Recovery point source backup timestamp is unexpectedly in the future."
            )
        if source_age_seconds > maximum_source_age_seconds:
            raise RecoveryPointError(
                "Recovery point source backup is stale."
            )
        database = staging_directory / RECOVERY_POINT_DATABASE
        database_size = database.stat().st_size
        if database_size < 1 or database_size > _MAX_DATABASE_BYTES:
            raise RecoveryPointError("Recovery point database size is invalid.")
        database_sha256 = sha256_file(database)
        payload = _create_manifest(
            created_at=_utc_timestamp(completed),
            tag=release["tag"],
            source_commit=release["source_commit"],
            manifest_sha256=manifest_sha256,
            database_size_bytes=database_size,
            database_sha256=database_sha256,
            schema_revision=restored.schema_revision,
            source_backup_file=restored.source.name,
            source_backup_completed_at=restored.source_completed_at,
            source_backup_sha256=restored.sha256,
        )
        _write_private_json(
            staging_directory / RECOVERY_POINT_MANIFEST,
            payload,
        )
        _fsync_directory(staging_directory)
        os.rename(staging_directory, final_directory)
        _fsync_directory(destination_directory)
        published = True

        verified = verify_recovery_point(final_directory)
        health = {
            "schema": "gram_scope_recovery_point_health_v1",
            "status": "verified",
            "created_at": payload["created_at"],
            "recovery_point": point_name,
            "recovery_manifest_sha256": sha256_file(
                final_directory / RECOVERY_POINT_MANIFEST
            ),
            "database_sha256": verified.database_sha256,
            "release": payload["release"],
        }
        _validate_health(health)
        _write_atomic_json(
            destination_directory / RECOVERY_POINT_HEALTH,
            health,
        )
        _apply_retention(
            destination_directory,
            retention,
            protected_name=point_name,
        )
        verify_recovery_point_health(destination_directory)
        return verified
    except (OSError, ValueError, sqlite3.Error, RuntimeError) as exc:
        if isinstance(exc, RecoveryPointError):
            raise
        raise RecoveryPointError("Recovery point publication failed.") from exc
    finally:
        if not published:
            _remove_staging_directory(staging_directory)


def run_recovery_point_exporter(
    *,
    heartbeat: Path,
    destination_directory: Path,
    retention: int,
    interval_seconds: int,
    retry_seconds: int,
    maximum_age_seconds: int = 172_800,
    sleep: Callable[[float], None] = time.sleep,
    iterations: int | None = None,
    wait_for_due: bool = True,
) -> None:
    """Periodically export the newest backup under the latest release binding."""
    if interval_seconds < 3_600 or interval_seconds > 604_800:
        raise RecoveryPointError("Recovery point interval is invalid.")
    if retry_seconds < 60 or retry_seconds >= interval_seconds:
        raise RecoveryPointError("Recovery point retry interval is invalid.")
    if maximum_age_seconds < interval_seconds + retry_seconds:
        raise RecoveryPointError("Recovery point age limit is invalid.")
    if wait_for_due:
        try:
            current = check_recovery_point_health(
                destination_directory,
                maximum_age_seconds=interval_seconds,
            )
            completed_at = datetime.fromisoformat(
                current.created_at.replace("Z", "+00:00")
            ).timestamp()
            sleep(max(60.0, interval_seconds - (time.time() - completed_at)))
        except (OSError, RuntimeError, sqlite3.Error, ValueError):
            pass
    completed = 0
    while iterations is None or completed < iterations:
        try:
            point = create_recovery_point(
                heartbeat=heartbeat,
                deployment_manifest=None,
                destination_directory=destination_directory,
                retention=retention,
                maximum_source_age_seconds=maximum_age_seconds,
            )
            print(
                "external recovery point created "
                f"tag={point.tag} schema={point.schema_revision}",
                flush=True,
            )
            completed += 1
            if iterations is None or completed < iterations:
                sleep(interval_seconds)
        except (OSError, RuntimeError, sqlite3.Error, ValueError) as exc:
            print(f"external recovery point failed: {exc}", flush=True)
            sleep(retry_seconds)


def check_recovery_point_health(
    directory: Path,
    *,
    maximum_age_seconds: int,
    now: float | None = None,
) -> VerifiedRecoveryPoint:
    """Require a fully verified latest point within the configured age."""
    if maximum_age_seconds < 1:
        raise ValueError("maximum_age_seconds must be positive")
    point = verify_recovery_point_health(directory)
    completed = datetime.fromisoformat(point.created_at.replace("Z", "+00:00"))
    source_completed = datetime.fromisoformat(
        point.source_backup_completed_at.replace("Z", "+00:00")
    )
    current = time.time() if now is None else now
    age_seconds = current - completed.timestamp()
    source_age_seconds = current - source_completed.timestamp()
    if age_seconds < -300:
        raise RecoveryPointError("Recovery point timestamp is unexpectedly in the future.")
    if age_seconds > maximum_age_seconds:
        raise RecoveryPointError(
            f"Recovery point is stale ({int(age_seconds)} seconds old)."
        )
    if source_age_seconds < -300:
        raise RecoveryPointError(
            "Recovery point source backup timestamp is unexpectedly in the future."
        )
    if source_age_seconds > maximum_age_seconds:
        raise RecoveryPointError(
            f"Recovery point source backup is stale ({int(source_age_seconds)} seconds old)."
        )
    return point


def verify_recovery_point(directory: Path) -> VerifiedRecoveryPoint:
    """Verify a self-contained point without trusting its health pointer."""
    entries = _point_entries(directory)

    raw_manifest = _read_regular_file(
        entries[RECOVERY_POINT_MANIFEST],
        maximum_bytes=_MAX_JSON_BYTES,
        label="Recovery point manifest",
    )
    payload = _decode_point_manifest(raw_manifest)
    raw_deployment = _read_regular_file(
        entries[RECOVERY_POINT_DEPLOYMENT],
        maximum_bytes=_MAX_JSON_BYTES,
        label="Embedded deployment manifest",
    )
    deployment = _decode_deployment_manifest(raw_deployment)
    deployment_sha256 = hashlib.sha256(raw_deployment).hexdigest()
    release = payload["release"]
    if (
        deployment["release"]["tag"] != release["tag"]
        or deployment["release"]["source_commit"] != release["source_commit"]
        or not hmac.compare_digest(deployment_sha256, release["manifest_sha256"])
        or not hmac.compare_digest(
            deployment_sha256,
            payload["deployment_manifest"]["sha256"],
        )
    ):
        raise RecoveryPointError("Recovery point release binding is invalid.")

    database = entries[RECOVERY_POINT_DATABASE]
    database_metadata = database.lstat()
    expected_database = payload["database"]
    if database_metadata.st_size != expected_database["size_bytes"]:
        raise RecoveryPointError("Recovery point database size does not match.")
    database_sha256 = sha256_file(database)
    if not hmac.compare_digest(database_sha256, expected_database["sha256"]):
        raise RecoveryPointError("Recovery point database digest does not match.")
    try:
        revision = verify_backup(database)
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise RecoveryPointError("Recovery point database is invalid.") from exc
    if revision != expected_database["schema_revision"]:
        raise RecoveryPointError("Recovery point database revision does not match.")
    if not hmac.compare_digest(sha256_file(database), database_sha256):
        raise RecoveryPointError("Recovery point database changed during verification.")
    return VerifiedRecoveryPoint(
        directory=directory,
        database=database,
        deployment_manifest=entries[RECOVERY_POINT_DEPLOYMENT],
        tag=release["tag"],
        source_commit=release["source_commit"],
        manifest_sha256=release["manifest_sha256"],
        database_sha256=database_sha256,
        database_size_bytes=database_metadata.st_size,
        schema_revision=revision,
        created_at=payload["created_at"],
        source_backup_completed_at=expected_database[
            "source_backup_completed_at"
        ],
    )


def _point_entries(directory: Path) -> dict[str, Path]:
    """Validate a point's private shape without hashing its potentially large DB."""
    validate_recovery_point_directory(directory)
    try:
        entries = {entry.name: entry for entry in directory.iterdir()}
    except OSError as exc:
        raise RecoveryPointError("Recovery point cannot be inspected.") from exc
    expected = {
        RECOVERY_POINT_MANIFEST,
        RECOVERY_POINT_DATABASE,
        RECOVERY_POINT_DEPLOYMENT,
    }
    if set(entries) != expected:
        raise RecoveryPointError("Recovery point entries are invalid.")
    _regular_file_metadata(
        entries[RECOVERY_POINT_MANIFEST],
        maximum_bytes=_MAX_JSON_BYTES,
        label="Recovery point manifest",
    )
    _regular_file_metadata(
        entries[RECOVERY_POINT_DEPLOYMENT],
        maximum_bytes=_MAX_JSON_BYTES,
        label="Embedded deployment manifest",
    )
    _regular_file_metadata(
        entries[RECOVERY_POINT_DATABASE],
        maximum_bytes=_MAX_DATABASE_BYTES,
        label="Recovery point database",
    )
    return entries


def verify_recovery_point_health(directory: Path) -> VerifiedRecoveryPoint:
    """Verify the atomic latest pointer and the complete referenced point."""
    validate_recovery_point_directory(directory)
    raw = _read_regular_file(
        directory / RECOVERY_POINT_HEALTH,
        maximum_bytes=_MAX_JSON_BYTES,
        label="Recovery point health",
    )
    try:
        health = _validate_health(json.loads(raw.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryPointError("Recovery point health JSON is invalid.") from exc
    point = verify_recovery_point(directory / health["recovery_point"])
    release = health["release"]
    if (
        point.tag != release["tag"]
        or point.source_commit != release["source_commit"]
        or not hmac.compare_digest(point.manifest_sha256, release["manifest_sha256"])
        or not hmac.compare_digest(point.database_sha256, health["database_sha256"])
        or not hmac.compare_digest(
            sha256_file(point.directory / RECOVERY_POINT_MANIFEST),
            health["recovery_manifest_sha256"],
        )
        or point.created_at != health["created_at"]
    ):
        raise RecoveryPointError("Recovery point health binding is invalid.")
    return point


def verify_recovery_point_release(
    directory: Path,
    *,
    manifest_path: Path,
    checksum_path: Path,
    attestation_path: Path,
    expected_tag: str,
    attestation_verifier: AttestationVerifier | None = None,
) -> VerifiedRecoveryPoint:
    """Bind a point to the original signed public release assets."""
    point = verify_recovery_point(directory)
    bundle = verify_release_bundle(
        manifest_path=manifest_path,
        checksum_path=checksum_path,
        attestation_path=attestation_path,
        expected_tag=expected_tag,
        attestation_verifier=attestation_verifier,
    )
    embedded = _read_regular_file(
        point.deployment_manifest,
        maximum_bytes=_MAX_JSON_BYTES,
        label="Embedded deployment manifest",
    )
    if (
        point.tag != bundle.tag
        or point.source_commit != bundle.source_commit
        or not hmac.compare_digest(
            point.manifest_sha256,
            hashlib.sha256(bundle.manifest_bytes).hexdigest(),
        )
        or not hmac.compare_digest(embedded, bundle.manifest_bytes)
    ):
        raise RecoveryPointError("Signed release does not match the recovery point.")
    return point


def restore_recovery_point(
    directory: Path,
    destination: Path,
    *,
    manifest_path: Path,
    checksum_path: Path,
    attestation_path: Path,
    expected_tag: str,
    attestation_verifier: AttestationVerifier | None = None,
) -> VerifiedRecoveryPoint:
    """Verify signed release provenance and restore without overwriting data."""
    if not destination.is_absolute():
        raise RecoveryPointError("Recovery destination must be an absolute path.")
    validate_recovery_point_directory(destination.parent)
    point = verify_recovery_point_release(
        directory,
        manifest_path=manifest_path,
        checksum_path=checksum_path,
        attestation_path=attestation_path,
        expected_tag=expected_tag,
        attestation_verifier=attestation_verifier,
    )
    try:
        restored_revision = restore_database_without_overwrite(
            point.database,
            destination,
        )
    except (OSError, RuntimeError, sqlite3.Error) as exc:
        raise RecoveryPointError("Recovery point restore failed.") from exc
    if restored_revision != point.schema_revision:
        destination.unlink(missing_ok=True)
        raise RecoveryPointError("Restored recovery point revision does not match.")
    if not hmac.compare_digest(sha256_file(point.database), point.database_sha256):
        destination.unlink(missing_ok=True)
        raise RecoveryPointError("Recovery point changed during restore.")
    return point


def _create_manifest(
    *,
    created_at: str,
    tag: str,
    source_commit: str,
    manifest_sha256: str,
    database_size_bytes: int,
    database_sha256: str,
    schema_revision: str,
    source_backup_file: str,
    source_backup_completed_at: str,
    source_backup_sha256: str,
) -> dict[str, Any]:
    payload = {
        "schema": "gram_scope_recovery_point_v1",
        "created_at": created_at,
        "release": {
            "tag": tag,
            "source_commit": source_commit,
            "manifest_sha256": manifest_sha256,
        },
        "deployment_manifest": {
            "file": RECOVERY_POINT_DEPLOYMENT,
            "sha256": manifest_sha256,
        },
        "database": {
            "file": RECOVERY_POINT_DATABASE,
            "size_bytes": database_size_bytes,
            "sha256": database_sha256,
            "schema_revision": schema_revision,
            "source_backup_file": source_backup_file,
            "source_backup_completed_at": source_backup_completed_at,
            "source_backup_sha256": source_backup_sha256,
        },
        "verification": {
            "database_integrity": "ok",
            "restore_check": "ok",
        },
    }
    _validate_point_manifest(payload)
    return payload


def _decode_point_manifest(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise RecoveryPointError("Recovery point manifest JSON is invalid.") from exc
    return _validate_point_manifest(payload)


def _validate_point_manifest(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _POINT_KEYS:
        raise RecoveryPointError("Recovery point manifest contract is invalid.")
    release = payload.get("release")
    deployment = payload.get("deployment_manifest")
    database = payload.get("database")
    verification = payload.get("verification")
    if (
        payload.get("schema") != "gram_scope_recovery_point_v1"
        or not _is_utc_timestamp(payload.get("created_at"))
        or not isinstance(release, dict)
        or set(release) != _RELEASE_KEYS
        or not isinstance(deployment, dict)
        or set(deployment) != _DEPLOYMENT_KEYS
        or not isinstance(database, dict)
        or set(database) != _DATABASE_KEYS
        or not isinstance(verification, dict)
        or set(verification) != _VERIFICATION_KEYS
    ):
        raise RecoveryPointError("Recovery point manifest fields are invalid.")
    size = database.get("size_bytes")
    if (
        not isinstance(release.get("tag"), str)
        or _TAG.fullmatch(release["tag"]) is None
        or not isinstance(release.get("source_commit"), str)
        or _COMMIT.fullmatch(release["source_commit"]) is None
        or not _is_sha256(release.get("manifest_sha256"))
        or deployment.get("file") != RECOVERY_POINT_DEPLOYMENT
        or not _is_sha256(deployment.get("sha256"))
        or database.get("file") != RECOVERY_POINT_DATABASE
        or not isinstance(size, int)
        or isinstance(size, bool)
        or size < 1
        or size > _MAX_DATABASE_BYTES
        or not _is_sha256(database.get("sha256"))
        or not isinstance(database.get("schema_revision"), str)
        or _SCHEMA_REVISION.fullmatch(database["schema_revision"]) is None
        or not isinstance(database.get("source_backup_file"), str)
        or _BACKUP_NAME.fullmatch(database["source_backup_file"]) is None
        or not _is_utc_timestamp(database.get("source_backup_completed_at"))
        or not _is_sha256(database.get("source_backup_sha256"))
        or verification
        != {"database_integrity": "ok", "restore_check": "ok"}
    ):
        raise RecoveryPointError("Recovery point manifest fields are invalid.")
    return payload


def _decode_deployment_manifest(raw: bytes) -> dict[str, Any]:
    try:
        return validate_release_manifest(json.loads(raw.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise RecoveryPointError("Deployment manifest contract is invalid.") from exc


def _validate_health(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) != _HEALTH_KEYS:
        raise RecoveryPointError("Recovery point health contract is invalid.")
    release = payload.get("release")
    if (
        payload.get("schema") != "gram_scope_recovery_point_health_v1"
        or payload.get("status") != "verified"
        or not _is_utc_timestamp(payload.get("created_at"))
        or not isinstance(payload.get("recovery_point"), str)
        or _POINT_NAME.fullmatch(payload["recovery_point"]) is None
        or not _is_sha256(payload.get("recovery_manifest_sha256"))
        or not _is_sha256(payload.get("database_sha256"))
        or not isinstance(release, dict)
        or set(release) != _RELEASE_KEYS
        or not isinstance(release.get("tag"), str)
        or _TAG.fullmatch(release["tag"]) is None
        or not isinstance(release.get("source_commit"), str)
        or _COMMIT.fullmatch(release["source_commit"]) is None
        or not _is_sha256(release.get("manifest_sha256"))
    ):
        raise RecoveryPointError("Recovery point health fields are invalid.")
    return payload


def _validate_root_entries(directory: Path) -> None:
    try:
        entries = list(directory.iterdir())
    except OSError as exc:
        raise RecoveryPointError("Recovery point directory cannot be inspected.") from exc
    has_health = False
    for entry in entries:
        if entry.name == RECOVERY_POINT_LOCK:
            _validate_lock_file(entry)
            continue
        if entry.name == RECOVERY_POINT_HEALTH:
            has_health = True
            continue
        if _POINT_NAME.fullmatch(entry.name) is None:
            raise RecoveryPointError("Recovery point directory has an unknown entry.")
        _point_entries(entry)
    if has_health:
        verify_recovery_point_health(directory)


@contextmanager
def _locked_recovery_point_directory(directory: Path) -> Iterator[None]:
    lock_path = directory / RECOVERY_POINT_LOCK
    descriptor: int | None = None
    try:
        descriptor = os.open(
            lock_path,
            os.O_RDWR
            | os.O_CREAT
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        _validate_lock_metadata(os.fstat(descriptor))
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise RecoveryPointError(
                "Another recovery point operation is in progress."
            ) from exc
        yield
    except RecoveryPointError:
        raise
    except OSError as exc:
        raise RecoveryPointError("Recovery point lock is unavailable.") from exc
    finally:
        if descriptor is not None:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
            finally:
                os.close(descriptor)


def _validate_lock_file(path: Path) -> None:
    try:
        _validate_lock_metadata(path.lstat())
    except OSError as exc:
        raise RecoveryPointError("Recovery point lock is unavailable.") from exc


def _validate_lock_metadata(metadata: os.stat_result) -> None:
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or metadata.st_mode & 0o077
        or metadata.st_size != 0
    ):
        raise RecoveryPointError("Recovery point lock is unsafe.")


def _apply_retention(
    directory: Path,
    retention: int,
    *,
    protected_name: str,
) -> None:
    points = sorted(
        (
            entry
            for entry in directory.iterdir()
            if _POINT_NAME.fullmatch(entry.name) is not None
        ),
        key=lambda entry: entry.lstat().st_mtime_ns,
        reverse=True,
    )
    protected = next(
        (point for point in points if point.name == protected_name),
        None,
    )
    if protected is None:
        raise RecoveryPointError("Current recovery point is unavailable.")
    remaining = [point for point in points if point.name != protected_name]
    retained_names = {protected_name}
    retained_names.update(point.name for point in remaining[: retention - 1])
    for expired in points:
        if expired.name in retained_names:
            continue
        verify_recovery_point(expired)
        for name in (
            RECOVERY_POINT_MANIFEST,
            RECOVERY_POINT_DATABASE,
            RECOVERY_POINT_DEPLOYMENT,
        ):
            (expired / name).unlink()
        expired.rmdir()
    _fsync_directory(directory)


def _preflight_retention(directory: Path, retention: int) -> None:
    """Verify every point that the next publication would need to remove."""
    points = sorted(
        (
            entry
            for entry in directory.iterdir()
            if _POINT_NAME.fullmatch(entry.name) is not None
        ),
        key=lambda entry: entry.lstat().st_mtime_ns,
        reverse=True,
    )
    for expiring in points[max(0, retention - 1) :]:
        verify_recovery_point(expiring)


def _remove_staging_directory(directory: Path) -> None:
    try:
        if not directory.exists():
            return
        for name in (
            RECOVERY_POINT_MANIFEST,
            RECOVERY_POINT_DATABASE,
            RECOVERY_POINT_DEPLOYMENT,
        ):
            (directory / name).unlink(missing_ok=True)
        directory.rmdir()
    except OSError:
        pass


def _read_regular_file(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
    require_private: bool = True,
) -> bytes:
    metadata = _regular_file_metadata(
        path,
        maximum_bytes=maximum_bytes,
        label=label,
        require_private=require_private,
    )
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise RecoveryPointError(f"{label} is unavailable.") from exc
    try:
        opened = os.fstat(descriptor)
        if (
            opened.st_dev != metadata.st_dev
            or opened.st_ino != metadata.st_ino
            or opened.st_size != metadata.st_size
        ):
            raise RecoveryPointError(f"{label} changed while it was opened.")
        raw = bytearray()
        while len(raw) <= maximum_bytes:
            chunk = os.read(descriptor, maximum_bytes + 1 - len(raw))
            if not chunk:
                break
            raw.extend(chunk)
        if len(raw) > maximum_bytes:
            raise RecoveryPointError(f"{label} exceeds the size limit.")
        return bytes(raw)
    finally:
        os.close(descriptor)


def _regular_file_metadata(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
    require_private: bool = True,
) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RecoveryPointError(f"{label} is unavailable.") from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_size < 1
        or metadata.st_size > maximum_bytes
        or metadata.st_nlink != 1
    ):
        raise RecoveryPointError(f"{label} must be a bounded regular file.")
    if require_private and (
        metadata.st_uid != os.geteuid() or metadata.st_mode & 0o077
    ):
        raise RecoveryPointError(f"{label} must be private and owned by the operator.")
    return metadata


def _write_private_file(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _write_private_json(path: Path, payload: dict[str, Any]) -> None:
    _write_private_file(
        path,
        (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "ascii"
        ),
    )


def _write_atomic_json(path: Path, payload: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        _write_private_json(temporary, payload)
        temporary.replace(path)
        _fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256.fullmatch(value) is not None


def _is_utc_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() == timedelta(0)


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Create, verify, or restore a release-bound recovery point."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--heartbeat", type=Path, required=True)
    create.add_argument("--deployment-manifest", type=Path, required=True)
    create.add_argument("--destination-directory", type=Path, required=True)
    create.add_argument("--retention", type=int, default=14)
    create.add_argument(
        "--maximum-source-age-seconds",
        type=int,
        default=int(
            os.environ.get("RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS", "172800")
        ),
    )

    loop = subparsers.add_parser("loop")
    loop.add_argument("--heartbeat", type=Path, required=True)
    loop.add_argument("--destination-directory", type=Path, required=True)
    loop.add_argument("--retention", type=int, default=14)
    loop.add_argument(
        "--interval-seconds",
        type=int,
        default=int(os.environ.get("RECOVERY_POINT_INTERVAL_SECONDS", "86400")),
    )
    loop.add_argument(
        "--retry-seconds",
        type=int,
        default=int(os.environ.get("RECOVERY_POINT_RETRY_SECONDS", "300")),
    )
    loop.add_argument(
        "--maximum-age-seconds",
        type=int,
        default=int(
            os.environ.get("RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS", "172800")
        ),
    )

    healthcheck = subparsers.add_parser("healthcheck")
    healthcheck.add_argument("--destination-directory", type=Path, required=True)
    healthcheck.add_argument(
        "--maximum-age-seconds",
        type=int,
        default=int(
            os.environ.get("RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS", "172800")
        ),
    )

    for command in ("verify", "restore"):
        subparser = subparsers.add_parser(command)
        subparser.add_argument("--point", type=Path, required=True)
        subparser.add_argument("--manifest", type=Path, required=True)
        subparser.add_argument("--checksum", type=Path, required=True)
        subparser.add_argument("--attestation-bundle", type=Path, required=True)
        subparser.add_argument("--tag", required=True)
        if command == "restore":
            subparser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "loop":
            run_recovery_point_exporter(
                heartbeat=args.heartbeat,
                destination_directory=args.destination_directory,
                retention=args.retention,
                interval_seconds=args.interval_seconds,
                retry_seconds=args.retry_seconds,
                maximum_age_seconds=args.maximum_age_seconds,
            )
            return
        if args.command == "healthcheck":
            point = check_recovery_point_health(
                args.destination_directory,
                maximum_age_seconds=args.maximum_age_seconds,
            )
            print(
                "external recovery point healthy "
                f"tag={point.tag} schema={point.schema_revision}",
                flush=True,
            )
            return
        if args.command == "create":
            point = create_recovery_point(
                heartbeat=args.heartbeat,
                deployment_manifest=args.deployment_manifest,
                destination_directory=args.destination_directory,
                retention=args.retention,
                maximum_source_age_seconds=args.maximum_source_age_seconds,
            )
        elif args.command == "restore":
            point = restore_recovery_point(
                args.point,
                args.destination,
                manifest_path=args.manifest,
                checksum_path=args.checksum,
                attestation_path=args.attestation_bundle,
                expected_tag=args.tag,
            )
        else:
            point = verify_recovery_point_release(
                args.point,
                manifest_path=args.manifest,
                checksum_path=args.checksum,
                attestation_path=args.attestation_bundle,
                expected_tag=args.tag,
            )
    except (
        OSError,
        ValueError,
        sqlite3.Error,
        RecoveryPointError,
        ReleaseBundleVerificationError,
    ) as exc:
        print(f"recovery point error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    print(
        f"recovery point {args.command} passed "
        f"tag={point.tag} schema={point.schema_revision} "
        f"database_sha256={point.database_sha256}",
        flush=True,
    )


if __name__ == "__main__":
    main()
