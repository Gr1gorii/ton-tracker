"""Owner-scoped application service for pinned Case evidence verification."""

from __future__ import annotations

from collections import OrderedDict
from datetime import datetime, timezone
import hashlib
import json
from threading import Lock
import time
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from adapters.tonapi import TonapiAdapter
from adapters.wallet_activity import TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
from config import get_settings
from models import CaseEvidenceVerification, CaseSync, LOCAL_SINGLE_USER_SCOPE, WalletCase
from services.wallet_case_activity import (
    WalletCaseActivityInvalidQuery,
    WalletCaseActivityItemNotFound,
    WalletCaseActivityNotFound,
    WalletCaseActivityScopeTooLarge,
    WalletCaseActivityService,
    ResolvedCaseActivityTransaction,
    WalletCaseActivitySnapshotConflict,
    WalletCaseActivitySnapshotNotFound,
    _activity_public_id,
    _run_matches_case,
    _transaction_observation,
)
from services.wallet_cases import _stored_coverage
from services.wallet_native_activity_ledger import (
    WalletNativeActivityLedgerConflict,
    get_wallet_native_activity_ledger,
)
from services.wallet_persisted_trace_evidence import (
    WalletPersistedTraceEvidenceConflict,
    get_persisted_wallet_transaction_trace_evidence,
)
from services.wallet_trace_boc_verification import (
    WalletTraceBocVerificationConflict,
    get_wallet_transaction_trace_boc_verification,
)
from services.wallet_transaction_inclusion_proof import (
    WalletTransactionInclusionProofConflict,
    get_wallet_transaction_inclusion_proofs,
)
from services.ton_liteclient_config import (
    CURRENT_VERIFIER_POLICY_ID,
    is_current_trusted_checkpoint,
)
from wallet_case_evidence_schemas import CaseEvidenceVerificationRequest


CATALOG_LIMIT = 50
POLICY_VERSION = "transaction_inclusion_v1"
STEP_CODES = (
    "trace_capture",
    "boc_verification",
    "block_inclusion",
    "native_ledger",
)
_SELECTION_CACHE_TTL_SECONDS = 5.0
_SELECTION_CACHE_MAX = 1024
_selection_cache: OrderedDict[tuple[Any, ...], float] = OrderedDict()
_selection_cache_lock = Lock()


class CaseEvidenceNotFound(LookupError):
    code = "evidence_not_found"


class CaseEvidenceSnapshotNotFound(LookupError):
    code = "evidence_snapshot_not_found"


class CaseEvidenceActivityNotFound(LookupError):
    code = "evidence_activity_not_found"


class CaseEvidenceIneligible(ValueError):
    code = "evidence_activity_ineligible"


class CaseEvidenceSnapshotConflict(ValueError):
    code = "evidence_snapshot_invalid"


class CaseEvidenceScopeTooLarge(ValueError):
    code = "evidence_scope_too_large"


class CaseEvidenceIdempotencyConflict(ValueError):
    code = "idempotency_conflict"


class CaseEvidenceAlreadyActive(ValueError):
    code = "evidence_verification_already_active"

    def __init__(self, public_id: str) -> None:
        self.public_id = public_id
        super().__init__("This pinned Activity selection already has active verification.")


class CaseEvidenceStoredConflict(RuntimeError):
    code = "evidence_stored_conflict"


class CaseEvidenceRuntimeUnavailable(RuntimeError):
    code = "evidence_runtime_unavailable"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        if code is not None:
            self.code = code[:64]
        super().__init__(message)


