"""Tests for mock-normalized wallet activity ingestion endpoints."""

from __future__ import annotations

import csv
import io
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
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
VALID_TRANSACTION_HASH = "ab" * 32
EVENT_ACTION_IDENTITY_VERSION = "tonapi_event_action_obs_v1"
WALLET_TABLES = (
    "wallet_ingestion_runs",
    "wallet_transfers",
    "wallet_transactions",
    "wallet_swaps",
    "wallet_balance_snapshots",
    "wallet_ingestion_warnings",
    "wallet_acquisition_streams",
    "wallet_acquisition_pages",
)


def _wallet_table_counts(engine) -> tuple[int, ...]:
    with engine.connect() as connection:
        return tuple(
            connection.execute(text(f"SELECT COUNT(*) FROM {table_name}")).scalar_one()
            for table_name in WALLET_TABLES
        )


def _event_page(
    account_address: str,
    limit: int,
    before_lt: str | None,
    start_date: int | None,
    end_date: int | None,
    events: list[dict],
) -> ProviderResult:
    logical_times = [int(event["lt"], 10) for event in events]
    minimum = str(min(logical_times)) if logical_times else None
    maximum = str(max(logical_times)) if logical_times else None
    return ProviderResult.success(
        {
            "wallet_address": account_address,
            "requested_limit": limit,
            "request_before_lt": before_lt,
            "request_start_date": start_date,
            "request_end_date": end_date,
            "raw_count": len(events),
            "min_logical_time": minimum,
            "max_logical_time": maximum,
            "next_before_lt": minimum,
            "events": events,
        },
        source="real",
        message="TonAPI account event page fetched for display evidence.",
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
    app.state.wallet_ingestion_test_engine = engine
    try:
        yield TestClient(app)
    finally:
        del app.state.wallet_ingestion_test_engine
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


def test_wallet_ingestion_rejects_oversized_wallet_address(client):
    response = client.post(
        "/api/wallets/ingest/preview",
        json={
            "wallet_address": "E" * 129,
            "time_window": "24h",
            "surfaces": ["transactions"],
        },
    )

    assert response.status_code == 422


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
    calls = []

    def fake_get_account_transactions_page(
        self,
        account_address,
        limit,
        before_lt=None,
    ):
        calls.append(before_lt)
        transactions = []
        if before_lt is None:
            transactions = [
                {
                    "tx_hash": VALID_TRANSACTION_HASH.upper(),
                    "logical_time": "46000000000001",
                    "utime": 1717236000,
                    "total_fees": "4200000",
                    "success": True,
                    "transaction_type": "TransOrd",
                    "source": "tonapi",
                }
            ]
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "requested_limit": limit,
                "request_before_lt": before_lt,
                "raw_count": len(transactions),
                "min_logical_time": (
                    "46000000000001" if transactions else None
                ),
                "max_logical_time": (
                    "46000000000001" if transactions else None
                ),
                "next_before_lt": (
                    "46000000000001" if transactions else None
                ),
                "transactions": transactions,
            },
            source="real",
            message="TonAPI account transaction page fetched.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_transactions_page",
        fake_get_account_transactions_page,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": VALID_MAINNET_WALLET,
            "time_window": "custom",
            "custom_start": "2024-06-01T00:00:00Z",
            "custom_end": "2024-06-02T00:00:00Z",
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
    assert calls == [None, "46000000000001"]
    assert body["incomplete_surfaces"] == []
    stream = body["acquisition_streams"][0]
    assert stream["completion_state"] == "complete"
    assert stream["termination_reason"] == "provider_terminal"
    assert stream["bounds_verified"] is True
    assert stream["requested_start"] == "2024-06-01T00:00:00Z"
    assert stream["requested_end"] == "2024-06-02T00:00:00Z"
    assert stream["page_count"] == 2
    assert stream["pages_succeeded"] == 2
    assert [page["page_index"] for page in stream["pages"]] == [1, 2]
    assert len(body["transactions"]) == 1
    tx = body["transactions"][0]
    assert tx["tx_hash"] == VALID_TRANSACTION_HASH.upper()
    assert tx["fee_ton"] == "0.004200000000000000"
    assert tx["success"] == "success"
    assert tx["provider"] == "tonapi"
    assert tx["source_status"] == "live"
    assert tx["raw"]["surface"] == "transactions"
    assert tx["transaction_identity"] == {
        "status": "network_scoped",
        "version": "ton_account_tx_v1",
        "network": "ton-mainnet",
        "account_canonical": VALID_MAINNET_CANONICAL,
        "logical_time_canonical": "46000000000001",
        "hash_canonical": VALID_TRANSACTION_HASH,
        "key": (
            "ton_account_tx_v1|ton-mainnet|"
            f"{VALID_MAINNET_CANONICAL}|46000000000001|"
            f"{VALID_TRANSACTION_HASH}"
        ),
        "is_deduplication_identity": True,
        "is_blockchain_proof_verified": False,
        "is_ownership_proof": False,
        "deduplication_applied": False,
        "used_by_pnl": False,
    }

    # The persisted run round-trips through GET with the live transaction row.
    read_back = client.get(f"/api/wallets/ingest/{run_id}")
    assert read_back.status_code == 200
    read_body = read_back.json()
    assert len(read_body["transactions"]) == 1
    assert read_body["transactions"][0]["tx_hash"] == VALID_TRANSACTION_HASH.upper()
    assert (
        read_body["transactions"][0]["transaction_identity"]
        == tx["transaction_identity"]
    )
    assert read_body["acquisition_streams"] == body["acquisition_streams"]


