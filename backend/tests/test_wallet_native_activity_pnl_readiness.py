"""Tests for fail-closed PnL readiness over native activity evidence."""

from schemas import WalletNativeActivityPnlReadinessResponse
import services.wallet_native_activity_pnl_readiness as readiness_service


def _dedup_result() -> dict:
    activities = [
        {"direction": "incoming", "amount_base_units": "2500000000"},
        {"direction": "outgoing", "amount_base_units": "1000000000"},
        {"direction": "self", "amount_base_units": "500000000"},
    ]
    return {
        "selected_run_ids": [1, 2],
        "dedup_digest_sha256": "11" * 32,
        "network": "ton-mainnet",
        "wallet_account_canonical": "0:" + "22" * 32,
        "source_ledger_count": 3,
        "merged_activity_count": 4,
        "deduplicated_activity_count": 3,
        "suppressed_occurrence_count": 1,
        "activities": activities,
    }


def test_readiness_reconciles_native_flows_without_inventing_pnl(monkeypatch):
    monkeypatch.setattr(
        readiness_service,
        "deduplicate_wallet_native_activity",
        lambda _target, _runs, _session: _dedup_result(),
    )

    result = readiness_service.build_native_activity_pnl_readiness(
        2, [2, 1], None
    )

    assert result["flow_summary"] == {
        "asset_identity_key": "ton_native_asset_v1|ton-mainnet",
        "activity_count": 3,
        "incoming_activity_count": 1,
        "outgoing_activity_count": 1,
        "self_activity_count": 1,
        "incoming_nanoton": "2500000000",
        "outgoing_nanoton": "1000000000",
        "self_nanoton": "500000000",
        "net_nanoton": "1500000000",
        "incoming_ton": "2.5",
        "outgoing_ton": "1",
        "self_ton": "0.5",
        "net_ton": "1.5",
    }
    assert result["native_activity_used_by_pnl_readiness"] is True
    assert result["native_activity_used_by_pnl_calculation"] is False
    assert result["eligible_for_cost_basis"] is False
    assert result["is_real_pnl"] is False
    assert result["real_pnl_locked"] is True
    assert result["blocked_requirement_codes"] == [
        "complete_wallet_history",
        "authoritative_trade_semantics",
        "jetton_asset_identity",
        "historical_trade_prices",
        "transaction_fee_linkage",
        "acquisition_cost_basis",
    ]
    WalletNativeActivityPnlReadinessResponse.model_validate(result)


def test_readiness_digest_is_stable(monkeypatch):
    monkeypatch.setattr(
        readiness_service,
        "deduplicate_wallet_native_activity",
        lambda _target, _runs, _session: _dedup_result(),
    )

    first = readiness_service.build_native_activity_pnl_readiness(2, [1, 2], None)
    second = readiness_service.build_native_activity_pnl_readiness(2, [2, 1], None)

    assert first["analysis_digest_sha256"] == second["analysis_digest_sha256"]
