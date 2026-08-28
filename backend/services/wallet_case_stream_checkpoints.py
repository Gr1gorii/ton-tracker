"""Canonical continuation records derived from immutable sync manifests."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import json
from typing import Any

from services.wallet_case_sync_manifests import BuiltWalletCaseSyncManifest


CHECKPOINT_CONTRACT_VERSION = "wallet_case_stream_checkpoint_v1"
_RESUMABLE_TERMINATIONS = {"page_cap_reached", "provider_error"}


@dataclass(frozen=True)
class BuiltWalletCaseStreamCheckpoint:
    document: dict[str, Any]
    canonical_json: str
    checkpoint_hash_sha256: str
    public_id: str
    provider: str
    stream_key: str
    provider_contract_version: str
    resume_state: str
    continuation_cursor: str | None
    continuation_page_index: int | None
    page_count: int
    pages_succeeded: int


def build_wallet_case_stream_checkpoints(
    manifest: BuiltWalletCaseSyncManifest,
) -> tuple[BuiltWalletCaseStreamCheckpoint, ...]:
    """Create one provider-safe continuation record per manifest stream."""
    document = manifest.document
    streams = document.get("streams")
    if not isinstance(streams, list):
        raise ValueError("Acquisition manifest streams are invalid.")
    return tuple(
        _build_checkpoint(manifest, stream)
        for stream in streams
        if isinstance(stream, dict)
    )


def verify_wallet_case_stream_checkpoint(
    checkpoint_json: str,
    expected_hash_sha256: str,
) -> dict[str, Any]:
    """Fail closed unless persisted checkpoint JSON is canonical and addressed."""
    try:
        document = json.loads(checkpoint_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Stored stream checkpoint JSON is invalid.") from exc
    if not isinstance(document, dict):
        raise ValueError("Stored stream checkpoint JSON is invalid.")
    canonical = _canonical_json(document)
    if canonical != checkpoint_json:
        raise ValueError("Stored stream checkpoint JSON is not canonical.")
    actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual_hash, expected_hash_sha256):
        raise ValueError("Stored stream checkpoint hash does not match its payload.")
    if document.get("contract_version") != CHECKPOINT_CONTRACT_VERSION:
        raise ValueError("Stored stream checkpoint contract is unsupported.")
    return document


def _build_checkpoint(
    manifest: BuiltWalletCaseSyncManifest,
    stream: dict[str, Any],
) -> BuiltWalletCaseStreamCheckpoint:
    provider = _required_text(stream.get("provider"), 64, "provider")
    stream_key = _required_text(stream.get("stream_key"), 40, "stream key")
    provider_contract = _required_text(
        stream.get("contract_version"),
        48,
        "provider contract version",
    )
    completion_state = _required_text(
        stream.get("completion_state"),
        24,
        "completion state",
    )
    termination_reason = _optional_text(stream.get("termination_reason"), 48)
    page_count = _nonnegative_int(stream.get("page_count"), "page count")
    pages_succeeded = _nonnegative_int(
        stream.get("pages_succeeded"),
        "pages succeeded",
    )
    if pages_succeeded > page_count:
        raise ValueError("Acquisition manifest page counts are invalid.")
    pages = stream.get("pages")
    if not isinstance(pages, list):
        raise ValueError("Acquisition manifest stream pages are invalid.")
    successful_pages = [
        page
        for page in pages
        if isinstance(page, dict) and page.get("error_code") is None
    ]
    if len(successful_pages) != pages_succeeded:
        raise ValueError("Acquisition manifest successful page count is invalid.")
    last_successful = successful_pages[-1] if successful_pages else None
    terminal_cursor = _optional_text(stream.get("terminal_cursor"), 128)
    last_response_cursor = (
        _optional_text(last_successful.get("response_cursor"), 128)
        if last_successful is not None
        else None
    )
    ready = (
        completion_state == "incomplete"
        and termination_reason in _RESUMABLE_TERMINATIONS
        and pages_succeeded > 0
        and terminal_cursor is not None
        and last_response_cursor == terminal_cursor
    )
    if completion_state == "complete":
        resume_state = "complete"
        resume_blocker = None
    elif ready:
        resume_state = "ready"
        resume_blocker = None
    else:
        resume_state = "blocked"
        resume_blocker = _resume_blocker(
            completion_state=completion_state,
            termination_reason=termination_reason,
            pages_succeeded=pages_succeeded,
            terminal_cursor=terminal_cursor,
            last_response_cursor=last_response_cursor,
        )
    continuation_cursor = terminal_cursor if ready else None
    continuation_page_index = (
        _nonnegative_int(last_successful.get("page_index"), "page index") + 1
        if ready and last_successful is not None
        else None
    )
    checkpoint_document = {
        "contract_version": CHECKPOINT_CONTRACT_VERSION,
        "case_public_id": _required_text(
            manifest.document.get("case_public_id"), 36, "case public ID"
        ),
        "source_sync_public_id": _required_text(
            manifest.document.get("sync_public_id"), 36, "sync public ID"
        ),
        "source_manifest_public_id": manifest.public_id,
        "source_manifest_hash_sha256": manifest.content_hash_sha256,
        "provider": provider,
        "stream_key": stream_key,
        "provider_contract_version": provider_contract,
        "acquisition_mode": _required_text(
            manifest.document.get("acquisition_mode"), 16, "acquisition mode"
        ),
        "requested_period": _period(stream.get("requested_period")),
        "sort_order": _optional_text(stream.get("sort_order"), 32),
        "page_size": _nonnegative_int(stream.get("page_size"), "page size"),
        "page_cap": _nonnegative_int(stream.get("page_cap"), "page cap"),
        "completion_state": completion_state,
        "termination_reason": termination_reason,
        "page_count": page_count,
        "pages_succeeded": pages_succeeded,
        "resume_state": resume_state,
        "resume_blocker": resume_blocker,
        "continuation_cursor": continuation_cursor,
        "continuation_page_index": continuation_page_index,
        "last_successful_page": _last_page_record(last_successful),
    }
    canonical = _canonical_json(checkpoint_document)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return BuiltWalletCaseStreamCheckpoint(
        document=checkpoint_document,
        canonical_json=canonical,
        checkpoint_hash_sha256=digest,
        public_id=f"scp_{digest}",
        provider=provider,
        stream_key=stream_key,
        provider_contract_version=provider_contract,
        resume_state=resume_state,
        continuation_cursor=continuation_cursor,
        continuation_page_index=continuation_page_index,
        page_count=page_count,
        pages_succeeded=pages_succeeded,
    )


def _last_page_record(page: dict[str, Any] | None) -> dict[str, Any] | None:
    if page is None:
        return None
    digest = _optional_text(page.get("response_digest_sha256"), 64)
    if digest is not None and (
        len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise ValueError("Acquisition manifest response digest is invalid.")
    return {
        "page_index": _nonnegative_int(page.get("page_index"), "page index"),
        "response_cursor": _optional_text(page.get("response_cursor"), 128),
        "response_digest_sha256": digest,
        "min_logical_time": _optional_text(page.get("min_logical_time"), 20),
        "max_logical_time": _optional_text(page.get("max_logical_time"), 20),
        "min_timestamp": _optional_text(page.get("min_timestamp"), 40),
        "max_timestamp": _optional_text(page.get("max_timestamp"), 40),
        "fetched_at": _optional_text(page.get("fetched_at"), 40),
    }


def _resume_blocker(
    *,
    completion_state: str,
    termination_reason: str | None,
    pages_succeeded: int,
    terminal_cursor: str | None,
    last_response_cursor: str | None,
) -> str:
    if completion_state == "preview_only":
        return "preview_only"
    if termination_reason == "legacy_unavailable":
        return "resolved_bounds_unavailable"
    if termination_reason == "provider_event_in_progress":
        return "provider_event_in_progress"
    if termination_reason == "protocol_error":
        return "provider_protocol_error"
    if pages_succeeded == 0:
        return "no_successful_page"
    if terminal_cursor is None:
        return "continuation_cursor_unavailable"
    if last_response_cursor != terminal_cursor:
        return "continuation_cursor_unverified"
    return "termination_not_resumable"


def _period(value: Any) -> dict[str, str | None]:
    if not isinstance(value, dict):
        raise ValueError("Acquisition manifest requested period is invalid.")
    return {
        "start_at": _optional_text(value.get("start_at"), 40),
        "end_at": _optional_text(value.get("end_at"), 40),
    }


def _required_text(value: Any, limit: int, label: str) -> str:
    result = _optional_text(value, limit)
    if result is None:
        raise ValueError(f"Acquisition manifest {label} is invalid.")
    return result


def _optional_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str) or not value or value != value.strip():
        return None
    return value if len(value) <= limit else None


def _nonnegative_int(value: Any, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"Acquisition manifest {label} is invalid.")
    return value


def _canonical_json(document: dict[str, Any]) -> str:
    return json.dumps(
        document,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


__all__ = [
    "BuiltWalletCaseStreamCheckpoint",
    "CHECKPOINT_CONTRACT_VERSION",
    "build_wallet_case_stream_checkpoints",
    "verify_wallet_case_stream_checkpoint",
]
