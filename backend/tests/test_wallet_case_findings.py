"""Integration tests for pinned Wallet Case Findings and Flows."""

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
    WalletSwap,
    WalletTransaction,
    WalletTransfer,
)
from services.database_migrations import run_database_migrations
from services.ton_event_action_identity import derive_ton_event_action_identity
from services.ton_transaction_identity import derive_ton_transaction_identity
from services.wallet_case_findings import _finding, _findings
from wallet_case_findings_schemas import WalletCaseFinding, WalletCaseFindingsResponse


ACCOUNT = f"0:{'11' * 32}"
COUNTERPARTY = f"0:{'22' * 32}"
JETTON_A = f"0:{'33' * 32}"
JETTON_B = f"0:{'44' * 32}"
START = datetime(2026, 8, 1, tzinfo=timezone.utc)
END = START + timedelta(days=1)


@pytest.fixture
def findings_client(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'findings.sqlite3'}")
    migration = run_database_migrations(engine)
    assert migration.revision_after == "20260828_0028"
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    app.state.findings_test_sessions = sessions
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        del app.state.findings_test_sessions
        engine.dispose()


def test_unsynchronized_findings_are_honest_and_no_store(findings_client):
    with app.state.findings_test_sessions() as session:
        wallet_case = _case(session, environment="live")
        session.commit()
        case_id = wallet_case.public_id

    response = findings_client.get(f"/api/v1/cases/{case_id}/findings")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "case_public_id": case_id,
        "snapshot_public_id": None,
        "findings": None,
        "limitations": [{
            "code": "not_synchronized",
            "message": "Synchronize this Wallet Case before reviewing findings.",
        }],
    }


def test_live_findings_are_reproducible_explainable_and_asset_scoped(findings_client):
    with app.state.findings_test_sessions() as session:
        wallet_case = _case(session, environment="live")
        run, sync = _run_and_sync(session, wallet_case)
        run.transactions.append(_transaction(run, outcome="failed"))
        run.transfers.extend((
            _transfer(run, index=0, direction="in", amount="3", contract=None),
            _transfer(run, index=1, direction="out", amount="1", contract=None),
            _transfer(run, index=2, direction="in", amount="4", contract=JETTON_A),
            _transfer(run, index=3, direction="in", amount="5", contract=JETTON_B),
        ))
        run.swaps.append(_swap(run, index=4))
        session.commit()
        case_id, snapshot_id = wallet_case.public_id, sync.public_id

    first = findings_client.get(
        f"/api/v1/cases/{case_id}/findings",
        params={"snapshot": snapshot_id},
    )
    second = findings_client.get(
        f"/api/v1/cases/{case_id}/findings",
        params={"snapshot": snapshot_id},
    )
    assert first.status_code == second.status_code == 200, first.text
    assert first.json() == second.json()
    document = first.json()["findings"]
    assert document["public_id"] == f"fset_{document['content_hash_sha256']}"
    assert document["snapshot_public_id"] == snapshot_id
    assert document["activity_revision"]["aggregate"] == {
        "total_items": 6,
        "transactions": 1,
        "transfers": 4,
        "swaps": 1,
        "failed_transactions": 1,
        "source_sync_count": 1,
        "suppressed_duplicate_observations": 0,
        "conflicted_identity_count": 0,
    }
    flows = document["flows"]
    assert flows["identified_asset_count"] == 3
    same_symbol_jettons = [
        row for row in flows["asset_flows"] if row["symbol"] == "SAME"
    ]
    assert len(same_symbol_jettons) == 2
    assert len({row["asset_id"] for row in same_symbol_jettons}) == 2
    assert {row["contract_address"] for row in same_symbol_jettons} == {
        JETTON_A,
        JETTON_B,
    }
    ton = next(row for row in flows["asset_flows"] if row["standard"] == "native")
    assert ton["inflow_amount"] == "3"
    assert ton["outflow_amount"] == "2"
    assert ton["inflow_observations"] == 1
    assert ton["outflow_observations"] == 2
    counterparty = flows["counterparty_flows"][0]
    assert counterparty["canonical_address"] == COUNTERPARTY
    assert counterparty["incoming_observations"] == 3
    assert counterparty["outgoing_observations"] == 1
    assert flows["protocol_flows"][0]["protocol_id"] == "stonfi_v2"

    by_rule = {}
    for finding in document["findings"]:
        by_rule.setdefault(finding["rule_id"], []).append(finding)
    assert by_rule["failed_transaction_observations_v1"][0]["importance"] == "attention"
    assert by_rule["repeated_counterparty_observations_v1"][0]["affected_count"] == 4
    assert by_rule["recognized_protocol_observations_v1"][0]["affected_count"] == 1
    assert all(
        support["activity_public_id"].startswith("act_")
        for finding in document["findings"]
        for support in finding["supporting_activities"]
    )
    assert document["truth_boundaries"] == {
        "establishes_complete_wallet_history": False,
        "establishes_ownership_or_control": False,
        "establishes_illicit_or_safe_status": False,
        "absence_of_findings_means_safe": False,
        "cross_asset_amounts_are_comparable": False,
        "includes_raw_provider_payloads": False,
    }
    assert "absence_of_findings_not_safety" in {
        item["code"] for item in document["limitations"]
    }
    for forbidden in (
        "run_id",
        "ingestion_run_id",
        "source_transaction_id",
        "raw_json",
        "lease_token",
        "risk_score",
    ):
        assert forbidden not in first.text


