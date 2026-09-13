"""Import every ORM model so Alembic can populate ``Base.metadata``.

This is the sole exception to ADR-0004's package import direction. Runtime
module code must import domain contracts instead of reaching through this
registry.
"""

from packages.helios_core.db.models import (
    Brand,
    SiteIdentity,
    Venue,
    VenueAlias,
    VenueSite,
    VenueSource,
)
from packages.helios_core.provenance.models import (
    Capture,
    Evidence,
    Source,
    SourceEndpoint,
    SourceRecord,
    SourceRecordVersion,
)

__all__ = [
    "Brand",
    "Capture",
    "Evidence",
    "SiteIdentity",
    "Source",
    "SourceEndpoint",
    "SourceRecord",
    "SourceRecordVersion",
    "Venue",
    "VenueAlias",
    "VenueSite",
    "VenueSource",
]
