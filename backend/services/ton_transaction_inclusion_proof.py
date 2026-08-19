"""Capture and provider-free verify transaction-to-block Merkle proofs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import stat
import tempfile
from threading import Event
import time
from typing import Any

from pytoniq_core import Address, Cell
from pytoniq_core.proof.check_proof import check_block_header_proof
from pytoniq_core.tl.block import BlockIdExt
from pytoniq_core.tlb.account import AccountBlock
from pytoniq_core.tlb.block import Block
from pytoniq_core.tlb.transaction import Transaction

from services.ton_liteclient_config import (
    TonLiteclientConfigFailure,
    is_current_trusted_checkpoint,
    prepare_pinned_liteclient,
    verifier_policy_id,
)
from services.ton_liteclient_process import (
    TonLiteclientProcessFailure,
    acquire_liteclient_child_slot,
    apply_liteclient_child_guards,
    liteclient_cache_lock,
    liteclient_frame_limit_rejected,
    liteclient_process_shutting_down,
    release_liteclient_child_slot,
    start_registered_process,
    unregister_process,
)


_MAX_CAPTURE_REQUESTS = 256
_MAX_CAPTURE_INPUT_BYTES = 256 * 1024
_MAX_CAPTURE_RESULT_BYTES = 64 * 1024 * 1024
_PROCESS_POLL_SECONDS = 0.05
_PROCESS_TERMINATE_GRACE_SECONDS = 0.5
_PROCESS_KILL_GRACE_SECONDS = 0.5
_SAFE_CHILD_CODES = frozenset({
    "http_408",
    "http_425",
    "http_429",
    "http_500",
    "http_502",
    "http_503",
    "http_504",
    "liteserver_capture_failed",
    "liteserver_capture_timeout",
    "liteserver_capture_cancelled",
    "liteserver_config_invalid",
    "liteserver_config_timeout",
    "liteserver_config_too_large",
    "liteserver_config_unavailable",
    "liteserver_ipc_invalid",
    "liteserver_network_invalid",
    "liteserver_network_mismatch",
    "liteserver_proof_invalid",
    "liteserver_trust_invalid",
    "liteserver_result_too_large",
    "liteclient_resource_limit",
    "liteclient_capacity_unavailable",
})


class TonTransactionInclusionProofFailure(RuntimeError):
    """Transaction inclusion proof retrieval or verification failed."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "liteserver_capture_failed",
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


