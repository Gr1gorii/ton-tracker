"""Public contracts for the Wallet Case application facade."""

from __future__ import annotations

import hashlib
import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from schemas import WalletIngestionSurface


WalletCaseNetwork = Literal["ton-mainnet", "ton-testnet"]
WalletCaseDataEnvironment = Literal["demo", "live"]
CaseSyncState = Literal[
    "queued",
    "running",
    "partial",
    "succeeded",
    "failed",
    "cancelled",
]
CanonicalPublicId = Annotated[
    str,
    Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
        max_length=36,
    ),
]
ManifestPublicId = Annotated[
    str,
    Field(pattern=r"^smf_[0-9a-f]{64}$", max_length=68),
]
CheckpointPublicId = Annotated[
    str,
    Field(pattern=r"^scp_[0-9a-f]{64}$", max_length=68),
]
CheckpointChainPublicId = Annotated[
    str,
    Field(pattern=r"^cch_[0-9a-f]{64}$", max_length=68),
]
CheckpointContinuationPlanPublicId = Annotated[
    str,
    Field(pattern=r"^cpl_[0-9a-f]{64}$", max_length=68),
]
CheckpointContinuationReceiptPublicId = Annotated[
    str,
    Field(pattern=r"^ctr_[0-9a-f]{64}$", max_length=68),
]
BackfillProgressPublicId = Annotated[
    str,
    Field(pattern=r"^bfp_[0-9a-f]{64}$", max_length=68),
]
Sha256Digest = Annotated[
    str,
    Field(pattern=r"^[0-9a-f]{64}$", min_length=64, max_length=64),
]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WalletCaseCreateRequest(_StrictModel):
    wallet_address: str = Field(min_length=1, max_length=128)
    network: WalletCaseNetwork
    data_environment: WalletCaseDataEnvironment
    label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("wallet_address")
    @classmethod
    def _clean_wallet_address(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Wallet address is required")
        return cleaned

    @field_validator("label", "note")
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None


class WalletCaseSyncRequest(_StrictModel):
    mode: Literal["bounded", "incremental"] = "bounded"
    time_window: Literal["24h", "3d", "7d", "custom"] = "24h"
    custom_start: str | None = None
    custom_end: str | None = None
    surfaces: list[WalletIngestionSurface] = Field(
        default_factory=lambda: [
            "transfers",
            "transactions",
            "swaps",
            "balances",
            "jettons",
        ]
    )

    @field_validator("surfaces")
    @classmethod
    def _require_surfaces(
        cls,
        value: list[WalletIngestionSurface],
    ) -> list[WalletIngestionSurface]:
        if not value:
            raise ValueError("At least one wallet activity surface is required")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _validate_window_scope(self):
        if self.mode == "incremental":
            if self.time_window != "24h":
                raise ValueError(
                    "incremental sync uses the latest snapshot instead of a time_window"
                )
            if self.custom_start is not None or self.custom_end is not None:
                raise ValueError(
                    "incremental sync does not accept custom bounds"
                )
            return self
        if self.time_window == "custom":
            if not self.custom_start or not self.custom_end:
                raise ValueError(
                    "custom_start and custom_end are required for custom windows"
                )
        elif self.custom_start is not None or self.custom_end is not None:
            raise ValueError(
                "custom_start and custom_end are allowed only for custom windows"
            )
        return self


class WalletCaseCheckpointPlanResumeRequest(_StrictModel):
    page_budget: int = Field(default=1, strict=True, ge=1, le=10)


class WalletCaseMetadataUpdateRequest(_StrictModel):
    expected_metadata_version: int = Field(ge=1)
    label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=4000)

    @field_validator("label", "note")
    @classmethod
    def _clean_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @model_validator(mode="after")
    def _require_a_metadata_field(self):
        if not ({"label", "note"} & self.model_fields_set):
            raise ValueError("At least one Wallet Case metadata field is required")
        return self


class WalletCaseLimitation(_StrictModel):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)


class WalletCaseActivityCounts(_StrictModel):
    transfers: int = Field(ge=0)
    transactions: int = Field(ge=0)
    swaps: int = Field(ge=0)
    balances: int = Field(ge=0)


class WalletCasePortfolioSnapshot(_StrictModel):
    total_balance_usd: str | None = None
    priced_assets: int = Field(ge=0)
    unpriced_assets: int = Field(ge=0)


class WalletCaseSummary(_StrictModel):
    activity_counts: WalletCaseActivityCounts
    failed_transaction_count: int = Field(ge=0)
    warning_count: int = Field(ge=0)
    portfolio_snapshot: WalletCasePortfolioSnapshot


class WalletCaseSyncProgress(_StrictModel):
    current: int = Field(ge=0)
    total: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _current_cannot_exceed_total(self):
        if self.total is not None and self.current > self.total:
            raise ValueError("progress current cannot exceed total")
        return self


class WalletCaseRequestedScope(_StrictModel):
    mode: Literal["bounded", "incremental", "resume"]
    time_window: Literal["24h", "3d", "7d", "custom"]
    start_at: str
    end_at: str
    surfaces: list[WalletIngestionSurface]
    acquisition_start_at: str
    acquisition_end_at: str
    overlap_seconds: int = Field(ge=0, le=86400)
    base_snapshot_public_id: CanonicalPublicId | None = None
    source_checkpoint_public_id: CheckpointPublicId | None = None
    continuation_plan_public_id: CheckpointContinuationPlanPublicId | None = None
    resume_page_budget: int | None = Field(
        default=None,
        strict=True,
        ge=1,
        le=10,
    )

    @model_validator(mode="after")
    def _validate_acquisition_scope(self):
        if self.mode == "bounded":
            if (
                self.acquisition_start_at != self.start_at
                or self.acquisition_end_at != self.end_at
                or self.overlap_seconds != 0
                or self.base_snapshot_public_id is not None
                or self.source_checkpoint_public_id is not None
                or self.continuation_plan_public_id is not None
                or self.resume_page_budget is not None
            ):
                raise ValueError("bounded sync acquisition must equal its requested scope")
        elif self.mode == "incremental":
            if (
                self.base_snapshot_public_id is None
                or self.source_checkpoint_public_id is not None
                or self.continuation_plan_public_id is not None
                or self.resume_page_budget is not None
            ):
                raise ValueError("incremental sync requires only a base snapshot")
        elif (
            self.time_window != "custom"
            or self.base_snapshot_public_id is None
            or self.source_checkpoint_public_id is None
            or self.overlap_seconds != 0
        ):
            raise ValueError(
                "resume sync requires a custom scope, base snapshot, and source checkpoint"
            )
        if (
            self.resume_page_budget is not None
            and self.continuation_plan_public_id is None
        ):
            raise ValueError(
                "budgeted resume requires a verified continuation plan"
            )
        return self


