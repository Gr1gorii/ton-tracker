"""Lightweight TonAPI wallet intelligence preview helpers.

All signals in this module are derived only from TonAPI account jetton preview
rows. The helpers do not fetch transactions, TON balances, swaps, PnL, or full
wallet history.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

STABLECOIN_MARKERS = ("USDT", "USDC", "USD")


def build_wallet_intelligence_preview(
    account_address: str,
    jettons: list[dict[str, Any]],
    total_jettons: int,
    preview_count: int,
    requested_limit: int,
) -> dict[str, Any]:
    """Build simple, bounded signals from already-returned jetton rows."""
    safe_jettons = [item for item in jettons if isinstance(item, dict)]
    non_zero_count = sum(1 for item in safe_jettons if _is_positive_balance(item))
    price_count = sum(1 for item in safe_jettons if _has_price(item))
    stablecoin_like_count = sum(
        1 for item in safe_jettons if _is_stablecoin_like(item)
    )

    return {
        "scope": "account_jettons_preview_only",
        "data_sources": ["tonapi"],
        "account_address": account_address,
        "total_jettons": total_jettons,
        "preview_count": preview_count,
        "requested_limit": requested_limit,
        "non_zero_balance_count": non_zero_count,
        "jettons_with_price_count": price_count,
        "stablecoin_like_count": stablecoin_like_count,
        "top_jettons_by_display_balance": _top_jettons_by_display_balance(
            safe_jettons,
        ),
        "basic_notes": _basic_notes(
            total_jettons=total_jettons,
            preview_count=preview_count,
            requested_limit=requested_limit,
            price_count=price_count,
            stablecoin_like_count=stablecoin_like_count,
        ),
    }


def empty_wallet_intelligence_preview(
    account_address: str,
    requested_limit: int,
    note: str,
) -> dict[str, Any]:
    """Return an empty intelligence envelope when provider data is unavailable."""
    return {
        "scope": "account_jettons_preview_only",
        "data_sources": ["tonapi"],
        "account_address": account_address,
        "total_jettons": 0,
        "preview_count": 0,
        "requested_limit": requested_limit,
        "non_zero_balance_count": 0,
        "jettons_with_price_count": 0,
        "stablecoin_like_count": 0,
        "top_jettons_by_display_balance": [],
        "basic_notes": [note],
    }


def _basic_notes(
    total_jettons: int,
    preview_count: int,
    requested_limit: int,
    price_count: int,
    stablecoin_like_count: int,
) -> list[str]:
    notes = [
        "Signals are derived only from TonAPI account jetton preview rows.",
        "No transaction history, DEX swaps, TON balance, or PnL are fetched "
        "or inferred.",
    ]
    if preview_count == 0:
        notes.append(
            "No jettons were returned in this preview. This is not evidence "
            "that the wallet is empty; it only means no account jetton rows "
            "were available in this response."
        )
    if total_jettons > preview_count:
        notes.append(
            f"Only {preview_count} of {total_jettons} returned jettons are "
            f"included because the requested preview limit is {requested_limit}."
        )
    if price_count == 0:
        notes.append("No price fields were present in the preview rows.")
    else:
        notes.append(
            "Price fields are counted only when TonAPI returned a price value; "
            "no PnL is calculated."
        )
    if stablecoin_like_count > 0:
        notes.append(
            "Stablecoin-like labels are simple symbol/name heuristics only."
        )
    return notes


def _top_jettons_by_display_balance(
    jettons: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    ranked = []
    for item in jettons:
        display_balance = _display_balance(item)
        if display_balance is None:
            continue
        ranked.append((display_balance, item))

    ranked.sort(key=lambda pair: pair[0], reverse=True)
    return [
        {
            "jetton_address": _optional_string(item.get("jetton_address")),
            "jetton_name": _optional_string(item.get("jetton_name")),
            "jetton_symbol": _optional_string(item.get("jetton_symbol")),
            "balance": _optional_string(item.get("balance")),
            "decimals": _optional_int(item.get("decimals")),
            "display_balance": _decimal_to_string(display_balance),
            "price_usd": _optional_string(
                item.get("price_usd") or item.get("price")
            ),
            "wallet_contract_address": _optional_string(
                item.get("wallet_contract_address")
            ),
            "source": _optional_string(item.get("source")),
        }
        for display_balance, item in ranked[:limit]
    ]


def _display_balance(item: dict[str, Any]) -> Decimal | None:
    raw_balance = _decimal_value(item.get("balance"))
    if raw_balance is None:
        return None

    decimals = _optional_int(item.get("decimals"))
    if decimals is None:
        return raw_balance
    if decimals < 0 or decimals > 255:
        return raw_balance
    return raw_balance / (Decimal(10) ** decimals)


def _is_positive_balance(item: dict[str, Any]) -> bool:
    value = _decimal_value(item.get("balance"))
    return value is not None and value > 0


def _has_price(item: dict[str, Any]) -> bool:
    return _optional_string(item.get("price_usd") or item.get("price")) is not None


def _is_stablecoin_like(item: dict[str, Any]) -> bool:
    text = " ".join(
        value
        for value in (
            _optional_string(item.get("jetton_symbol")),
            _optional_string(item.get("jetton_name")),
        )
        if value
    ).upper()
    if not text:
        return False
    return any(marker in text for marker in STABLECOIN_MARKERS)


def _decimal_value(value: Any) -> Decimal | None:
    cleaned = _optional_string(value)
    if cleaned is None:
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def _decimal_to_string(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
