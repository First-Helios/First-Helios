"""
Google Maps reviews adapter for ChainStaffingTracker.

Uses google-maps-scraper (noworneverev) for store ratings and review counts.
Falls back to a minimal requests-based approach if the library is unavailable.

Depends on: google-maps-scraper (optional), config.loader, scrapers.base
Called by: backend/scheduler.py, server.py, CLI
"""

import argparse
import logging
import random
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import get_chain, get_http_config, get_rate_limit, get_region
from scrapers.base import BaseScraper, ScraperSignal
from scrapers.geocoding import extract_store_num

logger = logging.getLogger(__name__)

# Staffing-stress keywords extracted from review text.
# Split into tiers: high-signal phrases vs. moderate single words.
_STAFFING_KEYWORDS_HIGH: list[str] = [
    "understaffed", "short staffed", "short-staffed",
    "skeleton crew", "no one working", "only one person",
    "one barista", "one employee", "one worker",
    "drive thru only", "drive-thru only", "lobby closed",
    "closed early", "closed the lobby", "hiring desperately",
    "can't keep staff", "always hiring", "always short",
    "waited 30 minutes", "waited 45 minutes", "waited an hour",
    "forever to get", "took forever",
]
_STAFFING_KEYWORDS_MED: list[str] = [
    "understaffing", "short handed", "short-handed",
    "understated", "wait forever", "waited long",
    "slow service", "overworked", "burned out", "turnover",
    "quitting", "nobody working", "no staff", "no employees",
    "only two", "just one",
]


def _staffing_keyword_score(text: str) -> tuple[float, list[str]]:
    """Return (score 0-1, matched keywords) for staffing-stress content.

    High-signal matches count 2×; moderate count 1×.
    Score is capped at 1.0 after normalizing against a ceiling of 5 hits.
    """
    t = text.lower()
    hits: list[str] = []
    weight = 0.0
    for phrase in _STAFFING_KEYWORDS_HIGH:
        if phrase in t:
            hits.append(phrase)
            weight += 2.0
    for phrase in _STAFFING_KEYWORDS_MED:
        if phrase in t and phrase not in hits:
            hits.append(phrase)
            weight += 1.0
    score = min(1.0, weight / 5.0)
    return score, hits


