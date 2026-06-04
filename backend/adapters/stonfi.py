"""STON.fi REST API adapter.

This is a backend provider foundation for TON-native STON.fi DEX data.
It is intentionally not wired into the main analysis flow yet.

* ``DATA_MODE=mock`` -> never queries STON.fi.
* ``DATA_MODE=real`` -> can query public STON.fi REST endpoints at adapter
  method call time.

STON.fi coverage is scoped to STON.fi DEX data such as pools, swaps,
liquidity, and market data. It is not a full TON DeFi or wallet indexer.
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


class StonfiAdapter:
    """Adapter for STON.fi DEX data."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    # -- Configuration ---------------------------------------------------

    def is_configured(self) -> bool:
        return self._validated_base_url() is not None

    def _validated_base_url(self) -> str | None:
        base_url = (self.settings.stonfi_base_url or "").strip().rstrip("/")
        parsed = urllib.parse.urlparse(base_url)
        if not base_url or parsed.scheme not in ("http", "https"):
            return None
        if not parsed.netloc:
            return None
        return base_url

    def _not_configured(self) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_PROVIDER_NOT_CONFIGURED,
            "STON.fi base URL is missing or invalid. STON.fi DEX data is "
            "unavailable.",
            source="real",
        )

    @staticmethod
    def _provider_error(message: str) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_PROVIDER_ERROR,
            message,
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
                    "Mock mode: STON.fi is not actively queried. STON.fi pool "
                    "preview responses are mock/offline only."
                ),
            }

        if not configured:
            return {
                "configured": False,
                "available": False,
                "message": (
                    "STON.fi provider is not configured: base URL is missing "
                    "or invalid. STON.fi DEX pool preview requests cannot be "
                    "attempted."
                ),
            }

        return {
            "configured": True,
            "available": True,
            "message": (
                "Real mode: STON.fi is configured. STON.fi pool preview "
                "endpoints can attempt live STON.fi DEX pool fetching. "
                "Coverage is limited to STON.fi DEX data, not all TON DeFi."
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
        """Fetch JSON from STON.fi and convert all provider errors safely."""
        url = self._url(path, query)
        if url is None:
            return self._not_configured()

        data = None
        headers = {
            "Accept": "application/json",
            "User-Agent": "ton-check/0.6.0",
        }
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
                f"STON.fi HTTP error: {exc.code} {exc.reason}."
            )
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return self._provider_error(f"STON.fi network error: {exc}.")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self._provider_error("STON.fi returned invalid JSON.")

        return ProviderResult.success(
            payload,
            source="real",
            message="STON.fi JSON response fetched.",
        )

    # -- Pools preview ---------------------------------------------------

    def get_pools_preview(self, limit: int = 10, dex_v2: bool = True) -> ProviderResult:
        """Fetch and normalize a small preview of STON.fi pools.

        This is not connected to the main dashboard analysis. In mock mode the
        method returns an explicitly offline response and performs no request.
        """
        if limit < 1:
            return self._provider_error("STON.fi preview limit must be at least 1.")

        if self.settings.is_mock:
            return ProviderResult.success(
                {
                    "pools": [],
                    "preview_count": 0,
                    "total_pools": 0,
                },
                source="mock",
                message="Mock mode: STON.fi is not actively queried.",
            )

        result = self.fetch_json("/v1/pools", query={"dex_v2": dex_v2})
        if not result.ok:
            return result

        try:
            pools = self.normalize_pools_response(result.data)
        except ValueError as exc:
            return self._provider_error(
                f"STON.fi response had an unexpected structure: {exc}."
            )

        preview = pools[:limit]
        return ProviderResult.success(
            {
                "pools": preview,
                "preview_count": len(preview),
                "total_pools": len(pools),
            },
            source="real",
            message=(
                "STON.fi pool preview fetched. Covers STON.fi DEX pools only, "
                "not all TON DeFi."
            ),
        )

    # -- Normalization ---------------------------------------------------

    @classmethod
    def normalize_pools_response(cls, payload: Any) -> list[dict]:
        if isinstance(payload, dict):
            raw_pools = payload.get("pool_list")
        elif isinstance(payload, list):
            raw_pools = payload
        else:
            raise ValueError("response must be an object or list")

        if not isinstance(raw_pools, list):
            raise ValueError("pool_list must be a list")

        normalized = []
        for index, raw_pool in enumerate(raw_pools):
            if not isinstance(raw_pool, dict):
                raise ValueError(f"pool {index} must be an object")
            normalized.append(cls.normalize_pool(raw_pool))
        return normalized

    @classmethod
    def normalize_pool(cls, raw_pool: dict) -> dict:
        address = cls._required_string(raw_pool, "address")
        return {
            "address": address,
            "token0_address": cls._optional_string(raw_pool.get("token0_address")),
            "token1_address": cls._optional_string(raw_pool.get("token1_address")),
            "reserve0": cls._optional_string(raw_pool.get("reserve0")),
            "reserve1": cls._optional_string(raw_pool.get("reserve1")),
            "token0_balance": cls._optional_string(raw_pool.get("token0_balance")),
            "token1_balance": cls._optional_string(raw_pool.get("token1_balance")),
            "lp_total_supply_usd": cls._optional_string(
                raw_pool.get("lp_total_supply_usd")
            ),
            "volume_24h_usd": cls._optional_string(raw_pool.get("volume_24h_usd")),
            "apy_1d": cls._optional_string(raw_pool.get("apy_1d")),
            "apy_7d": cls._optional_string(raw_pool.get("apy_7d")),
            "apy_30d": cls._optional_string(raw_pool.get("apy_30d")),
            "router_address": cls._optional_string(raw_pool.get("router_address")),
            "deprecated": raw_pool.get("deprecated") is True,
            "tags": cls._string_list(raw_pool.get("tags")),
            "source": "stonfi",
        }

    @classmethod
    def _required_string(cls, raw: dict, field_name: str) -> str:
        value = cls._optional_string(raw.get(field_name))
        if value is None:
            raise ValueError(f"pool is missing {field_name}")
        return value

    @staticmethod
    def _optional_string(value: Any) -> str | None:
        if value is None:
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result = []
        for item in value:
            cleaned = StonfiAdapter._optional_string(item)
            if cleaned is not None:
                result.append(cleaned)
        return result
