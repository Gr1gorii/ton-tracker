"""Focused API and durable-worker regressions for Wallet Case evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from threading import Event, Thread
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from fastapi.exceptions import ResponseValidationError
from pydantic import ValidationError
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

from adapters.tonapi import TonapiAdapter
from adapters.wallet_activity import TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
from config import ProviderResult, get_settings
from database import create_database_engine, get_session
from main import app
from models import (
    CaseSync,
    CaseEvidenceVerification,
    WalletTraceBocTransaction,
    WalletTransactionInclusionProof,
)
import services.wallet_native_activity_ledger as legacy_ledger_service
import services.wallet_trace_boc_verification as legacy_boc_service
import services.wallet_transaction_inclusion_proof as legacy_inclusion_service
import services.wallet_case_evidence as evidence_service_module
from services.case_evidence_jobs import CaseEvidenceWorker
from services.database_migrations import run_database_migrations
from services.ton_liteclient_config import (
    CURRENT_VERIFIER_POLICY_ID,
    trusted_checkpoint_document,
)
from services.wallet_case_activity import WalletCaseActivityService
from services.wallet_case_evidence import (
    CaseEvidenceService,
    CaseEvidenceStoredConflict,
    _clear_selection_cache_for_tests,
    _request_fingerprint,
)
from services.wallet_trace_evidence import WalletTraceEvidenceProviderFailure
from services.wallet_native_activity_ledger import build_wallet_native_activity_ledger
from services.wallet_native_activity_ledger import (
    WalletNativeActivityLedgerConflict,
    WalletNativeActivityLedgerFailure,
)
from services.wallet_persisted_trace_evidence import (
    WalletPersistedTraceEvidenceConflict,
    capture_persisted_wallet_transaction_trace_evidence,
)
from services.wallet_trace_boc_verification import (
    WalletTraceBocVerificationConflict,
    verify_wallet_transaction_trace_bocs,
)
from services.wallet_transaction_inclusion_proof import (
    WalletTransactionInclusionProofConflict,
    WalletTransactionInclusionProofFailure,
    create_wallet_transaction_inclusion_proofs,
)
from wallet_case_evidence_schemas import (
    CaseEvidenceVerificationRequest,
    CaseEvidenceVerificationResponse,
)

from backend.tests.test_wallet_case_activity import (
    END,
    START,
    _case,
    _demo_transaction,
    _run_and_sync,
    _swap,
    _transaction,
    _transfer,
)
from backend.tests.test_wallet_persisted_trace_evidence import (
    CHILD_HASH,
    ROOT_ACCOUNT,
    ROOT_HASH,
    ROOT_IN_HASH,
    ROOT_LT,
    ROOT_OUT_HASH,
    _fake_boc_derived,
    _normalized_finalized_candidate,
)


class ManualEvidenceRunner:
    def __init__(self, *, alive: bool = True) -> None:
        self.alive = alive
        self.notifications = 0

    def notify(self) -> None:
        self.notifications += 1


@pytest.fixture
def evidence_api(tmp_path, monkeypatch):
    _clear_selection_cache_for_tests()
    engine = create_database_engine(f"sqlite:///{tmp_path / 'case-evidence.sqlite3'}")
    assert run_database_migrations(engine).revision_after == "20260827_0026"
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        with sessions() as session:
            yield session

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setenv("TONAPI_API_KEY", "case-evidence-test-key")
    monkeypatch.setenv("TON_LITECLIENT_TRUST_LEVEL", "0")
    runner = ManualEvidenceRunner()
    app.dependency_overrides[get_session] = override
    app.state.wallet_case_evidence_runner = runner
    client = TestClient(app)
    fixture = SimpleNamespace(
        client=client,
        engine=engine,
        sessions=sessions,
        runner=runner,
        monkeypatch=monkeypatch,
    )
    try:
        yield fixture
    finally:
        app.dependency_overrides.clear()
        app.state.wallet_case_evidence_runner = None
        engine.dispose()
        _clear_selection_cache_for_tests()


def _seed_live_transaction(fixture, *, tx_hash: str = "a1" * 32):
    with fixture.sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        run.transactions.append(
            _transaction(
                run,
                tx_hash=tx_hash,
                logical_time="100",
                timestamp=START + timedelta(hours=1),
            )
        )
        case_id = wallet_case.public_id
        snapshot_id = snapshot.public_id
        session.commit()
    response = fixture.client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id},
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    return SimpleNamespace(
        case_id=case_id,
        snapshot_id=snapshot_id,
        activity_id=item["public_id"],
        tx_hash=tx_hash,
    )


def _post_verification(fixture, seeded, *, key: str | None = None):
    return fixture.client.post(
        f"/api/v1/cases/{seeded.case_id}/evidence/verifications",
        headers={"Idempotency-Key": key or str(uuid4())},
        json={
            "snapshot_public_id": seeded.snapshot_id,
            "activity_public_id": seeded.activity_id,
            "policy": "transaction_inclusion_v1",
        },
    )


def test_enqueue_is_strict_no_store_and_replays_before_runtime_preflight(
    evidence_api,
):
    seeded = _seed_live_transaction(evidence_api)
    key = str(uuid4())

    created = _post_verification(evidence_api, seeded, key=key)

    assert created.status_code == 202, created.text
    assert created.headers["cache-control"] == "no-store"
    body = created.json()
    assert body["state"] == "queued"
    assert body["stage"] == "queued"
    assert body["progress"] == {"current": 0, "total": 4}
    assert body["result"] is None
    assert body["error"] is None
    assert body["retry"] is None
    assert created.headers["location"].endswith(body["public_id"])
    assert "run_id" not in created.text
    assert "lease" not in created.text
    assert evidence_api.runner.notifications == 1

    evidence_api.runner.alive = False
    evidence_api.monkeypatch.setenv("DATA_MODE", "mock")
    replay = _post_verification(evidence_api, seeded, key=key)
    assert replay.status_code == 202, replay.text
    assert replay.json()["public_id"] == body["public_id"]
    assert evidence_api.runner.notifications == 1

    unavailable = _post_verification(evidence_api, seeded)
    assert unavailable.status_code == 503
    assert unavailable.json()["detail"]["code"] == "evidence_runner_unavailable"
    with evidence_api.sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(CaseEvidenceVerification)
        ) == 1


def test_catalog_accepts_the_actual_guarded_live_sync_provider(evidence_api):
    seeded = _seed_live_transaction(evidence_api)

    with evidence_api.sessions() as session:
        snapshot = session.scalar(
            select(CaseSync).where(CaseSync.public_id == seeded.snapshot_id)
        )
        assert snapshot is not None
        assert snapshot.provider == TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER

    response = evidence_api.client.get(
        f"/api/v1/cases/{seeded.case_id}/evidence",
        params={"snapshot": seeded.snapshot_id},
    )

    assert response.status_code == 200, response.text
    assert response.json()["readiness"]["transaction_verification_available"] is True

    created = _post_verification(evidence_api, seeded)
    assert created.status_code == 202, created.text
    assert created.json()["provenance"]["provider"] == "tonapi"


def test_concurrent_same_idempotency_key_converges_before_active_conflict(
    evidence_api,
    monkeypatch,
):
    seeded = _seed_live_transaction(evidence_api)
    key = str(uuid4())
    payload = CaseEvidenceVerificationRequest(
        snapshot_public_id=seeded.snapshot_id,
        activity_public_id=seeded.activity_id,
        policy="transaction_inclusion_v1",
    )
    session_b = evidence_api.sessions()
    service_b = CaseEvidenceService(session_b)
    original_resolve = service_b._resolve
    created_by_a: dict[str, str] = {}

    def resolve_then_commit_a(*args, **kwargs):
        resolved = original_resolve(*args, **kwargs)
        session_b.rollback()
        with evidence_api.sessions() as session_a:
            response_a, replayed_a = CaseEvidenceService(session_a).enqueue(
                seeded.case_id,
                payload,
                key,
                runner_available=True,
            )
        assert replayed_a is False
        created_by_a["public_id"] = response_a["public_id"]
        return resolved

    monkeypatch.setattr(service_b, "_resolve", resolve_then_commit_a)
    try:
        response_b, replayed_b = service_b.enqueue(
            seeded.case_id,
            payload,
            key,
            runner_available=True,
        )
    finally:
        session_b.close()

    assert replayed_b is True
    assert response_b["public_id"] == created_by_a["public_id"]
    with evidence_api.sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(CaseEvidenceVerification)
        ) == 1


def test_cancel_cas_reloads_truth_after_queued_job_is_concurrently_claimed(
    evidence_api,
    monkeypatch,
):
    seeded = _seed_live_transaction(evidence_api)
    created = _post_verification(evidence_api, seeded)
    verification_id = created.json()["public_id"]
    primary = evidence_api.sessions()
    original_execute = primary.execute
    interleaved = False

    def execute_with_claim(statement, *args, **kwargs):
        nonlocal interleaved
        if not interleaved and statement.__class__.__name__ == "Update":
            interleaved = True
            now = datetime.now(timezone.utc)
            with evidence_api.sessions() as concurrent:
                job = concurrent.scalar(
                    select(CaseEvidenceVerification).where(
                        CaseEvidenceVerification.public_id == verification_id
                    )
                )
                job.state = "running"
                job.stage = "validating"
                job.attempt_count += 1
                job.next_attempt_at = None
                job.lease_token = "concurrent-claim"
                job.lease_expires_at = now + timedelta(minutes=1)
                job.heartbeat_at = now
                job.started_at = now
                job.updated_at = now
                job.status_version += 1
                concurrent.commit()
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(primary, "execute", execute_with_claim)
    try:
        response, accepted = CaseEvidenceService(primary).cancel(
            seeded.case_id,
            verification_id,
        )
    finally:
        primary.close()

    assert interleaved is True
    assert accepted is True
    assert response["state"] == "running"
    assert response["cancel_requested"] is True
    with evidence_api.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == verification_id
            )
        )
        assert job.state == "running"
        assert job.cancel_requested_at is not None


def test_cancel_cas_returns_terminal_truth_after_running_job_finishes(
    evidence_api,
    monkeypatch,
):
    seeded = _seed_live_transaction(evidence_api)
    created = _post_verification(evidence_api, seeded)
    verification_id = created.json()["public_id"]
    now = datetime.now(timezone.utc)
    with evidence_api.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == verification_id
            )
        )
        job.state = "running"
        job.stage = "validating"
        job.attempt_count = 1
        job.next_attempt_at = None
        job.lease_token = "running-before-cancel"
        job.lease_expires_at = now + timedelta(minutes=1)
        job.heartbeat_at = now
        job.started_at = now
        job.updated_at = now
        job.status_version += 1
        session.commit()

    primary = evidence_api.sessions()
    original_execute = primary.execute
    interleaved = False

    def execute_after_terminal(statement, *args, **kwargs):
        nonlocal interleaved
        if not interleaved and statement.__class__.__name__ == "Update":
            interleaved = True
            completed = datetime.now(timezone.utc)
            with evidence_api.sessions() as concurrent:
                job = concurrent.scalar(
                    select(CaseEvidenceVerification).where(
                        CaseEvidenceVerification.public_id == verification_id
                    )
                )
                job.state = "failed"
                job.stage = "terminal"
                job.next_attempt_at = None
                job.lease_token = None
                job.lease_expires_at = None
                job.completed_at = completed
                job.updated_at = completed
                job.error_code = "evidence_worker_failed"
                job.error_detail_safe = "Evidence worker failed."
                job.message_safe = "Evidence worker failed."
                job.status_version += 1
                concurrent.commit()
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(primary, "execute", execute_after_terminal)
    try:
        response, accepted = CaseEvidenceService(primary).cancel(
            seeded.case_id,
            verification_id,
        )
    finally:
        primary.close()

    assert interleaved is True
    assert accepted is False
    assert response["state"] == "failed"
    assert response["cancel_requested"] is False
    with evidence_api.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == verification_id
            )
        )
        assert job.state == "failed"
        assert job.cancel_requested_at is None


def test_cancel_cas_never_reports_acceptance_after_bounded_compare_swap_misses(
    evidence_api,
    monkeypatch,
):
    seeded = _seed_live_transaction(evidence_api)
    created = _post_verification(evidence_api, seeded)
    verification_id = created.json()["public_id"]
    now = datetime.now(timezone.utc)
    with evidence_api.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == verification_id
            )
        )
        job.state = "running"
        job.stage = "validating"
        job.attempt_count = 1
        job.next_attempt_at = None
        job.lease_token = "always-racing"
        job.lease_expires_at = now + timedelta(minutes=1)
        job.heartbeat_at = now
        job.started_at = now
        job.updated_at = now
        job.status_version += 1
        session.commit()

    primary = evidence_api.sessions()
    original_execute = primary.execute
    misses = 0

    def lose_every_cas(statement, *args, **kwargs):
        nonlocal misses
        if statement.__class__.__name__ == "Update":
            misses += 1
            return SimpleNamespace(rowcount=0)
        return original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(primary, "execute", lose_every_cas)
    try:
        response, accepted = CaseEvidenceService(primary).cancel(
            seeded.case_id,
            verification_id,
        )
    finally:
        primary.close()

    assert misses == 8
    assert accepted is False
    assert response["state"] == "running"
    assert response["cancel_requested"] is False


def test_evidence_routes_inherit_remote_host_and_origin_local_boundary(
    evidence_api,
):
    seeded = _seed_live_transaction(evidence_api)
    request_json = {
        "snapshot_public_id": seeded.snapshot_id,
        "activity_public_id": seeded.activity_id,
        "policy": "transaction_inclusion_v1",
    }
    remote = TestClient(app, client=("203.0.113.10", 50000))
    rebound = TestClient(app, client=("127.0.0.1", 49152))
    try:
        responses = [
            remote.get(
                f"/api/v1/cases/{seeded.case_id}/evidence",
                headers={"X-Forwarded-For": "127.0.0.1"},
            ),
            remote.post(
                f"/api/v1/cases/{seeded.case_id}/evidence/verifications",
                headers={
                    "Idempotency-Key": str(uuid4()),
                    "X-Forwarded-For": "127.0.0.1",
                },
                json=request_json,
            ),
            rebound.get(
                f"/api/v1/cases/{seeded.case_id}/evidence",
                headers={
                    "Host": "attacker.example:8000",
                    "Origin": "http://attacker.example:8000",
                },
            ),
            rebound.post(
                f"/api/v1/cases/{seeded.case_id}/evidence/verifications",
                headers={
                    "Host": "localhost:8000",
                    "Origin": "http://attacker.example",
                    "Idempotency-Key": str(uuid4()),
                },
                json=request_json,
            ),
        ]
    finally:
        remote.close()
        rebound.close()

    assert [item.status_code for item in responses] == [403, 403, 403, 403]
    assert all("local-only" in item.json()["detail"] for item in responses)
    with evidence_api.sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(CaseEvidenceVerification)
        ) == 0


def test_hosted_disabled_evidence_runner_never_persists_a_job(evidence_api):
    seeded = _seed_live_transaction(evidence_api)
    evidence_api.monkeypatch.setenv("WALLET_CASE_EVIDENCE_RUNNER", "disabled")
    app.state.wallet_case_evidence_runner = None

    response = _post_verification(evidence_api, seeded)

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "evidence_runner_unavailable"
    with evidence_api.sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(CaseEvidenceVerification)
        ) == 0


def test_evidence_public_payloads_recursively_exclude_internal_and_raw_keys(
    evidence_api,
):
    seeded = _seed_live_transaction(evidence_api)
    created = _post_verification(evidence_api, seeded)
    verification_id = created.json()["public_id"]
    status = evidence_api.client.get(
        f"/api/v1/cases/{seeded.case_id}/evidence/verifications/"
        f"{verification_id}"
    )
    catalog = evidence_api.client.get(
        f"/api/v1/cases/{seeded.case_id}/evidence",
        params={"snapshot": seeded.snapshot_id},
    )
    cancelled = evidence_api.client.post(
        f"/api/v1/cases/{seeded.case_id}/evidence/verifications/"
        f"{verification_id}/cancel"
    )
    assert [created.status_code, status.status_code, catalog.status_code, cancelled.status_code] == [
        202,
        200,
        200,
        200,
    ]
    forbidden = {
        "id",
        "case_id",
        "run_id",
        "ingestion_run_id",
        "snapshot_sync_id",
        "source_sync_id",
        "source_transaction_id",
        "trace_capture_id",
        "boc_verification_id",
        "native_ledger_id",
        "lease_token",
        "lease_expires_at",
        "heartbeat_at",
        "idempotency_key",
        "request_fingerprint",
        "checkpoint_json",
        "raw",
        "raw_json",
        "raw_boc",
        "transaction_boc_hex",
        "block_proof_boc_hex",
        "provider_payload",
    }

    def keys(value):
        if isinstance(value, dict):
            yield from value
            for child in value.values():
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    for response in (created, status, catalog, cancelled):
        assert forbidden.isdisjoint(set(keys(response.json())))


def test_catalog_readiness_requires_runner_and_matching_live_runtime(evidence_api):
    seeded = _seed_live_transaction(evidence_api)
    path = f"/api/v1/cases/{seeded.case_id}/evidence?snapshot={seeded.snapshot_id}"

    ready = evidence_api.client.get(path)
    assert ready.status_code == 200, ready.text
    assert ready.json()["readiness"]["transaction_verification_available"] is True

    evidence_api.runner.alive = False
    dead = evidence_api.client.get(path)
    assert dead.status_code == 200
    assert dead.json()["readiness"]["transaction_verification_available"] is False
    assert "evidence_runner_unavailable" in {
        item["code"] for item in dead.json()["limitations"]
    }

    evidence_api.runner.alive = True
    evidence_api.monkeypatch.setenv("DATA_MODE", "mock")
    drifted = evidence_api.client.get(path)
    assert drifted.status_code == 200
    assert drifted.json()["readiness"]["transaction_verification_available"] is False
    assert "evidence_runtime_unavailable" in {
        item["code"] for item in drifted.json()["limitations"]
    }

    evidence_api.monkeypatch.setenv("DATA_MODE", "real")
    evidence_api.monkeypatch.setenv("TON_LITECLIENT_TRUST_LEVEL", "1")
    weak_trust = evidence_api.client.get(path)
    assert weak_trust.status_code == 200
    assert weak_trust.json()["readiness"]["transaction_verification_available"] is False
    assert "evidence_runtime_unavailable" in {
        item["code"] for item in weak_trust.json()["limitations"]
    }
    rejected = _post_verification(evidence_api, seeded)
    assert rejected.status_code == 503
    with evidence_api.sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(CaseEvidenceVerification)
        ) == 0


def test_repeated_active_status_poll_reuses_bounded_selection_validation(
    evidence_api,
    monkeypatch,
):
    seeded = _seed_live_transaction(evidence_api)
    created = _post_verification(evidence_api, seeded)
    assert created.status_code == 202
    original = WalletCaseActivityService.resolve_verifiable_transaction_revision
    calls = 0

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        WalletCaseActivityService,
        "resolve_verifiable_transaction_revision",
        counted,
    )
    path = (
        f"/api/v1/cases/{seeded.case_id}/evidence/verifications/"
        f"{created.json()['public_id']}"
    )
    for _ in range(8):
        response = evidence_api.client.get(path)
        assert response.status_code == 200, response.text
    assert calls == 1


def test_demo_transfer_swap_and_unknown_activity_reject_before_persistence(
    evidence_api,
):
    candidates: list[tuple[str, str, str]] = []
    with evidence_api.sessions() as session:
        live_case = _case(session)
        live_run, live_snapshot = _run_and_sync(
            session,
            live_case,
            surfaces=["transfers", "swaps"],
        )
        live_run.transfers.append(
            _transfer(
                live_run,
                event_id="b1" * 32,
                logical_time="201",
                action_index=0,
                contract="0:" + "22" * 32,
            )
        )
        live_run.swaps.append(
            _swap(
                live_run,
                event_id="b2" * 32,
                action_index=1,
                token_in_standard="native",
                token_in_address=None,
            )
        )
        demo_case = _case(session, environment="demo", account="0:" + "44" * 32)
        demo_run, demo_snapshot = _run_and_sync(session, demo_case)
        demo_run.transactions.append(
            _demo_transaction(demo_run, timestamp=START + timedelta(hours=3))
        )
        live_case_id, live_snapshot_id = live_case.public_id, live_snapshot.public_id
        demo_case_id, demo_snapshot_id = demo_case.public_id, demo_snapshot.public_id
        session.commit()

    for case_id, snapshot_id in (
        (live_case_id, live_snapshot_id),
        (demo_case_id, demo_snapshot_id),
    ):
        activity = evidence_api.client.get(
            f"/api/v1/cases/{case_id}/activity", params={"snapshot": snapshot_id}
        )
        assert activity.status_code == 200, activity.text
        for item in activity.json()["items"]:
            candidates.append((case_id, snapshot_id, item["public_id"]))

    candidates.append((live_case_id, live_snapshot_id, "act_" + "ff" * 32))
    statuses = []
    for case_id, snapshot_id, activity_id in candidates:
        response = evidence_api.client.post(
            f"/api/v1/cases/{case_id}/evidence/verifications",
            headers={"Idempotency-Key": str(uuid4())},
            json={
                "snapshot_public_id": snapshot_id,
                "activity_public_id": activity_id,
                "policy": "transaction_inclusion_v1",
            },
        )
        statuses.append(response.status_code)
    assert statuses[:-1] == [409, 409, 409]
    assert statuses[-1] == 404
    with evidence_api.sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(CaseEvidenceVerification)
        ) == 0


def _terminal_clone(base: CaseEvidenceVerification, *, offset: int):
    at = START + timedelta(seconds=offset)
    return CaseEvidenceVerification(
        public_id=str(uuid4()),
        case_id=base.case_id,
        snapshot_sync_id=base.snapshot_sync_id,
        source_sync_id=base.source_sync_id,
        source_transaction_id=base.source_transaction_id,
        activity_public_id=base.activity_public_id,
        activity_semantic_fingerprint=base.activity_semantic_fingerprint,
        policy=base.policy,
        state="cancelled",
        stage="terminal",
        progress_current=0,
        status_version=2,
        highest_evidence_level="normalized",
        provider=base.provider,
        network=base.network,
        wallet_account_canonical=base.wallet_account_canonical,
        transaction_hash=base.transaction_hash,
        transaction_logical_time=base.transaction_logical_time,
        idempotency_key=str(uuid4()),
        request_fingerprint=base.request_fingerprint,
        attempt_count=0,
        max_attempts=4,
        next_attempt_at=None,
        cancel_requested_at=at,
        checkpoint_json=json.dumps({"version": "case_evidence_job_v1", "phase": "cancelled", "retryable": False}),
        message_safe="Evidence verification was cancelled.",
        created_at=at,
        updated_at=at,
        completed_at=at,
    )


def test_catalog_over_fifty_returns_true_totals_with_one_activity_build(
    evidence_api,
    monkeypatch,
):
    seeded = _seed_live_transaction(evidence_api)
    created = _post_verification(evidence_api, seeded)
    assert created.status_code == 202
    cancelled = evidence_api.client.post(
        f"/api/v1/cases/{seeded.case_id}/evidence/verifications/"
        f"{created.json()['public_id']}/cancel"
    )
    assert cancelled.status_code == 200
    with evidence_api.sessions() as session:
        base = session.scalar(select(CaseEvidenceVerification))
        hidden_id = base.id
        session.add_all(_terminal_clone(base, offset=index + 1) for index in range(50))
        session.commit()
    with evidence_api.engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
        connection.exec_driver_sql(
            "UPDATE wallet_case_evidence_verifications "
            "SET highest_evidence_level='chain_inclusion_proven' WHERE id=?",
            (hidden_id,),
        )
        connection.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")

    original = WalletCaseActivityService.resolve_verifiable_transaction_revision
    calls = 0

    def counted(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        WalletCaseActivityService,
        "resolve_verifiable_transaction_revision",
        counted,
    )
    response = evidence_api.client.get(
        f"/api/v1/cases/{seeded.case_id}/evidence",
        params={"snapshot": seeded.snapshot_id},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["aggregate"]["total"] == 51
    assert body["aggregate"]["returned_count"] == 50
    assert body["aggregate"]["counts_scope"] == "returned_revalidated"
    assert body["aggregate"]["normalized"] == 50
    assert body["aggregate"]["chain_inclusion_proven"] == 0
    assert body["readiness"]["highest_evidence_level"] == "normalized"
    assert len(body["verifications"]) == 50
    assert body["truncated"] is True
    assert "catalog_history_not_revalidated" in {
        item["code"] for item in body["limitations"]
    }
    assert calls == 1


def _contract_response(state: str) -> dict:
    now = "2026-08-11T12:00:00Z"
    step_levels = (
        "normalized",
        "locally_verified",
        "chain_inclusion_proven",
        "chain_inclusion_proven",
    )
    progress = {
        "queued": 0,
        "retry": 2,
        "partial": 2,
        "partial3": 3,
        "succeeded": 4,
    }[state]
    steps = []
    for index, (code, level) in enumerate(
        zip(
            ("trace_capture", "boc_verification", "block_inclusion", "native_ledger"),
            step_levels,
        )
    ):
        complete = index < progress
        steps.append({
            "code": code,
            "state": "succeeded" if complete else "pending",
            "evidence_level": level if complete else None,
            "evidence_digest_sha256": f"{index + 1:064x}" if complete else None,
            "completed_at": now if complete else None,
        })
    retry = None
    public_state = state
    stage = "terminal" if state in {"partial", "partial3", "succeeded"} else "queued"
    started = None
    completed = now if stage == "terminal" else None
    if state == "retry":
        public_state = "queued"
        stage = "retry_wait"
        started = now
        retry = {
            "attempt": 1,
            "max_attempts": 4,
            "retry_at": "2026-08-11T12:01:00Z",
            "reason_code": "provider_timeout",
            "message_safe": "Provider retry is queued.",
        }
    elif stage == "terminal":
        started = now
    result = None
    limitations = [{"code": "selected_evidence_only", "message": "Selected transaction only."}]
    if state in {"partial", "partial3", "succeeded"}:
        public_state = "partial" if state == "partial3" else state
        result = {
            "verification_digest_sha256": "f" * 64,
            "evidence_digests": {
                item["code"]: item["evidence_digest_sha256"] for item in steps
            },
            "inclusion_provenance": None,
            "native_ledger": None,
        }
    if state in {"partial", "partial3"}:
        limitations.insert(0, {"code": "verification_partial", "message": "Proof stopped after local verification."})
    if progress >= 3:
        checkpoint = trusted_checkpoint_document("ton-mainnet")
        result["inclusion_provenance"] = {
            "contract_version": "ton_transaction_inclusion_v2",
            "network": "ton-mainnet",
            "verifier_policy_id": CURRENT_VERIFIER_POLICY_ID,
            "trust_level": 0,
            "trusted_checkpoint": {
                **checkpoint,
                "shard": str(checkpoint["shard"]),
            },
            "canonical_block_chain_verified_at_capture": True,
            "checkpoint_to_observed_head_transcript_persisted": False,
        }
    if state == "succeeded":
        result["native_ledger"] = {
            "evidence_digest_sha256": steps[3]["evidence_digest_sha256"],
            "activity_count": 1,
            "incoming_nanoton": "1",
            "outgoing_nanoton": "0",
            "self_nanoton": "0",
            "native_ton_only": True,
            "selected_evidence_only": True,
            "is_authoritative_activity_ledger": False,
            "establishes_complete_wallet_history": False,
            "eligible_for_cost_basis": False,
            "used_by_pnl": False,
            "message": "Selected native TON evidence only.",
        }
    inclusion_provenance = (
        None
        if progress < 3
        else deepcopy(result["inclusion_provenance"])
    )
    return {
        "case_public_id": str(uuid4()),
        "public_id": str(uuid4()),
        "snapshot_public_id": str(uuid4()),
        "activity_public_id": "act_" + "ab" * 32,
        "policy": "transaction_inclusion_v1",
        "state": public_state,
        "stage": stage,
        "status_version": 2 if state != "queued" else 1,
        "progress": {"current": progress, "total": 4},
        "cancel_requested": False,
        "highest_evidence_level": (
            "chain_inclusion_proven" if progress >= 3 else "locally_verified" if progress == 2 else "normalized"
        ),
        "provenance": {
            "data_origin": "provider_observed",
            "provider": "tonapi",
            "identity_assurance": "network_scoped",
            "source_sync_public_id": str(uuid4()),
            "transaction": {
                "network": "ton-mainnet",
                "wallet_account_canonical": "0:" + "11" * 32,
                "hash": "aa" * 32,
                "logical_time": "100",
            },
        },
        "inclusion_provenance": inclusion_provenance,
        "steps": steps,
        "retry": retry,
        "error": None,
        "result": result,
        "limitations": limitations,
        "message": "Evidence state is available.",
        "created_at": now,
        "updated_at": now,
        "started_at": started,
        "completed_at": completed,
    }


@pytest.mark.parametrize(
    "state", ("queued", "retry", "partial", "partial3", "succeeded")
)
def test_route_response_model_accepts_every_public_progress_shape(
    evidence_api,
    monkeypatch,
    state,
):
    payload = _contract_response(state)
    monkeypatch.setattr(
        "routers.wallet_case_evidence.CaseEvidenceService.get_verification",
        lambda _self, _case, _verification: deepcopy(payload),
    )
    response = evidence_api.client.get(
        f"/api/v1/cases/{payload['case_public_id']}/evidence/verifications/"
        f"{payload['public_id']}"
    )
    assert response.status_code == 200, response.text
    assert response.json() == payload


def test_response_model_rejects_non_prefix_failed_and_lifecycle_drift():
    failed = _contract_response("partial")
    failed["state"] = "failed"
    failed["result"] = None
    failed["error"] = {
        "code": "evidence_failed",
        "message_safe": "Evidence failed.",
        "retryable": False,
    }
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(failed)

    retry = _contract_response("retry")
    retry["retry"] = None
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(retry)

    queued = _contract_response("queued")
    queued["started_at"] = queued["created_at"]
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(queued)

    queued_work_stage = _contract_response("queued")
    queued_work_stage["stage"] = "validating"
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(queued_work_stage)

    running_queue_stage = _contract_response("retry")
    running_queue_stage["state"] = "running"
    running_queue_stage["stage"] = "queued"
    running_queue_stage["retry"] = None
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(running_queue_stage)

    bad_account = _contract_response("queued")
    bad_account["provenance"]["transaction"]["wallet_account_canonical"] = (
        "1:" + "AA" * 32
    )
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(bad_account)

    bad_lt = _contract_response("queued")
    bad_lt["provenance"]["transaction"]["logical_time"] = "18446744073709551616"
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(bad_lt)

    wrong_step_level = _contract_response("partial")
    wrong_step_level["steps"][0]["evidence_level"] = "chain_inclusion_proven"
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(wrong_step_level)

    wrong_ledger_digest = _contract_response("succeeded")
    wrong_ledger_digest["result"]["native_ledger"][
        "evidence_digest_sha256"
    ] = "e" * 64
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(wrong_ledger_digest)

    provenance_before_inclusion = _contract_response("partial")
    provenance_before_inclusion["result"]["inclusion_provenance"] = deepcopy(
        _contract_response("partial3")["result"]["inclusion_provenance"]
    )
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(provenance_before_inclusion)

    missing_provenance = _contract_response("partial3")
    missing_provenance["result"]["inclusion_provenance"] = None
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(missing_provenance)

    for mutate in (
        lambda value: value.update({"verifier_policy_id": "forged_policy"}),
        lambda value: value.update({"trust_level": 1}),
        lambda value: value.update(
            {"checkpoint_to_observed_head_transcript_persisted": True}
        ),
        lambda value: value["trusted_checkpoint"].update(
            {"root_hash": "0" * 64}
        ),
    ):
        forged_provenance = _contract_response("partial3")
        mutate(forged_provenance["result"]["inclusion_provenance"])
        with pytest.raises(ValidationError):
            CaseEvidenceVerificationResponse.model_validate(forged_provenance)

    for state in ("partial", "succeeded"):
        cancelled_truth_drift = _contract_response(state)
        cancelled_truth_drift["cancel_requested"] = True
        with pytest.raises(ValidationError):
            CaseEvidenceVerificationResponse.model_validate(cancelled_truth_drift)

    queued_with_cancel = _contract_response("queued")
    queued_with_cancel["cancel_requested"] = True
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(queued_with_cancel)

    failed_with_cancel = _contract_response("queued")
    failed_with_cancel.update({
        "state": "failed",
        "stage": "terminal",
        "cancel_requested": True,
        "completed_at": failed_with_cancel["updated_at"],
        "error": {
            "code": "evidence_failed",
            "message_safe": "Evidence failed.",
            "retryable": False,
        },
    })
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(failed_with_cancel)

    cancelled_without_request = _contract_response("queued")
    cancelled_without_request["state"] = "cancelled"
    cancelled_without_request["stage"] = "terminal"
    cancelled_without_request["completed_at"] = cancelled_without_request[
        "updated_at"
    ]
    with pytest.raises(ValidationError):
        CaseEvidenceVerificationResponse.model_validate(cancelled_without_request)


@pytest.mark.parametrize(
    "tamper",
    ("foreign_case", "foreign_snapshot", "wrong_highest", "demo_ready"),
)
def test_catalog_route_response_model_rejects_cross_scope_and_readiness_drift(
    evidence_api,
    monkeypatch,
    tamper,
):
    seeded = _seed_live_transaction(evidence_api)
    assert _post_verification(evidence_api, seeded).status_code == 202
    path = f"/api/v1/cases/{seeded.case_id}/evidence?snapshot={seeded.snapshot_id}"
    valid = evidence_api.client.get(path)
    assert valid.status_code == 200, valid.text
    payload = valid.json()
    if tamper == "foreign_case":
        payload["verifications"][0]["case_public_id"] = str(uuid4())
    elif tamper == "foreign_snapshot":
        payload["verifications"][0]["snapshot_public_id"] = str(uuid4())
    elif tamper == "wrong_highest":
        payload["readiness"]["highest_evidence_level"] = "chain_inclusion_proven"
    else:
        payload["snapshot"]["data_mode"] = "mock"
        payload["readiness"]["transaction_verification_available"] = True
    monkeypatch.setattr(
        "routers.wallet_case_evidence.CaseEvidenceService.catalog",
        lambda *_args, **_kwargs: deepcopy(payload),
    )
    with pytest.raises(ResponseValidationError):
        evidence_api.client.get(path)


@pytest.fixture
def worker_context(tmp_path, monkeypatch):
    _clear_selection_cache_for_tests()
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setenv("TONAPI_API_KEY", "worker-test-key")
    monkeypatch.setenv("TON_LITECLIENT_TRUST_LEVEL", "0")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'worker-evidence.sqlite3'}",
        connect_args={"check_same_thread": False},
        poolclass=QueuePool,
        pool_size=4,
        max_overflow=0,
    )
    assert run_database_migrations(engine).revision_after == "20260827_0026"
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    context = SimpleNamespace(
        engine=engine,
        sessions=sessions,
        monkeypatch=monkeypatch,
    )
    try:
        yield context
    finally:
        engine.dispose()
        _clear_selection_cache_for_tests()


def _seed_worker_verification(context):
    with context.sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        run.transactions.append(
            _transaction(
                run,
                tx_hash="c1" * 32,
                logical_time="301",
                timestamp=START + timedelta(hours=1),
            )
        )
        case_id = wallet_case.public_id
        snapshot_id = snapshot.public_id
        session.commit()
    with context.sessions() as session:
        revision = WalletCaseActivityService(session).resolve_verifiable_transaction_revision(
            case_id,
            snapshot_public_id=snapshot_id,
        )
        activity_id = next(iter(revision.verifiable_transactions))
        response, replayed = CaseEvidenceService(session).enqueue(
            case_id,
            CaseEvidenceVerificationRequest(
                snapshot_public_id=snapshot_id,
                activity_public_id=activity_id,
                policy="transaction_inclusion_v1",
            ),
            str(uuid4()),
            runner_available=True,
        )
        assert replayed is False
    return SimpleNamespace(
        case_id=case_id,
        snapshot_id=snapshot_id,
        activity_id=activity_id,
        verification_id=response["public_id"],
    )


def _set_prefix(context, verification_id: str, progress: int) -> None:
    at = START + timedelta(hours=4)
    with context.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == verification_id
            )
        )
        if progress >= 1:
            job.trace_capture_id = 101
            job.trace_digest_sha256 = "1" * 64
            job.trace_completed_at = at
        if progress >= 2:
            job.boc_verification_id = 102
            job.boc_digest_sha256 = "2" * 64
            job.boc_completed_at = at
        if progress >= 3:
            job.inclusion_catalog_digest_sha256 = "3" * 64
            job.inclusion_completed_at = at
        if progress >= 4:
            job.native_ledger_id = 104
            job.native_ledger_digest_sha256 = "4" * 64
            job.native_ledger_completed_at = at
        job.progress_current = progress
        job.highest_evidence_level = (
            "chain_inclusion_proven"
            if progress >= 3
            else "locally_verified"
            if progress == 2
            else "normalized"
        )
        session.commit()


def _fake_artifacts(job, _session):
    return {
        "trace_capture": (
            None
            if job.trace_capture_id is None
            else {
                "capture_id": str(job.trace_capture_id),
                "evidence_digest_sha256": job.trace_digest_sha256,
            }
        ),
        "boc_verification": (
            None
            if job.boc_verification_id is None
            else {
                "verification_id": str(job.boc_verification_id),
                "evidence_digest_sha256": job.boc_digest_sha256,
            }
        ),
        "block_inclusion": (
            None
            if job.inclusion_catalog_digest_sha256 is None
            else _current_inclusion_catalog(
                network=job.network,
                digest=job.inclusion_catalog_digest_sha256,
            )
        ),
        "native_ledger": (
            None
            if job.native_ledger_id is None
            else {
                "ledger_id": str(job.native_ledger_id),
                "evidence_digest_sha256": job.native_ledger_digest_sha256,
                "activity_count": 1,
                "incoming_nanoton": "1",
                "outgoing_nanoton": "0",
                "self_nanoton": "0",
            }
        ),
    }


def _patch_fake_artifacts(monkeypatch) -> None:
    monkeypatch.setattr(
        "services.case_evidence_jobs._revalidated_artifacts",
        _fake_artifacts,
    )
    monkeypatch.setattr(
        "services.wallet_case_evidence._revalidated_artifacts",
        _fake_artifacts,
    )


def _successful_operations(calls: list[str] | None = None):
    calls = calls if calls is not None else []

    def capture(*_args):
        calls.append("trace")
        return {"capture_id": "101", "evidence_digest_sha256": "1" * 64}

    def boc(*_args):
        calls.append("boc")
        return {"verification_id": "102", "evidence_digest_sha256": "2" * 64}

    def inclusion(*_args):
        calls.append("inclusion")
        return _current_inclusion_catalog()

    def ledger(*_args):
        calls.append("ledger")
        return {"ledger_id": "104", "evidence_digest_sha256": "4" * 64}

    return calls, capture, boc, inclusion, ledger


def _current_inclusion_catalog(
    *,
    network: str = "ton-mainnet",
    trust_level: int = 0,
    digest: str = "3" * 64,
) -> dict:
    checkpoint = trusted_checkpoint_document(network)
    public_checkpoint = {**checkpoint, "shard": str(checkpoint["shard"])}
    return {
        "contract_version": "ton_transaction_inclusion_v2",
        "verifier_policy_id": CURRENT_VERIFIER_POLICY_ID,
        "trusted_checkpoint": public_checkpoint,
        "catalog_digest_sha256": digest,
        "all_transaction_bocs_included_in_blocks": True,
        "proofs": [{
            "contract_version": "ton_transaction_inclusion_v2",
            "evidence_contract_version": "ton_transaction_inclusion_v2",
            "network": network,
            "verifier_policy_id": CURRENT_VERIFIER_POLICY_ID,
            "trusted_checkpoint": public_checkpoint,
            "trust_level": trust_level,
            "block_merkle_proof_verified": True,
            "canonical_block_chain_verified_at_capture": trust_level == 0,
            "checkpoint_to_observed_head_transcript_persisted": False,
            "provider_free_revalidated": True,
        }],
    }


def _worker(context, *, calls=None, **overrides):
    calls, capture, boc, inclusion, ledger = _successful_operations(calls)
    return CaseEvidenceWorker(
        context.sessions,
        settings_factory=get_settings,
        capture=overrides.get("capture", capture),
        verify_bocs=overrides.get("verify_bocs", boc),
        prove_inclusion=overrides.get("prove_inclusion", inclusion),
        build_ledger=overrides.get("build_ledger", ledger),
        lease_seconds=60,
        heartbeat_seconds=2,
        retry_base_seconds=1,
        retry_cap_seconds=2,
    ), calls


def _job(context, verification_id: str) -> CaseEvidenceVerification:
    with context.sessions() as session:
        value = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == verification_id
            )
        )
        session.expunge(value)
        return value


def _make_retry_due(context, verification_id: str) -> None:
    with context.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == verification_id
            )
        )
        job.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()


def test_worker_resumes_bound_prefix_and_succeeds_idempotently(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 1)
    _patch_fake_artifacts(monkeypatch)
    worker, calls = _worker(worker_context)

    assert worker.run_once() is True

    job = _job(worker_context, seeded.verification_id)
    assert job.state == "succeeded"
    assert job.progress_current == 4
    assert calls == ["boc", "inclusion", "ledger"]


def test_partial_inclusion_provenance_is_public_and_digest_bound_fail_closed(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    verification_id = seeded.verification_id
    with worker_context.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == verification_id
            )
        )
        job.attempt_count = job.max_attempts - 1
        session.commit()
    _patch_fake_artifacts(monkeypatch)

    def ledger_failure(*_args):
        raise WalletNativeActivityLedgerFailure("bounded ledger failure")

    worker, _calls = _worker(worker_context, build_ledger=ledger_failure)
    assert worker.run_once() is True

    path = (
        f"/api/v1/cases/{seeded.case_id}/evidence/verifications/"
        f"{verification_id}"
    )
    with worker_context.sessions() as session:
        body = CaseEvidenceService(session).get_verification(
            seeded.case_id,
            verification_id,
        )
    CaseEvidenceVerificationResponse.model_validate(body)
    assert body["state"] == "partial", {
        "state": body["state"],
        "error": body["error"],
        "progress": body["progress"],
        "limitations": body["limitations"],
    }
    assert body["progress"] == {"current": 3, "total": 4}
    assert body["result"]["native_ledger"] is None
    checkpoint = trusted_checkpoint_document("ton-mainnet")
    expected_provenance = {
        "contract_version": "ton_transaction_inclusion_v2",
        "network": "ton-mainnet",
        "verifier_policy_id": CURRENT_VERIFIER_POLICY_ID,
        "trust_level": 0,
        "trusted_checkpoint": {
            **checkpoint,
            "shard": str(checkpoint["shard"]),
        },
        "canonical_block_chain_verified_at_capture": True,
        "checkpoint_to_observed_head_transcript_persisted": False,
    }
    assert body["inclusion_provenance"] == expected_provenance
    assert body["result"]["inclusion_provenance"] == expected_provenance
    serialized = json.dumps(body, sort_keys=True)
    for forbidden in (
        "transaction_boc_hex",
        "block_proof_boc_hex",
        "lease_token",
        "source_run_id",
        "inclusion_proof_id",
    ):
        assert forbidden not in serialized

    tamper = {"kind": "policy"}

    def forged_artifacts(job, session):
        artifacts = _fake_artifacts(job, session)
        catalog = deepcopy(artifacts["block_inclusion"])
        if tamper["kind"] == "policy":
            catalog["verifier_policy_id"] = "forged_policy"
        else:
            catalog["trusted_checkpoint"]["root_hash"] = "0" * 64
        artifacts["block_inclusion"] = catalog
        return artifacts

    monkeypatch.setattr(
        "services.wallet_case_evidence._revalidated_artifacts",
        forged_artifacts,
    )

    def override_session():
        with worker_context.sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.state.wallet_case_evidence_runner = ManualEvidenceRunner()
    client = TestClient(app)
    try:
        for kind in ("policy", "checkpoint"):
            tamper["kind"] = kind
            rejected = client.get(path)
            assert rejected.status_code == 409
            assert rejected.json()["detail"]["code"] == "evidence_stored_conflict"
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.state.wallet_case_evidence_runner = None


@pytest.mark.parametrize(
    ("variant", "expected_state", "expected_stage"),
    (
        ("running", "running", "building_native_ledger"),
        ("retry", "queued", "retry_wait"),
        ("cancelled", "cancelled", "terminal"),
    ),
)
def test_progress_three_always_publishes_revalidated_top_level_provenance(
    worker_context,
    monkeypatch,
    variant,
    expected_state,
    expected_stage,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 3)
    now = datetime.now(timezone.utc)
    with worker_context.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == seeded.verification_id
            )
        )
        job.started_at = now
        job.updated_at = now
        if variant == "running":
            job.state = "running"
            job.stage = "building_native_ledger"
            job.next_attempt_at = None
            job.lease_token = "progress-three-lease"
            job.lease_expires_at = now + timedelta(minutes=1)
            job.heartbeat_at = now
        elif variant == "retry":
            job.state = "queued"
            job.stage = "retry_wait"
            job.attempt_count = 1
            job.next_attempt_at = now + timedelta(minutes=1)
            job.error_code = "evidence_storage_unavailable"
            job.error_detail_safe = "Evidence storage is temporarily unavailable."
        else:
            job.state = "cancelled"
            job.stage = "terminal"
            job.next_attempt_at = None
            job.cancel_requested_at = now
            job.completed_at = now
        session.commit()
    _patch_fake_artifacts(monkeypatch)

    def override_session():
        with worker_context.sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.state.wallet_case_evidence_runner = ManualEvidenceRunner()
    client = TestClient(app)
    try:
        response = client.get(
            f"/api/v1/cases/{seeded.case_id}/evidence/verifications/"
            f"{seeded.verification_id}"
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert (body["state"], body["stage"]) == (
            expected_state,
            expected_stage,
        )
        assert body["progress"] == {"current": 3, "total": 4}
        assert body["result"] is None
        assert body["inclusion_provenance"] == _contract_response("partial3")[
            "inclusion_provenance"
        ]
        serialized = json.dumps(body, sort_keys=True)
        assert "transaction_boc_hex" not in serialized
        assert "block_proof_boc_hex" not in serialized
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.state.wallet_case_evidence_runner = None


def test_runtime_drift_retries_with_prefix_then_restores_and_resumes(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 2)
    _patch_fake_artifacts(monkeypatch)
    worker, calls = _worker(worker_context)
    monkeypatch.setenv("DATA_MODE", "mock")

    assert worker.run_once() is True
    retry = _job(worker_context, seeded.verification_id)
    assert (retry.state, retry.stage, retry.progress_current) == ("queued", "retry_wait", 2)
    assert retry.error_code == "evidence_runtime_unavailable"

    monkeypatch.setenv("DATA_MODE", "real")
    _make_retry_due(worker_context, seeded.verification_id)
    assert worker.run_once() is True
    completed = _job(worker_context, seeded.verification_id)
    assert completed.state == "succeeded"
    assert calls == ["inclusion", "ledger"]


def test_canonical_selection_conflict_clears_public_bindings_and_fails(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 1)
    _patch_fake_artifacts(monkeypatch)
    with worker_context.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == seeded.verification_id
            )
        )
        job.activity_semantic_fingerprint = "0" * 64
        session.commit()
    worker, _calls = _worker(worker_context)

    assert worker.run_once() is True

    failed = _job(worker_context, seeded.verification_id)
    assert failed.state == "failed"
    assert failed.error_code == "evidence_selection_conflict"
    assert failed.progress_current == 0
    assert failed.result_digest_sha256 is None
    assert failed.trace_capture_id is None


@pytest.mark.parametrize(
    ("code", "expected_state"),
    (
        ("provider_protocol_error", "failed"),
        ("http_401", "failed"),
        ("http_404", "failed"),
        ("http_408", "queued"),
        ("http_425", "queued"),
        ("http_429", "queued"),
        ("http_503", "queued"),
    ),
)
def test_worker_retry_taxonomy_distinguishes_transport_from_protocol(
    worker_context,
    monkeypatch,
    code,
    expected_state,
):
    seeded = _seed_worker_verification(worker_context)
    _patch_fake_artifacts(monkeypatch)

    def fail(*_args):
        raise WalletTraceEvidenceProviderFailure("secret provider detail", code=code)

    worker, _calls = _worker(worker_context, capture=fail)
    assert worker.run_once() is True
    job = _job(worker_context, seeded.verification_id)
    assert job.state == expected_state
    assert job.attempt_count == 1
    assert "secret provider detail" not in (job.error_detail_safe or "")
    if expected_state == "queued":
        assert job.stage == "retry_wait"
    else:
        assert job.stage == "terminal"


@pytest.mark.parametrize(
    ("code", "retryable", "expected_state"),
    (
        ("liteserver_capture_timeout", True, "queued"),
        ("liteserver_config_timeout", True, "queued"),
        ("http_429", True, "queued"),
        ("http_503", True, "queued"),
        ("liteserver_network_mismatch", False, "partial"),
        ("liteserver_proof_invalid", False, "partial"),
        ("liteserver_config_invalid", False, "partial"),
        ("liteserver_ipc_invalid", False, "partial"),
    ),
)
def test_inclusion_failure_preserves_retry_truth_and_bounded_budget(
    worker_context,
    monkeypatch,
    code,
    retryable,
    expected_state,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 2)
    _patch_fake_artifacts(monkeypatch)

    def fail(*_args):
        raise WalletTransactionInclusionProofFailure(
            "secret liteserver path and payload",
            code=code,
            retryable=retryable,
        )

    worker, _calls = _worker(worker_context, prove_inclusion=fail)
    assert worker.run_once() is True
    job = _job(worker_context, seeded.verification_id)
    assert job.state == expected_state
    assert job.error_code == code
    assert "secret" not in (job.error_detail_safe or "")
    if retryable:
        assert job.stage == "retry_wait"
        assert job.attempt_count == 1
    else:
        assert job.stage == "terminal"
        assert job.progress_current == 2


def test_cancel_during_cancellable_inclusion_stops_before_binding(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 2)
    _patch_fake_artifacts(monkeypatch)
    entered = Event()

    def blocked(*_args, cancellation_event):
        entered.set()
        assert cancellation_event.wait(3)
        raise WalletTransactionInclusionProofFailure(
            "cancelled child",
            code="liteserver_capture_cancelled",
            retryable=True,
        )

    worker, _calls = _worker(worker_context, prove_inclusion=blocked)
    worker.heartbeat_seconds = 0.05
    thread = Thread(target=worker.run_once, daemon=True)
    thread.start()
    assert entered.wait(2)
    with worker_context.sessions() as session:
        response, accepted = CaseEvidenceService(session).cancel(
            seeded.case_id,
            seeded.verification_id,
        )
    assert accepted is True
    assert response["cancel_requested"] is True
    thread.join(3)
    assert not thread.is_alive()
    cancelled = _job(worker_context, seeded.verification_id)
    assert cancelled.state == "cancelled"
    assert cancelled.progress_current == 2
    assert cancelled.inclusion_catalog_digest_sha256 is None
    assert cancelled.error_code is None


def test_cancel_waits_for_noncancellable_stage_boundary_before_terminalizing(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 2)
    _patch_fake_artifacts(monkeypatch)
    entered = Event()
    release = Event()

    def blocked(*_args):
        entered.set()
        assert release.wait(3)
        return _current_inclusion_catalog()

    worker, _calls = _worker(worker_context, prove_inclusion=blocked)
    worker.heartbeat_seconds = 0.05
    thread = Thread(target=worker.run_once, daemon=True)
    thread.start()
    assert entered.wait(2)
    with worker_context.sessions() as session:
        _response, accepted = CaseEvidenceService(session).cancel(
            seeded.case_id,
            seeded.verification_id,
        )
    assert accepted is True
    Event().wait(0.2)
    active = _job(worker_context, seeded.verification_id)
    assert active.state == "running"
    assert active.progress_current == 2
    assert active.inclusion_catalog_digest_sha256 is None
    release.set()
    thread.join(3)
    assert not thread.is_alive()
    cancelled = _job(worker_context, seeded.verification_id)
    assert cancelled.state == "cancelled"
    assert cancelled.progress_current == 2
    assert cancelled.inclusion_catalog_digest_sha256 is None


def test_worker_stop_cancels_isolated_stage_without_publishing_failure(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 2)
    _patch_fake_artifacts(monkeypatch)
    entered = Event()

    def blocked(*_args, cancellation_event):
        entered.set()
        assert cancellation_event.wait(3)
        raise WalletTransactionInclusionProofFailure(
            "shutdown child",
            code="liteserver_capture_cancelled",
            retryable=True,
        )

    worker, _calls = _worker(worker_context, prove_inclusion=blocked)
    worker.heartbeat_seconds = 0.05
    thread = Thread(target=worker.run_once, daemon=True)
    thread.start()
    assert entered.wait(2)
    worker.request_stop()
    thread.join(3)
    assert not thread.is_alive()
    durable = _job(worker_context, seeded.verification_id)
    assert durable.state == "running"
    assert durable.progress_current == 2
    assert durable.inclusion_catalog_digest_sha256 is None
    assert durable.error_code is None


@pytest.mark.parametrize("control_failure", ("heartbeat", "cancelled_read"))
def test_control_sql_failure_stops_operation_before_retry_and_resumes(
    worker_context,
    monkeypatch,
    control_failure,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 2)
    _patch_fake_artifacts(monkeypatch)
    entered = Event()
    stopped = Event()
    operation_calls = 0

    def inclusion(*_args, cancellation_event):
        nonlocal operation_calls
        operation_calls += 1
        if operation_calls == 1:
            entered.set()
            assert cancellation_event.wait(3)
            stopped.set()
            raise WalletTransactionInclusionProofFailure(
                "isolated child cancelled after storage control failure",
                code="liteserver_capture_cancelled",
                retryable=True,
            )
        return _current_inclusion_catalog()

    worker, _calls = _worker(worker_context, prove_inclusion=inclusion)
    worker.heartbeat_seconds = 0.05
    original_heartbeat = worker._heartbeat
    original_cancelled = worker._cancelled
    if control_failure == "heartbeat":
        monkeypatch.setattr(
            worker,
            "_heartbeat",
            lambda _claimed: (_ for _ in ()).throw(
                SQLAlchemyError("secret heartbeat storage failure")
            ),
        )
    else:
        def cancelled_read(_claimed):
            if entered.is_set():
                raise SQLAlchemyError("secret cancel storage failure")
            return False

        monkeypatch.setattr(worker, "_cancelled", cancelled_read)

    assert worker.run_once() is True
    assert entered.is_set()
    assert stopped.is_set()
    assert operation_calls == 1
    with worker._lock:
        assert worker._active_cancellations == set()
    assert not any(
        thread.is_alive() and thread.name.startswith("case-evidence-")
        for thread in __import__("threading").enumerate()
    )
    retry = _job(worker_context, seeded.verification_id)
    assert retry.state == "queued"
    assert retry.stage == "retry_wait"
    assert retry.error_code == "evidence_storage_unavailable"

    monkeypatch.setattr(worker, "_heartbeat", original_heartbeat)
    monkeypatch.setattr(worker, "_cancelled", original_cancelled)
    _make_retry_due(worker_context, seeded.verification_id)
    assert worker.run_once() is True
    resumed = _job(worker_context, seeded.verification_id)
    assert resumed.state == "succeeded"
    assert operation_calls == 2


def test_trust_level_one_inclusion_stops_at_locally_verified_partial(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 2)
    _patch_fake_artifacts(monkeypatch)

    def trust_one(*_args):
        return _current_inclusion_catalog(trust_level=1)

    worker, calls = _worker(worker_context, prove_inclusion=trust_one)
    assert worker.run_once() is True
    partial = _job(worker_context, seeded.verification_id)
    assert partial.state == "partial"
    assert partial.progress_current == 2
    assert partial.highest_evidence_level == "locally_verified"
    assert partial.inclusion_catalog_digest_sha256 is None
    assert partial.error_code == "evidence_inclusion_trust_insufficient"
    assert calls == []


@pytest.mark.parametrize("progress", (0, 1, 2, 3))
def test_transient_control_or_stage_sql_error_is_safe_and_resumable(
    worker_context,
    monkeypatch,
    caplog,
    progress,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, progress)
    _patch_fake_artifacts(monkeypatch)
    secret = "secret-marker SELECT * FROM private_table"

    def fail(*_args):
        raise SQLAlchemyError(secret)

    overrides = ({"capture": fail}, {"verify_bocs": fail}, {"prove_inclusion": fail}, {"build_ledger": fail})[progress]
    worker, _calls = _worker(worker_context, **overrides)
    assert worker.run_once() is True
    retry = _job(worker_context, seeded.verification_id)
    assert (retry.state, retry.stage, retry.progress_current) == (
        "queued",
        "retry_wait",
        progress,
    )
    serialized = " ".join(
        value or ""
        for value in (
            retry.error_code,
            retry.error_detail_safe,
            retry.message_safe,
            retry.checkpoint_json,
            caplog.text,
        )
    )
    assert "secret-marker" not in serialized
    assert "private_table" not in serialized


def test_one_shot_control_plane_sql_failure_queues_then_resumes(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _set_prefix(worker_context, seeded.verification_id, 2)
    _patch_fake_artifacts(monkeypatch)
    worker, calls = _worker(worker_context)
    original = worker._has_binding
    raised = False

    def one_shot(*args, **kwargs):
        nonlocal raised
        if not raised:
            raised = True
            raise SQLAlchemyError("secret-marker control plane")
        return original(*args, **kwargs)

    monkeypatch.setattr(worker, "_has_binding", one_shot)
    assert worker.run_once() is True
    retry = _job(worker_context, seeded.verification_id)
    assert retry.state == "queued"
    assert retry.progress_current == 2
    assert "secret-marker" not in (retry.error_detail_safe or "")

    _make_retry_due(worker_context, seeded.verification_id)
    assert worker.run_once() is True
    assert _job(worker_context, seeded.verification_id).state == "succeeded"
    assert calls == ["inclusion", "ledger"]


def test_retry_publication_sql_failure_leaves_durable_lease_for_recovery(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _patch_fake_artifacts(monkeypatch)
    worker, _calls = _worker(worker_context)

    def control_failure(*_args, **_kwargs):
        raise SQLAlchemyError("secret-marker control")

    original_schedule = worker._schedule_retry
    schedule_calls = 0

    def one_shot_schedule(*args, **kwargs):
        nonlocal schedule_calls
        schedule_calls += 1
        if schedule_calls == 1:
            raise SQLAlchemyError("secret-marker retry publication")
        return original_schedule(*args, **kwargs)

    monkeypatch.setattr(worker, "_has_binding", control_failure)
    monkeypatch.setattr(worker, "_schedule_retry", one_shot_schedule)
    assert worker.run_once() is True
    running = _job(worker_context, seeded.verification_id)
    assert running.state == "running"
    assert running.lease_token is not None
    assert "secret-marker" not in (running.message_safe or "")

    with worker_context.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == seeded.verification_id
            )
        )
        job.lease_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        session.commit()
    assert worker.recover_expired() == 1
    recovered = _job(worker_context, seeded.verification_id)
    assert (recovered.state, recovered.stage) == ("queued", "retry_wait")


def test_exhausted_recovery_does_not_terminalize_a_concurrently_renewed_lease(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    worker, _calls = _worker(worker_context)
    claimed = worker.claim_next()
    assert claimed is not None
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with worker_context.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == seeded.verification_id
            )
        )
        job.attempt_count = job.max_attempts
        job.lease_expires_at = expired_at
        job.heartbeat_at = expired_at
        session.commit()

    original_finish = worker._finish_expired
    renewed_at = datetime.now(timezone.utc) + timedelta(minutes=2)
    interleaved = False

    def renew_before_finish(job_id, **kwargs):
        nonlocal interleaved
        interleaved = True
        with worker_context.sessions() as session:
            job = session.get(CaseEvidenceVerification, job_id)
            job.lease_expires_at = renewed_at
            job.heartbeat_at = datetime.now(timezone.utc)
            session.commit()
        return original_finish(job_id, **kwargs)

    monkeypatch.setattr(worker, "_finish_expired", renew_before_finish)

    assert worker.recover_expired() == 0
    assert interleaved is True
    running = _job(worker_context, seeded.verification_id)
    assert running.state == "running"
    assert running.lease_token == claimed.lease_token
    assert running.lease_expires_at.replace(tzinfo=timezone.utc) == renewed_at.replace(
        tzinfo=timezone.utc
    )


@pytest.mark.parametrize("terminal_path", ("failure", "success"))
def test_accepted_cancel_wins_terminal_publication_race(
    worker_context,
    monkeypatch,
    terminal_path,
):
    seeded = _seed_worker_verification(worker_context)
    _patch_fake_artifacts(monkeypatch)

    def request_cancel() -> None:
        with worker_context.sessions() as session:
            job = session.scalar(
                select(CaseEvidenceVerification).where(
                    CaseEvidenceVerification.public_id == seeded.verification_id
                )
            )
            job.cancel_requested_at = datetime.now(timezone.utc)
            job.updated_at = datetime.now(timezone.utc)
            session.commit()

    if terminal_path == "failure":
        def capture(*_args):
            request_cancel()
            raise WalletTraceEvidenceProviderFailure(
                "protocol mismatch",
                code="provider_protocol_error",
            )

        worker, _calls = _worker(worker_context, capture=capture)
    else:
        _set_prefix(worker_context, seeded.verification_id, 3)

        def ledger(*_args):
            request_cancel()
            return {"ledger_id": "104", "evidence_digest_sha256": "4" * 64}

        worker, _calls = _worker(worker_context, build_ledger=ledger)
        monkeypatch.setattr(worker, "_cancelled", lambda _claimed: False)

    assert worker.run_once() is True
    cancelled = _job(worker_context, seeded.verification_id)
    assert cancelled.state == "cancelled"
    assert cancelled.stage == "terminal"
    assert cancelled.result_digest_sha256 is None


def test_accepted_cancel_wins_selection_conflict_publication(
    worker_context,
    monkeypatch,
):
    seeded = _seed_worker_verification(worker_context)
    _patch_fake_artifacts(monkeypatch)
    worker, _calls = _worker(worker_context)

    def cancel_then_conflict(_claimed):
        with worker_context.sessions() as session:
            job = session.scalar(
                select(CaseEvidenceVerification).where(
                    CaseEvidenceVerification.public_id == seeded.verification_id
                )
            )
            job.cancel_requested_at = datetime.now(timezone.utc)
            session.commit()
        raise CaseEvidenceStoredConflict("selection changed")

    monkeypatch.setattr(worker, "_revalidate_selection", cancel_then_conflict)
    assert worker.run_once() is True
    cancelled = _job(worker_context, seeded.verification_id)
    assert cancelled.state == "cancelled"
    assert cancelled.error_code is None


def _canonical_inclusion_candidate(**kwargs):
    bocs = {ROOT_HASH: "00", CHILD_HASH: "01"}
    return [
        {
            **request,
            "block": {
                "workchain": 0,
                "shard": -9223372036854775808,
                "seqno": 100 + index,
                "root_hash": f"{index:064x}",
                "file_hash": f"{index + 10:064x}",
            },
            "masterchain_anchor": {
                "workchain": -1,
                "shard": -9223372036854775808,
                "seqno": 200,
                "root_hash": "aa" * 32,
                "file_hash": "bb" * 32,
            },
            "trusted_checkpoint": trusted_checkpoint_document(kwargs["network"]),
            "verifier_policy_id": CURRENT_VERIFIER_POLICY_ID,
            "transaction_boc_hex": bocs[request["transaction_hash"]],
            "block_proof_boc_hex": "cc",
            "trust_level": kwargs["trust_level"],
        }
        for index, request in enumerate(kwargs["requests"], start=1)
    ]


def _native_flow_source():
    return {
        "network": "ton-mainnet",
        "wallet_account_canonical": ROOT_ACCOUNT,
        "anchor": {
            "transaction_hash": ROOT_HASH,
            "logical_time": ROOT_LT,
            "account_canonical": ROOT_ACCOUNT,
            "matches_stored_transaction": True,
        },
        "message_evidence_digest_sha256": "ab" * 32,
        "incoming_nanoton": "0",
        "outgoing_nanoton": "2500000000",
        "self_nanoton": "0",
        "flows": [{
            "observation_identity": "cd" * 32,
            "transaction_hash": ROOT_HASH,
            "message_hash": ROOT_OUT_HASH,
            "direction": "outgoing",
            "counterparty_account_observed": "0:" + "44" * 32,
            "amount_nanoton": "2500000000",
            "created_logical_time": ROOT_LT,
            "unix_time": 1_717_236_000,
            "body_hash": "98" * 32,
            "opcode_hex": None,
            "bounce": True,
            "bounced": False,
        }],
    }


@pytest.fixture
def real_artifact_context(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setenv("TONAPI_API_KEY", "real-artifact-test-key")
    monkeypatch.setenv("TON_LITECLIENT_TRUST_LEVEL", "0")
    engine = create_database_engine(
        f"sqlite:///{tmp_path / 'real-case-evidence.sqlite3'}"
    )
    assert run_database_migrations(engine).revision_after == "20260827_0026"
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *_args, **_kwargs: ProviderResult.success(
            _normalized_finalized_candidate(), source="real"
        ),
    )

    def boc_candidate(*_args, **_kwargs):
        return ProviderResult.success(
            {
                "trace": _normalized_finalized_candidate(),
                "transaction_bocs": [
                    {
                        "preorder_index": 0,
                        "transaction_hash": ROOT_HASH,
                        "transaction_boc_hex": "00",
                        "transaction_boc_bytes": 1,
                    },
                    {
                        "preorder_index": 1,
                        "transaction_hash": CHILD_HASH,
                        "transaction_boc_hex": "01",
                        "transaction_boc_bytes": 1,
                    },
                ],
                "total_boc_bytes": 2,
            },
            source="real",
        )

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_boc_verification_candidate",
        boc_candidate,
    )
    monkeypatch.setattr(legacy_boc_service, "_derive_boc_evidence", _fake_boc_derived)
    monkeypatch.setattr(legacy_inclusion_service, "_verify_proof", lambda *_a, **_k: None)
    monkeypatch.setattr(
        legacy_ledger_service,
        "get_wallet_native_ton_flow_observations",
        lambda *_a, **_k: _native_flow_source(),
    )
    context = SimpleNamespace(engine=engine, sessions=sessions, monkeypatch=monkeypatch)
    try:
        yield context
    finally:
        engine.dispose()


def _seed_real_artifact_job(context):
    with context.sessions() as session:
        wallet_case = _case(session, account=ROOT_ACCOUNT)
        run, snapshot = _run_and_sync(session, wallet_case)
        run.transactions.append(
            _transaction(
                run,
                tx_hash=ROOT_HASH,
                logical_time=ROOT_LT,
                timestamp=START + timedelta(hours=1),
            )
        )
        case_id, snapshot_id, run_id = (
            wallet_case.public_id,
            snapshot.public_id,
            run.id,
        )
        session.commit()
    with context.sessions() as session:
        revision = WalletCaseActivityService(session).resolve_verifiable_transaction_revision(
            case_id,
            snapshot_public_id=snapshot_id,
        )
        activity_id = next(iter(revision.verifiable_transactions))
        response, _ = CaseEvidenceService(session).enqueue(
            case_id,
            CaseEvidenceVerificationRequest(
                snapshot_public_id=snapshot_id,
                activity_public_id=activity_id,
                policy="transaction_inclusion_v1",
            ),
            str(uuid4()),
            runner_available=True,
        )
    return SimpleNamespace(
        case_id=case_id,
        snapshot_id=snapshot_id,
        run_id=run_id,
        activity_id=activity_id,
        verification_id=response["public_id"],
    )


def _real_worker(
    context,
    *,
    capture=None,
    verify_bocs=None,
    prove_inclusion=None,
):
    def inclusion(run_id, transaction_hash, session):
        return create_wallet_transaction_inclusion_proofs(
            run_id,
            transaction_hash,
            session,
            live_verifier=_canonical_inclusion_candidate,
        )

    return CaseEvidenceWorker(
        context.sessions,
        settings_factory=get_settings,
        capture=capture or capture_persisted_wallet_transaction_trace_evidence,
        verify_bocs=verify_bocs or verify_wallet_transaction_trace_bocs,
        prove_inclusion=prove_inclusion or inclusion,
        build_ledger=build_wallet_native_activity_ledger,
        lease_seconds=60,
        heartbeat_seconds=2,
    )


def test_real_fk_on_legacy_artifact_chain_succeeds_and_revalidates(
    real_artifact_context,
):
    seeded = _seed_real_artifact_job(real_artifact_context)
    worker = _real_worker(real_artifact_context)

    assert worker.run_once() is True

    with real_artifact_context.sessions() as session:
        response = CaseEvidenceService(session).get_verification(
            seeded.case_id,
            seeded.verification_id,
        )
        CaseEvidenceVerificationResponse.model_validate(response)
        assert response["state"] == "succeeded"
        assert response["progress"] == {"current": 4, "total": 4}
        assert response["highest_evidence_level"] == "chain_inclusion_proven"
        assert response["result"]["native_ledger"]["activity_count"] == 1
        assert "transaction_boc_hex" not in json.dumps(response)


def test_real_legacy_trust_one_proofs_upgrade_immutably_and_evidence_succeeds(
    real_artifact_context,
):
    seeded = _seed_real_artifact_job(real_artifact_context)
    trust_calls: list[int] = []

    def live_verifier(**kwargs):
        trust_calls.append(kwargs["trust_level"])
        return _canonical_inclusion_candidate(**kwargs)

    with real_artifact_context.sessions() as session:
        capture_persisted_wallet_transaction_trace_evidence(
            seeded.run_id,
            ROOT_HASH,
            session,
        )
        verify_wallet_transaction_trace_bocs(
            seeded.run_id,
            ROOT_HASH,
            session,
        )
    real_artifact_context.monkeypatch.setenv("TON_LITECLIENT_TRUST_LEVEL", "1")
    with real_artifact_context.sessions() as session:
        legacy = create_wallet_transaction_inclusion_proofs(
            seeded.run_id,
            ROOT_HASH,
            session,
            live_verifier=live_verifier,
        )
    assert {item["trust_level"] for item in legacy["proofs"]} == {1}

    real_artifact_context.monkeypatch.setenv("TON_LITECLIENT_TRUST_LEVEL", "0")

    def upgrade_inclusion(run_id, transaction_hash, session):
        return create_wallet_transaction_inclusion_proofs(
            run_id,
            transaction_hash,
            session,
            live_verifier=live_verifier,
        )

    worker = _real_worker(
        real_artifact_context,
        prove_inclusion=upgrade_inclusion,
    )
    assert worker.run_once() is True
    assert trust_calls == [1, 0]
    assert _job(real_artifact_context, seeded.verification_id).state == "succeeded"
    with real_artifact_context.sessions() as session:
        assert session.scalar(
            select(func.count()).select_from(WalletTransactionInclusionProof)
        ) == 4
        assert list(
            session.scalars(
                select(WalletTransactionInclusionProof.trust_level)
                .order_by(WalletTransactionInclusionProof.trust_level)
            )
        ) == [0, 0, 1, 1]


def test_real_fk_on_resume_skips_bound_artifacts_and_tamper_fails_closed(
    real_artifact_context,
):
    seeded = _seed_real_artifact_job(real_artifact_context)
    at = datetime.now(timezone.utc)
    with real_artifact_context.sessions() as session:
        trace, _ = capture_persisted_wallet_transaction_trace_evidence(
            seeded.run_id,
            ROOT_HASH,
            session,
        )
        boc, _ = verify_wallet_transaction_trace_bocs(
            seeded.run_id,
            ROOT_HASH,
            session,
        )
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == seeded.verification_id
            )
        )
        job.trace_capture_id = int(trace["capture_id"])
        job.trace_digest_sha256 = trace["evidence_digest_sha256"]
        job.trace_completed_at = at
        job.boc_verification_id = int(boc["verification_id"])
        job.boc_digest_sha256 = boc["evidence_digest_sha256"]
        job.boc_completed_at = at
        job.progress_current = 2
        job.highest_evidence_level = "locally_verified"
        session.commit()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("resume repeated an already bound provider stage")

    worker = _real_worker(
        real_artifact_context,
        capture=forbidden,
        verify_bocs=forbidden,
    )
    assert worker.run_once() is True
    assert _job(real_artifact_context, seeded.verification_id).state == "succeeded"

    with real_artifact_context.sessions() as session:
        row = session.scalar(select(WalletTraceBocTransaction))
        row.transaction_cell_hash = "ff" * 32
        session.commit()
    with real_artifact_context.sessions() as session:
        with pytest.raises(CaseEvidenceStoredConflict):
            CaseEvidenceService(session).get_verification(
                seeded.case_id,
                seeded.verification_id,
            )


_LEGACY_ARTIFACT_CONFLICTS = (
    (
        "get_persisted_wallet_transaction_trace_evidence",
        WalletPersistedTraceEvidenceConflict,
    ),
    (
        "get_wallet_transaction_trace_boc_verification",
        WalletTraceBocVerificationConflict,
    ),
    (
        "get_wallet_transaction_inclusion_proofs",
        WalletTransactionInclusionProofConflict,
    ),
    (
        "get_wallet_native_activity_ledger",
        WalletNativeActivityLedgerConflict,
    ),
)


@pytest.mark.parametrize(("getter_name", "conflict_type"), _LEGACY_ARTIFACT_CONFLICTS)
def test_each_legacy_artifact_conflict_is_a_safe_route_409(
    real_artifact_context,
    monkeypatch,
    getter_name,
    conflict_type,
):
    seeded = _seed_real_artifact_job(real_artifact_context)
    assert _real_worker(real_artifact_context).run_once() is True

    def conflict(*_args, **_kwargs):
        raise conflict_type("secret-marker raw provider or SQL detail")

    monkeypatch.setattr(evidence_service_module, getter_name, conflict)

    def override_session():
        with real_artifact_context.sessions() as session:
            yield session

    app.dependency_overrides[get_session] = override_session
    app.state.wallet_case_evidence_runner = ManualEvidenceRunner()
    client = TestClient(app)
    try:
        response = client.get(
            f"/api/v1/cases/{seeded.case_id}/evidence/verifications/"
            f"{seeded.verification_id}"
        )
    finally:
        client.close()
        app.dependency_overrides.clear()
        app.state.wallet_case_evidence_runner = None

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["detail"]["code"] == "evidence_stored_conflict"
    assert "secret-marker" not in response.text


@pytest.mark.parametrize(("getter_name", "conflict_type"), _LEGACY_ARTIFACT_CONFLICTS)
def test_each_legacy_artifact_conflict_terminalizes_expired_job_once(
    real_artifact_context,
    monkeypatch,
    getter_name,
    conflict_type,
):
    seeded = _seed_real_artifact_job(real_artifact_context)
    worker = _real_worker(real_artifact_context)
    assert worker.run_once() is True
    expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    with real_artifact_context.sessions() as session:
        job = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == seeded.verification_id
            )
        )
        job.state = "running"
        job.stage = "finalizing"
        job.attempt_count = job.max_attempts
        job.next_attempt_at = None
        job.cancel_requested_at = None
        job.lease_token = "expired-artifact-conflict"
        job.lease_expires_at = expired_at
        job.heartbeat_at = expired_at
        job.completed_at = None
        job.result_digest_sha256 = None
        job.error_code = None
        job.error_detail_safe = None
        job.updated_at = expired_at
        job.status_version += 1
        session.commit()

    def conflict(*_args, **_kwargs):
        raise conflict_type("secret-marker raw provider or SQL detail")

    monkeypatch.setattr(evidence_service_module, getter_name, conflict)
    assert worker.recover_expired() == 1
    failed = _job(real_artifact_context, seeded.verification_id)
    assert failed.state == "failed"
    assert failed.stage == "terminal"
    assert failed.progress_current == 0
    assert failed.error_code == "evidence_artifact_conflict"
    assert failed.result_digest_sha256 is None
    assert failed.trace_capture_id is None
    assert failed.boc_verification_id is None
    assert failed.inclusion_catalog_digest_sha256 is None
    assert failed.native_ledger_id is None
    assert "secret-marker" not in (failed.error_detail_safe or "")
    assert worker.recover_expired() == 0


def _succeeded_clone(base: CaseEvidenceVerification, *, offset: int):
    at = base.completed_at + timedelta(microseconds=offset)
    return CaseEvidenceVerification(
        public_id=str(uuid4()),
        case_id=base.case_id,
        snapshot_sync_id=base.snapshot_sync_id,
        source_sync_id=base.source_sync_id,
        source_transaction_id=base.source_transaction_id,
        activity_public_id=base.activity_public_id,
        activity_semantic_fingerprint=base.activity_semantic_fingerprint,
        policy=base.policy,
        state="succeeded",
        stage="terminal",
        progress_current=4,
        status_version=base.status_version,
        highest_evidence_level="chain_inclusion_proven",
        provider=base.provider,
        network=base.network,
        wallet_account_canonical=base.wallet_account_canonical,
        transaction_hash=base.transaction_hash,
        transaction_logical_time=base.transaction_logical_time,
        idempotency_key=str(uuid4()),
        request_fingerprint=base.request_fingerprint,
        attempt_count=base.attempt_count,
        max_attempts=base.max_attempts,
        next_attempt_at=None,
        checkpoint_json=base.checkpoint_json,
        trace_capture_id=base.trace_capture_id,
        trace_digest_sha256=base.trace_digest_sha256,
        trace_completed_at=base.trace_completed_at,
        boc_verification_id=base.boc_verification_id,
        boc_digest_sha256=base.boc_digest_sha256,
        boc_completed_at=base.boc_completed_at,
        inclusion_catalog_digest_sha256=base.inclusion_catalog_digest_sha256,
        inclusion_completed_at=base.inclusion_completed_at,
        native_ledger_id=base.native_ledger_id,
        native_ledger_digest_sha256=base.native_ledger_digest_sha256,
        native_ledger_completed_at=base.native_ledger_completed_at,
        result_digest_sha256=base.result_digest_sha256,
        message_safe=base.message_safe,
        created_at=at,
        updated_at=at,
        started_at=base.started_at,
        completed_at=at,
    )


def test_catalog_revalidates_each_shared_real_artifact_set_once(
    real_artifact_context,
    monkeypatch,
):
    seeded = _seed_real_artifact_job(real_artifact_context)
    assert _real_worker(real_artifact_context).run_once() is True
    with real_artifact_context.sessions() as session:
        base = session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.public_id == seeded.verification_id
            )
        )
        session.add_all(_succeeded_clone(base, offset=index + 1) for index in range(49))
        session.commit()

    import services.wallet_case_evidence as evidence_service_module

    calls = {"trace": 0, "boc": 0, "inclusion": 0, "ledger": 0}
    for label, name in (
        ("trace", "get_persisted_wallet_transaction_trace_evidence"),
        ("boc", "get_wallet_transaction_trace_boc_verification"),
        ("inclusion", "get_wallet_transaction_inclusion_proofs"),
        ("ledger", "get_wallet_native_activity_ledger"),
    ):
        original = getattr(evidence_service_module, name)

        def counted(*args, _label=label, _original=original, **kwargs):
            calls[_label] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(evidence_service_module, name, counted)

    with real_artifact_context.sessions() as session:
        catalog = CaseEvidenceService(session).catalog(
            seeded.case_id,
            snapshot_public_id=seeded.snapshot_id,
            runner_available=True,
        )
    assert catalog["aggregate"]["total"] == 50
    assert catalog["aggregate"]["returned_count"] == 50
    assert catalog["aggregate"]["succeeded"] == 50
    assert calls == {"trace": 1, "boc": 1, "inclusion": 1, "ledger": 1}


def test_pool_connection_is_free_during_actual_provider_and_liteserver_calls(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setenv("TONAPI_API_KEY", "pool-test-key")
    monkeypatch.setenv("TON_LITECLIENT_TRUST_LEVEL", "0")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'provider-pool.sqlite3'}",
        connect_args={"check_same_thread": False, "timeout": 0.25},
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.5,
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    assert run_database_migrations(engine).revision_after == "20260827_0026"
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    context = SimpleNamespace(engine=engine, sessions=sessions)
    seeded = _seed_real_artifact_job(context)
    monkeypatch.setattr(legacy_boc_service, "_derive_boc_evidence", _fake_boc_derived)
    monkeypatch.setattr(legacy_inclusion_service, "_verify_proof", lambda *_a, **_k: None)

    def run_blocked(operation, install):
        entered = Event()
        release = Event()
        errors: list[BaseException] = []
        install(entered, release)

        def target():
            try:
                with sessions() as session:
                    operation(session)
            except BaseException as exc:  # pragma: no cover - asserted below
                errors.append(exc)

        thread = Thread(target=target, daemon=True)
        thread.start()
        assert entered.wait(3)
        assert engine.pool.checkedout() == 0
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        release.set()
        thread.join(5)
        assert not thread.is_alive()
        assert errors == []

    def install_trace(entered, release):
        def blocked(*_args, **_kwargs):
            entered.set()
            assert release.wait(3)
            return ProviderResult.success(_normalized_finalized_candidate(), source="real")

        monkeypatch.setattr(
            TonapiAdapter,
            "get_transaction_trace_persisted_evidence",
            blocked,
        )

    run_blocked(
        lambda session: capture_persisted_wallet_transaction_trace_evidence(
            seeded.run_id, ROOT_HASH, session
        ),
        install_trace,
    )

    def install_boc(entered, release):
        def blocked(*_args, **_kwargs):
            entered.set()
            assert release.wait(3)
            return ProviderResult.success(
                {
                    "trace": _normalized_finalized_candidate(),
                    "transaction_bocs": [
                        {"preorder_index": 0, "transaction_hash": ROOT_HASH, "transaction_boc_hex": "00", "transaction_boc_bytes": 1},
                        {"preorder_index": 1, "transaction_hash": CHILD_HASH, "transaction_boc_hex": "01", "transaction_boc_bytes": 1},
                    ],
                    "total_boc_bytes": 2,
                },
                source="real",
            )

        monkeypatch.setattr(
            TonapiAdapter,
            "get_transaction_trace_boc_verification_candidate",
            blocked,
        )

    run_blocked(
        lambda session: verify_wallet_transaction_trace_bocs(
            seeded.run_id, ROOT_HASH, session
        ),
        install_boc,
    )

    def install_inclusion(entered, release):
        def blocked(**kwargs):
            entered.set()
            assert release.wait(3)
            return _canonical_inclusion_candidate(**kwargs)

        context.live_verifier = blocked

    run_blocked(
        lambda session: create_wallet_transaction_inclusion_proofs(
            seeded.run_id,
            ROOT_HASH,
            session,
            live_verifier=context.live_verifier,
        ),
        install_inclusion,
    )
    engine.dispose()
