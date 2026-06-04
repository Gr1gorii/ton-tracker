"""Tests for the STON.fi pools preview endpoint."""

from fastapi.testclient import TestClient
import urllib.request

from adapters.stonfi import StonfiAdapter
from config import (
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_NOT_CONFIGURED,
    ProviderResult,
)
from main import app
from routers.stonfi import STONFI_SCOPE_WARNING


def _client() -> TestClient:
    return TestClient(app)


def _pool(address: str = "EQpool") -> dict:
    return {
        "address": address,
        "token0_address": "EQtoken0",
        "token1_address": "EQtoken1",
        "reserve0": "1000",
        "reserve1": "2000",
        "source": "stonfi",
    }


def test_endpoint_exists_and_returns_mock_offline_preview(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not call STON.fi")

    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    response = _client().get("/api/stonfi/pools/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "stonfi"
    assert body["data_mode"] == "mock"
    assert body["source"] == "mock"
    assert body["success"] is True
    assert body["summary"] == {
        "total_pools": 0,
        "preview_count": 0,
        "requested_limit": 10,
    }
    assert body["pools_preview"] == []
    assert body["error"] is None
    assert "Mock/offline mode" in body["warnings"][0]
    assert STONFI_SCOPE_WARNING in body["warnings"]
    assert "not actively queried" in body["message"]


def test_real_mode_success_uses_adapter_result(monkeypatch):
    pools = [_pool("EQpool1"), _pool("EQpool2")]
    calls = {}

    def fake_get_pools_preview(self, limit):
        calls["limit"] = limit
        return ProviderResult.success(
            {
                "pools": pools[:limit],
                "preview_count": limit,
                "total_pools": len(pools),
            },
            source="real",
            message=(
                "STON.fi pool preview fetched. Covers STON.fi DEX pools only, "
                "not all TON DeFi."
            ),
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(StonfiAdapter, "get_pools_preview", fake_get_pools_preview)

    response = _client().get("/api/stonfi/pools/preview?limit=1")

    assert response.status_code == 200
    body = response.json()
    assert calls == {"limit": 1}
    assert body["provider"] == "stonfi"
    assert body["data_mode"] == "real"
    assert body["source"] == "real"
    assert body["success"] is True
    assert body["summary"] == {
        "total_pools": 2,
        "preview_count": 1,
        "requested_limit": 1,
    }
    assert body["pools_preview"] == [_pool("EQpool1")]
    assert body["warnings"] == [STONFI_SCOPE_WARNING]
    assert "not all TON DeFi" in body["message"]
    assert body["error"] is None


def test_provider_error_returns_success_false_with_warning(monkeypatch):
    def fake_get_pools_preview(self, limit):
        return ProviderResult.failure(
            ERROR_PROVIDER_ERROR,
            "STON.fi returned invalid JSON.",
            source="real",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(StonfiAdapter, "get_pools_preview", fake_get_pools_preview)

    response = _client().get("/api/stonfi/pools/preview?limit=5")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["summary"] == {
        "total_pools": 0,
        "preview_count": 0,
        "requested_limit": 5,
    }
    assert body["pools_preview"] == []
    assert body["error"] == {
        "code": ERROR_PROVIDER_ERROR,
        "message": "STON.fi returned invalid JSON.",
    }
    assert body["warnings"] == [
        "STON.fi provider warning: STON.fi returned invalid JSON.",
        STONFI_SCOPE_WARNING,
    ]


def test_missing_config_error_is_safe(monkeypatch):
    def fake_get_pools_preview(self, limit):
        return ProviderResult.failure(
            ERROR_PROVIDER_NOT_CONFIGURED,
            "STON.fi base URL is missing or invalid.",
            source="real",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(StonfiAdapter, "get_pools_preview", fake_get_pools_preview)

    response = _client().get("/api/stonfi/pools/preview")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == ERROR_PROVIDER_NOT_CONFIGURED
    assert "STON.fi base URL" in body["error"]["message"]


def test_invalid_limit_low_returns_422():
    response = _client().get("/api/stonfi/pools/preview?limit=0")

    assert response.status_code == 422


def test_invalid_limit_high_returns_422():
    response = _client().get("/api/stonfi/pools/preview?limit=101")

    assert response.status_code == 422


def test_response_includes_honest_stonfi_scope_warning(monkeypatch):
    def fake_get_pools_preview(self, limit):
        return ProviderResult.success(
            {"pools": [_pool()], "preview_count": 1, "total_pools": 1},
            source="real",
            message="STON.fi pool preview fetched.",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(StonfiAdapter, "get_pools_preview", fake_get_pools_preview)

    response = _client().get("/api/stonfi/pools/preview")

    assert response.status_code == 200
    body = response.json()
    assert STONFI_SCOPE_WARNING in body["warnings"]
    assert "all TON DeFi" not in body["message"]


def test_no_live_network_calls_when_adapter_is_mocked(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("endpoint test must not make live network calls")

    def fake_get_pools_preview(self, limit):
        return ProviderResult.success(
            {"pools": [], "preview_count": 0, "total_pools": 0},
            source="real",
            message="STON.fi pool preview fetched.",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)
    monkeypatch.setattr(StonfiAdapter, "get_pools_preview", fake_get_pools_preview)

    response = _client().get("/api/stonfi/pools/preview")

    assert response.status_code == 200
    assert response.json()["success"] is True
