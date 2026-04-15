"""
collectors/meal_deals/gbp_offers.py — Google Business Profile offer collector.

Scrapes GBP "offer" posts from restaurant profiles via SerpApi's Google Maps
engine. Many restaurants post weekly specials on their GBP even when their
website is sparse or blocks scraping.

Uses the same SERPAPI_KEY env var and billing relationship as the existing
collectors/job_boards/serpapi_adapter.py.

Data flow:
  SerpApi Google Maps → DealSignal → collectors/meal_deals/ingest.py → meal_deals

Budget:
  MAX_DAILY_CALLS = 100 (configurable via --max-calls)
  Prioritizes brands by location_count descending (one API call per brand,
  fan-out to all locations via brand_fingerprint in ingest.py).

Schedule: Tuesday and Friday at 3:00 AM (stagger from website scraper).

Depends on: requests, core.tracked_request, SERPAPI_KEY env var
Called by: scheduler or CLI
"""

import argparse
import logging
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.registry import deal_collector
from core.tracked_request import check_budget, log_external

logger = logging.getLogger(__name__)

_SERPAPI_URL = "https://serpapi.com/search.json"
_SOURCE_KEY = "serpapi_gbp_offers"

# Budget controls
MAX_DAILY_CALLS = 100
MAX_BATCH_CALLS = 200

# Deal-signal keywords — reused from website_scraper for consistency
_DEAL_KEYWORDS = {
    "special", "specials", "deal", "deals", "combo", "bogo",
    "buy one", "happy hour", "kids eat free", "early bird",
    "lunch special", "dinner special", "daily special",
    "meal deal", "value meal", "discount",
    "limited time", "save", "promotion", "offer",
    "half off", "half price", "% off",
    "for the price of", "2 for", "free",
}

# Deal-type classification
_DEAL_TYPE_MAP = {
    "happy hour": "happy_hour",
    "lunch special": "lunch_special",
    "lunch combo": "lunch_special",
    "dinner special": "daily_special",
    "bogo": "bogo",
    "buy one get one": "bogo",
    "buy one, get one": "bogo",
    "kids eat free": "kids_eat_free",
    "kids meal": "kids_eat_free",
    "daily special": "daily_special",
    "combo": "combo",
    "meal deal": "combo",
    "value": "combo",
}

_PRICE_RE = re.compile(r"\$(\d+\.?\d{0,2})")


def _classify_deal_type(text: str) -> str:
    """Classify deal type from post text."""
    lower = text.lower()
    for keyword, dtype in _DEAL_TYPE_MAP.items():
        if keyword in lower:
            return dtype
    if _PRICE_RE.search(text):
        return "combo"
    return "daily_special"


def _extract_price(text: str) -> float | None:
    """Extract first price from text."""
    match = _PRICE_RE.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _has_deal_signal(text: str) -> bool:
    """Check if text contains deal-related keywords."""
    lower = text.lower()
    return any(kw in lower for kw in _DEAL_KEYWORDS)


def _query_serpapi_gmaps(query: str, api_key: str) -> dict | None:
    """Query SerpApi Google Maps engine for a business.

    Returns the raw JSON response or None on failure.
    """
    params = {
        "engine": "google_maps",
        "q": query,
        "api_key": api_key,
        "hl": "en",
        "type": "search",
    }

    try:
        t0 = time.time()
        resp = requests.get(_SERPAPI_URL, params=params, timeout=30)
        latency_ms = int((time.time() - t0) * 1000)

        log_external(
            _SOURCE_KEY, "gmaps_query",
            url=_SERPAPI_URL, success=resp.status_code == 200,
            latency_ms=latency_ms, data_items=0,
        )

        if resp.status_code != 200:
            logger.warning("[GBP] SerpApi returned HTTP %d for query: %s", resp.status_code, query)
            return None

        return resp.json()

    except Exception as e:
        logger.warning("[GBP] SerpApi request failed for %s: %s", query, e)
        return None


