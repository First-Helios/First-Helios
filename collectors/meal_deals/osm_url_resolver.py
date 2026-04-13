"""
collectors/meal_deals/osm_url_resolver.py — Resolve website URLs via OSM Overpass.

Queries the Overpass API for restaurant/café/fast_food POIs in the Austin
bounding box that have a `website` or `contact:website` tag. Matches
results against local_employers by name fingerprint + proximity, then
stores resolved URLs in the restaurant_urls table.

This is the FREE first pass — ~30-40% coverage expected.  Google Places
fills the gaps (at $32/1000 calls) only for employers OSM couldn't resolve.

Rate limit: single batch query (Overpass allows up to 60s timeout).
Produces CollectorRun record for audit trail.

Depends on: requests, core.database, core.ingest_layer (fingerprint util)
Called by: CLI or scheduler (weekly, Sunday 1:00 AM)
"""

import logging
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

import requests
from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert

from core.database import (
    BrandGroup,
    CollectorRun,
    LocalEmployer,
    RestaurantURL,
    get_engine,
    get_session,
    init_db,
)

logger = logging.getLogger(__name__)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

# Austin metro bounding box (generous — Buda to Georgetown, Dripping Springs to Manor)
AUSTIN_BBOX = (30.05, -98.15, 30.75, -97.40)  # south, west, north, east


def _fingerprint(name: str) -> str:
    """Minimal fingerprint for fuzzy matching — lowercase, strip punctuation, collapse spaces."""
    s = name.lower().strip()
    s = re.sub(r"[''`]s\b", "s", s)         # possessives
    s = re.sub(r"[^a-z0-9 ]", " ", s)       # strip punctuation
    s = re.sub(r"\s+", " ", s).strip()       # collapse whitespace
    return s


def _normalize_url(raw: str) -> str | None:
    """Clean and validate a URL. Strips UTM/tracking query params. Returns None if invalid."""
    if not raw or not raw.strip():
        return None
    url = raw.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    try:
        parsed = urlparse(url)
        if not parsed.netloc or "." not in parsed.netloc:
            return None
        # Strip UTM and common tracking parameters for clean storage
        if parsed.query:
            clean_params = {
                k: v for k, v in parse_qs(parsed.query).items()
                if not k.lower().startswith(("utm_", "fbclid", "gclid", "mc_", "ref", "source"))
            }
            clean_query = urlencode(clean_params, doseq=True) if clean_params else ""
            parsed = parsed._replace(query=clean_query)
        # Strip trailing fragment
        parsed = parsed._replace(fragment="")
        return urlunparse(parsed).rstrip("/") if parsed.path == "/" else urlunparse(parsed)
    except Exception:
        return None


