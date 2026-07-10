"""Strict vector tests for canonical TON standard-address identity parsing."""

from __future__ import annotations

import pytest

from services.ton_address_identity import (
    TON_IDENTITY_VERSION_RAW,
    TON_IDENTITY_VERSION_STD,
    TON_IDENTITY_VERSION_UNAVAILABLE,
    derive_ton_wallet_identity,
    parse_ton_address,
    unavailable_ton_identity,
)


ACCOUNT_ID = "ca6e321c7cce9ecedf0a8ca2492ec8592494aa5fb5ce0387dff96ef6af982a3e"
RAW = f"0:{ACCOUNT_ID}"
RAW_UPPER = f"0:{ACCOUNT_ID.upper()}"

BOUNCEABLE_MAINNET_URLSAFE = (
    "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHF"
)
NON_BOUNCEABLE_MAINNET_URLSAFE = (
    "UQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPuwA"
)
BOUNCEABLE_MAINNET_STANDARD = (
    "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff+W72r5gqPrHF"
)
BOUNCEABLE_TESTNET = "kQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPgpP"
NON_BOUNCEABLE_TESTNET = (
    "0QDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPleK"
)

MASTERCHAIN_BOUNCEABLE = (
    "Ef9Tj6fMJP-OqhAdhKXxq36DL-HYSzCc3-9O6UNzqsgPfYFX"
)
MASTERCHAIN_ACCOUNT_ID = (
    "538fa7cc24ff8eaa101d84a5f1ab7e832fe1d84b309cdfef4ee94373aac80f7d"
)


def _identity_key(identity):
    return identity.network, identity.workchain_id, identity.account_id_hex


@pytest.mark.parametrize(
    ("value", "bounceable"),
    [
        (BOUNCEABLE_MAINNET_URLSAFE, True),
        (NON_BOUNCEABLE_MAINNET_URLSAFE, False),
        (BOUNCEABLE_MAINNET_STANDARD, True),
    ],
)
def test_official_mainnet_friendly_vectors_parse_to_one_identity(
    value,
    bounceable,
):
    identity = parse_ton_address(value)

    assert identity is not None
    assert identity.status == "network_scoped"
    assert identity.version == TON_IDENTITY_VERSION_STD
    assert identity.network == "ton-mainnet"
    assert identity.canonical_address == RAW
    assert identity.workchain_id == 0
    assert identity.account_id_hex == ACCOUNT_ID
    assert identity.submitted_format == "user_friendly"
    assert identity.bounceable is bounceable
    assert identity.testnet_only is False
    assert identity.scoped_key == ("ton-mainnet", RAW)


def test_bounce_nonbounce_urlsafe_and_standard_forms_are_equivalent():
    identities = [
        parse_ton_address(BOUNCEABLE_MAINNET_URLSAFE),
        parse_ton_address(NON_BOUNCEABLE_MAINNET_URLSAFE),
        parse_ton_address(BOUNCEABLE_MAINNET_STANDARD),
    ]

    assert all(identity is not None for identity in identities)
    assert {_identity_key(identity) for identity in identities} == {
        ("ton-mainnet", 0, ACCOUNT_ID)
    }
    assert {identity.canonical_address for identity in identities} == {RAW}
    assert {identity.scoped_key for identity in identities} == {
        ("ton-mainnet", RAW)
    }
    assert {identity.bounceable for identity in identities} == {True, False}


def test_official_masterchain_vector_decodes_signed_workchain():
    identity = parse_ton_address(MASTERCHAIN_BOUNCEABLE)

    assert identity is not None
    assert identity.status == "network_scoped"
    assert identity.network == "ton-mainnet"
    assert identity.workchain_id == -1
    assert identity.account_id_hex == MASTERCHAIN_ACCOUNT_ID
    assert identity.canonical_address == f"-1:{MASTERCHAIN_ACCOUNT_ID}"
    assert identity.bounceable is True
    assert identity.testnet_only is False


@pytest.mark.parametrize(
    ("value", "bounceable"),
    [
        (BOUNCEABLE_TESTNET, True),
        (NON_BOUNCEABLE_TESTNET, False),
    ],
)
def test_official_testnet_vectors_preserve_network_and_flags(value, bounceable):
    identity = parse_ton_address(value)

    assert identity is not None
    assert identity.status == "network_scoped"
    assert identity.version == TON_IDENTITY_VERSION_STD
    assert identity.network == "ton-testnet"
    assert identity.canonical_address == RAW
    assert identity.workchain_id == 0
    assert identity.account_id_hex == ACCOUNT_ID
    assert identity.bounceable is bounceable
    assert identity.testnet_only is True
    assert identity.scoped_key == ("ton-testnet", RAW)


def test_raw_uppercase_hex_is_accepted_and_canonicalized_to_lowercase():
    identity = parse_ton_address(RAW_UPPER)

    assert identity is not None
    assert identity.status == "unscoped"
    assert identity.version == TON_IDENTITY_VERSION_RAW
    assert identity.network == "ton-unknown"
    assert identity.canonical_address == RAW
    assert identity.workchain_id == 0
    assert identity.account_id_hex == ACCOUNT_ID
    assert identity.submitted_format == "raw"
    assert identity.bounceable is None
    assert identity.testnet_only is None
    assert identity.scoped_key is None


