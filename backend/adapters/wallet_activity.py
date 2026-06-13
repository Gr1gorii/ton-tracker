"""Wallet activity ingestion adapter contracts and mock provider.

v0.11.4 introduces the adapter seam used by future real wallet activity
providers. The only executable adapter remains deterministic mock data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

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

MOCK_ACTIVITY_WARNINGS = [
    "Mock-normalized wallet activity ingestion uses deterministic fixtures only.",
    "No real transfers, swaps, balances, or transaction history are fetched in v0.11.4.",
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
                "No real provider calls are performed in v0.11.4."
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


def build_wallet_activity_adapter(_settings=None) -> WalletActivityAdapter:
    """Return the configured wallet activity adapter.

    v0.11.4 intentionally returns only the mock adapter. Future provider
    adapters should plug in here behind explicit configuration.
    """
    return MockWalletActivityAdapter()


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
            "mock-normalized in v0.11.4."
        )
    if "jettons" in request.surfaces:
        warnings.append(MOCK_JETTON_SURFACE_WARNING)
    return warnings


def _warning_records(warnings: list[str]) -> list[WalletActivityWarning]:
    return [
        WalletActivityWarning(
            severity="warning" if index == 1 else "info",
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            message=message,
            evidence_key=f"mock_wallet_activity_{index}",
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
