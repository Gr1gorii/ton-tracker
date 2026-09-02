"""Durable local execution for queued Wallet Case synchronization attempts.

The v0.72 execution contract intentionally reuses the existing monolithic
ingestion builder. It persists the job before provider I/O and fences the one
final result. Published stream checkpoints preserve safe continuation evidence,
but a crash during provider acquisition still repeats the bounded crawl until
the execution path consumes those checkpoints.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from queue import Queue
import secrets
from threading import Event, Lock, Thread
from typing import Any, Callable

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings
from adapters.wallet_activity import (
    TONAPI_EVENT_ACQUISITION_CONTRACT,
    TONAPI_TRANSACTION_ACQUISITION_CONTRACT,
)
from models import (
    CaseSync,
    WalletCase,
    WalletCaseCatalogEvent,
    WalletCaseStreamCheckpoint,
    WalletCaseSyncManifest,
)
from schemas import WalletIngestionPreviewRequest
from services.wallet_activity_ingestion import (
    WalletIngestionScopeMismatch,
    build_wallet_ingestion_run,
    wallet_ingestion_run_to_response,
)
from services.wallet_cases import (
    WalletCaseStreamCheckpointCorrupt,
    WalletCaseRuntimeConflict,
    WalletCaseService,
    _actual_provider,
    _bounded_message,
    _coverage_record,
    _json_dumps,
    _json_list,
    _sync_acquisition_plan,
    _summary_from_run,
    _sync_state,
    _stream_checkpoint_response,
)
from services.wallet_case_sync_manifests import (
    MANIFEST_CONTRACT_VERSION,
    build_wallet_case_sync_manifest,
)
from services.wallet_case_stream_checkpoints import (
    CHECKPOINT_CONTRACT_VERSION,
    build_wallet_case_stream_checkpoints,
)


LOGGER = logging.getLogger(__name__)
_RETRYABLE_CODES = {
    "provider_error",
    "provider_network_error",
    "provider_timeout",
    "provider_rate_limited",
    "provider_unavailable",
    "http_408",
    "http_425",
    "http_429",
    "http_500",
    "http_502",
    "http_503",
    "http_504",
}
_PERMANENT_CODES = {
    "protocol_error",
    "provider_protocol_error",
    "provider_not_configured",
    "invalid_request",
    "scope_mismatch",
}


class _CaseSyncStopRequested(RuntimeError):
    """Internal control signal; never published as a job failure."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_plan_instant(value: str) -> datetime:
    cleaned = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return _as_utc(datetime.fromisoformat(cleaned))


def _checkpoint(phase: str, *, retryable: bool = False) -> str:
    return json.dumps(
        {
            "version": "case_sync_monolithic_v1",
            "phase": phase,
            "last_error_retryable": retryable,
        },
        sort_keys=True,
        separators=(",", ":"),
    )


@dataclass(frozen=True)
class ClaimedCaseSync:
    id: int
    public_id: str
    case_id: int
    case_public_id: str
    lease_token: str
    attempt: int
    max_attempts: int
    network: str
    data_environment: str
    canonical_wallet_key: str
    display_address: str
    time_window: str
    requested_start: datetime
    requested_end: datetime
    requested_surfaces: tuple[str, ...]
    acquisition_mode: str
    acquisition_start: datetime
    acquisition_end: datetime
    acquisition_plan: dict[str, Any]
    source_checkpoint_public_id: str | None
    resume_stream_key: str | None
    resume_cursor: str | None
    resume_page_index: int | None
    resume_page_budget: int | None


