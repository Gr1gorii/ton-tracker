"""Bounded spawned-process supervisor for TON liteserver operations."""

from __future__ import annotations

import atexit
from contextlib import contextmanager
import ctypes
import fcntl
import hashlib
from importlib.metadata import version
import inspect
import json
import multiprocessing
from multiprocessing import util as _multiprocessing_util  # noqa: F401
import os
import platform
from pathlib import Path
import re
import stat
import tempfile
from threading import BoundedSemaphore, Event, Lock, current_thread
import time
from typing import Any, Callable


PROCESS_POLL_SECONDS = 0.05
PROCESS_TERMINATE_GRACE_SECONDS = 0.5
PROCESS_KILL_GRACE_SECONDS = 0.5
MAX_PROCESS_DEADLINE_SECONDS = 180.0
MAX_LITECLIENT_FRAME_BYTES = 64 * 1024 * 1024
CHILD_MEMORY_HEADROOM_BYTES = 512 * 1024 * 1024
CHILD_CPU_SECONDS = 120
LITECLIENT_CHILD_SLOTS = 2
LITECLIENT_SLOT_WAIT_SECONDS = 2.0
_CACHE_POLICY_SENTINEL = ".proof-policy"
_PYTONIQ_VERSION = "0.1.43"
_PYTONIQ_RECEIVE_SHA256 = (
    "9c12dd8e8edde720ec296cd47f9cf9ccb49071b8f8a28df7abf2774f5f35adc6"
)
_CHILD_SLOTS = BoundedSemaphore(LITECLIENT_CHILD_SLOTS)
_CHILD_REGISTRY_LOCK = Lock()
_ACTIVE_CHILDREN: dict[int, tuple[Any, tuple[str, ...], Any]] = {}
_SHUTTING_DOWN = False


