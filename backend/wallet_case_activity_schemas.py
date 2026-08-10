"""Strict public contracts for the Wallet Case Activity read facade."""

from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from wallet_case_schemas import (
    CanonicalPublicId,
    WalletCaseCoverage,
    WalletCaseLimitation,
)


ActivityKind = Literal["transaction", "transfer", "swap"]
ActivityDirection = Literal["in", "out", "unknown"]
ActivityOutcome = Literal["success", "failed", "unknown"]
ActivityDataOrigin = Literal["demo_fixture", "provider_observed"]
ActivitySort = Literal["newest", "oldest"]
ActivityPublicId = Annotated[
    str,
    Field(pattern=r"^act_[0-9a-f]{64}$", min_length=68, max_length=68),
]
AssetPublicId = Annotated[
    str,
    Field(pattern=r"^asset_[0-9a-f]{64}$", min_length=70, max_length=70),
]
_RFC3339_RE = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T"
    r"[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})$"
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WalletCaseActivityPeriod(_StrictModel):
    start_at: str
    end_at: str

    @model_validator(mode="after")
    def _is_half_open(self):
        if _timestamp(self.start_at) >= _timestamp(self.end_at):
            raise ValueError("activity period must have start_at before end_at")
        return self


class WalletCaseActivitySnapshot(_StrictModel):
    public_id: CanonicalPublicId
    state: Literal["partial", "succeeded"]
    completed_at: str
    data_mode: Literal["mock", "real"]
    provider: str = Field(min_length=1, max_length=64)
    requested_period: WalletCaseActivityPeriod
    coverage: WalletCaseCoverage

    @model_validator(mode="after")
    def _coverage_matches_request(self):
        _timestamp(self.completed_at)
        if (
            self.coverage.requested_start_at != self.requested_period.start_at
            or self.coverage.requested_end_at != self.requested_period.end_at
        ):
            raise ValueError("snapshot coverage must match requested period")
        return self


class WalletCaseActivityFilters(_StrictModel):
    kinds: list[ActivityKind]
    directions: list[ActivityDirection]
    outcomes: list[ActivityOutcome]
    from_at: str | None = None
    to_at: str | None = None
    asset_id: AssetPublicId | None = None
    protocol_id: str | None = Field(default=None, min_length=1, max_length=32)
    counterparty: str | None = Field(default=None, min_length=66, max_length=76)
    data_origins: list[ActivityDataOrigin]
    sort: ActivitySort

    @model_validator(mode="after")
    def _period_is_paired(self):
        if (self.from_at is None) != (self.to_at is None):
            raise ValueError("from_at and to_at must be provided together")
        if self.from_at is not None and self.to_at is not None:
            if _timestamp(self.from_at) >= _timestamp(self.to_at):
                raise ValueError("from_at must be before to_at")
        for values in (
            self.kinds,
            self.directions,
            self.outcomes,
            self.data_origins,
        ):
            if len(values) != len(set(values)):
                raise ValueError("activity filter values must be distinct")
        return self


class WalletCaseActivityAggregate(_StrictModel):
    total_items: int = Field(ge=0)
    transactions: int = Field(ge=0)
    transfers: int = Field(ge=0)
    swaps: int = Field(ge=0)
    failed_transactions: int = Field(ge=0)
    source_sync_count: int = Field(ge=0)
    suppressed_duplicate_observations: int = Field(ge=0)
    conflicted_identity_count: int = Field(ge=0)


class WalletCaseActivityGap(_StrictModel):
    code: str = Field(min_length=1, max_length=64)
    surface: str | None = Field(default=None, max_length=32)
    start_at: str | None = None
    end_at: str | None = None
    message: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def _timestamps_are_rfc3339(self):
        if (self.start_at is None) != (self.end_at is None):
            raise ValueError("activity gap bounds must be provided together")
        if self.start_at is not None and self.end_at is not None:
            if _timestamp(self.start_at) >= _timestamp(self.end_at):
                raise ValueError("activity gap bounds must be half-open")
        return self


