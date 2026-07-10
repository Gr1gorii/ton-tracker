"""Add canonical, network-scoped TON wallet identity evidence.

Revision ID: 20260710_0002
Revises: 20260710_0001
Create Date: 2026-07-10
"""

from __future__ import annotations

import base64
import binascii
import hmac
import re
from typing import Any

from alembic import op
import sqlalchemy as sa


revision = "20260710_0002"
down_revision = "20260710_0001"
branch_labels = None
depends_on = None


_BATCH_SIZE = 500
_IDENTITY_INDEX = "ix_wallet_ingestion_runs_wallet_identity"

_STATUS_SCOPED = "network_scoped"
_STATUS_UNSCOPED = "unscoped"
_STATUS_UNAVAILABLE = "unavailable"

_VERSION_STD = "ton_std_address_v1"
_VERSION_RAW = "ton_raw_address_v1"
_VERSION_UNAVAILABLE = "unavailable"

_NETWORK_MAINNET = "ton-mainnet"
_NETWORK_TESTNET = "ton-testnet"
_NETWORK_UNKNOWN = "ton-unknown"

_FORMAT_FRIENDLY = "user_friendly"
_FORMAT_RAW = "raw"
_FORMAT_UNRECOGNIZED = "unrecognized"

_RAW_ADDRESS_RE = re.compile(
    r"^((?:0|[1-9][0-9]*|-[1-9][0-9]*)):([0-9a-fA-F]{64})$"
)
_STANDARD_FRIENDLY_RE = re.compile(r"^[A-Za-z0-9+/]{48}$")
_URLSAFE_FRIENDLY_RE = re.compile(r"^[A-Za-z0-9_-]{48}$")
_MIN_WORKCHAIN = -(2**31)
_MAX_WORKCHAIN = 2**31 - 1


class _Identity:
    __slots__ = (
        "status",
        "version",
        "network",
        "canonical_address",
        "workchain_id",
        "account_id_hex",
        "submitted_format",
        "bounceable",
        "testnet_only",
    )

    def __init__(
        self,
        *,
        status: str,
        version: str,
        network: str,
        canonical_address: str | None,
        workchain_id: int | None,
        account_id_hex: str | None,
        submitted_format: str,
        bounceable: bool | None,
        testnet_only: bool | None,
    ) -> None:
        self.status = status
        self.version = version
        self.network = network
        self.canonical_address = canonical_address
        self.workchain_id = workchain_id
        self.account_id_hex = account_id_hex
        self.submitted_format = submitted_format
        self.bounceable = bounceable
        self.testnet_only = testnet_only


def _identity_columns() -> tuple[sa.Column, ...]:
    """Return fresh column objects for restart-safe additive migration work."""
    return (
        sa.Column(
            "wallet_identity_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unavailable'"),
        ),
        sa.Column(
            "wallet_identity_version",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'unavailable'"),
        ),
        sa.Column(
            "wallet_network",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'ton-unknown'"),
        ),
        sa.Column(
            "wallet_address_canonical",
            sa.String(length=76),
            nullable=True,
        ),
        sa.Column("wallet_workchain_id", sa.Integer(), nullable=True),
        sa.Column(
            "wallet_account_id_hex",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "wallet_address_format",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'unrecognized'"),
        ),
        sa.Column("wallet_address_bounceable", sa.Boolean(), nullable=True),
        sa.Column("wallet_address_testnet_only", sa.Boolean(), nullable=True),
    )


def _type_signature(value: Any) -> str:
    return "".join(str(value).upper().split())


def _default_signature(value: Any) -> str | None:
    if value is None:
        return None
    return "".join(str(value).split())


def _expected_default(column: sa.Column) -> str | None:
    if column.server_default is None:
        return None
    return _default_signature(column.server_default.arg)


def _column_signature(column: dict[str, Any]) -> tuple[str, str, bool, str | None]:
    return (
        str(column.get("name")),
        _type_signature(column.get("type")),
        bool(column.get("nullable")),
        _default_signature(column.get("default")),
    )


