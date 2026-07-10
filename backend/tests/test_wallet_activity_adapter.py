"""Tests for wallet activity ingestion adapter contracts."""

from __future__ import annotations

from datetime import datetime, timezone

from adapters.wallet_activity import (
    BitqueryWalletActivityScaffoldAdapter,
    MockWalletActivityAdapter,
    TonapiWalletActivityLiveAdapter,
    TonapiWalletActivityScaffoldAdapter,
    WalletActivityAdapterRequest,
    build_wallet_activity_adapter,
    get_wallet_activity_provider_status,
)
from config import (
    DEFAULT_STONFI_BASE_URL,
    DEFAULT_TONAPI_BASE_URL,
    ProviderResult,
    Settings,
)


def _settings(
    mode: str = "mock",
    provider: str = "mock",
    **kw,
) -> Settings:
    base = dict(
        data_mode=mode,
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        ton_api_base_url="https://tonapi.io",
        ton_api_key="ton-key",
        bitquery_api_url="https://graphql.bitquery.io",
        bitquery_api_key="bitquery-key",
        stonfi_base_url=DEFAULT_STONFI_BASE_URL,
        tonapi_base_url=DEFAULT_TONAPI_BASE_URL,
        tonapi_api_key="",
        wallet_activity_provider=provider,
        wallet_activity_live_enabled=False,
        wallet_activity_live_jetton_limit=100,
    )
    base.update(kw)
    return Settings(**base)


def _request(
    surfaces=None,
    environment_data_mode: str = "mock",
    *,
    bounded: bool = False,
) -> WalletActivityAdapterRequest:
    resolved_start = (
        datetime(2024, 6, 1, tzinfo=timezone.utc) if bounded else None
    )
    resolved_end = (
        datetime(2024, 6, 2, tzinfo=timezone.utc) if bounded else None
    )
    return WalletActivityAdapterRequest(
        wallet_address="EQwallet",
        time_window="custom" if bounded else "24h",
        custom_start="2024-06-01T00:00:00Z" if bounded else None,
        custom_end="2024-06-02T00:00:00Z" if bounded else None,
        surfaces=surfaces
        or ["transfers", "transactions", "swaps", "balances", "jettons"],
        environment_data_mode=environment_data_mode,
        resolved_start=resolved_start,
        resolved_end=resolved_end,
    )


def _event_page(
    account_address: str,
    limit: int,
    before_lt: str | None,
    start_date: int | None,
    end_date: int | None,
    events: list[dict],
) -> ProviderResult:
    logical_times = [int(event["lt"], 10) for event in events]
    minimum = str(min(logical_times)) if logical_times else None
    maximum = str(max(logical_times)) if logical_times else None
    return ProviderResult.success(
        {
            "wallet_address": account_address,
            "requested_limit": limit,
            "request_before_lt": before_lt,
            "request_start_date": start_date,
            "request_end_date": end_date,
            "raw_count": len(events),
            "min_logical_time": minimum,
            "max_logical_time": maximum,
            "next_before_lt": minimum,
            "events": events,
        },
        source="real",
        message="TonAPI account event page fetched for display evidence.",
    )


def test_mock_wallet_activity_adapter_preview_reports_coverage_without_rows():
    adapter = MockWalletActivityAdapter()

    result = adapter.preview(_request(["transfers", "swaps", "jettons"]))

    assert result.status == "success"
    assert result.data_mode == "mock"
    assert result.requested_surfaces == ["transfers", "swaps", "jettons"]
    assert result.unavailable_surfaces == []
    assert result.transfers == []
    assert result.transactions == []
    assert result.swaps == []
    assert result.balances == []

    evidence = result.provider_evidence[0]
    assert evidence.provider == "mock_wallet_activity"
    assert evidence.source_status == "mock"
    assert evidence.raw_count == 6
    assert evidence.normalized_count == 6
    assert evidence.to_public_dict()["data_mode"] == "mock"


def test_mock_wallet_activity_adapter_ingest_respects_requested_surfaces():
    adapter = MockWalletActivityAdapter()

    result = adapter.ingest(_request(["balances"]))

    assert result.status == "success"
    assert result.requested_surfaces == ["balances"]
    assert result.transfers == []
    assert result.transactions == []
    assert result.swaps == []
    assert [item.asset for item in result.balances] == ["TON"]
    assert result.provider_evidence[0].normalized_count == 1


