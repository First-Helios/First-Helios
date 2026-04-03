"""
collectors/events/ticketmaster.py — Ticketmaster Discovery API adapter.

Fetches events from the Ticketmaster Discovery API (free tier: 5000 req/day)
and routes them through events/ingest.py.

API overview:
  Endpoint: GET https://app.ticketmaster.com/discovery/v2/events.json
  Auth:     apikey query param (TICKETMASTER_API_KEY env var)
  Rate:     5000/day (free), 5 req/sec
  Key params:
    latlong       "lat,lng"
    radius        int (miles)
    unit          "miles"
    classificationName  "music" | "sports" | "arts" | etc.
    size          max 200
    page          pagination
    sort          "date,asc"

Category mapping (Ticketmaster segment → our category):
    Music → music, Sports → sports, Arts & Theatre → arts,
    Film → arts, Miscellaneous → community
"""

import argparse
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.tracked_request import check_budget, log_external
from collectors.cache import read_cache, write_cache
from events.ingest import EventSignal, ingest_event

logger = logging.getLogger(__name__)

_API_URL = "https://app.ticketmaster.com/discovery/v2/events.json"
_SOURCE_KEY = "ticketmaster"

# Austin, TX coords
_AUSTIN_LAT = 30.2672
_AUSTIN_LNG = -97.7431

_SEGMENT_MAP: dict[str, str] = {
    "Music": "music",
    "Sports": "sports",
    "Arts & Theatre": "arts",
    "Film": "arts",
    "Miscellaneous": "community",
}


