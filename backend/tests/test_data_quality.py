"""Tests for the data_quality block and provider status report."""

from config import ProviderResult, Settings
from services import mock_data
from services.analysis import (
    GeckoTerminalAdapter,
    _build_data_quality,
    analyze,
    get_providers_status,
)


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


def test_providers_status_shape_mock():
    ps = get_providers_status(_settings("mock"))
    assert ps["data_mode"] == "mock"
    for key in ("geckoterminal", "ton_provider", "bitquery"):
        assert set(ps[key]) == {"configured", "available", "message"}


def test_data_quality_mock_warning():
    s = _settings("mock")
    gecko_ok = ProviderResult.success({"token": {}, "pool": {}}, source="mock")
    dq = _build_data_quality(s, gecko_ok, get_providers_status(s))
    assert dq["mode"] == "mock"
    assert dq["components"] == {
        "pool_data": "mock",
        "token_data": "mock",
        "wallet_buyers": "mock",
        "wallet_balances": "mock",
        "pnl": "mock_calculated",
        "clustering": "mock_calculated",
        "common_holdings": "mock",
    }
    assert "Mock mode is active. No real on-chain wallet data is used." in dq[
        "warnings"
    ]


def test_data_quality_real_unconfigured_warnings():
    s = _settings("real")
    gecko_ok = ProviderResult.success(
        {"token": {}, "pool": {}}, source="real"
    )
    dq = _build_data_quality(s, gecko_ok, get_providers_status(s))
    assert dq["mode"] == "real"
    assert dq["components"]["pool_data"] == "real"
    assert dq["components"]["token_data"] == "real"
    assert dq["components"]["wallet_buyers"] == "mock"
    assert dq["components"]["wallet_balances"] == "mock"
    assert dq["components"]["pnl"] == "mock_calculated"
    assert dq["components"]["clustering"] == "mock_calculated"
    assert dq["components"]["common_holdings"] == "mock"
    joined = " ".join(dq["warnings"]).lower()
    assert "wallet-level analysis is still mocked in v0.2.1" in joined
    assert "ton provider is not configured" in joined
    assert "bitquery api key is missing" in joined
    # Real gecko + mocked wallets note should be present.
    assert any("wallet-level analysis" in n.lower() for n in dq["provider_notes"])


def test_data_quality_real_gecko_failure_warns():
    s = _settings("real")
    gecko_fail = ProviderResult.failure(
        "provider_error", "Could not reach GeckoTerminal.", source="real"
    )
    dq = _build_data_quality(s, gecko_fail, get_providers_status(s))
    joined = " ".join(dq["warnings"]).lower()
    assert dq["components"]["pool_data"] == "fallback_mock"
    assert dq["components"]["token_data"] == "fallback_mock"
    assert (
        "geckoterminal pool/token data could not be fetched. falling back "
        "to mock pool/token data."
    ) in joined


def test_analyze_mock_includes_data_quality_and_providers():
    result = analyze(
        "https://www.geckoterminal.com/ton/pools/EQpool",
        "24h",
        settings=_settings("mock"),
    )
    assert result["is_mock"] is True
    assert result["data_quality"]["mode"] == "mock"
    assert result["data_quality"]["components"]["wallet_buyers"] == "mock"
    assert "providers" in result
    assert result["providers"]["data_mode"] == "mock"


def test_analyze_real_success_labels_only_pool_and_token_real(monkeypatch):
    def fake_get_pool_and_token(self, pool_url):
        return ProviderResult.success(
            {
                "token": mock_data.get_token_info(),
                "pool": mock_data.get_pool_info(),
            },
            source="real",
        )

    monkeypatch.setattr(
        GeckoTerminalAdapter,
        "get_pool_and_token",
        fake_get_pool_and_token,
    )
    result = analyze(
        "https://www.geckoterminal.com/ton/pools/EQpool",
        "24h",
        settings=_settings("real"),
    )
    components = result["data_quality"]["components"]
    assert result["is_mock"] is False
    assert components["pool_data"] == "real"
    assert components["token_data"] == "real"
    assert components["wallet_buyers"] == "mock"
    assert components["wallet_balances"] == "mock"
    assert components["pnl"] == "mock_calculated"
    assert components["clustering"] == "mock_calculated"
    assert components["common_holdings"] == "mock"
    assert (
        "Real mode is enabled, but wallet-level analysis is still mocked in "
        "v0.2.1."
    ) in result["data_quality"]["warnings"]
