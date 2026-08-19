"""Replay-safe TON Connect ton_proof ownership verification."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
import hashlib
import secrets
import uuid
from typing import Any, Callable

from nacl.signing import VerifyKey
from pytoniq_core import Address, Cell, StateInit
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from config import get_settings
from models import WalletOwnershipChallenge
from services.ton_address_identity import derive_ton_wallet_identity
from services.ton_wallet_public_key import resolve_wallet_public_key_live


class WalletOwnershipProofConflict(ValueError):
    pass


class WalletOwnershipProofFailure(RuntimeError):
    pass


def create_ownership_challenge(
    session: Session, *, expected_wallet: str | None = None
) -> dict[str, Any]:
    settings = get_settings()
    expected_network = f"ton-{settings.ton_network}"
    canonical = None
    if expected_wallet is not None:
        identity = derive_ton_wallet_identity(
            expected_wallet,
            network_context=expected_network,
        )
        if identity.status == "unavailable" or identity.canonical_address is None:
            raise WalletOwnershipProofConflict("Expected wallet address is invalid.")
        canonical = identity.canonical_address
    now = datetime.now(timezone.utc)
    payload = secrets.token_urlsafe(48)
    row = WalletOwnershipChallenge(
        challenge_id=str(uuid.uuid4()),
        payload=payload,
        payload_hash=hashlib.sha256(payload.encode()).hexdigest(),
        expected_wallet_account_canonical=canonical,
        expected_domain=settings.tonconnect_expected_domain,
        expected_network=expected_network,
        issued_at=now,
        expires_at=now + timedelta(seconds=settings.tonconnect_proof_ttl_seconds),
    )
    session.add(row)
    session.commit()
    return {
        "challenge_id": row.challenge_id,
        "payload": payload,
        "expected_domain": row.expected_domain,
        "expected_network": row.expected_network,
        "expected_wallet_account_canonical": canonical,
        "issued_at": _iso(row.issued_at),
        "expires_at": _iso(row.expires_at),
        "single_use": True,
    }


def verify_ownership_proof(
    challenge_id: str,
    value: dict[str, Any],
    session: Session,
    *,
    public_key_resolver: Callable[..., bytes] = resolve_wallet_public_key_live,
) -> dict[str, Any]:
    row = session.scalar(select(WalletOwnershipChallenge).where(
        WalletOwnershipChallenge.challenge_id == challenge_id
    ))
    now = datetime.now(timezone.utc)
    if row is None or row.consumed_at is not None:
        raise WalletOwnershipProofConflict("Ownership challenge is absent or consumed.")
    expires = _utc(row.expires_at)
    if now > expires:
        raise WalletOwnershipProofConflict("Ownership challenge expired.")
    if row.expected_network not in {"ton-mainnet", "ton-testnet"}:
        raise WalletOwnershipProofConflict(
            "Ownership challenge predates strict network scoping."
        )
    if value["network"] != row.expected_network:
        raise WalletOwnershipProofConflict("Proof network does not match challenge scope.")
    address = Address(value["address"])
    canonical = address.to_str(is_user_friendly=False)
    if row.expected_wallet_account_canonical not in (None, canonical):
        raise WalletOwnershipProofConflict("Proof wallet does not match challenge scope.")
    proof = value["proof"]
    domain = proof["domain"]["value"].encode()
    if (
        proof["payload"] != row.payload
        or proof["domain"]["value"] != row.expected_domain
        or proof["domain"]["lengthBytes"] != len(domain)
        or proof["timestamp"] < int(_utc(row.issued_at).timestamp()) - 30
        or proof["timestamp"] > int(now.timestamp()) + 30
    ):
        raise WalletOwnershipProofConflict("Proof scope or timestamp is invalid.")
    state_root = _one_boc_base64(value["wallet_state_init"])
    state_slice = state_root.begin_parse()
    StateInit.deserialize(state_slice)
    if state_slice.remaining_bits or state_slice.remaining_refs or state_root.hash != address.hash_part:
        raise WalletOwnershipProofConflict("Wallet state init does not derive the proof address.")
    signature = _canonical_base64(proof["signature"], 64)
    snapshot = _challenge_snapshot(row)
    if snapshot["payload_hash"] != hashlib.sha256(
        snapshot["payload"].encode()
    ).hexdigest():
        raise WalletOwnershipProofConflict("Ownership challenge integrity changed.")
    settings = get_settings()
    # No ORM transaction/connection may remain checked out while the isolated
    # liteserver child is running. All durable scope is snapshotted and then
    # revalidated before the single-use compare-and-set below.
    session.rollback()
    try:
        public_key = public_key_resolver(
            network=snapshot["expected_network"],
            address=canonical,
            trust_level=settings.ton_liteclient_trust_level,
            timeout_seconds=settings.ton_liteclient_timeout_seconds,
            cache_directory=settings.ton_liteclient_cache_directory,
        )
    except Exception as exc:
        raise WalletOwnershipProofFailure(
            "Proof-checked wallet public key is temporarily unavailable."
        ) from exc
    try:
        VerifyKey(public_key).verify(_ton_proof_digest(address, proof), signature)
    except Exception as exc:
        raise WalletOwnershipProofConflict("Wallet ownership signature is invalid.") from exc
    verified_at = datetime.now(timezone.utc)
    current = session.get(WalletOwnershipChallenge, snapshot["id"])
    if (
        current is None
        or current.consumed_at is not None
        or _challenge_snapshot(current) != snapshot
        or verified_at > _utc(current.expires_at)
    ):
        session.rollback()
        raise WalletOwnershipProofConflict(
            "Ownership challenge changed, expired, or was consumed."
        )
    statement = (
        update(WalletOwnershipChallenge)
        .where(WalletOwnershipChallenge.id == snapshot["id"])
        .where(WalletOwnershipChallenge.consumed_at.is_(None))
        .where(WalletOwnershipChallenge.challenge_id == snapshot["challenge_id"])
        .where(WalletOwnershipChallenge.payload == snapshot["payload"])
        .where(WalletOwnershipChallenge.payload_hash == snapshot["payload_hash"])
        .where(
            WalletOwnershipChallenge.expected_domain
            == snapshot["expected_domain"]
        )
        .where(
            WalletOwnershipChallenge.expected_network
            == snapshot["expected_network"]
        )
        .where(
            WalletOwnershipChallenge.issued_at
            == snapshot["issued_at"].replace(tzinfo=None)
        )
        .where(
            WalletOwnershipChallenge.expires_at
            == snapshot["expires_at"].replace(tzinfo=None)
        )
    )
    expected_wallet = snapshot["expected_wallet_account_canonical"]
    statement = statement.where(
        WalletOwnershipChallenge.expected_wallet_account_canonical.is_(None)
        if expected_wallet is None
        else WalletOwnershipChallenge.expected_wallet_account_canonical
        == expected_wallet
    )
    result = session.execute(statement.values(
        consumed_at=verified_at,
        verified_wallet_account_canonical=canonical,
        signature_digest_sha256=hashlib.sha256(signature).hexdigest(),
    ))
    if result.rowcount != 1:
        session.rollback()
        raise WalletOwnershipProofConflict("Ownership challenge replay was rejected.")
    session.commit()
    return {
        "challenge_id": challenge_id, "wallet_account_canonical": canonical,
        "network": snapshot["expected_network"],
        "domain": snapshot["expected_domain"],
        "verified_at": _iso(verified_at), "signature_verified": True,
        "state_init_address_binding_verified": True,
        "public_key_resolved_from_proof_checked_account": True,
        "challenge_consumed": True, "is_ownership_proof": True,
    }


def _challenge_snapshot(row: WalletOwnershipChallenge) -> dict[str, Any]:
    return {
        "id": row.id,
        "challenge_id": row.challenge_id,
        "payload": row.payload,
        "payload_hash": row.payload_hash,
        "expected_wallet_account_canonical": (
            row.expected_wallet_account_canonical
        ),
        "expected_domain": row.expected_domain,
        "expected_network": row.expected_network,
        "issued_at": _utc(row.issued_at),
        "expires_at": _utc(row.expires_at),
    }


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ton_proof_digest(address: Address, proof: dict[str, Any]) -> bytes:
    domain = proof["domain"]["value"].encode()
    message = b"".join((
        b"ton-proof-item-v2/", address.wc.to_bytes(4, "big", signed=True),
        address.hash_part, len(domain).to_bytes(4, "little"), domain,
        proof["timestamp"].to_bytes(8, "little"), proof["payload"].encode(),
    ))
    return hashlib.sha256(b"\xff\xffton-connect" + hashlib.sha256(message).digest()).digest()


def _one_boc_base64(value: str) -> Cell:
    roots = Cell.from_boc(_canonical_base64(value, None))
    if len(roots) != 1:
        raise WalletOwnershipProofConflict("Wallet state init BOC is invalid.")
    return roots[0]


def _canonical_base64(value: str, length: int | None) -> bytes:
    try:
        raw = base64.b64decode(value, validate=True)
    except Exception as exc:
        raise WalletOwnershipProofConflict("Proof base64 is invalid.") from exc
    if (length is not None and len(raw) != length) or len(raw) > 262144:
        raise WalletOwnershipProofConflict("Proof binary length is invalid.")
    return raw


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
