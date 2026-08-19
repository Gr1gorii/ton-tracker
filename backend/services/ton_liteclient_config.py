"""Application-owned TON liteserver trust roots and bounded config loading."""

from __future__ import annotations

import base64
from dataclasses import dataclass
import ipaddress
import json
import struct
from typing import Any, Callable

import requests as http
from pytoniq import LiteBalancer

from services.ton_liteclient_strict_proof import StrictLiteClient


MAX_GLOBAL_CONFIG_BYTES = 512 * 1024
MAX_LITESERVERS = 64
CURRENT_VERIFIER_POLICY_ID = "ton_liteserver_checkpoint_strict_2026_08_v2"
LEGACY_CHECKPOINT_POLICY_ID = "ton_liteserver_checkpoint_2026_08_v1"
LEGACY_UNPINNED_POLICY_ID = "legacy_unpinned_v1"
_RETRYABLE_HTTP_STATUSES = frozenset({408, 425, 429})
_PASSTHROUGH_HTTP_STATUSES = _RETRYABLE_HTTP_STATUSES | frozenset(
    {500, 502, 503, 504}
)


class TonLiteclientConfigFailure(RuntimeError):
    """The official liteserver config could not be safely prepared."""

    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class TonLiteclientNetworkProfile:
    network: str
    config_url: str
    zero_state: dict[str, Any]
    trusted_checkpoint: dict[str, Any]
    verifier_policy_id: str = CURRENT_VERIFIER_POLICY_ID


@dataclass(frozen=True)
class PreparedTonLiteclient:
    client: Any
    verifier_policy_id: str
    trusted_checkpoint: dict[str, Any]


_MASTERCHAIN_SHARD = -9223372036854775808
_PROFILES = {
    "ton-mainnet": TonLiteclientNetworkProfile(
        network="ton-mainnet",
        config_url="https://ton.org/global-config.json",
        zero_state={
            "workchain": -1,
            "shard": _MASTERCHAIN_SHARD,
            "seqno": 0,
            "root_hash": "17a3a92992aabea785a7a090985a265cd31f323d849da51239737e321fb05569",
            "file_hash": "5e994fcf4d425c0a6ce6a792594b7173205f740a39cd56f537defd28b48a0f6e",
        },
        trusted_checkpoint={
            "workchain": -1,
            "shard": _MASTERCHAIN_SHARD,
            "seqno": 46894135,
            "root_hash": "3048e69a12cf946ebc99b4cf9ca61c3ff4b3fcc88c4015763ac01204ecc1bf9f",
            "file_hash": "bbdac0b4543e9141449ceb37c3c63ba6e9cc4e2c904d77f56d17e44acf1d1bed",
        },
    ),
    "ton-testnet": TonLiteclientNetworkProfile(
        network="ton-testnet",
        config_url="https://ton.org/testnet-global.config.json",
        zero_state={
            "workchain": -1,
            "shard": _MASTERCHAIN_SHARD,
            "seqno": 0,
            "root_hash": "823f81f306ff02694f935cf5021548e3ce2b86b529812af6a12148879e95a128",
            "file_hash": "67e20ac184b9e039a62667acc3f9c00f90f359a76738233379efa47604980ce8",
        },
        trusted_checkpoint={
            "workchain": -1,
            "shard": _MASTERCHAIN_SHARD,
            "seqno": 58834988,
            "root_hash": "8c711614c06a513e026dd1456f2f01a3b5b412f5a99ff1b050e23e9b103231d9",
            "file_hash": "898c25a4599a33bea0b442e80ec3877461eaac824b497ebbbc670f7d077925d7",
        },
    ),
}


def network_profile(network: str) -> TonLiteclientNetworkProfile:
    try:
        return _PROFILES[network]
    except (KeyError, TypeError) as exc:
        raise TonLiteclientConfigFailure(
            "TON liteserver verification requires a scoped TON network.",
            code="liteserver_network_invalid",
            retryable=False,
        ) from exc


def trusted_checkpoint_document(network: str) -> dict[str, Any]:
    return dict(network_profile(network).trusted_checkpoint)


def verifier_policy_id(network: str) -> str:
    return network_profile(network).verifier_policy_id


def is_current_trusted_checkpoint(
    network: str,
    policy_id: str,
    checkpoint: Any,
) -> bool:
    try:
        profile = network_profile(network)
    except TonLiteclientConfigFailure:
        return False
    return (
        policy_id == profile.verifier_policy_id
        and isinstance(checkpoint, dict)
        and checkpoint == profile.trusted_checkpoint
    )


def is_recognized_trusted_checkpoint(
    network: str,
    policy_id: str,
    checkpoint: Any,
) -> bool:
    """Recognize persisted pin metadata without granting current assurance."""
    try:
        profile = network_profile(network)
    except TonLiteclientConfigFailure:
        return False
    return (
        policy_id in {
            profile.verifier_policy_id,
            LEGACY_CHECKPOINT_POLICY_ID,
        }
        and isinstance(checkpoint, dict)
        and checkpoint == profile.trusted_checkpoint
    )


