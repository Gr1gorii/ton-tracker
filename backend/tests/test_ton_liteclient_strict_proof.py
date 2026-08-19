"""Adversarial parity tests for the application-owned TON proof verifier."""

from __future__ import annotations

import hashlib
from types import SimpleNamespace
from typing import Any

import pytest
from pytoniq_core.tl.block import BlockIdExt

from services import ton_liteclient_strict_proof as strict


MC_SHARD = -(2**63)


def _block(seqno: int, marker: int) -> BlockIdExt:
    return BlockIdExt(
        workchain=-1,
        shard=MC_SHARD,
        seqno=seqno,
        root_hash=bytes([marker]) * 32,
        file_hash=bytes([marker + 64]) * 32,
    )


class _Root:
    def __init__(self, hash_: bytes, value: Any, *, state_hash: bytes | None = None):
        self.hash_ = hash_
        self.value = value
        self.state_hash = state_hash

    def begin_parse(self) -> Any:
        return self.value

    def get_hash(self, level: int) -> bytes:
        assert level == 0
        return self.hash_


class _Wrapper:
    def __init__(self, root: _Root, bound_hash: bytes):
        self.refs = [root]
        self.bound_hash = bound_hash

    def __getitem__(self, index: int) -> _Root:
        return self.refs[index]


def _info(
    block: BlockIdExt,
    *,
    key_block: bool,
    validator_hash: int = 0,
    catchain_seqno: int = 9,
    gen_utime: int = 1_800_000_000,
) -> SimpleNamespace:
    shard = SimpleNamespace(
        workchain_id=-1,
        calculate_shard_signed=lambda: MC_SHARD,
    )
    return SimpleNamespace(
        version=0,
        not_master=False,
        seqno=block.seqno,
        shard=shard,
        key_block=key_block,
        gen_validator_list_hash_short=validator_hash,
        gen_catchain_seqno=catchain_seqno,
        gen_utime=gen_utime,
    )


def _validator(marker: int, weight: int = 1) -> SimpleNamespace:
    return SimpleNamespace(
        public_key=SimpleNamespace(pubkey=bytes([marker]) * 32),
        weight=weight,
        adnl_addr=bytes([marker + 32]) * 32,
    )


def _install_fake_codec(
    monkeypatch: pytest.MonkeyPatch,
    wrappers: dict[bytes, _Wrapper],
) -> None:
    monkeypatch.setattr(
        strict,
        "Cell",
        SimpleNamespace(one_from_boc=lambda value: wrappers[value]),
    )

    def check_proof(wrapper: _Wrapper, expected_hash: bytes) -> None:
        if (
            wrapper.bound_hash != expected_hash
            or wrapper[0].get_hash(0) != expected_hash
        ):
            raise ValueError("unbound Merkle proof")

    def check_header(root: _Root, expected_hash: bytes, store_state=False):
        if root.get_hash(0) != expected_hash:
            raise ValueError("wrong block root")
        return root.state_hash if store_state else None

    monkeypatch.setattr(strict, "check_proof", check_proof)
    monkeypatch.setattr(strict, "check_block_header_proof", check_header)
    monkeypatch.setattr(
        strict,
        "Block",
        SimpleNamespace(deserialize=lambda value: value),
    )
    monkeypatch.setattr(
        strict,
        "calculate_node_id_short",
        lambda public_key: hashlib.sha256(public_key).digest(),
    )
    monkeypatch.setattr(strict, "verify_sign", lambda **kwargs: True)


