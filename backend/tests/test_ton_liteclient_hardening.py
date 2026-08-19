"""Trust-root, bounded-config and hard subprocess-wall regressions."""

from __future__ import annotations

import base64
import asyncio
import copy
import ipaddress
import multiprocessing
from nacl.signing import SigningKey
import os
from pathlib import Path
import signal
import struct
import tempfile
import platform
from threading import Event, Thread
import time

import pytest
import subprocess
import sys

from services import ton_transaction_inclusion_proof as capture_service
from services import ton_liteclient_jetton_verifier as jetton_service
from services import ton_liteclient_process as process_service
from services import ton_wallet_public_key as public_key_service
from services.ton_liteclient_config import (
    CURRENT_VERIFIER_POLICY_ID,
    LEGACY_CHECKPOINT_POLICY_ID,
    MAX_GLOBAL_CONFIG_BYTES,
    TonLiteclientConfigFailure,
    _config_form,
    load_pinned_liteclient_config,
    network_profile,
    prepare_pinned_liteclient,
    trusted_checkpoint_document,
)
from services.ton_liteclient_strict_proof import StrictLiteClient
from services.ton_transaction_inclusion_proof import (
    TonTransactionInclusionProofFailure,
)


ACCOUNT = "0:" + "11" * 32
TRANSACTION_HASH = "22" * 32
REQUEST = {
    "account_address": ACCOUNT,
    "logical_time": "18446744073709551615",
    "transaction_hash": TRANSACTION_HASH,
}


class _Response:
    def __init__(
        self,
        body: bytes,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        chunks: list[bytes] | None = None,
    ) -> None:
        self.status_code = status
        self.headers = headers or {}
        self._body = body
        self._chunks = chunks
        self.closed = False

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self._chunks if self._chunks is not None else [self._body]

    def close(self) -> None:
        self.closed = True


def _signed_ip(value: str) -> int:
    return struct.unpack(">i", ipaddress.ip_address(value).packed)[0]


def _remote_config(network: str) -> dict:
    profile = network_profile(network)
    return {
        "@type": "config.global",
        "dht": {},
        "liteservers": [{
            "ip": _signed_ip("1.1.1.1"),
            "port": 19949,
            "id": {
                "@type": "pub.ed25519",
                "key": base64.b64encode(b"k" * 32).decode("ascii"),
            },
        }],
        "validator": {
            "@type": "validator.config.global",
            "zero_state": _config_form(profile.zero_state),
            "init_block": {
                "workchain": -1,
                "shard": -9223372036854775808,
                "seqno": 99999999,
                "root_hash": base64.b64encode(b"r" * 32).decode("ascii"),
                "file_hash": base64.b64encode(b"f" * 32).decode("ascii"),
            },
            "hardforks": [],
        },
    }


def _json(value: dict) -> bytes:
    import json

    return json.dumps(value, separators=(",", ":")).encode()


@pytest.mark.parametrize("network", ("ton-mainnet", "ton-testnet"))
def test_official_config_is_network_bound_and_remote_init_is_replaced(network):
    document = _remote_config(network)
    response = _Response(_json(document), headers={"content-type": "text/plain"})
    calls = []

    def get(url, **kwargs):
        calls.append((url, kwargs))
        return response

    prepared = load_pinned_liteclient_config(
        network,
        timeout_seconds=20,
        http_get=get,
    )

    profile = network_profile(network)
    assert prepared["validator"]["init_block"] == _config_form(
        profile.trusted_checkpoint
    )
    assert prepared["validator"]["init_block"] != document["validator"]["init_block"]
    assert calls == [(profile.config_url, {
        "allow_redirects": False,
        "stream": True,
        "timeout": (3.0, 10.0),
        "headers": {"Accept": "application/json"},
    })]
    assert response.closed is True


def test_prepared_balancer_uses_strict_peers_from_exact_application_pin():
    document = _remote_config("ton-mainnet")
    document["liteservers"][0]["id"]["key"] = base64.b64encode(
        SigningKey.generate().verify_key.encode()
    ).decode("ascii")
    prepared = prepare_pinned_liteclient(
        network="ton-mainnet",
        trust_level=0,
        timeout_seconds=5,
        http_get=lambda *_args, **_kwargs: _Response(_json(document)),
    )

    assert prepared.verifier_policy_id == CURRENT_VERIFIER_POLICY_ID
    assert prepared.trusted_checkpoint == trusted_checkpoint_document(
        "ton-mainnet"
    )
    peers = list(prepared.client._peers)
    assert len(peers) == 1
    assert all(isinstance(peer, StrictLiteClient) for peer in peers)
    assert all(
        peer.init_key_block.to_dict()
        == trusted_checkpoint_document("ton-mainnet")
        for peer in peers
    )


