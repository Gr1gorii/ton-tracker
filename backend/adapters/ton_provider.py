"""TON on-chain data provider adapter.

v0.2 scaffold. Mode-aware:

* ``DATA_MODE=mock`` -> returns data derived from the bundled mock wallets.
* ``DATA_MODE=real`` but ``TON_API_BASE_URL`` / ``TON_API_KEY`` missing ->
  returns a clean ``provider_not_configured`` error.
* ``DATA_MODE=real`` with config -> returns ``real_not_implemented`` for now.
  v0.2 deliberately does not build a full TON indexer; wallet-level analysis
  remains mocked.

``get_window_buyers`` keeps the v0.1 contract (returns aggregated mock wallet
records) because wallet-level aggregation is always mocked in v0.2. The new
granular methods follow the ProviderResult pattern for the real path.
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

# 1 TON = 1e9 nanotons.
_NANO = 1_000_000_000


class TonProviderAdapter:
    """Adapter for TON wallet + transfer data (mock or — later — real)."""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    # -- Configuration ---------------------------------------------------

    def is_configured(self) -> bool:
        """Real TON use requires both a base URL and an API key."""
        return bool(self.settings.ton_api_base_url and self.settings.ton_api_key)

    def _not_configured(self) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_PROVIDER_NOT_CONFIGURED,
            "TON provider is not configured. Wallet balances are unavailable.",
            source="real",
        )

    def _not_implemented(self) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_NOT_IMPLEMENTED,
            "Real TON provider integration is planned but not implemented in "
            "v0.2.",
            source="real",
        )

    def _guard_real(self) -> Optional[ProviderResult]:
        """Return the appropriate failure for real mode, or None if mock."""
        if self.settings.is_mock:
            return None
        if not self.is_configured():
            return self._not_configured()
        return self._not_implemented()

    # -- Normalization ---------------------------------------------------

    @staticmethod
    def normalize_balance(raw_balance) -> dict:
        """Normalize a raw account balance into TON units.

        Accepts a dict (TonAPI-style ``{"balance": <nanotons>}``) or a raw
        numeric value already in TON.
        """
        if isinstance(raw_balance, dict):
            nanotons = raw_balance.get("balance", 0) or 0
            try:
                ton = float(nanotons) / _NANO
            except (TypeError, ValueError):
                ton = 0.0
            return {
                "address": raw_balance.get("address"),
                "ton_balance": round(ton, 4),
            }
        try:
            return {"address": None, "ton_balance": round(float(raw_balance), 4)}
        except (TypeError, ValueError):
            return {"address": None, "ton_balance": 0.0}

    @staticmethod
    def normalize_transfer(raw_transfer: dict) -> dict:
        """Normalize a raw transfer/event into a canonical shape."""
        return {
            "from_address": raw_transfer.get("from_address")
            or raw_transfer.get("sender"),
            "to_address": raw_transfer.get("to_address")
            or raw_transfer.get("recipient"),
            "token": raw_transfer.get("token")
            or raw_transfer.get("symbol"),
            "amount": float(raw_transfer.get("amount", 0) or 0),
            "amount_usd": float(raw_transfer.get("amount_usd", 0) or 0),
            "timestamp": raw_transfer.get("timestamp"),
        }

    # -- Mock helpers ----------------------------------------------------

    @staticmethod
    def _mock_wallet(address: str) -> Optional[dict]:
        for w in mock_data.WALLETS:
            if w["address"] == address:
                return w
        return None

    # -- Public granular interface --------------------------------------

    def get_wallet_ton_balance(self, wallet_address: str) -> ProviderResult:
        guard = self._guard_real()
        if guard is not None:
            return guard
        w = self._mock_wallet(wallet_address)
        balance = float(w["ton_balance"]) if w else 0.0
        return ProviderResult.success(
            self.normalize_balance(balance), source="mock",
            message="Mock TON balance.",
        )

    def get_wallet_jetton_balances(self, wallet_address: str) -> ProviderResult:
        guard = self._guard_real()
        if guard is not None:
            return guard
        w = self._mock_wallet(wallet_address)
        jettons: list[dict] = []
        if w:
            current_price = mock_data.TOKEN_INFO["current_price_usd"]
            if w["current_holding"] > 0:
                jettons.append(
                    {
                        "symbol": mock_data.TOKEN_INFO["symbol"],
                        "amount": w["current_holding"],
                        "value_usd": round(
                            w["current_holding"] * current_price, 2
                        ),
                    }
                )
            for pos in w["other_positions"]:
                jettons.append(
                    {
                        "symbol": pos["symbol"],
                        "amount": None,
                        "value_usd": pos["value_usd"],
                    }
                )
        return ProviderResult.success(
            jettons, source="mock", message="Mock jetton balances."
        )

    def get_wallet_transactions(self, wallet_address: str, start: datetime,
                                end: datetime) -> ProviderResult:
        guard = self._guard_real()
        if guard is not None:
            return guard
        # No transaction-level detail exists in the mock fixtures.
        return ProviderResult.success(
            [], source="mock",
            message="Mock mode: transaction-level detail is not available.",
        )

    def get_token_transfers(self, token_address: str, start: datetime,
                            end: datetime) -> ProviderResult:
        guard = self._guard_real()
        if guard is not None:
            return guard
        return ProviderResult.success(
            [], source="mock",
            message="Mock mode: transfer-level detail is not available.",
        )

    # -- Backward-compatible aggregate buyers ---------------------------

    def get_window_buyers(self, pool_url: str, start: datetime,
                          end: datetime) -> list[dict]:
        """Return aggregated buyer wallet records.

        Always mock in v0.2 — wallet-level aggregation is not yet implemented
        for real providers. Kept as a plain list to preserve the v0.1 contract
        used by the analysis layer.
        """
        return mock_data.get_raw_wallets()

    # -- Status ----------------------------------------------------------

    def status(self) -> dict:
        configured = self.is_configured()
        if self.settings.is_mock:
            return {
                "configured": configured,
                "available": True,
                "message": "Mock mode: serving mock wallet balances.",
            }
        return {
            "configured": configured,
            "available": False,
            "message": (
                "Real mode: TON provider configured, but real wallet data is "
                "not implemented in v0.2."
                if configured
                else "TON provider is not configured. Wallet balances are "
                "unavailable."
            ),
        }
