"""GeckoTerminal adapter.

v0.1: returns mock token/pool metadata. The public method signatures are the
contract the rest of the backend depends on; a future version will implement
real HTTP calls to the GeckoTerminal API here without touching callers.

Real implementation notes (for later):
  * Parse the pool address + network from ``pool_url``
    (e.g. https://www.geckoterminal.com/ton/pools/<pool_address>).
  * GET /api/v2/networks/ton/pools/{address} for pool + base token info.
  * Respect rate limits / add caching.
"""

from __future__ import annotations

import re

from services import mock_data


class GeckoTerminalAdapter:
    """Adapter for token/pool market data. Currently mock-backed."""

    def __init__(self, use_mock: bool = True) -> None:
        self.use_mock = use_mock

    def parse_pool_url(self, pool_url: str) -> dict:
        """Best-effort extraction of network + pool address from a URL.

        Returns mock-friendly defaults when the URL does not match the
        expected GeckoTerminal pattern, so v0.1 never hard-fails on input.
        """
        network = "ton"
        pool_address = None
        match = re.search(r"/([a-z0-9-]+)/pools/([A-Za-z0-9_:-]+)", pool_url or "")
        if match:
            network, pool_address = match.group(1), match.group(2)
        return {"network": network, "pool_address": pool_address}

    def get_token_info(self, pool_url: str) -> dict:
        if not self.use_mock:
            raise NotImplementedError(
                "Real GeckoTerminal integration is not part of v0.1."
            )
        return mock_data.get_token_info()

    def get_pool_info(self, pool_url: str) -> dict:
        if not self.use_mock:
            raise NotImplementedError(
                "Real GeckoTerminal integration is not part of v0.1."
            )
        info = mock_data.get_pool_info()
        parsed = self.parse_pool_url(pool_url)
        # Surface what we parsed from the URL alongside the mock pool data.
        info["requested_network"] = parsed["network"]
        info["requested_pool_address"] = parsed["pool_address"]
        return info
