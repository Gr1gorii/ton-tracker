"""Tests for mock-normalized wallet activity ingestion endpoints."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import ProviderResult
from database import Base, get_session
from main import app


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override_get_session():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_wallet_ingestion_preview_returns_mock_coverage(client, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)

    response = client.post(
        "/api/wallets/ingest/preview",
        json={
            "wallet_address": "  EQwallet  ",
            "time_window": "24h",
            "surfaces": ["transfers", "swaps", "jettons"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["wallet_address"] == "EQwallet"
    assert body["requested_surfaces"] == ["transfers", "swaps", "jettons"]
    assert body["unavailable_surfaces"] == []
    assert "deterministic fixtures" in body["warnings"][0]
    assert "No real provider calls" in body["message"]

    evidence = body["provider_coverage"][0]
    assert evidence["provider"] == "mock_wallet_activity"
    assert evidence["data_mode"] == "mock"
    assert evidence["source_status"] == "mock"
    assert evidence["raw_count"] == 6
    assert evidence["normalized_count"] == 6


def test_wallet_ingestion_explicit_provider_scaffold_returns_limited_coverage(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest/preview",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["jettons"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["unavailable_surfaces"] == ["jettons"]
    assert "No real wallet activity provider calls" in body["message"]

    evidence = body["provider_coverage"][0]
    assert evidence["provider"] == "tonapi_wallet_activity_scaffold"
    assert evidence["data_mode"] == "real"
    assert evidence["source_status"] == "limited"
    assert evidence["raw_count"] == 0
    assert evidence["normalized_count"] == 0

    run_response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["jettons"],
        },
    )

    assert run_response.status_code == 200
    run_body = run_response.json()
    assert run_body["status"] == "partial"
    assert run_body["data_mode"] == "real"
    assert run_body["provider_evidence"][0]["source_status"] == "limited"
    assert run_body["balances"] == []
    assert run_body["warnings"]


def test_wallet_ingestion_guarded_tonapi_live_persists_jetton_snapshot(
    client,
    monkeypatch,
):
    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "jettons": [
                    {
                        "jetton_address": "EQjetton",
                        "jetton_name": "Example Jetton",
                        "jetton_symbol": "EJT",
                        "balance": "123450000",
                        "decimals": 6,
                        "price_usd": "0.25",
                        "wallet_contract_address": "EQjettonWallet",
                        "source": "tonapi",
                    }
                ],
                "preview_count": 1,
                "total_jettons": 1,
            },
            source="real",
            message="TonAPI account jettons preview fetched.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["jettons"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data_mode"] == "real"
    assert body["unavailable_surfaces"] == []
    assert body["provider_evidence"][0]["provider"] == "tonapi_wallet_activity_live"
    assert body["provider_evidence"][0]["source_status"] == "live"
    assert body["provider_evidence"][0]["raw_count"] == 1
    assert body["provider_evidence"][0]["normalized_count"] == 1
    assert body["transfers"] == []
    assert body["swaps"] == []
    assert len(body["balances"]) == 1
    assert body["balances"][0]["asset"] == "EJT"
    assert body["balances"][0]["balance"] == "123.450000000000000000"
    assert body["balances"][0]["balance_usd"] == "30.86250000"
    assert body["balances"][0]["provider"] == "tonapi"
    assert body["balances"][0]["source_status"] == "live"


def test_wallet_ingestion_guarded_tonapi_live_persists_native_balance_snapshot(
    client,
    monkeypatch,
):
    def fake_get_account_balance_preview(self, account_address):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "balance": {
                    "wallet_address": account_address,
                    "asset": "TON",
                    "balance": "2500000000",
                    "decimals": 9,
                    "account_status": "active",
                    "is_scam": False,
                    "source": "tonapi",
                },
            },
            source="real",
            message="TonAPI account native TON balance fetched.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_balance_preview",
        fake_get_account_balance_preview,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["balances"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "success"
    assert body["data_mode"] == "real"
    assert body["unavailable_surfaces"] == []
    assert body["provider_evidence"][0]["provider"] == "tonapi_wallet_activity_live"
    assert body["provider_evidence"][0]["source_status"] == "live"
    assert body["provider_evidence"][0]["raw_count"] == 1
    assert body["provider_evidence"][0]["normalized_count"] == 1
    assert body["transactions"] == []
    assert len(body["balances"]) == 1
    assert body["balances"][0]["asset"] == "TON"
    assert body["balances"][0]["balance"] == "2.500000000000000000"
    assert body["balances"][0]["balance_usd"] is None
    assert body["balances"][0]["provider"] == "tonapi"
    assert body["balances"][0]["source_status"] == "live"
    assert body["balances"][0]["raw"]["surface"] == "balances"


def test_wallet_ingestion_guarded_tonapi_live_persists_transaction_history(
    client,
    monkeypatch,
):
    def fake_get_account_transactions_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "transactions": [
                    {
                        "tx_hash": "abc123",
                        "logical_time": "46000000000001",
                        "utime": 1717236000,
                        "total_fees": "4200000",
                        "success": True,
                        "transaction_type": "TransOrd",
                        "source": "tonapi",
                    }
                ],
                "preview_count": 1,
                "total_transactions": 1,
            },
            source="real",
            message="TonAPI account transaction history fetched.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_transactions_preview",
        fake_get_account_transactions_preview,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["transactions"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert body["status"] == "success"
    assert body["data_mode"] == "real"
    assert body["unavailable_surfaces"] == []
    assert body["provider_evidence"][0]["provider"] == "tonapi_wallet_activity_live"
    assert body["provider_evidence"][0]["source_status"] == "live"
    assert body["provider_evidence"][0]["raw_count"] == 1
    assert body["provider_evidence"][0]["normalized_count"] == 1
    assert body["balances"] == []
    assert len(body["transactions"]) == 1
    tx = body["transactions"][0]
    assert tx["tx_hash"] == "abc123"
    assert tx["fee_ton"] == "0.004200000000000000"
    assert tx["success"] == "success"
    assert tx["provider"] == "tonapi"
    assert tx["source_status"] == "live"
    assert tx["raw"]["surface"] == "transactions"

    # The persisted run round-trips through GET with the live transaction row.
    read_back = client.get(f"/api/wallets/ingest/{run_id}")
    assert read_back.status_code == 200
    read_body = read_back.json()
    assert len(read_body["transactions"]) == 1
    assert read_body["transactions"][0]["tx_hash"] == "abc123"


def test_wallet_ingestion_guarded_tonapi_live_persists_transfer_history(
    client,
    monkeypatch,
):
    def fake_get_account_events_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "transfers": [
                    {
                        "event_id": "evt1",
                        "utime": 1717236000,
                        "lt": "46000000000001",
                        "action_type": "TonTransfer",
                        "asset": "TON",
                        "raw_amount": "2500000000",
                        "decimals": 9,
                        "direction": "out",
                        "counterparty": "EQdest",
                        "sender": "EQwallet",
                        "recipient": "EQdest",
                        "jetton_address": None,
                        "jetton_symbol": None,
                        "status": "ok",
                        "source": "tonapi",
                    }
                ],
                "preview_count": 1,
                "total_transfers": 1,
                "total_events": 1,
            },
            source="real",
            message="TonAPI account transfer history fetched from events.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_events_preview",
        fake_get_account_events_preview,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["transfers"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert body["status"] == "success"
    assert body["data_mode"] == "real"
    assert body["unavailable_surfaces"] == []
    assert body["provider_evidence"][0]["source_status"] == "live"
    assert body["provider_evidence"][0]["raw_count"] == 1
    assert body["provider_evidence"][0]["normalized_count"] == 1
    assert body["balances"] == []
    assert len(body["transfers"]) == 1
    transfer = body["transfers"][0]
    assert transfer["asset"] == "TON"
    assert transfer["direction"] == "out"
    assert transfer["amount"] == "2.500000000000000000"
    assert transfer["counterparty"] == "EQdest"
    assert transfer["provider"] == "tonapi"
    assert transfer["source_status"] == "live"
    assert transfer["raw"]["surface"] == "transfers"

    read_back = client.get(f"/api/wallets/ingest/{run_id}")
    assert read_back.status_code == 200
    assert len(read_back.json()["transfers"]) == 1


def test_wallet_ingestion_guarded_tonapi_live_persists_dex_swaps(
    client,
    monkeypatch,
):
    def fake_get_account_swaps_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "swaps": [
                    {
                        "event_id": "evtswap",
                        "utime": 1717236000,
                        "lt": "46000000000002",
                        "dex": "stonfi",
                        "token_in": "TON",
                        "raw_amount_in": "5000000000",
                        "decimals_in": 9,
                        "token_out": "EJT",
                        "raw_amount_out": "123450000",
                        "decimals_out": 6,
                        "router": "EQrouter",
                        "status": "ok",
                        "source": "tonapi",
                    }
                ],
                "preview_count": 1,
                "total_swaps": 1,
                "total_events": 1,
            },
            source="real",
            message="TonAPI account DEX swaps fetched from events.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_swaps_preview",
        fake_get_account_swaps_preview,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["swaps"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert body["status"] == "success"
    assert body["unavailable_surfaces"] == []
    assert body["provider_evidence"][0]["source_status"] == "live"
    assert body["provider_evidence"][0]["normalized_count"] == 1
    assert len(body["swaps"]) == 1
    swap = body["swaps"][0]
    assert swap["dex"] == "stonfi"
    assert swap["token_in"] == "TON"
    assert swap["amount_in"] == "5.000000000000000000"
    assert swap["token_out"] == "EJT"
    assert swap["amount_out"] == "123.450000000000000000"
    assert swap["estimated_usd"] is None
    assert swap["source_status"] == "live"
    assert swap["raw"]["surface"] == "swaps"

    read_back = client.get(f"/api/wallets/ingest/{run_id}")
    assert read_back.status_code == 200
    assert len(read_back.json()["swaps"]) == 1


def test_wallet_ingestion_persists_mock_activity_and_can_read_run(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "7d",
            "surfaces": [
                "transfers",
                "transactions",
                "swaps",
                "balances",
                "jettons",
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == 1
    assert body["status"] == "success"
    assert body["data_mode"] == "mock"
    assert body["provider_evidence"][0]["source_status"] == "mock"
    assert len(body["transfers"]) == 3
    assert len(body["transactions"]) == 3
    assert len(body["swaps"]) == 1
    assert len(body["balances"]) == 3
    assert len(body["warnings"]) == 4
    assert body["transfers"][0]["amount"] == "125.500000000000000000"
    assert body["swaps"][0]["dex"] == "STON.fi"
    assert body["balances"][1]["asset"] == "JETTON_ALPHA"

    read_response = client.get(f"/api/wallets/ingest/{body['run_id']}")

    assert read_response.status_code == 200
    read_body = read_response.json()
    assert read_body["run_id"] == body["run_id"]
    assert read_body["wallet_address"] == "EQwallet"
    assert len(read_body["transfers"]) == 3
    assert len(read_body["warnings"]) == 4


def test_wallet_ingestion_respects_requested_surfaces(client, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["balances"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_surfaces"] == ["balances"]
    assert body["transfers"] == []
    assert body["transactions"] == []
    assert body["swaps"] == []
    assert [item["asset"] for item in body["balances"]] == ["TON"]
    assert body["provider_evidence"][0]["raw_count"] == 1


def test_wallet_ingestion_custom_window_invalid_order_returns_400(client):
    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "custom",
            "custom_start": "2026-06-02T00:00:00Z",
            "custom_end": "2026-06-01T00:00:00Z",
            "surfaces": ["transfers"],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "custom_end must be after custom_start"


def test_wallet_ingestion_missing_run_returns_404(client):
    response = client.get("/api/wallets/ingest/404")

    assert response.status_code == 404
    assert response.json()["detail"] == "Wallet ingestion run not found"
