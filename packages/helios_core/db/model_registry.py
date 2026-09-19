"""Import every ORM model so Alembic can populate ``Base.metadata``.

This is the sole exception to ADR-0004's package import direction. Runtime
module code must import domain contracts instead of reaching through this
registry.
"""

from packages.helios_core.domains.menu.models import (
    Currency,
    EvidenceLink,
    MenuApplicability,
    MenuItem,
    MenuModifier,
    MenuPage,
    MenuSection,
    MenuVariant,
    PriceObservation,
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
    "Capture",
    "CurrentResolution",
    "Currency",
    "EvidenceLink",
    "MenuApplicability",
    "MenuItem",
    "MenuModifier",
    "MenuPage",
    "MenuSection",
    "MenuVariant",
    "PriceObservation",
    "Evidence",
    "Establishment",
    "Organization",
    "Place",
    "ResolutionEvent",
    "ResolutionEvidence",
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
]
