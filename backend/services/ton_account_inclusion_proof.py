"""Capture and provider-free verify TON account-state inclusion proofs."""

from __future__ import annotations

import hashlib
from typing import Any

from pytoniq_core import Address, Cell
from pytoniq_core.proof.check_proof import check_account_proof, check_shard_proof
from pytoniq_core.tl.block import BlockIdExt
from pytoniq_core.tlb.account import Account


class TonAccountInclusionProofFailure(RuntimeError):
    """Account-state proof retrieval or verification failed closed."""


async def capture_account_inclusion_proof(
    client: Any,
    *,
    account_address: str,
    masterchain_anchor: BlockIdExt,
) -> tuple[Account, dict[str, Any]]:
    """Fetch raw liteserver evidence and verify it before returning it."""
    address = Address(account_address)
    try:
        result = await client.execute_method(
            "liteserver_request",
            "getAccountState",
            {
                "id": masterchain_anchor.to_dict(),
                "account": address.to_tl_account_id(),
            },
        )
        if not result.get("state"):
            raise TonAccountInclusionProofFailure(
                "The account has no state at the selected block anchor."
            )
        shard_block = BlockIdExt.from_dict(result["shardblk"])
        evidence = {
            "account_address": account_address,
            "shard_block": _block_document(shard_block),
            "state_boc_hex": bytes(result["state"]).hex(),
            "account_proof_boc_hex": bytes(result["proof"]).hex(),
            "shard_proof_boc_hex": bytes(result["shard_proof"]).hex(),
        }
        verified = verify_account_inclusion_proof(
            evidence,
            masterchain_anchor=_block_document(masterchain_anchor),
        )
        return verified, evidence
    except TonAccountInclusionProofFailure:
        raise
    except Exception as exc:
        raise TonAccountInclusionProofFailure(
            "TON account-state inclusion proof verification failed."
        ) from exc


def verify_account_inclusion_proof(
    evidence: dict[str, Any],
    *,
    masterchain_anchor: dict[str, Any],
) -> Account:
    """Revalidate stored Merkle evidence without a provider request."""
    try:
        address = Address(evidence["account_address"])
        anchor = BlockIdExt.from_dict(masterchain_anchor)
        shard_block = BlockIdExt.from_dict(evidence["shard_block"])
        state_bytes = _bounded_boc(evidence["state_boc_hex"], "state")
        account_proof = _bounded_boc(
            evidence["account_proof_boc_hex"], "account proof"
        )
        shard_proof = _bounded_boc(
            evidence["shard_proof_boc_hex"], "shard proof"
        )
        state_root = Cell.one_from_boc(state_bytes)
        check_shard_proof(shard_proof, anchor, shard_block)
        check_account_proof(
            account_proof,
            shard_block,
            address,
            state_root,
        )
        return Account.deserialize(state_root.begin_parse())
    except TonAccountInclusionProofFailure:
        raise
    except Exception as exc:
        raise TonAccountInclusionProofFailure(
            "Stored TON account-state inclusion evidence is invalid."
        ) from exc


def inclusion_hashes(evidence: dict[str, Any]) -> dict[str, str]:
    return {
        field: hashlib.sha256(bytes.fromhex(evidence[field])).hexdigest()
        for field in (
            "state_boc_hex",
            "account_proof_boc_hex",
            "shard_proof_boc_hex",
        )
    }


def _bounded_boc(value: Any, label: str) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 8 * 1024 * 1024
        or len(value) % 2
        or value != value.lower()
    ):
        raise TonAccountInclusionProofFailure(
            f"Stored {label} BOC is not a bounded canonical hex value."
        )
    return bytes.fromhex(value)


def _block_document(block: BlockIdExt) -> dict[str, Any]:
    return {
        "workchain": block.workchain,
        "shard": block.shard,
        "seqno": block.seqno,
        "root_hash": block.root_hash.hex(),
        "file_hash": block.file_hash.hex(),
    }