class CaseSyncWorker:
    """Claim and execute at most one local SQLite CaseSync at a time."""

    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        settings_factory: Callable[[], Any] = get_settings,
        builder: Callable[..., Any] = build_wallet_ingestion_run,
        clock: Callable[[], datetime] = _utc_now,
        lease_seconds: int | None = None,
        heartbeat_seconds: int | None = None,
        retry_base_seconds: int | None = None,
        retry_cap_seconds: int | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.settings_factory = settings_factory
        self.builder = builder
        self.clock = clock
        settings = settings_factory()
        self.lease_seconds = max(
            30,
            int(lease_seconds or settings.wallet_case_job_lease_seconds),
        )
        configured_heartbeat = max(
            2,
            int(
                heartbeat_seconds
                or settings.wallet_case_job_heartbeat_seconds
            ),
        )
        self.heartbeat_seconds = min(
            configured_heartbeat,
            max(2, self.lease_seconds // 3),
        )
        self.retry_base_seconds = max(
            1,
            int(retry_base_seconds or settings.wallet_case_job_retry_base_seconds),
        )
        self.retry_cap_seconds = max(
            self.retry_base_seconds,
            int(retry_cap_seconds or settings.wallet_case_job_retry_cap_seconds),
        )
        self._stop_requested = Event()
        self._lifecycle_lock = Lock()

    def request_stop(self) -> None:
        """Stop extending leases so an interrupted job is restart-recoverable."""
        with self._lifecycle_lock:
            self._stop_requested.set()

    def reset_stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_requested.clear()

    def run_once(self) -> bool:
        if self._stop_requested.is_set():
            return False
        self.recover_expired()
        if self._stop_requested.is_set():
            return False
        claimed = self.claim_next()
        if claimed is None:
            return False
        if self._stop_requested.is_set():
            # The short claim is durable; do not begin new provider I/O. Its
            # lease will be reclaimed safely after restart.
            return True
        try:
            self.execute_claimed(claimed)
        except Exception as exc:
            # Do not publish raw exception text. A still-owned unexpected
            # failure becomes a safe terminal result; a lost lease is left for
            # recovery and fencing.
            LOGGER.error(
                "CaseSync worker execution failed safely (exception_type=%s)",
                type(exc).__name__,
            )
            self._fail_without_run(
                claimed,
                code="internal_job_error",
                message="Wallet Case synchronization stopped on an internal error.",
                retryable=False,
            )
        return True

    def recover_expired(self) -> int:
        now = _as_utc(self.clock())
        recovered = 0
        with self.session_factory() as session:
            cancelled = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.state == "running",
                    CaseSync.lease_expires_at.is_not(None),
                    CaseSync.lease_expires_at <= now,
                    CaseSync.cancel_requested_at.is_not(None),
                )
                .values(
                    state="cancelled",
                    stage="cancelled",
                    completed_at=now,
                    updated_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    next_attempt_at=None,
                    message_safe="Wallet Case synchronization was cancelled during recovery.",
                    checkpoint_json=_checkpoint("cancelled"),
                    status_version=CaseSync.status_version + 1,
                )
            )
            recovered += int(cancelled.rowcount or 0)
            exhausted = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.state == "running",
                    CaseSync.lease_expires_at.is_not(None),
                    CaseSync.lease_expires_at <= now,
                    CaseSync.cancel_requested_at.is_(None),
                    CaseSync.attempt_count >= CaseSync.max_attempts,
                )
                .values(
                    state="failed",
                    stage="failed",
                    completed_at=now,
                    updated_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    next_attempt_at=None,
                    error_code="worker_recovery_exhausted",
                    error_detail_safe=(
                        "The worker lease expired and the bounded retry budget "
                        "was exhausted."
                    ),
                    message_safe=(
                        "Synchronization failed after worker restart recovery."
                    ),
                    checkpoint_json=_checkpoint("failed", retryable=True),
                    status_version=CaseSync.status_version + 1,
                )
            )
            recovered += int(exhausted.rowcount or 0)
            retryable = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.state == "running",
                    CaseSync.lease_expires_at.is_not(None),
                    CaseSync.lease_expires_at <= now,
                    CaseSync.cancel_requested_at.is_(None),
                    CaseSync.attempt_count < CaseSync.max_attempts,
                )
                .values(
                    state="queued",
                    stage="retry_wait",
                    progress_current=0,
                    next_attempt_at=now,
                    updated_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code="worker_lease_expired",
                    error_detail_safe=(
                        "The previous worker stopped; the bounded crawl will "
                        "restart from its persisted request scope."
                    ),
                    message_safe="Synchronization is queued for restart recovery.",
                    checkpoint_json=_checkpoint("retry_wait", retryable=True),
                    status_version=CaseSync.status_version + 1,
                )
            )
            recovered += int(retryable.rowcount or 0)

            # Defensive cleanup for a queued retry that somehow reached its
            # budget before a worker could claim it.
            queued_exhausted = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.state == "queued",
                    CaseSync.stage == "retry_wait",
                    CaseSync.attempt_count >= CaseSync.max_attempts,
                )
                .values(
                    state="failed",
                    stage="failed",
                    completed_at=now,
                    updated_at=now,
                    next_attempt_at=None,
                    error_code="retry_budget_exhausted",
                    error_detail_safe="The bounded synchronization retry budget was exhausted.",
                    message_safe="Synchronization failed after bounded retries.",
                    checkpoint_json=_checkpoint("failed", retryable=True),
                    status_version=CaseSync.status_version + 1,
                )
            )
            recovered += int(queued_exhausted.rowcount or 0)
            session.commit()
        return recovered

    def claim_next(self) -> ClaimedCaseSync | None:
        if self._stop_requested.is_set():
            return None
        now = _as_utc(self.clock())
        with self.session_factory() as session:
            candidate_id = session.scalar(
                select(CaseSync.id)
                .where(
                    CaseSync.state == "queued",
                    CaseSync.cancel_requested_at.is_(None),
                    CaseSync.attempt_count < CaseSync.max_attempts,
                    CaseSync.next_attempt_at.is_not(None),
                    CaseSync.next_attempt_at <= now,
                )
                .order_by(
                    CaseSync.next_attempt_at.asc(),
                    CaseSync.created_at.asc(),
                    CaseSync.id.asc(),
                )
                .limit(1)
            )
            if candidate_id is None:
                session.rollback()
                return None
            if self._stop_requested.is_set():
                session.rollback()
                return None
            lease_token = secrets.token_hex(32)
            claimed = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.id == candidate_id,
                    CaseSync.state == "queued",
                    CaseSync.cancel_requested_at.is_(None),
                    CaseSync.attempt_count < CaseSync.max_attempts,
                    CaseSync.next_attempt_at <= now,
                )
                .values(
                    state="running",
                    stage="validating",
                    progress_current=0,
                    attempt_count=CaseSync.attempt_count + 1,
                    next_attempt_at=None,
                    lease_token=lease_token,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    heartbeat_at=now,
                    started_at=func.coalesce(CaseSync.started_at, now),
                    updated_at=now,
                    error_code=None,
                    error_detail_safe=None,
                    message_safe="Validating the persisted Wallet Case sync scope.",
                    checkpoint_json=_checkpoint("validating"),
                    status_version=CaseSync.status_version + 1,
                )
            )
            if claimed.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            row = session.execute(
                select(CaseSync, WalletCase)
                .join(WalletCase, WalletCase.id == CaseSync.case_id)
                .where(
                    CaseSync.id == candidate_id,
                    CaseSync.lease_token == lease_token,
                    WalletCase.archived_at.is_(None),
                )
            ).one_or_none()
            if row is None:
                session.rollback()
                self._close_unavailable_claim(candidate_id, lease_token)
                return None
            case_sync, wallet_case = row
            acquisition_plan = _sync_acquisition_plan(case_sync)
            return ClaimedCaseSync(
                id=case_sync.id,
                public_id=case_sync.public_id,
                case_id=wallet_case.id,
                case_public_id=wallet_case.public_id,
                lease_token=lease_token,
                attempt=case_sync.attempt_count,
                max_attempts=case_sync.max_attempts,
                network=wallet_case.network,
                data_environment=wallet_case.data_environment,
                canonical_wallet_key=wallet_case.canonical_wallet_key,
                display_address=wallet_case.display_address,
                time_window=case_sync.time_window,
                requested_start=_as_utc(case_sync.requested_start),
                requested_end=_as_utc(case_sync.requested_end),
                requested_surfaces=tuple(
                    _json_list(case_sync.requested_surfaces_json)
                ),
                acquisition_mode=acquisition_plan["mode"],
                acquisition_start=_parse_plan_instant(
                    acquisition_plan["start_at"]
                ),
                acquisition_end=_parse_plan_instant(
                    acquisition_plan["end_at"]
                ),
                acquisition_plan=acquisition_plan,
                source_checkpoint_public_id=acquisition_plan.get(
                    "source_checkpoint_public_id"
                ),
                resume_stream_key=acquisition_plan.get("resume_stream_key"),
                resume_cursor=acquisition_plan.get("resume_cursor"),
                resume_page_index=acquisition_plan.get("resume_page_index"),
                resume_page_budget=acquisition_plan.get(
                    "resume_page_budget"
                ),
            )

    def _close_unavailable_claim(self, sync_id: int, lease_token: str) -> bool:
        """Release an active slot when its parent case vanished/was archived."""
        now = _as_utc(self.clock())
        with self.session_factory() as session:
            result = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.id == sync_id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == lease_token,
                    CaseSync.lease_expires_at > now,
                )
                .values(
                    state="failed",
                    stage="failed",
                    completed_at=now,
                    updated_at=now,
                    next_attempt_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code="case_unavailable",
                    error_detail_safe=(
                        "The Wallet Case was archived or removed before execution."
                    ),
                    message_safe="Synchronization stopped because its case is unavailable.",
                    checkpoint_json=_checkpoint("failed"),
                    status_version=CaseSync.status_version + 1,
                )
            )
            session.commit()
            return result.rowcount == 1

    def execute_claimed(self, claimed: ClaimedCaseSync) -> None:
        try:
            settings = self._validated_settings(claimed)
        except (WalletCaseRuntimeConflict, ValueError) as exc:
            self._fail_without_run(
                claimed,
                code="runtime_scope_conflict",
                message=_bounded_message(str(exc))
                or "Runtime configuration cannot execute this Wallet Case scope.",
                retryable=False,
            )
            return

        if self._stop_requested.is_set():
            return

        if not self._advance_to_ingestion(claimed):
            return
        acquisition_window = (
            "custom"
            if claimed.acquisition_mode in {"incremental", "resume"}
            else claimed.time_window
        )
        payload = WalletIngestionPreviewRequest(
            wallet_address=claimed.display_address,
            time_window=acquisition_window,
            custom_start=(
                claimed.acquisition_start.isoformat()
                if acquisition_window == "custom"
                else None
            ),
            custom_end=(
                claimed.acquisition_end.isoformat()
                if acquisition_window == "custom"
                else None
            ),
            surfaces=list(claimed.requested_surfaces),
        )

        try:
            run, owned, cancellation_seen = self._build_with_heartbeats(
                claimed,
                payload,
                settings,
            )
        except _CaseSyncStopRequested:
            return
        except WalletIngestionScopeMismatch as exc:
            self._fail_without_run(
                claimed,
                code="scope_mismatch",
                message=_bounded_message(str(exc))
                or "The ingestion result did not match the Wallet Case scope.",
                retryable=False,
            )
            return
        except ValueError as exc:
            self._fail_without_run(
                claimed,
                code="invalid_request",
                message=_bounded_message(str(exc))
                or "The bounded synchronization request is invalid.",
                retryable=False,
            )
            return

        if not owned:
            return
        if cancellation_seen or self._cancel_requested(claimed):
            self._finish_cancelled(claimed)
            return

        if getattr(run, "status", None) not in {"success", "partial", "error"}:
            self._fail_without_run(
                claimed,
                code="invalid_builder_status",
                message="The ingestion builder returned a non-terminal status.",
                retryable=False,
            )
            return

        run_response = wallet_ingestion_run_to_response(run)
        retryable, retry_code = _retry_signal(run_response)
        # A partial run is already a useful immutable snapshot. Publish it
        # with honest coverage instead of discarding successful surfaces just
        # because another surface emitted a retryable provider signal.
        if (
            run.status == "error"
            and retryable
            and claimed.attempt < claimed.max_attempts
        ):
            self._schedule_retry(
                claimed,
                code=retry_code,
                message=_bounded_message(run_response.get("message"))
                or "The provider crawl failed temporarily; a bounded retry is scheduled.",
            )
            return

        if not self._advance_to_finalizing(claimed):
            return
        self._publish_final_run(
            claimed,
            run,
            run_response,
            settings,
            last_error_retryable=retryable,
        )

    def _validated_settings(self, claimed: ClaimedCaseSync):
        with self.session_factory() as session:
            wallet_case = session.scalar(
                select(WalletCase).where(
                    WalletCase.id == claimed.case_id,
                    WalletCase.public_id == claimed.case_public_id,
                    WalletCase.archived_at.is_(None),
                )
            )
            if wallet_case is None:
                raise WalletCaseRuntimeConflict("Wallet Case is no longer available.")
            scope = (
                wallet_case.network,
                wallet_case.data_environment,
                wallet_case.canonical_wallet_key,
                wallet_case.display_address,
            )
            expected = (
                claimed.network,
                claimed.data_environment,
                claimed.canonical_wallet_key,
                claimed.display_address,
            )
            if scope != expected:
                raise WalletCaseRuntimeConflict(
                    "Wallet Case scope changed after this job was queued."
                )
            settings = WalletCaseService(session)._settings_for_case(
                wallet_case,
                self.settings_factory(),
            )
            self._validate_resume_checkpoint(session, wallet_case, claimed)
            session.rollback()
            return settings

    def _validate_resume_checkpoint(
        self,
        session: Session,
        wallet_case: WalletCase,
        claimed: ClaimedCaseSync,
    ) -> None:
        resume_values = (
            claimed.source_checkpoint_public_id,
            claimed.resume_stream_key,
            claimed.resume_cursor,
            claimed.resume_page_index,
            claimed.resume_page_budget,
        )
        if claimed.acquisition_mode != "resume":
            if any(value is not None for value in resume_values):
                raise WalletCaseRuntimeConflict(
                    "Non-resume sync contains provider continuation state."
                )
            return
        if any(value is None for value in resume_values[:4]):
            raise WalletCaseRuntimeConflict(
                "Checkpoint continuation state is incomplete."
            )
        plan_version = claimed.acquisition_plan.get("version")
        if (
            plan_version in {4, 5}
            and (
                type(claimed.resume_page_budget) is not int
                or not 1 <= claimed.resume_page_budget <= 10
            )
        ) or (
            plan_version not in {4, 5} and claimed.resume_page_budget is not None
        ):
            raise WalletCaseRuntimeConflict(
                "Checkpoint continuation page budget is invalid."
            )
        checkpoint = session.scalar(
            select(WalletCaseStreamCheckpoint).where(
                WalletCaseStreamCheckpoint.case_id == wallet_case.id,
                WalletCaseStreamCheckpoint.public_id
                == claimed.source_checkpoint_public_id,
            )
        )
        if checkpoint is None:
            raise WalletCaseRuntimeConflict(
                "The source stream checkpoint is no longer available."
            )
        latest_id = session.scalar(
            select(func.max(WalletCaseStreamCheckpoint.id)).where(
                WalletCaseStreamCheckpoint.case_id == wallet_case.id,
                WalletCaseStreamCheckpoint.provider == checkpoint.provider,
                WalletCaseStreamCheckpoint.stream_key == checkpoint.stream_key,
            )
        )
        try:
            checkpoint_response = _stream_checkpoint_response(
                checkpoint,
                case_public_id=wallet_case.public_id,
            )
        except WalletCaseStreamCheckpointCorrupt as exc:
            raise WalletCaseRuntimeConflict(
                "The source stream checkpoint failed integrity validation."
            ) from exc
        document = checkpoint_response["document"]
        expected_contract = {
            "transactions": TONAPI_TRANSACTION_ACQUISITION_CONTRACT,
            "account_events": TONAPI_EVENT_ACQUISITION_CONTRACT,
        }.get(claimed.resume_stream_key)
        source_sync = checkpoint.source_sync
        source_surfaces = set(_json_list(source_sync.requested_surfaces_json))
        expected_surfaces = (
            {"transactions"}
            if claimed.resume_stream_key == "transactions"
            else source_surfaces & {"transfers", "swaps"}
        )
        requested_period = document.get("requested_period")
        if not isinstance(requested_period, dict):
            requested_period = {}
        try:
            period_start = _parse_plan_instant(requested_period["start_at"])
            period_end = _parse_plan_instant(requested_period["end_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WalletCaseRuntimeConflict(
                "The source stream checkpoint period is invalid."
            ) from exc
        if (
            latest_id != checkpoint.id
            or checkpoint.resume_state != "ready"
            or checkpoint.provider != "tonapi"
            or checkpoint.stream_key != claimed.resume_stream_key
            or checkpoint.provider_contract_version != expected_contract
            or checkpoint.continuation_cursor != claimed.resume_cursor
            or checkpoint.continuation_page_index != claimed.resume_page_index
            or source_sync.public_id
            != claimed.acquisition_plan["base_snapshot_public_id"]
            or source_sync.state not in {"partial", "succeeded"}
            or source_sync.ingestion_run_id is None
            or set(claimed.requested_surfaces) != expected_surfaces
            or period_start != claimed.acquisition_start
            or period_end != claimed.acquisition_end
        ):
            raise WalletCaseRuntimeConflict(
                "The source stream checkpoint no longer matches this resume job."
            )

    def _advance_to_ingestion(self, claimed: ClaimedCaseSync) -> bool:
        return self._advance(
            claimed,
            stage="ingesting",
            progress=1,
            message="Acquiring and normalizing the bounded provider response.",
        )

    def _advance_to_finalizing(self, claimed: ClaimedCaseSync) -> bool:
        return self._advance(
            claimed,
            stage="finalizing",
            progress=2,
            message="Calculating coverage and finalizing the case snapshot.",
        )

    def _advance(
        self,
        claimed: ClaimedCaseSync,
        *,
        stage: str,
        progress: int,
        message: str,
    ) -> bool:
        now = _as_utc(self.clock())
        with self.session_factory() as session:
            result = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.id == claimed.id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == claimed.lease_token,
                    CaseSync.lease_expires_at > now,
                    CaseSync.cancel_requested_at.is_(None),
                )
                .values(
                    stage=stage,
                    progress_current=progress,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    updated_at=now,
                    message_safe=message,
                    checkpoint_json=_checkpoint(stage),
                    status_version=CaseSync.status_version + 1,
                )
            )
            session.commit()
            updated = result.rowcount == 1
        if not updated:
            self._finish_cancelled(claimed)
        return updated

    def _build_with_heartbeats(
        self,
        claimed: ClaimedCaseSync,
        payload: WalletIngestionPreviewRequest,
        settings,
    ) -> tuple[Any, bool, bool]:
        if self._stop_requested.is_set():
            raise _CaseSyncStopRequested
        outcome: Queue[tuple[bool, Any]] = Queue(maxsize=1)

        def build() -> None:
            try:
                result = self.builder(
                    payload,
                    settings,
                    now=claimed.acquisition_end,
                    expected_data_mode=(
                        "mock" if claimed.data_environment == "demo" else "real"
                    ),
                    expected_network=claimed.network,
                    expected_canonical_wallet_key=claimed.canonical_wallet_key,
                    resume_stream_key=claimed.resume_stream_key,
                    resume_cursor=claimed.resume_cursor,
                    resume_page_index=claimed.resume_page_index,
                    resume_page_budget=claimed.resume_page_budget,
                )
                outcome.put((True, result))
            except Exception as exc:  # forwarded without logging provider detail
                outcome.put((False, exc))

        thread = Thread(
            target=build,
            name=f"case-sync-build-{claimed.public_id[:8]}",
            daemon=True,
        )
        with self._lifecycle_lock:
            if self._stop_requested.is_set():
                raise _CaseSyncStopRequested
            thread.start()
        owned = True
        cancellation_seen = False
        while thread.is_alive():
            thread.join(timeout=self.heartbeat_seconds)
            if thread.is_alive():
                if self._stop_requested.is_set():
                    owned = False
                    # The monolithic provider call cannot be killed safely.
                    # Its detached result is discarded once it returns, while
                    # the persisted lease is left for restart recovery.
                    thread.join()
                    break
                owned, cancel_requested = self._heartbeat(claimed)
                cancellation_seen = cancellation_seen or cancel_requested
                if not owned:
                    # The provider call cannot be killed safely. Wait for it,
                    # then discard its detached result under the lease fence.
                    thread.join()
                    break
        if self._stop_requested.is_set():
            owned = False
        if outcome.empty():
            raise RuntimeError("The provider worker stopped unexpectedly.")
        succeeded, value = outcome.get()
        if not succeeded:
            if isinstance(value, Exception):
                raise value
            raise RuntimeError("The provider worker stopped unexpectedly.")
        return value, owned, cancellation_seen

    def _heartbeat(self, claimed: ClaimedCaseSync) -> tuple[bool, bool]:
        now = _as_utc(self.clock())
        with self.session_factory() as session:
            row = session.execute(
                select(CaseSync.cancel_requested_at)
                .where(
                    CaseSync.id == claimed.id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == claimed.lease_token,
                    CaseSync.lease_expires_at > now,
                )
            ).one_or_none()
            if row is None:
                session.rollback()
                return False, False
            refreshed = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.id == claimed.id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == claimed.lease_token,
                    CaseSync.lease_expires_at > now,
                )
                .values(
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                )
            )
            session.commit()
            return refreshed.rowcount == 1, row[0] is not None

    def _cancel_requested(self, claimed: ClaimedCaseSync) -> bool:
        now = _as_utc(self.clock())
        with self.session_factory() as session:
            requested = session.scalar(
                select(CaseSync.cancel_requested_at).where(
                    CaseSync.id == claimed.id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == claimed.lease_token,
                    CaseSync.lease_expires_at > now,
                )
            )
            session.rollback()
            return requested is not None

    def _schedule_retry(
        self,
        claimed: ClaimedCaseSync,
        *,
        code: str,
        message: str,
    ) -> bool:
        now = _as_utc(self.clock())
        retry_at = now + timedelta(seconds=self._retry_delay(claimed))
        with self.session_factory() as session:
            result = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.id == claimed.id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == claimed.lease_token,
                    CaseSync.lease_expires_at > now,
                    CaseSync.cancel_requested_at.is_(None),
                    CaseSync.attempt_count < CaseSync.max_attempts,
                )
                .values(
                    state="queued",
                    stage="retry_wait",
                    progress_current=0,
                    next_attempt_at=retry_at,
                    lease_token=None,
                    lease_expires_at=None,
                    heartbeat_at=now,
                    updated_at=now,
                    error_code=code[:64],
                    error_detail_safe=message,
                    message_safe=message,
                    checkpoint_json=_checkpoint("retry_wait", retryable=True),
                    status_version=CaseSync.status_version + 1,
                )
            )
            session.commit()
            updated = result.rowcount == 1
        if not updated:
            self._finish_cancelled(claimed)
        return updated

    def _retry_delay(self, claimed: ClaimedCaseSync) -> float:
        exponential = min(
            self.retry_cap_seconds,
            self.retry_base_seconds * (2 ** max(0, claimed.attempt - 1)),
        )
        digest = hashlib.sha256(
            f"{claimed.public_id}:{claimed.attempt}".encode("ascii")
        ).digest()
        jitter_fraction = int.from_bytes(digest[:2], "big") / 65535
        return min(
            self.retry_cap_seconds,
            exponential + (exponential * 0.25 * jitter_fraction),
        )

    def _finish_cancelled(self, claimed: ClaimedCaseSync) -> bool:
        now = _as_utc(self.clock())
        with self.session_factory() as session:
            result = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.id == claimed.id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == claimed.lease_token,
                    CaseSync.lease_expires_at > now,
                    CaseSync.cancel_requested_at.is_not(None),
                )
                .values(
                    state="cancelled",
                    stage="cancelled",
                    completed_at=now,
                    updated_at=now,
                    next_attempt_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    message_safe="Wallet Case synchronization was cancelled safely.",
                    checkpoint_json=_checkpoint("cancelled"),
                    status_version=CaseSync.status_version + 1,
                )
            )
            session.commit()
            return result.rowcount == 1

    def _fail_without_run(
        self,
        claimed: ClaimedCaseSync,
        *,
        code: str,
        message: str,
        retryable: bool,
    ) -> bool:
        now = _as_utc(self.clock())
        with self.session_factory() as session:
            result = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.id == claimed.id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == claimed.lease_token,
                    CaseSync.lease_expires_at > now,
                    CaseSync.cancel_requested_at.is_(None),
                )
                .values(
                    state="failed",
                    stage="failed",
                    completed_at=now,
                    updated_at=now,
                    next_attempt_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code=code[:64],
                    error_detail_safe=message,
                    message_safe=message,
                    checkpoint_json=_checkpoint("failed", retryable=retryable),
                    status_version=CaseSync.status_version + 1,
                )
            )
            session.commit()
            updated = result.rowcount == 1
        if not updated:
            self._finish_cancelled(claimed)
        return updated

    def _publish_final_run(
        self,
        claimed: ClaimedCaseSync,
        run,
        run_response: dict[str, Any],
        settings,
        *,
        last_error_retryable: bool,
    ) -> bool:
        now = _as_utc(self.clock())
        state, stage = _sync_state(run.status)
        coverage = _coverage_record(
            run_response,
            start_at=claimed.requested_start,
            end_at=claimed.requested_end,
            state=state,
            requested_surfaces=list(claimed.requested_surfaces),
            acquisition_plan=claimed.acquisition_plan,
        )
        summary = _summary_from_run(run_response)
        message = _bounded_message(run_response.get("message"))
        if not message:
            message = "Wallet Case synchronization completed without a provider message."
        error_code = None
        error_detail = None
        if state == "failed":
            _retryable, classified_code = _retry_signal(run_response)
            error_code = classified_code or "ingestion_failed"
            error_detail = message
        actual_provider = _actual_provider(run_response, settings)
        built_manifest = build_wallet_case_sync_manifest(
            case_public_id=claimed.case_public_id,
            sync_public_id=claimed.public_id,
            network=claimed.network,
            data_mode=str(getattr(run, "data_mode", "unknown")),
            provider=actual_provider,
            sync_state=state,
            snapshot_start=claimed.requested_start,
            snapshot_end=claimed.requested_end,
            acquisition_plan=claimed.acquisition_plan,
            requested_surfaces=claimed.requested_surfaces,
            run_response=run_response,
        )
        built_checkpoints = build_wallet_case_stream_checkpoints(
            built_manifest
        )

        with self.session_factory() as session:
            wallet_case = session.scalar(
                select(WalletCase).where(
                    WalletCase.id == claimed.case_id,
                    WalletCase.public_id == claimed.case_public_id,
                    WalletCase.archived_at.is_(None),
                    WalletCase.network == claimed.network,
                    WalletCase.data_environment == claimed.data_environment,
                    WalletCase.canonical_wallet_key == claimed.canonical_wallet_key,
                    WalletCase.display_address == claimed.display_address,
                )
            )
            if wallet_case is None:
                session.rollback()
                return self._fail_without_run(
                    claimed,
                    code="scope_mismatch",
                    message="Wallet Case scope changed before result publication.",
                    retryable=False,
                )
            session.add(run)
            session.flush()
            fenced = session.execute(
                update(CaseSync)
                .where(
                    CaseSync.id == claimed.id,
                    CaseSync.case_id == claimed.case_id,
                    CaseSync.state == "running",
                    CaseSync.lease_token == claimed.lease_token,
                    CaseSync.lease_expires_at > now,
                    CaseSync.cancel_requested_at.is_(None),
                    CaseSync.ingestion_run_id.is_(None),
                )
                .values(
                    ingestion_run_id=run.id,
                    provider=actual_provider,
                    state=state,
                    stage=stage,
                    progress_current=3,
                    progress_total=3,
                    coverage_summary_json=_json_dumps(coverage),
                    result_summary_json=_json_dumps(summary),
                    message_safe=message,
                    error_code=error_code,
                    error_detail_safe=error_detail,
                    completed_at=now,
                    updated_at=now,
                    next_attempt_at=None,
                    lease_token=None,
                    lease_expires_at=None,
                    heartbeat_at=now,
                    checkpoint_json=_checkpoint(
                        stage,
                        retryable=last_error_retryable,
                    ),
                    status_version=CaseSync.status_version + 1,
                )
            )
            if fenced.rowcount != 1:
                session.rollback()
                published = False
            else:
                session.add(
                    WalletCaseSyncManifest(
                        public_id=built_manifest.public_id,
                        case_sync_id=claimed.id,
                        contract_version=MANIFEST_CONTRACT_VERSION,
                        content_hash_sha256=(
                            built_manifest.content_hash_sha256
                        ),
                        manifest_json=built_manifest.canonical_json,
                        created_at=now,
                    )
                )
                session.add_all(
                    [
                        WalletCaseStreamCheckpoint(
                            public_id=checkpoint.public_id,
                            case_id=claimed.case_id,
                            source_sync_id=claimed.id,
                            contract_version=CHECKPOINT_CONTRACT_VERSION,
                            provider=checkpoint.provider,
                            stream_key=checkpoint.stream_key,
                            provider_contract_version=(
                                checkpoint.provider_contract_version
                            ),
                            resume_state=checkpoint.resume_state,
                            continuation_cursor=(
                                checkpoint.continuation_cursor
                            ),
                            continuation_page_index=(
                                checkpoint.continuation_page_index
                            ),
                            page_count=checkpoint.page_count,
                            pages_succeeded=checkpoint.pages_succeeded,
                            checkpoint_hash_sha256=(
                                checkpoint.checkpoint_hash_sha256
                            ),
                            checkpoint_json=checkpoint.canonical_json,
                            created_at=now,
                        )
                        for checkpoint in built_checkpoints
                    ]
                )
                wallet_case.updated_at = now
                session.add(
                    WalletCaseCatalogEvent(
                        case=wallet_case,
                        recorded_at=now,
                        visible=True,
                    )
                )
                session.commit()
                published = True
        if not published:
            self._finish_cancelled(claimed)
        return published


class LocalCaseSyncJobRunner:
    """One wakeable daemon loop for the local-single-user deployment profile."""

    def __init__(
        self,
        worker: CaseSyncWorker,
        *,
        poll_milliseconds: int = 500,
    ) -> None:
        self.worker = worker
        self.poll_seconds = max(0.1, min(15.0, poll_milliseconds / 1000))
        self._wake = Event()
        self._stop = Event()
        self._thread: Thread | None = None

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        self.worker.reset_stop()
        self._thread = Thread(
            target=self._run,
            name="wallet-case-sync-runner",
            daemon=True,
        )
        self._thread.start()

    def notify(self) -> None:
        self._wake.set()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self.worker.request_stop()
        self._wake.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.0, timeout))

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                worked = self.worker.run_once()
            except Exception as exc:
                LOGGER.error(
                    "CaseSync runner iteration failed safely (exception_type=%s)",
                    type(exc).__name__,
                )
                worked = False
            if worked:
                continue
            self._wake.wait(self.poll_seconds)
            self._wake.clear()


def _retry_signal(run_response: dict[str, Any]) -> tuple[bool, str]:
    stream_codes = {
        str(stream.get("error_code"))
        for stream in run_response.get("acquisition_streams", [])
        if isinstance(stream, dict) and stream.get("error_code")
    }
    if stream_codes & _PERMANENT_CODES:
        return False, sorted(stream_codes & _PERMANENT_CODES)[0]
    retryable_codes = stream_codes & _RETRYABLE_CODES
    if retryable_codes:
        return True, sorted(retryable_codes)[0]
    if run_response.get("status") == "error":
        return True, "provider_error"
    evidence = run_response.get("provider_evidence")
    if isinstance(evidence, list) and any(
        isinstance(item, dict) and item.get("source_status") == "error"
        for item in evidence
    ):
        return True, "provider_error"
    return False, ""


__all__ = [
    "CaseSyncWorker",
    "ClaimedCaseSync",
    "LocalCaseSyncJobRunner",
]
