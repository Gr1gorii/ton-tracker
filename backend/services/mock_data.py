"""Realistic mock data for v0.1.

NO real network calls happen anywhere in this module. It returns hand-crafted
fixtures shaped exactly like the data a real GeckoTerminal + TON indexer
pipeline would eventually provide, so the rest of the backend can be built and
tested against a stable contract.

The wallet fixtures are tuned so the analysis output contains, at minimum:
  * 3 holder-only wallets, 3 partial sellers, 2 full-exit wallets
  * 2 whales (TON balance > 500)
  * 2 wallets flagged ИНТЕРЕСНО (a token position worth > $5,000)
  * 3 distinct candidate clusters plus ungrouped wallets
  * shared holdings across several wallets
  * at least one negative realised PnL and one large unrealised PnL
"""

from __future__ import annotations

# --- Market-wide constants for the analyzed market ------------------------

TON_PRICE_USD = 5.20
INTERESTING_POSITION_USD = 5000.0  # a position worth more than this => ИНТЕРЕСНО
HIGH_TON_BALANCE = 500.0  # TON balance above this => whale

TOKEN_INFO = {
    "name": "Gram",
    "symbol": "GRAM",
    "address": "EQB-MPwrd1G6WKNkLz_VnV6WqBDd142KMQv-g1O-8QUA3728",
    "decimals": 9,
    "current_price_usd": 0.0125,
    "market_cap_usd": 12_480_000,
    "fdv_usd": 31_250_000,
}

POOL_INFO = {
    "address": "EQCp_C-wPq2Z-9Z9JdVx...mockpool...STONfi",
    "dex": "STON.fi",
    "base_token": "GRAM",
    "quote_token": "TON",
    "liquidity_usd": 842_300,
    "volume_24h_usd": 1_276_400,
    "created_at": "2026-03-02T11:24:00Z",
}


