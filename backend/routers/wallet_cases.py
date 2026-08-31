"""Product-facing Wallet Case API facade."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_session
from services.wallet_cases import (
    WalletCaseArchiveConflict,
    WalletCaseCatalogInvalidCursor,
    WalletCaseCheckpointHistoryInvalidCursor,
    WalletCaseCheckpointResumeUnavailable,
    WalletCaseContinuationPlanStale,
    WalletCaseDeletionConflict,
    WalletCaseMetadataConflict,
    WalletCaseNotFound,
    WalletCaseIdempotencyConflict,
    WalletCaseIncrementalSyncUnavailable,
    WalletCaseRuntimeConflict,
    WalletCaseService,
    WalletCaseStreamCheckpointCorrupt,
    WalletCaseSyncAlreadyActive,
    WalletCaseSyncManifestCorrupt,
    WalletCaseSyncManifestNotFound,
)
from services.wallet_case_access import require_local_wallet_case_access
from wallet_case_schemas import (
    WalletCaseCreateRequest,
    WalletCaseDeletionResponse,
    WalletCaseListResponse,
    WalletCaseMetadataUpdateRequest,
    WalletCaseResponse,
    WalletCaseSyncRequest,
    WalletCaseSyncManifestResponse,
    WalletCaseCheckpointContinuationPlanResponse,
    WalletCaseStreamCheckpointCatalogResponse,
    WalletCaseStreamCheckpointChainResponse,
    WalletCaseStreamCheckpointDetailResponse,
    WalletCaseStreamCheckpointHistoryResponse,
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
_CHECKPOINT_ID_PATTERN = r"^scp_[0-9a-f]{64}$"
_CONTINUATION_PLAN_ID_PATTERN = r"^cpl_[0-9a-f]{64}$"
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
    cursor: str | None = Query(
        None,
        min_length=1,
        max_length=1024,
        description="Authenticated continuation from the preceding Case page.",
    ),
    state: str = Query(
        "active",
        pattern=r"^(active|archived)$",
        max_length=8,
        description="Lifecycle catalog to read.",
    ),
    q: str | None = Query(
        None,
        min_length=1,
        max_length=120,
        description="Case-insensitive text search across Case metadata and address.",
    ),
    network: str | None = Query(
        None,
        pattern=r"^(ton-mainnet|ton-testnet)$",
        max_length=11,
        description="Exact TON network filter.",
    ),
    data_environment: str | None = Query(
        None,
        pattern=r"^(demo|live)$",
        max_length=4,
        description="Exact data environment filter.",
    ),
    session: Session = Depends(get_session),
) -> dict:
    """List a bounded, frozen-order page in the local owner scope."""
    query_pairs = request.query_params.multi_items()
    allowed_query_parameters = {
        "limit",
        "cursor",
        "state",
        "q",
        "network",
        "data_environment",
    }
    if any(name not in allowed_query_parameters for name, _value in query_pairs):
        raise HTTPException(
            status_code=422,
            detail="Wallet Case catalog contains an unsupported query parameter",
        )
    for name in allowed_query_parameters:
        if len(request.query_params.getlist(name)) > 1:
            raise HTTPException(
                status_code=422,
                detail=f"Wallet Case catalog {name} must be provided at most once",
            )
    canonical_limit = int(limit, 10)
    if canonical_limit > _MAX_CASE_LIST_LIMIT:
        raise HTTPException(
            status_code=422,
            detail="limit must be no greater than 50",
        )
    canonical_query = q.strip() if q is not None else None
    if q is not None and not canonical_query:
        raise HTTPException(
            status_code=422,
            detail="Wallet Case catalog q must contain a non-whitespace character",
        )
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).list_cases(
            limit=canonical_limit,
            state=state,
            query=canonical_query,
            network=network,
            data_environment=data_environment,
            cursor=cursor,
        )
    except WalletCaseCatalogInvalidCursor as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.code,
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
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


@router.post("/{public_id}/archive", response_model=WalletCaseResponse)
def archive_wallet_case(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Archive one idle Case while retaining its evidence and reports."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).archive_case(public_id)
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseArchiveConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "case_archive_jobs_active",
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
                "code": "case_archive_changed",
                "message_safe": str(exc),
                "retryable": True,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case archival storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.post("/{public_id}/restore", response_model=WalletCaseResponse)
def restore_wallet_case(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Restore one archived Case to active owner-scoped workflows."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).restore_case(public_id)
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseRuntimeConflict as exc:
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail={
                "code": "case_restore_changed",
                "message_safe": str(exc),
                "retryable": True,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case restoration storage is unavailable.",
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
    except WalletCaseIncrementalSyncUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "incremental_sync_unavailable",
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
    except WalletCaseSyncManifestCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "acquisition_manifest_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
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
    "/{public_id}/stream-checkpoints",
    response_model=WalletCaseStreamCheckpointCatalogResponse,
)
def list_wallet_case_stream_checkpoints(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Read the newest verified continuation record for each provider stream."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).list_stream_checkpoints(public_id)
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseStreamCheckpointCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stream_checkpoint_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case stream checkpoint storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get(
    "/{public_id}/stream-checkpoints/history",
    response_model=WalletCaseStreamCheckpointHistoryResponse,
)
def list_wallet_case_stream_checkpoint_history(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    limit: str = Query(
        "20",
        pattern=r"^[1-9][0-9]*$",
        max_length=2,
        description="Canonical checkpoint revision page size from 1 through 50.",
    ),
    cursor: str | None = Query(
        None,
        min_length=1,
        max_length=1024,
        description="Authenticated continuation from the preceding history page.",
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Read a frozen, newest-first page of verified checkpoint revisions."""
    query_pairs = request.query_params.multi_items()
    if any(name not in {"limit", "cursor"} for name, _value in query_pairs):
        raise HTTPException(
            status_code=422,
            detail="Checkpoint history contains an unsupported query parameter",
        )
    for name in ("limit", "cursor"):
        if len(request.query_params.getlist(name)) > 1:
            raise HTTPException(
                status_code=422,
                detail=f"Checkpoint history {name} must be provided at most once",
            )
    canonical_limit = int(limit, 10)
    if canonical_limit > 50:
        raise HTTPException(
            status_code=422,
            detail="limit must be no greater than 50",
        )
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).list_stream_checkpoint_history(
            public_id,
            limit=canonical_limit,
            cursor=cursor,
        )
    except WalletCaseCheckpointHistoryInvalidCursor as exc:
        raise HTTPException(
            status_code=422,
            detail={
                "code": exc.code,
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseStreamCheckpointCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stream_checkpoint_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case checkpoint history storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get(
    "/{public_id}/stream-checkpoints/continuation-plan",
    response_model=WalletCaseCheckpointContinuationPlanResponse,
)
def read_wallet_case_checkpoint_continuation_plan(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Build the bounded plan over every latest verified provider stream."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).get_checkpoint_continuation_plan(
            public_id
        )
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseStreamCheckpointCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stream_checkpoint_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case continuation plan storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.post(
    (
        "/{public_id}/stream-checkpoints/continuation-plan/"
        "{continuation_plan_public_id}/{checkpoint_public_id}/resume"
    ),
    response_model=WalletCaseSyncResponse,
    status_code=202,
)
def enqueue_wallet_case_checkpoint_plan_resume(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    continuation_plan_public_id: str = Path(
        ...,
        pattern=_CONTINUATION_PLAN_ID_PATTERN,
        max_length=68,
    ),
    checkpoint_public_id: str = Path(
        ...,
        pattern=_CHECKPOINT_ID_PATTERN,
        max_length=68,
    ),
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
    """Resume one stream only from the exact plan the operator verified."""
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
        result, replayed = WalletCaseService(
            session
        ).enqueue_checkpoint_plan_resume(
            public_id,
            continuation_plan_public_id,
            checkpoint_public_id,
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
    except WalletCaseContinuationPlanStale as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "continuation_plan_stale",
                "message_safe": str(exc),
                "retryable": False,
                "current_plan_public_id": exc.current_plan_public_id,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseCheckpointResumeUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "checkpoint_resume_unavailable",
                "message_safe": str(exc),
                "retryable": False,
            },
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
    except WalletCaseStreamCheckpointCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stream_checkpoint_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case checkpoint resume storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get(
    "/{public_id}/stream-checkpoints/{checkpoint_public_id}",
    response_model=WalletCaseStreamCheckpointDetailResponse,
)
def read_wallet_case_stream_checkpoint(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    checkpoint_public_id: str = Path(
        ...,
        pattern=_CHECKPOINT_ID_PATTERN,
        max_length=68,
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Read one exact, verified checkpoint revision and its lineage."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).get_stream_checkpoint_detail(
            public_id,
            checkpoint_public_id,
        )
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseStreamCheckpointCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stream_checkpoint_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case stream checkpoint storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get(
    "/{public_id}/stream-checkpoints/{checkpoint_public_id}/chain",
    response_model=WalletCaseStreamCheckpointChainResponse,
)
def read_wallet_case_stream_checkpoint_chain(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    checkpoint_public_id: str = Path(
        ...,
        pattern=_CHECKPOINT_ID_PATTERN,
        max_length=68,
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Build one content-addressed, recursively verified checkpoint chain."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).get_stream_checkpoint_chain(
            public_id,
            checkpoint_public_id,
        )
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseStreamCheckpointCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stream_checkpoint_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case checkpoint chain storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.post(
    "/{public_id}/stream-checkpoints/{checkpoint_public_id}/resume",
    response_model=WalletCaseSyncResponse,
    status_code=202,
)
def enqueue_wallet_case_checkpoint_resume(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    checkpoint_public_id: str = Path(
        ...,
        pattern=_CHECKPOINT_ID_PATTERN,
        max_length=68,
    ),
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
    """Continue one latest, verified, resume-ready provider stream."""
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
        result, replayed = WalletCaseService(session).enqueue_checkpoint_resume(
            public_id,
            checkpoint_public_id,
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
    except WalletCaseCheckpointResumeUnavailable as exc:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "checkpoint_resume_unavailable",
                "message_safe": str(exc),
                "retryable": False,
            },
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
    except WalletCaseStreamCheckpointCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "stream_checkpoint_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case checkpoint resume storage is unavailable.",
            headers={"Cache-Control": "no-store"},
        ) from exc


@router.get(
    "/{public_id}/syncs/{sync_public_id}/manifest",
    response_model=WalletCaseSyncManifestResponse,
)
def read_wallet_case_sync_manifest(
    response: Response,
    public_id: str = Path(..., pattern=_PUBLIC_ID_PATTERN, max_length=36),
    sync_public_id: str = Path(
        ...,
        pattern=_PUBLIC_ID_PATTERN,
        max_length=36,
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Read verified, provider-safe acquisition evidence for one sync."""
    response.headers["Cache-Control"] = "no-store"
    try:
        return WalletCaseService(session).get_sync_manifest(
            public_id,
            sync_public_id,
        )
    except WalletCaseSyncManifestNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "acquisition_manifest_not_found",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers={"Cache-Control": "no-store"},
        ) from exc
    except WalletCaseSyncManifestCorrupt as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "acquisition_manifest_integrity_error",
                "message_safe": str(exc),
                "retryable": False,
            },
            headers={"Cache-Control": "no-store"},
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise HTTPException(
            status_code=503,
            detail="Wallet Case acquisition manifest storage is unavailable.",
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
