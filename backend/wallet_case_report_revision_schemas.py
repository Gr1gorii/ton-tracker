"""Strict public contract for durable Wallet Case Report revision history."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wallet_case_report_schemas import (
    CanonicalGateCode,
    CaseReportAssurance,
    WalletCaseReportResponse,
)
from wallet_case_schemas import CanonicalPublicId, WalletCaseLimitation


_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WalletCaseReportRevisionCaptureRequest(_StrictModel):
    snapshot_public_id: CanonicalPublicId


class WalletCaseReportRevisionSummary(_StrictModel):
    public_id: str = Field(pattern=r"^rpt_[0-9a-f]{64}$", min_length=68, max_length=68)
    content_hash_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_public_id: CanonicalPublicId
    snapshot_public_id: CanonicalPublicId
    assurance_level: CaseReportAssurance
    captured_at: str
    activity_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    activity_count: int = Field(ge=0)
    evidence_attempt_count: int = Field(ge=0)
    canonical_eligible: bool
    limitation_count: int = Field(ge=0)
    unverified_claim_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _summary_is_coherent(self):
        _timestamp(self.captured_at)
        if self.public_id != f"rpt_{self.content_hash_sha256}":
            raise ValueError("stored report public identity changed")
        if (self.assurance_level == "canonical") != self.canonical_eligible:
            raise ValueError("stored report assurance contradicts its canonical gate")
        return self


class WalletCaseReportRevisionPage(_StrictModel):
    limit: int = Field(ge=1, le=20)
    has_more: bool
    next_cursor: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def _cursor_matches_page(self):
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("report revision page cursor is incoherent")
        return self


class WalletCaseReportRevisionAggregate(_StrictModel):
    total_revisions: int = Field(ge=0)
    returned_count: int = Field(ge=0, le=20)


class WalletCaseReportRevisionCatalog(_StrictModel):
    contract_version: Literal["wallet_case_report_revision_catalog_v1"]
    public_id: str = Field(pattern=r"^rcat_[0-9a-f]{64}$", min_length=69, max_length=69)
    case_public_id: CanonicalPublicId
    revision_cutoff_public_id: str | None = Field(
        default=None,
        pattern=r"^rpt_[0-9a-f]{64}$",
        min_length=68,
        max_length=68,
    )
    items: list[WalletCaseReportRevisionSummary] = Field(max_length=20)
    aggregate: WalletCaseReportRevisionAggregate
    page: WalletCaseReportRevisionPage
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _catalog_is_scoped(self):
        if self.aggregate.returned_count != len(self.items):
            raise ValueError("report revision returned count changed")
        if self.aggregate.returned_count > self.aggregate.total_revisions:
            raise ValueError("report revision returned count exceeds its total")
        if len(self.items) > self.page.limit:
            raise ValueError("report revision page exceeds its requested limit")
        if (self.revision_cutoff_public_id is None) != (
            self.aggregate.total_revisions == 0
        ):
            raise ValueError("report revision cutoff is incoherent")
        if any(item.case_public_id != self.case_public_id for item in self.items):
            raise ValueError("report revision catalog crossed a case scope")
        if len({item.public_id for item in self.items}) != len(self.items):
            raise ValueError("report revision catalog contains duplicates")
        expected = report_revision_catalog_public_id(
            self.case_public_id,
            self.revision_cutoff_public_id,
        )
        if self.public_id != expected:
            raise ValueError("report revision catalog identity changed")
        if len({item.code for item in self.limitations}) != len(self.limitations):
            raise ValueError("report revision catalog limitations must be distinct")
        limitation_codes = {item.code for item in self.limitations}
        if "report_revisions_are_explicit_captures" not in limitation_codes:
            raise ValueError("report revision catalog must disclose capture scope")
        if self.page.has_more != (
            "report_revision_cursor_local_process_scope" in limitation_codes
        ):
            raise ValueError("report revision cursor limitation is incoherent")
        return self


class WalletCaseReportRevisionCaptureResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    created: bool
    revision: WalletCaseReportRevisionSummary

    @model_validator(mode="after")
    def _capture_is_scoped(self):
        if self.revision.case_public_id != self.case_public_id:
            raise ValueError("captured report revision crossed a case scope")
        return self


class WalletCaseReportRevisionDetailResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    revision: WalletCaseReportRevisionSummary
    report: WalletCaseReportResponse

    @model_validator(mode="after")
    def _detail_is_coherent(self):
        report = self.report.report
        if (
            report is None
            or self.report.case_public_id != self.case_public_id
            or self.revision.case_public_id != self.case_public_id
            or self.revision.public_id != report.public_id
            or self.revision.content_hash_sha256 != report.content_hash_sha256
            or self.revision.snapshot_public_id != report.snapshot_public_id
            or self.revision.assurance_level != report.assurance_level
            or self.revision.activity_digest_sha256
            != report.activity_revision.digest_sha256
            or self.revision.evidence_digest_sha256
            != report.evidence_revision.digest_sha256
            or self.revision.activity_count
            != report.activity_revision.aggregate.total_items
            or self.revision.evidence_attempt_count
            != report.evidence_revision.total_attempts
            or self.revision.canonical_eligible
            != report.canonical_gate.eligible
            or self.revision.limitation_count != len(report.limitations)
            or self.revision.unverified_claim_count
            != len(report.unverified_claims)
        ):
            raise ValueError("stored report revision detail is incoherent")
        return self


class WalletCaseReportRevisionIntegerDelta(_StrictModel):
    baseline: int = Field(ge=0)
    target: int = Field(ge=0)
    delta: int

    @model_validator(mode="after")
    def _delta_is_exact(self):
        if self.delta != self.target - self.baseline:
            raise ValueError("report comparison integer delta is incoherent")
        return self


class WalletCaseReportRevisionBooleanTransition(_StrictModel):
    baseline: bool
    target: bool
    changed: bool

    @model_validator(mode="after")
    def _change_is_exact(self):
        if self.changed != (self.baseline != self.target):
            raise ValueError("report comparison boolean transition is incoherent")
        return self


class WalletCaseReportRevisionAssuranceTransition(_StrictModel):
    baseline: CaseReportAssurance
    target: CaseReportAssurance
    changed: bool

    @model_validator(mode="after")
    def _change_is_exact(self):
        if self.changed != (self.baseline != self.target):
            raise ValueError("report comparison assurance transition is incoherent")
        return self


class WalletCaseReportRevisionActivityComparison(_StrictModel):
    digest_changed: bool
    observed_period_changed: bool
    total_items: WalletCaseReportRevisionIntegerDelta
    transactions: WalletCaseReportRevisionIntegerDelta
    transfers: WalletCaseReportRevisionIntegerDelta
    swaps: WalletCaseReportRevisionIntegerDelta
    failed_transactions: WalletCaseReportRevisionIntegerDelta
    source_sync_count: WalletCaseReportRevisionIntegerDelta
    suppressed_duplicate_observations: WalletCaseReportRevisionIntegerDelta
    conflicted_identity_count: WalletCaseReportRevisionIntegerDelta


class WalletCaseReportRevisionEvidenceComparison(_StrictModel):
    digest_changed: bool
    total_attempts: WalletCaseReportRevisionIntegerDelta
    returned_revalidated: WalletCaseReportRevisionIntegerDelta
    selected_activity_count: WalletCaseReportRevisionIntegerDelta
    locally_verified_activity_count: WalletCaseReportRevisionIntegerDelta
    chain_inclusion_proven_activity_count: WalletCaseReportRevisionIntegerDelta
    native_ledger_activity_count: WalletCaseReportRevisionIntegerDelta
    history_truncated: WalletCaseReportRevisionBooleanTransition


class WalletCaseReportRevisionCodeChanges(_StrictModel):
    added: list[str] = Field(max_length=64)
    removed: list[str] = Field(max_length=64)
    modified: list[str] = Field(max_length=64)
    unchanged_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _codes_are_canonical(self):
        groups = (self.added, self.removed, self.modified)
        if any(
            values != sorted(values)
            or len(values) != len(set(values))
            or any(not value or len(value) > 64 or value != value.strip() for value in values)
            for values in groups
        ):
            raise ValueError("report comparison code changes are not canonical")
        if (set(self.added) & set(self.removed)) or (
            (set(self.added) | set(self.removed)) & set(self.modified)
        ):
            raise ValueError("report comparison code changes overlap")
        return self


class WalletCaseReportRevisionCanonicalGateComparison(_StrictModel):
    eligible: WalletCaseReportRevisionBooleanTransition
    newly_unmet: list[CanonicalGateCode] = Field(max_length=16)
    resolved: list[CanonicalGateCode] = Field(max_length=16)
    unchanged_count: int = Field(ge=0)

    @model_validator(mode="after")
    def _gate_codes_are_canonical(self):
        if (
            self.newly_unmet != sorted(self.newly_unmet)
            or self.resolved != sorted(self.resolved)
            or len(self.newly_unmet) != len(set(self.newly_unmet))
            or len(self.resolved) != len(set(self.resolved))
            or set(self.newly_unmet) & set(self.resolved)
        ):
            raise ValueError("report comparison gate changes are not canonical")
        return self


class WalletCaseReportRevisionComparison(_StrictModel):
    contract_version: Literal["wallet_case_report_revision_comparison_v1"]
    public_id: str = Field(pattern=r"^rcmp_[0-9a-f]{64}$", min_length=69, max_length=69)
    case_public_id: CanonicalPublicId
    baseline: WalletCaseReportRevisionSummary
    target: WalletCaseReportRevisionSummary
    same_snapshot: bool
    content_changed: bool
    assurance: WalletCaseReportRevisionAssuranceTransition
    activity: WalletCaseReportRevisionActivityComparison
    evidence: WalletCaseReportRevisionEvidenceComparison
    coverage_changed: bool
    canonical_gate: WalletCaseReportRevisionCanonicalGateComparison
    gaps: WalletCaseReportRevisionCodeChanges
    limitations: WalletCaseReportRevisionCodeChanges
    unverified_claims: WalletCaseReportRevisionCodeChanges
    truth_boundaries_changed: Literal[False] = False
    comparison_limitations: list[WalletCaseLimitation] = Field(min_length=2, max_length=3)

    @model_validator(mode="after")
    def _comparison_is_coherent(self):
        if (
            self.baseline.case_public_id != self.case_public_id
            or self.target.case_public_id != self.case_public_id
        ):
            raise ValueError("report comparison crossed a case scope")
        if self.same_snapshot != (
            self.baseline.snapshot_public_id == self.target.snapshot_public_id
        ):
            raise ValueError("report comparison snapshot scope is incoherent")
        if self.content_changed != (self.baseline.public_id != self.target.public_id):
            raise ValueError("report comparison content state is incoherent")
        if (
            self.assurance.baseline != self.baseline.assurance_level
            or self.assurance.target != self.target.assurance_level
            or self.canonical_gate.eligible.baseline
            != self.baseline.canonical_eligible
            or self.canonical_gate.eligible.target != self.target.canonical_eligible
        ):
            raise ValueError("report comparison summaries are incoherent")
        if (
            self.activity.digest_changed
            != (
                self.baseline.activity_digest_sha256
                != self.target.activity_digest_sha256
            )
            or self.evidence.digest_changed
            != (
                self.baseline.evidence_digest_sha256
                != self.target.evidence_digest_sha256
            )
            or self.activity.total_items.baseline != self.baseline.activity_count
            or self.activity.total_items.target != self.target.activity_count
            or self.evidence.total_attempts.baseline
            != self.baseline.evidence_attempt_count
            or self.evidence.total_attempts.target
            != self.target.evidence_attempt_count
        ):
            raise ValueError("report comparison revision deltas are incoherent")
        limitation_codes = [item.code for item in self.comparison_limitations]
        expected_codes = [
            "comparison_uses_explicit_captures",
            "comparison_does_not_establish_causality",
        ]
        if not self.same_snapshot:
            expected_codes.append("comparison_spans_pinned_snapshots")
        if limitation_codes != expected_codes:
            raise ValueError("report comparison limitations are incoherent")
        expected_public_id = report_revision_comparison_public_id(
            self.model_dump(mode="json")
        )
        if self.public_id != expected_public_id:
            raise ValueError("report comparison public identity changed")
        return self


def report_revision_catalog_public_id(
    case_public_id: str,
    cutoff_public_id: str | None,
) -> str:
    payload = json.dumps(
        {
            "contract_version": "wallet_case_report_revision_catalog_v1",
            "case_public_id": case_public_id,
            "revision_cutoff_public_id": cutoff_public_id,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"rcat_{hashlib.sha256(payload).hexdigest()}"


def report_revision_comparison_public_id(document: dict) -> str:
    payload = {
        key: value
        for key, value in document.items()
        if key != "public_id"
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return f"rcmp_{hashlib.sha256(encoded).hexdigest()}"


def _timestamp(value: str) -> datetime:
    if _RFC3339_RE.fullmatch(value) is None:
        raise ValueError("report revision timestamps must be RFC3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("report revision timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "WalletCaseReportRevisionCaptureRequest",
    "WalletCaseReportRevisionCaptureResponse",
    "WalletCaseReportRevisionCatalog",
    "WalletCaseReportRevisionComparison",
    "WalletCaseReportRevisionDetailResponse",
    "report_revision_comparison_public_id",
    "report_revision_catalog_public_id",
]
