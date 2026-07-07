"""USD valuation of run swap flows via historical price points.

Second stage of the historical-prices track: TON-side swap legs are valued in
USD at the nearest historical TON/USD point. The ``historical_prices``
Real-PnL requirement becomes available only when every TON-side swap leg has
a nearby point; ``cost_basis`` and ``fee_handling`` stay missing, so Real PnL
remains locked. No hidden fallback: unmatched swaps and provider failures
stay visible in the evidence block and warnings.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from config import get_settings
from services.historical_pricing import build_historical_prices_preview
from services.pnl_preview import derive_run_pnl_preview

MATCH_TOLERANCE_SECONDS = 21600  # 6 hours

HISTORICAL_VALUATION_NOTE = (
    "USD figures value only the TON leg of matched swaps at the nearest "
    "historical TON/USD point (6h tolerance). Whether they amount to Real "
    "PnL is decided solely by the evidence requirement checklist."
)

REAL_PNL_NOTE = (
    "Real PnL (in-window realized): every evidence requirement is met for "
    "this run's window. Figures cover realized swap PnL in USD, with "
    "recorded fees valued at the matched historical points. Unrealized "
    "holdings and any activity outside the ingested window are not included."
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


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _nearest_price(
    points: list[tuple[datetime, Decimal]],
    timestamp: datetime,
) -> Decimal | None:
    best: Decimal | None = None
    best_diff: float | None = None
    for point_ts, price in points:
        diff = abs((point_ts - timestamp).total_seconds())
        if best_diff is None or diff < best_diff:
            best_diff = diff
            best = price
    if best is None or best_diff is None or best_diff > MATCH_TOLERANCE_SECONDS:
        return None
    return best


def _set_requirement(
    preview: dict[str, Any],
    code: str,
    available: bool,
    reason: str | None,
) -> None:
    for requirement in preview["requirements"]:
        if requirement["code"] == code:
            requirement["available"] = available
            requirement["reason"] = reason
    preview["missing_evidence"] = [
        f"{req['code']}: {req['reason']}"
        for req in preview["requirements"]
        if not req["available"]
    ]
    preview["real_pnl_locked"] = any(
        not req["available"] for req in preview["requirements"]
    )


def _evidence(
    source_status: str,
    points_fetched: int,
    swaps_matched: int,
    swaps_unmatched: int,
    note: str,
) -> dict[str, Any]:
    return {
        "source_status": source_status,
        "points_fetched": points_fetched,
        "swaps_matched": swaps_matched,
        "swaps_unmatched": swaps_unmatched,
        "tolerance_seconds": MATCH_TOLERANCE_SECONDS,
        "note": note,
    }


def _compute_in_window_cost_basis(
    legs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool, str | None, Decimal | None]:
    """Average-cost realized PnL per token, strictly within the run window.

    A token is computable only when every leg carries a positive token
    quantity and every sell is fully covered by earlier in-window buys;
    anything else is reported as unavailable with the exact reason.
    """
    by_token: dict[str, list[dict[str, Any]]] = {}
    for leg in legs:
        by_token.setdefault(leg["token"], []).append(leg)

    records: list[dict[str, Any]] = []
    total_realized = ZERO
    computed_count = 0
    for token in sorted(by_token):
        token_legs = sorted(by_token[token], key=lambda leg: leg["timestamp"])
        qty_held = ZERO
        cost_total = ZERO
        proceeds_total = ZERO
        basis_total = ZERO
        realized = ZERO
        sell_count = 0
        failure: str | None = None
        for leg in token_legs:
            token_qty = leg["token_qty"]
            if token_qty is None or token_qty <= ZERO:
                failure = (
                    f"A {leg['side']} leg lacks a positive token quantity; "
                    "in-window cost basis cannot be computed."
                )
                break
            fee_usd = (leg["fee_ton"] or ZERO) * leg["price_usd"]
            usd_value = leg["ton_amount"] * leg["price_usd"]
            if leg["side"] == "buy":
                qty_held += token_qty
                cost_total += usd_value + fee_usd
            else:
                sell_count += 1
                if token_qty > qty_held:
                    failure = (
                        "Sold quantity exceeds in-window acquisitions; the "
                        "cost basis of the sold tokens lies outside this "
                        "run's window."
                    )
                    break
                average_cost = cost_total / qty_held
                basis = average_cost * token_qty
                proceeds = usd_value - fee_usd
                realized += proceeds - basis
                proceeds_total += proceeds
                basis_total += basis
                qty_held -= token_qty
                cost_total -= basis

        if failure:
            records.append(
                {
                    "token": token,
                    "status": "unavailable",
                    "reason": failure,
                    "sell_leg_count": sell_count,
                }
            )
        else:
            computed_count += 1
            total_realized += realized
            records.append(
                {
                    "token": token,
                    "status": "computed",
                    "reason": None,
                    "sell_leg_count": sell_count,
                    "proceeds_usd": _money(proceeds_total),
                    "cost_basis_usd": _money(basis_total),
                    "realized_pnl_usd": _money(realized),
                    "remaining_qty": _money(qty_held),
                    "remaining_cost_usd": _money(cost_total),
                }
            )

    unavailable_count = len(records) - computed_count
    available = computed_count > 0 and unavailable_count == 0
    reason = (
        None
        if available
        else (
            f"In-window cost basis is unavailable for {unavailable_count} of "
            f"{len(records)} token(s); per-token reasons are listed in "
            "realized_pnl."
        )
    )
    total = _money(total_realized) if computed_count > 0 else None
    return records, available, reason, total


def derive_run_pnl_preview_with_historical(
    run: dict,
    settings=None,
) -> dict[str, Any]:
    """Return the estimated PnL preview enriched with USD-valued swap legs."""
    settings = settings or get_settings()
    preview = derive_run_pnl_preview(run)

    # Recorded fees, keyed by transaction hash (mirrors the base preview).
    fee_by_tx_hash: dict[str, Decimal] = {}
    for transaction in run.get("transactions") or []:
        tx_hash = transaction.get("tx_hash")
        fee = _decimal(transaction.get("fee_ton"))
        if tx_hash and fee is not None:
            fee_by_tx_hash[tx_hash] = fee

    # The same TON-side legs the TON-denominated estimate uses.
    legs: list[dict[str, Any]] = []
    for swap in run.get("swaps") or []:
        token_in = (swap.get("token_in") or "").upper()
        token_out = (swap.get("token_out") or "").upper()
        amount_in = _decimal(swap.get("amount_in"))
        amount_out = _decimal(swap.get("amount_out"))
        timestamp = _parse_ts(swap.get("timestamp"))
        fee_ton = fee_by_tx_hash.get(swap.get("tx_hash") or "")
        if token_in == "TON" and token_out and token_out != "TON" and amount_in:
            legs.append(
                {
                    "token": swap["token_out"],
                    "side": "buy",
                    "ton_amount": amount_in,
                    "token_qty": amount_out,
                    "timestamp": timestamp,
                    "fee_ton": fee_ton,
                }
            )
        elif token_out == "TON" and token_in and token_in != "TON" and amount_out:
            legs.append(
                {
                    "token": swap["token_in"],
                    "side": "sell",
                    "ton_amount": amount_out,
                    "token_qty": amount_in,
                    "timestamp": timestamp,
                    "fee_ton": fee_ton,
                }
            )

    if not legs:
        preview["historical_pricing"] = _evidence(
            "unavailable", 0, 0, 0,
            "No TON-side swap legs exist to value in USD.",
        )
        return preview

    timestamps = [leg["timestamp"] for leg in legs if leg["timestamp"] is not None]
    if not timestamps:
        preview["historical_pricing"] = _evidence(
            "unavailable", 0, 0, len(legs),
            "No swap has a parseable timestamp to match against historical "
            "prices.",
        )
        _set_requirement(
            preview,
            "historical_prices",
            False,
            "No swap has a parseable timestamp to match against historical "
            "prices.",
        )
        return preview

    window_start = min(timestamps) - timedelta(days=1)
    window_end = max(timestamps) + timedelta(days=1)
    try:
        prices = build_historical_prices_preview(
            "ton", _iso(window_start), _iso(window_end), settings=settings
        )
    except ValueError as exc:
        preview["historical_pricing"] = _evidence(
            "unavailable", 0, 0, len(legs), str(exc)
        )
        _set_requirement(preview, "historical_prices", False, str(exc))
        preview["warnings"].append(
            f"Historical price lookup failed: {exc} No fallback data is "
            "substituted."
        )
        return preview

    points: list[tuple[datetime, Decimal]] = []
    for point in prices["points"]:
        point_ts = _parse_ts(point.get("timestamp"))
        price = _decimal(point.get("price_usd"))
        if point_ts is not None and price is not None:
            points.append((point_ts, price))

    flows: dict[str, dict[str, Any]] = {}
    matched = 0
    unmatched = 0
    for leg in legs:
        timestamp = leg["timestamp"]
        price = _nearest_price(points, timestamp) if timestamp else None
        leg["price_usd"] = price
        if price is None:
            unmatched += 1
            continue
        matched += 1
        token = leg["token"]
        flow = flows.setdefault(
            token,
            {
                "token": token,
                "usd_spent": ZERO,
                "usd_received": ZERO,
                "matched_swap_count": 0,
            },
        )
        flow["matched_swap_count"] += 1
        usd_value = leg["ton_amount"] * price
        if leg["side"] == "buy":
            flow["usd_spent"] += usd_value
        else:
            flow["usd_received"] += usd_value

    usd_flows = []
    total_usd_spent = ZERO
    total_usd_received = ZERO
    for token in sorted(flows):
        flow = flows[token]
        total_usd_spent += flow["usd_spent"]
        total_usd_received += flow["usd_received"]
        usd_flows.append(
            {
                "token": flow["token"],
                "usd_spent": _money(flow["usd_spent"]),
                "usd_received": _money(flow["usd_received"]),
                "net_usd_flow": _money(
                    flow["usd_received"] - flow["usd_spent"]
                ),
                "matched_swap_count": flow["matched_swap_count"],
            }
        )

    source_status = prices["source_status"]
    available = matched == len(legs) and matched > 0 and source_status in (
        "mock",
        "real",
    )
    reason = (
        None
        if available
        else (
            f"Only {matched} of {len(legs)} TON-side swap legs have a "
            f"historical price point within "
            f"{MATCH_TOLERANCE_SECONDS // 3600}h."
        )
    )
    _set_requirement(preview, "historical_prices", available, reason)
    if available:
        records, cost_basis_available, cost_basis_reason, total_realized = (
            _compute_in_window_cost_basis(legs)
        )
        _set_requirement(
            preview, "cost_basis", cost_basis_available, cost_basis_reason
        )
        preview["realized_pnl"] = records
        preview["total_realized_pnl_usd"] = total_realized
    else:
        _set_requirement(
            preview,
            "cost_basis",
            False,
            "Cost basis needs a matched historical price for every swap leg.",
        )

    if not preview["real_pnl_locked"]:
        preview["pnl_mode"] = "real_pnl"
        preview["is_real_pnl"] = True
        preview["confidence"] = "high"
        preview["note"] = REAL_PNL_NOTE

    preview["usd_flows"] = usd_flows
    preview["total_usd_spent"] = _money(total_usd_spent)
    preview["total_usd_received"] = _money(total_usd_received)
    preview["net_usd_flow"] = _money(total_usd_received - total_usd_spent)
    preview["historical_pricing"] = _evidence(
        source_status,
        len(points),
        matched,
        unmatched,
        HISTORICAL_VALUATION_NOTE,
    )
    if unmatched:
        preview["warnings"].append(
            f"{unmatched} TON-side swap leg(s) have no historical price "
            "point within the matching tolerance; their USD value is not "
            "estimated."
        )
    preview["warnings"].extend(prices["warnings"])
    return preview
