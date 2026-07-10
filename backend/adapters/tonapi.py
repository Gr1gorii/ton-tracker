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

import http.client
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional
import urllib.error
import urllib.parse
import urllib.request

from config import (
    ERROR_PROVIDER_ERROR,
    ERROR_PROVIDER_NOT_CONFIGURED,
    ERROR_PROVIDER_PROTOCOL,
    ProviderResult,
    Settings,
    get_settings,
    tonapi_base_url_network,
)

_HTTP_TIMEOUT = 10
_MAX_RESPONSE_BYTES = 16 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 200_000
_MAX_JSON_NUMBER_CHARS = 128
_MAX_TRANSACTION_PAGE_LIMIT = 1000
_MAX_EVENT_PAGE_LIMIT = 100
_MAX_EVENT_DATE = 2114380800
_MAX_LOGICAL_TIME = 2**64 - 1
_MAX_TRACE_TRANSACTION_NODES = 256
_MAX_TRACE_DEPTH = 32
_MAX_TRACE_OUT_MESSAGES = 2048
_MAX_TRACE_PERSISTED_MESSAGES = (
    _MAX_TRACE_TRANSACTION_NODES + _MAX_TRACE_OUT_MESSAGES
)
_MAX_TRACE_INTERFACES_PER_NODE = 128
_MAX_TRACE_INTERFACE_LENGTH = 128
_MAX_SIGNED_64 = 2**63 - 1
_MAX_TRACE_TRANSACTION_BOC_BYTES = 1024 * 1024
_MAX_TRACE_TOTAL_BOC_BYTES = 8 * 1024 * 1024
_TRACE_MESSAGE_OBSERVATION_VERSION = "tonapi_trace_message_obs_v1"
_SUPPORTED_TRACE_NETWORKS = frozenset(("ton-mainnet", "ton-testnet"))
_LOGICAL_TIME_RE = re.compile(r"^[1-9][0-9]{0,19}$")
_TRANSACTION_HASH_RE = re.compile(r"^[0-9a-fA-F]{64}$")
_RAW_ACCOUNT_RE = re.compile(
    r"^((?:0|[1-9][0-9]*|-[1-9][0-9]*)):([0-9a-fA-F]{64})$"
)
_MIN_WORKCHAIN = -(2**31)
_MAX_WORKCHAIN = 2**31 - 1


def _json_structure_is_bounded(value: Any) -> bool:
    stack: list[tuple[Any, int]] = [(value, 0)]
    node_count = 0
    while stack:
        current, depth = stack.pop()
        node_count += 1
        if node_count > _MAX_JSON_NODES or depth > _MAX_JSON_DEPTH:
            return False
        if isinstance(current, dict):
            stack.extend((item, depth + 1) for item in current.values())
        elif isinstance(current, list):
            stack.extend((item, depth + 1) for item in current)
    return True


def _bounded_json_integer(value: str) -> int:
    if len(value) > _MAX_JSON_NUMBER_CHARS:
        raise ValueError("JSON integer token exceeds the configured limit.")
    return int(value, 10)


