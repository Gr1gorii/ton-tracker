"""Explainable Wallet Case Findings and Flows over one pinned revision."""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Iterable

from sqlalchemy.orm import Session

from models import LOCAL_SINGLE_USER_SCOPE
from services.wallet_case_activity import (
    WalletCaseActivityNotFound,
    WalletCaseActivityScopeTooLarge,
    WalletCaseActivityService,
    WalletCaseActivitySnapshotConflict,
    WalletCaseActivitySnapshotNotFound,
)
from services.wallet_case_evidence import (
    CaseEvidenceNotFound,
    CaseEvidenceScopeTooLarge,
    CaseEvidenceService,
    CaseEvidenceSnapshotConflict,
    CaseEvidenceSnapshotNotFound,
    CaseEvidenceStoredConflict,
)
from wallet_case_findings_schemas import case_findings_content_hash


MAX_FLOW_GROUPS = 50
MAX_SUPPORTING_ACTIVITIES = 50
MAX_PATTERN_FINDINGS = 20
_EVIDENCE_SCORE = {
    "fixture": 0,
    "normalized_provider_observation": 1,
    "locally_verified": 2,
    "chain_inclusion_proven": 3,
}


class WalletCaseFindingsNotFound(LookupError):
    code = "case_findings_not_found"


class WalletCaseFindingsSnapshotNotFound(LookupError):
    code = "case_findings_snapshot_not_found"


class WalletCaseFindingsConflict(RuntimeError):
    code = "case_findings_conflict"


class WalletCaseFindingsScopeTooLarge(RuntimeError):
    code = "case_findings_scope_too_large"


class WalletCaseFindingsService:
    def __init__(
        self,
        session: Session,
        *,
        owner_scope_id: str = LOCAL_SINGLE_USER_SCOPE,
    ) -> None:
        self.session = session
        self.owner_scope_id = owner_scope_id

    def build(
        self,
        case_public_id: str,
        *,
        snapshot_public_id: str | None,
    ) -> dict[str, Any]:
        try:
            activity = WalletCaseActivityService(
                self.session,
                owner_scope_id=self.owner_scope_id,
            ).resolve_activity_dataset(
                case_public_id,
                snapshot_public_id=snapshot_public_id,
            )
        except WalletCaseActivityNotFound as exc:
            raise WalletCaseFindingsNotFound(str(exc)) from exc
        except WalletCaseActivitySnapshotNotFound as exc:
            raise WalletCaseFindingsSnapshotNotFound(str(exc)) from exc
        except WalletCaseActivityScopeTooLarge as exc:
            raise WalletCaseFindingsScopeTooLarge(str(exc)) from exc
        except WalletCaseActivitySnapshotConflict as exc:
            raise WalletCaseFindingsConflict(str(exc)) from exc

        if activity.snapshot is None:
            return {
                "case_public_id": activity.wallet_case.public_id,
                "snapshot_public_id": None,
                "findings": None,
                "limitations": [{
                    "code": "not_synchronized",
                    "message": "Synchronize this Wallet Case before reviewing findings.",
                }],
            }

        try:
            evidence = CaseEvidenceService(
                self.session,
                owner_scope_id=self.owner_scope_id,
            ).catalog(
                case_public_id,
                snapshot_public_id=activity.snapshot.public_id,
                # Runtime availability is mutable and must not alter a pinned,
                # content-addressed findings revision.
                runner_available=True,
            )
        except (CaseEvidenceNotFound, CaseEvidenceSnapshotNotFound) as exc:
            raise WalletCaseFindingsSnapshotNotFound(str(exc)) from exc
        except (CaseEvidenceSnapshotConflict, CaseEvidenceStoredConflict) as exc:
            raise WalletCaseFindingsConflict(str(exc)) from exc
        except CaseEvidenceScopeTooLarge as exc:
            raise WalletCaseFindingsScopeTooLarge(str(exc)) from exc
        if (
            evidence["snapshot"] is None
            or evidence["snapshot"]["public_id"] != activity.snapshot.public_id
        ):
            raise WalletCaseFindingsConflict(
                "Findings Activity and Evidence revisions do not share one snapshot."
            )

        evidence_levels, evidence_revision = _evidence_basis(
            activity.items,
            evidence,
        )
        flows, flow_state = _flow_summary(activity.items)
        findings, finding_state = _findings(
            activity.items,
            aggregate=activity.aggregate,
            gaps=activity.gaps,
            evidence_levels=evidence_levels,
            demo=activity.wallet_case.data_environment == "demo",
            flow_state=flow_state,
        )
        activity_revision = {
            "digest_sha256": _digest({
                "items": sorted(activity.items, key=lambda item: item["public_id"]),
                "aggregate": activity.aggregate,
                "observed_period": activity.observed_period,
                "gaps": activity.gaps,
                "limitations": activity.limitations,
            }),
            "aggregate": activity.aggregate,
            "observed_period": activity.observed_period,
        }
        limitations = _limitations(
            activity.limitations,
            evidence_revision=evidence_revision,
            flows=flows,
            flow_state=flow_state,
            finding_state=finding_state,
        )
        document: dict[str, Any] = {
            "contract_version": "wallet_case_findings_v1",
            "case_public_id": activity.wallet_case.public_id,
            "snapshot_public_id": activity.snapshot.public_id,
            "subject": {
                "network": activity.wallet_case.network,
                "data_environment": activity.wallet_case.data_environment,
                "wallet_account_canonical": activity.wallet_case.canonical_wallet_key,
            },
            "snapshot": activity.snapshot_record,
            "activity_revision": activity_revision,
            "evidence_revision": evidence_revision,
            "flows": flows,
            "findings": findings,
            "gaps": list(activity.gaps),
            "limitations": limitations,
            "truth_boundaries": {
                "establishes_complete_wallet_history": False,
                "establishes_ownership_or_control": False,
                "establishes_illicit_or_safe_status": False,
                "absence_of_findings_means_safe": False,
                "cross_asset_amounts_are_comparable": False,
                "includes_raw_provider_payloads": False,
            },
        }
        content_hash = case_findings_content_hash(document)
        document["public_id"] = f"fset_{content_hash}"
        document["content_hash_sha256"] = content_hash
        return {
            "case_public_id": activity.wallet_case.public_id,
            "snapshot_public_id": activity.snapshot.public_id,
            "findings": document,
            "limitations": [],
        }


