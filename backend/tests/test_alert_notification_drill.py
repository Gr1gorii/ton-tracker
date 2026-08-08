"""Active Alertmanager notification-drill tests."""

from __future__ import annotations

from datetime import datetime, timezone
import json

from ops.check_alert_notification import (
    DrillResponse,
    _notification_metrics,
    run_notification_drill,
)
from ops.notification_receiver_fixture import NotificationFixtureHandler


ALERTS = "http://alertmanager:9093/api/v2/alerts"
METRICS = "http://alertmanager:9093/metrics"
TOKEN = "a" * 32


def _response(body: bytes = b"", *, status: int = 200) -> DrillResponse:
    return DrillResponse(status=status, headers={}, body=body)


def _metrics(*, requests: int, failed: int, receiver: str = "operations") -> bytes:
    return (
        "# HELP alertmanager_notification_requests_total attempted\n"
        f'alertmanager_notification_requests_total{{integration="webhook",receiver_name="{receiver}"}} {requests}\n'
        "# HELP alertmanager_notification_requests_failed_total failed\n"
        f'alertmanager_notification_requests_failed_total{{integration="webhook",receiver_name="{receiver}"}} {failed}\n'
    ).encode("utf-8")


def _active_alert(receiver: str = "operations") -> bytes:
    return json.dumps(
        [
            {
                "labels": {
                    "alertname": "GramScopeNotificationDrill",
                    "gram_scope_drill": TOKEN,
                    "severity": "warning",
                },
                "annotations": {},
                "receivers": [{"name": receiver}],
                "status": {
                    "state": "active",
                    "silencedBy": [],
                    "inhibitedBy": [],
                    "mutedBy": [],
                },
            }
        ],
        separators=(",", ":"),
    ).encode("utf-8")


def test_drill_posts_unique_alert_confirms_receiver_and_resolves_it():
    calls: list[tuple[str, str, bytes | None]] = []
    post_bodies: list[list[dict[str, object]]] = []
    metric_reads = 0

    def client(method: str, url: str, body: bytes | None) -> DrillResponse:
        nonlocal metric_reads
        calls.append((method, url, body))
        if method == "GET" and url == METRICS:
            metric_reads += 1
            return _response(
                _metrics(requests=0 if metric_reads == 1 else 1, failed=0)
            )
        if method == "GET" and url.startswith(f"{ALERTS}?"):
            assert "gram_scope_drill%3D%22" in url
            return _response(_active_alert())
        if method == "POST" and url == ALERTS and body is not None:
            post_bodies.append(json.loads(body.decode("utf-8")))
            return _response()
        raise AssertionError(f"unexpected request: {method} {url}")

    moment = datetime(2026, 8, 8, 12, 0, tzinfo=timezone.utc)
    errors = run_notification_drill(
        client,
        token_factory=lambda: TOKEN,
        clock=lambda: moment,
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )

    assert errors == []
    assert [call[0] for call in calls] == ["GET", "POST", "GET", "GET", "POST"]
    assert len(post_bodies) == 2
    firing = post_bodies[0][0]
    resolved = post_bodies[1][0]
    assert firing["labels"] == {
        "alertname": "GramScopeNotificationDrill",
        "gram_scope_drill": TOKEN,
        "severity": "warning",
    }
    assert firing["startsAt"] == "2026-08-08T12:00:00.000000Z"
    assert firing["endsAt"] == "2026-08-08T12:05:00.000000Z"
    assert resolved["startsAt"] == firing["startsAt"]
    assert resolved["endsAt"] == "2026-08-08T12:00:00.000000Z"


def test_drill_waits_until_every_routed_integration_succeeds():
    metric_reads = 0
    monotonic_values = iter([0.0, 0.0, 0.5])

    def metrics(requests: tuple[int, int], failed: tuple[int, int]) -> bytes:
        return (
            f'alertmanager_notification_requests_total{{integration="webhook",receiver_name="operations"}} {requests[0]}\n'
            f'alertmanager_notification_requests_total{{integration="slack",receiver_name="operations"}} {requests[1]}\n'
            f'alertmanager_notification_requests_failed_total{{integration="webhook",receiver_name="operations"}} {failed[0]}\n'
            f'alertmanager_notification_requests_failed_total{{integration="slack",receiver_name="operations"}} {failed[1]}\n'
        ).encode("utf-8")

    def client(method: str, url: str, body: bytes | None) -> DrillResponse:
        nonlocal metric_reads
        if method == "POST":
            return _response()
        if url.startswith(f"{ALERTS}?"):
            return _response(_active_alert())
        if url == METRICS:
            metric_reads += 1
            if metric_reads == 1:
                return _response(metrics((4, 2), (1, 0)))
            return _response(metrics((5, 3), (1, 0)))
        raise AssertionError("unexpected request")

    assert run_notification_drill(
        client,
        token_factory=lambda: TOKEN,
        clock=lambda: datetime.now(timezone.utc),
        monotonic=lambda: next(monotonic_values),
        sleeper=lambda _seconds: None,
        timeout_seconds=1,
    ) == []


