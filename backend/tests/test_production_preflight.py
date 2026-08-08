"""Production configuration and public smoke gate tests."""

import json
import sys

import pytest

from ops.create_release_manifest import create_release_manifest, write_release_manifest
from ops.production_preflight import (
    HttpProbe,
    main,
    run_smoke_checks,
    validate_environment,
)


def _environment(tmp_path) -> dict[str, str]:
    manifest = tmp_path / "deployment.json"
    write_release_manifest(
        create_release_manifest(
            tag="v0.57.0",
            source_commit="1" * 40,
            backend_digest="sha256:" + "a" * 64,
            frontend_digest="sha256:" + "b" * 64,
        ),
        manifest,
    )
    return {
        "PUBLIC_APP_URL": "https://gram.example",
        "TONCONNECT_EXPECTED_DOMAIN": "gram.example",
        "TONAPI_API_KEY": "test-key-with-adequate-length",
        "TONAPI_BASE_URL": "https://tonapi.io",
        "DATA_MODE": "real",
        "WALLET_ACTIVITY_PROVIDER": "tonapi",
        "WALLET_ACTIVITY_LIVE_ENABLED": "true",
        "TON_LITECLIENT_TRUST_LEVEL": "0",
        "TON_NETWORK": "mainnet",
        "BACKEND_IMAGE": (
            "ghcr.io/gr1gorii/ton-tracker-backend@sha256:" + "a" * 64
        ),
        "FRONTEND_IMAGE": (
            "ghcr.io/gr1gorii/ton-tracker-frontend@sha256:" + "b" * 64
        ),
        "DEPLOYMENT_MANIFEST_FILE": str(manifest),
        "APP_PORT": "8080",
        "BACKUP_INTERVAL_SECONDS": "86400",
        "BACKUP_RETENTION": "14",
        "BACKUP_HEALTH_MAX_AGE_SECONDS": "172800",
        "RECOVERY_INTERVAL_SECONDS": "604800",
        "RECOVERY_RETRY_SECONDS": "300",
        "RECOVERY_HEALTH_MAX_AGE_SECONDS": "691200",
        "DEPLOYMENT_STATE_DIRECTORY": str(tmp_path / "deployment-state"),
        "DEPLOYMENT_STATE_UID": "1000",
        "DEPLOYMENT_STATE_GID": "1000",
        "PROMETHEUS_RETENTION": "15d",
    }


def test_production_environment_contract_passes_without_exposing_secret(tmp_path):
    environment = _environment(tmp_path)
    assert validate_environment(environment) == []

    environment["PUBLIC_APP_URL"] = "http://user:password@gram.example/path?secret=1"
    environment["TONCONNECT_EXPECTED_DOMAIN"] = "wrong.example"
    environment["TONAPI_API_KEY"] = "secret"
    environment["BACKUP_HEALTH_MAX_AGE_SECONDS"] = "86400"
    errors = validate_environment(environment)
    joined = " ".join(errors)
    assert "PUBLIC_APP_URL" in joined
    assert "TONCONNECT_EXPECTED_DOMAIN" in joined
    assert "TONAPI_API_KEY" in joined
    assert "BACKUP_HEALTH_MAX_AGE_SECONDS" in joined
    assert "password" not in joined
    assert "secret" not in joined


def test_production_environment_requires_recovery_within_retention(tmp_path):
    environment = _environment(tmp_path)
    environment["BACKUP_RETENTION"] = "2"
    environment["RECOVERY_INTERVAL_SECONDS"] = "604800"
    errors = validate_environment(environment)
    assert errors == ["BACKUP_RETENTION must preserve a full recovery interval"]

    environment["RECOVERY_INTERVAL_SECONDS"] = "not-an-integer"
    errors = validate_environment(environment)
    assert "RECOVERY_INTERVAL_SECONDS must be an integer" in errors

    environment = _environment(tmp_path)
    environment["PUBLIC_APP_URL"] = "https://[invalid"
    environment["TONAPI_BASE_URL"] = "https://[invalid"
    errors = validate_environment(environment)
    assert "PUBLIC_APP_URL must be an origin-only HTTPS URL without credentials" in errors
    assert "TONAPI_BASE_URL must be an HTTPS URL without credentials" in errors