def test_mock_wallet_activity_adapter_real_mode_is_still_data_honest():
    adapter = MockWalletActivityAdapter()

    result = adapter.preview(
        _request(
            ["transfers"],
            environment_data_mode="real",
        )
    )

    assert result.data_mode == "mock"
    assert result.provider_evidence[0].data_mode == "mock"
    assert result.provider_evidence[0].source_status == "mock"
    assert any("DATA_MODE=real" in warning.message for warning in result.warnings)
    assert "No real provider calls" in result.message


def test_wallet_activity_adapter_factory_returns_mock_adapter():
    adapter = build_wallet_activity_adapter()

    assert isinstance(adapter, MockWalletActivityAdapter)
    assert adapter.provider_name == "mock_wallet_activity"


def test_wallet_activity_adapter_factory_defaults_real_mode_to_mock_adapter():
    adapter = build_wallet_activity_adapter(_settings("real"))

    assert isinstance(adapter, MockWalletActivityAdapter)


def test_wallet_activity_adapter_factory_routes_explicit_tonapi_scaffold():
    adapter = build_wallet_activity_adapter(_settings("real", "tonapi"))

    assert isinstance(adapter, TonapiWalletActivityScaffoldAdapter)

    result = adapter.preview(_request(["jettons", "swaps"], "real"))

    assert result.status == "partial"
    assert result.data_mode == "real"
    assert result.provider_evidence[0].provider == "tonapi_wallet_activity_scaffold"
    assert result.provider_evidence[0].source_status == "limited"
    assert result.provider_evidence[0].raw_count == 0
    assert result.provider_evidence[0].normalized_count == 0
    assert result.unavailable_surfaces == ["jettons", "swaps"]
    assert result.transfers == []
    assert result.swaps == []
    assert "No real wallet activity provider calls" in result.message
    assert any("scaffold-only" in warning.message for warning in result.warnings)


def test_wallet_activity_adapter_factory_routes_guarded_tonapi_live_adapter():
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    assert isinstance(adapter, TonapiWalletActivityLiveAdapter)


def test_guarded_tonapi_live_adapter_ingests_jetton_snapshots(monkeypatch):
    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "jettons": [
                    {
                        "jetton_address": "EQjetton",
                        "jetton_name": "Example Jetton",
                        "jetton_symbol": "EJT",
                        "balance": "123450000",
                        "decimals": 6,
                        "price_usd": "0.25",
                        "wallet_contract_address": "EQjettonWallet",
                        "source": "tonapi",
                    }
                ],
                "preview_count": 1,
                "total_jettons": 1,
            },
            source="real",
            message="TonAPI account jettons preview fetched.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["jettons"], "real"))

    assert result.status == "success"
    assert result.data_mode == "real"
    assert result.unavailable_surfaces == []
    assert result.provider_evidence[0].provider == "tonapi_wallet_activity_live"
    assert result.provider_evidence[0].source_status == "live"
    assert result.provider_evidence[0].raw_count == 1
    assert result.provider_evidence[0].normalized_count == 1
    assert result.balances[0].asset == "EJT"
    assert result.balances[0].balance == "123.450000000000000000"
    assert result.balances[0].balance_usd == "30.86250000"
    assert result.balances[0].provider == "tonapi"
    assert result.balances[0].source_status == "live"
    assert result.transfers == []
    assert any(
        "shared bounded account-event stream" in warning.message
        for warning in result.warnings
    )


def test_guarded_tonapi_live_adapter_ingests_native_and_jetton_balances(
    monkeypatch,
):
    def fake_get_account_balance_preview(self, account_address):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "balance": {
                    "wallet_address": account_address,
                    "asset": "TON",
                    "balance": "2500000000",
                    "decimals": 9,
                    "account_status": "active",
                    "is_scam": False,
                    "source": "tonapi",
                },
            },
            source="real",
            message="TonAPI account native TON balance fetched.",
        )

    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "jettons": [
                    {
                        "jetton_address": "EQjetton",
                        "jetton_name": "Example Jetton",
                        "jetton_symbol": "EJT",
                        "balance": "123450000",
                        "decimals": 6,
                        "price_usd": "0.25",
                        "wallet_contract_address": "EQjettonWallet",
                        "source": "tonapi",
                    }
                ],
                "preview_count": 1,
                "total_jettons": 1,
            },
            source="real",
            message="TonAPI account jettons preview fetched.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_balance_preview",
        fake_get_account_balance_preview,
    )
    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["balances", "jettons"], "real"))

    assert result.status == "success"
    assert result.unavailable_surfaces == []
    assert result.provider_evidence[0].source_status == "live"
    assert result.provider_evidence[0].raw_count == 2
    assert result.provider_evidence[0].normalized_count == 2
    assert [item.asset for item in result.balances] == ["TON", "EJT"]
    assert result.balances[0].balance == "2.500000000000000000"
    assert result.balances[0].balance_usd is None
    assert result.balances[0].raw["surface"] == "balances"
    assert result.balances[1].balance == "123.450000000000000000"