class WalletCaseActivityCounterparty(_StrictModel):
    display_address: str = Field(min_length=1, max_length=128)
    canonical_address: str | None = Field(default=None, min_length=66, max_length=76)
    identity_status: Literal["network_scoped", "unavailable"]

    @model_validator(mode="after")
    def _identity_is_coherent(self):
        if (self.identity_status == "network_scoped") != (
            self.canonical_address is not None
        ):
            raise ValueError("counterparty identity status is incoherent")
        return self


class WalletCaseActivityAsset(_StrictModel):
    role: Literal["asset", "in", "out"]
    asset_id: AssetPublicId | None = None
    identity_status: Literal["network_scoped", "unavailable"]
    network: Literal["ton-mainnet", "ton-testnet"]
    standard: Literal["native", "jetton", "unknown"]
    contract_address: str | None = Field(default=None, min_length=66, max_length=76)
    symbol: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _identity_is_coherent(self):
        if self.identity_status == "unavailable":
            if (
                self.asset_id is not None
                or self.standard != "unknown"
                or self.contract_address is not None
            ):
                raise ValueError("unavailable asset gained a canonical identity")
            return self
        if self.asset_id is None or self.standard not in {"native", "jetton"}:
            raise ValueError("network-scoped asset requires a stable identity")
        if self.standard == "native" and self.contract_address is not None:
            raise ValueError("native asset cannot have a contract address")
        if self.standard == "jetton" and self.contract_address is None:
            raise ValueError("jetton asset requires a canonical contract address")
        return self


class WalletCaseActivityProtocol(_StrictModel):
    status: Literal["recognized", "unknown", "missing"]
    id: str | None = Field(default=None, max_length=32)
    family: str | None = Field(default=None, max_length=32)
    version: str | None = Field(default=None, max_length=32)
    label: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _identity_is_coherent(self):
        if self.status == "recognized" and self.id is None:
            raise ValueError("recognized protocol requires an id")
        if self.status != "recognized" and self.id is not None:
            raise ValueError("unrecognized protocol cannot have an id")
        return self


class WalletCaseActivityTransactionReference(_StrictModel):
    linkage: Literal["self", "unknown"]
    hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$", max_length=64)
    event_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$", max_length=64)

    @model_validator(mode="after")
    def _linkage_is_coherent(self):
        if self.linkage == "self":
            if self.hash is None or self.event_id is not None:
                raise ValueError("self transaction linkage requires only a hash")
        elif self.hash is not None:
            raise ValueError("unknown transaction linkage cannot publish a hash")
        return self


class WalletCaseTransactionDetails(_StrictModel):
    kind: Literal["transaction"]
    fee_ton: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        max_length=80,
    )


class WalletCaseTransferDetails(_StrictModel):
    kind: Literal["transfer"]
    amount: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        max_length=80,
    )


class WalletCaseSwapDetails(_StrictModel):
    kind: Literal["swap"]
    amount_in: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        max_length=80,
    )
    amount_out: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        max_length=80,
    )
    estimated_usd: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$",
        max_length=80,
    )


WalletCaseActivityDetails = Annotated[
    WalletCaseTransactionDetails | WalletCaseTransferDetails | WalletCaseSwapDetails,
    Field(discriminator="kind"),
]


