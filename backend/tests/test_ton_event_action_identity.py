"""Strict tests for provider-scoped TonAPI event-action identity."""

from __future__ import annotations

import pytest

from services.ton_event_action_identity import (
    TON_EVENT_ACTION_IDENTITY_UNAVAILABLE,
    TON_EVENT_ACTION_IDENTITY_VERSION,
    derive_ton_event_action_identity,
    unavailable_ton_event_action_identity,
)


ACCOUNT = "0:" + "ab" * 32
EVENT_ID = "cd" * 32
LT = "89089355000001"


def _derive(**overrides):
    values = {
        "network": "ton-mainnet",
        "account_address_canonical": ACCOUNT,
        "account_identity_status": "network_scoped",
        "account_identity_version": "ton_std_address_v1",
        "account_workchain_id": 0,
        "account_id_hex": "ab" * 32,
        "event_id": EVENT_ID,
        "logical_time": LT,
        "action_index": 2,
        "action_type": "JettonSwap",
        "surface": "swaps",
        "data_mode": "real",
        "source_status": "live",
        "provider": "tonapi",
    }
    values.update(overrides)
    if "raw" not in values:
        values["raw"] = {
            "provider": "tonapi",
            "surface": values["surface"],
            "event_id": values["event_id"],
            "lt": values["logical_time"],
            "action_index": values["action_index"],
            "action_type": values["action_type"],
            "source": "tonapi",
        }
    return derive_ton_event_action_identity(**values)


def test_live_tonapi_action_tuple_is_provider_scoped_and_non_authoritative():
    identity = _derive()

    assert identity.status == "provider_scoped"
    assert identity.version == TON_EVENT_ACTION_IDENTITY_VERSION
    assert identity.provider == "tonapi"
    assert identity.network == "ton-mainnet"
    assert identity.account_canonical == ACCOUNT
    assert identity.event_id_canonical == EVENT_ID
    assert identity.logical_time_canonical == LT
    assert identity.action_index == 2
    assert identity.action_type == "JettonSwap"
    assert identity.key == (
        f"{TON_EVENT_ACTION_IDENTITY_VERSION}|tonapi|ton-mainnet|{ACCOUNT}|"
        f"{EVENT_ID}|{LT}|2"
    )
    assert identity.scoped_key == (
        "ton-mainnet",
        ACCOUNT,
        EVENT_ID,
        LT,
        2,
    )
    assert identity.is_provider_observation_identity is True
    assert identity.is_blockchain_proof_verified is False
    assert identity.is_authoritative_activity_identity is False
    assert identity.is_ownership_proof is False
    assert identity.eligible_for_cost_basis is False
    assert identity.deduplication_applied is False
    assert identity.used_by_pnl is False


def test_event_id_is_canonicalized_and_action_ordinal_changes_identity():
    uppercase = _derive(event_id=EVENT_ID.upper())
    next_action = _derive(action_index=3)

    assert uppercase.event_id_canonical == EVENT_ID
    assert uppercase.key == _derive().key
    assert next_action.key != uppercase.key


def test_transfer_action_types_are_provider_scoped_on_transfer_surface():
    ton_transfer = _derive(
        surface="transfers",
        action_type="TonTransfer",
        action_index=0,
    )
    jetton_transfer = _derive(
        surface="transfers",
        action_type="JettonTransfer",
        action_index=1,
    )

    assert ton_transfer.status == "provider_scoped"
    assert jetton_transfer.status == "provider_scoped"
    assert ton_transfer.key != jetton_transfer.key


def test_retyped_provider_coordinate_keeps_the_same_observation_key():
    transfer = _derive(
        surface="transfers",
        action_type="TonTransfer",
        action_index=0,
    )
    swap = _derive(
        surface="swaps",
        action_type="JettonSwap",
        action_index=0,
    )

    assert transfer.status == "provider_scoped"
    assert swap.status == "provider_scoped"
    assert transfer.key == swap.key


