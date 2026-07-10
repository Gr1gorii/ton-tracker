"""Add strict provider-scoped TonAPI event-action observation identity.

Revision ID: 20260710_0005
Revises: 20260710_0004
Create Date: 2026-07-10
"""

from __future__ import annotations

import json
import re
from typing import Any, NamedTuple

from alembic import op
import sqlalchemy as sa


revision = "20260710_0005"
down_revision = "20260710_0004"
branch_labels = None
depends_on = None


_BATCH_SIZE = 500

_TRANSFERS_TABLE = "wallet_transfers"
_SWAPS_TABLE = "wallet_swaps"
_ACTIVITY_TABLES = (_TRANSFERS_TABLE, _SWAPS_TABLE)

_STATUS_SCOPED = "provider_scoped"
_STATUS_UNAVAILABLE = "unavailable"

_VERSION_SCOPED = "tonapi_event_action_obs_v1"
_VERSION_UNAVAILABLE = "unavailable"
_WALLET_IDENTITY_VERSIONS = ("ton_std_address_v1", "ton_raw_address_v1")

_NETWORK_MAINNET = "ton-mainnet"
_NETWORK_TESTNET = "ton-testnet"
_NETWORK_UNKNOWN = "ton-unknown"

_EVENT_ID_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_LOGICAL_TIME_RE = re.compile(r"^[1-9][0-9]{0,19}$")
_RAW_ACCOUNT_RE = re.compile(
    r"^((?:0|[1-9][0-9]*|-[1-9][0-9]*)):([0-9a-f]{64})$"
)
_MAX_LOGICAL_TIME = 2**64 - 1
_MAX_ACTION_INDEX = 2**31 - 1
_MIN_WORKCHAIN = -(2**31)
_MAX_WORKCHAIN = 2**31 - 1

_SURFACE_BY_TABLE = {
    _TRANSFERS_TABLE: "transfers",
    _SWAPS_TABLE: "swaps",
}
_ACTION_TYPES_BY_TABLE = {
    _TRANSFERS_TABLE: frozenset(("TonTransfer", "JettonTransfer")),
    _SWAPS_TABLE: frozenset(("JettonSwap",)),
}

_IDENTITY_COLUMN_NAMES = frozenset(
    (
        "event_action_identity_status",
        "event_action_identity_version",
        "event_action_network",
        "event_action_account_canonical",
        "event_action_event_id_canonical",
        "event_action_logical_time_canonical",
        "event_action_index",
        "event_action_type",
        "event_action_identity_key",
    )
)

_IDENTITY_INDEXES_BY_TABLE = {
    _TRANSFERS_TABLE: (
        (
            "uq_wallet_transfers_run_event_action_identity",
            ("run_id", "event_action_identity_key"),
            True,
        ),
        (
            "ix_wallet_transfers_event_action_identity_key",
            ("event_action_identity_key",),
            False,
        ),
        (
            "ix_wallet_transfers_event_action_identity_tuple",
            (
                "provider",
                "event_action_network",
                "event_action_account_canonical",
                "event_action_event_id_canonical",
                "event_action_logical_time_canonical",
                "event_action_index",
            ),
            False,
        ),
    ),
    _SWAPS_TABLE: (
        (
            "uq_wallet_swaps_run_event_action_identity",
            ("run_id", "event_action_identity_key"),
            True,
        ),
        (
            "ix_wallet_swaps_event_action_identity_key",
            ("event_action_identity_key",),
            False,
        ),
        (
            "ix_wallet_swaps_event_action_identity_tuple",
            (
                "provider",
                "event_action_network",
                "event_action_account_canonical",
                "event_action_event_id_canonical",
                "event_action_logical_time_canonical",
                "event_action_index",
            ),
            False,
        ),
    ),
}


class _Identity(NamedTuple):
    status: str
    version: str
    network: str
    account_canonical: str | None
    event_id_canonical: str | None
    logical_time_canonical: str | None
    action_index: int | None
    action_type: str | None
    key: str | None