def test_production_environment_requires_safe_deployment_monitor_identity(tmp_path):
    environment = _environment(tmp_path)
    environment["DEPLOYMENT_STATE_DIRECTORY"] = "relative/state"
    environment["DEPLOYMENT_STATE_UID"] = "01"
    environment["DEPLOYMENT_STATE_GID"] = "not-a-number"

    assert validate_environment(environment) == [
        "DEPLOYMENT_STATE_DIRECTORY must be an absolute host path",
        "DEPLOYMENT_STATE_UID must be a canonical numeric host identifier",
        "DEPLOYMENT_STATE_GID must be a canonical numeric host identifier",
    ]

    environment = _environment(tmp_path)
    environment["DEPLOYMENT_STATE_UID"] = "2147483648"
    assert validate_environment(environment) == [
        "DEPLOYMENT_STATE_UID must be a canonical numeric host identifier"
    ]

    environment = _environment(tmp_path)
    environment["DEPLOYMENT_STATE_DIRECTORY"] = f" {tmp_path}/deployment-state"
    environment["DEPLOYMENT_STATE_UID"] = "1000 "
    assert validate_environment(environment) == [
        "DEPLOYMENT_STATE_DIRECTORY must be an absolute host path",
        "DEPLOYMENT_STATE_UID must be a canonical numeric host identifier",
    ]


def test_production_image_refs_are_digest_pinned_and_fail_closed(tmp_path):
    environment = _environment(tmp_path)
    environment["BACKEND_IMAGE"] = (
        "ghcr.io/gr1gorii/ton-tracker-backend@sha256:" + "a" * 64
    )
    environment["FRONTEND_IMAGE"] = (
        "ghcr.io/gr1gorii/ton-tracker-frontend@sha256:" + "b" * 64
    )
    assert validate_environment(environment) == []

    invalid_refs = (
        "",
        "ghcr.io/gr1gorii/ton-tracker-backend:latest",
        "ghcr.io/gr1gorii/ton-tracker-backend:0.57.0",
        "registry.example/ton-tracker-backend@sha256:" + "c" * 64,
        "ghcr.io/gr1gorii/ton-tracker-backend@sha256:abcd",
    )
    for image_ref in invalid_refs:
        environment = _environment(tmp_path)
        environment["BACKEND_IMAGE"] = image_ref
        errors = validate_environment(environment)
        assert any(error.startswith("BACKEND_IMAGE must use") for error in errors)
        if image_ref:
            assert image_ref not in " ".join(errors)


def test_production_images_must_match_one_canonical_manifest(tmp_path):
    environment = _environment(tmp_path)
    environment["BACKEND_IMAGE"] = (
        "ghcr.io/gr1gorii/ton-tracker-backend@sha256:" + "c" * 64
    )
    assert validate_environment(environment) == [
        "BACKEND_IMAGE and FRONTEND_IMAGE must match DEPLOYMENT_MANIFEST_FILE"
    ]

    environment = _environment(tmp_path)
    environment.pop("DEPLOYMENT_MANIFEST_FILE")
    assert validate_environment(environment) == [
        "DEPLOYMENT_MANIFEST_FILE is missing or invalid"
    ]

    environment = _environment(tmp_path)
    manifest = tmp_path / "deployment.json"
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["unexpected"] = "must-fail-closed"
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    assert validate_environment(environment) == [
        "DEPLOYMENT_MANIFEST_FILE is missing or invalid"
    ]

    valid_manifest = tmp_path / "valid-deployment.json"
    write_release_manifest(
        create_release_manifest(
            tag="v0.57.0",
            source_commit="1" * 40,
            backend_digest="sha256:" + "a" * 64,
            frontend_digest="sha256:" + "b" * 64,
        ),
        valid_manifest,
    )
    symlink = tmp_path / "deployment-link.json"
    symlink.symlink_to(valid_manifest)
    environment["DEPLOYMENT_MANIFEST_FILE"] = str(symlink)
    errors = validate_environment(environment)
    assert errors == ["DEPLOYMENT_MANIFEST_FILE is missing or invalid"]
    assert str(symlink) not in " ".join(errors)


