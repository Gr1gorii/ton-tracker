"""Database access for owner-scoped Wallet Cases and their sync attempts."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import (
    CaseEvidenceVerification,
    CaseSync,
    WalletCase,
    WalletCaseCatalogEvent,
)


class WalletCaseRepository:
    """Keep owner-scope predicates out of routers and presentation code."""

    def __init__(self, session: Session) -> None:
        self.session = session

    def get_by_identity(
        self,
        *,
        owner_scope_id: str,
        network: str,
        data_environment: str,
        canonical_wallet_key: str,
    ) -> WalletCase | None:
        statement = select(WalletCase).where(
            WalletCase.owner_scope_id == owner_scope_id,
            WalletCase.network == network,
            WalletCase.data_environment == data_environment,
            WalletCase.canonical_wallet_key == canonical_wallet_key,
        )
        return self.session.scalar(statement)

    def get_by_public_id(
        self,
        *,
        owner_scope_id: str,
        public_id: str,
    ) -> WalletCase | None:
        statement = select(WalletCase).where(
            WalletCase.owner_scope_id == owner_scope_id,
            WalletCase.public_id == public_id,
            WalletCase.archived_at.is_(None),
        )
        return self.session.scalar(statement)

    def get_any_by_public_id(
        self,
        *,
        owner_scope_id: str,
        public_id: str,
    ) -> WalletCase | None:
        """Load an active or archived Case without crossing the owner boundary."""
        return self.session.scalar(
            select(WalletCase).where(
                WalletCase.owner_scope_id == owner_scope_id,
                WalletCase.public_id == public_id,
            )
        )

    def active_catalog_cutoff(self, *, owner_scope_id: str) -> int | None:
        return self.session.scalar(
            select(func.max(WalletCaseCatalogEvent.id))
            .join(WalletCase, WalletCase.id == WalletCaseCatalogEvent.case_id)
            .where(
                WalletCase.owner_scope_id == owner_scope_id,
                WalletCase.archived_at.is_(None),
            )
        )

    def list_active_at_catalog_cutoff(
        self,
        *,
        owner_scope_id: str,
        limit: int,
        cutoff: int,
        after: int | None,
    ) -> tuple[list[tuple[WalletCase, int]], bool]:
        frozen_positions = (
            select(
                WalletCaseCatalogEvent.case_id.label("case_id"),
                func.max(WalletCaseCatalogEvent.id).label("position"),
            )
            .where(WalletCaseCatalogEvent.id <= cutoff)
            .group_by(WalletCaseCatalogEvent.case_id)
            .subquery()
        )
        statement = (
            select(WalletCase, frozen_positions.c.position)
            .join(
                frozen_positions,
                frozen_positions.c.case_id == WalletCase.id,
            )
            .join(
                WalletCaseCatalogEvent,
                WalletCaseCatalogEvent.id == frozen_positions.c.position,
            )
            .where(
                WalletCase.owner_scope_id == owner_scope_id,
                WalletCase.archived_at.is_(None),
                WalletCaseCatalogEvent.visible.is_(True),
            )
            .order_by(frozen_positions.c.position.desc())
            .limit(limit + 1)
        )
        if after is not None:
            statement = statement.where(frozen_positions.c.position < after)
        candidates = [
            (wallet_case, int(position))
            for wallet_case, position in self.session.execute(statement).all()
        ]
        return candidates[:limit], len(candidates) > limit

    def latest_syncs(self, case_ids: list[int]) -> dict[int, CaseSync]:
        """Load at most one compact latest attempt per case."""
        if not case_ids:
            return {}
        latest_ids = (
            select(func.max(CaseSync.id))
            .where(CaseSync.case_id.in_(case_ids))
            .group_by(CaseSync.case_id)
        )
        statement = select(CaseSync).where(CaseSync.id.in_(latest_ids))
        syncs = self.session.scalars(statement).unique()
        return {case_sync.case_id: case_sync for case_sync in syncs}

    def active_syncs(self, case_ids: list[int]) -> dict[int, CaseSync]:
        """Load the single queued/running attempt allowed for each case."""
        if not case_ids:
            return {}
        statement = select(CaseSync).where(
            CaseSync.case_id.in_(case_ids),
            CaseSync.state.in_(("queued", "running")),
        )
        return {
            case_sync.case_id: case_sync
            for case_sync in self.session.scalars(statement).unique()
        }

    def latest_usable_syncs(self, case_ids: list[int]) -> dict[int, CaseSync]:
        """Load the newest partial/succeeded immutable result per case."""
        if not case_ids:
            return {}
        latest_ids = (
            select(func.max(CaseSync.id))
            .where(
                CaseSync.case_id.in_(case_ids),
                CaseSync.state.in_(("partial", "succeeded")),
            )
            .group_by(CaseSync.case_id)
        )
        statement = select(CaseSync).where(CaseSync.id.in_(latest_ids))
        return {
            case_sync.case_id: case_sync
            for case_sync in self.session.scalars(statement).unique()
        }

    def get_by_idempotency_key(
        self,
        *,
        case_id: int,
        idempotency_key: str,
    ) -> CaseSync | None:
        return self.session.scalar(
            select(CaseSync).where(
                CaseSync.case_id == case_id,
                CaseSync.idempotency_key == idempotency_key,
            )
        )

    def get_active_sync(self, *, case_id: int) -> CaseSync | None:
        return self.session.scalar(
            select(CaseSync).where(
                CaseSync.case_id == case_id,
                CaseSync.state.in_(("queued", "running")),
            )
        )

    def get_active_evidence_verification(
        self,
        *,
        case_id: int,
    ) -> CaseEvidenceVerification | None:
        return self.session.scalar(
            select(CaseEvidenceVerification).where(
                CaseEvidenceVerification.case_id == case_id,
                CaseEvidenceVerification.state.in_(("queued", "running")),
            )
        )

    def get_sync_by_public_id_for_owner(
        self,
        *,
        owner_scope_id: str,
        public_id: str,
    ) -> CaseSync | None:
        return self.session.scalar(
            select(CaseSync)
            .join(WalletCase, WalletCase.id == CaseSync.case_id)
            .where(
                WalletCase.owner_scope_id == owner_scope_id,
                WalletCase.archived_at.is_(None),
                CaseSync.public_id == public_id,
            )
        )

    def get_sync(
        self,
        *,
        case_id: int,
        public_id: str,
    ) -> CaseSync | None:
        statement = (
            select(CaseSync)
            .where(
                CaseSync.case_id == case_id,
                CaseSync.public_id == public_id,
            )
        )
        return self.session.scalar(statement)

    def add_case(self, wallet_case: WalletCase) -> None:
        self.session.add(wallet_case)

    def add_sync(self, case_sync: CaseSync) -> None:
        self.session.add(case_sync)
