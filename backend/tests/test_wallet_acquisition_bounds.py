"""Tests for immutable half-open wallet acquisition intervals."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.wallet_acquisition_bounds import (
    WALLET_ACQUISITION_BOUNDS_VERSION,
    resolve_wallet_acquisition_bounds,
)


NOW = datetime(2026, 7, 10, 12, 30, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("window", "delta"),
    [
        ("24h", timedelta(hours=24)),
        ("3d", timedelta(days=3)),
        ("7d", timedelta(days=7)),
    ],
)
def test_rolling_windows_freeze_one_exact_half_open_interval(window, delta):
    bounds = resolve_wallet_acquisition_bounds(
        time_window=window,
        custom_start=None,
        custom_end=None,
        now=NOW,
    )

    assert bounds.version == WALLET_ACQUISITION_BOUNDS_VERSION
    assert bounds.start == NOW - delta
    assert bounds.end == NOW
    assert bounds.contains(bounds.start) is True
    assert bounds.contains(bounds.end) is False


def test_custom_bounds_normalize_to_utc_and_preserve_requested_interval():
    bounds = resolve_wallet_acquisition_bounds(
        time_window="custom",
        custom_start="2026-07-08T14:30:00+02:00",
        custom_end="2026-07-10T10:00:00Z",
        now=NOW,
    )

    assert bounds.start_iso == "2026-07-08T12:30:00Z"
    assert bounds.end_iso == "2026-07-10T10:00:00Z"


@pytest.mark.parametrize(
    "values",
    [
        {
            "time_window": "custom",
            "custom_start": None,
            "custom_end": "2026-07-10T10:00:00Z",
        },
        {
            "time_window": "custom",
            "custom_start": "2026-07-10T10:00:00Z",
            "custom_end": "2026-07-10T10:00:00Z",
        },
        {
            "time_window": "custom",
            "custom_start": "2026-07-10T10:00:00Z",
            "custom_end": "2026-07-10T13:00:00Z",
        },
        {
            "time_window": "24h",
            "custom_start": "2026-07-09T10:00:00Z",
            "custom_end": None,
        },
        {
            "time_window": "30d",
            "custom_start": None,
            "custom_end": None,
        },
    ],
)
def test_invalid_or_ambiguous_bounds_fail_closed(values):
    with pytest.raises(ValueError):
        resolve_wallet_acquisition_bounds(now=NOW, **values)