def _evidence_basis(
    items: tuple[dict[str, Any], ...],
    catalog: dict[str, Any],
) -> tuple[dict[str, str], dict[str, Any]]:
    levels = {
        item["public_id"]: (
            "fixture"
            if item["provenance"]["data_origin"] == "demo_fixture"
            else "normalized_provider_observation"
        )
        for item in items
    }
    strongest: dict[str, dict[str, Any]] = {}
    projection: list[dict[str, Any]] = []
    for row in catalog["verifications"]:
        projection.append({
            "public_id": row["public_id"],
            "activity_public_id": row["activity_public_id"],
            "status_version": row["status_version"],
            "state": row["state"],
            "progress": row["progress"]["current"],
            "highest_evidence_level": row["highest_evidence_level"],
            "result_digest_sha256": (
                row["result"]["verification_digest_sha256"]
                if row["result"] is not None
                else None
            ),
            "updated_at": row["updated_at"],
        })
        current = strongest.get(row["activity_public_id"])
        score = (row["progress"]["current"], row["status_version"], row["public_id"])
        if current is None or score > (
            current["progress"]["current"],
            current["status_version"],
            current["public_id"],
        ):
            strongest[row["activity_public_id"]] = row
    for activity_public_id, row in strongest.items():
        if activity_public_id not in levels:
            continue
        progress = row["progress"]["current"]
        if progress >= 3:
            levels[activity_public_id] = "chain_inclusion_proven"
        elif progress >= 2:
            levels[activity_public_id] = "locally_verified"
    total = catalog["aggregate"]["total"]
    returned = len(catalog["verifications"])
    return levels, {
        "digest_sha256": _digest(sorted(projection, key=lambda item: item["public_id"])),
        "total_attempts": total,
        "returned_revalidated": returned,
        "history_truncated": total > returned,
    }


