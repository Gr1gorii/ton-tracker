"""Diagnostic multi-run wallet-history readiness assessment.

This module deliberately does not merge or deduplicate persisted activity and
never feeds PnL.  It only measures the evidence that would need to be made
canonical before multiple legacy ingestion runs could become a history or
cost-basis source.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy.orm import Session

from models import WalletIngestionRun
from services.ton_address_identity import parse_ton_address
from services.ton_event_action_identity import (
    TON_EVENT_ACTION_IDENTITY_VERSION,
    derive_ton_event_action_identity,
    unavailable_ton_event_action_identity,
)
from services.wallet_interval_coverage import build_wallet_interval_coverage
from services.wallet_activity_ingestion import wallet_ingestion_run_to_response

_SWAP_ORDINAL_KEYS = ("action_id", "action_index", "action_ordinal")
_TRANSACTION_IDENTITY_VERSION = "ton_account_tx_v1"
_TRANSACTION_IDENTITY_UNAVAILABLE = "unavailable"
_TRANSACTION_ACQUISITION_VERSION = "tonapi_account_transactions_v1"
_EVENT_ACQUISITION_VERSION = "tonapi_account_events_display_v1"
_PROVIDER_EVENT_ACTION_IDENTITY_TYPE = "provider_event_action_observation"
_TRANSACTION_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_SUBMITTED_TRANSACTION_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_LOGICAL_TIME_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_MAX_LOGICAL_TIME = 2**64 - 1
_MAX_EVENT_DATE = 2_114_380_800
_MAX_IDENTITY_GROUPS = 200
_WALLET_INGESTION_SURFACES = frozenset(
    {"transfers", "transactions", "swaps", "balances", "jettons"}
)
_UNAVAILABLE_WALLET_IDENTITY = {
    "status": "unavailable",
    "version": "unavailable",
    "network": "ton-unknown",
    "canonical_address": None,
    "workchain_id": None,
    "account_id_hex": None,
    "submitted_format": "unrecognized",
    "bounceable": None,
    "testnet_only": None,
    "is_account_existence_proof": False,
    "is_ownership_proof": False,
}


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validated_requested_surfaces(run: dict[str, Any]) -> list[str] | None:
    """Return the exact persisted surface list or fail closed on corruption."""
    value = run.get("requested_surfaces")
    if (
        not isinstance(value, list)
        or not value
        or any(type(surface) is not str for surface in value)
        or any(surface not in _WALLET_INGESTION_SURFACES for surface in value)
        or len(set(value)) != len(value)
    ):
        return None
    return list(value)


def _validated_surface_status(value: Any) -> list[str] | None:
    """Validate an unavailable/incomplete surface list; empty is meaningful."""
    if (
        not isinstance(value, list)
        or any(type(surface) is not str for surface in value)
        or any(surface not in _WALLET_INGESTION_SURFACES for surface in value)
        or len(set(value)) != len(value)
    ):
        return None
    return list(value)


def _safe_surface_list(value: Any) -> list[str]:
    """Normalize a surface field for display without iterating scalars/maps."""
    if not isinstance(value, list):
        return []
    return list(
        dict.fromkeys(
            surface
            for surface in value
            if type(surface) is str
            and surface in _WALLET_INGESTION_SURFACES
        )
    )


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _normalized_decimal(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _normalized_timestamp(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    if parsed is not None:
        return _isoformat(parsed)
    return str(value) if value else None


def _transaction_semantic_payload(transaction: dict[str, Any]) -> dict[str, Any]:
    return {
        "logical_time": transaction.get("logical_time"),
        "timestamp": _normalized_timestamp(transaction.get("timestamp")),
        "fee_ton": _normalized_decimal(transaction.get("fee_ton")),
        "success": transaction.get("success"),
        "provider": transaction.get("provider"),
        "source_status": transaction.get("source_status"),
    }


def _swap_semantic_payload(swap: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": _normalized_timestamp(swap.get("timestamp")),
        "dex": swap.get("dex"),
        "token_in": swap.get("token_in"),
        "token_in_address": swap.get("token_in_address"),
        "amount_in": _normalized_decimal(swap.get("amount_in")),
        "token_out": swap.get("token_out"),
        "token_out_address": swap.get("token_out_address"),
        "amount_out": _normalized_decimal(swap.get("amount_out")),
        "estimated_usd": _normalized_decimal(swap.get("estimated_usd")),
        "provider": swap.get("provider"),
        "source_status": swap.get("source_status"),
    }


def _transfer_semantic_payload(transfer: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": _normalized_timestamp(transfer.get("timestamp")),
        "asset": transfer.get("asset"),
        "amount": _normalized_decimal(transfer.get("amount")),
        "direction": transfer.get("direction"),
        "counterparty": transfer.get("counterparty"),
        "provider": transfer.get("provider"),
        "source_status": transfer.get("source_status"),
    }


def _activity_timestamps(run: dict[str, Any]) -> list[datetime]:
    timestamps: list[datetime] = []
    for collection in ("transfers", "transactions", "swaps"):
        for row in run.get(collection) or []:
            parsed = _parse_timestamp(row.get("timestamp"))
            if parsed is not None:
                timestamps.append(parsed)
    return timestamps


def _wallet_identity(run: dict[str, Any]) -> dict[str, Any]:
    identity = run.get("wallet_identity")
    if not isinstance(identity, dict):
        return dict(_UNAVAILABLE_WALLET_IDENTITY)
    return {**_UNAVAILABLE_WALLET_IDENTITY, **identity}


def _scoped_wallet_identity_key(run: dict[str, Any]) -> tuple[str, str] | None:
    identity = _wallet_identity(run)
    network = identity.get("network")
    canonical_address = identity.get("canonical_address")
    if identity.get("status") != "network_scoped":
        return None
    if identity.get("version") not in {
        "ton_std_address_v1",
        "ton_raw_address_v1",
    }:
        return None
    if network not in {"ton-mainnet", "ton-testnet"}:
        return None
    if not isinstance(canonical_address, str) or not canonical_address:
        return None
    parsed = parse_ton_address(canonical_address)
    if (
        parsed is None
        or parsed.submitted_format != "raw"
        or parsed.canonical_address != canonical_address
        or parsed.workchain_id != identity.get("workchain_id")
        or parsed.account_id_hex != identity.get("account_id_hex")
    ):
        return None
    return network, canonical_address


def _canonical_logical_time(value: Any) -> str | None:
    if not isinstance(value, str) or _LOGICAL_TIME_RE.fullmatch(value) is None:
        return None
    parsed = int(value, 10)
    if parsed <= 0 or parsed > _MAX_LOGICAL_TIME:
        return None
    return value


def _legacy_transaction_hash(transaction: dict[str, Any]) -> str | None:
    tx_hash = transaction.get("tx_hash")
    if not isinstance(tx_hash, str) or not tx_hash.strip():
        return None
    cleaned = tx_hash.strip()
    if _SUBMITTED_TRANSACTION_HASH_RE.fullmatch(cleaned) is not None:
        return cleaned.lower()
    return cleaned


def _is_explicit_unavailable_transaction_identity(identity: dict[str, Any]) -> bool:
    return (
        identity.get("status") == "unavailable"
        and identity.get("version") == _TRANSACTION_IDENTITY_UNAVAILABLE
        and identity.get("network") == "ton-unknown"
        and identity.get("account_canonical") is None
        and identity.get("logical_time_canonical") is None
        and identity.get("hash_canonical") is None
        and identity.get("key") is None
        and identity.get("is_deduplication_identity") is False
    )


def _validated_transaction_identity_key(
    run: dict[str, Any],
    transaction: dict[str, Any],
) -> str | None:
    """Return a persisted exact key only when the full contract is coherent."""
    identity = transaction.get("transaction_identity")
    if not isinstance(identity, dict):
        return None
    if identity.get("status") != "network_scoped":
        return None
    if identity.get("version") != _TRANSACTION_IDENTITY_VERSION:
        return None
    if identity.get("is_deduplication_identity") is not True:
        return None
    if run.get("data_mode") != "real":
        return None
    if transaction.get("provider") != "tonapi":
        return None
    if transaction.get("source_status") != "live":
        return None
    raw = transaction.get("raw")
    if not isinstance(raw, dict):
        return None
    if raw.get("provider") != "tonapi" or raw.get("surface") != "transactions":
        return None
    if raw.get("tx_hash") != transaction.get("tx_hash"):
        return None
    if raw.get("logical_time") != transaction.get("logical_time"):
        return None

    network = identity.get("network")
    account = identity.get("account_canonical")
    logical_time = identity.get("logical_time_canonical")
    tx_hash = identity.get("hash_canonical")
    if network not in {"ton-mainnet", "ton-testnet"}:
        return None
    wallet_key = _scoped_wallet_identity_key(run)
    if wallet_key != (network, account):
        return None

    parsed_account = parse_ton_address(account)
    if (
        parsed_account is None
        or parsed_account.submitted_format != "raw"
        or parsed_account.canonical_address != account
    ):
        return None
    if _canonical_logical_time(logical_time) != logical_time:
        return None
    if _canonical_logical_time(transaction.get("logical_time")) != logical_time:
        return None
    if not isinstance(tx_hash, str) or _TRANSACTION_HASH_RE.fullmatch(tx_hash) is None:
        return None
    submitted_hash = transaction.get("tx_hash")
    if (
        not isinstance(submitted_hash, str)
        or _SUBMITTED_TRANSACTION_HASH_RE.fullmatch(submitted_hash) is None
        or submitted_hash.lower() != tx_hash
    ):
        return None

    expected_key = "|".join(
        (
            _TRANSACTION_IDENTITY_VERSION,
            network,
            account,
            logical_time,
            tx_hash,
        )
    )
    if identity.get("key") != expected_key:
        return None
    return expected_key


def _transaction_identity_classification(
    run: dict[str, Any],
    transaction: dict[str, Any],
) -> tuple[str, str | None, bool]:
    """Classify exact persisted identity or a weak legacy diagnostic fallback."""
    identity = transaction.get("transaction_identity")
    exact_key = _validated_transaction_identity_key(run, transaction)
    if exact_key is not None:
        return "exact", exact_key, False

    invalid_contract = False
    if isinstance(identity, dict):
        invalid_contract = not _is_explicit_unavailable_transaction_identity(
            identity
        )
    elif identity is not None:
        invalid_contract = True

    legacy_hash = _legacy_transaction_hash(transaction)
    if legacy_hash is not None:
        return "weak", legacy_hash, invalid_contract
    return "unavailable", None, invalid_contract


def _is_explicit_unavailable_event_action_identity(
    identity: dict[str, Any],
) -> bool:
    """Accept only the complete, proof-safe unavailable public contract."""
    return identity == unavailable_ton_event_action_identity().to_public_dict()


def _validated_event_action_identity_key(
    run: dict[str, Any],
    row: dict[str, Any],
    *,
    surface: str,
) -> str | None:
    """Return a provider observation key only when every component recomputes.

    The identity is deliberately provider-scoped.  Validation proves that the
    persisted object, normalized row, raw provider coordinates, and run-wallet
    scope agree; it does not make the mutable TonAPI action authoritative.
    """
    identity = row.get("event_action_identity")
    if not isinstance(identity, dict):
        return None
    raw = row.get("raw")
    if not isinstance(raw, dict):
        return None

    wallet_identity = _wallet_identity(run)
    logical_time = (
        row.get("logical_time") if surface == "transfers" else raw.get("lt")
    )
    derived = derive_ton_event_action_identity(
        network=wallet_identity.get("network"),
        account_address_canonical=wallet_identity.get("canonical_address"),
        account_identity_status=wallet_identity.get("status"),
        account_identity_version=wallet_identity.get("version"),
        account_workchain_id=wallet_identity.get("workchain_id"),
        account_id_hex=wallet_identity.get("account_id_hex"),
        event_id=row.get("tx_hash"),
        logical_time=logical_time,
        action_index=raw.get("action_index"),
        action_type=raw.get("action_type"),
        surface=surface,
        data_mode=run.get("data_mode"),
        source_status=row.get("source_status"),
        provider=row.get("provider"),
        raw=raw,
    )
    if (
        derived.status != "provider_scoped"
        or derived.version != TON_EVENT_ACTION_IDENTITY_VERSION
        or derived.key is None
    ):
        return None

    # Exact mapping equality rejects omitted safety flags, stale components,
    # and invented extensions that could change the meaning of this contract.
    if identity != derived.to_public_dict():
        return None
    return derived.key


def _event_action_identity_classification(
    run: dict[str, Any],
    row: Any,
    *,
    surface: str,
) -> tuple[str, str | None, bool]:
    """Classify a strict provider observation or explicit legacy fallback."""
    if not isinstance(row, dict):
        return "unavailable", None, True
    identity = row.get("event_action_identity")
    provider_key = _validated_event_action_identity_key(
        run,
        row,
        surface=surface,
    )
    if provider_key is not None:
        return "provider_scoped", provider_key, False

    invalid_contract = False
    if isinstance(identity, dict):
        invalid_contract = not _is_explicit_unavailable_event_action_identity(
            identity
        )
    elif identity is not None:
        invalid_contract = True
    return "unavailable", None, invalid_contract


def _run_scope(run: dict[str, Any], target_run_id: int) -> dict[str, Any]:
    transfers = run.get("transfers") or []
    transactions = run.get("transactions") or []
    swaps = run.get("swaps") or []
    timestamps = _activity_timestamps(run)
    activity_count = len(transfers) + len(transactions) + len(swaps)
    requested_start = _parse_timestamp(run.get("_custom_start"))
    requested_end = _parse_timestamp(run.get("_custom_end"))
    outside_requested_bounds = 0
    if requested_start is not None and requested_end is not None:
        outside_requested_bounds = sum(
            1
            for timestamp in timestamps
            if timestamp < requested_start or timestamp >= requested_end
        )
    return {
        "run_id": run["run_id"],
        "is_target": run["run_id"] == target_run_id,
        "wallet_address": run["wallet_address"],
        "wallet_identity": _wallet_identity(run),
        "time_window": run["time_window"],
        "status": run["status"],
        "created_at": run.get("_created_at"),
        "requested_start": run.get("_custom_start"),
        "requested_end": run.get("_custom_end"),
        "requested_bounds_verified": False,
        "observed_activity_start": _isoformat(min(timestamps)) if timestamps else None,
        "observed_activity_end": _isoformat(max(timestamps)) if timestamps else None,
        "transfer_count": len(transfers),
        "transaction_count": len(transactions),
        "swap_count": len(swaps),
        "timestamped_activity_count": len(timestamps),
        "untimestamped_activity_count": activity_count - len(timestamps),
        "outside_requested_bounds_count": outside_requested_bounds,
        "requested_surfaces": _safe_surface_list(run.get("requested_surfaces")),
        "unavailable_surfaces": _safe_surface_list(run.get("unavailable_surfaces")),
    }


def _transaction_pagination_evidence(run: dict[str, Any]) -> dict[str, Any]:
    """Validate the narrow persisted transaction-stream completion contract."""
    run_id = run["run_id"]
    requested_surfaces = _validated_requested_surfaces(run)
    if requested_surfaces is None:
        return {
            "run_id": run_id,
            "state": "incomplete",
            "reason_codes": ["requested_surfaces_invalid"],
        }
    if "transactions" not in requested_surfaces:
        return {
            "run_id": run_id,
            "state": "not_requested",
            "reason_codes": ["surface_not_requested"],
        }

    streams = run.get("acquisition_streams")
    if not isinstance(streams, list):
        streams = []
    candidates = [
        stream
        for stream in streams
        if isinstance(stream, dict) and stream.get("stream_key") == "transactions"
    ]
    if len(candidates) != 1:
        return {
            "run_id": run_id,
            "state": "missing" if not candidates else "ambiguous",
            "reason_codes": [
                "stream_missing" if not candidates else "stream_ambiguous"
            ],
        }

    stream = candidates[0]
    base = {
        "run_id": run_id,
        "state": "incomplete",
        "completion_state": stream.get("completion_state"),
        "termination_reason": stream.get("termination_reason"),
        "bounds_verified": stream.get("bounds_verified") is True,
        "page_count": stream.get("page_count"),
    }
    start = _parse_timestamp(stream.get("requested_start"))
    end = _parse_timestamp(stream.get("requested_end"))
    if start is not None:
        base["interval_start"] = _isoformat(start)
    if end is not None:
        base["interval_end"] = _isoformat(end)
    query_filters = stream.get("query_filters")
    pages = stream.get("pages")
    if not isinstance(pages, list):
        pages = []
    page_count = stream.get("page_count")
    pages_succeeded = stream.get("pages_succeeded")
    pages_are_records = all(isinstance(page, dict) for page in pages)
    page_size = stream.get("page_size")
    page_cap = stream.get("page_cap")
    valid_query_filters = query_filters == {
        "endpoint": "account_transactions",
        "cursor": "before_lt",
        "limit": page_size,
        "interval": "[resolved_start,resolved_end)",
        "bounds_available": True,
    }
    valid_stream_contract = (
        stream.get("provider") == "tonapi"
        and stream.get("contract_version") == _TRANSACTION_ACQUISITION_VERSION
        and stream.get("scope_kind") == "bounded_interval"
        and stream.get("sort_order") == "logical_time_desc"
        and valid_query_filters
        and isinstance(page_size, int)
        and not isinstance(page_size, bool)
        and 1 <= page_size <= 1000
        and isinstance(page_cap, int)
        and not isinstance(page_cap, bool)
        and 1 <= page_cap <= 100
        and stream.get("first_cursor") is None
    )
    valid_page_envelope = (
        isinstance(page_count, int)
        and not isinstance(page_count, bool)
        and page_count >= 1
        and isinstance(page_cap, int)
        and page_count <= page_cap
        and page_count == len(pages)
        and isinstance(pages_succeeded, int)
        and not isinstance(pages_succeeded, bool)
        and pages_succeeded == page_count
        and pages_are_records
        and [page.get("page_index") for page in pages]
        == list(range(1, page_count + 1))
    )
    valid_page_rows = valid_stream_contract and valid_page_envelope and all(
        page.get("requested_limit") == page_size
        and page.get("error_code") is None
        and page.get("error_message") is None
        and isinstance(page.get("attempt_count"), int)
        and not isinstance(page.get("attempt_count"), bool)
        and page["attempt_count"] >= 1
        and _parse_timestamp(page.get("fetched_at")) is not None
        and isinstance(page.get("raw_count"), int)
        and not isinstance(page.get("raw_count"), bool)
        and 0 <= page["raw_count"] <= page_size
        and isinstance(page.get("normalized_count"), int)
        and not isinstance(page.get("normalized_count"), bool)
        and 0 <= page["normalized_count"] <= page["raw_count"]
        and isinstance(page.get("duplicate_count"), int)
        and not isinstance(page.get("duplicate_count"), bool)
        and 0 <= page["duplicate_count"] <= page["raw_count"]
        and page["normalized_count"] + page["duplicate_count"]
        <= page["raw_count"]
        and isinstance(page.get("response_digest"), str)
        and _TRANSACTION_HASH_RE.fullmatch(page["response_digest"])
        is not None
        for page in pages
    )
    valid_aggregate_counts = valid_page_rows and all(
        isinstance(stream.get(field), int)
        and not isinstance(stream.get(field), bool)
        and stream[field] >= 0
        for field in ("raw_count", "normalized_count", "duplicate_count")
    )
    if valid_aggregate_counts:
        valid_aggregate_counts = (
            stream["raw_count"] == sum(page["raw_count"] for page in pages)
            and stream["raw_count"] <= page_size * page_cap
            and stream["normalized_count"]
            == sum(page["normalized_count"] for page in pages)
            and stream["duplicate_count"]
            == sum(page["duplicate_count"] for page in pages)
            and stream["normalized_count"] + stream["duplicate_count"]
            <= stream["raw_count"]
        )

    valid_cursor_chain = valid_page_rows and pages[0].get("request_cursor") is None
    previous_response_cursor: str | None = None
    previous_oldest_timestamp: datetime | None = None
    if valid_cursor_chain:
        for index, page in enumerate(pages):
            request_cursor = page.get("request_cursor")
            if index > 0 and request_cursor != previous_response_cursor:
                valid_cursor_chain = False
                break
            if request_cursor is not None and _canonical_logical_time(
                request_cursor
            ) is None:
                valid_cursor_chain = False
                break

            raw_count = page["raw_count"]
            response_cursor = page.get("response_cursor")
            minimum_lt = page.get("min_logical_time")
            maximum_lt = page.get("max_logical_time")
            minimum_timestamp = _parse_timestamp(page.get("min_timestamp"))
            maximum_timestamp = _parse_timestamp(page.get("max_timestamp"))
            if raw_count == 0:
                if (
                    index != len(pages) - 1
                    or response_cursor is not None
                    or minimum_lt is not None
                    or maximum_lt is not None
                    or minimum_timestamp is not None
                    or maximum_timestamp is not None
                ):
                    valid_cursor_chain = False
                    break
            else:
                canonical_minimum = _canonical_logical_time(minimum_lt)
                canonical_maximum = _canonical_logical_time(maximum_lt)
                if (
                    canonical_minimum is None
                    or canonical_maximum is None
                    or int(canonical_minimum, 10) > int(canonical_maximum, 10)
                    or response_cursor != canonical_minimum
                    or minimum_timestamp is None
                    or maximum_timestamp is None
                    or minimum_timestamp > maximum_timestamp
                    or (
                        request_cursor is not None
                        and int(canonical_maximum, 10)
                        >= int(request_cursor, 10)
                    )
                    or (
                        previous_oldest_timestamp is not None
                        and maximum_timestamp > previous_oldest_timestamp
                    )
                ):
                    valid_cursor_chain = False
                    break
                previous_oldest_timestamp = minimum_timestamp
            previous_response_cursor = response_cursor

    termination_reason = stream.get("termination_reason")
    valid_termination = False
    if valid_page_rows:
        terminal_page = pages[-1]
        if termination_reason == "provider_terminal":
            valid_termination = (
                terminal_page.get("raw_count") == 0
                and terminal_page.get("response_cursor") is None
                and stream.get("terminal_cursor") is None
            )
        elif termination_reason == "requested_start_crossed":
            oldest_timestamp = _parse_timestamp(
                terminal_page.get("min_timestamp")
            )
            valid_termination = (
                oldest_timestamp is not None
                and start is not None
                and oldest_timestamp < start
                and stream.get("terminal_cursor")
                == terminal_page.get("response_cursor")
            )

    valid_pages = (
        valid_stream_contract
        and valid_page_rows
        and valid_aggregate_counts
        and valid_cursor_chain
        and valid_termination
        and all(
            page.get("min_logical_time") is None
            or _canonical_logical_time(page.get("min_logical_time")) is not None
            for page in pages
        )
    )
    transaction_rows = run.get("transactions")
    if not isinstance(transaction_rows, list):
        transaction_rows = []
    valid_transaction_rows = all(
        isinstance(row, dict)
        and row.get("provider") == "tonapi"
        and row.get("source_status") == "live"
        and (timestamp := _parse_timestamp(row.get("timestamp"))) is not None
        and start is not None
        and end is not None
        and start <= timestamp < end
        for row in transaction_rows
    )
    time_window = run.get("time_window")
    expected_rolling_windows = {
        "24h": timedelta(hours=24),
        "3d": timedelta(days=3),
        "7d": timedelta(days=7),
    }
    if time_window == "custom":
        valid_window_bounds = (
            _parse_timestamp(run.get("_custom_start")) == start
            and _parse_timestamp(run.get("_custom_end")) == end
        )
    elif time_window in expected_rolling_windows:
        valid_window_bounds = (
            start is not None
            and end is not None
            and end - start == expected_rolling_windows[time_window]
            and run.get("_custom_start") is None
            and run.get("_custom_end") is None
        )
    else:
        valid_window_bounds = False
    created_at = _parse_timestamp(run.get("_created_at"))
    valid_window_bounds = (
        valid_window_bounds
        and created_at is not None
        and end is not None
        and end <= created_at
    )
    started_at = _parse_timestamp(stream.get("started_at"))
    finished_at = _parse_timestamp(stream.get("finished_at"))
    fetched_at_values = [
        _parse_timestamp(page.get("fetched_at")) for page in pages
    ]
    valid_capture_times = (
        start is not None
        and end is not None
        and created_at is not None
        and started_at is not None
        and finished_at is not None
        and end <= started_at <= finished_at <= created_at
        and all(
            fetched_at is not None
            and started_at <= fetched_at <= finished_at
            for fetched_at in fetched_at_values
        )
        and all(
            previous is not None
            and current is not None
            and previous <= current
            for previous, current in zip(
                fetched_at_values, fetched_at_values[1:]
            )
        )
    )
    unavailable_surfaces = _validated_surface_status(
        run.get("unavailable_surfaces")
    )
    incomplete_surfaces = _validated_surface_status(
        run.get("incomplete_surfaces")
    )
    valid_run_scope = (
        run.get("data_mode") == "real"
        and run.get("status") in {"success", "partial"}
        and unavailable_surfaces is not None
        and "transactions" not in unavailable_surfaces
        and incomplete_surfaces is not None
        and "transactions" not in incomplete_surfaces
        and valid_transaction_rows
        and valid_aggregate_counts
        and len(transaction_rows) == stream.get("normalized_count")
        and valid_window_bounds
        and valid_capture_times
    )
    if (
        stream.get("completion_state") == "complete"
        and stream.get("bounds_verified") is True
        and termination_reason in {"provider_terminal", "requested_start_crossed"}
        and start is not None
        and end is not None
        and start < end
        and valid_pages
        and valid_run_scope
        and stream.get("error_code") is None
        and stream.get("error_message") is None
    ):
        return {
            **base,
            "state": "complete",
            "interval_start": _isoformat(start),
            "interval_end": _isoformat(end),
            "reason_codes": [],
        }
    reason_codes: list[str] = []
    if stream.get("completion_state") != "complete":
        reason_codes.append("completion_not_complete")
    if stream.get("bounds_verified") is not True:
        reason_codes.append("bounds_not_verified")
    if not valid_stream_contract:
        reason_codes.append("provider_contract_invalid")
    if not valid_query_filters:
        reason_codes.append("query_filters_invalid")
    if not valid_pages:
        reason_codes.append("page_evidence_invalid")
    if not valid_window_bounds:
        reason_codes.append("recorded_bounds_invalid")
    if not valid_capture_times:
        reason_codes.append("capture_times_invalid")
    if not valid_run_scope:
        reason_codes.append("run_scope_invalid")
    if stream.get("error_code") is not None or stream.get("error_message") is not None:
        reason_codes.append("stream_error_present")
    return {**base, "reason_codes": reason_codes}


def _event_action_row_identity(
    row: Any,
    *,
    surface: str,
    start: datetime,
    end: datetime,
) -> tuple[str, str] | None:
    """Validate one persisted display-action row and return its event key."""
    if not isinstance(row, dict):
        return None
    timestamp = _parse_timestamp(row.get("timestamp"))
    raw = row.get("raw")
    if (
        row.get("provider") != "tonapi"
        or row.get("source_status") != "live"
        or timestamp is None
        or not start <= timestamp < end
        or not isinstance(raw, dict)
        or raw.get("provider") != "tonapi"
        or raw.get("surface") != surface
    ):
        return None
    event_id = raw.get("event_id")
    logical_time = raw.get("lt")
    if (
        not isinstance(event_id, str)
        or _SUBMITTED_TRANSACTION_HASH_RE.fullmatch(event_id) is None
        or row.get("tx_hash") != event_id
        or _canonical_logical_time(logical_time) != logical_time
    ):
        return None
    if surface == "transfers" and row.get("logical_time") != logical_time:
        return None
    return logical_time, event_id.lower()


def _event_pagination_evidence(run: dict[str, Any]) -> dict[str, Any]:
    """Validate bounded TonAPI event evidence without promoting its actions."""
    run_id = run["run_id"]
    requested_surfaces = _validated_requested_surfaces(run)
    if requested_surfaces is None:
        return {
            "run_id": run_id,
            "state": "incomplete",
            "requested_surfaces": [],
            "provider_semantics": "display_only_actions",
            "reason_codes": ["requested_surfaces_invalid"],
        }
    requested_event_surfaces = [
        surface
        for surface in ("transfers", "swaps")
        if surface in requested_surfaces
    ]
    if not requested_event_surfaces:
        return {
            "run_id": run_id,
            "state": "not_requested",
            "reason_codes": ["surface_not_requested"],
        }

    streams = run.get("acquisition_streams")
    if not isinstance(streams, list):
        streams = []
    candidates = [
        stream
        for stream in streams
        if isinstance(stream, dict)
        and stream.get("stream_key") == "account_events"
    ]
    if len(candidates) != 1:
        return {
            "run_id": run_id,
            "state": "missing" if not candidates else "ambiguous",
            "requested_surfaces": requested_event_surfaces,
            "provider_semantics": "display_only_actions",
            "reason_codes": [
                "stream_missing" if not candidates else "stream_ambiguous"
            ],
        }

    stream = candidates[0]
    base = {
        "run_id": run_id,
        "state": "incomplete",
        "requested_surfaces": requested_event_surfaces,
        "provider_semantics": "display_only_actions",
        "completion_state": stream.get("completion_state"),
        "termination_reason": stream.get("termination_reason"),
        "bounds_verified": stream.get("bounds_verified") is True,
        "page_count": stream.get("page_count"),
    }
    start = _parse_timestamp(stream.get("requested_start"))
    end = _parse_timestamp(stream.get("requested_end"))
    if start is not None:
        base["interval_start"] = _isoformat(start)
    if end is not None:
        base["interval_end"] = _isoformat(end)
    pages = stream.get("pages")
    if not isinstance(pages, list):
        pages = []
    page_count = stream.get("page_count")
    pages_succeeded = stream.get("pages_succeeded")
    page_size = stream.get("page_size")
    page_cap = stream.get("page_cap")
    query_filters = stream.get("query_filters")
    expected_query_start = (
        math.floor(start.timestamp()) if start is not None else None
    )
    expected_query_end = math.ceil(end.timestamp()) if end is not None else None
    valid_query_filters = (
        isinstance(query_filters, dict)
        and set(query_filters) == {
            "endpoint",
            "cursor",
            "limit",
            "start_date",
            "end_date",
            "sort_order",
            "provider_semantics",
        }
        and query_filters.get("endpoint") == "account_events"
        and query_filters.get("cursor") == "before_lt"
        and query_filters.get("limit") == page_size
        and query_filters.get("sort_order") == "logical_time_desc"
        and query_filters.get("provider_semantics") == "display_only_actions"
        and isinstance(query_filters.get("start_date"), int)
        and not isinstance(query_filters.get("start_date"), bool)
        and isinstance(query_filters.get("end_date"), int)
        and not isinstance(query_filters.get("end_date"), bool)
        and query_filters.get("start_date") == expected_query_start
        and query_filters.get("end_date") == expected_query_end
        and 0 <= query_filters["start_date"] <= _MAX_EVENT_DATE
        and 0 <= query_filters["end_date"] <= _MAX_EVENT_DATE
    )
    valid_stream_contract = (
        stream.get("provider") == "tonapi"
        and stream.get("contract_version") == _EVENT_ACQUISITION_VERSION
        and stream.get("scope_kind") == "provider_display_events"
        and stream.get("sort_order") == "logical_time_desc"
        and isinstance(page_size, int)
        and not isinstance(page_size, bool)
        and 1 <= page_size <= 100
        and isinstance(page_cap, int)
        and not isinstance(page_cap, bool)
        and 1 <= page_cap <= 100
        and stream.get("first_cursor") is None
        and start is not None
        and end is not None
        and start < end
        and valid_query_filters
    )
    valid_page_envelope = (
        isinstance(page_count, int)
        and not isinstance(page_count, bool)
        and page_count >= 1
        and isinstance(page_cap, int)
        and page_count <= page_cap
        and page_count == len(pages)
        and isinstance(pages_succeeded, int)
        and not isinstance(pages_succeeded, bool)
        and pages_succeeded == page_count
        and all(isinstance(page, dict) for page in pages)
        and [page.get("page_index") for page in pages]
        == list(range(1, page_count + 1))
    )
    valid_page_rows = valid_stream_contract and valid_page_envelope and all(
        page.get("requested_limit") == page_size
        and page.get("error_code") is None
        and page.get("error_message") is None
        and isinstance(page.get("attempt_count"), int)
        and not isinstance(page.get("attempt_count"), bool)
        and page["attempt_count"] >= 1
        and _parse_timestamp(page.get("fetched_at")) is not None
        and isinstance(page.get("raw_count"), int)
        and not isinstance(page.get("raw_count"), bool)
        and 0 <= page["raw_count"] <= page_size
        and isinstance(page.get("normalized_count"), int)
        and not isinstance(page.get("normalized_count"), bool)
        and 0 <= page["normalized_count"] <= page["raw_count"]
        and isinstance(page.get("duplicate_count"), int)
        and not isinstance(page.get("duplicate_count"), bool)
        and 0 <= page["duplicate_count"] <= page["raw_count"]
        and page["normalized_count"] + page["duplicate_count"]
        <= page["raw_count"]
        and isinstance(page.get("response_digest"), str)
        and _TRANSACTION_HASH_RE.fullmatch(page["response_digest"])
        is not None
        for page in pages
    )
    valid_aggregate_counts = valid_page_rows and all(
        isinstance(stream.get(field), int)
        and not isinstance(stream.get(field), bool)
        and stream[field] >= 0
        for field in ("raw_count", "normalized_count", "duplicate_count")
    )
    if valid_aggregate_counts:
        valid_aggregate_counts = (
            stream["raw_count"] == sum(page["raw_count"] for page in pages)
            and stream["raw_count"] <= page_size * page_cap
            and stream["normalized_count"]
            == sum(page["normalized_count"] for page in pages)
            and stream["duplicate_count"]
            == sum(page["duplicate_count"] for page in pages)
            and stream["normalized_count"] + stream["duplicate_count"]
            <= stream["raw_count"]
        )

    valid_cursor_chain = (
        valid_page_rows and pages[0].get("request_cursor") is None
    )
    previous_response_cursor: str | None = None
    previous_minimum_lt: str | None = None
    previous_oldest_timestamp: datetime | None = None
    if valid_cursor_chain:
        for index, page in enumerate(pages):
            request_cursor = page.get("request_cursor")
            if index > 0 and request_cursor != previous_response_cursor:
                valid_cursor_chain = False
                break
            if request_cursor is not None and _canonical_logical_time(
                request_cursor
            ) is None:
                valid_cursor_chain = False
                break

            raw_count = page["raw_count"]
            response_cursor = page.get("response_cursor")
            minimum_lt = page.get("min_logical_time")
            maximum_lt = page.get("max_logical_time")
            minimum_timestamp = _parse_timestamp(page.get("min_timestamp"))
            maximum_timestamp = _parse_timestamp(page.get("max_timestamp"))
            if raw_count == 0:
                if (
                    index != len(pages) - 1
                    or response_cursor is not None
                    or minimum_lt is not None
                    or maximum_lt is not None
                    or minimum_timestamp is not None
                    or maximum_timestamp is not None
                    or page["normalized_count"] != 0
                    or page["duplicate_count"] != 0
                ):
                    valid_cursor_chain = False
                    break
            else:
                canonical_minimum = _canonical_logical_time(minimum_lt)
                canonical_maximum = _canonical_logical_time(maximum_lt)
                if (
                    canonical_minimum is None
                    or canonical_maximum is None
                    or int(canonical_minimum, 10) > int(canonical_maximum, 10)
                    or response_cursor != canonical_minimum
                    or minimum_timestamp is None
                    or maximum_timestamp is None
                    or minimum_timestamp > maximum_timestamp
                    or (
                        request_cursor is not None
                        and int(canonical_maximum, 10)
                        >= int(request_cursor, 10)
                    )
                    or (
                        previous_minimum_lt is not None
                        and int(canonical_maximum, 10)
                        >= int(previous_minimum_lt, 10)
                    )
                    or (
                        previous_oldest_timestamp is not None
                        and maximum_timestamp > previous_oldest_timestamp
                    )
                ):
                    valid_cursor_chain = False
                    break
                previous_minimum_lt = canonical_minimum
                previous_oldest_timestamp = minimum_timestamp
            previous_response_cursor = response_cursor

    termination_reason = stream.get("termination_reason")
    valid_termination = False
    if valid_page_rows:
        terminal_page = pages[-1]
        if termination_reason == "provider_terminal":
            valid_termination = (
                terminal_page.get("raw_count") == 0
                and terminal_page.get("response_cursor") is None
                and stream.get("terminal_cursor") is None
            )
        elif termination_reason == "requested_start_crossed":
            oldest_timestamp = _parse_timestamp(
                terminal_page.get("min_timestamp")
            )
            valid_termination = (
                oldest_timestamp is not None
                and start is not None
                and oldest_timestamp < start
                and stream.get("terminal_cursor")
                == terminal_page.get("response_cursor")
            )

    time_window = run.get("time_window")
    expected_rolling_windows = {
        "24h": timedelta(hours=24),
        "3d": timedelta(days=3),
        "7d": timedelta(days=7),
    }
    if time_window == "custom":
        valid_window_bounds = (
            _parse_timestamp(run.get("_custom_start")) == start
            and _parse_timestamp(run.get("_custom_end")) == end
        )
    elif time_window in expected_rolling_windows:
        valid_window_bounds = (
            start is not None
            and end is not None
            and end - start == expected_rolling_windows[time_window]
            and run.get("_custom_start") is None
            and run.get("_custom_end") is None
        )
    else:
        valid_window_bounds = False
    created_at = _parse_timestamp(run.get("_created_at"))
    valid_window_bounds = (
        valid_window_bounds
        and created_at is not None
        and end is not None
        and end <= created_at
    )

    valid_action_rows = start is not None and end is not None
    action_event_identities: set[tuple[str, str]] = set()
    if valid_action_rows:
        assert start is not None and end is not None
        for surface in requested_event_surfaces:
            rows = run.get(surface)
            if not isinstance(rows, list):
                valid_action_rows = False
                break
            for row in rows:
                identity = _event_action_row_identity(
                    row,
                    surface=surface,
                    start=start,
                    end=end,
                )
                if identity is None:
                    valid_action_rows = False
                    break
                action_event_identities.add(identity)
            if not valid_action_rows:
                break
    if valid_action_rows and valid_aggregate_counts:
        valid_action_rows = (
            len(action_event_identities) <= stream["normalized_count"]
        )

    unavailable_surfaces = _validated_surface_status(
        run.get("unavailable_surfaces")
    )
    incomplete_surfaces = _validated_surface_status(
        run.get("incomplete_surfaces")
    )
    valid_run_scope = (
        run.get("data_mode") == "real"
        and run.get("status") in {"success", "partial"}
        and unavailable_surfaces is not None
        and all(
            surface not in unavailable_surfaces
            for surface in requested_event_surfaces
        )
        and incomplete_surfaces is not None
        and all(
            surface in incomplete_surfaces
            for surface in requested_event_surfaces
        )
        and valid_action_rows
        and valid_window_bounds
    )
    started_at = _parse_timestamp(stream.get("started_at"))
    finished_at = _parse_timestamp(stream.get("finished_at"))
    fetched_at_values = [
        _parse_timestamp(page.get("fetched_at")) for page in pages
    ]
    valid_capture_times = (
        start is not None
        and end is not None
        and created_at is not None
        and started_at is not None
        and finished_at is not None
        and end <= started_at <= finished_at <= created_at
        and all(
            fetched_at is not None
            and started_at <= fetched_at <= finished_at
            for fetched_at in fetched_at_values
        )
        and all(
            previous is not None
            and current is not None
            and previous <= current
            for previous, current in zip(
                fetched_at_values, fetched_at_values[1:]
            )
        )
    )
    if (
        stream.get("completion_state") == "complete"
        and stream.get("bounds_verified") is True
        and termination_reason in {"provider_terminal", "requested_start_crossed"}
        and valid_stream_contract
        and valid_page_rows
        and valid_aggregate_counts
        and valid_cursor_chain
        and valid_termination
        and valid_run_scope
        and valid_capture_times
        and stream.get("error_code") is None
        and stream.get("error_message") is None
    ):
        return {
            **base,
            "state": "provider_stream_complete",
            "interval_start": _isoformat(start),
            "interval_end": _isoformat(end),
            "reason_codes": [],
        }
    reason_codes: list[str] = []
    if stream.get("completion_state") != "complete":
        reason_codes.append("completion_not_complete")
    if stream.get("bounds_verified") is not True:
        reason_codes.append("bounds_not_verified")
    if not valid_stream_contract:
        reason_codes.append("provider_contract_invalid")
    if not valid_query_filters:
        reason_codes.append("query_filters_invalid")
    if (
        not valid_page_rows
        or not valid_aggregate_counts
        or not valid_cursor_chain
        or not valid_termination
    ):
        reason_codes.append("page_evidence_invalid")
    if not valid_window_bounds:
        reason_codes.append("recorded_bounds_invalid")
    if not valid_capture_times:
        reason_codes.append("capture_times_invalid")
    if not valid_run_scope:
        reason_codes.append("run_scope_invalid")
    if stream.get("error_code") is not None or stream.get("error_message") is not None:
        reason_codes.append("stream_error_present")
    return {**base, "reason_codes": reason_codes}


def _identity_groups(
    observations: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str]],
    ]
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for (identity_type, identity), rows in observations.items():
        run_ids = sorted({row[0] for row in rows})
        if len(run_ids) < 2:
            continue
        payloads = {_fingerprint(row[1]) for row in rows}
        strengths = {row[2] for row in rows}
        if strengths == {"exact"}:
            identity_strength = "exact"
        elif strengths == {"provider_scoped"}:
            identity_strength = "provider_scoped"
        else:
            identity_strength = "weak"
        groups.append(
            {
                "identity": identity,
                "identity_type": identity_type,
                "identity_strength": identity_strength,
                "run_ids": run_ids,
                "observation_count": len(rows),
                "distinct_payload_count": len(payloads),
                "has_conflict": (
                    identity_strength in {"exact", "provider_scoped"}
                    and len(payloads) > 1
                ),
            }
        )
    return sorted(groups, key=lambda group: (group["identity_type"], group["identity"]))


def _transaction_groups(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    exact_observations: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str]],
    ] = defaultdict(list)
    hash_candidates: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str | None]],
    ] = defaultdict(list)
    for run in runs:
        for transaction in run.get("transactions") or []:
            strength, identity, _ = _transaction_identity_classification(
                run, transaction
            )
            payload = _transaction_semantic_payload(transaction)
            exact_key = identity if strength == "exact" else None
            if exact_key is not None:
                exact_observations[("account_transaction", exact_key)].append(
                    (run["run_id"], payload, "exact")
                )

            hash_candidate = _legacy_transaction_hash(transaction)
            if hash_candidate is not None:
                hash_candidates[("transaction_hash", hash_candidate)].append(
                    (run["run_id"], payload, exact_key)
                )

    candidate_observations: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str]],
    ] = {}
    for candidate_key, rows in hash_candidates.items():
        exact_keys = {row[2] for row in rows if row[2] is not None}
        all_rows_share_one_exact_key = (
            len(exact_keys) == 1 and all(row[2] is not None for row in rows)
        )
        if all_rows_share_one_exact_key:
            continue
        candidate_observations[candidate_key] = [
            (run_id, payload, "weak")
            for run_id, payload, _ in rows
        ]

    return sorted(
        [
            *_identity_groups(exact_observations),
            *_identity_groups(candidate_observations),
        ],
        key=lambda group: (group["identity_type"], group["identity"]),
    )


def _legacy_swap_identity(swap: dict[str, Any]) -> tuple[str, str, str]:
    raw = swap.get("raw") if isinstance(swap.get("raw"), dict) else {}
    provider = swap.get("provider")
    provider_key = provider.strip() if isinstance(provider, str) else "unknown"
    event_id = raw.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        event_id = swap.get("tx_hash")
    event_id = event_id.strip() if isinstance(event_id, str) else None

    if event_id:
        for key in _SWAP_ORDINAL_KEYS:
            ordinal = raw.get(key)
            if ordinal is not None and str(ordinal).strip():
                return (
                    f"{provider_key}:{event_id}:{key}:{str(ordinal).strip()}",
                    "event_action",
                    "weak",
                )
        return f"{provider_key}:{event_id}", "event_reference", "weak"

    signature = {
        "timestamp": _normalized_timestamp(swap.get("timestamp")),
        "dex": swap.get("dex"),
        "token_in": swap.get("token_in_address") or swap.get("token_in"),
        "amount_in": _normalized_decimal(swap.get("amount_in")),
        "token_out": swap.get("token_out_address") or swap.get("token_out"),
        "amount_out": _normalized_decimal(swap.get("amount_out")),
        "provider": provider_key,
    }
    return f"sha256:{_fingerprint(signature)}", "swap_fingerprint", "weak"


def _swap_identity(
    run: dict[str, Any],
    swap: dict[str, Any],
) -> tuple[str, str, str]:
    strength, identity, _ = _event_action_identity_classification(
        run,
        swap,
        surface="swaps",
    )
    if strength == "provider_scoped" and identity is not None:
        return (
            identity,
            _PROVIDER_EVENT_ACTION_IDENTITY_TYPE,
            "provider_scoped",
        )
    return _legacy_swap_identity(swap)


def _event_action_semantic_payload(
    row: dict[str, Any],
    *,
    surface: str,
) -> dict[str, Any]:
    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    semantic = (
        _transfer_semantic_payload(row)
        if surface == "transfers"
        else _swap_semantic_payload(row)
    )
    return {
        "surface": surface,
        "action_type": raw.get("action_type"),
        **semantic,
    }


def _event_action_groups(
    runs: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    observations: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str]],
    ] = defaultdict(list)
    for run in runs:
        for surface in ("transfers", "swaps"):
            for row in run.get(surface) or []:
                strength, identity, _ = _event_action_identity_classification(
                    run,
                    row,
                    surface=surface,
                )
                if strength != "provider_scoped" or identity is None:
                    continue
                observations[
                    (_PROVIDER_EVENT_ACTION_IDENTITY_TYPE, identity)
                ].append(
                    (
                        run["run_id"],
                        _event_action_semantic_payload(row, surface=surface),
                        "provider_scoped",
                    )
                )
    return _identity_groups(observations)


def _swap_groups(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    observations: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str]],
    ] = defaultdict(list)
    for run in runs:
        for swap in run.get("swaps") or []:
            identity, identity_type, strength = _swap_identity(run, swap)
            observations[(identity_type, identity)].append(
                (
                    run["run_id"],
                    _swap_semantic_payload(swap),
                    strength,
                )
            )
    return _identity_groups(observations)


def _coverage(
    runs: list[dict[str, Any]],
    transaction_groups: list[dict[str, Any]],
    swap_groups: list[dict[str, Any]],
    event_action_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    transfers = [row for run in runs for row in (run.get("transfers") or [])]
    transactions = [row for run in runs for row in (run.get("transactions") or [])]
    swaps = [row for run in runs for row in (run.get("swaps") or [])]
    timestamped = sum(len(_activity_timestamps(run)) for run in runs)

    transaction_identity_counts = {
        "exact": 0,
        "weak": 0,
        "unavailable": 0,
    }
    invalid_transaction_identity_contracts = 0
    for run in runs:
        for transaction in run.get("transactions") or []:
            strength, _, invalid_contract = _transaction_identity_classification(
                run, transaction
            )
            transaction_identity_counts[strength] += 1
            if invalid_contract:
                invalid_transaction_identity_contracts += 1

    if not transactions:
        transaction_identity_coverage_state = "not_observed"
    elif transaction_identity_counts["exact"] == len(transactions):
        transaction_identity_coverage_state = "complete"
    else:
        transaction_identity_coverage_state = "incomplete"

    event_action_identity_counts = {
        "provider_scoped": 0,
        "unavailable": 0,
    }
    invalid_event_action_identity_contracts = 0
    for run in runs:
        for surface in ("transfers", "swaps"):
            for row in run.get(surface) or []:
                strength, _, invalid_contract = (
                    _event_action_identity_classification(
                        run,
                        row,
                        surface=surface,
                    )
                )
                event_action_identity_counts[strength] += 1
                if invalid_contract:
                    invalid_event_action_identity_contracts += 1

    event_action_observations = len(transfers) + len(swaps)
    if not event_action_observations:
        event_action_identity_coverage_state = "not_observed"
    elif (
        event_action_identity_counts["provider_scoped"]
        == event_action_observations
        and invalid_event_action_identity_contracts == 0
    ):
        event_action_identity_coverage_state = "complete"
    else:
        event_action_identity_coverage_state = "incomplete"

    exact_swap_observations = 0
    provider_scoped_swap_observations = 0
    weak_swap_observations = 0
    non_ton_legs = 0
    addressed_non_ton_legs = 0
    fee_hash_matches = 0

    for run in runs:
        transaction_fees = {
            row.get("tx_hash"): row.get("fee_ton")
            for row in run.get("transactions") or []
            if row.get("tx_hash")
        }
        for swap in run.get("swaps") or []:
            _, _, strength = _swap_identity(run, swap)
            if strength == "exact":
                exact_swap_observations += 1
            elif strength == "provider_scoped":
                provider_scoped_swap_observations += 1
            else:
                weak_swap_observations += 1
            for token_key, address_key in (
                ("token_in", "token_in_address"),
                ("token_out", "token_out_address"),
            ):
                token = swap.get(token_key)
                if isinstance(token, str) and token.strip().upper() == "TON":
                    continue
                non_ton_legs += 1
                address = swap.get(address_key)
                if isinstance(address, str) and address.strip():
                    addressed_non_ton_legs += 1
            tx_hash = swap.get("tx_hash")
            if tx_hash in transaction_fees and transaction_fees[tx_hash] not in (
                None,
                "",
            ):
                fee_hash_matches += 1

    asset_coverage_state = (
        "not_observed"
        if non_ton_legs == 0
        else "complete"
        if addressed_non_ton_legs == non_ton_legs
        else "incomplete"
    )
    fee_coverage_state = (
        "not_observed"
        if not swaps
        else "complete"
        if fee_hash_matches == len(swaps)
        else "incomplete"
    )

    return {
        "activity_observations": len(transfers) + len(transactions) + len(swaps),
        "timestamped_activity_observations": timestamped,
        "transaction_observations": len(transactions),
        "transaction_observations_with_hash": sum(
            1
            for row in transactions
            if isinstance(row.get("tx_hash"), str) and row["tx_hash"].strip()
        ),
        "transaction_observations_with_exact_identity": (
            transaction_identity_counts["exact"]
        ),
        "transaction_observations_with_weak_identity": (
            transaction_identity_counts["weak"]
        ),
        "transaction_observations_with_unavailable_identity": (
            transaction_identity_counts["unavailable"]
        ),
        "transaction_observations_with_invalid_identity_contract": (
            invalid_transaction_identity_contracts
        ),
        "transaction_identity_coverage_state": transaction_identity_coverage_state,
        "overlapping_transaction_identity_groups": sum(
            1
            for group in transaction_groups
            if group["identity_strength"] == "exact"
        ),
        "conflicting_transaction_identity_groups": sum(
            1 for group in transaction_groups if group["has_conflict"]
        ),
        "event_action_observations": event_action_observations,
        "event_action_observations_with_provider_scoped_identity": (
            event_action_identity_counts["provider_scoped"]
        ),
        "event_action_observations_with_unavailable_identity": (
            event_action_identity_counts["unavailable"]
        ),
        "event_action_observations_with_invalid_identity_contract": (
            invalid_event_action_identity_contracts
        ),
        "event_action_identity_coverage_state": (
            event_action_identity_coverage_state
        ),
        "overlapping_provider_scoped_event_action_identity_groups": sum(
            1
            for group in event_action_groups
            if group["identity_strength"] == "provider_scoped"
        ),
        "conflicting_provider_scoped_event_action_identity_groups": sum(
            1
            for group in event_action_groups
            if group["identity_strength"] == "provider_scoped"
            and group["has_conflict"]
        ),
        "swap_observations": len(swaps),
        "swap_observations_with_exact_identity": exact_swap_observations,
        "swap_observations_with_provider_scoped_identity": (
            provider_scoped_swap_observations
        ),
        "swap_observations_with_weak_identity": weak_swap_observations,
        "overlapping_exact_swap_identity_groups": sum(
            1 for group in swap_groups if group["identity_strength"] == "exact"
        ),
        "overlapping_provider_scoped_swap_identity_groups": sum(
            1
            for group in swap_groups
            if group["identity_strength"] == "provider_scoped"
        ),
        "overlapping_weak_swap_identity_groups": sum(
            1 for group in swap_groups if group["identity_strength"] == "weak"
        ),
        "conflicting_swap_identity_groups": sum(
            1 for group in swap_groups if group["has_conflict"]
        ),
        "non_ton_swap_legs": non_ton_legs,
        "addressed_non_ton_swap_legs": addressed_non_ton_legs,
        "asset_address_coverage_state": asset_coverage_state,
        "fee_link_candidate_swaps": len(swaps),
        "same_run_fee_hash_match_candidates": fee_hash_matches,
        "fee_hash_match_coverage_state": fee_coverage_state,
        "fee_linkage_contract_verified": False,
    }


def _blocker(
    code: str,
    reason: str,
    *,
    run_ids: list[int] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "reason": reason,
        "run_ids": run_ids or [],
        "evidence": evidence or {},
    }


def _build_blockers(
    runs: list[dict[str, Any]],
    transaction_groups: list[dict[str, Any]],
    swap_groups: list[dict[str, Any]],
    event_action_groups: list[dict[str, Any]],
    coverage: dict[str, Any],
    transaction_pagination: list[dict[str, Any]],
    event_pagination: list[dict[str, Any]],
    bounded_interval_coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    run_ids = [run["run_id"] for run in runs]
    requested_transaction_pagination = [
        item
        for item in transaction_pagination
        if item["state"] != "not_requested"
    ]
    incomplete_transaction_run_ids = [
        item["run_id"]
        for item in requested_transaction_pagination
        if item["state"] != "complete"
    ]
    requested_event_pagination = [
        item for item in event_pagination if item["state"] != "not_requested"
    ]
    incomplete_event_run_ids = [
        item["run_id"]
        for item in requested_event_pagination
        if item["state"] != "provider_stream_complete"
    ]
    incomplete_event_action_identity_run_ids: list[int] = []
    invalid_event_action_identity_run_ids: list[int] = []
    provider_scoped_event_action_identity_run_ids: list[int] = []
    for run in runs:
        run_has_incomplete_identity = False
        run_has_invalid_identity = False
        run_has_provider_identity = False
        for surface in ("transfers", "swaps"):
            for row in run.get(surface) or []:
                strength, _, invalid_contract = (
                    _event_action_identity_classification(
                        run,
                        row,
                        surface=surface,
                    )
                )
                run_has_provider_identity |= strength == "provider_scoped"
                run_has_incomplete_identity |= strength != "provider_scoped"
                run_has_invalid_identity |= invalid_contract
        if run_has_incomplete_identity:
            incomplete_event_action_identity_run_ids.append(run["run_id"])
        if run_has_invalid_identity:
            invalid_event_action_identity_run_ids.append(run["run_id"])
        if run_has_provider_identity:
            provider_scoped_event_action_identity_run_ids.append(run["run_id"])
    blockers = [
        _blocker(
            "requested_bounds_unverified",
            "Only a validated bounded transaction stream can verify its recorded interval; selected runs do not verify requested bounds across every activity surface.",
            run_ids=run_ids,
        ),
        _blocker(
            "pagination_completeness_unverified",
            (
                "Bounded transaction and provider-display event streams can expose persisted pagination evidence, but derived transfer/swap actions are non-authoritative and balances and jettons do not provide equivalent complete acquisition evidence."
            ),
            run_ids=run_ids,
            evidence={
                "transaction_streams_by_run": transaction_pagination,
                "event_streams_by_run": event_pagination,
            },
        ),
        _blocker(
            "canonical_activity_identity_unavailable",
            "Provider-scoped event-action observations do not establish canonical transfer, swap, jetton-asset, or counterparty identity.",
            run_ids=run_ids,
        ),
        _blocker(
            "history_completeness_unverified",
            "An explicit run set is not proof of complete acquisition history before the target run.",
            run_ids=run_ids,
        ),
        _blocker(
            "deduplication_not_applied",
            "This report exposes overlap but deliberately does not merge or remove activity rows.",
            run_ids=run_ids,
        ),
        _blocker(
            "fee_linkage_contract_unverified",
            "A same-run string match between swap event references and transaction hashes is only a candidate, not a verified fee relationship.",
            run_ids=run_ids,
        ),
        _blocker(
            "asset_identity_contract_unverified",
            "Address presence alone does not provide a canonical network, workchain, and asset revision identity.",
            run_ids=run_ids,
        ),
    ]

    if incomplete_transaction_run_ids:
        blockers.append(
            _blocker(
                "transaction_pagination_evidence_incomplete",
                "At least one selected run that requested transactions lacks valid bounded completion evidence for its low-level transaction stream.",
                run_ids=incomplete_transaction_run_ids,
                evidence={
                    "transaction_streams_by_run": requested_transaction_pagination
                },
            )
        )

    if incomplete_event_run_ids:
        blockers.append(
            _blocker(
                "provider_event_pagination_evidence_incomplete",
                "At least one selected run that requested transfers or swaps lacks valid bounded completion evidence for its shared TonAPI provider-display event stream.",
                run_ids=incomplete_event_run_ids,
                evidence={"event_streams_by_run": requested_event_pagination},
            )
        )

    transaction_intervals = bounded_interval_coverage[
        "low_level_transactions"
    ]
    provider_event_intervals = bounded_interval_coverage[
        "provider_display_events"
    ]
    if transaction_intervals["excluded_run_ids"]:
        blockers.append(
            _blocker(
                "bounded_transaction_interval_scope_rejected",
                "Some selected runs cannot contribute a validated low-level transaction interval to the bounded union.",
                run_ids=transaction_intervals["excluded_run_ids"],
                evidence={
                    "run_evidence": [
                        item
                        for item in transaction_intervals["run_evidence"]
                        if item["classification"] == "excluded"
                    ]
                },
            )
        )
    if transaction_intervals["gap_intervals"]:
        blockers.append(
            _blocker(
                "bounded_transaction_interval_gaps",
                "Validated low-level transaction intervals contain internal gaps inside their selected span; time outside the span remains unknown.",
                run_ids=transaction_intervals["included_run_ids"],
                evidence={
                    "gap_intervals": transaction_intervals["gap_intervals"]
                },
            )
        )
    if transaction_intervals["overlap_intervals"]:
        blockers.append(
            _blocker(
                "bounded_transaction_interval_overlaps",
                "Validated low-level transaction intervals overlap, but activity rows have not been merged or deduplicated.",
                run_ids=transaction_intervals["included_run_ids"],
                evidence={
                    "overlap_intervals": transaction_intervals[
                        "overlap_intervals"
                    ]
                },
            )
        )
    if provider_event_intervals["excluded_run_ids"]:
        blockers.append(
            _blocker(
                "provider_display_interval_scope_rejected",
                "Some selected runs cannot contribute a validated provider-display event interval.",
                run_ids=provider_event_intervals["excluded_run_ids"],
                evidence={
                    "run_evidence": [
                        item
                        for item in provider_event_intervals["run_evidence"]
                        if item["classification"] == "excluded"
                    ]
                },
            )
        )
    if provider_event_intervals["gap_intervals"]:
        blockers.append(
            _blocker(
                "provider_display_interval_gaps",
                "Validated TonAPI provider-display event intervals contain internal gaps; this remains non-authoritative display coverage.",
                run_ids=provider_event_intervals["included_run_ids"],
                evidence={
                    "gap_intervals": provider_event_intervals["gap_intervals"]
                },
            )
        )

    if runs[0]["data_mode"] == "mock":
        blockers.append(
            _blocker(
                "mock_data_not_cost_basis",
                "Deterministic mock fixtures are not on-chain history and cannot establish cost basis.",
                run_ids=run_ids,
            )
        )

    unscoped_wallet_runs = [
        run["run_id"]
        for run in runs
        if _scoped_wallet_identity_key(run) is None
    ]
    if unscoped_wallet_runs:
        blockers.append(
            _blocker(
                "wallet_identity_unavailable",
                "At least one run wallet lacks a network-scoped canonical TON address; exact submitted strings are used only as a legacy diagnostic fallback.",
                run_ids=unscoped_wallet_runs,
            )
        )

    unsuccessful = [run["run_id"] for run in runs if run.get("status") != "success"]
    if unsuccessful:
        blockers.append(
            _blocker(
                "run_status_not_success",
                "Every candidate run must have a successful terminal status before canonical history work can begin.",
                run_ids=unsuccessful,
            )
        )

    unavailable = {
        str(run["run_id"]): surfaces
        for run in runs
        if (surfaces := _safe_surface_list(run.get("unavailable_surfaces")))
    }
    if unavailable:
        blockers.append(
            _blocker(
                "requested_surfaces_unavailable",
                "At least one run reports requested wallet-activity surfaces as unavailable.",
                run_ids=[int(run_id) for run_id in unavailable],
                evidence={"unavailable_surfaces_by_run": unavailable},
            )
        )

    activity_observations = coverage["activity_observations"]
    if activity_observations == 0:
        blockers.append(
            _blocker(
                "no_activity_observed",
                "The selected runs contain no transfer, transaction, or swap observations.",
                run_ids=run_ids,
            )
        )
    elif coverage["timestamped_activity_observations"] < activity_observations:
        blockers.append(
            _blocker(
                "activity_timestamps_incomplete",
                "Some activity observations have missing or invalid timestamps and cannot be placed in history order.",
                run_ids=run_ids,
                evidence={
                    "timestamped": coverage["timestamped_activity_observations"],
                    "total": activity_observations,
                },
            )
        )

    transaction_observations = coverage["transaction_observations"]
    exact_transaction_observations = coverage[
        "transaction_observations_with_exact_identity"
    ]
    weak_transaction_observations = coverage[
        "transaction_observations_with_weak_identity"
    ]
    unavailable_transaction_observations = coverage[
        "transaction_observations_with_unavailable_identity"
    ]
    invalid_transaction_contracts = coverage[
        "transaction_observations_with_invalid_identity_contract"
    ]
    if (
        transaction_observations > 0
        and exact_transaction_observations < transaction_observations
    ):
        blockers.append(
            _blocker(
                "transaction_identity_coverage_incomplete",
                "Some transaction observations lack a valid persisted, network-scoped TON account-transaction identity.",
                run_ids=run_ids,
                evidence={
                    "exact": exact_transaction_observations,
                    "weak": weak_transaction_observations,
                    "unavailable": unavailable_transaction_observations,
                    "total": transaction_observations,
                },
            )
        )
    if invalid_transaction_contracts:
        blockers.append(
            _blocker(
                "transaction_identity_contract_invalid",
                "At least one transaction claims an identity contract whose persisted components do not recompute to its stored key and row scope.",
                run_ids=run_ids,
                evidence={"invalid_observations": invalid_transaction_contracts},
            )
        )
    if weak_transaction_observations:
        blockers.append(
            _blocker(
                "legacy_transaction_identity_fallback",
                "At least one transaction is grouped only by its submitted tx_hash as weak legacy diagnostic evidence.",
                run_ids=run_ids,
                evidence={"weak_observations": weak_transaction_observations},
            )
        )

    if incomplete_event_action_identity_run_ids:
        blockers.append(
            _blocker(
                "event_action_identity_coverage_incomplete",
                "Some transfer or swap observations lack a valid persisted TonAPI provider-scoped event-action identity.",
                run_ids=incomplete_event_action_identity_run_ids,
                evidence={
                    "provider_scoped": coverage[
                        "event_action_observations_with_provider_scoped_identity"
                    ],
                    "unavailable": coverage[
                        "event_action_observations_with_unavailable_identity"
                    ],
                    "invalid": coverage[
                        "event_action_observations_with_invalid_identity_contract"
                    ],
                    "total": coverage["event_action_observations"],
                },
            )
        )

    if invalid_event_action_identity_run_ids:
        blockers.append(
            _blocker(
                "event_action_identity_contract_invalid",
                "At least one transfer or swap claims an event-action identity whose persisted object does not recompute from its run, row, and raw TonAPI coordinates.",
                run_ids=invalid_event_action_identity_run_ids,
                evidence={
                    "invalid_observations": coverage[
                        "event_action_observations_with_invalid_identity_contract"
                    ]
                },
            )
        )

    if provider_scoped_event_action_identity_run_ids:
        blockers.append(
            _blocker(
                "event_action_identity_non_authoritative",
                "A provider-scoped TonAPI event-action key identifies one mutable provider observation only; it is not authoritative activity, blockchain proof, ownership proof, or cost-basis evidence.",
                run_ids=provider_scoped_event_action_identity_run_ids,
                evidence={
                    "provider_scoped_observations": coverage[
                        "event_action_observations_with_provider_scoped_identity"
                    ],
                    "is_authoritative_activity_identity": False,
                    "eligible_for_cost_basis": False,
                    "used_by_pnl": False,
                },
            )
        )

    event_action_conflicts = [
        group["identity"]
        for group in event_action_groups
        if group["identity_strength"] == "provider_scoped"
        and group["has_conflict"]
    ]
    if event_action_conflicts:
        blockers.append(
            _blocker(
                "event_action_payload_conflicts",
                "The same provider-scoped event-action coordinate has differing normalized semantic payloads across runs.",
                run_ids=run_ids,
                evidence={
                    "identity_count": len(event_action_conflicts),
                    "identity_sample": event_action_conflicts[:50],
                },
            )
        )

    outside_bounds = {
        str(scope["run_id"]): scope["outside_requested_bounds_count"]
        for scope in (_run_scope(run, -1) for run in runs)
        if scope["outside_requested_bounds_count"] > 0
    }
    if outside_bounds:
        blockers.append(
            _blocker(
                "observations_outside_custom_bounds",
                "At least one custom-window run contains observed activity outside its stored request bounds.",
                run_ids=[int(run_id) for run_id in outside_bounds],
                evidence={"outside_observations_by_run": outside_bounds},
            )
        )

    exact_transaction_groups = [
        group
        for group in transaction_groups
        if group["identity_strength"] == "exact"
    ]
    if exact_transaction_groups:
        blockers.append(
            _blocker(
                "overlapping_transaction_history",
                "Exact persisted TON account-transaction identities overlap across runs, so concatenating rows would double count activity.",
                run_ids=run_ids,
                evidence={"identity_group_count": len(exact_transaction_groups)},
            )
        )
    transaction_conflicts = [
        group["identity"] for group in transaction_groups if group["has_conflict"]
    ]
    if transaction_conflicts:
        blockers.append(
            _blocker(
                "transaction_payload_conflicts",
                "The same exact persisted TON account-transaction identity has differing semantic payloads across runs.",
                run_ids=run_ids,
                evidence={
                    "identity_count": len(transaction_conflicts),
                    "identity_sample": transaction_conflicts[:50],
                },
            )
        )

    if coverage["swap_observations_with_weak_identity"]:
        blockers.append(
            _blocker(
                "weak_swap_identity",
                "Some legacy swap rows have only raw event references, action ordinals, or semantic fingerprints and lack the strict provider-scoped observation contract.",
                run_ids=run_ids,
                evidence={
                    "swap_observations": coverage["swap_observations"],
                    "provider_scoped_identity_observations": coverage[
                        "swap_observations_with_provider_scoped_identity"
                    ],
                    "weak_identity_observations": coverage[
                        "swap_observations_with_weak_identity"
                    ],
                },
            )
        )
    swap_conflicts = [group["identity"] for group in swap_groups if group["has_conflict"]]
    if swap_conflicts:
        blockers.append(
            _blocker(
                "swap_payload_conflicts",
                "A repeated swap identity has differing persisted payloads; weak event identities can also represent multiple actions.",
                run_ids=run_ids,
                evidence={
                    "identity_count": len(swap_conflicts),
                    "identity_sample": swap_conflicts[:50],
                },
            )
        )

    if coverage["addressed_non_ton_swap_legs"] < coverage["non_ton_swap_legs"]:
        blockers.append(
            _blocker(
                "asset_address_coverage_incomplete",
                "Some non-TON swap legs lack a jetton master address and cannot be canonically grouped by symbol alone.",
                run_ids=run_ids,
                evidence={
                    "addressed": coverage["addressed_non_ton_swap_legs"],
                    "total": coverage["non_ton_swap_legs"],
                },
            )
        )

    if coverage["same_run_fee_hash_match_candidates"] < coverage[
        "fee_link_candidate_swaps"
    ]:
        blockers.append(
            _blocker(
                "fee_linkage_incomplete",
                "Some swap rows do not have even a same-run hash-match candidate transaction with a recorded fee.",
                run_ids=run_ids,
                evidence={
                    "hash_match_candidates": coverage[
                        "same_run_fee_hash_match_candidates"
                    ],
                    "total": coverage["fee_link_candidate_swaps"],
                },
            )
        )

    return blockers


def assess_wallet_history_readiness(
    run_responses: list[dict[str, Any]],
    target_run_id: int,
) -> dict[str, Any]:
    """Pure diagnostic assessment over explicit persisted-run payloads."""
    if len(run_responses) < 2:
        raise ValueError("At least 2 distinct run_ids are required.")
    if len(run_responses) > 50:
        raise ValueError("At most 50 run_ids can be inspected at once.")

    run_ids = [run.get("run_id") for run in run_responses]
    if any(type(run_id) is not int or run_id < 1 for run_id in run_ids):
        raise ValueError("Every run must have a persisted positive integer run_id.")
    if type(target_run_id) is not int or target_run_id < 1:
        raise ValueError("target_run_id must be a positive integer.")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("run_ids must contain 2-50 distinct ids.")
    if target_run_id not in run_ids:
        raise ValueError("target_run_id must be included in run_ids.")

    target_run = next(
        run for run in run_responses if run.get("run_id") == target_run_id
    )
    wallet_addresses = {run.get("wallet_address") for run in run_responses}
    scoped_identity_keys = [
        _scoped_wallet_identity_key(run) for run in run_responses
    ]
    if all(key is not None for key in scoped_identity_keys):
        if len(set(scoped_identity_keys)) != 1:
            raise ValueError(
                "All history-readiness runs must resolve to the same network-scoped canonical wallet identity."
            )
    elif len(wallet_addresses) != 1 or not next(iter(wallet_addresses), None):
        raise ValueError(
            "Runs without complete canonical wallet identity must use the exact same wallet_address."
        )
    data_modes = {run.get("data_mode") for run in run_responses}
    if len(data_modes) != 1 or next(iter(data_modes), None) not in {"mock", "real"}:
        raise ValueError(
            "All history-readiness runs must use the same data_mode."
        )

    run_responses = sorted(run_responses, key=lambda run: run["run_id"])
    run_ids = [run["run_id"] for run in run_responses]
    transaction_groups = _transaction_groups(run_responses)
    swap_groups = _swap_groups(run_responses)
    event_action_groups = _event_action_groups(run_responses)
    coverage = _coverage(
        run_responses,
        transaction_groups,
        swap_groups,
        event_action_groups,
    )
    transaction_pagination = [
        _transaction_pagination_evidence(run) for run in run_responses
    ]
    event_pagination = [
        _event_pagination_evidence(run) for run in run_responses
    ]
    bounded_interval_coverage = build_wallet_interval_coverage(
        selected_run_ids=run_ids,
        transaction_evidence=transaction_pagination,
        event_evidence=event_pagination,
    )
    scopes = [_run_scope(run, target_run_id) for run in run_responses]
    all_timestamps = [
        timestamp for run in run_responses for timestamp in _activity_timestamps(run)
    ]

    return {
        "analysis_version": "wallet_history_readiness_v0.22.7",
        "target_run_id": target_run_id,
        "run_ids": run_ids,
        "wallet_address": target_run["wallet_address"],
        "wallet_identity": _wallet_identity(target_run),
        "data_mode": next(iter(data_modes)),
        "requested_bounds_verified": False,
        "observed_activity_start": (
            _isoformat(min(all_timestamps)) if all_timestamps else None
        ),
        "observed_activity_end": (
            _isoformat(max(all_timestamps)) if all_timestamps else None
        ),
        "runs": scopes,
        "transaction_identity_groups": transaction_groups[:_MAX_IDENTITY_GROUPS],
        "swap_identity_groups": swap_groups[:_MAX_IDENTITY_GROUPS],
        "event_action_identity_groups": event_action_groups[:_MAX_IDENTITY_GROUPS],
        "transaction_identity_groups_total": len(transaction_groups),
        "swap_identity_groups_total": len(swap_groups),
        "event_action_identity_groups_total": len(event_action_groups),
        "evidence_groups_truncated": (
            len(transaction_groups) > _MAX_IDENTITY_GROUPS
            or len(swap_groups) > _MAX_IDENTITY_GROUPS
            or len(event_action_groups) > _MAX_IDENTITY_GROUPS
        ),
        "coverage": coverage,
        "bounded_interval_coverage": bounded_interval_coverage,
        "blockers": _build_blockers(
            run_responses,
            transaction_groups,
            swap_groups,
            event_action_groups,
            coverage,
            transaction_pagination,
            event_pagination,
            bounded_interval_coverage,
        ),
        "history_complete": False,
        "deduplication_applied": False,
        "is_cost_basis": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "note": (
            "Diagnostic evidence only. This report does not merge or deduplicate "
            "activity, prove complete wallet history, establish cost basis, or "
            "change any PnL result."
        ),
    }


def build_wallet_history_readiness(
    run_ids: list[int],
    target_run_id: int,
    session: Session,
) -> dict[str, Any]:
    """Load explicit runs and delegate to the pure readiness assessment."""
    if any(type(run_id) is not int or run_id < 1 for run_id in run_ids):
        raise ValueError("Every run_id must be a positive integer.")
    if type(target_run_id) is not int or target_run_id < 1:
        raise ValueError("target_run_id must be a positive integer.")
    if len(run_ids) < 2:
        raise ValueError("At least 2 distinct run_ids are required.")
    if len(run_ids) > 50:
        raise ValueError("At most 50 run_ids can be inspected at once.")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("run_ids must contain 2-50 distinct ids.")
    if target_run_id not in run_ids:
        raise ValueError("target_run_id must be included in run_ids.")

    responses: list[dict[str, Any]] = []
    with session.no_autoflush:
        for run_id in sorted(run_ids):
            run = session.get(WalletIngestionRun, run_id)
            if run is None:
                raise LookupError(f"Wallet ingestion run {run_id} not found")
            response = wallet_ingestion_run_to_response(run)
            response["_created_at"] = _isoformat(run.created_at)
            response["_custom_start"] = _isoformat(run.custom_start)
            response["_custom_end"] = _isoformat(run.custom_end)
            responses.append(response)

    return assess_wallet_history_readiness(responses, target_run_id)
