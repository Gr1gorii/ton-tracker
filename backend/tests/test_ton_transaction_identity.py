"""Strict tests for the TON account-transaction identity contract."""

from __future__ import annotations

import pytest

from services.ton_transaction_identity import (
    TON_TRANSACTION_IDENTITY_UNAVAILABLE,
    TON_TRANSACTION_IDENTITY_VERSION,
    derive_ton_transaction_identity,
    unavailable_ton_transaction_identity,
)


ACCOUNT = "0:" + "ab" * 32
HASH = "cd" * 32
LT = "89089355000001"


def _derive(**overrides):
    values = {
        "network": "ton-mainnet",
        "account_address_canonical": ACCOUNT,
        "account_identity_status": "network_scoped",
        "account_identity_version": "ton_std_address_v1",
        "account_workchain_id": 0,
        "account_id_hex": "ab" * 32,
        "logical_time": LT,
        "transaction_hash": HASH,
        "data_mode": "real",
        "source_status": "live",
        "provider": "tonapi",
    }
    values.update(overrides)
    if "raw" not in values:
        values["raw"] = {
            "provider": "tonapi",
            "surface": "transactions",
            "tx_hash": values["transaction_hash"],
            "logical_time": values["logical_time"],
        }
    return derive_ton_transaction_identity(**values)


def test_live_account_transaction_tuple_is_exact_and_network_scoped():
    identity = _derive()

    assert identity.status == "network_scoped"
    assert identity.version == TON_TRANSACTION_IDENTITY_VERSION
    assert identity.network == "ton-mainnet"
    assert identity.account_canonical == ACCOUNT
    assert identity.logical_time_canonical == LT
    assert identity.hash_canonical == HASH
    assert identity.key == (
        f"{TON_TRANSACTION_IDENTITY_VERSION}|ton-mainnet|{ACCOUNT}|{LT}|{HASH}"
    )
    assert identity.scoped_key == ("ton-mainnet", ACCOUNT, LT, HASH)
    assert identity.is_deduplication_identity is True
    assert identity.is_blockchain_proof_verified is False
    assert identity.is_ownership_proof is False
    assert identity.deduplication_applied is False
    assert identity.used_by_pnl is False


def test_hash_is_canonicalized_to_lowercase():
    identity = _derive(transaction_hash=HASH.upper())

    assert identity.status == "network_scoped"
    assert identity.hash_canonical == HASH


def test_network_is_part_of_transaction_identity():
    mainnet = _derive(network="ton-mainnet")
    testnet = _derive(network="ton-testnet")

    assert mainnet.scoped_key != testnet.scoped_key
    assert testnet.scoped_key == ("ton-testnet", ACCOUNT, LT, HASH)


def test_schema_boundary_tuple_fits_the_192_character_key_contract():
    boundary_account = f"{-2**31}:{'ef' * 32}"
    boundary_lt = str(2**64 - 1)
    identity = _derive(
        account_address_canonical=boundary_account,
        account_workchain_id=-(2**31),
        account_id_hex="ef" * 32,
        logical_time=boundary_lt,
    )

    assert identity.status == "network_scoped"
    assert identity.scoped_key == (
        "ton-mainnet",
        boundary_account,
        boundary_lt,
        HASH,
    )
    assert identity.key is not None
    assert len(identity.key) == 192


@pytest.mark.parametrize(
    "overrides",
    [
        {"network": "ton-unknown"},
        {"network": "mainnet"},
        {"account_address_canonical": None},
        {"account_address_canonical": ACCOUNT.upper()},
        {"account_address_canonical": "EQnot-raw"},
        {"account_identity_status": "unavailable"},
        {"account_identity_version": "unavailable"},
        {"account_identity_version": "unknown_identity_v9"},
        {"account_workchain_id": -1},
        {"account_id_hex": "ef" * 32},
        {"logical_time": None},
        {"logical_time": int(LT)},
        {"logical_time": "0"},
        {"logical_time": "01"},
        {"logical_time": " 1"},
        {"logical_time": str(2**64)},
        {"transaction_hash": None},
        {"transaction_hash": "a" * 63},
        {"transaction_hash": "g" * 64},
        {"transaction_hash": f" {HASH}"},
        {"data_mode": "mock"},
        {"source_status": "mock"},
        {"provider": "another_provider"},
        {"raw": None},
        {"raw": {}},
        {
            "raw": {
                "provider": "tonapi",
                "surface": "swaps",
                "tx_hash": HASH,
                "logical_time": LT,
            }
        },
        {
            "raw": {
                "provider": "tonapi",
                "surface": "transactions",
                "tx_hash": "ef" * 32,
                "logical_time": LT,
            }
        },
        {
            "raw": {
                "provider": "tonapi",
                "surface": "transactions",
                "tx_hash": HASH,
                "logical_time": "1",
            }
        },
    ],
)
def test_incomplete_or_non_live_tuple_is_unavailable(overrides):
    identity = _derive(**overrides)

    assert identity == unavailable_ton_transaction_identity()
    assert identity.status == "unavailable"
    assert identity.version == TON_TRANSACTION_IDENTITY_UNAVAILABLE
    assert identity.scoped_key is None
    assert identity.is_deduplication_identity is False
    assert identity.is_blockchain_proof_verified is False


def test_public_record_is_self_contained_and_proof_safe():
    assert _derive().to_public_dict() == {
        "status": "network_scoped",
        "version": TON_TRANSACTION_IDENTITY_VERSION,
        "network": "ton-mainnet",
        "account_canonical": ACCOUNT,
        "logical_time_canonical": LT,
        "hash_canonical": HASH,
        "key": (
            f"{TON_TRANSACTION_IDENTITY_VERSION}|ton-mainnet|{ACCOUNT}|{LT}|{HASH}"
        ),
        "is_deduplication_identity": True,
        "is_blockchain_proof_verified": False,
        "is_ownership_proof": False,
        "deduplication_applied": False,
        "used_by_pnl": False,
    }
