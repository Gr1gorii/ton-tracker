"""Tests for the GeckoTerminal adapter: URL parsing, validation, normalize."""

from config import Settings
from adapters.geckoterminal import GeckoTerminalAdapter

MOCK_SETTINGS = Settings(
    data_mode="mock",
    geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
    ton_api_base_url="",
    ton_api_key="",
    bitquery_api_url="",
    bitquery_api_key="",
)
REAL_SETTINGS = Settings(
    data_mode="real",
    geckoterminal_base_url="https://api.geckoterminal.com/api/v2",
    ton_api_base_url="",
    ton_api_key="",
    bitquery_api_url="",
    bitquery_api_key="",
)


def test_parse_pool_url_frontend_form():
    a = GeckoTerminalAdapter(MOCK_SETTINGS)
    parsed = a.parse_pool_url(
        "https://www.geckoterminal.com/ton/pools/EQCp_C-wPq2Z"
    )
    assert parsed["network"] == "ton"
    assert parsed["pool_address"] == "EQCp_C-wPq2Z"


def test_parse_pool_url_api_form():
    a = GeckoTerminalAdapter(MOCK_SETTINGS)
    parsed = a.parse_pool_url(
        "https://api.geckoterminal.com/api/v2/networks/ton/pools/EQabc123"
    )
    assert parsed["network"] == "ton"
    assert parsed["pool_address"] == "EQabc123"


def test_parse_pool_url_non_ton_network():
    a = GeckoTerminalAdapter(MOCK_SETTINGS)
    parsed = a.parse_pool_url(
        "https://www.geckoterminal.com/eth/pools/0xdeadbeef"
    )
    assert parsed["network"] == "eth"
    assert a.validate_network(parsed["network"]) is False


def test_parse_pool_url_bare_address():
    a = GeckoTerminalAdapter(MOCK_SETTINGS)
    parsed = a.parse_pool_url("EQbareaddress")
    assert parsed["pool_address"] == "EQbareaddress"


def test_validate_network():
    a = GeckoTerminalAdapter(MOCK_SETTINGS)
    assert a.validate_network("ton") is True
    assert a.validate_network("bsc") is False
    assert a.validate_network(None) is False


def test_get_pool_and_token_mock():
    a = GeckoTerminalAdapter(MOCK_SETTINGS)
    res = a.get_pool_and_token(
        "https://www.geckoterminal.com/ton/pools/EQpool"
    )
    assert res.ok is True
    assert res.source == "mock"
    assert res.data["token"]["symbol"] == "GRAM"
    assert res.data["pool"]["requested_network"] == "ton"


def test_get_pool_and_token_real_rejects_non_ton():
    a = GeckoTerminalAdapter(REAL_SETTINGS)
    res = a.get_pool_and_token(
        "https://www.geckoterminal.com/eth/pools/0xabc"
    )
    assert res.ok is False
    assert "network" in (res.message or "").lower()


def test_normalize_maps_geckoterminal_payload():
    a = GeckoTerminalAdapter(REAL_SETTINGS)
    payload = {
        "data": {
            "id": "ton_EQpool",
            "type": "pool",
            "attributes": {
                "name": "GRAM / TON",
                "address": "EQpool",
                "base_token_price_usd": "0.0125",
                "reserve_in_usd": "842300.5",
                "fdv_usd": "31250000",
                "market_cap_usd": "12480000",
                "volume_usd": {"h24": "1276400.0"},
                "pool_created_at": "2026-03-02T11:24:00Z",
            },
            "relationships": {
                "base_token": {"data": {"id": "ton_EQbase"}},
                "dex": {"data": {"id": "stonfi"}},
            },
        },
        "included": [
            {
                "id": "ton_EQbase",
                "type": "token",
                "attributes": {
                    "address": "EQbase",
                    "name": "Gram",
                    "symbol": "GRAM",
                    "decimals": 9,
                },
            },
            {"id": "stonfi", "type": "dex", "attributes": {"name": "STON.fi"}},
        ],
    }
    token, pool = a._normalize(payload, "ton", "EQpool")
    assert token["symbol"] == "GRAM"
    assert token["current_price_usd"] == 0.0125
    assert token["decimals"] == 9
    assert pool["dex"] == "STON.fi"
    assert pool["liquidity_usd"] == 842300.5
    assert pool["volume_24h_usd"] == 1276400.0
    assert pool["base_token"] == "GRAM"
    assert pool["quote_token"] == "TON"


def test_status_mock_vs_real():
    assert GeckoTerminalAdapter(MOCK_SETTINGS).status()["available"] is True
    real_status = GeckoTerminalAdapter(REAL_SETTINGS).status()
    assert real_status["configured"] is True
    assert real_status["available"] is True
