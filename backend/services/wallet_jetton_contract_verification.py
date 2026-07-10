"""Immutable proof-checked jetton wallet/master relationship evidence."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any, Callable

from pytoniq_core import Cell
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import get_settings
from models import (
    WalletAccountStateInclusionProof,
    WalletBalanceSnapshot,
    WalletIngestionRun,
    WalletJettonContractVerification,
)
from services.ton_account_inclusion_proof import (
    TonAccountInclusionProofFailure,
    inclusion_hashes,
    verify_account_inclusion_proof,
)
from services.ton_address_identity import derive_ton_wallet_identity
from services.ton_liteclient_jetton_verifier import (
    TonLiteclientJettonVerificationFailure,
    verify_jetton_contract_relationship_live,
)


JETTON_CONTRACT_VERIFICATION_VERSION = "ton_jetton_contract_verification_v1"
JETTON_ASSET_IDENTITY_VERSION = "ton_jetton_asset_v1"


class WalletJettonContractVerificationNotFound(LookupError):
    """The run or exact persisted jetton snapshot relation was not found."""


class WalletJettonContractVerificationConflict(ValueError):
    """Persisted or live contract relationship evidence is incoherent."""


class WalletJettonContractVerificationFailure(RuntimeError):
    """The local proof verifier or immutable storage was unavailable."""


def verify_wallet_jetton_contract_relationship(
    run_id: int,
    jetton_wallet_account_canonical: str,
    jetton_master_account_canonical: str,
    session: Session,
    *,
    live_verifier: Callable[..., dict[str, Any]] = (
        verify_jetton_contract_relationship_live
    ),
) -> dict[str, Any]:
    """Verify and persist one exact selected-run jetton contract relation."""
    run = session.get(WalletIngestionRun, run_id)
    if run is None:
        raise WalletJettonContractVerificationNotFound(
            "Persisted wallet ingestion run not found."
        )
    network = _validated_run_network(run)
    wallet = _canonical_account(jetton_wallet_account_canonical, network)
    master = _canonical_account(jetton_master_account_canonical, network)
    if wallet != jetton_wallet_account_canonical or master != (
        jetton_master_account_canonical
    ):
        raise WalletJettonContractVerificationConflict(
            "Jetton verification addresses must be canonical raw TON addresses."
        )
    snapshot = _exact_snapshot(run_id, wallet, master, network, session)
    existing = session.scalar(
        select(WalletJettonContractVerification).where(
            WalletJettonContractVerification.run_id == run_id,
            WalletJettonContractVerification.jetton_wallet_account_canonical
            == wallet,
            WalletJettonContractVerification.jetton_master_account_canonical
            == master,
            WalletJettonContractVerification.contract_version
            == JETTON_CONTRACT_VERIFICATION_VERSION,
        )
    )
    if existing is not None:
        return _record_response(existing)

    settings = get_settings()
    try:
        verified = live_verifier(
            network=network,
            owner_account_canonical=run.wallet_address_canonical,
            jetton_wallet_account_canonical=wallet,
            jetton_master_account_canonical=master,
            trust_level=settings.ton_liteclient_trust_level,
            timeout_seconds=settings.ton_liteclient_timeout_seconds,
        )
    except TonLiteclientJettonVerificationFailure as exc:
        raise WalletJettonContractVerificationFailure(str(exc)) from exc
    _validate_live_result(
        verified,
        expected_trust_level=settings.ton_liteclient_trust_level,
        expected_wallet=wallet,
        expected_master=master,
    )
    verified_at = datetime.now(timezone.utc)
    values = {
        "run_id": run_id,
        "balance_snapshot_id": snapshot.id,
        "contract_version": JETTON_CONTRACT_VERIFICATION_VERSION,
        "verifier_name": verified["verifier_name"],
        "verifier_version": verified["verifier_version"],
        "network": network,
        "trust_level": verified["trust_level"],
        "anchor_workchain": verified["anchor"]["workchain"],
        "anchor_shard": verified["anchor"]["shard"],
        "anchor_seqno": verified["anchor"]["seqno"],
        "anchor_root_hash": verified["anchor"]["root_hash"],
        "anchor_file_hash": verified["anchor"]["file_hash"],
        "owner_account_canonical": run.wallet_address_canonical,
        "jetton_wallet_account_canonical": wallet,
        "jetton_master_account_canonical": master,
        "asset_identity_key": f"{JETTON_ASSET_IDENTITY_VERSION}|{network}|{master}",
        "wallet_balance_base_units": verified["wallet_balance_base_units"],
        "total_supply_base_units": verified["total_supply_base_units"],
        "mintable": verified["mintable"],
        "wallet_code_boc_hex": verified["wallet_code_boc_hex"],
        "wallet_data_boc_hex": verified["wallet_data_boc_hex"],
        "master_code_boc_hex": verified["master_code_boc_hex"],
        "master_data_boc_hex": verified["master_data_boc_hex"],
        "wallet_code_hash": verified["wallet_code_hash"],
        "wallet_data_hash": verified["wallet_data_hash"],
        "master_code_hash": verified["master_code_hash"],
        "master_data_hash": verified["master_data_hash"],
        "jetton_content_hash": verified["jetton_content_hash"],
        "verified_at": verified_at,
    }
    values["evidence_digest_sha256"] = _digest_json(
        _evidence_document(values)
    )
    record = WalletJettonContractVerification(**values)
    session.add(record)
    session.flush()
    for role, evidence in verified["account_inclusion_proofs"].items():
        proof_values = _account_proof_values(
            record,
            role,
            evidence,
            verified_at,
        )
        record.account_inclusion_proofs.append(
            WalletAccountStateInclusionProof(**proof_values)
        )
    session.flush()
    result = _record_response(record)
    session.commit()
    return result


def list_wallet_jetton_contract_verifications(
    run_id: int,
    session: Session,
) -> dict[str, Any]:
    run = session.get(WalletIngestionRun, run_id)
    if run is None:
        raise WalletJettonContractVerificationNotFound(
            "Persisted wallet ingestion run not found."
        )
    network = _validated_run_network(run)
    records = list(
        session.scalars(
            select(WalletJettonContractVerification)
            .where(WalletJettonContractVerification.run_id == run_id)
            .order_by(WalletJettonContractVerification.id)
        )
    )
    items = [_record_response(record) for record in records]
    document = {
        "contract_version": JETTON_CONTRACT_VERIFICATION_VERSION,
        "run_id": str(run_id),
        "network": network,
        "verification_count": len(items),
        "verification_digests": [
            item["evidence_digest_sha256"] for item in items
        ],
    }
    return {
        **document,
        "verifications": items,
        "catalog_digest_sha256": _digest_json(document),
        "provider_requests_performed": False,
        "raw_account_state_bocs_returned": False,
        "message": (
            "Stored jetton contract verifications were reparsed and digest-"
            "checked provider-free. Raw account state BOCs remain hidden."
        ),
    }


def _record_response(record: WalletJettonContractVerification) -> dict[str, Any]:
    values = {column.name: getattr(record, column.name) for column in record.__table__.columns}
    for field, hash_field in (
        ("wallet_code_boc_hex", "wallet_code_hash"),
        ("wallet_data_boc_hex", "wallet_data_hash"),
        ("master_code_boc_hex", "master_code_hash"),
        ("master_data_boc_hex", "master_data_hash"),
    ):
        cell = _one_boc(values[field], field)
        if cell.hash.hex() != values[hash_field]:
            raise WalletJettonContractVerificationConflict(
                "Stored jetton account-state BOC hash changed."
            )
    document = _evidence_document(values)
    digest = _digest_json(document)
    if digest != record.evidence_digest_sha256:
        raise WalletJettonContractVerificationConflict(
            "Stored jetton contract verification digest changed."
        )
    inclusion_proofs = _revalidate_account_inclusion_proofs(record)
    has_persisted_inclusion = len(inclusion_proofs) == 2
    return {
        "contract_version": record.contract_version,
        "verification_id": str(record.id),
        "run_id": str(record.run_id),
        "balance_snapshot_id": str(record.balance_snapshot_id),
        "verifier_name": record.verifier_name,
        "verifier_version": record.verifier_version,
        "network": record.network,
        "trust_level": record.trust_level,
        "anchor": document["anchor"],
        "owner_account_canonical": record.owner_account_canonical,
        "jetton_wallet_account_canonical": record.jetton_wallet_account_canonical,
        "jetton_master_account_canonical": record.jetton_master_account_canonical,
        "asset_identity_key": record.asset_identity_key,
        "wallet_balance_base_units": record.wallet_balance_base_units,
        "total_supply_base_units": record.total_supply_base_units,
        "mintable": record.mintable,
        "wallet_code_hash": record.wallet_code_hash,
        "wallet_data_hash": record.wallet_data_hash,
        "master_code_hash": record.master_code_hash,
        "master_data_hash": record.master_data_hash,
        "jetton_content_hash": record.jetton_content_hash,
        "account_state_boc_hashes": document["account_state_boc_hashes"],
        "account_state_inclusion_proofs": inclusion_proofs,
        "evidence_digest_sha256": digest,
        "verified_at": _iso(record.verified_at),
        "account_state_proof_verified": True,
        "masterchain_checkpoint_chain_verified": record.trust_level == 0,
        "local_tvm_execution_applied": True,
        "wallet_owner_master_verified": True,
        "master_wallet_address_verified": True,
        "wallet_code_consistency_verified": True,
        "jetton_asset_identity_applied": True,
        "raw_account_state_bocs_persisted": has_persisted_inclusion,
        "raw_account_state_bocs_returned": False,
        "is_blockchain_inclusion_proof_verified": (
            record.trust_level == 0 and has_persisted_inclusion
        ),
        "eligible_for_cost_basis": False,
        "used_by_pnl": False,
        "is_ownership_proof": False,
        "message": (
            (
                "Stored Merkle proofs bind both full account-state BOCs to exact "
                "shard blocks and the selected masterchain anchor. "
                if has_persisted_inclusion
                else "This legacy verification predates persisted Merkle proofs. "
            )
            + "Locally executed jetton getters agree on owner, master, wallet "
            "address, and wallet code. This establishes a network-scoped jetton "
            "asset relationship, not wallet ownership, complete activity history, "
            "cost basis, or PnL."
        ),
    }


def _evidence_document(values: dict[str, Any]) -> dict[str, Any]:
    return {
        "contract_version": values["contract_version"],
        "run_id": values["run_id"],
        "balance_snapshot_id": values["balance_snapshot_id"],
        "verifier_name": values["verifier_name"],
        "verifier_version": values["verifier_version"],
        "network": values["network"],
        "trust_level": values["trust_level"],
        "anchor": {
            "workchain": values["anchor_workchain"],
            "shard": values["anchor_shard"],
            "seqno": values["anchor_seqno"],
            "root_hash": values["anchor_root_hash"],
            "file_hash": values["anchor_file_hash"],
        },
        "owner_account_canonical": values["owner_account_canonical"],
        "jetton_wallet_account_canonical": values[
            "jetton_wallet_account_canonical"
        ],
        "jetton_master_account_canonical": values[
            "jetton_master_account_canonical"
        ],
        "asset_identity_key": values["asset_identity_key"],
        "wallet_balance_base_units": values["wallet_balance_base_units"],
        "total_supply_base_units": values["total_supply_base_units"],
        "mintable": values["mintable"],
        "wallet_code_hash": values["wallet_code_hash"],
        "wallet_data_hash": values["wallet_data_hash"],
        "master_code_hash": values["master_code_hash"],
        "master_data_hash": values["master_data_hash"],
        "jetton_content_hash": values["jetton_content_hash"],
        "account_state_boc_hashes": {
            field: hashlib.sha256(bytes.fromhex(values[field])).hexdigest()
            for field in (
                "wallet_code_boc_hex",
                "wallet_data_boc_hex",
                "master_code_boc_hex",
                "master_data_boc_hex",
            )
        },
        "verified_at": _iso(values["verified_at"]),
    }


def _exact_snapshot(
    run_id: int,
    wallet: str,
    master: str,
    network: str,
    session: Session,
) -> WalletBalanceSnapshot:
    matches = []
    snapshots = session.scalars(
        select(WalletBalanceSnapshot).where(
            WalletBalanceSnapshot.run_id == run_id,
            WalletBalanceSnapshot.provider == "tonapi",
            WalletBalanceSnapshot.source_status == "live",
        )
    )
    for snapshot in snapshots:
        try:
            raw = json.loads(snapshot.raw_json or "")
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(raw, dict) or raw.get("surface") != "jettons":
            continue
        raw_wallet = _canonical_account(raw.get("wallet_contract_address"), network)
        raw_master = _canonical_account(raw.get("jetton_address"), network)
        if raw_wallet == wallet and raw_master == master:
            matches.append(snapshot)
    if not matches:
        raise WalletJettonContractVerificationNotFound(
            "Exact persisted live TonAPI jetton snapshot relation not found."
        )
    if len(matches) != 1:
        raise WalletJettonContractVerificationConflict(
            "Multiple persisted snapshots claim the same run-scoped jetton relation."
        )
    return matches[0]


def _validated_run_network(run: WalletIngestionRun) -> str:
    if (
        run.data_mode != "real"
        or run.wallet_identity_status != "network_scoped"
        or run.wallet_network not in {"ton-mainnet", "ton-testnet"}
        or run.wallet_address_canonical is None
    ):
        raise WalletJettonContractVerificationConflict(
            "Jetton contract verification requires a real network-scoped run."
        )
    return run.wallet_network


def _canonical_account(value: Any, network: str) -> str | None:
    identity = derive_ton_wallet_identity(value, network_context=network)
    if identity.status != "network_scoped" or identity.network != network:
        return None
    return identity.canonical_address


def _validate_live_result(
    value: dict[str, Any],
    *,
    expected_trust_level: int,
    expected_wallet: str,
    expected_master: str,
) -> None:
    required = {
        "verifier_name",
        "verifier_version",
        "trust_level",
        "anchor",
        "wallet_balance_base_units",
        "total_supply_base_units",
        "mintable",
        "wallet_code_boc_hex",
        "wallet_data_boc_hex",
        "master_code_boc_hex",
        "master_data_boc_hex",
        "wallet_code_hash",
        "wallet_data_hash",
        "master_code_hash",
        "master_data_hash",
        "jetton_content_hash",
        "account_state_proof_verified",
        "masterchain_checkpoint_chain_verified",
        "local_tvm_execution_applied",
        "account_inclusion_proofs",
    }
    if not isinstance(value, dict) or set(value) != required:
        raise WalletJettonContractVerificationConflict(
            "Local jetton verifier returned an unexpected result contract."
        )
    anchor = value["anchor"]
    canonical_integer = re.compile(r"^(?:0|[1-9][0-9]*)$")
    canonical_hash = re.compile(r"^[0-9a-f]{64}$")
    canonical_shard = re.compile(r"^-?[0-9]{1,20}$")
    if not (
        value["verifier_name"] == "pytoniq-pytvm"
        and isinstance(value["verifier_version"], str)
        and 1 <= len(value["verifier_version"]) <= 48
        and type(value["trust_level"]) is int
        and value["trust_level"] == expected_trust_level
        and isinstance(anchor, dict)
        and set(anchor)
        == {"workchain", "shard", "seqno", "root_hash", "file_hash"}
        and type(anchor["workchain"]) is int
        and anchor["workchain"] in {-1, 0}
        and isinstance(anchor["shard"], str)
        and canonical_shard.fullmatch(anchor["shard"])
        and type(anchor["seqno"]) is int
        and anchor["seqno"] > 0
        and isinstance(anchor["root_hash"], str)
        and canonical_hash.fullmatch(anchor["root_hash"])
        and isinstance(anchor["file_hash"], str)
        and canonical_hash.fullmatch(anchor["file_hash"])
        and isinstance(value["wallet_balance_base_units"], str)
        and len(value["wallet_balance_base_units"]) <= 80
        and canonical_integer.fullmatch(value["wallet_balance_base_units"])
        and isinstance(value["total_supply_base_units"], str)
        and len(value["total_supply_base_units"]) <= 80
        and canonical_integer.fullmatch(value["total_supply_base_units"])
        and type(value["mintable"]) is bool
        and isinstance(value["jetton_content_hash"], str)
        and canonical_hash.fullmatch(value["jetton_content_hash"])
    ):
        raise WalletJettonContractVerificationConflict(
            "Local jetton verifier returned malformed bounded evidence."
        )
    if not (
        value["account_state_proof_verified"] is True
        and value["local_tvm_execution_applied"] is True
        and value["masterchain_checkpoint_chain_verified"]
        == (value["trust_level"] == 0)
    ):
        raise WalletJettonContractVerificationConflict(
            "Local jetton verifier proof flags are incoherent."
        )
    for field, hash_field in (
        ("wallet_code_boc_hex", "wallet_code_hash"),
        ("wallet_data_boc_hex", "wallet_data_hash"),
        ("master_code_boc_hex", "master_code_hash"),
        ("master_data_boc_hex", "master_data_hash"),
    ):
        if not (
            isinstance(value[hash_field], str)
            and canonical_hash.fullmatch(value[hash_field])
            and _one_boc(value[field], field).hash.hex() == value[hash_field]
        ):
            raise WalletJettonContractVerificationConflict(
                "Local jetton verifier BOC/hash evidence is incoherent."
            )
    proofs = value["account_inclusion_proofs"]
    if not isinstance(proofs, dict) or set(proofs) != {
        "jetton_wallet",
        "jetton_master",
    }:
        raise WalletJettonContractVerificationConflict(
            "Local jetton verifier omitted account inclusion evidence."
        )
    expected_addresses = {
        "jetton_wallet": expected_wallet,
        "jetton_master": expected_master,
    }
    if any(
        not _valid_account_inclusion_shape(proofs[role], expected_addresses[role])
        for role in proofs
    ):
        raise WalletJettonContractVerificationConflict(
            "Local account inclusion evidence is malformed."
        )


def _account_proof_values(
    record: WalletJettonContractVerification,
    role: str,
    evidence: dict[str, Any],
    verified_at: datetime,
) -> dict[str, Any]:
    expected_address = (
        record.jetton_wallet_account_canonical
        if role == "jetton_wallet"
        else record.jetton_master_account_canonical
    )
    if not _valid_account_inclusion_shape(evidence, expected_address):
        raise WalletJettonContractVerificationConflict(
            "Account inclusion evidence changed before persistence."
        )
    _verify_and_match_account_proof(record, role, evidence)
    hashes = inclusion_hashes(evidence)
    shard = evidence["shard_block"]
    document = {
        "contract_version": "ton_account_state_inclusion_v1",
        "verification_id": record.id,
        "account_role": role,
        "account_address_canonical": expected_address,
        "masterchain_anchor": {
            "workchain": record.anchor_workchain,
            "shard": int(record.anchor_shard),
            "seqno": record.anchor_seqno,
            "root_hash": record.anchor_root_hash,
            "file_hash": record.anchor_file_hash,
        },
        "shard_block": shard,
        "boc_sha256": hashes,
        "verified_at": _iso(verified_at),
    }
    return {
        "account_role": role,
        "account_address_canonical": expected_address,
        "shard_workchain": shard["workchain"],
        "shard": str(shard["shard"]),
        "shard_seqno": shard["seqno"],
        "shard_root_hash": shard["root_hash"],
        "shard_file_hash": shard["file_hash"],
        "state_boc_hex": evidence["state_boc_hex"],
        "account_proof_boc_hex": evidence["account_proof_boc_hex"],
        "shard_proof_boc_hex": evidence["shard_proof_boc_hex"],
        "state_boc_sha256": hashes["state_boc_hex"],
        "account_proof_boc_sha256": hashes["account_proof_boc_hex"],
        "shard_proof_boc_sha256": hashes["shard_proof_boc_hex"],
        "evidence_digest_sha256": _digest_json(document),
        "verified_at": verified_at,
    }


def _revalidate_account_inclusion_proofs(
    record: WalletJettonContractVerification,
) -> list[dict[str, Any]]:
    proofs = sorted(record.account_inclusion_proofs, key=lambda row: row.account_role)
    if not proofs:
        return []
    if [row.account_role for row in proofs] != ["jetton_master", "jetton_wallet"]:
        raise WalletJettonContractVerificationConflict(
            "Stored jetton verification does not contain both account proofs."
        )
    result = []
    for row in proofs:
        evidence = {
            "account_address": row.account_address_canonical,
            "shard_block": {
                "workchain": row.shard_workchain,
                "shard": int(row.shard),
                "seqno": row.shard_seqno,
                "root_hash": row.shard_root_hash,
                "file_hash": row.shard_file_hash,
            },
            "state_boc_hex": row.state_boc_hex,
            "account_proof_boc_hex": row.account_proof_boc_hex,
            "shard_proof_boc_hex": row.shard_proof_boc_hex,
        }
        expected = _account_proof_values(
            record,
            row.account_role,
            evidence,
            row.verified_at,
        )
        for field in (
            "account_address_canonical",
            "shard_workchain",
            "shard",
            "shard_seqno",
            "shard_root_hash",
            "shard_file_hash",
            "state_boc_sha256",
            "account_proof_boc_sha256",
            "shard_proof_boc_sha256",
            "evidence_digest_sha256",
        ):
            if getattr(row, field) != expected[field]:
                raise WalletJettonContractVerificationConflict(
                    "Stored account inclusion proof digest or metadata changed."
                )
        result.append(
            {
                "contract_version": "ton_account_state_inclusion_v1",
                "account_role": row.account_role,
                "account_address_canonical": row.account_address_canonical,
                "shard_block": {
                    **evidence["shard_block"],
                    "shard": row.shard,
                },
                "boc_sha256": {
                    "state_boc_hex": row.state_boc_sha256,
                    "account_proof_boc_hex": row.account_proof_boc_sha256,
                    "shard_proof_boc_hex": row.shard_proof_boc_sha256,
                },
                "evidence_digest_sha256": row.evidence_digest_sha256,
                "verified_at": _iso(row.verified_at),
                "provider_requests_performed": False,
                "provider_free_revalidated": True,
                "raw_bocs_returned": False,
            }
        )
    return result


def _verify_and_match_account_proof(
    record: WalletJettonContractVerification,
    role: str,
    evidence: dict[str, Any],
) -> None:
    anchor = {
        "workchain": record.anchor_workchain,
        "shard": int(record.anchor_shard),
        "seqno": record.anchor_seqno,
        "root_hash": record.anchor_root_hash,
        "file_hash": record.anchor_file_hash,
    }
    try:
        account = verify_account_inclusion_proof(
            evidence,
            masterchain_anchor=anchor,
        )
        state = account.storage.state.state_init
        expected_code = (
            record.wallet_code_hash if role == "jetton_wallet" else record.master_code_hash
        )
        expected_data = (
            record.wallet_data_hash if role == "jetton_wallet" else record.master_data_hash
        )
        if (
            account.storage.state.type_ != "account_active"
            or state.code is None
            or state.data is None
            or state.code.hash.hex() != expected_code
            or state.data.hash.hex() != expected_data
        ):
            raise WalletJettonContractVerificationConflict(
                "Proved full account state differs from stored code/data BOCs."
            )
    except TonAccountInclusionProofFailure as exc:
        raise WalletJettonContractVerificationConflict(str(exc)) from exc


def _valid_account_inclusion_shape(value: Any, expected_address: str) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "account_address",
        "shard_block",
        "state_boc_hex",
        "account_proof_boc_hex",
        "shard_proof_boc_hex",
    }:
        return False
    shard = value["shard_block"]
    canonical_hash = re.compile(r"^[0-9a-f]{64}$")
    if not (
        value["account_address"] == expected_address
        and isinstance(shard, dict)
        and set(shard) == {"workchain", "shard", "seqno", "root_hash", "file_hash"}
        and type(shard["workchain"]) is int
        and shard["workchain"] in {-1, 0}
        and type(shard["shard"]) is int
        and type(shard["seqno"]) is int
        and shard["seqno"] > 0
        and canonical_hash.fullmatch(shard["root_hash"] or "")
        and canonical_hash.fullmatch(shard["file_hash"] or "")
    ):
        return False
    for field in (
        "state_boc_hex",
        "account_proof_boc_hex",
        "shard_proof_boc_hex",
    ):
        raw = value[field]
        if (
            not isinstance(raw, str)
            or not raw
            or len(raw) > 8 * 1024 * 1024
            or len(raw) % 2
            or raw != raw.lower()
        ):
            return False
        try:
            bytes.fromhex(raw)
        except ValueError:
            return False
    return True


def _one_boc(value: Any, field: str) -> Cell:
    if (
        not isinstance(value, str)
        or len(value) > 2 * 1024 * 1024
        or len(value) % 2
        or value != value.lower()
    ):
        raise WalletJettonContractVerificationConflict(
            f"Stored {field} is not a bounded canonical BOC."
        )
    try:
        roots = Cell.from_boc(bytes.fromhex(value))
    except Exception as exc:
        raise WalletJettonContractVerificationConflict(
            f"Stored {field} could not be reparsed."
        ) from exc
    if len(roots) != 1:
        raise WalletJettonContractVerificationConflict(
            f"Stored {field} must contain exactly one BOC root."
        )
    return roots[0]


def _digest_json(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


__all__ = [
    "JETTON_ASSET_IDENTITY_VERSION",
    "JETTON_CONTRACT_VERIFICATION_VERSION",
    "WalletJettonContractVerificationConflict",
    "WalletJettonContractVerificationFailure",
    "WalletJettonContractVerificationNotFound",
    "list_wallet_jetton_contract_verifications",
    "verify_wallet_jetton_contract_relationship",
]
