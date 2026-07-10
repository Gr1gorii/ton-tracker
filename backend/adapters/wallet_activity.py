"""Wallet activity ingestion adapter contracts, mock provider, and live guards.

Deterministic mock data remains the default executable adapter. Provider-
specific scaffold adapters stay behind explicit configuration, while the
guarded TonAPI live path covers native TON balance snapshots, account jetton
balance snapshots, ordered transaction history, TON/jetton transfers, and DEX
swaps parsed from account events.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any, Literal, Protocol

from adapters.bitquery import BitqueryAdapter
from adapters.stonfi import StonfiAdapter
from adapters.ton_provider import TonProviderAdapter
from adapters.tonapi import TonapiAdapter
from config import ERROR_PROVIDER_PROTOCOL, Settings, get_settings

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
WalletDataMode = Literal["mock", "real"]

MOCK_WALLET_ACTIVITY_PROVIDER = "mock_wallet_activity"
MOCK_WALLET_ACTIVITY_FRESHNESS = "2026-06-01T12:00:00Z"
MOCK_SOURCE_STATUS: WalletSourceStatus = "mock"
MOCK_DATA_MODE: WalletDataMode = "mock"

WALLET_ACTIVITY_PROVIDER_MOCK = "mock"
WALLET_ACTIVITY_PROVIDER_TONAPI = "tonapi"
WALLET_ACTIVITY_PROVIDER_TON_PROVIDER = "ton_provider"
WALLET_ACTIVITY_PROVIDER_STONFI = "stonfi"
WALLET_ACTIVITY_PROVIDER_BITQUERY = "bitquery"
WALLET_ACTIVITY_PROVIDER_CHOICES = {
    WALLET_ACTIVITY_PROVIDER_MOCK,
    WALLET_ACTIVITY_PROVIDER_TONAPI,
    WALLET_ACTIVITY_PROVIDER_TON_PROVIDER,
    WALLET_ACTIVITY_PROVIDER_STONFI,
    WALLET_ACTIVITY_PROVIDER_BITQUERY,
}

MOCK_ACTIVITY_WARNINGS = [
    "Mock-normalized wallet activity ingestion uses deterministic fixtures only.",
    "The default mock adapter makes no provider calls; its transfers, swaps, balances, and transactions are not real on-chain rows.",
    "Stored mock runs feed run-scoped signals, PnL preview, cluster comparison, and exports; legacy buyers and the top-level report remain separate.",
]

BALANCE_QUANT = Decimal("0.000000000000000001")
USD_QUANT = Decimal("0.00000001")

TONAPI_TRANSACTION_ACQUISITION_CONTRACT = "tonapi_account_transactions_v1"
TONAPI_EVENT_ACQUISITION_CONTRACT = "tonapi_account_events_display_v1"

MOCK_JETTON_SURFACE_WARNING = (
    "Jettons are represented as jetton balance snapshots until a dedicated "
    "jetton-activity table is introduced."
)

MOCK_SURFACE_COUNTS: dict[WalletIngestionSurface, int] = {
    "transfers": 3,
    "transactions": 3,
    "swaps": 1,
    "balances": 1,
    "jettons": 2,
}

MOCK_TRANSFERS = [
    {
        "tx_hash": "mock-ton-in-001",
        "logical_time": "46000000000001",
        "timestamp": "2026-06-01T10:00:00Z",
        "asset": "TON",
        "amount": "125.500000000000000000",
        "direction": "in",
        "counterparty": "EQsourceAlpha",
        "raw": {"fixture": "transfer", "surface": "transfers", "index": 1},
    },
    {
        "tx_hash": "mock-jetton-in-002",
        "logical_time": "46000000000002",
        "timestamp": "2026-06-01T10:12:00Z",
        "asset": "JETTON_ALPHA",
        "amount": "4200.000000000000000000",
        "direction": "in",
        "counterparty": "EQjettonVault",
        "raw": {"fixture": "transfer", "surface": "transfers", "index": 2},
    },
    {
        "tx_hash": "mock-ton-out-003",
        "logical_time": "46000000000003",
        "timestamp": "2026-06-01T11:05:00Z",
        "asset": "TON",
        "amount": "12.000000000000000000",
        "direction": "out",
        "counterparty": "EQdestinationBeta",
        "raw": {"fixture": "transfer", "surface": "transfers", "index": 3},
    },
]

MOCK_TRANSACTIONS = [
    {
        "tx_hash": "mock-ton-in-001",
        "logical_time": "46000000000001",
        "timestamp": "2026-06-01T10:00:00Z",
        "fee_ton": "0.004200000000000000",
        "success": "success",
        "raw": {"fixture": "transaction", "surface": "transactions", "index": 1},
    },
    {
        "tx_hash": "mock-jetton-in-002",
        "logical_time": "46000000000002",
        "timestamp": "2026-06-01T10:12:00Z",
        "fee_ton": "0.006500000000000000",
        "success": "success",
        "raw": {"fixture": "transaction", "surface": "transactions", "index": 2},
    },
    {
        "tx_hash": "mock-ton-out-003",
        "logical_time": "46000000000003",
        "timestamp": "2026-06-01T11:05:00Z",
        "fee_ton": "0.003900000000000000",
        "success": "success",
        "raw": {"fixture": "transaction", "surface": "transactions", "index": 3},
    },
]

MOCK_SWAPS = [
    {
        "tx_hash": "mock-swap-001",
        "timestamp": "2026-06-01T10:35:00Z",
        "dex": "STON.fi",
        "token_in": "TON",
        "amount_in": "15.000000000000000000",
        "token_out": "JETTON_ALPHA",
        "amount_out": "3180.000000000000000000",
        "estimated_usd": "94.25000000",
        "raw": {
            "fixture": "swap",
            "surface": "swaps",
            "index": 1,
            "token_in_address": None,
            "token_out_address": "EQjettonAlphaMasterMock",
        },
    },
]

MOCK_BALANCE_SNAPSHOTS = [
    {
        "asset": "TON",
        "balance": "238.750000000000000000",
        "balance_usd": "689.42000000",
        "snapshot_at": MOCK_WALLET_ACTIVITY_FRESHNESS,
        "raw": {"fixture": "balance", "surface": "balances", "index": 1},
    },
    {
        "asset": "JETTON_ALPHA",
        "balance": "7420.000000000000000000",
        "balance_usd": "219.88000000",
        "snapshot_at": MOCK_WALLET_ACTIVITY_FRESHNESS,
        "raw": {"fixture": "jetton", "surface": "jettons", "index": 1},
    },
    {
        "asset": "JETTON_BETA",
        "balance": "88.500000000000000000",
        "balance_usd": "41.12000000",
        "snapshot_at": MOCK_WALLET_ACTIVITY_FRESHNESS,
        "raw": {"fixture": "jetton", "surface": "jettons", "index": 2},
    },
]


@dataclass(frozen=True)
class WalletActivityAdapterRequest:
    wallet_address: str
    time_window: str
    surfaces: list[WalletIngestionSurface]
    environment_data_mode: str
    custom_start: str | None = None
    custom_end: str | None = None
    resolved_start: datetime | None = None
    resolved_end: datetime | None = None


@dataclass(frozen=True)
class WalletActivityProviderEvidence:
    provider: str
    data_mode: WalletDataMode
    source_status: WalletSourceStatus
    warnings: list[str]
    freshness: str | None
    raw_count: int
    normalized_count: int

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "data_mode": self.data_mode,
            "source_status": self.source_status,
            "warnings": self.warnings,
            "freshness": self.freshness,
            "raw_count": self.raw_count,
            "normalized_count": self.normalized_count,
        }


@dataclass(frozen=True)
class WalletActivityTransfer:
    tx_hash: str | None
    logical_time: str | None
    timestamp: str | None
    asset: str
    amount: str | None
    direction: Literal["in", "out", "unknown"]
    counterparty: str | None
    provider: str
    source_status: WalletSourceStatus
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletActivityTransaction:
    tx_hash: str
    logical_time: str | None
    timestamp: str | None
    fee_ton: str | None
    success: Literal["success", "failed", "unknown"]
    provider: str
    source_status: WalletSourceStatus
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletActivitySwap:
    tx_hash: str | None
    timestamp: str | None
    dex: str | None
    token_in: str | None
    amount_in: str | None
    token_out: str | None
    amount_out: str | None
    estimated_usd: str | None
    provider: str
    source_status: WalletSourceStatus
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletActivityBalanceSnapshot:
    asset: str
    balance: str | None
    balance_usd: str | None
    provider: str
    source_status: WalletSourceStatus
    snapshot_at: str | None
    raw: dict[str, Any] | None = None


@dataclass(frozen=True)
class WalletActivityWarning:
    severity: Literal["info", "warning", "error", "critical"]
    provider: str | None
    message: str
    evidence_key: str | None


@dataclass(frozen=True)
class WalletActivityAcquisitionPageEvidence:
    page_index: int
    request_cursor: str | None
    response_cursor: str | None
    requested_limit: int
    raw_count: int
    normalized_count: int
    duplicate_count: int
    min_logical_time: str | None
    max_logical_time: str | None
    min_timestamp: str | None
    max_timestamp: str | None
    response_digest: str
    attempt_count: int
    error_code: str | None
    error_message: str | None
    fetched_at: str

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "page_index": self.page_index,
            "request_cursor": self.request_cursor,
            "response_cursor": self.response_cursor,
            "requested_limit": self.requested_limit,
            "raw_count": self.raw_count,
            "normalized_count": self.normalized_count,
            "duplicate_count": self.duplicate_count,
            "min_logical_time": self.min_logical_time,
            "max_logical_time": self.max_logical_time,
            "min_timestamp": self.min_timestamp,
            "max_timestamp": self.max_timestamp,
            "response_digest": self.response_digest,
            "attempt_count": self.attempt_count,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "fetched_at": self.fetched_at,
        }


@dataclass(frozen=True)
class WalletActivityAcquisitionStreamEvidence:
    provider: str
    stream_key: str
    contract_version: str
    scope_kind: str
    requested_start: str
    requested_end: str
    query_filters: dict[str, Any]
    sort_order: str
    page_size: int
    page_cap: int
    completion_state: str
    termination_reason: str
    page_count: int
    raw_count: int
    normalized_count: int
    duplicate_count: int
    first_cursor: str | None
    terminal_cursor: str | None
    bounds_verified: bool
    started_at: str
    finished_at: str
    error_code: str | None
    error_message: str | None
    pages: list[WalletActivityAcquisitionPageEvidence] = field(
        default_factory=list
    )

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "stream_key": self.stream_key,
            "contract_version": self.contract_version,
            "scope_kind": self.scope_kind,
            "requested_start": self.requested_start,
            "requested_end": self.requested_end,
            "query_filters": self.query_filters,
            "sort_order": self.sort_order,
            "page_size": self.page_size,
            "page_cap": self.page_cap,
            "completion_state": self.completion_state,
            "termination_reason": self.termination_reason,
            "page_count": self.page_count,
            "raw_count": self.raw_count,
            "normalized_count": self.normalized_count,
            "duplicate_count": self.duplicate_count,
            "first_cursor": self.first_cursor,
            "terminal_cursor": self.terminal_cursor,
            "bounds_verified": self.bounds_verified,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "error_code": self.error_code,
            "error_message": self.error_message,
            "pages": [page.to_public_dict() for page in self.pages],
        }


@dataclass(frozen=True)
class WalletActivityAdapterResult:
    status: WalletIngestionStatus
    data_mode: WalletDataMode
    requested_surfaces: list[WalletIngestionSurface]
    provider_evidence: list[WalletActivityProviderEvidence]
    unavailable_surfaces: list[WalletIngestionSurface]
    warnings: list[WalletActivityWarning]
    message: str
    incomplete_surfaces: list[WalletIngestionSurface] = field(default_factory=list)
    acquisition_streams: list[WalletActivityAcquisitionStreamEvidence] = field(
        default_factory=list
    )
    transfers: list[WalletActivityTransfer] = field(default_factory=list)
    transactions: list[WalletActivityTransaction] = field(default_factory=list)
    swaps: list[WalletActivitySwap] = field(default_factory=list)
    balances: list[WalletActivityBalanceSnapshot] = field(default_factory=list)

    @property
    def warning_messages(self) -> list[str]:
        return [warning.message for warning in self.warnings]


@dataclass(frozen=True)
class _TransactionAcquisitionOutcome:
    raw_count: int
    transactions: list[WalletActivityTransaction]
    stream: WalletActivityAcquisitionStreamEvidence
    warnings: list[str]
    fatal: bool
    incomplete: bool


@dataclass(frozen=True)
class _ValidatedTransactionPage:
    rows: list[dict[str, Any]]
    raw_count: int
    response_cursor: str | None
    min_logical_time: str | None
    max_logical_time: str | None
    timestamps: list[datetime | None]
    min_timestamp: str | None
    max_timestamp: str | None
    response_digest: str


@dataclass(frozen=True)
class _EventAcquisitionOutcome:
    raw_count: int
    transfers: list[WalletActivityTransfer]
    swaps: list[WalletActivitySwap]
    stream: WalletActivityAcquisitionStreamEvidence
    warnings: list[str]
    fatal: bool
    incomplete: bool


@dataclass(frozen=True)
class _ValidatedEventPage:
    events: list[dict[str, Any]]
    raw_count: int
    response_cursor: str | None
    min_logical_time: str | None
    max_logical_time: str | None
    timestamps: list[datetime]
    min_timestamp: str | None
    max_timestamp: str | None
    response_digest: str


class WalletActivityAdapter(Protocol):
    """Provider interface for wallet activity ingestion."""

    provider_name: str

    def preview(
        self,
        request: WalletActivityAdapterRequest,
    ) -> WalletActivityAdapterResult:
        """Return provider coverage and warnings without normalized rows."""

    def ingest(
        self,
        request: WalletActivityAdapterRequest,
    ) -> WalletActivityAdapterResult:
        """Return normalized provider rows for persistence."""


@dataclass(frozen=True)
class WalletActivityProviderScaffoldSpec:
    key: str
    provider_name: str
    label: str
    planned_surfaces: tuple[WalletIngestionSurface, ...]
    configuration_label: str


TONAPI_WALLET_ACTIVITY_SCAFFOLD = WalletActivityProviderScaffoldSpec(
    key=WALLET_ACTIVITY_PROVIDER_TONAPI,
    provider_name="tonapi_wallet_activity_scaffold",
    label="TonAPI wallet activity",
    planned_surfaces=("jettons",),
    configuration_label="TONAPI_BASE_URL",
)
TON_PROVIDER_WALLET_ACTIVITY_SCAFFOLD = WalletActivityProviderScaffoldSpec(
    key=WALLET_ACTIVITY_PROVIDER_TON_PROVIDER,
    provider_name="ton_provider_wallet_activity_scaffold",
    label="TON provider wallet activity",
    planned_surfaces=("transfers", "transactions", "balances"),
    configuration_label="TON_API_BASE_URL + TON_API_KEY",
)
STONFI_WALLET_ACTIVITY_SCAFFOLD = WalletActivityProviderScaffoldSpec(
    key=WALLET_ACTIVITY_PROVIDER_STONFI,
    provider_name="stonfi_wallet_activity_scaffold",
    label="STON.fi wallet activity",
    planned_surfaces=("swaps",),
    configuration_label="STONFI_BASE_URL",
)
BITQUERY_WALLET_ACTIVITY_SCAFFOLD = WalletActivityProviderScaffoldSpec(
    key=WALLET_ACTIVITY_PROVIDER_BITQUERY,
    provider_name="bitquery_wallet_activity_scaffold",
    label="Bitquery wallet activity",
    planned_surfaces=("swaps",),
    configuration_label="BITQUERY_API_KEY",
)
WALLET_ACTIVITY_SCAFFOLD_SPECS = {
    TONAPI_WALLET_ACTIVITY_SCAFFOLD.key: TONAPI_WALLET_ACTIVITY_SCAFFOLD,
    TON_PROVIDER_WALLET_ACTIVITY_SCAFFOLD.key: TON_PROVIDER_WALLET_ACTIVITY_SCAFFOLD,
    STONFI_WALLET_ACTIVITY_SCAFFOLD.key: STONFI_WALLET_ACTIVITY_SCAFFOLD,
    BITQUERY_WALLET_ACTIVITY_SCAFFOLD.key: BITQUERY_WALLET_ACTIVITY_SCAFFOLD,
}


class MockWalletActivityAdapter:
    """Deterministic source-aware adapter used until real providers are wired."""

    provider_name = MOCK_WALLET_ACTIVITY_PROVIDER

    def preview(
        self,
        request: WalletActivityAdapterRequest,
    ) -> WalletActivityAdapterResult:
        warnings = _warnings_for_request(request)
        evidence = _provider_evidence(request.surfaces, warnings)
        return WalletActivityAdapterResult(
            status="success",
            data_mode=MOCK_DATA_MODE,
            requested_surfaces=request.surfaces,
            provider_evidence=[evidence],
            unavailable_surfaces=[],
            warnings=_warning_records(warnings),
            message=(
                "Mock-normalized wallet activity coverage is available. "
                "No real provider calls are performed by the default mock "
                "adapter."
            ),
        )

    def ingest(
        self,
        request: WalletActivityAdapterRequest,
    ) -> WalletActivityAdapterResult:
        warnings = _warnings_for_request(request)
        evidence = _provider_evidence(request.surfaces, warnings)
        return WalletActivityAdapterResult(
            status="success",
            data_mode=MOCK_DATA_MODE,
            requested_surfaces=request.surfaces,
            provider_evidence=[evidence],
            unavailable_surfaces=[],
            warnings=_warning_records(warnings),
            transfers=_transfers_for_request(request),
            transactions=_transactions_for_request(request),
            swaps=_swaps_for_request(request),
            balances=_balances_for_request(request),
            message=(
                "Mock-normalized wallet activity ingestion run completed. "
                "The rows are deterministic fixtures and are not connected to "
                "legacy PnL or clustering yet."
            ),
        )


class ProviderScaffoldWalletActivityAdapter:
    """Coverage-only wallet activity scaffold for a future real provider."""

    def __init__(
        self,
        settings: Settings,
        spec: WalletActivityProviderScaffoldSpec,
    ) -> None:
        self.settings = settings
        self.spec = spec
        self.provider_name = spec.provider_name

    def preview(
        self,
        request: WalletActivityAdapterRequest,
    ) -> WalletActivityAdapterResult:
        return self._result(request, mode="preview")

    def ingest(
        self,
        request: WalletActivityAdapterRequest,
    ) -> WalletActivityAdapterResult:
        return self._result(request, mode="ingest")

    def _result(
        self,
        request: WalletActivityAdapterRequest,
        mode: Literal["preview", "ingest"],
    ) -> WalletActivityAdapterResult:
        configured = _provider_scaffold_configured(self.spec.key, self.settings)
        source_status: WalletSourceStatus = "limited" if configured else "unavailable"
        status: WalletIngestionStatus = "partial" if configured else "error"
        warnings = self._warnings(request, configured)
        action = "coverage preview" if mode == "preview" else "ingestion run"

        return WalletActivityAdapterResult(
            status=status,
            data_mode="real",
            requested_surfaces=request.surfaces,
            provider_evidence=[
                WalletActivityProviderEvidence(
                    provider=self.provider_name,
                    data_mode="real",
                    source_status=source_status,
                    warnings=warnings,
                    freshness=None,
                    raw_count=0,
                    normalized_count=0,
                )
            ],
            unavailable_surfaces=list(request.surfaces),
            warnings=_warning_records_for_provider(warnings, self.provider_name),
            message=(
                f"{self.spec.label} scaffold returned {action} metadata only. "
                "No real wallet activity provider calls are performed in "
                "this scaffold path."
            ),
        )

    def _warnings(
        self,
        request: WalletActivityAdapterRequest,
        configured: bool,
    ) -> list[str]:
        planned = ", ".join(self.spec.planned_surfaces) or "none"
        warnings = [
            (
                f"{self.spec.label} is selected by "
                f"WALLET_ACTIVITY_PROVIDER={self.spec.key}."
            ),
            (
                "Provider-specific wallet activity adapters are scaffold-only "
                "unless an explicitly implemented live path is enabled; "
                "scaffold paths expose status and coverage limits but do not "
                "fetch or persist real provider rows."
            ),
            (
                f"Planned surface coverage for this scaffold: {planned}. "
                "Requested surfaces remain unavailable until the live adapter "
                "implementation is explicitly enabled."
            ),
        ]
        if not configured:
            warnings.append(
                f"{self.spec.configuration_label} is missing or invalid for "
                f"{self.spec.label}."
            )
        if request.environment_data_mode != "real":
            warnings.append(
                "This scaffold only activates in DATA_MODE=real; mock mode "
                "continues to use deterministic fixtures."
            )
        return warnings


class TonapiWalletActivityScaffoldAdapter(ProviderScaffoldWalletActivityAdapter):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, TONAPI_WALLET_ACTIVITY_SCAFFOLD)


TONAPI_LIVE_SUPPORTED_SURFACES: tuple[WalletIngestionSurface, ...] = (
    "balances",
    "jettons",
    "transactions",
    "transfers",
    "swaps",
)


class TonapiWalletActivityLiveAdapter:
    """Guarded live TonAPI adapter for the full account activity surface set.

    DEX swaps parsed from account events (``JettonSwap`` actions) are fetched
    alongside balance snapshots, transaction history, and TON/jetton transfers.
    Persisted rows can feed scoped signals, PnL, and clustering; full-history
    cost basis and ownership proof remain unavailable.
    """

    provider_name = "tonapi_wallet_activity_live"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.tonapi = TonapiAdapter(settings)

    def preview(
        self,
        request: WalletActivityAdapterRequest,
    ) -> WalletActivityAdapterResult:
        return self._fetch_live_activity(request, mode="preview")

    def ingest(
        self,
        request: WalletActivityAdapterRequest,
    ) -> WalletActivityAdapterResult:
        return self._fetch_live_activity(request, mode="ingest")

    def _fetch_transaction_acquisition(
        self,
        request: WalletActivityAdapterRequest,
        mode: Literal["preview", "ingest"],
    ) -> _TransactionAcquisitionOutcome:
        started_at = _now_utc_iso()
        page_size = max(
            1,
            min(1000, int(self.settings.wallet_activity_live_tx_limit)),
        )
        configured_page_cap = max(
            1,
            min(
                100,
                int(
                    getattr(
                        self.settings,
                        "wallet_activity_live_tx_max_pages",
                        1,
                    )
                ),
            ),
        )

        try:
            bounds = _resolved_transaction_bounds(request)
        except ValueError as exc:
            error_message = _sanitize_provider_message(str(exc), self.settings)
            finished_at = _now_utc_iso()
            stream = _transaction_stream_evidence(
                request=request,
                page_size=page_size,
                page_cap=1,
                completion_state="error",
                termination_reason="protocol_error",
                pages=[],
                raw_count=0,
                normalized_count=0,
                duplicate_count=0,
                terminal_cursor=None,
                bounds_verified=False,
                started_at=started_at,
                finished_at=finished_at,
                error_code="protocol_error",
                error_message=error_message,
                bounds=None,
            )
            return _TransactionAcquisitionOutcome(
                raw_count=0,
                transactions=[],
                stream=stream,
                warnings=[
                    f"TonAPI transaction acquisition protocol error: {error_message}"
                ],
                fatal=True,
                incomplete=True,
            )

        bounded = bounds is not None
        page_cap = (
            1
            if mode == "preview" or not bounded
            else configured_page_cap
        )
        pages: list[WalletActivityAcquisitionPageEvidence] = []
        accepted_rows: list[dict[str, Any]] = []
        transactions: list[WalletActivityTransaction] = []
        seen: dict[tuple[str, str], datetime | None] = {}
        total_raw = 0
        total_duplicates = 0
        cursor: str | None = None
        last_unique_lt: int | None = None
        last_unique_timestamp: datetime | None = None
        completion_state = "incomplete"
        termination_reason = "page_cap_reached"
        error_code: str | None = None
        error_message: str | None = None
        fatal = False

        for page_index in range(1, page_cap + 1):
            fetched_at = _now_utc_iso()
            if bounded:
                provider_result = self.tonapi.get_account_transactions_page(
                    request.wallet_address,
                    limit=page_size,
                    before_lt=cursor,
                )
            else:
                provider_result = self.tonapi.get_account_transactions_preview(
                    request.wallet_address,
                    limit=page_size,
                )

            if not provider_result.ok:
                provider_error_code = provider_result.error or "provider_error"
                provider_protocol_error = (
                    provider_error_code == ERROR_PROVIDER_PROTOCOL
                )
                error_code = (
                    "protocol_error"
                    if provider_protocol_error
                    else provider_error_code
                )
                error_message = _sanitize_provider_message(
                    provider_result.message or "TonAPI transaction request failed.",
                    self.settings,
                )
                pages.append(
                    _transaction_error_page_evidence(
                        page_index=page_index,
                        request_cursor=cursor,
                        requested_limit=page_size,
                        response=provider_result.data,
                        error_code=error_code,
                        error_message=error_message,
                        fetched_at=fetched_at,
                    )
                )
                fatal = not accepted_rows
                completion_state = "error" if fatal else "incomplete"
                termination_reason = (
                    "protocol_error"
                    if provider_protocol_error
                    else "provider_error"
                )
                break

            provider_data = provider_result.data
            if not bounded:
                provider_data = _legacy_transaction_page_data(
                    provider_data,
                    page_size=page_size,
                )

            try:
                validated = _validate_transaction_page(
                    provider_data,
                    request_cursor=cursor,
                    requested_limit=page_size,
                    require_timestamps=bounded,
                )

                page_seen = dict(seen)
                page_last_lt = last_unique_lt
                page_last_timestamp = last_unique_timestamp
                page_duplicates = 0
                page_accepted: list[dict[str, Any]] = []
                crossed_requested_start = False

                for row, timestamp in zip(
                    validated.rows,
                    validated.timestamps,
                ):
                    logical_time = row["logical_time"]
                    tx_hash = row["tx_hash"]
                    identity = (logical_time, tx_hash.lower())
                    prior_timestamp = page_seen.get(identity)
                    if identity in page_seen:
                        if bounded and prior_timestamp != timestamp:
                            raise ValueError(
                                "duplicate transaction identity changed timestamp"
                            )
                        page_duplicates += 1
                        continue

                    logical_time_value = int(logical_time, 10)
                    if (
                        page_last_lt is not None
                        and logical_time_value >= page_last_lt
                    ):
                        raise ValueError(
                            "transaction pages are not globally descending by "
                            "logical time"
                        )
                    if (
                        bounded
                        and page_last_timestamp is not None
                        and timestamp is not None
                        and timestamp > page_last_timestamp
                    ):
                        raise ValueError(
                            "transaction timestamps are not globally ordered"
                        )

                    page_seen[identity] = timestamp
                    page_last_lt = logical_time_value
                    if timestamp is not None:
                        page_last_timestamp = timestamp

                    if bounded:
                        assert bounds is not None
                        assert timestamp is not None
                        if timestamp < bounds[0]:
                            crossed_requested_start = True
                            continue
                        if timestamp >= bounds[1]:
                            continue
                    page_accepted.append(row)

                page_evidence = WalletActivityAcquisitionPageEvidence(
                    page_index=page_index,
                    request_cursor=cursor,
                    response_cursor=validated.response_cursor,
                    requested_limit=page_size,
                    raw_count=validated.raw_count,
                    normalized_count=len(page_accepted),
                    duplicate_count=page_duplicates,
                    min_logical_time=validated.min_logical_time,
                    max_logical_time=validated.max_logical_time,
                    min_timestamp=validated.min_timestamp,
                    max_timestamp=validated.max_timestamp,
                    response_digest=validated.response_digest,
                    attempt_count=1,
                    error_code=None,
                    error_message=None,
                    fetched_at=fetched_at,
                )
            except (AssertionError, KeyError, TypeError, ValueError) as exc:
                error_code = "protocol_error"
                error_message = _sanitize_provider_message(str(exc), self.settings)
                pages.append(
                    _transaction_error_page_evidence(
                        page_index=page_index,
                        request_cursor=cursor,
                        requested_limit=page_size,
                        response=provider_data,
                        error_code=error_code,
                        error_message=error_message,
                        fetched_at=fetched_at,
                    )
                )
                fatal = not accepted_rows
                completion_state = "error" if fatal else "incomplete"
                termination_reason = "protocol_error"
                break

            pages.append(page_evidence)
            total_raw += validated.raw_count
            total_duplicates += page_duplicates
            seen = page_seen
            last_unique_lt = page_last_lt
            last_unique_timestamp = page_last_timestamp
            accepted_rows.extend(page_accepted)
            if mode == "ingest":
                transactions.extend(_tonapi_live_transactions(page_accepted))

            if mode == "preview":
                completion_state = "preview_only"
                termination_reason = "preview_page_limit"
                cursor = validated.response_cursor
                break
            if not bounded:
                completion_state = "incomplete"
                termination_reason = "legacy_unavailable"
                cursor = validated.response_cursor
                break
            if validated.raw_count == 0:
                completion_state = "complete"
                termination_reason = "provider_terminal"
                cursor = None
                break
            if crossed_requested_start:
                completion_state = "complete"
                termination_reason = "requested_start_crossed"
                cursor = validated.response_cursor
                break

            cursor = validated.response_cursor
        else:
            completion_state = "incomplete"
            termination_reason = "page_cap_reached"

        finished_at = _now_utc_iso()
        bounds_verified = bounded and completion_state == "complete"
        stream = _transaction_stream_evidence(
            request=request,
            page_size=page_size,
            page_cap=page_cap,
            completion_state=completion_state,
            termination_reason=termination_reason,
            pages=pages,
            raw_count=total_raw,
            normalized_count=len(accepted_rows),
            duplicate_count=total_duplicates,
            terminal_cursor=cursor,
            bounds_verified=bounds_verified,
            started_at=started_at,
            finished_at=finished_at,
            error_code=error_code,
            error_message=error_message,
            bounds=bounds,
        )

        if completion_state == "preview_only":
            outcome_warnings = [
                "TonAPI transaction preview fetched exactly one page. It does "
                "not verify interval completeness or pagination termination."
            ]
        elif termination_reason == "legacy_unavailable":
            outcome_warnings = [
                "TonAPI transaction ingestion used the legacy one-page path "
                "because immutable resolved bounds were unavailable. History "
                "completeness remains unverified."
            ]
        elif completion_state == "complete":
            outcome_warnings = [
                "TonAPI transaction pagination terminated within the resolved "
                "interval contract. This does not establish cost basis or PnL."
            ]
        elif termination_reason in ("provider_error", "protocol_error"):
            detail = error_message or termination_reason
            outcome_warnings = [
                f"TonAPI transaction-history warning: {detail}. "
                "Pagination is incomplete and no full-history claim is made."
            ]
        else:
            detail = error_message or termination_reason
            outcome_warnings = [
                "TonAPI transaction pagination is incomplete: "
                f"{detail}. No full-history claim is made."
            ]

        return _TransactionAcquisitionOutcome(
            raw_count=total_raw,
            transactions=transactions,
            stream=stream,
            warnings=outcome_warnings,
            fatal=fatal,
            incomplete=completion_state in (
                "preview_only",
                "incomplete",
                "error",
            ),
        )

    def _fetch_event_acquisition(
        self,
        request: WalletActivityAdapterRequest,
        mode: Literal["preview", "ingest"],
        *,
        include_transfers: bool,
        include_swaps: bool,
    ) -> _EventAcquisitionOutcome:
        started_at = _now_utc_iso()
        page_size = max(
            1,
            min(
                100,
                int(
                    getattr(
                        self.settings,
                        "wallet_activity_live_event_limit",
                        100,
                    )
                ),
            ),
        )
        configured_cap = max(
            1,
            min(
                100,
                int(
                    getattr(
                        self.settings,
                        "wallet_activity_live_event_max_pages",
                        10,
                    )
                ),
            ),
        )
        try:
            bounds = _resolved_transaction_bounds(request)
        except ValueError as exc:
            error_message = _sanitize_provider_message(str(exc), self.settings)
            finished_at = _now_utc_iso()
            stream = _event_stream_evidence(
                page_size=page_size,
                page_cap=1,
                completion_state="error",
                termination_reason="protocol_error",
                pages=[],
                raw_count=0,
                normalized_count=0,
                duplicate_count=0,
                terminal_cursor=None,
                bounds_verified=False,
                started_at=started_at,
                finished_at=finished_at,
                error_code="protocol_error",
                error_message=error_message,
                bounds=None,
            )
            return _EventAcquisitionOutcome(
                raw_count=0,
                transfers=[],
                swaps=[],
                stream=stream,
                warnings=[
                    f"TonAPI account event acquisition protocol error: {error_message}"
                ],
                fatal=True,
                incomplete=True,
            )

        bounded = bounds is not None
        page_cap = 1 if mode == "preview" or not bounded else configured_cap
        query_start, query_end = _event_query_dates(bounds)
        pages: list[WalletActivityAcquisitionPageEvidence] = []
        accepted_events: list[dict[str, Any]] = []
        transfers: list[WalletActivityTransfer] = []
        swaps: list[WalletActivitySwap] = []
        seen: dict[str, tuple[str, datetime, str]] = {}
        cursor: str | None = None
        last_lt: int | None = None
        last_timestamp: datetime | None = None
        total_raw = 0
        total_duplicates = 0
        completion_state = "incomplete"
        termination_reason = "page_cap_reached"
        error_code: str | None = None
        error_message: str | None = None
        fatal = False
        saw_in_progress = False

        for page_index in range(1, page_cap + 1):
            fetched_at = _now_utc_iso()
            provider_result = self.tonapi.get_account_events_page(
                request.wallet_address,
                limit=page_size,
                before_lt=cursor,
                start_date=query_start,
                end_date=query_end,
            )
            if not provider_result.ok:
                is_protocol = provider_result.error == ERROR_PROVIDER_PROTOCOL
                error_code = (
                    "protocol_error"
                    if is_protocol
                    else provider_result.error or "provider_error"
                )
                error_message = _sanitize_provider_message(
                    provider_result.message or "TonAPI account event request failed.",
                    self.settings,
                )
                pages.append(
                    _transaction_error_page_evidence(
                        page_index=page_index,
                        request_cursor=cursor,
                        requested_limit=page_size,
                        response=provider_result.data,
                        error_code=error_code,
                        error_message=error_message,
                        fetched_at=fetched_at,
                    )
                )
                fatal = not accepted_events
                completion_state = "error" if fatal else "incomplete"
                termination_reason = (
                    "protocol_error" if is_protocol else "provider_error"
                )
                break

            provider_data = provider_result.data
            try:
                validated = _validate_event_page(
                    provider_data,
                    request_cursor=cursor,
                    requested_limit=page_size,
                )
                page_seen = dict(seen)
                page_last_lt = last_lt
                page_last_timestamp = last_timestamp
                page_accepted: list[dict[str, Any]] = []
                page_duplicates = 0
                page_in_progress = False
                crossed_start = False
                for event, timestamp in zip(
                    validated.events,
                    validated.timestamps,
                ):
                    logical_time_text = event["lt"]
                    event_identity = event["event_id"].lower()
                    event_fingerprint = _stable_page_digest(event)
                    prior_event = page_seen.get(event_identity)
                    if prior_event is not None:
                        if prior_event != (
                            logical_time_text,
                            timestamp,
                            event_fingerprint,
                        ):
                            raise ValueError(
                                "duplicate account event changed logical time, "
                                "timestamp, or payload"
                            )
                        page_duplicates += 1
                        continue
                    logical_time = int(logical_time_text, 10)
                    if page_last_lt is not None and logical_time >= page_last_lt:
                        raise ValueError(
                            "account event pages are not globally descending"
                        )
                    if (
                        page_last_timestamp is not None
                        and timestamp > page_last_timestamp
                    ):
                        raise ValueError(
                            "account event timestamps are not globally ordered"
                        )
                    page_seen[event_identity] = (
                        logical_time_text,
                        timestamp,
                        event_fingerprint,
                    )
                    page_last_lt = logical_time
                    page_last_timestamp = timestamp
                    if bounded:
                        assert bounds is not None
                        if timestamp < bounds[0]:
                            crossed_start = True
                            continue
                        if timestamp >= bounds[1]:
                            continue
                    if event.get("in_progress") is True:
                        page_in_progress = True
                        continue
                    page_accepted.append(event)

                payload = {"events": page_accepted}
                transfer_rows = (
                    self.tonapi.normalize_account_events_response(
                        payload,
                        request.wallet_address,
                    )
                    if include_transfers
                    else []
                )
                swap_rows = (
                    self.tonapi.normalize_account_swaps_response(
                        payload,
                        request.wallet_address,
                    )
                    if include_swaps
                    else []
                )
                page_transfers = (
                    _tonapi_live_transfers(transfer_rows)
                    if mode == "ingest"
                    else []
                )
                page_swaps = (
                    _tonapi_live_swaps(swap_rows)
                    if mode == "ingest"
                    else []
                )
                page_evidence = WalletActivityAcquisitionPageEvidence(
                    page_index=page_index,
                    request_cursor=cursor,
                    response_cursor=validated.response_cursor,
                    requested_limit=page_size,
                    raw_count=validated.raw_count,
                    normalized_count=len(page_accepted),
                    duplicate_count=page_duplicates,
                    min_logical_time=validated.min_logical_time,
                    max_logical_time=validated.max_logical_time,
                    min_timestamp=validated.min_timestamp,
                    max_timestamp=validated.max_timestamp,
                    response_digest=validated.response_digest,
                    attempt_count=1,
                    error_code=None,
                    error_message=None,
                    fetched_at=fetched_at,
                )
            except (
                AssertionError,
                ArithmeticError,
                KeyError,
                TypeError,
                ValueError,
            ) as exc:
                error_code = "protocol_error"
                error_message = _sanitize_provider_message(str(exc), self.settings)
                pages.append(
                    _transaction_error_page_evidence(
                        page_index=page_index,
                        request_cursor=cursor,
                        requested_limit=page_size,
                        response=provider_data,
                        error_code=error_code,
                        error_message=error_message,
                        fetched_at=fetched_at,
                    )
                )
                fatal = not accepted_events
                completion_state = "error" if fatal else "incomplete"
                termination_reason = "protocol_error"
                break

            pages.append(page_evidence)
            total_raw += validated.raw_count
            total_duplicates += page_duplicates
            seen = page_seen
            last_lt = page_last_lt
            last_timestamp = page_last_timestamp
            accepted_events.extend(page_accepted)
            transfers.extend(page_transfers)
            swaps.extend(page_swaps)
            saw_in_progress = saw_in_progress or page_in_progress

            if mode == "preview":
                completion_state = "preview_only"
                termination_reason = "preview_page_limit"
                cursor = validated.response_cursor
                break
            if not bounded:
                completion_state = "incomplete"
                termination_reason = "legacy_unavailable"
                cursor = validated.response_cursor
                break
            if validated.raw_count == 0 or crossed_start:
                if saw_in_progress:
                    completion_state = "incomplete"
                    termination_reason = "provider_event_in_progress"
                else:
                    completion_state = "complete"
                    termination_reason = (
                        "provider_terminal"
                        if validated.raw_count == 0
                        else "requested_start_crossed"
                    )
                cursor = (
                    None
                    if validated.raw_count == 0
                    else validated.response_cursor
                )
                break
            cursor = validated.response_cursor
        else:
            completion_state = "incomplete"
            termination_reason = "page_cap_reached"

        stream = _event_stream_evidence(
            page_size=page_size,
            page_cap=page_cap,
            completion_state=completion_state,
            termination_reason=termination_reason,
            pages=pages,
            raw_count=total_raw,
            normalized_count=len(accepted_events),
            duplicate_count=total_duplicates,
            terminal_cursor=cursor,
            bounds_verified=bounded and completion_state == "complete",
            started_at=started_at,
            finished_at=_now_utc_iso(),
            error_code=error_code,
            error_message=error_message,
            bounds=bounds,
        )
        if completion_state == "preview_only":
            outcome_warnings = [
                "TonAPI account event preview fetched exactly one page. It "
                "does not verify pagination or derived action completeness."
            ]
        elif completion_state == "complete":
            outcome_warnings = [
                "TonAPI account event pagination terminated for the bounded "
                "provider display stream. Derived actions can change and are "
                "not authoritative transaction logic."
            ]
        elif termination_reason == "provider_event_in_progress":
            outcome_warnings = [
                "TonAPI returned an in-progress event inside the requested "
                "interval. Derived action coverage remains incomplete."
            ]
        else:
            detail = error_message or termination_reason
            outcome_warnings = [
                "TonAPI account event pagination is incomplete: "
                f"{detail}. Derived actions remain display-only evidence."
            ]
        return _EventAcquisitionOutcome(
            raw_count=total_raw,
            transfers=transfers,
            swaps=swaps,
            stream=stream,
            warnings=outcome_warnings,
            fatal=fatal,
            incomplete=completion_state in (
                "preview_only",
                "incomplete",
                "error",
            ),
        )

    def _fetch_live_activity(
        self,
        request: WalletActivityAdapterRequest,
        mode: Literal["preview", "ingest"],
    ) -> WalletActivityAdapterResult:
        requested_surfaces = list(request.surfaces)
        unavailable_surfaces = [
            surface
            for surface in requested_surfaces
            if surface not in TONAPI_LIVE_SUPPORTED_SURFACES
        ]
        warnings = _tonapi_live_warnings(unavailable_surfaces)
        supported_requested = [
            surface
            for surface in TONAPI_LIVE_SUPPORTED_SURFACES
            if surface in requested_surfaces
        ]
        successful_supported_surfaces: list[WalletIngestionSurface] = []
        failed_supported_surfaces: list[WalletIngestionSurface] = []
        incomplete_surfaces: list[WalletIngestionSurface] = []
        acquisition_streams: list[WalletActivityAcquisitionStreamEvidence] = []
        raw_count = 0
        balances: list[WalletActivityBalanceSnapshot] = []
        transactions: list[WalletActivityTransaction] = []
        transfers: list[WalletActivityTransfer] = []
        swaps: list[WalletActivitySwap] = []

        if not supported_requested:
            warnings.append(
                "TonAPI live guard has no requested balance, jetton, "
                "transaction-history, transfer, or swap surface to fetch."
            )
            return self._live_result(
                requested_surfaces=requested_surfaces,
                unavailable_surfaces=unavailable_surfaces,
                warnings=warnings,
                status="partial" if unavailable_surfaces else "success",
                raw_count=0,
                balances=[],
                transactions=[],
                transfers=[],
                swaps=[],
                message=(
                    "Guarded TonAPI live adapter was enabled, but no native "
                    "TON balance, jetton balance, transaction-history, "
                    "transfer, or swap surface was requested."
                ),
            )

        if "balances" in requested_surfaces:
            result = self.tonapi.get_account_balance_preview(
                request.wallet_address
            )
            if not result.ok:
                message = (
                    result.message
                    or "TonAPI live native balance request failed."
                )
                warnings.append(f"TonAPI native balance warning: {message}")
                unavailable_surfaces.append("balances")
                failed_supported_surfaces.append("balances")
            else:
                data = result.data if isinstance(result.data, dict) else {}
                native_balance = data.get("balance")
                if isinstance(native_balance, dict):
                    raw_count += 1
                    successful_supported_surfaces.append("balances")
                    if mode == "ingest":
                        balances.append(
                            _tonapi_live_native_balance_snapshot(native_balance)
                        )
                else:
                    warnings.append(
                        "TonAPI native balance response did not include a "
                        "usable balance snapshot."
                    )
                    unavailable_surfaces.append("balances")
                    failed_supported_surfaces.append("balances")

        if "jettons" in requested_surfaces:
            result = self.tonapi.get_account_jettons_preview(
                request.wallet_address,
                limit=self.settings.wallet_activity_live_jetton_limit,
            )
            if not result.ok:
                message = result.message or "TonAPI live jetton request failed."
                warnings.append(f"TonAPI jetton balance warning: {message}")
                unavailable_surfaces.append("jettons")
                failed_supported_surfaces.append("jettons")
            else:
                data = result.data if isinstance(result.data, dict) else {}
                jettons = (
                    data.get("jettons")
                    if isinstance(data.get("jettons"), list)
                    else []
                )
                total_jettons = _safe_int(data.get("total_jettons"), len(jettons))
                preview_count = _safe_int(data.get("preview_count"), len(jettons))
                raw_count += total_jettons
                successful_supported_surfaces.append("jettons")
                if total_jettons > preview_count:
                    warnings.append(
                        f"TonAPI returned {preview_count} of {total_jettons} "
                        "jettons within WALLET_ACTIVITY_LIVE_JETTON_LIMIT."
                    )
                if total_jettons == 0:
                    warnings.append(
                        "TonAPI returned zero jettons for this guarded fetch. "
                        "This is not evidence that the wallet has no activity."
                    )
                if mode == "ingest":
                    balances.extend(_tonapi_live_balance_snapshots(jettons))

        if "transactions" in requested_surfaces:
            transaction_outcome = self._fetch_transaction_acquisition(
                request,
                mode,
            )
            raw_count += transaction_outcome.raw_count
            transactions.extend(transaction_outcome.transactions)
            acquisition_streams.append(transaction_outcome.stream)
            warnings.extend(transaction_outcome.warnings)
            if transaction_outcome.incomplete:
                incomplete_surfaces.append("transactions")
            if transaction_outcome.fatal:
                unavailable_surfaces.append("transactions")
                failed_supported_surfaces.append("transactions")
            else:
                successful_supported_surfaces.append("transactions")
                if transaction_outcome.raw_count == 0:
                    warnings.append(
                        "TonAPI returned zero transactions for this guarded "
                        "fetch. This is not evidence that the wallet has no "
                        "activity."
                    )

        event_surfaces = [
            surface
            for surface in ("transfers", "swaps")
            if surface in requested_surfaces
        ]
        if event_surfaces:
            event_outcome = self._fetch_event_acquisition(
                request,
                mode,
                include_transfers="transfers" in event_surfaces,
                include_swaps="swaps" in event_surfaces,
            )
            raw_count += event_outcome.raw_count
            transfers.extend(event_outcome.transfers)
            swaps.extend(event_outcome.swaps)
            acquisition_streams.append(event_outcome.stream)
            warnings.extend(event_outcome.warnings)

            # TonAPI explicitly defines events/actions as mutable display data.
            # Even a fully traversed provider page chain cannot make derived
            # transfer or swap actions authoritative activity evidence.
            incomplete_surfaces.extend(event_surfaces)
            if event_outcome.fatal:
                unavailable_surfaces.extend(event_surfaces)
                failed_supported_surfaces.extend(event_surfaces)
            else:
                successful_supported_surfaces.extend(event_surfaces)
                if event_outcome.raw_count == 0:
                    warnings.append(
                        "TonAPI returned zero account events for this guarded "
                        "fetch. This is not evidence that the wallet has no "
                        "transfer or swap activity."
                    )

        unavailable_surfaces = list(dict.fromkeys(unavailable_surfaces))
        incomplete_surfaces = list(dict.fromkeys(incomplete_surfaces))
        display_event_surfaces_requested = bool(event_surfaces)
        limiting_incomplete = any(
            stream.completion_state in ("incomplete", "error")
            and stream.termination_reason != "legacy_unavailable"
            for stream in acquisition_streams
        )
        if failed_supported_surfaces and not successful_supported_surfaces:
            status: WalletIngestionStatus = "error"
            source_status: WalletSourceStatus = "error"
            message = (
                "Guarded TonAPI live adapter could not fetch the requested "
                "balance, transaction-history, transfer, or swap data. No live "
                "wallet activity rows were persisted."
            )
        else:
            status = (
                "partial"
                if unavailable_surfaces
                or display_event_surfaces_requested
                or limiting_incomplete
                else "success"
            )
            source_status = (
                "limited"
                if failed_supported_surfaces
                or display_event_surfaces_requested
                or limiting_incomplete
                else "live"
            )
            message = (
                "Guarded TonAPI live activity fetched. Scope is native TON "
                "balance, account jetton balances, account transaction "
                "history, plus display-only TON/jetton transfer and DEX swap "
                "actions derived from one bounded account-event stream. "
                "Provider event actions remain non-authoritative and cannot "
                "establish ownership, complete trade history, or PnL."
            )

        return self._live_result(
            requested_surfaces=requested_surfaces,
            unavailable_surfaces=unavailable_surfaces,
            warnings=warnings,
            status=status,
            raw_count=raw_count,
            balances=balances,
            transactions=transactions,
            transfers=transfers,
            swaps=swaps,
            message=message,
            source_status=source_status,
            incomplete_surfaces=incomplete_surfaces,
            acquisition_streams=acquisition_streams,
        )

    def _live_result(
        self,
        requested_surfaces: list[WalletIngestionSurface],
        unavailable_surfaces: list[WalletIngestionSurface],
        warnings: list[str],
        status: WalletIngestionStatus,
        raw_count: int,
        balances: list[WalletActivityBalanceSnapshot],
        message: str,
        transactions: list[WalletActivityTransaction] | None = None,
        transfers: list[WalletActivityTransfer] | None = None,
        swaps: list[WalletActivitySwap] | None = None,
        source_status: WalletSourceStatus = "live",
        incomplete_surfaces: list[WalletIngestionSurface] | None = None,
        acquisition_streams: list[
            WalletActivityAcquisitionStreamEvidence
        ] | None = None,
    ) -> WalletActivityAdapterResult:
        transactions = transactions or []
        transfers = transfers or []
        swaps = swaps or []
        incomplete_surfaces = incomplete_surfaces or []
        acquisition_streams = acquisition_streams or []
        return WalletActivityAdapterResult(
            status=status,
            data_mode="real",
            requested_surfaces=requested_surfaces,
            provider_evidence=[
                WalletActivityProviderEvidence(
                    provider=self.provider_name,
                    data_mode="real",
                    source_status=source_status,
                    warnings=warnings,
                    freshness=_now_utc_iso(),
                    raw_count=raw_count,
                    normalized_count=(
                        len(balances)
                        + len(transactions)
                        + len(transfers)
                        + len(swaps)
                    ),
                )
            ],
            unavailable_surfaces=unavailable_surfaces,
            warnings=_warning_records_for_provider(warnings, self.provider_name),
            message=message,
            incomplete_surfaces=incomplete_surfaces,
            acquisition_streams=acquisition_streams,
            balances=balances,
            transactions=transactions,
            transfers=transfers,
            swaps=swaps,
        )


class TonProviderWalletActivityScaffoldAdapter(
    ProviderScaffoldWalletActivityAdapter
):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, TON_PROVIDER_WALLET_ACTIVITY_SCAFFOLD)


class StonfiWalletActivityScaffoldAdapter(ProviderScaffoldWalletActivityAdapter):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, STONFI_WALLET_ACTIVITY_SCAFFOLD)


class BitqueryWalletActivityScaffoldAdapter(ProviderScaffoldWalletActivityAdapter):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings, BITQUERY_WALLET_ACTIVITY_SCAFFOLD)


class UnsupportedWalletActivityProviderAdapter(ProviderScaffoldWalletActivityAdapter):
    def __init__(self, settings: Settings, provider_key: str) -> None:
        spec = WalletActivityProviderScaffoldSpec(
            key=provider_key,
            provider_name="unsupported_wallet_activity_provider",
            label="Unsupported wallet activity provider",
            planned_surfaces=(),
            configuration_label="WALLET_ACTIVITY_PROVIDER",
        )
        super().__init__(settings, spec)


def build_wallet_activity_adapter(settings=None) -> WalletActivityAdapter:
    """Return the configured wallet activity adapter.

    Mock remains the default even in DATA_MODE=real. Provider-specific
    scaffolds activate only when DATA_MODE=real and WALLET_ACTIVITY_PROVIDER is
    explicitly set to a non-mock provider key.
    """
    settings = settings or get_settings()
    provider_key = _wallet_activity_provider_key(settings)
    if settings.is_mock or provider_key == WALLET_ACTIVITY_PROVIDER_MOCK:
        return MockWalletActivityAdapter()
    if provider_key == WALLET_ACTIVITY_PROVIDER_TONAPI:
        if settings.wallet_activity_live_enabled:
            return TonapiWalletActivityLiveAdapter(settings)
        return TonapiWalletActivityScaffoldAdapter(settings)
    if provider_key == WALLET_ACTIVITY_PROVIDER_TON_PROVIDER:
        return TonProviderWalletActivityScaffoldAdapter(settings)
    if provider_key == WALLET_ACTIVITY_PROVIDER_STONFI:
        return StonfiWalletActivityScaffoldAdapter(settings)
    if provider_key == WALLET_ACTIVITY_PROVIDER_BITQUERY:
        return BitqueryWalletActivityScaffoldAdapter(settings)
    return UnsupportedWalletActivityProviderAdapter(settings, provider_key)


def get_wallet_activity_provider_status(settings=None) -> dict[str, Any]:
    """Return status for the configured wallet activity ingestion adapter."""
    settings = settings or get_settings()
    provider_key = _wallet_activity_provider_key(settings)

    if provider_key not in WALLET_ACTIVITY_PROVIDER_CHOICES:
        return {
            "configured": False,
            "available": False,
            "message": (
                f"WALLET_ACTIVITY_PROVIDER={provider_key} is unsupported. "
                "Use mock, tonapi, ton_provider, stonfi, or bitquery."
            ),
        }

    if settings.is_mock:
        if provider_key == WALLET_ACTIVITY_PROVIDER_MOCK:
            message = (
                "Mock mode: wallet activity ingestion uses the deterministic "
                "mock adapter. Provider-specific scaffolds are inactive."
            )
        else:
            message = (
                f"Mock mode: WALLET_ACTIVITY_PROVIDER={provider_key} is set, "
                "but wallet activity ingestion still uses deterministic mock "
                "fixtures. Switch DATA_MODE=real to inspect scaffold coverage."
            )
        return {
            "configured": True,
            "available": True,
            "message": message,
        }

    if provider_key == WALLET_ACTIVITY_PROVIDER_MOCK:
        return {
            "configured": True,
            "available": True,
            "message": (
                "Real mode: wallet activity ingestion is intentionally pinned "
                "to the deterministic mock adapter because "
                "WALLET_ACTIVITY_PROVIDER=mock. No real wallet provider calls "
                "are made."
            ),
        }

    spec = WALLET_ACTIVITY_SCAFFOLD_SPECS[provider_key]
    configured = _provider_scaffold_configured(provider_key, settings)
    if not configured:
        return {
            "configured": False,
            "available": False,
            "message": (
                f"Real mode: {spec.label} scaffold is selected, but "
                f"{spec.configuration_label} is missing or invalid. Wallet "
                "activity ingestion will return unavailable coverage only."
            ),
        }

    if (
        provider_key == WALLET_ACTIVITY_PROVIDER_TONAPI
        and settings.wallet_activity_live_enabled
    ):
        return {
            "configured": True,
            "available": True,
            "message": (
                "Real mode: guarded live TonAPI wallet activity is enabled. "
                "Native TON balance, account jetton balance snapshots, account "
                "transaction history, and one bounded account-event stream can "
                "be fetched. Derived transfers and DEX swaps are mutable "
                "provider display data; they remain incomplete and cannot "
                "establish ownership, cost basis, or PnL."
            ),
        }

    return {
        "configured": True,
        "available": False,
        "message": (
            f"Real mode: {spec.label} scaffold is selected. Configuration is "
            "present, but live wallet activity calls are disabled in this "
            "scaffold path; preview/run return limited coverage metadata only."
        ),
    }


def _wallet_activity_provider_key(settings: Settings) -> str:
    return (settings.wallet_activity_provider or WALLET_ACTIVITY_PROVIDER_MOCK).lower()


def _provider_scaffold_configured(provider_key: str, settings: Settings) -> bool:
    if provider_key == WALLET_ACTIVITY_PROVIDER_TONAPI:
        return TonapiAdapter(settings).is_configured()
    if provider_key == WALLET_ACTIVITY_PROVIDER_TON_PROVIDER:
        return TonProviderAdapter(settings).is_configured()
    if provider_key == WALLET_ACTIVITY_PROVIDER_STONFI:
        return StonfiAdapter(settings).is_configured()
    if provider_key == WALLET_ACTIVITY_PROVIDER_BITQUERY:
        return BitqueryAdapter(settings).is_configured()
    return False


def _utc_datetime(value: Any, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} must be a timezone-aware UTC datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be a timezone-aware UTC datetime.")
    return value.astimezone(timezone.utc)


def _resolved_transaction_bounds(
    request: WalletActivityAdapterRequest,
) -> tuple[datetime, datetime] | None:
    if request.resolved_start is None and request.resolved_end is None:
        return None
    if request.resolved_start is None or request.resolved_end is None:
        raise ValueError(
            "resolved_start and resolved_end must be supplied together."
        )
    start = _utc_datetime(request.resolved_start, "resolved_start")
    end = _utc_datetime(request.resolved_end, "resolved_end")
    if start >= end:
        raise ValueError("resolved_start must be earlier than resolved_end.")
    return start, end


def _event_query_dates(
    bounds: tuple[datetime, datetime] | None,
) -> tuple[int | None, int | None]:
    if bounds is None:
        return None, None
    return math.floor(bounds[0].timestamp()), math.ceil(bounds[1].timestamp())


def _utc_iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _stable_page_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _strict_logical_time(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if not value or not value.isascii() or not value.isdigit():
        return None
    if value[0] == "0" or len(value) > 20:
        return None
    if int(value, 10) > 2**64 - 1:
        return None
    return value


def _canonical_uint_string(value: Any) -> bool:
    if not isinstance(value, str) or not value.isascii():
        return False
    if value == "0":
        return True
    if (
        not value.isdigit()
        or value[0] == "0"
        or len(value) > 20
    ):
        return False
    return int(value, 10) <= 2**64 - 1


def _transaction_timestamp(value: Any) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        seconds = value
    elif isinstance(value, str) and value.isascii() and value.isdigit():
        seconds = int(value, 10)
    else:
        return None
    if seconds < 0:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def _legacy_transaction_page_data(value: Any, *, page_size: int) -> Any:
    if not isinstance(value, dict):
        return value
    rows = value.get("transactions")
    if not isinstance(rows, list):
        return value
    logical_times = [
        _strict_logical_time(row.get("logical_time"))
        if isinstance(row, dict)
        else None
        for row in rows
    ]
    valid_times = [item for item in logical_times if item is not None]
    min_logical_time = (
        str(min(int(item, 10) for item in valid_times))
        if len(valid_times) == len(rows) and rows
        else None
    )
    max_logical_time = (
        str(max(int(item, 10) for item in valid_times))
        if len(valid_times) == len(rows) and rows
        else None
    )
    return {
        "wallet_address": value.get("wallet_address"),
        "requested_limit": page_size,
        "request_before_lt": None,
        "raw_count": len(rows),
        "min_logical_time": min_logical_time,
        "max_logical_time": max_logical_time,
        "next_before_lt": min_logical_time,
        "transactions": rows,
    }


def _validate_transaction_page(
    value: Any,
    *,
    request_cursor: str | None,
    requested_limit: int,
    require_timestamps: bool,
) -> _ValidatedTransactionPage:
    if not isinstance(value, dict):
        raise ValueError("transaction page must be an object")
    if value.get("requested_limit") != requested_limit:
        raise ValueError("transaction page requested_limit does not match request")
    if value.get("request_before_lt") != request_cursor:
        raise ValueError("transaction page request cursor does not match request")

    rows = value.get("transactions")
    if not isinstance(rows, list):
        raise ValueError("transaction page transactions must be a list")
    raw_count = value.get("raw_count")
    if isinstance(raw_count, bool) or raw_count != len(rows):
        raise ValueError("transaction page raw_count does not match rows")
    if raw_count > requested_limit:
        raise ValueError("transaction page returned more rows than requested")

    logical_times: list[str] = []
    timestamps: list[datetime | None] = []
    prior_lt: int | None = None
    prior_timestamp: datetime | None = None
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"transaction page row {index} must be an object")
        tx_hash = row.get("tx_hash")
        if (
            not isinstance(tx_hash, str)
            or not tx_hash
            or tx_hash != tx_hash.strip()
        ):
            raise ValueError(
                f"transaction page row {index} has invalid transaction hash"
            )
        total_fees = row.get("total_fees")
        if total_fees is not None and not _canonical_uint_string(total_fees):
            raise ValueError(
                f"transaction page row {index} has invalid total fees"
            )
        logical_time = _strict_logical_time(row.get("logical_time"))
        if logical_time is None:
            raise ValueError(
                f"transaction page row {index} has invalid logical time"
            )
        logical_time_value = int(logical_time, 10)
        if prior_lt is not None and logical_time_value >= prior_lt:
            raise ValueError(
                "transaction page logical times must be strictly descending"
            )
        prior_lt = logical_time_value
        logical_times.append(logical_time)

        timestamp = _transaction_timestamp(row.get("utime"))
        if require_timestamps and timestamp is None:
            raise ValueError(
                f"transaction page row {index} has invalid timestamp"
            )
        if (
            require_timestamps
            and timestamp is not None
            and prior_timestamp is not None
            and timestamp > prior_timestamp
        ):
            raise ValueError(
                "transaction page timestamps must follow logical-time order"
            )
        if timestamp is not None:
            prior_timestamp = timestamp
        timestamps.append(timestamp)

    min_logical_time = (
        str(min(int(item, 10) for item in logical_times))
        if logical_times
        else None
    )
    max_logical_time = (
        str(max(int(item, 10) for item in logical_times))
        if logical_times
        else None
    )
    if value.get("min_logical_time") != min_logical_time:
        raise ValueError("transaction page minimum logical time is inconsistent")
    if value.get("max_logical_time") != max_logical_time:
        raise ValueError("transaction page maximum logical time is inconsistent")

    response_cursor = value.get("next_before_lt")
    if not logical_times:
        if response_cursor is not None:
            raise ValueError("empty transaction page must terminate its cursor")
    else:
        response_cursor = _strict_logical_time(response_cursor)
        if response_cursor != min_logical_time:
            raise ValueError(
                "transaction page response cursor must equal minimum logical time"
            )
        if (
            request_cursor is not None
            and int(response_cursor, 10) >= int(request_cursor, 10)
        ):
            raise ValueError("transaction page cursor did not advance")

    available_timestamps = [item for item in timestamps if item is not None]
    min_timestamp = (
        _utc_iso(min(available_timestamps)) if available_timestamps else None
    )
    max_timestamp = (
        _utc_iso(max(available_timestamps)) if available_timestamps else None
    )
    return _ValidatedTransactionPage(
        rows=rows,
        raw_count=raw_count,
        response_cursor=response_cursor,
        min_logical_time=min_logical_time,
        max_logical_time=max_logical_time,
        timestamps=timestamps,
        min_timestamp=min_timestamp,
        max_timestamp=max_timestamp,
        response_digest=_stable_page_digest(value),
    )


def _validate_event_page(
    value: Any,
    *,
    request_cursor: str | None,
    requested_limit: int,
) -> _ValidatedEventPage:
    if not isinstance(value, dict):
        raise ValueError("account event page must be an object")
    if value.get("requested_limit") != requested_limit:
        raise ValueError("account event page requested_limit does not match request")
    if value.get("request_before_lt") != request_cursor:
        raise ValueError("account event page request cursor does not match request")
    events = value.get("events")
    if not isinstance(events, list):
        raise ValueError("account event page events must be a list")
    raw_count = value.get("raw_count")
    if isinstance(raw_count, bool) or raw_count != len(events):
        raise ValueError("account event page raw_count does not match events")
    if raw_count > requested_limit:
        raise ValueError("account event page returned more rows than requested")

    logical_times: list[str] = []
    timestamps: list[datetime] = []
    prior_lt: int | None = None
    prior_timestamp: datetime | None = None
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise ValueError(f"account event page row {index} must be an object")
        event_id = event.get("event_id")
        if not _canonical_hex_256(event_id):
            raise ValueError(
                f"account event page row {index} has invalid event_id"
            )
        logical_time = _strict_logical_time(event.get("lt"))
        if logical_time is None:
            raise ValueError(
                f"account event page row {index} has invalid logical time"
            )
        logical_time_value = int(logical_time, 10)
        if prior_lt is not None and logical_time_value >= prior_lt:
            raise ValueError(
                "account event page logical times must be strictly descending"
            )
        timestamp = _transaction_timestamp(event.get("timestamp"))
        if timestamp is None:
            raise ValueError(
                f"account event page row {index} has invalid timestamp"
            )
        if prior_timestamp is not None and timestamp > prior_timestamp:
            raise ValueError(
                "account event page timestamps must follow logical-time order"
            )
        actions = event.get("actions")
        if not isinstance(actions, list) or any(
            not isinstance(action, dict)
            or not isinstance(action.get("type"), str)
            or not action["type"].strip()
            for action in actions
        ):
            raise ValueError(
                f"account event page row {index} has invalid actions"
            )
        if not isinstance(event.get("in_progress"), bool):
            raise ValueError(
                f"account event page row {index} has invalid in_progress state"
            )
        prior_lt = logical_time_value
        prior_timestamp = timestamp
        logical_times.append(logical_time)
        timestamps.append(timestamp)

    minimum_lt = (
        str(min(int(item, 10) for item in logical_times))
        if logical_times
        else None
    )
    maximum_lt = (
        str(max(int(item, 10) for item in logical_times))
        if logical_times
        else None
    )
    if value.get("min_logical_time") != minimum_lt:
        raise ValueError("account event page minimum logical time is inconsistent")
    if value.get("max_logical_time") != maximum_lt:
        raise ValueError("account event page maximum logical time is inconsistent")
    response_cursor = value.get("next_before_lt")
    if not events:
        if response_cursor is not None:
            raise ValueError("empty account event page must terminate its cursor")
    else:
        response_cursor = _strict_logical_time(response_cursor)
        if response_cursor != minimum_lt:
            raise ValueError(
                "account event page response cursor must equal minimum logical time"
            )
        if (
            request_cursor is not None
            and int(maximum_lt, 10) >= int(request_cursor, 10)
        ):
            raise ValueError("account event page cursor did not advance")
    return _ValidatedEventPage(
        events=events,
        raw_count=raw_count,
        response_cursor=response_cursor,
        min_logical_time=minimum_lt,
        max_logical_time=maximum_lt,
        timestamps=timestamps,
        min_timestamp=(_utc_iso(min(timestamps)) if timestamps else None),
        max_timestamp=(_utc_iso(max(timestamps)) if timestamps else None),
        response_digest=_stable_page_digest(value),
    )


def _canonical_hex_256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value == value.strip()
        and all(character in "0123456789abcdefABCDEF" for character in value)
    )


def _sanitize_provider_message(value: Any, settings: Settings) -> str:
    message = str(value or "Provider error.").strip() or "Provider error."
    api_key = getattr(settings, "tonapi_api_key", "")
    if api_key:
        message = message.replace(api_key, "[redacted]")
    return message[:500]


def _transaction_error_page_evidence(
    *,
    page_index: int,
    request_cursor: str | None,
    requested_limit: int,
    response: Any,
    error_code: str,
    error_message: str,
    fetched_at: str,
) -> WalletActivityAcquisitionPageEvidence:
    data = response if isinstance(response, dict) else {}
    raw_count = data.get("raw_count")
    if isinstance(raw_count, bool) or not isinstance(raw_count, int):
        raw_count = 0
    response_cursor = data.get("next_before_lt")
    if not isinstance(response_cursor, str):
        response_cursor = None
    return WalletActivityAcquisitionPageEvidence(
        page_index=page_index,
        request_cursor=request_cursor,
        response_cursor=response_cursor,
        requested_limit=requested_limit,
        raw_count=max(0, raw_count),
        normalized_count=0,
        duplicate_count=0,
        min_logical_time=(
            data.get("min_logical_time")
            if isinstance(data.get("min_logical_time"), str)
            else None
        ),
        max_logical_time=(
            data.get("max_logical_time")
            if isinstance(data.get("max_logical_time"), str)
            else None
        ),
        min_timestamp=None,
        max_timestamp=None,
        response_digest=_stable_page_digest(response),
        attempt_count=1,
        error_code=error_code,
        error_message=error_message,
        fetched_at=fetched_at,
    )


def _transaction_stream_evidence(
    *,
    request: WalletActivityAdapterRequest,
    page_size: int,
    page_cap: int,
    completion_state: str,
    termination_reason: str,
    pages: list[WalletActivityAcquisitionPageEvidence],
    raw_count: int,
    normalized_count: int,
    duplicate_count: int,
    terminal_cursor: str | None,
    bounds_verified: bool,
    started_at: str,
    finished_at: str,
    error_code: str | None,
    error_message: str | None,
    bounds: tuple[datetime, datetime] | None,
) -> WalletActivityAcquisitionStreamEvidence:
    requested_start = _utc_iso(bounds[0]) if bounds is not None else ""
    requested_end = _utc_iso(bounds[1]) if bounds is not None else ""
    return WalletActivityAcquisitionStreamEvidence(
        provider="tonapi",
        stream_key="transactions",
        contract_version=TONAPI_TRANSACTION_ACQUISITION_CONTRACT,
        scope_kind=("bounded_interval" if bounds is not None else "legacy_unavailable"),
        requested_start=requested_start,
        requested_end=requested_end,
        query_filters={
            "endpoint": "account_transactions",
            "cursor": "before_lt",
            "limit": page_size,
            "interval": "[resolved_start,resolved_end)",
            "bounds_available": bounds is not None,
        },
        sort_order="logical_time_desc",
        page_size=page_size,
        page_cap=page_cap,
        completion_state=completion_state,
        termination_reason=termination_reason,
        page_count=len(pages),
        raw_count=raw_count,
        normalized_count=normalized_count,
        duplicate_count=duplicate_count,
        first_cursor=pages[0].request_cursor if pages else None,
        terminal_cursor=terminal_cursor,
        bounds_verified=bounds_verified,
        started_at=started_at,
        finished_at=finished_at,
        error_code=error_code,
        error_message=error_message,
        pages=pages,
    )


def _event_stream_evidence(
    *,
    page_size: int,
    page_cap: int,
    completion_state: str,
    termination_reason: str,
    pages: list[WalletActivityAcquisitionPageEvidence],
    raw_count: int,
    normalized_count: int,
    duplicate_count: int,
    terminal_cursor: str | None,
    bounds_verified: bool,
    started_at: str,
    finished_at: str,
    error_code: str | None,
    error_message: str | None,
    bounds: tuple[datetime, datetime] | None,
) -> WalletActivityAcquisitionStreamEvidence:
    query_start, query_end = _event_query_dates(bounds)
    return WalletActivityAcquisitionStreamEvidence(
        provider="tonapi",
        stream_key="account_events",
        contract_version=TONAPI_EVENT_ACQUISITION_CONTRACT,
        scope_kind=(
            "provider_display_events"
            if bounds is not None
            else "legacy_unavailable"
        ),
        requested_start=_utc_iso(bounds[0]) if bounds is not None else "",
        requested_end=_utc_iso(bounds[1]) if bounds is not None else "",
        query_filters={
            "endpoint": "account_events",
            "cursor": "before_lt",
            "limit": page_size,
            "start_date": query_start,
            "end_date": query_end,
            "sort_order": "logical_time_desc",
            "provider_semantics": "display_only_actions",
        },
        sort_order="logical_time_desc",
        page_size=page_size,
        page_cap=page_cap,
        completion_state=completion_state,
        termination_reason=termination_reason,
        page_count=len(pages),
        raw_count=raw_count,
        normalized_count=normalized_count,
        duplicate_count=duplicate_count,
        first_cursor=pages[0].request_cursor if pages else None,
        terminal_cursor=terminal_cursor,
        bounds_verified=bounds_verified,
        started_at=started_at,
        finished_at=finished_at,
        error_code=error_code,
        error_message=error_message,
        pages=pages,
    )


def _tonapi_live_warnings(
    unavailable_surfaces: list[WalletIngestionSurface],
) -> list[str]:
    warnings = [
        (
            "Guarded live TonAPI wallet activity is enabled for native TON "
            "balance, account jetton balance snapshots, account transaction "
            "history, and a shared bounded account-event stream for derived "
            "TON/jetton transfer and DEX swap display actions."
        ),
        (
            "TonAPI event actions are mutable display-oriented interpretations. "
            "Transfer direction is best-effort, swaps exclude USD valuation, "
            "and derived actions are not authoritative history, PnL, clustering "
            "input, or ownership proof."
        ),
    ]
    if unavailable_surfaces:
        warnings.append(
            "Requested unsupported surfaces remain unavailable in the guarded "
            f"TonAPI live path: {', '.join(unavailable_surfaces)}."
        )
    return warnings


def _tonapi_live_transactions(
    rows: list[Any],
) -> list[WalletActivityTransaction]:
    return [
        _tonapi_live_transaction(item)
        for item in rows
        if isinstance(item, dict)
    ]


def _tonapi_live_transaction(item: dict[str, Any]) -> WalletActivityTransaction:
    success = item.get("success")
    if success is True:
        success_state: Literal["success", "failed", "unknown"] = "success"
    elif success is False:
        success_state = "failed"
    else:
        success_state = "unknown"
    fee_ton = _scaled_balance_string(item.get("total_fees"), 9)
    return WalletActivityTransaction(
        tx_hash=_optional_string(item.get("tx_hash")) or "",
        logical_time=_optional_string(item.get("logical_time")),
        timestamp=_utime_to_iso(item.get("utime")),
        fee_ton=fee_ton,
        success=success_state,
        provider="tonapi",
        source_status="live",
        raw={
            "provider": "tonapi",
            "surface": "transactions",
            "tx_hash": _optional_string(item.get("tx_hash")),
            "logical_time": _optional_string(item.get("logical_time")),
            "utime": item.get("utime"),
            "raw_total_fees": _optional_string(item.get("total_fees")),
            "normalized_fee_ton": fee_ton,
            "transaction_type": _optional_string(item.get("transaction_type")),
            "orig_status": _optional_string(item.get("orig_status")),
            "end_status": _optional_string(item.get("end_status")),
            "source": item.get("source"),
        },
    )


def _tonapi_live_transfers(
    rows: list[Any],
) -> list[WalletActivityTransfer]:
    return [
        _tonapi_live_transfer(item)
        for item in rows
        if isinstance(item, dict)
    ]


def _tonapi_live_transfer(item: dict[str, Any]) -> WalletActivityTransfer:
    direction = item.get("direction")
    if direction not in ("in", "out", "unknown"):
        direction = "unknown"
    amount = _scaled_balance_string(item.get("raw_amount"), item.get("decimals"))
    return WalletActivityTransfer(
        tx_hash=_optional_string(item.get("event_id")),
        logical_time=_optional_string(item.get("lt")),
        timestamp=_utime_to_iso(item.get("utime")),
        asset=_optional_string(item.get("asset")) or "UNKNOWN",
        amount=amount,
        direction=direction,
        counterparty=_optional_string(item.get("counterparty")),
        provider="tonapi",
        source_status="live",
        raw={
            "provider": "tonapi",
            "surface": "transfers",
            "event_id": _optional_string(item.get("event_id")),
            "action_type": _optional_string(item.get("action_type")),
            "action_index": item.get("action_index"),
            "lt": _optional_string(item.get("lt")),
            "utime": item.get("utime"),
            "raw_amount": _optional_string(item.get("raw_amount")),
            "normalized_amount": amount,
            "decimals": item.get("decimals"),
            "direction": direction,
            "sender": _optional_string(item.get("sender")),
            "recipient": _optional_string(item.get("recipient")),
            "counterparty": _optional_string(item.get("counterparty")),
            "jetton_address": _optional_string(item.get("jetton_address")),
            "jetton_symbol": _optional_string(item.get("jetton_symbol")),
            "status": _optional_string(item.get("status")),
            "source": item.get("source"),
        },
    )


def _tonapi_live_swaps(rows: list[Any]) -> list[WalletActivitySwap]:
    return [
        _tonapi_live_swap(item)
        for item in rows
        if isinstance(item, dict)
    ]


def _tonapi_live_swap(item: dict[str, Any]) -> WalletActivitySwap:
    amount_in = _scaled_balance_string(
        item.get("raw_amount_in"), item.get("decimals_in")
    )
    amount_out = _scaled_balance_string(
        item.get("raw_amount_out"), item.get("decimals_out")
    )
    return WalletActivitySwap(
        tx_hash=_optional_string(item.get("event_id")),
        timestamp=_utime_to_iso(item.get("utime")),
        dex=_optional_string(item.get("dex")),
        token_in=_optional_string(item.get("token_in")),
        amount_in=amount_in,
        token_out=_optional_string(item.get("token_out")),
        amount_out=amount_out,
        estimated_usd=None,
        provider="tonapi",
        source_status="live",
        raw={
            "provider": "tonapi",
            "surface": "swaps",
            "event_id": _optional_string(item.get("event_id")),
            "lt": _optional_string(item.get("lt")),
            "action_type": _optional_string(item.get("action_type")),
            "action_index": item.get("action_index"),
            "utime": item.get("utime"),
            "dex": _optional_string(item.get("dex")),
            "token_in": _optional_string(item.get("token_in")),
            "token_in_address": _optional_string(item.get("token_in_address")),
            "raw_amount_in": _optional_string(item.get("raw_amount_in")),
            "normalized_amount_in": amount_in,
            "decimals_in": item.get("decimals_in"),
            "token_out": _optional_string(item.get("token_out")),
            "token_out_address": _optional_string(item.get("token_out_address")),
            "raw_amount_out": _optional_string(item.get("raw_amount_out")),
            "normalized_amount_out": amount_out,
            "decimals_out": item.get("decimals_out"),
            "router": _optional_string(item.get("router")),
            "status": _optional_string(item.get("status")),
            "source": item.get("source"),
        },
    )


def _utime_to_iso(value: Any) -> str | None:
    seconds = _safe_int(value, -1)
    if seconds < 0:
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat()


def _tonapi_live_balance_snapshots(
    jettons: list[Any],
) -> list[WalletActivityBalanceSnapshot]:
    return [
        _tonapi_live_balance_snapshot(item)
        for item in jettons
        if isinstance(item, dict)
    ]


def _tonapi_live_native_balance_snapshot(
    item: dict[str, Any],
) -> WalletActivityBalanceSnapshot:
    balance = _scaled_balance_string(item.get("balance"), item.get("decimals", 9))
    return WalletActivityBalanceSnapshot(
        asset="TON",
        balance=balance,
        balance_usd=None,
        provider="tonapi",
        source_status="live",
        snapshot_at=_now_utc_iso(),
        raw={
            "provider": "tonapi",
            "surface": "balances",
            "asset": "TON",
            "raw_balance": _optional_string(item.get("balance")),
            "normalized_balance": balance,
            "normalized_balance_usd": None,
            "decimals": item.get("decimals", 9),
            "account_status": _optional_string(item.get("account_status")),
            "is_scam": item.get("is_scam"),
            "source": item.get("source"),
        },
    )


def _tonapi_live_balance_snapshot(item: dict[str, Any]) -> WalletActivityBalanceSnapshot:
    jetton_address = _optional_string(item.get("jetton_address"))
    symbol = _optional_string(item.get("jetton_symbol"))
    asset = symbol or jetton_address or "UNKNOWN_JETTON"
    balance = _scaled_balance_string(item.get("balance"), item.get("decimals"))
    price_usd = _optional_decimal(item.get("price_usd"))
    balance_decimal = _optional_decimal(balance)
    balance_usd = None
    if balance_decimal is not None and price_usd is not None:
        balance_usd = _fixed_decimal_string(balance_decimal * price_usd, USD_QUANT)

    return WalletActivityBalanceSnapshot(
        asset=asset,
        balance=balance,
        balance_usd=balance_usd,
        provider="tonapi",
        source_status="live",
        snapshot_at=_now_utc_iso(),
        raw={
            "provider": "tonapi",
            "surface": "jettons",
            "jetton_address": jetton_address,
            "jetton_name": _optional_string(item.get("jetton_name")),
            "jetton_symbol": symbol,
            "wallet_contract_address": _optional_string(
                item.get("wallet_contract_address")
            ),
            "price_usd": _optional_string(item.get("price_usd")),
            "raw_balance": _optional_string(item.get("balance")),
            "normalized_balance": balance,
            "normalized_balance_usd": balance_usd,
            "decimals": item.get("decimals"),
            "source": item.get("source"),
        },
    )


def _scaled_balance_string(value: Any, decimals: Any) -> str | None:
    raw = _optional_decimal(value)
    if raw is None:
        return None
    try:
        scale = int(decimals)
    except (TypeError, ValueError):
        return _fixed_decimal_string(raw, BALANCE_QUANT)
    if scale < 0:
        return _fixed_decimal_string(raw, BALANCE_QUANT)
    return _fixed_decimal_string(raw / (Decimal(10) ** scale), BALANCE_QUANT)


def _fixed_decimal_string(value: Decimal, quant: Decimal) -> str:
    digit_count = len(value.as_tuple().digits)
    decimal_places = abs(quant.as_tuple().exponent)
    with localcontext() as context:
        context.prec = max(60, digit_count + decimal_places + 4)
        return format(value.quantize(quant, rounding=ROUND_HALF_UP), "f")


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _now_utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _provider_evidence(
    surfaces: list[WalletIngestionSurface],
    warnings: list[str],
) -> WalletActivityProviderEvidence:
    count = sum(MOCK_SURFACE_COUNTS.get(surface, 0) for surface in surfaces)
    return WalletActivityProviderEvidence(
        provider=MOCK_WALLET_ACTIVITY_PROVIDER,
        data_mode=MOCK_DATA_MODE,
        source_status=MOCK_SOURCE_STATUS,
        warnings=warnings,
        freshness=MOCK_WALLET_ACTIVITY_FRESHNESS,
        raw_count=count,
        normalized_count=count,
    )


def _warnings_for_request(request: WalletActivityAdapterRequest) -> list[str]:
    warnings = list(MOCK_ACTIVITY_WARNINGS)
    if request.environment_data_mode == "real":
        warnings.append(
            "DATA_MODE=real is active, but wallet activity ingestion remains "
            "mock-normalized unless WALLET_ACTIVITY_PROVIDER selects a "
            "scaffold or the explicit TonAPI live guard."
        )
    if "jettons" in request.surfaces:
        warnings.append(MOCK_JETTON_SURFACE_WARNING)
    return warnings


def _warning_records(warnings: list[str]) -> list[WalletActivityWarning]:
    return _warning_records_for_provider(warnings, MOCK_WALLET_ACTIVITY_PROVIDER)


def _warning_records_for_provider(
    warnings: list[str],
    provider: str,
) -> list[WalletActivityWarning]:
    return [
        WalletActivityWarning(
            severity="warning" if index == 1 else "info",
            provider=provider,
            message=message,
            evidence_key=f"{provider}_{index}",
        )
        for index, message in enumerate(warnings, start=1)
    ]


def _transfers_for_request(
    request: WalletActivityAdapterRequest,
) -> list[WalletActivityTransfer]:
    if "transfers" not in request.surfaces:
        return []
    return [
        WalletActivityTransfer(
            tx_hash=item["tx_hash"],
            logical_time=item["logical_time"],
            timestamp=item["timestamp"],
            asset=item["asset"],
            amount=item["amount"],
            direction=item["direction"],
            counterparty=item["counterparty"],
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            source_status=MOCK_SOURCE_STATUS,
            raw=item["raw"],
        )
        for item in MOCK_TRANSFERS
    ]


def _transactions_for_request(
    request: WalletActivityAdapterRequest,
) -> list[WalletActivityTransaction]:
    if "transactions" not in request.surfaces:
        return []
    return [
        WalletActivityTransaction(
            tx_hash=item["tx_hash"],
            logical_time=item["logical_time"],
            timestamp=item["timestamp"],
            fee_ton=item["fee_ton"],
            success=item["success"],
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            source_status=MOCK_SOURCE_STATUS,
            raw=item["raw"],
        )
        for item in MOCK_TRANSACTIONS
    ]


def _swaps_for_request(
    request: WalletActivityAdapterRequest,
) -> list[WalletActivitySwap]:
    if "swaps" not in request.surfaces:
        return []
    return [
        WalletActivitySwap(
            tx_hash=item["tx_hash"],
            timestamp=item["timestamp"],
            dex=item["dex"],
            token_in=item["token_in"],
            amount_in=item["amount_in"],
            token_out=item["token_out"],
            amount_out=item["amount_out"],
            estimated_usd=item["estimated_usd"],
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            source_status=MOCK_SOURCE_STATUS,
            raw=item["raw"],
        )
        for item in MOCK_SWAPS
    ]


def _balances_for_request(
    request: WalletActivityAdapterRequest,
) -> list[WalletActivityBalanceSnapshot]:
    include_ton_balance = "balances" in request.surfaces
    include_jettons = "jettons" in request.surfaces
    rows = [
        item
        for item in MOCK_BALANCE_SNAPSHOTS
        if (item["asset"] == "TON" and include_ton_balance)
        or (item["asset"] != "TON" and include_jettons)
    ]
    return [
        WalletActivityBalanceSnapshot(
            asset=item["asset"],
            balance=item["balance"],
            balance_usd=item["balance_usd"],
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            source_status=MOCK_SOURCE_STATUS,
            snapshot_at=item["snapshot_at"],
            raw=item["raw"],
        )
        for item in rows
    ]
