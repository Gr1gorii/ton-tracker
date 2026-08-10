"""Bounded source loading for the Wallet Case Activity facade."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from models import (
    CaseSync,
    WalletCase,
    WalletIngestionRun,
    WalletSwap,
    WalletTransaction,
    WalletTransfer,
)


@dataclass(frozen=True)
class WalletCaseActivitySources:
    syncs: tuple[CaseSync, ...]
    runs: dict[int, WalletIngestionRun]
    transactions: tuple[WalletTransaction, ...]
    transfers: tuple[WalletTransfer, ...]
    swaps: tuple[WalletSwap, ...]


class WalletCaseActivityRepository:
    """Apply case/snapshot scope before any activity row is materialized."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_case(self, *, owner_scope_id: str, public_id: str) -> WalletCase | None:
        return self.session.scalar(
            select(WalletCase).where(
                WalletCase.owner_scope_id == owner_scope_id,
                WalletCase.public_id == public_id,
                WalletCase.archived_at.is_(None),
            )
        )

    def get_snapshot(
        self,
        *,
        case_id: int,
        public_id: str | None,
    ) -> CaseSync | None:
        statement = select(CaseSync).where(
            CaseSync.case_id == case_id,
            CaseSync.state.in_(("partial", "succeeded")),
            CaseSync.ingestion_run_id.is_not(None),
        )
        if public_id is not None:
            statement = statement.where(CaseSync.public_id == public_id)
        else:
            statement = statement.order_by(CaseSync.id.desc()).limit(1)
        return self.session.scalar(statement)

    def source_syncs(
        self,
        *,
        snapshot: CaseSync,
        start_at: datetime | None,
        end_at: datetime | None,
        maximum: int,
    ) -> tuple[CaseSync, ...] | None:
        statement = select(CaseSync).where(
            CaseSync.case_id == snapshot.case_id,
            CaseSync.id <= snapshot.id,
            CaseSync.state.in_(("partial", "succeeded")),
            CaseSync.ingestion_run_id.is_not(None),
        )
        if start_at is not None and end_at is not None:
            statement = statement.where(
                CaseSync.requested_start < end_at,
                CaseSync.requested_end > start_at,
            )
        candidates = tuple(
            self.session.scalars(
                statement.order_by(CaseSync.id.asc()).limit(maximum + 1)
            )
        )
        if len(candidates) > maximum:
            return None
        return candidates

    def load_sources(
        self,
        *,
        syncs: tuple[CaseSync, ...],
        start_at: datetime | None,
        end_at: datetime | None,
        maximum_rows: int,
    ) -> WalletCaseActivitySources | None:
        run_ids = tuple(
            sync.ingestion_run_id
            for sync in syncs
            if sync.ingestion_run_id is not None
        )
        if not run_ids:
            return WalletCaseActivitySources(syncs, {}, (), (), ())

        runs = {
            run.id: run
            for run in self.session.scalars(
                select(WalletIngestionRun).where(WalletIngestionRun.id.in_(run_ids))
            )
        }
        models = (WalletTransaction, WalletTransfer, WalletSwap)
        counts = [
            int(
                self.session.scalar(
                    select(func.count())
                    .select_from(model)
                    .where(model.run_id.in_(run_ids))
                    .where(_period_predicate(model, start_at, end_at))
                )
                or 0
            )
            for model in models
        ]
        if sum(counts) > maximum_rows:
            return None

        def rows(model):
            return tuple(
                self.session.scalars(
                    select(model)
                    .where(model.run_id.in_(run_ids))
                    .where(_period_predicate(model, start_at, end_at))
                    .order_by(model.run_id.asc(), model.id.asc())
                )
            )

        return WalletCaseActivitySources(
            syncs=syncs,
            runs=runs,
            transactions=rows(WalletTransaction),
            transfers=rows(WalletTransfer),
            swaps=rows(WalletSwap),
        )


def _period_predicate(model, start_at: datetime | None, end_at: datetime | None):
    if start_at is None or end_at is None:
        return model.id.is_not(None)
    # Timestamp-less normalized rows remain visible with an explicit limitation;
    # their bounded provider query is still part of the pinned snapshot basis.
    return or_(
        model.timestamp.is_(None),
        (model.timestamp >= start_at) & (model.timestamp < end_at),
    )
