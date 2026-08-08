"""Exercise one real Alertmanager receiver and verify downstream delivery."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import re
import secrets
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_ALERTS_URL = "http://alertmanager:9093/api/v2/alerts"
_METRICS_URL = "http://alertmanager:9093/metrics"
_MAX_RESPONSE_BYTES = 262_144
_DRILL_TIMEOUT_SECONDS = 120.0
_POLL_INTERVAL_SECONDS = 2.0
_TOKEN = re.compile(r"^[0-9a-f]{32}$")
_METRIC = re.compile(
    r"^(alertmanager_notification_requests(?:_failed)?_total)"
    r"(?:\{(.*)\})?\s+([^\s]+)(?:\s+\d+)?$"
)
_LABEL = re.compile(r'(?:^|,)([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')


@dataclass(frozen=True)
class DrillResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


HttpClient = Callable[[str, str, bytes | None], DrillResponse]
Clock = Callable[[], datetime]
Monotonic = Callable[[], float]
Sleeper = Callable[[float], None]


def run_notification_drill(
    client: HttpClient | None = None,
    *,
    token_factory: Callable[[], str] | None = None,
    clock: Clock | None = None,
    monotonic: Monotonic | None = None,
    sleeper: Sleeper | None = None,
    timeout_seconds: float = _DRILL_TIMEOUT_SECONDS,
) -> list[str]:
    """Return bounded field-only errors for one routed notification drill."""
    request = client or _request
    now = clock or (lambda: datetime.now(timezone.utc))
    elapsed = monotonic or time.monotonic
    wait = sleeper or time.sleep
    token = (token_factory or (lambda: secrets.token_hex(16)))()
    if not isinstance(token, str) or _TOKEN.fullmatch(token) is None:
        return ["notification drill identity is invalid"]
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, (int, float))
        or not math.isfinite(timeout_seconds)
        or not 1 <= timeout_seconds <= 150
    ):
        return ["notification drill timeout is invalid"]

    try:
        started_at = _utc_now(now)
        firing = _alert_payload(
            token,
            starts_at=started_at,
            ends_at=started_at + timedelta(minutes=5),
        )
    except (OverflowError, ValueError):
        return ["notification drill clock is invalid"]
    try:
        baseline_response = request("GET", _METRICS_URL, None)
        baseline = _notification_metrics(baseline_response)
    except (OSError, RuntimeError, HTTPError, URLError, ValueError):
        return ["notification metrics baseline is unavailable"]
    posted = False
    errors: list[str] = []
    try:
        response = request("POST", _ALERTS_URL, firing)
        if response.status != 200:
            return ["notification drill alert was rejected"]
        posted = True
        deadline = elapsed() + timeout_seconds
        while elapsed() < deadline:
            try:
                receivers = _active_receivers(request, token)
                current = _notification_metrics(request("GET", _METRICS_URL, None))
            except (OSError, RuntimeError, HTTPError, URLError, ValueError):
                errors = ["notification drill observation is unavailable"]
                break
            if receivers and _receiver_delivery_completed(
                baseline, current, receivers
            ):
                break
            wait(_POLL_INTERVAL_SECONDS)
        else:
            errors = ["notification drill delivery was not confirmed"]
    except (OSError, RuntimeError, HTTPError, URLError, ValueError):
        errors = ["notification drill request failed"]
    finally:
        if posted:
            try:
                resolved_at = _utc_now(now)
                resolved = _alert_payload(
                    token,
                    starts_at=started_at,
                    ends_at=resolved_at,
                )
                cleanup = request("POST", _ALERTS_URL, resolved)
                if cleanup.status != 200:
                    errors.append("notification drill cleanup was rejected")
            except (OSError, RuntimeError, HTTPError, URLError, ValueError):
                errors.append("notification drill cleanup failed")
    return errors


def _alert_payload(token: str, *, starts_at: datetime, ends_at: datetime) -> bytes:
    payload = [
        {
            "labels": {
                "alertname": "GramScopeNotificationDrill",
                "gram_scope_drill": token,
                "severity": "warning",
            },
            "annotations": {
                "summary": "GRAM Scope production notification drill",
                "description": (
                    "Synthetic rollout alert. No operator action is required."
                ),
            },
            "startsAt": _rfc3339(starts_at),
            "endsAt": _rfc3339(ends_at),
            "generatorURL": "https://gram.example/operations/notification-drill",
        }
    ]
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _utc_now(clock: Clock) -> datetime:
    value = clock()
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("notification drill clock must be timezone-aware")
    return value.astimezone(timezone.utc)


def _rfc3339(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("notification drill clock must be timezone-aware")
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _active_receivers(request: HttpClient, token: str) -> set[str]:
    query = urlencode({"filter": f'gram_scope_drill="{token}"'})
    response = request("GET", f"{_ALERTS_URL}?{query}", None)
    if response.status != 200:
        raise RuntimeError("notification alert lookup failed")
    try:
        payload = json.loads(response.body.decode("utf-8"))
    except (RecursionError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("notification alert lookup is invalid") from exc
    if not isinstance(payload, list) or len(payload) > 4:
        raise RuntimeError("notification alert lookup is invalid")
    matches = []
    for alert in payload:
        if not isinstance(alert, dict):
            raise RuntimeError("notification alert lookup is invalid")
        labels = alert.get("labels")
        if not isinstance(labels, dict):
            raise RuntimeError("notification alert lookup is invalid")
        if labels.get("gram_scope_drill") == token:
            matches.append(alert)
    if not matches:
        return set()
    if len(matches) != 1:
        raise RuntimeError("notification alert lookup is ambiguous")
    alert = matches[0]
    labels = alert["labels"]
    status = alert.get("status")
    receivers = alert.get("receivers")
    if (
        labels.get("alertname") != "GramScopeNotificationDrill"
        or labels.get("severity") != "warning"
        or not isinstance(status, dict)
        or not isinstance(receivers, list)
        or len(receivers) > 100
    ):
        raise RuntimeError("notification drill alert is not actively routed")
    state = status.get("state")
    if state == "unprocessed":
        return set()
    if state == "active" and not receivers:
        return set()
    if state != "active":
        raise RuntimeError("notification drill alert is not actively routed")
    names: set[str] = set()
    for receiver in receivers:
        if not isinstance(receiver, dict):
            raise RuntimeError("notification drill receiver is invalid")
        name = receiver.get("name")
        if (
            not isinstance(name, str)
            or not name
            or name != name.strip()
            or len(name) > 128
            or name in names
        ):
            raise RuntimeError("notification drill receiver is invalid")
        names.add(name)
    return names


def _notification_metrics(
    response: DrillResponse,
) -> dict[str, dict[tuple[str, str], float]]:
    if response.status != 200:
        raise RuntimeError("notification metrics are unavailable")
    try:
        text = response.body.decode("utf-8")
    except UnicodeError as exc:
        raise RuntimeError("notification metrics are invalid") from exc
    result: dict[str, dict[tuple[str, str], float]] = {
        "requests": {},
        "failed": {},
    }
    seen_metric = False
    for line in text.splitlines():
        match = _METRIC.fullmatch(line)
        if match is None:
            continue
        seen_metric = True
        labels = _parse_labels(match.group(2) or "")
        integration = labels.get("integration")
        receiver = labels.get("receiver_name")
        if (
            not integration
            or len(integration) > 64
            or not receiver
            or len(receiver) > 128
        ):
            raise RuntimeError("receiver-name notification metrics are unavailable")
        try:
            value = float(match.group(3))
        except ValueError as exc:
            raise RuntimeError("notification metrics are invalid") from exc
        if not math.isfinite(value) or value < 0:
            raise RuntimeError("notification metrics are invalid")
        group = (
            "failed"
            if match.group(1).endswith("_failed_total")
            else "requests"
        )
        key = (receiver, integration)
        if key in result[group]:
            raise RuntimeError("notification metrics are ambiguous")
        result[group][key] = value
    if not seen_metric or not result["requests"] or not result["failed"]:
        raise RuntimeError("notification metrics are unavailable")
    if result["requests"].keys() != result["failed"].keys():
        raise RuntimeError("notification metric series are incoherent")
    return result


def _parse_labels(raw: str) -> dict[str, str]:
    labels: dict[str, str] = {}
    position = 0
    for match in _LABEL.finditer(raw):
        if match.start() != position:
            raise RuntimeError("notification metric labels are invalid")
        name = match.group(1)
        try:
            value = json.loads(f'"{match.group(2)}"')
        except json.JSONDecodeError as exc:
            raise RuntimeError("notification metric labels are invalid") from exc
        if name in labels or not isinstance(value, str):
            raise RuntimeError("notification metric labels are invalid")
        labels[name] = value
        position = match.end()
    if position != len(raw):
        raise RuntimeError("notification metric labels are invalid")
    return labels


def _receiver_delivery_completed(
    baseline: dict[str, dict[tuple[str, str], float]],
    current: dict[str, dict[tuple[str, str], float]],
    receivers: set[str],
) -> bool:
    for receiver in receivers:
        keys = {
            key for key in baseline["requests"] if key[0] == receiver
        }
        current_keys = {
            key for key in current["requests"] if key[0] == receiver
        }
        if not keys:
            raise RuntimeError("routed receiver has no notification integration")
        if current_keys != keys:
            raise RuntimeError("notification metric series changed")
        for key in keys:
            if key not in current["requests"] or key not in current["failed"]:
                raise RuntimeError("notification metric series changed")
            request_delta = current["requests"][key] - baseline["requests"][key]
            failure_delta = current["failed"][key] - baseline["failed"][key]
            if request_delta < 0 or failure_delta < 0 or failure_delta > request_delta:
                raise RuntimeError("notification counters changed incoherently")
            if failure_delta != 0 or request_delta < 1:
                return False
    return True


def _request(method: str, url: str, body: bytes | None) -> DrillResponse:
    headers = {
        "Accept": "application/json,text/plain",
        "User-Agent": "GRAM-Scope-Notification-Drill/1",
    }
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    with urlopen(request, timeout=5) as response:
        if response.geturl() != url:
            raise RuntimeError("notification endpoint redirected unexpectedly")
        response_body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(response_body) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("notification response exceeds the size limit")
        return DrillResponse(
            status=response.status,
            headers=dict(response.headers.items()),
            body=response_body,
        )


def main() -> None:
    errors = run_notification_drill()
    if errors:
        print("notification drill failed: " + "; ".join(errors), file=sys.stderr)
        raise SystemExit(2)
    print("notification drill passed", flush=True)


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    main()
