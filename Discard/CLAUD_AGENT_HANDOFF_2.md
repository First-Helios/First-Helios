# HANDOFF_SESSION5.md — Geocoding + Headless Scraper Fallback

**Date:** 2026-03-19  
**Project root:** `/home/fortune/CodeProjects/First-Helios`  
**Venv:** `.venv/` (Python 3.12)  
**Picks up from:** `CLAUDE_AGENT_HANDOFF.md` (Session 4)

---

## Read These First

```bash
cat .github/agents/AGENT.md          # full project spec — read before anything else
cat CLAUDE_AGENT_HANDOFF.md          # session 4 state — what was built, what's broken
```

Then verify the current DB state before touching any code:

```bash
cd /home/fortune/CodeProjects/First-Helios
source .venv/bin/activate

python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
for t in ['stores','signals','snapshots','scores','wage_index']:
    n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
    print(f'{t}: {n} rows')

# Check how many stores have null coords
null_coords = conn.execute(
    'SELECT COUNT(*) FROM stores WHERE lat IS NULL OR lng IS NULL'
).fetchone()[0]
print(f'stores with null coords: {null_coords}')

# Sample the stores table
print()
for row in conn.execute('SELECT store_num, store_name, address, lat, lng FROM stores LIMIT 5'):
    print(row)
conn.close()
"
```

Expected state coming in:
- `stores`: 10 rows, **all with `lat=None, lng=None`**
- `signals`: 67 rows
- `scores`: 36 rows (but 30% of each score is fabricated — isolation + local_alternatives both defaulting to 50)
- `wage_index`: 9 rows, **all `is_chain=False`** (no chain wage baseline)

---

## This Session's Two Goals

### Goal 1 — Geocoding (fixes the map + fixes two broken score components)

Every store has null coordinates. The Leaflet map is blank. The isolation score (20% of targeting score) and local_alternatives score (10%) both default to 50 because haversine math requires coordinates. **30% of every targeting score is currently a fabricated neutral value.**

Fix: implement `scrapers/geocoding.py` using Nominatim (free, no key, already the right choice for this project). Then geocode all existing stores in the DB and wire geocoding into the ingestion pipeline so future stores are geocoded on insert.

### Goal 2 — Headless Playwright Fallback Scraper (fixes careers API + expands store coverage)

The Starbucks Workday API (`starbucks.wd1.myworkdayjobs.com`) returns HTTP 422 on every direct request because it's behind Cloudflare and requires a full browser JS runtime. The previous agent tried `cloudscraper`, session cookies, and browser-like headers — all failed.

Playwright headless browser rendering is the correct fix. This is also the pattern to use whenever any primary API gets blocked — it's the fallback that keeps data flowing.

Two immediate applications:
1. **Workday careers page** — renders the SPA, extracts job listings with real posting dates (needed for age-decay scoring)
2. **Google Maps store finder** — expands from 9 stores to the full ~35 Austin Starbucks locations, and gets coordinates directly without Nominatim

---

## Priority 1 — Implement Geocoding

### What exists

`scrapers/geocoding.py` (106 lines) has a `geocode()` function that is a stub returning `(None, None)`. The structure is there, the implementation is missing.

### What to build

#### Step 1 — Implement `geocode()` in `scrapers/geocoding.py`

Replace the stub with a working Nominatim implementation. Install `geopy` if not already present:

```bash
pip install geopy
# Add to RUNBOOK.md install command
```