def _forward_fixture(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    source = _block(100, 1)
    destination = _block(120, 2)
    nodes = [_validator(3), _validator(4), _validator(5)]
    validators = SimpleNamespace(
        total=3,
        main=3,
        list=dict(enumerate(nodes)),
        total_weight=3,
    )
    catchain = SimpleNamespace(shuffle_mc_validators=False)
    validator_hash = strict.compute_validator_set_hash(9, nodes)
    source_info = _info(source, key_block=True)
    destination_info = _info(
        destination,
        key_block=False,
        validator_hash=validator_hash,
    )
    source_config = {
        28: catchain,
        34: SimpleNamespace(cur_validators=SimpleNamespace(total=0)),
        35: SimpleNamespace(cur_temp_validators=validators),
    }
    source_block = SimpleNamespace(
        info=source_info,
        extra=SimpleNamespace(
            custom=SimpleNamespace(
                key_block=True,
                config=SimpleNamespace(config=source_config),
            )
        ),
    )
    destination_block = SimpleNamespace(info=destination_info)
    wrappers = {
        b"source": _Wrapper(_Root(source.root_hash, source_block), source.root_hash),
        b"destination": _Wrapper(
            _Root(destination.root_hash, destination_block),
            destination.root_hash,
        ),
    }
    _install_fake_codec(monkeypatch, wrappers)
    monkeypatch.setattr(
        strict,
        "ConfigParam28",
        SimpleNamespace(deserialize=lambda value: value),
    )
    monkeypatch.setattr(
        strict,
        "ConfigParam35",
        SimpleNamespace(deserialize=lambda value: value),
    )
    monkeypatch.setattr(
        strict,
        "ConfigParam34",
        SimpleNamespace(
            deserialize=lambda value: pytest.fail(
                "parameter 35 must take precedence over parameter 34"
            )
        ),
    )
    signatures = [
        {
            "node_id_short": hashlib.sha256(node.public_key.pubkey).hexdigest(),
            "signature": bytes([index + 10]) * 64,
        }
        for index, node in enumerate(nodes)
    ]
    step = {
        "from": source.to_dict(),
        "to": destination.to_dict(),
        "to_key_block": False,
        "config_proof": b"source",
        "dest_proof": b"destination",
        "signatures": {
            "catchain_seqno": 9,
            "validator_set_hash": validator_hash,
            "signatures": signatures,
        },
    }
    return {
        "source": source,
        "destination": destination,
        "nodes": nodes,
        "validators": validators,
        "source_info": source_info,
        "destination_info": destination_info,
        "wrappers": wrappers,
        "step": step,
        "result": {
            "complete": True,
            "from": source.to_dict(),
            "to": destination.to_dict(),
            "steps": [step],
        },
        "client": SimpleNamespace(last_key_block=None),
    }


def _verify_forward(context: dict[str, Any]):
    return strict.verify_masterchain_proof_response(
        context["client"],
        known_block=context["source"],
        target_block=context["destination"],
        result=context["result"],
        return_best_key_block=True,
    )


def test_crc32c_matches_castagnoli_reference_vector() -> None:
    assert strict.crc32c(b"123456789") == 0xE3069283


def test_forward_link_binds_source_and_uses_temporary_validator_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _forward_fixture(monkeypatch)

    complete, last, best_key, best_key_time = _verify_forward(context)

    assert complete is True
    assert last == context["destination"]
    assert best_key == context["source"]
    assert best_key_time == context["source_info"].gen_utime
    assert context["client"].last_key_block == context["source"]


def test_forward_link_falls_back_to_persistent_validator_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _forward_fixture(monkeypatch)
    config = context["wrappers"][b"source"][0].value.extra.custom.config.config
    config[34] = SimpleNamespace(cur_validators=context["validators"])
    del config[35]
    monkeypatch.setattr(
        strict,
        "ConfigParam34",
        SimpleNamespace(deserialize=lambda value: value),
    )

    assert _verify_forward(context)[0] is True


def test_forward_link_rejects_unbound_attacker_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _forward_fixture(monkeypatch)
    context["wrappers"][b"source"].bound_hash = b"x" * 32

    with pytest.raises(strict.TonLiteclientStrictProofFailure):
        _verify_forward(context)


@pytest.mark.parametrize(
    "mutation",
    [
        "header_hash",
        "signature_hash",
        "signature_catchain",
        "duplicate_signer",
        "exact_two_thirds",
        "invalid_signature",
        "source_header_version",
    ],
)
def test_forward_link_rejects_unbound_validator_or_signature_metadata(
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    context = _forward_fixture(monkeypatch)
    signatures = context["step"]["signatures"]
    if mutation == "header_hash":
        context["destination_info"].gen_validator_list_hash_short ^= 1
    elif mutation == "signature_hash":
        signatures["validator_set_hash"] ^= 1
    elif mutation == "signature_catchain":
        signatures["catchain_seqno"] += 1
    elif mutation == "duplicate_signer":
        signatures["signatures"][1]["node_id_short"] = signatures["signatures"][0][
            "node_id_short"
        ]
    elif mutation == "exact_two_thirds":
        signatures["signatures"] = signatures["signatures"][:2]
    elif mutation == "source_header_version":
        context["source_info"].version = 1
    else:
        signatures["signatures"][0]["signature"] = b"s" * 63

    with pytest.raises(strict.TonLiteclientStrictProofFailure):
        _verify_forward(context)


def test_forward_signatures_bind_destination_root_and_file_hash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _forward_fixture(monkeypatch)
    messages: list[bytes] = []

    def verify(**kwargs) -> bool:
        messages.append(kwargs["signed_message"])
        return True

    monkeypatch.setattr(strict, "verify_sign", verify)
    _verify_forward(context)

    assert messages == [
        b"pn\x0b\xc5"
        + context["destination"].root_hash
        + context["destination"].file_hash
    ] * 3


def test_validator_hash_matches_official_tl_crc32c_vector() -> None:
    nodes = [_validator(1, 5), _validator(2, 7)]

    assert strict.compute_validator_set_hash(0x11223344, nodes) == 0x68179053


def test_validator_set_rejects_wrong_declared_or_excessive_weight() -> None:
    nodes = [_validator(1, 2**60), _validator(2, 2**60 + 1)]
    validators = SimpleNamespace(
        total=2,
        main=2,
        list=dict(enumerate(nodes)),
        total_weight=2**61 + 1,
    )
    catchain = SimpleNamespace(shuffle_mc_validators=False)

    with pytest.raises(strict.TonLiteclientStrictProofFailure):
        strict.compute_masterchain_validator_set(catchain, validators, 1)

    nodes[1].weight = 2**60
    validators.total_weight = 123
    with pytest.raises(strict.TonLiteclientStrictProofFailure):
        strict.compute_masterchain_validator_set(catchain, validators, 1)


def test_masterchain_validator_shuffle_matches_official_prng_vector() -> None:
    nodes = [_validator(index) for index in range(1, 9)]
    validators = SimpleNamespace(
        total=8,
        main=8,
        list=dict(enumerate(nodes)),
        total_weight=8,
    )
    catchain = SimpleNamespace(shuffle_mc_validators=True)

    selected = strict.compute_masterchain_validator_set(catchain, validators, 9)

    assert [node.public_key.pubkey[0] for node in selected] == [
        7,
        3,
        6,
        5,
        4,
        8,
        1,
        2,
    ]


def test_backward_link_uses_full_previous_block_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _block(120, 4)
    destination = _block(100, 5)
    state_hash = b"s" * 32
    source_info = _info(source, key_block=False)
    destination_info = _info(destination, key_block=True)
    reference = SimpleNamespace(
        seqno=destination.seqno,
        root_hash=destination.root_hash,
        file_hash=destination.file_hash,
    )
    previous = {0: {destination.seqno: SimpleNamespace(blk_ref=reference)}}
    state = SimpleNamespace(
        seq_no=source.seqno,
        shard_id=SimpleNamespace(
            workchain_id=-1,
            calculate_shard_signed=lambda: MC_SHARD,
        ),
        custom=SimpleNamespace(prev_blocks=previous),
    )
    wrappers = {
        b"source": _Wrapper(
            _Root(source.root_hash, SimpleNamespace(info=source_info), state_hash=state_hash),
            source.root_hash,
        ),
        b"destination": _Wrapper(
            _Root(destination.root_hash, SimpleNamespace(info=destination_info)),
            destination.root_hash,
        ),
        b"state": _Wrapper(_Root(state_hash, state), state_hash),
    }
    _install_fake_codec(monkeypatch, wrappers)
    monkeypatch.setattr(
        strict,
        "ShardStateUnsplit",
        SimpleNamespace(deserialize=lambda value: value),
    )
    step = {
        "from": source.to_dict(),
        "to": destination.to_dict(),
        "to_key_block": True,
        "proof": b"source",
        "dest_proof": b"destination",
        "state_proof": b"state",
    }
    result = {
        "complete": True,
        "from": source.to_dict(),
        "to": destination.to_dict(),
        "steps": [step],
    }

    complete, last, _, _ = strict.verify_masterchain_proof_response(
        SimpleNamespace(last_key_block=None),
        known_block=source,
        target_block=destination,
        result=result,
    )
    assert complete is True
    assert last == destination

    reference.file_hash = b"f" * 32
    with pytest.raises(strict.TonLiteclientStrictProofFailure):
        strict.verify_masterchain_proof_response(
            SimpleNamespace(last_key_block=None),
            known_block=source,
            target_block=destination,
            result=result,
        )


def test_proof_chain_requires_contiguous_links_and_exact_completion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = _forward_fixture(monkeypatch)
    context["result"]["complete"] = False
    with pytest.raises(strict.TonLiteclientStrictProofFailure):
        _verify_forward(context)

    context = _forward_fixture(monkeypatch)
    context["step"]["from"] = _block(101, 9).to_dict()
    with pytest.raises(strict.TonLiteclientStrictProofFailure):
        _verify_forward(context)


def test_strict_client_uses_application_verifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _block(1, 1)
    destination = _block(2, 2)
    response = {
        "complete": True,
        "from": source.to_dict(),
        "to": destination.to_dict(),
        "steps": [],
    }
    calls: list[dict[str, Any]] = []

    async def request(self, method: str, data: dict[str, Any]):
        calls.append({"method": method, "data": data})
        return response

    monkeypatch.setattr(strict.StrictLiteClient, "liteserver_request", request)
    monkeypatch.setattr(
        strict,
        "verify_masterchain_proof_response",
        lambda client, **kwargs: (True, destination, None, 0),
    )
    client = object.__new__(strict.StrictLiteClient)

    import asyncio

    value = asyncio.run(client.raw_get_mc_block_proof(source, destination))
    assert value == (True, destination, None, 0)
    assert calls == [
        {
            "method": "getBlockProof",
            "data": {
                "known_block": source.to_dict(),
                "mode": 1,
                "target_block": destination.to_dict(),
            },
        }
    ]
