"""Durable local worker for selected Wallet Case transaction evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import logging
from queue import Queue
import secrets
from threading import Event, Lock, Thread
from typing import Any, Callable

from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker

from config import get_settings
from models import CaseEvidenceVerification, WalletCase
from services.wallet_case_activity import WalletCaseActivityService
from services.wallet_case_evidence import (
    CaseEvidenceRuntimeUnavailable,
    CaseEvidenceStoredConflict,
    _checkpoint,
    _canonical_inclusion_proven,
    _result_digest,
    _revalidated_artifacts,
    case_evidence_runtime_limitation,
)
from services.wallet_native_activity_ledger import (
    WalletNativeActivityLedgerConflict,
    WalletNativeActivityLedgerFailure,
    build_wallet_native_activity_ledger,
    get_wallet_native_activity_ledger,
)
from services.wallet_persisted_trace_evidence import (
    WalletPersistedTraceEvidenceConflict,
    WalletPersistedTraceEvidenceFailure,
    capture_persisted_wallet_transaction_trace_evidence,
    get_persisted_wallet_transaction_trace_evidence,
)
from services.wallet_trace_boc_verification import (
    WalletTraceBocVerificationConflict,
    WalletTraceBocVerificationFailure,
    get_wallet_transaction_trace_boc_verification,
    verify_wallet_transaction_trace_bocs,
)
from services.wallet_trace_evidence import (
    WalletTraceEvidenceIneligible,
    WalletTraceEvidenceNotFound,
    WalletTraceEvidenceProviderFailure,
)
from services.wallet_transaction_inclusion_proof import (
    WalletTransactionInclusionProofConflict,
    WalletTransactionInclusionProofFailure,
    WalletTransactionInclusionProofNotFound,
    create_wallet_transaction_inclusion_proofs,
    get_wallet_transaction_inclusion_proofs,
)


LOGGER = logging.getLogger(__name__)
_SAFE_DOMAIN_ERRORS = (
    WalletTraceEvidenceNotFound,
    WalletTraceEvidenceIneligible,
    WalletPersistedTraceEvidenceConflict,
    WalletTraceBocVerificationConflict,
    WalletTransactionInclusionProofNotFound,
    WalletTransactionInclusionProofConflict,
    WalletNativeActivityLedgerConflict,
    CaseEvidenceStoredConflict,
    CaseEvidenceRuntimeUnavailable,
)
_RETRYABLE_PROVIDER_CODES = frozenset(
    {
        "provider_error",
        "provider_network_error",
        "provider_timeout",
        "provider_rate_limited",
        "provider_unavailable",
        "http_429",
        "http_408",
        "http_425",
        "http_500",
        "http_502",
        "http_503",
        "http_504",
    }
)
_PERMANENT_PROVIDER_CODES = frozenset(
    {
        "protocol_error",
        "provider_protocol_error",
        "provider_not_configured",
        "invalid_request",
        "scope_mismatch",
    }
)
_RETRYABLE_OPERATION_ERRORS = (
    WalletPersistedTraceEvidenceFailure,
    WalletTraceBocVerificationFailure,
    WalletTransactionInclusionProofFailure,
    WalletNativeActivityLedgerFailure,
    SQLAlchemyError,
)


@dataclass(frozen=True)
class ClaimedEvidenceVerification:
    id: int
    public_id: str
    case_public_id: str
    snapshot_public_id: str
    activity_public_id: str
    source_sync_public_id: str
    source_run_id: int
    source_transaction_id: int
    transaction_hash: str
    network: str
    semantic_fingerprint: str
    lease_token: str
    attempt: int
    max_attempts: int


class _WorkerStop(RuntimeError):
    pass


class _EvidenceOperationCancelled(RuntimeError):
    pass


class CaseEvidenceInclusionTrustInsufficient(ValueError):
    code = "evidence_inclusion_trust_insufficient"


class CaseEvidenceWorker:
    def __init__(
        self,
        session_factory: sessionmaker,
        *,
        settings_factory: Callable[[], Any] = get_settings,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        lease_seconds: int | None = None,
        heartbeat_seconds: int | None = None,
        retry_base_seconds: int | None = None,
        retry_cap_seconds: int | None = None,
        capture: Callable[..., Any] = capture_persisted_wallet_transaction_trace_evidence,
        verify_bocs: Callable[..., Any] = verify_wallet_transaction_trace_bocs,
        prove_inclusion: Callable[..., Any] = create_wallet_transaction_inclusion_proofs,
        build_ledger: Callable[..., Any] = build_wallet_native_activity_ledger,
    ) -> None:
        self.session_factory = session_factory
        self.settings_factory = settings_factory
        self.clock = clock
        settings = settings_factory()
        self.lease_seconds = max(
            30, int(lease_seconds or settings.wallet_case_evidence_lease_seconds)
        )
        heartbeat = max(
            2,
            int(heartbeat_seconds or settings.wallet_case_evidence_heartbeat_seconds),
        )
        self.heartbeat_seconds = min(heartbeat, max(2, self.lease_seconds // 3))
        self.retry_base_seconds = max(
            1,
            int(retry_base_seconds or settings.wallet_case_evidence_retry_base_seconds),
        )
        self.retry_cap_seconds = max(
            self.retry_base_seconds,
            int(retry_cap_seconds or settings.wallet_case_evidence_retry_cap_seconds),
        )
        self.capture = capture
        self.verify_bocs = verify_bocs
        self.prove_inclusion = prove_inclusion
        self.build_ledger = build_ledger
        self._stop = Event()
        self._lock = Lock()
        self._active_cancellations: set[Event] = set()

    def request_stop(self) -> None:
        with self._lock:
            self._stop.set()
            for cancellation in self._active_cancellations:
                cancellation.set()

    def reset_stop(self) -> None:
        with self._lock:
            self._stop.clear()

    def run_once(self) -> bool:
        if self._stop.is_set():
            return False
        self.recover_expired()
        claimed = self.claim_next()
        if claimed is None:
            return False
        try:
            self.execute_claimed(claimed)
        except _WorkerStop:
            pass
        except SQLAlchemyError as exc:
            # If durable retry publication itself cannot reach storage, do not
            # overwrite the claimed job with an internal terminal result. Its
            # fenced lease is the recovery record and will be reclaimed after
            # expiry. Never log the database exception text.
            LOGGER.error(
                "Case evidence worker storage control failed safely "
                "(exception_type=%s)",
                type(exc).__name__,
            )
        except Exception as exc:
            LOGGER.error(
                "Case evidence worker failed safely (exception_type=%s)",
                type(exc).__name__,
            )
            try:
                self._finish_failure(
                    claimed,
                    code="internal_evidence_error",
                    message="Evidence verification stopped on an internal error.",
                )
            except Exception as terminal_exc:
                LOGGER.error(
                    "Case evidence terminalization failed safely (exception_type=%s)",
                    type(terminal_exc).__name__,
                )
        return True

    def recover_expired(self) -> int:
        now = self._now()
        with self.session_factory() as session:
            cancelled_ids = list(
                session.scalars(
                    select(CaseEvidenceVerification.id).where(
                    CaseEvidenceVerification.state == "running",
                    CaseEvidenceVerification.lease_expires_at.is_not(None),
                    CaseEvidenceVerification.lease_expires_at <= now,
                    CaseEvidenceVerification.cancel_requested_at.is_not(None),
                )
                )
            )
            retry = session.execute(
                update(CaseEvidenceVerification)
                .where(
                    CaseEvidenceVerification.state == "running",
                    CaseEvidenceVerification.lease_expires_at.is_not(None),
                    CaseEvidenceVerification.lease_expires_at <= now,
                    CaseEvidenceVerification.cancel_requested_at.is_(None),
                    CaseEvidenceVerification.attempt_count
                    < CaseEvidenceVerification.max_attempts,
                )
                .values(
                    state="queued",
                    stage="retry_wait",
                    next_attempt_at=now,
                    updated_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code="evidence_worker_lease_expired",
                    error_detail_safe=(
                        "The previous worker stopped; verification will resume "
                        "from the last revalidated artifact."
                    ),
                    message_safe="Evidence verification is queued for restart recovery.",
                    checkpoint_json=_checkpoint("retry_wait", retryable=True),
                    status_version=CaseEvidenceVerification.status_version + 1,
                )
            )
            exhausted = list(
                session.execute(
                    select(
                        CaseEvidenceVerification.id,
                        CaseEvidenceVerification.lease_token,
                        CaseEvidenceVerification.lease_expires_at,
                    ).where(
                        CaseEvidenceVerification.state == "running",
                        CaseEvidenceVerification.lease_expires_at.is_not(None),
                        CaseEvidenceVerification.lease_expires_at <= now,
                        CaseEvidenceVerification.cancel_requested_at.is_(None),
                        CaseEvidenceVerification.attempt_count
                        >= CaseEvidenceVerification.max_attempts,
                    )
                )
            )
            session.commit()
        cancelled_count = 0
        for job_id in cancelled_ids:
            cancelled_count += int(self._finish_recovered_cancel(job_id))
        exhausted_count = 0
        for job_id, lease_token, lease_expires_at in exhausted:
            exhausted_count += int(
                self._finish_expired(
                    job_id,
                    lease_token=lease_token,
                    lease_expires_at=lease_expires_at,
                    recovery_cutoff=now,
                )
            )
        return cancelled_count + int(retry.rowcount or 0) + exhausted_count

    def _finish_recovered_cancel(self, job_id: int) -> bool:
        with self.session_factory() as session:
            fenced = session.execute(
                update(CaseEvidenceVerification)
                .where(
                    CaseEvidenceVerification.id == job_id,
                    CaseEvidenceVerification.state == "running",
                    CaseEvidenceVerification.cancel_requested_at.is_not(None),
                )
                .values(updated_at=CaseEvidenceVerification.updated_at)
            )
            if fenced.rowcount != 1:
                session.rollback()
                return False
            job = session.scalar(
                select(CaseEvidenceVerification)
                .where(CaseEvidenceVerification.id == job_id)
                .with_for_update()
            )
            if job is None:
                session.rollback()
                return False
            self._terminal_cancel_row(
                job,
                session,
                message="Evidence verification was cancelled during recovery.",
            )
            return True

    def _finish_expired(
        self,
        job_id: int,
        *,
        lease_token: str | None,
        lease_expires_at: datetime,
        recovery_cutoff: datetime,
    ) -> bool:
        with self.session_factory() as session:
            # Acquire the same write fence used by cancel before deciding the
            # terminal outcome. On SQLite the no-op UPDATE obtains the writer
            # lock; databases with row-level locking additionally honor the
            # subsequent FOR UPDATE read.
            fenced = session.execute(
                update(CaseEvidenceVerification)
                .where(
                    CaseEvidenceVerification.id == job_id,
                    CaseEvidenceVerification.state == "running",
                    CaseEvidenceVerification.lease_token == lease_token,
                    CaseEvidenceVerification.lease_expires_at == lease_expires_at,
                    CaseEvidenceVerification.lease_expires_at <= recovery_cutoff,
                    CaseEvidenceVerification.attempt_count
                    >= CaseEvidenceVerification.max_attempts,
                )
                .values(updated_at=CaseEvidenceVerification.updated_at)
            )
            if fenced.rowcount != 1:
                session.rollback()
                return False
            job = session.scalar(
                select(CaseEvidenceVerification)
                .where(CaseEvidenceVerification.id == job_id)
                .with_for_update()
            )
            if job is None or job.state != "running":
                session.rollback()
                return False
            if job.cancel_requested_at is not None:
                self._terminal_cancel_row(
                    job,
                    session,
                    message=(
                        "Evidence verification was cancelled during retry recovery."
                    ),
                )
                return True
            self._terminal_row(
                job,
                session,
                code="evidence_retry_budget_exhausted",
                message="Evidence verification exhausted restart recovery attempts.",
            )
            return True

    def claim_next(self) -> ClaimedEvidenceVerification | None:
        if self._stop.is_set():
            return None
        now = self._now()
        with self.session_factory() as session:
            candidate = session.scalar(
                select(CaseEvidenceVerification.id)
                .where(
                    CaseEvidenceVerification.state == "queued",
                    CaseEvidenceVerification.cancel_requested_at.is_(None),
                    CaseEvidenceVerification.attempt_count
                    < CaseEvidenceVerification.max_attempts,
                    CaseEvidenceVerification.next_attempt_at.is_not(None),
                    CaseEvidenceVerification.next_attempt_at <= now,
                )
                .order_by(
                    CaseEvidenceVerification.next_attempt_at,
                    CaseEvidenceVerification.created_at,
                    CaseEvidenceVerification.id,
                )
                .limit(1)
            )
            if candidate is None:
                session.rollback()
                return None
            token = secrets.token_hex(32)
            result = session.execute(
                update(CaseEvidenceVerification)
                .where(
                    CaseEvidenceVerification.id == candidate,
                    CaseEvidenceVerification.state == "queued",
                    CaseEvidenceVerification.cancel_requested_at.is_(None),
                    CaseEvidenceVerification.attempt_count
                    < CaseEvidenceVerification.max_attempts,
                    CaseEvidenceVerification.next_attempt_at <= now,
                )
                .values(
                    state="running",
                    stage="validating",
                    attempt_count=CaseEvidenceVerification.attempt_count + 1,
                    next_attempt_at=None,
                    lease_token=token,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    heartbeat_at=now,
                    started_at=func_coalesce_started(now),
                    updated_at=now,
                    error_code=None,
                    error_detail_safe=None,
                    message_safe="Revalidating the pinned Activity transaction.",
                    checkpoint_json=_checkpoint("validating"),
                    status_version=CaseEvidenceVerification.status_version + 1,
                )
            )
            if result.rowcount != 1:
                session.rollback()
                return None
            session.commit()
            job = session.get(CaseEvidenceVerification, candidate)
            if job is None or job.case is None or job.snapshot_sync is None or job.source_sync is None:
                session.rollback()
                return None
            return ClaimedEvidenceVerification(
                id=job.id,
                public_id=job.public_id,
                case_public_id=job.case.public_id,
                snapshot_public_id=job.snapshot_sync.public_id,
                activity_public_id=job.activity_public_id,
                source_sync_public_id=job.source_sync.public_id,
                source_run_id=int(job.source_sync.ingestion_run_id or 0),
                source_transaction_id=job.source_transaction_id,
                transaction_hash=job.transaction_hash,
                network=job.network,
                semantic_fingerprint=job.activity_semantic_fingerprint,
                lease_token=token,
                attempt=job.attempt_count,
                max_attempts=job.max_attempts,
            )

    def execute_claimed(self, claimed: ClaimedEvidenceVerification) -> None:
        try:
            self._execute_claimed(claimed)
        except SQLAlchemyError as exc:
            code = _error_code(exc, "evidence_storage_unavailable")
            message = _safe_error(exc)
            if claimed.attempt < claimed.max_attempts:
                self._schedule_retry(claimed, code=code, message=message)
            else:
                self._finish_failure(claimed, code=code, message=message)

    def _execute_claimed(self, claimed: ClaimedEvidenceVerification) -> None:
        try:
            self._revalidate_selection(claimed)
        except CaseEvidenceRuntimeUnavailable as exc:
            code = "evidence_runtime_unavailable"
            message = _safe_error(exc)
            if claimed.attempt < claimed.max_attempts:
                self._schedule_retry(claimed, code=code, message=message)
            else:
                self._finish_failure(claimed, code=code, message=message)
            return
        except SQLAlchemyError as exc:
            code = _error_code(exc, "evidence_storage_unavailable")
            message = _safe_error(exc)
            if claimed.attempt < claimed.max_attempts:
                self._schedule_retry(claimed, code=code, message=message)
            else:
                self._finish_failure(claimed, code=code, message=message)
            return
        except Exception as exc:
            self._finish_invalid_selection(
                claimed,
                code="evidence_selection_conflict",
                message="Pinned Activity selection failed revalidation.",
            )
            return
        steps = (
            (
                "capturing_trace",
                "trace_capture_id",
                self.capture,
                self._bind_trace,
            ),
            (
                "verifying_bocs",
                "boc_verification_id",
                self.verify_bocs,
                self._bind_boc,
            ),
            (
                "proving_inclusion",
                "inclusion_catalog_digest_sha256",
                self.prove_inclusion,
                self._bind_inclusion,
            ),
            (
                "building_native_ledger",
                "native_ledger_id",
                self.build_ledger,
                self._bind_ledger,
            ),
        )
        for stage, field, operation, binder in steps:
            if self._stop.is_set():
                raise _WorkerStop
            if self._cancelled(claimed):
                self._finish_cancelled(claimed)
                return
            if self._has_binding(claimed, field):
                self._revalidate_bound(claimed)
                continue
            if not self._advance(claimed, stage):
                self._finish_cancelled(claimed)
                return
            try:
                value = self._call_with_heartbeats(claimed, operation)
                binder(claimed, value)
            except _WorkerStop:
                raise
            except _EvidenceOperationCancelled:
                self._finish_cancelled(claimed)
                return
            except Exception as exc:
                if self._cancelled(claimed):
                    self._finish_cancelled(claimed)
                    return
                retryable = _is_retryable(exc)
                code = _error_code(
                    exc,
                    "evidence_provider_unavailable"
                    if retryable
                    else "evidence_conflict",
                )
                message = _safe_error(exc)
                if retryable and claimed.attempt < claimed.max_attempts:
                    self._schedule_retry(
                        claimed,
                        code=code,
                        message=message,
                    )
                else:
                    self._finish_failure(
                        claimed,
                        code=(
                            "evidence_retry_budget_exhausted"
                            if retryable
                            else code
                        ),
                        message=(
                            "Evidence verification exhausted its bounded retry budget."
                            if retryable
                            else message
                        ),
                    )
                return
            if self._cancelled(claimed):
                self._finish_cancelled(claimed)
                return
        self._finish_success(claimed)

    def _revalidate_selection(self, claimed: ClaimedEvidenceVerification) -> None:
        with self.session_factory() as session:
            resolved = WalletCaseActivityService(session).resolve_verifiable_transaction(
                claimed.case_public_id,
                claimed.activity_public_id,
                snapshot_public_id=claimed.snapshot_public_id,
            )
            if (
                resolved.source_sync.public_id != claimed.source_sync_public_id
                or resolved.source_transaction.id != claimed.source_transaction_id
                or resolved.source_run.id != claimed.source_run_id
                or resolved.source_transaction.transaction_hash_canonical
                != claimed.transaction_hash
                or resolved.semantic_fingerprint != claimed.semantic_fingerprint
            ):
                raise CaseEvidenceStoredConflict(
                    "Pinned Activity source changed before evidence execution."
                )
            limitation = case_evidence_runtime_limitation(
                resolved.wallet_case,
                resolved.snapshot,
                source_sync=resolved.source_sync,
                runner_available=True,
                settings=self.settings_factory(),
            )
            if limitation is not None:
                raise CaseEvidenceRuntimeUnavailable(limitation["message"])
            session.rollback()

    def _call_with_heartbeats(
        self,
        claimed: ClaimedEvidenceVerification,
        operation: Callable[..., Any],
    ) -> Any:
        outcome: Queue[tuple[bool, Any]] = Queue(maxsize=1)
        cancellation = Event()
        try:
            accepts_cancellation = (
                "cancellation_event"
                in inspect.signature(operation).parameters
            )
        except (TypeError, ValueError):
            accepts_cancellation = False

        def call() -> None:
            try:
                with self.session_factory() as session:
                    kwargs = (
                        {"cancellation_event": cancellation}
                        if accepts_cancellation
                        else {}
                    )
                    value = operation(
                        claimed.source_run_id,
                        claimed.transaction_hash,
                        session,
                        **kwargs,
                    )
                outcome.put((True, value))
            except Exception as exc:
                outcome.put((False, exc))

        thread = Thread(target=call, name=f"case-evidence-{claimed.public_id[:8]}", daemon=True)
        with self._lock:
            if self._stop.is_set():
                raise _WorkerStop
            self._active_cancellations.add(cancellation)
            thread.start()
        cancel_requested = False
        stop_requested = False
        lease_lost = False
        try:
            while thread.is_alive():
                thread.join(timeout=self.heartbeat_seconds)
                if not thread.is_alive():
                    break
                if self._stop.is_set():
                    stop_requested = True
                    if accepts_cancellation:
                        cancellation.set()
                elif self._cancelled(claimed):
                    cancel_requested = True
                    if accepts_cancellation:
                        cancellation.set()
                if not self._heartbeat(claimed):
                    lease_lost = True
                    if accepts_cancellation:
                        cancellation.set()
        finally:
            # A control-plane exception (heartbeat/cancellation/storage read)
            # must never detach a still-running provider operation and then
            # publish a retry that can start a duplicate child. Signal every
            # cancellation-aware stage and keep its event registered until the
            # operation thread has actually stopped. The isolated liteserver
            # child has its own 180-second absolute wall; the other stage
            # providers retain their configured request bounds.
            if thread.is_alive():
                cancellation.set()
                while thread.is_alive():
                    thread.join(timeout=0.1)
            with self._lock:
                self._active_cancellations.discard(cancellation)
        if cancel_requested:
            raise _EvidenceOperationCancelled
        if self._stop.is_set() or stop_requested or lease_lost:
            raise _WorkerStop
        if outcome.empty():
            raise RuntimeError("Evidence proof call stopped unexpectedly.")
        ok, value = outcome.get()
        if not ok:
            raise value
        return value

    def _advance(self, claimed: ClaimedEvidenceVerification, stage: str) -> bool:
        now = self._now()
        with self.session_factory() as session:
            result = session.execute(
                update(CaseEvidenceVerification)
                .where(*self._owned(claimed, now), CaseEvidenceVerification.cancel_requested_at.is_(None))
                .values(
                    stage=stage,
                    updated_at=now,
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                    message_safe=_stage_message(stage),
                    checkpoint_json=_checkpoint(stage),
                    status_version=CaseEvidenceVerification.status_version + 1,
                )
            )
            session.commit()
            return result.rowcount == 1

    def _heartbeat(self, claimed: ClaimedEvidenceVerification) -> bool:
        if self._stop.is_set():
            return False
        now = self._now()
        with self.session_factory() as session:
            result = session.execute(
                update(CaseEvidenceVerification)
                .where(*self._owned(claimed, now))
                .values(
                    heartbeat_at=now,
                    lease_expires_at=now + timedelta(seconds=self.lease_seconds),
                )
            )
            session.commit()
            return result.rowcount == 1

    def _bind_trace(self, claimed: ClaimedEvidenceVerification, value: Any) -> None:
        payload = value[0] if isinstance(value, tuple) else value
        self._bind(
            claimed,
            progress=1,
            values={
                "trace_capture_id": int(payload["capture_id"]),
                "trace_digest_sha256": payload["evidence_digest_sha256"],
                "trace_completed_at": self._now(),
                "highest_evidence_level": "normalized",
            },
        )

    def _bind_boc(self, claimed: ClaimedEvidenceVerification, value: Any) -> None:
        payload = value[0] if isinstance(value, tuple) else value
        self._bind(
            claimed,
            progress=2,
            values={
                "boc_verification_id": int(payload["verification_id"]),
                "boc_digest_sha256": payload["evidence_digest_sha256"],
                "boc_completed_at": self._now(),
                "highest_evidence_level": "locally_verified",
            },
        )

    def _bind_inclusion(self, claimed: ClaimedEvidenceVerification, value: Any) -> None:
        if not _canonical_inclusion_proven(
            value,
            expected_network=claimed.network,
        ):
            raise CaseEvidenceInclusionTrustInsufficient(
                "Canonical block-chain verification requires liteserver trust level 0."
            )
        self._bind(
            claimed,
            progress=3,
            values={
                "inclusion_catalog_digest_sha256": value["catalog_digest_sha256"],
                "inclusion_completed_at": self._now(),
                "highest_evidence_level": "chain_inclusion_proven",
            },
        )

    def _bind_ledger(self, claimed: ClaimedEvidenceVerification, value: Any) -> None:
        payload = value[0] if isinstance(value, tuple) else value
        self._bind(
            claimed,
            progress=4,
            values={
                "native_ledger_id": int(payload["ledger_id"]),
                "native_ledger_digest_sha256": payload["evidence_digest_sha256"],
                "native_ledger_completed_at": self._now(),
                "highest_evidence_level": "chain_inclusion_proven",
            },
        )

    def _bind(
        self,
        claimed: ClaimedEvidenceVerification,
        *,
        progress: int,
        values: dict[str, Any],
    ) -> None:
        now = self._now()
        with self.session_factory() as session:
            job = session.scalar(
                select(CaseEvidenceVerification).where(*self._owned(claimed, now))
            )
            if job is None:
                raise _WorkerStop
            # Re-read and locally revalidate the committed legacy artifact
            # before publishing progress on the durable Case job.
            for key, value in values.items():
                setattr(job, key, value)
            job.progress_current = progress
            session.flush()
            _revalidated_artifacts(job, session)
            job.updated_at = now
            job.heartbeat_at = now
            job.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            job.checkpoint_json = _checkpoint(f"artifact_{progress}_bound")
            job.status_version += 1
            session.commit()

    def _revalidate_bound(self, claimed: ClaimedEvidenceVerification) -> None:
        now = self._now()
        with self.session_factory() as session:
            job = session.scalar(select(CaseEvidenceVerification).where(*self._owned(claimed, now)))
            if job is None:
                raise _WorkerStop
            _revalidated_artifacts(job, session)
            session.rollback()

    def _has_binding(self, claimed: ClaimedEvidenceVerification, field: str) -> bool:
        now = self._now()
        with self.session_factory() as session:
            value = session.scalar(
                select(getattr(CaseEvidenceVerification, field)).where(*self._owned(claimed, now))
            )
            session.rollback()
            return value is not None

    def _cancelled(self, claimed: ClaimedEvidenceVerification) -> bool:
        now = self._now()
        with self.session_factory() as session:
            value = session.scalar(
                select(CaseEvidenceVerification.cancel_requested_at).where(*self._owned(claimed, now))
            )
            session.rollback()
            return value is not None

    def _finish_success(self, claimed: ClaimedEvidenceVerification) -> None:
        now = self._now()
        with self.session_factory() as session:
            fenced = session.execute(
                update(CaseEvidenceVerification)
                .where(
                    *self._owned(claimed, now),
                    CaseEvidenceVerification.cancel_requested_at.is_(None),
                )
                .values(
                    stage="finalizing",
                    updated_at=now,
                    status_version=CaseEvidenceVerification.status_version + 1,
                )
            )
            if fenced.rowcount != 1:
                session.rollback()
                self._finish_cancelled(claimed)
                return
            job = session.scalar(
                select(CaseEvidenceVerification)
                .where(CaseEvidenceVerification.id == claimed.id)
                .with_for_update()
            )
            if job is None:
                session.rollback()
                return
            artifacts = _revalidated_artifacts(job, session)
            if job.progress_current != 4:
                raise CaseEvidenceStoredConflict("Evidence proof chain is incomplete.")
            job.result_digest_sha256 = _result_digest(job, artifacts)
            job.state = "succeeded"
            job.stage = "terminal"
            job.completed_at = now
            job.updated_at = now
            job.lease_token = None
            job.lease_expires_at = None
            job.next_attempt_at = None
            job.message_safe = "Selected transaction evidence and native ledger are verified."
            job.checkpoint_json = _checkpoint("succeeded")
            session.commit()

    def _finish_failure(
        self,
        claimed: ClaimedEvidenceVerification,
        *,
        code: str,
        message: str,
    ) -> None:
        now = self._now()
        with self.session_factory() as session:
            fenced = session.execute(
                update(CaseEvidenceVerification)
                .where(
                    *self._owned(claimed, now),
                    CaseEvidenceVerification.cancel_requested_at.is_(None),
                )
                .values(updated_at=CaseEvidenceVerification.updated_at)
            )
            if fenced.rowcount != 1:
                session.rollback()
                self._finish_cancelled(claimed)
                return
            job = session.scalar(
                select(CaseEvidenceVerification)
                .where(CaseEvidenceVerification.id == claimed.id)
                .with_for_update()
            )
            if job is None:
                session.rollback()
                return
            self._terminal_row(job, session, code=code, message=message)

    def _finish_invalid_selection(
        self,
        claimed: ClaimedEvidenceVerification,
        *,
        code: str,
        message: str,
    ) -> None:
        """Fail closed when the pinned source can no longer be trusted.

        Legacy artifacts are immutable and remain stored, but all public job
        bindings are cleared so a previously completed prefix cannot be
        mistaken for evidence about the now-invalid Activity selection.
        """
        now = self._now()
        with self.session_factory() as session:
            fenced = session.execute(
                update(CaseEvidenceVerification)
                .where(*self._owned(claimed, now))
                .values(updated_at=CaseEvidenceVerification.updated_at)
            )
            if fenced.rowcount != 1:
                session.rollback()
                return
            job = session.scalar(
                select(CaseEvidenceVerification)
                .where(CaseEvidenceVerification.id == claimed.id)
                .with_for_update()
            )
            if job is None:
                session.rollback()
                return
            if job.cancel_requested_at is not None:
                self._terminal_cancel_row(
                    job,
                    session,
                    message=(
                        "Evidence verification was cancelled before selection "
                        "failure publication."
                    ),
                )
                return
            _clear_artifact_bindings(job)
            job.state = "failed"
            job.stage = "terminal"
            job.completed_at = now
            job.updated_at = now
            job.next_attempt_at = None
            job.lease_token = None
            job.lease_expires_at = None
            job.error_code = code[:64]
            job.error_detail_safe = message[:1000]
            job.message_safe = message[:1000]
            job.checkpoint_json = _checkpoint("failed_selection_revalidation")
            job.status_version += 1
            session.commit()

    def _terminal_row(
        self,
        job: CaseEvidenceVerification,
        session: Session,
        *,
        code: str,
        message: str,
    ) -> None:
        now = self._now()
        if job.cancel_requested_at is not None:
            self._terminal_cancel_row(job, session, message=(
                "Evidence verification was cancelled before failure publication."
            ))
            return
        try:
            artifacts = _revalidated_artifacts(job, session)
            artifacts_valid = True
        except CaseEvidenceStoredConflict:
            # Never leave a poisoned binding running forever. Close the job as
            # failed without publishing a usable partial result; reads will
            # continue to fail closed on the corrupted artifact binding.
            artifacts = {}
            artifacts_valid = False
            code = "evidence_artifact_conflict"
            message = "Stored evidence artifact binding failed revalidation."
            _clear_artifact_bindings(job)
        job.state = (
            "partial" if artifacts_valid and job.progress_current > 0 else "failed"
        )
        job.stage = "terminal"
        job.completed_at = now
        job.updated_at = now
        job.next_attempt_at = None
        job.lease_token = None
        job.lease_expires_at = None
        job.error_code = code[:64]
        job.error_detail_safe = message[:1000]
        job.message_safe = message[:1000]
        if job.state == "partial":
            job.result_digest_sha256 = _result_digest(job, artifacts)
        job.checkpoint_json = _checkpoint(job.state)
        job.status_version += 1
        session.commit()

    def _finish_cancelled(self, claimed: ClaimedEvidenceVerification) -> None:
        now = self._now()
        with self.session_factory() as session:
            job = session.scalar(select(CaseEvidenceVerification).where(*self._owned(claimed, now)))
            if job is None or job.cancel_requested_at is None:
                return
            self._terminal_cancel_row(
                job,
                session,
                message="Evidence verification was cancelled between proof stages.",
            )

    def _terminal_cancel_row(
        self,
        job: CaseEvidenceVerification,
        session: Session,
        *,
        message: str,
    ) -> None:
        now = self._now()
        try:
            _revalidated_artifacts(job, session)
            state = "cancelled"
            code = None
        except CaseEvidenceStoredConflict:
            _clear_artifact_bindings(job)
            state = "failed"
            code = "evidence_artifact_conflict"
            job.cancel_requested_at = None
            message = "Stored evidence artifact binding failed revalidation."
        job.state = state
        job.stage = "terminal"
        job.completed_at = now
        job.updated_at = now
        job.next_attempt_at = None
        job.lease_token = None
        job.lease_expires_at = None
        job.result_digest_sha256 = None
        job.error_code = code
        job.error_detail_safe = message if code is not None else None
        job.message_safe = message
        job.checkpoint_json = _checkpoint(state)
        job.status_version += 1
        session.commit()

    def _schedule_retry(
        self,
        claimed: ClaimedEvidenceVerification,
        *,
        code: str,
        message: str,
    ) -> None:
        now = self._now()
        retry_at = now + timedelta(seconds=self._retry_delay(claimed))
        with self.session_factory() as session:
            result = session.execute(
                update(CaseEvidenceVerification)
                .where(*self._owned(claimed, now), CaseEvidenceVerification.cancel_requested_at.is_(None))
                .values(
                    state="queued",
                    stage="retry_wait",
                    next_attempt_at=retry_at,
                    updated_at=now,
                    lease_token=None,
                    lease_expires_at=None,
                    error_code=code[:64],
                    error_detail_safe=message[:1000],
                    message_safe=message[:1000],
                    checkpoint_json=_checkpoint("retry_wait", retryable=True),
                    status_version=CaseEvidenceVerification.status_version + 1,
                )
            )
            session.commit()
            if result.rowcount != 1:
                self._finish_cancelled(claimed)

    def _retry_delay(self, claimed: ClaimedEvidenceVerification) -> float:
        exponential = min(
            self.retry_cap_seconds,
            self.retry_base_seconds * (2 ** max(0, claimed.attempt - 1)),
        )
        fraction = int.from_bytes(
            hashlib.sha256(f"{claimed.public_id}:{claimed.attempt}".encode()).digest()[:2],
            "big",
        ) / 65535
        return min(self.retry_cap_seconds, exponential * (1 + 0.25 * fraction))

    def _owned(self, claimed: ClaimedEvidenceVerification, now: datetime):
        return (
            CaseEvidenceVerification.id == claimed.id,
            CaseEvidenceVerification.state == "running",
            CaseEvidenceVerification.lease_token == claimed.lease_token,
            CaseEvidenceVerification.lease_expires_at > now,
        )

    def _now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class LocalCaseEvidenceJobRunner:
    def __init__(self, worker: CaseEvidenceWorker, *, poll_milliseconds: int = 500):
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
        self._thread = Thread(target=self._run, name="case-evidence-runner", daemon=True)
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
                    "Case evidence runner iteration failed safely (exception_type=%s)",
                    type(exc).__name__,
                )
                worked = False
            if worked:
                continue
            self._wake.wait(self.poll_seconds)
            self._wake.clear()


def func_coalesce_started(now: datetime):
    from sqlalchemy import func

    return func.coalesce(CaseEvidenceVerification.started_at, now)


def _stage_message(stage: str) -> str:
    return {
        "capturing_trace": "Capturing finalized provider trace evidence.",
        "verifying_bocs": "Locally verifying persisted transaction BOCs.",
        "proving_inclusion": "Proving transaction BOC inclusion in TON blocks.",
        "building_native_ledger": "Building selected native TON activity semantics.",
    }[stage]


def _clear_artifact_bindings(job: CaseEvidenceVerification) -> None:
    for field in (
        "trace_capture_id",
        "trace_digest_sha256",
        "trace_completed_at",
        "boc_verification_id",
        "boc_digest_sha256",
        "boc_completed_at",
        "inclusion_catalog_digest_sha256",
        "inclusion_completed_at",
        "native_ledger_id",
        "native_ledger_digest_sha256",
        "native_ledger_completed_at",
        "result_digest_sha256",
    ):
        setattr(job, field, None)
    job.progress_current = 0
    job.highest_evidence_level = "normalized"


def _safe_error(exc: Exception) -> str:
    if isinstance(exc, SQLAlchemyError):
        return "Evidence verification storage is temporarily unavailable."
    if isinstance(exc, WalletTraceEvidenceProviderFailure):
        if _is_retryable_provider_code(_provider_error_code(exc)):
            return "The evidence provider is temporarily unavailable."
        return "The evidence provider response failed protocol or identity validation."
    if isinstance(exc, WalletTransactionInclusionProofFailure):
        if exc.retryable:
            return "TON block-inclusion verification is temporarily unavailable."
        return "TON block-inclusion verification failed its trust or protocol boundary."
    if isinstance(exc, _RETRYABLE_OPERATION_ERRORS):
        return "Evidence verification is temporarily unavailable."
    if isinstance(exc, _SAFE_DOMAIN_ERRORS):
        value = str(exc).strip()
        if value:
            return value[:1000]
    if isinstance(exc, CaseEvidenceInclusionTrustInsufficient):
        return str(exc)[:1000]
    return "Evidence verification stopped on an internal error."


def _error_code(exc: Exception, fallback: str) -> str:
    if isinstance(exc, SQLAlchemyError):
        return "evidence_storage_unavailable"
    if isinstance(exc, WalletTraceEvidenceProviderFailure):
        return _provider_error_code(exc)
    if isinstance(exc, WalletTransactionInclusionProofFailure):
        candidate = str(getattr(exc, "code", fallback))
        if (
            1 <= len(candidate) <= 64
            and all(char.islower() or char.isdigit() or char == "_" for char in candidate)
        ):
            return candidate
        return fallback[:64]
    if isinstance(exc, CaseEvidenceRuntimeUnavailable):
        return exc.code
    if isinstance(exc, CaseEvidenceStoredConflict):
        return "evidence_stored_conflict"
    if isinstance(exc, CaseEvidenceInclusionTrustInsufficient):
        return exc.code
    return fallback[:64]


def _provider_error_code(exc: WalletTraceEvidenceProviderFailure) -> str:
    candidate = str(getattr(exc, "code", "provider_error"))
    if candidate in _RETRYABLE_PROVIDER_CODES | _PERMANENT_PROVIDER_CODES:
        return candidate
    if candidate.startswith("http_") and candidate[5:].isdigit():
        status = int(candidate[5:])
        if 400 <= status <= 599:
            return candidate
    return "provider_error"


def _is_retryable_provider_code(code: str) -> bool:
    if code in _PERMANENT_PROVIDER_CODES:
        return False
    if code.startswith("http_") and code[5:].isdigit():
        status = int(code[5:])
        return status in {408, 425, 429} or 500 <= status <= 599
    return code in _RETRYABLE_PROVIDER_CODES


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, WalletTraceEvidenceProviderFailure):
        return _is_retryable_provider_code(_provider_error_code(exc))
    if isinstance(exc, WalletTransactionInclusionProofFailure):
        return bool(exc.retryable)
    return isinstance(exc, _RETRYABLE_OPERATION_ERRORS)


__all__ = ["CaseEvidenceWorker", "ClaimedEvidenceVerification", "LocalCaseEvidenceJobRunner"]
