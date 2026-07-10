"""Tests for the TonAPI provider adapter."""

from __future__ import annotations

import json
import urllib.error
import urllib.request

import pytest

import adapters.tonapi as tonapi_module
from adapters.tonapi import TonapiAdapter
from config import (
    DEFAULT_TONAPI_BASE_URL,
    DEFAULT_TONAPI_TESTNET_BASE_URL,
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_NOT_CONFIGURED,
    ERROR_PROVIDER_PROTOCOL,
    Settings,
    get_settings,
)


def _settings(mode: str = "real", **kw) -> Settings:
    base = dict(
        data_mode=mode,
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        ton_api_base_url="",
        ton_api_key="",
        bitquery_api_url="",
        bitquery_api_key="",
        stonfi_base_url="https://api.ston.fi",
        tonapi_base_url=DEFAULT_TONAPI_BASE_URL,
        tonapi_api_key="",
    )
    base.update(kw)
    return Settings(**base)


class _FakeResponse:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _json_response(payload: dict | list) -> _FakeResponse:
    return _FakeResponse(json.dumps(payload).encode("utf-8"))


def _transaction_page_payload(*logical_times) -> dict:
    return {
        "transactions": [
            {
                "hash": f"{index + 1:064x}",
                "lt": logical_time,
                "utime": 1717236000 - index,
                "total_fees": 4200000,
                "success": True,
                "transaction_type": "TransOrd",
            }
            for index, logical_time in enumerate(logical_times)
        ]
    }


def _forbid_network(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("TonAPI status/mock paths must not query network")

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fail_urlopen)


def test_config_default_tonapi_base_url_exists(monkeypatch):
    monkeypatch.delenv("TONAPI_BASE_URL", raising=False)
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)
    monkeypatch.delenv("TON_NETWORK", raising=False)

    settings = get_settings()

    assert settings.tonapi_base_url == DEFAULT_TONAPI_BASE_URL
    assert settings.tonapi_api_key == ""


def test_config_testnet_uses_official_testnet_base_url(monkeypatch):
    monkeypatch.delenv("TONAPI_BASE_URL", raising=False)
    monkeypatch.setenv("TON_NETWORK", "testnet")

    settings = get_settings()

    assert settings.tonapi_base_url == DEFAULT_TONAPI_TESTNET_BASE_URL


def test_official_tonapi_host_must_match_configured_network(monkeypatch):
    _forbid_network(monkeypatch)

    mismatched = TonapiAdapter(
        _settings(
            "real",
            ton_network="testnet",
            tonapi_base_url=DEFAULT_TONAPI_BASE_URL,
        )
    )
    matched = TonapiAdapter(
        _settings(
            "real",
            ton_network="testnet",
            tonapi_base_url=DEFAULT_TONAPI_TESTNET_BASE_URL,
        )
    )

    assert mismatched.is_configured() is False
    assert matched.is_configured() is True


def test_status_mock_mode_does_not_probe_network(monkeypatch):
    _forbid_network(monkeypatch)

    status = TonapiAdapter(_settings("mock")).status()

    assert status["configured"] is True
    assert status["available"] is True
    assert "mock mode" in status["message"].lower()
    assert "not actively queried" in status["message"].lower()


def test_status_real_mode_valid_base_url_without_api_key(monkeypatch):
    _forbid_network(monkeypatch)

    status = TonapiAdapter(_settings("real")).status()

    assert status["configured"] is True
    assert status["available"] is True
    assert "public TonAPI requests" in status["message"]
    assert "rate limits may apply" in status["message"]
    assert "native TON balance and jetton" in status["message"]
    assert "not full wallet intelligence" in status["message"]


def test_status_real_mode_valid_base_url_with_api_key(monkeypatch):
    _forbid_network(monkeypatch)

    status = TonapiAdapter(
        _settings("real", tonapi_api_key="secret-key")
    ).status()

    assert status["configured"] is True
    assert status["available"] is True
    assert "TONAPI_API_KEY is configured" in status["message"]
    assert "native TON balance and jetton" in status["message"]
    assert "secret-key" not in status["message"]


