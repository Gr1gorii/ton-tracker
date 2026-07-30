"""Production readiness and Prometheus metric tests."""

from datetime import datetime, timezone
import hashlib
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

import database
from database import get_session
from main import app
from services.database_migrations import run_database_migrations
from services.monitoring import (
    BackupHealthMetrics,
    RecoveryHealthMetrics,
    observe_http_request,
    read_backup_health_metrics,
    read_recovery_health_metrics,
    render_prometheus_metrics,
)


def test_prometheus_renderer_uses_bounded_route_labels():
    observe_http_request("GET", "/api/health", 200, 0.125)
    metrics = render_prometheus_metrics(version="0.2.1", database_ready=True)
    assert 'ton_tracker_build_info{version="0.2.1"} 1' in metrics
    assert "ton_tracker_database_ready 1" in metrics
    assert "ton_tracker_backup_monitoring_configured 0" in metrics
    assert "ton_tracker_backup_ready 0" in metrics
    assert "ton_tracker_recovery_monitoring_configured 0" in metrics
    assert "ton_tracker_recovery_ready 0" in metrics
    assert 'route="/api/health",status="200"' in metrics
    assert "ton_tracker_http_request_duration_seconds_sum" in metrics


def test_backup_heartbeat_metrics_are_bounded_and_fail_closed(tmp_path):
    backup = tmp_path / "ton-check-20260730T120000Z.sqlite3"
    backup.write_bytes(b"verified-backup")
    health = tmp_path / ".backup-health.json"
    completed = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    record = {
        "schema_version": 1,
        "status": "verified",
        "backup_file": backup.name,
        "completed_at": "2026-07-30T12:00:00Z",
        "size_bytes": backup.stat().st_size,
        "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(),
        "schema_revision": "20260710_0013",
        "integrity_check": "ok",
    }
    health.write_text(json.dumps(record), encoding="utf-8")

    status = read_backup_health_metrics(
        str(health), maximum_age_seconds=900, now=completed + 899
    )
    assert status == BackupHealthMetrics(
        configured=True,
        ready=True,
        age_seconds=899,
        last_success_timestamp_seconds=completed,
        size_bytes=len(b"verified-backup"),
    )
    metrics = render_prometheus_metrics(
        version="0.2.1", database_ready=True, backup=status
    )
    assert "ton_tracker_backup_monitoring_configured 1" in metrics
    assert "ton_tracker_backup_ready 1" in metrics
    assert "ton_tracker_backup_age_seconds 899.000" in metrics
    assert f"ton_tracker_backup_size_bytes {len(b'verified-backup')}" in metrics
    assert backup.name not in metrics

    stale = read_backup_health_metrics(
        str(health), maximum_age_seconds=900, now=completed + 901
    )
    assert stale.configured is True
    assert stale.ready is False

    backup.write_bytes(b"tampered-backup")
    assert read_backup_health_metrics(
        str(health), maximum_age_seconds=900, now=completed + 1
    ).ready is False

    record["size_bytes"] += 1
    health.write_text(json.dumps(record), encoding="utf-8")
    assert read_backup_health_metrics(
        str(health), maximum_age_seconds=900, now=completed + 1
    ).ready is False


def test_backup_heartbeat_rejects_unbounded_or_malformed_records(tmp_path):
    health = tmp_path / ".backup-health.json"
    health.write_text("{" + ("x" * 20_000), encoding="utf-8")
    status = read_backup_health_metrics(
        str(health), maximum_age_seconds=900, now=0
    )
    assert status == BackupHealthMetrics(configured=True, ready=False)

    health.unlink()
    target = tmp_path / "heartbeat-target.json"
    target.write_text("{}", encoding="utf-8")
    health.symlink_to(target)
    assert read_backup_health_metrics(
        str(health), maximum_age_seconds=900, now=0
    ).ready is False


def test_recovery_heartbeat_metrics_are_bounded_and_fail_closed(tmp_path):
    health = tmp_path / ".recovery-health.json"
    completed = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc).timestamp()
    record = {
        "schema_version": 1,
        "status": "passed",
        "completed_at": "2026-07-30T12:00:00Z",
        "backup_file": "ton-check-20260730T115900Z.sqlite3",
        "backup_size_bytes": 12345,
        "backup_sha256": "b" * 64,
        "schema_revision": "20260710_0014",
        "integrity_check": "ok",
        "restore_check": "ok",
    }
    health.write_text(json.dumps(record), encoding="utf-8")

    status = read_recovery_health_metrics(
        str(health), maximum_age_seconds=900, now=completed + 899
    )
    assert status == RecoveryHealthMetrics(
        configured=True,
        ready=True,
        age_seconds=899,
        last_success_timestamp_seconds=completed,
        source_size_bytes=12345,
    )
    metrics = render_prometheus_metrics(
        version="0.2.1",
        database_ready=True,
        recovery=status,
    )
    assert "ton_tracker_recovery_monitoring_configured 1" in metrics
    assert "ton_tracker_recovery_ready 1" in metrics
    assert "ton_tracker_recovery_age_seconds 899.000" in metrics
    assert "ton_tracker_recovery_source_size_bytes 12345" in metrics
    assert record["backup_file"] not in metrics

    stale = read_recovery_health_metrics(
        str(health), maximum_age_seconds=900, now=completed + 901
    )
    assert stale.configured is True
    assert stale.ready is False
    record["restore_check"] = "failed"
    health.write_text(json.dumps(record), encoding="utf-8")
    assert read_recovery_health_metrics(
        str(health), maximum_age_seconds=900, now=completed + 1
    ).ready is False


def test_readiness_and_metrics_endpoints(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    run_database_migrations(engine)
    testing_session = sessionmaker(bind=engine)

    def override_session():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr(database, "engine", engine)
    app.dependency_overrides[get_session] = override_session
    try:
        with TestClient(app) as client:
            ready = client.get("/api/ready")
            metrics = client.get("/metrics")
        assert ready.status_code == 200
        assert ready.json()["database"] == "ready"
        assert ready.headers["cache-control"] == "no-store"
        assert metrics.status_code == 200
        assert "ton_tracker_database_ready 1" in metrics.text
        assert "ton_tracker_backup_monitoring_configured 0" in metrics.text
        assert "ton_tracker_recovery_monitoring_configured 0" in metrics.text
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
