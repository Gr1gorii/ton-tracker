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


class WalletIngestionPreviewResponse(BaseModel):
    success: bool
    wallet_address: str
    time_window: str
    requested_surfaces: list[WalletIngestionSurface]
    provider_coverage: list[WalletActivityProviderEvidence]
    unavailable_surfaces: list[WalletIngestionSurface] = Field(default_factory=list)
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


class WalletTransactionRecord(BaseModel):
    tx_hash: str
    logical_time: str | None = None
    timestamp: str | None = None
    fee_ton: str | None = None
    success: Literal["success", "failed", "unknown"]
    provider: str
    source_status: WalletSourceStatus
    raw: dict[str, Any] | None = None


class WalletSwapRecord(BaseModel):
    tx_hash: str | None = None
    timestamp: str | None = None
    dex: str | None = None
    token_in: str | None = None
    amount_in: str | None = None
    token_out: str | None = None
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


class WalletIngestionRunResponse(BaseModel):
    run_id: int | None = None
    wallet_address: str
    time_window: str
    status: WalletIngestionStatus
    data_mode: Literal["mock", "real"]
    requested_surfaces: list[WalletIngestionSurface]
    provider_evidence: list[WalletActivityProviderEvidence] = Field(
        default_factory=list
    )
    unavailable_surfaces: list[WalletIngestionSurface] = Field(default_factory=list)
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
