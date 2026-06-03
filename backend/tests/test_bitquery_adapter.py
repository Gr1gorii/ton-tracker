"""Tests for the Bitquery adapter query builder."""

from datetime import datetime, timezone
import json
import urllib.error
import urllib.request

import pytest

from adapters.bitquery import BitqueryAdapter
from config import (
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_NOT_CONFIGURED,
    ProviderResult,
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


def _raw_trade(**overrides) -> dict:
    base = {
        "transaction": {"hash": "tx1"},
        "block": {"timestamp": {"time": "2026-01-01T00:00:00Z"}},
        "buyer": {"address": "EQbuyer"},
        "seller": {"address": "EQseller"},
        "buyCurrency": {"address": "EQtok"},
        "sellCurrency": {"address": "EQton"},
        "buyAmount": "5",
        "sellAmount": "2",
        "tradeAmount": "12.50",
        "protocol": "stonfi",
        "pool": {"address": "EQpool"},
    }
    base.update(overrides)
    return base


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


def test_status_behavior_by_mode(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("provider status must not probe Bitquery")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

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

    real_missing_url_status = BitqueryAdapter(
        _settings("real", bitquery_api_key="test-key")
    ).status()
    assert real_missing_url_status == {
        "configured": False,
        "available": False,
        "message": (
            "Bitquery API URL is missing or invalid. Historical DEX trades "
            "are unavailable."
        ),
    }

    real_configured_status = BitqueryAdapter(
        _settings(
            "real",
            bitquery_api_url="https://streaming.bitquery.io/graphql",
            bitquery_api_key="test-key",
        )
    ).status()
    assert real_configured_status == {
        "configured": True,
        "available": True,
        "message": (
            "Real mode: Bitquery is configured. Token trade preview/analyze "
            "endpoints can attempt live DEX trade fetching. Live availability "
            "is checked when those endpoints are called."
        ),
    }


def test_get_token_trades_mock_mode_does_not_make_network_call(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not call Bitquery")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    adapter = BitqueryAdapter(_settings("mock"))
    now = datetime.now(timezone.utc)
    result = adapter.get_token_trades("EQtok", now, now)

    assert result.ok is True
    assert result.source == "mock"
    assert len(result.data) > 0
    assert "wallet_address" in result.data[0]


def test_get_token_trades_real_missing_key_does_not_make_network_call(monkeypatch):
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
    now = datetime.now(timezone.utc)
    result = adapter.get_token_trades("EQtok", now, now)

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_NOT_CONFIGURED


def test_get_token_trades_real_calls_build_execute_normalize(monkeypatch):
    adapter = BitqueryAdapter(_real_settings())
    now = datetime.now(timezone.utc)
    calls = {}
    normalized = [
        {
            "tx_hash": "tx1",
            "block_time": "2026-01-01T00:00:00Z",
            "wallet": "EQbuyer",
            "side": "buy",
            "token_amount": "5",
            "usd_amount": "12.50",
            "price_usd": "2.50",
            "pool_address": "EQpool",
            "dex": "stonfi",
            "source": "bitquery",
        }
    ]

    def fake_build(token_address, start, end):
        calls["build"] = (token_address, start, end)
        return {
            "query": "query Built",
            "variables": {"token": token_address, "start": "s", "end": "e"},
        }

    def fake_execute(query, variables):
        calls["execute"] = (query, variables)
        return ProviderResult.success({"payload": True}, source="real")

    def fake_normalize(payload, target_token_address):
        calls["normalize"] = (payload, target_token_address)
        return normalized

    monkeypatch.setattr(adapter, "build_token_trades_query", fake_build)
    monkeypatch.setattr(adapter, "execute_graphql", fake_execute)
    monkeypatch.setattr(adapter, "normalize_token_trades_response", fake_normalize)

    result = adapter.get_token_trades("EQtok", now, now)

    assert result.ok is True
    assert result.source == "real"
    assert result.data == normalized
    assert calls["build"] == ("EQtok", now, now)
    assert calls["execute"] == (
        "query Built",
        {"token": "EQtok", "start": "s", "end": "e"},
    )
    assert calls["normalize"] == ({"payload": True}, "EQtok")


def test_get_token_trades_real_success_returns_normalized_buy_and_sell(monkeypatch):
    def fake_urlopen(request, timeout):
        payload = {
            "data": {
                "ton": {
                    "dexTrades": [
                        _raw_trade(transaction={"hash": "tx-buy"}),
                        _raw_trade(
                            transaction={"hash": "tx-sell"},
                            buyCurrency={"address": "EQton"},
                            sellCurrency={"address": "EQtok"},
                            buyAmount="3",
                            sellAmount="6",
                            tradeAmount="9",
                        ),
                    ]
                }
            }
        }
        return FakeResponse(json.dumps(payload))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    now = datetime.now(timezone.utc)
    result = adapter.get_token_trades("EQtok", now, now)

    assert result.ok is True
    assert result.source == "real"
    assert result.message == "Bitquery DEX trades fetched and normalized."
    assert result.data[0]["tx_hash"] == "tx-buy"
    assert result.data[0]["side"] == "buy"
    assert result.data[0]["source"] == "bitquery"
    assert result.data[1]["tx_hash"] == "tx-sell"
    assert result.data[1]["side"] == "sell"
    assert result.data[1]["token_amount"] == "6"


def test_get_token_trades_execute_graphql_error_is_propagated(monkeypatch):
    adapter = BitqueryAdapter(_real_settings())
    now = datetime.now(timezone.utc)
    error = ProviderResult.failure(
        ERROR_PROVIDER_ERROR,
        "Bitquery network error: timeout.",
        source="real",
    )

    def fake_execute(query, variables):
        return error

    def forbidden_normalize(*args, **kwargs):
        raise AssertionError("failed GraphQL result must not be normalized")

    monkeypatch.setattr(adapter, "execute_graphql", fake_execute)
    monkeypatch.setattr(
        adapter,
        "normalize_token_trades_response",
        forbidden_normalize,
    )

    result = adapter.get_token_trades("EQtok", now, now)

    assert result is error


def test_get_token_trades_malformed_payload_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        payload = {"data": {"ton": {"dexTrades": {"bad": "shape"}}}}
        return FakeResponse(json.dumps(payload))

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    now = datetime.now(timezone.utc)
    result = adapter.get_token_trades("EQtok", now, now)

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "normalization error" in (result.message or "").lower()


def test_normalize_trade_buy_side_for_target_token():
    adapter = BitqueryAdapter(_settings())

    trade = adapter.normalize_trade(_raw_trade(), "EQtok")

    assert trade == {
        "tx_hash": "tx1",
        "block_time": "2026-01-01T00:00:00Z",
        "wallet": "EQbuyer",
        "side": "buy",
        "token_amount": "5",
        "usd_amount": "12.50",
        "price_usd": "2.50",
        "pool_address": "EQpool",
        "dex": "stonfi",
        "source": "bitquery",
    }


def test_normalize_trade_sell_side_for_target_token():
    adapter = BitqueryAdapter(_settings())
    raw = _raw_trade(
        buyCurrency={"address": "EQton"},
        sellCurrency={"address": "EQtok"},
        buyAmount="2",
        sellAmount="4",
        tradeAmount="10",
    )

    trade = adapter.normalize_trade(raw, "EQtok")

    assert trade["side"] == "sell"
    assert trade["wallet"] == "EQseller"
    assert trade["token_amount"] == "4"
    assert trade["usd_amount"] == "10"
    assert trade["price_usd"] == "2.5"


def test_normalize_trade_uses_direct_price_when_available():
    adapter = BitqueryAdapter(_settings())

    trade = adapter.normalize_trade(_raw_trade(price_usd="3.125"), "EQtok")

    assert trade["price_usd"] == "3.125"


def test_normalize_trade_missing_required_field_fails_cleanly():
    adapter = BitqueryAdapter(_settings())
    raw = _raw_trade()
    raw.pop("transaction")

    with pytest.raises(ValueError, match="transaction hash"):
        adapter.normalize_trade(raw, "EQtok")


def test_normalize_trade_target_not_in_buy_or_sell_side_fails_cleanly():
    adapter = BitqueryAdapter(_settings())

    with pytest.raises(ValueError, match="Target token is not present"):
        adapter.normalize_trade(_raw_trade(), "EQother")


def test_normalize_token_trades_response_returns_multiple_trades():
    adapter = BitqueryAdapter(_settings())
    payload = {
        "ton": {
            "dexTrades": [
                _raw_trade(transaction={"hash": "tx1"}),
                _raw_trade(
                    transaction={"hash": "tx2"},
                    buyCurrency={"address": "EQton"},
                    sellCurrency={"address": "EQtok"},
                    buyAmount="3",
                    sellAmount="6",
                    tradeAmount="9",
                ),
            ]
        }
    }

    trades = adapter.normalize_token_trades_response(payload, "EQtok")

    assert len(trades) == 2
    assert trades[0]["tx_hash"] == "tx1"
    assert trades[0]["side"] == "buy"
    assert trades[1]["tx_hash"] == "tx2"
    assert trades[1]["side"] == "sell"


@pytest.mark.parametrize("payload", [None, {}, {"ton": {"dexTrades": []}}])
def test_normalize_token_trades_response_empty_payload_returns_empty_list(payload):
    adapter = BitqueryAdapter(_settings())

    assert adapter.normalize_token_trades_response(payload, "EQtok") == []


def test_normalize_token_trades_response_invalid_trade_fails_cleanly():
    adapter = BitqueryAdapter(_settings())
    payload = {"ton": {"dexTrades": [_raw_trade(transaction={})]}}

    with pytest.raises(ValueError, match="Invalid Bitquery trade at index 0"):
        adapter.normalize_token_trades_response(payload, "EQtok")


def test_normalize_trade_does_not_make_network_calls(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("normalization must not call Bitquery")

    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    adapter = BitqueryAdapter(_real_settings())
    trade = adapter.normalize_trade(_raw_trade(), "EQtok")

    assert trade["source"] == "bitquery"


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
