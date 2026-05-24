"""Tests confirming probabilistic clustering still works + stays hedged."""

from config import Settings
from services import clustering
from services.analysis import analyze

WINDOW = 24 * 3600


def _wallet(addr, group, frac_buy, price, tokens, sold_frac, ton, pv):
    return {
        "address": addr,
        "group": group,
        "buy_time_offset_s": frac_buy * WINDOW,
        "avg_buy_price_usd": price,
        "common_tokens": tokens,
        "sold_fraction": sold_frac,
        "ton_balance": ton,
        "portfolio_value_usd": pv,
    }


def test_score_band_labels():
    assert clustering.score_band_label(10) == "weak/no signal"
    assert clustering.score_band_label(60) == "possible cluster"
    assert clustering.score_band_label(95).endswith("not proof")


def test_pair_similarity_range_and_identity():
    a = _wallet("A", "g", 0.04, 0.008, ["GRAM", "NOT"], 0.0, 100, 1000)
    b = _wallet("B", "g", 0.041, 0.008, ["GRAM", "NOT"], 0.0, 100, 1000)
    score = clustering.pair_similarity(a, b, WINDOW)
    assert 0 <= score <= 100
    # Nearly identical wallets => very high similarity.
    assert score >= 95


def test_build_groups_structure():
    wallets = [
        _wallet("A", "g1", 0.04, 0.008, ["GRAM", "NOT"], 0.0, 100, 1000),
        _wallet("B", "g1", 0.045, 0.0082, ["GRAM", "NOT"], 0.0, 90, 1100),
        _wallet("C", "none", 0.9, 0.02, ["GRAM"], 1.0, 5, 200),
    ]
    groups = clustering.build_groups(wallets, WINDOW)
    assert len(groups) == 1  # only g1 (>=2 members); 'none' excluded
    g = groups[0]
    for key in (
        "group_name",
        "group_type",
        "wallet_list",
        "shared_tokens",
        "average_connected_score",
        "reason_summary",
        "Вывод",
    ):
        assert key in g
    assert 0 <= g["average_connected_score"] <= 100
    # Hedged language: never claims definite common ownership.
    assert "не доказательство" in g["Вывод"]


def test_clustering_via_analyze_mock():
    settings = Settings(
        data_mode="mock",
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        ton_api_base_url="",
        ton_api_key="",
        bitquery_api_url="",
        bitquery_api_key="",
    )
    result = analyze(
        "https://www.geckoterminal.com/ton/pools/EQpool", "24h",
        settings=settings,
    )
    assert len(result["groups"]) == 3
    for g in result["groups"]:
        assert 0 <= g["average_connected_score"] <= 100
        assert "не доказательство" in g["Вывод"]
    # Every wallet gets a connected score in range.
    for w in result["wallets"]:
        assert 0 <= w["connected_score"] <= 100