```python
from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError
import time
import logging

logger = logging.getLogger(__name__)

_geolocator = Nominatim(user_agent="ChainStaffingTracker/1.0 (community labor research)")

def geocode(address: str) -> tuple[float | None, float | None]:
    """
    Geocode an address string to (lat, lng).
    Uses Nominatim (OpenStreetMap). Free, no API key required.
    Rate limit: 1 request/second — enforced by sleep below.
    Returns (None, None) on failure — never raises.
    """
    if not address or not address.strip():
        return None, None
    try:
        time.sleep(1.1)  # Nominatim hard rate limit: 1 req/sec
        location = _geolocator.geocode(address, timeout=10)
        if location:
            logger.info(f"[geocoding] OK: {address!r} → ({location.latitude:.4f}, {location.longitude:.4f})")
            return location.latitude, location.longitude
        else:
            # Nominatim couldn't resolve — try a simplified version
            simplified = _simplify_address(address)
            if simplified != address:
                time.sleep(1.1)
                location = _geolocator.geocode(simplified, timeout=10)
                if location:
                    logger.info(f"[geocoding] OK (simplified): {simplified!r} → ({location.latitude:.4f}, {location.longitude:.4f})")
                    return location.latitude, location.longitude
            logger.warning(f"[geocoding] No result for: {address!r}")
            return None, None
    except (GeocoderTimedOut, GeocoderServiceError) as e:
        logger.error(f"[geocoding] Service error for {address!r}: {e}")
        return None, None
    except Exception as e:
        logger.error(f"[geocoding] Unexpected error for {address!r}: {e}")
        return None, None

def _simplify_address(address: str) -> str:
    """
    Strip unit numbers, suite info, etc. to improve Nominatim match rate.
    e.g. '123 Main St, Suite 100, Austin, TX 78701' → '123 Main St, Austin, TX'
    """
    import re
    # Remove suite/unit/ste/apt designators
    address = re.sub(r',?\s*(suite|ste|unit|apt|#)\s*[\w-]+', '', address, flags=re.IGNORECASE)
    # Remove ZIP codes (Nominatim is better without them sometimes)
    address = re.sub(r'\b\d{5}(-\d{4})?\b', '', address)
    return address.strip().strip(',').strip()
```

#### Step 2 — Backfill all existing stores with null coordinates

Create a one-time script `scripts/backfill_geocoding.py`:

```python
"""
One-time script to geocode all stores in tracker.db that have null coordinates.
Run once after implementing geocoding. Safe to re-run — skips already-geocoded stores.

Usage:
    python scripts/backfill_geocoding.py [--dry-run]
"""
import sys, argparse, logging
sys.path.insert(0, '.')

from backend.database import get_session, Store
from scrapers.geocoding import geocode

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true', help='Print what would be geocoded, do not write')
    args = parser.parse_args()

    with get_session() as session:
        stores = session.query(Store).filter(
            (Store.lat == None) | (Store.lng == None)
        ).all()

        logger.info(f"Found {len(stores)} stores with null coordinates")

        updated = 0
        failed = 0

        for store in stores:
            if not store.address:
                logger.warning(f"[{store.store_num}] No address — skipping")
                failed += 1
                continue

            lat, lng = geocode(store.address)

            if lat is not None and lng is not None:
                if not args.dry_run:
                    store.lat = lat
                    store.lng = lng
                    session.commit()
                logger.info(f"[{store.store_num}] {store.store_name} → ({lat:.4f}, {lng:.4f})")
                updated += 1
            else:
                logger.warning(f"[{store.store_num}] FAILED: {store.address!r}")
                failed += 1

        logger.info(f"\nDone. Updated: {updated}  Failed: {failed}")
        if args.dry_run:
            logger.info("(dry-run — no changes written)")

if __name__ == "__main__":
    main()
```

Run it:
```bash
# Dry run first to see what would happen
python scripts/backfill_geocoding.py --dry-run

# Then for real (will take ~12 seconds for 10 stores due to 1.1s rate limit)
python scripts/backfill_geocoding.py
```

#### Step 3 — Wire geocoding into `backend/ingest.py`

Find the section in `ingest.py` where new `Store` rows are created. Add geocoding on insert when coordinates are not provided:

```python
# In the store upsert logic — after building the Store object, before session.add()
if store.lat is None and store.address:
    from scrapers.geocoding import geocode
    store.lat, store.lng = geocode(store.address)
```

This ensures future stores from any scraper get coordinates automatically.