def _flow_summary(
    items: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    counterparties: dict[str, dict[str, Any]] = {}
    protocols: dict[str, dict[str, Any]] = {}
    unavailable_asset_ids: set[str] = set()
    unavailable_counterparty_ids: set[str] = set()
    unrecognized_protocol_ids: set[str] = set()

    for item in items:
        activity_id = item["public_id"]
        if item["kind"] == "transfer":
            asset = item["assets"][0]
            if asset["identity_status"] == "network_scoped":
                direction = item["direction"]
                _add_asset_observation(
                    assets,
                    asset,
                    activity_id,
                    flow_direction=direction,
                    amount=item["details"]["amount"],
                )
            else:
                unavailable_asset_ids.add(activity_id)
            counterparty = item["counterparty"]
            if (
                counterparty is not None
                and counterparty["identity_status"] == "network_scoped"
            ):
                key = counterparty["canonical_address"]
                group = counterparties.setdefault(key, {
                    "canonical_address": key,
                    "incoming_observations": 0,
                    "outgoing_observations": 0,
                    "unknown_direction_observations": 0,
                    "support": set(),
                })
                field = {
                    "in": "incoming_observations",
                    "out": "outgoing_observations",
                    "unknown": "unknown_direction_observations",
                }[item["direction"]]
                group[field] += 1
                group["support"].add(activity_id)
            else:
                unavailable_counterparty_ids.add(activity_id)
        elif item["kind"] == "swap":
            by_role = {asset["role"]: asset for asset in item["assets"]}
            input_asset = by_role["in"]
            output_asset = by_role["out"]
            if input_asset["identity_status"] == "network_scoped":
                _add_asset_observation(
                    assets,
                    input_asset,
                    activity_id,
                    flow_direction="out",
                    amount=item["details"]["amount_in"],
                )
            else:
                unavailable_asset_ids.add(activity_id)
            if output_asset["identity_status"] == "network_scoped":
                _add_asset_observation(
                    assets,
                    output_asset,
                    activity_id,
                    flow_direction="in",
                    amount=item["details"]["amount_out"],
                )
            else:
                unavailable_asset_ids.add(activity_id)
            protocol = item["protocol"]
            if protocol["status"] == "recognized":
                key = protocol["id"]
                group = protocols.setdefault(key, {
                    "protocol_id": key,
                    "family": protocol["family"],
                    "version": protocol["version"],
                    "label": protocol["label"],
                    "swap_observations": 0,
                    "support": set(),
                })
                group["swap_observations"] += 1
                group["support"].add(activity_id)
            else:
                unrecognized_protocol_ids.add(activity_id)

    asset_rows = [_asset_flow(value) for value in assets.values()]
    asset_rows.sort(
        key=lambda item: (
            -item["inflow_observations"]
            - item["outflow_observations"]
            - item["unknown_direction_observations"],
            item["asset_id"],
        )
    )
    counterparty_rows = [_counterparty_flow(value) for value in counterparties.values()]
    counterparty_rows.sort(
        key=lambda item: (
            -item["incoming_observations"]
            - item["outgoing_observations"]
            - item["unknown_direction_observations"],
            item["canonical_address"],
        )
    )
    protocol_rows = [_protocol_flow(value) for value in protocols.values()]
    protocol_rows.sort(key=lambda item: (-item["swap_observations"], item["protocol_id"]))
    flows = {
        "identified_asset_count": len(asset_rows),
        "returned_asset_count": min(len(asset_rows), MAX_FLOW_GROUPS),
        "assets_truncated": len(asset_rows) > MAX_FLOW_GROUPS,
        "unavailable_asset_observations": len(unavailable_asset_ids),
        "identified_counterparty_count": len(counterparty_rows),
        "returned_counterparty_count": min(len(counterparty_rows), MAX_FLOW_GROUPS),
        "counterparties_truncated": len(counterparty_rows) > MAX_FLOW_GROUPS,
        "unavailable_counterparty_observations": len(unavailable_counterparty_ids),
        "recognized_protocol_count": len(protocol_rows),
        "returned_protocol_count": min(len(protocol_rows), MAX_FLOW_GROUPS),
        "protocols_truncated": len(protocol_rows) > MAX_FLOW_GROUPS,
        "unrecognized_protocol_observations": len(unrecognized_protocol_ids),
        "asset_flows": asset_rows[:MAX_FLOW_GROUPS],
        "counterparty_flows": counterparty_rows[:MAX_FLOW_GROUPS],
        "protocol_flows": protocol_rows[:MAX_FLOW_GROUPS],
    }
    return flows, {
        "unavailable_asset_ids": unavailable_asset_ids,
        "unavailable_counterparty_ids": unavailable_counterparty_ids,
        "counterparty_groups": counterparty_rows,
        "protocol_groups": protocol_rows,
    }


def _add_asset_observation(
    groups: dict[str, dict[str, Any]],
    asset: dict[str, Any],
    activity_id: str,
    *,
    flow_direction: str,
    amount: str | None,
) -> None:
    key = asset["asset_id"]
    group = groups.setdefault(key, {
        "asset_id": key,
        "network": asset["network"],
        "standard": asset["standard"],
        "contract_address": asset["contract_address"],
        "symbol": asset["symbol"],
        "inflow_total": Decimal(0),
        "outflow_total": Decimal(0),
        "inflow_known": False,
        "outflow_known": False,
        "inflow_observations": 0,
        "outflow_observations": 0,
        "unknown_direction_observations": 0,
        "amount_unavailable_observations": 0,
        "support": set(),
    })
    field = {
        "in": "inflow_observations",
        "out": "outflow_observations",
        "unknown": "unknown_direction_observations",
    }[flow_direction]
    group[field] += 1
    group["support"].add(activity_id)
    parsed = _amount(amount)
    if parsed is None or flow_direction == "unknown":
        group["amount_unavailable_observations"] += 1
        return
    total_key = "inflow_total" if flow_direction == "in" else "outflow_total"
    known_key = "inflow_known" if flow_direction == "in" else "outflow_known"
    group[total_key] += parsed
    group[known_key] = True


def _asset_flow(group: dict[str, Any]) -> dict[str, Any]:
    support = sorted(group["support"])
    return {
        "asset_id": group["asset_id"],
        "network": group["network"],
        "standard": group["standard"],
        "contract_address": group["contract_address"],
        "symbol": group["symbol"],
        "inflow_amount": (
            _decimal_text(group["inflow_total"]) if group["inflow_known"] else None
        ),
        "outflow_amount": (
            _decimal_text(group["outflow_total"]) if group["outflow_known"] else None
        ),
        "inflow_observations": group["inflow_observations"],
        "outflow_observations": group["outflow_observations"],
        "unknown_direction_observations": group["unknown_direction_observations"],
        "amount_unavailable_observations": group["amount_unavailable_observations"],
        "supporting_activity_ids": support[:MAX_SUPPORTING_ACTIVITIES],
        "support_truncated": len(support) > MAX_SUPPORTING_ACTIVITIES,
    }


def _counterparty_flow(group: dict[str, Any]) -> dict[str, Any]:
    support = sorted(group["support"])
    return {
        key: value
        for key, value in group.items()
        if key != "support"
    } | {
        "supporting_activity_ids": support[:MAX_SUPPORTING_ACTIVITIES],
        "support_truncated": len(support) > MAX_SUPPORTING_ACTIVITIES,
    }


def _protocol_flow(group: dict[str, Any]) -> dict[str, Any]:
    support = sorted(group["support"])
    return {
        key: value
        for key, value in group.items()
        if key != "support"
    } | {
        "supporting_activity_ids": support[:MAX_SUPPORTING_ACTIVITIES],
        "support_truncated": len(support) > MAX_SUPPORTING_ACTIVITIES,
    }


def _findings(
    items: tuple[dict[str, Any], ...],
    *,
    aggregate: dict[str, Any],
    gaps: tuple[dict[str, Any], ...],
    evidence_levels: dict[str, str],
    demo: bool,
    flow_state: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, bool]]:
    by_id = {item["public_id"]: item for item in items}
    findings: list[dict[str, Any]] = []
    base_level = "fixture" if demo else "normalized_provider_observation"

    if gaps:
        findings.append(_finding(
            rule_id="activity_coverage_gaps_v1",
            key="coverage",
            category="data_quality",
            importance="attention",
            title="Activity coverage has recorded gaps",
            explanation=(
                "The pinned revision contains unavailable, incomplete or unknown Activity "
                "scope. Missing rows are not treated as zero activity."
            ),
            affected_count=len(gaps),
            support_basis="coverage_gaps",
            activity_ids=(),
            by_id=by_id,
            evidence_levels=evidence_levels,
            fallback_level=base_level,
        ))
    if aggregate["conflicted_identity_count"]:
        findings.append(_finding(
            rule_id="activity_identity_conflicts_v1",
            key="identity",
            category="data_quality",
            importance="attention",
            title="Conflicting Activity identities were withheld",
            explanation=(
                "Rows sharing one revalidated identity but disagreeing on normalized "
                "semantics were omitted instead of being silently merged."
            ),
            affected_count=aggregate["conflicted_identity_count"],
            support_basis="identity_conflicts",
            activity_ids=(),
            by_id=by_id,
            evidence_levels=evidence_levels,
            fallback_level=base_level,
        ))

    failed_ids = sorted(
        item["public_id"]
        for item in items
        if item["kind"] == "transaction" and item["outcome"] == "failed"
    )
    if failed_ids:
        findings.append(_finding(
            rule_id="failed_transaction_observations_v1",
            key="failed",
            category="transaction_outcome",
            importance="attention",
            title="Failed transaction observations",
            explanation=(
                "Normalized transaction rows report a failed outcome. This is an "
                "observed outcome, not a risk or intent classification."
            ),
            affected_count=len(failed_ids),
            support_basis="activity_rows",
            activity_ids=failed_ids,
            by_id=by_id,
            evidence_levels=evidence_levels,
            fallback_level=base_level,
            evidence_level_cap=base_level,
        ))

    unavailable_assets = sorted(flow_state["unavailable_asset_ids"])
    if unavailable_assets:
        findings.append(_finding(
            rule_id="unavailable_asset_identity_v1",
            key="asset",
            category="data_quality",
            importance="attention",
            title="Some asset identities are unavailable",
            explanation=(
                "These observations are excluded from asset-level aggregation because a "
                "canonical network and contract identity could not be revalidated."
            ),
            affected_count=len(unavailable_assets),
            support_basis="activity_rows",
            activity_ids=unavailable_assets,
            by_id=by_id,
            evidence_levels=evidence_levels,
            fallback_level=base_level,
        ))

    unavailable_counterparties = sorted(flow_state["unavailable_counterparty_ids"])
    if unavailable_counterparties:
        findings.append(_finding(
            rule_id="unavailable_counterparty_identity_v1",
            key="counterparty",
            category="data_quality",
            importance="information",
            title="Some counterparty identities are unavailable",
            explanation=(
                "Transfer observations without a canonical counterparty remain visible in "
                "Activity but are excluded from counterparty grouping."
            ),
            affected_count=len(unavailable_counterparties),
            support_basis="activity_rows",
            activity_ids=unavailable_counterparties,
            by_id=by_id,
            evidence_levels=evidence_levels,
            fallback_level=base_level,
        ))

    repeated_groups = [
        group
        for group in flow_state["counterparty_groups"]
        if (
            group["incoming_observations"]
            + group["outgoing_observations"]
            + group["unknown_direction_observations"]
        ) >= 2
    ]
    for group in repeated_groups[:MAX_PATTERN_FINDINGS]:
        count = (
            group["incoming_observations"]
            + group["outgoing_observations"]
            + group["unknown_direction_observations"]
        )
        findings.append(_finding(
            rule_id="repeated_counterparty_observations_v1",
            key=group["canonical_address"],
            category="flow_pattern",
            importance="information",
            title="Repeated counterparty observations",
            explanation=(
                f"{count} transfer observations reference the same canonical counterparty. "
                "This does not establish ownership, control or a relationship."
            ),
            affected_count=count,
            support_basis="activity_rows",
            activity_ids=group["supporting_activity_ids"],
            by_id=by_id,
            evidence_levels=evidence_levels,
            fallback_level=base_level,
        ))

    protocol_groups = flow_state["protocol_groups"]
    for group in protocol_groups[:MAX_PATTERN_FINDINGS]:
        count = group["swap_observations"]
        label = group["label"] or group["protocol_id"]
        findings.append(_finding(
            rule_id="recognized_protocol_observations_v1",
            key=group["protocol_id"],
            category="flow_pattern",
            importance="information",
            title=f"Recognized protocol observations: {label}",
            explanation=(
                f"{count} swap observation{'s' if count != 1 else ''} were decoded with the "
                "published protocol registry identity. This is not a protocol endorsement."
            ),
            affected_count=count,
            support_basis="activity_rows",
            activity_ids=group["supporting_activity_ids"],
            by_id=by_id,
            evidence_levels=evidence_levels,
            fallback_level=base_level,
        ))

    findings.sort(key=lambda item: (item["importance"] != "attention", item["public_id"]))
    return findings, {
        "counterparty_findings_truncated": len(repeated_groups) > MAX_PATTERN_FINDINGS,
        "protocol_findings_truncated": len(protocol_groups) > MAX_PATTERN_FINDINGS,
    }