def test_wallet_ingestion_rejects_duplicate_transaction_identity_within_run(
    client,
    monkeypatch,
):
    from adapters.wallet_activity import (
        WalletActivityAdapterResult,
        WalletActivityProviderEvidence,
        WalletActivityTransaction,
    )

    transaction = WalletActivityTransaction(
        tx_hash=VALID_TRANSACTION_HASH,
        logical_time="46000000000001",
        timestamp="2024-06-01T10:00:00Z",
        fee_ton="0.0042",
        success="success",
        provider="tonapi",
        source_status="live",
        raw={
            "provider": "tonapi",
            "surface": "transactions",
            "tx_hash": VALID_TRANSACTION_HASH,
            "logical_time": "46000000000001",
        },
    )

    class DuplicateAdapter:
        def ingest(self, request):
            return WalletActivityAdapterResult(
                status="success",
                data_mode="real",
                requested_surfaces=["transactions"],
                provider_evidence=[
                    WalletActivityProviderEvidence(
                        provider="tonapi_wallet_activity_live",
                        data_mode="real",
                        source_status="live",
                        warnings=[],
                        freshness="2024-06-02T00:00:00Z",
                        raw_count=2,
                        normalized_count=2,
                    )
                ],
                unavailable_surfaces=[],
                warnings=[],
                message="Duplicate transaction identity fixture.",
                transactions=[transaction, transaction],
            )

    monkeypatch.setattr(
        "services.wallet_activity_ingestion.build_wallet_activity_adapter",
        lambda settings: DuplicateAdapter(),
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": VALID_MAINNET_WALLET,
            "time_window": "custom",
            "custom_start": "2024-06-01T00:00:00Z",
            "custom_end": "2024-06-02T00:00:00Z",
            "surfaces": ["transactions"],
        },
    )

    assert response.status_code == 400
    assert "duplicate canonical identity" in response.json()["detail"]


