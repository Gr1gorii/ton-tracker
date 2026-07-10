"""Tests for the read-only multi-run history-readiness diagnostic."""

from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from models import (
    WalletBalanceSnapshot,
    WalletIngestionRun,
    WalletIngestionWarning,
    WalletSwap,
    WalletTransaction,
    WalletTransfer,
)
from schemas import WalletHistoryReadinessResponse
from services.wallet_history_readiness import assess_wallet_history_readiness
from services.ton_event_action_identity import (
    TON_EVENT_ACTION_IDENTITY_VERSION,
    unavailable_ton_event_action_identity,
)


BOUNCEABLE_WALLET = "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF"
NONBOUNCEABLE_WALLET = "UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA"
CANONICAL_WALLET = (
    "0:ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e"
)
TRANSACTION_HASH = "ab" * 32
TRANSACTION_LOGICAL_TIME = "46000000000001"
EVENT_ID = "cd" * 32
EVENT_LOGICAL_TIME = "46000000000002"


def _scoped_wallet_identity(
    *,
    network: str = "ton-mainnet",
    account: str = CANONICAL_WALLET,
) -> dict[str, Any]:
    return {
        "status": "network_scoped",
        "version": "ton_std_address_v1",
        "network": network,
        "canonical_address": account,
        "workchain_id": int(account.split(":", 1)[0]),
        "account_id_hex": account.split(":", 1)[1],
        "submitted_format": "user_friendly",
        "bounceable": True,
        "testnet_only": network == "ton-testnet",
        "is_account_existence_proof": False,
        "is_ownership_proof": False,
    }


def _exact_transaction_identity(
    *,
    tx_hash: str = TRANSACTION_HASH,
    logical_time: str = TRANSACTION_LOGICAL_TIME,
    network: str = "ton-mainnet",
    account: str = CANONICAL_WALLET,
) -> dict[str, Any]:
    canonical_hash = tx_hash.lower()
    key = "|".join(
        (
            "ton_account_tx_v1",
            network,
            account,
            logical_time,
            canonical_hash,
        )
    )
    return {
        "status": "network_scoped",
        "version": "ton_account_tx_v1",
        "network": network,
        "account_canonical": account,
        "logical_time_canonical": logical_time,
        "hash_canonical": canonical_hash,
        "key": key,
        "is_deduplication_identity": True,
    }


def _provider_event_action_identity(
    *,
    event_id: str = EVENT_ID,
    logical_time: str = EVENT_LOGICAL_TIME,
    action_index: int = 0,
    action_type: str = "TonTransfer",
    network: str = "ton-mainnet",
    account: str = CANONICAL_WALLET,
) -> dict[str, Any]:
    canonical_event_id = event_id.lower()
    key = "|".join(
        (
            TON_EVENT_ACTION_IDENTITY_VERSION,
            "tonapi",
            network,
            account,
            canonical_event_id,
            logical_time,
            str(action_index),
        )
    )
    return {
        "status": "provider_scoped",
        "version": TON_EVENT_ACTION_IDENTITY_VERSION,
        "provider": "tonapi",
        "network": network,
        "account_canonical": account,
        "event_id_canonical": canonical_event_id,
        "logical_time_canonical": logical_time,
        "action_index": action_index,
        "action_type": action_type,
        "key": key,
        "is_provider_observation_identity": True,
        "is_blockchain_proof_verified": False,
        "is_authoritative_activity_identity": False,
        "is_ownership_proof": False,
        "eligible_for_cost_basis": False,
        "deduplication_applied": False,
        "used_by_pnl": False,
    }


@pytest.fixture
def db_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    def override_get_session():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app), testing_session
    finally:
        app.dependency_overrides.clear()


