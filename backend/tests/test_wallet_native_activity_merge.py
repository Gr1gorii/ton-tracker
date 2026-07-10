"""Tests for deterministic multi-run native activity merge."""

from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from database import Base, create_database_engine
from models import (
    WalletIngestionRun,
    WalletNativeActivityLedger,
    WalletTraceEvidenceCapture,
    WalletTransaction,
)
import services.wallet_native_activity_merge as merge_service
from schemas import WalletNativeActivityMergeResponse


ACCOUNT = "0:" + "11" * 32
COUNTERPARTY = "0:" + "22" * 32
HASH = "33" * 32


def _engine():
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def _seed(session: Session, run_id: int, ledger_digest: str):
    run = WalletIngestionRun(
        id=run_id,
        wallet_address=ACCOUNT,
        time_window="24h",
        data_mode="real",
        status="success",
        requested_surfaces_json='["transactions"]',
        provider_summary_json="{}",
        wallet_identity_status="network_scoped",
        wallet_identity_version="ton_raw_address_v1",
        wallet_network="ton-mainnet",
        wallet_address_canonical=ACCOUNT,
        wallet_workchain_id=0,
        wallet_account_id_hex="11" * 32,
        wallet_address_format="raw",
    )
    tx_hash = f"{run_id:064x}"
    tx = WalletTransaction(
        tx_hash=tx_hash,
        logical_time=str(1000 + run_id),
        provider="tonapi",
        source_status="live",
        success="success",
        transaction_identity_status="network_scoped",
        transaction_identity_version="ton_account_tx_v1",
        transaction_network="ton-mainnet",
        transaction_account_canonical=ACCOUNT,
        transaction_logical_time_canonical=str(1000 + run_id),
        transaction_hash_canonical=tx_hash,
        transaction_identity_key=f"tx-{run_id}",
    )
    capture = WalletTraceEvidenceCapture(
        capture_slot=0,
        provider="tonapi",
        contract_version="tonapi_low_level_trace_evidence_v1",
        network="ton-mainnet",
        root_transaction_hash=tx_hash,
        trace_state="finalized",
        transaction_count=1,
        max_depth=0,
        message_count=0,
        root_inbound_message_count=0,
        child_internal_message_count=0,
        remaining_out_message_count=0,
        internal_message_count=0,
        external_in_message_count=0,
        external_out_message_count=0,
        successful_transaction_count=1,
        failed_transaction_count=0,
        aborted_transaction_count=0,
        unique_account_count=1,
        evidence_digest_sha256=f"{run_id + 10:064x}",
        captured_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    ledger = WalletNativeActivityLedger(
        contract_version="ton_native_activity_ledger_v1",
        network="ton-mainnet",
        wallet_account_canonical=ACCOUNT,
        source_message_evidence_digest_sha256="44" * 32,
        activity_count=1,
        incoming_nanoton="0",
        outgoing_nanoton="1",
        self_nanoton="0",
        evidence_digest_sha256=ledger_digest,
        built_at=datetime(2026, 7, 10, tzinfo=timezone.utc),
    )
    capture.native_activity_ledgers.append(ledger)
    capture.captured_via_transaction = tx
    run.transactions.append(tx)
    run.trace_evidence_captures.append(capture)
    session.add(run)


def _validated(ledger, run_id, _hash, _session):
    return {
        "ledger_id": str(ledger.id),
        "capture_id": str(ledger.capture_id),
        "activity_count": 1,
        "evidence_digest_sha256": ledger.evidence_digest_sha256,
        "activities": [
            {
                "ordinal": 0,
                "activity_identity_key": HASH,
                "source_flow_observation_identity": "55" * 32,
                "transaction_hash": f"{run_id:064x}",
                "message_hash": "66" * 32,
                "direction": "outgoing",
                "activity_kind": "native_ton_message_transfer",
                "asset_identity_key": "ton_native_asset_v1|ton-mainnet",
                "counterparty_identity_key": f"ton_counterparty_account_obs_v1|ton-mainnet|{COUNTERPARTY}",
                "counterparty_account_canonical": COUNTERPARTY,
                "amount_base_units": "1",
                "created_logical_time": str(1000 + run_id),
                "unix_time": 1000 + run_id,
                "body_hash": "77" * 32,
                "opcode_hex": None,
                "bounce": False,
                "bounced": False,
            }
        ],
    }


def test_merge_retains_and_groups_cross_run_duplicates(monkeypatch):
    engine = _engine()
    with Session(engine) as session:
        _seed(session, 1, "81" * 32)
        _seed(session, 2, "82" * 32)
        session.commit()
        monkeypatch.setattr(merge_service, "_revalidate_ledger", _validated)
        result = merge_service.merge_wallet_native_activity_ledgers(
            2, [2, 1], session
        )

    assert result["selected_run_ids"] == [1, 2]
    assert result["merged_activity_count"] == 2
    assert [row["merge_index"] for row in result["activities"]] == [0, 1]
    assert result["duplicate_group_count"] == 1
    assert result["duplicate_groups"][0]["source_run_ids"] == [1, 2]
    assert result["activity_merge_applied"] is True
    assert result["cross_run_deduplication_applied"] is False
    assert result["duplicates_retained"] is True
    WalletNativeActivityMergeResponse.model_validate(result)
    engine.dispose()


def test_merge_rejects_incompatible_wallet_identity(monkeypatch):
    engine = _engine()
    with Session(engine) as session:
        _seed(session, 1, "81" * 32)
        _seed(session, 2, "82" * 32)
        session.flush()
        session.get(WalletIngestionRun, 2).wallet_address_canonical = (
            "0:" + "99" * 32
        )
        session.commit()
        monkeypatch.setattr(merge_service, "_revalidate_ledger", _validated)
        with pytest.raises(
            merge_service.WalletNativeActivityMergeConflict,
            match="share one eligible",
        ):
            merge_service.merge_wallet_native_activity_ledgers(2, [1, 2], session)
    engine.dispose()
