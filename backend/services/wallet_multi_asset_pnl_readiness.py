"""Provider-free multi-run jetton, asset, fee, and PnL-readiness evidence."""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import (
    WalletBalanceSnapshot,
    WalletJettonContractVerification,
    WalletTraceEvidenceCapture,
    WalletTransaction,
)
from services.ton_address_identity import derive_ton_wallet_identity
from services.wallet_jetton_payload_observations import (
    get_wallet_transaction_jetton_payload_observations,
)
from services.wallet_native_activity_pnl_readiness import (
    build_native_activity_pnl_readiness,
)
from services.wallet_jetton_contract_verification import _record_response


MULTI_ASSET_PNL_READINESS_CONTRACT_VERSION = "ton_multi_asset_pnl_readiness_v2"
JETTON_PROVIDER_ASSET_OBSERVATION_VERSION = "tonapi_jetton_snapshot_v1"
NANOTON_PER_TON = Decimal("1000000000")
MAX_SELECTED_CAPTURES = 2500
MAX_SOURCE_MESSAGES = 115200
MAX_PAYLOAD_OCCURRENCES = 10000


class WalletMultiAssetPnlReadinessConflict(ValueError):
    """Selected persisted evidence is ambiguous, corrupt, or incoherent."""


def build_multi_asset_pnl_readiness(
    target_run_id: int,
    run_ids: list[int],
    session: Session,
) -> dict[str, Any]:
    """Reconcile selected native, jetton-layout, asset, and fee evidence."""
    native = build_native_activity_pnl_readiness(target_run_id, run_ids, session)
    selected_run_ids = native["selected_run_ids"]
    network = native["network"]

    snapshots = _load_asset_snapshot_index(selected_run_ids, network, session)
    contracts = _load_verified_contract_index(
        selected_run_ids,
        network,
        native["wallet_account_canonical"],
        session,
    )
    fees = _load_transaction_fee_index(selected_run_ids, network, session)
    collected = _collect_payload_observations(selected_run_ids, session)
    evidence_rows = _deduplicate_and_bind(
        collected["occurrences"],
        snapshots["index"],
        contracts["index"],
        fees,
    )

    matched_assets = sum(
        row["asset_binding_status"] == "verified_contract_match"
        for row in evidence_rows
    )
    linked_fees = sum(
        row["transaction_fee_evidence_status"] == "exact_transaction_match"
        for row in evidence_rows
    )
    fee_transactions = {
        row["transaction_hash"]: int(row["transaction_fee_nanoton"], 10)
        for row in evidence_rows
        if row["transaction_fee_nanoton"] is not None
    }
    linked_fee_nanoton = sum(fee_transactions.values())
    operations = Counter(row["operation"] for row in evidence_rows)
    operation_counts = [
        {"operation": operation, "count": operations[operation]}
        for operation in sorted(operations)
    ]
    unique_count = len(evidence_rows)
    occurrence_count = len(collected["occurrences"])
    summary = {
        "selected_capture_count": collected["selected_capture_count"],
        "verified_capture_count": collected["verified_capture_count"],
        "source_message_count": collected["source_message_count"],
        "recognized_payload_occurrence_count": occurrence_count,
        "unrecognized_message_count": collected["unrecognized_message_count"],
        "deduplicated_payload_observation_count": unique_count,
        "suppressed_payload_occurrence_count": occurrence_count - unique_count,
        "provider_jetton_snapshot_count": snapshots["snapshot_count"],
        "valid_provider_asset_snapshot_count": snapshots["valid_count"],
        "invalid_provider_asset_snapshot_count": snapshots["invalid_count"],
        "verified_jetton_contract_count": contracts["verification_count"],
        "asset_matched_observation_count": matched_assets,
        "asset_unmatched_observation_count": unique_count - matched_assets,
        "fee_linked_observation_count": linked_fees,
        "fee_unlinked_observation_count": unique_count - linked_fees,
        "linked_fee_transaction_count": len(fee_transactions),
        "linked_fee_nanoton": str(linked_fee_nanoton),
        "linked_fee_ton": _ton(linked_fee_nanoton),
    }
    requirements = _requirements(unique_count, matched_assets, linked_fees)
    blocked_codes = [
        row["code"] for row in requirements if not row["available"]
    ]
    document = {
        "contract_version": MULTI_ASSET_PNL_READINESS_CONTRACT_VERSION,
        "target_run_id": target_run_id,
        "selected_run_ids": selected_run_ids,
        "network": network,
        "wallet_account_canonical": native["wallet_account_canonical"],
        "source_native_analysis_digest_sha256": native[
            "analysis_digest_sha256"
        ],
        "native_flow_summary": native["flow_summary"],
        "jetton_evidence_summary": summary,
        "operations": operation_counts,
        "evidence": evidence_rows,
        "requirements": requirements,
        "blocked_requirement_codes": blocked_codes,
    }
    return {
        **document,
        "analysis_digest_sha256": _digest_json(document),
        "analysis_status": "blocked_missing_evidence",
        "calculation_mode": "evidence_reconciliation_only",
        "cost_basis_method": "unavailable",
        "cost_basis_usd": None,
        "realized_pnl_usd": None,
        "unrealized_pnl_usd": None,
        "native_activity_deduplication_applied": True,
        "jetton_observation_deduplication_applied": True,
        "jetton_payload_semantics_used_by_pnl_readiness": bool(unique_count),
        "verified_contract_identity_used_by_pnl_readiness": bool(matched_assets),
        "provider_asset_metadata_used_by_pnl_readiness": any(
            row["asset_decimals"] is not None for row in evidence_rows
        ),
        "transaction_fee_evidence_used_by_pnl_readiness": bool(linked_fees),
        "provider_snapshot_asset_identity_is_authoritative": False,
        "verified_contract_asset_identity_is_authoritative": bool(matched_assets),
        "transaction_fee_allocation_applied": False,
        "provider_requests_performed": False,
        "message_bodies_returned": False,
        "used_by_pnl_calculation": False,
        "establishes_complete_wallet_history": False,
        "eligible_for_cost_basis": False,
        "is_cost_basis": False,
        "is_real_pnl": False,
        "real_pnl_locked": True,
        "message": (
            "Verified native flow, TEP-74 payload observations, provider "
            "proof-checked jetton contract identities, optional snapshot "
            "metadata, and exact transaction-fee evidence were reconciled "
            "provider-free. Fees are not allocated to lots, and PnL remains "
            "locked until every missing requirement is established."
        ),
    }


