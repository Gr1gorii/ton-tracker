"""Strict tests for bounded persisted-transaction trace evidence preview."""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from adapters.tonapi import TonapiAdapter
from config import (
    DEFAULT_TONAPI_BASE_URL,
    ERROR_PROVIDER_ERROR,
    ProviderResult,
    Settings,
)
from database import Base, get_session
from main import app
from models import WalletIngestionRun, WalletTransaction
from schemas import WalletTransactionTraceEvidenceResponse
from services.ton_transaction_identity import derive_ton_transaction_identity


TRANSACTION_HASH = "ab" * 32
CHILD_HASH = "cd" * 32
OTHER_HASH = "ef" * 32
ACCOUNT = "0:" + "12" * 32
CHILD_ACCOUNT = "0:" + "34" * 32
LOGICAL_TIME = "89156526000001"
CHILD_LOGICAL_TIME = "89156526000003"
WALLET_TABLES = (
    "wallet_ingestion_runs",
    "wallet_transfers",
    "wallet_transactions",
    "wallet_swaps",
    "wallet_balance_snapshots",
    "wallet_ingestion_warnings",
    "wallet_acquisition_streams",
    "wallet_acquisition_pages",
    "wallet_trace_evidence_captures",
    "wallet_trace_evidence_nodes",
    "wallet_trace_evidence_messages",
)


def _settings(mode: str = "real", **overrides) -> Settings:
    values = {
        "data_mode": mode,
        "geckoterminal_base_url": "https://api.geckoterminal.com/api/v2",
        "ton_api_base_url": "",
        "ton_api_key": "",
        "bitquery_api_url": "",
        "bitquery_api_key": "",
        "stonfi_base_url": "https://api.ston.fi",
        "tonapi_base_url": DEFAULT_TONAPI_BASE_URL,
        "tonapi_api_key": "",
        "wallet_activity_provider": "tonapi",
        "wallet_activity_live_enabled": True,
        "ton_network": "mainnet",
    }
    values.update(overrides)
    return Settings(**values)


def _transaction(
    transaction_hash: str,
    logical_time: str,
    account: str,
    *,
    success: bool = True,
    aborted: bool = False,
    out_messages: list[dict] | None = None,
) -> dict:
    return {
        "hash": transaction_hash,
        "lt": logical_time,
        "account": {"address": account},
        "utime": 1_717_236_000,
        "success": success,
        "aborted": aborted,
        "out_msgs": out_messages or [],
    }


def _trace_node(
    transaction_hash: str = TRANSACTION_HASH,
    logical_time: str = LOGICAL_TIME,
    account: str = ACCOUNT,
    *,
    children: list[dict] | None = None,
    out_messages: list[dict] | None = None,
    success: bool = True,
    aborted: bool = False,
    include_children: bool = True,
) -> dict:
    node = {
        "transaction": _transaction(
            transaction_hash,
            logical_time,
            account,
            success=success,
            aborted=aborted,
            out_messages=out_messages,
        ),
        "interfaces": [],
        "emulated": False,
    }
    if include_children:
        node["children"] = children or []
    return node


def _finalized_trace() -> dict:
    child = _trace_node(
        CHILD_HASH,
        CHILD_LOGICAL_TIME,
        CHILD_ACCOUNT,
        success=False,
        aborted=True,
        include_children=False,
    )
    return _trace_node(
        children=[child],
        out_messages=[{"msg_type": "ext_out_msg"}],
    )


def _normalized_trace() -> dict:
    return TonapiAdapter.normalize_transaction_trace_evidence_response(
        _finalized_trace(),
        requested_transaction_hash=TRANSACTION_HASH,
    )


def _response_payload() -> dict:
    normalized = _normalized_trace()
    return {
        "contract_version": "tonapi_transaction_trace_preview_v1",
        "run_id": "1",
        "provider": "tonapi",
        "source_status": "live",
        "trace_state": normalized["trace_state"],
        "anchor": {
            **normalized["anchor"],
            "matches_stored_transaction": True,
        },
        "summary": normalized["summary"],
        "is_provider_indexed_low_level_trace": True,
        "is_blockchain_proof_verified": False,
        "is_authoritative_activity_identity": False,
        "semantic_reconstruction_applied": False,
        "activity_merge_applied": False,
        "deduplication_applied": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "is_ownership_proof": False,
        "message": (
            "Provider-indexed low-level trace structure matched the stored "
            "transaction anchor. No blockchain proof was verified and no "
            "semantic activity reconstruction was applied."
        ),
    }


