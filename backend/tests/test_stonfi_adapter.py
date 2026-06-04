"""Tests for the STON.fi provider adapter."""

from __future__ import annotations

import json
import urllib.error

import pytest

import adapters.stonfi as stonfi_module
from adapters.stonfi import StonfiAdapter
from config import (
    DEFAULT_STONFI_BASE_URL,
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
        stonfi_base_url=DEFAULT_STONFI_BASE_URL,
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


def test_config_default_stonfi_base_url_exists(monkeypatch):
    monkeypatch.delenv("STONFI_BASE_URL", raising=False)
    assert get_settings().stonfi_base_url == DEFAULT_STONFI_BASE_URL


def test_status_mock_mode_does_not_probe_network(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("status must not query STON.fi")

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fail_urlopen)

    adapter = StonfiAdapter(_settings("mock"))
    status = adapter.status()

    assert status["configured"] is True
    assert status["available"] is True
    assert "mock mode" in status["message"].lower()
    assert "not actively queried" in status["message"].lower()


def test_status_real_mode_valid_base_url_does_not_probe_network(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("status must not query STON.fi")

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fail_urlopen)

    status = StonfiAdapter(_settings("real")).status()

    assert status["configured"] is True
    assert status["available"] is True
    assert "ston.fi dex" in status["message"].lower()
    assert "not all ton defi" in status["message"].lower()


@pytest.mark.parametrize(
    "base_url",
    ["", "ftp://api.ston.fi", "https:///missing-host"],
)
def test_status_real_mode_invalid_or_missing_base_url(base_url):
    status = StonfiAdapter(
        _settings("real", stonfi_base_url=base_url)
    ).status()

    assert status["configured"] is False
    assert status["available"] is False
    assert "missing or invalid" in status["message"].lower()


def test_get_pools_preview_mock_mode_does_not_probe_network(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not query STON.fi")

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fail_urlopen)

    result = StonfiAdapter(_settings("mock")).get_pools_preview()

    assert result.ok is True
    assert result.source == "mock"
    assert result.data == {"pools": [], "preview_count": 0, "total_pools": 0}
    assert "not actively queried" in (result.message or "").lower()


def test_get_pools_preview_success_normalizes_response(monkeypatch):
    captured = {}
    payload = {
        "pool_list": [
            {
                "address": "EQpool1",
                "token0_address": "EQtoken0",
                "token1_address": "EQtoken1",
                "reserve0": "1000",
                "reserve1": "2000",
                "token0_balance": "1000",
                "token1_balance": "2000",
                "lp_total_supply_usd": "12345.67",
                "volume_24h_usd": "890.12",
                "apy_1d": "0.01",
                "apy_7d": "0.07",
                "apy_30d": "0.3",
                "router_address": "EQrouter",
                "deprecated": False,
                "tags": ["stable", "featured"],
            },
            {"address": "EQpool2"},
        ]
    }

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["method"] = request.get_method()
        captured["timeout"] = timeout
        return _json_response(payload)

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fake_urlopen)

    result = StonfiAdapter(_settings("real")).get_pools_preview(limit=1)

    assert result.ok is True
    assert result.source == "real"
    assert captured == {
        "url": f"{DEFAULT_STONFI_BASE_URL}/v1/pools?dex_v2=true",
        "method": "GET",
        "timeout": 10,
    }
    assert result.data["preview_count"] == 1
    assert result.data["total_pools"] == 2
    pool = result.data["pools"][0]
    assert pool["address"] == "EQpool1"
    assert pool["token0_address"] == "EQtoken0"
    assert pool["token1_address"] == "EQtoken1"
    assert pool["volume_24h_usd"] == "890.12"
    assert pool["tags"] == ["stable", "featured"]
    assert pool["source"] == "stonfi"
    assert "not all TON DeFi" in (result.message or "")


def test_get_pools_preview_http_error_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.HTTPError(
            request.full_url,
            503,
            "Service Unavailable",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fake_urlopen)

    result = StonfiAdapter(_settings("real")).get_pools_preview()

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "HTTP error: 503" in (result.message or "")


def test_get_pools_preview_network_error_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        raise urllib.error.URLError("network unavailable")

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fake_urlopen)

    result = StonfiAdapter(_settings("real")).get_pools_preview()

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "network error" in (result.message or "").lower()


def test_get_pools_preview_invalid_json_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return _FakeResponse(b"{not-json")

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fake_urlopen)

    result = StonfiAdapter(_settings("real")).get_pools_preview()

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "invalid json" in (result.message or "").lower()


def test_get_pools_preview_unexpected_shape_returns_provider_error(monkeypatch):
    def fake_urlopen(request, timeout):
        return _json_response({"unexpected": []})

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fake_urlopen)

    result = StonfiAdapter(_settings("real")).get_pools_preview()

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_ERROR
    assert "unexpected structure" in (result.message or "").lower()


def test_get_pools_preview_missing_base_url_returns_not_configured():
    result = StonfiAdapter(
        _settings("real", stonfi_base_url="")
    ).get_pools_preview()

    assert result.ok is False
    assert result.error == ERROR_PROVIDER_NOT_CONFIGURED
