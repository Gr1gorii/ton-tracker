"""Export helpers.

v0.1 produces CSV / JSON exports of an analysis result. The endpoints currently
run a fresh mock analysis and serialize it; a later version will export a
specific stored run by id.
"""

from __future__ import annotations

import csv
import io
import json

# Columns mirror the frontend buyers table.
CSV_COLUMNS = [
    "address",
    "status",
    "total_bought_qty",
    "total_bought_usd",
    "total_sold_qty",
    "total_sold_usd",
    "current_holding",
    "avg_buy_price_usd",
    "avg_sell_price_usd",
    "realised_pnl_usd",
    "realised_pnl_pct",
    "unrealised_pnl_usd",
    "unrealised_pnl_pct",
    "total_pnl_usd",
    "total_pnl_pct",
    "ton_balance",
    "portfolio_value_usd",
    "common_tokens",
    "group",
    "connected_score",
    "interesting",
    "high_ton_balance",
    "Вывод",
]


def wallets_to_csv(analysis: dict) -> str:
    """Serialize the wallet rows of an analysis result to CSV text."""
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CSV_COLUMNS, extrasaction="ignore"
    )
    writer.writeheader()
    for wallet in analysis.get("wallets", []):
        row = dict(wallet)
        # Flatten list-valued cells for CSV.
        row["common_tokens"] = "|".join(wallet.get("common_tokens", []))
        writer.writerow(row)
    return buffer.getvalue()


def analysis_to_json(analysis: dict) -> str:
    """Serialize a full analysis result to pretty JSON text."""
    return json.dumps(analysis, ensure_ascii=False, indent=2)
