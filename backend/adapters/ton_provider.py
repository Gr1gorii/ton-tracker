"""TON on-chain data provider adapter.

v0.1: returns mock buyer wallets with aggregate trade data. Later this will be
backed by a real TON indexer (TonAPI / Toncenter / Bitquery), normalizing
trade events into the same aggregate shape returned here so that
``services.analysis`` needs no changes.

Real implementation notes (for later):
  * Resolve the pool's jetton + LP contracts.
  * Page through swap/transfer events within [start, end].
  * Aggregate per-wallet bought/sold quantities and USD using price at trade
    time, fetch current holdings + TON balance, and normalize to the dicts
    documented in ``services.mock_data``.
"""

from __future__ import annotations

from datetime import datetime

from services import mock_data


class TonProviderAdapter:
    """Adapter for TON wallet + trade data. Currently mock-backed."""

    def __init__(self, use_mock: bool = True) -> None:
        self.use_mock = use_mock

    def get_window_buyers(
        self,
        pool_url: str,
        start: datetime,
        end: datetime,
    ) -> list[dict]:
        """Return raw aggregate trade records for wallets active in the window.

        In v0.1 the window is not actually used to filter mock wallets; it is
        accepted to lock in the real-implementation signature.
        """
        if not self.use_mock:
            raise NotImplementedError(
                "Real TON indexer integration is not part of v0.1."
            )
        return mock_data.get_raw_wallets()

    def get_ton_balance(self, address: str) -> float:
        """Placeholder for fetching a single wallet's TON balance."""
        if not self.use_mock:
            raise NotImplementedError(
                "Real TON balance lookup is not part of v0.1."
            )
        for w in mock_data.WALLETS:
            if w["address"] == address:
                return float(w["ton_balance"])
        return 0.0