def _expected_column_signature(
    column: sa.Column,
) -> tuple[str, str, bool, str | None]:
    return (
        str(column.name),
        _type_signature(column.type),
        bool(column.nullable),
        _expected_default(column),
    )


def _assert_existing_identity_columns(
    reflected: dict[str, dict[str, Any]],
    expected: tuple[sa.Column, ...],
) -> None:
    mismatches = []
    for column in expected:
        actual = reflected.get(str(column.name))
        if actual is None:
            continue
        expected_signature = _expected_column_signature(column)
        actual_signature = _column_signature(actual)
        if actual_signature != expected_signature:
            mismatches.append(
                f"{column.name}: expected={expected_signature}, "
                f"actual={actual_signature}"
            )
    if mismatches:
        raise RuntimeError(
            "Existing wallet identity columns do not match revision 0002: "
            + "; ".join(mismatches)
        )


def _ensure_identity_columns() -> None:
    """Add missing columns and validate any left by an interrupted attempt."""
    connection = op.get_bind()
    expected = _identity_columns()
    reflected = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns("wallet_ingestion_runs")
    }

    # Validate every already-present column before making any further DDL change.
    _assert_existing_identity_columns(reflected, expected)
    for column in expected:
        if column.name not in reflected:
            op.add_column("wallet_ingestion_runs", column)

    refreshed = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns("wallet_ingestion_runs")
    }
    missing = [column.name for column in expected if column.name not in refreshed]
    if missing:
        raise RuntimeError(
            f"Wallet identity migration did not add expected columns: {missing}."
        )
    _assert_existing_identity_columns(refreshed, expected)


def _ensure_identity_index() -> None:
    connection = op.get_bind()
    expected = (_IDENTITY_INDEX, ("wallet_network", "wallet_address_canonical"), False)
    indexes = {
        index["name"]: (
            index["name"],
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
        )
        for index in sa.inspect(connection).get_indexes("wallet_ingestion_runs")
    }
    actual = indexes.get(_IDENTITY_INDEX)
    if actual is not None and actual != expected:
        raise RuntimeError(
            "Existing wallet identity index does not match revision 0002: "
            f"expected={expected}, actual={actual}."
        )
    if actual is None:
        op.create_index(
            _IDENTITY_INDEX,
            "wallet_ingestion_runs",
            ["wallet_network", "wallet_address_canonical"],
            unique=False,
        )

    refreshed = {
        index["name"]: (
            index["name"],
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
        )
        for index in sa.inspect(connection).get_indexes("wallet_ingestion_runs")
    }
    if refreshed.get(_IDENTITY_INDEX) != expected:
        raise RuntimeError(
            "Wallet identity migration did not create the expected index: "
            f"expected={expected}, actual={refreshed.get(_IDENTITY_INDEX)}."
        )


def _unavailable_identity() -> _Identity:
    return _Identity(
        status=_STATUS_UNAVAILABLE,
        version=_VERSION_UNAVAILABLE,
        network=_NETWORK_UNKNOWN,
        canonical_address=None,
        workchain_id=None,
        account_id_hex=None,
        submitted_format=_FORMAT_UNRECOGNIZED,
        bounceable=None,
        testnet_only=None,
    )


def _parse_raw(value: str) -> _Identity | None:
    match = _RAW_ADDRESS_RE.fullmatch(value)
    if match is None:
        return None
    try:
        workchain_id = int(match.group(1), 10)
    except ValueError:
        return None
    if not _MIN_WORKCHAIN <= workchain_id <= _MAX_WORKCHAIN:
        return None

    account_id_hex = match.group(2).lower()
    return _Identity(
        status=_STATUS_UNSCOPED,
        version=_VERSION_RAW,
        network=_NETWORK_UNKNOWN,
        canonical_address=f"{workchain_id}:{account_id_hex}",
        workchain_id=workchain_id,
        account_id_hex=account_id_hex,
        submitted_format=_FORMAT_RAW,
        bounceable=None,
        testnet_only=None,
    )


