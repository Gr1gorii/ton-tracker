"""Database access for owner-scoped Wallet Cases and their sync attempts."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from models import CaseSync, WalletCase


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

    def list_active(
        self,
        *,
        owner_scope_id: str,
        limit: int,
    ) -> tuple[list[WalletCase], bool]:
        statement = (
            select(WalletCase)
            .where(
                WalletCase.owner_scope_id == owner_scope_id,
                WalletCase.archived_at.is_(None),
            )
            .order_by(WalletCase.updated_at.desc(), WalletCase.id.desc())
            .limit(limit + 1)
        )
        candidates = list(self.session.scalars(statement).unique())
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
