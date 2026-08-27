"""Canonical, provider-safe acquisition manifests for Wallet Case syncs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import json
import re
from typing import Any


MANIFEST_CONTRACT_VERSION = "wallet_case_sync_manifest_v1"
_SHA256_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class BuiltWalletCaseSyncManifest:
    document: dict[str, Any]
    canonical_json: str
    content_hash_sha256: str
    public_id: str
    stream_count: int
    page_count: int
    response_digest_count: int


def build_wallet_case_sync_manifest(
    *,
    case_public_id: str,
    sync_public_id: str,
    network: str,
    data_mode: str,
    provider: str,
    sync_state: str,
    snapshot_start: datetime,
    snapshot_end: datetime,
    acquisition_plan: dict[str, Any],
    requested_surfaces: list[str] | tuple[str, ...],
    run_response: dict[str, Any],
) -> BuiltWalletCaseSyncManifest:
    """Build a stable manifest without raw payloads, credentials, or messages."""
    streams = sorted(
        (
            _stream_record(item)
            for item in _list(run_response.get("acquisition_streams"))
            if isinstance(item, dict)
        ),
        key=lambda item: (item["provider"], item["stream_key"]),
    )
    document = {
        "contract_version": MANIFEST_CONTRACT_VERSION,
        "case_public_id": _required_text(case_public_id, limit=36),
        "sync_public_id": _required_text(sync_public_id, limit=36),
        "network": _required_text(network, limit=16),
        "data_mode": _required_text(data_mode, limit=16),
        "provider": _required_text(provider, limit=64),
        "sync_state": _required_text(sync_state, limit=16),
        "snapshot_period": {
            "start_at": _isoformat(snapshot_start),
            "end_at": _isoformat(snapshot_end),
        },
        "acquisition_period": {
            "start_at": _optional_text(acquisition_plan.get("start_at"), 40),
            "end_at": _optional_text(acquisition_plan.get("end_at"), 40),
        },
        "acquisition_mode": _required_text(
            acquisition_plan.get("mode"),
            limit=16,
        ),
        "overlap_seconds": _nonnegative_int(
            acquisition_plan.get("overlap_seconds")
        ),
        "base_snapshot_public_id": _optional_text(
            acquisition_plan.get("base_snapshot_public_id"),
            36,
        ),
        "requested_surfaces": sorted(
            {
                value
                for item in requested_surfaces
                if (value := _optional_text(item, 32)) is not None
            }
        ),
        "streams": streams,
    }
    canonical = json.dumps(
        document,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    pages = [page for stream in streams for page in stream["pages"]]
    return BuiltWalletCaseSyncManifest(
        document=document,
        canonical_json=canonical,
        content_hash_sha256=digest,
        public_id=f"smf_{digest}",
        stream_count=len(streams),
        page_count=len(pages),
        response_digest_count=sum(
            page["response_digest_sha256"] is not None for page in pages
        ),
    )


def verify_wallet_case_sync_manifest(
    manifest_json: str,
    expected_hash_sha256: str,
) -> dict[str, Any]:
    """Fail closed unless persisted JSON is canonical and matches its address."""
    try:
        document = json.loads(manifest_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Stored acquisition manifest JSON is invalid.") from exc
    if not isinstance(document, dict):
        raise ValueError("Stored acquisition manifest JSON is invalid.")
    canonical = json.dumps(
        document,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    if canonical != manifest_json:
        raise ValueError("Stored acquisition manifest JSON is not canonical.")
    actual_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(actual_hash, expected_hash_sha256):
        raise ValueError("Stored acquisition manifest hash does not match its payload.")
    if document.get("contract_version") != MANIFEST_CONTRACT_VERSION:
        raise ValueError("Stored acquisition manifest contract is unsupported.")
    return document


def _stream_record(item: dict[str, Any]) -> dict[str, Any]:
    pages = sorted(
        (
            _page_record(page)
            for page in _list(item.get("pages"))
            if isinstance(page, dict)
        ),
        key=lambda page: page["page_index"],
    )
    return {
        "provider": _required_text(item.get("provider"), limit=64),
        "stream_key": _required_text(item.get("stream_key"), limit=40),
        "contract_version": _required_text(
            item.get("contract_version"),
            limit=48,
        ),
        "scope_kind": _required_text(item.get("scope_kind"), limit=24),
        "requested_period": {
            "start_at": _optional_text(item.get("requested_start"), 40),
            "end_at": _optional_text(item.get("requested_end"), 40),
        },
        "sort_order": _optional_text(item.get("sort_order"), 32),
        "page_size": _nonnegative_int(item.get("page_size")),
        "page_cap": _nonnegative_int(item.get("page_cap")),
        "completion_state": _required_text(
            item.get("completion_state"),
            limit=24,
        ),
        "termination_reason": _optional_text(
            item.get("termination_reason"),
            48,
        ),
        "page_count": _nonnegative_int(item.get("page_count")),
        "pages_succeeded": _nonnegative_int(item.get("pages_succeeded")),
        "raw_count": _nonnegative_int(item.get("raw_count")),
        "normalized_count": _nonnegative_int(item.get("normalized_count")),
        "duplicate_count": _nonnegative_int(item.get("duplicate_count")),
        "first_cursor": _optional_text(item.get("first_cursor"), 128),
        "terminal_cursor": _optional_text(item.get("terminal_cursor"), 128),
        "bounds_verified": item.get("bounds_verified") is True,
        "error_code": _optional_text(item.get("error_code"), 64),
        "started_at": _optional_text(item.get("started_at"), 40),
        "finished_at": _optional_text(item.get("finished_at"), 40),
        "pages": pages,
    }


def _page_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "page_index": _nonnegative_int(item.get("page_index")),
        "request_cursor": _optional_text(item.get("request_cursor"), 128),
        "response_cursor": _optional_text(item.get("response_cursor"), 128),
        "requested_limit": _nonnegative_int(item.get("requested_limit")),
        "raw_count": _nonnegative_int(item.get("raw_count")),
        "normalized_count": _nonnegative_int(item.get("normalized_count")),
        "duplicate_count": _nonnegative_int(item.get("duplicate_count")),
        "min_logical_time": _optional_text(item.get("min_logical_time"), 20),
        "max_logical_time": _optional_text(item.get("max_logical_time"), 20),
        "min_timestamp": _optional_text(item.get("min_timestamp"), 40),
        "max_timestamp": _optional_text(item.get("max_timestamp"), 40),
        "response_digest_sha256": _sha256(item.get("response_digest")),
        "attempt_count": _nonnegative_int(item.get("attempt_count")),
        "error_code": _optional_text(item.get("error_code"), 64),
        "fetched_at": _optional_text(item.get("fetched_at"), 40),
    }


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _required_text(value: Any, *, limit: int) -> str:
    return _optional_text(value, limit) or "unknown"


def _optional_text(value: Any, limit: int) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned[:limit] if cleaned else None


def _nonnegative_int(value: Any) -> int:
    if type(value) is not int:
        return 0
    return max(0, value)


def _sha256(value: Any) -> str | None:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        return None
    return value.lower()


def _isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "BuiltWalletCaseSyncManifest",
    "MANIFEST_CONTRACT_VERSION",
    "build_wallet_case_sync_manifest",
    "verify_wallet_case_sync_manifest",
]
