"""Durable content-addressed Wallet Case Report revision catalog."""

from __future__ import annotations

import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import secrets
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from models import (
    CaseSync,
    LOCAL_SINGLE_USER_SCOPE,
    WalletCase,
    WalletCaseReportRevision,
)
from services.wallet_case_report import (
    WalletCaseReportConflict,
    WalletCaseReportNotFound,
    WalletCaseReportScopeTooLarge,
    WalletCaseReportService,
    WalletCaseReportSnapshotNotFound,
)
from wallet_case_report_revision_schemas import (
    WalletCaseReportRevisionComparison,
    report_revision_catalog_public_id,
    report_revision_comparison_public_id,
)
from wallet_case_report_schemas import WalletCaseReportResponse


MAX_PAGE_LIMIT = 20
_CURSOR_KEY = secrets.token_bytes(32)


class WalletCaseReportRevisionNotFound(LookupError):
    code = "case_report_revision_not_found"


class WalletCaseReportRevisionSnapshotNotFound(LookupError):
    code = "case_report_revision_snapshot_not_found"


class WalletCaseReportRevisionConflict(RuntimeError):
    code = "case_report_revision_conflict"


class WalletCaseReportRevisionScopeTooLarge(RuntimeError):
    code = "case_report_revision_scope_too_large"


class WalletCaseReportRevisionInvalidCursor(ValueError):
    code = "invalid_case_report_revision_cursor"


