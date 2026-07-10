"""Canonical DEX protocol classification for provider swap observations."""

from __future__ import annotations

import re
from typing import Any, Literal, TypedDict


class DexProtocolIdentity(TypedDict):
    status: Literal["recognized", "unknown", "missing"]
    protocol_id: str | None
    family: str | None
    version: str | None
    provider_label: str | None


_ALIASES = {
    "stonfi": ("stonfi_v1", "stonfi", "v1"),
    "stonfiv1": ("stonfi_v1", "stonfi", "v1"),
    "stonfiv2": ("stonfi_v2", "stonfi", "v2"),
    "dedust": ("dedust", "dedust", "v2"),
    "dedustv2": ("dedust", "dedust", "v2"),
    "dedustv3": ("dedust_v3", "dedust", "v3"),
    "dedustv3memepad": ("dedust_v3_memepad", "dedust", "v3-memepad"),
    "tonco": ("tonco", "tonco", None),
    "memeslab": ("memeslab", "memeslab", None),
    "tonfun": ("tonfun", "tonfun", None),
}


SUPPORTED_DEX_PROTOCOL_IDS = tuple(
    sorted({value[0] for value in _ALIASES.values()})
)


def classify_dex_protocol(value: Any) -> DexProtocolIdentity:
    label = _clean(value)
    if label is None:
        return {
            "status": "missing",
            "protocol_id": None,
            "family": None,
            "version": None,
            "provider_label": None,
        }
    key = re.sub(r"[^a-z0-9]", "", label.lower())
    match = _ALIASES.get(key)
    if match is None:
        return {
            "status": "unknown",
            "protocol_id": None,
            "family": None,
            "version": None,
            "provider_label": label,
        }
    protocol_id, family, version = match
    return {
        "status": "recognized",
        "protocol_id": protocol_id,
        "family": family,
        "version": version,
        "provider_label": label,
    }


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned[:128] if cleaned else None


__all__ = ["SUPPORTED_DEX_PROTOCOL_IDS", "classify_dex_protocol"]
