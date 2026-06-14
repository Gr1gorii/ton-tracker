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
            "surfaces": ["jettons", "swaps"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["data_mode"] == "real"
    assert body["unavailable_surfaces"] == ["swaps"]
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