def _load_verified_contract_index(
    selected_run_ids: list[int],
    network: str,
    owner: str,
    session: Session,
) -> dict[str, Any]:
    records = list(
        session.scalars(
            select(WalletJettonContractVerification)
            .where(WalletJettonContractVerification.run_id.in_(selected_run_ids))
            .order_by(
                WalletJettonContractVerification.run_id,
                WalletJettonContractVerification.id,
            )
        )
    )
    index: dict[tuple[str, str], dict[str, Any]] = {}
    for record in records:
        verified = _record_response(record)
        if (
            verified["network"] != network
            or verified["owner_account_canonical"] != owner
        ):
            raise WalletMultiAssetPnlReadinessConflict(
                "Verified jetton contract scope conflicts with selected runs."
            )
        normalized = {
            "jetton_master_account_canonical": verified[
                "jetton_master_account_canonical"
            ],
            "wallet_contract_account_canonical": verified[
                "jetton_wallet_account_canonical"
            ],
            "asset_identity_key": verified["asset_identity_key"],
            "verification_ids": [int(verified["verification_id"], 10)],
            "verification_digests": [verified["evidence_digest_sha256"]],
            "source_run_ids": [record.run_id],
        }
        for role, account in (
            ("jetton_wallet", verified["jetton_wallet_account_canonical"]),
            ("jetton_master", verified["jetton_master_account_canonical"]),
        ):
            key = (role, account)
            existing = index.get(key)
            if existing is None:
                index[key] = normalized.copy()
                continue
            if (
                existing["asset_identity_key"]
                != normalized["asset_identity_key"]
                or existing["wallet_contract_account_canonical"]
                != normalized["wallet_contract_account_canonical"]
            ):
                raise WalletMultiAssetPnlReadinessConflict(
                    "Verified jetton contract identities conflict."
                )
            for field in (
                "verification_ids",
                "verification_digests",
                "source_run_ids",
            ):
                existing[field] = sorted(
                    set(existing[field] + normalized[field])
                )
    return {"index": index, "verification_count": len(records)}


