"""
collectors/meal_deals/website_scraper.py — Crawl individual restaurant websites for deals.

For non-chain restaurants that have a URL in restaurant_urls, this module:
  1. Fetches homepage + common deal-related paths (/menu, /specials, /deals, /lunch)
  2. Scans page text for deal-signal keywords (prices, "special", "BOGO", etc.)
  3. Extracts structured DealSignal objects from detected deals
  4. Feeds them through the standard ingest pipeline

Respects robots.txt, 1 req/sec rate limit, uses user-agent rotation.

Depends on: requests, beautifulsoup4, collectors.rotation
Called by: scheduler (Wednesday/Saturday 2:00 AM) or CLI
"""

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.registry import deal_collector
from collectors.rotation import _load as _load_rotation

logger = logging.getLogger(__name__)

# Sub-paths to probe on each restaurant's domain
DEAL_PATHS = [
    "/",
    "/menu",
    "/specials",
    "/deals",
    "/lunch",
    "/happy-hour",
    "/promotions",
    "/offers",
]

# Keywords that suggest a deal (case-insensitive)
_DEAL_KEYWORDS = [
    "special", "specials", "deal", "deals", "combo", "bogo",
    "buy one get one", "happy hour", "kids eat free", "early bird",
    "lunch special", "dinner special", "daily special",
    "meal deal", "value meal", "discount",
    "monday", "tuesday", "wednesday", "thursday", "friday",
    "saturday", "sunday",
]

# Price pattern: "$5.99", "$10", "$12.50"
_PRICE_RE = re.compile(r"\$(\d{1,3}\.?\d{0,2})")

# Calorie patterns: "450 cal", "450 calories", "450 kcal", "450Cal"
_CALORIE_RE = re.compile(
    r"(\d{2,4})\s*(?:cal(?:ories?)?|kcal|Cal)\b",
    re.IGNORECASE,
)

# Day-of-week pattern (for matching valid_days)
_DAY_PATTERN = re.compile(
    r"\b(monday|tuesday|wednesday|thursday|friday|saturday|sunday"
    r"|mon|tue|wed|thu|fri|sat|sun"
    r"|mon-fri|mon-sat|mon-sun)\b",
    re.IGNORECASE,
)

# Time pattern: "11:00 AM", "2:00 PM", "11am", "2pm"
_TIME_PATTERN = re.compile(
    r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm|AM|PM))\b"
)

# Deal-type classification keywords
_DEAL_TYPE_MAP = {
    "happy hour": "happy_hour",
    "happy hr": "happy_hour",
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
    "early bird": "daily_special",
}

# Maximum page size to process (avoid huge pages)
MAX_PAGE_SIZE = 500_000  # 500KB

# Request timeout
REQUEST_TIMEOUT = 15


class _RobotsTxtBlocked(Exception):
    """Raised when robots.txt disallows fetching ALL deal-related paths."""
    pass


_SPIRITPOOL_BLOCKED_PATH = Path(__file__).parent.parent.parent / "data" / "cache" / "spiritpool_blocked_sites.json"


def _write_spiritpool_blocked(blocked: list[dict]) -> None:
    """Append blocked sites to a JSON file for SpiritPool to pick up."""
    existing = []
    if _SPIRITPOOL_BLOCKED_PATH.exists():
        try:
            existing = json.loads(_SPIRITPOOL_BLOCKED_PATH.read_text())
        except (json.JSONDecodeError, OSError):
            existing = []

    # Dedup by employer_id
    seen_ids = {e["employer_id"] for e in existing}
    for site in blocked:
        if site["employer_id"] not in seen_ids:
            site["flagged_at"] = datetime.utcnow().isoformat()
            existing.append(site)
            seen_ids.add(site["employer_id"])

    _SPIRITPOOL_BLOCKED_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SPIRITPOOL_BLOCKED_PATH.write_text(json.dumps(existing, indent=2))


def _get_user_agent() -> str:
    """Get a rotated user-agent string."""
    try:
        state = _load_rotation()
        agents = state.get("user_agents", [])
        if agents:
            import random
            return random.choice(agents)
    except Exception:
        pass
    return "FirstHelios/1.0 (community labor research)"


def _can_fetch(base_url: str, path: str, user_agent: str) -> bool:
    """Check robots.txt to see if we can fetch this path."""
    try:
        parsed = urlparse(base_url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, path)
    except Exception:
        return True  # if we can't read robots.txt, assume OK


def _fetch_page(url: str, user_agent: str) -> str | None:
    """Fetch a page, respecting size limits. Returns HTML text or None."""
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": user_agent},
            timeout=REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None
        if len(resp.content) > MAX_PAGE_SIZE:
            return resp.text[:MAX_PAGE_SIZE]
        return resp.text
    except Exception as e:
        logger.debug("[WebScraper] Failed to fetch %s: %s", url, e)
        return None


