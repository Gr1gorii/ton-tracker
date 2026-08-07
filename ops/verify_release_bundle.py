"""Verify a signed GRAM Scope deployment bundle before production use."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile
from typing import Any

try:
    from .create_release_manifest import validate_release_manifest
except ImportError:  # pragma: no cover - direct script execution
    from create_release_manifest import validate_release_manifest


_REPOSITORY = "Gr1gorii/ton-tracker"
_SIGNER_WORKFLOW = (
    "github.com/Gr1gorii/ton-tracker/.github/workflows/publish-images.yml"
)
_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_MAX_MANIFEST_BYTES = 65_536
_MAX_CHECKSUM_BYTES = 512
_MAX_ATTESTATION_BYTES = 8 * 1024 * 1024


class ReleaseBundleVerificationError(ValueError):
    """A public release asset failed a bounded verification gate."""


@dataclass(frozen=True)
class VerifiedReleaseBundle:
    tag: str
    source_commit: str
    deployment_environment: Mapping[str, str]


AttestationVerifier = Callable[[Path, Path, Mapping[str, Any]], None]


def verify_release_bundle(
    *,
    manifest_path: Path,
    checksum_path: Path,
    attestation_path: Path,
    expected_tag: str,
    attestation_verifier: AttestationVerifier | None = None,
) -> VerifiedReleaseBundle:
    """Verify exact assets and return only their trusted deployment values."""
    if _TAG.fullmatch(expected_tag) is None:
        raise ReleaseBundleVerificationError("expected release tag is invalid")

    asset_prefix = f"gram-scope-{expected_tag}-deployment"
    if manifest_path.name != f"{asset_prefix}.json":
        raise ReleaseBundleVerificationError("deployment manifest asset name is invalid")
    if checksum_path.name != f"{asset_prefix}.json.sha256":
        raise ReleaseBundleVerificationError("deployment checksum asset name is invalid")
    if attestation_path.name != f"{asset_prefix}.intoto.jsonl":
        raise ReleaseBundleVerificationError("deployment attestation asset name is invalid")

    manifest_bytes = _read_regular_file(
        manifest_path,
        maximum_bytes=_MAX_MANIFEST_BYTES,
        label="deployment manifest",
    )
    checksum_bytes = _read_regular_file(
        checksum_path,
        maximum_bytes=_MAX_CHECKSUM_BYTES,
        label="deployment checksum",
    )
    attestation_bytes = _read_regular_file(
        attestation_path,
        maximum_bytes=_MAX_ATTESTATION_BYTES,
        label="deployment attestation",
    )

    manifest = _decode_manifest(manifest_bytes)
    if manifest["release"]["tag"] != expected_tag:
        raise ReleaseBundleVerificationError("deployment manifest release tag does not match")
    _verify_checksum(
        checksum_bytes,
        manifest_name=manifest_path.name,
        manifest_bytes=manifest_bytes,
    )

    verifier = attestation_verifier or _verify_github_attestation
    with tempfile.TemporaryDirectory(prefix="gram-scope-release-") as workspace:
        workspace_path = Path(workspace)
        snapshot_manifest = workspace_path / manifest_path.name
        snapshot_attestation = workspace_path / attestation_path.name
        _write_private_snapshot(snapshot_manifest, manifest_bytes)
        _write_private_snapshot(snapshot_attestation, attestation_bytes)
        verifier(snapshot_manifest, snapshot_attestation, manifest)

    environment = manifest["deployment_environment"]
    return VerifiedReleaseBundle(
        tag=expected_tag,
        source_commit=manifest["release"]["source_commit"],
        deployment_environment={
            "BACKEND_IMAGE": environment["BACKEND_IMAGE"],
            "FRONTEND_IMAGE": environment["FRONTEND_IMAGE"],
        },
    )


def render_deployment_environment(bundle: VerifiedReleaseBundle) -> str:
    """Render two canonical shell-compatible assignments after verification."""
    return "".join(
        f"{name}={bundle.deployment_environment[name]}\n"
        for name in ("BACKEND_IMAGE", "FRONTEND_IMAGE")
    )


def _decode_manifest(raw: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
        return validate_release_manifest(payload)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ReleaseBundleVerificationError(
            "deployment manifest contract is invalid"
        ) from exc


def _verify_checksum(
    raw: bytes,
    *,
    manifest_name: str,
    manifest_bytes: bytes,
) -> None:
    try:
        value = raw.decode("ascii")
    except UnicodeError as exc:
        raise ReleaseBundleVerificationError("deployment checksum is invalid") from exc
    pattern = re.compile(
        rf"^(?P<digest>[0-9a-f]{{64}})  {re.escape(manifest_name)}\n$"
    )
    match = pattern.fullmatch(value)
    if match is None:
        raise ReleaseBundleVerificationError("deployment checksum is invalid")
    expected = hashlib.sha256(manifest_bytes).hexdigest()
    if not hmac.compare_digest(match.group("digest"), expected):
        raise ReleaseBundleVerificationError("deployment checksum does not match")


def _read_regular_file(path: Path, *, maximum_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        before = os.lstat(path)
        if stat.S_ISLNK(before.st_mode):
            raise OSError
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ReleaseBundleVerificationError(f"{label} is unavailable") from exc
    try:
        opened = os.fstat(descriptor)
        current = os.lstat(path)
        identity = (opened.st_dev, opened.st_ino)
        if (
            not stat.S_ISREG(opened.st_mode)
            or identity != (before.st_dev, before.st_ino)
            or identity != (current.st_dev, current.st_ino)
        ):
            raise ReleaseBundleVerificationError(f"{label} must be a regular file")
        if opened.st_size < 2 or opened.st_size > maximum_bytes:
            raise ReleaseBundleVerificationError(f"{label} size is invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(maximum_bytes + 1)
        if len(raw) > maximum_bytes:
            raise ReleaseBundleVerificationError(f"{label} exceeds the size limit")
        return raw
    except OSError as exc:
        raise ReleaseBundleVerificationError(f"{label} is unavailable") from exc
    finally:
        os.close(descriptor)


def _write_private_snapshot(path: Path, raw: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def _verify_github_attestation(
    manifest_path: Path,
    attestation_path: Path,
    manifest: Mapping[str, Any],
) -> None:
    release = manifest["release"]
    command = [
        "gh",
        "attestation",
        "verify",
        str(manifest_path),
        "--bundle",
        str(attestation_path),
        "--repo",
        _REPOSITORY,
        "--signer-workflow",
        _SIGNER_WORKFLOW,
        "--source-ref",
        release["source_ref"],
        "--source-digest",
        release["source_commit"],
        "--deny-self-hosted-runners",
    ]
    try:
        result = subprocess.run(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=120,
            env={**os.environ, "GH_PAGER": "cat"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ReleaseBundleVerificationError(
            "deployment attestation verifier is unavailable"
        ) from exc
    if result.returncode != 0:
        raise ReleaseBundleVerificationError(
            "deployment attestation is invalid"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Verify a checksum-bound signed deployment bundle and print its "
            "digest-pinned image assignments."
        )
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checksum", type=Path, required=True)
    parser.add_argument("--attestation-bundle", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()
    try:
        verified = verify_release_bundle(
            manifest_path=args.manifest,
            checksum_path=args.checksum,
            attestation_path=args.attestation_bundle,
            expected_tag=args.tag,
        )
    except ReleaseBundleVerificationError as exc:
        print(f"release bundle error: {exc}", file=sys.stderr)
        raise SystemExit(2) from None
    sys.stdout.write(render_deployment_environment(verified))


if __name__ == "__main__":
    main()
