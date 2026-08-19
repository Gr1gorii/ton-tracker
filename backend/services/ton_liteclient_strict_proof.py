"""Strict masterchain proof-link verification for the pinned TON liteclient.

pytoniq 0.1.43 verifies destination headers and validator signatures, but its
forward-link implementation does not bind the configuration proof to the
declared source block.  This module keeps the transport/client implementation
and replaces only that proof-chain boundary with application-owned checks that
mirror TON's ``BlockProofLink::validate`` invariants.
"""

from __future__ import annotations

import hashlib
import struct
from typing import Any, Iterable

from pytoniq.liteclient.client import LiteClient, LiteClientError
from pytoniq.liteclient.sync import choose_key_block
from pytoniq_core.boc import Cell
from pytoniq_core.crypto.signature import verify_sign
from pytoniq_core.proof.check_proof import (
    calculate_node_id_short,
    check_block_header_proof,
    check_proof,
)
from pytoniq_core.tl.block import BlockIdExt
from pytoniq_core.tlb.block import Block, ShardStateUnsplit
from pytoniq_core.tlb.config import ConfigParam28, ConfigParam34, ConfigParam35


_MASTERCHAIN_WORKCHAIN = -1
_MASTERCHAIN_SHARD = -(2**63)
_MAX_PROOF_LINKS = 256
_MAX_VALIDATORS = 2**16 - 1
_VALIDATOR_SET_MAGIC = -1877581587


class TonLiteclientStrictProofFailure(LiteClientError):
    """A liteserver proof chain failed an application-owned invariant."""

    code = "liteserver_proof_invalid"
    retryable = False


class StrictLiteClient(LiteClient):
    """LiteClient whose trust-0 masterchain links are verified fail closed."""

    async def raw_get_mc_block_proof(
        self,
        known_block: BlockIdExt,
        target_block: BlockIdExt | None = None,
        return_best_key_block: bool = False,
    ) -> tuple[bool, BlockIdExt, BlockIdExt | None, int]:
        known_block = _masterchain_block(known_block, "known block")
        target_block = (
            _masterchain_block(target_block, "target block")
            if target_block is not None
            else None
        )
        mode = 1 if target_block is not None else 0
        data: dict[str, Any] = {"known_block": known_block.to_dict(), "mode": mode}
        if target_block is not None:
            data["target_block"] = target_block.to_dict()
        result = await self.liteserver_request("getBlockProof", data)
        return verify_masterchain_proof_response(
            self,
            known_block=known_block,
            target_block=target_block,
            result=result,
            return_best_key_block=return_best_key_block,
        )


