"""Mock-normalized wallet activity ingestion service.

v0.11.2 proves the wallet activity schema with deterministic normalized rows.
It deliberately does not call real providers or feed legacy analytics.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from config import get_settings
from models import (
    WalletBalanceSnapshot,
    WalletIngestionRun,
    WalletIngestionWarning,
    WalletSwap,
    WalletTransaction,
    WalletTransfer,
)
from schemas import WalletIngestionPreviewRequest

MOCK_WALLET_ACTIVITY_PROVIDER = "mock_wallet_activity"
MOCK_WALLET_ACTIVITY_FRESHNESS = "2026-06-01T12:00:00Z"
MOCK_SOURCE_STATUS = "mock"

MOCK_ACTIVITY_WARNINGS = [
    "Mock-normalized wallet activity ingestion uses deterministic fixtures only.",
    "No real transfers, swaps, balances, or transaction history are fetched in v0.11.2.",
    "Legacy buyers, PnL, clustering, and exports are not wired to this ingestion run yet.",
]

MOCK_JETTON_SURFACE_WARNING = (
    "Jettons are represented as jetton balance snapshots until a dedicated "
    "jetton-activity table is introduced."
)

MOCK_SURFACE_COUNTS = {
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


def build_wallet_ingestion_preview(
    payload: WalletIngestionPreviewRequest,
    settings=None,
) -> dict[str, Any]:
    """Return deterministic coverage for a wallet ingestion request."""
    settings = settings or get_settings()
    _validate_window(payload)
    warnings = _warnings_for_surfaces(payload.surfaces, settings)
    evidence = _provider_evidence(payload.surfaces, warnings)

    return {
        "success": True,
        "wallet_address": payload.wallet_address,
        "time_window": payload.time_window,
        "requested_surfaces": payload.surfaces,
        "provider_coverage": [evidence],
        "unavailable_surfaces": [],
        "warnings": warnings,
        "message": (
            "Mock-normalized wallet activity coverage is available. "
            "No real provider calls are performed in v0.11.2."
        ),
    }


def persist_mock_wallet_ingestion(
    payload: WalletIngestionPreviewRequest,
    session: Session,
    settings=None,
) -> dict[str, Any]:
    """Persist one deterministic mock wallet ingestion run and return it."""
    settings = settings or get_settings()
    start, end = _validate_window(payload)
    warnings = _warnings_for_surfaces(payload.surfaces, settings)
    evidence = _provider_evidence(payload.surfaces, warnings)

    run = WalletIngestionRun(
        wallet_address=payload.wallet_address,
        time_window=payload.time_window,
        custom_start=start,
        custom_end=end,
        data_mode="mock",
        status="success",
        requested_surfaces_json=_json_dumps(payload.surfaces),
        provider_summary_json=_json_dumps(
            {
                "provider_evidence": [evidence],
                "unavailable_surfaces": [],
                "fixture_version": "v0.11.2",
            }
        ),
    )

    if "transfers" in payload.surfaces:
        run.transfers.extend(_transfer_models())
    if "transactions" in payload.surfaces:
        run.transactions.extend(_transaction_models())
    if "swaps" in payload.surfaces:
        run.swaps.extend(_swap_models())
    if "balances" in payload.surfaces or "jettons" in payload.surfaces:
        run.balance_snapshots.extend(_balance_snapshot_models(payload.surfaces))

    run.warnings.extend(_warning_models(warnings))

    session.add(run)
    session.commit()
    session.refresh(run)

    return wallet_ingestion_run_to_response(run)


def get_wallet_ingestion_run(run_id: int, session: Session) -> dict[str, Any] | None:
    """Return a persisted wallet ingestion run response, if present."""
    run = session.get(WalletIngestionRun, run_id)
    if run is None:
        return None
    return wallet_ingestion_run_to_response(run)


def wallet_ingestion_run_to_response(run: WalletIngestionRun) -> dict[str, Any]:
    """Convert a persisted wallet ingestion run into the public response shape."""
    provider_summary = _json_loads(run.provider_summary_json) or {}
    requested_surfaces = _json_loads(run.requested_surfaces_json) or []
    evidence = provider_summary.get("provider_evidence")
    if not isinstance(evidence, list):
        evidence = []

    return {
        "run_id": run.id,
        "wallet_address": run.wallet_address,
        "time_window": run.time_window,
        "status": run.status,
        "data_mode": "mock",
        "requested_surfaces": requested_surfaces,
        "provider_evidence": evidence,
        "transfers": [_transfer_record(item) for item in run.transfers],
        "transactions": [_transaction_record(item) for item in run.transactions],
        "swaps": [_swap_record(item) for item in run.swaps],
        "balances": [_balance_record(item) for item in run.balance_snapshots],
        "warnings": [_warning_record(item) for item in run.warnings],
        "message": (
            "Mock-normalized wallet activity ingestion run completed. "
            "The rows are deterministic fixtures and are not connected to "
            "legacy PnL or clustering yet."
        ),
    }


def _provider_evidence(
    surfaces: list[str],
    warnings: list[str],
) -> dict[str, Any]:
    count = sum(MOCK_SURFACE_COUNTS.get(surface, 0) for surface in surfaces)
    return {
        "provider": MOCK_WALLET_ACTIVITY_PROVIDER,
        "data_mode": "mock",
        "source_status": MOCK_SOURCE_STATUS,
        "warnings": warnings,
        "freshness": MOCK_WALLET_ACTIVITY_FRESHNESS,
        "raw_count": count,
        "normalized_count": count,
    }


def _warnings_for_surfaces(surfaces: list[str], settings) -> list[str]:
    warnings = list(MOCK_ACTIVITY_WARNINGS)
    if settings.data_mode == "real":
        warnings.append(
            "DATA_MODE=real is active, but wallet activity ingestion remains "
            "mock-normalized in v0.11.2."
        )
    if "jettons" in surfaces:
        warnings.append(MOCK_JETTON_SURFACE_WARNING)
    return warnings


def _validate_window(
    payload: WalletIngestionPreviewRequest,
) -> tuple[datetime | None, datetime | None]:
    start = _parse_datetime(payload.custom_start)
    end = _parse_datetime(payload.custom_end)
    if start and end and start >= end:
        raise ValueError("custom_end must be after custom_start")
    return start, end


def _parse_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        if cleaned.endswith("Z"):
            cleaned = f"{cleaned[:-1]}+00:00"
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError(f"Invalid ISO datetime: {value}") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _transfer_models() -> list[WalletTransfer]:
    return [
        WalletTransfer(
            tx_hash=item["tx_hash"],
            logical_time=item["logical_time"],
            timestamp=_parse_datetime(item["timestamp"]),
            asset=item["asset"],
            amount=_decimal(item["amount"]),
            direction=item["direction"],
            counterparty=item["counterparty"],
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            source_status=MOCK_SOURCE_STATUS,
            raw_json=_json_dumps(item["raw"]),
        )
        for item in MOCK_TRANSFERS
    ]


def _transaction_models() -> list[WalletTransaction]:
    return [
        WalletTransaction(
            tx_hash=item["tx_hash"],
            logical_time=item["logical_time"],
            timestamp=_parse_datetime(item["timestamp"]),
            fee_ton=_decimal(item["fee_ton"]),
            success=item["success"],
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            source_status=MOCK_SOURCE_STATUS,
            raw_json=_json_dumps(item["raw"]),
        )
        for item in MOCK_TRANSACTIONS
    ]


def _swap_models() -> list[WalletSwap]:
    return [
        WalletSwap(
            tx_hash=item["tx_hash"],
            timestamp=_parse_datetime(item["timestamp"]),
            dex=item["dex"],
            token_in=item["token_in"],
            amount_in=_decimal(item["amount_in"]),
            token_out=item["token_out"],
            amount_out=_decimal(item["amount_out"]),
            estimated_usd=_decimal(item["estimated_usd"]),
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            source_status=MOCK_SOURCE_STATUS,
            raw_json=_json_dumps(item["raw"]),
        )
        for item in MOCK_SWAPS
    ]


def _balance_snapshot_models(surfaces: list[str]) -> list[WalletBalanceSnapshot]:
    include_ton_balance = "balances" in surfaces
    include_jettons = "jettons" in surfaces
    rows = [
        item
        for item in MOCK_BALANCE_SNAPSHOTS
        if (item["asset"] == "TON" and include_ton_balance)
        or (item["asset"] != "TON" and include_jettons)
    ]
    return [
        WalletBalanceSnapshot(
            asset=item["asset"],
            balance=_decimal(item["balance"]),
            balance_usd=_decimal(item["balance_usd"]),
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            source_status=MOCK_SOURCE_STATUS,
            snapshot_at=_parse_datetime(item["snapshot_at"]),
            raw_json=_json_dumps(item["raw"]),
        )
        for item in rows
    ]


def _warning_models(warnings: list[str]) -> list[WalletIngestionWarning]:
    return [
        WalletIngestionWarning(
            severity="warning" if index == 1 else "info",
            provider=MOCK_WALLET_ACTIVITY_PROVIDER,
            message=message,
            evidence_key=f"mock_wallet_activity_{index}",
        )
        for index, message in enumerate(warnings, start=1)
    ]


def _transfer_record(item: WalletTransfer) -> dict[str, Any]:
    return {
        "tx_hash": item.tx_hash,
        "logical_time": item.logical_time,
        "timestamp": _isoformat(item.timestamp),
        "asset": item.asset,
        "amount": _decimal_string(item.amount),
        "direction": item.direction,
        "counterparty": item.counterparty,
        "provider": item.provider,
        "source_status": item.source_status,
        "raw": _json_loads(item.raw_json),
    }


def _transaction_record(item: WalletTransaction) -> dict[str, Any]:
    return {
        "tx_hash": item.tx_hash,
        "logical_time": item.logical_time,
        "timestamp": _isoformat(item.timestamp),
        "fee_ton": _decimal_string(item.fee_ton),
        "success": item.success,
        "provider": item.provider,
        "source_status": item.source_status,
        "raw": _json_loads(item.raw_json),
    }


def _swap_record(item: WalletSwap) -> dict[str, Any]:
    return {
        "tx_hash": item.tx_hash,
        "timestamp": _isoformat(item.timestamp),
        "dex": item.dex,
        "token_in": item.token_in,
        "amount_in": _decimal_string(item.amount_in),
        "token_out": item.token_out,
        "amount_out": _decimal_string(item.amount_out),
        "estimated_usd": _decimal_string(item.estimated_usd),
        "provider": item.provider,
        "source_status": item.source_status,
        "raw": _json_loads(item.raw_json),
    }


def _balance_record(item: WalletBalanceSnapshot) -> dict[str, Any]:
    return {
        "asset": item.asset,
        "balance": _decimal_string(item.balance),
        "balance_usd": _decimal_string(item.balance_usd),
        "provider": item.provider,
        "source_status": item.source_status,
        "snapshot_at": _isoformat(item.snapshot_at),
        "raw": _json_loads(item.raw_json),
    }


def _warning_record(item: WalletIngestionWarning) -> dict[str, Any]:
    return {
        "severity": item.severity,
        "provider": item.provider,
        "message": item.message,
        "evidence_key": item.evidence_key,
    }


def _decimal(value: str | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


def _decimal_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {"unparsed": value}
