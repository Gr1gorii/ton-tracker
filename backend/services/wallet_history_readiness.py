"""Diagnostic multi-run wallet-history readiness assessment.

This module deliberately does not merge or deduplicate persisted activity and
never feeds PnL.  It only measures the evidence that would need to be made
canonical before multiple legacy ingestion runs could become a history or
cost-basis source.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from sqlalchemy.orm import Session

from models import WalletIngestionRun
from services.wallet_activity_ingestion import wallet_ingestion_run_to_response

_EXACT_SWAP_ORDINAL_KEYS = ("action_id", "action_index", "action_ordinal")
_MAX_IDENTITY_GROUPS = 200
_UNAVAILABLE_WALLET_IDENTITY = {
    "status": "unavailable",
    "version": "unavailable",
    "network": "ton-unknown",
    "canonical_address": None,
    "workchain_id": None,
    "account_id_hex": None,
    "submitted_format": "unrecognized",
    "bounceable": None,
    "testnet_only": None,
    "is_account_existence_proof": False,
    "is_ownership_proof": False,
}


def _isoformat(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = f"{cleaned[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _stable_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_stable_json(value).encode("utf-8")).hexdigest()


def _normalized_decimal(value: Any) -> str | None:
    if value is None or value == "":
        return None
    try:
        decimal_value = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    if decimal_value == 0:
        return "0"
    return format(decimal_value.normalize(), "f")


def _normalized_timestamp(value: Any) -> str | None:
    parsed = _parse_timestamp(value)
    if parsed is not None:
        return _isoformat(parsed)
    return str(value) if value else None


def _transaction_semantic_payload(transaction: dict[str, Any]) -> dict[str, Any]:
    return {
        "logical_time": transaction.get("logical_time"),
        "timestamp": _normalized_timestamp(transaction.get("timestamp")),
        "fee_ton": _normalized_decimal(transaction.get("fee_ton")),
        "success": transaction.get("success"),
        "provider": transaction.get("provider"),
        "source_status": transaction.get("source_status"),
    }


def _swap_semantic_payload(swap: dict[str, Any]) -> dict[str, Any]:
    return {
        "timestamp": _normalized_timestamp(swap.get("timestamp")),
        "dex": swap.get("dex"),
        "token_in": swap.get("token_in"),
        "token_in_address": swap.get("token_in_address"),
        "amount_in": _normalized_decimal(swap.get("amount_in")),
        "token_out": swap.get("token_out"),
        "token_out_address": swap.get("token_out_address"),
        "amount_out": _normalized_decimal(swap.get("amount_out")),
        "estimated_usd": _normalized_decimal(swap.get("estimated_usd")),
        "provider": swap.get("provider"),
        "source_status": swap.get("source_status"),
    }


def _activity_timestamps(run: dict[str, Any]) -> list[datetime]:
    timestamps: list[datetime] = []
    for collection in ("transfers", "transactions", "swaps"):
        for row in run.get(collection) or []:
            parsed = _parse_timestamp(row.get("timestamp"))
            if parsed is not None:
                timestamps.append(parsed)
    return timestamps


def _wallet_identity(run: dict[str, Any]) -> dict[str, Any]:
    identity = run.get("wallet_identity")
    if not isinstance(identity, dict):
        return dict(_UNAVAILABLE_WALLET_IDENTITY)
    return {**_UNAVAILABLE_WALLET_IDENTITY, **identity}


def _scoped_wallet_identity_key(run: dict[str, Any]) -> tuple[str, str] | None:
    identity = _wallet_identity(run)
    network = identity.get("network")
    canonical_address = identity.get("canonical_address")
    if identity.get("status") != "network_scoped":
        return None
    if network not in {"ton-mainnet", "ton-testnet"}:
        return None
    if not isinstance(canonical_address, str) or not canonical_address:
        return None
    return network, canonical_address


def _run_scope(run: dict[str, Any], target_run_id: int) -> dict[str, Any]:
    transfers = run.get("transfers") or []
    transactions = run.get("transactions") or []
    swaps = run.get("swaps") or []
    timestamps = _activity_timestamps(run)
    activity_count = len(transfers) + len(transactions) + len(swaps)
    requested_start = _parse_timestamp(run.get("_custom_start"))
    requested_end = _parse_timestamp(run.get("_custom_end"))
    outside_requested_bounds = 0
    if requested_start is not None and requested_end is not None:
        outside_requested_bounds = sum(
            1
            for timestamp in timestamps
            if timestamp < requested_start or timestamp > requested_end
        )
    return {
        "run_id": run["run_id"],
        "is_target": run["run_id"] == target_run_id,
        "wallet_address": run["wallet_address"],
        "wallet_identity": _wallet_identity(run),
        "time_window": run["time_window"],
        "status": run["status"],
        "created_at": run.get("_created_at"),
        "requested_start": run.get("_custom_start"),
        "requested_end": run.get("_custom_end"),
        "requested_bounds_verified": False,
        "observed_activity_start": _isoformat(min(timestamps)) if timestamps else None,
        "observed_activity_end": _isoformat(max(timestamps)) if timestamps else None,
        "transfer_count": len(transfers),
        "transaction_count": len(transactions),
        "swap_count": len(swaps),
        "timestamped_activity_count": len(timestamps),
        "untimestamped_activity_count": activity_count - len(timestamps),
        "outside_requested_bounds_count": outside_requested_bounds,
        "requested_surfaces": list(run.get("requested_surfaces") or []),
        "unavailable_surfaces": list(run.get("unavailable_surfaces") or []),
    }


def _identity_groups(
    observations: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str]],
    ]
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for (identity_type, identity), rows in observations.items():
        run_ids = sorted({row[0] for row in rows})
        if len(run_ids) < 2:
            continue
        payloads = {_fingerprint(row[1]) for row in rows}
        strengths = {row[2] for row in rows}
        groups.append(
            {
                "identity": identity,
                "identity_type": identity_type,
                "identity_strength": (
                    "exact" if strengths == {"exact"} else "weak"
                ),
                "run_ids": run_ids,
                "observation_count": len(rows),
                "distinct_payload_count": len(payloads),
                "has_conflict": len(payloads) > 1,
            }
        )
    return sorted(groups, key=lambda group: (group["identity_type"], group["identity"]))


def _transaction_groups(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    observations: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str]],
    ] = defaultdict(list)
    for run in runs:
        for transaction in run.get("transactions") or []:
            tx_hash = transaction.get("tx_hash")
            if not isinstance(tx_hash, str) or not tx_hash.strip():
                continue
            identity = tx_hash.strip()
            observations[("transaction_hash", identity)].append(
                (
                    run["run_id"],
                    _transaction_semantic_payload(transaction),
                    "exact",
                )
            )
    return _identity_groups(observations)


def _swap_identity(swap: dict[str, Any]) -> tuple[str, str, str]:
    raw = swap.get("raw") if isinstance(swap.get("raw"), dict) else {}
    provider = swap.get("provider")
    provider_key = provider.strip() if isinstance(provider, str) else "unknown"
    event_id = raw.get("event_id")
    if not isinstance(event_id, str) or not event_id.strip():
        event_id = swap.get("tx_hash")
    event_id = event_id.strip() if isinstance(event_id, str) else None

    if event_id:
        for key in _EXACT_SWAP_ORDINAL_KEYS:
            ordinal = raw.get(key)
            if ordinal is not None and str(ordinal).strip():
                return (
                    f"{provider_key}:{event_id}:{key}:{str(ordinal).strip()}",
                    "event_action",
                    "exact",
                )
        return f"{provider_key}:{event_id}", "event_reference", "weak"

    signature = {
        "timestamp": _normalized_timestamp(swap.get("timestamp")),
        "dex": swap.get("dex"),
        "token_in": swap.get("token_in_address") or swap.get("token_in"),
        "amount_in": _normalized_decimal(swap.get("amount_in")),
        "token_out": swap.get("token_out_address") or swap.get("token_out"),
        "amount_out": _normalized_decimal(swap.get("amount_out")),
        "provider": provider_key,
    }
    return f"sha256:{_fingerprint(signature)}", "swap_fingerprint", "weak"


def _swap_groups(runs: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    observations: dict[
        tuple[str, str],
        list[tuple[int, dict[str, Any], str]],
    ] = defaultdict(list)
    for run in runs:
        for swap in run.get("swaps") or []:
            identity, identity_type, strength = _swap_identity(swap)
            observations[(identity_type, identity)].append(
                (
                    run["run_id"],
                    _swap_semantic_payload(swap),
                    strength,
                )
            )
    return _identity_groups(observations)


def _coverage(
    runs: list[dict[str, Any]],
    transaction_groups: list[dict[str, Any]],
    swap_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    transfers = [row for run in runs for row in (run.get("transfers") or [])]
    transactions = [row for run in runs for row in (run.get("transactions") or [])]
    swaps = [row for run in runs for row in (run.get("swaps") or [])]
    timestamped = sum(len(_activity_timestamps(run)) for run in runs)

    exact_swap_observations = 0
    non_ton_legs = 0
    addressed_non_ton_legs = 0
    fee_hash_matches = 0

    for run in runs:
        transaction_fees = {
            row.get("tx_hash"): row.get("fee_ton")
            for row in run.get("transactions") or []
            if row.get("tx_hash")
        }
        for swap in run.get("swaps") or []:
            _, _, strength = _swap_identity(swap)
            if strength == "exact":
                exact_swap_observations += 1
            for token_key, address_key in (
                ("token_in", "token_in_address"),
                ("token_out", "token_out_address"),
            ):
                token = swap.get(token_key)
                if isinstance(token, str) and token.strip().upper() == "TON":
                    continue
                non_ton_legs += 1
                address = swap.get(address_key)
                if isinstance(address, str) and address.strip():
                    addressed_non_ton_legs += 1
            tx_hash = swap.get("tx_hash")
            if tx_hash in transaction_fees and transaction_fees[tx_hash] not in (
                None,
                "",
            ):
                fee_hash_matches += 1

    asset_coverage_state = (
        "not_observed"
        if non_ton_legs == 0
        else "complete"
        if addressed_non_ton_legs == non_ton_legs
        else "incomplete"
    )
    fee_coverage_state = (
        "not_observed"
        if not swaps
        else "complete"
        if fee_hash_matches == len(swaps)
        else "incomplete"
    )

    return {
        "activity_observations": len(transfers) + len(transactions) + len(swaps),
        "timestamped_activity_observations": timestamped,
        "transaction_observations": len(transactions),
        "transaction_observations_with_hash": sum(
            1
            for row in transactions
            if isinstance(row.get("tx_hash"), str) and row["tx_hash"].strip()
        ),
        "overlapping_transaction_identity_groups": len(transaction_groups),
        "conflicting_transaction_identity_groups": sum(
            1 for group in transaction_groups if group["has_conflict"]
        ),
        "swap_observations": len(swaps),
        "swap_observations_with_exact_identity": exact_swap_observations,
        "overlapping_exact_swap_identity_groups": sum(
            1 for group in swap_groups if group["identity_strength"] == "exact"
        ),
        "overlapping_weak_swap_identity_groups": sum(
            1 for group in swap_groups if group["identity_strength"] == "weak"
        ),
        "conflicting_swap_identity_groups": sum(
            1 for group in swap_groups if group["has_conflict"]
        ),
        "non_ton_swap_legs": non_ton_legs,
        "addressed_non_ton_swap_legs": addressed_non_ton_legs,
        "asset_address_coverage_state": asset_coverage_state,
        "fee_link_candidate_swaps": len(swaps),
        "same_run_fee_hash_match_candidates": fee_hash_matches,
        "fee_hash_match_coverage_state": fee_coverage_state,
        "fee_linkage_contract_verified": False,
    }


def _blocker(
    code: str,
    reason: str,
    *,
    run_ids: list[int] | None = None,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "code": code,
        "reason": reason,
        "run_ids": run_ids or [],
        "evidence": evidence or {},
    }


def _build_blockers(
    runs: list[dict[str, Any]],
    transaction_groups: list[dict[str, Any]],
    swap_groups: list[dict[str, Any]],
    coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    run_ids = [run["run_id"] for run in runs]
    blockers = [
        _blocker(
            "requested_bounds_unverified",
            "Persisted request windows are not proof that provider rows were filtered or fully paginated to those bounds.",
            run_ids=run_ids,
        ),
        _blocker(
            "pagination_completeness_unverified",
            "Legacy ingestion runs do not persist pagination completion evidence or a terminal provider cursor.",
            run_ids=run_ids,
        ),
        _blocker(
            "canonical_activity_identity_unavailable",
            "Transaction, transfer, swap-action, jetton-asset, and counterparty rows do not yet share a complete canonical identity contract.",
            run_ids=run_ids,
        ),
        _blocker(
            "history_completeness_unverified",
            "An explicit run set is not proof of complete acquisition history before the target run.",
            run_ids=run_ids,
        ),
        _blocker(
            "deduplication_not_applied",
            "This report exposes overlap but deliberately does not merge or remove activity rows.",
            run_ids=run_ids,
        ),
        _blocker(
            "fee_linkage_contract_unverified",
            "A same-run string match between swap event references and transaction hashes is only a candidate, not a verified fee relationship.",
            run_ids=run_ids,
        ),
        _blocker(
            "asset_identity_contract_unverified",
            "Address presence alone does not provide a canonical network, workchain, and asset revision identity.",
            run_ids=run_ids,
        ),
    ]

    if runs[0]["data_mode"] == "mock":
        blockers.append(
            _blocker(
                "mock_data_not_cost_basis",
                "Deterministic mock fixtures are not on-chain history and cannot establish cost basis.",
                run_ids=run_ids,
            )
        )

    unscoped_wallet_runs = [
        run["run_id"]
        for run in runs
        if _scoped_wallet_identity_key(run) is None
    ]
    if unscoped_wallet_runs:
        blockers.append(
            _blocker(
                "wallet_identity_unavailable",
                "At least one run wallet lacks a network-scoped canonical TON address; exact submitted strings are used only as a legacy diagnostic fallback.",
                run_ids=unscoped_wallet_runs,
            )
        )

    unsuccessful = [run["run_id"] for run in runs if run.get("status") != "success"]
    if unsuccessful:
        blockers.append(
            _blocker(
                "run_status_not_success",
                "Every candidate run must have a successful terminal status before canonical history work can begin.",
                run_ids=unsuccessful,
            )
        )

    unavailable = {
        str(run["run_id"]): list(run.get("unavailable_surfaces") or [])
        for run in runs
        if run.get("unavailable_surfaces")
    }
    if unavailable:
        blockers.append(
            _blocker(
                "requested_surfaces_unavailable",
                "At least one run reports requested wallet-activity surfaces as unavailable.",
                run_ids=[int(run_id) for run_id in unavailable],
                evidence={"unavailable_surfaces_by_run": unavailable},
            )
        )

    activity_observations = coverage["activity_observations"]
    if activity_observations == 0:
        blockers.append(
            _blocker(
                "no_activity_observed",
                "The selected runs contain no transfer, transaction, or swap observations.",
                run_ids=run_ids,
            )
        )
    elif coverage["timestamped_activity_observations"] < activity_observations:
        blockers.append(
            _blocker(
                "activity_timestamps_incomplete",
                "Some activity observations have missing or invalid timestamps and cannot be placed in history order.",
                run_ids=run_ids,
                evidence={
                    "timestamped": coverage["timestamped_activity_observations"],
                    "total": activity_observations,
                },
            )
        )

    if coverage["transaction_observations_with_hash"] < coverage[
        "transaction_observations"
    ]:
        blockers.append(
            _blocker(
                "transaction_identity_coverage_incomplete",
                "Some transaction observations lack a nonblank transaction hash.",
                run_ids=run_ids,
                evidence={
                    "with_hash": coverage["transaction_observations_with_hash"],
                    "total": coverage["transaction_observations"],
                },
            )
        )

    outside_bounds = {
        str(scope["run_id"]): scope["outside_requested_bounds_count"]
        for scope in (_run_scope(run, -1) for run in runs)
        if scope["outside_requested_bounds_count"] > 0
    }
    if outside_bounds:
        blockers.append(
            _blocker(
                "observations_outside_custom_bounds",
                "At least one custom-window run contains observed activity outside its stored request bounds.",
                run_ids=[int(run_id) for run_id in outside_bounds],
                evidence={"outside_observations_by_run": outside_bounds},
            )
        )

    if transaction_groups:
        blockers.append(
            _blocker(
                "overlapping_transaction_history",
                "Exact transaction hashes overlap across runs, so concatenating rows would double count activity.",
                run_ids=run_ids,
                evidence={"identity_group_count": len(transaction_groups)},
            )
        )
    transaction_conflicts = [
        group["identity"] for group in transaction_groups if group["has_conflict"]
    ]
    if transaction_conflicts:
        blockers.append(
            _blocker(
                "transaction_payload_conflicts",
                "The same exact transaction hash has differing persisted payloads across runs.",
                run_ids=run_ids,
                evidence={
                    "identity_count": len(transaction_conflicts),
                    "identity_sample": transaction_conflicts[:50],
                },
            )
        )

    if coverage["swap_observations"] > coverage["swap_observations_with_exact_identity"]:
        blockers.append(
            _blocker(
                "weak_swap_identity",
                "At least one swap lacks the event-plus-action identity needed for exact cross-run deduplication.",
                run_ids=run_ids,
                evidence={
                    "swap_observations": coverage["swap_observations"],
                    "exact_identity_observations": coverage[
                        "swap_observations_with_exact_identity"
                    ],
                },
            )
        )
    swap_conflicts = [group["identity"] for group in swap_groups if group["has_conflict"]]
    if swap_conflicts:
        blockers.append(
            _blocker(
                "swap_payload_conflicts",
                "A repeated swap identity has differing persisted payloads; weak event identities can also represent multiple actions.",
                run_ids=run_ids,
                evidence={
                    "identity_count": len(swap_conflicts),
                    "identity_sample": swap_conflicts[:50],
                },
            )
        )

    if coverage["addressed_non_ton_swap_legs"] < coverage["non_ton_swap_legs"]:
        blockers.append(
            _blocker(
                "asset_address_coverage_incomplete",
                "Some non-TON swap legs lack a jetton master address and cannot be canonically grouped by symbol alone.",
                run_ids=run_ids,
                evidence={
                    "addressed": coverage["addressed_non_ton_swap_legs"],
                    "total": coverage["non_ton_swap_legs"],
                },
            )
        )

    if coverage["same_run_fee_hash_match_candidates"] < coverage[
        "fee_link_candidate_swaps"
    ]:
        blockers.append(
            _blocker(
                "fee_linkage_incomplete",
                "Some swap rows do not have even a same-run hash-match candidate transaction with a recorded fee.",
                run_ids=run_ids,
                evidence={
                    "hash_match_candidates": coverage[
                        "same_run_fee_hash_match_candidates"
                    ],
                    "total": coverage["fee_link_candidate_swaps"],
                },
            )
        )

    return blockers


def assess_wallet_history_readiness(
    run_responses: list[dict[str, Any]],
    target_run_id: int,
) -> dict[str, Any]:
    """Pure diagnostic assessment over explicit persisted-run payloads."""
    if len(run_responses) < 2:
        raise ValueError("At least 2 distinct run_ids are required.")
    if len(run_responses) > 50:
        raise ValueError("At most 50 run_ids can be inspected at once.")

    run_ids = [run.get("run_id") for run in run_responses]
    if any(not isinstance(run_id, int) for run_id in run_ids):
        raise ValueError("Every run must have a persisted integer run_id.")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("run_ids must contain 2-50 distinct ids.")
    if target_run_id not in run_ids:
        raise ValueError("target_run_id must be included in run_ids.")

    target_run = next(
        run for run in run_responses if run.get("run_id") == target_run_id
    )
    wallet_addresses = {run.get("wallet_address") for run in run_responses}
    scoped_identity_keys = [
        _scoped_wallet_identity_key(run) for run in run_responses
    ]
    if all(key is not None for key in scoped_identity_keys):
        if len(set(scoped_identity_keys)) != 1:
            raise ValueError(
                "All history-readiness runs must resolve to the same network-scoped canonical wallet identity."
            )
    elif len(wallet_addresses) != 1 or not next(iter(wallet_addresses), None):
        raise ValueError(
            "Runs without complete canonical wallet identity must use the exact same wallet_address."
        )
    data_modes = {run.get("data_mode") for run in run_responses}
    if len(data_modes) != 1 or next(iter(data_modes), None) not in {"mock", "real"}:
        raise ValueError(
            "All history-readiness runs must use the same data_mode."
        )

    run_responses = sorted(run_responses, key=lambda run: run["run_id"])
    run_ids = [run["run_id"] for run in run_responses]
    transaction_groups = _transaction_groups(run_responses)
    swap_groups = _swap_groups(run_responses)
    coverage = _coverage(run_responses, transaction_groups, swap_groups)
    scopes = [_run_scope(run, target_run_id) for run in run_responses]
    all_timestamps = [
        timestamp for run in run_responses for timestamp in _activity_timestamps(run)
    ]

    return {
        "analysis_version": "wallet_history_readiness_v0.22.0",
        "target_run_id": target_run_id,
        "run_ids": run_ids,
        "wallet_address": target_run["wallet_address"],
        "wallet_identity": _wallet_identity(target_run),
        "data_mode": next(iter(data_modes)),
        "requested_bounds_verified": False,
        "observed_activity_start": (
            _isoformat(min(all_timestamps)) if all_timestamps else None
        ),
        "observed_activity_end": (
            _isoformat(max(all_timestamps)) if all_timestamps else None
        ),
        "runs": scopes,
        "transaction_identity_groups": transaction_groups[:_MAX_IDENTITY_GROUPS],
        "swap_identity_groups": swap_groups[:_MAX_IDENTITY_GROUPS],
        "transaction_identity_groups_total": len(transaction_groups),
        "swap_identity_groups_total": len(swap_groups),
        "evidence_groups_truncated": (
            len(transaction_groups) > _MAX_IDENTITY_GROUPS
            or len(swap_groups) > _MAX_IDENTITY_GROUPS
        ),
        "coverage": coverage,
        "blockers": _build_blockers(
            run_responses, transaction_groups, swap_groups, coverage
        ),
        "history_complete": False,
        "deduplication_applied": False,
        "is_cost_basis": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "note": (
            "Diagnostic evidence only. This report does not merge or deduplicate "
            "activity, prove complete wallet history, establish cost basis, or "
            "change any PnL result."
        ),
    }


def build_wallet_history_readiness(
    run_ids: list[int],
    target_run_id: int,
    session: Session,
) -> dict[str, Any]:
    """Load explicit runs and delegate to the pure readiness assessment."""
    if len(run_ids) < 2:
        raise ValueError("At least 2 distinct run_ids are required.")
    if len(run_ids) > 50:
        raise ValueError("At most 50 run_ids can be inspected at once.")
    if len(set(run_ids)) != len(run_ids):
        raise ValueError("run_ids must contain 2-50 distinct ids.")
    if target_run_id not in run_ids:
        raise ValueError("target_run_id must be included in run_ids.")

    responses: list[dict[str, Any]] = []
    with session.no_autoflush:
        for run_id in sorted(run_ids):
            run = session.get(WalletIngestionRun, run_id)
            if run is None:
                raise LookupError(f"Wallet ingestion run {run_id} not found")
            response = wallet_ingestion_run_to_response(run)
            response["_created_at"] = _isoformat(run.created_at)
            response["_custom_start"] = _isoformat(run.custom_start)
            response["_custom_end"] = _isoformat(run.custom_end)
            responses.append(response)

    return assess_wallet_history_readiness(responses, target_run_id)
