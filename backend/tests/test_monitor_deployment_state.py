"""Deployment state Prometheus watchdog tests."""

from __future__ import annotations

import json
import threading
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest

from ops.deployment_state import (
    DEPLOYMENT_RECEIPT,
    DeploymentIdentity,
    locked_deployment_state,
)
from ops.monitor_deployment_state import (
    DeploymentAuditMetrics,
    collect_deployment_audit_metrics,
    create_monitor_server,
    render_deployment_prometheus,
)


def _identity(tag: str, marker: str) -> DeploymentIdentity:
    return DeploymentIdentity(
        tag=tag,
        source_commit=marker * 40,
        manifest_sha256=marker * 64,
    )


def _samples(payload: str) -> dict[str, int]:
    rows: dict[str, int] = {}
    for line in payload.splitlines():
        if line and not line.startswith("#"):
            name, value = line.rsplit(" ", 1)
            rows[name] = int(value)
    return rows


def test_monitor_reports_empty_and_ready_state_without_release_labels(tmp_path):
    directory = tmp_path / "state"
    empty = collect_deployment_audit_metrics(directory)
    empty_samples = _samples(render_deployment_prometheus(empty))

    assert empty == DeploymentAuditMetrics(status="empty", valid=True)
    assert empty_samples["ton_tracker_deployment_audit_valid"] == 1
    assert empty_samples["ton_tracker_deployment_state_ready"] == 0
    assert empty_samples['ton_tracker_deployment_state_info{status="empty"}'] == 1

    with locked_deployment_state(directory) as state:
        state.record_success(_identity("v0.64.0", "a"), attempt_id="1" * 32)

    ready = collect_deployment_audit_metrics(directory)
    rendered = render_deployment_prometheus(ready)
    ready_samples = _samples(rendered)
    assert ready == DeploymentAuditMetrics(
        status="ready",
        valid=True,
        ledger_event_count=1,
        receipt_bound=True,
    )
    assert ready_samples["ton_tracker_deployment_state_ready"] == 1
    assert ready_samples["ton_tracker_deployment_ledger_events"] == 1
    assert ready_samples["ton_tracker_deployment_receipt_bound"] == 1
    assert "v0.64.0" not in rendered
    assert "a" * 40 not in rendered


def test_monitor_exposes_interrupted_attempt_and_awaiting_receipt(tmp_path, monkeypatch):
    directory = tmp_path / "state"
    base = _identity("v0.64.0", "a")
    target = _identity("v0.65.0", "b")
    with locked_deployment_state(directory) as state:
        state.record_success(base, attempt_id="1" * 32)
        attempt = state.prepare_attempt(target, rollback=False, resume=False)

        def fail_receipt(*_args, **_kwargs):
            raise RuntimeError("simulated receipt interruption")

        monkeypatch.setattr("ops.deployment_state._write_atomic_receipt", fail_receipt)
        with pytest.raises(RuntimeError, match="interruption"):
            state.complete_attempt(target, attempt)

    observed = collect_deployment_audit_metrics(directory)
    samples = _samples(render_deployment_prometheus(observed))
    assert observed.status == "interrupted"
    assert observed.valid is True
    assert observed.pending_attempt is True
    assert observed.ledger_event_count == 2
    assert observed.receipt_bound is False
    assert samples["ton_tracker_deployment_pending_attempt"] == 1
    assert samples["ton_tracker_deployment_receipt_bound"] == 0
    assert samples['ton_tracker_deployment_state_info{status="interrupted"}'] == 1


def test_monitor_distinguishes_expected_busy_lock_from_corrupt_state(tmp_path):
    directory = tmp_path / "state"
    with locked_deployment_state(directory) as state:
        state.record_success(_identity("v0.64.0", "a"))
        busy = collect_deployment_audit_metrics(directory)

    assert busy == DeploymentAuditMetrics(
        status="busy",
        valid=False,
        lock_busy=True,
    )
    busy_samples = _samples(render_deployment_prometheus(busy))
    assert busy_samples["ton_tracker_deployment_audit_valid"] == 0
    assert busy_samples["ton_tracker_deployment_lock_busy"] == 1

    receipt = directory / DEPLOYMENT_RECEIPT
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    payload["ledger_event_sha256"] = "f" * 64
    receipt.write_text(json.dumps(payload) + "\n", encoding="utf-8")
    invalid = collect_deployment_audit_metrics(directory)
    assert invalid == DeploymentAuditMetrics(status="invalid", valid=False)
    invalid_samples = _samples(render_deployment_prometheus(invalid))
    assert invalid_samples["ton_tracker_deployment_audit_valid"] == 0
    assert invalid_samples["ton_tracker_deployment_lock_busy"] == 0
    assert invalid_samples['ton_tracker_deployment_state_info{status="invalid"}'] == 1


def test_monitor_http_surface_is_internal_minimal_and_no_store(tmp_path):
    directory = tmp_path / "state"
    server = create_monitor_server("127.0.0.1", 0, directory)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with urlopen(f"{origin}/healthz", timeout=2) as response:
            assert response.status == 200
            assert response.read() == b"ok\n"
            assert response.headers["Cache-Control"] == "no-store"
            assert response.headers["X-Content-Type-Options"] == "nosniff"
        with urlopen(f"{origin}/metrics", timeout=2) as response:
            assert response.status == 200
            assert response.headers["Content-Type"] == (
                "text/plain; version=0.0.4; charset=utf-8"
            )
            assert b"ton_tracker_deployment_audit_valid 1\n" in response.read()
        with pytest.raises(HTTPError) as error:
            urlopen(f"{origin}/metrics?unexpected=1", timeout=2)
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_monitor_renderer_rejects_unbounded_or_unknown_fields():
    with pytest.raises(ValueError, match="status"):
        render_deployment_prometheus(
            DeploymentAuditMetrics(status='ready"} 1\nbad_metric', valid=True)
        )
    with pytest.raises(ValueError, match="event count"):
        render_deployment_prometheus(
            DeploymentAuditMetrics(
                status="ready",
                valid=True,
                ledger_event_count=-1,
            )
        )
    with pytest.raises(ValueError, match="inconsistent"):
        render_deployment_prometheus(
            DeploymentAuditMetrics(status="ready", valid=False)
        )


def test_monitor_fails_closed_if_internal_audit_contract_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "ops.monitor_deployment_state.inspect_deployment_state",
        lambda _directory: {
            "status": "interrupted",
            "ledger": {
                "event_count": 100_001,
                "receipt_binding": "awaiting_receipt",
            },
            "pending_attempt": "unbounded-free-form-value",
        },
    )

    observed = collect_deployment_audit_metrics(tmp_path / "state")
    assert observed == DeploymentAuditMetrics(status="invalid", valid=False)
