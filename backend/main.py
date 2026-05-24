"""FastAPI application entry point for the TON Wallet Intelligence Dashboard.

v0.2.1 — data provenance labels for mixed real/mock mode. Pool/token data may
be real in DATA_MODE=real through GeckoTerminal, but wallet-level analysis
remains mock. Mock mode is the default and stays fully functional.
"""

from __future__ import annotations

import json

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session

from config import get_settings
from database import get_session, init_db
from models import AnalysisRun
from schemas import (
    AnalyzeRequest,
    AnalyzeResponse,
    HealthResponse,
    ProvidersStatusResponse,
)
from routers.import_trades import router as import_trades_router
from services import export
from services.analysis import analyze, get_providers_status

VERSION = "0.2.1"

app = FastAPI(
    title="TON Wallet Intelligence Dashboard API",
    version=VERSION,
    description=(
        "v0.2.1 — data provenance labels for mixed real/mock mode. "
        "Pool/token data may be real in DATA_MODE=real through GeckoTerminal, "
        "but wallet-level analysis remains mock."
    ),
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

app.include_router(import_trades_router)


@app.on_event("startup")
def _on_startup() -> None:
    init_db()


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
    return get_providers_status()


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
