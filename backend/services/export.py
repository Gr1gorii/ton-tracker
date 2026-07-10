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


# Flattened activity columns for a stored wallet ingestion run export.
ACTIVITY_CSV_COLUMNS = [
    "surface",
    "tx_hash",
    "timestamp",
    "asset",
    "amount",
    "direction",
    "counterparty",
    "dex",
    "token_in",
    "amount_in",
    "token_out",
    "amount_out",
    "fee_ton",
    "success",
    "balance",
    "balance_usd",
    "provider",
    "source_status",
    "transaction_identity_status",
    "transaction_identity_version",
    "transaction_network",
    "transaction_account_canonical",
    "transaction_logical_time_canonical",
    "transaction_hash_canonical",
    "transaction_identity_key",
]


def wallet_ingestion_run_to_csv(run: dict) -> str:
    """Serialize a stored wallet ingestion run into flattened activity CSV.

    One row per activity item, tagged by surface. Heterogeneous columns are
    left blank where a surface does not provide them.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=ACTIVITY_CSV_COLUMNS, extrasaction="ignore"
    )
    writer.writeheader()

    for item in run.get("transfers", []):
        writer.writerow(
            {
                "surface": "transfer",
                "tx_hash": item.get("tx_hash"),
                "timestamp": item.get("timestamp"),
                "asset": item.get("asset"),
                "amount": item.get("amount"),
                "direction": item.get("direction"),
                "counterparty": item.get("counterparty"),
                "provider": item.get("provider"),
                "source_status": item.get("source_status"),
            }
        )
    for item in run.get("transactions", []):
        identity = item.get("transaction_identity") or {}
        writer.writerow(
            {
                "surface": "transaction",
                "tx_hash": item.get("tx_hash"),
                "timestamp": item.get("timestamp"),
                "fee_ton": item.get("fee_ton"),
                "success": item.get("success"),
                "provider": item.get("provider"),
                "source_status": item.get("source_status"),
                "transaction_identity_status": identity.get("status"),
                "transaction_identity_version": identity.get("version"),
                "transaction_network": identity.get("network"),
                "transaction_account_canonical": identity.get(
                    "account_canonical"
                ),
                "transaction_logical_time_canonical": identity.get(
                    "logical_time_canonical"
                ),
                "transaction_hash_canonical": identity.get("hash_canonical"),
                "transaction_identity_key": identity.get("key"),
            }
        )
    for item in run.get("swaps", []):
        writer.writerow(
            {
                "surface": "swap",
                "tx_hash": item.get("tx_hash"),
                "timestamp": item.get("timestamp"),
                "dex": item.get("dex"),
                "token_in": item.get("token_in"),
                "amount_in": item.get("amount_in"),
                "token_out": item.get("token_out"),
                "amount_out": item.get("amount_out"),
                "provider": item.get("provider"),
                "source_status": item.get("source_status"),
            }
        )
    for item in run.get("balances", []):
        writer.writerow(
            {
                "surface": "balance",
                "timestamp": item.get("snapshot_at"),
                "asset": item.get("asset"),
                "balance": item.get("balance"),
                "balance_usd": item.get("balance_usd"),
                "provider": item.get("provider"),
                "source_status": item.get("source_status"),
            }
        )
    return buffer.getvalue()


# One row per compared wallet pair, mirroring the UI pair-detail table.
CLUSTER_COMPARISON_CSV_COLUMNS = [
    "wallet_a_run_id",
    "wallet_a_address",
    "wallet_b_run_id",
    "wallet_b_address",
    "score",
    "band",
    "shared_tokens",
]


def wallet_cluster_comparison_to_csv(comparison: dict) -> str:
    """Serialize a wallet cluster comparison into flattened pair CSV text.

    One row per wallet pair. This is a probabilistic similarity signal only,
    not proof of common ownership.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=CLUSTER_COMPARISON_CSV_COLUMNS, extrasaction="ignore"
    )
    writer.writeheader()
    for pair in comparison.get("pairs", []):
        row = dict(pair)
        # Flatten the list-valued cell for CSV.
        row["shared_tokens"] = "|".join(pair.get("shared_tokens", []))
        writer.writerow(row)
    return buffer.getvalue()


# One row per evidence record: derived signals first, then rules that lacked
# sufficient evidence, tagged by record_type. Blank cells mean the column does
# not apply to that record type.
RUN_SIGNALS_CSV_COLUMNS = [
    "record_type",
    "code",
    "title",
    "confidence",
    "observation",
    "evidence",
    "reason",
]


