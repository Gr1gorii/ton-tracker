"""Tests for the estimated PnL preview layer (never Real PnL)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from services.pnl_preview import derive_run_pnl_preview


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


def test_estimated_mode_computes_ton_denominated_flows():
    run = {
        "run_id": 7,
        "wallet_address": "EQtrader",
        "transactions": [{"success": "success"}],
        "swaps": [
            {"token_in": "TON", "amount_in": "10", "token_out": "JETA", "amount_out": "100"},
            {"token_in": "TON", "amount_in": "5", "token_out": "JETA", "amount_out": "50"},
            {"token_in": "JETA", "amount_in": "30", "token_out": "TON", "amount_out": "6"},
            {"token_in": "JETA", "amount_in": "1", "token_out": "JETB", "amount_out": "2"},
            {"token_in": "TON", "amount_in": None, "token_out": "JETA", "amount_out": "9"},
        ],
    }
    result = derive_run_pnl_preview(run)

    assert result["run_id"] == 7
    assert result["wallet_address"] == "EQtrader"
    assert result["pnl_mode"] == "estimated_onchain_pnl"
    assert result["confidence"] == "low"  # 3 usable swaps
    assert result["is_real_pnl"] is False
    assert result["real_pnl_locked"] is True
    assert result["swaps_used"] == 3
    assert result["swaps_excluded"] == 2

    assert len(result["token_flows"]) == 1
    flow = result["token_flows"][0]
    assert flow["token"] == "JETA"
    assert flow["buy_swap_count"] == 2
    assert flow["sell_swap_count"] == 1
    assert flow["token_bought_qty"] == "150"
    assert flow["token_sold_qty"] == "30"
    assert flow["ton_spent"] == "15"
    assert flow["ton_received"] == "6"
    assert flow["net_ton_flow"] == "-9"

    assert result["total_ton_spent"] == "15"
    assert result["total_ton_received"] == "6"
    assert result["net_ton_flow"] == "-9"
    assert any("excluded" in warning for warning in result["warnings"])
    assert "not Real PnL" in result["note"]


def test_estimated_confidence_capped_at_medium_with_volume():
    run = {
        "swaps": [
            {"token_in": "TON", "amount_in": "1", "token_out": f"JET{i}", "amount_out": "10"}
            for i in range(25)
        ],
    }
    result = derive_run_pnl_preview(run)
    assert result["pnl_mode"] == "estimated_onchain_pnl"
    # Never "high": fees, non-TON legs, and unrealized valuation are excluded.
    assert result["confidence"] == "medium"


def test_non_ton_swaps_only_locks_without_estimate():
    run = {
        "swaps": [
            {"token_in": "JETA", "amount_in": "1", "token_out": "JETB", "amount_out": "2"},
        ],
    }
    result = derive_run_pnl_preview(run)
    assert result["pnl_mode"] == "real_pnl_locked"
    assert result["confidence"] == "unavailable"
    assert result["token_flows"] == []
    assert any("historical prices" in warning for warning in result["warnings"])


def test_no_swaps_is_insufficient_data():
    result = derive_run_pnl_preview({"run_id": 1, "wallet_address": "EQidle"})
    assert result["pnl_mode"] == "insufficient_data"
    assert result["confidence"] == "unavailable"
    assert result["swaps_used"] == 0
    assert any("No DEX swap rows" in warning for warning in result["warnings"])


def test_real_pnl_requirements_stay_locked():
    run = {
        "transactions": [{"success": "success"}],
        "swaps": [
            {"token_in": "TON", "amount_in": "1", "token_out": "JETA", "amount_out": "2"},
        ],
    }
    result = derive_run_pnl_preview(run)

    assert len(result["requirements"]) == 5
    assert _requirement(result, "transaction_history")["available"] is True
    assert _requirement(result, "swap_evidence")["available"] is True
    for code in ("historical_prices", "cost_basis", "fee_handling"):
        requirement = _requirement(result, code)
        assert requirement["available"] is False
        assert requirement["reason"]
    assert result["real_pnl_locked"] is True
    assert result["is_real_pnl"] is False
    assert len(result["missing_evidence"]) == 3


def test_partial_token_quantity_warning():
    run = {
        "swaps": [
            {"token_in": "TON", "amount_in": "1", "token_out": "JETA", "amount_out": None},
            {"token_in": "TON", "amount_in": "2", "token_out": "JETA", "amount_out": "5"},
            {"token_in": "TON", "amount_in": "3", "token_out": "JETA", "amount_out": "5"},
        ],
    }
    result = derive_run_pnl_preview(run)
    assert result["swaps_used"] == 3
    assert result["token_flows"][0]["token_bought_qty"] == "10"
    assert any("token quantities are partial" in w for w in result["warnings"])


# --- Endpoint integration tests ----------------------------------------------


def test_pnl_preview_endpoint_on_mock_run(client, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)
    run = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "7d",
            "surfaces": ["transfers", "transactions", "swaps", "balances", "jettons"],
        },
    ).json()

    response = client.get(f"/api/wallets/ingest/{run['run_id']}/pnl-preview")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run["run_id"]
    assert body["pnl_mode"] == "estimated_onchain_pnl"  # one mock TON->jetton swap
    assert body["confidence"] == "low"
    assert body["is_real_pnl"] is False
    assert body["real_pnl_locked"] is True
    assert body["swaps_used"] == 1
    assert len(body["requirements"]) == 5
    assert len(body["missing_evidence"]) == 3
    assert "not Real PnL" in body["note"]


def test_pnl_preview_endpoint_missing_run_returns_404(client):
    response = client.get("/api/wallets/ingest/999999/pnl-preview")
    assert response.status_code == 404


def test_imported_trades_analysis_tagged_as_imported_pnl(client):
    clean = client.post(
        "/api/import/trades/analyze",
        json={
            "format": "csv",
            "content": (
                "tx_hash,block_time,wallet,side,token_amount,usd_amount\n"
                "tx1,2026-05-24T12:00:00Z,EQholder,buy,10,100"
            ),
            "preview_limit": 10,
        },
    )
    assert clean.status_code == 200
    body = clean.json()
    assert body["pnl_mode"] == "imported_pnl"
    assert body["pnl_confidence"] == "high"
    assert "not Real PnL" in body["pnl_note"]

    with_invalid = client.post(
        "/api/import/trades/analyze",
        json={
            "format": "csv",
            "content": (
                "tx_hash,block_time,wallet,side,token_amount,usd_amount\n"
                "tx1,2026-05-24T12:00:00Z,EQholder,buy,10,100\n"
                "tx2,not-a-date,EQholder,buy,10,100"
            ),
            "preview_limit": 10,
        },
    )
    assert with_invalid.status_code == 200
    assert with_invalid.json()["pnl_confidence"] == "medium"
