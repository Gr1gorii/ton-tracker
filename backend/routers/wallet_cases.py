"""Product-facing Wallet Case API facade."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_session
from services.wallet_cases import (
    WalletCaseDeletionConflict,
    WalletCaseMetadataConflict,
    WalletCaseNotFound,
    WalletCaseIdempotencyConflict,
    WalletCaseRuntimeConflict,
    WalletCaseService,
    WalletCaseSyncAlreadyActive,
)
from services.wallet_case_access import require_local_wallet_case_access
from wallet_case_schemas import (
    WalletCaseCreateRequest,
    WalletCaseDeletionResponse,
    WalletCaseListResponse,
    WalletCaseMetadataUpdateRequest,
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
jobs_router = APIRouter(
    prefix="/api/v1/jobs",
    tags=["wallet-case-jobs"],
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


@router.delete("/{public_id}", response_model=WalletCaseDeletionResponse)
def delete_wallet_case(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Permanently delete one case after all case-owned jobs become terminal."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).delete_case(public_id)
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseDeletionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "case_delete_jobs_active",
                "message_safe": str(exc),
                "retryable": False,
                "active_sync_public_id": exc.active_sync_public_id,
                "active_evidence_public_id": exc.active_evidence_public_id,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseRuntimeConflict as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "case_delete_changed",
                "message_safe": str(exc),
                "retryable": True,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case deletion storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.patch("/{public_id}", response_model=WalletCaseResponse)
def update_wallet_case_metadata(
    payload: WalletCaseMetadataUpdateRequest,
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Update the label or note without changing the canonical case scope."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).update_case_metadata(public_id, payload)
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseMetadataConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "case_metadata_changed",
                "message_safe": str(exc),
                "retryable": True,
                "current_metadata_version": exc.current_metadata_version,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case metadata storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.post(
    "/{public_id}/syncs",
    response_model=WalletCaseSyncResponse,
    status_code=202,
)
def enqueue_wallet_case_sync(
    payload: WalletCaseSyncRequest,
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
            r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
        ),
        max_length=36,
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Persist one bounded job before any provider I/O and return 202."""
    response.headers["Cache-Control"] = "no-store"
    runner = getattr(request.app.state, "wallet_case_job_runner", None)
    if runner is None or getattr(runner, "alive", False) is not True:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "case_sync_runner_unavailable",
                "message_safe": (
                    "Wallet Case synchronization is temporarily unavailable."
                ),
                "retryable": True,
            },
            headers={"Cache-Control": "no-store", "Retry-After": "5"},
        )
    if len(request.headers.getlist("idempotency-key")) != 1:
        raise HTTPException(
            status_code=422,
            detail="Idempotency-Key must be provided exactly once.",
            headers={"Cache-Control": "no-store"},
        )
    try:
        result, replayed = WalletCaseService(session).enqueue_sync(
            public_id,
            payload,
            idempotency_key,
        )
        response.headers["Location"] = (
            f"/api/v1/cases/{public_id}/syncs/{result['public_id']}"
        )
        response.headers["Retry-After"] = "1"
        if not replayed:
            runner.notify()
        return result
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
    except WalletCaseIdempotencyConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "idempotency_conflict",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseSyncAlreadyActive as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "case_sync_already_active",
                "message_safe": str(exc),
                "retryable": False,
                "active_sync_public_id": exc.public_id,
            },
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


@router.post(
    "/{public_id}/syncs/{sync_public_id}/cancel",
    response_model=WalletCaseSyncResponse,
)
def cancel_wallet_case_sync(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    sync_public_id: str = Path(
        ...,
        pattern=_PUBLIC_ID_PATTERN,
        max_length=36,
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Idempotently cancel queued work or request cooperative cancellation."""
    response.headers["Cache-Control"] = "no-store"
    try:
        result, accepted = WalletCaseService(session).cancel_sync(
            public_id,
            sync_public_id,
        )
        response.status_code = 202 if accepted else 200
        if accepted:
            response.headers["Retry-After"] = "1"
        return result
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


@jobs_router.get("/{sync_public_id}", response_model=WalletCaseSyncResponse)
def read_wallet_case_job(
    response: Response,
    sync_public_id: str = Path(
        ...,
        pattern=_PUBLIC_ID_PATTERN,
        max_length=36,
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Read one owner-scoped CaseSync through the generic job polling path."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).get_job(sync_public_id)
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
            detail="Wallet Case job storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc
