"""Tests for the Bitquery adapter query builder."""

from datetime import datetime, timezone
import http.client
import json
import socket
import urllib.error
import urllib.request

import pytest

from adapters.bitquery import BitqueryAdapter
from config import (
    ERROR_NOT_IMPLEMENTED,
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_NOT_CONFIGURED,
    Settings,
)


def _settings(mode: str = "mock", **overrides) -> Settings:
    base = dict(
        data_mode=mode,
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        ton_api_base_url="",
        ton_api_key="",
        bitquery_api_url="",
        bitquery_api_key="",
    )
    base.update(overrides)
    return Settings(**base)


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self.body


def _real_settings(**overrides) -> Settings:
    base = dict(
        bitquery_api_url="https://streaming.bitquery.io/graphql",
        bitquery_api_key="test-key",
    )
    base.update(overrides)
    return _settings("real", **base)


def test_build_token_trades_query_returns_query_and_variables():
    adapter = BitqueryAdapter(_settings())

    payload = adapter.build_token_trades_query(
        "EQtok",
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )

    assert set(payload) == {"query", "variables"}
    assert payload["variables"] == {
        "token": "EQtok",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-01-02T00:00:00Z",
    }


def test_build_token_trades_query_formats_datetime_variables():
    adapter = BitqueryAdapter(_settings())
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = datetime(2026, 1, 2, tzinfo=timezone.utc)

    payload = adapter.build_token_trades_query("EQtok", start, end)

    assert payload["variables"]["start"] == start.isoformat()
    assert payload["variables"]["end"] == end.isoformat()


def test_build_token_trades_query_includes_future_trade_fields():
    adapter = BitqueryAdapter(_settings())

    query = adapter.build_token_trades_query(
        "EQtok",
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )["query"]

    for text in (
        "dexTrades",
        "buyCurrency",
        "sellCurrency",
        "transaction",
        "hash",
        "block",
        "timestamp",
        "time",
        "buyer",
        "seller",
        "address",
        "buyAmount",
        "sellAmount",
        "tradeAmount(in: USD)",
        "protocol",
        "pool",
    ):
        assert text in query


def test_build_token_trades_query_filters_buy_or_sell_token():
    adapter = BitqueryAdapter(_settings())

    query = adapter.build_token_trades_query(
        "EQtok",
        "2026-01-01T00:00:00Z",
        "2026-01-02T00:00:00Z",
    )["query"]

    assert "{buyCurrency: {address: {is: $token}}}" in query
    assert "{sellCurrency: {address: {is: $token}}}" in query


@pytest.mark.parametrize("token_address", ["", "   ", None])
def test_build_token_trades_query_empty_token_fails_cleanly(token_address):
    adapter = BitqueryAdapter(_settings())

    with pytest.raises(ValueError, match="token_address is required"):
        adapter.build_token_trades_query(
            token_address,
            "2026-01-01T00:00:00Z",
            "2026-01-02T00:00:00Z",
        )


def test_build_token_trades_query_missing_start_fails_cleanly():
    adapter = BitqueryAdapter(_settings())

    with pytest.raises(ValueError, match="start is required"):
        adapter.build_token_trades_query(
            "EQtok",
            None,
            "2026-01-02T00:00:00Z",
        )


def test_build_token_trades_query_missing_end_fails_cleanly():
    adapter = BitqueryAdapter(_settings())

    with pytest.raises(ValueError, match="end is required"):
        adapter.build_token_trades_query(
            "EQtok",
            "2026-01-01T00:00:00Z",
            None,
        )


def test_status_behavior_remains_unchanged():
    mock_status = BitqueryAdapter(_settings("mock")).status()
    assert mock_status == {
        "configured": False,
        "available": True,
        "message": "Mock mode: synthesizing mock DEX trades.",
    }

    real_missing_key_status = BitqueryAdapter(_settings("real")).status()
    assert real_missing_key_status == {
        "configured": False,
        "available": False,
        "message": (
            "Bitquery API key is missing. Historical DEX trades are "
            "unavailable."
        ),
    }

    real_configured_status = BitqueryAdapter(
        _settings("real", bitquery_api_key="test-key")
    ).status()
    assert real_configured_status == {
        "configured": True,
        "available": False,
        "message": (
            "Real mode: Bitquery key present, but real trade fetching is "
            "not implemented in v0.2."
        ),
    }