class CaseEvidenceService:
    def __init__(
        self,
        session: Session,
        *,
        owner_scope_id: str = LOCAL_SINGLE_USER_SCOPE,
        settings_factory=get_settings,
    ) -> None:
        self.session = session
        self.owner_scope_id = owner_scope_id
        self.settings_factory = settings_factory

    def enqueue(
        self,
        case_public_id: str,
        payload: CaseEvidenceVerificationRequest,
        idempotency_key: str,
        *,
        runner_available: bool = False,
    ) -> tuple[dict[str, Any], bool]:
        wallet_case = self._required_case(case_public_id)
        fingerprint = _request_fingerprint(payload)
        existing = self.session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.case_id == wallet_case.id,
                CaseEvidenceVerification.idempotency_key == idempotency_key,
            )
        )
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise CaseEvidenceIdempotencyConflict(
                    "Idempotency-Key was already used for another evidence request."
                )
            return self._response(existing), True

        resolved = self._resolve(
            case_public_id,
            payload.snapshot_public_id,
            payload.activity_public_id,
        )
        wallet_case = resolved.wallet_case
        if wallet_case.data_environment != "live" or resolved.source_run.data_mode != "real":
            raise CaseEvidenceIneligible(
                "Demo fixture Activity cannot be promoted through live chain proof."
            )
        settings = self.settings_factory()
        limitation = case_evidence_runtime_limitation(
            wallet_case,
            resolved.snapshot,
            source_sync=resolved.source_sync,
            runner_available=runner_available,
            settings=settings,
        )
        if limitation is not None:
            if limitation["code"] == "evidence_runner_unavailable":
                raise CaseEvidenceRuntimeUnavailable(
                    "Transaction evidence verification runner is unavailable.",
                    code="evidence_runner_unavailable",
                )
            raise CaseEvidenceRuntimeUnavailable(
                limitation["message"], code=limitation["code"]
            )

        active = self.session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.case_id == wallet_case.id,
                CaseEvidenceVerification.snapshot_sync_id == resolved.snapshot.id,
                CaseEvidenceVerification.activity_public_id == payload.activity_public_id,
                CaseEvidenceVerification.policy == payload.policy,
                CaseEvidenceVerification.state.in_(("queued", "running")),
            )
        )
        if active is not None:
            active_public_id = active.public_id
            # A same-key caller may have committed after our first lookup but
            # before this active-selection read. End the read snapshot and let
            # owner-scoped idempotency win over the generic active conflict.
            self.session.rollback()
            replay = self.session.scalar(
                select(CaseEvidenceVerification).where(
                    CaseEvidenceVerification.case_id == wallet_case.id,
                    CaseEvidenceVerification.idempotency_key == idempotency_key,
                )
            )
            if replay is not None:
                if replay.request_fingerprint != fingerprint:
                    raise CaseEvidenceIdempotencyConflict(
                        "Idempotency-Key was already used for another evidence request."
                    )
                return self._response(replay), True
            raise CaseEvidenceAlreadyActive(active_public_id)

        item = resolved.item
        transaction = item["transaction"]
        now = _utc_now()
        job = CaseEvidenceVerification(
            case_id=wallet_case.id,
            snapshot_sync_id=resolved.snapshot.id,
            source_sync_id=resolved.source_sync.id,
            source_transaction_id=resolved.source_transaction.id,
            activity_public_id=payload.activity_public_id,
            activity_semantic_fingerprint=resolved.semantic_fingerprint,
            policy=payload.policy,
            state="queued",
            stage="queued",
            progress_current=0,
            highest_evidence_level="normalized",
            provider=item["provenance"]["provider"],
            network=wallet_case.network,
            wallet_account_canonical=wallet_case.canonical_wallet_key,
            transaction_hash=transaction["hash"],
            transaction_logical_time=item["logical_time"],
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            attempt_count=0,
            max_attempts=settings.wallet_case_evidence_max_attempts,
            next_attempt_at=now,
            checkpoint_json=_checkpoint("queued"),
            message_safe="Transaction evidence verification is queued.",
            created_at=now,
            updated_at=now,
        )
        try:
            self.session.add(job)
            self.session.commit()
            self.session.refresh(job)
        except IntegrityError as exc:
            self.session.rollback()
            replay = self.session.scalar(
                select(CaseEvidenceVerification).where(
                    CaseEvidenceVerification.case_id == wallet_case.id,
                    CaseEvidenceVerification.idempotency_key == idempotency_key,
                )
            )
            if replay is not None:
                if replay.request_fingerprint != fingerprint:
                    raise CaseEvidenceIdempotencyConflict(
                        "Idempotency-Key was already used for another evidence request."
                    ) from exc
                return self._response(replay), True
            active = self.session.scalar(
                select(CaseEvidenceVerification).where(
                    CaseEvidenceVerification.case_id == wallet_case.id,
                    CaseEvidenceVerification.snapshot_sync_id == resolved.snapshot.id,
                    CaseEvidenceVerification.activity_public_id == payload.activity_public_id,
                    CaseEvidenceVerification.policy == payload.policy,
                    CaseEvidenceVerification.state.in_(("queued", "running")),
                )
            )
            if active is not None:
                raise CaseEvidenceAlreadyActive(active.public_id) from exc
            raise
        return self._response(job), False

    def get_verification(self, case_public_id: str, public_id: str) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        job = self.session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.case_id == wallet_case.id,
                CaseEvidenceVerification.public_id == public_id,
            )
        )
        if job is None:
            raise CaseEvidenceNotFound("Evidence verification not found.")
        return self._response(job, allow_active_selection_cache=True)

    def cancel(
        self, case_public_id: str, public_id: str
    ) -> tuple[dict[str, Any], bool]:
        wallet_case = self._required_case(case_public_id)
        selector = select(CaseEvidenceVerification).where(
            CaseEvidenceVerification.case_id == wallet_case.id,
            CaseEvidenceVerification.public_id == public_id,
        )
        for _attempt in range(8):
            job = self.session.scalar(
                selector.execution_options(populate_existing=True)
            )
            if job is None:
                raise CaseEvidenceNotFound("Evidence verification not found.")
            if job.state not in {"queued", "running"}:
                return self._response(job), False
            if job.state == "running" and job.cancel_requested_at is not None:
                # The accepted request is already durable. Refresh once so a
                # concurrently completed terminal state is returned as such.
                self.session.rollback()
                refreshed = self.session.scalar(
                    selector.execution_options(populate_existing=True)
                )
                if refreshed is None:
                    raise CaseEvidenceNotFound("Evidence verification not found.")
                return self._response(refreshed), refreshed.state == "running"

            observed_state = job.state
            observed_version = job.status_version
            job_id = job.id
            # Release the read transaction before the compare-and-swap write;
            # provider workers must remain able to advance concurrently.
            self.session.rollback()
            now = _utc_now()
            if observed_state == "queued":
                result = self.session.execute(
                    update(CaseEvidenceVerification)
                    .where(
                        CaseEvidenceVerification.id == job_id,
                        CaseEvidenceVerification.case_id == wallet_case.id,
                        CaseEvidenceVerification.state == "queued",
                        CaseEvidenceVerification.status_version == observed_version,
                    )
                    .values(
                        state="cancelled",
                        stage="terminal",
                        cancel_requested_at=now,
                        completed_at=now,
                        updated_at=now,
                        next_attempt_at=None,
                        lease_token=None,
                        lease_expires_at=None,
                        message_safe=(
                            "Evidence verification was cancelled before execution."
                        ),
                        checkpoint_json=_checkpoint("cancelled"),
                        status_version=CaseEvidenceVerification.status_version + 1,
                    )
                )
            else:
                result = self.session.execute(
                    update(CaseEvidenceVerification)
                    .where(
                        CaseEvidenceVerification.id == job_id,
                        CaseEvidenceVerification.case_id == wallet_case.id,
                        CaseEvidenceVerification.state == "running",
                        CaseEvidenceVerification.status_version == observed_version,
                        CaseEvidenceVerification.cancel_requested_at.is_(None),
                    )
                    .values(
                        cancel_requested_at=now,
                        updated_at=now,
                        message_safe=(
                            "Cancellation will be applied between proof stages."
                        ),
                        status_version=CaseEvidenceVerification.status_version + 1,
                    )
                )
            self.session.commit()
            if result.rowcount != 1:
                continue
            refreshed = self.session.scalar(
                selector.execution_options(populate_existing=True)
            )
            if refreshed is None:
                raise CaseEvidenceNotFound("Evidence verification not found.")
            return self._response(refreshed), refreshed.state == "running"

        self.session.rollback()
        job = self.session.scalar(selector.execution_options(populate_existing=True))
        if job is None:
            raise CaseEvidenceNotFound("Evidence verification not found.")
        return self._response(job), (
            job.state == "running" and job.cancel_requested_at is not None
        )

    def catalog(
        self,
        case_public_id: str,
        *,
        snapshot_public_id: str | None,
        runner_available: bool = False,
    ) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        snapshot = self.session.scalar(
            select(CaseSync)
            .where(
                CaseSync.case_id == wallet_case.id,
                CaseSync.state.in_(("partial", "succeeded")),
                CaseSync.ingestion_run_id.is_not(None),
                *(
                    (CaseSync.public_id == snapshot_public_id,)
                    if snapshot_public_id is not None
                    else ()
                ),
            )
            .order_by(CaseSync.id.desc())
            .limit(1)
        )
        if snapshot is None and snapshot_public_id is not None:
            raise CaseEvidenceSnapshotNotFound(
                "The requested Wallet Case snapshot is unavailable."
            )
        canonical_transactions: dict[str, ResolvedCaseActivityTransaction] | None = None
        if snapshot is not None:
            # Reuse the canonical Activity facade so a corrupt usable-looking
            # CaseSync cannot advertise evidence readiness outside its run,
            # environment, provider, network, or wallet scope.
            try:
                revision = WalletCaseActivityService(
                    self.session, owner_scope_id=self.owner_scope_id
                ).resolve_verifiable_transaction_revision(
                    wallet_case.public_id,
                    snapshot_public_id=snapshot.public_id,
                )
                canonical_transactions = revision.verifiable_transactions
            except WalletCaseActivitySnapshotConflict as exc:
                raise CaseEvidenceSnapshotConflict(str(exc)) from exc
            except WalletCaseActivityScopeTooLarge as exc:
                raise CaseEvidenceScopeTooLarge(str(exc)) from exc
        rows: list[CaseEvidenceVerification] = []
        counts = _zero_counts()
        total = 0
        if snapshot is not None:
            rows = list(
                self.session.scalars(
                    select(CaseEvidenceVerification)
                    .where(
                        CaseEvidenceVerification.case_id == wallet_case.id,
                        CaseEvidenceVerification.snapshot_sync_id == snapshot.id,
                    )
                    .order_by(CaseEvidenceVerification.id.desc())
                    .limit(CATALOG_LIMIT)
                )
            )
            total = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(CaseEvidenceVerification)
                    .where(
                        CaseEvidenceVerification.case_id == wallet_case.id,
                        CaseEvidenceVerification.snapshot_sync_id == snapshot.id,
                    )
                )
                or 0
            )
        artifact_cache: dict[
            tuple[Any, ...], dict[str, dict[str, Any] | None]
        ] = {}
        serialized_rows = [
            self._response(
                row,
                canonical_transactions=canonical_transactions,
                artifact_cache=artifact_cache,
            )
            for row in rows
        ]
        for row in serialized_rows:
            counts[row["state"]] += 1
            counts[row["highest_evidence_level"]] += 1
        highest = next(
            (
                level
                for level in ("chain_inclusion_proven", "locally_verified", "normalized")
                if counts[level]
            ),
            None,
        )
        runtime_limitation = (
            None
            if snapshot is None
            else case_evidence_runtime_limitation(
                wallet_case,
                snapshot,
                runner_available=runner_available,
                settings=self.settings_factory(),
            )
        )
        limitations = [{
            "code": "report_not_built",
            "message": (
                "v0.74 verifies selected transaction evidence but does not build "
                "a Wallet Case report."
            ),
        }]
        if snapshot is None:
            limitations.insert(0, {
                "code": "not_synchronized",
                "message": "Synchronize this Wallet Case before verifying evidence.",
            })
        elif wallet_case.data_environment == "demo":
            limitations.insert(0, {
                "code": "demo_evidence_not_verifiable",
                "message": "Demo fixtures cannot be promoted to live chain proof.",
            })
        else:
            limitations.insert(0, {
                "code": "selective_transaction_evidence",
                "message": (
                    "Only explicitly selected eligible transactions are verified; "
                    "unselected Activity remains normalized provider evidence."
                ),
            })
        if runtime_limitation is not None and not any(
            item["code"] == runtime_limitation["code"] for item in limitations
        ):
            limitations.insert(0, runtime_limitation)
        if total > len(serialized_rows):
            limitations.append({
                "code": "catalog_history_not_revalidated",
                "message": (
                    "Aggregate state and evidence-level counts cover only the newest "
                    "returned, revalidated verifications; total includes older history."
                ),
            })
        return {
            "case_public_id": wallet_case.public_id,
            "snapshot": _snapshot(snapshot) if snapshot is not None else None,
            "aggregate": {
                "total": total,
                "returned_count": len(serialized_rows),
                "counts_scope": "returned_revalidated",
                **{state: counts[state] for state in _STATES},
                **{level: counts[level] for level in _LEVELS},
            },
            "readiness": {
                "transaction_verification_available": (
                    snapshot is not None
                    and wallet_case.data_environment == "live"
                    and runtime_limitation is None
                ),
                "report_available": False,
                "highest_evidence_level": highest,
            },
            "limitations": limitations,
            "verifications": serialized_rows,
            "limit": CATALOG_LIMIT,
            "truncated": total > len(serialized_rows),
        }

    def _required_case(self, public_id: str) -> WalletCase:
        wallet_case = self.session.scalar(
            select(WalletCase).where(
                WalletCase.owner_scope_id == self.owner_scope_id,
                WalletCase.public_id == public_id,
                WalletCase.archived_at.is_(None),
            )
        )
        if wallet_case is None:
            raise CaseEvidenceNotFound("Wallet Case not found.")
        return wallet_case

    def _resolve(self, case_public_id: str, snapshot_id: str, activity_id: str):
        try:
            return WalletCaseActivityService(
                self.session, owner_scope_id=self.owner_scope_id
            ).resolve_verifiable_transaction(
                case_public_id,
                activity_id,
                snapshot_public_id=snapshot_id,
            )
        except WalletCaseActivityNotFound as exc:
            raise CaseEvidenceNotFound(str(exc)) from exc
        except WalletCaseActivitySnapshotNotFound as exc:
            raise CaseEvidenceSnapshotNotFound(str(exc)) from exc
        except WalletCaseActivityItemNotFound as exc:
            raise CaseEvidenceActivityNotFound(str(exc)) from exc
        except WalletCaseActivityInvalidQuery as exc:
            raise CaseEvidenceIneligible(str(exc)) from exc
        except WalletCaseActivitySnapshotConflict as exc:
            raise CaseEvidenceSnapshotConflict(str(exc)) from exc
        except WalletCaseActivityScopeTooLarge as exc:
            raise CaseEvidenceScopeTooLarge(str(exc)) from exc

    def _response(
        self,
        job: CaseEvidenceVerification,
        *,
        canonical_transactions: dict[str, ResolvedCaseActivityTransaction] | None = None,
        allow_active_selection_cache: bool = False,
        artifact_cache: dict[
            tuple[Any, ...], dict[str, dict[str, Any] | None]
        ] | None = None,
    ) -> dict[str, Any]:
        _validate_job_scope(
            job,
            self.session,
            owner_scope_id=self.owner_scope_id,
            canonical_transactions=canonical_transactions,
            allow_active_selection_cache=allow_active_selection_cache,
        )
        if job.source_sync is None:
            raise CaseEvidenceStoredConflict("Evidence source synchronization disappeared.")
        _validate_artifact_prefix(job)
        artifact_key = _artifact_cache_key(job)
        artifacts = (
            artifact_cache.get(artifact_key)
            if artifact_cache is not None
            else None
        )
        if artifacts is None:
            artifacts = _revalidated_artifacts(job, self.session)
            if artifact_cache is not None:
                artifact_cache[artifact_key] = artifacts
        steps = _steps(job, artifacts)
        progress = sum(item["state"] == "succeeded" for item in steps)
        if progress != job.progress_current:
            raise CaseEvidenceStoredConflict("Evidence job progress lost its artifact binding.")
        inclusion_provenance = _inclusion_provenance(
            artifacts["block_inclusion"],
            expected_network=job.network,
        )
        if (inclusion_provenance is not None) != (progress >= 3):
            raise CaseEvidenceStoredConflict(
                "Evidence inclusion provenance lost its artifact binding."
            )
        result = None
        if job.state in {"partial", "succeeded"}:
            digest = _result_digest(job, artifacts)
            if digest != job.result_digest_sha256:
                raise CaseEvidenceStoredConflict("Evidence result digest failed revalidation.")
            ledger = artifacts["native_ledger"]
            result = {
                "verification_digest_sha256": digest,
                "evidence_digests": {
                    "trace_capture": job.trace_digest_sha256,
                    "boc_verification": job.boc_digest_sha256,
                    "block_inclusion": job.inclusion_catalog_digest_sha256,
                    "native_ledger": job.native_ledger_digest_sha256,
                },
                "inclusion_provenance": inclusion_provenance,
                "native_ledger": (
                    None
                    if ledger is None
                    else {
                        "evidence_digest_sha256": ledger["evidence_digest_sha256"],
                        "activity_count": ledger["activity_count"],
                        "incoming_nanoton": ledger["incoming_nanoton"],
                        "outgoing_nanoton": ledger["outgoing_nanoton"],
                        "self_nanoton": ledger["self_nanoton"],
                        "native_ton_only": True,
                        "selected_evidence_only": True,
                        "is_authoritative_activity_ledger": False,
                        "establishes_complete_wallet_history": False,
                        "eligible_for_cost_basis": False,
                        "used_by_pnl": False,
                        "message": (
                            "Native TON semantics are derived only from this selected "
                            "proved trace and do not establish complete wallet history."
                        ),
                    }
                ),
            }
        retry = None
        if job.state == "queued" and job.stage == "retry_wait":
            retry = {
                "attempt": job.attempt_count,
                "max_attempts": job.max_attempts,
                "retry_at": _iso(job.next_attempt_at),
                "reason_code": job.error_code or "evidence_retry",
                "message_safe": _message(job.error_detail_safe),
            }
        error = None
        if job.state == "failed":
            error = {
                "code": job.error_code or "evidence_failed",
                "message_safe": _message(job.error_detail_safe),
                "retryable": False,
            }
        limitations = []
        if job.state == "partial":
            limitations.append({
                "code": "verification_partial",
                "message": _message(job.error_detail_safe or job.message_safe),
            })
        limitations.append({
            "code": "selected_evidence_only",
            "message": "Verification covers one selected transaction, not all case Activity.",
        })
        return {
            "case_public_id": job.case.public_id,
            "public_id": job.public_id,
            "snapshot_public_id": job.snapshot_sync.public_id,
            "activity_public_id": job.activity_public_id,
            "policy": job.policy,
            "state": job.state,
            "stage": job.stage,
            "status_version": job.status_version,
            "progress": {"current": progress, "total": 4},
            "cancel_requested": job.cancel_requested_at is not None,
            "highest_evidence_level": job.highest_evidence_level,
            "provenance": {
                "data_origin": "provider_observed",
                "provider": job.provider,
                "identity_assurance": "network_scoped",
                "source_sync_public_id": job.source_sync.public_id,
                "transaction": {
                    "network": job.network,
                    "wallet_account_canonical": job.wallet_account_canonical,
                    "hash": job.transaction_hash,
                    "logical_time": job.transaction_logical_time,
                },
            },
            "inclusion_provenance": inclusion_provenance,
            "steps": steps,
            "retry": retry,
            "error": error,
            "result": result,
            "limitations": limitations,
            "message": _message(job.message_safe),
            "created_at": _iso(job.created_at),
            "updated_at": _iso(job.updated_at),
            "started_at": _iso(job.started_at),
            "completed_at": _iso(job.completed_at),
        }


