"""Pydantic schemas for request/response validation.

The analysis response is large and partly dynamic (it includes a Cyrillic
``Вывод`` key), so the response is returned as a plain dict from the service
layer. Here we strictly validate the *request* and document the response shape
for OpenAPI via a permissive model.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

WalletIngestionSurface = Literal[
    "transfers",
    "transactions",
    "swaps",
    "balances",
    "jettons",
]
WalletIngestionStatus = Literal[
    "planned",
    "queued",
    "running",
    "success",
    "partial",
    "error",
    "stale",
]
WalletSourceStatus = Literal[
    "live",
    "mock",
    "offline",
    "limited",
    "unavailable",
    "error",
]
PositiveStrictRunId = Annotated[int, Field(strict=True, ge=1)]


class AnalyzeRequest(BaseModel):
    pool_url: str = Field(
        ...,
        description="GeckoTerminal TON pool URL to analyze.",
        examples=["https://www.geckoterminal.com/ton/pools/EQCp_C-wPq2Z"],
    )
    time_window: Literal["24h", "3d", "7d", "custom"] = Field(
        ..., description="Analysis window."
    )
    custom_start: Optional[str] = Field(
        None, description="ISO start datetime (required when time_window=custom)."
    )
    custom_end: Optional[str] = Field(
        None, description="ISO end datetime (required when time_window=custom)."
    )


class HealthResponse(BaseModel):
    status: str
    version: str
    is_mock: bool
    data_mode: str


class ProviderStatus(BaseModel):
    configured: bool
    available: bool
    message: str


class ProvidersStatusResponse(BaseModel):
    data_mode: str
    geckoterminal: ProviderStatus
    ton_provider: ProviderStatus
    bitquery: ProviderStatus
    stonfi: ProviderStatus
    tonapi: ProviderStatus
    wallet_activity: ProviderStatus


class WalletIngestionPreviewRequest(BaseModel):
    wallet_address: str = Field(
        ...,
        description="TON wallet address to inspect before ingestion.",
        max_length=128,
    )
    time_window: Literal["24h", "3d", "7d", "custom"] = Field(
        default="24h",
        description="Wallet activity ingestion window.",
    )
    custom_start: Optional[str] = Field(
        None, description="ISO start datetime required when time_window=custom."
    )
    custom_end: Optional[str] = Field(
        None, description="ISO end datetime required when time_window=custom."
    )
    surfaces: list[WalletIngestionSurface] = Field(
        default_factory=lambda: [
            "transfers",
            "transactions",
            "swaps",
            "balances",
            "jettons",
        ],
        description="Wallet activity surfaces requested for coverage preview.",
    )

    @field_validator("wallet_address")
    @classmethod
    def _wallet_address_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Wallet address is required")
        return cleaned

    @field_validator("surfaces")
    @classmethod
    def _surfaces_required(cls, value: list[WalletIngestionSurface]):
        if not value:
            raise ValueError("At least one wallet activity surface is required")
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _custom_window_requires_bounds(self):
        if self.time_window == "custom" and not (
            self.custom_start and self.custom_end
        ):
            raise ValueError(
                "custom_start and custom_end are required for custom windows"
            )
        return self


class WalletActivityProviderEvidence(BaseModel):
    provider: str
    data_mode: Literal["mock", "real"]
    source_status: WalletSourceStatus
    warnings: list[str] = Field(default_factory=list)
    freshness: str | None = None
    raw_count: int = Field(default=0, ge=0)
    normalized_count: int = Field(default=0, ge=0)

    @field_validator("provider")
    @classmethod
    def _provider_required(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Provider is required")
        return cleaned


class WalletActivityAcquisitionPageRecord(BaseModel):
    page_index: int = Field(ge=0)
    request_cursor: str | None = None
    response_cursor: str | None = None
    requested_limit: int = Field(ge=1)
    raw_count: int = Field(ge=0)
    normalized_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    min_logical_time: str | None = None
    max_logical_time: str | None = None
    min_timestamp: str | None = None
    max_timestamp: str | None = None
    response_digest: str = ""
    attempt_count: int = Field(default=1, ge=1)
    error_code: str | None = None
    error_message: str | None = None
    fetched_at: str | None = None


class WalletActivityAcquisitionStreamRecord(BaseModel):
    provider: str
    stream_key: str
    contract_version: str
    scope_kind: str
    requested_start: str | None = None
    requested_end: str | None = None
    query_filters: dict[str, Any] = Field(default_factory=dict)
    sort_order: str
    page_size: int = Field(ge=1)
    page_cap: int = Field(ge=1)
    completion_state: Literal[
        "complete",
        "incomplete",
        "error",
        "preview_only",
        "legacy_unavailable",
    ]
    termination_reason: str | None = None
    page_count: int = Field(ge=0)
    pages_succeeded: int = Field(default=0, ge=0)
    raw_count: int = Field(ge=0)
    normalized_count: int = Field(ge=0)
    duplicate_count: int = Field(ge=0)
    first_cursor: str | None = None
    terminal_cursor: str | None = None
    bounds_verified: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None
    pages: list[WalletActivityAcquisitionPageRecord] = Field(
        default_factory=list
    )


class WalletIngestionPreviewResponse(BaseModel):
    success: bool
    wallet_address: str
    time_window: str
    requested_surfaces: list[WalletIngestionSurface]
    provider_coverage: list[WalletActivityProviderEvidence]
    unavailable_surfaces: list[WalletIngestionSurface] = Field(default_factory=list)
    incomplete_surfaces: list[WalletIngestionSurface] = Field(default_factory=list)
    acquisition_streams: list[WalletActivityAcquisitionStreamRecord] = Field(
        default_factory=list
    )
    warnings: list[str] = Field(default_factory=list)
    message: str


class WalletEventActionIdentityRecord(BaseModel):
    status: Literal["provider_scoped", "unavailable"]
    version: str
    provider: str | None = None
    network: Literal["ton-mainnet", "ton-testnet", "ton-unknown"]
    account_canonical: str | None = None
    event_id_canonical: str | None = None
    logical_time_canonical: str | None = None
    action_index: int | None = Field(default=None, ge=0, le=2**31 - 1)
    action_type: str | None = None
    key: str | None = None
    is_provider_observation_identity: bool
    is_blockchain_proof_verified: Literal[False] = False
    is_authoritative_activity_identity: Literal[False] = False
    is_ownership_proof: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    deduplication_applied: Literal[False] = False
    used_by_pnl: Literal[False] = False


class WalletTransferRecord(BaseModel):
    tx_hash: str | None = None
    logical_time: str | None = None
    timestamp: str | None = None
    asset: str
    amount: str | None = None
    direction: Literal["in", "out", "unknown"]
    counterparty: str | None = None
    provider: str
    source_status: WalletSourceStatus
    event_action_identity: WalletEventActionIdentityRecord
    raw: dict[str, Any] | None = None


class WalletTransactionIdentityRecord(BaseModel):
    status: Literal["network_scoped", "unavailable"]
    version: str
    network: Literal["ton-mainnet", "ton-testnet", "ton-unknown"]
    account_canonical: str | None = None
    logical_time_canonical: str | None = None
    hash_canonical: str | None = None
    key: str | None = None
    is_deduplication_identity: bool
    is_blockchain_proof_verified: Literal[False] = False
    is_ownership_proof: Literal[False] = False
    deduplication_applied: Literal[False] = False
    used_by_pnl: Literal[False] = False


class WalletTransactionRecord(BaseModel):
    tx_hash: str
    logical_time: str | None = None
    timestamp: str | None = None
    fee_ton: str | None = None
    success: Literal["success", "failed", "unknown"]
    provider: str
    source_status: WalletSourceStatus
    transaction_identity: WalletTransactionIdentityRecord
    raw: dict[str, Any] | None = None


CanonicalTraceTransactionHash = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-f]{64}$",
        min_length=64,
        max_length=64,
    ),
]
CanonicalTraceLogicalTime = Annotated[
    str,
    Field(pattern=r"^[1-9][0-9]{0,19}$", max_length=20),
]
StrictTraceCount = Annotated[int, Field(strict=True, ge=0)]


class WalletTransactionTraceAnchorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_hash: CanonicalTraceTransactionHash
    logical_time: CanonicalTraceLogicalTime
    account_canonical: str = Field(
        pattern=r"^(?:0|[1-9][0-9]*|-[1-9][0-9]*):[0-9a-f]{64}$",
        min_length=66,
        max_length=76,
    )
    matches_stored_transaction: Literal[True]

    @field_validator("logical_time")
    @classmethod
    def _trace_logical_time_must_fit_uint64(cls, value: str) -> str:
        if int(value, 10) > 2**64 - 1:
            raise ValueError("trace logical_time exceeds unsigned 64-bit range")
        return value


class WalletTransactionTraceSummaryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    root_transaction_hash: CanonicalTraceTransactionHash
    transaction_count: Annotated[int, Field(strict=True, ge=1, le=256)]
    max_depth: Annotated[int, Field(strict=True, ge=0, le=32)]
    out_message_count: Annotated[int, Field(strict=True, ge=0, le=2048)]
    pending_internal_message_count: Annotated[
        int,
        Field(strict=True, ge=0, le=2048),
    ]
    successful_transaction_count: StrictTraceCount
    failed_transaction_count: StrictTraceCount
    aborted_transaction_count: StrictTraceCount
    unique_account_count: Annotated[int, Field(strict=True, ge=1, le=256)]

    @model_validator(mode="after")
    def _trace_counts_must_be_coherent(self):
        if (
            self.successful_transaction_count
            + self.failed_transaction_count
            != self.transaction_count
        ):
            raise ValueError(
                "trace success and failure counts must cover every transaction"
            )
        if self.aborted_transaction_count > self.transaction_count:
            raise ValueError("trace aborted count exceeds transaction count")
        if self.unique_account_count > self.transaction_count:
            raise ValueError("trace account count exceeds transaction count")
        if self.pending_internal_message_count > self.out_message_count:
            raise ValueError(
                "trace pending internal messages exceed outgoing messages"
            )
        if self.transaction_count > 1 and self.max_depth == 0:
            raise ValueError("multi-transaction trace must have positive depth")
        return self


class WalletTransactionTraceEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["tonapi_transaction_trace_preview_v1"]
    run_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    provider: Literal["tonapi"]
    source_status: Literal["live"]
    trace_state: Literal["finalized", "pending"]
    anchor: WalletTransactionTraceAnchorRecord
    summary: WalletTransactionTraceSummaryRecord
    is_provider_indexed_low_level_trace: Literal[True]
    is_blockchain_proof_verified: Literal[False] = False
    is_authoritative_activity_identity: Literal[False] = False
    semantic_reconstruction_applied: Literal[False] = False
    activity_merge_applied: Literal[False] = False
    deduplication_applied: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    is_ownership_proof: Literal[False] = False
    message: str = Field(min_length=1, max_length=500)

    @field_validator("run_id")
    @classmethod
    def _trace_run_id_must_fit_sqlite(cls, value: str) -> str:
        if int(value, 10) > 2**63 - 1:
            raise ValueError("trace run_id exceeds signed 64-bit range")
        return value

    @model_validator(mode="after")
    def _trace_state_must_match_pending_messages(self):
        pending = self.summary.pending_internal_message_count
        if self.trace_state == "finalized" and pending != 0:
            raise ValueError("finalized trace cannot contain pending messages")
        if self.trace_state == "pending" and pending == 0:
            raise ValueError("pending trace requires an internal outgoing message")
        return self


class WalletPersistedTraceSummaryRecord(BaseModel):
    """Counts recomputed from one immutable persisted trace graph."""

    model_config = ConfigDict(extra="forbid")

    root_transaction_hash: CanonicalTraceTransactionHash
    transaction_count: Annotated[int, Field(strict=True, ge=1, le=256)]
    max_depth: Annotated[int, Field(strict=True, ge=0, le=32)]
    message_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    root_inbound_message_count: Annotated[
        int,
        Field(strict=True, ge=0, le=1),
    ]
    child_internal_message_count: Annotated[
        int,
        Field(strict=True, ge=0, le=255),
    ]
    remaining_out_message_count: Annotated[
        int,
        Field(strict=True, ge=0, le=2048),
    ]
    internal_message_count: Annotated[
        int,
        Field(strict=True, ge=0, le=2304),
    ]
    external_in_message_count: Annotated[
        int,
        Field(strict=True, ge=0, le=2304),
    ]
    external_out_message_count: Annotated[
        int,
        Field(strict=True, ge=0, le=2304),
    ]
    successful_transaction_count: StrictTraceCount
    failed_transaction_count: StrictTraceCount
    aborted_transaction_count: StrictTraceCount
    unique_account_count: Annotated[int, Field(strict=True, ge=1, le=256)]

    @model_validator(mode="after")
    def _persisted_trace_counts_must_be_coherent(self):
        if self.child_internal_message_count != self.transaction_count - 1:
            raise ValueError(
                "every non-root transaction requires one child inbound message"
            )
        if (
            self.root_inbound_message_count
            + self.child_internal_message_count
            + self.remaining_out_message_count
            != self.message_count
        ):
            raise ValueError("persisted trace message roles do not cover all messages")
        if (
            self.internal_message_count
            + self.external_in_message_count
            + self.external_out_message_count
            != self.message_count
        ):
            raise ValueError("persisted trace message types do not cover all messages")
        if (
            self.successful_transaction_count
            + self.failed_transaction_count
            != self.transaction_count
        ):
            raise ValueError(
                "persisted trace success and failure counts must cover every transaction"
            )
        if self.aborted_transaction_count > self.transaction_count:
            raise ValueError("persisted trace aborted count exceeds transaction count")
        if self.unique_account_count > self.transaction_count:
            raise ValueError("persisted trace account count exceeds transaction count")
        if self.transaction_count > 1 and self.max_depth == 0:
            raise ValueError("multi-transaction persisted trace requires positive depth")
        return self


class WalletPersistedTraceEvidenceResponse(BaseModel):
    """Locally revalidated summary of one stored provider trace graph."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["tonapi_low_level_trace_evidence_v1"]
    capture_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    run_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    provider: Literal["tonapi"]
    source_status: Literal["live"]
    network: str = Field(pattern=r"^ton-(?:mainnet|testnet)$", max_length=16)
    trace_state: Literal["finalized"]
    captured_at: datetime
    anchor: WalletTransactionTraceAnchorRecord
    summary: WalletPersistedTraceSummaryRecord
    evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    is_provider_indexed_low_level_trace: Literal[True]
    provider_structure_validated: Literal[True]
    persisted_graph_revalidated: Literal[True]
    is_immutable_record: Literal[True]
    raw_boc_persisted: Literal[False] = False
    message_body_persisted: Literal[False] = False
    is_blockchain_proof_verified: Literal[False] = False
    is_authoritative_activity_identity: Literal[False] = False
    semantic_reconstruction_applied: Literal[False] = False
    activity_merge_applied: Literal[False] = False
    deduplication_applied: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    is_ownership_proof: Literal[False] = False
    message: str = Field(min_length=1, max_length=500)

    @field_validator("capture_id", "run_id")
    @classmethod
    def _persisted_trace_ids_must_fit_sqlite(cls, value: str) -> str:
        if int(value, 10) > 2**63 - 1:
            raise ValueError("persisted trace id exceeds signed 64-bit range")
        return value


class WalletTraceBocVerifierRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Literal["pytoniq-core"]
    version: Literal["0.1.46"]


class WalletTraceBocVerificationSummaryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_count: Annotated[int, Field(strict=True, ge=1, le=256)]
    message_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    total_boc_bytes: Annotated[
        int,
        Field(strict=True, ge=1, le=8 * 1024 * 1024),
    ]
    normalized_external_in_hash_count: Annotated[
        int,
        Field(strict=True, ge=0, le=2304),
    ]
    direct_cell_hash_message_count: Annotated[
        int,
        Field(strict=True, ge=0, le=2304),
    ]
    body_hash_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    opcode_count: Annotated[int, Field(strict=True, ge=0, le=2304)]

    @model_validator(mode="after")
    def _locally_verified_message_counts_must_be_coherent(self):
        if (
            self.normalized_external_in_hash_count
            + self.direct_cell_hash_message_count
            != self.message_count
        ):
            raise ValueError("verified message hash kinds must cover all messages")
        if self.body_hash_count != self.message_count:
            raise ValueError("every verified message requires a body hash")
        if self.opcode_count > self.body_hash_count:
            raise ValueError("opcode count exceeds verified message body count")
        return self


class WalletTraceBocTransactionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    preorder_index: Annotated[int, Field(strict=True, ge=0, le=255)]
    transaction_hash: CanonicalTraceTransactionHash
    transaction_boc_bytes: Annotated[
        int,
        Field(strict=True, ge=1, le=1024 * 1024),
    ]
    transaction_cell_hash: CanonicalTraceTransactionHash
    raw_out_message_count: Annotated[int, Field(strict=True, ge=0, le=2048)]
    message_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    body_hash_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    opcode_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    message_evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _transaction_boc_counts_must_be_coherent(self):
        if self.transaction_cell_hash != self.transaction_hash:
            raise ValueError("transaction BOC cell hash must match transaction hash")
        if self.body_hash_count != self.message_count:
            raise ValueError("transaction body hashes must cover owned messages")
        if self.opcode_count > self.body_hash_count:
            raise ValueError("transaction opcode count exceeds body count")
        return self


