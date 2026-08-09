"""Validate production configuration and smoke-test a deployed GRAM Scope."""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

try:
    from .alertmanager_config import (
        AlertmanagerConfigError,
        validate_alertmanager_config,
        validate_alertmanager_data_directory,
    )
    from .create_release_manifest import load_release_manifest
    from .recovery_point import (
        RecoveryPointError,
        validate_recovery_point_directory,
    )
except ImportError:  # pragma: no cover - direct script execution inside the image
    from alertmanager_config import (
        AlertmanagerConfigError,
        validate_alertmanager_config,
        validate_alertmanager_data_directory,
    )
    from create_release_manifest import load_release_manifest
    from recovery_point import RecoveryPointError, validate_recovery_point_directory


_MAX_RESPONSE_BYTES = 65_536
_RETENTION = re.compile(r"^[1-9][0-9]*(?:s|m|h|d|w|y)$")
_IMAGE_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_NUMERIC_ID = re.compile(r"^(?:0|[1-9][0-9]{0,9})$")


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

    _validate_release_image(
        environment,
        "BACKEND_IMAGE",
        "ghcr.io/gr1gorii/ton-tracker-backend",
        errors,
    )
    _validate_release_image(
        environment,
        "FRONTEND_IMAGE",
        "ghcr.io/gr1gorii/ton-tracker-frontend",
        errors,
    )

    manifest_path = environment.get("DEPLOYMENT_MANIFEST_FILE", "").strip()
    deployment_manifest: dict[str, Any] | None = None
    if not manifest_path or len(manifest_path) > 4096 or "\x00" in manifest_path:
        errors.append("DEPLOYMENT_MANIFEST_FILE is missing or invalid")
    else:
        try:
            deployment_manifest = load_release_manifest(Path(manifest_path))
        except (OSError, ValueError):
            errors.append("DEPLOYMENT_MANIFEST_FILE is missing or invalid")
    if deployment_manifest is not None:
        expected_environment = deployment_manifest["deployment_environment"]
        if any(
            environment.get(name, "").strip() != expected_environment[name]
            for name in ("BACKEND_IMAGE", "FRONTEND_IMAGE")
        ):
            errors.append(
                "BACKEND_IMAGE and FRONTEND_IMAGE must match DEPLOYMENT_MANIFEST_FILE"
            )
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
    recovery_point_interval = _bounded_integer(
        environment,
        "RECOVERY_POINT_INTERVAL_SECONDS",
        86_400,
        3_600,
        604_800,
        errors,
    )
    recovery_point_retry = _bounded_integer(
        environment,
        "RECOVERY_POINT_RETRY_SECONDS",
        300,
        60,
        86_400,
        errors,
    )
    recovery_point_max_age = _bounded_integer(
        environment,
        "RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS",
        172_800,
        3_600,
        2_592_000,
        errors,
    )
    _bounded_integer(
        environment,
        "RECOVERY_POINT_RETENTION",
        14,
        2,
        365,
        errors,
    )
    if (
        recovery_point_retry is not None
        and recovery_point_interval is not None
        and recovery_point_retry >= recovery_point_interval
    ):
        errors.append(
            "RECOVERY_POINT_RETRY_SECONDS must be shorter than the recovery point interval"
        )
    if (
        recovery_point_max_age is not None
        and recovery_point_interval is not None
        and recovery_point_retry is not None
        and recovery_point_max_age
        < recovery_point_interval + recovery_point_retry
    ):
        errors.append(
            "RECOVERY_POINT_HEALTH_MAX_AGE_SECONDS must cover the interval and retry window"
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
    deployment_state_directory = environment.get("DEPLOYMENT_STATE_DIRECTORY", "")
    if (
        not deployment_state_directory
        or deployment_state_directory != deployment_state_directory.strip()
        or len(deployment_state_directory) > 4096
        or "\x00" in deployment_state_directory
        or not Path(deployment_state_directory).is_absolute()
    ):
        errors.append("DEPLOYMENT_STATE_DIRECTORY must be an absolute host path")
    recovery_point_directory = environment.get("DISASTER_RECOVERY_DIRECTORY", "")
    recovery_point_directory_valid = not (
        not recovery_point_directory
        or recovery_point_directory != recovery_point_directory.strip()
        or len(recovery_point_directory) > 4096
        or "\x00" in recovery_point_directory
        or not Path(recovery_point_directory).is_absolute()
    )
    if not recovery_point_directory_valid:
        errors.append("DISASTER_RECOVERY_DIRECTORY must be an absolute private path")
    else:
        try:
            validate_recovery_point_directory(Path(recovery_point_directory))
        except RecoveryPointError:
            errors.append("DISASTER_RECOVERY_DIRECTORY is missing or unsafe")
    for name in ("DEPLOYMENT_STATE_UID", "DEPLOYMENT_STATE_GID"):
        value = environment.get(name, "")
        if (
            _NUMERIC_ID.fullmatch(value) is None
            or int(value or "0") > 2_147_483_647
        ):
            errors.append(f"{name} must be a canonical numeric host identifier")
    prometheus_retention = environment.get("PROMETHEUS_RETENTION", "15d").strip()
    if _RETENTION.fullmatch(prometheus_retention) is None:
        errors.append("PROMETHEUS_RETENTION must be a positive Prometheus duration")
    alertmanager_retention = environment.get(
        "ALERTMANAGER_RETENTION", "120h"
    ).strip()
    if _RETENTION.fullmatch(alertmanager_retention) is None:
        errors.append(
            "ALERTMANAGER_RETENTION must be a positive Prometheus duration"
        )

    alertmanager_config = environment.get("ALERTMANAGER_CONFIG_FILE", "")
    if (
        not alertmanager_config
        or alertmanager_config != alertmanager_config.strip()
        or len(alertmanager_config) > 4096
        or "\x00" in alertmanager_config
        or not Path(alertmanager_config).is_absolute()
    ):
        errors.append("ALERTMANAGER_CONFIG_FILE must be an absolute private file")
    else:
        try:
            validate_alertmanager_config(Path(alertmanager_config))
        except AlertmanagerConfigError:
            errors.append("ALERTMANAGER_CONFIG_FILE is missing, unsafe, or invalid")

    alertmanager_data = environment.get("ALERTMANAGER_DATA_DIRECTORY", "")
    if (
        not alertmanager_data
        or alertmanager_data != alertmanager_data.strip()
        or len(alertmanager_data) > 4096
        or "\x00" in alertmanager_data
        or not Path(alertmanager_data).is_absolute()
    ):
        errors.append("ALERTMANAGER_DATA_DIRECTORY must be an absolute private path")
    else:
        try:
            validate_alertmanager_data_directory(Path(alertmanager_data))
        except AlertmanagerConfigError:
            errors.append("ALERTMANAGER_DATA_DIRECTORY is missing or unsafe")
    if recovery_point_directory_valid:
        for name, value in (
            ("DEPLOYMENT_STATE_DIRECTORY", deployment_state_directory),
            ("ALERTMANAGER_DATA_DIRECTORY", alertmanager_data),
        ):
            if _same_directory(recovery_point_directory, value):
                errors.append(f"DISASTER_RECOVERY_DIRECTORY must differ from {name}")
    return errors


def _validate_release_image(
    environment: Mapping[str, str],
    name: str,
    repository: str,
    errors: list[str],
) -> None:
    value = environment.get(name, "").strip()
    digest_prefix = f"{repository}@"
    if value.startswith(digest_prefix):
        digest = value.removeprefix(digest_prefix)
        if _IMAGE_DIGEST.fullmatch(digest) is not None:
            return
    errors.append(
        f"{name} must use the expected GHCR repository pinned by sha256 digest"
    )


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
        "/api/ops/ready",
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
    operational = _json_object(
        probes.get("/api/ops/ready"),
        "/api/ops/ready",
        errors,
    )
    if operational is not None and operational != {
        "status": "ready",
        "backup": "ready",
        "recovery": "ready",
        "version": "0.2.1",
    }:
        errors.append("/api/ops/ready recovery state is invalid")
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


def _same_directory(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    try:
        return os.path.samefile(left, right)
    except OSError:
        return False


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