_STATES = ("queued", "running", "partial", "succeeded", "failed", "cancelled")
_LEVELS = ("normalized", "locally_verified", "chain_inclusion_proven")


def case_evidence_runtime_limitation(
    wallet_case: WalletCase,
    snapshot: CaseSync,
    *,
    runner_available: bool,
    settings: Any,
    source_sync: CaseSync | None = None,
) -> dict[str, str] | None:
    """Return one safe reason why this pinned live proof cannot execute now.

    This is deliberately provider-I/O free. Enqueue, catalog readiness, and
    worker claim all use the same configuration/network boundary so a durable
    Case created under one runtime cannot be advertised as runnable under a
    different one.
    """
    if not runner_available:
        return {
            "code": "evidence_runner_unavailable",
            "message": "Transaction evidence verification runner is unavailable.",
        }
    if wallet_case.data_environment != "live" or snapshot.data_mode != "real":
        return {
            "code": "demo_evidence_not_verifiable",
            "message": "Demo fixtures cannot be promoted to live chain proof.",
        }
    run = snapshot.ingestion_run
    expected_network = f"ton-{settings.ton_network}"
    provider_matches = (
        snapshot.provider == TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
        and (
            source_sync is None
            or source_sync.provider == TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
        )
        and settings.wallet_activity_provider == "tonapi"
    )
    if (
        not settings.is_real
        or not settings.wallet_activity_live_enabled
        or not provider_matches
        or run is None
        or run.data_mode != "real"
        or run.wallet_network != wallet_case.network
        or wallet_case.network != expected_network
        or settings.ton_liteclient_trust_level != 0
        or not TonapiAdapter(settings).is_configured()
    ):
        return {
            "code": "evidence_runtime_unavailable",
            "message": (
                "The current guarded live TonAPI runtime does not match this "
                "Wallet Case network and provider scope."
            ),
        }
    return None