def test_guarded_tonapi_live_adapter_error_returns_no_rows(monkeypatch):
    def fake_get_account_jettons_preview(self, account_address, limit):
        return ProviderResult.failure(
            "provider_error",
            "TonAPI network error: timeout.",
            source="real",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_jettons_preview",
        fake_get_account_jettons_preview,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["jettons"], "real"))

    assert result.status == "error"
    assert result.provider_evidence[0].source_status == "error"
    assert result.provider_evidence[0].normalized_count == 0
    assert result.balances == []
    assert result.unavailable_surfaces == ["jettons"]
    assert any(
        "TonAPI jetton balance warning" in warning.message
        for warning in result.warnings
    )


def test_guarded_tonapi_live_adapter_ingests_transaction_history(monkeypatch):
    def fake_get_account_transactions_preview(self, account_address, limit):
        return ProviderResult.success(
            {
                "wallet_address": account_address,
                "transactions": [
                    {
                        "tx_hash": "abc123",
                        "logical_time": "46000000000001",
                        "utime": 1717236000,
                        "total_fees": "4200000",
                        "success": True,
                        "transaction_type": "TransOrd",
                        "source": "tonapi",
                    },
                    {
                        "tx_hash": "def456",
                        "logical_time": "46000000000000",
                        "utime": 1717235000,
                        "total_fees": "0",
                        "success": False,
                        "source": "tonapi",
                    },
                ],
                "preview_count": 2,
                "total_transactions": 2,
            },
            source="real",
            message="TonAPI account transaction history fetched.",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_transactions_preview",
        fake_get_account_transactions_preview,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["transactions"], "real"))

    assert result.status == "success"
    assert result.data_mode == "real"
    assert result.unavailable_surfaces == []
    assert result.provider_evidence[0].provider == "tonapi_wallet_activity_live"
    assert result.provider_evidence[0].source_status == "live"
    assert result.provider_evidence[0].raw_count == 2
    assert result.provider_evidence[0].normalized_count == 2
    assert result.balances == []
    assert [tx.tx_hash for tx in result.transactions] == ["abc123", "def456"]
    assert result.transactions[0].fee_ton == "0.004200000000000000"
    assert result.transactions[0].success == "success"
    assert result.transactions[0].timestamp == "2024-06-01T10:00:00+00:00"
    assert result.transactions[0].provider == "tonapi"
    assert result.transactions[0].source_status == "live"
    assert result.transactions[0].raw["surface"] == "transactions"
    assert result.transactions[1].success == "failed"
    assert any(
        "mutable display-oriented interpretations" in warning.message
        for warning in result.warnings
    )


def test_guarded_tonapi_live_adapter_transactions_error_returns_no_rows(monkeypatch):
    def fake_get_account_transactions_preview(self, account_address, limit):
        return ProviderResult.failure(
            "provider_error",
            "TonAPI network error: timeout.",
            source="real",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_transactions_preview",
        fake_get_account_transactions_preview,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["transactions"], "real"))

    assert result.status == "error"
    assert result.provider_evidence[0].source_status == "error"
    assert result.provider_evidence[0].normalized_count == 0
    assert result.transactions == []
    assert result.unavailable_surfaces == ["transactions"]
    assert any(
        "TonAPI transaction-history warning" in warning.message
        for warning in result.warnings
    )