def test_real_configured_trade_fetch_does_not_make_network_calls(monkeypatch):
    def forbidden_network_call(*args, **kwargs):
        raise AssertionError("network calls are not allowed in Bitquery tests")

    monkeypatch.setattr(socket, "create_connection", forbidden_network_call)
    monkeypatch.setattr(
        http.client.HTTPConnection,
        "connect",
        forbidden_network_call,
    )

    adapter = BitqueryAdapter(
        _settings(
            "real",
            bitquery_api_url="https://streaming.bitquery.io/graphql",
            bitquery_api_key="test-key",
        )
    )
    now = datetime.now(timezone.utc)

    payload = adapter.build_token_trades_query("EQtok", now, now)
    result = adapter.get_token_trades("EQtok", now, now)

    assert payload["variables"]["token"] == "EQtok"
    assert result.ok is False
    assert result.error == ERROR_NOT_IMPLEMENTED


def test_execute_graphql_mock_mode_does_not_make_network_call(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not call Bitquery")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    adapter = BitqueryAdapter(_settings("mock"))
    result = adapter.execute_graphql("query Mock", {"token": "EQtok"})

    assert result.ok is True
    assert result.source == "mock"
    assert result.data == {
        "query": "query Mock",
        "variables": {"token": "EQtok"},
    }


def test_execute_graphql_real_missing_key_does_not_make_network_call(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("missing key must not call Bitquery")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    adapter = BitqueryAdapter(
        _settings(
            "real",
            bitquery_api_url="https://streaming.bitquery.io/graphql",
            bitquery_api_key="",
        )
    )
    result = adapter.execute_graphql("query Real", {"token": "EQtok"})

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_NOT_CONFIGURED


def test_execute_graphql_real_builds_request_body_and_headers(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["request"] = request
        captured["timeout"] = timeout
        return FakeResponse('{"data": {"trades": []}}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    result = adapter.execute_graphql("query Real", {"token": "EQtok"})

    request = captured["request"]
    headers = {k.lower(): v for k, v in request.header_items()}
    assert result.ok is True
    assert result.data == {"trades": []}
    assert request.full_url == "https://streaming.bitquery.io/graphql"
    assert request.get_method() == "POST"
    assert captured["timeout"] == 20
    assert json.loads(request.data.decode("utf-8")) == {
        "query": "query Real",
        "variables": {"token": "EQtok"},
    }
    assert headers["authorization"] == "Bearer test-key"
    assert headers["content-type"] == "application/json"


def test_execute_graphql_uses_configured_bitquery_api_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return FakeResponse('{"data": {"ok": true}}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(
        _real_settings(bitquery_api_url="https://example.test/graphql")
    )
    result = adapter.execute_graphql("query Real", {})

    assert result.ok is True
    assert captured["url"] == "https://example.test/graphql"


@pytest.mark.parametrize("api_url", ["", "not-a-url", "ftp://example.test/graphql"])
def test_execute_graphql_invalid_api_url_returns_provider_error(monkeypatch,
                                                               api_url):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("invalid API URL must not call Bitquery")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    adapter = BitqueryAdapter(_real_settings(bitquery_api_url=api_url))
    result = adapter.execute_graphql("query Real", {})

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "url" in (result.message or "").lower()


def test_execute_graphql_http_error_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            url=request.full_url,
            code=429,
            msg="Too Many Requests",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    result = adapter.execute_graphql("query Real", {})

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "http error" in (result.message or "").lower()
    assert "429" in (result.message or "")


def test_execute_graphql_network_error_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    result = adapter.execute_graphql("query Real", {})

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "network error" in (result.message or "").lower()


def test_execute_graphql_invalid_json_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse("not json")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    result = adapter.execute_graphql("query Real", {})

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "invalid json" in (result.message or "").lower()


def test_execute_graphql_graphql_errors_return_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse('{"errors": [{"message": "bad query"}]}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    result = adapter.execute_graphql("query Real", {})

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "graphql error" in (result.message or "").lower()


def test_execute_graphql_missing_data_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse('{"extensions": {}}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    result = adapter.execute_graphql("query Real", {})

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "missing data" in (result.message or "").lower()


def test_execute_graphql_successful_json_returns_data_payload(monkeypatch):
    def fake_urlopen(request, timeout):
        return FakeResponse('{"data": {"ton": {"dexTrades": [{"id": "t1"}]}}}')

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    result = adapter.execute_graphql("query Real", {})

    assert result.ok is True
    assert result.source == "real"
    assert result.data == {"ton": {"dexTrades": [{"id": "t1"}]}}