class WalletTraceBocVerificationResponse(BaseModel):
    """Provider-safe summary of locally reparsed transaction BOC evidence."""

    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["ton_boc_trace_verification_v1"]
    verification_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    capture_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    run_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    provider: Literal["tonapi"]
    source_status: Literal["live"]
    network: str = Field(pattern=r"^ton-(?:mainnet|testnet)$", max_length=16)
    verified_at: datetime
    verifier: WalletTraceBocVerifierRecord
    anchor: WalletTransactionTraceAnchorRecord
    capture_evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    summary: WalletTraceBocVerificationSummaryRecord
    transactions: list[WalletTraceBocTransactionRecord]
    transaction_bocs_deserialized_locally: Literal[True]
    transaction_cell_hashes_verified: Literal[True]
    transaction_headers_verified: Literal[True]
    message_hashes_verified: Literal[True]
    message_headers_verified: Literal[True]
    message_body_hashes_derived: Literal[True]
    raw_boc_persisted: Literal[True]
    raw_boc_returned: Literal[False] = False
    message_bodies_returned: Literal[False] = False
    is_blockchain_inclusion_proof_verified: Literal[False] = False
    is_authoritative_activity_identity: Literal[False] = False
    semantic_reconstruction_applied: Literal[False] = False
    activity_merge_applied: Literal[False] = False
    deduplication_applied: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    is_ownership_proof: Literal[False] = False
    message: str = Field(min_length=1, max_length=600)

    @field_validator("verification_id", "capture_id", "run_id")
    @classmethod
    def _boc_verification_ids_must_fit_sqlite(cls, value: str) -> str:
        if int(value, 10) > 2**63 - 1:
            raise ValueError("BOC verification id exceeds signed 64-bit range")
        return value

    @model_validator(mode="after")
    def _boc_transaction_rows_must_match_summary(self):
        if len(self.transactions) != self.summary.transaction_count:
            raise ValueError("verified transaction rows must match summary")
        if [row.preorder_index for row in self.transactions] != list(
            range(len(self.transactions))
        ):
            raise ValueError("verified transaction rows require canonical preorder")
        if sum(row.transaction_boc_bytes for row in self.transactions) != (
            self.summary.total_boc_bytes
        ):
            raise ValueError("verified transaction BOC bytes must match summary")
        if sum(row.message_count for row in self.transactions) != (
            self.summary.message_count
        ):
            raise ValueError("verified transaction message counts must match summary")
        return self


class WalletTraceBocMessageEvidenceRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transaction_preorder_index: Annotated[int, Field(strict=True, ge=0, le=255)]
    transaction_hash: CanonicalTraceTransactionHash
    role: Literal["root_inbound", "child_inbound", "remaining_outbound"]
    ordinal: Annotated[int, Field(strict=True, ge=0, le=2047)]
    message_hash: CanonicalTraceTransactionHash
    raw_message_cell_hash: CanonicalTraceTransactionHash
    hash_kind: Literal["cell_hash", "normalized_external_in"]
    message_type: Literal["int_msg", "ext_in_msg", "ext_out_msg"]
    source_account_canonical: str | None = Field(default=None, max_length=76)
    destination_account_canonical: str | None = Field(default=None, max_length=76)
    created_logical_time: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,19})$")
    unix_time: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
    value_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,19})$")
    forward_fee_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,19})$")
    ihr_fee_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,19})$")
    import_fee_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,19})$")
    ihr_disabled: bool
    bounce: bool
    bounced: bool
    extra_currency_count: Annotated[int, Field(strict=True, ge=0)]
    body_hash: CanonicalTraceTransactionHash
    body_bit_length: Annotated[int, Field(strict=True, ge=0, le=1023)]
    body_ref_count: Annotated[int, Field(strict=True, ge=0, le=4)]
    opcode_hex: str | None = Field(default=None, pattern=r"^0x[0-9a-f]{8}$")


class WalletTraceBocMessageEvidenceResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["ton_boc_message_evidence_v1"]
    verification_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    capture_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    run_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    provider: Literal["tonapi"]
    source_status: Literal["live"]
    network: str = Field(pattern=r"^ton-(?:mainnet|testnet)$", max_length=16)
    anchor: WalletTransactionTraceAnchorRecord
    verification_evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    message_evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    message_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    messages: list[WalletTraceBocMessageEvidenceRecord]
    derived_from_locally_deserialized_bocs: Literal[True]
    message_headers_verified: Literal[True]
    message_body_hashes_derived: Literal[True]
    message_bodies_returned: Literal[False] = False
    semantic_reconstruction_applied: Literal[False] = False
    is_authoritative_activity_identity: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    is_ownership_proof: Literal[False] = False
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _message_rows_must_match_count(self):
        if len(self.messages) != self.message_count:
            raise ValueError("message evidence rows must match message_count")
        return self


class WalletNativeTonFlowObservationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    transaction_preorder_index: Annotated[int, Field(strict=True, ge=0, le=255)]
    transaction_hash: CanonicalTraceTransactionHash
    message_role: Literal["root_inbound", "child_inbound", "remaining_outbound"]
    message_ordinal: Annotated[int, Field(strict=True, ge=0, le=2047)]
    message_hash: CanonicalTraceTransactionHash
    direction: Literal["incoming", "outgoing", "self"]
    wallet_account_canonical: str = Field(min_length=66, max_length=76)
    counterparty_account_observed: str = Field(min_length=66, max_length=76)
    amount_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    created_logical_time: str = Field(pattern=r"^(?:0|[1-9][0-9]{0,19})$")
    unix_time: Annotated[int, Field(strict=True, ge=0, le=2**63 - 1)]
    body_hash: CanonicalTraceTransactionHash
    opcode_hex: str | None = Field(default=None, pattern=r"^0x[0-9a-f]{8}$")
    bounce: bool
    bounced: bool


class WalletNativeTonFlowObservationsResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["ton_native_flow_observations_v1"]
    identity_version: Literal["ton_native_message_flow_obs_v1"]
    verification_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    capture_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    run_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    provider: Literal["tonapi"]
    source_status: Literal["live"]
    network: str = Field(pattern=r"^ton-(?:mainnet|testnet)$", max_length=16)
    wallet_account_canonical: str = Field(min_length=66, max_length=76)
    anchor: WalletTransactionTraceAnchorRecord
    message_evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    flow_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    incoming_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    outgoing_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    self_nanoton: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    flows: list[WalletNativeTonFlowObservationRecord]
    derived_from_verified_message_headers: Literal[True]
    native_ton_only: Literal[True]
    counterparty_is_header_observation: Literal[True]
    is_authoritative_transfer_ledger: Literal[False] = False
    semantic_payload_decoding_applied: Literal[False] = False
    activity_merge_applied: Literal[False] = False
    deduplication_applied: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    is_ownership_proof: Literal[False] = False
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _native_flow_totals_must_match_rows(self):
        if len(self.flows) != self.flow_count:
            raise ValueError("native flow rows must match flow_count")
        totals = {"incoming": 0, "outgoing": 0, "self": 0}
        for flow in self.flows:
            if flow.wallet_account_canonical != self.wallet_account_canonical:
                raise ValueError("native flow wallet account changed")
            totals[flow.direction] += int(flow.amount_nanoton, 10)
        if (
            str(totals["incoming"]) != self.incoming_nanoton
            or str(totals["outgoing"]) != self.outgoing_nanoton
            or str(totals["self"]) != self.self_nanoton
        ):
            raise ValueError("native flow totals do not match rows")
        return self


class WalletNativeTonAssetIdentityRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    identity_version: Literal["ton_native_asset_v1"]
    identity_key: str = Field(pattern=r"^ton_native_asset_v1\|ton-(?:mainnet|testnet)$")
    network: str = Field(pattern=r"^ton-(?:mainnet|testnet)$")
    kind: Literal["native"]
    symbol: Literal["TON"]
    name: Literal["Toncoin"]
    decimals: Literal[9]
    base_unit: Literal["nanoton"]
    master_address: None = None


class WalletNativeTonAssetBindingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow_observation_identity: str = Field(pattern=r"^[0-9a-f]{64}$")
    transaction_hash: CanonicalTraceTransactionHash
    message_hash: CanonicalTraceTransactionHash
    direction: Literal["incoming", "outgoing", "self"]
    amount_base_units: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    asset_identity_key: str = Field(
        pattern=r"^ton_native_asset_v1\|ton-(?:mainnet|testnet)$"
    )


class WalletNativeTonAssetBindingResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contract_version: Literal["ton_native_asset_binding_v1"]
    verification_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    capture_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    run_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    network: str = Field(pattern=r"^ton-(?:mainnet|testnet)$")
    wallet_account_canonical: str = Field(min_length=66, max_length=76)
    anchor: WalletTransactionTraceAnchorRecord
    flow_message_evidence_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    asset: WalletNativeTonAssetIdentityRecord
    binding_count: Annotated[int, Field(strict=True, ge=0, le=2304)]
    bindings: list[WalletNativeTonAssetBindingRecord]
    asset_binding_digest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    canonical_native_asset_identity: Literal[True]
    jetton_asset_identity_applied: Literal[False] = False
    counterparty_identity_applied: Literal[False] = False
    activity_merge_applied: Literal[False] = False
    deduplication_applied: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _native_asset_bindings_must_be_coherent(self):
        if len(self.bindings) != self.binding_count:
            raise ValueError("native asset bindings must match binding_count")
        if self.asset.network != self.network:
            raise ValueError("native asset network changed")
        if any(
            binding.asset_identity_key != self.asset.identity_key
            for binding in self.bindings
        ):
            raise ValueError("native asset binding identity changed")
        return self


class WalletSwapRecord(BaseModel):
    tx_hash: str | None = None
    timestamp: str | None = None
    dex: str | None = None
    token_in: str | None = None
    token_in_address: str | None = None
    amount_in: str | None = None
    token_out: str | None = None
    token_out_address: str | None = None
    amount_out: str | None = None
    estimated_usd: str | None = None
    provider: str
    source_status: WalletSourceStatus
    event_action_identity: WalletEventActionIdentityRecord
    raw: dict[str, Any] | None = None


class WalletBalanceSnapshotRecord(BaseModel):
    asset: str
    balance: str | None = None
    balance_usd: str | None = None
    provider: str
    source_status: WalletSourceStatus
    snapshot_at: str | None = None
    raw: dict[str, Any] | None = None


class WalletIngestionWarningRecord(BaseModel):
    severity: Literal["info", "warning", "error", "critical"]
    provider: str | None = None
    message: str
    evidence_key: str | None = None


class WalletIdentityRecord(BaseModel):
    status: Literal["network_scoped", "unscoped", "unavailable"]
    version: str
    network: Literal["ton-mainnet", "ton-testnet", "ton-unknown"]
    canonical_address: str | None = None
    workchain_id: int | None = None
    account_id_hex: str | None = None
    submitted_format: Literal["user_friendly", "raw", "unrecognized"]
    bounceable: bool | None = None
    testnet_only: bool | None = None
    is_account_existence_proof: Literal[False] = False
    is_ownership_proof: Literal[False] = False


class WalletIngestionRunCatalogItem(BaseModel):
    run_id: str = Field(pattern=r"^[1-9][0-9]*$", max_length=19)
    wallet_hint: str = Field(min_length=1, max_length=11)
    time_window: Literal["24h", "3d", "7d", "custom"]
    created_at: str
    status: WalletIngestionStatus
    data_mode: Literal["mock", "real"]

    @field_validator("run_id")
    @classmethod
    def _catalog_run_id_must_fit_sqlite(cls, value: str) -> str:
        if int(value, 10) > 2**63 - 1:
            raise ValueError("catalog run_id exceeds signed 64-bit range")
        return value

    @field_validator("wallet_hint")
    @classmethod
    def _catalog_wallet_hint_must_stay_masked(cls, value: str) -> str:
        if value == "stored…run" or (len(value) == 11 and value[6] == "…"):
            return value
        raise ValueError("catalog wallet_hint must use the bounded masked shape")


class WalletIngestionRunCatalogResponse(BaseModel):
    runs: list[WalletIngestionRunCatalogItem]
    limit: Annotated[int, Field(strict=True, ge=1, le=50)]
    truncated: Annotated[bool, Field(strict=True)]

    @model_validator(mode="after")
    def _catalog_page_must_be_canonical(self):
        if len(self.runs) > self.limit:
            raise ValueError("catalog page cannot exceed its requested limit")
        run_ids = [int(run.run_id, 10) for run in self.runs]
        if any(left <= right for left, right in zip(run_ids, run_ids[1:])):
            raise ValueError("catalog runs must use unique descending run ids")
        if self.truncated and len(self.runs) != self.limit:
            raise ValueError("a truncated catalog must fill its requested limit")
        return self


class WalletIngestionRunResponse(BaseModel):
    run_id: PositiveStrictRunId
    wallet_address: str
    time_window: Literal["24h", "3d", "7d", "custom"]
    custom_start: str | None = None
    custom_end: str | None = None
    created_at: str
    status: WalletIngestionStatus
    data_mode: Literal["mock", "real"]
    wallet_identity: WalletIdentityRecord
    requested_surfaces: list[WalletIngestionSurface]
    provider_evidence: list[WalletActivityProviderEvidence] = Field(
        default_factory=list
    )
    unavailable_surfaces: list[WalletIngestionSurface] = Field(default_factory=list)
    incomplete_surfaces: list[WalletIngestionSurface] = Field(default_factory=list)
    acquisition_streams: list[WalletActivityAcquisitionStreamRecord] = Field(
        default_factory=list
    )
    transfers: list[WalletTransferRecord] = Field(default_factory=list)
    transactions: list[WalletTransactionRecord] = Field(default_factory=list)
    swaps: list[WalletSwapRecord] = Field(default_factory=list)
    balances: list[WalletBalanceSnapshotRecord] = Field(default_factory=list)
    warnings: list[WalletIngestionWarningRecord] = Field(default_factory=list)
    message: str
    activity_summary: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _stored_scope_must_match_window(self):
        if self.time_window == "custom":
            if not self.custom_start or not self.custom_end:
                raise ValueError(
                    "custom_start and custom_end are required for a stored custom run"
                )
        elif self.custom_start is not None or self.custom_end is not None:
            raise ValueError(
                "stored rolling runs cannot contain custom_start or custom_end"
            )
        return self


class WalletClusterCompareRequest(BaseModel):
    run_ids: list[int] = Field(
        ...,
        min_length=2,
        max_length=25,
        description="Persisted wallet ingestion run ids to compare pairwise.",
    )


