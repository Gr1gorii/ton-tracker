"""Real wallet-pair clustering from persisted wallet ingestion runs.

Wires already-ingested ``WalletIngestionRun`` data into the existing hedged
similarity scorer in ``services.clustering`` (reused unmodified). No
historical USD pricing exists anywhere in this project, so every signal here
is derived directly from on-chain swap/balance rows instead of retroactively
applying a current price to a past trade:

- entry-price signal: average TON spent per buy swap (on-chain ratio, not a
  USD price).
- sold/bought balance: swap counts (buy vs sell), not token amounts, since
  different jettons are not unit-comparable without pricing.
- portfolio value: the run's existing current-holdings USD total, which is
  already an honest *current*-value figure, not a PnL or trade-time claim.

Output is a probabilistic similarity signal only, never proof of common
ownership, consistent with ``services.clustering``'s framing.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from models import WalletIngestionRun
from services import clustering
from services.wallet_activity_ingestion import wallet_ingestion_run_to_response
from services.wallet_canonical_ledger import build_wallet_canonical_report

_ZERO = Decimal(0)
_MIN_WINDOW_SECONDS = 3600.0
_DEFAULT_WINDOW_SECONDS = 86400.0


def _dec(value: Any) -> Decimal:
    if value is None or value == "":
        return _ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return _ZERO


def _parse_iso_seconds(value: str) -> float:
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    parsed = datetime.fromisoformat(cleaned)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def derive_wallet_signals(run_response: dict[str, Any]) -> dict[str, Any]:
    """Build the public, honest per-wallet signal dict from a run response."""
    swaps = run_response.get("swaps") or []
    balances = run_response.get("balances") or []

    buy_swaps = [s for s in swaps if (s.get("token_in") or "").upper() == "TON"]
    sell_swaps = [s for s in swaps if (s.get("token_out") or "").upper() == "TON"]

    avg_ton_per_buy_swap: str | None = None
    if buy_swaps:
        total_in = sum((_dec(s.get("amount_in")) for s in buy_swaps), _ZERO)
        avg_ton_per_buy_swap = str(total_in / Decimal(len(buy_swaps)))

    buy_timestamps = sorted(s["timestamp"] for s in buy_swaps if s.get("timestamp"))
    first_buy_at = buy_timestamps[0] if buy_timestamps else None

    distinct_tokens: set[str] = set()
    for s in swaps:
        for key in ("token_in", "token_out"):
            token = s.get(key)
            if token and token.upper() != "TON":
                distinct_tokens.add(token)
    for b in balances:
        asset = b.get("asset")
        if asset and asset.upper() != "TON":
            distinct_tokens.add(asset)

    ton_balance = _ZERO
    for b in balances:
        if (b.get("asset") or "").upper() == "TON":
            ton_balance = _dec(b.get("balance"))
            break

    portfolio = (
        (run_response.get("activity_summary") or {})
        .get("balances", {})
        .get("portfolio", {})
    )
    portfolio_value_usd = portfolio.get("total_balance_usd")

    warnings: list[str] = []
    if not buy_swaps and not sell_swaps:
        warnings.append(
            "No swaps observed in this run; entry-price and timing signals "
            "default to zero and carry no behavioral signal."
        )

    return {
        "run_id": run_response["run_id"],
        "wallet_address": run_response["wallet_address"],
        "data_mode": run_response["data_mode"],
        "ton_balance": str(ton_balance),
        "portfolio_value_usd": portfolio_value_usd,
        "distinct_tokens_touched": sorted(distinct_tokens),
        "buy_swap_count": len(buy_swaps),
        "sell_swap_count": len(sell_swaps),
        "avg_ton_per_buy_swap": avg_ton_per_buy_swap,
        "first_buy_at": first_buy_at,
        "warnings": warnings,
    }


def _scorer_features(signals: dict[str, Any], t0_seconds: float) -> dict[str, Any]:
    """Map honest public signals onto the keys ``clustering.pair_similarity``
    expects. ``avg_buy_price_usd`` here holds a TON-denominated ratio, never a
    USD price; this mapping is private to this module."""
    buy_time_offset_s = 0.0
    if signals.get("first_buy_at"):
        buy_time_offset_s = _parse_iso_seconds(signals["first_buy_at"]) - t0_seconds

    avg_ton = signals.get("avg_ton_per_buy_swap")
    buy = signals["buy_swap_count"]
    sell = signals["sell_swap_count"]

    return {
        "buy_time_offset_s": buy_time_offset_s,
        "avg_buy_price_usd": float(avg_ton) if avg_ton is not None else 0.0,
        "common_tokens": signals["distinct_tokens_touched"],
        "sold_fraction": (sell / (buy + sell)) if (buy + sell) > 0 else 0.0,
        "ton_balance": float(signals["ton_balance"]),
        "portfolio_value_usd": (
            float(signals["portfolio_value_usd"])
            if signals.get("portfolio_value_usd") is not None
            else 0.0
        ),
    }


def compare_wallet_activity(run_ids: list[int], session: Session) -> dict[str, Any]:
    """Compare 2-25 persisted wallet ingestion runs pairwise.

    Raises ``ValueError`` for invalid input (bad request) and ``LookupError``
    when a run_id does not exist (not found). All compared runs must share
    the same ``data_mode`` so live and mock-fixture data are never conflated.
    """
    unique_ids = list(dict.fromkeys(run_ids))
    if len(unique_ids) < 2:
        raise ValueError("At least 2 distinct run_ids are required to compare wallets.")
    if len(unique_ids) > 25:
        raise ValueError("At most 25 run_ids can be compared at once.")

    responses: list[dict[str, Any]] = []
    for run_id in unique_ids:
        run = session.get(WalletIngestionRun, run_id)
        if run is None:
            raise LookupError(f"Wallet ingestion run {run_id} not found")
        responses.append(wallet_ingestion_run_to_response(run))

    data_modes = {r["data_mode"] for r in responses}
    if len(data_modes) > 1:
        raise ValueError(
            "Cannot compare wallet ingestion runs across mixed data modes "
            f"({sorted(data_modes)}); compare runs from the same mode only."
        )

    canonical_mode = data_modes == {"real"}
    if canonical_mode:
        reports = [build_wallet_canonical_report(int(r["run_id"]), session) for r in responses]
        signals_list = [
            _derive_canonical_wallet_signals(response, report)
            for response, report in zip(responses, reports)
        ]
    else:
        signals_list = [derive_wallet_signals(r) for r in responses]

    swap_seconds: list[float] = []
    if canonical_mode:
        for report in reports:
            for value in (
                report["first_activity_unix_time"],
                report["last_activity_unix_time"],
            ):
                if value is not None:
                    swap_seconds.append(float(value))
    else:
        for r in responses:
            for s in r.get("swaps") or []:
                if s.get("timestamp"):
                    swap_seconds.append(_parse_iso_seconds(s["timestamp"]))
    comparison_window_seconds = (
        max(_MIN_WINDOW_SECONDS, max(swap_seconds) - min(swap_seconds))
        if len(swap_seconds) >= 2
        else _DEFAULT_WINDOW_SECONDS
    )

    first_buy_seconds = [
        _parse_iso_seconds(s["first_buy_at"])
        for s in signals_list
        if s.get("first_buy_at")
    ]
    t0 = min(first_buy_seconds) if first_buy_seconds else 0.0

    features_by_run = {
        s["run_id"]: (
            s.pop("_canonical_features")
            if canonical_mode
            else _scorer_features(s, t0)
        )
        for s in signals_list
    }

    pairs: list[dict[str, Any]] = []
    for i in range(len(signals_list)):
        for j in range(i + 1, len(signals_list)):
            a, b = signals_list[i], signals_list[j]
            score = clustering.pair_similarity(
                features_by_run[a["run_id"]],
                features_by_run[b["run_id"]],
                comparison_window_seconds,
            )
            shared = sorted(
                set(a["distinct_tokens_touched"]) & set(b["distinct_tokens_touched"])
            )
            shared_counterparties = sorted(
                set(a.get("counterparties", []))
                & set(b.get("counterparties", []))
            )
            pairs.append(
                {
                    "wallet_a_run_id": a["run_id"],
                    "wallet_b_run_id": b["run_id"],
                    "wallet_a_address": a["wallet_address"],
                    "wallet_b_address": b["wallet_address"],
                    "score": score,
                    "band": clustering.score_band_label(score),
                    "shared_tokens": shared,
                    "shared_counterparties": shared_counterparties,
                    "note": clustering._build_vyvod(score, shared),
                }
            )

    return {
        "wallets": signals_list,
        "comparison_window_seconds": comparison_window_seconds,
        "pairs": pairs,
        "is_cluster_proof": False,
        "signal_basis": (
            "canonical_native_activity_ledger"
            if canonical_mode
            else "legacy_mock_fixture"
        ),
        "note": (
            (
                "Probabilistic similarity over provider-free canonical native "
                "activity ledgers only, not proof of common ownership. The "
                "scorer uses activity timing, verified TON flow, and observed "
                "counterparty overlap; it does not claim full history."
                if canonical_mode
                else "Probabilistic behavioral similarity only, not proof of common "
                "ownership. Legacy mock-fixture comparison remains isolated from "
                "the production canonical-ledger path."
            )
        ),
    }


def _derive_canonical_wallet_signals(
    run_response: dict[str, Any],
    report: dict[str, Any],
) -> dict[str, Any]:
    incoming = report["incoming_activity_count"]
    outgoing = report["outgoing_activity_count"]
    outgoing_nanoton = Decimal(report["outgoing_nanoton"])
    mean_outgoing_ton = (
        outgoing_nanoton / Decimal(outgoing) / Decimal(1_000_000_000)
        if outgoing
        else _ZERO
    )
    net_ton = (
        Decimal(report["incoming_nanoton"])
        - Decimal(report["outgoing_nanoton"])
    ) / Decimal(1_000_000_000)
    first_at = report["first_activity_unix_time"]
    first_iso = (
        datetime.fromtimestamp(first_at, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
        if first_at is not None
        else None
    )
    counterparties = report["counterparties"]
    activity_count = report["canonical_activity_count"]
    return {
        "run_id": run_response["run_id"],
        "wallet_address": report["wallet_account_canonical"],
        "data_mode": "real",
        "ton_balance": "0",
        "portfolio_value_usd": None,
        "distinct_tokens_touched": [
            f"ton_native_asset_v1|{report['network']}"
        ] if activity_count else [],
        "buy_swap_count": 0,
        "sell_swap_count": 0,
        "avg_ton_per_buy_swap": None,
        "first_buy_at": first_iso,
        "signal_basis": "canonical_native_activity_ledger",
        "canonical_ledger_digest_sha256": report[
            "canonical_ledger_digest_sha256"
        ],
        "canonical_activity_count": activity_count,
        "incoming_activity_count": incoming,
        "outgoing_activity_count": outgoing,
        "counterparties": counterparties,
        "warnings": [
            "Legacy swap and current-balance fields are intentionally blank on "
            "the production canonical-ledger clustering path."
        ],
        "_canonical_features": {
            "buy_time_offset_s": float(first_at or 0),
            "avg_buy_price_usd": float(mean_outgoing_ton),
            "common_tokens": counterparties,
            "sold_fraction": (
                outgoing / (incoming + outgoing)
                if incoming + outgoing
                else 0.0
            ),
            "ton_balance": float(net_ton),
            "portfolio_value_usd": float(activity_count),
        },
    }
