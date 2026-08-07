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
DEPLOYMENT_ATTEMPT = "pending-deployment.json"
_LOCK_FILE = ".deployment.lock"
_MAX_STATE_BYTES = 16_384
_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID = re.compile(r"^[0-9a-f]{32}$")
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
_RECEIPT_V3_KEYS = _RECEIPT_V2_KEYS | {"attempt_id"}
_ATTEMPT_KEYS = {
    "attempt_id",
    "base_release",
    "operation",
    "schema",
    "started_at",
    "status",
    "target_release",
}
_OPERATIONS = {"deployment", "rollback"}


class DeploymentStateError(RuntimeError):
    """The private host deployment state cannot be trusted or updated."""


@dataclass(frozen=True)
class DeploymentIdentity:
    tag: str
    source_commit: str
    manifest_sha256: str


@dataclass(frozen=True)
class DeploymentAttempt:
    attempt_id: str
    operation: str
    already_completed: bool = False


class LockedDeploymentState:
    """A private deployment state directory held under one exclusive lock."""

    def __init__(self, directory: Path, descriptor: int) -> None:
        self.directory = directory
        self._descriptor = descriptor
        self._closed = False

    @property
    def receipt_path(self) -> Path:
        return self.directory / DEPLOYMENT_RECEIPT

    @property
    def attempt_path(self) -> Path:
        return self.directory / DEPLOYMENT_ATTEMPT

    def current_receipt(self) -> dict[str, object] | None:
        self._ensure_open()
        if not os.path.lexists(self.receipt_path):
            return None
        return _read_receipt(self.receipt_path)

    def current_attempt(self) -> dict[str, object] | None:
        self._ensure_open()
        if not os.path.lexists(self.attempt_path):
            return None
        return _read_attempt(self.attempt_path)

    def record_success(
        self,
        identity: DeploymentIdentity,
        *,
        operation: str = "deployment",
        completed_at: datetime | None = None,
        attempt_id: str | None = None,
    ) -> Path:
        """Atomically replace current state only after a successful rollout."""
        self._ensure_open()
        _validate_identity(identity)
        if not isinstance(operation, str) or operation not in _OPERATIONS:
            raise DeploymentStateError("deployment operation is invalid")
        receipt_attempt_id = (
            secrets.token_hex(16) if attempt_id is None else attempt_id
        )
        if (
            not isinstance(receipt_attempt_id, str)
            or _ATTEMPT_ID.fullmatch(receipt_attempt_id) is None
        ):
            raise DeploymentStateError("deployment attempt id is invalid")
        current = self.current_receipt()
        previous: object = None
        if current is not None:
            current_identity = current["release"]
            if current_identity == _identity_payload(identity):
                previous = current["previous_release"]
            else:
                previous = current_identity

        completed = completed_at or datetime.now(timezone.utc)
        if (
            not isinstance(completed, datetime)
            or completed.tzinfo is None
            or completed.utcoffset() is None
        ):
            raise DeploymentStateError(
                "deployment completion time must be timezone-aware"
            )
        payload: dict[str, object] = {
            "schema": "gram_scope_deployment_receipt_v3",
            "status": "active",
            "operation": operation,
            "attempt_id": receipt_attempt_id,
            "completed_at": _utc_timestamp(completed),
            "release": _identity_payload(identity),
            "previous_release": previous,
        }
        _validate_receipt(payload)
        _write_atomic_receipt(self.receipt_path, payload)
        return self.receipt_path

    def prepare_attempt(
        self,
        identity: DeploymentIdentity,
        *,
        rollback: bool,
        resume: bool,
        started_at: datetime | None = None,
    ) -> DeploymentAttempt:
        """Create or explicitly resume one durable rollout intent."""
        self._ensure_open()
        _validate_identity(identity)
        operation = "rollback" if rollback else "deployment"
        target = _identity_payload(identity)
        current = self.current_receipt()
        current_release = current["release"] if current is not None else None
        pending = self.current_attempt()

        if pending is not None:
            if not resume:
                raise DeploymentStateError(
                    "an interrupted deployment attempt exists; rerun its exact "
                    "signed release with the matching operation and --resume"
                )
            if (
                pending["target_release"] != target
                or pending["operation"] != operation
            ):
                raise DeploymentStateError(
                    "resume bundle or operation does not match the pending attempt"
                )
            attempt_id = str(pending["attempt_id"])
            if (
                current is not None
                and current.get("attempt_id") == attempt_id
                and current["release"] == target
                and current.get("operation") == operation
            ):
                self._clear_attempt()
                return DeploymentAttempt(
                    attempt_id=attempt_id,
                    operation=operation,
                    already_completed=True,
                )
            if pending["base_release"] != current_release:
                raise DeploymentStateError(
                    "deployment receipt changed after the pending attempt started"
                )
            self.authorize(identity, rollback=rollback)
            return DeploymentAttempt(
                attempt_id=attempt_id,
                operation=operation,
            )

        if resume:
            raise DeploymentStateError("no interrupted deployment attempt exists")
        self.authorize(identity, rollback=rollback)
        started = started_at or datetime.now(timezone.utc)
        if (
            not isinstance(started, datetime)
            or started.tzinfo is None
            or started.utcoffset() is None
        ):
            raise DeploymentStateError("deployment start time must be timezone-aware")
        attempt_id = secrets.token_hex(16)
        payload: dict[str, object] = {
            "schema": "gram_scope_deployment_attempt_v1",
            "status": "pending",
            "operation": operation,
            "attempt_id": attempt_id,
            "started_at": _utc_timestamp(started),
            "base_release": current_release,
            "target_release": target,
        }
        _validate_attempt(payload)
        _write_atomic_attempt(self.attempt_path, payload)
        return DeploymentAttempt(
            attempt_id=attempt_id,
            operation=operation,
        )

    def complete_attempt(
        self,
        identity: DeploymentIdentity,
        attempt: DeploymentAttempt,
        *,
        completed_at: datetime | None = None,
    ) -> Path:
        """Commit one successful attempt, then durably clear its journal."""
        self._ensure_open()
        _validate_identity(identity)
        pending = self.current_attempt()
        if pending is None:
            raise DeploymentStateError("pending deployment attempt is unavailable")
        if (
            pending["attempt_id"] != attempt.attempt_id
            or pending["operation"] != attempt.operation
            or pending["target_release"] != _identity_payload(identity)
        ):
            raise DeploymentStateError("pending deployment attempt changed")
        current = self.current_receipt()
        current_release = current["release"] if current is not None else None
        if pending["base_release"] != current_release:
            raise DeploymentStateError(
                "deployment receipt changed after the pending attempt started"
            )
        receipt = self.record_success(
            identity,
            operation=attempt.operation,
            completed_at=completed_at,
            attempt_id=attempt.attempt_id,
        )
        self._clear_attempt()
        return receipt

    def _clear_attempt(self) -> None:
        try:
            self.attempt_path.unlink()
            _fsync_directory(self.directory)
        except OSError as exc:
            raise DeploymentStateError(
                "pending deployment attempt could not be cleared"
            ) from exc

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
        state.current_attempt()
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
    return _validate_receipt(_read_private_json(path, "deployment receipt"))


