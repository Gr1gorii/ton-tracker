"""Immutable transaction BOC-to-block inclusion evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from threading import Event
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
from services.ton_liteclient_config import (
    CURRENT_VERIFIER_POLICY_ID,
    LEGACY_CHECKPOINT_POLICY_ID,
    LEGACY_UNPINNED_POLICY_ID,
    is_current_trusted_checkpoint,
    is_recognized_trusted_checkpoint,
    verifier_policy_id,
)
from services.wallet_persisted_trace_evidence import _find_capture_for_transaction
from services.wallet_trace_boc_verification import (
    WalletTraceBocVerificationConflict,
    _find_verification,
    get_wallet_transaction_trace_boc_verification,
)


TRANSACTION_INCLUSION_CONTRACT_VERSION = "ton_transaction_inclusion_v2"
LEGACY_TRANSACTION_INCLUSION_CONTRACT_VERSION = "ton_transaction_inclusion_v1"


class WalletTransactionInclusionProofNotFound(LookupError):
    """The selected persisted BOC verification was not found."""


class WalletTransactionInclusionProofConflict(ValueError):
    """Stored or live inclusion evidence is incoherent."""


class WalletTransactionInclusionProofFailure(RuntimeError):
    """Inclusion proof retrieval or immutable persistence failed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "transaction_inclusion_unavailable",
        retryable: bool = True,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


