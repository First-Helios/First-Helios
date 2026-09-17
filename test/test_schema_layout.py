"""Architecture fitness tests for ADR-0004's schema ownership boundaries.

These need no database: they inspect model metadata and the Alembic filter
directly, so they fail fast in the lint/typecheck-speed part of the suite
rather than only where a Postgres service exists.

These tests exist because the failures they catch are *silent*. A model that
forgets `{"schema": ...}` lands in `public` without complaint, and a schema
missing from the allowlist makes its tables invisible to autogenerate rather
than raising. Neither shows up as an error -- only as a table that quietly
isn't where anyone expects it.
"""

from __future__ import annotations

import ast
import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy import JSON, Column, Integer, MetaData, Table

from packages.helios_core.db import model_registry  # noqa: F401 — registers all models
from packages.helios_core.db.base import (
    MANAGED_SCHEMAS,
    SCHEMA_BRONZE,
    SCHEMA_IDENTITY,
    SCHEMA_OWNERS,
    VERSION_TABLE_SCHEMA,
    Base,
)

if TYPE_CHECKING:
    from types import ModuleType


class _StopBeforeMigrations(Exception):
    """Sentinel: env.py reached its last line, so stop before it connects."""


def test_every_mapped_table_declares_an_allowlisted_schema() -> None:
    misplaced = {
        table.fullname: table.schema
        for table in Base.metadata.sorted_tables
        if table.schema not in MANAGED_SCHEMAS
    }
    assert not misplaced, (
        f"tables with a missing or unmanaged schema: {misplaced}. "
        f"Every model needs __table_args__ = {{'schema': ...}} "
        f"naming one of {sorted(MANAGED_SCHEMAS)}."
    )


def test_schema_ownership_names_only_active_bounded_contexts() -> None:
    assert dict(SCHEMA_OWNERS) == {
        SCHEMA_BRONZE: "packages.helios_core.provenance",
        SCHEMA_IDENTITY: "packages.helios_core.identity",
    }
    assert frozenset(SCHEMA_OWNERS) == MANAGED_SCHEMAS
    assert VERSION_TABLE_SCHEMA == "public"


def test_legacy_identity_scaffold_is_absent_from_model_metadata() -> None:
    legacy_schemas = {"raw", "canonical", "mart"}
    legacy_tables = {
        "brand",
        "venue",
        "venue_alias",
        "venue_source",
        "site_identity",
        "venue_site",
    }
    assert not {
        table.fullname
        for table in Base.metadata.sorted_tables
        if table.schema in legacy_schemas or table.name in legacy_tables
    }


def test_model_registry_exports_every_alembic_registered_model() -> None:
    exported_tables = {
        model_registry.__dict__[name].__table__.fullname for name in model_registry.__all__
    }
    assert exported_tables == set(Base.metadata.tables)


def test_bronze_owns_exactly_the_provenance_tables_in_step_one() -> None:
    bronze_tables = {
        table.name for table in Base.metadata.sorted_tables if table.schema == SCHEMA_BRONZE
    }
    assert bronze_tables == {
        "source",
        "source_endpoint",
        "capture",
        "source_record",
        "source_record_version",
        "evidence",
    }


def test_identity_owns_exactly_the_step_two_tables() -> None:
    identity_tables = {
        table.name for table in Base.metadata.sorted_tables if table.schema == SCHEMA_IDENTITY
    }
    assert identity_tables == {
        "adjudication",
        "applied_subject_change",
        "current_resolution",
        "establishment",
        "organization",
        "place",
        "resolution_event",
        "resolution_evidence",
        "subject",
        "subject_change",
        "subject_change_evidence",
        "subject_change_member",
        "subject_currentness",
        "subject_lineage",
        "subject_name",
    }


def test_resolution_work_queues_have_explicit_indexes() -> None:
    table = Base.metadata.tables["identity.current_resolution"]
    assert {
        "ix_current_resolution_unresolved",
        "ix_current_resolution_needs_review",
    }.issubset({index.name for index in table.indexes})


