"""Focused tests for bounded TonAPI transaction acquisition."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from config import DEFAULT_TONAPI_BASE_URL, ProviderResult, Settings
from adapters.wallet_activity import (
    TONAPI_TRANSACTION_ACQUISITION_CONTRACT,
    TonapiWalletActivityLiveAdapter,
    WalletActivityAdapterRequest,
)


START = datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc)
END = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
_AUTO_CURSOR = object()


def _settings(*, page_size: int = 2, page_cap: int = 10) -> Settings:
    return Settings(
        data_mode="real",
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        ton_api_base_url="",
        ton_api_key="",
        bitquery_api_url="",
        bitquery_api_key="",
        stonfi_base_url="https://api.ston.fi",
        tonapi_base_url=DEFAULT_TONAPI_BASE_URL,
        tonapi_api_key="page-secret",
        wallet_activity_provider="tonapi",
        wallet_activity_live_enabled=True,
        wallet_activity_live_tx_limit=page_size,
        wallet_activity_live_tx_max_pages=page_cap,
    )


def _request(*, bounded: bool = True) -> WalletActivityAdapterRequest:
    return WalletActivityAdapterRequest(
        wallet_address="EQwallet",
        time_window="custom",
        surfaces=["transactions"],
        environment_data_mode="real",
        custom_start="2026-07-10T10:00:00Z",
        custom_end="2026-07-10T12:00:00Z",
        resolved_start=START if bounded else None,
        resolved_end=END if bounded else None,
    )


def _row(logical_time: str, timestamp: datetime, tx_hash: str) -> dict:
    return {
        "wallet_address": "EQwallet",
        "tx_hash": tx_hash,
        "logical_time": logical_time,
        "utime": int(timestamp.timestamp()),
        "total_fees": "1000000",
        "success": True,
        "transaction_type": "TransOrd",
        "orig_status": "active",
        "end_status": "active",
        "source": "tonapi",
    }


def _page(
    rows: list[dict],
    *,
    request_cursor: str | None,
    limit: int,
    next_cursor=_AUTO_CURSOR,
) -> ProviderResult:
    logical_times = [row["logical_time"] for row in rows]
    minimum = min(logical_times, key=int) if logical_times else None
    maximum = max(logical_times, key=int) if logical_times else None
    if next_cursor is _AUTO_CURSOR:
        next_cursor = minimum
    return ProviderResult.success(
        {
            "wallet_address": "EQwallet",
            "requested_limit": limit,
            "request_before_lt": request_cursor,
            "raw_count": len(rows),
            "min_logical_time": minimum,
            "max_logical_time": maximum,
            "next_before_lt": next_cursor,
            "transactions": rows,
        },
        source="real",
        message="TonAPI transaction page fetched.",
    )


def _install_pages(monkeypatch, adapter, responses):
    calls = []
    pending = iter(responses)

    def fake_page(account_address, limit, before_lt=None):
        calls.append((account_address, limit, before_lt))
        response = next(pending)
        return response() if callable(response) else response

    monkeypatch.setattr(
        adapter.tonapi,
        "get_account_transactions_page",
        fake_page,
    )
    return calls


def _stream(result):
    assert len(result.acquisition_streams) == 1
    return result.acquisition_streams[0]


def test_empty_page_is_provider_terminal_with_verified_bounds(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings())
    calls = _install_pages(
        monkeypatch,
        adapter,
        [_page([], request_cursor=None, limit=2)],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "success"
    assert result.incomplete_surfaces == []
    assert result.transactions == []
    assert calls == [("EQwallet", 2, None)]
    assert stream.contract_version == TONAPI_TRANSACTION_ACQUISITION_CONTRACT
    assert stream.scope_kind == "bounded_interval"
    assert stream.completion_state == "complete"
    assert stream.termination_reason == "provider_terminal"
    assert stream.bounds_verified is True
    assert stream.page_count == 1
    assert stream.pages[0].raw_count == 0
    assert stream.pages[0].response_digest
    assert len(stream.pages[0].response_digest) == 64
    assert stream.pages[0].attempt_count == 1


def test_crossing_requested_start_completes_and_excludes_older_rows(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings())
    calls = _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [
                    _row(
                        "500",
                        datetime(2026, 7, 10, 11, 30, tzinfo=timezone.utc),
                        "A",
                    ),
                    _row(
                        "400",
                        datetime(2026, 7, 10, 10, 30, tzinfo=timezone.utc),
                        "B",
                    ),
                ],
                request_cursor=None,
                limit=2,
            ),
            _page(
                [
                    _row("300", datetime(2026, 7, 10, 9, 59, tzinfo=timezone.utc), "C"),
                ],
                request_cursor="400",
                limit=2,
            ),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert calls == [("EQwallet", 2, None), ("EQwallet", 2, "400")]
    assert [row.tx_hash for row in result.transactions] == ["A", "B"]
    assert stream.completion_state == "complete"
    assert stream.termination_reason == "requested_start_crossed"
    assert stream.bounds_verified is True
    assert stream.raw_count == 3
    assert stream.normalized_count == 2
    assert stream.pages[1].normalized_count == 0


def test_page_cap_is_incomplete_and_marks_transaction_surface(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(
        _settings(page_size=1, page_cap=2)
    )
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [_row("500", datetime(2026, 7, 10, 11, 30, tzinfo=timezone.utc), "A")],
                request_cursor=None,
                limit=1,
            ),
            _page(
                [_row("400", datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc), "B")],
                request_cursor="500",
                limit=1,
            ),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "partial"
    assert result.provider_evidence[0].source_status == "limited"
    assert result.incomplete_surfaces == ["transactions"]
    assert result.unavailable_surfaces == []
    assert [row.tx_hash for row in result.transactions] == ["A", "B"]
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "page_cap_reached"
    assert stream.bounds_verified is False
    assert stream.page_count == 2


def test_overlap_is_deduplicated_by_lt_and_lowercase_hash(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(
        _settings(page_size=2, page_cap=3)
    )
    duplicate_time = datetime(2026, 7, 10, 10, 30, tzinfo=timezone.utc)
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [
                    _row("500", datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc), "A"),
                    _row("400", duplicate_time, "ABCDEF"),
                ],
                request_cursor=None,
                limit=2,
            ),
            _page(
                [
                    _row("400", duplicate_time, "abcdef"),
                    _row("300", START, "C"),
                ],
                request_cursor="400",
                limit=2,
                next_cursor="300",
            ),
            _page([], request_cursor="300", limit=2),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert [row.tx_hash for row in result.transactions] == ["A", "ABCDEF", "C"]
    assert stream.completion_state == "complete"
    assert stream.termination_reason == "provider_terminal"
    assert stream.raw_count == 4
    assert stream.normalized_count == 3
    assert stream.duplicate_count == 1
    assert stream.pages[1].duplicate_count == 1
    assert stream.pages[1].normalized_count == 1


def test_cursor_stall_after_usable_page_is_protocol_incomplete(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [_row("500", datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc), "A")],
                request_cursor=None,
                limit=1,
            ),
            _page(
                [_row("500", datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc), "A")],
                request_cursor="500",
                limit=1,
                next_cursor="500",
            ),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "partial"
    assert result.unavailable_surfaces == []
    assert result.incomplete_surfaces == ["transactions"]
    assert [row.tx_hash for row in result.transactions] == ["A"]
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "protocol_error"
    assert stream.error_code == "protocol_error"
    assert stream.pages[-1].error_code == "protocol_error"


def test_timestamp_order_regression_is_protocol_error(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [_row("500", datetime(2026, 7, 10, 10, 30, tzinfo=timezone.utc), "A")],
                request_cursor=None,
                limit=1,
            ),
            _page(
                [_row("400", datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc), "B")],
                request_cursor="500",
                limit=1,
            ),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert [row.tx_hash for row in result.transactions] == ["A"]
    assert result.incomplete_surfaces == ["transactions"]
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "protocol_error"
    assert "globally ordered" in stream.error_message


def test_provider_error_after_page_retains_rows_and_sanitizes_error(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [_row("500", datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc), "A")],
                request_cursor=None,
                limit=1,
            ),
            ProviderResult.failure(
                "provider_error",
                "request failed with page-secret",
                source="real",
            ),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "partial"
    assert [row.tx_hash for row in result.transactions] == ["A"]
    assert result.incomplete_surfaces == ["transactions"]
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "provider_error"
    assert "page-secret" not in stream.error_message
    assert "[redacted]" in stream.error_message
    assert stream.pages[-1].attempt_count == 1


def test_provider_error_before_usable_data_is_surface_error(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings())
    _install_pages(
        monkeypatch,
        adapter,
        [
            ProviderResult.failure(
                "provider_error",
                "timeout",
                source="real",
            )
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "error"
    assert result.transactions == []
    assert result.unavailable_surfaces == ["transactions"]
    assert result.incomplete_surfaces == ["transactions"]
    assert stream.completion_state == "error"
    assert stream.termination_reason == "provider_error"


def test_preview_fetches_exactly_one_page_without_persistable_rows(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1, page_cap=99))
    calls = _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [_row("500", datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc), "A")],
                request_cursor=None,
                limit=1,
            )
        ],
    )

    result = adapter.preview(_request())

    stream = _stream(result)
    assert calls == [("EQwallet", 1, None)]
    assert result.status == "success"
    assert result.transactions == []
    assert result.incomplete_surfaces == ["transactions"]
    assert stream.completion_state == "preview_only"
    assert stream.termination_reason == "preview_page_limit"
    assert stream.page_cap == 1
    assert stream.page_count == 1
    assert stream.bounds_verified is False


def test_direct_settings_page_cap_is_clamped_to_one_hundred(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_cap=999))
    _install_pages(
        monkeypatch,
        adapter,
        [_page([], request_cursor=None, limit=2)],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert stream.page_cap == 100
    assert stream.completion_state == "complete"


def test_half_open_bounds_include_start_and_exclude_end(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(
        _settings(page_size=4, page_cap=1)
    )
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [
                    _row("600", END, "AT_END"),
                    _row(
                        "500",
                        datetime(2026, 7, 10, 11, 59, tzinfo=timezone.utc),
                        "INSIDE",
                    ),
                    _row("400", START, "AT_START"),
                    _row(
                        "300",
                        datetime(2026, 7, 10, 9, 59, tzinfo=timezone.utc),
                        "BELOW",
                    ),
                ],
                request_cursor=None,
                limit=4,
            )
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert [row.tx_hash for row in result.transactions] == ["INSIDE", "AT_START"]
    assert stream.completion_state == "complete"
    assert stream.termination_reason == "requested_start_crossed"
    assert stream.bounds_verified is True
    assert stream.pages[0].normalized_count == 2


def test_legacy_no_bounds_is_one_page_and_never_claims_completeness(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings())
    calls = []

    def fake_preview(account_address, limit):
        calls.append((account_address, limit))
        row = _row(
            "500",
            datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
            "A",
        )
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "transactions": [row],
                "preview_count": 1,
                "total_transactions": 1,
            },
            source="real",
        )

    monkeypatch.setattr(
        adapter.tonapi,
        "get_account_transactions_preview",
        fake_preview,
    )

    result = adapter.ingest(_request(bounded=False))

    stream = _stream(result)
    assert calls == [("EQwallet", 2)]
    assert result.status == "success"
    assert result.incomplete_surfaces == ["transactions"]
    assert [row.tx_hash for row in result.transactions] == ["A"]
    assert stream.scope_kind == "legacy_unavailable"
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "legacy_unavailable"
    assert stream.bounds_verified is False
    assert stream.page_count == 1


@pytest.mark.parametrize("invalid_utime", [True, False, 1.9])
def test_raw_non_integer_timestamp_cannot_complete_bounds(
    monkeypatch,
    invalid_utime,
):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))

    def fake_fetch_json(path, query=None):
        return ProviderResult.success(
            {
                "transactions": [
                    {
                        "hash": "ab" * 32,
                        "lt": "500",
                        "utime": invalid_utime,
                        "total_fees": "1000000",
                        "success": True,
                    }
                ]
            },
            source="real",
        )

    monkeypatch.setattr(adapter.tonapi, "fetch_json", fake_fetch_json)

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "error"
    assert result.transactions == []
    assert result.unavailable_surfaces == ["transactions"]
    assert result.incomplete_surfaces == ["transactions"]
    assert stream.completion_state == "error"
    assert stream.termination_reason == "protocol_error"
    assert stream.bounds_verified is False
    assert "invalid timestamp" in stream.error_message


@pytest.mark.parametrize("invalid_hash", [True, {}, [], "short"])
def test_raw_noncanonical_hash_cannot_complete_bounds(
    monkeypatch,
    invalid_hash,
):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))

    monkeypatch.setattr(
        adapter.tonapi,
        "fetch_json",
        lambda path, query=None: ProviderResult.success(
            {
                "transactions": [
                    {
                        "hash": invalid_hash,
                        "lt": "500",
                        "utime": int(
                            datetime(
                                2026,
                                7,
                                10,
                                9,
                                0,
                                tzinfo=timezone.utc,
                            ).timestamp()
                        ),
                        "total_fees": "1000000",
                        "success": True,
                    }
                ]
            },
            source="real",
        ),
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "error"
    assert result.transactions == []
    assert result.unavailable_surfaces == ["transactions"]
    assert result.incomplete_surfaces == ["transactions"]
    assert stream.completion_state == "error"
    assert stream.termination_reason == "protocol_error"
    assert stream.bounds_verified is False
    assert "canonical 32-byte hash" in stream.error_message


@pytest.mark.parametrize("invalid_fee", ["Infinity", "NaN", str(2**64), 1.5])
def test_invalid_second_page_fee_preserves_prior_rows_as_protocol_incomplete(
    monkeypatch,
    invalid_fee,
):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))
    payloads = iter(
        [
            {
                "transactions": [
                    {
                        "hash": "aa" * 32,
                        "lt": "500",
                        "utime": int(
                            datetime(
                                2026,
                                7,
                                10,
                                11,
                                0,
                                tzinfo=timezone.utc,
                            ).timestamp()
                        ),
                        "total_fees": "1000000",
                        "success": True,
                    }
                ]
            },
            {
                "transactions": [
                    {
                        "hash": "bb" * 32,
                        "lt": "400",
                        "utime": int(
                            datetime(
                                2026,
                                7,
                                10,
                                10,
                                30,
                                tzinfo=timezone.utc,
                            ).timestamp()
                        ),
                        "total_fees": invalid_fee,
                        "success": True,
                    }
                ]
            },
        ]
    )

    monkeypatch.setattr(
        adapter.tonapi,
        "fetch_json",
        lambda path, query=None: ProviderResult.success(
            next(payloads),
            source="real",
        ),
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "partial"
    assert [row.tx_hash for row in result.transactions] == ["aa" * 32]
    assert result.unavailable_surfaces == []
    assert result.incomplete_surfaces == ["transactions"]
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "protocol_error"
    assert stream.error_code == "protocol_error"
    assert stream.bounds_verified is False
    assert stream.page_count == 2
    assert stream.pages[0].error_code is None
    assert stream.pages[1].error_code == "protocol_error"


def test_oversized_normalized_page_is_protocol_error(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(
        _settings(page_size=1, page_cap=1)
    )
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [
                    _row(
                        "500",
                        datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
                        "aa" * 32,
                    ),
                    _row(
                        "400",
                        datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc),
                        "bb" * 32,
                    ),
                ],
                request_cursor=None,
                limit=1,
            )
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "error"
    assert result.transactions == []
    assert stream.completion_state == "error"
    assert stream.termination_reason == "protocol_error"
    assert stream.bounds_verified is False
    assert "more rows than requested" in stream.error_message