def _identity_columns() -> tuple[sa.Column, ...]:
    """Return fresh columns for restart-safe non-transactional SQLite DDL."""
    return (
        sa.Column(
            "event_action_identity_status",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'unavailable'"),
        ),
        sa.Column(
            "event_action_identity_version",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'unavailable'"),
        ),
        sa.Column(
            "event_action_network",
            sa.String(length=16),
            nullable=False,
            server_default=sa.text("'ton-unknown'"),
        ),
        sa.Column(
            "event_action_account_canonical",
            sa.String(length=76),
            nullable=True,
        ),
        sa.Column(
            "event_action_event_id_canonical",
            sa.String(length=64),
            nullable=True,
        ),
        sa.Column(
            "event_action_logical_time_canonical",
            sa.String(length=20),
            nullable=True,
        ),
        sa.Column("event_action_index", sa.Integer(), nullable=True),
        sa.Column(
            "event_action_type",
            sa.String(length=32),
            nullable=True,
        ),
        sa.Column(
            "event_action_identity_key",
            sa.String(length=256),
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
    table_name: str,
    reflected: dict[str, dict[str, Any]],
    expected: tuple[sa.Column, ...],
) -> None:
    expected_names = {str(column.name) for column in expected}
    unexpected = sorted(
        name
        for name in reflected
        if name.startswith("event_action_") and name not in expected_names
    )
    if unexpected:
        raise RuntimeError(
            f"Existing {table_name} has unexpected event-action identity "
            f"columns for revision 0005: {unexpected}."
        )

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
            f"Existing {table_name} event-action identity columns do not "
            "match revision 0005: " + "; ".join(mismatches)
        )


def _reflected_columns(table_name: str) -> dict[str, dict[str, Any]]:
    return {
        str(column["name"]): column
        for column in sa.inspect(op.get_bind()).get_columns(table_name)
    }


def _preflight_identity_columns() -> None:
    inspector = sa.inspect(op.get_bind())
    existing_tables = set(inspector.get_table_names())
    missing_tables = sorted(set(_ACTIVITY_TABLES) - existing_tables)
    if missing_tables:
        raise RuntimeError(
            "Event-action identity migration requires the revision 0004 "
            f"activity tables; missing={missing_tables}."
        )
    expected = _identity_columns()
    for table_name in _ACTIVITY_TABLES:
        _assert_existing_identity_columns(
            table_name,
            _reflected_columns(table_name),
            expected,
        )


def _ensure_identity_columns(table_name: str) -> None:
    expected = _identity_columns()
    reflected = _reflected_columns(table_name)
    _assert_existing_identity_columns(table_name, reflected, expected)

    for column in expected:
        if column.name not in reflected:
            op.add_column(table_name, column)

    refreshed = _reflected_columns(table_name)
    missing = [
        str(column.name)
        for column in expected
        if column.name not in refreshed
    ]
    if missing:
        raise RuntimeError(
            f"Event-action identity migration did not add expected "
            f"{table_name} columns: {missing}."
        )
    _assert_existing_identity_columns(table_name, refreshed, expected)


def _unavailable_identity() -> _Identity:
    return _Identity(
        status=_STATUS_UNAVAILABLE,
        version=_VERSION_UNAVAILABLE,
        network=_NETWORK_UNKNOWN,
        account_canonical=None,
        event_id_canonical=None,
        logical_time_canonical=None,
        action_index=None,
        action_type=None,
        key=None,
    )


def _canonical_account(row: dict[str, Any]) -> str | None:
    if row.get("wallet_identity_status") != "network_scoped":
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
    if type(row.get("wallet_workchain_id")) is not int:
        return None
    if row.get("wallet_workchain_id") != workchain_id:
        return None
    if row.get("wallet_account_id_hex") != account_id_hex:
        return None
    return value


def _canonical_event_id(value: Any) -> str | None:
    if not isinstance(value, str) or _EVENT_ID_RE.fullmatch(value) is None:
        return None
    return value.lower()


def _canonical_logical_time(value: Any) -> str | None:
    if not isinstance(value, str) or _LOGICAL_TIME_RE.fullmatch(value) is None:
        return None
    parsed = int(value, 10)
    if parsed > _MAX_LOGICAL_TIME:
        return None
    return value


def _canonical_action_index(value: Any) -> int | None:
    if type(value) is not int or not 0 <= value <= _MAX_ACTION_INDEX:
        return None
    return value


