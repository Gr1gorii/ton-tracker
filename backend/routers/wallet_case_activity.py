"""Local-only Wallet Case Activity read endpoints."""

from __future__ import annotations

from datetime import datetime, timezone
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Request, Response
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from database import get_session
from services.wallet_case_access import require_local_wallet_case_access
from services.wallet_case_activity import (
    WalletCaseActivityInvalidCursor,
    WalletCaseActivityInvalidQuery,
    WalletCaseActivityItemNotFound,
    WalletCaseActivityNotFound,
    WalletCaseActivityQuery,
    WalletCaseActivityScopeTooLarge,
    WalletCaseActivityService,
    WalletCaseActivitySnapshotConflict,
    WalletCaseActivitySnapshotNotFound,
)
from wallet_case_activity_schemas import (
    WalletCaseActivityDetailResponse,
    WalletCaseActivityListResponse,
)


router = APIRouter(
    prefix="/api/v1/cases",
    tags=["wallet-case-activity"],
    dependencies=[Depends(require_local_wallet_case_access)],
)
_UUID_PATTERN = (
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_UUID_RE = re.compile(_UUID_PATTERN)
_ACTIVITY_PATTERN = r"^act_[0-9a-f]{64}$"
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)
_LIST_PARAMETERS = {
    "snapshot",
    "limit",
    "cursor",
    "kind",
    "direction",
    "outcome",
    "from_at",
    "to_at",
    "asset_id",
    "protocol_id",
    "counterparty",
    "data_origin",
    "sort",
}
_REPEATABLE = {"kind", "direction", "outcome", "data_origin"}


@router.get(
    "/{public_id}/activity",
    response_model=WalletCaseActivityListResponse,
)
def list_wallet_case_activity(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    session: Session = Depends(get_session),
) -> dict:
    """Read one pinned, bounded and deduplicated Activity revision."""
    response.headers["Cache-Control"] = "no-store"
    try:
        query = _activity_query(request)
        return WalletCaseActivityService(session).list_activity(public_id, query)
    except WalletCaseActivityInvalidCursor as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except WalletCaseActivityInvalidQuery as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except WalletCaseActivityNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseActivitySnapshotNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseActivitySnapshotConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except WalletCaseActivityScopeTooLarge as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "activity_storage_unavailable",
            "Wallet Case Activity storage is unavailable.",
            retryable=True,
        ) from exc


@router.get(
    "/{public_id}/activity/{activity_public_id}",
    response_model=WalletCaseActivityDetailResponse,
)
def read_wallet_case_activity(
    request: Request,
    response: Response,
    public_id: str = Path(..., pattern=_UUID_PATTERN, max_length=36),
    activity_public_id: str = Path(
        ...,
        pattern=_ACTIVITY_PATTERN,
        min_length=68,
        max_length=68,
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Read sanitized provenance for one item in a pinned revision."""
    response.headers["Cache-Control"] = "no-store"
    try:
        snapshot = _detail_snapshot(request)
        return WalletCaseActivityService(session).get_activity(
            public_id,
            activity_public_id,
            snapshot_public_id=snapshot,
        )
    except WalletCaseActivityInvalidQuery as exc:
        raise _error(422, exc.code, str(exc)) from exc
    except WalletCaseActivityNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseActivitySnapshotNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseActivityItemNotFound as exc:
        raise _error(404, exc.code, str(exc)) from exc
    except WalletCaseActivitySnapshotConflict as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except WalletCaseActivityScopeTooLarge as exc:
        raise _error(409, exc.code, str(exc)) from exc
    except SQLAlchemyError as exc:
        session.rollback()
        raise _error(
            503,
            "activity_storage_unavailable",
            "Wallet Case Activity storage is unavailable.",
            retryable=True,
        ) from exc


def _activity_query(request: Request) -> WalletCaseActivityQuery:
    pairs = request.query_params.multi_items()
    if any(name not in _LIST_PARAMETERS for name, _value in pairs):
        raise WalletCaseActivityInvalidQuery(
            "Wallet Case Activity received an unknown query parameter."
        )
    for name in _LIST_PARAMETERS - _REPEATABLE:
        if len(request.query_params.getlist(name)) > 1:
            raise WalletCaseActivityInvalidQuery(
                f"{name} must be provided at most once."
            )

    snapshot = _optional(request, "snapshot")
    if snapshot is not None and _UUID_RE.fullmatch(snapshot) is None:
        raise WalletCaseActivityInvalidQuery("snapshot must be a canonical UUID.")
    limit_text = _optional(request, "limit") or "50"
    if (
        not re.fullmatch(r"[1-9][0-9]{0,2}", limit_text)
        or int(limit_text, 10) > 100
    ):
        raise WalletCaseActivityInvalidQuery("limit must be from 1 through 100.")
    return WalletCaseActivityQuery(
        snapshot_public_id=snapshot,
        limit=int(limit_text, 10),
        cursor=_optional(request, "cursor"),
        kinds=tuple(request.query_params.getlist("kind")),
        directions=tuple(request.query_params.getlist("direction")),
        outcomes=tuple(request.query_params.getlist("outcome")),
        from_at=_timestamp(_optional(request, "from_at"), "from_at"),
        to_at=_timestamp(_optional(request, "to_at"), "to_at"),
        asset_id=_optional(request, "asset_id"),
        protocol_id=_optional(request, "protocol_id"),
        counterparty=_optional(request, "counterparty"),
        data_origins=tuple(request.query_params.getlist("data_origin")),
        sort=_optional(request, "sort") or "newest",
    )


def _detail_snapshot(request: Request) -> str:
    pairs = request.query_params.multi_items()
    if any(name != "snapshot" for name, _value in pairs):
        raise WalletCaseActivityInvalidQuery(
            "Activity detail accepts only the snapshot query parameter."
        )
    values = request.query_params.getlist("snapshot")
    if len(values) > 1:
        raise WalletCaseActivityInvalidQuery(
            "snapshot must be provided at most once."
        )
    if not values:
        raise WalletCaseActivityInvalidQuery(
            "Activity detail requires one pinned snapshot."
        )
    if _UUID_RE.fullmatch(values[0]) is None:
        raise WalletCaseActivityInvalidQuery("snapshot must be a canonical UUID.")
    return values[0]


def _optional(request: Request, name: str) -> str | None:
    value = request.query_params.get(name)
    if value is None:
        return None
    if not value or value != value.strip():
        raise WalletCaseActivityInvalidQuery(f"{name} cannot be empty or padded.")
    return value


def _timestamp(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    if _RFC3339_RE.fullmatch(value) is None:
        raise WalletCaseActivityInvalidQuery(
            f"{field} must be an RFC3339 timestamp."
        )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone is required")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise WalletCaseActivityInvalidQuery(
            f"{field} must be an RFC3339 timestamp."
        ) from exc


def _error(
    status_code: int,
    code: str,
    message: str,
    *,
    retryable: bool = False,
) -> HTTPException:
    headers = {"Cache-Control": "no-store"}
    if retryable:
        headers["Retry-After"] = "1"
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message_safe": message[:1000],
            "retryable": retryable,
        },
        headers=headers,
    )
