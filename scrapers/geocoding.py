"""
Geocoding utilities for ChainStaffingTracker.

Uses OpenStreetMap Nominatim via geopy (free, no API key required)
with manual overrides for common Austin-area city names.

Rate limit: 1 request/second enforced by sleep.

Depends on: geopy, config.loader
Called by: scrapers/careers_api.py, scrapers/jobspy_adapter.py, backend/ingest.py
"""

import logging
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
    "Round Rock, TX": (30.5083, -97.6789),
    "Round Rock, TX, US": (30.5083, -97.6789),
    "Cedar Park, TX": (30.5052, -97.8203),
    "Cedar Park, TX, US": (30.5052, -97.8203),
    "Pflugerville, TX": (30.4394, -97.6200),
    "Pflugerville, TX, US": (30.4394, -97.6200),
    "Georgetown, TX": (30.6333, -97.6781),
    "San Marcos, TX": (29.8833, -97.9414),
    "Kyle, TX": (29.9889, -97.8772),
    "Buda, TX": (30.0852, -97.8392),
    "Lakeway, TX": (30.3639, -97.9795),
    "Leander, TX": (30.5788, -97.8531),
    "Leander, TX, US": (30.5788, -97.8531),
    "Del Valle, TX": (30.1869, -97.6083),
    "Del Valle, TX, US": (30.1869, -97.6083),
}


def geocode(address: str) -> tuple[float | None, float | None]:
    """Geocode an address string to (lat, lng).

    Checks local overrides first, then queries Nominatim via geopy.
    Rate limit: 1.1 s sleep before each Nominatim call.

    Args:
        address: Free-form address string.

    Returns:
        Tuple of (latitude, longitude) or (None, None) on failure.
        Never raises.
    """
    if not address or not address.strip():
        return None, None

    # Check overrides (case-insensitive containment)
    addr_lower = address.lower().strip()
    for key, coords in _OVERRIDES.items():
        if key.lower() in addr_lower:
            logger.debug("[Geocoding] Override hit for %r → %s", address, coords)
            return coords

    # Query Nominatim
    try:
        time.sleep(1.1)  # Nominatim hard rate limit: 1 req/sec
        location = _geolocator.geocode(address, timeout=10)
        if location:
            logger.info(
                "[Geocoding] OK: %r → (%.4f, %.4f)",
                address, location.latitude, location.longitude,
            )
            return location.latitude, location.longitude

        # Nominatim couldn't resolve — try a simplified version
        simplified = _simplify_address(address)
        if simplified != address:
            time.sleep(1.1)
            location = _geolocator.geocode(simplified, timeout=10)
            if location:
                logger.info(
                    "[Geocoding] OK (simplified): %r → (%.4f, %.4f)",
                    simplified, location.latitude, location.longitude,
                )
                return location.latitude, location.longitude

        logger.warning("[Geocoding] No result for: %r", address)
        return None, None

    except (GeocoderTimedOut, GeocoderServiceError) as e:
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
