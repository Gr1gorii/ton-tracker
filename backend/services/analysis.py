"""Analysis orchestration.

Pulls raw (currently mock) market + wallet data through the adapters, enriches
each wallet with PnL and behavioral flags, runs the probabilistic clustering,
and assembles the full response payload consumed by the frontend.

Everything network-specific lives behind the adapters in ``backend/adapters``;
swapping mock data for real GeckoTerminal / TON indexer calls should not
require changes here.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from adapters.bitquery import BitqueryAdapter
from adapters.geckoterminal import GeckoTerminalAdapter
from adapters.ton_provider import TonProviderAdapter
from config import ProviderResult, Settings, get_settings
from services import clustering, mock_data
from services.mock_data import (
    HIGH_TON_BALANCE,
    INTERESTING_POSITION_USD,
    TON_PRICE_USD,
)
from services.pnl import calculate_pnl

# Named window -> length in seconds.
NAMED_WINDOWS = {
    "24h": 24 * 3600,
    "3d": 3 * 24 * 3600,
    "7d": 7 * 24 * 3600,
}


def _resolve_window(
    time_window: str,
    custom_start: str | None,
    custom_end: str | None,
) -> tuple[datetime, datetime, int]:
    """Return (start, end, window_seconds) for the requested window."""
    now = datetime.now(timezone.utc)

    if time_window == "custom":
        if not custom_start or not custom_end:
            raise ValueError(
                "custom_start and custom_end are required for a custom window"
            )
        start = _parse_iso(custom_start)
        end = _parse_iso(custom_end)
        if end <= start:
            raise ValueError("custom_end must be after custom_start")
        return start, end, int((end - start).total_seconds())

    seconds = NAMED_WINDOWS.get(time_window)
    if seconds is None:
        raise ValueError(
            f"Unknown time_window '{time_window}'. "
            "Use one of: 24h, 3d, 7d, custom."
        )
    start = now - timedelta(seconds=seconds)
    return start, now, seconds


def _parse_iso(value: str) -> datetime:
    # Accept trailing 'Z' as UTC.
    cleaned = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(cleaned)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _build_vyvod(status: str, pnl, interesting: bool, whale: bool) -> str:
    """Compose a short hedged Russian conclusion for one wallet."""
    status_ru = {
        "holder": "Холдер: позиция всё ещё удерживается.",
        "partial_seller": "Частичная продажа: продал часть, остаток держит.",
        "full_exit": "Полный выход: позиция закрыта.",
        "unknown": "Недостаточно данных по сделкам.",
    }[status]

    parts = [status_ru]

    if status in ("holder", "partial_seller"):
        sign = "+" if pnl.unrealised_pnl_usd >= 0 else ""
        parts.append(
            f"Нереализованный PnL {sign}{pnl.unrealised_pnl_usd:.2f}$ "
            f"({sign}{pnl.unrealised_pnl_pct:.2f}%)."
        )
    if status in ("partial_seller", "full_exit"):
        sign = "+" if pnl.realised_pnl_usd >= 0 else ""
        parts.append(
            f"Реализованный PnL {sign}{pnl.realised_pnl_usd:.2f}$ "
            f"({sign}{pnl.realised_pnl_pct:.2f}%)."
        )
    if whale:
        parts.append("Крупный баланс TON (кит).")
    if interesting:
        parts.append("Есть позиция дороже $5,000 — ИНТЕРЕСНО.")

    return " ".join(parts)


def _enrich_wallet(raw: dict, current_price: float, window_seconds: int,
                   window_start: datetime) -> dict:
    """Compute PnL, positions, flags and conclusion for a single wallet."""
    pnl = calculate_pnl(
        total_bought_qty=raw["total_bought_qty"],
        total_bought_usd=raw["total_bought_usd"],
        total_sold_qty=raw["total_sold_qty"],
        total_sold_usd=raw["total_sold_usd"],
        current_holding=raw["current_holding"],
        current_price_usd=current_price,
    )

    analyzed_value = raw["current_holding"] * current_price
    positions = list(raw["other_positions"])
    if raw["current_holding"] > 0:
        positions = [
            {"symbol": "GRAM", "value_usd": round(analyzed_value, 2)}
        ] + positions

    max_position_value = max(
        (p["value_usd"] for p in positions), default=0.0
    )
    interesting = max_position_value > INTERESTING_POSITION_USD
    whale = raw["ton_balance"] > HIGH_TON_BALANCE

    ton_value = raw["ton_balance"] * TON_PRICE_USD
    portfolio_value = round(
        sum(p["value_usd"] for p in positions) + ton_value, 2
    )

    bought_qty = raw["total_bought_qty"] or 0
    sold_fraction = (
        raw["total_sold_qty"] / bought_qty if bought_qty > 0 else 0.0
    )

    buy_offset_s = raw["buy_time_fraction"] * window_seconds
    buy_time = (window_start + timedelta(seconds=buy_offset_s)).isoformat()

    return {
        "address": raw["address"],
        "status": pnl.status,
        "total_bought_qty": raw["total_bought_qty"],
        "total_bought_usd": raw["total_bought_usd"],
        "total_sold_qty": raw["total_sold_qty"],
        "total_sold_usd": raw["total_sold_usd"],
        "current_holding": raw["current_holding"],
        "avg_buy_price_usd": pnl.avg_buy_price_usd,
        "avg_sell_price_usd": pnl.avg_sell_price_usd,
        "realised_pnl_usd": pnl.realised_pnl_usd,
        "realised_pnl_pct": pnl.realised_pnl_pct,
        "unrealised_pnl_usd": pnl.unrealised_pnl_usd,
        "unrealised_pnl_pct": pnl.unrealised_pnl_pct,
        "total_pnl_usd": pnl.total_pnl_usd,
        "total_pnl_pct": pnl.total_pnl_pct,
        "ton_balance": raw["ton_balance"],
        "portfolio_value_usd": portfolio_value,
        "positions": positions,
        "max_position_value_usd": round(max_position_value, 2),
        "common_tokens": raw["common_tokens"],
        "group": raw["group"],
        "interesting": interesting,
        "high_ton_balance": whale,
        "buy_time": buy_time,
        # Fields used by the clustering similarity model.
        "sold_fraction": round(sold_fraction, 4),
        "buy_time_offset_s": buy_offset_s,
        # Per-wallet conclusion (filled with connected score appended later).
        "Вывод": _build_vyvod(pnl.status, pnl, interesting, whale),
        "_pnl": pnl,  # internal, stripped before returning
    }


def _common_holdings(wallets: list[dict]) -> list[dict]:
    """Aggregate tokens held across wallets (held by 2+ wallets)."""
    counts: dict[str, int] = {}
    values: dict[str, float] = {}
    holders: dict[str, list[str]] = {}

    for w in wallets:
        # Map this wallet's position values by symbol for value aggregation.
        pos_value = {p["symbol"]: p["value_usd"] for p in w["positions"]}
        for token in w["common_tokens"]:
            counts[token] = counts.get(token, 0) + 1
            values[token] = values.get(token, 0.0) + pos_value.get(token, 0.0)
            holders.setdefault(token, []).append(w["address"])

    result = [
        {
            "token": token,
            "holder_count": count,
            "total_value_usd": round(values.get(token, 0.0), 2),
            "holders": holders.get(token, []),
        }
        for token, count in counts.items()
        if count >= 2
    ]
    result.sort(key=lambda r: (-r["holder_count"], -r["total_value_usd"]))
    return result


def get_providers_status(settings: Optional[Settings] = None) -> dict:
    """Report configuration/availability for every provider.

    Used by both the /api/providers/status endpoint and the data_quality
    block. Does not make network calls.
    """
    settings = settings or get_settings()
    gecko = GeckoTerminalAdapter(settings)
    ton = TonProviderAdapter(settings)
    bitquery = BitqueryAdapter(settings)
    return {
        "data_mode": settings.data_mode,
        "geckoterminal": gecko.status(),
        "ton_provider": ton.status(),
        "bitquery": bitquery.status(),
    }


def _build_data_quality(
    settings: Settings,
    gecko_result: ProviderResult,
    providers_status: dict,
) -> dict:
    """Assemble warnings + provider notes describing data provenance."""
    warnings: list[str] = []
    provider_notes: list[str] = []

    if settings.is_mock:
        warnings.append(
            "v0.2 is running in mock mode. No real on-chain data is used."
        )
        provider_notes.append(
            "All pool, token, wallet, PnL and clustering data is mock."
        )
        return {
            "mode": settings.data_mode,
            "warnings": warnings,
            "provider_notes": provider_notes,
        }

    # Real mode.
    if gecko_result.ok and gecko_result.source == "real":
        provider_notes.append(
            "GeckoTerminal pool data is real, but wallet-level analysis is "
            "still mocked."
        )
    elif not gecko_result.ok:
        warnings.append(
            gecko_result.message
            or "GeckoTerminal pool data is unavailable; using mock pool data."
        )
        provider_notes.append("Falling back to mock pool/token data.")

    if not providers_status["ton_provider"]["available"]:
        warnings.append(providers_status["ton_provider"]["message"])
    if not providers_status["bitquery"]["available"]:
        warnings.append(providers_status["bitquery"]["message"])

    provider_notes.append(
        "Wallet-level analysis (buyers, PnL, clustering) uses mock data in "
        "v0.2."
    )
    return {
        "mode": settings.data_mode,
        "warnings": warnings,
        "provider_notes": provider_notes,
    }


def analyze(
    pool_url: str,
    time_window: str,
    custom_start: str | None = None,
    custom_end: str | None = None,
    settings: Optional[Settings] = None,
) -> dict:
    """Run the analysis and return the response payload.

    Pool/token data may be real (DATA_MODE=real + reachable GeckoTerminal);
    wallet-level data is mock in v0.2. The ``data_quality`` block documents
    exactly what is real vs mock for this run.
    """
    settings = settings or get_settings()
    start, end, window_seconds = _resolve_window(
        time_window, custom_start, custom_end
    )

    gecko = GeckoTerminalAdapter(settings)
    ton = TonProviderAdapter(settings)

    # Pool/token: real when configured + reachable, otherwise mock fallback.
    gecko_result = gecko.get_pool_and_token(pool_url)
    if gecko_result.ok:
        token_info = gecko_result.data["token"]
        pool_info = gecko_result.data["pool"]
    else:
        parsed = gecko.parse_pool_url(pool_url)
        token_info = mock_data.get_token_info()
        pool_info = mock_data.get_pool_info()
        pool_info["requested_network"] = parsed["network"]
        pool_info["requested_pool_address"] = parsed["pool_address"]

    # Wallet aggregates remain mock in v0.2.
    raw_wallets = ton.get_window_buyers(pool_url, start, end)

    providers_status = get_providers_status(settings)
    data_quality = _build_data_quality(settings, gecko_result, providers_status)

    current_price = token_info["current_price_usd"]

    enriched = [
        _enrich_wallet(w, current_price, window_seconds, start)
        for w in raw_wallets
    ]

    # Clustering needs the enriched view (avg buy price, portfolio, etc.).
    for w in enriched:
        w["connected_score"] = clustering.connected_score_for_wallet(
            w, enriched, window_seconds
        )

    groups = clustering.build_groups(enriched, window_seconds)
    common = _common_holdings(enriched)

    # Strip internal-only fields from the public payload.
    for w in enriched:
        w.pop("_pnl", None)
        w.pop("buy_time_offset_s", None)

    interesting_wallets = [w for w in enriched if w["interesting"]]
    whales = [w for w in enriched if w["high_ton_balance"]]

    summary = {
        "total_buyers": len(enriched),
        "holders": sum(1 for w in enriched if w["status"] == "holder"),
        "partial_sellers": sum(
            1 for w in enriched if w["status"] == "partial_seller"
        ),
        "full_exits": sum(1 for w in enriched if w["status"] == "full_exit"),
        "interesting_count": len(interesting_wallets),
        "whale_count": len(whales),
        "group_count": len(groups),
        "total_realised_pnl_usd": round(
            sum(w["realised_pnl_usd"] for w in enriched), 2
        ),
        "total_unrealised_pnl_usd": round(
            sum(w["unrealised_pnl_usd"] for w in enriched), 2
        ),
    }

    return {
        "pool_url": pool_url,
        "time_window": time_window,
        "analyzed_window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "window_seconds": window_seconds,
        },
        "token": token_info,
        "pool": pool_info,
        "summary": summary,
        "wallets": enriched,
        "groups": groups,
        "common_holdings": common,
        "interesting_wallets": interesting_wallets,
        "data_quality": data_quality,
        "providers": providers_status,
        "disclaimer": (
            "v0.2 — анализ кошельков (покупатели, PnL, кластеризация) "
            "использует mock-данные. Данные пула/токена могут быть реальными "
            "в режиме real. Кластеризация носит вероятностный характер и не "
            "является доказательством общего владения кошельками."
        ),
        "is_mock": settings.is_mock,
    }
