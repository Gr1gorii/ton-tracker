"""Verify the internal Prometheus to Alertmanager delivery path."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


_MAX_RESPONSE_BYTES = 65_536
_PROMETHEUS_READY = "http://prometheus:9090/-/ready"
_ALERTMANAGER_READY = "http://alertmanager:9093/-/ready"
_PROMETHEUS_ALERTMANAGERS = "http://prometheus:9090/api/v1/alertmanagers"
_EXPECTED_ALERTMANAGER_API = "http://alertmanager:9093/api/v2/alerts"


@dataclass(frozen=True)
class MonitoringProbe:
    status: int
    headers: Mapping[str, str]
    body: bytes


ProbeFetcher = Callable[[str], MonitoringProbe]


def run_alert_delivery_checks(fetch: ProbeFetcher | None = None) -> list[str]:
    """Return field-only errors for the internal notification chain."""
    get = fetch or _fetch
    errors: list[str] = []
    probes: dict[str, MonitoringProbe] = {}
    for name, url in (
        ("prometheus readiness", _PROMETHEUS_READY),
        ("alertmanager readiness", _ALERTMANAGER_READY),
        ("prometheus alertmanager discovery", _PROMETHEUS_ALERTMANAGERS),
    ):
        try:
            probes[name] = get(url)
        except (OSError, RuntimeError, HTTPError, URLError, ValueError):
            errors.append(f"{name} request failed")

    for name in ("prometheus readiness", "alertmanager readiness"):
        probe = probes.get(name)
        if probe is not None and probe.status != 200:
            errors.append(f"{name} is unavailable")

    discovery = probes.get("prometheus alertmanager discovery")
    if discovery is not None:
        if discovery.status != 200:
            errors.append("prometheus alertmanager discovery is unavailable")
        else:
            _validate_discovery(discovery.body, errors)
    return errors


def _validate_discovery(raw: bytes, errors: list[str]) -> None:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        errors.append("prometheus alertmanager discovery is invalid")
        return
    if not isinstance(payload, dict) or payload.get("status") != "success":
        errors.append("prometheus alertmanager discovery is invalid")
        return
    data = payload.get("data")
    if not isinstance(data, dict):
        errors.append("prometheus alertmanager discovery is invalid")
        return
    active = data.get("activeAlertmanagers")
    dropped = data.get("droppedAlertmanagers")
    if (
        not isinstance(active, list)
        or len(active) != 1
        or not isinstance(active[0], dict)
        or active[0].get("url") != _EXPECTED_ALERTMANAGER_API
        or dropped != []
    ):
        errors.append("prometheus alertmanager target is invalid")


def _fetch(url: str) -> MonitoringProbe:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain",
            "User-Agent": "GRAM-Scope-Monitoring-Preflight/1",
        },
    )
    with urlopen(request, timeout=5) as response:
        if response.geturl() != url:
            raise RuntimeError("monitoring endpoint redirected unexpectedly")
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("monitoring response exceeds the size limit")
        return MonitoringProbe(
            status=response.status,
            headers=dict(response.headers.items()),
            body=body,
        )


def main() -> None:
    errors = run_alert_delivery_checks()
    if errors:
        print(
            "monitoring delivery preflight failed: " + "; ".join(errors),
            file=sys.stderr,
        )
        raise SystemExit(2)
    print("monitoring delivery preflight passed", flush=True)


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    main()