def test_demo_findings_remain_fixture_only_and_do_not_claim_safety(findings_client):
    with app.state.findings_test_sessions() as session:
        wallet_case = _case(session, environment="demo")
        run, sync = _run_and_sync(session, wallet_case)
        run.transactions.append(_demo_transaction(run))
        session.commit()
        case_id, snapshot_id = wallet_case.public_id, sync.public_id

    response = findings_client.get(
        f"/api/v1/cases/{case_id}/findings",
        params={"snapshot": snapshot_id},
    )
    assert response.status_code == 200, response.text
    document = response.json()["findings"]
    assert document["subject"]["data_environment"] == "demo"
    assert document["findings"]
    assert all(item["evidence_level"] == "fixture" for item in document["findings"])
    assert document["truth_boundaries"]["absence_of_findings_means_safe"] is False


def test_findings_query_and_response_contract_fail_closed(findings_client):
    with app.state.findings_test_sessions() as session:
        wallet_case = _case(session, environment="demo")
        _run, sync = _run_and_sync(session, wallet_case)
        session.commit()
        case_id, snapshot_id = wallet_case.public_id, sync.public_id

    duplicate = findings_client.get(
        f"/api/v1/cases/{case_id}/findings?snapshot={snapshot_id}&snapshot={snapshot_id}"
    )
    unknown = findings_client.get(f"/api/v1/cases/{case_id}/findings?run_id=1")
    missing = findings_client.get(
        f"/api/v1/cases/{case_id}/findings",
        params={"snapshot": str(uuid4())},
    )
    assert duplicate.status_code == unknown.status_code == 422
    assert missing.status_code == 404

    valid = findings_client.get(
        f"/api/v1/cases/{case_id}/findings",
        params={"snapshot": snapshot_id},
    ).json()
    valid["findings"]["truth_boundaries"]["absence_of_findings_means_safe"] = True
    with pytest.raises(ValueError):
        WalletCaseFindingsResponse.model_validate(valid)


def test_failed_outcome_claim_does_not_inherit_transaction_inclusion_assurance():
    item = {
        "public_id": "act_failed",
        "kind": "transaction",
        "outcome": "failed",
        "occurred_at": _iso(START),
    }
    findings, _state = _findings(
        (item,),
        aggregate={"conflicted_identity_count": 0},
        gaps=(),
        evidence_levels={"act_failed": "chain_inclusion_proven"},
        demo=False,
        flow_state={
            "unavailable_asset_ids": set(),
            "unavailable_counterparty_ids": set(),
            "counterparty_groups": [],
            "protocol_groups": [],
        },
    )

    failed = next(
        row
        for row in findings
        if row["rule_id"] == "failed_transaction_observations_v1"
    )
    assert failed["evidence_level"] == "normalized_provider_observation"
    assert failed["supporting_activities"][0]["evidence_level"] == (
        "chain_inclusion_proven"
    )


