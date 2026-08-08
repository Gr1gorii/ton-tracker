"""Credential-free deployment audit command tests."""

from __future__ import annotations

import json

import pytest

from ops.deployment_state import (
    DEPLOYMENT_ATTEMPT,
    DEPLOYMENT_RECEIPT,
    DeploymentIdentity,
    DeploymentStateError,
    locked_deployment_state,
)
from ops.inspect_deployment_state import (
    EXIT_BUSY,
    EXIT_INTERRUPTED,
    EXIT_INVALID,
    EXIT_USAGE,
    EXIT_VALID,
    main,
)


def _identity(tag: str, marker: str) -> DeploymentIdentity:
    return DeploymentIdentity(
        tag=tag,
        source_commit=marker * 40,
        manifest_sha256=marker * 64,
    )


def test_audit_reports_empty_state_as_valid_json(tmp_path, capsys):
    directory = tmp_path / "state"

    assert main(["--state-directory", str(directory)]) == EXIT_VALID
    captured = capsys.readouterr()
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "schema": "gram_scope_deployment_audit_v1",
        "status": "empty",
        "active_release": None,
        "previous_release": None,
        "receipt": None,
        "ledger": {
            "event_count": 0,
            "head_sequence": None,
            "head_sha256": None,
            "receipt_binding": "none",
        },
        "pending_attempt": None,
    }


def test_audit_reserves_interrupted_code_from_usage_errors(capsys):
    assert main([]) == EXIT_USAGE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "schema": "gram_scope_deployment_audit_error_v1",
        "status": "usage",
        "message": "deployment audit arguments are invalid",
    }


def test_audit_reports_bound_active_release_and_complete_history(tmp_path, capsys):
    directory = tmp_path / "state"
    first = _identity("v0.63.0", "a")
    second = _identity("v0.64.0", "b")
    with locked_deployment_state(directory) as state:
        state.record_success(first, attempt_id="1" * 32)
        state.record_success(second, attempt_id="2" * 32)

    assert main(["--state-directory", str(directory)]) == EXIT_VALID
    captured = capsys.readouterr()
    report = json.loads(captured.out)
    assert captured.err == ""
    assert report["status"] == "ready"
    assert report["active_release"]["tag"] == "v0.64.0"
    assert report["previous_release"]["tag"] == "v0.63.0"
    assert report["receipt"] == {
        "schema": "gram_scope_deployment_receipt_v4",
        "operation": "deployment",
        "attempt_id": "2" * 32,
        "completed_at": report["receipt"]["completed_at"],
    }
    assert report["ledger"]["event_count"] == 2
    assert report["ledger"]["head_sequence"] == 2
    assert len(report["ledger"]["head_sha256"]) == 64
    assert report["ledger"]["receipt_binding"] == "bound"
    assert report["pending_attempt"] is None


def test_audit_reports_legacy_receipt_without_inventing_ledger_data(
    tmp_path,
    capsys,
):
    directory = tmp_path / "state"
    directory.mkdir(mode=0o700)
    release = _identity("v0.63.0", "a")
    receipt = {
        "schema": "gram_scope_deployment_receipt_v1",
        "status": "active",
        "completed_at": "2026-08-08T01:02:03Z",
        "release": {
            "tag": release.tag,
            "source_commit": release.source_commit,
            "manifest_sha256": release.manifest_sha256,
        },
        "previous_release": None,
    }
    receipt_path = directory / DEPLOYMENT_RECEIPT
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    receipt_path.chmod(0o600)

    assert main(["--state-directory", str(directory)]) == EXIT_VALID
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ready"
    assert report["active_release"]["tag"] == "v0.63.0"
    assert report["receipt"] == {
        "schema": "gram_scope_deployment_receipt_v1",
        "operation": None,
        "attempt_id": None,
        "completed_at": "2026-08-08T01:02:03Z",
    }
    assert report["ledger"] == {
        "event_count": 0,
        "head_sequence": None,
        "head_sha256": None,
        "receipt_binding": "none",
    }


def test_audit_returns_interrupted_for_pending_rollout(tmp_path, capsys):
    directory = tmp_path / "state"
    base = _identity("v0.63.0", "a")
    target = _identity("v0.64.0", "b")
    with locked_deployment_state(directory) as state:
        state.record_success(base, attempt_id="1" * 32)
        attempt = state.prepare_attempt(target, rollback=False, resume=False)

    assert main(["--state-directory", str(directory)]) == EXIT_INTERRUPTED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "interrupted"
    assert report["ledger"]["receipt_binding"] == "bound"
    assert report["pending_attempt"]["attempt_id"] == attempt.attempt_id
    assert report["pending_attempt"]["base_release"]["tag"] == "v0.63.0"
    assert report["pending_attempt"]["target_release"]["tag"] == "v0.64.0"


def test_audit_observes_event_awaiting_receipt_without_reconciling(
    tmp_path,
    capsys,
    monkeypatch,
):
    directory = tmp_path / "state"
    base = _identity("v0.63.0", "a")
    target = _identity("v0.64.0", "b")
    with locked_deployment_state(directory) as state:
        state.record_success(base, attempt_id="1" * 32)
        attempt = state.prepare_attempt(target, rollback=False, resume=False)

        def fail_receipt(*_args, **_kwargs):
            raise DeploymentStateError("simulated receipt interruption")

        monkeypatch.setattr("ops.deployment_state._write_atomic_receipt", fail_receipt)
        with pytest.raises(DeploymentStateError, match="interruption"):
            state.complete_attempt(target, attempt)

    assert main(["--state-directory", str(directory)]) == EXIT_INTERRUPTED
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "interrupted"
    assert report["active_release"]["tag"] == "v0.63.0"
    assert report["ledger"]["event_count"] == 2
    assert report["ledger"]["head_sequence"] == 2
    assert report["ledger"]["receipt_binding"] == "awaiting_receipt"
    assert report["pending_attempt"]["target_release"]["tag"] == "v0.64.0"
    persisted_receipt = json.loads(
        (directory / DEPLOYMENT_RECEIPT).read_text(encoding="utf-8")
    )
    assert persisted_receipt["release"]["tag"] == "v0.63.0"
    assert (directory / DEPLOYMENT_ATTEMPT).is_file()


def test_audit_rejects_corrupt_state_with_sanitized_error(tmp_path, capsys):
    directory = tmp_path / "state"
    with locked_deployment_state(directory) as state:
        state.record_success(_identity("v0.63.0", "a"))

    receipt_path = directory / DEPLOYMENT_RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["ledger_event_sha256"] = "f" * 64
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")

    assert main(["--state-directory", str(directory)]) == EXIT_INVALID
    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "schema": "gram_scope_deployment_audit_error_v1",
        "status": "invalid",
        "message": "deployment state validation failed",
    }
    assert str(directory) not in captured.err


def test_audit_distinguishes_busy_state_without_changing_it(tmp_path, capsys):
    directory = tmp_path / "state"
    with locked_deployment_state(directory) as state:
        state.record_success(_identity("v0.63.0", "a"))
        before = state.audit_report()
        assert main(["--state-directory", str(directory)]) == EXIT_BUSY
        assert state.audit_report() == before

    captured = capsys.readouterr()
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "schema": "gram_scope_deployment_audit_error_v1",
        "status": "busy",
        "message": "another deployment is already in progress",
    }
