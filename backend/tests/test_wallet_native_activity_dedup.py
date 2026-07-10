"""Tests for canonical cross-run native activity deduplication."""

import pytest

from schemas import WalletNativeActivityDedupResponse
import services.wallet_native_activity_dedup as dedup_service


ACCOUNT = "0:" + "11" * 32
COUNTERPARTY = "0:" + "22" * 32
ACTIVITY_IDENTITY = "33" * 32


def _activity(*, run_id: int, ledger_id: str, merge_index: int) -> dict:
    return {
        "source_run_id": run_id,
        "source_ledger_id": ledger_id,
        "merge_index": merge_index,
        "ordinal": 0,
        "activity_identity_key": ACTIVITY_IDENTITY,
        "source_flow_observation_identity": "44" * 32,
        "transaction_hash": "55" * 32,
        "message_hash": "66" * 32,
        "direction": "outgoing",
        "activity_kind": "native_ton_message_transfer",
        "asset_identity_key": "ton_native_asset_v1|ton-mainnet",
        "counterparty_identity_key": (
            "ton_counterparty_account_obs_v1|ton-mainnet|" + COUNTERPARTY
        ),
        "counterparty_account_canonical": COUNTERPARTY,
        "amount_base_units": "1000000000",
        "created_logical_time": "1000",
        "unix_time": 1000,
        "body_hash": "77" * 32,
        "opcode_hex": None,
        "bounce": False,
        "bounced": False,
    }


def _merge_result() -> dict:
    first = _activity(run_id=1, ledger_id="10", merge_index=0)
    second = _activity(run_id=2, ledger_id="20", merge_index=1)
    return {
        "target_run_id": 2,
        "selected_run_ids": [1, 2],
        "activities": [first, second],
        "network": "ton-mainnet",
        "wallet_account_canonical": ACCOUNT,
        "source_ledger_count": 2,
        "merged_activity_count": 2,
        "merge_digest_sha256": "88" * 32,
    }


def test_dedup_selects_first_occurrence_and_preserves_resolution(monkeypatch):
    monkeypatch.setattr(
        dedup_service,
        "merge_wallet_native_activity_ledgers",
        lambda _target, _runs, _session: _merge_result(),
    )

    result = dedup_service.deduplicate_wallet_native_activity(2, [2, 1], None)

    assert result["selected_run_ids"] == [1, 2]
    assert result["merged_activity_count"] == 2
    assert result["deduplicated_activity_count"] == 1
    assert result["suppressed_occurrence_count"] == 1
    assert result["resolution_count"] == 1
    assert result["activities"][0]["source_run_id"] == 1
    assert result["activities"][0]["occurrence_count"] == 2
    assert result["activities"][0]["source_occurrences"] == [
        {"source_run_id": 1, "source_ledger_id": "10", "merge_index": 0},
        {"source_run_id": 2, "source_ledger_id": "20", "merge_index": 1},
    ]
    assert result["resolutions"][0]["suppressed"][0]["source_run_id"] == 2
    assert result["cross_run_deduplication_applied"] is True
    assert result["duplicates_retained"] is False
    WalletNativeActivityDedupResponse.model_validate(result)


def test_dedup_rejects_conflicting_semantics(monkeypatch):
    merged = _merge_result()
    merged["activities"][1]["amount_base_units"] = "2000000000"
    monkeypatch.setattr(
        dedup_service,
        "merge_wallet_native_activity_ledgers",
        lambda _target, _runs, _session: merged,
    )

    with pytest.raises(
        dedup_service.WalletNativeActivityDedupConflict,
        match="conflicting verified semantics",
    ):
        dedup_service.deduplicate_wallet_native_activity(2, [1, 2], None)