def _finding(
    *,
    rule_id: str,
    key: str,
    category: str,
    importance: str,
    title: str,
    explanation: str,
    affected_count: int,
    support_basis: str,
    activity_ids: Iterable[str],
    by_id: dict[str, dict[str, Any]],
    evidence_levels: dict[str, str],
    fallback_level: str,
    evidence_level_cap: str | None = None,
) -> dict[str, Any]:
    ids = sorted(set(activity_ids))
    bounded = ids[:MAX_SUPPORTING_ACTIVITIES]
    supports = [
        {
            "activity_public_id": activity_id,
            "kind": by_id[activity_id]["kind"],
            "occurred_at": by_id[activity_id]["occurred_at"],
            "evidence_level": evidence_levels[activity_id],
        }
        for activity_id in bounded
        if activity_id in by_id and activity_id in evidence_levels
    ]
    affected_levels = [
        evidence_levels[activity_id]
        for activity_id in ids
        if activity_id in by_id and activity_id in evidence_levels
    ]
    evidence_level = (
        min(
            affected_levels,
            key=lambda level: _EVIDENCE_SCORE[level],
        )
        if affected_levels
        else fallback_level
    )
    if (
        evidence_level_cap is not None
        and _EVIDENCE_SCORE[evidence_level] > _EVIDENCE_SCORE[evidence_level_cap]
    ):
        evidence_level = evidence_level_cap
    seed = {
        "contract": "wallet_case_finding_v1",
        "rule_id": rule_id,
        "key": key,
        "affected_count": affected_count,
        "support_basis": support_basis,
        "supporting_activity_ids": [
            support["activity_public_id"] for support in supports
        ],
        "evidence_level": evidence_level,
    }
    return {
        "public_id": f"finding_{_digest(seed)}",
        "rule_id": rule_id,
        "category": category,
        "importance": importance,
        "title": title,
        "explanation": explanation,
        "affected_count": affected_count,
        "support_basis": support_basis,
        "supporting_activities": supports,
        "support_truncated": support_basis == "activity_rows" and affected_count > len(supports),
        "evidence_level": evidence_level,
    }


