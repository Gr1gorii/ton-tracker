"""Tests for STON.fi in the public providers status endpoint."""

from fastapi.testclient import TestClient

import adapters.stonfi as stonfi_module
from config import DEFAULT_STONFI_BASE_URL, Settings
from main import app, get_api_providers_status
from services.analysis import get_providers_status


def _client() -> TestClient:
    return TestClient(app)


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


def _forbid_stonfi_network(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("provider status must not probe STON.fi")

    monkeypatch.setattr(stonfi_module.urllib.request, "urlopen", fail_urlopen)


def test_providers_status_endpoint_includes_stonfi(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setenv("STONFI_BASE_URL", DEFAULT_STONFI_BASE_URL)

    response = _client().get("/api/providers/status")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "data_mode",
        "geckoterminal",
        "ton_provider",
        "bitquery",
        "stonfi",
        "tonapi",
        "wallet_activity",
    }
    assert set(body["stonfi"]) == {"configured", "available", "message"}


def test_providers_status_mock_mode_stonfi_is_honest(monkeypatch):
    _forbid_stonfi_network(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setenv("STONFI_BASE_URL", DEFAULT_STONFI_BASE_URL)

    body = _client().get("/api/providers/status").json()
    status = body["stonfi"]

    assert status["configured"] is True
    assert status["available"] is True
    assert "mock mode" in status["message"].lower()
    assert "not actively queried" in status["message"].lower()


def test_providers_status_real_mode_valid_stonfi_base_url(monkeypatch):
    _forbid_stonfi_network(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("STONFI_BASE_URL", DEFAULT_STONFI_BASE_URL)

    body = _client().get("/api/providers/status").json()
    status = body["stonfi"]

    assert status["configured"] is True
    assert status["available"] is True
    assert "STON.fi is configured" in status["message"]
    assert "pool preview endpoints" in status["message"]
    assert "not all TON DeFi" in status["message"]


def test_providers_status_real_mode_invalid_stonfi_base_url(monkeypatch):
    _forbid_stonfi_network(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("STONFI_BASE_URL", "ftp://api.ston.fi")

    body = _client().get("/api/providers/status").json()
    status = body["stonfi"]

    assert status["configured"] is False
    assert status["available"] is False
    assert "provider is not configured" in status["message"].lower()
    assert "missing or invalid" in status["message"].lower()


def test_providers_status_payload_missing_stonfi_base_url_is_unavailable(
    monkeypatch,
):
    _forbid_stonfi_network(monkeypatch)

    status = get_api_providers_status(
        _settings("real", stonfi_base_url="")
    )["stonfi"]

    assert status["configured"] is False
    assert status["available"] is False
    assert "provider is not configured" in status["message"].lower()


def test_analysis_provider_status_payload_is_unchanged():
    status = get_providers_status(_settings("mock"))

    assert "stonfi" not in status
    assert set(status) == {
        "data_mode",
        "geckoterminal",
        "ton_provider",
        "bitquery",
    }