def _read_attempt(path: Path) -> dict[str, object]:
    return _validate_attempt(_read_private_json(path, "deployment attempt"))


def _read_private_json(path: Path, label: str) -> object:
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
        raise DeploymentStateError(f"{label} is unavailable") from exc
    assert descriptor is not None
    try:
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_nlink != 1
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_size < 2
            or metadata.st_size > _MAX_STATE_BYTES
        ):
            raise DeploymentStateError(f"{label} is not a private file")
        payload = bytearray()
        while len(payload) <= _MAX_STATE_BYTES:
            chunk = os.read(
                descriptor,
                _MAX_STATE_BYTES + 1 - len(payload),
            )
            if not chunk:
                break
            payload.extend(chunk)
        if len(payload) > _MAX_STATE_BYTES:
            raise DeploymentStateError(f"{label} exceeds the size limit")
    finally:
        os.close(descriptor)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeploymentStateError(f"{label} is invalid") from exc


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
            or not isinstance(payload.get("operation"), str)
            or payload.get("operation") not in _OPERATIONS
        ):
            raise DeploymentStateError("deployment receipt contract is invalid")
    elif schema == "gram_scope_deployment_receipt_v3":
        if (
            set(payload) != _RECEIPT_V3_KEYS
            or not isinstance(payload.get("operation"), str)
            or payload.get("operation") not in _OPERATIONS
            or not isinstance(payload.get("attempt_id"), str)
            or _ATTEMPT_ID.fullmatch(payload["attempt_id"]) is None
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


def _validate_attempt(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _ATTEMPT_KEYS:
        raise DeploymentStateError("deployment attempt contract is invalid")
    if (
        payload["schema"] != "gram_scope_deployment_attempt_v1"
        or payload["status"] != "pending"
        or not isinstance(payload["operation"], str)
        or payload["operation"] not in _OPERATIONS
        or not isinstance(payload["attempt_id"], str)
        or _ATTEMPT_ID.fullmatch(payload["attempt_id"]) is None
        or not _valid_timestamp(payload["started_at"])
        or not _valid_identity_payload(payload["target_release"])
        or (
            payload["base_release"] is not None
            and not _valid_identity_payload(payload["base_release"])
        )
    ):
        raise DeploymentStateError("deployment attempt fields are invalid")
    return payload


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or _TIMESTAMP.fullmatch(value) is None:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.utcoffset() == timedelta(0)


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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
    _write_atomic_state(path, payload, "deployment receipt")


def _write_atomic_attempt(path: Path, payload: dict[str, object]) -> None:
    _write_atomic_state(path, payload, "deployment attempt")


def _write_atomic_state(
    path: Path,
    payload: dict[str, object],
    label: str,
) -> None:
    raw = (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")
    if len(raw) > _MAX_STATE_BYTES:
        raise DeploymentStateError(f"{label} exceeds the size limit")
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
        raise DeploymentStateError(f"{label} could not be recorded") from exc
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
