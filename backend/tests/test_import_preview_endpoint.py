"""Tests for the imported trades preview endpoint."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.import_trades import router
from services.analysis import analyze


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_valid_csv_preview_returns_summary_and_preview():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "content": "\n".join(
                [
                    "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                    "tx1,2026-05-24T12:00:00Z,EQwallet1,buy,1000,250",
                ]
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["invalid_rows"] == 0
    assert body["trades_preview"][0]["tx_hash"] == "tx1"
    assert body["trades_preview"][0]["price_usd"] == "0.25"
    assert body["preview_limit"] == 10
    assert body["has_more"] is False
    assert body["source"] == "imported_csv"


def test_valid_json_preview_returns_summary_and_preview():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "json",
            "content": [
                {
                    "tx_hash": "tx1",
                    "block_time": "2026-05-24T12:00:00Z",
                    "wallet": "EQwallet1",
                    "side": "buy",
                    "token_amount": "1000",
                    "usd_amount": "250",
                    "price_usd": "0.25",
                }
            ],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valid_rows"] == 1
    assert body["trades_preview"][0]["side"] == "buy"
    assert body["trades_preview"][0]["source"] == "imported_json"
    assert body["source"] == "imported_json"


def test_json_single_object_preview_is_supported():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "json",
            "content": {
                "tx_hash": "tx1",
                "block_time": "2026-05-24T12:00:00Z",
                "wallet": "EQwallet1",
                "side": "buy",
                "token_amount": "1000",
                "usd_amount": "250",
            },
            "preview_limit": 10,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valid_rows"] == 1
    assert len(body["trades_preview"]) == 1


def test_preview_limit_limits_rows_and_sets_has_more():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "preview_limit": 1,
            "content": "\n".join(
                [
                    "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                    "tx1,2026-05-24T12:00:00Z,EQwallet1,buy,1,2",
                    "tx2,2026-05-24T12:01:00Z,EQwallet2,sell,3,4",
                ]
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valid_rows"] == 2
    assert len(body["trades_preview"]) == 1
    assert body["has_more"] is True


def test_invalid_csv_row_returns_errors_with_http_200():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "content": "\n".join(
                [
                    "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                    "tx1,2026-05-24T12:00:00Z,EQwallet1,hold,1,2",
                ]
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valid_rows"] == 0
    assert body["summary"]["invalid_rows"] == 1
    assert body["summary"]["errors"] == [
        {
            "row": 2,
            "field": "side",
            "message": "Invalid side: expected buy or sell",
        }
    ]
    assert body["trades_preview"] == []


def test_duplicate_rows_are_counted_and_excluded_from_preview():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "content": "\n".join(
                [
                    "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                    "tx1,2026-05-24T12:00:00Z,EQwallet1,buy,1,2",
                    "tx1,2026-05-24T12:01:00Z,EQwallet1,BUY,1,3",
                ]
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["summary"]["valid_rows"] == 1
    assert body["summary"]["duplicate_rows"] == 1
    assert len(body["trades_preview"]) == 1
    assert body["trades_preview"][0]["usd_amount"] == "2"


def test_csv_content_must_be_string():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "content": [{"not": "a string"}],
            "preview_limit": 10,
        },
    )

    assert response.status_code == 422


def test_preview_limit_above_max_returns_validation_error():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "content": "",
            "preview_limit": 101,
        },
    )

    assert response.status_code == 422


def test_preview_limit_below_min_returns_validation_error():
    response = _client().post(
        "/api/import/trades/preview",
        json={
            "format": "csv",
            "content": "",
            "preview_limit": 0,
        },
    )

    assert response.status_code == 422


def test_missing_content_returns_validation_error():
    response = _client().post(
        "/api/import/trades/preview",
        json={"format": "csv"},
    )

    assert response.status_code == 422


def test_unsupported_format_returns_validation_error():
    response = _client().post(
        "/api/import/trades/preview",
        json={"format": "xml", "content": "<trades />"},
    )

    assert response.status_code == 422


def test_empty_csv_returns_clean_summary():
    response = _client().post(
        "/api/import/trades/preview",
        json={"format": "csv", "content": ""},
    )

    assert response.status_code == 200
    assert response.json() == {
        "summary": {
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "duplicate_rows": 0,
            "errors": [],
        },
        "trades_preview": [],
        "preview_limit": 10,
        "has_more": False,
        "source": "imported_csv",
    }


def test_existing_analyze_service_still_works():
    result = analyze(
        pool_url="https://www.geckoterminal.com/ton/pools/mock",
        time_window="24h",
    )

    assert result["pool_url"] == "https://www.geckoterminal.com/ton/pools/mock"
    assert result["summary"]["total_buyers"] > 0
    assert result["data_quality"]["components"]["wallet_buyers"] == "mock"
