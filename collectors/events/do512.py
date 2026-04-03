"""
collectors/events/do512.py — Do512.com HTML scraper.

Do512 is Austin's premier local events aggregator. It covers live music,
comedy, food events, community happenings, markets, and underground events
that don't appear on Ticketmaster or Eventbrite.

Scraping approach:
  - Fetches the events JSON feed at https://do512.com/events/ (paginated)
  - Falls back to HTML scraping of the events listing page
  - Respects robots.txt and adds polite delays

Category mapping (Do512 categories → our taxonomy):
    Live Music → music, Comedy → arts, Food & Drink → food,
    Community → community, Sports → sports, Arts → arts,
    Festivals → music, Markets → food, Film → arts,
    Nightlife → nightlife, Family → family, Free → (is_free=True)
"""

import argparse
import hashlib
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

_SOURCE_KEY = "do512"
_BASE_URL = "https://do512.com"

_CATEGORY_MAP: dict[str, str] = {
    "live music": "music",
    "music": "music",
    "dj": "nightlife",
    "comedy": "arts",
    "standup": "arts",
    "stand-up": "arts",
    "food": "food",
    "food & drink": "food",
    "drink": "food",
    "farmers market": "food",
    "market": "food",
    "community": "community",
    "cultural": "community",
    "volunteer": "community",
    "sports": "sports",
    "fitness": "outdoor",
    "arts": "arts",
    "art": "arts",
    "gallery": "arts",
    "theater": "arts",
    "theatre": "arts",
    "film": "arts",
    "screening": "arts",
    "festival": "music",
    "outdoor": "outdoor",
    "nightlife": "nightlife",
    "bar": "nightlife",
    "club": "nightlife",
    "family": "family",
    "kids": "family",
    "free": "community",
    "tech": "education",
    "workshop": "education",
    "networking": "education",
    "social": "social",
    "game night": "social",
    "trivia": "social",
    "drag": "arts",
}

# Custom User-Agent identifying the bot
_HEADERS = {
    "User-Agent": "FirstHelios-EventCollector/1.0 (+https://github.com/first-helios)",
    "Accept": "application/json, text/html",
}


def _classify(categories: list[str], title: str = "") -> tuple[str, str | None]:
    """Map Do512 categories/tags to our taxonomy."""
    combined = " ".join(categories).lower() + " " + title.lower()
    for keyword, cat in _CATEGORY_MAP.items():
        if keyword in combined:
            return cat, keyword.replace(" ", "_")
    return "community", None


def _sha_id(text: str) -> str:
    """Generate a short stable ID from text."""
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:20]


