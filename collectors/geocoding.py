"""
Geocoding utilities for ChainStaffingTracker.

Uses OpenStreetMap Nominatim via geopy (free, no API key required)
with manual overrides for common Austin-area city names.

Rate limit: 1 request/second enforced by sleep.

Depends on: geopy, config.loader
Called by: scrapers/careers_api.py, scrapers/jobspy_adapter.py, backend/ingest.py
"""

import json
import logging
import os
import re
import time

from geopy.exc import GeocoderServiceError, GeocoderTimedOut
from geopy.geocoders import Nominatim

logger = logging.getLogger(__name__)

_geolocator = Nominatim(
    user_agent="ChainStaffingTracker/1.0 (community labor research)"
)

# Manual coordinate overrides for common Austin-area city-level strings.
# These fire when the address is just a city name (e.g. from JobSpy) so
# we skip the Nominatim call entirely and stay under rate limits.
_OVERRIDES: dict[str, tuple[float, float]] = {
    "Austin, TX": (30.2672, -97.7431),
    "Austin, TX, US": (30.2672, -97.7431),
    "Austin, Texas": (30.2672, -97.7431),
    "Round Rock, TX": (30.5083, -97.6789),
    "Round Rock, TX, US": (30.5083, -97.6789),
    "Round Rock, Texas": (30.5083, -97.6789),
    "Cedar Park, TX": (30.5052, -97.8203),
    "Cedar Park, TX, US": (30.5052, -97.8203),
    "Cedar Park, Texas": (30.5052, -97.8203),
    "Pflugerville, TX": (30.4394, -97.6200),
    "Pflugerville, TX, US": (30.4394, -97.6200),
    "Pflugerville, Texas": (30.4394, -97.6200),
    "Georgetown, TX": (30.6333, -97.6781),
    "Georgetown, Texas": (30.6333, -97.6781),
    "San Marcos, TX": (29.8833, -97.9414),
    "San Marcos, Texas": (29.8833, -97.9414),
    "Kyle, TX": (29.9889, -97.8772),
    "Buda, TX": (30.0852, -97.8392),
    "Lakeway, TX": (30.3639, -97.9795),
    "Leander, TX": (30.5788, -97.8531),
    "Leander, TX, US": (30.5788, -97.8531),
    "Del Valle, TX": (30.1869, -97.6083),
    "Del Valle, TX, US": (30.1869, -97.6083),
    "Bluff Springs, TX": (30.1683, -97.7867),
    "Manor, TX": (30.3427, -97.5569),
    "Hutto, TX": (30.5374, -97.5467),
    "Bastrop, TX": (30.1105, -97.3150),
    "Dripping Springs, TX": (30.1902, -98.0867),
}


# ── Dynamic facility index ────────────────────────────────────────────────────
# Loaded from data/reference/facility_index.json (built by
# scripts/build_facility_index.py from Workday scrape data + Nominatim).
# Maps lowercase facility names → (lat, lng).  Empty dict if file missing.

_FACILITY_INDEX_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "reference", "facility_index.json",
)


def _load_facility_index() -> dict[str, tuple[float, float]]:
    """Load facility_index.json → {lowercase_name: (lat, lng)}."""
    if not os.path.exists(_FACILITY_INDEX_PATH):
        logger.debug("[Geocoding] No facility index at %s", _FACILITY_INDEX_PATH)
        return {}
    try:
        with open(_FACILITY_INDEX_PATH) as f:
            raw = json.load(f)
        idx = {}
        for key, val in raw.items():
            if isinstance(val, dict) and val.get("lat") and val.get("lng"):
                idx[key.lower()] = (val["lat"], val["lng"])
        logger.info("[Geocoding] Loaded %d facilities from index", len(idx))
        return idx
    except Exception as exc:
        logger.warning("[Geocoding] Failed to load facility index: %s", exc)
        return {}


_FACILITY_INDEX: dict[str, tuple[float, float]] = _load_facility_index()


def reload_facility_index() -> int:
    """Reload the facility index from disk.  Returns count of entries."""
    global _FACILITY_INDEX
    _FACILITY_INDEX = _load_facility_index()
    return len(_FACILITY_INDEX)


