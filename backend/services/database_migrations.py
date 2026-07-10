"""Fail-closed database migration bootstrap for fresh and legacy databases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RangeNotAncestorError, ResolutionError
from alembic.util.exc import CommandError
from sqlalchemy import Engine, inspect, text
from sqlalchemy.engine import Connection

from migrations.legacy_baseline import (
    BASELINE_REVISION,
    DOMAIN_TABLES,
    validate_legacy_schema,
)

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_ALEMBIC_INI = _BACKEND_ROOT / "alembic.ini"
_SCRIPT_LOCATION = _BACKEND_ROOT / "migrations"

MigrationAction = Literal[
    "created",
    "adopted_legacy",
    "upgraded",
    "already_current",
]


class MigrationBootstrapError(RuntimeError):
    """Raised when schema state cannot be upgraded without guessing."""


@dataclass(frozen=True)
class MigrationReport:
    action: MigrationAction
    revision_before: str | None
    revision_after: str
    applied_revisions: tuple[str, ...]


def _config(connection: Connection) -> Config:
    config = Config(str(_ALEMBIC_INI))
    config.set_main_option("script_location", str(_SCRIPT_LOCATION))
    config.set_main_option(
        "sqlalchemy.url",
        str(connection.engine.url).replace("%", "%%"),
    )
    config.attributes["connection"] = connection
    return config


def _script_directory(config: Config) -> ScriptDirectory:
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    if len(heads) != 1:
        raise MigrationBootstrapError(
            f"Expected exactly one migration head, found {sorted(heads)}."
        )
    return script


def _database_heads(connection: Connection) -> tuple[str, ...]:
    return tuple(MigrationContext.configure(connection).get_current_heads())


def _assert_known_revision(script: ScriptDirectory, revision: str) -> None:
    try:
        resolved = script.get_revision(revision)
    except (CommandError, ResolutionError) as exc:
        raise MigrationBootstrapError(
            f"Database revision {revision!r} is unknown to this application."
        ) from exc
    if resolved is None:
        raise MigrationBootstrapError(
            f"Database revision {revision!r} is unknown to this application."
        )


def _pending_revisions(
    script: ScriptDirectory,
    current_revision: str | None,
) -> tuple[str, ...]:
    head = script.get_current_head()
    if head is None:
        raise MigrationBootstrapError("Migration history has no current head.")
    lower = current_revision or "base"
    try:
        revisions = list(script.iterate_revisions(head, lower))
    except (CommandError, RangeNotAncestorError, ResolutionError) as exc:
        raise MigrationBootstrapError(
            f"Database revision {current_revision!r} is not an ancestor of head {head!r}."
        ) from exc
    return tuple(revision.revision for revision in reversed(revisions))


def _sqlite_integrity_errors(connection: Connection) -> list[str]:
    if connection.dialect.name != "sqlite":
        return []
    errors: list[str] = []
    integrity_rows = connection.execute(text("PRAGMA integrity_check")).scalars().all()
    if integrity_rows != ["ok"]:
        errors.append(f"SQLite integrity_check failed: {integrity_rows}")
    foreign_key_rows = connection.execute(text("PRAGMA foreign_key_check")).all()
    if foreign_key_rows:
        errors.append(
            f"SQLite foreign_key_check found {len(foreign_key_rows)} violation(s)."
        )
    return errors


def _assert_legacy_compatible(connection: Connection) -> None:
    errors = _sqlite_integrity_errors(connection)
    errors.extend(validate_legacy_schema(connection))
    if errors:
        details = "; ".join(errors[:20])
        if len(errors) > 20:
            details = f"{details}; and {len(errors) - 20} more mismatch(es)"
        raise MigrationBootstrapError(
            "Unversioned database does not match the frozen v0.22.0 baseline: "
            f"{details}"
        )


def _assert_current_schema(connection: Connection) -> None:
    """Validate the current release schema after migration.

    v0.22.1 introduces the baseline and intentionally makes no model changes,
    so the frozen v0.22.0 manifest is also the current release manifest. A
    later schema-changing revision must update this check with its own current
    manifest while leaving the legacy baseline immutable.
    """
    errors = _sqlite_integrity_errors(connection)
    errors.extend(validate_legacy_schema(connection))
    if errors:
        details = "; ".join(errors[:20])
        raise MigrationBootstrapError(
            f"Migrated database does not match the v0.22.1 schema: {details}"
        )


def run_database_migrations(target_engine: Engine) -> MigrationReport:
    """Upgrade one database safely and return the observed migration action.

    Fresh databases are built by Alembic. Exact legacy v0.22.0 databases are
    stamped at the immutable baseline before upgrading. Unknown, partial, or
    future schema states fail closed instead of being guessed or repaired.
    """
    if target_engine.dialect.name != "sqlite":
        raise MigrationBootstrapError(
            "v0.22.1 migration startup currently supports SQLite databases only."
        )
    with target_engine.begin() as connection:
        config = _config(connection)
        script = _script_directory(config)
        head = script.get_current_head()
        if head is None:
            raise MigrationBootstrapError("Migration history has no current head.")

        table_names = set(inspect(connection).get_table_names())
        domain_tables_present = table_names & DOMAIN_TABLES
        database_heads = _database_heads(connection)
        if len(database_heads) > 1:
            raise MigrationBootstrapError(
                f"Multiple database migration heads are unsupported: {database_heads}."
            )

        revision_before = database_heads[0] if database_heads else None
        if revision_before is not None:
            _assert_known_revision(script, revision_before)
            pending = _pending_revisions(script, revision_before)
            if pending:
                command.upgrade(config, "head")
                action: MigrationAction = "upgraded"
            else:
                action = "already_current"
        elif not domain_tables_present:
            pending = _pending_revisions(script, None)
            command.upgrade(config, "head")
            action = "created"
        else:
            if domain_tables_present != DOMAIN_TABLES:
                missing = sorted(DOMAIN_TABLES - domain_tables_present)
                present = sorted(domain_tables_present)
                raise MigrationBootstrapError(
                    "Unversioned database contains a partial application schema; "
                    f"present={present}, missing={missing}."
                )
            _assert_legacy_compatible(connection)
            command.stamp(config, BASELINE_REVISION)
            pending = _pending_revisions(script, BASELINE_REVISION)
            if pending:
                command.upgrade(config, "head")
            action = "adopted_legacy"

        revision_after_heads = _database_heads(connection)
        if revision_after_heads != (head,):
            raise MigrationBootstrapError(
                "Migration did not reach the expected head: "
                f"database={revision_after_heads}, expected={(head,)}."
            )
        _assert_current_schema(connection)
        return MigrationReport(
            action=action,
            revision_before=revision_before,
            revision_after=head,
            applied_revisions=pending,
        )


def main() -> None:
    """Run the same safe bootstrap used by application startup."""
    from database import engine

    report = run_database_migrations(engine)
    print(
        "Database migration complete: "
        f"action={report.action}, revision={report.revision_after}"
    )


if __name__ == "__main__":
    main()
