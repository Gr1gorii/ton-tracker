"""Migrated-file API integration tests for the Wallet Case facade."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from threading import Barrier, Event, Thread
import time
from uuid import uuid4

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
from database import create_database_engine, get_session
from main import app
from models import (
    CaseEvidenceVerification,
    CaseSync,
    WalletCase,
    WalletCaseLifecycleEvent,
    WalletCaseReportRevision,
    WalletIngestionRun,
    WalletTransaction,
)
from services.database_migrations import run_database_migrations
from services.case_sync_jobs import CaseSyncWorker, _retry_signal
from services.wallet_activity_ingestion import build_wallet_ingestion_run
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
    assert report.revision_after == "20260710_0024"
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
    app.state.wallet_case_test_session = testing_session

    class ManualRunner:
        alive = True

        def notify(self):
            return None

    app.state.wallet_case_job_runner = ManualRunner()
    api = TestClient(app)
    try:
        yield api
    finally:
        app.dependency_overrides.clear()
        app.state.wallet_case_job_runner = None
        del app.state.wallet_case_test_engine
        del app.state.wallet_case_test_session
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
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "time_window": "24h",
            "surfaces": surfaces
            or ["transfers", "transactions", "swaps", "balances", "jettons"],
        },
    )
    assert response.status_code == 202, response.text
    sync_id = response.json()["public_id"]
    worker = CaseSyncWorker(app.state.wallet_case_test_session)
    assert worker.run_once() is True
    completed = client.get(f"/api/v1/cases/{case_id}/syncs/{sync_id}")
    assert completed.status_code == 200, completed.text
    return completed.json()


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
        "latest_sync_attempt": None,
        "active_sync": None,
        "current_snapshot": None,
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


def test_case_delete_removes_owned_data_preserves_legacy_rows_and_keeps_audit(
    client,
):
    target = _create_case(
        client,
        label="Delete this case",
        note="Sensitive operator note",
    )["case"]
    sibling = _create_case(
        client,
        address=BOUNCEABLE_TESTNET,
        network="ton-testnet",
        label="Keep this case",
    )["case"]
    completed = _sync_case(client, target["public_id"])
    captured = client.post(
        f"/api/v1/cases/{target['public_id']}/reports",
        json={"snapshot_public_id": completed["public_id"]},
    )
    assert captured.status_code == 201, captured.text

    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    with app.state.wallet_case_test_session() as session:
        legacy_run = WalletIngestionRun(
            wallet_address="legacy-unscoped-wallet",
            time_window="24h",
            data_mode="mock",
            status="succeeded",
            requested_surfaces_json="[]",
            provider_summary_json="{}",
            created_at=now,
            updated_at=now,
        )
        session.add(legacy_run)
        session.commit()
        legacy_run_id = legacy_run.id

    response = client.delete(f"/api/v1/cases/{target['public_id']}")

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["deleted"] is True
    assert payload["case_public_id"] == target["public_id"]
    assert payload["removed"] == {
        "syncs": 1,
        "ingestion_runs": 1,
        "evidence_verifications": 0,
        "report_revisions": 1,
    }
    assert client.get(f"/api/v1/cases/{target['public_id']}").status_code == 404
    assert client.delete(f"/api/v1/cases/{target['public_id']}").status_code == 404
    kept = client.get(f"/api/v1/cases/{sibling['public_id']}")
    assert kept.status_code == 200
    assert kept.json()["label"] == "Keep this case"

    with app.state.wallet_case_test_session() as session:
        assert session.scalar(select(func.count()).select_from(WalletCase)) == 1
        assert session.scalar(select(func.count()).select_from(CaseSync)) == 0
        assert session.scalar(
            select(func.count()).select_from(WalletCaseReportRevision)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(WalletIngestionRun)
        ) == 1
        assert session.get(WalletIngestionRun, legacy_run_id) is not None
        event = session.scalar(select(WalletCaseLifecycleEvent))
        assert event is not None
        assert event.public_id == payload["audit_event_public_id"]
        assert event.case_public_id == target["public_id"]
        assert json.loads(event.details_json) == {"removed": payload["removed"]}
        assert target["display_address"] not in event.details_json
        assert "Sensitive operator note" not in event.details_json

    recreated = _create_case(client)
    assert recreated["created"] is True
    assert recreated["case"]["public_id"] != target["public_id"]


def test_case_delete_rejects_active_sync_without_mutating_rows(client):
    case_id = _create_case(client)["case"]["public_id"]
    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    ).json()

    response = client.delete(f"/api/v1/cases/{case_id}")

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "case_delete_jobs_active",
        "message_safe": (
            "Cancel or wait for active Wallet Case jobs before deleting this case."
        ),
        "retryable": False,
        "active_sync_public_id": queued["public_id"],
        "active_evidence_public_id": None,
    }
    assert _database_counts() == (1, 1, 0)
    with app.state.wallet_case_test_session() as session:
        assert session.scalar(
            select(func.count()).select_from(WalletCaseLifecycleEvent)
        ) == 0


def test_case_delete_rejects_active_evidence_verification(client):
    case_id = _create_case(client)["case"]["public_id"]
    completed = _sync_case(client, case_id)
    now = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
    with app.state.wallet_case_test_session() as session:
        wallet_case = session.scalar(
            select(WalletCase).where(WalletCase.public_id == case_id)
        )
        case_sync = session.scalar(
            select(CaseSync).where(CaseSync.public_id == completed["public_id"])
        )
        transaction = session.scalar(
            select(WalletTransaction).where(
                WalletTransaction.run_id == case_sync.ingestion_run_id
            )
        )
        assert wallet_case is not None
        assert case_sync is not None
        assert transaction is not None
        verification = CaseEvidenceVerification(
            case_id=wallet_case.id,
            snapshot_sync_id=case_sync.id,
            source_sync_id=case_sync.id,
            source_transaction_id=transaction.id,
            activity_public_id=f"wca_{'ab' * 32}",
            activity_semantic_fingerprint="cd" * 32,
            policy="transaction_inclusion_v1",
            state="queued",
            stage="queued",
            progress_current=0,
            status_version=1,
            highest_evidence_level="normalized",
            provider="mock",
            network="ton-mainnet",
            wallet_account_canonical=RAW_ADDRESS,
            transaction_hash="ef" * 32,
            transaction_logical_time="1",
            idempotency_key=str(uuid4()),
            request_fingerprint="12" * 32,
            attempt_count=0,
            max_attempts=4,
            next_attempt_at=now,
            checkpoint_json="{}",
            message_safe="Queued for lifecycle conflict coverage.",
            created_at=now,
            updated_at=now,
        )
        session.add(verification)
        session.commit()
        verification_public_id = verification.public_id

    response = client.delete(f"/api/v1/cases/{case_id}")

    assert response.status_code == 409
    assert response.json()["detail"]["active_sync_public_id"] is None
    assert response.json()["detail"]["active_evidence_public_id"] == (
        verification_public_id
    )
    assert _database_counts() == (1, 1, 1)


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
    assert sync["progress"] == {"current": 3, "total": 3}
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
    original_builder = build_wallet_ingestion_run

    with Session(engine) as session:
        def checked_builder(*args, **kwargs):
            assert session.in_transaction() is False
            return original_builder(*args, **kwargs)

        queued, replayed = WalletCaseService(session).enqueue_sync(
            case_id,
            WalletCaseSyncRequest(
                time_window="24h",
                surfaces=["transactions"],
            ),
            str(uuid4()),
        )
        assert replayed is False
        assert queued["state"] == "queued"
        # Mirror FastAPI dependency cleanup before the detached worker runs.
        session.rollback()
        worker = CaseSyncWorker(
            app.state.wallet_case_test_session,
            builder=checked_builder,
        )
        assert worker.run_once() is True
        response = WalletCaseService(session).get_sync(
            case_id,
            queued["public_id"],
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
    assert case["latest_sync_attempt"] == case["latest_sync"]
    assert case["current_snapshot"]["public_id"] == successful["public_id"]
    assert case["summary"] == case["current_snapshot"]["summary"]
    assert case["summary"] == successful["summary"]
    assert "sync_failed" not in {
        item["code"] for item in case["limitations"]
    }
    assert case["latest_sync"]["coverage"]["state"] == "unknown"
    assert case["latest_sync"]["coverage"]["requested_surfaces"] == [
        "transactions"
    ]


def test_live_case_rejects_incompatible_runtime_before_storage(
    client,
    monkeypatch,
):
    monkeypatch.setattr(
        "services.wallet_activity_ingestion.build_wallet_ingestion_run",
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
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    )

    assert response.status_code == 202
    assert CaseSyncWorker(app.state.wallet_case_test_session).run_once() is True
    failed = client.get(
        f"/api/v1/cases/{case_id}/syncs/{response.json()['public_id']}"
    )
    assert failed.status_code == 200
    assert failed.json()["state"] == "failed"
    assert "data environment" in failed.json()["error"]["message_safe"]
    assert _database_counts() == (1, 1, 0)


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


def test_sync_enqueue_is_durable_idempotent_and_globally_pollable(client):
    case_id = _create_case(client)["case"]["public_id"]
    idempotency_key = str(uuid4())
    payload = {"time_window": "24h", "surfaces": ["transactions"]}

    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": idempotency_key},
        json=payload,
    )

    assert queued.status_code == 202
    assert queued.headers["location"].endswith(queued.json()["public_id"])
    assert queued.headers["retry-after"] == "1"
    job = queued.json()
    assert job["case_public_id"] == case_id
    assert job["state"] == "queued"
    assert job["stage"] == "queued"
    assert job["provider"] == "pending_provider_observation"
    assert job["result"] is None
    assert job["error"] is None
    assert job["retry"] is None
    assert {item["code"] for item in job["limitations"]}.isdisjoint(
        {"summary_unavailable", "coverage_unavailable"}
    )
    assert _database_counts() == (1, 1, 0)

    replay = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": idempotency_key},
        json=payload,
    )
    assert replay.status_code == 202
    assert replay.json() == job
    assert _database_counts() == (1, 1, 0)

    mismatch = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": idempotency_key},
        json={"time_window": "24h", "surfaces": ["balances"]},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["detail"]["code"] == "idempotency_conflict"
    active_conflict = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json=payload,
    )
    assert active_conflict.status_code == 409
    assert active_conflict.json()["detail"] == {
        "code": "case_sync_already_active",
        "message_safe": "This Wallet Case already has an active synchronization.",
        "retryable": False,
        "active_sync_public_id": job["public_id"],
    }
    assert _database_counts() == (1, 1, 0)
    assert client.get(f"/api/v1/jobs/{job['public_id']}").json() == job
    case_payload = client.get(f"/api/v1/cases/{case_id}").json()
    serialized_public_payloads = json.dumps(
        {"job": job, "case": case_payload},
        sort_keys=True,
    )
    for internal_name in (
        "lease_token",
        "lease_expires_at",
        "heartbeat_at",
        "idempotency_key",
        "request_fingerprint",
        "checkpoint_json",
        "attempt_count",
    ):
        assert internal_name not in serialized_public_payloads


def test_custom_idempotency_fingerprint_canonicalizes_equivalent_utc_instants(
    client,
):
    case_id = _create_case(client)["case"]["public_id"]
    idempotency_key = str(uuid4())
    first = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": idempotency_key},
        json={
            "time_window": "custom",
            "custom_start": "2026-08-01T00:00:00Z",
            "custom_end": "2026-08-02T00:00:00Z",
            "surfaces": ["transactions", "balances"],
        },
    )
    replay = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": idempotency_key},
        json={
            "time_window": "custom",
            "custom_start": "2026-08-01T02:00:00+02:00",
            "custom_end": "2026-08-02T02:00:00+02:00",
            "surfaces": ["balances", "transactions"],
        },
    )

    assert first.status_code == replay.status_code == 202
    assert replay.json()["public_id"] == first.json()["public_id"]
    assert _database_counts() == (1, 1, 0)


def test_concurrent_same_key_enqueue_converges_on_one_persisted_job(client):
    case_id = _create_case(client)["case"]["public_id"]
    idempotency_key = str(uuid4())
    barrier = Barrier(3)
    results: list[tuple[str, bool]] = []
    errors: list[Exception] = []

    def enqueue():
        try:
            with app.state.wallet_case_test_session() as session:
                barrier.wait()
                result, replayed = WalletCaseService(session).enqueue_sync(
                    case_id,
                    WalletCaseSyncRequest(
                        time_window="24h",
                        surfaces=["transactions"],
                    ),
                    idempotency_key,
                )
                results.append((result["public_id"], replayed))
        except Exception as exc:  # surfaced in the coordinator assertion
            errors.append(exc)

    threads = [Thread(target=enqueue, daemon=True), Thread(target=enqueue, daemon=True)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert all(thread.is_alive() is False for thread in threads)
    assert len(results) == 2
    assert len({public_id for public_id, _replayed in results}) == 1
    assert sorted(replayed for _public_id, replayed in results) == [False, True]
    assert _database_counts() == (1, 1, 0)


def test_same_key_commit_before_active_lookup_converges_to_replay(
    client,
    monkeypatch,
):
    case_id = _create_case(client)["case"]["public_id"]
    idempotency_key = str(uuid4())
    payload = WalletCaseSyncRequest(
        time_window="24h",
        surfaces=["transactions"],
    )
    session_b = app.state.wallet_case_test_session()
    service_b = WalletCaseService(session_b)
    original_active_lookup = service_b.repository.get_active_sync
    created_by_a: dict[str, str] = {}
    interleaved = False

    # Avoid shadowing the public UUID with the repository's internal case_id.
    public_case_id = case_id

    def active_after_commit(*, case_id: int):
        nonlocal interleaved
        if not interleaved:
            interleaved = True
            session_b.rollback()
            with app.state.wallet_case_test_session() as session_a:
                response_a, replayed_a = WalletCaseService(session_a).enqueue_sync(
                    public_case_id,
                    payload,
                    idempotency_key,
                )
            assert replayed_a is False
            created_by_a["public_id"] = response_a["public_id"]
        return original_active_lookup(case_id=case_id)

    monkeypatch.setattr(
        service_b.repository,
        "get_active_sync",
        active_after_commit,
    )
    try:
        response_b, replayed_b = service_b.enqueue_sync(
            public_case_id,
            payload,
            idempotency_key,
        )
    finally:
        session_b.close()

    assert interleaved is True
    assert replayed_b is True
    assert response_b["public_id"] == created_by_a["public_id"]
    assert _database_counts() == (1, 1, 0)


def test_sync_enqueue_fails_without_a_live_consumer_and_stores_nothing(client):
    case_id = _create_case(client)["case"]["public_id"]
    app.state.wallet_case_job_runner = None

    response = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    )

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "case_sync_runner_unavailable"
    assert response.headers["retry-after"] == "5"
    assert _database_counts() == (1, 0, 0)
    assert client.get("/api/providers/status").json()[
        "wallet_cases_available"
    ] is False


def test_queued_cancel_is_terminal_and_idempotent(client):
    case_id = _create_case(client)["case"]["public_id"]
    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    ).json()
    path = f"/api/v1/cases/{case_id}/syncs/{queued['public_id']}/cancel"

    cancelled = client.post(path)
    repeated = client.post(path)

    assert cancelled.status_code == repeated.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["completed_at"] is not None
    assert repeated.json()["status_version"] == cancelled.json()["status_version"]
    assert _database_counts() == (1, 1, 0)


def test_claim_cancel_race_finalizes_without_waiting_for_lease_recovery(client):
    case_id = _create_case(client)["case"]["public_id"]
    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    ).json()
    worker = CaseSyncWorker(app.state.wallet_case_test_session)
    claimed = worker.claim_next()
    assert claimed is not None

    path = f"/api/v1/cases/{case_id}/syncs/{queued['public_id']}/cancel"
    accepted = client.post(path)
    repeated = client.post(path)
    assert accepted.status_code == 202
    assert repeated.status_code == 200
    assert repeated.json()["status_version"] == accepted.json()["status_version"]

    assert worker._advance_to_ingestion(claimed) is False
    terminal = client.get(
        f"/api/v1/cases/{case_id}/syncs/{queued['public_id']}"
    ).json()
    assert terminal["state"] == "cancelled"
    assert terminal["completed_at"] is not None


def test_blocked_builder_heartbeats_while_api_stays_responsive_then_cancels(
    client,
):
    case_id = _create_case(client)["case"]["public_id"]
    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    ).json()
    entered = Event()
    release = Event()

    def blocked_builder(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return build_wallet_ingestion_run(*args, **kwargs)

    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=blocked_builder,
        lease_seconds=30,
        heartbeat_seconds=2,
    )
    worker_thread = Thread(target=worker.run_once, daemon=True)
    worker_thread.start()
    assert entered.wait(5)
    with app.state.wallet_case_test_session() as session:
        before = session.scalar(
            select(CaseSync).where(CaseSync.public_id == queued["public_id"])
        )
        assert before is not None
        before_heartbeat = before.heartbeat_at
        before_expiry = before.lease_expires_at

    deadline = time.monotonic() + 5
    heartbeat_advanced = False
    while time.monotonic() < deadline:
        running = client.get(f"/api/v1/jobs/{queued['public_id']}")
        assert running.status_code == 200
        assert running.json()["state"] == "running"
        with app.state.wallet_case_test_session() as session:
            current = session.scalar(
                select(CaseSync).where(
                    CaseSync.public_id == queued["public_id"]
                )
            )
            assert current is not None
            heartbeat_advanced = (
                current.heartbeat_at is not None
                and before_heartbeat is not None
                and current.heartbeat_at > before_heartbeat
                and current.lease_expires_at is not None
                and before_expiry is not None
                and current.lease_expires_at > before_expiry
            )
        if heartbeat_advanced:
            break
        time.sleep(0.1)
    assert heartbeat_advanced is True

    cancel = client.post(
        f"/api/v1/cases/{case_id}/syncs/{queued['public_id']}/cancel"
    )
    assert cancel.status_code == 202
    release.set()
    worker_thread.join(timeout=5)
    assert worker_thread.is_alive() is False
    terminal = client.get(f"/api/v1/jobs/{queued['public_id']}").json()
    assert terminal["state"] == "cancelled"
    assert terminal["cancel_requested"] is True
    assert _database_counts() == (1, 1, 0)


def test_expired_lease_recovery_reclaims_and_fences_the_old_owner(client):
    case_id = _create_case(client)["case"]["public_id"]
    clock = [datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)]
    with app.state.wallet_case_test_session() as session:
        queued, _ = WalletCaseService(session).enqueue_sync(
            case_id,
            WalletCaseSyncRequest(
                time_window="24h",
                surfaces=["transactions"],
            ),
            str(uuid4()),
            now=clock[0],
        )
    first_worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        clock=lambda: clock[0],
        lease_seconds=30,
    )
    old_claim = first_worker.claim_next()
    assert old_claim is not None
    assert CaseSyncWorker(
        app.state.wallet_case_test_session,
        clock=lambda: clock[0],
        lease_seconds=30,
    ).claim_next() is None

    clock[0] += timedelta(seconds=31)
    replacement_worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        clock=lambda: clock[0],
        lease_seconds=30,
    )
    assert replacement_worker.recover_expired() == 1
    replacement = replacement_worker.claim_next()
    assert replacement is not None
    assert replacement.lease_token != old_claim.lease_token
    assert first_worker._fail_without_run(
        old_claim,
        code="stale_owner",
        message="A stale owner must not publish.",
        retryable=False,
    ) is False

    with app.state.wallet_case_test_session() as session:
        row = session.scalar(
            select(CaseSync).where(CaseSync.public_id == queued["public_id"])
        )
        assert row is not None
        assert row.state == "running"
        assert row.lease_token == replacement.lease_token


def test_two_concurrent_claimers_issue_only_one_lease(client):
    case_id = _create_case(client)["case"]["public_id"]
    client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    )
    barrier = Barrier(3)
    claims = []
    errors: list[Exception] = []

    def claim():
        try:
            worker = CaseSyncWorker(app.state.wallet_case_test_session)
            barrier.wait()
            claims.append(worker.claim_next())
        except Exception as exc:  # surfaced in the coordinator assertion
            errors.append(exc)

    threads = [Thread(target=claim, daemon=True), Thread(target=claim, daemon=True)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=5)

    assert errors == []
    assert all(thread.is_alive() is False for thread in threads)
    issued = [claim for claim in claims if claim is not None]
    assert len(issued) == 1
    with app.state.wallet_case_test_session() as session:
        row = session.scalar(select(CaseSync))
        assert row is not None
        assert row.state == "running"
        assert row.lease_token == issued[0].lease_token
        assert row.attempt_count == 1


def test_claim_closes_job_when_parent_case_was_archived(client):
    case_id = _create_case(client)["case"]["public_id"]
    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    ).json()
    with app.state.wallet_case_test_session() as session:
        wallet_case = session.scalar(
            select(WalletCase).where(WalletCase.public_id == case_id)
        )
        assert wallet_case is not None
        wallet_case.archived_at = datetime.now(timezone.utc)
        session.commit()

    worker = CaseSyncWorker(app.state.wallet_case_test_session)
    assert worker.claim_next() is None

    with app.state.wallet_case_test_session() as session:
        row = session.scalar(
            select(CaseSync).where(CaseSync.public_id == queued["public_id"])
        )
        assert row is not None
        assert row.state == "failed"
        assert row.stage == "failed"
        assert row.error_code == "case_unavailable"
        assert row.completed_at is not None
        assert row.lease_token is None


def test_retry_is_bounded_deterministic_and_publishes_one_final_run(
    client,
    monkeypatch,
):
    monkeypatch.setenv("WALLET_CASE_JOB_MAX_ATTEMPTS", "2")
    case_id = _create_case(client)["case"]["public_id"]
    clock = [datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)]
    with app.state.wallet_case_test_session() as session:
        queued, _ = WalletCaseService(session).enqueue_sync(
            case_id,
            WalletCaseSyncRequest(
                time_window="24h",
                surfaces=["transactions"],
            ),
            str(uuid4()),
            now=clock[0],
        )

    def temporary_error(*_args, **_kwargs):
        return WalletIngestionRun(
            wallet_address=BOUNCEABLE_MAINNET,
            time_window="24h",
            data_mode="mock",
            status="error",
            requested_surfaces_json='["transactions"]',
            provider_summary_json=json.dumps(
                {
                    "provider_evidence": [],
                    "unavailable_surfaces": ["transactions"],
                    "incomplete_surfaces": [],
                    "message": "A safe temporary provider failure.",
                }
            ),
        )

    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=temporary_error,
        clock=lambda: clock[0],
        retry_base_seconds=2,
        retry_cap_seconds=10,
    )
    assert worker.run_once() is True
    retrying = client.get(
        f"/api/v1/jobs/{queued['public_id']}"
    ).json()
    assert retrying["state"] == "queued"
    assert retrying["stage"] == "retry_wait"
    assert retrying["retry"]["attempt"] == 1
    assert retrying["retry"]["max_attempts"] == 2
    assert retrying["retry"]["reason_code"] == "provider_error"
    assert _database_counts() == (1, 1, 0)

    with app.state.wallet_case_test_session() as session:
        retry_at = session.scalar(
            select(CaseSync.next_attempt_at).where(
                CaseSync.public_id == queued["public_id"]
            )
        )
    assert retry_at is not None
    clock[0] = retry_at.replace(tzinfo=timezone.utc) + timedelta(milliseconds=1)
    assert worker.run_once() is True
    failed = client.get(f"/api/v1/jobs/{queued['public_id']}").json()
    assert failed["state"] == "failed"
    assert failed["error"]["retryable"] is True
    assert failed["retry"] is None
    assert _database_counts() == (1, 1, 1)


def test_retry_classifier_rejects_protocol_errors_and_accepts_http_signals():
    permanent = {
        "status": "error",
        "acquisition_streams": [{"error_code": "provider_protocol_error"}],
    }
    throttled = {
        "status": "error",
        "acquisition_streams": [{"error_code": "http_429"}],
    }
    unavailable = {
        "status": "error",
        "acquisition_streams": [{"error_code": "http_503"}],
    }

    assert _retry_signal(permanent) == (False, "provider_protocol_error")
    for timeout_code in ("http_408", "http_425"):
        assert _retry_signal(
            {
                "status": "partial",
                "acquisition_streams": [{"error_code": timeout_code}],
            }
        ) == (True, timeout_code)
    assert _retry_signal(throttled) == (True, "http_429")
    assert _retry_signal(unavailable) == (True, "http_503")


def test_runner_clamps_heartbeat_below_one_third_of_the_lease(client):
    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        lease_seconds=30,
        heartbeat_seconds=300,
    )

    assert worker.heartbeat_seconds == 10


def test_worker_stop_never_claims_or_starts_new_provider_work(client):
    case_id = _create_case(client)["case"]["public_id"]
    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    ).json()
    provider_called = False

    def forbidden_builder(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("shutdown must not start provider work")

    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=forbidden_builder,
    )
    worker.request_stop()

    assert worker.run_once() is False
    assert provider_called is False
    with app.state.wallet_case_test_session() as session:
        row = session.scalar(
            select(CaseSync).where(CaseSync.public_id == queued["public_id"])
        )
        assert row is not None
        assert row.state == "queued"
        assert row.attempt_count == 0


def test_stop_during_claim_validation_never_starts_provider_work(client):
    case_id = _create_case(client)["case"]["public_id"]
    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    ).json()
    provider_called = False

    def forbidden_builder(*_args, **_kwargs):
        nonlocal provider_called
        provider_called = True
        raise AssertionError("shutdown during validation must fence provider work")

    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=forbidden_builder,
    )
    validated_settings = worker._validated_settings

    def stop_after_validation(claimed):
        settings = validated_settings(claimed)
        worker.request_stop()
        return settings

    worker._validated_settings = stop_after_validation

    assert worker.run_once() is True
    assert provider_called is False
    with app.state.wallet_case_test_session() as session:
        row = session.scalar(
            select(CaseSync).where(CaseSync.public_id == queued["public_id"])
        )
        assert row is not None
        assert row.state == "running"
        assert row.lease_token is not None
        assert row.attempt_count == 1