class TonLiteclientProcessFailure(RuntimeError):
    """A child failed without exposing its payload, path, or provider response."""

    def __init__(self, message: str, *, code: str, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable


class TonLiteclientFrameLimitFailure(RuntimeError):
    """An authenticated peer advertised an unsafe ADNL frame length."""


def run_liteclient_subprocess(
    payload: dict[str, Any],
    *,
    deadline_seconds: float,
    input_maximum: int,
    output_maximum: int,
    process_name: str,
    path_prefix: str,
    process_target: Callable[[str, str], None],
    safe_error_codes: frozenset[str],
    cancellation_event: Event | None = None,
) -> Any:
    """Execute one file-IPC child under an absolute parent-owned deadline."""
    if (
        not isinstance(payload, dict)
        or type(input_maximum) is not int
        or not 1 <= input_maximum <= 64 * 1024 * 1024
        or type(output_maximum) is not int
        or not 1 <= output_maximum <= 64 * 1024 * 1024
        or not isinstance(process_name, str)
        or not process_name
        or len(process_name) > 64
        or not isinstance(path_prefix, str)
        or not path_prefix
        or len(path_prefix) > 48
        or not 0 < float(deadline_seconds) <= MAX_PROCESS_DEADLINE_SECONDS
    ):
        raise TonLiteclientProcessFailure(
            "TON liteserver subprocess contract is invalid.",
            code="liteserver_ipc_invalid",
            retryable=False,
        )
    slot_acquired = False
    input_path = ""
    output_path = ""
    process = None
    try:
        acquire_liteclient_child_slot(cancellation_event=cancellation_event)
        slot_acquired = True
        input_path = new_ipc_path(path_prefix, "input")
        output_path = new_ipc_path(path_prefix, "output")
        write_json_file(input_path, payload, maximum=input_maximum)
        if cancellation_event is not None and cancellation_event.is_set():
            raise TonLiteclientProcessFailure(
                "TON liteserver operation was cancelled.",
                code="liteserver_capture_cancelled",
                retryable=True,
            )
        process = multiprocessing.get_context("spawn").Process(
            target=process_target,
            args=(input_path, output_path),
            name=process_name,
            # The supervisor and the process-wide atexit registry both apply
            # bounded terminate/kill joins. Daemon mode is only a secondary
            # declaration of ownership; it is not the shutdown boundary.
            daemon=True,
        )
        start_registered_process(
            process,
            cleanup_paths=(input_path, output_path),
        )
        deadline = time.monotonic() + float(deadline_seconds)
        while process.is_alive():
            if cancellation_event is not None and cancellation_event.is_set():
                if not stop_process(process):
                    raise TonLiteclientProcessFailure(
                        "TON liteserver child could not be stopped.",
                        code="liteserver_capture_failed",
                        retryable=True,
                    )
                raise TonLiteclientProcessFailure(
                    "TON liteserver operation was cancelled.",
                    code="liteserver_capture_cancelled",
                    retryable=True,
                )
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                if not stop_process(process):
                    raise TonLiteclientProcessFailure(
                        "TON liteserver child could not be stopped.",
                        code="liteserver_capture_failed",
                        retryable=True,
                    )
                raise TonLiteclientProcessFailure(
                    "TON liteserver operation reached its hard deadline.",
                    code="liteserver_capture_timeout",
                    retryable=True,
                )
            process.join(min(PROCESS_POLL_SECONDS, remaining))
        if liteclient_process_shutting_down():
            return None
        process.join(0)
        if process.exitcode != 0:
            if process.exitcode in {-9, -24, -25}:
                raise TonLiteclientProcessFailure(
                    "TON liteserver child reached its resource boundary.",
                    code="liteclient_resource_limit",
                    retryable=False,
                )
            raise TonLiteclientProcessFailure(
                "TON liteserver child stopped unexpectedly.",
                code="liteserver_capture_failed",
                retryable=True,
            )
        return validated_child_envelope(
            read_json_file(output_path, maximum=output_maximum),
            safe_error_codes=safe_error_codes,
        )
    finally:
        if process is not None and process.is_alive():
            try:
                stop_process(process)
            except BaseException:
                pass
        process_stopped = process is not None and not process.is_alive()
        if process_stopped:
            unregister_process(process)
            try:
                process.close()
            except BaseException:
                pass
        if input_path:
            unlink_ipc(input_path)
        if output_path:
            unlink_ipc(output_path)
        if slot_acquired:
            release_liteclient_child_slot()


def validated_child_envelope(
    value: Any,
    *,
    safe_error_codes: frozenset[str],
) -> Any:
    if not isinstance(value, dict) or value.get("version") != 1:
        invalid_ipc()
    if value.get("ok") is True and set(value) == {"version", "ok", "result"}:
        return value["result"]
    if value.get("ok") is False and set(value) == {
        "version", "ok", "code", "retryable"
    }:
        code = value.get("code")
        retryable = value.get("retryable")
        if not isinstance(code, str) or code not in safe_error_codes:
            code = "liteserver_capture_failed"
            retryable = True
        if type(retryable) is not bool:
            invalid_ipc()
        raise TonLiteclientProcessFailure(
            "TON liteserver child operation failed.",
            code=code,
            retryable=retryable,
        )
    invalid_ipc()


def child_error_envelope(
    exc: BaseException,
    *,
    safe_error_codes: frozenset[str],
) -> dict[str, Any]:
    if isinstance(exc, (MemoryError, TonLiteclientFrameLimitFailure)):
        code = "liteclient_resource_limit"
        retryable = False
    else:
        code = getattr(exc, "code", None)
        retryable = getattr(exc, "retryable", None)
    if not isinstance(code, str) or code not in safe_error_codes:
        code = "liteserver_capture_failed"
        retryable = True
    if type(retryable) is not bool:
        retryable = True
    return {
        "version": 1,
        "ok": False,
        "code": code,
        "retryable": retryable,
    }


def success_envelope(result: Any) -> dict[str, Any]:
    return {"version": 1, "ok": True, "result": result}


def acquire_liteclient_child_slot(
    *,
    cancellation_event: Event | None = None,
    wait_seconds: float = LITECLIENT_SLOT_WAIT_SECONDS,
) -> None:
    deadline = time.monotonic() + max(0.01, min(float(wait_seconds), 5.0))
    while True:
        if cancellation_event is not None and cancellation_event.is_set():
            raise TonLiteclientProcessFailure(
                "TON liteserver operation was cancelled before execution.",
                code="liteserver_capture_cancelled",
                retryable=True,
            )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TonLiteclientProcessFailure(
                "TON liteserver child capacity is temporarily unavailable.",
                code="liteclient_capacity_unavailable",
                retryable=True,
            )
        if _CHILD_SLOTS.acquire(timeout=min(PROCESS_POLL_SECONDS, remaining)):
            return


def release_liteclient_child_slot() -> None:
    _CHILD_SLOTS.release()


def apply_liteclient_child_guards() -> None:
    """Install hard process and ADNL frame bounds before any network I/O."""
    _apply_resource_limits()
    _install_frame_guard()


def liteclient_frame_limit_rejected(client: Any) -> bool:
    try:
        return any(
            bool(getattr(peer, "_gram_scope_frame_limit_rejected", False))
            for peer in client._peers
        )
    except Exception:
        return False


def _apply_resource_limits() -> None:
    try:
        import resource

        current_virtual = _current_virtual_size()
        if not 1 <= current_virtual < 2**63 - CHILD_MEMORY_HEADROOM_BYTES:
            raise ValueError("invalid current virtual size")
        memory_limit = current_virtual + CHILD_MEMORY_HEADROOM_BYTES
        inherited_soft, inherited_hard = resource.getrlimit(resource.RLIMIT_AS)
        if inherited_soft != resource.RLIM_INFINITY:
            memory_limit = min(memory_limit, int(inherited_soft))
        if inherited_hard != resource.RLIM_INFINITY:
            memory_limit = min(memory_limit, int(inherited_hard))
        if memory_limit <= current_virtual + 64 * 1024 * 1024:
            raise ValueError("insufficient address-space headroom")
        resource.setrlimit(resource.RLIMIT_AS, (memory_limit, memory_limit))

        inherited_cpu_soft, inherited_cpu_hard = resource.getrlimit(
            resource.RLIMIT_CPU
        )
        cpu_soft = CHILD_CPU_SECONDS
        cpu_hard_target = CHILD_CPU_SECONDS + 1
        if inherited_cpu_soft != resource.RLIM_INFINITY:
            cpu_soft = min(cpu_soft, int(inherited_cpu_soft))
        if inherited_cpu_hard != resource.RLIM_INFINITY:
            cpu_hard_target = min(cpu_hard_target, int(inherited_cpu_hard))
            cpu_soft = min(cpu_soft, cpu_hard_target)
        if cpu_soft < 10:
            raise ValueError("insufficient CPU limit")
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_soft, cpu_hard_target))
    except TonLiteclientProcessFailure:
        raise
    except Exception as exc:
        raise TonLiteclientProcessFailure(
            "TON liteserver child resource limits could not be installed.",
            code="liteclient_resource_limit",
            retryable=False,
        ) from exc


