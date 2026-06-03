"""Tests for the Bitquery token trades analysis endpoint."""

from fastapi.testclient import TestClient
import urllib.request

from adapters.bitquery import BitqueryAdapter
from config import ERROR_PROVIDER_ERROR, ProviderResult
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


def _trade(
    tx_hash: str,
    wallet: str,
    side: str,
    token_amount: str,
    usd_amount: str,
    block_time: str = "2026-01-01T00:00:00Z",
) -> dict:
    return {
        "tx_hash": tx_hash,
        "block_time": block_time,
        "wallet": wallet,
        "side": side,
        "token_amount": token_amount,
        "usd_amount": usd_amount,
        "price_usd": str(float(usd_amount) / float(token_amount)),
        "pool_address": "EQpool",
        "dex": "stonfi",
        "source": "bitquery",
    }


def _wallet(body: dict, wallet: str) -> dict:
    return next(row for row in body["wallets"] if row["wallet"] == wallet)


def test_endpoint_exists_and_returns_200_in_mock_mode(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")

    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "bitquery"
    assert body["data_mode"] == "mock"
    assert body["success"] is True
    assert body["summary"]["valid_rows"] > 0
    assert body["analysis_note"].startswith("Bitquery token trade analysis")


def test_mock_mode_does_not_make_network_calls(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not call Bitquery")

    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=_payload(),
    )

    assert response.status_code == 200
    assert response.json()["success"] is True


def test_adapter_success_returns_wallet_analysis(monkeypatch):
    trades = [
        _trade("tx1", "EQholder", "buy", "10", "100"),
        _trade("tx2", "EQholder", "buy", "5", "75"),
    ]

    def fake_get_token_trades(self, token_address, start, end):
        assert token_address == "EQtok"
        assert start == "2026-01-01T00:00:00Z"
        assert end == "2026-01-02T00:00:00Z"
        return ProviderResult.success(trades, source="real")

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(BitqueryAdapter, "get_token_trades", fake_get_token_trades)

    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["summary"]["total_trades"] == 2
    assert body["summary"]["valid_rows"] == 2
    assert body["summary"]["wallets_count"] == 1
    assert body["summary"]["buy_trades_count"] == 2
    assert body["summary"]["sell_trades_count"] == 0
    wallet = body["wallets"][0]
    assert wallet["wallet"] == "EQholder"
    assert wallet["status"] == "holder"
    assert wallet["total_bought_qty"] == "15"
    assert wallet["total_bought_usd"] == "175"


def test_wallet_statuses_work_for_bitquery_trades(monkeypatch):
    trades = [
        _trade("tx1", "EQholder", "buy", "10", "100"),
        _trade("tx2", "EQpartial", "buy", "10", "100"),
        _trade("tx3", "EQpartial", "sell", "4", "60"),
        _trade("tx4", "EQseller", "sell", "5", "50"),
    ]

    def fake_get_token_trades(self, token_address, start, end):
        return ProviderResult.success(trades, source="real")

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(BitqueryAdapter, "get_token_trades", fake_get_token_trades)

    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=_payload(preview_limit=10),
    )

    assert response.status_code == 200
    body = response.json()
    assert _wallet(body, "EQholder")["status"] == "holder"
    assert _wallet(body, "EQpartial")["status"] == "partial_seller"
    assert _wallet(body, "EQseller")["status"] == "seller_only"


def test_realized_pnl_approximation_works(monkeypatch):
    trades = [
        _trade("tx1", "EQpnl", "buy", "10", "100"),
        _trade("tx2", "EQpnl", "sell", "4", "60"),
    ]

    def fake_get_token_trades(self, token_address, start, end):
        return ProviderResult.success(trades, source="real")

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(BitqueryAdapter, "get_token_trades", fake_get_token_trades)

    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=_payload(),
    )

    wallet = response.json()["wallets"][0]
    assert wallet["realized_pnl_usd"] == "20"
    assert wallet["realized_pnl_pct"] == "50"


def test_preview_limit_truncates_wallets_and_trades_preview(monkeypatch):
    trades = [
        _trade("tx1", "EQa", "buy", "1", "300"),
        _trade("tx2", "EQb", "buy", "1", "200"),
        _trade("tx3", "EQc", "buy", "1", "100"),
    ]

    def fake_get_token_trades(self, token_address, start, end):
        return ProviderResult.success(trades, source="real")

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(BitqueryAdapter, "get_token_trades", fake_get_token_trades)

    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=_payload(preview_limit=2),
    )

    body = response.json()
    assert body["summary"]["total_trades"] == 3
    assert body["summary"]["wallets_count"] == 3
    assert len(body["wallets"]) == 2
    assert len(body["trades_preview"]) == 2
    assert body["has_more_wallets"] is True
    assert [trade["tx_hash"] for trade in body["trades_preview"]] == ["tx1", "tx2"]


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
        "/api/bitquery/token-trades/analyze",
        json=_payload(),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["wallets"] == []
    assert body["trades_preview"] == []
    assert body["error"] == {
        "code": ERROR_PROVIDER_ERROR,
        "message": "Bitquery normalization error: bad payload.",
    }
    assert "Bitquery provider warning" in body["warnings"][0]


def test_invalid_preview_limit_zero_returns_422():
    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=_payload(preview_limit=0),
    )

    assert response.status_code == 422


def test_invalid_preview_limit_above_max_returns_422():
    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=_payload(preview_limit=101),
    )

    assert response.status_code == 422


def test_missing_token_address_returns_validation_error():
    payload = _payload()
    payload.pop("token_address")

    response = _client().post(
        "/api/bitquery/token-trades/analyze",
        json=payload,
    )

    assert response.status_code == 422


def test_bitquery_analysis_endpoint_does_not_write_to_db(monkeypatch):
    def fake_get_token_trades(self, token_address, start, end):
        return ProviderResult.success(
            [_trade("tx1", "EQholder", "buy", "1", "2")],
            source="real",
        )

    def forbidden_session():
        raise AssertionError("Bitquery analysis endpoint must not use DB")
        yield

    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setattr(BitqueryAdapter, "get_token_trades", fake_get_token_trades)
    app.dependency_overrides[get_session] = forbidden_session
    try:
        response = _client().post(
            "/api/bitquery/token-trades/analyze",
            json=_payload(),
        )
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    assert response.json()["success"] is True


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
