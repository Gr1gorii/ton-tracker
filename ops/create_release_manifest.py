"""Create a deterministic digest-pinned production deployment manifest."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import stat
from typing import Any


_REPOSITORY = "Gr1gorii/ton-tracker"
_SIGNER_WORKFLOW = (
    "github.com/Gr1gorii/ton-tracker/.github/workflows/publish-images.yml"
)
_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_SOURCE_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_PLATFORMS = ("linux/amd64", "linux/arm64")
_MAX_MANIFEST_BYTES = 65_536


def create_release_manifest(
    *,
    tag: str,
    source_commit: str,
    backend_digest: str,
    frontend_digest: str,
) -> dict[str, Any]:
    """Return the canonical production deployment contract for one release."""
    if _TAG.fullmatch(tag) is None:
        raise ValueError("release tag must be stable canonical semver")
    if _SOURCE_COMMIT.fullmatch(source_commit) is None:
        raise ValueError("source commit must be a lowercase 40-character digest")
    for name, digest in (
        ("backend digest", backend_digest),
        ("frontend digest", frontend_digest),
    ):
        if _DIGEST.fullmatch(digest) is None:
            raise ValueError(f"{name} must be a canonical sha256 digest")

    backend_repository = "ghcr.io/gr1gorii/ton-tracker-backend"
    frontend_repository = "ghcr.io/gr1gorii/ton-tracker-frontend"
    backend_reference = f"{backend_repository}@{backend_digest}"
    frontend_reference = f"{frontend_repository}@{frontend_digest}"
    return {
        "schema": "gram_scope_deployment_manifest_v1",
        "repository": _REPOSITORY,
        "release": {
            "tag": tag,
            "source_commit": source_commit,
            "source_ref": f"refs/tags/{tag}",
        },
        "images": {
            "backend": {
                "repository": backend_repository,
                "digest": backend_digest,
                "reference": backend_reference,
                "platforms": list(_PLATFORMS),
            },
            "frontend": {
                "repository": frontend_repository,
                "digest": frontend_digest,
                "reference": frontend_reference,
                "platforms": list(_PLATFORMS),
            },
        },
        "deployment_environment": {
            "BACKEND_IMAGE": backend_reference,
            "FRONTEND_IMAGE": frontend_reference,
        },
        "verification": {
            "signed_provenance_required": True,
            "signer_workflow": _SIGNER_WORKFLOW,
            "source_digest": source_commit,
            "self_hosted_runners_denied": True,
        },
    }


def write_release_manifest(payload: dict[str, Any], output: Path) -> None:
    """Write stable UTF-8 JSON without timestamps or machine-local fields."""
    output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )


def validate_release_manifest(payload: Any) -> dict[str, Any]:
    """Rebuild and compare a release manifest to reject partial or extra fields."""
    try:
        release = payload["release"]
        images = payload["images"]
        tag = release["tag"]
        source_commit = release["source_commit"]
        backend_digest = images["backend"]["digest"]
        frontend_digest = images["frontend"]["digest"]
    except (KeyError, TypeError):
        raise ValueError("deployment manifest structure is invalid") from None
    if not all(
        isinstance(value, str)
        for value in (tag, source_commit, backend_digest, frontend_digest)
    ):
        raise ValueError("deployment manifest identity fields must be strings")
    expected = create_release_manifest(
        tag=tag,
        source_commit=source_commit,
        backend_digest=backend_digest,
        frontend_digest=frontend_digest,
    )
    if payload != expected:
        raise ValueError("deployment manifest does not match its canonical contract")
    return expected


def load_release_manifest(path: Path) -> dict[str, Any]:
    """Load one bounded regular manifest without following a final symlink."""
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("deployment manifest is unavailable") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ValueError("deployment manifest must be a regular file")
        if metadata.st_size < 2 or metadata.st_size > _MAX_MANIFEST_BYTES:
            raise ValueError("deployment manifest size is invalid")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            raw = handle.read(_MAX_MANIFEST_BYTES + 1)
        if len(raw) > _MAX_MANIFEST_BYTES:
            raise ValueError("deployment manifest exceeds the size limit")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("deployment manifest JSON is invalid") from exc
    return validate_release_manifest(payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--backend-digest", required=True)
    parser.add_argument("--frontend-digest", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = create_release_manifest(
        tag=args.tag,
        source_commit=args.source_commit,
        backend_digest=args.backend_digest,
        frontend_digest=args.frontend_digest,
    )
    write_release_manifest(payload, args.output)


if __name__ == "__main__":
    main()