def _current_virtual_size() -> int:
    system = platform.system()
    if system == "Linux":
        with open("/proc/self/statm", "r", encoding="ascii") as source:
            pages = int(source.read(128).split()[0])
        return pages * int(os.sysconf("SC_PAGE_SIZE"))
    if system == "Darwin":
        class _TimeValue(ctypes.Structure):
            _fields_ = [("seconds", ctypes.c_int32), ("microseconds", ctypes.c_int32)]

        class _TaskBasicInfo64(ctypes.Structure):
            _fields_ = [
                ("virtual_size", ctypes.c_uint64),
                ("resident_size", ctypes.c_uint64),
                ("resident_size_max", ctypes.c_uint64),
                ("user_time", _TimeValue),
                ("system_time", _TimeValue),
                ("policy", ctypes.c_int32),
                ("suspend_count", ctypes.c_int32),
            ]

        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib")
        libc.mach_task_self.restype = ctypes.c_uint32
        task_info = libc.task_info
        task_info.argtypes = [
            ctypes.c_uint32,
            ctypes.c_int,
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_uint32),
        ]
        info = _TaskBasicInfo64()
        expected_count = ctypes.sizeof(info) // ctypes.sizeof(ctypes.c_uint32)
        count = ctypes.c_uint32(expected_count)
        status = task_info(
            libc.mach_task_self(),
            20,  # MACH_TASK_BASIC_INFO
            ctypes.byref(info),
            ctypes.byref(count),
        )
        if status != 0 or count.value != expected_count:
            raise OSError("task_info failed")
        return int(info.virtual_size)
    raise OSError("unsupported resource-limit platform")