async def capture_transaction_inclusion_proofs_async(
    *,
    network: str,
    requests: list[dict[str, Any]],
    trust_level: int,
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    try:
        prepared = prepare_pinned_liteclient(
            network=network,
            trust_level=trust_level,
            timeout_seconds=timeout_seconds,
        )
    except TonLiteclientConfigFailure as exc:
        raise TonTransactionInclusionProofFailure(
            str(exc),
            code=exc.code,
            retryable=exc.retryable,
        ) from exc
    client = prepared.client
    trusted_checkpoint = BlockIdExt.from_dict(prepared.trusted_checkpoint)
    try:
        await client.start_up()
        observed_anchor = client.last_mc_block
        if observed_anchor is None:
            raise TonTransactionInclusionProofFailure(
                "Liteserver consensus did not produce a masterchain anchor.",
                code="liteserver_capture_failed",
                retryable=True,
            )
        result = []
        result_bytes = 2  # JSON list delimiters.
        for request in requests:
            candidate = await _capture_one(
                client,
                request=request,
                masterchain_anchor=observed_anchor,
                trusted_checkpoint=trusted_checkpoint,
                verifier_policy_id=prepared.verifier_policy_id,
                trust_level=trust_level,
            )
            candidate = _validated_capture_result(
                [candidate],
                requests=[request],
                trust_level=trust_level,
                network=network,
            )[0]
            result_bytes = _append_bounded_capture_result(
                result,
                candidate,
                result_bytes=result_bytes,
            )
        return result
    except TonTransactionInclusionProofFailure:
        raise
    except MemoryError as exc:
        raise TonTransactionInclusionProofFailure(
            "TON liteserver child reached its resource boundary.",
            code="liteclient_resource_limit",
            retryable=False,
        ) from exc
    except Exception as exc:
        if liteclient_frame_limit_rejected(client):
            raise TonTransactionInclusionProofFailure(
                "TON liteserver frame exceeds the safe size limit.",
                code="liteclient_resource_limit",
                retryable=False,
            ) from exc
        raise TonTransactionInclusionProofFailure(
            "TON transaction inclusion proof verification failed.",
            code="liteserver_capture_failed",
            retryable=True,
        ) from exc
    finally:
        await client.close_all()


def capture_transaction_inclusion_proofs_live(
    *,
    network: str,
    requests: list[dict[str, Any]],
    trust_level: int,
    timeout_seconds: int,
    cache_directory: str | None = None,
    cancellation_event: Event | None = None,
) -> list[dict[str, Any]]:
    """Capture inside a spawned process with an absolute parent-owned wall."""
    if cache_directory is None:
        from config import get_settings

        cache_directory = get_settings().ton_liteclient_cache_directory
    payload = _validated_capture_payload({
        "network": network,
        "requests": requests,
        "trust_level": trust_level,
        "timeout_seconds": timeout_seconds,
        "cache_directory": cache_directory,
    })
    return _run_capture_subprocess(
        payload,
        deadline_seconds=_capture_deadline_seconds(payload["timeout_seconds"]),
        cancellation_event=cancellation_event,
    )


async def _capture_one(
    client: Any,
    *,
    request: dict[str, Any],
    masterchain_anchor: BlockIdExt,
    trusted_checkpoint: BlockIdExt,
    verifier_policy_id: str,
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
    transaction_boc = bytes(raw["transaction"])
    block_proof_boc = bytes(raw["proof"])
    if len(transaction_boc) > 4 * 1024 * 1024 or len(block_proof_boc) > 4 * 1024 * 1024:
        raise TonTransactionInclusionProofFailure(
            "Liteserver transaction inclusion proof exceeds the safe size limit.",
            code="liteserver_result_too_large",
            retryable=False,
        )
    evidence = {
        "account_address": request["account_address"],
        "logical_time": request["logical_time"],
        "transaction_hash": request["transaction_hash"],
        "block": _block_document(block),
        "masterchain_anchor": _block_document(masterchain_anchor),
        "trusted_checkpoint": _block_document(trusted_checkpoint),
        "verifier_policy_id": verifier_policy_id,
        "transaction_boc_hex": transaction_boc.hex(),
        "block_proof_boc_hex": block_proof_boc.hex(),
        "trust_level": trust_level,
    }
    verify_transaction_inclusion_proof(evidence)
    if trust_level == 0:
        await client.prove_block(block)
    return evidence


def _run_capture_subprocess(
    payload: dict[str, Any],
    *,
    deadline_seconds: float,
    cancellation_event: Event | None = None,
    process_target: Any | None = None,
) -> list[dict[str, Any]]:
    """Run one capture with bounded file IPC and a non-negotiable deadline."""
    payload = _validated_capture_payload(payload)
    if not 0 < float(deadline_seconds) <= 180:
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion proof deadline is invalid.",
            code="liteserver_ipc_invalid",
            retryable=False,
        )
    input_path = ""
    output_path = ""
    slot_acquired = False
    process = None
    try:
        try:
            acquire_liteclient_child_slot(cancellation_event=cancellation_event)
            slot_acquired = True
        except TonLiteclientProcessFailure as exc:
            raise TonTransactionInclusionProofFailure(
                _child_error_message(exc.code),
                code=exc.code,
                retryable=exc.retryable,
            ) from exc
        input_path = _new_ipc_path("input")
        output_path = _new_ipc_path("output")
        _write_json_file(input_path, payload, maximum=_MAX_CAPTURE_INPUT_BYTES)
        if cancellation_event is not None and cancellation_event.is_set():
            raise TonTransactionInclusionProofFailure(
                "Transaction inclusion proof capture was cancelled.",
                code="liteserver_capture_cancelled",
                retryable=True,
            )
        context = multiprocessing.get_context("spawn")
        process = context.Process(
            target=process_target or _capture_process_entry,
            args=(input_path, output_path),
            name="ton-inclusion-proof",
            # The supervisor and shared atexit registry apply bounded
            # terminate/kill joins. Daemon mode alone is not relied on for
            # interpreter shutdown safety.
            daemon=True,
        )
        started = time.monotonic()
        start_registered_process(
            process,
            cleanup_paths=(input_path, output_path),
        )
        deadline = started + float(deadline_seconds)
        while process.is_alive():
            if cancellation_event is not None and cancellation_event.is_set():
                _stop_process(process)
                raise TonTransactionInclusionProofFailure(
                    "Transaction inclusion proof capture was cancelled.",
                    code="liteserver_capture_cancelled",
                    retryable=True,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _stop_process(process)
                raise TonTransactionInclusionProofFailure(
                    "Transaction inclusion proof capture reached its hard deadline.",
                    code="liteserver_capture_timeout",
                    retryable=True,
                )
            process.join(min(_PROCESS_POLL_SECONDS, remaining))
        if liteclient_process_shutting_down():
            return []
        process.join(0)
        if process.exitcode != 0:
            if process.exitcode in {-9, -24, -25}:
                raise TonTransactionInclusionProofFailure(
                    "Transaction inclusion proof child reached its resource boundary.",
                    code="liteclient_resource_limit",
                    retryable=False,
                )
            raise TonTransactionInclusionProofFailure(
                "Transaction inclusion proof child stopped unexpectedly.",
                code="liteserver_capture_failed",
                retryable=True,
            )
        envelope = _read_json_file(
            output_path,
            maximum=_MAX_CAPTURE_RESULT_BYTES,
        )
        return _validated_child_envelope(envelope, payload)
    finally:
        if process is not None and process.is_alive():
            try:
                _stop_process(process)
            except Exception:
                pass
        process_stopped = process is not None and not process.is_alive()
        if process_stopped:
            unregister_process(process)
            try:
                process.close()
            except Exception:
                pass
        if input_path:
            _unlink_ipc(input_path)
        if output_path:
            _unlink_ipc(output_path)
        if slot_acquired:
            release_liteclient_child_slot()


def _capture_process_entry(input_path: str, output_path: str) -> None:
    try:
        apply_liteclient_child_guards()
        payload = _validated_capture_payload(
            _read_json_file(input_path, maximum=_MAX_CAPTURE_INPUT_BYTES)
        )
        cache_directory = payload.pop("cache_directory")
        with liteclient_cache_lock(cache_directory, payload["network"]):
            result = asyncio.run(capture_transaction_inclusion_proofs_async(**payload))
        result = _validated_capture_result(
            result,
            requests=payload["requests"],
            trust_level=payload["trust_level"],
            network=payload["network"],
        )
        envelope = {"version": 1, "ok": True, "result": result}
    except TonTransactionInclusionProofFailure as exc:
        envelope = {
            "version": 1,
            "ok": False,
            "code": _safe_child_code(exc.code),
            "retryable": bool(exc.retryable),
        }
    except TonLiteclientProcessFailure as exc:
        envelope = {
            "version": 1,
            "ok": False,
            "code": _safe_child_code(exc.code),
            "retryable": bool(exc.retryable),
        }
    except BaseException:
        envelope = {
            "version": 1,
            "ok": False,
            "code": "liteserver_capture_failed",
            "retryable": True,
        }
    try:
        _write_json_file(output_path, envelope, maximum=_MAX_CAPTURE_RESULT_BYTES)
    except BaseException:
        os._exit(70)


def _validated_child_envelope(
    value: Any,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    if not isinstance(value, dict) or value.get("version") != 1:
        _invalid_ipc()
    if value.get("ok") is True and set(value) == {"version", "ok", "result"}:
        return _validated_capture_result(
            value["result"],
            requests=payload["requests"],
            trust_level=payload["trust_level"],
            network=payload["network"],
        )
    if value.get("ok") is False and set(value) == {
        "version", "ok", "code", "retryable"
    }:
        code = _safe_child_code(value.get("code"))
        if type(value.get("retryable")) is not bool:
            _invalid_ipc()
        raise TonTransactionInclusionProofFailure(
            _child_error_message(code),
            code=code,
            retryable=value["retryable"],
        )
    _invalid_ipc()


def _validated_capture_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "network", "requests", "trust_level", "timeout_seconds", "cache_directory"
    }:
        _invalid_ipc()
    network = value.get("network")
    if network not in {"ton-mainnet", "ton-testnet"}:
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion requires a scoped TON network.",
            code="liteserver_network_invalid",
            retryable=False,
        )
    trust_level = value.get("trust_level")
    timeout_seconds = value.get("timeout_seconds")
    requests = value.get("requests")
    cache_directory = value.get("cache_directory")
    if (
        type(trust_level) is not int
        or trust_level not in {0, 1}
        or type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= 60
        or not isinstance(requests, list)
        or not 1 <= len(requests) <= _MAX_CAPTURE_REQUESTS
        or not isinstance(cache_directory, str)
        or not cache_directory
        or len(cache_directory) > 1024
    ):
        _invalid_ipc()
    safe_requests = []
    for request in requests:
        if not isinstance(request, dict) or set(request) != {
            "account_address", "logical_time", "transaction_hash"
        }:
            _invalid_ipc()
        account = request.get("account_address")
        logical_time = request.get("logical_time")
        transaction_hash = request.get("transaction_hash")
        if (
            not isinstance(account, str)
            or not 66 <= len(account) <= 76
            or not isinstance(logical_time, str)
            or not logical_time.isdigit()
            or logical_time.startswith("0")
            or len(logical_time) > 20
            or int(logical_time) > 2**64 - 1
            or not _canonical_hash(transaction_hash)
        ):
            _invalid_ipc()
        safe_requests.append(dict(request))
    cache_path = str(Path(cache_directory).expanduser().absolute())
    result = {
        "network": network,
        "requests": safe_requests,
        "trust_level": trust_level,
        "timeout_seconds": timeout_seconds,
        "cache_directory": cache_path,
    }
    encoded = _canonical_json(result)
    if len(encoded) > _MAX_CAPTURE_INPUT_BYTES:
        _invalid_ipc()
    return result


def _validated_capture_result(
    value: Any,
    *,
    requests: list[dict[str, Any]],
    trust_level: int,
    network: str,
) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) != len(requests):
        _invalid_ipc()
    result = []
    expected_keys = {
        "account_address", "logical_time", "transaction_hash", "block",
        "masterchain_anchor", "trusted_checkpoint", "verifier_policy_id",
        "transaction_boc_hex", "block_proof_boc_hex", "trust_level",
    }
    for expected, item in zip(requests, value):
        if (
            not isinstance(item, dict)
            or set(item) != expected_keys
            or any(item.get(key) != expected[key] for key in expected)
            or item.get("trust_level") != trust_level
            or item.get("verifier_policy_id") != verifier_policy_id(network)
        ):
            _invalid_ipc()
        _ipc_block(item.get("block"))
        _ipc_block(item.get("masterchain_anchor"))
        _ipc_block(item.get("trusted_checkpoint"))
        if not is_current_trusted_checkpoint(
            network,
            item["verifier_policy_id"],
            item["trusted_checkpoint"],
        ):
            _invalid_ipc()
        _bounded_boc(item.get("transaction_boc_hex"), "transaction")
        _bounded_boc(item.get("block_proof_boc_hex"), "block proof")
        result.append(dict(item))
    if len(_canonical_json(result)) > _MAX_CAPTURE_RESULT_BYTES:
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion proof result exceeds the safe size limit.",
            code="liteserver_ipc_invalid",
            retryable=False,
        )
    return result


