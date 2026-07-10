"""Provider-free TEP-74 payload observations from locally verified BOCs."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from typing import Any

from pytoniq_core import Cell
from pytoniq_core.tlb.transaction import Transaction
from sqlalchemy.orm import Session

from models import WalletTraceBocVerification
from services.wallet_trace_boc_verification import (
    WalletTraceBocVerificationConflict,
    _message_hashes,
    get_wallet_transaction_boc_message_evidence,
)


JETTON_PAYLOAD_OBSERVATIONS_CONTRACT_VERSION = (
    "ton_jetton_payload_observations_v1"
)
JETTON_PAYLOAD_IDENTITY_VERSION = "ton_jetton_payload_obs_v1"

_OPCODE_TO_OPERATION = {
    0x0F8A7EA5: ("transfer", "active"),
    0x7362D09C: ("transfer_notification", "active"),
    0xD53276DB: ("excesses", "active"),
    0x595F07BC: ("burn", "active"),
    0x178D4519: ("internal_transfer", "suggested"),
    0x7BDD97DE: ("burn_notification", "suggested"),
}


class WalletJettonPayloadConflict(ValueError):
    """A recognized payload or its verified BOC binding was incoherent."""


def get_wallet_transaction_jetton_payload_observations(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any] | None:
    """Decode bounded TEP-74 message bodies after full BOC revalidation."""
    message_evidence = get_wallet_transaction_boc_message_evidence(
        run_id,
        transaction_hash,
        session,
    )
    if message_evidence is None:
        return None
    verification = session.get(
        WalletTraceBocVerification,
        int(message_evidence["verification_id"], 10),
    )
    if verification is None:
        raise WalletJettonPayloadConflict(
            "Locally verified BOC storage disappeared during payload decoding."
        )
    body_rows = _load_verified_body_rows(verification, message_evidence)
    return _build_response(message_evidence, body_rows)


def _build_response(
    message_evidence: dict[str, Any],
    body_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    source_messages = message_evidence["messages"]
    if len(body_rows) != len(source_messages):
        raise WalletJettonPayloadConflict(
            "Verified message body count changed during payload decoding."
        )
    observations = []
    for source, body_row in zip(source_messages, body_rows):
        if body_row["message_hash"] != source["message_hash"]:
            raise WalletJettonPayloadConflict(
                "Verified message order changed during payload decoding."
            )
        decoded = _decode_jetton_payload(body_row["body"])
        if decoded is None:
            continue
        identity_document = {
            "identity_version": JETTON_PAYLOAD_IDENTITY_VERSION,
            "network": message_evidence["network"],
            "transaction_hash": source["transaction_hash"],
            "message_hash": source["message_hash"],
            "body_hash": source["body_hash"],
            "opcode_hex": source["opcode_hex"],
            "decoded": decoded,
        }
        observations.append(
            {
                "ordinal": len(observations),
                "payload_observation_identity": _digest_json(identity_document),
                "transaction_preorder_index": source[
                    "transaction_preorder_index"
                ],
                "transaction_hash": source["transaction_hash"],
                "message_role": source["role"],
                "message_ordinal": source["ordinal"],
                "message_hash": source["message_hash"],
                "message_source_account_canonical": source[
                    "source_account_canonical"
                ],
                "message_destination_account_canonical": source[
                    "destination_account_canonical"
                ],
                "message_native_value_nanoton": source["value_nanoton"],
                "body_hash": source["body_hash"],
                "opcode_hex": source["opcode_hex"],
                **decoded,
            }
        )
    operation_counts = Counter(row["operation"] for row in observations)
    operations = [
        {"operation": operation, "count": operation_counts[operation]}
        for operation in sorted(operation_counts)
    ]
    document = {
        "contract_version": JETTON_PAYLOAD_OBSERVATIONS_CONTRACT_VERSION,
        "identity_version": JETTON_PAYLOAD_IDENTITY_VERSION,
        "verification_evidence_digest_sha256": message_evidence[
            "verification_evidence_digest_sha256"
        ],
        "message_evidence_digest_sha256": message_evidence[
            "message_evidence_digest_sha256"
        ],
        "source_message_count": message_evidence["message_count"],
        "recognized_message_count": len(observations),
        "unrecognized_message_count": len(source_messages) - len(observations),
        "operations": operations,
        "observations": observations,
    }
    return {
        **document,
        "verification_id": message_evidence["verification_id"],
        "capture_id": message_evidence["capture_id"],
        "run_id": message_evidence["run_id"],
        "provider": "tonapi",
        "source_status": "live",
        "network": message_evidence["network"],
        "anchor": message_evidence["anchor"],
        "payload_observations_digest_sha256": _digest_json(document),
        "tep74_decoder_applied": True,
        "recognized_payload_semantics_applied": bool(observations),
        "query_id_is_correlation_only": True,
        "message_bodies_returned": False,
        "jetton_wallet_contract_role_is_observation_only": True,
        "jetton_master_identity_applied": False,
        "jetton_asset_identity_applied": False,
        "is_authoritative_jetton_transfer_ledger": False,
        "activity_merge_applied": False,
        "deduplication_applied": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "is_ownership_proof": False,
        "message": (
            "Recognized TEP-74 payload layouts were decoded locally from "
            "fully revalidated transaction BOCs. Payload contents remain "
            "hidden; contract roles, master identity, asset identity, "
            "ownership, cost basis, and PnL are not inferred."
        ),
    }


def _load_verified_body_rows(
    verification: WalletTraceBocVerification,
    message_evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    transaction_rows = {
        row.preorder_index: row
        for row in verification.transactions
    }
    parsed_by_preorder: dict[int, Any] = {}
    for preorder_index, row in transaction_rows.items():
        try:
            roots = Cell.from_boc(bytes.fromhex(row.transaction_boc_hex))
            if len(roots) != 1 or roots[0].hash.hex() != row.transaction_hash:
                raise ValueError("transaction root changed")
            cell_slice = roots[0].begin_parse()
            parsed = Transaction.deserialize(cell_slice)
            if cell_slice.remaining_bits or cell_slice.remaining_refs:
                raise ValueError("transaction root has trailing data")
        except Exception as exc:
            raise WalletJettonPayloadConflict(
                "Stored transaction BOC could not be reparsed for payload decoding."
            ) from exc
        parsed_by_preorder[preorder_index] = parsed

    body_rows = []
    for source in message_evidence["messages"]:
        preorder = source["transaction_preorder_index"]
        parsed = parsed_by_preorder.get(preorder)
        if parsed is None:
            raise WalletJettonPayloadConflict(
                "Verified payload transaction coordinate is missing."
            )
        if source["role"] in ("root_inbound", "child_inbound"):
            candidates = [] if parsed.in_msg is None else [parsed.in_msg]
        else:
            candidates = [
                message
                for message in parsed.out_msgs
                if _message_hashes(message)[0] == source["message_hash"]
            ]
        if len(candidates) != 1:
            raise WalletJettonPayloadConflict(
                "Verified payload message coordinate is ambiguous."
            )
        message = candidates[0]
        provider_hash = _message_hashes(message)[0]
        body = message.body
        opcode = (
            None
            if len(body.bits) < 32
            else f"0x{body.begin_parse().preload_uint(32):08x}"
        )
        if (
            provider_hash != source["message_hash"]
            or body.hash.hex() != source["body_hash"]
            or len(body.bits) != source["body_bit_length"]
            or len(body.refs) != source["body_ref_count"]
            or opcode != source["opcode_hex"]
        ):
            raise WalletJettonPayloadConflict(
                "Verified message body changed during payload decoding."
            )
        body_rows.append({"message_hash": provider_hash, "body": body})
    return body_rows


def _decode_jetton_payload(body: Cell) -> dict[str, Any] | None:
    if len(body.bits) < 32:
        return None
    opcode = body.begin_parse().preload_uint(32)
    operation_metadata = _OPCODE_TO_OPERATION.get(opcode)
    if operation_metadata is None:
        return None
    operation, standard_status = operation_metadata
    source = body.begin_parse()
    try:
        if source.load_uint(32) != opcode:
            raise ValueError("opcode changed")
        decoded: dict[str, Any] = {
            "operation": operation,
            "standard_status": standard_status,
            "query_id": str(source.load_uint(64)),
            "amount_base_units": None,
            "destination_account_canonical": None,
            "response_destination_account_canonical": None,
            "sender_account_canonical": None,
            "from_account_canonical": None,
            "forward_ton_amount_nanoton": None,
            "custom_payload_present": False,
            "custom_payload_hash": None,
            "forward_payload_in_ref": None,
            "forward_payload_hash": None,
            "forward_payload_bit_length": None,
            "forward_payload_ref_count": None,
            "contract_account_role": _contract_role(operation),
        }
        if operation == "transfer":
            decoded["amount_base_units"] = str(source.load_coins())
            decoded["destination_account_canonical"] = _address(
                source.load_address()
            )
            decoded["response_destination_account_canonical"] = _address(
                source.load_address(),
                allow_none=True,
            )
            custom_payload = source.load_maybe_ref()
            decoded["custom_payload_present"] = custom_payload is not None
            decoded["custom_payload_hash"] = (
                None if custom_payload is None else custom_payload.hash.hex()
            )
            decoded["forward_ton_amount_nanoton"] = str(source.load_coins())
            decoded.update(_forward_payload(source))
        elif operation == "transfer_notification":
            decoded["amount_base_units"] = str(source.load_coins())
            decoded["sender_account_canonical"] = _address(
                source.load_address()
            )
            decoded.update(_forward_payload(source))
        elif operation == "burn":
            decoded["amount_base_units"] = str(source.load_coins())
            decoded["response_destination_account_canonical"] = _address(
                source.load_address(),
                allow_none=True,
            )
            custom_payload = source.load_maybe_ref()
            decoded["custom_payload_present"] = custom_payload is not None
            decoded["custom_payload_hash"] = (
                None if custom_payload is None else custom_payload.hash.hex()
            )
            _require_consumed(source)
        elif operation == "internal_transfer":
            decoded["amount_base_units"] = str(source.load_coins())
            decoded["from_account_canonical"] = _address(
                source.load_address(),
                allow_none=True,
            )
            decoded["response_destination_account_canonical"] = _address(
                source.load_address(),
                allow_none=True,
            )
            decoded["forward_ton_amount_nanoton"] = str(source.load_coins())
            decoded.update(_forward_payload(source))
        elif operation == "burn_notification":
            decoded["amount_base_units"] = str(source.load_coins())
            decoded["sender_account_canonical"] = _address(
                source.load_address()
            )
            decoded["response_destination_account_canonical"] = _address(
                source.load_address(),
                allow_none=True,
            )
            _require_consumed(source)
        elif operation == "excesses":
            _require_consumed(source)
        else:  # pragma: no cover - the opcode table is exhaustive
            raise ValueError("unsupported operation")
        return decoded
    except WalletJettonPayloadConflict:
        raise
    except Exception as exc:
        raise WalletJettonPayloadConflict(
            "A recognized TEP-74 payload failed strict local decoding."
        ) from exc


def _forward_payload(source: Any) -> dict[str, Any]:
    in_ref = bool(source.load_bit())
    if in_ref:
        payload = source.load_ref()
        _require_consumed(source)
    else:
        payload = source.to_cell()
    return {
        "forward_payload_in_ref": in_ref,
        "forward_payload_hash": payload.hash.hex(),
        "forward_payload_bit_length": len(payload.bits),
        "forward_payload_ref_count": len(payload.refs),
    }


def _require_consumed(source: Any) -> None:
    if source.remaining_bits or source.remaining_refs:
        raise WalletJettonPayloadConflict(
            "A recognized TEP-74 payload contains trailing data."
        )


def _address(value: Any, *, allow_none: bool = False) -> str | None:
    if value is None and allow_none:
        return None
    try:
        result = value.to_str(is_user_friendly=False)
    except (AttributeError, TypeError, ValueError) as exc:
        raise WalletJettonPayloadConflict(
            "A recognized TEP-74 payload uses a non-canonical address."
        ) from exc
    if not isinstance(result, str) or ":" not in result:
        raise WalletJettonPayloadConflict(
            "A recognized TEP-74 payload address is not canonical."
        )
    return result


def _contract_role(operation: str) -> str:
    return {
        "transfer": "destination_jetton_wallet_observed",
        "internal_transfer": "destination_jetton_wallet_observed",
        "transfer_notification": "source_jetton_wallet_observed",
        "burn": "destination_jetton_wallet_observed",
        "burn_notification": "destination_jetton_master_observed",
        "excesses": "unresolved_contract_role",
    }[operation]


def _digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "JETTON_PAYLOAD_OBSERVATIONS_CONTRACT_VERSION",
    "JETTON_PAYLOAD_IDENTITY_VERSION",
    "WalletJettonPayloadConflict",
    "get_wallet_transaction_jetton_payload_observations",
]
