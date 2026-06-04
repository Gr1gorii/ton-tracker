"""Tests for the TonAPI account jettons preview endpoint."""

from fastapi.testclient import TestClient
import urllib.request

from adapters.tonapi import TonapiAdapter
from config import ERROR_PROVIDER_ERROR, ProviderResult
from main import app
from routers.tonapi import TONAPI_PUBLIC_MODE_WARNING, TONAPI_SCOPE_WARNING


def _client() -> TestClient:
    return TestClient(app)


def _jetton(address: str = "EQjetton") -> dict:
    return {
        "wallet_address": "EQwallet",
        "jetton_address": address,
        "jetton_name": "Example Jetton",
        "jetton_symbol": "EJT",
        "balance": "1234500000",
        "decimals": 9,
        "image": "https://example.test/jetton.png",
        "source": "tonapi",
    }


def test_endpoint_exists_and_returns_mock_offline_preview(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not call TonAPI")

    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    response = _client().get(
        "/api/tonapi/account-jettons/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "tonapi"
    assert body["data_mode"] == "mock"
    assert body["source"] == "mock"
    assert body["success"] is True
    assert body["summary"] == {
        "total_jettons": 0,
        "preview_count": 0,
        "requested_limit": 10,
    }
    assert body["account_address"] == "EQwallet"
    assert body["jettons_preview"] == []
    assert body["error"] is None
    assert "Mock/offline mode" in body["warnings"][0]
    assert TONAPI_SCOPE_WARNING in body["warnings"]
    assert "not actively queried" in body["message"]


def test_real_mode_success_uses_adapter_result_and_public_warning(monkeypatch):
    jettons = [_jetton("EQjetton1"), _jetton("EQjetton2")]
    calls = {}

    def fake_get_account_jettons_preview(self, account_address, limit):
        calls["account_address"] = account_address
        calls["limit"] = limit
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "jettons": jettons[:limit],
                "preview_count": limit,
                "total_jettons": len(jettons),
            },
            source="real",
            message=(
                "TonAPI account jettons preview fetched. This is "
                "account-level TON/jetton data only and is not connected to "
                "dashboard wallet intelligence yet."
            ),
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)
    monkeypatch.setattr(
        TonapiAdapter,
        "get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )

    response = _client().get(
        "/api/tonapi/account-jettons/preview"
        "?account_address=EQwallet&limit=1"
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == {"account_address": "EQwallet", "limit": 1}
    assert body["provider"] == "tonapi"
    assert body["data_mode"] == "real"
    assert body["source"] == "real"
    assert body["success"] is True
    assert body["summary"] == {
        "total_jettons": 2,
        "preview_count": 1,
        "requested_limit": 1,
    }
    assert body["account_address"] == "EQwallet"
    assert body["jettons_preview"] == [_jetton("EQjetton1")]
    assert TONAPI_SCOPE_WARNING in body["warnings"]
    assert TONAPI_PUBLIC_MODE_WARNING in body["warnings"]
    assert "wallet intelligence" in body["message"]
    assert body["error"] is None


def test_provider_error_returns_success_false_with_safe_error(monkeypatch):
    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.failure(
            ERROR_PROVIDER_ERROR,
            "TonAPI returned invalid JSON.",
            source="real",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)
    monkeypatch.setattr(
        TonapiAdapter,
        "get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )

    response = _client().get(
        "/api/tonapi/account-jettons/preview"
        "?account_address=EQwallet&limit=5"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["summary"] == {
        "total_jettons": 0,
        "preview_count": 0,
        "requested_limit": 5,
    }
    assert body["account_address"] == "EQwallet"
    assert body["jettons_preview"] == []
    assert body["error"] == {
        "code": ERROR_PROVIDER_ERROR,
        "message": "TonAPI returned invalid JSON.",
    }
    assert body["warnings"] == [
        "TonAPI provider warning: TonAPI returned invalid JSON.",
        TONAPI_SCOPE_WARNING,
        TONAPI_PUBLIC_MODE_WARNING,
    ]


def test_missing_account_address_returns_422():
    response = _client().get("/api/tonapi/account-jettons/preview")

    assert response.status_code == 422


def test_empty_account_address_returns_422():
    response = _client().get(
        "/api/tonapi/account-jettons/preview?account_address=%20%20"
    )

    assert response.status_code == 422


def test_invalid_limit_low_returns_422():
    response = _client().get(
        "/api/tonapi/account-jettons/preview"
        "?account_address=EQwallet&limit=0"
    )

    assert response.status_code == 422


def test_invalid_limit_high_returns_422():
    response = _client().get(
        "/api/tonapi/account-jettons/preview"
        "?account_address=EQwallet&limit=101"
    )

    assert response.status_code == 422


def test_response_includes_honest_tonapi_scope_warning(monkeypatch):
    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "jettons": [_jetton()],
                "preview_count": 1,
                "total_jettons": 1,
            },
            source="real",
            message="TonAPI account jettons preview fetched.",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setenv("TONAPI_API_KEY", "configured-test-key")
    monkeypatch.setattr(
        TonapiAdapter,
        "get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )

    response = _client().get(
        "/api/tonapi/account-jettons/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    body = response.json()
    assert TONAPI_SCOPE_WARNING in body["warnings"]
    assert TONAPI_PUBLIC_MODE_WARNING not in body["warnings"]
    assert "full wallet intelligence" not in body["message"]


def test_no_live_network_calls_when_adapter_is_mocked(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("endpoint test must not make live network calls")

    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "jettons": [],
                "preview_count": 0,
                "total_jettons": 0,
            },
            source="real",
            message="TonAPI account jettons preview fetched.",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)
    monkeypatch.setattr(
        TonapiAdapter,
        "get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )

    response = _client().get(
        "/api/tonapi/account-jettons/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_api_key_is_not_exposed_in_endpoint_response(monkeypatch):
    secret = "secret-tonapi-key"

    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.failure(
            ERROR_PROVIDER_ERROR,
            "TonAPI network error: [redacted]",
            source="real",
            diagnostic="[redacted]",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.setenv("TONAPI_API_KEY", secret)
    monkeypatch.setattr(
        TonapiAdapter,
        "get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )

    response = _client().get(
        "/api/tonapi/account-jettons/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert secret not in str(body)
