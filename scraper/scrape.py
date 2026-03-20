"""
scraper/scrape.py
=================
Fetches all open Starbucks job listings for a given region from the
public careers search API, groups them by store, computes a vacancy
score per store, geocodes addresses, and writes the result to
data/vacancies.json ready for the front end.

Usage
-----
    python scraper/scrape.py --location "Seattle, WA, US" --radius 30
    python scraper/scrape.py --location "New York, NY, US" --radius 25 --out data/vacancies.json

Vacancy score algorithm
-----------------------
Each open role carries a weight:
  barista              1.0   (core service staff — most impactful to customers)
  shift supervisor     2.0   (harder to fill, cascades to whole shift)
  assistant store mgr  1.0
  store manager        0.5   (management gap, but not front-of-house)
  other                0.5

Vacancy levels (per store, based on total weighted score):
  0              → unknown  (no current listings)
  0 < score ≤ 2  → low
  score > 2      → critical
"""

import re
import sys
import json
import time
import argparse
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path

import requests
from tqdm import tqdm

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────
SEARCH_URL   = "https://apply.starbucks.com/api/pcsx/search"
DOMAIN       = "starbucks.com"
PAGE_SIZE    = 100          # max results per API call
REQUEST_DELAY = 1.0         # seconds between pages (be polite)
MAX_RESULTS  = 2000         # hard cap to avoid runaway scraping

# Role → vacancy weight mapping (case-insensitive substring match)
ROLE_WEIGHTS: list[tuple[str, float]] = [
    ("barista",               1.0),
    ("shift supervisor",      2.0),
    ("assistant store manager",1.0),
    ("store manager",         0.5),
]
DEFAULT_WEIGHT = 0.5

VACANCY_THRESHOLDS = {
    "critical": 2.0,   # score > this → critical
    "low":      0.0,   # score > 0    → low
}


# ── Data classes ──────────────────────────────────────────────────
@dataclass
class JobListing:
    position_id: int
    job_id: str
    title: str
    department: str
    store_num: str          # e.g. "03347"
    store_name: str         # e.g. "FIRST INTERSTATE II"
    address: str            # full address string from API
    posted_ts: int
    role_weight: float


@dataclass
class StoreVacancy:
    store_num:     str
    store_name:    str
    address:       str
    lat:           Optional[float] = None
    lng:           Optional[float] = None
    # Roles found (dict: role_label → count)
    open_roles:    dict = field(default_factory=dict)
    vacancy_score: float = 0.0
    vacancy_level: str   = "unknown"   # critical | low | unknown
    listing_count: int   = 0
    # ISO8601 timestamp of most recently posted job
    latest_posting: Optional[str] = None
    # IDs of OSM locations matched from the map layer (filled by frontend)
    osm_ids: list = field(default_factory=list)


# ── API helpers ───────────────────────────────────────────────────

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent":  "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Accept":      "application/json",
    "Referer":     "https://apply.starbucks.com/careers",
})


def fetch_page(location: str, radius: int, start: int) -> dict:
    """Fetch one page of search results from the careers API."""
    params = {
        "domain":          DOMAIN,
        "query":           "",
        "location":        location,
        "start":           start,
        "num":             PAGE_SIZE,
        "sort_by":         "distance",
        "filter_distance": radius,
        # explicitly exclude remote to only get physical stores
        "filter_worklocation_option": "onsite",
    }
    for attempt in range(3):
        try:
            resp = SESSION.get(SEARCH_URL, params=params, timeout=20)
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as exc:
            log.warning("API request failed (attempt %d/3): %s", attempt + 1, exc)
            time.sleep(2 ** attempt)
    raise RuntimeError(f"API unreachable after 3 attempts for start={start}")


