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
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.registry import deal_collector
from collectors.rotation import _load as _load_rotation

try:
    import pdfplumber
    _HAS_PDFPLUMBER = True
except ImportError:
    _HAS_PDFPLUMBER = False

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

# Keywords that suggest a deal (case-insensitive).
# Day-of-week names alone are too broad (match hours-of-operation text);
# they're only tested as supporting evidence inside _is_valid_deal_block().
_DEAL_KEYWORDS = [
    "special", "specials", "deal", "deals", "combo", "bogo",
    "buy one", "happy hour", "kids eat free", "early bird",
    "lunch special", "dinner special", "daily special",
    "meal deal", "value meal", "discount",
    "limited time", "save", "promotion", "offer",
    "half off", "half price", "% off",
    "for the price of", "2 for",
]

# Self-validating keywords — strong deal signals that don't need a price.
# Keep this set VERY tight: only phrases that are unambiguously a deal.
_SELF_VALIDATING_KEYWORDS = {
    "bogo", "buy one get one", "buy one, get one",
    "kids eat free", "happy hour",
    "half off", "half price", "% off",
}

# Negative-context patterns — when these appear, the block is NOT a deal
# even if it contains a deal keyword. Compiled once at import time.
_NEGATIVE_CONTEXT_PATTERNS = [
    re.compile(r"\bspecial\s+occasion", re.IGNORECASE),
    re.compile(r"\bno\s+substitution", re.IGNORECASE),
    re.compile(r"\bpre-?order\b", re.IGNORECASE),
    re.compile(r"\bskip\s+to\s+(?:content|main)", re.IGNORECASE),
    re.compile(r"open\s+menu.*close\s+menu", re.IGNORECASE),
]

# Phrases that mark navigational / boilerplate / ad content.
_BOILERPLATE_PHRASES = [
    "privacy", "terms of use", "site map", "cookie",
    "toggle header", "toggle menu", "toggle nav",
    "newsroom", "gift card", "careers", "about us",
    "rewards", "sign in", "log in", "sign up",
    "download the app", "mobile app",
    "international sites", "franchise",
    "copyright", "all rights reserved",
    "skip to content", "skip to main",
    "open menu close menu",
    "locations specials jobs",
]

