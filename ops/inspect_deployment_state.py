"""Audit GRAM Scope deployment state without changing deployment records."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
import json
from pathlib import Path
import sys
from typing import TextIO

try:
    from .deployment_state import (
        DeploymentStateBusyError,
        DeploymentStateError,
        locked_deployment_state,
    )
except ImportError:  # pragma: no cover - direct script execution
    from deployment_state import (
        DeploymentStateBusyError,
        DeploymentStateError,
        locked_deployment_state,
    )


EXIT_VALID = 0
EXIT_INTERRUPTED = 2
EXIT_INVALID = 3
EXIT_BUSY = 4
EXIT_USAGE = 64
_ERROR_SCHEMA = "gram_scope_deployment_audit_error_v1"


class _UsageError(ValueError):
    pass


class _AuditArgumentParser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def inspect_deployment_state(state_directory: Path) -> dict[str, object]:
    """Return one verified audit report while holding the deployment lock."""
    with locked_deployment_state(state_directory) as state:
        return state.audit_report()


def main(argv: Sequence[str] | None = None) -> int:
    parser = _AuditArgumentParser(
        description=(
            "Validate the deployment receipt, pending journal, and complete "
            "hash-chained event ledger without reconciling or changing them."
        )
    )
    parser.add_argument("--state-directory", type=Path, required=True)
    try:
        args = parser.parse_args(argv)
    except _UsageError:
        _write_json(
            sys.stderr,
            {
                "schema": _ERROR_SCHEMA,
                "status": "usage",
                "message": "deployment audit arguments are invalid",
            },
        )
        return EXIT_USAGE
    try:
        report = inspect_deployment_state(args.state_directory)
    except DeploymentStateBusyError:
        _write_json(
            sys.stderr,
            {
                "schema": _ERROR_SCHEMA,
                "status": "busy",
                "message": "another deployment is already in progress",
            },
        )
        return EXIT_BUSY
    except DeploymentStateError:
        _write_json(
            sys.stderr,
            {
                "schema": _ERROR_SCHEMA,
                "status": "invalid",
                "message": "deployment state validation failed",
            },
        )
        return EXIT_INVALID
    _write_json(sys.stdout, report)
    if report["status"] == "interrupted":
        return EXIT_INTERRUPTED
    return EXIT_VALID


def _write_json(stream: TextIO, payload: dict[str, object]) -> None:
    stream.write(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    )


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    raise SystemExit(main())
