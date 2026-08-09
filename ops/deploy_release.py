"""Run one ordered, fail-closed GRAM Scope production rollout."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile

try:
    from .alertmanager_config import (
        AlertmanagerConfigError,
        prepare_alertmanager_data_directory,
    )
    from .deployment_state import (
        DeploymentIdentity,
        DeploymentStateError,
        locked_deployment_state,
    )
    from .production_preflight import run_smoke_checks, validate_environment
    from .verify_release_bundle import (
        AttestationVerifier,
        ReleaseBundleVerificationError,
        VerifiedReleaseBundle,
        verify_release_bundle,
    )
except ImportError:  # pragma: no cover - direct script execution
    from alertmanager_config import (
        AlertmanagerConfigError,
        prepare_alertmanager_data_directory,
    )
    from deployment_state import (
        DeploymentIdentity,
        DeploymentStateError,
        locked_deployment_state,
    )
    from production_preflight import run_smoke_checks, validate_environment
    from verify_release_bundle import (
        AttestationVerifier,
        ReleaseBundleVerificationError,
        VerifiedReleaseBundle,
        verify_release_bundle,
    )


_ROOT = Path(__file__).resolve().parents[1]
_COMPOSE_FILE = _ROOT / "compose.production.yml"


class DeploymentRolloutError(RuntimeError):
    """A rollout gate failed before a successful public smoke check."""


@dataclass(frozen=True)
class RolloutStep:
    name: str
    command: tuple[str, ...]
    timeout_seconds: int
    checkpoint: str | None = None


@dataclass(frozen=True)
class DeploymentResult:
    tag: str
    source_commit: str
    manifest_sha256: str


CommandRunner = Callable[[RolloutStep, Mapping[str, str]], None]
SmokeChecker = Callable[[str, str], list[str]]
CheckpointRecorder = Callable[[str], None]


def run_guarded_rollout(
    bundle: VerifiedReleaseBundle,
    *,
    environment: Mapping[str, str],
    smoke_url: str | None = None,
    command_runner: CommandRunner | None = None,
    smoke_checker: SmokeChecker | None = None,
    initial_deployment: bool = False,
    initial_bootstrap_verified: bool = False,
    checkpoint_recorder: CheckpointRecorder | None = None,
) -> DeploymentResult:
    """Deploy one verified bundle after backup and recovery safety gates."""
    runner = command_runner or _run_command
    check_smoke = smoke_checker or _check_public_smoke

    with tempfile.TemporaryDirectory(prefix="gram-scope-rollout-") as workspace:
        manifest_path = Path(workspace) / f"gram-scope-{bundle.tag}-deployment.json"
        _write_private_manifest(manifest_path, bundle.manifest_bytes)
        rollout_environment = dict(environment)
        rollout_environment.update(bundle.deployment_environment)
        rollout_environment["DEPLOYMENT_MANIFEST_FILE"] = str(manifest_path)

        errors = validate_environment(rollout_environment)
        if errors:
            raise DeploymentRolloutError(
                "production environment is invalid: " + "; ".join(errors)
            )

        for step in rollout_steps(
            initial_deployment=initial_deployment,
            initial_bootstrap_verified=initial_bootstrap_verified,
        ):
            runner(step, rollout_environment)
            if step.checkpoint is not None:
                if checkpoint_recorder is None:
                    raise DeploymentRolloutError(
                        "rollout checkpoint recorder is unavailable"
                    )
                checkpoint_recorder(step.checkpoint)

        expected_public_url = rollout_environment["PUBLIC_APP_URL"].strip()
        target = smoke_url or expected_public_url
        smoke_errors = check_smoke(target, expected_public_url)
        if smoke_errors:
            raise DeploymentRolloutError(
                "public smoke gate failed: " + "; ".join(smoke_errors)
            )

    return DeploymentResult(
        tag=bundle.tag,
        source_commit=bundle.source_commit,
        manifest_sha256=hashlib.sha256(bundle.manifest_bytes).hexdigest(),
    )


def verify_and_deploy_release(
    *,
    manifest_path: Path,
    checksum_path: Path,
    attestation_path: Path,
    expected_tag: str,
    environment: Mapping[str, str],
    state_directory: Path,
    rollback: bool = False,
    resume: bool = False,
    smoke_url: str | None = None,
    attestation_verifier: AttestationVerifier | None = None,
    command_runner: CommandRunner | None = None,
    smoke_checker: SmokeChecker | None = None,
) -> DeploymentResult:
    """Verify, journal, deploy, and commit one serialized release attempt."""
    try:
        with locked_deployment_state(state_directory) as deployment_state:
            bundle = verify_release_bundle(
                manifest_path=manifest_path,
                checksum_path=checksum_path,
                attestation_path=attestation_path,
                expected_tag=expected_tag,
                attestation_verifier=attestation_verifier,
            )
            alertmanager_data_directory = state_directory.with_name(
                f"{state_directory.name}-alertmanager"
            )
            try:
                prepare_alertmanager_data_directory(alertmanager_data_directory)
            except AlertmanagerConfigError as exc:
                raise DeploymentRolloutError(
                    "Alertmanager persistent state gate failed"
                ) from exc
            identity = DeploymentIdentity(
                tag=bundle.tag,
                source_commit=bundle.source_commit,
                manifest_sha256=hashlib.sha256(bundle.manifest_bytes).hexdigest(),
            )
            attempt = deployment_state.prepare_attempt(
                identity,
                rollback=rollback,
                resume=resume,
            )
            if attempt.already_completed:
                return DeploymentResult(
                    tag=identity.tag,
                    source_commit=identity.source_commit,
                    manifest_sha256=identity.manifest_sha256,
                )

            def record_checkpoint(checkpoint: str) -> None:
                if checkpoint != "initial_bootstrap_verified":
                    raise DeploymentRolloutError(
                        f"rollout checkpoint is invalid: {checkpoint}"
                    )
                deployment_state.mark_initial_bootstrap_verified(
                    identity,
                    attempt,
                )

            result = run_guarded_rollout(
                bundle,
                environment={
                    **environment,
                    "DEPLOYMENT_STATE_DIRECTORY": str(state_directory),
                    "DEPLOYMENT_STATE_UID": str(os.getuid()),
                    "DEPLOYMENT_STATE_GID": str(os.getgid()),
                    "ALERTMANAGER_DATA_DIRECTORY": str(
                        alertmanager_data_directory
                    ),
                },
                smoke_url=smoke_url,
                command_runner=command_runner,
                smoke_checker=smoke_checker,
                initial_deployment=attempt.initial_deployment,
                initial_bootstrap_verified=(
                    attempt.rollout_phase == "initial_bootstrap_verified"
                ),
                checkpoint_recorder=record_checkpoint,
            )
            try:
                deployment_state.complete_attempt(
                    identity,
                    attempt,
                )
            except DeploymentStateError as exc:
                raise DeploymentRolloutError(
                    "rollout succeeded but deployment state finalization failed; "
                    "manual inspection is required"
                ) from exc
            return result
    except DeploymentStateError as exc:
        raise DeploymentRolloutError(f"deployment state gate failed: {exc}") from exc


def rollout_steps(
    *,
    initial_deployment: bool = False,
    initial_bootstrap_verified: bool = False,
) -> tuple[RolloutStep, ...]:
    if initial_bootstrap_verified and not initial_deployment:
        raise DeploymentRolloutError(
            "initial bootstrap checkpoint requires an initial deployment"
        )
    compose = (
        "docker",
        "compose",
        "--file",
        str(_COMPOSE_FILE),
    )
    common = (
        RolloutStep(
            "compose configuration",
            (*compose, "config", "--quiet"),
            60,
        ),
        RolloutStep(
            "container production preflight",
            (*compose, "--profile", "ops", "run", "--rm", "production-preflight"),
            180,
        ),
        RolloutStep(
            "Alertmanager configuration",
            (
                *compose,
                "--profile",
                "ops",
                "run",
                "--rm",
                "alertmanager-config-check",
            ),
            180,
        ),
    )
    activation_command = (
        *compose,
        "up",
        "--detach",
        "--no-build",
        "--wait",
        "--wait-timeout",
        "180",
        "frontend",
        "prometheus",
        "backup",
        "recovery-watchdog",
        "deployment-monitor",
        "alertmanager",
    )
    monitoring_steps = (
        RolloutStep(
            "monitoring delivery smoke",
            (
                *compose,
                "--profile",
                "deployment",
                "run",
                "--rm",
                "monitoring-smoke",
            ),
            180,
        ),
        RolloutStep(
            "external notification drill",
            (
                *compose,
                "--profile",
                "deployment",
                "run",
                "--rm",
                "notification-drill",
            ),
            180,
        ),
    )
    recovery_point_steps = (
        RolloutStep(
            "post-activation database backup",
            (*compose, "--profile", "deployment", "run", "--rm", "backup-now"),
            900,
        ),
        RolloutStep(
            "post-activation backup restore drill",
            (*compose, "--profile", "deployment", "run", "--rm", "restore-drill"),
            900,
        ),
        RolloutStep(
            "external recovery point",
            (
                *compose,
                "--profile",
                "deployment",
                "run",
                "--rm",
                "recovery-point-now",
            ),
            900,
        ),
        RolloutStep(
            "external recovery exporter activation",
            (
                *compose,
                "up",
                "--detach",
                "--no-build",
                "--wait",
                "--wait-timeout",
                "900",
                "recovery-point-exporter",
            ),
            1_000,
        ),
    )
    if initial_deployment:
        bootstrap_command = (
            *compose,
            "--profile",
            "deployment",
            "run",
            "--rm",
            "database-bootstrap",
        )
        if initial_bootstrap_verified:
            bootstrap_command = (
                *bootstrap_command,
                "python",
                "/app/ops/rehearse_database_bootstrap.py",
                "--mode",
                "resume",
            )
        return common + (
            RolloutStep(
                "release image pull",
                (*compose, "pull", "backend", "frontend", "alertmanager"),
                1_200,
            ),
            RolloutStep(
                (
                    "resumed initial database safety"
                    if initial_bootstrap_verified
                    else "initial database bootstrap rehearsal"
                ),
                bootstrap_command,
                900,
                (
                    None
                    if initial_bootstrap_verified
                    else "initial_bootstrap_verified"
                ),
            ),
            RolloutStep(
                "initial application activation",
                (
                    *compose,
                    "up",
                    "--detach",
                    "--no-build",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "frontend",
                ),
                300,
            ),
            RolloutStep(
                "initial database backup",
                (*compose, "--profile", "deployment", "run", "--rm", "backup-now"),
                900,
            ),
            RolloutStep(
                "initial backup restore drill",
                (*compose, "--profile", "deployment", "run", "--rm", "restore-drill"),
                900,
            ),
            RolloutStep(
                "initial database migration verification",
                (
                    *compose,
                    "--profile",
                    "deployment",
                    "run",
                    "--rm",
                    "migration-rehearsal",
                ),
                900,
            ),
            RolloutStep(
                "operational services activation",
                activation_command,
                300,
            ),
        ) + recovery_point_steps + monitoring_steps

    return common + (
        RolloutStep(
            "pre-rollout backup",
            (*compose, "--profile", "deployment", "run", "--rm", "backup-now"),
            900,
        ),
        RolloutStep(
            "pre-rollout restore drill",
            (*compose, "--profile", "deployment", "run", "--rm", "restore-drill"),
            900,
        ),
        RolloutStep(
            "release image pull",
            (*compose, "pull", "backend", "frontend", "alertmanager"),
            1_200,
        ),
        RolloutStep(
            "target database migration rehearsal",
            (
                *compose,
                "--profile",
                "deployment",
                "run",
                "--rm",
                "migration-rehearsal",
            ),
            900,
        ),
        RolloutStep(
            "service activation",
            activation_command,
            300,
        ),
    ) + recovery_point_steps + monitoring_steps


def _run_command(step: RolloutStep, environment: Mapping[str, str]) -> None:
    try:
        result = subprocess.run(
            list(step.command),
            cwd=_ROOT,
            env=dict(environment),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=step.timeout_seconds,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise DeploymentRolloutError(
            f"rollout step is unavailable: {step.name}"
        ) from exc
    if result.returncode != 0:
        raise DeploymentRolloutError(f"rollout step failed: {step.name}")


def _check_public_smoke(smoke_url: str, expected_public_url: str) -> list[str]:
    return run_smoke_checks(
        smoke_url,
        expected_public_url=expected_public_url,
    )


def _write_private_manifest(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a signed release, create a recovery-tested backup, deploy "
            "its exact images, and require a public smoke check."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--attestation-bundle", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="authorize only the exact previous release from the current receipt",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="resume only the exact signed release in the pending attempt journal",
    )
    parser.add_argument("--smoke-url")
    args = parser.parse_args(argv)
    try:
        result = verify_and_deploy_release(
            manifest_path=args.manifest,
            checksum_path=args.checksum,
            attestation_path=args.attestation_bundle,
            expected_tag=args.tag,
            environment=os.environ,
            state_directory=args.state_directory,
            rollback=args.rollback,
            resume=args.resume,
            smoke_url=args.smoke_url,
        )
    except (ReleaseBundleVerificationError, DeploymentRolloutError) as exc:
        print(f"deployment error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    operation = "rollback" if args.rollback else "deployment"
    print(
        f"{operation} completed "
        f"tag={result.tag} source={result.source_commit} "
        f"manifest_sha256={result.manifest_sha256}",
        flush=True,
    )


if __name__ == "__main__":
    main()
