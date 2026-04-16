"""
collectors/meal_deals/website_scraper.py — Crawl individual restaurant websites for deals.

For non-chain restaurants that have a URL in restaurant_urls, this module:
  1. Fetches homepage + common deal-related paths (/menu, /specials, /deals, /lunch)
  2. Scans page text for deal-signal keywords (prices, "special", "BOGO", etc.)
  3. Extracts structured DealSignal objects from detected deals
  4. Feeds them through the standard ingest pipeline

robots.txt is IGNORED by default — we are promoting restaurants' own deals
to drive them traffic and customers. Sites that were previously robots-blocked
are re-checked weekly (not every run) to be respectful of server load.

1 req/sec rate limit, uses user-agent rotation.

Depends on: requests, beautifulsoup4, collectors.rotation
Called by: scheduler (Wednesday/Saturday 2:00 AM) or CLI
"""

import hashlib
import json
import logging
import re
import time
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup, Tag

from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.registry import deal_collector
from collectors.meal_deals.temporal import extract_days, extract_times
from collectors.rotation import _load as _load_rotation
from config.paths import CACHE_DIR, WEBSITE_SCRAPE_DEBUG_DIR
from core.venue_identity import cluster_likely_same_venues, normalize_url_for_identity, pick_canonical_item

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

# ── Context-aware pricing patterns ──────────────────────────────────────────
# Words immediately before/after a price that indicate discount (not a meal price)
_DISCOUNT_CONTEXT_RE = re.compile(
    r"(?:\b(?:off|discount|save|saving)\b)",
    re.IGNORECASE,
)

# Words that indicate an absolute deal price
_ABSOLUTE_CONTEXT_RE = re.compile(
    r"(?:\b(?:for|just|only|starting\s+at|from|meal|combo|plate|platter|basket|bucket|box)\b)",
    re.IGNORECASE,
)

# Add-on / modifier patterns — these are NOT deals
_ADDON_CONTEXT_RE = re.compile(
    r"(?:\+\s*\$|(?:\badd\b|\bextra\b|\bupgrade\b|\bsubstitut)\s.{0,15}\$)",
    re.IGNORECASE,
)

# Percentage-off patterns: "half off", "½ off", "50% off", "X% off"
_PERCENTAGE_RE = re.compile(
    r"(?:(\d{1,2})%\s*off)|(?:half\s*(?:off|price))|(?:½\s*(?:off|price))",
    re.IGNORECASE,
)

# Food keywords — allow sub-$1.50 prices if the text mentions these
_FOOD_KEYWORDS_RE = re.compile(
    r"\b(?:wing|wings|taco|tacos|slider|sliders|nugget|nuggets|fry|fries"
    r"|oyster|oysters|shrimp|dumpling|dumplings|pierogi|pierogies"
    r"|egg\s+roll|spring\s+roll|corn\s+dog|mozzarella\s+stick"
    r"|bone[- ]?in|boneless)\b",
    re.IGNORECASE,
)

# Minimum price floor — deals below this are almost always add-ons or noise
_MIN_PRICE_FLOOR = 1.00

# Event / catering / non-food promo patterns
_NON_FOOD_PROMO_RE = re.compile(
    r"\b(?:book|event|catering|wedding|venue|party\s+room|banquet|private\s+dining"
    r"|clearance|sale|apparel|clothing|accessories)\b",
    re.IGNORECASE,
)


@dataclass
class DealPricing:
    """Result of context-aware price extraction."""
    price: float | None = None
    price_type: str | None = None           # absolute | discount_amount | percentage_off | unknown
    discount_percentage: float | None = None
    is_addon: bool = False
    is_non_food: bool = False


