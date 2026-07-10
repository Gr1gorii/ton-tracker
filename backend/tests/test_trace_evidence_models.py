"""Relational integrity tests for finalized persisted trace evidence."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from database import Base, create_database_engine
from models import (
    WalletIngestionRun,
    WalletTraceBocTransaction,
    WalletTraceBocVerification,
    WalletTraceEvidenceCapture,
    WalletTraceEvidenceMessage,
    WalletTraceEvidenceNode,
    WalletTransaction,
)


TRANSACTION_HASH = "ab" * 32
SECOND_TRANSACTION_HASH = "cd" * 32
MESSAGE_HASH = "ef" * 32
ACCOUNT = "0:" + "12" * 32
SECOND_ACCOUNT = "0:" + "34" * 32
LOGICAL_TIME = "89156526000001"
SECOND_LOGICAL_TIME = "89156526000002"
CONTRACT_VERSION = "tonapi_low_level_trace_evidence_v1"
BOC_CONTRACT_VERSION = "ton_boc_trace_verification_v1"


def _engine():
    engine = create_database_engine("sqlite://")
    Base.metadata.create_all(engine)
    return engine


def _run() -> WalletIngestionRun:
    return WalletIngestionRun(
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
        wallet_account_id_hex="12" * 32,
        wallet_address_format="raw",
    )


def _transaction(transaction_hash: str = TRANSACTION_HASH) -> WalletTransaction:
    return WalletTransaction(
        tx_hash=transaction_hash,
        logical_time=LOGICAL_TIME,
        success="success",
        provider="tonapi",
        source_status="live",
    )


def _capture(
    *,
    capture_slot: int = 0,
    root_transaction_hash: str = TRANSACTION_HASH,
    digest: str = "56" * 32,
) -> WalletTraceEvidenceCapture:
    return WalletTraceEvidenceCapture(
        capture_slot=capture_slot,
        provider="tonapi",
        contract_version=CONTRACT_VERSION,
        network="ton-mainnet",
        root_transaction_hash=root_transaction_hash,
        trace_state="finalized",
        transaction_count=1,
        max_depth=0,
        message_count=1,
        root_inbound_message_count=1,
        child_internal_message_count=0,
        remaining_out_message_count=0,
        internal_message_count=1,
        external_in_message_count=0,
        external_out_message_count=0,
        successful_transaction_count=1,
        failed_transaction_count=0,
        aborted_transaction_count=0,
        unique_account_count=1,
        evidence_digest_sha256=digest,
        captured_at=datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc),
    )


def _node(
    *,
    preorder_index: int = 0,
    transaction_hash: str = TRANSACTION_HASH,
    account: str = ACCOUNT,
    logical_time: str = LOGICAL_TIME,
) -> WalletTraceEvidenceNode:
    return WalletTraceEvidenceNode(
        preorder_index=preorder_index,
        depth=0 if preorder_index == 0 else 1,
        transaction_hash=transaction_hash,
        account_canonical=account,
        logical_time=logical_time,
        unix_time=1_717_236_000,
        success=True,
        aborted=False,
    )


def _message(
    *,
    ordinal: int = 0,
    observation_identity_key: str = "message-observation-1",
    message_hash: str = MESSAGE_HASH,
) -> WalletTraceEvidenceMessage:
    return WalletTraceEvidenceMessage(
        role="root_inbound",
        ordinal=ordinal,
        message_hash=message_hash,
        message_type="int_msg",
        source_account_canonical=SECOND_ACCOUNT,
        destination_account_canonical=ACCOUNT,
        created_logical_time=LOGICAL_TIME,
        unix_time=1_717_235_999,
        value_nanoton="1000000000",
        forward_fee_nanoton="0",
        ihr_fee_nanoton="0",
        import_fee_nanoton="0",
        ihr_disabled=True,
        bounce=True,
        bounced=False,
        observation_identity_key=observation_identity_key,
    )


def _seed_tree(session: Session) -> tuple[int, int, int, int]:
    run = _run()
    transaction = _transaction()
    capture = _capture()
    node = _node()
    node.messages.append(_message())
    capture.nodes.append(node)
    capture.captured_via_transaction = transaction
    run.transactions.append(transaction)
    run.trace_evidence_captures.append(capture)
    session.add(run)
    session.commit()
    return run.id, transaction.id, capture.id, node.id


def _counts(session: Session) -> tuple[int, int, int]:
    return (
        session.scalar(
            select(func.count()).select_from(WalletTraceEvidenceCapture)
        ),
        session.scalar(select(func.count()).select_from(WalletTraceEvidenceNode)),
        session.scalar(
            select(func.count()).select_from(WalletTraceEvidenceMessage)
        ),
    )


def _boc_verification() -> WalletTraceBocVerification:
    return WalletTraceBocVerification(
        contract_version=BOC_CONTRACT_VERSION,
        verifier_name="pytoniq-core",
        verifier_version="0.1.46",
        network="ton-mainnet",
        transaction_count=1,
        message_count=1,
        total_boc_bytes=1,
        normalized_external_in_hash_count=0,
        direct_cell_hash_message_count=1,
        body_hash_count=1,
        opcode_count=0,
        evidence_digest_sha256="78" * 32,
        verified_at=datetime(2026, 7, 10, 13, 0, tzinfo=timezone.utc),
    )


def _boc_transaction() -> WalletTraceBocTransaction:
    return WalletTraceBocTransaction(
        preorder_index=0,
        transaction_hash=TRANSACTION_HASH,
        transaction_boc_hex="00",
        transaction_boc_bytes=1,
        transaction_cell_hash=TRANSACTION_HASH,
        message_count=1,
        message_evidence_digest_sha256="9a" * 32,
    )


def _boc_counts(session: Session) -> tuple[int, int]:
    return (
        session.scalar(
            select(func.count()).select_from(WalletTraceBocVerification)
        ),
        session.scalar(
            select(func.count()).select_from(WalletTraceBocTransaction)
        ),
    )


def test_relationships_persist_one_complete_trace_tree():
    engine = _engine()
    with Session(engine) as session:
        _seed_tree(session)
        capture = session.scalar(select(WalletTraceEvidenceCapture))
        assert capture is not None
        assert capture.run.trace_evidence_captures == [capture]
        assert capture.captured_via_transaction.captured_trace_evidence == [capture]
        assert len(capture.nodes) == 1
        assert len(capture.nodes[0].messages) == 1
        assert _counts(session) == (1, 1, 1)
    engine.dispose()


def test_boc_verification_relationships_persist_one_bound_transaction():
    engine = _engine()
    with Session(engine) as session:
        _run_id, _transaction_id, capture_id, node_id = _seed_tree(session)
        capture = session.get(WalletTraceEvidenceCapture, capture_id)
        node = session.get(WalletTraceEvidenceNode, node_id)
        verification = _boc_verification()
        boc_transaction = _boc_transaction()
        with session.no_autoflush:
            boc_transaction.node = node
            verification.transactions.append(boc_transaction)
            capture.boc_verifications.append(verification)
            session.add(verification)
        session.commit()

        assert verification.capture is capture
        assert verification.transactions == [boc_transaction]
        assert boc_transaction.node is node
        assert node.boc_transactions == [boc_transaction]
        assert _boc_counts(session) == (1, 1)
    engine.dispose()


def test_deleting_capture_cascades_boc_verification_and_transactions():
    engine = _engine()
    with Session(engine) as session:
        _run_id, _transaction_id, capture_id, node_id = _seed_tree(session)
        verification = _boc_verification()
        verification.capture_id = capture_id
        boc_transaction = _boc_transaction()
        boc_transaction.node_id = node_id
        verification.transactions.append(boc_transaction)
        session.add(verification)
        session.commit()

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM wallet_trace_evidence_captures WHERE id=?",
            (capture_id,),
        )

    with Session(engine) as session:
        assert _boc_counts(session) == (0, 0)
    engine.dispose()


def test_boc_verification_contract_is_unique_per_capture():
    engine = _engine()
    with Session(engine) as session:
        _run_id, _transaction_id, capture_id, _node_id = _seed_tree(session)
        first = _boc_verification()
        first.capture_id = capture_id
        second = _boc_verification()
        second.capture_id = capture_id
        session.add_all((first, second))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


@pytest.mark.parametrize(
    "changed_field",
    ["node_id", "preorder_index", "transaction_hash"],
)
def test_boc_transaction_identity_is_unique_within_verification(changed_field):
    engine = _engine()
    with Session(engine) as session:
        _run_id, _transaction_id, capture_id, node_id = _seed_tree(session)
        verification = _boc_verification()
        verification.capture_id = capture_id
        first = _boc_transaction()
        first.node_id = node_id
        second = _boc_transaction()
        second.node_id = node_id
        if changed_field != "node_id":
            second.node_id = node_id
        if changed_field != "preorder_index":
            second.preorder_index = 1
        if changed_field != "transaction_hash":
            second.transaction_hash = SECOND_TRANSACTION_HASH
        verification.transactions.extend((first, second))
        session.add(verification)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_deleting_anchor_transaction_cascades_capture_nodes_and_messages():
    engine = _engine()
    with Session(engine) as session:
        _run_id, transaction_id, _capture_id, _node_id = _seed_tree(session)

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM wallet_transactions WHERE id=?",
            (transaction_id,),
        )

    with Session(engine) as session:
        assert _counts(session) == (0, 0, 0)
    engine.dispose()


def test_deleting_parent_node_cascades_child_nodes_and_messages():
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        transaction = _transaction()
        capture = _capture()
        root = _node()
        child = _node(
            preorder_index=1,
            transaction_hash=SECOND_TRANSACTION_HASH,
            account=SECOND_ACCOUNT,
            logical_time=SECOND_LOGICAL_TIME,
        )
        child.parent = root
        child.messages.append(
            _message(observation_identity_key="child-message-observation")
        )
        capture.nodes.extend([root, child])
        capture.captured_via_transaction = transaction
        run.transactions.append(transaction)
        run.trace_evidence_captures.append(capture)
        session.add(run)
        session.commit()
        root_id = root.id
        assert child in root.children

    with engine.begin() as connection:
        connection.exec_driver_sql(
            "DELETE FROM wallet_trace_evidence_nodes WHERE id=?",
            (root_id,),
        )

    with Session(engine) as session:
        assert _counts(session) == (1, 0, 0)
    engine.dispose()


@pytest.mark.parametrize(
    ("table_name", "columns", "values"),
    [
        (
            "wallet_trace_evidence_captures",
            "run_id, captured_via_transaction_id, capture_slot, provider, "
            "contract_version, network, root_transaction_hash, trace_state, "
            "transaction_count, "
            "max_depth, message_count, root_inbound_message_count, "
            "child_internal_message_count, remaining_out_message_count, "
            "internal_message_count, external_in_message_count, "
            "external_out_message_count, successful_transaction_count, "
            "failed_transaction_count, aborted_transaction_count, "
            "unique_account_count, evidence_digest_sha256, captured_at",
            (
                404,
                405,
                0,
                "tonapi",
                CONTRACT_VERSION,
                "ton-mainnet",
                TRANSACTION_HASH,
                "finalized",
                1,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                1,
                0,
                0,
                1,
                "56" * 32,
                "2026-07-10 12:00:00",
            ),
        ),
        (
            "wallet_trace_evidence_nodes",
            "capture_id, preorder_index, parent_node_id, depth, "
            "transaction_hash, account_canonical, logical_time, unix_time, "
            "success, aborted",
            (
                404,
                0,
                None,
                0,
                TRANSACTION_HASH,
                ACCOUNT,
                LOGICAL_TIME,
                1_717_236_000,
                1,
                0,
            ),
        ),
        (
            "wallet_trace_evidence_messages",
            "node_id, role, ordinal, message_hash, message_type, "
            "source_account_canonical, destination_account_canonical, "
            "created_logical_time, unix_time, value_nanoton, "
            "forward_fee_nanoton, ihr_fee_nanoton, import_fee_nanoton, "
            "ihr_disabled, bounce, bounced, observation_identity_key",
            (
                404,
                "root_inbound",
                0,
                MESSAGE_HASH,
                "int_msg",
                SECOND_ACCOUNT,
                ACCOUNT,
                LOGICAL_TIME,
                1_717_235_999,
                "1",
                "0",
                "0",
                "0",
                1,
                1,
                0,
                "orphan-message",
            ),
        ),
    ],
)
def test_database_rejects_orphan_trace_evidence(table_name, columns, values):
    engine = _engine()
    placeholders = ", ".join("?" for _ in values)
    with engine.begin() as connection:
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})",
                values,
            )
    engine.dispose()


@pytest.mark.parametrize("duplicate", ["root", "anchor"])
def test_capture_root_and_anchor_contracts_are_unique_within_run(duplicate):
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        first_transaction = _transaction()
        second_transaction = _transaction(SECOND_TRANSACTION_HASH)
        first = _capture()
        second = _capture(
            capture_slot=1,
            root_transaction_hash=(
                TRANSACTION_HASH if duplicate == "root" else SECOND_TRANSACTION_HASH
            ),
            digest="78" * 32,
        )
        first.captured_via_transaction = first_transaction
        second.captured_via_transaction = (
            second_transaction if duplicate == "root" else first_transaction
        )
        run.transactions.append(first_transaction)
        if duplicate == "root":
            run.transactions.append(second_transaction)
        run.trace_evidence_captures.extend([first, second])
        session.add(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_capture_slot_is_unique_within_run():
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        first_transaction = _transaction()
        second_transaction = _transaction(SECOND_TRANSACTION_HASH)
        first = _capture(capture_slot=0)
        second = _capture(
            capture_slot=0,
            root_transaction_hash=SECOND_TRANSACTION_HASH,
            digest="78" * 32,
        )
        first.captured_via_transaction = first_transaction
        second.captured_via_transaction = second_transaction
        run.transactions.extend([first_transaction, second_transaction])
        run.trace_evidence_captures.extend([first, second])
        session.add(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_distinct_capture_slots_are_allowed_within_run():
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        first_transaction = _transaction()
        second_transaction = _transaction(SECOND_TRANSACTION_HASH)
        first = _capture(capture_slot=0)
        second = _capture(
            capture_slot=1,
            root_transaction_hash=SECOND_TRANSACTION_HASH,
            digest="78" * 32,
        )
        first.captured_via_transaction = first_transaction
        second.captured_via_transaction = second_transaction
        run.transactions.extend([first_transaction, second_transaction])
        run.trace_evidence_captures.extend([first, second])
        session.add(run)
        session.commit()
        assert session.scalar(
            select(func.count()).select_from(WalletTraceEvidenceCapture)
        ) == 2
    engine.dispose()


@pytest.mark.parametrize(
    "duplicate",
    ["preorder", "hash", "coordinate"],
)
def test_node_identities_are_unique_within_capture(duplicate):
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        transaction = _transaction()
        capture = _capture()
        first = _node()
        second = _node(
            preorder_index=0 if duplicate == "preorder" else 1,
            transaction_hash=(
                TRANSACTION_HASH if duplicate == "hash" else SECOND_TRANSACTION_HASH
            ),
            account=ACCOUNT if duplicate == "coordinate" else SECOND_ACCOUNT,
            logical_time=(
                LOGICAL_TIME if duplicate == "coordinate" else SECOND_LOGICAL_TIME
            ),
        )
        capture.nodes.extend([first, second])
        capture.captured_via_transaction = transaction
        run.transactions.append(transaction)
        run.trace_evidence_captures.append(capture)
        session.add(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_message_node_role_ordinal_is_unique():
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        transaction = _transaction()
        capture = _capture()
        first_node = _node()
        first_node.messages.append(_message())
        first_node.messages.append(
            _message(observation_identity_key="message-observation-2")
        )
        capture.nodes.append(first_node)
        capture.captured_via_transaction = transaction
        run.transactions.append(transaction)
        run.trace_evidence_captures.append(capture)
        session.add(run)
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()
    engine.dispose()


def test_message_observation_key_is_deliberately_nonunique_across_nodes():
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        transaction = _transaction()
        capture = _capture()
        first_node = _node()
        second_node = _node(
            preorder_index=1,
            transaction_hash=SECOND_TRANSACTION_HASH,
            account=SECOND_ACCOUNT,
            logical_time=SECOND_LOGICAL_TIME,
        )
        first_node.messages.append(_message())
        second_node.messages.append(_message())
        capture.nodes.extend([first_node, second_node])
        capture.captured_via_transaction = transaction
        run.transactions.append(transaction)
        run.trace_evidence_captures.append(capture)
        session.add(run)
        session.commit()
        assert _counts(session) == (1, 2, 2)
    engine.dispose()


def test_message_hash_is_deliberately_nonunique():
    engine = _engine()
    with Session(engine) as session:
        run = _run()
        transaction = _transaction()
        capture = _capture()
        node = _node()
        node.messages.extend(
            [
                _message(),
                _message(
                    ordinal=1,
                    observation_identity_key="message-observation-2",
                ),
            ]
        )
        capture.nodes.append(node)
        capture.captured_via_transaction = transaction
        run.transactions.append(transaction)
        run.trace_evidence_captures.append(capture)
        session.add(run)
        session.commit()
        assert _counts(session) == (1, 1, 2)
    engine.dispose()