def _append_bounded_capture_result(
    result: list[dict[str, Any]],
    candidate: dict[str, Any],
    *,
    result_bytes: int,
) -> int:
    candidate_bytes = len(_canonical_json(candidate))
    next_size = result_bytes + candidate_bytes + (1 if result else 0)
    if next_size > _MAX_CAPTURE_RESULT_BYTES:
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion proof result exceeds the safe size limit.",
            code="liteserver_result_too_large",
            retryable=False,
        )
    result.append(candidate)
    return next_size


def _capture_deadline_seconds(timeout_seconds: int) -> float:
    return float(min(180, max(30, int(timeout_seconds) * 8)))


def _stop_process(process: Any) -> None:
    if not process.is_alive():
        process.join(0)
        return
    process.terminate()
    process.join(_PROCESS_TERMINATE_GRACE_SECONDS)
    if process.is_alive():
        process.kill()
        process.join(_PROCESS_KILL_GRACE_SECONDS)
    if process.is_alive():
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion proof child could not be stopped.",
            code="liteserver_capture_failed",
            retryable=True,
        )


def _new_ipc_path(label: str) -> str:
    fd, path = tempfile.mkstemp(prefix=f"ton-inclusion-{label}-", suffix=".json")
    os.fchmod(fd, 0o600)
    os.close(fd)
    return path


