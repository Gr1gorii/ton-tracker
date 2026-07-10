"""Strict page-contract tests for display-oriented TonAPI account events."""

from __future__ import annotations

import json

import pytest

import adapters.tonapi as tonapi_module
from adapters.tonapi import TonapiAdapter
from config import (
    DEFAULT_TONAPI_BASE_URL,
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_PROTOCOL,
    Settings,
)


def _settings(mode: str = "real") -> Settings:
    return Settings(
        data_mode=mode,
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        ton_api_base_url="",
        ton_api_key="",
        bitquery_api_url="",
        bitquery_api_key="",
        tonapi_base_url=DEFAULT_TONAPI_BASE_URL,
        tonapi_api_key="event-page-secret",
        wallet_activity_provider="tonapi",
        wallet_activity_live_enabled=True,
    )


class _Response:
    def __init__(self, payload) -> None:
        self.body = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None

    def read(self):
        return self.body


def _event(lt: int, timestamp: int, suffix: int = 1, *, in_progress=False):
    return {
        "event_id": f"{suffix:064x}",
        "timestamp": timestamp,
        "lt": lt,
        "in_progress": in_progress,
        "actions": [{"type": "TonTransfer", "TonTransfer": {}}],
    }


def _install(monkeypatch, payloads):
    urls = []
    pending = iter(payloads)

    def fake_urlopen(request, timeout):
        urls.append(request.full_url)
        return _Response(next(pending))

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)
    return urls


def test_first_and_next_event_pages_preserve_strict_cursor(monkeypatch):
    urls = _install(
        monkeypatch,
        [
            {
                "events": [
                    _event(500, 1783380000, 1),
                    _event(400, 1783370000, 2),
                ],
                "next_from": 400,
            },
            {
                "events": [_event(300, 1783360000, 3)],
                "next_from": 300,
            },
        ],
    )
    adapter = TonapiAdapter(_settings())

    first = adapter.get_account_events_page("EQwallet", limit=2)
    second = adapter.get_account_events_page(
        "EQwallet",
        limit=2,
        before_lt=first.data["next_before_lt"],
        start_date=1783300000,
        end_date=1783400000,
    )

    assert first.ok is True
    assert second.ok is True
    assert urls == [
        f"{DEFAULT_TONAPI_BASE_URL}/v2/accounts/EQwallet/events"
        "?limit=2&sort_order=desc",
        f"{DEFAULT_TONAPI_BASE_URL}/v2/accounts/EQwallet/events"
        "?limit=2&before_lt=400&start_date=1783300000"
        "&end_date=1783400000&sort_order=desc",
    ]
    assert first.data["min_logical_time"] == "400"
    assert first.data["max_logical_time"] == "500"
    assert first.data["next_before_lt"] == "400"
    assert [event["lt"] for event in first.data["events"]] == ["500", "400"]
    assert second.data["request_before_lt"] == "400"


def test_empty_event_page_normalizes_zero_next_from_to_terminal(monkeypatch):
    _install(monkeypatch, [{"events": [], "next_from": 0}])

    result = TonapiAdapter(_settings()).get_account_events_page("EQwallet")

    assert result.ok is True
    assert result.data["raw_count"] == 0
    assert result.data["next_before_lt"] is None


@pytest.mark.parametrize("next_from", [False, 0.0])
def test_empty_event_page_rejects_lossy_zero_cursor(monkeypatch, next_from):
    _install(monkeypatch, [{"events": [], "next_from": next_from}])

    result = TonapiAdapter(_settings()).get_account_events_page("EQwallet")

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL


def test_event_page_rejects_reused_event_id_at_different_lt(monkeypatch):
    _install(
        monkeypatch,
        [
            {
                "events": [
                    _event(500, 1783380000, 1),
                    _event(400, 1783370000, 1),
                ],
                "next_from": 400,
            }
        ],
    )

    result = TonapiAdapter(_settings()).get_account_events_page(
        "EQwallet",
        limit=2,
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "reuses an event_id" in (result.message or "")


def test_mock_event_page_is_offline_and_deterministic(monkeypatch):
    monkeypatch.setattr(
        tonapi_module.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("mock mode must not query network")
        ),
    )

    result = TonapiAdapter(_settings("mock")).get_account_events_page(
        "EQwallet",
        before_lt="500",
        start_date=1,
        end_date=2,
    )

    assert result.ok is True
    assert result.source == "mock"
    assert result.data["events"] == []
    assert result.data["request_before_lt"] == "500"


@pytest.mark.parametrize("limit", [0, 101, True, "20"])
def test_event_page_rejects_invalid_limit(monkeypatch, limit):
    result = TonapiAdapter(_settings()).get_account_events_page(
        "EQwallet",
        limit=limit,
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR


@pytest.mark.parametrize("cursor", [0, -1, True, "01", str(2**64)])
def test_event_page_rejects_invalid_cursor(monkeypatch, cursor):
    result = TonapiAdapter(_settings()).get_account_events_page(
        "EQwallet",
        before_lt=cursor,
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR


@pytest.mark.parametrize(
    "start,end",
    [(True, 2), (-1, 2), (1, 2114380801), (3, 2), (1.5, 2)],
)
def test_event_page_rejects_invalid_dates(monkeypatch, start, end):
    result = TonapiAdapter(_settings()).get_account_events_page(
        "EQwallet",
        start_date=start,
        end_date=end,
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR


@pytest.mark.parametrize(
    "mutation",
    [
        lambda payload: payload["events"][0].update(event_id=True),
        lambda payload: payload["events"][0].update(lt="01"),
        lambda payload: payload["events"][0].update(timestamp=1.5),
        lambda payload: payload["events"][0].update(actions={}),
        lambda payload: payload["events"][0].update(in_progress="false"),
        lambda payload: payload.update(next_from=499),
    ],
)
def test_event_page_rejects_malformed_provider_fields(monkeypatch, mutation):
    payload = {"events": [_event(500, 1783380000)], "next_from": 500}
    mutation(payload)
    _install(monkeypatch, [payload])

    result = TonapiAdapter(_settings()).get_account_events_page("EQwallet")

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "event-page-secret" not in (result.message or "")


@pytest.mark.parametrize(
    "events,next_from,message",
    [
        ([_event(400, 1), _event(500, 0, 2)], 500, "strictly descending"),
        ([_event(500, 1), _event(400, 2, 2)], 400, "timestamps"),
        ([_event(500, 1), _event(400, 0, 2)], 400, "more rows"),
    ],
)
def test_event_page_rejects_order_or_size_violation(
    monkeypatch,
    events,
    next_from,
    message,
):
    _install(monkeypatch, [{"events": events, "next_from": next_from}])

    result = TonapiAdapter(_settings()).get_account_events_page(
        "EQwallet",
        limit=1 if message == "more rows" else 2,
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert message in (result.message or "")