def _collect_payload_observations(
    selected_run_ids: list[int],
    session: Session,
) -> dict[str, Any]:
    captures = list(
        session.scalars(
            select(WalletTraceEvidenceCapture)
            .where(WalletTraceEvidenceCapture.run_id.in_(selected_run_ids))
            .order_by(
                WalletTraceEvidenceCapture.run_id,
                WalletTraceEvidenceCapture.capture_slot,
                WalletTraceEvidenceCapture.id,
            )
        )
    )
    if len(captures) > MAX_SELECTED_CAPTURES:
        raise WalletMultiAssetPnlReadinessConflict(
            "Selected runs exceed the multi-asset capture bound."
        )
    occurrences: list[dict[str, Any]] = []
    verified_capture_count = 0
    source_message_count = 0
    unrecognized_message_count = 0
    for capture in captures:
        payloads = get_wallet_transaction_jetton_payload_observations(
            capture.run_id,
            capture.root_transaction_hash,
            session,
        )
        if payloads is None:
            continue
        verified_capture_count += 1
        source_message_count += payloads["source_message_count"]
        unrecognized_message_count += payloads["unrecognized_message_count"]
        if source_message_count > MAX_SOURCE_MESSAGES:
            raise WalletMultiAssetPnlReadinessConflict(
                "Selected captures exceed the multi-asset message bound."
            )
        for observation in payloads["observations"]:
            occurrences.append(
                {
                    "run_id": capture.run_id,
                    "capture_id": int(payloads["capture_id"], 10),
                    "verification_id": int(payloads["verification_id"], 10),
                    "observation": observation,
                }
            )
            if len(occurrences) > MAX_PAYLOAD_OCCURRENCES:
                raise WalletMultiAssetPnlReadinessConflict(
                    "Selected captures exceed the jetton payload occurrence bound."
                )
    return {
        "selected_capture_count": len(captures),
        "verified_capture_count": verified_capture_count,
        "source_message_count": source_message_count,
        "unrecognized_message_count": unrecognized_message_count,
        "occurrences": occurrences,
    }


def _load_asset_snapshot_index(
    selected_run_ids: list[int],
    network: str,
    session: Session,
) -> dict[str, Any]:
    snapshots = list(
        session.scalars(
            select(WalletBalanceSnapshot)
            .where(WalletBalanceSnapshot.run_id.in_(selected_run_ids))
            .order_by(WalletBalanceSnapshot.run_id, WalletBalanceSnapshot.id)
        )
    )
    index: dict[tuple[str, str], dict[str, Any]] = {}
    snapshot_count = valid_count = invalid_count = 0
    for snapshot in snapshots:
        if snapshot.asset == "TON":
            continue
        snapshot_count += 1
        normalized = _validated_snapshot(snapshot, network)
        if normalized is None:
            invalid_count += 1
            continue
        valid_count += 1
        for role, account in (
            ("jetton_wallet", normalized["wallet_contract_account_canonical"]),
            ("jetton_master", normalized["jetton_master_account_canonical"]),
        ):
            key = (role, account)
            existing = index.get(key)
            if existing is None:
                index[key] = normalized
                continue
            if (
                existing["jetton_master_account_canonical"]
                != normalized["jetton_master_account_canonical"]
                or existing["decimals"] != normalized["decimals"]
            ):
                raise WalletMultiAssetPnlReadinessConflict(
                    "Provider jetton snapshots conflict for one contract account."
                )
            existing["source_run_ids"] = sorted(
                set(existing["source_run_ids"] + normalized["source_run_ids"])
            )
            if existing["symbol"] != normalized["symbol"]:
                existing["symbol"] = None
    return {
        "index": index,
        "snapshot_count": snapshot_count,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
    }


def _validated_snapshot(
    snapshot: WalletBalanceSnapshot,
    network: str,
) -> dict[str, Any] | None:
    if snapshot.provider != "tonapi" or snapshot.source_status != "live":
        return None
    try:
        raw = json.loads(snapshot.raw_json or "")
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(raw, dict) or raw.get("surface") != "jettons":
        return None
    master = _canonical_account(raw.get("jetton_address"), network)
    wallet = _canonical_account(raw.get("wallet_contract_address"), network)
    decimals = raw.get("decimals")
    if (
        master is None
        or wallet is None
        or isinstance(decimals, bool)
        or not isinstance(decimals, int)
        or not 0 <= decimals <= 255
    ):
        return None
    symbol = raw.get("jetton_symbol")
    if not isinstance(symbol, str) or not symbol or len(symbol) > 64:
        symbol = None
    return {
        "jetton_master_account_canonical": master,
        "wallet_contract_account_canonical": wallet,
        "provider_asset_observation_key": (
            f"{JETTON_PROVIDER_ASSET_OBSERVATION_VERSION}|{network}|{master}"
        ),
        "decimals": decimals,
        "symbol": symbol,
        "source_run_ids": [snapshot.run_id],
    }


