"""Canonical acquisition manifest unit coverage."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from services.wallet_case_sync_manifests import (
    MANIFEST_CONTRACT_VERSION,
    build_wallet_case_sync_manifest,
    verify_wallet_case_sync_manifest,
)
from services.wallet_case_stream_checkpoints import (
    build_wallet_case_stream_checkpoints,
)
from wallet_case_schemas import (
    WalletCaseStreamCheckpointResponse,
    WalletCaseSyncManifestResponse,
)


START = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
END = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
DIGEST = "aB" * 32


def _manifest(**overrides):
    values = {
        "case_public_id": "00000000-0000-4000-8000-000000000001",
        "sync_public_id": "00000000-0000-4000-8000-000000000002",
        "network": "ton-mainnet",
        "data_mode": "real",
        "provider": "tonapi_wallet_activity_live",
        "sync_state": "succeeded",
        "snapshot_start": START,
        "snapshot_end": END,
        "acquisition_plan": {
            "version": 1,
            "mode": "incremental",
            "start_at": "2026-08-27T11:45:00Z",
            "end_at": "2026-08-27T12:00:00Z",
            "overlap_seconds": 900,
            "base_snapshot_public_id": "00000000-0000-4000-8000-000000000003",
        },
        "requested_surfaces": ["transactions"],
        "run_response": {
            "acquisition_streams": [
                {
                    "provider": "tonapi_wallet_activity_live",
                    "stream_key": "account_transactions",
                    "contract_version": "tonapi_account_transactions_v1",
                    "scope_kind": "bounded_time",
                    "requested_start": "2026-08-27T11:45:00Z",
                    "requested_end": "2026-08-27T12:00:00Z",
                    "query_filters": {"api_key": "must-not-leak"},
                    "sort_order": "desc",
                    "page_size": 100,
                    "page_cap": 20,
                    "completion_state": "complete",
                    "termination_reason": "window_exhausted",
                    "page_count": 1,
                    "pages_succeeded": 1,
                    "raw_count": 2,
                    "normalized_count": 2,
                    "duplicate_count": 0,
                    "first_cursor": "cursor-1",
                    "terminal_cursor": "cursor-2",
                    "bounds_verified": True,
                    "started_at": "2026-08-27T12:00:01Z",
                    "finished_at": "2026-08-27T12:00:02Z",
                    "error_code": None,
                    "error_message": "must-not-leak",
                    "pages": [
                        {
                            "page_index": 0,
                            "request_cursor": None,
                            "response_cursor": "cursor-2",
                            "requested_limit": 100,
                            "raw_count": 2,
                            "normalized_count": 2,
                            "duplicate_count": 0,
                            "min_logical_time": "10",
                            "max_logical_time": "20",
                            "min_timestamp": "2026-08-27T11:50:00Z",
                            "max_timestamp": "2026-08-27T11:55:00Z",
                            "response_digest": DIGEST,
                            "attempt_count": 1,
                            "error_code": None,
                            "error_message": "must-not-leak",
                            "fetched_at": "2026-08-27T12:00:02Z",
                            "raw": {"credential": "must-not-leak"},
                        }
                    ],
                }
            ]
        },
    }
    values.update(overrides)
    return build_wallet_case_sync_manifest(**values)


def test_manifest_is_canonical_content_addressed_and_provider_safe():
    manifest = _manifest()

    assert manifest.document["contract_version"] == MANIFEST_CONTRACT_VERSION
    assert manifest.public_id == f"smf_{manifest.content_hash_sha256}"
    assert len(manifest.content_hash_sha256) == 64
    assert manifest.stream_count == 1
    assert manifest.page_count == 1
    assert manifest.response_digest_count == 1
    assert manifest.canonical_json == json.dumps(
        manifest.document,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert manifest.document["streams"][0]["pages"][0][
        "response_digest_sha256"
    ] == DIGEST.lower()
    serialized = manifest.canonical_json
    assert "must-not-leak" not in serialized
    assert "query_filters" not in serialized
    assert "error_message" not in serialized
    assert '"raw"' not in serialized


def test_manifest_hash_is_stable_across_input_order_and_ignores_unknown_fields():
    first = _manifest(requested_surfaces=["transactions", "balances"])
    reversed_streams = dict(first.document)
    second = _manifest(
        requested_surfaces=["balances", "transactions", "balances"],
    )

    assert reversed_streams == first.document
    assert second.canonical_json == first.canonical_json
    assert second.public_id == first.public_id


def test_manifest_does_not_claim_invalid_response_digest():
    run_response = _manifest().document
    source = {
        "acquisition_streams": [
            {
                "provider": "tonapi",
                "stream_key": "events",
                "contract_version": "v1",
                "scope_kind": "bounded_time",
                "completion_state": "error",
                "pages": [
                    {"page_index": 0, "response_digest": "not-a-sha256"}
                ],
            }
        ]
    }
    manifest = _manifest(run_response=source)

    assert run_response["contract_version"] == MANIFEST_CONTRACT_VERSION
    assert manifest.response_digest_count == 0
    assert manifest.document["streams"][0]["pages"][0][
        "response_digest_sha256"
    ] is None


def test_manifest_verification_rejects_noncanonical_or_tampered_payload():
    manifest = _manifest()

    assert verify_wallet_case_sync_manifest(
        manifest.canonical_json,
        manifest.content_hash_sha256,
    ) == manifest.document
    with pytest.raises(ValueError, match="not canonical"):
        verify_wallet_case_sync_manifest(
            json.dumps(manifest.document, indent=2),
            manifest.content_hash_sha256,
        )
    with pytest.raises(ValueError, match="does not match"):
        verify_wallet_case_sync_manifest(
            manifest.canonical_json,
            "0" * 64,
        )


def test_resume_manifest_and_derived_checkpoint_match_public_schemas():
    manifest = _manifest(
        acquisition_plan={
            "version": 2,
            "mode": "resume",
            "start_at": "2026-08-26T12:00:00Z",
            "end_at": "2026-08-27T12:00:00Z",
            "overlap_seconds": 0,
            "base_snapshot_public_id": (
                "00000000-0000-4000-8000-000000000003"
            ),
            "source_checkpoint_public_id": f"scp_{'1' * 64}",
            "resume_stream_key": "account_transactions",
            "resume_cursor": "cursor-1",
            "resume_page_index": 2,
        }
    )
    manifest_response = {
        "manifest": {
            "public_id": manifest.public_id,
            "contract_version": MANIFEST_CONTRACT_VERSION,
            "content_hash_sha256": manifest.content_hash_sha256,
            "stream_count": manifest.stream_count,
            "page_count": manifest.page_count,
            "response_digest_count": manifest.response_digest_count,
            "created_at": "2026-08-27T12:00:03Z",
        },
        "document": manifest.document,
    }

    validated_manifest = WalletCaseSyncManifestResponse.model_validate(
        manifest_response
    )
    assert validated_manifest.document.acquisition_mode == "resume"

    checkpoint = build_wallet_case_stream_checkpoints(manifest)[0]
    validated_checkpoint = WalletCaseStreamCheckpointResponse.model_validate(
        {
            "checkpoint": {
                "public_id": checkpoint.public_id,
                "contract_version": checkpoint.document["contract_version"],
                "checkpoint_hash_sha256": checkpoint.checkpoint_hash_sha256,
                "provider": checkpoint.provider,
                "stream_key": checkpoint.stream_key,
                "provider_contract_version": (
                    checkpoint.provider_contract_version
                ),
                "source_sync_public_id": manifest.document["sync_public_id"],
                "resume_state": checkpoint.resume_state,
                "created_at": "2026-08-27T12:00:03Z",
            },
            "document": checkpoint.document,
        }
    )
    assert validated_checkpoint.document.acquisition_mode == "resume"