def test_public_smoke_contract_accepts_guarded_real_release():
    origin = "https://gram.example"
    responses = {
        "/healthz": HttpProbe(
            status=200,
            headers={
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'self'; frame-ancestors 'none'",
            },
            body=b"ok\n",
        ),
        "/": HttpProbe(
            status=200,
            headers={"Content-Type": "text/html"},
            body=b'<html><body><div id="root"></div></body></html>',
        ),
        "/gram-scope-icon.png": HttpProbe(
            status=200,
            headers={"Content-Type": "image/png"},
            body=b"\x89PNG\r\n\x1a\nicon",
        ),
        "/api/ready": _json_probe(
            {"status": "ready", "database": "ready", "version": "0.2.1"}
        ),
        "/api/ops/ready": _json_probe(
            {
                "status": "ready",
                "backup": "ready",
                "recovery": "ready",
                "version": "0.2.1",
            }
        ),
        "/api/health": _json_probe(
            {"status": "ok", "data_mode": "real", "is_mock": False}
        ),
        "/tonconnect-manifest.json": _json_probe(
            {
                "url": origin,
                "name": "GRAM Scope",
                "iconUrl": f"{origin}/gram-scope-icon.png",
            }
        ),
    }

    def fetch(url: str) -> HttpProbe:
        return responses[url.removeprefix(origin)]

    assert run_smoke_checks(origin, fetch=fetch) == []

    loopback = "http://127.0.0.1:18080"

    def fetch_loopback(url: str) -> HttpProbe:
        return responses[url.removeprefix(loopback)]

    assert run_smoke_checks(
        loopback,
        fetch=fetch_loopback,
        expected_public_url=origin,
    ) == []
    assert run_smoke_checks(
        "http://backend.internal:8080",
        fetch=fetch_loopback,
        expected_public_url=origin,
    ) == ["smoke URL must be an origin-only HTTPS URL without credentials"]
    assert run_smoke_checks(
        loopback,
        fetch=fetch_loopback,
        expected_public_url="http://gram.example",
    ) == ["expected public URL must be an origin-only HTTPS URL"]


def test_public_smoke_contract_fails_closed_without_leaking_payloads():
    origin = "https://gram.example"
    assert run_smoke_checks("https://gram.example:not-a-port") == [
        "smoke URL must be an origin-only HTTPS URL without credentials"
    ]

    def fetch(url: str) -> HttpProbe:
        path = url.removeprefix(origin)
        if path == "/healthz":
            return HttpProbe(status=200, headers={}, body=b"wrong")
        if path == "/api/ready":
            return _json_probe({"status": "ready", "database": "down"})
        if path == "/api/health":
            return _json_probe({"status": "ok", "data_mode": "mock", "is_mock": True})
        return HttpProbe(status=200, headers={}, body=b"{not-json")

    errors = run_smoke_checks(origin, fetch=fetch)
    assert "/healthz response is invalid" in errors
    assert "/api/ready dependency state is invalid" in errors
    assert "/api/ops/ready returned invalid JSON" in errors
    assert "/api/health is not in guarded real mode" in errors
    assert "/tonconnect-manifest.json returned invalid JSON" in errors
    assert "not-json" not in " ".join(errors)


def test_expected_public_url_requires_a_smoke_target(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["production_preflight.py", "--expected-public-url", "https://gram.example"],
    )
    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 2


def _json_probe(payload: dict) -> HttpProbe:
    return HttpProbe(
        status=200,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )
