"""
collectors/events/meetup.py — Meetup GraphQL API adapter.

Fetches events from the Meetup GraphQL API and routes them through
events/ingest.py.

API overview:
  Endpoint: POST https://api.meetup.com/gql
  Auth:     Bearer token (MEETUP_API_KEY env var — requires Meetup Pro)
  Rate:     ~200 req/day (Pro tier)

Category mapping (Meetup topic → our category):
    Tech → education, Social → social, Fitness → outdoor,
    Arts → arts, Food & Drink → food, Music → music,
    Language → education, Games → social, Film → arts,
    Health → outdoor, Outdoors → outdoor, Community → community
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

_GQL_URL = "https://api.meetup.com/gql"
_SOURCE_KEY = "meetup"

# Austin, TX coords
_AUSTIN_LAT = 30.2672
_AUSTIN_LNG = -97.7431

_TOPIC_MAP: dict[str, str] = {
    "Tech": "education",
    "Technology": "education",
    "Software Development": "education",
    "Web Development": "education",
    "Data Science": "education",
    "Social": "social",
    "Socializing": "social",
    "New In Town": "social",
    "Making Friends": "social",
    "Singles": "social",
    "Fitness": "outdoor",
    "Sports": "sports",
    "Running": "outdoor",
    "Hiking": "outdoor",
    "Yoga": "outdoor",
    "Arts": "arts",
    "Photography": "arts",
    "Writing": "arts",
    "Dance": "arts",
    "Theater": "arts",
    "Food & Drink": "food",
    "Cooking": "food",
    "Wine": "food",
    "Beer": "food",
    "Music": "music",
    "Language": "education",
    "Games": "social",
    "Board Games": "social",
    "Video Games": "social",
    "Film": "arts",
    "Health": "outdoor",
    "Outdoors": "outdoor",
    "Community": "community",
    "Volunteering": "community",
    "Parents & Family": "family",
    "Education": "education",
    "Career": "education",
    "Networking": "education",
    "Book Club": "social",
    "Anime": "social",
    "Cosplay": "social",
    "LGBTQ": "community",
}

_SEARCH_EVENTS_QUERY = """
query ($filter: SearchConnectionFilter!, $first: Int, $after: String) {
  result: keywordSearch(filter: $filter, input: { first: $first, after: $after }) {
    count
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        result {
          ... on Event {
            id
            title
            description
            dateTime
            endTime
            eventUrl
            going
            isOnline
            venue {
              id
              name
              address
              city
              state
              lat
              lng
            }
            group {
              name
              urlname
              topics(first: 5) {
                edges {
                  node {
                    name
                  }
                }
              }
            }
            feeSettings {
              amount
              currency
            }
            images {
              id
              baseUrl
            }
          }
        }
      }
    }
  }
}
"""


def _classify_topics(topics: list[str]) -> tuple[str, str | None]:
    """Map Meetup topic names to (category, subcategory)."""
    for topic in topics:
        for key, cat in _TOPIC_MAP.items():
            if key.lower() in topic.lower():
                subcategory = topic.lower().replace(" ", "_").replace("&", "and")
                return cat, subcategory
    return "community", None


def _parse_event(node: dict[str, Any]) -> EventSignal | None:
    """Parse one Meetup event from GraphQL response into an EventSignal."""
    event = node.get("result", {})
    if not event:
        return None

    event_id = event.get("id")
    title = event.get("title")
    if not event_id or not title:
        return None

    # ── Timing ────────────────────────────────────────────────────────────────
    start_time = None
    if event.get("dateTime"):
        try:
            start_time = datetime.fromisoformat(
                event["dateTime"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    end_time = None
    if event.get("endTime"):
        try:
            end_time = datetime.fromisoformat(
                event["endTime"].replace("Z", "+00:00")
            )
        except (ValueError, TypeError):
            pass

    # ── Venue ─────────────────────────────────────────────────────────────────
    venue = event.get("venue") or {}
    venue_name = venue.get("name")
    lat, lng = None, None
    venue_address = None

    if venue.get("address"):
        parts = [venue["address"]]
        if venue.get("city"):
            parts.append(venue["city"])
        if venue.get("state"):
            parts.append(venue["state"])
        venue_address = ", ".join(parts)

    if venue.get("lat") and venue.get("lng"):
        try:
            lat = float(venue["lat"])
            lng = float(venue["lng"])
        except (ValueError, TypeError):
            pass

    # ── Category ──────────────────────────────────────────────────────────────
    group = event.get("group") or {}
    topic_edges = (group.get("topics") or {}).get("edges", [])
    topics = [e["node"]["name"] for e in topic_edges if e.get("node", {}).get("name")]
    category, subcategory = _classify_topics(topics)

    # ── Pricing ───────────────────────────────────────────────────────────────
    fee = event.get("feeSettings") or {}
    price_min = fee.get("amount")
    is_free = price_min is None or price_min == 0

    # ── Description ───────────────────────────────────────────────────────────
    description = event.get("description")
    if description:
        description = description[:2000]

    # ── Image ─────────────────────────────────────────────────────────────────
    images = event.get("images") or []
    image_url = images[0].get("baseUrl") if images else None

    # ── Source URL ────────────────────────────────────────────────────────────
    source_url = event.get("eventUrl")

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
        price_min=price_min if not is_free else None,
        price_max=None,
        is_free=is_free,
        source_url=source_url,
        ticket_url=source_url,
        metadata={
            "image_url": image_url,
            "group_name": group.get("name"),
            "group_urlname": group.get("urlname"),
            "topics": topics,
            "going_count": event.get("going"),
        },
    )


def scrape_meetup(
    region: str = "austin_tx",
    max_pages: int = 5,
    page_size: int = 50,
) -> list[EventSignal]:
    """Fetch events from the Meetup GraphQL API.

    Returns list of EventSignal (not yet ingested).
    """
    api_key = os.environ.get("MEETUP_API_KEY")
    if not api_key:
        logger.warning("[meetup] MEETUP_API_KEY not set — skipping")
        return []

    if not check_budget(_SOURCE_KEY, max_pages):
        logger.info("[meetup] Daily budget exhausted")
        return []

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    variables = {
        "filter": {
            "query": "events",
            "lat": _AUSTIN_LAT,
            "lon": _AUSTIN_LNG,
            "radius": 50,
            "source": "EVENTS",
        },
        "first": page_size,
    }

    signals: list[EventSignal] = []
    cursor = None

    for page_num in range(max_pages):
        if cursor:
            variables["after"] = cursor

        payload = {
            "query": _SEARCH_EVENTS_QUERY,
            "variables": variables,
        }

        try:
            t0 = time.monotonic()
            resp = requests.post(_GQL_URL, json=payload, headers=headers, timeout=30)
            elapsed = time.monotonic() - t0
            log_external(_SOURCE_KEY, "events_search", elapsed, resp.status_code)

            if resp.status_code == 429:
                logger.warning("[meetup] Rate limited — stopping pagination")
                break
            resp.raise_for_status()

            data = resp.json()
            result = data.get("data", {}).get("result", {})
            edges = result.get("edges", [])

            if not edges:
                break

            for edge in edges:
                node = edge.get("node", {})
                sig = _parse_event(node)
                if sig:
                    signals.append(sig)

            page_info = result.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            cursor = page_info.get("endCursor")

            time.sleep(0.5)

        except requests.RequestException as exc:
            logger.error("[meetup] Request failed page %d: %s", page_num, exc)
            break

    logger.info("[meetup] Fetched %d event signals", len(signals))
    return signals


def run_meetup_collector(region: str = "austin_tx") -> int:
    """Full collect → ingest cycle. Returns count of new events."""
    from core.database import init_db, get_session

    signals = scrape_meetup(region)
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

    logger.info("[meetup] Ingested %d new events out of %d signals", new_count, len(signals))
    return new_count


@event_collector("meetup", schedule="0 */4 * * *")
class MeetupCollector:
    """Registry-compatible Meetup GraphQL API adapter."""

    SOURCE = "meetup"

    def collect(self, region: str = "austin_tx") -> list[EventSignal]:
        return scrape_meetup(region)

    def run(self, region: str = "austin_tx") -> int:
        return run_meetup_collector(region)


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Meetup event collector")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true", help="Fetch but don't ingest")
    args = parser.parse_args()

    if args.dry_run:
        sigs = scrape_meetup(args.region)
        for s in sigs[:10]:
            print(f"  {s.start_time}  {s.category:12s}  {s.title[:60]}")
        print(f"Total: {len(sigs)} events")
    else:
        count = run_meetup_collector(args.region)
        print(f"Ingested {count} new events")
