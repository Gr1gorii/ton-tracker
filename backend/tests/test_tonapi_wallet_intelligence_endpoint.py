"""Tests for the TonAPI wallet intelligence preview endpoint."""

from fastapi.testclient import TestClient
import urllib.request

from adapters.tonapi import TonapiAdapter
from config import ERROR_PROVIDER_ERROR, ProviderResult
from main import app
from routers.tonapi import (
    TONAPI_PUBLIC_MODE_WARNING,
    TONAPI_WALLET_INTELLIGENCE_LIMIT_WARNING,
    TONAPI_WALLET_INTELLIGENCE_SCOPE_WARNING,
)


def _client() -> TestClient:
    return TestClient(app)


def _jetton(
    address: str = "EQjetton",
    symbol: str = "EJT",
    name: str = "Example Jetton",
    balance: str = "1234500000",
    decimals: int = 9,
    price_usd: str | None = None,
) -> dict:
    item = {
        "wallet_address": "EQwallet",
        "jetton_address": address,
        "jetton_name": name,
        "jetton_symbol": symbol,
        "balance": balance,
        "decimals": decimals,
        "image": "https://example.test/jetton.png",
        "wallet_contract_address": f"{address}Wallet",
        "source": "tonapi",
    }
    if price_usd is not None:
        item["price_usd"] = price_usd
    return item


def test_wallet_intelligence_mock_mode_success(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not call TonAPI")

    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    response = _client().get(
        "/api/tonapi/wallet-intelligence/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "tonapi"
    assert body["data_mode"] == "mock"
    assert body["source"] == "mock"
    assert body["success"] is True
    assert body["account_address"] == "EQwallet"
    assert body["summary"] == {
        "total_jettons": 0,
        "preview_count": 0,
        "requested_limit": 10,
        "non_zero_balance_count": 0,
        "jettons_with_price_count": 0,
        "stablecoin_like_count": 0,
    }
    assert body["intelligence"]["scope"] == "account_jettons_preview_only"
    assert body["intelligence"]["data_sources"] == ["tonapi"]
    assert body["intelligence"]["top_jettons_by_display_balance"] == []
    assert body["jettons_preview"] == []
    assert "Mock/offline mode" in body["warnings"][0]
    assert TONAPI_WALLET_INTELLIGENCE_SCOPE_WARNING in body["warnings"]
    assert TONAPI_WALLET_INTELLIGENCE_LIMIT_WARNING in body["warnings"]
    assert body["error"] is None


def test_wallet_intelligence_real_mode_success_uses_adapter_result(
    monkeypatch,
):
    jettons = [
        _jetton(
            "EQusdt",
            symbol="USDT",
            name="Tether USD",
            balance="1500000",
            decimals=6,
            price_usd="1.00",
        ),
        _jetton(
            "EQexample",
            symbol="EJT",
            name="Example Jetton",
            balance="0",
            decimals=9,
        ),
    ]
    calls = {}

    def fake_get_account_jettons_preview(self, account_address, limit):
        calls["account_address"] = account_address
        calls["limit"] = limit
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "jettons": jettons,
                "preview_count": len(jettons),
                "total_jettons": 4,
            },
            source="real",
            message="TonAPI account jettons preview fetched.",
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
        "/api/tonapi/wallet-intelligence/preview"
        "?account_address=EQwallet&limit=2"
    )

    assert response.status_code == 200
    body = response.json()
    assert calls == {"account_address": "EQwallet", "limit": 2}
    assert body["data_mode"] == "real"
    assert body["source"] == "real"
    assert body["success"] is True
    assert body["summary"]["total_jettons"] == 4
    assert body["summary"]["preview_count"] == 2
    assert body["summary"]["requested_limit"] == 2
    assert body["summary"]["non_zero_balance_count"] == 1
    assert body["summary"]["jettons_with_price_count"] == 1
    assert body["summary"]["stablecoin_like_count"] == 1
    assert body["intelligence"]["non_zero_balance_count"] == 1
    assert body["intelligence"]["jettons_with_price_count"] == 1
    assert body["intelligence"]["stablecoin_like_count"] == 1
    assert body["intelligence"]["top_jettons_by_display_balance"][0][
        "jetton_symbol"
    ] == "USDT"
    assert body["intelligence"]["top_jettons_by_display_balance"][0][
        "display_balance"
    ] == "1.5"
    assert body["jettons_preview"] == jettons
    assert TONAPI_WALLET_INTELLIGENCE_SCOPE_WARNING in body["warnings"]
    assert TONAPI_WALLET_INTELLIGENCE_LIMIT_WARNING in body["warnings"]
    assert TONAPI_PUBLIC_MODE_WARNING in body["warnings"]
    assert "not full wallet intelligence" in body["message"]


def test_wallet_intelligence_provider_error_is_safe(monkeypatch):
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
        "/api/tonapi/wallet-intelligence/preview"
        "?account_address=EQwallet&limit=5"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["summary"] == {
        "total_jettons": 0,
        "preview_count": 0,
        "requested_limit": 5,
        "non_zero_balance_count": 0,
        "jettons_with_price_count": 0,
        "stablecoin_like_count": 0,
    }
    assert body["jettons_preview"] == []
    assert body["error"] == {
        "code": ERROR_PROVIDER_ERROR,
        "message": "TonAPI returned invalid JSON.",
    }
    assert body["warnings"] == [
        "TonAPI provider warning: TonAPI returned invalid JSON.",
        TONAPI_WALLET_INTELLIGENCE_SCOPE_WARNING,
        TONAPI_WALLET_INTELLIGENCE_LIMIT_WARNING,
        TONAPI_PUBLIC_MODE_WARNING,
    ]
    assert "no wallet intelligence preview signals were derived" in body[
        "intelligence"
    ]["basic_notes"][0]


def test_wallet_intelligence_missing_account_address_returns_422():
    response = _client().get("/api/tonapi/wallet-intelligence/preview")

    assert response.status_code == 422


def test_wallet_intelligence_empty_account_address_returns_422():
    response = _client().get(
        "/api/tonapi/wallet-intelligence/preview?account_address=%20%20"
    )

    assert response.status_code == 422


def test_wallet_intelligence_invalid_limit_low_returns_422():
    response = _client().get(
        "/api/tonapi/wallet-intelligence/preview"
        "?account_address=EQwallet&limit=0"
    )

    assert response.status_code == 422


def test_wallet_intelligence_invalid_limit_high_returns_422():
    response = _client().get(
        "/api/tonapi/wallet-intelligence/preview"
        "?account_address=EQwallet&limit=101"
    )

    assert response.status_code == 422


def test_empty_jettons_response_is_not_false_empty_wallet_claim(monkeypatch):
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
    monkeypatch.setenv("TONAPI_API_KEY", "configured-test-key")
    monkeypatch.setattr(
        TonapiAdapter,
        "get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )

    response = _client().get(
        "/api/tonapi/wallet-intelligence/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    body = response.json()
    notes = " ".join(body["intelligence"]["basic_notes"])
    assert "not evidence that the wallet is empty" in notes
    assert body["success"] is True
    assert body["summary"]["total_jettons"] == 0


def test_stablecoin_like_heuristic_counts_usdt_and_usdc(monkeypatch):
    jettons = [
        _jetton("EQusdt", symbol="USDT", name="Tether", balance="1000000"),
        _jetton("EQusdc", symbol="jUSDC", name="USD Coin", balance="2500000"),
        _jetton("EQton", symbol="TONX", name="Example", balance="3000000"),
    ]

    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "jettons": jettons,
                "preview_count": len(jettons),
                "total_jettons": len(jettons),
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
        "/api/tonapi/wallet-intelligence/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["stablecoin_like_count"] == 2
    assert body["intelligence"]["stablecoin_like_count"] == 2
    assert any(
        "Stablecoin-like labels are simple symbol/name heuristics only."
        == note
        for note in body["intelligence"]["basic_notes"]
    )


def test_wallet_intelligence_no_live_network_calls_when_adapter_is_mocked(
    monkeypatch,
):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("endpoint test must not make live network calls")

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
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)
    monkeypatch.setattr(
        TonapiAdapter,
        "get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )

    response = _client().get(
        "/api/tonapi/wallet-intelligence/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_wallet_intelligence_api_key_is_not_exposed(monkeypatch):
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
        "/api/tonapi/wallet-intelligence/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert secret not in str(body)


def test_wallet_intelligence_warnings_include_explicit_limitations(
    monkeypatch,
):
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
        "/api/tonapi/wallet-intelligence/preview?account_address=EQwallet"
    )

    assert response.status_code == 200
    body = response.json()
    assert TONAPI_WALLET_INTELLIGENCE_SCOPE_WARNING in body["warnings"]
    assert TONAPI_WALLET_INTELLIGENCE_LIMIT_WARNING in body["warnings"]
    limitation = " ".join(body["warnings"])
    assert "not full wallet intelligence" in limitation
    assert "transaction history" in limitation
    assert "PnL" in limitation
    assert "DEX swaps" in limitation
    assert "current TON balance" in limitation
    assert "full wallet analysis" not in str(body)
    assert "full wallet history" not in str(body)