def verify_masterchain_proof_response(
    client: Any,
    *,
    known_block: BlockIdExt,
    target_block: BlockIdExt | None,
    result: Any,
    return_best_key_block: bool = False,
) -> tuple[bool, BlockIdExt, BlockIdExt | None, int]:
    """Verify one bounded ``liteServer.partialBlockProof`` response."""
    try:
        known_block = _masterchain_block(known_block, "known block")
        target_block = (
            _masterchain_block(target_block, "target block")
            if target_block is not None
            else None
        )
        if not isinstance(result, dict):
            _invalid("Masterchain proof response is not an object.")
        declared_from = _block_from_value(result.get("from"), "declared source")
        declared_to = _block_from_value(result.get("to"), "declared destination")
        complete = result.get("complete")
        steps = result.get("steps")
        if (
            type(complete) is not bool
            or not isinstance(steps, list)
            or len(steps) > _MAX_PROOF_LINKS
            or declared_from != known_block
        ):
            _invalid("Masterchain proof response header is incoherent.")

        last_trusted = known_block
        best_key: BlockIdExt | None = None
        best_key_ts = 0
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                _invalid(f"Masterchain proof link {index + 1} is not an object.")
            source = _block_from_value(step.get("from"), "link source")
            destination = _block_from_value(step.get("to"), "link destination")
            if source != last_trusted or source.seqno == destination.seqno:
                _invalid("Masterchain proof links are not contiguous.")
            is_forward = "config_proof" in step
            if is_forward:
                if source.seqno >= destination.seqno:
                    _invalid("A forward proof link does not move forward.")
                source_time, destination_time = _verify_forward_link(
                    source=source,
                    destination=destination,
                    step=step,
                )
            else:
                if source.seqno <= destination.seqno:
                    _invalid("A backward proof link does not move backward.")
                source_time, destination_time = _verify_backward_link(
                    source=source,
                    destination=destination,
                    step=step,
                )

            if return_best_key_block:
                if is_forward:
                    best_key, best_key_ts = choose_key_block(
                        best_key,
                        best_key_ts,
                        source,
                        source_time,
                    )
                if step.get("to_key_block") is True:
                    best_key, best_key_ts = choose_key_block(
                        best_key,
                        best_key_ts,
                        destination,
                        destination_time,
                    )
            if is_forward and (
                getattr(client, "last_key_block", None) is None
                or source.seqno > client.last_key_block.seqno
            ):
                client.last_key_block = source
            if step.get("to_key_block") is True and (
                getattr(client, "last_key_block", None) is None
                or destination.seqno > client.last_key_block.seqno
            ):
                client.last_key_block = destination
            last_trusted = destination

        if declared_to != last_trusted:
            _invalid("Masterchain proof destination does not match its final link.")
        if steps and last_trusted == known_block:
            _invalid("Masterchain proof made no progress.")
        if not steps and declared_from != declared_to:
            _invalid("An empty masterchain proof changes its block.")
        if target_block is not None:
            if target_block != known_block and not steps:
                _invalid("Masterchain proof made no progress toward its target.")
            reached_target = last_trusted == target_block
            if complete != reached_target:
                _invalid("Masterchain proof completeness does not match its target.")
        elif complete and not steps:
            # Without a requested target an empty response has no independently
            # meaningful completion claim.
            complete = False
        return complete, last_trusted, best_key, best_key_ts
    except TonLiteclientStrictProofFailure:
        raise
    except Exception as exc:
        raise TonLiteclientStrictProofFailure(
            "TON masterchain proof verification failed closed."
        ) from exc


def _verify_forward_link(
    *,
    source: BlockIdExt,
    destination: BlockIdExt,
    step: dict[str, Any],
) -> tuple[int, int]:
    required = {
        "from",
        "to",
        "to_key_block",
        "dest_proof",
        "config_proof",
        "signatures",
    }
    if not required.issubset(step) or type(step.get("to_key_block")) is not bool:
        _invalid("Forward masterchain proof link is incomplete.")
    source_root = _proof_root(
        step.get("config_proof"), "source configuration", source.root_hash
    )
    destination_root = _proof_root(
        step.get("dest_proof"), "destination", destination.root_hash
    )
    check_block_header_proof(source_root, source.root_hash)
    check_block_header_proof(destination_root, destination.root_hash)
    source_block = Block.deserialize(source_root.begin_parse())
    destination_block = Block.deserialize(destination_root.begin_parse())
    _require_block_identity(source_block, source, "source")
    _require_block_identity(destination_block, destination, "destination")
    source_info = source_block.info
    destination_info = destination_block.info
    source_extra = getattr(getattr(source_block, "extra", None), "custom", None)
    if (
        not bool(getattr(source_info, "key_block", False))
        or source_extra is None
        or not bool(getattr(source_extra, "key_block", False))
        or getattr(source_extra, "config", None) is None
    ):
        _invalid("Forward proof source is not a configuration key block.")
    if bool(destination_info.key_block) != step["to_key_block"]:
        _invalid("Forward proof destination key-block flag changed.")

    config = getattr(source_extra.config, "config", None)
    if not isinstance(config, dict) or 28 not in config or not ({34, 35} & set(config)):
        _invalid("Forward proof source lacks validator configuration.")
    catchain = ConfigParam28.deserialize(config[28])
    if 35 in config:
        validators = ConfigParam35.deserialize(config[35]).cur_temp_validators
    else:
        validators = ConfigParam34.deserialize(config[34]).cur_validators
    header_cc = _uint32(destination_info.gen_catchain_seqno, "header catchain")
    nodes = compute_masterchain_validator_set(catchain, validators, header_cc)
    signatures = step.get("signatures")
    if not isinstance(signatures, dict):
        _invalid("Forward proof signature set is missing.")
    signature_cc = _uint32(signatures.get("catchain_seqno"), "signature catchain")
    signature_hash = _uint32(
        signatures.get("validator_set_hash"), "signature validator-set hash"
    )
    header_hash = _uint32(
        destination_info.gen_validator_list_hash_short,
        "header validator-set hash",
    )
    computed_hash = compute_validator_set_hash(header_cc, nodes)
    if signature_cc != header_cc or signature_hash != header_hash or computed_hash != header_hash:
        _invalid("Forward proof validator-set metadata is inconsistent.")
    _verify_unique_weighted_signatures(
        nodes,
        signatures.get("signatures"),
        destination,
    )
    return (
        _uint32(source_info.gen_utime, "source generation time"),
        _uint32(destination_info.gen_utime, "destination generation time"),
    )