def test_bronze_foreign_keys_never_point_upward_or_cascade() -> None:
    violations: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.schema != SCHEMA_BRONZE:
            continue
        for foreign_key in table.foreign_keys:
            target = foreign_key.column.table
            if target.schema != SCHEMA_BRONZE or foreign_key.ondelete not in {
                "RESTRICT",
                "NO ACTION",
            }:
                violations.append(
                    f"{table.fullname}.{foreign_key.parent.name} -> "
                    f"{target.fullname} ondelete={foreign_key.ondelete!r}"
                )
    assert not violations, f"invalid Bronze FK directions or deletion rules: {violations}"


def test_identity_foreign_keys_only_reference_identity_or_bronze_without_cascade() -> None:
    violations: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.schema != SCHEMA_IDENTITY:
            continue
        for foreign_key in table.foreign_keys:
            target = foreign_key.column.table
            if target.schema not in {
                SCHEMA_BRONZE,
                SCHEMA_IDENTITY,
            } or foreign_key.ondelete not in {
                "RESTRICT",
                "NO ACTION",
            }:
                violations.append(
                    f"{table.fullname}.{foreign_key.parent.name} -> "
                    f"{target.fullname} ondelete={foreign_key.ondelete!r}"
                )
    assert not violations, f"invalid Identity FK directions or deletion rules: {violations}"


def test_source_payload_json_exists_only_on_bronze_record_versions() -> None:
    bronze_json_columns = {
        f"{table.fullname}.{column.name}"
        for table in Base.metadata.sorted_tables
        if table.schema == SCHEMA_BRONZE
        for column in table.columns
        if isinstance(column.type, JSON)
    }
    assert bronze_json_columns == {"bronze.source_record_version.source_payload"}


def test_model_registry_is_the_only_db_module_importing_provenance_models() -> None:
    db_root = Path(__file__).resolve().parents[1] / "packages" / "helios_core" / "db"
    importers: set[str] = set()
    for path in db_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("packages.helios_core.provenance")
            for node in ast.walk(tree)
        ):
            importers.add(path.relative_to(db_root).as_posix())
    assert importers == {"model_registry.py"}


def test_model_registry_is_the_only_db_module_importing_identity_models() -> None:
    db_root = Path(__file__).resolve().parents[1] / "packages" / "helios_core" / "db"
    importers: set[str] = set()
    for path in db_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        if any(
            isinstance(node, ast.ImportFrom)
            and node.module is not None
            and node.module.startswith("packages.helios_core.identity")
            for node in ast.walk(tree)
        ):
            importers.add(path.relative_to(db_root).as_posix())
    assert importers == {"model_registry.py"}


def test_identity_imports_only_lower_shared_modules() -> None:
    identity_root = Path(__file__).resolve().parents[1] / "packages" / "helios_core" / "identity"
    forbidden: list[str] = []
    for path in identity_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if node.module.startswith(
                ("apps.", "packages.helios_core.domains.", "packages.helios_core.gold")
            ):
                forbidden.append(f"{path.name}: {node.module}")
    assert not forbidden, f"Identity imports higher or vertical modules: {forbidden}"


def test_identity_uses_the_provenance_contract_not_provenance_models() -> None:
    identity_root = Path(__file__).resolve().parents[1] / "packages" / "helios_core" / "identity"
    forbidden: list[str] = []
    for path in identity_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module == "packages.helios_core.provenance.models"
            ):
                forbidden.append(path.name)
    assert not forbidden, f"Identity reaches through the provenance contract: {forbidden}"


def test_identity_imports_provenance_only_through_its_contract_module() -> None:
    identity_root = Path(__file__).resolve().parents[1] / "packages" / "helios_core" / "identity"
    forbidden: list[str] = []
    for path in identity_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.ImportFrom)
                and node.module is not None
                and node.module.startswith("packages.helios_core.provenance")
                and node.module != "packages.helios_core.provenance.contracts"
            ):
                forbidden.append(f"{path.name}: {node.module}")
    assert not forbidden, f"Identity bypasses published provenance contracts: {forbidden}"