def _extract_offers_from_result(
    result: dict,
    brand_fingerprint: str | None,
    restaurant_name: str,
    local_employer_id: int | None,
    brand_group_id: int | None,
    region: str,
) -> list[DealSignal]:
    """Extract DealSignals from a SerpApi Google Maps result.

    Checks the result's posts/updates/offers for deal-related content.
    """
    signals: list[DealSignal] = []
    seen: set[str] = set()

    # SerpApi returns posts under various keys depending on the result
    posts = []

    # Check top-level local_results for posts
    local_results = result.get("local_results", [])
    if isinstance(local_results, list) and local_results:
        first = local_results[0]
        posts.extend(first.get("posts", []))
        posts.extend(first.get("updates", []))

        # Some results have an "offers" section
        offers = first.get("offers", [])
        if isinstance(offers, list):
            posts.extend(offers)

    # Also check place_results if present (detailed view)
    place = result.get("place_results", {})
    if isinstance(place, dict):
        posts.extend(place.get("posts", []))
        posts.extend(place.get("updates", []))
        posts.extend(place.get("offers", []))

    for post in posts:
        if not isinstance(post, dict):
            continue

        # Extract text from various post formats
        title = post.get("title", "")
        snippet = post.get("snippet", "") or post.get("description", "") or post.get("text", "")
        text = f"{title} {snippet}".strip()

        if not text or not _has_deal_signal(text):
            continue

        # Build deal name from title or first sentence
        deal_name = (title or snippet.split(".")[0].strip())[:80]
        if not deal_name or len(deal_name) < 5:
            continue

        name_key = deal_name.lower()
        if name_key in seen:
            continue
        seen.add(name_key)

        price = _extract_price(text)
        deal_type = _classify_deal_type(text)

        # Extract link if available
        source_url = post.get("link") or post.get("url")

        signals.append(DealSignal(
            restaurant_name=restaurant_name,
            brand_fingerprint=brand_fingerprint,
            local_employer_id=local_employer_id,
            brand_group_id=brand_group_id,
            deal_name=deal_name,
            deal_description=text[:500],
            deal_type=deal_type,
            price=price,
            source="gbp_offer",
            source_url=source_url,
            region=region,
            observed_at=datetime.now(datetime.UTC),
        ))

    return signals


