"""External release-bound recovery point tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3

import pytest

from ops.backup_sqlite import BACKUP_HEALTH_RECORD, create_backup
from ops.create_release_manifest import create_release_manifest, write_release_manifest
from ops.recovery_point import (
    RECOVERY_POINT_DATABASE,
    RECOVERY_POINT_DEPLOYMENT,
    RECOVERY_POINT_HEALTH,
    RECOVERY_POINT_LOCK,
    RECOVERY_POINT_MANIFEST,
    RecoveryPointError,
    check_recovery_point_health,
    create_recovery_point,
    restore_recovery_point,
    run_recovery_point_exporter,
    verify_recovery_point,
    verify_recovery_point_health,
    verify_recovery_point_release,
)


TAG = "v0.70.0"
SOURCE_COMMIT = "1" * 40


def _database(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE alembic_version (version_num TEXT NOT NULL)")
        connection.execute("INSERT INTO alembic_version VALUES ('20260710_0014')")
        connection.execute("CREATE TABLE evidence (value TEXT NOT NULL)")
        connection.execute("INSERT INTO evidence VALUES ('external-recovery')")


def _release_assets(directory: Path, *, tag: str = TAG) -> tuple[Path, Path, Path]:
    prefix = f"gram-scope-{tag}-deployment"
    manifest = directory / f"{prefix}.json"
    checksum = directory / f"{prefix}.json.sha256"
    attestation = directory / f"{prefix}.intoto.jsonl"
    write_release_manifest(
        create_release_manifest(
            tag=tag,
            source_commit=SOURCE_COMMIT,
            backend_digest="sha256:" + "a" * 64,
            frontend_digest="sha256:" + "b" * 64,
        ),
        manifest,
    )
    checksum.write_text(
        f"{hashlib.sha256(manifest.read_bytes()).hexdigest()}  {manifest.name}\n",
        encoding="ascii",
    )
    attestation.write_text('{"fixture":true}\n', encoding="utf-8")
    return manifest, checksum, attestation


def _source(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source.sqlite3"
    backups = tmp_path / "backups"
    _database(source)
    create_backup(source, backups, retention=3)
    return backups / BACKUP_HEALTH_RECORD, source


def _destination(tmp_path: Path) -> Path:
    destination = tmp_path / "external-recovery"
    destination.mkdir(mode=0o700)
    destination.chmod(0o700)
    return destination


def test_recovery_point_is_atomic_private_and_release_bound(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    destination = _destination(tmp_path)
    completed = datetime(2026, 8, 9, 12, 30, 15, 123456, tzinfo=timezone.utc)

    point = create_recovery_point(
        heartbeat=heartbeat,
        deployment_manifest=manifest,
        destination_directory=destination,
        retention=3,
        created_at=completed,
    )

    assert point.tag == TAG
    assert point.source_commit == SOURCE_COMMIT
    assert point.schema_revision == "20260710_0014"
    assert point.created_at == "2026-08-09T12:30:15.123456Z"
    assert point.directory.parent == destination
    assert point.directory.name.startswith(
        "recovery-point-v0.70.0-20260809T123015123456Z-"
    )
    assert {entry.name for entry in point.directory.iterdir()} == {
        RECOVERY_POINT_MANIFEST,
        RECOVERY_POINT_DATABASE,
        RECOVERY_POINT_DEPLOYMENT,
    }
    assert point.directory.stat().st_mode & 0o777 == 0o700
    assert all(entry.stat().st_mode & 0o777 == 0o600 for entry in point.directory.iterdir())
    assert not list(destination.glob(".*.tmp"))
    assert verify_recovery_point(point.directory) == point
    with sqlite3.connect(f"file:{point.database}?mode=ro", uri=True) as connection:
        assert connection.execute("SELECT value FROM evidence").fetchone() == (
            "external-recovery",
        )

    health = json.loads((destination / RECOVERY_POINT_HEALTH).read_text())
    assert health["schema"] == "gram_scope_recovery_point_health_v1"
    assert health["status"] == "verified"
    assert health["recovery_point"] == point.directory.name
    assert health["database_sha256"] == point.database_sha256
    assert health["release"]["manifest_sha256"] == point.manifest_sha256
    assert verify_recovery_point_health(destination) == point


def test_signed_release_verification_and_restore_never_overwrite(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, checksum, attestation = _release_assets(tmp_path)
    point = create_recovery_point(
        heartbeat=heartbeat,
        deployment_manifest=manifest,
        destination_directory=_destination(tmp_path),
        retention=3,
    )
    attestations: list[Path] = []

    verified = verify_recovery_point_release(
        point.directory,
        manifest_path=manifest,
        checksum_path=checksum,
        attestation_path=attestation,
        expected_tag=TAG,
        attestation_verifier=lambda snapshot, *_args: attestations.append(snapshot),
    )
    assert verified == point
    assert attestations

    restored = tmp_path / "restored.sqlite3"
    restored_point = restore_recovery_point(
        point.directory,
        restored,
        manifest_path=manifest,
        checksum_path=checksum,
        attestation_path=attestation,
        expected_tag=TAG,
        attestation_verifier=lambda *_args: None,
    )
    assert restored_point == point
    assert restored.stat().st_mode & 0o777 == 0o600
    original = restored.read_bytes()
    with pytest.raises(RecoveryPointError, match="restore failed"):
        restore_recovery_point(
            point.directory,
            restored,
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            attestation_verifier=lambda *_args: None,
        )
    assert restored.read_bytes() == original

    unsafe_parent = tmp_path / "unsafe-restore"
    unsafe_parent.mkdir(mode=0o755)
    unsafe_parent.chmod(0o755)
    with pytest.raises(RecoveryPointError, match="private"):
        restore_recovery_point(
            point.directory,
            unsafe_parent / "database.sqlite3",
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            attestation_verifier=lambda *_args: None,
        )


def test_recovery_point_rejects_a_different_valid_signed_release(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    point = create_recovery_point(
        heartbeat=heartbeat,
        deployment_manifest=manifest,
        destination_directory=_destination(tmp_path),
        retention=3,
    )
    other_directory = tmp_path / "other-release"
    other_directory.mkdir()
    other_manifest, other_checksum, other_attestation = _release_assets(
        other_directory,
        tag="v0.70.1",
    )

    with pytest.raises(RecoveryPointError, match="does not match"):
        verify_recovery_point_release(
            point.directory,
            manifest_path=other_manifest,
            checksum_path=other_checksum,
            attestation_path=other_attestation,
            expected_tag="v0.70.1",
            attestation_verifier=lambda *_args: None,
        )


def test_recovery_point_rejects_tampering_and_release_mismatch(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, checksum, attestation = _release_assets(tmp_path)
    point = create_recovery_point(
        heartbeat=heartbeat,
        deployment_manifest=manifest,
        destination_directory=_destination(tmp_path),
        retention=3,
    )
    payload = bytearray(point.database.read_bytes())
    payload[-1] ^= 1
    point.database.write_bytes(payload)
    point.database.chmod(0o600)
    with pytest.raises(RecoveryPointError, match="digest"):
        verify_recovery_point(point.directory)

    point.database.unlink()
    point.database.write_bytes(b"not a database")
    point.database.chmod(0o600)
    with pytest.raises(RecoveryPointError):
        verify_recovery_point_release(
            point.directory,
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            attestation_verifier=lambda *_args: None,
        )


def test_recovery_point_health_rejects_a_changed_latest_binding(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    destination = _destination(tmp_path)
    create_recovery_point(
        heartbeat=heartbeat,
        deployment_manifest=manifest,
        destination_directory=destination,
        retention=3,
    )
    health_path = destination / RECOVERY_POINT_HEALTH
    health = json.loads(health_path.read_text())
    health["database_sha256"] = "f" * 64
    health_path.write_text(json.dumps(health), encoding="utf-8")
    health_path.chmod(0o600)

    with pytest.raises(RecoveryPointError, match="health binding"):
        verify_recovery_point_health(destination)
    with pytest.raises(RecoveryPointError, match="health binding"):
        create_recovery_point(
            heartbeat=heartbeat,
            deployment_manifest=manifest,
            destination_directory=destination,
            retention=3,
        )


def test_periodic_exporter_reuses_latest_release_and_health_is_age_bounded(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    destination = _destination(tmp_path)
    first = create_recovery_point(
        heartbeat=heartbeat,
        deployment_manifest=manifest,
        destination_directory=destination,
        retention=3,
    )
    point_timestamp = datetime.fromisoformat(
        first.created_at.replace("Z", "+00:00")
    ).timestamp()
    source_timestamp = datetime.fromisoformat(
        first.source_backup_completed_at.replace("Z", "+00:00")
    ).timestamp()
    latest_timestamp = max(point_timestamp, source_timestamp)
    assert check_recovery_point_health(
        destination,
        maximum_age_seconds=900,
        now=latest_timestamp + 800,
    ) == first
    with pytest.raises(RecoveryPointError, match="stale"):
        check_recovery_point_health(
            destination,
            maximum_age_seconds=900,
            now=latest_timestamp + 901,
        )

    run_recovery_point_exporter(
        heartbeat=heartbeat,
        destination_directory=destination,
        retention=3,
        interval_seconds=86_400,
        retry_seconds=300,
        sleep=lambda _seconds: pytest.fail("one iteration must not sleep"),
        iterations=1,
        wait_for_due=False,
    )
    latest = verify_recovery_point_health(destination)
    assert latest.tag == first.tag
    assert latest.source_commit == first.source_commit
    assert latest.directory != first.directory


def test_recovery_point_rejects_unsafe_root_and_cleans_failed_staging(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    destination = _destination(tmp_path)
    destination.chmod(0o755)
    with pytest.raises(RecoveryPointError, match="private"):
        create_recovery_point(
            heartbeat=heartbeat,
            deployment_manifest=manifest,
            destination_directory=destination,
            retention=3,
        )

    destination.chmod(0o700)
    (destination / "unexpected").write_text("do not delete", encoding="utf-8")
    with pytest.raises(RecoveryPointError, match="unknown entry"):
        create_recovery_point(
            heartbeat=heartbeat,
            deployment_manifest=manifest,
            destination_directory=destination,
            retention=3,
        )
    assert (destination / "unexpected").read_text() == "do not delete"

    (destination / "unexpected").unlink()
    heartbeat.write_text("{}", encoding="utf-8")
    with pytest.raises(RecoveryPointError):
        create_recovery_point(
            heartbeat=heartbeat,
            deployment_manifest=manifest,
            destination_directory=destination,
            retention=3,
        )
    assert {entry.name for entry in destination.iterdir()} == {
        RECOVERY_POINT_LOCK
    }


def test_recovery_point_lock_serializes_deployment_and_periodic_exports(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    destination = _destination(tmp_path)
    lock_path = destination / RECOVERY_POINT_LOCK
    lock_path.touch(mode=0o600)
    lock_path.chmod(0o600)

    with lock_path.open("r+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(RecoveryPointError, match="in progress"):
            create_recovery_point(
                heartbeat=heartbeat,
                deployment_manifest=manifest,
                destination_directory=destination,
                retention=3,
            )
        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    assert {entry.name for entry in destination.iterdir()} == {
        RECOVERY_POINT_LOCK
    }


def test_stale_source_backup_is_rejected_before_publication(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    destination = _destination(tmp_path)
    record = json.loads(heartbeat.read_text())
    record["completed_at"] = "2020-01-01T00:00:00Z"
    heartbeat.write_text(json.dumps(record), encoding="utf-8")

    with pytest.raises(RecoveryPointError, match="stale"):
        create_recovery_point(
            heartbeat=heartbeat,
            deployment_manifest=manifest,
            destination_directory=destination,
            retention=3,
            maximum_source_age_seconds=3_600,
        )

    assert {entry.name for entry in destination.iterdir()} == {
        RECOVERY_POINT_LOCK
    }


def test_recovery_point_retention_removes_only_verified_old_points(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    destination = _destination(tmp_path)
    base = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
    points = []
    for offset in range(3):
        points.append(
            create_recovery_point(
                heartbeat=heartbeat,
                deployment_manifest=manifest,
                destination_directory=destination,
                retention=2,
                created_at=base + timedelta(seconds=offset),
            )
        )
        if offset == 0:
            future = (base + timedelta(days=365)).timestamp()
            os.utime(points[0].directory, (future, future))

    existing = {
        entry.name
        for entry in destination.iterdir()
        if entry.name.startswith("recovery-point-")
    }
    assert points[1].directory.name not in existing
    assert existing == {points[0].directory.name, points[2].directory.name}
    health = json.loads((destination / RECOVERY_POINT_HEALTH).read_text())
    assert health["recovery_point"] == points[2].directory.name


def test_corrupt_expiring_point_blocks_before_another_point_is_published(tmp_path):
    heartbeat, _source_database = _source(tmp_path)
    manifest, _checksum, _attestation = _release_assets(tmp_path)
    destination = _destination(tmp_path)
    points = [
        create_recovery_point(
            heartbeat=heartbeat,
            deployment_manifest=manifest,
            destination_directory=destination,
            retention=2,
        )
        for _index in range(2)
    ]
    points[0].database.write_bytes(b"corrupt")
    points[0].database.chmod(0o600)
    before = {
        entry.name
        for entry in destination.iterdir()
        if entry.name.startswith("recovery-point-")
    }

    with pytest.raises(RecoveryPointError):
        create_recovery_point(
            heartbeat=heartbeat,
            deployment_manifest=manifest,
            destination_directory=destination,
            retention=2,
        )

    after = {
        entry.name
        for entry in destination.iterdir()
        if entry.name.startswith("recovery-point-")
    }
    assert after == before
    assert verify_recovery_point_health(destination) == points[1]
