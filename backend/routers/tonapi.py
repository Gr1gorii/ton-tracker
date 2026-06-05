"""TonAPI preview API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from adapters.tonapi import TonapiAdapter
from config import ProviderResult, get_settings
from schemas import (
    TonapiAccountJettonsPreviewResponse,
    TonapiWalletIntelligencePreviewResponse,
)
from services.tonapi_wallet_intelligence import (
    build_wallet_intelligence_preview,
    empty_wallet_intelligence_preview,
)

router = APIRouter(prefix="/api/tonapi", tags=["tonapi"])

TONAPI_SCOPE_WARNING = (
    "TonAPI preview shows account jetton data only; it is not full wallet "
    "intelligence yet."
)
TONAPI_PUBLIC_MODE_WARNING = (
    "TonAPI API key is not configured; public mode may be rate limited."
)
TONAPI_WALLET_INTELLIGENCE_SCOPE_WARNING = (
    "TonAPI wallet intelligence preview is based only on account jetton data; "
    "it is not full wallet intelligence."
)
TONAPI_WALLET_INTELLIGENCE_LIMIT_WARNING = (
    "It does not include full transaction history, PnL, DEX swaps, current "
    "TON balance, or full on-chain behavior."
)


@router.get(
    "/account-jettons/preview",
    response_model=TonapiAccountJettonsPreviewResponse,
)
def preview_account_jettons(
    account_address: str = Query(
        ...,
        min_length=1,
        description="TON account address to preview jetton balances for.",
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of normalized TonAPI jettons to preview.",
    ),
) -> dict[str, Any]:
    """Fetch a TonAPI account jettons preview without dashboard analysis."""
    cleaned_account = account_address.strip()
    if not cleaned_account:
        raise HTTPException(
            status_code=422,
            detail="account_address must not be empty",
        )

    settings = get_settings()
    adapter = TonapiAdapter(settings)
    result = adapter.get_account_jettons_preview(
        account_address=cleaned_account,
        limit=limit,
    )

    if not result.ok:
        return _error_response(settings, cleaned_account, limit, result)

    data = result.data if isinstance(result.data, dict) else {}
    jettons = (
        data.get("jettons") if isinstance(data.get("jettons"), list) else []
    )
    preview_count = _int_value(data.get("preview_count"), len(jettons))
    total_jettons = _int_value(data.get("total_jettons"), preview_count)
    account = str(data.get("wallet_address") or cleaned_account)
    message = result.message or (
        "TonAPI account jettons preview fetched. This is account jetton data "
        "only and is not full wallet intelligence yet."
    )

    return {
        "provider": "tonapi",
        "data_mode": settings.data_mode,
        "source": result.source,
        "success": True,
        "summary": {
            "total_jettons": total_jettons,
            "preview_count": preview_count,
            "requested_limit": limit,
        },
        "account_address": account,
        "jettons_preview": jettons,
        "warnings": _warnings_for_result(settings, result),
        "message": message,
        "error": None,
    }


@router.get(
    "/wallet-intelligence/preview",
    response_model=TonapiWalletIntelligencePreviewResponse,
)
def preview_wallet_intelligence(
    account_address: str = Query(
        ...,
        min_length=1,
        description="TON account address to build a jettons-only preview for.",
    ),
    limit: int = Query(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of normalized TonAPI jettons to analyze.",
    ),
) -> dict[str, Any]:
    """Build a jettons-only TonAPI wallet intelligence preview."""
    cleaned_account = account_address.strip()
    if not cleaned_account:
        raise HTTPException(
            status_code=422,
            detail="account_address must not be empty",
        )

    settings = get_settings()
    adapter = TonapiAdapter(settings)
    result = adapter.get_account_jettons_preview(
        account_address=cleaned_account,
        limit=limit,
    )

    if not result.ok:
        return _wallet_intelligence_error_response(
            settings,
            cleaned_account,
            limit,
            result,
        )

    data = result.data if isinstance(result.data, dict) else {}
    jettons = (
        data.get("jettons") if isinstance(data.get("jettons"), list) else []
    )
    preview_count = _int_value(data.get("preview_count"), len(jettons))
    total_jettons = _int_value(data.get("total_jettons"), preview_count)
    account = str(data.get("wallet_address") or cleaned_account)
    intelligence = build_wallet_intelligence_preview(
        account_address=account,
        jettons=jettons,
        total_jettons=total_jettons,
        preview_count=preview_count,
        requested_limit=limit,
    )
    message = (
        "TonAPI wallet intelligence preview built from account jetton preview "
        "data only. It is not full wallet intelligence."
    )

    return {
        "provider": "tonapi",
        "data_mode": settings.data_mode,
        "source": result.source,
        "success": True,
        "account_address": account,
        "summary": _wallet_intelligence_summary(
            total_jettons,
            preview_count,
            limit,
            intelligence,
        ),
        "intelligence": intelligence,
        "jettons_preview": jettons,
        "warnings": _wallet_intelligence_warnings(settings, result.source),
        "message": message,
        "error": None,
    }


def _error_response(
    settings,
    account_address: str,
    limit: int,
    result: ProviderResult,
) -> dict[str, Any]:
    message = result.message or "TonAPI provider returned an error."
    warnings = [f"TonAPI provider warning: {message}"]
    if result.diagnostic:
        warnings.append(f"TonAPI diagnostic: {result.diagnostic}")
    warnings.extend(_scope_warnings(settings, result.source))

    error = {
        "code": result.error,
        "message": message,
    }
    if result.diagnostic:
        error["diagnostic"] = result.diagnostic

    return {
        "provider": "tonapi",
        "data_mode": settings.data_mode,
        "source": result.source,
        "success": False,
        "summary": {
            "total_jettons": 0,
            "preview_count": 0,
            "requested_limit": limit,
        },
        "account_address": account_address,
        "jettons_preview": [],
        "warnings": warnings,
        "message": message,
        "error": error,
    }


def _wallet_intelligence_error_response(
    settings,
    account_address: str,
    limit: int,
    result: ProviderResult,
) -> dict[str, Any]:
    message = result.message or "TonAPI provider returned an error."
    warnings = [f"TonAPI provider warning: {message}"]
    if result.diagnostic:
        warnings.append(f"TonAPI diagnostic: {result.diagnostic}")
    warnings.extend(_wallet_intelligence_warnings(settings, result.source))

    intelligence = empty_wallet_intelligence_preview(
        account_address=account_address,
        requested_limit=limit,
        note=(
            "TonAPI provider did not return account jetton preview data; no "
            "wallet intelligence preview signals were derived."
        ),
    )
    error = {
        "code": result.error,
        "message": message,
    }
    if result.diagnostic:
        error["diagnostic"] = result.diagnostic

    return {
        "provider": "tonapi",
        "data_mode": settings.data_mode,
        "source": result.source,
        "success": False,
        "account_address": account_address,
        "summary": _wallet_intelligence_summary(0, 0, limit, intelligence),
        "intelligence": intelligence,
        "jettons_preview": [],
        "warnings": warnings,
        "message": message,
        "error": error,
    }


def _warnings_for_result(settings, result: ProviderResult) -> list[str]:
    return _scope_warnings(settings, result.source)


def _scope_warnings(settings, source: str) -> list[str]:
    warnings = [TONAPI_SCOPE_WARNING]
    if source == "mock":
        warnings.insert(0, "Mock/offline mode: TonAPI is not actively queried.")
    if settings.is_real and not settings.tonapi_api_key:
        warnings.append(TONAPI_PUBLIC_MODE_WARNING)
    return warnings


def _wallet_intelligence_warnings(settings, source: str) -> list[str]:
    warnings = [
        TONAPI_WALLET_INTELLIGENCE_SCOPE_WARNING,
        TONAPI_WALLET_INTELLIGENCE_LIMIT_WARNING,
    ]
    if source == "mock":
        warnings.insert(0, "Mock/offline mode: TonAPI is not actively queried.")
    if settings.is_real and not settings.tonapi_api_key:
        warnings.append(TONAPI_PUBLIC_MODE_WARNING)
    return warnings


def _wallet_intelligence_summary(
    total_jettons: int,
    preview_count: int,
    requested_limit: int,
    intelligence: dict[str, Any],
) -> dict[str, Any]:
    return {
        "total_jettons": total_jettons,
        "preview_count": preview_count,
        "requested_limit": requested_limit,
        "non_zero_balance_count": _int_value(
            intelligence.get("non_zero_balance_count"),
            0,
        ),
        "jettons_with_price_count": _int_value(
            intelligence.get("jettons_with_price_count"),
            0,
        ),
        "stablecoin_like_count": _int_value(
            intelligence.get("stablecoin_like_count"),
            0,
        ),
    }


def _int_value(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
