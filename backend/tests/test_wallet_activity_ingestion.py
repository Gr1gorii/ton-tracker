"""Tests for mock-normalized wallet activity ingestion endpoints."""

from __future__ import annotations

from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from config import ProviderResult
from database import Base, get_session
from main import app


VALID_MAINNET_WALLET = "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF"
VALID_MAINNET_WALLET_NONBOUNCEABLE = (
    "UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA"
)
VALID_TESTNET_WALLET = "kQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPgpP"
VALID_MAINNET_CANONICAL = (
    "0:ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e"
)


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


def test_wallet_ingestion_persists_network_scoped_identity_variants(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setenv("TON_NETWORK", "mainnet")

    bodies = []
    for address in (VALID_MAINNET_WALLET, VALID_MAINNET_WALLET_NONBOUNCEABLE):
        response = client.post(
            "/api/wallets/ingest",
            json={
                "wallet_address": address,
                "time_window": "24h",
                "surfaces": ["transactions"],
            },
        )
        assert response.status_code == 200
        bodies.append(response.json())

    assert [body["wallet_address"] for body in bodies] == [
        VALID_MAINNET_WALLET,
        VALID_MAINNET_WALLET_NONBOUNCEABLE,
    ]
    assert {
        body["wallet_identity"]["canonical_address"] for body in bodies
    } == {VALID_MAINNET_CANONICAL}
    assert {body["wallet_identity"]["network"] for body in bodies} == {
        "ton-mainnet"
    }
    assert [body["wallet_identity"]["bounceable"] for body in bodies] == [
        True,
        False,
    ]
    assert all(
        body["wallet_identity"]["status"] == "network_scoped"
        and body["wallet_identity"]["is_account_existence_proof"] is False
        and body["wallet_identity"]["is_ownership_proof"] is False
        for body in bodies
    )


def test_mock_placeholder_identity_stays_explicitly_unavailable(client, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQfixtureOnly",
            "time_window": "24h",
            "surfaces": ["transactions"],
        },
    )

    assert response.status_code == 200
    identity = response.json()["wallet_identity"]
    assert identity["status"] == "unavailable"
    assert identity["network"] == "ton-unknown"
    assert identity["canonical_address"] is None
    assert identity["submitted_format"] == "unrecognized"


def test_guarded_live_tonapi_rejects_unavailable_wallet_identity(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQnotAValidTonAddress",
            "time_window": "24h",
            "surfaces": ["balances"],
        },
    )

    assert response.status_code == 400
    assert "valid standard TON wallet address" in response.json()["detail"]