def _zero_counts() -> dict[str, int]:
    return {value: 0 for value in _STATES + _LEVELS}


def _validate_job_scope(
    job: CaseEvidenceVerification,
    session: Session,
    *,
    owner_scope_id: str,
    canonical_transactions: dict[str, ResolvedCaseActivityTransaction] | None,
    allow_active_selection_cache: bool,
) -> None:
    wallet_case = job.case
    snapshot = job.snapshot_sync
    source_sync = job.source_sync
    transaction = job.source_transaction
    if (
        wallet_case is None
        or snapshot is None
        or source_sync is None
        or transaction is None
        or wallet_case.archived_at is not None
        or snapshot.case_id != job.case_id
        or source_sync.case_id != job.case_id
        or source_sync.id > snapshot.id
        or snapshot.state not in {"partial", "succeeded"}
        or source_sync.state not in {"partial", "succeeded"}
        or snapshot.ingestion_run_id is None
        or source_sync.ingestion_run_id is None
        or transaction.run_id != source_sync.ingestion_run_id
        or snapshot.provider != TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
        or source_sync.provider != TONAPI_LIVE_WALLET_ACTIVITY_PROVIDER
        or job.network != wallet_case.network
        or job.wallet_account_canonical != wallet_case.canonical_wallet_key
        or job.policy != POLICY_VERSION
        or job.request_fingerprint
        != _digest({
            "contract": "case_evidence_request_v1",
            "snapshot_public_id": snapshot.public_id,
            "activity_public_id": job.activity_public_id,
            "policy": job.policy,
        })
    ):
        raise CaseEvidenceStoredConflict(
            "Evidence verification failed its Wallet Case source-scope contract."
        )
    run = source_sync.ingestion_run
    expected_mode = "mock" if wallet_case.data_environment == "demo" else "real"
    if run is None or not _run_matches_case(
        run, source_sync, wallet_case, expected_mode
    ):
        raise CaseEvidenceStoredConflict(
            "Evidence source run failed its Wallet Case scope contract."
        )
    observation = _transaction_observation(wallet_case, source_sync, run, transaction)
    if (
        observation is None
        or observation.identity_key is None
        or job.provider != observation.provider
        or observation.semantic_fingerprint != job.activity_semantic_fingerprint
        or _activity_public_id(wallet_case.public_id, observation)
        != job.activity_public_id
        or transaction.transaction_hash_canonical != job.transaction_hash
        or transaction.transaction_logical_time_canonical
        != job.transaction_logical_time
    ):
        raise CaseEvidenceStoredConflict(
            "Evidence transaction identity or semantic binding changed."
        )
    cache_key = _selection_cache_key(job)
    cache_hit = (
        allow_active_selection_cache
        and job.state in {"queued", "running"}
        and _selection_cache_hit(cache_key)
    )
    if canonical_transactions is None and not cache_hit:
        try:
            resolved = WalletCaseActivityService(
                session,
                owner_scope_id=owner_scope_id,
            ).resolve_verifiable_transaction(
                wallet_case.public_id,
                job.activity_public_id,
                snapshot_public_id=snapshot.public_id,
            )
        except (
            WalletCaseActivityNotFound,
            WalletCaseActivitySnapshotNotFound,
            WalletCaseActivityItemNotFound,
            WalletCaseActivityInvalidQuery,
            WalletCaseActivitySnapshotConflict,
            WalletCaseActivityScopeTooLarge,
        ) as exc:
            raise CaseEvidenceStoredConflict(
                "Evidence canonical Activity selection failed revalidation."
            ) from exc
    else:
        resolved = (
            None
            if canonical_transactions is None
            else canonical_transactions.get(job.activity_public_id)
        )
        if canonical_transactions is not None and resolved is None:
            raise CaseEvidenceStoredConflict(
                "Evidence canonical Activity selection failed revalidation."
            )
    if cache_hit:
        return
    if (
        resolved.wallet_case.id != job.case_id
        or resolved.snapshot.id != job.snapshot_sync_id
        or resolved.source_sync.id != job.source_sync_id
        or resolved.source_run.id != source_sync.ingestion_run_id
        or resolved.source_transaction.id != job.source_transaction_id
        or resolved.semantic_fingerprint != job.activity_semantic_fingerprint
    ):
        raise CaseEvidenceStoredConflict(
            "Evidence source no longer matches the canonical Activity selection."
        )
    if allow_active_selection_cache and job.state in {"queued", "running"}:
        _selection_cache_store(cache_key)


