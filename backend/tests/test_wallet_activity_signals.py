"""Tests for the rule-based wallet evidence signal layer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from services.export import wallet_run_signals_to_csv
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
            {"direction": "out", "counterparty": "EQa", "asset": "TON", "amount": "1.1"},
            {"direction": "out", "counterparty": "EQb", "asset": "TON", "amount": "2.2"},
            {"direction": "out", "counterparty": "EQc", "asset": "TON", "amount": "3.3"},
        ],
        "transactions": [
            {"success": "success", "timestamp": "2026-07-01T00:00:00Z"},
            {"success": "success", "timestamp": "2026-07-01T06:00:00Z"},
            {"success": "success", "timestamp": "2026-07-01T12:00:00Z"},
            {"success": "success", "timestamp": "2026-07-01T18:00:00Z"},
            {"success": "success", "timestamp": "2026-07-02T00:00:00Z"},
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
        "repeated_identical_transfer_amounts",
        "burst_transaction_activity",
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


def test_repeated_identical_transfer_amounts_fires():
    run = {
        "transfers": [
            {"asset": "JETX", "amount": "777.000000000000000000"},
            {"asset": "JETX", "amount": "777.000000000000000000"},
            {"asset": "JETX", "amount": "777.000000000000000000"},
            {"asset": "JETX", "amount": "777.000000000000000000"},
            {"asset": "TON", "amount": "1.500000000000000000"},
        ],
    }
    signal = _signal(
        derive_run_signals(run), "repeated_identical_transfer_amounts"
    )
    assert signal["evidence"]["asset"] == "JETX"
    assert signal["evidence"]["repeated_count"] == 4
    assert signal["evidence"]["total_with_amount"] == 5
    assert signal["confidence"] == "medium"  # 5 rows
    assert "not by itself" in signal["note"]


def test_repeated_identical_amounts_needs_majority_and_min_count():
    # Three distinct amounts -> highest repetition is 1 -> no signal.
    spread = derive_run_signals(
        {
            "transfers": [
                {"asset": "TON", "amount": "1"},
                {"asset": "TON", "amount": "2"},
                {"asset": "TON", "amount": "3"},
            ],
        }
    )
    assert "repeated_identical_transfer_amounts" not in _codes(spread["signals"])

    # Too few transfers carrying an amount -> insufficient evidence.
    weak = derive_run_signals({"transfers": [{"asset": "TON", "amount": "1"}]})
    assert "repeated_identical_transfer_amounts" in _codes(
        weak["insufficient_evidence"]
    )


def test_burst_transaction_activity_fires():
    run = {
        "transactions": [
            {"timestamp": f"2026-07-01T10:00:{second:02d}Z"} for second in range(10)
        ]
        + [{"timestamp": "2026-07-02T10:00:00Z"}],
    }
    signal = _signal(derive_run_signals(run), "burst_transaction_activity")
    assert signal["evidence"]["burst_transaction_count"] == 10
    assert signal["evidence"]["total_with_timestamp"] == 11
    assert signal["evidence"]["window_seconds"] == 600
    assert signal["confidence"] == "medium"  # 11 rows
    assert "not by itself" in signal["note"]


def test_burst_transaction_activity_quiet_and_insufficient_paths():
    # Ten transactions spread over ten hours -> no burst signal.
    spread = derive_run_signals(
        {
            "transactions": [
                {"timestamp": f"2026-07-01T{hour:02d}:00:00Z"} for hour in range(10)
            ],
        }
    )
    assert "burst_transaction_activity" not in _codes(spread["signals"])

    # Unparseable or missing timestamps -> insufficient evidence.
    weak = derive_run_signals(
        {
            "transactions": [
                {"timestamp": "not-a-date"},
                {"timestamp": None},
                {},
            ],
        }
    )
    assert "burst_transaction_activity" in _codes(weak["insufficient_evidence"])


def test_empty_run_is_all_insufficient_no_signals():
    result = derive_run_signals({"run_id": 9, "wallet_address": "EQempty"})
    assert result["signals"] == []
    assert _codes(result["insufficient_evidence"]) == {
        "single_counterparty_dominance",
        "high_outflow_concentration",
        "failed_transaction_ratio",
        "many_distinct_jettons",
        "repeated_identical_transfer_amounts",
        "burst_transaction_activity",
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
    assert len(body["evaluated"]) == 6
    # The deterministic mock wallet is clean: distinct counterparties, no
    # failed transactions, only two jettons. It has a single outgoing transfer,
    # so outflow concentration is reported as insufficient evidence.
    assert body["signals"] == []
    assert "high_outflow_concentration" in _codes(body["insufficient_evidence"])
    assert "not a risk score" in body["note"]


def test_signals_endpoint_missing_run_returns_404(client):
    response = client.get("/api/wallets/ingest/999999/signals")
    assert response.status_code == 404


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


def test_signals_json_export_download(client, monkeypatch):
    run = _ingest_mock_run(client, monkeypatch)

    response = client.get(f"/api/wallets/ingest/{run['run_id']}/signals/export.json")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert f"wallet_run_signals_{run['run_id']}.json" in disposition

    body = response.json()
    assert body["run_id"] == run["run_id"]
    assert body["is_risk_score"] is False
    assert "high_outflow_concentration" in _codes(body["insufficient_evidence"])
    assert "not a risk score" in body["note"]


def test_signals_csv_export_download(client, monkeypatch):
    run = _ingest_mock_run(client, monkeypatch)

    response = client.get(f"/api/wallets/ingest/{run['run_id']}/signals/export.csv")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert f"wallet_run_signals_{run['run_id']}.csv" in disposition

    lines = response.text.strip().splitlines()
    assert lines[0] == (
        "record_type,code,title,confidence,observation,evidence,reason"
    )
    # The deterministic mock wallet derives no signals; insufficient-evidence
    # records must still be visible in the export.
    data_rows = lines[1:]
    assert any(row.startswith("insufficient_evidence,") for row in data_rows)
    assert not any(row.startswith("signal,") for row in data_rows)


def test_wallet_run_signals_to_csv_flattens_signal_rows():
    csv_text = wallet_run_signals_to_csv(
        {
            "signals": [
                {
                    "code": "many_distinct_jettons",
                    "title": "Many distinct jettons held",
                    "confidence": "high",
                    "observation": "The wallet holds 100 distinct non-TON jettons.",
                    "evidence": {"distinct_jetton_count": 100},
                    "note": "Heuristic indicator only.",
                }
            ],
            "insufficient_evidence": [
                {"code": "failed_transaction_ratio", "reason": "No transactions."}
            ],
        }
    )

    lines = csv_text.strip().splitlines()
    assert lines[0] == (
        "record_type,code,title,confidence,observation,evidence,reason"
    )
    assert lines[1].startswith("signal,many_distinct_jettons,")
    assert "distinct_jetton_count=100" in lines[1]
    assert lines[2].startswith("insufficient_evidence,failed_transaction_ratio,")
    assert lines[2].endswith("No transactions.")


def test_signals_json_export_missing_run_returns_404(client):
    response = client.get("/api/wallets/ingest/999999/signals/export.json")
    assert response.status_code == 404


def test_signals_csv_export_missing_run_returns_404(client):
    response = client.get("/api/wallets/ingest/999999/signals/export.csv")
    assert response.status_code == 404
