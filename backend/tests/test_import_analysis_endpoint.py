"""Tests for imported trade per-wallet analysis endpoint."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.import_trades import router
from services.analysis import analyze


CSV_HEADER = "tx_hash,block_time,wallet,side,token_amount,usd_amount"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def _csv(*rows: str) -> str:
    return "\n".join((CSV_HEADER, *rows))


def _post_csv(content: str, preview_limit: int = 10):
    return _client().post(
        "/api/import/trades/analyze",
        json={
            "format": "csv",
            "content": content,
            "preview_limit": preview_limit,
        },
    )


def test_valid_csv_with_one_holder_wallet():
    response = _post_csv(
        _csv("tx1,2026-05-24T12:00:00Z,EQholder,buy,10,100")
    )

    assert response.status_code == 200
    body = response.json()
    wallet = body["wallets"][0]
    assert body["summary"]["wallets_count"] == 1
    assert body["summary"]["buy_trades_count"] == 1
    assert body["summary"]["sell_trades_count"] == 0
    assert wallet["wallet"] == "EQholder"
    assert wallet["status"] == "holder"
    assert wallet["total_bought_qty"] == "10"
    assert wallet["total_bought_usd"] == "100"
    assert wallet["net_holding_qty"] == "10"
    assert wallet["avg_buy_price_usd"] == "10"
    assert wallet["avg_sell_price_usd"] is None
    assert wallet["realized_pnl_usd"] == "0"
    assert wallet["realized_pnl_pct"] == "0"
    assert body["analysis_note"].startswith("Imported trades analysis is based only")


def test_valid_csv_with_one_partial_seller():
    response = _post_csv(
        _csv(
            "tx1,2026-05-24T12:00:00Z,EQpartial,buy,10,100",
            "tx2,2026-05-24T12:05:00Z,EQpartial,sell,4,60",
        )
    )

    assert response.status_code == 200
    wallet = response.json()["wallets"][0]
    assert wallet["status"] == "partial_seller"
    assert wallet["buy_trades_count"] == 1
    assert wallet["sell_trades_count"] == 1
    assert wallet["total_sold_qty"] == "4"
    assert wallet["total_sold_usd"] == "60"
    assert wallet["net_holding_qty"] == "6"
    assert wallet["avg_sell_price_usd"] == "15"


def test_valid_csv_with_one_full_exit():
    response = _post_csv(
        _csv(
            "tx1,2026-05-24T12:00:00Z,EQexit,buy,10,100",
            "tx2,2026-05-24T12:05:00Z,EQexit,sell,10,120",
        )
    )

    assert response.status_code == 200
    wallet = response.json()["wallets"][0]
    assert wallet["status"] == "full_exit"
    assert wallet["net_holding_qty"] == "0"


def test_seller_only_wallet():
    response = _post_csv(
        _csv("tx1,2026-05-24T12:00:00Z,EQseller,sell,5,50")
    )

    assert response.status_code == 200
    wallet = response.json()["wallets"][0]
    assert wallet["status"] == "seller_only"
    assert wallet["total_bought_qty"] == "0"
    assert wallet["total_sold_qty"] == "5"
    assert wallet["avg_buy_price_usd"] is None
    assert wallet["avg_sell_price_usd"] == "10"
    assert wallet["realized_pnl_usd"] == "0"
    assert wallet["realized_pnl_pct"] is None


def test_realized_pnl_uses_average_cost_approximation():
    response = _post_csv(
        _csv(
            "tx1,2026-05-24T12:00:00Z,EQpnl,buy,10,100",
            "tx2,2026-05-24T12:05:00Z,EQpnl,sell,4,60",
        )
    )

    assert response.status_code == 200
    wallet = response.json()["wallets"][0]
    assert wallet["realized_pnl_usd"] == "20"
    assert wallet["realized_pnl_pct"] == "50"


def test_duplicate_trades_are_excluded_from_calculations():
    response = _post_csv(
        _csv(
            "tx1,2026-05-24T12:00:00Z,EQdup,buy,10,100",
            "tx1,2026-05-24T12:01:00Z,EQdup,BUY,10,999",
        )
    )

    assert response.status_code == 200
    body = response.json()
    wallet = body["wallets"][0]
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["duplicate_rows"] == 1
    assert wallet["total_bought_usd"] == "100"
    assert wallet["avg_buy_price_usd"] == "10"


def test_invalid_rows_are_reported_and_valid_rows_still_analyzed():
    response = _post_csv(
        _csv(
            "tx1,2026-05-24T12:00:00Z,EQvalid,buy,10,100",
            "tx2,2026-05-24T12:01:00Z,EQbad,hold,5,20",
        )
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["invalid_rows"] == 1
    assert body["summary"]["errors"] == [
        {
            "row": 3,
            "field": "side",
            "message": "Invalid side: expected buy or sell",
        }
    ]
    assert body["summary"]["wallets_count"] == 1
    assert body["wallets"][0]["wallet"] == "EQvalid"


def test_preview_limit_limits_wallets_and_sets_has_more_wallets():
    response = _post_csv(
        _csv(
            "tx1,2026-05-24T12:00:00Z,EQb,buy,10,200",
            "tx2,2026-05-24T12:01:00Z,EQa,buy,10,200",
            "tx3,2026-05-24T12:02:00Z,EQc,buy,10,50",
        ),
        preview_limit=2,
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["wallets_count"] == 3
    assert len(body["wallets"]) == 2
    assert body["has_more_wallets"] is True
    assert [wallet["wallet"] for wallet in body["wallets"]] == ["EQa", "EQb"]


def test_json_input_works():
    response = _client().post(
        "/api/import/trades/analyze",
        json={
            "format": "json",
            "content": [
                {
                    "tx_hash": "tx1",
                    "block_time": "2026-05-24T12:00:00Z",
                    "wallet": "EQjson",
                    "side": "buy",
                    "token_amount": "8",
                    "usd_amount": "24",
                }
            ],
            "preview_limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "imported_json"
    assert body["summary"]["wallets_count"] == 1
    assert body["wallets"][0]["wallet"] == "EQjson"
    assert body["wallets"][0]["avg_buy_price_usd"] == "3"
    assert body["trades_preview"][0]["source"] == "imported_json"


def test_existing_preview_endpoint_still_works():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "content": _csv("tx1,2026-05-24T12:00:00Z,EQwallet,buy,1,2"),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valid_rows"] == 1
    assert body["trades_preview"][0]["price_usd"] == "2"


def test_existing_analyze_service_still_works():
    result = analyze(
        pool_url="https://www.geckoterminal.com/ton/pools/mock",
        time_window="24h",
    )

    assert result["summary"]["total_buyers"] > 0
    assert result["data_quality"]["components"]["wallet_buyers"] == "mock"
