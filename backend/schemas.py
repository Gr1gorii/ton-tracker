"""Pydantic schemas for request/response validation.

The analysis response is large and partly dynamic (it includes a Cyrillic
``Вывод`` key), so the response is returned as a plain dict from the service
layer. Here we strictly validate the *request* and document the response shape
for OpenAPI via a permissive model.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

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


class WalletIngestionRunResponse(BaseModel):
    run_id: int | None = None
    wallet_address: str
    time_window: str
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
    target_run_id: int = Field(
        ...,
        ge=1,
        description="Persisted run used as the explicit diagnostic target.",
    )
    run_ids: list[int] = Field(
        ...,
        min_length=2,
        max_length=50,
        description=(
            "Distinct persisted runs for the same wallet and data mode to "
            "inspect for history-readiness evidence."
        ),
    )

    @field_validator("run_ids")
    @classmethod
    def _run_ids_must_be_positive(cls, value: list[int]) -> list[int]:
        if any(run_id < 1 for run_id in value):
            raise ValueError("Every run_id must be a positive integer.")
        return value

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
        "event_action",
        "event_reference",
        "swap_fingerprint",
    ]
    identity_strength: Literal["exact", "weak"]
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
    swap_observations: int = Field(ge=0)
    swap_observations_with_exact_identity: int = Field(ge=0)
    overlapping_exact_swap_identity_groups: int = Field(ge=0)
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


class WalletHistoryBlockerRecord(BaseModel):
    code: str
    reason: str
    run_ids: list[int] = Field(default_factory=list)
    evidence: dict[str, Any] = Field(default_factory=dict)


class WalletHistoryReadinessResponse(BaseModel):
    analysis_version: Literal["wallet_history_readiness_v0.22.4"]
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
    transaction_identity_groups_total: int = Field(ge=0)
    swap_identity_groups_total: int = Field(ge=0)
    evidence_groups_truncated: bool
    coverage: WalletHistoryCoverageRecord
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
