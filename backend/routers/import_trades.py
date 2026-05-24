"""Imported trade preview API routes."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, HTTPException

from schemas import ImportTradesPreviewRequest, ImportTradesPreviewResponse
from services.import_parser import parse_csv_trades, parse_json_trades

router = APIRouter(prefix="/api/import/trades", tags=["trade-import"])


@router.post("/preview", response_model=ImportTradesPreviewResponse)
def preview_imported_trades(payload: ImportTradesPreviewRequest) -> dict[str, Any]:
    """Parse imported trades and return validation summary plus preview rows."""
    source = f"imported_{payload.format}"

    if payload.format == "csv":
        if not isinstance(payload.content, str):
            raise HTTPException(
                status_code=422,
                detail="CSV import content must be a string.",
            )
        parsed = parse_csv_trades(payload.content)
    else:
        rows = _json_rows(payload.content)
        parsed = parse_json_trades(rows)

    preview = parsed["trades"][: payload.preview_limit]
    return {
        "summary": parsed["summary"],
        "trades_preview": [_json_trade(trade) for trade in preview],
        "preview_limit": payload.preview_limit,
        "has_more": parsed["summary"]["valid_rows"] > payload.preview_limit,
        "source": source,
    }


def _json_rows(content: Any) -> list[Mapping[str, Any]]:
    if isinstance(content, Mapping):
        return [content] if content else []
    if isinstance(content, list):
        if not all(isinstance(row, Mapping) for row in content):
            raise HTTPException(
                status_code=422,
                detail="JSON import content must be an object or array of objects.",
            )
        return content
    raise HTTPException(
        status_code=422,
        detail="JSON import content must be an object or array of objects.",
    )


def _json_trade(trade: dict[str, Any]) -> dict[str, Any]:
    return {
        key: _json_value(value)
        for key, value in trade.items()
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    return value
