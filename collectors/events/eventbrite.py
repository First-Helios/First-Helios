"""
collectors/events/eventbrite.py — Eventbrite API adapter.

Fetches events from the Eventbrite API (free tier: ~500 req/day)
and routes them through events/ingest.py.

API overview:
  Endpoint: GET https://www.eventbriteapi.com/v3/events/search/
  Auth:     Bearer token (EVENTBRITE_TOKEN env var — private OAuth token)
  Rate:     ~500/day free, 5 req/sec
  Key params:
    location.latitude    float
    location.longitude   float
    location.within      "30mi"
    expand               "venue"
    page                 pagination (50 per page)

Category mapping (Eventbrite category → our category):
    Music → music, Sports & Fitness → sports, Food & Drink → food,
    Science & Technology → community, Community & Culture → community,
    Performing & Visual Arts → arts, Film, Media & Entertainment → arts,
    Family & Education → family, Health & Wellness → outdoor,
    Travel & Outdoor → outdoor, Charity & Causes → community,
    Business & Professional → community
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
from collectors.events.registry import event_collector
from events.ingest import EventSignal, ingest_event

logger = logging.getLogger(__name__)

_API_URL = "https://www.eventbriteapi.com/v3/events/search/"
_SOURCE_KEY = "eventbrite"

_AUSTIN_LAT = 30.2672
_AUSTIN_LNG = -97.7431

_CATEGORY_MAP: dict[str, str] = {
    "Music": "music",
    "Sports & Fitness": "sports",
    "Food & Drink": "food",
    "Science & Technology": "community",
    "Community & Culture": "community",
    "Performing & Visual Arts": "arts",
    "Film, Media & Entertainment": "arts",
    "Family & Education": "family",
    "Health & Wellness": "outdoor",
    "Travel & Outdoor": "outdoor",
    "Charity & Causes": "community",
    "Business & Professional": "community",
    "Government & Politics": "community",
    "Home & Lifestyle": "community",
    "Auto, Boat & Air": "community",
    "Hobbies & Special Interest": "community",
    "Other": "community",
    "School Activities": "family",
    "Holiday": "community",
    "Spirituality": "community",
    "Fashion & Beauty": "community",
    "Seasonal & Holiday": "community",
}


def _parse_event(raw: dict[str, Any]) -> EventSignal | None:
    """Parse one Eventbrite event JSON into an EventSignal."""
    event_id = raw.get("id")
    title_obj = raw.get("name", {})
    title = title_obj.get("text") if isinstance(title_obj, dict) else str(title_obj or "")
    if not event_id or not title:
        return None

    # ── Timing ────────────────────────────────────────────────────────────────
    start_time = None
    start_obj = raw.get("start", {})
    if start_obj.get("utc"):
        try:
            start_time = datetime.fromisoformat(
                start_obj["utc"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    end_time = None
    end_obj = raw.get("end", {})
    if end_obj.get("utc"):
        try:
            end_time = datetime.fromisoformat(
                end_obj["utc"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    # ── Venue ─────────────────────────────────────────────────────────────────
    venue = raw.get("venue") or {}
    venue_name = venue.get("name")
    venue_address = None
    lat, lng = None, None

    addr_obj = venue.get("address", {})
    if addr_obj:
        venue_address = addr_obj.get("localized_address_display") or addr_obj.get("address_1")
        if addr_obj.get("latitude") and addr_obj.get("longitude"):
            try:
                lat = float(addr_obj["latitude"])
                lng = float(addr_obj["longitude"])
            except (ValueError, TypeError):
                pass

    # ── Category ──────────────────────────────────────────────────────────────
    cat_obj = raw.get("category") or {}
    cat_name = cat_obj.get("name", "") if isinstance(cat_obj, dict) else ""
    category = _CATEGORY_MAP.get(cat_name, "community")
    subcategory = None
    subcat_obj = raw.get("subcategory") or {}
    if isinstance(subcat_obj, dict) and subcat_obj.get("name"):
        subcategory = subcat_obj["name"].lower().replace(" ", "_")

    # ── Pricing ───────────────────────────────────────────────────────────────
    is_free = raw.get("is_free")
    price_min, price_max = None, None
    # Eventbrite doesn't always expose price in search results;
    # is_free is the reliable field.

    # ── Description ───────────────────────────────────────────────────────────
    desc_obj = raw.get("description", {})
    description = None
    if isinstance(desc_obj, dict):
        description = desc_obj.get("text", "")
        if description:
            description = description[:2000]  # Truncate long descriptions
    elif isinstance(desc_obj, str):
        description = desc_obj[:2000]

    # ── Image ─────────────────────────────────────────────────────────────────
    logo = raw.get("logo", {}) or {}
    image_url = logo.get("url") if isinstance(logo, dict) else None

    # ── Links ─────────────────────────────────────────────────────────────────
    source_url = raw.get("url")

    return EventSignal(
        source=_SOURCE_KEY,
        external_id=str(event_id),
        title=title,
        description=description,
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
        },
    )


def scrape_eventbrite(
    region: str = "austin_tx",
    radius_mi: int = 30,
    max_pages: int = 5,
) -> list[EventSignal]:
    """Fetch events from the Eventbrite API.

    Returns list of EventSignal (not yet ingested).
    """
    token = os.environ.get("EVENTBRITE_TOKEN")
    if not token:
        logger.warning("[eventbrite] EVENTBRITE_TOKEN not set — skipping")
        return []

    if not check_budget(_SOURCE_KEY, max_pages):
        logger.info("[eventbrite] Daily budget exhausted")
        return []

    headers = {"Authorization": f"Bearer {token}"}
    signals: list[EventSignal] = []

    for page_num in range(1, max_pages + 1):
        params = {
            "location.latitude": str(_AUSTIN_LAT),
            "location.longitude": str(_AUSTIN_LNG),
            "location.within": f"{radius_mi}mi",
            "expand": "venue,category,subcategory",
            "page": str(page_num),
        }

        try:
            t0 = time.monotonic()
            resp = requests.get(_API_URL, params=params, headers=headers, timeout=30)
            elapsed = time.monotonic() - t0
            log_external(_SOURCE_KEY, "events_search", elapsed, resp.status_code)

            if resp.status_code == 429:
                logger.warning("[eventbrite] Rate limited — stopping pagination")
                break
            resp.raise_for_status()

            data = resp.json()
            events_raw = data.get("events", [])

            if not events_raw:
                break

            for raw in events_raw:
                sig = _parse_event(raw)
                if sig:
                    signals.append(sig)

            # Check pagination
            pagination = data.get("pagination", {})
            if not pagination.get("has_more_items", False):
                break

            time.sleep(0.25)

        except requests.RequestException as exc:
            logger.error("[eventbrite] Request failed page %d: %s", page_num, exc)
            break

    logger.info("[eventbrite] Fetched %d event signals", len(signals))
    return signals


def run_eventbrite_collector(region: str = "austin_tx") -> int:
    """Full collect → ingest cycle. Returns count of new events."""
    from core.database import init_db, get_session

    signals = scrape_eventbrite(region)
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

    logger.info("[eventbrite] Ingested %d new events out of %d signals", new_count, len(signals))
    return new_count


@event_collector("eventbrite", schedule="0 */6 * * *")
class EventbriteCollector:
    """Registry-compatible wrapper around the Eventbrite adapter."""

    SOURCE = "eventbrite"

    def collect(self, region: str = "austin_tx") -> list[EventSignal]:
        return scrape_eventbrite(region)

    def run(self, region: str = "austin_tx") -> int:
        return run_eventbrite_collector(region)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Eventbrite event collector")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--radius", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't ingest")
    args = parser.parse_args()

    if args.dry_run:
        sigs = scrape_eventbrite(args.region, args.radius)
        for s in sigs[:10]:
            print(f"  {s.start_time}  {s.category:12s}  {s.title[:60]}")
        print(f"Total: {len(sigs)} events")
    else:
        count = run_eventbrite_collector(args.region)
        print(f"Ingested {count} new events")
