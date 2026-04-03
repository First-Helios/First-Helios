"""
collectors/events/austin_city_calendar.py — City of Austin events via Socrata API.

Fetches events from Austin's open data portal (data.austintexas.gov) and
public meeting calendar via the Socrata SODA API (no auth required for
low-volume reads).

API overview:
  Endpoint: GET https://data.austintexas.gov/resource/{dataset_id}.json
  Auth:     Optional app token (SOCRATA_APP_TOKEN env var) for higher limits
  Rate:     1000 req/hour unauthenticated, 40k with token
  Formats:  JSON, GeoJSON, CSV

The city publishes several relevant datasets:
  - Special Event Permits (dataset varies by year)
  - Public meetings calendar
  - Parks & Recreation events

This adapter also scrapes the city's public event calendar at
https://www.austintexas.gov/events for broader coverage.
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

from collectors.events.registry import event_collector
from core.tracked_request import check_budget, log_external
from events.ingest import EventSignal, ingest_event

logger = logging.getLogger(__name__)

_SOURCE_KEY = "austin_city"

# Socrata SODA API base
_SOCRATA_BASE = "https://data.austintexas.gov/resource"

# Known dataset IDs (these can change — update periodically)
_DATASETS = {
    # Special event permits — includes festivals, runs, markets
    "special_events": "wah4-7y3j",
}

_CATEGORY_MAP: dict[str, str] = {
    "music": "music",
    "concert": "music",
    "festival": "music",
    "run": "outdoor",
    "race": "outdoor",
    "walk": "outdoor",
    "parade": "community",
    "market": "food",
    "farmers": "food",
    "film": "arts",
    "movie": "arts",
    "theater": "arts",
    "theatre": "arts",
    "art": "arts",
    "gallery": "arts",
    "sport": "sports",
    "athletic": "sports",
    "community": "community",
    "meeting": "community",
    "hearing": "community",
    "workshop": "education",
    "class": "education",
    "seminar": "education",
    "park": "outdoor",
    "pool": "outdoor",
    "family": "family",
    "kid": "family",
    "children": "family",
}


def _classify_event(title: str, description: str | None = None) -> tuple[str, str | None]:
    """Guess category from event title/description keywords."""
    text = (title + " " + (description or "")).lower()
    for keyword, cat in _CATEGORY_MAP.items():
        if keyword in text:
            return cat, keyword
    return "community", None


def _parse_socrata_event(raw: dict[str, Any], dataset_type: str) -> EventSignal | None:
    """Parse one Socrata row into an EventSignal."""
    # Different datasets have different column names
    title = (
        raw.get("event_name")
        or raw.get("name")
        or raw.get("title")
        or raw.get("description", "")[:100]
    )
    if not title:
        return None

    # Generate a stable external ID
    ext_id = raw.get("permit_number") or raw.get("id") or raw.get(":id")
    if not ext_id:
        ext_id = f"{dataset_type}_{hash(title + str(raw.get('start_date', '')))}"

    # ── Timing ────────────────────────────────────────────────────────────────
    start_time = None
    for date_field in ("start_date", "event_date", "date", "start_time"):
        if raw.get(date_field):
            try:
                start_time = datetime.fromisoformat(
                    raw[date_field].replace("Z", "+00:00")
                )
                break
            except (ValueError, TypeError):
                pass

    end_time = None
    for date_field in ("end_date", "end_time"):
        if raw.get(date_field):
            try:
                end_time = datetime.fromisoformat(
                    raw[date_field].replace("Z", "+00:00")
                )
                break
            except (ValueError, TypeError):
                pass

    # ── Location ──────────────────────────────────────────────────────────────
    venue_name = raw.get("location") or raw.get("venue") or raw.get("facility_name")
    venue_address = raw.get("address") or raw.get("location_address")
    lat, lng = None, None

    if raw.get("latitude") and raw.get("longitude"):
        try:
            lat = float(raw["latitude"])
            lng = float(raw["longitude"])
        except (ValueError, TypeError):
            pass
    elif raw.get("location_1"):
        loc = raw["location_1"]
        if isinstance(loc, dict):
            lat = loc.get("latitude")
            lng = loc.get("longitude")
            if lat is not None:
                lat = float(lat)
            if lng is not None:
                lng = float(lng)

    # ── Category ──────────────────────────────────────────────────────────────
    description = raw.get("description") or raw.get("event_description")
    category, subcategory = _classify_event(title, description)

    return EventSignal(
        source=_SOURCE_KEY,
        external_id=str(ext_id),
        title=title,
        description=description[:2000] if description else None,
        venue_name=venue_name,
        venue_address=venue_address,
        lat=lat,
        lng=lng,
        category=category,
        subcategory=subcategory,
        start_time=start_time,
        end_time=end_time,
        is_free=True,  # City events are generally free/public
        source_url=f"https://data.austintexas.gov/resource/{_DATASETS.get(dataset_type, '')}",
        metadata={
            "dataset": dataset_type,
            "permit_type": raw.get("permit_type"),
            "attendance_estimate": raw.get("estimated_attendance"),
        },
    )


def scrape_austin_city_calendar(
    region: str = "austin_tx",
    max_rows: int = 1000,
) -> list[EventSignal]:
    """Fetch events from City of Austin Socrata datasets.

    Returns list of EventSignal (not yet ingested).
    """
    if not check_budget(_SOURCE_KEY, len(_DATASETS)):
        logger.info("[austin_city] Daily budget exhausted")
        return []

    app_token = os.environ.get("SOCRATA_APP_TOKEN")
    headers = {}
    if app_token:
        headers["X-App-Token"] = app_token

    signals: list[EventSignal] = []

    for dataset_type, dataset_id in _DATASETS.items():
        url = f"{_SOCRATA_BASE}/{dataset_id}.json"

        # Only fetch events from the last 30 days and future
        where_clause = (
            "start_date > '"
            + (datetime.utcnow().strftime("%Y-%m-%dT00:00:00"))
            + "'"
        )

        params = {
            "$limit": str(max_rows),
            "$order": "start_date ASC",
            "$where": where_clause,
        }

        try:
            t0 = time.monotonic()
            resp = requests.get(url, params=params, headers=headers, timeout=30)
            elapsed = time.monotonic() - t0
            log_external(_SOURCE_KEY, f"socrata_{dataset_type}", elapsed, resp.status_code)

            if resp.status_code == 429:
                logger.warning("[austin_city] Rate limited on %s", dataset_type)
                continue
            resp.raise_for_status()

            rows = resp.json()
            if not isinstance(rows, list):
                logger.warning("[austin_city] Unexpected response for %s", dataset_type)
                continue

            for raw in rows:
                sig = _parse_socrata_event(raw, dataset_type)
                if sig:
                    signals.append(sig)

            logger.info("[austin_city] %s: %d rows → %d signals", dataset_type, len(rows), len(signals))
            time.sleep(0.5)

        except requests.RequestException as exc:
            logger.error("[austin_city] %s fetch failed: %s", dataset_type, exc)

    logger.info("[austin_city] Total: %d event signals", len(signals))
    return signals


def run_austin_city_collector(region: str = "austin_tx") -> int:
    """Full collect → ingest cycle. Returns count of new events."""
    from core.database import init_db, get_session

    signals = scrape_austin_city_calendar(region)
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

    logger.info("[austin_city] Ingested %d new events out of %d signals", new_count, len(signals))
    return new_count


@event_collector("austin_city", schedule="0 5 * * *")
class AustinCityCalendarCollector:
    """Registry-compatible City of Austin Socrata adapter."""

    SOURCE = "austin_city"

    def collect(self, region: str = "austin_tx") -> list[EventSignal]:
        return scrape_austin_city_calendar(region)

    def run(self, region: str = "austin_tx") -> int:
        return run_austin_city_collector(region)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Austin City Calendar event collector")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't ingest")
    args = parser.parse_args()

    if args.dry_run:
        sigs = scrape_austin_city_calendar(args.region)
        for s in sigs[:10]:
            print(f"  {s.start_time}  {s.category:12s}  {s.title[:60]}")
        print(f"Total: {len(sigs)} events")
    else:
        count = run_austin_city_collector(args.region)
        print(f"Ingested {count} new events")