def _wallet_table_counts(engine) -> tuple[int, ...]:
    with engine.connect() as connection:
        return tuple(
            connection.execute(
                text(f"SELECT COUNT(*) FROM {table_name}")
            ).scalar_one()
            for table_name in WALLET_TABLES
        )


def _seed_eligible_run(testing_session) -> tuple[int, str]:
    raw = {
        "provider": "tonapi",
        "surface": "transactions",
        "tx_hash": TRANSACTION_HASH,
        "logical_time": LOGICAL_TIME,
    }
    run = WalletIngestionRun(
        wallet_address=ACCOUNT,
        wallet_identity_status="network_scoped",
        wallet_identity_version="ton_raw_address_v1",
        wallet_network="ton-mainnet",
        wallet_address_canonical=ACCOUNT,
        wallet_workchain_id=0,
        wallet_account_id_hex="12" * 32,
        wallet_address_format="raw",
        wallet_address_bounceable=None,
        wallet_address_testnet_only=None,
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
        logical_time=LOGICAL_TIME,
        transaction_hash=TRANSACTION_HASH,
        data_mode=run.data_mode,
        source_status="live",
        provider="tonapi",
        raw=raw,
    )
    run.transactions.append(
        WalletTransaction(
            tx_hash=TRANSACTION_HASH,
            logical_time=LOGICAL_TIME,
            success="success",
            provider="tonapi",
            source_status="live",
            raw_json=json.dumps(raw, separators=(",", ":")),
            transaction_identity_status=identity.status,
            transaction_identity_version=identity.version,
            transaction_network=identity.network,
            transaction_account_canonical=identity.account_canonical,
            transaction_logical_time_canonical=(
                identity.logical_time_canonical
            ),
            transaction_hash_canonical=identity.hash_canonical,
            transaction_identity_key=identity.key,
        )
    )
    session = testing_session()
    try:
        session.add(run)
        session.commit()
        return run.id, TRANSACTION_HASH
    finally:
        session.close()


@pytest.fixture
def trace_client(monkeypatch):
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
    run_id, transaction_hash = _seed_eligible_run(testing_session)

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
    monkeypatch.setenv("TONAPI_API_KEY", "trace-provider-secret")
    app.dependency_overrides[get_session] = override_get_session
    try:
        yield TestClient(app), engine, testing_session, run_id, transaction_hash
    finally:
        app.dependency_overrides.clear()


def test_trace_normalizer_returns_sanitized_finalized_summary():
    result = _normalized_trace()

    assert result == {
        "trace_state": "finalized",
        "anchor": {
            "transaction_hash": TRANSACTION_HASH,
            "logical_time": LOGICAL_TIME,
            "account_canonical": ACCOUNT,
        },
        "summary": {
            "root_transaction_hash": TRANSACTION_HASH,
            "transaction_count": 2,
            "max_depth": 1,
            "out_message_count": 1,
            "pending_internal_message_count": 0,
            "successful_transaction_count": 1,
            "failed_transaction_count": 1,
            "aborted_transaction_count": 1,
            "unique_account_count": 2,
        },
    }
    serialized = json.dumps(result)
    assert "raw_body" not in serialized
    assert "decoded_body" not in serialized
    assert "interfaces" not in serialized


def test_trace_normalizer_marks_remaining_internal_message_pending():
    payload = _trace_node(out_messages=[{"msg_type": "int_msg"}])

    result = TonapiAdapter.normalize_transaction_trace_evidence_response(
        payload,
        requested_transaction_hash=TRANSACTION_HASH,
    )

    assert result["trace_state"] == "pending"
    assert result["summary"]["pending_internal_message_count"] == 1


def test_trace_normalizer_accepts_exact_node_and_depth_boundaries():
    leaves = [
        _trace_node(
            f"{index + 1:064x}",
            str(1_000 + index),
            f"0:{index + 1:064x}",
            include_children=False,
        )
        for index in range(255)
    ]
    leaves[0]["transaction"]["hash"] = TRANSACTION_HASH
    payload = _trace_node(
        OTHER_HASH,
        "999999",
        ACCOUNT,
        children=leaves,
    )
    result = TonapiAdapter.normalize_transaction_trace_evidence_response(
        payload,
        requested_transaction_hash=TRANSACTION_HASH,
    )
    assert result["summary"]["transaction_count"] == 256
    assert result["summary"]["max_depth"] == 1

    depth_payload = _trace_node(include_children=False)
    cursor = depth_payload
    for depth in range(1, 33):
        child = _trace_node(
            f"{10_000 + depth:064x}",
            str(10_000 + depth),
            f"0:{20_000 + depth:064x}",
            include_children=False,
        )
        cursor["children"] = [child]
        cursor = child
    result = TonapiAdapter.normalize_transaction_trace_evidence_response(
        depth_payload,
        requested_transaction_hash=TRANSACTION_HASH,
    )
    assert result["summary"]["max_depth"] == 32