class WalletSignalsRecord(BaseModel):
    run_id: int
    wallet_address: str
    data_mode: Literal["mock", "real"]
    ton_balance: str
    portfolio_value_usd: str | None = None
    distinct_tokens_touched: list[str] = Field(default_factory=list)
    buy_swap_count: int
    sell_swap_count: int
    avg_ton_per_buy_swap: str | None = None
    first_buy_at: str | None = None
    warnings: list[str] = Field(default_factory=list)


class WalletClusterPairRecord(BaseModel):
    wallet_a_run_id: int
    wallet_b_run_id: int
    wallet_a_address: str
    wallet_b_address: str
    score: float
    band: str
    shared_tokens: list[str] = Field(default_factory=list)
    note: str


class WalletClusterCompareResponse(BaseModel):
    wallets: list[WalletSignalsRecord]
    comparison_window_seconds: float
    pairs: list[WalletClusterPairRecord]
    is_cluster_proof: bool = False
    note: str


class WalletHistoryReadinessRequest(BaseModel):
    target_run_id: PositiveStrictRunId = Field(
        ...,
        description="Persisted run used as the explicit diagnostic target.",
    )
    run_ids: list[PositiveStrictRunId] = Field(
        ...,
        min_length=2,
        max_length=50,
        description=(
            "Distinct persisted runs for the same wallet and data mode to "
            "inspect for history-readiness evidence."
        ),
    )

    @model_validator(mode="after")
    def _target_must_be_in_scope(self):
        if self.target_run_id not in self.run_ids:
            raise ValueError("target_run_id must be included in run_ids.")
        return self


class WalletHistoryRunScopeRecord(BaseModel):
    run_id: int
    is_target: bool
    wallet_address: str
    wallet_identity: WalletIdentityRecord
    time_window: str
    status: WalletIngestionStatus
    created_at: str | None = None
    requested_start: str | None = None
    requested_end: str | None = None
    requested_bounds_verified: Literal[False] = False
    observed_activity_start: str | None = None
    observed_activity_end: str | None = None
    transfer_count: int = Field(ge=0)
    transaction_count: int = Field(ge=0)
    swap_count: int = Field(ge=0)
    timestamped_activity_count: int = Field(ge=0)
    untimestamped_activity_count: int = Field(ge=0)
    outside_requested_bounds_count: int = Field(ge=0)
    requested_surfaces: list[WalletIngestionSurface] = Field(default_factory=list)
    unavailable_surfaces: list[WalletIngestionSurface] = Field(default_factory=list)


class WalletHistoryIdentityGroupRecord(BaseModel):
    identity: str
    identity_type: Literal[
        "account_transaction",
        "transaction_hash",
        "provider_event_action_observation",
        "event_action",
        "event_reference",
        "swap_fingerprint",
    ]
    identity_strength: Literal["exact", "provider_scoped", "weak"]
    run_ids: list[int]
    observation_count: int = Field(ge=2)
    distinct_payload_count: int = Field(ge=1)
    has_conflict: bool


class WalletHistoryCoverageRecord(BaseModel):
    activity_observations: int = Field(ge=0)
    timestamped_activity_observations: int = Field(ge=0)
    transaction_observations: int = Field(ge=0)
    transaction_observations_with_hash: int = Field(ge=0)
    transaction_observations_with_exact_identity: int = Field(ge=0)
    transaction_observations_with_weak_identity: int = Field(ge=0)
    transaction_observations_with_unavailable_identity: int = Field(ge=0)
    transaction_observations_with_invalid_identity_contract: int = Field(ge=0)
    transaction_identity_coverage_state: Literal[
        "not_observed", "complete", "incomplete"
    ]
    overlapping_transaction_identity_groups: int = Field(ge=0)
    conflicting_transaction_identity_groups: int = Field(ge=0)
    event_action_observations: int = Field(ge=0)
    event_action_observations_with_provider_scoped_identity: int = Field(ge=0)
    event_action_observations_with_unavailable_identity: int = Field(ge=0)
    event_action_observations_with_invalid_identity_contract: int = Field(ge=0)
    event_action_identity_coverage_state: Literal[
        "not_observed", "complete", "incomplete"
    ]
    overlapping_provider_scoped_event_action_identity_groups: int = Field(ge=0)
    conflicting_provider_scoped_event_action_identity_groups: int = Field(ge=0)
    swap_observations: int = Field(ge=0)
    swap_observations_with_exact_identity: int = Field(ge=0)
    swap_observations_with_provider_scoped_identity: int = Field(ge=0)
    swap_observations_with_weak_identity: int = Field(ge=0)
    overlapping_exact_swap_identity_groups: int = Field(ge=0)
    overlapping_provider_scoped_swap_identity_groups: int = Field(ge=0)
    overlapping_weak_swap_identity_groups: int = Field(ge=0)
    conflicting_swap_identity_groups: int = Field(ge=0)
    non_ton_swap_legs: int = Field(ge=0)
    addressed_non_ton_swap_legs: int = Field(ge=0)
    asset_address_coverage_state: Literal["not_observed", "complete", "incomplete"]
    fee_link_candidate_swaps: int = Field(ge=0)
    same_run_fee_hash_match_candidates: int = Field(ge=0)
    fee_hash_match_coverage_state: Literal[
        "not_observed", "complete", "incomplete"
    ]
    fee_linkage_contract_verified: Literal[False] = False


class WalletHistoryIntervalRecord(BaseModel):
    start: str
    end: str
    duration_microseconds: str = Field(pattern=r"^[1-9][0-9]*$")


class WalletHistoryAcceptedIntervalRecord(WalletHistoryIntervalRecord):
    run_id: int = Field(ge=1)


class WalletHistoryOverlapIntervalRecord(WalletHistoryIntervalRecord):
    run_ids: list[int]
    coverage_depth: int = Field(ge=2)


class WalletHistoryGapIntervalRecord(WalletHistoryIntervalRecord):
    left_run_ids: list[int]
    right_run_ids: list[int]


class WalletHistoryIntervalRunEvidenceRecord(BaseModel):
    run_id: int = Field(ge=1)
    source_state: str | None = None
    candidate_states: list[str] = Field(default_factory=list)
    classification: Literal["included", "excluded", "not_requested"]
    reason: str | None = None
    source_reason_codes: list[str] = Field(default_factory=list)
    recorded_interval_start: str | None = None
    recorded_interval_end: str | None = None
    interval_start: str | None = None
    interval_end: str | None = None
    duration_microseconds: str | None = Field(
        default=None,
        pattern=r"^[1-9][0-9]*$",
    )
    included_in_union: bool


