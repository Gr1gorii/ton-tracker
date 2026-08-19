"""Content-addressed Wallet Case report over one pinned Activity revision."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from models import LOCAL_SINGLE_USER_SCOPE, WalletCase
from services.wallet_case_activity import (
    WalletCaseActivityInvalidCursor,
    WalletCaseActivityQuery,
    WalletCaseActivityScopeTooLarge,
    WalletCaseActivitySnapshotConflict,
    WalletCaseActivitySnapshotNotFound,
    WalletCaseActivityService,
)
from services.wallet_case_evidence import (
    CaseEvidenceNotFound,
    CaseEvidenceScopeTooLarge,
    CaseEvidenceService,
    CaseEvidenceSnapshotConflict,
    CaseEvidenceSnapshotNotFound,
    CaseEvidenceStoredConflict,
)
from wallet_case_report_schemas import case_report_content_hash


class WalletCaseReportNotFound(LookupError):
    code = "case_report_not_found"


class WalletCaseReportSnapshotNotFound(LookupError):
    code = "case_report_snapshot_not_found"


class WalletCaseReportConflict(RuntimeError):
    code = "case_report_conflict"


class WalletCaseReportScopeTooLarge(RuntimeError):
    code = "case_report_scope_too_large"


class WalletCaseReportService:
    def __init__(
        self,
        session: Session,
        *,
        owner_scope_id: str = LOCAL_SINGLE_USER_SCOPE,
    ) -> None:
        self.session = session
        self.owner_scope_id = owner_scope_id

    def build(
        self,
        case_public_id: str,
        *,
        snapshot_public_id: str | None,
    ) -> dict[str, Any]:
        wallet_case = self.session.scalar(
            select(WalletCase).where(
                WalletCase.owner_scope_id == self.owner_scope_id,
                WalletCase.public_id == case_public_id,
                WalletCase.archived_at.is_(None),
            )
        )
        if wallet_case is None:
            raise WalletCaseReportNotFound("Wallet Case not found.")

        try:
            activity = WalletCaseActivityService(
                self.session,
                owner_scope_id=self.owner_scope_id,
            ).list_activity(
                case_public_id,
                WalletCaseActivityQuery(
                    snapshot_public_id=snapshot_public_id,
                    limit=1,
                ),
            )
        except WalletCaseActivitySnapshotNotFound as exc:
            raise WalletCaseReportSnapshotNotFound(str(exc)) from exc
        except WalletCaseActivityScopeTooLarge as exc:
            raise WalletCaseReportScopeTooLarge(str(exc)) from exc
        except (
            WalletCaseActivitySnapshotConflict,
            WalletCaseActivityInvalidCursor,
        ) as exc:
            raise WalletCaseReportConflict(str(exc)) from exc

        snapshot = activity["snapshot"]
        if snapshot is None:
            return {
                "case_public_id": wallet_case.public_id,
                "snapshot_public_id": None,
                "report": None,
                "limitations": [{
                    "code": "not_synchronized",
                    "message": "Synchronize this Wallet Case before building a report.",
                }],
            }

        try:
            evidence = CaseEvidenceService(
                self.session,
                owner_scope_id=self.owner_scope_id,
            ).catalog(
                case_public_id,
                snapshot_public_id=snapshot["public_id"],
                # Runner/runtime readiness is deliberately excluded from the
                # immutable report. Only persisted, revalidated artifacts are
                # part of this content-addressed revision.
                runner_available=True,
            )
        except (CaseEvidenceNotFound, CaseEvidenceSnapshotNotFound) as exc:
            raise WalletCaseReportSnapshotNotFound(str(exc)) from exc
        except (CaseEvidenceSnapshotConflict, CaseEvidenceStoredConflict) as exc:
            raise WalletCaseReportConflict(str(exc)) from exc
        except CaseEvidenceScopeTooLarge as exc:
            raise WalletCaseReportScopeTooLarge(str(exc)) from exc
        if (
            evidence["snapshot"] is None
            or evidence["snapshot"]["public_id"] != snapshot["public_id"]
        ):
            raise WalletCaseReportConflict(
                "Report Activity and Evidence revisions do not share one snapshot."
            )

        activity_revision = {
            "aggregate": activity["aggregate"],
            "observed_period": activity["observed_period"],
        }
        activity_revision["digest_sha256"] = _digest(activity_revision)
        evidence_revision = _evidence_revision(evidence)
        canonical_gate = _canonical_gate(
            wallet_case=wallet_case,
            snapshot=snapshot,
            activity=activity,
            evidence=evidence_revision,
        )
        assurance = _assurance_level(
            wallet_case=wallet_case,
            evidence=evidence_revision,
            canonical=canonical_gate["eligible"],
        )
        limitations = _report_limitations(
            activity=activity,
            evidence=evidence_revision,
            assurance=assurance,
        )
        unverified_claims = _unverified_claims(
            canonical_gate=canonical_gate,
            activity=activity,
            evidence=evidence_revision,
        )
        report: dict[str, Any] = {
            "contract_version": "wallet_case_report_v1",
            "case_public_id": wallet_case.public_id,
            "snapshot_public_id": snapshot["public_id"],
            "assurance_level": assurance,
            "subject": {
                "network": wallet_case.network,
                "data_environment": wallet_case.data_environment,
                "wallet_account_canonical": wallet_case.canonical_wallet_key,
            },
            "snapshot": snapshot,
            "activity_revision": activity_revision,
            "evidence_revision": evidence_revision,
            "coverage": snapshot["coverage"],
            "gaps": activity["gaps"],
            "canonical_gate": canonical_gate,
            "limitations": limitations,
            "unverified_claims": unverified_claims,
            "truth_boundaries": {
                "establishes_complete_wallet_history": False,
                "eligible_for_cost_basis": False,
                "used_by_pnl": False,
                "includes_raw_provider_payloads": False,
                "provider_free_full_report_revalidation": False,
            },
        }
        content_hash = case_report_content_hash(report)
        report["public_id"] = f"rpt_{content_hash}"
        report["content_hash_sha256"] = content_hash
        return {
            "case_public_id": wallet_case.public_id,
            "snapshot_public_id": snapshot["public_id"],
            "report": report,
            "limitations": [],
        }


def _evidence_revision(catalog: dict[str, Any]) -> dict[str, Any]:
    rows = catalog["verifications"]
    strongest_by_activity: dict[str, dict[str, Any]] = {}
    for row in rows:
        current = strongest_by_activity.get(row["activity_public_id"])
        score = (row["progress"]["current"], row["status_version"], row["public_id"])
        if current is None or score > (
            current["progress"]["current"],
            current["status_version"],
            current["public_id"],
        ):
            strongest_by_activity[row["activity_public_id"]] = row

    selected = tuple(strongest_by_activity.values())
    projection = {
        "total_attempts": catalog["aggregate"]["total"],
        "returned_revalidated": len(rows),
        "history_truncated": catalog["truncated"],
        "verifications": sorted(
            (
                {
                    "public_id": row["public_id"],
                    "activity_public_id": row["activity_public_id"],
                    "status_version": row["status_version"],
                    "state": row["state"],
                    "progress": row["progress"]["current"],
                    "highest_evidence_level": row["highest_evidence_level"],
                    "result_digest_sha256": (
                        row["result"]["verification_digest_sha256"]
                        if row["result"] is not None
                        else None
                    ),
                    "updated_at": row["updated_at"],
                }
                for row in rows
            ),
            key=lambda item: item["public_id"],
        ),
    }
    return {
        "digest_sha256": _digest(projection),
        "total_attempts": projection["total_attempts"],
        "returned_revalidated": projection["returned_revalidated"],
        "history_truncated": projection["history_truncated"],
        "selected_activity_count": len(selected),
        "locally_verified_activity_count": sum(
            row["progress"]["current"] >= 2 for row in selected
        ),
        "chain_inclusion_proven_activity_count": sum(
            row["progress"]["current"] >= 3 for row in selected
        ),
        "native_ledger_activity_count": sum(
            row["progress"]["current"] == 4 for row in selected
        ),
    }


def _canonical_gate(
    *,
    wallet_case: WalletCase,
    snapshot: dict[str, Any],
    activity: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    aggregate = activity["aggregate"]
    coverage = snapshot["coverage"]
    transactions = aggregate["transactions"]
    unmet: list[str] = []
    if wallet_case.data_environment != "live":
        unmet.append("live_data_required")
    if snapshot["state"] != "succeeded":
        unmet.append("succeeded_snapshot_required")
    if aggregate["total_items"] == 0:
        unmet.append("activity_required")
    if (
        coverage["state"] != "bounded_complete"
        or coverage["unavailable_surfaces"]
        or coverage["incomplete_surfaces"]
    ):
        unmet.append("complete_coverage_required")
    if coverage["full_history_proven"] is not True:
        unmet.append("full_history_proof_required")
    if activity["gaps"]:
        unmet.append("activity_gaps_must_be_closed")
    if aggregate["conflicted_identity_count"]:
        unmet.append("identity_conflicts_must_be_resolved")
    if evidence["history_truncated"]:
        unmet.append("evidence_history_must_be_fully_revalidated")
    if evidence["chain_inclusion_proven_activity_count"] != transactions:
        unmet.append("every_transaction_must_be_chain_proven")
    if evidence["native_ledger_activity_count"] != transactions:
        unmet.append("every_transaction_needs_native_ledger")
    return {"eligible": not unmet, "unmet": unmet}


def _assurance_level(
    *,
    wallet_case: WalletCase,
    evidence: dict[str, Any],
    canonical: bool,
) -> str:
    if canonical:
        return "canonical"
    if wallet_case.data_environment == "demo":
        return "observed"
    if evidence["locally_verified_activity_count"]:
        return "partially_verified"
    return "normalized"


def _report_limitations(
    *,
    activity: dict[str, Any],
    evidence: dict[str, Any],
    assurance: str,
) -> list[dict[str, str]]:
    items = list(activity["limitations"])
    if assurance == "observed":
        items.append({
            "code": "observed_demo_report",
            "message": "This report summarizes deterministic demo observations, not chain data.",
        })
    if evidence["history_truncated"]:
        items.append({
            "code": "evidence_history_truncated",
            "message": "Only the newest 50 evidence attempts were revalidated for this report revision.",
        })
    items.append({
        "code": "selective_evidence_report",
        "message": "Only explicitly selected transactions have evidence verification attempts.",
    })
    if assurance != "canonical":
        items.append({
            "code": "canonical_gate_locked",
            "message": "Canonical assurance remains locked until every published hard gate is met.",
        })
    return _distinct_messages(items)


def _unverified_claims(
    *,
    canonical_gate: dict[str, Any],
    activity: dict[str, Any],
    evidence: dict[str, Any],
) -> list[dict[str, Any]]:
    transactions = activity["aggregate"]["transactions"]
    messages = {
        "live_data_required": "Demo observations are not live provider evidence.",
        "succeeded_snapshot_required": "The pinned snapshot completed only partially.",
        "activity_required": "No Activity rows are available in the pinned revision.",
        "complete_coverage_required": "Requested surfaces do not have bounded complete coverage.",
        "full_history_proof_required": "The pinned interval does not establish complete wallet history.",
        "activity_gaps_must_be_closed": "Activity still publishes explicit coverage or evidence gaps.",
        "identity_conflicts_must_be_resolved": "Conflicting observation identities were omitted fail-closed.",
        "evidence_history_must_be_fully_revalidated": "Older evidence attempts are outside the bounded report page.",
        "every_transaction_must_be_chain_proven": "Not every transaction has a checkpoint-bound inclusion proof.",
        "every_transaction_needs_native_ledger": "Not every transaction has a completed native ledger artifact.",
    }
    affected = {
        "activity_required": activity["aggregate"]["total_items"],
        "identity_conflicts_must_be_resolved": activity["aggregate"]["conflicted_identity_count"],
        "evidence_history_must_be_fully_revalidated": (
            evidence["total_attempts"] - evidence["returned_revalidated"]
        ),
        "every_transaction_must_be_chain_proven": max(
            0, transactions - evidence["chain_inclusion_proven_activity_count"]
        ),
        "every_transaction_needs_native_ledger": max(
            0, transactions - evidence["native_ledger_activity_count"]
        ),
    }
    return [
        {
            "code": code,
            "message": messages[code],
            "affected_count": affected.get(code),
        }
        for code in canonical_gate["unmet"]
    ]


def _distinct_messages(items: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        code = item["code"]
        if code not in seen:
            seen.add(code)
            result.append(item)
    return result


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "WalletCaseReportConflict",
    "WalletCaseReportNotFound",
    "WalletCaseReportScopeTooLarge",
    "WalletCaseReportService",
    "WalletCaseReportSnapshotNotFound",
]