def _parse_event(raw: dict[str, Any]) -> EventSignal | None:
    """Parse one Ticketmaster event JSON into an EventSignal."""
    event_id = raw.get("id")
    title = raw.get("name")
    if not event_id or not title:
        return None

    # ── Timing ────────────────────────────────────────────────────────────────
    dates = raw.get("dates", {})
    start_obj = dates.get("start", {})
    start_time = None
    if start_obj.get("dateTime"):
        try:
            start_time = datetime.fromisoformat(
                start_obj["dateTime"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass
    elif start_obj.get("localDate"):
        try:
            start_time = datetime.strptime(start_obj["localDate"], "%Y-%m-%d")
        except (ValueError, TypeError):
            pass

    end_obj = dates.get("end", {})
    end_time = None
    if end_obj.get("dateTime"):
        try:
            end_time = datetime.fromisoformat(
                end_obj["dateTime"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    # ── Venue ─────────────────────────────────────────────────────────────────
    venues_list = (raw.get("_embedded") or {}).get("venues", [])
    venue = venues_list[0] if venues_list else {}
    venue_name = venue.get("name")
    venue_address = None
    lat, lng = None, None

    if venue.get("address"):
        parts = [venue["address"].get("line1", "")]
        city_obj = venue.get("city", {})
        if city_obj.get("name"):
            parts.append(city_obj["name"])
        state_obj = venue.get("state", {})
        if state_obj.get("stateCode"):
            parts.append(state_obj["stateCode"])
        venue_address = ", ".join(p for p in parts if p)

    location = venue.get("location", {})
    if location.get("latitude") and location.get("longitude"):
        try:
            lat = float(location["latitude"])
            lng = float(location["longitude"])
        except (ValueError, TypeError):
            pass

    # ── Category ──────────────────────────────────────────────────────────────
    classifications = raw.get("classifications", [])
    category = "community"
    subcategory = None
    if classifications:
        segment = classifications[0].get("segment", {}).get("name", "")
        category = _SEGMENT_MAP.get(segment, "community")
        genre = classifications[0].get("genre", {}).get("name")
        if genre:
            subcategory = genre.lower().replace(" ", "_")

    # ── Pricing ───────────────────────────────────────────────────────────────
    price_ranges = raw.get("priceRanges", [])
    price_min, price_max = None, None
    is_free = None
    if price_ranges:
        price_min = price_ranges[0].get("min")
        price_max = price_ranges[0].get("max")
        if price_min is not None and price_min == 0 and (price_max is None or price_max == 0):
            is_free = True
        elif price_min is not None:
            is_free = False

    # ── Images ────────────────────────────────────────────────────────────────
    images = raw.get("images", [])
    image_url = images[0]["url"] if images else None

    # ── Links ─────────────────────────────────────────────────────────────────
    source_url = raw.get("url")

    return EventSignal(
        source=_SOURCE_KEY,
        external_id=event_id,
        title=title,
        description=raw.get("info") or raw.get("pleaseNote"),
        venue_name=venue_name,
        venue_address=venue_address,
        lat=lat,
        lng=lng,
        category=category,
        subcategory=subcategory,
        start_time=start_time,
        end_time=end_time,
        price_min=price_min,
        price_max=price_max,
        is_free=is_free,
        source_url=source_url,
        ticket_url=source_url,
        metadata={
            "image_url": image_url,
            "venue_category": venue.get("type"),
        },
    )


def scrape_ticketmaster(
    region: str = "austin_tx",
    radius_mi: int = 30,
    max_pages: int = 5,
) -> list[EventSignal]:
    """Fetch events from Ticketmaster Discovery API.

    Returns list of EventSignal (not yet ingested — caller decides
    whether to ingest or just inspect).
    """
    api_key = os.environ.get("TICKETMASTER_API_KEY")
    if not api_key:
        logger.warning("[ticketmaster] TICKETMASTER_API_KEY not set — skipping")
        return []

    if not check_budget(_SOURCE_KEY, max_pages):
        logger.info("[ticketmaster] Daily budget exhausted")
        return []

    signals: list[EventSignal] = []

    for page_num in range(max_pages):
        params = {
            "apikey": api_key,
            "latlong": f"{_AUSTIN_LAT},{_AUSTIN_LNG}",
            "radius": str(radius_mi),
            "unit": "miles",
            "size": "200",
            "page": str(page_num),
            "sort": "date,asc",
        }

        try:
            t0 = time.monotonic()
            resp = requests.get(_API_URL, params=params, timeout=30)
            elapsed = time.monotonic() - t0
            log_external(_SOURCE_KEY, "events_search", elapsed, resp.status_code)

            if resp.status_code == 429:
                logger.warning("[ticketmaster] Rate limited — stopping pagination")
                break
            resp.raise_for_status()

            data = resp.json()
            embedded = data.get("_embedded", {})
            events_raw = embedded.get("events", [])

            if not events_raw:
                break

            for raw in events_raw:
                sig = _parse_event(raw)
                if sig:
                    signals.append(sig)

            # Check if there are more pages
            page_info = data.get("page", {})
            total_pages = page_info.get("totalPages", 0)
            if page_num + 1 >= total_pages:
                break

            time.sleep(0.25)  # Stay well under 5 req/sec

        except requests.RequestException as exc:
            logger.error("[ticketmaster] Request failed page %d: %s", page_num, exc)
            break

    logger.info("[ticketmaster] Fetched %d event signals", len(signals))
    return signals


def run_ticketmaster_collector(region: str = "austin_tx") -> int:
    """Full collect → ingest cycle. Returns count of new events."""
    from core.database import init_db, get_session

    signals = scrape_ticketmaster(region)
    if not signals:
        return 0

    engine = init_db()
    session = get_session(engine)
    new_count = 0
    try:
        for sig in signals:
            _, is_new = ingest_event(sig, region, session)
            if is_new:
                new_count += 1
    finally:
        session.close()

    logger.info("[ticketmaster] Ingested %d new events out of %d signals", new_count, len(signals))
    return new_count


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Ticketmaster event collector")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--radius", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't ingest")
    args = parser.parse_args()

    if args.dry_run:
        sigs = scrape_ticketmaster(args.region, args.radius)
        for s in sigs[:10]:
            print(f"  {s.start_time}  {s.category:12s}  {s.title[:60]}")
        print(f"Total: {len(sigs)} events")
    else:
        count = run_ticketmaster_collector(args.region)
        print(f"Ingested {count} new events")
