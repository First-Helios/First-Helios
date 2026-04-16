"""
collectors/meal_deals/chain_deals.py — Scrape deal pages for known chain restaurants.

Reads config/meal_deal_sources.yaml for the URL + strategy mapping,
fetches each chain's deal page, extracts DealSignal objects, and
returns them for the ingest pipeline to fan out across all locations.

Handles all strategies:
  - static_html   → requests + BeautifulSoup
  - menu_only     → requests + BeautifulSoup (filtered for actual deals, not full menus)
  - playwright_required → async Playwright headless Chromium
  - app_only      → skipped (no public web deals)

Depends on: requests, beautifulsoup4, pyyaml, config/meal_deal_sources.yaml
            playwright (optional — only for playwright_required chains)
Called by: scheduler or CLI
"""

import asyncio
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
import yaml
from bs4 import BeautifulSoup, Tag

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.registry import deal_collector
from collectors.meal_deals.temporal import extract_days, extract_times
from collectors.rotation import _load as _load_rotation  # noqa: for user-agent
from core.normalizer import make_fingerprint

logger = logging.getLogger(__name__)

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "meal_deal_sources.yaml"

# Common price regex: "$5.99", "$10", "$3.50"
_PRICE_RE = re.compile(r"\$(\d+\.?\d{0,2})")

# Deal-type keyword mapping
_DEAL_TYPE_KEYWORDS = {
    "happy hour": "happy_hour",
    "happy hr": "happy_hour",
    "lunch special": "lunch_special",
    "lunch combo": "lunch_special",
    "bogo": "bogo",
    "buy one get one": "bogo",
    "buy one, get one": "bogo",
    "kids eat free": "kids_eat_free",
    "kids meal": "kids_eat_free",
    "daily special": "daily_special",
    "combo": "combo",
    "meal deal": "combo",
    "value": "combo",
    "cravings": "combo",
}

# Keywords that indicate an actual DEAL vs. a regular menu item
# (used to filter menu_only strategy so we don't ingest entire menus)
_DEAL_SIGNAL_KEYWORDS = {
    "deal", "deals", "special", "specials", "combo", "value",
    "bogo", "buy one", "free", "save", "offer", "promotion",
    "limited time", "happy hour", "kids eat", "early bird",
    "meal deal", "cravings", "discount",
}

# User-Agent rotation (subset — keep it simple for chain sites)
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

_REQUEST_TIMEOUT = 20  # seconds (up from 15 — Pizza Hut needs more)
_REQUEST_MAX_RETRIES = 2  # retry once on timeout/5xx


def _load_chain_config() -> dict[str, dict[str, Any]]:
    """Load chain deal source config from YAML."""
    with open(_CONFIG_PATH, "r") as f:
        data = yaml.safe_load(f) or {}
    return data.get("chain_deal_sources", {})


def _classify_deal_type(text: str) -> str:
    """Infer deal_type from text content using keyword matching."""
    lower = text.lower()
    for keyword, deal_type in _DEAL_TYPE_KEYWORDS.items():
        if keyword in lower:
            return deal_type
    return "combo"  # default


def _is_deal_text(text: str) -> bool:
    """Check if text looks like an actual deal/special vs. a regular menu item.

    Used by menu_only strategy to filter out plain menu items
    (e.g. ThunderCloud's 80 menu items) and keep only real deals.
    """
    lower = text.lower()
    return any(kw in lower for kw in _DEAL_SIGNAL_KEYWORDS)


def _extract_prices(text: str) -> list[float]:
    """Extract all dollar amounts from text."""
    return [float(m) for m in _PRICE_RE.findall(text)]


def _fetch_page(url: str) -> BeautifulSoup | None:
    """Fetch a page and return parsed BeautifulSoup, or None on failure.

    Retries once on timeout or 5xx errors.
    """
    for attempt in range(_REQUEST_MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                headers={"User-Agent": _USER_AGENT},
                timeout=_REQUEST_TIMEOUT,
                allow_redirects=True,
            )
            resp.raise_for_status()
            return BeautifulSoup(resp.text, "html.parser")
        except requests.exceptions.Timeout:
            if attempt < _REQUEST_MAX_RETRIES:
                logger.warning("[ChainDeals] Timeout for %s, retrying (%d/%d)", url, attempt + 1, _REQUEST_MAX_RETRIES)
                import time
                time.sleep(3)
                continue
            logger.warning("[ChainDeals] Timeout for %s after %d attempts", url, attempt + 1)
            return None
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status >= 500 and attempt < _REQUEST_MAX_RETRIES:
                logger.warning("[ChainDeals] %d for %s, retrying (%d/%d)", status, url, attempt + 1, _REQUEST_MAX_RETRIES)
                import time
                time.sleep(3)
                continue
            logger.warning("[ChainDeals] Failed to fetch %s: %s", url, e)
            return None
        except Exception as exc:
            logger.warning("[ChainDeals] Failed to fetch %s: %s", url, exc)
            return None
    return None


