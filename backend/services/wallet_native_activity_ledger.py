"""Immutable native TON activity ledger derived from verified BOC evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from models import WalletNativeActivityLedger, WalletNativeActivityRow
from services.wallet_native_ton_flow_observations import (
    COUNTERPARTY_IDENTITY_VERSION,
    NATIVE_TON_ASSET_IDENTITY_VERSION,
    get_wallet_native_ton_flow_observations,
)
from services.wallet_persisted_trace_evidence import (
    _canonical_utc_datetime,
    _find_capture_for_transaction,
)
from services.wallet_trace_evidence import (
    _require_eligible_stored_identity,
    resolve_wallet_transaction_trace_anchor,
)


NATIVE_ACTIVITY_LEDGER_CONTRACT_VERSION = "ton_native_activity_ledger_v1"
NATIVE_ACTIVITY_IDENTITY_VERSION = "ton_native_activity_v1"
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class WalletNativeActivityLedgerConflict(ValueError):
    """Stored activity ledger failed deterministic local revalidation."""


class WalletNativeActivityLedgerFailure(RuntimeError):
    """Activity ledger could not be stored atomically."""


def get_wallet_native_activity_ledger(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any] | None:
    run, transaction = resolve_wallet_transaction_trace_anchor(
        run_id, transaction_hash, session
    )
    _require_eligible_stored_identity(run, transaction, transaction_hash)
    capture = _find_capture_for_transaction(run_id, transaction_hash, session)
    if capture is None:
        return None
    ledger = _find_ledger(capture.id, session)
    if ledger is None:
        return None
    return _revalidate_ledger(ledger, run_id, transaction_hash, session)


def build_wallet_native_activity_ledger(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> tuple[dict[str, Any], bool]:
    run, transaction = resolve_wallet_transaction_trace_anchor(
        run_id, transaction_hash, session
    )
    _require_eligible_stored_identity(run, transaction, transaction_hash)
    capture = _find_capture_for_transaction(run_id, transaction_hash, session)
    if capture is None:
        raise WalletNativeActivityLedgerConflict(
            "Verified trace capture is required before building activity."
        )
    existing = _find_ledger(capture.id, session)
    if existing is not None:
        return _revalidate_ledger(existing, run_id, transaction_hash, session), False
    source, rows = _derive_rows(run_id, transaction_hash, session)
    built_at = datetime.now(timezone.utc)
    digest = _ledger_digest(capture.id, source, rows, built_at)
    ledger = WalletNativeActivityLedger(
        capture_id=capture.id,
        contract_version=NATIVE_ACTIVITY_LEDGER_CONTRACT_VERSION,
        network=source["network"],
        wallet_account_canonical=source["wallet_account_canonical"],
        source_message_evidence_digest_sha256=source[
            "message_evidence_digest_sha256"
        ],
        activity_count=len(rows),
        incoming_nanoton=source["incoming_nanoton"],
        outgoing_nanoton=source["outgoing_nanoton"],
        self_nanoton=source["self_nanoton"],
        evidence_digest_sha256=digest,
        built_at=built_at,
    )
    try:
        session.add(ledger)
        session.flush()
        for row in rows:
            session.add(WalletNativeActivityRow(ledger_id=ledger.id, **row))
        session.flush()
        stored = _find_ledger(capture.id, session)
        if stored is None:
            raise WalletNativeActivityLedgerFailure(
                "Activity ledger disappeared before commit."
            )
        validated = _revalidate_ledger(stored, run_id, transaction_hash, session)
        session.commit()
        return validated, True
    except WalletNativeActivityLedgerConflict:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        concurrent = _find_ledger(capture.id, session)
        if concurrent is not None:
            return _revalidate_ledger(
                concurrent, run_id, transaction_hash, session
            ), False
        raise WalletNativeActivityLedgerFailure(
            "Activity ledger conflicted with stored evidence."
        ) from exc
    except (KeyError, TypeError, ValueError, SQLAlchemyError) as exc:
        session.rollback()
        raise WalletNativeActivityLedgerFailure(
            "Activity ledger could not be stored atomically."
        ) from exc


def _derive_rows(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source = get_wallet_native_ton_flow_observations(
        run_id, transaction_hash, session
    )
    if source is None:
        raise WalletNativeActivityLedgerConflict(
            "Verified native TON flow evidence is unavailable."
        )
    asset_key = f"{NATIVE_TON_ASSET_IDENTITY_VERSION}|{source['network']}"
    rows = []
    for ordinal, flow in enumerate(source["flows"]):
        counterparty_key = "|".join(
            (
                COUNTERPARTY_IDENTITY_VERSION,
                source["network"],
                flow["counterparty_account_observed"],
            )
        )
        identity_document = {
            "version": NATIVE_ACTIVITY_IDENTITY_VERSION,
            "network": source["network"],
            "wallet": source["wallet_account_canonical"],
            "message_hash": flow["message_hash"],
            "direction": flow["direction"],
            "asset_identity_key": asset_key,
            "counterparty_identity_key": counterparty_key,
            "amount_base_units": flow["amount_nanoton"],
        }
        rows.append(
            {
                "ordinal": ordinal,
                "activity_identity_key": _digest(identity_document),
                "source_flow_observation_identity": flow[
                    "observation_identity"
                ],
                "transaction_hash": flow["transaction_hash"],
                "message_hash": flow["message_hash"],
                "direction": flow["direction"],
                "activity_kind": "native_ton_message_transfer",
                "asset_identity_key": asset_key,
                "counterparty_identity_key": counterparty_key,
                "counterparty_account_canonical": flow[
                    "counterparty_account_observed"
                ],
                "amount_base_units": flow["amount_nanoton"],
                "created_logical_time": flow["created_logical_time"],
                "unix_time": flow["unix_time"],
                "body_hash": flow["body_hash"],
                "opcode_hex": flow["opcode_hex"],
                "bounce": flow["bounce"],
                "bounced": flow["bounced"],
            }
        )
    return source, rows


def _find_ledger(capture_id: int, session: Session) -> WalletNativeActivityLedger | None:
    rows = list(
        session.scalars(
            select(WalletNativeActivityLedger)
            .where(WalletNativeActivityLedger.capture_id == capture_id)
            .where(
                WalletNativeActivityLedger.contract_version
                == NATIVE_ACTIVITY_LEDGER_CONTRACT_VERSION
            )
            .options(selectinload(WalletNativeActivityLedger.rows))
            .limit(2)
        )
    )
    if len(rows) > 1:
        raise WalletNativeActivityLedgerConflict("Activity ledger is ambiguous.")
    return rows[0] if rows else None


def _revalidate_ledger(
    ledger: WalletNativeActivityLedger,
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any]:
    source, derived_rows = _derive_rows(run_id, transaction_hash, session)
    stored_rows = sorted(ledger.rows, key=lambda row: row.ordinal)
    normalized_rows = [
        {
            name: getattr(row, name)
            for name in (
                "ordinal",
                "activity_identity_key",
                "source_flow_observation_identity",
                "transaction_hash",
                "message_hash",
                "direction",
                "activity_kind",
                "asset_identity_key",
                "counterparty_identity_key",
                "counterparty_account_canonical",
                "amount_base_units",
                "created_logical_time",
                "unix_time",
                "body_hash",
                "opcode_hex",
                "bounce",
                "bounced",
            )
        }
        for row in stored_rows
    ]
    built_at = _canonical_utc_datetime(ledger.built_at)
    if (
        ledger.contract_version != NATIVE_ACTIVITY_LEDGER_CONTRACT_VERSION
        or ledger.network != source["network"]
        or ledger.wallet_account_canonical != source["wallet_account_canonical"]
        or ledger.source_message_evidence_digest_sha256
        != source["message_evidence_digest_sha256"]
        or ledger.activity_count != len(derived_rows)
        or ledger.incoming_nanoton != source["incoming_nanoton"]
        or ledger.outgoing_nanoton != source["outgoing_nanoton"]
        or ledger.self_nanoton != source["self_nanoton"]
        or normalized_rows != derived_rows
        or not _HASH_RE.fullmatch(ledger.evidence_digest_sha256 or "")
        or ledger.evidence_digest_sha256
        != _ledger_digest(ledger.capture_id, source, derived_rows, built_at)
    ):
        raise WalletNativeActivityLedgerConflict(
            "Stored native activity ledger failed local revalidation."
        )
    return {
        "contract_version": NATIVE_ACTIVITY_LEDGER_CONTRACT_VERSION,
        "identity_version": NATIVE_ACTIVITY_IDENTITY_VERSION,
        "ledger_id": str(ledger.id),
        "capture_id": str(ledger.capture_id),
        "run_id": str(run_id),
        "network": ledger.network,
        "wallet_account_canonical": ledger.wallet_account_canonical,
        "anchor": source["anchor"],
        "source_message_evidence_digest_sha256": ledger.source_message_evidence_digest_sha256,
        "evidence_digest_sha256": ledger.evidence_digest_sha256,
        "built_at": built_at,
        "activity_count": ledger.activity_count,
        "incoming_nanoton": ledger.incoming_nanoton,
        "outgoing_nanoton": ledger.outgoing_nanoton,
        "self_nanoton": ledger.self_nanoton,
        "activities": normalized_rows,
        "semantic_reconstruction_applied": True,
        "native_ton_only": True,
        "immutable_record": True,
        "is_authoritative_activity_ledger": False,
        "activity_merge_applied": False,
        "cross_run_deduplication_applied": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "is_ownership_proof": False,
        "message": (
            "Verified native TON header observations were materialized as an "
            "immutable semantic ledger. It records observed transfers, not "
            "user intent or an authoritative full-history activity ledger."
        ),
    }


def _ledger_digest(
    capture_id: int,
    source: dict[str, Any],
    rows: list[dict[str, Any]],
    built_at: datetime,
) -> str:
    return _digest(
        {
            "contract_version": NATIVE_ACTIVITY_LEDGER_CONTRACT_VERSION,
            "capture_id": str(capture_id),
            "network": source["network"],
            "wallet_account_canonical": source["wallet_account_canonical"],
            "source_message_evidence_digest_sha256": source[
                "message_evidence_digest_sha256"
            ],
            "built_at": _canonical_utc_datetime(built_at)
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z"),
            "activities": rows,
        }
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


__all__ = [
    "NATIVE_ACTIVITY_LEDGER_CONTRACT_VERSION",
    "NATIVE_ACTIVITY_IDENTITY_VERSION",
    "WalletNativeActivityLedgerConflict",
    "WalletNativeActivityLedgerFailure",
    "build_wallet_native_activity_ledger",
    "get_wallet_native_activity_ledger",
]
