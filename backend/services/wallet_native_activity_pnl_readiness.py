"""Fail-closed PnL readiness over deduplicated native TON activities."""

from __future__ import annotations

from decimal import Decimal
import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from services.wallet_native_activity_dedup import (
    deduplicate_wallet_native_activity,
)


NATIVE_ACTIVITY_PNL_READINESS_CONTRACT_VERSION = (
    "ton_native_activity_pnl_readiness_v1"
)
NANOTON_PER_TON = Decimal("1000000000")


def build_native_activity_pnl_readiness(
    target_run_id: int,
    run_ids: list[int],
    session: Session,
) -> dict[str, Any]:
    """Reconcile native flows and expose every missing PnL prerequisite.

    A native message value is not a trade leg. This contract deliberately
    consumes the canonical dedup result without turning transfers into swaps,
    prices, fees, acquisition lots, or profit.
    """
    dedup = deduplicate_wallet_native_activity(target_run_id, run_ids, session)
    counts = {"incoming": 0, "outgoing": 0, "self": 0}
    totals = {"incoming": 0, "outgoing": 0, "self": 0}
    for activity in dedup["activities"]:
        direction = activity["direction"]
        counts[direction] += 1
        totals[direction] += int(activity["amount_base_units"], 10)

    net_nanoton = totals["incoming"] - totals["outgoing"]
    flow_summary = {
        "asset_identity_key": f"ton_native_asset_v1|{dedup['network']}",
        "activity_count": len(dedup["activities"]),
        "incoming_activity_count": counts["incoming"],
        "outgoing_activity_count": counts["outgoing"],
        "self_activity_count": counts["self"],
        "incoming_nanoton": str(totals["incoming"]),
        "outgoing_nanoton": str(totals["outgoing"]),
        "self_nanoton": str(totals["self"]),
        "net_nanoton": str(net_nanoton),
        "incoming_ton": _ton(totals["incoming"]),
        "outgoing_ton": _ton(totals["outgoing"]),
        "self_ton": _ton(totals["self"]),
        "net_ton": _ton(net_nanoton),
    }
    requirements = [
        {
            "code": "deduplicated_native_activity",
            "available": True,
            "reason": None,
        },
        {
            "code": "complete_wallet_history",
            "available": False,
            "reason": (
                "Selected immutable ledgers cover explicit captures only; "
                "time outside those captures remains unknown."
            ),
        },
        {
            "code": "authoritative_trade_semantics",
            "available": False,
            "reason": (
                "Native message values do not prove a swap, purchase, sale, "
                "deposit, withdrawal, or beneficial owner."
            ),
        },
        {
            "code": "jetton_asset_identity",
            "available": False,
            "reason": (
                "The verified activity ledger contains native Toncoin only "
                "and no canonical jetton trade legs."
            ),
        },
        {
            "code": "historical_trade_prices",
            "available": False,
            "reason": (
                "No historical price lookup is attempted without verified "
                "trade legs to value."
            ),
        },
        {
            "code": "transaction_fee_linkage",
            "available": False,
            "reason": (
                "Native activity rows do not establish transaction-fee "
                "allocation to acquisition or disposal lots."
            ),
        },
        {
            "code": "acquisition_cost_basis",
            "available": False,
            "reason": (
                "Cost basis requires complete ordered acquisition lots with "
                "asset quantities, historical valuation, and fee allocation."
            ),
        },
    ]
    blocked_codes = [
        requirement["code"]
        for requirement in requirements
        if not requirement["available"]
    ]
    document = {
        "contract_version": NATIVE_ACTIVITY_PNL_READINESS_CONTRACT_VERSION,
        "target_run_id": target_run_id,
        "selected_run_ids": dedup["selected_run_ids"],
        "network": dedup["network"],
        "wallet_account_canonical": dedup["wallet_account_canonical"],
        "source_dedup_digest_sha256": dedup["dedup_digest_sha256"],
        "source_ledger_count": dedup["source_ledger_count"],
        "merged_activity_count": dedup["merged_activity_count"],
        "deduplicated_activity_count": dedup["deduplicated_activity_count"],
        "suppressed_occurrence_count": dedup["suppressed_occurrence_count"],
        "flow_summary": flow_summary,
        "requirements": requirements,
        "blocked_requirement_codes": blocked_codes,
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
        **document,
        "analysis_digest_sha256": digest,
        "analysis_status": "blocked_missing_evidence",
        "calculation_mode": "native_flow_reconciliation_only",
        "cost_basis_method": "unavailable",
        "cost_basis_usd": None,
        "realized_pnl_usd": None,
        "unrealized_pnl_usd": None,
        "activity_merge_applied": True,
        "cross_run_deduplication_applied": True,
        "native_activity_used_by_pnl_readiness": True,
        "native_activity_used_by_pnl_calculation": False,
        "establishes_complete_wallet_history": False,
        "eligible_for_cost_basis": False,
        "is_cost_basis": False,
        "is_real_pnl": False,
        "real_pnl_locked": True,
        "message": (
            "Deduplicated native TON flows were reconciled and evaluated as "
            "PnL evidence. Cost basis and PnL remain unavailable because the "
            "listed prerequisites are not established."
        ),
    }


def _ton(value: int) -> str:
    return format(Decimal(value) / NANOTON_PER_TON, "f")


__all__ = [
    "NATIVE_ACTIVITY_PNL_READINESS_CONTRACT_VERSION",
    "build_native_activity_pnl_readiness",
]