def test_trace_normalizer_rejects_above_node_depth_and_message_bounds():
    too_many_nodes = _trace_node(
        children=[
            _trace_node(
                f"{index + 1:064x}",
                str(index + 1),
                f"0:{index + 1:064x}",
                include_children=False,
            )
            for index in range(256)
        ]
    )
    with pytest.raises(ValueError, match="node count"):
        TonapiAdapter.normalize_transaction_trace_evidence_response(
            too_many_nodes,
            requested_transaction_hash=TRANSACTION_HASH,
        )

    too_deep = _trace_node(include_children=False)
    cursor = too_deep
    for depth in range(1, 34):
        child = _trace_node(
            f"{30_000 + depth:064x}",
            str(30_000 + depth),
            f"0:{40_000 + depth:064x}",
            include_children=False,
        )
        cursor["children"] = [child]
        cursor = child
    with pytest.raises(ValueError, match="tree depth"):
        TonapiAdapter.normalize_transaction_trace_evidence_response(
            too_deep,
            requested_transaction_hash=TRANSACTION_HASH,
        )

    exact_messages = _trace_node(
        out_messages=[{"msg_type": "ext_out_msg"}] * 2048
    )
    result = TonapiAdapter.normalize_transaction_trace_evidence_response(
        exact_messages,
        requested_transaction_hash=TRANSACTION_HASH,
    )
    assert result["summary"]["out_message_count"] == 2048
    exact_messages["transaction"]["out_msgs"].append(
        {"msg_type": "ext_out_msg"}
    )
    with pytest.raises(ValueError, match="message count"):
        TonapiAdapter.normalize_transaction_trace_evidence_response(
            exact_messages,
            requested_transaction_hash=TRANSACTION_HASH,
        )


def test_trace_normalizer_rejects_conflicting_coordinate_hash():
    conflicting = _trace_node(
        children=[
            _trace_node(
                CHILD_HASH,
                LOGICAL_TIME,
                ACCOUNT,
                include_children=False,
            )
        ]
    )

    with pytest.raises(ValueError, match="coordinate changed hash"):
        TonapiAdapter.normalize_transaction_trace_evidence_response(
            conflicting,
            requested_transaction_hash=TRANSACTION_HASH,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda payload: payload.pop("transaction"), "transaction"),
        (lambda payload: payload.pop("interfaces"), "interfaces"),
        (lambda payload: payload.update({"children": {}}), "children"),
        (
            lambda payload: payload.update({"emulated": True}),
            "emulated",
        ),
        (
            lambda payload: payload["transaction"].update({"hash": "x"}),
            "hash",
        ),
        (
            lambda payload: payload["transaction"].update({"lt": "01"}),
            "logical time",
        ),
        (
            lambda payload: payload["transaction"].update(
                {"account": {"address": "EQinvalid"}}
            ),
            "account",
        ),
        (
            lambda payload: payload["transaction"].update({"utime": True}),
            "utime",
        ),
        (
            lambda payload: payload["transaction"].update({"success": 1}),
            "success",
        ),
        (
            lambda payload: payload["transaction"].update({"aborted": 0}),
            "aborted",
        ),
        (
            lambda payload: payload["transaction"].update({"out_msgs": {}}),
            "out_msgs",
        ),
    ],
)
def test_trace_normalizer_rejects_malformed_required_contract(
    mutation,
    message,
):
    payload = _trace_node()
    mutation(payload)
    with pytest.raises(ValueError, match=message):
        TonapiAdapter.normalize_transaction_trace_evidence_response(
            payload,
            requested_transaction_hash=TRANSACTION_HASH,
        )


