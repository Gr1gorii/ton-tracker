"""Tests for USD valuation of swap legs via historical prices (never Real PnL)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from services.pnl_usd_valuation import derive_run_pnl_preview_with_historical


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


def _requirement(result: dict, code: str) -> dict:
    return next(req for req in result["requirements"] if req["code"] == code)


# --- Pure-function tests ------------------------------------------------------


def test_usd_valuation_matches_mock_points_and_flips_requirement(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    run = {
        "transactions": [{"success": "success"}],
        "swaps": [
            {
                "token_in": "TON",
                "amount_in": "10",
                "token_out": "JETA",
                "amount_out": "100",
                "timestamp": "2026-06-01T10:00:00Z",
            },
            {
                "token_in": "JETA",
                "amount_in": "30",
                "token_out": "TON",
                "amount_out": "6",
                "timestamp": "2026-06-02T10:00:00Z",
            },
        ],
    }
    result = derive_run_pnl_preview_with_historical(run)

    # Mock daily points start one day before the first swap: 2.50, 2.51, ...
    assert result["usd_flows"] == [
        {
            "token": "JETA",
            "usd_spent": "25.10",
            "usd_received": "15.12",
            "net_usd_flow": "-9.98",
            "matched_swap_count": 2,
        }
    ]
    assert result["total_usd_spent"] == "25.10"
    assert result["total_usd_received"] == "15.12"
    assert result["net_usd_flow"] == "-9.98"

    evidence = result["historical_pricing"]
    assert evidence["source_status"] == "mock"
    assert evidence["swaps_matched"] == 2
    assert evidence["swaps_unmatched"] == 0
    assert evidence["points_fetched"] == 4

    prices_req = _requirement(result, "historical_prices")
    assert prices_req["available"] is True
    assert prices_req["reason"] is None
    # Cost basis and fee handling still block Real PnL.
    assert _requirement(result, "cost_basis")["available"] is False
    assert _requirement(result, "fee_handling")["available"] is False
    assert result["real_pnl_locked"] is True
    assert result["is_real_pnl"] is False
    assert len(result["missing_evidence"]) == 2


def test_partial_match_keeps_requirement_missing(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    run = {
        "swaps": [
            {
                "token_in": "TON",
                "amount_in": "10",
                "token_out": "JETA",
                "amount_out": "100",
                "timestamp": "2026-06-01T10:00:00Z",
            },
            {
                "token_in": "TON",
                "amount_in": "5",
                "token_out": "JETA",
                "amount_out": "50",
                "timestamp": "not-a-date",
            },
        ],
    }
    result = derive_run_pnl_preview_with_historical(run)

    assert result["historical_pricing"]["swaps_matched"] == 1
    assert result["historical_pricing"]["swaps_unmatched"] == 1
    prices_req = _requirement(result, "historical_prices")
    assert prices_req["available"] is False
    assert "Only 1 of 2" in prices_req["reason"]
    assert any("no historical price point" in w for w in result["warnings"])


def test_no_parseable_timestamps_reports_unavailable(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    run = {
        "swaps": [
            {"token_in": "TON", "amount_in": "1", "token_out": "JETA",
             "amount_out": "2"},
        ],
    }
    result = derive_run_pnl_preview_with_historical(run)

    assert result["historical_pricing"]["source_status"] == "unavailable"
    assert result["historical_pricing"]["swaps_unmatched"] == 1
    assert _requirement(result, "historical_prices")["available"] is False
    assert "usd_flows" not in result  # no valuation was possible


def test_no_ton_side_legs_keeps_preview_untouched(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    result = derive_run_pnl_preview_with_historical(
        {"run_id": 1, "wallet_address": "EQidle"}
    )

    assert result["pnl_mode"] == "insufficient_data"
    assert result["historical_pricing"]["source_status"] == "unavailable"
    assert "No TON-side swap legs" in result["historical_pricing"]["note"]
    assert _requirement(result, "historical_prices")["available"] is False


# --- Endpoint integration tests ----------------------------------------------


def _ingest_mock_run(client, monkeypatch) -> dict:
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)
    return client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "7d",
            "surfaces": ["transfers", "transactions", "swaps", "balances", "jettons"],
        },
    ).json()


def test_endpoint_include_historical_values_mock_swap(client, monkeypatch):
    run = _ingest_mock_run(client, monkeypatch)

    response = client.get(
        f"/api/wallets/ingest/{run['run_id']}/pnl-preview",
        params={"include_historical": "true"},
    )

    assert response.status_code == 200
    body = response.json()
    # The mock swap spends 15 TON at the day-1 mock point (2.51 USD/TON).
    assert body["usd_flows"] == [
        {
            "token": "JETTON_ALPHA",
            "usd_spent": "37.65000000000000000000",
            "usd_received": "0",
            "net_usd_flow": "-37.65000000000000000000",
            "matched_swap_count": 1,
        }
    ]
    assert body["historical_pricing"]["source_status"] == "mock"
    assert body["real_pnl_locked"] is True

    prices_req = next(
        req for req in body["requirements"] if req["code"] == "historical_prices"
    )
    assert prices_req["available"] is True


def test_endpoint_default_stays_offline_without_usd_fields(client, monkeypatch):
    run = _ingest_mock_run(client, monkeypatch)

    response = client.get(f"/api/wallets/ingest/{run['run_id']}/pnl-preview")

    assert response.status_code == 200
    body = response.json()
    assert body["usd_flows"] == []
    assert body["historical_pricing"] is None
    assert body["total_usd_spent"] is None
    prices_req = next(
        req for req in body["requirements"] if req["code"] == "historical_prices"
    )
    assert prices_req["available"] is False
