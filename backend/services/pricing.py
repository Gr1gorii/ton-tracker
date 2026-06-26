"""Provider-priced USD valuation helper for wallet assets.

Two explicit price sources are queried: TonAPI rates first, then GeckoTerminal
for assets TonAPI did not price. Each asset records which source priced it
(``priced_by``); assets neither source priced stay ``unpriced``. There is no
hidden fallback and no inferred price — only provider-reported USD values
(treated as ~USDT for stablecoin purposes).
"""

from __future__ import annotations

from typing import Any

from adapters.geckoterminal import GeckoTerminalAdapter
from adapters.tonapi import TonapiAdapter
from config import get_settings

PRICING_NOTE = (
    "Prices are provider-reported USD (~USDT) from TonAPI rates and "
    "GeckoTerminal. Each asset shows which source priced it; unpriced assets "
    "are excluded from valuation. Prices may be stale and are not PnL. No "
    "hidden fallback is used."
)


def price_assets(assets: list[dict[str, Any]], settings=None) -> dict[str, Any]:
    """Return USD prices for ``assets`` from two explicit sources.

    Each asset is ``{"asset": <label>, "token": "ton"|<jetton_address>|None}``.
    """
    settings = settings or get_settings()
    tonapi = TonapiAdapter(settings)
    gecko = GeckoTerminalAdapter(settings)
    warnings: list[str] = []

    tokens = [
        spec["token"]
        for spec in assets
        if isinstance(spec, dict) and spec.get("token")
    ]
    tonapi_rates: dict[str, str | None] = {}
    if tokens:
        result = tonapi.get_rates_preview(tokens)
        if result.ok and isinstance(result.data, dict):
            raw = result.data.get("rates")
            if isinstance(raw, dict):
                tonapi_rates = {str(k).lower(): v for k, v in raw.items()}
        elif not result.ok:
            warnings.append(f"TonAPI rates warning: {result.message}")

    prices: list[dict[str, Any]] = []
    for spec in assets:
        if not isinstance(spec, dict):
            continue
        label = spec.get("asset")
        token = spec.get("token")
        price: str | None = None
        priced_by: str | None = None

        if token:
            tonapi_price = tonapi_rates.get(str(token).lower())
            if tonapi_price:
                price = tonapi_price
                priced_by = "tonapi"

        if price is None and token and str(token).lower() != "ton":
            gecko_result = gecko.get_token_price(token)
            if gecko_result.ok and isinstance(gecko_result.data, dict):
                gecko_price = gecko_result.data.get("price_usd")
                if gecko_price:
                    price = str(gecko_price)
                    priced_by = "geckoterminal"
            elif not gecko_result.ok:
                warnings.append(
                    f"GeckoTerminal price warning ({label}): "
                    f"{gecko_result.message}"
                )

        prices.append(
            {
                "asset": label,
                "token": token,
                "price_usd": price,
                "priced_by": priced_by,
            }
        )

    unpriced = [item["asset"] for item in prices if item["price_usd"] is None]
    return {
        "currency": "usd",
        "prices": prices,
        "unpriced": unpriced,
        "warnings": warnings,
        "note": PRICING_NOTE,
    }
