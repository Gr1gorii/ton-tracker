"""Wallet activity ingestion API routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Path
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_session
from schemas import WalletIngestionPreviewRequest, WalletIngestionPreviewResponse
from schemas import WalletIngestionRunResponse
from services import export
from services.wallet_activity_ingestion import (
    build_wallet_ingestion_preview,
    get_wallet_ingestion_run,
    persist_mock_wallet_ingestion,
)

router = APIRouter(prefix="/api/wallets", tags=["wallet-activity"])


@router.post(
    "/ingest/preview",
    response_model=WalletIngestionPreviewResponse,
)
def preview_wallet_ingestion(payload: WalletIngestionPreviewRequest) -> dict:
    """Preview mock-normalized wallet ingestion coverage without persistence."""
    try:
        return build_wallet_ingestion_preview(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post(
    "/ingest",
    response_model=WalletIngestionRunResponse,
)
def run_wallet_ingestion(
    payload: WalletIngestionPreviewRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Persist one deterministic mock-normalized wallet ingestion run."""
    try:
        return persist_mock_wallet_ingestion(payload, session)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get(
    "/ingest/{run_id}",
    response_model=WalletIngestionRunResponse,
)
def read_wallet_ingestion_run(
    run_id: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> dict:
    """Read one persisted wallet ingestion run."""
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    return result


@router.get("/ingest/{run_id}/export.json")
def export_wallet_ingestion_run(
    run_id: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> Response:
    """Download one persisted wallet ingestion run (rows + summary) as JSON."""
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    body = json.dumps(result, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename=wallet_ingestion_run_{run_id}.json"
            )
        },
    )


@router.get("/ingest/{run_id}/export.csv")
def export_wallet_ingestion_run_csv(
    run_id: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> Response:
    """Download one persisted wallet ingestion run as flattened activity CSV."""
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    return Response(
        content=export.wallet_ingestion_run_to_csv(result),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=wallet_ingestion_run_{run_id}.csv"
            )
        },
    )
