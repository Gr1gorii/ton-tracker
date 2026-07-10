"""Tests for multi-run jetton, asset, fee, and PnL-readiness evidence."""

from decimal import Decimal
import json
from types import SimpleNamespace

import pytest

from schemas import WalletMultiAssetPnlReadinessResponse
import services.wallet_multi_asset_pnl_readiness as readiness


ACCOUNT = "0:" + "11" * 32
JETTON_WALLET = "0:" + "22" * 32
JETTON_MASTER = "0:" + "33" * 32
TRANSACTION_HASH = "44" * 32
MESSAGE_HASH = "55" * 32
PAYLOAD_IDENTITY = "66" * 32


def _native() -> dict:
    return {
        "selected_run_ids": [1, 2],
        "network": "ton-mainnet",
        "wallet_account_canonical": ACCOUNT,
        "analysis_digest_sha256": "77" * 32,
        "flow_summary": {
            "asset_identity_key": "ton_native_asset_v1|ton-mainnet",
            "activity_count": 1,
            "incoming_activity_count": 0,
            "outgoing_activity_count": 1,
            "self_activity_count": 0,
            "incoming_nanoton": "0",
            "outgoing_nanoton": "1000000000",
            "self_nanoton": "0",
            "net_nanoton": "-1000000000",
            "incoming_ton": "0",
            "outgoing_ton": "1",
            "self_ton": "0",
            "net_ton": "-1",
        },
    }


def _observation(**overrides) -> dict:
    result = {
        "ordinal": 0,
        "payload_observation_identity": PAYLOAD_IDENTITY,
        "transaction_preorder_index": 0,
        "transaction_hash": TRANSACTION_HASH,
        "message_role": "remaining_outbound",
        "message_ordinal": 0,
        "message_hash": MESSAGE_HASH,
        "message_source_account_canonical": ACCOUNT,
        "message_destination_account_canonical": JETTON_WALLET,
        "message_native_value_nanoton": "100000000",
        "body_hash": "88" * 32,
        "opcode_hex": "0x0f8a7ea5",
        "operation": "transfer",
        "standard_status": "active",
        "query_id": "9",
        "amount_base_units": "123",
        "destination_account_canonical": ACCOUNT,
        "response_destination_account_canonical": ACCOUNT,
        "sender_account_canonical": None,
        "from_account_canonical": None,
        "forward_ton_amount_nanoton": "1",
        "custom_payload_present": False,
        "custom_payload_hash": None,
        "forward_payload_in_ref": True,
        "forward_payload_hash": "99" * 32,
        "forward_payload_bit_length": 0,
        "forward_payload_ref_count": 0,
        "contract_account_role": "destination_jetton_wallet_observed",
    }
    result.update(overrides)
    return result


def _snapshot_index() -> dict:
    return {
        ("jetton_wallet", JETTON_WALLET): {
            "jetton_master_account_canonical": JETTON_MASTER,
            "wallet_contract_account_canonical": JETTON_WALLET,
            "provider_asset_observation_key": (
                "tonapi_jetton_snapshot_v1|ton-mainnet|" + JETTON_MASTER
            ),
            "decimals": 9,
            "symbol": "JET",
            "source_run_ids": [1, 2],
        }
    }


def _occurrences() -> list[dict]:
    observation = _observation()
    return [
        {
            "run_id": 1,
            "capture_id": 10,
            "verification_id": 20,
            "observation": observation,
        },
        {
            "run_id": 2,
            "capture_id": 11,
            "verification_id": 21,
            "observation": {**observation, "ordinal": 3},
        },
    ]


def test_valid_snapshot_requires_canonical_wallet_and_master_addresses():
    snapshot = SimpleNamespace(
        run_id=1,
        provider="tonapi",
        source_status="live",
        raw_json=json.dumps(
            {
                "surface": "jettons",
                "jetton_address": JETTON_MASTER,
                "wallet_contract_address": JETTON_WALLET,
                "decimals": 9,
                "jetton_symbol": "JET",
            }
        ),
    )

    result = readiness._validated_snapshot(snapshot, "ton-mainnet")

    assert result["jetton_master_account_canonical"] == JETTON_MASTER
    assert result["wallet_contract_account_canonical"] == JETTON_WALLET
    assert result["source_run_ids"] == [1]


def test_legacy_stringified_wallet_object_is_not_guessed():
    snapshot = SimpleNamespace(
        run_id=1,
        provider="tonapi",
        source_status="live",
        raw_json=json.dumps(
            {
                "surface": "jettons",
                "jetton_address": JETTON_MASTER,
                "wallet_contract_address": "{'address': '" + JETTON_WALLET + "'}",
                "decimals": 9,
            }
        ),
    )

    assert readiness._validated_snapshot(snapshot, "ton-mainnet") is None


