"""Wallet Case application service over the existing ingestion subsystem."""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import datetime, timezone
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
    WalletIngestionRun,
)
from repositories.wallet_cases import WalletCaseRepository
from services.ton_address_identity import derive_ton_wallet_identity
from services.wallet_acquisition_bounds import resolve_wallet_acquisition_bounds
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


_ENVIRONMENT_DATA_MODE = {"demo": "mock", "live": "real"}
_SYNC_PROGRESS_TOTAL = 3
_CASE_CATALOG_CURSOR_KEY = secrets.token_bytes(32)
_CASE_CATALOG_CURSOR_VERSION = 3
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
        bounds = resolve_wallet_acquisition_bounds(
            time_window=payload.time_window,
            custom_start=payload.custom_start,
            custom_end=payload.custom_end,
            now=queued_at,
        )
        expected_data_mode = _ENVIRONMENT_DATA_MODE[wallet_case.data_environment]
        coverage = _coverage_record(
            {"requested_surfaces": payload.surfaces, "data_mode": expected_data_mode},
            start_at=bounds.start,
            end_at=bounds.end,
            state="queued",
            requested_surfaces=payload.surfaces,
        )
        case_sync = CaseSync(
            case=wallet_case,
            time_window=payload.time_window,
            data_mode=expected_data_mode,
            provider=_queued_provider(ingestion_settings),
            requested_start=bounds.start,
            requested_end=bounds.end,
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
            "provider": case_sync.provider,
            "data_mode": case_sync.data_mode,
            "requested_scope": {
                "time_window": case_sync.time_window,
                "start_at": _isoformat(case_sync.requested_start),
                "end_at": _isoformat(case_sync.requested_end),
                "surfaces": _json_list(case_sync.requested_surfaces_json),
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
        "contract": "wallet_case_sync_request_v1",
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
    streams = _compact_coverage_streams(
        run_response.get("acquisition_streams")
    )
    return {
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


def _stored_coverage(case_sync: CaseSync) -> dict[str, Any]:
    coverage = _json_object(case_sync.coverage_summary_json)
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


def _valid_coverage(value: dict[str, Any], case_sync: CaseSync) -> bool:
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