def load_pinned_liteclient_config(
    network: str,
    *,
    timeout_seconds: int,
    http_get: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    """Fetch, bound and validate an official config, then replace its trust root."""
    profile = network_profile(network)
    getter = http_get or http.get
    timeout = max(1.0, min(float(timeout_seconds), 10.0))
    response = None
    try:
        response = getter(
            profile.config_url,
            allow_redirects=False,
            stream=True,
            timeout=(min(timeout, 3.0), timeout),
            headers={"Accept": "application/json"},
        )
        status = int(getattr(response, "status_code", 0))
        if status != 200:
            retryable = status in _RETRYABLE_HTTP_STATUSES or 500 <= status <= 599
            raise TonLiteclientConfigFailure(
                "Official TON liteserver configuration is unavailable.",
                # Child IPC intentionally accepts a small, audited set of
                # machine-readable HTTP codes. Other statuses keep their
                # retryability but collapse to the safe config-domain code;
                # in particular, permanent redirects/4xx responses must not
                # be rewritten by the child envelope into a retryable error.
                code=(
                    f"http_{status}"
                    if status in _PASSTHROUGH_HTTP_STATUSES
                    else "liteserver_config_unavailable"
                ),
                retryable=retryable,
            )
        content_length = _content_length(getattr(response, "headers", {}))
        if content_length is not None and content_length > MAX_GLOBAL_CONFIG_BYTES:
            raise TonLiteclientConfigFailure(
                "Official TON liteserver configuration exceeds the safe size limit.",
                code="liteserver_config_too_large",
                retryable=False,
            )
        body = bytearray()
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not isinstance(chunk, bytes):
                raise TonLiteclientConfigFailure(
                    "Official TON liteserver configuration has an invalid response body.",
                    code="liteserver_config_invalid",
                    retryable=False,
                )
            body.extend(chunk)
            if len(body) > MAX_GLOBAL_CONFIG_BYTES:
                raise TonLiteclientConfigFailure(
                    "Official TON liteserver configuration exceeds the safe size limit.",
                    code="liteserver_config_too_large",
                    retryable=False,
                )
    except TonLiteclientConfigFailure:
        raise
    except (http.Timeout, http.ConnectionError) as exc:
        raise TonLiteclientConfigFailure(
            "Official TON liteserver configuration request timed out.",
            code="liteserver_config_timeout",
            retryable=True,
        ) from exc
    except http.RequestException as exc:
        raise TonLiteclientConfigFailure(
            "Official TON liteserver configuration is unavailable.",
            code="liteserver_config_unavailable",
            retryable=True,
        ) from exc
    except Exception as exc:
        raise TonLiteclientConfigFailure(
            "Official TON liteserver configuration could not be read safely.",
            code="liteserver_config_invalid",
            retryable=False,
        ) from exc
    finally:
        if response is not None:
            try:
                response.close()
            except Exception:
                pass
    try:
        document = json.loads(
            bytes(body).decode("utf-8"),
            parse_constant=lambda _value: (_ for _ in ()).throw(ValueError()),
        )
    except Exception as exc:
        raise TonLiteclientConfigFailure(
            "Official TON liteserver configuration is malformed.",
            code="liteserver_config_invalid",
            retryable=False,
        ) from exc
    return _validated_and_pinned_config(document, profile)


def prepare_pinned_liteclient(
    *,
    network: str,
    trust_level: int,
    timeout_seconds: int,
    http_get: Callable[..., Any] | None = None,
) -> PreparedTonLiteclient:
    if type(trust_level) is not int or trust_level not in {0, 1}:
        raise TonLiteclientConfigFailure(
            "TON liteserver trust level is invalid.",
            code="liteserver_trust_invalid",
            retryable=False,
        )
    config = load_pinned_liteclient_config(
        network,
        timeout_seconds=timeout_seconds,
        http_get=http_get,
    )
    profile = network_profile(network)
    try:
        peers = [
            StrictLiteClient.from_config(
                config,
                index,
                trust_level,
                timeout_seconds,
            )
            for index in range(len(config["liteservers"]))
        ]
        client = LiteBalancer(
            peers,
            timeout=timeout_seconds,
        )
        expected = profile.trusted_checkpoint
        prepared_peers = list(getattr(client, "_peers", ()))
        if not prepared_peers or any(
            not isinstance(peer, StrictLiteClient)
            or
            _block_id_document(getattr(peer, "init_key_block", None)) != expected
            for peer in prepared_peers
        ):
            raise ValueError("prepared client trust root mismatch")
    except Exception as exc:
        raise TonLiteclientConfigFailure(
            "TON liteserver client rejected the pinned application checkpoint.",
            code="liteserver_config_invalid",
            retryable=False,
        ) from exc
    return PreparedTonLiteclient(
        client=client,
        verifier_policy_id=profile.verifier_policy_id,
        trusted_checkpoint=dict(profile.trusted_checkpoint),
    )


def _validated_and_pinned_config(
    value: Any,
    profile: TonLiteclientNetworkProfile,
) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "@type", "dht", "liteservers", "validator"
    } or value.get("@type") != "config.global":
        _invalid_config()
    validator = value.get("validator")
    if not isinstance(validator, dict) or set(validator) != {
        "@type", "zero_state", "init_block", "hardforks"
    } or validator.get("@type") != "validator.config.global":
        _invalid_config()
    zero_state = _config_block(validator.get("zero_state"), allow_zero=True)
    if zero_state != profile.zero_state:
        raise TonLiteclientConfigFailure(
            "Official TON liteserver configuration belongs to another network.",
            code="liteserver_network_mismatch",
            retryable=False,
        )
    _config_block(validator.get("init_block"), allow_zero=False)
    hardforks = validator.get("hardforks")
    if not isinstance(hardforks, list) or len(hardforks) > 128:
        _invalid_config()
    for block in hardforks:
        _config_block(block, allow_zero=False)
    liteservers = value.get("liteservers")
    if not isinstance(liteservers, list) or not 1 <= len(liteservers) <= MAX_LITESERVERS:
        _invalid_config()
    safe_servers = [_liteserver(value) for value in liteservers]
    identities = {
        (row["ip"], row["port"], row["id"]["key"])
        for row in safe_servers
    }
    if len(identities) != len(safe_servers):
        _invalid_config()
    return {
        "liteservers": safe_servers,
        "validator": {
            "init_block": _config_form(profile.trusted_checkpoint),
        },
    }