#### Step 4 — Verify geocoding worked

```bash
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
rows = conn.execute('SELECT store_num, store_name, lat, lng FROM stores ORDER BY lat').fetchall()
for r in rows:
    status = '✅' if r[2] is not None else '❌ NULL'
    print(f'{status}  {r[0]}  {r[1][:40]}  ({r[2]}, {r[3]})')
conn.close()
"
```

All rows should show coordinates. Then check the map:
```bash
python server.py --debug
# Open http://localhost:8765 — markers should appear on Austin map
```

#### Step 5 — Re-score after geocoding

The isolation and local_alternatives scores were defaulting to 50. With real coordinates, re-run scoring:

```python
python3 -c "
import sys; sys.path.insert(0, '.')
from backend.scoring.engine import compute_all_scores
results = compute_all_scores('austin_tx', chain='starbucks')
from collections import Counter
tiers = [r.tier for r in results]
print('Score distribution after geocoding fix:')
print(Counter(tiers))
"
```

The distribution should shift from the pre-geocoding values as isolation scores become real.

---

## Priority 2 — Headless Playwright Fallback Scraper

### Architecture

The fallback scraper has two distinct jobs that share one Playwright implementation:

```
scrapers/playwright_fallback.py
├── WorkdayScraper          — renders starbucks.wd1.myworkdayjobs.com SPA
│   └── produces ScraperSignal(signal_type="listing") with real posting dates
└── GoogleMapsStoreFinder   — finds all Starbucks locations in Austin with coords
    └── produces store records with lat/lng — bypasses Nominatim entirely
```

The fallback scraper is NOT a replacement for the primary pipeline. It runs:
- When `careers_api.py` returns 0 signals (Workday blocked)
- When store discovery needs to expand beyond what JobSpy found (9 → ~35 stores)
- On demand via CLI only — it is NOT added to the APScheduler (too slow and too detectable for daily automated runs)

### Install Playwright if not already done

```bash
pip install playwright
playwright install chromium --with-deps
# Verify:
python -c "from playwright.sync_api import sync_playwright; print('Playwright OK')"
```

### Build `scrapers/playwright_fallback.py`

Create this file from scratch. Two classes, one file.

#### Class 1 — WorkdayScraper

