"""Historical rate points for standalone inspection and PnL enrichment.

Points are provider-reported (TonAPI rates chart) or deterministic mock
samples. A standalone preview does not mutate a stored run; run-scoped PnL
reuses this source only when historical enrichment is explicitly requested.
No hidden fallback: provider failure is reported as ``unavailable`` instead
of silently substituting mock points.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from adapters.tonapi import TonapiAdapter
from config import get_settings

HISTORICAL_PRICING_NOTE = (
    "This standalone preview does not alter a stored run. Run-scoped PnL "
    "requests the same provider-reported (or deterministic mock) rate source "
    "only when historical enrichment is explicitly enabled. Coverage may be "
    "sparse or stale; missing coverage stays visible instead of being inferred."
)

MAX_WINDOW_DAYS = 90

_MOCK_TON_BASE = Decimal("2.5")
_MOCK_JETTON_BASE = Decimal("0.05")
_MOCK_DAILY_STEP = Decimal("0.01")


def _parse_iso(value: str, label: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO datetime.") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _mock_points(token: str, start: datetime, end: datetime) -> list[dict]:
    """Deterministic daily mock points; clearly labeled, never provider data."""
    base = _MOCK_TON_BASE if token.lower() == "ton" else _MOCK_JETTON_BASE
    points = []
    day = start
    index = 0
    while day <= end:
        price = base + _MOCK_DAILY_STEP * index
        points.append({"timestamp": _iso(day), "price_usd": f"{price:f}"})
        day = day + timedelta(days=1)
        index += 1
    return points


def build_historical_prices_preview(
    token: str,
    start: str,
    end: str,
    settings=None,
) -> dict[str, Any]:
    """Return a preview of historical rate points for one token.

    Raises ``ValueError`` for invalid input; the router maps that to 400.
    """
    settings = settings or get_settings()
    cleaned = (token or "").strip()
    if not cleaned:
        raise ValueError("Token is required.")

    start_dt = _parse_iso(start, "start")
    end_dt = _parse_iso(end, "end")
    if start_dt >= end_dt:
        raise ValueError("start must be before end.")
    if end_dt - start_dt > timedelta(days=MAX_WINDOW_DAYS):
        raise ValueError(
            f"Preview window is capped at {MAX_WINDOW_DAYS} days."
        )

    warnings: list[str] = []
    if settings.is_mock:
        points = _mock_points(cleaned, start_dt, end_dt)
        source_status = "mock"
        message = (
            "Deterministic mock historical price preview. TonAPI was not "
            "queried."
        )
    else:
        adapter = TonapiAdapter(settings)
        result = adapter.get_rates_chart_preview(
            cleaned,
            "usd",
            start_date=int(start_dt.timestamp()),
            end_date=int(end_dt.timestamp()),
        )
        if result.ok:
            points = result.data.get("points", [])
            source_status = "real"
            message = result.message or "TonAPI historical rate points fetched."
            if not points:
                warnings.append(
                    "Provider returned no points for this window; missing "
                    "coverage stays visible instead of being inferred."
                )
        else:
            points = []
            source_status = "unavailable"
            message = result.message or "TonAPI historical rates are unavailable."
            warnings.append(
                "Provider request failed; no fallback data is substituted."
            )

    return {
        "token": cleaned,
        "currency": "usd",
        "requested_start": _iso(start_dt),
        "requested_end": _iso(end_dt),
        "data_mode": settings.data_mode,
        "source_status": source_status,
        "points": points,
        "point_count": len(points),
        "is_cost_basis_source": False,
        "warnings": warnings,
        "message": message,
        "note": HISTORICAL_PRICING_NOTE,
    }