@deal_collector("gbp_offers", schedule="0 3 * * 2,5")
class GBPOfferCollector:
    """Scheduled collector: scrapes Google Business Profile offers via SerpApi.

    Prioritizes brands by location_count (one API call per brand → fan-out
    to all locations via brand_fingerprint in ingest.py).

    Schedule: Tuesday and Friday at 3:00 AM.
    """

    SOURCE = "gbp_offers"

    def collect(
        self,
        region: str = "austin_tx",
        max_calls: int = MAX_DAILY_CALLS,
        dry_run: bool = False,
    ) -> list[DealSignal]:
        """Query SerpApi for GBP offers and return DealSignals."""
        from core.database import BrandGroup, LocalEmployer, RestaurantURL, get_engine, get_session, init_db

        api_key = os.environ.get("SERPAPI_KEY")
        if not api_key:
            logger.error("[GBP] SERPAPI_KEY not set in environment — skipping")
            return []

        engine = init_db()
        session = get_session(engine)
        all_signals: list[DealSignal] = []
        calls_made = 0

        try:
            # Phase 1: Query by brand groups (high ROI — one call covers many locations)
            brands = session.query(BrandGroup).filter(
                BrandGroup.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
                BrandGroup.location_count >= 2,  # at least 2 locations to be worth an API call
            ).order_by(
                BrandGroup.location_count.desc()
            ).all()

            logger.info("[GBP] Found %d restaurant brands to query", len(brands))

            for brand in brands:
                if calls_made >= max_calls:
                    logger.info("[GBP] Hit max_calls limit (%d)", max_calls)
                    break

                if not check_budget(_SOURCE_KEY):
                    logger.warning("[GBP] Daily budget exhausted for %s", _SOURCE_KEY)
                    break

                # Build query: brand name + "Austin TX" for geo context
                query = f"{brand.canonical_name} Austin TX"
                logger.debug("[GBP] Querying: %s", query)

                data = _query_serpapi_gmaps(query, api_key)
                calls_made += 1

                if data:
                    signals = _extract_offers_from_result(
                        data,
                        brand_fingerprint=brand.fingerprint,
                        restaurant_name=brand.canonical_name,
                        local_employer_id=None,  # fan-out happens in ingest
                        brand_group_id=brand.id,
                        region=region,
                    )
                    if signals:
                        logger.info(
                            "[GBP] %s: %d offers found (x%d locations = %d potential rows)",
                            brand.canonical_name, len(signals),
                            brand.location_count, len(signals) * brand.location_count,
                        )
                        all_signals.extend(signals)

                # Rate limit: 0.5 sec between calls
                time.sleep(0.5)

            # Phase 2: Query individual local restaurants (if budget remains)
            if calls_made < max_calls:
                remaining = max_calls - calls_made
                # Find local restaurants with Google Places URLs but no recent deals
                locals_query = session.query(
                    LocalEmployer
                ).join(
                    RestaurantURL, RestaurantURL.local_employer_id == LocalEmployer.id
                ).filter(
                    LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
                    LocalEmployer.region == region,
                    LocalEmployer.is_active.is_(True),
                    RestaurantURL.source == "google_places",
                    RestaurantURL.is_active.is_(True),
                    # Only locals (not brands already covered in Phase 1)
                    (LocalEmployer.brand_group_id.is_(None)) | (LocalEmployer.location_count <= 1),
                ).order_by(
                    LocalEmployer.id.asc()
                ).limit(remaining).all()

                logger.info("[GBP] Querying %d individual local restaurants", len(locals_query))

                for emp in locals_query:
                    if calls_made >= max_calls:
                        break
                    if not check_budget(_SOURCE_KEY):
                        break

                    query = f"{emp.name} {emp.address or ''} Austin TX".strip()
                    data = _query_serpapi_gmaps(query, api_key)
                    calls_made += 1

                    if data:
                        signals = _extract_offers_from_result(
                            data,
                            brand_fingerprint=None,
                            restaurant_name=emp.name,
                            local_employer_id=emp.id,
                            brand_group_id=emp.brand_group_id,
                            region=region,
                        )
                        if signals:
                            logger.info("[GBP] %s: %d offers found", emp.name, len(signals))
                            all_signals.extend(signals)

                    time.sleep(0.5)

        except Exception as exc:
            logger.error("[GBP] Collection failed: %s", exc, exc_info=True)
        finally:
            session.close()

        logger.info("[GBP] Total: %d deal signals from %d API calls", len(all_signals), calls_made)
        return all_signals


def run_gbp_offers(
    region: str = "austin_tx",
    max_calls: int = MAX_DAILY_CALLS,
    dry_run: bool = False,
) -> dict:
    """Run the GBP offer collector and ingest results."""
    collector = GBPOfferCollector()
    signals = collector.collect(region=region, max_calls=max_calls, dry_run=dry_run)

    if not dry_run and signals:
        from collectors.meal_deals.ingest import ingest_deal_signals
        stats = ingest_deal_signals(signals, region=region)
        return {
            "signals_found": len(signals),
            "ingest": stats,
        }

    return {
        "signals_found": len(signals),
        "dry_run": dry_run,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Google Business Profile offer collector")
    parser.add_argument("--max-calls", type=int, default=MAX_DAILY_CALLS, help="Max SerpApi calls (default: 100)")
    parser.add_argument("--all", action="store_true", help="Query ALL restaurants (overrides --max-calls)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--region", default="austin_tx")
    args = parser.parse_args()

    max_calls = MAX_BATCH_CALLS if args.all else args.max_calls

    stats = run_gbp_offers(
        region=args.region,
        max_calls=max_calls,
        dry_run=args.dry_run,
    )
    print(f"\n--- GBP Offer Collector Stats ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")