def test_keyed_tonapi_rejects_plaintext_base_url():
    adapter = TonapiAdapter(
        _settings(
            "real",
            tonapi_base_url="http://tonapi.internal.example",
            tonapi_api_key="secret-key",
        )
    )

    assert adapter.is_configured() is False


def test_authorization_is_not_forwarded_to_redirect_request(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        redirected = urllib.request.HTTPRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://different-origin.example/v2/accounts/EQwallet",
        )
        captured["initial"] = request.get_header("Authorization")
        captured["redirected"] = redirected.get_header("Authorization")
        return _json_response({"balance": "0"})

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(
        _settings("real", tonapi_api_key="redirect-secret")
    ).get_account_balance_preview("EQwallet")

    assert result.ok is True
    assert captured == {
        "initial": "Bearer redirect-secret",
        "redirected": None,
    }


@pytest.mark.parametrize(
    "base_url",
    ["", "ftp://tonapi.io", "https:///missing-host"],
)
def test_status_real_mode_invalid_base_url(base_url):
    status = TonapiAdapter(
        _settings("real", tonapi_base_url=base_url)
    ).status()

    assert status["configured"] is False
    assert status["available"] is False
    assert "not configured" in status["message"].lower()
    assert "missing or invalid" in status["message"].lower()


def test_get_account_jettons_preview_mock_mode_does_not_probe_network(monkeypatch):
    _forbid_network(monkeypatch)

    result = TonapiAdapter(_settings("mock")).get_account_jettons_preview(
        "EQwallet",
    )

    assert result.ok is True
    assert result.source == "mock"
    assert result.data == {
        "wallet_address": "EQwallet",
        "jettons": [],
        "preview_count": 0,
        "total_jettons": 0,
    }
    assert "not actively queried" in (result.message or "").lower()