class WalletCaseCoverageStream(_StrictModel):
    provider: str = Field(min_length=1, max_length=64)
    stream_key: str = Field(min_length=1, max_length=64)
    completion_state: str = Field(min_length=1, max_length=32)
    error_code: str | None = Field(default=None, max_length=64)


class WalletCaseCoverage(_StrictModel):
    state: Literal["unknown", "bounded_partial", "bounded_complete"]
    requested_start_at: str
    requested_end_at: str
    requested_surfaces: list[WalletIngestionSurface]
    unavailable_surfaces: list[WalletIngestionSurface]
    incomplete_surfaces: list[WalletIngestionSurface]
    streams: list[WalletCaseCoverageStream] = Field(default_factory=list)
    full_history_proven: Literal[False] = False


class WalletCaseSyncRetry(_StrictModel):
    attempt: int = Field(ge=1)
    max_attempts: int = Field(ge=1)
    retry_at: str
    reason_code: str = Field(min_length=1, max_length=64)
    message_safe: str = Field(min_length=1, max_length=1000)


class WalletCaseSyncError(_StrictModel):
    code: str = Field(min_length=1, max_length=64)
    message_safe: str = Field(min_length=1, max_length=1000)
    retryable: bool


class WalletCaseSyncResult(_StrictModel):
    summary: WalletCaseSummary
    coverage: WalletCaseCoverage
    limitations: list[WalletCaseLimitation]
    message: str = Field(min_length=1, max_length=1000)


class WalletCaseSyncManifestDescriptor(_StrictModel):
    public_id: ManifestPublicId
    contract_version: Literal["wallet_case_sync_manifest_v1"]
    content_hash_sha256: Sha256Digest
    stream_count: int = Field(ge=0)
    page_count: int = Field(ge=0)
    response_digest_count: int = Field(ge=0)
    created_at: str


class WalletCaseSyncManifestPeriod(_StrictModel):
    start_at: str | None
    end_at: str | None


class WalletCaseSyncManifestPage(_StrictModel):
    page_index: int = Field(ge=0)
    request_cursor: str | None = Field(default=None, max_length=128)
    response_cursor: str | None = Field(default=None, max_length=128)
    requested_limit: int = Field(ge=0)
    raw_count: int = Field(ge=0)
    normalized_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    min_logical_time: str | None = Field(default=None, max_length=20)
    max_logical_time: str | None = Field(default=None, max_length=20)
    min_timestamp: str | None = None
    max_timestamp: str | None = None
    response_digest_sha256: Sha256Digest | None = None
    attempt_count: int = Field(ge=0)
    error_code: str | None = Field(default=None, max_length=64)
    fetched_at: str | None = None


class WalletCaseSyncManifestStream(_StrictModel):
    provider: str = Field(min_length=1, max_length=64)
    stream_key: str = Field(min_length=1, max_length=40)
    contract_version: str = Field(min_length=1, max_length=48)
    scope_kind: str = Field(min_length=1, max_length=24)
    requested_period: WalletCaseSyncManifestPeriod
    sort_order: str | None = Field(default=None, max_length=32)
    page_size: int = Field(ge=0)
    page_cap: int = Field(ge=0)
    completion_state: str = Field(min_length=1, max_length=24)
    termination_reason: str | None = Field(default=None, max_length=48)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    raw_count: int = Field(ge=0)
    normalized_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    first_cursor: str | None = Field(default=None, max_length=128)
    terminal_cursor: str | None = Field(default=None, max_length=128)
    bounds_verified: bool
    error_code: str | None = Field(default=None, max_length=64)
    started_at: str | None = None
    finished_at: str | None = None
    pages: list[WalletCaseSyncManifestPage]


class WalletCaseSyncManifestDocument(_StrictModel):
    contract_version: Literal["wallet_case_sync_manifest_v1"]
    case_public_id: CanonicalPublicId
    sync_public_id: CanonicalPublicId
    network: WalletCaseNetwork
    data_mode: Literal["mock", "real"]
    provider: str = Field(min_length=1, max_length=64)
    sync_state: CaseSyncState
    snapshot_period: WalletCaseSyncManifestPeriod
    acquisition_period: WalletCaseSyncManifestPeriod
    acquisition_mode: Literal["bounded", "incremental", "resume"]
    overlap_seconds: int = Field(ge=0, le=86400)
    base_snapshot_public_id: CanonicalPublicId | None = None
    requested_surfaces: list[WalletIngestionSurface]
    streams: list[WalletCaseSyncManifestStream]

    @model_validator(mode="after")
    def _validate_acquisition_lineage(self):
        if self.acquisition_mode == "bounded":
            if (
                self.overlap_seconds != 0
                or self.base_snapshot_public_id is not None
                or self.snapshot_period != self.acquisition_period
            ):
                raise ValueError("bounded acquisition manifest lineage is invalid")
        elif self.base_snapshot_public_id is None:
            raise ValueError("continued acquisition manifests require a base snapshot")
        elif self.acquisition_mode == "resume" and self.overlap_seconds != 0:
            raise ValueError("resume acquisition manifests cannot overlap")
        return self


class WalletCaseSyncManifestResponse(_StrictModel):
    manifest: WalletCaseSyncManifestDescriptor
    document: WalletCaseSyncManifestDocument


class WalletCaseStreamCheckpointLastPage(_StrictModel):
    page_index: int = Field(ge=0)
    response_cursor: str | None = Field(default=None, max_length=128)
    response_digest_sha256: Sha256Digest | None = None
    min_logical_time: str | None = Field(default=None, max_length=20)
    max_logical_time: str | None = Field(default=None, max_length=20)
    min_timestamp: str | None = None
    max_timestamp: str | None = None
    fetched_at: str | None = None


