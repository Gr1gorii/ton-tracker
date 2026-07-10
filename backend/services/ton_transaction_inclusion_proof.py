"""Capture and provider-free verify transaction-to-block Merkle proofs."""

from __future__ import annotations

import asyncio
import hashlib
from typing import Any

from pytoniq import LiteBalancer
from pytoniq_core import Address, Cell
from pytoniq_core.proof.check_proof import check_block_header_proof
from pytoniq_core.tl.block import BlockIdExt
from pytoniq_core.tlb.account import AccountBlock
from pytoniq_core.tlb.block import Block
from pytoniq_core.tlb.transaction import Transaction


class TonTransactionInclusionProofFailure(RuntimeError):
    """Transaction inclusion proof retrieval or verification failed."""


async def capture_transaction_inclusion_proofs_async(
    *,
    network: str,
    requests: list[dict[str, Any]],
    trust_level: int,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    if network == "ton-mainnet":
        client = LiteBalancer.from_mainnet_config(
            trust_level=trust_level,
            timeout=timeout_seconds,
        )
    elif network == "ton-testnet":
        client = LiteBalancer.from_testnet_config(
            trust_level=trust_level,
            timeout=timeout_seconds,
        )
    else:
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion requires a scoped TON network."
        )
    try:
        await client.start_up()
        anchor = client.last_mc_block
        if anchor is None:
            raise TonTransactionInclusionProofFailure(
                "Liteserver consensus did not produce a masterchain anchor."
            )
        result = []
        for request in requests:
            result.append(
                await _capture_one(
                    client,
                    request=request,
                    masterchain_anchor=anchor,
                    trust_level=trust_level,
                )
            )
        return result
    except TonTransactionInclusionProofFailure:
        raise
    except Exception as exc:
        raise TonTransactionInclusionProofFailure(
            "TON transaction inclusion proof verification failed."
        ) from exc
    finally:
        await client.close_all()


def capture_transaction_inclusion_proofs_live(**kwargs: Any) -> list[dict[str, Any]]:
    timeout = int(kwargs["timeout_seconds"])
    request_count = len(kwargs["requests"])
    try:
        return asyncio.run(
            asyncio.wait_for(
                capture_transaction_inclusion_proofs_async(**kwargs),
                timeout=max(30, timeout * max(8, request_count * 2)),
            )
        )
    except TonTransactionInclusionProofFailure:
        raise
    except Exception as exc:
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion proof capture timed out or failed."
        ) from exc


async def _capture_one(
    client: Any,
    *,
    request: dict[str, Any],
    masterchain_anchor: BlockIdExt,
    trust_level: int,
) -> dict[str, Any]:
    address = Address(request["account_address"])
    logical_time = int(request["logical_time"])
    transaction_hash = bytes.fromhex(request["transaction_hash"])
    transactions, blocks = await client.raw_get_transactions(
        address,
        count=1,
        from_lt=logical_time,
        from_hash=transaction_hash,
        only_archive=True,
    )
    if len(transactions) != 1 or len(blocks) != 1:
        raise TonTransactionInclusionProofFailure(
            "The exact transaction block could not be resolved."
        )
    block = blocks[0]
    raw = await client.execute_method(
        "liteserver_request",
        "getOneTransaction",
        {
            "id": block.to_dict(),
            "account": address.to_tl_account_id(),
            "lt": logical_time,
        },
        only_archive=True,
    )
    evidence = {
        "account_address": request["account_address"],
        "logical_time": request["logical_time"],
        "transaction_hash": request["transaction_hash"],
        "block": _block_document(block),
        "masterchain_anchor": _block_document(masterchain_anchor),
        "transaction_boc_hex": bytes(raw["transaction"]).hex(),
        "block_proof_boc_hex": bytes(raw["proof"]).hex(),
        "trust_level": trust_level,
    }
    verify_transaction_inclusion_proof(evidence)
    if trust_level == 0:
        await client.prove_block(block)
    return evidence


def verify_transaction_inclusion_proof(evidence: dict[str, Any]) -> Transaction:
    """Verify a transaction BOC against its stored block proof only."""
    try:
        address = Address(evidence["account_address"])
        logical_time = int(evidence["logical_time"])
        block = BlockIdExt.from_dict(evidence["block"])
        transaction_root = Cell.one_from_boc(
            _bounded_boc(evidence["transaction_boc_hex"], "transaction")
        )
        proof_root = Cell.one_from_boc(
            _bounded_boc(evidence["block_proof_boc_hex"], "block proof")
        )
        header = proof_root[0]
        check_block_header_proof(header, block.root_hash)
        account_block = Block.deserialize(header.begin_parse()).extra.account_blocks[
            0
        ].get(int.from_bytes(address.hash_part, "big"))
        if not account_block:
            raise TonTransactionInclusionProofFailure(
                "Block proof does not contain the requested account."
            )
        account_block: AccountBlock
        proved = account_block.transactions[0].get(logical_time)
        if proved is None or proved.get_hash(0) != transaction_root.get_hash(0):
            raise TonTransactionInclusionProofFailure(
                "Block proof does not commit to the requested transaction BOC."
            )
        if transaction_root.hash.hex() != evidence["transaction_hash"]:
            raise TonTransactionInclusionProofFailure(
                "Transaction BOC hash differs from the requested identity."
            )
        transaction = Transaction.deserialize(transaction_root.begin_parse())
        if transaction.lt != logical_time:
            raise TonTransactionInclusionProofFailure(
                "Transaction logical time differs from the proof coordinate."
            )
        return transaction
    except TonTransactionInclusionProofFailure:
        raise
    except Exception as exc:
        raise TonTransactionInclusionProofFailure(
            "Stored transaction inclusion proof is invalid."
        ) from exc


def proof_boc_sha256(value: str) -> str:
    return hashlib.sha256(bytes.fromhex(value)).hexdigest()


def _bounded_boc(value: Any, label: str) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 8 * 1024 * 1024
        or len(value) % 2
        or value != value.lower()
    ):
        raise TonTransactionInclusionProofFailure(
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
