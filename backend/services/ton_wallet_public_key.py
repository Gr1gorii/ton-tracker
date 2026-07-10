"""Resolve a wallet public key from proof-checked account state."""

from __future__ import annotations

import asyncio
from typing import Any

from pytoniq import LiteBalancer


class TonWalletPublicKeyFailure(RuntimeError):
    pass


async def _resolve_async(
    *, network: str, address: str, trust_level: int, timeout_seconds: int
) -> bytes:
    if network not in {"ton-mainnet", "ton-testnet"}:
        raise TonWalletPublicKeyFailure("Wallet network is invalid.")
    factory = (
        LiteBalancer.from_mainnet_config
        if network == "ton-mainnet"
        else LiteBalancer.from_testnet_config
    )
    client = factory(trust_level=trust_level, timeout=timeout_seconds)
    try:
        await client.start_up()
        anchor = client.last_mc_block
        account, _ = await client.raw_get_account_state(address, block=anchor)
        if account is None or account.storage.state.type_ != "account_active":
            raise TonWalletPublicKeyFailure("Wallet account is not active.")
        stack = await client.run_get_method_local(
            address, "get_public_key", [], block=anchor
        )
        if len(stack) != 1 or type(stack[0]) is not int or not 0 <= stack[0] < 2**256:
            raise TonWalletPublicKeyFailure("Wallet public-key getter is invalid.")
        return stack[0].to_bytes(32, "big")
    except TonWalletPublicKeyFailure:
        raise
    except Exception as exc:
        raise TonWalletPublicKeyFailure(
            "Proof-checked wallet public-key resolution failed."
        ) from exc
    finally:
        await client.close_all()


def resolve_wallet_public_key_live(**kwargs: Any) -> bytes:
    return asyncio.run(asyncio.wait_for(_resolve_async(**kwargs), timeout=180))