def test_get_account_balance_preview_success_normalizes_response(monkeypatch):
    captured = {}
    payload = {
        "balance": "2500000000",
        "status": "active",
        "is_scam": False,
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        captured["authorization"] = request.get_header("Authorization")
        return _json_response(payload)

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(
        _settings("real", tonapi_api_key="test-key")
    ).get_account_balance_preview("EQwallet")

    assert result.ok is True
    assert result.source == "real"
    assert captured == {
        "url": f"{DEFAULT_TONAPI_BASE_URL}/v2/accounts/EQwallet",
        "method": "GET",
        "timeout": 10,
        "authorization": "Bearer test-key",
    }
    assert result.data["wallet_address"] == "EQwallet"
    assert result.data["balance"] == {
        "wallet_address": "EQwallet",
        "asset": "TON",
        "balance": "2500000000",
        "decimals": 9,
        "account_status": "active",
        "is_scam": False,
        "source": "tonapi",
    }
    assert "native TON balance" in (result.message or "")


def test_get_account_jettons_preview_success_normalizes_response(monkeypatch):
    captured = {}
    payload = {
        "balances": [
            {
                "balance": "1234500000",
                "price": "0.12",
                "wallet_address": "EQjettonWallet",
                "jetton": {
                    "address": "EQjetton",
                    "name": "Example Jetton",
                    "symbol": "EJT",
                    "decimals": 9,
                    "image": "https://example.test/jetton.png",
                },
            },
            {
                "balance": "5",
                "jetton": {
                    "address": "EQsecond",
                    "symbol": "SECOND",
                    "decimals": "6",
                },
            },
        ]
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        captured["authorization"] = request.get_header("Authorization")
        return _json_response(payload)

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(
        _settings("real", tonapi_api_key="test-key")
    ).get_account_jettons_preview("EQwallet", limit=1)

    assert result.ok is True
    assert result.source == "real"
    assert captured == {
        "url": f"{DEFAULT_TONAPI_BASE_URL}/v2/accounts/EQwallet/jettons",
        "method": "GET",
        "timeout": 10,
        "authorization": "Bearer test-key",
    }
    assert result.data["wallet_address"] == "EQwallet"
    assert result.data["preview_count"] == 1
    assert result.data["total_jettons"] == 2
    jetton = result.data["jettons"][0]
    assert jetton == {
        "wallet_address": "EQwallet",
        "jetton_address": "EQjetton",
        "jetton_name": "Example Jetton",
        "jetton_symbol": "EJT",
        "balance": "1234500000",
        "decimals": 9,
        "image": "https://example.test/jetton.png",
        "price_usd": "0.12",
        "wallet_contract_address": "EQjettonWallet",
        "source": "tonapi",
    }
    assert "dashboard wallet intelligence" in (result.message or "")


def test_fetch_json_public_mode_omits_authorization_header(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["authorization"] = request.get_header("Authorization")
        return _json_response({"balances": []})

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_jettons_preview(
        "EQwallet",
    )

    assert result.ok is True
    assert captured["authorization"] is None


def test_get_account_jettons_preview_http_error_returns_provider_error(
    monkeypatch,
):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "Too Many Requests",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_jettons_preview(
        "EQwallet",
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "HTTP error: 429" in (result.message or "")


def test_get_account_jettons_preview_network_error_redacts_api_key(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("network failed for secret-key")

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(
        _settings("real", tonapi_api_key="secret-key")
    ).get_account_jettons_preview("EQwallet")

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "network error" in (result.message or "").lower()
    assert "secret-key" not in (result.message or "")
    assert "[redacted]" in (result.message or "")
    assert "secret-key" not in str(result.to_dict())


def test_get_account_jettons_preview_invalid_json_returns_provider_error(
    monkeypatch,
):
    def fake_urlopen(request, timeout):
        return _FakeResponse(b"{not-json")

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_jettons_preview(
        "EQwallet",
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "invalid json" in (result.message or "").lower()


def test_get_account_jettons_preview_unexpected_shape_returns_provider_error(
    monkeypatch,
):
    def fake_urlopen(request, timeout):
        return _json_response({"unexpected": []})

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_jettons_preview(
        "EQwallet",
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "unexpected structure" in (result.message or "").lower()


def test_get_account_jettons_preview_missing_base_url_returns_not_configured():
    result = TonapiAdapter(
        _settings("real", tonapi_base_url="")
    ).get_account_jettons_preview("EQwallet")

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_NOT_CONFIGURED


def test_get_account_jettons_preview_rejects_missing_account_address():
    result = TonapiAdapter(_settings("real")).get_account_jettons_preview("")

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "account address is required" in (result.message or "").lower()


def test_get_account_transactions_preview_mock_mode_does_not_probe_network(
    monkeypatch,
):
    _forbid_network(monkeypatch)

    result = TonapiAdapter(_settings("mock")).get_account_transactions_preview(
        "EQwallet",
    )

    assert result.ok is True
    assert result.source == "mock"
    assert result.data == {
        "wallet_address": "EQwallet",
        "transactions": [],
        "preview_count": 0,
        "total_transactions": 0,
    }
    assert "not actively queried" in (result.message or "").lower()


def test_get_account_transactions_page_first_and_next_cursor_urls(monkeypatch):
    captured_urls = []
    payloads = iter(
        (
            _transaction_page_payload("300", "200"),
            _transaction_page_payload("150", "100"),
        )
    )

    def fake_urlopen(request, timeout):
        captured_urls.append(request.full_url)
        return _json_response(next(payloads))

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)
    adapter = TonapiAdapter(_settings("real", tonapi_api_key="test-key"))

    first = adapter.get_account_transactions_page("EQwallet", limit=2)
    second = adapter.get_account_transactions_page(
        "EQwallet",
        limit=2,
        before_lt=first.data["next_before_lt"],
    )

    assert first.ok is True
    assert second.ok is True
    assert captured_urls == [
        (
            f"{DEFAULT_TONAPI_BASE_URL}/v2/blockchain/accounts/EQwallet"
            "/transactions?limit=2"
        ),
        (
            f"{DEFAULT_TONAPI_BASE_URL}/v2/blockchain/accounts/EQwallet"
            "/transactions?limit=2&before_lt=200"
        ),
    ]
    assert first.data == {
        "wallet_address": "EQwallet",
        "requested_limit": 2,
        "request_before_lt": None,
        "raw_count": 2,
        "min_logical_time": "200",
        "max_logical_time": "300",
        "next_before_lt": "200",
        "transactions": [
            {
                "wallet_address": "EQwallet",
                "tx_hash": f"{1:064x}",
                "logical_time": "300",
                "utime": 1717236000,
                "total_fees": "4200000",
                "success": True,
                "transaction_type": "TransOrd",
                "orig_status": None,
                "end_status": None,
                "source": "tonapi",
            },
            {
                "wallet_address": "EQwallet",
                "tx_hash": f"{2:064x}",
                "logical_time": "200",
                "utime": 1717235999,
                "total_fees": "4200000",
                "success": True,
                "transaction_type": "TransOrd",
                "orig_status": None,
                "end_status": None,
                "source": "tonapi",
            },
        ],
    }
    assert second.data["request_before_lt"] == "200"
    assert second.data["min_logical_time"] == "100"
    assert second.data["max_logical_time"] == "150"
    assert second.data["next_before_lt"] == "100"


def test_get_account_transactions_page_empty_page_terminates_cursor(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return _json_response({"transactions": []})

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet",
        limit=25,
        before_lt="100",
    )

    assert result.ok is True
    assert captured["url"].endswith(
        "/transactions?limit=25&before_lt=100"
    )
    assert result.data == {
        "wallet_address": "EQwallet",
        "requested_limit": 25,
        "request_before_lt": "100",
        "raw_count": 0,
        "min_logical_time": None,
        "max_logical_time": None,
        "next_before_lt": None,
        "transactions": [],
    }


@pytest.mark.parametrize("limit", [0, 1001, True, "10"])
def test_get_account_transactions_page_rejects_invalid_limit(monkeypatch, limit):
    _forbid_network(monkeypatch)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet",
        limit=limit,
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "between 1 and 1000" in (result.message or "")


@pytest.mark.parametrize(
    "before_lt",
    [0, -1, True, "01", " 1", str(2**64), 2**64],
)
def test_get_account_transactions_page_rejects_invalid_cursor(
    monkeypatch,
    before_lt,
):
    _forbid_network(monkeypatch)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet",
        before_lt=before_lt,
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "before_lt" in (result.message or "")


@pytest.mark.parametrize(
    "logical_time",
    [None, 0, "01", " 1", str(2**64)],
)
def test_get_account_transactions_page_rejects_missing_or_invalid_lt(
    monkeypatch,
    logical_time,
):
    def fake_urlopen(request, timeout):
        payload = _transaction_page_payload(logical_time)
        if logical_time is None:
            payload["transactions"][0].pop("lt")
        return _json_response(payload)

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(
        _settings("real", tonapi_api_key="provider-secret")
    ).get_account_transactions_page("EQwallet")

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "logical time" in (result.message or "").lower()
    assert "provider-secret" not in (result.message or "")


@pytest.mark.parametrize(
    "tx_hash",
    [True, {}, [], "short", "ab" * 31, f" {'ab' * 32}"],
)
def test_get_account_transactions_page_rejects_noncanonical_hash(
    monkeypatch,
    tx_hash,
):
    def fake_urlopen(request, timeout):
        payload = _transaction_page_payload("100")
        payload["transactions"][0]["hash"] = tx_hash
        return _json_response(payload)

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet"
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "canonical 32-byte hash" in (result.message or "")


@pytest.mark.parametrize(
    "total_fees",
    [True, 1.5, "Infinity", "NaN", "01", "-1", str(2**64)],
)
def test_get_account_transactions_page_rejects_invalid_total_fees(
    monkeypatch,
    total_fees,
):
    def fake_urlopen(request, timeout):
        payload = _transaction_page_payload("100")
        payload["transactions"][0]["total_fees"] = total_fees
        return _json_response(payload)

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet"
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "total_fees" in (result.message or "")


def test_get_account_transactions_page_rejects_oversized_response(monkeypatch):
    def fake_urlopen(request, timeout):
        return _json_response(_transaction_page_payload("200", "100"))

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet",
        limit=1,
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "more rows than requested" in (result.message or "")


def test_get_account_transactions_page_rejects_non_descending_lt(monkeypatch):
    def fake_urlopen(request, timeout):
        return _json_response(_transaction_page_payload("100", "200"))

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet"
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "strictly descending" in (result.message or "").lower()


def test_get_account_transactions_page_rejects_stalled_cursor(monkeypatch):
    def fake_urlopen(request, timeout):
        return _json_response(_transaction_page_payload("100", "90"))

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet",
        before_lt="100",
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "did not advance" in (result.message or "").lower()


def test_get_account_transactions_page_accepts_max_limit(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return _json_response({"transactions": []})

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_transactions_page(
        "EQwallet",
        limit=1000,
    )

    assert result.ok is True
    assert result.data["requested_limit"] == 1000
    assert captured["url"].endswith("/transactions?limit=1000")


def test_get_account_transactions_preview_success_normalizes_response(monkeypatch):
    captured = {}
    payload = {
        "transactions": [
            {
                "hash": "ab" * 32,
                "lt": 46000000000001,
                "utime": 1717236000,
                "total_fees": 4200000,
                "success": True,
                "transaction_type": "TransOrd",
                "orig_status": "active",
                "end_status": "active",
            },
            {
                "hash": "de" * 32,
                "lt": 46000000000000,
                "utime": 1717235000,
                "total_fees": 0,
                "success": False,
            },
        ]
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return _json_response(payload)

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(
        _settings("real", tonapi_api_key="test-key")
    ).get_account_transactions_preview("EQwallet", limit=2)

    assert result.ok is True
    assert result.source == "real"
    assert captured["url"] == (
        f"{DEFAULT_TONAPI_BASE_URL}/v2/blockchain/accounts/EQwallet"
        "/transactions?limit=2"
    )
    assert result.data["wallet_address"] == "EQwallet"
    assert result.data["preview_count"] == 2
    assert result.data["total_transactions"] == 2
    tx = result.data["transactions"][0]
    assert tx == {
        "wallet_address": "EQwallet",
        "tx_hash": "ab" * 32,
        "logical_time": "46000000000001",
        "utime": 1717236000,
        "total_fees": "4200000",
        "success": True,
        "transaction_type": "TransOrd",
        "orig_status": "active",
        "end_status": "active",
        "source": "tonapi",
    }
    assert "transaction history" in (result.message or "").lower()


def test_get_account_transactions_preview_unexpected_shape_returns_error(
    monkeypatch,
):
    def fake_urlopen(request, timeout):
        return _json_response({"unexpected": []})

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_transactions_preview(
        "EQwallet",
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "unexpected structure" in (result.message or "").lower()


def test_get_account_transactions_preview_rejects_missing_account_address():
    result = TonapiAdapter(_settings("real")).get_account_transactions_preview("")

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "account address is required" in (result.message or "").lower()


def test_get_account_events_preview_mock_mode_does_not_probe_network(monkeypatch):
    _forbid_network(monkeypatch)

    result = TonapiAdapter(_settings("mock")).get_account_events_preview(
        "EQwallet",
    )

    assert result.ok is True
    assert result.source == "mock"
    assert result.data == {
        "wallet_address": "EQwallet",
        "transfers": [],
        "preview_count": 0,
        "total_transfers": 0,
        "total_events": 0,
    }
    assert "not actively queried" in (result.message or "").lower()


def test_get_account_events_preview_normalizes_ton_and_jetton_transfers(monkeypatch):
    captured = {}
    payload = {
        "events": [
            {
                "event_id": "e1" * 32,
                "timestamp": 1717236000,
                "lt": "46000000000001",
                "in_progress": False,
                "actions": [
                    {
                        "type": "TonTransfer",
                        "status": "ok",
                        "TonTransfer": {
                            "sender": {"address": "EQwallet"},
                            "recipient": {"address": "EQdest"},
                            "amount": 2500000000,
                        },
                    },
                    {
                        "type": "JettonTransfer",
                        "status": "ok",
                        "JettonTransfer": {
                            "sender": {"address": "EQsource"},
                            "recipient": {"address": "EQwallet"},
                            "amount": "123450000",
                            "jetton": {
                                "address": "EQjetton",
                                "symbol": "EJT",
                                "decimals": 6,
                            },
                        },
                    },
                    {"type": "ContractDeploy", "status": "ok"},
                ],
            }
        ],
        "next_from": 46000000000001,
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return _json_response(payload)

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(
        _settings("real", tonapi_api_key="test-key")
    ).get_account_events_preview("EQwallet", limit=2)

    assert result.ok is True
    assert result.source == "real"
    assert captured["url"] == (
        f"{DEFAULT_TONAPI_BASE_URL}/v2/accounts/EQwallet/events"
        "?limit=2&sort_order=desc"
    )
    assert result.data["total_events"] == 1
    assert result.data["total_transfers"] == 2
    transfers = result.data["transfers"]
    assert transfers[0]["action_type"] == "TonTransfer"
    assert transfers[0]["asset"] == "TON"
    assert transfers[0]["direction"] == "out"
    assert transfers[0]["counterparty"] == "EQdest"
    assert transfers[0]["raw_amount"] == "2500000000"
    assert transfers[0]["decimals"] == 9
    assert transfers[1]["action_type"] == "JettonTransfer"
    assert transfers[1]["asset"] == "EJT"
    assert transfers[1]["direction"] == "in"
    assert transfers[1]["counterparty"] == "EQsource"
    assert transfers[1]["raw_amount"] == "123450000"
    assert transfers[1]["decimals"] == 6
    assert "transfer history" in (result.message or "").lower()


def test_get_account_events_preview_unexpected_shape_returns_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return _json_response({"unexpected": []})

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(_settings("real")).get_account_events_preview(
        "EQwallet",
    )

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_PROTOCOL
    assert "unexpected structure" in (result.message or "").lower()


def test_get_account_swaps_preview_mock_mode_does_not_probe_network(monkeypatch):
    _forbid_network(monkeypatch)

    result = TonapiAdapter(_settings("mock")).get_account_swaps_preview(
        "EQwallet",
    )

    assert result.ok is True
    assert result.source == "mock"
    assert result.data == {
        "wallet_address": "EQwallet",
        "swaps": [],
        "preview_count": 0,
        "total_swaps": 0,
        "total_events": 0,
    }


def test_get_account_swaps_preview_normalizes_jetton_swap(monkeypatch):
    captured = {}
    payload = {
        "events": [
            {
                "event_id": "e2" * 32,
                "timestamp": 1717236000,
                "lt": "46000000000002",
                "in_progress": False,
                "actions": [
                    {
                        "type": "JettonSwap",
                        "status": "ok",
                        "JettonSwap": {
                            "dex": "stonfi",
                            "ton_in": 5000000000,
                            "amount_out": "123450000",
                            "jetton_master_out": {
                                "address": "EQjetton",
                                "symbol": "EJT",
                                "decimals": 6,
                            },
                            "router": {"address": "EQrouter"},
                        },
                    },
                    {
                        "type": "TonTransfer",
                        "status": "ok",
                        "TonTransfer": {
                            "sender": {"address": "EQwallet"},
                            "recipient": {"address": "EQdest"},
                            "amount": 1,
                        },
                    },
                ],
            }
        ],
        "next_from": 46000000000002,
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        return _json_response(payload)

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fake_urlopen)

    result = TonapiAdapter(
        _settings("real", tonapi_api_key="test-key")
    ).get_account_swaps_preview("EQwallet", limit=3)

    assert result.ok is True
    assert result.source == "real"
    assert captured["url"] == (
        f"{DEFAULT_TONAPI_BASE_URL}/v2/accounts/EQwallet/events"
        "?limit=3&sort_order=desc"
    )
    assert result.data["total_events"] == 1
    assert result.data["total_swaps"] == 1
    swap = result.data["swaps"][0]
    assert swap["dex"] == "stonfi"
    assert swap["token_in"] == "TON"
    assert swap["token_in_address"] is None  # native TON has no master
    assert swap["raw_amount_in"] == "5000000000"
    assert swap["decimals_in"] == 9
    assert swap["token_out"] == "EJT"
    assert swap["token_out_address"] == "EQjetton"
    assert swap["raw_amount_out"] == "123450000"
    assert swap["decimals_out"] == 6
    assert swap["router"] == "EQrouter"
    assert "dex swaps" in (result.message or "").lower()
