"""Persistence guards for provider event-action observation identities."""

from __future__ import annotations

import pytest

from adapters.wallet_activity import WalletActivitySwap, WalletActivityTransfer
from models import WalletIngestionRun
import services.wallet_activity_ingestion as ingestion


ACCOUNT_ID = "ab" * 32
ACCOUNT = f"0:{ACCOUNT_ID}"
EVENT_ID = "cd" * 32
LT = "89089355000001"


def _run(*, data_mode: str = "real") -> WalletIngestionRun:
    return WalletIngestionRun(
        wallet_address="EQsubmitted",
        time_window="24h",
        data_mode=data_mode,
        status="partial",
        requested_surfaces_json='["transfers","swaps"]',
        provider_summary_json="{}",
        wallet_identity_status=(
            "network_scoped" if data_mode == "real" else "unavailable"
        ),
        wallet_identity_version=(
            "ton_std_address_v1" if data_mode == "real" else "unavailable"
        ),
        wallet_network="ton-mainnet" if data_mode == "real" else "ton-unknown",
        wallet_address_canonical=ACCOUNT if data_mode == "real" else None,
        wallet_workchain_id=0 if data_mode == "real" else None,
        wallet_account_id_hex=ACCOUNT_ID if data_mode == "real" else None,
    )


def _transfer(*, action_index: int = 0) -> WalletActivityTransfer:
    return WalletActivityTransfer(
        tx_hash=EVENT_ID,
        logical_time=LT,
        timestamp="2026-07-10T10:00:00Z",
        asset="TON",
        amount="1.000000000000000000",
        direction="out",
        counterparty="EQcounterparty",
        provider="tonapi",
        source_status="live",
        raw={
            "provider": "tonapi",
            "surface": "transfers",
            "event_id": EVENT_ID,
            "lt": LT,
            "action_index": action_index,
            "action_type": "TonTransfer",
            "source": "tonapi",
        },
    )


def _swap(*, action_index: int = 1) -> WalletActivitySwap:
    return WalletActivitySwap(
        tx_hash=EVENT_ID,
        timestamp="2026-07-10T10:00:00Z",
        dex="stonfi",
        token_in="TON",
        amount_in="1.000000000000000000",
        token_out="JETTON",
        amount_out="10.000000000000000000",
        estimated_usd=None,
        provider="tonapi",
        source_status="live",
        raw={
            "provider": "tonapi",
            "surface": "swaps",
            "event_id": EVENT_ID,
            "lt": LT,
            "action_index": action_index,
            "action_type": "JettonSwap",
            "source": "tonapi",
        },
    )


def test_same_event_different_action_indices_are_distinct_observations():
    run = _run()
    seen: set[str] = set()

    transfers = ingestion._transfer_models([_transfer(action_index=0)], run, seen)
    swaps = ingestion._swap_models([_swap(action_index=1)], run, seen)

    assert len(seen) == 2
    assert transfers[0].event_action_identity_key
    assert swaps[0].event_action_identity_key
    assert (
        transfers[0].event_action_identity_key
        != swaps[0].event_action_identity_key
    )


def test_retyped_cross_table_coordinate_is_rejected_within_one_run():
    run = _run()
    seen: set[str] = set()
    ingestion._transfer_models([_transfer(action_index=0)], run, seen)

    with pytest.raises(ValueError, match="duplicate provider event-action"):
        ingestion._swap_models([_swap(action_index=0)], run, seen)


def test_tampered_persisted_tuple_never_exposes_valid_identity_flag():
    run = _run()
    models = ingestion._transfer_models([_transfer()], run, set())
    run.transfers.extend(models)
    item = run.transfers[0]

    valid = ingestion._transfer_record(item)["event_action_identity"]
    item.event_action_identity_key = "tampered"
    tampered = ingestion._transfer_record(item)["event_action_identity"]

    assert valid["status"] == "provider_scoped"
    assert valid["is_provider_observation_identity"] is True
    assert valid["is_authoritative_activity_identity"] is False
    assert tampered["status"] == "provider_scoped"
    assert tampered["key"] == "tampered"
    assert tampered["is_provider_observation_identity"] is False


def test_non_live_row_persists_explicit_unavailable_identity():
    run = _run(data_mode="mock")
    transfer = _transfer()
    transfer = WalletActivityTransfer(
        **{
            **transfer.__dict__,
            "provider": "mock_wallet_activity",
            "source_status": "mock",
        }
    )
    models = ingestion._transfer_models([transfer], run, set())
    run.transfers.extend(models)

    identity = ingestion._transfer_record(run.transfers[0])[
        "event_action_identity"
    ]

    assert identity["status"] == "unavailable"
    assert identity["version"] == "unavailable"
    assert identity["network"] == "ton-unknown"
    assert identity["key"] is None
    assert identity["is_provider_observation_identity"] is False
    assert identity["used_by_pnl"] is False
