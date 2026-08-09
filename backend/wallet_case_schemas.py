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
    time_window: Literal["24h", "3d", "7d", "custom"]
    start_at: str
    end_at: str
    surfaces: list[WalletIngestionSurface]


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
    created_at: str
    updated_at: str
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
    truncated: bool