def _extract_deals_generic(
    soup: BeautifulSoup,
    chain_key: str,
    chain_cfg: dict[str, Any],
) -> list[dict[str, Any]]:
    """Generic deal extraction: find text blocks with prices and deal keywords.

    Returns raw dicts with keys: name, description, deal_type, price.
    Works across most chain sites by scanning headings + nearby text.

    For menu_only strategy, applies stricter keyword filtering to avoid
    ingesting regular menu items (e.g. ThunderCloud's 80 items).
    """
    is_menu_only = chain_cfg.get("strategy") == "menu_only"
    deals: list[dict[str, Any]] = []
    seen_names: set[str] = set()

    # Strategy 1: Scan headings (h1-h6) for deal-like text
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        heading_text = heading.get_text(strip=True)
        if not heading_text or len(heading_text) < 3:
            continue

        # Collect description from siblings/children
        desc_parts: list[str] = []
        for sibling in heading.find_next_siblings():
            if isinstance(sibling, Tag) and sibling.name in ("h1", "h2", "h3", "h4", "h5", "h6"):
                break  # stop at next heading
            text = sibling.get_text(strip=True)
            if text:
                desc_parts.append(text)
            if len(desc_parts) >= 3:
                break

        full_text = f"{heading_text} {' '.join(desc_parts)}"
        prices = _extract_prices(full_text)

        # Only keep if it looks like a deal (has a price or deal keyword)
        has_deal_keyword = any(kw in full_text.lower() for kw in _DEAL_TYPE_KEYWORDS)
        if not prices and not has_deal_keyword:
            continue

        # For menu_only strategy, require actual deal signal keywords
        # (filters out regular menu items like "Turkey Sub $8.99")
        if is_menu_only and not _is_deal_text(full_text):
            continue

        name = heading_text[:120]
        if name in seen_names:
            continue
        seen_names.add(name)

        valid_days = extract_days(full_text)
        v_start, v_end = extract_times(full_text)

        deals.append({
            "name": name,
            "description": " ".join(desc_parts)[:500] if desc_parts else None,
            "deal_type": _classify_deal_type(full_text),
            "price": prices[0] if prices else None,
            "original_price": prices[1] if len(prices) > 1 else None,
            "valid_days": valid_days,
            "valid_start_time": v_start,
            "valid_end_time": v_end,
            "raw_scraped_text": full_text[:2000],
        })

    # Strategy 2: Scan links with deal-like text (many chains use link cards)
    for link in soup.find_all("a"):
        link_text = link.get_text(strip=True)
        if not link_text or len(link_text) < 5 or link_text in seen_names:
            continue

        prices = _extract_prices(link_text)
        has_deal_keyword = any(kw in link_text.lower() for kw in _DEAL_TYPE_KEYWORDS)
        if not prices and not has_deal_keyword:
            continue

        # For menu_only, require deal signal keywords
        if is_menu_only and not _is_deal_text(link_text):
            continue

        seen_names.add(link_text[:120])
        valid_days = extract_days(link_text)
        v_start, v_end = extract_times(link_text)
        deals.append({
            "name": link_text[:120],
            "description": None,
            "deal_type": _classify_deal_type(link_text),
            "price": prices[0] if prices else None,
            "original_price": prices[1] if len(prices) > 1 else None,
            "valid_days": valid_days,
            "valid_start_time": v_start,
            "valid_end_time": v_end,
            "raw_scraped_text": link_text[:2000],
        })

    return deals


# ── Playwright deal page scraper ─────────────────────────────────────────────

async def _fetch_page_playwright(url: str, wait_ms: int = 5000) -> BeautifulSoup | None:
    """Fetch a JS-rendered page with Playwright and return parsed BeautifulSoup.

    Used for chains with strategy=playwright_required (Subway, Sonic, etc.).
    Launches headless Chromium, waits for content to render, returns HTML.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        logger.error("[ChainDeals] playwright not installed — run: pip install playwright && playwright install chromium")
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-dev-shm-usage"],
            )
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1280, "height": 900},
            )
            page = await context.new_page()

            try:
                logger.info("[ChainDeals/PW] Loading: %s", url)
                # Use domcontentloaded instead of networkidle — many chain sites
                # have aggressive ad-tech that prevents networkidle from firing.
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await page.wait_for_timeout(wait_ms)

                # Try to dismiss cookie consent banners
                for selector in [
                    'button:has-text("Accept")',
                    'button:has-text("Accept All")',
                    'button[id*="cookie"]',
                    'button[id*="consent"]',
                    'button[class*="accept"]',
                ]:
                    try:
                        btn = await page.query_selector(selector)
                        if btn:
                            await btn.click()
                            await page.wait_for_timeout(500)
                            break
                    except Exception:
                        continue

                # Scroll to load lazy content
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight / 2)")
                await page.wait_for_timeout(1500)
                await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                await page.wait_for_timeout(1500)

                content = await page.content()
                return BeautifulSoup(content, "html.parser")

            finally:
                await browser.close()

    except Exception as exc:
        logger.warning("[ChainDeals/PW] Failed for %s: %s", url, exc)
        return None


def _fetch_page_pw_sync(url: str, wait_ms: int = 5000) -> BeautifulSoup | None:
    """Sync wrapper for _fetch_page_playwright."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # If we're in an async context, use a new thread
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, _fetch_page_playwright(url, wait_ms)).result()
        return loop.run_until_complete(_fetch_page_playwright(url, wait_ms))
    except RuntimeError:
        return asyncio.run(_fetch_page_playwright(url, wait_ms))


