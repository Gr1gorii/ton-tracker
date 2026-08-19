"""Integration tests for the content-addressed Wallet Case report."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from adapters.wallet_activity import TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
from database import create_database_engine, get_session
from main import app
from models import (
    CaseSync,
    LOCAL_SINGLE_USER_SCOPE,
    WalletCase,
    WalletIngestionRun,
    WalletTransaction,
)
from services.database_migrations import run_database_migrations
from services.ton_transaction_identity import derive_ton_transaction_identity
from services.wallet_case_report import _assurance_level
from wallet_case_report_schemas import WalletCaseReportResponse


ACCOUNT = f"0:{'11' * 32}"
START = datetime(2026, 8, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


@pytest.fixture
def report_client(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'report.sqlite3'}")
    migration = run_database_migrations(engine)
    assert migration.revision_after == "20260710_0022"
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    app.state.case_report_test_sessions = sessions
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        del app.state.case_report_test_sessions
        engine.dispose()


def test_unsynchronized_report_is_honest_and_scoped(report_client):
    with app.state.case_report_test_sessions() as session:
        wallet_case = _case(session, environment="live")
        session.commit()
        case_id = wallet_case.public_id

    response = report_client.get(f"/api/v1/cases/{case_id}/report")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "case_public_id": case_id,
        "snapshot_public_id": None,
        "report": None,
        "limitations": [{
            "code": "not_synchronized",
            "message": "Synchronize this Wallet Case before building a report.",
        }],
    }
    export = report_client.get(f"/api/v1/cases/{case_id}/report/export.json")
    assert export.status_code == 409
    assert export.json()["detail"]["code"] == "case_report_not_ready"


def test_demo_report_is_reproducible_observed_and_exports_exact_revision(report_client):
    with app.state.case_report_test_sessions() as session:
        wallet_case = _case(session, environment="demo")
        run, sync = _run_and_sync(session, wallet_case)
        session.add(_demo_transaction(run))
        session.commit()
        case_id = wallet_case.public_id
        snapshot_id = sync.public_id

    first = report_client.get(
        f"/api/v1/cases/{case_id}/report",
        params={"snapshot": snapshot_id},
    )
    second = report_client.get(
        f"/api/v1/cases/{case_id}/report",
        params={"snapshot": snapshot_id},
    )
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    report = first.json()["report"]
    assert report["assurance_level"] == "observed"
    assert report["public_id"] == f"rpt_{report['content_hash_sha256']}"
    assert report["snapshot_public_id"] == snapshot_id
    assert report["activity_revision"]["aggregate"]["transactions"] == 1
    assert report["evidence_revision"]["total_attempts"] == 0
    assert report["canonical_gate"]["eligible"] is False
    assert "live_data_required" in report["canonical_gate"]["unmet"]
    assert "full_history_proof_required" in report["canonical_gate"]["unmet"]
    assert report["truth_boundaries"] == {
        "establishes_complete_wallet_history": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "includes_raw_provider_payloads": False,
        "provider_free_full_report_revalidation": False,
    }
    serialized = first.text
    for forbidden in (
        "run_id",
        "ingestion_run_id",
        "source_transaction_id",
        "lease_token",
        "raw_json",
    ):
        assert forbidden not in serialized

    exported = report_client.get(
        f"/api/v1/cases/{case_id}/report/export.json",
        params={"snapshot": snapshot_id},
    )
    assert exported.status_code == 200
    assert exported.headers["cache-control"] == "no-store"
    assert exported.headers["content-disposition"].endswith(
        f'{report["public_id"]}.json"'
    )
    assert exported.json() == first.json()


def test_live_normalized_report_keeps_canonical_gate_fail_closed(report_client):
    with app.state.case_report_test_sessions() as session:
        wallet_case = _case(session, environment="live")
        run, sync = _run_and_sync(session, wallet_case)
        session.add(_live_transaction(run))
        session.commit()
        case_id = wallet_case.public_id
        snapshot_id = sync.public_id

    response = report_client.get(
        f"/api/v1/cases/{case_id}/report",
        params={"snapshot": snapshot_id},
    )
    assert response.status_code == 200, response.text
    report = response.json()["report"]
    assert report["assurance_level"] == "normalized"
    assert report["canonical_gate"]["eligible"] is False
    assert "full_history_proof_required" in report["canonical_gate"]["unmet"]
    assert "every_transaction_must_be_chain_proven" in report["canonical_gate"]["unmet"]
    assert "every_transaction_needs_native_ledger" in report["canonical_gate"]["unmet"]
    assert report["unverified_claims"]


def test_report_query_and_response_model_fail_closed(report_client):
    with app.state.case_report_test_sessions() as session:
        wallet_case = _case(session, environment="demo")
        _run, sync = _run_and_sync(session, wallet_case)
        session.commit()
        case_id = wallet_case.public_id
        snapshot_id = sync.public_id

    duplicate = report_client.get(
        f"/api/v1/cases/{case_id}/report?snapshot={snapshot_id}&snapshot={snapshot_id}"
    )
    unknown = report_client.get(f"/api/v1/cases/{case_id}/report?run_id=1")
    missing = report_client.get(
        f"/api/v1/cases/{case_id}/report",
        params={"snapshot": str(uuid4())},
    )
    assert duplicate.status_code == unknown.status_code == 422
    assert missing.status_code == 404

    valid = report_client.get(
        f"/api/v1/cases/{case_id}/report",
        params={"snapshot": snapshot_id},
    ).json()
    valid["report"]["assurance_level"] = "canonical"
    with pytest.raises(ValueError):
        WalletCaseReportResponse.model_validate(valid)


def test_partially_verified_assurance_requires_a_local_artifact_prefix():
    live_case = WalletCase(data_environment="live")
    assert _assurance_level(
        wallet_case=live_case,
        evidence={"locally_verified_activity_count": 0},
        canonical=False,
    ) == "normalized"
    assert _assurance_level(
        wallet_case=live_case,
        evidence={"locally_verified_activity_count": 1},
        canonical=False,
    ) == "partially_verified"
    assert _assurance_level(
        wallet_case=live_case,
        evidence={"locally_verified_activity_count": 1},
        canonical=True,
    ) == "canonical"


def _case(session: Session, *, environment: str) -> WalletCase:
    row = WalletCase(
        public_id=str(uuid4()),
        owner_scope_id=LOCAL_SINGLE_USER_SCOPE,
        network="ton-mainnet",
        data_environment=environment,
        canonical_wallet_key=ACCOUNT,
        canonical_identity_version="ton_raw_address_v1",
        display_address=ACCOUNT,
        created_at=START,
        updated_at=START,
    )
    session.add(row)
    session.flush()
    return row


def _run_and_sync(
    session: Session,
    wallet_case: WalletCase,
) -> tuple[WalletIngestionRun, CaseSync]:
    demo = wallet_case.data_environment == "demo"
    mode = "mock" if demo else "real"
    provider = "mock_wallet_activity" if demo else TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
    run = WalletIngestionRun(
        wallet_address=ACCOUNT,
        time_window="custom",
        custom_start=START,
        custom_end=END,
        data_mode=mode,
        status="success",
        requested_surfaces_json=json.dumps(["transactions"]),
        provider_summary_json=json.dumps({
            "provider_evidence": [{"provider": provider}],
            "unavailable_surfaces": [],
            "incomplete_surfaces": [],
        }),
        wallet_identity_status="network_scoped",
        wallet_identity_version="ton_raw_address_v1",
        wallet_network="ton-mainnet",
        wallet_address_canonical=ACCOUNT,
        wallet_workchain_id=0,
        wallet_account_id_hex="11" * 32,
        wallet_address_format="raw",
        created_at=END,
        updated_at=END,
    )
    session.add(run)
    session.flush()
    coverage = {
        "state": "unknown" if demo else "bounded_complete",
        "requested_start_at": _iso(START),
        "requested_end_at": _iso(END),
        "requested_surfaces": ["transactions"],
        "unavailable_surfaces": [],
        "incomplete_surfaces": [],
        "streams": [],
        "full_history_proven": False,
    }
    sync = CaseSync(
        public_id=str(uuid4()),
        case_id=wallet_case.id,
        ingestion_run_id=run.id,
        time_window="custom",
        data_mode=mode,
        provider=provider,
        requested_start=START,
        requested_end=END,
        requested_surfaces_json=json.dumps(["transactions"]),
        state="succeeded",
        stage="completed",
        progress_current=3,
        progress_total=3,
        coverage_summary_json=json.dumps(coverage),
        result_summary_json=json.dumps({
            "activity_counts": {"transfers": 0, "transactions": 1, "swaps": 0, "balances": 0},
            "failed_transaction_count": 0,
            "warning_count": 0,
            "portfolio_snapshot": {"total_balance_usd": None, "priced_assets": 0, "unpriced_assets": 0},
        }),
        message_safe="Stored report test snapshot.",
        created_at=END,
        updated_at=END,
        started_at=END,
        completed_at=END,
    )
    session.add(sync)
    session.flush()
    return run, sync


def _demo_transaction(run: WalletIngestionRun) -> WalletTransaction:
    return WalletTransaction(
        run=run,
        tx_hash="demo-report-transaction",
        logical_time="42",
        timestamp=START + timedelta(hours=1),
        fee_ton="0.1",
        success="success",
        provider="mock_wallet_activity",
        source_status="mock",
        raw_json=json.dumps({"fixture": "report-test", "surface": "transactions"}),
        transaction_identity_status="unavailable",
        transaction_identity_version="unavailable",
        transaction_network="ton-unknown",
    )


def _live_transaction(run: WalletIngestionRun) -> WalletTransaction:
    transaction_hash = "ab" * 32
    timestamp = START + timedelta(hours=1)
    raw = {
        "provider": "tonapi",
        "surface": "transactions",
        "tx_hash": transaction_hash,
        "logical_time": "42",
        "utime": int(timestamp.timestamp()),
        "normalized_fee_ton": "0.1",
        "source": "tonapi",
    }
    identity = derive_ton_transaction_identity(
        network="ton-mainnet",
        account_address_canonical=ACCOUNT,
        account_identity_status="network_scoped",
        account_identity_version="ton_raw_address_v1",
        account_workchain_id=0,
        account_id_hex="11" * 32,
        logical_time="42",
        transaction_hash=transaction_hash,
        data_mode="real",
        source_status="live",
        provider="tonapi",
        raw=raw,
    )
    return WalletTransaction(
        run=run,
        tx_hash=transaction_hash,
        logical_time="42",
        timestamp=timestamp,
        fee_ton="0.1",
        success="success",
        provider="tonapi",
        source_status="live",
        raw_json=json.dumps(raw),
        transaction_identity_status=identity.status,
        transaction_identity_version=identity.version,
        transaction_network=identity.network,
        transaction_account_canonical=identity.account_canonical,
        transaction_logical_time_canonical=identity.logical_time_canonical,
        transaction_hash_canonical=identity.hash_canonical,
        transaction_identity_key=identity.key,
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