def create_wallet_transaction_inclusion_proofs(
    run_id: int,
    transaction_hash: str,
    session: Session,
    *,
    live_verifier: Callable[..., list[dict[str, Any]]] = (
        capture_transaction_inclusion_proofs_live
    ),
    cancellation_event: Event | None = None,
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
    settings = get_settings()
    requested_trust_level = settings.ton_liteclient_trust_level
    requested_policy_id = verifier_policy_id(capture.network)
    existing = _proofs_for_trust(
        transactions,
        requested_trust_level,
        policy_id=requested_policy_id,
    )
    if all(row is not None for row in existing):
        return _catalog(
            verification,
            transactions,
            trust_level=requested_trust_level,
            policy_id=requested_policy_id,
        )
    if any(row is not None for row in existing):
        raise WalletTransactionInclusionProofConflict(
            "Partial transaction inclusion proof storage is forbidden for one trust level."
        )
    requests = [
        {
            "account_address": row.node.account_canonical,
            "logical_time": row.node.logical_time,
            "transaction_hash": row.transaction_hash,
        }
        for row in transactions
    ]
    expected_verification_id = verification.id
    expected_verification_digest = verification.evidence_digest_sha256
    expected_network = capture.network
    expected_transactions = [
        (
            row.id,
            row.node.account_canonical,
            row.node.logical_time,
            row.transaction_hash,
            row.transaction_boc_hex,
        )
        for row in transactions
    ]
    # Liteserver I/O is intentionally outside an ORM transaction. The exact
    # verification and BOC coordinates are reloaded before proof persistence.
    session.rollback()
    try:
        captured = live_verifier(
            network=expected_network,
            requests=requests,
            trust_level=settings.ton_liteclient_trust_level,
            timeout_seconds=settings.ton_liteclient_timeout_seconds,
            cache_directory=settings.ton_liteclient_cache_directory,
            cancellation_event=cancellation_event,
        )
    except TonTransactionInclusionProofFailure as exc:
        raise WalletTransactionInclusionProofFailure(
            str(exc),
            code=exc.code,
            retryable=exc.retryable,
        ) from exc
    if cancellation_event is not None and cancellation_event.is_set():
        raise WalletTransactionInclusionProofFailure(
            "Transaction inclusion proof capture was cancelled.",
            code="liteserver_capture_cancelled",
            retryable=True,
        )
    if not isinstance(captured, list) or len(captured) != len(transactions):
        raise WalletTransactionInclusionProofConflict(
            "Liteserver returned an incomplete inclusion proof set."
        )

    verified = get_wallet_transaction_trace_boc_verification(
        run_id, transaction_hash, session
    )
    if verified is None:
        raise WalletTransactionInclusionProofNotFound(
            "Persisted BOC verification disappeared during proof acquisition."
        )
    capture = _find_capture_for_transaction(run_id, transaction_hash, session)
    if capture is None:
        raise WalletTransactionInclusionProofNotFound(
            "Persisted trace capture disappeared during proof acquisition."
        )
    verification = _find_verification(capture.id, session)
    if verification is None:
        raise WalletTransactionInclusionProofNotFound(
            "Persisted BOC verification disappeared during proof acquisition."
        )
    transactions = sorted(
        verification.transactions,
        key=lambda row: row.preorder_index,
    )
    current_transactions = [
        (
            row.id,
            row.node.account_canonical,
            row.node.logical_time,
            row.transaction_hash,
            row.transaction_boc_hex,
        )
        for row in transactions
    ]
    if (
        verification.id != expected_verification_id
        or verification.evidence_digest_sha256 != expected_verification_digest
        or capture.network != expected_network
        or current_transactions != expected_transactions
    ):
        raise WalletTransactionInclusionProofConflict(
            "Persisted BOC verification changed during proof acquisition."
        )
    existing = _proofs_for_trust(
        transactions,
        requested_trust_level,
        policy_id=requested_policy_id,
    )
    if all(row is not None for row in existing):
        return _catalog(
            verification,
            transactions,
            trust_level=requested_trust_level,
            policy_id=requested_policy_id,
        )
    if any(row is not None for row in existing):
        raise WalletTransactionInclusionProofConflict(
            "Partial transaction inclusion proof storage is forbidden for one trust level."
        )
    verified_at = datetime.now(timezone.utc)
    try:
        for request, boc_transaction, evidence in zip(
            requests, transactions, captured
        ):
            values = _proof_values(
                capture.network,
                requested_trust_level,
                requested_policy_id,
                request,
                boc_transaction,
                evidence,
                verified_at,
            )
            boc_transaction.inclusion_proofs.append(
                WalletTransactionInclusionProof(**values)
            )
        session.flush()
        result = _catalog(
            verification,
            transactions,
            trust_level=requested_trust_level,
            policy_id=requested_policy_id,
        )
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
    identity = _strongest_complete_identity(transactions)
    if identity is None:
        return None
    trust_level, policy_id = identity
    return _catalog(
        verification,
        transactions,
        trust_level=trust_level,
        policy_id=policy_id,
    )


def get_wallet_transaction_inclusion_proofs_for_current_trust(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any] | None:
    """Read only the complete proof set matching the configured verifier trust."""
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
    transactions = sorted(
        verification.transactions,
        key=lambda row: row.preorder_index,
    )
    trust_level = get_settings().ton_liteclient_trust_level
    policy_id = verifier_policy_id(capture.network)
    proofs = _proofs_for_trust(transactions, trust_level, policy_id=policy_id)
    if not any(proofs):
        return None
    if any(row is None for row in proofs):
        raise WalletTransactionInclusionProofConflict(
            "Stored transaction inclusion proof set is partial for configured trust."
        )
    return _catalog(
        verification,
        transactions,
        trust_level=trust_level,
        policy_id=policy_id,
    )


def _proof_values(
    network: str,
    trust_level: int,
    policy_id: str,
    request: dict[str, str],
    boc_transaction: Any,
    evidence: dict[str, Any],
    verified_at: datetime,
    *,
    allow_recognized_legacy_policy: bool = False,
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
    if evidence.get("verifier_policy_id") != policy_id:
        raise WalletTransactionInclusionProofConflict(
            "Transaction inclusion proof verifier policy changed."
        )
    if evidence.get("transaction_boc_hex") != boc_transaction.transaction_boc_hex:
        raise WalletTransactionInclusionProofConflict(
            "Proved transaction BOC differs from persisted trace evidence."
        )
    _verify_proof(evidence)
    block = _valid_block(evidence.get("block"), "transaction block")
    anchor = _valid_block(evidence.get("masterchain_anchor"), "masterchain anchor")
    checkpoint = _valid_block(
        evidence.get("trusted_checkpoint"),
        "trusted checkpoint",
    )
    current_checkpoint = is_current_trusted_checkpoint(
        network,
        policy_id,
        checkpoint,
    )
    recognized_legacy_checkpoint = (
        allow_recognized_legacy_policy
        and policy_id == LEGACY_CHECKPOINT_POLICY_ID
        and is_recognized_trusted_checkpoint(network, policy_id, checkpoint)
    )
    if not (current_checkpoint or recognized_legacy_checkpoint):
        raise WalletTransactionInclusionProofConflict(
            "Transaction inclusion proof trust root is not application-owned."
        )
    proof_hex = evidence.get("block_proof_boc_hex")
    if not _bounded_hex(proof_hex):
        raise WalletTransactionInclusionProofConflict(
            "Transaction block proof BOC is malformed."
        )
    document = {
        "contract_version": TRANSACTION_INCLUSION_CONTRACT_VERSION,
        "network": network,
        "trust_level": trust_level,
        "verifier_policy_id": policy_id,
        "trusted_checkpoint": checkpoint,
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
        "verifier_policy_id": policy_id,
        "trusted_checkpoint_workchain": checkpoint["workchain"],
        "trusted_checkpoint_shard": str(checkpoint["shard"]),
        "trusted_checkpoint_seqno": checkpoint["seqno"],
        "trusted_checkpoint_root_hash": checkpoint["root_hash"],
        "trusted_checkpoint_file_hash": checkpoint["file_hash"],
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


def _catalog(
    verification: Any,
    transactions: list[Any],
    *,
    trust_level: int,
    policy_id: str,
) -> dict[str, Any]:
    items = [
        _proof_response(row, trust_level=trust_level, policy_id=policy_id)
        for row in transactions
    ]
    checkpoints = [row["trusted_checkpoint"] for row in items]
    checkpoint = checkpoints[0]
    if any(
        row["verifier_policy_id"] != policy_id
        or row["trusted_checkpoint"] != checkpoint
        for row in items
    ):
        raise WalletTransactionInclusionProofConflict(
            "Transaction inclusion proof catalog mixed verifier policies."
        )
    document = {
        "contract_version": TRANSACTION_INCLUSION_CONTRACT_VERSION,
        "verifier_policy_id": policy_id,
        "trusted_checkpoint": checkpoint,
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


def _proof_response(
    boc_transaction: Any,
    *,
    trust_level: int,
    policy_id: str = CURRENT_VERIFIER_POLICY_ID,
) -> dict[str, Any]:
    row = _proof_for_trust(boc_transaction, trust_level, policy_id=policy_id)
    if row is None:
        raise WalletTransactionInclusionProofConflict(
            "Transaction inclusion proof is missing for the selected trust level."
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
    if row.verifier_policy_id == LEGACY_UNPINNED_POLICY_ID:
        expected = _legacy_proof_values(
            row,
            boc_transaction,
            evidence,
        )
        checkpoint = None
        evidence_contract_version = LEGACY_TRANSACTION_INCLUSION_CONTRACT_VERSION
        canonical = False
    elif row.verifier_policy_id in {
        CURRENT_VERIFIER_POLICY_ID,
        LEGACY_CHECKPOINT_POLICY_ID,
    }:
        checkpoint = _row_checkpoint(row)
        evidence.update({
            "verifier_policy_id": row.verifier_policy_id,
            "trusted_checkpoint": checkpoint,
        })
        expected = _proof_values(
            row.network,
            row.trust_level,
            row.verifier_policy_id,
            {
                "account_address": row.account_address_canonical,
                "logical_time": row.logical_time,
                "transaction_hash": row.transaction_hash,
            },
            boc_transaction,
            evidence,
            row.verified_at,
            allow_recognized_legacy_policy=(
                row.verifier_policy_id == LEGACY_CHECKPOINT_POLICY_ID
            ),
        )
        evidence_contract_version = TRANSACTION_INCLUSION_CONTRACT_VERSION
        canonical = (
            row.trust_level == 0
            and row.verifier_policy_id == CURRENT_VERIFIER_POLICY_ID
        )
    else:
        raise WalletTransactionInclusionProofConflict(
            "Stored transaction inclusion proof verifier policy is unsupported."
        )
    for field, value in expected.items():
        if getattr(row, field) != value:
            raise WalletTransactionInclusionProofConflict(
                "Stored transaction inclusion proof metadata or digest changed."
            )
    return {
        "contract_version": TRANSACTION_INCLUSION_CONTRACT_VERSION,
        "evidence_contract_version": evidence_contract_version,
        "network": row.network,
        "trust_level": row.trust_level,
        "verifier_policy_id": row.verifier_policy_id,
        "trusted_checkpoint": _public_checkpoint(checkpoint),
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
        "canonical_block_chain_verified_at_capture": canonical,
        "checkpoint_to_observed_head_transcript_persisted": False,
        "provider_free_revalidated": True,
        "raw_bocs_returned": False,
    }


def _legacy_proof_values(
    row: Any,
    boc_transaction: Any,
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Revalidate the original v1 digest without inventing checkpoint provenance."""
    _verify_proof(evidence)
    block = _valid_block(evidence.get("block"), "transaction block")
    anchor = _valid_block(evidence.get("masterchain_anchor"), "masterchain anchor")
    proof_hex = evidence.get("block_proof_boc_hex")
    if not _bounded_hex(proof_hex):
        raise WalletTransactionInclusionProofConflict(
            "Transaction block proof BOC is malformed."
        )
    document = {
        "contract_version": LEGACY_TRANSACTION_INCLUSION_CONTRACT_VERSION,
        "network": row.network,
        "trust_level": row.trust_level,
        "account_address": row.account_address_canonical,
        "logical_time": row.logical_time,
        "transaction_hash": row.transaction_hash,
        "block": block,
        "masterchain_anchor": anchor,
        "transaction_boc_sha256": proof_boc_sha256(
            boc_transaction.transaction_boc_hex
        ),
        "block_proof_boc_sha256": proof_boc_sha256(proof_hex),
        "verified_at": _iso(row.verified_at),
    }
    return {
        "network": row.network,
        "trust_level": row.trust_level,
        "account_address_canonical": row.account_address_canonical,
        "logical_time": row.logical_time,
        "transaction_hash": row.transaction_hash,
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
        "verified_at": row.verified_at,
    }


def _row_checkpoint(row: Any) -> dict[str, Any]:
    value = {
        "workchain": row.trusted_checkpoint_workchain,
        "shard": (
            int(row.trusted_checkpoint_shard)
            if row.trusted_checkpoint_shard is not None
            else None
        ),
        "seqno": row.trusted_checkpoint_seqno,
        "root_hash": row.trusted_checkpoint_root_hash,
        "file_hash": row.trusted_checkpoint_file_hash,
    }
    return _valid_block(value, "trusted checkpoint")


def _public_checkpoint(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    result = dict(value)
    result["shard"] = str(result["shard"])
    return result


def _proof_for_trust(
    boc_transaction: Any,
    trust_level: int,
    *,
    policy_id: str,
) -> Any | None:
    matches = [
        row
        for row in boc_transaction.inclusion_proofs
        if row.trust_level == trust_level and row.verifier_policy_id == policy_id
    ]
    if len(matches) > 1:
        raise WalletTransactionInclusionProofConflict(
            "Stored transaction inclusion proof trust identity is duplicated."
        )
    return matches[0] if matches else None


def _proofs_for_trust(
    transactions: list[Any],
    trust_level: int,
    *,
    policy_id: str,
) -> list[Any | None]:
    return [
        _proof_for_trust(row, trust_level, policy_id=policy_id)
        for row in transactions
    ]


def _strongest_complete_identity(
    transactions: list[Any],
) -> tuple[int, str] | None:
    observed = {
        (proof.trust_level, proof.verifier_policy_id)
        for transaction in transactions
        for proof in transaction.inclusion_proofs
    }
    if not observed:
        return None
    if any(
        trust_level not in {0, 1}
        or policy_id not in {
            CURRENT_VERIFIER_POLICY_ID,
            LEGACY_CHECKPOINT_POLICY_ID,
            LEGACY_UNPINNED_POLICY_ID,
        }
        for trust_level, policy_id in observed
    ):
        raise WalletTransactionInclusionProofConflict(
            "Stored transaction inclusion proof trust level is unsupported."
        )
    complete: list[tuple[int, str]] = []
    for trust_level, policy_id in sorted(
        observed,
        key=lambda value: {
            (0, CURRENT_VERIFIER_POLICY_ID): 0,
            (1, CURRENT_VERIFIER_POLICY_ID): 1,
            (1, LEGACY_UNPINNED_POLICY_ID): 2,
            (1, LEGACY_CHECKPOINT_POLICY_ID): 3,
            (0, LEGACY_UNPINNED_POLICY_ID): 4,
            (0, LEGACY_CHECKPOINT_POLICY_ID): 5,
        }[value],
    ):
        proofs = _proofs_for_trust(
            transactions,
            trust_level,
            policy_id=policy_id,
        )
        if all(row is not None for row in proofs):
            complete.append((trust_level, policy_id))
        elif any(row is not None for row in proofs):
            raise WalletTransactionInclusionProofConflict(
                "Stored transaction inclusion proof set is partial for one trust level."
            )
    return complete[0] if complete else None


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
