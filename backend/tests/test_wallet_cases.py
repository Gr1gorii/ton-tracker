"""Migrated-file API integration tests for the Wallet Case facade."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from adapters.wallet_activity import (
    MockWalletActivityAdapter,
    WalletActivityAdapterResult,
    WalletActivityProviderEvidence,
)
import services.wallet_cases as wallet_cases_module
from database import create_database_engine, get_session
from main import app
from models import CaseSync, WalletCase, WalletIngestionRun
from services.database_migrations import run_database_migrations
from services.wallet_cases import WalletCaseService, _compact_coverage_streams
from wallet_case_schemas import WalletCaseSyncRequest


ACCOUNT_ID = "ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e"
RAW_ADDRESS = f"0:{ACCOUNT_ID}"
RAW_ADDRESS_UPPER = f"0:{ACCOUNT_ID.upper()}"
BOUNCEABLE_MAINNET = "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF"
NON_BOUNCEABLE_MAINNET = "UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA"
BOUNCEABLE_TESTNET = "kQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPgpP"


@pytest.fixture
def client(tmp_path, monkeypatch):
    database_path = tmp_path / "wallet-cases.sqlite3"
    engine = create_database_engine(f"sqlite:///{database_path}")
    report = run_database_migrations(engine)
    assert report.revision_after == "20260710_0016"
    testing_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )

    def override_get_session():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_LIVE_ENABLED", raising=False)
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)
    app.dependency_overrides[get_session] = override_get_session
    app.state.wallet_case_test_engine = engine
    api = TestClient(app)
    try:
        yield api
    finally:
        app.dependency_overrides.clear()
        del app.state.wallet_case_test_engine
        engine.dispose()


def _create_case(
    client: TestClient,
    *,
    address: str = BOUNCEABLE_MAINNET,
    network: str = "ton-mainnet",
    environment: str = "demo",
    label: str | None = None,
    note: str | None = None,
) -> dict:
    response = client.post(
        "/api/v1/cases",
        json={
            "wallet_address": address,
            "network": network,
            "data_environment": environment,
            "label": label,
            "note": note,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _sync_case(
    client: TestClient,
    case_id: str,
    *,
    surfaces: list[str] | None = None,
) -> dict:
    response = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        json={
            "time_window": "24h",
            "surfaces": surfaces
            or ["transfers", "transactions", "swaps", "balances", "jettons"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _database_counts() -> tuple[int, int, int]:
    engine = app.state.wallet_case_test_engine
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(WalletCase)),
            session.scalar(select(func.count()).select_from(CaseSync)),
            session.scalar(select(func.count()).select_from(WalletIngestionRun)),
        )


def _configure_guarded_live_runtime(monkeypatch) -> None:
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_API_KEY", "test-tonapi-credential")


def test_case_create_is_canonical_idempotent_and_scope_separated(
    client,
    monkeypatch,
):
    first = _create_case(
        client,
        label="Primary wallet",
        note="Keep the first metadata values.",
    )
    reopened = _create_case(
        client,
        address=NON_BOUNCEABLE_MAINNET,
        label="Do not overwrite",
    )
    raw_reopened = _create_case(client, address=RAW_ADDRESS_UPPER)

    assert first["created"] is True
    assert reopened["created"] is False
    assert raw_reopened["created"] is False
    assert {
        first["case"]["public_id"],
        reopened["case"]["public_id"],
        raw_reopened["case"]["public_id"],
    } == {first["case"]["public_id"]}
    case = reopened["case"]
    assert case == {
        "public_id": first["case"]["public_id"],
        "network": "ton-mainnet",
        "data_environment": "demo",
        "canonical_wallet_key": RAW_ADDRESS,
        "identity_version": "ton_std_address_v1",
        "display_address": BOUNCEABLE_MAINNET,
        "label": "Primary wallet",
        "note": "Keep the first metadata values.",
        "created_at": first["case"]["created_at"],
        "updated_at": first["case"]["updated_at"],
        "latest_sync": None,
        "summary": {
            "activity_counts": {
                "transfers": 0,
                "transactions": 0,
                "swaps": 0,
                "balances": 0,
            },
            "failed_transaction_count": 0,
            "warning_count": 0,
            "portfolio_snapshot": {
                "total_balance_usd": None,
                "priced_assets": 0,
                "unpriced_assets": 0,
            },
        },
        "limitations": [
            {
                "code": "not_synchronized",
                "message": "This Wallet Case has not been synchronized yet.",
            }
        ],
    }

    testnet = _create_case(
        client,
        address=BOUNCEABLE_TESTNET,
        network="ton-testnet",
    )
    _configure_guarded_live_runtime(monkeypatch)
    live = _create_case(client, environment="live")
    assert len(
        {
            first["case"]["public_id"],
            testnet["case"]["public_id"],
            live["case"]["public_id"],
        }
    ) == 3
    assert _database_counts() == (3, 0, 0)

    catalog = client.get("/api/v1/cases?limit=3")
    assert catalog.status_code == 200
    assert catalog.headers["cache-control"] == "no-store"
    assert catalog.json()["limit"] == 3
    assert catalog.json()["truncated"] is False
    assert len(catalog.json()["cases"]) == 3


def test_case_create_rejects_invalid_or_mismatched_network_without_rows(client):
    invalid = client.post(
        "/api/v1/cases",
        json={
            "wallet_address": "EQnot-a-valid-wallet",
            "network": "ton-mainnet",
            "data_environment": "demo",
        },
    )
    mismatch = client.post(
        "/api/v1/cases",
        json={
            "wallet_address": BOUNCEABLE_TESTNET,
            "network": "ton-mainnet",
            "data_environment": "demo",
        },
    )

    assert invalid.status_code == 400
    assert mismatch.status_code == 400
    assert "network" in mismatch.json()["detail"].lower()
    assert _database_counts() == (0, 0, 0)


def test_wallet_case_facade_is_blocked_outside_direct_loopback(client):
    remote = TestClient(app, client=("203.0.113.10", 50000))
    try:
        status = remote.get(
            "/api/providers/status",
            headers={"X-Forwarded-For": "127.0.0.1"},
        )
        response = remote.post(
            "/api/v1/cases",
            headers={"X-Forwarded-For": "127.0.0.1"},
            json={
                "wallet_address": BOUNCEABLE_MAINNET,
                "network": "ton-mainnet",
                "data_environment": "demo",
            },
        )
    finally:
        remote.close()

    assert status.status_code == 200
    assert status.json()["wallet_cases_available"] is False
    assert response.status_code == 403
    assert "local-only" in response.json()["detail"]
    assert _database_counts() == (0, 0, 0)


def test_wallet_case_facade_rejects_dns_rebinding_host_on_loopback(client):
    rebound = TestClient(app, client=("127.0.0.1", 49152))
    try:
        status = rebound.get(
            "/api/providers/status",
            headers={
                "Host": "attacker.example:8000",
                "Origin": "http://attacker.example:8000",
            },
        )
        response = rebound.post(
            "/api/v1/cases",
            headers={
                "Host": "attacker.example:8000",
                "Origin": "http://attacker.example:8000",
            },
            json={
                "wallet_address": BOUNCEABLE_MAINNET,
                "network": "ton-mainnet",
                "data_environment": "demo",
            },
        )
        hostile_origin_status = rebound.get(
            "/api/providers/status",
            headers={
                "Host": "localhost:8000",
                "Origin": "http://attacker.example",
            },
        )
        hostile_origin_response = rebound.post(
            "/api/v1/cases",
            headers={
                "Host": "localhost:8000",
                "Origin": "http://attacker.example",
                "Content-Type": "text/plain",
            },
            content=json.dumps(
                {
                    "wallet_address": BOUNCEABLE_MAINNET,
                    "network": "ton-mainnet",
                    "data_environment": "demo",
                }
            ),
        )
    finally:
        rebound.close()

    assert status.status_code == 200
    assert status.json()["wallet_cases_available"] is False
    assert response.status_code == 403
    assert "local-only" in response.json()["detail"]
    assert hostile_origin_status.status_code == 200
    assert hostile_origin_status.json()["wallet_cases_available"] is False
    assert hostile_origin_response.status_code == 403
    assert _database_counts() == (0, 0, 0)


def test_demo_case_sync_links_legacy_run_and_restores_summary(client):
    created = _create_case(client)
    case_id = created["case"]["public_id"]

    sync = _sync_case(client, case_id)

    assert sync["state"] == "succeeded"
    assert sync["stage"] == "completed"
    assert sync["progress"] == {"current": 1, "total": 1}
    assert sync["provider"] == "mock_wallet_activity"
    assert sync["data_mode"] == "mock"
    assert sync["requested_scope"]["time_window"] == "24h"
    assert sync["requested_scope"]["surfaces"] == [
        "transfers",
        "transactions",
        "swaps",
        "balances",
        "jettons",
    ]
    assert sync["requested_scope"]["start_at"].endswith("Z")
    assert sync["requested_scope"]["end_at"].endswith("Z")
    assert sync["coverage"] == {
        "state": "unknown",
        "requested_start_at": sync["requested_scope"]["start_at"],
        "requested_end_at": sync["requested_scope"]["end_at"],
        "requested_surfaces": sync["requested_scope"]["surfaces"],
        "unavailable_surfaces": [],
        "incomplete_surfaces": [],
        "streams": [],
        "full_history_proven": False,
    }
    assert sync["summary"] == {
        "activity_counts": {
            "transfers": 3,
            "transactions": 3,
            "swaps": 1,
            "balances": 3,
        },
        "failed_transaction_count": 0,
        "warning_count": 4,
        "portfolio_snapshot": {
            "total_balance_usd": "950.42000000",
            "priced_assets": 3,
            "unpriced_assets": 0,
        },
    }
    limitation_codes = {item["code"] for item in sync["limitations"]}
    assert limitation_codes == {
        "bounded_interval_not_full_history",
        "demo_fixture_not_chain_data",
        "provider_display_events_not_authoritative",
        "snapshot_not_historical_cost_basis",
    }
    serialized = json.dumps(sync, sort_keys=True)
    assert "ingestion_run_id" not in serialized
    assert '"run_id"' not in serialized

    assert _database_counts() == (1, 1, 1)
    engine = app.state.wallet_case_test_engine
    with Session(engine) as session:
        stored_sync = session.scalar(select(CaseSync))
        assert stored_sync is not None
        assert stored_sync.ingestion_run_id is not None
        legacy_run_id = stored_sync.ingestion_run_id

    legacy = client.get(f"/api/wallets/ingest/{legacy_run_id}")
    assert legacy.status_code == 200
    assert legacy.json()["activity_summary"]["counts"] == {
        "transfers": 3,
        "transactions": 3,
        "swaps": 1,
        "balances": 3,
    }

    sync_read = client.get(
        f"/api/v1/cases/{case_id}/syncs/{sync['public_id']}"
    )
    assert sync_read.status_code == 200
    assert sync_read.json() == sync
    case_read = client.get(f"/api/v1/cases/{case_id}")
    assert case_read.status_code == 200
    assert case_read.headers["cache-control"] == "no-store"
    assert case_read.json()["latest_sync"] == sync
    assert case_read.json()["summary"] == sync["summary"]
    assert "ingestion_run_id" not in case_read.text
    assert '"run_id"' not in case_read.text


def test_sync_releases_the_case_read_transaction_before_provider_io(
    client,
    monkeypatch,
):
    created = _create_case(client)
    case_id = created["case"]["public_id"]
    engine = app.state.wallet_case_test_engine
    original_builder = wallet_cases_module.build_wallet_ingestion_run

    with Session(engine) as session:
        def checked_builder(*args, **kwargs):
            assert session.in_transaction() is False
            return original_builder(*args, **kwargs)

        monkeypatch.setattr(
            wallet_cases_module,
            "build_wallet_ingestion_run",
            checked_builder,
        )
        response = WalletCaseService(session).synchronize_case(
            case_id,
            WalletCaseSyncRequest(
                time_window="24h",
                surfaces=["transactions"],
            ),
        )

    assert response["state"] == "succeeded"
    assert _database_counts() == (1, 1, 1)


def test_orm_delete_cannot_detach_a_case_sync_from_its_source_run(client):
    created = _create_case(client)
    _sync_case(client, created["case"]["public_id"])
    engine = app.state.wallet_case_test_engine

    with Session(engine) as session:
        stored_sync = session.scalar(select(CaseSync))
        assert stored_sync is not None
        run_id = stored_sync.ingestion_run_id
        assert run_id is not None
        run = session.get(WalletIngestionRun, run_id)
        assert run is not None

        session.delete(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

        preserved_sync = session.get(CaseSync, stored_sync.id)
        assert session.get(WalletIngestionRun, run_id) is not None
        assert preserved_sync is not None
        assert preserved_sync.ingestion_run_id == run_id


def test_case_summary_never_mixes_an_older_success_with_latest_failure(client):
    created = _create_case(client)
    case_id = created["case"]["public_id"]
    successful = _sync_case(client, case_id)
    assert successful["summary"]["activity_counts"]["transactions"] > 0
    engine = app.state.wallet_case_test_engine
    completed_at = datetime.now(timezone.utc) + timedelta(seconds=1)
    requested_start = completed_at - timedelta(hours=24)
    with Session(engine) as session:
        wallet_case = session.scalar(
            select(WalletCase).where(WalletCase.public_id == case_id)
        )
        assert wallet_case is not None
        failed = CaseSync(
            case_id=wallet_case.id,
            ingestion_run_id=None,
            time_window="24h",
            data_mode="mock",
            provider="mock_wallet_activity",
            requested_start=requested_start,
            requested_end=completed_at,
            requested_surfaces_json='["transactions"]',
            state="failed",
            stage="failed",
            progress_current=1,
            progress_total=1,
            coverage_summary_json='{"state":"unknown"}',
            error_code="provider_error",
            error_detail_safe="The latest bounded sync failed.",
            created_at=completed_at,
            updated_at=completed_at,
            started_at=completed_at,
            completed_at=completed_at,
        )
        wallet_case.updated_at = completed_at
        session.add(failed)
        session.commit()

    case = client.get(f"/api/v1/cases/{case_id}").json()

    assert case["latest_sync"]["state"] == "failed"
    assert case["latest_sync"]["requested_scope"]["surfaces"] == [
        "transactions"
    ]
    assert case["summary"] == case["latest_sync"]["summary"]
    assert case["limitations"] == case["latest_sync"]["limitations"]
    assert case["summary"]["activity_counts"] == {
        "transfers": 0,
        "transactions": 0,
        "swaps": 0,
        "balances": 0,
    }
    limitation_codes = {item["code"] for item in case["limitations"]}
    assert "sync_failed" in limitation_codes
    assert "summary_unavailable" in limitation_codes
    assert "coverage_unavailable" in limitation_codes
    assert case["latest_sync"]["coverage"]["state"] == "unknown"
    assert case["latest_sync"]["coverage"]["requested_surfaces"] == [
        "transactions"
    ]


def test_live_case_rejects_incompatible_runtime_before_storage(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "services.wallet_cases.build_wallet_ingestion_run",
        lambda *_args, **_kwargs: pytest.fail(
            "incompatible live runtime must fail before adapter execution"
        ),
    )
    response = client.post(
        "/api/v1/cases",
        json={
            "wallet_address": BOUNCEABLE_MAINNET,
            "network": "ton-mainnet",
            "data_environment": "live",
        },
    )

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert "DATA_MODE=real" in response.json()["detail"]
    assert _database_counts() == (0, 0, 0)

    _configure_guarded_live_runtime(monkeypatch)
    unsupported_workchain = client.post(
        "/api/v1/cases",
        json={
            "wallet_address": f"1:{ACCOUNT_ID}",
            "network": "ton-mainnet",
            "data_environment": "live",
        },
    )
    assert unsupported_workchain.status_code == 400
    assert "workchains -1 and 0" in unsupported_workchain.json()["detail"]
    assert _database_counts() == (0, 0, 0)


def test_live_case_fails_closed_on_actual_mock_adapter_without_orphan(
    client,
    monkeypatch,
):
    _configure_guarded_live_runtime(monkeypatch)
    created = _create_case(client, environment="live")
    case_id = created["case"]["public_id"]
    monkeypatch.setattr(
        "services.wallet_activity_ingestion.build_wallet_activity_adapter",
        lambda _settings: MockWalletActivityAdapter(),
    )

    response = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        json={"time_window": "24h", "surfaces": ["transactions"]},
    )

    assert response.status_code == 409
    assert "data environment" in response.json()["detail"]
    assert _database_counts() == (1, 0, 0)


def test_live_partial_sync_remains_useful_and_never_claims_full_history(
    client,
    monkeypatch,
):
    _configure_guarded_live_runtime(monkeypatch)
    created = _create_case(client, environment="live")
    case_id = created["case"]["public_id"]

    class PartialLiveAdapter:
        def ingest(self, request):
            return WalletActivityAdapterResult(
                status="partial",
                data_mode="real",
                requested_surfaces=request.surfaces,
                provider_evidence=[
                    WalletActivityProviderEvidence(
                        provider="tonapi_wallet_activity_live",
                        data_mode="real",
                        source_status="limited",
                        warnings=["Bounded partial fixture."],
                        freshness=None,
                        raw_count=0,
                        normalized_count=0,
                    )
                ],
                unavailable_surfaces=[],
                incomplete_surfaces=["transactions"],
                warnings=[],
                message="A bounded partial result is available.",
            )

    monkeypatch.setattr(
        "services.wallet_activity_ingestion.build_wallet_activity_adapter",
        lambda _settings: PartialLiveAdapter(),
    )

    sync = _sync_case(client, case_id, surfaces=["transactions"])

    assert sync["state"] == "partial"
    assert sync["coverage"]["state"] == "bounded_partial"
    assert sync["coverage"]["full_history_proven"] is False
    assert sync["coverage"]["incomplete_surfaces"] == ["transactions"]
    assert "partial_or_unavailable_surfaces" in {
        item["code"] for item in sync["limitations"]
    }
    case = client.get(f"/api/v1/cases/{case_id}").json()
    assert case["summary"] == sync["summary"]
    assert case["latest_sync"]["state"] == "partial"


def test_case_coverage_streams_do_not_publish_request_or_page_diagnostics():
    streams = _compact_coverage_streams(
        [
            {
                "provider": "tonapi_wallet_activity_live",
                "stream_key": "account_transactions",
                "completion_state": "incomplete",
                "error_code": "page_cap_reached",
                "query_filters": {"account": "sensitive-provider-query"},
                "error_message": "unbounded provider diagnostic",
                "pages": [{"response_digest": "internal-page-digest"}],
            }
        ]
    )

    assert streams == [
        {
            "provider": "tonapi_wallet_activity_live",
            "stream_key": "account_transactions",
            "completion_state": "incomplete",
            "error_code": "page_cap_reached",
        }
    ]
    serialized = json.dumps(streams)
    assert "pages" not in serialized
    assert "query_filters" not in serialized
    assert "error_message" not in serialized


def test_sync_public_id_is_case_scoped_and_paths_are_strict(client):
    first = _create_case(client)
    second = _create_case(
        client,
        address=BOUNCEABLE_TESTNET,
        network="ton-testnet",
    )
    sync = _sync_case(client, first["case"]["public_id"], surfaces=["balances"])

    wrong_case = client.get(
        f"/api/v1/cases/{second['case']['public_id']}/syncs/{sync['public_id']}"
    )
    sequential_case = client.get("/api/v1/cases/1")
    uppercase_case = client.get(
        f"/api/v1/cases/{first['case']['public_id'].upper()}"
    )

    assert wrong_case.status_code == 404
    assert sequential_case.status_code == 422
    assert uppercase_case.status_code == 422