def _extract_deal_pricing(text: str) -> DealPricing:
    """Context-aware price extraction.

    Instead of returning the first $X.XX found, this:
    1. Checks for percentage-off patterns first (half off, X% off)
    2. Scans ALL dollar amounts and classifies each by surrounding context
    3. Prefers absolute prices over discount amounts
    4. Detects add-on/modifier prices and non-food promos
    5. Applies a price floor with food-keyword exception
    """
    result = DealPricing()

    # Check for non-food promotions (events, catering, clearance)
    if _NON_FOOD_PROMO_RE.search(text):
        result.is_non_food = True

    # 1. Check for percentage-off patterns
    pct_match = _PERCENTAGE_RE.search(text)
    if pct_match:
        if pct_match.group(1):  # "X% off"
            result.discount_percentage = float(pct_match.group(1))
        else:  # "half off" / "half price" / "½ off"
            result.discount_percentage = 50.0
        result.price_type = "percentage_off"

    # 2. Find all dollar amounts with surrounding context
    absolute_prices: list[float] = []
    discount_prices: list[float] = []
    has_food_keyword = bool(_FOOD_KEYWORDS_RE.search(text))

    for match in _PRICE_RE.finditer(text):
        try:
            price_val = float(match.group(1))
        except ValueError:
            continue

        # Skip obviously broken prices ($0.00, $1500 from "$1,500")
        if price_val == 0.0 or price_val > 200.0:
            continue

        # Get context window: 40 chars before and after the price match
        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        context = text[start:end]

        # Check if this is an add-on price
        addon_start = max(0, match.start() - 20)
        addon_context = text[addon_start:match.end() + 10]
        if _ADDON_CONTEXT_RE.search(addon_context):
            result.is_addon = True
            continue

        # Classify by context
        if _DISCOUNT_CONTEXT_RE.search(context):
            discount_prices.append(price_val)
        elif _ABSOLUTE_CONTEXT_RE.search(context):
            absolute_prices.append(price_val)
        else:
            # No clear context — treat as unknown, but bucket it
            # If percentage already found, this is likely a discount amount
            if result.discount_percentage is not None:
                discount_prices.append(price_val)
            else:
                absolute_prices.append(price_val)

    # 3. Pick the best price
    if absolute_prices:
        # Prefer the largest absolute price (more likely the actual deal, not a side)
        best = max(absolute_prices)
        if best >= _MIN_PRICE_FLOOR or has_food_keyword:
            result.price = best
            result.price_type = "absolute"
    elif discount_prices:
        # Only discount amounts found — store the largest
        best = max(discount_prices)
        result.price = best
        if result.price_type != "percentage_off":
            result.price_type = "discount_amount"
    elif result.discount_percentage is not None:
        # Percentage-off only (no dollar amounts)
        pass  # price stays None, price_type already set
    else:
        # No prices found at all
        return result

    # 4. Price floor check (skip sub-$1.00 unless food keyword present)
    if result.price is not None and result.price < _MIN_PRICE_FLOOR:
        if not has_food_keyword:
            result.is_addon = True
            result.price = None
            result.price_type = None

    return result


# ── Multi-promo splitter ────────────────────────────────────────────────────

# Sentence / clause boundary for splitting a block with multiple promos.
# Looks for periods, exclamation/question marks, newlines, semicolons, or
# pipe/bullet separators followed by whitespace.  A dollar amount starting
# the next clause is also a strong boundary.
_PROMO_SPLIT_RE = re.compile(
    r"(?:[.!?;|•·\n]+\s+)|(?:\s{2,})|(?=\s\$\d)",
)

# A sub-block is valid only if it contains its own price OR its own
# self-validating phrase (BOGO, half-off, etc.)
_SUB_PROMO_MIN_LEN = 5
_SUB_PROMO_MAX_LEN = 250


def _split_multi_promo(block: str) -> list[str]:
    """If `block` contains 3+ distinct prices, split into sub-promos.

    Returns list[str].  A single-element list means the block wasn't split
    (either because it has <3 prices or the split didn't produce multiple
    valid sub-blocks).  Callers can always iterate the result as deals.

    Triggers split only when there are ≥3 `$X` amounts in the block — we keep
    single-price blocks whole so "$5 Combo Meal" doesn't get chopped.
    """
    if not block or len(block) < 20:
        return [block]

    prices = _PRICE_RE.findall(block)
    if len(prices) < 3:
        return [block]

    # Split on clause boundaries / dollar anchors.
    raw_parts = _PROMO_SPLIT_RE.split(block)
    parts: list[str] = []
    for p in raw_parts:
        s = (p or "").strip(" -–—:,\n\t")
        if not s:
            continue
        if not (_SUB_PROMO_MIN_LEN <= len(s) <= _SUB_PROMO_MAX_LEN):
            continue
        # Each sub must contain a price OR a self-validating phrase to be a deal
        lower = s.lower()
        has_price = bool(_PRICE_RE.search(s))
        has_self_valid = any(kw in lower for kw in _SELF_VALIDATING_KEYWORDS)
        has_percentage = bool(_PERCENTAGE_RE.search(s))
        if not (has_price or has_self_valid or has_percentage):
            continue
        parts.append(s)

    # Only consider it a successful split if we got ≥2 valid sub-promos.
    if len(parts) >= 2:
        return parts
    return [block]


# Calorie patterns: "450 cal", "450 calories", "450 kcal", "450Cal"
_CALORIE_RE = re.compile(
    r"(\d{2,4})\s*(?:cal(?:ories?)?|kcal|Cal)\b",
    re.IGNORECASE,
)

# Temporal extraction: use shared module (see collectors.meal_deals.temporal).
# Day and time patterns moved there so chain_deals.py can reuse them.

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


_SCRAPE_AUDIT_PATH = CACHE_DIR / "website_scrape_audit.json"


def _debug_cache_key(url: str) -> str:
    normalized = normalize_url_for_identity(url)
    if normalized:
        return normalized
    return re.sub(r"[^a-z0-9]+", "-", url.strip().lower()).strip("-") or "site"


def _debug_cache_path_from_key(site_key: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "_", site_key).strip("_")[:80] or "site"
    digest = hashlib.sha1(site_key.encode("utf-8")).hexdigest()[:12]
    return WEBSITE_SCRAPE_DEBUG_DIR / f"{slug}__{digest}.json"


def _site_debug_cache_path(url: str) -> Path:
    return _debug_cache_path_from_key(_debug_cache_key(url))


