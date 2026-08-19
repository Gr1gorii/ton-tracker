"""Strict public contracts for Wallet Case evidence verification."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from services.ton_liteclient_config import (
    CURRENT_VERIFIER_POLICY_ID,
    is_current_trusted_checkpoint,
)
from wallet_case_activity_schemas import ActivityPublicId, WalletCaseActivitySnapshot
from wallet_case_schemas import CanonicalPublicId, WalletCaseLimitation


EvidencePolicy = Literal["transaction_inclusion_v1"]
EvidenceState = Literal[
    "queued", "running", "partial", "succeeded", "failed", "cancelled"
]
EvidenceStage = Literal[
    "queued",
    "validating",
    "capturing_trace",
    "verifying_bocs",
    "proving_inclusion",
    "building_native_ledger",
    "finalizing",
    "retry_wait",
    "terminal",
]
EvidenceLevel = Literal["normalized", "locally_verified", "chain_inclusion_proven"]
_STEP_CODES = (
    "trace_capture",
    "boc_verification",
    "block_inclusion",
    "native_ledger",
)
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaseEvidenceVerificationRequest(_StrictModel):
    snapshot_public_id: CanonicalPublicId
    activity_public_id: ActivityPublicId
    policy: EvidencePolicy


class CaseEvidenceProgress(_StrictModel):
    current: int = Field(ge=0, le=4)
    total: Literal[4] = 4


class CaseEvidenceTransaction(_StrictModel):
    network: Literal["ton-mainnet", "ton-testnet"]
    wallet_account_canonical: str = Field(
        pattern=r"^(?:0|-1):[0-9a-f]{64}$",
        min_length=66,
        max_length=67,
    )
    hash: str = Field(pattern=r"^[0-9a-f]{64}$", max_length=64)
    logical_time: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,19})$", max_length=20)

    @model_validator(mode="after")
    def _logical_time_is_uint64(self):
        if int(self.logical_time) > 2**64 - 1:
            raise ValueError("evidence logical time exceeds uint64")
        return self


class CaseEvidenceProvenance(_StrictModel):
    data_origin: Literal["provider_observed"]
    provider: str = Field(min_length=1, max_length=64)
    identity_assurance: Literal["network_scoped"]
    source_sync_public_id: CanonicalPublicId
    transaction: CaseEvidenceTransaction


class CaseEvidenceStep(_StrictModel):
    code: Literal[
        "trace_capture", "boc_verification", "block_inclusion", "native_ledger"
    ]
    state: Literal["pending", "succeeded"]
    evidence_level: EvidenceLevel | None = None
    evidence_digest_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$", max_length=64
    )
    completed_at: str | None = None

    @model_validator(mode="after")
    def _completion_is_coherent(self):
        succeeded = self.state == "succeeded"
        if succeeded != (self.evidence_digest_sha256 is not None):
            raise ValueError("evidence step digest must match its state")
        if succeeded != (self.completed_at is not None):
            raise ValueError("evidence step timestamp must match its state")
        if succeeded != (self.evidence_level is not None):
            raise ValueError("evidence step level must match its state")
        if self.completed_at is not None:
            _timestamp(self.completed_at)
        return self


class CaseEvidenceRetry(_StrictModel):
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    retry_at: str
    reason_code: str = Field(min_length=1, max_length=64)
    message_safe: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def _valid_retry(self):
        _timestamp(self.retry_at)
        if self.attempt >= self.max_attempts:
            raise ValueError("evidence retry requires remaining attempts")
        return self


class CaseEvidenceError(_StrictModel):
    code: str = Field(min_length=1, max_length=64)
    message_safe: str = Field(min_length=1, max_length=1000)
    retryable: bool


class CaseEvidenceDigests(_StrictModel):
    trace_capture: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    boc_verification: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    block_inclusion: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    native_ledger: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class CaseEvidenceNativeLedger(_StrictModel):
    evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    activity_count: int = Field(ge=0)
    incoming_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    outgoing_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    self_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    native_ton_only: Literal[True]
    selected_evidence_only: Literal[True]
    is_authoritative_activity_ledger: Literal[False] = False
    establishes_complete_wallet_history: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    message: str = Field(min_length=1, max_length=500)


class CaseEvidenceTrustedCheckpoint(_StrictModel):
    workchain: Literal[-1]
    shard: Literal["-9223372036854775808"]
    seqno: int = Field(strict=True, ge=1, le=2**31 - 1)
    root_hash: str = Field(pattern=r"^[0-9a-f]{64}$", max_length=64)
    file_hash: str = Field(pattern=r"^[0-9a-f]{64}$", max_length=64)


class CaseEvidenceInclusionProvenance(_StrictModel):
    contract_version: Literal["ton_transaction_inclusion_v2"]
    network: Literal["ton-mainnet", "ton-testnet"]
    verifier_policy_id: Literal[CURRENT_VERIFIER_POLICY_ID]
    trust_level: Literal[0]
    trusted_checkpoint: CaseEvidenceTrustedCheckpoint
    canonical_block_chain_verified_at_capture: Literal[True]
    checkpoint_to_observed_head_transcript_persisted: Literal[False]

    @model_validator(mode="after")
    def _checkpoint_is_application_owned(self):
        checkpoint = self.trusted_checkpoint.model_dump()
        checkpoint["shard"] = int(checkpoint["shard"])
        if not is_current_trusted_checkpoint(
            self.network,
            self.verifier_policy_id,
            checkpoint,
        ):
            raise ValueError("evidence inclusion checkpoint is not application-owned")
        return self


class CaseEvidenceResult(_StrictModel):
    verification_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digests: CaseEvidenceDigests
    inclusion_provenance: CaseEvidenceInclusionProvenance | None = None
    native_ledger: CaseEvidenceNativeLedger | None = None


class CaseEvidenceVerificationResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    public_id: CanonicalPublicId
    snapshot_public_id: CanonicalPublicId
    activity_public_id: ActivityPublicId
    policy: EvidencePolicy
    state: EvidenceState
    stage: EvidenceStage
    status_version: int = Field(ge=1)
    progress: CaseEvidenceProgress
    cancel_requested: bool
    highest_evidence_level: EvidenceLevel
    provenance: CaseEvidenceProvenance
    inclusion_provenance: CaseEvidenceInclusionProvenance | None = None
    steps: list[CaseEvidenceStep] = Field(min_length=4, max_length=4)
    retry: CaseEvidenceRetry | None = None
    error: CaseEvidenceError | None = None
    result: CaseEvidenceResult | None = None
    limitations: list[WalletCaseLimitation]
    message: str = Field(min_length=1, max_length=1000)
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None

    @model_validator(mode="after")
    def _job_is_coherent(self):
        if [step.code for step in self.steps] != list(_STEP_CODES):
            raise ValueError("evidence steps must use canonical order")
        expected_step_levels = (
            "normalized",
            "locally_verified",
            "chain_inclusion_proven",
            "chain_inclusion_proven",
        )
        if any(
            step.state == "succeeded"
            and step.evidence_level != expected_step_levels[index]
            for index, step in enumerate(self.steps)
        ):
            raise ValueError("evidence step level does not match its proof stage")
        completed = [step.state == "succeeded" for step in self.steps]
        if completed != [index < self.progress.current for index in range(4)]:
            raise ValueError("evidence steps must form the canonical proof prefix")
        expected_level: EvidenceLevel = (
            "chain_inclusion_proven"
            if self.progress.current >= 3
            else "locally_verified"
            if self.progress.current == 2
            else "normalized"
        )
        if self.highest_evidence_level != expected_level:
            raise ValueError("evidence level must match the completed proof prefix")
        if (self.inclusion_provenance is not None) != (
            self.progress.current >= 3
        ):
            raise ValueError(
                "top-level inclusion provenance must match the proven proof prefix"
            )
        if (
            self.inclusion_provenance is not None
            and self.inclusion_provenance.network
            != self.provenance.transaction.network
        ):
            raise ValueError("top-level inclusion provenance network changed")
        for value in (self.created_at, self.updated_at):
            _timestamp(value)
        for value in (self.started_at, self.completed_at):
            if value is not None:
                _timestamp(value)
        terminal = self.state in {"partial", "succeeded", "failed", "cancelled"}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal evidence state must match completed_at")
        if terminal != (self.stage == "terminal"):
            raise ValueError("terminal evidence state must use terminal stage")
        if self.state == "cancelled" and not self.cancel_requested:
            raise ValueError("cancelled evidence requires an accepted cancellation")
        if self.state not in {"running", "cancelled"} and self.cancel_requested:
            raise ValueError("evidence state cannot claim cancellation")
        if self.state in {"partial", "succeeded"}:
            if self.result is None or self.error is not None:
                raise ValueError("usable evidence result has incoherent terminal fields")
        elif self.result is not None:
            raise ValueError("only partial or succeeded evidence may publish a result")
        if self.state == "failed":
            if self.error is None or self.progress.current != 0:
                raise ValueError("failed evidence requires a safe error")
        elif self.error is not None:
            raise ValueError("only failed evidence may publish a terminal error")
        if self.state == "partial" and not any(
            item.code == "verification_partial" for item in self.limitations
        ):
            raise ValueError("partial evidence requires a machine-readable limitation")
        if self.state == "partial" and self.progress.current == 0:
            raise ValueError("partial evidence requires a completed proof prefix")
        if self.retry is not None and not (
            self.state == "queued" and self.stage == "retry_wait"
        ):
            raise ValueError("retry metadata requires queued retry_wait")
        if (self.stage == "retry_wait") != (self.retry is not None):
            raise ValueError("retry_wait requires retry metadata")
        if self.state == "queued" and self.stage not in {"queued", "retry_wait"}:
            raise ValueError("queued evidence has an invalid stage")
        if self.state == "running" and self.stage not in {
            "validating",
            "capturing_trace",
            "verifying_bocs",
            "proving_inclusion",
            "building_native_ledger",
            "finalizing",
        }:
            raise ValueError("running evidence has an invalid stage")
        if self.state == "succeeded" and (
            self.highest_evidence_level != "chain_inclusion_proven"
            or self.progress.current != 4
            or self.result is None
            or self.result.native_ledger is None
        ):
            raise ValueError("succeeded evidence must complete the proof chain")
        if self.result is not None:
            digests = self.result.evidence_digests
            published = [
                digests.trace_capture,
                digests.boc_verification,
                digests.block_inclusion,
                digests.native_ledger,
            ]
            if published != [step.evidence_digest_sha256 for step in self.steps]:
                raise ValueError("evidence result digests must match completed steps")
            if (self.result.native_ledger is not None) != (self.progress.current == 4):
                raise ValueError("native ledger result must match the proof prefix")
            if (self.result.inclusion_provenance is not None) != (
                self.progress.current >= 3
            ):
                raise ValueError(
                    "inclusion provenance must match the proven proof prefix"
                )
            if (
                self.result.inclusion_provenance is not None
                and self.result.inclusion_provenance.network
                != self.provenance.transaction.network
            ):
                raise ValueError("inclusion provenance network changed")
            if self.result.inclusion_provenance != self.inclusion_provenance:
                raise ValueError(
                    "result inclusion provenance must match the job provenance"
                )
            if (
                self.result.native_ledger is not None
                and self.result.native_ledger.evidence_digest_sha256
                != self.result.evidence_digests.native_ledger
            ):
                raise ValueError("native ledger digest must match evidence digests")
        created_at = _timestamp(self.created_at)
        updated_at = _timestamp(self.updated_at)
        started_at = _timestamp(self.started_at) if self.started_at is not None else None
        completed_at = (
            _timestamp(self.completed_at) if self.completed_at is not None else None
        )
        if (
            updated_at < created_at
            or (started_at is not None and started_at < created_at)
            or (started_at is not None and updated_at < started_at)
            or (
                completed_at is not None
                and (
                    completed_at < created_at
                    or (started_at is not None and completed_at < started_at)
                    or updated_at < completed_at
                )
            )
            or (self.state == "queued" and self.stage == "queued" and started_at is not None)
            or (self.state == "running" and started_at is None)
            or (self.state == "queued" and self.stage == "retry_wait" and started_at is None)
        ):
            raise ValueError("evidence lifecycle timestamps are inconsistent")
        return self


class CaseEvidenceAggregate(_StrictModel):
    total: int = Field(ge=0)
    returned_count: int = Field(ge=0, le=50)
    counts_scope: Literal["returned_revalidated"]
    queued: int = Field(ge=0)
    running: int = Field(ge=0)
    partial: int = Field(ge=0)
    succeeded: int = Field(ge=0)
    failed: int = Field(ge=0)
    cancelled: int = Field(ge=0)
    normalized: int = Field(ge=0)
    locally_verified: int = Field(ge=0)
    chain_inclusion_proven: int = Field(ge=0)

    @model_validator(mode="after")
    def _counts_add_up(self):
        if self.returned_count != sum(
            getattr(self, state)
            for state in ("queued", "running", "partial", "succeeded", "failed", "cancelled")
        ):
            raise ValueError("evidence state counts do not add up")
        if self.returned_count != self.normalized + self.locally_verified + self.chain_inclusion_proven:
            raise ValueError("evidence level counts do not add up")
        if self.returned_count > self.total:
            raise ValueError("returned evidence count exceeds total")
        return self


class CaseEvidenceReadiness(_StrictModel):
    transaction_verification_available: bool
    report_available: Literal[False] = False
    highest_evidence_level: EvidenceLevel | None = None


class CaseEvidenceCatalogResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    snapshot: WalletCaseActivitySnapshot | None = None
    aggregate: CaseEvidenceAggregate
    readiness: CaseEvidenceReadiness
    limitations: list[WalletCaseLimitation]
    verifications: list[CaseEvidenceVerificationResponse] = Field(max_length=50)
    limit: Literal[50] = 50
    truncated: bool

    @model_validator(mode="after")
    def _catalog_is_coherent(self):
        if len(self.verifications) != self.aggregate.returned_count:
            raise ValueError("evidence catalog returned count must match its page")
        if self.truncated != (self.aggregate.total > self.aggregate.returned_count):
            raise ValueError("evidence catalog truncation flag is incoherent")
        if self.truncated and not any(
            item.code == "catalog_history_not_revalidated" for item in self.limitations
        ):
            raise ValueError("truncated evidence catalog must disclose count scope")
        if self.snapshot is None and self.verifications:
            raise ValueError("unsynchronized evidence catalog cannot contain jobs")
        if len({item.public_id for item in self.verifications}) != len(
            self.verifications
        ):
            raise ValueError("evidence catalog verification IDs must be unique")
        if any(
            item.case_public_id != self.case_public_id
            for item in self.verifications
        ):
            raise ValueError("evidence catalog contains another Wallet Case")
        if self.snapshot is not None and any(
            item.snapshot_public_id != self.snapshot.public_id
            for item in self.verifications
        ):
            raise ValueError("evidence catalog contains another snapshot")
        if len({item.code for item in self.limitations}) != len(self.limitations):
            raise ValueError("evidence catalog limitation codes must be unique")
        if not any(item.code == "report_not_built" for item in self.limitations):
            raise ValueError("v0.74 evidence catalog must disclose report limitation")
        limitation_codes = {item.code for item in self.limitations}
        unavailable_codes = {
            "demo_evidence_not_verifiable",
            "evidence_runner_unavailable",
            "evidence_runtime_unavailable",
        }
        aggregate_highest: EvidenceLevel | None = (
            "chain_inclusion_proven"
            if self.aggregate.chain_inclusion_proven
            else "locally_verified"
            if self.aggregate.locally_verified
            else "normalized"
            if self.aggregate.normalized
            else None
        )
        if self.readiness.highest_evidence_level != aggregate_highest:
            raise ValueError("catalog highest evidence level is incoherent")
        if self.snapshot is None:
            if (
                self.aggregate.total != 0
                or self.aggregate.returned_count != 0
                or self.readiness.transaction_verification_available
                or "not_synchronized" not in limitation_codes
            ):
                raise ValueError("unsynchronized evidence catalog is incoherent")
        elif self.snapshot.data_mode == "mock":
            if (
                self.readiness.transaction_verification_available
                or "demo_evidence_not_verifiable" not in limitation_codes
            ):
                raise ValueError("demo evidence readiness is incoherent")
        elif self.readiness.transaction_verification_available:
            if limitation_codes & unavailable_codes:
                raise ValueError("available evidence catalog has an unavailable limitation")
        elif not limitation_codes & {
            "evidence_runner_unavailable",
            "evidence_runtime_unavailable",
        }:
            raise ValueError("unavailable live evidence requires a runtime limitation")
        return self


def _timestamp(value: str) -> datetime:
    if _RFC3339_RE.fullmatch(value) is None:
        raise ValueError("evidence timestamps must be RFC3339")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("evidence timestamps require timezone")
    return parsed.astimezone(timezone.utc)
