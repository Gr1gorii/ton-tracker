"""Wallet clustering service.

IMPORTANT framing: this module produces *probabilistic similarity signals*, not
proof of common ownership. On-chain wallets that behave similarly may belong to
one actor, to coordinated actors, or to unrelated traders reacting to the same
market event. All public-facing language must stay hedged ("possible cluster",
"likely related behavior", "not proof of common ownership").

The scoring is intentionally simple and transparent for v0.1. Each pair of
wallets is compared across a handful of behavioral features; the per-feature
similarities are weighted and combined into a 0-100 score. Wallets that already
carry a ``group`` tag in the mock data are grouped together and summarized.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Iterable

# Score band thresholds (inclusive lower bound).
SCORE_BANDS = [
    (0, "weak/no signal"),
    (26, "weak similarity"),
    (51, "possible cluster"),
    (71, "likely related behavior"),
    (86, "very high similarity, still not proof"),
]

# Relative weights for each behavioral similarity feature. They do not need to
# sum to 1; the weighted average normalizes by the total weight.
FEATURE_WEIGHTS = {
    "buy_time": 0.20,
    "entry_price": 0.20,
    "held_tokens": 0.20,
    "partial_sell_behavior": 0.15,
    "ton_balance": 0.10,
    "portfolio_value": 0.15,
}


def score_band_label(score: float) -> str:
    label = SCORE_BANDS[0][1]
    for threshold, text in SCORE_BANDS:
        if score >= threshold:
            label = text
    return label


def _ratio_similarity(a: float, b: float) -> float:
    """Similarity of two non-negative magnitudes, in [0, 1].

    1.0 when equal, approaching 0.0 as they diverge. Uses the ratio of the
    smaller to the larger so it is scale-independent.
    """
    a, b = abs(a), abs(b)
    if a == 0 and b == 0:
        return 1.0
    hi = max(a, b)
    if hi == 0:
        return 1.0
    return min(a, b) / hi


def _time_similarity(t_a: float, t_b: float, window_seconds: float) -> float:
    """Closeness of two buy timestamps relative to the analysis window."""
    if window_seconds <= 0:
        return 1.0 if t_a == t_b else 0.0
    diff = abs(t_a - t_b)
    return max(0.0, 1.0 - diff / window_seconds)


def _jaccard(set_a: Iterable[str], set_b: Iterable[str]) -> float:
    a, b = set(set_a), set(set_b)
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _partial_sell_similarity(frac_a: float, frac_b: float) -> float:
    """Similarity of sold fractions (0 = never sold, 1 = full exit)."""
    return 1.0 - abs(frac_a - frac_b)


def pair_similarity(w_a: dict, w_b: dict, window_seconds: float) -> float:
    """Return a 0-100 behavioral similarity score for a pair of wallets.

    Each wallet dict is expected to expose: ``buy_time_offset_s``,
    ``avg_buy_price_usd``, ``common_tokens``, ``sold_fraction``,
    ``ton_balance``, ``portfolio_value_usd``.
    """
    features = {
        "buy_time": _time_similarity(
            w_a["buy_time_offset_s"], w_b["buy_time_offset_s"], window_seconds
        ),
        "entry_price": _ratio_similarity(
            w_a["avg_buy_price_usd"], w_b["avg_buy_price_usd"]
        ),
        "held_tokens": _jaccard(w_a["common_tokens"], w_b["common_tokens"]),
        "partial_sell_behavior": _partial_sell_similarity(
            w_a["sold_fraction"], w_b["sold_fraction"]
        ),
        "ton_balance": _ratio_similarity(
            w_a["ton_balance"], w_b["ton_balance"]
        ),
        "portfolio_value": _ratio_similarity(
            w_a["portfolio_value_usd"], w_b["portfolio_value_usd"]
        ),
    }

    total_weight = sum(FEATURE_WEIGHTS.values())
    weighted = sum(features[k] * FEATURE_WEIGHTS[k] for k in features)
    score01 = weighted / total_weight if total_weight else 0.0
    return round(score01 * 100, 2)


@dataclass
class WalletGroup:
    group_name: str
    group_type: str
    wallet_list: list[str]
    shared_tokens: list[str]
    average_connected_score: float
    reason_summary: str
    vyvod: str = field(metadata={"alias": "Вывод"})

    def to_dict(self) -> dict:
        return {
            "group_name": self.group_name,
            "group_type": self.group_type,
            "wallet_list": self.wallet_list,
            "shared_tokens": self.shared_tokens,
            "average_connected_score": self.average_connected_score,
            "reason_summary": self.reason_summary,
            "Вывод": self.vyvod,
        }


# Human-readable group type per band, used when summarizing a group.
def _group_type_for_score(score: float) -> str:
    if score >= 86:
        return "very high similarity (not proof)"
    if score >= 71:
        return "likely related behavior"
    if score >= 51:
        return "possible cluster"
    if score >= 26:
        return "weak similarity"
    return "weak/no signal"


def _build_vyvod(score: float, shared_tokens: list[str]) -> str:
    """Compose a hedged Russian conclusion for a group."""
    band = _group_type_for_score(score)
    band_ru = {
        "very high similarity (not proof)": "очень высокая схожесть поведения",
        "likely related behavior": "вероятно связанное поведение",
        "possible cluster": "возможная группа",
        "weak similarity": "слабая схожесть",
        "weak/no signal": "слабый сигнал или его отсутствие",
    }[band]
    tokens_part = (
        f" и похожий набор токенов ({', '.join(shared_tokens)})"
        if shared_tokens
        else ""
    )
    return (
        f"Кошельки демонстрируют {band_ru} из-за близкого времени покупки, "
        f"схожих цен входа{tokens_part}. Это поведенческий сигнал, "
        f"а не доказательство общего владения."
    )


def _shared_tokens(wallets: list[dict]) -> list[str]:
    if not wallets:
        return []
    common = set(wallets[0]["common_tokens"])
    for w in wallets[1:]:
        common &= set(w["common_tokens"])
    return sorted(common)


def build_groups(wallets: list[dict], window_seconds: float) -> list[dict]:
    """Group wallets by their mock ``group`` tag and summarize each cluster.

    Wallets tagged ``"none"`` (or missing a tag) are treated as ungrouped and
    excluded from cluster output. Within each group we compute the average
    pairwise similarity score to characterize the strength of the signal.
    """
    by_group: dict[str, list[dict]] = {}
    for w in wallets:
        tag = w.get("group") or "none"
        if tag == "none":
            continue
        by_group.setdefault(tag, []).append(w)

    groups: list[dict] = []
    for tag, members in sorted(by_group.items()):
        if len(members) < 2:
            # A single wallet is not a cluster; skip it.
            continue

        # Average of all unique pairwise similarity scores.
        pair_scores: list[float] = []
        for i in range(len(members)):
            for j in range(i + 1, len(members)):
                pair_scores.append(
                    pair_similarity(members[i], members[j], window_seconds)
                )
        avg_score = round(mean(pair_scores), 2) if pair_scores else 0.0

        shared = _shared_tokens(members)
        reason = (
            "Сгруппировано по схожести: время покупки, цена входа, "
            "набор токенов, поведение при продаже, баланс TON и стоимость "
            "портфеля. Средний балл схожести по парам = "
            f"{avg_score} ({score_band_label(avg_score)})."
        )

        group = WalletGroup(
            group_name=tag,
            group_type=_group_type_for_score(avg_score),
            wallet_list=[m["address"] for m in members],
            shared_tokens=shared,
            average_connected_score=avg_score,
            reason_summary=reason,
            vyvod=_build_vyvod(avg_score, shared),
        )
        groups.append(group.to_dict())

    return groups


def connected_score_for_wallet(
    target: dict, wallets: list[dict], window_seconds: float
) -> float:
    """Per-wallet connected score = best pairwise similarity to any peer.

    Reflects how strongly a wallet resembles its closest behavioral neighbor.
    Returns 0.0 for a lone wallet.
    """
    best = 0.0
    for other in wallets:
        if other["address"] == target["address"]:
            continue
        best = max(best, pair_similarity(target, other, window_seconds))
    return round(best, 2)
