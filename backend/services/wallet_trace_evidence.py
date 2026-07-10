"""Bounded provider trace evidence for one persisted low-level transaction."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from adapters.tonapi import TonapiAdapter
from config import Settings, get_settings
from models import WalletIngestionRun, WalletTransaction
from services.ton_transaction_identity import derive_ton_transaction_identity


TRACE_EVIDENCE_CONTRACT_VERSION = "tonapi_transaction_trace_preview_v1"
_TRANSACTION_HASH_RE = re.compile(r"^[0-9a-f]{64}$")


class WalletTraceEvidenceNotFound(LookupError):
    """The requested persisted run or transaction does not exist."""


class WalletTraceEvidenceIneligible(ValueError):
    """Persisted identity or current provider configuration is ineligible."""


class WalletTraceEvidenceProviderFailure(RuntimeError):
    """The provider response failed transport, protocol, or anchor checks."""


def get_wallet_transaction_trace_evidence(
    run_id: int,
    transaction_hash: str,
    session: Session,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Fetch one sanitized trace summary without mutating persisted evidence."""
    run, transaction = resolve_wallet_transaction_trace_anchor(
        run_id,
        transaction_hash,
        session,
    )

    settings = settings or get_settings()
    _require_guarded_live_tonapi(settings, run)
    _require_eligible_stored_identity(run, transaction, transaction_hash)

    adapter = TonapiAdapter(settings)
    result = adapter.get_transaction_trace_evidence_preview(transaction_hash)
    if not result.ok:
        detail = result.message or "TonAPI trace evidence request failed."
        raise WalletTraceEvidenceProviderFailure(
            _sanitize_provider_message(detail, settings)
        )
    data = result.data
    if not isinstance(data, dict):
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI trace evidence response was not an object."
        )
    anchor = data.get("anchor")
    summary = data.get("summary")
    trace_state = data.get("trace_state")
    if (
        not isinstance(anchor, dict)
        or not isinstance(summary, dict)
        or trace_state not in ("finalized", "pending")
    ):
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI trace evidence response was incomplete."
        )
    if (
        anchor.get("transaction_hash")
        != transaction.transaction_hash_canonical
        or anchor.get("logical_time")
        != transaction.transaction_logical_time_canonical
        or anchor.get("account_canonical")
        != transaction.transaction_account_canonical
    ):
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI trace anchor did not match the stored transaction identity."
        )

    return {
        "contract_version": TRACE_EVIDENCE_CONTRACT_VERSION,
        "run_id": str(run.id),
        "provider": "tonapi",
        "source_status": "live",
        "trace_state": trace_state,
        "anchor": {
            "transaction_hash": anchor["transaction_hash"],
            "logical_time": anchor["logical_time"],
            "account_canonical": anchor["account_canonical"],
            "matches_stored_transaction": True,
        },
        "summary": summary,
        "is_provider_indexed_low_level_trace": True,
        "is_blockchain_proof_verified": False,
        "is_authoritative_activity_identity": False,
        "semantic_reconstruction_applied": False,
        "activity_merge_applied": False,
        "deduplication_applied": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "is_ownership_proof": False,
        "message": (
            "Provider-indexed low-level trace structure matched the stored "
            "transaction anchor. No blockchain proof was verified and no "
            "semantic activity reconstruction was applied."
        ),
    }


def resolve_wallet_transaction_trace_anchor(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> tuple[WalletIngestionRun, WalletTransaction]:
    """Resolve one exact persisted run/transaction pair without provider access."""
    if (
        isinstance(run_id, bool)
        or not isinstance(run_id, int)
        or not 1 <= run_id <= 2**63 - 1
    ):
        raise WalletTraceEvidenceNotFound("Wallet ingestion run not found")
    if (
        not isinstance(transaction_hash, str)
        or _TRANSACTION_HASH_RE.fullmatch(transaction_hash) is None
    ):
        raise WalletTraceEvidenceNotFound("Wallet transaction not found")

    with session.no_autoflush:
        run = session.get(WalletIngestionRun, run_id)
        if run is None:
            raise WalletTraceEvidenceNotFound(
                "Wallet ingestion run not found"
            )
        transactions = list(
            session.scalars(
                select(WalletTransaction)
                .where(WalletTransaction.run_id == run_id)
                .where(
                    func.lower(WalletTransaction.tx_hash)
                    == transaction_hash
                )
                .limit(2)
            )
        )
    if not transactions:
        raise WalletTraceEvidenceNotFound("Wallet transaction not found")
    if len(transactions) != 1:
        raise WalletTraceEvidenceIneligible(
            "Stored transaction identity is ambiguous."
        )
    return run, transactions[0]


def _require_guarded_live_tonapi(
    settings: Settings,
    run: WalletIngestionRun,
) -> None:
    expected_network = f"ton-{settings.ton_network}"
    adapter = TonapiAdapter(settings)
    if (
        not settings.is_real
        or settings.wallet_activity_provider != "tonapi"
        or not settings.wallet_activity_live_enabled
        or not adapter.is_configured()
    ):
        raise WalletTraceEvidenceIneligible(
            "Trace evidence requires guarded live TonAPI configuration."
        )
    if run.data_mode != "real" or run.wallet_network != expected_network:
        raise WalletTraceEvidenceIneligible(
            "Stored run is not eligible for the current TonAPI network."
        )


def _sanitize_provider_message(value: Any, settings: Settings) -> str:
    text = str(value).strip() or "TonAPI trace evidence request failed."
    if settings.tonapi_api_key:
        text = text.replace(settings.tonapi_api_key, "[redacted]")
    return text[:500]


def _require_eligible_stored_identity(
    run: WalletIngestionRun,
    transaction: WalletTransaction,
    requested_hash: str,
) -> None:
    raw: Any = None
    if isinstance(transaction.raw_json, str):
        try:
            raw = json.loads(transaction.raw_json)
        except (TypeError, ValueError):
            raw = None
    derived = derive_ton_transaction_identity(
        network=run.wallet_network,
        account_address_canonical=run.wallet_address_canonical,
        account_identity_status=run.wallet_identity_status,
        account_identity_version=run.wallet_identity_version,
        account_workchain_id=run.wallet_workchain_id,
        account_id_hex=run.wallet_account_id_hex,
        logical_time=transaction.logical_time,
        transaction_hash=transaction.tx_hash,
        data_mode=run.data_mode,
        source_status=transaction.source_status,
        provider=transaction.provider,
        raw=raw,
    )
    persisted_matches = (
        transaction.transaction_identity_status == derived.status
        and transaction.transaction_identity_version == derived.version
        and transaction.transaction_network == derived.network
        and transaction.transaction_account_canonical
        == derived.account_canonical
        and transaction.transaction_logical_time_canonical
        == derived.logical_time_canonical
        and transaction.transaction_hash_canonical == derived.hash_canonical
        and transaction.transaction_identity_key == derived.key
    )
    if (
        derived.status != "network_scoped"
        or not derived.is_deduplication_identity
        or not persisted_matches
        or derived.hash_canonical != requested_hash
    ):
        raise WalletTraceEvidenceIneligible(
            "Stored transaction lacks a coherent network-scoped identity."
        )
