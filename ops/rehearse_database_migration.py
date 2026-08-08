"""Rehearse target-image database migrations on one verified backup copy."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import stat
import sys
import tempfile
from typing import Callable

from sqlalchemy.engine import Engine

_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

try:
    from .backup_sqlite import verify_backup
    from .restore_sqlite import restore_from_heartbeat
except ImportError:  # pragma: no cover - direct script execution in the image
    from backup_sqlite import verify_backup
    from restore_sqlite import restore_from_heartbeat

from database import create_database_engine
from services.database_migrations import MigrationReport, run_database_migrations


@dataclass(frozen=True)
class MigrationRehearsalResult:
    source_revision: str
    target_revision: str
    action: str
    applied_revisions: tuple[str, ...]


MigrationRunner = Callable[[Engine], MigrationReport]


def rehearse_database_migration(
    heartbeat: Path,
    *,
    workspace: Path,
    migration_runner: MigrationRunner | None = None,
) -> MigrationRehearsalResult:
    """Restore, migrate, validate, and discard a private database copy."""
    try:
        metadata = workspace.lstat()
    except OSError as exc:
        raise RuntimeError("Migration rehearsal workspace is unavailable.") from exc
    if not stat.S_ISDIR(metadata.st_mode) or workspace.is_symlink():
        raise RuntimeError("Migration rehearsal workspace must be a directory.")

    migrate = migration_runner or run_database_migrations
    with tempfile.TemporaryDirectory(
        prefix="gram-scope-migration-rehearsal-",
        dir=workspace,
    ) as private_workspace:
        restored_path = Path(private_workspace) / "rehearsal.sqlite3"
        restored = restore_from_heartbeat(heartbeat, restored_path)
        engine = create_database_engine(f"sqlite:///{restored_path}")
        try:
            report = migrate(engine)
        finally:
            engine.dispose()

        target_revision = verify_backup(restored_path)
        if report.revision_before != restored.schema_revision:
            raise RuntimeError(
                "Migration rehearsal source revision changed unexpectedly."
            )
        if report.revision_after != target_revision:
            raise RuntimeError(
                "Migration rehearsal target revision is inconsistent."
            )
        return MigrationRehearsalResult(
            source_revision=restored.schema_revision,
            target_revision=target_revision,
            action=report.action,
            applied_revisions=report.applied_revisions,
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Rehearse the target backend migration against a verified backup copy."
        )
    )
    parser.add_argument("--heartbeat", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, default=Path("/tmp"))
    args = parser.parse_args()
    try:
        result = rehearse_database_migration(
            args.heartbeat,
            workspace=args.workspace,
        )
    except Exception:  # noqa: BLE001 - CLI must not expose database diagnostics.
        print("database migration rehearsal failed", file=sys.stderr)
        raise SystemExit(2) from None
    print(
        "database migration rehearsal passed "
        f"from={result.source_revision} to={result.target_revision} "
        f"action={result.action} applied={len(result.applied_revisions)}",
        flush=True,
    )


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    main()
