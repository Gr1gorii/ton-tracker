"""Adversarial tests for pure bounded multi-run interval math."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from services.wallet_interval_coverage import (
    WALLET_INTERVAL_COVERAGE_VERSION,
    build_wallet_interval_coverage,
)


BASE = datetime(2026, 7, 1, tzinfo=timezone.utc)
HOUR_US = 3_600_000_000


def _iso(*, hours: int = 0, microseconds: int = 0) -> str:
    value = BASE + timedelta(hours=hours, microseconds=microseconds)
    return value.isoformat().replace("+00:00", "Z")


def _row(
    run_id: int,
    start: str | None,
    end: str | None,
    *,
    state: str = "complete",
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "state": state,
        "interval_start": start,
        "interval_end": end,
    }


def _not_requested(run_ids: list[int]) -> list[dict[str, Any]]:
    return [_row(run_id, None, None, state="not_requested") for run_id in run_ids]


def _build(
    run_ids: list[int],
    transactions: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return build_wallet_interval_coverage(
        selected_run_ids=run_ids,
        transaction_evidence=transactions,
        event_evidence=events if events is not None else _not_requested(run_ids),
    )


def _assert_no_floats(value: Any) -> None:
    assert not isinstance(value, float)
    if isinstance(value, dict):
        for item in value.values():
            _assert_no_floats(item)
    elif isinstance(value, list):
        for item in value:
            _assert_no_floats(item)


def test_gap_is_measured_only_inside_the_accepted_span():
    result = _build(
        [1, 2],
        [
            _row(1, _iso(hours=0), _iso(hours=1)),
            _row(2, _iso(hours=2), _iso(hours=3)),
        ],
    )
    layer = result["low_level_transactions"]

    assert result["contract_version"] == WALLET_INTERVAL_COVERAGE_VERSION
    assert result["interval_semantics"] == "[start,end)"
    assert layer["state"] == "gapped_selected_span"
    assert layer["selected_span"] == {
        "start": _iso(hours=0),
        "end": _iso(hours=3),
        "duration_microseconds": str(3 * HOUR_US),
    }
    assert layer["union_intervals"] == [
        {
            "start": _iso(hours=0),
            "end": _iso(hours=1),
            "duration_microseconds": str(HOUR_US),
        },
        {
            "start": _iso(hours=2),
            "end": _iso(hours=3),
            "duration_microseconds": str(HOUR_US),
        },
    ]
    assert layer["gap_intervals"] == [
        {
            "start": _iso(hours=1),
            "end": _iso(hours=2),
            "duration_microseconds": str(HOUR_US),
            "left_run_ids": [1],
            "right_run_ids": [2],
        }
    ]
    assert layer["span_duration_microseconds"] == str(3 * HOUR_US)
    assert layer["covered_duration_microseconds"] == str(2 * HOUR_US)
    assert layer["gap_duration_microseconds"] == str(HOUR_US)
    assert layer["outside_selected_span_coverage"] == "unknown"
    assert layer["establishes_full_history"] is False
    _assert_no_floats(result)


def test_adjacent_half_open_intervals_form_one_union_without_overlap_or_gap():
    layer = _build(
        [2, 1],
        [
            _row(2, _iso(hours=1), _iso(hours=2)),
            _row(1, _iso(hours=0), _iso(hours=1)),
        ],
    )["low_level_transactions"]

    assert layer["state"] == "contiguous_selected_span"
    assert layer["union_intervals"] == [
        {
            "start": _iso(hours=0),
            "end": _iso(hours=2),
            "duration_microseconds": str(2 * HOUR_US),
        }
    ]
    assert layer["gap_intervals"] == []
    assert layer["overlap_intervals"] == []
    assert layer["max_coverage_depth"] == 1
    assert layer["is_contiguous_within_selected_span"] is True


def test_nested_intervals_report_only_the_nested_overlap():
    layer = _build(
        [1, 2],
        [
            _row(1, _iso(hours=0), _iso(hours=10)),
            _row(2, _iso(hours=2), _iso(hours=8)),
        ],
    )["low_level_transactions"]

    assert layer["union_intervals"] == [
        {
            "start": _iso(hours=0),
            "end": _iso(hours=10),
            "duration_microseconds": str(10 * HOUR_US),
        }
    ]
    assert layer["overlap_intervals"] == [
        {
            "start": _iso(hours=2),
            "end": _iso(hours=8),
            "duration_microseconds": str(6 * HOUR_US),
            "run_ids": [1, 2],
            "coverage_depth": 2,
        }
    ]
    assert layer["overlapped_duration_microseconds"] == str(6 * HOUR_US)
    assert layer["max_coverage_depth"] == 2


def test_identical_intervals_overlap_for_the_entire_selected_span():
    layer = _build(
        [1, 2],
        [
            _row(1, _iso(hours=0), _iso(hours=5)),
            _row(2, _iso(hours=0), _iso(hours=5)),
        ],
    )["low_level_transactions"]

    assert layer["covered_duration_microseconds"] == str(5 * HOUR_US)
    assert layer["overlapped_duration_microseconds"] == str(5 * HOUR_US)
    assert layer["overlap_intervals"][0]["run_ids"] == [1, 2]
    assert layer["overlap_intervals"][0]["coverage_depth"] == 2
    assert layer["gap_intervals"] == []


def test_triple_overlap_preserves_contributor_changes():
    layer = _build(
        [1, 2, 3],
        [
            _row(1, _iso(hours=0), _iso(hours=4)),
            _row(2, _iso(hours=1), _iso(hours=3)),
            _row(3, _iso(hours=2), _iso(hours=5)),
        ],
    )["low_level_transactions"]

    assert layer["overlap_intervals"] == [
        {
            "start": _iso(hours=1),
            "end": _iso(hours=2),
            "duration_microseconds": str(HOUR_US),
            "run_ids": [1, 2],
            "coverage_depth": 2,
        },
        {
            "start": _iso(hours=2),
            "end": _iso(hours=3),
            "duration_microseconds": str(HOUR_US),
            "run_ids": [1, 2, 3],
            "coverage_depth": 3,
        },
        {
            "start": _iso(hours=3),
            "end": _iso(hours=4),
            "duration_microseconds": str(HOUR_US),
            "run_ids": [1, 3],
            "coverage_depth": 2,
        },
    ]
    assert layer["max_coverage_depth"] == 3
    assert layer["overlapped_duration_microseconds"] == str(3 * HOUR_US)


def test_one_microsecond_gap_is_exact_and_never_rounded():
    layer = _build(
        [1, 2],
        [
            _row(1, _iso(microseconds=0), _iso(microseconds=1)),
            _row(2, _iso(microseconds=2), _iso(microseconds=3)),
        ],
    )["low_level_transactions"]

    assert layer["span_duration_microseconds"] == "3"
    assert layer["covered_duration_microseconds"] == "2"
    assert layer["gap_duration_microseconds"] == "1"
    assert layer["gap_intervals"] == [
        {
            "start": _iso(microseconds=1),
            "end": _iso(microseconds=2),
            "duration_microseconds": "1",
            "left_run_ids": [1],
            "right_run_ids": [2],
        }
    ]


def test_microsecond_durations_remain_exact_beyond_javascript_safe_integer():
    start = "0001-01-01T00:00:00.000001Z"
    end = "2026-06-02T00:00:00Z"
    start_at = datetime.fromisoformat(start.replace("Z", "+00:00"))
    end_at = datetime.fromisoformat(end.replace("Z", "+00:00"))
    delta = end_at - start_at
    duration = str(
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    assert int(duration) > 2**53 - 1

    layer = _build(
        [1, 2],
        [
            _row(1, start, end),
            _row(2, start, end),
        ],
    )["low_level_transactions"]

    assert layer["selected_span"]["duration_microseconds"] == duration
    assert layer["accepted_intervals"][0]["duration_microseconds"] == duration
    assert layer["run_evidence"][0]["duration_microseconds"] == duration
    assert layer["span_duration_microseconds"] == duration
    assert layer["covered_duration_microseconds"] == duration
    assert layer["overlapped_duration_microseconds"] == duration
    assert isinstance(layer["span_duration_microseconds"], str)


def test_shuffled_run_and_evidence_order_is_byte_stable():
    transactions = [
        _row(1, _iso(hours=0), _iso(hours=4)),
        _row(2, _iso(hours=2), _iso(hours=5)),
        _row(3, _iso(hours=7), _iso(hours=8)),
        _row(4, None, None, state="not_requested"),
    ]
    events = [
        _row(
            1,
            _iso(hours=0),
            _iso(hours=1),
            state="provider_stream_complete",
        ),
        _row(2, None, None, state="not_requested"),
        _row(3, None, None, state="incomplete"),
        _row(4, None, None, state="not_requested"),
    ]

    first = _build([1, 2, 3, 4], transactions, events)
    second = _build(
        [4, 3, 2, 1],
        list(reversed(transactions)),
        list(reversed(events)),
    )

    assert second == first
    assert first["selected_run_ids"] == [1, 2, 3, 4]


def test_no_eligible_interval_has_no_span_and_no_fabricated_gap():
    result = _build(
        [1, 2],
        _not_requested([1, 2]),
        [],
    )
    transactions = result["low_level_transactions"]
    events = result["provider_display_events"]

    assert transactions["state"] == "no_validated_intervals"
    assert transactions["selected_span"] is None
    assert transactions["union_intervals"] == []
    assert transactions["overlap_intervals"] == []
    assert transactions["gap_intervals"] == []
    assert transactions["not_requested_run_ids"] == [1, 2]
    assert transactions["excluded_run_ids"] == []
    assert events["state"] == "no_validated_intervals"
    assert events["excluded_run_ids"] == [1, 2]
    assert all(
        record["reason"] == "missing_evidence_record"
        for record in events["run_evidence"]
    )


def test_invalid_ambiguous_missing_and_not_requested_states_are_preserved():
    evidence = [
        _row(1, "2026-07-01T00:00:00", _iso(hours=1)),
        _row(2, _iso(hours=0), _iso(hours=1)),
        _row(2, _iso(hours=1), _iso(hours=2), state="incomplete"),
        _row(3, None, None, state="incomplete"),
        _row(4, None, None, state="not_requested"),
    ]

    layer = _build([1, 2, 3, 4, 5], evidence)["low_level_transactions"]
    by_run = {record["run_id"]: record for record in layer["run_evidence"]}

    assert by_run[1]["source_state"] == "complete"
    assert by_run[1]["reason"] == "invalid_interval"
    assert by_run[1]["recorded_interval_start"] == "2026-07-01T00:00:00"
    assert by_run[2]["source_state"] is None
    assert by_run[2]["candidate_states"] == ["complete", "incomplete"]
    assert by_run[2]["reason"] == "ambiguous_evidence_record"
    assert by_run[3]["source_state"] == "incomplete"
    assert by_run[3]["reason"] == "state_not_eligible"
    assert by_run[4]["classification"] == "not_requested"
    assert by_run[4]["source_state"] == "not_requested"
    assert by_run[5]["reason"] == "missing_evidence_record"
    assert layer["excluded_run_ids"] == [1, 2, 3, 5]
    assert layer["not_requested_run_ids"] == [4]
    assert layer["selected_run_coverage_state"] == "none"
    assert layer["accepted_intervals"] == []


def test_fifty_adjacent_runs_remain_bounded_and_contiguous():
    run_ids = list(range(1, 51))
    evidence = [
        _row(run_id, _iso(hours=run_id - 1), _iso(hours=run_id))
        for run_id in run_ids
    ]

    layer = _build(list(reversed(run_ids)), evidence)[
        "low_level_transactions"
    ]

    assert layer["selected_run_count"] == 50
    assert layer["included_run_count"] == 50
    assert layer["selected_run_coverage_state"] == "complete"
    assert layer["included_run_ids"] == run_ids
    assert layer["state"] == "contiguous_selected_span"
    assert len(layer["union_intervals"]) == 1
    assert layer["union_intervals"][0]["duration_microseconds"] == str(
        50 * HOUR_US
    )
    assert layer["max_coverage_depth"] == 1
    assert layer["gap_intervals"] == []


def test_transaction_and_provider_display_streams_never_bridge_each_other():
    result = _build(
        [1, 2],
        [
            _row(1, _iso(hours=0), _iso(hours=1)),
            _row(2, _iso(hours=2), _iso(hours=3)),
        ],
        [
            _row(
                1,
                _iso(hours=0),
                _iso(hours=2),
                state="provider_stream_complete",
            ),
            _row(
                2,
                _iso(hours=2),
                _iso(hours=3),
                state="provider_stream_complete",
            ),
        ],
    )
    transactions = result["low_level_transactions"]
    events = result["provider_display_events"]

    assert result["cross_stream_union_applied"] is False
    assert transactions["state"] == "gapped_selected_span"
    assert transactions["gap_duration_microseconds"] == str(HOUR_US)
    assert events["state"] == "contiguous_selected_span"
    assert events["gap_duration_microseconds"] == "0"
    assert events["provider_semantics"] == "display_only_actions"
    assert events["is_authoritative_activity_coverage"] is False
    assert result["complete_wallet_history_established"] is False
    assert result["deduplication_applied"] is False
    assert result["eligible_for_cost_basis"] is False
    assert result["used_by_pnl"] is False


def test_eligible_states_are_strictly_layer_specific():
    result = _build(
        [1, 2],
        [
            _row(
                1,
                _iso(hours=0),
                _iso(hours=1),
                state="provider_stream_complete",
            ),
            _row(2, None, None, state="not_requested"),
        ],
        [
            _row(1, _iso(hours=0), _iso(hours=1), state="complete"),
            _row(2, None, None, state="not_requested"),
        ],
    )

    transaction_record = result["low_level_transactions"]["run_evidence"][0]
    event_record = result["provider_display_events"]["run_evidence"][0]
    assert transaction_record["source_state"] == "provider_stream_complete"
    assert transaction_record["reason"] == "state_not_eligible"
    assert event_record["source_state"] == "complete"
    assert event_record["reason"] == "state_not_eligible"
    assert result["low_level_transactions"]["included_run_count"] == 0
    assert result["provider_display_events"]["included_run_count"] == 0


@pytest.mark.parametrize(
    "run_ids",
    [
        [1],
        list(range(1, 52)),
        [1, 1],
        [1, True],
        [0, 1],
    ],
)
def test_selected_run_scope_fails_closed(run_ids):
    with pytest.raises(ValueError):
        _build(run_ids, [])