def geocode(address: str) -> tuple[float | None, float | None]:
    """Geocode an address string to (lat, lng).

    Resolution order:
      1. Facility/landmark index from data/reference/facility_index.json
      2. City-only overrides (no digits in address → "Austin, TX" etc.)
      3. Nominatim free-form search
      4. Nominatim with simplified address (strip suite/ZIP)
      5. (None, None) on failure

    Rate limit: 1.1 s sleep before each Nominatim call.  Never raises.
    """
    if not address or not address.strip():
        return None, None

    addr_lower = address.lower().strip()
    has_street = bool(re.search(r"\d", address))  # digits → likely a street address

    # ── Facility / landmark lookup (always check, regardless of digits) ──
    for key, coords in _FACILITY_INDEX.items():
        if key in addr_lower:
            logger.info("[Geocoding] Facility match %r → %s", address, coords)
            return coords

    # ── City-only overrides (no digits → "Austin, TX" etc.) ──
    if not has_street:
        for key, coords in _OVERRIDES.items():
            if key.lower() in addr_lower:
                logger.debug("[Geocoding] Override hit for %r → %s", address, coords)
                return coords

    # ── Vague patterns even with digits ("3 Locations, Austin, TX") ──
    if re.match(r"^\d+\s+locations?\b", addr_lower):
        return _OVERRIDES.get("Austin, TX", (None, None))

    # ── Sanitise address before Nominatim (strip appended description text) ──
    clean_address = re.split(
        r"\s+(?:When|Applicants|This\s+has|The\s+incumbent|See\s+locations|"
        r"EEO\b|Schedule[:\s]|Work\s+location|Minimum\s+Qualif|Watch\b)",
        address, maxsplit=1, flags=re.IGNORECASE,
    )[0].strip().rstrip(",. ")
    # Truncate after ZIP+junk: "78741 Some text..." → "78741"
    clean_address = re.sub(r"(\d{5})\.\s+[A-Z].*$", r"\1", clean_address)
    clean_address = re.sub(r"(\d{5})\s+[A-Z][a-z].*$", r"\1", clean_address)
    # Handle "RLC Schedule" / "RLC" appended to address
    clean_address = re.sub(r",?\s*RLC\b.*$", "", clean_address, flags=re.I).strip()
    # Normalise Farm-to-Market road: "F.M. 620" → "FM 620"
    clean_address = re.sub(r"F\.?M\.?\s+", "FM ", clean_address)
    # Strip Building/Suite suffixes that confuse Nominatim
    clean_address = re.sub(
        r"\s*(?:Building|Bldg\.?)\s+[A-Z0-9]+(?:\s*,\s*Suite\s+\d+)?",
        "", clean_address, flags=re.I,
    ).strip()
    # Truncate after city+state(+ZIP): "505 Barton Springs Rd. Austin, TX, One TX" → trimmed
    m = re.search(
        r"(?:Austin|Del\s+Valle)\s*,?\s*(?:TX|Texas)(?:\s*,?\s*\d{5})?",
        clean_address, re.I,
    )
    if m:
        clean_address = clean_address[:m.end()].strip().rstrip(",")
    if len(clean_address) < 10:
        clean_address = address.strip()

    # If the cleaned address has no digits, it's probably a garbage
    # description — fall back to city override rather than wasting
    # a Nominatim call
    if not re.search(r"\d", clean_address):
        for key, coords in _OVERRIDES.items():
            if key.lower() in clean_address.lower():
                return coords
        return None, None

    # Query Nominatim
    try:
        import time as _time_mod
        from backend.tracked_request import log_external

        time.sleep(1.1)  # Nominatim hard rate limit: 1 req/sec
        _t0 = _time_mod.time()
        location = _geolocator.geocode(clean_address, timeout=10)
        _lat_ms = int((_time_mod.time() - _t0) * 1000)

        if location:
            log_external(
                "nominatim", "geocode",
                url="https://nominatim.openstreetmap.org/search",
                success=True, latency_ms=_lat_ms, data_items=1,
            )
            logger.info(
                "[Geocoding] OK: %r → (%.4f, %.4f)",
                clean_address, location.latitude, location.longitude,
            )
            return location.latitude, location.longitude

        log_external(
            "nominatim", "geocode",
            url="https://nominatim.openstreetmap.org/search",
            success=True, latency_ms=_lat_ms, data_items=0,
        )

        # Nominatim couldn't resolve — try a simplified version
        simplified = _simplify_address(clean_address)
        if simplified != clean_address:
            time.sleep(1.1)
            _t0 = _time_mod.time()
            location = _geolocator.geocode(simplified, timeout=10)
            _lat_ms2 = int((_time_mod.time() - _t0) * 1000)
            if location:
                log_external(
                    "nominatim", "geocode_simplified",
                    url="https://nominatim.openstreetmap.org/search",
                    success=True, latency_ms=_lat_ms2, data_items=1,
                )
                logger.info(
                    "[Geocoding] OK (simplified): %r → (%.4f, %.4f)",
                    simplified, location.latitude, location.longitude,
                )
                return location.latitude, location.longitude
            log_external(
                "nominatim", "geocode_simplified",
                url="https://nominatim.openstreetmap.org/search",
                success=True, latency_ms=_lat_ms2, data_items=0,
            )

        logger.warning("[Geocoding] No result for: %r", address)
        return None, None

    except (GeocoderTimedOut, GeocoderServiceError) as e:
        log_external(
            "nominatim", "geocode",
            url="https://nominatim.openstreetmap.org/search",
            success=False, error_message=str(e)[:500],
        )
        logger.error("[Geocoding] Service error for %r: %s", address, e)
        return None, None
    except Exception as e:
        logger.error("[Geocoding] Unexpected error for %r: %s", address, e)
        return None, None


def _simplify_address(address: str) -> str:
    """Strip suite/unit numbers and ZIP codes to improve Nominatim match rate.

    e.g. '123 Main St, Suite 100, Austin, TX 78701' → '123 Main St, Austin, TX'
    """
    # Remove suite/unit/ste/apt designators
    address = re.sub(
        r',?\s*(suite|ste|unit|apt|#)\s*[\w-]+', '', address, flags=re.IGNORECASE
    )
    # Remove ZIP codes (Nominatim is sometimes better without them)
    address = re.sub(r'\b\d{5}(-\d{4})?\b', '', address)
    return address.strip().strip(',').strip()


def extract_store_num(
    chain_prefix: str,
    store_id: str | None = None,
    address: str | None = None,
) -> str:
    """Generate a canonical store number.

    Args:
        chain_prefix: e.g. 'SB' for Starbucks.
        store_id: Store's own ID if available.
        address: Fallback — hash of address.

    Returns:
        Canonical store_num like 'SB-03347'.
    """
    if store_id:
        # Clean and zero-pad if numeric
        cleaned = store_id.strip().lstrip("#")
        if cleaned.isdigit():
            cleaned = cleaned.zfill(5)
        return f"{chain_prefix}-{cleaned}"

    if address:
        # Use address hash as fallback
        import hashlib
        addr_hash = hashlib.md5(address.encode()).hexdigest()[:8]
        return f"{chain_prefix}-{addr_hash}"

    return f"{chain_prefix}-UNKNOWN"
