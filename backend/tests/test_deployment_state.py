"""Exclusive and durable production deployment state tests."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import pytest

from ops.deployment_state import (
    DEPLOYMENT_ATTEMPT,
    DEPLOYMENT_LEDGER,
    DEPLOYMENT_RECEIPT,
    DeploymentIdentity,
    DeploymentStateError,
    locked_deployment_state,
)


def _identity(tag: str = "v0.60.0", marker: str = "a") -> DeploymentIdentity:
    return DeploymentIdentity(
        tag=tag,
        source_commit=marker * 40,
        manifest_sha256=marker * 64,
    )


def _event_files(directory: Path) -> list[Path]:
    return sorted((directory / DEPLOYMENT_LEDGER).iterdir())


def test_locked_state_records_private_atomic_current_and_previous_release(tmp_path):
    directory = tmp_path / "state"
    first_completed = datetime(2026, 8, 8, 1, 2, 3, tzinfo=timezone.utc)
    with locked_deployment_state(directory) as state:
        assert state.current_receipt() is None
        receipt_path = state.record_success(
            _identity("v0.59.0", "a"),
            completed_at=first_completed,
            attempt_id="1" * 32,
        )
        first = state.current_receipt()

    assert receipt_path == directory / DEPLOYMENT_RECEIPT
    assert directory.stat().st_mode & 0o777 == 0o700
    assert receipt_path.stat().st_mode & 0o777 == 0o600
    assert (directory / ".deployment.lock").stat().st_mode & 0o777 == 0o600
    assert first == {
        "schema": "gram_scope_deployment_receipt_v4",
        "status": "active",
        "operation": "deployment",
        "attempt_id": "1" * 32,
        "completed_at": "2026-08-08T01:02:03Z",
        "release": {
            "tag": "v0.59.0",
            "source_commit": "a" * 40,
            "manifest_sha256": "a" * 64,
        },
        "previous_release": None,
        "ledger_sequence": 1,
        "ledger_event_sha256": first["ledger_event_sha256"],
    }
    first_event_path = _event_files(directory)[0]
    assert first_event_path.stat().st_mode & 0o777 == 0o600
    assert first_event_path.name == (
        f"{1:020d}-{first['ledger_event_sha256']}.json"
    )
    first_event = json.loads(first_event_path.read_text(encoding="utf-8"))
    assert first_event["base_release"] is None
    assert first_event["previous_event_sha256"] is None
    assert first_event["release"] == first["release"]
    assert list(directory.glob(f".{DEPLOYMENT_RECEIPT}.*.tmp")) == []

    with locked_deployment_state(directory) as state:
        state.record_success(
            _identity("v0.60.0", "b"),
            completed_at=datetime(2026, 8, 8, 2, 3, 4, tzinfo=timezone.utc),
        )
        second = state.current_receipt()

    assert second["release"] == {
        "tag": "v0.60.0",
        "source_commit": "b" * 40,
        "manifest_sha256": "b" * 64,
    }
    assert second["previous_release"] == first["release"]
    assert second["operation"] == "deployment"
    assert second["ledger_sequence"] == 2
    second_event = json.loads(_event_files(directory)[1].read_text(encoding="utf-8"))
    assert second_event["base_release"] == first["release"]
    assert second_event["previous_event_sha256"] == first["ledger_event_sha256"]


def test_redeploying_same_identity_preserves_true_previous_release(tmp_path):
    directory = tmp_path / "state"
    with locked_deployment_state(directory) as state:
        state.record_success(_identity("v0.58.0", "a"))
        state.record_success(_identity("v0.59.0", "b"))
        previous = state.current_receipt()["previous_release"]
        state.record_success(_identity("v0.59.0", "b"))
        current = state.current_receipt()

    assert current["previous_release"] == previous


def test_authorization_allows_forward_or_exact_previous_release_only(tmp_path):
    directory = tmp_path / "state"
    release_58 = _identity("v0.58.0", "a")
    release_59 = _identity("v0.59.0", "b")
    release_60 = _identity("v0.60.0", "c")
    conflicting_60 = _identity("v0.60.0", "d")
    release_61 = _identity("v0.61.0", "d")

    with locked_deployment_state(directory) as state:
        with pytest.raises(DeploymentStateError, match="existing deployment"):
            state.authorize(release_59, rollback=True)
        state.authorize(release_59, rollback=False)
        state.record_success(release_59)

        state.authorize(release_59, rollback=False)
        state.authorize(release_60, rollback=False)
        with pytest.raises(DeploymentStateError, match="must be newer"):
            state.authorize(release_58, rollback=False)
        with pytest.raises(DeploymentStateError, match="immediately previous"):
            state.authorize(release_58, rollback=True)

        state.record_success(release_60)
        with pytest.raises(DeploymentStateError, match="must be newer"):
            state.authorize(conflicting_60, rollback=False)
        state.authorize(release_59, rollback=True)
        with pytest.raises(DeploymentStateError, match="does not match"):
            state.authorize(release_58, rollback=True)
        with pytest.raises(DeploymentStateError, match="does not match"):
            state.authorize(release_61, rollback=True)
        state.authorize(release_61, rollback=False)


@pytest.mark.parametrize(
    ("schema", "operation"),
    [
        ("gram_scope_deployment_receipt_v1", None),
        ("gram_scope_deployment_receipt_v2", "deployment"),
        ("gram_scope_deployment_receipt_v3", "deployment"),
    ],
)
def test_legacy_receipt_is_accepted_and_upgraded_after_success(
    tmp_path,
    schema,
    operation,
):
    directory = tmp_path / "state"
    directory.mkdir(mode=0o700)
    legacy_release = _identity("v0.60.0", "a")
    legacy: dict[str, object] = {
        "schema": schema,
        "status": "active",
        "completed_at": "2026-08-08T01:02:03Z",
        "release": {
            "tag": legacy_release.tag,
            "source_commit": legacy_release.source_commit,
            "manifest_sha256": legacy_release.manifest_sha256,
        },
        "previous_release": None,
    }
    if operation is not None:
        legacy["operation"] = operation
    if schema == "gram_scope_deployment_receipt_v3":
        legacy["attempt_id"] = "1" * 32
    receipt_path = directory / DEPLOYMENT_RECEIPT
    receipt_path.write_text(json.dumps(legacy) + "\n", encoding="utf-8")
    receipt_path.chmod(0o600)

    with locked_deployment_state(directory) as state:
        assert state.current_receipt() == legacy
        next_release = _identity("v0.61.0", "b")
        state.authorize(next_release, rollback=False)
        state.record_success(next_release)
        upgraded = state.current_receipt()

    assert upgraded["schema"] == "gram_scope_deployment_receipt_v4"
    assert upgraded["operation"] == "deployment"
    assert len(upgraded["attempt_id"]) == 32
    assert upgraded["previous_release"] == legacy["release"]
    assert upgraded["ledger_sequence"] == 1
    event = json.loads(_event_files(directory)[0].read_text(encoding="utf-8"))
    assert event["base_release"] == legacy["release"]


def test_attempt_journal_blocks_other_work_and_resumes_exact_identity(tmp_path):
    directory = tmp_path / "state"
    base = _identity("v0.60.0", "a")
    target = _identity("v0.61.0", "b")
    started = datetime(2026, 8, 8, 3, 4, 5, tzinfo=timezone.utc)

    with locked_deployment_state(directory) as state:
        state.record_success(base)
        attempt = state.prepare_attempt(
            target,
            rollback=False,
            resume=False,
            started_at=started,
        )
        pending = state.current_attempt()
        assert pending == {
            "schema": "gram_scope_deployment_attempt_v2",
            "status": "pending",
            "operation": "deployment",
            "attempt_id": attempt.attempt_id,
            "started_at": "2026-08-08T03:04:05Z",
            "base_release": {
                "tag": base.tag,
                "source_commit": base.source_commit,
                "manifest_sha256": base.manifest_sha256,
            },
            "target_release": {
                "tag": target.tag,
                "source_commit": target.source_commit,
                "manifest_sha256": target.manifest_sha256,
            },
            "rollout_phase": "prepared",
        }
        assert state.attempt_path.stat().st_mode & 0o777 == 0o600

        with pytest.raises(DeploymentStateError, match="--resume"):
            state.prepare_attempt(target, rollback=False, resume=False)
        with pytest.raises(DeploymentStateError, match="does not match"):
            state.prepare_attempt(
                _identity("v0.62.0", "c"),
                rollback=False,
                resume=True,
            )
        with pytest.raises(DeploymentStateError, match="does not match"):
            state.prepare_attempt(target, rollback=True, resume=True)

        resumed = state.prepare_attempt(target, rollback=False, resume=True)
        assert resumed == attempt
        state.complete_attempt(target, resumed)
        receipt = state.current_receipt()
        assert state.current_attempt() is None

    assert receipt["schema"] == "gram_scope_deployment_receipt_v4"
    assert receipt["attempt_id"] == attempt.attempt_id
    assert receipt["ledger_sequence"] == 2
    assert not (directory / DEPLOYMENT_ATTEMPT).exists()


def test_initial_bootstrap_checkpoint_is_durable_and_scoped_to_initial_attempt(
    tmp_path,
):
    directory = tmp_path / "state"
    target = _identity("v0.69.0", "b")

    with locked_deployment_state(directory) as state:
        attempt = state.prepare_attempt(target, rollback=False, resume=False)
        assert attempt.initial_deployment is True
        assert attempt.rollout_phase == "prepared"
        state.mark_initial_bootstrap_verified(target, attempt)
        checkpointed = state.current_attempt()
        assert checkpointed["schema"] == "gram_scope_deployment_attempt_v2"
        assert checkpointed["rollout_phase"] == "initial_bootstrap_verified"

    with locked_deployment_state(directory) as state:
        resumed = state.prepare_attempt(target, rollback=False, resume=True)
        assert resumed.attempt_id == attempt.attempt_id
        assert resumed.initial_deployment is True
        assert resumed.rollout_phase == "initial_bootstrap_verified"

    upgrade_directory = tmp_path / "upgrade-state"
    with locked_deployment_state(upgrade_directory) as state:
        state.record_success(_identity("v0.68.0", "a"))
        upgrade = state.prepare_attempt(target, rollback=False, resume=False)
        with pytest.raises(DeploymentStateError, match="initial deployment"):
            state.mark_initial_bootstrap_verified(target, upgrade)


def test_resume_reconciles_receipt_committed_before_journal_clear(tmp_path):
    directory = tmp_path / "state"
    target = _identity("v0.61.0", "b")
    with locked_deployment_state(directory) as state:
        attempt = state.prepare_attempt(target, rollback=False, resume=False)
        state.record_success(
            target,
            operation=attempt.operation,
            attempt_id=attempt.attempt_id,
        )

    with locked_deployment_state(directory) as state:
        resumed = state.prepare_attempt(target, rollback=False, resume=True)
        assert resumed.already_completed is True
        assert resumed.attempt_id == attempt.attempt_id
        assert state.current_attempt() is None
        assert state.current_receipt()["attempt_id"] == attempt.attempt_id


def test_resume_reconciles_legacy_v3_receipt_with_stale_journal(tmp_path):
    directory = tmp_path / "state"
    directory.mkdir(mode=0o700)
    base = _identity("v0.60.0", "a")
    target = _identity("v0.61.0", "b")
    attempt_id = "2" * 32
    base_payload = {
        "tag": base.tag,
        "source_commit": base.source_commit,
        "manifest_sha256": base.manifest_sha256,
    }
    target_payload = {
        "tag": target.tag,
        "source_commit": target.source_commit,
        "manifest_sha256": target.manifest_sha256,
    }
    receipt = {
        "schema": "gram_scope_deployment_receipt_v3",
        "status": "active",
        "operation": "deployment",
        "attempt_id": attempt_id,
        "completed_at": "2026-08-08T03:05:06Z",
        "release": target_payload,
        "previous_release": base_payload,
    }
    pending = {
        "schema": "gram_scope_deployment_attempt_v1",
        "status": "pending",
        "operation": "deployment",
        "attempt_id": attempt_id,
        "started_at": "2026-08-08T03:04:05Z",
        "base_release": base_payload,
        "target_release": target_payload,
    }
    for name, payload in (
        (DEPLOYMENT_RECEIPT, receipt),
        (DEPLOYMENT_ATTEMPT, pending),
    ):
        path = directory / name
        path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
        path.chmod(0o600)

    with locked_deployment_state(directory) as state:
        resumed = state.prepare_attempt(target, rollback=False, resume=True)
        assert resumed.already_completed is True
        assert state.current_attempt() is None
        assert state.current_receipt() == receipt
        assert state.current_ledger_event() is None


def test_resume_reconciles_ledger_event_committed_before_receipt(
    tmp_path,
    monkeypatch,
):
    directory = tmp_path / "state"
    base = _identity("v0.60.0", "a")
    target = _identity("v0.61.0", "b")
    with locked_deployment_state(directory) as state:
        state.record_success(base, attempt_id="1" * 32)
        attempt = state.prepare_attempt(target, rollback=False, resume=False)

        def fail_receipt(*_args, **_kwargs):
            raise DeploymentStateError("simulated receipt interruption")

        monkeypatch.setattr("ops.deployment_state._write_atomic_receipt", fail_receipt)
        with pytest.raises(DeploymentStateError, match="interruption"):
            state.complete_attempt(target, attempt)
        assert len(_event_files(directory)) == 2
        assert state.current_receipt()["release"]["tag"] == "v0.60.0"
        assert state.current_attempt()["attempt_id"] == attempt.attempt_id

    monkeypatch.undo()
    with locked_deployment_state(directory) as state:
        resumed = state.prepare_attempt(target, rollback=False, resume=True)
        receipt = state.current_receipt()
        assert resumed.already_completed is True
        assert receipt["schema"] == "gram_scope_deployment_receipt_v4"
        assert receipt["attempt_id"] == attempt.attempt_id
        assert receipt["ledger_sequence"] == 2
        assert state.current_attempt() is None


def test_state_rejects_tampered_or_missing_ledger_event(tmp_path):
    directory = tmp_path / "state"
    with locked_deployment_state(directory) as state:
        state.record_success(_identity("v0.60.0", "a"))
        state.record_success(_identity("v0.61.0", "b"))

    first_event, _second_event = _event_files(directory)
    original = first_event.read_text(encoding="utf-8")
    first_event.write_text(original.replace("v0.60.0", "v0.50.0"), encoding="utf-8")
    with pytest.raises(DeploymentStateError, match="digest"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")

    first_event.write_text(original, encoding="utf-8")
    first_event.unlink()
    with pytest.raises(DeploymentStateError, match="sequence"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")


def test_state_rejects_rehashed_event_that_breaks_digest_chain(tmp_path):
    directory = tmp_path / "state"
    with locked_deployment_state(directory) as state:
        state.record_success(_identity("v0.60.0", "a"))
        state.record_success(_identity("v0.61.0", "b"))

    first_event, _second_event = _event_files(directory)
    payload = json.loads(first_event.read_text(encoding="utf-8"))
    payload["completed_at"] = "2026-08-08T00:00:00Z"
    raw = (
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("ascii")
    digest = hashlib.sha256(raw).hexdigest()
    rewritten = first_event.with_name(f"{1:020d}-{digest}.json")
    first_event.write_bytes(raw)
    first_event.rename(rewritten)

    with pytest.raises(DeploymentStateError, match="chain"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")


def test_state_rejects_receipt_not_bound_to_ledger_head(tmp_path):
    directory = tmp_path / "state"
    with locked_deployment_state(directory) as state:
        state.record_success(_identity("v0.60.0", "a"))

    receipt_path = directory / DEPLOYMENT_RECEIPT
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    receipt["ledger_event_sha256"] = "f" * 64
    receipt_path.write_text(json.dumps(receipt) + "\n", encoding="utf-8")
    with pytest.raises(DeploymentStateError, match="not bound"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")


def test_state_rejects_public_or_symlinked_ledger_directory(tmp_path):
    public_state = tmp_path / "public-state"
    public_state.mkdir(mode=0o700)
    public_ledger = public_state / DEPLOYMENT_LEDGER
    public_ledger.mkdir(mode=0o755)
    with pytest.raises(DeploymentStateError, match="private and owned"):
        with locked_deployment_state(public_state):
            raise AssertionError("unreachable")

    linked_state = tmp_path / "linked-state"
    linked_state.mkdir(mode=0o700)
    target = tmp_path / "events"
    target.mkdir(mode=0o700)
    (linked_state / DEPLOYMENT_LEDGER).symlink_to(target, target_is_directory=True)
    with pytest.raises(DeploymentStateError, match="private and owned"):
        with locked_deployment_state(linked_state):
            raise AssertionError("unreachable")


def test_second_deployment_lock_fails_immediately(tmp_path):
    directory = tmp_path / "state"
    with locked_deployment_state(directory):
        with pytest.raises(
            DeploymentStateError,
            match="another deployment is already in progress",
        ):
            with locked_deployment_state(directory):
                raise AssertionError("unreachable")

    with locked_deployment_state(directory) as state:
        assert state.current_receipt() is None


def test_state_rejects_relative_public_and_symlinked_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(DeploymentStateError, match="must be absolute"):
        with locked_deployment_state(Path("state")):
            raise AssertionError("unreachable")

    public = tmp_path / "public"
    public.mkdir(mode=0o755)
    with pytest.raises(DeploymentStateError, match="private and owned"):
        with locked_deployment_state(public):
            raise AssertionError("unreachable")

    real = tmp_path / "real"
    real.mkdir(mode=0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)
    with pytest.raises(DeploymentStateError, match="private and owned"):
        with locked_deployment_state(linked):
            raise AssertionError("unreachable")


def test_state_rejects_corrupt_or_non_private_receipt_before_use(tmp_path):
    directory = tmp_path / "state"
    directory.mkdir(mode=0o700)
    receipt = directory / DEPLOYMENT_RECEIPT
    receipt.write_text('{"status":"tampered"}\n', encoding="utf-8")
    receipt.chmod(0o600)
    with pytest.raises(DeploymentStateError, match="contract"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")

    receipt.write_text(json.dumps({"ignored": True}), encoding="utf-8")
    receipt.chmod(0o644)
    with pytest.raises(DeploymentStateError, match="private file"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")

    receipt.unlink()
    target = tmp_path / "target.json"
    target.write_text("{}", encoding="utf-8")
    receipt.symlink_to(target)
    with pytest.raises(DeploymentStateError, match="unavailable"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")


def test_state_rejects_corrupt_or_symlinked_attempt_before_use(tmp_path):
    directory = tmp_path / "state"
    directory.mkdir(mode=0o700)
    attempt = directory / DEPLOYMENT_ATTEMPT
    attempt.write_text('{"status":"tampered"}\n', encoding="utf-8")
    attempt.chmod(0o600)
    with pytest.raises(DeploymentStateError, match="attempt contract"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")

    attempt.unlink()
    target = tmp_path / "attempt.json"
    target.write_text("{}", encoding="utf-8")
    attempt.symlink_to(target)
    with pytest.raises(DeploymentStateError, match="attempt is unavailable"):
        with locked_deployment_state(directory):
            raise AssertionError("unreachable")


def test_state_rejects_invalid_identity_and_naive_completion_time(tmp_path):
    directory = tmp_path / "state"
    with locked_deployment_state(directory) as state:
        with pytest.raises(DeploymentStateError, match="identity"):
            state.record_success(
                DeploymentIdentity(
                    tag="latest",
                    source_commit="a" * 40,
                    manifest_sha256="b" * 64,
                )
            )
        with pytest.raises(DeploymentStateError, match="timezone-aware"):
            state.record_success(
                _identity(),
                completed_at=datetime(2026, 8, 8, 1, 2, 3),
            )
        with pytest.raises(DeploymentStateError, match="operation"):
            state.record_success(_identity(), operation="automatic")
        with pytest.raises(DeploymentStateError, match="operation"):
            state.record_success(_identity(), operation=[])
        for invalid_attempt_id in ("", "invalid", 1):
            with pytest.raises(DeploymentStateError, match="attempt id"):
                state.record_success(
                    _identity(),
                    attempt_id=invalid_attempt_id,
                )
        with pytest.raises(DeploymentStateError, match="start time"):
            state.prepare_attempt(
                _identity(),
                rollback=False,
                resume=False,
                started_at=datetime(2026, 8, 8, 1, 2, 3),
            )
        assert state.current_receipt() is None

    assert not any(path.name.endswith(".tmp") for path in directory.iterdir())
