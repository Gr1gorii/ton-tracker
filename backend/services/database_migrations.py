"""Fail-closed database migration bootstrap for fresh and legacy databases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic.script.revision import RangeNotAncestorError, ResolutionError
from alembic.util.exc import CommandError
from sqlalchemy import CheckConstraint, Engine, UniqueConstraint, inspect, text
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


def _type_signature(value: Any) -> str:
    return "".join(str(value).upper().split())


def _default_signature(value: Any) -> str | None:
    if value is None:
        return None
    return "".join(str(value).split())


def _metadata_default_signature(column) -> str | None:
    if column.server_default is None:
        return None
    argument = column.server_default.arg
    if isinstance(argument, str):
        # SQLAlchemy quotes string-valued server defaults when it emits DDL.
        return _default_signature(repr(argument))
    return _default_signature(argument.compile(compile_kwargs={"literal_binds": True}))


def _options_signature(options: dict[str, Any] | None) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted((str(key), str(value)) for key, value in (options or {}).items())
    )


def _metadata_fk_options(constraint) -> tuple[tuple[str, str], ...]:
    options = {
        "onupdate": constraint.onupdate,
        "ondelete": constraint.ondelete,
        "deferrable": constraint.deferrable,
        "initially": constraint.initially,
        "match": constraint.match,
    }
    return _options_signature(
        {key: value for key, value in options.items() if value is not None}
    )


def _check_text_signature(value: Any) -> str:
    return " ".join(str(value).split())


def _assert_current_schema(connection: Connection) -> None:
    """Validate migrated domain tables against current SQLAlchemy metadata."""
    import models as _models  # noqa: F401 - register every mapped table.
    from database import Base

    errors = _sqlite_integrity_errors(connection)
    schema_inspector = inspect(connection)
    actual_tables = set(schema_inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    missing_tables = sorted(expected_tables - actual_tables)
    if missing_tables:
        errors.append(f"Missing current domain tables: {missing_tables}")

    for table_name in sorted(expected_tables & actual_tables):
        table = Base.metadata.tables[table_name]
        expected_columns = tuple(
            (
                column.name,
                _type_signature(column.type),
                bool(column.nullable),
                _metadata_default_signature(column),
            )
            for column in table.columns
        )
        actual_columns = tuple(
            (
                column["name"],
                _type_signature(column["type"]),
                bool(column["nullable"]),
                _default_signature(column.get("default")),
            )
            for column in schema_inspector.get_columns(table_name)
        )
        if actual_columns != expected_columns:
            errors.append(
                f"{table_name}: current columns differ; "
                f"expected={expected_columns}, actual={actual_columns}"
            )

        expected_pk = tuple(column.name for column in table.primary_key.columns)
        actual_pk = tuple(
            schema_inspector.get_pk_constraint(table_name).get(
                "constrained_columns"
            )
            or ()
        )
        if actual_pk != expected_pk:
            errors.append(
                f"{table_name}: current primary key differs; "
                f"expected={expected_pk}, actual={actual_pk}"
            )

        expected_indexes = {
            (
                index.name,
                tuple(column.name for column in index.columns),
                bool(index.unique),
            )
            for index in table.indexes
        }
        actual_indexes = {
            (
                index["name"],
                tuple(index.get("column_names") or ()),
                bool(index.get("unique")),
            )
            for index in schema_inspector.get_indexes(table_name)
        }
        if actual_indexes != expected_indexes:
            errors.append(
                f"{table_name}: current indexes differ; "
                f"expected={sorted(expected_indexes)}, "
                f"actual={sorted(actual_indexes)}"
            )

        expected_fks = {
            (
                tuple(element.parent.name for element in constraint.elements),
                constraint.elements[0].column.table.schema,
                constraint.elements[0].column.table.name,
                tuple(element.column.name for element in constraint.elements),
                _metadata_fk_options(constraint),
            )
            for constraint in table.foreign_key_constraints
        }
        actual_fks = {
            (
                tuple(foreign_key.get("constrained_columns") or ()),
                foreign_key.get("referred_schema"),
                foreign_key.get("referred_table"),
                tuple(foreign_key.get("referred_columns") or ()),
                _options_signature(foreign_key.get("options")),
            )
            for foreign_key in schema_inspector.get_foreign_keys(table_name)
        }
        if actual_fks != expected_fks:
            errors.append(
                f"{table_name}: current foreign keys differ; "
                f"expected={sorted(expected_fks)}, actual={sorted(actual_fks)}"
            )

        expected_uniques = {
            (
                constraint.name,
                tuple(column.name for column in constraint.columns),
            )
            for constraint in table.constraints
            if isinstance(constraint, UniqueConstraint)
        }
        actual_uniques = {
            (
                unique.get("name"),
                tuple(unique.get("column_names") or ()),
            )
            for unique in schema_inspector.get_unique_constraints(table_name)
        }
        if actual_uniques != expected_uniques:
            errors.append(
                f"{table_name}: current unique constraints differ; "
                f"expected={sorted(expected_uniques, key=repr)}, "
                f"actual={sorted(actual_uniques, key=repr)}"
            )

        expected_checks = {
            (constraint.name, _check_text_signature(constraint.sqltext))
            for constraint in table.constraints
            if isinstance(constraint, CheckConstraint)
        }
        actual_checks = {
            (check.get("name"), _check_text_signature(check.get("sqltext")))
            for check in schema_inspector.get_check_constraints(table_name)
        }
        if actual_checks != expected_checks:
            errors.append(
                f"{table_name}: current check constraints differ; "
                f"expected={sorted(expected_checks, key=repr)}, "
                f"actual={sorted(actual_checks, key=repr)}"
            )

    if errors:
        details = "; ".join(errors[:20])
        raise MigrationBootstrapError(
            f"Migrated database does not match current model metadata: {details}"
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
