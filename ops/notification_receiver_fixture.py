"""Bounded webhook receiver used only by the container release gate."""

from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from typing import ClassVar


_MAX_BODY_BYTES = 65_536
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


class NotificationFixtureHandler(BaseHTTPRequestHandler):
    server_version = "GRAMScopeNotificationFixture/1"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    accepted_drills: ClassVar[int] = 0

    def do_GET(self) -> None:  # noqa: N802 - stdlib callback contract
        if self.path != "/healthz":
            self._respond(404, b"not found\n")
            return
        self._respond(200, b"ok\n")

    def do_POST(self) -> None:  # noqa: N802 - stdlib callback contract
        if self.path != "/alerts":
            self._respond(404, b"not found\n")
            return
        raw_length = self.headers.get("Content-Length", "")
        content_type = self.headers.get("Content-Type", "")
        if (
            not raw_length.isascii()
            or not raw_length.isdigit()
            or raw_length.startswith("0")
            or not 1 <= int(raw_length) <= _MAX_BODY_BYTES
            or content_type.split(";", 1)[0].strip().lower() != "application/json"
        ):
            self._respond(400, b"invalid request\n")
            return
        body = self.rfile.read(int(raw_length))
        if not self._valid_drill(body):
            self._respond(400, b"invalid request\n")
            return
        type(self).accepted_drills += 1
        self._respond(204, b"")

    def log_message(self, _format: str, *_args: object) -> None:
        return

    @staticmethod
    def _valid_drill(body: bytes) -> bool:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (RecursionError, UnicodeError, json.JSONDecodeError):
            return False
        if not isinstance(payload, dict) or len(payload) > 16:
            return False
        alerts = payload.get("alerts")
        if not isinstance(alerts, list) or not 1 <= len(alerts) <= 4:
            return False
        for alert in alerts:
            if not isinstance(alert, dict):
                return False
            labels = alert.get("labels")
            if (
                isinstance(labels, dict)
                and labels.get("alertname") == "GramScopeNotificationDrill"
                and isinstance(labels.get("gram_scope_drill"), str)
                and _TOKEN.fullmatch(labels["gram_scope_drill"]) is not None
            ):
                return True
        return False

    def _respond(self, status: int, body: bytes) -> None:
        self.close_connection = True
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()
        if body:
            self.wfile.write(body)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the release-gate webhook fixture")
    parser.add_argument("--listen", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9199)
    args = parser.parse_args()
    if not 1 <= args.port <= 65_535:
        parser.error("port must be between 1 and 65535")
    server = ThreadingHTTPServer((args.listen, args.port), NotificationFixtureHandler)
    server.serve_forever()


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    main()
