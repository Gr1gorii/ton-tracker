"""Account-perspective native TON flow observations from verified BOC messages."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from services.wallet_trace_boc_verification import (
    get_wallet_transaction_boc_message_evidence,
)
from services.wallet_trace_evidence import (
    _require_eligible_stored_identity,
    resolve_wallet_transaction_trace_anchor,
)


NATIVE_TON_FLOW_CONTRACT_VERSION = "ton_native_flow_observations_v1"
NATIVE_TON_FLOW_IDENTITY_VERSION = "ton_native_message_flow_obs_v1"
NATIVE_TON_ASSET_BINDING_CONTRACT_VERSION = "ton_native_asset_binding_v1"
NATIVE_TON_ASSET_IDENTITY_VERSION = "ton_native_asset_v1"


def get_wallet_native_ton_flow_observations(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any] | None:
    """Derive bounded native TON movements involving the persisted run account."""
    run, transaction = resolve_wallet_transaction_trace_anchor(
        run_id,
        transaction_hash,
        session,
    )
    _require_eligible_stored_identity(run, transaction, transaction_hash)
    evidence = get_wallet_transaction_boc_message_evidence(
        run_id,
        transaction_hash,
        session,
    )
    if evidence is None:
        return None
    wallet = run.wallet_address_canonical
    if not isinstance(wallet, str):
        return None

    flows: list[dict[str, Any]] = []
    incoming = 0
    outgoing = 0
    self_amount = 0
    for message in evidence["messages"]:
        if message["message_type"] != "int_msg":
            continue
        source = message["source_account_canonical"]
        destination = message["destination_account_canonical"]
        if source != wallet and destination != wallet:
            continue
        if source == wallet and destination == wallet:
            direction = "self"
            counterparty = wallet
        elif destination == wallet:
            direction = "incoming"
            counterparty = source
        else:
            direction = "outgoing"
            counterparty = destination
        amount = int(message["value_nanoton"], 10)
        if direction == "incoming":
            incoming += amount
        elif direction == "outgoing":
            outgoing += amount
        else:
            self_amount += amount
        identity_material = "|".join(
            (
                NATIVE_TON_FLOW_IDENTITY_VERSION,
                evidence["network"],
                wallet,
                message["transaction_hash"],
                message["message_hash"],
                direction,
            )
        )
        flows.append(
            {
                "observation_identity": hashlib.sha256(
                    identity_material.encode("utf-8")
                ).hexdigest(),
                "transaction_preorder_index": message[
                    "transaction_preorder_index"
                ],
                "transaction_hash": message["transaction_hash"],
                "message_role": message["role"],
                "message_ordinal": message["ordinal"],
                "message_hash": message["message_hash"],
                "direction": direction,
                "wallet_account_canonical": wallet,
                "counterparty_account_observed": counterparty,
                "amount_nanoton": str(amount),
                "created_logical_time": message["created_logical_time"],
                "unix_time": message["unix_time"],
                "body_hash": message["body_hash"],
                "opcode_hex": message["opcode_hex"],
                "bounce": message["bounce"],
                "bounced": message["bounced"],
            }
        )

    return {
        "contract_version": NATIVE_TON_FLOW_CONTRACT_VERSION,
        "identity_version": NATIVE_TON_FLOW_IDENTITY_VERSION,
        "verification_id": evidence["verification_id"],
        "capture_id": evidence["capture_id"],
        "run_id": evidence["run_id"],
        "provider": "tonapi",
        "source_status": "live",
        "network": evidence["network"],
        "wallet_account_canonical": wallet,
        "anchor": evidence["anchor"],
        "message_evidence_digest_sha256": evidence[
            "message_evidence_digest_sha256"
        ],
        "flow_count": len(flows),
        "incoming_nanoton": str(incoming),
        "outgoing_nanoton": str(outgoing),
        "self_nanoton": str(self_amount),
        "flows": flows,
        "derived_from_verified_message_headers": True,
        "native_ton_only": True,
        "counterparty_is_header_observation": True,
        "is_authoritative_transfer_ledger": False,
        "semantic_payload_decoding_applied": False,
        "activity_merge_applied": False,
        "deduplication_applied": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "is_ownership_proof": False,
        "message": (
            "Native TON value directions were derived only from verified "
            "internal-message headers involving the stored run account. "
            "Counterparties are header observations, not authoritative actors."
        ),
    }


def get_wallet_native_ton_asset_binding(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any] | None:
    """Bind every native flow observation to one canonical network asset."""
    flows = get_wallet_native_ton_flow_observations(
        run_id,
        transaction_hash,
        session,
    )
    if flows is None:
        return None
    asset_identity_key = "|".join(
        (NATIVE_TON_ASSET_IDENTITY_VERSION, flows["network"])
    )
    bindings = [
        {
            "flow_observation_identity": flow["observation_identity"],
            "transaction_hash": flow["transaction_hash"],
            "message_hash": flow["message_hash"],
            "direction": flow["direction"],
            "amount_base_units": flow["amount_nanoton"],
            "asset_identity_key": asset_identity_key,
        }
        for flow in flows["flows"]
    ]
    document = {
        "contract_version": NATIVE_TON_ASSET_BINDING_CONTRACT_VERSION,
        "flow_message_evidence_digest_sha256": flows[
            "message_evidence_digest_sha256"
        ],
        "asset_identity_key": asset_identity_key,
        "bindings": bindings,
    }
    digest = hashlib.sha256(
        json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        "contract_version": NATIVE_TON_ASSET_BINDING_CONTRACT_VERSION,
        "verification_id": flows["verification_id"],
        "capture_id": flows["capture_id"],
        "run_id": flows["run_id"],
        "network": flows["network"],
        "wallet_account_canonical": flows["wallet_account_canonical"],
        "anchor": flows["anchor"],
        "flow_message_evidence_digest_sha256": flows[
            "message_evidence_digest_sha256"
        ],
        "asset": {
            "identity_version": NATIVE_TON_ASSET_IDENTITY_VERSION,
            "identity_key": asset_identity_key,
            "network": flows["network"],
            "kind": "native",
            "symbol": "TON",
            "name": "Toncoin",
            "decimals": 9,
            "base_unit": "nanoton",
            "master_address": None,
        },
        "binding_count": len(bindings),
        "bindings": bindings,
        "asset_binding_digest_sha256": digest,
        "canonical_native_asset_identity": True,
        "jetton_asset_identity_applied": False,
        "counterparty_identity_applied": False,
        "activity_merge_applied": False,
        "deduplication_applied": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "message": (
            "Every verified native TON flow observation is bound to the "
            "network-scoped Toncoin base-unit identity. Jetton and counterparty "
            "identity contracts are not applied."
        ),
    }


__all__ = [
    "NATIVE_TON_ASSET_BINDING_CONTRACT_VERSION",
    "NATIVE_TON_ASSET_IDENTITY_VERSION",
    "NATIVE_TON_FLOW_CONTRACT_VERSION",
    "NATIVE_TON_FLOW_IDENTITY_VERSION",
    "get_wallet_native_ton_flow_observations",
    "get_wallet_native_ton_asset_binding",
]
