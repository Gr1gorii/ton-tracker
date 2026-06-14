"""Wallet activity ingestion adapter contracts, mock provider, and scaffolds.

v0.11.5 keeps deterministic mock data as the default executable adapter and
adds provider-specific scaffold adapters behind explicit configuration. The
scaffolds expose status and coverage limits only; they do not perform real
wallet activity provider calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    "No real transfers, swaps, balances, or transaction history are fetched in v0.11.5.",
    "Legacy buyers, PnL, clustering, and exports are not wired to this ingestion run yet.",
]

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
        "raw": {"fixture": "swap", "surface": "swaps", "index": 1},
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
                "No real provider calls are performed in v0.11.5."
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
                "v0.11.5."
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
                "in v0.11.5; they expose status and coverage limits but do not "
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

    return {
        "configured": True,
        "available": False,
        "message": (
            f"Real mode: {spec.label} scaffold is selected. Configuration is "
            "present, but live wallet activity calls are disabled in v0.11.5; "
            "preview/run return limited coverage metadata only."
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
            "v0.11.5 scaffold."
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