def _install_frame_guard() -> None:
    try:
        if version("pytoniq") != _PYTONIQ_VERSION:
            raise ValueError("unsupported pytoniq version")
        from pytoniq.liteclient.client import LiteClient

        original = LiteClient.receive
        if getattr(original, "_gram_scope_bounded", False):
            return
        source_hash = hashlib.sha256(inspect.getsource(original).encode()).hexdigest()
        if source_hash != _PYTONIQ_RECEIVE_SHA256:
            raise ValueError("pytoniq receive contract changed")

        async def bounded_receive(self: Any, data_len: int) -> bytes:
            if (
                type(data_len) is not int
                or data_len < 0
                or data_len > MAX_LITECLIENT_FRAME_BYTES
            ):
                self._gram_scope_frame_limit_rejected = True
                failure = TonLiteclientFrameLimitFailure(
                    "TON liteserver frame exceeds the safe size limit."
                )
                for pending in list(getattr(self, "tasks", {}).values()):
                    if pending is not None and not pending.done():
                        pending.set_exception(failure)
                raise failure
            return await original(self, data_len)

        bounded_receive._gram_scope_bounded = True
        bounded_receive._gram_scope_original = original
        LiteClient.receive = bounded_receive
    except TonLiteclientProcessFailure:
        raise
    except Exception as exc:
        raise TonLiteclientProcessFailure(
            "TON liteserver frame guard could not be installed.",
            code="liteclient_resource_limit",
            retryable=False,
        ) from exc


def stop_process(process: Any) -> bool:
    """Best-effort terminate/kill with bounded joins; never raise."""
    try:
        if not process.is_alive():
            process.join(0)
            return True
        process.terminate()
        process.join(PROCESS_TERMINATE_GRACE_SECONDS)
        if process.is_alive():
            process.kill()
            process.join(PROCESS_KILL_GRACE_SECONDS)
        return not process.is_alive()
    except BaseException:
        return False


def start_registered_process(
    process: Any,
    *,
    cleanup_paths: tuple[str, ...] = (),
) -> None:
    """Start a child while fencing the interpreter-shutdown race."""
    if not all(isinstance(path, str) and path for path in cleanup_paths):
        invalid_ipc()
    global _SHUTTING_DOWN
    with _CHILD_REGISTRY_LOCK:
        if _SHUTTING_DOWN:
            raise TonLiteclientProcessFailure(
                "TON liteserver process supervisor is shutting down.",
                code="liteserver_capture_cancelled",
                retryable=True,
            )
        process.start()
        _ACTIVE_CHILDREN[id(process)] = (
            process,
            cleanup_paths,
            current_thread(),
        )


def unregister_process(process: Any) -> None:
    """Forget a child only after the caller has proven it is stopped."""
    with _CHILD_REGISTRY_LOCK:
        _ACTIVE_CHILDREN.pop(id(process), None)


def liteclient_process_shutting_down() -> bool:
    return _SHUTTING_DOWN


def _shutdown_registered_processes() -> None:
    """Beat multiprocessing's unbounded daemon-child atexit join."""
    global _SHUTTING_DOWN
    with _CHILD_REGISTRY_LOCK:
        _SHUTTING_DOWN = True
        registered = tuple(_ACTIVE_CHILDREN.values())
        _ACTIVE_CHILDREN.clear()
    owner_threads = []
    for process, cleanup_paths, owner_thread in registered:
        try:
            stop_process(process)
        except BaseException:
            pass
        if owner_thread is not current_thread():
            owner_threads.append(owner_thread)
        for path in cleanup_paths:
            try:
                unlink_ipc(path)
            except BaseException:
                pass
    # Give daemon supervisors time to observe the stopped child and leave
    # their Python frames before interpreter finalization closes stderr and
    # module globals. Process objects remain owned/closed by those threads.
    for owner_thread in dict.fromkeys(owner_threads):
        try:
            owner_thread.join(0.25)
        except BaseException:
            pass


# ``multiprocessing.util`` registers its own exit hook during the explicit
# import above. atexit is LIFO, so this bounded killer runs before its
# otherwise unbounded daemon-child join.
atexit.register(_shutdown_registered_processes)


