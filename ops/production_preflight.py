"""Validate production configuration and smoke-test a deployed GRAM Scope."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen


_MAX_RESPONSE_BYTES = 65_536
_RETENTION = re.compile(r"^[1-9][0-9]*(?:s|m|h|d|w|y)$")


@dataclass(frozen=True)
class HttpProbe:
    status: int
    headers: Mapping[str, str]
    body: bytes


def validate_environment(environment: Mapping[str, str]) -> list[str]:
    """Return field-only validation errors without exposing secret values."""
    errors: list[str] = []
    public_url = environment.get("PUBLIC_APP_URL", "").strip()
    expected_domain = environment.get("TONCONNECT_EXPECTED_DOMAIN", "").strip()
    api_key = environment.get("TONAPI_API_KEY", "")
    try:
        public = urlsplit(public_url)
        public_valid = (
            public.scheme == "https"
            and bool(public.hostname)
            and public.username is None
            and public.password is None
            and not public.query
            and not public.fragment
            and public.path in ("", "/")
            and not public_url.endswith("/")
            and (public.port is None or public.port >= 1)
        )
    except ValueError:
        public = None
        public_valid = False
    if not public_valid:
        errors.append("PUBLIC_APP_URL must be an origin-only HTTPS URL without credentials")
    if not expected_domain or "://" in expected_domain or "/" in expected_domain:
        errors.append("TONCONNECT_EXPECTED_DOMAIN must be a host with an optional port")
    elif public is not None and public.netloc and expected_domain.lower() != public.netloc.lower():
        errors.append("TONCONNECT_EXPECTED_DOMAIN must match PUBLIC_APP_URL")
    if len(api_key) < 16 or len(api_key) > 4096 or any(char.isspace() for char in api_key):
        errors.append("TONAPI_API_KEY is missing or structurally invalid")

    try:
        tonapi_url = urlsplit(
            environment.get("TONAPI_BASE_URL", "https://tonapi.io").strip()
        )
        tonapi_valid = (
            tonapi_url.scheme == "https"
            and bool(tonapi_url.hostname)
            and tonapi_url.username is None
            and tonapi_url.password is None
            and not tonapi_url.query
            and not tonapi_url.fragment
            and (tonapi_url.port is None or tonapi_url.port >= 1)
        )
    except ValueError:
        tonapi_valid = False
    if not tonapi_valid:
        errors.append("TONAPI_BASE_URL must be an HTTPS URL without credentials")
    if environment.get("DATA_MODE", "").strip().lower() != "real":
        errors.append("DATA_MODE must be real")
    if environment.get("WALLET_ACTIVITY_PROVIDER", "").strip().lower() != "tonapi":
        errors.append("WALLET_ACTIVITY_PROVIDER must be tonapi")
    if environment.get("WALLET_ACTIVITY_LIVE_ENABLED", "").strip().lower() != "true":
        errors.append("WALLET_ACTIVITY_LIVE_ENABLED must be true")
    if environment.get("TON_LITECLIENT_TRUST_LEVEL", "").strip() != "0":
        errors.append("TON_LITECLIENT_TRUST_LEVEL must be zero")
    if environment.get("TON_NETWORK", "mainnet").strip().lower() not in {
        "mainnet",
        "testnet",
    }:
        errors.append("TON_NETWORK must be mainnet or testnet")

    _bounded_integer(environment, "APP_PORT", 8080, 1, 65_535, errors)
    backup_interval = _bounded_integer(
        environment,
        "BACKUP_INTERVAL_SECONDS",
        86_400,
        300,
        604_800,
        errors,
    )
    backup_retention = _bounded_integer(
        environment,
        "BACKUP_RETENTION",
        14,
        2,
        365,
        errors,
    )
    backup_max_age = _bounded_integer(
        environment,
        "BACKUP_HEALTH_MAX_AGE_SECONDS",
        172_800,
        900,
        2_592_000,
        errors,
    )
    recovery_interval = _bounded_integer(
        environment,
        "RECOVERY_INTERVAL_SECONDS",
        604_800,
        3_600,
        2_592_000,
        errors,
    )
    recovery_retry = _bounded_integer(
        environment,
        "RECOVERY_RETRY_SECONDS",
        300,
        60,
        86_400,
        errors,
    )
    recovery_max_age = _bounded_integer(
        environment,
        "RECOVERY_HEALTH_MAX_AGE_SECONDS",
        691_200,
        3_600,
        2_592_000,
        errors,
    )
    if backup_interval is not None and backup_max_age is not None:
        if backup_max_age < backup_interval * 2:
            errors.append("BACKUP_HEALTH_MAX_AGE_SECONDS must cover two backup intervals")
    if (
        backup_retention is not None
        and backup_interval is not None
        and recovery_interval is not None
    ):
        if (backup_retention - 1) * backup_interval < recovery_interval:
            errors.append("BACKUP_RETENTION must preserve a full recovery interval")
    if (
        recovery_max_age is not None
        and recovery_interval is not None
        and recovery_retry is not None
    ):
        if recovery_max_age < recovery_interval + recovery_retry:
            errors.append(
                "RECOVERY_HEALTH_MAX_AGE_SECONDS must cover the recovery interval and retry window"
            )
    if recovery_retry is not None and recovery_interval is not None:
        if recovery_retry >= recovery_interval:
            errors.append("RECOVERY_RETRY_SECONDS must be shorter than the recovery interval")
    prometheus_retention = environment.get("PROMETHEUS_RETENTION", "15d").strip()
    if _RETENTION.fullmatch(prometheus_retention) is None:
        errors.append("PROMETHEUS_RETENTION must be a positive Prometheus duration")
    return errors


def run_smoke_checks(
    public_url: str,
    *,
    fetch: Callable[[str], HttpProbe] | None = None,
    expected_public_url: str | None = None,
) -> list[str]:
    """Probe the public origin with bounded responses and strict contracts."""
    origin = public_url.rstrip("/")
    try:
        parsed = urlsplit(origin)
        loopback_http = (
            expected_public_url is not None
            and parsed.scheme == "http"
            and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
        )
        valid_origin = (
            (parsed.scheme == "https" or loopback_http)
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not parsed.path
            and (parsed.port is None or parsed.port >= 1)
        )
    except ValueError:
        valid_origin = False
    if not valid_origin:
        return ["smoke URL must be an origin-only HTTPS URL without credentials"]
    manifest_origin = (expected_public_url or origin).rstrip("/")
    if expected_public_url is not None and not _is_public_https_origin(manifest_origin):
        return ["expected public URL must be an origin-only HTTPS URL"]
    get = fetch or _fetch
    errors: list[str] = []
    probes: dict[str, HttpProbe] = {}
    for path in (
        "/healthz",
        "/",
        "/gram-scope-icon.png",
        "/api/ready",
        "/api/health",
        "/tonconnect-manifest.json",
    ):
        try:
            probes[path] = get(urljoin(f"{origin}/", path.lstrip("/")))
        except (OSError, RuntimeError, HTTPError, URLError, ValueError):
            errors.append(f"{path} request failed")
    healthz = probes.get("/healthz")
    if healthz is not None:
        if healthz.status != 200 or healthz.body != b"ok\n":
            errors.append("/healthz response is invalid")
        headers = {key.lower(): value for key, value in healthz.headers.items()}
        if headers.get("x-content-type-options", "").lower() != "nosniff":
            errors.append("security headers are missing nosniff")
        policy = headers.get("content-security-policy", "")
        if "default-src 'self'" not in policy or "frame-ancestors 'none'" not in policy:
            errors.append("security headers contain an invalid content security policy")
    landing = probes.get("/")
    if landing is not None and (
        landing.status != 200 or b'<div id="root"></div>' not in landing.body
    ):
        errors.append("landing document is invalid")
    icon = probes.get("/gram-scope-icon.png")
    if icon is not None and (
        icon.status != 200 or not icon.body.startswith(b"\x89PNG\r\n\x1a\n")
    ):
        errors.append("public application icon is invalid")
    ready = _json_object(probes.get("/api/ready"), "/api/ready", errors)
    if ready is not None and (
        ready.get("status") != "ready" or ready.get("database") != "ready"
    ):
        errors.append("/api/ready dependency state is invalid")
    health = _json_object(probes.get("/api/health"), "/api/health", errors)
    if health is not None and (
        health.get("status") != "ok"
        or health.get("data_mode") != "real"
        or health.get("is_mock") is not False
    ):
        errors.append("/api/health is not in guarded real mode")
    manifest = _json_object(
        probes.get("/tonconnect-manifest.json"),
        "/tonconnect-manifest.json",
        errors,
    )
    if manifest is not None and (
        manifest.get("url") != manifest_origin
        or manifest.get("name") != "GRAM Scope"
        or manifest.get("iconUrl") != f"{manifest_origin}/gram-scope-icon.png"
    ):
        errors.append("TonConnect manifest does not match the public origin")
    return errors


def _is_public_https_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not parsed.path
            and (parsed.port is None or parsed.port >= 1)
        )
    except ValueError:
        return False


def _bounded_integer(
    environment: Mapping[str, str],
    name: str,
    default: int,
    minimum: int,
    maximum: int,
    errors: list[str],
) -> int | None:
    raw = environment.get(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name} must be an integer")
        return None
    if value < minimum or value > maximum:
        errors.append(f"{name} is outside the supported range")
        return None
    return value


def _fetch(url: str) -> HttpProbe:
    request = Request(
        url,
        headers={
            "Accept": "application/json,text/plain,text/html,image/png",
            "User-Agent": "GRAM-Scope-Preflight/1",
        },
    )
    with urlopen(request, timeout=10) as response:
        if response.geturl() != url:
            raise RuntimeError("Smoke endpoint redirected unexpectedly.")
        body = response.read(_MAX_RESPONSE_BYTES + 1)
        if len(body) > _MAX_RESPONSE_BYTES:
            raise RuntimeError("Smoke response exceeds the size limit.")
        return HttpProbe(
            status=response.status,
            headers=dict(response.headers.items()),
            body=body,
        )


def _json_object(
    probe: HttpProbe | None,
    path: str,
    errors: list[str],
) -> dict[str, Any] | None:
    if probe is None:
        return None
    if probe.status != 200:
        errors.append(f"{path} returned a non-success status")
        return None
    try:
        payload = json.loads(probe.body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        errors.append(f"{path} returned invalid JSON")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{path} returned a non-object JSON payload")
        return None
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke-url")
    parser.add_argument("--expected-public-url")
    args = parser.parse_args()
    if args.expected_public_url and not args.smoke_url:
        parser.error("--expected-public-url requires --smoke-url")
    errors = (
        run_smoke_checks(
            args.smoke_url,
            expected_public_url=args.expected_public_url,
        )
        if args.smoke_url
        else validate_environment(os.environ)
    )
    if errors:
        for error in errors:
            print(f"preflight error: {error}", file=sys.stderr)
        raise SystemExit(2)
    print("production preflight passed", flush=True)


if __name__ == "__main__":
    main()
