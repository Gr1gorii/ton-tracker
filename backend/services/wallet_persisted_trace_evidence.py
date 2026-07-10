"""Immutable, locally revalidated low-level trace evidence persistence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from adapters.tonapi import TonapiAdapter
from config import Settings, get_settings
from models import (
    WalletTraceEvidenceCapture,
    WalletTraceEvidenceMessage,
    WalletTraceEvidenceNode,
    WalletTransaction,
)
from services.wallet_trace_evidence import (
    WalletTraceEvidenceIneligible,
    WalletTraceEvidenceNotFound,
    WalletTraceEvidenceProviderFailure,
    _require_eligible_stored_identity,
    _require_guarded_live_tonapi,
    _sanitize_provider_message,
    resolve_wallet_transaction_trace_anchor,
)


PERSISTED_TRACE_CONTRACT_VERSION = "tonapi_low_level_trace_evidence_v1"
TRACE_MESSAGE_OBSERVATION_VERSION = "tonapi_trace_message_obs_v1"
MAX_PERSISTED_TRACES_PER_RUN = 16

_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_ACCOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]*|-[1-9][0-9]*):[0-9a-f]{64}$")
_POSITIVE_UINT64_RE = re.compile(r"^[1-9][0-9]{0,19}$")
_NONNEGATIVE_UINT64_RE = re.compile(r"^(?:0|[1-9][0-9]{0,19})$")
_MESSAGE_TYPES = frozenset(("int_msg", "ext_in_msg", "ext_out_msg"))
_MESSAGE_ROLES = frozenset(
    ("root_inbound", "child_inbound", "remaining_outbound")
)


class WalletPersistedTraceEvidenceConflict(ValueError):
    """The stored graph, capacity, or finalization contract is not eligible."""


class WalletPersistedTraceEvidenceFailure(RuntimeError):
    """The evidence graph could not be persisted atomically."""


def get_persisted_wallet_transaction_trace_evidence(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> dict[str, Any] | None:
    """Read and locally revalidate one stored trace without provider access."""
    run, transaction = resolve_wallet_transaction_trace_anchor(
        run_id,
        transaction_hash,
        session,
    )
    _require_eligible_stored_identity(run, transaction, transaction_hash)
    capture = _find_capture_for_transaction(run_id, transaction_hash, session)
    if capture is None:
        return None
    return _revalidate_capture(capture, run, transaction, session)


def capture_persisted_wallet_transaction_trace_evidence(
    run_id: int,
    transaction_hash: str,
    session: Session,
    settings: Settings | None = None,
) -> tuple[dict[str, Any], bool]:
    """Persist one finalized provider graph or return its existing record."""
    run, transaction = resolve_wallet_transaction_trace_anchor(
        run_id,
        transaction_hash,
        session,
    )
    _require_eligible_stored_identity(run, transaction, transaction_hash)

    existing = _find_capture_for_transaction(run_id, transaction_hash, session)
    if existing is not None:
        return _revalidate_capture(existing, run, transaction, session), False

    if _available_capture_slot(session, run_id) is None:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence reached the per-run capture limit."
        )

    settings = settings or get_settings()
    _require_guarded_live_tonapi(settings, run)
    adapter = TonapiAdapter(settings)
    result = adapter.get_transaction_trace_persisted_evidence(
        transaction_hash,
        network=run.wallet_network,
    )
    if not result.ok:
        detail = result.message or "TonAPI persisted trace evidence request failed."
        raise WalletTraceEvidenceProviderFailure(
            _sanitize_provider_message(detail, settings)
        )
    normalized = result.data
    if not isinstance(normalized, dict):
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI persisted trace evidence response was not an object."
        )
    if normalized.get("trace_state") != "finalized":
        raise WalletPersistedTraceEvidenceConflict(
            "Only a finalized provider trace can be persisted."
        )
    anchor = normalized.get("anchor")
    if (
        not isinstance(anchor, dict)
        or anchor.get("transaction_hash")
        != transaction.transaction_hash_canonical
        or anchor.get("logical_time")
        != transaction.transaction_logical_time_canonical
        or anchor.get("account_canonical")
        != transaction.transaction_account_canonical
    ):
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI persisted trace anchor did not match the stored transaction identity."
        )

    capture_slot = _available_capture_slot(session, run_id)
    if capture_slot is None:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence reached the per-run capture limit."
        )
    captured_at = datetime.now(timezone.utc)
    try:
        summary = normalized["summary"]
        nodes = normalized["nodes"]
        if not isinstance(summary, dict) or not isinstance(nodes, list):
            raise TypeError("summary and nodes must use their canonical shapes")
        canonical_document = _canonical_document(
            normalized,
            run.wallet_network,
            run_id=run.id,
            capture_slot=capture_slot,
            captured_via_transaction=transaction,
            captured_at=captured_at,
        )
        evidence_digest = _digest_document(canonical_document)
        capture = WalletTraceEvidenceCapture(
            run_id=run.id,
            captured_via_transaction_id=transaction.id,
            capture_slot=capture_slot,
            provider="tonapi",
            contract_version=PERSISTED_TRACE_CONTRACT_VERSION,
            network=run.wallet_network,
            root_transaction_hash=summary["root_transaction_hash"],
            trace_state="finalized",
            transaction_count=summary["transaction_count"],
            max_depth=summary["max_depth"],
            message_count=summary["message_count"],
            root_inbound_message_count=summary["root_inbound_message_count"],
            child_internal_message_count=summary[
                "child_internal_message_count"
            ],
            remaining_out_message_count=summary[
                "remaining_out_message_count"
            ],
            internal_message_count=summary["internal_message_count"],
            external_in_message_count=summary[
                "external_in_message_count"
            ],
            external_out_message_count=summary[
                "external_out_message_count"
            ],
            successful_transaction_count=summary[
                "successful_transaction_count"
            ],
            failed_transaction_count=summary["failed_transaction_count"],
            aborted_transaction_count=summary["aborted_transaction_count"],
            unique_account_count=summary["unique_account_count"],
            evidence_digest_sha256=evidence_digest,
            captured_at=captured_at,
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise WalletTraceEvidenceProviderFailure(
            "TonAPI persisted trace evidence candidate was incoherent."
        ) from exc

    try:
        session.add(capture)
        session.flush()
        persisted_nodes: list[WalletTraceEvidenceNode] = []
        for expected_index, node_data in enumerate(nodes):
            if (
                not isinstance(node_data, dict)
                or node_data.get("preorder_index") != expected_index
            ):
                raise WalletTraceEvidenceProviderFailure(
                    "TonAPI persisted trace node order was incoherent."
                )
            parent_index = node_data.get("parent_preorder_index")
            if parent_index is not None and (
                isinstance(parent_index, bool)
                or not isinstance(parent_index, int)
                or not 0 <= parent_index < expected_index
            ):
                raise WalletTraceEvidenceProviderFailure(
                    "TonAPI persisted trace parent order was incoherent."
                )
            parent_id = (
                None
                if parent_index is None
                else persisted_nodes[parent_index].id
            )
            node = WalletTraceEvidenceNode(
                capture_id=capture.id,
                preorder_index=expected_index,
                parent_node_id=parent_id,
                depth=node_data["depth"],
                transaction_hash=node_data["transaction_hash"],
                account_canonical=node_data["account_canonical"],
                logical_time=node_data["logical_time"],
                unix_time=node_data["unix_time"],
                success=node_data["success"],
                aborted=node_data["aborted"],
            )
            session.add(node)
            session.flush()
            persisted_nodes.append(node)
            message_groups = (
                ([node_data["in_message"]] if node_data["in_message"] else [])
                + node_data["out_messages"]
            )
            for message_data in message_groups:
                session.add(
                    WalletTraceEvidenceMessage(
                        node_id=node.id,
                        role=message_data["role"],
                        ordinal=message_data["ordinal"],
                        message_hash=message_data["message_hash"],
                        message_type=message_data["message_type"],
                        source_account_canonical=message_data[
                            "source_account_canonical"
                        ],
                        destination_account_canonical=message_data[
                            "destination_account_canonical"
                        ],
                        created_logical_time=message_data[
                            "created_logical_time"
                        ],
                        unix_time=message_data["unix_time"],
                        value_nanoton=message_data["value_nanoton"],
                        forward_fee_nanoton=message_data[
                            "forward_fee_nanoton"
                        ],
                        ihr_fee_nanoton=message_data["ihr_fee_nanoton"],
                        import_fee_nanoton=message_data[
                            "import_fee_nanoton"
                        ],
                        ihr_disabled=message_data["ihr_disabled"],
                        bounce=message_data["bounce"],
                        bounced=message_data["bounced"],
                        observation_identity_key=message_data[
                            "observation_identity_key"
                        ],
                    )
                )
        session.flush()
        persisted = _find_capture_for_transaction(
            run_id,
            transaction_hash,
            session,
        )
        if persisted is None:
            raise WalletPersistedTraceEvidenceConflict(
                "Persisted trace evidence could not be read before commit."
            )
        validated = _revalidate_capture(
            persisted,
            run,
            transaction,
            session,
        )
        session.commit()
        return validated, True
    except WalletTraceEvidenceProviderFailure:
        session.rollback()
        raise
    except IntegrityError as exc:
        session.rollback()
        concurrent = _find_capture_for_transaction(
            run_id,
            transaction_hash,
            session,
        )
        if concurrent is not None:
            return _revalidate_capture(
                concurrent,
                run,
                transaction,
                session,
            ), False
        raise WalletPersistedTraceEvidenceFailure(
            "Persisted trace evidence conflicted with existing evidence."
        ) from exc
    except (IndexError, KeyError, TypeError, ValueError, SQLAlchemyError) as exc:
        session.rollback()
        raise WalletPersistedTraceEvidenceFailure(
            "Persisted trace evidence could not be stored atomically."
        ) from exc


def _available_capture_slot(session: Session, run_id: int) -> int | None:
    slots = list(
        session.scalars(
            select(WalletTraceEvidenceCapture.capture_slot).where(
                WalletTraceEvidenceCapture.run_id == run_id
            )
        )
    )
    if (
        len(slots) > MAX_PERSISTED_TRACES_PER_RUN
        or any(
            isinstance(slot, bool)
            or not isinstance(slot, int)
            or not 0 <= slot < MAX_PERSISTED_TRACES_PER_RUN
            for slot in slots
        )
        or len(set(slots)) != len(slots)
    ):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence slots are incoherent."
        )
    used = set(slots)
    return next(
        (
            slot
            for slot in range(MAX_PERSISTED_TRACES_PER_RUN)
            if slot not in used
        ),
        None,
    )


def _find_capture_for_transaction(
    run_id: int,
    transaction_hash: str,
    session: Session,
) -> WalletTraceEvidenceCapture | None:
    captures = list(
        session.scalars(
            select(WalletTraceEvidenceCapture)
            .join(WalletTraceEvidenceNode)
            .where(WalletTraceEvidenceCapture.run_id == run_id)
            .where(WalletTraceEvidenceNode.transaction_hash == transaction_hash)
            .options(
                selectinload(WalletTraceEvidenceCapture.nodes).selectinload(
                    WalletTraceEvidenceNode.messages
                )
            )
            .limit(2)
        ).unique()
    )
    if len(captures) > 1:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence anchor is ambiguous."
        )
    return captures[0] if captures else None


def _revalidate_capture(
    capture: WalletTraceEvidenceCapture,
    run: Any,
    selected_transaction: WalletTransaction,
    session: Session,
) -> dict[str, Any]:
    if (
        capture.run_id != run.id
        or capture.provider != "tonapi"
        or capture.contract_version != PERSISTED_TRACE_CONTRACT_VERSION
        or capture.network != run.wallet_network
        or capture.trace_state != "finalized"
        or isinstance(capture.capture_slot, bool)
        or not isinstance(capture.capture_slot, int)
        or not 0 <= capture.capture_slot < MAX_PERSISTED_TRACES_PER_RUN
        or not _is_hash(capture.root_transaction_hash)
        or not _is_hash(capture.evidence_digest_sha256)
    ):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence metadata failed local revalidation."
        )

    captured_transaction = session.get(
        WalletTransaction,
        capture.captured_via_transaction_id,
    )
    if captured_transaction is None or captured_transaction.run_id != run.id:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence capture anchor is missing."
        )
    _require_eligible_stored_identity(
        run,
        captured_transaction,
        captured_transaction.transaction_hash_canonical or "",
    )

    nodes = sorted(capture.nodes, key=lambda item: item.preorder_index)
    if not 1 <= len(nodes) <= 256:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence has an invalid node count."
        )
    id_to_preorder: dict[int, int] = {}
    hashes: set[str] = set()
    coordinates: set[tuple[str, str]] = set()
    normalized_nodes: list[dict[str, Any]] = []
    selected_anchor: dict[str, str] | None = None
    captured_anchor_found = False
    accounts: set[str] = set()
    message_count = 0
    root_inbound_count = 0
    child_inbound_count = 0
    remaining_out_count = 0
    message_types = {key: 0 for key in _MESSAGE_TYPES}
    success_count = 0
    failed_count = 0
    aborted_count = 0
    max_depth = 0
    open_preorder_path: list[WalletTraceEvidenceNode] = []

    for expected_index, node in enumerate(nodes):
        if node.preorder_index != expected_index or node.id in id_to_preorder:
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace evidence preorder is incoherent."
            )
        id_to_preorder[node.id] = expected_index
        if (
            not _is_hash(node.transaction_hash)
            or not _is_account(node.account_canonical)
            or not _is_positive_uint64(node.logical_time)
            or isinstance(node.unix_time, bool)
            or not isinstance(node.unix_time, int)
            or not 0 <= node.unix_time <= 2**63 - 1
            or not isinstance(node.success, bool)
            or not isinstance(node.aborted, bool)
        ):
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace transaction fields are incoherent."
            )
        if node.transaction_hash in hashes:
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace evidence reuses a transaction hash."
            )
        coordinate = (node.account_canonical, node.logical_time)
        if coordinate in coordinates:
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace evidence reuses a transaction coordinate."
            )
        hashes.add(node.transaction_hash)
        coordinates.add(coordinate)
        accounts.add(node.account_canonical)

        if not 0 <= node.depth <= 32:
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace depth exceeds its contract."
            )

        if expected_index == 0:
            if node.parent_node_id is not None or node.depth != 0:
                raise WalletPersistedTraceEvidenceConflict(
                    "Stored trace root linkage is incoherent."
                )
            parent_index = None
            open_preorder_path = [node]
        else:
            parent_index = id_to_preorder.get(node.parent_node_id)
            if parent_index is None or parent_index >= expected_index:
                raise WalletPersistedTraceEvidenceConflict(
                    "Stored trace parent linkage is incoherent."
                )
            if node.depth != nodes[parent_index].depth + 1:
                raise WalletPersistedTraceEvidenceConflict(
                    "Stored trace depth is incoherent."
                )
            if (
                node.depth < 1
                or node.depth > len(open_preorder_path)
                or node.parent_node_id
                != open_preorder_path[node.depth - 1].id
            ):
                raise WalletPersistedTraceEvidenceConflict(
                    "Stored trace preorder traversal is incoherent."
                )
            open_preorder_path = open_preorder_path[: node.depth]
            open_preorder_path.append(node)
        max_depth = max(max_depth, node.depth)
        success_count += int(node.success)
        failed_count += int(not node.success)
        aborted_count += int(node.aborted)

        if node.transaction_hash == selected_transaction.transaction_hash_canonical:
            if selected_anchor is not None:
                raise WalletPersistedTraceEvidenceConflict(
                    "Stored trace selected anchor is ambiguous."
                )
            selected_anchor = {
                "transaction_hash": node.transaction_hash,
                "logical_time": node.logical_time,
                "account_canonical": node.account_canonical,
            }
        if node.transaction_hash == captured_transaction.transaction_hash_canonical:
            captured_anchor_found = (
                node.logical_time
                == captured_transaction.transaction_logical_time_canonical
                and node.account_canonical
                == captured_transaction.transaction_account_canonical
            )

        messages = sorted(
            node.messages,
            key=lambda item: (
                _role_sort_key(item.role),
                item.ordinal,
                item.id,
            ),
        )
        inbound: dict[str, Any] | None = None
        out_messages: list[dict[str, Any]] = []
        role_ordinals: dict[str, list[int]] = {role: [] for role in _MESSAGE_ROLES}
        for message in messages:
            normalized_message = _revalidate_message(
                message,
                capture,
                node,
                expected_index,
            )
            role_ordinals[message.role].append(message.ordinal)
            message_count += 1
            message_types[message.message_type] += 1
            if message.role == "root_inbound":
                root_inbound_count += 1
                if (
                    expected_index != 0
                    or inbound is not None
                    or message.message_type not in ("int_msg", "ext_in_msg")
                ):
                    raise WalletPersistedTraceEvidenceConflict(
                        "Stored trace root inbound role is incoherent."
                    )
                inbound = normalized_message
            elif message.role == "child_inbound":
                child_inbound_count += 1
                if expected_index == 0 or inbound is not None:
                    raise WalletPersistedTraceEvidenceConflict(
                        "Stored trace child inbound role is incoherent."
                    )
                parent = nodes[parent_index]
                if (
                    message.message_type != "int_msg"
                    or message.source_account_canonical
                    != parent.account_canonical
                    or message.destination_account_canonical
                    != node.account_canonical
                ):
                    raise WalletPersistedTraceEvidenceConflict(
                        "Stored trace child inbound linkage is incoherent."
                    )
                inbound = normalized_message
            else:
                if message.message_type not in ("int_msg", "ext_out_msg"):
                    raise WalletPersistedTraceEvidenceConflict(
                        "Stored trace remaining outgoing role is incoherent."
                    )
                remaining_out_count += 1
                out_messages.append(normalized_message)

        expected_inbound_role = (
            "root_inbound" if expected_index == 0 else "child_inbound"
        )
        if expected_index > 0 and inbound is None:
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace child is missing its internal inbound message."
            )
        if role_ordinals[expected_inbound_role] not in ([], [0]):
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace inbound message ordinal is incoherent."
            )
        other_inbound_role = (
            "child_inbound" if expected_index == 0 else "root_inbound"
        )
        if role_ordinals[other_inbound_role]:
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace inbound message role is incoherent."
            )
        if role_ordinals["remaining_outbound"] != list(range(len(out_messages))):
            raise WalletPersistedTraceEvidenceConflict(
                "Stored trace outgoing message ordinals are incoherent."
            )

        normalized_nodes.append(
            {
                "preorder_index": expected_index,
                "parent_preorder_index": parent_index,
                "depth": node.depth,
                "transaction_hash": node.transaction_hash,
                "account_canonical": node.account_canonical,
                "logical_time": node.logical_time,
                "unix_time": node.unix_time,
                "success": node.success,
                "aborted": node.aborted,
                "in_message": inbound,
                "out_messages": out_messages,
            }
        )

    if selected_anchor is None or not captured_anchor_found:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence did not preserve its transaction anchors."
        )
    if (
        selected_anchor["logical_time"]
        != selected_transaction.transaction_logical_time_canonical
        or selected_anchor["account_canonical"]
        != selected_transaction.transaction_account_canonical
    ):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence selected anchor changed identity."
        )
    if capture.root_transaction_hash != nodes[0].transaction_hash:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence root hash is incoherent."
        )
    if message_count > 2304 or remaining_out_count > 2048:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence exceeds its message limits."
        )
    if any(
        message.message_type == "int_msg"
        for node in nodes
        for message in node.messages
        if message.role == "remaining_outbound"
    ):
        raise WalletPersistedTraceEvidenceConflict(
            "A finalized stored trace cannot retain an internal outgoing message."
        )

    summary = {
        "root_transaction_hash": nodes[0].transaction_hash,
        "transaction_count": len(nodes),
        "max_depth": max_depth,
        "message_count": message_count,
        "root_inbound_message_count": root_inbound_count,
        "child_internal_message_count": child_inbound_count,
        "remaining_out_message_count": remaining_out_count,
        "internal_message_count": message_types["int_msg"],
        "external_in_message_count": message_types["ext_in_msg"],
        "external_out_message_count": message_types["ext_out_msg"],
        "successful_transaction_count": success_count,
        "failed_transaction_count": failed_count,
        "aborted_transaction_count": aborted_count,
        "unique_account_count": len(accounts),
    }
    _require_summary_matches_capture(summary, capture)
    captured_at = _canonical_utc_datetime(capture.captured_at)
    canonical = _canonical_document(
        {
            "trace_state": "finalized",
            "summary": summary,
            "nodes": normalized_nodes,
        },
        capture.network,
        run_id=capture.run_id,
        capture_slot=capture.capture_slot,
        captured_via_transaction=captured_transaction,
        captured_at=captured_at,
    )
    if _digest_document(canonical) != capture.evidence_digest_sha256:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence digest failed local revalidation."
        )

    return {
        "contract_version": PERSISTED_TRACE_CONTRACT_VERSION,
        "capture_id": str(capture.id),
        "run_id": str(run.id),
        "provider": "tonapi",
        "source_status": "live",
        "network": capture.network,
        "trace_state": "finalized",
        "captured_at": captured_at,
        "anchor": {
            **selected_anchor,
            "matches_stored_transaction": True,
        },
        "summary": summary,
        "evidence_digest_sha256": capture.evidence_digest_sha256,
        "is_provider_indexed_low_level_trace": True,
        "provider_structure_validated": True,
        "persisted_graph_revalidated": True,
        "is_immutable_record": True,
        "raw_boc_persisted": False,
        "message_body_persisted": False,
        "is_blockchain_proof_verified": False,
        "is_authoritative_activity_identity": False,
        "semantic_reconstruction_applied": False,
        "activity_merge_applied": False,
        "deduplication_applied": False,
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "is_ownership_proof": False,
        "message": (
            "A finalized provider-indexed trace graph was stored and its "
            "relational contract was revalidated locally. Raw BOCs and message "
            "bodies were not persisted, and no semantic activity reconstruction "
            "or blockchain proof verification was applied."
        ),
    }


def _revalidate_message(
    message: WalletTraceEvidenceMessage,
    capture: WalletTraceEvidenceCapture,
    node: WalletTraceEvidenceNode,
    preorder_index: int,
) -> dict[str, Any]:
    if (
        message.role not in _MESSAGE_ROLES
        or isinstance(message.ordinal, bool)
        or not isinstance(message.ordinal, int)
        or message.ordinal < 0
        or not _is_hash(message.message_hash)
        or message.message_type not in _MESSAGE_TYPES
        or (
            message.source_account_canonical is not None
            and not _is_account(message.source_account_canonical)
        )
        or (
            message.destination_account_canonical is not None
            and not _is_account(message.destination_account_canonical)
        )
        or not _is_nonnegative_uint64(message.created_logical_time)
        or isinstance(message.unix_time, bool)
        or not isinstance(message.unix_time, int)
        or not 0 <= message.unix_time <= 2**63 - 1
        or not _is_nonnegative_uint64(message.value_nanoton)
        or not _is_nonnegative_uint64(message.forward_fee_nanoton)
        or not _is_nonnegative_uint64(message.ihr_fee_nanoton)
        or not _is_nonnegative_uint64(message.import_fee_nanoton)
        or not isinstance(message.ihr_disabled, bool)
        or not isinstance(message.bounce, bool)
        or not isinstance(message.bounced, bool)
    ):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace message fields are incoherent."
        )
    if message.message_type == "int_msg" and (
        message.source_account_canonical is None
        or message.destination_account_canonical is None
    ):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored internal trace message is missing an account endpoint."
        )
    if message.message_type == "ext_in_msg" and (
        message.source_account_canonical is not None
        or message.destination_account_canonical is None
    ):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored external inbound trace message endpoints are incoherent."
        )
    if message.message_type == "ext_out_msg" and (
        message.source_account_canonical is None
        or message.destination_account_canonical is not None
    ):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored external outbound trace message endpoints are incoherent."
        )
    expected_identity = _message_observation_identity(
        capture.network,
        capture.root_transaction_hash,
        preorder_index,
        message.role,
        message.ordinal,
        message.message_hash,
    )
    if message.observation_identity_key != expected_identity:
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace message observation identity changed."
        )
    return {
        "role": message.role,
        "ordinal": message.ordinal,
        "message_hash": message.message_hash,
        "message_type": message.message_type,
        "source_account_canonical": message.source_account_canonical,
        "destination_account_canonical": (
            message.destination_account_canonical
        ),
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


def _canonical_document(
    normalized: dict[str, Any],
    network: str,
    *,
    run_id: int,
    capture_slot: int,
    captured_via_transaction: WalletTransaction,
    captured_at: datetime,
) -> dict[str, Any]:
    captured_at_utc = _canonical_utc_datetime(captured_at)
    return {
        "contract_version": PERSISTED_TRACE_CONTRACT_VERSION,
        "network": network,
        "provider": "tonapi",
        "capture_context": {
            "run_id": str(run_id),
            "capture_slot": capture_slot,
            "captured_via_transaction_id": str(captured_via_transaction.id),
            "captured_at": captured_at_utc.isoformat(
                timespec="microseconds"
            ).replace("+00:00", "Z"),
            "captured_via_anchor": {
                "transaction_hash": (
                    captured_via_transaction.transaction_hash_canonical
                ),
                "logical_time": (
                    captured_via_transaction.transaction_logical_time_canonical
                ),
                "account_canonical": (
                    captured_via_transaction.transaction_account_canonical
                ),
            },
        },
        "trace_state": normalized["trace_state"],
        "summary": normalized["summary"],
        "nodes": normalized["nodes"],
    }


def _canonical_utc_datetime(value: Any) -> datetime:
    if not isinstance(value, datetime):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence timestamp is invalid."
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _digest_document(document: dict[str, Any]) -> str:
    serialized = json.dumps(
        document,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _require_summary_matches_capture(
    summary: dict[str, Any],
    capture: WalletTraceEvidenceCapture,
) -> None:
    column_names = (
        "root_transaction_hash",
        "transaction_count",
        "max_depth",
        "message_count",
        "root_inbound_message_count",
        "child_internal_message_count",
        "remaining_out_message_count",
        "internal_message_count",
        "external_in_message_count",
        "external_out_message_count",
        "successful_transaction_count",
        "failed_transaction_count",
        "aborted_transaction_count",
        "unique_account_count",
    )
    if any(summary[name] != getattr(capture, name) for name in column_names):
        raise WalletPersistedTraceEvidenceConflict(
            "Stored trace evidence summary failed local revalidation."
        )


def _message_observation_identity(
    network: str,
    root_hash: str,
    preorder_index: int,
    role: str,
    ordinal: int,
    message_hash: str,
) -> str:
    return "|".join(
        (
            TRACE_MESSAGE_OBSERVATION_VERSION,
            network,
            root_hash,
            str(preorder_index),
            role,
            str(ordinal),
            message_hash,
        )
    )


def _role_sort_key(role: str) -> int:
    return {
        "root_inbound": 0,
        "child_inbound": 0,
        "remaining_outbound": 1,
    }.get(role, 99)


def _is_hash(value: Any) -> bool:
    return isinstance(value, str) and _HASH_RE.fullmatch(value) is not None


def _is_account(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    match = _ACCOUNT_RE.fullmatch(value)
    if match is None:
        return False
    workchain_text = value.split(":", 1)[0]
    workchain = int(workchain_text, 10)
    return -(2**31) <= workchain <= 2**31 - 1


def _is_positive_uint64(value: Any) -> bool:
    return (
        isinstance(value, str)
        and _POSITIVE_UINT64_RE.fullmatch(value) is not None
        and int(value, 10) <= 2**64 - 1
    )


def _is_nonnegative_uint64(value: Any) -> bool:
    return (
        isinstance(value, str)
        and _NONNEGATIVE_UINT64_RE.fullmatch(value) is not None
        and int(value, 10) <= 2**64 - 1
    )


__all__ = [
    "MAX_PERSISTED_TRACES_PER_RUN",
    "PERSISTED_TRACE_CONTRACT_VERSION",
    "WalletPersistedTraceEvidenceConflict",
    "WalletPersistedTraceEvidenceFailure",
    "capture_persisted_wallet_transaction_trace_evidence",
    "get_persisted_wallet_transaction_trace_evidence",
]