```python
"""
scrapers/playwright_fallback.py

Headless browser fallback scraper using Playwright.
Used when primary API endpoints are blocked (Cloudflare, JS-rendered SPAs).

Two scrapers:
  WorkdayScraper        — Starbucks Workday careers SPA → job listings with real posting dates
  GoogleMapsStoreFinder — Google Maps search → store locations with coordinates

CLI usage:
    python scrapers/playwright_fallback.py --scraper workday --region austin_tx
    python scrapers/playwright_fallback.py --scraper gmaps --chain starbucks --region austin_tx

NOT scheduled automatically — run manually or when primary scrapers return 0 signals.
"""

import asyncio
import logging
import re
import time
import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from playwright.async_api import async_playwright, Page, Browser, TimeoutError as PlaywrightTimeout

sys.path.insert(0, '.')
from scrapers.base import BaseScraper, ScraperSignal
from config.loader import get_config

logger = logging.getLogger(__name__)
config = get_config()


# ─────────────────────────────────────────────
# Workday Careers Scraper
# ─────────────────────────────────────────────

class WorkdayScraper(BaseScraper):
    """
    Renders the Starbucks Workday SPA with a real headless browser.
    Extracts job listings including posting dates (required for age-decay scoring).
    
    The direct API (starbucks.wd1.myworkdayjobs.com) returns 422 on all direct HTTP
    requests due to Cloudflare + JS rendering requirement. This is the fallback.
    
    Depends on: Playwright + Chromium
    Called by: careers_api.py when HTTP approach fails, or directly via CLI
    """

    name = "workday_playwright"
    chain = "starbucks"

    WORKDAY_URL = "https://starbucks.wd1.myworkdayjobs.com/StarbucksExternalCareerSite"
    SEARCH_QUERY = "Barista"

    async def _scrape_async(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        signals = []
        region_config = config.regions.get(region)
        if not region_config:
            logger.error(f"[WorkdayScraper] Unknown region: {region}")
            return []

        location_filter = region_config.get("search_string", "Austin, TX")

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ]
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
                logger.info(f"[WorkdayScraper] Loading Workday SPA...")
                await page.goto(self.WORKDAY_URL, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # Search for barista positions
                logger.info(f"[WorkdayScraper] Searching for '{self.SEARCH_QUERY}' in '{location_filter}'")
                search_box = await page.wait_for_selector(
                    'input[data-automation-id="searchBox"], input[placeholder*="Search"]',
                    timeout=10000
                )
                await search_box.fill(self.SEARCH_QUERY)
                await page.keyboard.press("Enter")
                await page.wait_for_timeout(3000)

                # Filter by location if the UI supports it
                try:
                    location_input = await page.query_selector(
                        'input[data-automation-id="locationSearchInput"], input[placeholder*="Location"]'
                    )
                    if location_input:
                        await location_input.fill(location_filter)
                        await page.wait_for_timeout(1500)
                        # Click first autocomplete suggestion
                        suggestion = await page.query_selector('[data-automation-id="promptOption"]')
                        if suggestion:
                            await suggestion.click()
                            await page.wait_for_timeout(2000)
                except PlaywrightTimeout:
                    logger.warning("[WorkdayScraper] Location filter not found — proceeding without it")

                # Collect all listings across pages
                page_num = 0
                while True:
                    page_num += 1
                    logger.info(f"[WorkdayScraper] Scraping page {page_num}...")

                    # Wait for job cards
                    try:
                        await page.wait_for_selector(
                            '[data-automation-id="jobTitle"], .job-title, li[class*="job"]',
                            timeout=8000
                        )
                    except PlaywrightTimeout:
                        logger.info(f"[WorkdayScraper] No job cards found on page {page_num} — stopping")
                        break

                    page_signals = await self._extract_listings_from_page(page, region)
                    signals.extend(page_signals)
                    logger.info(f"[WorkdayScraper] Page {page_num}: {len(page_signals)} listings")

                    # Try to advance to next page
                    next_btn = await page.query_selector(
                        '[data-automation-id="next"], button[aria-label="next page"], .next-page'
                    )
                    if not next_btn:
                        break
                    is_disabled = await next_btn.get_attribute("disabled")
                    if is_disabled:
                        break
                    await next_btn.click()
                    await page.wait_for_timeout(2500)

            except PlaywrightTimeout as e:
                logger.error(f"[WorkdayScraper] Timeout: {e}")
            except Exception as e:
                logger.error(f"[WorkdayScraper] Unexpected error: {e}")
            finally:
                await browser.close()

        logger.info(f"[WorkdayScraper] Total: {len(signals)} listings extracted")
        return signals

    async def _extract_listings_from_page(self, page: Page, region: str) -> list[ScraperSignal]:
        """Extract ScraperSignal objects from the current page of job results."""
        signals = []

        # Workday job card selectors — try multiple patterns
        job_cards = await page.query_selector_all(
            '[data-automation-id="jobTitle"], li[class*="job-listing"], div[class*="job-card"]'
        )

        for card in job_cards:
            try:
                title = await card.inner_text()
                title = title.strip()
                if not title:
                    continue

                # Try to get the parent container for more metadata
                parent = await card.evaluate_handle("el => el.closest('li') || el.closest('div[class*=job]')")

                # Posting date — look for date strings near the card
                posted_text = ""
                try:
                    date_el = await parent.query_selector(
                        '[data-automation-id="postedOn"], [class*="posted"], [class*="date"]'
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

                # Parse posting age from text like "Posted 3 Days Ago" or "Today"
                days_old = self._parse_posting_age(posted_text)
                observed_at = datetime.utcnow()
                if days_old is not None:
                    # Reconstruct approximate posting date
                    posted_date = observed_at - timedelta(days=days_old)
                else:
                    posted_date = observed_at

                # Try to extract store number from location
                store_num = self._extract_store_num(location_text) or f"REGIONAL-{region}"

                signal = ScraperSignal(
                    store_num=store_num,
                    chain="starbucks",
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
                logger.debug(f"[WorkdayScraper] Card extraction error: {e}")
                continue

        return signals

    def _parse_posting_age(self, text: str) -> Optional[int]:
        """
        Parse posting age from Workday text strings.
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
        match = re.search(r'(\d+)\+?\s*day', text)
        if match:
            return int(match.group(1))
        if "week" in text:
            match = re.search(r'(\d+)\+?\s*week', text)
            if match:
                return int(match.group(1)) * 7
            return 7
        if "month" in text:
            return 30
        return None

    def _extract_store_num(self, location_text: str) -> Optional[str]:
        """Extract store number from location strings like 'Store #12345 - Austin, TX'"""
        if not location_text:
            return None
        match = re.search(r'(?:store\s*#?|#)(\d{4,6})', location_text, re.IGNORECASE)
        if match:
            return f"SB-{match.group(1)}"
        return None

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """Sync wrapper for async implementation. BaseScraper interface."""
        return asyncio.run(self._scrape_async(region, radius_mi))


# ─────────────────────────────────────────────
# Google Maps Store Finder
# ─────────────────────────────────────────────

class GoogleMapsStoreFinder(BaseScraper):
    """
    Uses Playwright to search Google Maps for chain store locations in a region.
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
    chain = "starbucks"  # overridden by CLI --chain arg

    GMAPS_SEARCH = "https://www.google.com/maps/search/{query}+{location}"

    async def _scrape_async(self, chain: str, region: str) -> list[dict]:
        """
        Returns list of store dicts:
        {store_num, chain, store_name, address, lat, lng, rating, review_count, maps_url}
        """
        region_config = config.regions.get(region)
        if not region_config:
            logger.error(f"[GoogleMapsStoreFinder] Unknown region: {region}")
            return []

        chain_config = config.chains.get(chain)
        chain_name = chain_config.get("name", chain) if chain_config else chain
        location_str = region_config.get("label", region)

        search_url = self.GMAPS_SEARCH.format(
            query=chain_name.replace(" ", "+"),
            location=location_str.replace(" ", "+").replace(",", "")
        )

        stores = []

        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"]
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
                logger.info(f"[GoogleMapsStoreFinder] Loading: {search_url}")
                await page.goto(search_url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(3000)

                # Scroll the results panel to load all locations
                logger.info("[GoogleMapsStoreFinder] Scrolling results to load all stores...")
                await self._scroll_results(page)

                # Extract all result cards
                result_links = await page.query_selector_all(
                    'a[href*="/maps/place/"], div[role="article"] a, .Nv2PK a'
                )
                logger.info(f"[GoogleMapsStoreFinder] Found {len(result_links)} result links")

                seen_urls = set()
                for link in result_links:
                    try:
                        href = await link.get_attribute("href")
                        if not href or href in seen_urls:
                            continue
                        if "/maps/place/" not in href:
                            continue
                        seen_urls.add(href)

                        # Visit each store's detail page
                        store_data = await self._scrape_store_page(page, href, chain, region)
                        if store_data:
                            stores.append(store_data)
                            logger.info(f"[GoogleMapsStoreFinder] ✅ {store_data['store_name']} — {store_data['address']}")

                        await page.wait_for_timeout(2000)  # polite delay

                    except Exception as e:
                        logger.debug(f"[GoogleMapsStoreFinder] Link error: {e}")
                        continue

            except Exception as e:
                logger.error(f"[GoogleMapsStoreFinder] Error: {e}")
            finally:
                await browser.close()

        logger.info(f"[GoogleMapsStoreFinder] Total: {len(stores)} stores found")
        return stores

    async def _scroll_results(self, page: Page, max_scrolls: int = 15):
        """Scroll the results panel until no new results appear."""
        panel = await page.query_selector('div[role="feed"], div[aria-label*="Results"]')
        if not panel:
            return
        prev_count = 0
        for _ in range(max_scrolls):
            await panel.evaluate("el => el.scrollBy(0, 500)")
            await page.wait_for_timeout(1200)
            current = await page.query_selector_all('a[href*="/maps/place/"]')
            if len(current) == prev_count:
                break
            prev_count = len(current)

    async def _scrape_store_page(self, page: Page, maps_url: str, chain: str, region: str) -> Optional[dict]:
        """Navigate to a store's Google Maps page and extract structured data."""
        try:
            await page.goto(maps_url, wait_until="networkidle", timeout=20000)
            await page.wait_for_timeout(1500)

            # Store name
            name_el = await page.query_selector('h1[class*="header"], h1.DUwDvf, h1')
            store_name = (await name_el.inner_text()).strip() if name_el else chain

            # Address
            address = ""
            addr_el = await page.query_selector(
                'button[data-item-id="address"], [data-tooltip="Copy address"], [aria-label*="Address"]'
            )
            if addr_el:
                address = (await addr_el.inner_text()).strip()

            # Rating
            rating = None
            rating_el = await page.query_selector('div[aria-label*="stars"], span[aria-label*="stars"]')
            if rating_el:
                aria = await rating_el.get_attribute("aria-label") or ""
                match = re.search(r'([\d.]+)\s*star', aria)
                if match:
                    rating = float(match.group(1))

            # Review count
            review_count = None
            review_el = await page.query_selector(
                'span[aria-label*="reviews"], button[aria-label*="reviews"]'
            )
            if review_el:
                text = await review_el.inner_text()
                match = re.search(r'([\d,]+)', text)
                if match:
                    review_count = int(match.group(1).replace(",", ""))

            # Coordinates — extract from URL (Google encodes them there)
            lat, lng = self._extract_coords_from_url(page.url)

            # Permanently closed
            closed = False
            closed_el = await page.query_selector('[aria-label*="Permanently closed"], span:has-text("Permanently closed")')
            if closed_el:
                closed = True

            if not store_name or not address:
                return None

            # Generate a stable store_num from the maps URL
            place_match = re.search(r'place/([^/]+)', maps_url)
            store_slug = place_match.group(1) if place_match else store_name
            store_num = f"GMAPS-{chain.upper()[:2]}-{abs(hash(store_slug)) % 100000:05d}"

            return {
                "store_num": store_num,
                "chain": chain,
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
            logger.debug(f"[GoogleMapsStoreFinder] Page scrape error for {maps_url}: {e}")
            return None

    def _extract_coords_from_url(self, url: str) -> tuple[Optional[float], Optional[float]]:
        """
        Extract lat/lng from Google Maps URL.
        Pattern: /@lat,lng,zoom or /place/name/@lat,lng
        """
        match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', url)
        if match:
            return float(match.group(1)), float(match.group(2))
        return None, None

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        """
        BaseScraper interface. For GoogleMapsStoreFinder, produces review_score signals
        AND side-effects: upserts discovered stores with real coordinates into tracker.db.
        """
        stores = asyncio.run(self._scrape_async(self.chain, region))

        if not stores:
            return []

        # Upsert stores with real coordinates
        from backend.database import get_session, Store
        from datetime import datetime

        with get_session() as session:
            for store_data in stores:
                if store_data.get("permanently_closed"):
                    continue
                existing = session.query(Store).filter_by(store_num=store_data["store_num"]).first()
                if existing:
                    # Update coordinates if we got them
                    if store_data.get("lat") and store_data.get("lng"):
                        existing.lat = store_data["lat"]
                        existing.lng = store_data["lng"]
                    existing.last_seen = datetime.utcnow()
                else:
                    store = Store(
                        store_num=store_data["store_num"],
                        chain=store_data["chain"],
                        industry=config.chains.get(store_data["chain"], {}).get("industry", "unknown"),
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
                logger.info(f"[GoogleMapsStoreFinder] Upserted store: {store_data['store_name']}")

        # Produce ScraperSignals for rating data (feeds sentiment scorer)
        signals = []
        for store_data in stores:
            if store_data.get("permanently_closed") or not store_data.get("rating"):
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
```

