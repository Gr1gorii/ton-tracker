"""Serialize production rollouts and record the last successful release."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
from typing import Iterator


DEPLOYMENT_RECEIPT = "current-deployment.json"
DEPLOYMENT_ATTEMPT = "pending-deployment.json"
DEPLOYMENT_LEDGER = "deployment-events"
_LOCK_FILE = ".deployment.lock"
_MAX_STATE_BYTES = 16_384
_MAX_LEDGER_EVENTS = 100_000
_TAG = re.compile(r"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ATTEMPT_ID = re.compile(r"^[0-9a-f]{32}$")
_EVENT_FILE = re.compile(r"^([0-9]{20})-([0-9a-f]{64})\.json$")
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
_RECEIPT_V4_KEYS = _RECEIPT_V3_KEYS | {
    "ledger_event_sha256",
    "ledger_sequence",
}
_ATTEMPT_V1_KEYS = {
    "attempt_id",
    "base_release",
    "operation",
    "schema",
    "started_at",
    "status",
    "target_release",
}
_ATTEMPT_V2_KEYS = _ATTEMPT_V1_KEYS | {"rollout_phase"}
_ROLLOUT_PHASES = {"prepared", "initial_bootstrap_verified"}
_OPERATIONS = {"deployment", "rollback"}
_EVENT_KEYS = {
    "attempt_id",
    "base_release",
    "completed_at",
    "operation",
    "previous_event_sha256",
    "previous_release",
    "release",
    "schema",
    "sequence",
}


class DeploymentStateError(RuntimeError):
    """The private host deployment state cannot be trusted or updated."""


class DeploymentStateBusyError(DeploymentStateError):
    """Another process holds the deployment state lock."""


@dataclass(frozen=True)
class DeploymentIdentity:
    tag: str
    source_commit: str
    manifest_sha256: str


@dataclass(frozen=True)
class DeploymentAttempt:
    attempt_id: str
    operation: str
    initial_deployment: bool = False
    rollout_phase: str = "prepared"
    already_completed: bool = False


@dataclass(frozen=True)
class _LedgerEvent:
    payload: dict[str, object]
    sha256: str
    path: Path


@dataclass(frozen=True)
class _LedgerSnapshot:
    event_count: int
    previous: _LedgerEvent | None
    head: _LedgerEvent | None


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

    @property
    def ledger_path(self) -> Path:
        return self.directory / DEPLOYMENT_LEDGER

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

    def current_ledger_event(self) -> dict[str, object] | None:
        """Return the verified ledger head without exposing mutable internals."""
        self._ensure_open()
        head = _read_ledger(self.ledger_path).head
        return None if head is None else dict(head.payload)

    def validate_consistency(self) -> None:
        """Fail closed unless receipt, journal, and ledger form one state."""
        self._ensure_open()
        _validate_state_consistency(
            self.current_receipt(),
            self.current_attempt(),
            _read_ledger(self.ledger_path),
        )

    def audit_report(self) -> dict[str, object]:
        """Build a stable, credential-free view of the verified state."""
        self._ensure_open()
        receipt = self.current_receipt()
        pending = self.current_attempt()
        ledger = _read_ledger(self.ledger_path)
        _validate_state_consistency(receipt, pending, ledger)
        head = ledger.head
        if head is None:
            binding = "none"
        elif _receipt_matches_event(receipt, head):
            binding = "bound"
        else:
            binding = "awaiting_receipt"
        if pending is not None:
            status = "interrupted"
        elif receipt is None:
            status = "empty"
        else:
            status = "ready"
        return {
            "schema": "gram_scope_deployment_audit_v2",
            "status": status,
            "active_release": None if receipt is None else receipt["release"],
            "previous_release": (
                None if receipt is None else receipt["previous_release"]
            ),
            "receipt": (
                None
                if receipt is None
                else {
                    "schema": receipt["schema"],
                    "operation": receipt.get("operation"),
                    "attempt_id": receipt.get("attempt_id"),
                    "completed_at": receipt["completed_at"],
                }
            ),
            "ledger": {
                "event_count": ledger.event_count,
                "head_sequence": None if head is None else head.payload["sequence"],
                "head_sha256": None if head is None else head.sha256,
                "receipt_binding": binding,
            },
            "pending_attempt": (
                None
                if pending is None
                else {
                    "attempt_id": pending["attempt_id"],
                    "operation": pending["operation"],
                    "started_at": pending["started_at"],
                    "base_release": pending["base_release"],
                    "target_release": pending["target_release"],
                    "rollout_phase": _attempt_rollout_phase(pending),
                }
            ),
        }

    def record_success(
        self,
        identity: DeploymentIdentity,
        *,
        operation: str = "deployment",
        completed_at: datetime | None = None,
        attempt_id: str | None = None,
    ) -> Path:
        """Append one event and bind the active receipt to its verified hash."""
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
        ledger = _read_ledger(self.ledger_path)
        pending = self.current_attempt()
        _validate_state_consistency(current, pending, ledger)
        _require_committed_ledger_head(current, ledger)
        self.authorize(identity, rollback=operation == "rollback")
        if pending is not None and (
            pending["attempt_id"] != receipt_attempt_id
            or pending["operation"] != operation
            or pending["base_release"]
            != (None if current is None else current["release"])
            or pending["target_release"] != _identity_payload(identity)
        ):
            raise DeploymentStateError("pending deployment attempt changed")
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
        event_payload: dict[str, object] = {
            "schema": "gram_scope_deployment_event_v1",
            "sequence": 1 if ledger.head is None else ledger.head.payload["sequence"] + 1,
            "operation": operation,
            "attempt_id": receipt_attempt_id,
            "completed_at": _utc_timestamp(completed),
            "base_release": None if current is None else current["release"],
            "release": _identity_payload(identity),
            "previous_release": previous,
            "previous_event_sha256": (
                None if ledger.head is None else ledger.head.sha256
            ),
        }
        _validate_event(event_payload)
        _validate_event_chain(event_payload, ledger.head)
        event = _write_ledger_event(self.directory, self.ledger_path, event_payload)
        payload: dict[str, object] = {
            "schema": "gram_scope_deployment_receipt_v4",
            "status": "active",
            "operation": operation,
            "attempt_id": receipt_attempt_id,
            "completed_at": event_payload["completed_at"],
            "release": event_payload["release"],
            "previous_release": event_payload["previous_release"],
            "ledger_sequence": event_payload["sequence"],
            "ledger_event_sha256": event.sha256,
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
        ledger = _read_ledger(self.ledger_path)
        _validate_state_consistency(current, pending, ledger)

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
                ledger.head is not None
                and ledger.head.payload["attempt_id"] == attempt_id
            ):
                if not _receipt_matches_event(current, ledger.head):
                    _write_atomic_receipt(
                        self.receipt_path,
                        _receipt_from_event(ledger.head),
                    )
                self._clear_attempt()
                return DeploymentAttempt(
                    attempt_id=attempt_id,
                    operation=operation,
                    initial_deployment=pending["base_release"] is None,
                    rollout_phase=_attempt_rollout_phase(pending),
                    already_completed=True,
                )
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
                    initial_deployment=pending["base_release"] is None,
                    rollout_phase=_attempt_rollout_phase(pending),
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
                initial_deployment=pending["base_release"] is None,
                rollout_phase=_attempt_rollout_phase(pending),
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
            "schema": "gram_scope_deployment_attempt_v2",
            "status": "pending",
            "operation": operation,
            "attempt_id": attempt_id,
            "started_at": _utc_timestamp(started),
            "base_release": current_release,
            "target_release": target,
            "rollout_phase": "prepared",
        }
        _validate_attempt(payload)
        _write_atomic_attempt(self.attempt_path, payload)
        return DeploymentAttempt(
            attempt_id=attempt_id,
            operation=operation,
            initial_deployment=current_release is None,
            rollout_phase="prepared",
        )

    def mark_initial_bootstrap_verified(
        self,
        identity: DeploymentIdentity,
        attempt: DeploymentAttempt,
    ) -> None:
        """Durably authorize an initial rollout to resume after its empty-volume gate."""
        self._ensure_open()
        _validate_identity(identity)
        pending = self.current_attempt()
        if pending is None:
            raise DeploymentStateError("pending deployment attempt is unavailable")
        if (
            pending["attempt_id"] != attempt.attempt_id
            or pending["operation"] != "deployment"
            or pending["target_release"] != _identity_payload(identity)
            or pending["base_release"] is not None
        ):
            raise DeploymentStateError("initial deployment attempt changed")
        current = self.current_receipt()
        ledger = _read_ledger(self.ledger_path)
        _validate_state_consistency(current, pending, ledger)
        if current is not None:
            raise DeploymentStateError("initial deployment receipt changed")
        phase = _attempt_rollout_phase(pending)
        if phase == "initial_bootstrap_verified":
            return
        if phase != "prepared":
            raise DeploymentStateError("deployment rollout phase is invalid")
        checkpoint = {
            **pending,
            "schema": "gram_scope_deployment_attempt_v2",
            "rollout_phase": "initial_bootstrap_verified",
        }
        _validate_attempt(checkpoint)
        _write_atomic_attempt(self.attempt_path, checkpoint)

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
        ledger = _read_ledger(self.ledger_path)
        _validate_state_consistency(current, pending, ledger)
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
                raise DeploymentStateBusyError(
                    "another deployment is already in progress"
                ) from exc
            raise DeploymentStateError("deployment lock is unavailable") from exc
        state = LockedDeploymentState(directory, descriptor)
        state.validate_consistency()
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


def _validate_private_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise DeploymentStateError(f"{label} is unavailable") from exc
    if (
        not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.geteuid()
        or stat.S_IMODE(metadata.st_mode) & 0o077
    ):
        raise DeploymentStateError(
            f"{label} must be private and owned by the operator"
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


def _read_ledger(path: Path) -> _LedgerSnapshot:
    if not os.path.lexists(path):
        return _LedgerSnapshot(event_count=0, previous=None, head=None)
    _validate_private_directory(path, "deployment ledger")
    try:
        entries = sorted(path.iterdir(), key=lambda entry: entry.name)
    except OSError as exc:
        raise DeploymentStateError("deployment ledger is unavailable") from exc
    if len(entries) > _MAX_LEDGER_EVENTS:
        raise DeploymentStateError("deployment ledger exceeds the event limit")

    prior: _LedgerEvent | None = None
    penultimate: _LedgerEvent | None = None
    for expected_sequence, entry in enumerate(entries, start=1):
        match = _EVENT_FILE.fullmatch(entry.name)
        if match is None or int(match.group(1)) != expected_sequence:
            raise DeploymentStateError("deployment ledger sequence is invalid")
        raw = _read_private_bytes(entry, "deployment ledger event")
        digest = hashlib.sha256(raw).hexdigest()
        if digest != match.group(2):
            raise DeploymentStateError("deployment ledger event digest is invalid")
        try:
            payload = _validate_event(json.loads(raw.decode("utf-8")))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise DeploymentStateError("deployment ledger event is invalid") from exc
        if raw != _canonical_json_bytes(payload):
            raise DeploymentStateError("deployment ledger event is not canonical")
        if payload["sequence"] != expected_sequence:
            raise DeploymentStateError("deployment ledger sequence is invalid")
        _validate_event_chain(payload, prior)
        penultimate = prior
        prior = _LedgerEvent(payload=payload, sha256=digest, path=entry)
    return _LedgerSnapshot(
        event_count=len(entries),
        previous=penultimate,
        head=prior,
    )


def _read_private_json(path: Path, label: str) -> object:
    payload = _read_private_bytes(path, label)
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise DeploymentStateError(f"{label} is invalid") from exc


def _read_private_bytes(path: Path, label: str) -> bytes:
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
    return bytes(payload)


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
    elif schema == "gram_scope_deployment_receipt_v4":
        if (
            set(payload) != _RECEIPT_V4_KEYS
            or not isinstance(payload.get("operation"), str)
            or payload.get("operation") not in _OPERATIONS
            or not isinstance(payload.get("attempt_id"), str)
            or _ATTEMPT_ID.fullmatch(payload["attempt_id"]) is None
            or not isinstance(payload.get("ledger_sequence"), int)
            or isinstance(payload.get("ledger_sequence"), bool)
            or payload["ledger_sequence"] < 1
            or payload["ledger_sequence"] > _MAX_LEDGER_EVENTS
            or not isinstance(payload.get("ledger_event_sha256"), str)
            or _DIGEST.fullmatch(payload["ledger_event_sha256"]) is None
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
    if not isinstance(payload, dict):
        raise DeploymentStateError("deployment attempt contract is invalid")
    schema = payload.get("schema")
    if schema == "gram_scope_deployment_attempt_v1":
        if set(payload) != _ATTEMPT_V1_KEYS:
            raise DeploymentStateError("deployment attempt contract is invalid")
    elif schema == "gram_scope_deployment_attempt_v2":
        if set(payload) != _ATTEMPT_V2_KEYS:
            raise DeploymentStateError("deployment attempt contract is invalid")
    else:
        raise DeploymentStateError("deployment attempt contract is invalid")
    if (
        payload["status"] != "pending"
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
    if schema == "gram_scope_deployment_attempt_v2":
        phase = payload["rollout_phase"]
        if (
            not isinstance(phase, str)
            or phase not in _ROLLOUT_PHASES
            or (
                phase == "initial_bootstrap_verified"
                and (
                    payload["base_release"] is not None
                    or payload["operation"] != "deployment"
                )
            )
        ):
            raise DeploymentStateError("deployment attempt fields are invalid")
    return payload


def _attempt_rollout_phase(payload: dict[str, object]) -> str:
    phase = payload.get("rollout_phase", "prepared")
    if not isinstance(phase, str) or phase not in _ROLLOUT_PHASES:
        raise DeploymentStateError("deployment rollout phase is invalid")
    return phase


def _validate_event(payload: object) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != _EVENT_KEYS:
        raise DeploymentStateError("deployment ledger event contract is invalid")
    sequence = payload["sequence"]
    previous_digest = payload["previous_event_sha256"]
    if (
        payload["schema"] != "gram_scope_deployment_event_v1"
        or not isinstance(sequence, int)
        or isinstance(sequence, bool)
        or sequence < 1
        or sequence > _MAX_LEDGER_EVENTS
        or not isinstance(payload["operation"], str)
        or payload["operation"] not in _OPERATIONS
        or not isinstance(payload["attempt_id"], str)
        or _ATTEMPT_ID.fullmatch(payload["attempt_id"]) is None
        or not _valid_timestamp(payload["completed_at"])
        or not _valid_identity_payload(payload["release"])
        or (
            payload["base_release"] is not None
            and not _valid_identity_payload(payload["base_release"])
        )
        or (
            payload["previous_release"] is not None
            and not _valid_identity_payload(payload["previous_release"])
        )
        or payload["previous_release"] == payload["release"]
        or (
            previous_digest is not None
            and (
                not isinstance(previous_digest, str)
                or _DIGEST.fullmatch(previous_digest) is None
            )
        )
    ):
        raise DeploymentStateError("deployment ledger event fields are invalid")
    return payload


def _validate_event_chain(
    payload: dict[str, object],
    prior: _LedgerEvent | None,
) -> None:
    if prior is None:
        if payload["sequence"] != 1 or payload["previous_event_sha256"] is not None:
            raise DeploymentStateError("deployment ledger genesis is invalid")
        return
    prior_payload = prior.payload
    if (
        payload["sequence"] != prior_payload["sequence"] + 1
        or payload["previous_event_sha256"] != prior.sha256
        or payload["base_release"] != prior_payload["release"]
    ):
        raise DeploymentStateError("deployment ledger chain is invalid")
    target = payload["release"]
    active = prior_payload["release"]
    expected_previous = (
        prior_payload["previous_release"] if target == active else active
    )
    if payload["previous_release"] != expected_previous:
        raise DeploymentStateError("deployment ledger transition is invalid")
    if payload["operation"] == "rollback":
        if target != prior_payload["previous_release"]:
            raise DeploymentStateError("deployment ledger rollback is invalid")
    elif target != active and _release_version(str(target["tag"])) <= _release_version(
        str(active["tag"])
    ):
        raise DeploymentStateError("deployment ledger deployment is invalid")


def _receipt_from_event(event: _LedgerEvent) -> dict[str, object]:
    payload = event.payload
    receipt: dict[str, object] = {
        "schema": "gram_scope_deployment_receipt_v4",
        "status": "active",
        "operation": payload["operation"],
        "attempt_id": payload["attempt_id"],
        "completed_at": payload["completed_at"],
        "release": payload["release"],
        "previous_release": payload["previous_release"],
        "ledger_sequence": payload["sequence"],
        "ledger_event_sha256": event.sha256,
    }
    return _validate_receipt(receipt)


def _receipt_matches_event(
    receipt: dict[str, object] | None,
    event: _LedgerEvent,
) -> bool:
    return receipt == _receipt_from_event(event)


def _pending_matches_event(
    pending: dict[str, object],
    event: _LedgerEvent,
) -> bool:
    payload = event.payload
    return (
        pending["attempt_id"] == payload["attempt_id"]
        and pending["operation"] == payload["operation"]
        and pending["base_release"] == payload["base_release"]
        and pending["target_release"] == payload["release"]
    )


def _validate_state_consistency(
    receipt: dict[str, object] | None,
    pending: dict[str, object] | None,
    ledger: _LedgerSnapshot,
) -> None:
    head = ledger.head
    if head is None:
        if receipt is not None and receipt["schema"] == "gram_scope_deployment_receipt_v4":
            raise DeploymentStateError("deployment receipt ledger head is unavailable")
        if pending is not None:
            active = None if receipt is None else receipt["release"]
            legacy_receipt_committed = (
                receipt is not None
                and receipt["schema"] == "gram_scope_deployment_receipt_v3"
                and receipt["attempt_id"] == pending["attempt_id"]
                and receipt["operation"] == pending["operation"]
                and receipt["release"] == pending["target_release"]
                and (
                    pending["base_release"] == receipt["release"]
                    or pending["base_release"] == receipt["previous_release"]
                )
            )
            if pending["base_release"] != active and not legacy_receipt_committed:
                raise DeploymentStateError("deployment journal base is inconsistent")
        return

    if _receipt_matches_event(receipt, head):
        if pending is None:
            return
        if pending["attempt_id"] == head.payload["attempt_id"]:
            if not _pending_matches_event(pending, head):
                raise DeploymentStateError("deployment journal and ledger disagree")
        elif pending["base_release"] != receipt["release"]:
            raise DeploymentStateError("deployment journal base is inconsistent")
        return

    if pending is None or not _pending_matches_event(pending, head):
        raise DeploymentStateError("deployment receipt is not bound to the ledger head")
    if ledger.previous is None:
        if receipt is not None and receipt["schema"] == "gram_scope_deployment_receipt_v4":
            raise DeploymentStateError("deployment receipt ledger sequence is invalid")
    elif not _receipt_matches_event(receipt, ledger.previous):
        raise DeploymentStateError("deployment receipt is not bound to the prior ledger event")
    active = None if receipt is None else receipt["release"]
    if active != head.payload["base_release"]:
        raise DeploymentStateError("deployment ledger base is inconsistent")


def _require_committed_ledger_head(
    receipt: dict[str, object] | None,
    ledger: _LedgerSnapshot,
) -> None:
    if ledger.head is None:
        if receipt is not None and receipt["schema"] == "gram_scope_deployment_receipt_v4":
            raise DeploymentStateError("deployment receipt ledger head is unavailable")
        return
    if not _receipt_matches_event(receipt, ledger.head):
        raise DeploymentStateError("deployment ledger contains an uncommitted event")


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


def _write_ledger_event(
    state_directory: Path,
    ledger_path: Path,
    payload: dict[str, object],
) -> _LedgerEvent:
    try:
        created = not os.path.lexists(ledger_path)
        ledger_path.mkdir(mode=0o700, exist_ok=True)
        _validate_private_directory(ledger_path, "deployment ledger")
        if created:
            _fsync_directory(state_directory)
    except (OSError, DeploymentStateError) as exc:
        if isinstance(exc, DeploymentStateError):
            raise
        raise DeploymentStateError("deployment ledger is unavailable") from exc

    raw = _canonical_json_bytes(payload)
    if len(raw) > _MAX_STATE_BYTES:
        raise DeploymentStateError("deployment ledger event exceeds the size limit")
    digest = hashlib.sha256(raw).hexdigest()
    sequence = payload["sequence"]
    target = ledger_path / f"{sequence:020d}-{digest}.json"
    if os.path.lexists(target):
        raise DeploymentStateError("deployment ledger event already exists")
    temporary = state_directory / f".deployment-event.{secrets.token_hex(8)}.tmp"
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
        if os.path.lexists(target):
            raise DeploymentStateError("deployment ledger event already exists")
        os.replace(temporary, target)
        _fsync_directory(ledger_path)
    except DeploymentStateError:
        raise
    except OSError as exc:
        raise DeploymentStateError("deployment ledger event could not be recorded") from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
    return _LedgerEvent(payload=payload, sha256=digest, path=target)


def _write_atomic_state(
    path: Path,
    payload: dict[str, object],
    label: str,
) -> None:
    raw = _canonical_json_bytes(payload)
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


def _canonical_json_bytes(payload: dict[str, object]) -> bytes:
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
