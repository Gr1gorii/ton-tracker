"""STON.fi preview API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from adapters.stonfi import StonfiAdapter
from config import ProviderResult, get_settings
from schemas import StonfiPoolsPreviewResponse

router = APIRouter(prefix="/api/stonfi", tags=["stonfi"])

STONFI_SCOPE_WARNING = (
    "STON.fi data covers STON.fi DEX pools only, not all TON DeFi."
)


@router.get(
    "/pools/preview",
    response_model=StonfiPoolsPreviewResponse,
)
def preview_pools(
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of normalized STON.fi pools to preview.",
    ),
) -> dict[str, Any]:
    """Fetch a STON.fi pools preview without running dashboard analysis."""
    settings = get_settings()
    adapter = StonfiAdapter(settings)
    result = adapter.get_pools_preview(limit=limit)

    if not result.ok:
        return _error_response(settings.data_mode, limit, result)

    data = result.data if isinstance(result.data, dict) else {}
    pools = data.get("pools") if isinstance(data.get("pools"), list) else []
    preview_count = _int_value(data.get("preview_count"), len(pools))
    total_pools = _int_value(data.get("total_pools"), preview_count)
    message = result.message or (
        "STON.fi pool preview fetched. Covers STON.fi DEX pools only, not all "
        "TON DeFi."
    )
    return {
        "provider": "stonfi",
        "data_mode": settings.data_mode,
        "source": result.source,
        "success": True,
        "summary": {
            "total_pools": total_pools,
            "preview_count": preview_count,
            "requested_limit": limit,
        },
        "pools_preview": pools,
        "warnings": _warnings_for_result(result),
        "message": message,
        "error": None,
    }


def _error_response(
    data_mode: str,
    limit: int,
    result: ProviderResult,
) -> dict[str, Any]:
    message = result.message or "STON.fi provider returned an error."
    warnings = [f"STON.fi provider warning: {message}", STONFI_SCOPE_WARNING]
    error = {
        "code": result.error,
        "message": message,
    }
    if result.diagnostic:
        warnings.insert(1, f"STON.fi diagnostic: {result.diagnostic}")
        error["diagnostic"] = result.diagnostic
    return {
        "provider": "stonfi",
        "data_mode": data_mode,
        "source": result.source,
        "success": False,
        "summary": {
            "total_pools": 0,
            "preview_count": 0,
            "requested_limit": limit,
        },
        "pools_preview": [],
        "warnings": warnings,
        "message": message,
        "error": error,
    }


def _warnings_for_result(result: ProviderResult) -> list[str]:
    warnings = [STONFI_SCOPE_WARNING]
    if result.source == "mock":
        warnings.insert(0, "Mock/offline mode: STON.fi is not actively queried.")
    return warnings


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