def _load_transaction_fee_index(
    selected_run_ids: list[int],
    network: str,
    session: Session,
) -> dict[str, dict[str, Any]]:
    transactions = list(
        session.scalars(
            select(WalletTransaction)
            .where(WalletTransaction.run_id.in_(selected_run_ids))
            .order_by(WalletTransaction.run_id, WalletTransaction.id)
        )
    )
    index: dict[str, dict[str, Any]] = {}
    for transaction in transactions:
        if (
            transaction.provider != "tonapi"
            or transaction.source_status != "live"
            or transaction.transaction_network != network
            or transaction.transaction_hash_canonical is None
            or transaction.fee_ton is None
        ):
            continue
        fee_nanoton = _fee_nanoton(transaction.fee_ton)
        existing = index.get(transaction.transaction_hash_canonical)
        if existing is None:
            index[transaction.transaction_hash_canonical] = {
                "fee_nanoton": fee_nanoton,
                "source_run_ids": [transaction.run_id],
            }
            continue
        if existing["fee_nanoton"] != fee_nanoton:
            raise WalletMultiAssetPnlReadinessConflict(
                "Persisted transaction fees conflict for one transaction hash."
            )
        existing["source_run_ids"] = sorted(
            set(existing["source_run_ids"] + [transaction.run_id])
        )
    return index


