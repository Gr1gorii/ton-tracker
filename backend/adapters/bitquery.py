"""Bitquery adapter (historical DEX trades).

v0.2 scaffold. Mode-aware:

* ``DATA_MODE=mock`` -> synthesizes mock trades from the bundled mock wallets.
* ``DATA_MODE=real`` but no ``BITQUERY_API_KEY`` -> returns a clean
  ``provider_not_configured`` error.
* ``DATA_MODE=real`` with a key -> returns ``real_not_implemented`` for now.
  This is intentional: v0.2 does not build a full DEX-trade indexer, and we do
  not claim real historical trade analysis is complete.

The interface (method signatures + normalized trade shape) is the contract a
future real implementation will satisfy without touching callers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from config import (
    ERROR_NOT_IMPLEMENTED,
    ERROR_PROVIDER_NOT_CONFIGURED,
    ProviderResult,
    Settings,
    get_settings,
)
from services import mock_data


class BitqueryAdapter:
    """Adapter for historical DEX trades (mock or — later — real Bitquery)."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    # -- Configuration ---------------------------------------------------

    def is_configured(self) -> bool:
        """Real Bitquery use requires an API key."""
        return bool(self.settings.bitquery_api_key)

    def _not_configured(self) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_PROVIDER_NOT_CONFIGURED,
            "Bitquery API key is missing. Historical DEX trades are "
            "unavailable.",
            source="real",
        )

    def _not_implemented(self) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_NOT_IMPLEMENTED,
            "Real Bitquery integration is planned but not implemented in "
            "v0.2.",
            source="real",
        )

    # -- Normalization ---------------------------------------------------

    @staticmethod
    def normalize_trade(raw_trade: dict) -> dict:
        """Map a raw trade record into the canonical normalized shape.

        Accepts either an already-normalized mock trade or a loosely-shaped
        raw provider record, filling sensible defaults for missing keys.
        """
        return {
            "wallet_address": raw_trade.get("wallet_address")
            or raw_trade.get("maker")
            or raw_trade.get("buyer"),
            "token_address": raw_trade.get("token_address")
            or raw_trade.get("base_address"),
            "side": raw_trade.get("side", "buy"),
            "base_amount": float(raw_trade.get("base_amount", 0) or 0),
            "amount_usd": float(raw_trade.get("amount_usd", 0) or 0),
            "price_usd": float(raw_trade.get("price_usd", 0) or 0),
            "timestamp": raw_trade.get("timestamp"),
        }

    # -- Mock trade synthesis -------------------------------------------

    def _mock_trades(self, token_address: str,
                     wallet_address: Optional[str] = None) -> list[dict]:
        """Build normalized mock trades from the bundled mock wallets."""
        trades: list[dict] = []
        for w in mock_data.WALLETS:
            if wallet_address and w["address"] != wallet_address:
                continue

            if w["total_bought_qty"] > 0:
                qty = w["total_bought_qty"]
                usd = w["total_bought_usd"]
                trades.append(
                    self.normalize_trade(
                        {
                            "wallet_address": w["address"],
                            "token_address": token_address,
                            "side": "buy",
                            "base_amount": qty,
                            "amount_usd": usd,
                            "price_usd": (usd / qty) if qty else 0,
                            "timestamp": None,
                        }
                    )
                )
            if w["total_sold_qty"] > 0:
                qty = w["total_sold_qty"]
                usd = w["total_sold_usd"]
                trades.append(
                    self.normalize_trade(
                        {
                            "wallet_address": w["address"],
                            "token_address": token_address,
                            "side": "sell",
                            "base_amount": qty,
                            "amount_usd": usd,
                            "price_usd": (usd / qty) if qty else 0,
                            "timestamp": None,
                        }
                    )
                )
        return trades

    # -- Public interface ------------------------------------------------

    def get_token_trades(self, token_address: str, start: datetime,
                         end: datetime) -> ProviderResult:
        if self.settings.is_mock:
            return ProviderResult.success(
                self._mock_trades(token_address),
                source="mock",
                message="Mock DEX trades.",
            )
        if not self.is_configured():
            return self._not_configured()
        return self._not_implemented()

    def get_wallet_token_trades(self, wallet_address: str, token_address: str,
                                start: datetime,
                                end: datetime) -> ProviderResult:
        if self.settings.is_mock:
            return ProviderResult.success(
                self._mock_trades(token_address, wallet_address),
                source="mock",
                message="Mock DEX trades for wallet.",
            )
        if not self.is_configured():
            return self._not_configured()
        return self._not_implemented()

    # -- Status ----------------------------------------------------------

    def status(self) -> dict:
        configured = self.is_configured()
        if self.settings.is_mock:
            return {
                "configured": configured,
                "available": True,
                "message": "Mock mode: synthesizing mock DEX trades.",
            }
        return {
            "configured": configured,
            "available": False,
            "message": (
                "Real mode: Bitquery key present, but real trade fetching is "
                "not implemented in v0.2."
                if configured
                else "Bitquery API key is missing. Historical DEX trades are "
                "unavailable."
            ),
        }
