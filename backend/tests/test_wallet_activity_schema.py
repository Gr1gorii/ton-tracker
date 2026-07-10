"""Schema scaffold tests for wallet activity ingestion planning."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker

from database import Base
from models import (
    WalletBalanceSnapshot,
    WalletIngestionRun,
    WalletIngestionWarning,
    WalletSwap,
    WalletTransaction,
    WalletTransfer,
)
from schemas import (
    WalletActivityProviderEvidence,
    WalletEventActionIdentityRecord,
    WalletIdentityRecord,
    WalletIngestionPreviewRequest,
    WalletIngestionRunCatalogResponse,
    WalletIngestionRunResponse,
    WalletTransferRecord,
)


def _memory_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)(), engine


def test_wallet_activity_tables_are_registered():
    _, engine = _memory_session()
    inspector = inspect(engine)

    assert {
        "wallet_ingestion_runs",
        "wallet_transfers",
        "wallet_transactions",
        "wallet_swaps",
        "wallet_balance_snapshots",
        "wallet_ingestion_warnings",
    }.issubset(set(inspector.get_table_names()))

    run_columns = {
        column["name"] for column in inspector.get_columns("wallet_ingestion_runs")
    }
    assert {
        "wallet_address",
        "time_window",
        "data_mode",
        "status",
        "requested_surfaces_json",
        "provider_summary_json",
    }.issubset(run_columns)

    transfer_columns = {
        column["name"] for column in inspector.get_columns("wallet_transfers")
    }
    assert {
        "run_id",
        "tx_hash",
        "logical_time",
        "asset",
        "amount",
        "direction",
        "provider",
        "source_status",
        "raw_json",
        "event_action_identity_status",
        "event_action_identity_version",
        "event_action_network",
        "event_action_account_canonical",
        "event_action_event_id_canonical",
        "event_action_logical_time_canonical",
        "event_action_index",
        "event_action_type",
        "event_action_identity_key",
    }.issubset(transfer_columns)

    swap_columns = {
        column["name"] for column in inspector.get_columns("wallet_swaps")
    }
    assert {
        "event_action_identity_status",
        "event_action_identity_version",
        "event_action_network",
        "event_action_account_canonical",
        "event_action_event_id_canonical",
        "event_action_logical_time_canonical",
        "event_action_index",
        "event_action_type",
        "event_action_identity_key",
    }.issubset(swap_columns)


def test_wallet_ingestion_run_persists_child_records_and_cascades():
    session, _ = _memory_session()

    run = WalletIngestionRun(
        wallet_address="EQwallet",
        time_window="24h",
        data_mode="mock",
        status="planned",
        requested_surfaces_json='["transfers","transactions","swaps","balances"]',
        provider_summary_json='{"mock":"schema scaffold"}',
    )
    run.transfers.append(
        WalletTransfer(
            tx_hash="tx-transfer",
            logical_time="123",
            asset="TON",
            amount=Decimal("1.25"),
            direction="in",
            counterparty="EQcounterparty",
            provider="mock",
            source_status="mock",
        )
    )
    run.transactions.append(
        WalletTransaction(
            tx_hash="tx-transfer",
            logical_time="123",
            fee_ton=Decimal("0.01"),
            success="success",
            provider="mock",
            source_status="mock",
        )
    )
    run.swaps.append(
        WalletSwap(
            tx_hash="tx-swap",
            dex="STON.fi",
            token_in="TON",
            amount_in=Decimal("1"),
            token_out="JETTON",
            amount_out=Decimal("10"),
            estimated_usd=Decimal("5.50"),
            provider="mock",
            source_status="mock",
        )
    )
    run.balance_snapshots.append(
        WalletBalanceSnapshot(
            asset="TON",
            balance=Decimal("42"),
            balance_usd=Decimal("210"),
            provider="mock",
            source_status="mock",
        )
    )
    run.warnings.append(
        WalletIngestionWarning(
            severity="warning",
            provider="tonapi",
            message="Jetton balances only; full activity is not implemented.",
            evidence_key="tonapi_scope",
        )
    )

    session.add(run)
    session.commit()

    saved = session.query(WalletIngestionRun).one()
    assert saved.wallet_address == "EQwallet"
    assert saved.transfers[0].amount == Decimal("1.250000000000000000")
    assert saved.transactions[0].success == "success"
    assert saved.swaps[0].dex == "STON.fi"
    assert saved.balance_snapshots[0].balance == Decimal("42.000000000000000000")
    assert saved.warnings[0].evidence_key == "tonapi_scope"

    session.delete(saved)
    session.commit()

    assert session.query(WalletTransfer).count() == 0
    assert session.query(WalletTransaction).count() == 0
    assert session.query(WalletSwap).count() == 0
    assert session.query(WalletBalanceSnapshot).count() == 0
    assert session.query(WalletIngestionWarning).count() == 0


def test_wallet_ingestion_preview_request_validates_scope():
    request = WalletIngestionPreviewRequest(
        wallet_address="  EQwallet  ",
        time_window="24h",
        surfaces=["transfers", "balances", "transfers"],
    )

    assert request.wallet_address == "EQwallet"
    assert request.surfaces == ["transfers", "balances"]

    with pytest.raises(ValidationError):
        WalletIngestionPreviewRequest(wallet_address="", time_window="24h")

    with pytest.raises(ValidationError):
        WalletIngestionPreviewRequest(
            wallet_address="E" * 129,
            time_window="24h",
        )

    with pytest.raises(ValidationError):
        WalletIngestionPreviewRequest(
            wallet_address="EQwallet",
            time_window="custom",
            custom_start="2026-06-01T00:00:00Z",
        )

    with pytest.raises(ValidationError):
        WalletIngestionPreviewRequest(
            wallet_address="EQwallet",
            time_window="24h",
            surfaces=[],
        )


def test_wallet_ingestion_response_contract_preserves_provider_evidence():
    response = WalletIngestionRunResponse(
        run_id=7,
        wallet_address="EQwallet",
        time_window="24h",
        custom_start=None,
        custom_end=None,
        created_at="2026-07-10T00:00:00Z",
        status="planned",
        data_mode="mock",
        wallet_identity=WalletIdentityRecord(
            status="unavailable",
            version="unavailable",
            network="ton-unknown",
            submitted_format="unrecognized",
        ),
        requested_surfaces=["transfers", "balances"],
        provider_evidence=[
            WalletActivityProviderEvidence(
                provider="tonapi",
                data_mode="mock",
                source_status="limited",
                warnings=["Jettons only; full wallet activity not fetched."],
                raw_count=3,
                normalized_count=2,
            )
        ],
        transfers=[
            WalletTransferRecord(
                tx_hash="tx-transfer",
                asset="TON",
                amount="1.25",
                direction="in",
                provider="mock",
                source_status="mock",
                event_action_identity=WalletEventActionIdentityRecord(
                    status="unavailable",
                    version="unavailable",
                    network="ton-unknown",
                    is_provider_observation_identity=False,
                ),
            )
        ],
        warnings=[
            {
                "severity": "warning",
                "provider": "tonapi",
                "message": "Full wallet history is unavailable.",
                "evidence_key": "wallet_history",
            }
        ],
        message="Schema scaffold only; no provider ingestion has run.",
    )

    assert response.provider_evidence[0].source_status == "limited"
    assert response.run_id == 7
    assert response.custom_start is None
    assert response.custom_end is None
    assert response.created_at == "2026-07-10T00:00:00Z"
    assert response.wallet_identity.status == "unavailable"
    assert response.wallet_identity.is_ownership_proof is False
    assert response.transfers[0].asset == "TON"
    assert response.transfers[0].event_action_identity.status == "unavailable"
    assert (
        response.transfers[0]
        .event_action_identity.is_authoritative_activity_identity
        is False
    )
    assert response.warnings[0].evidence_key == "wallet_history"


def test_wallet_ingestion_catalog_schema_enforces_canonical_order_and_bounds():
    response = WalletIngestionRunCatalogResponse(
        runs=[
            {
                "run_id": "9",
                "wallet_hint": "EQwall…llet",
                "time_window": "24h",
                "created_at": "2026-07-10T00:00:00Z",
                "status": "success",
                "data_mode": "real",
            },
            {
                "run_id": "8",
                "wallet_hint": "EQwall…llet",
                "time_window": "custom",
                "created_at": "2026-07-09T00:00:00Z",
                "status": "partial",
                "data_mode": "real",
            },
        ],
        limit=2,
        truncated=True,
    )

    assert [run.run_id for run in response.runs] == ["9", "8"]

    with pytest.raises(ValidationError):
        WalletIngestionRunCatalogResponse(
            runs=[response.runs[1], response.runs[0]],
            limit=2,
            truncated=True,
        )
    with pytest.raises(ValidationError):
        WalletIngestionRunCatalogResponse(
            runs=[response.runs[0], response.runs[0]],
            limit=2,
            truncated=True,
        )
    with pytest.raises(ValidationError):
        WalletIngestionRunCatalogResponse(
            runs=[response.runs[0]],
            limit=2,
            truncated=True,
        )
    with pytest.raises(ValidationError):
        WalletIngestionRunCatalogResponse(
            runs=[
                {
                    **response.runs[0].model_dump(),
                    "run_id": str(2**63),
                }
            ],
            limit=1,
            truncated=False,
        )
    with pytest.raises(ValidationError):
        WalletIngestionRunCatalogResponse(
            runs=[
                {
                    **response.runs[0].model_dump(),
                    "wallet_hint": "EQshort",
                }
            ],
            limit=1,
            truncated=False,
        )
    with pytest.raises(ValidationError):
        WalletIngestionRunCatalogResponse(
            limit=1,
            truncated=False,
        )
    with pytest.raises(ValidationError):
        WalletIngestionRunCatalogResponse(
            runs=[],
            limit=1,
            truncated="false",
        )
