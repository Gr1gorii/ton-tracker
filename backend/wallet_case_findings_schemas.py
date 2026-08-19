"""Strict public contract for pinned Wallet Case Findings and Flows."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wallet_case_activity_schemas import (
    ActivityKind,
    ActivityPublicId,
    AssetPublicId,
    WalletCaseActivityAggregate,
    WalletCaseActivityGap,
    WalletCaseActivityPeriod,
    WalletCaseActivitySnapshot,
)
from wallet_case_schemas import (
    CanonicalPublicId,
    WalletCaseDataEnvironment,
    WalletCaseLimitation,
    WalletCaseNetwork,
)


FindingEvidenceLevel = Literal[
    "fixture",
    "normalized_provider_observation",
    "locally_verified",
    "chain_inclusion_proven",
]
FindingRule = Literal[
    "activity_coverage_gaps_v1",
    "activity_identity_conflicts_v1",
    "failed_transaction_observations_v1",
    "unavailable_asset_identity_v1",
    "unavailable_counterparty_identity_v1",
    "repeated_counterparty_observations_v1",
    "recognized_protocol_observations_v1",
]
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WalletCaseFindingsSubject(_StrictModel):
    network: WalletCaseNetwork
    data_environment: WalletCaseDataEnvironment
    wallet_account_canonical: str = Field(
        pattern=r"^(?:0|-1):[0-9a-f]{64}$",
        min_length=66,
        max_length=67,
    )


class WalletCaseFindingsActivityRevision(_StrictModel):
    digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    aggregate: WalletCaseActivityAggregate
    observed_period: WalletCaseActivityPeriod | None = None


class WalletCaseFindingsEvidenceRevision(_StrictModel):
    digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    total_attempts: int = Field(ge=0)
    returned_revalidated: int = Field(ge=0, le=50)
    history_truncated: bool

    @model_validator(mode="after")
    def _counts_are_coherent(self):
        if self.returned_revalidated > self.total_attempts:
            raise ValueError("findings evidence exceeds its total history")
        if self.history_truncated != (
            self.total_attempts > self.returned_revalidated
        ):
            raise ValueError("findings evidence truncation is incoherent")
        return self


class WalletCaseFindingSupport(_StrictModel):
    activity_public_id: ActivityPublicId
    kind: ActivityKind
    occurred_at: str | None = None
    evidence_level: FindingEvidenceLevel

    @model_validator(mode="after")
    def _timestamp_is_public(self):
        if self.occurred_at is not None:
            _timestamp(self.occurred_at)
        return self


class WalletCaseAssetFlow(_StrictModel):
    asset_id: AssetPublicId
    network: WalletCaseNetwork
    standard: Literal["native", "jetton"]
    contract_address: str | None = Field(default=None, min_length=66, max_length=67)
    symbol: str | None = Field(default=None, max_length=128)
    inflow_amount: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        max_length=80,
    )
    outflow_amount: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        max_length=80,
    )
    inflow_observations: int = Field(ge=0)
    outflow_observations: int = Field(ge=0)
    unknown_direction_observations: int = Field(ge=0)
    amount_unavailable_observations: int = Field(ge=0)
    supporting_activity_ids: list[ActivityPublicId] = Field(max_length=50)
    support_truncated: bool

    @model_validator(mode="after")
    def _identity_and_support_are_coherent(self):
        if self.standard == "native" and self.contract_address is not None:
            raise ValueError("native flow cannot publish a contract address")
        if self.standard == "jetton" and self.contract_address is None:
            raise ValueError("jetton flow requires a contract address")
        if len(self.supporting_activity_ids) != len(set(self.supporting_activity_ids)):
            raise ValueError("asset flow support must be distinct")
        observations = (
            self.inflow_observations
            + self.outflow_observations
            + self.unknown_direction_observations
        )
        if observations == 0 or self.amount_unavailable_observations > observations:
            raise ValueError("asset flow observation counts are incoherent")
        if len(self.supporting_activity_ids) > observations:
            raise ValueError("asset flow has more support rows than observations")
        if self.support_truncated and len(self.supporting_activity_ids) != 50:
            raise ValueError("truncated asset flow support must fill its public bound")
        return self


class WalletCaseCounterpartyFlow(_StrictModel):
    canonical_address: str = Field(
        pattern=r"^(?:0|-1):[0-9a-f]{64}$",
        min_length=66,
        max_length=67,
    )
    incoming_observations: int = Field(ge=0)
    outgoing_observations: int = Field(ge=0)
    unknown_direction_observations: int = Field(ge=0)
    supporting_activity_ids: list[ActivityPublicId] = Field(max_length=50)
    support_truncated: bool

    @model_validator(mode="after")
    def _counts_are_coherent(self):
        observations = (
            self.incoming_observations
            + self.outgoing_observations
            + self.unknown_direction_observations
        )
        if observations == 0:
            raise ValueError("counterparty flow requires an observation")
        if len(self.supporting_activity_ids) != len(set(self.supporting_activity_ids)):
            raise ValueError("counterparty support must be distinct")
        if self.support_truncated != (observations > len(self.supporting_activity_ids)):
            raise ValueError("counterparty support truncation is incoherent")
        return self


class WalletCaseProtocolFlow(_StrictModel):
    protocol_id: str = Field(min_length=1, max_length=32)
    family: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=128)
    swap_observations: int = Field(ge=1)
    supporting_activity_ids: list[ActivityPublicId] = Field(max_length=50)
    support_truncated: bool

    @model_validator(mode="after")
    def _support_is_coherent(self):
        if len(self.supporting_activity_ids) != len(set(self.supporting_activity_ids)):
            raise ValueError("protocol support must be distinct")
        if self.support_truncated != (
            self.swap_observations > len(self.supporting_activity_ids)
        ):
            raise ValueError("protocol support truncation is incoherent")
        return self


class WalletCaseFlowSummary(_StrictModel):
    identified_asset_count: int = Field(ge=0)
    returned_asset_count: int = Field(ge=0, le=50)
    assets_truncated: bool
    unavailable_asset_observations: int = Field(ge=0)
    identified_counterparty_count: int = Field(ge=0)
    returned_counterparty_count: int = Field(ge=0, le=50)
    counterparties_truncated: bool
    unavailable_counterparty_observations: int = Field(ge=0)
    recognized_protocol_count: int = Field(ge=0)
    returned_protocol_count: int = Field(ge=0, le=50)
    protocols_truncated: bool
    unrecognized_protocol_observations: int = Field(ge=0)
    asset_flows: list[WalletCaseAssetFlow] = Field(max_length=50)
    counterparty_flows: list[WalletCaseCounterpartyFlow] = Field(max_length=50)
    protocol_flows: list[WalletCaseProtocolFlow] = Field(max_length=50)

    @model_validator(mode="after")
    def _totals_match_rows(self):
        triples = (
            (
                self.identified_asset_count,
                self.returned_asset_count,
                self.assets_truncated,
                len(self.asset_flows),
            ),
            (
                self.identified_counterparty_count,
                self.returned_counterparty_count,
                self.counterparties_truncated,
                len(self.counterparty_flows),
            ),
            (
                self.recognized_protocol_count,
                self.returned_protocol_count,
                self.protocols_truncated,
                len(self.protocol_flows),
            ),
        )
        for total, returned, truncated, length in triples:
            if returned != length or returned > total or truncated != (total > returned):
                raise ValueError("flow group totals are incoherent")
        if len({item.asset_id for item in self.asset_flows}) != len(self.asset_flows):
            raise ValueError("asset flows must have distinct identities")
        if len({item.canonical_address for item in self.counterparty_flows}) != len(
            self.counterparty_flows
        ):
            raise ValueError("counterparty flows must have distinct identities")
        if len({item.protocol_id for item in self.protocol_flows}) != len(
            self.protocol_flows
        ):
            raise ValueError("protocol flows must have distinct identities")
        return self


class WalletCaseFinding(_StrictModel):
    public_id: str = Field(
        pattern=r"^finding_[0-9a-f]{64}$",
        min_length=72,
        max_length=72,
    )
    rule_id: FindingRule
    category: Literal["data_quality", "transaction_outcome", "flow_pattern"]
    importance: Literal["information", "attention"]
    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, max_length=500)
    affected_count: int = Field(ge=1)
    support_basis: Literal["activity_rows", "coverage_gaps", "identity_conflicts"]
    supporting_activities: list[WalletCaseFindingSupport] = Field(max_length=50)
    support_truncated: bool
    evidence_level: FindingEvidenceLevel

    @model_validator(mode="after")
    def _support_is_coherent(self):
        ids = [item.activity_public_id for item in self.supporting_activities]
        if len(ids) != len(set(ids)):
            raise ValueError("finding support must be distinct")
        if self.support_basis == "activity_rows":
            if not ids or len(ids) > self.affected_count:
                raise ValueError("activity finding support is incoherent")
            if self.support_truncated != (self.affected_count > len(ids)):
                raise ValueError("finding support truncation is incoherent")
        elif ids or self.support_truncated:
            raise ValueError("diagnostic finding cannot invent Activity support")
        return self


class WalletCaseFindingsTruthBoundaries(_StrictModel):
    establishes_complete_wallet_history: Literal[False] = False
    establishes_ownership_or_control: Literal[False] = False
    establishes_illicit_or_safe_status: Literal[False] = False
    absence_of_findings_means_safe: Literal[False] = False
    cross_asset_amounts_are_comparable: Literal[False] = False
    includes_raw_provider_payloads: Literal[False] = False


class WalletCaseFindings(_StrictModel):
    contract_version: Literal["wallet_case_findings_v1"]
    public_id: str = Field(
        pattern=r"^fset_[0-9a-f]{64}$",
        min_length=69,
        max_length=69,
    )
    content_hash_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_public_id: CanonicalPublicId
    snapshot_public_id: CanonicalPublicId
    subject: WalletCaseFindingsSubject
    snapshot: WalletCaseActivitySnapshot
    activity_revision: WalletCaseFindingsActivityRevision
    evidence_revision: WalletCaseFindingsEvidenceRevision
    flows: WalletCaseFlowSummary
    findings: list[WalletCaseFinding] = Field(max_length=100)
    gaps: list[WalletCaseActivityGap]
    limitations: list[WalletCaseLimitation]
    truth_boundaries: WalletCaseFindingsTruthBoundaries

    @model_validator(mode="after")
    def _document_is_scoped_and_content_addressed(self):
        if self.snapshot_public_id != self.snapshot.public_id:
            raise ValueError("findings snapshot identity changed")
        if (self.subject.data_environment == "demo") != (
            self.snapshot.data_mode == "mock"
        ):
            raise ValueError("findings subject and snapshot modes disagree")
        if len({item.public_id for item in self.findings}) != len(self.findings):
            raise ValueError("finding public ids must be distinct")
        if len({item.code for item in self.limitations}) != len(self.limitations):
            raise ValueError("finding limitations must be distinct")
        expected = case_findings_content_hash(self.model_dump())
        if self.content_hash_sha256 != expected or self.public_id != f"fset_{expected}":
            raise ValueError("findings content address changed")
        return self


class WalletCaseFindingsResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    snapshot_public_id: CanonicalPublicId | None = None
    findings: WalletCaseFindings | None = None
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _response_is_coherent(self):
        if (self.findings is not None) != (self.snapshot_public_id is not None):
            raise ValueError("findings and snapshot availability disagree")
        if self.findings is not None:
            if (
                self.findings.case_public_id != self.case_public_id
                or self.findings.snapshot_public_id != self.snapshot_public_id
                or self.limitations
            ):
                raise ValueError("findings response scope is incoherent")
        elif (
            len(self.limitations) != 1
            or self.limitations[0].code != "not_synchronized"
        ):
            raise ValueError("missing findings require not_synchronized")
        return self


def case_findings_content_hash(document: dict) -> str:
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


def _timestamp(value: str) -> datetime:
    if _RFC3339_RE.fullmatch(value) is None:
        raise ValueError("finding timestamps must be RFC3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("finding timestamps require a timezone")
    return parsed.astimezone(timezone.utc)


__all__ = [
    "WalletCaseFindings",
    "WalletCaseFindingsResponse",
    "case_findings_content_hash",
]
