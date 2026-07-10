"""Wallet activity ingestion API routes."""

from __future__ import annotations

import json
import re

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session

from database import get_session
from schemas import WalletClusterCompareRequest, WalletClusterCompareResponse
from schemas import WalletHistoryReadinessRequest, WalletHistoryReadinessResponse
from schemas import WalletIngestionPreviewRequest, WalletIngestionPreviewResponse
from schemas import (
    WalletIngestionRunCatalogResponse,
    WalletIngestionRunResponse,
    WalletRunSignalsResponse,
    WalletTransactionTraceEvidenceResponse,
)
from schemas import WalletRunPnlPreviewResponse
from services import export
from services.pnl_preview import derive_run_pnl_preview
from services.pnl_unrealized import derive_run_pnl_preview_with_unrealized
from services.pnl_usd_valuation import derive_run_pnl_preview_with_historical
from services.wallet_activity_clustering import compare_wallet_activity
from services.wallet_history_readiness import build_wallet_history_readiness
from services.wallet_activity_signals import derive_run_signals
from services.wallet_activity_ingestion import (
    build_wallet_ingestion_preview,
    get_wallet_ingestion_run,
    list_wallet_ingestion_runs,
    persist_mock_wallet_ingestion,
)
from services.wallet_trace_evidence import (
    WalletTraceEvidenceIneligible,
    WalletTraceEvidenceNotFound,
    WalletTraceEvidenceProviderFailure,
    get_wallet_transaction_trace_evidence,
)

router = APIRouter(prefix="/api/wallets", tags=["wallet-activity"])
_MAX_SQLITE_RUN_ID = 2**63 - 1
_MAX_RUN_CATALOG_LIMIT = 50
_CANONICAL_RUN_ID_RE = re.compile(r"^[1-9][0-9]{0,18}$")
_CANONICAL_TRACE_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


def _derive_pnl_preview(
    result: dict,
    *,
    include_historical: bool,
    include_unrealized: bool,
) -> dict:
    if include_unrealized:
        return derive_run_pnl_preview_with_unrealized(result)
    if include_historical:
        return derive_run_pnl_preview_with_historical(result)
    return derive_run_pnl_preview(result)


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


def _canonical_positive_integer(
    raw_value: str,
    *,
    field_name: str,
    maximum: int,
) -> int:
    value = int(raw_value, 10)
    if value > maximum:
        raise HTTPException(
            status_code=422,
            detail=f"{field_name} must be a canonical positive integer no greater than {maximum}",
        )
    return value


@router.get(
    "/ingest",
    response_model=WalletIngestionRunCatalogResponse,
)
def read_wallet_ingestion_run_catalog(
    request: Request,
    response: Response,
    limit: str = Query(
        "8",
        pattern=r"^[1-9][0-9]*$",
        max_length=2,
        description="Canonical page size from 1 through 50.",
    ),
    session: Session = Depends(get_session),
) -> dict:
    """List a bounded newest-first page of persisted runs without ingestion."""
    query_pairs = request.query_params.multi_items()
    if any(name != "limit" for name, _value in query_pairs):
        raise HTTPException(
            status_code=422,
            detail="wallet run catalog accepts only the limit query parameter",
        )
    if len(request.query_params.getlist("limit")) > 1:
        raise HTTPException(
            status_code=422,
            detail="wallet run catalog limit must be provided at most once",
        )
    canonical_limit = _canonical_positive_integer(
        limit,
        field_name="limit",
        maximum=_MAX_RUN_CATALOG_LIMIT,
    )
    response.headers["Cache-Control"] = "no-store"
    return list_wallet_ingestion_runs(
        limit=canonical_limit,
        session=session,
    )


