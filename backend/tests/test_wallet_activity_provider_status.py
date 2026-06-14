"""Tests for wallet activity adapter status controls."""

from fastapi.testclient import TestClient

from main import app, get_api_providers_status


def _client() -> TestClient:
    return TestClient(app)


def test_providers_status_includes_wallet_activity_default(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.delenv("WALLET_ACTIVITY_PROVIDER", raising=False)

    response = _client().get("/api/providers/status")

    assert response.status_code == 200
    body = response.json()
    assert "wallet_activity" in body
    assert body["wallet_activity"]["configured"] is True
    assert body["wallet_activity"]["available"] is True
    assert "deterministic mock adapter" in body["wallet_activity"]["message"]


def test_providers_status_real_mode_mock_provider_stays_data_honest(
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "mock")

    body = _client().get("/api/providers/status").json()
    status = body["wallet_activity"]

    assert status["configured"] is True
    assert status["available"] is True
    assert "pinned to the deterministic mock adapter" in status["message"]
    assert "No real wallet provider calls" in status["message"]


def test_providers_status_real_mode_tonapi_scaffold_is_limited(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    body = _client().get("/api/providers/status").json()
    status = body["wallet_activity"]

    assert status["configured"] is True
    assert status["available"] is False
    assert "TonAPI wallet activity scaffold" in status["message"]
    assert "live wallet activity calls are disabled" in status["message"]


def test_providers_status_real_mode_tonapi_live_guard(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    body = _client().get("/api/providers/status").json()
    status = body["wallet_activity"]

    assert status["configured"] is True
    assert status["available"] is True
    assert "guarded live TonAPI" in status["message"]
    assert "jetton balance snapshots" in status["message"]
    assert "transfers" in status["message"]


def test_providers_status_real_mode_bitquery_scaffold_missing_key(
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "bitquery")
    monkeypatch.delenv("BITQUERY_API_KEY", raising=False)

    body = _client().get("/api/providers/status").json()
    status = body["wallet_activity"]

    assert status["configured"] is False
    assert status["available"] is False
    assert "BITQUERY_API_KEY is missing or invalid" in status["message"]


def test_get_api_providers_status_reports_wallet_activity_without_network(
    monkeypatch,
):
    def fail_urlopen(*args, **kwargs):
        raise AssertionError("provider status must not probe wallet activity")

    monkeypatch.setattr("adapters.tonapi.urllib.request.urlopen", fail_urlopen)
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")

    status = get_api_providers_status()["wallet_activity"]

    assert status["configured"] is True
    assert status["available"] is False
    assert "scaffold" in status["message"]