def _verify_backward_link(
    *,
    source: BlockIdExt,
    destination: BlockIdExt,
    step: dict[str, Any],
) -> tuple[int, int]:
    required = {
        "from",
        "to",
        "to_key_block",
        "dest_proof",
        "proof",
        "state_proof",
    }
    if not required.issubset(step) or type(step.get("to_key_block")) is not bool:
        _invalid("Backward masterchain proof link is incomplete.")
    source_root = _proof_root(step.get("proof"), "source", source.root_hash)
    destination_root = _proof_root(
        step.get("dest_proof"), "destination", destination.root_hash
    )
    state_hash = check_block_header_proof(
        source_root,
        source.root_hash,
        True,
    )
    if not isinstance(state_hash, bytes) or len(state_hash) != 32:
        _invalid("Backward proof source-state hash is invalid.")
    state_root = _proof_root(
        step.get("state_proof"), "source state", state_hash
    )
    check_block_header_proof(destination_root, destination.root_hash)
    source_block = Block.deserialize(source_root.begin_parse())
    destination_block = Block.deserialize(destination_root.begin_parse())
    _require_block_identity(source_block, source, "source")
    _require_block_identity(destination_block, destination, "destination")
    source_info = source_block.info
    destination_info = destination_block.info
    if bool(destination_info.key_block) != step["to_key_block"]:
        _invalid("Backward proof destination key-block flag changed.")
    state = ShardStateUnsplit.deserialize(state_root.begin_parse())
    _require_state_identity(state, source)
    custom = getattr(state, "custom", None)
    if custom is None:
        _invalid("Backward proof source state lacks masterchain history.")
    previous = getattr(custom, "prev_blocks", None)
    reference = None
    try:
        key_reference = previous[0].get(destination.seqno)
        reference = getattr(key_reference, "blk_ref", None)
    except Exception:
        reference = None
    if not _reference_matches(reference, destination):
        _invalid("Backward proof does not bind the full destination block id.")
    return (
        _uint32(source_info.gen_utime, "source generation time"),
        _uint32(destination_info.gen_utime, "destination generation time"),
    )


def compute_masterchain_validator_set(
    catchain: Any,
    validators: Any,
    catchain_seqno: int,
) -> list[Any]:
    """Port TON's masterchain branch of ``Config::do_compute_validator_set``."""
    total = getattr(validators, "total", None)
    main = getattr(validators, "main", None)
    values = getattr(validators, "list", None)
    if (
        type(total) is not int
        or type(main) is not int
        or not 1 <= main <= total <= _MAX_VALIDATORS
        or not isinstance(values, dict)
        or any(type(index) is not int for index in values)
        or set(values) != set(range(total))
    ):
        _invalid("Validator configuration is not canonical.")
    validator_rows = [values[index] for index in range(total)]
    total_weight = 0
    for node in validator_rows:
        public_key = getattr(getattr(node, "public_key", None), "pubkey", None)
        weight = getattr(node, "weight", None)
        address = getattr(node, "adnl_addr", None)
        if (
            not isinstance(public_key, bytes)
            or len(public_key) != 32
            or type(weight) is not int
            or not 0 < weight < 2**64
            or (address is not None and (not isinstance(address, bytes) or len(address) != 32))
        ):
            _invalid("Validator configuration contains an invalid entry.")
        total_weight += weight
        if total_weight > 2**61:
            _invalid("Validator configuration exceeds TON's total-weight bound.")
    declared_weight = getattr(validators, "total_weight", None)
    if declared_weight is not None and (
        type(declared_weight) is not int or declared_weight != total_weight
    ):
        _invalid("Validator configuration declares an incorrect total weight.")
    nodes = validator_rows[:main]
    shuffle = getattr(catchain, "shuffle_mc_validators", None)
    if shuffle is None:
        shuffle = False
    elif type(shuffle) is not bool:
        _invalid("Catchain validator-shuffle configuration is invalid.")
    if shuffle:
        generator = _ValidatorSetPrng(catchain_seqno)
        indices: list[int] = [0] * main
        for index in range(main):
            swap = generator.next_ranged(index + 1)
            indices[index] = indices[swap]
            indices[swap] = index
        nodes = [nodes[index] for index in indices]
    return nodes