#### CLI entry point (add at bottom of `playwright_fallback.py`)

```python
# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    from backend.ingest import ingest_signals

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    parser = argparse.ArgumentParser(description="Playwright headless fallback scraper")
    parser.add_argument(
        "--scraper",
        choices=["workday", "gmaps"],
        required=True,
        help="Which scraper to run"
    )
    parser.add_argument("--chain", default="starbucks", help="Chain key from config (default: starbucks)")
    parser.add_argument("--region", default="austin_tx", help="Region key from config (default: austin_tx)")
    parser.add_argument("--dry-run", action="store_true", help="Print signals but do not write to DB")
    args = parser.parse_args()

    if args.scraper == "workday":
        scraper = WorkdayScraper()
        scraper.chain = args.chain
        signals = scraper.scrape(args.region)
    elif args.scraper == "gmaps":
        scraper = GoogleMapsStoreFinder()
        scraper.chain = args.chain
        signals = scraper.scrape(args.region)

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Collected {len(signals)} signals")
    for s in signals[:5]:
        print(f"  {s.signal_type} | {s.store_num} | {s.source} | value={s.value:.2f} | {s.metadata.get('title') or s.metadata.get('address') or ''}")
    if len(signals) > 5:
        print(f"  ... and {len(signals) - 5} more")

    if not args.dry_run and signals:
        ingest_signals(signals)
        print(f"\nIngested {len(signals)} signals into tracker.db")
```