# Each entry is RAW aggregate trade data for one wallet over the analyzed
# window. Derived metrics (PnL, flags, portfolio value) are computed downstream
# in services/analysis.py so this file stays a pure data fixture.
#
# Fields:
#   address              TON wallet address (mock)
#   total_bought_qty     tokens bought during window
#   total_bought_usd     USD spent buying
#   total_sold_qty       tokens sold during window
#   total_sold_usd       USD received selling
#   current_holding      tokens still held
#   ton_balance          native TON balance
#   common_tokens        other notable tokens this wallet holds/trades
#   other_positions      non-analyzed token positions (USD value) for the
#                        portfolio + ИНТЕРЕСНО computation
#   buy_time_fraction    when in the window the wallet bought (0=start, 1=end)
#   group                candidate cluster tag, or "none" if ungrouped
WALLETS: list[dict] = [
    # --- cluster_alpha: early buyers, ~$0.008 entry, hold GRAM/NOT/STON ---
    {
        "address": "EQAlpha1_n7Yh3kQv5rT...holderwhale",
        "total_bought_qty": 1_000_000,
        "total_bought_usd": 8_000,
        "total_sold_qty": 0,
        "total_sold_usd": 0,
        "current_holding": 1_000_000,
        "ton_balance": 820,  # whale
        "common_tokens": ["GRAM", "NOT", "STON"],
        "other_positions": [
            {"symbol": "NOT", "value_usd": 3_200},
            {"symbol": "STON", "value_usd": 1_100},
        ],
        "buy_time_fraction": 0.040,
        "group": "cluster_alpha",
    },
    {
        "address": "EQAlpha2_p2Lд9fGm...holder",
        "total_bought_qty": 300_000,
        "total_bought_usd": 2_550,
        "total_sold_qty": 0,
        "total_sold_usd": 0,
        "current_holding": 300_000,
        "ton_balance": 45,
        "common_tokens": ["GRAM", "NOT", "STON"],
        "other_positions": [
            {"symbol": "NOT", "value_usd": 600},
            {"symbol": "STON", "value_usd": 300},
        ],
        "buy_time_fraction": 0.044,
        "group": "cluster_alpha",
    },
    {
        "address": "EQAlpha3_k9Wm2zXt...partial",
        "total_bought_qty": 500_000,
        "total_bought_usd": 4_250,
        "total_sold_qty": 150_000,
        "total_sold_usd": 1_650,
        "current_holding": 350_000,
        "ton_balance": 60,
        "common_tokens": ["GRAM", "NOT", "STON"],
        "other_positions": [
            {"symbol": "NOT", "value_usd": 700},
        ],
        "buy_time_fraction": 0.049,
        "group": "cluster_alpha",
    },
    # --- cluster_beta: mid-window buyers, ~$0.0095 entry, GRAM/DOGS/USDT ---
    {
        "address": "EQBeta1_r4Tn8vБq...partial",
        "total_bought_qty": 200_000,
        "total_bought_usd": 1_900,
        "total_sold_qty": 80_000,
        "total_sold_usd": 1_040,
        "current_holding": 120_000,
        "ton_balance": 30,
        "common_tokens": ["GRAM", "DOGS", "USDT"],
        "other_positions": [
            {"symbol": "DOGS", "value_usd": 900},
            {"symbol": "USDT", "value_usd": 1_200},
        ],
        "buy_time_fraction": 0.451,
        "group": "cluster_beta",
    },
    {
        "address": "EQBeta2_s6Yp3wНr...partial",
        "total_bought_qty": 260_000,
        "total_bought_usd": 2_470,
        "total_sold_qty": 100_000,
        "total_sold_usd": 1_250,
        "current_holding": 160_000,
        "ton_balance": 75,
        "common_tokens": ["GRAM", "DOGS", "USDT"],
        "other_positions": [
            {"symbol": "DOGS", "value_usd": 1_100},
            {"symbol": "USDT", "value_usd": 800},
        ],
        "buy_time_fraction": 0.470,
        "group": "cluster_beta",
    },
    {
        "address": "EQBeta3_t8Zq5xОs...partial",
        "total_bought_qty": 220_000,
        "total_bought_usd": 2_090,
        "total_sold_qty": 60_000,
        "total_sold_usd": 720,
        "current_holding": 160_000,
        "ton_balance": 50,
        "common_tokens": ["GRAM", "DOGS", "USDT"],
        "other_positions": [
            {"symbol": "DOGS", "value_usd": 700},
            {"symbol": "USDT", "value_usd": 600},
        ],
        "buy_time_fraction": 0.445,
        "group": "cluster_beta",
    },
    # --- cluster_gamma: late buyers, ~$0.009 entry, two full exits + holder -
    {
        "address": "EQGamma1_u1Аr7yPt...fullexit",
        "total_bought_qty": 400_000,
        "total_bought_usd": 3_600,
        "total_sold_qty": 400_000,
        "total_sold_usd": 6_000,
        "current_holding": 0,
        "ton_balance": 210,
        "common_tokens": ["GRAM", "HMSTR", "REDO"],
        "other_positions": [
            {"symbol": "HMSTR", "value_usd": 1_800},
            {"symbol": "REDO", "value_usd": 900},
        ],
        "buy_time_fraction": 0.915,
        "group": "cluster_gamma",
    },
    {
        "address": "EQGamma2_v3Бs9zQu...fullexit",
        "total_bought_qty": 350_000,
        "total_bought_usd": 3_150,
        "total_sold_qty": 350_000,
        "total_sold_usd": 4_200,
        "current_holding": 0,
        "ton_balance": 180,
        "common_tokens": ["GRAM", "HMSTR", "REDO"],
        "other_positions": [
            {"symbol": "HMSTR", "value_usd": 1_200},
            {"symbol": "REDO", "value_usd": 700},
        ],
        "buy_time_fraction": 0.932,
        "group": "cluster_gamma",
    },
    {
        "address": "EQGamma3_w5Вt2xRv...holder",
        "total_bought_qty": 150_000,
        "total_bought_usd": 1_350,
        "total_sold_qty": 0,
        "total_sold_usd": 0,
        "current_holding": 150_000,
        "ton_balance": 90,
        "common_tokens": ["GRAM", "HMSTR", "REDO"],
        "other_positions": [
            {"symbol": "HMSTR", "value_usd": 600},
            {"symbol": "REDO", "value_usd": 400},
        ],
        "buy_time_fraction": 0.938,
        "group": "cluster_gamma",
    },
    # --- ungrouped wallets ------------------------------------------------
    {
        "address": "EQSolo1_x7Гu4ySw...holder",
        "total_bought_qty": 80_000,
        "total_bought_usd": 720,
        "total_sold_qty": 0,
        "total_sold_usd": 0,
        "current_holding": 80_000,
        "ton_balance": 15,
        "common_tokens": ["GRAM", "USDT"],
        "other_positions": [
            {"symbol": "USDT", "value_usd": 300},
        ],
        "buy_time_fraction": 0.240,
        "group": "none",
    },
    {
        # Negative realised PnL: sold part below average buy price.
        "address": "EQSolo2_y9Дv6zTx...partial_loss",
        "total_bought_qty": 600_000,
        "total_bought_usd": 7_200,
        "total_sold_qty": 200_000,
        "total_sold_usd": 1_800,
        "current_holding": 400_000,
        "ton_balance": 40,
        "common_tokens": ["GRAM", "NOT"],
        "other_positions": [
            {"symbol": "NOT", "value_usd": 400},
        ],
        "buy_time_fraction": 0.580,
        "group": "none",
    },
    {
        # Whale + ИНТЕРЕСНО: large holding, large unrealised gain.
        "address": "EQSolo3_z1Еw8yUz...whale_interesting",
        "total_bought_qty": 1_500_000,
        "total_bought_usd": 13_500,
        "total_sold_qty": 0,
        "total_sold_usd": 0,
        "current_holding": 1_500_000,
        "ton_balance": 1_250,  # whale
        "common_tokens": ["GRAM", "USDT", "NOT"],
        "other_positions": [
            {"symbol": "USDT", "value_usd": 4_000},
            {"symbol": "NOT", "value_usd": 2_000},
        ],
        "buy_time_fraction": 0.750,
        "group": "none",
    },
    {
        "address": "EQSolo4_a2Жx0zVa...partial",
        "total_bought_qty": 120_000,
        "total_bought_usd": 1_200,
        "total_sold_qty": 40_000,
        "total_sold_usd": 520,
        "current_holding": 80_000,
        "ton_balance": 25,
        "common_tokens": ["GRAM", "DOGS"],
        "other_positions": [
            {"symbol": "DOGS", "value_usd": 300},
        ],
        "buy_time_fraction": 0.810,
        "group": "none",
    },
    {
        "address": "EQSolo5_b4Зy1aWb...holder",
        "total_bought_qty": 95_000,
        "total_bought_usd": 950,
        "total_sold_qty": 0,
        "total_sold_usd": 0,
        "current_holding": 95_000,
        "ton_balance": 8,
        "common_tokens": ["GRAM", "STON"],
        "other_positions": [
            {"symbol": "STON", "value_usd": 250},
        ],
        "buy_time_fraction": 0.140,
        "group": "none",
    },
]


def get_token_info() -> dict:
    return dict(TOKEN_INFO)


def get_pool_info() -> dict:
    return dict(POOL_INFO)


def get_raw_wallets() -> list[dict]:
    """Return deep-ish copies so callers can enrich without mutating fixtures."""
    return [
        {**w, "common_tokens": list(w["common_tokens"]),
         "other_positions": [dict(p) for p in w["other_positions"]]}
        for w in WALLETS
    ]
