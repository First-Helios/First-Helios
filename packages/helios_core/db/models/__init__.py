"""Model registry.

Importing models here ensures they're registered on Base.metadata before
Alembic introspects it. If a model isn't imported somewhere, Alembic can't
see it and won't generate migrations for it.
"""

from packages.helios_core.db.models.venue import (
    Brand,
    SiteIdentity,
    Venue,
    VenueAlias,
    VenueSite,
    VenueSource,
)

__all__ = [
    "Brand",
    "SiteIdentity",
    "Venue",
    "VenueAlias",
    "VenueSite",
    "VenueSource",
]