class WalletCaseStreamCheckpointDocument(_StrictModel):
    contract_version: Literal["wallet_case_stream_checkpoint_v1"]
    case_public_id: CanonicalPublicId
    source_sync_public_id: CanonicalPublicId
    source_manifest_public_id: ManifestPublicId
    source_manifest_hash_sha256: Sha256Digest
    provider: str = Field(min_length=1, max_length=64)
    stream_key: str = Field(min_length=1, max_length=40)
    provider_contract_version: str = Field(min_length=1, max_length=48)
    acquisition_mode: Literal["bounded", "incremental", "resume"]
    requested_period: WalletCaseSyncManifestPeriod
    sort_order: str | None = Field(default=None, max_length=32)
    page_size: int = Field(ge=0)
    page_cap: int = Field(ge=0)
    completion_state: str = Field(min_length=1, max_length=24)
    termination_reason: str | None = Field(default=None, max_length=48)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    resume_state: Literal["ready", "complete", "blocked"]
    resume_blocker: str | None = Field(default=None, max_length=64)
    continuation_cursor: str | None = Field(default=None, max_length=128)
    continuation_page_index: int | None = Field(default=None, ge=1)
    last_successful_page: WalletCaseStreamCheckpointLastPage | None = None

    @model_validator(mode="after")
    def _validate_continuation(self):
        ready = self.resume_state == "ready"
        if ready != (self.continuation_cursor is not None):
            raise ValueError("ready stream checkpoints require a cursor")
        if ready != (self.continuation_page_index is not None):
            raise ValueError("ready stream checkpoints require a page index")
        blocked = self.resume_state == "blocked"
        if blocked != (self.resume_blocker is not None):
            raise ValueError("only blocked stream checkpoints require a blocker")
        if self.pages_succeeded > self.page_count:
            raise ValueError("stream checkpoint page counts are inconsistent")
        return self


class WalletCaseStreamCheckpointDescriptor(_StrictModel):
    public_id: CheckpointPublicId
    contract_version: Literal["wallet_case_stream_checkpoint_v1"]
    checkpoint_hash_sha256: Sha256Digest
    provider: str = Field(min_length=1, max_length=64)
    stream_key: str = Field(min_length=1, max_length=40)
    provider_contract_version: str = Field(min_length=1, max_length=48)
    source_sync_public_id: CanonicalPublicId
    resume_state: Literal["ready", "complete", "blocked"]
    created_at: str


class WalletCaseStreamCheckpointResponse(_StrictModel):
    checkpoint: WalletCaseStreamCheckpointDescriptor
    document: WalletCaseStreamCheckpointDocument


class WalletCaseStreamCheckpointCatalogResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    checkpoint_count: int = Field(ge=0)
    ready_count: int = Field(ge=0)
    complete_count: int = Field(ge=0)
    blocked_count: int = Field(ge=0)
    checkpoints: list[WalletCaseStreamCheckpointResponse]

    @model_validator(mode="after")
    def _validate_counts(self):
        if self.checkpoint_count != len(self.checkpoints):
            raise ValueError("stream checkpoint count is inconsistent")
        if self.checkpoint_count != (
            self.ready_count + self.complete_count + self.blocked_count
        ):
            raise ValueError("stream checkpoint state counts are inconsistent")
        return self


class WalletCaseStreamCheckpointLineage(_StrictModel):
    acquisition_mode: Literal["bounded", "incremental", "resume"]
    base_snapshot_public_id: CanonicalPublicId | None = None
    parent_checkpoint_public_id: CheckpointPublicId | None = None
    chain_depth: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_lineage(self):
        if self.acquisition_mode == "bounded":
            if (
                self.base_snapshot_public_id is not None
                or self.parent_checkpoint_public_id is not None
                or self.chain_depth != 0
            ):
                raise ValueError("bounded checkpoint lineage is inconsistent")
        elif self.acquisition_mode == "incremental":
            if (
                self.base_snapshot_public_id is None
                or self.parent_checkpoint_public_id is not None
                or self.chain_depth != 0
            ):
                raise ValueError("incremental checkpoint lineage is inconsistent")
        elif (
            self.base_snapshot_public_id is None
            or self.parent_checkpoint_public_id is None
            or self.chain_depth < 1
        ):
            raise ValueError("resume checkpoint lineage is inconsistent")
        return self


class WalletCaseStreamCheckpointDetailResponse(_StrictModel):
    checkpoint: WalletCaseStreamCheckpointDescriptor
    document: WalletCaseStreamCheckpointDocument
    lineage: WalletCaseStreamCheckpointLineage


class WalletCaseStreamCheckpointHistoryItem(_StrictModel):
    checkpoint: WalletCaseStreamCheckpointDescriptor
    lineage: WalletCaseStreamCheckpointLineage
    continuation_page_index: int | None = Field(default=None, ge=1)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)

    @model_validator(mode="after")
    def _validate_page_counts(self):
        if self.pages_succeeded > self.page_count:
            raise ValueError("checkpoint history page counts are inconsistent")
        if (self.checkpoint.resume_state == "ready") != (
            self.continuation_page_index is not None
        ):
            raise ValueError("checkpoint history continuation is inconsistent")
        return self


class WalletCaseStreamCheckpointHistoryAggregate(_StrictModel):
    total_revisions: int = Field(ge=0)
    returned_count: int = Field(ge=0, le=50)


class WalletCaseStreamCheckpointHistoryPage(_StrictModel):
    limit: int = Field(ge=1, le=50)
    has_more: bool
    next_cursor: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def _validate_cursor(self):
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("checkpoint history cursor is inconsistent")
        return self


class WalletCaseStreamCheckpointHistoryResponse(_StrictModel):
    contract_version: Literal["wallet_case_stream_checkpoint_history_v1"]
    case_public_id: CanonicalPublicId
    revision_cutoff_public_id: CheckpointPublicId | None = None
    items: list[WalletCaseStreamCheckpointHistoryItem] = Field(max_length=50)
    aggregate: WalletCaseStreamCheckpointHistoryAggregate
    page: WalletCaseStreamCheckpointHistoryPage
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _validate_catalog(self):
        if self.aggregate.returned_count != len(self.items):
            raise ValueError("checkpoint history returned count is inconsistent")
        if self.aggregate.returned_count > self.aggregate.total_revisions:
            raise ValueError("checkpoint history returned count exceeds total")
        if len(self.items) > self.page.limit:
            raise ValueError("checkpoint history page exceeds its limit")
        if (self.revision_cutoff_public_id is None) != (
            self.aggregate.total_revisions == 0
        ):
            raise ValueError("checkpoint history cutoff is inconsistent")
        return self


