"""Historical price preview API routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from schemas import HistoricalPricesPreviewResponse
from services.historical_pricing import build_historical_prices_preview

router = APIRouter(prefix="/api/prices", tags=["prices"])


@router.get(
    "/historical/preview",
    response_model=HistoricalPricesPreviewResponse,
)
def read_historical_prices_preview(
    token: str = Query(
        ...,
        min_length=1,
        description='Token to preview: "ton" or a jetton master address.',
    ),
    start: str = Query(..., description="ISO start datetime."),
    end: str = Query(..., description="ISO end datetime."),
) -> dict:
    """Preview provider-reported historical rate points for one token.

    Preview only -- points are not wired into cost-basis or PnL math, so
    Real PnL stays locked. Provider failures are reported as unavailable
    with no hidden fallback.
    """
    try:
        return build_historical_prices_preview(token=token, start=start, end=end)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
