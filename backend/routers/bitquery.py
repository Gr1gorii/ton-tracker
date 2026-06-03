"""Bitquery preview API routes."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter

from adapters.bitquery import BitqueryAdapter
from config import ProviderResult, get_settings
from schemas import (
    BitqueryTokenTradesAnalysisResponse,
    BitqueryTokenTradesPreviewRequest,
    BitqueryTokenTradesPreviewResponse,
)
from services.import_analysis import analyze_imported_trades

router = APIRouter(prefix="/api/bitquery", tags=["bitquery"])

BITQUERY_ANALYSIS_NOTE = (
    "Bitquery token trade analysis is based only on fetched DEX trades. It "
    "does not fetch wallet balances, current holdings, or full on-chain "
    "history."
)


@router.post(
    "/token-trades/preview",
    response_model=BitqueryTokenTradesPreviewResponse,
)
def preview_token_trades(
    payload: BitqueryTokenTradesPreviewRequest,
) -> dict[str, Any]:
    """Fetch Bitquery token trades through the adapter and return a preview."""
    settings = get_settings()
    adapter = BitqueryAdapter(settings)
    result = adapter.get_token_trades(
        payload.token_address,
        payload.start,
        payload.end,
    )

    if not result.ok:
        return _error_response(settings.data_mode, result)

    trades = result.data or []
    preview = trades[: payload.preview_limit]
    return {
        "provider": "bitquery",
        "data_mode": settings.data_mode,
        "success": True,
        "summary": {
            "total_trades": len(trades),
            "preview_count": len(preview),
        },
        "trades_preview": preview,
        "warnings": [],
        "error": None,
    }


@router.post(
    "/token-trades/analyze",
    response_model=BitqueryTokenTradesAnalysisResponse,
)
def analyze_token_trades(
    payload: BitqueryTokenTradesPreviewRequest,
) -> dict[str, Any]:
    """Fetch Bitquery token trades and run imported-trade wallet analysis."""
    settings = get_settings()
    adapter = BitqueryAdapter(settings)
    result = adapter.get_token_trades(
        payload.token_address,
        payload.start,
        payload.end,
    )

    if not result.ok:
        return _analysis_error_response(settings.data_mode, result,
                                        payload.preview_limit)

    try:
        parsed = _parsed_bitquery_trades(result.data or [], payload.start)
    except ValueError as exc:
        error = ProviderResult.failure(
            "provider_error",
            f"Bitquery analysis error: {exc}",
            source=result.source,
        )
        return _analysis_error_response(settings.data_mode, error,
                                        payload.preview_limit)

    analysis = analyze_imported_trades(
        parsed=parsed,
        preview_limit=payload.preview_limit,
        source="bitquery",
    )
    source_summary = analysis["summary"]
    return {
        "provider": "bitquery",
        "data_mode": settings.data_mode,
        "success": True,
        "summary": {
            "total_trades": len(parsed["trades"]),
            "valid_rows": source_summary["valid_rows"],
            "wallets_count": source_summary["wallets_count"],
            "buy_trades_count": source_summary["buy_trades_count"],
            "sell_trades_count": source_summary["sell_trades_count"],
            "errors": source_summary["errors"],
        },
        "wallets": analysis["wallets"],
        "trades_preview": analysis["trades_preview"],
        "preview_limit": payload.preview_limit,
        "has_more_wallets": analysis["has_more_wallets"],
        "warnings": [],
        "error": None,
        "analysis_note": BITQUERY_ANALYSIS_NOTE,
    }


def _error_response(data_mode: str, result: ProviderResult) -> dict[str, Any]:
    message = result.message or "Bitquery provider returned an error."
    warning = f"Bitquery provider warning: {message}"
    return {
        "provider": "bitquery",
        "data_mode": data_mode,
        "success": False,
        "summary": {
            "total_trades": 0,
            "preview_count": 0,
        },
        "trades_preview": [],
        "warnings": [warning],
        "error": {
            "code": result.error,
            "message": message,
        },
    }


def _analysis_error_response(
    data_mode: str,
    result: ProviderResult,
    preview_limit: int,
) -> dict[str, Any]:
    message = result.message or "Bitquery provider returned an error."
    warning = f"Bitquery provider warning: {message}"
    return {
        "provider": "bitquery",
        "data_mode": data_mode,
        "success": False,
        "summary": {
            "total_trades": 0,
            "valid_rows": 0,
            "wallets_count": 0,
            "buy_trades_count": 0,
            "sell_trades_count": 0,
            "errors": [],
        },
        "wallets": [],
        "trades_preview": [],
        "preview_limit": preview_limit,
        "has_more_wallets": False,
        "warnings": [warning],
        "error": {
            "code": result.error,
            "message": message,
        },
        "analysis_note": BITQUERY_ANALYSIS_NOTE,
    }


def _parsed_bitquery_trades(trades: Any, fallback_block_time: str) -> dict[str, Any]:
    if not isinstance(trades, list):
        raise ValueError("Bitquery trades must be a list")

    normalized = [
        _analysis_trade(trade, index, fallback_block_time)
        for index, trade in enumerate(trades, start=1)
    ]
    return {
        "trades": normalized,
        "summary": {
            "total_rows": len(normalized),
            "valid_rows": len(normalized),
            "invalid_rows": 0,
            "duplicate_rows": 0,
            "errors": [],
        },
    }


def _analysis_trade(
    trade: Any,
    index: int,
    fallback_block_time: str,
) -> dict[str, Any]:
    if not isinstance(trade, dict):
        raise ValueError(f"trade {index} must be an object")

    is_legacy_mock = "wallet_address" in trade or "base_amount" in trade
    tx_hash = (
        _optional_string(trade.get("tx_hash"))
        or _optional_string(trade.get("transaction_hash"))
    )
    block_time = (
        _optional_string(trade.get("block_time"))
        or _optional_string(trade.get("timestamp"))
    )
    if tx_hash is None:
        if not is_legacy_mock:
            raise ValueError(f"trade {index} is missing tx_hash")
        tx_hash = f"mock-bitquery-{index}"
    if block_time is None:
        if not is_legacy_mock:
            raise ValueError(f"trade {index} is missing block_time")
        block_time = fallback_block_time

    return {
        "tx_hash": tx_hash,
        "block_time": block_time,
        "wallet": (
            _optional_string(trade.get("wallet"))
            or _required_string(trade, "wallet_address", index)
        ),
        "side": _required_side(trade, index),
        "token_amount": _required_decimal(
            trade,
            ("token_amount", "base_amount"),
            "token_amount",
            index,
        ),
        "usd_amount": _required_decimal(
            trade,
            ("usd_amount", "amount_usd"),
            "usd_amount",
            index,
        ),
        "price_usd": _optional_decimal(trade, "price_usd", index),
        "pool_address": _optional_string(trade.get("pool_address")),
        "dex": _optional_string(trade.get("dex")),
        "source": "bitquery",
    }


def _required_side(trade: dict[str, Any], index: int) -> str:
    side = _required_string(trade, "side", index).lower()
    if side not in ("buy", "sell"):
        raise ValueError(f"trade {index} has invalid side")
    return side


def _required_string(trade: dict[str, Any], field: str, index: int) -> str:
    value = _optional_string(trade.get(field))
    if value is None:
        raise ValueError(f"trade {index} is missing {field}")
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _required_decimal(
    trade: dict[str, Any],
    fields: tuple[str, ...],
    label: str,
    index: int,
) -> Decimal:
    for field in fields:
        value = trade.get(field)
        if _optional_string(value) is not None:
            return _decimal(value, label, index)
    raise ValueError(f"trade {index} is missing {label}")


def _optional_decimal(
    trade: dict[str, Any],
    field: str,
    index: int,
) -> Decimal | None:
    value = trade.get(field)
    if _optional_string(value) is None:
        return None
    return _decimal(value, field, index)


def _decimal(value: Any, field: str, index: int) -> Decimal:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise ValueError(f"trade {index} has invalid {field}") from None
    if not parsed.is_finite():
        raise ValueError(f"trade {index} has invalid {field}")
    return parsed