def _raw_payload(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, str):
        return None
    try:
        payload = json.loads(value)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _derive_identity(row: dict[str, Any], table_name: str) -> _Identity:
    if row.get("data_mode") != "real":
        return _unavailable_identity()
    if row.get("provider") != "tonapi" or row.get("source_status") != "live":
        return _unavailable_identity()

    raw = _raw_payload(row.get("raw_json"))
    if raw is None:
        return _unavailable_identity()
    surface = _SURFACE_BY_TABLE[table_name]
    if (
        raw.get("provider") != "tonapi"
        or raw.get("source") != "tonapi"
        or raw.get("surface") != surface
    ):
        return _unavailable_identity()

    event_id = row.get("tx_hash")
    if raw.get("event_id") != event_id:
        return _unavailable_identity()
    logical_time = (
        row.get("logical_time")
        if table_name == _TRANSFERS_TABLE
        else raw.get("lt")
    )
    if raw.get("lt") != logical_time:
        return _unavailable_identity()
    action_index = _canonical_action_index(raw.get("action_index"))
    action_type = raw.get("action_type")
    if action_index is None or action_type not in _ACTION_TYPES_BY_TABLE[table_name]:
        return _unavailable_identity()

    account = _canonical_account(row)
    canonical_event_id = _canonical_event_id(event_id)
    canonical_lt = _canonical_logical_time(logical_time)
    network = row.get("wallet_network")
    if account is None or canonical_event_id is None or canonical_lt is None:
        return _unavailable_identity()

    key = "|".join(
        (
            _VERSION_SCOPED,
            "tonapi",
            network,
            account,
            canonical_event_id,
            canonical_lt,
            str(action_index),
        )
    )
    if len(key) > 256:
        raise RuntimeError(
            "Provider event-action observation identity key exceeds its schema."
        )
    return _Identity(
        status=_STATUS_SCOPED,
        version=_VERSION_SCOPED,
        network=network,
        account_canonical=account,
        event_id_canonical=canonical_event_id,
        logical_time_canonical=canonical_lt,
        action_index=action_index,
        action_type=action_type,
        key=key,
    )


