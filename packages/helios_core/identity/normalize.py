"""Pure identity-matching helpers: name/address normalization and proximity.

Shared-identity matching logic with **no ORM, DB, or network imports** so it is
unit-testable in isolation and importable by the discovery entrypoint
(ADR-0009 §4). A name fingerprint is one match input, never proof of identity by
itself (ADR-0004 §3); proximity uses lat/lon distance, not H3.
"""

from __future__ import annotations

import math
import re
import unicodedata

# Apostrophes are elided, not treated as a word break, so "Torchy's" -> "torchys"
# rather than "torchy s". Everything else non-alphanumeric becomes a break.
_APOSTROPHES = re.compile(r"['‘’`]")
_NON_ALNUM = re.compile(r"[^0-9a-z]+")

# Mean Earth radius (metres), the standard value for haversine distance.
_EARTH_RADIUS_M = 6_371_008.8


def _strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def normalize_name(name: str) -> str:
    """Casefold, de-accent, and collapse a display name to a stable token string.

    ``"Torchy's Tacos"`` -> ``"torchys tacos"``. Punctuation becomes a word
    break; runs of whitespace collapse to one space. Deliberately conservative:
    it does not drop stop words or legal suffixes, because over-normalizing
    merges genuinely distinct names.
    """
    folded = _APOSTROPHES.sub("", _strip_accents(name).casefold())
    return _NON_ALNUM.sub(" ", folded).strip()


def name_fingerprint(name: str) -> str:
    """Return the deterministic match key for a name (``""`` when it has no tokens)."""
    return normalize_name(name)


def normalize_address(address: str) -> str:
    """Normalize an address for use as a coarse equality/alias signal."""
    return normalize_name(address)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres between two WGS84 lat/lon points."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def within_radius_m(
    lat1: float,
    lon1: float,
    lat2: float,
    lon2: float,
    radius_m: float,
) -> bool:
    """True when two points are within ``radius_m`` metres of each other."""
    return haversine_m(lat1, lon1, lat2, lon2) <= radius_m