def test_truncated_supports_include_omitted_rows_in_weakest_evidence_level():
    activity_ids = [f"act_{index:02d}" for index in range(51)]
    by_id = {
        activity_id: {
            "kind": "transaction",
            "occurred_at": _iso(START),
        }
        for activity_id in activity_ids
    }
    evidence_levels = {
        activity_id: "chain_inclusion_proven"
        for activity_id in activity_ids[:50]
    }
    evidence_levels[activity_ids[50]] = "normalized_provider_observation"

    finding = _finding(
        rule_id="failed_transaction_observations_v1",
        key="failed",
        category="transaction_outcome",
        importance="attention",
        title="Failed transaction observations",
        explanation="Observed provider outcomes.",
        affected_count=len(activity_ids),
        support_basis="activity_rows",
        activity_ids=activity_ids,
        by_id=by_id,
        evidence_levels=evidence_levels,
        fallback_level="normalized_provider_observation",
    )

    assert finding["support_truncated"] is True
    assert len(finding["supporting_activities"]) == 50
    assert all(
        support["evidence_level"] == "chain_inclusion_proven"
        for support in finding["supporting_activities"]
    )
    assert finding["evidence_level"] == "normalized_provider_observation"


def test_public_finding_schema_rejects_assurance_overstatement():
    support = [{
        "activity_public_id": f"act_{'1' * 64}",
        "kind": "transaction",
        "occurred_at": _iso(START),
        "evidence_level": "chain_inclusion_proven",
    }]
    base = {
        "public_id": f"finding_{'2' * 64}",
        "rule_id": "failed_transaction_observations_v1",
        "category": "transaction_outcome",
        "importance": "attention",
        "title": "Failed transaction observations",
        "explanation": "Observed provider outcomes.",
        "affected_count": 1,
        "support_basis": "activity_rows",
        "supporting_activities": support,
        "support_truncated": False,
        "evidence_level": "chain_inclusion_proven",
    }
    with pytest.raises(ValueError, match="provider outcome"):
        WalletCaseFinding.model_validate(base)

    weaker_support = dict(base)
    weaker_support["rule_id"] = "repeated_counterparty_observations_v1"
    weaker_support["category"] = "flow_pattern"
    weaker_support["supporting_activities"] = [
        support[0] | {"evidence_level": "normalized_provider_observation"}
    ]
    with pytest.raises(ValueError, match="weakest public support"):
        WalletCaseFinding.model_validate(weaker_support)


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
    surfaces = ["transactions", "transfers", "swaps"]
    run = WalletIngestionRun(
        wallet_address=ACCOUNT,
        time_window="custom",
        custom_start=START,
        custom_end=END,
        data_mode=mode,
        status="success",
        requested_surfaces_json=json.dumps(surfaces),
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
        "requested_surfaces": surfaces,
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
        requested_surfaces_json=json.dumps(surfaces),
        state="succeeded",
        stage="completed",
        progress_current=3,
        progress_total=3,
        coverage_summary_json=json.dumps(coverage),
        result_summary_json=json.dumps({
            "activity_counts": {"transfers": 4, "transactions": 1, "swaps": 1, "balances": 0},
            "failed_transaction_count": 1,
            "warning_count": 0,
            "portfolio_snapshot": {"total_balance_usd": None, "priced_assets": 0, "unpriced_assets": 0},
        }),
        message_safe="Stored findings test snapshot.",
        created_at=END,
        updated_at=END,
        started_at=END,
        completed_at=END,
    )
    session.add(sync)
    session.flush()
    return run, sync