class ReviewsAdapter(BaseScraper):
    """Scrapes Google Maps for store ratings and review counts.

    Uses the google-maps-scraper library if installed, otherwise
    provides a placeholder that returns no signals (graceful degradation).
    """

    name = "Reviews"

    def __init__(self, chain_key: str = "starbucks") -> None:
        super().__init__()
        self.chain_key = chain_key
        self.chain_cfg = get_chain(chain_key)
        self.rate_limit = get_rate_limit("google_maps")
        self.http_cfg = get_http_config()

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Scrape Google Maps for store reviews in the region.

        Args:
            region: Region key from config.
            radius_mi: Search radius in miles.

        Returns:
            List of ScraperSignal objects. Empty on failure.
        """
        try:
            region_cfg = get_region(region)
            search_query = self.chain_cfg.get(
                "maps_search_query",
                f"{self.chain_cfg['display_name']} {region_cfg['location_string']}",
            )

            logger.info(
                "[%s] Searching Google Maps: '%s'", self.name, search_query
            )

            # Try google-maps-scraper library first
            signals = self._scrape_via_library(search_query, region)
            if signals:
                return signals

            # Fallback: use Nominatim to find known locations and skip reviews
            logger.info(
                "[%s] google-maps-scraper not available; returning empty (graceful degradation)",
                self.name,
            )
            return []

        except Exception as e:
            logger.error("[%s] Failed for region=%s: %s", self.name, region, e)
            return []

    def _scrape_via_library(
        self, search_query: str, region: str
    ) -> list[ScraperSignal]:
        """Try scraping via google-maps-scraper library."""
        try:
            import asyncio
            from gmaps_scraper import GoogleMapsScraper, ScrapeConfig

            config = ScrapeConfig(language="en", headless=True)

            async def _do_scrape():
                signals: list[ScraperSignal] = []
                async with GoogleMapsScraper(config) as scraper:
                    import time as _t
                    from backend.tracked_request import log_external
                    _t0 = _t.time()
                    result = await scraper.scrape_search(search_query)
                    _lat_ms = int((_t.time() - _t0) * 1000)
                    _place_count = len(result.places) if result and result.places else 0
                    log_external(
                        "gmaps_scraper", "search_scrape",
                        url="https://maps.google.com/",
                        success=_place_count > 0, latency_ms=_lat_ms,
                        data_items=_place_count,
                        params={"query": search_query},
                    )
                    if not result or not result.places:
                        return signals

                    prefix = self.chain_cfg.get("store_num_prefix", "XX")

                    for place in result.places:
                        store_num = extract_store_num(
                            prefix, None, place.address or place.name
                        )

                        signal = ScraperSignal(
                            store_num=store_num,
                            chain=self.chain_key,
                            source="google_maps",
                            signal_type="review_score",
                            value=place.rating or 0.0,
                            metadata={
                                "store_name": place.name or "",
                                "address": place.address or "",
                                "lat": place.latitude,
                                "lng": place.longitude,
                                "rating": place.rating,
                                "review_count": place.review_count,
                                "permanently_closed": getattr(place, "permanently_closed", False),
                            },
                            observed_at=datetime.utcnow(),
                            source_url=getattr(place, "url", None),
                        )
                        signals.append(signal)

                        # ── Staffing keyword NLP ──────────────────────
                        # If the library returns individual review snippets,
                        # score them for staffing-stress language.
                        review_texts: list[str] = []
                        if hasattr(place, "reviews") and place.reviews:
                            review_texts = [
                                r.text if hasattr(r, "text") else str(r)
                                for r in place.reviews
                                if r
                            ]
                        elif hasattr(place, "review_text") and place.review_text:
                            review_texts = [place.review_text]

                        if review_texts:
                            combined_text = " ".join(review_texts)
                            kw_score, matched_kws = _staffing_keyword_score(combined_text)
                            if kw_score > 0:
                                kw_signal = ScraperSignal(
                                    store_num=store_num,
                                    chain=self.chain_key,
                                    source="google_maps",
                                    signal_type="staffing_keywords",
                                    value=kw_score,
                                    metadata={
                                        "store_name": place.name or "",
                                        "address": place.address or "",
                                        "lat": place.latitude,
                                        "lng": place.longitude,
                                        "matched_keywords": matched_kws,
                                        "keyword_count": len(matched_kws),
                                        "review_sample_count": len(review_texts),
                                    },
                                    observed_at=datetime.utcnow(),
                                    source_url=getattr(place, "url", None),
                                )
                                signals.append(kw_signal)

                        # Rate limiting
                        delay_min = self.rate_limit.get("delay_min_seconds", 3.0)
                        delay_max = self.rate_limit.get("delay_max_seconds", 5.0)
                        await asyncio.sleep(random.uniform(delay_min, delay_max))

                return signals

            return asyncio.run(_do_scrape())

        except ImportError:
            logger.info("[%s] google-maps-scraper not installed", self.name)
            return []
        except Exception as e:
            logger.error("[%s] Library scrape failed: %s", self.name, e)
            return []


def scrape_reviews(
    chain: str = "starbucks",
    region: str = "austin_tx",
    radius_mi: int = 25,
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Convenience function to scrape reviews and optionally ingest."""
    adapter = ReviewsAdapter(chain)
    signals = adapter.scrape(region, radius_mi)

    if ingest and signals:
        from backend.ingest import ingest_signals
        count = ingest_signals(signals, region, chain, "google_maps")
        logger.info("[Reviews] Ingested %d signals", count)

    return signals


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Scrape Google Maps reviews")
    parser.add_argument("--chain", default="starbucks", help="Chain key")
    parser.add_argument("--region", default="austin_tx", help="Region key")
    parser.add_argument("--radius", type=int, default=25)
    parser.add_argument("--no-ingest", action="store_true")
    args = parser.parse_args()

    signals = scrape_reviews(
        chain=args.chain,
        region=args.region,
        radius_mi=args.radius,
        ingest=not args.no_ingest,
    )
    logger.info("Scraped %d signals", len(signals))


if __name__ == "__main__":
    main()
