"""Tests for the read-only multi-run history-readiness diagnostic."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
from services.wallet_history_readiness import assess_wallet_history_readiness


BOUNCEABLE_WALLET = "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF"
NONBOUNCEABLE_WALLET = "UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA"
CANONICAL_WALLET = (
    "0:ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e"
)


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
) -> dict[str, Any]:
    return {
        "tx_hash": tx_hash,
        "logical_time": logical_time,
        "timestamp": timestamp,
        "fee_ton": fee_ton,
        "success": success,
        "provider": provider,
        "source_status": source_status,
        "raw": raw,
    }


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
) -> dict[str, Any]:
    return {
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
    created_at: str = "2026-06-02T00:00:00Z",
    requested_surfaces: list[str] | None = None,
    unavailable_surfaces: list[str] | None = None,
) -> dict[str, Any]:
    return {
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
        "_created_at": created_at,
        "_custom_start": custom_start,
        "_custom_end": custom_end,
    }


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
    first = _run(
        1,
        transactions=[
            _transaction(
                "shared-hash",
                fee_ton="1.000000000000000000",
                timestamp="2026-06-01T10:00:00Z",
                raw={"capture": "first", "provider_only": 1},
            )
        ],
    )
    equivalent = _run(
        2,
        transactions=[
            _transaction(
                "shared-hash",
                fee_ton="1.0",
                timestamp="2026-06-01T10:00:00+00:00",
                raw={"capture": "second", "provider_only": 999},
            )
        ],
    )

    result = assess_wallet_history_readiness([equivalent, first], target_run_id=2)

    assert result["run_ids"] == [1, 2]
    assert result["transaction_identity_groups_total"] == 1
    group = result["transaction_identity_groups"][0]
    assert group == {
        "identity": "shared-hash",
        "identity_type": "transaction_hash",
        "identity_strength": "exact",
        "run_ids": [1, 2],
        "observation_count": 2,
        "distinct_payload_count": 1,
        "has_conflict": False,
    }
    assert result["coverage"]["conflicting_transaction_identity_groups"] == 0
    assert "transaction_payload_conflicts" not in _blocker_codes(result)


def test_transaction_semantic_difference_is_reported_as_conflict():
    first = _run(
        1,
        transactions=[_transaction("shared-hash", fee_ton="1.0")],
    )
    conflicting = _run(
        2,
        transactions=[_transaction("shared-hash", fee_ton="1.0001")],
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


def test_swap_identity_distinguishes_weak_event_reference_and_exact_action():
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
    exact = groups["event_action"]
    weak = groups["event_reference"]
    assert exact["identity"] == "tonapi:evt-exact:action_index:0"
    assert exact["identity_strength"] == "exact"
    assert exact["distinct_payload_count"] == 1
    assert exact["has_conflict"] is False
    assert weak["identity"] == "tonapi:evt-weak"
    assert weak["identity_strength"] == "weak"
    assert weak["distinct_payload_count"] == 1
    assert result["coverage"]["swap_observations"] == 4
    assert result["coverage"]["swap_observations_with_exact_identity"] == 2
    assert result["coverage"]["overlapping_exact_swap_identity_groups"] == 1
    assert result["coverage"]["overlapping_weak_swap_identity_groups"] == 1
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
    assert body["analysis_version"] == "wallet_history_readiness_v0.22.0"
    assert body["run_ids"] == [first_id, target_id]
    assert body["target_run_id"] == target_id
    assert next(scope for scope in body["runs"] if scope["is_target"])[
        "run_id"
    ] == target_id
    assert body["transaction_identity_groups_total"] == 1
    assert body["transaction_identity_groups"][0]["has_conflict"] is False
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
