"""Parse user-imported trade data into normalized trade rows.

This service is intentionally standalone: it does not call external APIs,
touch persistence, or affect the existing dashboard analysis flow.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from io import StringIO
from typing import Any, Iterable, Mapping

REQUIRED_COLUMNS = (
    "tx_hash",
    "block_time",
    "wallet",
    "side",
    "token_amount",
    "usd_amount",
)

ZERO = Decimal("0")


def parse_csv_trades(csv_text: str) -> dict[str, Any]:
    """Parse CSV trade rows into normalized imported trade dictionaries."""
    if not csv_text or not csv_text.strip():
        return _empty_result()

    reader = csv.DictReader(StringIO(csv_text.strip()))
    if not reader.fieldnames:
        return _empty_result()
    missing_columns = _missing_required_columns(reader.fieldnames)
    if missing_columns:
        return _header_error_result(
            f"Missing required columns: {', '.join(missing_columns)}"
        )

    rows = []
    for row_number, row in enumerate(reader, start=2):
        if _is_empty_csv_row(row):
            continue
        rows.append((row_number, row))

    return _parse_rows(rows, source="imported_csv")


def parse_json_trades(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Parse JSON-like Python mappings into normalized imported trades."""
    numbered_rows = [(index, row) for index, row in enumerate(rows, start=1)]
    return _parse_rows(numbered_rows, source="imported_json")


def _parse_rows(
    numbered_rows: list[tuple[int, Mapping[str, Any]]],
    source: str,
) -> dict[str, Any]:
    trades: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, Decimal]] = set()
    duplicate_rows = 0
    invalid_rows = 0

    for row_number, row in numbered_rows:
        trade, row_errors = _normalize_row(row, row_number, source)
        if row_errors:
            invalid_rows += 1
            errors.extend(row_errors)
            continue

        assert trade is not None
        key = (
            trade["tx_hash"],
            trade["wallet"],
            trade["side"],
            trade["token_amount"],
        )
        if key in seen:
            duplicate_rows += 1
            continue
        seen.add(key)
        trades.append(trade)

    return {
        "trades": trades,
        "summary": {
            "total_rows": len(numbered_rows),
            "valid_rows": len(trades),
            "invalid_rows": invalid_rows,
            "duplicate_rows": duplicate_rows,
            "errors": errors,
        },
    }


def _normalize_row(
    row: Mapping[str, Any],
    row_number: int,
    source: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    errors: list[dict[str, Any]] = []

    tx_hash = _required_string(row, "tx_hash", row_number, errors)
    block_time = _normalize_datetime(row.get("block_time"), row_number, errors)
    wallet = _required_string(row, "wallet", row_number, errors)
    side = _normalize_side(row.get("side"), row_number, errors)
    token_amount = _required_decimal(row, "token_amount", row_number, errors)
    usd_amount = _required_decimal(row, "usd_amount", row_number, errors)
    price_usd = _optional_decimal(row, "price_usd", row_number, errors)

    if token_amount is not None and token_amount <= ZERO:
        errors.append(
            _error(row_number, "token_amount", "Invalid numeric value: must be > 0")
        )
    if usd_amount is not None and usd_amount < ZERO:
        errors.append(
            _error(row_number, "usd_amount", "Invalid numeric value: must be >= 0")
        )
    if price_usd is not None and price_usd < ZERO:
        errors.append(
            _error(row_number, "price_usd", "Invalid numeric value: must be >= 0")
        )

    if errors:
        return None, errors

    assert tx_hash is not None
    assert block_time is not None
    assert wallet is not None
    assert side is not None
    assert token_amount is not None
    assert usd_amount is not None

    if price_usd is None:
        price_usd = usd_amount / token_amount

    trade = {
        "tx_hash": tx_hash,
        "block_time": block_time,
        "wallet": wallet,
        "side": side,
        "token_amount": token_amount,
        "usd_amount": usd_amount,
        "price_usd": price_usd,
        "pool_address": _optional_string(row.get("pool_address")),
        "dex": _optional_string(row.get("dex")),
        "source": source,
    }
    return trade, []


def _empty_result() -> dict[str, Any]:
    return {
        "trades": [],
        "summary": {
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "duplicate_rows": 0,
            "errors": [],
        },
    }


def _header_error_result(message: str) -> dict[str, Any]:
    return {
        "trades": [],
        "summary": {
            "total_rows": 0,
            "valid_rows": 0,
            "invalid_rows": 0,
            "duplicate_rows": 0,
            "errors": [_error(1, "header", message)],
        },
    }


def _missing_required_columns(fieldnames: list[str]) -> list[str]:
    present = {field.strip() for field in fieldnames if field}
    return [field for field in REQUIRED_COLUMNS if field not in present]


def _required_string(
    row: Mapping[str, Any],
    field: str,
    row_number: int,
    errors: list[dict[str, Any]],
) -> str | None:
    value = _optional_string(row.get(field))
    if value is None:
        errors.append(_error(row_number, field, "Required value is missing"))
    return value


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_side(
    value: Any,
    row_number: int,
    errors: list[dict[str, Any]],
) -> str | None:
    side = _optional_string(value)
    if side is None:
        errors.append(_error(row_number, "side", "Required value is missing"))
        return None
    normalized = side.lower()
    if normalized not in ("buy", "sell"):
        errors.append(
            _error(row_number, "side", "Invalid side: expected buy or sell")
        )
        return None
    return normalized


def _required_decimal(
    row: Mapping[str, Any],
    field: str,
    row_number: int,
    errors: list[dict[str, Any]],
) -> Decimal | None:
    value = row.get(field)
    if _optional_string(value) is None:
        errors.append(_error(row_number, field, "Required value is missing"))
        return None
    return _parse_decimal(value, field, row_number, errors)


def _optional_decimal(
    row: Mapping[str, Any],
    field: str,
    row_number: int,
    errors: list[dict[str, Any]],
) -> Decimal | None:
    value = row.get(field)
    if _optional_string(value) is None:
        return None
    return _parse_decimal(value, field, row_number, errors)


def _parse_decimal(
    value: Any,
    field: str,
    row_number: int,
    errors: list[dict[str, Any]],
) -> Decimal | None:
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors.append(_error(row_number, field, "Invalid numeric value"))
        return None
    if not parsed.is_finite():
        errors.append(_error(row_number, field, "Invalid numeric value"))
        return None
    return parsed


def _normalize_datetime(
    value: Any,
    row_number: int,
    errors: list[dict[str, Any]],
) -> str | None:
    text = _optional_string(value)
    if text is None:
        errors.append(_error(row_number, "block_time", "Required value is missing"))
        return None

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        errors.append(_error(row_number, "block_time", "Invalid ISO datetime"))
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _error(row_number: int, field: str, message: str) -> dict[str, Any]:
    return {"row": row_number, "field": field, "message": message}


def _is_empty_csv_row(row: Mapping[str, Any]) -> bool:
    return all(_optional_string(value) is None for value in row.values())
