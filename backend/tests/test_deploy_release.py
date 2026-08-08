"""Guarded signed-release rollout tests."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from ops.create_release_manifest import create_release_manifest, write_release_manifest
from ops.deployment_state import (
    DEPLOYMENT_ATTEMPT,
    DEPLOYMENT_LEDGER,
    DEPLOYMENT_RECEIPT,
    DeploymentIdentity,
    DeploymentStateError,
    locked_deployment_state,
)
from ops.deploy_release import (
    DeploymentRolloutError,
    RolloutStep,
    _run_command,
    verify_and_deploy_release,
)
from ops.verify_release_bundle import ReleaseBundleVerificationError


TAG = "v0.68.0"
SOURCE_COMMIT = "1" * 40
BACKEND_DIGEST = "sha256:" + "a" * 64
FRONTEND_DIGEST = "sha256:" + "b" * 64


def _release_assets(
    tmp_path: Path,
    *,
    tag: str = TAG,
    source_commit: str = SOURCE_COMMIT,
    backend_digest: str = BACKEND_DIGEST,
    frontend_digest: str = FRONTEND_DIGEST,
) -> tuple[Path, Path, Path]:
    prefix = f"gram-scope-{tag}-deployment"
    manifest = tmp_path / f"{prefix}.json"
    checksum = tmp_path / f"{prefix}.json.sha256"
    attestation = tmp_path / f"{prefix}.intoto.jsonl"
    write_release_manifest(
        create_release_manifest(
            tag=tag,
            source_commit=source_commit,
            backend_digest=backend_digest,
            frontend_digest=frontend_digest,
        ),
        manifest,
    )
    checksum.write_text(
        f"{hashlib.sha256(manifest.read_bytes()).hexdigest()}  {manifest.name}\n",
        encoding="ascii",
    )
    attestation.write_text('{"attestation":"fixture"}\n', encoding="utf-8")
    return manifest, checksum, attestation


def _environment(tmp_path: Path | None = None) -> dict[str, str]:
    environment = {
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
        "ALERTMANAGER_RETENTION": "120h",
        "APP_PULL_POLICY": "always",
    }
    if tmp_path is not None:
        config = tmp_path / "alertmanager.yml"
        config.write_text(
            "route:\n  receiver: release-test\nreceivers:\n"
            "  - name: release-test\n    webhook_configs:\n"
            "      - url: https://alerts.example/release-test\n",
            encoding="utf-8",
        )
        config.chmod(0o600)
        environment["ALERTMANAGER_CONFIG_FILE"] = str(config)
    return environment


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
        environment=_environment(tmp_path),
        state_directory=tmp_path / "state",
        smoke_url="http://127.0.0.1:18080",
        attestation_verifier=verify_attestation,
        command_runner=runner,
        smoke_checker=check_smoke,
    )

    assert [step.name for step, _environment_value in observed] == [
        "compose configuration",
        "container production preflight",
        "Alertmanager configuration",
        "pre-rollout backup",
        "pre-rollout restore drill",
        "release image pull",
        "target database migration rehearsal",
        "service activation",
        "monitoring delivery smoke",
        "external notification drill",
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
        "ops",
        "run",
        "--rm",
        "alertmanager-config-check",
    )
    assert commands[3][-5:] == (
        "--profile",
        "deployment",
        "run",
        "--rm",
        "backup-now",
    )
    assert commands[4][-1] == "restore-drill"
    assert commands[5][-4:] == ("pull", "backend", "frontend", "alertmanager")
    assert commands[6][-5:] == (
        "--profile",
        "deployment",
        "run",
        "--rm",
        "migration-rehearsal",
    )
    assert commands[7][-6:] == (
        "frontend",
        "prometheus",
        "backup",
        "recovery-watchdog",
        "deployment-monitor",
        "alertmanager",
    )
    assert commands[8][-5:] == (
        "--profile",
        "deployment",
        "run",
        "--rm",
        "monitoring-smoke",
    )
    assert commands[9][-5:] == (
        "--profile",
        "deployment",
        "run",
        "--rm",
        "notification-drill",
    )
    rollout_environment = observed[-1][1]
    assert rollout_environment["BACKEND_IMAGE"] == (
        f"ghcr.io/gr1gorii/ton-tracker-backend@{BACKEND_DIGEST}"
    )
    assert rollout_environment["FRONTEND_IMAGE"] == (
        f"ghcr.io/gr1gorii/ton-tracker-frontend@{FRONTEND_DIGEST}"
    )
    assert rollout_environment["DEPLOYMENT_STATE_DIRECTORY"] == str(
        tmp_path / "state"
    )
    assert rollout_environment["DEPLOYMENT_STATE_UID"] == str(os.getuid())
    assert rollout_environment["DEPLOYMENT_STATE_GID"] == str(os.getgid())
    assert rollout_environment["ALERTMANAGER_DATA_DIRECTORY"] == str(
        tmp_path / "state-alertmanager"
    )
    assert (tmp_path / "state-alertmanager").stat().st_mode & 0o777 == 0o700
    assert smoke == [("http://127.0.0.1:18080", "https://gram.example")]
    assert result.tag == TAG
    assert result.source_commit == SOURCE_COMMIT
    assert result.manifest_sha256 == hashlib.sha256(trusted_manifest).hexdigest()
    assert snapshot_paths and not snapshot_paths[0].exists()
    receipt_path = tmp_path / "state" / DEPLOYMENT_RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert receipt["schema"] == "gram_scope_deployment_receipt_v4"
    assert receipt["status"] == "active"
    assert receipt["operation"] == "deployment"
    assert len(receipt["attempt_id"]) == 32
    assert receipt["release"] == {
        "tag": TAG,
        "source_commit": SOURCE_COMMIT,
        "manifest_sha256": result.manifest_sha256,
    }
    assert receipt["previous_release"] is None
    assert receipt["ledger_sequence"] == 1
    events = list((tmp_path / "state" / DEPLOYMENT_LEDGER).iterdir())
    assert len(events) == 1
    assert events[0].name == (
        f"{1:020d}-{receipt['ledger_event_sha256']}.json"
    )
    event = json.loads(events[0].read_text(encoding="utf-8"))
    assert event["attempt_id"] == receipt["attempt_id"]
    assert event["release"] == receipt["release"]
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert not (tmp_path / "state" / DEPLOYMENT_ATTEMPT).exists()


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
            environment=_environment(tmp_path),
            state_directory=tmp_path / "state",
            attestation_verifier=reject,
            command_runner=runner,
        )
    assert invoked is False
    assert not (tmp_path / "state" / DEPLOYMENT_ATTEMPT).exists()


def test_invalid_production_environment_runs_no_rollout_step(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    environment = _environment(tmp_path)
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
    assert (tmp_path / "state" / DEPLOYMENT_ATTEMPT).is_file()


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
            environment=_environment(tmp_path),
            state_directory=tmp_path / "state",
            attestation_verifier=lambda *_args: None,
            command_runner=runner,
        )
    assert observed == [
        "compose configuration",
        "container production preflight",
        "Alertmanager configuration",
        "pre-rollout backup",
    ]
    assert (tmp_path / "state" / DEPLOYMENT_ATTEMPT).is_file()


def test_public_smoke_failure_is_fail_closed_after_activation(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    observed: list[str] = []

    with pytest.raises(DeploymentRolloutError, match="public smoke gate"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(tmp_path),
            state_directory=tmp_path / "state",
            attestation_verifier=lambda *_args: None,
            command_runner=lambda step, _env: observed.append(step.name),
            smoke_checker=lambda _target, _expected: ["/api/ready is unavailable"],
        )
    assert observed[-1] == "external notification drill"
    assert not (tmp_path / "state" / DEPLOYMENT_RECEIPT).exists()
    assert (tmp_path / "state" / DEPLOYMENT_ATTEMPT).is_file()


def test_migration_rehearsal_failure_stops_before_service_activation(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    observed: list[str] = []

    def runner(step: RolloutStep, _environment_value: dict[str, str]) -> None:
        observed.append(step.name)
        if step.name == "target database migration rehearsal":
            raise DeploymentRolloutError(
                "rollout step failed: target database migration rehearsal"
            )

    with pytest.raises(DeploymentRolloutError, match="migration rehearsal"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(tmp_path),
            state_directory=tmp_path / "state",
            attestation_verifier=lambda *_args: None,
            command_runner=runner,
        )

    assert observed[-2:] == [
        "release image pull",
        "target database migration rehearsal",
    ]
    assert "service activation" not in observed
    assert (tmp_path / "state" / DEPLOYMENT_ATTEMPT).is_file()


def test_interrupted_rollout_blocks_new_attempt_and_exact_resume_completes(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    state_directory = tmp_path / "state"
    first_steps: list[str] = []

    def fail_after_activation(step: RolloutStep, _environment: dict[str, str]) -> None:
        first_steps.append(step.name)
        if step.name == "service activation":
            raise DeploymentRolloutError("activation result is unknown")

    with pytest.raises(DeploymentRolloutError, match="unknown"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(tmp_path),
            state_directory=state_directory,
            attestation_verifier=lambda *_args: None,
            command_runner=fail_after_activation,
        )
    pending_before = json.loads(
        (state_directory / DEPLOYMENT_ATTEMPT).read_text(encoding="utf-8")
    )
    assert first_steps[-1] == "service activation"

    with pytest.raises(DeploymentRolloutError, match="--resume"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(tmp_path),
            state_directory=state_directory,
            attestation_verifier=lambda *_args: None,
            command_runner=lambda *_args: pytest.fail("rollout must not restart"),
        )

    resumed_steps: list[str] = []
    result = verify_and_deploy_release(
        manifest_path=manifest,
        checksum_path=checksum,
        attestation_path=attestation,
        expected_tag=TAG,
        environment=_environment(tmp_path),
        state_directory=state_directory,
        resume=True,
        attestation_verifier=lambda *_args: None,
        command_runner=lambda step, _env: resumed_steps.append(step.name),
        smoke_checker=lambda *_args: [],
    )

    receipt = json.loads(
        (state_directory / DEPLOYMENT_RECEIPT).read_text(encoding="utf-8")
    )
    assert result.tag == TAG
    assert resumed_steps[-1] == "external notification drill"
    assert receipt["attempt_id"] == pending_before["attempt_id"]
    assert not (state_directory / DEPLOYMENT_ATTEMPT).exists()


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
            environment=_environment(tmp_path),
            state_directory=state_directory,
            attestation_verifier=lambda *_args: observed.append("verification"),
            command_runner=lambda step, _env: observed.append(step.name),
        )

    assert observed == []


def test_explicit_rollback_requires_and_activates_exact_previous_bundle(tmp_path):
    rollback_tag = "v0.61.0"
    manifest, checksum, attestation = _release_assets(
        tmp_path,
        tag=rollback_tag,
        source_commit="2" * 40,
        backend_digest="sha256:" + "c" * 64,
        frontend_digest="sha256:" + "d" * 64,
    )
    rollback_identity = DeploymentIdentity(
        tag=rollback_tag,
        source_commit="2" * 40,
        manifest_sha256=hashlib.sha256(manifest.read_bytes()).hexdigest(),
    )
    current_identity = DeploymentIdentity(
        tag=TAG,
        source_commit="3" * 40,
        manifest_sha256="e" * 64,
    )
    state_directory = tmp_path / "state"
    with locked_deployment_state(state_directory) as state:
        state.record_success(rollback_identity)
        state.record_success(current_identity)

    with pytest.raises(DeploymentRolloutError, match="must be newer"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=rollback_tag,
            environment=_environment(tmp_path),
            state_directory=state_directory,
            attestation_verifier=lambda *_args: None,
            command_runner=lambda *_args: pytest.fail("rollout must not start"),
        )

    observed: list[str] = []
    result = verify_and_deploy_release(
        manifest_path=manifest,
        checksum_path=checksum,
        attestation_path=attestation,
        expected_tag=rollback_tag,
        environment=_environment(tmp_path),
        state_directory=state_directory,
        rollback=True,
        attestation_verifier=lambda *_args: None,
        command_runner=lambda step, _env: observed.append(step.name),
        smoke_checker=lambda *_args: [],
    )

    assert result.tag == rollback_tag
    assert observed[-1] == "external notification drill"
    receipt = json.loads(
        (state_directory / DEPLOYMENT_RECEIPT).read_text(encoding="utf-8")
    )
    assert receipt["operation"] == "rollback"
    assert receipt["release"] == {
        "tag": rollback_identity.tag,
        "source_commit": rollback_identity.source_commit,
        "manifest_sha256": rollback_identity.manifest_sha256,
    }
    assert receipt["previous_release"] == {
        "tag": current_identity.tag,
        "source_commit": current_identity.source_commit,
        "manifest_sha256": current_identity.manifest_sha256,
    }


def test_explicit_rollback_rejects_other_signed_release_before_rollout(tmp_path):
    previous_identity = DeploymentIdentity(
        tag="v0.61.0",
        source_commit="2" * 40,
        manifest_sha256="c" * 64,
    )
    current_identity = DeploymentIdentity(
        tag=TAG,
        source_commit="3" * 40,
        manifest_sha256="d" * 64,
    )
    state_directory = tmp_path / "state"
    with locked_deployment_state(state_directory) as state:
        state.record_success(previous_identity)
        state.record_success(current_identity)

    manifest, checksum, attestation = _release_assets(
        tmp_path,
        tag="v0.59.0",
        source_commit="4" * 40,
    )
    with pytest.raises(DeploymentRolloutError, match="does not match"):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag="v0.59.0",
            environment=_environment(tmp_path),
            state_directory=state_directory,
            rollback=True,
            attestation_verifier=lambda *_args: None,
            command_runner=lambda *_args: pytest.fail("rollout must not start"),
        )


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
        match="rollout succeeded but deployment state finalization failed",
    ):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(tmp_path),
            state_directory=tmp_path / "state",
            attestation_verifier=lambda *_args: None,
            command_runner=lambda step, _env: observed.append(step.name),
            smoke_checker=lambda *_args: [],
        )

    assert observed[-1] == "external notification drill"
    assert not (tmp_path / "state" / DEPLOYMENT_RECEIPT).exists()
    assert (tmp_path / "state" / DEPLOYMENT_ATTEMPT).is_file()


def test_resume_finalizes_published_event_without_repeating_rollout(
    tmp_path,
    monkeypatch,
):
    manifest, checksum, attestation = _release_assets(tmp_path)
    state_directory = tmp_path / "state"
    observed: list[str] = []

    def fail_receipt(*_args, **_kwargs):
        raise DeploymentStateError("simulated receipt interruption")

    monkeypatch.setattr("ops.deployment_state._write_atomic_receipt", fail_receipt)
    with pytest.raises(
        DeploymentRolloutError,
        match="rollout succeeded but deployment state finalization failed",
    ):
        verify_and_deploy_release(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            environment=_environment(tmp_path),
            state_directory=state_directory,
            attestation_verifier=lambda *_args: None,
            command_runner=lambda step, _env: observed.append(step.name),
            smoke_checker=lambda *_args: [],
        )

    assert observed[-1] == "external notification drill"
    assert len(list((state_directory / DEPLOYMENT_LEDGER).iterdir())) == 1
    assert (state_directory / DEPLOYMENT_ATTEMPT).is_file()
    assert not (state_directory / DEPLOYMENT_RECEIPT).exists()

    monkeypatch.undo()
    result = verify_and_deploy_release(
        manifest_path=manifest,
        checksum_path=checksum,
        attestation_path=attestation,
        expected_tag=TAG,
        environment=_environment(tmp_path),
        state_directory=state_directory,
        resume=True,
        attestation_verifier=lambda *_args: None,
        command_runner=lambda *_args: pytest.fail("rollout must not repeat"),
        smoke_checker=lambda *_args: pytest.fail("smoke must not repeat"),
    )

    receipt = json.loads(
        (state_directory / DEPLOYMENT_RECEIPT).read_text(encoding="utf-8")
    )
    assert result.tag == TAG
    assert receipt["schema"] == "gram_scope_deployment_receipt_v4"
    assert receipt["ledger_sequence"] == 1
    assert not (state_directory / DEPLOYMENT_ATTEMPT).exists()


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
