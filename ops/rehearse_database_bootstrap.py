"""Gate and rehearse the database path for a first production deployment."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from sqlalchemy.engine import Engine

_BACKEND_ROOT = Path(__file__).resolve().parents[1] / "backend"
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

try:
    from .backup_sqlite import (
        BACKUP_HEALTH_RECORD,
        create_backup,
        verify_backup,
    )
    from .rehearse_database_migration import rehearse_database_migration
except ImportError:  # pragma: no cover - direct script execution in the image
    from backup_sqlite import BACKUP_HEALTH_RECORD, create_backup, verify_backup
    from rehearse_database_migration import rehearse_database_migration

from database import create_database_engine
from services.database_migrations import MigrationReport, run_database_migrations


_DATABASE_NAME = "ton_check.db"
_SQLITE_SIDECARS = {
    _DATABASE_NAME + "-journal",
    _DATABASE_NAME + "-shm",
    _DATABASE_NAME + "-wal",
}
_MAX_DATA_ENTRIES = 8
_MAX_BACKUP_ENTRIES = 367
_BACKUP_NAME = re.compile(
    r"^ton-check-[0-9]{8}T[0-9]{6}(?:[0-9]{6})?Z\.sqlite3$"
)


@dataclass(frozen=True)
class DatabaseBootstrapResult:
    source: str
    source_revision: str | None
    target_revision: str
    migration_action: str
    applied_revisions: tuple[str, ...]


def rehearse_database_bootstrap(
    *,
    mode: str,
    data_directory: Path,
    backup_directory: Path,
    workspace: Path,
    retention: int,
) -> DatabaseBootstrapResult:
    """Prove an empty first install or safely recover its verified checkpoint."""
    if mode not in {"fresh", "resume"}:
        raise ValueError("Database bootstrap mode is invalid.")
    if (
        not isinstance(retention, int)
        or isinstance(retention, bool)
        or retention < 1
        or retention > 365
    ):
        raise ValueError("Database backup retention is invalid.")
    _require_directory(workspace, "workspace")
    _require_directory(backup_directory, "backup directory")
    data_entries = _directory_entries(
        data_directory,
        label="database volume",
        maximum_entries=_MAX_DATA_ENTRIES,
    )
    backup_entries = _backup_entries(backup_directory)
    if mode == "fresh" and (data_entries or backup_entries):
        raise RuntimeError("Initial database or backup volume is not empty.")
    if not data_entries:
        if backup_entries:
            raise RuntimeError(
                "Checkpointed backup exists without its database."
            )
        return _rehearse_fresh_database(workspace)
    if mode != "resume":
        raise RuntimeError("Initial database or backup volume is not empty.")

    database = data_directory / _DATABASE_NAME
    if _DATABASE_NAME not in data_entries:
        raise RuntimeError("Checkpointed database is unavailable.")
    unexpected = data_entries - {_DATABASE_NAME} - _SQLITE_SIDECARS
    if unexpected:
        raise RuntimeError("Checkpointed database volume has unexpected entries.")
    _require_regular_file(database, "checkpointed database")
    for sidecar_name in data_entries & _SQLITE_SIDECARS:
        _require_regular_file(data_directory / sidecar_name, "SQLite sidecar")
    _verify_retained_backups(backup_directory, backup_entries)

    backup = create_backup(database, backup_directory, retention)
    migration = rehearse_database_migration(
        backup.parent / BACKUP_HEALTH_RECORD,
        workspace=workspace,
    )
    return DatabaseBootstrapResult(
        source="checkpointed",
        source_revision=migration.source_revision,
        target_revision=migration.target_revision,
        migration_action=migration.action,
        applied_revisions=migration.applied_revisions,
    )


def _rehearse_fresh_database(workspace: Path) -> DatabaseBootstrapResult:
    with tempfile.TemporaryDirectory(
        prefix="gram-scope-database-bootstrap-",
        dir=workspace,
    ) as private_workspace:
        database = Path(private_workspace) / "bootstrap.sqlite3"
        engine: Engine = create_database_engine(f"sqlite:///{database}")
        try:
            report: MigrationReport = run_database_migrations(engine)
        finally:
            engine.dispose()
        target_revision = verify_backup(database)
        if report.revision_before is not None:
            raise RuntimeError("Fresh database unexpectedly had a schema revision.")
        if report.revision_after != target_revision:
            raise RuntimeError("Fresh database target revision is inconsistent.")
        return DatabaseBootstrapResult(
            source="empty",
            source_revision=None,
            target_revision=target_revision,
            migration_action=report.action,
            applied_revisions=report.applied_revisions,
        )


def _backup_entries(directory: Path) -> set[str]:
    entries = _directory_entries(
        directory,
        label="backup volume",
        maximum_entries=_MAX_BACKUP_ENTRIES,
    )
    for name in entries:
        if name != BACKUP_HEALTH_RECORD and _BACKUP_NAME.fullmatch(name) is None:
            raise RuntimeError("Checkpointed backup volume has unexpected entries.")
        _require_regular_file(directory / name, "backup volume entry")
    retained = {name for name in entries if _BACKUP_NAME.fullmatch(name)}
    if BACKUP_HEALTH_RECORD in entries and not retained:
        raise RuntimeError("Checkpointed backup heartbeat has no retained backup.")
    return entries


def _verify_retained_backups(directory: Path, entries: set[str]) -> None:
    for name in sorted(entries):
        if _BACKUP_NAME.fullmatch(name) is not None:
            verify_backup(directory / name)


def _directory_entries(
    directory: Path,
    *,
    label: str,
    maximum_entries: int,
) -> set[str]:
    _require_directory(directory, label)
    try:
        with os.scandir(directory) as scan:
            entries = []
            for entry in scan:
                entries.append(entry.name)
                if len(entries) > maximum_entries:
                    raise RuntimeError(
                        f"Database bootstrap {label} has too many entries."
                    )
    except OSError as exc:
        raise RuntimeError(
            f"Database bootstrap {label} cannot be inspected."
        ) from exc
    if any(not name or name in {".", ".."} for name in entries):
        raise RuntimeError(f"Database bootstrap {label} entry is invalid.")
    return set(entries)


def _require_directory(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"Database bootstrap {label} is unavailable.") from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise RuntimeError(f"Database bootstrap {label} must be a directory.")


def _require_regular_file(path: Path, label: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise RuntimeError(f"Database bootstrap {label} is unavailable.") from exc
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1:
        raise RuntimeError(f"Database bootstrap {label} must be a regular file.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rehearse a fail-closed first-deployment database bootstrap."
    )
    parser.add_argument("--mode", choices=("fresh", "resume"), required=True)
    parser.add_argument("--data-directory", type=Path, default=Path("/data"))
    parser.add_argument("--backup-directory", type=Path, default=Path("/backups"))
    parser.add_argument("--workspace", type=Path, default=Path("/tmp"))
    parser.add_argument("--retention", type=int)
    args = parser.parse_args()
    try:
        retention = (
            int(os.environ.get("BACKUP_RETENTION", "14"))
            if args.retention is None
            else args.retention
        )
        result = rehearse_database_bootstrap(
            mode=args.mode,
            data_directory=args.data_directory,
            backup_directory=args.backup_directory,
            workspace=args.workspace,
            retention=retention,
        )
    except Exception:  # noqa: BLE001 - CLI must not expose database diagnostics.
        print("database bootstrap rehearsal failed", file=sys.stderr)
        raise SystemExit(2) from None
    print(
        "database bootstrap rehearsal passed "
        f"source={result.source} target={result.target_revision} "
        f"action={result.migration_action} "
        f"applied={len(result.applied_revisions)}",
        flush=True,
    )


if __name__ == "__main__":  # pragma: no cover - CLI boundary
    main()
