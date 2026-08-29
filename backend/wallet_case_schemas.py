"""Public contracts for the Wallet Case application facade."""

from __future__ import annotations

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

    @model_validator(mode="after")
    def _validate_acquisition_scope(self):
        if self.mode == "bounded":
            if (
                self.acquisition_start_at != self.start_at
                or self.acquisition_end_at != self.end_at
                or self.overlap_seconds != 0
                or self.base_snapshot_public_id is not None
                or self.source_checkpoint_public_id is not None
            ):
                raise ValueError("bounded sync acquisition must equal its requested scope")
        elif self.mode == "incremental":
            if (
                self.base_snapshot_public_id is None
                or self.source_checkpoint_public_id is not None
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
