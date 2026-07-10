"""Estimated PnL preview derived from one wallet ingestion run.

This is an *estimate layer*, never Real PnL. It computes TON-denominated
realized swap flows per token from the run's already-ingested swap rows and
reports exactly which Real-PnL evidence requirements are still missing. Real
PnL stays locked until transaction history, swap evidence, historical prices,
cost basis, and fee handling are all available; a partial calculation is never
labeled as Real PnL.

Confidence reflects evidence volume and is capped at "medium" for the base
on-chain estimate: non-TON swap legs and transfers are excluded, while
historical cost basis and spot valuation require explicit enrichment. Every
base rule is a pure function of the public run-response dict.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

PNL_PREVIEW_NOTE = (
    "Estimated PnL preview only -- not Real PnL. Figures are TON-denominated "
    "realized swap flows computed from this run's ingested swap rows. They "
    "exclude non-TON swap legs, transfers, historical prices, and unrealized "
    "valuation; recorded transaction fees are netted separately in the "
    "after-fee figures. Real PnL stays locked until every evidence "
    "requirement is available."
)

ZERO = Decimal("0")


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money(value: Decimal) -> str:
    return f"{value:f}"


def build_real_pnl_requirements(run: dict) -> list[dict[str, Any]]:
    """Return the Real-PnL evidence checklist for one run.

    Real PnL unlocks only when every requirement is available. This base
    checklist starts without historical enrichment or cost basis; downstream
    enrichment updates those entries when explicitly requested and complete.
    """
    has_transactions = bool(run.get("transactions"))
    has_swaps = bool(run.get("swaps"))
    return [
        {
            "code": "transaction_history",
            "available": has_transactions,
            "reason": None
            if has_transactions
            else "No transaction rows were ingested for this run.",
        },
        {
            "code": "swap_evidence",
            "available": has_swaps,
            "reason": None
            if has_swaps
            else "No DEX swap rows were ingested for this run.",
        },
        {
            "code": "historical_prices",
            "available": False,
            "reason": "Historical enrichment was not requested for this preview.",
        },
        {
            "code": "cost_basis",
            "available": False,
            "reason": (
                "Cost basis requires historical enrichment and sufficient "
                "in-window acquisition evidence."
            ),
        },
        {
            "code": "fee_handling",
            "available": False,
            "reason": (
                "Transaction fees are recorded but not yet incorporated into "
                "PnL math."
            ),
        },
    ]


def _set_requirement_entry(
    requirements: list[dict[str, Any]],
    code: str,
    available: bool,
    reason: str | None,
) -> None:
    for requirement in requirements:
        if requirement["code"] == code:
            requirement["available"] = available
            requirement["reason"] = reason


def _empty_flow(token: str) -> dict[str, Any]:
    return {
        "token": token,
        "buy_swap_count": 0,
        "sell_swap_count": 0,
        "token_bought_qty": ZERO,
        "token_sold_qty": ZERO,
        "ton_spent": ZERO,
        "ton_received": ZERO,
        "fee_ton": ZERO,
    }


def derive_run_pnl_preview(run: dict) -> dict[str, Any]:
    """Return an estimated PnL preview derived from one run response."""
    swaps = run.get("swaps") or []
    requirements = build_real_pnl_requirements(run)
    warnings: list[str] = []

    # Recorded fees, keyed by transaction hash, for fee handling.
    fee_by_tx_hash: dict[str, Decimal] = {}
    for transaction in run.get("transactions") or []:
        tx_hash = transaction.get("tx_hash")
        fee = _decimal(transaction.get("fee_ton"))
        if tx_hash and fee is not None:
            fee_by_tx_hash[tx_hash] = fee

    flows: dict[str, dict[str, Any]] = {}
    swaps_used = 0
    swaps_excluded = 0
    partial_quantity_rows = 0
    fees_matched = 0
    for swap in swaps:
        token_in = (swap.get("token_in") or "").upper()
        token_out = (swap.get("token_out") or "").upper()
        amount_in = _decimal(swap.get("amount_in"))
        amount_out = _decimal(swap.get("amount_out"))

        if token_in == "TON" and token_out and token_out != "TON" and amount_in:
            flow = flows.setdefault(swap["token_out"], _empty_flow(swap["token_out"]))
            flow["buy_swap_count"] += 1
            flow["ton_spent"] += amount_in
            if amount_out is None:
                partial_quantity_rows += 1
            else:
                flow["token_bought_qty"] += amount_out
            swaps_used += 1
        elif token_out == "TON" and token_in and token_in != "TON" and amount_out:
            flow = flows.setdefault(swap["token_in"], _empty_flow(swap["token_in"]))
            flow["sell_swap_count"] += 1
            flow["ton_received"] += amount_out
            if amount_in is None:
                partial_quantity_rows += 1
            else:
                flow["token_sold_qty"] += amount_in
            swaps_used += 1
        else:
            swaps_excluded += 1
            continue

        fee = fee_by_tx_hash.get(swap.get("tx_hash") or "")
        if fee is not None:
            flow["fee_ton"] += fee
            fees_matched += 1

    if swaps_used == 0:
        _set_requirement_entry(
            requirements,
            "fee_handling",
            False,
            "No usable swap rows exist to attach recorded fees to.",
        )
    elif fees_matched == swaps_used:
        _set_requirement_entry(requirements, "fee_handling", True, None)
    else:
        _set_requirement_entry(
            requirements,
            "fee_handling",
            False,
            f"Only {fees_matched} of {swaps_used} used swap rows have a "
            "recorded transaction fee.",
        )
        warnings.append(
            f"{swaps_used - fees_matched} used swap row(s) have no recorded "
            "transaction fee; after-fee figures are partial."
        )

    missing_evidence = [
        f"{req['code']}: {req['reason']}"
        for req in requirements
        if not req["available"]
    ]
    real_pnl_locked = any(not req["available"] for req in requirements)

    if swaps_excluded:
        warnings.append(
            f"{swaps_excluded} swap row(s) were excluded from the estimate "
            "(non-TON pair or missing amounts)."
        )
    if partial_quantity_rows:
        warnings.append(
            f"{partial_quantity_rows} swap row(s) lacked a token-side amount; "
            "token quantities are partial."
        )

    if swaps_used > 0:
        pnl_mode = "estimated_onchain_pnl"
        # Capped at medium: the base estimate excludes non-TON legs and has no
        # historical cost basis or spot valuation.
        confidence = "low" if swaps_used < 5 else "medium"
    elif swaps:
        pnl_mode = "real_pnl_locked"
        confidence = "unavailable"
        warnings.append(
            "Swap rows exist but none has a TON-denominated side with "
            "amounts; no honest estimate is possible without historical "
            "prices."
        )
    else:
        pnl_mode = "insufficient_data"
        confidence = "unavailable"
        warnings.append(
            "No DEX swap rows were ingested for this run; nothing can be "
            "estimated."
        )

    token_flows = []
    total_ton_spent = ZERO
    total_ton_received = ZERO
    total_fees_ton = ZERO
    for token in sorted(flows):
        flow = flows[token]
        total_ton_spent += flow["ton_spent"]
        total_ton_received += flow["ton_received"]
        total_fees_ton += flow["fee_ton"]
        net_flow = flow["ton_received"] - flow["ton_spent"]
        token_flows.append(
            {
                "token": flow["token"],
                "buy_swap_count": flow["buy_swap_count"],
                "sell_swap_count": flow["sell_swap_count"],
                "token_bought_qty": _money(flow["token_bought_qty"]),
                "token_sold_qty": _money(flow["token_sold_qty"]),
                "ton_spent": _money(flow["ton_spent"]),
                "ton_received": _money(flow["ton_received"]),
                "net_ton_flow": _money(net_flow),
                "fee_ton": _money(flow["fee_ton"]),
                "net_ton_flow_after_fees": _money(net_flow - flow["fee_ton"]),
            }
        )

    net_total = total_ton_received - total_ton_spent
    return {
        "run_id": run.get("run_id"),
        "wallet_address": run.get("wallet_address"),
        "pnl_mode": pnl_mode,
        "confidence": confidence,
        "is_real_pnl": False,
        "real_pnl_locked": real_pnl_locked,
        "token_flows": token_flows,
        "total_ton_spent": _money(total_ton_spent),
        "total_ton_received": _money(total_ton_received),
        "net_ton_flow": _money(net_total),
        "total_fees_ton": _money(total_fees_ton),
        "net_ton_flow_after_fees": _money(net_total - total_fees_ton),
        "swaps_used": swaps_used,
        "swaps_excluded": swaps_excluded,
        "requirements": requirements,
        "missing_evidence": missing_evidence,
        "warnings": warnings,
        "note": PNL_PREVIEW_NOTE,
    }
