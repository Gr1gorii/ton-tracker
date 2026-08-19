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
from services.wallet_case_report_revisions import (
    MAX_PAGE_LIMIT,
    WalletCaseReportRevisionConflict,
    WalletCaseReportRevisionInvalidCursor,
    WalletCaseReportRevisionNotFound,
    WalletCaseReportRevisionScopeTooLarge,
    WalletCaseReportRevisionService,
    WalletCaseReportRevisionSnapshotNotFound,
)
from wallet_case_report_revision_schemas import (
    WalletCaseReportRevisionCaptureRequest,
    WalletCaseReportRevisionCaptureResponse,
    WalletCaseReportRevisionCatalog,
    WalletCaseReportRevisionDetailResponse,
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
_REPORT_ID_PATTERN = r"^rpt_[0-9a-f]{64}$"


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


@router.get(
    "/{public_id}/reports",
    response_model=WalletCaseReportRevisionCatalog,
)
def read_case_report_revisions(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    response.headers["Cache-Control"] = "no-store"
    limit, cursor = _revision_catalog_query(request)
    return _revision_call(
        session,
        lambda service: service.catalog(public_id, limit=limit, cursor=cursor),
    )


@router.post(
    "/{public_id}/reports",
    response_model=WalletCaseReportRevisionCaptureResponse,
    status_code=201,
)
def capture_case_report_revision(
    request: Request,
    response: Response,
    body: WalletCaseReportRevisionCaptureRequest,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    _no_query(request)
    response.headers["Cache-Control"] = "no-store"
    payload = _revision_call(
        session,
        lambda service: service.capture(
            public_id,
            snapshot_public_id=body.snapshot_public_id,
        ),
    )
    if not payload["created"]:
        response.status_code = 200
    return payload


@router.get(
    "/{public_id}/reports/{report_public_id}",
    response_model=WalletCaseReportRevisionDetailResponse,
)
def read_case_report_revision(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    report_public_id: str = Path(
        ...,
        pattern=_REPORT_ID_PATTERN,
        min_length=68,
        max_length=68,
    ),
    session: Session = Depends(get_session),
) -> dict:
    _no_query(request)
    response.headers["Cache-Control"] = "no-store"
    return _revision_call(
        session,
        lambda service: service.detail(
            public_id,
            report_public_id=report_public_id,
        ),
    )


@router.get("/{public_id}/reports/{report_public_id}/export.json")
def export_case_report_revision(
    request: Request,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    report_public_id: str = Path(
        ...,
        pattern=_REPORT_ID_PATTERN,
        min_length=68,
        max_length=68,
    ),
    session: Session = Depends(get_session),
) -> Response:
    _no_query(request)
    payload = _revision_call(
        session,
        lambda service: service.detail(
            public_id,
            report_public_id=report_public_id,
        ),
    )
    detail = WalletCaseReportRevisionDetailResponse.model_validate(payload)
    return Response(
        content=json.dumps(
            detail.report.model_dump(mode="json"),
            sort_keys=True,
            indent=2,
            ensure_ascii=True,
        ),
        media_type="application/json",
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (
                f'attachment; filename="wallet_case_report_{report_public_id}.json"'
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


def _revision_catalog_query(request: Request) -> tuple[int, str | None]:
    pairs = request.query_params.multi_items()
    if any(name not in {"limit", "cursor"} for name, _value in pairs):
        raise _error(
            422,
            "invalid_case_report_revision_query",
            "Report history accepts only limit and cursor.",
        )
    for name in ("limit", "cursor"):
        if len(request.query_params.getlist(name)) > 1:
            raise _error(
                422,
                "invalid_case_report_revision_query",
                f"{name} must be provided at most once.",
            )
    raw_limit = request.query_params.get("limit")
    try:
        limit = 10 if raw_limit is None else int(raw_limit)
    except ValueError as exc:
        raise _error(
            422,
            "invalid_case_report_revision_query",
            "limit must be an integer between 1 and 20.",
        ) from exc
    if not 1 <= limit <= MAX_PAGE_LIMIT or (
        raw_limit is not None and raw_limit != str(limit)
    ):
        raise _error(
            422,
            "invalid_case_report_revision_query",
            "limit must be an integer between 1 and 20.",
        )
    cursor = request.query_params.get("cursor")
    if cursor is not None and (cursor != cursor.strip() or not cursor):
        raise _error(
            422,
            "invalid_case_report_revision_query",
            "cursor must be one opaque non-empty value.",
        )
    return limit, cursor


def _no_query(request: Request) -> None:
    if request.query_params.multi_items():
        raise _error(
            422,
            "invalid_case_report_revision_query",
            "This report revision operation does not accept query parameters.",
        )


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


def _revision_call(session: Session, operation) -> dict:
    try:
        return operation(WalletCaseReportRevisionService(session))
    except WalletCaseReportRevisionNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseReportRevisionSnapshotNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseReportRevisionInvalidCursor as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except WalletCaseReportRevisionConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except WalletCaseReportRevisionScopeTooLarge as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "case_report_revision_storage_unavailable",
            "Wallet Case report revision storage is unavailable.",
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