def test_transaction_commands_flush_but_never_commit() -> None:
    root = Path(__file__).resolve().parents[1] / "packages" / "helios_core"
    command_paths = (
        root / "identity" / "commands.py",
        root / "provenance" / "contracts.py",
    )
    commits: list[str] = []
    for path in command_paths:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "commit"
            ):
                commits.append(f"{path.name}:{node.lineno}")
    assert not commits, f"transaction commands must leave commit to their caller: {commits}"


def test_parser_package_remains_orm_free_when_it_lands() -> None:
    parsing_root = Path(__file__).resolve().parents[1] / "packages" / "helios_parsing"
    forbidden: list[str] = []
    for path in parsing_root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            module = node.module if isinstance(node, ast.ImportFrom) else None
            imported_names = (
                [alias.name for alias in node.names] if isinstance(node, ast.Import) else []
            )
            if (
                module is not None and module.startswith(("sqlalchemy", "packages.helios_core"))
            ) or (
                any(
                    name.startswith(("sqlalchemy", "packages.helios_core"))
                    for name in imported_names
                )
            ):
                forbidden.append(f"{path.name}: {module or imported_names}")
    assert not forbidden, f"helios_parsing imports ORM/application modules: {forbidden}"


def _load_alembic_env() -> ModuleType:
    """Import `alembic/env.py` for its filter without running migrations.

    The module runs migrations as an import side effect, which needs a live
    database. Executing it against a stubbed `alembic.context` whose
    `is_offline_mode()` raises a sentinel lets the module define
    `include_object` -- the only part under test -- and then stop at the very
    last line, before any migration machinery starts.
    """
    env_path = Path(__file__).resolve().parents[1] / "alembic" / "env.py"
    spec = importlib.util.spec_from_file_location("_alembic_env_under_test", env_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)

    import alembic

    real_context = alembic.context

    stub = MagicMock()
    # None short-circuits env.py's logging setup; a MagicMock here would be
    # passed to fileConfig() and blow up.
    stub.config.config_file_name = None
    stub.is_offline_mode.side_effect = _StopBeforeMigrations

    alembic.context = stub
    sys.modules["_alembic_env_under_test"] = module
    try:
        spec.loader.exec_module(module)
    except _StopBeforeMigrations:
        pass
    finally:
        alembic.context = real_context
        sys.modules.pop("_alembic_env_under_test", None)

    assert hasattr(module, "include_object"), "env.py stopped before defining include_object"
    return module


def _table_in(schema: str | None) -> Table:
    return Table("some_table", MetaData(), Column("id", Integer), schema=schema)


@pytest.mark.parametrize("schema", sorted(MANAGED_SCHEMAS))
def test_autogenerate_manages_our_own_schemas(schema: str) -> None:
    env = _load_alembic_env()
    assert env.include_object(_table_in(schema), "some_table", "table", True, None) is True


@pytest.mark.parametrize("schema", ["tiger", "tiger_data", "topology", "public", None])
def test_autogenerate_ignores_everything_else(schema: str | None) -> None:
    """The PostGIS/Tiger drop hazard `include_schemas=True` would reintroduce.

    Without this filter, autogenerate emits ~150 `remove_table` operations
    against a PostGIS-enabled database -- it would drop the entire Tiger
    geocoder install. `public` is included here deliberately: `alembic_version`
    lives there and is excluded via `version_table_schema`, not this filter,
    and `spatial_ref_sys` sits there too.
    """
    env = _load_alembic_env()
    assert env.include_object(_table_in(schema), "some_table", "table", True, None) is False


def test_column_inherits_its_parent_tables_verdict() -> None:
    """Columns carry no schema of their own; they must defer to the table."""
    env = _load_alembic_env()
    ours = _table_in("bronze")
    theirs = _table_in("tiger")

    assert env.include_object(ours.c.id, "id", "column", True, None) is True
    assert env.include_object(theirs.c.id, "id", "column", True, None) is False