def fetch_all_listings(location: str, radius: int) -> list[dict]:
    """Paginate through all results and return raw position dicts."""
    raw_positions: list[dict] = []

    # First page — also grab total and detect actual page size
    log.info("Fetching first page for %r (radius %d mi)…", location, radius)
    first = fetch_page(location, radius, 0)

    if first.get("status") != 200:
        raise RuntimeError(f"API error: {first.get('error')}")

    data      = first.get("data", {})
    positions = data.get("positions", [])
    raw_positions.extend(positions)

    total = (
        data.get("totalPositions")
        or data.get("count")
        or data.get("total")
        or 0
    )

    # Detect true page size from the number of results actually returned
    actual_page_size = len(positions) if positions else PAGE_SIZE
    if actual_page_size == 0:
        log.info("No results on first page.")
        return raw_positions

    log.info(
        "Total positions: %s | Actual page size: %d",
        total or "unknown", actual_page_size,
    )

    # If total unknown, just keep going until we hit an empty page
    if not total:
        start = actual_page_size
        while start < MAX_RESULTS:
            time.sleep(REQUEST_DELAY)
            resp  = fetch_page(location, radius, start)
            batch = resp.get("data", {}).get("positions", [])
            if not batch:
                break
            raw_positions.extend(batch)
            start += actual_page_size
        log.info("Collected %d raw listings.", len(raw_positions))
        return raw_positions

    # Known total — paginate deterministically
    pages = min(
        (total + actual_page_size - 1) // actual_page_size,
        MAX_RESULTS // actual_page_size,
    )

    if pages > 1:
        for page_num in tqdm(range(1, pages), desc="Fetching pages", unit="page"):
            start = page_num * actual_page_size
            time.sleep(REQUEST_DELAY)
            resp  = fetch_page(location, radius, start)
            batch = resp.get("data", {}).get("positions", [])
            if not batch:
                log.info("Empty page at start=%d — stopping.", start)
                break
            raw_positions.extend(batch)

    log.info("Collected %d raw listings.", len(raw_positions))
    return raw_positions


# ── Parsing ───────────────────────────────────────────────────────

_STORE_RE = re.compile(
    r"(?P<role>.+?)\s*-\s*Store#\s*(?P<num>\d+),\s*(?P<name>.+)",
    re.IGNORECASE,
)


def parse_role_weight(role_label: str) -> float:
    """Return vacancy weight for a role label (case-insensitive)."""
    rl = role_label.lower()
    for keyword, weight in ROLE_WEIGHTS:
        if keyword in rl:
            return weight
    return DEFAULT_WEIGHT


def parse_listing(raw: dict) -> Optional[JobListing]:
    """Convert a raw API position dict → JobListing, or None if not a store job."""
    name = raw.get("name", "")
    m = _STORE_RE.match(name)
    if not m:
        return None  # non-store role (corporate, etc.)

    role_label = m.group("role").strip()
    store_num  = m.group("num").strip().zfill(5)
    store_name = m.group("name").strip()

    locations = raw.get("locations") or []
    address = locations[0] if locations else ""

    return JobListing(
        position_id  = raw.get("id", 0),
        job_id       = raw.get("displayJobId", ""),
        title        = name,
        department   = raw.get("department", ""),
        store_num    = store_num,
        store_name   = store_name,
        address      = address,
        posted_ts    = raw.get("postedTs", 0),
        role_weight  = parse_role_weight(role_label),
    )


# ── Aggregation ───────────────────────────────────────────────────

def aggregate_by_store(listings: list[JobListing]) -> list[StoreVacancy]:
    """Group listings by store number and compute vacancy scores."""
    stores: dict[str, StoreVacancy] = {}

    for job in listings:
        key = job.store_num
        if key not in stores:
            stores[key] = StoreVacancy(
                store_num  = job.store_num,
                store_name = job.store_name,
                address    = job.address,
            )
        sv = stores[key]

        # Track per-role counts
        role_key = job.department or job.title.split("-")[0].strip().lower()
        sv.open_roles[role_key] = sv.open_roles.get(role_key, 0) + 1

        sv.vacancy_score  += job.role_weight
        sv.listing_count  += 1

        # Track the most recent posting
        if sv.latest_posting is None or job.posted_ts > (sv.latest_posting or 0):
            sv.latest_posting = job.posted_ts  # type: ignore[assignment]

    # Compute vacancy levels
    for sv in stores.values():
        if sv.vacancy_score == 0:
            sv.vacancy_level = "unknown"
        elif sv.vacancy_score > VACANCY_THRESHOLDS["critical"]:
            sv.vacancy_level = "critical"
        else:
            sv.vacancy_level = "low"

    return sorted(stores.values(), key=lambda s: s.vacancy_score, reverse=True)


# ── Geocoding (Nominatim) ─────────────────────────────────────────

NOM_URL = "https://nominatim.openstreetmap.org/search"
_geo_cache: dict[str, tuple] = {}
_GEOCODE_DELAY = 1.1         # Nominatim rate-limit: ≤1 request/second