---

## Wiring the Fallback into `careers_api.py`

The fallback should trigger automatically when the Workday API returns 0 results. Find the `scrape()` method in `scrapers/careers_api.py` and add this at the end:

```python
def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
    signals = self._try_workday_api(region, radius_mi)  # existing logic

    if not signals:
        logger.warning(
            "[CareersAPI] Workday API returned 0 signals — "
            "activating Playwright fallback. This is expected if Cloudflare is active."
        )
        try:
            from scrapers.playwright_fallback import WorkdayScraper
            fallback = WorkdayScraper()
            signals = fallback.scrape(region, radius_mi)
            logger.info(f"[CareersAPI] Playwright fallback returned {len(signals)} signals")
        except Exception as e:
            logger.error(f"[CareersAPI] Playwright fallback also failed: {e}")
            signals = []

    return signals
```

---

## Verification Sequence

Run this in order after completing both priorities:

```bash
cd /home/fortune/CodeProjects/First-Helios
source .venv/bin/activate

# 1. Geocoding backfill
python scripts/backfill_geocoding.py --dry-run   # inspect first
python scripts/backfill_geocoding.py             # write coords

# 2. Verify all stores have coordinates
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
null = conn.execute('SELECT COUNT(*) FROM stores WHERE lat IS NULL').fetchone()[0]
total = conn.execute('SELECT COUNT(*) FROM stores').fetchone()[0]
print(f'Stores with coordinates: {total - null}/{total}')
if null > 0:
    rows = conn.execute('SELECT store_num, address FROM stores WHERE lat IS NULL').fetchall()
    print('Still missing:')
    for r in rows: print(f'  {r}')
conn.close()
"

# 3. Re-score with real coordinates
python3 -c "
import sys; sys.path.insert(0, '.')
from backend.scoring.engine import compute_all_scores
from collections import Counter
results = compute_all_scores('austin_tx', chain='starbucks')
tiers = Counter(r.tier for r in results)
print('Score distribution after geocoding:')
for tier, count in sorted(tiers.items()):
    print(f'  {tier}: {count} ({count/len(results)*100:.0f}%)')
"

# 4. Playwright fallback — gmaps store finder (expands coverage)
python scrapers/playwright_fallback.py --scraper gmaps --chain starbucks --region austin_tx --dry-run
# If dry run looks good:
python scrapers/playwright_fallback.py --scraper gmaps --chain starbucks --region austin_tx

# 5. Check store count after gmaps run
python3 -c "
import sqlite3
conn = sqlite3.connect('data/tracker.db')
n = conn.execute('SELECT COUNT(*) FROM stores WHERE chain=\"starbucks\"').fetchone()[0]
null = conn.execute('SELECT COUNT(*) FROM stores WHERE lat IS NULL').fetchone()[0]
print(f'Starbucks stores: {n} (target: ~35)')
print(f'Stores still missing coords: {null}')
conn.close()
"

# 6. Playwright fallback — Workday careers
python scrapers/playwright_fallback.py --scraper workday --chain starbucks --region austin_tx --dry-run
# If dry run returns listings with posting dates:
python scrapers/playwright_fallback.py --scraper workday --chain starbucks --region austin_tx

# 7. Map renders with markers
python server.py &
sleep 2
# Open http://localhost:8765 — should see ~35 markers on Austin map

# 8. Targeting output looks real (not all defaulting to 50)
curl -s "http://localhost:8765/api/targeting?industry=coffee_cafe&region=austin_tx&limit=5" \
  | python3 -m json.tool \
  | grep -E '"isolation|wage_gap|targeting_score|address"'
```