def _activity_table(table_name: str) -> sa.TableClause:
    columns = [
        sa.column("id", sa.Integer()),
        sa.column("run_id", sa.Integer()),
        sa.column("tx_hash", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("source_status", sa.String()),
        sa.column("raw_json", sa.Text()),
        sa.column("event_action_identity_status", sa.String()),
        sa.column("event_action_identity_version", sa.String()),
        sa.column("event_action_network", sa.String()),
        sa.column("event_action_account_canonical", sa.String()),
        sa.column("event_action_event_id_canonical", sa.String()),
        sa.column("event_action_logical_time_canonical", sa.String()),
        sa.column("event_action_index", sa.Integer()),
        sa.column("event_action_type", sa.String()),
        sa.column("event_action_identity_key", sa.String()),
    ]
    if table_name == _TRANSFERS_TABLE:
        columns.insert(3, sa.column("logical_time", sa.String()))
    return sa.table(table_name, *columns)


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


def _identity_source_query(
    table_name: str,
    *,
    after_id: int | None = None,
):
    activity = _activity_table(table_name)
    runs = _wallet_runs_table()
    selected = [
        activity.c.id,
        activity.c.run_id,
        activity.c.tx_hash,
        activity.c.provider,
        activity.c.source_status,
        activity.c.raw_json,
        activity.c.event_action_identity_status,
        activity.c.event_action_identity_version,
        activity.c.event_action_network,
        activity.c.event_action_account_canonical,
        activity.c.event_action_event_id_canonical,
        activity.c.event_action_logical_time_canonical,
        activity.c.event_action_index,
        activity.c.event_action_type,
        activity.c.event_action_identity_key,
        runs.c.data_mode,
        runs.c.wallet_identity_status,
        runs.c.wallet_identity_version,
        runs.c.wallet_network,
        runs.c.wallet_address_canonical,
        runs.c.wallet_workchain_id,
        runs.c.wallet_account_id_hex,
    ]
    if table_name == _TRANSFERS_TABLE:
        selected.insert(3, activity.c.logical_time)
    query = (
        sa.select(*selected)
        .select_from(activity.join(runs, activity.c.run_id == runs.c.id))
        .order_by(activity.c.id)
        .limit(_BATCH_SIZE)
    )
    if after_id is not None:
        query = query.where(activity.c.id > after_id)
    return query


def _backfill_event_action_identities(table_name: str) -> None:
    connection = op.get_bind()
    activity = _activity_table(table_name)
    last_id: int | None = None

    while True:
        rows = connection.execute(
            _identity_source_query(table_name, after_id=last_id)
        ).mappings().all()
        if not rows:
            break

        updates: list[dict[str, Any]] = []
        for row in rows:
            identity = _derive_identity(dict(row), table_name)
            updates.append(
                {
                    "target_activity_id": row["id"],
                    "event_action_identity_status": identity.status,
                    "event_action_identity_version": identity.version,
                    "event_action_network": identity.network,
                    "event_action_account_canonical": identity.account_canonical,
                    "event_action_event_id_canonical": (
                        identity.event_id_canonical
                    ),
                    "event_action_logical_time_canonical": (
                        identity.logical_time_canonical
                    ),
                    "event_action_index": identity.action_index,
                    "event_action_type": identity.action_type,
                    "event_action_identity_key": identity.key,
                }
            )

        update = (
            activity.update()
            .where(activity.c.id == sa.bindparam("target_activity_id"))
            .values(
                event_action_identity_status=sa.bindparam(
                    "event_action_identity_status"
                ),
                event_action_identity_version=sa.bindparam(
                    "event_action_identity_version"
                ),
                event_action_network=sa.bindparam("event_action_network"),
                event_action_account_canonical=sa.bindparam(
                    "event_action_account_canonical"
                ),
                event_action_event_id_canonical=sa.bindparam(
                    "event_action_event_id_canonical"
                ),
                event_action_logical_time_canonical=sa.bindparam(
                    "event_action_logical_time_canonical"
                ),
                event_action_index=sa.bindparam("event_action_index"),
                event_action_type=sa.bindparam("event_action_type"),
                event_action_identity_key=sa.bindparam(
                    "event_action_identity_key"
                ),
            )
        )
        connection.execute(update, updates)
        last_id = int(rows[-1]["id"])


def _identity_from_persisted_row(row: dict[str, Any]) -> _Identity:
    return _Identity(
        status=row["event_action_identity_status"],
        version=row["event_action_identity_version"],
        network=row["event_action_network"],
        account_canonical=row["event_action_account_canonical"],
        event_id_canonical=row["event_action_event_id_canonical"],
        logical_time_canonical=row[
            "event_action_logical_time_canonical"
        ],
        action_index=row["event_action_index"],
        action_type=row["event_action_type"],
        key=row["event_action_identity_key"],
    )


def _assert_backfill_postconditions(table_name: str) -> None:
    connection = op.get_bind()
    last_id: int | None = None
    mismatch_ids: list[int] = []

    while True:
        rows = connection.execute(
            _identity_source_query(table_name, after_id=last_id)
        ).mappings().all()
        if not rows:
            break
        for row in rows:
            expected = _derive_identity(dict(row), table_name)
            actual = _identity_from_persisted_row(dict(row))
            if actual != expected:
                mismatch_ids.append(int(row["id"]))
                if len(mismatch_ids) >= 20:
                    break
        if len(mismatch_ids) >= 20:
            break
        last_id = int(rows[-1]["id"])

    if mismatch_ids:
        raise RuntimeError(
            f"{table_name} event-action identity backfill produced "
            f"inconsistent rows: sample_ids={mismatch_ids}."
        )


def _assert_no_same_table_duplicates(table_name: str) -> None:
    connection = op.get_bind()
    activity = _activity_table(table_name)
    duplicates = connection.execute(
        sa.select(
            activity.c.run_id,
            activity.c.event_action_identity_key,
            sa.func.count().label("row_count"),
        )
        .where(activity.c.event_action_identity_key.is_not(None))
        .group_by(activity.c.run_id, activity.c.event_action_identity_key)
        .having(sa.func.count() > 1)
        .order_by(activity.c.run_id, activity.c.event_action_identity_key)
        .limit(20)
    ).all()
    if duplicates:
        sample = [
            {
                "run_id": int(row.run_id),
                "key": row.event_action_identity_key,
                "row_count": int(row.row_count),
            }
            for row in duplicates
        ]
        raise RuntimeError(
            f"Duplicate provider event-action observation identities exist "
            f"within {table_name}; migration refuses to guess: "
            f"sample={sample}."
        )


def _assert_no_cross_table_duplicates() -> None:
    connection = op.get_bind()
    transfers = _activity_table(_TRANSFERS_TABLE)
    swaps = _activity_table(_SWAPS_TABLE)
    duplicates = connection.execute(
        sa.select(
            transfers.c.run_id,
            transfers.c.event_action_identity_key,
        )
        .select_from(
            transfers.join(
                swaps,
                sa.and_(
                    transfers.c.run_id == swaps.c.run_id,
                    transfers.c.event_action_identity_key
                    == swaps.c.event_action_identity_key,
                ),
            )
        )
        .where(transfers.c.event_action_identity_key.is_not(None))
        .distinct()
        .order_by(
            transfers.c.run_id,
            transfers.c.event_action_identity_key,
        )
        .limit(20)
    ).all()
    if duplicates:
        sample = [
            {
                "run_id": int(row.run_id),
                "key": row.event_action_identity_key,
            }
            for row in duplicates
        ]
        raise RuntimeError(
            "The same provider event-action observation identity appears in "
            "both wallet_transfers and wallet_swaps within one run; migration "
            f"refuses to guess: sample={sample}."
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


def _index_signature(index: dict[str, Any]) -> tuple[Any, ...]:
    return (
        str(index.get("name")),
        tuple(index.get("column_names") or ()),
        bool(index.get("unique")),
        _index_options_signature(index.get("dialect_options")),
    )


def _expected_index_signature(index: tuple[Any, ...]) -> tuple[Any, ...]:
    name, columns, unique = index
    return name, columns, unique, ()


def _is_identity_related_index(index: dict[str, Any]) -> bool:
    name = str(index.get("name") or "")
    columns = set(index.get("column_names") or ())
    return "event_action" in name or bool(columns & _IDENTITY_COLUMN_NAMES)


def _assert_identity_indexes(table_name: str, *, allow_missing: bool) -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = inspector.get_indexes(table_name)
    by_name = {str(index.get("name")): index for index in indexes}
    expected_indexes = _IDENTITY_INDEXES_BY_TABLE[table_name]
    expected_names = {str(index[0]) for index in expected_indexes}

    unexpected = sorted(
        str(index.get("name"))
        for index in indexes
        if _is_identity_related_index(index)
        and str(index.get("name")) not in expected_names
    )
    if unexpected:
        raise RuntimeError(
            f"Existing {table_name} has unexpected event-action identity "
            f"indexes for revision 0005: {unexpected}."
        )

    mismatches = []
    for expected_index in expected_indexes:
        expected = _expected_index_signature(expected_index)
        name = str(expected_index[0])
        actual_index = by_name.get(name)
        if actual_index is None:
            if not allow_missing:
                mismatches.append(f"expected={expected}, actual=None")
            continue
        actual = _index_signature(actual_index)
        if actual != expected:
            mismatches.append(f"expected={expected}, actual={actual}")
    if mismatches:
        raise RuntimeError(
            f"Existing {table_name} event-action identity indexes do not "
            "match revision 0005: " + "; ".join(mismatches)
        )

    for constraint in inspector.get_unique_constraints(table_name):
        constraint_name = str(constraint.get("name") or "")
        constraint_columns = set(constraint.get("column_names") or ())
        if (
            "event_action" in constraint_name
            or constraint_columns & _IDENTITY_COLUMN_NAMES
        ):
            raise RuntimeError(
                f"Existing {table_name} has an unexpected event-action "
                f"unique constraint for revision 0005: {constraint}."
            )

    for constraint in inspector.get_check_constraints(table_name):
        sqltext = str(constraint.get("sqltext") or "")
        if "event_action_" in sqltext:
            raise RuntimeError(
                f"Existing {table_name} has an unexpected event-action "
                f"check constraint for revision 0005: {constraint}."
            )


def _ensure_identity_indexes(table_name: str) -> None:
    _assert_identity_indexes(table_name, allow_missing=True)
    reflected = {
        str(index.get("name")): index
        for index in sa.inspect(op.get_bind()).get_indexes(table_name)
    }
    for name, columns, unique in _IDENTITY_INDEXES_BY_TABLE[table_name]:
        if name not in reflected:
            op.create_index(
                name,
                table_name,
                list(columns),
                unique=unique,
            )
    _assert_identity_indexes(table_name, allow_missing=False)


def upgrade() -> None:
    if op.get_context().as_sql:
        raise RuntimeError(
            "Event-action identity backfill requires an online database "
            "connection; offline SQL generation is intentionally unsupported "
            "for this revision."
        )

    # SQLite DDL can survive a failed Alembic transaction. Validate both
    # tables before the first change, then make each phase deterministic and
    # verify it before the revision marker may advance.
    _preflight_identity_columns()
    for table_name in _ACTIVITY_TABLES:
        _assert_identity_indexes(table_name, allow_missing=True)
    for table_name in _ACTIVITY_TABLES:
        _ensure_identity_columns(table_name)
    for table_name in _ACTIVITY_TABLES:
        _backfill_event_action_identities(table_name)
        _assert_backfill_postconditions(table_name)
    for table_name in _ACTIVITY_TABLES:
        _assert_no_same_table_duplicates(table_name)
    _assert_no_cross_table_duplicates()
    for table_name in _ACTIVITY_TABLES:
        _ensure_identity_indexes(table_name)


def downgrade() -> None:
    raise RuntimeError(
        "Event-action identity downgrade would discard provider observation "
        "identity evidence and is intentionally unsupported. Restore a "
        "verified backup instead."
    )
