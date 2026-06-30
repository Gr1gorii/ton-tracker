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

    signals_list = [derive_wallet_signals(r) for r in responses]

    swap_seconds: list[float] = []
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
        s["run_id"]: _scorer_features(s, t0) for s in signals_list
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
            pairs.append(
                {
                    "wallet_a_run_id": a["run_id"],
                    "wallet_b_run_id": b["run_id"],
                    "wallet_a_address": a["wallet_address"],
                    "wallet_b_address": b["wallet_address"],
                    "score": score,
                    "band": clustering.score_band_label(score),
                    "shared_tokens": shared,
                    "note": clustering._build_vyvod(score, shared),
                }
            )

    return {
        "wallets": signals_list,
        "comparison_window_seconds": comparison_window_seconds,
        "pairs": pairs,
        "is_cluster_proof": False,
        "note": (
            "Probabilistic behavioral similarity only, not proof of common "
            "ownership. The entry-price signal is TON-denominated (average "
            "TON spent per buy swap from on-chain swap rows), not a "
            "historical or current USD price. portfolio_value_usd reflects "
            "current holdings priced now, not value at the time of any trade."
        ),
    }
