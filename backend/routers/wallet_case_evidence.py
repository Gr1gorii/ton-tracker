"""Local-only Wallet Case evidence verification endpoints."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_session
from services.wallet_case_access import require_local_wallet_case_access
from services.wallet_case_evidence import (
    CaseEvidenceActivityNotFound,
    CaseEvidenceAlreadyActive,
    CaseEvidenceIdempotencyConflict,
    CaseEvidenceIneligible,
    CaseEvidenceNotFound,
    CaseEvidenceRuntimeUnavailable,
    CaseEvidenceScopeTooLarge,
    CaseEvidenceService,
    CaseEvidenceSnapshotConflict,
    CaseEvidenceSnapshotNotFound,
    CaseEvidenceStoredConflict,
)
from wallet_case_evidence_schemas import (
    CaseEvidenceCatalogResponse,
    CaseEvidenceVerificationRequest,
    CaseEvidenceVerificationResponse,
)


router = APIRouter(
    prefix="/api/v1/cases",
    tags=["wallet-case-evidence"],
    dependencies=[Depends(require_local_wallet_case_access)],
)
_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_UUID_RE = re.compile(_UUID_PATTERN)
_UUID4_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


@router.get(
    "/{public_id}/evidence",
    response_model=CaseEvidenceCatalogResponse,
)
def read_case_evidence(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    pairs = request.query_params.multi_items()
    if any(name != "snapshot" for name, _value in pairs):
        raise _error(422, "invalid_evidence_query", "Evidence accepts only snapshot.")
    values = request.query_params.getlist("snapshot")
    if len(values) > 1:
        raise _error(
            422,
            "invalid_evidence_query",
            "snapshot must be provided at most once.",
        )
    snapshot = values[0] if values else None
    if snapshot is not None and (
        snapshot != snapshot.strip() or _UUID_RE.fullmatch(snapshot) is None
    ):
        raise _error(
            422,
            "invalid_evidence_query",
            "snapshot must be one canonical UUID.",
        )
    try:
        return CaseEvidenceService(session).catalog(
            public_id,
            snapshot_public_id=snapshot,
            runner_available=(
                getattr(
                    getattr(request.app.state, "wallet_case_evidence_runner", None),
                    "alive",
                    False,
                )
                is True
            ),
        )
    except (CaseEvidenceNotFound, CaseEvidenceSnapshotNotFound) as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except CaseEvidenceStoredConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except (CaseEvidenceSnapshotConflict, CaseEvidenceScopeTooLarge) as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "evidence_storage_unavailable",
            "Wallet Case evidence storage is unavailable.",
            retryable=True,
        ) from exc


@router.post(
    "/{public_id}/evidence/verifications",
    response_model=CaseEvidenceVerificationResponse,
    status_code=202,
)
def enqueue_case_evidence_verification(
    payload: CaseEvidenceVerificationRequest,
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        pattern=_UUID4_PATTERN,
        max_length=36,
    ),
    session: Session = Depends(get_session),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    runner = getattr(request.app.state, "wallet_case_evidence_runner", None)
    if len(request.headers.getlist("idempotency-key")) != 1:
        raise _error(
            422,
            "invalid_idempotency_key",
            "Idempotency-Key must be provided exactly once.",
        )
    try:
        result, replayed = CaseEvidenceService(session).enqueue(
            public_id,
            payload,
            idempotency_key,
            runner_available=(
                runner is not None and getattr(runner, "alive", False) is True
            ),
        )
        response.headers["Location"] = (
            f"/api/v1/cases/{public_id}/evidence/verifications/{result['public_id']}"
        )
        response.headers["Retry-After"] = "1"
        if not replayed:
            runner.notify()
        return result
    except (CaseEvidenceNotFound, CaseEvidenceSnapshotNotFound, CaseEvidenceActivityNotFound) as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except (
        CaseEvidenceIneligible,
        CaseEvidenceSnapshotConflict,
        CaseEvidenceScopeTooLarge,
        CaseEvidenceIdempotencyConflict,
        CaseEvidenceStoredConflict,
    ) as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except CaseEvidenceAlreadyActive as exc:
        error = _error(409, exc.code, str(exc))
        error.detail["active_verification_public_id"] = exc.public_id
        raise error from exc
    except CaseEvidenceRuntimeUnavailable as exc:
        raise _error(
            503,
            exc.code,
            str(exc),
            retryable=exc.code == "evidence_runner_unavailable",
            retry_after="5" if exc.code == "evidence_runner_unavailable" else None,
        ) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "evidence_storage_unavailable",
            "Wallet Case evidence storage is unavailable.",
            retryable=True,
        ) from exc


@router.get(
    "/{public_id}/evidence/verifications/{verification_public_id}",
    response_model=CaseEvidenceVerificationResponse,
)
def read_case_evidence_verification(
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    verification_public_id: str = Path(
        ..., pattern=_UUID_PATTERN, max_length=36
    ),
    session: Session = Depends(get_session),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        return CaseEvidenceService(session).get_verification(
            public_id, verification_public_id
        )
    except CaseEvidenceNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except CaseEvidenceStoredConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "evidence_storage_unavailable",
            "Wallet Case evidence storage is unavailable.",
            retryable=True,
        ) from exc


@router.post(
    "/{public_id}/evidence/verifications/{verification_public_id}/cancel",
    response_model=CaseEvidenceVerificationResponse,
)
def cancel_case_evidence_verification(
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    verification_public_id: str = Path(
        ..., pattern=_UUID_PATTERN, max_length=36
    ),
    session: Session = Depends(get_session),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    try:
        result, accepted = CaseEvidenceService(session).cancel(
            public_id, verification_public_id
        )
        response.status_code = 202 if accepted else 200
        if accepted:
            response.headers["Retry-After"] = "1"
        return result
    except CaseEvidenceNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except CaseEvidenceStoredConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "evidence_storage_unavailable",
            "Wallet Case evidence storage is unavailable.",
            retryable=True,
        ) from exc


def _error(
    status: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
    retry_after: str | None = None,
) -> HTTPException:
    headers = {"Cache-Control": "no-store"}
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return HTTPException(
        status_code=status,
        detail={
            "code": code,
            "message_safe": message[:1000],
            "retryable": retryable,
        },
        headers=headers,
    )
