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
# rather than "torchy s". Includes the modifier-letter forms (U+02BC, U+02BB,
# U+02B9), which are letters to Unicode and would otherwise be kept, and the
# acute/fullwidth forms that NFKD would turn into a space or an ASCII quote.
_APOSTROPHES = re.compile("['`‘’‛′´ʹʻʼ＇]")

# Latin letters that NFKD cannot split into base + accent; without this map they
# would survive as distinct letters ("đ" != "d") while their accented cousins fold.
_UNSPLITTABLE = str.maketrans(
    {
        "đ": "d",
        "ð": "d",
        "ø": "o",
        "ł": "l",
        "æ": "ae",
        "œ": "oe",
        "ß": "ss",
        "ı": "i",
        "þ": "th",
        "ħ": "h",
        "ŧ": "t",
    }
)

# Mean Earth radius (metres), the standard value for haversine distance.
_EARTH_RADIUS_M = 6_371_008.8


def _fold(value: str) -> str:
    """Compatibility-decompose, casefold, and drop accents (non-zero combining class)."""
    # NFKD before casefold catches compatibility uppercase (e.g. fullwidth "Ａ");
    # the second NFKD decomposes anything casefold composed.
    decomposed = unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", value).casefold())
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    return stripped.translate(_UNSPLITTABLE)


def _token_char(char: str) -> str:
    category = unicodedata.category(char)
    if category[0] in "LNM":
        # Letters and digits of any script. Marks left after _fold have combining
        # class 0 (e.g. Indic vowel signs): part of the letter, not an accent.
        return char
    if category == "Cf":
        return ""  # invisible format characters (soft hyphen, ZWJ) join, not break
    return " "


def normalize_name(name: str) -> str:
    """Casefold, de-accent, and collapse a display name to a stable token string.

    ``"Torchy's Tacos"`` -> ``"torchys tacos"``; ``"Đông Phương"`` ->
    ``"dong phuong"``; ``"金龍"`` -> ``"金龍"``. Letters and digits of every
    script are kept; only accents are stripped. Punctuation and symbols become a
    word break; runs of whitespace collapse to one space. Deliberately
    conservative: it does not drop stop words or legal suffixes, because
    over-normalizing merges genuinely distinct names.
    """
    # Elide before folding (NFKD turns "´" into a space) and after (it turns
    # "ŉ" into "ʼn").
    folded = _APOSTROPHES.sub("", _fold(_APOSTROPHES.sub("", name)))
    return " ".join("".join(_token_char(char) for char in folded).split())


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