def test_guarded_tonapi_live_adapter_ingests_transfer_history(monkeypatch):
    calls: list[str | None] = []
    event = {
        "event_id": "11" * 32,
        "timestamp": 1717236000,
        "lt": "46000000000001",
        "in_progress": False,
        "actions": [
            {
                "type": "TonTransfer",
                "status": "ok",
                "TonTransfer": {
                    "amount": "2500000000",
                    "sender": {"address": "EQwallet"},
                    "recipient": {"address": "EQdest"},
                },
            },
            {
                "type": "JettonTransfer",
                "status": "ok",
                "JettonTransfer": {
                    "amount": "123450000",
                    "sender": {"address": "EQsource"},
                    "recipient": {"address": "EQwallet"},
                    "jetton": {
                        "address": "EQjetton",
                        "symbol": "EJT",
                        "decimals": 6,
                    },
                },
            },
        ],
    }

    def fake_get_account_events_page(
        self,
        account_address,
        limit,
        before_lt=None,
        start_date=None,
        end_date=None,
    ):
        calls.append(before_lt)
        assert (start_date, end_date) == (1717200000, 1717286400)
        rows = [event] if before_lt is None else []
        return _event_page(
            account_address,
            limit,
            before_lt,
            start_date,
            end_date,
            rows,
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_events_page",
        fake_get_account_events_page,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["transfers"], "real", bounded=True))

    assert calls == [None, "46000000000001"]
    assert result.status == "partial"
    assert result.data_mode == "real"
    assert result.unavailable_surfaces == []
    assert result.incomplete_surfaces == ["transfers"]
    assert result.provider_evidence[0].provider == "tonapi_wallet_activity_live"
    assert result.provider_evidence[0].source_status == "limited"
    assert result.provider_evidence[0].raw_count == 1
    assert result.provider_evidence[0].normalized_count == 2
    assert len(result.acquisition_streams) == 1
    stream = result.acquisition_streams[0]
    assert stream.stream_key == "account_events"
    assert stream.completion_state == "complete"
    assert stream.termination_reason == "provider_terminal"
    assert stream.bounds_verified is True
    assert len(stream.pages) == 2
    assert result.balances == []
    assert [t.asset for t in result.transfers] == ["TON", "EJT"]
    assert result.transfers[0].direction == "out"
    assert result.transfers[0].amount == "2.500000000000000000"
    assert result.transfers[0].counterparty == "EQdest"
    assert result.transfers[0].provider == "tonapi"
    assert result.transfers[0].source_status == "live"
    assert result.transfers[0].raw["surface"] == "transfers"
    assert result.transfers[1].direction == "in"
    assert result.transfers[1].asset == "EJT"
    assert result.transfers[1].amount == "123.450000000000000000"
    assert any(
        "display stream" in warning.message
        for warning in result.warnings
    )


def test_guarded_tonapi_live_adapter_transfers_error_returns_no_rows(monkeypatch):
    def fake_get_account_events_page(
        self,
        account_address,
        limit,
        before_lt=None,
        start_date=None,
        end_date=None,
    ):
        return ProviderResult.failure(
            "provider_error",
            "TonAPI network error: timeout.",
            source="real",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_events_page",
        fake_get_account_events_page,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["transfers"], "real", bounded=True))

    assert result.status == "error"
    assert result.provider_evidence[0].source_status == "error"
    assert result.provider_evidence[0].normalized_count == 0
    assert result.transfers == []
    assert result.unavailable_surfaces == ["transfers"]
    assert result.incomplete_surfaces == ["transfers"]
    assert len(result.acquisition_streams) == 1
    assert result.acquisition_streams[0].stream_key == "account_events"
    assert result.acquisition_streams[0].completion_state == "error"
    assert any(
        "account event pagination is incomplete" in warning.message
        for warning in result.warnings
    )


