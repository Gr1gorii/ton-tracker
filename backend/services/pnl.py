"""PnL calculation service.

All financial math is performed with :class:`decimal.Decimal` to avoid binary
floating point rounding errors, then rounded and exposed as plain ``float`` at
the boundary so the values serialize cleanly to JSON for the frontend.

The functions here are pure: they take normalized aggregate trade figures and
return derived metrics. They make no assumptions about where the data comes
from (mock today, real on-chain indexers later).
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from decimal import Decimal, ROUND_HALF_UP, getcontext
from typing import Literal

# Give Decimal plenty of precision for intermediate products/divisions.
getcontext().prec = 50

ZERO = Decimal("0")

WalletStatus = Literal["holder", "partial_seller", "full_exit", "unknown"]

# Rounding helpers ----------------------------------------------------------

_USD_QUANT = Decimal("0.01")
_PCT_QUANT = Decimal("0.01")
_PRICE_QUANT = Decimal("0.00000001")


def _to_decimal(value) -> Decimal:
    """Coerce ints/floats/strings/Decimals into a Decimal safely."""
    if isinstance(value, Decimal):
        return value
    # Going through ``str`` avoids float artifacts like 0.1 -> 0.10000000001.
    return Decimal(str(value if value is not None else 0))


def _round(value: Decimal, quant: Decimal) -> float:
    return float(value.quantize(quant, rounding=ROUND_HALF_UP))


@dataclass
class PnLResult:
    avg_buy_price_usd: float
    avg_sell_price_usd: float
    realised_pnl_usd: float
    realised_pnl_pct: float
    unrealised_pnl_usd: float
    unrealised_pnl_pct: float
    total_pnl_usd: float
    total_pnl_pct: float
    status: WalletStatus

    def to_dict(self) -> dict:
        return asdict(self)


def classify_status(
    total_bought_qty: Decimal,
    total_sold_qty: Decimal,
    current_holding: Decimal,
) -> WalletStatus:
    """Determine a wallet's lifecycle status from aggregate quantities.

    - holder: never sold and still holds
    - partial_seller: sold some but still holds a remainder
    - full_exit: sold everything (no remaining holding)
    - unknown: insufficient data (e.g. never actually bought)
    """
    if total_bought_qty <= ZERO:
        return "unknown"

    sold = total_sold_qty > ZERO
    holding = current_holding > ZERO

    if sold and holding and total_sold_qty < total_bought_qty:
        return "partial_seller"
    if sold and not holding:
        return "full_exit"
    if not sold and holding:
        return "holder"
    # Sold >= bought but still reports a holding, or other odd combinations.
    if sold and holding:
        return "partial_seller"
    return "unknown"


def calculate_pnl(
    total_bought_qty,
    total_bought_usd,
    total_sold_qty,
    total_sold_usd,
    current_holding,
    current_price_usd,
) -> PnLResult:
    """Compute realised / unrealised / total PnL using average-cost basis.

    Average-cost method: every unit bought shares the same cost basis
    (``total_bought_usd / total_bought_qty``). Realised PnL is the sale
    proceeds minus the cost basis of the units that were sold. Unrealised PnL
    is the current market value of the remaining holding minus its cost basis.
    """
    bought_qty = _to_decimal(total_bought_qty)
    bought_usd = _to_decimal(total_bought_usd)
    sold_qty = _to_decimal(total_sold_qty)
    sold_usd = _to_decimal(total_sold_usd)
    holding = _to_decimal(current_holding)
    price = _to_decimal(current_price_usd)

    status = classify_status(bought_qty, sold_qty, holding)

    # Average prices (guard against division by zero).
    avg_buy = (bought_usd / bought_qty) if bought_qty > ZERO else ZERO
    avg_sell = (sold_usd / sold_qty) if sold_qty > ZERO else ZERO

    # Realised: proceeds from sales minus cost basis of the sold quantity.
    cost_basis_sold = avg_buy * sold_qty
    realised_usd = sold_usd - cost_basis_sold
    realised_pct = (
        (realised_usd / cost_basis_sold * Decimal(100))
        if cost_basis_sold > ZERO
        else ZERO
    )

    # Unrealised: current market value of remaining holding minus its basis.
    cost_basis_held = avg_buy * holding
    current_value = holding * price
    unrealised_usd = current_value - cost_basis_held
    unrealised_pct = (
        (unrealised_usd / cost_basis_held * Decimal(100))
        if cost_basis_held > ZERO
        else ZERO
    )

    # Total PnL measured against the entire amount of capital deployed.
    total_usd = realised_usd + unrealised_usd
    total_pct = (
        (total_usd / bought_usd * Decimal(100)) if bought_usd > ZERO else ZERO
    )

    return PnLResult(
        avg_buy_price_usd=_round(avg_buy, _PRICE_QUANT),
        avg_sell_price_usd=_round(avg_sell, _PRICE_QUANT),
        realised_pnl_usd=_round(realised_usd, _USD_QUANT),
        realised_pnl_pct=_round(realised_pct, _PCT_QUANT),
        unrealised_pnl_usd=_round(unrealised_usd, _USD_QUANT),
        unrealised_pnl_pct=_round(unrealised_pct, _PCT_QUANT),
        total_pnl_usd=_round(total_usd, _USD_QUANT),
        total_pnl_pct=_round(total_pct, _PCT_QUANT),
        status=status,
    )
