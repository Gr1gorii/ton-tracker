"""Pinned, deduplicated Wallet Case Activity read facade.

The facade never mutates source evidence. It revalidates persisted identity
contracts, keeps unknown identities distinct, and pins every page to one
usable CaseSync revision.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import hmac
import json
import re
import secrets
from typing import Any, Iterable

from sqlalchemy.orm import Session

from models import (
    CaseSync,
    LOCAL_SINGLE_USER_SCOPE,
    WalletCase,
    WalletIngestionRun,
    WalletSwap,
    WalletTransaction,
    WalletTransfer,
)
from repositories.wallet_case_activity import (
    WalletCaseActivityRepository,
    WalletCaseActivitySources,
)
from services.dex_protocols import SUPPORTED_DEX_PROTOCOL_IDS, classify_dex_protocol
from services.ton_address_identity import derive_ton_wallet_identity, parse_ton_address
from services.ton_event_action_identity import derive_ton_event_action_identity
from services.ton_transaction_identity import derive_ton_transaction_identity
from services.wallet_cases import _stored_coverage, _sync_acquisition_plan


MAX_SOURCE_SYNCS = 256
# A local provider run can be large, but materializing raw-normalized source
# JSON for hundreds of thousands of rows would make a read endpoint unsafe.
# Refuse oversized revisions before loading ORM rows; no partial page is served.
MAX_SOURCE_ROWS = 25_000
MAX_DETAIL_SOURCES = 50
_KINDS = ("transaction", "transfer", "swap")
_DIRECTIONS = ("in", "out", "unknown")
_OUTCOMES = ("success", "failed", "unknown")
_DATA_ORIGINS = ("demo_fixture", "provider_observed")
_SORTS = ("newest", "oldest")
_CURSOR_KEY = secrets.token_bytes(32)
_PUBLIC_LOGICAL_TIME_RE = re.compile(r"^(?:0|[1-9][0-9]{0,19})$")
_MAX_PUBLIC_LOGICAL_TIME = 2**64 - 1


class WalletCaseActivityNotFound(LookupError):
    code = "wallet_case_not_found"


class WalletCaseActivitySnapshotNotFound(LookupError):
    code = "activity_snapshot_not_found"


class WalletCaseActivityItemNotFound(LookupError):
    code = "activity_not_found"


class WalletCaseActivityInvalidQuery(ValueError):
    code = "invalid_activity_query"


class WalletCaseActivityInvalidCursor(ValueError):
    code = "invalid_activity_cursor"


class WalletCaseActivityScopeTooLarge(RuntimeError):
    code = "activity_scope_too_large"


class WalletCaseActivitySnapshotConflict(RuntimeError):
    code = "activity_snapshot_invalid"


@dataclass(frozen=True)
class WalletCaseActivityQuery:
    snapshot_public_id: str | None = None
    limit: int = 50
    cursor: str | None = None
    kinds: tuple[str, ...] = ()
    directions: tuple[str, ...] = ()
    outcomes: tuple[str, ...] = ()
    from_at: datetime | None = None
    to_at: datetime | None = None
    asset_id: str | None = None
    protocol_id: str | None = None
    counterparty: str | None = None
    counterparty_network: str | None = None
    data_origins: tuple[str, ...] = ()
    sort: str = "newest"


@dataclass(frozen=True)
class _Observation:
    sync_id: int
    sync_public_id: str
    row_id: int
    kind: str
    identity_namespace: str | None
    identity_key: str | None
    semantic_fingerprint: str
    item: dict[str, Any]
    observed_at: str | None
    provider: str
    source_status: str
    data_origin: str


@dataclass(frozen=True)
class _BuiltActivity:
    items: tuple[dict[str, Any], ...]
    sources_by_public_id: dict[str, tuple[dict[str, Any], ...]]
    observations_by_public_id: dict[str, tuple[_Observation, ...]]
    valid_sync_kinds: tuple[frozenset[str], ...]
    scope_mismatch_kinds: tuple[str, ...]
    invalid_provenance_kinds: tuple[str, ...]
    conflicted_groups: tuple[tuple[dict[str, Any], ...], ...]


@dataclass(frozen=True)
class ResolvedCaseActivityTransaction:
    wallet_case: WalletCase
    snapshot: CaseSync
    source_sync: CaseSync
    source_run: WalletIngestionRun
    source_transaction: WalletTransaction
    activity_public_id: str
    semantic_fingerprint: str
    item: dict[str, Any]


@dataclass(frozen=True)
class ResolvedCaseActivityRevision:
    wallet_case: WalletCase
    snapshot: CaseSync
    activity_public_ids: frozenset[str]
    verifiable_transactions: dict[str, ResolvedCaseActivityTransaction]


@dataclass(frozen=True)
class ResolvedCaseActivityDataset:
    """One fully materialized, pinned Activity read revision.

    Case-level derived read models use this internal bridge so they do not
    paginate and rebuild the same bounded source revision once per page.  It
    deliberately contains public Activity records only; source row and run
    identifiers remain private to the Activity/Evidence services.
    """

    wallet_case: WalletCase
    snapshot: CaseSync | None
    snapshot_record: dict[str, Any] | None
    aggregate: dict[str, Any]
    observed_period: dict[str, Any] | None
    gaps: tuple[dict[str, Any], ...]
    limitations: tuple[dict[str, Any], ...]
    items: tuple[dict[str, Any], ...]


class WalletCaseActivityService:
    def __init__(
        self,
        session: Session,
        *,
        owner_scope_id: str = LOCAL_SINGLE_USER_SCOPE,
    ) -> None:
        self.session = session
        self.owner_scope_id = owner_scope_id
        self.repository = WalletCaseActivityRepository(session)

    def list_activity(
        self,
        case_public_id: str,
        query: WalletCaseActivityQuery,
    ) -> dict[str, Any]:
        if query.cursor is not None:
            cursor_document = _decode_cursor(query.cursor)
            if cursor_document["case"] != case_public_id:
                raise WalletCaseActivityInvalidCursor(
                    "Activity cursor belongs to another Wallet Case."
                )
            if query.snapshot_public_id is None:
                query = replace(
                    query,
                    snapshot_public_id=cursor_document["snapshot"],
                )
            elif query.snapshot_public_id != cursor_document["snapshot"]:
                raise WalletCaseActivityInvalidCursor(
                    "Activity cursor belongs to another snapshot."
                )
        query = normalize_activity_query(query)
        wallet_case = self._required_case(case_public_id)
        if (
            query.counterparty_network is not None
            and query.counterparty_network != wallet_case.network
        ):
            raise WalletCaseActivityInvalidQuery(
                "counterparty address belongs to another TON network."
            )
        snapshot = self.repository.get_snapshot(
            case_id=wallet_case.id,
            public_id=query.snapshot_public_id,
        )
        if snapshot is None:
            if query.snapshot_public_id is not None:
                raise WalletCaseActivitySnapshotNotFound(
                    "The requested Wallet Case snapshot is unavailable."
                )
            return _empty_response(wallet_case.public_id, query)

        _validate_query_period(snapshot, query)
        start_at, end_at = _effective_period(snapshot, query)
        row_start_at, row_end_at = _row_period(snapshot, query, start_at, end_at)
        source_syncs = self.repository.source_syncs(
            snapshot=snapshot,
            start_at=start_at,
            end_at=end_at,
            maximum=MAX_SOURCE_SYNCS,
        )
        if source_syncs is None:
            raise WalletCaseActivityScopeTooLarge(
                "The pinned activity revision includes too many synchronization sources."
            )
        sources = self.repository.load_sources(
            syncs=source_syncs,
            start_at=row_start_at,
            end_at=row_end_at,
            maximum_rows=MAX_SOURCE_ROWS,
        )
        if sources is None:
            raise WalletCaseActivityScopeTooLarge(
                "The pinned activity revision contains too many normalized rows."
            )
        snapshot_run = sources.runs.get(snapshot.ingestion_run_id)
        if snapshot_run is None or not _run_matches_case(
            snapshot_run,
            snapshot,
            wallet_case,
            "mock" if wallet_case.data_environment == "demo" else "real",
        ):
            raise WalletCaseActivitySnapshotConflict(
                "The pinned snapshot failed its Wallet Case source-scope contract."
            )
        built = _build_activity(wallet_case, snapshot, sources)
        filtered = tuple(item for item in built.items if _matches(item, query))
        ordered = _ordered(filtered, query.sort)
        page_items, next_cursor = _page(
            wallet_case.public_id,
            snapshot.public_id,
            ordered,
            query,
        )
        observed_period = _observed_period(filtered)
        gaps = _gaps(snapshot, built, query, start_at, end_at)
        limitations = _limitations(snapshot, built, query)
        aggregate = _aggregate(filtered, built, query, snapshot.data_mode)
        return {
            "case_public_id": wallet_case.public_id,
            "snapshot": _snapshot_record(snapshot),
            "filters": _filter_record(query),
            "aggregate": aggregate,
            "observed_period": observed_period,
            "gaps": gaps,
            "limitations": limitations,
            "items": list(page_items),
            "page": {
                "limit": query.limit,
                "has_more": next_cursor is not None,
                "next_cursor": next_cursor,
            },
        }

    def get_activity(
        self,
        case_public_id: str,
        activity_public_id: str,
        *,
        snapshot_public_id: str,
    ) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        snapshot = self.repository.get_snapshot(
            case_id=wallet_case.id,
            public_id=snapshot_public_id,
        )
        if snapshot is None:
            raise WalletCaseActivitySnapshotNotFound(
                "The requested Wallet Case snapshot is unavailable."
            )
        query = normalize_activity_query(
            WalletCaseActivityQuery(snapshot_public_id=snapshot.public_id)
        )
        start_at, end_at = _effective_period(snapshot, query)
        row_start_at, row_end_at = _row_period(snapshot, query, start_at, end_at)
        syncs = self.repository.source_syncs(
            snapshot=snapshot,
            start_at=start_at,
            end_at=end_at,
            maximum=MAX_SOURCE_SYNCS,
        )
        if syncs is None:
            raise WalletCaseActivityScopeTooLarge(
                "The pinned activity revision includes too many synchronization sources."
            )
        sources = self.repository.load_sources(
            syncs=syncs,
            start_at=row_start_at,
            end_at=row_end_at,
            maximum_rows=MAX_SOURCE_ROWS,
        )
        if sources is None:
            raise WalletCaseActivityScopeTooLarge(
                "The pinned activity revision contains too many normalized rows."
            )
        snapshot_run = sources.runs.get(snapshot.ingestion_run_id)
        if snapshot_run is None or not _run_matches_case(
            snapshot_run,
            snapshot,
            wallet_case,
            "mock" if wallet_case.data_environment == "demo" else "real",
        ):
            raise WalletCaseActivitySnapshotConflict(
                "The pinned snapshot failed its Wallet Case source-scope contract."
            )
        built = _build_activity(wallet_case, snapshot, sources)
        item = next(
            (value for value in built.items if value["public_id"] == activity_public_id),
            None,
        )
        if item is None:
            raise WalletCaseActivityItemNotFound(
                "Activity is not available in the requested snapshot."
            )
        all_sources = built.sources_by_public_id.get(activity_public_id, ())
        return {
            "case_public_id": wallet_case.public_id,
            "snapshot_public_id": snapshot.public_id,
            "item": item,
            "source_observations": list(all_sources[:MAX_DETAIL_SOURCES]),
            "sources_truncated": len(all_sources) > MAX_DETAIL_SOURCES,
        }

    def resolve_activity_dataset(
        self,
        case_public_id: str,
        *,
        snapshot_public_id: str | None,
    ) -> ResolvedCaseActivityDataset:
        """Materialize one unfiltered Activity revision exactly once.

        This is an internal case-read-model boundary, not a public pagination
        escape hatch.  The same source-sync and row-count caps used by the
        Activity endpoint are enforced before any derived facade can inspect
        the records.
        """
        query = normalize_activity_query(
            WalletCaseActivityQuery(snapshot_public_id=snapshot_public_id)
        )
        wallet_case = self._required_case(case_public_id)
        snapshot = self.repository.get_snapshot(
            case_id=wallet_case.id,
            public_id=query.snapshot_public_id,
        )
        if snapshot is None:
            if query.snapshot_public_id is not None:
                raise WalletCaseActivitySnapshotNotFound(
                    "The requested Wallet Case snapshot is unavailable."
                )
            empty = _empty_response(wallet_case.public_id, query)
            return ResolvedCaseActivityDataset(
                wallet_case=wallet_case,
                snapshot=None,
                snapshot_record=None,
                aggregate=empty["aggregate"],
                observed_period=None,
                gaps=tuple(empty["gaps"]),
                limitations=tuple(empty["limitations"]),
                items=(),
            )

        start_at, end_at = _effective_period(snapshot, query)
        row_start_at, row_end_at = _row_period(snapshot, query, start_at, end_at)
        source_syncs = self.repository.source_syncs(
            snapshot=snapshot,
            start_at=start_at,
            end_at=end_at,
            maximum=MAX_SOURCE_SYNCS,
        )
        if source_syncs is None:
            raise WalletCaseActivityScopeTooLarge(
                "The pinned activity revision includes too many synchronization sources."
            )
        sources = self.repository.load_sources(
            syncs=source_syncs,
            start_at=row_start_at,
            end_at=row_end_at,
            maximum_rows=MAX_SOURCE_ROWS,
        )
        if sources is None:
            raise WalletCaseActivityScopeTooLarge(
                "The pinned activity revision contains too many normalized rows."
            )
        snapshot_run = sources.runs.get(snapshot.ingestion_run_id)
        expected_mode = "mock" if wallet_case.data_environment == "demo" else "real"
        if snapshot_run is None or not _run_matches_case(
            snapshot_run,
            snapshot,
            wallet_case,
            expected_mode,
        ):
            raise WalletCaseActivitySnapshotConflict(
                "The pinned snapshot failed its Wallet Case source-scope contract."
            )
        built = _build_activity(wallet_case, snapshot, sources)
        items = tuple(built.items)
        return ResolvedCaseActivityDataset(
            wallet_case=wallet_case,
            snapshot=snapshot,
            snapshot_record=_snapshot_record(snapshot),
            aggregate=_aggregate(items, built, query, snapshot.data_mode),
            observed_period=_observed_period(items),
            gaps=tuple(_gaps(snapshot, built, query, start_at, end_at)),
            limitations=tuple(_limitations(snapshot, built, query)),
            items=items,
        )

    def resolve_verifiable_transaction(
        self,
        case_public_id: str,
        activity_public_id: str,
        *,
        snapshot_public_id: str,
    ) -> ResolvedCaseActivityTransaction:
        """Resolve the exact latest source row behind one pinned public item.

        This internal bridge deliberately returns database identities only to
        the evidence application service. Public Activity responses remain
        free of compatibility run and sequential row identifiers.
        """
        revision = self.resolve_verifiable_transaction_revision(
            case_public_id,
            snapshot_public_id=snapshot_public_id,
        )
        if activity_public_id not in revision.activity_public_ids:
            raise WalletCaseActivityItemNotFound(
                "Activity is not available in the requested snapshot."
            )
        resolved = revision.verifiable_transactions.get(activity_public_id)
        if resolved is None:
            raise WalletCaseActivityInvalidQuery(
                "Only a live provider-observed transaction with a revalidated "
                "network-scoped identity can be verified."
            )
        return resolved

    def resolve_verifiable_transaction_revision(
        self,
        case_public_id: str,
        *,
        snapshot_public_id: str,
    ) -> ResolvedCaseActivityRevision:
        """Build one canonical revision and index every eligible transaction."""
        wallet_case = self._required_case(case_public_id)
        snapshot = self.repository.get_snapshot(
            case_id=wallet_case.id,
            public_id=snapshot_public_id,
        )
        if snapshot is None:
            raise WalletCaseActivitySnapshotNotFound(
                "The requested Wallet Case snapshot is unavailable."
            )
        query = normalize_activity_query(
            WalletCaseActivityQuery(snapshot_public_id=snapshot.public_id)
        )
        start_at, end_at = _effective_period(snapshot, query)
        row_start_at, row_end_at = _row_period(snapshot, query, start_at, end_at)
        syncs = self.repository.source_syncs(
            snapshot=snapshot,
            start_at=start_at,
            end_at=end_at,
            maximum=MAX_SOURCE_SYNCS,
        )
        if syncs is None:
            raise WalletCaseActivityScopeTooLarge(
                "The pinned activity revision includes too many synchronization sources."
            )
        sources = self.repository.load_sources(
            syncs=syncs,
            start_at=row_start_at,
            end_at=row_end_at,
            maximum_rows=MAX_SOURCE_ROWS,
        )
        if sources is None:
            raise WalletCaseActivityScopeTooLarge(
                "The pinned activity revision contains too many normalized rows."
            )
        snapshot_run = sources.runs.get(snapshot.ingestion_run_id)
        expected_mode = "mock" if wallet_case.data_environment == "demo" else "real"
        if snapshot_run is None or not _run_matches_case(
            snapshot_run, snapshot, wallet_case, expected_mode
        ):
            raise WalletCaseActivitySnapshotConflict(
                "The pinned snapshot failed its Wallet Case source-scope contract."
            )
        built = _build_activity(wallet_case, snapshot, sources)
        sync_by_id = {value.id: value for value in syncs}
        transaction_by_id = {value.id: value for value in sources.transactions}
        resolved: dict[str, ResolvedCaseActivityTransaction] = {}
        for item in built.items:
            activity_public_id = item["public_id"]
            observations = built.observations_by_public_id.get(activity_public_id, ())
            if not observations:
                continue
            winner = observations[-1]
            source_sync = sync_by_id.get(winner.sync_id)
            source_run = (
                sources.runs.get(source_sync.ingestion_run_id)
                if source_sync is not None
                else None
            )
            source_transaction = transaction_by_id.get(winner.row_id)
            if (
                item.get("kind") != "transaction"
                or item.get("transaction", {}).get("linkage") != "self"
                or item.get("provenance", {}).get("data_origin")
                != "provider_observed"
                or item.get("provenance", {}).get("identity_assurance")
                != "network_scoped"
                or source_sync is None
                or source_run is None
                or source_transaction is None
                or winner.kind != "transaction"
                or winner.identity_namespace != "transaction"
                or winner.identity_key is None
            ):
                continue
            resolved[activity_public_id] = ResolvedCaseActivityTransaction(
                wallet_case=wallet_case,
                snapshot=snapshot,
                source_sync=source_sync,
                source_run=source_run,
                source_transaction=source_transaction,
                activity_public_id=activity_public_id,
                semantic_fingerprint=winner.semantic_fingerprint,
                item=item,
            )
        return ResolvedCaseActivityRevision(
            wallet_case=wallet_case,
            snapshot=snapshot,
            activity_public_ids=frozenset(
                item["public_id"] for item in built.items
            ),
            verifiable_transactions=resolved,
        )

    def _required_case(self, public_id: str) -> WalletCase:
        wallet_case = self.repository.get_case(
            owner_scope_id=self.owner_scope_id,
            public_id=public_id,
        )
        if wallet_case is None:
            raise WalletCaseActivityNotFound("Wallet Case not found.")
        return wallet_case


def normalize_activity_query(query: WalletCaseActivityQuery) -> WalletCaseActivityQuery:
    if isinstance(query.limit, bool) or not 1 <= query.limit <= 100:
        raise WalletCaseActivityInvalidQuery("limit must be from 1 through 100.")
    kinds = _canonical_choices(query.kinds, _KINDS, "kind")
    directions = _canonical_choices(query.directions, _DIRECTIONS, "direction")
    outcomes = _canonical_choices(query.outcomes, _OUTCOMES, "outcome")
    data_origins = _canonical_choices(
        query.data_origins,
        _DATA_ORIGINS,
        "data_origin",
    )
    if query.sort not in _SORTS:
        raise WalletCaseActivityInvalidQuery("sort must be newest or oldest.")
    if (query.from_at is None) != (query.to_at is None):
        raise WalletCaseActivityInvalidQuery(
            "from_at and to_at must be provided together."
        )
    from_at = _as_utc(query.from_at) if query.from_at is not None else None
    to_at = _as_utc(query.to_at) if query.to_at is not None else None
    if from_at is not None and to_at is not None and from_at >= to_at:
        raise WalletCaseActivityInvalidQuery("from_at must be before to_at.")
    if query.asset_id is not None and not _valid_prefixed_hash(
        query.asset_id, "asset_"
    ):
        raise WalletCaseActivityInvalidQuery("asset_id is not canonical.")
    if query.protocol_id is not None and query.protocol_id not in set(
        SUPPORTED_DEX_PROTOCOL_IDS
    ):
        raise WalletCaseActivityInvalidQuery("protocol_id is not recognized.")
    counterparty = None
    counterparty_network = None
    if query.counterparty is not None:
        identity = parse_ton_address(query.counterparty)
        if identity is None or identity.canonical_address is None:
            raise WalletCaseActivityInvalidQuery(
                "counterparty must be a canonicalizable TON address."
            )
        counterparty = identity.canonical_address
        if identity.network in {"ton-mainnet", "ton-testnet"}:
            counterparty_network = identity.network
    if query.cursor is not None and len(query.cursor) > 1024:
        raise WalletCaseActivityInvalidCursor("Activity cursor is too long.")
    return replace(
        query,
        kinds=kinds,
        directions=directions,
        outcomes=outcomes,
        data_origins=data_origins,
        from_at=from_at,
        to_at=to_at,
        counterparty=counterparty,
        counterparty_network=counterparty_network,
    )


def _canonical_choices(
    values: Iterable[str],
    allowed: tuple[str, ...],
    field: str,
) -> tuple[str, ...]:
    candidate = tuple(values)
    if len(candidate) > len(allowed) or len(set(candidate)) != len(candidate):
        raise WalletCaseActivityInvalidQuery(f"{field} values must be unique.")
    if any(value not in allowed for value in candidate):
        raise WalletCaseActivityInvalidQuery(f"{field} contains an unknown value.")
    return tuple(value for value in allowed if value in candidate)


def _effective_period(
    snapshot: CaseSync,
    query: WalletCaseActivityQuery,
) -> tuple[datetime | None, datetime | None]:
    if query.from_at is not None and query.to_at is not None:
        return query.from_at, query.to_at
    return _as_utc(snapshot.requested_start), _as_utc(snapshot.requested_end)


def _validate_query_period(
    snapshot: CaseSync,
    query: WalletCaseActivityQuery,
) -> None:
    if query.from_at is None or query.to_at is None:
        return
    requested_start = _as_utc(snapshot.requested_start)
    requested_end = _as_utc(snapshot.requested_end)
    if query.from_at < requested_start or query.to_at > requested_end:
        raise WalletCaseActivityInvalidQuery(
            "The activity period must stay within the pinned snapshot request."
        )


def _row_period(
    snapshot: CaseSync,
    query: WalletCaseActivityQuery,
    start_at: datetime,
    end_at: datetime,
) -> tuple[datetime | None, datetime | None]:
    # Demo timestamps describe the fixture scenario, not the time at which the
    # user pressed Sync. Source sync selection remains bounded by the pinned
    # requested period, while default demo rows remain visible and explicitly
    # carry fixture limitations. An explicit user period still filters them.
    if snapshot.data_mode == "mock" and query.from_at is None:
        return None, None
    return start_at, end_at


def _empty_response(case_public_id: str, query: WalletCaseActivityQuery) -> dict[str, Any]:
    limitation = {
        "code": "not_synchronized",
        "message": "Synchronize this Wallet Case before inspecting activity.",
    }
    return {
        "case_public_id": case_public_id,
        "snapshot": None,
        "filters": _filter_record(query),
        "aggregate": {
            "total_items": 0,
            "transactions": 0,
            "transfers": 0,
            "swaps": 0,
            "failed_transactions": 0,
            "source_sync_count": 0,
            "suppressed_duplicate_observations": 0,
            "conflicted_identity_count": 0,
        },
        "observed_period": None,
        "gaps": [
            {
                "code": "not_synchronized",
                "surface": None,
                "start_at": None,
                "end_at": None,
                "message": limitation["message"],
            }
        ],
        "limitations": [limitation],
        "items": [],
        "page": {"limit": query.limit, "has_more": False, "next_cursor": None},
    }


def _snapshot_record(snapshot: CaseSync) -> dict[str, Any]:
    return {
        "public_id": snapshot.public_id,
        "state": snapshot.state,
        "completed_at": _isoformat(snapshot.completed_at),
        "data_mode": snapshot.data_mode,
        "provider": snapshot.provider,
        "requested_period": {
            "start_at": _isoformat(snapshot.requested_start),
            "end_at": _isoformat(snapshot.requested_end),
        },
        "coverage": _stored_coverage(snapshot),
    }


def _filter_record(query: WalletCaseActivityQuery) -> dict[str, Any]:
    return {
        "kinds": list(query.kinds),
        "directions": list(query.directions),
        "outcomes": list(query.outcomes),
        "from_at": _isoformat(query.from_at),
        "to_at": _isoformat(query.to_at),
        "asset_id": query.asset_id,
        "protocol_id": query.protocol_id,
        "counterparty": query.counterparty,
        "data_origins": list(query.data_origins),
        "sort": query.sort,
    }


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _valid_prefixed_hash(value: str, prefix: str) -> bool:
    if not value.startswith(prefix) or len(value) != len(prefix) + 64:
        return False
    return all(char in "0123456789abcdef" for char in value[len(prefix) :])


def _build_activity(
    wallet_case: WalletCase,
    snapshot: CaseSync,
    sources: WalletCaseActivitySources,
) -> _BuiltActivity:
    expected_mode = "mock" if wallet_case.data_environment == "demo" else "real"
    sync_by_run = {
        sync.ingestion_run_id: sync
        for sync in sources.syncs
        if sync.ingestion_run_id is not None
    }
    surfaces_by_run = {
        run_id: frozenset(_json_list(sync.requested_surfaces_json))
        for run_id, sync in sync_by_run.items()
    }
    valid_runs: dict[int, WalletIngestionRun] = {}
    scope_mismatch_kinds: list[str] = []
    for run_id, sync in sync_by_run.items():
        run = sources.runs.get(run_id)
        if run is None or not _run_matches_case(run, sync, wallet_case, expected_mode):
            scope_mismatch_kinds.extend(
                _activity_kinds_for_surfaces(_json_list(sync.requested_surfaces_json))
            )
            continue
        valid_runs[run_id] = run

    observations: list[_Observation] = []
    invalid_provenance_kinds: list[str] = []

    for row in sources.transactions:
        sync = sync_by_run.get(row.run_id)
        run = valid_runs.get(row.run_id)
        if sync is None or run is None:
            continue
        if "transactions" not in surfaces_by_run.get(row.run_id, frozenset()):
            scope_mismatch_kinds.append("transaction")
            continue
        if not _row_matches_source_period(sync, run, row.timestamp):
            invalid_provenance_kinds.append("transaction")
            continue
        observation = _transaction_observation(wallet_case, sync, run, row)
        if observation is None:
            invalid_provenance_kinds.append("transaction")
            continue
        observations.append(observation)
    for row in sources.transfers:
        sync = sync_by_run.get(row.run_id)
        run = valid_runs.get(row.run_id)
        if sync is None or run is None:
            continue
        if "transfers" not in surfaces_by_run.get(row.run_id, frozenset()):
            scope_mismatch_kinds.append("transfer")
            continue
        if not _row_matches_source_period(sync, run, row.timestamp):
            invalid_provenance_kinds.append("transfer")
            continue
        observation = _transfer_observation(wallet_case, sync, run, row)
        if observation is None:
            invalid_provenance_kinds.append("transfer")
            continue
        observations.append(observation)
    for row in sources.swaps:
        sync = sync_by_run.get(row.run_id)
        run = valid_runs.get(row.run_id)
        if sync is None or run is None:
            continue
        if "swaps" not in surfaces_by_run.get(row.run_id, frozenset()):
            scope_mismatch_kinds.append("swap")
            continue
        if not _row_matches_source_period(sync, run, row.timestamp):
            invalid_provenance_kinds.append("swap")
            continue
        observation = _swap_observation(wallet_case, sync, run, row)
        if observation is None:
            invalid_provenance_kinds.append("swap")
            continue
        observations.append(observation)

    groups: dict[tuple[str, str], list[_Observation]] = {}
    distinct: list[list[_Observation]] = []
    for observation in observations:
        if observation.identity_namespace is None or observation.identity_key is None:
            distinct.append([observation])
            continue
        groups.setdefault(
            (observation.identity_namespace, observation.identity_key), []
        ).append(observation)

    conflicted_groups: list[tuple[dict[str, Any], ...]] = []
    for occurrences in groups.values():
        if len({item.semantic_fingerprint for item in occurrences}) != 1:
            conflicted_groups.append(
                tuple(
                    item.item
                    for item in sorted(
                        occurrences,
                        key=lambda value: (value.sync_id, value.row_id),
                    )
                )
            )
            continue
        distinct.append(occurrences)

    items: list[dict[str, Any]] = []
    sources_by_public_id: dict[str, tuple[dict[str, Any], ...]] = {}
    observations_by_public_id: dict[str, tuple[_Observation, ...]] = {}
    for occurrences in distinct:
        ordered = sorted(occurrences, key=lambda item: (item.sync_id, item.row_id))
        winner = ordered[-1]
        public_id = _activity_public_id(wallet_case.public_id, winner)
        item = dict(winner.item)
        provenance = dict(item["provenance"])
        provenance.update(
            {
                "observation_count": len(ordered),
                "suppressed_count": len(ordered) - 1,
                "first_seen_sync_public_id": ordered[0].sync_public_id,
                "last_seen_sync_public_id": ordered[-1].sync_public_id,
            }
        )
        item["public_id"] = public_id
        item["provenance"] = provenance
        items.append(item)
        sources_by_public_id[public_id] = tuple(
            {
                "sync_public_id": source.sync_public_id,
                "observed_at": source.observed_at,
                "provider": source.provider,
                "source_status": source.source_status,
                "data_origin": source.data_origin,
            }
            for source in ordered
        )
        observations_by_public_id[public_id] = tuple(ordered)

    return _BuiltActivity(
        items=tuple(items),
        sources_by_public_id=sources_by_public_id,
        observations_by_public_id=observations_by_public_id,
        valid_sync_kinds=tuple(
            frozenset(_activity_kinds_for_surfaces(surfaces_by_run[run_id]))
            for run_id in valid_runs
        ),
        scope_mismatch_kinds=tuple(scope_mismatch_kinds),
        invalid_provenance_kinds=tuple(invalid_provenance_kinds),
        conflicted_groups=tuple(conflicted_groups),
    )


def _run_matches_case(
    run: WalletIngestionRun,
    sync: CaseSync,
    wallet_case: WalletCase,
    expected_mode: str,
) -> bool:
    expected_status = {"succeeded": "success", "partial": "partial"}.get(
        sync.state
    )
    sync_surfaces = _json_list(sync.requested_surfaces_json)
    run_surfaces = _json_list(run.requested_surfaces_json)
    acquisition = _sync_acquisition_plan(sync)
    return (
        sync.case_id == wallet_case.id
        and sync.ingestion_run_id == run.id
        and sync.data_mode == expected_mode
        and run.data_mode == expected_mode
        and expected_status is not None
        and run.status == expected_status
        and sync.completed_at is not None
        and sync.time_window == run.time_window
        and sync_surfaces == run_surfaces
        and _run_provider(run) == sync.provider
        and run.wallet_identity_status == "network_scoped"
        and run.wallet_identity_version == wallet_case.canonical_identity_version
        and run.wallet_network == wallet_case.network
        and run.wallet_address_canonical == wallet_case.canonical_wallet_key
        and (
            sync.time_window != "custom"
            or (
                _same_datetime(
                    run.custom_start,
                    _parse_plan_instant(acquisition["start_at"]),
                )
                and _same_datetime(
                    run.custom_end,
                    _parse_plan_instant(acquisition["end_at"]),
                )
            )
        )
    )


def _run_provider(run: WalletIngestionRun) -> str:
    summary = _json_object(run.provider_summary_json)
    evidence = summary.get("provider_evidence")
    providers = sorted(
        {
            item.get("provider")
            for item in evidence
            if isinstance(evidence, list)
            and isinstance(item, dict)
            and isinstance(item.get("provider"), str)
            and item["provider"]
        }
    ) if isinstance(evidence, list) else []
    if len(providers) == 1:
        return providers[0][:64]
    if providers:
        return "multiple_wallet_activity_providers"
    return "unknown"


def _same_datetime(left: datetime | None, right: datetime | None) -> bool:
    return left is not None and right is not None and _as_utc(left) == _as_utc(right)


def _row_matches_source_period(
    sync: CaseSync,
    run: WalletIngestionRun,
    timestamp: datetime | None,
) -> bool:
    if run.data_mode == "mock" or timestamp is None:
        return True
    observed = _as_utc(timestamp)
    acquisition = _sync_acquisition_plan(sync)
    return (
        _parse_plan_instant(acquisition["start_at"])
        <= observed
        < _parse_plan_instant(acquisition["end_at"])
    )


def _parse_plan_instant(value: str) -> datetime:
    cleaned = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return _as_utc(datetime.fromisoformat(cleaned))


def _json_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _transaction_observation(
    wallet_case: WalletCase,
    sync: CaseSync,
    run: WalletIngestionRun,
    row: WalletTransaction,
) -> _Observation | None:
    raw = _json_object(row.raw_json)
    origin = _validated_origin(run, row.provider, row.source_status, raw, "transactions")
    if origin is None or not _normalized_row_coherent(run, row, raw):
        return None
    identity_key = _validated_transaction_key(wallet_case, run, row, raw)
    data_origin, evidence_level = origin
    transaction_hash = (
        row.transaction_hash_canonical if identity_key is not None else None
    )
    item = {
        "public_id": _placeholder_public_id(),
        "kind": "transaction",
        "occurred_at": _isoformat(row.timestamp),
        "logical_time": _public_logical_time(row.logical_time),
        "direction": None,
        "outcome": row.success if row.success in _OUTCOMES else "unknown",
        "counterparty": None,
        "assets": [],
        "protocol": None,
        "transaction": {
            "linkage": "self" if transaction_hash is not None else "unknown",
            "hash": transaction_hash,
            "event_id": None,
        },
        "details": {
            "kind": "transaction",
            "fee_ton": _public_decimal_text(row.fee_ton),
        },
        "provenance": _provenance(
            sync,
            row.provider,
            row.source_status,
            data_origin,
            evidence_level,
            "network_scoped" if identity_key is not None else "unavailable",
            "transaction_identity" if identity_key is not None else "none",
        ),
        "limitations": _item_limitations(
            data_origin,
            identity_key is None,
            provider_action=False,
            missing_timestamp=row.timestamp is None,
        ),
    }
    return _observation(
        sync,
        row.id,
        "transaction",
        "transaction" if identity_key is not None else None,
        identity_key,
        item,
        row.provider,
        row.source_status,
        data_origin,
    )


def _transfer_observation(
    wallet_case: WalletCase,
    sync: CaseSync,
    run: WalletIngestionRun,
    row: WalletTransfer,
) -> _Observation | None:
    raw = _json_object(row.raw_json)
    origin = _validated_origin(run, row.provider, row.source_status, raw, "transfers")
    if origin is None or not _normalized_row_coherent(run, row, raw):
        return None
    identity_key = _validated_event_key(
        wallet_case, run, row, raw, surface="transfers"
    )
    data_origin, evidence_level = origin
    asset = _asset(
        wallet_case,
        role="asset",
        symbol=row.asset,
        contract_address=raw.get("jetton_address"),
        native_allowed=(
            (run.data_mode == "mock" and row.asset == "TON")
            or raw.get("action_type") == "TonTransfer"
        ),
    )
    counterparty = _counterparty(wallet_case, row.counterparty)
    event_id = row.event_action_event_id_canonical if identity_key is not None else None
    item = {
        "public_id": _placeholder_public_id(),
        "kind": "transfer",
        "occurred_at": _isoformat(row.timestamp),
        "logical_time": _public_logical_time(row.logical_time),
        "direction": row.direction if row.direction in _DIRECTIONS else "unknown",
        "outcome": None,
        "counterparty": counterparty,
        "assets": [asset],
        "protocol": None,
        "transaction": {
            "linkage": "unknown",
            "hash": None,
            "event_id": event_id,
        },
        "details": {
            "kind": "transfer",
            "amount": _public_decimal_text(row.amount),
        },
        "provenance": _provenance(
            sync,
            row.provider,
            row.source_status,
            data_origin,
            evidence_level,
            "provider_scoped" if identity_key is not None else "unavailable",
            "event_action_identity" if identity_key is not None else "none",
        ),
        "limitations": _item_limitations(
            data_origin,
            identity_key is None,
            provider_action=True,
            missing_timestamp=row.timestamp is None,
        ),
    }
    return _observation(
        sync,
        row.id,
        "transfer",
        "event_action" if identity_key is not None else None,
        identity_key,
        item,
        row.provider,
        row.source_status,
        data_origin,
    )


def _swap_observation(
    wallet_case: WalletCase,
    sync: CaseSync,
    run: WalletIngestionRun,
    row: WalletSwap,
) -> _Observation | None:
    raw = _json_object(row.raw_json)
    origin = _validated_origin(run, row.provider, row.source_status, raw, "swaps")
    if origin is None or not _normalized_row_coherent(run, row, raw):
        return None
    identity_key = _validated_event_key(
        wallet_case, run, row, raw, surface="swaps"
    )
    data_origin, evidence_level = origin
    assets = [
        _asset(
            wallet_case,
            role="in",
            symbol=row.token_in,
            contract_address=raw.get("token_in_address"),
            native_allowed=(
                (run.data_mode == "mock" and row.token_in == "TON")
                or (
                    raw.get("action_type") == "JettonSwap"
                    and raw.get("token_in_standard") == "native"
                    and raw.get("token_in") == row.token_in == "TON"
                    and raw.get("token_in_address") is None
                    and _decimal_equal(raw.get("normalized_amount_in"), row.amount_in)
                )
            ),
        ),
        _asset(
            wallet_case,
            role="out",
            symbol=row.token_out,
            contract_address=raw.get("token_out_address"),
            native_allowed=(
                (run.data_mode == "mock" and row.token_out == "TON")
                or (
                    raw.get("action_type") == "JettonSwap"
                    and raw.get("token_out_standard") == "native"
                    and raw.get("token_out") == row.token_out == "TON"
                    and raw.get("token_out_address") is None
                    and _decimal_equal(raw.get("normalized_amount_out"), row.amount_out)
                )
            ),
        ),
    ]
    protocol_identity = classify_dex_protocol(row.dex)
    protocol = {
        "status": protocol_identity["status"],
        "id": protocol_identity["protocol_id"],
        "family": protocol_identity["family"],
        "version": protocol_identity["version"],
        "label": protocol_identity["provider_label"],
    }
    event_id = row.event_action_event_id_canonical if identity_key is not None else None
    item = {
        "public_id": _placeholder_public_id(),
        "kind": "swap",
        "occurred_at": _isoformat(row.timestamp),
        "logical_time": _public_logical_time(raw.get("lt")),
        "direction": None,
        "outcome": None,
        "counterparty": None,
        "assets": assets,
        "protocol": protocol,
        "transaction": {
            "linkage": "unknown",
            "hash": None,
            "event_id": event_id,
        },
        "details": {
            "kind": "swap",
            "amount_in": _public_decimal_text(row.amount_in),
            "amount_out": _public_decimal_text(row.amount_out),
            "estimated_usd": _public_decimal_text(row.estimated_usd),
        },
        "provenance": _provenance(
            sync,
            row.provider,
            row.source_status,
            data_origin,
            evidence_level,
            "provider_scoped" if identity_key is not None else "unavailable",
            "event_action_identity" if identity_key is not None else "none",
        ),
        "limitations": _item_limitations(
            data_origin,
            identity_key is None,
            provider_action=True,
            missing_timestamp=row.timestamp is None,
        ),
    }
    return _observation(
        sync,
        row.id,
        "swap",
        "event_action" if identity_key is not None else None,
        identity_key,
        item,
        row.provider,
        row.source_status,
        data_origin,
    )


def _validated_transaction_key(
    wallet_case: WalletCase,
    run: WalletIngestionRun,
    row: WalletTransaction,
    raw: dict[str, Any],
) -> str | None:
    derived = derive_ton_transaction_identity(
        network=run.wallet_network,
        account_address_canonical=run.wallet_address_canonical,
        account_identity_status=run.wallet_identity_status,
        account_identity_version=run.wallet_identity_version,
        account_workchain_id=run.wallet_workchain_id,
        account_id_hex=run.wallet_account_id_hex,
        logical_time=row.logical_time,
        transaction_hash=row.tx_hash,
        data_mode=run.data_mode,
        source_status=row.source_status,
        provider=row.provider,
        raw=raw,
    )
    if (
        derived.status != "network_scoped"
        or derived.key is None
        or derived.network != wallet_case.network
        or derived.account_canonical != wallet_case.canonical_wallet_key
        or row.transaction_identity_status != derived.status
        or row.transaction_identity_version != derived.version
        or row.transaction_network != derived.network
        or row.transaction_account_canonical != derived.account_canonical
        or row.transaction_logical_time_canonical != derived.logical_time_canonical
        or row.transaction_hash_canonical != derived.hash_canonical
        or row.transaction_identity_key != derived.key
    ):
        return None
    return derived.key


def _validated_event_key(
    wallet_case: WalletCase,
    run: WalletIngestionRun,
    row: WalletTransfer | WalletSwap,
    raw: dict[str, Any],
    *,
    surface: str,
) -> str | None:
    logical_time = row.logical_time if isinstance(row, WalletTransfer) else raw.get("lt")
    derived = derive_ton_event_action_identity(
        network=run.wallet_network,
        account_address_canonical=run.wallet_address_canonical,
        account_identity_status=run.wallet_identity_status,
        account_identity_version=run.wallet_identity_version,
        account_workchain_id=run.wallet_workchain_id,
        account_id_hex=run.wallet_account_id_hex,
        event_id=row.tx_hash,
        logical_time=logical_time,
        action_index=raw.get("action_index"),
        action_type=raw.get("action_type"),
        surface=surface,
        data_mode=run.data_mode,
        source_status=row.source_status,
        provider=row.provider,
        raw=raw,
    )
    if (
        derived.status != "provider_scoped"
        or derived.key is None
        or derived.network != wallet_case.network
        or derived.account_canonical != wallet_case.canonical_wallet_key
        or row.event_action_identity_status != derived.status
        or row.event_action_identity_version != derived.version
        or row.event_action_network != derived.network
        or row.event_action_account_canonical != derived.account_canonical
        or row.event_action_event_id_canonical != derived.event_id_canonical
        or row.event_action_logical_time_canonical != derived.logical_time_canonical
        or row.event_action_index != derived.action_index
        or row.event_action_type != derived.action_type
        or row.event_action_identity_key != derived.key
    ):
        return None
    return derived.key


def _asset(
    wallet_case: WalletCase,
    *,
    role: str,
    symbol: Any,
    contract_address: Any,
    native_allowed: bool,
) -> dict[str, Any]:
    display_symbol = _bounded_text(symbol, 128)
    submitted_contract = _bounded_text(contract_address, 128)
    if submitted_contract is None and display_symbol == "TON" and native_allowed:
        seed = f"case_asset_v1|{wallet_case.network}|native|ton"
        return {
            "role": role,
            "asset_id": f"asset_{hashlib.sha256(seed.encode('utf-8')).hexdigest()}",
            "identity_status": "network_scoped",
            "network": wallet_case.network,
            "standard": "native",
            "contract_address": None,
            "symbol": "TON",
        }
    if submitted_contract is not None:
        identity = derive_ton_wallet_identity(
            submitted_contract,
            network_context=wallet_case.network,
        )
        if identity.status == "network_scoped" and identity.canonical_address:
            if identity.network != wallet_case.network:
                return {
                    "role": role,
                    "asset_id": None,
                    "identity_status": "unavailable",
                    "network": wallet_case.network,
                    "standard": "unknown",
                    "contract_address": None,
                    "symbol": display_symbol,
                }
            canonical = identity.canonical_address
            seed = f"case_asset_v1|{wallet_case.network}|jetton|{canonical}"
            return {
                "role": role,
                "asset_id": f"asset_{hashlib.sha256(seed.encode('utf-8')).hexdigest()}",
                "identity_status": "network_scoped",
                "network": wallet_case.network,
                "standard": "jetton",
                "contract_address": canonical,
                "symbol": display_symbol,
            }
    return {
        "role": role,
        "asset_id": None,
        "identity_status": "unavailable",
        "network": wallet_case.network,
        "standard": "unknown",
        "contract_address": None,
        "symbol": display_symbol,
    }


def _counterparty(wallet_case: WalletCase, value: Any) -> dict[str, Any] | None:
    display = _bounded_text(value, 128)
    if display is None:
        return None
    identity = derive_ton_wallet_identity(display, network_context=wallet_case.network)
    canonical = (
        identity.canonical_address
        if identity.status == "network_scoped"
        and identity.network == wallet_case.network
        else None
    )
    return {
        "display_address": display,
        "canonical_address": canonical,
        "identity_status": "network_scoped" if canonical else "unavailable",
    }


def _validated_origin(
    run: WalletIngestionRun,
    provider: Any,
    source_status: Any,
    raw: dict[str, Any],
    surface: str,
) -> tuple[str, str] | None:
    if run.data_mode == "mock":
        if provider != "mock_wallet_activity" or source_status != "mock":
            return None
        if raw.get("surface") != surface:
            return None
        return "demo_fixture", "fixture"
    if (
        provider != "tonapi"
        or source_status != "live"
        or raw.get("provider") != "tonapi"
        or raw.get("source") != "tonapi"
        or raw.get("surface") != surface
    ):
        return None
    return "provider_observed", "normalized_provider_observation"


def _normalized_row_coherent(
    run: WalletIngestionRun,
    row: WalletTransaction | WalletTransfer | WalletSwap,
    raw: dict[str, Any],
) -> bool:
    if run.data_mode == "mock":
        return isinstance(raw.get("fixture"), str)
    if not _timestamp_matches_epoch(row.timestamp, raw.get("utime")):
        return False
    if isinstance(row, WalletTransaction):
        raw_hash = raw.get("tx_hash")
        return (
            row.tx_hash == (raw_hash if isinstance(raw_hash, str) else "")
            and row.logical_time == raw.get("logical_time")
            and _optional_nonnegative_decimal_equal(
                raw.get("normalized_fee_ton"), row.fee_ton
            )
        )
    if isinstance(row, WalletTransfer):
        if row.tx_hash != raw.get("event_id") or row.logical_time != raw.get("lt"):
            return False
        action_type = raw.get("action_type")
        if action_type == "TonTransfer":
            expected_asset = "TON"
            if raw.get("jetton_address") is not None:
                return False
        elif action_type == "JettonTransfer":
            expected_asset = (
                raw.get("jetton_symbol")
                or raw.get("jetton_address")
                or "UNKNOWN_JETTON"
            )
        else:
            return False
        return (
            row.asset == expected_asset
            and row.direction == raw.get("direction")
            and row.counterparty == raw.get("counterparty")
            and _optional_nonnegative_decimal_equal(
                raw.get("normalized_amount"), row.amount
            )
        )
    return (
        row.tx_hash == raw.get("event_id")
        and row.dex == raw.get("dex")
        and row.token_in == raw.get("token_in")
        and row.token_out == raw.get("token_out")
        and _optional_nonnegative_decimal_equal(
            raw.get("normalized_amount_in"), row.amount_in
        )
        and _optional_nonnegative_decimal_equal(
            raw.get("normalized_amount_out"), row.amount_out
        )
        # Guarded live TonAPI swaps intentionally carry no USD estimate; there
        # is no raw normalized valuation field that could validate one.
        and row.estimated_usd is None
    )


def _timestamp_matches_epoch(timestamp: datetime | None, epoch: Any) -> bool:
    if timestamp is None:
        return epoch is None
    if isinstance(epoch, bool) or not isinstance(epoch, int):
        return False
    return int(_as_utc(timestamp).timestamp()) == epoch


def _provenance(
    sync: CaseSync,
    provider: Any,
    source_status: Any,
    data_origin: str,
    evidence_level: str,
    assurance: str,
    basis: str,
) -> dict[str, Any]:
    return {
        "data_origin": data_origin,
        "evidence_level": evidence_level,
        "provider": _bounded_text(provider, 64) or "unknown",
        "source_status": _bounded_text(source_status, 32) or "unknown",
        "identity_assurance": assurance,
        "deduplication_basis": basis,
        "observation_count": 1,
        "suppressed_count": 0,
        "first_seen_sync_public_id": sync.public_id,
        "last_seen_sync_public_id": sync.public_id,
    }


def _item_limitations(
    data_origin: str,
    identity_unavailable: bool,
    *,
    provider_action: bool,
    missing_timestamp: bool,
) -> list[dict[str, str]]:
    values: list[dict[str, str]] = []
    if data_origin == "demo_fixture":
        values.append(
            {
                "code": "demo_fixture_not_chain_data",
                "message": "This row is a deterministic demo fixture, not chain evidence.",
            }
        )
    if provider_action:
        values.append(
            {
                "code": "provider_action_not_authoritative",
                "message": "This normalized provider action is not an authoritative transaction ledger row.",
            }
        )
    if identity_unavailable:
        values.append(
            {
                "code": "activity_identity_unavailable",
                "message": "This observation has no validated cross-sync identity and was not deduplicated.",
            }
        )
    if missing_timestamp:
        values.append(
            {
                "code": "activity_timestamp_unavailable",
                "message": "This observation has no timestamp; its exact period membership is unknown.",
            }
        )
    return values


def _observation(
    sync: CaseSync,
    row_id: int,
    kind: str,
    namespace: str | None,
    identity_key: str | None,
    item: dict[str, Any],
    provider: Any,
    source_status: Any,
    data_origin: str,
) -> _Observation:
    semantic = {
        key: value
        for key, value in item.items()
        if key not in {"public_id", "provenance", "limitations"}
    }
    fingerprint = hashlib.sha256(_canonical_json(semantic)).hexdigest()
    return _Observation(
        sync_id=sync.id,
        sync_public_id=sync.public_id,
        row_id=row_id,
        kind=kind,
        identity_namespace=namespace,
        identity_key=identity_key,
        semantic_fingerprint=fingerprint,
        item=item,
        observed_at=item["occurred_at"],
        provider=_bounded_text(provider, 64) or "unknown",
        source_status=_bounded_text(source_status, 32) or "unknown",
        data_origin=data_origin,
    )


def _activity_public_id(case_public_id: str, observation: _Observation) -> str:
    if observation.identity_namespace and observation.identity_key:
        identity = f"{observation.identity_namespace}|{observation.identity_key}"
    else:
        # Unknown identities intentionally remain source-row scoped. The
        # internal row id is one input to a one-way public identifier only.
        identity = (
            f"unavailable|{observation.sync_public_id}|"
            f"{observation.kind}|{observation.row_id}"
        )
    seed = f"case_activity_v1|{case_public_id}|{identity}"
    return f"act_{hashlib.sha256(seed.encode('utf-8')).hexdigest()}"


def _placeholder_public_id() -> str:
    return "act_" + ("0" * 64)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_object(value: str | None) -> dict[str, Any]:
    try:
        parsed = json.loads(value or "{}")
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _bounded_text(value: Any, maximum: int) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned[:maximum] if cleaned else None


def _public_logical_time(value: Any) -> str | None:
    if not isinstance(value, str) or _PUBLIC_LOGICAL_TIME_RE.fullmatch(value) is None:
        return None
    return value if int(value, 10) <= _MAX_PUBLIC_LOGICAL_TIME else None


def _public_decimal_text(value: Decimal | None) -> str | None:
    if value is None or not value.is_finite() or value < 0:
        return None
    return format(value, "f")


def _decimal_equal(raw: Any, stored: Decimal | None) -> bool:
    if stored is None or isinstance(raw, bool):
        return False
    try:
        parsed = Decimal(str(raw))
        if not parsed.is_finite() or not stored.is_finite():
            return False
        if parsed == stored:
            return True
        # SQLite persists SQLAlchemy Numeric(38, 18) through a binary float.
        # Reproduce that exact, scale-bounded storage conversion instead of
        # accepting a broad numeric tolerance. PostgreSQL's exact Decimal path
        # is covered by the equality check above.
        sqlite_value = Decimal.from_float(float(parsed)).quantize(
            Decimal("0.000000000000000001")
        )
        return sqlite_value == stored
    except (ValueError, ArithmeticError, OverflowError):
        return False


def _optional_nonnegative_decimal_equal(raw: Any, stored: Decimal | None) -> bool:
    if raw is None or raw == "":
        return stored is None
    if isinstance(raw, bool):
        return False
    try:
        parsed = Decimal(str(raw))
    except (ValueError, ArithmeticError):
        return False
    return parsed.is_finite() and parsed >= 0 and _decimal_equal(raw, stored)


def _matches(item: dict[str, Any], query: WalletCaseActivityQuery) -> bool:
    if query.kinds and item["kind"] not in query.kinds:
        return False
    if query.directions and item["direction"] not in query.directions:
        return False
    if query.outcomes and item["outcome"] not in query.outcomes:
        return False
    if query.from_at is not None and query.to_at is not None:
        occurred = _parse_public_timestamp(item["occurred_at"])
        if occurred is None or not (query.from_at <= occurred < query.to_at):
            return False
    if query.asset_id is not None and not any(
        asset["asset_id"] == query.asset_id for asset in item["assets"]
    ):
        return False
    if query.protocol_id is not None:
        protocol = item["protocol"]
        if protocol is None or protocol["id"] != query.protocol_id:
            return False
    if query.counterparty is not None:
        counterparty = item["counterparty"]
        if (
            counterparty is None
            or counterparty["canonical_address"] != query.counterparty
        ):
            return False
    if query.data_origins and (
        item["provenance"]["data_origin"] not in query.data_origins
    ):
        return False
    return True


def _ordered(
    items: tuple[dict[str, Any], ...],
    order: str,
) -> tuple[dict[str, Any], ...]:
    known = [item for item in items if item["occurred_at"] is not None]
    unknown = [item for item in items if item["occurred_at"] is None]
    reverse = order == "newest"
    known.sort(key=_known_sort_key, reverse=reverse)
    # Unknown timestamps are always last. Logical time and public id preserve a
    # deterministic order without pretending they establish wall-clock time.
    unknown.sort(key=_unknown_sort_key, reverse=reverse)
    return tuple(known + unknown)


def _known_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    logical_time = item["logical_time"] or ""
    occurred_at = _parse_public_timestamp(item["occurred_at"])
    assert occurred_at is not None
    return (
        occurred_at,
        len(logical_time),
        logical_time,
        item["public_id"],
    )


def _unknown_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    logical_time = item["logical_time"] or ""
    return len(logical_time), logical_time, item["public_id"]


def _page(
    case_public_id: str,
    snapshot_public_id: str,
    ordered: tuple[dict[str, Any], ...],
    query: WalletCaseActivityQuery,
) -> tuple[tuple[dict[str, Any], ...], str | None]:
    start = 0
    if query.cursor is not None:
        document = _decode_cursor(query.cursor)
        expected = {
            "case": case_public_id,
            "snapshot": snapshot_public_id,
            "filter_sha256": _filter_sha256(query),
            "sort": query.sort,
        }
        if any(document.get(key) != value for key, value in expected.items()):
            raise WalletCaseActivityInvalidCursor(
                "Activity cursor does not match this case, snapshot, or filter."
            )
        after = document.get("after")
        if not isinstance(after, dict):
            raise WalletCaseActivityInvalidCursor("Activity cursor position is invalid.")
        position = next(
            (
                index
                for index, item in enumerate(ordered)
                if _cursor_position(item) == after
            ),
            None,
        )
        if position is None:
            raise WalletCaseActivityInvalidCursor(
                "Activity cursor position is no longer present in this snapshot."
            )
        start = position + 1
    values = ordered[start : start + query.limit]
    has_more = start + len(values) < len(ordered)
    next_cursor = None
    if has_more and values:
        next_cursor = _encode_cursor(
            {
                "v": 1,
                "case": case_public_id,
                "snapshot": snapshot_public_id,
                "filter_sha256": _filter_sha256(query),
                "sort": query.sort,
                "after": _cursor_position(values[-1]),
            }
        )
    return values, next_cursor


def _cursor_position(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "occurred_at": item["occurred_at"],
        "logical_time": item["logical_time"],
        "public_id": item["public_id"],
    }


def _filter_sha256(query: WalletCaseActivityQuery) -> str:
    return hashlib.sha256(_canonical_json(_filter_record(query))).hexdigest()


def _encode_cursor(document: dict[str, Any]) -> str:
    payload = _canonical_json(document)
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(_CURSOR_KEY, payload, hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode_cursor(value: str) -> dict[str, Any]:
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise WalletCaseActivityInvalidCursor("Activity cursor is invalid.")
    if value.count(".") != 1:
        raise WalletCaseActivityInvalidCursor("Activity cursor is invalid.")
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
        raise WalletCaseActivityInvalidCursor("Activity cursor is invalid.")
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise WalletCaseActivityInvalidCursor("Activity cursor is invalid.") from exc
    if not isinstance(document, dict) or document.get("v") != 1:
        raise WalletCaseActivityInvalidCursor("Activity cursor version is invalid.")
    expected_signature = hmac.new(_CURSOR_KEY, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected_signature):
        raise WalletCaseActivityInvalidCursor("Activity cursor signature is invalid.")
    if _encode_cursor(document) != value:
        raise WalletCaseActivityInvalidCursor("Activity cursor is not canonical.")
    if set(document) != {
        "v",
        "case",
        "snapshot",
        "filter_sha256",
        "sort",
        "after",
    }:
        raise WalletCaseActivityInvalidCursor("Activity cursor shape is invalid.")
    if not isinstance(document.get("snapshot"), str):
        raise WalletCaseActivityInvalidCursor("Activity cursor snapshot is invalid.")
    return document


def _aggregate(
    items: tuple[dict[str, Any], ...],
    built: _BuiltActivity,
    query: WalletCaseActivityQuery,
    data_mode: str,
) -> dict[str, int]:
    counts = {
        kind: sum(item["kind"] == kind for item in items) for kind in _KINDS
    }
    return {
        "total_items": len(items),
        "transactions": counts["transaction"],
        "transfers": counts["transfer"],
        "swaps": counts["swap"],
        "failed_transactions": sum(
            item["kind"] == "transaction" and item["outcome"] == "failed"
            for item in items
        ),
        "source_sync_count": _matching_source_sync_count(
            built,
            query,
            data_mode,
        ),
        "suppressed_duplicate_observations": sum(
            item["provenance"]["suppressed_count"] for item in items
        ),
        "conflicted_identity_count": _matching_conflict_count(built, query),
    }


def _observed_period(
    items: tuple[dict[str, Any], ...],
) -> dict[str, str] | None:
    timestamps = sorted(
        parsed
        for item in items
        if (parsed := _parse_public_timestamp(item["occurred_at"])) is not None
    )
    if not timestamps:
        return None
    return {
        "start_at": _isoformat(timestamps[0]),
        "end_at": _isoformat(timestamps[-1] + timedelta(microseconds=1)),
    }


def _gaps(
    snapshot: CaseSync,
    built: _BuiltActivity,
    query: WalletCaseActivityQuery,
    start_at: datetime,
    end_at: datetime,
) -> list[dict[str, Any]]:
    coverage = _stored_coverage(snapshot)
    values: list[dict[str, Any]] = []
    if (
        snapshot.data_mode == "real"
        and coverage.get("state") == "unknown"
        and any(
            _surface_matches_query(surface, query, snapshot.data_mode)
            for surface in _json_list(snapshot.requested_surfaces_json)
        )
    ):
        values.append(
            _gap(
                "coverage_unavailable",
                "activity",
                start_at,
                end_at,
                "Stored coverage for the selected activity kinds was missing or inconsistent; the pinned snapshot basis is unknown.",
            )
        )
    for surface in coverage.get("unavailable_surfaces", []):
        if not _surface_matches_query(surface, query, snapshot.data_mode):
            continue
        values.append(
            _gap(
                "surface_unavailable",
                surface,
                start_at,
                end_at,
                "The requested surface was unavailable in the pinned snapshot.",
            )
        )
    for surface in coverage.get("incomplete_surfaces", []):
        if not _surface_matches_query(surface, query, snapshot.data_mode):
            continue
        values.append(
            _gap(
                "surface_incomplete",
                surface,
                start_at,
                end_at,
                "The requested surface is incomplete in the pinned snapshot.",
            )
        )
    invalid_identity_count = sum(
        item["provenance"]["identity_assurance"] == "unavailable"
        and _matches(item, query)
        for item in _diagnostic_items(built)
    )
    invalid_asset_count = sum(
        any(asset["identity_status"] == "unavailable" for asset in item["assets"])
        and _matches(item, replace(query, asset_id=None))
        for item in _diagnostic_items(built)
    )
    missing_timestamp_count = sum(
        item["occurred_at"] is None
        and _matches(item, replace(query, from_at=None, to_at=None))
        for item in _diagnostic_items(built)
    )
    scope_mismatch_count = sum(
        _diagnostic_kind_may_match(kind, query, snapshot.data_mode)
        for kind in built.scope_mismatch_kinds
    )
    invalid_provenance_count = sum(
        _diagnostic_kind_may_match(kind, query, snapshot.data_mode)
        for kind in built.invalid_provenance_kinds
    )
    diagnostics = (
        (
            _matching_conflict_count(built, query),
            "identity_semantic_conflict",
            "Conflicting observations with one validated identity were omitted fail-closed.",
        ),
        (
            invalid_identity_count,
            "activity_identity_unavailable",
            "Some observations have no validated cross-sync identity and remain distinct.",
        ),
        (
            invalid_asset_count,
            "asset_identity_unavailable",
            "Some displayed assets lack a canonical contract identity and cannot be merged or asset-filtered.",
        ),
        (
            missing_timestamp_count,
            "activity_timestamp_unavailable",
            "Some observations lack a timestamp; explicit period filters omit them.",
        ),
        (
            scope_mismatch_count,
            "source_scope_mismatch",
            "One or more linked source runs relevant to the selected activity kinds failed Wallet Case scope validation and were omitted.",
        ),
        (
            invalid_provenance_count,
            "source_provenance_mismatch",
            "One or more rows relevant to the selected activity filters failed provider/source or normalized semantic validation and were omitted.",
        ),
    )
    for count, code, message in diagnostics:
        if count:
            values.append(_gap(code, "activity", start_at, end_at, message))
    if snapshot.data_mode == "mock" and _query_accepts_origin(
        query, snapshot.data_mode
    ):
        values.append(
            _gap(
                "demo_fixture_period_not_chain_coverage",
                "activity",
                start_at,
                end_at,
                "Demo timestamps describe a fixture scenario and do not prove coverage of the requested interval.",
            )
        )
    return values


def _surface_matches_query(
    surface: Any,
    query: WalletCaseActivityQuery,
    data_mode: str,
) -> bool:
    kind = {
        "transactions": "transaction",
        "transfers": "transfer",
        "swaps": "swap",
    }.get(surface)
    return (
        _query_accepts_origin(query, data_mode)
        and kind is not None
        and kind in _possible_kinds(query)
    )


def _possible_kinds(query: WalletCaseActivityQuery) -> frozenset[str]:
    possible = set(query.kinds or _KINDS)
    if query.directions:
        possible.intersection_update({"transfer"})
    if query.outcomes:
        possible.intersection_update({"transaction"})
    if query.asset_id is not None:
        possible.intersection_update({"transfer", "swap"})
    if query.protocol_id is not None:
        possible.intersection_update({"swap"})
    if query.counterparty is not None:
        possible.intersection_update({"transfer"})
    return frozenset(possible)


def _matching_source_sync_count(
    built: _BuiltActivity,
    query: WalletCaseActivityQuery,
    data_mode: str,
) -> int:
    if not _query_accepts_origin(query, data_mode):
        return 0
    possible = _possible_kinds(query)
    return sum(bool(kinds & possible) for kinds in built.valid_sync_kinds)


def _query_accepts_origin(
    query: WalletCaseActivityQuery,
    data_mode: str,
) -> bool:
    expected_origin = "demo_fixture" if data_mode == "mock" else "provider_observed"
    return not query.data_origins or expected_origin in query.data_origins


def _activity_kinds_for_surfaces(surfaces: Iterable[str]) -> tuple[str, ...]:
    mapping = {
        "transactions": "transaction",
        "transfers": "transfer",
        "swaps": "swap",
    }
    return tuple(mapping[surface] for surface in surfaces if surface in mapping)


def _diagnostic_kind_may_match(
    kind: str,
    query: WalletCaseActivityQuery,
    data_mode: str,
) -> bool:
    if kind not in _possible_kinds(query):
        return False
    expected_origin = "demo_fixture" if data_mode == "mock" else "provider_observed"
    if query.data_origins and expected_origin not in query.data_origins:
        return False
    # A row omitted because its provenance or normalized semantics are corrupt
    # cannot be safely compared against value/time filters. Keep the gap when
    # its kind could match instead of trusting the corrupt value to hide it.
    return True


def _matching_conflict_count(
    built: _BuiltActivity,
    query: WalletCaseActivityQuery,
) -> int:
    return sum(
        any(_matches(item, query) for item in group)
        for group in built.conflicted_groups
    )


def _diagnostic_items(built: _BuiltActivity) -> tuple[dict[str, Any], ...]:
    return built.items + tuple(
        item for group in built.conflicted_groups for item in group
    )


def _gap(
    code: str,
    surface: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    message: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "surface": surface,
        "start_at": _isoformat(start_at),
        "end_at": _isoformat(end_at),
        "message": message,
    }


def _limitations(
    snapshot: CaseSync,
    built: _BuiltActivity,
    query: WalletCaseActivityQuery,
) -> list[dict[str, str]]:
    invalid_identity = any(
        item["provenance"]["identity_assurance"] == "unavailable"
        and _matches(item, query)
        for item in _diagnostic_items(built)
    )
    invalid_asset = any(
        any(asset["identity_status"] == "unavailable" for asset in item["assets"])
        and _matches(item, replace(query, asset_id=None))
        for item in _diagnostic_items(built)
    )
    missing_timestamp = any(
        item["occurred_at"] is None
        and _matches(item, replace(query, from_at=None, to_at=None))
        for item in _diagnostic_items(built)
    )
    scope_mismatch = any(
        _diagnostic_kind_may_match(kind, query, snapshot.data_mode)
        for kind in built.scope_mismatch_kinds
    )
    invalid_provenance = any(
        _diagnostic_kind_may_match(kind, query, snapshot.data_mode)
        for kind in built.invalid_provenance_kinds
    )
    values = [
        {
            "code": "bounded_interval_not_full_history",
            "message": "Activity is bounded and does not prove complete wallet history.",
        },
        {
            "code": "case_summary_is_latest_run_basis",
            "message": "The case Summary remains based on the latest run; this Activity aggregate is deduplicated across overlapping usable syncs.",
        },
        {
            "code": "proof_ledger_not_in_activity",
            "message": "This timeline does not incorporate native proof-ledger rows or claim block inclusion.",
        },
        {
            "code": "cursor_local_process_scope",
            "message": "Pagination cursors are authenticated for this local API process and must be restarted after an API restart.",
        },
        {
            "code": "coverage_is_pinned_snapshot_basis",
            "message": "Published coverage belongs to the pinned snapshot run; coverage from older overlapping observations is not merged.",
        },
    ]
    if snapshot.data_mode == "mock":
        values.append(
            {
                "code": "demo_fixture_not_chain_data",
                "message": "Demo activity is deterministic fixture data, not provider or chain evidence.",
            }
        )
    elif _stored_coverage(snapshot).get("state") == "unknown" and any(
        _surface_matches_query(surface, query, snapshot.data_mode)
        for surface in _json_list(snapshot.requested_surfaces_json)
    ):
        values.append(
            {
                "code": "coverage_unavailable",
                "message": "Stored coverage for the selected activity kinds is missing or inconsistent; the published pinned-snapshot coverage is unknown.",
            }
        )
    if "transaction" in _possible_kinds(query) and any(
        item["kind"] == "transaction" for item in _diagnostic_items(built)
    ):
        values.append(
            {
                "code": "transaction_outcome_not_raw_revalidated",
                "message": "Stored transaction outcome is normalized provider metadata; legacy source rows do not carry a second normalized outcome field for comparison.",
            }
        )
    if _matching_conflict_count(built, query):
        values.append(
            {
                "code": "identity_semantic_conflict",
                "message": "Conflicting observations sharing one validated identity were omitted.",
            }
        )
    if invalid_identity:
        values.append(
            {
                "code": "activity_identity_unavailable",
                "message": "Identity-unavailable observations are never deduplicated across syncs.",
            }
        )
    if invalid_asset:
        values.append(
            {
                "code": "asset_identity_unavailable",
                "message": "Asset symbols without canonical contract addresses remain display-only metadata.",
            }
        )
    if scope_mismatch:
        values.append(
            {
                "code": "source_scope_mismatch",
                "message": "Invalid linked source scope was omitted without publishing its rows.",
            }
        )
    if invalid_provenance:
        values.append(
            {
                "code": "source_provenance_mismatch",
                "message": "Rows with inconsistent provider/source provenance were omitted fail-closed.",
            }
        )
    if query.from_at is not None and missing_timestamp:
        values.append(
            {
                "code": "unknown_time_rows_excluded",
                "message": "Rows without timestamps were excluded from the explicit period filter.",
            }
        )
    return values


def _parse_public_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    try:
        return _as_utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None
