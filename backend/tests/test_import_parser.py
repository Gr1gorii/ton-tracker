"""Tests for user-provided trade import parsing."""

from decimal import Decimal

from services.import_parser import parse_csv_trades, parse_json_trades


def test_valid_csv_with_buy_and_sell_rows():
    result = parse_csv_trades(
        "\n".join(
            [
                "tx_hash,block_time,wallet,side,token_amount,usd_amount,price_usd,pool_address,dex",
                "tx1,2026-05-24T10:00:00Z,EQwallet1,BUY,100,25,0.25,EQpool,stonfi",
                "tx2,2026-05-24T11:00:00+00:00,EQwallet2,sell,50,20,0.4,,dedust",
            ]
        )
    )

    assert result["summary"] == {
        "total_rows": 2,
        "valid_rows": 2,
        "invalid_rows": 0,
        "duplicate_rows": 0,
        "errors": [],
    }
    assert result["trades"][0]["side"] == "buy"
    assert result["trades"][0]["block_time"] == "2026-05-24T10:00:00+00:00"
    assert result["trades"][0]["token_amount"] == Decimal("100")
    assert result["trades"][0]["usd_amount"] == Decimal("25")
    assert result["trades"][0]["price_usd"] == Decimal("0.25")
    assert result["trades"][0]["pool_address"] == "EQpool"
    assert result["trades"][0]["dex"] == "stonfi"
    assert result["trades"][0]["source"] == "imported_csv"
    assert result["trades"][1]["side"] == "sell"


def test_missing_price_usd_calculates_from_usd_and_token_amount():
    result = parse_csv_trades(
        "\n".join(
            [
                "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                "tx1,2026-05-24T10:00:00Z,EQwallet1,buy,4,10",
            ]
        )
    )

    assert result["summary"]["valid_rows"] == 1
    assert result["trades"][0]["price_usd"] == Decimal("2.5")


def test_invalid_side_returns_validation_error():
    result = parse_csv_trades(
        "\n".join(
            [
                "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                "tx1,2026-05-24T10:00:00Z,EQwallet1,hold,4,10",
            ]
        )
    )

    assert result["trades"] == []
    assert result["summary"]["invalid_rows"] == 1
    assert result["summary"]["errors"] == [
        {
            "row": 2,
            "field": "side",
            "message": "Invalid side: expected buy or sell",
        }
    ]


def test_invalid_numeric_field_returns_validation_error():
    result = parse_csv_trades(
        "\n".join(
            [
                "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                "tx1,2026-05-24T10:00:00Z,EQwallet1,buy,not-a-number,10",
            ]
        )
    )

    assert result["summary"]["valid_rows"] == 0
    assert result["summary"]["invalid_rows"] == 1
    assert result["summary"]["errors"][0] == {
        "row": 2,
        "field": "token_amount",
        "message": "Invalid numeric value",
    }


def test_duplicate_row_is_deduplicated_and_counted():
    result = parse_csv_trades(
        "\n".join(
            [
                "tx_hash,block_time,wallet,side,token_amount,usd_amount",
                "tx1,2026-05-24T10:00:00Z,EQwallet1,buy,4,10",
                "tx1,2026-05-24T10:01:00Z,EQwallet1,BUY,4,11",
            ]
        )
    )

    assert result["summary"]["total_rows"] == 2
    assert result["summary"]["valid_rows"] == 1
    assert result["summary"]["invalid_rows"] == 0
    assert result["summary"]["duplicate_rows"] == 1
    assert len(result["trades"]) == 1


def test_json_like_input_parsing():
    result = parse_json_trades(
        [
            {
                "tx_hash": "tx1",
                "block_time": "2026-05-24T10:00:00Z",
                "wallet": "EQwallet1",
                "side": "Sell",
                "token_amount": "8",
                "usd_amount": "4",
                "pool_address": "EQpool",
            }
        ]
    )

    assert result["summary"]["valid_rows"] == 1
    assert result["trades"][0]["side"] == "sell"
    assert result["trades"][0]["price_usd"] == Decimal("0.5")
    assert result["trades"][0]["pool_address"] == "EQpool"
    assert result["trades"][0]["source"] == "imported_json"


def test_empty_csv_returns_clear_validation_summary():
    result = parse_csv_trades("")

    assert result == {
        "trades": [],
        "summary": {
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "duplicate_rows": 0,
            "errors": [],
        },
    }
