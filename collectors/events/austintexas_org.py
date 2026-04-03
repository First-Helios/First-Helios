"""
collectors/events/austintexas_org.py — Visit Austin tourism calendar scraper.

Scrapes events from https://www.austintexas.org/events/ — the official
Visit Austin tourism calendar. This covers festivals, concerts, food events,
outdoor activities, and cultural happenings promoted by the Austin CVB.

Approach:
  - Fetches the events listing page (paginated)
  - Extracts JSON-LD structured data and/or HTML-embedded event data
  - Polite 1.5s delays between requests

Category mapping is based on Visit Austin's own categorization plus
keyword detection from event titles.
"""

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from collectors.events.registry import event_collector
from core.tracked_request import check_budget, log_external
from events.ingest import EventSignal, ingest_event

logger = logging.getLogger(__name__)

_SOURCE_KEY = "austintexas_org"
_BASE_URL = "https://www.austintexas.org"
_EVENTS_URL = f"{_BASE_URL}/events/"

_CATEGORY_MAP: dict[str, str] = {
    "music": "music",
    "live music": "music",
    "concert": "music",
    "festival": "music",
    "food": "food",
    "food & drink": "food",
    "dining": "food",
    "restaurant": "food",
    "wine": "food",
    "beer": "food",
    "craft beer": "food",
    "bbq": "food",
    "barbecue": "food",
    "sports": "sports",
    "racing": "sports",
    "arts": "arts",
    "art": "arts",
    "gallery": "arts",
    "museum": "arts",
    "theater": "arts",
    "theatre": "arts",
    "film": "arts",
    "comedy": "arts",
    "outdoor": "outdoor",
    "nature": "outdoor",
    "hiking": "outdoor",
    "running": "outdoor",
    "cycling": "outdoor",
    "yoga": "outdoor",
    "swimming": "outdoor",
    "lake": "outdoor",
    "community": "community",
    "cultural": "community",
    "heritage": "community",
    "holiday": "community",
    "market": "food",
    "farmers market": "food",
    "family": "family",
    "kids": "family",
    "nightlife": "nightlife",
    "bar": "nightlife",
    "club": "nightlife",
    "education": "education",
    "workshop": "education",
    "conference": "education",
    "tech": "education",
}

_HEADERS = {
    "User-Agent": "FirstHelios-EventCollector/1.0 (+https://github.com/first-helios)",
    "Accept": "text/html, application/json",
}


def _sha_id(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:20]


def _classify_event(title: str, categories: list[str] | None = None) -> tuple[str, str | None]:
    """Guess category from event title and explicit categories."""
    combined = title.lower()
    if categories:
        combined += " " + " ".join(categories).lower()
    for keyword, cat in _CATEGORY_MAP.items():
        if keyword in combined:
            return cat, keyword.replace(" ", "_")
    return "community", None


