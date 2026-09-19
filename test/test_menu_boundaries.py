"""Menu ownership, restrictive FKs, exact registry exception and import checks."""

from pathlib import Path

import pytest
from sqlalchemy import PrimaryKeyConstraint, UniqueConstraint

from packages.helios_core.db import model_registry  # noqa: F401
from packages.helios_core.db.base import Base
from test.import_boundaries import boundary_violations


def test_exact_nine_menu_tables_and_restrictive_downward_fks() -> None:
    tables = [table for table in Base.metadata.tables.values() if table.schema == "menu"]
    assert {t.name for t in tables} == {
        "currency",
        "menu_page",
        "menu_section",
        "menu_item",
        "menu_variant",
        "menu_modifier",
        "menu_applicability",
        "price_observation",
        "evidence_link",
    }
    for table in tables:
        for fk in table.foreign_keys:
            assert fk.column.table.schema in {"menu", "bronze", "identity"}
            assert fk.ondelete == "RESTRICT" and fk.onupdate == "NO ACTION"
            # Every FK needs a leading index (or PK/UNIQUE) for its local columns.
            assert fk.constraint is not None
            columns = tuple(c.name for c in fk.constraint.columns)
            indexed = [tuple(c.name for c in index.columns) for index in table.indexes]
            indexed += [
                tuple(c.name for c in constraint.columns)
                for constraint in table.constraints
                if isinstance(constraint, (UniqueConstraint, PrimaryKeyConstraint))
            ]
            assert any(key[: len(columns)] == columns for key in indexed), (table.name, columns)


@pytest.mark.parametrize(
    "source",
    [
        "from packages.helios_core.identity import models",
        "import packages.helios_core.provenance.models as hidden",
        "from ...identity.models import Subject",
        "from ...identity import _private",
        "from packages.helios_core.db import model_registry",
        "from packages.helios_core.domains.other.contracts import Something",
        "from packages.helios_core.gold import query",
        "from apps.api import main",
    ],
)
def test_menu_private_upward_and_relative_imports_fail(source: str) -> None:
    assert boundary_violations(source, Path("packages/helios_core/domains/menu/commands.py"))


@pytest.mark.parametrize(
    "source",
    [
        "from packages.helios_core.identity.contracts import ResolvedScopeRequest",
        "from packages.helios_core.provenance.contracts import get_record_version",
        "from ...menu.models import MenuPage",
        "from packages.helios_core.db.base import Base",
    ],
)
def test_menu_published_contracts_and_owned_models_pass(source: str) -> None:
    assert not boundary_violations(source, Path("packages/helios_core/domains/menu/commands.py"))
