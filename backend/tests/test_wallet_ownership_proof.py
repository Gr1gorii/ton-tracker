"""TON Connect ownership challenge and replay-protection tests."""

import base64
from datetime import datetime, timezone

import pytest
from nacl.signing import SigningKey
from pytoniq_core import Address, StateInit, begin_cell
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import QueuePool

from database import Base
from schemas import (
    WalletOwnershipChallengeRequest,
    WalletOwnershipChallengeResponse,
    WalletOwnershipProofResponse,
)
from services.wallet_ownership_proof import (
    WalletOwnershipProofConflict,
    _ton_proof_digest,
    create_ownership_challenge,
    verify_ownership_proof,
)


def _session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _fixture(challenge):
    signing_key = SigningKey.generate()
    state = StateInit(
        code=begin_cell().store_uint(1, 8).end_cell(),
        data=begin_cell().store_bytes(bytes(signing_key.verify_key)).end_cell(),
    ).serialize()
    address = Address(f"0:{state.hash.hex()}")
    proof = {
        "timestamp": int(datetime.now(timezone.utc).timestamp()),
        "domain": {
            "lengthBytes": len(challenge["expected_domain"].encode()),
            "value": challenge["expected_domain"],
        },
        "payload": challenge["payload"],
        "signature": "",
    }
    proof["signature"] = base64.b64encode(
        signing_key.sign(_ton_proof_digest(address, proof)).signature
    ).decode()
    return {
        "address": address.to_str(is_user_friendly=False),
        "network": "ton-mainnet",
        "wallet_state_init": base64.b64encode(state.to_boc()).decode(),
        "proof": proof,
    }, bytes(signing_key.verify_key)


def test_ownership_challenge_verifies_signature_and_rejects_replay(monkeypatch):
    monkeypatch.setenv("TONCONNECT_EXPECTED_DOMAIN", "tracker.example")
    session = _session()
    challenge = create_ownership_challenge(session)
    WalletOwnershipChallengeResponse.model_validate(challenge)
    request, public_key = _fixture(challenge)

    result = verify_ownership_proof(
        challenge["challenge_id"], request, session,
        public_key_resolver=lambda **_kwargs: public_key,
    )
    WalletOwnershipProofResponse.model_validate(result)
    assert result["signature_verified"] is True
    assert result["is_ownership_proof"] is True

    with pytest.raises(WalletOwnershipProofConflict, match="consumed"):
        verify_ownership_proof(
            challenge["challenge_id"], request, session,
            public_key_resolver=lambda **_kwargs: public_key,
        )


def test_ownership_proof_rejects_wrong_domain_before_key_resolution(monkeypatch):
    monkeypatch.setenv("TONCONNECT_EXPECTED_DOMAIN", "tracker.example")
    session = _session()
    challenge = create_ownership_challenge(session)
    request, _ = _fixture(challenge)
    request["proof"]["domain"]["value"] = "evil.example"

    with pytest.raises(WalletOwnershipProofConflict, match="scope"):
        verify_ownership_proof(
            challenge["challenge_id"], request, session,
            public_key_resolver=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("key resolution must not occur")
            ),
        )


def test_ownership_proof_rejects_cross_network_replay_before_key_resolution(
    monkeypatch,
):
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    session = _session()
    challenge = create_ownership_challenge(session)
    assert challenge["expected_network"] == "ton-mainnet"
    request, _ = _fixture(challenge)
    request["network"] = "ton-testnet"

    with pytest.raises(WalletOwnershipProofConflict, match="network"):
        verify_ownership_proof(
            challenge["challenge_id"],
            request,
            session,
            public_key_resolver=lambda **_kwargs: (_ for _ in ()).throw(
                AssertionError("key resolution must not occur")
            ),
        )


def test_ownership_challenge_accepts_user_friendly_expected_wallet(monkeypatch):
    monkeypatch.setenv("TON_NETWORK", "mainnet")
    session = _session()
    state = StateInit(
        code=begin_cell().store_uint(1, 8).end_cell(),
        data=begin_cell().store_uint(2, 8).end_cell(),
    ).serialize()
    address = Address(f"0:{state.hash.hex()}")
    friendly = address.to_str(
        is_user_friendly=True,
        is_bounceable=False,
        is_test_only=False,
    )

    request = WalletOwnershipChallengeRequest(expected_wallet=friendly)
    challenge = create_ownership_challenge(
        session,
        expected_wallet=request.expected_wallet,
    )

    assert challenge["expected_wallet_account_canonical"] == address.to_str(
        is_user_friendly=False,
    )


def test_ownership_releases_pool_connection_during_public_key_child(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("TONCONNECT_EXPECTED_DOMAIN", "tracker.example")
    engine = create_engine(
        f"sqlite:///{tmp_path / 'ownership.db'}",
        poolclass=QueuePool,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.2,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    challenge = create_ownership_challenge(session)
    request, public_key = _fixture(challenge)
    observed = []

    def resolver(**_kwargs):
        observed.append(engine.pool.checkedout())
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        return public_key

    try:
        result = verify_ownership_proof(
            challenge["challenge_id"],
            request,
            session,
            public_key_resolver=resolver,
        )
        assert result["signature_verified"] is True
        assert observed == [0]
    finally:
        session.close()
        engine.dispose()
