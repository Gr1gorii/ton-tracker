"""Pydantic schemas for request/response validation.

The analysis response is large and partly dynamic (it includes a Cyrillic
``Вывод`` key), so the response is returned as a plain dict from the service
layer. Here we strictly validate the *request* and document the response shape
for OpenAPI via a permissive model.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator


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
