"""Tests for the two-source asset pricing service."""

from __future__ import annotations

from config import ProviderResult
from services.pricing import price_assets


def test_price_assets_uses_tonapi_then_geckoterminal(monkeypatch):
    def fake_rates(self, tokens, currency="usd"):
        return ProviderResult.success(
            {
                "rates": {"TON": "5.60", "EQalpha": "0.25"},
                "currency": "usd",
                "source": "tonapi",
            },
            source="real",
        )

    def fake_gecko(self, token_address, network="ton"):
        price = "1.10" if token_address == "EQbeta" else None
        return ProviderResult.success(
            {"token_address": token_address, "price_usd": price},
            source="real",
        )

    monkeypatch.setattr(
        "adapters.tonapi.TonapiAdapter.get_rates_preview", fake_rates
    )
    monkeypatch.setattr(
        "adapters.geckoterminal.GeckoTerminalAdapter.get_token_price",
        fake_gecko,
    )

    result = price_assets(
        [
            {"asset": "TON", "token": "ton"},
            {"asset": "ALPHA", "token": "EQalpha"},
            {"asset": "BETA", "token": "EQbeta"},
            {"asset": "GAMMA", "token": None},
        ]
    )

    by_asset = {item["asset"]: item for item in result["prices"]}
    assert by_asset["TON"]["price_usd"] == "5.60"
    assert by_asset["TON"]["priced_by"] == "tonapi"
    assert by_asset["ALPHA"]["price_usd"] == "0.25"
    assert by_asset["ALPHA"]["priced_by"] == "tonapi"
    assert by_asset["BETA"]["price_usd"] == "1.10"
    assert by_asset["BETA"]["priced_by"] == "geckoterminal"
    assert by_asset["GAMMA"]["price_usd"] is None
    assert by_asset["GAMMA"]["priced_by"] is None
    assert result["unpriced"] == ["GAMMA"]
    assert result["currency"] == "usd"


def test_price_assets_mock_mode_is_unpriced_without_network(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")

    result = price_assets(
        [
            {"asset": "TON", "token": "ton"},
            {"asset": "ALPHA", "token": "EQalpha"},
        ]
    )

    assert result["unpriced"] == ["TON", "ALPHA"]
    assert all(item["price_usd"] is None for item in result["prices"])