@pytest.mark.parametrize(
    ("mutate", "code"),
    (
        (lambda value: value.pop("validator"), "liteserver_config_invalid"),
        (
            lambda value: value["validator"]["zero_state"].update(
                _config_form(network_profile("ton-testnet").zero_state)
            ),
            "liteserver_network_mismatch",
        ),
        (
            lambda value: value["liteservers"].append(
                copy.deepcopy(value["liteservers"][0])
            ),
            "liteserver_config_invalid",
        ),
        (
            lambda value: value["liteservers"][0].update(
                {"ip": _signed_ip("127.0.0.1")}
            ),
            "liteserver_config_invalid",
        ),
    ),
)
def test_official_config_rejects_malformed_wrong_network_and_bad_peers(mutate, code):
    document = _remote_config("ton-mainnet")
    mutate(document)
    with pytest.raises(TonLiteclientConfigFailure) as failure:
        load_pinned_liteclient_config(
            "ton-mainnet",
            timeout_seconds=5,
            http_get=lambda *_args, **_kwargs: _Response(_json(document)),
        )
    assert failure.value.code == code
    assert failure.value.retryable is False


@pytest.mark.parametrize("via_header", (True, False))
def test_official_config_rejects_oversize_without_reading_unbounded(via_header):
    body = b"x" * (MAX_GLOBAL_CONFIG_BYTES + 1)
    response = _Response(
        body,
        headers={"Content-Length": str(len(body))} if via_header else {},
        chunks=[body],
    )
    with pytest.raises(TonLiteclientConfigFailure) as failure:
        load_pinned_liteclient_config(
            "ton-mainnet",
            timeout_seconds=5,
            http_get=lambda *_args, **_kwargs: response,
        )
    assert failure.value.code == "liteserver_config_too_large"
    assert failure.value.retryable is False
    assert response.closed is True


def _payload(cache_directory: str) -> dict:
    return {
        "network": "ton-mainnet",
        "requests": [REQUEST],
        "trust_level": 0,
        "timeout_seconds": 5,
        "cache_directory": cache_directory,
    }


def _proof_result(payload: dict) -> list[dict]:
    return [{
        **payload["requests"][0],
        "block": {
            "workchain": 0,
            "shard": -9223372036854775808,
            "seqno": 123,
            "root_hash": "33" * 32,
            "file_hash": "44" * 32,
        },
        "masterchain_anchor": {
            "workchain": -1,
            "shard": -9223372036854775808,
            "seqno": 124,
            "root_hash": "55" * 32,
            "file_hash": "66" * 32,
        },
        "trusted_checkpoint": trusted_checkpoint_document(payload["network"]),
        "verifier_policy_id": CURRENT_VERIFIER_POLICY_ID,
        "transaction_boc_hex": "00",
        "block_proof_boc_hex": "01",
        "trust_level": payload["trust_level"],
    }]


def _success_child(input_path: str, output_path: str) -> None:
    payload = capture_service._read_json_file(
        input_path,
        maximum=capture_service._MAX_CAPTURE_INPUT_BYTES,
    )
    capture_service._write_json_file(
        output_path,
        {"version": 1, "ok": True, "result": _proof_result(payload)},
        maximum=capture_service._MAX_CAPTURE_RESULT_BYTES,
    )


def _error_child(input_path: str, output_path: str) -> None:
    del input_path
    capture_service._write_json_file(
        output_path,
        {
            "version": 1,
            "ok": False,
            "code": "liteserver_network_mismatch",
            "retryable": False,
        },
        maximum=capture_service._MAX_CAPTURE_RESULT_BYTES,
    )


def _strict_proof_error_child(input_path: str, output_path: str) -> None:
    del input_path
    capture_service._write_json_file(
        output_path,
        {
            "version": 1,
            "ok": False,
            "code": "liteserver_proof_invalid",
            "retryable": False,
        },
        maximum=capture_service._MAX_CAPTURE_RESULT_BYTES,
    )


def _crash_child(input_path: str, output_path: str) -> None:
    del input_path, output_path
    os._exit(3)


def _hang_child(input_path: str, output_path: str) -> None:
    del input_path, output_path
    while True:
        time.sleep(1)


