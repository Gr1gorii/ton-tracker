"""Tests for the historical price preview (preview-only, never cost basis)."""

from __future__ import annotations

import urllib.request

import pytest
from fastapi.testclient import TestClient

from adapters.tonapi import TonapiAdapter
from config import ProviderResult
from main import app


def _client() -> TestClient:
    return TestClient(app)


def _get(token: str = "ton", start: str = "2026-06-01T00:00:00Z",
         end: str = "2026-06-04T00:00:00Z"):
    return _client().get(
        "/api/prices/historical/preview",
        params={"token": token, "start": start, "end": end},
    )


# --- Adapter normalization ----------------------------------------------------


def test_normalize_rates_chart_response_converts_points():
    points = TonapiAdapter.normalize_rates_chart_response(
        {"points": [[1780272000, 3.21], [1780358400, 3.42]]}
    )
    assert points == [
        {"timestamp": "2026-06-01T00:00:00Z", "price_usd": "3.21"},
        {"timestamp": "2026-06-02T00:00:00Z", "price_usd": "3.42"},
    ]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        {"points": "nope"},
        {"points": [[1780272000]]},
        {"points": [["when", 3.21]]},
        {"points": [[1780272000, "cheap"]]},
    ],
)
def test_normalize_rates_chart_response_rejects_malformed(payload):
    with pytest.raises(ValueError):
        TonapiAdapter.normalize_rates_chart_response(payload)


# --- Endpoint: mock mode ------------------------------------------------------


def test_mock_mode_returns_deterministic_points_without_network(monkeypatch):
    def forbidden_urlopen(*args, **kwargs):
        raise AssertionError("mock mode must not call TonAPI")

    monkeypatch.setenv("DATA_MODE", "mock")
    monkeypatch.setattr(urllib.request, "urlopen", forbidden_urlopen)

    response = _get()

    assert response.status_code == 200
    body = response.json()
    assert body["token"] == "ton"
    assert body["data_mode"] == "mock"
    assert body["source_status"] == "mock"
    assert body["is_cost_basis_source"] is False
    assert body["point_count"] == 4  # daily, inclusive bounds
    assert body["points"][0] == {
        "timestamp": "2026-06-01T00:00:00Z",
        "price_usd": "2.50",
    }
    assert body["points"][1]["price_usd"] == "2.51"
    assert "not wired into cost-basis" in body["note"]
    assert "mock" in body["message"].lower()


def test_mock_mode_jetton_uses_smaller_base_price(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    response = _get(token="EQjetton")
    assert response.status_code == 200
    assert response.json()["points"][0]["price_usd"] == "0.05"


# --- Endpoint: validation -----------------------------------------------------


def test_start_after_end_returns_400(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    response = _get(start="2026-06-05T00:00:00Z", end="2026-06-01T00:00:00Z")
    assert response.status_code == 400
    assert "before" in response.json()["detail"]


def test_window_over_cap_returns_400(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    response = _get(start="2026-01-01T00:00:00Z", end="2026-06-01T00:00:00Z")
    assert response.status_code == 400
    assert "capped" in response.json()["detail"]


def test_bad_datetime_returns_400(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "mock")
    response = _get(start="not-a-date")
    assert response.status_code == 400


def test_missing_token_returns_422():
    response = _client().get(
        "/api/prices/historical/preview",
        params={"start": "2026-06-01T00:00:00Z", "end": "2026-06-02T00:00:00Z"},
    )
    assert response.status_code == 422


# --- Endpoint: real mode ------------------------------------------------------


def test_real_mode_success_normalizes_provider_points(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)

    def fake_fetch_json(self, path, query=None):
        assert path == "/v2/rates/chart"
        assert query["token"] == "ton"
        assert query["currency"] == "usd"
        assert isinstance(query["start_date"], int)
        assert isinstance(query["end_date"], int)
        return ProviderResult.success(
            {"points": [[1780272000, 3.21]]},
            source="real",
        )

    monkeypatch.setattr(TonapiAdapter, "fetch_json", fake_fetch_json)

    response = _get()

    assert response.status_code == 200
    body = response.json()
    assert body["data_mode"] == "real"
    assert body["source_status"] == "real"
    assert body["point_count"] == 1
    assert body["points"][0] == {
        "timestamp": "2026-06-01T00:00:00Z",
        "price_usd": "3.21",
    }
    assert body["is_cost_basis_source"] is False


def test_real_mode_provider_failure_reports_unavailable_without_fallback(
    monkeypatch,
):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)

    def fake_fetch_json(self, path, query=None):
        return ProviderResult(
            ok=False,
            error="provider_error",
            message="TonAPI request failed.",
            source="real",
        )

    monkeypatch.setattr(TonapiAdapter, "fetch_json", fake_fetch_json)

    response = _get()

    assert response.status_code == 200
    body = response.json()
    assert body["source_status"] == "unavailable"
    assert body["points"] == []
    assert any("no fallback" in warning.lower() for warning in body["warnings"])


def test_real_mode_empty_points_stays_visible(monkeypatch):
    monkeypatch.setenv("DATA_MODE", "real")
    monkeypatch.setenv("TONAPI_BASE_URL", "https://tonapi.io")
    monkeypatch.delenv("TONAPI_API_KEY", raising=False)

    def fake_fetch_json(self, path, query=None):
        return ProviderResult.success({"points": []}, source="real")

    monkeypatch.setattr(TonapiAdapter, "fetch_json", fake_fetch_json)

    response = _get()

    assert response.status_code == 200
    body = response.json()
    assert body["source_status"] == "real"
    assert body["point_count"] == 0
    assert any("no points" in warning.lower() for warning in body["warnings"])
