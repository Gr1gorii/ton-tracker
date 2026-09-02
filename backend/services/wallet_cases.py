"""Wallet Case application service over the existing ingestion subsystem."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import secrets
from typing import Any

from sqlalchemy import delete, exists, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from adapters.wallet_activity import get_wallet_activity_provider_status
from config import get_settings
from models import (
    CaseEvidenceVerification,
    CaseSync,
    LOCAL_SINGLE_USER_SCOPE,
    WalletCase,
    WalletCaseCatalogEvent,
    WalletCaseLifecycleEvent,
    WalletCaseReportRevision,
    WalletCaseStreamCheckpoint,
    WalletCaseSyncManifest,
    WalletIngestionRun,
)
from repositories.wallet_cases import WalletCaseRepository
from services.ton_address_identity import derive_ton_wallet_identity
from services.wallet_acquisition_bounds import resolve_wallet_acquisition_bounds
from services.wallet_case_sync_manifests import (
    MANIFEST_CONTRACT_VERSION,
    verify_wallet_case_sync_manifest,
)
from services.wallet_case_stream_checkpoints import (
    CHECKPOINT_CONTRACT_VERSION,
    verify_wallet_case_stream_checkpoint,
)
from wallet_case_schemas import (
    WalletCaseCreateRequest,
    WalletCaseMetadataUpdateRequest,
    WalletCaseSyncRequest,
)


class WalletCaseNotFound(LookupError):
    """Raised when an owner-scoped public case resource does not exist."""


class WalletCaseRuntimeConflict(RuntimeError):
    """Raised when runtime configuration cannot satisfy a case contract."""


class WalletCaseSyncAlreadyActive(RuntimeError):
    """Raised when a different active synchronization owns the case slot."""

    def __init__(self, public_id: str) -> None:
        super().__init__("This Wallet Case already has an active synchronization.")
        self.public_id = public_id


class WalletCaseIdempotencyConflict(RuntimeError):
    """Raised when an idempotency key is reused for another request body."""


class WalletCaseDeletionConflict(RuntimeError):
    """Raised when active case-owned work makes deletion unsafe."""

    def __init__(
        self,
        *,
        active_sync_public_id: str | None,
        active_evidence_public_id: str | None,
    ) -> None:
        super().__init__(
            "Cancel or wait for active Wallet Case jobs before deleting this case."
        )
        self.active_sync_public_id = active_sync_public_id
        self.active_evidence_public_id = active_evidence_public_id


class WalletCaseArchiveConflict(RuntimeError):
    """Raised when active case-owned work makes archival unsafe."""

    def __init__(
        self,
        *,
        active_sync_public_id: str | None,
        active_evidence_public_id: str | None,
    ) -> None:
        super().__init__(
            "Cancel or wait for active Wallet Case jobs before archiving this case."
        )
        self.active_sync_public_id = active_sync_public_id
        self.active_evidence_public_id = active_evidence_public_id


class WalletCaseMetadataConflict(RuntimeError):
    """Raised when an update is based on stale Case metadata."""

    def __init__(self, current_metadata_version: int) -> None:
        super().__init__(
            "Wallet Case metadata changed after this editor was opened."
        )
        self.current_metadata_version = current_metadata_version


class WalletCaseCatalogInvalidCursor(ValueError):
    """Raised when a Case catalog continuation cannot be authenticated."""

    code = "invalid_case_catalog_cursor"


class WalletCaseCheckpointHistoryInvalidCursor(ValueError):
    """Raised when checkpoint history continuation cannot be authenticated."""

    code = "invalid_checkpoint_history_cursor"


class WalletCaseIncrementalSyncUnavailable(RuntimeError):
    """Raised when a Case has no safe forward-refresh baseline."""


class WalletCaseSyncManifestNotFound(LookupError):
    """Raised when a sync has no published acquisition manifest."""


class WalletCaseSyncManifestCorrupt(RuntimeError):
    """Raised when persisted manifest evidence fails integrity validation."""


class WalletCaseStreamCheckpointCorrupt(RuntimeError):
    """Raised when persisted provider continuation state fails validation."""


class WalletCaseCheckpointResumeUnavailable(RuntimeError):
    """Raised when a checkpoint cannot safely start a continuation job."""


class WalletCaseContinuationPlanStale(RuntimeError):
    """Raised when a resume request is bound to a superseded plan."""

    def __init__(self, current_plan_public_id: str) -> None:
        super().__init__(
            "Continuation Plan changed; verify the current plan before resuming."
        )
        self.current_plan_public_id = current_plan_public_id


class WalletCaseBackfillScheduleStale(RuntimeError):
    """Raised when execution is bound to a superseded schedule."""

    def __init__(self, current_public_id: str, current_state: str) -> None:
        super().__init__(
            "Backfill Schedule changed; verify the current schedule before running it."
        )
        self.current_public_id = current_public_id
        self.current_state = current_state


class WalletCaseBackfillScheduleUnavailable(RuntimeError):
    """Raised when the current schedule has no executable selection."""

    def __init__(self, state: str, active_sync_public_id: str | None) -> None:
        super().__init__(
            "This Backfill Schedule is not ready to enqueue a provider request."
        )
        self.state = state
        self.active_sync_public_id = active_sync_public_id


class WalletCaseContinuationReceiptNotFound(LookupError):
    """Raised when a sync did not publish a plan-bound continuation result."""

    code = "continuation_receipt_not_available"


_ENVIRONMENT_DATA_MODE = {"demo": "mock", "live": "real"}
_SYNC_PROGRESS_TOTAL = 3
_CASE_CATALOG_CURSOR_KEY = secrets.token_bytes(32)
_CASE_CATALOG_CURSOR_VERSION = 3
_CHECKPOINT_HISTORY_CURSOR_KEY = secrets.token_bytes(32)
_CHECKPOINT_HISTORY_CURSOR_VERSION = 1
_MAX_CHECKPOINT_CHAIN_REVISIONS = 100
_MAX_CHECKPOINT_CONTINUATION_PLAN_STREAMS = 32
_INCREMENTAL_OVERLAP = timedelta(minutes=15)
_ACQUISITION_PLAN_KEY = "_acquisition"
_UNSET = object()
_ZERO_SUMMARY: dict[str, Any] = {
    "activity_counts": {
        "transfers": 0,
        "transactions": 0,
        "swaps": 0,
        "balances": 0,
    },
    "failed_transaction_count": 0,
    "warning_count": 0,
    "portfolio_snapshot": {
        "total_balance_usd": None,
        "priced_assets": 0,
        "unpriced_assets": 0,
    },
}


class WalletCaseService:
    """Create, load, synchronize and summarize local Wallet Cases."""

    def __init__(
        self,
        session: Session,
        *,
        owner_scope_id: str = LOCAL_SINGLE_USER_SCOPE,
    ) -> None:
        self.session = session
        self.owner_scope_id = owner_scope_id
        self.repository = WalletCaseRepository(session)

    def create_or_open_case(
        self,
        payload: WalletCaseCreateRequest,
        *,
        settings=None,
    ) -> dict[str, Any]:
        identity = derive_ton_wallet_identity(
            payload.wallet_address,
            network_context=payload.network,
        )
        if identity.status != "network_scoped" or not identity.canonical_address:
            raise ValueError("A valid canonical TON wallet address is required.")
        if identity.network != payload.network:
            raise ValueError(
                "Wallet address network does not match the requested network."
            )
        if (
            payload.data_environment == "live"
            and identity.workchain_id not in (-1, 0)
        ):
            raise ValueError(
                "Live TonAPI Wallet Cases support standard workchains -1 and 0 only."
            )

        existing = self.repository.get_by_identity(
            owner_scope_id=self.owner_scope_id,
            network=payload.network,
            data_environment=payload.data_environment,
            canonical_wallet_key=identity.canonical_address,
        )
        if existing is not None:
            if existing.archived_at is not None:
                reopened_at = _utc_now()
                existing.archived_at = None
                existing.updated_at = reopened_at
                self._record_catalog_event(existing, recorded_at=reopened_at)
                self.session.commit()
            return {
                "created": False,
                "case": self._case_response(
                    existing,
                    latest_sync=self._latest_sync(existing),
                ),
            }

        # Do not persist a new live case that this runtime cannot ever sync.
        # Existing cases remain readable if operators later disable live access.
        self._settings_for_scope(
            network=payload.network,
            data_environment=payload.data_environment,
            settings=settings or get_settings(),
        )

        now = _utc_now()
        wallet_case = WalletCase(
            owner_scope_id=self.owner_scope_id,
            network=payload.network,
            data_environment=payload.data_environment,
            canonical_wallet_key=identity.canonical_address,
            canonical_identity_version=identity.version,
            display_address=payload.wallet_address,
            label=payload.label,
            note=payload.note,
            created_at=now,
            updated_at=now,
        )
        self.repository.add_case(wallet_case)
        self._record_catalog_event(wallet_case, recorded_at=now)
        try:
            self.session.commit()
        except IntegrityError:
            # A concurrent create may have won the unique scope/identity race.
            self.session.rollback()
            existing = self.repository.get_by_identity(
                owner_scope_id=self.owner_scope_id,
                network=payload.network,
                data_environment=payload.data_environment,
                canonical_wallet_key=identity.canonical_address,
            )
            if existing is None:
                raise
            return {
                "created": False,
                "case": self._case_response(
                    existing,
                    latest_sync=self._latest_sync(existing),
                ),
            }
        self.session.refresh(wallet_case)
        return {"created": True, "case": self._case_response(wallet_case)}

    def list_cases(
        self,
        *,
        limit: int,
        state: str = "active",
        query: str | None = None,
        network: str | None = None,
        data_environment: str | None = None,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 50:
            raise WalletCaseCatalogInvalidCursor(
                "Wallet Case catalog limit must be between 1 and 50."
            )
        if state not in {"active", "archived"}:
            raise WalletCaseCatalogInvalidCursor(
                "Wallet Case catalog state must be active or archived."
            )
        if query is not None:
            query = query.strip()
            if not query or len(query) > 120:
                raise WalletCaseCatalogInvalidCursor(
                    "Wallet Case catalog query must contain 1 through 120 characters."
                )
        if network not in {None, "ton-mainnet", "ton-testnet"}:
            raise WalletCaseCatalogInvalidCursor(
                "Wallet Case catalog network is invalid."
            )
        if data_environment not in {None, "demo", "live"}:
            raise WalletCaseCatalogInvalidCursor(
                "Wallet Case catalog data environment is invalid."
            )
        cursor_document = (
            _decode_case_catalog_cursor(cursor) if cursor is not None else None
        )
        scope_digest = _case_catalog_scope_digest(self.owner_scope_id)
        filter_digest = _case_catalog_filter_digest(
            query=query,
            network=network,
            data_environment=data_environment,
        )
        if (
            cursor_document is not None
            and cursor_document["scope"] != scope_digest
        ):
            raise WalletCaseCatalogInvalidCursor(
                "Wallet Case catalog cursor belongs to another owner scope."
            )
        if cursor_document is not None and cursor_document["state"] != state:
            raise WalletCaseCatalogInvalidCursor(
                "Wallet Case catalog cursor belongs to another lifecycle state."
            )
        if (
            cursor_document is not None
            and cursor_document["filters"] != filter_digest
        ):
            raise WalletCaseCatalogInvalidCursor(
                "Wallet Case catalog cursor belongs to another filter set."
            )
        cutoff = (
            int(cursor_document["cutoff"])
            if cursor_document is not None
            else self.repository.catalog_cutoff(
                owner_scope_id=self.owner_scope_id
            )
        )
        after = (
            int(cursor_document["after"])
            if cursor_document is not None
            else None
        )
        if cutoff is None:
            return {
                "cases": [],
                "limit": limit,
                "state": state,
                "query": query,
                "network": network,
                "data_environment": data_environment,
                "truncated": False,
                "next_cursor": None,
            }
        positioned_cases, truncated = self.repository.list_at_catalog_cutoff(
            owner_scope_id=self.owner_scope_id,
            archived=state == "archived",
            query=query,
            network=network,
            data_environment=data_environment,
            limit=limit,
            cutoff=cutoff,
            after=after,
        )
        cases = [wallet_case for wallet_case, _position in positioned_cases]
        latest_syncs = self.repository.latest_syncs(
            [wallet_case.id for wallet_case in cases]
        )
        active_syncs = self.repository.active_syncs(
            [wallet_case.id for wallet_case in cases]
        )
        usable_syncs = self.repository.latest_usable_syncs(
            [wallet_case.id for wallet_case in cases]
        )
        next_cursor = None
        if truncated:
            next_cursor = _encode_case_catalog_cursor(
                {
                    "v": _CASE_CATALOG_CURSOR_VERSION,
                    "scope": scope_digest,
                    "state": state,
                    "filters": filter_digest,
                    "cutoff": cutoff,
                    "after": positioned_cases[-1][1],
                }
            )
        return {
            "cases": [
                self._case_response(
                    wallet_case,
                    latest_sync=latest_syncs.get(wallet_case.id),
                    active_sync=active_syncs.get(wallet_case.id),
                    current_snapshot=usable_syncs.get(wallet_case.id),
                )
                for wallet_case in cases
            ],
            "limit": limit,
            "state": state,
            "query": query,
            "network": network,
            "data_environment": data_environment,
            "truncated": truncated,
            "next_cursor": next_cursor,
        }

    def get_case(self, public_id: str) -> dict[str, Any]:
        wallet_case = self._required_case(public_id)
        latest_sync = self._latest_sync(wallet_case)
        active_sync = self.repository.get_active_sync(case_id=wallet_case.id)
        current_snapshot = self.repository.latest_usable_syncs(
            [wallet_case.id]
        ).get(wallet_case.id)
        return self._case_response(
            wallet_case,
            latest_sync=latest_sync,
            active_sync=active_sync,
            current_snapshot=current_snapshot,
        )

    def update_case_metadata(
        self,
        public_id: str,
        payload: WalletCaseMetadataUpdateRequest,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Update mutable presentation fields with optimistic concurrency."""
        wallet_case = self._required_case(public_id)
        values: dict[str, Any] = {
            "metadata_version": WalletCase.metadata_version + 1,
            "updated_at": _as_utc(now or _utc_now()),
        }
        if "label" in payload.model_fields_set:
            values["label"] = payload.label
        if "note" in payload.model_fields_set:
            values["note"] = payload.note

        changed = self.session.execute(
            update(WalletCase)
            .where(
                WalletCase.id == wallet_case.id,
                WalletCase.owner_scope_id == self.owner_scope_id,
                WalletCase.public_id == public_id,
                WalletCase.archived_at.is_(None),
                WalletCase.metadata_version == payload.expected_metadata_version,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            self.session.rollback()
            current = self.repository.get_by_public_id(
                owner_scope_id=self.owner_scope_id,
                public_id=public_id,
            )
            if current is None:
                raise WalletCaseNotFound("Wallet Case not found")
            raise WalletCaseMetadataConflict(current.metadata_version)

        self._record_catalog_event(wallet_case, recorded_at=values["updated_at"])
        self.session.commit()
        refreshed = self._required_case(public_id)
        return self._case_response(
            refreshed,
            latest_sync=self._latest_sync(refreshed),
        )

    def archive_case(
        self,
        public_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Hide one Case from active workflows without deleting its evidence."""
        wallet_case = self.repository.get_any_by_public_id(
            owner_scope_id=self.owner_scope_id,
            public_id=public_id,
        )
        if wallet_case is None:
            raise WalletCaseNotFound("Wallet Case not found")
        if wallet_case.archived_at is not None:
            return self._case_response(
                wallet_case,
                latest_sync=self._latest_sync(wallet_case),
                active_sync=None,
            )

        self._raise_if_archive_conflicts(wallet_case.id)
        archived_at = _as_utc(now or _utc_now())
        changed = self.session.execute(
            update(WalletCase)
            .where(
                WalletCase.id == wallet_case.id,
                WalletCase.owner_scope_id == self.owner_scope_id,
                WalletCase.public_id == public_id,
                WalletCase.archived_at.is_(None),
                ~exists().where(
                    CaseSync.case_id == wallet_case.id,
                    CaseSync.state.in_(("queued", "running")),
                ),
                ~exists().where(
                    CaseEvidenceVerification.case_id == wallet_case.id,
                    CaseEvidenceVerification.state.in_(("queued", "running")),
                ),
            )
            .values(archived_at=archived_at, updated_at=archived_at)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            self.session.rollback()
            current = self.repository.get_any_by_public_id(
                owner_scope_id=self.owner_scope_id,
                public_id=public_id,
            )
            if current is None:
                raise WalletCaseNotFound("Wallet Case not found")
            if current.archived_at is not None:
                return self._case_response(
                    current,
                    latest_sync=self._latest_sync(current),
                    active_sync=None,
                )
            self._raise_if_archive_conflicts(current.id)
            raise WalletCaseRuntimeConflict(
                "Wallet Case changed while archival was being prepared."
            )
        self._record_catalog_event(
            wallet_case,
            recorded_at=archived_at,
            visible=False,
        )
        self.session.commit()
        refreshed = self.repository.get_any_by_public_id(
            owner_scope_id=self.owner_scope_id,
            public_id=public_id,
        )
        if refreshed is None:
            raise WalletCaseNotFound("Wallet Case not found")
        return self._case_response(
            refreshed,
            latest_sync=self._latest_sync(refreshed),
            active_sync=None,
        )

    def restore_case(
        self,
        public_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Restore an archived Case as the newest active catalog entry."""
        wallet_case = self.repository.get_any_by_public_id(
            owner_scope_id=self.owner_scope_id,
            public_id=public_id,
        )
        if wallet_case is None:
            raise WalletCaseNotFound("Wallet Case not found")
        if wallet_case.archived_at is None:
            return self._case_response(
                wallet_case,
                latest_sync=self._latest_sync(wallet_case),
            )

        restored_at = _as_utc(now or _utc_now())
        changed = self.session.execute(
            update(WalletCase)
            .where(
                WalletCase.id == wallet_case.id,
                WalletCase.owner_scope_id == self.owner_scope_id,
                WalletCase.public_id == public_id,
                WalletCase.archived_at.is_not(None),
            )
            .values(archived_at=None, updated_at=restored_at)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            self.session.rollback()
            current = self.repository.get_any_by_public_id(
                owner_scope_id=self.owner_scope_id,
                public_id=public_id,
            )
            if current is None:
                raise WalletCaseNotFound("Wallet Case not found")
            if current.archived_at is None:
                return self._case_response(
                    current,
                    latest_sync=self._latest_sync(current),
                )
            raise WalletCaseRuntimeConflict(
                "Wallet Case changed while restoration was being prepared."
            )
        self._record_catalog_event(wallet_case, recorded_at=restored_at)
        self.session.commit()
        refreshed = self._required_case(public_id)
        return self._case_response(
            refreshed,
            latest_sync=self._latest_sync(refreshed),
        )

    def delete_case(
        self,
        public_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Delete one owner-scoped case and its uniquely owned persisted data."""
        wallet_case = self._required_case(public_id)
        self._raise_if_delete_conflicts(wallet_case.id)
        self._acquire_delete_write_fence(wallet_case)

        ingestion_runs = list(
            self.session.scalars(
                select(WalletIngestionRun)
                .join(CaseSync, CaseSync.ingestion_run_id == WalletIngestionRun.id)
                .where(CaseSync.case_id == wallet_case.id)
            )
        )
        removed = {
            "syncs": self._row_count(CaseSync, CaseSync.case_id == wallet_case.id),
            "ingestion_runs": len(ingestion_runs),
            "evidence_verifications": self._row_count(
                CaseEvidenceVerification,
                CaseEvidenceVerification.case_id == wallet_case.id,
            ),
            "report_revisions": self._row_count(
                WalletCaseReportRevision,
                WalletCaseReportRevision.case_id == wallet_case.id,
            ),
        }
        deleted_at = _as_utc(now or _utc_now())
        case_delete = self.session.execute(
            delete(WalletCase)
            .where(
                WalletCase.id == wallet_case.id,
                WalletCase.owner_scope_id == self.owner_scope_id,
                ~exists().where(
                    CaseSync.case_id == wallet_case.id,
                    CaseSync.state.in_(("queued", "running")),
                ),
                ~exists().where(
                    CaseEvidenceVerification.case_id == wallet_case.id,
                    CaseEvidenceVerification.state.in_(("queued", "running")),
                ),
            )
            .execution_options(synchronize_session=False)
        )
        if case_delete.rowcount != 1:
            self._raise_delete_changed(public_id)

        audit_event = WalletCaseLifecycleEvent(
            owner_scope_id=self.owner_scope_id,
            case_public_id=wallet_case.public_id,
            event_type="deleted",
            occurred_at=deleted_at,
            details_json=_json_dumps({"removed": removed}),
        )
        self.session.add(audit_event)
        self.session.flush()
        audit_event_public_id = audit_event.public_id

        # The original ingestion tables predate database-level cascades. Use
        # their complete ORM ownership graph after the CaseSync RESTRICT edge
        # has been removed, so normalized rows and proof artifacts disappear
        # in dependency order without touching unrelated legacy runs.
        for ingestion_run in ingestion_runs:
            self.session.delete(ingestion_run)
        self.session.flush()
        self.session.commit()
        return {
            "deleted": True,
            "case_public_id": public_id,
            "audit_event_public_id": audit_event_public_id,
            "deleted_at": _isoformat(deleted_at),
            "removed": removed,
        }

    def enqueue_sync(
        self,
        public_id: str,
        payload: WalletCaseSyncRequest,
        idempotency_key: str,
        *,
        settings=None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        wallet_case = self._required_case(public_id)
        fingerprint = _sync_request_fingerprint(payload)
        replay = self.repository.get_by_idempotency_key(
            case_id=wallet_case.id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            if replay.request_fingerprint != fingerprint:
                raise WalletCaseIdempotencyConflict(
                    "Idempotency-Key was already used for another sync scope."
                )
            return self._sync_response(replay, case_public_id=wallet_case.public_id), True

        active = self.repository.get_active_sync(case_id=wallet_case.id)
        if active is not None:
            active_public_id = active.public_id
            # A same-key caller can commit between the first idempotency read
            # and the active-selection read. Refresh the transaction snapshot
            # and let idempotent replay take precedence over active conflict.
            self.session.rollback()
            replay = self.repository.get_by_idempotency_key(
                case_id=wallet_case.id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                if replay.request_fingerprint != fingerprint:
                    raise WalletCaseIdempotencyConflict(
                        "Idempotency-Key was already used for another sync scope."
                    )
                return self._sync_response(
                    replay,
                    case_public_id=wallet_case.public_id,
                ), True
            raise WalletCaseSyncAlreadyActive(active_public_id)

        queued_at = _as_utc(now or _utc_now())
        ingestion_settings = self._settings_for_case(
            wallet_case,
            settings or get_settings(),
        )
        if payload.mode == "incremental":
            base_sync = self.repository.latest_usable_syncs(
                [wallet_case.id]
            ).get(wallet_case.id)
            if base_sync is None:
                raise WalletCaseIncrementalSyncUnavailable(
                    "Build a usable bounded snapshot before requesting an incremental refresh."
                )
            if set(_json_list(base_sync.requested_surfaces_json)) != set(
                payload.surfaces
            ):
                raise WalletCaseIncrementalSyncUnavailable(
                    "Incremental refresh surfaces must match the base snapshot."
                )
            base_end = _as_utc(base_sync.requested_end)
            if queued_at <= base_end:
                raise WalletCaseIncrementalSyncUnavailable(
                    "The base snapshot already reaches or exceeds the current refresh time."
                )
            requested_start = _as_utc(base_sync.requested_start)
            requested_end = queued_at
            acquisition_start = max(
                requested_start,
                base_end - _INCREMENTAL_OVERLAP,
            )
            acquisition_plan = {
                "version": 1,
                "mode": "incremental",
                "start_at": _isoformat(acquisition_start),
                "end_at": _isoformat(requested_end),
                "overlap_seconds": max(
                    0,
                    int((base_end - acquisition_start).total_seconds()),
                ),
                "base_snapshot_public_id": base_sync.public_id,
            }
            stored_time_window = "custom"
        else:
            bounds = resolve_wallet_acquisition_bounds(
                time_window=payload.time_window,
                custom_start=payload.custom_start,
                custom_end=payload.custom_end,
                now=queued_at,
            )
            requested_start = bounds.start
            requested_end = bounds.end
            acquisition_plan = {
                "version": 1,
                "mode": "bounded",
                "start_at": _isoformat(bounds.start),
                "end_at": _isoformat(bounds.end),
                "overlap_seconds": 0,
                "base_snapshot_public_id": None,
            }
            stored_time_window = payload.time_window
        expected_data_mode = _ENVIRONMENT_DATA_MODE[wallet_case.data_environment]
        coverage = _coverage_record(
            {"requested_surfaces": payload.surfaces, "data_mode": expected_data_mode},
            start_at=requested_start,
            end_at=requested_end,
            state="queued",
            requested_surfaces=payload.surfaces,
            acquisition_plan=acquisition_plan,
        )
        case_sync = CaseSync(
            case=wallet_case,
            time_window=stored_time_window,
            data_mode=expected_data_mode,
            provider=_queued_provider(ingestion_settings),
            requested_start=requested_start,
            requested_end=requested_end,
            requested_surfaces_json=_json_dumps(payload.surfaces),
            state="queued",
            stage="queued",
            progress_current=0,
            progress_total=_SYNC_PROGRESS_TOTAL,
            coverage_summary_json=_json_dumps(coverage),
            result_summary_json="{}",
            message_safe="Wallet Case synchronization is queued.",
            created_at=queued_at,
            updated_at=queued_at,
            status_version=1,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            attempt_count=0,
            max_attempts=int(ingestion_settings.wallet_case_job_max_attempts),
            next_attempt_at=queued_at,
            checkpoint_json=_json_dumps(
                {"version": "case_sync_monolithic_v1", "phase": "queued"}
            ),
        )
        wallet_case.updated_at = queued_at
        self._record_catalog_event(wallet_case, recorded_at=queued_at)
        self.repository.add_sync(case_sync)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            replay = self.repository.get_by_idempotency_key(
                case_id=wallet_case.id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                if replay.request_fingerprint != fingerprint:
                    raise WalletCaseIdempotencyConflict(
                        "Idempotency-Key was already used for another sync scope."
                    )
                return self._sync_response(
                    replay,
                    case_public_id=wallet_case.public_id,
                ), True
            active = self.repository.get_active_sync(case_id=wallet_case.id)
            if active is not None:
                raise WalletCaseSyncAlreadyActive(active.public_id)
            raise
        self.session.refresh(case_sync)
        response = self._sync_response(
            case_sync,
            case_public_id=wallet_case.public_id,
        )
        # End the post-commit refresh transaction before the router wakes the
        # detached worker. Provider I/O never inherits a request Session.
        self.session.rollback()
        return response, False

    def get_sync(self, case_public_id: str, sync_public_id: str) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        case_sync = self.repository.get_sync(
            case_id=wallet_case.id,
            public_id=sync_public_id,
        )
        if case_sync is None:
            raise WalletCaseNotFound("Wallet Case sync not found")
        return self._sync_response(case_sync, case_public_id=wallet_case.public_id)

    def enqueue_checkpoint_resume(
        self,
        case_public_id: str,
        checkpoint_public_id: str,
        idempotency_key: str,
        *,
        continuation_plan_public_id: str | None = None,
        page_budget: int | None = None,
        backfill_schedule_public_id: str | None = None,
        settings=None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Queue one continuation only from the latest verified ready checkpoint."""
        wallet_case = self._required_case(case_public_id)
        checkpoint = self.repository.get_stream_checkpoint(
            case_id=wallet_case.id,
            public_id=checkpoint_public_id,
        )
        if checkpoint is None:
            raise WalletCaseNotFound("Wallet Case stream checkpoint not found")
        checkpoint_response = _stream_checkpoint_response(
            checkpoint,
            case_public_id=wallet_case.public_id,
        )
        descriptor = checkpoint_response["checkpoint"]
        document = checkpoint_response["document"]
        latest = {
            (item.provider, item.stream_key): item.public_id
            for item in self.repository.latest_stream_checkpoints(
                case_id=wallet_case.id
            )
        }
        stream_identity = (checkpoint.provider, checkpoint.stream_key)
        if latest.get(stream_identity) != checkpoint.public_id:
            raise WalletCaseCheckpointResumeUnavailable(
                "Only the latest verified checkpoint for a provider stream can be resumed."
            )
        if descriptor["resume_state"] != "ready":
            raise WalletCaseCheckpointResumeUnavailable(
                "This provider stream checkpoint is not ready to resume."
            )
        if checkpoint.provider != "tonapi":
            raise WalletCaseCheckpointResumeUnavailable(
                "This checkpoint provider is not supported by resume execution."
            )
        source_sync = checkpoint.source_sync
        if (
            source_sync.case_id != wallet_case.id
            or source_sync.state not in {"partial", "succeeded"}
            or source_sync.ingestion_run_id is None
        ):
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case stream checkpoint source sync is unusable."
            )
        source_surfaces = _json_list(source_sync.requested_surfaces_json)
        if checkpoint.stream_key == "transactions":
            resumed_surfaces = [
                surface for surface in source_surfaces if surface == "transactions"
            ]
        elif checkpoint.stream_key == "account_events":
            resumed_surfaces = [
                surface
                for surface in source_surfaces
                if surface in {"transfers", "swaps"}
            ]
        else:
            raise WalletCaseCheckpointResumeUnavailable(
                "This provider stream does not have a supported resume adapter."
            )
        if not resumed_surfaces:
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case stream checkpoint has no matching source surface."
            )
        requested_period = document.get("requested_period")
        if not isinstance(requested_period, dict):
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case stream checkpoint period is invalid."
            )
        try:
            acquisition_start_text = _canonical_request_timestamp(
                requested_period["start_at"]
            )
            acquisition_end_text = _canonical_request_timestamp(
                requested_period["end_at"]
            )
            acquisition_start = _parse_canonical_timestamp(
                acquisition_start_text
            )
            acquisition_end = _parse_canonical_timestamp(acquisition_end_text)
        except (KeyError, TypeError, ValueError) as exc:
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case stream checkpoint period is invalid."
            ) from exc
        requested_start = _as_utc(source_sync.requested_start)
        requested_end = _as_utc(source_sync.requested_end)
        if (
            acquisition_start < requested_start
            or acquisition_end != requested_end
            or acquisition_start >= acquisition_end
        ):
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case stream checkpoint period escaped its source sync."
            )
        cursor = document.get("continuation_cursor")
        page_index = document.get("continuation_page_index")
        if _strict_logical_time(cursor) is None or (
            type(page_index) is not int or page_index < 1
        ):
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case stream checkpoint continuation is invalid."
            )

        if continuation_plan_public_id is None:
            if page_budget is not None or backfill_schedule_public_id is not None:
                raise ValueError(
                    "A page budget requires a verified Continuation Plan."
                )
        elif type(page_budget) is not int or not 1 <= page_budget <= 10:
            raise ValueError("Continuation page budget must be from 1 through 10.")
        if backfill_schedule_public_id is not None and (
            len(backfill_schedule_public_id) != 68
            or not backfill_schedule_public_id.startswith("bfs_")
            or any(
                char not in "0123456789abcdef"
                for char in backfill_schedule_public_id[4:]
            )
        ):
            raise ValueError("Backfill Schedule public ID is invalid.")

        fingerprint = _checkpoint_resume_fingerprint(
            checkpoint.public_id,
            continuation_plan_public_id=continuation_plan_public_id,
            page_budget=page_budget,
            backfill_schedule_public_id=backfill_schedule_public_id,
        )
        replay = self.repository.get_by_idempotency_key(
            case_id=wallet_case.id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            if replay.request_fingerprint != fingerprint:
                raise WalletCaseIdempotencyConflict(
                    "Idempotency-Key was already used for another sync scope."
                )
            return self._sync_response(
                replay,
                case_public_id=wallet_case.public_id,
            ), True
        active = self.repository.get_active_sync(case_id=wallet_case.id)
        if active is not None:
            raise WalletCaseSyncAlreadyActive(active.public_id)

        queued_at = _as_utc(now or _utc_now())
        ingestion_settings = self._settings_for_case(
            wallet_case,
            settings or get_settings(),
        )
        acquisition_plan = {
            "version": (
                5
                if backfill_schedule_public_id is not None
                else 4
                if continuation_plan_public_id is not None
                else 2
            ),
            "mode": "resume",
            "start_at": acquisition_start_text,
            "end_at": acquisition_end_text,
            "overlap_seconds": 0,
            "base_snapshot_public_id": source_sync.public_id,
            "source_checkpoint_public_id": checkpoint.public_id,
            "resume_stream_key": checkpoint.stream_key,
            "resume_cursor": cursor,
            "resume_page_index": page_index,
        }
        if continuation_plan_public_id is not None:
            acquisition_plan["continuation_plan_public_id"] = (
                continuation_plan_public_id
            )
            acquisition_plan["resume_page_budget"] = page_budget
        if backfill_schedule_public_id is not None:
            acquisition_plan["backfill_schedule_public_id"] = (
                backfill_schedule_public_id
            )
        expected_data_mode = _ENVIRONMENT_DATA_MODE[
            wallet_case.data_environment
        ]
        coverage = _coverage_record(
            {
                "requested_surfaces": resumed_surfaces,
                "data_mode": expected_data_mode,
            },
            start_at=requested_start,
            end_at=requested_end,
            state="queued",
            requested_surfaces=resumed_surfaces,
            acquisition_plan=acquisition_plan,
        )
        case_sync = CaseSync(
            case=wallet_case,
            time_window="custom",
            data_mode=expected_data_mode,
            provider=_queued_provider(ingestion_settings),
            requested_start=requested_start,
            requested_end=requested_end,
            requested_surfaces_json=_json_dumps(resumed_surfaces),
            state="queued",
            stage="queued",
            progress_current=0,
            progress_total=_SYNC_PROGRESS_TOTAL,
            coverage_summary_json=_json_dumps(coverage),
            result_summary_json="{}",
            message_safe="Wallet Case checkpoint continuation is queued.",
            created_at=queued_at,
            updated_at=queued_at,
            status_version=1,
            idempotency_key=idempotency_key,
            request_fingerprint=fingerprint,
            attempt_count=0,
            max_attempts=int(ingestion_settings.wallet_case_job_max_attempts),
            next_attempt_at=queued_at,
            checkpoint_json=_json_dumps(
                {"version": "case_sync_monolithic_v1", "phase": "queued"}
            ),
        )
        wallet_case.updated_at = queued_at
        self._record_catalog_event(wallet_case, recorded_at=queued_at)
        self.repository.add_sync(case_sync)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            replay = self.repository.get_by_idempotency_key(
                case_id=wallet_case.id,
                idempotency_key=idempotency_key,
            )
            if replay is not None:
                if replay.request_fingerprint != fingerprint:
                    raise WalletCaseIdempotencyConflict(
                        "Idempotency-Key was already used for another sync scope."
                    )
                return self._sync_response(
                    replay,
                    case_public_id=wallet_case.public_id,
                ), True
            active = self.repository.get_active_sync(case_id=wallet_case.id)
            if active is not None:
                raise WalletCaseSyncAlreadyActive(active.public_id)
            raise
        self.session.refresh(case_sync)
        response = self._sync_response(
            case_sync,
            case_public_id=wallet_case.public_id,
        )
        self.session.rollback()
        return response, False

    def enqueue_checkpoint_plan_resume(
        self,
        case_public_id: str,
        continuation_plan_public_id: str,
        checkpoint_public_id: str,
        idempotency_key: str,
        *,
        page_budget: int = 1,
        backfill_schedule_public_id: str | None = None,
        settings=None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Queue a continuation only when its verified plan is still current."""
        if type(page_budget) is not int or not 1 <= page_budget <= 10:
            raise ValueError("Continuation page budget must be from 1 through 10.")
        wallet_case = self._required_case(case_public_id)
        fingerprint = _checkpoint_resume_fingerprint(
            checkpoint_public_id,
            continuation_plan_public_id=continuation_plan_public_id,
            page_budget=page_budget,
            backfill_schedule_public_id=backfill_schedule_public_id,
        )
        replay = self.repository.get_by_idempotency_key(
            case_id=wallet_case.id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            if replay.request_fingerprint != fingerprint:
                raise WalletCaseIdempotencyConflict(
                    "Idempotency-Key was already used for another sync scope."
                )
            return self._sync_response(
                replay,
                case_public_id=wallet_case.public_id,
            ), True

        current_plan = self._checkpoint_continuation_plan_response(wallet_case)
        current_plan_public_id = current_plan["plan"]["public_id"]
        if current_plan_public_id != continuation_plan_public_id:
            raise WalletCaseContinuationPlanStale(current_plan_public_id)
        planned_stream = next(
            (
                stream
                for stream in current_plan["document"]["streams"]
                if stream["tip_checkpoint"]["public_id"]
                == checkpoint_public_id
            ),
            None,
        )
        if planned_stream is None:
            raise WalletCaseCheckpointResumeUnavailable(
                "This checkpoint is not a current Continuation Plan stream tip."
            )
        if planned_stream["resume_state"] != "ready":
            raise WalletCaseCheckpointResumeUnavailable(
                "This Continuation Plan stream is not ready to resume."
            )
        return self.enqueue_checkpoint_resume(
            wallet_case.public_id,
            checkpoint_public_id,
            idempotency_key,
            continuation_plan_public_id=continuation_plan_public_id,
            page_budget=page_budget,
            backfill_schedule_public_id=backfill_schedule_public_id,
            settings=settings,
            now=now,
        )

    def get_sync_manifest(
        self,
        case_public_id: str,
        sync_public_id: str,
    ) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        case_sync = self.repository.get_sync(
            case_id=wallet_case.id,
            public_id=sync_public_id,
        )
        if case_sync is None:
            raise WalletCaseNotFound("Wallet Case sync not found")
        manifest = case_sync.acquisition_manifest
        if manifest is None:
            raise WalletCaseSyncManifestNotFound(
                "Wallet Case sync acquisition manifest not found"
            )
        descriptor, document = _manifest_response(
            manifest,
            case_sync=case_sync,
            case_public_id=wallet_case.public_id,
        )
        return {"manifest": descriptor, "document": document}

    def get_checkpoint_continuation_receipt(
        self,
        case_public_id: str,
        sync_public_id: str,
    ) -> dict[str, Any]:
        """Reconstruct one immutable plan-bound resume transition."""
        wallet_case = self._required_case(case_public_id)
        case_sync = self.repository.get_sync(
            case_id=wallet_case.id,
            public_id=sync_public_id,
        )
        if case_sync is None:
            raise WalletCaseNotFound("Wallet Case sync not found")
        try:
            acquisition_plan = _sync_acquisition_plan(case_sync)
        except ValueError as exc:
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case continuation receipt lineage is invalid."
            ) from exc
        if (
            acquisition_plan.get("mode") != "resume"
            or acquisition_plan.get("version") not in {3, 4}
        ):
            raise WalletCaseContinuationReceiptNotFound(
                "This sync was not accepted from a verified Continuation Plan."
            )
        if case_sync.state not in {"partial", "succeeded"}:
            raise WalletCaseContinuationReceiptNotFound(
                "This plan-bound continuation has not published a result."
            )

        source_public_id = acquisition_plan["source_checkpoint_public_id"]
        source = self.repository.get_stream_checkpoint(
            case_id=wallet_case.id,
            public_id=source_public_id,
        )
        outputs = self.repository.stream_checkpoints_for_sync(
            case_id=wallet_case.id,
            source_sync_id=case_sync.id,
        )
        if source is None or len(outputs) != 1:
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case continuation receipt checkpoints are invalid."
            )
        output = outputs[0]
        if (
            output.provider != source.provider
            or output.stream_key != source.stream_key
            or output.provider_contract_version
            != source.provider_contract_version
        ):
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case continuation receipt stream changed identity."
            )

        source_chain = self._verified_stream_checkpoint_chain(
            source,
            case_id=wallet_case.id,
            case_public_id=wallet_case.public_id,
        )
        output_chain = self._verified_stream_checkpoint_chain(
            output,
            case_id=wallet_case.id,
            case_public_id=wallet_case.public_id,
        )
        source_ids = [item["row"].public_id for item in source_chain]
        output_ids = [item["row"].public_id for item in output_chain]
        if output_ids[:-1] != source_ids or output_ids[-1] == source_ids[-1]:
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case continuation receipt is not a direct revision."
            )

        source_chain_response = self._stream_checkpoint_chain_response(
            wallet_case,
            source_chain,
        )
        output_chain_response = self._stream_checkpoint_chain_response(
            wallet_case,
            output_chain,
        )
        source_response = source_chain[-1]["response"]
        output_response = output_chain[-1]["response"]
        source_document = source_response["document"]
        output_document = output_response["document"]
        source_aggregate = source_chain_response["document"]["aggregate"]
        output_aggregate = output_chain_response["document"]["aggregate"]

        bounded_tips = self.repository.latest_stream_checkpoints_at_cutoff(
            case_id=wallet_case.id,
            cutoff_id=output.id,
        )
        after_plan = self._checkpoint_continuation_plan_response(
            wallet_case,
            checkpoints=bounded_tips,
        )
        if (
            after_plan["plan"]["checkpoint_cutoff_public_id"]
            != output.public_id
        ):
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case continuation receipt cutoff is invalid."
            )

        transition = {
            "checkpoint_changed": True,
            "plan_changed": True,
            "revision_delta": (
                output_aggregate["revision_count"]
                - source_aggregate["revision_count"]
            ),
            "page_count_delta": (
                output_aggregate["page_count"]
                - source_aggregate["page_count"]
            ),
            "pages_succeeded_delta": (
                output_aggregate["pages_succeeded"]
                - source_aggregate["pages_succeeded"]
            ),
        }
        if (
            transition["revision_delta"] != 1
            or transition["page_count_delta"] < 0
            or transition["pages_succeeded_delta"] < 0
            or after_plan["plan"]["public_id"]
            == acquisition_plan["continuation_plan_public_id"]
        ):
            raise WalletCaseStreamCheckpointCorrupt(
                "Stored Wallet Case continuation receipt transition is invalid."
            )
        page_budget = acquisition_plan.get("resume_page_budget")
        budgeted = acquisition_plan["version"] == 4
        if budgeted:
            if (
                type(page_budget) is not int
                or not 1 <= page_budget <= 10
                or transition["page_count_delta"] > page_budget
                or transition["pages_succeeded_delta"]
                > transition["page_count_delta"]
            ):
                raise WalletCaseStreamCheckpointCorrupt(
                    "Stored Wallet Case continuation receipt budget is invalid."
                )
            transition.update(
                {
                    "page_budget_consumed": transition["page_count_delta"],
                    "page_budget_remaining": (
                        page_budget - transition["page_count_delta"]
                    ),
                }
            )
        document = {
            "contract_version": (
                "wallet_case_checkpoint_continuation_receipt_v2"
                if budgeted
                else "wallet_case_checkpoint_continuation_receipt_v1"
            ),
            "case_public_id": wallet_case.public_id,
            "sync_public_id": case_sync.public_id,
            "input": {
                "continuation_plan_public_id": acquisition_plan[
                    "continuation_plan_public_id"
                ],
                "checkpoint": source_response["checkpoint"],
                "chain_public_id": source_chain_response["chain"]["public_id"],
                "chain_content_hash_sha256": source_chain_response["chain"][
                    "content_hash_sha256"
                ],
                **source_aggregate,
                "next_page_index": source_document[
                    "continuation_page_index"
                ],
                **({"page_budget": page_budget} if budgeted else {}),
            },
            "output": {
                "checkpoint": output_response["checkpoint"],
                "chain_public_id": output_chain_response["chain"]["public_id"],
                "chain_content_hash_sha256": output_chain_response["chain"][
                    "content_hash_sha256"
                ],
                **output_aggregate,
                "resume_state": output_document["resume_state"],
                "next_page_index": output_document[
                    "continuation_page_index"
                ],
                "resume_blocker": output_document["resume_blocker"],
            },
            "after_plan": after_plan,
            "transition": transition,
            "limitations": [
                _limitation(
                    "continuation_receipt_is_provider_progress",
                    (
                        "This receipt proves one accepted checkpoint transition; "
                        "it does not prove complete wallet history or semantic "
                        "deduplication of wallet activity."
                    ),
                ),
                _limitation(
                    "continuation_receipt_does_not_schedule_next_page",
                    (
                        "The after-plan is reconstructed at publication time and "
                        "does not automatically enqueue another provider request."
                    ),
                ),
            ],
        }
        canonical = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        receipt = {
            "public_id": f"ctr_{digest}",
            "contract_version": document["contract_version"],
            "content_hash_sha256": digest,
            "sync_public_id": case_sync.public_id,
            "input_plan_public_id": acquisition_plan[
                "continuation_plan_public_id"
            ],
            "input_checkpoint_public_id": source.public_id,
            "output_checkpoint_public_id": output.public_id,
            "after_plan_public_id": after_plan["plan"]["public_id"],
            "revision_delta": transition["revision_delta"],
            "page_count_delta": transition["page_count_delta"],
            "pages_succeeded_delta": transition[
                "pages_succeeded_delta"
            ],
        }
        if budgeted:
            receipt.update(
                {
                    "page_budget": page_budget,
                    "page_budget_consumed": transition[
                        "page_budget_consumed"
                    ],
                    "page_budget_remaining": transition[
                        "page_budget_remaining"
                    ],
                }
            )
        return {
            "receipt": receipt,
            "document": document,
        }

    def list_stream_checkpoints(self, case_public_id: str) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        checkpoints = [
            _stream_checkpoint_response(
                checkpoint,
                case_public_id=wallet_case.public_id,
            )
            for checkpoint in self.repository.latest_stream_checkpoints(
                case_id=wallet_case.id
            )
        ]
        counts = {"ready": 0, "complete": 0, "blocked": 0}
        for item in checkpoints:
            counts[item["checkpoint"]["resume_state"]] += 1
        return {
            "case_public_id": wallet_case.public_id,
            "checkpoint_count": len(checkpoints),
            "ready_count": counts["ready"],
            "complete_count": counts["complete"],
            "blocked_count": counts["blocked"],
            "checkpoints": checkpoints,
        }

    def get_checkpoint_continuation_plan(
        self,
        case_public_id: str,
    ) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        return self._checkpoint_continuation_plan_response(wallet_case)

    def get_backfill_progress(self, case_public_id: str) -> dict[str, Any]:
        """Measure verified provider history movement across latest stream chains."""
        wallet_case = self._required_case(case_public_id)
        checkpoints = self.repository.latest_stream_checkpoints(
            case_id=wallet_case.id
        )
        if len(checkpoints) > _MAX_CHECKPOINT_CONTINUATION_PLAN_STREAMS:
            raise WalletCaseStreamCheckpointCorrupt(
                "Wallet Case backfill progress contains too many provider streams."
            )
        streams: list[dict[str, Any]] = []
        for checkpoint in checkpoints:
            chain = self._verified_stream_checkpoint_chain(
                checkpoint,
                case_id=wallet_case.id,
                case_public_id=wallet_case.public_id,
            )
            chain_response = self._stream_checkpoint_chain_response(
                wallet_case,
                chain,
            )
            root_response = chain[0]["response"]
            root_document = root_response["document"]
            tip_response = chain[-1]["response"]
            tip_descriptor = tip_response["checkpoint"]
            tip_document = tip_response["document"]
            if any(
                item["response"]["document"]["requested_period"]
                != root_document["requested_period"]
                for item in chain[1:]
            ):
                raise WalletCaseStreamCheckpointCorrupt(
                    "Stored Wallet Case backfill period changed within one stream chain."
                )
            root_frontier = _backfill_frontier(chain[0])
            current_frontier = next(
                (
                    frontier
                    for item in reversed(chain)
                    if (frontier := _backfill_frontier(item)) is not None
                ),
                None,
            )
            chain_descriptor = chain_response["chain"]
            initial_page_count = root_document["page_count"]
            initial_pages_succeeded = root_document["pages_succeeded"]
            continuation_page_count = (
                chain_descriptor["page_count"] - initial_page_count
            )
            continuation_pages_succeeded = (
                chain_descriptor["pages_succeeded"]
                - initial_pages_succeeded
            )
            streams.append(
                {
                    "provider": tip_descriptor["provider"],
                    "stream_key": tip_descriptor["stream_key"],
                    "provider_contract_version": tip_descriptor[
                        "provider_contract_version"
                    ],
                    "root_checkpoint_public_id": root_response["checkpoint"][
                        "public_id"
                    ],
                    "tip_checkpoint": tip_descriptor,
                    "chain_public_id": chain_descriptor["public_id"],
                    "chain_content_hash_sha256": chain_descriptor[
                        "content_hash_sha256"
                    ],
                    "root_acquisition_mode": chain[0]["plan"]["mode"],
                    "requested_period": root_document["requested_period"],
                    "revision_count": chain_descriptor["revision_count"],
                    "initial_page_count": initial_page_count,
                    "initial_pages_succeeded": initial_pages_succeeded,
                    "continuation_revision_count": len(chain) - 1,
                    "continuation_page_count": continuation_page_count,
                    "continuation_pages_succeeded": (
                        continuation_pages_succeeded
                    ),
                    "page_count": chain_descriptor["page_count"],
                    "pages_succeeded": chain_descriptor["pages_succeeded"],
                    "resume_state": tip_document["resume_state"],
                    "requested_interval_complete": (
                        tip_document["resume_state"] == "complete"
                    ),
                    "next_page_index": tip_document[
                        "continuation_page_index"
                    ],
                    "termination_reason": tip_document[
                        "termination_reason"
                    ],
                    "resume_blocker": tip_document["resume_blocker"],
                    "root_frontier": root_frontier,
                    "current_frontier": current_frontier,
                    "frontier_advanced": (
                        root_frontier is not None
                        and current_frontier is not None
                        and root_frontier["page"] != current_frontier["page"]
                    ),
                }
            )
        states = [item["resume_state"] for item in streams]
        aggregate = {
            "stream_count": len(streams),
            "ready_count": states.count("ready"),
            "complete_count": states.count("complete"),
            "blocked_count": states.count("blocked"),
            "revision_count": sum(item["revision_count"] for item in streams),
            "continuation_revision_count": sum(
                item["continuation_revision_count"] for item in streams
            ),
            "page_count": sum(item["page_count"] for item in streams),
            "pages_succeeded": sum(
                item["pages_succeeded"] for item in streams
            ),
            "continuation_page_count": sum(
                item["continuation_page_count"] for item in streams
            ),
            "continuation_pages_succeeded": sum(
                item["continuation_pages_succeeded"] for item in streams
            ),
            "observed_frontier_count": sum(
                item["current_frontier"] is not None for item in streams
            ),
            "advanced_frontier_count": sum(
                item["frontier_advanced"] for item in streams
            ),
        }
        cutoff = max(checkpoints, key=lambda item: item.id) if checkpoints else None
        document = {
            "contract_version": "wallet_case_backfill_progress_v1",
            "case_public_id": wallet_case.public_id,
            "checkpoint_cutoff_public_id": (
                cutoff.public_id if cutoff is not None else None
            ),
            "aggregate": aggregate,
            "streams": streams,
            "limitations": [
                _limitation(
                    "backfill_frontier_is_page_evidence",
                    (
                        "Each frontier is metadata from the latest successful "
                        "provider page in a verified chain; it is not proof of "
                        "the wallet's earliest activity."
                    ),
                ),
                _limitation(
                    "backfill_remaining_work_is_unknown",
                    (
                        "Provider cursors do not expose a reliable remaining-page "
                        "count, so progress reports acquired pages and state instead "
                        "of a completion percentage."
                    ),
                ),
            ],
        }
        canonical = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        return {
            "progress": {
                "public_id": f"bfp_{digest}",
                "contract_version": document["contract_version"],
                "content_hash_sha256": digest,
                "checkpoint_cutoff_public_id": document[
                    "checkpoint_cutoff_public_id"
                ],
                **aggregate,
            },
            "document": document,
        }

    def get_backfill_schedule(
        self,
        case_public_id: str,
        *,
        page_budget: int = 1,
    ) -> dict[str, Any]:
        """Select one fair, finite continuation from current verified state."""
        if type(page_budget) is not int or not 1 <= page_budget <= 10:
            raise ValueError("Backfill page budget must be from 1 through 10.")
        wallet_case = self._required_case(case_public_id)
        progress = self.get_backfill_progress(wallet_case.public_id)
        plan = self._checkpoint_continuation_plan_response(wallet_case)
        progress_document = progress["document"]
        plan_document = plan["document"]
        if (
            progress_document["checkpoint_cutoff_public_id"]
            != plan_document["checkpoint_cutoff_public_id"]
        ):
            raise WalletCaseStreamCheckpointCorrupt(
                "Wallet Case backfill schedule inputs have different checkpoint cutoffs."
            )

        plan_by_identity = {
            (stream["provider"], stream["stream_key"]): stream
            for stream in plan_document["streams"]
        }
        ready_streams = [
            stream
            for stream in progress_document["streams"]
            if stream["resume_state"] == "ready"
        ]
        ready_streams.sort(
            key=lambda stream: (
                stream["continuation_page_count"],
                stream["continuation_revision_count"],
                stream["provider"],
                stream["stream_key"],
            )
        )
        selected_progress = ready_streams[0] if ready_streams else None
        selected_plan = (
            plan_by_identity.get(
                (
                    selected_progress["provider"],
                    selected_progress["stream_key"],
                )
            )
            if selected_progress is not None
            else None
        )
        if selected_progress is not None and (
            selected_plan is None
            or selected_plan["resume_state"] != "ready"
            or selected_plan["tip_checkpoint"]["public_id"]
            != selected_progress["tip_checkpoint"]["public_id"]
            or selected_plan["next_page_index"]
            != selected_progress["next_page_index"]
        ):
            raise WalletCaseStreamCheckpointCorrupt(
                "Wallet Case backfill schedule inputs disagree on the selected stream."
            )

        active = self.repository.get_active_sync(case_id=wallet_case.id)
        aggregate = progress_document["aggregate"]
        if active is not None:
            state = "backpressured"
            selection = None
        elif selected_progress is not None:
            state = "ready"
            selection = {
                "provider": selected_progress["provider"],
                "stream_key": selected_progress["stream_key"],
                "checkpoint_public_id": selected_progress["tip_checkpoint"][
                    "public_id"
                ],
                "continuation_revision_count": selected_progress[
                    "continuation_revision_count"
                ],
                "continuation_page_count": selected_progress[
                    "continuation_page_count"
                ],
                "next_page_index": selected_progress["next_page_index"],
            }
        elif aggregate["stream_count"] == 0:
            state = "empty"
            selection = None
        elif aggregate["blocked_count"] > 0:
            state = "blocked"
            selection = None
        else:
            state = "complete"
            selection = None

        document = {
            "contract_version": "wallet_case_backfill_schedule_v1",
            "case_public_id": wallet_case.public_id,
            "input_progress_public_id": progress["progress"]["public_id"],
            "input_plan_public_id": plan["plan"]["public_id"],
            "checkpoint_cutoff_public_id": progress_document[
                "checkpoint_cutoff_public_id"
            ],
            "page_budget": page_budget,
            "selection_policy": (
                "least_continuation_pages_then_revisions_then_provider_stream_v1"
            ),
            "state": state,
            "stream_count": aggregate["stream_count"],
            "ready_count": aggregate["ready_count"],
            "complete_count": aggregate["complete_count"],
            "blocked_count": aggregate["blocked_count"],
            "active_sync_public_id": (
                active.public_id if active is not None else None
            ),
            "selection": selection,
            "limitations": [
                _limitation(
                    "backfill_schedule_is_one_finite_step",
                    (
                        "This schedule selects at most one provider stream and "
                        "authorizes only the displayed page budget; it does not "
                        "repeat or crawl in the background."
                    ),
                ),
                _limitation(
                    "backfill_schedule_requires_fresh_state",
                    (
                        "Any active synchronization applies backpressure, and a "
                        "new schedule must be verified after every published result."
                    ),
                ),
            ],
        }
        canonical = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        return {
            "schedule": {
                "public_id": f"bfs_{digest}",
                "contract_version": document["contract_version"],
                "content_hash_sha256": digest,
                "state": state,
                "input_progress_public_id": document[
                    "input_progress_public_id"
                ],
                "input_plan_public_id": document["input_plan_public_id"],
                "checkpoint_cutoff_public_id": document[
                    "checkpoint_cutoff_public_id"
                ],
                "page_budget": page_budget,
                "selected_checkpoint_public_id": (
                    selection["checkpoint_public_id"]
                    if selection is not None
                    else None
                ),
                "active_sync_public_id": document["active_sync_public_id"],
            },
            "document": document,
        }

    def enqueue_backfill_schedule(
        self,
        case_public_id: str,
        schedule_public_id: str,
        idempotency_key: str,
        *,
        page_budget: int = 1,
        settings=None,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Queue the one selection bound to an exact current schedule."""
        if type(page_budget) is not int or not 1 <= page_budget <= 10:
            raise ValueError("Backfill page budget must be from 1 through 10.")
        wallet_case = self._required_case(case_public_id)
        replay = self.repository.get_by_idempotency_key(
            case_id=wallet_case.id,
            idempotency_key=idempotency_key,
        )
        if replay is not None:
            try:
                replay_plan = _sync_acquisition_plan(replay)
            except ValueError as exc:
                raise WalletCaseIdempotencyConflict(
                    "Idempotency-Key was already used for another sync scope."
                ) from exc
            if (
                replay_plan.get("version") != 5
                or replay_plan.get("backfill_schedule_public_id")
                != schedule_public_id
                or replay_plan.get("resume_page_budget") != page_budget
            ):
                raise WalletCaseIdempotencyConflict(
                    "Idempotency-Key was already used for another sync scope."
                )
            return self._sync_response(
                replay,
                case_public_id=wallet_case.public_id,
            ), True

        current = self.get_backfill_schedule(
            wallet_case.public_id,
            page_budget=page_budget,
        )
        descriptor = current["schedule"]
        if descriptor["public_id"] != schedule_public_id:
            raise WalletCaseBackfillScheduleStale(
                descriptor["public_id"],
                descriptor["state"],
            )
        selection = current["document"]["selection"]
        if descriptor["state"] != "ready" or selection is None:
            raise WalletCaseBackfillScheduleUnavailable(
                descriptor["state"],
                descriptor["active_sync_public_id"],
            )
        return self.enqueue_checkpoint_plan_resume(
            wallet_case.public_id,
            descriptor["input_plan_public_id"],
            selection["checkpoint_public_id"],
            idempotency_key,
            page_budget=page_budget,
            backfill_schedule_public_id=schedule_public_id,
            settings=settings,
            now=now,
        )

    def _checkpoint_continuation_plan_response(
        self,
        wallet_case: WalletCase,
        *,
        checkpoints: list[WalletCaseStreamCheckpoint] | None = None,
    ) -> dict[str, Any]:
        """Build a content-addressed plan from current or bounded stream tips."""
        if checkpoints is None:
            checkpoints = self.repository.latest_stream_checkpoints(
                case_id=wallet_case.id
            )
        if len(checkpoints) > _MAX_CHECKPOINT_CONTINUATION_PLAN_STREAMS:
            raise WalletCaseStreamCheckpointCorrupt(
                "Wallet Case continuation plan contains too many provider streams."
            )
        streams = []
        for checkpoint in checkpoints:
            chain = self._verified_stream_checkpoint_chain(
                checkpoint,
                case_id=wallet_case.id,
                case_public_id=wallet_case.public_id,
            )
            chain_response = self._stream_checkpoint_chain_response(
                wallet_case,
                chain,
            )
            tip_response = chain[-1]["response"]
            tip_descriptor = tip_response["checkpoint"]
            tip_document = tip_response["document"]
            chain_descriptor = chain_response["chain"]
            streams.append(
                {
                    "provider": tip_descriptor["provider"],
                    "stream_key": tip_descriptor["stream_key"],
                    "provider_contract_version": tip_descriptor[
                        "provider_contract_version"
                    ],
                    "tip_checkpoint": tip_descriptor,
                    "chain_public_id": chain_descriptor["public_id"],
                    "chain_content_hash_sha256": chain_descriptor[
                        "content_hash_sha256"
                    ],
                    "revision_count": chain_descriptor["revision_count"],
                    "page_count": chain_descriptor["page_count"],
                    "pages_succeeded": chain_descriptor[
                        "pages_succeeded"
                    ],
                    "resume_state": tip_document["resume_state"],
                    "next_page_index": tip_document[
                        "continuation_page_index"
                    ],
                    "resume_blocker": tip_document["resume_blocker"],
                }
            )
        states = [item["resume_state"] for item in streams]
        aggregate = {
            "stream_count": len(streams),
            "ready_count": states.count("ready"),
            "complete_count": states.count("complete"),
            "blocked_count": states.count("blocked"),
            "revision_count": sum(
                item["revision_count"] for item in streams
            ),
            "page_count": sum(item["page_count"] for item in streams),
            "pages_succeeded": sum(
                item["pages_succeeded"] for item in streams
            ),
        }
        cutoff = max(checkpoints, key=lambda item: item.id) if checkpoints else None
        document = {
            "contract_version": "wallet_case_checkpoint_continuation_plan_v1",
            "case_public_id": wallet_case.public_id,
            "checkpoint_cutoff_public_id": (
                cutoff.public_id if cutoff is not None else None
            ),
            "aggregate": aggregate,
            "streams": streams,
            "limitations": [
                _limitation(
                    "continuation_plan_requires_sequential_resume",
                    (
                        "Only one Wallet Case synchronization can run at a time; "
                        "resume one ready stream and verify a new plan after it publishes."
                    ),
                ),
                _limitation(
                    "continuation_plan_is_not_automatic_backfill",
                    (
                        "Continuation Plan describes current verified checkpoints; "
                        "it does not schedule provider requests or prove complete "
                        "wallet history."
                    ),
                ),
            ],
        }
        canonical = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        return {
            "plan": {
                "public_id": f"cpl_{digest}",
                "contract_version": document["contract_version"],
                "content_hash_sha256": digest,
                "checkpoint_cutoff_public_id": document[
                    "checkpoint_cutoff_public_id"
                ],
                **aggregate,
            },
            "document": document,
        }

    def get_stream_checkpoint_detail(
        self,
        case_public_id: str,
        checkpoint_public_id: str,
    ) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        checkpoint = self.repository.get_stream_checkpoint(
            case_id=wallet_case.id,
            public_id=checkpoint_public_id,
        )
        if checkpoint is None:
            raise WalletCaseNotFound("Wallet Case stream checkpoint not found")
        chain = self._verified_stream_checkpoint_chain(
            checkpoint,
            case_id=wallet_case.id,
            case_public_id=wallet_case.public_id,
        )
        tip = chain[-1]
        return {
            **tip["response"],
            "lineage": self._stream_checkpoint_lineage(chain),
        }

    def get_stream_checkpoint_chain(
        self,
        case_public_id: str,
        checkpoint_public_id: str,
    ) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        checkpoint = self.repository.get_stream_checkpoint(
            case_id=wallet_case.id,
            public_id=checkpoint_public_id,
        )
        if checkpoint is None:
            raise WalletCaseNotFound("Wallet Case stream checkpoint not found")
        chain = self._verified_stream_checkpoint_chain(
            checkpoint,
            case_id=wallet_case.id,
            case_public_id=wallet_case.public_id,
        )
        return self._stream_checkpoint_chain_response(wallet_case, chain)

    @staticmethod
    def _stream_checkpoint_chain_response(
        wallet_case: WalletCase,
        chain: list[dict[str, Any]],
    ) -> dict[str, Any]:
        revisions = []
        for ordinal, item in enumerate(chain):
            response = item["response"]
            descriptor = response["checkpoint"]
            checkpoint_document = response["document"]
            plan = item["plan"]
            last_page = checkpoint_document["last_successful_page"]
            revisions.append(
                {
                    "ordinal": ordinal,
                    "checkpoint": descriptor,
                    "acquisition_mode": plan["mode"],
                    "base_snapshot_public_id": plan[
                        "base_snapshot_public_id"
                    ],
                    "parent_checkpoint_public_id": plan.get(
                        "source_checkpoint_public_id"
                    ),
                    "source_manifest_public_id": checkpoint_document[
                        "source_manifest_public_id"
                    ],
                    "source_manifest_hash_sha256": checkpoint_document[
                        "source_manifest_hash_sha256"
                    ],
                    "requested_period": checkpoint_document[
                        "requested_period"
                    ],
                    "continuation_page_index": checkpoint_document[
                        "continuation_page_index"
                    ],
                    "page_count": checkpoint_document["page_count"],
                    "pages_succeeded": checkpoint_document[
                        "pages_succeeded"
                    ],
                    "last_response_digest_sha256": (
                        last_page["response_digest_sha256"]
                        if last_page is not None
                        else None
                    ),
                }
            )
        root = chain[0]
        tip = chain[-1]
        root_plan = root["plan"]
        tip_document = tip["response"]["document"]
        aggregate = {
            "revision_count": len(revisions),
            "page_count": sum(item["page_count"] for item in revisions),
            "pages_succeeded": sum(
                item["pages_succeeded"] for item in revisions
            ),
        }
        limitations = [
            _limitation(
                "checkpoint_chain_is_acquisition_progress",
                (
                    "Checkpoint Chain totals verified provider page acquisitions; "
                    "it does not deduplicate wallet activity or prove complete "
                    "wallet history."
                ),
            )
        ]
        if root_plan["mode"] == "incremental":
            limitations.append(
                _limitation(
                    "checkpoint_chain_starts_after_external_snapshot",
                    (
                        "This checkpoint chain starts from an incremental sync; "
                        "its base snapshot is outside the provider checkpoint chain."
                    ),
                )
            )
        document = {
            "contract_version": "wallet_case_stream_checkpoint_chain_v1",
            "case_public_id": wallet_case.public_id,
            "tip_checkpoint_public_id": tip["row"].public_id,
            "provider": tip["row"].provider,
            "stream_key": tip["row"].stream_key,
            "provider_contract_version": tip[
                "row"
            ].provider_contract_version,
            "root_acquisition_mode": root_plan["mode"],
            "root_base_snapshot_public_id": root_plan[
                "base_snapshot_public_id"
            ],
            "current_resume_state": tip_document["resume_state"],
            "next_page_index": tip_document["continuation_page_index"],
            "aggregate": aggregate,
            "revisions": revisions,
            "limitations": limitations,
        }
        canonical = json.dumps(
            document,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        digest = hashlib.sha256(canonical).hexdigest()
        return {
            "chain": {
                "public_id": f"cch_{digest}",
                "contract_version": document["contract_version"],
                "content_hash_sha256": digest,
                **aggregate,
            },
            "document": document,
        }

    def list_stream_checkpoint_history(
        self,
        case_public_id: str,
        *,
        limit: int = 20,
        cursor: str | None = None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > 50:
            raise WalletCaseCheckpointHistoryInvalidCursor(
                "Checkpoint history limit must be between 1 and 50."
            )
        wallet_case = self._required_case(case_public_id)
        cursor_document = (
            _decode_checkpoint_history_cursor(cursor)
            if cursor is not None
            else None
        )
        if (
            cursor_document is not None
            and cursor_document["case"] != wallet_case.public_id
        ):
            raise WalletCaseCheckpointHistoryInvalidCursor(
                "Checkpoint history cursor belongs to another Wallet Case."
            )
        cutoff = (
            self.repository.latest_stream_checkpoint(case_id=wallet_case.id)
            if cursor_document is None
            else self.repository.get_stream_checkpoint(
                case_id=wallet_case.id,
                public_id=cursor_document["cutoff"],
            )
        )
        limitations = [
            _limitation(
                "checkpoint_history_is_explicit_revisions",
                (
                    "Checkpoint history contains published provider continuation "
                    "revisions and does not prove complete wallet history."
                ),
            )
        ]
        if cutoff is None:
            if cursor_document is not None:
                raise WalletCaseCheckpointHistoryInvalidCursor(
                    "Checkpoint history cursor cutoff is unavailable."
                )
            return {
                "contract_version": "wallet_case_stream_checkpoint_history_v1",
                "case_public_id": wallet_case.public_id,
                "revision_cutoff_public_id": None,
                "items": [],
                "aggregate": {"total_revisions": 0, "returned_count": 0},
                "page": {
                    "limit": limit,
                    "has_more": False,
                    "next_cursor": None,
                },
                "limitations": limitations,
            }
        after_id = None
        if cursor_document is not None:
            after = self.repository.get_stream_checkpoint(
                case_id=wallet_case.id,
                public_id=cursor_document["after"],
            )
            if after is None or after.id > cutoff.id:
                raise WalletCaseCheckpointHistoryInvalidCursor(
                    "Checkpoint history cursor position is unavailable."
                )
            after_id = after.id
        rows = self.repository.stream_checkpoint_history(
            case_id=wallet_case.id,
            cutoff_id=cutoff.id,
            after_id=after_id,
            limit=limit + 1,
        )
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = []
        for checkpoint in visible:
            chain = self._verified_stream_checkpoint_chain(
                checkpoint,
                case_id=wallet_case.id,
                case_public_id=wallet_case.public_id,
            )
            response = chain[-1]["response"]
            document = response["document"]
            items.append(
                {
                    "checkpoint": response["checkpoint"],
                    "lineage": self._stream_checkpoint_lineage(chain),
                    "continuation_page_index": document[
                        "continuation_page_index"
                    ],
                    "page_count": document["page_count"],
                    "pages_succeeded": document["pages_succeeded"],
                }
            )
        next_cursor = None
        if has_more:
            next_cursor = _encode_checkpoint_history_cursor(
                {
                    "v": _CHECKPOINT_HISTORY_CURSOR_VERSION,
                    "case": wallet_case.public_id,
                    "cutoff": cutoff.public_id,
                    "after": visible[-1].public_id,
                }
            )
            limitations.append(
                _limitation(
                    "checkpoint_history_cursor_local_process_scope",
                    (
                        "Pagination cursors are authenticated for this local API "
                        "process and expire after restart."
                    ),
                )
            )
        total = self.repository.count_stream_checkpoint_history(
            case_id=wallet_case.id,
            cutoff_id=cutoff.id,
        )
        return {
            "contract_version": "wallet_case_stream_checkpoint_history_v1",
            "case_public_id": wallet_case.public_id,
            "revision_cutoff_public_id": cutoff.public_id,
            "items": items,
            "aggregate": {
                "total_revisions": total,
                "returned_count": len(items),
            },
            "page": {
                "limit": limit,
                "has_more": has_more,
                "next_cursor": next_cursor,
            },
            "limitations": limitations,
        }

    def _verified_stream_checkpoint_chain(
        self,
        checkpoint: WalletCaseStreamCheckpoint,
        *,
        case_id: int,
        case_public_id: str,
    ) -> list[dict[str, Any]]:
        current = checkpoint
        seen: set[str] = set()
        descending: list[dict[str, Any]] = []
        while True:
            if len(descending) >= _MAX_CHECKPOINT_CHAIN_REVISIONS:
                raise WalletCaseStreamCheckpointCorrupt(
                    "Stored Wallet Case stream checkpoint lineage is too deep."
                )
            if current.public_id in seen:
                raise WalletCaseStreamCheckpointCorrupt(
                    "Stored Wallet Case stream checkpoint lineage contains a cycle."
                )
            seen.add(current.public_id)
            response = _stream_checkpoint_response(
                current,
                case_public_id=case_public_id,
            )
            try:
                plan = _sync_acquisition_plan(current.source_sync)
            except ValueError as exc:
                raise WalletCaseStreamCheckpointCorrupt(
                    "Stored Wallet Case stream checkpoint lineage is invalid."
                ) from exc
            mode = plan["mode"]
            base_public_id = plan["base_snapshot_public_id"]
            parent_public_id = plan.get("source_checkpoint_public_id")
            descending.append(
                {"row": current, "response": response, "plan": plan}
            )
            if mode != "resume":
                if parent_public_id is not None:
                    raise WalletCaseStreamCheckpointCorrupt(
                        "Stored Wallet Case stream checkpoint lineage is invalid."
                    )
                if mode == "incremental":
                    base_sync = self.repository.get_sync(
                        case_id=case_id,
                        public_id=base_public_id,
                    )
                    if (
                        base_sync is None
                        or base_sync.id >= current.source_sync.id
                    ):
                        raise WalletCaseStreamCheckpointCorrupt(
                            "Stored Wallet Case stream checkpoint base snapshot is invalid."
                        )
                break
            parent = self.repository.get_stream_checkpoint(
                case_id=case_id,
                public_id=parent_public_id,
            )
            if (
                parent is None
                or parent.id >= current.id
                or base_public_id != parent.source_sync.public_id
                or parent.provider != current.provider
                or parent.stream_key != current.stream_key
                or parent.provider_contract_version
                != current.provider_contract_version
            ):
                raise WalletCaseStreamCheckpointCorrupt(
                    "Stored Wallet Case stream checkpoint parent is invalid."
                )
            current = parent
        descending.reverse()
        return descending

    @staticmethod
    def _stream_checkpoint_lineage(
        chain: list[dict[str, Any]],
    ) -> dict[str, Any]:
        tip = chain[-1]
        plan = tip["plan"]
        return {
            "acquisition_mode": plan["mode"],
            "base_snapshot_public_id": plan["base_snapshot_public_id"],
            "parent_checkpoint_public_id": plan.get(
                "source_checkpoint_public_id"
            ),
            "chain_depth": len(chain) - 1,
        }

    def get_job(self, sync_public_id: str) -> dict[str, Any]:
        case_sync = self.repository.get_sync_by_public_id_for_owner(
            owner_scope_id=self.owner_scope_id,
            public_id=sync_public_id,
        )
        if case_sync is None:
            raise WalletCaseNotFound("Wallet Case synchronization job not found")
        return self._sync_response(case_sync)

    def cancel_sync(
        self,
        case_public_id: str,
        sync_public_id: str,
        *,
        now: datetime | None = None,
    ) -> tuple[dict[str, Any], bool]:
        wallet_case = self._required_case(case_public_id)
        case_sync = self.repository.get_sync(
            case_id=wallet_case.id,
            public_id=sync_public_id,
        )
        if case_sync is None:
            raise WalletCaseNotFound("Wallet Case sync not found")
        if case_sync.state in {"partial", "succeeded", "failed", "cancelled"}:
            return self._sync_response(
                case_sync,
                case_public_id=wallet_case.public_id,
            ), False

        cancelled_at = _as_utc(now or _utc_now())
        queued_update = self.session.execute(
            update(CaseSync)
            .where(CaseSync.id == case_sync.id, CaseSync.state == "queued")
            .values(
                state="cancelled",
                stage="cancelled",
                cancel_requested_at=cancelled_at,
                completed_at=cancelled_at,
                updated_at=cancelled_at,
                next_attempt_at=None,
                message_safe="Wallet Case synchronization was cancelled before execution.",
                status_version=CaseSync.status_version + 1,
            )
        )
        if queued_update.rowcount == 1:
            self.session.commit()
            refreshed = self.repository.get_sync(
                case_id=wallet_case.id,
                public_id=sync_public_id,
            )
            assert refreshed is not None
            return self._sync_response(
                refreshed,
                case_public_id=wallet_case.public_id,
            ), False

        running_update = self.session.execute(
            update(CaseSync)
            .where(
                CaseSync.id == case_sync.id,
                CaseSync.state == "running",
                CaseSync.cancel_requested_at.is_(None),
            )
            .values(
                stage="cancelling",
                cancel_requested_at=cancelled_at,
                updated_at=cancelled_at,
                message_safe=(
                    "Cancellation requested. The current bounded provider crawl "
                    "will be discarded when it returns."
                ),
                status_version=CaseSync.status_version + 1,
            )
        )
        self.session.commit()
        refreshed = self.repository.get_sync(
            case_id=wallet_case.id,
            public_id=sync_public_id,
        )
        if refreshed is None:
            raise WalletCaseNotFound("Wallet Case sync not found")
        return self._sync_response(
            refreshed,
            case_public_id=wallet_case.public_id,
        ), running_update.rowcount == 1

    def _required_case(self, public_id: str) -> WalletCase:
        wallet_case = self.repository.get_by_public_id(
            owner_scope_id=self.owner_scope_id,
            public_id=public_id,
        )
        if wallet_case is None:
            raise WalletCaseNotFound("Wallet Case not found")
        return wallet_case

    def _raise_if_delete_conflicts(self, case_id: int) -> None:
        active_sync = self.repository.get_active_sync(case_id=case_id)
        active_evidence = self.repository.get_active_evidence_verification(
            case_id=case_id
        )
        if active_sync is not None or active_evidence is not None:
            raise WalletCaseDeletionConflict(
                active_sync_public_id=(
                    active_sync.public_id if active_sync is not None else None
                ),
                active_evidence_public_id=(
                    active_evidence.public_id
                    if active_evidence is not None
                    else None
                ),
            )

    def _raise_if_archive_conflicts(self, case_id: int) -> None:
        active_sync = self.repository.get_active_sync(case_id=case_id)
        active_evidence = self.repository.get_active_evidence_verification(
            case_id=case_id
        )
        if active_sync is not None or active_evidence is not None:
            raise WalletCaseArchiveConflict(
                active_sync_public_id=(
                    active_sync.public_id if active_sync is not None else None
                ),
                active_evidence_public_id=(
                    active_evidence.public_id
                    if active_evidence is not None
                    else None
                ),
            )

    def _record_catalog_event(
        self,
        wallet_case: WalletCase,
        *,
        recorded_at: datetime,
        visible: bool = True,
    ) -> None:
        self.session.add(
            WalletCaseCatalogEvent(
                case=wallet_case,
                recorded_at=_as_utc(recorded_at),
                visible=visible,
            )
        )

    def _acquire_delete_write_fence(self, wallet_case: WalletCase) -> None:
        """Serialize the cleanup inventory against new SQLite writers."""
        fenced = self.session.execute(
            update(WalletCase)
            .where(
                WalletCase.id == wallet_case.id,
                WalletCase.owner_scope_id == self.owner_scope_id,
                ~exists().where(
                    CaseSync.case_id == wallet_case.id,
                    CaseSync.state.in_(("queued", "running")),
                ),
                ~exists().where(
                    CaseEvidenceVerification.case_id == wallet_case.id,
                    CaseEvidenceVerification.state.in_(("queued", "running")),
                ),
            )
            .values(updated_at=WalletCase.updated_at)
            .execution_options(synchronize_session=False)
        )
        if fenced.rowcount != 1:
            self._raise_delete_changed(wallet_case.public_id)

    def _raise_delete_changed(self, public_id: str) -> None:
        self.session.rollback()
        current = self.repository.get_by_public_id(
            owner_scope_id=self.owner_scope_id,
            public_id=public_id,
        )
        if current is None:
            raise WalletCaseNotFound("Wallet Case not found")
        self._raise_if_delete_conflicts(current.id)
        raise WalletCaseRuntimeConflict(
            "Wallet Case changed while deletion was being prepared."
        )

    def _row_count(self, model, predicate) -> int:
        return int(
            self.session.scalar(
                select(func.count()).select_from(model).where(predicate)
            )
            or 0
        )

    def _latest_sync(self, wallet_case: WalletCase) -> CaseSync | None:
        return self.repository.latest_syncs([wallet_case.id]).get(wallet_case.id)

    def _settings_for_case(self, wallet_case: WalletCase, settings):
        return self._settings_for_scope(
            network=wallet_case.network,
            data_environment=wallet_case.data_environment,
            settings=settings,
        )

    def _settings_for_scope(
        self,
        *,
        network: str,
        data_environment: str,
        settings,
    ):
        runtime_network = network.removeprefix("ton-")
        if data_environment == "demo":
            return replace(
                settings,
                data_mode="mock",
                wallet_activity_provider="mock",
                wallet_activity_live_enabled=False,
                ton_network=runtime_network,
            )
        if not settings.is_real:
            raise WalletCaseRuntimeConflict(
                "Live Wallet Case requires DATA_MODE=real."
            )
        if settings.ton_network != runtime_network:
            raise WalletCaseRuntimeConflict(
                "Live Wallet Case network does not match TON_NETWORK."
            )
        if (
            settings.wallet_activity_provider != "tonapi"
            or not settings.wallet_activity_live_enabled
        ):
            raise WalletCaseRuntimeConflict(
                "Live Wallet Case requires the guarded TonAPI live adapter."
            )
        provider_status = get_wallet_activity_provider_status(settings)
        if not (
            provider_status.get("configured") is True
            and provider_status.get("available") is True
        ):
            raise WalletCaseRuntimeConflict(
                "Live Wallet Case requires an available TonAPI configuration."
            )
        return settings

    def _case_response(
        self,
        wallet_case: WalletCase,
        *,
        latest_sync: CaseSync | None = None,
        active_sync: CaseSync | None | object = _UNSET,
        current_snapshot: CaseSync | None | object = _UNSET,
    ) -> dict[str, Any]:
        if active_sync is _UNSET:
            active_sync = self.repository.get_active_sync(case_id=wallet_case.id)
        if current_snapshot is _UNSET:
            current_snapshot = self.repository.latest_usable_syncs(
                [wallet_case.id]
            ).get(wallet_case.id)
        snapshot_for_compatibility = (
            current_snapshot if isinstance(current_snapshot, CaseSync) else None
        )
        summary = _stored_summary(snapshot_for_compatibility)
        if snapshot_for_compatibility is None:
            limitations = [
                _limitation(
                    "not_synchronized",
                    "This Wallet Case has not been synchronized yet.",
                )
            ]
        else:
            limitations = _limitations_for_sync(
                snapshot_for_compatibility,
                _stored_coverage(snapshot_for_compatibility),
            )
        return {
            "public_id": wallet_case.public_id,
            "network": wallet_case.network,
            "data_environment": wallet_case.data_environment,
            "canonical_wallet_key": wallet_case.canonical_wallet_key,
            "identity_version": wallet_case.canonical_identity_version,
            "display_address": wallet_case.display_address,
            "label": wallet_case.label,
            "note": wallet_case.note,
            "metadata_version": wallet_case.metadata_version,
            "created_at": _isoformat(wallet_case.created_at),
            "updated_at": _isoformat(wallet_case.updated_at),
            "archived_at": (
                _isoformat(wallet_case.archived_at)
                if wallet_case.archived_at is not None
                else None
            ),
            "latest_sync": (
                self._sync_response(
                    latest_sync,
                    case_public_id=wallet_case.public_id,
                )
                if latest_sync is not None
                else None
            ),
            "latest_sync_attempt": (
                self._sync_response(
                    latest_sync,
                    case_public_id=wallet_case.public_id,
                )
                if latest_sync is not None
                else None
            ),
            "active_sync": (
                self._sync_response(
                    active_sync,
                    case_public_id=wallet_case.public_id,
                )
                if isinstance(active_sync, CaseSync)
                else None
            ),
            "current_snapshot": (
                self._sync_response(
                    current_snapshot,
                    case_public_id=wallet_case.public_id,
                )
                if isinstance(current_snapshot, CaseSync)
                else None
            ),
            "summary": summary,
            "limitations": limitations,
        }

    def _sync_response(
        self,
        case_sync: CaseSync,
        *,
        case_public_id: str | None = None,
    ) -> dict[str, Any]:
        if case_public_id is None:
            case_public_id = case_sync.case.public_id
        acquisition_plan = _sync_acquisition_plan(case_sync)
        coverage = _stored_coverage(case_sync)
        summary = _stored_summary(case_sync)
        limitations = _limitations_for_sync(case_sync, coverage)
        message = _bounded_message(case_sync.message_safe)
        if not message:
            message = _bounded_message(case_sync.error_detail_safe)
        if not message:
            message = "Wallet Case sync has no published result message."
        checkpoint = _json_object(case_sync.checkpoint_json)
        retry = None
        if (
            case_sync.state == "queued"
            and case_sync.stage == "retry_wait"
            and case_sync.next_attempt_at is not None
            and case_sync.attempt_count > 0
        ):
            retry = {
                "attempt": case_sync.attempt_count,
                "max_attempts": case_sync.max_attempts,
                "retry_at": _isoformat(case_sync.next_attempt_at),
                "reason_code": case_sync.error_code or "provider_retry",
                "message_safe": _bounded_message(case_sync.error_detail_safe)
                or "A bounded retry is scheduled.",
            }
        terminal_error = None
        if case_sync.state == "failed":
            terminal_error = {
                "code": case_sync.error_code or "sync_failed",
                "message_safe": _bounded_message(case_sync.error_detail_safe)
                or message,
                "retryable": bool(checkpoint.get("last_error_retryable", False)),
            }
        result = None
        if case_sync.state in {"partial", "succeeded"}:
            result = {
                "summary": summary,
                "coverage": coverage,
                "limitations": limitations,
                "message": message,
            }
        return {
            "case_public_id": case_public_id,
            "public_id": case_sync.public_id,
            "status_version": case_sync.status_version,
            "state": case_sync.state,
            "stage": case_sync.stage,
            "progress": {
                "current": case_sync.progress_current,
                "total": case_sync.progress_total,
            },
            "poll_after_ms": _poll_after_ms(case_sync),
            "cancel_requested": case_sync.cancel_requested_at is not None,
            "retry": retry,
            "error": terminal_error,
            "result": result,
            "acquisition_manifest": (
                _manifest_response(
                    case_sync.acquisition_manifest,
                    case_sync=case_sync,
                    case_public_id=case_public_id,
                )[0]
                if case_sync.acquisition_manifest is not None
                else None
            ),
            "provider": case_sync.provider,
            "data_mode": case_sync.data_mode,
            "requested_scope": {
                "mode": acquisition_plan["mode"],
                "time_window": case_sync.time_window,
                "start_at": _isoformat(case_sync.requested_start),
                "end_at": _isoformat(case_sync.requested_end),
                "surfaces": _json_list(case_sync.requested_surfaces_json),
                "acquisition_start_at": acquisition_plan["start_at"],
                "acquisition_end_at": acquisition_plan["end_at"],
                "overlap_seconds": acquisition_plan["overlap_seconds"],
                "base_snapshot_public_id": acquisition_plan[
                    "base_snapshot_public_id"
                ],
                "source_checkpoint_public_id": acquisition_plan.get(
                    "source_checkpoint_public_id"
                ),
                "continuation_plan_public_id": acquisition_plan.get(
                    "continuation_plan_public_id"
                ),
                "resume_page_budget": acquisition_plan.get(
                    "resume_page_budget"
                ),
            },
            "coverage": coverage,
            "summary": summary,
            "limitations": limitations,
            "message": message,
            "created_at": _isoformat(case_sync.created_at),
            "updated_at": _isoformat(case_sync.updated_at),
            "started_at": _isoformat(case_sync.started_at),
            "completed_at": _isoformat(case_sync.completed_at),
        }


def _sync_state(status: str) -> tuple[str, str]:
    return {
        "planned": ("queued", "queued"),
        "queued": ("queued", "queued"),
        "running": ("running", "ingesting"),
        "success": ("succeeded", "completed"),
        "partial": ("partial", "completed_with_limitations"),
        "error": ("failed", "failed"),
        "stale": ("failed", "failed"),
    }.get(status, ("failed", "failed"))


def _sync_request_fingerprint(payload: WalletCaseSyncRequest) -> str:
    """Hash one semantic request body without persisting HTTP metadata."""
    surface_order = {
        name: index
        for index, name in enumerate(
            ("transfers", "transactions", "swaps", "balances", "jettons")
        )
    }
    document = {
        "contract": "wallet_case_sync_request_v2",
        "mode": payload.mode,
        "time_window": payload.time_window,
        "custom_start": (
            _canonical_request_timestamp(payload.custom_start)
            if payload.custom_start
            else None
        ),
        "custom_end": (
            _canonical_request_timestamp(payload.custom_end)
            if payload.custom_end
            else None
        ),
        "surfaces": sorted(payload.surfaces, key=surface_order.__getitem__),
    }
    canonical = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _checkpoint_resume_fingerprint(
    checkpoint_public_id: str,
    *,
    continuation_plan_public_id: str | None = None,
    page_budget: int | None = None,
    backfill_schedule_public_id: str | None = None,
) -> str:
    document = {
        "contract": "wallet_case_checkpoint_resume_request_v1",
        "checkpoint_public_id": checkpoint_public_id,
    }
    if backfill_schedule_public_id is not None:
        document = {
            "contract": "wallet_case_backfill_schedule_run_request_v1",
            "backfill_schedule_public_id": backfill_schedule_public_id,
            "continuation_plan_public_id": continuation_plan_public_id,
            "checkpoint_public_id": checkpoint_public_id,
            "page_budget": page_budget,
        }
    elif continuation_plan_public_id is not None:
        if page_budget is None:
            document = {
                "contract": "wallet_case_checkpoint_plan_resume_request_v1",
                "continuation_plan_public_id": continuation_plan_public_id,
                "checkpoint_public_id": checkpoint_public_id,
            }
        else:
            document = {
                "contract": "wallet_case_checkpoint_plan_resume_request_v2",
                "continuation_plan_public_id": continuation_plan_public_id,
                "checkpoint_public_id": checkpoint_public_id,
                "page_budget": page_budget,
            }
    canonical = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _canonical_request_timestamp(value: str) -> str:
    """Canonicalize one valid custom-bound instant for semantic idempotency."""
    if value != value.strip():
        raise ValueError("Custom sync bounds must be unpadded ISO datetimes.")
    cleaned = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise ValueError("Custom sync bounds must be valid ISO datetimes.") from exc
    return _as_utc(parsed).isoformat().replace("+00:00", "Z")


def _parse_canonical_timestamp(value: str) -> datetime:
    cleaned = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return _as_utc(datetime.fromisoformat(cleaned))


def _strict_logical_time(value: Any) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or not value.isascii()
        or not value.isdigit()
        or value[0] == "0"
        or len(value) > 20
        or int(value, 10) > 2**64 - 1
    ):
        return None
    return value


def _queued_provider(_settings) -> str:
    # The compatibility field historically names observed provenance. A
    # durable queued/retry job has configuration, but no provider observation
    # yet; final publication replaces this sentinel atomically.
    return "pending_provider_observation"


def _poll_after_ms(case_sync: CaseSync) -> int:
    if case_sync.state not in {"queued", "running"}:
        return 15000
    if case_sync.stage != "retry_wait" or case_sync.next_attempt_at is None:
        return 1000
    remaining = (
        _as_utc(case_sync.next_attempt_at) - _utc_now()
    ).total_seconds()
    return max(500, min(15000, int(max(0.5, remaining) * 1000)))


def _actual_provider(run_response: dict[str, Any], settings) -> str:
    providers = sorted(
        {
            item.get("provider")
            for item in run_response.get("provider_evidence", [])
            if isinstance(item, dict)
            and isinstance(item.get("provider"), str)
            and item["provider"]
        }
    )
    if len(providers) == 1:
        return providers[0][:64]
    if providers:
        return "multiple_wallet_activity_providers"
    configured = str(getattr(settings, "wallet_activity_provider", "unknown"))
    return (configured or "unknown")[:64]


def _coverage_record(
    run_response: dict[str, Any],
    *,
    start_at: datetime,
    end_at: datetime,
    state: str,
    requested_surfaces: list[str] | None = None,
    acquisition_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    unavailable = _surface_list(run_response.get("unavailable_surfaces"))
    incomplete = _surface_list(run_response.get("incomplete_surfaces"))
    if run_response.get("data_mode") != "real" or state not in {
        "partial",
        "succeeded",
    }:
        coverage_state = "unknown"
    elif state == "partial" or unavailable or incomplete:
        coverage_state = "bounded_partial"
    else:
        coverage_state = "bounded_complete"
    if (
        acquisition_plan is not None
        and acquisition_plan.get("mode") in {"incremental", "resume"}
        and coverage_state == "bounded_complete"
    ):
        coverage_state = "bounded_partial"
    streams = _compact_coverage_streams(
        run_response.get("acquisition_streams")
    )
    coverage = {
        "state": coverage_state,
        "requested_start_at": _isoformat(start_at),
        "requested_end_at": _isoformat(end_at),
        "requested_surfaces": _surface_list(
            requested_surfaces
            if requested_surfaces is not None
            else run_response.get("requested_surfaces")
        ),
        "unavailable_surfaces": unavailable,
        "incomplete_surfaces": incomplete,
        "streams": streams,
        "full_history_proven": False,
    }
    if acquisition_plan is not None:
        coverage[_ACQUISITION_PLAN_KEY] = acquisition_plan
    return coverage


def _summary_from_run(run_response: dict[str, Any] | None) -> dict[str, Any]:
    if not run_response:
        return _zero_summary()
    activity_summary = run_response.get("activity_summary")
    if not isinstance(activity_summary, dict):
        activity_summary = {}
    counts = activity_summary.get("counts")
    if not isinstance(counts, dict):
        counts = {}
    balances = activity_summary.get("balances")
    if not isinstance(balances, dict):
        balances = {}
    portfolio = balances.get("portfolio")
    if not isinstance(portfolio, dict):
        portfolio = {}
    transactions = run_response.get("transactions")
    if not isinstance(transactions, list):
        transactions = []
    warnings = run_response.get("warnings")
    if not isinstance(warnings, list):
        warnings = []
    return {
        "activity_counts": {
            key: _nonnegative_int(counts.get(key))
            for key in ("transfers", "transactions", "swaps", "balances")
        },
        "failed_transaction_count": sum(
            1
            for row in transactions
            if isinstance(row, dict) and row.get("success") == "failed"
        ),
        "warning_count": len(warnings),
        "portfolio_snapshot": {
            "total_balance_usd": (
                str(portfolio["total_balance_usd"])
                if portfolio.get("total_balance_usd") is not None
                else None
            ),
            "priced_assets": _nonnegative_int(portfolio.get("priced_assets")),
            "unpriced_assets": _nonnegative_int(
                portfolio.get("unpriced_assets")
            ),
        },
    }


def _stored_summary(case_sync: CaseSync | None) -> dict[str, Any]:
    if case_sync is None:
        return _zero_summary()
    summary = _json_object(case_sync.result_summary_json)
    return summary if _valid_summary(summary) else _zero_summary()


def _sync_acquisition_plan(case_sync: CaseSync) -> dict[str, Any]:
    stored = _json_object(case_sync.coverage_summary_json).get(
        _ACQUISITION_PLAN_KEY
    )
    if stored is None:
        return {
            "version": 1,
            "mode": "bounded",
            "start_at": _isoformat(case_sync.requested_start),
            "end_at": _isoformat(case_sync.requested_end),
            "overlap_seconds": 0,
            "base_snapshot_public_id": None,
        }
    version_one_keys = {
        "version",
        "mode",
        "start_at",
        "end_at",
        "overlap_seconds",
        "base_snapshot_public_id",
    }
    version_two_keys = version_one_keys | {
        "source_checkpoint_public_id",
        "resume_stream_key",
        "resume_cursor",
        "resume_page_index",
    }
    version_three_keys = version_two_keys | {
        "continuation_plan_public_id",
    }
    version_four_keys = version_three_keys | {
        "resume_page_budget",
    }
    version_five_keys = version_four_keys | {
        "backfill_schedule_public_id",
    }
    expected_keys_by_version = {
        1: frozenset(version_one_keys),
        2: frozenset(version_two_keys),
        3: frozenset(version_three_keys),
        4: frozenset(version_four_keys),
        5: frozenset(version_five_keys),
    }
    if (
        not isinstance(stored, dict)
        or expected_keys_by_version.get(stored.get("version"))
        != frozenset(stored)
    ):
        raise ValueError("Stored Wallet Case acquisition plan is invalid.")
    mode = stored.get("mode")
    start_at = stored.get("start_at")
    end_at = stored.get("end_at")
    overlap_seconds = stored.get("overlap_seconds")
    base_public_id = stored.get("base_snapshot_public_id")
    source_checkpoint_public_id = stored.get("source_checkpoint_public_id")
    resume_stream_key = stored.get("resume_stream_key")
    resume_cursor = stored.get("resume_cursor")
    resume_page_index = stored.get("resume_page_index")
    continuation_plan_public_id = stored.get("continuation_plan_public_id")
    resume_page_budget = stored.get("resume_page_budget")
    backfill_schedule_public_id = stored.get("backfill_schedule_public_id")
    if (
        stored.get("version") not in {1, 2, 3, 4, 5}
        or mode not in {"bounded", "incremental", "resume"}
        or not isinstance(start_at, str)
        or not isinstance(end_at, str)
        or type(overlap_seconds) is not int
        or overlap_seconds < 0
        or overlap_seconds > 86400
    ):
        raise ValueError("Stored Wallet Case acquisition plan is invalid.")
    try:
        canonical_start = _canonical_request_timestamp(start_at)
        canonical_end = _canonical_request_timestamp(end_at)
    except ValueError as exc:
        raise ValueError("Stored Wallet Case acquisition plan is invalid.") from exc
    requested_start = _isoformat(case_sync.requested_start)
    requested_end = _isoformat(case_sync.requested_end)
    if (
        canonical_start != start_at
        or canonical_end != end_at
        or canonical_start >= canonical_end
        or end_at != requested_end
        or canonical_start < requested_start
    ):
        raise ValueError("Stored Wallet Case acquisition plan is invalid.")
    if mode == "bounded":
        if (
            stored.get("version") != 1
            or start_at != requested_start
            or overlap_seconds != 0
            or base_public_id is not None
        ):
            raise ValueError("Stored Wallet Case acquisition plan is invalid.")
    elif mode == "incremental":
        if (
            stored.get("version") != 1
            or not isinstance(base_public_id, str)
            or len(base_public_id) != 36
        ):
            raise ValueError("Stored Wallet Case acquisition plan is invalid.")
    elif (
        stored.get("version") not in {2, 3, 4, 5}
        or not isinstance(base_public_id, str)
        or len(base_public_id) != 36
        or not isinstance(source_checkpoint_public_id, str)
        or len(source_checkpoint_public_id) != 68
        or not source_checkpoint_public_id.startswith("scp_")
        or any(
            char not in "0123456789abcdef"
            for char in source_checkpoint_public_id[4:]
        )
        or resume_stream_key not in {"transactions", "account_events"}
        or _strict_logical_time(resume_cursor) is None
        or type(resume_page_index) is not int
        or resume_page_index < 1
        or overlap_seconds != 0
        or (
            stored.get("version") in {3, 4, 5}
            and (
                not isinstance(continuation_plan_public_id, str)
                or len(continuation_plan_public_id) != 68
                or not continuation_plan_public_id.startswith("cpl_")
                or any(
                    char not in "0123456789abcdef"
                    for char in continuation_plan_public_id[4:]
                )
            )
        )
        or (
            stored.get("version") in {4, 5}
            and (
                type(resume_page_budget) is not int
                or not 1 <= resume_page_budget <= 10
            )
        )
        or (
            stored.get("version") == 5
            and (
                not isinstance(backfill_schedule_public_id, str)
                or len(backfill_schedule_public_id) != 68
                or not backfill_schedule_public_id.startswith("bfs_")
                or any(
                    char not in "0123456789abcdef"
                    for char in backfill_schedule_public_id[4:]
                )
            )
        )
    ):
        raise ValueError("Stored Wallet Case acquisition plan is invalid.")
    return stored


def _stored_coverage(case_sync: CaseSync) -> dict[str, Any]:
    coverage = _json_object(case_sync.coverage_summary_json)
    coverage.pop(_ACQUISITION_PLAN_KEY, None)
    if not _valid_coverage(coverage, case_sync):
        return _coverage_record(
            {},
            start_at=case_sync.requested_start,
            end_at=case_sync.requested_end,
            state=case_sync.state,
            requested_surfaces=_json_list(
                case_sync.requested_surfaces_json
            ),
        )
    return {
        **coverage,
        "streams": _compact_coverage_streams(coverage.get("streams")),
    }


def _limitations_for_sync(
    case_sync: CaseSync,
    coverage: dict[str, Any],
) -> list[dict[str, str]]:
    requested = _json_list(case_sync.requested_surfaces_json)
    limitations = [
        _limitation(
            "bounded_interval_not_full_history",
            "This sync covers a bounded requested interval and does not prove full wallet history.",
        )
    ]
    if _sync_acquisition_plan(case_sync)["mode"] == "incremental":
        limitations.append(
            _limitation(
                "incremental_composite_not_full_history",
                "This snapshot composes prior usable sources with a forward overlap refresh; it does not prove complete history and its summary reflects the latest acquisition run.",
            )
        )
    if _sync_acquisition_plan(case_sync)["mode"] == "resume":
        limitations.append(
            _limitation(
                "checkpoint_resume_composite_not_full_history",
                "This snapshot continues one verified provider stream checkpoint; the composed observations remain bounded and do not prove complete wallet history.",
            )
        )
    pending = case_sync.state in {"queued", "running"}
    if pending:
        limitations.append(
            _limitation(
                "sync_in_progress",
                "This synchronization has not published a result yet.",
            )
        )
    if not pending and not _valid_summary(
        _json_object(case_sync.result_summary_json)
    ):
        limitations.append(
            _limitation(
                "summary_unavailable",
                "Activity and portfolio summary was not captured for this sync; zero placeholders are not evidence of no activity.",
            )
        )
    if not pending and not _valid_coverage(
        _json_object(case_sync.coverage_summary_json),
        case_sync,
    ):
        limitations.append(
            _limitation(
                "coverage_unavailable",
                "Stored coverage was missing or inconsistent; published coverage is reset to unknown.",
            )
        )
    if (
        case_sync.state in {"partial", "succeeded"}
        and case_sync.ingestion_run_id is not None
        and case_sync.acquisition_manifest is None
    ):
        limitations.append(
            _limitation(
                "acquisition_manifest_unavailable",
                "This legacy snapshot predates immutable acquisition manifests; provider page digests and checkpoints are unavailable.",
            )
        )
    if case_sync.data_mode == "mock":
        limitations.append(
            _limitation(
                "demo_fixture_not_chain_data",
                "Demo results are deterministic fixtures and are not live TON chain observations.",
            )
        )
    if {"transfers", "swaps"} & set(requested):
        limitations.append(
            _limitation(
                "provider_display_events_not_authoritative",
                "Provider display actions are observations, not an authoritative transaction ledger.",
            )
        )
    if {"balances", "jettons"} & set(requested):
        limitations.append(
            _limitation(
                "snapshot_not_historical_cost_basis",
                "Balance and price snapshots do not establish historical cost basis or PnL.",
            )
        )
    unavailable = _surface_list(coverage.get("unavailable_surfaces"))
    incomplete = _surface_list(coverage.get("incomplete_surfaces"))
    if case_sync.state == "partial" or unavailable or incomplete:
        limitations.append(
            _limitation(
                "partial_or_unavailable_surfaces",
                "One or more requested surfaces are incomplete or unavailable.",
            )
        )
    if case_sync.state == "failed":
        limitations.append(
            _limitation(
                "sync_failed",
                "The synchronization attempt failed and produced no complete coverage claim.",
            )
        )
    return limitations


def _manifest_response(
    manifest: WalletCaseSyncManifest,
    *,
    case_sync: CaseSync,
    case_public_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        document = verify_wallet_case_sync_manifest(
            manifest.manifest_json,
            manifest.content_hash_sha256,
        )
    except ValueError as exc:
        raise WalletCaseSyncManifestCorrupt(
            "Stored Wallet Case acquisition manifest failed integrity validation."
        ) from exc
    if (
        manifest.contract_version != MANIFEST_CONTRACT_VERSION
        or manifest.public_id != f"smf_{manifest.content_hash_sha256}"
        or document.get("case_public_id") != case_public_id
        or document.get("sync_public_id") != case_sync.public_id
    ):
        raise WalletCaseSyncManifestCorrupt(
            "Stored Wallet Case acquisition manifest identity is inconsistent."
        )
    streams = document.get("streams")
    if not isinstance(streams, list) or not all(
        isinstance(stream, dict) for stream in streams
    ):
        raise WalletCaseSyncManifestCorrupt(
            "Stored Wallet Case acquisition manifest streams are invalid."
        )
    pages: list[dict[str, Any]] = []
    for stream in streams:
        stream_pages = stream.get("pages")
        if not isinstance(stream_pages, list) or not all(
            isinstance(page, dict) for page in stream_pages
        ):
            raise WalletCaseSyncManifestCorrupt(
                "Stored Wallet Case acquisition manifest pages are invalid."
            )
        pages.extend(stream_pages)
    descriptor = {
        "public_id": manifest.public_id,
        "contract_version": manifest.contract_version,
        "content_hash_sha256": manifest.content_hash_sha256,
        "stream_count": len(streams),
        "page_count": len(pages),
        "response_digest_count": sum(
            isinstance(page.get("response_digest_sha256"), str)
            for page in pages
        ),
        "created_at": _isoformat(manifest.created_at),
    }
    return descriptor, document


def _stream_checkpoint_response(
    checkpoint: WalletCaseStreamCheckpoint,
    *,
    case_public_id: str,
) -> dict[str, Any]:
    try:
        document = verify_wallet_case_stream_checkpoint(
            checkpoint.checkpoint_json,
            checkpoint.checkpoint_hash_sha256,
        )
    except ValueError as exc:
        raise WalletCaseStreamCheckpointCorrupt(
            "Stored Wallet Case stream checkpoint failed integrity validation."
        ) from exc
    source_sync = checkpoint.source_sync
    if source_sync.case_id != checkpoint.case_id:
        raise WalletCaseStreamCheckpointCorrupt(
            "Stored Wallet Case stream checkpoint source sync is foreign."
        )
    try:
        acquisition_plan = _sync_acquisition_plan(source_sync)
    except ValueError as exc:
        raise WalletCaseStreamCheckpointCorrupt(
            "Stored Wallet Case stream checkpoint acquisition plan is invalid."
        ) from exc
    source_manifest = source_sync.acquisition_manifest
    if source_manifest is None:
        raise WalletCaseStreamCheckpointCorrupt(
            "Stored Wallet Case stream checkpoint has no source manifest."
        )
    try:
        source_manifest_descriptor, _source_manifest_document = (
            _manifest_response(
                source_manifest,
                case_sync=source_sync,
                case_public_id=case_public_id,
            )
        )
    except WalletCaseSyncManifestCorrupt as exc:
        raise WalletCaseStreamCheckpointCorrupt(
            "Stored Wallet Case stream checkpoint source manifest is invalid."
        ) from exc
    expected_public_id = f"scp_{checkpoint.checkpoint_hash_sha256}"
    if (
        checkpoint.contract_version != CHECKPOINT_CONTRACT_VERSION
        or checkpoint.public_id != expected_public_id
        or document.get("case_public_id") != case_public_id
        or document.get("source_sync_public_id") != source_sync.public_id
        or document.get("provider") != checkpoint.provider
        or document.get("stream_key") != checkpoint.stream_key
        or document.get("provider_contract_version")
        != checkpoint.provider_contract_version
        or document.get("acquisition_mode") != acquisition_plan["mode"]
        or document.get("requested_period")
        != {
            "start_at": acquisition_plan["start_at"],
            "end_at": acquisition_plan["end_at"],
        }
        or (
            acquisition_plan["mode"] == "resume"
            and acquisition_plan.get("resume_stream_key")
            != checkpoint.stream_key
        )
        or document.get("resume_state") != checkpoint.resume_state
        or document.get("continuation_cursor")
        != checkpoint.continuation_cursor
        or document.get("continuation_page_index")
        != checkpoint.continuation_page_index
        or document.get("page_count") != checkpoint.page_count
        or document.get("pages_succeeded") != checkpoint.pages_succeeded
        or document.get("source_manifest_public_id")
        != source_manifest_descriptor["public_id"]
        or document.get("source_manifest_hash_sha256")
        != source_manifest_descriptor["content_hash_sha256"]
    ):
        raise WalletCaseStreamCheckpointCorrupt(
            "Stored Wallet Case stream checkpoint identity is inconsistent."
        )
    return {
        "checkpoint": {
            "public_id": checkpoint.public_id,
            "contract_version": checkpoint.contract_version,
            "checkpoint_hash_sha256": checkpoint.checkpoint_hash_sha256,
            "provider": checkpoint.provider,
            "stream_key": checkpoint.stream_key,
            "provider_contract_version": (
                checkpoint.provider_contract_version
            ),
            "source_sync_public_id": source_sync.public_id,
            "resume_state": checkpoint.resume_state,
            "created_at": _isoformat(checkpoint.created_at),
        },
        "document": document,
    }


def _backfill_frontier(
    item: dict[str, Any],
) -> dict[str, Any] | None:
    """Bind one successful provider-page boundary to its checkpoint revision."""
    response = item["response"]
    last_page = response["document"]["last_successful_page"]
    if last_page is None:
        return None
    return {
        "checkpoint_public_id": response["checkpoint"]["public_id"],
        "page": last_page,
    }


def _valid_coverage(value: dict[str, Any], case_sync: CaseSync) -> bool:
    value = {
        key: item
        for key, item in value.items()
        if key != _ACQUISITION_PLAN_KEY
    }
    required = {
        "state",
        "requested_start_at",
        "requested_end_at",
        "requested_surfaces",
        "unavailable_surfaces",
        "incomplete_surfaces",
        "streams",
        "full_history_proven",
    }
    if (
        set(value) != required
        or value.get("state")
        not in {"unknown", "bounded_partial", "bounded_complete"}
        or value.get("full_history_proven") is not False
        or value.get("requested_start_at")
        != _isoformat(case_sync.requested_start)
        or value.get("requested_end_at") != _isoformat(case_sync.requested_end)
    ):
        return False
    raw_requested = value.get("requested_surfaces")
    raw_unavailable = value.get("unavailable_surfaces")
    raw_incomplete = value.get("incomplete_surfaces")
    if not all(
        isinstance(item, list)
        and item == _surface_list(item)
        for item in (raw_requested, raw_unavailable, raw_incomplete)
    ):
        return False
    requested = _surface_list(raw_requested)
    unavailable = _surface_list(raw_unavailable)
    incomplete = _surface_list(raw_incomplete)
    if (
        not requested
        or requested != _json_list(case_sync.requested_surfaces_json)
        or not set(unavailable + incomplete).issubset(requested)
        or set(unavailable) & set(incomplete)
    ):
        return False
    raw_streams = value.get("streams")
    streams = _compact_coverage_streams(raw_streams)
    if not isinstance(raw_streams, list) or len(streams) != len(raw_streams):
        return False
    state = value["state"]
    if case_sync.data_mode == "mock" and state != "unknown":
        return False
    if state in {"bounded_partial", "bounded_complete"} and case_sync.data_mode != "real":
        return False
    if state == "bounded_complete" and (
        case_sync.state != "succeeded"
        or unavailable
        or incomplete
        or any(
            stream["completion_state"] != "complete"
            or stream["error_code"] is not None
            for stream in streams
        )
    ):
        return False
    return True


def _valid_summary(value: dict[str, Any]) -> bool:
    if set(value) != {
        "activity_counts",
        "failed_transaction_count",
        "warning_count",
        "portfolio_snapshot",
    }:
        return False
    counts = value.get("activity_counts")
    portfolio = value.get("portfolio_snapshot")
    if not isinstance(counts, dict) or set(counts) != {
        "transfers",
        "transactions",
        "swaps",
        "balances",
    }:
        return False
    if not isinstance(portfolio, dict) or set(portfolio) != {
        "total_balance_usd",
        "priced_assets",
        "unpriced_assets",
    }:
        return False
    integers = [
        *counts.values(),
        value.get("failed_transaction_count"),
        value.get("warning_count"),
        portfolio.get("priced_assets"),
        portfolio.get("unpriced_assets"),
    ]
    return (
        all(type(item) is int and item >= 0 for item in integers)
        and (
            portfolio.get("total_balance_usd") is None
            or isinstance(portfolio.get("total_balance_usd"), str)
        )
    )


def _limitation(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def _zero_summary() -> dict[str, Any]:
    return json.loads(json.dumps(_ZERO_SUMMARY))


def _surface_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    allowed = {"transfers", "transactions", "swaps", "balances", "jettons"}
    return list(dict.fromkeys(item for item in value if item in allowed))


def _compact_coverage_streams(value: Any) -> list[dict[str, Any]]:
    """Publish only bounded stream state, never request/page diagnostics."""
    if not isinstance(value, list):
        return []
    streams: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        provider = item.get("provider")
        stream_key = item.get("stream_key")
        completion_state = item.get("completion_state")
        error_code = item.get("error_code")
        if not all(
            isinstance(field, str) and field
            for field in (provider, stream_key, completion_state)
        ) or completion_state not in {
            "complete",
            "incomplete",
            "error",
            "preview_only",
        }:
            continue
        streams.append(
            {
                "provider": provider[:64],
                "stream_key": stream_key[:64],
                "completion_state": completion_state[:32],
                "error_code": error_code[:64]
                if isinstance(error_code, str) and error_code
                else None,
            }
        )
    return streams


def _nonnegative_int(value: Any) -> int:
    return value if type(value) is int and value >= 0 else 0


def _case_catalog_scope_digest(owner_scope_id: str) -> str:
    return hashlib.sha256(owner_scope_id.encode("utf-8")).hexdigest()


def _case_catalog_filter_digest(
    *,
    query: str | None,
    network: str | None,
    data_environment: str | None,
) -> str:
    payload = _case_catalog_cursor_json(
        {
            "data_environment": data_environment,
            "network": network,
            "query": query,
        }
    )
    return hashlib.sha256(payload).hexdigest()


def _case_catalog_cursor_json(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _encode_checkpoint_history_cursor(document: dict[str, Any]) -> str:
    payload = _case_catalog_cursor_json(document)
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        _CHECKPOINT_HISTORY_CURSOR_KEY,
        payload,
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def _decode_checkpoint_history_cursor(value: str) -> dict[str, Any]:
    error = "Checkpoint history cursor is invalid."
    if not value or len(value) > 1024 or value.count(".") != 1:
        raise WalletCaseCheckpointHistoryInvalidCursor(error)
    encoded, signature = value.split(".", 1)
    if (
        not encoded
        or len(signature) != 64
        or any(char not in "0123456789abcdef" for char in signature)
        or any(
            char
            not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for char in encoded
        )
    ):
        raise WalletCaseCheckpointHistoryInvalidCursor(error)
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WalletCaseCheckpointHistoryInvalidCursor(error) from exc
    if (
        not isinstance(document, dict)
        or set(document) != {"v", "case", "cutoff", "after"}
        or document.get("v") != _CHECKPOINT_HISTORY_CURSOR_VERSION
    ):
        raise WalletCaseCheckpointHistoryInvalidCursor(
            "Checkpoint history cursor shape is invalid."
        )
    expected = hmac.new(
        _CHECKPOINT_HISTORY_CURSOR_KEY,
        raw,
        hashlib.sha256,
    ).hexdigest()
    if (
        not hmac.compare_digest(signature, expected)
        or _encode_checkpoint_history_cursor(document) != value
    ):
        raise WalletCaseCheckpointHistoryInvalidCursor(
            "Checkpoint history cursor signature is invalid."
        )
    case_public_id = document.get("case")
    identifiers = (document.get("cutoff"), document.get("after"))
    if (
        not isinstance(case_public_id, str)
        or len(case_public_id) != 36
        or any(
            not isinstance(identifier, str)
            or len(identifier) != 68
            or not identifier.startswith("scp_")
            or any(
                char not in "0123456789abcdef"
                for char in identifier[4:]
            )
            for identifier in identifiers
        )
    ):
        raise WalletCaseCheckpointHistoryInvalidCursor(
            "Checkpoint history cursor identifiers are invalid."
        )
    return document


def _encode_case_catalog_cursor(document: dict[str, Any]) -> str:
    payload = _case_catalog_cursor_json(document)
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(
        _CASE_CATALOG_CURSOR_KEY,
        payload,
        hashlib.sha256,
    ).hexdigest()
    return f"{encoded}.{signature}"


def _decode_case_catalog_cursor(value: str) -> dict[str, Any]:
    if not value or len(value) > 1024 or value.count(".") != 1:
        raise WalletCaseCatalogInvalidCursor(
            "Wallet Case catalog cursor is invalid."
        )
    encoded, signature = value.split(".", 1)
    if (
        not encoded
        or len(signature) != 64
        or any(char not in "0123456789abcdef" for char in signature)
        or any(
            char
            not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
            for char in encoded
        )
    ):
        raise WalletCaseCatalogInvalidCursor(
            "Wallet Case catalog cursor is invalid."
        )
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise WalletCaseCatalogInvalidCursor(
            "Wallet Case catalog cursor is invalid."
        ) from exc
    if (
        not isinstance(document, dict)
        or set(document) != {
            "v",
            "scope",
            "state",
            "filters",
            "cutoff",
            "after",
        }
        or document.get("v") != _CASE_CATALOG_CURSOR_VERSION
    ):
        raise WalletCaseCatalogInvalidCursor(
            "Wallet Case catalog cursor shape is invalid."
        )
    expected = hmac.new(
        _CASE_CATALOG_CURSOR_KEY,
        raw,
        hashlib.sha256,
    ).hexdigest()
    if (
        not hmac.compare_digest(signature, expected)
        or _encode_case_catalog_cursor(document) != value
    ):
        raise WalletCaseCatalogInvalidCursor(
            "Wallet Case catalog cursor signature is invalid."
        )
    scope = document.get("scope")
    state = document.get("state")
    filters = document.get("filters")
    cutoff = document.get("cutoff")
    after = document.get("after")
    if (
        not isinstance(scope, str)
        or len(scope) != 64
        or any(char not in "0123456789abcdef" for char in scope)
        or state not in {"active", "archived"}
        or not isinstance(filters, str)
        or len(filters) != 64
        or any(char not in "0123456789abcdef" for char in filters)
        or type(cutoff) is not int
        or type(after) is not int
        or cutoff < 1
        or after < 1
        or after > cutoff
    ):
        raise WalletCaseCatalogInvalidCursor(
            "Wallet Case catalog cursor values are invalid."
        )
    return document


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return _surface_list(parsed)


def _bounded_message(value: Any) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:1000]


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat().replace("+00:00", "Z")
