"""Proof-checked account state and local TVM jetton relationship verifier."""

from __future__ import annotations

import asyncio
from importlib.metadata import version
from pathlib import Path
import re
from threading import Event
from typing import Any

from pytoniq_core import Address, Cell, Slice, begin_cell

from services.ton_account_inclusion_proof import (
    TonAccountInclusionProofFailure,
    capture_account_inclusion_proof,
)
from services.ton_liteclient_config import (
    TonLiteclientConfigFailure,
    prepare_pinned_liteclient,
)
from services.ton_liteclient_process import (
    TonLiteclientProcessFailure,
    apply_liteclient_child_guards,
    child_error_envelope,
    liteclient_cache_lock,
    read_json_file,
    run_liteclient_subprocess,
    success_envelope,
    liteclient_frame_limit_rejected,
    write_json_file,
)


_MAX_INPUT_BYTES = 8 * 1024
_MAX_OUTPUT_BYTES = 64 * 1024 * 1024
_SAFE_CODES = frozenset({
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
    "liteserver_operation_invalid",
    "liteserver_trust_invalid",
    "liteclient_resource_limit",
    "liteclient_capacity_unavailable",
})


class TonLiteclientJettonVerificationFailure(RuntimeError):
    """Liteserver proof retrieval or local TVM execution failed."""

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