def _decode_friendly(value: str) -> bytes | None:
    if len(value) != 48:
        return None
    if _STANDARD_FRIENDLY_RE.fullmatch(value):
        altchars = None
    elif _URLSAFE_FRIENDLY_RE.fullmatch(value):
        altchars = b"-_"
    else:
        return None
    try:
        decoded = base64.b64decode(
            value.encode("ascii"),
            altchars=altchars,
            validate=True,
        )
    except (UnicodeEncodeError, binascii.Error, ValueError):
        return None
    return decoded if len(decoded) == 36 else None


def _parse_friendly(value: str) -> _Identity | None:
    decoded = _decode_friendly(value)
    if decoded is None:
        return None

    payload = decoded[:34]
    expected_checksum = binascii.crc_hqx(payload, 0).to_bytes(2, "big")
    if not hmac.compare_digest(decoded[34:], expected_checksum):
        return None

    tag = payload[0]
    if tag & 0x3F != 0x11:
        return None
    testnet_only = bool(tag & 0x80)
    bounceable = not bool(tag & 0x40)
    workchain_id = int.from_bytes(payload[1:2], "big", signed=True)
    account_id_hex = payload[2:34].hex()
    network = _NETWORK_TESTNET if testnet_only else _NETWORK_MAINNET
    return _Identity(
        status=_STATUS_SCOPED,
        version=_VERSION_STD,
        network=network,
        canonical_address=f"{workchain_id}:{account_id_hex}",
        workchain_id=workchain_id,
        account_id_hex=account_id_hex,
        submitted_format=_FORMAT_FRIENDLY,
        bounceable=bounceable,
        testnet_only=testnet_only,
    )


def _derive_identity(value: Any) -> _Identity:
    if not isinstance(value, str) or not value or value != value.strip():
        return _unavailable_identity()
    return _parse_raw(value) or _parse_friendly(value) or _unavailable_identity()


def _wallet_runs_table() -> sa.TableClause:
    return sa.table(
        "wallet_ingestion_runs",
        sa.column("id", sa.Integer()),
        sa.column("wallet_address", sa.String()),
        sa.column("wallet_identity_status", sa.String()),
        sa.column("wallet_identity_version", sa.String()),
        sa.column("wallet_network", sa.String()),
        sa.column("wallet_address_canonical", sa.String()),
        sa.column("wallet_workchain_id", sa.Integer()),
        sa.column("wallet_account_id_hex", sa.String()),
        sa.column("wallet_address_format", sa.String()),
        sa.column("wallet_address_bounceable", sa.Boolean()),
        sa.column("wallet_address_testnet_only", sa.Boolean()),
    )


def _backfill_wallet_identities() -> None:
    connection = op.get_bind()
    wallet_runs = _wallet_runs_table()
    last_id: int | None = None

    while True:
        query = (
            sa.select(wallet_runs.c.id, wallet_runs.c.wallet_address)
            .order_by(wallet_runs.c.id)
            .limit(_BATCH_SIZE)
        )
        if last_id is not None:
            query = query.where(wallet_runs.c.id > last_id)
        rows = connection.execute(query).mappings().all()
        if not rows:
            break

        updates: list[dict[str, Any]] = []
        for row in rows:
            identity = _derive_identity(row["wallet_address"])
            updates.append(
                {
                    "target_run_id": row["id"],
                    "wallet_identity_status": identity.status,
                    "wallet_identity_version": identity.version,
                    "wallet_network": identity.network,
                    "wallet_address_canonical": identity.canonical_address,
                    "wallet_workchain_id": identity.workchain_id,
                    "wallet_account_id_hex": identity.account_id_hex,
                    "wallet_address_format": identity.submitted_format,
                    "wallet_address_bounceable": identity.bounceable,
                    "wallet_address_testnet_only": identity.testnet_only,
                }
            )

        update = (
            wallet_runs.update()
            .where(wallet_runs.c.id == sa.bindparam("target_run_id"))
            .values(
                wallet_identity_status=sa.bindparam("wallet_identity_status"),
                wallet_identity_version=sa.bindparam("wallet_identity_version"),
                wallet_network=sa.bindparam("wallet_network"),
                wallet_address_canonical=sa.bindparam("wallet_address_canonical"),
                wallet_workchain_id=sa.bindparam("wallet_workchain_id"),
                wallet_account_id_hex=sa.bindparam("wallet_account_id_hex"),
                wallet_address_format=sa.bindparam("wallet_address_format"),
                wallet_address_bounceable=sa.bindparam(
                    "wallet_address_bounceable"
                ),
                wallet_address_testnet_only=sa.bindparam(
                    "wallet_address_testnet_only"
                ),
            )
        )
        connection.execute(update, updates)
        last_id = int(rows[-1]["id"])


