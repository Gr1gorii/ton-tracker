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
    "historical TON/USD point (6h tolerance). They are in-window realized "
    "flows, not cost-basis PnL: fees are accounted in TON terms only and "
    "cost basis remains unavailable, so Real PnL stays locked."
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


def derive_run_pnl_preview_with_historical(
    run: dict,
    settings=None,
) -> dict[str, Any]:
    """Return the estimated PnL preview enriched with USD-valued swap legs."""
    settings = settings or get_settings()
    preview = derive_run_pnl_preview(run)

    # The same TON-side legs the TON-denominated estimate uses.
    legs: list[tuple[str, str, Decimal, datetime | None]] = []
    for swap in run.get("swaps") or []:
        token_in = (swap.get("token_in") or "").upper()
        token_out = (swap.get("token_out") or "").upper()
        amount_in = _decimal(swap.get("amount_in"))
        amount_out = _decimal(swap.get("amount_out"))
        timestamp = _parse_ts(swap.get("timestamp"))
        if token_in == "TON" and token_out and token_out != "TON" and amount_in:
            legs.append((swap["token_out"], "buy", amount_in, timestamp))
        elif token_out == "TON" and token_in and token_in != "TON" and amount_out:
            legs.append((swap["token_in"], "sell", amount_out, timestamp))

    if not legs:
        preview["historical_pricing"] = _evidence(
            "unavailable", 0, 0, 0,
            "No TON-side swap legs exist to value in USD.",
        )
        return preview

    timestamps = [ts for (_, _, _, ts) in legs if ts is not None]
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
    for token, side, ton_amount, timestamp in legs:
        price = _nearest_price(points, timestamp) if timestamp else None
        if price is None:
            unmatched += 1
            continue
        matched += 1
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
        usd_value = ton_amount * price
        if side == "buy":
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
        _set_requirement(
            preview,
            "cost_basis",
            False,
            "Cost basis requires acquisition history beyond this run's "
            "window; only in-window USD-valued flows are computed.",
        )

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