@contextmanager
def liteclient_cache_lock(cache_directory: str, network: str):
    if network not in {"ton-mainnet", "ton-testnet"}:
        invalid_ipc()
    if not isinstance(cache_directory, str) or not cache_directory:
        invalid_ipc()
    base = Path(cache_directory).expanduser().absolute()
    if base.is_symlink() or (base.exists() and not base.is_dir()):
        invalid_ipc()
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    network_directory = base / network
    if network_directory.is_symlink() or (
        network_directory.exists() and not network_directory.is_dir()
    ):
        invalid_ipc()
    network_directory.mkdir(mode=0o700, exist_ok=True)
    from services.ton_liteclient_config import verifier_policy_id

    policy_directory = network_directory / verifier_policy_id(network)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(network_directory / ".capture.lock"), flags, 0o600)
    original_directory = os.getcwd()
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        # The root marker invalidates pre-policy cache. The policy namespace
        # prevents an older rolling-deployment process, which does not know
        # about this marker, from repopulating the directory used by strict v2.
        _enforce_cache_policy(network_directory, network)
        _clear_blockstore(network_directory)
        if policy_directory.is_symlink() or (
            policy_directory.exists() and not policy_directory.is_dir()
        ):
            invalid_ipc()
        policy_directory.mkdir(mode=0o700, exist_ok=True)
        _repair_blockstore(policy_directory, network)
        os.chdir(policy_directory)
        yield
    finally:
        try:
            os.chdir(original_directory)
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)


def _repair_blockstore(network_directory: Path, network: str) -> None:
    """Delete interrupted pytoniq cache files; cache bytes are never evidence."""
    _enforce_cache_policy(network_directory, network)
    blockstore = network_directory / ".blockstore"
    try:
        blockstore_metadata = blockstore.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(blockstore_metadata.st_mode):
        invalid_ipc()
    from pytoniq.liteclient.sync import parse_blocks
    from services.ton_liteclient_config import trusted_checkpoint_document

    pin_hash = trusted_checkpoint_document(network)["root_hash"]
    expected_name = re.compile(
        rf"^[0-9a-f]{{176}}{re.escape(pin_hash)}\.blks$"
    )
    valid: list[Path] = []
    for entry in blockstore.iterdir():
        if entry.is_symlink() or not entry.is_file():
            invalid_ipc()
        keep = False
        try:
            metadata = entry.stat(follow_symlinks=False)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size != 168:
                raise ValueError("invalid blockstore entry")
            data = entry.read_bytes()
            if (
                expected_name.fullmatch(entry.name)
                and entry.name == f"{data[:88].hex()}{pin_hash}.blks"
            ):
                ttl, key_ts, key_block, mc_block = parse_blocks(data)
                pinned_seqno = trusted_checkpoint_document(network)["seqno"]
                keep = _valid_cached_blocks(
                    ttl,
                    key_ts,
                    key_block,
                    mc_block,
                    pinned_seqno=pinned_seqno,
                )
        except Exception:
            keep = False
        if keep:
            valid.append(entry)
        else:
            entry.unlink(missing_ok=True)
    # pytoniq selects an arbitrary last directory entry. Its writer normally
    # leaves one file, so retain at most the newest fully parseable candidate.
    if len(valid) > 1:
        valid.sort(key=lambda item: (item.stat().st_mtime_ns, item.name))
        for entry in valid[:-1]:
            entry.unlink(missing_ok=True)


def _enforce_cache_policy(network_directory: Path, network: str) -> None:
    """Discard cache produced under an older cryptographic verifier policy."""
    from services.ton_liteclient_config import verifier_policy_id

    expected = f"{verifier_policy_id(network)}\n".encode("ascii")
    sentinel = network_directory / _CACHE_POLICY_SENTINEL
    matches = False
    try:
        metadata = sentinel.stat(follow_symlinks=False)
    except FileNotFoundError:
        metadata = None
    if metadata is not None:
        if not stat.S_ISREG(metadata.st_mode):
            invalid_ipc()
        if metadata.st_size == len(expected):
            flags = os.O_RDONLY
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            fd = os.open(str(sentinel), flags)
            try:
                if not stat.S_ISREG(os.fstat(fd).st_mode):
                    invalid_ipc()
                matches = os.read(fd, len(expected) + 1) == expected
            finally:
                os.close(fd)
    if matches:
        return
    _clear_blockstore(network_directory)
    _replace_cache_policy_sentinel(sentinel, expected)