class WalletCaseActivityProvenance(_StrictModel):
    data_origin: ActivityDataOrigin
    evidence_level: Literal["fixture", "normalized_provider_observation"]
    provider: str = Field(min_length=1, max_length=64)
    source_status: str = Field(min_length=1, max_length=32)
    identity_assurance: Literal["network_scoped", "provider_scoped", "unavailable"]
    deduplication_basis: Literal[
        "transaction_identity",
        "event_action_identity",
        "none",
    ]
    observation_count: int = Field(ge=1)
    suppressed_count: int = Field(ge=0)
    first_seen_sync_public_id: CanonicalPublicId
    last_seen_sync_public_id: CanonicalPublicId

    @model_validator(mode="after")
    def _truth_tier_is_coherent(self):
        if self.suppressed_count != self.observation_count - 1:
            raise ValueError("suppressed count must match observation count")
        if self.data_origin == "demo_fixture":
            if (
                self.evidence_level != "fixture"
                or self.identity_assurance != "unavailable"
                or self.deduplication_basis != "none"
            ):
                raise ValueError("demo origin must remain fixture-only")
        elif self.evidence_level != "normalized_provider_observation":
            raise ValueError("provider origin requires normalized observation level")
        expected_basis = {
            "network_scoped": "transaction_identity",
            "provider_scoped": "event_action_identity",
            "unavailable": "none",
        }[self.identity_assurance]
        if self.deduplication_basis != expected_basis:
            raise ValueError("identity assurance and deduplication basis disagree")
        if self.identity_assurance == "unavailable" and self.observation_count != 1:
            raise ValueError("identity-unavailable rows cannot be deduplicated")
        return self


class WalletCaseActivityItem(_StrictModel):
    public_id: ActivityPublicId
    kind: ActivityKind
    occurred_at: str | None = None
    logical_time: str | None = Field(
        default=None,
        pattern=r"^(?:0|[1-9][0-9]{0,19})$",
        max_length=20,
    )
    direction: ActivityDirection | None = None
    outcome: ActivityOutcome | None = None
    counterparty: WalletCaseActivityCounterparty | None = None
    assets: list[WalletCaseActivityAsset]
    protocol: WalletCaseActivityProtocol | None = None
    transaction: WalletCaseActivityTransactionReference
    details: WalletCaseActivityDetails
    provenance: WalletCaseActivityProvenance
    limitations: list[WalletCaseLimitation]

    @model_validator(mode="after")
    def _detail_kind_matches_item(self):
        if self.occurred_at is not None:
            _timestamp(self.occurred_at)
        if self.logical_time is not None and int(self.logical_time, 10) > 2**64 - 1:
            raise ValueError("activity logical time exceeds uint64")
        if self.details.kind != self.kind:
            raise ValueError("activity details kind must match item kind")
        roles = [asset.role for asset in self.assets]
        if len(roles) != len(set(roles)):
            raise ValueError("activity asset roles must be unique")
        expected_roles = {
            "transaction": [],
            "transfer": ["asset"],
            "swap": ["in", "out"],
        }[self.kind]
        if roles != expected_roles:
            raise ValueError("activity asset roles do not match item kind")
        if self.kind == "transaction" and self.transaction.linkage not in {
            "self",
            "unknown",
        }:
            raise ValueError("transaction linkage is invalid")
        if self.kind != "transaction" and self.transaction.linkage != "unknown":
            raise ValueError("provider actions cannot claim transaction linkage")
        if self.kind == "transaction":
            if self.direction is not None or self.outcome is None or self.protocol is not None:
                raise ValueError("transaction activity fields are incoherent")
            if self.provenance.identity_assurance == "network_scoped":
                if self.transaction.linkage != "self":
                    raise ValueError("network-scoped transaction requires self linkage")
            elif (
                self.provenance.identity_assurance != "unavailable"
                or self.transaction.linkage != "unknown"
                or self.transaction.event_id is not None
            ):
                raise ValueError("transaction identity and linkage are incoherent")
        elif self.kind == "transfer":
            if self.direction is None or self.outcome is not None or self.protocol is not None:
                raise ValueError("transfer activity fields are incoherent")
            if (
                self.provenance.identity_assurance
                not in {"provider_scoped", "unavailable"}
                or (
                    self.provenance.identity_assurance == "provider_scoped"
                ) != (self.transaction.event_id is not None)
            ):
                raise ValueError("transfer identity and event reference are incoherent")
        elif self.direction is not None or self.outcome is not None or self.protocol is None:
            raise ValueError("swap activity fields are incoherent")
        elif (
            self.provenance.identity_assurance
            not in {"provider_scoped", "unavailable"}
            or (
                self.provenance.identity_assurance == "provider_scoped"
            ) != (self.transaction.event_id is not None)
        ):
            raise ValueError("swap identity and event reference are incoherent")
        return self


