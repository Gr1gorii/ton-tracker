"""Canonical cross-run deduplication over the deterministic native merge."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy.orm import Session

from services.wallet_native_activity_merge import (
    merge_wallet_native_activity_ledgers,
)


NATIVE_ACTIVITY_DEDUP_CONTRACT_VERSION = "ton_native_activity_dedup_v1"


class WalletNativeActivityDedupConflict(ValueError):
    """One activity identity mapped to conflicting verified semantics."""


def deduplicate_wallet_native_activity(
    target_run_id: int,
    run_ids: list[int],
    session: Session,
) -> dict[str, Any]:
    merged = merge_wallet_native_activity_ledgers(
        target_run_id, run_ids, session
    )
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in merged["activities"]:
        grouped.setdefault(row["activity_identity_key"], []).append(row)
    activities = []
    resolutions = []
    for identity_key, occurrences in grouped.items():
        winner = occurrences[0]
        winner_fingerprint = _semantic_fingerprint(winner)
        if any(
            _semantic_fingerprint(value) != winner_fingerprint
            for value in occurrences[1:]
        ):
            raise WalletNativeActivityDedupConflict(
                "Duplicate activity identity has conflicting verified semantics."
            )
        canonical = {
            key: value
            for key, value in winner.items()
            if key != "merge_index"
        }
        canonical["dedup_index"] = len(activities)
        canonical["occurrence_count"] = len(occurrences)
        canonical["source_occurrences"] = [
            {
                "source_run_id": value["source_run_id"],
                "source_ledger_id": value["source_ledger_id"],
                "merge_index": value["merge_index"],
            }
            for value in occurrences
        ]
        activities.append(canonical)
        if len(occurrences) > 1:
            resolutions.append(
                {
                    "activity_identity_key": identity_key,
                    "winner": canonical["source_occurrences"][0],
                    "suppressed": canonical["source_occurrences"][1:],
                    "suppressed_count": len(occurrences) - 1,
                    "selection_rule": "first_deterministic_merge_occurrence",
                }
            )
    suppressed_count = merged["merged_activity_count"] - len(activities)
    document = {
        "contract_version": NATIVE_ACTIVITY_DEDUP_CONTRACT_VERSION,
        "target_run_id": target_run_id,
        "selected_run_ids": merged["selected_run_ids"],
        "source_merge_digest_sha256": merged["merge_digest_sha256"],
        "activities": activities,
        "resolutions": resolutions,
    }
    digest = hashlib.sha256(
        json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return {
        **document,
        "network": merged["network"],
        "wallet_account_canonical": merged["wallet_account_canonical"],
        "source_ledger_count": merged["source_ledger_count"],
        "merged_activity_count": merged["merged_activity_count"],
        "deduplicated_activity_count": len(activities),
        "suppressed_occurrence_count": suppressed_count,
        "resolution_count": len(resolutions),
        "dedup_digest_sha256": digest,
        "activity_merge_applied": True,
        "cross_run_deduplication_applied": True,
        "canonical_winner_rule_applied": True,
        "duplicates_retained": False,
        "establishes_complete_wallet_history": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "message": (
            "Repeated content-addressed native activities were collapsed using "
            "the first deterministic merge occurrence. Every suppressed source "
            "remains visible in resolution evidence."
        ),
    }


def _semantic_fingerprint(row: dict[str, Any]) -> dict[str, Any]:
    ignored = {"source_run_id", "source_ledger_id", "merge_index", "ordinal"}
    return {key: value for key, value in row.items() if key not in ignored}


__all__ = [
    "NATIVE_ACTIVITY_DEDUP_CONTRACT_VERSION",
    "WalletNativeActivityDedupConflict",
    "deduplicate_wallet_native_activity",
]