def _ignore_term_child(input_path: str, output_path: str) -> None:
    del input_path, output_path
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pid_path = os.environ.get("GRAM_SCOPE_TEST_CHILD_PID_PATH")
    if pid_path:
        Path(pid_path).write_text(str(os.getpid()), encoding="ascii")
    while True:
        time.sleep(1)


def _public_key_success_child(input_path: str, output_path: str) -> None:
    del input_path
    process_service.write_json_file(
        output_path,
        process_service.success_envelope("ab" * 32),
        maximum=public_key_service._MAX_OUTPUT_BYTES,
    )


def _jetton_result(payload: dict) -> dict:
    proof = {
        "account_address": payload["jetton_wallet_account_canonical"],
        "shard_block": {
            "workchain": 0,
            "shard": -9223372036854775808,
            "seqno": 1,
            "root_hash": "11" * 32,
            "file_hash": "22" * 32,
        },
        "state_boc_hex": "00",
        "account_proof_boc_hex": "01",
        "shard_proof_boc_hex": "02",
    }
    return {
        "verifier_name": "pytoniq-pytvm",
        "verifier_version": "pytoniq-test/pytvm-test",
        "trust_level": payload["trust_level"],
        "anchor": {
            "workchain": -1,
            "shard": "-9223372036854775808",
            "seqno": 2,
            "root_hash": "33" * 32,
            "file_hash": "44" * 32,
        },
        "wallet_balance_base_units": "1",
        "total_supply_base_units": "2",
        "mintable": False,
        "wallet_code_boc_hex": "00",
        "wallet_data_boc_hex": "01",
        "master_code_boc_hex": "02",
        "master_data_boc_hex": "03",
        "wallet_code_hash": "55" * 32,
        "wallet_data_hash": "66" * 32,
        "master_code_hash": "77" * 32,
        "master_data_hash": "88" * 32,
        "jetton_content_hash": "99" * 32,
        "account_state_proof_verified": True,
        "masterchain_checkpoint_chain_verified": False,
        "local_tvm_execution_applied": True,
        "account_inclusion_proofs": {
            "jetton_wallet": proof,
            "jetton_master": {
                **proof,
                "account_address": payload["jetton_master_account_canonical"],
            },
        },
    }


def _jetton_success_child(input_path: str, output_path: str) -> None:
    payload = process_service.read_json_file(
        input_path, maximum=jetton_service._MAX_INPUT_BYTES
    )
    process_service.write_json_file(
        output_path,
        process_service.success_envelope(_jetton_result(payload)),
        maximum=jetton_service._MAX_OUTPUT_BYTES,
    )


def _guard_small_child(input_path: str, output_path: str) -> None:
    del input_path
    try:
        process_service.apply_liteclient_child_guards()
        probe = bytearray(8 * 1024 * 1024)
        envelope = process_service.success_envelope(len(probe))
    except BaseException as exc:
        envelope = process_service.child_error_envelope(
            exc, safe_error_codes=frozenset({"liteclient_resource_limit"})
        )
    process_service.write_json_file(output_path, envelope, maximum=4096)


def _guard_memory_child(input_path: str, output_path: str) -> None:
    del input_path
    try:
        process_service.apply_liteclient_child_guards()
        bytearray(process_service.CHILD_MEMORY_HEADROOM_BYTES + 64 * 1024 * 1024)
        envelope = process_service.success_envelope("unexpected")
    except BaseException as exc:
        envelope = process_service.child_error_envelope(
            exc, safe_error_codes=frozenset({"liteclient_resource_limit"})
        )
    process_service.write_json_file(output_path, envelope, maximum=4096)


def _guard_inherited_soft_limit_child(input_path: str, output_path: str) -> None:
    del input_path
    try:
        import resource

        current_virtual = process_service._current_virtual_size()
        as_soft = current_virtual + 256 * 1024 * 1024
        _old_as_soft, as_hard = resource.getrlimit(resource.RLIMIT_AS)
        if as_hard != resource.RLIM_INFINITY:
            as_soft = min(as_soft, int(as_hard))
        resource.setrlimit(resource.RLIMIT_AS, (as_soft, as_hard))
        _old_cpu_soft, cpu_hard = resource.getrlimit(resource.RLIMIT_CPU)
        cpu_soft = 30
        if cpu_hard != resource.RLIM_INFINITY:
            cpu_soft = min(cpu_soft, int(cpu_hard))
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_hard))
        before_as = resource.getrlimit(resource.RLIMIT_AS)
        before_cpu = resource.getrlimit(resource.RLIMIT_CPU)
        process_service.apply_liteclient_child_guards()
        after_as = resource.getrlimit(resource.RLIMIT_AS)
        after_cpu = resource.getrlimit(resource.RLIMIT_CPU)
        envelope = process_service.success_envelope({
            "before_as": list(before_as),
            "after_as": list(after_as),
            "before_cpu": list(before_cpu),
            "after_cpu": list(after_cpu),
        })
    except BaseException as exc:
        envelope = process_service.child_error_envelope(
            exc, safe_error_codes=frozenset({"liteclient_resource_limit"})
        )
    process_service.write_json_file(output_path, envelope, maximum=4096)


