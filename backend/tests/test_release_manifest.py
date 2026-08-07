"""Immutable production release manifest tests."""

import json

import pytest

from ops.create_release_manifest import (
    create_release_manifest,
    load_release_manifest,
    validate_release_manifest,
    write_release_manifest,
)


SOURCE_COMMIT = "1" * 40
BACKEND_DIGEST = "sha256:" + "a" * 64
FRONTEND_DIGEST = "sha256:" + "b" * 64


def test_release_manifest_is_digest_pinned_deterministic_and_deployable(tmp_path):
    payload = create_release_manifest(
        tag="v0.57.0",
        source_commit=SOURCE_COMMIT,
        backend_digest=BACKEND_DIGEST,
        frontend_digest=FRONTEND_DIGEST,
    )

    assert payload["schema"] == "gram_scope_deployment_manifest_v1"
    assert payload["release"] == {
        "tag": "v0.57.0",
        "source_commit": SOURCE_COMMIT,
        "source_ref": "refs/tags/v0.57.0",
    }
    for component, digest in (
        ("backend", BACKEND_DIGEST),
        ("frontend", FRONTEND_DIGEST),
    ):
        image = payload["images"][component]
        assert image["digest"] == digest
        assert image["reference"] == f"{image['repository']}@{digest}"
        assert image["platforms"] == ["linux/amd64", "linux/arm64"]
    assert payload["deployment_environment"] == {
        "BACKEND_IMAGE": payload["images"]["backend"]["reference"],
        "FRONTEND_IMAGE": payload["images"]["frontend"]["reference"],
    }
    assert payload["verification"] == {
        "signed_provenance_required": True,
        "signer_workflow": (
            "github.com/Gr1gorii/ton-tracker/.github/workflows/publish-images.yml"
        ),
        "source_digest": SOURCE_COMMIT,
        "self_hosted_runners_denied": True,
    }

    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    write_release_manifest(payload, first)
    write_release_manifest(payload, second)
    assert first.read_bytes() == second.read_bytes()
    assert json.loads(first.read_text(encoding="utf-8")) == payload
    assert first.read_bytes().endswith(b"\n")

    payload["images"]["backend"]["platforms"].append("linux/s390x")
    assert payload["images"]["frontend"]["platforms"] == [
        "linux/amd64",
        "linux/arm64",
    ]
    assert load_release_manifest(first) == json.loads(
        first.read_text(encoding="utf-8")
    )


def test_release_manifest_loader_rejects_noncanonical_and_oversized_files(tmp_path):
    payload = create_release_manifest(
        tag="v0.57.0",
        source_commit=SOURCE_COMMIT,
        backend_digest=BACKEND_DIGEST,
        frontend_digest=FRONTEND_DIGEST,
    )
    payload["unexpected"] = True
    with pytest.raises(ValueError, match="canonical contract"):
        validate_release_manifest(payload)

    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"{" + b" " * 65_536 + b"}")
    with pytest.raises(ValueError, match="size"):
        load_release_manifest(oversized)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tag", "v0.56"),
        ("tag", "v01.56.0"),
        ("source_commit", "A" * 40),
        ("source_commit", "1" * 39),
        ("backend_digest", "sha256:abcd"),
        ("frontend_digest", "sha512:" + "b" * 64),
    ],
)
def test_release_manifest_rejects_noncanonical_identity(field, value):
    arguments = {
        "tag": "v0.57.0",
        "source_commit": SOURCE_COMMIT,
        "backend_digest": BACKEND_DIGEST,
        "frontend_digest": FRONTEND_DIGEST,
    }
    arguments[field] = value
    with pytest.raises(ValueError):
        create_release_manifest(**arguments)