class WalletCaseReportRevisionService:
    def __init__(
        self,
        session: Session,
        *,
        owner_scope_id: str = LOCAL_SINGLE_USER_SCOPE,
    ) -> None:
        self.session = session
        self.owner_scope_id = owner_scope_id

    def capture(
        self,
        case_public_id: str,
        *,
        snapshot_public_id: str,
    ) -> dict[str, Any]:
        try:
            payload = WalletCaseReportService(
                self.session,
                owner_scope_id=self.owner_scope_id,
            ).build(case_public_id, snapshot_public_id=snapshot_public_id)
        except WalletCaseReportNotFound as exc:
            raise WalletCaseReportRevisionNotFound(str(exc)) from exc
        except WalletCaseReportSnapshotNotFound as exc:
            raise WalletCaseReportRevisionSnapshotNotFound(str(exc)) from exc
        except WalletCaseReportConflict as exc:
            raise WalletCaseReportRevisionConflict(str(exc)) from exc
        except WalletCaseReportScopeTooLarge as exc:
            raise WalletCaseReportRevisionScopeTooLarge(str(exc)) from exc

        validated = WalletCaseReportResponse.model_validate(payload)
        report = validated.report
        if report is None:
            raise WalletCaseReportRevisionSnapshotNotFound(
                "Synchronize this Wallet Case before capturing a report revision."
            )
        wallet_case = self._required_case(case_public_id)
        snapshot = self.session.scalar(
            select(CaseSync).where(
                CaseSync.case_id == wallet_case.id,
                CaseSync.public_id == snapshot_public_id,
                CaseSync.state.in_(("partial", "succeeded")),
                CaseSync.ingestion_run_id.is_not(None),
            )
        )
        if snapshot is None:
            raise WalletCaseReportRevisionSnapshotNotFound(
                "The requested Wallet Case snapshot is unavailable."
            )

        existing = self.session.scalar(
            select(WalletCaseReportRevision).where(
                WalletCaseReportRevision.case_id == wallet_case.id,
                WalletCaseReportRevision.public_id == report.public_id,
            ).options(joinedload(WalletCaseReportRevision.snapshot_sync))
        )
        if existing is not None:
            return {
                "case_public_id": wallet_case.public_id,
                "created": False,
                "revision": self._stored(existing, wallet_case=wallet_case)[0],
            }

        report_document = validated.model_dump(mode="json")
        encoded = _canonical_json(report_document).decode("utf-8")
        row = WalletCaseReportRevision(
            public_id=report.public_id,
            case_id=wallet_case.id,
            snapshot_sync_id=snapshot.id,
            contract_version=report.contract_version,
            content_hash_sha256=report.content_hash_sha256,
            assurance_level=report.assurance_level,
            activity_digest_sha256=report.activity_revision.digest_sha256,
            evidence_digest_sha256=report.evidence_revision.digest_sha256,
            report_json=encoded,
            created_at=datetime.now(timezone.utc),
        )
        self.session.add(row)
        try:
            self.session.commit()
        except IntegrityError:
            self.session.rollback()
            row = self.session.scalar(
                select(WalletCaseReportRevision).where(
                    WalletCaseReportRevision.case_id == wallet_case.id,
                    WalletCaseReportRevision.public_id == report.public_id,
                ).options(joinedload(WalletCaseReportRevision.snapshot_sync))
            )
            if row is None:
                raise
            return {
                "case_public_id": wallet_case.public_id,
                "created": False,
                "revision": self._stored(row, wallet_case=wallet_case)[0],
            }
        self.session.refresh(row)
        return {
            "case_public_id": wallet_case.public_id,
            "created": True,
            "revision": self._stored(row, wallet_case=wallet_case)[0],
        }

    def catalog(
        self,
        case_public_id: str,
        *,
        limit: int,
        cursor: str | None,
    ) -> dict[str, Any]:
        if limit < 1 or limit > MAX_PAGE_LIMIT:
            raise WalletCaseReportRevisionInvalidCursor(
                "Report revision limit must be between 1 and 20."
            )
        wallet_case = self._required_case(case_public_id)
        cursor_document = _decode_cursor(cursor) if cursor is not None else None
        if cursor_document is not None and cursor_document["case"] != case_public_id:
            raise WalletCaseReportRevisionInvalidCursor(
                "Report revision cursor belongs to another Wallet Case."
            )

        if cursor_document is None:
            cutoff = self.session.scalar(
                select(WalletCaseReportRevision)
                .where(WalletCaseReportRevision.case_id == wallet_case.id)
                .order_by(WalletCaseReportRevision.id.desc())
                .limit(1)
            )
        else:
            cutoff = self.session.scalar(
                select(WalletCaseReportRevision).where(
                    WalletCaseReportRevision.case_id == wallet_case.id,
                    WalletCaseReportRevision.public_id == cursor_document["cutoff"],
                )
            )
            if cutoff is None:
                raise WalletCaseReportRevisionInvalidCursor(
                    "Report revision cursor cutoff is unavailable."
                )

        if cutoff is None:
            return {
                "contract_version": "wallet_case_report_revision_catalog_v1",
                "public_id": report_revision_catalog_public_id(case_public_id, None),
                "case_public_id": case_public_id,
                "revision_cutoff_public_id": None,
                "items": [],
                "aggregate": {"total_revisions": 0, "returned_count": 0},
                "page": {"limit": limit, "has_more": False, "next_cursor": None},
                "limitations": [_explicit_capture_limitation()],
            }

        after_id: int | None = None
        if cursor_document is not None:
            after = self.session.scalar(
                select(WalletCaseReportRevision).where(
                    WalletCaseReportRevision.case_id == wallet_case.id,
                    WalletCaseReportRevision.public_id == cursor_document["after"],
                    WalletCaseReportRevision.id <= cutoff.id,
                )
            )
            if after is None:
                raise WalletCaseReportRevisionInvalidCursor(
                    "Report revision cursor position is unavailable."
                )
            after_id = after.id

        statement = (
            select(WalletCaseReportRevision)
            .where(
                WalletCaseReportRevision.case_id == wallet_case.id,
                WalletCaseReportRevision.id <= cutoff.id,
            )
            .options(joinedload(WalletCaseReportRevision.snapshot_sync))
        )
        if after_id is not None:
            statement = statement.where(WalletCaseReportRevision.id < after_id)
        rows = list(
            self.session.scalars(
                statement.order_by(WalletCaseReportRevision.id.desc()).limit(limit + 1)
            )
        )
        has_more = len(rows) > limit
        visible = rows[:limit]
        items = [self._stored(row, wallet_case=wallet_case)[0] for row in visible]
        total = int(
            self.session.scalar(
                select(func.count())
                .select_from(WalletCaseReportRevision)
                .where(
                    WalletCaseReportRevision.case_id == wallet_case.id,
                    WalletCaseReportRevision.id <= cutoff.id,
                )
            )
            or 0
        )
        next_cursor = None
        if has_more:
            next_cursor = _encode_cursor({
                "v": 1,
                "case": case_public_id,
                "cutoff": cutoff.public_id,
                "after": visible[-1].public_id,
            })
        limitations = [_explicit_capture_limitation()]
        if next_cursor is not None:
            limitations.append({
                "code": "report_revision_cursor_local_process_scope",
                "message": "Pagination cursors are authenticated for this local API process and expire after restart.",
            })
        return {
            "contract_version": "wallet_case_report_revision_catalog_v1",
            "public_id": report_revision_catalog_public_id(
                case_public_id,
                cutoff.public_id,
            ),
            "case_public_id": case_public_id,
            "revision_cutoff_public_id": cutoff.public_id,
            "items": items,
            "aggregate": {"total_revisions": total, "returned_count": len(items)},
            "page": {
                "limit": limit,
                "has_more": has_more,
                "next_cursor": next_cursor,
            },
            "limitations": limitations,
        }

    def detail(self, case_public_id: str, *, report_public_id: str) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        row = self.session.scalar(
            select(WalletCaseReportRevision).where(
                WalletCaseReportRevision.case_id == wallet_case.id,
                WalletCaseReportRevision.public_id == report_public_id,
            ).options(joinedload(WalletCaseReportRevision.snapshot_sync))
        )
        if row is None:
            raise WalletCaseReportRevisionNotFound("Stored report revision not found.")
        summary, report = self._stored(row, wallet_case=wallet_case)
        return {
            "case_public_id": wallet_case.public_id,
            "revision": summary,
            "report": report,
        }

    def compare(
        self,
        case_public_id: str,
        *,
        baseline_public_id: str,
        target_public_id: str,
    ) -> dict[str, Any]:
        wallet_case = self._required_case(case_public_id)
        requested_ids = {baseline_public_id, target_public_id}
        rows = {
            row.public_id: row
            for row in self.session.scalars(
                select(WalletCaseReportRevision)
                .where(
                    WalletCaseReportRevision.case_id == wallet_case.id,
                    WalletCaseReportRevision.public_id.in_(requested_ids),
                )
                .options(joinedload(WalletCaseReportRevision.snapshot_sync))
            )
        }
        if set(rows) != requested_ids:
            raise WalletCaseReportRevisionNotFound(
                "One or both stored report revisions were not found."
            )
        baseline_summary, baseline_document = self._stored(
            rows[baseline_public_id],
            wallet_case=wallet_case,
        )
        if baseline_public_id == target_public_id:
            target_summary, target_document = baseline_summary, baseline_document
        else:
            target_summary, target_document = self._stored(
                rows[target_public_id],
                wallet_case=wallet_case,
            )
        baseline = WalletCaseReportResponse.model_validate(baseline_document).report
        target = WalletCaseReportResponse.model_validate(target_document).report
        if baseline is None or target is None or baseline.subject != target.subject:
            raise WalletCaseReportRevisionConflict(
                "Stored report revisions do not share one public subject identity."
            )

        same_snapshot = baseline.snapshot_public_id == target.snapshot_public_id
        comparison_limitations = [
            {
                "code": "comparison_uses_explicit_captures",
                "message": "This comparison covers two explicitly captured revisions, not every intermediate report state.",
            },
            {
                "code": "comparison_does_not_establish_causality",
                "message": "Directional deltas describe stored public documents and do not prove why a value changed.",
            },
        ]
        if not same_snapshot:
            comparison_limitations.append({
                "code": "comparison_spans_pinned_snapshots",
                "message": "The revisions use different pinned snapshots, so Activity and Evidence deltas may reflect different bounded observation scopes.",
            })

        baseline_activity = baseline.activity_revision.aggregate.model_dump()
        target_activity = target.activity_revision.aggregate.model_dump()
        baseline_evidence = baseline.evidence_revision.model_dump()
        target_evidence = target.evidence_revision.model_dump()
        payload: dict[str, Any] = {
            "contract_version": "wallet_case_report_revision_comparison_v1",
            "public_id": "rcmp_" + ("0" * 64),
            "case_public_id": wallet_case.public_id,
            "baseline": baseline_summary,
            "target": target_summary,
            "same_snapshot": same_snapshot,
            "content_changed": baseline.public_id != target.public_id,
            "assurance": {
                "baseline": baseline.assurance_level,
                "target": target.assurance_level,
                "changed": baseline.assurance_level != target.assurance_level,
            },
            "activity": {
                "digest_changed": baseline.activity_revision.digest_sha256
                != target.activity_revision.digest_sha256,
                "observed_period_changed": baseline.activity_revision.observed_period
                != target.activity_revision.observed_period,
                **{
                    key: _integer_delta(baseline_activity[key], target_activity[key])
                    for key in baseline_activity
                },
            },
            "evidence": {
                "digest_changed": baseline.evidence_revision.digest_sha256
                != target.evidence_revision.digest_sha256,
                **{
                    key: _integer_delta(baseline_evidence[key], target_evidence[key])
                    for key in (
                        "total_attempts",
                        "returned_revalidated",
                        "selected_activity_count",
                        "locally_verified_activity_count",
                        "chain_inclusion_proven_activity_count",
                        "native_ledger_activity_count",
                    )
                },
                "history_truncated": _boolean_transition(
                    baseline.evidence_revision.history_truncated,
                    target.evidence_revision.history_truncated,
                ),
            },
            "coverage_changed": baseline.coverage != target.coverage,
            "canonical_gate": {
                "eligible": _boolean_transition(
                    baseline.canonical_gate.eligible,
                    target.canonical_gate.eligible,
                ),
                "newly_unmet": sorted(
                    set(target.canonical_gate.unmet)
                    - set(baseline.canonical_gate.unmet)
                ),
                "resolved": sorted(
                    set(baseline.canonical_gate.unmet)
                    - set(target.canonical_gate.unmet)
                ),
                "unchanged_count": len(
                    set(baseline.canonical_gate.unmet)
                    & set(target.canonical_gate.unmet)
                ),
            },
            "gaps": _code_changes(baseline.gaps, target.gaps),
            "limitations": _code_changes(
                baseline.limitations,
                target.limitations,
            ),
            "unverified_claims": _code_changes(
                baseline.unverified_claims,
                target.unverified_claims,
            ),
            "truth_boundaries_changed": False,
            "comparison_limitations": comparison_limitations,
        }
        payload["public_id"] = report_revision_comparison_public_id(payload)
        return WalletCaseReportRevisionComparison.model_validate(payload).model_dump(
            mode="json"
        )

    def _required_case(self, case_public_id: str) -> WalletCase:
        row = self.session.scalar(
            select(WalletCase).where(
                WalletCase.owner_scope_id == self.owner_scope_id,
                WalletCase.public_id == case_public_id,
                WalletCase.archived_at.is_(None),
            )
        )
        if row is None:
            raise WalletCaseReportRevisionNotFound("Wallet Case not found.")
        return row

    def _stored(
        self,
        row: WalletCaseReportRevision,
        *,
        wallet_case: WalletCase,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        try:
            raw = json.loads(row.report_json)
            validated = WalletCaseReportResponse.model_validate(raw)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            raise WalletCaseReportRevisionConflict(
                "Stored report revision is invalid."
            ) from exc
        report = validated.report
        snapshot = row.snapshot_sync
        canonical = _canonical_json(validated.model_dump(mode="json")).decode("utf-8")
        if (
            report is None
            or snapshot is None
            or snapshot.case_id != wallet_case.id
            or canonical != row.report_json
            or validated.case_public_id != wallet_case.public_id
            or report.case_public_id != wallet_case.public_id
            or report.snapshot_public_id != snapshot.public_id
            or row.public_id != report.public_id
            or row.contract_version != report.contract_version
            or row.content_hash_sha256 != report.content_hash_sha256
            or row.assurance_level != report.assurance_level
            or row.activity_digest_sha256 != report.activity_revision.digest_sha256
            or row.evidence_digest_sha256 != report.evidence_revision.digest_sha256
        ):
            raise WalletCaseReportRevisionConflict(
                "Stored report revision no longer matches its public provenance."
            )
        return {
            "public_id": row.public_id,
            "content_hash_sha256": row.content_hash_sha256,
            "case_public_id": wallet_case.public_id,
            "snapshot_public_id": snapshot.public_id,
            "assurance_level": row.assurance_level,
            "captured_at": _iso(row.created_at),
            "activity_digest_sha256": row.activity_digest_sha256,
            "evidence_digest_sha256": row.evidence_digest_sha256,
            "activity_count": report.activity_revision.aggregate.total_items,
            "evidence_attempt_count": report.evidence_revision.total_attempts,
            "canonical_eligible": report.canonical_gate.eligible,
            "limitation_count": len(report.limitations),
            "unverified_claim_count": len(report.unverified_claims),
        }, validated.model_dump(mode="json")


def _explicit_capture_limitation() -> dict[str, str]:
    return {
        "code": "report_revisions_are_explicit_captures",
        "message": "Only explicitly captured report revisions are retained; intermediate Evidence states are not reconstructed.",
    }


def _integer_delta(baseline: int, target: int) -> dict[str, int]:
    return {
        "baseline": baseline,
        "target": target,
        "delta": target - baseline,
    }


def _boolean_transition(baseline: bool, target: bool) -> dict[str, bool]:
    return {
        "baseline": baseline,
        "target": target,
        "changed": baseline != target,
    }


def _code_changes(baseline: list[Any], target: list[Any]) -> dict[str, Any]:
    def group(items: list[Any]) -> dict[str, list[str]]:
        grouped: dict[str, list[str]] = {}
        for item in items:
            encoded = _canonical_json(item.model_dump(mode="json")).decode("utf-8")
            grouped.setdefault(item.code, []).append(encoded)
        return {key: sorted(values) for key, values in grouped.items()}

    baseline_by_code = group(baseline)
    target_by_code = group(target)
    baseline_codes = set(baseline_by_code)
    target_codes = set(target_by_code)
    shared = baseline_codes & target_codes
    return {
        "added": sorted(target_codes - baseline_codes),
        "removed": sorted(baseline_codes - target_codes),
        "modified": sorted(
            code
            for code in shared
            if baseline_by_code[code] != target_by_code[code]
        ),
        "unchanged_count": sum(
            baseline_by_code[code] == target_by_code[code]
            for code in shared
        ),
    }


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def _encode_cursor(document: dict[str, Any]) -> str:
    payload = _canonical_json(document)
    encoded = base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    signature = hmac.new(_CURSOR_KEY, payload, hashlib.sha256).hexdigest()
    return f"{encoded}.{signature}"


def _decode_cursor(value: str) -> dict[str, Any]:
    if not value or len(value) > 1024 or value.count(".") != 1:
        raise WalletCaseReportRevisionInvalidCursor("Report revision cursor is invalid.")
    encoded, signature = value.split(".", 1)
    if (
        not encoded
        or len(signature) != 64
        or any(char not in "0123456789abcdef" for char in signature)
        or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_" for char in encoded)
    ):
        raise WalletCaseReportRevisionInvalidCursor("Report revision cursor is invalid.")
    try:
        padding = "=" * ((4 - len(encoded) % 4) % 4)
        raw = base64.urlsafe_b64decode((encoded + padding).encode("ascii"))
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise WalletCaseReportRevisionInvalidCursor(
            "Report revision cursor is invalid."
        ) from exc
    if not isinstance(document, dict) or set(document) != {
        "v", "case", "cutoff", "after"
    } or document.get("v") != 1:
        raise WalletCaseReportRevisionInvalidCursor(
            "Report revision cursor shape is invalid."
        )
    expected = hmac.new(_CURSOR_KEY, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected) or _encode_cursor(document) != value:
        raise WalletCaseReportRevisionInvalidCursor(
            "Report revision cursor signature is invalid."
        )
    if not all(isinstance(document.get(key), str) for key in ("case", "cutoff", "after")):
        raise WalletCaseReportRevisionInvalidCursor(
            "Report revision cursor identifiers are invalid."
        )
    return document


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "WalletCaseReportRevisionConflict",
    "WalletCaseReportRevisionInvalidCursor",
    "WalletCaseReportRevisionNotFound",
    "WalletCaseReportRevisionScopeTooLarge",
    "WalletCaseReportRevisionService",
    "WalletCaseReportRevisionSnapshotNotFound",
]