def _clear_blockstore(network_directory: Path) -> None:
    blockstore = network_directory / ".blockstore"
    try:
        metadata = blockstore.stat(follow_symlinks=False)
    except FileNotFoundError:
        return
    if not stat.S_ISDIR(metadata.st_mode):
        invalid_ipc()
    deleted = False
    for entry in blockstore.iterdir():
        entry_metadata = entry.stat(follow_symlinks=False)
        if not stat.S_ISREG(entry_metadata.st_mode):
            invalid_ipc()
        entry.unlink()
        deleted = True
    if deleted:
        _fsync_directory(blockstore)


def _replace_cache_policy_sentinel(sentinel: Path, expected: bytes) -> None:
    fd, temporary = tempfile.mkstemp(
        prefix=f"{_CACHE_POLICY_SENTINEL}-",
        suffix=".tmp",
        dir=str(sentinel.parent),
    )
    try:
        os.fchmod(fd, 0o600)
        view = memoryview(expected)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                invalid_ipc()
            view = view[written:]
        os.fsync(fd)
        os.close(fd)
        fd = -1
        os.replace(temporary, sentinel)
        temporary = ""
        _fsync_directory(sentinel.parent)
    finally:
        if fd >= 0:
            os.close(fd)
        if temporary:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def _fsync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(str(directory), flags)
    try:
        if not stat.S_ISDIR(os.fstat(fd).st_mode):
            invalid_ipc()
        os.fsync(fd)
    finally:
        os.close(fd)


def _valid_cached_blocks(
    ttl: Any,
    key_ts: Any,
    key_block: Any,
    mc_block: Any,
    *,
    pinned_seqno: int,
) -> bool:
    try:
        blocks = (key_block, mc_block)
        return (
            type(ttl) is int
            and type(key_ts) is int
            and 0 < key_ts <= ttl <= 2**32 - 1
            and all(
                block.workchain == -1
                and block.shard == -9223372036854775808
                and pinned_seqno <= block.seqno <= 2**31 - 1
                and len(bytes(block.root_hash)) == 32
                and len(bytes(block.file_hash)) == 32
                for block in blocks
            )
            and key_block.seqno <= mc_block.seqno
        )
    except Exception:
        return False


def new_ipc_path(prefix: str, label: str) -> str:
    fd, path = tempfile.mkstemp(prefix=f"{prefix}-{label}-", suffix=".json")
    os.fchmod(fd, 0o600)
    os.close(fd)
    return path


def write_json_file(path: str, value: Any, *, maximum: int) -> None:
    encoded = canonical_json(value)
    if len(encoded) > maximum:
        invalid_ipc()
    flags = os.O_WRONLY | os.O_TRUNC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            invalid_ipc()
        view = memoryview(encoded)
        while view:
            written = os.write(fd, view)
            if written <= 0:
                invalid_ipc()
            view = view[written:]
        os.fsync(fd)
    finally:
        os.close(fd)


def read_json_file(path: str, *, maximum: int) -> Any:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            invalid_ipc()
        chunks = []
        size = 0
        while True:
            chunk = os.read(fd, min(64 * 1024, maximum + 1 - size))
            if not chunk:
                break
            chunks.append(chunk)
            size += len(chunk)
            if size > maximum:
                invalid_ipc()
    finally:
        os.close(fd)
    try:
        return json.loads(b"".join(chunks).decode("utf-8"))
    except Exception as exc:
        raise TonLiteclientProcessFailure(
            "TON liteserver IPC response is malformed.",
            code="liteserver_ipc_invalid",
            retryable=False,
        ) from exc


def canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    except Exception as exc:
        raise TonLiteclientProcessFailure(
            "TON liteserver IPC value is invalid.",
            code="liteserver_ipc_invalid",
            retryable=False,
        ) from exc


def unlink_ipc(path: str) -> None:
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


def invalid_ipc() -> None:
    raise TonLiteclientProcessFailure(
        "TON liteserver IPC contract is invalid.",
        code="liteserver_ipc_invalid",
        retryable=False,
    )


__all__ = [
    "TonLiteclientProcessFailure",
    "canonical_json",
    "child_error_envelope",
    "invalid_ipc",
    "liteclient_cache_lock",
    "liteclient_process_shutting_down",
    "read_json_file",
    "run_liteclient_subprocess",
    "start_registered_process",
    "success_envelope",
    "unregister_process",
    "write_json_file",
]
