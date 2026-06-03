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
import json
from typing import Optional
import urllib.error
import urllib.parse
import urllib.request

from config import (
    ERROR_NOT_IMPLEMENTED,
    ERROR_PROVIDER_ERROR,
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

    def _provider_error(self, message: str) -> ProviderResult:
        return ProviderResult.failure(ERROR_PROVIDER_ERROR, message,
                                      source="real")

    # -- Query building --------------------------------------------------

    @staticmethod
    def _format_query_time(value: datetime | str, field_name: str) -> str:
        if value is None:
            raise ValueError(f"{field_name} is required")
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value)

    def build_token_trades_query(self, token_address: str, start: datetime | str,
                                 end: datetime | str) -> dict:
        """Build the Bitquery GraphQL request for TON DEX token trades.

        This intentionally only prepares the future real-provider request. It
        does not perform any network calls or require a configured API key.
        """
        if not token_address or not str(token_address).strip():
            raise ValueError("token_address is required")

        start_value = self._format_query_time(start, "start")
        end_value = self._format_query_time(end, "end")

        query = """
query TonTokenDexTrades($token: String!, $start: DateTime!, $end: DateTime!) {
  ton(network: ton) {
    dexTrades(
      options: {asc: "block.timestamp.time"}
      date: {since: $start, till: $end}
      any: [
        {buyCurrency: {address: {is: $token}}},
        {sellCurrency: {address: {is: $token}}}
      ]
    ) {
      transaction {
        hash
      }
      block {
        timestamp {
          time
        }
      }
      buyer {
        address
      }
      seller {
        address
      }
      buyCurrency {
        address
      }
      sellCurrency {
        address
      }
      buyAmount
      sellAmount
      tradeAmount(in: USD)
      protocol
      pool {
        address
      }
    }
  }
}
""".strip()

        return {
            "query": query,
            "variables": {
                "token": token_address,
                "start": start_value,
                "end": end_value,
            },
        }

    # -- Request client --------------------------------------------------

    def _validated_api_url(self) -> str | None:
        api_url = (self.settings.bitquery_api_url or "").strip()
        parsed = urllib.parse.urlparse(api_url)
        if not api_url or parsed.scheme not in ("http", "https") or not parsed.netloc:
            return None
        return api_url

    def execute_graphql(self, query: str, variables: dict) -> ProviderResult:
        """Execute a Bitquery GraphQL request in real mode.

        Mock mode never sends a request. Real trade-fetching methods still do
        not call this method until the schema is finalized.
        """
        if self.settings.is_mock:
            return ProviderResult.success(
                {"query": query, "variables": variables},
                source="mock",
                message="Mock mode: Bitquery request not sent.",
            )
        if not self.is_configured():
            return self._not_configured()

        api_url = self._validated_api_url()
        if not api_url:
            return self._provider_error(
                "Bitquery API URL is missing or invalid."
            )

        body = json.dumps({"query": query, "variables": variables}).encode(
            "utf-8"
        )
        request = urllib.request.Request(
            api_url,
            data=body,
            headers={
                "Authorization": f"Bearer {self.settings.bitquery_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=20) as response:
                raw_body = response.read().decode("utf-8")
            payload = json.loads(raw_body)
        except urllib.error.HTTPError as exc:
            return self._provider_error(
                f"Bitquery HTTP error: {exc.code} {exc.reason}."
            )
        except urllib.error.URLError as exc:
            return self._provider_error(
                f"Bitquery network error: {exc.reason}."
            )
        except OSError as exc:
            return self._provider_error(f"Bitquery network error: {exc}.")
        except json.JSONDecodeError:
            return self._provider_error("Bitquery returned invalid JSON.")

        errors = payload.get("errors") if isinstance(payload, dict) else None
        if errors:
            return self._provider_error(
                f"Bitquery GraphQL error: {errors}."
            )
        if not isinstance(payload, dict) or "data" not in payload:
            return self._provider_error(
                "Bitquery response is missing data."
            )

        return ProviderResult.success(
            payload["data"],
            source="real",
            message="Bitquery GraphQL request succeeded.",
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
