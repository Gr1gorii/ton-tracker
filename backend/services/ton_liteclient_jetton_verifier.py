"""Proof-checked account state and local TVM jetton relationship verifier."""

from __future__ import annotations

import asyncio
from importlib.metadata import version
from typing import Any

from pytoniq import LiteBalancer
from pytoniq_core import Address, Cell, Slice, begin_cell

from services.ton_account_inclusion_proof import (
    TonAccountInclusionProofFailure,
    capture_account_inclusion_proof,
)


class TonLiteclientJettonVerificationFailure(RuntimeError):
    """Liteserver proof retrieval or local TVM execution failed."""


async def verify_jetton_contract_relationship_async(
    *,
    network: str,
    owner_account_canonical: str,
    jetton_wallet_account_canonical: str,
    jetton_master_account_canonical: str,
    trust_level: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    """Verify one wallet/master relationship at one masterchain anchor."""
    if network == "ton-mainnet":
        client = LiteBalancer.from_mainnet_config(
            trust_level=trust_level,
            timeout=timeout_seconds,
        )
    elif network == "ton-testnet":
        client = LiteBalancer.from_testnet_config(
            trust_level=trust_level,
            timeout=timeout_seconds,
        )
    else:
        raise TonLiteclientJettonVerificationFailure(
            "Jetton contract verification requires a scoped TON network."
        )

    try:
        await client.start_up()
        anchor = client.last_mc_block
        if anchor is None:
            raise TonLiteclientJettonVerificationFailure(
                "Liteserver consensus did not produce a masterchain anchor."
            )
        wallet_account, wallet_inclusion = await capture_account_inclusion_proof(
            client,
            account_address=jetton_wallet_account_canonical,
            masterchain_anchor=anchor,
        )
        master_account, master_inclusion = await capture_account_inclusion_proof(
            client,
            account_address=jetton_master_account_canonical,
            masterchain_anchor=anchor,
        )
        wallet_state = _active_state(wallet_account, "jetton wallet")
        master_state = _active_state(master_account, "jetton master")

        wallet_stack = await client.run_get_method_local(
            jetton_wallet_account_canonical,
            "get_wallet_data",
            [],
            block=anchor,
        )
        wallet_data = _decode_wallet_data(wallet_stack)
        owner = Address(owner_account_canonical)
        master = Address(jetton_master_account_canonical)
        wallet = Address(jetton_wallet_account_canonical)
        if wallet_data["owner"] != owner:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton wallet getter owner does not match the persisted run wallet."
            )
        if wallet_data["master"] != master:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton wallet getter master does not match the persisted snapshot."
            )

        wallet_address_stack = await client.run_get_method_local(
            jetton_master_account_canonical,
            "get_wallet_address",
            [begin_cell().store_address(owner).end_cell().begin_parse()],
            block=anchor,
        )
        derived_wallet = _single_address(wallet_address_stack)
        if derived_wallet != wallet:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton master getter derived a different wallet address."
            )

        master_stack = await client.run_get_method_local(
            jetton_master_account_canonical,
            "get_jetton_data",
            [],
            block=anchor,
        )
        master_data = _decode_master_data(master_stack)
        wallet_code = wallet_data["wallet_code"]
        if wallet_state.code.hash != wallet_code.hash:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton wallet account code differs from get_wallet_data code."
            )
        if master_data["wallet_code"].hash != wallet_code.hash:
            raise TonLiteclientJettonVerificationFailure(
                "Jetton master and wallet getters disagree on wallet code."
            )

        return {
            "verifier_name": "pytoniq-pytvm",
            "verifier_version": (
                f"pytoniq-{version('pytoniq')}/pytvm-{version('pytvm')}"
            ),
            "trust_level": trust_level,
            "anchor": {
                "workchain": anchor.workchain,
                "shard": str(anchor.shard),
                "seqno": anchor.seqno,
                "root_hash": anchor.root_hash.hex(),
                "file_hash": anchor.file_hash.hex(),
            },
            "wallet_balance_base_units": str(wallet_data["balance"]),
            "total_supply_base_units": str(master_data["total_supply"]),
            "mintable": master_data["mintable"],
            "wallet_code_boc_hex": wallet_state.code.to_boc().hex(),
            "wallet_data_boc_hex": wallet_state.data.to_boc().hex(),
            "master_code_boc_hex": master_state.code.to_boc().hex(),
            "master_data_boc_hex": master_state.data.to_boc().hex(),
            "wallet_code_hash": wallet_state.code.hash.hex(),
            "wallet_data_hash": wallet_state.data.hash.hex(),
            "master_code_hash": master_state.code.hash.hex(),
            "master_data_hash": master_state.data.hash.hex(),
            "jetton_content_hash": master_data["content"].hash.hex(),
            "account_state_proof_verified": True,
            "masterchain_checkpoint_chain_verified": trust_level == 0,
            "local_tvm_execution_applied": True,
            "account_inclusion_proofs": {
                "jetton_wallet": wallet_inclusion,
                "jetton_master": master_inclusion,
            },
        }
    except TonLiteclientJettonVerificationFailure:
        raise
    except TonAccountInclusionProofFailure as exc:
        raise TonLiteclientJettonVerificationFailure(str(exc)) from exc
    except Exception as exc:
        raise TonLiteclientJettonVerificationFailure(
            "Proof-checked jetton contract verification failed."
        ) from exc
    finally:
        await client.close_all()