class WalletCaseActivityPage(_StrictModel):
    limit: int = Field(ge=1, le=100)
    has_more: bool
    next_cursor: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def _cursor_matches_more(self):
        if self.has_more != (self.next_cursor is not None):
            raise ValueError("has_more must match next_cursor")
        return self


class WalletCaseActivityListResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    snapshot: WalletCaseActivitySnapshot | None = None
    filters: WalletCaseActivityFilters
    aggregate: WalletCaseActivityAggregate
    observed_period: WalletCaseActivityPeriod | None = None
    gaps: list[WalletCaseActivityGap]
    limitations: list[WalletCaseLimitation]
    items: list[WalletCaseActivityItem]
    page: WalletCaseActivityPage

    @model_validator(mode="after")
    def _aggregate_and_origin_are_coherent(self):
        if self.aggregate.total_items != (
            self.aggregate.transactions
            + self.aggregate.transfers
            + self.aggregate.swaps
        ):
            raise ValueError("activity aggregate kind counts do not add up")
        if self.snapshot is None:
            if self.items or self.aggregate.total_items or self.observed_period is not None:
                raise ValueError("unsynchronized activity response must stay empty")
            if not any(item.code == "not_synchronized" for item in self.limitations):
                raise ValueError("unsynchronized response requires a limitation")
        else:
            expected_origin = (
                "demo_fixture" if self.snapshot.data_mode == "mock" else "provider_observed"
            )
            if any(
                item.provenance.data_origin != expected_origin for item in self.items
            ):
                raise ValueError("activity item origin does not match snapshot mode")
        return self


class WalletCaseActivitySourceObservation(_StrictModel):
    sync_public_id: CanonicalPublicId
    observed_at: str | None = None
    provider: str = Field(min_length=1, max_length=64)
    source_status: str = Field(min_length=1, max_length=32)
    data_origin: ActivityDataOrigin

    @model_validator(mode="after")
    def _observed_at_is_rfc3339(self):
        if self.observed_at is not None:
            _timestamp(self.observed_at)
        return self


class WalletCaseActivityDetailResponse(_StrictModel):
    case_public_id: CanonicalPublicId
    snapshot_public_id: CanonicalPublicId
    item: WalletCaseActivityItem
    source_observations: list[WalletCaseActivitySourceObservation]
    sources_truncated: bool

    @model_validator(mode="after")
    def _sources_match_item(self):
        if len(self.source_observations) > self.item.provenance.observation_count:
            raise ValueError("detail has more sources than observations")
        if not self.sources_truncated and (
            len(self.source_observations) != self.item.provenance.observation_count
        ):
            raise ValueError("untruncated detail must include every source")
        if any(
            source.data_origin != self.item.provenance.data_origin
            for source in self.source_observations
        ):
            raise ValueError("detail source origins disagree with the activity item")
        if any(
            source.provider != self.item.provenance.provider
            or source.source_status != self.item.provenance.source_status
            for source in self.source_observations
        ):
            raise ValueError("detail source provenance disagrees with the item")
        if self.source_observations and not self.sources_truncated:
            source_ids = {source.sync_public_id for source in self.source_observations}
            if (
                self.item.provenance.first_seen_sync_public_id not in source_ids
                or self.item.provenance.last_seen_sync_public_id not in source_ids
            ):
                raise ValueError("detail lost first/last source sync")
        return self


def _timestamp(value: str) -> datetime:
    if _RFC3339_RE.fullmatch(value) is None:
        raise ValueError("activity timestamps must be RFC3339")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("timezone is required")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ValueError("activity timestamps must be valid RFC3339") from exc
