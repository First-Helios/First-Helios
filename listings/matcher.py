"""
listings/matcher.py — Link a job posting to an existing LocalEmployer row.

Two-stage algorithm that mirrors _find_existing() in backend/ingest_layer.py:

  Stage 1 — Fingerprint + proximity (confidence 0.95)
    Query local_employers WHERE fingerprint = :fp AND is_active = TRUE.
    For each candidate compute the Haversine distance to the posting's
    geocoded lat/lng.  Accept the closest candidate within
    PROXIMITY_THRESHOLD_M metres.

  Stage 2 — Fingerprint-only fallback (confidence 0.70)
    If the fingerprint matched exactly one candidate but no candidate was
    within the proximity threshold, accept with lower confidence.
    If multiple candidates matched (multi-location brand) and none are
    close enough, return None — proximity is needed to disambiguate.

Returns (LocalEmployer | None, confidence: float, method: str).

Unmatched result (None, 0.0, "none") is valid — the posting still appears
on the map using its own geocoded lat/lng.
"""

import logging
import math

from sqlalchemy.orm import Session

from backend.database import LocalEmployer
from listings.config import PROXIMITY_THRESHOLD_M

logger = logging.getLogger(__name__)

# Earth radius in metres (WGS-84 mean)
_EARTH_R_M = 6_371_000.0


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in metres between two lat/lng points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi  = math.radians(lat2 - lat1)
    dlam  = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return _EARTH_R_M * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def match_posting_to_employer(
    session: Session,
    fingerprint: str,
    lat: float | None,
    lng: float | None,
) -> tuple["LocalEmployer | None", float, str]:
    """Attempt to link a job posting to an existing LocalEmployer row.

    Args:
        session:     Active SQLAlchemy session.
        fingerprint: Output of make_fingerprint(raw_employer_name).
        lat, lng:    Geocoded position of the job posting (may be None).

    Returns:
        (employer_row | None, confidence, method_string)

        method_string values:
          "exact_fp+proximity" — fingerprint matched AND within threshold
          "fp_only"            — fingerprint matched, single candidate, no proximity confirm
          "fp_ambiguous"       — fingerprint matched multiple, no proximity to pick one
          "none"               — no fingerprint match at all
    """
    if not fingerprint:
        return None, 0.0, "none"

    candidates: list[LocalEmployer] = (
        session.query(LocalEmployer)
        .filter(
            LocalEmployer.fingerprint == fingerprint,
            LocalEmployer.is_active.is_(True),
        )
        .all()
    )

    if not candidates:
        return None, 0.0, "none"

    # Stage 1 — proximity confirmation when coordinates are available
    if lat is not None and lng is not None:
        within: list[tuple[float, LocalEmployer]] = []
        for emp in candidates:
            if emp.lat is None or emp.lng is None:
                continue
            dist = _haversine_m(lat, lng, emp.lat, emp.lng)
            if dist <= PROXIMITY_THRESHOLD_M:
                within.append((dist, emp))

        if within:
            within.sort(key=lambda x: x[0])
            best_dist, best_emp = within[0]
            logger.debug(
                "[Matcher] Matched %r → LocalEmployer id=%d via fp+proximity (%.0f m)",
                fingerprint, best_emp.id, best_dist,
            )
            return best_emp, 0.95, "exact_fp+proximity"

    # Stage 2 — fingerprint-only fallback
    if len(candidates) == 1:
        logger.debug(
            "[Matcher] Matched %r → LocalEmployer id=%d via fp_only (single candidate)",
            fingerprint, candidates[0].id,
        )
        return candidates[0], 0.70, "fp_only"

    # Multiple candidates, no proximity — cannot pick one safely
    logger.debug(
        "[Matcher] %r matched %d candidates, no proximity data — ambiguous",
        fingerprint, len(candidates),
    )
    return None, 0.0, "fp_ambiguous"
