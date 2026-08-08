"""Expose a credential-free Prometheus view of deployment state."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import TypeAlias

try:
    from .deployment_state import DeploymentStateBusyError, DeploymentStateError
    from .inspect_deployment_state import inspect_deployment_state
except ImportError:  # pragma: no cover - direct script execution in the image
    from deployment_state import DeploymentStateBusyError, DeploymentStateError
    from inspect_deployment_state import inspect_deployment_state


_STATUSES = ("ready", "empty", "interrupted", "busy", "invalid")
_MAX_LEDGER_EVENTS = 100_000
_METRICS_CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"
_ServerAddress: TypeAlias = tuple[str, int]


@dataclass(frozen=True)
class DeploymentAuditMetrics:
    """Bounded monitoring fields derived from one locked state audit."""

    status: str
    valid: bool
    lock_busy: bool = False
    pending_attempt: bool = False
    ledger_event_count: int = 0
    receipt_bound: bool = False


def collect_deployment_audit_metrics(
    state_directory: Path,
) -> DeploymentAuditMetrics:
    """Collect one fail-closed audit without exposing release identities."""
    try:
        report = inspect_deployment_state(state_directory)
    except DeploymentStateBusyError:
        return DeploymentAuditMetrics(status="busy", valid=False, lock_busy=True)
    except DeploymentStateError:
        return DeploymentAuditMetrics(status="invalid", valid=False)

    try:
        schema = report["schema"]
        status = report["status"]
        ledger = report["ledger"]
        pending = report["pending_attempt"]
        if (
            schema != "gram_scope_deployment_audit_v2"
            or status not in {"ready", "empty", "interrupted"}
        ):
            raise ValueError
        if not isinstance(ledger, dict):
            raise ValueError
        event_count = ledger["event_count"]
        binding = ledger["receipt_binding"]
        if (
            not isinstance(event_count, int)
            or isinstance(event_count, bool)
            or event_count < 0
            or event_count > _MAX_LEDGER_EVENTS
            or binding not in {"none", "bound", "awaiting_receipt"}
            or (pending is not None and not isinstance(pending, dict))
            or (status == "interrupted") != (pending is not None)
        ):
            raise ValueError
    except (KeyError, TypeError, ValueError):
        return DeploymentAuditMetrics(status="invalid", valid=False)

    return DeploymentAuditMetrics(
        status=status,
        valid=True,
        pending_attempt=pending is not None,
        ledger_event_count=event_count,
        receipt_bound=binding == "bound",
    )


def render_deployment_prometheus(metrics: DeploymentAuditMetrics) -> str:
    """Render a stable, low-cardinality Prometheus exposition contract."""
    if metrics.status not in _STATUSES:
        raise ValueError("deployment audit monitoring status is invalid")
    if (
        not isinstance(metrics.ledger_event_count, int)
        or isinstance(metrics.ledger_event_count, bool)
        or metrics.ledger_event_count < 0
        or metrics.ledger_event_count > _MAX_LEDGER_EVENTS
    ):
        raise ValueError("deployment audit event count is invalid")
    flags = (
        metrics.valid,
        metrics.lock_busy,
        metrics.pending_attempt,
        metrics.receipt_bound,
    )
    if not all(isinstance(value, bool) for value in flags):
        raise ValueError("deployment audit monitoring flags are invalid")
    if (
        metrics.valid != (metrics.status in {"ready", "empty", "interrupted"})
        or metrics.lock_busy != (metrics.status == "busy")
        or metrics.pending_attempt != (metrics.status == "interrupted")
        or (metrics.receipt_bound and metrics.ledger_event_count == 0)
    ):
        raise ValueError("deployment audit monitoring fields are inconsistent")

    lines = [
        "# HELP ton_tracker_deployment_audit_valid Deployment state passed complete validation.",
        "# TYPE ton_tracker_deployment_audit_valid gauge",
        f"ton_tracker_deployment_audit_valid {1 if metrics.valid else 0}",
        "# HELP ton_tracker_deployment_state_ready Deployment state has one active verified release and no pending attempt.",
        "# TYPE ton_tracker_deployment_state_ready gauge",
        f"ton_tracker_deployment_state_ready {1 if metrics.status == 'ready' else 0}",
        "# HELP ton_tracker_deployment_lock_busy Another process currently holds the deployment lock.",
        "# TYPE ton_tracker_deployment_lock_busy gauge",
        f"ton_tracker_deployment_lock_busy {1 if metrics.lock_busy else 0}",
        "# HELP ton_tracker_deployment_pending_attempt A crash-safe deployment attempt requires explicit inspection or resume.",
        "# TYPE ton_tracker_deployment_pending_attempt gauge",
        f"ton_tracker_deployment_pending_attempt {1 if metrics.pending_attempt else 0}",
        "# HELP ton_tracker_deployment_ledger_events Number of verified hash-chained deployment events.",
        "# TYPE ton_tracker_deployment_ledger_events gauge",
        f"ton_tracker_deployment_ledger_events {metrics.ledger_event_count}",
        "# HELP ton_tracker_deployment_receipt_bound Active receipt is bound to the verified ledger head.",
        "# TYPE ton_tracker_deployment_receipt_bound gauge",
        f"ton_tracker_deployment_receipt_bound {1 if metrics.receipt_bound else 0}",
        "# HELP ton_tracker_deployment_state_info One-hot deployment audit status.",
        "# TYPE ton_tracker_deployment_state_info gauge",
    ]
    for status in _STATUSES:
        lines.append(
            f'ton_tracker_deployment_state_info{{status="{status}"}} '
            f"{1 if status == metrics.status else 0}"
        )
    return "\n".join(lines) + "\n"


class DeploymentMonitorServer(ThreadingHTTPServer):
    """Internal-only HTTP server carrying the monitored state directory."""

    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: _ServerAddress, state_directory: Path) -> None:
        self.state_directory = state_directory
        super().__init__(address, DeploymentMonitorHandler)


class DeploymentMonitorHandler(BaseHTTPRequestHandler):
    """Serve only a liveness probe and Prometheus metrics."""

    server: DeploymentMonitorServer

    def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path == "/healthz":
            self._write_response(200, b"ok\n", "text/plain; charset=utf-8")
            return
        if self.path == "/metrics":
            metrics = collect_deployment_audit_metrics(self.server.state_directory)
            payload = render_deployment_prometheus(metrics).encode("ascii")
            self._write_response(200, payload, _METRICS_CONTENT_TYPE)
            return
        self._write_response(404, b"not found\n", "text/plain; charset=utf-8")

    def _write_response(self, status: int, payload: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, _format: str, *_args: object) -> None:
        return


def create_monitor_server(
    listen: str,
    port: int,
    state_directory: Path,
) -> DeploymentMonitorServer:
    """Create the bounded internal server without starting a thread."""
    return DeploymentMonitorServer((listen, port), state_directory)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Expose sanitized deployment state metrics for Prometheus."
    )
    parser.add_argument("--state-directory", type=Path, required=True)
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9101)
    args = parser.parse_args()
    if args.port < 1 or args.port > 65_535:
        parser.error("--port must be between 1 and 65535")
    with create_monitor_server(args.listen, args.port, args.state_directory) as server:
        server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    main()
