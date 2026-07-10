"""Tests for strict provider-free TEP-74 payload observations."""

import pytest
from pytoniq_core import Address, Builder

from schemas import WalletJettonPayloadObservationsResponse
import services.wallet_jetton_payload_observations as jetton_service


ACCOUNT = "0:" + "11" * 32
DESTINATION = "0:" + "22" * 32
RESPONSE = "0:" + "33" * 32
MESSAGE_HASH = "44" * 32
TRANSACTION_HASH = "55" * 32


def _address(raw: str) -> Address:
    return Address(raw)


def _forward_payload():
    return Builder().store_uint(0, 32).store_string("invoice-7").end_cell()


def _transfer_body():
    custom = Builder().store_uint(7, 8).end_cell()
    return (
        Builder()
        .store_uint(0x0F8A7EA5, 32)
        .store_uint(9, 64)
        .store_coins(123456789)
        .store_address(_address(DESTINATION))
        .store_address(_address(RESPONSE))
        .store_maybe_ref(custom)
        .store_coins(25000000)
        .store_bit(1)
        .store_ref(_forward_payload())
        .end_cell()
    )


def _internal_transfer_body():
    return (
        Builder()
        .store_uint(0x178D4519, 32)
        .store_uint(10, 64)
        .store_coins(777)
        .store_address(_address(ACCOUNT))
        .store_address(_address(RESPONSE))
        .store_coins(1)
        .store_bit(0)
        .store_uint(0xAB, 8)
        .end_cell()
    )


def _message_evidence(body, opcode: int) -> dict:
    return {
        "verification_id": "1",
        "capture_id": "2",
        "run_id": "3",
        "network": "ton-mainnet",
        "anchor": {
            "transaction_hash": TRANSACTION_HASH,
            "logical_time": "1000",
            "account_canonical": ACCOUNT,
            "matches_stored_transaction": True,
        },
        "verification_evidence_digest_sha256": "66" * 32,
        "message_evidence_digest_sha256": "77" * 32,
        "message_count": 1,
        "messages": [
            {
                "transaction_preorder_index": 0,
                "transaction_hash": TRANSACTION_HASH,
                "role": "remaining_outbound",
                "ordinal": 0,
                "message_hash": MESSAGE_HASH,
                "source_account_canonical": ACCOUNT,
                "destination_account_canonical": DESTINATION,
                "value_nanoton": "100000000",
                "body_hash": body.hash.hex(),
                "opcode_hex": f"0x{opcode:08x}",
            }
        ],
    }


def test_transfer_payload_is_fully_decoded_without_returning_contents():
    body = _transfer_body()

    result = jetton_service._decode_jetton_payload(body)

    assert result["operation"] == "transfer"
    assert result["standard_status"] == "active"
    assert result["query_id"] == "9"
    assert result["amount_base_units"] == "123456789"
    assert result["destination_account_canonical"] == DESTINATION
    assert result["response_destination_account_canonical"] == RESPONSE
    assert result["custom_payload_present"] is True
    assert result["custom_payload_hash"]
    assert result["forward_ton_amount_nanoton"] == "25000000"
    assert result["forward_payload_in_ref"] is True
    assert result["forward_payload_hash"] == _forward_payload().hash.hex()


def test_suggested_internal_transfer_preserves_inline_payload_boundary():
    result = jetton_service._decode_jetton_payload(_internal_transfer_body())

    assert result["operation"] == "internal_transfer"
    assert result["standard_status"] == "suggested"
    assert result["from_account_canonical"] == ACCOUNT
    assert result["forward_payload_in_ref"] is False
    assert result["forward_payload_bit_length"] == 8
    assert result["contract_account_role"] == (
        "destination_jetton_wallet_observed"
    )


@pytest.mark.parametrize(
    ("opcode", "operation", "body"),
    [
        (
            0x7362D09C,
            "transfer_notification",
            lambda: Builder()
            .store_uint(0x7362D09C, 32)
            .store_uint(1, 64)
            .store_coins(2)
            .store_address(_address(ACCOUNT))
            .store_bit(1)
            .store_ref(_forward_payload())
            .end_cell(),
        ),
        (
            0xD53276DB,
            "excesses",
            lambda: Builder()
            .store_uint(0xD53276DB, 32)
            .store_uint(1, 64)
            .end_cell(),
        ),
        (
            0x595F07BC,
            "burn",
            lambda: Builder()
            .store_uint(0x595F07BC, 32)
            .store_uint(1, 64)
            .store_coins(2)
            .store_address(_address(RESPONSE))
            .store_maybe_ref(None)
            .end_cell(),
        ),
        (
            0x7BDD97DE,
            "burn_notification",
            lambda: Builder()
            .store_uint(0x7BDD97DE, 32)
            .store_uint(1, 64)
            .store_coins(2)
            .store_address(_address(ACCOUNT))
            .store_address(_address(RESPONSE))
            .end_cell(),
        ),
    ],
)
def test_supported_tep74_operations_decode(opcode, operation, body):
    result = jetton_service._decode_jetton_payload(body())
    assert result["operation"] == operation
    assert result["query_id"] == "1"


def test_recognized_malformed_payload_fails_closed():
    body = Builder().store_uint(0x0F8A7EA5, 32).store_uint(1, 64).end_cell()

    with pytest.raises(
        jetton_service.WalletJettonPayloadConflict,
        match="strict local decoding",
    ):
        jetton_service._decode_jetton_payload(body)


def test_response_is_digest_bound_and_keeps_asset_identity_false(monkeypatch):
    body = _transfer_body()
    evidence = _message_evidence(body, 0x0F8A7EA5)
    monkeypatch.setattr(
        jetton_service,
        "get_wallet_transaction_boc_message_evidence",
        lambda _run, _hash, _session: evidence,
    )
    monkeypatch.setattr(
        jetton_service,
        "_load_verified_body_rows",
        lambda _verification, _evidence: [
            {"message_hash": MESSAGE_HASH, "body": body}
        ],
    )

    class SessionStub:
        def get(self, _model, _identifier):
            return object()

    first = jetton_service.get_wallet_transaction_jetton_payload_observations(
        3, TRANSACTION_HASH, SessionStub()
    )
    second = jetton_service.get_wallet_transaction_jetton_payload_observations(
        3, TRANSACTION_HASH, SessionStub()
    )

    assert first["recognized_message_count"] == 1
    assert first["unrecognized_message_count"] == 0
    assert first["operations"] == [{"operation": "transfer", "count": 1}]
    assert first["jetton_master_identity_applied"] is False
    assert first["jetton_asset_identity_applied"] is False
    assert first["eligible_for_cost_basis"] is False
    assert first["used_by_pnl"] is False
    assert (
        first["payload_observations_digest_sha256"]
        == second["payload_observations_digest_sha256"]
    )
    WalletJettonPayloadObservationsResponse.model_validate(first)


def test_unknown_opcode_remains_visible_as_unrecognized_count(monkeypatch):
    body = Builder().store_uint(0xDEADBEEF, 32).end_cell()
    evidence = _message_evidence(body, 0xDEADBEEF)
    result = jetton_service._build_response(
        evidence,
        [{"message_hash": MESSAGE_HASH, "body": body}],
    )

    assert result["recognized_message_count"] == 0
    assert result["unrecognized_message_count"] == 1
    assert result["recognized_payload_semantics_applied"] is False
    WalletJettonPayloadObservationsResponse.model_validate(result)