def compute_validator_set_hash(catchain_seqno: int, nodes: Iterable[Any]) -> int:
    """Port TON's TL serialization plus CRC32C validator-set hash."""
    rows = list(nodes)
    if not 1 <= len(rows) <= _MAX_VALIDATORS:
        _invalid("Computed validator set is empty or too large.")
    document = bytearray(
        struct.pack(
            "<iII",
            _VALIDATOR_SET_MAGIC,
            _uint32(catchain_seqno, "validator-set catchain"),
            len(rows),
        )
    )
    for node in rows:
        public_key = getattr(getattr(node, "public_key", None), "pubkey", None)
        weight = getattr(node, "weight", None)
        address = getattr(node, "adnl_addr", None)
        if (
            not isinstance(public_key, bytes)
            or len(public_key) != 32
            or type(weight) is not int
            or not 0 < weight < 2**64
            or (address is not None and (not isinstance(address, bytes) or len(address) != 32))
        ):
            _invalid("Computed validator entry is invalid.")
        document.extend(public_key)
        document.extend(struct.pack("<Q", weight))
        document.extend(address if address is not None else bytes(32))
    return crc32c(bytes(document))


def crc32c(value: bytes) -> int:
    """Small dependency-free CRC32C (Castagnoli), matching ``td::crc32c``."""
    crc = 0xFFFFFFFF
    for byte in value:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return (~crc) & 0xFFFFFFFF


class _ValidatorSetPrng:
    def __init__(self, catchain_seqno: int) -> None:
        self._seed = 0
        self._catchain_seqno = _uint32(catchain_seqno, "validator shuffle catchain")
        self._values: list[int] = []

    def _refill(self) -> None:
        document = (
            self._seed.to_bytes(32, "big")
            + (1 << 63).to_bytes(8, "big")
            + _MASTERCHAIN_WORKCHAIN.to_bytes(4, "big", signed=True)
            + self._catchain_seqno.to_bytes(4, "big")
        )
        digest = hashlib.sha512(document).digest()
        self._seed = (self._seed + 1) % 2**256
        self._values = [
            int.from_bytes(digest[index : index + 8], "big")
            for index in range(0, 64, 8)
        ]

    def next_ulong(self) -> int:
        if not self._values:
            self._refill()
        return self._values.pop(0)

    def next_ranged(self, range_: int) -> int:
        if type(range_) is not int or not 1 <= range_ < 2**64:
            _invalid("Validator shuffle range is invalid.")
        return (range_ * self.next_ulong()) >> 64


def _verify_unique_weighted_signatures(
    nodes: list[Any],
    signatures: Any,
    block: BlockIdExt,
) -> None:
    if not isinstance(signatures, list) or not 1 <= len(signatures) <= len(nodes):
        _invalid("Forward proof signature count is invalid.")
    node_map: dict[bytes, Any] = {}
    total_weight = 0
    for node in nodes:
        public_key = getattr(getattr(node, "public_key", None), "pubkey", None)
        weight = getattr(node, "weight", None)
        if (
            not isinstance(public_key, bytes)
            or len(public_key) != 32
            or type(weight) is not int
            or not 0 < weight < 2**64
        ):
            _invalid("Forward proof validator entry is invalid.")
        node_id = calculate_node_id_short(public_key)
        if node_id in node_map:
            _invalid("Forward proof validator set contains duplicate identities.")
        node_map[node_id] = node
        total_weight += weight
        if total_weight >= 2**64:
            _invalid("Forward proof validator weight overflows.")
    message = b"pn\x0b\xc5" + block.root_hash + block.file_hash
    seen: set[bytes] = set()
    signed_weight = 0
    for signature in signatures:
        if not isinstance(signature, dict):
            _invalid("Forward proof signature is invalid.")
        try:
            node_id = bytes.fromhex(signature.get("node_id_short", ""))
        except Exception:
            _invalid("Forward proof signer identity is invalid.")
        raw_signature = signature.get("signature")
        if (
            len(node_id) != 32
            or node_id in seen
            or not isinstance(raw_signature, bytes)
            or len(raw_signature) != 64
            or node_id not in node_map
        ):
            _invalid("Forward proof signer set is invalid.")
        seen.add(node_id)
        node = node_map[node_id]
        if not verify_sign(
            public_key=node.public_key.pubkey,
            signed_message=message,
            signature=raw_signature,
        ):
            _invalid("Forward proof signature is invalid.")
        signed_weight += node.weight
    if signed_weight * 3 <= total_weight * 2:
        _invalid("Forward proof is not signed by more than two thirds of validators.")


