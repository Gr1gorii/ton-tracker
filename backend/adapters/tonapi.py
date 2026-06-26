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
                "be attempted in public mode, but rate limits may apply."
            )

        return {
            "configured": True,
            "available": True,
            "message": (
                "Real mode: TonAPI is configured. Account jetton preview "
                "endpoints can attempt live TonAPI requests. "
                f"{auth_note} Scope is account native TON balance and jetton "
                "previews only, not full wallet intelligence."
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

    # -- Account balance preview ----------------------------------------

    def get_account_balance_preview(
        self,
        account_address: str,
    ) -> ProviderResult:
        """Fetch and normalize TonAPI account native TON balance."""
        account = self._optional_string(account_address)
        if account is None:
            return self._provider_error("TonAPI account address is required.")

        if self.settings.is_mock:
            return ProviderResult.success(
                {
                    "wallet_address": account,
                    "balance": None,
                },
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        encoded_account = urllib.parse.quote(account, safe="")
        result = self.fetch_json(f"/v2/accounts/{encoded_account}")
        if not result.ok:
            return result

        try:
            balance = self.normalize_account_balance_response(
                result.data,
                account,
            )
        except ValueError as exc:
            return self._provider_error(
                f"TonAPI response had an unexpected structure: {exc}."
            )

        return ProviderResult.success(
            {
                "wallet_address": account,
                "balance": balance,
            },
            source="real",
            message=(
                "TonAPI account native TON balance fetched. This is an "
                "account-level balance snapshot only and is not transaction "
                "history or full wallet intelligence."
            ),
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

    # -- Transactions preview -------------------------------------------

    def get_account_transactions_preview(
        self,
        account_address: str,
        limit: int = 10,
        before_lt: Optional[int] = None,
    ) -> ProviderResult:
        """Fetch and normalize a TonAPI account transaction-history preview.

        This is an ordered account-level activity timeline only. It is not DEX
        swap reconstruction, transfer-level attribution, PnL, or ownership
        proof.
        """
        account = self._optional_string(account_address)
        if account is None:
            return self._provider_error("TonAPI account address is required.")
        if limit < 1:
            return self._provider_error(
                "TonAPI transactions preview limit must be at least 1."
            )

        if self.settings.is_mock:
            return ProviderResult.success(
                {
                    "wallet_address": account,
                    "transactions": [],
                    "preview_count": 0,
                    "total_transactions": 0,
                },
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        encoded_account = urllib.parse.quote(account, safe="")
        result = self.fetch_json(
            f"/v2/blockchain/accounts/{encoded_account}/transactions",
            query={"limit": limit, "before_lt": before_lt},
        )
        if not result.ok:
            return result

        try:
            transactions = self.normalize_account_transactions_response(
                result.data,
                account,
            )
        except ValueError as exc:
            return self._provider_error(
                f"TonAPI response had an unexpected structure: {exc}."
            )

        preview = transactions[:limit]
        return ProviderResult.success(
            {
                "wallet_address": account,
                "transactions": preview,
                "preview_count": len(preview),
                "total_transactions": len(transactions),
            },
            source="real",
            message=(
                "TonAPI account transaction history fetched. This is an "
                "ordered account-level activity timeline only and is not DEX "
                "swap reconstruction, PnL, or ownership proof."
            ),
        )

    # -- Transfers preview (events) -------------------------------------

    def get_account_events_preview(
        self,
        account_address: str,
        limit: int = 10,
    ) -> ProviderResult:
        """Fetch and normalize TON/jetton transfers from TonAPI account events.

        Only ``TonTransfer`` and ``JettonTransfer`` actions are represented as
        transfers. Other action types (swaps, NFT, contract calls) are not
        transfers. Transfer direction is best-effort from the event addresses.
        """
        account = self._optional_string(account_address)
        if account is None:
            return self._provider_error("TonAPI account address is required.")
        if limit < 1:
            return self._provider_error(
                "TonAPI events preview limit must be at least 1."
            )

        if self.settings.is_mock:
            return ProviderResult.success(
                {
                    "wallet_address": account,
                    "transfers": [],
                    "preview_count": 0,
                    "total_transfers": 0,
                    "total_events": 0,
                },
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        encoded_account = urllib.parse.quote(account, safe="")
        result = self.fetch_json(
            f"/v2/accounts/{encoded_account}/events",
            query={"limit": limit},
        )
        if not result.ok:
            return result

        try:
            transfers = self.normalize_account_events_response(
                result.data,
                account,
            )
        except ValueError as exc:
            return self._provider_error(
                f"TonAPI response had an unexpected structure: {exc}."
            )

        events = result.data.get("events") if isinstance(result.data, dict) else None
        total_events = len(events) if isinstance(events, list) else len(transfers)
        return ProviderResult.success(
            {
                "wallet_address": account,
                "transfers": transfers,
                "preview_count": len(transfers),
                "total_transfers": len(transfers),
                "total_events": total_events,
            },
            source="real",
            message=(
                "TonAPI account transfer history fetched from events. Only TON "
                "and jetton transfer actions are represented and direction is "
                "best-effort; this is not DEX swap reconstruction, PnL, or "
                "ownership proof."
            ),
        )

    # -- Swaps preview (events) -----------------------------------------

    def get_account_swaps_preview(
        self,
        account_address: str,
        limit: int = 10,
    ) -> ProviderResult:
        """Fetch and normalize DEX swaps from TonAPI account events.

        Only ``JettonSwap`` actions are represented as swaps. USD valuation is
        not computed. This is not PnL or ownership proof.
        """
        account = self._optional_string(account_address)
        if account is None:
            return self._provider_error("TonAPI account address is required.")
        if limit < 1:
            return self._provider_error(
                "TonAPI swaps preview limit must be at least 1."
            )

        if self.settings.is_mock:
            return ProviderResult.success(
                {
                    "wallet_address": account,
                    "swaps": [],
                    "preview_count": 0,
                    "total_swaps": 0,
                    "total_events": 0,
                },
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        encoded_account = urllib.parse.quote(account, safe="")
        result = self.fetch_json(
            f"/v2/accounts/{encoded_account}/events",
            query={"limit": limit},
        )
        if not result.ok:
            return result

        try:
            swaps = self.normalize_account_swaps_response(result.data, account)
        except ValueError as exc:
            return self._provider_error(
                f"TonAPI response had an unexpected structure: {exc}."
            )

        events = result.data.get("events") if isinstance(result.data, dict) else None
        total_events = len(events) if isinstance(events, list) else len(swaps)
        return ProviderResult.success(
            {
                "wallet_address": account,
                "swaps": swaps,
                "preview_count": len(swaps),
                "total_swaps": len(swaps),
                "total_events": total_events,
            },
            source="real",
            message=(
                "TonAPI account DEX swaps fetched from events. Only JettonSwap "
                "actions are represented and USD valuation is not computed; "
                "this is not PnL or ownership proof."
            ),
        )

    # -- Rates (prices) preview -----------------------------------------

    def get_rates_preview(
        self,
        tokens: list[str],
        currency: str = "usd",
    ) -> ProviderResult:
        """Fetch provider-reported USD rates for tokens from TonAPI.

        ``tokens`` accepts ``"ton"`` and/or jetton master addresses. Prices are
        provider-reported and may be stale; this is not PnL.
        """
        cleaned = [
            token
            for token in (self._optional_string(item) for item in tokens)
            if token
        ]
        if not cleaned:
            return self._provider_error(
                "TonAPI rates require at least one token."
            )

        if self.settings.is_mock:
            return ProviderResult.success(
                {"rates": {}, "currency": currency, "source": "tonapi"},
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        result = self.fetch_json(
            "/v2/rates",
            query={"tokens": ",".join(cleaned), "currencies": currency},
        )
        if not result.ok:
            return result

        try:
            rates = self.normalize_rates_response(result.data, currency)
        except ValueError as exc:
            return self._provider_error(
                f"TonAPI response had an unexpected structure: {exc}."
            )

        return ProviderResult.success(
            {"rates": rates, "currency": currency, "source": "tonapi"},
            source="real",
            message=(
                "TonAPI rates fetched. Provider-reported prices may be stale "
                "and are not PnL."
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
    def normalize_account_balance_response(
        cls,
        payload: Any,
        wallet_address: str,
    ) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")

        nested_account = payload.get("account")
        if not isinstance(nested_account, dict):
            nested_account = {}
        raw_balance = payload.get("balance", nested_account.get("balance"))
        if raw_balance is None:
            raise ValueError("account balance is missing")

        return {
            "wallet_address": wallet_address,
            "asset": "TON",
            "balance": cls._optional_string(raw_balance),
            "decimals": 9,
            "account_status": cls._optional_string(
                payload.get("status", nested_account.get("status"))
            ),
            "is_scam": payload.get("is_scam", nested_account.get("is_scam")),
            "source": "tonapi",
        }

    @classmethod
    def normalize_account_transactions_response(
        cls,
        payload: Any,
        wallet_address: str,
    ) -> list[dict]:
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")

        transactions = payload.get("transactions")
        if not isinstance(transactions, list):
            raise ValueError("transactions must be a list")

        normalized = []
        for index, raw_tx in enumerate(transactions):
            if not isinstance(raw_tx, dict):
                raise ValueError(f"transaction {index} must be an object")
            normalized.append(cls.normalize_transaction(raw_tx, wallet_address))
        return normalized

    @classmethod
    def normalize_transaction(
        cls,
        raw_tx: dict,
        wallet_address: str,
    ) -> dict:
        tx_hash = cls._optional_string(raw_tx.get("hash"))
        if tx_hash is None:
            raise ValueError("transaction is missing a hash")

        success = raw_tx.get("success")
        return {
            "wallet_address": wallet_address,
            "tx_hash": tx_hash,
            "logical_time": cls._optional_string(raw_tx.get("lt")),
            "utime": cls._optional_int(raw_tx.get("utime")),
            "total_fees": cls._optional_string(raw_tx.get("total_fees")),
            "success": success if isinstance(success, bool) else None,
            "transaction_type": cls._optional_string(
                raw_tx.get("transaction_type")
            ),
            "orig_status": cls._optional_string(raw_tx.get("orig_status")),
            "end_status": cls._optional_string(raw_tx.get("end_status")),
            "source": "tonapi",
        }

    @classmethod
    def normalize_account_events_response(
        cls,
        payload: Any,
        wallet_address: str,
    ) -> list[dict]:
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")

        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("events must be a list")

        account_norm = (wallet_address or "").strip().lower()
        transfers: list[dict] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = cls._optional_string(event.get("event_id"))
            utime = cls._optional_int(event.get("timestamp"))
            lt = cls._optional_string(event.get("lt"))
            actions = event.get("actions")
            if not isinstance(actions, list):
                continue
            for action in actions:
                if not isinstance(action, dict):
                    continue
                action_type = cls._optional_string(action.get("type"))
                if action_type not in ("TonTransfer", "JettonTransfer"):
                    continue
                detail = action.get(action_type)
                if not isinstance(detail, dict):
                    continue
                transfers.append(
                    cls.normalize_event_transfer(
                        detail,
                        action,
                        action_type,
                        event_id,
                        utime,
                        lt,
                        account_norm,
                    )
                )
        return transfers

    @classmethod
    def normalize_event_transfer(
        cls,
        detail: dict,
        action: dict,
        action_type: str,
        event_id: str | None,
        utime: int | None,
        lt: str | None,
        account_norm: str,
    ) -> dict:
        sender_addr = cls._account_address(detail.get("sender"))
        recipient_addr = cls._account_address(detail.get("recipient"))

        if account_norm and account_norm == (sender_addr or "").strip().lower():
            direction = "out"
            counterparty = recipient_addr
        elif account_norm and account_norm == (recipient_addr or "").strip().lower():
            direction = "in"
            counterparty = sender_addr
        else:
            direction = "unknown"
            counterparty = recipient_addr or sender_addr

        if action_type == "TonTransfer":
            asset = "TON"
            decimals: int | None = 9
            jetton_address = None
            jetton_symbol = None
        else:
            jetton = detail.get("jetton")
            if not isinstance(jetton, dict):
                jetton = {}
            jetton_symbol = cls._optional_string(jetton.get("symbol"))
            jetton_address = cls._optional_string(jetton.get("address"))
            asset = jetton_symbol or jetton_address or "UNKNOWN_JETTON"
            decimals = cls._optional_int(jetton.get("decimals"))

        return {
            "event_id": event_id,
            "utime": utime,
            "lt": lt,
            "action_type": action_type,
            "asset": asset,
            "raw_amount": cls._optional_string(detail.get("amount")),
            "decimals": decimals,
            "direction": direction,
            "counterparty": counterparty,
            "sender": sender_addr,
            "recipient": recipient_addr,
            "jetton_address": jetton_address,
            "jetton_symbol": jetton_symbol,
            "status": cls._optional_string(action.get("status")),
            "source": "tonapi",
        }

    @classmethod
    def _account_address(cls, value: Any) -> str | None:
        if isinstance(value, dict):
            return cls._optional_string(value.get("address"))
        return cls._optional_string(value)

    @classmethod
    def normalize_account_swaps_response(
        cls,
        payload: Any,
        wallet_address: str,
    ) -> list[dict]:
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")

        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("events must be a list")

        swaps: list[dict] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_id = cls._optional_string(event.get("event_id"))
            utime = cls._optional_int(event.get("timestamp"))
            lt = cls._optional_string(event.get("lt"))
            actions = event.get("actions")
            if not isinstance(actions, list):
                continue
            for action in actions:
                if not isinstance(action, dict):
                    continue
                if cls._optional_string(action.get("type")) != "JettonSwap":
                    continue
                detail = action.get("JettonSwap")
                if not isinstance(detail, dict):
                    continue
                swaps.append(
                    cls.normalize_swap(detail, action, event_id, utime, lt)
                )
        return swaps

    @classmethod
    def normalize_swap(
        cls,
        detail: dict,
        action: dict,
        event_id: str | None,
        utime: int | None,
        lt: str | None,
    ) -> dict:
        token_in, amount_in, decimals_in = cls._swap_side(detail, "in")
        token_out, amount_out, decimals_out = cls._swap_side(detail, "out")
        return {
            "event_id": event_id,
            "utime": utime,
            "lt": lt,
            "dex": cls._optional_string(detail.get("dex")),
            "token_in": token_in,
            "raw_amount_in": amount_in,
            "decimals_in": decimals_in,
            "token_out": token_out,
            "raw_amount_out": amount_out,
            "decimals_out": decimals_out,
            "router": cls._account_address(detail.get("router")),
            "status": cls._optional_string(action.get("status")),
            "source": "tonapi",
        }

    @classmethod
    def _swap_side(
        cls,
        detail: dict,
        side: str,
    ) -> tuple[str | None, str | None, int | None]:
        # TonAPI JettonSwap exposes ton_in/ton_out (nanoton) and
        # amount_in/amount_out (raw jetton) with jetton_master_in/out.
        ton_amount = detail.get(f"ton_{side}")
        if ton_amount not in (None, ""):
            return "TON", cls._optional_string(ton_amount), 9
        master = detail.get(f"jetton_master_{side}")
        if not isinstance(master, dict):
            master = {}
        token = cls._optional_string(master.get("symbol")) or cls._optional_string(
            master.get("address")
        )
        amount = cls._optional_string(detail.get(f"amount_{side}"))
        decimals = cls._optional_int(master.get("decimals"))
        return token, amount, decimals

    @classmethod
    def normalize_rates_response(
        cls,
        payload: Any,
        currency: str,
    ) -> dict[str, str | None]:
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")
        rates = payload.get("rates")
        if not isinstance(rates, dict):
            raise ValueError("rates must be an object")

        wanted = currency.upper()
        out: dict[str, str | None] = {}
        for token, entry in rates.items():
            price = None
            if isinstance(entry, dict):
                prices = entry.get("prices")
                if isinstance(prices, dict):
                    for key, value in prices.items():
                        if str(key).upper() == wanted:
                            price = value
                            break
            out[token] = cls._optional_string(price)
        return out

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
