"""Integration coverage for the canonical Wallet Case Activity read facade."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
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


ACCOUNT = f"0:{'11' * 32}"
JETTON_A = f"0:{'22' * 32}"
JETTON_B = f"0:{'33' * 32}"
START = datetime(2026, 8, 1, tzinfo=timezone.utc)
END = START + timedelta(days=7)
TESTNET_COUNTERPARTY = "kQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPgpP"


@pytest.fixture
def activity_client(tmp_path):
    engine = create_database_engine(f"sqlite:///{tmp_path / 'activity.sqlite3'}")
    report = run_database_migrations(engine)
    assert report.revision_after == "20260827_0027"
    sessions = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    def override():
        session = sessions()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_session] = override
    app.state.activity_test_sessions = sessions
    app.state.activity_test_engine = engine
    client = TestClient(app)
    try:
        yield client
    finally:
        app.dependency_overrides.clear()
        del app.state.activity_test_sessions
        del app.state.activity_test_engine
        engine.dispose()


def _case(
    session: Session,
    *,
    environment: str = "live",
    account: str = ACCOUNT,
) -> WalletCase:
    wallet_case = WalletCase(
        public_id=str(uuid4()),
        owner_scope_id=LOCAL_SINGLE_USER_SCOPE,
        network="ton-mainnet",
        data_environment=environment,
        canonical_wallet_key=account,
        canonical_identity_version="ton_raw_address_v1",
        display_address=account,
        created_at=START,
        updated_at=START,
    )
    session.add(wallet_case)
    session.flush()
    return wallet_case


def _run_and_sync(
    session: Session,
    wallet_case: WalletCase,
    *,
    status: str = "success",
    surfaces: list[str] | None = None,
    start: datetime = START,
    end: datetime = END,
    coverage_state: str = "bounded_complete",
) -> tuple[WalletIngestionRun, CaseSync]:
    surfaces = surfaces or ["transactions"]
    is_demo = wallet_case.data_environment == "demo"
    data_mode = "mock" if is_demo else "real"
    provider = (
        "mock_wallet_activity"
        if is_demo
        else TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
    )
    run = WalletIngestionRun(
        wallet_address=wallet_case.canonical_wallet_key,
        time_window="custom",
        custom_start=start,
        custom_end=end,
        data_mode=data_mode,
        status=status,
        requested_surfaces_json=json.dumps(surfaces),
        provider_summary_json=json.dumps(
            {
                "provider_evidence": [{"provider": provider}],
                "unavailable_surfaces": [],
                "incomplete_surfaces": (
                    [surface for surface in surfaces if surface in {"transfers", "swaps"}]
                    if status == "partial"
                    else []
                ),
            }
        ),
        wallet_identity_status="network_scoped",
        wallet_identity_version="ton_raw_address_v1",
        wallet_network="ton-mainnet",
        wallet_address_canonical=wallet_case.canonical_wallet_key,
        wallet_workchain_id=int(wallet_case.canonical_wallet_key.split(":", 1)[0]),
        wallet_account_id_hex=wallet_case.canonical_wallet_key.split(":", 1)[1],
        wallet_address_format="raw",
        created_at=end,
        updated_at=end,
    )
    session.add(run)
    session.flush()
    state = "partial" if status == "partial" else "succeeded"
    sync = CaseSync(
        public_id=str(uuid4()),
        case_id=wallet_case.id,
        ingestion_run_id=run.id,
        time_window="custom",
        data_mode=data_mode,
        provider=provider,
        requested_start=start,
        requested_end=end,
        requested_surfaces_json=json.dumps(surfaces),
        state=state,
        stage="completed_with_limitations" if state == "partial" else "completed",
        progress_current=3,
        progress_total=3,
        coverage_summary_json=json.dumps(
            {
                "state": "unknown" if is_demo else coverage_state,
                "requested_start_at": _iso(start),
                "requested_end_at": _iso(end),
                "requested_surfaces": surfaces,
                "unavailable_surfaces": [],
                "incomplete_surfaces": (
                    [surface for surface in surfaces if surface in {"transfers", "swaps"}]
                    if state == "partial"
                    else []
                ),
                "streams": [],
                "full_history_proven": False,
            }
        ),
        result_summary_json=json.dumps(_zero_summary()),
        message_safe="Stored test snapshot.",
        created_at=end,
        updated_at=end,
        started_at=end,
        completed_at=end,
    )
    session.add(sync)
    session.flush()
    wallet_case.updated_at = end
    return run, sync


def _transaction(
    run: WalletIngestionRun,
    *,
    tx_hash: str,
    logical_time: str,
    timestamp: datetime,
    fee: str = "0.1",
) -> WalletTransaction:
    raw = {
        "provider": "tonapi",
        "surface": "transactions",
        "tx_hash": tx_hash,
        "logical_time": logical_time,
        "utime": int(timestamp.timestamp()),
        "normalized_fee_ton": fee,
        "source": "tonapi",
    }
    identity = derive_ton_transaction_identity(
        network=run.wallet_network,
        account_address_canonical=run.wallet_address_canonical,
        account_identity_status=run.wallet_identity_status,
        account_identity_version=run.wallet_identity_version,
        account_workchain_id=run.wallet_workchain_id,
        account_id_hex=run.wallet_account_id_hex,
        logical_time=logical_time,
        transaction_hash=tx_hash,
        data_mode="real",
        source_status="live",
        provider="tonapi",
        raw=raw,
    )
    return WalletTransaction(
        run=run,
        tx_hash=tx_hash,
        logical_time=logical_time,
        timestamp=timestamp,
        fee_ton=fee,
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


def _unavailable_transaction(
    run: WalletIngestionRun,
    *,
    tx_hash: str,
    timestamp: datetime,
) -> WalletTransaction:
    raw = {
        "provider": "tonapi",
        "surface": "transactions",
        "tx_hash": tx_hash,
        "logical_time": None,
        "utime": int(timestamp.timestamp()),
        "normalized_fee_ton": None,
        "source": "tonapi",
    }
    return WalletTransaction(
        run=run,
        tx_hash=tx_hash,
        logical_time=None,
        timestamp=timestamp,
        fee_ton=None,
        success="unknown",
        provider="tonapi",
        source_status="live",
        raw_json=json.dumps(raw),
        transaction_identity_status="unavailable",
        transaction_identity_version="unavailable",
        transaction_network="ton-unknown",
        transaction_account_canonical=None,
        transaction_logical_time_canonical=None,
        transaction_hash_canonical=None,
        transaction_identity_key=None,
    )


def _demo_transaction(
    run: WalletIngestionRun,
    *,
    timestamp: datetime,
) -> WalletTransaction:
    return WalletTransaction(
        run=run,
        tx_hash="demo-transaction",
        logical_time="42",
        timestamp=timestamp,
        fee_ton="0.1",
        success="success",
        provider="mock_wallet_activity",
        source_status="mock",
        raw_json=json.dumps(
            {
                "fixture": "activity-test",
                "surface": "transactions",
            }
        ),
        transaction_identity_status="unavailable",
        transaction_identity_version="unavailable",
        transaction_network="ton-unknown",
        transaction_account_canonical=None,
        transaction_logical_time_canonical=None,
        transaction_hash_canonical=None,
        transaction_identity_key=None,
    )


def _transfer(
    run: WalletIngestionRun,
    *,
    event_id: str,
    logical_time: str,
    action_index: int,
    contract: str | None,
    symbol: str = "SAME",
    action_type: str = "JettonTransfer",
) -> WalletTransfer:
    raw = {
        "provider": "tonapi",
        "surface": "transfers",
        "source": "tonapi",
        "event_id": event_id,
        "lt": logical_time,
        "action_index": action_index,
        "action_type": action_type,
        "jetton_address": contract,
        "jetton_symbol": symbol,
        "utime": int((START + timedelta(hours=action_index + 1)).timestamp()),
        "normalized_amount": "1",
        "direction": "in",
        "counterparty": None,
    }
    identity = derive_ton_event_action_identity(
        network=run.wallet_network,
        account_address_canonical=run.wallet_address_canonical,
        account_identity_status=run.wallet_identity_status,
        account_identity_version=run.wallet_identity_version,
        account_workchain_id=run.wallet_workchain_id,
        account_id_hex=run.wallet_account_id_hex,
        event_id=event_id,
        logical_time=logical_time,
        action_index=action_index,
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
        timestamp=START + timedelta(hours=action_index + 1),
        asset=symbol,
        amount="1",
        direction="in",
        counterparty=None,
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


def _swap(
    run: WalletIngestionRun,
    *,
    event_id: str,
    action_index: int,
    token_in_standard: str,
    token_in_address: str | None,
    logical_time: str | None = None,
) -> WalletSwap:
    raw = {
        "provider": "tonapi",
        "surface": "swaps",
        "source": "tonapi",
        "event_id": event_id,
        "lt": logical_time or str(600 + action_index),
        "action_index": action_index,
        "action_type": "JettonSwap",
        "utime": int((START + timedelta(hours=action_index + 1)).timestamp()),
        "dex": "STON.fi v2",
        "token_in": "TON",
        "token_in_standard": token_in_standard,
        "token_in_address": token_in_address,
        "normalized_amount_in": "1",
        "token_out": "OUT",
        "token_out_standard": "jetton",
        "token_out_address": JETTON_B,
        "normalized_amount_out": "2",
    }
    identity = derive_ton_event_action_identity(
        network=run.wallet_network,
        account_address_canonical=run.wallet_address_canonical,
        account_identity_status=run.wallet_identity_status,
        account_identity_version=run.wallet_identity_version,
        account_workchain_id=run.wallet_workchain_id,
        account_id_hex=run.wallet_account_id_hex,
        event_id=event_id,
        logical_time=raw["lt"],
        action_index=action_index,
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
        timestamp=START + timedelta(hours=action_index + 1),
        dex="STON.fi v2",
        token_in="TON",
        amount_in="1",
        token_out="OUT",
        amount_out="2",
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


def test_unsynchronized_activity_is_honest_empty(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        case_id = wallet_case.public_id
        session.commit()
    response = activity_client.get(f"/api/v1/cases/{case_id}/activity")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["snapshot"] is None
    assert body["aggregate"]["total_items"] == 0
    assert body["items"] == []
    assert body["gaps"][0]["code"] == "not_synchronized"
    assert body["limitations"][0]["code"] == "not_synchronized"


def test_demo_activity_stays_fixture_only_and_origin_filter_scopes_coverage(
    activity_client,
):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session, environment="demo")
        run, snapshot = _run_and_sync(session, wallet_case)
        run.transactions.append(
            _demo_transaction(run, timestamp=START - timedelta(days=30))
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    item = response.json()["items"][0]
    assert item["provenance"] == {
        "data_origin": "demo_fixture",
        "evidence_level": "fixture",
        "provider": "mock_wallet_activity",
        "source_status": "mock",
        "identity_assurance": "unavailable",
        "deduplication_basis": "none",
        "observation_count": 1,
        "suppressed_count": 0,
        "first_seen_sync_public_id": snapshot_id,
        "last_seen_sync_public_id": snapshot_id,
    }
    excluded = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "data_origin": "provider_observed"},
    )
    assert excluded.status_code == 200, excluded.text
    assert excluded.json()["items"] == []
    assert excluded.json()["aggregate"]["source_sync_count"] == 0
    assert "demo_fixture_period_not_chain_coverage" not in {
        gap["code"] for gap in excluded.json()["gaps"]
    }


def test_overlapping_exact_transactions_deduplicate_with_sanitized_detail(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        first_run, _first_sync = _run_and_sync(session, wallet_case, end=END)
        first_run.transactions.append(
            _transaction(
                first_run,
                tx_hash="aa" * 32,
                logical_time="100",
                timestamp=START + timedelta(hours=1),
            )
        )
        second_run, second_sync = _run_and_sync(
            session, wallet_case, end=END + timedelta(seconds=1)
        )
        second_run.transactions.append(
            _transaction(
                second_run,
                tx_hash="aa" * 32,
                logical_time="100",
                timestamp=START + timedelta(hours=1),
            )
        )
        case_id = wallet_case.public_id
        snapshot_id = second_sync.public_id
        session.commit()

    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["aggregate"]["total_items"] == 1
    assert body["aggregate"]["suppressed_duplicate_observations"] == 1
    item = body["items"][0]
    assert item["provenance"]["observation_count"] == 2
    assert item["provenance"]["deduplication_basis"] == "transaction_identity"
    assert "raw_json" not in response.text
    detail = activity_client.get(
        f"/api/v1/cases/{case_id}/activity/{item['public_id']}?snapshot={snapshot_id}"
    )
    assert detail.status_code == 200, detail.text
    assert len(detail.json()["source_observations"]) == 2
    assert "run_id" not in detail.text
    assert "raw_json" not in detail.text


def test_incremental_snapshot_composes_base_with_its_actual_acquisition_period(
    activity_client,
):
    base_end = START + timedelta(days=1)
    refresh_start = base_end - timedelta(minutes=15)
    refresh_end = base_end + timedelta(hours=6)
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        base_run, base_sync = _run_and_sync(
            session,
            wallet_case,
            start=START,
            end=base_end,
        )
        base_run.transactions.append(
            _transaction(
                base_run,
                tx_hash="a1" * 32,
                logical_time="101",
                timestamp=START + timedelta(hours=1),
            )
        )
        refresh_run, refresh_sync = _run_and_sync(
            session,
            wallet_case,
            start=refresh_start,
            end=refresh_end,
            coverage_state="bounded_partial",
        )
        refresh_run.transactions.append(
            _transaction(
                refresh_run,
                tx_hash="a2" * 32,
                logical_time="102",
                timestamp=base_end + timedelta(hours=1),
            )
        )
        refresh_sync.requested_start = START
        refresh_sync.coverage_summary_json = json.dumps(
            {
                "state": "bounded_partial",
                "requested_start_at": _iso(START),
                "requested_end_at": _iso(refresh_end),
                "requested_surfaces": ["transactions"],
                "unavailable_surfaces": [],
                "incomplete_surfaces": [],
                "streams": [],
                "full_history_proven": False,
                "_acquisition": {
                    "version": 1,
                    "mode": "incremental",
                    "start_at": _iso(refresh_start),
                    "end_at": _iso(refresh_end),
                    "overlap_seconds": 900,
                    "base_snapshot_public_id": base_sync.public_id,
                },
            }
        )
        case_id, snapshot_id = wallet_case.public_id, refresh_sync.public_id
        session.commit()

    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [item["logical_time"] for item in body["items"]] == ["102", "101"]
    assert body["aggregate"]["source_sync_count"] == 2
    assert body["snapshot"]["public_id"] == snapshot_id
    assert body["snapshot"]["requested_period"] == {
        "start_at": _iso(START),
        "end_at": _iso(refresh_end),
    }


def test_same_identity_with_changed_semantics_is_omitted_fail_closed(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        first_run, _ = _run_and_sync(session, wallet_case, end=END)
        first_run.transactions.append(
            _transaction(
                first_run,
                tx_hash="bb" * 32,
                logical_time="200",
                timestamp=START + timedelta(hours=2),
                fee="0.1",
            )
        )
        second_run, snapshot = _run_and_sync(
            session, wallet_case, end=END + timedelta(seconds=1)
        )
        second_run.transactions.append(
            _transaction(
                second_run,
                tx_hash="bb" * 32,
                logical_time="200",
                timestamp=START + timedelta(hours=2),
                fee="0.2",
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["items"] == []
    assert body["aggregate"]["conflicted_identity_count"] == 1
    assert "identity_semantic_conflict" in {gap["code"] for gap in body["gaps"]}


def test_identity_unavailable_observations_are_never_cross_sync_deduplicated(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        first_run, _ = _run_and_sync(session, wallet_case, end=END)
        first_run.transactions.append(
            _unavailable_transaction(
                first_run,
                tx_hash="not-canonical",
                timestamp=START + timedelta(hours=1),
            )
        )
        second_run, snapshot = _run_and_sync(
            session, wallet_case, end=END + timedelta(seconds=1)
        )
        second_run.transactions.append(
            _unavailable_transaction(
                second_run,
                tx_hash="not-canonical",
                timestamp=START + timedelta(hours=1),
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["aggregate"]["total_items"] == 2
    assert body["aggregate"]["suppressed_duplicate_observations"] == 0
    assert len({item["public_id"] for item in body["items"]}) == 2
    assert all(
        item["provenance"]["identity_assurance"] == "unavailable"
        and item["provenance"]["observation_count"] == 1
        for item in body["items"]
    )


def test_same_symbol_different_contracts_keep_distinct_asset_ids_and_filter(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(
            session,
            wallet_case,
            status="partial",
            surfaces=["transfers"],
            coverage_state="bounded_partial",
        )
        run.transfers.extend(
            [
                _transfer(
                    run,
                    event_id="cc" * 32,
                    logical_time="300",
                    action_index=0,
                    contract=JETTON_A,
                ),
                _transfer(
                    run,
                    event_id="dd" * 32,
                    logical_time="301",
                    action_index=1,
                    contract=JETTON_B,
                ),
            ]
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 2
    asset_ids = {item["assets"][0]["asset_id"] for item in items}
    assert None not in asset_ids and len(asset_ids) == 2
    selected = next(iter(asset_ids))
    filtered = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&asset_id={selected}"
    )
    assert filtered.status_code == 200, filtered.text
    assert filtered.json()["aggregate"]["total_items"] == 1
    assert filtered.json()["items"][0]["assets"][0]["asset_id"] == selected


def test_cursor_is_stable_filter_bound_and_tamper_evident(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        for index in range(3):
            run.transactions.append(
                _transaction(
                    run,
                    tx_hash=f"{index + 1:02x}" * 32,
                    logical_time=str(400 + index),
                    timestamp=START + timedelta(hours=index + 1),
                )
            )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    first = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&kind=transaction&limit=1"
    )
    assert first.status_code == 200, first.text
    cursor = first.json()["page"]["next_cursor"]
    assert cursor
    second = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&kind=transaction&limit=1&cursor={cursor}"
    )
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["public_id"] != first.json()["items"][0]["public_id"]
    mismatch = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&kind=swap&limit=1&cursor={cursor}"
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "invalid_activity_cursor"
    tampered = f"{cursor[:-1]}{'0' if cursor[-1] != '0' else '1'}"
    bad = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&kind=transaction&limit=1&cursor={tampered}"
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "invalid_activity_cursor"


def test_live_swap_native_discriminator_does_not_trust_jetton_symbol(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(
            session,
            wallet_case,
            status="partial",
            surfaces=["swaps"],
            coverage_state="bounded_partial",
        )
        run.swaps.extend(
            [
                _swap(
                    run,
                    event_id="f1" * 32,
                    action_index=0,
                    token_in_standard="native",
                    token_in_address=None,
                ),
                _swap(
                    run,
                    event_id="f2" * 32,
                    action_index=1,
                    token_in_standard="jetton",
                    token_in_address=None,
                ),
            ]
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&kind=swap&sort=oldest"
    )
    assert response.status_code == 200, response.text
    first, second = response.json()["items"]
    assert first["assets"][0]["standard"] == "native"
    assert first["assets"][0]["asset_id"] is not None
    assert second["assets"][0] == {
        "role": "in",
        "asset_id": None,
        "identity_status": "unavailable",
        "network": "ton-mainnet",
        "standard": "unknown",
        "contract_address": None,
        "symbol": "TON",
    }


def test_ton_transfer_with_jetton_master_is_omitted_fail_closed(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(
            session,
            wallet_case,
            status="partial",
            surfaces=["transfers"],
            coverage_state="bounded_partial",
        )
        run.transfers.append(
            _transfer(
                run,
                event_id="f4" * 32,
                logical_time="650",
                action_index=0,
                contract=JETTON_A,
                symbol="TON",
                action_type="TonTransfer",
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert "source_provenance_mismatch" in {
        gap["code"] for gap in response.json()["gaps"]
    }


def test_negative_normalized_value_is_omitted_not_published(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        run.transactions.append(
            _transaction(
                run,
                tx_hash="f5" * 32,
                logical_time="651",
                timestamp=START + timedelta(hours=1),
                fee="-0.1",
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert "source_provenance_mismatch" in {
        gap["code"] for gap in response.json()["gaps"]
    }


def test_coverage_surface_gap_respects_kind_filter(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        _run, snapshot = _run_and_sync(
            session,
            wallet_case,
            status="partial",
            surfaces=["swaps"],
            coverage_state="bounded_partial",
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    transaction_view = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&kind=transaction"
    )
    assert transaction_view.status_code == 200, transaction_view.text
    assert "surface_incomplete" not in {
        gap["code"] for gap in transaction_view.json()["gaps"]
    }
    for structural_filter in ("outcome=failed", "direction=in"):
        unrelated = activity_client.get(
            f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&{structural_filter}"
        )
        assert unrelated.status_code == 200, unrelated.text
        assert "surface_incomplete" not in {
            gap["code"] for gap in unrelated.json()["gaps"]
        }
    swap_view = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&kind=swap"
    )
    assert swap_view.status_code == 200, swap_view.text
    assert "surface_incomplete" in {
        gap["code"] for gap in swap_view.json()["gaps"]
    }
    protocol_view = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&protocol_id=stonfi_v2"
    )
    assert protocol_view.status_code == 200, protocol_view.text
    assert "surface_incomplete" in {
        gap["code"] for gap in protocol_view.json()["gaps"]
    }
    excluded_origin = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "data_origin": "demo_fixture"},
    )
    assert excluded_origin.status_code == 200, excluded_origin.text
    assert excluded_origin.json()["aggregate"]["source_sync_count"] == 0
    assert "surface_incomplete" not in {
        gap["code"] for gap in excluded_origin.json()["gaps"]
    }


def test_detail_requires_explicit_snapshot(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        run.transactions.append(
            _transaction(
                run,
                tx_hash="ee" * 32,
                logical_time="500",
                timestamp=START + timedelta(hours=1),
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    listed = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    ).json()
    item_id = listed["items"][0]["public_id"]
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity/{item_id}"
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_activity_query"


def test_explicit_period_must_stay_inside_pinned_snapshot(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        _run, snapshot = _run_and_sync(session, wallet_case)
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={
            "snapshot": snapshot_id,
            "from_at": _iso(START - timedelta(seconds=1)),
            "to_at": _iso(END),
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_activity_query"


def test_friendly_counterparty_filter_must_match_case_network(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        case_id = wallet_case.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"counterparty": TESTNET_COUNTERPARTY},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_activity_query"


def test_invalid_pinned_snapshot_scope_fails_closed(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        run.wallet_network = "ton-testnet"
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "activity_snapshot_invalid",
        "message_safe": (
            "The pinned snapshot failed its Wallet Case source-scope contract."
        ),
        "retryable": False,
    }


def test_live_rows_must_belong_to_their_own_source_sync_period(activity_client):
    narrow_end = START + timedelta(hours=2)
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        narrow_run, _narrow_sync = _run_and_sync(
            session,
            wallet_case,
            end=narrow_end,
        )
        narrow_run.transactions.extend(
            [
                _transaction(
                    narrow_run,
                    tx_hash="f6" * 32,
                    logical_time="660",
                    timestamp=narrow_end,
                ),
                _transaction(
                    narrow_run,
                    tx_hash="f7" * 32,
                    logical_time="661",
                    timestamp=narrow_end + timedelta(hours=1),
                ),
            ]
        )
        wide_run, snapshot = _run_and_sync(
            session,
            wallet_case,
            end=END + timedelta(seconds=1),
        )
        wide_run.transactions.append(
            _transaction(
                wide_run,
                tx_hash="f8" * 32,
                logical_time="662",
                timestamp=START + timedelta(hours=1),
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    assert [item["logical_time"] for item in response.json()["items"]] == ["662"]
    assert "source_provenance_mismatch" in {
        gap["code"] for gap in response.json()["gaps"]
    }


def test_row_kind_must_be_requested_by_its_source_sync(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(
            session,
            wallet_case,
            surfaces=["transactions"],
        )
        run.swaps.append(
            _swap(
                run,
                event_id="f9" * 32,
                action_index=0,
                token_in_standard="native",
                token_in_address=None,
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    swap_view = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "kind": "swap"},
    )
    assert swap_view.status_code == 200, swap_view.text
    assert swap_view.json()["items"] == []
    assert "source_scope_mismatch" in {
        gap["code"] for gap in swap_view.json()["gaps"]
    }
    transaction_view = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "kind": "transaction"},
    )
    assert transaction_view.status_code == 200, transaction_view.text
    assert "source_scope_mismatch" not in {
        gap["code"] for gap in transaction_view.json()["gaps"]
    }


def test_unknown_stored_coverage_is_explicit(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        _run, snapshot = _run_and_sync(session, wallet_case)
        snapshot.coverage_summary_json = "{}"
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["snapshot"]["coverage"]["state"] == "unknown"
    assert "coverage_unavailable" in {gap["code"] for gap in body["gaps"]}
    assert "coverage_unavailable" in {
        limitation["code"] for limitation in body["limitations"]
    }


def test_source_sync_bound_refuses_partial_activity(monkeypatch, activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        _run_and_sync(session, wallet_case, end=END)
        _run, snapshot = _run_and_sync(
            session, wallet_case, end=END + timedelta(seconds=1)
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    monkeypatch.setattr("services.wallet_case_activity.MAX_SOURCE_SYNCS", 1)
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "activity_scope_too_large"
    assert "items" not in response.text


def test_wrong_case_cursor_is_invalid_before_snapshot_lookup(activity_client):
    with app.state.activity_test_sessions() as session:
        first_case = _case(session)
        first_run, first_snapshot = _run_and_sync(session, first_case)
        for index in range(2):
            first_run.transactions.append(
                _transaction(
                    first_run,
                    tx_hash=f"a{index}" * 32,
                    logical_time=str(700 + index),
                    timestamp=START + timedelta(hours=index + 1),
                )
            )
        second_case = _case(session, account=f"0:{'44' * 32}")
        first_id, snapshot_id = first_case.public_id, first_snapshot.public_id
        second_id = second_case.public_id
        session.commit()
    first = activity_client.get(
        f"/api/v1/cases/{first_id}/activity?snapshot={snapshot_id}&limit=1"
    ).json()
    response = activity_client.get(
        f"/api/v1/cases/{second_id}/activity?cursor={first['page']['next_cursor']}"
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_activity_cursor"


@pytest.mark.parametrize(
    "query",
    [
        "unknown=value",
        "limit=01",
        "limit=101",
        "sort=newest&sort=oldest",
        "kind=transaction&kind=transaction",
        "from_at=2026-08-01T00:00:00Z",
        f"cursor={'x' * 1025}",
    ],
)
def test_activity_query_rejects_unknown_duplicate_or_oversized_values(
    activity_client,
    query,
):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        case_id = wallet_case.public_id
        session.commit()
    response = activity_client.get(f"/api/v1/cases/{case_id}/activity?{query}")
    assert response.status_code == 422
    assert response.json()["detail"]["code"] in {
        "invalid_activity_query",
        "invalid_activity_cursor",
    }


@pytest.mark.parametrize(
    "from_at",
    (
        "2026-08-01 00:00:00Z",
        "2026-08-01T00:00:00.1234567Z",
        "2026-08-01T00:00:00",
        "2026-02-30T00:00:00Z",
        "2026-08-01T24:00:00Z",
        "2026-08-01T00:00:00+0000",
        "0001-01-01T00:00:00+23:00",
    ),
)
def test_activity_period_requires_strict_rfc3339(
    activity_client,
    from_at,
):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        case_id = wallet_case.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"from_at": from_at, "to_at": "2026-08-02T00:00:00Z"},
    )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_activity_query"


def test_same_and_missing_timestamps_paginate_without_repeats(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        rows = [
            _transaction(
                run,
                tx_hash=f"b{index}" * 32,
                logical_time=str(800 + index),
                timestamp=START + timedelta(hours=1),
            )
            for index in range(2)
        ]
        missing = _transaction(
            run,
            tx_hash="bf" * 32,
            logical_time="899",
            timestamp=START + timedelta(hours=2),
        )
        missing.timestamp = None
        missing_raw = json.loads(missing.raw_json)
        missing_raw["utime"] = None
        missing.raw_json = json.dumps(missing_raw)
        rows.append(missing)
        run.transactions.extend(rows)
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    cursor = None
    seen = []
    for _ in range(3):
        params = {"snapshot": snapshot_id, "limit": "1"}
        if cursor:
            params["cursor"] = cursor
        response = activity_client.get(
            f"/api/v1/cases/{case_id}/activity", params=params
        )
        assert response.status_code == 200, response.text
        seen.append(response.json()["items"][0]["public_id"])
        cursor = response.json()["page"]["next_cursor"]
    assert len(set(seen)) == 3
    assert cursor is None


@pytest.mark.parametrize(
    ("sort", "expected_first"),
    (("oldest", "whole"), ("newest", "fractional")),
)
def test_fractional_timestamp_sort_and_observed_period_are_chronological(
    activity_client,
    sort,
    expected_first,
):
    whole = START + timedelta(seconds=1)
    fractional = whole + timedelta(microseconds=100_000)
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        run.transactions.extend(
            [
                _transaction(
                    run,
                    tx_hash="b1" * 32,
                    logical_time="810",
                    timestamp=whole,
                ),
                _transaction(
                    run,
                    tx_hash="b2" * 32,
                    logical_time="811",
                    timestamp=fractional,
                ),
            ]
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    first = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "sort": sort, "limit": "1"},
    )
    assert first.status_code == 200, first.text
    first_body = first.json()
    expected_time = whole if expected_first == "whole" else fractional
    assert first_body["items"][0]["occurred_at"] == _iso(expected_time)
    second = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={
            "snapshot": snapshot_id,
            "sort": sort,
            "limit": "1",
            "cursor": first_body["page"]["next_cursor"],
        },
    )
    assert second.status_code == 200, second.text
    assert second.json()["items"][0]["public_id"] != first_body["items"][0]["public_id"]
    assert first_body["observed_period"] == {
        "start_at": _iso(whole),
        "end_at": _iso(fractional + timedelta(microseconds=1)),
    }


@pytest.mark.parametrize(
    "logical_time",
    ("01", str(2**64), "not-a-logical-time"),
)
def test_unavailable_noncanonical_logical_time_is_sanitized_to_null(
    activity_client,
    logical_time,
):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        row = _unavailable_transaction(
            run,
            tx_hash="not-canonical",
            timestamp=START + timedelta(hours=1),
        )
        row.logical_time = logical_time
        raw = json.loads(row.raw_json)
        raw["logical_time"] = logical_time
        row.raw_json = json.dumps(raw)
        run.transactions.append(row)
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"][0]["logical_time"] is None


def test_cursor_keeps_snapshot_when_new_sync_publishes_between_pages(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        for index in range(2):
            run.transactions.append(
                _transaction(
                    run,
                    tx_hash=f"c{index}" * 32,
                    logical_time=str(900 + index),
                    timestamp=START + timedelta(hours=index + 1),
                )
            )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    first = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&limit=1"
    ).json()
    with app.state.activity_test_sessions() as session:
        wallet_case = session.query(WalletCase).filter_by(public_id=case_id).one()
        new_run, _new_snapshot = _run_and_sync(
            session, wallet_case, end=END + timedelta(seconds=2)
        )
        new_run.transactions.append(
            _transaction(
                new_run,
                tx_hash="cf" * 32,
                logical_time="999",
                timestamp=START + timedelta(hours=3),
            )
        )
        session.commit()
    second = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"limit": "1", "cursor": first["page"]["next_cursor"]},
    )
    assert second.status_code == 200, second.text
    assert second.json()["snapshot"]["public_id"] == snapshot_id
    assert second.json()["aggregate"]["total_items"] == 2


def test_conflict_diagnostic_respects_kind_filter(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        first_run, _ = _run_and_sync(session, wallet_case, end=END)
        first_run.transactions.append(
            _transaction(
                first_run,
                tx_hash="d1" * 32,
                logical_time="1000",
                timestamp=START + timedelta(hours=1),
                fee="1",
            )
        )
        second_run, snapshot = _run_and_sync(
            session, wallet_case, end=END + timedelta(seconds=1)
        )
        second_run.transactions.append(
            _transaction(
                second_run,
                tx_hash="d1" * 32,
                logical_time="1000",
                timestamp=START + timedelta(hours=1),
                fee="2",
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}&kind=swap"
    )
    assert response.status_code == 200, response.text
    assert response.json()["aggregate"]["conflicted_identity_count"] == 0
    assert "identity_semantic_conflict" not in {
        gap["code"] for gap in response.json()["gaps"]
    }


def test_cross_surface_conflict_is_scoped_by_any_group_candidate(activity_client):
    event_id = "d2" * 32
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(
            session,
            wallet_case,
            status="partial",
            surfaces=["transfers", "swaps"],
            coverage_state="bounded_partial",
        )
        run.transfers.append(
            _transfer(
                run,
                event_id=event_id,
                logical_time="600",
                action_index=0,
                contract=JETTON_A,
            )
        )
        run.swaps.append(
            _swap(
                run,
                event_id=event_id,
                action_index=0,
                token_in_standard="native",
                token_in_address=None,
                logical_time="600",
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    for kind in ("transfer", "swap"):
        response = activity_client.get(
            f"/api/v1/cases/{case_id}/activity",
            params={"snapshot": snapshot_id, "kind": kind},
        )
        assert response.status_code == 200, response.text
        assert response.json()["aggregate"]["conflicted_identity_count"] == 1
        assert "identity_semantic_conflict" in {
            gap["code"] for gap in response.json()["gaps"]
        }
    inbound = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "direction": "in"},
    ).json()
    assert inbound["aggregate"]["conflicted_identity_count"] == 1
    outbound = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "direction": "out"},
    ).json()
    assert outbound["aggregate"]["conflicted_identity_count"] == 0
    assert "identity_semantic_conflict" not in {
        gap["code"] for gap in outbound["gaps"]
    }


def test_null_timestamp_conflict_keeps_explicit_period_gap(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        first_run, _ = _run_and_sync(session, wallet_case, end=END)
        first = _transaction(
            first_run,
            tx_hash="d6" * 32,
            logical_time="1060",
            timestamp=START + timedelta(hours=1),
            fee="1",
        )
        first.timestamp = None
        first_raw = json.loads(first.raw_json)
        first_raw["utime"] = None
        first.raw_json = json.dumps(first_raw)
        first_run.transactions.append(first)
        second_run, snapshot = _run_and_sync(
            session,
            wallet_case,
            end=END + timedelta(seconds=1),
        )
        second = _transaction(
            second_run,
            tx_hash="d6" * 32,
            logical_time="1060",
            timestamp=START + timedelta(hours=1),
            fee="2",
        )
        second.timestamp = None
        second_raw = json.loads(second.raw_json)
        second_raw["utime"] = None
        second.raw_json = json.dumps(second_raw)
        second_run.transactions.append(second)
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    response = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={
            "snapshot": snapshot_id,
            "from_at": _iso(START),
            "to_at": _iso(END),
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["items"] == []
    assert response.json()["aggregate"]["conflicted_identity_count"] == 0
    assert "activity_timestamp_unavailable" in {
        gap["code"] for gap in response.json()["gaps"]
    }


def test_nonconflict_diagnostics_respect_selected_kind(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(
            session,
            wallet_case,
            status="partial",
            surfaces=["transactions", "swaps"],
            coverage_state="bounded_partial",
        )
        run.transactions.append(
            _unavailable_transaction(
                run,
                tx_hash="not-canonical",
                timestamp=START + timedelta(hours=1),
            )
        )
        missing = _transaction(
            run,
            tx_hash="d3" * 32,
            logical_time="1050",
            timestamp=START + timedelta(hours=1),
        )
        missing.timestamp = None
        missing_raw = json.loads(missing.raw_json)
        missing_raw["utime"] = None
        missing.raw_json = json.dumps(missing_raw)
        run.transactions.append(missing)
        run.swaps.append(
            _swap(
                run,
                event_id="d4" * 32,
                action_index=0,
                token_in_standard="jetton",
                token_in_address=None,
            )
        )
        corrupt = _swap(
            run,
            event_id="d5" * 32,
            action_index=1,
            token_in_standard="native",
            token_in_address=None,
        )
        corrupt_raw = json.loads(corrupt.raw_json)
        corrupt_raw["source"] = "corrupt"
        corrupt.raw_json = json.dumps(corrupt_raw)
        run.swaps.append(corrupt)
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    transaction = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "kind": "transaction"},
    )
    assert transaction.status_code == 200, transaction.text
    transaction_codes = {gap["code"] for gap in transaction.json()["gaps"]}
    assert "activity_identity_unavailable" in transaction_codes
    assert "activity_timestamp_unavailable" in transaction_codes
    assert "asset_identity_unavailable" not in transaction_codes
    assert "source_provenance_mismatch" not in transaction_codes
    assert "surface_incomplete" not in transaction_codes

    swap = activity_client.get(
        f"/api/v1/cases/{case_id}/activity",
        params={"snapshot": snapshot_id, "kind": "swap"},
    )
    assert swap.status_code == 200, swap.text
    swap_codes = {gap["code"] for gap in swap.json()["gaps"]}
    assert "asset_identity_unavailable" in swap_codes
    assert "source_provenance_mismatch" in swap_codes
    assert "surface_incomplete" in swap_codes
    assert "activity_identity_unavailable" not in swap_codes
    assert "activity_timestamp_unavailable" not in swap_codes
    assert "transaction_outcome_not_raw_revalidated" not in {
        item["code"] for item in swap.json()["limitations"]
    }
    assert "transaction_outcome_not_raw_revalidated" in {
        item["code"] for item in transaction.json()["limitations"]
    }


def test_activity_inherits_local_only_host_boundary(activity_client):
    remote = TestClient(app, client=("127.0.0.1", 49152))
    try:
        response = remote.get(
            f"/api/v1/cases/{uuid4()}/activity",
            headers={
                "Host": "attacker.example:8000",
                "Origin": "http://attacker.example:8000",
            },
        )
    finally:
        remote.close()
    assert response.status_code == 403
    assert "local-only" in response.json()["detail"]


def test_activity_response_recursively_excludes_internal_and_raw_keys(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        run, snapshot = _run_and_sync(session, wallet_case)
        run.transactions.append(
            _transaction(
                run,
                tx_hash="e1" * 32,
                logical_time="1100",
                timestamp=START + timedelta(hours=1),
            )
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    body = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={snapshot_id}"
    ).json()
    forbidden = {
        "id",
        "run_id",
        "ingestion_run_id",
        "raw",
        "raw_json",
        "case_id",
        "lease_token",
        "checkpoint_json",
    }

    def keys(value):
        if isinstance(value, dict):
            yield from value.keys()
            for child in value.values():
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert forbidden.isdisjoint(set(keys(body)))


def test_activity_query_count_does_not_grow_with_source_sync_count(activity_client):
    engine = app.state.activity_test_engine
    counts = []
    case_ids = []
    for source_count, account_byte in ((1, "11"), (5, "44")):
        with app.state.activity_test_sessions() as session:
            wallet_case = _case(session, account=f"0:{account_byte * 32}")
            snapshot = None
            for index in range(source_count):
                run, snapshot = _run_and_sync(
                    session,
                    wallet_case,
                    end=END + timedelta(seconds=index),
                )
                run.transactions.append(
                    _transaction(
                        run,
                        tx_hash=f"{source_count:02x}{index:02x}" * 16,
                        logical_time=str(1200 + index),
                        timestamp=START + timedelta(hours=1),
                    )
                )
            assert snapshot is not None
            case_ids.append((wallet_case.public_id, snapshot.public_id))
            session.commit()
        counter = {"value": 0}

        def before_cursor(*_args):
            counter["value"] += 1

        event.listen(engine, "before_cursor_execute", before_cursor)
        try:
            response = activity_client.get(
                f"/api/v1/cases/{case_ids[-1][0]}/activity",
                params={"snapshot": case_ids[-1][1]},
            )
            assert response.status_code == 200, response.text
        finally:
            event.remove(engine, "before_cursor_execute", before_cursor)
        counts.append(counter["value"])
    assert counts[0] == counts[1]


def test_source_sync_count_is_selected_activity_basis(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        _run_and_sync(
            session,
            wallet_case,
            surfaces=["transactions"],
            end=END,
        )
        _run_and_sync(
            session,
            wallet_case,
            surfaces=["swaps"],
            end=END + timedelta(seconds=1),
        )
        _run, snapshot = _run_and_sync(
            session,
            wallet_case,
            surfaces=["balances"],
            end=END + timedelta(seconds=2),
        )
        case_id, snapshot_id = wallet_case.public_id, snapshot.public_id
        session.commit()
    expected = (
        ({}, 2),
        ({"kind": "transaction"}, 1),
        ({"kind": "swap"}, 1),
        ({"data_origin": "demo_fixture"}, 0),
    )
    for extra, count in expected:
        response = activity_client.get(
            f"/api/v1/cases/{case_id}/activity",
            params={"snapshot": snapshot_id, **extra},
        )
        assert response.status_code == 200, response.text
        assert response.json()["aggregate"]["source_sync_count"] == count


def test_detail_wrong_snapshot_or_item_is_scoped_not_found(activity_client):
    with app.state.activity_test_sessions() as session:
        wallet_case = _case(session)
        first_run, first_snapshot = _run_and_sync(session, wallet_case, end=END)
        first_run.transactions.append(
            _transaction(
                first_run,
                tx_hash="f3" * 32,
                logical_time="1300",
                timestamp=START + timedelta(hours=1),
            )
        )
        _second_run, _second_snapshot = _run_and_sync(
            session, wallet_case, end=END + timedelta(seconds=1)
        )
        case_id = wallet_case.public_id
        first_snapshot_id = first_snapshot.public_id
        session.commit()
    listed = activity_client.get(
        f"/api/v1/cases/{case_id}/activity?snapshot={first_snapshot_id}"
    ).json()
    item_id = listed["items"][0]["public_id"]
    wrong_item = activity_client.get(
        f"/api/v1/cases/{case_id}/activity/{'act_' + '0' * 64}",
        params={"snapshot": first_snapshot_id},
    )
    assert wrong_item.status_code == 404
    assert wrong_item.json()["detail"]["code"] == "activity_not_found"
    wrong_snapshot = activity_client.get(
        f"/api/v1/cases/{case_id}/activity/{item_id}",
        params={"snapshot": str(uuid4())},
    )
    assert wrong_snapshot.status_code == 404
    assert wrong_snapshot.json()["detail"]["code"] == "activity_snapshot_not_found"


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _zero_summary() -> dict:
    return {
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
    }
