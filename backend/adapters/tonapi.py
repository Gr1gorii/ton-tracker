"""TonAPI REST adapter.

This is a backend provider foundation for TON-native wallet and jetton data.
It is intentionally not wired into dashboard analysis yet.

* ``DATA_MODE=mock`` -> never queries TonAPI.
* ``DATA_MODE=real`` -> can query TonAPI public endpoints at adapter method
  call time. ``TONAPI_API_KEY`` is optional; public mode may be rate-limited.

TonAPI coverage here is scoped to account-level TON/jetton data. This adapter
does not provide full wallet intelligence by itself.
"""

from __future__ import annotations

import json
from typing import Any, Optional
import urllib.error
import urllib.parse
import urllib.request

from config import (
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_NOT_CONFIGURED,
    ProviderResult,
    Settings,
    get_settings,
)

_HTTP_TIMEOUT = 10


class TonapiAdapter:
    """Adapter for TonAPI account and jetton data."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    # -- Configuration ---------------------------------------------------

    def is_configured(self) -> bool:
        return self._validated_base_url() is not None

    def has_api_key(self) -> bool:
        return bool(self.settings.tonapi_api_key)

    def _validated_base_url(self) -> str | None:
        base_url = (self.settings.tonapi_base_url or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(base_url)
        if not base_url or parsed.scheme not in ("http", "https"):
            return None
        if not parsed.netloc:
            return None
        return base_url

    def _not_configured(self) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_PROVIDER_NOT_CONFIGURED,
            "TonAPI base URL is missing or invalid. TonAPI account and "
            "jetton data is unavailable.",
            source="real",
        )

    def _provider_error(self, message: str) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_PROVIDER_ERROR,
            self._sanitize_diagnostic(message) or "TonAPI provider error.",
            source="real",
        )

    # -- Status ----------------------------------------------------------

    def status(self) -> dict:
        configured = self.is_configured()
        if self.settings.is_mock:
            return {
                "configured": configured,
                "available": True,
                "message": (
                    "Mock mode: TonAPI is not actively queried. TonAPI "
                    "account and jetton responses are mock/offline only."
                ),
            }

        if not configured:
            return {
                "configured": False,
                "available": False,
                "message": (
                    "TonAPI provider is not configured: base URL is missing "
                    "or invalid. TonAPI account and jetton requests cannot be "
                    "attempted."
                ),
            }

        if self.has_api_key():
            auth_note = "TONAPI_API_KEY is configured."
        else:
            auth_note = (
                "TONAPI_API_KEY is not configured; public TonAPI requests can "
                "be attempted but rate limits may apply."
            )

        return {
            "configured": True,
            "available": True,
            "message": (
                "Real mode: TonAPI requests can be attempted at provider call "
                f"time. {auth_note} TonAPI is for account-level TON and "
                "jetton data; it is not connected to dashboard wallet "
                "intelligence yet."
            ),
        }

    # -- Request client --------------------------------------------------

    @staticmethod
    def _query_value(value: Any) -> Any:
        if isinstance(value, bool):
            return "true" if value else "false"
        return value

    def _url(self, path: str, query: Optional[dict[str, Any]] = None) -> str | None:
        base_url = self._validated_base_url()
        if base_url is None:
            return None

        cleaned_path = "/" + path.lstrip("/")
        url = f"{base_url}{cleaned_path}"
        if query:
            normalized = {
                key: self._query_value(value)
                for key, value in query.items()
                if value is not None
            }
            if normalized:
                url = f"{url}?{urllib.parse.urlencode(normalized, doseq=True)}"
        return url

    def fetch_json(
        self,
        path: str,
        query: Optional[dict[str, Any]] = None,
        method: str = "GET",
        body: Optional[dict[str, Any]] = None,
        timeout: int = _HTTP_TIMEOUT,
    ) -> ProviderResult:
        """Fetch JSON from TonAPI and convert provider errors safely."""
        url = self._url(path, query)
        if url is None:
            return self._not_configured()

        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "ton-check/0.7.0",
        }
        if self.settings.tonapi_api_key:
            headers["Authorization"] = f"Bearer {self.settings.tonapi_api_key}"
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method.upper(),
        )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_body = response.read().decode("utf-8")
            payload = json.loads(raw_body)
        except urllib.error.HTTPError as exc:
            return self._provider_error(
                f"TonAPI HTTP error: {exc.code} {exc.reason}."
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return self._provider_error(f"TonAPI network error: {exc}.")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._provider_error("TonAPI returned invalid JSON.")

        return ProviderResult.success(
            payload,
            source="real",
            message="TonAPI JSON response fetched.",
        )

    # -- Jettons preview -------------------------------------------------

    def get_account_jettons_preview(
        self,
        account_address: str,
        limit: int = 10,
    ) -> ProviderResult:
        """Fetch and normalize a small TonAPI account jettons preview."""
        account = self._optional_string(account_address)
        if account is None:
            return self._provider_error("TonAPI account address is required.")
        if limit < 1:
            return self._provider_error(
                "TonAPI jettons preview limit must be at least 1."
            )

        if self.settings.is_mock:
            return ProviderResult.success(
                {
                    "wallet_address": account,
                    "jettons": [],
                    "preview_count": 0,
                    "total_jettons": 0,
                },
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        encoded_account = urllib.parse.quote(account, safe="")
        result = self.fetch_json(f"/v2/accounts/{encoded_account}/jettons")
        if not result.ok:
            return result

        try:
            jettons = self.normalize_account_jettons_response(
                result.data,
                account,
            )
        except ValueError as exc:
            return self._provider_error(
                f"TonAPI response had an unexpected structure: {exc}."
            )

        preview = jettons[:limit]
        return ProviderResult.success(
            {
                "wallet_address": account,
                "jettons": preview,
                "preview_count": len(preview),
                "total_jettons": len(jettons),
            },
            source="real",
            message=(
                "TonAPI account jettons preview fetched. This is account-level "
                "TON/jetton data only and is not connected to dashboard wallet "
                "intelligence yet."
            ),
        )

    # -- Normalization ---------------------------------------------------

    @classmethod
    def normalize_account_jettons_response(
        cls,
        payload: Any,
        wallet_address: str,
    ) -> list[dict]:
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")

        balances = payload.get("balances")
        if not isinstance(balances, list):
            raise ValueError("balances must be a list")

        normalized = []
        for index, raw_balance in enumerate(balances):
            if not isinstance(raw_balance, dict):
                raise ValueError(f"balance {index} must be an object")
            normalized.append(cls.normalize_jetton_balance(raw_balance,
                                                           wallet_address))
        return normalized

    @classmethod
    def normalize_jetton_balance(
        cls,
        raw_balance: dict,
        wallet_address: str,
    ) -> dict:
        jetton = raw_balance.get("jetton")
        if not isinstance(jetton, dict):
            jetton = {}

        jetton_address = cls._optional_string(
            jetton.get("address")
            or jetton.get("master")
            or raw_balance.get("jetton_address")
            or raw_balance.get("jetton_master")
        )
        if jetton_address is None:
            raise ValueError("jetton balance is missing jetton address")

        return {
            "wallet_address": wallet_address,
            "jetton_address": jetton_address,
            "jetton_name": cls._optional_string(jetton.get("name")),
            "jetton_symbol": cls._optional_string(jetton.get("symbol")),
            "balance": cls._optional_string(raw_balance.get("balance")),
            "decimals": cls._optional_int(jetton.get("decimals")),
            "image": cls._optional_string(jetton.get("image")),
            "price_usd": cls._optional_string(raw_balance.get("price")),
            "wallet_contract_address": cls._optional_string(
                raw_balance.get("wallet_address")
            ),
            "source": "tonapi",
        }

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    def _sanitize_diagnostic(self, value: Any) -> str | None:
        text = self._optional_string(value)
        if text is None:
            return None
        api_key = self.settings.tonapi_api_key
        if api_key:
            text = text.replace(api_key, "[redacted]")
        return text[:500]
