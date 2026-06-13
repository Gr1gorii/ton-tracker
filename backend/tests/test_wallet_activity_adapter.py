"""Tests for wallet activity ingestion adapter contracts."""

from __future__ import annotations

from adapters.wallet_activity import (
    MockWalletActivityAdapter,
    WalletActivityAdapterRequest,
    build_wallet_activity_adapter,
)


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
