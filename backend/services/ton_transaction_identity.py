"""Strict, versioned identity for low-level TON account transactions."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

from services.ton_address_identity import parse_ton_address

TonTransactionIdentityStatus = Literal["network_scoped", "unavailable"]
TonTransactionNetwork = Literal["ton-mainnet", "ton-testnet", "ton-unknown"]

TON_TRANSACTION_IDENTITY_VERSION = "ton_account_tx_v1"
TON_TRANSACTION_IDENTITY_UNAVAILABLE = "unavailable"

_TRANSACTION_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_LOGICAL_TIME_RE = re.compile(r"^(?:0|[1-9][0-9]*)$")
_MAX_LOGICAL_TIME = 2**64 - 1


@dataclass(frozen=True)
class TonTransactionIdentity:
    status: TonTransactionIdentityStatus
    version: str
    network: TonTransactionNetwork
    account_canonical: str | None
    logical_time_canonical: str | None
    hash_canonical: str | None
    key: str | None
    is_deduplication_identity: bool
    is_blockchain_proof_verified: bool = False
    is_ownership_proof: bool = False
    deduplication_applied: bool = False
    used_by_pnl: bool = False

    @property
    def scoped_key(self) -> tuple[str, str, str, str] | None:
        if self.status != "network_scoped":
            return None
        if not all(
            (
                self.account_canonical,
                self.logical_time_canonical,
                self.hash_canonical,
            )
        ):
            return None
        return (
            self.network,
            self.account_canonical,
            self.logical_time_canonical,
            self.hash_canonical,
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


def _canonical_logical_time(value: Any) -> str | None:
    if not isinstance(value, str) or _LOGICAL_TIME_RE.fullmatch(value) is None:
        return None
    parsed = int(value, 10)
    if parsed <= 0 or parsed > _MAX_LOGICAL_TIME:
        return None
    return value


def _canonical_transaction_hash(value: Any) -> str | None:
    if not isinstance(value, str) or _TRANSACTION_HASH_RE.fullmatch(value) is None:
        return None
    return value.lower()


def unavailable_ton_transaction_identity() -> TonTransactionIdentity:
    return TonTransactionIdentity(
        status="unavailable",
        version=TON_TRANSACTION_IDENTITY_UNAVAILABLE,
        network="ton-unknown",
        account_canonical=None,
        logical_time_canonical=None,
        hash_canonical=None,
        key=None,
        is_deduplication_identity=False,
        is_blockchain_proof_verified=False,
        is_ownership_proof=False,
        deduplication_applied=False,
        used_by_pnl=False,
    )


def derive_ton_transaction_identity(
    *,
    network: Any,
    account_address_canonical: Any,
    account_identity_status: Any,
    account_identity_version: Any,
    account_workchain_id: Any,
    account_id_hex: Any,
    logical_time: Any,
    transaction_hash: Any,
    data_mode: Any,
    source_status: Any,
    provider: Any,
    raw: Any,
) -> TonTransactionIdentity:
    """Return an exact provider-observed tuple or explicit unavailable state.

    Exact here describes the identity tuple, not cryptographic proof. Only
    source-labeled live rows in a known network scope are eligible.
    """
    if network not in ("ton-mainnet", "ton-testnet"):
        return unavailable_ton_transaction_identity()
    if data_mode != "real" or source_status != "live":
        return unavailable_ton_transaction_identity()
    if provider != "tonapi" or not isinstance(raw, dict):
        return unavailable_ton_transaction_identity()
    if raw.get("provider") != "tonapi" or raw.get("surface") != "transactions":
        return unavailable_ton_transaction_identity()
    if raw.get("tx_hash") != transaction_hash:
        return unavailable_ton_transaction_identity()
    if raw.get("logical_time") != logical_time:
        return unavailable_ton_transaction_identity()
    canonical_account = _canonical_account_address(
        account_address_canonical,
        identity_status=account_identity_status,
        identity_version=account_identity_version,
        workchain_id=account_workchain_id,
        account_id_hex=account_id_hex,
    )
    canonical_lt = _canonical_logical_time(logical_time)
    canonical_hash = _canonical_transaction_hash(transaction_hash)
    if canonical_account is None or canonical_lt is None or canonical_hash is None:
        return unavailable_ton_transaction_identity()
    key = "|".join(
        (
            TON_TRANSACTION_IDENTITY_VERSION,
            network,
            canonical_account,
            canonical_lt,
            canonical_hash,
        )
    )
    return TonTransactionIdentity(
        status="network_scoped",
        version=TON_TRANSACTION_IDENTITY_VERSION,
        network=network,
        account_canonical=canonical_account,
        logical_time_canonical=canonical_lt,
        hash_canonical=canonical_hash,
        key=key,
        is_deduplication_identity=True,
        is_blockchain_proof_verified=False,
        is_ownership_proof=False,
        deduplication_applied=False,
        used_by_pnl=False,
    )
