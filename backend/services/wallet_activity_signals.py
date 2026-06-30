"""Rule-based, evidence-backed signals derived from a wallet ingestion run.

This is an *evidence signal layer*, not a risk score. Each signal is a
transparent, rule-based heuristic indicator over the run's already-ingested
rows; it carries the exact evidence it is based on, a confidence level driven
by how much data supports it, and hedged language. The layer never emits a
single opaque "risk score", a verdict, or any claim about a real-world person,
identity, ownership, intent, or fraud. Wallet addresses are treated only as
pseudonymous technical identifiers. A clean wallet correctly produces no
signals; weak data is reported explicitly as insufficient evidence rather than
silently skipped.

Every rule is a pure function of the public run-response dict, so the set is
easy to unit-test and audit. The endpoint layer only fetches the persisted run
and calls :func:`derive_run_signals`.
"""

from __future__ import annotations

from typing import Any, Callable

LAYER_NOTE = (
    "Evidence signals are heuristic, rule-based indicators computed only from "
    "this run's ingested on-chain data. They are not a risk score, a verdict, "
    "or proof of ownership, intent, identity, or fraud. Wallet addresses are "
    "pseudonymous technical identifiers. Each signal lists the exact evidence "
    "it is based on and a confidence level; an empty result means no rule "
    "matched, not that the wallet is verified safe."
)


def _confidence_from_sample(sample: int, low_max: int, medium_max: int) -> str:
    """Confidence reflects evidence volume, not how extreme the pattern is.

    A very concentrated pattern observed over only a handful of rows is still
    low confidence, because the sample is too small to be reliable.
    """
    if sample <= low_max:
        return "low"
    if sample <= medium_max:
        return "medium"
    return "high"


def _signal(code: str, **fields: Any) -> dict:
    return {"kind": "signal", "code": code, **fields}


def _insufficient(code: str, reason: str) -> dict:
    return {"kind": "insufficient", "code": code, "reason": reason}


def _rule_single_counterparty_dominance(run: dict) -> dict | None:
    """Most transfers involve one pseudonymous counterparty address."""
    transfers = run.get("transfers") or []
    if not transfers:
        return _insufficient(
            "single_counterparty_dominance",
            "No transfer data was ingested for this run.",
        )

    counts: dict[str, int] = {}
    for transfer in transfers:
        counterparty = transfer.get("counterparty")
        if counterparty:
            counts[counterparty] = counts.get(counterparty, 0) + 1

    total = sum(counts.values())
    if total < 3:
        return _insufficient(
            "single_counterparty_dominance",
            f"Only {total} transfer(s) with a known counterparty; "
            "insufficient evidence to assess concentration.",
        )

    top_counterparty, top_count = max(counts.items(), key=lambda kv: kv[1])
    share = top_count / total
    if share <= 0.5:
        return None

    pct = round(share * 100, 1)
    return _signal(
        "single_counterparty_dominance",
        title="Single-counterparty dominance",
        confidence=_confidence_from_sample(total, low_max=4, medium_max=9),
        observation=(
            f"{top_count} of {total} transfers with a known counterparty "
            f"involve one pseudonymous address ({pct}%)."
        ),
        evidence={
            "counterparty": top_counterparty,
            "transfer_count": top_count,
            "total_with_counterparty": total,
            "share": round(share, 4),
        },
        note=(
            "Repeated interaction with a single pseudonymous address accounts "
            "for most transfers. This is a possible behavioral pattern and a "
            "heuristic indicator only -- it can reflect an exchange deposit "
            "address, a service, or ordinary usage, and is not proof of "
            "ownership, intent, or fraud."
        ),
    )


