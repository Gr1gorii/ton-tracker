"""Product-facing Wallet Case API facade."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_session
from services.wallet_cases import (
    WalletCaseNotFound,
    WalletCaseRuntimeConflict,
    WalletCaseService,
)
from services.wallet_case_access import require_local_wallet_case_access
from wallet_case_schemas import (
    WalletCaseCreateRequest,
    WalletCaseListResponse,
    WalletCaseResponse,
    WalletCaseSyncRequest,
    WalletCaseSyncResponse,
    WalletCaseUpsertResponse,
)


router = APIRouter(
    prefix="/api/v1/cases",
    tags=["wallet-cases"],
    dependencies=[Depends(require_local_wallet_case_access)],
)
_PUBLIC_ID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_MAX_CASE_LIST_LIMIT = 50


@router.post("", response_model=WalletCaseUpsertResponse)
def create_or_open_wallet_case(
    payload: WalletCaseCreateRequest,
    response: Response,
    session: Session = Depends(get_session),
) -> dict:
    """Create or idempotently open one canonical owner-scoped Wallet Case."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).create_or_open_case(payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseRuntimeConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get("", response_model=WalletCaseListResponse)
def list_wallet_cases(
    request: Request,
    response: Response,
    limit: str = Query(
        "20",
        pattern=r"^[1-9][0-9]*$",
        max_length=2,
        description="Canonical page size from 1 through 50.",
    ),
    session: Session = Depends(get_session),
) -> dict:
    """List a bounded newest-updated page in the local owner scope."""
    query_pairs = request.query_params.multi_items()
    if any(name != "limit" for name, _value in query_pairs):
        raise HTTPException(
            status_code=422,
            detail="Wallet Case catalog accepts only the limit query parameter",
        )
    if len(request.query_params.getlist("limit")) > 1:
        raise HTTPException(
            status_code=422,
            detail="Wallet Case catalog limit must be provided at most once",
        )
    canonical_limit = int(limit, 10)
    if canonical_limit > _MAX_CASE_LIST_LIMIT:
        raise HTTPException(
            status_code=422,
            detail="limit must be no greater than 50",
        )
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).list_cases(limit=canonical_limit)
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get("/{public_id}", response_model=WalletCaseResponse)
def read_wallet_case(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Read a Wallet Case and its latest usable bounded summary."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).get_case(public_id)
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.post(
    "/{public_id}/syncs",
    response_model=WalletCaseSyncResponse,
)
def synchronize_wallet_case(
    payload: WalletCaseSyncRequest,
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Run one bounded synchronous compatibility sync for a Wallet Case."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).synchronize_case(public_id, payload)
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseRuntimeConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case sync storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get(
    "/{public_id}/syncs/{sync_public_id}",
    response_model=WalletCaseSyncResponse,
)
def read_wallet_case_sync(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    sync_public_id: str = Path(
        ...,
        pattern=_PUBLIC_ID_PATTERN,
        max_length=36,
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Read one sync by its case-scoped non-sequential public identifier."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).get_sync(public_id, sync_public_id)
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case sync storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc
