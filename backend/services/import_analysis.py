"""Analyze normalized user-imported trades without external data lookups."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")
ONE_HUNDRED = Decimal("100")

ANALYSIS_NOTE = (
    "Imported trades analysis is based only on provided trade rows. It does not "
    "fetch wallet balances or on-chain history."
)


@dataclass
class WalletAccumulator:
    wallet: str
    buy_trades_count: int = 0
    sell_trades_count: int = 0
    total_bought_qty: Decimal = ZERO
    total_bought_usd: Decimal = ZERO
    total_sold_qty: Decimal = ZERO
    total_sold_usd: Decimal = ZERO
    first_trade_time: str | None = None
    first_trade_dt: datetime | None = None
    last_trade_time: str | None = None
    last_trade_dt: datetime | None = None

    def add_trade(self, trade: dict[str, Any]) -> None:
        side = trade["side"]
        token_amount = trade["token_amount"]
        usd_amount = trade["usd_amount"]

        if side == "buy":
            self.buy_trades_count += 1
            self.total_bought_qty += token_amount
            self.total_bought_usd += usd_amount
        elif side == "sell":
            self.sell_trades_count += 1
            self.total_sold_qty += token_amount
            self.total_sold_usd += usd_amount

        trade_time = trade["block_time"]
        trade_dt = datetime.fromisoformat(trade_time)
        if self.first_trade_dt is None or trade_dt < self.first_trade_dt:
            self.first_trade_dt = trade_dt
            self.first_trade_time = trade_time
        if self.last_trade_dt is None or trade_dt > self.last_trade_dt:
            self.last_trade_dt = trade_dt
            self.last_trade_time = trade_time


def analyze_imported_trades(
    parsed: dict[str, Any],
    preview_limit: int,
    source: str,
) -> dict[str, Any]:
    """Build a simple per-wallet analysis from parser output."""
    trades = parsed["trades"]
    summary = parsed["summary"]
    wallets = _build_wallet_rows(trades)
    buy_trades_count = sum(1 for trade in trades if trade["side"] == "buy")
    sell_trades_count = sum(1 for trade in trades if trade["side"] == "sell")

    return {
        "summary": {
            "total_rows": summary["total_rows"],
            "valid_rows": summary["valid_rows"],
            "invalid_rows": summary["invalid_rows"],
            "duplicate_rows": summary["duplicate_rows"],
            "wallets_count": len(wallets),
            "buy_trades_count": buy_trades_count,
            "sell_trades_count": sell_trades_count,
            "errors": summary["errors"],
        },
        "wallets": wallets[:preview_limit],
        "trades_preview": [_json_trade(trade) for trade in trades[:preview_limit]],
        "preview_limit": preview_limit,
        "has_more_wallets": len(wallets) > preview_limit,
        "source": source,
        "analysis_note": ANALYSIS_NOTE,
    }


def _build_wallet_rows(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accumulators: dict[str, WalletAccumulator] = {}
    for trade in trades:
        wallet = trade["wallet"]
        if wallet not in accumulators:
            accumulators[wallet] = WalletAccumulator(wallet=wallet)
        accumulators[wallet].add_trade(trade)

    wallets = [_wallet_row(acc) for acc in accumulators.values()]
    return sorted(
        wallets,
        key=lambda row: (-Decimal(row["total_bought_usd"]), row["wallet"]),
    )


def _wallet_row(acc: WalletAccumulator) -> dict[str, Any]:
    net_holding_qty = acc.total_bought_qty - acc.total_sold_qty
    avg_buy_price = _ratio(acc.total_bought_usd, acc.total_bought_qty)
    avg_sell_price = _ratio(acc.total_sold_usd, acc.total_sold_qty)
    realised_pnl_usd: Decimal = ZERO
    realised_pnl_pct: Decimal | None = ZERO if acc.sell_trades_count == 0 else None

    if avg_buy_price is not None and acc.total_sold_qty > ZERO:
        sold_cost_basis = acc.total_sold_qty * avg_buy_price
        realised_pnl_usd = acc.total_sold_usd - sold_cost_basis
        if sold_cost_basis > ZERO:
            realised_pnl_pct = (realised_pnl_usd / sold_cost_basis) * ONE_HUNDRED

    return {
        "wallet": acc.wallet,
        "buy_trades_count": acc.buy_trades_count,
        "sell_trades_count": acc.sell_trades_count,
        "total_bought_qty": _decimal_string(acc.total_bought_qty),
        "total_bought_usd": _decimal_string(acc.total_bought_usd),
        "total_sold_qty": _decimal_string(acc.total_sold_qty),
        "total_sold_usd": _decimal_string(acc.total_sold_usd),
        "net_holding_qty": _decimal_string(net_holding_qty),
        "avg_buy_price_usd": _decimal_string_or_none(avg_buy_price),
        "avg_sell_price_usd": _decimal_string_or_none(avg_sell_price),
        "realized_pnl_usd": _decimal_string(realised_pnl_usd),
        "realized_pnl_pct": _decimal_string_or_none(realised_pnl_pct),
        "status": _status(acc.total_bought_qty, acc.total_sold_qty, net_holding_qty),
        "first_trade_time": acc.first_trade_time,
        "last_trade_time": acc.last_trade_time,
    }


def _status(
    total_bought_qty: Decimal,
    total_sold_qty: Decimal,
    net_holding_qty: Decimal,
) -> str:
    if total_bought_qty > ZERO and total_sold_qty == ZERO and net_holding_qty > ZERO:
        return "holder"
    if total_bought_qty > ZERO and total_sold_qty > ZERO and net_holding_qty > ZERO:
        return "partial_seller"
    if total_bought_qty > ZERO and total_sold_qty > ZERO and net_holding_qty <= ZERO:
        return "full_exit"
    if total_bought_qty == ZERO and total_sold_qty > ZERO:
        return "seller_only"
    return "unknown"


def _ratio(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    if denominator <= ZERO:
        return None
    return numerator / denominator


def _json_trade(trade: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in trade.items()}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal_string(value)
    return value


def _decimal_string_or_none(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return _decimal_string(value)


def _decimal_string(value: Decimal) -> str:
    if value == ZERO:
        return "0"
    return format(value.normalize(), "f")