# Spam / ad content blocklist — gambling, pharma, unrelated marketing.
_SPAM_PHRASES = [
    "casino", "gambling", "gamstop", "slot machine",
    "poker", "roulette", "blackjack", "betting",
    "live dealer", "online casino", "sports betting",
    "erectile", "viagra", "cbd gummies",
    "crypto", "bitcoin", "nft",
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

# JSON-LD extraction regex — same pattern proven in collectors/events/austintexas_org.py
_JSONLD_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# Schema.org types that may contain deals or menu items with prices
_DEAL_SCHEMA_TYPES = frozenset([
    "Offer", "AggregateOffer", "MenuItem", "MenuSection",
    "Menu", "Restaurant", "FoodEstablishment",
])

# URL path fragments that suggest a deal-related page (for link discovery)
_DEAL_URL_KEYWORDS = frozenset([
    "special", "specials", "deal", "deals", "offer", "offers",
    "promo", "promotion", "promotions", "happy-hour", "happyhour",
    "lunch", "dinner", "menu", "price", "coupon", "coupons",
    "combo", "value", "discount", "weekly", "daily", "today",
])

# URL paths that are definitely NOT deal pages — exclude from discovery
_NON_DEAL_URL_KEYWORDS = frozenset([
    "career", "careers", "jobs", "about", "contact", "privacy",
    "terms", "login", "signin", "sign-up", "signup", "account",
    "order", "delivery", "catering", "franchise", "blog", "news",
    "press", "media", "faq", "help", "support", "donate",
    "gift", "rewards", "loyalty", "app", "download",
    "reservation", "reservations", "book", "booking",
    "events", "gallery", "photos", "team", "staff",
    "sitemap", "feed", "rss", "xml",
])

# Maximum page budget per site (hardcoded + discovered)
MAX_PAGES_PER_SITE = 12

# Maximum PDFs to parse per site
MAX_PDFS_PER_SITE = 3

# Maximum page size to process (avoid huge pages)
MAX_PAGE_SIZE = 500_000  # 500KB

# Request timeout
REQUEST_TIMEOUT = 15


class _RobotsTxtBlocked(Exception):
    """Raised when robots.txt disallows fetching ALL deal-related paths."""
    pass


_SPIRITPOOL_BLOCKED_PATH = Path(__file__).parent.parent.parent / "data" / "cache" / "spiritpool_blocked_sites.json"
_SCRAPE_AUDIT_PATH = Path(__file__).parent.parent.parent / "data" / "cache" / "website_scrape_audit.json"


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


def _write_scrape_audit(entries: list[dict]) -> None:
    """Write the scrape audit log (overwritten each run with full results)."""
    _SCRAPE_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SCRAPE_AUDIT_PATH.write_text(json.dumps(entries, indent=2))


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


# HTML tags / CSS classes / IDs that are reliably navigational / structural.
_SKIP_TAG_NAMES = frozenset(["script", "style", "nav", "footer", "noscript", "header", "iframe"])
_SKIP_CLASS_ID_TOKENS = frozenset([
    "nav", "menu", "header", "footer", "breadcrumb",
    "pagination", "sidebar", "toolbar", "cookie",
    "consent", "banner", "popup", "modal",
])


def _should_skip_tag(tag: Tag) -> bool:
    """Return True for tags that are navigation, footer, or structural boilerplate."""
    if tag.name in _SKIP_TAG_NAMES:
        return True
    class_str = " ".join(tag.get("class", [])).lower()
    id_str = (tag.get("id") or "").lower()
    combined = f"{class_str} {id_str}"
    return any(tok in combined for tok in _SKIP_CLASS_ID_TOKENS)


def _extract_text_blocks(soup: BeautifulSoup) -> list[str]:
    """Extract meaningful text blocks, skipping navigation/footer/ad elements."""
    # Remove entire nav/footer/script subtrees first so nested tags don't leak.
    for bad in soup.find_all(_SKIP_TAG_NAMES):
        bad.decompose()

    # Original tags with established length thresholds
    _CORE_TAGS = frozenset(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td"])
    # Structural tags — often wrap large text, so use tighter length bounds
    _STRUCTURAL_TAGS = frozenset(["div", "span", "article", "section"])

    blocks = []
    seen_text: set[str] = set()  # avoid duplicate blocks from nested tags

    for tag in soup.find_all(list(_CORE_TAGS | _STRUCTURAL_TAGS)):
        if _should_skip_tag(tag):
            continue
        text = tag.get_text(separator=" ", strip=True)
        if not text:
            continue

        # Apply tag-appropriate length bounds
        if tag.name in _STRUCTURAL_TAGS:
            if not (25 < len(text) < 300):
                continue
        else:
            if not (15 < len(text) < 400):
                continue

        # Dedup: skip if this exact text was already captured by a parent/child
        if text in seen_text:
            continue
        seen_text.add(text)
        blocks.append(text)

    return blocks


def _is_boilerplate(text: str) -> bool:
    """Return True if the text is navigation, footer, or ad/spam content."""
    lower = text.lower()
    # Boilerplate nav/footer phrases
    if any(bp in lower for bp in _BOILERPLATE_PHRASES):
        return True
    # Spam / ad injection (casino sites injecting into restaurant pages)
    if any(sp in lower for sp in _SPAM_PHRASES):
        return True
    return False


# Pre-compiled word-boundary regex for deal keywords.
# Using \b prevents 'special' from matching 'specialty'.
_DEAL_KEYWORD_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _DEAL_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _has_deal_keywords(text: str) -> bool:
    """Check if a text block contains deal-related keywords (word-boundary)."""
    return bool(_DEAL_KEYWORD_RE.search(text))


def _is_negative_context(text: str) -> bool:
    """Return True if text has anti-deal context that overrides keywords."""
    return any(pat.search(text) for pat in _NEGATIVE_CONTEXT_PATTERNS)


def _is_valid_deal_block(text: str) -> bool:
    """A valid deal must contain a price OR a self-validating keyword.

    Requirements (must pass ALL):
      1. NOT boilerplate / spam
      2. NOT negative context ("special occasion", "pre-order", etc.)
      3. Contains at least one deal keyword (word-boundary matched)
      4. AND one of:
         a. A price ($X.XX) in the same text block
         b. A self-validating keyword ("BOGO", "kids eat free", etc.)
    """
    if _is_boilerplate(text):
        return False
    if _is_negative_context(text):
        return False
    if not _has_deal_keywords(text):
        return False
    lower = text.lower()
    # Self-validating phrases are strong enough alone
    if any(kw in lower for kw in _SELF_VALIDATING_KEYWORDS):
        return True
    # Otherwise, a price MUST be present in this text block
    return bool(_PRICE_RE.search(text))


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


def _extract_jsonld_deals(
    html: str,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
) -> list[DealSignal]:
    """Extract deal signals from JSON-LD structured data on the page.

    Looks for schema.org Offer, MenuItem, Menu, MenuSection, Restaurant,
    and FoodEstablishment types. Applies the same deal-validation logic
    as text-block extraction to avoid ingesting regular menu items.

    Pattern adapted from collectors/events/austintexas_org.py:266-299.
    """
    signals: list[DealSignal] = []

    for match in _JSONLD_RE.finditer(html):
        try:
            ld_data = json.loads(match.group(1))
            items = ld_data if isinstance(ld_data, list) else [ld_data]

            for item in items:
                if not isinstance(item, dict):
                    continue
                # Handle @graph arrays (common in WordPress sites)
                if item.get("@graph"):
                    graph = item["@graph"]
                    if isinstance(graph, list):
                        items.extend(graph)
                    continue

                item_type = item.get("@type", "")
                # Normalize list types like ["Restaurant", "FoodEstablishment"]
                if isinstance(item_type, list):
                    item_type = item_type[0] if item_type else ""

                if item_type not in _DEAL_SCHEMA_TYPES:
                    continue

                # Route by type
                if item_type in ("Offer", "AggregateOffer"):
                    _jsonld_offer_to_signal(
                        item, restaurant_name, local_employer_id,
                        brand_group_id, source_url, region,
                        seen_deals, signals,
                    )
                elif item_type == "MenuItem":
                    _jsonld_menuitem_to_signal(
                        item, restaurant_name, local_employer_id,
                        brand_group_id, source_url, region,
                        seen_deals, signals,
                    )
                elif item_type == "MenuSection":
                    # MenuSection contains a list of MenuItems
                    for menu_item in item.get("hasMenuItem", []):
                        if isinstance(menu_item, dict):
                            _jsonld_menuitem_to_signal(
                                menu_item, restaurant_name, local_employer_id,
                                brand_group_id, source_url, region,
                                seen_deals, signals,
                            )
                elif item_type == "Menu":
                    # Menu → hasMenuSection → hasMenuItem
                    for section in item.get("hasMenuSection", []):
                        if isinstance(section, dict):
                            for menu_item in section.get("hasMenuItem", []):
                                if isinstance(menu_item, dict):
                                    _jsonld_menuitem_to_signal(
                                        menu_item, restaurant_name, local_employer_id,
                                        brand_group_id, source_url, region,
                                        seen_deals, signals,
                                    )
                elif item_type in ("Restaurant", "FoodEstablishment"):
                    # Check for nested offers
                    offers = item.get("makesOffer") or item.get("offers") or []
                    if isinstance(offers, dict):
                        offers = [offers]
                    for offer in offers:
                        if isinstance(offer, dict):
                            _jsonld_offer_to_signal(
                                offer, restaurant_name, local_employer_id,
                                brand_group_id, source_url, region,
                                seen_deals, signals,
                            )
                    # Check for nested menu
                    menu = item.get("hasMenu")
                    if isinstance(menu, dict) and menu.get("@type") == "Menu":
                        for section in menu.get("hasMenuSection", []):
                            if isinstance(section, dict):
                                for mi in section.get("hasMenuItem", []):
                                    if isinstance(mi, dict):
                                        _jsonld_menuitem_to_signal(
                                            mi, restaurant_name, local_employer_id,
                                            brand_group_id, source_url, region,
                                            seen_deals, signals,
                                        )

        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    return signals


def _jsonld_offer_to_signal(
    offer: dict,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
    signals: list[DealSignal],
) -> None:
    """Convert a schema.org Offer to a DealSignal if it passes deal validation."""
    name = offer.get("name") or offer.get("description", "")
    if not name:
        return

    # Build text for deal validation
    desc = offer.get("description", "")
    text = f"{name} {desc}".strip()

    # Must pass the same validation as text-block deals
    if not _is_valid_deal_block(text):
        return

    name_key = name[:80].lower()
    if name_key in seen_deals:
        return
    seen_deals.add(name_key)

    price = None
    raw_price = offer.get("price")
    if raw_price is not None:
        try:
            price = float(raw_price)
        except (ValueError, TypeError):
            price = _extract_price(str(raw_price))

    deal_type = _classify_deal_type(text)
    valid_days = _extract_days(text)
    start_time, end_time = _extract_times(text)

    signals.append(DealSignal(
        restaurant_name=restaurant_name,
        local_employer_id=local_employer_id,
        brand_group_id=brand_group_id,
        deal_name=name[:80],
        deal_description=text[:500],
        deal_type=deal_type,
        price=price,
        valid_days=valid_days,
        valid_start_time=start_time,
        valid_end_time=end_time,
        source="website_scrape",
        source_url=source_url,
        region=region,
        observed_at=datetime.utcnow(),
    ))


def _jsonld_menuitem_to_signal(
    item: dict,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
    signals: list[DealSignal],
) -> None:
    """Convert a schema.org MenuItem to a DealSignal if it looks like a deal."""
    name = item.get("name", "")
    desc = item.get("description", "")
    text = f"{name} {desc}".strip()
    if not text:
        return

    # Must pass deal validation — prevents ingesting plain menu items
    if not _is_valid_deal_block(text):
        return

    name_key = name[:80].lower()
    if name_key in seen_deals:
        return
    seen_deals.add(name_key)

    # Extract price from nested offers
    price = None
    offers = item.get("offers")
    if isinstance(offers, dict):
        try:
            price = float(offers.get("price", 0))
        except (ValueError, TypeError):
            pass
    elif isinstance(offers, list) and offers:
        try:
            price = float(offers[0].get("price", 0))
        except (ValueError, TypeError):
            pass
    if not price:
        price = _extract_price(text)

    # Extract calories from nutrition
    calories = None
    nutrition = item.get("nutrition")
    if isinstance(nutrition, dict):
        cal_val = nutrition.get("calories")
        if cal_val is not None:
            try:
                cal_int = int(str(cal_val).replace(" calories", "").replace(" cal", ""))
                if 50 <= cal_int <= 5000:
                    calories = cal_int
            except (ValueError, TypeError):
                pass
    if not calories:
        calories = _extract_calories(text)

    calorie_price_ratio = None
    if calories and price and price > 0:
        calorie_price_ratio = round(calories / price, 1)

    deal_type = _classify_deal_type(text)
    valid_days = _extract_days(text)
    start_time, end_time = _extract_times(text)

    signals.append(DealSignal(
        restaurant_name=restaurant_name,
        local_employer_id=local_employer_id,
        brand_group_id=brand_group_id,
        deal_name=name[:80],
        deal_description=text[:500],
        deal_type=deal_type,
        price=price,
        calories=calories,
        calorie_price_ratio=calorie_price_ratio,
        valid_days=valid_days,
        valid_start_time=start_time,
        valid_end_time=end_time,
        source="website_scrape",
        source_url=source_url,
        region=region,
        observed_at=datetime.utcnow(),
    ))


def _discover_deal_pages(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Discover deal-related subpages by scanning homepage links.

    Scores each link by URL path keywords and anchor text keywords.
    Returns up to 5 discovered URLs, excluding those already in DEAL_PATHS.
    """
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()

    # Normalize hardcoded paths for dedup
    existing_paths = {p.rstrip("/").lower() for p in DEAL_PATHS}

    scored: list[tuple[int, str]] = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Same-domain only
        if parsed.netloc.lower() != base_domain:
            continue

        # Skip non-HTTP schemes (mailto:, tel:, javascript:)
        if parsed.scheme not in ("http", "https"):
            continue

        path = parsed.path.rstrip("/").lower()

        # Skip if it's already in our hardcoded paths
        if path in existing_paths or path == "":
            continue

        # Skip file downloads (except PDFs which are handled separately)
        if any(path.endswith(ext) for ext in (".jpg", ".png", ".gif", ".svg", ".zip", ".css", ".js")):
            continue

        # Exclude known non-deal paths
        path_parts = path.strip("/").split("/")
        if any(part in _NON_DEAL_URL_KEYWORDS for part in path_parts):
            continue

        # Score by URL keywords
        score = 0
        for keyword in _DEAL_URL_KEYWORDS:
            if keyword in path:
                score += 2

        # Score by anchor text keywords
        anchor_text = a_tag.get_text(strip=True).lower()
        for keyword in _DEAL_KEYWORDS:
            if keyword in anchor_text:
                score += 1

        if score > 0:
            scored.append((score, full_url))

    # Dedup by URL, keep highest score
    seen_urls: set[str] = set()
    deduped: list[tuple[int, str]] = []
    for score, url in sorted(scored, key=lambda x: -x[0]):
        if url not in seen_urls:
            seen_urls.add(url)
            deduped.append((score, url))

    # Return top 5 discovered pages
    return [url for _, url in deduped[:5]]


def _discover_pdf_links(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Find PDF links on a page, prioritizing those with deal-related context.

    Returns deduplicated list of absolute PDF URLs, capped at 5 per site.
    """
    pdf_links: list[tuple[int, str]] = []  # (priority_score, url)
    seen: set[str] = set()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        if not href.lower().endswith(".pdf"):
            continue

        full_url = urljoin(base_url, href)
        if full_url in seen:
            continue
        seen.add(full_url)

        # Score by anchor text relevance
        anchor_text = a_tag.get_text(strip=True).lower()
        score = 0
        for kw in ("special", "deal", "happy hour", "lunch", "dinner",
                    "menu", "coupon", "offer", "promo", "weekly", "daily"):
            if kw in anchor_text:
                score += 1
        # Also check surrounding heading/paragraph text
        parent = a_tag.find_parent(["h1", "h2", "h3", "h4", "p", "div"])
        if parent:
            parent_text = parent.get_text(strip=True).lower()
            for kw in ("special", "deal", "happy hour"):
                if kw in parent_text:
                    score += 1

        pdf_links.append((score, full_url))

    # Sort by relevance score, take top 5
    pdf_links.sort(key=lambda x: -x[0])
    return [url for _, url in pdf_links[:5]]


def _parse_pdf_for_deals(
    pdf_url: str,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    region: str,
    seen_deals: set[str],
) -> list[DealSignal]:
    """Download and parse a PDF file for deal signals.

    Uses pdfplumber to extract text, then applies the same deal-validation
    pipeline as text-block extraction. Returns DealSignal objects.
    """
    if not _HAS_PDFPLUMBER:
        logger.debug("[WebScraper] pdfplumber not installed — skipping PDF: %s", pdf_url)
        return []

    signals: list[DealSignal] = []
    try:
        resp = requests.get(
            pdf_url,
            headers={"User-Agent": _get_user_agent()},
            timeout=20,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return []

        # Size guard: skip PDFs larger than 5MB
        if len(resp.content) > 5_000_000:
            logger.debug("[WebScraper] PDF too large (%.1f MB): %s", len(resp.content) / 1e6, pdf_url)
            return []

        with pdfplumber.open(BytesIO(resp.content)) as pdf:
            # Page guard: skip PDFs with more than 20 pages
            if len(pdf.pages) > 20:
                logger.debug("[WebScraper] PDF too many pages (%d): %s", len(pdf.pages), pdf_url)
                return []

            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"

        if not full_text.strip():
            return []

        # Split into blocks by double-newline or significant whitespace
        raw_blocks = re.split(r"\n{2,}|\r\n{2,}", full_text)
        blocks: list[str] = []
        for raw in raw_blocks:
            # Clean up single newlines within a block
            cleaned = re.sub(r"\s+", " ", raw).strip()
            if cleaned and 15 < len(cleaned) < 500:
                blocks.append(cleaned)

        for block in blocks:
            if not _is_valid_deal_block(block):
                continue

            deal_name = block.split(".")[0].strip()[:80]
            if not deal_name or len(deal_name) < 5:
                continue

            name_key = deal_name.lower()
            if name_key in seen_deals:
                continue
            seen_deals.add(name_key)

            price = _extract_price(block)
            deal_type = _classify_deal_type(block)
            valid_days = _extract_days(block)
            start_time, end_time = _extract_times(block)
            calories = _extract_calories(block)

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
                source_url=pdf_url,
                region=region,
                observed_at=datetime.utcnow(),
            ))

    except Exception as e:
        logger.debug("[WebScraper] Failed to parse PDF %s: %s", pdf_url, e)

    return signals


def scrape_restaurant_website(
    url: str,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None = None,
    region: str = "austin_tx",
) -> list[DealSignal]:
    """Scrape a single restaurant's website for deals.

    Enhanced pipeline:
      1. Probe homepage + hardcoded deal paths (8 paths)
      2. Discover additional deal pages from homepage links (up to 4 more)
      3. For each page: extract text blocks + JSON-LD structured data
      4. Collect and parse PDF links found across all pages (up to 3 PDFs)

    Returns list of DealSignals found.
    """
    user_agent = _get_user_agent()
    parsed = urlparse(url)
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    signals: list[DealSignal] = []
    seen_deals: set[str] = set()  # dedup by deal_name
    robots_blocked_count = 0
    all_menu_prices: list[float] = []  # collect all prices across pages for avg
    all_pdf_links: list[str] = []  # collect PDF links across all pages
    discovered_pages: list[str] = []  # track link-discovered pages
    pages_fetched = 0

    # --- Phase 1: Hardcoded paths ---
    homepage_soup = None

    for path in DEAL_PATHS:
        if pages_fetched >= MAX_PAGES_PER_SITE:
            break

        full_url = urljoin(base_url, path)

        # Respect robots.txt
        if not _can_fetch(base_url, path, user_agent):
            logger.debug("[WebScraper] Blocked by robots.txt: %s", full_url)
            robots_blocked_count += 1
            continue

        html = _fetch_page(full_url, user_agent)
        if not html:
            continue

        pages_fetched += 1
        soup = BeautifulSoup(html, "html.parser")

        # Save homepage soup for link discovery
        if path == "/":
            homepage_soup = soup

        # --- Text block extraction ---
        blocks = _extract_text_blocks(soup)
        all_menu_prices.extend(_extract_all_prices(blocks))

        for block in blocks:
            if not _is_valid_deal_block(block):
                continue

            deal_name = block.split(".")[0].strip()[:80]
            if not deal_name or len(deal_name) < 5:
                continue

            name_key = deal_name.lower()
            if name_key in seen_deals:
                continue
            seen_deals.add(name_key)

            price = _extract_price(block)
            deal_type = _classify_deal_type(block)
            valid_days = _extract_days(block)
            start_time, end_time = _extract_times(block)
            calories = _extract_calories(block)

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

        # --- JSON-LD extraction ---
        jsonld_signals = _extract_jsonld_deals(
            html, restaurant_name, local_employer_id,
            brand_group_id, full_url, region, seen_deals,
        )
        signals.extend(jsonld_signals)

        # --- PDF link discovery ---
        all_pdf_links.extend(_discover_pdf_links(soup, base_url))

        # Rate limit: 1 req/sec between pages
        time.sleep(1.0)

    # --- Phase 2: Discover additional deal pages from homepage links ---
    if homepage_soup and pages_fetched < MAX_PAGES_PER_SITE:
        discovered_pages = _discover_deal_pages(homepage_soup, base_url)

        for disc_url in discovered_pages:
            if pages_fetched >= MAX_PAGES_PER_SITE:
                break

            disc_parsed = urlparse(disc_url)
            if not _can_fetch(base_url, disc_parsed.path, user_agent):
                continue

            html = _fetch_page(disc_url, user_agent)
            if not html:
                continue

            pages_fetched += 1
            soup = BeautifulSoup(html, "html.parser")
            blocks = _extract_text_blocks(soup)
            all_menu_prices.extend(_extract_all_prices(blocks))

            for block in blocks:
                if not _is_valid_deal_block(block):
                    continue

                deal_name = block.split(".")[0].strip()[:80]
                if not deal_name or len(deal_name) < 5:
                    continue

                name_key = deal_name.lower()
                if name_key in seen_deals:
                    continue
                seen_deals.add(name_key)

                price = _extract_price(block)
                deal_type = _classify_deal_type(block)
                valid_days = _extract_days(block)
                start_time, end_time = _extract_times(block)
                calories = _extract_calories(block)

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
                    source_url=disc_url,
                    region=region,
                    observed_at=datetime.utcnow(),
                ))

            # JSON-LD on discovered pages too
            jsonld_signals = _extract_jsonld_deals(
                html, restaurant_name, local_employer_id,
                brand_group_id, disc_url, region, seen_deals,
            )
            signals.extend(jsonld_signals)

            # PDF links on discovered pages
            all_pdf_links.extend(_discover_pdf_links(soup, base_url))

            time.sleep(1.0)

    # --- Phase 3: Parse PDF links ---
    # Dedup PDFs and limit to MAX_PDFS_PER_SITE
    unique_pdfs: list[str] = []
    pdf_seen: set[str] = set()
    for pdf_url in all_pdf_links:
        if pdf_url not in pdf_seen:
            pdf_seen.add(pdf_url)
            unique_pdfs.append(pdf_url)

    for pdf_url in unique_pdfs[:MAX_PDFS_PER_SITE]:
        pdf_signals = _parse_pdf_for_deals(
            pdf_url, restaurant_name, local_employer_id,
            brand_group_id, region, seen_deals,
        )
        signals.extend(pdf_signals)
        time.sleep(1.0)

    # If robots.txt blocked ALL hardcoded paths, flag for SpiritPool
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
        skip_checked_days: int | None = None,
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
            url_filters = [
                RestaurantURL.is_active.is_(True),
                LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
                LocalEmployer.region == region,
                LocalEmployer.is_active.is_(True),
            ]
            if skip_checked_days is not None:
                from datetime import timedelta
                cutoff = datetime.utcnow() - timedelta(days=skip_checked_days)
                # Only scrape sites never checked, or checked before the cutoff
                url_filters.append(
                    (RestaurantURL.last_checked.is_(None)) |
                    (RestaurantURL.last_checked < cutoff)
                )
                logger.info(
                    "[WebScraper] Skipping sites checked within the last %d day(s)", skip_checked_days
                )

            urls = session.query(
                RestaurantURL, LocalEmployer
            ).join(
                LocalEmployer, LocalEmployer.id == RestaurantURL.local_employer_id
            ).filter(
                *url_filters
            ).order_by(
                RestaurantURL.last_checked.asc().nullsfirst()
            ).limit(max_sites).all()

            logger.info("[WebScraper] Scanning %d restaurant websites", len(urls))

            blocked_sites: list[dict] = []  # Track sites that block scraping
            audit_entries: list[dict] = []   # Track all scrape outcomes for manual review

            for rurl, emp in urls:
                site_audit: dict[str, Any] = {
                    "employer_id": emp.id,
                    "name": emp.name,
                    "url": rurl.url,
                    "scraped_at": datetime.utcnow().isoformat(),
                    "deals_found": 0,
                    "outcome": "pending",
                }
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
                        site_audit["deals_found"] = len(signals)
                        site_audit["outcome"] = "deals_found"
                        site_audit["deal_names"] = [s.deal_name[:80] for s in signals]
                    else:
                        site_audit["outcome"] = "no_deals"
                        # Grab candidate text blocks for manual review
                        try:
                            html = _fetch_page(rurl.url, _get_user_agent())
                            if html:
                                soup = BeautifulSoup(html, "html.parser")
                                blocks = _extract_text_blocks(soup)
                                # Sample up to 10 blocks for manual review
                                site_audit["sample_blocks"] = [b[:200] for b in blocks[:10]]
                                site_audit["total_blocks"] = len(blocks)
                                # Note if site has PDFs that failed to parse
                                pdf_links = _discover_pdf_links(soup, rurl.url)
                                if pdf_links:
                                    site_audit["pdf_links"] = pdf_links[:5]
                                    site_audit["needs_pdf_reader"] = not _HAS_PDFPLUMBER
                                # Note discovered subpages
                                disc = _discover_deal_pages(soup, rurl.url)
                                if disc:
                                    site_audit["discovered_pages"] = disc
                        except Exception:
                            pass  # audit is best-effort

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
                    site_audit["outcome"] = "robots_blocked"
                    if not dry_run:
                        rurl.last_checked = datetime.utcnow()
                        rurl.last_http_status = 403
                        session.flush()

                except Exception as e:
                    logger.warning("[WebScraper] Error scraping %s: %s", rurl.url, e)
                    site_audit["outcome"] = "error"
                    site_audit["error"] = str(e)[:200]
                    if not dry_run:
                        rurl.last_checked = datetime.utcnow()
                        # Try to extract HTTP status from exception
                        status = getattr(getattr(e, 'response', None), 'status_code', 0)
                        if status:
                            rurl.last_http_status = status
                        session.flush()
                    continue

                finally:
                    audit_entries.append(site_audit)

            if not dry_run:
                session.commit()

            # Write blocked sites for SpiritPool pickup
            if blocked_sites:
                _write_spiritpool_blocked(blocked_sites)

            # Write scrape audit log
            if audit_entries:
                _write_scrape_audit(audit_entries)
                no_deals = sum(1 for e in audit_entries if e["outcome"] == "no_deals")
                has_pdf = sum(1 for e in audit_entries if e.get("pdf_links"))
                has_disc = sum(1 for e in audit_entries if e.get("discovered_pages"))
                logger.info(
                    "[WebScraper] Audit: %d sites scraped, %d no deals, %d have PDFs, %d had discovered pages",
                    len(audit_entries), no_deals, has_pdf, has_disc,
                )
                logger.info("[WebScraper] Audit log written to %s", _SCRAPE_AUDIT_PATH)

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
    skip_checked_days: int | None = None,
) -> dict:
    """Run the website scraper and ingest results."""
    collector = WebsiteDealCollector()
    signals = collector.collect(
        region=region, max_sites=max_sites, dry_run=dry_run,
        skip_checked_days=skip_checked_days,
    )

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
    parser.add_argument(
        "--skip-checked-days", type=int, default=None,
        help="Skip sites already checked within N days (avoids re-scraping fresh data)",
    )
    args = parser.parse_args()

    stats = run_website_scraper(
        region=args.region,
        max_sites=args.max_sites,
        dry_run=args.dry_run,
        skip_checked_days=args.skip_checked_days,
    )
    print(f"\n--- Website Scraper Stats ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")
