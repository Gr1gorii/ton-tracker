"""Wallet activity ingestion API routes."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_session
from schemas import WalletClusterCompareRequest, WalletClusterCompareResponse
from schemas import WalletIngestionPreviewRequest, WalletIngestionPreviewResponse
from schemas import WalletIngestionRunResponse, WalletRunSignalsResponse
from services import export
from services.wallet_activity_clustering import compare_wallet_activity
from services.wallet_activity_signals import derive_run_signals
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


@router.get(
    "/ingest/{run_id}/signals",
    response_model=WalletRunSignalsResponse,
)
def read_wallet_ingestion_run_signals(
    run_id: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> dict:
    """Return rule-based evidence signals for one persisted run.

    Heuristic, explainable observations only -- not a risk score or a verdict.
    """
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    return derive_run_signals(result)


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


@router.post(
    "/cluster/compare",
    response_model=WalletClusterCompareResponse,
)
def compare_wallet_ingestion_runs(
    payload: WalletClusterCompareRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Compare 2-25 persisted wallet ingestion runs pairwise.

    Returns a probabilistic behavioral-similarity signal only -- not proof
    of common ownership.
    """
    try:
        return compare_wallet_activity(payload.run_ids, session)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/cluster/compare/export.json")
def export_wallet_cluster_comparison(
    run_ids: list[int] = Query(..., description="Run ids to compare and export."),
    session: Session = Depends(get_session),
) -> Response:
    """Download a wallet cluster comparison (pairs, signals, note) as JSON.

    The comparison is computed on the fly from the given run ids; it is a
    probabilistic behavioral-similarity signal only, not proof of ownership.
    """
    try:
        result = compare_wallet_activity(run_ids, session)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    body = json.dumps(result, ensure_ascii=False, indent=2)
    suffix = "_".join(str(run_id) for run_id in dict.fromkeys(run_ids))
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename=wallet_cluster_comparison_{suffix}.json"
            )
        },
    )


@router.get("/cluster/compare/export.csv")
def export_wallet_cluster_comparison_csv(
    run_ids: list[int] = Query(..., description="Run ids to compare and export."),
    session: Session = Depends(get_session),
) -> Response:
    """Download a wallet cluster comparison as flattened pair CSV.

    One row per wallet pair; a probabilistic behavioral-similarity signal
    only, not proof of ownership.
    """
    try:
        result = compare_wallet_activity(run_ids, session)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    suffix = "_".join(str(run_id) for run_id in dict.fromkeys(run_ids))
    return Response(
        content=export.wallet_cluster_comparison_to_csv(result),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=wallet_cluster_comparison_{suffix}.csv"
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