def _transaction(
    tx_hash: str,
    *,
    timestamp: str | None = "2026-06-01T10:00:00Z",
    logical_time: str | None = "46000000000001",
    fee_ton: str | None = "0.0042",
    success: str = "success",
    provider: str = "tonapi",
    source_status: str = "live",
    raw: dict[str, Any] | None = None,
    transaction_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if transaction_identity is not None:
        raw = dict(raw or {})
        raw.setdefault("provider", "tonapi")
        raw.setdefault("surface", "transactions")
        raw.setdefault("tx_hash", tx_hash)
        raw.setdefault("logical_time", logical_time)
    record = {
        "tx_hash": tx_hash,
        "logical_time": logical_time,
        "timestamp": timestamp,
        "fee_ton": fee_ton,
        "success": success,
        "provider": provider,
        "source_status": source_status,
        "raw": raw,
    }
    if transaction_identity is not None:
        record["transaction_identity"] = transaction_identity
    return record


def _transfer(
    event_id: str | None,
    *,
    logical_time: str | None = EVENT_LOGICAL_TIME,
    timestamp: str | None = "2026-06-01T10:05:00Z",
    asset: str = "TON",
    amount: str | None = "1",
    direction: str = "out",
    counterparty: str | None = "EQcounterparty",
    provider: str = "tonapi",
    source_status: str = "live",
    raw: dict[str, Any] | None = None,
    event_action_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event_action_identity is not None:
        raw = dict(raw or {})
        raw.setdefault("provider", "tonapi")
        raw.setdefault("surface", "transfers")
        raw.setdefault("source", "tonapi")
        raw.setdefault("event_id", event_id)
        raw.setdefault("lt", logical_time)
        raw.setdefault("action_index", event_action_identity.get("action_index"))
        raw.setdefault("action_type", event_action_identity.get("action_type"))
    record = {
        "tx_hash": event_id,
        "logical_time": logical_time,
        "timestamp": timestamp,
        "asset": asset,
        "amount": amount,
        "direction": direction,
        "counterparty": counterparty,
        "provider": provider,
        "source_status": source_status,
        "raw": raw,
    }
    if event_action_identity is not None:
        record["event_action_identity"] = event_action_identity
    return record


def _swap(
    tx_hash: str | None,
    *,
    timestamp: str | None = "2026-06-01T10:05:00Z",
    dex: str | None = "STON.fi",
    token_in: str | None = "TON",
    token_in_address: str | None = None,
    amount_in: str | None = "1",
    token_out: str | None = "JET",
    token_out_address: str | None = "EQjetton",
    amount_out: str | None = "10",
    estimated_usd: str | None = None,
    provider: str = "tonapi",
    source_status: str = "live",
    raw: dict[str, Any] | None = None,
    logical_time: str = EVENT_LOGICAL_TIME,
    event_action_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event_action_identity is not None:
        raw = dict(raw or {})
        raw.setdefault("provider", "tonapi")
        raw.setdefault("surface", "swaps")
        raw.setdefault("source", "tonapi")
        raw.setdefault("event_id", tx_hash)
        raw.setdefault("lt", logical_time)
        raw.setdefault("action_index", event_action_identity.get("action_index"))
        raw.setdefault("action_type", event_action_identity.get("action_type"))
    record = {
        "tx_hash": tx_hash,
        "timestamp": timestamp,
        "dex": dex,
        "token_in": token_in,
        "token_in_address": token_in_address,
        "amount_in": amount_in,
        "token_out": token_out,
        "token_out_address": token_out_address,
        "amount_out": amount_out,
        "estimated_usd": estimated_usd,
        "provider": provider,
        "source_status": source_status,
        "raw": raw,
    }
    if event_action_identity is not None:
        record["event_action_identity"] = event_action_identity
    return record


def _run(
    run_id: int,
    *,
    wallet_address: str = "EQhistory",
    data_mode: str = "real",
    time_window: str = "24h",
    status: str = "success",
    transactions: list[dict[str, Any]] | None = None,
    swaps: list[dict[str, Any]] | None = None,
    transfers: list[dict[str, Any]] | None = None,
    custom_start: str | None = None,
    custom_end: str | None = None,
    created_at: str = "2026-06-02T00:00:02Z",
    requested_surfaces: list[str] | None = None,
    unavailable_surfaces: list[str] | None = None,
    incomplete_surfaces: list[str] | None = None,
    acquisition_streams: list[dict[str, Any]] | None = None,
    wallet_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = {
        "run_id": run_id,
        "wallet_address": wallet_address,
        "data_mode": data_mode,
        "time_window": time_window,
        "status": status,
        "transactions": list(transactions or []),
        "swaps": list(swaps or []),
        "transfers": list(transfers or []),
        "balances": [],
        "requested_surfaces": list(
            requested_surfaces or ["transfers", "transactions", "swaps"]
        ),
        "unavailable_surfaces": list(unavailable_surfaces or []),
        "incomplete_surfaces": list(incomplete_surfaces or []),
        "acquisition_streams": list(acquisition_streams or []),
        "_created_at": created_at,
        "_custom_start": custom_start,
        "_custom_end": custom_end,
    }
    if wallet_identity is not None:
        response["wallet_identity"] = wallet_identity
    return response


def _transaction_acquisition_stream(
    *,
    completion_state: str = "complete",
    termination_reason: str = "requested_start_crossed",
    bounds_verified: bool = True,
    digest: str = "cd" * 32,
) -> dict[str, Any]:
    return {
        "provider": "tonapi",
        "stream_key": "transactions",
        "contract_version": "tonapi_account_transactions_v1",
        "scope_kind": "bounded_interval",
        "requested_start": "2026-06-01T00:00:00Z",
        "requested_end": "2026-06-02T00:00:00Z",
        "query_filters": {
            "endpoint": "account_transactions",
            "cursor": "before_lt",
            "limit": 100,
            "interval": "[resolved_start,resolved_end)",
            "bounds_available": True,
        },
        "sort_order": "logical_time_desc",
        "page_size": 100,
        "page_cap": 10,
        "completion_state": completion_state,
        "termination_reason": termination_reason,
        "page_count": 1,
        "pages_succeeded": 1,
        "raw_count": 1,
        "normalized_count": 0,
        "duplicate_count": 0,
        "first_cursor": None,
        "terminal_cursor": "46000000000000",
        "bounds_verified": bounds_verified,
        "started_at": "2026-06-02T00:00:00Z",
        "finished_at": "2026-06-02T00:00:01Z",
        "error_code": None,
        "error_message": None,
        "pages": [
            {
                "page_index": 1,
                "request_cursor": None,
                "response_cursor": "46000000000000",
                "requested_limit": 100,
                "raw_count": 1,
                "normalized_count": 0,
                "duplicate_count": 0,
                "min_logical_time": "46000000000000",
                "max_logical_time": "46000000000000",
                "min_timestamp": "2026-05-31T23:59:00Z",
                "max_timestamp": "2026-05-31T23:59:00Z",
                "response_digest": digest,
                "attempt_count": 1,
                "error_code": None,
                "error_message": None,
                "fetched_at": "2026-06-02T00:00:00Z",
            }
        ],
    }


def _event_acquisition_stream(
    *,
    with_activity: bool = False,
    completion_state: str = "complete",
    bounds_verified: bool = True,
    digest: str = "de" * 32,
) -> dict[str, Any]:
    first_page = {
        "page_index": 1,
        "request_cursor": None,
        "response_cursor": (
            "46000000000002" if with_activity else "46000000000000"
        ),
        "requested_limit": 100,
        "raw_count": 1,
        "normalized_count": 1 if with_activity else 0,
        "duplicate_count": 0,
        "min_logical_time": (
            "46000000000002" if with_activity else "46000000000000"
        ),
        "max_logical_time": (
            "46000000000002" if with_activity else "46000000000000"
        ),
        "min_timestamp": (
            "2026-06-01T12:00:00Z"
            if with_activity
            else "2026-05-31T23:59:00Z"
        ),
        "max_timestamp": (
            "2026-06-01T12:00:00Z"
            if with_activity
            else "2026-05-31T23:59:00Z"
        ),
        "response_digest": digest,
        "attempt_count": 1,
        "error_code": None,
        "error_message": None,
        "fetched_at": "2026-06-02T00:00:00Z",
    }
    pages = [first_page]
    termination_reason = "requested_start_crossed"
    terminal_cursor: str | None = first_page["response_cursor"]
    if with_activity:
        pages.append(
            {
                "page_index": 2,
                "request_cursor": first_page["response_cursor"],
                "response_cursor": None,
                "requested_limit": 100,
                "raw_count": 0,
                "normalized_count": 0,
                "duplicate_count": 0,
                "min_logical_time": None,
                "max_logical_time": None,
                "min_timestamp": None,
                "max_timestamp": None,
                "response_digest": "ef" * 32,
                "attempt_count": 1,
                "error_code": None,
                "error_message": None,
                "fetched_at": "2026-06-02T00:00:01Z",
            }
        )
        termination_reason = "provider_terminal"
        terminal_cursor = None
    return {
        "provider": "tonapi",
        "stream_key": "account_events",
        "contract_version": "tonapi_account_events_display_v1",
        "scope_kind": "provider_display_events",
        "requested_start": "2026-06-01T00:00:00Z",
        "requested_end": "2026-06-02T00:00:00Z",
        "query_filters": {
            "endpoint": "account_events",
            "cursor": "before_lt",
            "limit": 100,
            "start_date": 1780272000,
            "end_date": 1780358400,
            "sort_order": "logical_time_desc",
            "provider_semantics": "display_only_actions",
        },
        "sort_order": "logical_time_desc",
        "page_size": 100,
        "page_cap": 10,
        "completion_state": completion_state,
        "termination_reason": termination_reason,
        "page_count": len(pages),
        "pages_succeeded": len(pages),
        "raw_count": 1,
        "normalized_count": 1 if with_activity else 0,
        "duplicate_count": 0,
        "first_cursor": None,
        "terminal_cursor": terminal_cursor,
        "bounds_verified": bounds_verified,
        "started_at": "2026-06-02T00:00:00Z",
        "finished_at": "2026-06-02T00:00:01Z",
        "error_code": None,
        "error_message": None,
        "pages": pages,
    }


def _retime_transaction_stream(start: str, end: str) -> dict[str, Any]:
    stream = copy.deepcopy(_transaction_acquisition_stream())
    start_at = _parse_datetime(start)
    end_at = _parse_datetime(end)
    assert start_at is not None and end_at is not None
    before_start = (start_at - timedelta(minutes=1)).isoformat().replace(
        "+00:00", "Z"
    )
    started_at = end_at.isoformat().replace("+00:00", "Z")
    finished_at = (end_at + timedelta(seconds=1)).isoformat().replace(
        "+00:00", "Z"
    )
    stream["requested_start"] = start
    stream["requested_end"] = end
    stream["started_at"] = started_at
    stream["finished_at"] = finished_at
    stream["pages"][0]["min_timestamp"] = before_start
    stream["pages"][0]["max_timestamp"] = before_start
    stream["pages"][0]["fetched_at"] = started_at
    return stream


def _retime_event_stream(start: str, end: str) -> dict[str, Any]:
    stream = copy.deepcopy(_event_acquisition_stream())
    start_at = _parse_datetime(start)
    end_at = _parse_datetime(end)
    assert start_at is not None and end_at is not None
    before_start = (start_at - timedelta(minutes=1)).isoformat().replace(
        "+00:00", "Z"
    )
    started_at = end_at.isoformat().replace("+00:00", "Z")
    finished_at = (end_at + timedelta(seconds=1)).isoformat().replace(
        "+00:00", "Z"
    )
    stream["requested_start"] = start
    stream["requested_end"] = end
    stream["query_filters"]["start_date"] = int(start_at.timestamp())
    stream["query_filters"]["end_date"] = int(end_at.timestamp())
    stream["started_at"] = started_at
    stream["finished_at"] = finished_at
    stream["pages"][0]["min_timestamp"] = before_start
    stream["pages"][0]["max_timestamp"] = before_start
    stream["pages"][0]["fetched_at"] = started_at
    return stream


def _created_after(end: str) -> str:
    end_at = _parse_datetime(end)
    assert end_at is not None
    return (end_at + timedelta(seconds=2)).isoformat().replace("+00:00", "Z")


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    cleaned = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _json_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _persist_run(
    session_factory,
    *,
    wallet_address: str,
    data_mode: str = "real",
    time_window: str = "24h",
    status: str = "success",
    transactions: list[dict[str, Any]] | None = None,
    swaps: list[dict[str, Any]] | None = None,
    custom_start: str | None = None,
    custom_end: str | None = None,
) -> int:
    transactions = transactions or []
    swaps = swaps or []
    requested_surfaces = ["transactions", "swaps"]
    run = WalletIngestionRun(
        wallet_address=wallet_address,
        time_window=time_window,
        custom_start=_parse_datetime(custom_start),
        custom_end=_parse_datetime(custom_end),
        data_mode=data_mode,
        status=status,
        requested_surfaces_json=json.dumps(requested_surfaces),
        provider_summary_json=json.dumps(
            {
                "provider_evidence": [],
                "unavailable_surfaces": [],
                "message": "History-readiness test fixture.",
            }
        ),
        created_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        updated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
    )
    for row in transactions:
        run.transactions.append(
            WalletTransaction(
                tx_hash=row["tx_hash"],
                logical_time=row.get("logical_time"),
                timestamp=_parse_datetime(row.get("timestamp")),
                fee_ton=(
                    Decimal(row["fee_ton"])
                    if row.get("fee_ton") not in (None, "")
                    else None
                ),
                success=row.get("success") or "unknown",
                provider=row.get("provider") or "tonapi",
                source_status=row.get("source_status") or "live",
                raw_json=_json_or_none(row.get("raw")),
            )
        )
    for row in swaps:
        raw = dict(row.get("raw") or {})
        raw.setdefault("token_in_address", row.get("token_in_address"))
        raw.setdefault("token_out_address", row.get("token_out_address"))
        run.swaps.append(
            WalletSwap(
                tx_hash=row.get("tx_hash"),
                timestamp=_parse_datetime(row.get("timestamp")),
                dex=row.get("dex"),
                token_in=row.get("token_in"),
                amount_in=(
                    Decimal(row["amount_in"])
                    if row.get("amount_in") not in (None, "")
                    else None
                ),
                token_out=row.get("token_out"),
                amount_out=(
                    Decimal(row["amount_out"])
                    if row.get("amount_out") not in (None, "")
                    else None
                ),
                estimated_usd=(
                    Decimal(row["estimated_usd"])
                    if row.get("estimated_usd") not in (None, "")
                    else None
                ),
                provider=row.get("provider") or "tonapi",
                source_status=row.get("source_status") or "live",
                raw_json=_json_or_none(raw),
            )
        )

    with session_factory() as session:
        session.add(run)
        session.commit()
        session.refresh(run)
        return run.id


def _database_counts(session_factory) -> dict[str, int]:
    models = (
        WalletIngestionRun,
        WalletTransfer,
        WalletTransaction,
        WalletSwap,
        WalletBalanceSnapshot,
        WalletIngestionWarning,
    )
    with session_factory() as session:
        return {model.__tablename__: session.query(model).count() for model in models}


def _blocker_codes(result: dict[str, Any]) -> set[str]:
    return {blocker["code"] for blocker in result["blockers"]}


def test_transaction_semantics_ignore_raw_and_normalize_decimals_and_timestamps():
    transaction_identity = _exact_transaction_identity()
    wallet_identity = _scoped_wallet_identity()
    first = _run(
        1,
        wallet_identity=wallet_identity,
        transactions=[
            _transaction(
                TRANSACTION_HASH,
                logical_time=TRANSACTION_LOGICAL_TIME,
                fee_ton="1.000000000000000000",
                timestamp="2026-06-01T10:00:00Z",
                raw={"capture": "first", "provider_only": 1},
                transaction_identity=transaction_identity,
            )
        ],
    )
    equivalent = _run(
        2,
        wallet_identity=wallet_identity,
        transactions=[
            _transaction(
                TRANSACTION_HASH.upper(),
                logical_time=TRANSACTION_LOGICAL_TIME,
                fee_ton="1.0",
                timestamp="2026-06-01T10:00:00+00:00",
                raw={"capture": "second", "provider_only": 999},
                transaction_identity=transaction_identity,
            )
        ],
    )

    result = assess_wallet_history_readiness([equivalent, first], target_run_id=2)

    assert result["run_ids"] == [1, 2]
    assert result["transaction_identity_groups_total"] == 1
    group = result["transaction_identity_groups"][0]
    assert group == {
        "identity": transaction_identity["key"],
        "identity_type": "account_transaction",
        "identity_strength": "exact",
        "run_ids": [1, 2],
        "observation_count": 2,
        "distinct_payload_count": 1,
        "has_conflict": False,
    }
    assert result["coverage"]["transaction_observations_with_exact_identity"] == 2
    assert result["coverage"]["transaction_observations_with_weak_identity"] == 0
    assert result["coverage"][
        "transaction_observations_with_unavailable_identity"
    ] == 0
    assert result["coverage"]["transaction_identity_coverage_state"] == "complete"
    assert "transaction_identity_coverage_incomplete" not in _blocker_codes(result)
    assert "legacy_transaction_identity_fallback" not in _blocker_codes(result)
    assert result["coverage"]["conflicting_transaction_identity_groups"] == 0
    assert "transaction_payload_conflicts" not in _blocker_codes(result)


def test_transaction_semantic_difference_is_reported_as_conflict():
    transaction_identity = _exact_transaction_identity()
    wallet_identity = _scoped_wallet_identity()
    first = _run(
        1,
        wallet_identity=wallet_identity,
        transactions=[
            _transaction(
                TRANSACTION_HASH,
                logical_time=TRANSACTION_LOGICAL_TIME,
                fee_ton="1.0",
                transaction_identity=transaction_identity,
            )
        ],
    )
    conflicting = _run(
        2,
        wallet_identity=wallet_identity,
        transactions=[
            _transaction(
                TRANSACTION_HASH,
                logical_time=TRANSACTION_LOGICAL_TIME,
                fee_ton="1.0001",
                transaction_identity=transaction_identity,
            )
        ],
    )

    result = assess_wallet_history_readiness([first, conflicting], target_run_id=2)

    group = result["transaction_identity_groups"][0]
    assert group["identity_strength"] == "exact"
    assert group["distinct_payload_count"] == 2
    assert group["has_conflict"] is True
    assert result["coverage"]["overlapping_transaction_identity_groups"] == 1
    assert result["coverage"]["conflicting_transaction_identity_groups"] == 1
    assert "overlapping_transaction_history" in _blocker_codes(result)
    assert "transaction_payload_conflicts" in _blocker_codes(result)


def test_transaction_identity_network_mismatch_is_never_exact():
    wallet_identity = _scoped_wallet_identity(network="ton-mainnet")
    first = _run(
        1,
        wallet_identity=wallet_identity,
        transactions=[
            _transaction(
                TRANSACTION_HASH,
                logical_time=TRANSACTION_LOGICAL_TIME,
                transaction_identity=_exact_transaction_identity(
                    network="ton-mainnet"
                ),
            )
        ],
    )
    mismatched = _run(
        2,
        wallet_identity=wallet_identity,
        transactions=[
            _transaction(
                TRANSACTION_HASH,
                logical_time=TRANSACTION_LOGICAL_TIME,
                transaction_identity=_exact_transaction_identity(
                    network="ton-testnet"
                ),
            )
        ],
    )

    result = assess_wallet_history_readiness([first, mismatched], target_run_id=2)

    assert result["transaction_identity_groups_total"] == 1
    group = result["transaction_identity_groups"][0]
    assert group["identity_type"] == "transaction_hash"
    assert group["identity_strength"] == "weak"
    assert result["coverage"]["overlapping_transaction_identity_groups"] == 0
    assert result["coverage"]["transaction_observations_with_exact_identity"] == 1
    assert result["coverage"]["transaction_observations_with_weak_identity"] == 1
    assert result["coverage"][
        "transaction_observations_with_invalid_identity_contract"
    ] == 1
    assert "transaction_identity_contract_invalid" in _blocker_codes(result)
    assert "transaction_identity_coverage_incomplete" in _blocker_codes(result)
    assert "legacy_transaction_identity_fallback" in _blocker_codes(result)


def test_malformed_claimed_transaction_key_falls_back_to_weak_diagnostic():
    malformed = _exact_transaction_identity()
    malformed["key"] = f"{malformed['key']}|tampered"
    wallet_identity = _scoped_wallet_identity()
    runs = [
        _run(
            run_id,
            wallet_identity=wallet_identity,
            transactions=[
                _transaction(
                    TRANSACTION_HASH,
                    logical_time=TRANSACTION_LOGICAL_TIME,
                    fee_ton=fee,
                    transaction_identity=malformed,
                )
            ],
        )
        for run_id, fee in ((1, "1"), (2, "2"))
    ]

    result = assess_wallet_history_readiness(runs, target_run_id=2)

    group = result["transaction_identity_groups"][0]
    assert group["identity"] == TRANSACTION_HASH
    assert group["identity_strength"] == "weak"
    assert group["distinct_payload_count"] == 2
    assert group["has_conflict"] is False
    assert result["coverage"]["transaction_observations_with_exact_identity"] == 0
    assert result["coverage"]["transaction_observations_with_weak_identity"] == 2
    assert result["coverage"][
        "transaction_observations_with_invalid_identity_contract"
    ] == 2
    assert result["coverage"]["conflicting_transaction_identity_groups"] == 0
    assert "transaction_identity_contract_invalid" in _blocker_codes(result)
    assert "transaction_payload_conflicts" not in _blocker_codes(result)


def test_missing_transaction_contract_is_legacy_weak_never_exact():
    result = assess_wallet_history_readiness(
        [
            _run(1, transactions=[_transaction("legacy-shared", fee_ton="1")]),
            _run(2, transactions=[_transaction("legacy-shared", fee_ton="2")]),
        ],
        target_run_id=2,
    )

    group = result["transaction_identity_groups"][0]
    assert group["identity"] == "legacy-shared"
    assert group["identity_type"] == "transaction_hash"
    assert group["identity_strength"] == "weak"
    assert group["distinct_payload_count"] == 2
    assert group["has_conflict"] is False
    assert result["coverage"]["transaction_observations_with_exact_identity"] == 0
    assert result["coverage"]["transaction_observations_with_weak_identity"] == 2
    assert result["coverage"][
        "transaction_observations_with_unavailable_identity"
    ] == 0
    assert result["coverage"]["transaction_identity_coverage_state"] == "incomplete"
    assert "transaction_identity_coverage_incomplete" in _blocker_codes(result)
    assert "legacy_transaction_identity_fallback" in _blocker_codes(result)
    assert "transaction_identity_contract_invalid" not in _blocker_codes(result)
    assert "overlapping_transaction_history" not in _blocker_codes(result)
    assert "transaction_payload_conflicts" not in _blocker_codes(result)


def test_exact_and_legacy_observations_emit_one_weak_hash_candidate_group():
    scoped_wallet = _scoped_wallet_identity()
    exact_identity = _exact_transaction_identity()
    result = assess_wallet_history_readiness(
        [
            _run(
                1,
                wallet_identity=scoped_wallet,
                transactions=[
                    _transaction(
                        TRANSACTION_HASH,
                        transaction_identity=exact_identity,
                    )
                ],
            ),
            _run(
                2,
                wallet_identity=scoped_wallet,
                transactions=[_transaction(TRANSACTION_HASH.upper())],
            ),
        ],
        target_run_id=2,
    )

    assert result["transaction_identity_groups_total"] == 1
    group = result["transaction_identity_groups"][0]
    assert group["identity"] == TRANSACTION_HASH
    assert group["identity_type"] == "transaction_hash"
    assert group["identity_strength"] == "weak"
    assert group["run_ids"] == [1, 2]
    assert group["has_conflict"] is False
    assert result["coverage"]["transaction_observations_with_exact_identity"] == 1
    assert result["coverage"]["transaction_observations_with_weak_identity"] == 1


def test_legacy_hex_hash_candidates_are_case_normalized_only_when_strict():
    result = assess_wallet_history_readiness(
        [
            _run(1, transactions=[_transaction(TRANSACTION_HASH.upper())]),
            _run(2, transactions=[_transaction(TRANSACTION_HASH)]),
        ],
        target_run_id=2,
    )

    assert result["transaction_identity_groups_total"] == 1
    group = result["transaction_identity_groups"][0]
    assert group["identity"] == TRANSACTION_HASH
    assert group["identity_type"] == "transaction_hash"
    assert group["identity_strength"] == "weak"


def test_transaction_identity_coverage_counts_unavailable_rows():
    result = assess_wallet_history_readiness(
        [
            _run(1, transactions=[_transaction("")]),
            _run(2, transactions=[_transaction("legacy-only")]),
        ],
        target_run_id=2,
    )

    coverage = result["coverage"]
    assert coverage["transaction_observations_with_exact_identity"] == 0
    assert coverage["transaction_observations_with_weak_identity"] == 1
    assert coverage["transaction_observations_with_unavailable_identity"] == 1
    assert coverage["transaction_identity_coverage_state"] == "incomplete"


def test_provider_scoped_event_action_identity_covers_transfers_and_swaps():
    wallet_identity = _scoped_wallet_identity()
    transfer_event_id = EVENT_ID.upper()
    transfer_identity = _provider_event_action_identity(
        event_id=transfer_event_id,
        action_index=0,
        action_type="TonTransfer",
    )
    swap_event_id = "ef" * 32
    swap_logical_time = "46000000000003"
    swap_identity = _provider_event_action_identity(
        event_id=swap_event_id,
        logical_time=swap_logical_time,
        action_index=1,
        action_type="JettonSwap",
    )
    runs = [
        _run(
            run_id,
            wallet_identity=wallet_identity,
            transfers=[
                _transfer(
                    transfer_event_id,
                    amount=transfer_amount,
                    event_action_identity=transfer_identity,
                )
            ],
            swaps=[
                _swap(
                    swap_event_id,
                    logical_time=swap_logical_time,
                    amount_in=swap_amount,
                    event_action_identity=swap_identity,
                )
            ],
        )
        for run_id, transfer_amount, swap_amount in (
            (1, "1.000000000000000000", "2.000"),
            (2, "1", "2"),
        )
    ]

    result = assess_wallet_history_readiness(runs, target_run_id=2)

    assert result["analysis_version"] == "wallet_history_readiness_v0.22.7"
    assert result["event_action_identity_groups_total"] == 2
    assert all(
        group["identity_type"] == "provider_event_action_observation"
        and group["identity_strength"] == "provider_scoped"
        and group["has_conflict"] is False
        for group in result["event_action_identity_groups"]
    )
    coverage = result["coverage"]
    assert coverage["event_action_observations"] == 4
    assert coverage[
        "event_action_observations_with_provider_scoped_identity"
    ] == 4
    assert coverage["event_action_observations_with_unavailable_identity"] == 0
    assert coverage[
        "event_action_observations_with_invalid_identity_contract"
    ] == 0
    assert coverage["event_action_identity_coverage_state"] == "complete"
    assert coverage[
        "overlapping_provider_scoped_event_action_identity_groups"
    ] == 2
    assert coverage[
        "conflicting_provider_scoped_event_action_identity_groups"
    ] == 0
    assert coverage["swap_observations_with_exact_identity"] == 0
    assert coverage["swap_observations_with_provider_scoped_identity"] == 2
    assert coverage["swap_observations_with_weak_identity"] == 0
    assert coverage["overlapping_provider_scoped_swap_identity_groups"] == 1
    blockers = _blocker_codes(result)
    assert "event_action_identity_non_authoritative" in blockers
    assert "event_action_identity_coverage_incomplete" not in blockers
    assert "event_action_identity_contract_invalid" not in blockers
    assert "weak_swap_identity" not in blockers
    assert "canonical_activity_identity_unavailable" in blockers
    assert result["history_complete"] is False
    assert result["eligible_for_cost_basis"] is False
    assert result["used_by_pnl"] is False


def test_provider_action_key_retyped_across_surfaces_is_a_conflict():
    wallet_identity = _scoped_wallet_identity()
    transfer_identity = _provider_event_action_identity(
        action_index=0,
        action_type="TonTransfer",
    )
    swap_identity = _provider_event_action_identity(
        action_index=0,
        action_type="JettonSwap",
    )
    assert transfer_identity["key"] == swap_identity["key"]

    result = assess_wallet_history_readiness(
        [
            _run(
                1,
                wallet_identity=wallet_identity,
                transfers=[
                    _transfer(
                        EVENT_ID,
                        event_action_identity=transfer_identity,
                    )
                ],
            ),
            _run(
                2,
                wallet_identity=wallet_identity,
                swaps=[
                    _swap(
                        EVENT_ID,
                        event_action_identity=swap_identity,
                    )
                ],
            ),
        ],
        target_run_id=2,
    )

    assert result["event_action_identity_groups_total"] == 1
    group = result["event_action_identity_groups"][0]
    assert group["identity"] == transfer_identity["key"]
    assert group["identity_type"] == "provider_event_action_observation"
    assert group["identity_strength"] == "provider_scoped"
    assert group["distinct_payload_count"] == 2
    assert group["has_conflict"] is True
    assert result["coverage"][
        "conflicting_provider_scoped_event_action_identity_groups"
    ] == 1
    assert "event_action_payload_conflicts" in _blocker_codes(result)
    assert result["history_complete"] is False
    assert result["is_cost_basis"] is False


@pytest.mark.parametrize(
    "tamper",
    [
        "version",
        "key",
        "network",
        "account",
        "event_id",
        "logical_time",
        "action_index_bool",
        "action_type_for_surface",
        "raw_event_id",
        "raw_surface",
        "raw_source",
        "row_event_id",
        "row_logical_time",
        "row_provider",
        "source_status",
        "safety_flag",
        "extra_field",
    ],
)
def test_event_action_identity_validation_fails_closed_on_tampering(tamper):
    wallet_identity = _scoped_wallet_identity()
    valid_identity = _provider_event_action_identity()
    valid_row = _transfer(
        EVENT_ID,
        event_action_identity=valid_identity,
    )
    tampered_row = copy.deepcopy(valid_row)
    identity = tampered_row["event_action_identity"]
    raw = tampered_row["raw"]

    if tamper == "version":
        identity["version"] = "invented_v9"
    elif tamper == "key":
        identity["key"] += "|tampered"
    elif tamper == "network":
        identity["network"] = "ton-testnet"
    elif tamper == "account":
        identity["account_canonical"] = "0:" + "ef" * 32
    elif tamper == "event_id":
        identity["event_id_canonical"] = "ef" * 32
    elif tamper == "logical_time":
        identity["logical_time_canonical"] = "1"
    elif tamper == "action_index_bool":
        identity["action_index"] = True
        raw["action_index"] = True
    elif tamper == "action_type_for_surface":
        identity["action_type"] = "JettonSwap"
        raw["action_type"] = "JettonSwap"
    elif tamper == "raw_event_id":
        raw["event_id"] = "ef" * 32
    elif tamper == "raw_surface":
        raw["surface"] = "swaps"
    elif tamper == "raw_source":
        raw["source"] = "other"
    elif tamper == "row_event_id":
        tampered_row["tx_hash"] = "ef" * 32
    elif tamper == "row_logical_time":
        tampered_row["logical_time"] = "1"
    elif tamper == "row_provider":
        tampered_row["provider"] = "other"
    elif tamper == "source_status":
        tampered_row["source_status"] = "limited"
    elif tamper == "safety_flag":
        identity["eligible_for_cost_basis"] = True
    elif tamper == "extra_field":
        identity["invented_semantics"] = True

    result = assess_wallet_history_readiness(
        [
            _run(
                1,
                wallet_identity=wallet_identity,
                transfers=[valid_row],
            ),
            _run(
                2,
                wallet_identity=wallet_identity,
                transfers=[tampered_row],
            ),
        ],
        target_run_id=2,
    )

    coverage = result["coverage"]
    assert coverage[
        "event_action_observations_with_provider_scoped_identity"
    ] == 1
    assert coverage["event_action_observations_with_unavailable_identity"] == 1
    assert coverage[
        "event_action_observations_with_invalid_identity_contract"
    ] == 1
    assert coverage["event_action_identity_coverage_state"] == "incomplete"
    assert result["event_action_identity_groups_total"] == 0
    blockers = {item["code"]: item for item in result["blockers"]}
    assert blockers["event_action_identity_coverage_incomplete"]["run_ids"] == [2]
    assert blockers["event_action_identity_contract_invalid"]["run_ids"] == [2]
    assert blockers["event_action_identity_non_authoritative"]["run_ids"] == [1]
    assert result["history_complete"] is False
    assert result["eligible_for_cost_basis"] is False
    assert result["used_by_pnl"] is False


@pytest.mark.parametrize("tamper", ["row_event_id", "raw_lt", "raw_source"])
def test_swap_event_action_identity_validation_fails_closed(tamper):
    wallet_identity = _scoped_wallet_identity()
    identity = _provider_event_action_identity(
        action_index=1,
        action_type="JettonSwap",
    )
    valid_swap = _swap(
        EVENT_ID,
        event_action_identity=identity,
    )
    tampered_swap = copy.deepcopy(valid_swap)
    if tamper == "row_event_id":
        tampered_swap["tx_hash"] = "ef" * 32
    elif tamper == "raw_lt":
        tampered_swap["raw"]["lt"] = "1"
    elif tamper == "raw_source":
        tampered_swap["raw"]["source"] = "other"

    result = assess_wallet_history_readiness(
        [
            _run(
                1,
                wallet_identity=wallet_identity,
                swaps=[valid_swap],
            ),
            _run(
                2,
                wallet_identity=wallet_identity,
                swaps=[tampered_swap],
            ),
        ],
        target_run_id=2,
    )

    coverage = result["coverage"]
    assert coverage["swap_observations_with_provider_scoped_identity"] == 1
    assert coverage["swap_observations_with_weak_identity"] == 1
    assert coverage[
        "event_action_observations_with_invalid_identity_contract"
    ] == 1
    blockers = {item["code"]: item for item in result["blockers"]}
    assert blockers["event_action_identity_contract_invalid"]["run_ids"] == [2]
    assert blockers["event_action_identity_coverage_incomplete"]["run_ids"] == [2]
    assert result["history_complete"] is False
    assert result["is_cost_basis"] is False


def test_unavailable_or_missing_event_action_identity_is_not_invalid():
    unavailable = unavailable_ton_event_action_identity().to_public_dict()
    transfer = _transfer(
        EVENT_ID,
        raw={
            "provider": "tonapi",
            "surface": "transfers",
            "event_id": EVENT_ID,
            "lt": EVENT_LOGICAL_TIME,
            "action_index": 0,
            "action_type": "TonTransfer",
        },
    )
    transfer["event_action_identity"] = unavailable

    result = assess_wallet_history_readiness(
        [
            _run(
                1,
                wallet_identity=_scoped_wallet_identity(),
                transfers=[transfer],
            ),
            _run(
                2,
                wallet_identity=_scoped_wallet_identity(),
                swaps=[_swap("legacy-event", raw={"event_id": "legacy-event"})],
            ),
        ],
        target_run_id=2,
    )

    coverage = result["coverage"]
    assert coverage["event_action_observations"] == 2
    assert coverage[
        "event_action_observations_with_provider_scoped_identity"
    ] == 0
    assert coverage["event_action_observations_with_unavailable_identity"] == 2
    assert coverage[
        "event_action_observations_with_invalid_identity_contract"
    ] == 0
    assert coverage["event_action_identity_coverage_state"] == "incomplete"
    blockers = _blocker_codes(result)
    assert "event_action_identity_coverage_incomplete" in blockers
    assert "event_action_identity_contract_invalid" not in blockers
    assert "event_action_identity_non_authoritative" not in blockers
    assert "weak_swap_identity" in blockers


def test_swap_raw_action_ordinal_and_event_reference_both_remain_weak():
    first = _run(
        1,
        swaps=[
            _swap(
                "evt-weak",
                amount_in="1.000",
                amount_out="10.0",
                raw={"event_id": "evt-weak", "capture": 1},
            ),
            _swap(
                "evt-exact",
                amount_in="2.000",
                amount_out="20.0",
                raw={"event_id": "evt-exact", "action_index": 0, "capture": 1},
            ),
        ],
    )
    second = _run(
        2,
        swaps=[
            _swap(
                "evt-weak",
                amount_in="1",
                amount_out="10",
                raw={"event_id": "evt-weak", "capture": 2},
            ),
            _swap(
                "evt-exact",
                amount_in="2",
                amount_out="20",
                raw={"event_id": "evt-exact", "action_index": 0, "capture": 2},
            ),
        ],
    )

    result = assess_wallet_history_readiness([first, second], target_run_id=2)

    groups = {group["identity_type"]: group for group in result["swap_identity_groups"]}
    action = groups["event_action"]
    weak = groups["event_reference"]
    assert action["identity"] == "tonapi:evt-exact:action_index:0"
    assert action["identity_strength"] == "weak"
    assert action["distinct_payload_count"] == 1
    assert action["has_conflict"] is False
    assert weak["identity"] == "tonapi:evt-weak"
    assert weak["identity_strength"] == "weak"
    assert weak["distinct_payload_count"] == 1
    assert result["coverage"]["swap_observations"] == 4
    assert result["coverage"]["swap_observations_with_exact_identity"] == 0
    assert result["coverage"]["overlapping_exact_swap_identity_groups"] == 0
    assert result["coverage"]["overlapping_weak_swap_identity_groups"] == 2
    assert "weak_swap_identity" in _blocker_codes(result)


def test_bounds_remain_unverified_and_observed_bounds_are_evidence_only():
    custom = _run(
        1,
        time_window="custom",
        custom_start="2026-06-01T00:00:00Z",
        custom_end="2026-06-01T01:00:00Z",
        transfers=[
            {"timestamp": "2026-05-31T23:59:00Z"},
            {"timestamp": None},
        ],
        transactions=[
            _transaction("inside", timestamp="2026-06-01T00:30:00Z")
        ],
        swaps=[_swap("outside", timestamp="2026-06-01T01:01:00Z")],
    )
    fixed = _run(
        2,
        transactions=[
            _transaction("fixed", timestamp="2026-06-01T00:45:00+00:00")
        ],
    )

    result = assess_wallet_history_readiness([fixed, custom], target_run_id=2)

    assert result["requested_bounds_verified"] is False
    assert result["observed_activity_start"] == "2026-05-31T23:59:00Z"
    assert result["observed_activity_end"] == "2026-06-01T01:01:00Z"
    custom_scope = next(scope for scope in result["runs"] if scope["run_id"] == 1)
    assert custom_scope["requested_start"] == "2026-06-01T00:00:00Z"
    assert custom_scope["requested_end"] == "2026-06-01T01:00:00Z"
    assert custom_scope["requested_bounds_verified"] is False
    assert custom_scope["observed_activity_start"] == "2026-05-31T23:59:00Z"
    assert custom_scope["observed_activity_end"] == "2026-06-01T01:01:00Z"
    assert custom_scope["timestamped_activity_count"] == 3
    assert custom_scope["untimestamped_activity_count"] == 1
    assert custom_scope["outside_requested_bounds_count"] == 2
    assert "requested_bounds_unverified" in _blocker_codes(result)
    assert "observations_outside_custom_bounds" in _blocker_codes(result)
    assert "activity_timestamps_incomplete" in _blocker_codes(result)


def test_address_and_fee_coverage_are_scoped_and_do_not_cross_link_runs():
    first = _run(
        1,
        transactions=[_transaction("fee-linked", fee_ton="0.01")],
        swaps=[
            _swap(
                "fee-linked",
                token_in="TON",
                token_out="JETA",
                token_out_address="EQjettA",
            ),
            _swap(
                "other-run-only",
                token_in="JETB",
                token_in_address=None,
                token_out="TON",
                token_out_address=None,
            ),
        ],
    )
    second = _run(
        2,
        transactions=[_transaction("other-run-only", fee_ton="0.02")],
    )

    result = assess_wallet_history_readiness([first, second], target_run_id=2)
    coverage = result["coverage"]

    assert coverage["non_ton_swap_legs"] == 2
    assert coverage["addressed_non_ton_swap_legs"] == 1
    assert coverage["asset_address_coverage_state"] == "incomplete"
    assert coverage["fee_link_candidate_swaps"] == 2
    assert coverage["same_run_fee_hash_match_candidates"] == 1
    assert coverage["fee_hash_match_coverage_state"] == "incomplete"
    assert coverage["fee_linkage_contract_verified"] is False
    assert "asset_address_coverage_incomplete" in _blocker_codes(result)
    assert "fee_linkage_incomplete" in _blocker_codes(result)


def test_empty_swap_coverage_is_not_reported_as_complete():
    result = assess_wallet_history_readiness(
        [
            _run(1, transactions=[_transaction("tx-a")]),
            _run(2, transactions=[_transaction("tx-b")]),
        ],
        target_run_id=2,
    )

    coverage = result["coverage"]
    assert coverage["non_ton_swap_legs"] == 0
    assert coverage["addressed_non_ton_swap_legs"] == 0
    assert coverage["asset_address_coverage_state"] == "not_observed"
    assert coverage["fee_link_candidate_swaps"] == 0
    assert coverage["same_run_fee_hash_match_candidates"] == 0
    assert coverage["fee_hash_match_coverage_state"] == "not_observed"


def test_complete_transaction_stream_evidence_is_reported_but_not_global_history():
    stream = _transaction_acquisition_stream()
    runs = [
        _run(
            1,
            requested_surfaces=["transactions"],
            acquisition_streams=[stream],
        ),
        _run(
            2,
            requested_surfaces=["transactions"],
            acquisition_streams=[stream],
        ),
    ]

    result = assess_wallet_history_readiness(runs, target_run_id=2)

    blockers = {item["code"]: item for item in result["blockers"]}
    assert "transaction_pagination_evidence_incomplete" not in blockers
    assert "pagination_completeness_unverified" in blockers
    states = blockers["pagination_completeness_unverified"]["evidence"][
        "transaction_streams_by_run"
    ]
    assert [item["state"] for item in states] == ["complete", "complete"]
    event_states = blockers["pagination_completeness_unverified"]["evidence"][
        "event_streams_by_run"
    ]
    assert [item["state"] for item in event_states] == [
        "not_requested",
        "not_requested",
    ]
    assert "provider_event_pagination_evidence_incomplete" not in blockers
    assert result["requested_bounds_verified"] is False
    assert result["history_complete"] is False
    assert result["eligible_for_cost_basis"] is False
    assert result["used_by_pnl"] is False


@pytest.mark.parametrize(
    "invalid_surfaces",
    [
        {"transactions": True, "transfers": True, "swaps": True},
        7,
        "transactions",
        ["transactions", "transactions"],
        ["transactions", "unknown"],
    ],
)
def test_malformed_requested_surfaces_fail_closed_without_endpoint_crash(
    invalid_surfaces,
):
    runs = [
        _run(
            run_id,
            status="partial",
            requested_surfaces=["transactions", "transfers", "swaps"],
            incomplete_surfaces=["transfers", "swaps"],
            acquisition_streams=[
                _transaction_acquisition_stream(),
                _event_acquisition_stream(),
            ],
        )
        for run_id in (1, 2)
    ]
    for run in runs:
        run["requested_surfaces"] = copy.deepcopy(invalid_surfaces)

    result = assess_wallet_history_readiness(runs, target_run_id=2)
    WalletHistoryReadinessResponse.model_validate(result)
    bounded = result["bounded_interval_coverage"]

    for layer_name in ("low_level_transactions", "provider_display_events"):
        layer = bounded[layer_name]
        assert layer["state"] == "no_validated_intervals"
        assert layer["included_run_ids"] == []
        assert layer["excluded_run_ids"] == [1, 2]
        assert all(
            record["source_reason_codes"] == ["requested_surfaces_invalid"]
            for record in layer["run_evidence"]
        )
    assert result["history_complete"] is False
    assert result["used_by_pnl"] is False


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [
        ("unavailable_surfaces", ["bogus"]),
        ("unavailable_surfaces", ["transfers", "transfers"]),
        ("unavailable_surfaces", {"transfers": True}),
        ("incomplete_surfaces", ["transfers", "swaps", "bogus"]),
        ("incomplete_surfaces", ["transfers", "transfers"]),
        ("incomplete_surfaces", 7),
    ],
)
def test_malformed_surface_status_lists_reject_both_interval_layers(
    field,
    invalid_value,
):
    runs = [
        _run(
            run_id,
            status="partial",
            requested_surfaces=["transactions", "transfers", "swaps"],
            incomplete_surfaces=["transfers", "swaps"],
            acquisition_streams=[
                _transaction_acquisition_stream(),
                _event_acquisition_stream(),
            ],
        )
        for run_id in (1, 2)
    ]
    for run in runs:
        run[field] = copy.deepcopy(invalid_value)

    result = assess_wallet_history_readiness(runs, target_run_id=2)
    WalletHistoryReadinessResponse.model_validate(result)

    for layer_name in ("low_level_transactions", "provider_display_events"):
        layer = result["bounded_interval_coverage"][layer_name]
        assert layer["included_run_ids"] == []
        assert layer["excluded_run_ids"] == [1, 2]
        assert all(
            "run_scope_invalid" in record["source_reason_codes"]
            for record in layer["run_evidence"]
        )
    assert result["history_complete"] is False
    assert result["used_by_pnl"] is False


@pytest.mark.parametrize(
    "stream",
    [
        _transaction_acquisition_stream(
            completion_state="incomplete",
            termination_reason="page_cap_reached",
            bounds_verified=False,
        ),
        _transaction_acquisition_stream(digest="not-a-sha256-digest"),
    ],
)
def test_incomplete_or_invalid_transaction_stream_evidence_stays_blocked(stream):
    result = assess_wallet_history_readiness(
        [
            _run(1, acquisition_streams=[_transaction_acquisition_stream()]),
            _run(2, acquisition_streams=[stream]),
        ],
        target_run_id=2,
    )

    blocker = next(
        item
        for item in result["blockers"]
        if item["code"] == "transaction_pagination_evidence_incomplete"
    )
    assert blocker["run_ids"] == [2]
    assert result["history_complete"] is False
    assert result["eligible_for_cost_basis"] is False


def test_transaction_pagination_validation_fails_closed_on_tampered_scope():
    cursor_stream = copy.deepcopy(_transaction_acquisition_stream())
    cursor_stream["pages"][0]["response_cursor"] = "46000000000001"
    cursor_stream["terminal_cursor"] = "46000000000001"

    outside_stream = copy.deepcopy(_transaction_acquisition_stream())
    outside_stream["normalized_count"] = 1
    outside_stream["pages"][0]["normalized_count"] = 1
    outside_transaction = _transaction(
        "outside-bound",
        timestamp="2026-06-02T00:00:00Z",
    )
    oversized_stream = copy.deepcopy(_transaction_acquisition_stream())
    oversized_stream["raw_count"] = 101
    oversized_stream["pages"][0]["raw_count"] = 101
    invalid_page_size_stream = copy.deepcopy(
        _transaction_acquisition_stream()
    )
    invalid_page_size_stream["page_size"] = "100"
    wrong_window_stream = copy.deepcopy(_transaction_acquisition_stream())
    wrong_window_stream["requested_start"] = "2026-06-01T01:00:00Z"
    wrong_query_stream = copy.deepcopy(_transaction_acquisition_stream())
    wrong_query_stream["query_filters"]["unexpected"] = True
    page_error_metadata_stream = copy.deepcopy(
        _transaction_acquisition_stream()
    )
    page_error_metadata_stream["pages"][0]["error_message"] = "stale error"
    impossible_count_stream = copy.deepcopy(_transaction_acquisition_stream())
    impossible_count_stream["normalized_count"] = 1
    impossible_count_stream["duplicate_count"] = 1
    impossible_count_stream["pages"][0]["normalized_count"] = 1
    impossible_count_stream["pages"][0]["duplicate_count"] = 1
    invalid_capture_stream = copy.deepcopy(_transaction_acquisition_stream())
    invalid_capture_stream["started_at"] = "2026-06-01T23:59:59Z"

    tampered_runs = [
        _run(2, data_mode="mock", acquisition_streams=[_transaction_acquisition_stream()]),
        _run(
            2,
            incomplete_surfaces=["transactions"],
            acquisition_streams=[_transaction_acquisition_stream()],
        ),
        _run(2, acquisition_streams=[cursor_stream]),
        _run(2, acquisition_streams=[oversized_stream]),
        _run(2, acquisition_streams=[invalid_page_size_stream]),
        _run(2, acquisition_streams=[wrong_window_stream]),
        _run(2, acquisition_streams=[wrong_query_stream]),
        _run(2, acquisition_streams=[page_error_metadata_stream]),
        _run(2, acquisition_streams=[impossible_count_stream]),
        _run(2, acquisition_streams=[invalid_capture_stream]),
        _run(
            2,
            custom_start="2026-06-01T00:00:00Z",
            acquisition_streams=[_transaction_acquisition_stream()],
        ),
        _run(
            2,
            transactions=[outside_transaction],
            acquisition_streams=[outside_stream],
        ),
        _run(
            2,
            time_window="custom",
            custom_start="2026-05-31T00:00:00Z",
            custom_end="2026-06-02T00:00:00Z",
            acquisition_streams=[_transaction_acquisition_stream()],
        ),
    ]

    for tampered in tampered_runs:
        first = _run(
            1,
            data_mode=tampered["data_mode"],
            acquisition_streams=(
                []
                if tampered["data_mode"] == "mock"
                else [_transaction_acquisition_stream()]
            ),
        )
        result = assess_wallet_history_readiness([first, tampered], target_run_id=2)
        blocker = next(
            item
            for item in result["blockers"]
            if item["code"] == "transaction_pagination_evidence_incomplete"
        )
        assert 2 in blocker["run_ids"]
        assert result["history_complete"] is False
        assert result["eligible_for_cost_basis"] is False
        assert result["used_by_pnl"] is False


def test_complete_event_stream_is_observed_without_promoting_display_actions():
    # Provider event ids are 256-bit hex and may be submitted in upper case.
    event_id = "FA" * 32
    logical_time = "46000000000002"
    transfer_identity = _provider_event_action_identity(
        event_id=event_id,
        logical_time=logical_time,
        action_index=0,
        action_type="TonTransfer",
    )
    swap_identity = _provider_event_action_identity(
        event_id=event_id,
        logical_time=logical_time,
        action_index=1,
        action_type="JettonSwap",
    )
    transfer = _transfer(
        event_id,
        logical_time=logical_time,
        timestamp="2026-06-01T12:00:00Z",
        event_action_identity=transfer_identity,
    )
    swap = _swap(
        event_id,
        logical_time=logical_time,
        timestamp="2026-06-01T12:00:00Z",
        event_action_identity=swap_identity,
    )
    runs = [
        _run(
            1,
            wallet_identity=_scoped_wallet_identity(),
            status="partial",
            requested_surfaces=["transfers", "swaps"],
            incomplete_surfaces=["transfers", "swaps"],
            acquisition_streams=[_event_acquisition_stream()],
        ),
        _run(
            2,
            wallet_identity=_scoped_wallet_identity(),
            status="partial",
            requested_surfaces=["transfers", "swaps"],
            incomplete_surfaces=["transfers", "swaps"],
            transfers=[transfer],
            swaps=[swap],
            acquisition_streams=[
                _event_acquisition_stream(with_activity=True)
            ],
        ),
    ]

    result = assess_wallet_history_readiness(runs, target_run_id=2)

    blockers = {item["code"]: item for item in result["blockers"]}
    states = blockers["pagination_completeness_unverified"]["evidence"][
        "event_streams_by_run"
    ]
    assert [item["state"] for item in states] == [
        "provider_stream_complete",
        "provider_stream_complete",
    ]
    assert all(
        item["provider_semantics"] == "display_only_actions"
        for item in states
    )
    assert "provider_event_pagination_evidence_incomplete" not in blockers
    assert "pagination_completeness_unverified" in blockers
    assert "canonical_activity_identity_unavailable" in blockers
    assert "event_action_identity_non_authoritative" in blockers
    assert "event_action_identity_coverage_incomplete" not in blockers
    assert result["coverage"]["event_action_observations"] == 2
    assert result["coverage"][
        "event_action_observations_with_provider_scoped_identity"
    ] == 2
    # One accepted provider event produced two separately identified actions.
    # Event pagination remains valid because it compares unique event refs.
    assert result["coverage"]["event_action_identity_coverage_state"] == "complete"
    assert result["requested_bounds_verified"] is False
    assert result["history_complete"] is False
    assert result["eligible_for_cost_basis"] is False
    assert result["used_by_pnl"] is False


@pytest.mark.parametrize(
    "tamper",
    [
        "provider",
        "scope",
        "page_size",
        "page_envelope",
        "aggregate_count",
        "digest",
        "cursor_chain",
        "time_order",
        "query_bounds",
        "query_extra",
        "page_error_metadata",
        "combined_count",
        "capture_order",
        "fetch_order",
        "termination",
    ],
)
def test_event_pagination_validation_fails_closed_on_tampering(tamper):
    stream = copy.deepcopy(_event_acquisition_stream(with_activity=True))
    if tamper == "provider":
        stream["provider"] = "other"
    elif tamper == "scope":
        stream["scope_kind"] = "bounded_interval"
    elif tamper == "page_size":
        stream["page_size"] = 101
        stream["query_filters"]["limit"] = 101
        for page in stream["pages"]:
            page["requested_limit"] = 101
    elif tamper == "page_envelope":
        stream["page_count"] = 3
    elif tamper == "aggregate_count":
        stream["raw_count"] = 2
    elif tamper == "digest":
        stream["pages"][0]["response_digest"] = "not-a-digest"
    elif tamper == "cursor_chain":
        stream["pages"][1]["request_cursor"] = "46000000000001"
    elif tamper == "time_order":
        stream["pages"][0]["min_timestamp"] = "2026-06-01T13:00:00Z"
    elif tamper == "query_bounds":
        stream["query_filters"]["start_date"] += 1
    elif tamper == "query_extra":
        stream["query_filters"]["unexpected"] = True
    elif tamper == "page_error_metadata":
        stream["pages"][0]["error_message"] = "stale error"
    elif tamper == "combined_count":
        stream["duplicate_count"] = 1
        stream["pages"][0]["duplicate_count"] = 1
    elif tamper == "capture_order":
        stream["started_at"] = "2026-06-01T23:59:59Z"
    elif tamper == "fetch_order":
        stream["pages"][0]["fetched_at"] = "2026-06-02T00:00:01Z"
        stream["pages"][1]["fetched_at"] = "2026-06-02T00:00:00Z"
    elif tamper == "termination":
        stream["termination_reason"] = "requested_start_crossed"

    result = assess_wallet_history_readiness(
        [
            _run(
                1,
                status="partial",
                requested_surfaces=["transfers", "swaps"],
                incomplete_surfaces=["transfers", "swaps"],
                acquisition_streams=[_event_acquisition_stream()],
            ),
            _run(
                2,
                status="partial",
                requested_surfaces=["transfers", "swaps"],
                incomplete_surfaces=["transfers", "swaps"],
                acquisition_streams=[stream],
            ),
        ],
        target_run_id=2,
    )

    blocker = next(
        item
        for item in result["blockers"]
        if item["code"] == "provider_event_pagination_evidence_incomplete"
    )
    assert blocker["run_ids"] == [2]
    evidence = blocker["evidence"]["event_streams_by_run"]
    assert [item["state"] for item in evidence] == [
        "provider_stream_complete",
        "incomplete",
    ]
    if tamper == "aggregate_count":
        assert "page_evidence_invalid" in evidence[1]["reason_codes"]


def test_transaction_page_fetch_times_must_follow_page_order():
    stream = copy.deepcopy(_transaction_acquisition_stream())
    stream["termination_reason"] = "provider_terminal"
    stream["terminal_cursor"] = None
    stream["page_count"] = 2
    stream["pages_succeeded"] = 2
    stream["pages"].append(
        {
            "page_index": 2,
            "request_cursor": "46000000000000",
            "response_cursor": None,
            "requested_limit": 100,
            "raw_count": 0,
            "normalized_count": 0,
            "duplicate_count": 0,
            "min_logical_time": None,
            "max_logical_time": None,
            "min_timestamp": None,
            "max_timestamp": None,
            "response_digest": "ef" * 32,
            "attempt_count": 1,
            "error_code": None,
            "error_message": None,
            "fetched_at": "2026-06-02T00:00:01Z",
        }
    )
    baseline = assess_wallet_history_readiness(
        [
            _run(
                1,
                requested_surfaces=["transactions"],
                acquisition_streams=[_transaction_acquisition_stream()],
            ),
            _run(
                2,
                requested_surfaces=["transactions"],
                acquisition_streams=[stream],
            ),
        ],
        target_run_id=2,
    )
    baseline_layer = baseline["bounded_interval_coverage"][
        "low_level_transactions"
    ]
    assert baseline_layer["included_run_ids"] == [1, 2]

    stream["pages"][0]["fetched_at"] = "2026-06-02T00:00:01Z"
    stream["pages"][1]["fetched_at"] = "2026-06-02T00:00:00Z"
    result = assess_wallet_history_readiness(
        [
            _run(
                1,
                requested_surfaces=["transactions"],
                acquisition_streams=[_transaction_acquisition_stream()],
            ),
            _run(
                2,
                requested_surfaces=["transactions"],
                acquisition_streams=[stream],
            ),
        ],
        target_run_id=2,
    )
    layer = result["bounded_interval_coverage"]["low_level_transactions"]
    target_evidence = next(
        item for item in layer["run_evidence"] if item["run_id"] == 2
    )
    assert target_evidence["classification"] == "excluded"
    assert "capture_times_invalid" in target_evidence["source_reason_codes"]


def test_event_stream_requires_display_actions_to_remain_incomplete_at_run_level():
    result = assess_wallet_history_readiness(
        [
            _run(
                1,
                status="partial",
                requested_surfaces=["transfers", "swaps"],
                incomplete_surfaces=["transfers", "swaps"],
                acquisition_streams=[_event_acquisition_stream()],
            ),
            _run(
                2,
                requested_surfaces=["transfers", "swaps"],
                incomplete_surfaces=["transfers"],
                acquisition_streams=[_event_acquisition_stream()],
            ),
        ],
        target_run_id=2,
    )

    blocker = next(
        item
        for item in result["blockers"]
        if item["code"] == "provider_event_pagination_evidence_incomplete"
    )
    assert blocker["run_ids"] == [2]
    assert blocker["evidence"]["event_streams_by_run"][1]["state"] == "incomplete"


def test_missing_event_stream_is_blocking_only_when_event_surfaces_were_requested():
    event_requested = assess_wallet_history_readiness(
        [
            _run(
                1,
                requested_surfaces=["transfers"],
                incomplete_surfaces=["transfers"],
            ),
            _run(
                2,
                requested_surfaces=["transfers"],
                incomplete_surfaces=["transfers"],
            ),
        ],
        target_run_id=2,
    )
    transaction_only = assess_wallet_history_readiness(
        [
            _run(1, requested_surfaces=["transactions"]),
            _run(2, requested_surfaces=["transactions"]),
        ],
        target_run_id=2,
    )

    event_blocker = next(
        item
        for item in event_requested["blockers"]
        if item["code"] == "provider_event_pagination_evidence_incomplete"
    )
    assert event_blocker["run_ids"] == [1, 2]
    assert [
        item["state"]
        for item in event_blocker["evidence"]["event_streams_by_run"]
    ] == ["missing", "missing"]
    assert (
        "provider_event_pagination_evidence_incomplete"
        not in _blocker_codes(transaction_only)
    )


def test_bounded_transaction_intervals_form_contiguous_selected_span_only():
    first_start = "2026-06-01T00:00:00Z"
    shared_boundary = "2026-06-02T00:00:00Z"
    second_end = "2026-06-03T00:00:00Z"
    runs = [
        _run(
            1,
            time_window="custom",
            custom_start=first_start,
            custom_end=shared_boundary,
            created_at=_created_after(shared_boundary),
            requested_surfaces=["transactions"],
            acquisition_streams=[
                _retime_transaction_stream(first_start, shared_boundary)
            ],
        ),
        _run(
            2,
            time_window="custom",
            custom_start=shared_boundary,
            custom_end=second_end,
            created_at=_created_after(second_end),
            requested_surfaces=["transactions"],
            acquisition_streams=[
                _retime_transaction_stream(shared_boundary, second_end)
            ],
        ),
    ]

    result = assess_wallet_history_readiness(runs, target_run_id=2)
    bounded = result["bounded_interval_coverage"]
    transactions = bounded["low_level_transactions"]

    assert result["analysis_version"] == "wallet_history_readiness_v0.22.7"
    assert bounded["contract_version"] == "wallet_multi_run_interval_coverage_v1"
    assert bounded["cross_stream_union_applied"] is False
    assert transactions["state"] == "contiguous_selected_span"
    assert transactions["selected_run_coverage_state"] == "complete"
    assert transactions["included_run_ids"] == [1, 2]
    assert transactions["gap_intervals"] == []
    assert transactions["overlap_intervals"] == []
    assert transactions["covered_duration_microseconds"] == str(
        2 * 86_400_000_000
    )
    assert bounded["provider_display_events"]["state"] == (
        "no_validated_intervals"
    )
    assert bounded["full_pre_run_history_established"] is False
    assert bounded["complete_wallet_history_established"] is False
    assert bounded["deduplication_applied"] is False
    assert bounded["eligible_for_cost_basis"] is False
    assert bounded["used_by_pnl"] is False
    assert "bounded_transaction_interval_gaps" not in _blocker_codes(result)
    assert "bounded_transaction_interval_overlaps" not in _blocker_codes(result)
    assert result["history_complete"] is False


def test_provider_display_intervals_never_bridge_transaction_gap():
    bounds = [
        ("2026-06-01T00:00:00Z", "2026-06-02T00:00:00Z"),
        ("2026-06-02T00:00:00Z", "2026-06-03T00:00:00Z"),
        ("2026-06-03T00:00:00Z", "2026-06-04T00:00:00Z"),
    ]
    runs: list[dict[str, Any]] = []
    for run_id, (start, end) in enumerate(bounds, start=1):
        transaction_requested = run_id != 2
        requested_surfaces = ["transfers"]
        streams = [_retime_event_stream(start, end)]
        if transaction_requested:
            requested_surfaces.insert(0, "transactions")
            streams.insert(0, _retime_transaction_stream(start, end))
        runs.append(
            _run(
                run_id,
                time_window="custom",
                status="partial",
                custom_start=start,
                custom_end=end,
                created_at=_created_after(end),
                requested_surfaces=requested_surfaces,
                incomplete_surfaces=["transfers"],
                acquisition_streams=streams,
            )
        )

    result = assess_wallet_history_readiness(runs, target_run_id=3)
    bounded = result["bounded_interval_coverage"]
    transactions = bounded["low_level_transactions"]
    events = bounded["provider_display_events"]

    assert transactions["state"] == "gapped_selected_span"
    assert transactions["selected_run_coverage_state"] == "partial"
    assert transactions["included_run_ids"] == [1, 3]
    assert transactions["not_requested_run_ids"] == [2]
    assert transactions["gap_intervals"] == [
        {
            "start": bounds[0][1],
            "end": bounds[2][0],
            "duration_microseconds": "86400000000",
            "left_run_ids": [1],
            "right_run_ids": [3],
        }
    ]
    assert events["state"] == "contiguous_selected_span"
    assert events["included_run_ids"] == [1, 2, 3]
    assert events["gap_intervals"] == []
    assert bounded["cross_stream_union_applied"] is False
    blocker_codes = _blocker_codes(result)
    assert "bounded_transaction_interval_gaps" in blocker_codes
    assert "provider_display_interval_gaps" not in blocker_codes
    assert result["history_complete"] is False
    assert result["deduplication_applied"] is False


def test_transaction_interval_overlap_is_diagnostic_and_never_deduplicates():
    start = "2026-06-01T00:00:00Z"
    end = "2026-06-02T00:00:00Z"
    runs = [
        _run(
            run_id,
            time_window="custom",
            custom_start=start,
            custom_end=end,
            created_at=_created_after(end),
            requested_surfaces=["transactions"],
            acquisition_streams=[_retime_transaction_stream(start, end)],
        )
        for run_id in (1, 2)
    ]

    result = assess_wallet_history_readiness(runs, target_run_id=2)
    transactions = result["bounded_interval_coverage"][
        "low_level_transactions"
    ]

    assert transactions["max_coverage_depth"] == 2
    assert transactions["overlap_intervals"][0]["run_ids"] == [1, 2]
    assert "bounded_transaction_interval_overlaps" in _blocker_codes(result)
    assert result["deduplication_applied"] is False
    assert result["used_by_pnl"] is False


def test_endpoint_is_read_only_and_does_not_change_pnl(db_client):
    client, session_factory = db_client
    transaction = _transaction("shared", fee_ton="0.01")
    swap = _swap(
        "shared",
        amount_in="2",
        amount_out="20",
        raw={"event_id": "shared"},
    )
    first_id = _persist_run(
        session_factory,
        wallet_address="EQpersisted",
        transactions=[transaction],
        swaps=[swap],
    )
    target_id = _persist_run(
        session_factory,
        wallet_address="EQpersisted",
        transactions=[transaction],
        swaps=[swap],
    )

    pnl_before_response = client.get(
        f"/api/wallets/ingest/{target_id}/pnl-preview"
    )
    assert pnl_before_response.status_code == 200
    pnl_before = pnl_before_response.json()
    counts_before = _database_counts(session_factory)

    response = client.post(
        "/api/wallets/history/readiness",
        json={"target_run_id": target_id, "run_ids": [target_id, first_id]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["analysis_version"] == "wallet_history_readiness_v0.22.7"
    assert body["run_ids"] == [first_id, target_id]
    assert body["target_run_id"] == target_id
    assert next(scope for scope in body["runs"] if scope["is_target"])[
        "run_id"
    ] == target_id
    assert body["transaction_identity_groups_total"] == 1
    assert body["transaction_identity_groups"][0]["has_conflict"] is False
    bounded = body["bounded_interval_coverage"]
    assert bounded["contract_version"] == "wallet_multi_run_interval_coverage_v1"
    assert bounded["selected_run_ids"] == [first_id, target_id]
    assert bounded["low_level_transactions"]["state"] == (
        "no_validated_intervals"
    )
    assert bounded["provider_display_events"]["state"] == (
        "no_validated_intervals"
    )
    assert bounded["cross_stream_union_applied"] is False
    assert bounded["complete_wallet_history_established"] is False
    assert bounded["activity_rows_merged"] is False
    assert bounded["deduplication_applied"] is False
    assert bounded["eligible_for_cost_basis"] is False
    assert bounded["used_by_pnl"] is False
    assert body["history_complete"] is False
    assert body["deduplication_applied"] is False
    assert body["is_cost_basis"] is False
    assert body["eligible_for_cost_basis"] is False
    assert body["used_by_pnl"] is False
    assert _database_counts(session_factory) == counts_before

    pnl_after_response = client.get(f"/api/wallets/ingest/{target_id}/pnl-preview")
    assert pnl_after_response.status_code == 200
    assert pnl_after_response.json() == pnl_before


def test_endpoint_groups_bounce_variants_by_scoped_wallet_identity(
    db_client,
    monkeypatch,
):
    client, _ = db_client
    monkeypatch.setenv("DATA_MODE", "mock")
    run_ids = []
    for wallet_address in (BOUNCEABLE_WALLET, NONBOUNCEABLE_WALLET):
        response = client.post(
            "/api/wallets/ingest",
            json={
                "wallet_address": wallet_address,
                "time_window": "24h",
                "surfaces": ["transactions", "swaps"],
            },
        )
        assert response.status_code == 200
        run_ids.append(response.json()["run_id"])

    response = client.post(
        "/api/wallets/history/readiness",
        json={"target_run_id": run_ids[1], "run_ids": run_ids},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["wallet_address"] == NONBOUNCEABLE_WALLET
    assert body["wallet_identity"]["status"] == "network_scoped"
    assert body["wallet_identity"]["network"] == "ton-mainnet"
    assert body["wallet_identity"]["canonical_address"] == CANONICAL_WALLET
    assert [scope["wallet_address"] for scope in body["runs"]] == [
        BOUNCEABLE_WALLET,
        NONBOUNCEABLE_WALLET,
    ]
    assert "wallet_identity_unavailable" not in _blocker_codes(body)
    assert "canonical_activity_identity_unavailable" in _blocker_codes(body)


@pytest.mark.parametrize(
    "payload",
    [
        {"target_run_id": 1, "run_ids": [1]},
        {"target_run_id": 1, "run_ids": list(range(1, 52))},
        {"target_run_id": 1, "run_ids": [1, 0]},
        {"target_run_id": 3, "run_ids": [1, 2]},
        {"target_run_id": 0, "run_ids": [1, 2]},
        {"target_run_id": True, "run_ids": [True, 2]},
        {"target_run_id": 1.0, "run_ids": [1.0, 2]},
        {"target_run_id": "1", "run_ids": ["1", 2]},
        {"target_run_id": 1, "run_ids": [1, False]},
        {"target_run_id": 1, "run_ids": [1, 2.0]},
        {"target_run_id": 1, "run_ids": [1, "2"]},
        {"run_ids": [1, 2]},
        {"target_run_id": 1},
    ],
)
def test_endpoint_request_validation_returns_422(db_client, payload):
    client, _ = db_client

    response = client.post("/api/wallets/history/readiness", json=payload)

    assert response.status_code == 422
    assert response.json()["detail"]


def test_endpoint_maps_domain_errors_to_400_and_missing_runs_to_404(db_client):
    client, session_factory = db_client
    base_id = _persist_run(session_factory, wallet_address="EQbase")

    duplicate = client.post(
        "/api/wallets/history/readiness",
        json={"target_run_id": base_id, "run_ids": [base_id, base_id]},
    )
    assert duplicate.status_code == 400
    assert "distinct" in duplicate.json()["detail"]

    different_wallet_id = _persist_run(
        session_factory,
        wallet_address="eqbase",
    )
    wallet_mismatch = client.post(
        "/api/wallets/history/readiness",
        json={
            "target_run_id": base_id,
            "run_ids": [base_id, different_wallet_id],
        },
    )
    assert wallet_mismatch.status_code == 400
    assert "exact same wallet_address" in wallet_mismatch.json()["detail"]

    mock_id = _persist_run(
        session_factory,
        wallet_address="EQbase",
        data_mode="mock",
    )
    mixed_modes = client.post(
        "/api/wallets/history/readiness",
        json={"target_run_id": base_id, "run_ids": [base_id, mock_id]},
    )
    assert mixed_modes.status_code == 400
    assert "same data_mode" in mixed_modes.json()["detail"]

    missing_id = 999999
    missing = client.post(
        "/api/wallets/history/readiness",
        json={"target_run_id": base_id, "run_ids": [base_id, missing_id]},
    )
    assert missing.status_code == 404
    assert f"run {missing_id} not found" in missing.json()["detail"]
