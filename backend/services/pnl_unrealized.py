"""Optional unrealized valuation of remaining in-window holdings.

Spot-based and informational only: the remaining quantity of tokens whose
in-window cost basis was computed is valued at the current provider-reported
spot price. Unrealized figures never feed the Real-PnL requirement checklist
or the realized results; spot prices may be stale and every record names the
source that priced it. No hidden fallback: tokens without a recorded jetton
master address or without a provider price stay visible as unavailable.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from config import get_settings
from services.pnl_usd_valuation import derive_run_pnl_preview_with_historical
from services.pricing import price_assets

UNREALIZED_NOTE = (
    "Unrealized figures value remaining in-window holdings at current "
    "provider-reported spot prices, which may be stale. They are "
    "informational only: excluded from realized figures and from the "
    "Real-PnL evidence checklist."
)

ZERO = Decimal("0")

# Deterministic mock spot price so the default mock path never queries
# providers; clearly attributed via priced_by="mock".
_MOCK_SPOT_JETTON = Decimal("0.06")


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _money(value: Decimal) -> str:
    return f"{value:f}"


def _unavailable(token: str, reason: str) -> dict[str, Any]:
    return {"token": token, "status": "unavailable", "reason": reason}


def derive_run_pnl_preview_with_unrealized(
    run: dict,
    settings=None,
) -> dict[str, Any]:
    """Return the historical-enriched preview plus unrealized valuation."""
    settings = settings or get_settings()
    preview = derive_run_pnl_preview_with_historical(run, settings=settings)

    # Jetton master addresses recorded on the run's swap rows, per token.
    address_by_token: dict[str, str] = {}
    for swap in run.get("swaps") or []:
        for token_key, address_key in (
            ("token_in", "token_in_address"),
            ("token_out", "token_out_address"),
        ):
            token = swap.get(token_key)
            address = swap.get(address_key)
            if (
                token
                and str(token).upper() != "TON"
                and address
                and token not in address_by_token
            ):
                address_by_token[token] = address

    records: list[dict[str, Any]] = []
    candidates: list[tuple[str, Decimal, Decimal]] = []
    for realized in preview.get("realized_pnl", []) or []:
        token = realized["token"]
        if realized["status"] != "computed":
            records.append(
                _unavailable(
                    token,
                    "In-window cost basis is unavailable for this token.",
                )
            )
            continue
        remaining = _decimal(realized.get("remaining_qty")) or ZERO
        if remaining <= ZERO:
            continue  # nothing left in-window to value
        if token not in address_by_token:
            records.append(
                _unavailable(
                    token,
                    "No jetton master address is recorded for this token's "
                    "swap rows.",
                )
            )
            continue
        remaining_cost = _decimal(realized.get("remaining_cost_usd")) or ZERO
        candidates.append((token, remaining, remaining_cost))

    spot: dict[str, tuple[Decimal, str]] = {}
    if candidates:
        if settings.is_mock:
            for token, _, _ in candidates:
                spot[token] = (_MOCK_SPOT_JETTON, "mock")
        else:
            specs = [
                {"asset": token, "token": address_by_token[token]}
                for token, _, _ in candidates
            ]
            pricing = price_assets(specs, settings=settings)
            preview["warnings"].extend(pricing.get("warnings", []))
            for item in pricing.get("prices", []):
                price = _decimal(item.get("price_usd"))
                # A non-positive provider price for a token more likely means
                # "unknown token" than "worth zero" -- treat it as unpriced.
                if price is not None and price > ZERO and item.get("priced_by"):
                    spot[item["asset"]] = (price, item["priced_by"])

    total_unrealized = ZERO
    computed_any = False
    for token, remaining, remaining_cost in candidates:
        priced = spot.get(token)
        if priced is None:
            records.append(
                _unavailable(
                    token,
                    "No provider spot price is available for this token.",
                )
            )
            continue
        price, priced_by = priced
        market_value = remaining * price
        unrealized = market_value - remaining_cost
        computed_any = True
        total_unrealized += unrealized
        records.append(
            {
                "token": token,
                "status": "computed",
                "reason": None,
                "remaining_qty": _money(remaining),
                "remaining_cost_usd": _money(remaining_cost),
                "spot_price_usd": _money(price),
                "priced_by": priced_by,
                "market_value_usd": _money(market_value),
                "unrealized_pnl_usd": _money(unrealized),
            }
        )

    preview["unrealized"] = sorted(records, key=lambda record: record["token"])
    preview["total_unrealized_pnl_usd"] = (
        _money(total_unrealized) if computed_any else None
    )
    preview["unrealized_note"] = UNREALIZED_NOTE if records else None
    return preview
