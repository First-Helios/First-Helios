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
from packages.helios_core.identity.models import (
    Adjudication,
    AppliedSubjectChange,
    CurrentResolution,
    Establishment,
    Organization,
    Place,
    ResolutionEvent,
    ResolutionEvidence,
    Subject,
    SubjectChange,
    SubjectChangeEvidence,
    SubjectChangeMember,
    SubjectCurrentness,
    SubjectLineage,
    SubjectName,
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
    "Adjudication",
    "AppliedSubjectChange",
    "Brand",
    "Capture",
    "CurrentResolution",
    "Evidence",
    "Establishment",
    "Organization",
    "Place",
    "ResolutionEvent",
    "ResolutionEvidence",
    "SiteIdentity",
    "Source",
    "SourceEndpoint",
    "SourceRecord",
    "SourceRecordVersion",
    "Subject",
    "SubjectChange",
    "SubjectChangeEvidence",
    "SubjectChangeMember",
    "SubjectCurrentness",
    "SubjectLineage",
    "SubjectName",
    "Venue",
    "VenueAlias",
    "VenueSite",
    "VenueSource",
]
