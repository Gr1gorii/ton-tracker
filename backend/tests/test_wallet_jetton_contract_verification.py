"""Proof-checked jetton contract relationship evidence tests."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from pytoniq_core import Address, begin_cell
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from database import Base, get_session
from main import app
from models import (
    WalletBalanceSnapshot,
    WalletIngestionRun,
    WalletJettonContractVerification,
)
from schemas import (
    WalletJettonContractVerificationCatalogResponse,
    WalletJettonContractVerificationResponse,
)
import routers.wallet_activity as wallet_activity_router
from services.ton_liteclient_jetton_verifier import (
    TonLiteclientJettonVerificationFailure,
    _address_from_slice,
    _decode_master_data,
    _decode_wallet_data,
    _single_address,
)
from services.wallet_jetton_contract_verification import (
    WalletJettonContractVerificationConflict,
    WalletJettonContractVerificationNotFound,
    list_wallet_jetton_contract_verifications,
    verify_wallet_jetton_contract_relationship,
)


OWNER = "0:" + "11" * 32
JETTON_WALLET = "0:" + "22" * 32
JETTON_MASTER = "0:" + "33" * 32


def _address_slice(value: str | None):
    return begin_cell().store_address(
        Address(value) if value is not None else None
    ).end_cell().begin_parse()


def _cell(value: int):
    return begin_cell().store_uint(value, 8).end_cell()


def _live_result(*, trust_level: int) -> dict:
    wallet_code = _cell(1)
    wallet_data = _cell(2)
    master_code = _cell(3)
    master_data = _cell(4)
    return {
        "verifier_name": "pytoniq-pytvm",
        "verifier_version": "pytoniq-test/pytvm-test",
        "trust_level": trust_level,
        "anchor": {
            "workchain": -1,
            "shard": "-9223372036854775808",
            "seqno": 123,
            "root_hash": "44" * 32,
            "file_hash": "55" * 32,
        },
        "wallet_balance_base_units": "123456",
        "total_supply_base_units": "987654321",
        "mintable": True,
        "wallet_code_boc_hex": wallet_code.to_boc().hex(),
        "wallet_data_boc_hex": wallet_data.to_boc().hex(),
        "master_code_boc_hex": master_code.to_boc().hex(),
        "master_data_boc_hex": master_data.to_boc().hex(),
        "wallet_code_hash": wallet_code.hash.hex(),
        "wallet_data_hash": wallet_data.hash.hex(),
        "master_code_hash": master_code.hash.hex(),
        "master_data_hash": master_data.hash.hex(),
        "jetton_content_hash": "66" * 32,
        "account_state_proof_verified": True,
        "masterchain_checkpoint_chain_verified": trust_level == 0,
        "local_tvm_execution_applied": True,
    }


def _session_with_run():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    run = WalletIngestionRun(
        wallet_address=OWNER,
        time_window="all",
        data_mode="real",
        status="completed",
        requested_surfaces_json='["balances"]',
        provider_summary_json='{"tonapi":"live"}',
        wallet_identity_status="network_scoped",
        wallet_identity_version="ton_std_address_v1",
        wallet_network="ton-mainnet",
        wallet_address_canonical=OWNER,
        wallet_workchain_id=0,
        wallet_account_id_hex="11" * 32,
        wallet_address_format="raw",
        wallet_address_bounceable=None,
        wallet_address_testnet_only=None,
    )
    run.balance_snapshots.append(
        WalletBalanceSnapshot(
            asset="TEST",
            balance=123456,
            provider="tonapi",
            source_status="live",
            raw_json=json.dumps(
                {
                    "surface": "jettons",
                    "wallet_contract_address": JETTON_WALLET,
                    "jetton_address": JETTON_MASTER,
                }
            ),
        )
    )
    session.add(run)
    session.commit()
    return session, run.id


def _endpoint_client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine)
    session = testing_session()
    run = WalletIngestionRun(
        wallet_address=OWNER,
        time_window="all",
        data_mode="real",
        status="completed",
        requested_surfaces_json='["balances"]',
        provider_summary_json='{"tonapi":"live"}',
        wallet_identity_status="network_scoped",
        wallet_identity_version="ton_std_address_v1",
        wallet_network="ton-mainnet",
        wallet_address_canonical=OWNER,
        wallet_workchain_id=0,
        wallet_account_id_hex="11" * 32,
        wallet_address_format="raw",
    )
    run.balance_snapshots.append(
        WalletBalanceSnapshot(
            asset="TEST",
            balance=123456,
            provider="tonapi",
            source_status="live",
            raw_json=json.dumps(
                {
                    "surface": "jettons",
                    "wallet_contract_address": JETTON_WALLET,
                    "jetton_address": JETTON_MASTER,
                }
            ),
        )
    )
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    def override_session():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_session] = override_session
    return TestClient(app), engine, run_id


def test_local_getter_decoders_are_strict_and_address_complete():
    wallet_code = _cell(7)
    wallet = _decode_wallet_data(
        [
            42,
            _address_slice(OWNER),
            _address_slice(JETTON_MASTER),
            wallet_code,
        ]
    )
    assert wallet == {
        "balance": 42,
        "owner": Address(OWNER),
        "master": Address(JETTON_MASTER),
        "wallet_code": wallet_code,
    }

    master = _decode_master_data(
        [1000, -1, _address_slice(None), _cell(8), wallet_code]
    )
    assert master["total_supply"] == 1000
    assert master["mintable"] is True
    assert _single_address([_address_slice(JETTON_WALLET)]) == Address(
        JETTON_WALLET
    )

    with pytest.raises(TonLiteclientJettonVerificationFailure):
        _decode_wallet_data([True, _address_slice(OWNER), _address_slice(OWNER), wallet_code])
    with pytest.raises(TonLiteclientJettonVerificationFailure):
        _single_address([])
    trailing = begin_cell().store_address(Address(OWNER)).store_bit(1).end_cell()
    with pytest.raises(TonLiteclientJettonVerificationFailure):
        _address_from_slice(trailing.begin_parse())


def test_verification_is_immutable_idempotent_and_provider_free_on_readback():
    session, run_id = _session_with_run()
    calls = []

    def fake_live_verifier(**kwargs):
        calls.append(kwargs)
        return _live_result(trust_level=kwargs["trust_level"])

    created = verify_wallet_jetton_contract_relationship(
        run_id,
        JETTON_WALLET,
        JETTON_MASTER,
        session,
        live_verifier=fake_live_verifier,
    )
    WalletJettonContractVerificationResponse.model_validate(created)
    assert created["asset_identity_key"] == (
        f"ton_jetton_asset_v1|ton-mainnet|{JETTON_MASTER}"
    )
    assert created["wallet_owner_master_verified"] is True
    assert created["master_wallet_address_verified"] is True
    assert created["eligible_for_cost_basis"] is False
    assert created["used_by_pnl"] is False
    assert set(created["account_state_boc_hashes"]) == {
        "wallet_code_boc_hex",
        "wallet_data_boc_hex",
        "master_code_boc_hex",
        "master_data_boc_hex",
    }
    assert all(
        len(value) == 64
        for value in created["account_state_boc_hashes"].values()
    )

    repeated = verify_wallet_jetton_contract_relationship(
        run_id,
        JETTON_WALLET,
        JETTON_MASTER,
        session,
        live_verifier=lambda **_kwargs: (_ for _ in ()).throw(
            AssertionError("immutable repeat must not contact a liteserver")
        ),
    )
    assert repeated == created
    assert len(calls) == 1

    catalog = list_wallet_jetton_contract_verifications(run_id, session)
    WalletJettonContractVerificationCatalogResponse.model_validate(catalog)
    assert catalog["verification_count"] == 1
    assert catalog["provider_requests_performed"] is False
    assert catalog["verifications"] == [created]


def test_verification_fails_closed_without_exact_live_snapshot_or_on_tamper():
    session, run_id = _session_with_run()
    with pytest.raises(WalletJettonContractVerificationNotFound):
        verify_wallet_jetton_contract_relationship(
            run_id,
            "0:" + "77" * 32,
            JETTON_MASTER,
            session,
            live_verifier=lambda **kwargs: _live_result(
                trust_level=kwargs["trust_level"]
            ),
        )

    verify_wallet_jetton_contract_relationship(
        run_id,
        JETTON_WALLET,
        JETTON_MASTER,
        session,
        live_verifier=lambda **kwargs: _live_result(
            trust_level=kwargs["trust_level"]
        ),
    )
    record = session.scalar(select(WalletJettonContractVerification))
    assert record is not None
    record.wallet_code_hash = "ff" * 32
    session.commit()
    with pytest.raises(WalletJettonContractVerificationConflict):
        list_wallet_jetton_contract_verifications(run_id, session)


def test_schema_rejects_overstated_proof_and_pnl_flags():
    session, run_id = _session_with_run()
    payload = verify_wallet_jetton_contract_relationship(
        run_id,
        JETTON_WALLET,
        JETTON_MASTER,
        session,
        live_verifier=lambda **kwargs: _live_result(
            trust_level=kwargs["trust_level"]
        ),
    )
    payload["is_blockchain_inclusion_proof_verified"] = not (
        payload["trust_level"] == 0
    )
    with pytest.raises(ValidationError):
        WalletJettonContractVerificationResponse.model_validate(payload)

    payload["is_blockchain_inclusion_proof_verified"] = (
        payload["trust_level"] == 0
    )
    payload["eligible_for_cost_basis"] = True
    with pytest.raises(ValidationError):
        WalletJettonContractVerificationResponse.model_validate(payload)


def test_verification_endpoints_apply_response_contract_and_no_store(monkeypatch):
    client, engine, run_id = _endpoint_client()

    def endpoint_verifier(
        selected_run_id,
        jetton_wallet,
        jetton_master,
        session,
    ):
        return verify_wallet_jetton_contract_relationship(
            selected_run_id,
            jetton_wallet,
            jetton_master,
            session,
            live_verifier=lambda **kwargs: _live_result(
                trust_level=kwargs["trust_level"]
            ),
        )

    monkeypatch.setattr(
        wallet_activity_router,
        "verify_wallet_jetton_contract_relationship",
        endpoint_verifier,
    )
    try:
        created = client.post(
            f"/api/wallets/ingest/{run_id}/jetton-contract-verifications",
            json={
                "jetton_wallet_account_canonical": JETTON_WALLET,
                "jetton_master_account_canonical": JETTON_MASTER,
            },
        )
        assert created.status_code == 200, created.text
        assert created.headers["cache-control"] == "no-store"
        WalletJettonContractVerificationResponse.model_validate(created.json())

        catalog = client.get(
            f"/api/wallets/ingest/{run_id}/jetton-contract-verifications"
        )
        assert catalog.status_code == 200, catalog.text
        assert catalog.headers["cache-control"] == "no-store"
        payload = WalletJettonContractVerificationCatalogResponse.model_validate(
            catalog.json()
        )
        assert payload.verification_count == 1
        assert payload.provider_requests_performed is False
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
