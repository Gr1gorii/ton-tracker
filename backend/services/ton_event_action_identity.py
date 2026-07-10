"""Strict provider-scoped identity for TonAPI event-action observations."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from services.ton_address_identity import parse_ton_address

TonEventActionIdentityStatus = Literal["provider_scoped", "unavailable"]
TonEventActionNetwork = Literal[
    "ton-mainnet",
    "ton-testnet",
    "ton-unknown",
]

TON_EVENT_ACTION_IDENTITY_VERSION = "tonapi_event_action_obs_v1"
TON_EVENT_ACTION_IDENTITY_UNAVAILABLE = "unavailable"

_EVENT_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_LOGICAL_TIME_RE = re.compile(r"^[1-9][0-9]{0,19}$")
_MAX_LOGICAL_TIME = 2**64 - 1
_MAX_ACTION_INDEX = 2**31 - 1
_ACTION_TYPES_BY_SURFACE = {
    "transfers": frozenset(("TonTransfer", "JettonTransfer")),
    "swaps": frozenset(("JettonSwap",)),
}


@dataclass(frozen=True)
class TonEventActionIdentity:
    status: TonEventActionIdentityStatus
    version: str
    provider: str | None
    network: TonEventActionNetwork
    account_canonical: str | None
    event_id_canonical: str | None
    logical_time_canonical: str | None
    action_index: int | None
    action_type: str | None
    key: str | None
    is_provider_observation_identity: bool
    is_blockchain_proof_verified: bool = False
    is_authoritative_activity_identity: bool = False
    is_ownership_proof: bool = False
    eligible_for_cost_basis: bool = False
    deduplication_applied: bool = False
    used_by_pnl: bool = False

    @property
    def scoped_key(self) -> tuple[str, str, str, str, int] | None:
        if self.status != "provider_scoped" or self.provider != "tonapi":
            return None
        if (
            self.account_canonical is None
            or self.event_id_canonical is None
            or self.logical_time_canonical is None
            or self.action_index is None
        ):
            return None
        return (
            self.network,
            self.account_canonical,
            self.event_id_canonical,
            self.logical_time_canonical,
            self.action_index,
        )

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_account_address(
    value: Any,
    *,
    identity_status: Any,
    identity_version: Any,
    workchain_id: Any,
    account_id_hex: Any,
) -> str | None:
    if identity_status != "network_scoped":
        return None
    if identity_version not in ("ton_std_address_v1", "ton_raw_address_v1"):
        return None
    if type(workchain_id) is not int:
        return None
    identity = parse_ton_address(value)
    if identity is None or identity.submitted_format != "raw":
        return None
    if identity.canonical_address != value:
        return None
    if identity.workchain_id != workchain_id:
        return None
    if identity.account_id_hex != account_id_hex:
        return None
    return identity.canonical_address


def _canonical_event_id(value: Any) -> str | None:
    if not isinstance(value, str) or _EVENT_ID_RE.fullmatch(value) is None:
        return None
    return value.lower()


def _canonical_logical_time(value: Any) -> str | None:
    if not isinstance(value, str) or _LOGICAL_TIME_RE.fullmatch(value) is None:
        return None
    parsed = int(value, 10)
    if parsed > _MAX_LOGICAL_TIME:
        return None
    return value


def _canonical_action_index(value: Any) -> int | None:
    if type(value) is not int or not 0 <= value <= _MAX_ACTION_INDEX:
        return None
    return value


def unavailable_ton_event_action_identity() -> TonEventActionIdentity:
    return TonEventActionIdentity(
        status="unavailable",
        version=TON_EVENT_ACTION_IDENTITY_UNAVAILABLE,
        provider=None,
        network="ton-unknown",
        account_canonical=None,
        event_id_canonical=None,
        logical_time_canonical=None,
        action_index=None,
        action_type=None,
        key=None,
        is_provider_observation_identity=False,
        is_blockchain_proof_verified=False,
        is_authoritative_activity_identity=False,
        is_ownership_proof=False,
        eligible_for_cost_basis=False,
        deduplication_applied=False,
        used_by_pnl=False,
    )


def derive_ton_event_action_identity(
    *,
    network: Any,
    account_address_canonical: Any,
    account_identity_status: Any,
    account_identity_version: Any,
    account_workchain_id: Any,
    account_id_hex: Any,
    event_id: Any,
    logical_time: Any,
    action_index: Any,
    action_type: Any,
    surface: Any,
    data_mode: Any,
    source_status: Any,
    provider: Any,
    raw: Any,
) -> TonEventActionIdentity:
    """Return a provider observation tuple or explicit unavailable state.

    The tuple identifies one TonAPI action observation. TonAPI event actions can
    change, so this never upgrades the action to authoritative chain logic.
    """
    if network not in ("ton-mainnet", "ton-testnet"):
        return unavailable_ton_event_action_identity()
    if data_mode != "real" or source_status != "live":
        return unavailable_ton_event_action_identity()
    if provider != "tonapi" or not isinstance(raw, dict):
        return unavailable_ton_event_action_identity()
    allowed_types = _ACTION_TYPES_BY_SURFACE.get(surface)
    if allowed_types is None or action_type not in allowed_types:
        return unavailable_ton_event_action_identity()
    if raw.get("provider") != "tonapi" or raw.get("surface") != surface:
        return unavailable_ton_event_action_identity()
    if raw.get("source") != "tonapi":
        return unavailable_ton_event_action_identity()
    if raw.get("event_id") != event_id or raw.get("lt") != logical_time:
        return unavailable_ton_event_action_identity()
    raw_action_index = raw.get("action_index")
    if (
        _canonical_action_index(raw_action_index) is None
        or raw_action_index != action_index
    ):
        return unavailable_ton_event_action_identity()
    if raw.get("action_type") != action_type:
        return unavailable_ton_event_action_identity()

    canonical_account = _canonical_account_address(
        account_address_canonical,
        identity_status=account_identity_status,
        identity_version=account_identity_version,
        workchain_id=account_workchain_id,
        account_id_hex=account_id_hex,
    )
    canonical_event_id = _canonical_event_id(event_id)
    canonical_lt = _canonical_logical_time(logical_time)
    canonical_index = _canonical_action_index(action_index)
    if (
        canonical_account is None
        or canonical_event_id is None
        or canonical_lt is None
        or canonical_index is None
    ):
        return unavailable_ton_event_action_identity()

    key = "|".join(
        (
            TON_EVENT_ACTION_IDENTITY_VERSION,
            "tonapi",
            network,
            canonical_account,
            canonical_event_id,
            canonical_lt,
            str(canonical_index),
        )
    )
    if len(key) > 256:
        return unavailable_ton_event_action_identity()
    return TonEventActionIdentity(
        status="provider_scoped",
        version=TON_EVENT_ACTION_IDENTITY_VERSION,
        provider="tonapi",
        network=network,
        account_canonical=canonical_account,
        event_id_canonical=canonical_event_id,
        logical_time_canonical=canonical_lt,
        action_index=canonical_index,
        action_type=action_type,
        key=key,
        is_provider_observation_identity=True,
        is_blockchain_proof_verified=False,
        is_authoritative_activity_identity=False,
        is_ownership_proof=False,
        eligible_for_cost_basis=False,
        deduplication_applied=False,
        used_by_pnl=False,
    )