def _haversine_approx(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Quick approximate distance in miles between two points."""
    import math
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlng / 2) ** 2)
    return 3959 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def fetch_osm_restaurant_websites(
    bbox: tuple[float, float, float, float] = AUSTIN_BBOX,
    timeout: int = 180,
) -> list[dict]:
    """Query Overpass for restaurants/cafés/fast_food with website tags.

    Returns list of dicts: {name, lat, lng, website, osm_id, osm_type, amenity, brand, ...}
    """
    south, west, north, east = bbox

    # Query for amenity=restaurant|cafe|fast_food|bar|pub with website OR contact:website
    query = f"""
    [out:json][timeout:{timeout}];
    (
      node["amenity"~"restaurant|cafe|fast_food|bar|pub"]["website"]({south},{west},{north},{east});
      way["amenity"~"restaurant|cafe|fast_food|bar|pub"]["website"]({south},{west},{north},{east});
      node["amenity"~"restaurant|cafe|fast_food|bar|pub"]["contact:website"]({south},{west},{north},{east});
      way["amenity"~"restaurant|cafe|fast_food|bar|pub"]["contact:website"]({south},{west},{north},{east});
    );
    out center;
    """

    logger.info("[OSM-URL] Querying Overpass for restaurant websites in bbox %s", bbox)

    # Overpass rate limit: respect 1 query per 60s.
    # If we've queried recently, wait before firing again.
    _last_query_file = Path(__file__).parent.parent.parent / "data" / "cache" / ".overpass_last_query"
    _last_query_file.parent.mkdir(parents=True, exist_ok=True)
    if _last_query_file.exists():
        try:
            last_ts = float(_last_query_file.read_text().strip())
            elapsed = time.time() - last_ts
            if elapsed < 60:
                wait = 60 - elapsed
                logger.info("[OSM-URL] Rate limit: waiting %.0fs before Overpass query", wait)
                time.sleep(wait)
        except (ValueError, OSError):
            pass

    # Retry with back-off on 429/504
    for attempt in range(3):
        try:
            resp = requests.post(
                OVERPASS_URL,
                data={"data": query},
                timeout=timeout + 60,
                headers={"User-Agent": "FirstHelios/1.0 (community labor research)"},
            )
            # Record successful query time for rate limiting
            try:
                _last_query_file.write_text(str(time.time()))
            except OSError:
                pass
            resp.raise_for_status()
            break
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status in (429, 504) and attempt < 2:
                wait = 60 * (attempt + 1)  # 60s, 120s — respect rate limits
                logger.warning("[OSM-URL] Got %d, retrying in %ds (attempt %d/3)", status, wait, attempt + 1)
                time.sleep(wait)
                continue
            raise

    elements = resp.json().get("elements", [])
    logger.info("[OSM-URL] Got %d elements with website tags", len(elements))

    results = []
    for elem in elements:
        tags = elem.get("tags", {})
        lat = elem.get("lat") or elem.get("center", {}).get("lat")
        lng = elem.get("lon") or elem.get("center", {}).get("lon")
        if not lat or not lng:
            continue

        name = tags.get("name", "")
        if not name:
            continue

        website = tags.get("website") or tags.get("contact:website") or ""
        url = _normalize_url(website)
        if not url:
            continue

        results.append({
            "name": name,
            "fingerprint": _fingerprint(name),
            "lat": lat,
            "lng": lng,
            "website": url,
            "osm_id": str(elem.get("id", "")),
            "osm_type": elem.get("type", ""),
            "amenity": tags.get("amenity", ""),
            "brand": tags.get("brand", ""),
            "cuisine": tags.get("cuisine", ""),
            "phone": tags.get("phone"),
            "opening_hours": tags.get("opening_hours"),
        })

    return results


def match_and_store_urls(
    osm_pois: list[dict],
    region: str = "austin_tx",
    max_distance_mi: float = 0.3,
    dry_run: bool = False,
) -> dict:
    """Match OSM POIs to local_employers and store URLs in restaurant_urls.

    Matching strategy:
      1. Exact fingerprint match + within max_distance_mi
      2. Brand match via brand_group fingerprint (chain fan-out)
      3. Fuzzy name containment + proximity (for slight name variations)

    Returns stats dict.
    """
    engine = init_db()
    session = get_session(engine)

    stats = {
        "osm_total": len(osm_pois),
        "matched": 0,
        "brand_fanout": 0,
        "skipped_no_match": 0,
        "skipped_duplicate": 0,
        "stored": 0,
    }

    # Pre-load all food employers with their fingerprints
    employers = session.query(LocalEmployer).filter(
        LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
        LocalEmployer.region == region,
        LocalEmployer.is_active.is_(True),
    ).all()

    # Build lookup indexes
    fp_to_employers: dict[str, list[LocalEmployer]] = {}
    for emp in employers:
        if emp.fingerprint:
            fp_to_employers.setdefault(emp.fingerprint, []).append(emp)

    now = datetime.utcnow()

    # CollectorRun for audit trail
    run = CollectorRun(
        source="osm_url_resolver",
        fetched=len(osm_pois),
        new=0, updated=0, skipped=0,
        run_at=now,
    )
    if not dry_run:
        session.add(run)
        session.flush()

    try:
        for poi in osm_pois:
            matched_employers = []
            poi_fp = poi["fingerprint"]

            # Strategy 1: exact fingerprint match + proximity
            if poi_fp in fp_to_employers:
                for emp in fp_to_employers[poi_fp]:
                    if emp.lat and emp.lng:
                        dist = _haversine_approx(poi["lat"], poi["lng"], emp.lat, emp.lng)
                        if dist <= max_distance_mi:
                            matched_employers.append(emp)

            # Strategy 2: if no direct match, try brand_group fingerprint
            if not matched_employers and poi.get("brand"):
                brand_fp = _fingerprint(poi["brand"])
                bg = session.query(BrandGroup).filter(
                    BrandGroup.fingerprint == brand_fp
                ).first()
                if bg:
                    brand_emps = session.query(LocalEmployer).filter(
                        LocalEmployer.brand_group_id == bg.id,
                        LocalEmployer.region == region,
                        LocalEmployer.is_active.is_(True),
                    ).all()
                    # For brand match, apply the URL to the nearest location
                    for emp in brand_emps:
                        if emp.lat and emp.lng:
                            dist = _haversine_approx(poi["lat"], poi["lng"], emp.lat, emp.lng)
                            if dist <= max_distance_mi:
                                matched_employers.append(emp)
                    if not matched_employers and brand_emps:
                        # Brand match but no nearby location — apply to ALL brand locations
                        # (chain website applies to every location)
                        matched_employers = brand_emps
                        stats["brand_fanout"] += len(brand_emps)

            # Strategy 3: fuzzy containment + proximity
            if not matched_employers:
                for fp, emps in fp_to_employers.items():
                    if poi_fp in fp or fp in poi_fp:
                        for emp in emps:
                            if emp.lat and emp.lng:
                                dist = _haversine_approx(poi["lat"], poi["lng"], emp.lat, emp.lng)
                                if dist <= 0.15:  # tighter threshold for fuzzy
                                    matched_employers.append(emp)

            if not matched_employers:
                stats["skipped_no_match"] += 1
                continue

            stats["matched"] += 1

            for emp in matched_employers:
                if dry_run:
                    stats["stored"] += 1
                    continue

                url_data = {
                    "local_employer_id": emp.id,
                    "brand_group_id": emp.brand_group_id,
                    "url": poi["website"],
                    "source": "osm",
                    "confidence": 0.8,
                    "is_active": True,
                    "last_checked": now,
                    "created_at": now,
                    "updated_at": now,
                }

                # Upsert — ON CONFLICT (local_employer_id, source) DO UPDATE
                if session.bind.dialect.name == "postgresql":
                    stmt = pg_insert(RestaurantURL).values(**url_data)
                    stmt = stmt.on_conflict_do_update(
                        constraint="uq_restaurant_url_employer_source",
                        set_={
                            "url": stmt.excluded.url,
                            "confidence": stmt.excluded.confidence,
                            "last_checked": stmt.excluded.last_checked,
                            "updated_at": now,
                        },
                    )
                    session.execute(stmt)
                else:
                    existing = session.query(RestaurantURL).filter(
                        RestaurantURL.local_employer_id == emp.id,
                        RestaurantURL.source == "osm",
                    ).first()
                    if existing:
                        existing.url = poi["website"]
                        existing.last_checked = now
                        existing.updated_at = now
                        stats["skipped_duplicate"] += 1
                    else:
                        session.add(RestaurantURL(**url_data))

                stats["stored"] += 1

        if not dry_run:
            run.new = stats["stored"]
            run.skipped = stats["skipped_no_match"]
            session.commit()
            logger.info(
                "[OSM-URL] Committed %d URLs from %d OSM POIs "
                "(matched=%d, brand_fanout=%d, no_match=%d)",
                stats["stored"], stats["osm_total"],
                stats["matched"], stats["brand_fanout"],
                stats["skipped_no_match"],
            )
        else:
            logger.info("[OSM-URL] DRY RUN: would store %d URLs", stats["stored"])

    except Exception as exc:
        session.rollback()
        logger.error("[OSM-URL] Failed: %s", exc, exc_info=True)
        raise
    finally:
        session.close()

    return stats


def run_osm_url_resolver(
    region: str = "austin_tx",
    dry_run: bool = False,
) -> dict:
    """Full pipeline: fetch OSM data → match → store URLs."""
    osm_pois = fetch_osm_restaurant_websites()
    stats = match_and_store_urls(osm_pois, region=region, dry_run=dry_run)
    return stats


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Resolve restaurant URLs from OSM Overpass")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--region", default="austin_tx")
    args = parser.parse_args()

    stats = run_osm_url_resolver(region=args.region, dry_run=args.dry_run)
    print(f"\n--- OSM URL Resolution Stats ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")