def _selection_cache_key(job: CaseEvidenceVerification) -> tuple[Any, ...]:
    return (
        job.public_id,
        job.status_version,
        job.case_id,
        job.snapshot_sync_id,
        job.source_sync_id,
        job.source_transaction_id,
        job.activity_public_id,
        job.activity_semantic_fingerprint,
        job.request_fingerprint,
    )


def _selection_cache_hit(key: tuple[Any, ...]) -> bool:
    now = time.monotonic()
    with _selection_cache_lock:
        expires_at = _selection_cache.get(key)
        if expires_at is None:
            return False
        if expires_at <= now:
            _selection_cache.pop(key, None)
            return False
        _selection_cache.move_to_end(key)
        return True


def _selection_cache_store(key: tuple[Any, ...]) -> None:
    with _selection_cache_lock:
        _selection_cache[key] = time.monotonic() + _SELECTION_CACHE_TTL_SECONDS
        _selection_cache.move_to_end(key)
        while len(_selection_cache) > _SELECTION_CACHE_MAX:
            _selection_cache.popitem(last=False)


def _clear_selection_cache_for_tests() -> None:
    with _selection_cache_lock:
        _selection_cache.clear()


def _request_fingerprint(payload: CaseEvidenceVerificationRequest) -> str:
    return _digest({
        "contract": "case_evidence_request_v1",
        "snapshot_public_id": payload.snapshot_public_id,
        "activity_public_id": payload.activity_public_id,
        "policy": payload.policy,
    })


