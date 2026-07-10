"""FastAPI application entry point for the TON wallet intelligence API.

The stable API-version field remains ``0.2.1``. Provider previews, guarded
live wallet ingestion, and stored-run intelligence keep explicit source and
limitation labels; deterministic mock mode remains the default.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from adapters.stonfi import StonfiAdapter
from adapters.tonapi import TonapiAdapter
from adapters.wallet_activity import get_wallet_activity_provider_status
from config import get_settings
from database import get_session, init_db
from models import AnalysisRun
from schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    HealthResponse,
    ProvidersStatusResponse,
)
from routers.bitquery import router as bitquery_router
from routers.import_trades import router as import_trades_router
from routers.prices import router as prices_router
from routers.stonfi import router as stonfi_router
from routers.tonapi import router as tonapi_router
from routers.wallet_activity import router as wallet_activity_router
from services import export
from services.analysis import analyze, get_providers_status

VERSION = "0.2.1"


@asynccontextmanager
async def _lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Apply schema migrations before the API begins serving requests."""
    init_db()
    yield


app = FastAPI(
    title="TON Wallet Intelligence Dashboard API",
    version=VERSION,
    description=(
        "Source-aware TON provider previews, guarded wallet ingestion, and "
        "stored-run diagnostics. Backend version 0.2.1 is the stable API "
        "contract; product release labels are managed separately."
    ),
    lifespan=_lifespan,
)

# Allow the local Vite dev server (and common alternates) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(bitquery_router)
app.include_router(import_trades_router)
app.include_router(prices_router)
app.include_router(stonfi_router)
app.include_router(tonapi_router)
app.include_router(wallet_activity_router)

@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    return HealthResponse(
        status="ok",
        version=VERSION,
        is_mock=settings.is_mock,
        data_mode=settings.data_mode,
    )


@app.get("/api/providers/status", response_model=ProvidersStatusResponse)
def providers_status() -> dict:
    return get_api_providers_status()


def get_api_providers_status(settings=None) -> dict:
    """Provider status payload for the public status endpoint.

    This intentionally augments the endpoint response without changing the
    analysis service's provider-status payload.
    """
    settings = settings or get_settings()
    status = get_providers_status(settings)
    status["stonfi"] = StonfiAdapter(settings).status()
    status["tonapi"] = TonapiAdapter(settings).status()
    status["wallet_activity"] = get_wallet_activity_provider_status(settings)
    return status


@app.post("/api/analyze", response_model=AnalyzeResponse)
def post_analyze(
    payload: AnalyzeRequest,
    session: Session = Depends(get_session),
) -> dict:
    try:
        result = analyze(
            pool_url=payload.pool_url,
            time_window=payload.time_window,
            custom_start=payload.custom_start,
            custom_end=payload.custom_end,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Persist a lightweight record of the run (best-effort).
    run = AnalysisRun(
        pool_url=payload.pool_url,
        time_window=payload.time_window,
        result_json=json.dumps(result, ensure_ascii=False),
    )
    session.add(run)
    session.commit()

    return result


def _run_for_export(pool_url: str, time_window: str) -> dict:
    try:
        return analyze(pool_url=pool_url, time_window=time_window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/api/export/csv")
def export_csv(
    pool_url: str = "https://www.geckoterminal.com/ton/pools/mock",
    time_window: str = "24h",
) -> Response:
    """Download the wallet table as CSV (runs a fresh mock analysis)."""
    result = _run_for_export(pool_url, time_window)
    csv_text = export.wallets_to_csv(result)
    return Response(
        content=csv_text,
        media_type="text/csv",
        headers={
            "Content-Disposition": "attachment; filename=ton_check_wallets.csv"
        },
    )


@app.get("/api/export/json")
def export_json(
    pool_url: str = "https://www.geckoterminal.com/ton/pools/mock",
    time_window: str = "24h",
) -> Response:
    """Download the full analysis as JSON (runs a fresh mock analysis)."""
    result = _run_for_export(pool_url, time_window)
    json_text = export.analysis_to_json(result)
    return Response(
        content=json_text,
        media_type="application/json",
        headers={
            "Content-Disposition": "attachment; filename=ton_check_analysis.json"
        },
    )


@app.get("/")
def root() -> dict:
    return {
        "name": "TON Wallet Intelligence Dashboard API",
        "version": VERSION,
        "data_mode": get_settings().data_mode,
        "docs": "/docs",
    }
