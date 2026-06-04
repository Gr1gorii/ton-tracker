"""Tests for the TonAPI provider adapter."""

from __future__ import annotations

import json
import urllib.error

import pytest

import adapters.tonapi as tonapi_module
from adapters.tonapi import TonapiAdapter
from config import (
    DEFAULT_TONAPI_BASE_URL,
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_NOT_CONFIGURED,
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


def _forbid_network(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("TonAPI status/mock paths must not query network")

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fail_urlopen)


def test_config_default_tonapi_base_url_exists(monkeypatch):
    monkeypatch.delenv("TONAPI_BASE_URL", raising=False)
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)

    settings = get_settings()

    assert settings.tonapi_base_url == DEFAULT_TONAPI_BASE_URL
    assert settings.tonapi_api_key == ""


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
    assert "not connected to dashboard wallet intelligence yet" in status[
        "message"
    ]


def test_status_real_mode_valid_base_url_with_api_key(monkeypatch):
    _forbid_network(monkeypatch)

    status = TonapiAdapter(
        _settings("real", tonapi_api_key="secret-key")
    ).status()

    assert status["configured"] is True
    assert status["available"] is True
    assert "TONAPI_API_KEY is configured" in status["message"]
    assert "secret-key" not in status["message"]


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