---

## What Done Looks Like

| Check | Before This Session | After This Session |
|-------|--------------------|--------------------|
| Stores with coordinates | 0 / 10 | 10 / 10 (Nominatim) |
| Total stores in DB | 10 | ~35 (Google Maps finder) |
| Map markers visible | ❌ Blank map | ✅ ~35 markers on Austin |
| Isolation score | Defaults to 50 (fake) | Real haversine distances |
| Local alternatives score | Defaults to 50 (fake) | Real density calculations |
| Careers API fallback | Returns 0, fails silently | Activates Playwright, gets listings + dates |
| Age decay scoring | Blind (no real posting dates) | Real dates from Workday SPA |

---

## Do Not Touch

Per `AGENT.md`:
- `data/spiritpool.db` — never write to it
- `spiritpool/` directory — on hiatus
- Flask port — stays 8765
- Legacy CLI — `python scraper/scrape.py --location "Austin, TX, US"` must keep working
- Frontend CSS/JS — do not modify existing styles

---

## Bugs to Watch For

**Nominatim address format sensitivity**
Starbucks addresses from JobSpy often include suite numbers and non-standard formatting. The `_simplify_address()` helper handles the common cases, but some stores may still fail to geocode. For any that still return null after Nominatim, use the Google Maps coordinates from the `GoogleMapsStoreFinder` run — it will have them.

**Google Maps selector drift**
Google Maps updates its DOM structure frequently. If `query_selector_all('a[href*="/maps/place/"]')` returns 0 results, the selectors need updating. Open Chromium non-headless (`headless=False`) to inspect the current DOM:

```python
browser = await p.chromium.launch(headless=False)  # temporary for debugging
```

**Playwright Cloudflare on Workday**
Even with headless Playwright, Workday may show a Cloudflare challenge page. Signs: the page loads but no job cards appear. Fix: add a longer initial wait (`wait_for_timeout(5000)`) and check if a challenge iframe is present before proceeding. If the challenge persists, the SPA's network requests can be intercepted via `page.on("response", ...)` to capture the API JSON directly — that's a fallback to the fallback, only needed if the DOM approach fails.

**APScheduler and Playwright**
Do NOT add `playwright_fallback.py` scrapers to APScheduler. Playwright spins up a full browser, takes 30-60 seconds per run, and would flag as suspicious behavior if run on a fixed schedule. Keep it as a manual / on-demand tool only.
