"""Strict public contract for a reproducible Wallet Case report."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wallet_case_activity_schemas import (
    WalletCaseActivityAggregate,
    WalletCaseActivityGap,
    WalletCaseActivityPeriod,
    WalletCaseActivitySnapshot,
)
from wallet_case_schemas import (
    CanonicalPublicId,
    WalletCaseCoverage,
    WalletCaseDataEnvironment,
    WalletCaseLimitation,
    WalletCaseNetwork,
)


CaseReportAssurance = Literal[
    "observed",
    "normalized",
    "partially_verified",
    "canonical",
]
CanonicalGateCode = Literal[
    "live_data_required",
    "succeeded_snapshot_required",
    "activity_required",
    "complete_coverage_required",
    "full_history_proof_required",
    "activity_gaps_must_be_closed",
    "identity_conflicts_must_be_resolved",
    "evidence_history_must_be_fully_revalidated",
    "every_transaction_must_be_chain_proven",
    "every_transaction_needs_native_ledger",
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WalletCaseReportSubject(_StrictModel):
    network: WalletCaseNetwork
    data_environment: WalletCaseDataEnvironment
    wallet_account_canonical: str = Field(
        pattern=r"^(?:0|-1):[0-9a-f]{64}$",
        min_length=66,
        max_length=67,
    )


class WalletCaseReportActivityRevision(_StrictModel):
    digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    aggregate: WalletCaseActivityAggregate
    observed_period: WalletCaseActivityPeriod | None = None


class WalletCaseReportEvidenceRevision(_StrictModel):
    digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_attempts: int = Field(ge=0)
    returned_revalidated: int = Field(ge=0, le=50)
    history_truncated: bool
    selected_activity_count: int = Field(ge=0, le=50)
    locally_verified_activity_count: int = Field(ge=0, le=50)
    chain_inclusion_proven_activity_count: int = Field(ge=0, le=50)
    native_ledger_activity_count: int = Field(ge=0, le=50)

    @model_validator(mode="after")
    def _counts_are_coherent(self):
        if self.returned_revalidated > self.total_attempts:
            raise ValueError("returned report evidence exceeds its total")
        if self.history_truncated != (
            self.total_attempts > self.returned_revalidated
        ):
            raise ValueError("report evidence truncation is incoherent")
        if not (
            self.native_ledger_activity_count
            <= self.chain_inclusion_proven_activity_count
            <= self.locally_verified_activity_count
            <= self.selected_activity_count
            <= self.returned_revalidated
        ):
            raise ValueError("report evidence counts are not a verified prefix")
        return self


class WalletCaseReportCanonicalGate(_StrictModel):
    eligible: bool
    unmet: list[CanonicalGateCode]

    @model_validator(mode="after")
    def _eligibility_matches_unmet(self):
        if self.eligible != (not self.unmet):
            raise ValueError("canonical report eligibility is incoherent")
        if len(self.unmet) != len(set(self.unmet)):
            raise ValueError("canonical report gate codes must be distinct")
        return self


class WalletCaseReportUnverifiedClaim(_StrictModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)
    affected_count: int | None = Field(default=None, ge=0)


class WalletCaseReportTruthBoundaries(_StrictModel):
    establishes_complete_wallet_history: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    includes_raw_provider_payloads: Literal[False] = False
    provider_free_full_report_revalidation: Literal[False] = False


class WalletCaseReport(_StrictModel):
    contract_version: Literal["wallet_case_report_v1"]
    public_id: str = Field(pattern=r"^rpt_[0-9a-f]{64}$", min_length=68, max_length=68)
    content_hash_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_public_id: CanonicalPublicId
    snapshot_public_id: CanonicalPublicId
    assurance_level: CaseReportAssurance
    subject: WalletCaseReportSubject
    snapshot: WalletCaseActivitySnapshot
    activity_revision: WalletCaseReportActivityRevision
    evidence_revision: WalletCaseReportEvidenceRevision
    coverage: WalletCaseCoverage
    gaps: list[WalletCaseActivityGap]
    canonical_gate: WalletCaseReportCanonicalGate
    limitations: list[WalletCaseLimitation]
    unverified_claims: list[WalletCaseReportUnverifiedClaim]
    truth_boundaries: WalletCaseReportTruthBoundaries

    @model_validator(mode="after")
    def _report_is_content_addressed_and_truthful(self):
        if self.snapshot_public_id != self.snapshot.public_id:
            raise ValueError("report snapshot identity changed")
        if self.coverage != self.snapshot.coverage:
            raise ValueError("report coverage must come from its pinned snapshot")
        if self.subject.network not in {"ton-mainnet", "ton-testnet"}:
            raise ValueError("report network is invalid")
        if self.assurance_level == "canonical" and not self.canonical_gate.eligible:
            raise ValueError("canonical report cannot bypass its hard gate")
        if self.canonical_gate.eligible and self.assurance_level != "canonical":
            raise ValueError("an eligible canonical report must publish canonical assurance")
        if self.subject.data_environment == "demo" and self.assurance_level != "observed":
            raise ValueError("demo report cannot exceed observed assurance")
        if len({item.code for item in self.limitations}) != len(self.limitations):
            raise ValueError("report limitation codes must be distinct")
        if len({item.code for item in self.unverified_claims}) != len(
            self.unverified_claims
        ):
            raise ValueError("report unverified claim codes must be distinct")
        expected = case_report_content_hash(self.model_dump())
        if self.content_hash_sha256 != expected or self.public_id != f"rpt_{expected}":
            raise ValueError("report content address changed")
        return self


class WalletCaseReportResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    snapshot_public_id: CanonicalPublicId | None = None
    report: WalletCaseReport | None = None
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _response_is_coherent(self):
        if (self.report is not None) != (self.snapshot_public_id is not None):
            raise ValueError("report and snapshot availability disagree")
        if self.report is not None and (
            self.report.case_public_id != self.case_public_id
            or self.report.snapshot_public_id != self.snapshot_public_id
            or self.limitations
        ):
            raise ValueError("report response scope is incoherent")
        if self.report is None and (
            len(self.limitations) != 1
            or self.limitations[0].code != "not_synchronized"
        ):
            raise ValueError("missing report requires not_synchronized")
        return self


def case_report_content_hash(document: dict) -> str:
    """Hash the canonical report payload without its self-addressing fields."""
    payload = {
        key: value
        for key, value in document.items()
        if key not in {"public_id", "content_hash_sha256"}
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "WalletCaseReport",
    "WalletCaseReportResponse",
    "case_report_content_hash",
]