def _proof_root(value: Any, label: str, expected_hash: bytes) -> Any:
    if not isinstance(value, bytes) or not value:
        _invalid(f"{label.capitalize()} proof is missing.")
    try:
        root = Cell.one_from_boc(value)
        if root is None or len(root.refs) != 1:
            _invalid(f"{label.capitalize()} proof is not a single Merkle proof.")
        check_proof(root, expected_hash)
        return root[0]
    except TonLiteclientStrictProofFailure:
        raise
    except Exception as exc:
        raise TonLiteclientStrictProofFailure(
            f"{label.capitalize()} proof cannot be decoded."
        ) from exc


def _require_block_identity(block: Any, expected: BlockIdExt, label: str) -> None:
    info = getattr(block, "info", None)
    shard = getattr(info, "shard", None)
    if (
        info is None
        or shard is None
        or getattr(info, "version", None) != 0
        or type(getattr(info, "seqno", None)) is not int
        or info.seqno != expected.seqno
        or getattr(shard, "workchain_id", None) != expected.workchain
        or getattr(shard, "calculate_shard_signed", lambda: None)() != expected.shard
        or bool(getattr(info, "not_master", False))
    ):
        _invalid(f"Masterchain proof {label} header identifies another block.")


def _require_state_identity(state: Any, expected: BlockIdExt) -> None:
    shard = getattr(state, "shard_id", None)
    if (
        shard is None
        or getattr(state, "seq_no", None) != expected.seqno
        or getattr(shard, "workchain_id", None) != expected.workchain
        or getattr(shard, "calculate_shard_signed", lambda: None)() != expected.shard
    ):
        _invalid("Backward proof state identifies another block.")


def _reference_matches(reference: Any, block: BlockIdExt) -> bool:
    return bool(
        reference is not None
        and getattr(reference, "seqno", None) == block.seqno
        and getattr(reference, "root_hash", None) == block.root_hash
        and getattr(reference, "file_hash", None) == block.file_hash
    )


def _block_from_value(value: Any, label: str) -> BlockIdExt:
    if not isinstance(value, dict):
        _invalid(f"Masterchain proof {label} is invalid.")
    try:
        block = BlockIdExt.from_dict(value)
    except Exception as exc:
        raise TonLiteclientStrictProofFailure(
            f"Masterchain proof {label} is invalid."
        ) from exc
    return _masterchain_block(block, label)


def _masterchain_block(value: Any, label: str) -> BlockIdExt:
    if (
        not isinstance(value, BlockIdExt)
        or value.workchain != _MASTERCHAIN_WORKCHAIN
        or value.shard != _MASTERCHAIN_SHARD
        or type(value.seqno) is not int
        or not 0 <= value.seqno < 2**32
        or not isinstance(value.root_hash, bytes)
        or len(value.root_hash) != 32
        or not isinstance(value.file_hash, bytes)
        or len(value.file_hash) != 32
    ):
        _invalid(f"Masterchain proof {label} is invalid.")
    return value


def _uint32(value: Any, label: str) -> int:
    if type(value) is not int or not -(2**31) <= value < 2**32:
        _invalid(f"Masterchain proof {label} is invalid.")
    return value & 0xFFFFFFFF


def _invalid(message: str) -> None:
    raise TonLiteclientStrictProofFailure(message)


__all__ = [
    "StrictLiteClient",
    "TonLiteclientStrictProofFailure",
    "compute_masterchain_validator_set",
    "compute_validator_set_hash",
    "crc32c",
    "verify_masterchain_proof_response",
]