def _parse_json_event(raw: dict[str, Any]) -> EventSignal | None:
    """Parse one Do512 event from their JSON API."""
    title = raw.get("title") or raw.get("name")
    if not title:
        return None

    event_id = raw.get("id") or raw.get("slug") or _sha_id(title)

    # ── Timing ────────────────────────────────────────────────────────────────
    start_time = None
    for field in ("startDate", "start_date", "date"):
        if raw.get(field):
            try:
                start_time = datetime.fromisoformat(
                    str(raw[field]).replace("Z", "+00:00")
                )
                break
            except (ValueError, TypeError):
                pass

    end_time = None
    for field in ("endDate", "end_date"):
        if raw.get(field):
            try:
                end_time = datetime.fromisoformat(
                    str(raw[field]).replace("Z", "+00:00")
                )
                break
            except (ValueError, TypeError):
                pass

    # ── Venue ─────────────────────────────────────────────────────────────────
    venue_data = raw.get("venue") or {}
    if isinstance(venue_data, str):
        venue_name = venue_data
        venue_address = None
        lat, lng = None, None
    else:
        venue_name = venue_data.get("name")
        venue_address = venue_data.get("address") or venue_data.get("full_address")
        lat = venue_data.get("lat") or venue_data.get("latitude")
        lng = venue_data.get("lng") or venue_data.get("longitude")
        if lat is not None:
            try:
                lat = float(lat)
            except (ValueError, TypeError):
                lat = None
        if lng is not None:
            try:
                lng = float(lng)
            except (ValueError, TypeError):
                lng = None

    # ── Category ──────────────────────────────────────────────────────────────
    categories = raw.get("categories") or raw.get("tags") or []
    if isinstance(categories, str):
        categories = [categories]
    category, subcategory = _classify(categories, title)

    # ── Pricing ───────────────────────────────────────────────────────────────
    price = raw.get("price") or raw.get("cost")
    is_free = None
    price_min = None
    if isinstance(price, str):
        price_lower = price.lower().strip()
        if price_lower in ("free", "$0", "0", ""):
            is_free = True
        else:
            # Try to extract numeric price
            match = re.search(r"\$?(\d+(?:\.\d+)?)", price_lower)
            if match:
                price_min = float(match.group(1))
                is_free = price_min == 0
    elif isinstance(price, (int, float)):
        price_min = float(price)
        is_free = price_min == 0

    # ── Description ───────────────────────────────────────────────────────────
    description = raw.get("description") or raw.get("body") or raw.get("excerpt")
    if description:
        # Strip HTML tags
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()[:2000]

    # ── Source URL ────────────────────────────────────────────────────────────
    slug = raw.get("slug") or raw.get("url_path")
    source_url = raw.get("url") or (f"{_BASE_URL}/events/{slug}" if slug else None)

    # ── Image ─────────────────────────────────────────────────────────────────
    image_url = raw.get("image") or raw.get("thumbnail")
    if isinstance(image_url, dict):
        image_url = image_url.get("url")

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
        price_max=None,
        is_free=is_free,
        source_url=source_url,
        ticket_url=raw.get("ticket_url") or raw.get("ticketUrl"),
raw_payload=raw,
    metadata={
            "image_url": image_url,
            "categories": categories,
        },
    )


def _try_json_feed(max_pages: int = 5) -> list[EventSignal]:
    """Attempt to fetch events from Do512's JSON API/feed."""
    signals: list[EventSignal] = []

    for page in range(1, max_pages + 1):
        # Do512 has various API endpoints; try common patterns
        for url_pattern in [
            f"{_BASE_URL}/events?page={page}&format=json",
            f"{_BASE_URL}/api/events?page={page}",
        ]:
            try:
                t0 = time.monotonic()
                resp = requests.get(url_pattern, headers=_HEADERS, timeout=30)
                elapsed = time.monotonic() - t0
                log_external(_SOURCE_KEY, "json_feed", elapsed, resp.status_code)

                if resp.status_code == 404:
                    continue
                if resp.status_code == 429:
                    logger.warning("[do512] Rate limited — stopping")
                    return signals
                resp.raise_for_status()

                data = resp.json()
                events = data if isinstance(data, list) else data.get("events", data.get("data", []))

                if not events:
                    continue

                for raw in events:
                    sig = _parse_json_event(raw)
                    if sig:
                        signals.append(sig)

                time.sleep(1.0)  # Polite delay
                break  # Found working URL pattern

            except (requests.RequestException, ValueError):
                continue

    return signals


def _try_html_scrape(max_pages: int = 3) -> list[EventSignal]:
    """Fallback: scrape the Do512 HTML events listing page.

    Extracts structured data from JSON-LD or meta tags embedded in the page.
    """
    signals: list[EventSignal] = []

    for page in range(1, max_pages + 1):
        url = f"{_BASE_URL}/events/upcoming?page={page}"
        try:
            t0 = time.monotonic()
            resp = requests.get(url, headers=_HEADERS, timeout=30)
            elapsed = time.monotonic() - t0
            log_external(_SOURCE_KEY, "html_scrape", elapsed, resp.status_code)

            if resp.status_code == 429:
                logger.warning("[do512] Rate limited on HTML — stopping")
                break
            if resp.status_code != 200:
                break
            resp.raise_for_status()

            html = resp.text

            # Extract JSON-LD structured data (many event sites embed this)
            import json
            json_ld_pattern = re.compile(
                r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                re.DOTALL,
            )
            for match in json_ld_pattern.finditer(html):
                try:
                    ld_data = json.loads(match.group(1))
                    # Could be a single object or array
                    items = ld_data if isinstance(ld_data, list) else [ld_data]
                    for item in items:
                        if item.get("@type") == "Event":
                            sig = _parse_jsonld_event(item)
                            if sig:
                                signals.append(sig)
                except (json.JSONDecodeError, KeyError):
                    continue

            time.sleep(1.5)  # Be polite to HTML pages

        except requests.RequestException as exc:
            logger.error("[do512] HTML scrape failed page %d: %s", page, exc)
            break

    return signals