class WalletHistoryIntervalCoverageLayerRecord(BaseModel):
    stream_key: Literal["transactions", "account_events"]
    coverage_kind: Literal[
        "low_level_transaction_stream",
        "provider_display_event_stream",
    ]
    eligible_state: Literal["complete", "provider_stream_complete"]
    provider_semantics: Literal[
        "bounded_low_level_transaction_query",
        "display_only_actions",
    ]
    state: Literal[
        "no_validated_intervals",
        "contiguous_selected_span",
        "gapped_selected_span",
    ]
    selected_run_count: int = Field(ge=2, le=50)
    requested_run_count: int = Field(ge=0, le=50)
    included_run_count: int = Field(ge=0, le=50)
    included_run_ids: list[int]
    excluded_run_ids: list[int]
    not_requested_run_ids: list[int]
    selected_run_coverage_state: Literal["none", "partial", "complete"]
    run_evidence: list[WalletHistoryIntervalRunEvidenceRecord]
    accepted_intervals: list[WalletHistoryAcceptedIntervalRecord]
    selected_span: WalletHistoryIntervalRecord | None = None
    union_intervals: list[WalletHistoryIntervalRecord]
    overlap_intervals: list[WalletHistoryOverlapIntervalRecord]
    gap_intervals: list[WalletHistoryGapIntervalRecord]
    span_duration_microseconds: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    covered_duration_microseconds: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    gap_duration_microseconds: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    overlapped_duration_microseconds: str = Field(pattern=r"^(?:0|[1-9][0-9]*)$")
    max_coverage_depth: int = Field(ge=0, le=50)
    is_contiguous_within_selected_span: bool
    outside_selected_span_coverage: Literal["unknown"]
    establishes_full_history: Literal[False] = False
    is_authoritative_activity_coverage: Literal[False] = False


class WalletHistoryBoundedIntervalCoverageRecord(BaseModel):
    contract_version: Literal["wallet_multi_run_interval_coverage_v1"]
    selected_run_ids: list[int]
    interval_semantics: Literal["[start,end)"]
    coverage_scope: Literal["selected_validated_run_intervals_only"]
    gap_scope: Literal["inside_validated_selected_span_only"]
    cross_stream_union_applied: Literal[False] = False
    low_level_transactions: WalletHistoryIntervalCoverageLayerRecord
    provider_display_events: WalletHistoryIntervalCoverageLayerRecord
    full_pre_run_history_established: Literal[False] = False
    complete_wallet_history_established: Literal[False] = False
    is_global_history_coverage: Literal[False] = False
    is_authoritative_activity_coverage: Literal[False] = False
    activity_rows_merged: Literal[False] = False
    deduplication_applied: Literal[False] = False
    is_cost_basis: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    note: str


class WalletHistoryBlockerRecord(BaseModel):
    code: str
    reason: str
    run_ids: list[int] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class WalletHistoryReadinessResponse(BaseModel):
    analysis_version: Literal["wallet_history_readiness_v0.22.7"]
    target_run_id: int
    run_ids: list[int]
    wallet_address: str
    wallet_identity: WalletIdentityRecord
    data_mode: Literal["mock", "real"]
    requested_bounds_verified: Literal[False] = False
    observed_activity_start: str | None = None
    observed_activity_end: str | None = None
    runs: list[WalletHistoryRunScopeRecord]
    transaction_identity_groups: list[WalletHistoryIdentityGroupRecord] = Field(
        default_factory=list
    )
    swap_identity_groups: list[WalletHistoryIdentityGroupRecord] = Field(
        default_factory=list
    )
    event_action_identity_groups: list[WalletHistoryIdentityGroupRecord] = Field(
        default_factory=list
    )
    transaction_identity_groups_total: int = Field(ge=0)
    swap_identity_groups_total: int = Field(ge=0)
    event_action_identity_groups_total: int = Field(ge=0)
    evidence_groups_truncated: bool
    coverage: WalletHistoryCoverageRecord
    bounded_interval_coverage: WalletHistoryBoundedIntervalCoverageRecord
    blockers: list[WalletHistoryBlockerRecord] = Field(default_factory=list)
    history_complete: Literal[False] = False
    deduplication_applied: Literal[False] = False
    is_cost_basis: Literal[False] = False
    eligible_for_cost_basis: Literal[False] = False
    used_by_pnl: Literal[False] = False
    note: str


class WalletEvidenceSignalRecord(BaseModel):
    code: str
    title: str
    confidence: Literal["low", "medium", "high"]
    observation: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    note: str


class WalletEvidenceInsufficientRecord(BaseModel):
    code: str
    reason: str


class WalletRunSignalsResponse(BaseModel):
    run_id: int | None = None
    wallet_address: str
    is_risk_score: bool = False
    evaluated: list[str] = Field(default_factory=list)
    signals: list[WalletEvidenceSignalRecord] = Field(default_factory=list)
    insufficient_evidence: list[WalletEvidenceInsufficientRecord] = Field(
        default_factory=list
    )
    note: str


class HistoricalPricePointRecord(BaseModel):
    timestamp: str
    price_usd: str


class HistoricalPricesPreviewResponse(BaseModel):
    token: str
    currency: Literal["usd"]
    requested_start: str
    requested_end: str
    data_mode: Literal["mock", "real"]
    source_status: Literal["mock", "real", "unavailable"]
    points: list[HistoricalPricePointRecord] = Field(default_factory=list)
    point_count: int
    is_cost_basis_source: bool = False
    warnings: list[str] = Field(default_factory=list)
    message: str
    note: str


class WalletPnlRequirementRecord(BaseModel):
    code: str
    available: bool
    reason: str | None = None


class WalletPnlTokenFlowRecord(BaseModel):
    token: str
    buy_swap_count: int
    sell_swap_count: int
    token_bought_qty: str
    token_sold_qty: str
    ton_spent: str
    ton_received: str
    net_ton_flow: str
    fee_ton: str
    net_ton_flow_after_fees: str


class WalletPnlUsdFlowRecord(BaseModel):
    token: str
    usd_spent: str
    usd_received: str
    net_usd_flow: str
    matched_swap_count: int


class WalletPnlRealizedRecord(BaseModel):
    token: str
    status: Literal["computed", "unavailable"]
    reason: str | None = None
    sell_leg_count: int
    proceeds_usd: str | None = None
    cost_basis_usd: str | None = None
    realized_pnl_usd: str | None = None
    remaining_qty: str | None = None
    remaining_cost_usd: str | None = None


