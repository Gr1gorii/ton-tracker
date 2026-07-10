"""Resolve one immutable UTC interval for wallet activity acquisition."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

WalletTimeWindow = Literal["24h", "3d", "7d", "custom"]

WALLET_ACQUISITION_BOUNDS_VERSION = "wallet_time_bounds_v1"

_ROLLING_WINDOWS = {
    "24h": timedelta(hours=24),
    "3d": timedelta(days=3),
    "7d": timedelta(days=7),
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_iso(value: str | None, field_name: str) -> datetime:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a nonblank ISO datetime.")
    cleaned = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be a valid ISO datetime.") from exc
    return _utc(parsed)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class WalletAcquisitionBounds:
    version: str
    time_window: WalletTimeWindow
    start: datetime
    end: datetime

    @property
    def start_iso(self) -> str:
        return _iso(self.start)

    @property
    def end_iso(self) -> str:
        return _iso(self.end)

    def contains(self, value: datetime) -> bool:
        candidate = _utc(value)
        return self.start <= candidate < self.end


def resolve_wallet_acquisition_bounds(
    *,
    time_window: str,
    custom_start: str | None,
    custom_end: str | None,
    now: datetime,
) -> WalletAcquisitionBounds:
    """Freeze one half-open ``[start, end)`` interval for a request."""
    resolved_now = _utc(now)
    if time_window in _ROLLING_WINDOWS:
        if custom_start is not None or custom_end is not None:
            raise ValueError(
                "custom_start and custom_end are allowed only for custom windows."
            )
        end = resolved_now
        start = end - _ROLLING_WINDOWS[time_window]
    elif time_window == "custom":
        start = _parse_iso(custom_start, "custom_start")
        end = _parse_iso(custom_end, "custom_end")
        if end > resolved_now:
            raise ValueError("custom_end cannot be later than acquisition time.")
    else:
        raise ValueError("Unsupported wallet acquisition time_window.")

    if start >= end:
        raise ValueError("Wallet acquisition start must be before end.")
    return WalletAcquisitionBounds(
        version=WALLET_ACQUISITION_BOUNDS_VERSION,
        time_window=time_window,
        start=start,
        end=end,
    )