def _parse_jsonld_event(item: dict[str, Any]) -> EventSignal | None:
    """Parse a JSON-LD Event object from the page."""
    title = item.get("name")
    if not title:
        return None

    ext_url = item.get("url") or ""
    ext_id = _sha_id(ext_url) if ext_url else _sha_id(title)

    start_time = None
    if item.get("startDate"):
        try:
            start_time = datetime.fromisoformat(str(item["startDate"]).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    end_time = None
    if item.get("endDate"):
        try:
            end_time = datetime.fromisoformat(str(item["endDate"]).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            pass

    # Location
    location = item.get("location") or {}
    venue_name = location.get("name") if isinstance(location, dict) else None
    venue_address = None
    lat, lng = None, None

    if isinstance(location, dict):
        addr = location.get("address")
        if isinstance(addr, dict):
            parts = []
            if addr.get("streetAddress"):
                parts.append(addr["streetAddress"])
            if addr.get("addressLocality"):
                parts.append(addr["addressLocality"])
            if addr.get("addressRegion"):
                parts.append(addr["addressRegion"])
            venue_address = ", ".join(parts) if parts else None
        elif isinstance(addr, str):
            venue_address = addr

        geo = location.get("geo")
        if isinstance(geo, dict):
            if geo.get("latitude") is not None:
                try:
                    lat = float(geo["latitude"])
                    lng = float(geo["longitude"])
                except (ValueError, TypeError):
                    pass

    description = item.get("description", "")
    if description:
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()[:2000]

    category, subcategory = _classify_event(title)

    # Price
    is_free = None
    price_min = None
    offers = item.get("offers")
    if isinstance(offers, dict):
        p = offers.get("price")
        if p is not None:
            try:
                price_min = float(p)
                is_free = price_min == 0
            except (ValueError, TypeError):
                if str(p).lower() in ("free", "0"):
                    is_free = True
    elif isinstance(offers, list) and offers:
        p = offers[0].get("price")
        if p is not None:
            try:
                price_min = float(p)
                is_free = price_min == 0
            except (ValueError, TypeError):
                if str(p).lower() in ("free", "0"):
                    is_free = True

    image = item.get("image")
    image_url = None
    if isinstance(image, str):
        image_url = image
    elif isinstance(image, list) and image:
        image_url = image[0] if isinstance(image[0], str) else image[0].get("url")
    elif isinstance(image, dict):
        image_url = image.get("url")

    source_url = item.get("url")
    if source_url and not source_url.startswith("http"):
        source_url = f"{_BASE_URL}{source_url}"

    return EventSignal(
        source=_SOURCE_KEY,
        external_id=ext_id,
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
        is_free=is_free,
        source_url=source_url,
        ticket_url=source_url,
raw_payload=item,
    metadata={
            "image_url": image_url,
        },
    )


def scrape_austintexas_org(
    region: str = "austin_tx",
    max_pages: int = 5,
) -> list[EventSignal]:
    """Scrape events from Visit Austin's tourism calendar.

    Returns list of EventSignal (not yet ingested).
    """
    if not check_budget(_SOURCE_KEY, max_pages):
        logger.info("[austintexas_org] Daily budget exhausted")
        return []

    signals: list[EventSignal] = []

    for page in range(1, max_pages + 1):
        url = f"{_EVENTS_URL}?page={page}" if page > 1 else _EVENTS_URL

        try:
            t0 = time.monotonic()
            resp = requests.get(url, headers=_HEADERS, timeout=30)
            elapsed = time.monotonic() - t0
            log_external(_SOURCE_KEY, "html_scrape", elapsed, resp.status_code)

            if resp.status_code == 429:
                logger.warning("[austintexas_org] Rate limited — stopping")
                break
            if resp.status_code != 200:
                logger.warning("[austintexas_org] HTTP %d on page %d", resp.status_code, page)
                break

            html = resp.text

            # Extract JSON-LD structured data
            json_ld_pattern = re.compile(
                r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                re.DOTALL,
            )

            page_signals = 0
            for match in json_ld_pattern.finditer(html):
                try:
                    ld_data = json.loads(match.group(1))
                    items = ld_data if isinstance(ld_data, list) else [ld_data]

                    for item in items:
                        # Handle @graph arrays
                        if item.get("@graph"):
                            items.extend(item["@graph"])
                            continue

                        if item.get("@type") in ("Event", "MusicEvent", "SportsEvent",
                                                   "Festival", "SocialEvent"):
                            sig = _parse_jsonld_event(item)
                            if sig:
                                signals.append(sig)
                                page_signals += 1

                        # ItemList containing events
                        if item.get("@type") == "ItemList":
                            for elem in item.get("itemListElement", []):
                                event_item = elem.get("item", elem)
                                if event_item.get("@type") in ("Event", "MusicEvent"):
                                    sig = _parse_jsonld_event(event_item)
                                    if sig:
                                        signals.append(sig)
                                        page_signals += 1

                except (json.JSONDecodeError, KeyError, TypeError):
                    continue

            logger.debug("[austintexas_org] Page %d: %d events", page, page_signals)

            if page_signals == 0 and page > 1:
                break  # No more events

            time.sleep(1.5)  # Be polite

        except requests.RequestException as exc:
            logger.error("[austintexas_org] Page %d failed: %s", page, exc)
            break

    logger.info("[austintexas_org] Fetched %d event signals", len(signals))
    return signals


def run_austintexas_org_collector(region: str = "austin_tx") -> int:
    """Full collect → ingest cycle. Returns count of new events."""
    from core.database import init_db, get_session

    signals = scrape_austintexas_org(region)
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

    logger.info("[austintexas_org] Ingested %d new events out of %d signals",
                new_count, len(signals))
    return new_count


@event_collector("austintexas_org", schedule="0 6 * * *")
class AustinTexasOrgCollector:
    """Registry-compatible Visit Austin tourism calendar scraper."""

    SOURCE = "austintexas_org"

    def collect(self, region: str = "austin_tx") -> list[EventSignal]:
        return scrape_austintexas_org(region)

    def run(self, region: str = "austin_tx") -> int:
        return run_austintexas_org_collector(region)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Visit Austin event collector")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't ingest")
    args = parser.parse_args()

    if args.dry_run:
        sigs = scrape_austintexas_org(args.region)
        for s in sigs[:10]:
            print(f"  {s.start_time}  {s.category:12s}  {s.title[:60]}")
        print(f"Total: {len(sigs)} events")
    else:
        count = run_austintexas_org_collector(args.region)
        print(f"Ingested {count} new events")
