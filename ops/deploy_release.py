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


@dataclass(frozen=True)
class DeploymentResult:
    tag: str
    source_commit: str
    manifest_sha256: str


CommandRunner = Callable[[RolloutStep, Mapping[str, str]], None]
SmokeChecker = Callable[[str, str], list[str]]


def run_guarded_rollout(
    bundle: VerifiedReleaseBundle,
    *,
    environment: Mapping[str, str],
    smoke_url: str | None = None,
    command_runner: CommandRunner | None = None,
    smoke_checker: SmokeChecker | None = None,
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

        for step in rollout_steps():
            runner(step, rollout_environment)

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
            result = run_guarded_rollout(
                bundle,
                environment=environment,
                smoke_url=smoke_url,
                command_runner=command_runner,
                smoke_checker=smoke_checker,
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


def rollout_steps() -> tuple[RolloutStep, ...]:
    compose = (
        "docker",
        "compose",
        "--file",
        str(_COMPOSE_FILE),
    )
    return (
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
            (*compose, "pull", "backend", "frontend"),
            1_200,
        ),
        RolloutStep(
            "service activation",
            (
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
            ),
            300,
        ),
    )


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