def _deduplicate_and_bind(
    occurrences: list[dict[str, Any]],
    snapshot_index: dict[tuple[str, str], dict[str, Any]],
    contract_index: dict[tuple[str, str], dict[str, Any]],
    fee_index: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for occurrence in occurrences:
        observation = occurrence["observation"]
        identity = observation["payload_observation_identity"]
        signature = _observation_signature(observation)
        existing = grouped.get(identity)
        if existing is None:
            grouped[identity] = {
                "observation": observation,
                "signature": signature,
                "occurrences": [occurrence],
            }
        elif existing["signature"] != signature:
            raise WalletMultiAssetPnlReadinessConflict(
                "One jetton payload identity has conflicting semantics."
            )
        else:
            existing["occurrences"].append(occurrence)

    rows = []
    for identity in sorted(grouped):
        grouped_row = grouped[identity]
        observation = grouped_row["observation"]
        occurrence_records = sorted(
            (
                {
                    "run_id": row["run_id"],
                    "capture_id": row["capture_id"],
                    "verification_id": row["verification_id"],
                }
                for row in grouped_row["occurrences"]
            ),
            key=lambda row: (
                row["run_id"],
                row["capture_id"],
                row["verification_id"],
            ),
        )
        source_run_ids = sorted({row["run_id"] for row in occurrence_records})
        role, account = _observed_contract(observation)
        snapshot = None if role is None or account is None else snapshot_index.get(
            (role, account)
        )
        contract = None if role is None or account is None else contract_index.get(
            (role, account)
        )
        if snapshot and contract and (
            snapshot["jetton_master_account_canonical"]
            != contract["jetton_master_account_canonical"]
        ):
            raise WalletMultiAssetPnlReadinessConflict(
                "Provider metadata conflicts with verified jetton identity."
            )
        metadata = snapshot if contract else None
        fee = fee_index.get(observation["transaction_hash"])
        rows.append(
            {
                "ordinal": len(rows),
                "payload_observation_identity": identity,
                "occurrence_count": len(grouped_row["occurrences"]),
                "source_run_ids": source_run_ids,
                "occurrences": occurrence_records,
                "operation": observation["operation"],
                "standard_status": observation["standard_status"],
                "transaction_hash": observation["transaction_hash"],
                "message_hash": observation["message_hash"],
                "query_id": observation["query_id"],
                "amount_base_units": observation["amount_base_units"],
                "contract_account_role": observation["contract_account_role"],
                "observed_contract_account_canonical": account,
                "asset_binding_status": (
                    "verified_contract_match" if contract else "unavailable"
                ),
                "jetton_master_account_canonical": (
                    contract["jetton_master_account_canonical"]
                    if contract
                    else None
                ),
                "asset_identity_key": (
                    contract["asset_identity_key"] if contract else None
                ),
                "contract_verification_ids": (
                    contract["verification_ids"] if contract else []
                ),
                "contract_verification_digests": (
                    contract["verification_digests"] if contract else []
                ),
                "contract_verification_run_ids": (
                    contract["source_run_ids"] if contract else []
                ),
                "provider_asset_observation_key": (
                    metadata["provider_asset_observation_key"]
                    if metadata
                    else None
                ),
                "asset_decimals": metadata["decimals"] if metadata else None,
                "asset_symbol": metadata["symbol"] if metadata else None,
                "asset_snapshot_run_ids": (
                    metadata["source_run_ids"] if metadata else []
                ),
                "transaction_fee_evidence_status": (
                    "exact_transaction_match" if fee else "unavailable"
                ),
                "transaction_fee_nanoton": (
                    str(fee["fee_nanoton"]) if fee else None
                ),
                "transaction_fee_ton": (
                    _ton(fee["fee_nanoton"]) if fee else None
                ),
                "fee_source_run_ids": fee["source_run_ids"] if fee else [],
                "provider_snapshot_is_local_master_proof": False,
                "fee_allocation_applied": False,
                "eligible_for_cost_basis": False,
                "used_by_pnl_calculation": False,
            }
        )
    return rows


def _observed_contract(observation: dict[str, Any]) -> tuple[str | None, str | None]:
    role = observation["contract_account_role"]
    if role == "source_jetton_wallet_observed":
        return "jetton_wallet", observation["message_source_account_canonical"]
    if role == "destination_jetton_wallet_observed":
        return "jetton_wallet", observation[
            "message_destination_account_canonical"
        ]
    if role == "destination_jetton_master_observed":
        return "jetton_master", observation[
            "message_destination_account_canonical"
        ]
    return None, None


def _observation_signature(observation: dict[str, Any]) -> str:
    return _digest_json({key: value for key, value in observation.items() if key != "ordinal"})


def _canonical_account(value: Any, network: str) -> str | None:
    identity = derive_ton_wallet_identity(value, network_context=network)
    if identity.status != "network_scoped" or identity.network != network:
        return None
    return identity.canonical_address


def _fee_nanoton(value: Any) -> int:
    try:
        decimal_value = Decimal(str(value))
        scaled = decimal_value * NANOTON_PER_TON
    except (InvalidOperation, ValueError) as exc:
        raise WalletMultiAssetPnlReadinessConflict(
            "Persisted transaction fee is not a decimal TON amount."
        ) from exc
    if decimal_value < 0 or scaled != scaled.to_integral_value():
        raise WalletMultiAssetPnlReadinessConflict(
            "Persisted transaction fee is not an exact non-negative nanoton amount."
        )
    return int(scaled)


def _requirements(
    unique_count: int,
    matched_assets: int,
    linked_fees: int,
) -> list[dict[str, Any]]:
    has_payloads = unique_count > 0
    all_assets = has_payloads and matched_assets == unique_count
    all_fees = has_payloads and linked_fees == unique_count
    return [
        {"code": "deduplicated_native_activity", "available": True, "reason": None},
        {
            "code": "verified_jetton_payload_semantics",
            "available": has_payloads,
            "reason": (
                None
                if has_payloads
                else "No recognized TEP-74 payload observation exists in the "
                "selected verified captures."
            ),
        },
        {
            "code": "proof_checked_jetton_asset_identity",
            "available": all_assets,
            "reason": (
                None
                if all_assets
                else "Every recognized payload requires one unambiguous match "
                "to a proof-checked selected-run jetton contract identity."
            ),
        },
        {
            "code": "exact_transaction_fee_evidence",
            "available": all_fees,
            "reason": (
                None
                if all_fees
                else "Every recognized payload transaction requires one exact "
                "persisted transaction-fee match."
            ),
        },
        {
            "code": "complete_wallet_history",
            "available": False,
            "reason": (
                "Selected runs and captures do not establish wallet history "
                "outside their bounded intervals."
            ),
        },
        {
            "code": "authoritative_trade_semantics",
            "available": False,
            "reason": (
                "TEP-74 transfer and burn layouts do not by themselves prove "
                "a DEX trade, economic intent, or successful beneficial "
                "execution."
            ),
        },
        {
            "code": "historical_trade_prices",
            "available": False,
            "reason": (
                "No historical price is applied without authoritative trade "
                "legs and timestamps."
            ),
        },
        {
            "code": "transaction_fee_allocation",
            "available": False,
            "reason": (
                "Exact transaction fees are evidence only and are not allocated "
                "to acquisition or disposal lots."
            ),
        },
        {
            "code": "acquisition_lots_and_cost_basis",
            "available": False,
            "reason": (
                "Complete ordered acquisition lots, valuations, and allocated "
                "fees are not established."
            ),
        },
    ]


def _ton(value: int) -> str:
    return format(Decimal(value) / NANOTON_PER_TON, "f")


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
    "MULTI_ASSET_PNL_READINESS_CONTRACT_VERSION",
    "WalletMultiAssetPnlReadinessConflict",
    "build_multi_asset_pnl_readiness",
]