def _serialize_signal(signal: DealSignal) -> dict[str, Any]:
    return {
        "restaurant_name": signal.restaurant_name,
        "address": signal.address,
        "lat": signal.lat,
        "lng": signal.lng,
        "brand_fingerprint": signal.brand_fingerprint,
        "brand_group_id": signal.brand_group_id,
        "local_employer_id": signal.local_employer_id,
        "deal_name": signal.deal_name,
        "deal_description": signal.deal_description,
        "deal_type": signal.deal_type,
        "price": signal.price,
        "price_type": signal.price_type,
        "discount_percentage": signal.discount_percentage,
        "original_price": signal.original_price,
        "menu_avg_price": signal.menu_avg_price,
        "calories": signal.calories,
        "calorie_price_ratio": signal.calorie_price_ratio,
        "valid_days": signal.valid_days,
        "valid_start_time": signal.valid_start_time,
        "valid_end_time": signal.valid_end_time,
        "is_recurring": signal.is_recurring,
        "start_date": signal.start_date.isoformat() if signal.start_date else None,
        "end_date": signal.end_date.isoformat() if signal.end_date else None,
        "source": signal.source,
        "source_url": signal.source_url,
        "region": signal.region,
        "raw_scraped_text": signal.raw_scraped_text,
        "signal_quality": signal.signal_quality,
        "deal_value_score": signal.deal_value_score,
        "sub_deals": deepcopy(signal.sub_deals),
        "metadata": deepcopy(signal.metadata),
        "observed_at": signal.observed_at.isoformat() if signal.observed_at else None,
    }


def _new_site_debug_bundle(base_url: str, *, restaurant_name: str, region: str) -> dict[str, Any]:
    return {
        "site_key": _debug_cache_key(base_url),
        "site_url": base_url,
        "restaurant_name": restaurant_name,
        "region": region,
        "scraped_at": datetime.now(timezone.utc).isoformat(),
        "pages": {},
        "pdfs": {},
        "signals": [],
        "discovered_pages": [],
        "pdf_links": [],
        "menu_avg_price": None,
    }


def _write_site_debug_bundle(bundle: dict[str, Any]) -> None:
    WEBSITE_SCRAPE_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = _debug_cache_path_from_key(bundle["site_key"])
    path.write_text(json.dumps(bundle, indent=2), encoding="utf-8")


def _reset_site_debug_bundle(base_url: str, *, restaurant_name: str, region: str) -> dict[str, Any]:
    path = _site_debug_cache_path(base_url)
    if path.exists():
        path.unlink()
    bundle = _new_site_debug_bundle(base_url, restaurant_name=restaurant_name, region=region)
    _write_site_debug_bundle(bundle)
    return bundle


def _load_site_debug_bundle(base_url: str) -> dict[str, Any] | None:
    path = _site_debug_cache_path(base_url)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _record_debug_page(bundle: dict[str, Any], page_url: str, *, html: str, fetch_type: str) -> None:
    bundle.setdefault("pages", {})[_debug_cache_key(page_url)] = {
        "url": page_url,
        "fetch_type": fetch_type,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "html": html,
    }
    _write_site_debug_bundle(bundle)


def _get_debug_page(bundle: dict[str, Any] | None, page_url: str) -> str | None:
    if not bundle:
        return None
    page = bundle.get("pages", {}).get(_debug_cache_key(page_url))
    if isinstance(page, dict):
        html = page.get("html")
        if isinstance(html, str):
            return html
    return None


def _record_debug_pdf_text(bundle: dict[str, Any], pdf_url: str, *, full_text: str) -> None:
    bundle.setdefault("pdfs", {})[_debug_cache_key(pdf_url)] = {
        "url": pdf_url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "full_text": full_text,
    }
    _write_site_debug_bundle(bundle)


def _get_debug_pdf_text(bundle: dict[str, Any] | None, pdf_url: str) -> str | None:
    if not bundle:
        return None
    pdf = bundle.get("pdfs", {}).get(_debug_cache_key(pdf_url))
    if isinstance(pdf, dict):
        full_text = pdf.get("full_text")
        if isinstance(full_text, str):
            return full_text
    return None


