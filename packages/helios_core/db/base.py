"""Declarative base and schema ownership shared by every model.

Every model imports from here so they share a single MetaData instance.
Alembic reads Base.metadata to figure out what migrations to generate.

**Schema ownership** (see ADR-0004): one database with schemas owned by
bounded-context modules. Models declare their owner explicitly via
``__table_args__ = {"schema": ...}`` -- never rely on ``search_path``, which
is how a table silently gets created in the wrong namespace.

``SCHEMA_OWNERS`` is the single source of truth for ownership and
``MANAGED_SCHEMAS`` is its Alembic allowlist. The legacy schemas remain
explicitly transitional until Plan 0002 Step 3 removes them.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — see TimestampMixin below
from types import MappingProxyType
from typing import Final

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_RAW = "raw"
SCHEMA_CANONICAL = "canonical"
SCHEMA_MART = "mart"
SCHEMA_BRONZE = "bronze"

TRANSITIONAL_SCHEMAS = frozenset({SCHEMA_RAW, SCHEMA_CANONICAL, SCHEMA_MART})
SCHEMA_OWNERS: Final = MappingProxyType(
    {
        SCHEMA_BRONZE: "packages.helios_core.provenance",
        SCHEMA_RAW: "Plan 0002 Step 3 legacy reset",
        SCHEMA_CANONICAL: "Plan 0002 Step 3 legacy reset",
        SCHEMA_MART: "Plan 0002 Step 3 legacy reset",
    }
)
MANAGED_SCHEMAS = frozenset(SCHEMA_OWNERS)

# Alembic's own bookkeeping table. It belongs to the migration tool rather
# than to any data layer, so it stays in `public` where it is findable
# regardless of search_path.
VERSION_TABLE_SCHEMA = "public"


class Base(DeclarativeBase):
    """Shared base class for all Helios ORM models."""


class TimestampMixin:
    """`created_at` / `updated_at` timestamps.

    Both columns default to `now()` on insert via `server_default`.
    `updated_at` is set on ORM UPDATEs via `onupdate=func.now()`; non-ORM writers must set it explicitly.

    The `datetime` import above cannot move into a TYPE_CHECKING block:
    SQLAlchemy resolves `Mapped[datetime]` against the module namespace at
    mapper-configuration time and raises `MappedAnnotationError` if the name
    is absent. Ruff's `runtime-evaluated-base-classes` setting covers models
    that inherit from `Base`, but this mixin inherits from nothing, so it
    needs the explicit `noqa`.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
