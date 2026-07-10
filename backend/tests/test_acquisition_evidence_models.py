"""Persistence invariants for wallet acquisition stream and page evidence."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import Base, create_database_engine
from models import (
    WalletAcquisitionPage,
    WalletAcquisitionStream,
    WalletIngestionRun,
)


def _engine():
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def _run() -> WalletIngestionRun:
    return WalletIngestionRun(
        wallet_address="EQacquisitionEvidenceFixture",
        time_window="24h",
        data_mode="real",
        status="partial",
        requested_surfaces_json='["transactions"]',
        provider_summary_json="{}",
    )


def _stream(*, stream_key: str = "blockchain_transactions"):
    return WalletAcquisitionStream(
        provider="tonapi",
        stream_key=stream_key,
        contract_version="wallet_activity_acquisition_v1",
        scope_kind="bounded_history",
        page_size=100,
        max_pages=20,
        max_items=2000,
        completion_state="incomplete",
    )


def _page(*, page_index: int = 0):
    return WalletAcquisitionPage(
        page_index=page_index,
        requested_limit=100,
        request_query_json='{"limit":100,"sort_order":"desc"}',
        raw_item_count=100,
        normalized_item_count=100,
        response_cursor="89090242000012",
        newest_logical_time="89090247000003",
        oldest_logical_time="89090242000012",
        response_digest_sha256="ab" * 32,
        attempt_count=1,
        fetch_status="success",
    )


def test_database_cascade_removes_stream_and_page_evidence():
    engine = _engine()
    with engine.connect() as connection:
        assert connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() == 1
    with Session(engine) as session:
        run = _run()
        stream = _stream()
        stream.pages.append(_page())
        run.acquisition_streams.append(stream)
        session.add(run)
        session.commit()
        run_id = run.id

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM wallet_ingestion_runs WHERE id=?",
            (run_id,),
        )

    with Session(engine) as session:
        assert session.scalar(
            select(func.count()).select_from(WalletAcquisitionStream)
        ) == 0
        assert session.scalar(
            select(func.count()).select_from(WalletAcquisitionPage)
        ) == 0
    engine.dispose()


def test_runtime_engine_rejects_orphan_acquisition_stream():
    engine = _engine()
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO wallet_acquisition_streams ("
                "run_id, provider, stream_key, contract_version, scope_kind, "
                "page_size, max_pages, max_items, completion_state, "
                "started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    404,
                    "tonapi",
                    "transactions",
                    "tonapi_account_transactions_v1",
                    "bounded_interval",
                    100,
                    10,
                    1000,
                    "incomplete",
                    "2026-07-10 00:00:00",
                ),
            )
    engine.dispose()


def test_stream_identity_is_unique_within_one_run_and_provider():
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        run.acquisition_streams.extend([_stream(), _stream()])
        session.add(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_page_index_is_unique_within_one_stream():
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        stream = _stream()
        stream.pages.extend([_page(), _page()])
        run.acquisition_streams.append(stream)
        session.add(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()
