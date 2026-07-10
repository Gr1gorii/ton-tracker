"""Deterministic multi-run merge of immutable native activity ledgers."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from models import (
    WalletIngestionRun,
    WalletNativeActivityLedger,
    WalletTraceEvidenceCapture,
)
from services.wallet_native_activity_ledger import _revalidate_ledger


NATIVE_ACTIVITY_MERGE_CONTRACT_VERSION = "ton_native_activity_merge_v1"


class WalletNativeActivityMergeConflict(ValueError):
    """Selected runs cannot form one coherent native activity merge."""


def merge_wallet_native_activity_ledgers(
    target_run_id: int,
    run_ids: list[int],
    session: Session,
) -> dict[str, Any]:
    if (
        not isinstance(run_ids, list)
        or not 2 <= len(run_ids) <= 50
        or any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in run_ids)
        or len(set(run_ids)) != len(run_ids)
        or target_run_id not in run_ids
    ):
        raise WalletNativeActivityMergeConflict(
            "Select 2-50 unique positive run ids including the target run."
        )
    selected_ids = sorted(run_ids)
    runs = list(
        session.scalars(
            select(WalletIngestionRun)
            .where(WalletIngestionRun.id.in_(selected_ids))
            .order_by(WalletIngestionRun.id)
        )
    )
    if [run.id for run in runs] != selected_ids:
        raise WalletNativeActivityMergeConflict("One or more selected runs do not exist.")
    target = next(run for run in runs if run.id == target_run_id)
    identity = (target.wallet_network, target.wallet_address_canonical)
    if (
        target.data_mode != "real"
        or target.wallet_identity_status != "network_scoped"
        or identity[0] not in ("ton-mainnet", "ton-testnet")
        or not isinstance(identity[1], str)
        or any(
            run.data_mode != "real"
            or run.wallet_identity_status != "network_scoped"
            or (run.wallet_network, run.wallet_address_canonical) != identity
            for run in runs
        )
    ):
        raise WalletNativeActivityMergeConflict(
            "Selected runs do not share one eligible wallet/network identity."
        )

    sources = []
    merged = []
    for run in runs:
        ledgers = list(
            session.scalars(
                select(WalletNativeActivityLedger)
                .join(WalletTraceEvidenceCapture)
                .where(WalletTraceEvidenceCapture.run_id == run.id)
                .options(
                    selectinload(WalletNativeActivityLedger.rows),
                    selectinload(WalletNativeActivityLedger.capture).selectinload(
                        WalletTraceEvidenceCapture.captured_via_transaction
                    ),
                )
                .order_by(WalletNativeActivityLedger.id)
            )
        )
        if not ledgers:
            raise WalletNativeActivityMergeConflict(
                f"Selected run {run.id} has no immutable native activity ledger."
            )
        for ledger in ledgers:
            anchor_transaction = ledger.capture.captured_via_transaction
            transaction_hash = anchor_transaction.transaction_hash_canonical
            if not isinstance(transaction_hash, str):
                raise WalletNativeActivityMergeConflict(
                    "A selected ledger lost its canonical capture anchor."
                )
            validated = _revalidate_ledger(
                ledger, run.id, transaction_hash, session
            )
            sources.append(
                {
                    "run_id": run.id,
                    "ledger_id": validated["ledger_id"],
                    "capture_id": validated["capture_id"],
                    "activity_count": validated["activity_count"],
                    "evidence_digest_sha256": validated[
                        "evidence_digest_sha256"
                    ],
                }
            )
            for activity in validated["activities"]:
                merged.append(
                    {
                        "source_run_id": run.id,
                        "source_ledger_id": validated["ledger_id"],
                        **activity,
                    }
                )
    merged.sort(
        key=lambda row: (
            row["unix_time"],
            int(row["created_logical_time"], 10),
            row["transaction_hash"],
            row["message_hash"],
            row["source_run_id"],
            row["source_ledger_id"],
        )
    )
    for merge_index, row in enumerate(merged):
        row["merge_index"] = merge_index
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in merged:
        grouped.setdefault(row["activity_identity_key"], []).append(row)
    duplicate_groups = [
        {
            "activity_identity_key": key,
            "occurrence_count": len(rows),
            "source_run_ids": sorted({row["source_run_id"] for row in rows}),
            "merge_indexes": [row["merge_index"] for row in rows],
        }
        for key, rows in sorted(grouped.items())
        if len(rows) > 1
    ]
    document = {
        "contract_version": NATIVE_ACTIVITY_MERGE_CONTRACT_VERSION,
        "target_run_id": target_run_id,
        "selected_run_ids": selected_ids,
        "sources": sources,
        "activities": merged,
        "duplicate_groups": duplicate_groups,
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
        "network": identity[0],
        "wallet_account_canonical": identity[1],
        "source_ledger_count": len(sources),
        "merged_activity_count": len(merged),
        "duplicate_group_count": len(duplicate_groups),
        "merge_digest_sha256": digest,
        "activity_merge_applied": True,
        "chronological_order_applied": True,
        "cross_run_deduplication_applied": False,
        "duplicates_retained": True,
        "establishes_complete_wallet_history": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "message": (
            "Selected immutable native ledgers were merged in deterministic "
            "chronological order. Duplicate identities remain visible and are "
            "not removed in this contract."
        ),
    }


__all__ = [
    "NATIVE_ACTIVITY_MERGE_CONTRACT_VERSION",
    "WalletNativeActivityMergeConflict",
    "merge_wallet_native_activity_ledgers",
]