def _finalize_site_debug_bundle(
    bundle: dict[str, Any] | None,
    *,
    signals: list[DealSignal],
    discovered_pages: list[str],
    pdf_links: list[str],
    menu_avg_price: float | None,
) -> None:
    if not bundle:
        return
    bundle["signals"] = [_serialize_signal(signal) for signal in signals]
    bundle["discovered_pages"] = list(discovered_pages)
    bundle["pdf_links"] = list(pdf_links)
    bundle["menu_avg_price"] = menu_avg_price
    bundle["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_site_debug_bundle(bundle)


def _write_scrape_audit(entries: list[dict], append: bool = False) -> None:
    """Write the scrape audit log.

    When append=True, merges new entries into the existing file (used by
    chunked processing so earlier chunks aren't lost).
    """
    _SCRAPE_AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    if append and _SCRAPE_AUDIT_PATH.exists():
        try:
            existing = json.loads(_SCRAPE_AUDIT_PATH.read_text())
            if isinstance(existing, list):
                entries = existing + entries
        except (json.JSONDecodeError, OSError):
            pass  # overwrite if corrupt
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


# Backwards-compatible aliases — implementations live in temporal.py now.
_extract_days = extract_days
_extract_times = extract_times


# ── Deal name extraction ────────────────────────────────────────────────────

# Strong, label-like phrases that make great deal names if present in text.
# Order matters — earlier matches win.
# NOTE: `\b` doesn't anchor before `$`, so `$` patterns use `(?<!\w)` instead.
_DEAL_LABEL_PATTERNS = [
    re.compile(r"\bhappy\s*hour\b", re.IGNORECASE),
    re.compile(r"\bkids\s+eat\s+free\b", re.IGNORECASE),
    re.compile(r"\bearly\s+bird(?:\s+special)?\b", re.IGNORECASE),
    re.compile(r"\blate\s+night(?:\s+special)?\b", re.IGNORECASE),
    re.compile(r"\b(?:lunch|dinner|breakfast|brunch)\s+(?:special|combo|deal)\b", re.IGNORECASE),
    re.compile(r"\b(?:weekly|daily|weekend|weekday)\s+special(?:s)?\b", re.IGNORECASE),
    re.compile(r"\b(?:taco|wing|burger|pizza|pasta|steak|seafood|sushi|margarita)\s+(?:tuesday|wednesday|thursday|monday|night|special|day)\b", re.IGNORECASE),
    re.compile(r"\bbogo\b", re.IGNORECASE),
    re.compile(r"\bbuy\s+one\s*,?\s*get\s+one(?:\s+free)?\b", re.IGNORECASE),
    re.compile(r"(?<!\w)\$\d+(?:\.\d{2})?\s+(?:combo|meal|special|deal|lunch|dinner|burger|pizza|plate|platter|box|bucket|basket|taco|wings?)\b", re.IGNORECASE),
    re.compile(r"\b2\s+for\s+\$\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:half|½)\s+(?:off|price)\s+(?:appetizers?|apps?|drinks?|wine|pizza|burgers?)\b", re.IGNORECASE),
]

# Leading / trailing filler to strip from candidate names
_NAME_STOPWORDS_PREFIX_RE = re.compile(
    r"^(?:check\s+out|take\s+a\s+look|introducing|new\s+deal|don't\s+miss)\s+",
    re.IGNORECASE,
)

# Names that end up being sentence fragments — these markers indicate we
# should fall back to a label search instead of keeping the fragment
_FRAGMENT_MARKERS_RE = re.compile(
    r"(?:\ba\s+spicy\b|\byour\s+choice\s+of\b|\b(?:made|served|seasoned|grilled)\s+with\b"
    r"|\b(?:includ(?:ed|es|ing)?|comes?\s+with|topped\s+with)\b)",
    re.IGNORECASE,
)

# Only trim these from the ends of a snippet (no periods — they're part of prices)
_NAME_TRIM_CHARS = " -–—:,\n\t"


def _trim_name(snippet: str) -> str:
    """Collapse whitespace and strip trim chars from both ends."""
    return re.sub(r"\s+", " ", snippet).strip(_NAME_TRIM_CHARS)


def _extract_deal_name(block: str, fallback_heading: str | None = None) -> str | None:
    """Produce a concise, label-like deal name from a text block.

    Strategy (first match wins):
      1. If `fallback_heading` is a short, non-fragment string, use it.
      2. Search for known deal-label patterns ("Happy Hour", "$5 Combo",
         "BOGO", "Lunch Special", etc.) and return the match expanded up
         to the nearest clause boundary (~70 chars).
      3. Split on sentence boundaries; the first clause that's short,
         not a sentence fragment, and contains a deal keyword wins.
      4. Fallback: first clause trimmed to 70 chars, only if it doesn't
         smell like a sentence fragment.

    Returns None if no acceptable name can be produced — caller should skip.
    """
    if not block:
        return None

    # 1. Heading preference
    if fallback_heading:
        h = _trim_name(fallback_heading)
        h = _NAME_STOPWORDS_PREFIX_RE.sub("", h)
        if 3 <= len(h) <= 80 and not _FRAGMENT_MARKERS_RE.search(h):
            return h[:80]

    # 2. Label-pattern search — expand match to nearest clause boundary.
    for pat in _DEAL_LABEL_PATTERNS:
        m = pat.search(block)
        if not m:
            continue
        # Find a reasonable end: prefer a comma or "featuring"/"with" split,
        # fall back to 70 chars past the match start.
        start = m.start()
        stop_search = re.search(
            r"[.!?\n]|\s(?:featuring|including|with|served)\s",
            block[m.end():m.end() + 80],
            re.IGNORECASE,
        )
        end = m.end() + (stop_search.start() if stop_search else min(40, len(block) - m.end()))
        end = min(len(block), end)
        snippet = _trim_name(block[start:end])
        if 3 <= len(snippet) <= 80:
            return snippet
        # Very long — just return the bare match
        bare = _trim_name(m.group(0))
        if bare:
            return bare[:80]

    # 3. Short-clause scan
    for clause in re.split(r"[.!?\n]", block):
        c = _trim_name(clause)
        if not (5 <= len(c) <= 70):
            continue
        if _FRAGMENT_MARKERS_RE.search(c):
            continue
        lower = c.lower()
        if any(kw in lower for kw in (
            "special", "deal", "combo", "happy hour", "bogo",
            "kids eat", "lunch", "dinner", "discount", " off",
        )):
            return c[:80]

    # 4. Last resort: first short clause if it doesn't look like a fragment
    first = _trim_name(re.split(r"[.!?\n]", block, maxsplit=1)[0])
    if 5 <= len(first) <= 70 and not _FRAGMENT_MARKERS_RE.search(first):
        return first[:80]

    return None


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
        observed_at=datetime.now(timezone.utc),
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
        observed_at=datetime.now(timezone.utc),
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


def _text_block_to_signals(
    block: str,
    *,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
) -> list[DealSignal]:
    """Convert a single text block into 0-or-more DealSignals.

    Applies the multi-promo splitter first, then runs the existing
    extraction pipeline on each sub-block.  Handles dedup against
    `seen_deals` (mutated in place) and skips add-on / non-food promos.
    """
    results: list[DealSignal] = []
    if not _is_valid_deal_block(block):
        return results

    for sub in _split_multi_promo(block):
        deal_name = _extract_deal_name(sub)
        if not deal_name or len(deal_name) < 5:
            continue

        name_key = deal_name.lower()
        if name_key in seen_deals:
            continue
        seen_deals.add(name_key)

        pricing = _extract_deal_pricing(sub)
        if pricing.is_addon or pricing.is_non_food:
            continue

        deal_type = _classify_deal_type(sub)
        valid_days = _extract_days(sub)
        start_time, end_time = _extract_times(sub)
        calories = _extract_calories(sub)

        calorie_price_ratio = None
        if calories and pricing.price and pricing.price > 0:
            calorie_price_ratio = round(calories / pricing.price, 1)

        results.append(DealSignal(
            restaurant_name=restaurant_name,
            local_employer_id=local_employer_id,
            brand_group_id=brand_group_id,
            deal_name=deal_name,
            deal_description=sub[:500],
            deal_type=deal_type,
            price=pricing.price,
            price_type=pricing.price_type,
            discount_percentage=pricing.discount_percentage,
            calories=calories,
            calorie_price_ratio=calorie_price_ratio,
            valid_days=valid_days,
            valid_start_time=start_time,
            valid_end_time=end_time,
            raw_scraped_text=sub,
            source="website_scrape",
            source_url=source_url,
            region=region,
            observed_at=datetime.now(timezone.utc),
        ))

    return results


def _pdf_text_to_signals(
    full_text: str,
    *,
    pdf_url: str,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    region: str,
    seen_deals: set[str],
) -> list[DealSignal]:
    """Convert extracted PDF text into deal signals."""
    if not full_text.strip():
        return []

    signals: list[DealSignal] = []
    raw_blocks = re.split(r"\n{2,}|\r\n{2,}", full_text)
    blocks: list[str] = []
    for raw in raw_blocks:
        cleaned = re.sub(r"\s+", " ", raw).strip()
        if cleaned and 15 < len(cleaned) < 500:
            blocks.append(cleaned)

    for block in blocks:
        signals.extend(_text_block_to_signals(
            block,
            restaurant_name=restaurant_name,
            local_employer_id=local_employer_id,
            brand_group_id=brand_group_id,
            source_url=pdf_url,
            region=region,
            seen_deals=seen_deals,
        ))

    return signals


def _download_pdf_text(pdf_url: str) -> str | None:
    """Download a PDF and extract plain text for later parsing."""
    if not _HAS_PDFPLUMBER:
        logger.debug("[WebScraper] pdfplumber not installed — skipping PDF: %s", pdf_url)
        return None

    try:
        resp = requests.get(
            pdf_url,
            headers={"User-Agent": _get_user_agent()},
            timeout=20,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None

        # Size guard: skip PDFs larger than 5MB
        if len(resp.content) > 5_000_000:
            logger.debug("[WebScraper] PDF too large (%.1f MB): %s", len(resp.content) / 1e6, pdf_url)
            return None

        with pdfplumber.open(BytesIO(resp.content)) as pdf:
            # Page guard: skip PDFs with more than 20 pages
            if len(pdf.pages) > 20:
                logger.debug("[WebScraper] PDF too many pages (%d): %s", len(pdf.pages), pdf_url)
                return None

            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"

        return full_text.strip() or None

    except Exception as e:
        logger.debug("[WebScraper] Failed to parse PDF %s: %s", pdf_url, e)
        return None

    return None


def _parse_pdf_for_deals(
    pdf_url: str,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    region: str,
    seen_deals: set[str],
    *,
    debug_bundle: dict[str, Any] | None = None,
    replay_debug_cache: bool = False,
) -> list[DealSignal]:
    """Parse a PDF for deal signals, using local debug cache when requested."""
    if replay_debug_cache:
        full_text = _get_debug_pdf_text(debug_bundle, pdf_url)
        if full_text is None:
            logger.debug("[WebScraper] No cached PDF text for %s", pdf_url)
            return []
    else:
        full_text = _download_pdf_text(pdf_url)
        if full_text and debug_bundle is not None:
            _record_debug_pdf_text(debug_bundle, pdf_url, full_text=full_text)

    if not full_text:
        return []

    return _pdf_text_to_signals(
        full_text,
        pdf_url=pdf_url,
        restaurant_name=restaurant_name,
        local_employer_id=local_employer_id,
        brand_group_id=brand_group_id,
        region=region,
        seen_deals=seen_deals,
    )


def scrape_restaurant_website(
    url: str,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None = None,
    region: str = "austin_tx",
    replay_debug_cache: bool = False,
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
    debug_bundle = _load_site_debug_bundle(url) if replay_debug_cache else _reset_site_debug_bundle(
        url,
        restaurant_name=restaurant_name,
        region=region,
    )
    if replay_debug_cache and debug_bundle is None:
        logger.warning("[WebScraper] No local debug cache for %s", url)
        return []

    signals: list[DealSignal] = []
    seen_deals: set[str] = set()  # dedup by deal_name
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

        html = _get_debug_page(debug_bundle, full_url) if replay_debug_cache else _fetch_page(full_url, user_agent)
        if not html:
            continue
        if not replay_debug_cache and debug_bundle is not None:
            _record_debug_page(debug_bundle, full_url, html=html, fetch_type="hardcoded")

        pages_fetched += 1
        soup = BeautifulSoup(html, "html.parser")

        # Save homepage soup for link discovery
        if path == "/":
            homepage_soup = soup

        # --- Text block extraction ---
        blocks = _extract_text_blocks(soup)
        all_menu_prices.extend(_extract_all_prices(blocks))

        for block in blocks:
            signals.extend(_text_block_to_signals(
                block,
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                source_url=full_url,
                region=region,
                seen_deals=seen_deals,
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

            html = _get_debug_page(debug_bundle, disc_url) if replay_debug_cache else _fetch_page(disc_url, user_agent)
            if not html:
                continue
            if not replay_debug_cache and debug_bundle is not None:
                _record_debug_page(debug_bundle, disc_url, html=html, fetch_type="discovered")

            pages_fetched += 1
            soup = BeautifulSoup(html, "html.parser")
            blocks = _extract_text_blocks(soup)
            all_menu_prices.extend(_extract_all_prices(blocks))

            for block in blocks:
                signals.extend(_text_block_to_signals(
                    block,
                    restaurant_name=restaurant_name,
                    local_employer_id=local_employer_id,
                    brand_group_id=brand_group_id,
                    source_url=disc_url,
                    region=region,
                    seen_deals=seen_deals,
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
            debug_bundle=debug_bundle,
            replay_debug_cache=replay_debug_cache,
        )
        signals.extend(pdf_signals)
        time.sleep(1.0)

    # Compute menu average price and attach to each signal
    menu_avg_price = None
    if all_menu_prices and len(all_menu_prices) >= 3:
        menu_avg_price = round(sum(all_menu_prices) / len(all_menu_prices), 2)
        for sig in signals:
            sig.menu_avg_price = menu_avg_price

    _finalize_site_debug_bundle(
        debug_bundle,
        signals=signals,
        discovered_pages=discovered_pages,
        pdf_links=unique_pdfs,
        menu_avg_price=menu_avg_price,
    )

    return signals


def _copy_signal_for_location(signal: DealSignal, employer: Any, *, region: str) -> DealSignal:
    """Copy a scraped signal to another location without dropping extracted fields."""
    return replace(
        signal,
        restaurant_name=employer.name,
        address=employer.address or signal.address,
        lat=employer.lat,
        lng=employer.lng,
        brand_fingerprint=None,
        local_employer_id=employer.id,
        brand_group_id=employer.brand_group_id,
        region=region,
        sub_deals=deepcopy(signal.sub_deals),
        metadata=deepcopy(signal.metadata),
    )


def _collapse_shared_url_aliases(group: list[tuple]) -> tuple[list[tuple], list[tuple]]:
    """Collapse same-URL alias employers down to one canonical venue row."""
    if len(group) <= 1:
        return group, []

    original_index = {id(item): index for index, item in enumerate(group)}
    clusters = cluster_likely_same_venues(
        group,
        get_name=lambda item: item[1].name,
        get_address=lambda item: item[1].address,
        get_url=lambda item: item[0].url,
        get_lat=lambda item: item[1].lat,
        get_lng=lambda item: item[1].lng,
    )

    canonical_items: list[tuple[int, tuple]] = []
    skipped_items: list[tuple] = []
    for cluster in clusters:
        canonical = pick_canonical_item(
            cluster,
            get_id=lambda item: item[1].id,
            get_brand_group_id=lambda item: item[1].brand_group_id,
            get_address=lambda item: item[1].address,
        )
        canonical_items.append((min(original_index[id(item)] for item in cluster), canonical))
        skipped_items.extend(item for item in cluster if item is not canonical)

    canonical_items.sort(key=lambda pair: pair[0])
    return [item for _, item in canonical_items], skipped_items


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

    CHUNK_SIZE = 100  # Scrape/ingest in batches to avoid data loss and RAM buildup

    def collect(
        self,
        region: str = "austin_tx",
        max_sites: int = 100,
        dry_run: bool = False,
        skip_checked_days: int | None = 3,
        replay_debug_cache: bool = False,
    ) -> list[DealSignal]:
        """Scrape websites and return DealSignals.

        Processes in chunks of CHUNK_SIZE unique URLs.  After each chunk the
        DB is committed (last_checked updates), signals are ingested, and the
        audit log is flushed to disk.  This means a crash at site #350 still
        keeps the first 300 sites' data.
        """
        from collections import defaultdict
        from core.database import LocalEmployer, MealDeal, RestaurantURL, get_engine, get_session, init_db

        engine = init_db()
        session = get_session(engine)

        all_signals: list[DealSignal] = []
        url_groups: dict[str, list[tuple]] = {}

        try:
            # ── Build URL list ──────────────────────────────────────────
            url_filters = [
                RestaurantURL.is_active.is_(True),
                LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
                LocalEmployer.region == region,
                LocalEmployer.is_active.is_(True),
            ]
            if skip_checked_days:  # 0 or None means "scrape all"
                from datetime import timedelta
                cutoff = datetime.now(timezone.utc) - timedelta(days=skip_checked_days)
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

            # ── Deduplicate by URL ──────────────────────────────────────
            url_groups_raw: dict[str, list[tuple]] = defaultdict(list)
            for rurl, emp in urls:
                normalized = rurl.url.rstrip("/").lower()
                url_groups_raw[normalized].append((rurl, emp))
            # Convert to regular dict so we can slice it
            url_groups = dict(url_groups_raw)

            total_unique = len(url_groups)
            logger.info(
                "[WebScraper] Scanning %d unique websites (%d restaurant_url rows)",
                total_unique, len(urls),
            )

            # ── Process in chunks ───────────────────────────────────────
            # Clear audit log at the start of a fresh run
            if _SCRAPE_AUDIT_PATH.exists():
                _SCRAPE_AUDIT_PATH.unlink()

            group_items = list(url_groups.items())
            total_ingested = 0
            is_first_chunk = True

            for chunk_start in range(0, len(group_items), self.CHUNK_SIZE):
                chunk = group_items[chunk_start : chunk_start + self.CHUNK_SIZE]
                chunk_num = chunk_start // self.CHUNK_SIZE + 1
                chunk_end = min(chunk_start + self.CHUNK_SIZE, len(group_items))
                logger.info(
                    "[WebScraper] ── Chunk %d: sites %d–%d of %d ──",
                    chunk_num, chunk_start + 1, chunk_end, total_unique,
                )

                chunk_signals: list[DealSignal] = []
                chunk_audit: list[dict] = []

                for _norm_url, group in chunk:
                    canonical_group, alias_rows = _collapse_shared_url_aliases(group)
                    rurl_rep, emp_rep = canonical_group[0]

                    if alias_rows:
                        logger.info(
                            "[WebScraper] Collapsed %d alias rows for %s at %s",
                            len(alias_rows),
                            emp_rep.name,
                            rurl_rep.url,
                        )

                    site_audit: dict[str, Any] = {
                        "employer_id": emp_rep.id,
                        "name": emp_rep.name,
                        "url": rurl_rep.url,
                        "debug_cache_key": _debug_cache_key(rurl_rep.url),
                        "locations_sharing_url": len(group),
                        "canonical_locations": len(canonical_group),
                        "alias_rows_collapsed": len(alias_rows),
                        "scraped_at": datetime.now(timezone.utc).isoformat(),
                        "deals_found": 0,
                        "outcome": "pending",
                    }
                    try:
                        signals = scrape_restaurant_website(
                            url=rurl_rep.url,
                            restaurant_name=emp_rep.name,
                            local_employer_id=emp_rep.id,
                            brand_group_id=emp_rep.brand_group_id,
                            region=region,
                            replay_debug_cache=replay_debug_cache,
                        )

                        if signals:
                            logger.info(
                                "[WebScraper] %s: %d deals found at %s (%d locations)",
                                emp_rep.name, len(signals), rurl_rep.url, len(canonical_group),
                            )
                            # Fan out signals to every location sharing this URL,
                            # but ONLY if the location belongs to the same brand.
                            # If employers with different brand groups share a URL
                            # (data quality issue), skip the mismatched ones to
                            # prevent wrong deals from leaking across businesses.
                            rep_bg = emp_rep.brand_group_id
                            for rurl_loc, emp_loc in canonical_group:
                                if len(canonical_group) > 1 and emp_loc.brand_group_id != rep_bg:
                                    logger.warning(
                                        "[WebScraper] Skipping fan-out of %s deals to %s "
                                        "(brand_group %s ≠ %s) — URL shared across brands",
                                        emp_rep.name, emp_loc.name,
                                        emp_loc.brand_group_id, rep_bg,
                                    )
                                    continue
                                for sig in signals:
                                    loc_sig = _copy_signal_for_location(sig, emp_loc, region=region)
                                    chunk_signals.append(loc_sig)
                            site_audit["deals_found"] = len(signals)
                            site_audit["outcome"] = "deals_found"
                            site_audit["deal_names"] = [s.deal_name[:80] for s in signals]
                        else:
                            site_audit["outcome"] = "no_deals"
                            try:
                                cached_bundle = _load_site_debug_bundle(rurl_rep.url) if replay_debug_cache else None
                                html = _get_debug_page(cached_bundle, rurl_rep.url) if replay_debug_cache else _fetch_page(rurl_rep.url, _get_user_agent())
                                if html:
                                    soup = BeautifulSoup(html, "html.parser")
                                    blocks = _extract_text_blocks(soup)
                                    site_audit["sample_blocks"] = [b[:200] for b in blocks[:10]]
                                    site_audit["total_blocks"] = len(blocks)
                                    pdf_links = _discover_pdf_links(soup, rurl_rep.url)
                                    if pdf_links:
                                        site_audit["pdf_links"] = pdf_links[:5]
                                        site_audit["needs_pdf_reader"] = not _HAS_PDFPLUMBER
                                    disc = _discover_deal_pages(soup, rurl_rep.url)
                                    if disc:
                                        site_audit["discovered_pages"] = disc
                            except Exception:
                                pass  # audit is best-effort

                        # Update ALL restaurant_url records sharing this URL
                        if not dry_run:
                            for rurl_loc, _emp_loc in group:
                                rurl_loc.last_checked = datetime.now(timezone.utc)
                                rurl_loc.has_deals_page = len(signals) > 0
                                rurl_loc.last_http_status = 200
                            session.flush()

                    except Exception as e:
                        logger.warning("[WebScraper] Error scraping %s: %s", rurl_rep.url, e)
                        site_audit["outcome"] = "error"
                        site_audit["error"] = str(e)[:200]
                        if not dry_run:
                            status = getattr(getattr(e, 'response', None), 'status_code', 0)
                            for rurl_loc, _emp_loc in group:
                                rurl_loc.last_checked = datetime.now(timezone.utc)
                                if status:
                                    rurl_loc.last_http_status = status
                            session.flush()

                    finally:
                        chunk_audit.append(site_audit)

                # ── End of chunk: commit, ingest, flush audit ───────────
                if not dry_run:
                    session.commit()

                # Ingest this chunk's signals immediately
                if not dry_run and chunk_signals:
                    from collectors.meal_deals.ingest import ingest_deal_signals
                    stats = ingest_deal_signals(chunk_signals, region=region)
                    total_ingested += stats.get("total_rows", 0)
                    logger.info(
                        "[WebScraper] Chunk %d ingested: %d rows (%d total so far)",
                        chunk_num, stats.get("total_rows", 0), total_ingested,
                    )

                all_signals.extend(chunk_signals)

                # Append audit entries (first chunk overwrites, rest append)
                if chunk_audit:
                    _write_scrape_audit(chunk_audit, append=not is_first_chunk)
                    is_first_chunk = False
                    deals_found = sum(1 for e in chunk_audit if e["outcome"] == "deals_found")
                    logger.info(
                        "[WebScraper] Chunk %d audit: %d scraped, %d with deals",
                        chunk_num, len(chunk_audit), deals_found,
                    )

                # Free memory between chunks
                del chunk_signals, chunk_audit

        except Exception as exc:
            session.rollback()
            logger.error("[WebScraper] Collection failed: %s", exc, exc_info=True)
        finally:
            session.close()

        logger.info(
            "[WebScraper] Done: %d deal signals from %d unique sites (%d ingested to DB)",
            len(all_signals), len(url_groups), total_ingested,
        )
        return all_signals


def run_website_scraper(
    region: str = "austin_tx",
    max_sites: int = 100,
    dry_run: bool = False,
    skip_checked_days: int | None = 3,
    replay_debug_cache: bool = False,
) -> dict:
    """Run the website scraper.

    Ingestion happens per-chunk inside collect() — no bulk ingest at the end.
    """
    collector = WebsiteDealCollector()
    signals = collector.collect(
        region=region, max_sites=max_sites, dry_run=dry_run,
        skip_checked_days=skip_checked_days,
        replay_debug_cache=replay_debug_cache,
    )

    return {
        "signals_found": len(signals),
        "dry_run": dry_run,
        "replay_debug_cache": replay_debug_cache,
    }


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    parser = argparse.ArgumentParser(description="Scrape restaurant websites for meal deals")
    parser.add_argument("--max-sites", type=int, default=100, help="Max sites to scrape (default: 100)")
    parser.add_argument("--all", action="store_true", help="Scan ALL sites (overrides --max-sites)")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB")
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument(
        "--skip-checked-days", type=int, default=3,
        help="Skip sites already checked within N days (default: 3). Use 0 to force re-scrape all.",
    )
    parser.add_argument(
        "--replay-debug-cache",
        action="store_true",
        help="Replay locally saved website scrape bundles instead of re-fetching pages.",
    )
    args = parser.parse_args()

    max_sites = 999999 if args.all else args.max_sites

    stats = run_website_scraper(
        region=args.region,
        max_sites=max_sites,
        dry_run=args.dry_run,
        skip_checked_days=args.skip_checked_days,
        replay_debug_cache=args.replay_debug_cache,
    )
    print(f"\n--- Website Scraper Stats ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")
