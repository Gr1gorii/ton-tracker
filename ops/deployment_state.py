"""Serialize production rollouts and record the last successful release."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import fcntl
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Iterator


DEPLOYMENT_RECEIPT = "current-deployment.json"
_LOCK_FILE = ".deployment.lock"
_MAX_RECEIPT_BYTES = 16_384
_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
    r"(?:\.[0-9]{1,6})?Z$"
)
_IDENTITY_KEYS = {"manifest_sha256", "source_commit", "tag"}
_RECEIPT_V1_KEYS = {
    "completed_at",
    "previous_release",
    "release",
    "schema",
    "status",
}
_RECEIPT_V2_KEYS = _RECEIPT_V1_KEYS | {"operation"}
_OPERATIONS = {"deployment", "rollback"}


class DeploymentStateError(RuntimeError):
    """The private host deployment state cannot be trusted or updated."""


@dataclass(frozen=True)
class DeploymentIdentity:
    tag: str
    source_commit: str
    manifest_sha256: str


class LockedDeploymentState:
    """A private deployment state directory held under one exclusive lock."""

    def __init__(self, directory: Path, descriptor: int) -> None:
        self.directory = directory
        self._descriptor = descriptor
        self._closed = False

    @property
    def receipt_path(self) -> Path:
        return self.directory / DEPLOYMENT_RECEIPT

    def current_receipt(self) -> dict[str, object] | None:
        self._ensure_open()
        if not os.path.lexists(self.receipt_path):
            return None
        return _read_receipt(self.receipt_path)

    def record_success(
        self,
        identity: DeploymentIdentity,
        *,
        operation: str = "deployment",
        completed_at: datetime | None = None,
    ) -> Path:
        """Atomically replace current state only after a successful rollout."""
        self._ensure_open()
        _validate_identity(identity)
        if operation not in _OPERATIONS:
            raise DeploymentStateError("deployment operation is invalid")
        current = self.current_receipt()
        previous: object = None
        if current is not None:
            current_identity = current["release"]
            if current_identity == _identity_payload(identity):
                previous = current["previous_release"]
            else:
                previous = current_identity

        completed = completed_at or datetime.now(timezone.utc)
        if completed.tzinfo is None or completed.utcoffset() is None:
            raise DeploymentStateError(
                "deployment completion time must be timezone-aware"
            )
        payload: dict[str, object] = {
            "schema": "gram_scope_deployment_receipt_v2",
            "status": "active",
            "operation": operation,
            "completed_at": completed.astimezone(timezone.utc)
            .isoformat()
            .replace("+00:00", "Z"),
            "release": _identity_payload(identity),
            "previous_release": previous,
        }
        _validate_receipt(payload)
        _write_atomic_receipt(self.receipt_path, payload)
        return self.receipt_path

    def authorize(self, identity: DeploymentIdentity, *, rollback: bool) -> None:
        """Authorize only a forward deploy or the exact previous release."""
        self._ensure_open()
        _validate_identity(identity)
        current = self.current_receipt()
        if current is None:
            if rollback:
                raise DeploymentStateError(
                    "rollback requires an existing deployment receipt"
                )
            return

        current_identity = current["release"]
        previous_identity = current["previous_release"]
        target_identity = _identity_payload(identity)
        if rollback:
            if previous_identity is None:
                raise DeploymentStateError(
                    "rollback requires an immediately previous release"
                )
            if target_identity != previous_identity:
                raise DeploymentStateError(
                    "rollback bundle does not match the immediately previous release"
                )
            return

        if target_identity == current_identity:
            return
        if _release_version(identity.tag) <= _release_version(
            str(current_identity["tag"])
        ):
            raise DeploymentStateError(
                "deployment target must be newer than the current release"
            )

    def close(self) -> None:
        if self._closed:
            return
        try:
            fcntl.flock(self._descriptor, fcntl.LOCK_UN)
        finally:
            os.close(self._descriptor)
            self._closed = True

    def _ensure_open(self) -> None:
        if self._closed:
            raise DeploymentStateError("deployment state lock is not held")


@contextmanager
def locked_deployment_state(directory: Path) -> Iterator[LockedDeploymentState]:
    """Acquire one non-blocking host lock for the complete rollout lifetime."""
    _prepare_private_directory(directory)
    lock_path = directory / _LOCK_FILE
    descriptor = _open_private_regular_file(lock_path)
    state: LockedDeploymentState | None = None
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            if exc.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK}:
                raise DeploymentStateError(
                    "another deployment is already in progress"
                ) from exc
            raise DeploymentStateError("deployment lock is unavailable") from exc
        state = LockedDeploymentState(directory, descriptor)
        state.current_receipt()
        yield state
    finally:
        if state is not None:
            state.close()
        else:
            os.close(descriptor)


def _prepare_private_directory(directory: Path) -> None:
    if not directory.is_absolute():
        raise DeploymentStateError("deployment state directory must be absolute")
    try:
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        metadata = directory.lstat()
    except OSError as exc:
        raise DeploymentStateError("deployment state directory is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise DeploymentStateError(
            "deployment state directory must be private and owned by the operator"
        )


def _open_private_regular_file(path: Path) -> int:
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags, 0o600)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise DeploymentStateError("deployment lock is unavailable") from exc
    assert descriptor is not None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or metadata.st_nlink != 1
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        os.close(descriptor)
        raise DeploymentStateError("deployment lock file is not private")
    return descriptor


def _read_receipt(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor: int | None = None
    try:
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
    except OSError as exc:
        if descriptor is not None:
            os.close(descriptor)
        raise DeploymentStateError("deployment receipt is unavailable") from exc
    assert descriptor is not None
    try:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_size < 2
            or metadata.st_size > _MAX_RECEIPT_BYTES
        ):
            raise DeploymentStateError("deployment receipt is not a private file")
        payload = bytearray()
        while len(payload) <= _MAX_RECEIPT_BYTES:
            chunk = os.read(
                descriptor,
                _MAX_RECEIPT_BYTES + 1 - len(payload),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > _MAX_RECEIPT_BYTES:
            raise DeploymentStateError("deployment receipt exceeds the size limit")
    finally:
        os.close(descriptor)
    try:
        decoded = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeploymentStateError("deployment receipt is invalid") from exc
    return _validate_receipt(decoded)


def _validate_receipt(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict):
        raise DeploymentStateError("deployment receipt contract is invalid")
    schema = payload.get("schema")
    if schema == "gram_scope_deployment_receipt_v1":
        if set(payload) != _RECEIPT_V1_KEYS:
            raise DeploymentStateError("deployment receipt contract is invalid")
    elif schema == "gram_scope_deployment_receipt_v2":
        if (
            set(payload) != _RECEIPT_V2_KEYS
            or payload.get("operation") not in _OPERATIONS
        ):
            raise DeploymentStateError("deployment receipt contract is invalid")
    else:
        raise DeploymentStateError("deployment receipt contract is invalid")
    if (
        payload["status"] != "active"
        or not _valid_timestamp(payload["completed_at"])
        or not _valid_identity_payload(payload["release"])
        or (
            payload["previous_release"] is not None
            and not _valid_identity_payload(payload["previous_release"])
        )
        or payload["previous_release"] == payload["release"]
    ):
        raise DeploymentStateError("deployment receipt fields are invalid")
    return payload


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() == timedelta(0)


def _identity_payload(identity: DeploymentIdentity) -> dict[str, str]:
    return {
        "tag": identity.tag,
        "source_commit": identity.source_commit,
        "manifest_sha256": identity.manifest_sha256,
    }


def _validate_identity(identity: DeploymentIdentity) -> None:
    if not _valid_identity_payload(_identity_payload(identity)):
        raise DeploymentStateError("deployment identity is invalid")


def _valid_identity_payload(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and set(payload) == _IDENTITY_KEYS
        and isinstance(payload["tag"], str)
        and _TAG.fullmatch(payload["tag"]) is not None
        and isinstance(payload["source_commit"], str)
        and _COMMIT.fullmatch(payload["source_commit"]) is not None
        and isinstance(payload["manifest_sha256"], str)
        and _DIGEST.fullmatch(payload["manifest_sha256"]) is not None
    )


def _release_version(tag: str) -> tuple[int, int, int]:
    match = _TAG.fullmatch(tag)
    if match is None:
        raise DeploymentStateError("deployment identity is invalid")
    return tuple(int(value) for value in match.groups())


def _write_atomic_receipt(path: Path, payload: dict[str, object]) -> None:
    raw = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")
    if len(raw) > _MAX_RECEIPT_BYTES:
        raise DeploymentStateError("deployment receipt exceeds the size limit")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor: int | None = None
    try:
        descriptor = os.open(
            temporary,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = None
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise DeploymentStateError("deployment receipt could not be recorded") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
