"""Application configuration and provider plumbing for v0.2.

Loads environment variables that select the data mode and configure the
external data providers. The default mode is ``mock`` so the app keeps working
with bundled mock data when nothing is configured.

A tiny ``.env`` loader is included (no extra dependency) so a local
``backend/.env`` file is picked up automatically. Real OS environment variables
always take precedence over ``.env`` values.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

DEFAULT_GECKOTERMINAL_BASE_URL = "https://api.geckoterminal.com/api/v2"
DEFAULT_STONFI_BASE_URL = "https://api.ston.fi"
DEFAULT_TONAPI_BASE_URL = "https://tonapi.io"
DEFAULT_TONAPI_TESTNET_BASE_URL = "https://testnet.tonapi.io"

# Machine-readable provider error codes.
ERROR_PROVIDER_NOT_CONFIGURED = "provider_not_configured"
ERROR_PROVIDER_ERROR = "provider_error"
ERROR_PROVIDER_PROTOCOL = "provider_protocol_error"
ERROR_PROVIDER_COVERAGE_UNAVAILABLE = "provider_coverage_unavailable"
ERROR_NOT_IMPLEMENTED = "real_not_implemented"


def _load_dotenv() -> None:
    """Populate os.environ from backend/.env without overriding real env vars."""
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            # setdefault => real environment variables win over .env file.
            os.environ.setdefault(key, value)
    except OSError:
        # A broken .env file must never crash the app.
        pass


_load_dotenv()


@dataclass
class Settings:
    """Resolved application settings."""

    data_mode: str
    geckoterminal_base_url: str
    ton_api_base_url: str
    ton_api_key: str
    bitquery_api_url: str
    bitquery_api_key: str
    stonfi_base_url: str = DEFAULT_STONFI_BASE_URL
    tonapi_base_url: str = DEFAULT_TONAPI_BASE_URL
    tonapi_api_key: str = ""
    wallet_activity_provider: str = "mock"
    wallet_activity_live_enabled: bool = False
    wallet_activity_live_jetton_limit: int = 100
    wallet_activity_live_tx_limit: int = 100
    wallet_activity_live_tx_max_pages: int = 10
    wallet_activity_live_event_limit: int = 100
    wallet_activity_live_event_max_pages: int = 10
    ton_network: str = "mainnet"
    ton_liteclient_trust_level: int = 1
    ton_liteclient_timeout_seconds: int = 20
    tonconnect_expected_domain: str = "127.0.0.1:5173"
    tonconnect_proof_ttl_seconds: int = 900
    backup_health_file: str = ""
    backup_health_max_age_seconds: int = 172800
    recovery_health_file: str = ""
    recovery_health_max_age_seconds: int = 691200
    wallet_case_job_runner: str = "local"
    wallet_case_job_poll_milliseconds: int = 500
    wallet_case_job_lease_seconds: int = 60
    wallet_case_job_heartbeat_seconds: int = 10
    wallet_case_job_max_attempts: int = 4
    wallet_case_job_retry_base_seconds: int = 2
    wallet_case_job_retry_cap_seconds: int = 60

    @property
    def is_mock(self) -> bool:
        return self.data_mode == "mock"

    @property
    def is_real(self) -> bool:
        return self.data_mode == "real"


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name, default) or "").strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(_env(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def tonapi_base_url_network(base_url: str) -> str | None:
    """Return the network of an official TonAPI host, if recognizable."""
    hostname = (urlparse(base_url).hostname or "").lower()
    if hostname == "tonapi.io":
        return "mainnet"
    if hostname == "testnet.tonapi.io":
        return "testnet"
    return None


def get_settings() -> Settings:
    """Read settings fresh from the environment.

    Intentionally not cached so tests can mutate os.environ between calls.
    """
    mode = _env("DATA_MODE", "mock").lower()
    if mode not in ("mock", "real"):
        mode = "mock"
    ton_network = _env("TON_NETWORK", "mainnet").lower()
    if ton_network not in ("mainnet", "testnet"):
        ton_network = "mainnet"
    default_tonapi_base_url = (
        DEFAULT_TONAPI_TESTNET_BASE_URL
        if ton_network == "testnet"
        else DEFAULT_TONAPI_BASE_URL
    )
    tonapi_base_url = _env("TONAPI_BASE_URL") or default_tonapi_base_url
    wallet_case_job_runner = _env("WALLET_CASE_JOB_RUNNER", "local").lower()
    if wallet_case_job_runner not in {"local", "disabled"}:
        wallet_case_job_runner = "disabled"

    return Settings(
        data_mode=mode,
        geckoterminal_base_url=_env(
            "GECKOTERMINAL_BASE_URL", DEFAULT_GECKOTERMINAL_BASE_URL
        )
        or DEFAULT_GECKOTERMINAL_BASE_URL,
        ton_api_base_url=_env("TON_API_BASE_URL"),
        ton_api_key=_env("TON_API_KEY"),
        bitquery_api_url=_env("BITQUERY_API_URL"),
        bitquery_api_key=_env("BITQUERY_API_KEY"),
        stonfi_base_url=_env("STONFI_BASE_URL", DEFAULT_STONFI_BASE_URL)
        or DEFAULT_STONFI_BASE_URL,
        tonapi_base_url=tonapi_base_url,
        tonapi_api_key=_env("TONAPI_API_KEY"),
        wallet_activity_provider=_env("WALLET_ACTIVITY_PROVIDER", "mock").lower()
        or "mock",
        wallet_activity_live_enabled=_env_bool("WALLET_ACTIVITY_LIVE_ENABLED"),
        wallet_activity_live_jetton_limit=_env_int(
            "WALLET_ACTIVITY_LIVE_JETTON_LIMIT",
            default=100,
            minimum=1,
            maximum=500,
        ),
        wallet_activity_live_tx_limit=_env_int(
            "WALLET_ACTIVITY_LIVE_TX_LIMIT",
            default=100,
            minimum=1,
            maximum=1000,
        ),
        wallet_activity_live_tx_max_pages=_env_int(
            "WALLET_ACTIVITY_LIVE_TX_MAX_PAGES",
            default=10,
            minimum=1,
            maximum=100,
        ),
        wallet_activity_live_event_limit=_env_int(
            "WALLET_ACTIVITY_LIVE_EVENT_LIMIT",
            default=100,
            minimum=1,
            maximum=100,
        ),
        wallet_activity_live_event_max_pages=_env_int(
            "WALLET_ACTIVITY_LIVE_EVENT_MAX_PAGES",
            default=10,
            minimum=1,
            maximum=100,
        ),
        ton_network=ton_network,
        ton_liteclient_trust_level=_env_int(
            "TON_LITECLIENT_TRUST_LEVEL", 1, 0, 1
        ),
        ton_liteclient_timeout_seconds=_env_int(
            "TON_LITECLIENT_TIMEOUT_SECONDS", 20, 5, 60
        ),
        tonconnect_expected_domain=_env(
            "TONCONNECT_EXPECTED_DOMAIN", "127.0.0.1:5173"
        ),
        tonconnect_proof_ttl_seconds=_env_int(
            "TONCONNECT_PROOF_TTL_SECONDS", 900, 60, 3600
        ),
        backup_health_file=_env("BACKUP_HEALTH_FILE"),
        backup_health_max_age_seconds=_env_int(
            "BACKUP_HEALTH_MAX_AGE_SECONDS", 172800, 900, 2592000
        ),
        recovery_health_file=_env("RECOVERY_HEALTH_FILE"),
        recovery_health_max_age_seconds=_env_int(
            "RECOVERY_HEALTH_MAX_AGE_SECONDS", 691200, 3600, 2592000
        ),
        wallet_case_job_runner=wallet_case_job_runner,
        wallet_case_job_poll_milliseconds=_env_int(
            "WALLET_CASE_JOB_POLL_MILLISECONDS", 500, 100, 15000
        ),
        wallet_case_job_lease_seconds=_env_int(
            "WALLET_CASE_JOB_LEASE_SECONDS", 60, 30, 3600
        ),
        wallet_case_job_heartbeat_seconds=_env_int(
            "WALLET_CASE_JOB_HEARTBEAT_SECONDS", 10, 2, 300
        ),
        wallet_case_job_max_attempts=_env_int(
            "WALLET_CASE_JOB_MAX_ATTEMPTS", 4, 1, 10
        ),
        wallet_case_job_retry_base_seconds=_env_int(
            "WALLET_CASE_JOB_RETRY_BASE_SECONDS", 2, 1, 60
        ),
        wallet_case_job_retry_cap_seconds=_env_int(
            "WALLET_CASE_JOB_RETRY_CAP_SECONDS", 60, 2, 900
        ),
    )


@dataclass
class ProviderResult:
    """Uniform result wrapper returned by every adapter method.

    ``ok`` indicates success. On failure, ``error`` carries a machine code
    (see ERROR_* constants) and ``message`` a human-readable explanation.
    ``source`` is ``"mock"`` or ``"real"`` so callers can attribute the data.
    """

    ok: bool
    data: Any = None
    error: Optional[str] = None
    message: Optional[str] = None
    source: str = "mock"
    diagnostic: Optional[str] = None

    @classmethod
    def success(cls, data: Any, source: str = "mock",
                message: Optional[str] = None) -> "ProviderResult":
        return cls(ok=True, data=data, source=source, message=message)

    @classmethod
    def failure(cls, error: str, message: str,
                source: str = "real",
                diagnostic: Optional[str] = None) -> "ProviderResult":
        return cls(
            ok=False,
            error=error,
            message=message,
            source=source,
            diagnostic=diagnostic,
        )

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "message": self.message,
            "source": self.source,
            "diagnostic": self.diagnostic,
        }
