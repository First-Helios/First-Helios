"""Guards on the three-layer schema split (ADR-0003).

These need no database: they inspect model metadata and the Alembic filter
directly, so they fail fast in the lint/typecheck-speed part of the suite
rather than only where a Postgres service exists.

Both tests exist because the failure they catch is *silent*. A model that
forgets `{"schema": ...}` lands in `public` without complaint, and a schema
missing from the allowlist makes its tables invisible to autogenerate rather
than raising. Neither shows up as an error -- only as a table that quietly
isn't where anyone expects it.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest
from sqlalchemy import Column, Integer, MetaData, Table

from packages.helios_core.db import models  # noqa: F401 — registers models
from packages.helios_core.db.base import MANAGED_SCHEMAS, VERSION_TABLE_SCHEMA, Base

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


def test_managed_schemas_are_exactly_the_three_layers() -> None:
    """A tripwire, not a tautology: adding a layer is an ADR-0003 amendment."""
    assert set(MANAGED_SCHEMAS) == {"raw", "canonical", "mart"}
    assert VERSION_TABLE_SCHEMA == "public"


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
    ours = _table_in("canonical")
    theirs = _table_in("tiger")

    assert env.include_object(ours.c.id, "id", "column", True, None) is True
    assert env.include_object(theirs.c.id, "id", "column", True, None) is False
