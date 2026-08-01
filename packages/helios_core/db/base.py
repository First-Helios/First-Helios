"""Declarative base and the schema layout every model builds on.

Every model imports from here so they share a single MetaData instance.
Alembic reads Base.metadata to figure out what migrations to generate.

**Schema layout** (see docs/adr/0003-three-layer-schema.md): one database,
three Postgres schemas, distinguished by who writes them and what happens
when they are lost. Models declare their layer explicitly via
``__table_args__ = {"schema": ...}`` -- never rely on ``search_path``, which
is how a table silently gets created in the wrong namespace.

``MANAGED_SCHEMAS`` is the single source of truth for that allowlist. It is
imported by ``alembic/env.py``; adding a layer means adding it here, and
nowhere else.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003 — see TimestampMixin below

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

SCHEMA_RAW = "raw"
SCHEMA_CANONICAL = "canonical"
SCHEMA_MART = "mart"

MANAGED_SCHEMAS = frozenset({SCHEMA_RAW, SCHEMA_CANONICAL, SCHEMA_MART})

# Alembic's own bookkeeping table. It belongs to the migration tool rather
# than to any data layer, so it stays in `public` where it is findable
# regardless of search_path.
VERSION_TABLE_SCHEMA = "public"


class Base(DeclarativeBase):
    """Shared base class for all Helios ORM models."""


class TimestampMixin:
    """`created_at` / `updated_at`, defaulted by the database.

    Server-side defaults rather than Python-side ones, so rows written by
    migrations, `psql`, or any future non-Python writer get them too.

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
