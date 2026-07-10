"""Immutable transaction BOC-to-block inclusion evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from config import get_settings
from models import WalletTransactionInclusionProof
from services.ton_transaction_inclusion_proof import (
    TonTransactionInclusionProofFailure,
    capture_transaction_inclusion_proofs_live,
    proof_boc_sha256,
    verify_transaction_inclusion_proof,
)
from services.wallet_persisted_trace_evidence import _find_capture_for_transaction
from services.wallet_trace_boc_verification import (
    WalletTraceBocVerificationConflict,
    _find_verification,
    get_wallet_transaction_trace_boc_verification,
)


TRANSACTION_INCLUSION_CONTRACT_VERSION = "ton_transaction_inclusion_v1"


class WalletTransactionInclusionProofNotFound(LookupError):
    """The selected persisted BOC verification was not found."""


class WalletTransactionInclusionProofConflict(ValueError):
    """Stored or live inclusion evidence is incoherent."""


class WalletTransactionInclusionProofFailure(RuntimeError):
    """Inclusion proof retrieval or immutable persistence failed."""


def create_wallet_transaction_inclusion_proofs(
    run_id: int,
    transaction_hash: str,
    session: Session,
    *,
    live_verifier: Callable[..., list[dict[str, Any]]] = (
        capture_transaction_inclusion_proofs_live
    ),
) -> dict[str, Any]:
    """Prove every transaction BOC in one finalized persisted trace."""
    if get_wallet_transaction_trace_boc_verification(
        run_id, transaction_hash, session
    ) is None:
        raise WalletTransactionInclusionProofNotFound(
            "Locally verified transaction BOC trace not found."
        )
    capture = _find_capture_for_transaction(run_id, transaction_hash, session)
    if capture is None:
        raise WalletTransactionInclusionProofNotFound(
            "Persisted trace capture not found."
        )
    verification = _find_verification(capture.id, session)
    if verification is None:
        raise WalletTransactionInclusionProofNotFound(
            "Persisted BOC verification not found."
        )
    transactions = sorted(
        verification.transactions,
        key=lambda row: row.preorder_index,
    )
    existing = [row.inclusion_proof for row in transactions]
    if all(row is not None for row in existing):
        return _catalog(verification, transactions)
    if any(row is not None for row in existing):
        raise WalletTransactionInclusionProofConflict(
            "Partial transaction inclusion proof storage is forbidden."
        )
    settings = get_settings()
    requests = [
        {
            "account_address": row.node.account_canonical,
            "logical_time": row.node.logical_time,
            "transaction_hash": row.transaction_hash,
        }
        for row in transactions
    ]
    try:
        captured = live_verifier(
            network=capture.network,
            requests=requests,
            trust_level=settings.ton_liteclient_trust_level,
            timeout_seconds=settings.ton_liteclient_timeout_seconds,
        )
    except TonTransactionInclusionProofFailure as exc:
        raise WalletTransactionInclusionProofFailure(str(exc)) from exc
    if not isinstance(captured, list) or len(captured) != len(transactions):
        raise WalletTransactionInclusionProofConflict(
            "Liteserver returned an incomplete inclusion proof set."
        )
    verified_at = datetime.now(timezone.utc)
    try:
        for request, boc_transaction, evidence in zip(
            requests, transactions, captured
        ):
            values = _proof_values(
                capture.network,
                settings.ton_liteclient_trust_level,
                request,
                boc_transaction,
                evidence,
                verified_at,
            )
            boc_transaction.inclusion_proof = WalletTransactionInclusionProof(
                **values
            )
        session.flush()
        result = _catalog(verification, transactions)
        session.commit()
        return result
    except WalletTransactionInclusionProofConflict:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        raise WalletTransactionInclusionProofFailure(
            "Transaction inclusion proof storage conflicted."
        ) from exc
    except Exception as exc:
        session.rollback()
        raise WalletTransactionInclusionProofFailure(
            "Transaction inclusion proofs could not be stored atomically."
        ) from exc


def get_wallet_transaction_inclusion_proofs(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any] | None:
    if get_wallet_transaction_trace_boc_verification(
        run_id, transaction_hash, session
    ) is None:
        return None
    capture = _find_capture_for_transaction(run_id, transaction_hash, session)
    if capture is None:
        return None
    verification = _find_verification(capture.id, session)
    if verification is None:
        return None
    transactions = sorted(verification.transactions, key=lambda row: row.preorder_index)
    proofs = [row.inclusion_proof for row in transactions]
    if not any(proofs):
        return None
    if any(row is None for row in proofs):
        raise WalletTransactionInclusionProofConflict(
            "Stored transaction inclusion proof set is partial."
        )
    return _catalog(verification, transactions)


def _proof_values(
    network: str,
    trust_level: int,
    request: dict[str, str],
    boc_transaction: Any,
    evidence: dict[str, Any],
    verified_at: datetime,
) -> dict[str, Any]:
    if not isinstance(evidence, dict) or any(
        evidence.get(field) != request[field]
        for field in ("account_address", "logical_time", "transaction_hash")
    ):
        raise WalletTransactionInclusionProofConflict(
            "Transaction inclusion proof coordinate changed."
        )
    if evidence.get("trust_level") != trust_level:
        raise WalletTransactionInclusionProofConflict(
            "Transaction inclusion proof trust level changed."
        )
    if evidence.get("transaction_boc_hex") != boc_transaction.transaction_boc_hex:
        raise WalletTransactionInclusionProofConflict(
            "Proved transaction BOC differs from persisted trace evidence."
        )
    _verify_proof(evidence)
    block = _valid_block(evidence.get("block"), "transaction block")
    anchor = _valid_block(evidence.get("masterchain_anchor"), "masterchain anchor")
    proof_hex = evidence.get("block_proof_boc_hex")
    if not _bounded_hex(proof_hex):
        raise WalletTransactionInclusionProofConflict(
            "Transaction block proof BOC is malformed."
        )
    document = {
        "contract_version": TRANSACTION_INCLUSION_CONTRACT_VERSION,
        "network": network,
        "trust_level": trust_level,
        **request,
        "block": block,
        "masterchain_anchor": anchor,
        "transaction_boc_sha256": proof_boc_sha256(
            boc_transaction.transaction_boc_hex
        ),
        "block_proof_boc_sha256": proof_boc_sha256(proof_hex),
        "verified_at": _iso(verified_at),
    }
    return {
        "network": network,
        "trust_level": trust_level,
        "account_address_canonical": request["account_address"],
        "logical_time": request["logical_time"],
        "transaction_hash": request["transaction_hash"],
        "block_workchain": block["workchain"],
        "block_shard": str(block["shard"]),
        "block_seqno": block["seqno"],
        "block_root_hash": block["root_hash"],
        "block_file_hash": block["file_hash"],
        "anchor_workchain": anchor["workchain"],
        "anchor_shard": str(anchor["shard"]),
        "anchor_seqno": anchor["seqno"],
        "anchor_root_hash": anchor["root_hash"],
        "anchor_file_hash": anchor["file_hash"],
        "block_proof_boc_hex": proof_hex,
        "transaction_boc_sha256": document["transaction_boc_sha256"],
        "block_proof_boc_sha256": document["block_proof_boc_sha256"],
        "evidence_digest_sha256": _digest_json(document),
        "verified_at": verified_at,
    }


def _catalog(verification: Any, transactions: list[Any]) -> dict[str, Any]:
    items = [_proof_response(row) for row in transactions]
    document = {
        "contract_version": TRANSACTION_INCLUSION_CONTRACT_VERSION,
        "boc_verification_id": str(verification.id),
        "proof_count": len(items),
        "proof_digests": [row["evidence_digest_sha256"] for row in items],
    }
    return {
        **document,
        "proofs": items,
        "catalog_digest_sha256": _digest_json(document),
        "provider_requests_performed": False,
        "all_transaction_bocs_included_in_blocks": True,
        "raw_bocs_returned": False,
        "message": (
            "Every persisted transaction BOC is bound by a stored Merkle proof "
            "to an exact block and was revalidated without provider access."
        ),
    }


def _proof_response(boc_transaction: Any) -> dict[str, Any]:
    row = boc_transaction.inclusion_proof
    if row is None:
        raise WalletTransactionInclusionProofConflict(
            "Transaction inclusion proof is missing."
        )
    evidence = {
        "account_address": row.account_address_canonical,
        "logical_time": row.logical_time,
        "transaction_hash": row.transaction_hash,
        "block": _row_block(row, "block"),
        "masterchain_anchor": _row_block(row, "anchor"),
        "transaction_boc_hex": boc_transaction.transaction_boc_hex,
        "block_proof_boc_hex": row.block_proof_boc_hex,
        "trust_level": row.trust_level,
    }
    expected = _proof_values(
        row.network,
        row.trust_level,
        {
            "account_address": row.account_address_canonical,
            "logical_time": row.logical_time,
            "transaction_hash": row.transaction_hash,
        },
        boc_transaction,
        evidence,
        row.verified_at,
    )
    for field, value in expected.items():
        if getattr(row, field) != value:
            raise WalletTransactionInclusionProofConflict(
                "Stored transaction inclusion proof metadata or digest changed."
            )
    return {
        "contract_version": TRANSACTION_INCLUSION_CONTRACT_VERSION,
        "network": row.network,
        "trust_level": row.trust_level,
        "account_address_canonical": row.account_address_canonical,
        "logical_time": row.logical_time,
        "transaction_hash": row.transaction_hash,
        "block": _public_block(row, "block"),
        "masterchain_anchor": _public_block(row, "anchor"),
        "transaction_boc_sha256": row.transaction_boc_sha256,
        "block_proof_boc_sha256": row.block_proof_boc_sha256,
        "evidence_digest_sha256": row.evidence_digest_sha256,
        "verified_at": _iso(row.verified_at),
        "block_merkle_proof_verified": True,
        "canonical_block_chain_verified_at_capture": row.trust_level == 0,
        "provider_free_revalidated": True,
        "raw_bocs_returned": False,
    }


def _verify_proof(evidence: dict[str, Any]) -> None:
    try:
        verify_transaction_inclusion_proof(evidence)
    except TonTransactionInclusionProofFailure as exc:
        raise WalletTransactionInclusionProofConflict(str(exc)) from exc


def _valid_block(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "workchain", "shard", "seqno", "root_hash", "file_hash"
    }:
        raise WalletTransactionInclusionProofConflict(f"Malformed {label}.")
    if not (
        type(value["workchain"]) is int
        and value["workchain"] in {-1, 0}
        and type(value["shard"]) is int
        and type(value["seqno"]) is int
        and value["seqno"] > 0
        and _hash(value["root_hash"])
        and _hash(value["file_hash"])
    ):
        raise WalletTransactionInclusionProofConflict(f"Malformed {label}.")
    return value


def _row_block(row: Any, prefix: str) -> dict[str, Any]:
    return {
        "workchain": getattr(row, f"{prefix}_workchain"),
        "shard": int(getattr(row, f"{prefix}_shard")),
        "seqno": getattr(row, f"{prefix}_seqno"),
        "root_hash": getattr(row, f"{prefix}_root_hash"),
        "file_hash": getattr(row, f"{prefix}_file_hash"),
    }


def _public_block(row: Any, prefix: str) -> dict[str, Any]:
    value = _row_block(row, prefix)
    value["shard"] = str(value["shard"])
    return value


def _bounded_hex(value: Any) -> bool:
    if not isinstance(value, str) or not value or len(value) > 8 * 1024 * 1024:
        return False
    if len(value) % 2 or value != value.lower():
        return False
    try:
        bytes.fromhex(value)
    except ValueError:
        return False
    return True


def _hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
