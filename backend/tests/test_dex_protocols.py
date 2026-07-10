"""Canonical DEX protocol identity coverage."""

import pytest

from services.dex_protocols import (
    SUPPORTED_DEX_PROTOCOL_IDS,
    classify_dex_protocol,
)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("STON.fi", "stonfi_v1"),
        ("STON.fi V2", "stonfi_v2"),
        ("DeDust", "dedust"),
        ("DeDust V3", "dedust_v3"),
        ("DeDust V3 Memepad", "dedust_v3_memepad"),
        ("TONCO", "tonco"),
        ("MemesLab", "memeslab"),
        ("TON.fun", "tonfun"),
    ],
)
def test_supported_dex_aliases_are_canonical(label, expected):
    identity = classify_dex_protocol(label)
    assert identity["status"] == "recognized"
    assert identity["protocol_id"] == expected
    assert expected in SUPPORTED_DEX_PROTOCOL_IDS


def test_unknown_and_missing_dex_labels_are_not_promoted():
    unknown = classify_dex_protocol("FutureSwap")
    assert unknown == {
        "status": "unknown",
        "protocol_id": None,
        "family": None,
        "version": None,
        "provider_label": "FutureSwap",
    }
    assert classify_dex_protocol(None)["status"] == "missing"
