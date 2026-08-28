"""Canonical provider-stream checkpoint unit coverage."""

from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from services.wallet_case_stream_checkpoints import (
    CHECKPOINT_CONTRACT_VERSION,
    build_wallet_case_stream_checkpoints,
    verify_wallet_case_stream_checkpoint,
)
from services.wallet_case_sync_manifests import build_wallet_case_sync_manifest


START = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
END = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
DIGEST = "ab" * 32


def _manifest(
    *,
    completion_state: str = "incomplete",
    termination_reason: str = "page_cap_reached",
    terminal_cursor: str | None = "cursor-2",
    error_code: str | None = None,
    pages: list[dict] | None = None,
):
    if pages is None:
        pages = [
            {
                "page_index": 1,
                "request_cursor": None,
                "response_cursor": "cursor-2",
                "requested_limit": 100,
                "raw_count": 2,
                "normalized_count": 2,
                "duplicate_count": 0,
                "min_logical_time": "10",
                "max_logical_time": "20",
                "min_timestamp": "2026-08-28T11:50:00Z",
                "max_timestamp": "2026-08-28T11:55:00Z",
                "response_digest": DIGEST,
                "attempt_count": 1,
                "error_code": None,
                "error_message": "must-not-leak",
                "fetched_at": "2026-08-28T12:00:02Z",
                "raw": {"secret": "must-not-leak"},
            }
        ]
    stream = {
        "provider": "tonapi_wallet_activity_live",
        "stream_key": "account_transactions",
        "contract_version": "tonapi_account_transactions_v1",
        "scope_kind": "bounded_time",
        "requested_start": "2026-08-28T11:45:00Z",
        "requested_end": "2026-08-28T12:00:00Z",
        "sort_order": "desc",
        "page_size": 100,
        "page_cap": 1,
        "completion_state": completion_state,
        "termination_reason": termination_reason,
        "page_count": len(pages),
        "pages_succeeded": sum(page.get("error_code") is None for page in pages),
        "raw_count": 2,
        "normalized_count": 2,
        "duplicate_count": 0,
        "first_cursor": None,
        "terminal_cursor": terminal_cursor,
        "bounds_verified": completion_state == "complete",
        "started_at": "2026-08-28T12:00:01Z",
        "finished_at": "2026-08-28T12:00:02Z",
        "error_code": error_code,
        "error_message": "must-not-leak",
        "pages": pages,
    }
    return build_wallet_case_sync_manifest(
        case_public_id="00000000-0000-4000-8000-000000000001",
        sync_public_id="00000000-0000-4000-8000-000000000002",
        network="ton-mainnet",
        data_mode="real",
        provider="tonapi_wallet_activity_live",
        sync_state="partial",
        snapshot_start=START,
        snapshot_end=END,
        acquisition_plan={
            "version": 1,
            "mode": "incremental",
            "start_at": "2026-08-28T11:45:00Z",
            "end_at": "2026-08-28T12:00:00Z",
            "overlap_seconds": 900,
            "base_snapshot_public_id": "00000000-0000-4000-8000-000000000003",
        },
        requested_surfaces=["transactions"],
        run_response={"acquisition_streams": [stream]},
    )


def test_checkpoint_is_canonical_content_addressed_and_resume_ready():
    manifest = _manifest()

    (checkpoint,) = build_wallet_case_stream_checkpoints(manifest)

    assert checkpoint.document["contract_version"] == CHECKPOINT_CONTRACT_VERSION
    assert checkpoint.public_id == f"scp_{checkpoint.checkpoint_hash_sha256}"
    assert checkpoint.resume_state == "ready"
    assert checkpoint.continuation_cursor == "cursor-2"
    assert checkpoint.continuation_page_index == 2
    assert checkpoint.document["source_manifest_public_id"] == manifest.public_id
    assert checkpoint.document["last_successful_page"][
        "response_digest_sha256"
    ] == DIGEST
    assert checkpoint.canonical_json == json.dumps(
        checkpoint.document,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert "must-not-leak" not in checkpoint.canonical_json


def test_complete_stream_does_not_publish_a_continuation_cursor():
    (checkpoint,) = build_wallet_case_stream_checkpoints(
        _manifest(
            completion_state="complete",
            termination_reason="requested_start_crossed",
        )
    )

    assert checkpoint.resume_state == "complete"
    assert checkpoint.continuation_cursor is None
    assert checkpoint.continuation_page_index is None
    assert checkpoint.document["resume_blocker"] is None


@pytest.mark.parametrize(
    ("termination_reason", "terminal_cursor", "expected_blocker"),
    [
        ("protocol_error", "cursor-2", "provider_protocol_error"),
        ("provider_event_in_progress", "cursor-2", "provider_event_in_progress"),
        ("page_cap_reached", None, "continuation_cursor_unavailable"),
    ],
)
def test_checkpoint_blocks_unsafe_continuation(
    termination_reason,
    terminal_cursor,
    expected_blocker,
):
    (checkpoint,) = build_wallet_case_stream_checkpoints(
        _manifest(
            termination_reason=termination_reason,
            terminal_cursor=terminal_cursor,
        )
    )

    assert checkpoint.resume_state == "blocked"
    assert checkpoint.continuation_cursor is None
    assert checkpoint.document["resume_blocker"] == expected_blocker


def test_checkpoint_verification_rejects_noncanonical_or_tampered_payload():
    (checkpoint,) = build_wallet_case_stream_checkpoints(_manifest())

    assert verify_wallet_case_stream_checkpoint(
        checkpoint.canonical_json,
        checkpoint.checkpoint_hash_sha256,
    ) == checkpoint.document
    with pytest.raises(ValueError, match="not canonical"):
        verify_wallet_case_stream_checkpoint(
            json.dumps(checkpoint.document, indent=2),
            checkpoint.checkpoint_hash_sha256,
        )
    with pytest.raises(ValueError, match="does not match"):
        verify_wallet_case_stream_checkpoint(
            checkpoint.canonical_json,
            "0" * 64,
        )