def test_trace_normalizer_rejects_duplicate_hash_and_missing_anchor():
    duplicate = _trace_node(
        children=[
            _trace_node(
                TRANSACTION_HASH,
                CHILD_LOGICAL_TIME,
                CHILD_ACCOUNT,
                include_children=False,
            )
        ]
    )
    with pytest.raises(ValueError, match="reuses a transaction hash"):
        TonapiAdapter.normalize_transaction_trace_evidence_response(
            duplicate,
            requested_transaction_hash=TRANSACTION_HASH,
        )

    with pytest.raises(ValueError, match="does not contain"):
        TonapiAdapter.normalize_transaction_trace_evidence_response(
            _trace_node(),
            requested_transaction_hash=OTHER_HASH,
        )


def test_trace_adapter_makes_exactly_one_requested_provider_call(monkeypatch):
    calls: list[tuple[str, object, object, object]] = []

    def fake_fetch(self, path, query=None, method="GET", body=None, timeout=10):
        calls.append((path, query, method, body))
        return ProviderResult.success(_finalized_trace(), source="real")

    monkeypatch.setattr(TonapiAdapter, "fetch_json", fake_fetch)
    result = TonapiAdapter(_settings()).get_transaction_trace_evidence_preview(
        TRANSACTION_HASH
    )

    assert result.ok is True
    assert result.data == _normalized_trace()
    assert calls == [
        (f"/v2/traces/{TRANSACTION_HASH}", None, "GET", None)
    ]


def test_trace_adapter_rejects_mock_and_noncanonical_hash_without_call(monkeypatch):
    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider must not be called")

    monkeypatch.setattr(TonapiAdapter, "fetch_json", forbidden)
    assert not TonapiAdapter(
        _settings(mode="mock")
    ).get_transaction_trace_evidence_preview(TRANSACTION_HASH).ok
    assert not TonapiAdapter(
        _settings()
    ).get_transaction_trace_evidence_preview(TRANSACTION_HASH.upper()).ok


def test_trace_response_schema_is_strict_and_coherent():
    payload = _response_payload()
    assert WalletTransactionTraceEvidenceResponse.model_validate(payload)

    for field in (
        "is_blockchain_proof_verified",
        "is_authoritative_activity_identity",
        "semantic_reconstruction_applied",
        "activity_merge_applied",
        "deduplication_applied",
        "eligible_for_cost_basis",
        "used_by_pnl",
        "is_ownership_proof",
    ):
        invalid = copy.deepcopy(payload)
        invalid[field] = True
        with pytest.raises(ValidationError):
            WalletTransactionTraceEvidenceResponse.model_validate(invalid)

    invalid = copy.deepcopy(payload)
    invalid["unexpected"] = "field"
    with pytest.raises(ValidationError):
        WalletTransactionTraceEvidenceResponse.model_validate(invalid)

    invalid = copy.deepcopy(payload)
    invalid["trace_state"] = "pending"
    with pytest.raises(ValidationError):
        WalletTransactionTraceEvidenceResponse.model_validate(invalid)


def test_trace_endpoint_returns_exact_summary_and_no_store(
    trace_client,
    monkeypatch,
):
    client, _engine, _sessions, run_id, transaction_hash = trace_client
    calls: list[str] = []

    def fake_trace(self, requested_hash):
        calls.append(requested_hash)
        return ProviderResult.success(_normalized_trace(), source="real")

    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_evidence_preview",
        fake_trace,
    )
    response = client.get(
        f"/api/wallets/ingest/{run_id}/transactions/"
        f"{transaction_hash}/trace-evidence"
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body == {**_response_payload(), "run_id": str(run_id)}
    assert calls == [transaction_hash]


def test_trace_endpoint_performs_no_database_mutation(
    trace_client,
    monkeypatch,
):
    client, engine, _sessions, run_id, transaction_hash = trace_client
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_evidence_preview",
        lambda self, requested_hash: ProviderResult.success(
            _normalized_trace(),
            source="real",
        ),
    )
    before = _wallet_table_counts(engine)
    statements: list[str] = []

    def capture_statement(_conn, _cursor, statement, *_args):
        statements.append(statement.strip().upper())

    event.listen(engine, "before_cursor_execute", capture_statement)
    try:
        first = client.get(
            f"/api/wallets/ingest/{run_id}/transactions/"
            f"{transaction_hash}/trace-evidence"
        )
        second = client.get(
            f"/api/wallets/ingest/{run_id}/transactions/"
            f"{transaction_hash}/trace-evidence"
        )
    finally:
        event.remove(engine, "before_cursor_execute", capture_statement)

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert _wallet_table_counts(engine) == before
    assert statements
    assert all(
        not statement.startswith(
            ("INSERT", "UPDATE", "DELETE", "REPLACE", "CREATE", "DROP", "ALTER")
        )
        for statement in statements
    )