def _liteserver(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or not {"ip", "port", "id"}.issubset(value):
        _invalid_config()
    if set(value) - {"ip", "port", "id", "provided"}:
        _invalid_config()
    ip = value.get("ip")
    port = value.get("port")
    identity = value.get("id")
    if (
        type(ip) is not int
        or not -(2**31) <= ip < 2**31
        or type(port) is not int
        or not 1 <= port <= 65535
        or not isinstance(identity, dict)
        or set(identity) != {"@type", "key"}
        or identity.get("@type") != "pub.ed25519"
    ):
        _invalid_config()
    try:
        address = ipaddress.ip_address(struct.pack(">i", ip))
    except Exception:
        _invalid_config()
    if not isinstance(address, ipaddress.IPv4Address) or not address.is_global:
        _invalid_config()
    _base64_hash(identity.get("key"))
    return {"ip": ip, "port": port, "id": dict(identity)}


def _config_block(value: Any, *, allow_zero: bool) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "workchain", "shard", "seqno", "root_hash", "file_hash"
    }:
        _invalid_config()
    workchain = value.get("workchain")
    shard = value.get("shard")
    seqno = value.get("seqno")
    if (
        type(workchain) is not int
        or workchain != -1
        or type(shard) is not int
        or shard != _MASTERCHAIN_SHARD
        or type(seqno) is not int
        or seqno < (0 if allow_zero else 1)
        or seqno > 2**31 - 1
    ):
        _invalid_config()
    return {
        "workchain": workchain,
        "shard": shard,
        "seqno": seqno,
        "root_hash": _base64_hash(value.get("root_hash")),
        "file_hash": _base64_hash(value.get("file_hash")),
    }


def _config_form(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "workchain": value["workchain"],
        "shard": value["shard"],
        "seqno": value["seqno"],
        "root_hash": base64.b64encode(bytes.fromhex(value["root_hash"])).decode("ascii"),
        "file_hash": base64.b64encode(bytes.fromhex(value["file_hash"])).decode("ascii"),
    }


def _base64_hash(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 64:
        _invalid_config()
    try:
        decoded = base64.b64decode(value, validate=True)
    except Exception:
        _invalid_config()
    if len(decoded) != 32 or base64.b64encode(decoded).decode("ascii") != value:
        _invalid_config()
    return decoded.hex()


def _block_id_document(value: Any) -> dict[str, Any] | None:
    try:
        return {
            "workchain": value.workchain,
            "shard": value.shard,
            "seqno": value.seqno,
            "root_hash": bytes(value.root_hash).hex(),
            "file_hash": bytes(value.file_hash).hex(),
        }
    except Exception:
        return None


def _content_length(headers: Any) -> int | None:
    try:
        value = headers.get("content-length") or headers.get("Content-Length")
    except Exception:
        return None
    if value in (None, ""):
        return None
    try:
        result = int(value)
    except (TypeError, ValueError):
        _invalid_config()
    if result < 0:
        _invalid_config()
    return result


def _invalid_config() -> None:
    raise TonLiteclientConfigFailure(
        "Official TON liteserver configuration is malformed.",
        code="liteserver_config_invalid",
        retryable=False,
    )


__all__ = [
    "CURRENT_VERIFIER_POLICY_ID",
    "LEGACY_CHECKPOINT_POLICY_ID",
    "LEGACY_UNPINNED_POLICY_ID",
    "MAX_GLOBAL_CONFIG_BYTES",
    "PreparedTonLiteclient",
    "TonLiteclientConfigFailure",
    "is_current_trusted_checkpoint",
    "is_recognized_trusted_checkpoint",
    "load_pinned_liteclient_config",
    "network_profile",
    "prepare_pinned_liteclient",
    "trusted_checkpoint_document",
    "verifier_policy_id",
]