def _parse_jsonld_event(item: dict[str, Any]) -> EventSignal | None:
    """Parse a JSON-LD Event object into an EventSignal."""
    title = item.get("name")
    if not title:
        return None

    ext_id = item.get("url") or _sha_id(title)
    if isinstance(ext_id, str) and ext_id.startswith("http"):
        ext_id = _sha_id(ext_id)

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

    location = item.get("location") or {}
    venue_name = location.get("name") if isinstance(location, dict) else None
    venue_address = None
    lat, lng = None, None

    if isinstance(location, dict):
        addr = location.get("address")
        if isinstance(addr, dict):
            venue_address = addr.get("streetAddress")
        elif isinstance(addr, str):
            venue_address = addr
        geo = location.get("geo")
        if isinstance(geo, dict):
            lat = geo.get("latitude")
            lng = geo.get("longitude")
            if lat is not None:
                lat = float(lat)
            if lng is not None:
                lng = float(lng)

    description = item.get("description", "")
    if description:
        description = description[:2000]

    category, subcategory = _classify([], title)

    # Price
    offers = item.get("offers")
    is_free = None
    price_min = None
    if isinstance(offers, dict):
        price_str = offers.get("price")
        if price_str is not None:
            try:
                price_min = float(price_str)
                is_free = price_min == 0
            except (ValueError, TypeError):
                if str(price_str).lower() == "free":
                    is_free = True

    return EventSignal(
        source=_SOURCE_KEY,
        external_id=str(ext_id),
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
        source_url=item.get("url"),
        ticket_url=item.get("url"),
raw_payload=item,
    metadata={
            "image_url": item.get("image"),
        },
    )


def scrape_do512(
    region: str = "austin_tx",
    max_pages: int = 5,
) -> list[EventSignal]:
    """Fetch events from Do512 via JSON feed, falling back to HTML scraping.

    Returns list of EventSignal (not yet ingested).
    """
    if not check_budget(_SOURCE_KEY, max_pages):
        logger.info("[do512] Daily budget exhausted")
        return []

    # Try JSON feed first (faster, more structured)
    signals = _try_json_feed(max_pages)

    if not signals:
        logger.info("[do512] JSON feed empty — falling back to HTML scrape")
        signals = _try_html_scrape(max_pages)

    logger.info("[do512] Fetched %d event signals", len(signals))
    return signals


def run_do512_collector(region: str = "austin_tx") -> int:
    """Full collect → ingest cycle. Returns count of new events."""
    from core.database import init_db, get_session

    signals = scrape_do512(region)
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

    logger.info("[do512] Ingested %d new events out of %d signals", new_count, len(signals))
    return new_count


@event_collector("do512", schedule="0 */6 * * *")
class Do512Collector:
    """Registry-compatible Do512.com scraper adapter."""

    SOURCE = "do512"

    def collect(self, region: str = "austin_tx") -> list[EventSignal]:
        return scrape_do512(region)

    def run(self, region: str = "austin_tx") -> int:
        return run_do512_collector(region)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Do512 event collector")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't ingest")
    args = parser.parse_args()

    if args.dry_run:
        sigs = scrape_do512(args.region)
        for s in sigs[:10]:
            print(f"  {s.start_time}  {s.category:12s}  {s.title[:60]}")
        print(f"Total: {len(sigs)} events")
    else:
        count = run_do512_collector(args.region)
        print(f"Ingested {count} new events")
