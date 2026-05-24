"""Tests for the data_quality block and provider status report."""

from config import ProviderResult, Settings
from services.analysis import (
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
    assert any("mock mode" in w.lower() for w in dq["warnings"])


def test_data_quality_real_unconfigured_warnings():
    s = _settings("real")
    gecko_ok = ProviderResult.success(
        {"token": {}, "pool": {}}, source="real"
    )
    dq = _build_data_quality(s, gecko_ok, get_providers_status(s))
    assert dq["mode"] == "real"
    joined = " ".join(dq["warnings"]).lower()
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
    assert "geckoterminal" in joined


def test_analyze_mock_includes_data_quality_and_providers():
    result = analyze(
        "https://www.geckoterminal.com/ton/pools/EQpool",
        "24h",
        settings=_settings("mock"),
    )
    assert result["is_mock"] is True
    assert result["data_quality"]["mode"] == "mock"
    assert "providers" in result
    assert result["providers"]["data_mode"] == "mock"