def verify_jetton_contract_relationship_live(**kwargs: Any) -> dict[str, Any]:
    timeout = int(kwargs["timeout_seconds"])
    try:
        return asyncio.run(
            asyncio.wait_for(
                verify_jetton_contract_relationship_async(**kwargs),
                timeout=max(30, timeout * 8),
            )
        )
    except TonLiteclientJettonVerificationFailure:
        raise
    except Exception as exc:
        raise TonLiteclientJettonVerificationFailure(
            "Proof-checked jetton contract verification timed out or failed."
        ) from exc


def _active_state(account: Any, label: str) -> Any:
    if account is None or account.storage.state.type_ != "account_active":
        raise TonLiteclientJettonVerificationFailure(
            f"The {label} account is not active at the verification anchor."
        )
    state = account.storage.state.state_init
    if state.code is None or state.data is None:
        raise TonLiteclientJettonVerificationFailure(
            f"The {label} account has no complete code/data state."
        )
    return state


def _decode_wallet_data(stack: list[Any]) -> dict[str, Any]:
    if (
        len(stack) != 4
        or isinstance(stack[0], bool)
        or not isinstance(stack[0], int)
        or stack[0] < 0
        or not isinstance(stack[1], Slice)
        or not isinstance(stack[2], Slice)
        or not isinstance(stack[3], Cell)
    ):
        raise TonLiteclientJettonVerificationFailure(
            "get_wallet_data returned an invalid stack shape."
        )
    return {
        "balance": stack[0],
        "owner": _address_from_slice(stack[1]),
        "master": _address_from_slice(stack[2]),
        "wallet_code": stack[3],
    }


def _decode_master_data(stack: list[Any]) -> dict[str, Any]:
    if (
        len(stack) != 5
        or isinstance(stack[0], bool)
        or not isinstance(stack[0], int)
        or stack[0] < 0
        or isinstance(stack[1], bool)
        or not isinstance(stack[1], int)
        or not isinstance(stack[2], Slice)
        or not isinstance(stack[3], Cell)
        or not isinstance(stack[4], Cell)
    ):
        raise TonLiteclientJettonVerificationFailure(
            "get_jetton_data returned an invalid stack shape."
        )
    _address_from_slice(stack[2], allow_none=True)
    return {
        "total_supply": stack[0],
        "mintable": stack[1] != 0,
        "content": stack[3],
        "wallet_code": stack[4],
    }


def _single_address(stack: list[Any]) -> Address:
    if len(stack) != 1 or not isinstance(stack[0], Slice):
        raise TonLiteclientJettonVerificationFailure(
            "get_wallet_address returned an invalid stack shape."
        )
    address = _address_from_slice(stack[0])
    if address is None:  # pragma: no cover - guarded by allow_none=False
        raise TonLiteclientJettonVerificationFailure(
            "get_wallet_address returned no address."
        )
    return address


def _address_from_slice(
    value: Slice,
    *,
    allow_none: bool = False,
) -> Address | None:
    source = value.copy()
    try:
        address = source.load_address()
    except Exception as exc:
        raise TonLiteclientJettonVerificationFailure(
            "Jetton getter returned a malformed address slice."
        ) from exc
    if source.remaining_bits or source.remaining_refs:
        raise TonLiteclientJettonVerificationFailure(
            "Jetton getter address slice contains trailing data."
        )
    if address is None and not allow_none:
        raise TonLiteclientJettonVerificationFailure(
            "Jetton getter returned an absent required address."
        )
    return address


__all__ = [
    "TonLiteclientJettonVerificationFailure",
    "verify_jetton_contract_relationship_async",
    "verify_jetton_contract_relationship_live",
]
