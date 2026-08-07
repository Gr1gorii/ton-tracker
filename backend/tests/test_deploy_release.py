"""Guarded signed-release rollout tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from ops.create_release_manifest import create_release_manifest, write_release_manifest
from ops.deployment_state import DEPLOYMENT_RECEIPT, DeploymentStateError
from ops.deploy_release import (
    DeploymentRolloutError,
    RolloutStep,
    _run_command,
    verify_and_deploy_release,
)
from ops.verify_release_bundle import ReleaseBundleVerificationError


TAG = "v0.60.0"
SOURCE_COMMIT = "1" * 40
BACKEND_DIGEST = "sha256:" + "a" * 64
FRONTEND_DIGEST = "sha256:" + "b" * 64


def _release_assets(tmp_path: Path) -> tuple[Path, Path, Path]:
    prefix = f"gram-scope-{TAG}-deployment"
    manifest = tmp_path / f"{prefix}.json"
    checksum = tmp_path / f"{prefix}.json.sha256"
    attestation = tmp_path / f"{prefix}.intoto.jsonl"
    write_release_manifest(
        create_release_manifest(
            tag=TAG,
            source_commit=SOURCE_COMMIT,
            backend_digest=BACKEND_DIGEST,
            frontend_digest=FRONTEND_DIGEST,
        ),
        manifest,
    )
    checksum.write_text(
        f"{hashlib.sha256(manifest.read_bytes()).hexdigest()}  {manifest.name}\n",
        encoding="ascii",
    )
    attestation.write_text('{"attestation":"fixture"}\n', encoding="utf-8")
    return manifest, checksum, attestation


def _environment() -> dict[str, str]:
    return {
        "PATH": os.environ.get("PATH", ""),
        "PUBLIC_APP_URL": "https://gram.example",
        "APP_PORT": "8080",
        "DATA_MODE": "real",
        "TON_NETWORK": "mainnet",
        "TONAPI_BASE_URL": "https://tonapi.io",
        "TONAPI_API_KEY": "ci-placeholder-key-with-valid-length",
        "WALLET_ACTIVITY_PROVIDER": "tonapi",
        "WALLET_ACTIVITY_LIVE_ENABLED": "true",
        "TON_LITECLIENT_TRUST_LEVEL": "0",
        "TONCONNECT_EXPECTED_DOMAIN": "gram.example",
        "BACKUP_INTERVAL_SECONDS": "86400",
        "BACKUP_RETENTION": "14",
        "BACKUP_HEALTH_MAX_AGE_SECONDS": "172800",
        "RECOVERY_INTERVAL_SECONDS": "604800",
        "RECOVERY_RETRY_SECONDS": "300",
        "RECOVERY_HEALTH_MAX_AGE_SECONDS": "691200",
        "PROMETHEUS_RETENTION": "15d",
        "APP_PULL_POLICY": "always",
    }


def test_guarded_rollout_uses_verified_snapshot_and_strict_step_order(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    trusted_manifest = manifest.read_bytes()
    observed: list[tuple[RolloutStep, dict[str, str]]] = []
    snapshot_paths: list[Path] = []
    smoke: list[tuple[str, str]] = []

    def runner(step: RolloutStep, environment: dict[str, str]) -> None:
        snapshot = Path(environment["DEPLOYMENT_MANIFEST_FILE"])
        assert snapshot.read_bytes() == trusted_manifest
        assert snapshot.stat().st_mode & 0o777 == 0o600
        snapshot_paths.append(snapshot)
        observed.append((step, dict(environment)))

    def check_smoke(target: str, expected: str) -> list[str]:
        smoke.append((target, expected))
        return []

    def verify_attestation(manifest_snapshot: Path, *_args) -> None:
        assert manifest_snapshot.read_bytes() == trusted_manifest
        manifest.write_bytes(b"tampered after signed snapshot verification")

    result = verify_and_deploy_release(
        manifest_path=manifest,
        checksum_path=checksum,
        attestation_path=attestation,
        expected_tag=TAG,
        environment=_environment(),
        state_directory=tmp_path / "state",
        smoke_url="http://127.0.0.1:18080",
        attestation_verifier=verify_attestation,
        command_runner=runner,
        smoke_checker=check_smoke,
    )

    assert [step.name for step, _environment_value in observed] == [
        "compose configuration",
        "container production preflight",
        "pre-rollout backup",
        "pre-rollout restore drill",
        "release image pull",
        "service activation",
    ]
    commands = [step.command for step, _environment_value in observed]
    assert commands[1][-5:] == (
        "--profile",
        "ops",
        "run",
        "--rm",
        "production-preflight",
    )
    assert commands[2][-5:] == (
        "--profile",
        "deployment",
        "run",
        "--rm",
        "backup-now",
    )
    assert commands[3][-1] == "restore-drill"
    assert commands[4][-3:] == ("pull", "backend", "frontend")
    assert commands[5][-4:] == (
        "frontend",
        "prometheus",
        "backup",
        "recovery-watchdog",
    )
    rollout_environment = observed[-1][1]
    assert rollout_environment["BACKEND_IMAGE"] == (
        f"ghcr.io/gr1gorii/ton-tracker-backend@{BACKEND_DIGEST}"
    )
    assert rollout_environment["FRONTEND_IMAGE"] == (
        f"ghcr.io/gr1gorii/ton-tracker-frontend@{FRONTEND_DIGEST}"
    )
    assert smoke == [("http://127.0.0.1:18080", "https://gram.example")]
    assert result.tag == TAG
    assert result.source_commit == SOURCE_COMMIT
    assert result.manifest_sha256 == hashlib.sha256(trusted_manifest).hexdigest()
    assert snapshot_paths and not snapshot_paths[0].exists()
    receipt_path = tmp_path / "state" / DEPLOYMENT_RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == "gram_scope_deployment_receipt_v1"
    assert receipt["status"] == "active"
    assert receipt["release"] == {
        "tag": TAG,
        "source_commit": SOURCE_COMMIT,
        "manifest_sha256": result.manifest_sha256,
    }
    assert receipt["previous_release"] is None
    assert receipt_path.stat().st_mode & 0o777 == 0o600


def test_bundle_verification_failure_runs_no_rollout_step(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    invoked = False

    def runner(*_args) -> None:
        nonlocal invoked
        invoked = True

    def reject(*_args) -> None:
        raise ReleaseBundleVerificationError("deployment attestation is invalid")

    with pytest.raises(ReleaseBundleVerificationError, match="attestation"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(),
            state_directory=tmp_path / "state",
            attestation_verifier=reject,
            command_runner=runner,
        )
    assert invoked is False


def test_invalid_production_environment_runs_no_rollout_step(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    environment = _environment()
    environment["TONAPI_API_KEY"] = "exposed invalid value"
    invoked = False

    def runner(*_args) -> None:
        nonlocal invoked
        invoked = True

    with pytest.raises(DeploymentRolloutError, match="TONAPI_API_KEY") as exc_info:
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=environment,
            state_directory=tmp_path / "state",
            attestation_verifier=lambda *_args: None,
            command_runner=runner,
        )
    assert invoked is False
    assert environment["TONAPI_API_KEY"] not in str(exc_info.value)


def test_rollout_stops_before_pull_when_backup_gate_fails(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    observed: list[str] = []

    def runner(step: RolloutStep, _environment_value: dict[str, str]) -> None:
        observed.append(step.name)
        if step.name == "pre-rollout backup":
            raise DeploymentRolloutError("rollout step failed: pre-rollout backup")

    with pytest.raises(DeploymentRolloutError, match="pre-rollout backup"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(),
            state_directory=tmp_path / "state",
            attestation_verifier=lambda *_args: None,
            command_runner=runner,
        )
    assert observed == [
        "compose configuration",
        "container production preflight",
        "pre-rollout backup",
    ]


def test_public_smoke_failure_is_fail_closed_after_activation(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    observed: list[str] = []

    with pytest.raises(DeploymentRolloutError, match="public smoke gate"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(),
            state_directory=tmp_path / "state",
            attestation_verifier=lambda *_args: None,
            command_runner=lambda step, _env: observed.append(step.name),
            smoke_checker=lambda _target, _expected: ["/api/ready is unavailable"],
        )
    assert observed[-1] == "service activation"
    assert not (tmp_path / "state" / DEPLOYMENT_RECEIPT).exists()


def test_invalid_existing_receipt_runs_no_verification_or_rollout_step(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    state_directory = tmp_path / "state"
    state_directory.mkdir(mode=0o700)
    receipt = state_directory / DEPLOYMENT_RECEIPT
    receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")
    receipt.chmod(0o600)
    observed: list[str] = []

    with pytest.raises(DeploymentRolloutError, match="deployment state gate failed"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(),
            state_directory=state_directory,
            attestation_verifier=lambda *_args: observed.append("verification"),
            command_runner=lambda step, _env: observed.append(step.name),
        )

    assert observed == []


def test_receipt_finalization_failure_reports_ambiguous_active_state(
    tmp_path,
    monkeypatch,
):
    manifest, checksum, attestation = _release_assets(tmp_path)
    observed: list[str] = []

    def fail_receipt(*_args, **_kwargs):
        raise DeploymentStateError("storage unavailable")

    monkeypatch.setattr(
        "ops.deployment_state.LockedDeploymentState.record_success",
        fail_receipt,
    )
    with pytest.raises(
        DeploymentRolloutError,
        match="deployment succeeded but receipt finalization failed",
    ):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(),
            state_directory=tmp_path / "state",
            attestation_verifier=lambda *_args: None,
            command_runner=lambda step, _env: observed.append(step.name),
            smoke_checker=lambda *_args: [],
        )

    assert observed[-1] == "service activation"
    assert not (tmp_path / "state" / DEPLOYMENT_RECEIPT).exists()


def test_command_failure_does_not_expose_process_output(monkeypatch):
    step = RolloutStep("pre-rollout backup", ("docker", "compose"), 60)
    observed: dict[str, object] = {}

    def run(command, **options):
        observed["command"] = command
        observed["options"] = options
        return subprocess.CompletedProcess(
            step.command,
            1,
            stdout=b"private stdout",
            stderr=b"secret stderr",
        )

    monkeypatch.setattr("ops.deploy_release.subprocess.run", run)
    with pytest.raises(
        DeploymentRolloutError,
        match=r"^rollout step failed: pre-rollout backup$",
    ) as exc_info:
        _run_command(step, _environment())
    assert "private" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)
    assert observed["command"] == ["docker", "compose"]
    options = observed["options"]
    assert options["stdin"] is subprocess.DEVNULL
    assert options["stdout"] is subprocess.DEVNULL
    assert options["stderr"] is subprocess.DEVNULL
    assert options["check"] is False
    assert options["timeout"] == 60