class WalletCaseStreamCheckpointChainRevision(_StrictModel):
    ordinal: int = Field(ge=0, le=99)
    checkpoint: WalletCaseStreamCheckpointDescriptor
    acquisition_mode: Literal["bounded", "incremental", "resume"]
    base_snapshot_public_id: CanonicalPublicId | None = None
    parent_checkpoint_public_id: CheckpointPublicId | None = None
    source_manifest_public_id: ManifestPublicId
    source_manifest_hash_sha256: Sha256Digest
    requested_period: WalletCaseSyncManifestPeriod
    continuation_page_index: int | None = Field(default=None, ge=1)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    last_response_digest_sha256: Sha256Digest | None = None

    @model_validator(mode="after")
    def _validate_revision(self):
        if self.pages_succeeded > self.page_count:
            raise ValueError("checkpoint chain page counts are inconsistent")
        if (self.checkpoint.resume_state == "ready") != (
            self.continuation_page_index is not None
        ):
            raise ValueError("checkpoint chain continuation is inconsistent")
        if self.source_manifest_public_id != (
            f"smf_{self.source_manifest_hash_sha256}"
        ):
            raise ValueError("checkpoint chain manifest identity is inconsistent")
        return self


class WalletCaseStreamCheckpointChainAggregate(_StrictModel):
    revision_count: int = Field(ge=1, le=100)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)


class WalletCaseStreamCheckpointChainDocument(_StrictModel):
    contract_version: Literal["wallet_case_stream_checkpoint_chain_v1"]
    case_public_id: CanonicalPublicId
    tip_checkpoint_public_id: CheckpointPublicId
    provider: str = Field(min_length=1, max_length=64)
    stream_key: str = Field(min_length=1, max_length=40)
    provider_contract_version: str = Field(min_length=1, max_length=48)
    root_acquisition_mode: Literal["bounded", "incremental"]
    root_base_snapshot_public_id: CanonicalPublicId | None = None
    current_resume_state: Literal["ready", "complete", "blocked"]
    next_page_index: int | None = Field(default=None, ge=1)
    aggregate: WalletCaseStreamCheckpointChainAggregate
    revisions: list[WalletCaseStreamCheckpointChainRevision] = Field(
        min_length=1,
        max_length=100,
    )
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _validate_chain(self):
        if self.aggregate.revision_count != len(self.revisions):
            raise ValueError("checkpoint chain revision count is inconsistent")
        if self.aggregate.page_count != sum(
            item.page_count for item in self.revisions
        ):
            raise ValueError("checkpoint chain page count is inconsistent")
        if self.aggregate.pages_succeeded != sum(
            item.pages_succeeded for item in self.revisions
        ):
            raise ValueError("checkpoint chain success count is inconsistent")
        if self.aggregate.pages_succeeded > self.aggregate.page_count:
            raise ValueError("checkpoint chain aggregate is inconsistent")
        root = self.revisions[0]
        tip = self.revisions[-1]
        if (
            root.ordinal != 0
            or root.acquisition_mode != self.root_acquisition_mode
            or root.base_snapshot_public_id
            != self.root_base_snapshot_public_id
            or root.parent_checkpoint_public_id is not None
            or (root.acquisition_mode == "bounded")
            != (root.base_snapshot_public_id is None)
            or tip.checkpoint.public_id != self.tip_checkpoint_public_id
            or tip.checkpoint.resume_state != self.current_resume_state
            or tip.continuation_page_index != self.next_page_index
        ):
            raise ValueError("checkpoint chain endpoints are inconsistent")
        for index, revision in enumerate(self.revisions):
            if (
                revision.ordinal != index
                or revision.checkpoint.provider != self.provider
                or revision.checkpoint.stream_key != self.stream_key
                or revision.checkpoint.provider_contract_version
                != self.provider_contract_version
            ):
                raise ValueError("checkpoint chain revision identity is inconsistent")
            if index == 0:
                continue
            parent = self.revisions[index - 1]
            if (
                revision.acquisition_mode != "resume"
                or revision.parent_checkpoint_public_id
                != parent.checkpoint.public_id
                or revision.base_snapshot_public_id
                != parent.checkpoint.source_sync_public_id
            ):
                raise ValueError("checkpoint chain parent lineage is inconsistent")
        return self


class WalletCaseStreamCheckpointChainDescriptor(_StrictModel):
    public_id: CheckpointChainPublicId
    contract_version: Literal["wallet_case_stream_checkpoint_chain_v1"]
    content_hash_sha256: Sha256Digest
    revision_count: int = Field(ge=1, le=100)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)


