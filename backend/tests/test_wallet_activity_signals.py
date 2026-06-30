"""Tests for the rule-based wallet evidence signal layer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from services.wallet_activity_signals import derive_run_signals


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


def _signal_codes(result: dict) -> set[str]:
    return {signal["code"] for signal in result["signals"]}


# --- Pure-function rule tests -------------------------------------------------


def test_clean_run_produces_no_signals():
    run = {
        "run_id": 1,
        "wallet_address": "EQclean",
        "transfers": [
            {"counterparty": "EQa"},
            {"counterparty": "EQb"},
            {"counterparty": "EQc"},
        ],
        "transactions": [
            {"success": "success"},
            {"success": "success"},
            {"success": "success"},
        ],
        "balances": [{"asset": "TON"}, {"asset": "JET1"}],
    }
    result = derive_run_signals(run)
    assert result["is_risk_score"] is False
    assert result["signals"] == []
    assert set(result["evaluated"]) == {
        "transfer_counterparty_concentration",
        "failed_transaction_ratio",
        "many_distinct_jettons",
    }


def test_counterparty_concentration_fires_with_evidence():
    run = {
        "run_id": 2,
        "wallet_address": "EQconc",
        "transfers": [
            {"counterparty": "EQhub"},
            {"counterparty": "EQhub"},
            {"counterparty": "EQhub"},
            {"counterparty": "EQother"},
        ],
    }
    result = derive_run_signals(run)
    signals = {s["code"]: s for s in result["signals"]}
    assert "transfer_counterparty_concentration" in signals
    signal = signals["transfer_counterparty_concentration"]
    assert signal["strength"] == "moderate"  # 3/4 = 0.75 -> moderate
    assert signal["evidence"]["counterparty"] == "EQhub"
    assert signal["evidence"]["transfer_count"] == 3
    assert signal["evidence"]["total_with_counterparty"] == 4
    assert "not proof of risk" in signal["note"]


def test_counterparty_concentration_strength_scales():
    run = {
        "transfers": [{"counterparty": "EQhub"} for _ in range(9)]
        + [{"counterparty": "EQother"}],
    }
    signal = next(
        s
        for s in derive_run_signals(run)["signals"]
        if s["code"] == "transfer_counterparty_concentration"
    )
    # 9/10 = 0.9 -> strong
    assert signal["strength"] == "strong"


def test_counterparty_concentration_ignored_below_threshold():
    run = {
        "transfers": [
            {"counterparty": "EQa"},
            {"counterparty": "EQb"},
            {"counterparty": "EQc"},
        ],
    }
    assert "transfer_counterparty_concentration" not in _signal_codes(
        derive_run_signals(run)
    )


def test_failed_transaction_ratio_fires():
    run = {
        "transactions": [
            {"success": "failed"},
            {"success": "failed"},
            {"success": "success"},
            {"success": "success"},
        ],
    }
    signal = next(
        s
        for s in derive_run_signals(run)["signals"]
        if s["code"] == "failed_transaction_ratio"
    )
    assert signal["evidence"] == {"failed": 2, "total": 4, "share": 0.5}
    assert signal["strength"] == "weak"  # 0.5 -> not > 0.6


def test_many_distinct_jettons_fires():
    balances = [{"asset": "TON"}] + [
        {"asset": f"JET{i}"} for i in range(12)
    ]
    run = {"balances": balances}
    signal = next(
        s
        for s in derive_run_signals(run)["signals"]
        if s["code"] == "many_distinct_jettons"
    )
    assert signal["evidence"]["distinct_jetton_count"] == 12
    assert signal["strength"] == "weak"


# --- Endpoint integration tests ----------------------------------------------


def test_signals_endpoint_on_clean_mock_run(client, monkeypatch):
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

    response = client.get(f"/api/wallets/ingest/{run['run_id']}/signals")

    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == run["run_id"]
    assert body["wallet_address"] == "EQwallet"
    assert body["is_risk_score"] is False
    assert len(body["evaluated"]) == 3
    # The deterministic mock wallet is clean: distinct counterparties, no
    # failed transactions, only two jettons.
    assert body["signals"] == []
    assert "not a risk score" in body["note"]


def test_signals_endpoint_missing_run_returns_404(client):
    response = client.get("/api/wallets/ingest/999999/signals")
    assert response.status_code == 404
