"""
Starbucks Careers API scraper for ChainStaffingTracker.

Scrapes the Starbucks Workday careers API for job listings in a region.
Produces ScraperSignal objects with listing and wage data.

This is the refactored version of the original scraper/scrape.py.
The legacy CLI delegates to this module.

Depends on: requests, config.loader, scrapers.base, scrapers.geocoding
Called by: scraper/scrape.py (legacy CLI), backend/scheduler.py, server.py
"""

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import requests

# Ensure project root is on sys.path for imports
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import get_chain, get_http_config, get_rate_limit, get_region
from scrapers.base import BaseScraper, ScraperSignal
from scrapers.geocoding import extract_store_num, geocode

logger = logging.getLogger(__name__)


class CareersAPIScraper(BaseScraper):
    """Scrapes Starbucks (and similar Workday) careers APIs.

    Hits the Workday JSON API to list job postings, extracts store IDs,
    posting dates, role titles, and wage data. Produces one ScraperSignal
    per listing.
    """

    name = "CareersAPI"

    def __init__(self, chain_key: str = "starbucks") -> None:
        super().__init__()
        self.chain_key = chain_key
        self.chain_cfg = get_chain(chain_key)
        self.api_cfg = self.chain_cfg["careers_api"]
        self.rate_limit = get_rate_limit("careers_api")
        self.http_cfg = get_http_config()

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Scrape careers API for the given region.

        Args:
            region: Region key from config, e.g. 'austin_tx'.
            radius_mi: Search radius in miles.

        Returns:
            List of ScraperSignal objects. Empty list on failure.
        """
        try:
            region_cfg = get_region(region)
            location = self.api_cfg.get("location_filter", region_cfg["location_string"])
            radius_km = int(radius_mi * 1.60934)

            logger.info(
                "[%s] Scraping %s careers for region=%s location=%s",
                self.name, self.chain_key, region, location,
            )

            all_listings = self._fetch_all_listings(location, radius_km)
            signals = self._convert_to_signals(all_listings, region)

            logger.info(
                "[%s] Found %d listings → %d signals for region=%s",
                self.name, len(all_listings), len(signals), region,
            )

            # If primary API returned nothing, activate Playwright fallback
            if not signals:
                logger.warning(
                    "[%s] Workday API returned 0 signals — "
                    "activating Playwright fallback. This is expected "
                    "if Cloudflare is active.",
                    self.name,
                )
                try:
                    from scrapers.playwright_fallback import WorkdayScraper
                    fallback = WorkdayScraper(chain_key=self.chain_key)
                    signals = fallback.scrape(region, radius_mi)
                    logger.info(
                        "[%s] Playwright fallback returned %d signals",
                        self.name, len(signals),
                    )
                except Exception as fb_err:
                    logger.error(
                        "[%s] Playwright fallback also failed: %s",
                        self.name, fb_err,
                    )
                    signals = []

            return signals

        except Exception as e:
            logger.error("[%s] Failed for region=%s: %s", self.name, region, e)
            return []

    def _fetch_all_listings(
        self, location: str, radius_km: int
    ) -> list[dict[str, Any]]:
        """Paginate through Workday API to get all listings.

        Uses a session to maintain cookies. The Workday CXS API requires
        browser-like headers and session cookies for access. If the API
        returns 422 (common with Cloudflare-protected Workday sites),
        logs a warning and returns empty — callers should rely on JobSpy
        as the primary job listing source.
        """
        api_url = self.api_cfg["api_url"]
        if not api_url:
            logger.warning("[%s] No API URL configured for %s", self.name, self.chain_key)
            return []

        page_size = self.api_cfg.get("page_size", 20)
        all_jobs: list[dict] = []
        offset = 0
        max_pages = 50  # safety limit

        # Build a session with browser-like headers
        session = requests.Session()
        session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": self.http_cfg["user_agent"],
            "Origin": api_url.split("/wday/")[0] if "/wday/" in api_url else None,
            "Referer": self.api_cfg.get("search_url", ""),
        })
        # Remove None-valued headers
        session.headers = {k: v for k, v in session.headers.items() if v}

        # Warm up session — fetch the careers page to obtain cookies
        search_url = self.api_cfg.get("search_url", "")
        if search_url:
            try:
                from backend.tracked_request import log_external
                import time as _t
                _t0 = _t.time()
                session.get(search_url, timeout=self.http_cfg["timeout_seconds"])
                log_external(
                    "careers_workday", "session_warmup",
                    url=search_url, success=True,
                    latency_ms=int((_t.time() - _t0) * 1000),
                )
            except requests.RequestException:
                pass  # proceed anyway

        for page in range(max_pages):
            payload = {
                "appliedFacets": {},
                "limit": page_size,
                "offset": offset,
                "searchText": location,
            }

            try:
                import time as _t
                from backend.tracked_request import log_external
                _t0 = _t.time()
                resp = session.post(
                    api_url,
                    json=payload,
                    timeout=self.http_cfg["timeout_seconds"],
                )
                _lat = int((_t.time() - _t0) * 1000)

                if resp.status_code == 422:
                    log_external(
                        "careers_workday", "job_listing_page",
                        url=api_url, method="POST",
                        success=False, error_message="HTTP 422 — browser JS required",
                        latency_ms=_lat,
                    )
                    logger.warning(
                        "[%s] Workday API returned 422 — site may require "
                        "browser JS execution. Use JobSpy adapter as primary "
                        "listing source instead.",
                        self.name,
                    )
                    break

                resp.raise_for_status()
                data = resp.json()
                _items = len(data.get("jobPostings", []))
                log_external(
                    "careers_workday", "job_listing_page",
                    url=api_url, method="POST",
                    success=True, latency_ms=_lat,
                    data_items=_items,
                    response_bytes=len(resp.content) if resp.content else 0,
                )
            except requests.RequestException as e:
                logger.error("[%s] API request failed (page %d): %s", self.name, page, e)
                break

            job_postings = data.get("jobPostings", [])
            if not job_postings:
                break

            # Filter to location
            for job in job_postings:
                loc_str = job.get("locationsText", "")
                if self._matches_location(loc_str, location):
                    all_jobs.append(job)

            total = data.get("total", 0)
            offset += page_size
            if offset >= total:
                break

            # Rate limiting
            time.sleep(self.rate_limit.get("delay_seconds", 1.0))

        return all_jobs

    def _matches_location(self, loc_text: str, target_location: str) -> bool:
        """Check if a listing's location matches the target region."""
        if not loc_text:
            return False
        # Simple containment check — "Austin" in location text
        target_parts = target_location.replace(",", "").split()
        loc_lower = loc_text.lower()
        return all(part.lower() in loc_lower for part in target_parts[:2])

    def _convert_to_signals(
        self, listings: list[dict], region: str
    ) -> list[ScraperSignal]:
        """Convert raw API listings to ScraperSignal objects."""
        signals: list[ScraperSignal] = []
        prefix = self.chain_cfg.get("store_num_prefix", "XX")

        for listing in listings:
            title = listing.get("title", "")
            external_path = listing.get("externalPath", "")
            loc_text = listing.get("locationsText", "")
            posted_on = listing.get("postedOn", "")

            # Extract store number from title or path
            store_id = self._extract_store_id(title, external_path)
            store_num = extract_store_num(prefix, store_id, loc_text)

            # Parse posting date
            observed_at = datetime.utcnow()
            posted_date = None
            if posted_on:
                try:
                    posted_date = datetime.fromisoformat(
                        posted_on.replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                    observed_at = posted_date
                except (ValueError, TypeError):
                    pass

            # Geocode location
            lat, lng = geocode(loc_text) if loc_text else (None, None)

            # Build signal
            signal = ScraperSignal(
                store_num=store_num,
                chain=self.chain_key,
                source="careers_api",
                signal_type="listing",
                value=1.0,  # each listing = 1 signal
                metadata={
                    "title": title,
                    "external_path": external_path,
                    "location_text": loc_text,
                    "posted_date": posted_date.isoformat() if posted_date else None,
                    "store_name": f"{self.chain_cfg['display_name']} - {loc_text}",
                    "address": loc_text,
                    "lat": lat,
                    "lng": lng,
                },
                observed_at=observed_at,
                role_title=title,
                source_url=(
                    f"{self.api_cfg['search_url']}{external_path}"
                    if external_path and self.api_cfg.get("search_url")
                    else None
                ),
            )
            signals.append(signal)

        return signals

    def _extract_store_id(self, title: str, path: str) -> str | None:
        """Try to extract a store number from listing title or URL path."""
        import re

        # Look for patterns like "Store #12345" or "store-12345"
        patterns = [
            r"(?:store|location)\s*#?\s*(\d{4,6})",
            r"(\d{5})\s*[-–]",
            r"/(\d{5})/",
        ]
        for text in [title, path]:
            for pat in patterns:
                match = re.search(pat, text, re.IGNORECASE)
                if match:
                    return match.group(1)
        return None


def scrape_careers_api(
    region: str = "austin_tx",
    chain: str = "starbucks",
    radius_mi: int = 25,
    ingest: bool = True,
) -> list[ScraperSignal]:
    """Convenience function to scrape and optionally ingest.

    Args:
        region: Region key.
        chain: Chain key.
        radius_mi: Search radius.
        ingest: If True, write signals to tracker.db.

    Returns:
        List of ScraperSignal objects.
    """
    scraper = CareersAPIScraper(chain)
    signals = scraper.scrape(region, radius_mi)

    if ingest and signals:
        from backend.ingest import ingest_signals
        count = ingest_signals(signals, region, chain, "careers_api")
        logger.info("[CareersAPI] Ingested %d signals", count)

    return signals


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    """CLI entry point for careers API scraper."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    parser = argparse.ArgumentParser(description="Scrape chain careers API")
    parser.add_argument("--region", default="austin_tx", help="Region key (default: austin_tx)")
    parser.add_argument("--chain", default="starbucks", help="Chain key (default: starbucks)")
    parser.add_argument("--radius", type=int, default=25, help="Radius in miles (default: 25)")
    parser.add_argument("--no-ingest", action="store_true", help="Skip DB ingestion")
    args = parser.parse_args()

    signals = scrape_careers_api(
        region=args.region,
        chain=args.chain,
        radius_mi=args.radius,
        ingest=not args.no_ingest,
    )
    logger.info("Scraped %d signals", len(signals))


if __name__ == "__main__":
    main()