def test_wallet_ingestion_persists_page_cap_as_incomplete_evidence(
    client,
    monkeypatch,
):
    calls = []
    logical_times = ["46000000000003", "46000000000002"]

    def fake_get_account_transactions_page(
        self,
        account_address,
        limit,
        before_lt=None,
    ):
        calls.append(before_lt)
        index = len(calls) - 1
        logical_time = logical_times[index]
        transaction = {
            "tx_hash": f"{index + 1:064x}",
            "logical_time": logical_time,
            "utime": 1717236000 - index * 60,
            "total_fees": "1000000",
            "success": True,
            "transaction_type": "TransOrd",
            "source": "tonapi",
        }
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "requested_limit": limit,
                "request_before_lt": before_lt,
                "raw_count": 1,
                "min_logical_time": logical_time,
                "max_logical_time": logical_time,
                "next_before_lt": logical_time,
                "transactions": [transaction],
            },
            source="real",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_transactions_page",
        fake_get_account_transactions_page,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_TX_LIMIT", "1")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_TX_MAX_PAGES", "2")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": VALID_MAINNET_WALLET,
            "time_window": "custom",
            "custom_start": "2024-06-01T00:00:00Z",
            "custom_end": "2024-06-02T00:00:00Z",
            "surfaces": ["transactions"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert body["provider_evidence"][0]["source_status"] == "limited"
    assert body["incomplete_surfaces"] == ["transactions"]
    assert len(body["transactions"]) == 2
    assert calls == [None, "46000000000003"]
    stream = body["acquisition_streams"][0]
    assert stream["completion_state"] == "incomplete"
    assert stream["termination_reason"] == "page_cap_reached"
    assert stream["bounds_verified"] is False
    assert stream["page_count"] == 2
    assert stream["pages_succeeded"] == 2
    assert stream["terminal_cursor"] == "46000000000002"
    assert len(stream["pages"]) == 2
    assert all(len(page["response_digest"]) == 64 for page in stream["pages"])

    read_back = client.get(f"/api/wallets/ingest/{body['run_id']}")
    assert read_back.status_code == 200
    assert read_back.json()["acquisition_streams"] == body["acquisition_streams"]

    pnl = client.get(f"/api/wallets/ingest/{body['run_id']}/pnl-preview")
    assert pnl.status_code == 200
    assert pnl.json()["is_real_pnl"] is False


def test_wallet_transaction_preview_is_one_page_and_explicitly_incomplete(
    client,
    monkeypatch,
):
    calls = []

    def fake_get_account_transactions_page(
        self,
        account_address,
        limit,
        before_lt=None,
    ):
        calls.append(before_lt)
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "requested_limit": limit,
                "request_before_lt": before_lt,
                "raw_count": 1,
                "min_logical_time": "46000000000003",
                "max_logical_time": "46000000000003",
                "next_before_lt": "46000000000003",
                "transactions": [
                    {
                        "tx_hash": "01" * 32,
                        "logical_time": "46000000000003",
                        "utime": 1717236000,
                        "total_fees": "1000000",
                        "success": True,
                        "source": "tonapi",
                    }
                ],
            },
            source="real",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_transactions_page",
        fake_get_account_transactions_page,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_TX_MAX_PAGES", "10")

    response = client.post(
        "/api/wallets/ingest/preview",
        json={
            "wallet_address": VALID_MAINNET_WALLET,
            "time_window": "custom",
            "custom_start": "2024-06-01T00:00:00Z",
            "custom_end": "2024-06-02T00:00:00Z",
            "surfaces": ["transactions"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == [None]
    assert body["success"] is True
    assert body["incomplete_surfaces"] == ["transactions"]
    stream = body["acquisition_streams"][0]
    assert stream["completion_state"] == "preview_only"
    assert stream["termination_reason"] == "preview_page_limit"
    assert stream["bounds_verified"] is False
    assert stream["page_count"] == 1
    assert stream["pages_succeeded"] == 1


def test_wallet_ingestion_guarded_tonapi_live_persists_transfer_history(
    client,
    monkeypatch,
):
    calls: list[str | None] = []
    event = {
        "event_id": "33" * 32,
        "timestamp": 1717236000,
        "lt": "46000000000001",
        "in_progress": False,
        "actions": [
            {
                "type": "TonTransfer",
                "status": "ok",
                "TonTransfer": {
                    "amount": "2500000000",
                    "sender": {"address": VALID_MAINNET_WALLET},
                    "recipient": {"address": "EQdest"},
                },
            }
        ],
    }

    def fake_get_account_events_page(
        self,
        account_address,
        limit,
        before_lt=None,
        start_date=None,
        end_date=None,
    ):
        calls.append(before_lt)
        assert (start_date, end_date) == (1717200000, 1717286400)
        rows = [event] if before_lt is None else []
        return _event_page(
            account_address,
            limit,
            before_lt,
            start_date,
            end_date,
            rows,
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_events_page",
        fake_get_account_events_page,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": VALID_MAINNET_WALLET,
            "time_window": "custom",
            "custom_start": "2024-06-01T00:00:00Z",
            "custom_end": "2024-06-02T00:00:00Z",
            "surfaces": ["transfers"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert calls == [None, "46000000000001"]
    assert body["status"] == "partial"
    assert body["data_mode"] == "real"
    assert body["unavailable_surfaces"] == []
    assert body["incomplete_surfaces"] == ["transfers"]
    assert body["provider_evidence"][0]["source_status"] == "limited"
    assert body["provider_evidence"][0]["raw_count"] == 1
    assert body["provider_evidence"][0]["normalized_count"] == 1
    assert len(body["acquisition_streams"]) == 1
    stream = body["acquisition_streams"][0]
    assert stream["stream_key"] == "account_events"
    assert stream["completion_state"] == "complete"
    assert stream["termination_reason"] == "provider_terminal"
    assert stream["bounds_verified"] is True
    assert stream["page_count"] == 2
    assert stream["pages_succeeded"] == 2
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
    assert transfer["raw"]["action_index"] == 0
    identity = transfer["event_action_identity"]
    assert identity["status"] == "provider_scoped"
    assert identity["version"] == EVENT_ACTION_IDENTITY_VERSION
    assert identity["provider"] == "tonapi"
    assert identity["network"] == "ton-mainnet"
    assert identity["account_canonical"] == VALID_MAINNET_CANONICAL
    assert identity["event_id_canonical"] == "33" * 32
    assert identity["logical_time_canonical"] == "46000000000001"
    assert identity["action_index"] == 0
    assert identity["action_type"] == "TonTransfer"
    assert identity["is_provider_observation_identity"] is True
    assert identity["is_authoritative_activity_identity"] is False
    assert identity["eligible_for_cost_basis"] is False
    assert identity["used_by_pnl"] is False

    read_back = client.get(f"/api/wallets/ingest/{run_id}")
    assert read_back.status_code == 200
    read_body = read_back.json()
    assert len(read_body["transfers"]) == 1
    assert read_body["incomplete_surfaces"] == ["transfers"]
    assert len(read_body["acquisition_streams"]) == 1
    assert read_body["acquisition_streams"][0]["stream_key"] == "account_events"
    assert read_body["acquisition_streams"][0]["page_count"] == 2
    assert read_body["transfers"][0]["event_action_identity"] == identity

    export_response = client.get(
        f"/api/wallets/ingest/{run_id}/export.csv"
    )
    assert export_response.status_code == 200
    export_rows = list(csv.DictReader(io.StringIO(export_response.text)))
    transfer_rows = [
        row for row in export_rows if row["surface"] == "transfer"
    ]
    assert len(transfer_rows) == 1
    assert transfer_rows[0]["event_action_identity_status"] == "provider_scoped"
    assert transfer_rows[0]["event_action_identity_version"] == (
        EVENT_ACTION_IDENTITY_VERSION
    )
    assert transfer_rows[0]["event_action_index"] == "0"
    assert transfer_rows[0]["event_action_type"] == "TonTransfer"
    assert transfer_rows[0]["event_action_identity_key"] == identity["key"]
    assert (
        transfer_rows[0]["event_action_is_provider_observation_identity"]
        == "True"
    )
    assert transfer_rows[0]["event_action_used_by_pnl"] == "False"


def test_wallet_ingestion_guarded_tonapi_live_persists_dex_swaps(
    client,
    monkeypatch,
):
    calls: list[str | None] = []
    event = {
        "event_id": "44" * 32,
        "timestamp": 1717236000,
        "lt": "46000000000002",
        "in_progress": False,
        "actions": [
            {
                "type": "JettonSwap",
                "status": "ok",
                "JettonSwap": {
                    "dex": "stonfi",
                    "ton_in": "5000000000",
                    "amount_out": "123450000",
                    "jetton_master_out": {
                        "address": "EQjetton",
                        "symbol": "EJT",
                        "decimals": 6,
                    },
                    "router": {"address": "EQrouter"},
                },
            }
        ],
    }

    def fake_get_account_events_page(
        self,
        account_address,
        limit,
        before_lt=None,
        start_date=None,
        end_date=None,
    ):
        calls.append(before_lt)
        assert (start_date, end_date) == (1717200000, 1717286400)
        rows = [event] if before_lt is None else []
        return _event_page(
            account_address,
            limit,
            before_lt,
            start_date,
            end_date,
            rows,
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_events_page",
        fake_get_account_events_page,
    )
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    response = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": VALID_MAINNET_WALLET,
            "time_window": "custom",
            "custom_start": "2024-06-01T00:00:00Z",
            "custom_end": "2024-06-02T00:00:00Z",
            "surfaces": ["swaps"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    run_id = body["run_id"]
    assert calls == [None, "46000000000002"]
    assert body["status"] == "partial"
    assert body["unavailable_surfaces"] == []
    assert body["incomplete_surfaces"] == ["swaps"]
    assert body["provider_evidence"][0]["source_status"] == "limited"
    assert body["provider_evidence"][0]["normalized_count"] == 1
    assert len(body["acquisition_streams"]) == 1
    stream = body["acquisition_streams"][0]
    assert stream["stream_key"] == "account_events"
    assert stream["completion_state"] == "complete"
    assert stream["termination_reason"] == "provider_terminal"
    assert stream["bounds_verified"] is True
    assert stream["page_count"] == 2
    assert stream["pages_succeeded"] == 2
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
    assert swap["raw"]["action_index"] == 0
    assert swap["raw"]["action_type"] == "JettonSwap"
    identity = swap["event_action_identity"]
    assert identity["status"] == "provider_scoped"
    assert identity["version"] == EVENT_ACTION_IDENTITY_VERSION
    assert identity["provider"] == "tonapi"
    assert identity["network"] == "ton-mainnet"
    assert identity["account_canonical"] == VALID_MAINNET_CANONICAL
    assert identity["event_id_canonical"] == "44" * 32
    assert identity["logical_time_canonical"] == "46000000000002"
    assert identity["action_index"] == 0
    assert identity["action_type"] == "JettonSwap"
    assert identity["is_provider_observation_identity"] is True
    assert identity["is_authoritative_activity_identity"] is False

    read_back = client.get(f"/api/wallets/ingest/{run_id}")
    assert read_back.status_code == 200
    read_swap = read_back.json()["swaps"][0]
    # Jetton master addresses survive persistence via the stored raw payload.
    assert read_swap["token_out_address"] == "EQjetton"
    assert read_swap["token_in_address"] is None
    assert read_swap["event_action_identity"] == identity
    read_streams = read_back.json()["acquisition_streams"]
    assert len(read_streams) == 1
    assert read_streams[0]["stream_key"] == "account_events"
    assert read_streams[0]["page_count"] == 2


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
    rows = list(csv.DictReader(io.StringIO(res.text)))
    transaction_rows = [row for row in rows if row["surface"] == "transaction"]
    assert transaction_rows
    assert all(
        row["transaction_identity_status"] == "unavailable"
        and row["transaction_identity_version"] == "unavailable"
        and row["transaction_network"] == "ton-unknown"
        and row["transaction_identity_key"] == ""
        for row in transaction_rows
    )
    event_action_rows = [
        row for row in rows if row["surface"] in {"transfer", "swap"}
    ]
    assert event_action_rows
    assert all(
        row["event_action_identity_status"] == "unavailable"
        and row["event_action_identity_version"] == "unavailable"
        and row["event_action_network"] == "ton-unknown"
        and row["event_action_identity_key"] == ""
        and row["event_action_is_provider_observation_identity"] == "False"
        and row["event_action_is_authoritative_activity_identity"] == "False"
        and row["event_action_used_by_pnl"] == "False"
        for row in event_action_rows
    )

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
    assert all(
        transaction["transaction_identity"]["status"] == "unavailable"
        and transaction["transaction_identity"]["key"] is None
        and transaction["transaction_identity"]["used_by_pnl"] is False
        for transaction in body["transactions"]
    )
    assert all(
        item["event_action_identity"]["status"] == "unavailable"
        and item["event_action_identity"]["key"] is None
        and item["event_action_identity"]["used_by_pnl"] is False
        for item in body["transfers"] + body["swaps"]
    )

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


def test_wallet_ingestion_custom_window_future_end_returns_400(client):
    response = client.post(
        "/api/wallets/ingest/preview",
        json={
            "wallet_address": "EQwallet",
            "time_window": "custom",
            "custom_start": "2999-01-01T00:00:00Z",
            "custom_end": "2999-01-02T00:00:00Z",
            "surfaces": ["transactions"],
        },
    )

    assert response.status_code == 400
    assert "cannot be later than acquisition time" in response.json()["detail"]


def test_wallet_ingestion_rolling_window_rejects_custom_fields(client):
    response = client.post(
        "/api/wallets/ingest/preview",
        json={
            "wallet_address": "EQwallet",
            "time_window": "24h",
            "custom_start": "2026-07-09T00:00:00Z",
            "surfaces": ["transactions"],
        },
    )

    assert response.status_code == 400
    assert "allowed only for custom windows" in response.json()["detail"]


def test_wallet_ingestion_missing_run_returns_404(client):
    response = client.get("/api/wallets/ingest/404")

    assert response.status_code == 404
    assert response.json()["detail"] == "Wallet ingestion run not found"


def test_wallet_ingestion_read_restores_exact_stored_request_scope(client, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    payload = {
        "wallet_address": VALID_MAINNET_WALLET,
        "time_window": "custom",
        "custom_start": "2026-06-01T00:00:00Z",
        "custom_end": "2026-06-02T00:00:00Z",
        "surfaces": ["transactions", "swaps"],
    }
    created = client.post("/api/wallets/ingest", json=payload)
    assert created.status_code == 200
    run_id = created.json()["run_id"]

    engine = app.state.wallet_ingestion_test_engine
    counts_before = _wallet_table_counts(engine)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.strip().upper())

    monkeypatch.setattr(
        "services.wallet_activity_ingestion.build_wallet_activity_adapter",
        lambda *_args, **_kwargs: pytest.fail(
            "reading a stored run must not build or call an ingestion provider"
        ),
    )
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        first_read = client.get(f"/api/wallets/ingest/{run_id}")
        second_read = client.get(f"/api/wallets/ingest/{run_id}")
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert first_read.status_code == 200
    assert second_read.status_code == 200
    assert second_read.json() == first_read.json()
    assert _wallet_table_counts(engine) == counts_before
    assert statements
    assert all(
        not statement.startswith(
            ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "ALTER", "DROP")
        )
        for statement in statements
    )
    body = first_read.json()
    assert body["run_id"] == run_id
    assert body["wallet_address"] == payload["wallet_address"]
    assert body["time_window"] == "custom"
    assert body["custom_start"] == payload["custom_start"]
    assert body["custom_end"] == payload["custom_end"]
    assert body["requested_surfaces"] == payload["surfaces"]
    assert body["created_at"].endswith("Z")


def test_wallet_ingestion_read_reports_null_custom_bounds_for_rolling_run(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "mock")
    created = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": VALID_MAINNET_WALLET,
            "time_window": "24h",
            "surfaces": ["transactions"],
        },
    )
    assert created.status_code == 200

    response = client.get(f"/api/wallets/ingest/{created.json()['run_id']}")

    assert response.status_code == 200
    body = response.json()
    assert body["time_window"] == "24h"
    assert body["custom_start"] is None
    assert body["custom_end"] is None


@pytest.mark.parametrize(
    "run_path",
    [
        "0",
        "-1",
        "abc",
        "true",
        "1.0",
        "01",
        "+1",
        "%201",
        str(2**63),
    ],
)
def test_wallet_ingestion_read_rejects_invalid_run_path(client, run_path):
    response = client.get(f"/api/wallets/ingest/{run_path}")

    assert response.status_code == 422


def test_wallet_ingestion_read_accepts_max_int64_as_canonical_missing_id(client):
    response = client.get(f"/api/wallets/ingest/{2**63 - 1}")

    assert response.status_code == 404
    assert response.json()["detail"] == "Wallet ingestion run not found"


def test_wallet_ingestion_catalog_empty_contract_is_private_and_terminal(client):
    response = client.get("/api/wallets/ingest")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "runs": [],
        "limit": 8,
        "truncated": False,
    }


def test_wallet_ingestion_catalog_returns_bounded_newest_first_metadata(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "mock")
    created = []
    for _index in range(9):
        response = client.post(
            "/api/wallets/ingest",
            json={
                "wallet_address": VALID_MAINNET_WALLET,
                "time_window": "24h",
                "surfaces": ["transactions"],
            },
        )
        assert response.status_code == 200
        created.append(response.json())

    response = client.get("/api/wallets/ingest?limit=8")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["limit"] == 8
    assert body["truncated"] is True
    assert [item["run_id"] for item in body["runs"]] == [
        str(item["run_id"]) for item in reversed(created[-8:])
    ]
    expected_keys = {
        "run_id",
        "wallet_hint",
        "time_window",
        "created_at",
        "status",
        "data_mode",
    }
    assert all(set(item) == expected_keys for item in body["runs"])
    latest = body["runs"][0]
    assert latest["wallet_hint"] == (
        f"{VALID_MAINNET_WALLET[:6]}…{VALID_MAINNET_WALLET[-4:]}"
    )
    assert latest["time_window"] == "24h"
    assert latest["created_at"] == created[-1]["created_at"]
    assert latest["status"] == created[-1]["status"]
    assert latest["data_mode"] == "mock"
    assert VALID_MAINNET_WALLET not in response.text


def test_wallet_ingestion_catalog_never_reconstructs_a_short_legacy_address(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "mock")
    created = client.post(
        "/api/wallets/ingest",
        json={
            "wallet_address": "EQshort",
            "time_window": "24h",
            "surfaces": ["transactions"],
        },
    )
    assert created.status_code == 200

    response = client.get("/api/wallets/ingest?limit=1")

    assert response.status_code == 200
    assert response.json()["runs"][0]["wallet_hint"] == "stored…run"
    assert "EQshort" not in response.text


def test_wallet_ingestion_catalog_mask_threshold_and_exact_limit(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "mock")
    for address in ("A" * 15, "B" * 16):
        response = client.post(
            "/api/wallets/ingest",
            json={
                "wallet_address": address,
                "time_window": "24h",
                "surfaces": ["transactions"],
            },
        )
        assert response.status_code == 200

    response = client.get("/api/wallets/ingest?limit=2")

    assert response.status_code == 200
    body = response.json()
    assert body["truncated"] is False
    assert [item["wallet_hint"] for item in body["runs"]] == [
        "BBBBBB…BBBB",
        "stored…run",
    ]


def test_wallet_ingestion_catalog_preserves_id_above_javascript_safe_range(
    client,
):
    from models import WalletIngestionRun

    engine = app.state.wallet_ingestion_test_engine
    session = sessionmaker(bind=engine)()
    try:
        session.add(
            WalletIngestionRun(
                id=9_007_199_254_740_993,
                wallet_address=VALID_MAINNET_WALLET,
                time_window="24h",
                data_mode="mock",
                status="success",
                requested_surfaces_json='["transactions"]',
                provider_summary_json="{}",
            )
        )
        session.commit()
    finally:
        session.close()

    response = client.get("/api/wallets/ingest?limit=1")

    assert response.status_code == 200
    assert response.json()["runs"][0]["run_id"] == "9007199254740993"


def test_wallet_ingestion_catalog_is_one_select_and_never_calls_provider(
    client,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "mock")
    for _index in range(3):
        created = client.post(
            "/api/wallets/ingest",
            json={
                "wallet_address": VALID_MAINNET_WALLET,
                "time_window": "24h",
                "surfaces": ["transfers", "transactions", "swaps", "balances"],
            },
        )
        assert created.status_code == 200

    engine = app.state.wallet_ingestion_test_engine
    counts_before = _wallet_table_counts(engine)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement.strip().upper())

    def forbidden_call(*_args, **_kwargs):
        pytest.fail("catalog reads must not build providers or load settings")

    monkeypatch.setattr(
        "services.wallet_activity_ingestion.build_wallet_activity_adapter",
        forbidden_call,
    )
    monkeypatch.setattr(
        "services.wallet_activity_ingestion.get_settings",
        forbidden_call,
    )
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        first = client.get("/api/wallets/ingest?limit=2")
        second = client.get("/api/wallets/ingest?limit=2")
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json() == first.json()
    assert _wallet_table_counts(engine) == counts_before
    assert len(statements) == 2
    assert all(statement.startswith("SELECT") for statement in statements)
    assert all("WALLET_INGESTION_RUNS" in statement for statement in statements)
    assert all(
        child_table not in statement
        for statement in statements
        for child_table in (
            "WALLET_TRANSFERS",
            "WALLET_TRANSACTIONS",
            "WALLET_SWAPS",
            "WALLET_BALANCE_SNAPSHOTS",
            "WALLET_INGESTION_WARNINGS",
        )
    )


@pytest.mark.parametrize(
    "query",
    [
        "limit=0",
        "limit=-1",
        "limit=01",
        "limit=%2B1",
        "limit=1.0",
        "limit=true",
        "limit=%201",
        "limit=51",
        "limit=999",
        "limit=",
        "limit=1&limit=2",
        "unknown=1",
        "limit=8&unknown=1",
        "LIMIT=8",
    ],
)
def test_wallet_ingestion_catalog_rejects_noncanonical_or_unknown_query(
    client,
    query,
):
    response = client.get(f"/api/wallets/ingest?{query}")

    assert response.status_code == 422


def test_wallet_ingestion_catalog_rejects_query_before_service_or_sql(
    client,
    monkeypatch,
):
    engine = app.state.wallet_ingestion_test_engine
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, _params, _context, _many):
        statements.append(statement)

    monkeypatch.setattr(
        "routers.wallet_activity.list_wallet_ingestion_runs",
        lambda **_kwargs: pytest.fail("invalid catalog query reached the service"),
    )
    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        for query in ("limit=0", "limit=8&limit=7", "unknown=1"):
            response = client.get(f"/api/wallets/ingest?{query}")
            assert response.status_code == 422
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert statements == []


@pytest.mark.parametrize("limit", [1, 50])
def test_wallet_ingestion_catalog_accepts_limit_boundaries(client, limit):
    response = client.get(f"/api/wallets/ingest?limit={limit}")

    assert response.status_code == 200
    assert response.json() == {
        "runs": [],
        "limit": limit,
        "truncated": False,
    }
