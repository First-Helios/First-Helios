#!/usr/bin/env python3
"""Build a facility-name → (lat, lng) index from scrape cache + Nominatim.

Strategy:
  1. Parse location_detail strings from the Workday scrape cache.
     Many contain "Facility Name, 123 Street, Austin, TX 78xxx".
     Extract the facility name and the embedded street address.
  2. For facility names with a co-located street address, geocode the
     street address via Nominatim free-form search.
  3. For facility names WITHOUT a street address, try Nominatim
     structured search (amenity param + Austin viewbox).
  4. Cache all resolved coordinates in data/reference/facility_index.json.

The generated index is loaded by scrapers/geocoding.py at startup and
used as a fast lookup layer between city-level overrides and Nominatim.

Usage:
    python scripts/build_facility_index.py            # from cache
    python scripts/build_facility_index.py --from-db  # from live DB
"""

import argparse
import json
import logging
import os
import re
import sys
import time

import requests

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_PATH = os.path.join(ROOT, "data", "cache", "austin_gov_dryrun.json")
INDEX_PATH = os.path.join(ROOT, "data", "reference", "facility_index.json")

# ── Nominatim config ─────────────────────────────────────────────────────────

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ChainStaffingTracker/1.0 (community labor research)"
RATE_LIMIT = 1.2  # seconds between requests

# Austin metro bounding box (lon1, lat1, lon2, lat2)
AUSTIN_VIEWBOX = "-98.1,30.0,-97.4,30.6"

# Regex: starts with a street number, captures the address portion
# Handles "3201-A Presidential Blvd", "6800 North F.M. 620", etc.
_STREET_ADDR_RE = re.compile(
    r"\d+(?:-?[A-Za-z])?\s+[\w][\w\s.,]+(?:Austin|TX|Texas)\b[,\s]*(?:TX|Texas)?\s*\d{0,5}",
    re.IGNORECASE,
)

# Broader fallback: match "3201-A Presidential Blvd" even without city name,
# then we'll append ", Austin, TX" for geocoding.
_LOOSE_STREET_RE = re.compile(
    r"(\d+(?:-?[A-Za-z])?\s+[\w][\w\s.,']+(?:St|Street|Rd|Road|Blvd|Boulevard|Ave|Avenue|Dr|Drive|Ln|Lane|Way|Ct|Court|Loop|Pkwy|Hwy|FM)\b[.,]?(?:\s*[\w\s,.]*?\d{5})?)",
    re.IGNORECASE,
)

# Facility names that are too vague to geocode precisely → map to city center
_VAGUE_PATTERNS = [
    "various", "multiple", "city of austin",
    "fully remote", "tbd", "community recreation",
    "harold ct", "health campus", "sherman road",
]