@pytest.mark.parametrize(
    ("workchain", "expected"),
    [
        (-(2**31), -(2**31)),
        (-1, -1),
        (0, 0),
        (2**31 - 1, 2**31 - 1),
    ],
)
def test_raw_format_accepts_full_signed_int32_workchain_range(workchain, expected):
    identity = parse_ton_address(f"{workchain}:{ACCOUNT_ID}")

    assert identity is not None
    assert identity.status == "unscoped"
    assert identity.workchain_id == expected
    assert identity.canonical_address == f"{expected}:{ACCOUNT_ID}"


def test_raw_network_context_scopes_identity_without_changing_address():
    unscoped = derive_ton_wallet_identity(RAW)
    mainnet = derive_ton_wallet_identity(RAW, network_context="ton-mainnet")
    testnet = derive_ton_wallet_identity(RAW, network_context="ton-testnet")

    assert unscoped.status == "unscoped"
    assert unscoped.network == "ton-unknown"
    assert unscoped.scoped_key is None
    assert mainnet.status == "network_scoped"
    assert mainnet.network == "ton-mainnet"
    assert mainnet.canonical_address == RAW
    assert mainnet.scoped_key == ("ton-mainnet", RAW)
    assert testnet.status == "network_scoped"
    assert testnet.network == "ton-testnet"
    assert testnet.canonical_address == RAW
    assert testnet.scoped_key == ("ton-testnet", RAW)
    assert mainnet.scoped_key != testnet.scoped_key


def test_friendly_embedded_network_is_not_overridden_by_network_context():
    identity = derive_ton_wallet_identity(
        BOUNCEABLE_TESTNET,
        network_context="ton-mainnet",
    )

    assert identity.status == "network_scoped"
    assert identity.network == "ton-testnet"
    assert identity.testnet_only is True
    assert identity.scoped_key == ("ton-testnet", RAW)


@pytest.mark.parametrize(
    "value",
    [
        # Valid shape/tag with one checksum character changed.
        "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHG",
        # Correct CRC for an unsupported 0x31 tag.
        "MQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPhc3",
        BOUNCEABLE_MAINNET_URLSAFE[:-1],
        BOUNCEABLE_MAINNET_URLSAFE + "A",
        BOUNCEABLE_MAINNET_URLSAFE[:10] + "%" + BOUNCEABLE_MAINNET_URLSAFE[11:],
        BOUNCEABLE_MAINNET_URLSAFE[:10] + "é" + BOUNCEABLE_MAINNET_URLSAFE[11:],
        # Standard '+' and URL-safe '_' alphabets must not be mixed.
        BOUNCEABLE_MAINNET_STANDARD[:-1] + "_",
        # Padding/autocorrection is intentionally unsupported, even at length 48.
        BOUNCEABLE_MAINNET_URLSAFE[:-1] + "=",
        " " + BOUNCEABLE_MAINNET_URLSAFE,
        BOUNCEABLE_MAINNET_URLSAFE + " ",
        BOUNCEABLE_MAINNET_URLSAFE[:24] + " " + BOUNCEABLE_MAINNET_URLSAFE[25:],
        "\t" + BOUNCEABLE_MAINNET_URLSAFE,
        "\n" + BOUNCEABLE_MAINNET_URLSAFE,
    ],
)
def test_invalid_friendly_forms_are_rejected_without_correction(value):
    assert parse_ton_address(value) is None


@pytest.mark.parametrize(
    "value",
    [
        f"-0:{ACCOUNT_ID}",
        f"+0:{ACCOUNT_ID}",
        f"00:{ACCOUNT_ID}",
        f"01:{ACCOUNT_ID}",
        f"{2**31}:{ACCOUNT_ID}",
        f"{-(2**31) - 1}:{ACCOUNT_ID}",
        f"0:{ACCOUNT_ID[:-1]}",
        f"0:{ACCOUNT_ID}0",
        f"0:{ACCOUNT_ID[:-1]}g",
        f"0 {ACCOUNT_ID}",
        f" 0:{ACCOUNT_ID}",
        f"0:{ACCOUNT_ID} ",
        f"0:{ACCOUNT_ID[:32]} {ACCOUNT_ID[32:]}",
    ],
)
def test_invalid_raw_forms_and_workchain_overflow_are_rejected(value):
    assert parse_ton_address(value) is None


@pytest.mark.parametrize("value", [None, b"", b"address", 0, 1.5, [], {}])
def test_non_string_inputs_are_rejected(value):
    assert parse_ton_address(value) is None


def test_unavailable_identity_record_is_explicit_and_public():
    unavailable = unavailable_ton_identity()

    assert unavailable.status == "unavailable"
    assert unavailable.version == TON_IDENTITY_VERSION_UNAVAILABLE
    assert unavailable.network == "ton-unknown"
    assert unavailable.canonical_address is None
    assert unavailable.workchain_id is None
    assert unavailable.account_id_hex is None
    assert unavailable.submitted_format == "unrecognized"
    assert unavailable.bounceable is None
    assert unavailable.testnet_only is None
    assert unavailable.scoped_key is None
    assert unavailable.to_public_dict() == {
        "status": "unavailable",
        "version": TON_IDENTITY_VERSION_UNAVAILABLE,
        "network": "ton-unknown",
        "canonical_address": None,
        "workchain_id": None,
        "account_id_hex": None,
        "submitted_format": "unrecognized",
        "bounceable": None,
        "testnet_only": None,
    }


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-ton-address",
        " " + RAW,
        "EQDKbjIcfM6ezt8KjKJJLshZJJSqX7XOA4ff-W72r5gqPrHG",
        None,
    ],
)
def test_derive_returns_unavailable_record_for_every_invalid_input(value):
    identity = derive_ton_wallet_identity(
        value,
        network_context="ton-mainnet",
    )

    assert identity == unavailable_ton_identity()