# One row per record: estimated token flows, optional USD-valued flows,
# in-window realized results, spot-based unrealized records plus their coverage
# summary, then the Real-PnL evidence checklist. Blank cells mean the column
# does not apply to that record type.
PNL_PREVIEW_CSV_COLUMNS = [
    "record_type",
    "token",
    "buy_swap_count",
    "sell_swap_count",
    "token_bought_qty",
    "token_sold_qty",
    "ton_spent",
    "ton_received",
    "net_ton_flow",
    "fee_ton",
    "net_ton_flow_after_fees",
    "matched_swap_count",
    "usd_spent",
    "usd_received",
    "net_usd_flow",
    "status",
    "sell_leg_count",
    "proceeds_usd",
    "cost_basis_usd",
    "realized_pnl_usd",
    "remaining_qty",
    "code",
    "available",
    "reason",
    "remaining_cost_usd",
    "spot_price_usd",
    "priced_by",
    "market_value_usd",
    "unrealized_pnl_usd",
    "total_unrealized_pnl_usd",
    "priced_record_count",
    "unavailable_record_count",
    "note",
]


def wallet_pnl_preview_to_csv(result: dict) -> str:
    """Serialize an estimated PnL preview into flattened CSV text.

    One row per token flow, USD-valued flow, realized cost-basis result,
    unrealized result, unrealized coverage/subtotal summary, or Real-PnL
    requirement. Real PnL is decided solely by requirement rows.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=PNL_PREVIEW_CSV_COLUMNS, extrasaction="ignore"
    )
    writer.writeheader()
    for flow in result.get("token_flows", []):
        row = dict(flow)
        row["record_type"] = "token_flow"
        writer.writerow(row)
    for flow in result.get("usd_flows", []):
        row = dict(flow)
        row["record_type"] = "usd_flow"
        writer.writerow(row)
    for record in result.get("realized_pnl", []):
        row = dict(record)
        row["record_type"] = "realized"
        row["reason"] = record.get("reason") or ""
        writer.writerow(row)
    unrealized_records = result.get("unrealized", [])
    for record in unrealized_records:
        row = dict(record)
        row["record_type"] = "unrealized"
        row["reason"] = record.get("reason") or ""
        writer.writerow(row)
    if "unrealized" in result:
        writer.writerow(
            {
                "record_type": "unrealized_coverage",
                "priced_record_count": sum(
                    record.get("status") == "computed"
                    for record in unrealized_records
                ),
                "unavailable_record_count": sum(
                    record.get("status") == "unavailable"
                    for record in unrealized_records
                ),
                "note": result.get("unrealized_note") or (
                    "No unrealized candidate records were derived; 0/0 "
                    "coverage does not prove that the wallet has no holdings."
                ),
            }
        )
    if result.get("total_unrealized_pnl_usd") is not None:
        writer.writerow(
            {
                "record_type": "unrealized_subtotal",
                "total_unrealized_pnl_usd": result[
                    "total_unrealized_pnl_usd"
                ],
                "note": (
                    "Priced subtotal sums computed unrealized records only; "
                    "unavailable records are excluded."
                ),
            }
        )
    for requirement in result.get("requirements", []):
        writer.writerow(
            {
                "record_type": "requirement",
                "code": requirement.get("code"),
                "available": requirement.get("available"),
                "reason": requirement.get("reason") or "",
            }
        )
    return buffer.getvalue()


def wallet_run_signals_to_csv(result: dict) -> str:
    """Serialize run evidence signals into flattened CSV text.

    One row per signal or insufficient-evidence record. Signals are heuristic
    indicators only -- not a risk score or a verdict.
    """
    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=RUN_SIGNALS_CSV_COLUMNS, extrasaction="ignore"
    )
    writer.writeheader()
    for signal in result.get("signals", []):
        row = dict(signal)
        row["record_type"] = "signal"
        # Flatten the evidence mapping for CSV.
        row["evidence"] = "|".join(
            f"{key}={value}" for key, value in signal.get("evidence", {}).items()
        )
        writer.writerow(row)
    for item in result.get("insufficient_evidence", []):
        writer.writerow(
            {
                "record_type": "insufficient_evidence",
                "code": item.get("code"),
                "reason": item.get("reason"),
            }
        )
    return buffer.getvalue()