def _extract_text_blocks(soup: BeautifulSoup) -> list[str]:
    """Extract meaningful text blocks from a page (paragraphs, headings, list items, divs)."""
    blocks = []
    for tag in soup.find_all(["p", "h1", "h2", "h3", "h4", "li", "td", "span", "div"]):
        text = tag.get_text(separator=" ", strip=True)
        if text and len(text) > 10 and len(text) < 500:
            blocks.append(text)
    return blocks


def _has_deal_keywords(text: str) -> bool:
    """Check if a text block contains deal-related keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in _DEAL_KEYWORDS)


def _classify_deal_type(text: str) -> str:
    """Classify the deal type from text content."""
    text_lower = text.lower()
    for keyword, deal_type in _DEAL_TYPE_MAP.items():
        if keyword in text_lower:
            return deal_type
    if _PRICE_RE.search(text):
        return "combo"
    return "daily_special"


def _extract_price(text: str) -> float | None:
    """Extract the first price from text."""
    match = _PRICE_RE.search(text)
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            pass
    return None


def _extract_calories(text: str) -> int | None:
    """Extract calorie count from text (e.g. '450 cal', '620 calories')."""
    match = _CALORIE_RE.search(text)
    if match:
        try:
            val = int(match.group(1))
            if 50 <= val <= 5000:  # sanity range
                return val
        except ValueError:
            pass
    return None


def _extract_all_prices(blocks: list[str]) -> list[float]:
    """Extract all dollar prices from text blocks for menu average calculation."""
    prices = []
    for block in blocks:
        for m in _PRICE_RE.finditer(block):
            try:
                p = float(m.group(1))
                if 1.0 <= p <= 200.0:  # filter noise (tax amounts, phone numbers, etc.)
                    prices.append(p)
            except ValueError:
                pass
    return prices


def _extract_days(text: str) -> str | None:
    """Extract day-of-week mention from text."""
    match = _DAY_PATTERN.search(text)
    if match:
        return match.group(0).title()
    return None


def _extract_times(text: str) -> tuple[str | None, str | None]:
    """Extract time range from text. Returns (start_time, end_time)."""
    matches = _TIME_PATTERN.findall(text)
    if len(matches) >= 2:
        return matches[0], matches[1]
    elif len(matches) == 1:
        return matches[0], None
    return None, None


def scrape_restaurant_website(
    url: str,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None = None,
    region: str = "austin_tx",
) -> list[DealSignal]:
    """Scrape a single restaurant's website for deals.

    Probes homepage + common deal sub-paths, extracts deal signals.
    Returns list of DealSignals found.
    """
    user_agent = _get_user_agent()
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    signals: list[DealSignal] = []
    seen_deals: set[str] = set()  # dedup by deal_name
    robots_blocked_count = 0
    all_menu_prices: list[float] = []  # collect all prices across pages for avg

    for path in DEAL_PATHS:
        full_url = urljoin(base_url, path)

        # Respect robots.txt
        if not _can_fetch(base_url, path, user_agent):
            logger.debug("[WebScraper] Blocked by robots.txt: %s", full_url)
            robots_blocked_count += 1
            continue

        html = _fetch_page(full_url, user_agent)
        if not html:
            continue

        soup = BeautifulSoup(html, "html.parser")
        blocks = _extract_text_blocks(soup)

        # Collect all prices from this page for menu average
        all_menu_prices.extend(_extract_all_prices(blocks))

        for block in blocks:
            if not _has_deal_keywords(block):
                continue

            # Extract a deal name (first sentence or first 80 chars)
            deal_name = block.split(".")[0].strip()[:80]
            if not deal_name or len(deal_name) < 5:
                continue

            # Dedup
            name_key = deal_name.lower()
            if name_key in seen_deals:
                continue
            seen_deals.add(name_key)

            price = _extract_price(block)
            deal_type = _classify_deal_type(block)
            valid_days = _extract_days(block)
            start_time, end_time = _extract_times(block)
            calories = _extract_calories(block)

            # Compute calorie-per-dollar ratio
            calorie_price_ratio = None
            if calories and price and price > 0:
                calorie_price_ratio = round(calories / price, 1)

            signals.append(DealSignal(
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                deal_name=deal_name,
                deal_description=block[:500],
                deal_type=deal_type,
                price=price,
                calories=calories,
                calorie_price_ratio=calorie_price_ratio,
                valid_days=valid_days,
                valid_start_time=start_time,
                valid_end_time=end_time,
                source="website_scrape",
                source_url=full_url,
                region=region,
                observed_at=datetime.utcnow(),
            ))

        # Rate limit: 1 req/sec between pages
        time.sleep(1.0)

    # If robots.txt blocked ALL paths, flag for SpiritPool
    if robots_blocked_count >= len(DEAL_PATHS):
        raise _RobotsTxtBlocked(f"{restaurant_name} ({base_url}) blocks all deal paths via robots.txt")

    # Compute menu average price and attach to each signal
    if all_menu_prices and len(all_menu_prices) >= 3:
        menu_avg = round(sum(all_menu_prices) / len(all_menu_prices), 2)
        for sig in signals:
            sig.menu_avg_price = menu_avg

    return signals


@deal_collector("website_scraper", schedule="0 2 * * 1,3,5")
class WebsiteDealCollector:
    """Scheduled collector: scrapes restaurant websites for deals.

    Targets local_employers that have a URL in restaurant_urls but
    either have no meal_deals or stale ones.

    Schedule: Mon, Wed, Fri at 2:00 AM — scrape regularly for freshness.
    Sites that block us are flagged for SpiritPool manual entry.
    Deals expire after 14 days without re-verification.
    """

    SOURCE = "website_scraper"

    def collect(
        self,
        region: str = "austin_tx",
        max_sites: int = 100,
        dry_run: bool = False,
    ) -> list[DealSignal]:
        """Scrape websites and return DealSignals."""
        from core.database import LocalEmployer, MealDeal, RestaurantURL, get_engine, get_session, init_db

        engine = init_db()
        session = get_session(engine)

        all_signals: list[DealSignal] = []
        urls: list = []

        try:
            # Find restaurant_urls that:
            # 1. Are active
            # 2. Haven't been checked recently (or never checked for deals)
            # 3. Are for food employers
            # Priority: check sites we haven't visited recently first.
            # Sites that block us (last_http_status >= 400 or robots.txt blocked)
            # are deprioritized — they'll be flagged for SpiritPool.
            urls = session.query(
                RestaurantURL, LocalEmployer
            ).join(
                LocalEmployer, LocalEmployer.id == RestaurantURL.local_employer_id
            ).filter(
                RestaurantURL.is_active.is_(True),
                LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
                LocalEmployer.region == region,
                LocalEmployer.is_active.is_(True),
            ).order_by(
                RestaurantURL.last_checked.asc().nullsfirst()
            ).limit(max_sites).all()

            logger.info("[WebScraper] Scanning %d restaurant websites", len(urls))

            blocked_sites: list[dict] = []  # Track sites that block scraping

            for rurl, emp in urls:
                try:
                    signals = scrape_restaurant_website(
                        url=rurl.url,
                        restaurant_name=emp.name,
                        local_employer_id=emp.id,
                        brand_group_id=emp.brand_group_id,
                        region=region,
                    )

                    if signals:
                        logger.info(
                            "[WebScraper] %s: %d deals found at %s",
                            emp.name, len(signals), rurl.url,
                        )
                        all_signals.extend(signals)

                    # Update the restaurant_url record
                    if not dry_run:
                        rurl.last_checked = datetime.utcnow()
                        rurl.has_deals_page = len(signals) > 0
                        rurl.last_http_status = 200
                        session.flush()

                except _RobotsTxtBlocked as e:
                    # Site blocks scraping via robots.txt — flag for SpiritPool
                    logger.info("[WebScraper] %s blocked by robots.txt → flagging for SpiritPool", emp.name)
                    blocked_sites.append({
                        "name": emp.name,
                        "url": rurl.url,
                        "reason": "robots.txt",
                        "employer_id": emp.id,
                    })
                    if not dry_run:
                        rurl.last_checked = datetime.utcnow()
                        rurl.last_http_status = 403
                        session.flush()

                except Exception as e:
                    logger.warning("[WebScraper] Error scraping %s: %s", rurl.url, e)
                    if not dry_run:
                        rurl.last_checked = datetime.utcnow()
                        # Try to extract HTTP status from exception
                        status = getattr(getattr(e, 'response', None), 'status_code', 0)
                        if status:
                            rurl.last_http_status = status
                        session.flush()
                    continue

            if not dry_run:
                session.commit()

            # Write blocked sites for SpiritPool pickup
            if blocked_sites:
                _write_spiritpool_blocked(blocked_sites)

        except Exception as exc:
            session.rollback()
            logger.error("[WebScraper] Collection failed: %s", exc, exc_info=True)
        finally:
            session.close()

        logger.info("[WebScraper] Total: %d deal signals from %d sites", len(all_signals), len(urls))
        return all_signals


def run_website_scraper(
    region: str = "austin_tx",
    max_sites: int = 100,
    dry_run: bool = False,
) -> dict:
    """Run the website scraper and ingest results."""
    collector = WebsiteDealCollector()
    signals = collector.collect(region=region, max_sites=max_sites, dry_run=dry_run)

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
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Scrape restaurant websites for meal deals")
    parser.add_argument("--max-sites", type=int, default=100, help="Max sites to scrape")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--region", default="austin_tx")
    args = parser.parse_args()

    stats = run_website_scraper(
        region=args.region,
        max_sites=args.max_sites,
        dry_run=args.dry_run,
    )
    print(f"\n--- Website Scraper Stats ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")
