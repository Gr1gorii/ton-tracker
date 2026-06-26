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

DEFAULT_GECKOTERMINAL_BASE_URL = "https://api.geckoterminal.com/api/v2"
DEFAULT_STONFI_BASE_URL = "https://api.ston.fi"
DEFAULT_TONAPI_BASE_URL = "https://tonapi.io"

# Machine-readable provider error codes.
ERROR_PROVIDER_NOT_CONFIGURED = "provider_not_configured"
ERROR_PROVIDER_ERROR = "provider_error"
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


def get_settings() -> Settings:
    """Read settings fresh from the environment.

    Intentionally not cached so tests can mutate os.environ between calls.
    """
    mode = _env("DATA_MODE", "mock").lower()
    if mode not in ("mock", "real"):
        mode = "mock"

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
        tonapi_base_url=_env("TONAPI_BASE_URL", DEFAULT_TONAPI_BASE_URL)
        or DEFAULT_TONAPI_BASE_URL,
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
