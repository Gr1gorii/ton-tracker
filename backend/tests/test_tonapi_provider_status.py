"""Tests for TonAPI in the public providers status endpoint."""

from fastapi.testclient import TestClient

import adapters.tonapi as tonapi_module
from config import DEFAULT_TONAPI_BASE_URL, Settings
from main import app, get_api_providers_status


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
        stonfi_base_url="https://api.ston.fi",
        tonapi_base_url=DEFAULT_TONAPI_BASE_URL,
        tonapi_api_key="",
    )
    base.update(kw)
    return Settings(**base)


def _forbid_tonapi_network(monkeypatch):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("provider status must not probe TonAPI")

    monkeypatch.setattr(tonapi_module.urllib.request, "urlopen", fail_urlopen)


def test_providers_status_endpoint_includes_tonapi(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setenv("TONAPI_BASE_URL", DEFAULT_TONAPI_BASE_URL)
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)

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
    assert set(body["tonapi"]) == {"configured", "available", "message"}


def test_providers_status_mock_mode_tonapi_is_honest(monkeypatch):
    _forbid_tonapi_network(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setenv("TONAPI_BASE_URL", DEFAULT_TONAPI_BASE_URL)

    body = _client().get("/api/providers/status").json()
    status = body["tonapi"]

    assert status["configured"] is True
    assert status["available"] is True
    assert "mock mode" in status["message"].lower()
    assert "not actively queried" in status["message"].lower()


def test_providers_status_real_mode_valid_tonapi_without_api_key(
    monkeypatch,
):
    _forbid_tonapi_network(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", DEFAULT_TONAPI_BASE_URL)
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)

    body = _client().get("/api/providers/status").json()
    status = body["tonapi"]

    assert status["configured"] is True
    assert status["available"] is True
    assert "public TonAPI requests" in status["message"]
    assert "public mode" in status["message"]
    assert "rate limits may apply" in status["message"]
    assert "native TON balance and jetton" in status["message"]
    assert "not full wallet intelligence" in status["message"]


def test_providers_status_real_mode_valid_tonapi_with_api_key(monkeypatch):
    secret = "secret-tonapi-key"
    _forbid_tonapi_network(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", DEFAULT_TONAPI_BASE_URL)
    monkeypatch.setenv("TONAPI_API_KEY", secret)

    body = _client().get("/api/providers/status").json()
    status = body["tonapi"]

    assert status["configured"] is True
    assert status["available"] is True
    assert "TONAPI_API_KEY is configured" in status["message"]
    assert "native TON balance and jetton" in status["message"]
    assert "not full wallet intelligence" in status["message"]
    assert secret not in status["message"]
    assert secret not in str(body)


def test_providers_status_real_mode_invalid_tonapi_base_url(monkeypatch):
    _forbid_tonapi_network(monkeypatch)
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "ftp://tonapi.io")

    body = _client().get("/api/providers/status").json()
    status = body["tonapi"]

    assert status["configured"] is False
    assert status["available"] is False
    assert "provider is not configured" in status["message"].lower()
    assert "missing or invalid" in status["message"].lower()


def test_providers_status_payload_missing_tonapi_base_url_is_unavailable(
    monkeypatch,
):
    _forbid_tonapi_network(monkeypatch)

    status = get_api_providers_status(
        _settings("real", tonapi_base_url="")
    )["tonapi"]

    assert status["configured"] is False
    assert status["available"] is False
    assert "provider is not configured" in status["message"].lower()