@deal_collector("chain_deals", schedule="0 6 * * 1")
class ChainDealCollector:
    """Scrapes chain restaurant deal pages and produces DealSignal objects.

    Only processes chains with strategy=static_html or strategy=menu_only.
    """

    SOURCE = "chain_website"

    def collect(self, region: str = "austin_tx") -> list[DealSignal]:
        """Scrape all configured chain deal pages and return DealSignals.

        Each DealSignal has brand_fingerprint set — the ingest pipeline
        fans these out to all locations of that brand in the region.

        Supports strategies: static_html, menu_only, playwright_required.
        Skips: app_only.
        """
        config = _load_chain_config()
        signals: list[DealSignal] = []

        for chain_key, chain_cfg in config.items():
            strategy = chain_cfg.get("strategy", "")
            if strategy == "app_only":
                logger.debug(
                    "[ChainDeals] Skipping %s (strategy=%s)", chain_key, strategy
                )
                continue

            if strategy not in ("static_html", "menu_only", "playwright_required"):
                logger.debug(
                    "[ChainDeals] Skipping %s (unknown strategy=%s)", chain_key, strategy
                )
                continue

            url = chain_cfg.get("url")
            if not url:
                continue

            display_name = chain_cfg.get("display_name", chain_key)
            logger.info("[ChainDeals] Scraping %s → %s (strategy=%s)", display_name, url, strategy)

            # Choose fetch method based on strategy
            if strategy == "playwright_required":
                soup = _fetch_page_pw_sync(url, wait_ms=5000)
            else:
                soup = _fetch_page(url)
                if not soup:
                    # Try fallback URLs
                    for fb_url in chain_cfg.get("fallback_urls", []):
                        soup = _fetch_page(fb_url)
                        if soup:
                            url = fb_url
                            break

            if not soup:
                logger.warning("[ChainDeals] No content for %s", display_name)
                continue

            raw_deals = _extract_deals_generic(soup, chain_key, chain_cfg)
            logger.info(
                "[ChainDeals] %s: extracted %d deals", display_name, len(raw_deals)
            )

            for deal in raw_deals:
                signals.append(
                    DealSignal(
                        restaurant_name=display_name,
                        brand_fingerprint=chain_cfg.get("fingerprint") or make_fingerprint(display_name),
                        deal_name=deal["name"],
                        deal_description=deal.get("description"),
                        deal_type=deal.get("deal_type", "combo"),
                        price=deal.get("price"),
                        original_price=deal.get("original_price"),
                        valid_days=deal.get("valid_days"),
                        valid_start_time=deal.get("valid_start_time"),
                        valid_end_time=deal.get("valid_end_time"),
                        raw_scraped_text=deal.get("raw_scraped_text"),
                        source="chain_website",
                        source_url=url,
                        region=region,
                    )
                )

        logger.info("[ChainDeals] Total signals: %d", len(signals))
        return signals


# ── CLI entry point ──────────────────────────────────────────────────────────

def run_chain_deals(region: str = "austin_tx", dry_run: bool = False) -> list[DealSignal]:
    """CLI-callable function. Returns signals; optionally writes to DB."""
    collector = ChainDealCollector()
    signals = collector.collect(region=region)

    if dry_run:
        for s in signals:
            print(f"  [{s.deal_type}] {s.restaurant_name}: {s.deal_name} — ${s.price}")
        return signals

    # Import ingest pipeline and write
    from collectors.meal_deals.ingest import ingest_deal_signals
    ingest_deal_signals(signals, region=region)
    return signals


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Scrape chain restaurant deals")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--dry-run", action="store_true", help="Print deals without writing to DB")
    args = parser.parse_args()

    results = run_chain_deals(region=args.region, dry_run=args.dry_run)
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Collected {len(results)} deal signals.")