def _transaction(run: WalletIngestionRun, *, outcome: str) -> WalletTransaction:
    tx_hash = "ab" * 32
    timestamp = START + timedelta(hours=1)
    raw = {
        "provider": "tonapi",
        "surface": "transactions",
        "tx_hash": tx_hash,
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
        transaction_hash=tx_hash,
        data_mode="real",
        source_status="live",
        provider="tonapi",
        raw=raw,
    )
    return WalletTransaction(
        run=run,
        tx_hash=tx_hash,
        logical_time="42",
        timestamp=timestamp,
        fee_ton="0.1",
        success=outcome,
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


def _transfer(
    run: WalletIngestionRun,
    *,
    index: int,
    direction: str,
    amount: str,
    contract: str | None,
) -> WalletTransfer:
    event_id = f"{index + 1:064x}"
    logical_time = str(100 + index)
    timestamp = START + timedelta(hours=index + 2)
    action_type = "TonTransfer" if contract is None else "JettonTransfer"
    symbol = "TON" if contract is None else "SAME"
    raw = {
        "provider": "tonapi",
        "surface": "transfers",
        "source": "tonapi",
        "event_id": event_id,
        "lt": logical_time,
        "action_index": index,
        "action_type": action_type,
        "jetton_address": contract,
        "jetton_symbol": symbol if contract else None,
        "utime": int(timestamp.timestamp()),
        "normalized_amount": amount,
        "direction": direction,
        "counterparty": COUNTERPARTY,
    }
    identity = derive_ton_event_action_identity(
        network="ton-mainnet",
        account_address_canonical=ACCOUNT,
        account_identity_status="network_scoped",
        account_identity_version="ton_raw_address_v1",
        account_workchain_id=0,
        account_id_hex="11" * 32,
        event_id=event_id,
        logical_time=logical_time,
        action_index=index,
        action_type=action_type,
        surface="transfers",
        data_mode="real",
        source_status="live",
        provider="tonapi",
        raw=raw,
    )
    return WalletTransfer(
        run=run,
        tx_hash=event_id,
        logical_time=logical_time,
        timestamp=timestamp,
        asset=symbol,
        amount=amount,
        direction=direction,
        counterparty=COUNTERPARTY,
        provider="tonapi",
        source_status="live",
        raw_json=json.dumps(raw),
        event_action_identity_status=identity.status,
        event_action_identity_version=identity.version,
        event_action_network=identity.network,
        event_action_account_canonical=identity.account_canonical,
        event_action_event_id_canonical=identity.event_id_canonical,
        event_action_logical_time_canonical=identity.logical_time_canonical,
        event_action_index=identity.action_index,
        event_action_type=identity.action_type,
        event_action_identity_key=identity.key,
    )


def _swap(run: WalletIngestionRun, *, index: int) -> WalletSwap:
    event_id = f"{100 + index:064x}"
    logical_time = str(300 + index)
    timestamp = START + timedelta(hours=index + 2)
    raw = {
        "provider": "tonapi",
        "surface": "swaps",
        "source": "tonapi",
        "event_id": event_id,
        "lt": logical_time,
        "action_index": index,
        "action_type": "JettonSwap",
        "utime": int(timestamp.timestamp()),
        "dex": "STON.fi v2",
        "token_in": "TON",
        "token_in_standard": "native",
        "token_in_address": None,
        "normalized_amount_in": "1",
        "token_out": "SAME",
        "token_out_standard": "jetton",
        "token_out_address": JETTON_A,
        "normalized_amount_out": "2",
    }
    identity = derive_ton_event_action_identity(
        network="ton-mainnet",
        account_address_canonical=ACCOUNT,
        account_identity_status="network_scoped",
        account_identity_version="ton_raw_address_v1",
        account_workchain_id=0,
        account_id_hex="11" * 32,
        event_id=event_id,
        logical_time=logical_time,
        action_index=index,
        action_type="JettonSwap",
        surface="swaps",
        data_mode="real",
        source_status="live",
        provider="tonapi",
        raw=raw,
    )
    return WalletSwap(
        run=run,
        tx_hash=event_id,
        timestamp=timestamp,
        dex="STON.fi v2",
        token_in="TON",
        amount_in="1",
        token_out="SAME",
        amount_out="2",
        estimated_usd=None,
        provider="tonapi",
        source_status="live",
        raw_json=json.dumps(raw),
        event_action_identity_status=identity.status,
        event_action_identity_version=identity.version,
        event_action_network=identity.network,
        event_action_account_canonical=identity.account_canonical,
        event_action_event_id_canonical=identity.event_id_canonical,
        event_action_logical_time_canonical=identity.logical_time_canonical,
        event_action_index=identity.action_index,
        event_action_type=identity.action_type,
        event_action_identity_key=identity.key,
    )


def _demo_transaction(run: WalletIngestionRun) -> WalletTransaction:
    return WalletTransaction(
        run=run,
        tx_hash="demo-findings-transaction",
        logical_time="42",
        timestamp=START + timedelta(hours=1),
        fee_ton="0.1",
        success="failed",
        provider="mock_wallet_activity",
        source_status="mock",
        raw_json=json.dumps({"fixture": "findings-test", "surface": "transactions"}),
        transaction_identity_status="unavailable",
        transaction_identity_version="unavailable",
        transaction_network="ton-unknown",
    )


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