class WalletCaseStreamCheckpointChainResponse(_StrictModel):
    chain: WalletCaseStreamCheckpointChainDescriptor
    document: WalletCaseStreamCheckpointChainDocument

    @model_validator(mode="after")
    def _validate_content_address(self):
        canonical = json.dumps(
            self.document.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        if (
            self.chain.public_id != f"cch_{digest}"
            or self.chain.content_hash_sha256 != digest
            or self.chain.contract_version != self.document.contract_version
            or self.chain.revision_count
            != self.document.aggregate.revision_count
            or self.chain.page_count != self.document.aggregate.page_count
            or self.chain.pages_succeeded
            != self.document.aggregate.pages_succeeded
        ):
            raise ValueError("checkpoint chain content address is inconsistent")
        return self


class WalletCaseBackfillProgressFrontier(_StrictModel):
    checkpoint_public_id: CheckpointPublicId
    page: WalletCaseStreamCheckpointLastPage


class WalletCaseBackfillProgressStream(_StrictModel):
    provider: str = Field(min_length=1, max_length=64)
    stream_key: str = Field(min_length=1, max_length=40)
    provider_contract_version: str = Field(min_length=1, max_length=48)
    root_checkpoint_public_id: CheckpointPublicId
    tip_checkpoint: WalletCaseStreamCheckpointDescriptor
    chain_public_id: CheckpointChainPublicId
    chain_content_hash_sha256: Sha256Digest
    root_acquisition_mode: Literal["bounded", "incremental"]
    requested_period: WalletCaseSyncManifestPeriod
    revision_count: int = Field(ge=1, le=100)
    initial_page_count: int = Field(ge=0)
    initial_pages_succeeded: int = Field(ge=0)
    continuation_revision_count: int = Field(ge=0, le=99)
    continuation_page_count: int = Field(ge=0)
    continuation_pages_succeeded: int = Field(ge=0)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    resume_state: Literal["ready", "complete", "blocked"]
    requested_interval_complete: bool
    next_page_index: int | None = Field(default=None, ge=1)
    termination_reason: str | None = Field(default=None, max_length=48)
    resume_blocker: str | None = Field(default=None, max_length=64)
    root_frontier: WalletCaseBackfillProgressFrontier | None = None
    current_frontier: WalletCaseBackfillProgressFrontier | None = None
    frontier_advanced: bool

    @model_validator(mode="after")
    def _validate_stream(self):
        if (
            self.tip_checkpoint.provider != self.provider
            or self.tip_checkpoint.stream_key != self.stream_key
            or self.tip_checkpoint.provider_contract_version
            != self.provider_contract_version
            or self.tip_checkpoint.resume_state != self.resume_state
            or self.chain_public_id
            != f"cch_{self.chain_content_hash_sha256}"
            or self.revision_count != self.continuation_revision_count + 1
            or self.initial_pages_succeeded > self.initial_page_count
            or self.continuation_pages_succeeded
            > self.continuation_page_count
            or self.page_count
            != self.initial_page_count + self.continuation_page_count
            or self.pages_succeeded
            != self.initial_pages_succeeded
            + self.continuation_pages_succeeded
            or self.pages_succeeded > self.page_count
            or self.requested_interval_complete
            != (self.resume_state == "complete")
            or (self.resume_state == "ready")
            != (self.next_page_index is not None)
            or (self.resume_state == "blocked")
            != (self.resume_blocker is not None)
            or (self.root_frontier is None)
            != (self.initial_pages_succeeded == 0)
            or (self.current_frontier is None)
            != (self.pages_succeeded == 0)
            or (
                self.root_frontier is not None
                and self.root_frontier.checkpoint_public_id
                != self.root_checkpoint_public_id
            )
            or self.frontier_advanced
            != (
                self.root_frontier is not None
                and self.current_frontier is not None
                and self.root_frontier.page != self.current_frontier.page
            )
        ):
            raise ValueError("backfill progress stream is inconsistent")
        return self


class WalletCaseBackfillProgressAggregate(_StrictModel):
    stream_count: int = Field(ge=0, le=32)
    ready_count: int = Field(ge=0, le=32)
    complete_count: int = Field(ge=0, le=32)
    blocked_count: int = Field(ge=0, le=32)
    revision_count: int = Field(ge=0, le=3200)
    continuation_revision_count: int = Field(ge=0, le=3168)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    continuation_page_count: int = Field(ge=0)
    continuation_pages_succeeded: int = Field(ge=0)
    observed_frontier_count: int = Field(ge=0, le=32)
    advanced_frontier_count: int = Field(ge=0, le=32)


class WalletCaseBackfillProgressDocument(_StrictModel):
    contract_version: Literal["wallet_case_backfill_progress_v1"]
    case_public_id: CanonicalPublicId
    checkpoint_cutoff_public_id: CheckpointPublicId | None = None
    aggregate: WalletCaseBackfillProgressAggregate
    streams: list[WalletCaseBackfillProgressStream] = Field(max_length=32)
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _validate_progress(self):
        states = [item.resume_state for item in self.streams]
        keys = [f"{item.provider}\0{item.stream_key}" for item in self.streams]
        expected = {
            "stream_count": len(self.streams),
            "ready_count": states.count("ready"),
            "complete_count": states.count("complete"),
            "blocked_count": states.count("blocked"),
            "revision_count": sum(item.revision_count for item in self.streams),
            "continuation_revision_count": sum(
                item.continuation_revision_count for item in self.streams
            ),
            "page_count": sum(item.page_count for item in self.streams),
            "pages_succeeded": sum(
                item.pages_succeeded for item in self.streams
            ),
            "continuation_page_count": sum(
                item.continuation_page_count for item in self.streams
            ),
            "continuation_pages_succeeded": sum(
                item.continuation_pages_succeeded for item in self.streams
            ),
            "observed_frontier_count": sum(
                item.current_frontier is not None for item in self.streams
            ),
            "advanced_frontier_count": sum(
                item.frontier_advanced for item in self.streams
            ),
        }
        if (
            self.aggregate.model_dump() != expected
            or len(set(keys)) != len(keys)
            or keys != sorted(keys)
            or (self.checkpoint_cutoff_public_id is None)
            != (not self.streams)
            or (
                self.checkpoint_cutoff_public_id is not None
                and self.checkpoint_cutoff_public_id
                not in {
                    item.tip_checkpoint.public_id for item in self.streams
                }
            )
        ):
            raise ValueError("backfill progress is inconsistent")
        return self


class WalletCaseBackfillProgressDescriptor(_StrictModel):
    public_id: BackfillProgressPublicId
    contract_version: Literal["wallet_case_backfill_progress_v1"]
    content_hash_sha256: Sha256Digest
    checkpoint_cutoff_public_id: CheckpointPublicId | None = None
    stream_count: int = Field(ge=0, le=32)
    ready_count: int = Field(ge=0, le=32)
    complete_count: int = Field(ge=0, le=32)
    blocked_count: int = Field(ge=0, le=32)
    revision_count: int = Field(ge=0, le=3200)
    continuation_revision_count: int = Field(ge=0, le=3168)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    continuation_page_count: int = Field(ge=0)
    continuation_pages_succeeded: int = Field(ge=0)
    observed_frontier_count: int = Field(ge=0, le=32)
    advanced_frontier_count: int = Field(ge=0, le=32)


class WalletCaseBackfillProgressResponse(_StrictModel):
    progress: WalletCaseBackfillProgressDescriptor
    document: WalletCaseBackfillProgressDocument

    @model_validator(mode="after")
    def _validate_content_address(self):
        canonical = json.dumps(
            self.document.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        aggregate = self.document.aggregate.model_dump()
        descriptor = self.progress.model_dump()
        if any(descriptor[key] != value for key, value in aggregate.items()):
            raise ValueError("backfill progress content address is inconsistent")
        if (
            self.progress.public_id != f"bfp_{digest}"
            or self.progress.content_hash_sha256 != digest
            or self.progress.contract_version != self.document.contract_version
            or self.progress.checkpoint_cutoff_public_id
            != self.document.checkpoint_cutoff_public_id
        ):
            raise ValueError("backfill progress content address is inconsistent")
        return self


class WalletCaseCheckpointContinuationPlanStream(_StrictModel):
    provider: str = Field(min_length=1, max_length=64)
    stream_key: str = Field(min_length=1, max_length=40)
    provider_contract_version: str = Field(min_length=1, max_length=48)
    tip_checkpoint: WalletCaseStreamCheckpointDescriptor
    chain_public_id: CheckpointChainPublicId
    chain_content_hash_sha256: Sha256Digest
    revision_count: int = Field(ge=1, le=100)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    resume_state: Literal["ready", "complete", "blocked"]
    next_page_index: int | None = Field(default=None, ge=1)
    resume_blocker: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _validate_stream(self):
        if (
            self.tip_checkpoint.provider != self.provider
            or self.tip_checkpoint.stream_key != self.stream_key
            or self.tip_checkpoint.provider_contract_version
            != self.provider_contract_version
            or self.tip_checkpoint.resume_state != self.resume_state
            or self.chain_public_id
            != f"cch_{self.chain_content_hash_sha256}"
            or self.pages_succeeded > self.page_count
            or (self.resume_state == "ready")
            != (self.next_page_index is not None)
            or (self.resume_state == "blocked")
            != (self.resume_blocker is not None)
        ):
            raise ValueError("checkpoint continuation plan stream is inconsistent")
        return self


class WalletCaseCheckpointContinuationPlanAggregate(_StrictModel):
    stream_count: int = Field(ge=0, le=32)
    ready_count: int = Field(ge=0, le=32)
    complete_count: int = Field(ge=0, le=32)
    blocked_count: int = Field(ge=0, le=32)
    revision_count: int = Field(ge=0, le=3200)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)


class WalletCaseCheckpointContinuationPlanDocument(_StrictModel):
    contract_version: Literal["wallet_case_checkpoint_continuation_plan_v1"]
    case_public_id: CanonicalPublicId
    checkpoint_cutoff_public_id: CheckpointPublicId | None = None
    aggregate: WalletCaseCheckpointContinuationPlanAggregate
    streams: list[WalletCaseCheckpointContinuationPlanStream] = Field(
        max_length=32,
    )
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _validate_plan(self):
        states = [item.resume_state for item in self.streams]
        keys = [f"{item.provider}\0{item.stream_key}" for item in self.streams]
        if (
            self.aggregate.stream_count != len(self.streams)
            or self.aggregate.ready_count != states.count("ready")
            or self.aggregate.complete_count != states.count("complete")
            or self.aggregate.blocked_count != states.count("blocked")
            or self.aggregate.stream_count
            != self.aggregate.ready_count
            + self.aggregate.complete_count
            + self.aggregate.blocked_count
            or self.aggregate.revision_count
            != sum(item.revision_count for item in self.streams)
            or self.aggregate.page_count
            != sum(item.page_count for item in self.streams)
            or self.aggregate.pages_succeeded
            != sum(item.pages_succeeded for item in self.streams)
            or self.aggregate.pages_succeeded > self.aggregate.page_count
            or len(set(keys)) != len(keys)
            or keys != sorted(keys)
            or (self.checkpoint_cutoff_public_id is None) != (not self.streams)
            or (
                self.checkpoint_cutoff_public_id is not None
                and self.checkpoint_cutoff_public_id
                not in {item.tip_checkpoint.public_id for item in self.streams}
            )
        ):
            raise ValueError("checkpoint continuation plan is inconsistent")
        return self


class WalletCaseCheckpointContinuationPlanDescriptor(_StrictModel):
    public_id: CheckpointContinuationPlanPublicId
    contract_version: Literal["wallet_case_checkpoint_continuation_plan_v1"]
    content_hash_sha256: Sha256Digest
    checkpoint_cutoff_public_id: CheckpointPublicId | None = None
    stream_count: int = Field(ge=0, le=32)
    ready_count: int = Field(ge=0, le=32)
    complete_count: int = Field(ge=0, le=32)
    blocked_count: int = Field(ge=0, le=32)
    revision_count: int = Field(ge=0, le=3200)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)