def test_drill_retries_while_the_alert_is_still_unprocessed():
    alert_reads = 0
    metric_reads = 0
    monotonic_values = iter([0.0, 0.0, 0.25])

    def client(method: str, url: str, body: bytes | None) -> DrillResponse:
        nonlocal alert_reads, metric_reads
        if method == "POST":
            return _response()
        if url.startswith(f"{ALERTS}?"):
            alert_reads += 1
            if alert_reads == 1:
                pending = json.loads(_active_alert())
                pending[0]["status"]["state"] = "unprocessed"
                pending[0]["receivers"] = []
                return _response(json.dumps(pending).encode("utf-8"))
            return _response(_active_alert())
        metric_reads += 1
        return _response(_metrics(requests=max(metric_reads - 1, 0), failed=0))

    assert run_notification_drill(
        client,
        token_factory=lambda: TOKEN,
        clock=lambda: datetime.now(timezone.utc),
        monotonic=lambda: next(monotonic_values),
        sleeper=lambda _seconds: None,
        timeout_seconds=1,
    ) == []
    assert alert_reads == 2


def test_drill_fails_closed_when_receiver_name_metrics_are_not_enabled():
    body = (
        'alertmanager_notification_requests_total{integration="webhook"} 0\n'
        'alertmanager_notification_requests_failed_total{integration="webhook"} 0\n'
    ).encode("utf-8")

    assert run_notification_drill(
        lambda _method, _url, _body: _response(body),
        token_factory=lambda: TOKEN,
    ) == ["notification metrics baseline is unavailable"]


def test_drill_times_out_when_the_receiver_only_reports_failed_requests():
    metric_reads = 0
    monotonic_values = iter([0.0, 0.0, 2.0])
    posts = 0

    def client(method: str, url: str, body: bytes | None) -> DrillResponse:
        nonlocal metric_reads, posts
        if method == "POST":
            posts += 1
            return _response()
        if url.startswith(f"{ALERTS}?"):
            return _response(_active_alert())
        metric_reads += 1
        return _response(
            _metrics(
                requests=0 if metric_reads == 1 else 1,
                failed=0 if metric_reads == 1 else 1,
            )
        )

    assert run_notification_drill(
        client,
        token_factory=lambda: TOKEN,
        clock=lambda: datetime.now(timezone.utc),
        monotonic=lambda: next(monotonic_values),
        sleeper=lambda _seconds: None,
        timeout_seconds=1,
    ) == ["notification drill delivery was not confirmed"]
    assert posts == 2


def test_drill_reports_cleanup_failure_without_leaking_transport_details():
    posts = 0
    metric_reads = 0

    def client(method: str, url: str, body: bytes | None) -> DrillResponse:
        nonlocal posts, metric_reads
        if method == "POST":
            posts += 1
            if posts == 2:
                raise OSError("https://secret.receiver.example/token")
            return _response()
        if url.startswith(f"{ALERTS}?"):
            return _response(_active_alert())
        metric_reads += 1
        return _response(_metrics(requests=metric_reads - 1, failed=0))

    errors = run_notification_drill(
        client,
        token_factory=lambda: TOKEN,
        clock=lambda: datetime.now(timezone.utc),
        monotonic=lambda: 0.0,
        sleeper=lambda _seconds: None,
    )
    assert errors == ["notification drill cleanup failed"]
    assert "secret" not in " ".join(errors)


def test_metric_parser_rejects_counter_or_series_drift():
    escaped = _metrics(requests=2, failed=0, receiver='ops\\nprimary')
    parsed = _notification_metrics(_response(escaped))
    assert parsed["requests"] == {("ops\nprimary", "webhook"): 2.0}

    duplicate = escaped + escaped
    try:
        _notification_metrics(_response(duplicate))
    except RuntimeError as exc:
        assert str(exc) == "notification metrics are ambiguous"
    else:  # pragma: no cover - assertion clarity
        raise AssertionError("duplicate metric series must fail closed")


def test_drill_rejects_invalid_identity_and_timeout_before_network_access():
    invoked = False

    def client(_method: str, _url: str, _body: bytes | None) -> DrillResponse:
        nonlocal invoked
        invoked = True
        return _response()

    assert run_notification_drill(client, token_factory=lambda: "not-a-token") == [
        "notification drill identity is invalid"
    ]
    assert run_notification_drill(
        client, token_factory=lambda: TOKEN, timeout_seconds=151
    ) == ["notification drill timeout is invalid"]
    assert invoked is False

    assert run_notification_drill(
        client,
        token_factory=lambda: TOKEN,
        clock=lambda: datetime(2026, 8, 8, 12, 0),
    ) == ["notification drill clock is invalid"]


def test_release_gate_fixture_accepts_only_bounded_drill_payloads():
    valid = json.dumps(
        {
            "alerts": [
                {
                    "labels": {
                        "alertname": "GramScopeNotificationDrill",
                        "gram_scope_drill": TOKEN,
                    }
                }
            ]
        }
    ).encode("utf-8")
    assert NotificationFixtureHandler._valid_drill(valid) is True
    assert NotificationFixtureHandler._valid_drill(b"{}") is False
    assert NotificationFixtureHandler._valid_drill(b"not-json") is False
    assert NotificationFixtureHandler._valid_drill(
        valid.replace(b"GramScopeNotificationDrill", b"UnrelatedAlert")
    ) is False
