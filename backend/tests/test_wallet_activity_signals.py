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


def _codes(items: list[dict]) -> set[str]:
    return {item["code"] for item in items}


def _signal(result: dict, code: str) -> dict:
    return next(s for s in result["signals"] if s["code"] == code)


# --- Pure-function rule tests -------------------------------------------------


def test_clean_run_produces_no_signals_and_no_insufficiency():
    run = {
        "run_id": 1,
        "wallet_address": "EQclean",
        "transfers": [
            {"direction": "out", "counterparty": "EQa"},
            {"direction": "out", "counterparty": "EQb"},
            {"direction": "out", "counterparty": "EQc"},
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
    assert result["insufficient_evidence"] == []
    assert set(result["evaluated"]) == {
        "single_counterparty_dominance",
        "high_outflow_concentration",
        "failed_transaction_ratio",
        "many_distinct_jettons",
    }


def test_single_counterparty_dominance_low_confidence_small_sample():
    run = {
        "transfers": [
            {"counterparty": "EQhub"},
            {"counterparty": "EQhub"},
            {"counterparty": "EQhub"},
            {"counterparty": "EQother"},
        ],
    }
    signal = _signal(derive_run_signals(run), "single_counterparty_dominance")
    # 3/4 = 0.75 pattern, but only 4 rows -> low confidence (volume-driven).
    assert signal["confidence"] == "low"
    assert signal["evidence"]["counterparty"] == "EQhub"
    assert signal["evidence"]["total_with_counterparty"] == 4
    assert "pseudonymous" in signal["note"]
    assert "not proof" in signal["note"]


def test_single_counterparty_dominance_high_confidence_large_sample():
    run = {
        "transfers": [{"counterparty": "EQhub"} for _ in range(9)]
        + [{"counterparty": "EQother"}],
    }
    signal = _signal(derive_run_signals(run), "single_counterparty_dominance")
    assert signal["confidence"] == "high"  # 10 rows


def test_single_counterparty_insufficient_when_too_few():
    run = {"transfers": [{"counterparty": "EQa"}, {"counterparty": "EQb"}]}
    result = derive_run_signals(run)
    assert "single_counterparty_dominance" not in _codes(result["signals"])
    assert "single_counterparty_dominance" in _codes(result["insufficient_evidence"])


def test_high_outflow_concentration_fires():
    run = {
        "transfers": [
            {"direction": "out", "counterparty": "EQsink"},
            {"direction": "out", "counterparty": "EQsink"},
            {"direction": "out", "counterparty": "EQsink"},
            {"direction": "out", "counterparty": "EQx"},
        ],
    }
    signal = _signal(derive_run_signals(run), "high_outflow_concentration")
    assert signal["evidence"]["counterparty"] == "EQsink"
    assert signal["evidence"]["total_outgoing"] == 4
    assert signal["confidence"] == "low"


def test_high_outflow_insufficient_when_direction_data_weak():
    run = {
        "transfers": [
            {"direction": "unknown", "counterparty": "EQa"},
            {"direction": "out", "counterparty": "EQb"},
        ],
    }
    result = derive_run_signals(run)
    insufficient = {i["code"]: i for i in result["insufficient_evidence"]}
    assert "high_outflow_concentration" in insufficient
    assert "outgoing" in insufficient["high_outflow_concentration"]["reason"]


def test_failed_transaction_ratio_fires_and_insufficient_path():
    fired = derive_run_signals(
        {
            "transactions": [
                {"success": "failed"},
                {"success": "failed"},
                {"success": "success"},
                {"success": "success"},
            ],
        }
    )
    signal = _signal(fired, "failed_transaction_ratio")
    assert signal["evidence"] == {"failed": 2, "total": 4, "share": 0.5}
    assert signal["confidence"] == "low"  # 4 transactions

    weak = derive_run_signals({"transactions": [{"success": "failed"}]})
    assert "failed_transaction_ratio" in _codes(weak["insufficient_evidence"])


def test_many_distinct_jettons_fires_and_insufficient_without_balances():
    fired = derive_run_signals(
        {"balances": [{"asset": "TON"}] + [{"asset": f"JET{i}"} for i in range(12)]}
    )
    signal = _signal(fired, "many_distinct_jettons")
    assert signal["evidence"]["distinct_jetton_count"] == 12
    assert signal["confidence"] == "low"

    none_ingested = derive_run_signals({"transfers": [], "transactions": []})
    assert "many_distinct_jettons" in _codes(none_ingested["insufficient_evidence"])


def test_empty_run_is_all_insufficient_no_signals():
    result = derive_run_signals({"run_id": 9, "wallet_address": "EQempty"})
    assert result["signals"] == []
    assert _codes(result["insufficient_evidence"]) == {
        "single_counterparty_dominance",
        "high_outflow_concentration",
        "failed_transaction_ratio",
        "many_distinct_jettons",
    }


# --- Endpoint integration tests ----------------------------------------------


def test_signals_endpoint_on_mock_run(client, monkeypatch):
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
    assert len(body["evaluated"]) == 4
    # The deterministic mock wallet is clean: distinct counterparties, no
    # failed transactions, only two jettons. It has a single outgoing transfer,
    # so outflow concentration is reported as insufficient evidence.
    assert body["signals"] == []
    assert "high_outflow_concentration" in _codes(body["insufficient_evidence"])
    assert "not a risk score" in body["note"]


def test_signals_endpoint_missing_run_returns_404(client):
    response = client.get("/api/wallets/ingest/999999/signals")
    assert response.status_code == 404