class WalletCaseCheckpointContinuationPlanResponse(_StrictModel):
    plan: WalletCaseCheckpointContinuationPlanDescriptor
    document: WalletCaseCheckpointContinuationPlanDocument

    @model_validator(mode="after")
    def _validate_content_address(self):
        canonical = json.dumps(
            self.document.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        aggregate = self.document.aggregate
        if (
            self.plan.public_id != f"cpl_{digest}"
            or self.plan.content_hash_sha256 != digest
            or self.plan.contract_version != self.document.contract_version
            or self.plan.checkpoint_cutoff_public_id
            != self.document.checkpoint_cutoff_public_id
            or self.plan.stream_count != aggregate.stream_count
            or self.plan.ready_count != aggregate.ready_count
            or self.plan.complete_count != aggregate.complete_count
            or self.plan.blocked_count != aggregate.blocked_count
            or self.plan.revision_count != aggregate.revision_count
            or self.plan.page_count != aggregate.page_count
            or self.plan.pages_succeeded != aggregate.pages_succeeded
        ):
            raise ValueError(
                "checkpoint continuation plan content address is inconsistent"
            )
        return self


class WalletCaseCheckpointContinuationReceiptInput(_StrictModel):
    continuation_plan_public_id: CheckpointContinuationPlanPublicId
    checkpoint: WalletCaseStreamCheckpointDescriptor
    chain_public_id: CheckpointChainPublicId
    chain_content_hash_sha256: Sha256Digest
    revision_count: int = Field(ge=1, le=99)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    next_page_index: int = Field(ge=1)

    @model_validator(mode="after")
    def _validate_input(self):
        if (
            self.checkpoint.resume_state != "ready"
            or self.chain_public_id != f"cch_{self.chain_content_hash_sha256}"
            or self.pages_succeeded > self.page_count
        ):
            raise ValueError("continuation receipt input is inconsistent")
        return self


class WalletCaseCheckpointContinuationReceiptOutput(_StrictModel):
    checkpoint: WalletCaseStreamCheckpointDescriptor
    chain_public_id: CheckpointChainPublicId
    chain_content_hash_sha256: Sha256Digest
    revision_count: int = Field(ge=2, le=100)
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(ge=0)
    resume_state: Literal["ready", "complete", "blocked"]
    next_page_index: int | None = Field(default=None, ge=1)
    resume_blocker: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def _validate_output(self):
        if (
            self.checkpoint.resume_state != self.resume_state
            or self.chain_public_id != f"cch_{self.chain_content_hash_sha256}"
            or self.pages_succeeded > self.page_count
            or (self.resume_state == "ready")
            != (self.next_page_index is not None)
            or (self.resume_state == "blocked")
            != (self.resume_blocker is not None)
        ):
            raise ValueError("continuation receipt output is inconsistent")
        return self


class WalletCaseCheckpointContinuationReceiptTransition(_StrictModel):
    checkpoint_changed: Literal[True]
    plan_changed: Literal[True]
    revision_delta: Literal[1]
    page_count_delta: int = Field(ge=0)
    pages_succeeded_delta: int = Field(ge=0)


class WalletCaseCheckpointContinuationReceiptDocument(_StrictModel):
    contract_version: Literal["wallet_case_checkpoint_continuation_receipt_v1"]
    case_public_id: CanonicalPublicId
    sync_public_id: CanonicalPublicId
    input: WalletCaseCheckpointContinuationReceiptInput
    output: WalletCaseCheckpointContinuationReceiptOutput
    after_plan: WalletCaseCheckpointContinuationPlanResponse
    transition: WalletCaseCheckpointContinuationReceiptTransition
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _validate_receipt(self):
        source = self.input
        output = self.output
        transition = self.transition
        matching_streams = [
            stream
            for stream in self.after_plan.document.streams
            if stream.provider == output.checkpoint.provider
            and stream.stream_key == output.checkpoint.stream_key
        ]
        if len(matching_streams) != 1:
            raise ValueError("continuation receipt output stream is missing")
        stream = matching_streams[0]
        if (
            self.after_plan.document.case_public_id != self.case_public_id
            or source.checkpoint.provider != output.checkpoint.provider
            or source.checkpoint.stream_key != output.checkpoint.stream_key
            or source.checkpoint.provider_contract_version
            != output.checkpoint.provider_contract_version
            or output.checkpoint.source_sync_public_id != self.sync_public_id
            or source.checkpoint.public_id == output.checkpoint.public_id
            or source.continuation_plan_public_id
            == self.after_plan.plan.public_id
            or transition.page_count_delta
            != output.page_count - source.page_count
            or transition.pages_succeeded_delta
            != output.pages_succeeded - source.pages_succeeded
            or output.revision_count != source.revision_count + 1
            or stream.tip_checkpoint.public_id
            != output.checkpoint.public_id
            or stream.chain_public_id != output.chain_public_id
            or stream.chain_content_hash_sha256
            != output.chain_content_hash_sha256
            or stream.revision_count != output.revision_count
            or stream.page_count != output.page_count
            or stream.pages_succeeded != output.pages_succeeded
            or stream.resume_state != output.resume_state
            or stream.next_page_index != output.next_page_index
            or stream.resume_blocker != output.resume_blocker
        ):
            raise ValueError("continuation receipt transition is inconsistent")
        return self


class WalletCaseCheckpointContinuationReceiptDescriptor(_StrictModel):
    public_id: CheckpointContinuationReceiptPublicId
    contract_version: Literal["wallet_case_checkpoint_continuation_receipt_v1"]
    content_hash_sha256: Sha256Digest
    sync_public_id: CanonicalPublicId
    input_plan_public_id: CheckpointContinuationPlanPublicId
    input_checkpoint_public_id: CheckpointPublicId
    output_checkpoint_public_id: CheckpointPublicId
    after_plan_public_id: CheckpointContinuationPlanPublicId
    revision_delta: Literal[1]
    page_count_delta: int = Field(ge=0)
    pages_succeeded_delta: int = Field(ge=0)


class WalletCaseCheckpointContinuationReceiptResponse(_StrictModel):
    receipt: WalletCaseCheckpointContinuationReceiptDescriptor
    document: WalletCaseCheckpointContinuationReceiptDocument

    @model_validator(mode="after")
    def _validate_content_address(self):
        canonical = json.dumps(
            self.document.model_dump(mode="json"),
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        source = self.document.input
        output = self.document.output
        transition = self.document.transition
        if (
            self.receipt.public_id != f"ctr_{digest}"
            or self.receipt.content_hash_sha256 != digest
            or self.receipt.contract_version != self.document.contract_version
            or self.receipt.sync_public_id != self.document.sync_public_id
            or self.receipt.input_plan_public_id
            != source.continuation_plan_public_id
            or self.receipt.input_checkpoint_public_id
            != source.checkpoint.public_id
            or self.receipt.output_checkpoint_public_id
            != output.checkpoint.public_id
            or self.receipt.after_plan_public_id
            != self.document.after_plan.plan.public_id
            or self.receipt.revision_delta != transition.revision_delta
            or self.receipt.page_count_delta != transition.page_count_delta
            or self.receipt.pages_succeeded_delta
            != transition.pages_succeeded_delta
        ):
            raise ValueError(
                "checkpoint continuation receipt content address is inconsistent"
            )
        return self


class WalletCaseCheckpointContinuationReceiptV2Input(
    WalletCaseCheckpointContinuationReceiptInput
):
    page_budget: int = Field(strict=True, ge=1, le=10)


class WalletCaseCheckpointContinuationReceiptV2Transition(
    WalletCaseCheckpointContinuationReceiptTransition
):
    page_budget_consumed: int = Field(strict=True, ge=0, le=10)
    page_budget_remaining: int = Field(strict=True, ge=0, le=10)

    @model_validator(mode="after")
    def _validate_budget_consumption(self):
        if (
            self.page_budget_consumed != self.page_count_delta
            or self.pages_succeeded_delta > self.page_budget_consumed
        ):
            raise ValueError(
                "continuation receipt budget consumption is inconsistent"
            )
        return self


class WalletCaseCheckpointContinuationReceiptV2Document(
    WalletCaseCheckpointContinuationReceiptDocument
):
    contract_version: Literal[
        "wallet_case_checkpoint_continuation_receipt_v2"
    ]
    input: WalletCaseCheckpointContinuationReceiptV2Input
    transition: WalletCaseCheckpointContinuationReceiptV2Transition

    @model_validator(mode="after")
    def _validate_budget_accounting(self):
        if (
            self.transition.page_budget_consumed
            + self.transition.page_budget_remaining
            != self.input.page_budget
        ):
            raise ValueError(
                "continuation receipt budget accounting is inconsistent"
            )
        return self


class WalletCaseCheckpointContinuationReceiptV2Descriptor(
    WalletCaseCheckpointContinuationReceiptDescriptor
):
    contract_version: Literal[
        "wallet_case_checkpoint_continuation_receipt_v2"
    ]
    page_budget: int = Field(strict=True, ge=1, le=10)
    page_budget_consumed: int = Field(strict=True, ge=0, le=10)
    page_budget_remaining: int = Field(strict=True, ge=0, le=10)


class WalletCaseCheckpointContinuationReceiptV2Response(
    WalletCaseCheckpointContinuationReceiptResponse
):
    receipt: WalletCaseCheckpointContinuationReceiptV2Descriptor
    document: WalletCaseCheckpointContinuationReceiptV2Document

    @model_validator(mode="after")
    def _validate_budget_descriptor(self):
        if (
            self.receipt.page_budget != self.document.input.page_budget
            or self.receipt.page_budget_consumed
            != self.document.transition.page_budget_consumed
            or self.receipt.page_budget_remaining
            != self.document.transition.page_budget_remaining
        ):
            raise ValueError(
                "continuation receipt budget descriptor is inconsistent"
            )
        return self


class WalletCaseSyncResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    public_id: CanonicalPublicId
    status_version: int = Field(ge=1)
    state: CaseSyncState
    stage: str = Field(min_length=1, max_length=32)
    progress: WalletCaseSyncProgress
    poll_after_ms: int = Field(ge=500, le=15000)
    cancel_requested: bool
    retry: WalletCaseSyncRetry | None = None
    error: WalletCaseSyncError | None = None
    result: WalletCaseSyncResult | None = None
    acquisition_manifest: WalletCaseSyncManifestDescriptor | None = None
    provider: str = Field(min_length=1, max_length=64)
    data_mode: Literal["mock", "real"]
    requested_scope: WalletCaseRequestedScope
    coverage: WalletCaseCoverage
    summary: WalletCaseSummary
    limitations: list[WalletCaseLimitation]
    message: str = Field(min_length=1, max_length=1000)
    created_at: str
    updated_at: str
    started_at: str | None = None
    completed_at: str | None = None

    @model_validator(mode="after")
    def _validate_job_state(self):
        terminal = self.state in {"partial", "succeeded", "failed", "cancelled"}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal sync state must match completed_at")
        if self.state in {"partial", "succeeded"}:
            if self.result is None or self.error is not None:
                raise ValueError("usable terminal sync requires only a result")
        elif self.result is not None:
            raise ValueError("only partial or succeeded sync may publish a result")
        if self.state == "failed":
            if self.error is None:
                raise ValueError("failed sync requires a safe error")
        elif self.error is not None:
            raise ValueError("only failed sync may publish a terminal error")
        if self.retry is not None and not (
            self.state == "queued" and self.stage == "retry_wait"
        ):
            raise ValueError("retry metadata requires queued retry_wait state")
        if self.state == "queued" and self.started_at is None:
            return self
        if self.state == "running" and self.started_at is None:
            raise ValueError("running sync requires started_at")
        return self


class WalletCaseResponse(_StrictModel):
    public_id: CanonicalPublicId
    network: WalletCaseNetwork
    data_environment: WalletCaseDataEnvironment
    canonical_wallet_key: str = Field(min_length=1, max_length=76)
    identity_version: str = Field(min_length=1, max_length=24)
    display_address: str = Field(min_length=1, max_length=128)
    label: str | None = Field(default=None, max_length=120)
    note: str | None = Field(default=None, max_length=4000)
    metadata_version: int = Field(ge=1)
    created_at: str
    updated_at: str
    archived_at: str | None = None
    latest_sync: WalletCaseSyncResponse | None = None
    latest_sync_attempt: WalletCaseSyncResponse | None = None
    active_sync: WalletCaseSyncResponse | None = None
    current_snapshot: WalletCaseSyncResponse | None = None
    summary: WalletCaseSummary
    limitations: list[WalletCaseLimitation]


class WalletCaseUpsertResponse(_StrictModel):
    created: bool
    case: WalletCaseResponse


class WalletCaseListResponse(_StrictModel):
    cases: list[WalletCaseResponse]
    limit: int = Field(ge=1, le=50)
    state: Literal["active", "archived"]
    query: str | None = Field(default=None, min_length=1, max_length=120)
    network: Literal["ton-mainnet", "ton-testnet"] | None = None
    data_environment: Literal["demo", "live"] | None = None
    truncated: bool
    next_cursor: str | None = Field(default=None, min_length=1, max_length=1024)

    @model_validator(mode="after")
    def _validate_page(self):
        if len(self.cases) > self.limit:
            raise ValueError("Case catalog cannot exceed its requested limit")
        if self.truncated != (self.next_cursor is not None):
            raise ValueError("truncated Case catalog pages require a cursor")
        if self.truncated and len(self.cases) != self.limit:
            raise ValueError("truncated Case catalog pages must be full")
        return self


class WalletCaseDeletionCounts(_StrictModel):
    syncs: int = Field(ge=0)
    ingestion_runs: int = Field(ge=0)
    evidence_verifications: int = Field(ge=0)
    report_revisions: int = Field(ge=0)


class WalletCaseDeletionResponse(_StrictModel):
    deleted: Literal[True]
    case_public_id: CanonicalPublicId
    audit_event_public_id: CanonicalPublicId
    deleted_at: str
    removed: WalletCaseDeletionCounts
