"""Migrated-file API integration tests for the Wallet Case facade."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from threading import Barrier, Event, Thread
import time
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
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
    WalletCaseCatalogEvent,
    WalletCaseLifecycleEvent,
    WalletCaseReportRevision,
    WalletCaseStreamCheckpoint,
    WalletCaseSyncManifest,
    WalletAcquisitionPage,
    WalletAcquisitionStream,
    WalletIngestionRun,
    WalletTransaction,
)
from services.database_migrations import run_database_migrations
from services.case_sync_jobs import CaseSyncWorker, _retry_signal
from services.wallet_activity_ingestion import (
    build_wallet_ingestion_run,
    wallet_ingestion_run_to_response,
)
from services.wallet_cases import (
    WalletCaseCatalogInvalidCursor,
    WalletCaseNotFound,
    WalletCaseService,
    _checkpoint_resume_fingerprint,
    _compact_coverage_streams,
)
from schemas import WalletIngestionPreviewRequest
from wallet_case_schemas import (
    WalletCaseCheckpointContinuationReceiptResponse,
    WalletCaseCheckpointContinuationPlanResponse,
    WalletCaseStreamCheckpointChainResponse,
    WalletCaseSyncRequest,
)


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
    assert report.revision_after == "20260828_0028"
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


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(
        timezone.utc
    )


def _database_counts() -> tuple[int, int, int]:
    engine = app.state.wallet_case_test_engine
    with Session(engine) as session:
        return (
            session.scalar(select(func.count()).select_from(WalletCase)),
            session.scalar(select(func.count()).select_from(CaseSync)),
            session.scalar(select(func.count()).select_from(WalletIngestionRun)),
        )


def _attach_transaction_stream(
    run,
    claimed,
    *,
    cursor: str | None = "10",
    completion_state: str = "incomplete",
    termination_reason: str = "page_cap_reached",
    page_index: int = 1,
    request_cursor: str | None = None,
    stream_key: str = "transactions",
    contract_version: str = "tonapi_account_transactions_v1",
) -> None:
    stream = WalletAcquisitionStream(
        provider="tonapi",
        stream_key=stream_key,
        contract_version=contract_version,
        scope_kind="bounded_time",
        resolved_start_at=claimed.requested_start,
        resolved_end_at=claimed.requested_end,
        request_query_json=json.dumps(
            {"filters": {"bounded": True}, "sort_order": "desc"},
            sort_keys=True,
        ),
        page_size=100,
        max_pages=1,
        max_items=100,
        completion_state=completion_state,
        termination_reason=termination_reason,
        pages_attempted=1,
        pages_succeeded=1,
        raw_item_count=2,
        normalized_item_count=2,
        duplicate_item_count=0,
        first_cursor=request_cursor,
        terminal_cursor=cursor,
        bounds_verified=False,
        error_code=None,
        error_message=None,
        started_at=claimed.requested_start,
        finished_at=claimed.requested_end,
    )
    stream.pages.append(
        WalletAcquisitionPage(
            page_index=page_index,
            request_cursor=request_cursor,
            response_cursor=cursor,
            request_offset=None,
            requested_limit=100,
            request_query_json='{"limit":100}',
            raw_item_count=2,
            normalized_item_count=2,
            duplicate_item_count=0,
            newest_logical_time="20",
            oldest_logical_time="10",
            newest_activity_at=claimed.requested_end - timedelta(minutes=1),
            oldest_activity_at=claimed.requested_end - timedelta(minutes=2),
            response_digest_sha256="ab" * 32,
            attempt_count=1,
            fetch_status="success",
            error_code=None,
            error_message=None,
            fetched_at=claimed.requested_end,
        )
    )
    run.acquisition_streams.append(stream)


def _resumed_transaction_run(payload, settings, **kwargs):
    run = build_wallet_ingestion_run(payload, settings, **kwargs)
    _attach_transaction_stream(
        run,
        SimpleNamespace(
            requested_start=_parse_utc(payload.custom_start),
            requested_end=_parse_utc(payload.custom_end),
        ),
        cursor=str(int(kwargs["resume_cursor"]) + 10),
        page_index=kwargs["resume_page_index"],
        request_cursor=kwargs["resume_cursor"],
    )
    return run


def _publish_transaction_checkpoint(
    client,
    *,
    case_id: str | None = None,
    cursor: str = "10",
    completion_state: str = "incomplete",
    termination_reason: str = "page_cap_reached",
):
    case_id = case_id or _create_case(client)["case"]["public_id"]
    with app.state.wallet_case_test_session() as session:
        queued, _ = WalletCaseService(session).enqueue_sync(
            case_id,
            WalletCaseSyncRequest(
                time_window="24h",
                surfaces=["transactions"],
            ),
            str(uuid4()),
        )
    worker = CaseSyncWorker(app.state.wallet_case_test_session)
    claimed = worker.claim_next()
    assert claimed is not None
    settings = worker._validated_settings(claimed)
    run = build_wallet_ingestion_run(
        WalletIngestionPreviewRequest(
            wallet_address=claimed.display_address,
            time_window=claimed.time_window,
            surfaces=list(claimed.requested_surfaces),
        ),
        settings,
        now=claimed.requested_end,
    )
    _attach_transaction_stream(
        run,
        claimed,
        cursor=cursor,
        completion_state=completion_state,
        termination_reason=termination_reason,
    )
    run_response = wallet_ingestion_run_to_response(run)
    assert worker._publish_final_run(
        claimed,
        run,
        run_response,
        settings,
        last_error_retryable=False,
    ) is True
    return case_id, queued, claimed


def _publish_multi_stream_checkpoints(client):
    case_id = _create_case(client)["case"]["public_id"]
    with app.state.wallet_case_test_session() as session:
        queued, _ = WalletCaseService(session).enqueue_sync(
            case_id,
            WalletCaseSyncRequest(
                time_window="24h",
                surfaces=["transactions", "transfers"],
            ),
            str(uuid4()),
        )
    worker = CaseSyncWorker(app.state.wallet_case_test_session)
    claimed = worker.claim_next()
    assert claimed is not None
    settings = worker._validated_settings(claimed)
    run = build_wallet_ingestion_run(
        WalletIngestionPreviewRequest(
            wallet_address=claimed.display_address,
            time_window=claimed.time_window,
            surfaces=list(claimed.requested_surfaces),
        ),
        settings,
        now=claimed.requested_end,
    )
    _attach_transaction_stream(run, claimed)
    _attach_transaction_stream(
        run,
        claimed,
        cursor=None,
        completion_state="complete",
        termination_reason="end_reached",
        stream_key="account_events",
        contract_version="tonapi_account_events_display_v1",
    )
    run_response = wallet_ingestion_run_to_response(run)
    assert worker._publish_final_run(
        claimed,
        run,
        run_response,
        settings,
        last_error_retryable=False,
    ) is True
    return case_id, queued, claimed


def _resume_transaction_checkpoint(
    client: TestClient,
    *,
    case_id: str,
    checkpoint_id: str,
) -> tuple[dict, str]:
    response = client.post(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{checkpoint_id}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202, response.text
    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=_resumed_transaction_run,
    )
    assert worker.run_once() is True
    completed = client.get(
        f"/api/v1/cases/{case_id}/syncs/{response.json()['public_id']}"
    )
    assert completed.status_code == 200, completed.text
    with app.state.wallet_case_test_session() as session:
        checkpoint = session.scalar(
            select(WalletCaseStreamCheckpoint)
            .where(WalletCaseStreamCheckpoint.case.has(public_id=case_id))
            .order_by(WalletCaseStreamCheckpoint.id.desc())
        )
        assert checkpoint is not None
        return completed.json(), checkpoint.public_id


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
            "metadata_version": 1,
            "created_at": first["case"]["created_at"],
            "updated_at": first["case"]["updated_at"],
            "archived_at": None,
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
    assert catalog.json()["state"] == "active"
    assert catalog.json()["truncated"] is False
    assert len(catalog.json()["cases"]) == 3
    assert catalog.json()["next_cursor"] is None


def test_case_catalog_cursor_freezes_order_and_excludes_later_cases(client):
    created = [
        _create_case(
            client,
            address=f"0:{account_id:064x}",
            label=f"Case {account_id}",
        )["case"]
        for account_id in range(1, 6)
    ]
    frozen_order = [item["public_id"] for item in reversed(created)]

    first = client.get("/api/v1/cases?limit=2")
    assert first.status_code == 200, first.text
    assert [item["public_id"] for item in first.json()["cases"]] == frozen_order[:2]
    assert first.json()["truncated"] is True
    first_cursor = first.json()["next_cursor"]
    assert isinstance(first_cursor, str)
    assert len(first.json()["cases"]) == first.json()["limit"] == 2

    moved = client.patch(
        f"/api/v1/cases/{created[0]['public_id']}",
        json={"expected_metadata_version": 1, "label": "Moved after page one"},
    )
    assert moved.status_code == 200, moved.text
    later = _create_case(client, address=f"0:{6:064x}")["case"]

    second = client.get(
        "/api/v1/cases",
        params={"limit": 2, "cursor": first_cursor},
    )
    assert second.status_code == 200, second.text
    assert [item["public_id"] for item in second.json()["cases"]] == frozen_order[2:4]
    assert second.json()["truncated"] is True
    second_cursor = second.json()["next_cursor"]
    assert isinstance(second_cursor, str)
    assert second_cursor != first_cursor

    final = client.get(
        "/api/v1/cases",
        params={"limit": 2, "cursor": second_cursor},
    )
    assert final.status_code == 200, final.text
    assert [item["public_id"] for item in final.json()["cases"]] == frozen_order[4:]
    assert final.json()["truncated"] is False
    assert final.json()["next_cursor"] is None
    assert later["public_id"] not in {
        item["public_id"]
        for page in (first.json(), second.json(), final.json())
        for item in page["cases"]
    }

    repeated_second = client.get(
        "/api/v1/cases",
        params={"limit": 2, "cursor": first_cursor},
    )
    assert [
        item["public_id"] for item in repeated_second.json()["cases"]
    ] == frozen_order[2:4]

    fresh = client.get("/api/v1/cases?limit=2")
    assert [item["public_id"] for item in fresh.json()["cases"]] == [
        later["public_id"],
        created[0]["public_id"],
    ]


def test_case_catalog_searches_metadata_and_literal_address_text(
    client,
    monkeypatch,
):
    treasury = _create_case(
        client,
        address=f"0:{1:064x}",
        label="ALPHA Treasury 100%",
        note="Priority_blue review",
    )["case"]
    reserve = _create_case(
        client,
        address=f"0:{2:064x}",
        label="alpha reserve 100x",
    )["case"]
    testnet = _create_case(
        client,
        address=f"0:{3:064x}",
        network="ton-testnet",
        label="Alpha Testnet",
    )["case"]
    _configure_guarded_live_runtime(monkeypatch)
    live = _create_case(
        client,
        address=f"0:{4:064x}",
        environment="live",
        label="Alpha Live",
    )["case"]

    searched = client.get(
        "/api/v1/cases",
        params={"limit": 10, "q": "  alpha  "},
    )
    assert searched.status_code == 200, searched.text
    assert searched.json()["query"] == "alpha"
    assert searched.json()["network"] is None
    assert searched.json()["data_environment"] is None
    assert [item["public_id"] for item in searched.json()["cases"]] == [
        live["public_id"],
        testnet["public_id"],
        reserve["public_id"],
        treasury["public_id"],
    ]

    literal_percent = client.get(
        "/api/v1/cases",
        params={"limit": 10, "q": "100%"},
    )
    assert [item["public_id"] for item in literal_percent.json()["cases"]] == [
        treasury["public_id"]
    ]
    literal_underscore = client.get(
        "/api/v1/cases",
        params={"limit": 10, "q": "_blue"},
    )
    assert [
        item["public_id"] for item in literal_underscore.json()["cases"]
    ] == [treasury["public_id"]]

    canonical_fragment = treasury["canonical_wallet_key"][-12:]
    by_address = client.get(
        "/api/v1/cases",
        params={"limit": 10, "q": canonical_fragment},
    )
    assert [item["public_id"] for item in by_address.json()["cases"]] == [
        treasury["public_id"]
    ]


def test_case_catalog_combines_exact_network_and_environment_filters(
    client,
    monkeypatch,
):
    mainnet = _create_case(
        client,
        address=f"0:{1:064x}",
        label="Investigate bridge",
    )["case"]
    testnet = _create_case(
        client,
        address=f"0:{2:064x}",
        network="ton-testnet",
        label="Investigate bridge",
    )["case"]
    _configure_guarded_live_runtime(monkeypatch)
    live = _create_case(
        client,
        address=f"0:{3:064x}",
        environment="live",
        label="Investigate bridge",
    )["case"]

    filtered = client.get(
        "/api/v1/cases",
        params={
            "limit": 10,
            "q": "bridge",
            "network": "ton-mainnet",
            "data_environment": "demo",
        },
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["query"] == "bridge"
    assert filtered.json()["network"] == "ton-mainnet"
    assert filtered.json()["data_environment"] == "demo"
    assert [item["public_id"] for item in filtered.json()["cases"]] == [
        mainnet["public_id"]
    ]

    testnet_only = client.get(
        "/api/v1/cases",
        params={"limit": 10, "network": "ton-testnet"},
    )
    assert [item["public_id"] for item in testnet_only.json()["cases"]] == [
        testnet["public_id"]
    ]
    live_only = client.get(
        "/api/v1/cases",
        params={"limit": 10, "data_environment": "live"},
    )
    assert [item["public_id"] for item in live_only.json()["cases"]] == [
        live["public_id"]
    ]


def test_case_catalog_cursor_is_bound_to_normalized_discovery_filters(client):
    for account_id in range(1, 4):
        _create_case(
            client,
            address=f"0:{account_id:064x}",
            label=f"Needle {account_id}",
        )

    first = client.get(
        "/api/v1/cases",
        params={"limit": 1, "q": "  Needle  "},
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["next_cursor"]
    assert isinstance(cursor, str)

    continued = client.get(
        "/api/v1/cases",
        params={"limit": 1, "q": "Needle", "cursor": cursor},
    )
    assert continued.status_code == 200, continued.text

    for changed_filter in (
        {"q": "different"},
        {"q": "Needle", "network": "ton-mainnet"},
        {"q": "Needle", "data_environment": "demo"},
    ):
        mismatch = client.get(
            "/api/v1/cases",
            params={"limit": 1, "cursor": cursor, **changed_filter},
        )
        assert mismatch.status_code == 422
        assert mismatch.json()["detail"]["message_safe"].endswith(
            "another filter set."
        )


def test_case_catalog_cursor_excludes_cases_reopened_after_cutoff(client):
    active = [
        _create_case(client, address=f"0:{account_id:064x}")["case"]
        for account_id in range(1, 4)
    ]
    archived = _create_case(client, address=f"0:{4:064x}")["case"]
    archived_at = datetime.now(timezone.utc)
    with app.state.wallet_case_test_session() as session:
        wallet_case = session.scalar(
            select(WalletCase).where(
                WalletCase.public_id == archived["public_id"]
            )
        )
        assert wallet_case is not None
        wallet_case.archived_at = archived_at
        session.add(
            WalletCaseCatalogEvent(
                case=wallet_case,
                recorded_at=archived_at,
                visible=False,
            )
        )
        session.commit()

    first = client.get("/api/v1/cases?limit=1").json()
    assert first["truncated"] is True
    assert first["next_cursor"] is not None
    reopened = _create_case(client, address=f"0:{4:064x}")
    assert reopened["created"] is False

    frozen_ids = [first["cases"][0]["public_id"]]
    cursor = first["next_cursor"]
    while cursor is not None:
        page = client.get(
            "/api/v1/cases",
            params={"limit": 1, "cursor": cursor},
        ).json()
        frozen_ids.extend(item["public_id"] for item in page["cases"])
        cursor = page["next_cursor"]

    assert frozen_ids == [item["public_id"] for item in reversed(active)]
    fresh = client.get("/api/v1/cases?limit=1").json()
    assert fresh["cases"][0]["public_id"] == archived["public_id"]


def test_archived_case_catalog_is_paged_and_freezes_lifecycle_membership(client):
    created = [
        _create_case(
            client,
            address=f"0:{account_id:064x}",
            label=f"Archived {account_id}",
        )["case"]
        for account_id in range(1, 5)
    ]
    for wallet_case in created:
        response = client.post(
            f"/api/v1/cases/{wallet_case['public_id']}/archive"
        )
        assert response.status_code == 200, response.text

    first = client.get("/api/v1/cases?limit=1&state=archived")
    assert first.status_code == 200, first.text
    first_page = first.json()
    assert first_page["state"] == "archived"
    assert first_page["cases"][0]["public_id"] == created[3]["public_id"]
    assert first_page["cases"][0]["archived_at"] is not None
    assert first_page["truncated"] is True
    cursor = first_page["next_cursor"]
    assert isinstance(cursor, str)

    wrong_state = client.get(
        "/api/v1/cases",
        params={"limit": 1, "state": "active", "cursor": cursor},
    )
    assert wrong_state.status_code == 422
    assert wrong_state.json()["detail"]["message_safe"].endswith(
        "another lifecycle state."
    )

    restored = client.post(
        f"/api/v1/cases/{created[1]['public_id']}/restore"
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["archived_at"] is None

    frozen_ids = [first_page["cases"][0]["public_id"]]
    frozen_states = [first_page["cases"][0]["archived_at"]]
    while cursor is not None:
        page = client.get(
            "/api/v1/cases",
            params={"limit": 1, "state": "archived", "cursor": cursor},
        )
        assert page.status_code == 200, page.text
        document = page.json()
        assert document["state"] == "archived"
        frozen_ids.extend(item["public_id"] for item in document["cases"])
        frozen_states.extend(item["archived_at"] for item in document["cases"])
        cursor = document["next_cursor"]

    assert frozen_ids == [item["public_id"] for item in reversed(created)]
    restored_index = frozen_ids.index(created[1]["public_id"])
    assert frozen_states[restored_index] is None

    fresh_archived = client.get(
        "/api/v1/cases?limit=4&state=archived"
    ).json()
    assert [item["public_id"] for item in fresh_archived["cases"]] == [
        created[3]["public_id"],
        created[2]["public_id"],
        created[0]["public_id"],
    ]
    active = client.get("/api/v1/cases?limit=4&state=active").json()
    assert [item["public_id"] for item in active["cases"]] == [
        created[1]["public_id"]
    ]


def test_case_catalog_rejects_untrusted_or_cross_scope_cursors(client):
    for account_id in range(1, 4):
        _create_case(client, address=f"0:{account_id:064x}")
    cursor = client.get("/api/v1/cases?limit=1").json()["next_cursor"]
    assert isinstance(cursor, str)

    replacement = "0" if cursor[-1] != "0" else "1"
    tampered = client.get(
        "/api/v1/cases",
        params={"limit": 1, "cursor": cursor[:-1] + replacement},
    )
    assert tampered.status_code == 422
    assert tampered.headers["cache-control"] == "no-store"
    assert tampered.json()["detail"] == {
        "code": "invalid_case_catalog_cursor",
        "message_safe": "Wallet Case catalog cursor signature is invalid.",
        "retryable": False,
    }

    malformed = client.get(
        "/api/v1/cases",
        params={"limit": 1, "cursor": "not-a-cursor"},
    )
    assert malformed.status_code == 422
    assert malformed.json()["detail"]["code"] == "invalid_case_catalog_cursor"

    engine = app.state.wallet_case_test_engine
    with Session(engine) as session:
        with pytest.raises(
            WalletCaseCatalogInvalidCursor,
            match="another owner scope",
        ):
            WalletCaseService(
                session,
                owner_scope_id="another-local-owner",
            ).list_cases(limit=1, cursor=cursor)


@pytest.mark.parametrize(
    "query",
    (
        "limit=2&cursor=one&cursor=two",
        "limit=2&cursor=one&extra=value",
        "limit=2&state=active&state=archived",
        "limit=2&q=one&q=two",
        "limit=2&network=ton-mainnet&network=ton-testnet",
        "limit=2&data_environment=demo&data_environment=live",
        "limit=2&q=%20%20%20",
    ),
)
def test_case_catalog_rejects_ambiguous_query_parameters(client, query):
    response = client.get(f"/api/v1/cases?{query}")

    assert response.status_code == 422


def test_case_metadata_update_is_versioned_trimmed_and_scope_preserving(client):
    created = _create_case(
        client,
        label="Primary wallet",
        note="Initial note",
    )["case"]
    case_id = created["public_id"]

    response = client.patch(
        f"/api/v1/cases/{case_id}",
        json={
            "expected_metadata_version": 1,
            "label": "  Treasury review  ",
            "note": "  Evidence requested from compliance.  ",
        },
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    updated = response.json()
    assert updated["label"] == "Treasury review"
    assert updated["note"] == "Evidence requested from compliance."
    assert updated["metadata_version"] == 2
    assert updated["updated_at"] >= created["updated_at"]
    for immutable in (
        "public_id",
        "network",
        "data_environment",
        "canonical_wallet_key",
        "identity_version",
        "display_address",
        "created_at",
    ):
        assert updated[immutable] == created[immutable]

    cleared = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"expected_metadata_version": 2, "label": "   "},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["label"] is None
    assert cleared.json()["note"] == "Evidence requested from compliance."
    assert cleared.json()["metadata_version"] == 3

    stored = client.get(f"/api/v1/cases/{case_id}")
    assert stored.status_code == 200
    assert stored.json() == cleared.json()
    with Session(app.state.wallet_case_test_engine) as session:
        catalog_events = list(
            session.scalars(
                select(WalletCaseCatalogEvent)
                .join(WalletCase)
                .where(WalletCase.public_id == case_id)
                .order_by(WalletCaseCatalogEvent.id)
            )
        )
    assert len(catalog_events) == 3
    assert all(event.recorded_at is not None for event in catalog_events)


def test_case_metadata_update_rejects_stale_or_invalid_edits_without_mutation(client):
    case_id = _create_case(client, label="Original")["case"]["public_id"]
    first = client.patch(
        f"/api/v1/cases/{case_id}",
        json={"expected_metadata_version": 1, "label": "Current"},
    )
    assert first.status_code == 200

    stale = client.patch(
        f"/api/v1/cases/{case_id}",
        json={
            "expected_metadata_version": 1,
            "label": "Overwrite from stale tab",
        },
    )
    assert stale.status_code == 409
    assert stale.headers["cache-control"] == "no-store"
    assert stale.json() == {
        "detail": {
            "code": "case_metadata_changed",
            "message_safe": (
                "Wallet Case metadata changed after this editor was opened."
            ),
            "retryable": True,
            "current_metadata_version": 2,
        }
    }

    invalid_payloads = (
        {"expected_metadata_version": 2},
        {"expected_metadata_version": 0, "label": "Invalid"},
        {"expected_metadata_version": 2, "label": "x" * 121},
        {"expected_metadata_version": 2, "note": "x" * 4001},
        {"expected_metadata_version": 2, "label": "Invalid", "extra": True},
    )
    for payload in invalid_payloads:
        invalid = client.patch(f"/api/v1/cases/{case_id}", json=payload)
        assert invalid.status_code == 422, invalid.text

    missing = client.patch(
        f"/api/v1/cases/{uuid4()}",
        json={"expected_metadata_version": 1, "note": "No case"},
    )
    assert missing.status_code == 404
    stored = client.get(f"/api/v1/cases/{case_id}").json()
    assert stored["label"] == "Current"
    assert stored["metadata_version"] == 2


def test_case_archive_and_restore_preserve_evidence_and_are_idempotent(client):
    created = _create_case(client, label="Treasury archive")["case"]
    case_id = created["public_id"]
    completed = _sync_case(client, case_id)

    archived = client.post(f"/api/v1/cases/{case_id}/archive")

    assert archived.status_code == 200, archived.text
    assert archived.headers["cache-control"] == "no-store"
    archived_case = archived.json()
    assert archived_case["public_id"] == case_id
    assert archived_case["archived_at"] is not None
    assert archived_case["updated_at"] == archived_case["archived_at"]
    assert archived_case["current_snapshot"]["public_id"] == completed["public_id"]
    assert archived_case["active_sync"] is None
    assert client.get(f"/api/v1/cases/{case_id}").status_code == 404
    assert client.get("/api/v1/cases").json()["cases"] == []
    assert _database_counts() == (1, 1, 1)

    repeated_archive = client.post(f"/api/v1/cases/{case_id}/archive")
    assert repeated_archive.status_code == 200
    assert repeated_archive.json()["archived_at"] == archived_case["archived_at"]

    restored = client.post(f"/api/v1/cases/{case_id}/restore")

    assert restored.status_code == 200, restored.text
    assert restored.headers["cache-control"] == "no-store"
    restored_case = restored.json()
    assert restored_case["public_id"] == case_id
    assert restored_case["archived_at"] is None
    assert restored_case["updated_at"] > archived_case["updated_at"]
    assert restored_case["current_snapshot"]["public_id"] == completed["public_id"]
    assert client.get(f"/api/v1/cases/{case_id}").json() == restored_case
    assert client.get("/api/v1/cases").json()["cases"][0]["public_id"] == case_id
    assert _database_counts() == (1, 1, 1)

    repeated_restore = client.post(f"/api/v1/cases/{case_id}/restore")
    assert repeated_restore.status_code == 200
    assert repeated_restore.json()["updated_at"] == restored_case["updated_at"]
    with app.state.wallet_case_test_session() as session:
        events = list(
            session.scalars(
                select(WalletCaseCatalogEvent)
                .join(WalletCase)
                .where(WalletCase.public_id == case_id)
                .order_by(WalletCaseCatalogEvent.id)
            )
        )
    assert [event.visible for event in events] == [True, True, True, False, True]


def test_case_archive_rejects_active_jobs_without_hiding_the_case(client):
    case_id = _create_case(client)["case"]["public_id"]
    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    ).json()

    response = client.post(f"/api/v1/cases/{case_id}/archive")

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == {
        "code": "case_archive_jobs_active",
        "message_safe": (
            "Cancel or wait for active Wallet Case jobs before archiving this case."
        ),
        "retryable": False,
        "active_sync_public_id": queued["public_id"],
        "active_evidence_public_id": None,
    }
    assert client.get(f"/api/v1/cases/{case_id}").status_code == 200
    with app.state.wallet_case_test_session() as session:
        wallet_case = session.scalar(
            select(WalletCase).where(WalletCase.public_id == case_id)
        )
        assert wallet_case is not None
        assert wallet_case.archived_at is None


def test_case_lifecycle_endpoints_do_not_disclose_another_owner_scope(client):
    case_id = _create_case(client)["case"]["public_id"]
    engine = app.state.wallet_case_test_engine

    with Session(engine) as session:
        service = WalletCaseService(session, owner_scope_id="another-local-owner")
        with pytest.raises(WalletCaseNotFound, match="not found"):
            service.archive_case(case_id)
        with pytest.raises(WalletCaseNotFound, match="not found"):
            service.restore_case(case_id)


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


def test_case_delete_write_fence_blocks_late_sync_before_cleanup_inventory(
    client,
    monkeypatch,
):
    case_id = _create_case(client)["case"]["public_id"]
    session_factory = app.state.wallet_case_test_session
    writer_errors: list[Exception] = []

    with session_factory() as delete_session:
        service = WalletCaseService(delete_session)
        original_row_count = service._row_count
        interleaved = False

        def try_late_enqueue(model, predicate):
            nonlocal interleaved
            if not interleaved:
                interleaved = True

                def enqueue() -> None:
                    with session_factory() as writer_session:
                        writer_session.connection().exec_driver_sql(
                            "PRAGMA busy_timeout=100"
                        )
                        try:
                            WalletCaseService(writer_session).enqueue_sync(
                                case_id,
                                WalletCaseSyncRequest(
                                    time_window="24h",
                                    surfaces=["transactions"],
                                ),
                                str(uuid4()),
                            )
                        except Exception as exc:  # captured for the parent test
                            writer_errors.append(exc)

                writer = Thread(target=enqueue)
                writer.start()
                writer.join(timeout=2)
                assert not writer.is_alive()
            return original_row_count(model, predicate)

        monkeypatch.setattr(service, "_row_count", try_late_enqueue)
        receipt = service.delete_case(case_id)

    assert receipt["deleted"] is True
    assert receipt["removed"] == {
        "syncs": 0,
        "ingestion_runs": 0,
        "evidence_verifications": 0,
        "report_revisions": 0,
    }
    assert len(writer_errors) == 1
    assert isinstance(writer_errors[0], OperationalError)
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
    assert sync["progress"] == {"current": 3, "total": 3}
    assert sync["provider"] == "mock_wallet_activity"
    assert sync["data_mode"] == "mock"
    descriptor = sync["acquisition_manifest"]
    assert descriptor["public_id"].startswith("smf_")
    assert descriptor["contract_version"] == "wallet_case_sync_manifest_v1"
    assert descriptor["public_id"] == (
        f"smf_{descriptor['content_hash_sha256']}"
    )
    assert descriptor["stream_count"] == 0
    assert descriptor["page_count"] == 0
    assert descriptor["response_digest_count"] == 0
    assert sync["requested_scope"]["time_window"] == "24h"
    assert sync["requested_scope"]["mode"] == "bounded"
    assert sync["requested_scope"]["surfaces"] == [
        "transfers",
        "transactions",
        "swaps",
        "balances",
        "jettons",
    ]
    assert sync["requested_scope"]["start_at"].endswith("Z")
    assert sync["requested_scope"]["end_at"].endswith("Z")
    assert sync["requested_scope"]["acquisition_start_at"] == sync[
        "requested_scope"
    ]["start_at"]
    assert sync["requested_scope"]["acquisition_end_at"] == sync[
        "requested_scope"
    ]["end_at"]
    assert sync["requested_scope"]["overlap_seconds"] == 0
    assert sync["requested_scope"]["base_snapshot_public_id"] is None
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
        assert session.scalar(
            select(func.count()).select_from(WalletCaseCatalogEvent)
        ) == 3
        stored_sync = session.scalar(select(CaseSync))
        assert stored_sync is not None
        assert stored_sync.ingestion_run_id is not None
        manifest = session.scalar(select(WalletCaseSyncManifest))
        assert manifest is not None
        assert manifest.case_sync_id == stored_sync.id
        assert manifest.public_id == f"smf_{manifest.content_hash_sha256}"
        document = json.loads(manifest.manifest_json)
        assert document["case_public_id"] == case_id
        assert document["sync_public_id"] == sync["public_id"]
        assert document["acquisition_mode"] == "bounded"
        assert document["snapshot_period"] == {
            "start_at": sync["requested_scope"]["start_at"],
            "end_at": sync["requested_scope"]["end_at"],
        }
        assert document["streams"] == []
        legacy_run_id = stored_sync.ingestion_run_id

    manifest_response = client.get(
        f"/api/v1/cases/{case_id}/syncs/{sync['public_id']}/manifest"
    )
    assert manifest_response.status_code == 200, manifest_response.text
    assert manifest_response.headers["cache-control"] == "no-store"
    manifest_payload = manifest_response.json()
    assert manifest_payload["manifest"] == descriptor
    assert manifest_payload["document"] == document
    assert "api_key" not in manifest_response.text
    assert "error_message" not in manifest_response.text
    assert '"run_id"' not in manifest_response.text

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


def test_final_publication_persists_manifest_bound_stream_checkpoint(client):
    case_id, queued, claimed = _publish_transaction_checkpoint(client)

    with app.state.wallet_case_test_session() as session:
        manifest = session.scalar(select(WalletCaseSyncManifest))
        checkpoint = session.scalar(select(WalletCaseStreamCheckpoint))
        assert manifest is not None
        assert checkpoint is not None
        assert checkpoint.case_id == claimed.case_id
        assert checkpoint.source_sync_id == claimed.id
        assert checkpoint.public_id == (
            f"scp_{checkpoint.checkpoint_hash_sha256}"
        )
        assert checkpoint.provider == "tonapi"
        assert checkpoint.stream_key == "transactions"
        assert checkpoint.resume_state == "ready"
        assert checkpoint.continuation_cursor == "10"
        assert checkpoint.continuation_page_index == 2
        document = json.loads(checkpoint.checkpoint_json)
        assert document["source_sync_public_id"] == queued["public_id"]
        assert document["source_manifest_public_id"] == manifest.public_id
        assert document["source_manifest_hash_sha256"] == (
            manifest.content_hash_sha256
        )
        assert document["last_successful_page"][
            "response_digest_sha256"
        ] == "ab" * 32

    response = client.get(f"/api/v1/cases/{case_id}/stream-checkpoints")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["case_public_id"] == case_id
    assert body["checkpoint_count"] == 1
    assert body["ready_count"] == 1
    assert body["complete_count"] == 0
    assert body["blocked_count"] == 0
    assert body["checkpoints"][0]["checkpoint"] == {
        "public_id": checkpoint.public_id,
        "contract_version": "wallet_case_stream_checkpoint_v1",
        "checkpoint_hash_sha256": checkpoint.checkpoint_hash_sha256,
        "provider": "tonapi",
        "stream_key": "transactions",
        "provider_contract_version": "tonapi_account_transactions_v1",
        "source_sync_public_id": queued["public_id"],
        "resume_state": "ready",
        "created_at": body["checkpoints"][0]["checkpoint"]["created_at"],
    }
    assert body["checkpoints"][0]["document"] == document
    assert "must-not-leak" not in response.text


def test_stream_checkpoint_catalog_fails_closed_on_corrupt_payload(client):
    case_id, _queued, _claimed = _publish_transaction_checkpoint(client)
    with app.state.wallet_case_test_session() as session:
        checkpoint = session.scalar(select(WalletCaseStreamCheckpoint))
        assert checkpoint is not None
        checkpoint.checkpoint_json = (
            '{"contract_version":"wallet_case_stream_checkpoint_v1"}'
        )
        session.commit()

    response = client.get(f"/api/v1/cases/{case_id}/stream-checkpoints")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"] == {
        "code": "stream_checkpoint_integrity_error",
        "message_safe": (
            "Stored Wallet Case stream checkpoint failed integrity validation."
        ),
        "retryable": False,
    }


def test_ready_stream_checkpoint_queues_and_executes_one_resume(client):
    case_id, source_sync, _claimed = _publish_transaction_checkpoint(client)
    with app.state.wallet_case_test_session() as session:
        checkpoint = session.scalar(select(WalletCaseStreamCheckpoint))
        assert checkpoint is not None
        checkpoint_id = checkpoint.public_id

    idempotency_key = str(uuid4())
    response = client.post(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{checkpoint_id}/resume",
        headers={"Idempotency-Key": idempotency_key},
    )

    assert response.status_code == 202, response.text
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["retry-after"] == "1"
    body = response.json()
    assert response.headers["location"].endswith(f"/syncs/{body['public_id']}")
    assert body["state"] == "queued"
    assert body["requested_scope"] == {
        "mode": "resume",
        "time_window": "custom",
        "start_at": source_sync["requested_scope"]["start_at"],
        "end_at": source_sync["requested_scope"]["end_at"],
        "surfaces": ["transactions"],
        "acquisition_start_at": source_sync["requested_scope"]["start_at"],
        "acquisition_end_at": source_sync["requested_scope"]["end_at"],
        "overlap_seconds": 0,
        "base_snapshot_public_id": source_sync["public_id"],
        "source_checkpoint_public_id": checkpoint_id,
        "continuation_plan_public_id": None,
        "resume_page_budget": None,
    }

    replay = client.post(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{checkpoint_id}/resume",
        headers={"Idempotency-Key": idempotency_key},
    )
    assert replay.status_code == 202, replay.text
    assert replay.json() == body
    conflict = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": idempotency_key},
        json={"time_window": "24h", "surfaces": ["transactions"]},
    )
    assert conflict.status_code == 409
    assert conflict.json()["detail"]["code"] == "idempotency_conflict"

    seen = []

    def recording_builder(payload, settings, **kwargs):
        seen.append((payload, kwargs))
        return _resumed_transaction_run(payload, settings, **kwargs)

    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=recording_builder,
    )
    assert worker.run_once() is True
    assert len(seen) == 1
    payload, kwargs = seen[0]
    assert payload.time_window == "custom"
    assert payload.surfaces == ["transactions"]
    assert kwargs["resume_stream_key"] == "transactions"
    assert kwargs["resume_cursor"] == "10"
    assert kwargs["resume_page_index"] == 2

    completed = client.get(
        f"/api/v1/cases/{case_id}/syncs/{body['public_id']}"
    )
    assert completed.status_code == 200, completed.text
    completed_body = completed.json()
    assert completed_body["state"] == "succeeded"
    assert completed_body["coverage"]["state"] == "unknown"
    assert "checkpoint_resume_composite_not_full_history" in {
        item["code"] for item in completed_body["limitations"]
    }
    assert _database_counts() == (1, 2, 2)

    manifest = client.get(
        f"/api/v1/cases/{case_id}/syncs/{body['public_id']}/manifest"
    )
    assert manifest.status_code == 200, manifest.text
    assert manifest.json()["document"]["acquisition_mode"] == "resume"
    catalog = client.get(f"/api/v1/cases/{case_id}/stream-checkpoints")
    assert catalog.status_code == 200, catalog.text
    assert catalog.json()["checkpoints"][0]["document"][
        "acquisition_mode"
    ] == "resume"

    with app.state.wallet_case_test_session() as session:
        resumed = session.scalar(
            select(CaseSync).where(CaseSync.public_id == body["public_id"])
        )
        assert resumed is not None
        persisted = json.loads(resumed.coverage_summary_json)["_acquisition"]
        assert persisted == {
            "version": 2,
            "mode": "resume",
            "start_at": body["requested_scope"]["acquisition_start_at"],
            "end_at": body["requested_scope"]["acquisition_end_at"],
            "overlap_seconds": 0,
            "base_snapshot_public_id": source_sync["public_id"],
            "source_checkpoint_public_id": checkpoint_id,
            "resume_stream_key": "transactions",
            "resume_cursor": "10",
            "resume_page_index": 2,
        }


def test_checkpoint_history_reads_exact_lineage_and_freezes_pagination(client):
    case_id, source_sync, _claimed = _publish_transaction_checkpoint(client)
    with app.state.wallet_case_test_session() as session:
        root = session.scalar(select(WalletCaseStreamCheckpoint))
        assert root is not None
        root_id = root.public_id

    _completed, resumed_id = _resume_transaction_checkpoint(
        client,
        case_id=case_id,
        checkpoint_id=root_id,
    )
    first = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/history?limit=1"
    )

    assert first.status_code == 200, first.text
    first_body = first.json()
    assert first.headers["cache-control"] == "no-store"
    assert first_body["contract_version"] == (
        "wallet_case_stream_checkpoint_history_v1"
    )
    assert first_body["revision_cutoff_public_id"] == resumed_id
    assert first_body["aggregate"] == {
        "total_revisions": 2,
        "returned_count": 1,
    }
    assert first_body["items"][0]["checkpoint"]["public_id"] == resumed_id
    assert first_body["items"][0]["lineage"] == {
        "acquisition_mode": "resume",
        "base_snapshot_public_id": source_sync["public_id"],
        "parent_checkpoint_public_id": root_id,
        "chain_depth": 1,
    }
    assert first_body["page"]["has_more"] is True
    cursor = first_body["page"]["next_cursor"]
    assert isinstance(cursor, str)

    exact = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{resumed_id}"
    )
    assert exact.status_code == 200, exact.text
    assert exact.json()["document"]["acquisition_mode"] == "resume"
    assert exact.json()["lineage"] == first_body["items"][0]["lineage"]

    _completed, newest_id = _resume_transaction_checkpoint(
        client,
        case_id=case_id,
        checkpoint_id=resumed_id,
    )
    second = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/history",
        params={"limit": "1", "cursor": cursor},
    )
    assert second.status_code == 200, second.text
    assert second.json()["revision_cutoff_public_id"] == resumed_id
    assert second.json()["aggregate"]["total_revisions"] == 2
    assert [
        item["checkpoint"]["public_id"] for item in second.json()["items"]
    ] == [root_id]
    assert second.json()["page"] == {
        "limit": 1,
        "has_more": False,
        "next_cursor": None,
    }

    fresh = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/history?limit=1"
    )
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["revision_cutoff_public_id"] == newest_id
    assert fresh.json()["aggregate"]["total_revisions"] == 3
    assert fresh.json()["items"][0]["lineage"]["chain_depth"] == 2

    foreign_case_id = _create_case(
        client,
        address=f"0:{'1' * 64}",
    )["case"]["public_id"]
    foreign = client.get(
        f"/api/v1/cases/{foreign_case_id}/stream-checkpoints/history",
        params={"cursor": cursor},
    )
    assert foreign.status_code == 422
    assert foreign.json()["detail"]["code"] == (
        "invalid_checkpoint_history_cursor"
    )
    replacement = "0" if cursor[-1] != "0" else "1"
    tampered = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/history",
        params={"cursor": f"{cursor[:-1]}{replacement}"},
    )
    assert tampered.status_code == 422
    assert tampered.json()["detail"]["code"] == (
        "invalid_checkpoint_history_cursor"
    )


def test_checkpoint_chain_aggregates_verified_root_to_tip_progress(client):
    case_id, source_sync, _claimed = _publish_transaction_checkpoint(client)
    with app.state.wallet_case_test_session() as session:
        root = session.scalar(select(WalletCaseStreamCheckpoint))
        assert root is not None
        root_id = root.public_id
    _completed, resumed_id = _resume_transaction_checkpoint(
        client,
        case_id=case_id,
        checkpoint_id=root_id,
    )
    _completed, tip_id = _resume_transaction_checkpoint(
        client,
        case_id=case_id,
        checkpoint_id=resumed_id,
    )

    response = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{tip_id}/chain"
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["chain"]["public_id"] == (
        f"cch_{body['chain']['content_hash_sha256']}"
    )
    assert body["chain"]["contract_version"] == (
        "wallet_case_stream_checkpoint_chain_v1"
    )
    assert body["chain"]["revision_count"] == 3
    assert body["chain"]["page_count"] == 3
    assert body["chain"]["pages_succeeded"] == 3
    document = body["document"]
    assert document["tip_checkpoint_public_id"] == tip_id
    assert document["root_acquisition_mode"] == "bounded"
    assert document["root_base_snapshot_public_id"] is None
    assert document["current_resume_state"] == "ready"
    assert document["next_page_index"] == 4
    assert document["aggregate"] == {
        "revision_count": 3,
        "page_count": 3,
        "pages_succeeded": 3,
    }
    revisions = document["revisions"]
    assert [item["ordinal"] for item in revisions] == [0, 1, 2]
    assert [item["checkpoint"]["public_id"] for item in revisions] == [
        root_id,
        resumed_id,
        tip_id,
    ]
    assert [item["acquisition_mode"] for item in revisions] == [
        "bounded",
        "resume",
        "resume",
    ]
    assert revisions[0]["parent_checkpoint_public_id"] is None
    assert revisions[1]["parent_checkpoint_public_id"] == root_id
    assert revisions[2]["parent_checkpoint_public_id"] == resumed_id
    assert revisions[1]["base_snapshot_public_id"] == source_sync["public_id"]
    assert revisions[2]["base_snapshot_public_id"] == revisions[1][
        "checkpoint"
    ]["source_sync_public_id"]
    assert all(
        item["last_response_digest_sha256"] == "ab" * 32
        for item in revisions
    )
    assert document["limitations"][0]["code"] == (
        "checkpoint_chain_is_acquisition_progress"
    )
    repeated = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{tip_id}/chain"
    )
    assert repeated.status_code == 200
    assert repeated.json() == body
    tampered = json.loads(json.dumps(body))
    tampered["chain"]["public_id"] = f"cch_{'0' * 64}"
    tampered["chain"]["content_hash_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="content address"):
        WalletCaseStreamCheckpointChainResponse.model_validate(tampered)


def test_checkpoint_continuation_plan_aggregates_latest_stream_chains(client):
    case_id, _source_sync, _claimed = _publish_multi_stream_checkpoints(client)
    with app.state.wallet_case_test_session() as session:
        roots = list(
            session.scalars(
                select(WalletCaseStreamCheckpoint)
                .where(WalletCaseStreamCheckpoint.case.has(public_id=case_id))
                .order_by(WalletCaseStreamCheckpoint.stream_key)
            )
        )
        assert [item.stream_key for item in roots] == [
            "account_events",
            "transactions",
        ]
        transaction_root_id = roots[1].public_id
    _completed, transaction_tip_id = _resume_transaction_checkpoint(
        client,
        case_id=case_id,
        checkpoint_id=transaction_root_id,
    )

    response = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    )

    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["plan"]["public_id"] == (
        f"cpl_{body['plan']['content_hash_sha256']}"
    )
    assert body["plan"]["contract_version"] == (
        "wallet_case_checkpoint_continuation_plan_v1"
    )
    assert body["plan"]["checkpoint_cutoff_public_id"] == transaction_tip_id
    assert body["plan"]["stream_count"] == 2
    assert body["plan"]["ready_count"] == 1
    assert body["plan"]["complete_count"] == 1
    assert body["plan"]["blocked_count"] == 0
    assert body["plan"]["revision_count"] == 3
    assert body["plan"]["page_count"] == 3
    assert body["plan"]["pages_succeeded"] == 3
    document = body["document"]
    assert document["aggregate"] == {
        key: body["plan"][key]
        for key in (
            "stream_count",
            "ready_count",
            "complete_count",
            "blocked_count",
            "revision_count",
            "page_count",
            "pages_succeeded",
        )
    }
    assert [item["stream_key"] for item in document["streams"]] == [
        "account_events",
        "transactions",
    ]
    completed_stream, ready_stream = document["streams"]
    assert completed_stream["resume_state"] == "complete"
    assert completed_stream["revision_count"] == 1
    assert completed_stream["next_page_index"] is None
    assert completed_stream["resume_blocker"] is None
    assert ready_stream["tip_checkpoint"]["public_id"] == transaction_tip_id
    assert ready_stream["resume_state"] == "ready"
    assert ready_stream["revision_count"] == 2
    assert ready_stream["next_page_index"] == 3
    assert ready_stream["resume_blocker"] is None
    chain = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/"
        f"{transaction_tip_id}/chain"
    )
    assert chain.status_code == 200, chain.text
    assert ready_stream["chain_public_id"] == chain.json()["chain"]["public_id"]
    assert ready_stream["chain_content_hash_sha256"] == chain.json()["chain"][
        "content_hash_sha256"
    ]
    repeated = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    )
    assert repeated.status_code == 200
    assert repeated.json() == body
    tampered = json.loads(json.dumps(body))
    tampered["plan"]["public_id"] = f"cpl_{'0' * 64}"
    with pytest.raises(ValueError, match="content address"):
        WalletCaseCheckpointContinuationPlanResponse.model_validate(tampered)


def test_plan_bound_resume_replays_after_plan_advances_and_rejects_stale_use(
    client,
):
    case_id, source_sync, _claimed = _publish_transaction_checkpoint(client)
    initial_plan_response = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    )
    assert initial_plan_response.status_code == 200
    initial_plan = initial_plan_response.json()
    plan_id = initial_plan["plan"]["public_id"]
    checkpoint_id = initial_plan["document"]["streams"][0][
        "tip_checkpoint"
    ]["public_id"]
    idempotency_key = str(uuid4())
    resume_url = (
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan/"
        f"{plan_id}/{checkpoint_id}/resume"
    )

    queued_response = client.post(
        resume_url,
        headers={"Idempotency-Key": idempotency_key},
        json={"page_budget": 3},
    )

    assert queued_response.status_code == 202, queued_response.text
    assert queued_response.headers["cache-control"] == "no-store"
    assert queued_response.headers["retry-after"] == "1"
    queued = queued_response.json()
    assert queued_response.headers["location"].endswith(
        f"/syncs/{queued['public_id']}"
    )
    assert queued["requested_scope"] == {
        "mode": "resume",
        "time_window": "custom",
        "start_at": source_sync["requested_scope"]["start_at"],
        "end_at": source_sync["requested_scope"]["end_at"],
        "surfaces": ["transactions"],
        "acquisition_start_at": source_sync["requested_scope"]["start_at"],
        "acquisition_end_at": source_sync["requested_scope"]["end_at"],
        "overlap_seconds": 0,
        "base_snapshot_public_id": source_sync["public_id"],
        "source_checkpoint_public_id": checkpoint_id,
        "continuation_plan_public_id": plan_id,
        "resume_page_budget": 3,
    }
    with app.state.wallet_case_test_session() as session:
        persisted = session.scalar(
            select(CaseSync).where(CaseSync.public_id == queued["public_id"])
        )
        assert persisted is not None
        assert persisted.request_fingerprint == _checkpoint_resume_fingerprint(
            checkpoint_id,
            continuation_plan_public_id=plan_id,
            page_budget=3,
        )
        acquisition_plan = json.loads(persisted.coverage_summary_json)[
            "_acquisition"
        ]
        assert acquisition_plan["version"] == 4
        assert acquisition_plan["continuation_plan_public_id"] == plan_id
        assert acquisition_plan["resume_page_budget"] == 3
    changed_budget_reuse = client.post(
        resume_url,
        headers={"Idempotency-Key": idempotency_key},
        json={"page_budget": 2},
    )
    assert changed_budget_reuse.status_code == 409
    assert changed_budget_reuse.json()["detail"]["code"] == (
        "idempotency_conflict"
    )
    unbound_reuse = client.post(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{checkpoint_id}/resume",
        headers={"Idempotency-Key": idempotency_key},
    )
    assert unbound_reuse.status_code == 409
    assert unbound_reuse.json()["detail"]["code"] == "idempotency_conflict"

    seen_build_kwargs = []

    def recording_builder(payload, settings, **kwargs):
        seen_build_kwargs.append(kwargs)
        return _resumed_transaction_run(payload, settings, **kwargs)

    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=recording_builder,
    )
    assert worker.run_once() is True
    assert len(seen_build_kwargs) == 1
    assert seen_build_kwargs[0]["resume_page_budget"] == 3
    advanced_plan_response = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    )
    assert advanced_plan_response.status_code == 200
    advanced_plan_id = advanced_plan_response.json()["plan"]["public_id"]
    assert advanced_plan_id != plan_id

    replay = client.post(
        resume_url,
        headers={"Idempotency-Key": idempotency_key},
        json={"page_budget": 3},
    )
    assert replay.status_code == 202, replay.text
    assert replay.json()["public_id"] == queued["public_id"]
    assert replay.json()["state"] == "succeeded"
    assert replay.json()["requested_scope"] == queued["requested_scope"]

    stale = client.post(
        resume_url,
        headers={"Idempotency-Key": str(uuid4())},
        json={"page_budget": 3},
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == {
        "code": "continuation_plan_stale",
        "message_safe": (
            "Continuation Plan changed; verify the current plan before resuming."
        ),
        "retryable": False,
        "current_plan_public_id": advanced_plan_id,
    }
    assert _database_counts() == (1, 2, 2)


def test_plan_bound_resume_rejects_noncanonical_page_budgets(client):
    case_id, _source_sync, _claimed = _publish_transaction_checkpoint(client)
    plan = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    ).json()
    plan_id = plan["plan"]["public_id"]
    checkpoint_id = plan["document"]["streams"][0]["tip_checkpoint"][
        "public_id"
    ]
    resume_url = (
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan/"
        f"{plan_id}/{checkpoint_id}/resume"
    )

    for payload in (
        {"page_budget": 0},
        {"page_budget": 11},
        {"page_budget": "3"},
        {"page_budget": True},
        {"page_budget": 1, "unexpected": "field"},
    ):
        response = client.post(
            resume_url,
            headers={"Idempotency-Key": str(uuid4())},
            json=payload,
        )
        assert response.status_code == 422, response.text

    assert _database_counts() == (1, 1, 1)


def test_continuation_receipt_is_content_addressed_and_stable_after_later_resume(
    client,
):
    case_id, _source_sync, _claimed = _publish_multi_stream_checkpoints(client)
    initial_plan = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    ).json()
    ready_stream = next(
        stream
        for stream in initial_plan["document"]["streams"]
        if stream["resume_state"] == "ready"
    )
    input_checkpoint_id = ready_stream["tip_checkpoint"]["public_id"]
    first_queued = client.post(
        (
            f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan/"
            f"{initial_plan['plan']['public_id']}/{input_checkpoint_id}/resume"
        ),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert first_queued.status_code == 202, first_queued.text
    first_sync_id = first_queued.json()["public_id"]
    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=_resumed_transaction_run,
    )
    assert worker.run_once() is True

    receipt_response = client.get(
        f"/api/v1/cases/{case_id}/syncs/{first_sync_id}/continuation-receipt"
    )

    assert receipt_response.status_code == 200, receipt_response.text
    assert receipt_response.headers["cache-control"] == "no-store"
    receipt = receipt_response.json()
    validated = WalletCaseCheckpointContinuationReceiptResponse.model_validate(
        receipt
    )
    assert validated.receipt.public_id == (
        f"ctr_{validated.receipt.content_hash_sha256}"
    )
    assert receipt["receipt"]["sync_public_id"] == first_sync_id
    assert receipt["receipt"]["input_plan_public_id"] == initial_plan["plan"][
        "public_id"
    ]
    assert receipt["receipt"]["input_checkpoint_public_id"] == (
        input_checkpoint_id
    )
    output_checkpoint_id = receipt["receipt"]["output_checkpoint_public_id"]
    assert output_checkpoint_id != input_checkpoint_id
    assert receipt["document"]["input"]["next_page_index"] == 2
    assert receipt["document"]["output"]["next_page_index"] == 3
    assert receipt["document"]["transition"] == {
        "checkpoint_changed": True,
        "plan_changed": True,
        "revision_delta": 1,
        "page_count_delta": 1,
        "pages_succeeded_delta": 1,
    }
    after_plan = receipt["document"]["after_plan"]
    assert receipt["receipt"]["after_plan_public_id"] == after_plan["plan"][
        "public_id"
    ]
    assert after_plan["plan"]["checkpoint_cutoff_public_id"] == (
        output_checkpoint_id
    )
    assert after_plan["plan"]["stream_count"] == 2
    assert after_plan["plan"]["revision_count"] == 3
    assert client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    ).json() == after_plan

    tampered = json.loads(json.dumps(receipt))
    tampered["document"]["transition"]["page_count_delta"] = 0
    with pytest.raises(ValueError, match="transition is inconsistent"):
        WalletCaseCheckpointContinuationReceiptResponse.model_validate(
            tampered
        )

    second_queued = client.post(
        (
            f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan/"
            f"{after_plan['plan']['public_id']}/{output_checkpoint_id}/resume"
        ),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert second_queued.status_code == 202, second_queued.text
    assert worker.run_once() is True
    current_plan = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    ).json()
    assert current_plan["plan"]["public_id"] != after_plan["plan"]["public_id"]

    repeated = client.get(
        f"/api/v1/cases/{case_id}/syncs/{first_sync_id}/continuation-receipt"
    )
    assert repeated.status_code == 200
    assert repeated.json() == receipt


def test_continuation_receipt_is_plan_bound_terminal_and_case_scoped(client):
    first_case_id, bounded_sync, _claimed = _publish_transaction_checkpoint(
        client
    )
    bounded = client.get(
        f"/api/v1/cases/{first_case_id}/syncs/"
        f"{bounded_sync['public_id']}/continuation-receipt"
    )
    assert bounded.status_code == 404
    assert bounded.json()["detail"]["code"] == (
        "continuation_receipt_not_available"
    )

    plan = client.get(
        f"/api/v1/cases/{first_case_id}/stream-checkpoints/continuation-plan"
    ).json()
    checkpoint_id = plan["document"]["streams"][0]["tip_checkpoint"][
        "public_id"
    ]
    queued = client.post(
        (
            f"/api/v1/cases/{first_case_id}/stream-checkpoints/"
            f"continuation-plan/{plan['plan']['public_id']}/"
            f"{checkpoint_id}/resume"
        ),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert queued.status_code == 202, queued.text
    queued_sync_id = queued.json()["public_id"]
    pending = client.get(
        f"/api/v1/cases/{first_case_id}/syncs/"
        f"{queued_sync_id}/continuation-receipt"
    )
    assert pending.status_code == 404
    assert pending.json()["detail"]["message_safe"] == (
        "This plan-bound continuation has not published a result."
    )

    second_case_id = _create_case(client, address=f"0:{'4' * 64}")["case"][
        "public_id"
    ]
    foreign = client.get(
        f"/api/v1/cases/{second_case_id}/syncs/"
        f"{queued_sync_id}/continuation-receipt"
    )
    assert foreign.status_code == 404
    assert foreign.json()["detail"] == "Wallet Case sync not found"


def test_continuation_receipt_fails_closed_on_broken_output_lineage(client):
    case_id, _source_sync, _claimed = _publish_transaction_checkpoint(client)
    plan = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    ).json()
    checkpoint_id = plan["document"]["streams"][0]["tip_checkpoint"][
        "public_id"
    ]
    queued = client.post(
        (
            f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan/"
            f"{plan['plan']['public_id']}/{checkpoint_id}/resume"
        ),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert queued.status_code == 202, queued.text
    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=_resumed_transaction_run,
    )
    assert worker.run_once() is True
    sync_id = queued.json()["public_id"]

    with app.state.wallet_case_test_session() as session:
        persisted = session.scalar(
            select(CaseSync).where(CaseSync.public_id == sync_id)
        )
        assert persisted is not None
        stored = json.loads(persisted.coverage_summary_json)
        stored["_acquisition"]["source_checkpoint_public_id"] = (
            f"scp_{'0' * 64}"
        )
        persisted.coverage_summary_json = json.dumps(stored, sort_keys=True)
        session.commit()

    corrupt = client.get(
        f"/api/v1/cases/{case_id}/syncs/{sync_id}/continuation-receipt"
    )
    assert corrupt.status_code == 503
    assert corrupt.json()["detail"] == {
        "code": "continuation_receipt_integrity_error",
        "message_safe": (
            "Stored Wallet Case continuation receipt checkpoints are invalid."
        ),
        "retryable": False,
    }


def test_plan_bound_resume_is_case_scoped_and_requires_a_planned_tip(client):
    first_case_id, _sync, _claimed = _publish_transaction_checkpoint(client)
    second_case_id = _create_case(client, address=f"0:{'1' * 64}")["case"][
        "public_id"
    ]
    _publish_transaction_checkpoint(client, case_id=second_case_id)
    first_plan = client.get(
        f"/api/v1/cases/{first_case_id}/stream-checkpoints/continuation-plan"
    ).json()
    second_plan = client.get(
        f"/api/v1/cases/{second_case_id}/stream-checkpoints/continuation-plan"
    ).json()
    first_plan_id = first_plan["plan"]["public_id"]
    first_checkpoint_id = first_plan["document"]["streams"][0][
        "tip_checkpoint"
    ]["public_id"]
    second_plan_id = second_plan["plan"]["public_id"]
    second_checkpoint_id = second_plan["document"]["streams"][0][
        "tip_checkpoint"
    ]["public_id"]

    foreign_plan = client.post(
        (
            f"/api/v1/cases/{first_case_id}/stream-checkpoints/"
            f"continuation-plan/{second_plan_id}/{first_checkpoint_id}/resume"
        ),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert foreign_plan.status_code == 409
    assert foreign_plan.json()["detail"] == {
        "code": "continuation_plan_stale",
        "message_safe": (
            "Continuation Plan changed; verify the current plan before resuming."
        ),
        "retryable": False,
        "current_plan_public_id": first_plan_id,
    }

    foreign_tip = client.post(
        (
            f"/api/v1/cases/{first_case_id}/stream-checkpoints/"
            f"continuation-plan/{first_plan_id}/{second_checkpoint_id}/resume"
        ),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert foreign_tip.status_code == 409
    assert foreign_tip.json()["detail"]["code"] == (
        "checkpoint_resume_unavailable"
    )
    assert _database_counts() == (2, 2, 2)


def test_checkpoint_continuation_plan_is_empty_scoped_and_bounded(
    client,
    monkeypatch,
):
    empty_case_id = _create_case(client)["case"]["public_id"]
    empty = client.get(
        f"/api/v1/cases/{empty_case_id}/stream-checkpoints/continuation-plan"
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["plan"]["checkpoint_cutoff_public_id"] is None
    assert empty.json()["document"]["streams"] == []
    assert empty.json()["document"]["aggregate"] == {
        "stream_count": 0,
        "ready_count": 0,
        "complete_count": 0,
        "blocked_count": 0,
        "revision_count": 0,
        "page_count": 0,
        "pages_succeeded": 0,
    }
    populated_case_id, _sync, _claimed = _publish_transaction_checkpoint(
        client,
        case_id=_create_case(client, address=f"0:{'3' * 64}")["case"][
            "public_id"
        ],
    )
    scoped = client.get(
        f"/api/v1/cases/{empty_case_id}/stream-checkpoints/continuation-plan"
    )
    assert scoped.status_code == 200
    assert scoped.json() == empty.json()
    missing = client.get(
        f"/api/v1/cases/{uuid4()}/stream-checkpoints/continuation-plan"
    )
    assert missing.status_code == 404

    monkeypatch.setattr(
        "services.wallet_cases._MAX_CHECKPOINT_CONTINUATION_PLAN_STREAMS",
        0,
    )
    bounded = client.get(
        f"/api/v1/cases/{populated_case_id}/stream-checkpoints/continuation-plan"
    )
    assert bounded.status_code == 503
    assert bounded.json()["detail"] == {
        "code": "stream_checkpoint_integrity_error",
        "message_safe": (
            "Wallet Case continuation plan contains too many provider streams."
        ),
        "retryable": False,
    }


def test_checkpoint_chain_bounds_recursive_verification(client, monkeypatch):
    case_id, _source_sync, _claimed = _publish_transaction_checkpoint(client)
    with app.state.wallet_case_test_session() as session:
        root = session.scalar(select(WalletCaseStreamCheckpoint))
        assert root is not None
        root_id = root.public_id
    _completed, resumed_id = _resume_transaction_checkpoint(
        client,
        case_id=case_id,
        checkpoint_id=root_id,
    )
    monkeypatch.setattr(
        "services.wallet_cases._MAX_CHECKPOINT_CHAIN_REVISIONS",
        1,
    )

    response = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{resumed_id}/chain"
    )

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "stream_checkpoint_integrity_error",
        "message_safe": (
            "Stored Wallet Case stream checkpoint lineage is too deep."
        ),
        "retryable": False,
    }


def test_checkpoint_history_fails_closed_on_broken_resume_lineage(client):
    case_id, _source_sync, _claimed = _publish_transaction_checkpoint(client)
    with app.state.wallet_case_test_session() as session:
        root = session.scalar(select(WalletCaseStreamCheckpoint))
        assert root is not None
        root_id = root.public_id
    _completed, resumed_id = _resume_transaction_checkpoint(
        client,
        case_id=case_id,
        checkpoint_id=root_id,
    )
    with app.state.wallet_case_test_session() as session:
        resumed = session.scalar(
            select(WalletCaseStreamCheckpoint).where(
                WalletCaseStreamCheckpoint.public_id == resumed_id
            )
        )
        assert resumed is not None
        stored = json.loads(resumed.source_sync.coverage_summary_json)
        stored["_acquisition"]["base_snapshot_public_id"] = str(uuid4())
        resumed.source_sync.coverage_summary_json = json.dumps(
            stored,
            sort_keys=True,
        )
        session.commit()

    exact = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{resumed_id}"
    )
    history = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/history"
    )
    chain = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{resumed_id}/chain"
    )
    plan = client.get(
        f"/api/v1/cases/{case_id}/stream-checkpoints/continuation-plan"
    )
    for response in (exact, history, chain, plan):
        assert response.status_code == 503
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["detail"] == {
            "code": "stream_checkpoint_integrity_error",
            "message_safe": (
                "Stored Wallet Case stream checkpoint parent is invalid."
            ),
            "retryable": False,
        }


def test_checkpoint_history_empty_and_exact_read_are_case_scoped(client):
    first_case_id = _create_case(client)["case"]["public_id"]
    empty = client.get(
        f"/api/v1/cases/{first_case_id}/stream-checkpoints/history"
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["revision_cutoff_public_id"] is None
    assert empty.json()["items"] == []
    assert empty.json()["aggregate"] == {
        "total_revisions": 0,
        "returned_count": 0,
    }

    second_case_id, _sync, _claimed = _publish_transaction_checkpoint(
        client,
        case_id=_create_case(client, address=f"0:{'2' * 64}")["case"][
            "public_id"
        ],
    )
    with app.state.wallet_case_test_session() as session:
        checkpoint = session.scalar(
            select(WalletCaseStreamCheckpoint).where(
                WalletCaseStreamCheckpoint.case.has(public_id=second_case_id)
            )
        )
        assert checkpoint is not None
        checkpoint_id = checkpoint.public_id
    missing = client.get(
        f"/api/v1/cases/{first_case_id}/stream-checkpoints/{checkpoint_id}"
    )
    assert missing.status_code == 404
    missing_chain = client.get(
        f"/api/v1/cases/{first_case_id}/stream-checkpoints/{checkpoint_id}/chain"
    )
    assert missing_chain.status_code == 404
    unsupported = client.get(
        f"/api/v1/cases/{first_case_id}/stream-checkpoints/history?offset=1"
    )
    assert unsupported.status_code == 422


def test_stream_checkpoint_resume_rejects_blocked_and_stale_records(client):
    blocked_case_id, _sync, _claimed = _publish_transaction_checkpoint(
        client,
        completion_state="incomplete",
        termination_reason="protocol_error",
    )
    with app.state.wallet_case_test_session() as session:
        blocked = session.scalar(
            select(WalletCaseStreamCheckpoint).where(
                WalletCaseStreamCheckpoint.case.has(public_id=blocked_case_id)
            )
        )
        assert blocked is not None
        assert blocked.resume_state == "blocked"
        blocked_id = blocked.public_id

    blocked_response = client.post(
        f"/api/v1/cases/{blocked_case_id}/stream-checkpoints/{blocked_id}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert blocked_response.status_code == 409
    assert blocked_response.json()["detail"]["code"] == (
        "checkpoint_resume_unavailable"
    )

    case_id, _first_sync, _claimed = _publish_transaction_checkpoint(client)
    with app.state.wallet_case_test_session() as session:
        first = session.scalar(
            select(WalletCaseStreamCheckpoint)
            .where(WalletCaseStreamCheckpoint.case.has(public_id=case_id))
            .order_by(WalletCaseStreamCheckpoint.id)
        )
        assert first is not None
        first_id = first.public_id
    _publish_transaction_checkpoint(client, case_id=case_id, cursor="9")

    stale_response = client.post(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{first_id}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert stale_response.status_code == 409
    assert stale_response.json()["detail"]["code"] == (
        "checkpoint_resume_unavailable"
    )
    assert _database_counts() == (1, 3, 3)


def test_checkpoint_is_revalidated_before_resume_provider_execution(client):
    case_id, _source_sync, _claimed = _publish_transaction_checkpoint(client)
    with app.state.wallet_case_test_session() as session:
        checkpoint = session.scalar(select(WalletCaseStreamCheckpoint))
        assert checkpoint is not None
        checkpoint_id = checkpoint.public_id

    queued = client.post(
        f"/api/v1/cases/{case_id}/stream-checkpoints/{checkpoint_id}/resume",
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert queued.status_code == 202, queued.text

    with app.state.wallet_case_test_session() as session:
        checkpoint = session.scalar(
            select(WalletCaseStreamCheckpoint).where(
                WalletCaseStreamCheckpoint.public_id == checkpoint_id
            )
        )
        assert checkpoint is not None
        checkpoint.checkpoint_json = (
            '{"contract_version":"wallet_case_stream_checkpoint_v1"}'
        )
        session.commit()

    def forbidden_builder(*_args, **_kwargs):
        pytest.fail("corrupt continuation state must fail before provider I/O")

    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=forbidden_builder,
    )
    assert worker.run_once() is True
    failed = client.get(
        f"/api/v1/cases/{case_id}/syncs/{queued.json()['public_id']}"
    )
    assert failed.status_code == 200, failed.text
    assert failed.json()["state"] == "failed"
    assert failed.json()["error"]["code"] == "runtime_scope_conflict"
    assert "integrity" in failed.json()["error"]["message_safe"]
    assert _database_counts() == (1, 2, 1)


def test_legacy_usable_sync_without_manifest_is_labeled_honestly(client):
    case_id = _create_case(client)["case"]["public_id"]
    sync = _sync_case(client, case_id, surfaces=["transactions"])
    with app.state.wallet_case_test_session() as session:
        manifest = session.scalar(select(WalletCaseSyncManifest))
        assert manifest is not None
        session.delete(manifest)
        session.commit()

    response = client.get(
        f"/api/v1/cases/{case_id}/syncs/{sync['public_id']}"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["acquisition_manifest"] is None
    assert "acquisition_manifest_unavailable" in {
        item["code"] for item in body["limitations"]
    }
    assert client.get(
        f"/api/v1/cases/{case_id}/syncs/{sync['public_id']}/manifest"
    ).status_code == 404


def test_manifest_read_fails_closed_when_payload_hash_is_corrupt(client):
    case_id = _create_case(client)["case"]["public_id"]
    sync = _sync_case(client, case_id, surfaces=["transactions"])
    with app.state.wallet_case_test_session() as session:
        manifest = session.scalar(select(WalletCaseSyncManifest))
        assert manifest is not None
        manifest.manifest_json = '{"contract_version":"wallet_case_sync_manifest_v1"}'
        session.commit()

    manifest_response = client.get(
        f"/api/v1/cases/{case_id}/syncs/{sync['public_id']}/manifest"
    )
    sync_response = client.get(
        f"/api/v1/cases/{case_id}/syncs/{sync['public_id']}"
    )

    assert manifest_response.status_code == 503
    assert manifest_response.headers["cache-control"] == "no-store"
    assert manifest_response.json()["detail"] == {
        "code": "acquisition_manifest_integrity_error",
        "message_safe": (
            "Stored Wallet Case acquisition manifest failed integrity validation."
        ),
        "retryable": False,
    }
    assert sync_response.status_code == 503
    assert sync_response.json()["detail"]["code"] == (
        "acquisition_manifest_integrity_error"
    )


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
    wrong_manifest_case = client.get(
        f"/api/v1/cases/{second['case']['public_id']}/syncs/"
        f"{sync['public_id']}/manifest"
    )
    sequential_case = client.get("/api/v1/cases/1")
    uppercase_case = client.get(
        f"/api/v1/cases/{first['case']['public_id'].upper()}"
    )

    assert wrong_case.status_code == 404
    assert wrong_manifest_case.status_code == 404
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
    assert job["acquisition_manifest"] is None
    assert {item["code"] for item in job["limitations"]}.isdisjoint(
        {"summary_unavailable", "coverage_unavailable"}
    )
    assert _database_counts() == (1, 1, 0)
    unavailable_manifest = client.get(
        f"/api/v1/cases/{case_id}/syncs/{job['public_id']}/manifest"
    )
    assert unavailable_manifest.status_code == 404
    assert unavailable_manifest.headers["cache-control"] == "no-store"
    assert unavailable_manifest.json()["detail"]["code"] == (
        "acquisition_manifest_not_found"
    )

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


def test_incremental_sync_requires_a_usable_matching_base_snapshot(client):
    case_id = _create_case(client)["case"]["public_id"]
    without_base = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "mode": "incremental",
            "surfaces": ["transactions"],
        },
    )
    assert without_base.status_code == 409
    assert without_base.json()["detail"] == {
        "code": "incremental_sync_unavailable",
        "message_safe": (
            "Build a usable bounded snapshot before requesting an incremental "
            "refresh."
        ),
        "retryable": False,
    }
    assert _database_counts() == (1, 0, 0)

    _sync_case(client, case_id, surfaces=["transactions"])
    mismatched = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "mode": "incremental",
            "surfaces": ["balances"],
        },
    )
    assert mismatched.status_code == 409
    assert mismatched.json()["detail"] == {
        "code": "incremental_sync_unavailable",
        "message_safe": (
            "Incremental refresh surfaces must match the base snapshot."
        ),
        "retryable": False,
    }
    assert _database_counts() == (1, 1, 1)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "mode": "incremental",
            "time_window": "3d",
            "surfaces": ["transactions"],
        },
        {
            "mode": "incremental",
            "time_window": "24h",
            "custom_start": "2026-08-01T00:00:00Z",
            "custom_end": "2026-08-02T00:00:00Z",
            "surfaces": ["transactions"],
        },
    ],
)
def test_incremental_sync_rejects_caller_defined_time_bounds(client, payload):
    case_id = _create_case(client)["case"]["public_id"]
    response = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json=payload,
    )
    assert response.status_code == 422
    assert _database_counts() == (1, 0, 0)


def test_incremental_sync_acquires_only_forward_overlap_and_keeps_lineage(client):
    case_id = _create_case(client)["case"]["public_id"]
    base = _sync_case(client, case_id, surfaces=["transactions"])
    seen_payloads = []

    def recording_builder(payload, *args, **kwargs):
        seen_payloads.append(payload)
        return build_wallet_ingestion_run(payload, *args, **kwargs)

    queued = client.post(
        f"/api/v1/cases/{case_id}/syncs",
        headers={"Idempotency-Key": str(uuid4())},
        json={
            "mode": "incremental",
            "surfaces": ["transactions"],
        },
    )
    assert queued.status_code == 202, queued.text
    scope = queued.json()["requested_scope"]
    assert scope["mode"] == "incremental"
    assert scope["time_window"] == "custom"
    assert scope["start_at"] == base["requested_scope"]["start_at"]
    assert scope["base_snapshot_public_id"] == base["public_id"]
    assert scope["overlap_seconds"] == 900
    assert scope["acquisition_end_at"] == scope["end_at"]
    assert _parse_utc(scope["acquisition_start_at"]) == (
        _parse_utc(base["requested_scope"]["end_at"])
        - timedelta(minutes=15)
    )

    worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        builder=recording_builder,
    )
    assert worker.run_once() is True
    assert len(seen_payloads) == 1
    acquisition = seen_payloads[0]
    assert acquisition.time_window == "custom"
    assert _parse_utc(acquisition.custom_start) == _parse_utc(
        scope["acquisition_start_at"]
    )
    assert _parse_utc(acquisition.custom_end) == _parse_utc(
        scope["acquisition_end_at"]
    )

    completed = client.get(
        f"/api/v1/cases/{case_id}/syncs/{queued.json()['public_id']}"
    )
    assert completed.status_code == 200, completed.text
    body = completed.json()
    assert body["state"] == "succeeded"
    assert body["coverage"]["state"] == "unknown"
    assert "_acquisition" not in json.dumps(body)
    assert "incremental_composite_not_full_history" in {
        item["code"] for item in body["limitations"]
    }

    with Session(app.state.wallet_case_test_engine) as session:
        stored = session.scalar(
            select(CaseSync).where(CaseSync.public_id == body["public_id"])
        )
        assert stored is not None
        persisted_coverage = json.loads(stored.coverage_summary_json)
        assert persisted_coverage["_acquisition"] == {
            "version": 1,
            "mode": "incremental",
            "start_at": scope["acquisition_start_at"],
            "end_at": scope["acquisition_end_at"],
            "overlap_seconds": 900,
            "base_snapshot_public_id": base["public_id"],
        }


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


def test_stale_final_publication_rolls_back_run_manifest_and_checkpoints(client):
    case_id = _create_case(client)["case"]["public_id"]
    clock = [datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)]
    with app.state.wallet_case_test_session() as session:
        WalletCaseService(session).enqueue_sync(
            case_id,
            WalletCaseSyncRequest(
                time_window="24h",
                surfaces=["transactions"],
            ),
            str(uuid4()),
            now=clock[0],
        )
    stale_worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        clock=lambda: clock[0],
        lease_seconds=30,
    )
    stale_claim = stale_worker.claim_next()
    assert stale_claim is not None
    settings = stale_worker._validated_settings(stale_claim)
    run = build_wallet_ingestion_run(
        WalletIngestionPreviewRequest(
            wallet_address=stale_claim.display_address,
            time_window=stale_claim.time_window,
            surfaces=list(stale_claim.requested_surfaces),
        ),
        settings,
        now=clock[0],
    )
    _attach_transaction_stream(run, stale_claim)
    run_response = wallet_ingestion_run_to_response(run)

    clock[0] += timedelta(seconds=31)
    replacement_worker = CaseSyncWorker(
        app.state.wallet_case_test_session,
        clock=lambda: clock[0],
        lease_seconds=30,
    )
    assert replacement_worker.recover_expired() == 1
    replacement = replacement_worker.claim_next()
    assert replacement is not None

    assert stale_worker._publish_final_run(
        stale_claim,
        run,
        run_response,
        settings,
        last_error_retryable=False,
    ) is False
    with app.state.wallet_case_test_session() as session:
        assert session.scalar(
            select(func.count()).select_from(WalletIngestionRun)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(WalletCaseSyncManifest)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(WalletCaseStreamCheckpoint)
        ) == 0
        current = session.scalar(select(CaseSync))
        assert current is not None
        assert current.state == "running"
        assert current.lease_token == replacement.lease_token


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
