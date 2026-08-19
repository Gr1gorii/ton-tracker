"""Strict public contract for durable Wallet Case Report revision history."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wallet_case_report_schemas import (
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
        ):
            raise ValueError("stored report revision detail is incoherent")
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
    "WalletCaseReportRevisionDetailResponse",
    "report_revision_catalog_public_id",
]