def _write_json_file(path: str, value: Any, *, maximum: int) -> None:
    encoded = _canonical_json(value)
    if len(encoded) > maximum:
        _invalid_ipc()
    flags = os.O_WRONLY | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            _invalid_ipc()
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                _invalid_ipc()
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def _read_json_file(path: str, *, maximum: int) -> Any:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            _invalid_ipc()
        chunks = []
        size = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                _invalid_ipc()
    finally:
        os.close(fd)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except Exception as exc:
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion proof IPC response is malformed.",
            code="liteserver_ipc_invalid",
            retryable=False,
        ) from exc


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception as exc:
        raise TonTransactionInclusionProofFailure(
            "Transaction inclusion proof IPC value is invalid.",
            code="liteserver_ipc_invalid",
            retryable=False,
        ) from exc


def _unlink_ipc(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def _safe_child_code(value: Any) -> str:
    if isinstance(value, str) and value in _SAFE_CHILD_CODES:
        return value
    return "liteserver_capture_failed"


def _child_error_message(code: str) -> str:
    if code == "liteserver_capture_timeout":
        return "Transaction inclusion proof capture reached its hard deadline."
    if code == "liteserver_capture_cancelled":
        return "Transaction inclusion proof capture was cancelled."
    if code == "liteclient_capacity_unavailable":
        return "TON liteserver verification capacity is temporarily unavailable."
    if code.startswith("http_") or code in {
        "liteserver_config_timeout", "liteserver_config_unavailable"
    }:
        return "Official TON liteserver configuration is unavailable."
    if code in {
        "liteserver_config_invalid", "liteserver_config_too_large",
        "liteserver_network_invalid", "liteserver_network_mismatch",
        "liteserver_proof_invalid",
        "liteserver_trust_invalid", "liteserver_ipc_invalid",
        "liteserver_result_too_large",
        "liteclient_resource_limit",
        "liteclient_capacity_unavailable",
    }:
        return "TON liteserver verification input or configuration is invalid."
    return "TON transaction inclusion proof capture failed."


def _invalid_ipc() -> None:
    raise TonTransactionInclusionProofFailure(
        "Transaction inclusion proof IPC contract is invalid.",
        code="liteserver_ipc_invalid",
        retryable=False,
    )


def _ipc_block(value: Any) -> None:
    if not isinstance(value, dict) or set(value) != {
        "workchain", "shard", "seqno", "root_hash", "file_hash"
    }:
        _invalid_ipc()
    if (
        type(value.get("workchain")) is not int
        or value["workchain"] not in {-1, 0}
        or type(value.get("shard")) is not int
        or type(value.get("seqno")) is not int
        or value["seqno"] < 0
        or not _canonical_hash(value.get("root_hash"))
        or not _canonical_hash(value.get("file_hash"))
    ):
        _invalid_ipc()


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


def _canonical_hash(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdef" for char in value)
    )


def _block_document(block: BlockIdExt) -> dict[str, Any]:
    return {
        "workchain": block.workchain,
        "shard": block.shard,
        "seqno": block.seqno,
        "root_hash": block.root_hash.hex(),
        "file_hash": block.file_hash.hex(),
    }