def _checkpoint(phase: str, *, retryable: bool = False) -> str:
    return json.dumps(
        {"version": "case_evidence_job_v1", "phase": phase, "retryable": retryable},
        sort_keys=True,
        separators=(",", ":"),
    )


def _revalidated_artifacts(
    job: CaseEvidenceVerification, session: Session
) -> dict[str, dict[str, Any] | None]:
    _validate_artifact_prefix(job)
    run_id = job.source_sync.ingestion_run_id
    if run_id is None:
        raise CaseEvidenceStoredConflict("Evidence source run disappeared.")
    values: dict[str, dict[str, Any] | None] = {
        "trace_capture": None,
        "boc_verification": None,
        "block_inclusion": None,
        "native_ledger": None,
    }
    if job.trace_capture_id is not None:
        value = _legacy_artifact_read(get_persisted_wallet_transaction_trace_evidence,
            run_id, job.transaction_hash, session
        )
        _binding(value, job.trace_capture_id, job.trace_digest_sha256, "capture_id")
        values["trace_capture"] = value
    if job.boc_verification_id is not None:
        value = _legacy_artifact_read(get_wallet_transaction_trace_boc_verification,
            run_id, job.transaction_hash, session
        )
        _binding(value, job.boc_verification_id, job.boc_digest_sha256, "verification_id")
        values["boc_verification"] = value
    if job.inclusion_catalog_digest_sha256 is not None:
        value = _legacy_artifact_read(get_wallet_transaction_inclusion_proofs,
            run_id, job.transaction_hash, session
        )
        if value is None or value.get("catalog_digest_sha256") != job.inclusion_catalog_digest_sha256:
            raise CaseEvidenceStoredConflict("Transaction inclusion binding changed.")
        if not _canonical_inclusion_proven(value, expected_network=job.network):
            raise CaseEvidenceStoredConflict(
                "Transaction inclusion did not prove the canonical block chain."
            )
        values["block_inclusion"] = value
    if job.native_ledger_id is not None:
        value = _legacy_artifact_read(
            get_wallet_native_activity_ledger,
            run_id,
            job.transaction_hash,
            session,
        )
        _binding(value, job.native_ledger_id, job.native_ledger_digest_sha256, "ledger_id")
        values["native_ledger"] = value
    return values


