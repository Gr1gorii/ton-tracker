"""Wallet activity ingestion orchestration service.

v0.11.4 routes wallet activity through an adapter interface. The active
adapter is still deterministic mock data; this service owns validation,
persistence, and public response conversion.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
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
from config import get_settings, tonapi_base_url_network
from services.pricing import price_assets
from services.ton_address_identity import (
    TonAddressIdentity,
    derive_ton_wallet_identity,
)
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
    _derive_request_wallet_identity(payload.wallet_address, settings)
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
    wallet_identity = _derive_request_wallet_identity(
        payload.wallet_address,
        settings,
    )
    adapter = build_wallet_activity_adapter(settings)
    result = adapter.ingest(_adapter_request(payload, settings))

    run = WalletIngestionRun(
        wallet_address=payload.wallet_address,
        wallet_identity_status=wallet_identity.status,
        wallet_identity_version=wallet_identity.version,
        wallet_network=wallet_identity.network,
        wallet_address_canonical=wallet_identity.canonical_address,
        wallet_workchain_id=wallet_identity.workchain_id,
        wallet_account_id_hex=wallet_identity.account_id_hex,
        wallet_address_format=wallet_identity.submitted_format,
        wallet_address_bounceable=wallet_identity.bounceable,
        wallet_address_testnet_only=wallet_identity.testnet_only,
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
                "adapter_contract": "wallet_activity_adapter_v0.12.0",
            }
        ),
    )

    priced_balances = _price_balances(result.balances, settings)
    run.transfers.extend(_transfer_models(result.transfers))
    run.transactions.extend(_transaction_models(result.transactions))
    run.swaps.extend(_swap_models(result.swaps))
    run.balance_snapshots.extend(_balance_snapshot_models(priced_balances))
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

    transfers = [_transfer_record(item) for item in run.transfers]
    transactions = [_transaction_record(item) for item in run.transactions]
    swaps = [_swap_record(item) for item in run.swaps]
    balances = [_balance_record(item) for item in run.balance_snapshots]

    return {
        "run_id": run.id,
        "wallet_address": run.wallet_address,
        "wallet_identity": _wallet_identity_record(run),
        "time_window": run.time_window,
        "status": run.status,
        "data_mode": run.data_mode,
        "requested_surfaces": requested_surfaces,
        "provider_evidence": evidence,
        "unavailable_surfaces": unavailable_surfaces,
        "transfers": transfers,
        "transactions": transactions,
        "swaps": swaps,
        "balances": balances,
        "warnings": [_warning_record(item) for item in run.warnings],
        "message": message,
        "activity_summary": _activity_summary(
            transfers, transactions, swaps, balances
        ),
    }


def _derive_request_wallet_identity(
    wallet_address: str,
    settings,
) -> TonAddressIdentity:
    network_context = (
        "ton-testnet" if settings.ton_network == "testnet" else "ton-mainnet"
    )
    identity = derive_ton_wallet_identity(
        wallet_address,
        network_context=network_context,
    )
    live_tonapi = (
        settings.is_real
        and settings.wallet_activity_provider == "tonapi"
        and settings.wallet_activity_live_enabled
    )
    if not live_tonapi:
        return identity
    if identity.status != "network_scoped":
        raise ValueError(
            "Live TonAPI ingestion requires a valid standard TON wallet address."
        )
    if identity.network != network_context:
        raise ValueError(
            "Wallet address network scope does not match TON_NETWORK."
        )
    if identity.workchain_id not in (-1, 0):
        raise ValueError(
            "Live TonAPI ingestion supports standard workchains -1 and 0 only."
        )
    provider_network = tonapi_base_url_network(settings.tonapi_base_url)
    if provider_network is not None and provider_network != settings.ton_network:
        raise ValueError(
            "Official TonAPI base URL network does not match TON_NETWORK."
        )
    return identity


def _wallet_identity_record(run: WalletIngestionRun) -> dict[str, Any]:
    return {
        "status": run.wallet_identity_status,
        "version": run.wallet_identity_version,
        "network": run.wallet_network,
        "canonical_address": run.wallet_address_canonical,
        "workchain_id": run.wallet_workchain_id,
        "account_id_hex": run.wallet_account_id_hex,
        "submitted_format": run.wallet_address_format,
        "bounceable": run.wallet_address_bounceable,
        "testnet_only": run.wallet_address_testnet_only,
        "is_account_existence_proof": False,
        "is_ownership_proof": False,
    }


_ZERO = Decimal(0)
_USD_QUANT = Decimal("0.00000001")


def _dec(value: Any) -> Decimal:
    if value is None or value == "":
        return _ZERO
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return _ZERO


def _price_balances(
    balances: list[WalletActivityBalanceSnapshot],
    settings,
) -> list[WalletActivityBalanceSnapshot]:
    """Fill missing ``balance_usd`` via the two-source pricing service.

    Real mode only. Uses provider-reported USD prices (TonAPI rates, then
    GeckoTerminal). Never overwrites a value the provider already set; assets
    neither source priced are left unpriced (no inferred value).
    """
    if not balances or not getattr(settings, "is_real", False):
        return balances
    if all(b.balance_usd is not None for b in balances):
        return balances

    specs = []
    for b in balances:
        raw = b.raw if isinstance(b.raw, dict) else {}
        token = "ton" if b.asset == "TON" else raw.get("jetton_address")
        specs.append({"asset": b.asset, "token": token})

    prices = price_assets(specs, settings).get("prices", [])

    enriched: list[WalletActivityBalanceSnapshot] = []
    for snapshot, price in zip(balances, prices):
        price_usd = price.get("price_usd") if isinstance(price, dict) else None
        if snapshot.balance_usd is None and price_usd and snapshot.balance:
            usd = (_dec(snapshot.balance) * _dec(price_usd)).quantize(
                _USD_QUANT, rounding=ROUND_HALF_UP
            )
            usd_str = format(usd, "f")
            raw = dict(snapshot.raw) if isinstance(snapshot.raw, dict) else {}
            raw["normalized_balance_usd"] = usd_str
            raw["priced_by"] = price.get("priced_by")
            enriched.append(replace(snapshot, balance_usd=usd_str, raw=raw))
        else:
            enriched.append(snapshot)
    return enriched


def _activity_summary(
    transfers: list[dict[str, Any]],
    transactions: list[dict[str, Any]],
    swaps: list[dict[str, Any]],
    balances: list[dict[str, Any]],
) -> dict[str, Any]:
    """Derived, read-only activity summary aggregated from ingested rows.

    Amounts are token quantities only. No pricing, cost basis, USD valuation,
    PnL, or clustering is inferred here.
    """
    transfer_assets: dict[str, dict[str, Any]] = {}
    for item in transfers:
        asset = item.get("asset") or "UNKNOWN"
        entry = transfer_assets.setdefault(
            asset,
            {
                "in_count": 0,
                "out_count": 0,
                "unknown_count": 0,
                "in_amount": _ZERO,
                "out_amount": _ZERO,
            },
        )
        amount = _dec(item.get("amount"))
        direction = item.get("direction")
        if direction == "in":
            entry["in_count"] += 1
            entry["in_amount"] += amount
        elif direction == "out":
            entry["out_count"] += 1
            entry["out_amount"] += amount
        else:
            entry["unknown_count"] += 1

    transfers_by_asset = [
        {
            "asset": asset,
            "in_count": e["in_count"],
            "out_count": e["out_count"],
            "unknown_count": e["unknown_count"],
            "in_amount": str(e["in_amount"]),
            "out_amount": str(e["out_amount"]),
            "net_amount": str(e["in_amount"] - e["out_amount"]),
        }
        for asset, e in sorted(transfer_assets.items())
    ]

    swap_dex: dict[str, int] = {}
    swap_tokens: dict[str, dict[str, Any]] = {}
    for item in swaps:
        dex = item.get("dex") or "unknown"
        swap_dex[dex] = swap_dex.get(dex, 0) + 1

        token_in = item.get("token_in")
        if token_in:
            entry = swap_tokens.setdefault(
                token_in,
                {"sent_count": 0, "received_count": 0,
                 "sent_amount": _ZERO, "received_amount": _ZERO},
            )
            entry["sent_count"] += 1
            entry["sent_amount"] += _dec(item.get("amount_in"))

        token_out = item.get("token_out")
        if token_out:
            entry = swap_tokens.setdefault(
                token_out,
                {"sent_count": 0, "received_count": 0,
                 "sent_amount": _ZERO, "received_amount": _ZERO},
            )
            entry["received_count"] += 1
            entry["received_amount"] += _dec(item.get("amount_out"))

    swaps_by_dex = [
        {"dex": dex, "count": count} for dex, count in sorted(swap_dex.items())
    ]
    swaps_by_token = [
        {
            "token": token,
            "sent_count": e["sent_count"],
            "received_count": e["received_count"],
            "sent_amount": str(e["sent_amount"]),
            "received_amount": str(e["received_amount"]),
        }
        for token, e in sorted(swap_tokens.items())
    ]

    total_fee = _ZERO
    for item in transactions:
        total_fee += _dec(item.get("fee_ton"))

    balance_assets = sorted(
        {item.get("asset") for item in balances if item.get("asset")}
    )

    total_balance_usd = _ZERO
    priced_assets = 0
    unpriced_assets = 0
    for item in balances:
        usd = item.get("balance_usd")
        if usd is None or usd == "":
            unpriced_assets += 1
        else:
            total_balance_usd += _dec(usd)
            priced_assets += 1

    return {
        "is_pnl": False,
        "note": (
            "Derived activity summary from ingested rows only. Amounts are "
            "token quantities, not USD. This is not PnL, cost basis, or "
            "valuation."
        ),
        "counts": {
            "transfers": len(transfers),
            "transactions": len(transactions),
            "swaps": len(swaps),
            "balances": len(balances),
        },
        "transfers_by_asset": transfers_by_asset,
        "swaps_by_dex": swaps_by_dex,
        "swaps_by_token": swaps_by_token,
        "transactions": {
            "count": len(transactions),
            "total_fee_ton": str(total_fee),
        },
        "balances": {
            "count": len(balances),
            "assets": balance_assets,
            "portfolio": {
                "total_balance_usd": (
                    str(total_balance_usd) if priced_assets else None
                ),
                "priced_assets": priced_assets,
                "unpriced_assets": unpriced_assets,
                "note": (
                    "USD totals use provider-reported prices for priced assets "
                    "only; unpriced assets (e.g. native TON, jettons without a "
                    "provider price) are excluded and prices may be stale."
                ),
            },
        },
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
    raw = _json_loads(item.raw_json)
    return {
        "tx_hash": item.tx_hash,
        "logical_time": item.logical_time,
        "timestamp": _isoformat(item.timestamp),
        "asset": item.asset,
        "amount": _balance_value_from_raw(raw, "normalized_amount")
        or _decimal_string(item.amount),
        "direction": item.direction,
        "counterparty": item.counterparty,
        "provider": item.provider,
        "source_status": item.source_status,
        "raw": raw,
    }


def _transaction_record(item: WalletTransaction) -> dict[str, Any]:
    raw = _json_loads(item.raw_json)
    return {
        "tx_hash": item.tx_hash,
        "logical_time": item.logical_time,
        "timestamp": _isoformat(item.timestamp),
        "fee_ton": _balance_value_from_raw(raw, "normalized_fee_ton")
        or _decimal_string(item.fee_ton),
        "success": item.success,
        "provider": item.provider,
        "source_status": item.source_status,
        "raw": raw,
    }


def _swap_record(item: WalletSwap) -> dict[str, Any]:
    raw = _json_loads(item.raw_json)
    raw_dict = raw if isinstance(raw, dict) else {}
    return {
        "tx_hash": item.tx_hash,
        "timestamp": _isoformat(item.timestamp),
        "dex": item.dex,
        "token_in": item.token_in,
        "token_in_address": raw_dict.get("token_in_address"),
        "amount_in": _balance_value_from_raw(raw, "normalized_amount_in")
        or _decimal_string(item.amount_in),
        "token_out": item.token_out,
        "token_out_address": raw_dict.get("token_out_address"),
        "amount_out": _balance_value_from_raw(raw, "normalized_amount_out")
        or _decimal_string(item.amount_out),
        "estimated_usd": _decimal_string(item.estimated_usd),
        "provider": item.provider,
        "source_status": item.source_status,
        "raw": raw,
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
