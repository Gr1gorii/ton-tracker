"""Provider-free readback of locally deserialized transaction BOC evidence."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version as package_version
import json
import re
from typing import Any

from pytoniq_core import Builder, Cell
from pytoniq_core.tlb.transaction import (
    ExternalMsgInfo,
    ExternalOutMsgInfo,
    InternalMsgInfo,
    Transaction,
)
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from adapters.tonapi import TonapiAdapter
from config import Settings, get_settings
from models import (
    WalletTraceBocTransaction,
    WalletTraceBocVerification,
    WalletTraceEvidenceCapture,
    WalletTraceEvidenceMessage,
    WalletTraceEvidenceNode,
)
from services.wallet_persisted_trace_evidence import (
    PERSISTED_TRACE_CONTRACT_VERSION,
    WalletPersistedTraceEvidenceConflict,
    _canonical_utc_datetime,
    _find_capture_for_transaction,
    _revalidate_capture,
)
from services.wallet_trace_evidence import (
    WalletTraceEvidenceProviderFailure,
    _require_eligible_stored_identity,
    _require_guarded_live_tonapi,
    _sanitize_provider_message,
    resolve_wallet_transaction_trace_anchor,
)


BOC_VERIFICATION_CONTRACT_VERSION = "ton_boc_trace_verification_v1"
BOC_VERIFIER_NAME = "pytoniq-core"
BOC_VERIFIER_VERSION = "0.1.46"
MAX_TRANSACTION_BOC_BYTES = 1024 * 1024
MAX_TOTAL_BOC_BYTES = 8 * 1024 * 1024

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_BOC_HEX_RE = re.compile(r"^(?:[0-9a-f]{2})+$")


class WalletTraceBocVerificationConflict(ValueError):
    """Stored BOC evidence or its trace binding failed local revalidation."""


class WalletTraceBocVerificationFailure(RuntimeError):
    """Local verification storage or its pinned verifier is unavailable."""


def get_wallet_transaction_trace_boc_verification(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any] | None:
    """Read and reparse a stored verification without provider access."""
    run, transaction = resolve_wallet_transaction_trace_anchor(
        run_id,
        transaction_hash,
        session,
    )
    _require_eligible_stored_identity(run, transaction, transaction_hash)
    capture = _find_capture_for_transaction(run_id, transaction_hash, session)
    if capture is None:
        return None
    persisted = _revalidate_capture(capture, run, transaction, session)
    verification = _find_verification(capture.id, session)
    if verification is None:
        return None
    return _revalidate_verification(
        verification,
        capture,
        persisted,
        run,
        transaction,
    )


def verify_wallet_transaction_trace_bocs(
    run_id: int,
    transaction_hash: str,
    session: Session,
    settings: Settings | None = None,
) -> tuple[dict[str, Any], bool]:
    """Fetch once, locally verify, and atomically persist every trace BOC."""
    _require_pinned_verifier()
    run, transaction = resolve_wallet_transaction_trace_anchor(
        run_id,
        transaction_hash,
        session,
    )
    _require_eligible_stored_identity(run, transaction, transaction_hash)
    capture = _find_capture_for_transaction(run_id, transaction_hash, session)
    if capture is None:
        raise WalletTraceBocVerificationConflict(
            "Persisted trace evidence must be captured before BOC verification."
        )
    persisted = _revalidate_capture(capture, run, transaction, session)
    existing = _find_verification(capture.id, session)
    if existing is not None:
        return (
            _revalidate_verification(
                existing,
                capture,
                persisted,
                run,
                transaction,
            ),
            False,
        )

    settings = settings or get_settings()
    _require_guarded_live_tonapi(settings, run)
    result = TonapiAdapter(
        settings
    ).get_transaction_trace_boc_verification_candidate(
        transaction_hash,
        network=run.wallet_network,
    )
    if not result.ok:
        detail = result.message or "TonAPI BOC verification request failed."
        raise WalletTraceEvidenceProviderFailure(
            _sanitize_provider_message(detail, settings)
        )
    candidate = result.data
    if not isinstance(candidate, dict):
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI BOC verification response was not an object."
        )
    _require_candidate_matches_capture(candidate.get("trace"), capture, persisted)
    raw_rows = candidate.get("transaction_bocs")
    if not isinstance(raw_rows, list):
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI BOC verification candidate omitted transaction BOCs."
        )

    verified_at = datetime.now(timezone.utc)
    try:
        derived = _derive_boc_evidence(capture, raw_rows)
    except WalletTraceBocVerificationConflict as exc:
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI transaction BOCs failed local trace-bound verification."
        ) from exc

    verification = WalletTraceBocVerification(
        capture_id=capture.id,
        contract_version=BOC_VERIFICATION_CONTRACT_VERSION,
        verifier_name=BOC_VERIFIER_NAME,
        verifier_version=BOC_VERIFIER_VERSION,
        network=capture.network,
        transaction_count=derived["transaction_count"],
        message_count=derived["message_count"],
        total_boc_bytes=derived["total_boc_bytes"],
        normalized_external_in_hash_count=derived[
            "normalized_external_in_hash_count"
        ],
        direct_cell_hash_message_count=derived[
            "direct_cell_hash_message_count"
        ],
        body_hash_count=derived["body_hash_count"],
        opcode_count=derived["opcode_count"],
        evidence_digest_sha256=_verification_digest(
            capture,
            verified_at,
            derived["canonical_transactions"],
        ),
        verified_at=verified_at,
    )
    try:
        session.add(verification)
        session.flush()
        node_by_preorder = {
            node.preorder_index: node for node in capture.nodes
        }
        for transaction_evidence in derived["canonical_transactions"]:
            preorder_index = transaction_evidence["preorder_index"]
            node = node_by_preorder[preorder_index]
            session.add(
                WalletTraceBocTransaction(
                    verification_id=verification.id,
                    node_id=node.id,
                    preorder_index=preorder_index,
                    transaction_hash=transaction_evidence[
                        "transaction_hash"
                    ],
                    transaction_boc_hex=transaction_evidence[
                        "transaction_boc_hex"
                    ],
                    transaction_boc_bytes=transaction_evidence[
                        "transaction_boc_bytes"
                    ],
                    transaction_cell_hash=transaction_evidence[
                        "transaction_cell_hash"
                    ],
                    message_count=transaction_evidence["message_count"],
                    message_evidence_digest_sha256=_digest_json(
                        transaction_evidence
                    ),
                )
            )
        session.flush()
        stored = _find_verification(capture.id, session)
        if stored is None:
            raise WalletTraceBocVerificationFailure(
                "Stored BOC verification could not be read before commit."
            )
        validated = _revalidate_verification(
            stored,
            capture,
            persisted,
            run,
            transaction,
        )
        session.commit()
        return validated, True
    except WalletTraceBocVerificationConflict:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        concurrent = _find_verification(capture.id, session)
        if concurrent is not None:
            return (
                _revalidate_verification(
                    concurrent,
                    capture,
                    persisted,
                    run,
                    transaction,
                ),
                False,
            )
        raise WalletTraceBocVerificationFailure(
            "BOC verification conflicted with existing evidence."
        ) from exc
    except (KeyError, TypeError, ValueError, SQLAlchemyError) as exc:
        session.rollback()
        raise WalletTraceBocVerificationFailure(
            "BOC verification could not be stored atomically."
        ) from exc


def _find_verification(
    capture_id: int,
    session: Session,
) -> WalletTraceBocVerification | None:
    rows = list(
        session.scalars(
            select(WalletTraceBocVerification)
            .where(WalletTraceBocVerification.capture_id == capture_id)
            .where(
                WalletTraceBocVerification.contract_version
                == BOC_VERIFICATION_CONTRACT_VERSION
            )
            .options(
                selectinload(WalletTraceBocVerification.transactions)
                .selectinload(WalletTraceBocTransaction.node)
                .selectinload(WalletTraceEvidenceNode.messages)
            )
            .limit(2)
        ).unique()
    )
    if len(rows) > 1:
        raise WalletTraceBocVerificationConflict(
            "Stored BOC verification identity is ambiguous."
        )
    return rows[0] if rows else None


def _revalidate_verification(
    verification: WalletTraceBocVerification,
    capture: WalletTraceEvidenceCapture,
    persisted: dict[str, Any],
    run: Any,
    transaction: Any,
) -> dict[str, Any]:
    _require_pinned_verifier()
    if (
        verification.capture_id != capture.id
        or verification.contract_version != BOC_VERIFICATION_CONTRACT_VERSION
        or verification.verifier_name != BOC_VERIFIER_NAME
        or verification.verifier_version != BOC_VERIFIER_VERSION
        or verification.network != capture.network
        or not _is_hash(verification.evidence_digest_sha256)
    ):
        raise WalletTraceBocVerificationConflict(
            "Stored BOC verification metadata failed local revalidation."
        )
    rows = sorted(
        verification.transactions,
        key=lambda item: item.preorder_index,
    )
    raw_rows: list[dict[str, Any]] = []
    for expected_index, row in enumerate(rows):
        if (
            row.preorder_index != expected_index
            or row.node is None
            or row.node.capture_id != capture.id
            or row.node.preorder_index != expected_index
            or row.transaction_hash != row.node.transaction_hash
            or row.transaction_cell_hash != row.transaction_hash
            or not _is_hash(row.message_evidence_digest_sha256)
            or not _valid_boc_hex(row.transaction_boc_hex)
            or row.transaction_boc_bytes != len(row.transaction_boc_hex) // 2
            or not 0 < row.transaction_boc_bytes <= MAX_TRANSACTION_BOC_BYTES
        ):
            raise WalletTraceBocVerificationConflict(
                "Stored transaction BOC row failed local revalidation."
            )
        raw_rows.append(
            {
                "preorder_index": row.preorder_index,
                "transaction_hash": row.transaction_hash,
                "transaction_boc_hex": row.transaction_boc_hex,
                "transaction_boc_bytes": row.transaction_boc_bytes,
            }
        )
    derived = _derive_boc_evidence(capture, raw_rows)
    if len(rows) != derived["transaction_count"]:
        raise WalletTraceBocVerificationConflict(
            "Stored transaction BOC count failed local revalidation."
        )
    for row, evidence in zip(rows, derived["canonical_transactions"]):
        if (
            row.message_count != evidence["message_count"]
            or row.message_evidence_digest_sha256 != _digest_json(evidence)
        ):
            raise WalletTraceBocVerificationConflict(
                "Stored transaction message evidence digest changed."
            )
    summary = {
        name: derived[name]
        for name in (
            "transaction_count",
            "message_count",
            "total_boc_bytes",
            "normalized_external_in_hash_count",
            "direct_cell_hash_message_count",
            "body_hash_count",
            "opcode_count",
        )
    }
    if any(getattr(verification, name) != value for name, value in summary.items()):
        raise WalletTraceBocVerificationConflict(
            "Stored BOC verification summary failed local revalidation."
        )
    verified_at = _canonical_utc_datetime(verification.verified_at)
    digest = _verification_digest(
        capture,
        verified_at,
        derived["canonical_transactions"],
    )
    if digest != verification.evidence_digest_sha256:
        raise WalletTraceBocVerificationConflict(
            "Stored BOC verification digest failed local revalidation."
        )
    anchor = persisted["anchor"]
    if anchor["transaction_hash"] != transaction.transaction_hash_canonical:
        raise WalletTraceBocVerificationConflict(
            "Stored BOC verification selected anchor changed."
        )
    return {
        "contract_version": BOC_VERIFICATION_CONTRACT_VERSION,
        "verification_id": str(verification.id),
        "capture_id": str(capture.id),
        "run_id": str(run.id),
        "provider": "tonapi",
        "source_status": "live",
        "network": verification.network,
        "verified_at": verified_at,
        "verifier": {
            "name": BOC_VERIFIER_NAME,
            "version": BOC_VERIFIER_VERSION,
        },
        "anchor": anchor,
        "capture_evidence_digest_sha256": capture.evidence_digest_sha256,
        "evidence_digest_sha256": digest,
        "summary": summary,
        "transactions": [
            _public_transaction_summary(value)
            for value in derived["canonical_transactions"]
        ],
        "transaction_bocs_deserialized_locally": True,
        "transaction_cell_hashes_verified": True,
        "transaction_headers_verified": True,
        "message_hashes_verified": True,
        "message_headers_verified": True,
        "message_body_hashes_derived": True,
        "raw_boc_persisted": True,
        "raw_boc_returned": False,
        "message_bodies_returned": False,
        "is_blockchain_inclusion_proof_verified": False,
        "is_authoritative_activity_identity": False,
        "semantic_reconstruction_applied": False,
        "activity_merge_applied": False,
        "deduplication_applied": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "is_ownership_proof": False,
        "message": (
            "Every stored transaction BOC was reparsed locally; transaction "
            "cell hashes, bounded headers, message hashes, message headers, "
            "body hashes, and outgoing trace edges matched the persisted "
            "graph. Provider delivery is not a blockchain inclusion proof, "
            "and no semantic activity reconstruction or PnL use was applied."
        ),
    }


def _require_candidate_matches_capture(
    candidate: Any,
    capture: WalletTraceEvidenceCapture,
    persisted: dict[str, Any],
) -> None:
    if not isinstance(candidate, dict):
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI BOC verification candidate omitted its trace graph."
        )
    nodes = sorted(capture.nodes, key=lambda item: item.preorder_index)
    id_to_preorder = {node.id: node.preorder_index for node in nodes}
    expected_nodes = []
    for node in nodes:
        messages = sorted(
            node.messages,
            key=lambda item: (_message_role_rank(item.role), item.ordinal),
        )
        inbound = next(
            (value for value in messages if value.role != "remaining_outbound"),
            None,
        )
        expected_nodes.append(
            {
                "preorder_index": node.preorder_index,
                "parent_preorder_index": (
                    None
                    if node.parent_node_id is None
                    else id_to_preorder[node.parent_node_id]
                ),
                "depth": node.depth,
                "transaction_hash": node.transaction_hash,
                "account_canonical": node.account_canonical,
                "logical_time": node.logical_time,
                "unix_time": node.unix_time,
                "success": node.success,
                "aborted": node.aborted,
                "in_message": (
                    None if inbound is None else _stored_message_dict(inbound)
                ),
                "out_messages": [
                    _stored_message_dict(value)
                    for value in messages
                    if value.role == "remaining_outbound"
                ],
            }
        )
    anchor = candidate.get("anchor")
    expected_anchor = persisted["anchor"]
    if (
        candidate.get("trace_state") != "finalized"
        or candidate.get("summary") != persisted["summary"]
        or candidate.get("nodes") != expected_nodes
        or not isinstance(anchor, dict)
        or any(
            anchor.get(name) != expected_anchor.get(name)
            for name in (
                "transaction_hash",
                "logical_time",
                "account_canonical",
            )
        )
        or capture.contract_version != PERSISTED_TRACE_CONTRACT_VERSION
    ):
        raise WalletTraceBocVerificationConflict(
            "Current TonAPI trace candidate does not match persisted evidence."
        )


def _derive_boc_evidence(
    capture: WalletTraceEvidenceCapture,
    raw_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    _require_pinned_verifier()
    nodes = sorted(capture.nodes, key=lambda item: item.preorder_index)
    if len(raw_rows) != len(nodes) or not 1 <= len(nodes) <= 256:
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC count does not match the persisted trace."
        )
    total_boc_bytes = 0
    canonical_transactions = []
    for expected_index, (node, raw_row) in enumerate(zip(nodes, raw_rows)):
        if (
            not isinstance(raw_row, dict)
            or raw_row.get("preorder_index") != expected_index
            or raw_row.get("transaction_hash") != node.transaction_hash
        ):
            raise WalletTraceBocVerificationConflict(
                "Transaction BOC order or identity is incoherent."
            )
        boc_hex = raw_row.get("transaction_boc_hex")
        boc_size = raw_row.get("transaction_boc_bytes")
        if (
            not _valid_boc_hex(boc_hex)
            or isinstance(boc_size, bool)
            or not isinstance(boc_size, int)
            or boc_size != len(boc_hex) // 2
            or not 0 < boc_size <= MAX_TRANSACTION_BOC_BYTES
        ):
            raise WalletTraceBocVerificationConflict(
                "Transaction BOC encoding or size is invalid."
            )
        total_boc_bytes += boc_size
        if total_boc_bytes > MAX_TOTAL_BOC_BYTES:
            raise WalletTraceBocVerificationConflict(
                "Transaction BOCs exceed the aggregate storage limit."
            )
        canonical_transactions.append(
            _derive_transaction_evidence(node, nodes, boc_hex, boc_size)
        )

    owned_messages = [
        message
        for transaction in canonical_transactions
        for message in transaction["messages"]
    ]
    return {
        "transaction_count": len(canonical_transactions),
        "message_count": len(owned_messages),
        "total_boc_bytes": total_boc_bytes,
        "normalized_external_in_hash_count": sum(
            value["hash_kind"] == "normalized_external_in"
            for value in owned_messages
        ),
        "direct_cell_hash_message_count": sum(
            value["hash_kind"] == "cell_hash" for value in owned_messages
        ),
        "body_hash_count": len(owned_messages),
        "opcode_count": sum(
            value["opcode_hex"] is not None for value in owned_messages
        ),
        "canonical_transactions": canonical_transactions,
    }


def _derive_transaction_evidence(
    node: WalletTraceEvidenceNode,
    nodes: list[WalletTraceEvidenceNode],
    boc_hex: str,
    boc_size: int,
) -> dict[str, Any]:
    try:
        roots = Cell.from_boc(bytes.fromhex(boc_hex))
        if len(roots) != 1:
            raise ValueError("transaction BOC must have one root")
        root = roots[0]
        cell_hash = root.hash.hex()
        transaction_slice = root.begin_parse()
        parsed = Transaction.deserialize(transaction_slice)
    except Exception as exc:
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC could not be deserialized locally."
        ) from exc
    if transaction_slice.remaining_bits or transaction_slice.remaining_refs:
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC has unconsumed root data."
        )
    account_hash = node.account_canonical.split(":", 1)[1]
    parsed_aborted = bool(getattr(parsed.description, "aborted", False))
    if (
        cell_hash != node.transaction_hash
        or parsed.account_addr.hex() != account_hash
        or parsed.lt != int(node.logical_time, 10)
        or parsed.now != node.unix_time
        or parsed.outmsg_cnt != len(parsed.out_msgs)
        or parsed_aborted != node.aborted
    ):
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC header does not match persisted trace evidence."
        )

    messages = sorted(
        node.messages,
        key=lambda item: (_message_role_rank(item.role), item.ordinal),
    )
    inbound_rows = [
        value for value in messages if value.role != "remaining_outbound"
    ]
    if len(inbound_rows) > 1 or bool(parsed.in_msg) != bool(inbound_rows):
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC inbound message does not match persisted evidence."
        )
    owned: list[dict[str, Any]] = []
    if inbound_rows:
        owned.append(_verify_message(parsed.in_msg, inbound_rows[0]))

    child_inbound_rows: list[WalletTraceEvidenceMessage] = []
    for child in nodes:
        if child.parent_node_id != node.id:
            continue
        child_rows = [
            value for value in child.messages if value.role == "child_inbound"
        ]
        if len(child_rows) != 1:
            raise WalletTraceBocVerificationConflict(
                "Persisted child edge is missing its inbound message."
            )
        child_inbound_rows.extend(child_rows)
    remaining_rows = [
        value for value in messages if value.role == "remaining_outbound"
    ]
    expected_out = child_inbound_rows + remaining_rows
    expected_hashes = Counter(value.message_hash for value in expected_out)
    raw_out_by_hash: dict[str, list[Any]] = {}
    for raw_message in parsed.out_msgs:
        provider_hash, _raw_hash, _hash_kind = _message_hashes(raw_message)
        raw_out_by_hash.setdefault(provider_hash, []).append(raw_message)
    if Counter(
        hash_value
        for hash_value, values in raw_out_by_hash.items()
        for _value in values
    ) != expected_hashes:
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC outgoing messages do not match trace edges."
        )
    outgoing_checks = []
    for expected in expected_out:
        candidates = raw_out_by_hash[expected.message_hash]
        raw_message = candidates.pop(0)
        evidence = _verify_message(raw_message, expected)
        outgoing_checks.append(evidence)
        if expected.role == "remaining_outbound":
            owned.append(evidence)

    return {
        "preorder_index": node.preorder_index,
        "transaction_hash": node.transaction_hash,
        "transaction_boc_hex": boc_hex,
        "transaction_boc_bytes": boc_size,
        "transaction_cell_hash": cell_hash,
        "account_hash_hex": parsed.account_addr.hex(),
        "logical_time": str(parsed.lt),
        "unix_time": parsed.now,
        "aborted": parsed_aborted,
        "raw_out_message_count": parsed.outmsg_cnt,
        "message_count": len(owned),
        "messages": owned,
        "outgoing_edge_checks": outgoing_checks,
    }


def _verify_message(
    message: Any,
    stored: WalletTraceEvidenceMessage,
) -> dict[str, Any]:
    provider_hash, raw_cell_hash, hash_kind = _message_hashes(message)
    info = message.info
    if isinstance(info, InternalMsgInfo):
        expected_type = "int_msg"
        source = _raw_address(info.src)
        destination = _raw_address(info.dest)
        created_lt = str(info.created_lt)
        unix_time = info.created_at
        value = str(info.value.grams)
        fwd_fee = str(info.fwd_fee)
        ihr_fee = str(info.ihr_fee)
        import_fee = "0"
        ihr_disabled = info.ihr_disabled
        bounce = info.bounce
        bounced = info.bounced
        extra_currency_count = len(getattr(info.value.other, "dict", None) or {})
    elif isinstance(info, ExternalMsgInfo):
        expected_type = "ext_in_msg"
        source = None
        destination = _raw_address(info.dest)
        created_lt = "0"
        unix_time = 0
        value = "0"
        fwd_fee = "0"
        ihr_fee = "0"
        import_fee = str(info.import_fee)
        ihr_disabled = bounce = bounced = False
        extra_currency_count = 0
    elif isinstance(info, ExternalOutMsgInfo):
        expected_type = "ext_out_msg"
        source = _raw_address(info.src)
        destination = None
        created_lt = str(info.created_lt)
        unix_time = info.created_at
        value = fwd_fee = ihr_fee = import_fee = "0"
        ihr_disabled = bounce = bounced = False
        extra_currency_count = 0
    else:
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC contains an unsupported message type."
        )
    expected = (
        provider_hash,
        expected_type,
        source,
        destination,
        created_lt,
        unix_time,
        value,
        fwd_fee,
        ihr_fee,
        import_fee,
        ihr_disabled,
        bounce,
        bounced,
    )
    persisted = (
        stored.message_hash,
        stored.message_type,
        stored.source_account_canonical,
        stored.destination_account_canonical,
        stored.created_logical_time,
        stored.unix_time,
        stored.value_nanoton,
        stored.forward_fee_nanoton,
        stored.ihr_fee_nanoton,
        stored.import_fee_nanoton,
        stored.ihr_disabled,
        stored.bounce,
        stored.bounced,
    )
    if expected != persisted:
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC message header does not match persisted evidence."
        )
    body = message.body
    opcode = None
    if len(body.bits) >= 32:
        opcode = f"0x{body.begin_parse().preload_uint(32):08x}"
    return {
        "role": stored.role,
        "ordinal": stored.ordinal,
        "message_hash": provider_hash,
        "raw_message_cell_hash": raw_cell_hash,
        "hash_kind": hash_kind,
        "message_type": expected_type,
        "source_account_canonical": source,
        "destination_account_canonical": destination,
        "created_logical_time": created_lt,
        "unix_time": unix_time,
        "value_nanoton": value,
        "forward_fee_nanoton": fwd_fee,
        "ihr_fee_nanoton": ihr_fee,
        "import_fee_nanoton": import_fee,
        "ihr_disabled": ihr_disabled,
        "bounce": bounce,
        "bounced": bounced,
        "extra_currency_count": extra_currency_count,
        "body_hash": body.hash.hex(),
        "body_bit_length": len(body.bits),
        "body_ref_count": len(body.refs),
        "opcode_hex": opcode,
    }


def _message_hashes(message: Any) -> tuple[str, str, str]:
    raw_hash = message.serialize().hash.hex()
    if not isinstance(message.info, ExternalMsgInfo):
        return raw_hash, raw_hash, "cell_hash"
    normalized = (
        Builder()
        .store_uint(2, 2)
        .store_uint(0, 2)
        .store_address(message.info.dest)
        .store_uint(0, 4)
        .store_bit(0)
        .store_bit(1)
        .store_ref(message.body)
        .end_cell()
        .hash.hex()
    )
    return normalized, raw_hash, "normalized_external_in"


def _verification_digest(
    capture: WalletTraceEvidenceCapture,
    verified_at: datetime,
    transactions: list[dict[str, Any]],
) -> str:
    timestamp = _canonical_utc_datetime(verified_at)
    return _digest_json(
        {
            "contract_version": BOC_VERIFICATION_CONTRACT_VERSION,
            "verifier_name": BOC_VERIFIER_NAME,
            "verifier_version": BOC_VERIFIER_VERSION,
            "capture_id": str(capture.id),
            "capture_evidence_digest_sha256": capture.evidence_digest_sha256,
            "network": capture.network,
            "verified_at": timestamp.isoformat(timespec="microseconds").replace(
                "+00:00", "Z"
            ),
            "transactions": transactions,
        }
    )


def _public_transaction_summary(value: dict[str, Any]) -> dict[str, Any]:
    messages = value["messages"]
    return {
        "preorder_index": value["preorder_index"],
        "transaction_hash": value["transaction_hash"],
        "transaction_boc_bytes": value["transaction_boc_bytes"],
        "transaction_cell_hash": value["transaction_cell_hash"],
        "raw_out_message_count": value["raw_out_message_count"],
        "message_count": value["message_count"],
        "body_hash_count": len(messages),
        "opcode_count": sum(item["opcode_hex"] is not None for item in messages),
        "message_evidence_digest_sha256": _digest_json(value),
    }


def _stored_message_dict(message: WalletTraceEvidenceMessage) -> dict[str, Any]:
    return {
        "role": message.role,
        "ordinal": message.ordinal,
        "message_hash": message.message_hash,
        "message_type": message.message_type,
        "source_account_canonical": message.source_account_canonical,
        "destination_account_canonical": message.destination_account_canonical,
        "created_logical_time": message.created_logical_time,
        "unix_time": message.unix_time,
        "value_nanoton": message.value_nanoton,
        "forward_fee_nanoton": message.forward_fee_nanoton,
        "ihr_fee_nanoton": message.ihr_fee_nanoton,
        "import_fee_nanoton": message.import_fee_nanoton,
        "ihr_disabled": message.ihr_disabled,
        "bounce": message.bounce,
        "bounced": message.bounced,
        "observation_identity_key": message.observation_identity_key,
    }


def _raw_address(value: Any) -> str:
    try:
        result = value.to_str(is_user_friendly=False)
    except (AttributeError, TypeError, ValueError) as exc:
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC message account is not a standard TON address."
        ) from exc
    if not isinstance(result, str) or ":" not in result:
        raise WalletTraceBocVerificationConflict(
            "Transaction BOC message account is not canonical."
        )
    return result.lower()


def _message_role_rank(role: str) -> int:
    return 1 if role == "remaining_outbound" else 0


def _valid_boc_hex(value: Any) -> bool:
    return (
        isinstance(value, str)
        and _BOC_HEX_RE.fullmatch(value) is not None
        and len(value) // 2 <= MAX_TRANSACTION_BOC_BYTES
    )


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def _digest_json(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _require_pinned_verifier() -> None:
    try:
        installed = package_version(BOC_VERIFIER_NAME)
    except PackageNotFoundError as exc:
        raise WalletTraceBocVerificationFailure(
            "The pinned local BOC verifier is not installed."
        ) from exc
    if installed != BOC_VERIFIER_VERSION:
        raise WalletTraceBocVerificationFailure(
            "The installed local BOC verifier does not match the pinned version."
        )


__all__ = [
    "BOC_VERIFICATION_CONTRACT_VERSION",
    "WalletTraceBocVerificationConflict",
    "WalletTraceBocVerificationFailure",
    "get_wallet_transaction_trace_boc_verification",
    "verify_wallet_transaction_trace_bocs",
]
