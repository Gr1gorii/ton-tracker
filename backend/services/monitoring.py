"""Small dependency-free Prometheus metrics registry."""

from __future__ import annotations

from collections import defaultdict
import threading
import time


_STARTED_AT = time.time()
_LOCK = threading.Lock()
_REQUESTS: dict[tuple[str, str, int], int] = defaultdict(int)
_DURATION_SUM: dict[tuple[str, str], float] = defaultdict(float)
_DURATION_COUNT: dict[tuple[str, str], int] = defaultdict(int)


def observe_http_request(
    method: str,
    route: str,
    status: int,
    duration_seconds: float,
) -> None:
    route = route if route.startswith("/") else "unmatched"
    with _LOCK:
        _REQUESTS[(method, route, status)] += 1
        _DURATION_SUM[(method, route)] += max(0.0, duration_seconds)
        _DURATION_COUNT[(method, route)] += 1


def render_prometheus_metrics(*, version: str, database_ready: bool) -> str:
    with _LOCK:
        request_rows = list(_REQUESTS.items())
        duration_sums = list(_DURATION_SUM.items())
        duration_counts = list(_DURATION_COUNT.items())
    lines = [
        "# HELP ton_tracker_build_info Application build information.",
        "# TYPE ton_tracker_build_info gauge",
        f'ton_tracker_build_info{{version="{_escape(version)}"}} 1',
        "# HELP ton_tracker_process_start_time_seconds Process start time.",
        "# TYPE ton_tracker_process_start_time_seconds gauge",
        f"ton_tracker_process_start_time_seconds {_STARTED_AT:.3f}",
        "# HELP ton_tracker_database_ready Database readiness state.",
        "# TYPE ton_tracker_database_ready gauge",
        f"ton_tracker_database_ready {1 if database_ready else 0}",
        "# HELP ton_tracker_http_requests_total HTTP requests by route and status.",
        "# TYPE ton_tracker_http_requests_total counter",
    ]
    for (method, route, status), count in sorted(request_rows):
        lines.append(
            "ton_tracker_http_requests_total"
            f'{{method="{_escape(method)}",route="{_escape(route)}",'
            f'status="{status}"}} {count}'
        )
    lines.extend(
        (
            "# HELP ton_tracker_http_request_duration_seconds_sum "
            "Cumulative request duration.",
            "# TYPE ton_tracker_http_request_duration_seconds_sum counter",
        )
    )
    for (method, route), value in sorted(duration_sums):
        lines.append(
            "ton_tracker_http_request_duration_seconds_sum"
            f'{{method="{_escape(method)}",route="{_escape(route)}"}} '
            f"{value:.9f}"
        )
    lines.extend(
        (
            "# HELP ton_tracker_http_request_duration_seconds_count "
            "Observed request duration count.",
            "# TYPE ton_tracker_http_request_duration_seconds_count counter",
        )
    )
    for (method, route), count in sorted(duration_counts):
        lines.append(
            "ton_tracker_http_request_duration_seconds_count"
            f'{{method="{_escape(method)}",route="{_escape(route)}"}} {count}'
        )
    return "\n".join(lines) + "\n"


def _escape(value: str) -> str:
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
