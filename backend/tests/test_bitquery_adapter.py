"""Tests for the Bitquery adapter query builder."""

from datetime import datetime, timezone
import http.client
import socket

import pytest

from adapters.bitquery import BitqueryAdapter
from config import ERROR_NOT_IMPLEMENTED, Settings


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
