"""Wallet activity ingestion adapter contracts, mock provider, and live guards.

Deterministic mock data remains the default executable adapter. Provider-
specific scaffold adapters stay behind explicit configuration, while the
guarded TonAPI live path covers native TON balance snapshots, account jetton
balance snapshots, ordered transaction history, TON/jetton transfers, and DEX
swaps parsed from account events.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from typing import Any, Literal, Protocol

from adapters.bitquery import BitqueryAdapter
from adapters.stonfi import StonfiAdapter
from adapters.ton_provider import TonProviderAdapter
from adapters.tonapi import TonapiAdapter
from config import Settings, get_settings

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
class WalletActivityAdapterResult:
    status: WalletIngestionStatus
    data_mode: WalletDataMode
    requested_surfaces: list[WalletIngestionSurface]
    provider_evidence: list[WalletActivityProviderEvidence]
    unavailable_surfaces: list[WalletIngestionSurface]
    warnings: list[WalletActivityWarning]
    message: str
    transfers: list[WalletActivityTransfer] = field(default_factory=list)
    transactions: list[WalletActivityTransaction] = field(default_factory=list)
    swaps: list[WalletActivitySwap] = field(default_factory=list)
    balances: list[WalletActivityBalanceSnapshot] = field(default_factory=list)

    @property
    def warning_messages(self) -> list[str]:
        return [warning.message for warning in self.warnings]


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
            result = self.tonapi.get_account_transactions_preview(
                request.wallet_address,
                limit=self.settings.wallet_activity_live_tx_limit,
            )
            if not result.ok:
                message = (
                    result.message
                    or "TonAPI live transaction-history request failed."
                )
                warnings.append(f"TonAPI transaction-history warning: {message}")
                unavailable_surfaces.append("transactions")
                failed_supported_surfaces.append("transactions")
            else:
                data = result.data if isinstance(result.data, dict) else {}
                tx_rows = (
                    data.get("transactions")
                    if isinstance(data.get("transactions"), list)
                    else []
                )
                total_tx = _safe_int(
                    data.get("total_transactions"), len(tx_rows)
                )
                preview_count = _safe_int(data.get("preview_count"), len(tx_rows))
                raw_count += total_tx
                successful_supported_surfaces.append("transactions")
                if total_tx > preview_count:
                    warnings.append(
                        f"TonAPI returned {preview_count} of {total_tx} "
                        "transactions within WALLET_ACTIVITY_LIVE_TX_LIMIT."
                    )
                if total_tx == 0:
                    warnings.append(
                        "TonAPI returned zero transactions for this guarded "
                        "fetch. This is not evidence that the wallet has no "
                        "activity."
                    )
                if mode == "ingest":
                    transactions.extend(_tonapi_live_transactions(tx_rows))

        if "transfers" in requested_surfaces:
            result = self.tonapi.get_account_events_preview(
                request.wallet_address,
                limit=self.settings.wallet_activity_live_transfer_limit,
            )
            if not result.ok:
                message = (
                    result.message
                    or "TonAPI live transfer-history request failed."
                )
                warnings.append(f"TonAPI transfer-history warning: {message}")
                unavailable_surfaces.append("transfers")
                failed_supported_surfaces.append("transfers")
            else:
                data = result.data if isinstance(result.data, dict) else {}
                transfer_rows = (
                    data.get("transfers")
                    if isinstance(data.get("transfers"), list)
                    else []
                )
                total_transfers = _safe_int(
                    data.get("total_transfers"), len(transfer_rows)
                )
                total_events = _safe_int(data.get("total_events"), 0)
                raw_count += total_transfers
                successful_supported_surfaces.append("transfers")
                warnings.append(
                    "TonAPI transfer history is derived from account events: "
                    "only TON and jetton transfer actions are represented, and "
                    "direction is best-effort from event addresses. Swaps, NFT, "
                    "and contract-call actions are not transfers."
                )
                if total_events and total_transfers == 0:
                    warnings.append(
                        "TonAPI returned events but no TON/jetton transfer "
                        "actions for this guarded fetch. This is not evidence "
                        "of no activity."
                    )
                if total_events == 0:
                    warnings.append(
                        "TonAPI returned zero events for this guarded fetch. "
                        "This is not evidence that the wallet has no activity."
                    )
                if mode == "ingest":
                    transfers.extend(_tonapi_live_transfers(transfer_rows))

        if "swaps" in requested_surfaces:
            result = self.tonapi.get_account_swaps_preview(
                request.wallet_address,
                limit=self.settings.wallet_activity_live_swap_limit,
            )
            if not result.ok:
                message = (
                    result.message or "TonAPI live DEX swap request failed."
                )
                warnings.append(f"TonAPI DEX swap warning: {message}")
                unavailable_surfaces.append("swaps")
                failed_supported_surfaces.append("swaps")
            else:
                data = result.data if isinstance(result.data, dict) else {}
                swap_rows = (
                    data.get("swaps")
                    if isinstance(data.get("swaps"), list)
                    else []
                )
                total_swaps = _safe_int(data.get("total_swaps"), len(swap_rows))
                total_events = _safe_int(data.get("total_events"), 0)
                raw_count += total_swaps
                successful_supported_surfaces.append("swaps")
                warnings.append(
                    "TonAPI DEX swaps are parsed from account events "
                    "(JettonSwap actions) and exclude USD valuation. They are "
                    "not PnL, ownership proof, or full DEX trade history."
                )
                if total_events and total_swaps == 0:
                    warnings.append(
                        "TonAPI returned events but no JettonSwap actions for "
                        "this guarded fetch. This is not evidence of no "
                        "activity."
                    )
                if mode == "ingest":
                    swaps.extend(_tonapi_live_swaps(swap_rows))

        unavailable_surfaces = list(dict.fromkeys(unavailable_surfaces))
        if failed_supported_surfaces and not successful_supported_surfaces:
            status: WalletIngestionStatus = "error"
            source_status: WalletSourceStatus = "error"
            message = (
                "Guarded TonAPI live adapter could not fetch the requested "
                "balance, transaction-history, transfer, or swap data. No live "
                "wallet activity rows were persisted."
            )
        else:
            status = "partial" if unavailable_surfaces else "success"
            source_status = "limited" if failed_supported_surfaces else "live"
            message = (
                "Guarded TonAPI live activity fetched. Scope is native TON "
                "balance, account jetton balances, account transaction "
                "history, TON/jetton transfer history, and DEX swaps from "
                "events only. Persisted rows can feed run-scoped signals, "
                "evidence-gated PnL, and probabilistic clustering."
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
    ) -> WalletActivityAdapterResult:
        transactions = transactions or []
        transfers = transfers or []
        swaps = swaps or []
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
                "transaction history, TON/jetton transfers, and DEX swaps from "
                "events can be fetched. Persisted rows can feed run-scoped "
                "signals, evidence-gated PnL, and probabilistic clustering."
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


def _tonapi_live_warnings(
    unavailable_surfaces: list[WalletIngestionSurface],
) -> list[str]:
    warnings = [
        (
            "Guarded live TonAPI wallet activity is enabled for native TON "
            "balance, account jetton balance snapshots, account transaction "
            "history, TON/jetton transfers, and DEX swaps from events only."
        ),
        (
            "Live TonAPI data is account-level evidence. Transfer direction is "
            "best-effort from event addresses, swaps exclude USD valuation, and "
            "it is not PnL, clustering input, or ownership proof."
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
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


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
