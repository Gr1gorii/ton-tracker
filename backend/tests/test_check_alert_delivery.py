"""Prometheus to Alertmanager delivery-path smoke tests."""

from __future__ import annotations

import json

from ops.check_alert_delivery import MonitoringProbe, run_alert_delivery_checks


PROMETHEUS_READY = "http://prometheus:9090/-/ready"
ALERTMANAGER_READY = "http://alertmanager:9093/-/ready"
DISCOVERY = "http://prometheus:9090/api/v1/alertmanagers"


def _probe(body: object = b"ready\n", *, status: int = 200) -> MonitoringProbe:
    encoded = (
        json.dumps(body, separators=(",", ":")).encode("utf-8")
        if not isinstance(body, bytes)
        else body
    )
    return MonitoringProbe(status=status, headers={}, body=encoded)


def _responses() -> dict[str, MonitoringProbe]:
    return {
        PROMETHEUS_READY: _probe(),
        ALERTMANAGER_READY: _probe(),
        DISCOVERY: _probe(
            {
                "status": "success",
                "data": {
                    "activeAlertmanagers": [
                        {"url": "http://alertmanager:9093/api/v2/alerts"}
                    ],
                    "droppedAlertmanagers": [],
                },
            }
        ),
    }


def test_delivery_check_requires_ready_services_and_exact_active_target():
    responses = _responses()
    requested: list[str] = []

    def fetch(url: str) -> MonitoringProbe:
        requested.append(url)
        return responses[url]

    assert run_alert_delivery_checks(fetch) == []
    assert requested == [PROMETHEUS_READY, ALERTMANAGER_READY, DISCOVERY]


def test_delivery_check_fails_closed_for_bad_status_or_discovery():
    responses = _responses()
    responses[PROMETHEUS_READY] = _probe(status=503)
    responses[DISCOVERY] = _probe(
        {
            "status": "success",
            "data": {
                "activeAlertmanagers": [
                    {"url": "http://unexpected:9093/api/v2/alerts"}
                ],
                "droppedAlertmanagers": [],
            },
        }
    )

    errors = run_alert_delivery_checks(lambda url: responses[url])
    assert errors == [
        "prometheus readiness is unavailable",
        "prometheus alertmanager target is invalid",
    ]


def test_delivery_check_sanitizes_network_and_malformed_response_failures():
    def unavailable(url: str) -> MonitoringProbe:
        if url == DISCOVERY:
            return _probe(b'{"private":"response"')
        raise OSError("private network diagnostic")

    errors = run_alert_delivery_checks(unavailable)
    assert errors == [
        "prometheus readiness request failed",
        "alertmanager readiness request failed",
        "prometheus alertmanager discovery is invalid",
    ]
    assert "private" not in " ".join(errors)
