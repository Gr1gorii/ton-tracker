"""Local-only, content-addressed Wallet Case report endpoints."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_session
from services.wallet_case_access import require_local_wallet_case_access
from services.wallet_case_report import (
    WalletCaseReportConflict,
    WalletCaseReportNotFound,
    WalletCaseReportScopeTooLarge,
    WalletCaseReportService,
    WalletCaseReportSnapshotNotFound,
)
from wallet_case_report_schemas import WalletCaseReportResponse


router = APIRouter(
    prefix="/api/v1/cases",
    tags=["wallet-case-report"],
    dependencies=[Depends(require_local_wallet_case_access)],
)
_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_UUID_RE = re.compile(_UUID_PATTERN)


@router.get("/{public_id}/report", response_model=WalletCaseReportResponse)
def read_case_report(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    snapshot = _snapshot_query(request)
    return _build(public_id, snapshot, session)


@router.get("/{public_id}/report/export.json")
def export_case_report(
    request: Request,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> Response:
    snapshot = _snapshot_query(request)
    payload = _build(public_id, snapshot, session)
    validated = WalletCaseReportResponse.model_validate(payload).model_dump()
    report = validated["report"]
    if report is None:
        raise _error(
            409,
            "case_report_not_ready",
            "Synchronize this Wallet Case before exporting its report.",
        )
    return Response(
        content=json.dumps(
            validated,
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        ),
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (
                f'attachment; filename="wallet_case_report_{report["public_id"]}.json"'
            ),
        },
    )


def _snapshot_query(request: Request) -> str | None:
    pairs = request.query_params.multi_items()
    if any(name != "snapshot" for name, _value in pairs):
        raise _error(422, "invalid_case_report_query", "Report accepts only snapshot.")
    values = request.query_params.getlist("snapshot")
    if len(values) > 1:
        raise _error(
            422,
            "invalid_case_report_query",
            "snapshot must be provided at most once.",
        )
    snapshot = values[0] if values else None
    if snapshot is not None and (
        snapshot != snapshot.strip() or _UUID_RE.fullmatch(snapshot) is None
    ):
        raise _error(
            422,
            "invalid_case_report_query",
            "snapshot must be one canonical UUID.",
        )
    return snapshot


def _build(public_id: str, snapshot: str | None, session: Session) -> dict:
    try:
        return WalletCaseReportService(session).build(
            public_id,
            snapshot_public_id=snapshot,
        )
    except WalletCaseReportNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseReportSnapshotNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseReportConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except WalletCaseReportScopeTooLarge as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "case_report_storage_unavailable",
            "Wallet Case report storage is unavailable.",
            retryable=True,
        ) from exc


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