def _legacy_artifact_read(reader, *args):
    try:
        return reader(*args)
    except (
        WalletPersistedTraceEvidenceConflict,
        WalletTraceBocVerificationConflict,
        WalletTransactionInclusionProofConflict,
        WalletNativeActivityLedgerConflict,
    ) as exc:
        raise CaseEvidenceStoredConflict(
            "Stored evidence artifact failed local revalidation."
        ) from exc


def _validate_artifact_prefix(job: CaseEvidenceVerification) -> None:
    coordinates = (
        (job.trace_capture_id, job.trace_digest_sha256, job.trace_completed_at),
        (job.boc_verification_id, job.boc_digest_sha256, job.boc_completed_at),
        (job.inclusion_catalog_digest_sha256, job.inclusion_completed_at),
        (
            job.native_ledger_id,
            job.native_ledger_digest_sha256,
            job.native_ledger_completed_at,
        ),
    )
    completed: list[bool] = []
    for values in coordinates:
        present = tuple(value is not None for value in values)
        if any(present) and not all(present):
            raise CaseEvidenceStoredConflict(
                "Evidence artifact coordinates are incomplete."
            )
        completed.append(all(present))
    expected = [index < job.progress_current for index in range(4)]
    if completed != expected:
        raise CaseEvidenceStoredConflict(
            "Evidence artifacts do not form the canonical proof prefix."
        )
    expected_level = (
        "chain_inclusion_proven"
        if job.progress_current >= 3
        else "locally_verified"
        if job.progress_current == 2
        else "normalized"
    )
    if job.highest_evidence_level != expected_level:
        raise CaseEvidenceStoredConflict(
            "Evidence level does not match the canonical proof prefix."
        )


def _artifact_cache_key(job: CaseEvidenceVerification) -> tuple[Any, ...]:
    return (
        job.source_sync_id,
        job.source_transaction_id,
        job.transaction_hash,
        job.trace_capture_id,
        job.trace_digest_sha256,
        job.boc_verification_id,
        job.boc_digest_sha256,
        job.inclusion_catalog_digest_sha256,
        job.native_ledger_id,
        job.native_ledger_digest_sha256,
    )


def _canonical_inclusion_proven(
    value: Any,
    *,
    expected_network: str | None = None,
) -> bool:
    return _inclusion_provenance(
        value,
        expected_network=expected_network,
    ) is not None