def _limitations(
    activity_limitations: tuple[dict[str, Any], ...],
    *,
    evidence_revision: dict[str, Any],
    flows: dict[str, Any],
    flow_state: dict[str, Any],
    finding_state: dict[str, bool],
) -> list[dict[str, str]]:
    items = list(activity_limitations)
    items.extend((
        {
            "code": "rule_based_findings_only",
            "message": "Findings are deterministic published rules, not an opaque risk score.",
        },
        {
            "code": "absence_of_findings_not_safety",
            "message": "No finding must not be interpreted as a safe wallet classification.",
        },
        {
            "code": "cross_asset_amounts_not_aggregated",
            "message": "Amounts remain separated by canonical asset identity and are not comparable totals.",
        },
        {
            "code": "selective_evidence_findings",
            "message": "Only explicitly selected transactions may have stronger Evidence levels.",
        },
    ))
    if evidence_revision["history_truncated"]:
        items.append({
            "code": "evidence_history_truncated",
            "message": "Only the newest 50 Evidence attempts were revalidated for this revision.",
        })
    if flows["unavailable_asset_observations"]:
        items.append({
            "code": "unidentified_assets_excluded",
            "message": "Asset observations without canonical identity are excluded from asset flows.",
        })
    if flows["unavailable_counterparty_observations"]:
        items.append({
            "code": "unidentified_counterparties_excluded",
            "message": "Transfers without canonical counterparties are excluded from grouped counterparties.",
        })
    if flows["unrecognized_protocol_observations"]:
        items.append({
            "code": "unrecognized_protocols_excluded",
            "message": "Swaps without a recognized protocol identity are excluded from protocol groups.",
        })
    if (
        flows["assets_truncated"]
        or flows["counterparties_truncated"]
        or flows["protocols_truncated"]
    ):
        items.append({
            "code": "flow_groups_truncated",
            "message": "Only the 50 most frequently observed groups per flow dimension are returned.",
        })
    if (
        finding_state["counterparty_findings_truncated"]
        or finding_state["protocol_findings_truncated"]
    ):
        items.append({
            "code": "pattern_findings_truncated",
            "message": "Only the first 20 repeated-counterparty and protocol rules are returned.",
        })
    return _distinct_messages(items)


def _amount(value: str | None) -> Decimal | None:
    if value is None:
        return None
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() and parsed >= 0 else None


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _distinct_messages(items: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        code = str(item.get("code") or "")[:64]
        message = str(item.get("message") or "")[:500]
        if not code or not message or code in seen:
            continue
        seen.add(code)
        result.append({"code": code, "message": message})
    return result


def _digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "WalletCaseFindingsConflict",
    "WalletCaseFindingsNotFound",
    "WalletCaseFindingsScopeTooLarge",
    "WalletCaseFindingsService",
    "WalletCaseFindingsSnapshotNotFound",
]
