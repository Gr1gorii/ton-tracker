"""Resolve a wallet public key from proof-checked account state."""

from __future__ import annotations

import asyncio
from pathlib import Path
import re
from threading import Event
from typing import Any

from config import get_settings
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


_MAX_INPUT_BYTES = 4 * 1024
_MAX_OUTPUT_BYTES = 4 * 1024
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


class TonWalletPublicKeyFailure(RuntimeError):
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


async def _resolve_async(
    *, network: str, address: str, trust_level: int, timeout_seconds: int
) -> bytes:
    try:
        prepared = prepare_pinned_liteclient(
            network=network,
            trust_level=trust_level,
            timeout_seconds=timeout_seconds,
        )
    except TonLiteclientConfigFailure as exc:
        raise TonWalletPublicKeyFailure(
            str(exc), code=exc.code, retryable=exc.retryable
        ) from exc
    client = prepared.client
    try:
        await client.start_up()
        anchor = client.last_mc_block
        account, _ = await client.raw_get_account_state(address, block=anchor)
        if account is None or account.storage.state.type_ != "account_active":
            raise TonWalletPublicKeyFailure(
                "Wallet account is not active.",
                code="liteserver_operation_invalid",
                retryable=False,
            )
        stack = await client.run_get_method_local(
            address, "get_public_key", [], block=anchor
        )
        if len(stack) != 1 or type(stack[0]) is not int or not 0 <= stack[0] < 2**256:
            raise TonWalletPublicKeyFailure(
                "Wallet public-key getter is invalid.",
                code="liteserver_operation_invalid",
                retryable=False,
            )
        return stack[0].to_bytes(32, "big")
    except TonWalletPublicKeyFailure:
        raise
    except MemoryError as exc:
        raise TonWalletPublicKeyFailure(
            "TON liteserver child reached its resource boundary.",
            code="liteclient_resource_limit",
            retryable=False,
        ) from exc
    except Exception as exc:
        if liteclient_frame_limit_rejected(client):
            raise TonWalletPublicKeyFailure(
                "TON liteserver frame exceeds the safe size limit.",
                code="liteclient_resource_limit",
                retryable=False,
            ) from exc
        raise TonWalletPublicKeyFailure(
            "Proof-checked wallet public-key resolution failed.",
            code="liteserver_capture_failed",
            retryable=True,
        ) from exc
    finally:
        await client.close_all()


def resolve_wallet_public_key_live(
    *,
    network: str,
    address: str,
    trust_level: int,
    timeout_seconds: int,
    cache_directory: str | None = None,
    cancellation_event: Event | None = None,
    process_target: Any | None = None,
) -> bytes:
    """Resolve in a cache-scoped child that the parent can always terminate."""
    if cache_directory is None:
        cache_directory = get_settings().ton_liteclient_cache_directory
    payload = _validated_payload({
        "network": network,
        "address": address,
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
            process_name="ton-wallet-public-key",
            path_prefix="ton-public-key",
            process_target=process_target or _public_key_process_entry,
            safe_error_codes=_SAFE_CODES,
            cancellation_event=cancellation_event,
        )
        return bytes.fromhex(_validated_result(result))
    except TonLiteclientProcessFailure as exc:
        raise TonWalletPublicKeyFailure(
            _failure_message(exc.code),
            code=exc.code,
            retryable=exc.retryable,
        ) from exc


def _public_key_process_entry(input_path: str, output_path: str) -> None:
    try:
        apply_liteclient_child_guards()
        payload = _validated_payload(
            read_json_file(input_path, maximum=_MAX_INPUT_BYTES)
        )
        cache_directory = payload.pop("cache_directory")
        with liteclient_cache_lock(cache_directory, payload["network"]):
            public_key = asyncio.run(_resolve_async(**payload))
        envelope = success_envelope(_validated_result(public_key.hex()))
    except BaseException as exc:
        envelope = child_error_envelope(exc, safe_error_codes=_SAFE_CODES)
    try:
        write_json_file(output_path, envelope, maximum=_MAX_OUTPUT_BYTES)
    except BaseException:
        import os

        os._exit(70)


def _validated_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "network", "address", "trust_level", "timeout_seconds",
        "cache_directory",
    }:
        _invalid_payload()
    network = value.get("network")
    address = value.get("address")
    trust_level = value.get("trust_level")
    timeout_seconds = value.get("timeout_seconds")
    cache_directory = value.get("cache_directory")
    if (
        network not in {"ton-mainnet", "ton-testnet"}
        or not isinstance(address, str)
        or re.fullmatch(r"(?:0|-1):[0-9a-f]{64}", address) is None
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
        "address": address,
        "trust_level": trust_level,
        "timeout_seconds": timeout_seconds,
        "cache_directory": str(Path(cache_directory).expanduser().absolute()),
    }


def _validated_result(value: Any) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        _invalid_payload()
    return value


def _invalid_payload() -> None:
    raise TonWalletPublicKeyFailure(
        "Wallet public-key subprocess contract is invalid.",
        code="liteserver_ipc_invalid",
        retryable=False,
    )


def _deadline_seconds(timeout_seconds: int) -> float:
    return float(min(180, max(30, int(timeout_seconds) * 8)))


def _failure_message(code: str) -> str:
    if code == "liteserver_capture_timeout":
        return "Proof-checked wallet public-key resolution reached its deadline."
    if code == "liteserver_capture_cancelled":
        return "Proof-checked wallet public-key resolution was cancelled."
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
        return "Proof-checked wallet public-key input or evidence is invalid."
    return "Proof-checked wallet public-key resolution failed."


__all__ = [
    "TonWalletPublicKeyFailure",
    "resolve_wallet_public_key_live",
]