def _bounded_json_float(value: str) -> float:
    if len(value) > _MAX_JSON_NUMBER_CHARS:
        raise ValueError("JSON float token exceeds the configured limit.")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError("JSON float token is not finite.")
    return parsed


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"Non-standard JSON constant is not allowed: {value}.")


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
        if self.settings.tonapi_api_key and parsed.scheme != "https":
            return None
        provider_network = tonapi_base_url_network(base_url)
        if (
            provider_network is not None
            and provider_network != self.settings.ton_network
        ):
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

    def _protocol_error(self, message: str) -> ProviderResult:
        return ProviderResult.failure(
            ERROR_PROVIDER_PROTOCOL,
            self._sanitize_diagnostic(message) or "TonAPI protocol error.",
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
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"

        request = urllib.request.Request(
            url,
            data=data,
            headers=headers,
            method=method.upper(),
        )
        if self.settings.tonapi_api_key:
            # Unredirected headers are sent to the configured origin but are
            # deliberately omitted when urllib constructs a redirect request.
            request.add_unredirected_header(
                "Authorization",
                f"Bearer {self.settings.tonapi_api_key}",
            )

        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw_bytes = response.read(_MAX_RESPONSE_BYTES + 1)
            if not isinstance(raw_bytes, bytes):
                return self._protocol_error(
                    "TonAPI returned a non-byte response body."
                )
            if len(raw_bytes) > _MAX_RESPONSE_BYTES:
                return self._protocol_error(
                    "TonAPI response exceeded the configured byte limit."
                )
            raw_body = raw_bytes.decode("utf-8")
            payload = json.loads(
                raw_body,
                parse_int=_bounded_json_integer,
                parse_float=_bounded_json_float,
                parse_constant=_reject_json_constant,
            )
            if not _json_structure_is_bounded(payload):
                return self._protocol_error(
                    "TonAPI JSON exceeded structural depth or node limits."
                )
        except urllib.error.HTTPError as exc:
            return self._provider_error(
                f"TonAPI HTTP error: {exc.code} {exc.reason}."
            )
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            http.client.HTTPException,
        ) as exc:
            return self._provider_error(f"TonAPI network error: {exc}.")
        except (
            ValueError,
            UnicodeDecodeError,
            RecursionError,
            MemoryError,
            OverflowError,
        ):
            return self._protocol_error("TonAPI returned invalid JSON.")

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

    # -- Transaction pages and preview ----------------------------------

    def get_account_transactions_page(
        self,
        account_address: str,
        limit: int = 10,
        before_lt: Optional[int | str] = None,
    ) -> ProviderResult:
        """Fetch one strictly ordered TonAPI account-transaction page.

        The returned cursor is evidence about this response page only. An
        empty page terminates the cursor chain; it does not by itself prove
        that a requested historical time range is complete.
        """
        account = self._optional_string(account_address)
        if account is None:
            return self._provider_error("TonAPI account address is required.")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_TRANSACTION_PAGE_LIMIT
        ):
            return self._provider_error(
                "TonAPI transaction page limit must be between 1 and 1000."
            )

        request_before_lt = None
        if before_lt is not None:
            request_before_lt = self._strict_logical_time(before_lt)
            if request_before_lt is None:
                return self._provider_error(
                    "TonAPI transaction page before_lt must be a canonical "
                    "decimal logical time from 1 through 2^64-1."
                )

        if self.settings.is_mock:
            return ProviderResult.success(
                {
                    "wallet_address": account,
                    "requested_limit": limit,
                    "request_before_lt": request_before_lt,
                    "raw_count": 0,
                    "min_logical_time": None,
                    "max_logical_time": None,
                    "next_before_lt": None,
                    "transactions": [],
                },
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        encoded_account = urllib.parse.quote(account, safe="")
        result = self.fetch_json(
            f"/v2/blockchain/accounts/{encoded_account}/transactions",
            query={"limit": limit, "before_lt": request_before_lt},
        )
        if not result.ok:
            return result

        try:
            transactions = self.normalize_account_transactions_response(
                result.data,
                account,
            )
            if len(transactions) > limit:
                raise ValueError(
                    "transaction page returned more rows than requested"
                )
            logical_times = [
                int(transaction["logical_time"], 10)
                for transaction in transactions
            ]
            if any(
                previous <= current
                for previous, current in zip(
                    logical_times,
                    logical_times[1:],
                )
            ):
                raise ValueError(
                    "transaction logical times must be strictly descending"
                )
            if (
                request_before_lt is not None
                and logical_times
                and max(logical_times) >= int(request_before_lt, 10)
            ):
                raise ValueError(
                    "transaction page did not advance below its before_lt cursor"
                )
        except (KeyError, TypeError, ValueError) as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_PROTOCOL,
                self._sanitize_diagnostic(
                    "TonAPI response had an unexpected structure for "
                    f"transaction page: {exc}."
                )
                or "TonAPI transaction page protocol error.",
                source="real",
            )

        min_logical_time = str(min(logical_times)) if logical_times else None
        max_logical_time = str(max(logical_times)) if logical_times else None
        return ProviderResult.success(
            {
                "wallet_address": account,
                "requested_limit": limit,
                "request_before_lt": request_before_lt,
                "raw_count": len(transactions),
                "min_logical_time": min_logical_time,
                "max_logical_time": max_logical_time,
                "next_before_lt": min_logical_time,
                "transactions": transactions,
            },
            source="real",
            message=(
                "TonAPI account transaction page fetched with a strict "
                "descending logical-time cursor. This page is not proof of "
                "complete wallet history, PnL, or ownership."
            ),
        )

    def get_account_transactions_preview(
        self,
        account_address: str,
        limit: int = 10,
        before_lt: Optional[int | str] = None,
    ) -> ProviderResult:
        """Fetch and normalize a TonAPI account transaction-history preview.

        This is an ordered account-level activity timeline only. It is not DEX
        swap reconstruction, transfer-level attribution, PnL, or ownership
        proof.
        """
        page = self.get_account_transactions_page(
            account_address,
            limit=limit,
            before_lt=before_lt,
        )
        if not page.ok:
            return page

        data = page.data if isinstance(page.data, dict) else {}
        account = data.get("wallet_address")
        transactions = (
            data.get("transactions")
            if isinstance(data.get("transactions"), list)
            else []
        )
        preview = transactions[:limit]
        if page.source == "mock":
            message = "Mock mode: TonAPI is not actively queried."
        else:
            message = (
                "TonAPI account transaction history fetched. This is an "
                "ordered account-level activity timeline only and is not DEX "
                "swap reconstruction, PnL, or ownership proof."
            )
        return ProviderResult.success(
            {
                "wallet_address": account,
                "transactions": preview,
                "preview_count": len(preview),
                "total_transactions": data.get("raw_count", len(transactions)),
            },
            source=page.source,
            message=message,
        )

    # -- Low-level transaction trace evidence preview ------------------

    def get_transaction_trace_evidence_preview(
        self,
        transaction_hash: str,
    ) -> ProviderResult:
        """Fetch one bounded provider-indexed low-level transaction trace.

        The result is a sanitized structural summary. It intentionally omits
        raw messages, BOCs, decoded bodies, interfaces, and semantic actions.
        A validated provider trace is still not locally verified blockchain
        proof and is not an authoritative transfer/trade reconstruction.
        """
        if (
            not isinstance(transaction_hash, str)
            or transaction_hash != transaction_hash.lower()
            or _TRANSACTION_HASH_RE.fullmatch(transaction_hash) is None
        ):
            return self._provider_error(
                "TonAPI trace evidence requires a canonical lowercase "
                "32-byte transaction hash."
            )
        if self.settings.is_mock:
            return self._provider_error(
                "TonAPI trace evidence requires guarded real mode."
            )

        result = self.fetch_json(f"/v2/traces/{transaction_hash}")
        if not result.ok:
            return result

        try:
            normalized = self.normalize_transaction_trace_evidence_response(
                result.data,
                requested_transaction_hash=transaction_hash,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_PROTOCOL,
                self._sanitize_diagnostic(
                    "TonAPI response had an unexpected structure for "
                    f"transaction trace evidence: {exc}."
                )
                or "TonAPI transaction trace evidence protocol error.",
                source="real",
            )

        return ProviderResult.success(
            normalized,
            source="real",
            message=(
                "TonAPI low-level transaction trace evidence fetched and "
                "structurally validated. This provider-indexed summary is "
                "not locally verified blockchain proof or authoritative "
                "semantic activity reconstruction."
            ),
        )

    def get_transaction_trace_persisted_evidence(
        self,
        transaction_hash: str,
        network: str,
    ) -> ProviderResult:
        """Fetch one trace candidate for a bounded persisted evidence ledger."""
        if (
            not isinstance(transaction_hash, str)
            or transaction_hash != transaction_hash.lower()
            or _TRANSACTION_HASH_RE.fullmatch(transaction_hash) is None
        ):
            return self._provider_error(
                "TonAPI persisted trace evidence requires a canonical "
                "lowercase 32-byte transaction hash."
            )
        if network not in _SUPPORTED_TRACE_NETWORKS:
            return self._provider_error(
                "TonAPI persisted trace evidence requires a supported "
                "canonical TON network."
            )
        if self.settings.is_mock:
            return self._provider_error(
                "TonAPI persisted trace evidence requires guarded real mode."
            )

        result = self.fetch_json(f"/v2/traces/{transaction_hash}")
        if not result.ok:
            return result

        try:
            normalized = (
                self.normalize_transaction_trace_persisted_evidence_response(
                    result.data,
                    requested_transaction_hash=transaction_hash,
                    network=network,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_PROTOCOL,
                self._sanitize_diagnostic(
                    "TonAPI response had an unexpected structure for "
                    f"persisted transaction trace evidence: {exc}."
                )
                or "TonAPI persisted transaction trace evidence protocol error.",
                source="real",
            )

        return ProviderResult.success(
            normalized,
            source="real",
            message=(
                "TonAPI low-level transaction and message evidence was "
                "structurally validated as a persistence candidate. It is not "
                "locally verified blockchain proof or authoritative semantic "
                "activity reconstruction."
            ),
        )

    def get_transaction_trace_boc_verification_candidate(
        self,
        transaction_hash: str,
        network: str,
    ) -> ProviderResult:
        """Fetch one bounded trace including transaction BOCs for local checks."""
        if (
            not isinstance(transaction_hash, str)
            or transaction_hash != transaction_hash.lower()
            or _TRANSACTION_HASH_RE.fullmatch(transaction_hash) is None
        ):
            return self._provider_error(
                "TonAPI BOC verification requires a canonical lowercase "
                "32-byte transaction hash."
            )
        if network not in _SUPPORTED_TRACE_NETWORKS:
            return self._provider_error(
                "TonAPI BOC verification requires a supported canonical TON network."
            )
        if self.settings.is_mock:
            return self._provider_error(
                "TonAPI BOC verification requires guarded real mode."
            )

        result = self.fetch_json(f"/v2/traces/{transaction_hash}")
        if not result.ok:
            return result
        try:
            normalized = self.normalize_transaction_trace_boc_verification_response(
                result.data,
                requested_transaction_hash=transaction_hash,
                network=network,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_PROTOCOL,
                self._sanitize_diagnostic(
                    "TonAPI response had an unexpected structure for local "
                    f"transaction BOC verification: {exc}."
                )
                or "TonAPI transaction BOC verification protocol error.",
                source="real",
            )
        return ProviderResult.success(
            normalized,
            source="real",
            message=(
                "TonAPI transaction BOCs were fetched as a bounded local "
                "verification candidate. Provider delivery alone is not a "
                "blockchain inclusion proof."
            ),
        )

    # -- Account event pages and derived previews -----------------------

    def get_account_events_page(
        self,
        account_address: str,
        limit: int = 20,
        before_lt: Optional[int | str] = None,
        start_date: Optional[int] = None,
        end_date: Optional[int] = None,
    ) -> ProviderResult:
        """Fetch one strict page of display-oriented account events.

        Events and actions are provider-derived UI abstractions. Page evidence
        can describe TonAPI acquisition only; it is never authoritative
        protocol logic, ownership proof, cost basis, or PnL.
        """
        account = self._optional_string(account_address)
        if account is None:
            return self._provider_error("TonAPI account address is required.")
        if (
            isinstance(limit, bool)
            or not isinstance(limit, int)
            or not 1 <= limit <= _MAX_EVENT_PAGE_LIMIT
        ):
            return self._provider_error(
                "TonAPI account event page limit must be between 1 and 100."
            )

        request_before_lt = None
        if before_lt is not None:
            request_before_lt = self._strict_logical_time(before_lt)
            if request_before_lt is None:
                return self._provider_error(
                    "TonAPI account event before_lt must be a canonical "
                    "decimal logical time from 1 through 2^64-1."
                )
        request_start = self._strict_event_date(start_date)
        request_end = self._strict_event_date(end_date)
        if start_date is not None and request_start is None:
            return self._provider_error(
                "TonAPI account event start_date is outside the supported range."
            )
        if end_date is not None and request_end is None:
            return self._provider_error(
                "TonAPI account event end_date is outside the supported range."
            )
        if (
            request_start is not None
            and request_end is not None
            and request_start > request_end
        ):
            return self._provider_error(
                "TonAPI account event start_date must not exceed end_date."
            )

        if self.settings.is_mock:
            return ProviderResult.success(
                {
                    "wallet_address": account,
                    "requested_limit": limit,
                    "request_before_lt": request_before_lt,
                    "request_start_date": request_start,
                    "request_end_date": request_end,
                    "raw_count": 0,
                    "min_logical_time": None,
                    "max_logical_time": None,
                    "next_before_lt": None,
                    "events": [],
                },
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        encoded_account = urllib.parse.quote(account, safe="")
        result = self.fetch_json(
            f"/v2/accounts/{encoded_account}/events",
            query={
                "limit": limit,
                "before_lt": request_before_lt,
                "start_date": request_start,
                "end_date": request_end,
                "sort_order": "desc",
            },
        )
        if not result.ok:
            return result

        try:
            page = self.normalize_account_events_page_response(result.data)
            events = page["events"]
            if len(events) > limit:
                raise ValueError("event page returned more rows than requested")
            logical_times = [int(event["lt"], 10) for event in events]
            timestamps = [event["timestamp"] for event in events]
            if any(
                previous <= current
                for previous, current in zip(logical_times, logical_times[1:])
            ):
                raise ValueError(
                    "event logical times must be strictly descending"
                )
            if any(
                previous < current
                for previous, current in zip(timestamps, timestamps[1:])
            ):
                raise ValueError(
                    "event timestamps must follow logical-time order"
                )
            if (
                request_before_lt is not None
                and logical_times
                and max(logical_times) >= int(request_before_lt, 10)
            ):
                raise ValueError(
                    "event page did not advance below its before_lt cursor"
                )
            min_logical_time = (
                str(min(logical_times)) if logical_times else None
            )
            max_logical_time = (
                str(max(logical_times)) if logical_times else None
            )
            next_before_lt = page["next_before_lt"]
            if events and next_before_lt != min_logical_time:
                raise ValueError(
                    "event page next_from must equal minimum logical time"
                )
            if not events and next_before_lt is not None:
                raise ValueError("empty event page must terminate its cursor")
        except (KeyError, TypeError, ValueError) as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_PROTOCOL,
                self._sanitize_diagnostic(
                    "TonAPI response had an unexpected structure for account "
                    f"event page: {exc}."
                )
                or "TonAPI account event page protocol error.",
                source="real",
            )

        return ProviderResult.success(
            {
                "wallet_address": account,
                "requested_limit": limit,
                "request_before_lt": request_before_lt,
                "request_start_date": request_start,
                "request_end_date": request_end,
                "raw_count": len(events),
                "min_logical_time": min_logical_time,
                "max_logical_time": max_logical_time,
                "next_before_lt": next_before_lt,
                "events": events,
            },
            source="real",
            message=(
                "TonAPI account event page fetched for display-oriented "
                "provider evidence only. Event actions can change and must "
                "not be used as authoritative protocol logic."
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
        page = self.get_account_events_page(
            account_address,
            limit=limit,
        )
        if not page.ok:
            return page
        data = page.data if isinstance(page.data, dict) else {}
        account = data.get("wallet_address")
        events = data.get("events") if isinstance(data.get("events"), list) else []
        try:
            transfers = self.normalize_account_events_response(
                {"events": events},
                account or "",
            )
        except ValueError as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_PROTOCOL,
                self._sanitize_diagnostic(
                    f"TonAPI event action normalization failed: {exc}."
                )
                or "TonAPI event action protocol error.",
                source=page.source,
            )
        total_events = data.get("raw_count", len(events))
        message = (
            "Mock mode: TonAPI is not actively queried."
            if page.source == "mock"
            else (
                "TonAPI account transfer history fetched from events. Only "
                "TON and jetton transfer actions are represented and "
                "direction is best-effort; this is not DEX swap "
                "reconstruction, PnL, or ownership proof."
            )
        )
        return ProviderResult.success(
            {
                "wallet_address": account,
                "transfers": transfers,
                "preview_count": len(transfers),
                "total_transfers": len(transfers),
                "total_events": total_events,
            },
            source=page.source,
            message=message,
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
        page = self.get_account_events_page(
            account_address,
            limit=limit,
        )
        if not page.ok:
            return page
        data = page.data if isinstance(page.data, dict) else {}
        account = data.get("wallet_address")
        events = data.get("events") if isinstance(data.get("events"), list) else []
        try:
            swaps = self.normalize_account_swaps_response(
                {"events": events},
                account or "",
            )
        except ValueError as exc:
            return ProviderResult.failure(
                ERROR_PROVIDER_PROTOCOL,
                self._sanitize_diagnostic(
                    f"TonAPI event action normalization failed: {exc}."
                )
                or "TonAPI event action protocol error.",
                source=page.source,
            )
        total_events = data.get("raw_count", len(events))
        message = (
            "Mock mode: TonAPI is not actively queried."
            if page.source == "mock"
            else (
                "TonAPI account DEX swaps fetched from events. Only "
                "JettonSwap actions are represented and USD valuation is not "
                "computed; this is not PnL or ownership proof."
            )
        )
        return ProviderResult.success(
            {
                "wallet_address": account,
                "swaps": swaps,
                "preview_count": len(swaps),
                "total_swaps": len(swaps),
                "total_events": total_events,
            },
            source=page.source,
            message=message,
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

    def get_rates_chart_preview(
        self,
        token: str,
        currency: str = "usd",
        start_date: int | None = None,
        end_date: int | None = None,
    ) -> ProviderResult:
        """Fetch provider-reported historical rate points from TonAPI.

        ``token`` accepts ``"ton"`` or a jetton master address. Points are
        provider-reported chart samples used by standalone inspection and by
        explicitly requested run-scoped PnL enrichment.
        """
        cleaned = self._optional_string(token)
        if not cleaned:
            return self._provider_error("TonAPI rates chart requires a token.")

        if self.settings.is_mock:
            return ProviderResult.success(
                {"token": cleaned, "currency": currency, "points": []},
                source="mock",
                message="Mock mode: TonAPI is not actively queried.",
            )

        query: dict[str, Any] = {"token": cleaned, "currency": currency}
        if start_date is not None:
            query["start_date"] = start_date
        if end_date is not None:
            query["end_date"] = end_date

        result = self.fetch_json("/v2/rates/chart", query=query)
        if not result.ok:
            return result

        try:
            points = self.normalize_rates_chart_response(result.data)
        except ValueError as exc:
            return self._provider_error(
                f"TonAPI response had an unexpected structure: {exc}."
            )

        return ProviderResult.success(
            {"token": cleaned, "currency": currency, "points": points},
            source="real",
            message=(
                "TonAPI historical rate points fetched. Provider-reported "
                "chart samples; coverage may be sparse or stale."
            ),
        )

    # -- Normalization ---------------------------------------------------

    @classmethod
    def normalize_rates_chart_response(cls, payload: Any) -> list[dict]:
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")
        points = payload.get("points")
        if not isinstance(points, list):
            raise ValueError("points must be a list")

        normalized = []
        for index, point in enumerate(points):
            if not isinstance(point, (list, tuple)) or len(point) != 2:
                raise ValueError(
                    f"point {index} must be a [timestamp, price] pair"
                )
            timestamp, price = point
            if isinstance(timestamp, bool) or not isinstance(
                timestamp, (int, float)
            ):
                raise ValueError(f"point {index} timestamp must be a number")
            if isinstance(price, bool) or not isinstance(price, (int, float)):
                raise ValueError(f"point {index} price must be a number")
            iso = (
                datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
                .isoformat()
                .replace("+00:00", "Z")
            )
            normalized.append({"timestamp": iso, "price_usd": str(price)})
        return normalized

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
        tx_hash = raw_tx.get("hash")
        if (
            not isinstance(tx_hash, str)
            or tx_hash != tx_hash.strip()
            or _TRANSACTION_HASH_RE.fullmatch(tx_hash) is None
        ):
            raise ValueError("transaction is missing a canonical 32-byte hash")
        logical_time = cls._strict_logical_time(raw_tx.get("lt"))
        if logical_time is None:
            raise ValueError(
                "transaction is missing or has invalid logical time"
            )
        raw_total_fees = raw_tx.get("total_fees")
        total_fees = cls._strict_nonnegative_integer_string(raw_total_fees)
        if raw_total_fees is not None and total_fees is None:
            raise ValueError("transaction has invalid total_fees")

        success = raw_tx.get("success")
        return {
            "wallet_address": wallet_address,
            "tx_hash": tx_hash,
            "logical_time": logical_time,
            "utime": cls._optional_int(raw_tx.get("utime")),
            "total_fees": total_fees,
            "success": success if isinstance(success, bool) else None,
            "transaction_type": cls._optional_string(
                raw_tx.get("transaction_type")
            ),
            "orig_status": cls._optional_string(raw_tx.get("orig_status")),
            "end_status": cls._optional_string(raw_tx.get("end_status")),
            "source": "tonapi",
        }

    @classmethod
    def normalize_transaction_trace_evidence_response(
        cls,
        payload: Any,
        *,
        requested_transaction_hash: str,
    ) -> dict[str, Any]:
        """Validate a trace iteratively and return a bounded summary only."""
        if (
            not isinstance(requested_transaction_hash, str)
            or requested_transaction_hash
            != requested_transaction_hash.lower()
            or _TRANSACTION_HASH_RE.fullmatch(requested_transaction_hash)
            is None
        ):
            raise ValueError(
                "requested transaction hash must be canonical lowercase hex"
            )
        if not isinstance(payload, dict):
            raise ValueError("trace response must be an object")

        stack: list[tuple[dict[str, Any], int]] = [(payload, 0)]
        seen_hashes: set[str] = set()
        seen_coordinates: dict[tuple[str, str], str] = {}
        anchor: dict[str, str] | None = None
        root_transaction_hash: str | None = None
        transaction_count = 0
        max_depth = 0
        out_message_count = 0
        pending_internal_message_count = 0
        successful_transaction_count = 0
        failed_transaction_count = 0
        aborted_transaction_count = 0
        accounts: set[str] = set()

        while stack:
            node, depth = stack.pop()
            if not isinstance(node, dict):
                raise ValueError("trace child must be an object")
            if depth > _MAX_TRACE_DEPTH:
                raise ValueError(
                    "trace exceeds the maximum transaction-tree depth"
                )
            transaction_count += 1
            if transaction_count > _MAX_TRACE_TRANSACTION_NODES:
                raise ValueError(
                    "trace exceeds the maximum transaction-node count"
                )
            max_depth = max(max_depth, depth)

            emulated = node.get("emulated", False)
            if not isinstance(emulated, bool):
                raise ValueError("trace emulated state must be boolean")
            if emulated:
                raise ValueError("emulated trace nodes are not accepted")

            interfaces = node.get("interfaces")
            if (
                not isinstance(interfaces, list)
                or len(interfaces) > _MAX_TRACE_INTERFACES_PER_NODE
                or any(
                    not isinstance(interface, str)
                    or not interface
                    or interface != interface.strip()
                    or len(interface) > _MAX_TRACE_INTERFACE_LENGTH
                    for interface in interfaces
                )
            ):
                raise ValueError("trace interfaces must be a bounded string list")

            transaction = node.get("transaction")
            if not isinstance(transaction, dict):
                raise ValueError("trace node transaction must be an object")
            raw_hash = transaction.get("hash")
            if (
                not isinstance(raw_hash, str)
                or raw_hash != raw_hash.strip()
                or _TRANSACTION_HASH_RE.fullmatch(raw_hash) is None
            ):
                raise ValueError(
                    "trace transaction hash must be canonical 32-byte hex"
                )
            transaction_hash = raw_hash.lower()
            if transaction_hash in seen_hashes:
                raise ValueError("trace reuses a transaction hash")
            seen_hashes.add(transaction_hash)
            if root_transaction_hash is None:
                root_transaction_hash = transaction_hash

            logical_time = cls._strict_logical_time(transaction.get("lt"))
            if logical_time is None:
                raise ValueError("trace transaction has invalid logical time")
            account = cls._canonical_raw_account_address(
                transaction.get("account")
            )
            if account is None:
                raise ValueError("trace transaction has invalid account")
            accounts.add(account)
            coordinate = (account, logical_time)
            prior_coordinate_hash = seen_coordinates.get(coordinate)
            if (
                prior_coordinate_hash is not None
                and prior_coordinate_hash != transaction_hash
            ):
                raise ValueError(
                    "trace transaction coordinate changed hash"
                )
            seen_coordinates[coordinate] = transaction_hash

            utime = transaction.get("utime")
            if (
                isinstance(utime, bool)
                or not isinstance(utime, int)
                or not 0 <= utime <= 2**63 - 1
            ):
                raise ValueError("trace transaction has invalid utime")
            success = transaction.get("success")
            if not isinstance(success, bool):
                raise ValueError("trace transaction success must be boolean")
            if success:
                successful_transaction_count += 1
            else:
                failed_transaction_count += 1
            aborted = transaction.get("aborted")
            if not isinstance(aborted, bool):
                raise ValueError("trace transaction aborted must be boolean")
            if aborted:
                aborted_transaction_count += 1

            out_messages = transaction.get("out_msgs")
            if not isinstance(out_messages, list):
                raise ValueError("trace transaction out_msgs must be a list")
            out_message_count += len(out_messages)
            if out_message_count > _MAX_TRACE_OUT_MESSAGES:
                raise ValueError(
                    "trace exceeds the maximum outgoing-message count"
                )
            for message in out_messages:
                if not isinstance(message, dict):
                    raise ValueError("trace outgoing message must be an object")
                message_type = message.get("msg_type")
                if message_type not in (
                    "int_msg",
                    "ext_in_msg",
                    "ext_out_msg",
                ):
                    raise ValueError(
                        "trace outgoing message has invalid message type"
                    )
                if message_type == "int_msg":
                    pending_internal_message_count += 1

            if transaction_hash == requested_transaction_hash:
                anchor = {
                    "transaction_hash": transaction_hash,
                    "logical_time": logical_time,
                    "account_canonical": account,
                }

            raw_children = node.get("children", [])
            if not isinstance(raw_children, list):
                raise ValueError("trace children must be a list")
            if transaction_count + len(stack) + len(raw_children) > (
                _MAX_TRACE_TRANSACTION_NODES
            ):
                raise ValueError(
                    "trace exceeds the maximum transaction-node count"
                )
            for child in reversed(raw_children):
                if not isinstance(child, dict):
                    raise ValueError("trace child must be an object")
                stack.append((child, depth + 1))

        if anchor is None:
            raise ValueError(
                "trace does not contain the requested transaction hash"
            )
        assert root_transaction_hash is not None
        trace_state = (
            "pending" if pending_internal_message_count else "finalized"
        )
        return {
            "trace_state": trace_state,
            "anchor": anchor,
            "summary": {
                "root_transaction_hash": root_transaction_hash,
                "transaction_count": transaction_count,
                "max_depth": max_depth,
                "out_message_count": out_message_count,
                "pending_internal_message_count": (
                    pending_internal_message_count
                ),
                "successful_transaction_count": (
                    successful_transaction_count
                ),
                "failed_transaction_count": failed_transaction_count,
                "aborted_transaction_count": aborted_transaction_count,
                "unique_account_count": len(accounts),
            },
        }

    @classmethod
    def normalize_transaction_trace_persisted_evidence_response(
        cls,
        payload: Any,
        *,
        requested_transaction_hash: str,
        network: str,
    ) -> dict[str, Any]:
        """Return a strict transaction/message observation graph candidate.

        The existing preview normalizer remains the first validation boundary.
        This second pass adds only the bounded fields needed by the persisted
        provider-observation ledger; it never returns raw cells, decoded
        bodies, interfaces, or semantic actions.
        """
        preview = cls.normalize_transaction_trace_evidence_response(
            payload,
            requested_transaction_hash=requested_transaction_hash,
        )
        if network not in _SUPPORTED_TRACE_NETWORKS:
            raise ValueError("persisted trace network is not supported")
        root_transaction_hash = preview["summary"][
            "root_transaction_hash"
        ]
        nodes: list[dict[str, Any]] = []
        root_inbound_message_count = 0
        child_internal_message_count = 0
        remaining_out_message_count = 0
        type_counts = {
            "int_msg": 0,
            "ext_in_msg": 0,
            "ext_out_msg": 0,
        }
        observation_keys: set[str] = set()
        stack: list[tuple[dict[str, Any], int | None, str | None, int]] = [
            (payload, None, None, 0)
        ]

        while stack:
            node, parent_preorder_index, parent_account, depth = stack.pop()
            transaction = node["transaction"]
            preorder_index = len(nodes)
            transaction_hash = transaction["hash"].lower()
            account = cls._canonical_raw_account_address(
                transaction["account"]
            )
            logical_time = cls._strict_logical_time(transaction["lt"])
            if account is None or logical_time is None:
                raise ValueError(
                    "trace transaction identity changed during normalization"
                )

            raw_in_message = transaction.get("in_msg")
            if raw_in_message is None:
                if parent_preorder_index is not None:
                    raise ValueError(
                        "trace child transaction is missing its internal "
                        "incoming message"
                    )
                in_message = None
            else:
                if not isinstance(raw_in_message, dict):
                    raise ValueError(
                        "trace transaction in_msg must be an object or null"
                    )
                role = (
                    "root_inbound"
                    if parent_preorder_index is None
                    else "child_inbound"
                )
                in_message = cls._normalize_persisted_trace_message(
                    raw_in_message,
                    network=network,
                    root_transaction_hash=root_transaction_hash,
                    preorder_index=preorder_index,
                    role=role,
                    ordinal=0,
                )
                if parent_preorder_index is None:
                    if in_message["message_type"] == "ext_out_msg":
                        raise ValueError(
                            "trace root incoming message has invalid type"
                        )
                    root_inbound_message_count += 1
                else:
                    if (
                        in_message["message_type"] != "int_msg"
                        or in_message["source_account_canonical"]
                        != parent_account
                        or in_message["destination_account_canonical"]
                        != account
                    ):
                        raise ValueError(
                            "trace child incoming message does not match its "
                            "parent/account edge"
                        )
                    child_internal_message_count += 1
                observation_key = in_message["observation_identity_key"]
                if observation_key in observation_keys:
                    raise ValueError(
                        "trace reuses a message observation identity"
                    )
                observation_keys.add(observation_key)
                type_counts[in_message["message_type"]] += 1

            out_messages: list[dict[str, Any]] = []
            for ordinal, raw_message in enumerate(transaction["out_msgs"]):
                message = cls._normalize_persisted_trace_message(
                    raw_message,
                    network=network,
                    root_transaction_hash=root_transaction_hash,
                    preorder_index=preorder_index,
                    role="remaining_outbound",
                    ordinal=ordinal,
                )
                if message["message_type"] not in (
                    "int_msg",
                    "ext_out_msg",
                ):
                    raise ValueError(
                        "trace has an invalid remaining outgoing message type"
                    )
                observation_key = message["observation_identity_key"]
                if observation_key in observation_keys:
                    raise ValueError(
                        "trace reuses a message observation identity"
                    )
                observation_keys.add(observation_key)
                type_counts[message["message_type"]] += 1
                remaining_out_message_count += 1
                out_messages.append(message)

            nodes.append(
                {
                    "preorder_index": preorder_index,
                    "parent_preorder_index": parent_preorder_index,
                    "depth": depth,
                    "transaction_hash": transaction_hash,
                    "account_canonical": account,
                    "logical_time": logical_time,
                    "unix_time": transaction["utime"],
                    "success": transaction["success"],
                    "aborted": transaction["aborted"],
                    "in_message": in_message,
                    "out_messages": out_messages,
                }
            )

            raw_children = node.get("children", [])
            for child in reversed(raw_children):
                stack.append((child, preorder_index, account, depth + 1))

        message_count = (
            root_inbound_message_count
            + child_internal_message_count
            + remaining_out_message_count
        )
        if message_count > _MAX_TRACE_PERSISTED_MESSAGES:
            raise ValueError(
                "trace exceeds the maximum persisted-message count"
            )
        if child_internal_message_count != len(nodes) - 1:
            raise ValueError(
                "trace child-message count does not cover every child node"
            )
        if sum(type_counts.values()) != message_count:
            raise ValueError("trace message type counts are incoherent")

        preview_summary = preview["summary"]
        return {
            "trace_state": preview["trace_state"],
            "anchor": preview["anchor"],
            "summary": {
                "root_transaction_hash": root_transaction_hash,
                "transaction_count": preview_summary["transaction_count"],
                "max_depth": preview_summary["max_depth"],
                "message_count": message_count,
                "root_inbound_message_count": root_inbound_message_count,
                "child_internal_message_count": (
                    child_internal_message_count
                ),
                "remaining_out_message_count": remaining_out_message_count,
                "internal_message_count": type_counts["int_msg"],
                "external_in_message_count": type_counts["ext_in_msg"],
                "external_out_message_count": type_counts["ext_out_msg"],
                "successful_transaction_count": preview_summary[
                    "successful_transaction_count"
                ],
                "failed_transaction_count": preview_summary[
                    "failed_transaction_count"
                ],
                "aborted_transaction_count": preview_summary[
                    "aborted_transaction_count"
                ],
                "unique_account_count": preview_summary[
                    "unique_account_count"
                ],
            },
            "nodes": nodes,
        }

    @classmethod
    def normalize_transaction_trace_boc_verification_response(
        cls,
        payload: Any,
        *,
        requested_transaction_hash: str,
        network: str,
    ) -> dict[str, Any]:
        """Add bounded canonical transaction BOCs to the persisted graph candidate."""
        trace = cls.normalize_transaction_trace_persisted_evidence_response(
            payload,
            requested_transaction_hash=requested_transaction_hash,
            network=network,
        )
        transaction_bocs: list[dict[str, Any]] = []
        total_boc_bytes = 0
        stack: list[dict[str, Any]] = [payload]
        while stack:
            node = stack.pop()
            preorder_index = len(transaction_bocs)
            transaction = node.get("transaction")
            if not isinstance(transaction, dict):
                raise ValueError("trace BOC node transaction must be an object")
            raw_boc = transaction.get("raw")
            if (
                not isinstance(raw_boc, str)
                or not raw_boc
                or raw_boc != raw_boc.strip()
                or len(raw_boc) % 2 != 0
                or re.fullmatch(r"[0-9a-fA-F]+", raw_boc) is None
            ):
                raise ValueError("trace transaction raw BOC must be canonical hex")
            boc_bytes = len(raw_boc) // 2
            if boc_bytes > _MAX_TRACE_TRANSACTION_BOC_BYTES:
                raise ValueError("trace transaction BOC exceeds the per-node limit")
            total_boc_bytes += boc_bytes
            if total_boc_bytes > _MAX_TRACE_TOTAL_BOC_BYTES:
                raise ValueError("trace transaction BOCs exceed the aggregate limit")
            expected_node = trace["nodes"][preorder_index]
            transaction_bocs.append(
                {
                    "preorder_index": preorder_index,
                    "transaction_hash": expected_node["transaction_hash"],
                    "transaction_boc_hex": raw_boc.lower(),
                    "transaction_boc_bytes": boc_bytes,
                }
            )
            children = node.get("children", [])
            for child in reversed(children):
                stack.append(child)

        if len(transaction_bocs) != trace["summary"]["transaction_count"]:
            raise ValueError("trace transaction BOC count is incoherent")
        return {
            "trace": trace,
            "transaction_bocs": transaction_bocs,
            "total_boc_bytes": total_boc_bytes,
        }

    @classmethod
    def _normalize_persisted_trace_message(
        cls,
        message: Any,
        *,
        network: str,
        root_transaction_hash: str,
        preorder_index: int,
        role: str,
        ordinal: int,
    ) -> dict[str, Any]:
        if not isinstance(message, dict):
            raise ValueError("trace message must be an object")
        raw_hash = message.get("hash")
        if (
            not isinstance(raw_hash, str)
            or raw_hash != raw_hash.strip()
            or _TRANSACTION_HASH_RE.fullmatch(raw_hash) is None
        ):
            raise ValueError("trace message has invalid hash")
        message_hash = raw_hash.lower()
        message_type = message.get("msg_type")
        if message_type not in ("int_msg", "ext_in_msg", "ext_out_msg"):
            raise ValueError("trace message has invalid type")

        accounts: dict[str, str | None] = {}
        for provider_field, output_field in (
            ("source", "source_account_canonical"),
            ("destination", "destination_account_canonical"),
        ):
            raw_account = message.get(provider_field)
            if raw_account is None:
                accounts[output_field] = None
                continue
            canonical_account = cls._canonical_raw_account_address(raw_account)
            if canonical_account is None:
                raise ValueError(
                    f"trace message has invalid {provider_field} account"
                )
            accounts[output_field] = canonical_account

        source_account = accounts["source_account_canonical"]
        destination_account = accounts["destination_account_canonical"]
        if message_type == "int_msg" and (
            source_account is None or destination_account is None
        ):
            raise ValueError(
                "trace internal message requires source and destination accounts"
            )
        if message_type == "ext_in_msg" and (
            source_account is not None or destination_account is None
        ):
            raise ValueError(
                "trace external inbound message endpoints are incoherent"
            )
        if message_type == "ext_out_msg" and (
            source_account is None or destination_account is not None
        ):
            raise ValueError(
                "trace external outbound message endpoints are incoherent"
            )

        created_logical_time = cls._strict_nonnegative_integer_string(
            message.get("created_lt")
        )
        if created_logical_time is None:
            raise ValueError("trace message has invalid created logical time")
        unix_time = message.get("created_at")
        if (
            isinstance(unix_time, bool)
            or not isinstance(unix_time, int)
            or not 0 <= unix_time <= _MAX_SIGNED_64
        ):
            raise ValueError("trace message has invalid unix time")

        amounts: dict[str, str] = {}
        for provider_field, output_field in (
            ("value", "value_nanoton"),
            ("fwd_fee", "forward_fee_nanoton"),
            ("ihr_fee", "ihr_fee_nanoton"),
            ("import_fee", "import_fee_nanoton"),
        ):
            amount = cls._strict_nonnegative_integer_string(
                message.get(provider_field)
            )
            if amount is None:
                raise ValueError(
                    f"trace message has invalid {provider_field}"
                )
            amounts[output_field] = amount

        flags: dict[str, bool] = {}
        for field in ("ihr_disabled", "bounce", "bounced"):
            flag = message.get(field)
            if not isinstance(flag, bool):
                raise ValueError(f"trace message {field} must be boolean")
            flags[field] = flag

        observation_identity_key = "|".join(
            (
                _TRACE_MESSAGE_OBSERVATION_VERSION,
                network,
                root_transaction_hash,
                str(preorder_index),
                role,
                str(ordinal),
                message_hash,
            )
        )
        return {
            "role": role,
            "ordinal": ordinal,
            "message_hash": message_hash,
            "message_type": message_type,
            **accounts,
            "created_logical_time": created_logical_time,
            "unix_time": unix_time,
            **amounts,
            **flags,
            "observation_identity_key": observation_identity_key,
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
            for action_index, action in enumerate(actions):
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
                        action_index,
                    )
                )
        return transfers

    @classmethod
    def normalize_account_events_page_response(cls, payload: Any) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("response must be an object")
        events = payload.get("events")
        if not isinstance(events, list):
            raise ValueError("events must be a list")
        if "next_from" not in payload:
            raise ValueError("event page is missing next_from")

        normalized_events: list[dict] = []
        seen_event_ids: set[str] = set()
        for index, event in enumerate(events):
            if not isinstance(event, dict):
                raise ValueError(f"event {index} must be an object")
            event_id = event.get("event_id")
            if (
                not isinstance(event_id, str)
                or event_id != event_id.strip()
                or _TRANSACTION_HASH_RE.fullmatch(event_id) is None
            ):
                raise ValueError(
                    f"event {index} has invalid canonical event_id"
                )
            canonical_event_id = event_id.lower()
            if canonical_event_id in seen_event_ids:
                raise ValueError(
                    f"event {index} reuses an event_id inside one page"
                )
            seen_event_ids.add(canonical_event_id)
            logical_time = cls._strict_logical_time(event.get("lt"))
            if logical_time is None:
                raise ValueError(f"event {index} has invalid logical time")
            timestamp = cls._strict_event_date(event.get("timestamp"))
            if timestamp is None:
                raise ValueError(f"event {index} has invalid timestamp")
            actions = event.get("actions")
            if not isinstance(actions, list) or any(
                not isinstance(action, dict)
                or not isinstance(action.get("type"), str)
                or not action["type"].strip()
                for action in actions
            ):
                raise ValueError(f"event {index} has invalid actions")
            in_progress = event.get("in_progress")
            if not isinstance(in_progress, bool):
                raise ValueError(f"event {index} has invalid in_progress state")
            normalized = dict(event)
            normalized["event_id"] = event_id
            normalized["lt"] = logical_time
            normalized["timestamp"] = timestamp
            normalized["actions"] = actions
            normalized["in_progress"] = in_progress
            normalized_events.append(normalized)

        raw_next = payload.get("next_from")
        terminal_zero = (
            raw_next is None
            or (type(raw_next) is int and raw_next == 0)
            or (type(raw_next) is str and raw_next == "0")
        )
        if not normalized_events and terminal_zero:
            next_before_lt = None
        else:
            next_before_lt = cls._strict_logical_time(raw_next)
            if next_before_lt is None:
                raise ValueError("event page has invalid next_from")
        return {
            "events": normalized_events,
            "next_before_lt": next_before_lt,
        }

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
        action_index: int,
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
            "action_index": action_index,
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
            for action_index, action in enumerate(actions):
                if not isinstance(action, dict):
                    continue
                if cls._optional_string(action.get("type")) != "JettonSwap":
                    continue
                detail = action.get("JettonSwap")
                if not isinstance(detail, dict):
                    continue
                swaps.append(
                    cls.normalize_swap(
                        detail,
                        action,
                        event_id,
                        utime,
                        lt,
                        action_index,
                    )
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
        action_index: int,
    ) -> dict:
        token_in, amount_in, decimals_in, address_in = cls._swap_side(
            detail, "in"
        )
        token_out, amount_out, decimals_out, address_out = cls._swap_side(
            detail, "out"
        )
        return {
            "event_id": event_id,
            "utime": utime,
            "lt": lt,
            "action_type": "JettonSwap",
            "action_index": action_index,
            "dex": cls._optional_string(detail.get("dex")),
            "token_in": token_in,
            "token_in_address": address_in,
            "raw_amount_in": amount_in,
            "decimals_in": decimals_in,
            "token_out": token_out,
            "token_out_address": address_out,
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
    ) -> tuple[str | None, str | None, int | None, str | None]:
        # TonAPI JettonSwap exposes ton_in/ton_out (nanoton) and
        # amount_in/amount_out (raw jetton) with jetton_master_in/out.
        # Native TON has no jetton master address.
        ton_amount = detail.get(f"ton_{side}")
        if ton_amount not in (None, ""):
            return "TON", cls._optional_string(ton_amount), 9, None
        master = detail.get(f"jetton_master_{side}")
        if not isinstance(master, dict):
            master = {}
        address = cls._optional_string(master.get("address"))
        token = cls._optional_string(master.get("symbol")) or address
        amount = cls._optional_string(detail.get(f"amount_{side}"))
        decimals = cls._optional_int(master.get("decimals"))
        return token, amount, decimals, address

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
        if isinstance(value, bool) or value is None or value == "":
            return None
        if isinstance(value, int):
            return value
        if (
            isinstance(value, str)
            and value.isascii()
            and (value == "0" or (value.isdigit() and value[0] != "0"))
        ):
            return int(value, 10)
        return None

    @staticmethod
    def _canonical_raw_account_address(value: Any) -> str | None:
        if not isinstance(value, dict):
            return None
        address = value.get("address")
        if (
            not isinstance(address, str)
            or address != address.strip()
        ):
            return None
        match = _RAW_ACCOUNT_RE.fullmatch(address)
        if match is None:
            return None
        workchain = int(match.group(1), 10)
        if not _MIN_WORKCHAIN <= workchain <= _MAX_WORKCHAIN:
            return None
        return f"{workchain}:{match.group(2).lower()}"

    @staticmethod
    def _strict_logical_time(value: Any) -> str | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            if not 1 <= value <= _MAX_LOGICAL_TIME:
                return None
            return str(value)
        if not isinstance(value, str) or _LOGICAL_TIME_RE.fullmatch(value) is None:
            return None
        parsed = int(value, 10)
        if parsed > _MAX_LOGICAL_TIME:
            return None
        return value

    @staticmethod
    def _strict_nonnegative_integer_string(value: Any) -> str | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            if 0 <= value <= _MAX_LOGICAL_TIME:
                return str(value)
            return None
        if not isinstance(value, str):
            return None
        if value == "0":
            return value
        if (
            not value.isascii()
            or not value.isdigit()
            or value[0] == "0"
            or len(value) > 20
        ):
            return None
        if int(value, 10) > _MAX_LOGICAL_TIME:
            return None
        return value

    @staticmethod
    def _strict_event_date(value: Any) -> int | None:
        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            parsed = value
        elif (
            isinstance(value, str)
            and value.isascii()
            and (value == "0" or (value.isdigit() and value[0] != "0"))
        ):
            parsed = int(value, 10)
        else:
            return None
        if not 0 <= parsed <= _MAX_EVENT_DATE:
            return None
        return parsed

    def _sanitize_diagnostic(self, value: Any) -> str | None:
        text = self._optional_string(value)
        if text is None:
            return None
        api_key = self.settings.tonapi_api_key
        if api_key:
            text = text.replace(api_key, "[redacted]")
        return text[:500]