def test_payload_occurrences_deduplicate_and_bind_asset_and_fee():
    rows = readiness._deduplicate_and_bind(
        _occurrences(),
        _snapshot_index(),
        {TRANSACTION_HASH: {"fee_nanoton": 468567, "source_run_ids": [1]}},
    )

    assert len(rows) == 1
    assert rows[0]["occurrence_count"] == 2
    assert rows[0]["source_run_ids"] == [1, 2]
    assert rows[0]["occurrences"] == [
        {"run_id": 1, "capture_id": 10, "verification_id": 20},
        {"run_id": 2, "capture_id": 11, "verification_id": 21},
    ]
    assert rows[0]["asset_binding_status"] == "provider_snapshot_match"
    assert rows[0]["jetton_master_account_canonical"] == JETTON_MASTER
    assert rows[0]["transaction_fee_nanoton"] == "468567"
    assert rows[0]["transaction_fee_ton"] == "0.000468567"
    assert rows[0]["fee_allocation_applied"] is False


def test_same_payload_identity_with_changed_semantics_fails_closed():
    occurrences = _occurrences()
    occurrences[1]["observation"] = _observation(query_id="10")

    with pytest.raises(
        readiness.WalletMultiAssetPnlReadinessConflict,
        match="conflicting semantics",
    ):
        readiness._deduplicate_and_bind(occurrences, {}, {})


def test_full_readiness_uses_evidence_without_unlocking_pnl(monkeypatch):
    monkeypatch.setattr(
        readiness,
        "build_native_activity_pnl_readiness",
        lambda _target, _runs, _session: _native(),
    )
    monkeypatch.setattr(
        readiness,
        "_load_asset_snapshot_index",
        lambda _runs, _network, _session: {
            "index": _snapshot_index(),
            "snapshot_count": 2,
            "valid_count": 2,
            "invalid_count": 0,
        },
    )
    monkeypatch.setattr(
        readiness,
        "_load_transaction_fee_index",
        lambda _runs, _network, _session: {
            TRANSACTION_HASH: {"fee_nanoton": 468567, "source_run_ids": [1]}
        },
    )
    monkeypatch.setattr(
        readiness,
        "_collect_payload_observations",
        lambda _runs, _session: {
            "selected_capture_count": 2,
            "verified_capture_count": 2,
            "source_message_count": 3,
            "unrecognized_message_count": 1,
            "occurrences": _occurrences(),
        },
    )

    first = readiness.build_multi_asset_pnl_readiness(2, [2, 1], None)
    second = readiness.build_multi_asset_pnl_readiness(2, [1, 2], None)

    assert first["jetton_evidence_summary"][
        "deduplicated_payload_observation_count"
    ] == 1
    assert first["jetton_evidence_summary"][
        "suppressed_payload_occurrence_count"
    ] == 1
    assert [row["available"] for row in first["requirements"][:4]] == [
        True,
        True,
        True,
        True,
    ]
    assert all(not row["available"] for row in first["requirements"][4:])
    assert first["used_by_pnl_calculation"] is False
    assert first["eligible_for_cost_basis"] is False
    assert first["real_pnl_locked"] is True
    assert first["analysis_digest_sha256"] == second["analysis_digest_sha256"]
    WalletMultiAssetPnlReadinessResponse.model_validate(first)


def test_zero_recognized_payloads_remain_explicitly_blocked(monkeypatch):
    monkeypatch.setattr(
        readiness,
        "build_native_activity_pnl_readiness",
        lambda _target, _runs, _session: _native(),
    )
    monkeypatch.setattr(
        readiness,
        "_load_asset_snapshot_index",
        lambda _runs, _network, _session: {
            "index": {},
            "snapshot_count": 4,
            "valid_count": 0,
            "invalid_count": 4,
        },
    )
    monkeypatch.setattr(
        readiness,
        "_load_transaction_fee_index",
        lambda _runs, _network, _session: {},
    )
    monkeypatch.setattr(
        readiness,
        "_collect_payload_observations",
        lambda _runs, _session: {
            "selected_capture_count": 2,
            "verified_capture_count": 2,
            "source_message_count": 4,
            "unrecognized_message_count": 4,
            "occurrences": [],
        },
    )

    result = readiness.build_multi_asset_pnl_readiness(2, [1, 2], None)

    assert result["evidence"] == []
    assert result["requirements"][1]["available"] is False
    assert result["provider_asset_evidence_used_by_pnl_readiness"] is False
    assert result["transaction_fee_evidence_used_by_pnl_readiness"] is False
    WalletMultiAssetPnlReadinessResponse.model_validate(result)


@pytest.mark.parametrize(
    ("fee_ton", "expected"),
    [(Decimal("0"), 0), (Decimal("0.000468567"), 468567)],
)
def test_fee_conversion_is_exact_nanoton(fee_ton, expected):
    assert readiness._fee_nanoton(fee_ton) == expected


def test_sub_nanoton_fee_fails_closed():
    with pytest.raises(
        readiness.WalletMultiAssetPnlReadinessConflict,
        match="exact non-negative nanoton",
    ):
        readiness._fee_nanoton(Decimal("0.0000000001"))


def test_selected_capture_bound_fails_before_boc_revalidation():
    class SessionStub:
        def scalars(self, _statement):
            return [object()] * (readiness.MAX_SELECTED_CAPTURES + 1)

    with pytest.raises(
        readiness.WalletMultiAssetPnlReadinessConflict,
        match="capture bound",
    ):
        readiness._collect_payload_observations([1, 2], SessionStub())
