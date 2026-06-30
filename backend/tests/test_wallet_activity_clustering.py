"""Tests for real wallet-pair clustering from persisted ingestion runs."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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


def _ingest_mock_wallet(client, monkeypatch, wallet_address, surfaces=None):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)
    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": wallet_address,
            "time_window": "7d",
            "surfaces": surfaces
            or ["transfers", "transactions", "swaps", "balances", "jettons"],
        },
    )
    assert response.status_code == 200
    return response.json()


def test_compare_two_identical_mock_wallets_scores_high(client, monkeypatch):
    run_a = _ingest_mock_wallet(client, monkeypatch, "EQalice")
    run_b = _ingest_mock_wallet(client, monkeypatch, "EQbob")

    response = client.post(
        "/api/wallets/cluster/compare",
        json={"run_ids": [run_a["run_id"], run_b["run_id"]]},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["is_cluster_proof"] is False
    assert "not proof of common ownership" in body["note"]
    assert len(body["wallets"]) == 2
    assert len(body["pairs"]) == 1

    wallet_a = next(w for w in body["wallets"] if w["run_id"] == run_a["run_id"])
    assert wallet_a["wallet_address"] == "EQalice"
    assert wallet_a["data_mode"] == "mock"
    assert wallet_a["buy_swap_count"] == 1
    assert wallet_a["sell_swap_count"] == 0
    assert Decimal(wallet_a["avg_ton_per_buy_swap"]) == Decimal("15")
    assert wallet_a["first_buy_at"] == "2026-06-01T10:35:00Z"
    assert set(wallet_a["distinct_tokens_touched"]) == {"JETTON_ALPHA", "JETTON_BETA"}
    assert Decimal(wallet_a["ton_balance"]) == Decimal("238.75")
    assert Decimal(wallet_a["portfolio_value_usd"]) == Decimal("950.42")
    assert wallet_a["warnings"] == []

    pair = body["pairs"][0]
    assert {pair["wallet_a_run_id"], pair["wallet_b_run_id"]} == {
        run_a["run_id"],
        run_b["run_id"],
    }
    # Identical deterministic mock fixtures behind both wallets -> top band.
    assert pair["score"] == 100.0
    assert pair["band"] == "very high similarity, still not proof"
    assert set(pair["shared_tokens"]) == {"JETTON_ALPHA", "JETTON_BETA"}
    assert "не доказательство" in pair["note"]


def test_compare_wallet_with_no_swaps_gets_warning_not_error(client, monkeypatch):
    run_no_swaps = _ingest_mock_wallet(
        client, monkeypatch, "EQnoswaps", surfaces=["balances", "jettons"]
    )
    run_with_swaps = _ingest_mock_wallet(client, monkeypatch, "EQbob")

    response = client.post(
        "/api/wallets/cluster/compare",
        json={"run_ids": [run_no_swaps["run_id"], run_with_swaps["run_id"]]},
    )

    assert response.status_code == 200
    body = response.json()
    wallet_no_swaps = next(
        w for w in body["wallets"] if w["run_id"] == run_no_swaps["run_id"]
    )
    assert wallet_no_swaps["buy_swap_count"] == 0
    assert wallet_no_swaps["sell_swap_count"] == 0
    assert wallet_no_swaps["avg_ton_per_buy_swap"] is None
    assert wallet_no_swaps["first_buy_at"] is None
    assert "No swaps observed" in wallet_no_swaps["warnings"][0]

    pair = body["pairs"][0]
    assert 0.0 <= pair["score"] <= 100.0


def test_compare_rejects_mixed_data_modes(client, monkeypatch):
    mock_run = _ingest_mock_wallet(client, monkeypatch, "EQalice")

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "scaffold")
    real_run = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQreal",
            "time_window": "24h",
            "surfaces": ["jettons"],
        },
    ).json()

    response = client.post(
        "/api/wallets/cluster/compare",
        json={"run_ids": [mock_run["run_id"], real_run["run_id"]]},
    )

    assert response.status_code == 400
    assert "mixed data modes" in response.json()["detail"]


def test_compare_unknown_run_id_returns_404(client, monkeypatch):
    run_a = _ingest_mock_wallet(client, monkeypatch, "EQalice")

    response = client.post(
        "/api/wallets/cluster/compare",
        json={"run_ids": [run_a["run_id"], 999999]},
    )

    assert response.status_code == 404


def test_compare_requires_at_least_two_run_ids(client):
    response = client.post(
        "/api/wallets/cluster/compare",
        json={"run_ids": [1]},
    )

    assert response.status_code == 422


def test_compare_caps_at_twenty_five_run_ids(client):
    response = client.post(
        "/api/wallets/cluster/compare",
        json={"run_ids": list(range(1, 27))},
    )

    assert response.status_code == 422


def test_cluster_comparison_json_export_download(client, monkeypatch):
    run_a = _ingest_mock_wallet(client, monkeypatch, "EQalice")
    run_b = _ingest_mock_wallet(client, monkeypatch, "EQbob")

    response = client.get(
        "/api/wallets/cluster/compare/export.json",
        params={"run_ids": [run_a["run_id"], run_b["run_id"]]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert (
        f"wallet_cluster_comparison_{run_a['run_id']}_{run_b['run_id']}.json"
        in disposition
    )

    body = response.json()
    assert body["is_cluster_proof"] is False
    assert len(body["wallets"]) == 2
    assert len(body["pairs"]) == 1
    assert "not proof of common ownership" in body["note"]


def test_cluster_comparison_json_export_unknown_run_returns_404(client, monkeypatch):
    run_a = _ingest_mock_wallet(client, monkeypatch, "EQalice")

    response = client.get(
        "/api/wallets/cluster/compare/export.json",
        params={"run_ids": [run_a["run_id"], 999999]},
    )

    assert response.status_code == 404


def test_cluster_comparison_json_export_requires_two_runs(client, monkeypatch):
    run_a = _ingest_mock_wallet(client, monkeypatch, "EQalice")

    response = client.get(
        "/api/wallets/cluster/compare/export.json",
        params={"run_ids": [run_a["run_id"]]},
    )

    assert response.status_code == 400


def test_cluster_comparison_csv_export_download(client, monkeypatch):
    run_a = _ingest_mock_wallet(client, monkeypatch, "EQalice")
    run_b = _ingest_mock_wallet(client, monkeypatch, "EQbob")

    response = client.get(
        "/api/wallets/cluster/compare/export.csv",
        params={"run_ids": [run_a["run_id"], run_b["run_id"]]},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    disposition = response.headers["content-disposition"]
    assert "attachment" in disposition
    assert (
        f"wallet_cluster_comparison_{run_a['run_id']}_{run_b['run_id']}.csv"
        in disposition
    )

    lines = response.text.strip().splitlines()
    assert lines[0] == (
        "wallet_a_run_id,wallet_a_address,wallet_b_run_id,"
        "wallet_b_address,score,band,shared_tokens"
    )
    # Two identical mock wallets -> one pair row scoring 100.
    assert len(lines) == 2
    assert lines[1].startswith(f"{run_a['run_id']},EQalice,{run_b['run_id']},EQbob,100.0")
    assert "JETTON_ALPHA|JETTON_BETA" in lines[1]


def test_cluster_comparison_csv_export_unknown_run_returns_404(client, monkeypatch):
    run_a = _ingest_mock_wallet(client, monkeypatch, "EQalice")

    response = client.get(
        "/api/wallets/cluster/compare/export.csv",
        params={"run_ids": [run_a["run_id"], 999999]},
    )

    assert response.status_code == 404


def test_cluster_comparison_csv_export_requires_two_runs(client, monkeypatch):
    run_a = _ingest_mock_wallet(client, monkeypatch, "EQalice")

    response = client.get(
        "/api/wallets/cluster/compare/export.csv",
        params={"run_ids": [run_a["run_id"]]},
    )

    assert response.status_code == 400
