"""Production configuration and public smoke gate tests."""

import json

from ops.production_preflight import HttpProbe, run_smoke_checks, validate_environment


def _environment() -> dict[str, str]:
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
        "APP_PORT": "8080",
        "BACKUP_INTERVAL_SECONDS": "86400",
        "BACKUP_RETENTION": "14",
        "BACKUP_HEALTH_MAX_AGE_SECONDS": "172800",
        "RECOVERY_INTERVAL_SECONDS": "604800",
        "RECOVERY_RETRY_SECONDS": "300",
        "RECOVERY_HEALTH_MAX_AGE_SECONDS": "691200",
        "PROMETHEUS_RETENTION": "15d",
    }


def test_production_environment_contract_passes_without_exposing_secret():
    environment = _environment()
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


def test_production_environment_requires_recovery_within_retention():
    environment = _environment()
    environment["BACKUP_RETENTION"] = "2"
    environment["RECOVERY_INTERVAL_SECONDS"] = "604800"
    errors = validate_environment(environment)
    assert errors == ["BACKUP_RETENTION must preserve a full recovery interval"]

    environment["RECOVERY_INTERVAL_SECONDS"] = "not-an-integer"
    errors = validate_environment(environment)
    assert "RECOVERY_INTERVAL_SECONDS must be an integer" in errors

    environment = _environment()
    environment["PUBLIC_APP_URL"] = "https://[invalid"
    environment["TONAPI_BASE_URL"] = "https://[invalid"
    errors = validate_environment(environment)
    assert "PUBLIC_APP_URL must be an origin-only HTTPS URL without credentials" in errors
    assert "TONAPI_BASE_URL must be an HTTPS URL without credentials" in errors


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
    assert "/api/health is not in guarded real mode" in errors
    assert "/tonconnect-manifest.json returned invalid JSON" in errors
    assert "not-json" not in " ".join(errors)


def _json_probe(payload: dict) -> HttpProbe:
    return HttpProbe(
        status=200,
        headers={"Content-Type": "application/json"},
        body=json.dumps(payload).encode("utf-8"),
    )