def _inclusion_provenance(
    value: Any,
    *,
    expected_network: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    proofs = value.get("proofs")
    checkpoint = value.get("trusted_checkpoint")
    if (
        value.get("contract_version") != "ton_transaction_inclusion_v2"
        or value.get("verifier_policy_id") != CURRENT_VERIFIER_POLICY_ID
        or not isinstance(proofs, list)
        or not proofs
        or not isinstance(checkpoint, dict)
        or set(checkpoint) != {
            "workchain", "shard", "seqno", "root_hash", "file_hash"
        }
        or value.get("all_transaction_bocs_included_in_blocks") is not True
    ):
        return None
    networks = {
        proof.get("network")
        for proof in proofs
        if isinstance(proof, dict)
    }
    if len(networks) != 1:
        return None
    network = next(iter(networks))
    if network not in {"ton-mainnet", "ton-testnet"} or (
        expected_network is not None and network != expected_network
    ):
        return None
    try:
        internal_checkpoint = dict(checkpoint)
        if (
            not isinstance(internal_checkpoint["shard"], str)
            or internal_checkpoint["shard"]
            != str(int(internal_checkpoint["shard"]))
        ):
            return None
        internal_checkpoint["shard"] = int(internal_checkpoint["shard"])
    except (TypeError, ValueError):
        return None
    if not is_current_trusted_checkpoint(
        network,
        CURRENT_VERIFIER_POLICY_ID,
        internal_checkpoint,
    ):
        return None
    if any(
        not isinstance(proof, dict)
        or proof.get("contract_version") != "ton_transaction_inclusion_v2"
        or proof.get("evidence_contract_version")
        != "ton_transaction_inclusion_v2"
        or proof.get("network") != network
        or proof.get("verifier_policy_id") != CURRENT_VERIFIER_POLICY_ID
        or proof.get("trusted_checkpoint") != checkpoint
        or proof.get("trust_level") != 0
        or proof.get("block_merkle_proof_verified") is not True
        or proof.get("canonical_block_chain_verified_at_capture") is not True
        or proof.get("checkpoint_to_observed_head_transcript_persisted") is not False
        or proof.get("provider_free_revalidated") is not True
        for proof in proofs
    ):
        return None
    return {
        "contract_version": "ton_transaction_inclusion_v2",
        "network": network,
        "verifier_policy_id": CURRENT_VERIFIER_POLICY_ID,
        "trust_level": 0,
        "trusted_checkpoint": dict(checkpoint),
        "canonical_block_chain_verified_at_capture": True,
        "checkpoint_to_observed_head_transcript_persisted": False,
    }


def _binding(
    value: dict[str, Any] | None,
    internal_id: int,
    digest: str | None,
    id_field: str,
) -> None:
    if (
        value is None
        or value.get(id_field) != str(internal_id)
        or value.get("evidence_digest_sha256") != digest
    ):
        raise CaseEvidenceStoredConflict("Stored evidence artifact binding changed.")


def _steps(
    job: CaseEvidenceVerification,
    artifacts: dict[str, dict[str, Any] | None],
) -> list[dict[str, Any]]:
    definitions = (
        ("trace_capture", "normalized", job.trace_digest_sha256, job.trace_completed_at),
        ("boc_verification", "locally_verified", job.boc_digest_sha256, job.boc_completed_at),
        (
            "block_inclusion",
            "chain_inclusion_proven",
            job.inclusion_catalog_digest_sha256,
            job.inclusion_completed_at,
        ),
        (
            "native_ledger",
            "chain_inclusion_proven",
            job.native_ledger_digest_sha256,
            job.native_ledger_completed_at,
        ),
    )
    result = []
    for code, level, digest, completed_at in definitions:
        complete = artifacts[code] is not None
        if complete != (digest is not None and completed_at is not None):
            raise CaseEvidenceStoredConflict("Evidence step completion is incoherent.")
        result.append({
            "code": code,
            "state": "succeeded" if complete else "pending",
            "evidence_level": level if complete else None,
            "evidence_digest_sha256": digest if complete else None,
            "completed_at": _iso(completed_at) if complete else None,
        })
    return result


def _result_digest(
    job: CaseEvidenceVerification,
    artifacts: dict[str, dict[str, Any] | None],
) -> str:
    return _digest({
        "contract": "case_evidence_verification_result_v2",
        "case_public_id": job.case.public_id,
        "snapshot_public_id": job.snapshot_sync.public_id,
        "activity_public_id": job.activity_public_id,
        "activity_semantic_fingerprint": job.activity_semantic_fingerprint,
        "policy": job.policy,
        "network": job.network,
        "wallet_account_canonical": job.wallet_account_canonical,
        "transaction_hash": job.transaction_hash,
        "transaction_logical_time": job.transaction_logical_time,
        "highest_evidence_level": job.highest_evidence_level,
        "inclusion_provenance": _inclusion_provenance(
            artifacts["block_inclusion"],
            expected_network=job.network,
        ),
        "artifact_digests": {
            key: None if value is None else (
                value.get("catalog_digest_sha256")
                if key == "block_inclusion"
                else value.get("evidence_digest_sha256")
            )
            for key, value in artifacts.items()
        },
    })


def _snapshot(sync: CaseSync) -> dict[str, Any]:
    return {
        "public_id": sync.public_id,
        "state": sync.state,
        "completed_at": _iso(sync.completed_at),
        "data_mode": sync.data_mode,
        "provider": sync.provider,
        "requested_period": {
            "start_at": _iso(sync.requested_start),
            "end_at": _iso(sync.requested_end),
        },
        "coverage": _stored_coverage(sync),
    }


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _message(value: Any) -> str:
    return (str(value or "Evidence verification state is available.").strip() or "Evidence verification state is available.")[:1000]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "CaseEvidenceActivityNotFound",
    "CaseEvidenceAlreadyActive",
    "CaseEvidenceIdempotencyConflict",
    "CaseEvidenceIneligible",
    "CaseEvidenceNotFound",
    "CaseEvidenceRuntimeUnavailable",
    "CaseEvidenceScopeTooLarge",
    "CaseEvidenceService",
    "CaseEvidenceSnapshotConflict",
    "CaseEvidenceSnapshotNotFound",
    "CaseEvidenceStoredConflict",
    "case_evidence_runtime_limitation",
    "_checkpoint",
    "_result_digest",
]