def _clean_address(address: str) -> str:
    """Strip suite numbers, shopping center names, and other noise that
    confuses Nominatim. Returns only the street + city + state + country."""
    addr = address
    # 1. Suite / Ste / Bldg / Building + number (word-boundary to avoid "Steiner")
    addr = re.sub(r',?\s*\b(?:Suite|Ste|Bldg|Building)\b\.?\s*[A-Z0-9#.-]+', '', addr, flags=re.IGNORECASE)
    # 2. "Unit" separately so we don't eat "United"
    addr = re.sub(r',?\s*\bUnit\b\s*[A-Z0-9#.-]+', '', addr, flags=re.IGNORECASE)
    # 3. Standalone short token after comma ("..., B, ...", "..., 12, ...")
    #    Limited to 3 chars to avoid eating state names like "Ohio"
    addr = re.sub(r',\s*[A-Z0-9]{1,3}\s*,', ',', addr, flags=re.IGNORECASE)
    # 4. Shopping center / plaza / market / named-place patterns between commas
    #    Matches: "Festival Square", "Parkway Centre", "The Shoppes at Tremont",
    #    "Market at Mill Run", "Hamilton Quarter Shopping Center", etc.
    addr = re.sub(
        r',\s*(?:The\s+)?[\w\s.\'&-]+?'
        r'(?:Shopping Center|Shopping Ctr|Plaza|Market|Mall|Center|Centre|'
        r'Square|Shoppes?|Quarter|Crossing|Run|Outlets|Town Center)\b[^,]*',
        '', addr, flags=re.IGNORECASE,
    )
    # 4b. "Market at <Name>" / "The Market at <Name>" pattern
    addr = re.sub(
        r',\s*(?:The\s+)?Market\s+at\s+[\w\s.]+',
        '', addr, flags=re.IGNORECASE,
    )
    # 5. Normalise freeway designations for Nominatim
    addr = re.sub(r'\bS\s+IH-?35\b', 'S Interstate 35', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bN\s+IH-?35\b', 'N Interstate 35', addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bIH-?35\b',     'Interstate 35',   addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bI-35\b',       'Interstate 35',   addr, flags=re.IGNORECASE)
    addr = re.sub(r'\bS Mopac Expy\b', 'S MoPac Expressway', addr, flags=re.IGNORECASE)
    # 6. Collapse whitespace + dangling commas
    addr = re.sub(r',(\s*,)+', ',', addr)
    addr = re.sub(r'\s{2,}', ' ', addr)
    addr = re.sub(r'^\s*,\s*|\s*,\s*$', '', addr.strip())
    return addr


def _nominatim_query(query: str) -> tuple[Optional[float], Optional[float]]:
    """Single Nominatim request.  Returns (lat, lng) or (None, None)."""
    params = {
        "q":            query,
        "format":       "json",
        "limit":        "1",
        "countrycodes": "us",
    }
    headers = {
        "User-Agent":      "ChainStaffingTracker/1.0 (open-source research tool)",
        "Accept-Language": "en",
    }
    time.sleep(_GEOCODE_DELAY)
    resp = requests.get(NOM_URL, params=params, headers=headers, timeout=15)
    resp.raise_for_status()
    results = resp.json()
    if results:
        return float(results[0]["lat"]), float(results[0]["lon"])
    return None, None


def _load_geocode_overrides() -> dict[str, tuple[float, float]]:
    """Load manual geocode overrides from geocode_overrides.json (if present).
    Returns dict mapping store_num → (lat, lng)."""
    overrides_path = Path(__file__).parent / "geocode_overrides.json"
    if not overrides_path.exists():
        return {}
    try:
        raw = json.loads(overrides_path.read_text())
        return {
            sid: (entry["lat"], entry["lng"])
            for sid, entry in raw.items()
            if entry.get("lat") is not None
        }
    except Exception as exc:
        log.warning("Could not load geocode overrides: %s", exc)
        return {}


_geocode_overrides: dict[str, tuple[float, float]] = {}


def geocode_address(address: str) -> tuple[Optional[float], Optional[float]]:
    """Geocode a store address to (lat, lng) using Nominatim.

    Strategy:
      1. Try the raw address.
      2. If that fails, try a cleaned version (no suite/center/unit noise).
      3. If that fails, try street + city + state only (drop middle tokens).
    Results are cached in memory.
    """
    if not address:
        return None, None
    if address in _geo_cache:
        return _geo_cache[address]

    # Attempt 1: raw address
    try:
        lat, lng = _nominatim_query(address)
        if lat is not None:
            _geo_cache[address] = (lat, lng)
            return lat, lng
    except Exception as exc:
        log.debug("Geocode raw failed for %r: %s", address, exc)

    # Attempt 2: cleaned address (strip suite / shopping center / etc.)
    cleaned = _clean_address(address)
    if cleaned != address:
        try:
            lat, lng = _nominatim_query(cleaned)
            if lat is not None:
                log.debug("Geocode succeeded on cleaned address: %r → %r", address, cleaned)
                _geo_cache[address] = (lat, lng)
                return lat, lng
        except Exception as exc:
            log.debug("Geocode cleaned failed for %r: %s", cleaned, exc)

    # Attempt 3: minimal — first token (street) + last 3 tokens (city, state, country)
    parts = [p.strip() for p in address.split(",") if p.strip()]
    if len(parts) >= 4:
        minimal = f"{parts[0]}, {parts[-3]}, {parts[-2]}, {parts[-1]}"
        try:
            lat, lng = _nominatim_query(minimal)
            if lat is not None:
                log.debug("Geocode succeeded on minimal address: %r → %r", address, minimal)
                _geo_cache[address] = (lat, lng)
                return lat, lng
        except Exception as exc:
            log.debug("Geocode minimal failed for %r: %s", minimal, exc)

    _geo_cache[address] = (None, None)
    return None, None


def geocode_stores(stores: list[StoreVacancy], skip_geocode: bool = False) -> None:
    """Geocode all stores in-place (modifies lat/lng fields).
    Applies manual overrides first (from geocode_overrides.json), then
    Nominatim for the remainder."""
    global _geocode_overrides
    if not _geocode_overrides:
        _geocode_overrides = _load_geocode_overrides()

    # Apply overrides first (instant, no API calls)
    override_count = 0
    for sv in stores:
        if sv.lat is None and sv.store_num in _geocode_overrides:
            sv.lat, sv.lng = _geocode_overrides[sv.store_num]
            override_count += 1
    if override_count:
        log.info("Applied %d geocode overrides from geocode_overrides.json.", override_count)

    if skip_geocode:
        log.info("Skipping Nominatim geocoding (--no-geocode flag).")
        return

    need_geo = [s for s in stores if s.lat is None]
    log.info("Geocoding %d store addresses…", len(need_geo))
    for sv in tqdm(need_geo, desc="Geocoding", unit="store"):
        sv.lat, sv.lng = geocode_address(sv.address)


# ── Output ────────────────────────────────────────────────────────

def stores_to_json(stores: list[StoreVacancy]) -> dict:
    """
    Produce the final JSON payload consumed by the front end.
    Shape:
    {
      "generated":    "ISO timestamp",
      "location":     "Seattle, WA, US",
      "radius_mi":    25,
      "total_stores": 42,
      "stores": {
        "03347": {
          "store_num":      "03347",
          "store_name":     "FIRST INTERSTATE II",
          "address":        "999 3rd Ave, ...",
          "lat":            47.605,
          "lng":           -122.334,
          "open_roles":     {"Barista": 3, "Shift Supervisor": 1},
          "listing_count":  4,
          "vacancy_score":  5.0,
          "vacancy_level":  "critical",
          "latest_posting": 1766379600,
          "osm_ids":        []
        },
        ...
      }
    }
    """
    import datetime
    return {
        "generated":    datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "stores":       {s.store_num: asdict(s) for s in stores},
    }


def append_history_snapshot(payload: dict, history_path: Path) -> None:
    """Append a compact snapshot of the current scan to a history JSON file.

    Each snapshot captures:
      - timestamp, location, radius
      - per-store: vacancy_level, vacancy_score, listing_count, open_roles
      - summary counts (critical / low / unknown)

    The history file is a JSON array of snapshots, newest last.
    """
    import datetime

    stores_raw = payload.get("stores", {})
    summary = {"critical": 0, "low": 0, "unknown": 0, "total": len(stores_raw)}
    store_snapshots = {}
    for snum, s in stores_raw.items():
        lvl = s.get("vacancy_level", "unknown")
        summary[lvl] = summary.get(lvl, 0) + 1
        store_snapshots[snum] = {
            "n":  s.get("store_name", ""),
            "l":  lvl[0],                         # "c" / "l" / "u"
            "s":  round(s.get("vacancy_score", 0), 1),
            "lc": s.get("listing_count", 0),
            "r":  s.get("open_roles", {}),
        }

    snapshot = {
        "ts":       payload.get("generated", datetime.datetime.now(datetime.timezone.utc).isoformat()),
        "loc":      payload.get("location", ""),
        "rad":      payload.get("radius_mi", 0),
        "summary":  summary,
        "stores":   store_snapshots,
    }

    # Load existing history (or start fresh)
    history = []
    if history_path.exists():
        try:
            history = json.loads(history_path.read_text())
            if not isinstance(history, list):
                history = []
        except Exception:
            history = []

    history.append(snapshot)
    history_path.write_text(json.dumps(history, separators=(",", ":")))
    log.info("History snapshot appended to %s  (%d total snapshots)", history_path, len(history))


# ── CLI ───────────────────────────────────────────────────────────

def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Scrape Starbucks job listings and estimate store vacancies."
    )
    p.add_argument(
        "--location", "-l",
        default="Seattle, WA, US",
        help="Location string (e.g. 'Seattle, WA, US')",
    )
    p.add_argument(
        "--radius", "-r",
        type=int,
        default=25,
        help="Search radius in miles (default: 25)",
    )
    p.add_argument(
        "--out", "-o",
        default="frontend/data/vacancies.json",
        help="Output JSON path (default: frontend/data/vacancies.json)",
    )
    p.add_argument(
        "--no-geocode",
        action="store_true",
        help="Skip Nominatim geocoding (faster, but stores lack lat/lng)",
    )
    p.add_argument(
        "--merge",
        action="store_true",
        help="Merge into existing output file instead of overwriting",
    )
    p.add_argument(
        "--verbose", "-v",
        action="store_true",
    )
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 1. Fetch all listings
    raw = fetch_all_listings(args.location, args.radius)

    # 2. Parse into JobListings
    listings = [j for raw_pos in raw if (j := parse_listing(raw_pos)) is not None]
    log.info("Parsed %d store-level listings (%d skipped).",
             len(listings), len(raw) - len(listings))

    if not listings:
        log.error("No store listings found. Check your --location string.")
        sys.exit(1)

    # 3. Aggregate by store
    stores = aggregate_by_store(listings)
    log.info("Found %d unique stores with at least one open position.", len(stores))

    # Print quick summary
    lvl_counts = {"critical": 0, "low": 0, "unknown": 0}
    for s in stores:
        lvl_counts[s.vacancy_level] = lvl_counts.get(s.vacancy_level, 0) + 1
    log.info("Vacancy summary: %s", lvl_counts)

    # 4. Geocode
    geocode_stores(stores, skip_geocode=args.no_geocode)

    # 5. Build output payload
    payload = stores_to_json(stores)
    payload["location"]     = args.location
    payload["radius_mi"]    = args.radius
    payload["total_stores"] = len(stores)

    # 6. Optionally merge with existing data
    if args.merge and out_path.exists():
        try:
            existing = json.loads(out_path.read_text())
            existing_stores = existing.get("stores", {})
            existing_stores.update(payload["stores"])
            payload["stores"] = existing_stores
            payload["total_stores"] = len(existing_stores)
            log.info("Merged with existing data (%d total stores).", len(existing_stores))
        except Exception as exc:
            log.warning("Could not merge with existing file: %s", exc)

    # 7. Write output
    out_path.write_text(json.dumps(payload, indent=2))
    log.info("Written to %s  (%d stores)", out_path, len(payload["stores"]))

    # 8. Append snapshot to history log
    append_history_snapshot(payload, out_path.parent / "history.json")

    # 9. Print top 10 most vacant stores
    top = stores[:10]
    print("\n── Top 10 most vacant stores ──────────────────────────────")
    print(f"{'Store#':<8} {'Level':<10} {'Score':>6}  {'Listings':>8}  Name")
    print("─" * 65)
    for s in top:
        print(f"{s.store_num:<8} {s.vacancy_level:<10} {s.vacancy_score:>6.1f}"
              f"  {s.listing_count:>8}  {s.store_name}")


if __name__ == "__main__":
    main()