def _cpu_limit_child(input_path: str, output_path: str) -> None:
    del input_path, output_path
    import resource

    resource.setrlimit(resource.RLIMIT_CPU, (1, 1))
    while True:
        pass


def _ipc_files() -> set[Path]:
    return set(Path(tempfile.gettempdir()).glob("ton-inclusion-*.json"))


def test_spawn_capture_success_and_sanitized_error_propagation(tmp_path):
    payload = _payload(str(tmp_path / "cache"))
    result = capture_service._run_capture_subprocess(
        payload,
        deadline_seconds=3,
        process_target=_success_child,
    )
    assert result == _proof_result(payload)

    with pytest.raises(TonTransactionInclusionProofFailure) as failure:
        capture_service._run_capture_subprocess(
            payload,
            deadline_seconds=3,
            process_target=_error_child,
        )
    assert failure.value.code == "liteserver_network_mismatch"
    assert failure.value.retryable is False
    assert "http" not in str(failure.value).lower()

    with pytest.raises(TonTransactionInclusionProofFailure) as strict_failure:
        capture_service._run_capture_subprocess(
            payload,
            deadline_seconds=3,
            process_target=_strict_proof_error_child,
        )
    assert strict_failure.value.code == "liteserver_proof_invalid"
    assert strict_failure.value.retryable is False


@pytest.mark.parametrize("target", (_hang_child, _ignore_term_child))
def test_spawn_capture_hard_wall_terminates_or_kills_without_leak(tmp_path, target):
    before_files = _ipc_files()
    before_children = {child.pid for child in multiprocessing.active_children()}
    started = time.monotonic()
    with pytest.raises(TonTransactionInclusionProofFailure) as failure:
        capture_service._run_capture_subprocess(
            _payload(str(tmp_path / "cache")),
            deadline_seconds=0.25,
            process_target=target,
        )
    elapsed = time.monotonic() - started
    assert failure.value.code == "liteserver_capture_timeout"
    assert failure.value.retryable is True
    assert elapsed < 2.0
    assert _ipc_files() == before_files
    assert {
        child.pid for child in multiprocessing.active_children()
    } == before_children


def test_spawn_capture_crash_is_retryable_and_cleans_ipc(tmp_path):
    before = _ipc_files()
    with pytest.raises(TonTransactionInclusionProofFailure) as failure:
        capture_service._run_capture_subprocess(
            _payload(str(tmp_path / "cache")),
            deadline_seconds=3,
            process_target=_crash_child,
        )
    assert failure.value.code == "liteserver_capture_failed"
    assert failure.value.retryable is True
    assert _ipc_files() == before


def test_spawn_capture_cancellation_stops_child_and_cleans_ipc(tmp_path):
    cancellation = Event()
    trigger = Thread(
        target=lambda: (time.sleep(0.15), cancellation.set()),
        daemon=True,
    )
    trigger.start()
    before = _ipc_files()
    started = time.monotonic()
    with pytest.raises(TonTransactionInclusionProofFailure) as failure:
        capture_service._run_capture_subprocess(
            _payload(str(tmp_path / "cache")),
            deadline_seconds=5,
            cancellation_event=cancellation,
            process_target=_hang_child,
        )
    trigger.join(1)
    assert failure.value.code == "liteserver_capture_cancelled"
    assert time.monotonic() - started < 1.5
    assert _ipc_files() == before


def test_capture_deadline_is_absolute_and_request_count_independent(tmp_path):
    assert capture_service._capture_deadline_seconds(5) == 40
    assert capture_service._capture_deadline_seconds(60) == 180
    one = _payload(str(tmp_path / "cache"))
    many = copy.deepcopy(one)
    many["requests"] = [
        {**REQUEST, "transaction_hash": f"{index:064x}"}
        for index in range(1, 257)
    ]
    assert capture_service._validated_capture_payload(one)["timeout_seconds"] == 5
    assert len(capture_service._validated_capture_payload(many)["requests"]) == 256
    assert capture_service._capture_deadline_seconds(5) == 40


