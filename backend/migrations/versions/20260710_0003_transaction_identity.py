"""Add strict network-scoped TON account-transaction identity.

Revision ID: 20260710_0003
Revises: 20260710_0002
Create Date: 2026-07-10
"""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple

from alembic import op
import sqlalchemy as sa


revision = "20260710_0003"
down_revision = "20260710_0002"
branch_labels = None
depends_on = None


_BATCH_SIZE = 500

_STATUS_SCOPED = "network_scoped"
_STATUS_UNAVAILABLE = "unavailable"

_VERSION_SCOPED = "ton_account_tx_v1"
_VERSION_UNAVAILABLE = "unavailable"
_WALLET_IDENTITY_VERSIONS = ("ton_std_address_v1", "ton_raw_address_v1")

_NETWORK_MAINNET = "ton-mainnet"
_NETWORK_TESTNET = "ton-testnet"
_NETWORK_UNKNOWN = "ton-unknown"

_TRANSACTION_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_LOGICAL_TIME_RE = re.compile(r"^[1-9][0-9]{0,19}$")
_RAW_ACCOUNT_RE = re.compile(
    r"^((?:0|[1-9][0-9]*|-[1-9][0-9]*)):([0-9a-f]{64})$"
)
_MAX_LOGICAL_TIME = 2**64 - 1
_MIN_WORKCHAIN = -(2**31)
_MAX_WORKCHAIN = 2**31 - 1

_IDENTITY_INDEXES = (
    (
        "uq_wallet_transactions_run_identity",
        ("run_id", "transaction_identity_key"),
        True,
    ),
    (
        "ix_wallet_transactions_identity_key",
        ("transaction_identity_key",),
        False,
    ),
    (
        "ix_wallet_transactions_identity_tuple",
        (
            "transaction_network",
            "transaction_account_canonical",
            "transaction_logical_time_canonical",
            "transaction_hash_canonical",
        ),
        False,
    ),
)


class _Identity(NamedTuple):
    status: str
    version: str
    network: str
    account_canonical: str | None
    logical_time_canonical: str | None
    hash_canonical: str | None
    key: str | None


def _identity_columns() -> tuple[sa.Column, ...]:
    """Return fresh columns for restart-safe non-transactional SQLite DDL."""
    return (
        sa.Column(
            "transaction_identity_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unavailable'"),
        ),
        sa.Column(
            "transaction_identity_version",
            sa.String(length=24),
            nullable=False,
            server_default=sa.text("'unavailable'"),
        ),
        sa.Column(
            "transaction_network",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'ton-unknown'"),
        ),
        sa.Column(
            "transaction_account_canonical",
            sa.String(length=76),
            nullable=True,
        ),
        sa.Column(
            "transaction_logical_time_canonical",
            sa.String(length=20),
            nullable=True,
        ),
        sa.Column(
            "transaction_hash_canonical",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "transaction_identity_key",
            sa.String(length=192),
            nullable=True,
        ),
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
            "Existing transaction identity columns do not match revision 0003: "
            + "; ".join(mismatches)
        )


def _ensure_identity_columns() -> None:
    connection = op.get_bind()
    expected = _identity_columns()
    reflected = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns("wallet_transactions")
    }

    # Validate every existing column before making any further DDL change.
    _assert_existing_identity_columns(reflected, expected)
    for column in expected:
        if column.name not in reflected:
            op.add_column("wallet_transactions", column)

    refreshed = {
        column["name"]: column
        for column in sa.inspect(connection).get_columns("wallet_transactions")
    }
    missing = [column.name for column in expected if column.name not in refreshed]
    if missing:
        raise RuntimeError(
            "Transaction identity migration did not add expected columns: "
            f"{missing}."
        )
    _assert_existing_identity_columns(refreshed, expected)


