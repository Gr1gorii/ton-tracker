"""GeckoTerminal adapter.

Provides pool + token market data. Mode-aware:

* ``DATA_MODE=mock`` (default) -> returns bundled mock pool/token data.
* ``DATA_MODE=real`` -> queries the public GeckoTerminal v2 API
  (no API key required) and normalizes the response into the same shape as
  the mock data, so the rest of the backend is agnostic to the source.

All real network access is wrapped: any failure returns a clean
``ProviderResult`` error instead of raising, so the backend never crashes and
the frontend can surface a useful warning.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from typing import Optional

from config import (
    ERROR_PROVIDER_ERROR,
    ProviderResult,
    Settings,
    get_settings,
)
from services import mock_data

_HTTP_TIMEOUT = 10  # seconds


class GeckoTerminalAdapter:
    """Adapter for token/pool market data (mock or real GeckoTerminal)."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    # -- URL handling ----------------------------------------------------

    def parse_pool_url(self, pool_url: str) -> dict:
        """Extract network + pool address from a GeckoTerminal URL.

        Handles forms like:
          https://www.geckoterminal.com/ton/pools/<pool_address>
          https://api.geckoterminal.com/api/v2/networks/ton/pools/<addr>
        Falls back to a bare address if the URL is just an address string.
        """
        raw = (pool_url or "").strip()
        network: Optional[str] = None
        pool_address: Optional[str] = None

        match = re.search(
            r"/(?:networks/)?([a-z0-9-]+)/pools/([A-Za-z0-9_:-]+)", raw
        )
        if match:
            network = match.group(1)
            pool_address = match.group(2)
        elif raw and "/" not in raw and " " not in raw:
            # Treat a bare token as the pool address; network unknown.
            pool_address = raw

        return {"network": network, "pool_address": pool_address}

    def validate_network(self, network: Optional[str]) -> bool:
        """Only TON pools are supported."""
        return network == "ton"

    # -- Real fetch ------------------------------------------------------

    def fetch_pool_info(self, pool_address: str,
                        network: str = "ton") -> ProviderResult:
        """Fetch + normalize real pool/token data from GeckoTerminal.

        Returns a ProviderResult; on any network/parse error returns a clean
        failure rather than raising.
        """
        base = self.settings.geckoterminal_base_url.rstrip("/")
        url = (
            f"{base}/networks/{network}/pools/{pool_address}"
            "?include=base_token,quote_token,dex"
        )
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ton-check/0.2",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                f"GeckoTerminal returned HTTP {exc.code} for pool "
                f"{pool_address}.",
                source="real",
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                f"Could not reach GeckoTerminal: {exc}.",
                source="real",
            )
        except (ValueError, json.JSONDecodeError):
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                "GeckoTerminal returned an unparseable response.",
                source="real",
            )

        try:
            token_info, pool_info = self._normalize(payload, network,
                                                    pool_address)
        except (KeyError, TypeError, ValueError):
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                "GeckoTerminal response had an unexpected structure.",
                source="real",
            )

        return ProviderResult.success(
            {"token": token_info, "pool": pool_info},
            source="real",
            message="Real GeckoTerminal pool/token data.",
        )

    def get_token_price(self, token_address: str,
                        network: str = "ton") -> ProviderResult:
        """Fetch a provider-reported USD token price from GeckoTerminal."""
        if self.settings.is_mock:
            return ProviderResult.success(
                {"token_address": token_address, "price_usd": None},
                source="mock",
                message="Mock mode: GeckoTerminal is not actively queried.",
            )

        base = self.settings.geckoterminal_base_url.rstrip("/")
        url = f"{base}/networks/{network}/tokens/{token_address}"
        req = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "ton-check/0.2",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                f"GeckoTerminal returned HTTP {exc.code} for token "
                f"{token_address}.",
                source="real",
            )
        except (urllib.error.URLError, TimeoutError) as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                f"Could not reach GeckoTerminal: {exc}.",
                source="real",
            )
        except (ValueError, json.JSONDecodeError):
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                "GeckoTerminal returned an unparseable response.",
                source="real",
            )

        try:
            attrs = payload["data"]["attributes"]
            price = attrs.get("price_usd")
        except (KeyError, TypeError):
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                "GeckoTerminal token response had an unexpected structure.",
                source="real",
            )

        price_str = str(price).strip() if price not in (None, "") else None
        return ProviderResult.success(
            {"token_address": token_address, "price_usd": price_str},
            source="real",
            message="GeckoTerminal token price fetched.",
        )

    # -- Mode-aware orchestrator ----------------------------------------

    def get_pool_and_token(self, pool_url: str) -> ProviderResult:
        """Return {'token':..., 'pool':...} from mock or real source."""
        parsed = self.parse_pool_url(pool_url)

        if self.settings.is_mock:
            token = mock_data.get_token_info()
            pool = mock_data.get_pool_info()
            pool["requested_network"] = parsed["network"]
            pool["requested_pool_address"] = parsed["pool_address"]
            return ProviderResult.success(
                {"token": token, "pool": pool},
                source="mock",
                message="Mock pool/token data.",
            )

        # Real mode.
        network = parsed["network"]
        if not parsed["pool_address"]:
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                "Could not extract a pool address from the provided URL.",
                source="real",
            )
        if network and not self.validate_network(network):
            return ProviderResult.failure(
                ERROR_PROVIDER_ERROR,
                f"Unsupported network '{network}'. Only TON pools are "
                "supported.",
                source="real",
            )
        return self.fetch_pool_info(parsed["pool_address"], network or "ton")

    # -- Status ----------------------------------------------------------

    def status(self) -> dict:
        configured = bool(self.settings.geckoterminal_base_url)
        if self.settings.is_mock:
            return {
                "configured": configured,
                "available": True,
                "message": "Mock mode: serving bundled mock pool/token data.",
            }
        return {
            "configured": configured,
            "available": configured,
            "message": (
                "Real mode: GeckoTerminal public API is queried at analyze "
                "time."
                if configured
                else "GeckoTerminal base URL is not set."
            ),
        }

    # -- Normalization ---------------------------------------------------

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    def _normalize(self, payload: dict, network: str,
                   pool_address: str) -> tuple[dict, dict]:
        """Map a GeckoTerminal pool response to our mock-compatible shape."""
        data = payload["data"]
        attrs = data.get("attributes", {})
        included = payload.get("included", []) or []

        # Index included resources by id, and locate the base token + dex.
        by_id = {item.get("id"): item for item in included}
        rels = data.get("relationships", {}) or {}

        base_token_id = (
            rels.get("base_token", {}).get("data", {}) or {}
        ).get("id")
        dex_id = (rels.get("dex", {}).get("data", {}) or {}).get("id")

        base_token = by_id.get(base_token_id, {})
        bt_attrs = base_token.get("attributes", {}) if base_token else {}

        dex_name = dex_id or attrs.get("dex_id") or "unknown"
        if dex_id in by_id:
            dex_name = by_id[dex_id].get("attributes", {}).get("name", dex_id)

        volume = attrs.get("volume_usd", {}) or {}

        # Split a pool name like "GRAM / TON" into base/quote symbols.
        name = attrs.get("name", "") or ""
        base_sym, quote_sym = "?", "?"
        if "/" in name:
            parts = [p.strip() for p in name.split("/", 1)]
            base_sym, quote_sym = parts[0], parts[1]
        if bt_attrs.get("symbol"):
            base_sym = bt_attrs["symbol"]

        token_info = {
            "name": bt_attrs.get("name") or base_sym,
            "symbol": base_sym,
            "address": bt_attrs.get("address", ""),
            "decimals": bt_attrs.get("decimals", 9),
            "current_price_usd": self._to_float(
                attrs.get("base_token_price_usd")
            ),
            "market_cap_usd": self._to_float(attrs.get("market_cap_usd")),
            "fdv_usd": self._to_float(attrs.get("fdv_usd")),
        }

        pool_info = {
            "address": attrs.get("address", pool_address),
            "dex": dex_name,
            "base_token": base_sym,
            "quote_token": quote_sym,
            "liquidity_usd": self._to_float(attrs.get("reserve_in_usd")),
            "volume_24h_usd": self._to_float(volume.get("h24")),
            "created_at": attrs.get("pool_created_at", ""),
            "requested_network": network,
            "requested_pool_address": pool_address,
        }
        return token_info, pool_info