def test_schema_boundary_tuple_fits_256_character_key_contract():
    identity = _derive(
        account_address_canonical=f"{-2**31}:{'ef' * 32}",
        account_workchain_id=-(2**31),
        account_id_hex="ef" * 32,
        logical_time=str(2**64 - 1),
        action_index=2**31 - 1,
    )

    assert identity.status == "provider_scoped"
    assert identity.key is not None
    assert len(identity.key) <= 256


@pytest.mark.parametrize(
    "overrides",
    [
        {"network": "ton-unknown"},
        {"network": "mainnet"},
        {"account_address_canonical": None},
        {"account_address_canonical": ACCOUNT.upper()},
        {"account_identity_status": "unavailable"},
        {"account_identity_version": "unavailable"},
        {"account_workchain_id": -1},
        {"account_workchain_id": False},
        {"account_id_hex": "ef" * 32},
        {"event_id": None},
        {"event_id": "a" * 63},
        {"event_id": "g" * 64},
        {"logical_time": None},
        {"logical_time": int(LT)},
        {"logical_time": "0"},
        {"logical_time": "01"},
        {"logical_time": str(2**64)},
        {"action_index": None},
        {"action_index": True},
        {"action_index": 0.0},
        {"action_index": "0"},
        {"action_index": -1},
        {"action_index": 2**31},
        {"action_type": "TonTransfer"},
        {"surface": "transactions"},
        {"data_mode": "mock"},
        {"source_status": "mock"},
        {"provider": "another_provider"},
        {"raw": None},
        {"raw": {}},
        {
            "raw": {
                "provider": "tonapi",
                "surface": "swaps",
                "event_id": "ef" * 32,
                "lt": LT,
                "action_index": 2,
                "action_type": "JettonSwap",
                "source": "tonapi",
            }
        },
        {
            "raw": {
                "provider": "tonapi",
                "surface": "swaps",
                "event_id": EVENT_ID,
                "lt": "1",
                "action_index": 2,
                "action_type": "JettonSwap",
                "source": "tonapi",
            }
        },
        {
            "raw": {
                "provider": "tonapi",
                "surface": "swaps",
                "event_id": EVENT_ID,
                "lt": LT,
                "action_index": 1,
                "action_type": "JettonSwap",
                "source": "tonapi",
            }
        },
        {
            "action_index": 0,
            "raw": {
                "provider": "tonapi",
                "surface": "swaps",
                "event_id": EVENT_ID,
                "lt": LT,
                "action_index": False,
                "action_type": "JettonSwap",
                "source": "tonapi",
            },
        },
        {
            "action_index": 0,
            "raw": {
                "provider": "tonapi",
                "surface": "swaps",
                "event_id": EVENT_ID,
                "lt": LT,
                "action_index": 0.0,
                "action_type": "JettonSwap",
                "source": "tonapi",
            },
        },
        {
            "raw": {
                "provider": "tonapi",
                "surface": "swaps",
                "event_id": EVENT_ID,
                "lt": LT,
                "action_index": 2,
                "action_type": "JettonSwap",
            }
        },
    ],
)
def test_incomplete_or_non_live_action_tuple_is_unavailable(overrides):
    identity = _derive(**overrides)

    assert identity == unavailable_ton_event_action_identity()
    assert identity.status == "unavailable"
    assert identity.version == TON_EVENT_ACTION_IDENTITY_UNAVAILABLE
    assert identity.scoped_key is None
    assert identity.is_provider_observation_identity is False
    assert identity.is_authoritative_activity_identity is False


def test_public_record_is_self_contained_and_proof_safe():
    record = _derive().to_public_dict()

    assert record["status"] == "provider_scoped"
    assert record["provider"] == "tonapi"
    assert record["event_id_canonical"] == EVENT_ID
    assert record["action_index"] == 2
    assert record["action_type"] == "JettonSwap"
    assert record["is_provider_observation_identity"] is True
    assert record["is_blockchain_proof_verified"] is False
    assert record["is_authoritative_activity_identity"] is False
    assert record["is_ownership_proof"] is False
    assert record["eligible_for_cost_basis"] is False
    assert record["deduplication_applied"] is False
    assert record["used_by_pnl"] is False
