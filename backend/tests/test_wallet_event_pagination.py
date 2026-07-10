"""Black-box tests for the shared bounded TonAPI account-event chain."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from adapters.wallet_activity import (
    TONAPI_EVENT_ACQUISITION_CONTRACT,
    TonapiWalletActivityLiveAdapter,
    WalletActivityAdapterRequest,
)
from config import (
    DEFAULT_TONAPI_BASE_URL,
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_PROTOCOL,
    ProviderResult,
    Settings,
)


START = datetime(2026, 7, 10, 10, 0, tzinfo=timezone.utc)
END = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
START_SECONDS = int(START.timestamp())
END_SECONDS = int(END.timestamp())


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
        tonapi_api_key="event-secret",
        wallet_activity_provider="tonapi",
        wallet_activity_live_enabled=True,
        wallet_activity_live_event_limit=page_size,
        wallet_activity_live_event_max_pages=page_cap,
    )


def _request() -> WalletActivityAdapterRequest:
    return WalletActivityAdapterRequest(
        wallet_address="EQwallet",
        time_window="custom",
        surfaces=["transfers", "swaps"],
        environment_data_mode="real",
        custom_start="2026-07-10T10:00:00Z",
        custom_end="2026-07-10T12:00:00Z",
        resolved_start=START,
        resolved_end=END,
    )


def _event(
    logical_time: str,
    timestamp: datetime,
    event_number: int,
    *,
    in_progress: bool = False,
    actions: bool = True,
) -> dict:
    event_actions = []
    if actions:
        event_actions = [
            {
                "type": "TonTransfer",
                "status": "ok",
                "TonTransfer": {
                    "sender": {"address": "EQwallet"},
                    "recipient": {"address": f"EQdest{event_number}"},
                    "amount": "2500000000",
                },
            },
            {
                "type": "JettonSwap",
                "status": "ok",
                "JettonSwap": {
                    "dex": "stonfi",
                    "ton_in": "5000000000",
                    "amount_out": "123450000",
                    "jetton_master_out": {
                        "address": f"EQjetton{event_number}",
                        "symbol": "EJT",
                        "decimals": 6,
                    },
                    "router": {"address": "EQrouter"},
                },
            },
        ]
    return {
        "event_id": f"{event_number:064x}",
        "timestamp": int(timestamp.timestamp()),
        "lt": logical_time,
        "in_progress": in_progress,
        "actions": event_actions,
    }


def _page(
    events: list[dict],
    *,
    request_cursor: str | None,
    limit: int,
) -> ProviderResult:
    logical_times = [event["lt"] for event in events]
    minimum = min(logical_times, key=int) if logical_times else None
    maximum = max(logical_times, key=int) if logical_times else None
    return ProviderResult.success(
        {
            "wallet_address": "EQwallet",
            "requested_limit": limit,
            "request_before_lt": request_cursor,
            "request_start_date": START_SECONDS,
            "request_end_date": END_SECONDS,
            "raw_count": len(events),
            "min_logical_time": minimum,
            "max_logical_time": maximum,
            "next_before_lt": minimum,
            "events": events,
        },
        source="real",
        message="TonAPI account event page fetched.",
    )


def _install_pages(monkeypatch, adapter, responses):
    calls = []
    pending = iter(responses)

    def fake_page(
        account_address,
        limit,
        before_lt=None,
        start_date=None,
        end_date=None,
    ):
        calls.append(
            (account_address, limit, before_lt, start_date, end_date)
        )
        return next(pending)

    monkeypatch.setattr(
        adapter.tonapi,
        "get_account_events_page",
        fake_page,
    )
    return calls


def _stream(result):
    assert len(result.acquisition_streams) == 1
    return result.acquisition_streams[0]


def test_terminal_shared_chain_is_complete_but_derived_surfaces_stay_partial(
    monkeypatch,
):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))
    event = _event(
        "500",
        datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
        1,
    )
    calls = _install_pages(
        monkeypatch,
        adapter,
        [
            _page([event], request_cursor=None, limit=1),
            _page([], request_cursor="500", limit=1),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert calls == [
        ("EQwallet", 1, None, START_SECONDS, END_SECONDS),
        ("EQwallet", 1, "500", START_SECONDS, END_SECONDS),
    ]
    assert result.status == "partial"
    assert result.provider_evidence[0].source_status == "limited"
    assert result.unavailable_surfaces == []
    assert result.incomplete_surfaces == ["transfers", "swaps"]
    assert len(result.transfers) == 1
    assert len(result.swaps) == 1
    assert result.transfers[0].direction == "out"
    assert result.swaps[0].dex == "stonfi"
    assert result.transfers[0].raw["action_index"] == 0
    assert result.transfers[0].raw["action_type"] == "TonTransfer"
    assert result.swaps[0].raw["action_index"] == 1
    assert result.swaps[0].raw["action_type"] == "JettonSwap"
    assert stream.stream_key == "account_events"
    assert stream.contract_version == TONAPI_EVENT_ACQUISITION_CONTRACT
    assert stream.scope_kind == "provider_display_events"
    assert stream.completion_state == "complete"
    assert stream.termination_reason == "provider_terminal"
    assert stream.bounds_verified is True
    assert stream.page_count == 2
    assert stream.raw_count == 1
    assert stream.normalized_count == 1
    assert len(stream.pages[0].response_digest) == 64
    assert any(
        "display" in warning.message.lower() for warning in result.warnings
    )


def test_preview_uses_one_shared_page_and_persists_no_derived_rows(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(
        _settings(page_size=1, page_cap=99)
    )
    calls = _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [
                    _event(
                        "500",
                        datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
                        1,
                    )
                ],
                request_cursor=None,
                limit=1,
            )
        ],
    )

    result = adapter.preview(_request())

    stream = _stream(result)
    assert calls == [
        ("EQwallet", 1, None, START_SECONDS, END_SECONDS)
    ]
    assert result.status == "partial"
    assert result.transfers == []
    assert result.swaps == []
    assert result.incomplete_surfaces == ["transfers", "swaps"]
    assert stream.completion_state == "preview_only"
    assert stream.termination_reason == "preview_page_limit"
    assert stream.page_cap == 1
    assert stream.page_count == 1
    assert stream.bounds_verified is False


def test_page_cap_keeps_one_shared_stream_incomplete(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(
        _settings(page_size=1, page_cap=2)
    )
    calls = _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [
                    _event(
                        "500",
                        datetime(2026, 7, 10, 11, 30, tzinfo=timezone.utc),
                        1,
                    )
                ],
                request_cursor=None,
                limit=1,
            ),
            _page(
                [
                    _event(
                        "400",
                        datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
                        2,
                    )
                ],
                request_cursor="500",
                limit=1,
            ),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert len(calls) == 2
    assert len(result.transfers) == 2
    assert len(result.swaps) == 2
    assert result.incomplete_surfaces == ["transfers", "swaps"]
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "page_cap_reached"
    assert stream.bounds_verified is False
    assert stream.page_count == 2


def test_in_progress_event_prevents_complete_derived_coverage(monkeypatch):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [
                    _event(
                        "500",
                        datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
                        1,
                        in_progress=True,
                    )
                ],
                request_cursor=None,
                limit=1,
            ),
            _page([], request_cursor="500", limit=1),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "partial"
    assert result.transfers == []
    assert result.swaps == []
    assert result.incomplete_surfaces == ["transfers", "swaps"]
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "provider_event_in_progress"
    assert stream.bounds_verified is False
    assert stream.raw_count == 1
    assert stream.normalized_count == 0
    assert stream.pages[0].normalized_count == 0


@pytest.mark.parametrize(
    ("provider_error", "termination_reason", "stored_error"),
    [
        (ERROR_PROVIDER_ERROR, "provider_error", ERROR_PROVIDER_ERROR),
        (ERROR_PROVIDER_PROTOCOL, "protocol_error", "protocol_error"),
    ],
)
def test_error_after_usable_event_page_retains_both_derived_surfaces(
    monkeypatch,
    provider_error,
    termination_reason,
    stored_error,
):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page(
                [
                    _event(
                        "500",
                        datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
                        1,
                    )
                ],
                request_cursor=None,
                limit=1,
            ),
            ProviderResult.failure(
                provider_error,
                "event-secret failed",
                source="real",
            ),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "partial"
    assert result.unavailable_surfaces == []
    assert result.incomplete_surfaces == ["transfers", "swaps"]
    assert len(result.transfers) == 1
    assert len(result.swaps) == 1
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == termination_reason
    assert stream.error_code == stored_error
    assert "event-secret" not in stream.error_message
    assert "[redacted]" in stream.error_message
    assert stream.pages[-1].error_code == stored_error


def test_reused_event_id_with_changed_lt_fails_closed_after_first_page(
    monkeypatch,
):
    adapter = TonapiWalletActivityLiveAdapter(_settings(page_size=1))
    first = _event(
        "500",
        datetime(2026, 7, 10, 11, 0, tzinfo=timezone.utc),
        1,
    )
    changed = _event(
        "400",
        datetime(2026, 7, 10, 10, 30, tzinfo=timezone.utc),
        1,
    )
    _install_pages(
        monkeypatch,
        adapter,
        [
            _page([first], request_cursor=None, limit=1),
            _page([changed], request_cursor="500", limit=1),
        ],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "partial"
    assert result.unavailable_surfaces == []
    assert len(result.transfers) == 1
    assert len(result.swaps) == 1
    assert stream.completion_state == "incomplete"
    assert stream.termination_reason == "protocol_error"
    assert stream.bounds_verified is False
    assert stream.raw_count == 1
    assert stream.normalized_count == 1
    assert stream.duplicate_count == 0
    assert "changed logical time" in (stream.error_message or "")


def test_half_open_bounds_include_start_exclude_end_and_stop_below_start(
    monkeypatch,
):
    adapter = TonapiWalletActivityLiveAdapter(
        _settings(page_size=4, page_cap=1)
    )
    events = [
        _event("600", END, 1),
        _event(
            "500",
            datetime(2026, 7, 10, 11, 59, tzinfo=timezone.utc),
            2,
        ),
        _event("400", START, 3),
        _event(
            "300",
            datetime(2026, 7, 10, 9, 59, tzinfo=timezone.utc),
            4,
        ),
    ]
    _install_pages(
        monkeypatch,
        adapter,
        [_page(events, request_cursor=None, limit=4)],
    )

    result = adapter.ingest(_request())

    stream = _stream(result)
    assert result.status == "partial"
    assert len(result.transfers) == 2
    assert len(result.swaps) == 2
    assert {
        row.counterparty for row in result.transfers
    } == {"EQdest2", "EQdest3"}
    assert stream.completion_state == "complete"
    assert stream.termination_reason == "requested_start_crossed"
    assert stream.bounds_verified is True
    assert stream.raw_count == 4
    assert stream.normalized_count == 2
    assert stream.pages[0].normalized_count == 2
    assert result.incomplete_surfaces == ["transfers", "swaps"]