@pytest.mark.parametrize(
    "run_id",
    ["0", "-1", "01", "+1", "9223372036854775808", "abc"],
)
def test_trace_endpoint_rejects_noncanonical_run_path(trace_client, run_id):
    client, _engine, _sessions, _stored_run_id, transaction_hash = trace_client
    response = client.get(
        f"/api/wallets/ingest/{run_id}/transactions/"
        f"{transaction_hash}/trace-evidence"
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "transaction_hash",
    [TRANSACTION_HASH.upper(), "a" * 63, "a" * 65, "g" * 64],
)
def test_trace_endpoint_rejects_noncanonical_hash_path(
    trace_client,
    transaction_hash,
):
    client, _engine, _sessions, run_id, _stored_hash = trace_client
    response = client.get(
        f"/api/wallets/ingest/{run_id}/transactions/"
        f"{transaction_hash}/trace-evidence"
    )
    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"


def test_trace_endpoint_returns_404_for_missing_run_or_transaction(trace_client):
    client, _engine, _sessions, run_id, transaction_hash = trace_client
    missing_run = client.get(
        f"/api/wallets/ingest/{run_id + 1}/transactions/"
        f"{transaction_hash}/trace-evidence"
    )
    missing_transaction = client.get(
        f"/api/wallets/ingest/{run_id}/transactions/"
        f"{OTHER_HASH}/trace-evidence"
    )
    assert missing_run.status_code == 404
    assert missing_transaction.status_code == 404
    assert missing_run.headers["cache-control"] == "no-store"
    assert missing_transaction.headers["cache-control"] == "no-store"


def test_trace_endpoint_returns_409_before_provider_for_ineligible_config(
    trace_client,
    monkeypatch,
):
    client, _engine, _sessions, run_id, transaction_hash = trace_client
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_evidence_preview",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("provider must not be called")
        ),
    )
    response = client.get(
        f"/api/wallets/ingest/{run_id}/transactions/"
        f"{transaction_hash}/trace-evidence"
    )
    assert response.status_code == 409
    assert response.headers["cache-control"] == "no-store"


def test_trace_endpoint_returns_409_for_tampered_stored_identity(
    trace_client,
    monkeypatch,
):
    client, _engine, testing_session, run_id, transaction_hash = trace_client
    session = testing_session()
    try:
        row = session.query(WalletTransaction).filter_by(run_id=run_id).one()
        row.transaction_identity_key = "tampered"
        session.commit()
    finally:
        session.close()
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_evidence_preview",
        lambda *_args: (_ for _ in ()).throw(
            AssertionError("provider must not be called")
        ),
    )
    response = client.get(
        f"/api/wallets/ingest/{run_id}/transactions/"
        f"{transaction_hash}/trace-evidence"
    )
    assert response.status_code == 409


def test_trace_endpoint_returns_502_for_anchor_mismatch(
    trace_client,
    monkeypatch,
):
    client, _engine, _sessions, run_id, transaction_hash = trace_client
    mismatched = _normalized_trace()
    mismatched["anchor"]["logical_time"] = "1"
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_evidence_preview",
        lambda self, requested_hash: ProviderResult.success(
            mismatched,
            source="real",
        ),
    )
    response = client.get(
        f"/api/wallets/ingest/{run_id}/transactions/"
        f"{transaction_hash}/trace-evidence"
    )
    assert response.status_code == 502
    assert response.headers["cache-control"] == "no-store"


def test_trace_endpoint_redacts_provider_credential_from_502(
    trace_client,
    monkeypatch,
):
    client, _engine, _sessions, run_id, transaction_hash = trace_client
    monkeypatch.setattr(
        TonapiAdapter,
        "get_transaction_trace_evidence_preview",
        lambda self, requested_hash: ProviderResult.failure(
            ERROR_PROVIDER_ERROR,
            "provider rejected trace-provider-secret credential",
            source="real",
        ),
    )
    response = client.get(
        f"/api/wallets/ingest/{run_id}/transactions/"
        f"{transaction_hash}/trace-evidence"
    )
    assert response.status_code == 502
    serialized = response.text
    assert "trace-provider-secret" not in serialized
    assert "[redacted]" in serialized
