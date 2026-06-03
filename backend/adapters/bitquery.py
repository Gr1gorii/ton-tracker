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
from decimal import Decimal, InvalidOperation
import json
from typing import Any, Optional
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
        Bitquery V2 exposes TON under the uppercase ``Ton`` root with the
        ``DEXTrades`` cube; the older lowercase ``ton/dexTrades`` shape is not
        valid against the active RootQuery.
        """
        if not token_address or not str(token_address).strip():
            raise ValueError("token_address is required")

        start_value = self._format_query_time(start, "start")
        end_value = self._format_query_time(end, "end")

        query = """
query TonTokenDexTrades($token: String!, $start: DateTime!, $end: DateTime!) {
  Ton(network: ton) {
    DEXTrades(
      orderBy: {ascending: Block_Time}
      where: {
        Block: {Time: {since: $start, till: $end}}
        any: [
          {
            Trade: {
              Buy: {
                Currency: {
                  SmartContract: {Address: {is: $token}}
                }
              }
            }
          }
          {
            Trade: {
              Sell: {
                Currency: {
                  SmartContract: {Address: {is: $token}}
                }
              }
            }
          }
        ]
      }
    ) {
      Block {
        Time
      }
      Transaction {
        Hash
      }
      Trade {
        Buy {
          Amount
          AmountInUSD
          Buyer {
            Address
          }
          Currency {
            SmartContract {
              Address
            }
          }
        }
        Sell {
          Amount
          AmountInUSD
          Seller {
            Address
          }
          Currency {
            SmartContract {
              Address
            }
          }
        }
        Dex {
          ProtocolName
          SmartContract {
            Address
          }
        }
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
    def _normalize_legacy_trade(raw_trade: dict) -> dict:
        """Map old mock/provider rows into the v0.2 canonical shape."""
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

    @staticmethod
    def _string_value(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, dict):
            for key in ("address", "name", "fullName", "value"):
                nested = BitqueryAdapter._string_value(value.get(key))
                if nested is not None:
                    return nested
            return None
        cleaned = str(value).strip()
        return cleaned or None

    @staticmethod
    def _first_value(raw_trade: dict, *paths: tuple[str, ...]) -> Any:
        for path in paths:
            current: Any = raw_trade
            for key in path:
                if not isinstance(current, dict) or key not in current:
                    current = None
                    break
                current = current[key]
            if current is not None:
                return current
        return None

    @classmethod
    def _required_string(cls, raw_trade: dict, field_name: str,
                         *paths: tuple[str, ...]) -> str:
        value = cls._string_value(cls._first_value(raw_trade, *paths))
        if value is None:
            raise ValueError(f"Bitquery trade is missing {field_name}")
        return value

    @staticmethod
    def _decimal_value(value: Any, field_name: str,
                       allow_zero: bool = False) -> Decimal:
        text = BitqueryAdapter._string_value(value)
        if text is None:
            raise ValueError(f"Bitquery trade is missing {field_name}")
        try:
            parsed = Decimal(text)
        except (InvalidOperation, ValueError):
            raise ValueError(
                f"Bitquery trade has invalid {field_name}"
            ) from None
        if not parsed.is_finite():
            raise ValueError(f"Bitquery trade has invalid {field_name}")
        if parsed < 0 or (parsed == 0 and not allow_zero):
            raise ValueError(f"Bitquery trade has invalid {field_name}")
        return parsed

    @staticmethod
    def _optional_decimal_value(value: Any, field_name: str) -> Decimal | None:
        if BitqueryAdapter._string_value(value) is None:
            return None
        return BitqueryAdapter._decimal_value(value, field_name,
                                              allow_zero=True)

    @staticmethod
    def _decimal_string(value: Decimal) -> str:
        return str(value)

    @classmethod
    def normalize_trade(cls, raw_trade: dict,
                        target_token_address: str | None = None) -> dict:
        """Map a raw trade record into the canonical normalized shape.

        Without ``target_token_address``, this preserves the legacy mock-trade
        shape used by the existing provider scaffolding. With a target token,
        it maps Bitquery DEX trades into the imported-trade shape.
        """
        if target_token_address is None:
            return cls._normalize_legacy_trade(raw_trade)

        target = cls._string_value(target_token_address)
        if target is None:
            raise ValueError("target_token_address is required")

        buy_token = cls._required_string(
            raw_trade,
            "buy token address",
            ("Trade", "Buy", "Currency", "SmartContract", "Address"),
            ("buyCurrency", "address"),
            ("buy_currency", "address"),
            ("buy_token_address",),
            ("buyToken", "address"),
        )
        sell_token = cls._required_string(
            raw_trade,
            "sell token address",
            ("Trade", "Sell", "Currency", "SmartContract", "Address"),
            ("sellCurrency", "address"),
            ("sell_currency", "address"),
            ("sell_token_address",),
            ("sellToken", "address"),
        )

        if buy_token == target:
            side = "buy"
            wallet = cls._required_string(
                raw_trade,
                "buyer wallet",
                ("Trade", "Buy", "Buyer", "Address"),
                ("buyer", "address"),
                ("buyer_address",),
                ("buyer",),
            )
            token_amount = cls._decimal_value(
                cls._first_value(
                    raw_trade,
                    ("Trade", "Buy", "Amount"),
                    ("buyAmount",),
                    ("buy_amount",),
                ),
                "buy amount",
            )
            usd_paths = (
                ("Trade", "Buy", "AmountInUSD"),
                ("Trade", "AmountInUSD"),
                ("tradeAmount",),
                ("tradeAmount(in: USD)",),
                ("amount_usd",),
                ("usd_amount",),
            )
            price_paths = (
                ("Trade", "Buy", "PriceInUSD"),
                ("price_usd",),
                ("priceUsd",),
                ("priceUSD",),
            )
        elif sell_token == target:
            side = "sell"
            wallet = cls._required_string(
                raw_trade,
                "seller wallet",
                ("Trade", "Sell", "Seller", "Address"),
                ("seller", "address"),
                ("seller_address",),
                ("seller",),
            )
            token_amount = cls._decimal_value(
                cls._first_value(
                    raw_trade,
                    ("Trade", "Sell", "Amount"),
                    ("sellAmount",),
                    ("sell_amount",),
                ),
                "sell amount",
            )
            usd_paths = (
                ("Trade", "Sell", "AmountInUSD"),
                ("Trade", "AmountInUSD"),
                ("tradeAmount",),
                ("tradeAmount(in: USD)",),
                ("amount_usd",),
                ("usd_amount",),
            )
            price_paths = (
                ("Trade", "Sell", "PriceInUSD"),
                ("price_usd",),
                ("priceUsd",),
                ("priceUSD",),
            )
        else:
            raise ValueError(
                "Target token is not present in Bitquery trade buy/sell side"
            )

        usd_amount = cls._decimal_value(
            cls._first_value(raw_trade, *usd_paths),
            "USD amount",
            allow_zero=True,
        )
        price_usd = cls._optional_decimal_value(
            cls._first_value(raw_trade, *price_paths),
            "price USD",
        )
        if price_usd is None:
            price_usd = usd_amount / token_amount

        return {
            "tx_hash": cls._required_string(
                raw_trade,
                "transaction hash",
                ("Transaction", "Hash"),
                ("transaction", "hash"),
                ("tx_hash",),
                ("transaction_hash",),
            ),
            "block_time": cls._required_string(
                raw_trade,
                "block time",
                ("Block", "Time"),
                ("block", "timestamp", "time"),
                ("block_time",),
                ("timestamp",),
            ),
            "wallet": wallet,
            "side": side,
            "token_amount": cls._decimal_string(token_amount),
            "usd_amount": cls._decimal_string(usd_amount),
            "price_usd": cls._decimal_string(price_usd),
            "pool_address": cls._string_value(
                cls._first_value(
                    raw_trade,
                    ("Trade", "Dex", "SmartContract", "Address"),
                    ("pool", "address"),
                    ("pool_address",),
                )
            ),
            "dex": cls._string_value(
                cls._first_value(
                    raw_trade,
                    ("Trade", "Dex", "ProtocolName"),
                    ("dex",),
                    ("protocol",),
                )
            ),
            "source": "bitquery",
        }

    @classmethod
    def normalize_token_trades_response(
        cls,
        payload: dict | list | None,
        target_token_address: str,
    ) -> list[dict]:
        """Normalize a Bitquery token-trades payload into trade rows."""
        if payload is None:
            return []
        if isinstance(payload, list):
            trades = payload
        elif isinstance(payload, dict):
            trades = cls._first_value(
                payload,
                ("Ton", "DEXTrades"),
                ("ton", "dexTrades"),
                ("DEXTrades",),
                ("dexTrades",),
                ("trades",),
            )
            if trades is None:
                return []
        else:
            raise ValueError("Bitquery trades response must be a dict or list")

        if not isinstance(trades, list):
            raise ValueError("Bitquery DEXTrades response must be a list")

        normalized = []
        for index, raw_trade in enumerate(trades):
            if not isinstance(raw_trade, dict):
                raise ValueError(
                    f"Invalid Bitquery trade at index {index}: expected dict"
                )
            try:
                normalized.append(cls.normalize_trade(raw_trade,
                                                      target_token_address))
            except ValueError as exc:
                raise ValueError(
                    f"Invalid Bitquery trade at index {index}: {exc}"
                ) from exc
        return normalized

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

        try:
            request = self.build_token_trades_query(token_address, start, end)
        except ValueError as exc:
            return self._provider_error(f"Bitquery query error: {exc}.")

        result = self.execute_graphql(request["query"], request["variables"])
        if not result.ok:
            return result

        try:
            trades = self.normalize_token_trades_response(
                result.data,
                token_address,
            )
        except ValueError as exc:
            return self._provider_error(
                f"Bitquery normalization error: {exc}."
            )

        return ProviderResult.success(
            trades,
            source="real",
            message="Bitquery DEX trades fetched and normalized.",
        )

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
        if self.settings.is_mock:
            return {
                "configured": self.is_configured(),
                "available": True,
                "message": "Mock mode: synthesizing mock DEX trades.",
            }

        if not self.is_configured():
            return {
                "configured": False,
                "available": False,
                "message": (
                    "Bitquery API key is missing. Historical DEX trades are "
                    "unavailable."
                ),
            }

        if not self._validated_api_url():
            return {
                "configured": False,
                "available": False,
                "message": (
                    "Bitquery API URL is missing or invalid. Historical DEX "
                    "trades are unavailable."
                ),
            }

        return {
            "configured": True,
            "available": True,
            "message": (
                "Real mode: Bitquery is configured. Token trade "
                "preview/analyze endpoints can attempt live DEX trade "
                "fetching. Live availability is checked when those endpoints "
                "are called."
            ),
        }
