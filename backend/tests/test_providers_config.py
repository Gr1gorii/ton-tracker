"""Tests for provider mode config and missing-API-key handling."""

from datetime import datetime, timezone

from config import (
    DEFAULT_TONAPI_BASE_URL,
    DEFAULT_TONAPI_TESTNET_BASE_URL,
    ERROR_PROVIDER_NOT_CONFIGURED,
    Settings,
    get_settings,
)
from adapters.bitquery import BitqueryAdapter
from adapters.ton_provider import TonProviderAdapter

NOW = datetime.now(timezone.utc)


def _settings(mode, **kw):
    base = dict(
        data_mode=mode,
        geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
        ton_api_base_url="",
        ton_api_key="",
        bitquery_api_url="",
        bitquery_api_key="",
    )
    base.update(kw)
    return Settings(**base)


def test_default_mode_is_mock(monkeypatch):
    monkeypatch.delenv("DATA_MODE", raising=False)
    assert get_settings().data_mode == "mock"


def test_data_mode_real_from_env(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    s = get_settings()
    assert s.data_mode == "real"
    assert s.is_real is True
    assert s.is_mock is False


def test_invalid_mode_falls_back_to_mock(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "banana")
    assert get_settings().data_mode == "mock"


def test_wallet_activity_live_guard_env(monkeypatch):
    monkeypatch.setenv("WALLET_ACTIVITY_PROVIDER", "tonapi")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_ENABLED", "true")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_JETTON_LIMIT", "999")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_TX_MAX_PAGES", "999")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_EVENT_LIMIT", "999")
    monkeypatch.setenv("WALLET_ACTIVITY_LIVE_EVENT_MAX_PAGES", "999")

    settings = get_settings()

    assert settings.wallet_activity_provider == "tonapi"
    assert settings.wallet_activity_live_enabled is True
    assert settings.wallet_activity_live_jetton_limit == 500
    assert settings.wallet_activity_live_tx_max_pages == 100
    assert settings.wallet_activity_live_event_limit == 100
    assert settings.wallet_activity_live_event_max_pages == 100


def test_ton_network_scope_from_env(monkeypatch):
    monkeypatch.delenv("TONAPI_BASE_URL", raising=False)
    monkeypatch.setenv("TON_NETWORK", "testnet")
    settings = get_settings()
    assert settings.ton_network == "testnet"
    assert settings.tonapi_base_url == DEFAULT_TONAPI_TESTNET_BASE_URL


def test_invalid_ton_network_falls_back_to_mainnet(monkeypatch):
    monkeypatch.delenv("TONAPI_BASE_URL", raising=False)
    monkeypatch.setenv("TON_NETWORK", "not-a-network")
    settings = get_settings()
    assert settings.ton_network == "mainnet"
    assert settings.tonapi_base_url == DEFAULT_TONAPI_BASE_URL


def test_explicit_tonapi_base_url_is_preserved_for_custom_gateway(monkeypatch):
    monkeypatch.setenv("TON_NETWORK", "testnet")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.internal.example")
    assert get_settings().tonapi_base_url == "https://tonapi.internal.example"


def test_ton_real_missing_config_returns_not_configured():
    ton = TonProviderAdapter(_settings("real"))
    assert ton.is_configured() is False
    res = ton.get_wallet_ton_balance("EQx")
    assert res.ok is False
    assert res.error == ERROR_PROVIDER_NOT_CONFIGURED


def test_ton_configured_detection():
    ton = TonProviderAdapter(
        _settings("real", ton_api_base_url="https://tonapi.io", ton_api_key="k")
    )
    assert ton.is_configured() is True
    # Configured but real fetch not implemented in v0.2.
    res = ton.get_wallet_ton_balance("EQx")
    assert res.ok is False
    assert res.error == "real_not_implemented"


def test_bitquery_real_missing_key_returns_not_configured():
    bq = BitqueryAdapter(_settings("real"))
    assert bq.is_configured() is False
    res = bq.get_token_trades("EQtok", NOW, NOW)
    assert res.ok is False
    assert res.error == ERROR_PROVIDER_NOT_CONFIGURED


def test_bitquery_mock_returns_trades():
    bq = BitqueryAdapter(_settings("mock"))
    res = bq.get_token_trades("EQtok", NOW, NOW)
    assert res.ok is True
    assert res.source == "mock"
    assert len(res.data) > 0
    trade = res.data[0]
    assert trade["side"] in ("buy", "sell")
    assert "amount_usd" in trade


def test_ton_mock_balance():
    ton = TonProviderAdapter(_settings("mock"))
    # Use a real mock wallet address.
    from services import mock_data

    addr = mock_data.WALLETS[0]["address"]
    res = ton.get_wallet_ton_balance(addr)
    assert res.ok is True
    assert res.data["ton_balance"] == float(mock_data.WALLETS[0]["ton_balance"])


def test_normalize_balance_nanotons():
    ton = TonProviderAdapter(_settings("mock"))
    norm = ton.normalize_balance({"balance": 5_200_000_000, "address": "EQx"})
    assert norm["ton_balance"] == 5.2
    assert norm["address"] == "EQx"