AUSTIN_CENTER = (30.2672, -97.7431)
# Austin-Bergstrom International Airport (for "AUS" prefixed facilities)
ABIA_CENTER = (30.1975, -97.6664)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s  %(message)s",
)
logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _nominatim_freeform(query: str) -> tuple[float, float] | None:
    """Free-form Nominatim search within Austin viewbox."""
    time.sleep(RATE_LIMIT)
    r = requests.get(
        NOMINATIM_URL,
        params={
            "q": query,
            "countrycodes": "us",
            "format": "jsonv2",
            "limit": 1,
            "viewbox": AUSTIN_VIEWBOX,
            "bounded": 1,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None


def _nominatim_structured(amenity: str) -> tuple[float, float] | None:
    """Structured Nominatim search using amenity + Austin, Texas."""
    time.sleep(RATE_LIMIT)
    r = requests.get(
        NOMINATIM_URL,
        params={
            "amenity": amenity,
            "city": "Austin",
            "state": "Texas",
            "countrycodes": "us",
            "format": "jsonv2",
            "limit": 1,
            "viewbox": AUSTIN_VIEWBOX,
            "bounded": 1,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data:
        return float(data[0]["lat"]), float(data[0]["lon"])
    return None


def _extract_facility_name(loc_text: str) -> str | None:
    """Extract a clean facility / building name from a location_detail string.

    Examples:
      "Austin Animal Services, 7201 Levander Loop, ..."   → "Austin Animal Services"
      "Central Library – 710 W. Cesar Chavez St., ..."     → "Central Library"
      "One Texas Center (OTC) - 505 Barton Springs Rd ..." → "One Texas Center"
      "Palmer Events Center"                                → "Palmer Events Center"
      "4815 Mueller Blvd, Austin TX 78723"                  → None (just an address)

    Returns the facility name portion, or None if the string is just an address.
    """
    if not loc_text:
        return None

    # If the string starts with digits, it's a direct address, not a facility name
    if re.match(r"\d", loc_text.strip()):
        return None

    # Split on common separators that precede a street number:
    # "Name, 123 St" or "Name – 123 St" or "Name - 123 St"
    parts = re.split(r"[,\-–—]\s*(?=\d)", loc_text, maxsplit=1)
    name = parts[0].strip()

    # Also split on " at " or standalone digits mid-string
    name = re.split(r"\s+\d+\s+", name, maxsplit=1)[0].strip()

    # Remove parenthetical content (abbreviations, addresses within parens)
    name = re.sub(r"\s*\([^)]*\)\s*", " ", name).strip()

    # Remove trailing punctuation / junk
    name = name.rstrip(",-–— ")

    # If the name still contains "Austin" + a state indicator, it's probably
    # "Austin, TX" or "Austin, Texas" — skip city-only strings
    if re.match(r"^Austin\s*,?\s*(TX|Texas)\s*$", name, re.IGNORECASE):
        return None

    # If the name is too short or too long, skip
    if len(name) < 3 or len(name) > 60:
        return None

    return name


def _extract_street_from_detail(loc_text: str) -> str | None:
    """Extract a street address embedded in a location_detail string.

    Tries strict regex first (requires Austin/TX), then loose regex
    (just needs a street suffix like Blvd/Rd/Dr) with Austin appended.
    """
    # Strict: "123 Main St, Austin, TX 78701"
    m = _STREET_ADDR_RE.search(loc_text)
    if m:
        addr = _clean_extracted_address(m.group(0))
        if addr and len(addr) >= 10:
            return addr

    # Loose: "3201-A Presidential Blvd" (no city) — append Austin
    m2 = _LOOSE_STREET_RE.search(loc_text)
    if m2:
        addr = _clean_extracted_address(m2.group(1))
        if addr and len(addr) >= 10:
            # Check if Austin/TX already present
            if not re.search(r"Austin|TX|Texas", addr, re.IGNORECASE):
                addr = f"{addr}, Austin, TX"
            return addr

    return None


def _clean_extracted_address(raw: str) -> str | None:
    """Post-process an extracted address: truncate at ZIP boundary, clean notation."""
    addr = raw.strip().rstrip(",")

    # Truncate at the first complete ZIP code (5 digits) + trailing content.
    # "2600 Webberville Rd, Austin 78702 Glen Bell..." → "2600 Webberville Rd, Austin 78702"
    m = re.search(r"(\d{5})\s+[A-Z]", addr)
    if m:
        addr = addr[:m.end(1)]

    # Normalise Farm-to-Market road notation: "F.M. 620" → "FM 620"
    addr = re.sub(r"F\.?M\.?\s+", "FM ", addr)

    # Strip "Building X" / "Bldg. X" suffixes that confuse Nominatim
    addr = re.sub(r"\s*,?\s*(?:Building|Bldg\.?)\s+[A-Z0-9]+", "", addr, flags=re.I)

    # Truncate junk after ZIP code boundary ("78744. Watch Inside TPW...")
    addr = re.sub(r"(\d{5})\.\s+[A-Z].*$", r"\1", addr)

    addr = addr.strip().rstrip(",")
    return addr[:150] if addr else None


def _is_vague(name: str) -> bool:
    """Check if a facility name is too vague to geocode precisely."""
    low = name.lower()
    return any(p in low for p in _VAGUE_PATTERNS)


# ── Main build logic ─────────────────────────────────────────────────────────

def load_location_details_from_cache() -> list[dict]:
    """Load location signal data from the Workday scrape cache.

    Returns list of dicts with keys: location_text, address, location_detail.
    Uses paired data so we can match facility names to co-located addresses.
    """
    if not os.path.exists(CACHE_PATH):
        logger.error("Cache file not found: %s", CACHE_PATH)
        sys.exit(1)

    with open(CACHE_PATH) as f:
        signals = json.load(f)

    records = []
    for sig in signals:
        meta = sig.get("metadata", {})
        records.append({
            "location_text": meta.get("location_text", ""),
            "address": meta.get("address", ""),
            "location_detail": meta.get("location_detail", ""),
        })
    return records


def load_location_details_from_db() -> list[dict]:
    """Load location data from the job_postings table."""
    sys.path.insert(0, ROOT)
    from backend.database import get_session
    from postings.models import JobPosting

    session = get_session()
    try:
        rows = (
            session.query(
                JobPosting.raw_address,
                JobPosting.detail_json,
            )
            .filter(JobPosting.source == "workday_gov")
            .all()
        )
        records = []
        for raw_addr, dj in rows:
            records.append({
                "location_text": "",
                "address": raw_addr or "",
                "location_detail": (dj or {}).get("location_detail", ""),
            })
        return records
    finally:
        session.close()


def _normalise_facility_name(name: str) -> str:
    """Normalise a facility name for index keying."""
    # Strip trailing ", Austin, TX" / ", Austin, Texas" / ", Austin"
    name = re.sub(r",?\s*Austin\s*,?\s*(TX|Texas)?\s*$", "", name, flags=re.I)
    # Remove parenthetical content
    name = re.sub(r"\s*\([^)]*\)\s*", " ", name)
    return name.strip().lower()


def build_index(records: list[dict]) -> dict:
    """Build facility_name → {lat, lng, source, address} from signal records.

    Each record has location_text, address, and location_detail.
    Strategy:
      1. Build mapping: normalised_facility_name → best_street_address
         using ALL three fields from every signal.
      2. Geocode each facility name using its best address.
    """
    existing = {}
    if os.path.exists(INDEX_PATH):
        with open(INDEX_PATH) as f:
            existing = json.load(f)
        logger.info("Loaded %d existing entries from %s", len(existing), INDEX_PATH)

    # Phase 1: collect facility_name → best street address
    # Sources: location_text (short name), location_detail (description blob)
    # For street address: prefer address field, then extract from location_detail
    facility_addresses: dict[str, str | None] = {}

    for rec in records:
        # Try location_text as facility name (short, clean names from Workday)
        loc_text = (rec.get("location_text") or "").strip()
        address = (rec.get("address") or "").strip()
        loc_detail = (rec.get("location_detail") or "").strip()

        # Source 1: location_text as the facility name
        if loc_text and not re.match(r"^\d", loc_text):
            key = _normalise_facility_name(loc_text)
            if key and len(key) >= 3:
                # Find best street address: try address field, then location_detail
                street = _extract_street_from_detail(address) if address else None
                if not street:
                    street = _extract_street_from_detail(loc_detail) if loc_detail else None
                if key not in facility_addresses or (street and not facility_addresses[key]):
                    facility_addresses[key] = street

        # Source 2: location_detail as facility name (for names embedded in descriptions)
        if loc_detail and not re.match(r"^\d", loc_detail.strip()):
            name = _extract_facility_name(loc_detail)
            if name:
                key2 = _normalise_facility_name(name)
                if key2 and len(key2) >= 3 and key2 not in facility_addresses:
                    street2 = _extract_street_from_detail(loc_detail)
                    facility_addresses[key2] = street2

    logger.info("Found %d unique facility candidates", len(facility_addresses))

    index = dict(existing)  # start from existing cache
    resolved = 0
    failed = 0

    for name_lower, street_addr in sorted(facility_addresses.items()):
        # Skip if already in cache
        if name_lower in index:
            logger.debug("  cached: %s", name_lower)
            continue

        # Vague / generic names → city center
        if _is_vague(name_lower):
            index[name_lower] = {
                "lat": AUSTIN_CENTER[0],
                "lng": AUSTIN_CENTER[1],
                "source": "vague_default",
                "address": None,
            }
            resolved += 1
            logger.info("  vague → city center: %s", name_lower)
            continue

        coords = None
        source = None

        # Strategy 1: geocode co-located street address
        if street_addr:
            try:
                coords = _nominatim_freeform(street_addr)
                if coords:
                    source = "nominatim_street"
                    logger.info("  street OK: %s → %s via %r", name_lower, coords, street_addr)
            except Exception as e:
                logger.warning("  street FAIL: %s → %s", name_lower, e)

        # Strategy 2: Nominatim structured (amenity)
        if not coords:
            try:
                coords = _nominatim_structured(name_lower)
                if coords:
                    source = "nominatim_amenity"
                    logger.info("  amenity OK: %s → %s", name_lower, coords)
            except Exception as e:
                logger.warning("  amenity FAIL: %s → %s", name_lower, e)

        # Strategy 3: freeform with ", Austin, Texas"
        if not coords:
            try:
                query = f"{name_lower}, Austin, Texas"
                coords = _nominatim_freeform(query)
                if coords:
                    source = "nominatim_freeform"
                    logger.info("  freeform OK: %s → %s", name_lower, coords)
            except Exception as e:
                logger.warning("  freeform FAIL: %s → %s", name_lower, e)
        #User Note: This is bad practice, all solutions should come from an external dataset we can download or generated via algoritm
        # Strategy 4: "AUS ..." prefix → Austin-Bergstrom Int'l Airport
        if not coords and name_lower.startswith("aus "):
            coords = ABIA_CENTER
            source = "airport_prefix"
            logger.info("  airport prefix: %s → %s", name_lower, coords)

        # Strategy 5: check for an already-resolved variant
        # e.g. "south austin regional ww treatment plant" ↔
        #      "south austin regional wastewater treatment plant"
        if not coords:
            words = set(name_lower.split())
            best_overlap, best_key = 0, None
            for k in index:
                kwords = set(k.split())
                overlap = len(words & kwords) / max(len(words | kwords), 1)
                if overlap > best_overlap:
                    best_overlap = overlap
                    best_key = k
            if best_overlap >= 0.7 and best_key:
                entry = index[best_key]
                coords = (entry["lat"], entry["lng"])
                source = f"alias_of:{best_key}"
                logger.info("  alias match (%.0f%%): %s → %s",
                            best_overlap * 100, name_lower, best_key)

        # Strategy 6: unresolved → city center (better than no geocode)
        if not coords:
            coords = AUSTIN_CENTER
            source = "unresolved_default"
            logger.info("  unresolved default → city center: %s", name_lower)

        if coords:
            index[name_lower] = {
                "lat": coords[0],
                "lng": coords[1],
                "source": source,
                "address": street_addr,
            }
            resolved += 1
        else:
            failed += 1
            logger.warning("  UNRESOLVED: %s (street=%r)", name_lower, street_addr)

    logger.info("Done: %d resolved, %d failed, %d total in index", resolved, failed, len(index))
    return index


def save_index(index: dict) -> None:
    """Write facility index to JSON."""
    os.makedirs(os.path.dirname(INDEX_PATH), exist_ok=True)
    with open(INDEX_PATH, "w") as f:
        json.dump(index, f, indent=2, sort_keys=True)
    logger.info("Saved %d entries to %s", len(index), INDEX_PATH)


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Build facility location index")
    parser.add_argument("--from-db", action="store_true",
                        help="Load location data from PostgreSQL instead of cache file")
    args = parser.parse_args()

    if args.from_db:
        records = load_location_details_from_db()
    else:
        records = load_location_details_from_cache()

    logger.info("Loaded %d signal records", len(records))
    index = build_index(records)
    save_index(index)


if __name__ == "__main__":
    main()
