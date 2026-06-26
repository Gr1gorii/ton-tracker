"""Wallet activity ingestion orchestration service.

v0.11.4 routes wallet activity through an adapter interface. The active
adapter is still deterministic mock data; this service owns validation,
persistence, and public response conversion.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from adapters.wallet_activity import (
    WalletActivityAdapterRequest,
    WalletActivityAdapterResult,
    WalletActivityBalanceSnapshot,
    WalletActivitySwap,
    WalletActivityTransaction,
    WalletActivityTransfer,
    WalletActivityWarning,
    build_wallet_activity_adapter,
)
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


def build_wallet_ingestion_preview(
    payload: WalletIngestionPreviewRequest,
    settings=None,
) -> dict[str, Any]:
    """Return adapter coverage for a wallet ingestion request."""
    settings = settings or get_settings()
    _validate_window(payload)
    adapter = build_wallet_activity_adapter(settings)
    result = adapter.preview(_adapter_request(payload, settings))

    return {
        "success": result.status in ("success", "partial"),
        "wallet_address": payload.wallet_address,
        "time_window": payload.time_window,
        "requested_surfaces": result.requested_surfaces,
        "provider_coverage": _provider_evidence(result),
        "unavailable_surfaces": result.unavailable_surfaces,
        "warnings": result.warning_messages,
        "message": result.message,
    }


def persist_mock_wallet_ingestion(
    payload: WalletIngestionPreviewRequest,
    session: Session,
    settings=None,
) -> dict[str, Any]:
    """Persist one adapter-backed mock wallet ingestion run and return it."""
    settings = settings or get_settings()
    start, end = _validate_window(payload)
    adapter = build_wallet_activity_adapter(settings)
    result = adapter.ingest(_adapter_request(payload, settings))

    run = WalletIngestionRun(
        wallet_address=payload.wallet_address,
        time_window=payload.time_window,
        custom_start=start,
        custom_end=end,
        data_mode=result.data_mode,
        status=result.status,
        requested_surfaces_json=_json_dumps(result.requested_surfaces),
        provider_summary_json=_json_dumps(
            {
                "provider_evidence": _provider_evidence(result),
                "unavailable_surfaces": result.unavailable_surfaces,
                "message": result.message,
                "adapter_contract": "wallet_activity_adapter_v0.11.8",
            }
        ),
    )

    run.transfers.extend(_transfer_models(result.transfers))
    run.transactions.extend(_transaction_models(result.transactions))
    run.swaps.extend(_swap_models(result.swaps))
    run.balance_snapshots.extend(_balance_snapshot_models(result.balances))
    run.warnings.extend(_warning_models(result.warnings))

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
    unavailable_surfaces = provider_summary.get("unavailable_surfaces")
    if not isinstance(unavailable_surfaces, list):
        unavailable_surfaces = []
    message = provider_summary.get("message")
    if not isinstance(message, str) or not message:
        message = (
            "Mock-normalized wallet activity ingestion run completed. "
            "The rows are deterministic fixtures and are not connected to "
            "legacy PnL or clustering yet."
        )

    return {
        "run_id": run.id,
        "wallet_address": run.wallet_address,
        "time_window": run.time_window,
        "status": run.status,
        "data_mode": run.data_mode,
        "requested_surfaces": requested_surfaces,
        "provider_evidence": evidence,
        "unavailable_surfaces": unavailable_surfaces,
        "transfers": [_transfer_record(item) for item in run.transfers],
        "transactions": [_transaction_record(item) for item in run.transactions],
        "swaps": [_swap_record(item) for item in run.swaps],
        "balances": [_balance_record(item) for item in run.balance_snapshots],
        "warnings": [_warning_record(item) for item in run.warnings],
        "message": message,
    }


def _adapter_request(
    payload: WalletIngestionPreviewRequest,
    settings,
) -> WalletActivityAdapterRequest:
    return WalletActivityAdapterRequest(
        wallet_address=payload.wallet_address,
        time_window=payload.time_window,
        custom_start=payload.custom_start,
        custom_end=payload.custom_end,
        surfaces=payload.surfaces,
        environment_data_mode=settings.data_mode,
    )


def _provider_evidence(result: WalletActivityAdapterResult) -> list[dict[str, Any]]:
    return [item.to_public_dict() for item in result.provider_evidence]


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


def _transfer_models(
    transfers: list[WalletActivityTransfer],
) -> list[WalletTransfer]:
    return [
        WalletTransfer(
            tx_hash=item.tx_hash,
            logical_time=item.logical_time,
            timestamp=_parse_datetime(item.timestamp),
            asset=item.asset,
            amount=_decimal(item.amount),
            direction=item.direction,
            counterparty=item.counterparty,
            provider=item.provider,
            source_status=item.source_status,
            raw_json=_json_dumps(item.raw),
        )
        for item in transfers
    ]


def _transaction_models(
    transactions: list[WalletActivityTransaction],
) -> list[WalletTransaction]:
    return [
        WalletTransaction(
            tx_hash=item.tx_hash,
            logical_time=item.logical_time,
            timestamp=_parse_datetime(item.timestamp),
            fee_ton=_decimal(item.fee_ton),
            success=item.success,
            provider=item.provider,
            source_status=item.source_status,
            raw_json=_json_dumps(item.raw),
        )
        for item in transactions
    ]


def _swap_models(swaps: list[WalletActivitySwap]) -> list[WalletSwap]:
    return [
        WalletSwap(
            tx_hash=item.tx_hash,
            timestamp=_parse_datetime(item.timestamp),
            dex=item.dex,
            token_in=item.token_in,
            amount_in=_decimal(item.amount_in),
            token_out=item.token_out,
            amount_out=_decimal(item.amount_out),
            estimated_usd=_decimal(item.estimated_usd),
            provider=item.provider,
            source_status=item.source_status,
            raw_json=_json_dumps(item.raw),
        )
        for item in swaps
    ]


def _balance_snapshot_models(
    balances: list[WalletActivityBalanceSnapshot],
) -> list[WalletBalanceSnapshot]:
    return [
        WalletBalanceSnapshot(
            asset=item.asset,
            balance=_decimal(item.balance),
            balance_usd=_decimal(item.balance_usd),
            provider=item.provider,
            source_status=item.source_status,
            snapshot_at=_parse_datetime(item.snapshot_at),
            raw_json=_json_dumps(item.raw),
        )
        for item in balances
    ]


def _warning_models(
    warnings: list[WalletActivityWarning],
) -> list[WalletIngestionWarning]:
    return [
        WalletIngestionWarning(
            severity=item.severity,
            provider=item.provider,
            message=item.message,
            evidence_key=item.evidence_key,
        )
        for item in warnings
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
    raw = _json_loads(item.raw_json)
    return {
        "asset": item.asset,
        "balance": _balance_value_from_raw(raw, "normalized_balance")
        or _decimal_string(item.balance),
        "balance_usd": _balance_value_from_raw(raw, "normalized_balance_usd")
        or _decimal_string(item.balance_usd),
        "provider": item.provider,
        "source_status": item.source_status,
        "snapshot_at": _isoformat(item.snapshot_at),
        "raw": raw,
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


def _balance_value_from_raw(raw: Any, key: str) -> str | None:
    if not isinstance(raw, dict):
        return None
    value = raw.get(key)
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


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
