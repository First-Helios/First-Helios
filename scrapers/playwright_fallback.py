"""
Headless browser fallback scraper using Playwright.

Used when primary API endpoints are blocked (Cloudflare, JS-rendered SPAs).

Two scrapers:
  WorkdayScraper        — Starbucks Workday careers SPA → job listings with real posting dates
  GoogleMapsStoreFinder — Google Maps search → store locations with coordinates

CLI usage:
    python scrapers/playwright_fallback.py --scraper workday --region austin_tx
    python scrapers/playwright_fallback.py --scraper gmaps --chain starbucks --region austin_tx

NOT scheduled automatically — run manually or when primary scrapers return 0 signals.

Depends on: playwright (+ chromium), config.loader, scrapers.base, backend.database
Called by: scrapers/careers_api.py (auto-fallback), CLI
"""

import argparse
import asyncio
import logging
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from playwright.async_api import (
    Page,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import get_chain, get_config, get_region
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Workday Careers Scraper
# ─────────────────────────────────────────────────────────────────────────────


class WorkdayScraper(BaseScraper):
    """Renders the Starbucks Workday SPA with a real headless browser.

    Extracts job listings including posting dates (required for age-decay scoring).

    The direct API (starbucks.wd1.myworkdayjobs.com) returns 422 on all direct HTTP
    requests due to Cloudflare + JS rendering requirement. This is the fallback.

    Depends on: Playwright + Chromium
    Called by: careers_api.py when HTTP approach fails, or directly via CLI
    """

    name = "workday_playwright"

    WORKDAY_URL = (
        "https://starbucks.wd1.myworkdayjobs.com/StarbucksExternalCareerSite"
    )
    SEARCH_QUERY = "Barista"

    def __init__(self, chain_key: str = "starbucks") -> None:
        super().__init__()
        self.chain_key = chain_key

    async def _scrape_async(
        self, region: str, radius_mi: int = 25
    ) -> list[ScraperSignal]:
        signals: list[ScraperSignal] = []
        try:
            region_cfg = get_region(region)
        except KeyError:
            logger.error("[WorkdayScraper] Unknown region: %s", region)
            return []

        location_filter = region_cfg.get("location_string", "Austin, TX")

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-blink-features=AutomationControlled",
                        "--disable-dev-shm-usage",
                    ],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                    locale="en-US",
                )
                page = await context.new_page()

                try:
                    logger.info("[WorkdayScraper] Loading Workday SPA...")
                    await page.goto(
                        self.WORKDAY_URL,
                        wait_until="networkidle",
                        timeout=30000,
                    )
                    await page.wait_for_timeout(2000)

                    # Search for barista positions
                    logger.info(
                        "[WorkdayScraper] Searching for '%s' in '%s'",
                        self.SEARCH_QUERY,
                        location_filter,
                    )
                    search_box = await page.wait_for_selector(
                        'input[data-automation-id="searchBox"], '
                        'input[placeholder*="Search"]',
                        timeout=10000,
                    )
                    if search_box:
                        await search_box.fill(self.SEARCH_QUERY)
                        await page.keyboard.press("Enter")
                        await page.wait_for_timeout(3000)

                    # Filter by location if the UI supports it
                    try:
                        location_input = await page.query_selector(
                            'input[data-automation-id="locationSearchInput"], '
                            'input[placeholder*="Location"]'
                        )
                        if location_input:
                            await location_input.fill(location_filter)
                            await page.wait_for_timeout(1500)
                            suggestion = await page.query_selector(
                                '[data-automation-id="promptOption"]'
                            )
                            if suggestion:
                                await suggestion.click()
                                await page.wait_for_timeout(2000)
                    except PlaywrightTimeout:
                        logger.warning(
                            "[WorkdayScraper] Location filter not found — "
                            "proceeding without it"
                        )

                    # Collect listings across pages
                    page_num = 0
                    while True:
                        page_num += 1
                        logger.info(
                            "[WorkdayScraper] Scraping page %d...", page_num
                        )

                        try:
                            await page.wait_for_selector(
                                '[data-automation-id="jobTitle"], '
                                ".job-title, li[class*='job']",
                                timeout=8000,
                            )
                        except PlaywrightTimeout:
                            logger.info(
                                "[WorkdayScraper] No job cards on page %d — stopping",
                                page_num,
                            )
                            break

                        page_signals = await self._extract_listings_from_page(
                            page, region
                        )
                        signals.extend(page_signals)
                        logger.info(
                            "[WorkdayScraper] Page %d: %d listings",
                            page_num,
                            len(page_signals),
                        )

                        # Try to advance to next page
                        next_btn = await page.query_selector(
                            '[data-automation-id="next"], '
                            'button[aria-label="next page"], .next-page'
                        )
                        if not next_btn:
                            break
                        is_disabled = await next_btn.get_attribute("disabled")
                        if is_disabled:
                            break
                        await next_btn.click()
                        await page.wait_for_timeout(2500)

                except PlaywrightTimeout as e:
                    logger.error("[WorkdayScraper] Timeout: %s", e)
                except Exception as e:
                    logger.error("[WorkdayScraper] Unexpected error: %s", e)
                finally:
                    await browser.close()

        except Exception as e:
            logger.error("[WorkdayScraper] Browser launch failed: %s", e)

        logger.info(
            "[WorkdayScraper] Total: %d listings extracted", len(signals)
        )
        return signals

    async def _extract_listings_from_page(
        self, page: Page, region: str
    ) -> list[ScraperSignal]:
        """Extract ScraperSignal objects from the current page of job results."""
        signals: list[ScraperSignal] = []

        job_cards = await page.query_selector_all(
            '[data-automation-id="jobTitle"], '
            "li[class*='job-listing'], div[class*='job-card']"
        )

        for card in job_cards:
            try:
                title = (await card.inner_text()).strip()
                if not title:
                    continue

                parent = await card.evaluate_handle(
                    "el => el.closest('li') || el.closest('div[class*=job]')"
                )

                # Posting date
                posted_text = ""
                try:
                    date_el = await parent.query_selector(
                        '[data-automation-id="postedOn"], '
                        "[class*='posted'], [class*='date']"
                    )
                    if date_el:
                        posted_text = await date_el.inner_text()
                except Exception:
                    pass

                # Store location
                location_text = ""
                try:
                    loc_el = await parent.query_selector(
                        '[data-automation-id="location"], [class*="location"]'
                    )
                    if loc_el:
                        location_text = await loc_el.inner_text()
                except Exception:
                    pass

                days_old = self._parse_posting_age(posted_text)
                observed_at = datetime.utcnow()
                posted_date = (
                    observed_at - timedelta(days=days_old)
                    if days_old is not None
                    else observed_at
                )

                store_num = (
                    self._extract_store_num(location_text)
                    or f"REGIONAL-{region}"
                )

                signal = ScraperSignal(
                    store_num=store_num,
                    chain=self.chain_key,
                    source=self.name,
                    signal_type="listing",
                    value=1.0,
                    metadata={
                        "title": title,
                        "location": location_text,
                        "posted_text": posted_text,
                        "days_old": days_old,
                        "posted_date": posted_date.isoformat(),
                        "source_url": self.WORKDAY_URL,
                    },
                    observed_at=observed_at,
                    role_title=title,
                    source_url=self.WORKDAY_URL,
                )
                signals.append(signal)

            except Exception as e:
                logger.debug("[WorkdayScraper] Card extraction error: %s", e)
                continue

        return signals

    def _parse_posting_age(self, text: str) -> Optional[int]:
        """Parse posting age from Workday text strings.

        'Posted Today' → 0
        'Posted 3 Days Ago' → 3
        'Posted 30+ Days Ago' → 30
        Returns None if unparseable.
        """
        if not text:
            return None
        text = text.lower()
        if "today" in text:
            return 0
        match = re.search(r"(\d+)\+?\s*day", text)
        if match:
            return int(match.group(1))
        if "week" in text:
            match = re.search(r"(\d+)\+?\s*week", text)
            if match:
                return int(match.group(1)) * 7
            return 7
        if "month" in text:
            return 30
        return None

    def _extract_store_num(self, location_text: str) -> Optional[str]:
        """Extract store number from location strings like 'Store #12345 - Austin, TX'."""
        if not location_text:
            return None
        match = re.search(
            r"(?:store\s*#?|#)(\d{4,6})", location_text, re.IGNORECASE
        )
        if match:
            return f"SB-{match.group(1)}"
        return None

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Sync wrapper for async implementation. BaseScraper interface."""
        try:
            return asyncio.run(self._scrape_async(region, radius_mi))
        except Exception as e:
            logger.error("[WorkdayScraper] scrape() failed: %s", e)
            return []


# ─────────────────────────────────────────────────────────────────────────────
# Google Maps Store Finder
# ─────────────────────────────────────────────────────────────────────────────


class GoogleMapsStoreFinder(BaseScraper):
    """Uses Playwright to search Google Maps for chain store locations in a region.

    Extracts store name, address, rating, review count, and coordinates.

    Primary use: expand store coverage beyond what JobSpy/careers API found.
    Secondary use: get coordinates directly without Nominatim.

    Results are used to:
    1. Upsert stores into tracker.db with real lat/lng
    2. Produce review_score signals for the sentiment sub-scorer

    Depends on: Playwright + Chromium
    Called by: CLI when store coverage is low, or reviews_adapter.py for URL seeding
    """

    name = "gmaps_store_finder"

    GMAPS_SEARCH = "https://www.google.com/maps/search/{query}+{location}"

    def __init__(self, chain_key: str = "starbucks") -> None:
        super().__init__()
        self.chain_key = chain_key

    async def _scrape_async(self, region: str) -> list[dict]:
        """Returns list of store dicts with coordinates and metadata."""
        try:
            region_cfg = get_region(region)
        except KeyError:
            logger.error("[GoogleMapsStoreFinder] Unknown region: %s", region)
            return []

        try:
            chain_cfg = get_chain(self.chain_key)
            chain_name = chain_cfg.get("display_name", self.chain_key)
        except KeyError:
            chain_name = self.chain_key

        location_str = region_cfg.get("display_name", region)
        search_url = self.GMAPS_SEARCH.format(
            query=chain_name.replace(" ", "+"),
            location=location_str.replace(" ", "+").replace(",", ""),
        )

        stores: list[dict] = []

        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/122.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 900},
                )
                page = await context.new_page()

                try:
                    logger.info(
                        "[GoogleMapsStoreFinder] Loading: %s", search_url
                    )
                    await page.goto(
                        search_url, wait_until="networkidle", timeout=30000
                    )
                    await page.wait_for_timeout(3000)

                    # Scroll the results panel to load all locations
                    logger.info(
                        "[GoogleMapsStoreFinder] Scrolling results to "
                        "load all stores..."
                    )
                    await self._scroll_results(page)

                    # Extract all result cards
                    result_links = await page.query_selector_all(
                        'a[href*="/maps/place/"], div[role="article"] a, .Nv2PK a'
                    )
                    logger.info(
                        "[GoogleMapsStoreFinder] Found %d result links",
                        len(result_links),
                    )

                    seen_urls: set[str] = set()
                    for link in result_links:
                        try:
                            href = await link.get_attribute("href")
                            if not href or href in seen_urls:
                                continue
                            if "/maps/place/" not in href:
                                continue
                            seen_urls.add(href)

                            store_data = await self._scrape_store_page(
                                page, href, region
                            )
                            if store_data:
                                stores.append(store_data)
                                logger.info(
                                    "[GoogleMapsStoreFinder] %s — %s",
                                    store_data["store_name"],
                                    store_data["address"],
                                )

                            await page.wait_for_timeout(2000)

                        except Exception as e:
                            logger.debug(
                                "[GoogleMapsStoreFinder] Link error: %s", e
                            )
                            continue

                except Exception as e:
                    logger.error("[GoogleMapsStoreFinder] Error: %s", e)
                finally:
                    await browser.close()

        except Exception as e:
            logger.error(
                "[GoogleMapsStoreFinder] Browser launch failed: %s", e
            )

        logger.info(
            "[GoogleMapsStoreFinder] Total: %d stores found", len(stores)
        )
        return stores

    async def _scroll_results(
        self, page: Page, max_scrolls: int = 15
    ) -> None:
        """Scroll the results panel until no new results appear."""
        panel = await page.query_selector(
            'div[role="feed"], div[aria-label*="Results"]'
        )
        if not panel:
            return
        prev_count = 0
        for _ in range(max_scrolls):
            await panel.evaluate("el => el.scrollBy(0, 500)")
            await page.wait_for_timeout(1200)
            current = await page.query_selector_all(
                'a[href*="/maps/place/"]'
            )
            if len(current) == prev_count:
                break
            prev_count = len(current)

    async def _scrape_store_page(
        self, page: Page, maps_url: str, region: str
    ) -> Optional[dict]:
        """Navigate to a store's Google Maps page and extract structured data."""
        try:
            await page.goto(
                maps_url, wait_until="networkidle", timeout=20000
            )
            await page.wait_for_timeout(1500)

            # Store name
            name_el = await page.query_selector(
                "h1[class*='header'], h1.DUwDvf, h1"
            )
            store_name = (
                (await name_el.inner_text()).strip() if name_el else self.chain_key
            )

            # Address
            address = ""
            addr_el = await page.query_selector(
                'button[data-item-id="address"], '
                '[data-tooltip="Copy address"], [aria-label*="Address"]'
            )
            if addr_el:
                address = (await addr_el.inner_text()).strip()

            # Rating
            rating: Optional[float] = None
            rating_el = await page.query_selector(
                'div[aria-label*="stars"], span[aria-label*="stars"]'
            )
            if rating_el:
                aria = await rating_el.get_attribute("aria-label") or ""
                match = re.search(r"([\d.]+)\s*star", aria)
                if match:
                    rating = float(match.group(1))

            # Review count
            review_count: Optional[int] = None
            review_el = await page.query_selector(
                'span[aria-label*="reviews"], button[aria-label*="reviews"]'
            )
            if review_el:
                text = await review_el.inner_text()
                match = re.search(r"([\d,]+)", text)
                if match:
                    review_count = int(match.group(1).replace(",", ""))

            # Coordinates from URL
            lat, lng = self._extract_coords_from_url(page.url)

            # Permanently closed
            closed = False
            closed_el = await page.query_selector(
                '[aria-label*="Permanently closed"], '
                'span:has-text("Permanently closed")'
            )
            if closed_el:
                closed = True

            if not store_name or not address:
                return None

            # Generate stable store_num from maps URL
            place_match = re.search(r"place/([^/]+)", maps_url)
            store_slug = place_match.group(1) if place_match else store_name
            store_num = (
                f"GMAPS-{self.chain_key.upper()[:2]}-"
                f"{abs(hash(store_slug)) % 100000:05d}"
            )

            return {
                "store_num": store_num,
                "chain": self.chain_key,
                "store_name": store_name,
                "address": address,
                "lat": lat,
                "lng": lng,
                "rating": rating,
                "review_count": review_count,
                "maps_url": maps_url,
                "permanently_closed": closed,
                "region": region,
            }

        except Exception as e:
            logger.debug(
                "[GoogleMapsStoreFinder] Page scrape error for %s: %s",
                maps_url,
                e,
            )
            return None

    def _extract_coords_from_url(
        self, url: str
    ) -> tuple[Optional[float], Optional[float]]:
        """Extract lat/lng from Google Maps URL.

        Pattern: /@lat,lng,zoom or /place/name/@lat,lng
        """
        match = re.search(r"@(-?\d+\.\d+),(-?\d+\.\d+)", url)
        if match:
            return float(match.group(1)), float(match.group(2))
        return None, None

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """BaseScraper interface.

        Produces review_score signals AND side-effects: upserts discovered
        stores with real coordinates into tracker.db.
        """
        try:
            stores = asyncio.run(self._scrape_async(region))
        except Exception as e:
            logger.error("[GoogleMapsStoreFinder] scrape() failed: %s", e)
            return []

        if not stores:
            return []

        # Upsert stores with real coordinates
        from backend.database import Store as StoreModel
        from backend.database import get_session, init_db

        engine = init_db()
        session = get_session(engine)

        try:
            cfg = get_config()
            for store_data in stores:
                if store_data.get("permanently_closed"):
                    continue
                existing = (
                    session.query(StoreModel)
                    .filter_by(store_num=store_data["store_num"])
                    .first()
                )
                if existing:
                    if store_data.get("lat") and store_data.get("lng"):
                        existing.lat = store_data["lat"]
                        existing.lng = store_data["lng"]
                    existing.last_seen = datetime.utcnow()
                else:
                    chain_industry = "unknown"
                    try:
                        chain_cfg = get_chain(store_data["chain"])
                        chain_industry = chain_cfg.get("industry", "unknown")
                    except (KeyError, TypeError):
                        pass

                    store = StoreModel(
                        store_num=store_data["store_num"],
                        chain=store_data["chain"],
                        industry=chain_industry,
                        store_name=store_data["store_name"],
                        address=store_data["address"],
                        lat=store_data.get("lat"),
                        lng=store_data.get("lng"),
                        region=store_data["region"],
                        first_seen=datetime.utcnow(),
                        last_seen=datetime.utcnow(),
                        is_active=True,
                    )
                    session.add(store)
                session.commit()
                logger.info(
                    "[GoogleMapsStoreFinder] Upserted store: %s",
                    store_data["store_name"],
                )

        except Exception as e:
            session.rollback()
            logger.error(
                "[GoogleMapsStoreFinder] DB upsert failed: %s", e
            )
        finally:
            session.close()

        # Produce ScraperSignals for rating data (feeds sentiment scorer)
        signals: list[ScraperSignal] = []
        for store_data in stores:
            if store_data.get("permanently_closed") or not store_data.get(
                "rating"
            ):
                continue
            signal = ScraperSignal(
                store_num=store_data["store_num"],
                chain=store_data["chain"],
                source=self.name,
                signal_type="review_score",
                value=store_data["rating"] / 5.0,  # normalize to 0-1
                metadata={
                    "rating": store_data["rating"],
                    "review_count": store_data["review_count"],
                    "maps_url": store_data["maps_url"],
                    "address": store_data["address"],
                },
                observed_at=datetime.utcnow(),
                source_url=store_data["maps_url"],
            )
            signals.append(signal)

        return signals


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    parser = argparse.ArgumentParser(
        description="Playwright headless fallback scraper"
    )
    parser.add_argument(
        "--scraper",
        choices=["workday", "gmaps"],
        required=True,
        help="Which scraper to run",
    )
    parser.add_argument(
        "--chain",
        default="starbucks",
        help="Chain key from config (default: starbucks)",
    )
    parser.add_argument(
        "--region",
        default="austin_tx",
        help="Region key from config (default: austin_tx)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print signals but do not write to DB",
    )
    args = parser.parse_args()

    if args.scraper == "workday":
        scraper = WorkdayScraper(chain_key=args.chain)
        signals = scraper.scrape(args.region)
    elif args.scraper == "gmaps":
        scraper = GoogleMapsStoreFinder(chain_key=args.chain)
        signals = scraper.scrape(args.region)
    else:
        signals = []

    print(
        f"\n{'DRY RUN — ' if args.dry_run else ''}"
        f"Collected {len(signals)} signals"
    )
    for s in signals[:5]:
        detail = (
            s.metadata.get("title")
            or s.metadata.get("address")
            or ""
        )
        print(
            f"  {s.signal_type} | {s.store_num} | {s.source} | "
            f"value={s.value:.2f} | {detail}"
        )
    if len(signals) > 5:
        print(f"  ... and {len(signals) - 5} more")

    if not args.dry_run and signals:
        from backend.ingest import ingest_signals

        ingest_signals(signals, args.region, args.chain, signals[0].source)
        print(f"\nIngested {len(signals)} signals into tracker.db")