def test_capture_result_budget_is_enforced_before_multi_item_accumulation(
    tmp_path,
    monkeypatch,
):
    payload = _payload(str(tmp_path / "cache"))
    candidate = _proof_result(payload)[0]
    one_size = len(capture_service._canonical_json(candidate)) + 2
    monkeypatch.setattr(capture_service, "_MAX_CAPTURE_RESULT_BYTES", one_size + 1)
    result = []
    used = capture_service._append_bounded_capture_result(
        result,
        candidate,
        result_bytes=2,
    )
    assert result == [candidate]
    with pytest.raises(TonTransactionInclusionProofFailure) as failure:
        capture_service._append_bounded_capture_result(
            result,
            candidate,
            result_bytes=used,
        )
    assert failure.value.code == "liteserver_result_too_large"
    assert failure.value.retryable is False
    assert result == [candidate]


def test_parent_ipc_rejects_non_pinned_checkpoint(tmp_path):
    payload = _payload(str(tmp_path / "cache"))
    result = _proof_result(payload)
    result[0]["trusted_checkpoint"]["root_hash"] = "ff" * 32
    with pytest.raises(TonTransactionInclusionProofFailure) as failure:
        capture_service._validated_capture_result(
            result,
            requests=payload["requests"],
            trust_level=payload["trust_level"],
            network=payload["network"],
        )
    assert failure.value.code == "liteserver_ipc_invalid"
    assert failure.value.retryable is False


def test_ipc_writer_handles_partial_os_writes_without_duplication(monkeypatch):
    path = capture_service._new_ipc_path("partial-write")
    original = os.write

    def partial(fd, value):
        return original(fd, bytes(value[:3]))

    monkeypatch.setattr(os, "write", partial)
    try:
        value = {"nested": [1, 2, 3], "message": "bounded"}
        capture_service._write_json_file(path, value, maximum=1024)
        assert capture_service._read_json_file(path, maximum=1024) == value
    finally:
        capture_service._unlink_ipc(path)


