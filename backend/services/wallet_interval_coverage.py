"""Pure bounded interval math for validated wallet acquisition evidence.

The module never validates provider pages itself.  It accepts the per-run
states emitted by the readiness validator, includes only the layer-specific
eligible states, and keeps low-level transaction coverage separate from
provider-display event coverage.

Gaps are measured only inside the span of accepted intervals.  Time before
the earliest accepted start and after the latest accepted end remains unknown.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any


WALLET_INTERVAL_COVERAGE_VERSION = "wallet_multi_run_interval_coverage_v1"

_MAX_RUNS = 50
_TRANSACTION_ELIGIBLE_STATE = "complete"
_EVENT_ELIGIBLE_STATE = "provider_stream_complete"
_MICROSECONDS_PER_SECOND = 1_000_000
_MICROSECONDS_PER_DAY = 86_400 * _MICROSECONDS_PER_SECOND


def _parse_timestamp(value: Any) -> datetime | None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 40
    ):
        return None
    cleaned = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _duration_microseconds(start: datetime, end: datetime) -> int:
    delta = end - start
    return (
        delta.days * _MICROSECONDS_PER_DAY
        + delta.seconds * _MICROSECONDS_PER_SECOND
        + delta.microseconds
    )


def _validate_selected_run_ids(selected_run_ids: list[int]) -> list[int]:
    if not isinstance(selected_run_ids, list):
        raise ValueError("selected_run_ids must be a list.")
    if not 2 <= len(selected_run_ids) <= _MAX_RUNS:
        raise ValueError("selected_run_ids must contain 2-50 ids.")
    if any(type(run_id) is not int or run_id < 1 for run_id in selected_run_ids):
        raise ValueError("Every selected run id must be a positive integer.")
    if len(set(selected_run_ids)) != len(selected_run_ids):
        raise ValueError("selected_run_ids must be distinct.")
    return sorted(selected_run_ids)


def _recorded_value(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _normalized_interval(
    run_id: int,
    row: dict[str, Any],
) -> dict[str, Any] | None:
    start = _parse_timestamp(row.get("interval_start"))
    end = _parse_timestamp(row.get("interval_end"))
    if start is None or end is None or start >= end:
        return None
    return {"run_id": run_id, "start": start, "end": end}


def _candidate_states(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(
        state
        for state in (row.get("state") for row in rows)
        if isinstance(state, str)
    )


def _run_evidence_record(
    *,
    run_id: int,
    source_state: str | None,
    classification: str,
    reason: str | None,
    candidate_states: list[str],
    row: dict[str, Any] | None = None,
    interval: dict[str, Any] | None = None,
) -> dict[str, Any]:
    record = {
        "run_id": run_id,
        "source_state": source_state,
        "candidate_states": candidate_states,
        "classification": classification,
        "reason": reason,
        "source_reason_codes": sorted(
            {
                code
                for code in (row.get("reason_codes", []) if row else [])
                if isinstance(code, str) and code
            }
        ),
        "recorded_interval_start": (
            _recorded_value(row.get("interval_start")) if row else None
        ),
        "recorded_interval_end": (
            _recorded_value(row.get("interval_end")) if row else None
        ),
        "interval_start": None,
        "interval_end": None,
        "duration_microseconds": None,
        "included_in_union": interval is not None,
    }
    if interval is not None:
        record.update(
            {
                "interval_start": _isoformat(interval["start"]),
                "interval_end": _isoformat(interval["end"]),
                "duration_microseconds": str(
                    _duration_microseconds(interval["start"], interval["end"])
                ),
            }
        )
    return record


def _classify_run_evidence(
    *,
    run_id: int,
    candidates: list[dict[str, Any]],
    eligible_state: str,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    if not candidates:
        return (
            _run_evidence_record(
                run_id=run_id,
                source_state=None,
                classification="excluded",
                reason="missing_evidence_record",
                candidate_states=[],
            ),
            None,
        )
    if len(candidates) != 1:
        return (
            _run_evidence_record(
                run_id=run_id,
                source_state=None,
                classification="excluded",
                reason="ambiguous_evidence_record",
                candidate_states=_candidate_states(candidates),
            ),
            None,
        )

    row = candidates[0]
    state_value = row.get("state")
    source_state = state_value if isinstance(state_value, str) else None
    candidate_states = [source_state] if source_state is not None else []
    if source_state == "not_requested":
        return (
            _run_evidence_record(
                run_id=run_id,
                source_state=source_state,
                classification="not_requested",
                reason=None,
                candidate_states=candidate_states,
                row=row,
            ),
            None,
        )
    if source_state != eligible_state:
        return (
            _run_evidence_record(
                run_id=run_id,
                source_state=source_state,
                classification="excluded",
                reason=(
                    "state_not_eligible"
                    if source_state is not None
                    else "invalid_state"
                ),
                candidate_states=candidate_states,
                row=row,
            ),
            None,
        )

    interval = _normalized_interval(run_id, row)
    if interval is None:
        return (
            _run_evidence_record(
                run_id=run_id,
                source_state=source_state,
                classification="excluded",
                reason="invalid_interval",
                candidate_states=candidate_states,
                row=row,
            ),
            None,
        )
    return (
        _run_evidence_record(
            run_id=run_id,
            source_state=source_state,
            classification="included",
            reason=None,
            candidate_states=candidate_states,
            row=row,
            interval=interval,
        ),
        interval,
    )


def _interval_cells(
    intervals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    boundaries = sorted(
        {
            boundary
            for interval in intervals
            for boundary in (interval["start"], interval["end"])
        }
    )
    cells: list[dict[str, Any]] = []
    for start, end in zip(boundaries, boundaries[1:]):
        if start >= end:
            continue
        active_run_ids = tuple(
            sorted(
                interval["run_id"]
                for interval in intervals
                if interval["start"] < end and interval["end"] > start
            )
        )
        cells.append(
            {"start": start, "end": end, "run_ids": active_run_ids}
        )
    return cells


def _union_intervals(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for cell in cells:
        if not cell["run_ids"]:
            continue
        if segments and segments[-1]["end"] == cell["start"]:
            segments[-1]["end"] = cell["end"]
        else:
            segments.append({"start": cell["start"], "end": cell["end"]})
    return segments


def _overlap_intervals(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for cell in cells:
        run_ids = cell["run_ids"]
        if len(run_ids) < 2:
            continue
        if (
            segments
            and segments[-1]["end"] == cell["start"]
            and segments[-1]["run_ids"] == run_ids
        ):
            segments[-1]["end"] = cell["end"]
        else:
            segments.append(
                {
                    "start": cell["start"],
                    "end": cell["end"],
                    "run_ids": run_ids,
                }
            )
    return segments


def _gap_intervals(cells: list[dict[str, Any]]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    index = 0
    while index < len(cells):
        if cells[index]["run_ids"]:
            index += 1
            continue
        first = index
        while index + 1 < len(cells) and not cells[index + 1]["run_ids"]:
            index += 1
        last = index
        segments.append(
            {
                "start": cells[first]["start"],
                "end": cells[last]["end"],
                "left_run_ids": (
                    cells[first - 1]["run_ids"] if first > 0 else ()
                ),
                "right_run_ids": (
                    cells[last + 1]["run_ids"]
                    if last + 1 < len(cells)
                    else ()
                ),
            }
        )
        index += 1
    return segments


def _public_interval(segment: dict[str, Any]) -> dict[str, Any]:
    start = segment["start"]
    end = segment["end"]
    return {
        "start": _isoformat(start),
        "end": _isoformat(end),
        "duration_microseconds": str(_duration_microseconds(start, end)),
    }


def _public_overlap(segment: dict[str, Any]) -> dict[str, Any]:
    record = _public_interval(segment)
    run_ids = list(segment["run_ids"])
    record.update({"run_ids": run_ids, "coverage_depth": len(run_ids)})
    return record


def _public_gap(segment: dict[str, Any]) -> dict[str, Any]:
    record = _public_interval(segment)
    record.update(
        {
            "left_run_ids": list(segment["left_run_ids"]),
            "right_run_ids": list(segment["right_run_ids"]),
        }
    )
    return record


def _public_accepted_interval(interval: dict[str, Any]) -> dict[str, Any]:
    record = _public_interval(interval)
    return {"run_id": interval["run_id"], **record}


def _coverage_layer(
    *,
    selected_run_ids: list[int],
    evidence_rows: list[dict[str, Any]],
    stream_key: str,
    coverage_kind: str,
    eligible_state: str,
    provider_semantics: str,
) -> dict[str, Any]:
    rows_by_run_id: dict[int, list[dict[str, Any]]] = defaultdict(list)
    if isinstance(evidence_rows, list):
        for row in evidence_rows:
            if not isinstance(row, dict):
                continue
            run_id = row.get("run_id")
            if type(run_id) is int and run_id in selected_run_ids:
                rows_by_run_id[run_id].append(row)

    run_evidence: list[dict[str, Any]] = []
    intervals: list[dict[str, Any]] = []
    for run_id in selected_run_ids:
        record, interval = _classify_run_evidence(
            run_id=run_id,
            candidates=rows_by_run_id.get(run_id, []),
            eligible_state=eligible_state,
        )
        run_evidence.append(record)
        if interval is not None:
            intervals.append(interval)

    intervals.sort(key=lambda item: (item["start"], item["end"], item["run_id"]))
    cells = _interval_cells(intervals)
    union = _union_intervals(cells)
    overlaps = _overlap_intervals(cells)
    gaps = _gap_intervals(cells)

    public_union = [_public_interval(segment) for segment in union]
    public_overlaps = [_public_overlap(segment) for segment in overlaps]
    public_gaps = [_public_gap(segment) for segment in gaps]
    public_intervals = [
        _public_accepted_interval(interval) for interval in intervals
    ]

    if not union:
        state = "no_validated_intervals"
        selected_span = None
        span_duration = 0
        is_contiguous = False
    else:
        span_start = union[0]["start"]
        span_end = union[-1]["end"]
        span_duration = _duration_microseconds(span_start, span_end)
        selected_span = _public_interval(
            {"start": span_start, "end": span_end}
        )
        is_contiguous = len(union) == 1
        state = (
            "contiguous_selected_span"
            if is_contiguous
            else "gapped_selected_span"
        )

    covered_duration = sum(
        _duration_microseconds(interval["start"], interval["end"])
        for interval in union
    )
    gap_duration = sum(
        _duration_microseconds(interval["start"], interval["end"])
        for interval in gaps
    )
    overlapped_duration = sum(
        _duration_microseconds(interval["start"], interval["end"])
        for interval in overlaps
    )
    max_depth = max(
        (len(cell["run_ids"]) for cell in cells),
        default=0,
    )

    included_run_ids = [
        record["run_id"]
        for record in run_evidence
        if record["classification"] == "included"
    ]
    not_requested_run_ids = [
        record["run_id"]
        for record in run_evidence
        if record["classification"] == "not_requested"
    ]
    excluded_runs = [
        record
        for record in run_evidence
        if record["classification"] == "excluded"
    ]
    if not included_run_ids:
        selected_run_coverage_state = "none"
    elif len(included_run_ids) == len(selected_run_ids):
        selected_run_coverage_state = "complete"
    else:
        selected_run_coverage_state = "partial"
    requested_run_count = sum(
        1
        for record in run_evidence
        if record["source_state"] not in {None, "not_requested"}
    )

    return {
        "stream_key": stream_key,
        "coverage_kind": coverage_kind,
        "eligible_state": eligible_state,
        "provider_semantics": provider_semantics,
        "state": state,
        "selected_run_count": len(selected_run_ids),
        "requested_run_count": requested_run_count,
        "included_run_count": len(included_run_ids),
        "included_run_ids": included_run_ids,
        "excluded_run_ids": [record["run_id"] for record in excluded_runs],
        "not_requested_run_ids": not_requested_run_ids,
        "selected_run_coverage_state": selected_run_coverage_state,
        "run_evidence": run_evidence,
        "accepted_intervals": public_intervals,
        "selected_span": selected_span,
        "union_intervals": public_union,
        "overlap_intervals": public_overlaps,
        "gap_intervals": public_gaps,
        "span_duration_microseconds": str(span_duration),
        "covered_duration_microseconds": str(covered_duration),
        "gap_duration_microseconds": str(gap_duration),
        "overlapped_duration_microseconds": str(overlapped_duration),
        "max_coverage_depth": max_depth,
        "is_contiguous_within_selected_span": is_contiguous,
        "outside_selected_span_coverage": "unknown",
        "establishes_full_history": False,
        "is_authoritative_activity_coverage": False,
    }


def build_wallet_interval_coverage(
    *,
    selected_run_ids: list[int],
    transaction_evidence: list[dict[str, Any]],
    event_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build separate deterministic interval diagnostics for two streams."""
    run_ids = _validate_selected_run_ids(selected_run_ids)
    return {
        "contract_version": WALLET_INTERVAL_COVERAGE_VERSION,
        "selected_run_ids": run_ids,
        "interval_semantics": "[start,end)",
        "coverage_scope": "selected_validated_run_intervals_only",
        "gap_scope": "inside_validated_selected_span_only",
        "cross_stream_union_applied": False,
        "low_level_transactions": _coverage_layer(
            selected_run_ids=run_ids,
            evidence_rows=transaction_evidence,
            stream_key="transactions",
            coverage_kind="low_level_transaction_stream",
            eligible_state=_TRANSACTION_ELIGIBLE_STATE,
            provider_semantics="bounded_low_level_transaction_query",
        ),
        "provider_display_events": _coverage_layer(
            selected_run_ids=run_ids,
            evidence_rows=event_evidence,
            stream_key="account_events",
            coverage_kind="provider_display_event_stream",
            eligible_state=_EVENT_ELIGIBLE_STATE,
            provider_semantics="display_only_actions",
        ),
        "full_pre_run_history_established": False,
        "complete_wallet_history_established": False,
        "is_global_history_coverage": False,
        "is_authoritative_activity_coverage": False,
        "activity_rows_merged": False,
        "deduplication_applied": False,
        "is_cost_basis": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "note": (
            "Coverage is measured only inside accepted bounded intervals. "
            "Time outside each selected span is unknown, and provider-display "
            "event coverage is never authoritative activity history."
        ),
    }