def test_guarded_live_tonapi_rejects_official_host_network_mismatch(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TON_NETWORK", "testnet")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    def forbid_network(*args, **kwargs):
        raise AssertionError("Network must not be called for mismatched scope")

    monkeypatch.setattr(
        "adapters.tonapi.urllib.request.urlopen",
        forbid_network,
    )

    response = client.post(
        "/api/wallets/ingest/preview",
        json={
            "wallet_address": VALID_TESTNET_WALLET,
            "time_window": "24h",
            "surfaces": ["balances"],
        },
    )

    assert response.status_code == 400
    assert "base URL network does not match" in response.json()["detail"]


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
            "wallet_address": VALID_MAINNET_WALLET,
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
            "wallet_address": VALID_MAINNET_WALLET,
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

    def fake_price_assets(specs, settings):
        return {
            "prices": [
                {
                    "asset": spec["asset"],
                    "token": spec["token"],
                    "price_usd": "1.50" if spec["token"] == "ton" else None,
                    "priced_by": "tonapi" if spec["token"] == "ton" else None,
                }
                for spec in specs
            ],
            "unpriced": [],
            "warnings": [],
            "currency": "usd",
        }

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_balance_preview",
        fake_get_account_balance_preview,
    )
    monkeypatch.setattr(
        "services.wallet_activity_ingestion.price_assets", fake_price_assets
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": VALID_MAINNET_WALLET,
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
    assert body["balances"][0]["balance_usd"] == "3.75000000"
    assert body["balances"][0]["provider"] == "tonapi"
    assert body["balances"][0]["source_status"] == "live"
    assert body["balances"][0]["raw"]["surface"] == "balances"
    portfolio = body["activity_summary"]["balances"]["portfolio"]
    assert portfolio["priced_assets"] == 1
    assert Decimal(portfolio["total_balance_usd"]).quantize(
        Decimal("0.01")
    ) == Decimal("3.75")


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
            "wallet_address": VALID_MAINNET_WALLET,
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
            "wallet_address": VALID_MAINNET_WALLET,
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
                        "token_in_address": None,
                        "raw_amount_in": "5000000000",
                        "decimals_in": 9,
                        "token_out": "EJT",
                        "token_out_address": "EQjetton",
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
            "wallet_address": VALID_MAINNET_WALLET,
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
    assert swap["token_in_address"] is None
    assert swap["amount_in"] == "5.000000000000000000"
    assert swap["token_out"] == "EJT"
    assert swap["token_out_address"] == "EQjetton"
    assert swap["amount_out"] == "123.450000000000000000"
    assert swap["estimated_usd"] is None
    assert swap["source_status"] == "live"
    assert swap["raw"]["surface"] == "swaps"

    read_back = client.get(f"/api/wallets/ingest/{run_id}")
    assert read_back.status_code == 200
    read_swap = read_back.json()["swaps"][0]
    # Jetton master addresses survive persistence via the stored raw payload.
    assert read_swap["token_out_address"] == "EQjetton"
    assert read_swap["token_in_address"] is None


def test_wallet_ingestion_activity_summary_is_derived_and_labeled(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
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
    summary = response.json()["activity_summary"]

    assert summary["is_pnl"] is False
    assert "not pnl" in summary["note"].lower()
    assert summary["counts"] == {
        "transfers": 3,
        "transactions": 3,
        "swaps": 1,
        "balances": 3,
    }
    ton = next(
        item for item in summary["transfers_by_asset"] if item["asset"] == "TON"
    )
    assert ton["in_count"] == 1
    assert ton["out_count"] == 1
    assert Decimal(ton["net_amount"]) == Decimal("113.5")
    assert summary["swaps_by_dex"] == [{"dex": "STON.fi", "count": 1}]
    swap_ton = next(
        item for item in summary["swaps_by_token"] if item["token"] == "TON"
    )
    assert swap_ton["sent_count"] == 1
    assert Decimal(swap_ton["sent_amount"]) == Decimal("15")
    swap_alpha = next(
        item
        for item in summary["swaps_by_token"]
        if item["token"] == "JETTON_ALPHA"
    )
    assert swap_alpha["received_count"] == 1
    assert Decimal(swap_alpha["received_amount"]) == Decimal("3180")
    assert "TON" in summary["balances"]["assets"]
    portfolio = summary["balances"]["portfolio"]
    assert portfolio["priced_assets"] == 3
    assert portfolio["unpriced_assets"] == 0
    assert Decimal(portfolio["total_balance_usd"]).quantize(
        Decimal("0.01")
    ) == Decimal("950.42")


def test_price_balances_fills_usd_in_real_mode(monkeypatch):
    from adapters.wallet_activity import WalletActivityBalanceSnapshot
    from config import get_settings
    from services import wallet_activity_ingestion as svc

    def fake_price_assets(specs, settings):
        prices = []
        for spec in specs:
            if spec["token"] == "ton":
                prices.append({"asset": spec["asset"], "token": spec["token"],
                               "price_usd": "1.50", "priced_by": "tonapi"})
            elif spec["token"] == "EQjetton":
                prices.append({"asset": spec["asset"], "token": spec["token"],
                               "price_usd": "0.25", "priced_by": "geckoterminal"})
            else:
                prices.append({"asset": spec["asset"], "token": spec["token"],
                               "price_usd": None, "priced_by": None})
        return {"prices": prices, "unpriced": [], "warnings": [], "currency": "usd"}

    monkeypatch.setattr(svc, "price_assets", fake_price_assets)
    monkeypatch.setenv("DATA_MODE", "real")
    settings = get_settings()

    balances = [
        WalletActivityBalanceSnapshot(
            asset="TON", balance="2.000000000000000000", balance_usd=None,
            provider="tonapi", source_status="live", snapshot_at=None,
            raw={"surface": "balances", "normalized_balance_usd": None},
        ),
        WalletActivityBalanceSnapshot(
            asset="EJT", balance="100.000000000000000000", balance_usd=None,
            provider="tonapi", source_status="live", snapshot_at=None,
            raw={"surface": "jettons", "jetton_address": "EQjetton",
                 "normalized_balance_usd": None},
        ),
    ]

    out = svc._price_balances(balances, settings)
    assert out[0].balance_usd == "3.00000000"
    assert out[0].raw["normalized_balance_usd"] == "3.00000000"
    assert out[0].raw["priced_by"] == "tonapi"
    assert out[1].balance_usd == "25.00000000"
    assert out[1].raw["priced_by"] == "geckoterminal"


def test_price_balances_skips_in_mock_mode(monkeypatch):
    from adapters.wallet_activity import WalletActivityBalanceSnapshot
    from config import get_settings
    from services import wallet_activity_ingestion as svc

    def boom(specs, settings):  # must not be called in mock mode
        raise AssertionError("price_assets must not run in mock mode")

    monkeypatch.setattr(svc, "price_assets", boom)
    monkeypatch.setenv("DATA_MODE", "mock")
    settings = get_settings()

    balances = [
        WalletActivityBalanceSnapshot(
            asset="TON", balance="2.0", balance_usd=None, provider="mock",
            source_status="mock", snapshot_at=None, raw={},
        )
    ]
    out = svc._price_balances(balances, settings)
    assert out[0].balance_usd is None


def test_wallet_ingestion_run_json_export_download(client, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)

    run = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["transfers", "transactions", "swaps", "balances"],
        },
    )
    run_id = run.json()["run_id"]

    res = client.get(f"/api/wallets/ingest/{run_id}/export.json")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/json")
    disposition = res.headers["content-disposition"]
    assert "attachment" in disposition
    assert f"wallet_ingestion_run_{run_id}.json" in disposition
    body = res.json()
    assert body["run_id"] == run_id
    assert "activity_summary" in body

    missing = client.get("/api/wallets/ingest/99999/export.json")
    assert missing.status_code == 404


def test_wallet_ingestion_run_csv_export_download(client, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)

    run = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "surfaces": ["transfers", "transactions", "swaps", "balances"],
        },
    )
    run_id = run.json()["run_id"]

    res = client.get(f"/api/wallets/ingest/{run_id}/export.csv")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert f"wallet_ingestion_run_{run_id}.csv" in res.headers["content-disposition"]
    lines = res.text.splitlines()
    assert lines[0].split(",")[0] == "surface"
    assert any(line.startswith("transfer,") for line in lines[1:])
    assert any(line.startswith("swap,") for line in lines[1:])

    missing = client.get("/api/wallets/ingest/99999/export.csv")
    assert missing.status_code == 404


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
    assert body["swaps"][0]["token_out_address"] == "EQjettonAlphaMasterMock"
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