@router.get(
    "/ingest/{run_id}",
    response_model=WalletIngestionRunResponse,
)
def read_wallet_ingestion_run(
    run_id: str = Path(
        ...,
        pattern=r"^[1-9][0-9]*$",
        max_length=19,
        description="Canonical positive persisted run id.",
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Read one persisted wallet ingestion run."""
    canonical_run_id = _canonical_positive_integer(
        run_id,
        field_name="run_id",
        maximum=_MAX_SQLITE_RUN_ID,
    )
    result = get_wallet_ingestion_run(canonical_run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    return result


@router.get(
    "/ingest/{run_id}/transactions/{transaction_hash}/trace-evidence",
    response_model=WalletTransactionTraceEvidenceResponse,
)
def read_wallet_transaction_trace_evidence(
    response: Response,
    run_id: str = Path(
        ...,
        description="Canonical positive persisted run id.",
    ),
    transaction_hash: str = Path(
        ...,
        description="Canonical lowercase persisted transaction hash.",
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Inspect one bounded provider trace without persistence or reconstruction."""
    no_store_headers = {"Cache-Control": "no-store"}
    response.headers.update(no_store_headers)
    if _CANONICAL_RUN_ID_RE.fullmatch(run_id) is None:
        raise HTTPException(
            status_code=422,
            detail="run_id must be a canonical positive signed 64-bit integer",
            headers=no_store_headers,
        )
    if _CANONICAL_TRACE_HASH_RE.fullmatch(transaction_hash) is None:
        raise HTTPException(
            status_code=422,
            detail="transaction_hash must be canonical lowercase 32-byte hex",
            headers=no_store_headers,
        )
    canonical_run_id = int(run_id, 10)
    if canonical_run_id > _MAX_SQLITE_RUN_ID:
        raise HTTPException(
            status_code=422,
            detail="run_id must be a canonical positive signed 64-bit integer",
            headers=no_store_headers,
        )
    try:
        return get_wallet_transaction_trace_evidence(
            canonical_run_id,
            transaction_hash,
            session,
        )
    except WalletTraceEvidenceNotFound as exc:
        raise HTTPException(
            status_code=404,
            detail=str(exc),
            headers=no_store_headers,
        ) from exc
    except WalletTraceEvidenceIneligible as exc:
        raise HTTPException(
            status_code=409,
            detail=str(exc),
            headers=no_store_headers,
        ) from exc
    except WalletTraceEvidenceProviderFailure as exc:
        raise HTTPException(
            status_code=502,
            detail=str(exc),
            headers=no_store_headers,
        ) from exc


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


@router.get(
    "/ingest/{run_id}/pnl-preview",
    response_model=WalletRunPnlPreviewResponse,
)
def read_wallet_ingestion_run_pnl_preview(
    run_id: int = Path(..., ge=1),
    include_historical: bool = Query(
        False,
        description=(
            "Also value TON-side swap legs at historical TON/USD points and "
            "derive in-window cost basis. Real PnL still requires every "
            "evidence requirement."
        ),
    ),
    include_unrealized: bool = Query(
        False,
        description=(
            "Also value remaining in-window holdings with deterministic mock "
            "pricing or real provider-reported spot prices (implies "
            "include_historical). Informational only; never part of realized "
            "figures or the Real-PnL checklist."
        ),
    ),
    session: Session = Depends(get_session),
) -> dict:
    """Return an estimated PnL preview for one persisted run.

    Estimate only -- never Real PnL unless every evidence requirement is
    met; missing evidence is reported explicitly. With
    ``include_historical=true`` the response also values TON-side swap legs
    in USD using historical price points; ``include_unrealized=true``
    additionally values remaining in-window holdings at spot prices.
    """
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    return _derive_pnl_preview(
        result,
        include_historical=include_historical,
        include_unrealized=include_unrealized,
    )


@router.get("/ingest/{run_id}/pnl-preview/export.json")
def export_wallet_ingestion_run_pnl_preview(
    run_id: int = Path(..., ge=1),
    include_historical: bool = Query(
        False,
        description=(
            "Include USD-valued swap legs and in-window realized cost-basis "
            "results computed from historical price points."
        ),
    ),
    include_unrealized: bool = Query(
        False,
        description=(
            "Include spot-based unrealized records and their priced subtotal "
            "(implies include_historical)."
        ),
    ),
    session: Session = Depends(get_session),
) -> Response:
    """Download the PnL preview for one persisted run as JSON.

    The locked-requirement checklist and missing-evidence reasons are always
    included; whether the payload amounts to Real PnL is decided solely by
    that checklist.
    """
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    preview = _derive_pnl_preview(
        result,
        include_historical=include_historical,
        include_unrealized=include_unrealized,
    )
    body = json.dumps(preview, ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename=wallet_pnl_preview_{run_id}.json"
            )
        },
    )


@router.get("/ingest/{run_id}/pnl-preview/export.csv")
def export_wallet_ingestion_run_pnl_preview_csv(
    run_id: int = Path(..., ge=1),
    include_historical: bool = Query(
        False,
        description=(
            "Include USD-valued swap legs and in-window realized cost-basis "
            "results computed from historical price points."
        ),
    ),
    include_unrealized: bool = Query(
        False,
        description=(
            "Include spot-based unrealized records plus optional coverage and "
            "priced-subtotal rows (implies include_historical)."
        ),
    ),
    session: Session = Depends(get_session),
) -> Response:
    """Download the PnL preview for one persisted run as CSV.

    One row per token flow, optional USD flow, realized cost-basis or
    unrealized record, optional unrealized coverage and priced-subtotal rows,
    and each Real-PnL requirement. Real PnL is decided solely by requirements.
    """
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    preview = _derive_pnl_preview(
        result,
        include_historical=include_historical,
        include_unrealized=include_unrealized,
    )
    return Response(
        content=export.wallet_pnl_preview_to_csv(preview),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=wallet_pnl_preview_{run_id}.csv"
            )
        },
    )


@router.get("/ingest/{run_id}/signals/export.json")
def export_wallet_ingestion_run_signals(
    run_id: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> Response:
    """Download rule-based evidence signals for one persisted run as JSON.

    Heuristic, explainable observations only -- not a risk score or a verdict.
    """
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    body = json.dumps(derive_run_signals(result), ensure_ascii=False, indent=2)
    return Response(
        content=body,
        media_type="application/json",
        headers={
            "Content-Disposition": (
                f"attachment; filename=wallet_run_signals_{run_id}.json"
            )
        },
    )


@router.get("/ingest/{run_id}/signals/export.csv")
def export_wallet_ingestion_run_signals_csv(
    run_id: int = Path(..., ge=1),
    session: Session = Depends(get_session),
) -> Response:
    """Download rule-based evidence signals for one persisted run as CSV.

    One row per signal or insufficient-evidence record; heuristic indicators
    only -- not a risk score or a verdict.
    """
    result = get_wallet_ingestion_run(run_id, session)
    if result is None:
        raise HTTPException(status_code=404, detail="Wallet ingestion run not found")
    return Response(
        content=export.wallet_run_signals_to_csv(derive_run_signals(result)),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f"attachment; filename=wallet_run_signals_{run_id}.csv"
            )
        },
    )


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
    "/history/readiness",
    response_model=WalletHistoryReadinessResponse,
)
def inspect_wallet_history_readiness(
    payload: WalletHistoryReadinessRequest,
    session: Session = Depends(get_session),
) -> dict:
    """Inspect multi-run history evidence without merging rows or changing PnL."""
    try:
        return build_wallet_history_readiness(
            payload.run_ids,
            payload.target_run_id,
            session,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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
