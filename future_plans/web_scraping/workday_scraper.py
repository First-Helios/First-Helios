"""
Workday Careers Scraper — FUTURE PLANS.

Renders the Starbucks Workday SPA with a real headless browser.
Extracts job listings including posting dates (required for age-decay scoring).

This file was moved from scrapers/playwright_fallback.py as part of the
database reorganization. Direct website scraping is architecturally distinct
from consuming public APIs and requires its own project with:
  - Anti-bot handling
  - Session management
  - Per-site maintenance
  - Dedicated infrastructure

See docs/PROJECT_INTENT_EVALUATION.md for the rationale.

Original location: scrapers/playwright_fallback.py (WorkdayScraper class)
Depends on: playwright (+ chromium), config.loader, scrapers.base
"""

# NOTE: This is archived code. It was functional when moved but is not
# actively maintained. Before reactivating, review:
# 1. Workday API endpoint changes
# 2. Anti-bot countermeasure updates
# 3. Session management requirements
# 4. Rate limiting / ethical scraping considerations

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

_PROJECT_ROOT = Path(__file__).parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from config.loader import get_chain, get_config, get_region
from scrapers.base import BaseScraper, ScraperSignal

logger = logging.getLogger(__name__)


class WorkdayScraper(BaseScraper):
    """Renders the Starbucks Workday SPA with a real headless browser.

    Extracts job listings including posting dates (required for age-decay scoring).

    The direct API (starbucks.wd1.myworkdayjobs.com) returns 422 on all direct HTTP
    requests due to Cloudflare + JS rendering requirement. This is the fallback.

    Depends on: Playwright + Chromium
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
        import time as _pw_t
        from backend.tracked_request import log_external
        _pw_t0 = _pw_t.time()
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

        _pw_lat = int((_pw_t.time() - _pw_t0) * 1000)
        log_external(
            "workday_playwright", "spa_scrape",
            url=self.WORKDAY_URL,
            success=len(signals) > 0, latency_ms=_pw_lat,
            data_items=len(signals),
            params={"region": region, "location_filter": location_filter},
        )
        logger.info(
            "[WorkdayScraper] Total: %d listings extracted", len(signals)
        )
        return signals

    async def _extract_listings_from_page(
        self, page: Page, region: str
    ) -> list[ScraperSignal]:
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
        if not location_text:
            return None
        match = re.search(
            r"(?:store\s*#?|#)(\d{4,6})", location_text, re.IGNORECASE
        )
        if match:
            return f"SB-{match.group(1)}"
        return None

    def scrape(self, region: str, radius_mi: int = 25) -> list[ScraperSignal]:
        try:
            return asyncio.run(self._scrape_async(region, radius_mi))
        except Exception as e:
            logger.error("[WorkdayScraper] scrape() failed: %s", e)
            return []
