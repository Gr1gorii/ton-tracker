"""Local-only, pinned Wallet Case Findings and Flows endpoint."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_session
from services.wallet_case_access import require_local_wallet_case_access
from services.wallet_case_findings import (
    WalletCaseFindingsConflict,
    WalletCaseFindingsNotFound,
    WalletCaseFindingsScopeTooLarge,
    WalletCaseFindingsService,
    WalletCaseFindingsSnapshotNotFound,
)
from wallet_case_findings_schemas import WalletCaseFindingsResponse


router = APIRouter(
    prefix="/api/v1/cases",
    tags=["wallet-case-findings"],
    dependencies=[Depends(require_local_wallet_case_access)],
)
_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_UUID_RE = re.compile(_UUID_PATTERN)


@router.get("/{public_id}/findings", response_model=WalletCaseFindingsResponse)
def read_case_findings(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    snapshot = _snapshot_query(request)
    try:
        return WalletCaseFindingsService(session).build(
            public_id,
            snapshot_public_id=snapshot,
        )
    except WalletCaseFindingsNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseFindingsSnapshotNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseFindingsConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except WalletCaseFindingsScopeTooLarge as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "case_findings_storage_unavailable",
            "Wallet Case Findings storage is unavailable.",
            retryable=True,
        ) from exc


def _snapshot_query(request: Request) -> str | None:
    pairs = request.query_params.multi_items()
    if any(name != "snapshot" for name, _value in pairs):
        raise _error(
            422,
            "invalid_case_findings_query",
            "Findings accepts only snapshot.",
        )
    values = request.query_params.getlist("snapshot")
    if len(values) > 1:
        raise _error(
            422,
            "invalid_case_findings_query",
            "snapshot must be provided at most once.",
        )
    snapshot = values[0] if values else None
    if snapshot is not None and (
        snapshot != snapshot.strip() or _UUID_RE.fullmatch(snapshot) is None
    ):
        raise _error(
            422,
            "invalid_case_findings_query",
            "snapshot must be one canonical UUID.",
        )
    return snapshot


def _error(
    status: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> HTTPException:
    return HTTPException(
        status_code=status,
        detail={
            "code": code,
            "message_safe": message,
            "retryable": retryable,
        },
        headers={"Cache-Control": "no-store"},
    )


__all__ = ["router"]
