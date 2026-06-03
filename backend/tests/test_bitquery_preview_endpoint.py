"""Tests for the Bitquery token trades preview endpoint."""

from fastapi.testclient import TestClient
import urllib.request

from adapters.bitquery import BitqueryAdapter
from config import ERROR_PROVIDER_ERROR, ERROR_PROVIDER_NOT_CONFIGURED, ProviderResult
from main import app, get_session


def _client() -> TestClient:
    return TestClient(app)


def _payload(**overrides) -> dict:
    payload = {
        "token_address": "EQtok",
        "start": "2026-01-01T00:00:00Z",
        "end": "2026-01-02T00:00:00Z",
    }
    payload.update(overrides)
    return payload


def _trade(tx_hash: str, side: str = "buy") -> dict:
    return {
        "tx_hash": tx_hash,
        "block_time": "2026-01-01T00:00:00Z",
        "wallet": "EQwallet",
        "side": side,
        "token_amount": "5",
        "usd_amount": "12.50",
        "price_usd": "2.50",
        "pool_address": "EQpool",
        "dex": "stonfi",
        "source": "bitquery",
    }


def test_endpoint_exists_and_returns_200_in_mock_mode(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")

    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "bitquery"
    assert body["data_mode"] == "mock"
    assert body["success"] is True
    assert body["summary"]["total_trades"] > 0


def test_mock_mode_does_not_make_network_calls(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not call Bitquery")

    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_adapter_success_returns_preview_and_total_count(monkeypatch):
    trades = [_trade("tx1"), _trade("tx2", "sell")]

    def fake_get_token_trades(self, token_address, start, end):
        assert token_address == "EQtok"
        assert start == "2026-01-01T00:00:00Z"
        assert end == "2026-01-02T00:00:00Z"
        return ProviderResult.success(trades, source="real")

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(BitqueryAdapter, "get_token_trades", fake_get_token_trades)

    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data_mode"] == "real"
    assert body["success"] is True
    assert body["summary"] == {"total_trades": 2, "preview_count": 2}
    assert body["trades_preview"] == trades
    assert body["warnings"] == []
    assert body["error"] is None


def test_preview_limit_truncates_preview_and_preserves_total_count(monkeypatch):
    trades = [_trade("tx1"), _trade("tx2", "sell"), _trade("tx3")]

    def fake_get_token_trades(self, token_address, start, end):
        return ProviderResult.success(trades, source="real")

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(BitqueryAdapter, "get_token_trades", fake_get_token_trades)

    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=_payload(preview_limit=2),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"] == {"total_trades": 3, "preview_count": 2}
    assert [trade["tx_hash"] for trade in body["trades_preview"]] == [
        "tx1",
        "tx2",
    ]


def test_adapter_error_returns_success_false_with_warning(monkeypatch):
    def fake_get_token_trades(self, token_address, start, end):
        return ProviderResult.failure(
            ERROR_PROVIDER_ERROR,
            "Bitquery normalization error: bad payload.",
            source="real",
        )

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(BitqueryAdapter, "get_token_trades", fake_get_token_trades)

    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["summary"] == {"total_trades": 0, "preview_count": 0}
    assert body["trades_preview"] == []
    assert body["error"] == {
        "code": ERROR_PROVIDER_ERROR,
        "message": "Bitquery normalization error: bad payload.",
    }
    assert "Bitquery provider warning" in body["warnings"][0]


def test_missing_key_error_returns_success_false_without_network(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("missing key must not call Bitquery")

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.delenv("BITQUERY_API_KEY", raising=False)
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == ERROR_PROVIDER_NOT_CONFIGURED


def test_invalid_preview_limit_zero_returns_422():
    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=_payload(preview_limit=0),
    )

    assert response.status_code == 422


def test_invalid_preview_limit_above_max_returns_422():
    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=_payload(preview_limit=101),
    )

    assert response.status_code == 422


def test_missing_token_address_returns_validation_error():
    payload = _payload()
    payload.pop("token_address")

    response = _client().post(
        "/api/bitquery/token-trades/preview",
        json=payload,
    )

    assert response.status_code == 422


def test_api_analyze_still_works(monkeypatch):
    class FakeSession:
        def add(self, value):
            self.value = value

        def commit(self):
            pass

    def fake_session():
        yield FakeSession()

    monkeypatch.setenv("DATA_MODE", "mock")
    app.dependency_overrides[get_session] = fake_session
    try:
        response = _client().post(
            "/api/analyze",
            json={
                "pool_url": "https://www.geckoterminal.com/ton/pools/mock",
                "time_window": "24h",
            },
        )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["total_buyers"] > 0
    assert body["data_quality"]["components"]["wallet_buyers"] == "mock"


def test_imported_preview_endpoint_still_works():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "content": "\n".join(
                [
                    "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                    "tx1,2026-01-01T00:00:00Z,EQwallet,buy,5,10",
                ]
            ),
        },
    )

    assert response.status_code == 200
    assert response.json()["summary"]["valid_rows"] == 1


def test_imported_analyze_endpoint_still_works():
    response = _client().post(
        "/api/import/trades/analyze",
        json={
            "format": "csv",
            "content": "\n".join(
                [
                    "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                    "tx1,2026-01-01T00:00:00Z,EQwallet,buy,5,10",
                ]
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["wallets_count"] == 1
    assert body["wallets"][0]["wallet"] == "EQwallet"
