"""TON Connect ownership challenge and replay-protection tests."""

import base64
from datetime import datetime, timezone

import pytest
from nacl.signing import SigningKey
from pytoniq_core import Address, StateInit, begin_cell
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from database import Base
from schemas import WalletOwnershipChallengeResponse, WalletOwnershipProofResponse
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
