"""Signed deployment bundle consumer tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
import subprocess

import pytest

from ops.create_release_manifest import create_release_manifest, write_release_manifest
from ops.verify_release_bundle import (
    ReleaseBundleVerificationError,
    render_deployment_environment,
    verify_release_bundle,
)


TAG = "v0.58.0"
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


def test_verified_bundle_uses_private_snapshots_and_emits_only_digest_images(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    observed: dict[str, object] = {}

    def verifier(
        manifest_snapshot: Path,
        attestation_snapshot: Path,
        payload: dict,
    ) -> None:
        observed["manifest"] = manifest_snapshot.read_bytes()
        observed["attestation"] = attestation_snapshot.read_bytes()
        observed["mode"] = stat_mode = manifest_snapshot.stat().st_mode & 0o777
        observed["attestation_mode"] = attestation_snapshot.stat().st_mode & 0o777
        observed["source_ref"] = payload["release"]["source_ref"]
        assert stat_mode == 0o600

    verified = verify_release_bundle(
        manifest_path=manifest,
        checksum_path=checksum,
        attestation_path=attestation,
        expected_tag=TAG,
        attestation_verifier=verifier,
    )

    assert observed == {
        "manifest": manifest.read_bytes(),
        "attestation": attestation.read_bytes(),
        "mode": 0o600,
        "attestation_mode": 0o600,
        "source_ref": f"refs/tags/{TAG}",
    }
    assert verified.tag == TAG
    assert verified.source_commit == SOURCE_COMMIT
    assert verified.manifest_bytes == manifest.read_bytes()
    assert render_deployment_environment(verified) == (
        f"BACKEND_IMAGE=ghcr.io/gr1gorii/ton-tracker-backend@{BACKEND_DIGEST}\n"
        f"FRONTEND_IMAGE=ghcr.io/gr1gorii/ton-tracker-frontend@{FRONTEND_DIGEST}\n"
    )


@pytest.mark.parametrize(
    "mutation, expected",
    [
        ("manifest", "checksum does not match"),
        ("checksum", "checksum is invalid"),
        ("attestation", "attestation is invalid"),
    ],
)
def test_bundle_rejects_tampered_assets(tmp_path, mutation, expected):
    manifest, checksum, attestation = _release_assets(tmp_path)
    if mutation == "manifest":
        manifest.write_bytes(manifest.read_bytes() + b" ")
    elif mutation == "checksum":
        checksum.write_text("0" * 64 + f" *{manifest.name}\n", encoding="ascii")

    def verifier(*_args) -> None:
        if mutation == "attestation":
            raise ReleaseBundleVerificationError("deployment attestation is invalid")

    with pytest.raises(ReleaseBundleVerificationError, match=expected):
        verify_release_bundle(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            attestation_verifier=verifier,
        )


def test_bundle_rejects_wrong_tag_and_noncanonical_asset_names(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    wrong_prefix = "gram-scope-v0.58.1-deployment"
    wrong_manifest = tmp_path / f"{wrong_prefix}.json"
    wrong_checksum = tmp_path / f"{wrong_prefix}.json.sha256"
    wrong_attestation = tmp_path / f"{wrong_prefix}.intoto.jsonl"
    wrong_manifest.write_bytes(manifest.read_bytes())
    wrong_checksum.write_text(
        f"{hashlib.sha256(wrong_manifest.read_bytes()).hexdigest()}  "
        f"{wrong_manifest.name}\n",
        encoding="ascii",
    )
    wrong_attestation.write_bytes(attestation.read_bytes())
    with pytest.raises(ReleaseBundleVerificationError, match="release tag"):
        verify_release_bundle(
            manifest_path=wrong_manifest,
            checksum_path=wrong_checksum,
            attestation_path=wrong_attestation,
            expected_tag="v0.58.1",
            attestation_verifier=lambda *_args: None,
        )

    renamed = tmp_path / "deployment.json"
    renamed.write_bytes(manifest.read_bytes())
    with pytest.raises(ReleaseBundleVerificationError, match="asset name"):
        verify_release_bundle(
            manifest_path=renamed,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            attestation_verifier=lambda *_args: None,
        )


@pytest.mark.parametrize("asset_index", [0, 1, 2])
def test_bundle_rejects_symlinked_assets(tmp_path, asset_index):
    assets = list(_release_assets(tmp_path))
    source = assets[asset_index]
    target = tmp_path / f"stored-{source.name}"
    source.rename(target)
    source.symlink_to(target)

    with pytest.raises(ReleaseBundleVerificationError, match="unavailable"):
        verify_release_bundle(
            manifest_path=assets[0],
            checksum_path=assets[1],
            attestation_path=assets[2],
            expected_tag=TAG,
            attestation_verifier=lambda *_args: None,
        )


def test_bundle_rejects_oversized_attestation_without_invoking_verifier(tmp_path):
    manifest, checksum, attestation = _release_assets(tmp_path)
    attestation.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    invoked = False

    def verifier(*_args) -> None:
        nonlocal invoked
        invoked = True

    with pytest.raises(ReleaseBundleVerificationError, match="size"):
        verify_release_bundle(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
            attestation_verifier=verifier,
        )
    assert invoked is False


def test_default_attestation_verifier_pins_repository_workflow_ref_and_commit(
    tmp_path,
    monkeypatch,
):
    manifest, checksum, attestation = _release_assets(tmp_path)
    observed: dict[str, object] = {}

    def run(command, **options):
        observed["command"] = command
        observed["manifest"] = Path(command[3]).read_bytes()
        observed["attestation"] = Path(command[5]).read_bytes()
        observed["options"] = options
        return subprocess.CompletedProcess(command, 0, stdout=b"verified", stderr=b"")

    monkeypatch.setattr("ops.verify_release_bundle.subprocess.run", run)
    verify_release_bundle(
        manifest_path=manifest,
        checksum_path=checksum,
        attestation_path=attestation,
        expected_tag=TAG,
    )

    command = observed["command"]
    assert command[:3] == ["gh", "attestation", "verify"]
    assert command[4] == "--bundle"
    assert command[6:] == [
        "--repo",
        "Gr1gorii/ton-tracker",
        "--signer-workflow",
        "github.com/Gr1gorii/ton-tracker/.github/workflows/publish-images.yml",
        "--source-ref",
        f"refs/tags/{TAG}",
        "--source-digest",
        SOURCE_COMMIT,
        "--deny-self-hosted-runners",
    ]
    assert observed["manifest"] == manifest.read_bytes()
    assert observed["attestation"] == attestation.read_bytes()
    options = observed["options"]
    assert options["stdin"] is subprocess.DEVNULL
    assert options["stdout"] is subprocess.PIPE
    assert options["stderr"] is subprocess.PIPE
    assert options["check"] is False
    assert options["timeout"] == 120


def test_attestation_failure_does_not_expose_verifier_output(tmp_path, monkeypatch):
    manifest, checksum, attestation = _release_assets(tmp_path)

    def run(command, **_options):
        return subprocess.CompletedProcess(
            command,
            1,
            stdout=b"untrusted provider output",
            stderr=b"private diagnostic payload",
        )

    monkeypatch.setattr("ops.verify_release_bundle.subprocess.run", run)
    with pytest.raises(
        ReleaseBundleVerificationError,
        match=r"^deployment attestation is invalid$",
    ) as exc_info:
        verify_release_bundle(
            manifest_path=manifest,
            checksum_path=checksum,
            attestation_path=attestation,
            expected_tag=TAG,
        )
    assert "provider" not in str(exc_info.value)
    assert "private" not in str(exc_info.value)