def _unavailable_identity() -> _Identity:
    return _Identity(
        status=_STATUS_UNAVAILABLE,
        version=_VERSION_UNAVAILABLE,
        network=_NETWORK_UNKNOWN,
        account_canonical=None,
        logical_time_canonical=None,
        hash_canonical=None,
        key=None,
    )


def _canonical_account(row: dict[str, Any]) -> str | None:
    if row.get("wallet_identity_status") != _STATUS_SCOPED:
        return None
    if row.get("wallet_identity_version") not in _WALLET_IDENTITY_VERSIONS:
        return None
    network = row.get("wallet_network")
    if network not in (_NETWORK_MAINNET, _NETWORK_TESTNET):
        return None
    value = row.get("wallet_address_canonical")
    if not isinstance(value, str):
        return None
    match = _RAW_ACCOUNT_RE.fullmatch(value)
    if match is None:
        return None
    try:
        workchain_id = int(match.group(1), 10)
    except ValueError:
        return None
    if not _MIN_WORKCHAIN <= workchain_id <= _MAX_WORKCHAIN:
        return None
    account_id_hex = match.group(2)
    if value != f"{workchain_id}:{account_id_hex}":
        return None
    if row.get("wallet_workchain_id") != workchain_id:
        return None
    if row.get("wallet_account_id_hex") != account_id_hex:
        return None
    return value


def _canonical_logical_time(value: Any) -> str | None:
    if not isinstance(value, str) or _LOGICAL_TIME_RE.fullmatch(value) is None:
        return None
    parsed = int(value, 10)
    if parsed > _MAX_LOGICAL_TIME:
        return None
    return value


def _canonical_hash(value: Any) -> str | None:
    if not isinstance(value, str) or _TRANSACTION_HASH_RE.fullmatch(value) is None:
        return None
    return value.lower()


def _raw_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _derive_identity(row: dict[str, Any]) -> _Identity:
    if row.get("data_mode") != "real":
        return _unavailable_identity()
    if row.get("provider") != "tonapi" or row.get("source_status") != "live":
        return _unavailable_identity()

    transaction_hash = row.get("tx_hash")
    logical_time = row.get("logical_time")
    raw = _raw_payload(row.get("raw_json"))
    if raw is None:
        return _unavailable_identity()
    if raw.get("provider") != "tonapi" or raw.get("surface") != "transactions":
        return _unavailable_identity()
    if raw.get("tx_hash") != transaction_hash:
        return _unavailable_identity()
    if raw.get("logical_time") != logical_time:
        return _unavailable_identity()

    account = _canonical_account(row)
    canonical_lt = _canonical_logical_time(logical_time)
    canonical_hash = _canonical_hash(transaction_hash)
    network = row.get("wallet_network")
    if account is None or canonical_lt is None or canonical_hash is None:
        return _unavailable_identity()

    key = "|".join(
        (
            _VERSION_SCOPED,
            network,
            account,
            canonical_lt,
            canonical_hash,
        )
    )
    if len(key) > 192:
        raise RuntimeError("Canonical transaction identity key exceeds its schema.")
    return _Identity(
        status=_STATUS_SCOPED,
        version=_VERSION_SCOPED,
        network=network,
        account_canonical=account,
        logical_time_canonical=canonical_lt,
        hash_canonical=canonical_hash,
        key=key,
    )


