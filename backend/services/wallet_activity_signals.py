"""Rule-based, evidence-backed signals derived from a wallet ingestion run.

This is an *evidence signal layer*, not a risk score. Each signal is a
transparent, rule-based observation over the run's already-ingested rows; it
carries the exact evidence it is based on and hedged language. The layer never
emits a single opaque "risk score", a verdict, or proof of wrongdoing —
consistent with the project's data-honesty doctrine. A clean wallet correctly
produces no signals.

Every rule is a pure function of the public run-response dict, so the set is
easy to unit-test and audit. The endpoint layer only fetches the persisted run
and calls :func:`derive_run_signals`.
"""

from __future__ import annotations

from typing import Any, Callable

LAYER_NOTE = (
    "Evidence signals are heuristic, rule-based observations from this run's "
    "ingested data only. They are not a risk score, a verdict, or proof of "
    "wrongdoing; each signal lists the exact evidence it is based on, and an "
    "empty result means no rule matched, not that the wallet is verified safe."
)


def _strength_for_share(share: float) -> str:
    if share > 0.8:
        return "strong"
    if share > 0.6:
        return "moderate"
    return "weak"


def _rule_transfer_counterparty_concentration(run: dict) -> dict | None:
    """Most transfers (with a known counterparty) involve one address."""
    counts: dict[str, int] = {}
    for transfer in run.get("transfers") or []:
        counterparty = transfer.get("counterparty")
        if counterparty:
            counts[counterparty] = counts.get(counterparty, 0) + 1

    total = sum(counts.values())
    if total < 3:
        return None
    top_counterparty, top_count = max(counts.items(), key=lambda kv: kv[1])
    share = top_count / total
    if share <= 0.4:
        return None

    pct = round(share * 100, 1)
    return {
        "code": "transfer_counterparty_concentration",
        "title": "Transfer counterparty concentration",
        "strength": _strength_for_share(share),
        "observation": (
            f"{top_count} of {total} transfers with a known counterparty "
            f"involve one address ({pct}%)."
        ),
        "evidence": {
            "counterparty": top_counterparty,
            "transfer_count": top_count,
            "total_with_counterparty": total,
            "share": round(share, 4),
        },
        "note": (
            "A large share of transfers involve a single counterparty. This "
            "can reflect an exchange deposit address, a service, or ordinary "
            "usage — a behavioral signal, not proof of risk."
        ),
    }


def _rule_failed_transaction_ratio(run: dict) -> dict | None:
    """An elevated share of transactions in the run failed."""
    transactions = run.get("transactions") or []
    total = len(transactions)
    if total < 3:
        return None
    failed = sum(1 for tx in transactions if tx.get("success") == "failed")
    share = failed / total
    if share <= 0.1:
        return None

    pct = round(share * 100, 1)
    return {
        "code": "failed_transaction_ratio",
        "title": "Elevated failed-transaction ratio",
        "strength": _strength_for_share(share),
        "observation": (
            f"{failed} of {total} transactions failed ({pct}%)."
        ),
        "evidence": {
            "failed": failed,
            "total": total,
            "share": round(share, 4),
        },
        "note": (
            "An elevated share of transactions failed. This often reflects "
            "slippage, expired messages, or contract reverts; it is not by "
            "itself evidence of malicious activity."
        ),
    }


def _rule_many_distinct_jettons(run: dict) -> dict | None:
    """The wallet holds many distinct non-TON jettons (airdrop/spam exposure)."""
    jettons = [
        balance
        for balance in run.get("balances") or []
        if (balance.get("asset") or "").upper() != "TON"
    ]
    count = len(jettons)
    if count <= 10:
        return None

    strength = "strong" if count > 50 else "moderate" if count > 25 else "weak"
    return {
        "code": "many_distinct_jettons",
        "title": "Many distinct jettons held",
        "strength": strength,
        "observation": f"The wallet holds {count} distinct non-TON jettons.",
        "evidence": {"distinct_jetton_count": count},
        "note": (
            "Holding many distinct jettons often reflects airdrops or spam "
            "tokens received without action, and is not by itself a risk "
            "indicator."
        ),
    }


# Ordered so output is deterministic and the evaluated list is stable.
_RULES: list[Callable[[dict], dict | None]] = [
    _rule_transfer_counterparty_concentration,
    _rule_failed_transaction_ratio,
    _rule_many_distinct_jettons,
]

_RULE_CODES = [
    "transfer_counterparty_concentration",
    "failed_transaction_ratio",
    "many_distinct_jettons",
]


def derive_run_signals(run: dict) -> dict[str, Any]:
    """Return evidence signals derived from one wallet ingestion run response."""
    signals = [signal for rule in _RULES if (signal := rule(run)) is not None]
    return {
        "run_id": run.get("run_id"),
        "wallet_address": run.get("wallet_address"),
        "is_risk_score": False,
        "evaluated": list(_RULE_CODES),
        "signals": signals,
        "note": LAYER_NOTE,
    }
