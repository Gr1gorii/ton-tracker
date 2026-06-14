"""Tests for wallet activity ingestion adapter contracts."""

from __future__ import annotations

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
) -> WalletActivityAdapterRequest:
    return WalletActivityAdapterRequest(
        wallet_address="EQwallet",
        time_window="24h",
        custom_start=None,
        custom_end=None,
        surfaces=surfaces
        or ["transfers", "transactions", "swaps", "balances", "jettons"],
        environment_data_mode=environment_data_mode,
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

    result = adapter.ingest(_request(["jettons", "transfers"], "real"))

    assert result.status == "partial"
    assert result.data_mode == "real"
    assert result.unavailable_surfaces == ["transfers"]
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
    assert any("non-jetton surfaces" in warning.message for warning in result.warnings)


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
    assert any("TonAPI provider warning" in warning.message for warning in result.warnings)


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
    assert "jetton balance snapshots" in status["message"]


def test_wallet_activity_provider_status_rejects_unknown_provider():
    status = get_wallet_activity_provider_status(_settings("real", "banana"))

    assert status["configured"] is False
    assert status["available"] is False
    assert "unsupported" in status["message"]