def _transactions_table() -> sa.TableClause:
    return sa.table(
        "wallet_transactions",
        sa.column("id", sa.Integer()),
        sa.column("run_id", sa.Integer()),
        sa.column("tx_hash", sa.String()),
        sa.column("logical_time", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("source_status", sa.String()),
        sa.column("raw_json", sa.Text()),
        sa.column("transaction_identity_status", sa.String()),
        sa.column("transaction_identity_version", sa.String()),
        sa.column("transaction_network", sa.String()),
        sa.column("transaction_account_canonical", sa.String()),
        sa.column("transaction_logical_time_canonical", sa.String()),
        sa.column("transaction_hash_canonical", sa.String()),
        sa.column("transaction_identity_key", sa.String()),
    )


def _wallet_runs_table() -> sa.TableClause:
    return sa.table(
        "wallet_ingestion_runs",
        sa.column("id", sa.Integer()),
        sa.column("data_mode", sa.String()),
        sa.column("wallet_identity_status", sa.String()),
        sa.column("wallet_identity_version", sa.String()),
        sa.column("wallet_network", sa.String()),
        sa.column("wallet_address_canonical", sa.String()),
        sa.column("wallet_workchain_id", sa.Integer()),
        sa.column("wallet_account_id_hex", sa.String()),
    )


def _identity_source_query(*, after_id: int | None = None):
    transactions = _transactions_table()
    runs = _wallet_runs_table()
    query = (
        sa.select(
            transactions.c.id,
            transactions.c.run_id,
            transactions.c.tx_hash,
            transactions.c.logical_time,
            transactions.c.provider,
            transactions.c.source_status,
            transactions.c.raw_json,
            transactions.c.transaction_identity_status,
            transactions.c.transaction_identity_version,
            transactions.c.transaction_network,
            transactions.c.transaction_account_canonical,
            transactions.c.transaction_logical_time_canonical,
            transactions.c.transaction_hash_canonical,
            transactions.c.transaction_identity_key,
            runs.c.data_mode,
            runs.c.wallet_identity_status,
            runs.c.wallet_identity_version,
            runs.c.wallet_network,
            runs.c.wallet_address_canonical,
            runs.c.wallet_workchain_id,
            runs.c.wallet_account_id_hex,
        )
        .select_from(
            transactions.join(runs, transactions.c.run_id == runs.c.id)
        )
        .order_by(transactions.c.id)
        .limit(_BATCH_SIZE)
    )
    if after_id is not None:
        query = query.where(transactions.c.id > after_id)
    return query


def _backfill_transaction_identities() -> None:
    connection = op.get_bind()
    transactions = _transactions_table()
    last_id: int | None = None

    while True:
        rows = connection.execute(
            _identity_source_query(after_id=last_id)
        ).mappings().all()
        if not rows:
            break

        updates: list[dict[str, Any]] = []
        for row in rows:
            identity = _derive_identity(dict(row))
            updates.append(
                {
                    "target_transaction_id": row["id"],
                    "transaction_identity_status": identity.status,
                    "transaction_identity_version": identity.version,
                    "transaction_network": identity.network,
                    "transaction_account_canonical": identity.account_canonical,
                    "transaction_logical_time_canonical": (
                        identity.logical_time_canonical
                    ),
                    "transaction_hash_canonical": identity.hash_canonical,
                    "transaction_identity_key": identity.key,
                }
            )

        update = (
            transactions.update()
            .where(
                transactions.c.id == sa.bindparam("target_transaction_id")
            )
            .values(
                transaction_identity_status=sa.bindparam(
                    "transaction_identity_status"
                ),
                transaction_identity_version=sa.bindparam(
                    "transaction_identity_version"
                ),
                transaction_network=sa.bindparam("transaction_network"),
                transaction_account_canonical=sa.bindparam(
                    "transaction_account_canonical"
                ),
                transaction_logical_time_canonical=sa.bindparam(
                    "transaction_logical_time_canonical"
                ),
                transaction_hash_canonical=sa.bindparam(
                    "transaction_hash_canonical"
                ),
                transaction_identity_key=sa.bindparam(
                    "transaction_identity_key"
                ),
            )
        )
        connection.execute(update, updates)
        last_id = int(rows[-1]["id"])


def _assert_backfill_postconditions() -> None:
    connection = op.get_bind()
    last_id: int | None = None
    mismatch_ids: list[int] = []

    while True:
        rows = connection.execute(
            _identity_source_query(after_id=last_id)
        ).mappings().all()
        if not rows:
            break
        for row in rows:
            expected = _derive_identity(dict(row))
            actual = _Identity(
                status=row["transaction_identity_status"],
                version=row["transaction_identity_version"],
                network=row["transaction_network"],
                account_canonical=row["transaction_account_canonical"],
                logical_time_canonical=row[
                    "transaction_logical_time_canonical"
                ],
                hash_canonical=row["transaction_hash_canonical"],
                key=row["transaction_identity_key"],
            )
            if actual != expected:
                mismatch_ids.append(int(row["id"]))
                if len(mismatch_ids) >= 20:
                    break
        if len(mismatch_ids) >= 20:
            break
        last_id = int(rows[-1]["id"])

    if mismatch_ids:
        raise RuntimeError(
            "Transaction identity backfill produced inconsistent rows: "
            f"sample_ids={mismatch_ids}."
        )


def _assert_no_duplicate_run_identities() -> None:
    connection = op.get_bind()
    transactions = _transactions_table()
    duplicates = connection.execute(
        sa.select(
            transactions.c.run_id,
            transactions.c.transaction_identity_key,
            sa.func.count().label("row_count"),
        )
        .where(transactions.c.transaction_identity_key.is_not(None))
        .group_by(
            transactions.c.run_id,
            transactions.c.transaction_identity_key,
        )
        .having(sa.func.count() > 1)
        .order_by(transactions.c.run_id)
        .limit(20)
    ).all()
    if duplicates:
        sample = [
            {
                "run_id": int(row.run_id),
                "key": row.transaction_identity_key,
                "row_count": int(row.row_count),
            }
            for row in duplicates
        ]
        raise RuntimeError(
            "Duplicate canonical transaction identities exist within an "
            f"ingestion run; migration refuses to guess: sample={sample}."
        )


def _index_options_signature(
    options: dict[str, Any] | None,
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted(
            (str(key), " ".join(str(value).split()))
            for key, value in (options or {}).items()
            if value is not None
        )
    )


def _ensure_identity_indexes() -> None:
    connection = op.get_bind()
    reflected = {
        index["name"]: (
            index["name"],
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
            _index_options_signature(index.get("dialect_options")),
        )
        for index in sa.inspect(connection).get_indexes("wallet_transactions")
    }

    for name, columns, unique in _IDENTITY_INDEXES:
        expected = (name, columns, unique, ())
        actual = reflected.get(name)
        if actual is not None and actual != expected:
            raise RuntimeError(
                "Existing transaction identity index does not match revision "
                f"0003: expected={expected}, actual={actual}."
            )

    for name, columns, unique in _IDENTITY_INDEXES:
        if name not in reflected:
            op.create_index(
                name,
                "wallet_transactions",
                list(columns),
                unique=unique,
            )

    refreshed = {
        index["name"]: (
            index["name"],
            tuple(index.get("column_names") or ()),
            bool(index.get("unique")),
            _index_options_signature(index.get("dialect_options")),
        )
        for index in sa.inspect(connection).get_indexes("wallet_transactions")
    }
    mismatches = []
    for name, columns, unique in _IDENTITY_INDEXES:
        expected = (name, columns, unique, ())
        if refreshed.get(name) != expected:
            mismatches.append(
                f"expected={expected}, actual={refreshed.get(name)}"
            )
    if mismatches:
        raise RuntimeError(
            "Transaction identity migration did not create expected indexes: "
            + "; ".join(mismatches)
        )


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Transaction identity backfill requires an online database "
            "connection; offline SQL generation is intentionally unsupported "
            "for this revision."
        )

    # SQLite DDL can survive a failed Alembic transaction. Every phase accepts
    # an already-correct partial state, redoes deterministic DML, and validates
    # the result before the revision marker may advance.
    _ensure_identity_columns()
    _backfill_transaction_identities()
    _assert_backfill_postconditions()
    _assert_no_duplicate_run_identities()
    _ensure_identity_indexes()


def downgrade() -> None:
    raise RuntimeError(
        "Transaction identity downgrade would discard derived identity "
        "evidence and is intentionally unsupported. Restore a verified "
        "backup instead."
    )
