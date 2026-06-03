"""Bitquery preview API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from adapters.bitquery import BitqueryAdapter
from config import ProviderResult, get_settings
from schemas import (
    BitqueryTokenTradesPreviewRequest,
    BitqueryTokenTradesPreviewResponse,
)

router = APIRouter(prefix="/api/bitquery", tags=["bitquery"])


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