async def verify_jetton_contract_relationship_async(
    *,
    network: str,
    owner_account_canonical: str,
    jetton_wallet_account_canonical: str,
    jetton_master_account_canonical: str,
    trust_level: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Verify one wallet/master relationship at one masterchain anchor."""
    try:
        prepared = prepare_pinned_liteclient(
            network=network,
            trust_level=trust_level,
            timeout_seconds=timeout_seconds,
        )
    except TonLiteclientConfigFailure as exc:
        raise TonLiteclientJettonVerificationFailure(
            str(exc), code=exc.code, retryable=exc.retryable
        ) from exc
    client = prepared.client

    try:
        await client.start_up()
        anchor = client.last_mc_block
        if anchor is None:
            raise TonLiteclientJettonVerificationFailure(
                "Liteserver consensus did not produce a masterchain anchor.",
                code="liteserver_capture_failed",
                retryable=True,
            )
        wallet_account, wallet_inclusion = await capture_account_inclusion_proof(
            client,
            account_address=jetton_wallet_account_canonical,
            masterchain_anchor=anchor,
        )
        master_account, master_inclusion = await capture_account_inclusion_proof(
            client,
            account_address=jetton_master_account_canonical,
            masterchain_anchor=anchor,
        )
        wallet_state = _active_state(wallet_account, "jetton wallet")
        master_state = _active_state(master_account, "jetton master")

        wallet_stack = await client.run_get_method_local(
            jetton_wallet_account_canonical,
            "get_wallet_data",
            [],
            block=anchor,
        )
        wallet_data = _decode_wallet_data(wallet_stack)
        owner = Address(owner_account_canonical)
        master = Address(jetton_master_account_canonical)
        wallet = Address(jetton_wallet_account_canonical)
        if wallet_data["owner"] != owner:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton wallet getter owner does not match the persisted run wallet."
            )
        if wallet_data["master"] != master:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton wallet getter master does not match the persisted snapshot."
            )

        wallet_address_stack = await client.run_get_method_local(
            jetton_master_account_canonical,
            "get_wallet_address",
            [begin_cell().store_address(owner).end_cell().begin_parse()],
            block=anchor,
        )
        derived_wallet = _single_address(wallet_address_stack)
        if derived_wallet != wallet:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton master getter derived a different wallet address."
            )

        master_stack = await client.run_get_method_local(
            jetton_master_account_canonical,
            "get_jetton_data",
            [],
            block=anchor,
        )
        master_data = _decode_master_data(master_stack)
        wallet_code = wallet_data["wallet_code"]
        if wallet_state.code.hash != wallet_code.hash:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton wallet account code differs from get_wallet_data code."
            )
        if master_data["wallet_code"].hash != wallet_code.hash:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton master and wallet getters disagree on wallet code."
            )

        return {
            "verifier_name": "pytoniq-pytvm",
            "verifier_version": (
                f"pytoniq-{version('pytoniq')}/pytvm-{version('pytvm')}"
            ),
            "trust_level": trust_level,
            "anchor": {
                "workchain": anchor.workchain,
                "shard": str(anchor.shard),
                "seqno": anchor.seqno,
                "root_hash": anchor.root_hash.hex(),
                "file_hash": anchor.file_hash.hex(),
            },
            "wallet_balance_base_units": str(wallet_data["balance"]),
            "total_supply_base_units": str(master_data["total_supply"]),
            "mintable": master_data["mintable"],
            "wallet_code_boc_hex": wallet_state.code.to_boc().hex(),
            "wallet_data_boc_hex": wallet_state.data.to_boc().hex(),
            "master_code_boc_hex": master_state.code.to_boc().hex(),
            "master_data_boc_hex": master_state.data.to_boc().hex(),
            "wallet_code_hash": wallet_state.code.hash.hex(),
            "wallet_data_hash": wallet_state.data.hash.hex(),
            "master_code_hash": master_state.code.hash.hex(),
            "master_data_hash": master_state.data.hash.hex(),
            "jetton_content_hash": master_data["content"].hash.hex(),
            "account_state_proof_verified": True,
            # This v1 result is persisted without the selected policy/checkpoint.
            # Never turn trust_level alone into a durable canonical claim.
            "masterchain_checkpoint_chain_verified": False,
            "local_tvm_execution_applied": True,
            "account_inclusion_proofs": {
                "jetton_wallet": wallet_inclusion,
                "jetton_master": master_inclusion,
            },
        }
    except TonLiteclientJettonVerificationFailure:
        raise
    except MemoryError as exc:
        raise TonLiteclientJettonVerificationFailure(
            "TON liteserver child reached its resource boundary.",
            code="liteclient_resource_limit",
            retryable=False,
        ) from exc
    except TonAccountInclusionProofFailure as exc:
        raise TonLiteclientJettonVerificationFailure(
            str(exc), code="liteserver_operation_invalid", retryable=False
        ) from exc
    except Exception as exc:
        if liteclient_frame_limit_rejected(client):
            raise TonLiteclientJettonVerificationFailure(
                "TON liteserver frame exceeds the safe size limit.",
                code="liteclient_resource_limit",
                retryable=False,
            ) from exc
        raise TonLiteclientJettonVerificationFailure(
            "Proof-checked jetton contract verification failed.",
            code="liteserver_capture_failed",
            retryable=True,
        ) from exc
    finally:
        await client.close_all()


def verify_jetton_contract_relationship_live(
    *,
    network: str,
    owner_account_canonical: str,
    jetton_wallet_account_canonical: str,
    jetton_master_account_canonical: str,
    trust_level: int,
    timeout_seconds: int,
    cache_directory: str | None = None,
    cancellation_event: Event | None = None,
    process_target: Any | None = None,
) -> dict[str, Any]:
    """Verify in a cache-scoped child under a hard parent-owned wall."""
    if cache_directory is None:
        from config import get_settings

        cache_directory = get_settings().ton_liteclient_cache_directory
    payload = _validated_payload({
        "network": network,
        "owner_account_canonical": owner_account_canonical,
        "jetton_wallet_account_canonical": jetton_wallet_account_canonical,
        "jetton_master_account_canonical": jetton_master_account_canonical,
        "trust_level": trust_level,
        "timeout_seconds": timeout_seconds,
        "cache_directory": cache_directory,
    })
    try:
        result = run_liteclient_subprocess(
            payload,
            deadline_seconds=_deadline_seconds(payload["timeout_seconds"]),
            input_maximum=_MAX_INPUT_BYTES,
            output_maximum=_MAX_OUTPUT_BYTES,
            process_name="ton-jetton-verifier",
            path_prefix="ton-jetton",
            process_target=process_target or _jetton_process_entry,
            safe_error_codes=_SAFE_CODES,
            cancellation_event=cancellation_event,
        )
        return _validated_result(result, payload)
    except TonLiteclientProcessFailure as exc:
        raise TonLiteclientJettonVerificationFailure(
            _failure_message(exc.code),
            code=exc.code,
            retryable=exc.retryable,
        ) from exc


def _jetton_process_entry(input_path: str, output_path: str) -> None:
    try:
        apply_liteclient_child_guards()
        payload = _validated_payload(
            read_json_file(input_path, maximum=_MAX_INPUT_BYTES)
        )
        cache_directory = payload.pop("cache_directory")
        with liteclient_cache_lock(cache_directory, payload["network"]):
            result = asyncio.run(
                verify_jetton_contract_relationship_async(**payload)
            )
        envelope = success_envelope(_validated_result(result, payload))
    except BaseException as exc:
        envelope = child_error_envelope(exc, safe_error_codes=_SAFE_CODES)
    try:
        write_json_file(output_path, envelope, maximum=_MAX_OUTPUT_BYTES)
    except BaseException:
        import os

        os._exit(70)


def _validated_payload(value: Any) -> dict[str, Any]:
    expected = {
        "network", "owner_account_canonical",
        "jetton_wallet_account_canonical", "jetton_master_account_canonical",
        "trust_level", "timeout_seconds", "cache_directory",
    }
    if not isinstance(value, dict) or set(value) != expected:
        _invalid_payload()
    network = value.get("network")
    accounts = (
        value.get("owner_account_canonical"),
        value.get("jetton_wallet_account_canonical"),
        value.get("jetton_master_account_canonical"),
    )
    trust_level = value.get("trust_level")
    timeout_seconds = value.get("timeout_seconds")
    cache_directory = value.get("cache_directory")
    if (
        network not in {"ton-mainnet", "ton-testnet"}
        or any(
            not isinstance(account, str)
            or re.fullmatch(r"(?:0|-1):[0-9a-f]{64}", account) is None
            for account in accounts
        )
        or accounts[1] == accounts[2]
        or type(trust_level) is not int
        or trust_level not in {0, 1}
        or type(timeout_seconds) is not int
        or not 1 <= timeout_seconds <= 60
        or not isinstance(cache_directory, str)
        or not cache_directory
        or len(cache_directory) > 1024
    ):
        _invalid_payload()
    return {
        "network": network,
        "owner_account_canonical": accounts[0],
        "jetton_wallet_account_canonical": accounts[1],
        "jetton_master_account_canonical": accounts[2],
        "trust_level": trust_level,
        "timeout_seconds": timeout_seconds,
        "cache_directory": str(Path(cache_directory).expanduser().absolute()),
    }


def _validated_result(value: Any, payload: dict[str, Any]) -> dict[str, Any]:
    expected = {
        "verifier_name", "verifier_version", "trust_level", "anchor",
        "wallet_balance_base_units", "total_supply_base_units", "mintable",
        "wallet_code_boc_hex", "wallet_data_boc_hex", "master_code_boc_hex",
        "master_data_boc_hex", "wallet_code_hash", "wallet_data_hash",
        "master_code_hash", "master_data_hash", "jetton_content_hash",
        "account_state_proof_verified",
        "masterchain_checkpoint_chain_verified",
        "local_tvm_execution_applied", "account_inclusion_proofs",
    }
    if (
        not isinstance(value, dict)
        or set(value) != expected
        or value.get("trust_level") != payload.get("trust_level")
        or value.get("account_state_proof_verified") is not True
        or value.get("masterchain_checkpoint_chain_verified") is not False
        or value.get("local_tvm_execution_applied") is not True
    ):
        _invalid_payload()
    for field in (
        "wallet_code_boc_hex", "wallet_data_boc_hex",
        "master_code_boc_hex", "master_data_boc_hex",
    ):
        _bounded_hex(value.get(field), maximum=2 * 1024 * 1024)
    proofs = value.get("account_inclusion_proofs")
    if not isinstance(proofs, dict) or set(proofs) != {
        "jetton_wallet", "jetton_master"
    }:
        _invalid_payload()
    expected_accounts = {
        "jetton_wallet": payload["jetton_wallet_account_canonical"],
        "jetton_master": payload["jetton_master_account_canonical"],
    }
    for role, proof in proofs.items():
        if not isinstance(proof, dict) or proof.get("account_address") != (
            expected_accounts[role]
        ):
            _invalid_payload()
        for field in (
            "state_boc_hex", "account_proof_boc_hex", "shard_proof_boc_hex"
        ):
            _bounded_hex(proof.get(field), maximum=8 * 1024 * 1024)
    return dict(value)


def _bounded_hex(value: Any, *, maximum: int) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or len(value) % 2
        or value != value.lower()
        or re.fullmatch(r"[0-9a-f]+", value) is None
    ):
        _invalid_payload()


def _invalid_payload() -> None:
    raise TonLiteclientJettonVerificationFailure(
        "Jetton verification subprocess contract is invalid.",
        code="liteserver_ipc_invalid",
        retryable=False,
    )


def _deadline_seconds(timeout_seconds: int) -> float:
    return float(min(180, max(30, int(timeout_seconds) * 8)))


def _failure_message(code: str) -> str:
    if code == "liteserver_capture_timeout":
        return "Proof-checked jetton verification reached its hard deadline."
    if code == "liteserver_capture_cancelled":
        return "Proof-checked jetton verification was cancelled."
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
        "liteserver_operation_invalid", "liteserver_trust_invalid",
        "liteserver_ipc_invalid",
        "liteclient_resource_limit",
    }:
        return "Proof-checked jetton verification input or evidence is invalid."
    return "Proof-checked jetton contract verification failed."


def _active_state(account: Any, label: str) -> Any:
    if account is None or account.storage.state.type_ != "account_active":
        raise TonLiteclientJettonVerificationFailure(
            f"The {label} account is not active at the verification anchor."
        )
    state = account.storage.state.state_init
    if state.code is None or state.data is None:
        raise TonLiteclientJettonVerificationFailure(
            f"The {label} account has no complete code/data state."
        )
    return state


def _decode_wallet_data(stack: list[Any]) -> dict[str, Any]:
    if (
        len(stack) != 4
        or isinstance(stack[0], bool)
        or not isinstance(stack[0], int)
        or stack[0] < 0
        or not isinstance(stack[1], Slice)
        or not isinstance(stack[2], Slice)
        or not isinstance(stack[3], Cell)
    ):
        raise TonLiteclientJettonVerificationFailure(
            "get_wallet_data returned an invalid stack shape."
        )
    return {
        "balance": stack[0],
        "owner": _address_from_slice(stack[1]),
        "master": _address_from_slice(stack[2]),
        "wallet_code": stack[3],
    }


def _decode_master_data(stack: list[Any]) -> dict[str, Any]:
    if (
        len(stack) != 5
        or isinstance(stack[0], bool)
        or not isinstance(stack[0], int)
        or stack[0] < 0
        or isinstance(stack[1], bool)
        or not isinstance(stack[1], int)
        or not isinstance(stack[2], Slice)
        or not isinstance(stack[3], Cell)
        or not isinstance(stack[4], Cell)
    ):
        raise TonLiteclientJettonVerificationFailure(
            "get_jetton_data returned an invalid stack shape."
        )
    _address_from_slice(stack[2], allow_none=True)
    return {
        "total_supply": stack[0],
        "mintable": stack[1] != 0,
        "content": stack[3],
        "wallet_code": stack[4],
    }


def _single_address(stack: list[Any]) -> Address:
    if len(stack) != 1 or not isinstance(stack[0], Slice):
        raise TonLiteclientJettonVerificationFailure(
            "get_wallet_address returned an invalid stack shape."
        )
    address = _address_from_slice(stack[0])
    if address is None:  # pragma: no cover - guarded by allow_none=False
        raise TonLiteclientJettonVerificationFailure(
            "get_wallet_address returned no address."
        )
    return address


def _address_from_slice(
    value: Slice,
    *,
    allow_none: bool = False,
) -> Address | None:
    source = value.copy()
    try:
        address = source.load_address()
    except Exception as exc:
        raise TonLiteclientJettonVerificationFailure(
            "Jetton getter returned a malformed address slice."
        ) from exc
    if source.remaining_bits or source.remaining_refs:
        raise TonLiteclientJettonVerificationFailure(
            "Jetton getter address slice contains trailing data."
        )
    if address is None and not allow_none:
        raise TonLiteclientJettonVerificationFailure(
            "Jetton getter returned an absent required address."
        )
    return address


__all__ = [
    "TonLiteclientJettonVerificationFailure",
    "verify_jetton_contract_relationship_async",
    "verify_jetton_contract_relationship_live",
]
