"""Tests confirming PnL math + status classification still work."""

from services.pnl import calculate_pnl

PRICE = 0.0125  # GRAM current price used by the mock dataset


def test_holder_unrealised_only():
    r = calculate_pnl(
        total_bought_qty=1_000_000,
        total_bought_usd=8_000,
        total_sold_qty=0,
        total_sold_usd=0,
        current_holding=1_000_000,
        current_price_usd=PRICE,
    )
    assert r.status == "holder"
    assert r.avg_buy_price_usd == 0.008
    assert r.realised_pnl_usd == 0.0
    assert r.unrealised_pnl_usd == 4_500.0
    assert r.unrealised_pnl_pct == 56.25
    assert r.total_pnl_usd == 4_500.0


def test_partial_seller():
    r = calculate_pnl(
        total_bought_qty=500_000,
        total_bought_usd=4_250,
        total_sold_qty=150_000,
        total_sold_usd=1_650,
        current_holding=350_000,
        current_price_usd=PRICE,
    )
    assert r.status == "partial_seller"
    # avg buy 0.0085; realised = 1650 - 0.0085*150000 = 375
    assert r.realised_pnl_usd == 375.0
    # unrealised = 350000*0.0125 - 0.0085*350000 = 4375 - 2975 = 1400
    assert r.unrealised_pnl_usd == 1_400.0
    assert r.total_pnl_usd == 1_775.0


def test_full_exit():
    r = calculate_pnl(
        total_bought_qty=400_000,
        total_bought_usd=3_600,
        total_sold_qty=400_000,
        total_sold_usd=6_000,
        current_holding=0,
        current_price_usd=PRICE,
    )
    assert r.status == "full_exit"
    assert r.realised_pnl_usd == 2_400.0  # 6000 - 3600
    assert r.unrealised_pnl_usd == 0.0


def test_negative_realised():
    r = calculate_pnl(
        total_bought_qty=600_000,
        total_bought_usd=7_200,
        total_sold_qty=200_000,
        total_sold_usd=1_800,
        current_holding=400_000,
        current_price_usd=PRICE,
    )
    assert r.status == "partial_seller"
    # avg buy 0.012; realised = 1800 - 0.012*200000 = -600
    assert r.realised_pnl_usd == -600.0
    assert r.realised_pnl_pct == -25.0


def test_unknown_when_no_buys():
    r = calculate_pnl(
        total_bought_qty=0,
        total_bought_usd=0,
        total_sold_qty=0,
        total_sold_usd=0,
        current_holding=0,
        current_price_usd=PRICE,
    )
    assert r.status == "unknown"
    assert r.total_pnl_usd == 0.0
