"""Strict TON standard-address parsing and canonical wallet identity fields."""

from __future__ import annotations

import base64
import binascii
import hmac
import re
from dataclasses import asdict, dataclass
from typing import Any, Literal

TonNetwork = Literal["ton-mainnet", "ton-testnet", "ton-unknown"]
TonAddressFormat = Literal["user_friendly", "raw", "unrecognized"]
TonIdentityStatus = Literal["network_scoped", "unscoped", "unavailable"]

TON_IDENTITY_VERSION_STD = "ton_std_address_v1"
TON_IDENTITY_VERSION_RAW = "ton_raw_address_v1"
TON_IDENTITY_VERSION_UNAVAILABLE = "unavailable"

_RAW_ADDRESS_RE = re.compile(
    r"^((?:0|[1-9][0-9]*|-[1-9][0-9]*)):([0-9a-fA-F]{64})$"
)
_STANDARD_FRIENDLY_RE = re.compile(r"^[A-Za-z0-9+/]{48}$")
_URLSAFE_FRIENDLY_RE = re.compile(r"^[A-Za-z0-9_-]{48}$")
_MIN_WORKCHAIN = -(2**31)
_MAX_WORKCHAIN = 2**31 - 1


@dataclass(frozen=True)
class TonAddressIdentity:
    status: TonIdentityStatus
    version: str
    network: TonNetwork
    canonical_address: str | None
    workchain_id: int | None
    account_id_hex: str | None
    submitted_format: TonAddressFormat
    bounceable: bool | None
    testnet_only: bool | None

    @property
    def scoped_key(self) -> tuple[str, str] | None:
        if self.status != "network_scoped" or not self.canonical_address:
            return None
        return self.network, self.canonical_address

    def to_public_dict(self) -> dict[str, Any]:
        return asdict(self)


def _crc16_ccitt(data: bytes) -> int:
    """Return TON's CRC16-CCITT checksum (poly 0x1021, initial value 0)."""
    return binascii.crc_hqx(data, 0)


def _parse_raw(value: str) -> TonAddressIdentity | None:
    match = _RAW_ADDRESS_RE.fullmatch(value)
    if match is None:
        return None
    try:
        workchain_id = int(match.group(1), 10)
    except ValueError:
        return None
    if not _MIN_WORKCHAIN <= workchain_id <= _MAX_WORKCHAIN:
        return None
    account_id_hex = match.group(2).lower()
    return TonAddressIdentity(
        status="unscoped",
        version=TON_IDENTITY_VERSION_RAW,
        network="ton-unknown",
        canonical_address=f"{workchain_id}:{account_id_hex}",
        workchain_id=workchain_id,
        account_id_hex=account_id_hex,
        submitted_format="raw",
        bounceable=None,
        testnet_only=None,
    )


def _decode_user_friendly(value: str) -> bytes | None:
    if len(value) != 48:
        return None
    if _STANDARD_FRIENDLY_RE.fullmatch(value):
        altchars = None
    elif _URLSAFE_FRIENDLY_RE.fullmatch(value):
        altchars = b"-_"
    else:
        return None
    try:
        decoded = base64.b64decode(
            value.encode("ascii"),
            altchars=altchars,
            validate=True,
        )
    except (UnicodeEncodeError, binascii.Error, ValueError):
        return None
    return decoded if len(decoded) == 36 else None


def _parse_user_friendly(value: str) -> TonAddressIdentity | None:
    decoded = _decode_user_friendly(value)
    if decoded is None:
        return None
    payload, checksum = decoded[:34], decoded[34:]
    expected_checksum = _crc16_ccitt(payload).to_bytes(2, "big")
    if not hmac.compare_digest(checksum, expected_checksum):
        return None

    tag = payload[0]
    if tag & 0x3F != 0x11:
        return None
    testnet_only = bool(tag & 0x80)
    bounceable = not bool(tag & 0x40)
    workchain_id = int.from_bytes(payload[1:2], "big", signed=True)
    account_id_hex = payload[2:34].hex()
    network: TonNetwork = "ton-testnet" if testnet_only else "ton-mainnet"
    return TonAddressIdentity(
        status="network_scoped",
        version=TON_IDENTITY_VERSION_STD,
        network=network,
        canonical_address=f"{workchain_id}:{account_id_hex}",
        workchain_id=workchain_id,
        account_id_hex=account_id_hex,
        submitted_format="user_friendly",
        bounceable=bounceable,
        testnet_only=testnet_only,
    )


def parse_ton_address(value: Any) -> TonAddressIdentity | None:
    """Parse one strict standard TON address without guessing or correction."""
    if not isinstance(value, str):
        return None
    if value != value.strip() or not value:
        return None
    return _parse_raw(value) or _parse_user_friendly(value)


def unavailable_ton_identity() -> TonAddressIdentity:
    return TonAddressIdentity(
        status="unavailable",
        version=TON_IDENTITY_VERSION_UNAVAILABLE,
        network="ton-unknown",
        canonical_address=None,
        workchain_id=None,
        account_id_hex=None,
        submitted_format="unrecognized",
        bounceable=None,
        testnet_only=None,
    )


def derive_ton_wallet_identity(
    value: Any,
    *,
    network_context: Literal["ton-mainnet", "ton-testnet"] | None = None,
) -> TonAddressIdentity:
    """Return a parsed identity or an explicit unavailable record."""
    identity = parse_ton_address(value)
    if identity is None:
        return unavailable_ton_identity()
    if identity.status == "unscoped" and network_context is not None:
        return TonAddressIdentity(
            status="network_scoped",
            version=identity.version,
            network=network_context,
            canonical_address=identity.canonical_address,
            workchain_id=identity.workchain_id,
            account_id_hex=identity.account_id_hex,
            submitted_format=identity.submitted_format,
            bounceable=identity.bounceable,
            testnet_only=identity.testnet_only,
        )
    return identity