def _assert_backfill_postconditions() -> None:
    connection = op.get_bind()
    wallet_runs = _wallet_runs_table()

    scoped = sa.and_(
        wallet_runs.c.wallet_identity_status == _STATUS_SCOPED,
        wallet_runs.c.wallet_identity_version == _VERSION_STD,
        wallet_runs.c.wallet_network.in_((_NETWORK_MAINNET, _NETWORK_TESTNET)),
        wallet_runs.c.wallet_address_canonical.is_not(None),
        wallet_runs.c.wallet_workchain_id.is_not(None),
        wallet_runs.c.wallet_account_id_hex.is_not(None),
        wallet_runs.c.wallet_address_format == _FORMAT_FRIENDLY,
        wallet_runs.c.wallet_address_bounceable.is_not(None),
        wallet_runs.c.wallet_address_testnet_only.is_not(None),
        sa.or_(
            sa.and_(
                wallet_runs.c.wallet_network == _NETWORK_MAINNET,
                wallet_runs.c.wallet_address_testnet_only.is_(False),
            ),
            sa.and_(
                wallet_runs.c.wallet_network == _NETWORK_TESTNET,
                wallet_runs.c.wallet_address_testnet_only.is_(True),
            ),
        ),
    )
    unscoped = sa.and_(
        wallet_runs.c.wallet_identity_status == _STATUS_UNSCOPED,
        wallet_runs.c.wallet_identity_version == _VERSION_RAW,
        wallet_runs.c.wallet_network == _NETWORK_UNKNOWN,
        wallet_runs.c.wallet_address_canonical.is_not(None),
        wallet_runs.c.wallet_workchain_id.is_not(None),
        wallet_runs.c.wallet_account_id_hex.is_not(None),
        wallet_runs.c.wallet_address_format == _FORMAT_RAW,
        wallet_runs.c.wallet_address_bounceable.is_(None),
        wallet_runs.c.wallet_address_testnet_only.is_(None),
    )
    unavailable = sa.and_(
        wallet_runs.c.wallet_identity_status == _STATUS_UNAVAILABLE,
        wallet_runs.c.wallet_identity_version == _VERSION_UNAVAILABLE,
        wallet_runs.c.wallet_network == _NETWORK_UNKNOWN,
        wallet_runs.c.wallet_address_canonical.is_(None),
        wallet_runs.c.wallet_workchain_id.is_(None),
        wallet_runs.c.wallet_account_id_hex.is_(None),
        wallet_runs.c.wallet_address_format == _FORMAT_UNRECOGNIZED,
        wallet_runs.c.wallet_address_bounceable.is_(None),
        wallet_runs.c.wallet_address_testnet_only.is_(None),
    )
    invalid_count = connection.scalar(
        sa.select(sa.func.count())
        .select_from(wallet_runs)
        .where(sa.not_(sa.or_(scoped, unscoped, unavailable)))
    )
    if invalid_count:
        raise RuntimeError(
            "Wallet identity backfill produced "
            f"{invalid_count} inconsistent row(s)."
        )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Wallet identity backfill requires an online database connection; "
            "offline SQL generation is intentionally unsupported for this revision."
        )

    # SQLite DDL is non-transactional under Alembic. These guards make an
    # interrupted revision safe to retry from its still-recorded 0001 marker.
    _ensure_identity_columns()
    _backfill_wallet_identities()
    _assert_backfill_postconditions()
    _ensure_identity_index()


def downgrade() -> None:
    raise RuntimeError(
        "Wallet identity downgrade would discard derived identity evidence and "
        "is intentionally unsupported. Restore a verified backup instead."
    )