def test_guarded_tonapi_live_adapter_ingests_dex_swaps(monkeypatch):
    calls: list[str | None] = []
    event = {
        "event_id": "22" * 32,
        "timestamp": 1717236000,
        "lt": "46000000000002",
        "in_progress": False,
        "actions": [
            {
                "type": "JettonSwap",
                "status": "ok",
                "JettonSwap": {
                    "dex": "stonfi",
                    "ton_in": "5000000000",
                    "amount_out": "123450000",
                    "jetton_master_out": {
                        "address": "EQjetton",
                        "symbol": "EJT",
                        "decimals": 6,
                    },
                    "router": {"address": "EQrouter"},
                },
            }
        ],
    }

    def fake_get_account_events_page(
        self,
        account_address,
        limit,
        before_lt=None,
        start_date=None,
        end_date=None,
    ):
        calls.append(before_lt)
        assert (start_date, end_date) == (1717200000, 1717286400)
        rows = [event] if before_lt is None else []
        return _event_page(
            account_address,
            limit,
            before_lt,
            start_date,
            end_date,
            rows,
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_events_page",
        fake_get_account_events_page,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["swaps"], "real", bounded=True))

    assert calls == [None, "46000000000002"]
    assert result.status == "partial"
    assert result.data_mode == "real"
    assert result.unavailable_surfaces == []
    assert result.incomplete_surfaces == ["swaps"]
    assert result.provider_evidence[0].source_status == "limited"
    assert result.provider_evidence[0].raw_count == 1
    assert result.provider_evidence[0].normalized_count == 1
    assert len(result.acquisition_streams) == 1
    stream = result.acquisition_streams[0]
    assert stream.stream_key == "account_events"
    assert stream.completion_state == "complete"
    assert stream.termination_reason == "provider_terminal"
    assert stream.bounds_verified is True
    assert len(stream.pages) == 2
    assert len(result.swaps) == 1
    swap = result.swaps[0]
    assert swap.dex == "stonfi"
    assert swap.token_in == "TON"
    assert swap.amount_in == "5.000000000000000000"
    assert swap.token_out == "EJT"
    assert swap.amount_out == "123.450000000000000000"
    assert swap.estimated_usd is None
    assert swap.provider == "tonapi"
    assert swap.source_status == "live"
    assert swap.raw["surface"] == "swaps"
    assert any(
        "display stream" in warning.message
        for warning in result.warnings
    )


def test_guarded_tonapi_live_adapter_swaps_error_returns_no_rows(monkeypatch):
    def fake_get_account_events_page(
        self,
        account_address,
        limit,
        before_lt=None,
        start_date=None,
        end_date=None,
    ):
        return ProviderResult.failure(
            "provider_error",
            "TonAPI network error: timeout.",
            source="real",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_account_events_page",
        fake_get_account_events_page,
    )
    adapter = build_wallet_activity_adapter(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    result = adapter.ingest(_request(["swaps"], "real", bounded=True))

    assert result.status == "error"
    assert result.provider_evidence[0].source_status == "error"
    assert result.provider_evidence[0].normalized_count == 0
    assert result.swaps == []
    assert result.unavailable_surfaces == ["swaps"]
    assert result.incomplete_surfaces == ["swaps"]
    assert len(result.acquisition_streams) == 1
    assert result.acquisition_streams[0].stream_key == "account_events"
    assert result.acquisition_streams[0].completion_state == "error"
    assert any(
        "account event pagination is incomplete" in warning.message
        for warning in result.warnings
    )


def test_wallet_activity_scaffold_missing_config_is_unavailable():
    adapter = build_wallet_activity_adapter(
        _settings("real", "bitquery", bitquery_api_key="")
    )

    assert isinstance(adapter, BitqueryWalletActivityScaffoldAdapter)

    result = adapter.ingest(_request(["swaps"], "real"))

    assert result.status == "error"
    assert result.provider_evidence[0].source_status == "unavailable"
    assert result.unavailable_surfaces == ["swaps"]
    assert result.swaps == []
    assert any("BITQUERY_API_KEY" in warning.message for warning in result.warnings)


def test_wallet_activity_provider_status_reports_mock_default():
    status = get_wallet_activity_provider_status(_settings("mock"))

    assert status["configured"] is True
    assert status["available"] is True
    assert "deterministic mock adapter" in status["message"]


def test_wallet_activity_provider_status_reports_real_scaffold_limited():
    status = get_wallet_activity_provider_status(_settings("real", "stonfi"))

    assert status["configured"] is True
    assert status["available"] is False
    assert "STON.fi wallet activity scaffold" in status["message"]
    assert "live wallet activity calls are disabled" in status["message"]


def test_wallet_activity_provider_status_reports_guarded_tonapi_live():
    status = get_wallet_activity_provider_status(
        _settings("real", "tonapi", wallet_activity_live_enabled=True)
    )

    assert status["configured"] is True
    assert status["available"] is True
    assert "guarded live TonAPI" in status["message"]
    assert "Native TON balance" in status["message"]
    assert "jetton balance snapshots" in status["message"]


def test_wallet_activity_provider_status_rejects_unknown_provider():
    status = get_wallet_activity_provider_status(_settings("real", "banana"))

    assert status["configured"] is False
    assert status["available"] is False
    assert "unsupported" in status["message"]