def _rule_high_outflow_concentration(run: dict) -> dict | None:
    """Outgoing transfers are concentrated toward one counterparty address."""
    outgoing = [
        transfer
        for transfer in run.get("transfers") or []
        if transfer.get("direction") == "out" and transfer.get("counterparty")
    ]
    if len(outgoing) < 3:
        return _insufficient(
            "high_outflow_concentration",
            f"Only {len(outgoing)} outgoing transfer(s) with a known "
            "counterparty (transfer direction is often unavailable on-chain); "
            "insufficient evidence to assess outflow concentration.",
        )

    counts: dict[str, int] = {}
    for transfer in outgoing:
        counterparty = transfer["counterparty"]
        counts[counterparty] = counts.get(counterparty, 0) + 1

    total = len(outgoing)
    top_counterparty, top_count = max(counts.items(), key=lambda kv: kv[1])
    share = top_count / total
    if share <= 0.5:
        return None

    pct = round(share * 100, 1)
    return _signal(
        "high_outflow_concentration",
        title="High outflow concentration",
        confidence=_confidence_from_sample(total, low_max=4, medium_max=9),
        observation=(
            f"{top_count} of {total} outgoing transfers go to one "
            f"pseudonymous address ({pct}%)."
        ),
        evidence={
            "counterparty": top_counterparty,
            "outgoing_transfer_count": top_count,
            "total_outgoing": total,
            "share": round(share, 4),
        },
        note=(
            "Outgoing transfers are concentrated toward a single pseudonymous "
            "address. This is a possible pattern and a heuristic indicator "
            "only -- not proof of ownership, intent, or fraud."
        ),
    )


def _rule_failed_transaction_ratio(run: dict) -> dict | None:
    """An elevated share of transactions in the run failed."""
    transactions = run.get("transactions") or []
    total = len(transactions)
    if total < 3:
        return _insufficient(
            "failed_transaction_ratio",
            f"Only {total} transaction(s) ingested; insufficient evidence to "
            "assess the failure rate.",
        )

    failed = sum(1 for tx in transactions if tx.get("success") == "failed")
    share = failed / total
    if share <= 0.1:
        return None

    pct = round(share * 100, 1)
    return _signal(
        "failed_transaction_ratio",
        title="Elevated failed-transaction ratio",
        confidence=_confidence_from_sample(total, low_max=5, medium_max=19),
        observation=f"{failed} of {total} transactions failed ({pct}%).",
        evidence={"failed": failed, "total": total, "share": round(share, 4)},
        note=(
            "An elevated share of transactions failed. This is a heuristic "
            "indicator that often reflects slippage, expired messages, or "
            "contract reverts; it is not by itself evidence of malicious "
            "activity."
        ),
    )


def _rule_many_distinct_jettons(run: dict) -> dict | None:
    """The wallet holds many distinct non-TON jettons (airdrop/spam exposure)."""
    balances = run.get("balances") or []
    if not balances:
        return _insufficient(
            "many_distinct_jettons",
            "No balance data was ingested for this run.",
        )

    count = sum(
        1 for balance in balances if (balance.get("asset") or "").upper() != "TON"
    )
    if count <= 10:
        return None

    return _signal(
        "many_distinct_jettons",
        title="Many distinct jettons held",
        confidence=_confidence_from_sample(count, low_max=20, medium_max=50),
        observation=f"The wallet holds {count} distinct non-TON jettons.",
        evidence={"distinct_jetton_count": count},
        note=(
            "Holding many distinct jettons is a heuristic indicator that often "
            "reflects airdrops or spam tokens received without action, and is "
            "not by itself a risk indicator."
        ),
    )


# Ordered so output is deterministic and the evaluated list is stable.
_RULES: list[Callable[[dict], dict | None]] = [
    _rule_single_counterparty_dominance,
    _rule_high_outflow_concentration,
    _rule_failed_transaction_ratio,
    _rule_many_distinct_jettons,
]

_RULE_CODES = [
    "single_counterparty_dominance",
    "high_outflow_concentration",
    "failed_transaction_ratio",
    "many_distinct_jettons",
]


def derive_run_signals(run: dict) -> dict[str, Any]:
    """Return evidence signals derived from one wallet ingestion run response."""
    signals: list[dict] = []
    insufficient: list[dict] = []
    for rule in _RULES:
        result = rule(run)
        if result is None:
            continue
        if result["kind"] == "signal":
            signals.append({k: v for k, v in result.items() if k != "kind"})
        else:
            insufficient.append({"code": result["code"], "reason": result["reason"]})

    return {
        "run_id": run.get("run_id"),
        "wallet_address": run.get("wallet_address"),
        "is_risk_score": False,
        "evaluated": list(_RULE_CODES),
        "signals": signals,
        "insufficient_evidence": insufficient,
        "note": LAYER_NOTE,
    }
