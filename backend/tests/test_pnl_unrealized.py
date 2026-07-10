"""Tests for the optional spot-based unrealized valuation (informational only)."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import services.pnl_unrealized as pnl_unrealized_module
from database import Base, get_session
from main import app
from services.export import wallet_pnl_preview_to_csv
from services.pnl_unrealized import derive_run_pnl_preview_with_unrealized


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


def _buy_run(**swap_overrides) -> dict:
    swap = {
        "token_in": "TON",
        "amount_in": "10",
        "token_out": "JETA",
        "token_out_address": "EQjetaMaster",
        "amount_out": "100",
        "timestamp": "2026-06-01T10:00:00Z",
    }
    swap.update(swap_overrides)
    return {"transactions": [{"success": "success"}], "swaps": [swap]}


# --- Pure-function tests ------------------------------------------------------


def test_mock_mode_values_remaining_holdings_deterministically(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    result = derive_run_pnl_preview_with_unrealized(_buy_run())

    record = result["unrealized"][0]
    assert record["status"] == "computed"
    assert record["priced_by"] == "mock"
    # Remaining 100 JETA at mock spot 0.06 = 6.00; in-window cost was
    # 10 TON @ 2.51 = 25.10 -> unrealized -19.10.
    assert Decimal(record["remaining_qty"]) == Decimal("100")
    assert Decimal(record["remaining_cost_usd"]) == Decimal("25.10")
    assert Decimal(record["spot_price_usd"]) == Decimal("0.06")
    assert Decimal(record["market_value_usd"]) == Decimal("6.00")
    assert Decimal(record["unrealized_pnl_usd"]) == Decimal("-19.10")
    assert Decimal(result["total_unrealized_pnl_usd"]) == Decimal("-19.10")
    assert "informational only" in result["unrealized_note"]
    assert "deterministic mock" in result["unrealized_note"]
    # Unrealized never touches the requirement checklist.
    assert result["real_pnl_locked"] is True


def test_missing_jetton_address_stays_visible_as_unavailable(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    result = derive_run_pnl_preview_with_unrealized(
        _buy_run(token_out_address=None)
    )

    record = result["unrealized"][0]
    assert record["status"] == "unavailable"
    assert "No jetton master address" in record["reason"]
    assert result["total_unrealized_pnl_usd"] is None


def test_zero_remaining_holdings_are_skipped(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    run = _buy_run()
    run["swaps"].append(
        {
            "token_in": "JETA",
            "token_in_address": "EQjetaMaster",
            "amount_in": "100",
            "token_out": "TON",
            "amount_out": "12",
            "timestamp": "2026-06-02T10:00:00Z",
        }
    )
    result = derive_run_pnl_preview_with_unrealized(run)

    assert result["unrealized"] == []
    assert result["total_unrealized_pnl_usd"] is None
    assert result["unrealized_note"] is None
    rows = list(csv.DictReader(io.StringIO(wallet_pnl_preview_to_csv(result))))
    coverage = next(
        row for row in rows if row["record_type"] == "unrealized_coverage"
    )
    assert coverage["priced_record_count"] == "0"
    assert coverage["unavailable_record_count"] == "0"
    assert "does not prove" in coverage["note"]
    assert not any(row["record_type"] == "unrealized" for row in rows)
    assert not any(
        row["record_type"] == "unrealized_subtotal" for row in rows
    )


def test_real_mode_uses_provider_prices_and_reports_unpriced(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    def fake_price_assets(assets, settings=None):
        assert assets == [{"asset": "JETA", "token": "EQjetaMaster"}]
        return {
            "currency": "usd",
            "prices": [
                {
                    "asset": "JETA",
                    "token": "EQjetaMaster",
                    "price_usd": "0.5",
                    "priced_by": "tonapi",
                }
            ],
            "unpriced": [],
            "warnings": ["TonAPI rates warning: sample"],
            "note": "n",
        }

    monkeypatch.setattr(
        pnl_unrealized_module, "price_assets", fake_price_assets
    )
    # Historical enrichment must not hit the network either.
    monkeypatch.setattr(
        "services.pnl_usd_valuation.build_historical_prices_preview",
        lambda token, start, end, settings=None: {
            "source_status": "real",
            "points": [
                {"timestamp": "2026-06-01T10:00:00Z", "price_usd": "2.0"}
            ],
            "warnings": [],
        },
    )

    result = derive_run_pnl_preview_with_unrealized(_buy_run())

    record = result["unrealized"][0]
    assert record["status"] == "computed"
    assert record["priced_by"] == "tonapi"
    assert "provider-reported spot" in result["unrealized_note"]
    # Remaining 100 at spot 0.5 = 50; cost 10 TON @ 2.0 = 20 -> +30.
    assert Decimal(record["unrealized_pnl_usd"]) == Decimal("30")
    assert any("TonAPI rates warning" in w for w in result["warnings"])

    def unpriced_price_assets(assets, settings=None):
        return {
            "currency": "usd",
            "prices": [
                {
                    "asset": "JETA",
                    "token": "EQjetaMaster",
                    "price_usd": None,
                    "priced_by": None,
                }
            ],
            "unpriced": ["JETA"],
            "warnings": [],
            "note": "n",
        }

    monkeypatch.setattr(
        pnl_unrealized_module, "price_assets", unpriced_price_assets
    )
    result = derive_run_pnl_preview_with_unrealized(_buy_run())
    record = result["unrealized"][0]
    assert record["status"] == "unavailable"
    assert "No provider spot price" in record["reason"]

    def zero_price_assets(assets, settings=None):
        return {
            "currency": "usd",
            "prices": [
                {
                    "asset": "JETA",
                    "token": "EQjetaMaster",
                    "price_usd": "0",
                    "priced_by": "tonapi",
                }
            ],
            "unpriced": [],
            "warnings": [],
            "note": "n",
        }

    # A zero provider price is treated as unpriced, not as "worth zero".
    monkeypatch.setattr(pnl_unrealized_module, "price_assets", zero_price_assets)
    result = derive_run_pnl_preview_with_unrealized(_buy_run())
    assert result["unrealized"][0]["status"] == "unavailable"


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


def test_endpoint_include_unrealized_values_mock_holdings(client, monkeypatch):
    run = _ingest_mock_run(client, monkeypatch)

    response = client.get(
        f"/api/wallets/ingest/{run['run_id']}/pnl-preview",
        params={"include_unrealized": "true"},
    )

    assert response.status_code == 200
    body = response.json()
    # include_unrealized implies the historical enrichment.
    assert body["historical_pricing"] is not None
    record = body["unrealized"][0]
    assert record["token"] == "JETTON_ALPHA"
    assert record["status"] == "computed"
    assert record["priced_by"] == "mock"
    # Remaining 3180 at mock spot 0.06 = 190.80; cost 15 TON @ 2.51 = 37.65.
    assert Decimal(record["market_value_usd"]) == Decimal("190.80")
    assert Decimal(record["unrealized_pnl_usd"]) == Decimal("153.15")
    assert Decimal(body["total_unrealized_pnl_usd"]) == Decimal("153.15")
    assert body["real_pnl_locked"] is True


def test_endpoint_default_has_no_unrealized_fields(client, monkeypatch):
    run = _ingest_mock_run(client, monkeypatch)

    response = client.get(f"/api/wallets/ingest/{run['run_id']}/pnl-preview")

    assert response.status_code == 200
    body = response.json()
    assert body["unrealized"] == []
    assert body["total_unrealized_pnl_usd"] is None
    assert body["unrealized_note"] is None


@pytest.mark.parametrize("include_historical", [False, True])
def test_json_export_include_unrealized_carries_spot_records(
    client, monkeypatch, include_historical
):
    run = _ingest_mock_run(client, monkeypatch)

    response = client.get(
        f"/api/wallets/ingest/{run['run_id']}/pnl-preview/export.json",
        params={
            "include_historical": str(include_historical).lower(),
            "include_unrealized": "true",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["historical_pricing"]["source_status"] == "mock"
    assert body["unrealized"][0]["token"] == "JETTON_ALPHA"
    assert body["unrealized"][0]["priced_by"] == "mock"
    assert Decimal(body["total_unrealized_pnl_usd"]) == Decimal("153.15")
    assert "deterministic mock" in body["unrealized_note"]


@pytest.mark.parametrize("include_historical", [False, True])
def test_csv_export_include_unrealized_has_record_and_summary(
    client, monkeypatch, include_historical
):
    run = _ingest_mock_run(client, monkeypatch)

    response = client.get(
        f"/api/wallets/ingest/{run['run_id']}/pnl-preview/export.csv",
        params={
            "include_historical": str(include_historical).lower(),
            "include_unrealized": "true",
        },
    )

    assert response.status_code == 200
    rows = list(csv.DictReader(io.StringIO(response.text)))
    unrealized = next(row for row in rows if row["record_type"] == "unrealized")
    coverage = next(
        row for row in rows if row["record_type"] == "unrealized_coverage"
    )
    subtotal = next(
        row for row in rows if row["record_type"] == "unrealized_subtotal"
    )
    assert unrealized["token"] == "JETTON_ALPHA"
    assert unrealized["status"] == "computed"
    assert unrealized["priced_by"] == "mock"
    assert Decimal(unrealized["unrealized_pnl_usd"]) == Decimal("153.15")
    assert coverage["priced_record_count"] == "1"
    assert coverage["unavailable_record_count"] == "0"
    assert "deterministic mock" in coverage["note"]
    assert Decimal(subtotal["total_unrealized_pnl_usd"]) == Decimal("153.15")
    assert "computed unrealized records only" in subtotal["note"]


def test_csv_unrealized_unavailable_record_is_not_dropped(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    result = derive_run_pnl_preview_with_unrealized(
        _buy_run(token_out_address=None)
    )

    rows = list(csv.DictReader(io.StringIO(wallet_pnl_preview_to_csv(result))))
    unrealized = next(row for row in rows if row["record_type"] == "unrealized")
    coverage = next(
        row for row in rows if row["record_type"] == "unrealized_coverage"
    )
    assert unrealized["status"] == "unavailable"
    assert "No jetton master address" in unrealized["reason"]
    assert coverage["priced_record_count"] == "0"
    assert coverage["unavailable_record_count"] == "1"
    assert not any(
        row["record_type"] == "unrealized_subtotal" for row in rows
    )


def test_csv_unrealized_mixed_coverage_subtotal_excludes_unavailable(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    run = _buy_run()
    run["swaps"].append(
        {
            "token_in": "TON",
            "amount_in": "5",
            "token_out": "JETB",
            "token_out_address": None,
            "amount_out": "50",
            "timestamp": "2026-06-02T10:00:00Z",
        }
    )
    result = derive_run_pnl_preview_with_unrealized(run)

    rows = list(csv.DictReader(io.StringIO(wallet_pnl_preview_to_csv(result))))
    unrealized = [row for row in rows if row["record_type"] == "unrealized"]
    coverage = next(
        row for row in rows if row["record_type"] == "unrealized_coverage"
    )
    subtotal = next(
        row for row in rows if row["record_type"] == "unrealized_subtotal"
    )
    assert {row["status"] for row in unrealized} == {"computed", "unavailable"}
    assert coverage["priced_record_count"] == "1"
    assert coverage["unavailable_record_count"] == "1"
    computed = next(row for row in unrealized if row["status"] == "computed")
    assert Decimal(subtotal["total_unrealized_pnl_usd"]) == Decimal(
        computed["unrealized_pnl_usd"]
    )


def test_csv_unrealized_zero_subtotal_is_preserved():
    rows = list(
        csv.DictReader(
            io.StringIO(
                wallet_pnl_preview_to_csv(
                    {
                        "unrealized": [
                            {
                                "token": "JETA",
                                "status": "computed",
                                "unrealized_pnl_usd": "0",
                            }
                        ],
                        "total_unrealized_pnl_usd": "0",
                        "unrealized_note": "Informational only.",
                        "requirements": [],
                    }
                )
            )
        )
    )
    subtotal = next(
        row for row in rows if row["record_type"] == "unrealized_subtotal"
    )
    assert subtotal["total_unrealized_pnl_usd"] == "0"
