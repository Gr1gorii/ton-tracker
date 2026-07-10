"""Endpoint and service tests for finalized persisted trace evidence."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest
from fastapi.testclient import TestClient
from pytoniq_core import Address, Builder
from pytoniq_core.tlb.transaction import ExternalMsgInfo, MessageAny
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from adapters.tonapi import TonapiAdapter
from config import DEFAULT_TONAPI_BASE_URL, ProviderResult
from database import Base, get_session
from main import app
from models import (
    WalletIngestionRun,
    WalletTraceBocTransaction,
    WalletTraceBocVerification,
    WalletTraceEvidenceCapture,
    WalletTraceEvidenceMessage,
    WalletTraceEvidenceNode,
    WalletTransaction,
)
from schemas import (
    WalletPersistedTraceEvidenceResponse,
    WalletNativeTonFlowObservationsResponse,
    WalletTraceBocMessageEvidenceResponse,
    WalletTraceBocVerificationResponse,
)
import services.wallet_trace_boc_verification as boc_service
import services.wallet_native_ton_flow_observations as native_flow_service
from services.wallet_trace_boc_verification import (
    WalletTraceBocVerificationConflict,
)
from services.ton_transaction_identity import derive_ton_transaction_identity


ROOT_HASH = "11" * 32
CHILD_HASH = "22" * 32
ROOT_ACCOUNT = "0:" + "33" * 32
CHILD_ACCOUNT = "0:" + "44" * 32
ROOT_IN_HASH = "55" * 32
CHILD_IN_HASH = "66" * 32
ROOT_OUT_HASH = "77" * 32
ROOT_LT = "89156526000001"
CHILD_LT = "89156526000003"
PERSISTED_CONTRACT = "tonapi_low_level_trace_evidence_v1"


def _observation_key(
    preorder: int,
    role: str,
    ordinal: int,
    message_hash: str,
) -> str:
    return "|".join(
        (
            "tonapi_trace_message_obs_v1",
            "ton-mainnet",
            ROOT_HASH,
            str(preorder),
            role,
            str(ordinal),
            message_hash,
        )
    )


def _normalized_message(
    *,
    preorder: int,
    role: str,
    ordinal: int,
    message_hash: str,
    message_type: str,
    source: str | None,
    destination: str | None,
) -> dict:
    return {
        "role": role,
        "ordinal": ordinal,
        "message_hash": message_hash,
        "message_type": message_type,
        "source_account_canonical": source,
        "destination_account_canonical": destination,
        "created_logical_time": "0" if role == "root_inbound" else ROOT_LT,
        "unix_time": 1_717_236_000,
        "value_nanoton": "1000000000",
        "forward_fee_nanoton": "15",
        "ihr_fee_nanoton": "0",
        "import_fee_nanoton": "0",
        "ihr_disabled": True,
        "bounce": False,
        "bounced": False,
        "observation_identity_key": _observation_key(
            preorder,
            role,
            ordinal,
            message_hash,
        ),
    }


def _normalized_finalized_candidate() -> dict:
    root_in = _normalized_message(
        preorder=0,
        role="root_inbound",
        ordinal=0,
        message_hash=ROOT_IN_HASH,
        message_type="ext_in_msg",
        source=None,
        destination=ROOT_ACCOUNT,
    )
    root_out = _normalized_message(
        preorder=0,
        role="remaining_outbound",
        ordinal=0,
        message_hash=ROOT_OUT_HASH,
        message_type="ext_out_msg",
        source=ROOT_ACCOUNT,
        destination=None,
    )
    child_in = _normalized_message(
        preorder=1,
        role="child_inbound",
        ordinal=0,
        message_hash=CHILD_IN_HASH,
        message_type="int_msg",
        source=ROOT_ACCOUNT,
        destination=CHILD_ACCOUNT,
    )
    summary = {
        "root_transaction_hash": ROOT_HASH,
        "transaction_count": 2,
        "max_depth": 1,
        "message_count": 3,
        "root_inbound_message_count": 1,
        "child_internal_message_count": 1,
        "remaining_out_message_count": 1,
        "internal_message_count": 1,
        "external_in_message_count": 1,
        "external_out_message_count": 1,
        "successful_transaction_count": 1,
        "failed_transaction_count": 1,
        "aborted_transaction_count": 1,
        "unique_account_count": 2,
    }
    return {
        "trace_state": "finalized",
        "anchor": {
            "transaction_hash": ROOT_HASH,
            "logical_time": ROOT_LT,
            "account_canonical": ROOT_ACCOUNT,
        },
        "summary": summary,
        "nodes": [
            {
                "preorder_index": 0,
                "parent_preorder_index": None,
                "depth": 0,
                "transaction_hash": ROOT_HASH,
                "account_canonical": ROOT_ACCOUNT,
                "logical_time": ROOT_LT,
                "unix_time": 1_717_236_000,
                "success": True,
                "aborted": False,
                "in_message": root_in,
                "out_messages": [root_out],
            },
            {
                "preorder_index": 1,
                "parent_preorder_index": 0,
                "depth": 1,
                "transaction_hash": CHILD_HASH,
                "account_canonical": CHILD_ACCOUNT,
                "logical_time": CHILD_LT,
                "unix_time": 1_717_236_001,
                "success": False,
                "aborted": True,
                "in_message": child_in,
                "out_messages": [],
            },
        ],
    }


def _normalized_non_preorder_candidate() -> dict:
    candidate = _normalized_finalized_candidate()
    extra_hashes = ["88" * 32, "99" * 32]
    extra_accounts = ["0:" + "aa" * 32, "0:" + "bb" * 32]
    extra_lts = ["89156526000005", "89156526000007"]
    child_b_message = _normalized_message(
        preorder=2,
        role="child_inbound",
        ordinal=0,
        message_hash="cc" * 32,
        message_type="int_msg",
        source=ROOT_ACCOUNT,
        destination=extra_accounts[0],
    )
    grandchild_message = _normalized_message(
        preorder=3,
        role="child_inbound",
        ordinal=0,
        message_hash="dd" * 32,
        message_type="int_msg",
        source=CHILD_ACCOUNT,
        destination=extra_accounts[1],
    )
    candidate["nodes"].extend(
        [
            {
                "preorder_index": 2,
                "parent_preorder_index": 0,
                "depth": 1,
                "transaction_hash": extra_hashes[0],
                "account_canonical": extra_accounts[0],
                "logical_time": extra_lts[0],
                "unix_time": 1_717_236_002,
                "success": True,
                "aborted": False,
                "in_message": child_b_message,
                "out_messages": [],
            },
            {
                "preorder_index": 3,
                "parent_preorder_index": 1,
                "depth": 2,
                "transaction_hash": extra_hashes[1],
                "account_canonical": extra_accounts[1],
                "logical_time": extra_lts[1],
                "unix_time": 1_717_236_003,
                "success": True,
                "aborted": False,
                "in_message": grandchild_message,
                "out_messages": [],
            },
        ]
    )
    candidate["summary"].update(
        {
            "transaction_count": 4,
            "max_depth": 2,
            "message_count": 5,
            "child_internal_message_count": 3,
            "internal_message_count": 3,
            "successful_transaction_count": 3,
            "failed_transaction_count": 1,
            "aborted_transaction_count": 1,
            "unique_account_count": 4,
        }
    )
    return candidate


def _seed_eligible_run(testing_session) -> int:
    raw = {
        "provider": "tonapi",
        "surface": "transactions",
        "tx_hash": ROOT_HASH,
        "logical_time": ROOT_LT,
    }
    run = WalletIngestionRun(
        wallet_address=ROOT_ACCOUNT,
        wallet_identity_status="network_scoped",
        wallet_identity_version="ton_raw_address_v1",
        wallet_network="ton-mainnet",
        wallet_address_canonical=ROOT_ACCOUNT,
        wallet_workchain_id=0,
        wallet_account_id_hex="33" * 32,
        wallet_address_format="raw",
        time_window="24h",
        data_mode="real",
        status="success",
        requested_surfaces_json='["transactions"]',
        provider_summary_json="{}",
    )
    identity = derive_ton_transaction_identity(
        network=run.wallet_network,
        account_address_canonical=run.wallet_address_canonical,
        account_identity_status=run.wallet_identity_status,
        account_identity_version=run.wallet_identity_version,
        account_workchain_id=run.wallet_workchain_id,
        account_id_hex=run.wallet_account_id_hex,
        logical_time=ROOT_LT,
        transaction_hash=ROOT_HASH,
        data_mode=run.data_mode,
        source_status="live",
        provider="tonapi",
        raw=raw,
    )
    run.transactions.append(
        WalletTransaction(
            tx_hash=ROOT_HASH,
            logical_time=ROOT_LT,
            success="success",
            provider="tonapi",
            source_status="live",
            raw_json=json.dumps(raw, separators=(",", ":")),
            transaction_identity_status=identity.status,
            transaction_identity_version=identity.version,
            transaction_network=identity.network,
            transaction_account_canonical=identity.account_canonical,
            transaction_logical_time_canonical=identity.logical_time_canonical,
            transaction_hash_canonical=identity.hash_canonical,
            transaction_identity_key=identity.key,
        )
    )
    session = testing_session()
    try:
        session.add(run)
        session.commit()
        return run.id
    finally:
        session.close()


def _seed_capture_slots(testing_session, run_id: int, slots: list[int]) -> None:
    with testing_session() as session:
        transaction = session.scalar(
            select(WalletTransaction).where(WalletTransaction.run_id == run_id)
        )
        assert transaction is not None
        for position, slot in enumerate(slots):
            session.add(
                WalletTraceEvidenceCapture(
                    run_id=run_id,
                    captured_via_transaction_id=transaction.id,
                    capture_slot=slot,
                    provider="tonapi",
                    contract_version=f"test_slot_contract_{position}",
                    network="ton-mainnet",
                    root_transaction_hash=f"{position + 1:064x}",
                    trace_state="finalized",
                    transaction_count=1,
                    max_depth=0,
                    message_count=0,
                    root_inbound_message_count=0,
                    child_internal_message_count=0,
                    remaining_out_message_count=0,
                    internal_message_count=0,
                    external_in_message_count=0,
                    external_out_message_count=0,
                    successful_transaction_count=1,
                    failed_transaction_count=0,
                    aborted_transaction_count=0,
                    unique_account_count=1,
                    evidence_digest_sha256=f"{position + 17:064x}",
                    captured_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
                )
            )
        session.commit()


@pytest.fixture
def persisted_trace_client(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    testing_session = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=engine,
    )
    run_id = _seed_eligible_run(testing_session)

    def override_get_session():
        session = testing_session()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    monkeypatch.setenv("TONAPI_BASE_URL", DEFAULT_TONAPI_BASE_URL)
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_API_KEY", "persisted-trace-secret")
    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app), engine, testing_session, run_id
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


def _url(run_id: int | str, transaction_hash: str = ROOT_HASH) -> str:
    return (
        f"/api/wallets/ingest/{run_id}/transactions/{transaction_hash}"
        "/trace-evidence/persisted"
    )


def _counts(testing_session) -> tuple[int, int, int]:
    with testing_session() as session:
        return (
            session.scalar(
                select(func.count()).select_from(WalletTraceEvidenceCapture)
            ),
            session.scalar(
                select(func.count()).select_from(WalletTraceEvidenceNode)
            ),
            session.scalar(
                select(func.count()).select_from(WalletTraceEvidenceMessage)
            ),
        )


def test_persisted_trace_get_absent_is_provider_free_and_no_store(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stored read must not construct provider evidence")
        ),
    )
    response = client.get(_url(run_id))

    assert response.status_code == 404
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "Persisted trace evidence not found"}
    assert _counts(testing_session) == (0, 0, 0)


def test_persisted_trace_capture_is_atomic_idempotent_and_provider_free_on_read(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    calls: list[tuple[str, str]] = []

    def fake_capture(self, transaction_hash, network):
        calls.append((transaction_hash, network))
        return ProviderResult.success(
            _normalized_finalized_candidate(),
            source="real",
        )

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        fake_capture,
    )

    created = client.post(_url(run_id))
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    payload = created.json()
    WalletPersistedTraceEvidenceResponse.model_validate(payload)
    assert payload["contract_version"] == "tonapi_low_level_trace_evidence_v1"
    assert payload["trace_state"] == "finalized"
    assert payload["anchor"]["transaction_hash"] == ROOT_HASH
    assert payload["summary"] == _normalized_finalized_candidate()["summary"]
    assert payload["persisted_graph_revalidated"] is True
    assert payload["raw_boc_persisted"] is False
    assert payload["message_body_persisted"] is False
    assert payload["is_blockchain_proof_verified"] is False
    assert len(payload["evidence_digest_sha256"]) == 64
    assert calls == [(ROOT_HASH, "ton-mainnet")]
    assert _counts(testing_session) == (1, 2, 3)

    repeated = client.post(_url(run_id))
    assert repeated.status_code == 200
    assert repeated.headers["cache-control"] == "no-store"
    assert repeated.json() == payload
    assert calls == [(ROOT_HASH, "ton-mainnet")]
    assert _counts(testing_session) == (1, 2, 3)

    readback = client.get(_url(run_id))
    assert readback.status_code == 200
    assert readback.headers["cache-control"] == "no-store"
    assert readback.json() == payload
    assert calls == [(ROOT_HASH, "ton-mainnet")]
    assert _counts(testing_session) == (1, 2, 3)


def test_persisted_trace_capture_rejects_pending_without_write(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    pending = _normalized_finalized_candidate()
    pending["trace_state"] = "pending"

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: ProviderResult.success(pending, source="real"),
    )
    response = client.post(_url(run_id))

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "detail": "Only a finalized provider trace can be persisted."
    }
    assert _counts(testing_session) == (0, 0, 0)


def test_persisted_trace_invalid_graph_rolls_back_before_commit(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    malformed = _normalized_finalized_candidate()
    malformed["nodes"][1]["depth"] = 2

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: ProviderResult.success(
            malformed,
            source="real",
        ),
    )
    response = client.post(_url(run_id))

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "detail": "Persisted trace evidence could not be stored atomically."
    }
    assert _counts(testing_session) == (0, 0, 0)


def test_persisted_trace_rejects_non_dfs_preorder_before_commit(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    malformed = _normalized_non_preorder_candidate()

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: ProviderResult.success(
            malformed,
            source="real",
        ),
    )
    response = client.post(_url(run_id))

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert _counts(testing_session) == (0, 0, 0)


def test_persisted_trace_capture_rejects_disabled_guard_before_provider(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "false")
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("disabled capture must not call provider")
        ),
    )

    response = client.post(_url(run_id))
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert _counts(testing_session) == (0, 0, 0)


def test_persisted_trace_capture_reuses_lowest_free_slot(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    _seed_capture_slots(testing_session, run_id, [0, 2])
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: ProviderResult.success(
            _normalized_finalized_candidate(),
            source="real",
        ),
    )

    response = client.post(_url(run_id))
    assert response.status_code == 201
    with testing_session() as session:
        created = session.scalar(
            select(WalletTraceEvidenceCapture).where(
                WalletTraceEvidenceCapture.contract_version
                == PERSISTED_CONTRACT
            )
        )
        assert created is not None
        assert created.capture_slot == 1


def test_persisted_trace_capture_rejects_full_slot_set_before_provider(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    _seed_capture_slots(testing_session, run_id, list(range(16)))
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("full slot set must stop before provider")
        ),
    )

    response = client.post(_url(run_id))
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "detail": "Stored trace evidence reached the per-run capture limit."
    }


def test_persisted_trace_capture_rejects_corrupt_slot_before_provider(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    _seed_capture_slots(testing_session, run_id, [16])
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("corrupt slot must stop before provider")
        ),
    )

    response = client.post(_url(run_id))
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "detail": "Stored trace evidence slots are incoherent."
    }


def test_persisted_trace_readback_fails_closed_after_digest_tamper(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: ProviderResult.success(
            _normalized_finalized_candidate(),
            source="real",
        ),
    )
    assert client.post(_url(run_id)).status_code == 201
    with testing_session() as session:
        capture = session.scalar(select(WalletTraceEvidenceCapture))
        assert capture is not None
        capture.evidence_digest_sha256 = "00" * 32
        session.commit()

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("corrupt stored read must not fall back to provider")
        ),
    )
    response = client.get(_url(run_id))

    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert "digest failed local revalidation" in response.json()["detail"]
    assert _counts(testing_session) == (1, 2, 3)


@pytest.mark.parametrize("tamper", ["root_role_type", "out_role_type"])
def test_persisted_trace_readback_rejects_role_type_drift(
    persisted_trace_client,
    monkeypatch,
    tamper,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: ProviderResult.success(
            _normalized_finalized_candidate(),
            source="real",
        ),
    )
    assert client.post(_url(run_id)).status_code == 201
    with testing_session() as session:
        role = "root_inbound" if tamper == "root_role_type" else "remaining_outbound"
        message = session.scalar(
            select(WalletTraceEvidenceMessage).where(
                WalletTraceEvidenceMessage.role == role
            )
        )
        assert message is not None
        if tamper == "root_role_type":
            message.message_type = "ext_out_msg"
            message.source_account_canonical = ROOT_ACCOUNT
            message.destination_account_canonical = None
        else:
            message.message_type = "ext_in_msg"
            message.source_account_canonical = None
            message.destination_account_canonical = ROOT_ACCOUNT
        session.commit()

    response = client.get(_url(run_id))
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert "role is incoherent" in response.json()["detail"]


@pytest.mark.parametrize("tamper", ["captured_at", "capture_slot"])
def test_persisted_trace_digest_covers_capture_context(
    persisted_trace_client,
    monkeypatch,
    tamper,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: ProviderResult.success(
            _normalized_finalized_candidate(),
            source="real",
        ),
    )
    assert client.post(_url(run_id)).status_code == 201
    with testing_session() as session:
        capture = session.scalar(select(WalletTraceEvidenceCapture))
        assert capture is not None
        if tamper == "captured_at":
            capture.captured_at = capture.captured_at + timedelta(seconds=1)
        else:
            capture.capture_slot = 1
        session.commit()

    response = client.get(_url(run_id))
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert "digest failed local revalidation" in response.json()["detail"]


@pytest.mark.parametrize(
    ("run_id", "transaction_hash"),
    [
        ("01", ROOT_HASH),
        ("9223372036854775808", ROOT_HASH),
        ("1", "AB" * 32),
        ("1", "bad"),
    ],
)
def test_persisted_trace_paths_are_canonical_and_no_store(
    persisted_trace_client,
    run_id,
    transaction_hash,
):
    client, _engine, testing_session, _seeded_run_id = persisted_trace_client
    response = client.post(_url(run_id, transaction_hash))
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert _counts(testing_session) == (0, 0, 0)


def _boc_url(run_id: int | str, transaction_hash: str = ROOT_HASH) -> str:
    return (
        f"/api/wallets/ingest/{run_id}/transactions/{transaction_hash}"
        "/trace-evidence/boc-verification"
    )


def _boc_messages_url(
    run_id: int | str,
    transaction_hash: str = ROOT_HASH,
) -> str:
    return f"{_boc_url(run_id, transaction_hash)}/messages"


def _native_flow_url(
    run_id: int | str,
    transaction_hash: str = ROOT_HASH,
) -> str:
    return f"{_boc_url(run_id, transaction_hash)}/native-ton-flows"


def _fake_boc_derived(_capture, raw_rows):
    hashes = (ROOT_HASH, CHILD_HASH)
    owned_counts = (2, 1)
    canonical = []
    for index, row in enumerate(raw_rows):
        messages = []
        for position in range(owned_counts[index]):
            external_in = index == 0 and position == 0
            external_out = index == 0 and position == 1
            messages.append(
                {
                    "role": (
                        "root_inbound"
                        if external_in
                        else "remaining_outbound"
                        if external_out
                        else "child_inbound"
                    ),
                    "ordinal": 0,
                    "message_hash": f"{index * 2 + position + 1:064x}",
                    "raw_message_cell_hash": f"{index * 2 + position + 5:064x}",
                    "hash_kind": (
                        "normalized_external_in" if external_in else "cell_hash"
                    ),
                    "message_type": (
                        "ext_in_msg"
                        if external_in
                        else "ext_out_msg"
                        if external_out
                        else "int_msg"
                    ),
                    "source_account_canonical": (
                        None if external_in else ROOT_ACCOUNT
                    ),
                    "destination_account_canonical": (
                        None if external_out else ROOT_ACCOUNT
                    ),
                    "created_logical_time": "0" if external_in else ROOT_LT,
                    "unix_time": 0 if external_in else 1_717_236_000,
                    "value_nanoton": "0" if not external_out else "1",
                    "forward_fee_nanoton": "0",
                    "ihr_fee_nanoton": "0",
                    "import_fee_nanoton": "0",
                    "ihr_disabled": not external_in,
                    "bounce": False,
                    "bounced": False,
                    "extra_currency_count": 0,
                    "body_hash": f"{index * 2 + position + 9:064x}",
                    "body_bit_length": 32 if position == 0 else 0,
                    "body_ref_count": 0,
                    "opcode_hex": "0x00000001" if position == 0 else None,
                }
            )
        canonical.append(
            {
                "preorder_index": index,
                "transaction_hash": hashes[index],
                "transaction_boc_hex": row["transaction_boc_hex"],
                "transaction_boc_bytes": row["transaction_boc_bytes"],
                "transaction_cell_hash": hashes[index],
                "account_hash_hex": ("33" if index == 0 else "44") * 32,
                "logical_time": ROOT_LT if index == 0 else CHILD_LT,
                "unix_time": 1_717_236_000 + index,
                "aborted": index == 1,
                "raw_out_message_count": 2 if index == 0 else 0,
                "message_count": owned_counts[index],
                "messages": messages,
                "outgoing_edge_checks": messages,
            }
        )
    return {
        "transaction_count": 2,
        "message_count": 3,
        "total_boc_bytes": 2,
        "normalized_external_in_hash_count": 1,
        "direct_cell_hash_message_count": 2,
        "body_hash_count": 3,
        "opcode_count": 2,
        "canonical_transactions": canonical,
    }


def _capture_then_verify_bocs(client, run_id, monkeypatch):
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_persisted_evidence",
        lambda *args, **kwargs: ProviderResult.success(
            _normalized_finalized_candidate(),
            source="real",
        ),
    )
    assert client.post(_url(run_id)).status_code == 201
    calls = []

    def fake_boc_candidate(self, transaction_hash, network):
        calls.append((transaction_hash, network))
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
        fake_boc_candidate,
    )
    monkeypatch.setattr(boc_service, "_derive_boc_evidence", _fake_boc_derived)
    return calls


def test_boc_verification_requires_a_persisted_capture_and_is_provider_free(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, _testing_session, run_id = persisted_trace_client
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_boc_verification_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not be called without a capture")
        ),
    )

    absent = client.get(_boc_url(run_id))
    assert absent.status_code == 404
    assert absent.headers["cache-control"] == "no-store"

    rejected = client.post(_boc_url(run_id))
    assert rejected.status_code == 409
    assert rejected.headers["cache-control"] == "no-store"
    assert "must be captured" in rejected.json()["detail"]


def test_boc_verification_is_atomic_idempotent_and_never_returns_raw_bocs(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    calls = _capture_then_verify_bocs(client, run_id, monkeypatch)

    created = client.post(_boc_url(run_id))
    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    payload = created.json()
    WalletTraceBocVerificationResponse.model_validate(payload)
    assert payload["contract_version"] == "ton_boc_trace_verification_v1"
    assert payload["summary"]["transaction_count"] == 2
    assert payload["summary"]["message_count"] == 3
    assert payload["transaction_bocs_deserialized_locally"] is True
    assert payload["is_blockchain_inclusion_proof_verified"] is False
    assert payload["semantic_reconstruction_applied"] is False
    assert "transaction_boc_hex" not in json.dumps(payload)
    assert calls == [(ROOT_HASH, "ton-mainnet")]

    repeated = client.post(_boc_url(run_id))
    assert repeated.status_code == 200
    assert repeated.json() == payload
    assert calls == [(ROOT_HASH, "ton-mainnet")]

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_boc_verification_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("stored BOC readback must be provider-free")
        ),
    )
    readback = client.get(_boc_url(run_id))
    assert readback.status_code == 200
    assert readback.json() == payload
    with testing_session() as session:
        assert session.scalar(
            select(func.count()).select_from(WalletTraceBocVerification)
        ) == 1
        assert session.scalar(
            select(func.count()).select_from(WalletTraceBocTransaction)
        ) == 2


def test_boc_verification_readback_rejects_relational_tampering(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id = persisted_trace_client
    _capture_then_verify_bocs(client, run_id, monkeypatch)
    assert client.post(_boc_url(run_id)).status_code == 201
    with testing_session() as session:
        row = session.scalar(select(WalletTraceBocTransaction))
        assert row is not None
        row.transaction_cell_hash = "ff" * 32
        session.commit()

    response = client.get(_boc_url(run_id))
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"
    assert "row failed local revalidation" in response.json()["detail"]


def test_boc_message_evidence_is_provider_free_body_safe_and_digest_bound(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, _testing_session, run_id = persisted_trace_client
    _capture_then_verify_bocs(client, run_id, monkeypatch)
    verified = client.post(_boc_url(run_id))
    assert verified.status_code == 201
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_boc_verification_candidate",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("message evidence readback must be provider-free")
        ),
    )

    response = client.get(_boc_messages_url(run_id))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    WalletTraceBocMessageEvidenceResponse.model_validate(payload)
    assert payload["contract_version"] == "ton_boc_message_evidence_v1"
    assert payload["verification_evidence_digest_sha256"] == (
        verified.json()["evidence_digest_sha256"]
    )
    assert payload["message_count"] == 3
    assert payload["messages"][0]["body_hash"]
    assert "body" not in payload["messages"][0]
    assert "transaction_boc_hex" not in json.dumps(payload)
    assert payload["message_bodies_returned"] is False
    assert payload["semantic_reconstruction_applied"] is False


def test_native_ton_flows_are_account_scoped_provider_free_observations(
    persisted_trace_client,
    monkeypatch,
):
    client, _engine, _testing_session, run_id = persisted_trace_client
    evidence = {
        "verification_id": "1",
        "capture_id": "2",
        "run_id": str(run_id),
        "network": "ton-mainnet",
        "anchor": {
            "transaction_hash": ROOT_HASH,
            "logical_time": ROOT_LT,
            "account_canonical": ROOT_ACCOUNT,
            "matches_stored_transaction": True,
        },
        "message_evidence_digest_sha256": "ab" * 32,
        "messages": [
            {
                "transaction_preorder_index": 0,
                "transaction_hash": ROOT_HASH,
                "role": "remaining_outbound",
                "ordinal": 0,
                "message_hash": ROOT_OUT_HASH,
                "message_type": "int_msg",
                "source_account_canonical": ROOT_ACCOUNT,
                "destination_account_canonical": CHILD_ACCOUNT,
                "value_nanoton": "2500000000",
                "created_logical_time": ROOT_LT,
                "unix_time": 1_717_236_000,
                "body_hash": "98" * 32,
                "opcode_hex": None,
                "bounce": True,
                "bounced": False,
            },
            {
                "message_type": "ext_in_msg",
                "source_account_canonical": None,
                "destination_account_canonical": ROOT_ACCOUNT,
            },
        ],
    }
    monkeypatch.setattr(
        native_flow_service,
        "get_wallet_transaction_boc_message_evidence",
        lambda *args, **kwargs: evidence,
    )

    response = client.get(_native_flow_url(run_id))

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    WalletNativeTonFlowObservationsResponse.model_validate(payload)
    assert payload["flow_count"] == 1
    assert payload["outgoing_nanoton"] == "2500000000"
    assert payload["incoming_nanoton"] == "0"
    assert payload["flows"][0]["direction"] == "outgoing"
    assert payload["flows"][0]["counterparty_account_observed"] == CHILD_ACCOUNT
    assert payload["counterparty_is_header_observation"] is True
    assert payload["is_authoritative_transfer_ledger"] is False
    assert payload["eligible_for_cost_basis"] is False


def _storage_transaction_boc() -> tuple[str, str]:
    messages = Builder().store_bit(0).store_bit(0).end_cell()
    zero_fees = Builder().store_coins(0).store_bit(0).end_cell()
    state_update = (
        Builder()
        .store_uint(0x72, 8)
        .store_bytes(bytes(32))
        .store_bytes(bytes(32))
        .end_cell()
    )
    storage_description = (
        Builder()
        .store_uint(1, 4)
        .store_coins(0)
        .store_bit(0)
        .store_bit(0)
        .end_cell()
    )
    transaction = (
        Builder()
        .store_uint(7, 4)
        .store_bytes(bytes.fromhex("33" * 32))
        .store_uint(int(ROOT_LT), 64)
        .store_bytes(bytes(32))
        .store_uint(0, 64)
        .store_uint(1_717_236_000, 32)
        .store_uint(0, 15)
        .store_uint(2, 2)
        .store_uint(2, 2)
        .store_ref(messages)
        .store_cell(zero_fees)
        .store_ref(state_update)
        .store_ref(storage_description)
        .end_cell()
    )
    return transaction.hash.hex(), transaction.to_boc().hex()


def test_local_boc_parser_verifies_a_generated_storage_transaction():
    transaction_hash, boc_hex = _storage_transaction_boc()
    capture = WalletTraceEvidenceCapture(
        id=1,
        provider="tonapi",
        contract_version=PERSISTED_CONTRACT,
        network="ton-mainnet",
        root_transaction_hash=transaction_hash,
        trace_state="finalized",
        transaction_count=1,
        max_depth=0,
        message_count=0,
        root_inbound_message_count=0,
        child_internal_message_count=0,
        remaining_out_message_count=0,
        internal_message_count=0,
        external_in_message_count=0,
        external_out_message_count=0,
        successful_transaction_count=1,
        failed_transaction_count=0,
        aborted_transaction_count=0,
        unique_account_count=1,
        evidence_digest_sha256="ab" * 32,
        captured_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    node = WalletTraceEvidenceNode(
        id=1,
        preorder_index=0,
        depth=0,
        transaction_hash=transaction_hash,
        account_canonical=ROOT_ACCOUNT,
        logical_time=ROOT_LT,
        unix_time=1_717_236_000,
        success=True,
        aborted=False,
    )
    capture.nodes.append(node)
    raw_rows = [
        {
            "preorder_index": 0,
            "transaction_hash": transaction_hash,
            "transaction_boc_hex": boc_hex,
            "transaction_boc_bytes": len(boc_hex) // 2,
        }
    ]

    derived = boc_service._derive_boc_evidence(capture, raw_rows)

    assert derived["transaction_count"] == 1
    assert derived["message_count"] == 0
    assert derived["total_boc_bytes"] == len(boc_hex) // 2
    assert derived["canonical_transactions"][0]["transaction_cell_hash"] == (
        transaction_hash
    )
    node.logical_time = str(int(ROOT_LT) + 1)
    with pytest.raises(
        WalletTraceBocVerificationConflict,
        match="header does not match",
    ):
        boc_service._derive_boc_evidence(capture, raw_rows)


def test_external_in_message_hash_uses_normalized_cell_layout():
    destination = Address(ROOT_ACCOUNT)
    body = Builder().store_uint(0x12345678, 32).end_cell()
    message = MessageAny(
        ExternalMsgInfo(src=None, dest=destination, import_fee=123),
        init=None,
        body=body,
    )
    expected = (
        Builder()
        .store_uint(2, 2)
        .store_uint(0, 2)
        .store_address(destination)
        .store_uint(0, 4)
        .store_bit(0)
        .store_bit(1)
        .store_ref(body)
        .end_cell()
        .hash.hex()
    )

    provider_hash, raw_hash, hash_kind = boc_service._message_hashes(message)

    assert provider_hash == expected
    assert provider_hash != raw_hash
    assert hash_kind == "normalized_external_in"
