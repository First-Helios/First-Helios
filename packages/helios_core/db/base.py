"""Declarative base and schema ownership shared by every model.

Every model imports from here so they share a single MetaData instance.
Alembic reads Base.metadata to figure out what migrations to generate.

**Schema ownership** (see ADR-0004): one database with schemas owned by
bounded-context modules. Models declare their owner explicitly via
``__table_args__ = {"schema": ...}`` -- never rely on ``search_path``, which
is how a table silently gets created in the wrong namespace.

``SCHEMA_OWNERS`` is the single source of truth for ownership and
``MANAGED_SCHEMAS`` is its Alembic allowlist.
"""

from __future__ import annotations

from types import MappingProxyType
from typing import Final

from sqlalchemy.orm import DeclarativeBase

SCHEMA_BRONZE = "bronze"
SCHEMA_IDENTITY = "identity"
SCHEMA_MENU = "menu"
SCHEMA_GOLD = "gold"

SCHEMA_OWNERS: Final = MappingProxyType(
    {
        SCHEMA_BRONZE: "packages.helios_core.provenance",
        SCHEMA_IDENTITY: "packages.helios_core.identity",
        SCHEMA_MENU: "packages.helios_core.domains.menu",
        SCHEMA_GOLD: "packages.helios_core.gold",
    }
)
MANAGED_SCHEMAS = frozenset(SCHEMA_OWNERS)

# Alembic's own bookkeeping table. It belongs to the migration tool rather
# than to any data layer, so it stays in `public` where it is findable
# regardless of search_path.
VERSION_TABLE_SCHEMA = "public"


class Base(DeclarativeBase):
    """Shared base class for all Helios ORM models."""