class WalletPnlUnrealizedRecord(BaseModel):
    token: str
    status: Literal["computed", "unavailable"]
    reason: str | None = None
    remaining_qty: str | None = None
    remaining_cost_usd: str | None = None
    spot_price_usd: str | None = None
    priced_by: str | None = None
    market_value_usd: str | None = None
    unrealized_pnl_usd: str | None = None


class WalletPnlHistoricalPricingRecord(BaseModel):
    source_status: Literal["mock", "real", "unavailable"]
    points_fetched: int
    swaps_matched: int
    swaps_unmatched: int
    tolerance_seconds: int
    note: str


class WalletRunPnlPreviewResponse(BaseModel):
    run_id: int | None = None
    wallet_address: str
    pnl_mode: Literal[
        "imported_pnl",
        "estimated_onchain_pnl",
        "real_pnl_locked",
        "insufficient_data",
        "real_pnl",
    ]
    confidence: Literal["high", "medium", "low", "unavailable"]
    is_real_pnl: bool = False
    real_pnl_locked: bool = True
    token_flows: list[WalletPnlTokenFlowRecord] = Field(default_factory=list)
    total_ton_spent: str
    total_ton_received: str
    net_ton_flow: str
    total_fees_ton: str
    net_ton_flow_after_fees: str
    swaps_used: int
    swaps_excluded: int
    usd_flows: list[WalletPnlUsdFlowRecord] = Field(default_factory=list)
    total_usd_spent: str | None = None
    total_usd_received: str | None = None
    net_usd_flow: str | None = None
    historical_pricing: WalletPnlHistoricalPricingRecord | None = None
    realized_pnl: list[WalletPnlRealizedRecord] = Field(default_factory=list)
    total_realized_pnl_usd: str | None = None
    unrealized: list[WalletPnlUnrealizedRecord] = Field(default_factory=list)
    total_unrealized_pnl_usd: str | None = None
    unrealized_note: str | None = None
    requirements: list[WalletPnlRequirementRecord] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    note: str


class BitqueryTokenTradesPreviewRequest(BaseModel):
    token_address: str = Field(
        ...,
        description="TON token address to preview DEX trades for.",
    )
    start: str = Field(..., description="ISO start datetime.")
    end: str = Field(..., description="ISO end datetime.")
    preview_limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of normalized Bitquery trades to preview.",
    )

    @field_validator("token_address", "start", "end")
    @classmethod
    def _required_non_empty_string(cls, value: str) -> str:
        cleaned = (value or "").strip()
        if not cleaned:
            raise ValueError("Required value is missing")
        return cleaned


class BitqueryTokenTradesPreviewResponse(BaseModel):
    provider: Literal["bitquery"]
    data_mode: Literal["mock", "real"]
    success: bool
    summary: dict[str, Any]
    trades_preview: list[dict[str, Any]]
    warnings: list[str]
    error: dict[str, Any] | None


class BitqueryTokenTradesAnalysisResponse(BaseModel):
    provider: Literal["bitquery"]
    data_mode: Literal["mock", "real"]
    success: bool
    summary: dict[str, Any]
    wallets: list[dict[str, Any]]
    trades_preview: list[dict[str, Any]]
    preview_limit: int
    has_more_wallets: bool
    warnings: list[str]
    error: dict[str, Any] | None
    analysis_note: str


class StonfiPoolsPreviewResponse(BaseModel):
    provider: Literal["stonfi"]
    data_mode: Literal["mock", "real"]
    source: Literal["mock", "real"]
    success: bool
    summary: dict[str, Any]
    pools_preview: list[dict[str, Any]]
    warnings: list[str]
    message: str
    error: dict[str, Any] | None


class TonapiAccountJettonsPreviewResponse(BaseModel):
    provider: Literal["tonapi"]
    data_mode: Literal["mock", "real"]
    source: Literal["mock", "real"]
    success: bool
    summary: dict[str, Any]
    account_address: str
    jettons_preview: list[dict[str, Any]]
    warnings: list[str]
    message: str
    error: dict[str, Any] | None


class TonapiWalletIntelligencePreviewResponse(BaseModel):
    provider: Literal["tonapi"]
    data_mode: Literal["mock", "real"]
    source: Literal["mock", "real"]
    success: bool
    account_address: str
    summary: dict[str, Any]
    intelligence: dict[str, Any]
    jettons_preview: list[dict[str, Any]]
    warnings: list[str]
    message: str
    error: dict[str, Any] | None


class ImportTradesPreviewRequest(BaseModel):
    format: Literal["csv", "json"]
    content: Any
    preview_limit: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of valid normalized trades to preview.",
    )


class ImportTradesPreviewResponse(BaseModel):
    summary: dict[str, Any]
    trades_preview: list[dict[str, Any]]
    preview_limit: int
    has_more: bool
    source: Literal["imported_csv", "imported_json"]


class ImportTradesAnalysisResponse(BaseModel):
    summary: dict[str, Any]
    wallets: list[dict[str, Any]]
    trades_preview: list[dict[str, Any]]
    preview_limit: int
    has_more_wallets: bool
    source: Literal["imported_csv", "imported_json"]
    analysis_note: str
    pnl_mode: Literal["imported_pnl"] = "imported_pnl"
    pnl_confidence: Literal["high", "medium", "low", "unavailable"] = "medium"
    pnl_note: str = ""


class DataQualityComponents(BaseModel):
    pool_data: Literal["mock", "real", "fallback_mock"]
    token_data: Literal["mock", "real", "fallback_mock"]
    wallet_buyers: Literal["mock"]
    wallet_balances: Literal["mock"]
    pnl: Literal["mock_calculated"]
    clustering: Literal["mock_calculated"]
    common_holdings: Literal["mock"]


class DataQuality(BaseModel):
    mode: Literal["mock", "real"]
    components: DataQualityComponents
    warnings: list[str]
    provider_notes: list[str]


class AnalyzeResponse(BaseModel):
    """Permissive response model.

    The real payload is built in ``services.analysis.analyze``. We allow extra
    fields so the Cyrillic ``Вывод`` keys and nested structures pass through.
    """

    model_config = {"extra": "allow"}

    pool_url: str
    time_window: str
    is_mock: bool
    summary: dict[str, Any]
    wallets: list[dict[str, Any]]
    groups: list[dict[str, Any]]
    common_holdings: list[dict[str, Any]]
    interesting_wallets: list[dict[str, Any]]
    data_quality: DataQuality
    providers: dict[str, Any]
