"""Canonical provider-free ledger view over proved native TON activity."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from models import (
    WalletIngestionRun,
    WalletNativeActivityLedger,
    WalletTraceBocTransaction,
    WalletTraceBocVerification,
    WalletTraceEvidenceCapture,
    WalletTransactionInclusionProof,
)
from services.wallet_native_activity_ledger import _revalidate_ledger
from services.wallet_transaction_inclusion_proof import _proof_response


CANONICAL_LEDGER_CONTRACT_VERSION = "ton_canonical_activity_ledger_v1"


class WalletCanonicalLedgerNotFound(LookupError):
    """No canonical proved ledger is available for the selected run."""


class WalletCanonicalLedgerConflict(ValueError):
    """Source ledgers or block proofs cannot form one canonical view."""


def get_wallet_canonical_ledger(
    run_id: int,
    session: Session,
) -> dict[str, Any]:
    run = session.get(WalletIngestionRun, run_id)
    if run is None:
        raise WalletCanonicalLedgerNotFound(
            f"Wallet ingestion run {run_id} not found"
        )
    if (
        run.data_mode != "real"
        or run.wallet_identity_status != "network_scoped"
        or run.wallet_network not in {"ton-mainnet", "ton-testnet"}
        or not isinstance(run.wallet_address_canonical, str)
    ):
        raise WalletCanonicalLedgerConflict(
            "Canonical ledger requires a real network-scoped wallet run."
        )
    ledgers = list(
        session.scalars(
            select(WalletNativeActivityLedger)
            .join(WalletTraceEvidenceCapture)
            .where(WalletTraceEvidenceCapture.run_id == run_id)
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
        raise WalletCanonicalLedgerNotFound(
            "No immutable native activity ledgers exist for this run."
        )

    sources = []
    occurrences = []
    for ledger in ledgers:
        anchor = ledger.capture.captured_via_transaction
        anchor_hash = anchor.transaction_hash_canonical
        if not isinstance(anchor_hash, str):
            raise WalletCanonicalLedgerConflict(
                "A source ledger lost its canonical transaction anchor."
            )
        validated = _revalidate_ledger(ledger, run_id, anchor_hash, session)
        proof_rows = list(
            session.scalars(
                select(WalletTransactionInclusionProof)
                .join(WalletTransactionInclusionProof.boc_transaction)
                .join(WalletTraceBocTransaction.verification)
                .where(WalletTraceBocVerification.capture_id == ledger.capture_id)
                .options(
                    selectinload(
                        WalletTransactionInclusionProof.boc_transaction
                    )
                )
                .order_by(WalletTransactionInclusionProof.id)
            )
        )
        proof_by_hash = {
            row.transaction_hash: _proof_response(row.boc_transaction)
            for row in proof_rows
        }
        activity_hashes = {
            activity["transaction_hash"] for activity in validated["activities"]
        }
        if not activity_hashes.issubset(proof_by_hash):
            raise WalletCanonicalLedgerConflict(
                "Every canonical activity requires a provider-free transaction "
                "block-inclusion proof."
            )
        sources.append(
            {
                "ledger_id": validated["ledger_id"],
                "capture_id": validated["capture_id"],
                "ledger_digest_sha256": validated["evidence_digest_sha256"],
                "transaction_inclusion_proof_digests": sorted(
                    proof_by_hash[value]["evidence_digest_sha256"]
                    for value in activity_hashes
                ),
            }
        )
        for activity in validated["activities"]:
            occurrences.append(
                {
                    **activity,
                    "source_ledger_id": validated["ledger_id"],
                    "source_capture_id": validated["capture_id"],
                    "transaction_inclusion_proof_digest_sha256": proof_by_hash[
                        activity["transaction_hash"]
                    ]["evidence_digest_sha256"],
                }
            )

    occurrences.sort(key=_activity_order)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in occurrences:
        grouped.setdefault(row["activity_identity_key"], []).append(row)
    activities = []
    resolutions = []
    for identity, rows in grouped.items():
        if any(_semantic(row) != _semantic(rows[0]) for row in rows[1:]):
            raise WalletCanonicalLedgerConflict(
                "Duplicate canonical activity identities have conflicting semantics."
            )
        winner = dict(rows[0])
        winner["canonical_index"] = len(activities)
        winner["occurrence_count"] = len(rows)
        winner["source_occurrences"] = [
            {
                "source_ledger_id": row["source_ledger_id"],
                "source_capture_id": row["source_capture_id"],
                "transaction_inclusion_proof_digest_sha256": row[
                    "transaction_inclusion_proof_digest_sha256"
                ],
            }
            for row in rows
        ]
        activities.append(winner)
        if len(rows) > 1:
            resolutions.append(
                {
                    "activity_identity_key": identity,
                    "occurrence_count": len(rows),
                    "canonical_source": winner["source_occurrences"][0],
                    "suppressed_sources": winner["source_occurrences"][1:],
                }
            )

    document = {
        "contract_version": CANONICAL_LEDGER_CONTRACT_VERSION,
        "run_id": str(run_id),
        "network": run.wallet_network,
        "wallet_account_canonical": run.wallet_address_canonical,
        "sources": sources,
        "activities": activities,
        "duplicate_resolutions": resolutions,
    }
    return {
        **document,
        "source_ledger_count": len(sources),
        "source_occurrence_count": len(occurrences),
        "canonical_activity_count": len(activities),
        "suppressed_occurrence_count": len(occurrences) - len(activities),
        "canonical_ledger_digest_sha256": _digest(document),
        "transaction_block_inclusion_required": True,
        "provider_free_revalidated": True,
        "cross_ledger_deduplication_applied": True,
        "native_ton_only": True,
        "establishes_complete_wallet_history": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "message": (
            "Canonical native TON activities are derived only from immutable "
            "ledgers whose transaction BOCs have stored block-inclusion proofs. "
            "This view is canonical within selected evidence, not proof of full "
            "wallet history."
        ),
    }


def build_wallet_canonical_report(run_id: int, session: Session) -> dict[str, Any]:
    ledger = get_wallet_canonical_ledger(run_id, session)
    incoming = [row for row in ledger["activities"] if row["direction"] == "incoming"]
    outgoing = [row for row in ledger["activities"] if row["direction"] == "outgoing"]
    self_rows = [row for row in ledger["activities"] if row["direction"] == "self"]
    counterparties = sorted(
        {row["counterparty_account_canonical"] for row in ledger["activities"]}
    )
    report = {
        "contract_version": "ton_canonical_activity_report_v1",
        "run_id": ledger["run_id"],
        "network": ledger["network"],
        "wallet_account_canonical": ledger["wallet_account_canonical"],
        "canonical_ledger_digest_sha256": ledger[
            "canonical_ledger_digest_sha256"
        ],
        "canonical_activity_count": ledger["canonical_activity_count"],
        "incoming_activity_count": len(incoming),
        "outgoing_activity_count": len(outgoing),
        "self_activity_count": len(self_rows),
        "incoming_nanoton": str(sum(int(row["amount_base_units"]) for row in incoming)),
        "outgoing_nanoton": str(sum(int(row["amount_base_units"]) for row in outgoing)),
        "self_nanoton": str(sum(int(row["amount_base_units"]) for row in self_rows)),
        "unique_counterparty_count": len(counterparties),
        "counterparties": counterparties,
        "first_activity_unix_time": min(
            (row["unix_time"] for row in ledger["activities"]),
            default=None,
        ),
        "last_activity_unix_time": max(
            (row["unix_time"] for row in ledger["activities"]),
            default=None,
        ),
        "native_ton_only": True,
        "establishes_complete_wallet_history": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
    }
    report["report_digest_sha256"] = _digest(report)
    return report


def _activity_order(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["unix_time"],
        int(row["created_logical_time"]),
        row["transaction_hash"],
        row["message_hash"],
        row["source_ledger_id"],
    )


def _semantic(row: dict[str, Any]) -> dict[str, Any]:
    ignored = {
        "ordinal",
        "source_ledger_id",
        "source_capture_id",
        "transaction_inclusion_proof_digest_sha256",
    }
    return {key: value for key, value in row.items() if key not in ignored}


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "CANONICAL_LEDGER_CONTRACT_VERSION",
    "WalletCanonicalLedgerConflict",
    "WalletCanonicalLedgerNotFound",
    "build_wallet_canonical_report",
    "get_wallet_canonical_ledger",
]