@pytest.mark.parametrize("supervisor", ("inclusion", "generic"))
def test_parent_interpreter_hard_kills_sigterm_ignoring_child_on_exit(
    tmp_path,
    supervisor,
):
    pid_path = tmp_path / f"{supervisor}.pid"
    common = [
        "import pathlib, threading, time",
        "from backend.tests.liteclient_process_targets import ignore_sigterm",
        f"pid_path = pathlib.Path({str(pid_path)!r})",
    ]
    if supervisor == "inclusion":
        launch = [
            "from services.ton_transaction_inclusion_proof import _run_capture_subprocess",
            f"payload = {_payload(str(tmp_path / 'cache'))!r}",
            "threading.Thread(target=lambda: _run_capture_subprocess(payload, deadline_seconds=30, process_target=ignore_sigterm), daemon=True).start()",
        ]
        ipc_pattern = "ton-inclusion-*.json"
    else:
        launch = [
            "from services.ton_liteclient_process import run_liteclient_subprocess",
            "threading.Thread(target=lambda: run_liteclient_subprocess({}, deadline_seconds=30, input_maximum=1024, output_maximum=1024, process_name='ton-exit-test', path_prefix='ton-exit-test', process_target=ignore_sigterm, safe_error_codes=frozenset({'liteserver_capture_failed'})), daemon=True).start()",
        ]
        ipc_pattern = "ton-exit-test-*.json"
    script = "\n".join((*common, *launch, (
        "deadline = time.monotonic() + 1.5\n"
        "while not pid_path.exists() and time.monotonic() < deadline:\n"
        "    time.sleep(0.01)\n"
        "assert pid_path.exists()"
    )))
    before_ipc = set(Path(tempfile.gettempdir()).glob(ipc_pattern))
    started = time.monotonic()
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "GRAM_SCOPE_TEST_CHILD_PID_PATH": str(pid_path),
            "PYTHONPATH": os.pathsep.join((
                str(Path(__file__).resolve().parents[2]),
                str(Path(__file__).resolve().parents[1]),
            )),
        },
        capture_output=True,
        text=True,
        timeout=4,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert time.monotonic() - started < 3.0
    child_pid = int(pid_path.read_text(encoding="ascii"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)
    assert set(Path(tempfile.gettempdir()).glob(ipc_pattern)) == before_ipc


def test_public_key_and_jetton_live_wrappers_use_spawned_hard_wall(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(public_key_service, "_deadline_seconds", lambda _value: 0.25)
    started = time.monotonic()
    with pytest.raises(public_key_service.TonWalletPublicKeyFailure) as key_failure:
        public_key_service.resolve_wallet_public_key_live(
            network="ton-mainnet",
            address=ACCOUNT,
            trust_level=0,
            timeout_seconds=5,
            cache_directory=str(tmp_path / "key-cache"),
            process_target=_hang_child,
        )
    assert key_failure.value.code == "liteserver_capture_timeout"
    assert time.monotonic() - started < 2.0

    monkeypatch.setattr(jetton_service, "_deadline_seconds", lambda _value: 0.25)
    started = time.monotonic()
    with pytest.raises(
        jetton_service.TonLiteclientJettonVerificationFailure
    ) as jetton_failure:
        jetton_service.verify_jetton_contract_relationship_live(
            network="ton-mainnet",
            owner_account_canonical=ACCOUNT,
            jetton_wallet_account_canonical="0:" + "22" * 32,
            jetton_master_account_canonical="0:" + "33" * 32,
            trust_level=0,
            timeout_seconds=5,
            cache_directory=str(tmp_path / "jetton-cache"),
            process_target=_hang_child,
        )
    assert jetton_failure.value.code == "liteserver_capture_timeout"
    assert time.monotonic() - started < 2.0


def test_public_key_and_jetton_spawn_success_contracts(tmp_path):
    assert public_key_service.resolve_wallet_public_key_live(
        network="ton-mainnet",
        address=ACCOUNT,
        trust_level=0,
        timeout_seconds=5,
        cache_directory=str(tmp_path / "key-cache"),
        process_target=_public_key_success_child,
    ) == bytes.fromhex("ab" * 32)

    payload = {
        "network": "ton-mainnet",
        "owner_account_canonical": ACCOUNT,
        "jetton_wallet_account_canonical": "0:" + "22" * 32,
        "jetton_master_account_canonical": "0:" + "33" * 32,
        "trust_level": 0,
        "timeout_seconds": 5,
        "cache_directory": str(tmp_path / "jetton-cache"),
    }
    assert jetton_service.verify_jetton_contract_relationship_live(
        **payload,
        process_target=_jetton_success_child,
    ) == _jetton_result(payload)


def test_shared_cache_removes_truncated_and_oversize_entries_before_start(tmp_path):
    network_directory = tmp_path / "cache" / "ton-mainnet"
    blockstore = network_directory / ".blockstore"
    blockstore.mkdir(parents=True)
    pin = trusted_checkpoint_document("ton-mainnet")["root_hash"]
    truncated = blockstore / ("00" * 88 + pin + ".blks")
    oversized = blockstore / ("11" * 88 + pin + ".blks")
    truncated.write_bytes(b"x")
    oversized.write_bytes(b"x" * (1024 * 1024))

    original = Path.cwd()
    with process_service.liteclient_cache_lock(
        str(tmp_path / "cache"), "ton-mainnet"
    ):
        assert Path.cwd() == (
            network_directory / CURRENT_VERIFIER_POLICY_ID
        )
        assert not truncated.exists()
        assert not oversized.exists()
    assert Path.cwd() == original


def test_shared_cache_rejects_parseable_blocks_older_than_application_pin(tmp_path):
    from pytoniq.liteclient.sync import blocks_to_bytes
    from pytoniq_core.tl.block import BlockIdExt

    checkpoint = trusted_checkpoint_document("ton-mainnet")
    old = BlockIdExt.from_dict({**checkpoint, "seqno": checkpoint["seqno"] - 1})
    now = int(time.time())
    data = blocks_to_bytes(now + 3600, now, old, old)
    network_directory = tmp_path / "cache" / "ton-mainnet"
    with process_service.liteclient_cache_lock(
        str(tmp_path / "cache"), "ton-mainnet"
    ):
        pass
    blockstore = (
        network_directory / CURRENT_VERIFIER_POLICY_ID / ".blockstore"
    )
    blockstore.mkdir(parents=True)
    poisoned = blockstore / (
        f"{data[:88].hex()}{checkpoint['root_hash']}.blks"
    )
    poisoned.write_bytes(data)

    with process_service.liteclient_cache_lock(
        str(tmp_path / "cache"), "ton-mainnet"
    ):
        assert not poisoned.exists()


def test_shared_cache_invalidates_pre_strict_policy_before_start(tmp_path):
    from pytoniq.liteclient.sync import blocks_to_bytes
    from pytoniq_core.tl.block import BlockIdExt

    checkpoint = trusted_checkpoint_document("ton-mainnet")
    pinned = BlockIdExt.from_dict(checkpoint)
    now = int(time.time())
    data = blocks_to_bytes(now + 3600, now, pinned, pinned)
    network_directory = tmp_path / "cache" / "ton-mainnet"
    blockstore = network_directory / ".blockstore"
    blockstore.mkdir(parents=True)
    legacy_cached = blockstore / (
        f"{data[:88].hex()}{checkpoint['root_hash']}.blks"
    )
    legacy_cached.write_bytes(data)
    strict_blockstore = (
        network_directory / CURRENT_VERIFIER_POLICY_ID / ".blockstore"
    )
    strict_blockstore.mkdir(parents=True, exist_ok=True)
    stale_strict_cached = strict_blockstore / (
        f"{data[:88].hex()}{checkpoint['root_hash']}.blks"
    )
    stale_strict_cached.write_bytes(data)
    sentinel = network_directory / ".proof-policy"
    sentinel.write_text(f"{LEGACY_CHECKPOINT_POLICY_ID}\n", encoding="ascii")

    with process_service.liteclient_cache_lock(
        str(tmp_path / "cache"), "ton-mainnet"
    ):
        assert not legacy_cached.exists()
        assert not stale_strict_cached.exists()
        assert sentinel.read_text(encoding="ascii") == (
            f"{CURRENT_VERIFIER_POLICY_ID}\n"
        )
        assert sentinel.stat().st_mode & 0o777 == 0o600

    strict_cached = strict_blockstore / (
        f"{data[:88].hex()}{checkpoint['root_hash']}.blks"
    )
    strict_cached.write_bytes(data)
    with process_service.liteclient_cache_lock(
        str(tmp_path / "cache"), "ton-mainnet"
    ):
        assert strict_cached.exists()


def test_shared_cache_policy_transition_is_durably_ordered(tmp_path, monkeypatch):
    network_directory = tmp_path / "cache" / "ton-mainnet"
    blockstore = network_directory / ".blockstore"
    blockstore.mkdir(parents=True)
    (blockstore / "pre-strict.blks").write_bytes(b"old")
    (network_directory / ".proof-policy").write_text(
        f"{LEGACY_CHECKPOINT_POLICY_ID}\n",
        encoding="ascii",
    )
    events = []
    real_fsync_directory = process_service._fsync_directory
    real_replace = process_service.os.replace

    def fsync_directory(path):
        events.append(("fsync_dir", Path(path)))
        return real_fsync_directory(path)

    def replace(source, destination):
        events.append(("replace", Path(destination)))
        return real_replace(source, destination)

    monkeypatch.setattr(process_service, "_fsync_directory", fsync_directory)
    monkeypatch.setattr(process_service.os, "replace", replace)
    with process_service.liteclient_cache_lock(
        str(tmp_path / "cache"), "ton-mainnet"
    ):
        pass

    policy_directory = network_directory / CURRENT_VERIFIER_POLICY_ID
    assert events == [
        ("fsync_dir", blockstore),
        ("replace", network_directory / ".proof-policy"),
        ("fsync_dir", network_directory),
        ("replace", policy_directory / ".proof-policy"),
        ("fsync_dir", policy_directory),
    ]


def test_repeated_shared_cache_locks_do_not_leak_file_descriptors(tmp_path):
    fd_directory = Path("/dev/fd") if Path("/dev/fd").exists() else Path("/proc/self/fd")
    before = len(list(fd_directory.iterdir()))
    for _ in range(40):
        with process_service.liteclient_cache_lock(
            str(tmp_path / "cache"), "ton-mainnet"
        ):
            pass
    after = len(list(fd_directory.iterdir()))
    assert after <= before + 1


def test_shared_ipc_reader_accepts_exact_serialized_boundary(tmp_path):
    path = process_service.new_ipc_path("ton-boundary", "result")
    value = {"blob": "x" * 1024}
    maximum = len(process_service.canonical_json(value))
    try:
        process_service.write_json_file(path, value, maximum=maximum)
        assert process_service.read_json_file(path, maximum=maximum) == value
    finally:
        process_service.unlink_ipc(path)


def test_child_resource_guard_allows_bounded_work_and_rejects_memory_growth():
    safe = frozenset({"liteclient_resource_limit"})
    assert process_service.run_liteclient_subprocess(
        {"operation": "small"},
        deadline_seconds=5,
        input_maximum=4096,
        output_maximum=4096,
        process_name="ton-limit-small",
        path_prefix="ton-limit",
        process_target=_guard_small_child,
        safe_error_codes=safe,
    ) == 8 * 1024 * 1024

    with pytest.raises(process_service.TonLiteclientProcessFailure) as failure:
        process_service.run_liteclient_subprocess(
            {"operation": "memory"},
            deadline_seconds=5,
            input_maximum=4096,
            output_maximum=4096,
            process_name="ton-limit-memory",
            path_prefix="ton-limit",
            process_target=_guard_memory_child,
            safe_error_codes=safe,
        )
    assert failure.value.code == "liteclient_resource_limit"
    assert failure.value.retryable is False


def test_child_resource_guard_never_raises_inherited_soft_ulimits():
    result = process_service.run_liteclient_subprocess(
        {"operation": "inherited-soft-limits"},
        deadline_seconds=5,
        input_maximum=4096,
        output_maximum=4096,
        process_name="ton-limit-inherited",
        path_prefix="ton-limit",
        process_target=_guard_inherited_soft_limit_child,
        safe_error_codes=frozenset({"liteclient_resource_limit"}),
    )
    assert result["after_as"][0] <= result["before_as"][0]
    assert result["after_cpu"][0] <= result["before_cpu"][0]
    assert result["after_as"][0] == result["after_as"][1]
    assert result["after_cpu"][0] <= result["after_cpu"][1]


def test_child_cpu_signal_is_permanent_and_parent_survives():
    started = time.monotonic()
    with pytest.raises(process_service.TonLiteclientProcessFailure) as failure:
        process_service.run_liteclient_subprocess(
            {"operation": "cpu"},
            deadline_seconds=5,
            input_maximum=4096,
            output_maximum=4096,
            process_name="ton-limit-cpu",
            path_prefix="ton-limit",
            process_target=_cpu_limit_child,
            safe_error_codes=frozenset({"liteclient_resource_limit"}),
        )
    assert failure.value.code == "liteclient_resource_limit"
    assert failure.value.retryable is False
    assert time.monotonic() - started < 4


def test_shared_child_capacity_is_bounded_and_cancellation_aware():
    acquired = 0
    try:
        for _ in range(process_service.LITECLIENT_CHILD_SLOTS):
            process_service.acquire_liteclient_child_slot(wait_seconds=0.1)
            acquired += 1
        with pytest.raises(process_service.TonLiteclientProcessFailure) as saturated:
            process_service.acquire_liteclient_child_slot(wait_seconds=0.05)
        assert saturated.value.code == "liteclient_capacity_unavailable"
        assert saturated.value.retryable is True

        cancelled = Event()
        cancelled.set()
        with pytest.raises(process_service.TonLiteclientProcessFailure) as stopped:
            process_service.acquire_liteclient_child_slot(
                cancellation_event=cancelled,
                wait_seconds=0.05,
            )
        assert stopped.value.code == "liteserver_capture_cancelled"
    finally:
        for _ in range(acquired):
            process_service.release_liteclient_child_slot()


def test_pinned_pytoniq_frame_guard_rejects_before_stream_allocation():
    process_service._install_frame_guard()
    from pytoniq.liteclient.client import LiteClient

    class Reader:
        called = False

        async def readexactly(self, _length):
            self.called = True
            return b""

    fake = object.__new__(LiteClient)
    fake.reader = Reader()
    fake.tasks = {}
    with pytest.raises(process_service.TonLiteclientFrameLimitFailure):
        asyncio.run(
            LiteClient.receive(
                fake,
                process_service.MAX_LITECLIENT_FRAME_BYTES + 1,
            )
        )
    assert fake.reader.called is False
    assert fake._gram_scope_frame_limit_rejected is True


@pytest.mark.skipif(platform.system() != "Darwin", reason="Darwin Mach contract")
def test_darwin_virtual_size_uses_matching_mach_task_info_layout():
    measured = process_service._current_virtual_size()
    ps_kib = int(
        subprocess.check_output(
            ["ps", "-o", "vsz=", "-p", str(os.getpid())],
            text=True,
        ).strip()
    )
    ps_bytes = ps_kib * 1024
    assert measured > 0
    assert 0.8 <= measured / ps_bytes <= 1.25
