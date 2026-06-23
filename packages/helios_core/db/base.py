"""Declarative base for all ORM models.

Every model imports from here so they share a single MetaData instance.
Alembic reads Base.metadata to figure out what migrations to generate.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared base class for all Helios ORM models."""
