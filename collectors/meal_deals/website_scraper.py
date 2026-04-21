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
from collections import deque
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from html import unescape
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
import requests
from bs4 import BeautifulSoup, Tag

from collectors.meal_deals.hint_registry import (
    Hint,
    annotate_exploration_use,
    find_hints,
    load_hints,
)
from collectors.meal_deals.menu_db_writer import upsert_menu_shape
from collectors.meal_deals.menu_persistence_schema import (
    serialize_sidecar,
    summarize_shape,
)
from collectors.meal_deals.menu_sidecar import (
    MenuSidecar,
    ingest_dom_fallback,
    ingest_jsonld_from_html,
    ingest_pdf_tables,
    link_signal_to_target,
)
from collectors.meal_deals.models import DealSignal
from collectors.meal_deals.registry import deal_collector
from collectors.meal_deals.render_policy import (
    PageEvidence,
    RenderBudget,
    should_render,
)
from collectors.meal_deals.website_scrape_audit_utils import classify_domain_family, summarize_debug_bundle
from collectors.meal_deals.temporal import extract_days, extract_times
from collectors.rotation import _load as _load_rotation
from config.paths import CACHE_DIR, WEBSITE_SCRAPE_DEBUG_DIR
from core.database import get_engine, get_session
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
    "/promos",
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
    "2 for 1", "two for one",
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
    "was this helpful",
    "thank you for your feedback",
]

_SOFT_BOILERPLATE_PHRASES = frozenset([
    "rewards", "sign in", "log in", "sign up",
    "download the app", "mobile app",
])

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
    r"|clearance|sale|apparel|clothing|accessories|game\s*play|gaming|arcade"
    r"|all\s+you\s+can\s+play|play\s*points?|fun\s+pass|adventure\s+zone)\b",
    re.IGNORECASE,
)


_FAQ_BLOCK_RE = re.compile(
    r"^\s*(?:does|do|what|when|where|which|who|how|can|is|are)\b.{0,180}\?",
    re.IGNORECASE,
)
_INVALID_DEAL_NAME_RE = re.compile(
    r"^\s*(?:"
    r"available\s+at\s+participating\s+locations"
    r"|(?:cannot|can't)\s+be\s+combined\s+with\s+other\s+offers"
    r"|terms\s+apply"
    r"|restrictions\s+apply"
    r"|daily\s+deals?\s*&\s*happy\s+hour"
    r"|happy\s+hour\s+specials?"
    r"|happy\s+hour\s+items?\s*&\s*pricing.*"
    r"|items?\s*&\s*pricing.*"
    r"|only\s+for\s+dine-?in\s+customers?"
    r"|was\s+this\s+helpful"
    r"|thank\s+you\s+for\s+your\s+feedback"
    r")\s*$",
    re.IGNORECASE,
)
_QUESTION_NAME_RE = re.compile(
    r"^\s*(?:does|do|what|when|where|which|who|how|can|is|are)\b.{0,180}\?\s*$",
    re.IGNORECASE,
)
_VARIANT_ONLY_NAME_RE = re.compile(
    r"^\s*(?:"
    r"choice\s+of\b.{0,60}"
    r"|combo\s*\([^)]{1,40}\)"
    r"|(?:beef|chicken|vegetable|veggie|shrimp|fish|pork|tofu|paneer|cheese)"
    r")\s*$",
    re.IGNORECASE,
)
_MENU_BADGE_PROMO_RE = re.compile(
    r"\b(?:discount\s+of\s+\d{1,2}%|\d{1,2}%\s*off|orders?\s+above\s+\$\d|offer\s+code|use\s+code)\b",
    re.IGNORECASE,
)
_MENU_UI_NOISE_RE = re.compile(
    r"\b(?:add\s+to\s+cart|our\s+most\s+popular\s+dishes|popular\s+dishes|explore\s+more|menu\s+categories|creativity\s+is\s+always\s+on\s+our\s+menu|see\s+more)\b",
    re.IGNORECASE,
)
_MENU_PAGE_URL_MARKERS = (
    "food-menu",
    "drink-menu",
    "drinks-menu",
    "bar-menu",
    "cocktail-menu",
    "dessert-menu",
    "desserts-menu",
    "breakfast-menu",
    "brunch-menu",
    "dinner-menu",
)
_PROMOISH_PATH_MARKERS = (
    "special",
    "deal",
    "offer",
    "promo",
    "promotion",
    "happy-hour",
    "happy_hour",
    "happyhours",
    "lunch",
    "daily",
    "brunch",
    "dinner",
)
_TRAILING_PERCENT_BADGE_RE = re.compile(
    r"(?:\d{1,2}%\s*off\s+\$\d{1,3}(?:\.\d{2})?|\$\d{1,3}(?:\.\d{2})?\s+\d{1,2}%\s*off)(?:\s+\d{1,2}%\s*off)?$",
    re.IGNORECASE,
)
_ORDER_THRESHOLD_PROMO_RE = re.compile(
    r"\b(?:orders?\s+above|minimum\s+order|offer\s+code|use\s+code|read\s+more|free\s+with|buy\s+one|get\s+one)\b",
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
    "2 for 1": "bogo",
    "two for one": "bogo",
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
_NEXT_DATA_SCRIPT_ID = "__NEXT_DATA__"

_JSONLD_INLINE_PRICE_RE = re.compile(r"(?<![\d$])(\d{1,3}\.\d{2})(?!\d)")
_JSONLD_CONTEXT_NOISE_RE = re.compile(r"\bno\s+substitutions?\b", re.IGNORECASE)

# Schema.org types that may contain deals or menu items with prices
_DEAL_SCHEMA_TYPES = frozenset([
    "Offer", "AggregateOffer", "MenuItem", "MenuSection",
    "Menu", "Restaurant", "FoodEstablishment",
])

_JSONLD_PROMO_CONTEXT_KEYWORDS = frozenset([
    "special",
    "specials",
    "deal",
    "deals",
    "promo",
    "promotion",
    "promotions",
    "happy hour",
    "bogo",
    "buy one get one",
    "kids eat free",
    "prix fixe",
    "limited time",
])

# URL path fragments that suggest a deal-related page (for link discovery)
_DEAL_URL_KEYWORDS = frozenset([
    "special", "specials", "deal", "deals", "offer", "offers",
    "promo", "promotion", "promotions", "happy-hour", "happyhour",
    "lunch", "dinner", "menu", "price", "coupon", "coupons",
    "combo", "value", "discount", "weekly", "daily", "today",
])

_DISCOVERY_CONTEXT_KEYWORDS = frozenset([
    "special", "specials", "deal", "deals", "offer", "offers",
    "promo", "promotion", "promotions", "happy hour", "coupon",
    "discount", "save", "limited time", "bogo", "buy one get one",
    "lunch", "dinner", "daily", "weekly", "menu", "menus",
    "food", "drink", "drinks", "beer", "wine", "cocktail", "cocktails",
])

_BROAD_MENU_DISCOVERY_CONTEXT_KEYWORDS = frozenset(
    set(_DISCOVERY_CONTEXT_KEYWORDS) | {
        "order", "order online", "view menu", "beers on tap", "beer on tap",
    }
)

_DISCOVERY_SOFT_LABELS = frozenset([
    "learn more",
    "see details",
    "details",
    "more info",
    "view details",
])

_DISCOVERY_FOOTER_TOKENS = frozenset([
    "footer",
    "site-footer",
    "bottom",
])

_LOCATOR_HINT_TEXT_KEYWORDS = frozenset([
    "deal", "deals", "offer", "offers", "promo", "promotion",
    "promotions", "special", "specials", "happy hour", "lunch",
    "menu",
])

_LOCATOR_HINT_EXCLUDED_TOKENS = frozenset([
    "apparel",
    "itunes.apple.com",
    "play.google.com",
    "google play",
    "app store",
    "careers",
    "jobs",
])

_LOCATOR_HINT_PATHS = (
    "/",
    "/deals",
    "/offers",
    "/promotions",
)

_LOCATOR_HINT_HOST_RULES = {
    "locations.dennys.com": "https://www.dennys.com",
    "locations.tropicalsmoothiecafe.com": "https://www.tropicalsmoothiecafe.com",
}

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

_LOW_MENU_COVERAGE_THRESHOLD = 15


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
        "hinted_pages": [],
        "pdf_links": [],
        "menu_avg_price": None,
    }


_SKIP_DOMAIN_FAMILIES = frozenset({
    "social",
    "government",
    "directory",
    "hotel",
    "other_nonrestaurant",
})


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


def _get_replay_page(bundle: dict[str, Any] | None, page_url: str) -> str | None:
    html = _get_debug_page(bundle, page_url)
    if html:
        return html

    parsed = urlparse(page_url)
    if not parsed.scheme or not parsed.netloc:
        return None

    candidate_urls = [
        page_url,
        f"{parsed.scheme}://{parsed.netloc}",
    ]
    seen_site_keys: set[str] = set()
    primary_site_key = bundle.get("site_key") if isinstance(bundle, dict) else None
    if isinstance(primary_site_key, str) and primary_site_key:
        seen_site_keys.add(primary_site_key)

    for candidate_url in candidate_urls:
        candidate_bundle = _load_site_debug_bundle(candidate_url)
        if not candidate_bundle:
            continue
        site_key = candidate_bundle.get("site_key")
        if isinstance(site_key, str) and site_key in seen_site_keys:
            continue
        if isinstance(site_key, str) and site_key:
            seen_site_keys.add(site_key)
        html = _get_debug_page(candidate_bundle, page_url)
        if html:
            return html

    return None


def _record_debug_pdf_text(
    bundle: dict[str, Any],
    pdf_url: str,
    *,
    full_text: str,
    tables: list[list[list[str | None]]] | None = None,
) -> None:
    entry: dict[str, Any] = {
        "url": pdf_url,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "full_text": full_text,
    }
    if tables:
        entry["tables"] = tables
    bundle.setdefault("pdfs", {})[_debug_cache_key(pdf_url)] = entry
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


def _get_debug_pdf_tables(
    bundle: dict[str, Any] | None,
    pdf_url: str,
) -> list[list[list[str | None]]]:
    if not bundle:
        return []
    pdf = bundle.get("pdfs", {}).get(_debug_cache_key(pdf_url))
    if isinstance(pdf, dict):
        tables = pdf.get("tables")
        if isinstance(tables, list):
            return tables
    return []


def _extract_blocks_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    return _extract_text_blocks(soup)


def _site_audit_context_from_debug_bundle(base_url: str) -> dict[str, Any]:
    bundle = _load_site_debug_bundle(base_url)
    if not bundle:
        return {}

    summary = summarize_debug_bundle(bundle, extract_text_blocks=_extract_blocks_from_html)
    context: dict[str, Any] = {
        "page_count": summary["page_count"],
        "page_fetch_types": summary["page_fetch_types"],
        "structured_data_present": summary["has_jsonld"],
        "parsed_pdf_count": summary["parsed_pdf_count"],
        "menu_avg_price": summary["menu_avg_price"],
        "bundle_signal_count": summary["signal_count"],
    }

    if summary["total_blocks"] is not None:
        context["total_blocks"] = summary["total_blocks"]
    if summary["sample_blocks"]:
        context["sample_blocks"] = summary["sample_blocks"]
    if summary["discovered_pages"]:
        context["discovered_pages"] = summary["discovered_pages"]
        context["discovered_page_count"] = len(summary["discovered_pages"])
    if summary["hinted_pages"]:
        context["hinted_pages"] = summary["hinted_pages"]
        context["hinted_page_count"] = len(summary["hinted_pages"])
    if summary["pdf_links"]:
        context["pdf_links"] = summary["pdf_links"][:5]
        context["needs_pdf_reader"] = not _HAS_PDFPLUMBER

    return context


def _finalize_site_debug_bundle(
    bundle: dict[str, Any] | None,
    *,
    signals: list[DealSignal],
    discovered_pages: list[str],
    hinted_pages: list[dict[str, Any]],
    pdf_links: list[str],
    menu_avg_price: float | None,
    sidecar: MenuSidecar | None = None,
    render_decisions: list[dict[str, Any]] | None = None,
    render_budget: RenderBudget | None = None,
    restaurant_id: str | None = None,
    source_url: str | None = None,
) -> None:
    if not bundle:
        return
    bundle["signals"] = [_serialize_signal(signal) for signal in signals]
    bundle["discovered_pages"] = list(discovered_pages)
    bundle["hinted_pages"] = [deepcopy(page) for page in hinted_pages]
    bundle["pdf_links"] = list(pdf_links)
    bundle["menu_avg_price"] = menu_avg_price
    if sidecar is not None and (sidecar.sections or sidecar.items or sidecar.price_points):
        bundle["menu_sidecar"] = sidecar.to_dict()
        # ARCH-01: also emit the target persistent row shape so replay
        # bundles are forward-compatible with a future menu_graph schema.
        try:
            shape = serialize_sidecar(
                sidecar,
                restaurant_id=restaurant_id,
                source_url=source_url,
                source_bundle=bundle.get("site_key"),
            )
            bundle["menu_persistence_shape"] = shape
            bundle["menu_persistence_summary"] = summarize_shape(shape)
        except Exception as exc:  # pragma: no cover — never let serializer crash a scrape
            logger.warning("[WebScraper] persistence serializer failed: %s", exc)
    if render_decisions:
        # ARCH-03: audit-only render decisions. The scraper is requests-only
        # today — these records let us tune escalation thresholds before
        # wiring an actual renderer in RENDER-01.
        bundle["render_decisions"] = list(render_decisions)
    if render_budget is not None:
        bundle["render_budget"] = {
            "max_renders": render_budget.max_renders,
            "max_exploration_samples": render_budget.max_exploration_samples,
            "renders_used": render_budget.renders_used,
            "exploration_used": render_budget.exploration_used,
        }
    bundle["completed_at"] = datetime.now(timezone.utc).isoformat()
    _write_site_debug_bundle(bundle)


def _annotate_signals(signals: list[DealSignal], metadata: dict[str, Any]) -> None:
    if not signals or not metadata:
        return
    for signal in signals:
        if signal.metadata is None:
            signal.metadata = {}
        for key, value in metadata.items():
            signal.metadata.setdefault(key, deepcopy(value))


def _jsonld_clean_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return ""
    return re.sub(r"\s+", " ", unescape(value)).strip()


def _jsonld_clean_fragment(value: Any) -> str:
    cleaned = _jsonld_clean_text(value)
    if not cleaned:
        return ""
    cleaned = _JSONLD_CONTEXT_NOISE_RE.sub("", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -;,.")
    return cleaned


def _jsonld_node_types(node: dict[str, Any]) -> set[str]:
    raw_type = node.get("@type")
    if isinstance(raw_type, str):
        return {raw_type}
    if isinstance(raw_type, list):
        return {item for item in raw_type if isinstance(item, str)}
    return set()


def _jsonld_top_level_nodes(payload: Any) -> list[dict[str, Any]]:
    items = payload if isinstance(payload, list) else [payload]
    nodes: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        graph = item.get("@graph")
        if isinstance(graph, list):
            nodes.extend(node for node in graph if isinstance(node, dict))
            continue
        nodes.append(item)
    return nodes


def _jsonld_collect_id_index(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    id_index: dict[str, dict[str, Any]] = {}
    queue: deque[Any] = deque(nodes)
    seen_objects: set[int] = set()

    while queue:
        value = queue.popleft()
        if isinstance(value, list):
            queue.extend(value)
            continue
        if not isinstance(value, dict):
            continue
        obj_id = id(value)
        if obj_id in seen_objects:
            continue
        seen_objects.add(obj_id)

        node_id = value.get("@id")
        if isinstance(node_id, str) and node_id and node_id not in id_index:
            id_index[node_id] = value

        for child in value.values():
            if isinstance(child, (dict, list)):
                queue.append(child)

    return id_index


def _jsonld_resolve_node(value: Any, id_index: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(value, str):
        resolved = id_index.get(value)
        return resolved if isinstance(resolved, dict) else None
    if not isinstance(value, dict):
        return None

    ref_id = value.get("@id")
    if isinstance(ref_id, str) and ref_id and len(value) == 1:
        resolved = id_index.get(ref_id)
        if isinstance(resolved, dict):
            return resolved
    return value


def _jsonld_child_nodes(node: dict[str, Any], key: str, id_index: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    raw_value = node.get(key)
    values = raw_value if isinstance(raw_value, list) else [raw_value] if raw_value is not None else []
    children: list[dict[str, Any]] = []
    for value in values:
        resolved = _jsonld_resolve_node(value, id_index)
        if isinstance(resolved, dict):
            children.append(resolved)
    return children


def _jsonld_parse_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None

    cleaned = value.strip()
    if not cleaned:
        return None
    cleaned = re.sub(r"[^0-9.]+", "", cleaned)
    if not cleaned or cleaned.count(".") > 1:
        return None

    try:
        return float(cleaned)
    except ValueError:
        return None


def _jsonld_extract_price_details(
    node: dict[str, Any] | None,
    id_index: dict[str, dict[str, Any]],
) -> tuple[float | None, str | None]:
    if not isinstance(node, dict):
        return None, None

    price = _jsonld_parse_float(node.get("price"))
    if price is None:
        price = _jsonld_parse_float(node.get("minPrice"))
    if price is None:
        price = _jsonld_parse_float(node.get("maxPrice"))
    currency = _jsonld_clean_text(node.get("priceCurrency")) or None

    for spec in _jsonld_child_nodes(node, "priceSpecification", id_index):
        spec_price, spec_currency = _jsonld_extract_price_details(spec, id_index)
        if price is None and spec_price is not None:
            price = spec_price
        if currency is None and spec_currency:
            currency = spec_currency
        if price is not None and currency is not None:
            break

    return price, currency


def _jsonld_parse_datetime(value: Any) -> datetime | None:
    text = _jsonld_clean_text(value)
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


def _jsonld_extract_valid_window(
    node: dict[str, Any] | None,
    id_index: dict[str, dict[str, Any]],
) -> tuple[datetime | None, datetime | None]:
    if not isinstance(node, dict):
        return None, None

    start_date = _jsonld_parse_datetime(node.get("validFrom"))
    end_date = _jsonld_parse_datetime(node.get("validThrough"))
    if start_date or end_date:
        return start_date, end_date

    for spec in _jsonld_child_nodes(node, "priceSpecification", id_index):
        spec_start, spec_end = _jsonld_extract_valid_window(spec, id_index)
        if spec_start or spec_end:
            return spec_start, spec_end

    return None, None


def _jsonld_extract_inline_price(texts: list[str]) -> float | None:
    for text in texts:
        cleaned = _jsonld_clean_text(text)
        if not cleaned:
            continue
        match = _JSONLD_INLINE_PRICE_RE.search(cleaned)
        if not match:
            continue
        try:
            return float(match.group(1))
        except ValueError:
            continue
    return None


def _jsonld_extract_calories_from_node(node: dict[str, Any] | None) -> int | None:
    if not isinstance(node, dict):
        return None
    nutrition = node.get("nutrition")
    if isinstance(nutrition, dict):
        cal_val = nutrition.get("calories")
        if cal_val is not None:
            try:
                cal_int = int(str(cal_val).replace(" calories", "").replace(" cal", ""))
                if 50 <= cal_int <= 5000:
                    return cal_int
            except (TypeError, ValueError):
                pass
    return None


def _jsonld_compose_text(
    *,
    context_path: list[str],
    context_fragments: list[str],
    primary_name: str | None,
    description: str | None,
    price: float | None,
) -> str:
    parts: list[str] = []
    seen: set[str] = set()
    for raw in [*context_path, *context_fragments, primary_name or "", description or ""]:
        cleaned = _jsonld_clean_fragment(raw)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        parts.append(cleaned)

    text = " ".join(parts).strip()
    if price is not None and "$" not in text:
        text = f"{text} ${price:.2f}".strip()
    return text


def _jsonld_fallback_heading(context_path: list[str], name: str | None) -> str | None:
    cleaned_path = [_jsonld_clean_text(part) for part in context_path if _jsonld_clean_text(part)]
    cleaned_name = _jsonld_clean_text(name)

    if cleaned_path and cleaned_name and cleaned_name.lower() != cleaned_path[-1].lower():
        return f"{cleaned_path[-1]} - {cleaned_name}"[:80]
    if cleaned_name:
        return cleaned_name[:80]
    if cleaned_path:
        return cleaned_path[-1][:80]
    return None


def _jsonld_build_metadata(
    *,
    context_path: list[str],
    node_types: set[str],
    price: float | None,
    price_currency: str | None,
    primary_name: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "structured_source": "jsonld",
        "jsonld_path": [part for part in context_path if part],
        "jsonld_types": sorted(node_types),
    }
    cleaned_name = _jsonld_clean_text(primary_name)
    if cleaned_name:
        metadata["jsonld_primary_name"] = cleaned_name
    if price is not None:
        metadata["jsonld_structured_price"] = price
    if price_currency:
        metadata["jsonld_price_currency"] = price_currency
    return metadata


def _jsonld_has_promo_context(text: str, context_path: list[str], source_url: str) -> bool:
    haystacks = [text.lower(), " ".join(context_path).lower()]
    return any(
        keyword in haystack
        for haystack in haystacks
        for keyword in _JSONLD_PROMO_CONTEXT_KEYWORDS
    )


def _is_related_locator_corporate_host(current_host: str, candidate_host: str) -> bool:
    current = current_host.lower()
    candidate = candidate_host.lower()
    if not current or not candidate or current == candidate:
        return False
    if current in _LOCATOR_HINT_HOST_RULES:
        expected = urlparse(_LOCATOR_HINT_HOST_RULES[current]).netloc.lower()
        if candidate == expected:
            return True
    if current.startswith("locations."):
        base = current[len("locations."):]
        return candidate in {base, f"www.{base}"} or candidate.endswith(f".{base}")
    return False


def _discover_locator_corporate_pages(
    soup: BeautifulSoup,
    page_url: str,
    *,
    registry_hints: list[Hint] | None = None,
) -> list[dict[str, Any]]:
    parsed = urlparse(page_url)
    host = parsed.netloc.lower()
    if not host:
        return []

    hinted: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    def _add_hint(
        url: str,
        reason: str,
        *,
        audit: dict[str, Any] | None = None,
    ) -> None:
        normalized = url.strip()
        if not normalized or normalized in seen_urls:
            return
        seen_urls.add(normalized)
        entry: dict[str, Any] = {"url": normalized, "reason": reason}
        if audit is not None:
            entry["hint_audit"] = audit
        hinted.append(entry)

    if host in _LOCATOR_HINT_HOST_RULES:
        corporate_root = _LOCATOR_HINT_HOST_RULES[host]
        for path in _LOCATOR_HINT_PATHS:
            _add_hint(urljoin(corporate_root, path), f"locator_host_rule:{host}")
    elif host.startswith("locations."):
        corporate_root = f"{parsed.scheme}://www.{host[len('locations.'):] }"
        for path in _LOCATOR_HINT_PATHS:
            _add_hint(urljoin(corporate_root, path), "locator_host_rule:locations_subdomain")

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(page_url, href)
        parsed_link = urlparse(full_url)
        if parsed_link.scheme not in ("http", "https"):
            continue
        if not _is_related_locator_corporate_host(host, parsed_link.netloc.lower()):
            continue

        combined = f"{a_tag.get_text(' ', strip=True)} {full_url}".lower()
        if any(token in combined for token in _LOCATOR_HINT_EXCLUDED_TOKENS):
            continue
        if not any(token in combined for token in _LOCATOR_HINT_TEXT_KEYWORDS):
            continue

        link_path = parsed_link.path.rstrip("/").lower()
        if any(keyword in link_path for keyword in ("deal", "offer", "promo", "special", "happy-hour", "happyhour")):
            _add_hint(full_url, f"locator_cross_domain_link:{a_tag.get_text(' ', strip=True)[:40] or parsed_link.path or parsed_link.netloc}")

        corporate_root = f"{parsed_link.scheme}://{parsed_link.netloc}"
        _add_hint(corporate_root, f"locator_cross_domain_root:{a_tag.get_text(' ', strip=True)[:40] or parsed_link.netloc}")

    # ARCH-04: layer in brand-tagged registry hints. Registry entries are
    # exploration-only — they MUST NEVER be treated as first-party evidence.
    # We annotate each probe with provenance so the debug bundle can tell
    # hinted fetches apart from discovered ones.
    if registry_hints:
        for hint in registry_hints:
            if not hint.slug or not hint.target_domain:
                continue
            if not _is_related_locator_corporate_host(host, hint.target_domain) \
               and host != hint.target_domain \
               and not host.endswith(f".{hint.target_domain}"):
                continue
            corporate_root = f"{parsed.scheme}://{hint.target_domain}"
            probe_url = urljoin(corporate_root + "/", hint.slug.lstrip("/"))
            audit = annotate_exploration_use(hint, used_at_url=probe_url)
            _add_hint(probe_url, f"hint_registry:{hint.id}", audit=audit)

    return hinted[:6]


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
_HEADING_TAG_NAMES = ("h1", "h2", "h3", "h4", "h5", "h6")
_CORE_TAG_NAMES = frozenset(["p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "td"])
_STRUCTURAL_TAG_NAMES = frozenset(["div", "span", "article", "section"])
_PROMO_SECTION_HEADING_RE = re.compile(
    r"^\s*(?:specials?|deals?|offers?|promotions?|daily\s+specials?|happy\s*hour)\s*$",
    re.IGNORECASE,
)


def _should_skip_tag(tag: Tag) -> bool:
    """Return True for tags that are navigation, footer, or structural boilerplate."""
    if tag.name in _SKIP_TAG_NAMES:
        return True
    class_str = " ".join(tag.get("class", [])).lower()
    id_str = (tag.get("id") or "").lower()
    combined = f"{class_str} {id_str}"
    return any(tok in combined for tok in _SKIP_CLASS_ID_TOKENS)


def _prefix_day_heading_context(tag: Tag, text: str) -> str:
    """Carry nearby day headings into row blocks that lost temporal context."""
    if not text or _extract_days(text):
        return text

    def _maybe_prefix(candidate: Tag | None) -> str | None:
        if candidate is None:
            return None
        candidate_text = re.sub(r"\s+", " ", candidate.get_text(separator=" ", strip=True)).strip()
        if not candidate_text:
            return None
        if not _extract_days(candidate_text):
            return None
        if len(candidate_text) > 48:
            return None
        if _PRICE_RE.search(candidate_text):
            return None
        if _has_deal_keywords(candidate_text):
            return None
        lower_candidate = candidate_text.lower()
        if lower_candidate in text.lower():
            return None
        return f"{candidate_text} {text}".strip()

    current: Tag | None = tag
    while isinstance(current, Tag):
        heading = current.find_previous_sibling(_HEADING_TAG_NAMES)
        if heading is not None:
            heading_text = re.sub(r"\s+", " ", heading.get_text(separator=" ", strip=True)).strip()
            if heading_text and _extract_days(heading_text):
                lower_heading = heading_text.lower()
                if lower_heading not in text.lower():
                    return f"{heading_text} {text}".strip()
        sibling = current.find_previous_sibling()
        checks = 0
        while isinstance(sibling, Tag) and checks < 3:
            prefixed = _maybe_prefix(sibling)
            if prefixed is not None:
                return prefixed
            sibling = sibling.find_previous_sibling()
            checks += 1
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None

    return text


def _prefix_promotional_heading_context(tag: Tag, text: str) -> str:
    """Carry nearby promo headings like 'Specials' into child offer rows."""
    if not text or _has_deal_keywords(text):
        return text

    heading = tag.find_previous(_HEADING_TAG_NAMES)
    checks = 0
    while heading is not None and checks < 4:
        heading_text = re.sub(r"\s+", " ", heading.get_text(separator=" ", strip=True)).strip()
        if heading_text and _PROMO_SECTION_HEADING_RE.match(heading_text):
            if heading_text.lower() not in text.lower():
                return f"{heading_text} {text}".strip()
            break
        heading = heading.find_previous(_HEADING_TAG_NAMES)
        checks += 1

    return text


def _text_block_has_offer_evidence(text: str) -> bool:
    """Return True when a block contains substantive offer content."""
    if not text:
        return False
    return _is_valid_deal_block(text)


def _has_nested_offerish_descendants(tag: Tag, text: str) -> bool:
    """Skip aggregate wrappers when child blocks already preserve the offers."""
    normalized_parent = re.sub(r"\s+", " ", text).strip()
    descendant_blocks: set[str] = set()

    for child in tag.find_all(list(_CORE_TAG_NAMES | _STRUCTURAL_TAG_NAMES)):
        if child is tag or _should_skip_tag(child):
            continue

        child_text = child.get_text(separator=" ", strip=True)
        if not child_text:
            continue

        child_text = _prefix_day_heading_context(child, child_text)
        child_text = _prefix_promotional_heading_context(child, child_text)
        child_text = re.sub(r"\s+", " ", child_text).strip()
        if not child_text or child_text == normalized_parent or len(child_text) >= len(normalized_parent):
            continue

        if child.name in _STRUCTURAL_TAG_NAMES:
            if not (25 < len(child_text) < 300):
                continue
        else:
            if not (15 < len(child_text) < 400):
                continue

        if not _text_block_has_offer_evidence(child_text):
            continue

        descendant_blocks.add(child_text)
        if len(descendant_blocks) >= 2:
            return True

    return False


def _extract_text_blocks(soup: BeautifulSoup) -> list[str]:
    """Extract meaningful text blocks, skipping navigation/footer/ad elements."""
    # Remove entire nav/footer/script subtrees first so nested tags don't leak.
    for bad in soup.find_all(_SKIP_TAG_NAMES):
        bad.decompose()

    blocks = []
    seen_text: set[str] = set()  # avoid duplicate blocks from nested tags

    for tag in soup.find_all(list(_CORE_TAG_NAMES | _STRUCTURAL_TAG_NAMES)):
        if _should_skip_tag(tag):
            continue
        text = tag.get_text(separator=" ", strip=True)
        if not text:
            continue
        text = _prefix_day_heading_context(tag, text)
        text = _prefix_promotional_heading_context(tag, text)

        # Apply tag-appropriate length bounds
        if tag.name in _STRUCTURAL_TAG_NAMES:
            if not (25 < len(text) < 300):
                continue
            if _has_nested_offerish_descendants(tag, text):
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
    strong_offer_evidence = (
        bool(_PRICE_RE.search(text))
        or bool(_PERCENTAGE_RE.search(text))
        or any(kw in lower for kw in _SELF_VALIDATING_KEYWORDS)
    )
    # Boilerplate nav/footer phrases
    if any(bp in lower for bp in _BOILERPLATE_PHRASES if bp not in _SOFT_BOILERPLATE_PHRASES):
        return True
    if any(bp in lower for bp in _SOFT_BOILERPLATE_PHRASES) and not strong_offer_evidence:
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
    if _FAQ_BLOCK_RE.search(text):
        return True
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
    re.compile(
        r"\bfree\s+(?:burger|wings?|boneless\s+wings?|bone-?in\s+wings?|appetizers?|apps?|entrees?|meals?|combos?|desserts?|drinks?|pizza|tacos?|sandwich(?:es)?|sliders?)\s+with\s+(?:your\s+)?\$\d+(?:\.\d{2})?\+?\s+order\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bfree\s+(?:burger|wings?|boneless\s+wings?|bone-?in\s+wings?|appetizers?|apps?|entrees?|meals?|combos?|desserts?|drinks?|pizza|tacos?|sandwich(?:es)?|sliders?)\b",
        re.IGNORECASE,
    ),
    re.compile(r"(?<!\w)\$\d+(?:\.\d{2})?\s+(?:combo|meal|special|deal|lunch|dinner|burger|pizza|plate|platter|box|bucket|basket|taco|wings?)\b", re.IGNORECASE),
    re.compile(r"\b2\s+for\s+\$\d+\b", re.IGNORECASE),
    re.compile(r"\b(?:half|½)\s+(?:off|price)\s+(?:appetizers?|apps?|drinks?|wine|pizza|burgers?)\b", re.IGNORECASE),
]

_DEAL_NAME_SIGNAL_RE = re.compile(
    r"\b(?:happy\s*hour|kids\s+eat\s+free|bogo|buy\s+one|get\s+one|free\b|special|deal|combo|discount|half\s+(?:off|price)|\$\d)",
    re.IGNORECASE,
)

_GENERIC_PROMO_HEADING_RE = re.compile(
    r"\b(?:rewards?|offers?|promotions?|download(?:\s+the)?\s+app|join(?:\s+now|\s+today)?|sign\s*(?:in|up)|log\s*in|learn\s+more)\b",
    re.IGNORECASE,
)

_PRICE_LADDER_NAME_RE = re.compile(
    r"^(?=.*\$\d)(?=.*\b(?:am|pm)\b)[a-z0-9$:+\-\s]{4,80}$",
    re.IGNORECASE,
)

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
_MONTH_NAME_RE = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
    r"jul(?:y)?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
_LEADING_PROMO_PREFIX_RE = re.compile(
    r"^(?:specials?|deals?|offers?|promotions?)\s+",
    re.IGNORECASE,
)
_LEADING_DAY_DATE_RE = re.compile(
    rf"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues?|wed(?:s|nesday)?|thu(?:r|rs)?|fri|sat|sun)\b(?:\s+{_MONTH_NAME_RE})?\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,\s*\d{{4}})?\s+",
    re.IGNORECASE,
)
_TRAILING_TIME_RANGE_RE = re.compile(
    r"\s+\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)\s*(?:-|–|—|to|til|till|until)\s*(?:\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)|close|closing)\s*$",
    re.IGNORECASE,
)
_TRAILING_PARTIAL_TIME_RE = re.compile(
    r"\s+\d{1,2}(?::\d{2})?\s*[AP](?:\.?M?)?\.?\s*$",
    re.IGNORECASE,
)

# Only trim these from the ends of a snippet (no periods — they're part of prices)
_NAME_TRIM_CHARS = " -–—:,\n\t"


def _trim_name(snippet: str) -> str:
    """Collapse whitespace and strip trim chars from both ends."""
    return re.sub(r"\s+", " ", snippet).strip(_NAME_TRIM_CHARS)


def _clean_candidate_deal_name(candidate: str) -> str:
    """Normalize extracted names by dropping date/time scaffolding and clipping noise."""
    cleaned = _trim_name(candidate)
    cleaned = _NAME_STOPWORDS_PREFIX_RE.sub("", cleaned)
    cleaned = _LEADING_PROMO_PREFIX_RE.sub("", cleaned)
    cleaned = _LEADING_DAY_DATE_RE.sub("", cleaned)
    cleaned = _TRAILING_TIME_RANGE_RE.sub("", cleaned)
    cleaned = _TRAILING_PARTIAL_TIME_RE.sub("", cleaned)
    cleaned = _trim_name(cleaned).rstrip("|").strip()
    if cleaned.isupper() and any(char.isalpha() for char in cleaned):
        cleaned = cleaned.title()
    return cleaned[:80]


def _is_invalid_deal_name(candidate: str, *, raw_text: str | None = None) -> bool:
    """Reject headings and fragments that are not stable deal labels."""
    cleaned = _clean_candidate_deal_name(candidate)
    if not cleaned:
        return True
    if _INVALID_DEAL_NAME_RE.match(cleaned):
        return True
    if _QUESTION_NAME_RE.match(cleaned) or _FAQ_BLOCK_RE.match(cleaned):
        return True
    if _VARIANT_ONLY_NAME_RE.match(cleaned):
        return True
    if raw_text and _MENU_BADGE_PROMO_RE.search(raw_text) and _MENU_UI_NOISE_RE.search(raw_text):
        return True
    return False


def _finalize_deal_name(candidate: str | None, *, raw_text: str | None = None) -> str | None:
    """Return a cleaned deal name or None when the candidate is not usable."""
    if not candidate:
        return None
    cleaned = _clean_candidate_deal_name(candidate)
    if _is_invalid_deal_name(cleaned, raw_text=raw_text):
        return None
    return cleaned


def _looks_like_menu_badge_noise(text: str) -> bool:
    """Reject wrapper blocks that blend one promo badge with menu-card UI text."""
    if not text:
        return False
    return bool(_MENU_BADGE_PROMO_RE.search(text) and _MENU_UI_NOISE_RE.search(text))


def _is_plain_menu_page_url(source_url: str | None) -> bool:
    if not source_url:
        return False

    path = urlparse(source_url).path.casefold().strip("/")
    if not path:
        return False

    normalized_path = path.replace("_", "-")
    has_menu_marker = any(marker in normalized_path for marker in _MENU_PAGE_URL_MARKERS)
    if not has_menu_marker:
        has_menu_marker = re.search(r"(?:^|/)menu(?:/|$)", normalized_path) is not None
    if not has_menu_marker:
        return False

    return not any(hint in normalized_path for hint in _PROMOISH_PATH_MARKERS)


def _looks_like_menu_item_discount_badge_noise(text: str, source_url: str | None) -> bool:
    """Reject plain menu-item cards that only inherit a sitewide discount badge."""
    if not text or not _is_plain_menu_page_url(source_url):
        return False

    normalized = " ".join(text.split())
    if _ORDER_THRESHOLD_PROMO_RE.search(normalized):
        return False

    return bool(_TRAILING_PERCENT_BADGE_RE.search(normalized))


def _is_generic_fallback_heading(heading: str, block: str) -> bool:
    """Reject promo-card headings that are less informative than the body text."""
    cleaned = _trim_name(heading)
    if not cleaned:
        return False
    if _GENERIC_PROMO_HEADING_RE.search(cleaned) and not _DEAL_NAME_SIGNAL_RE.search(cleaned):
        return True
    if _PRICE_LADDER_NAME_RE.search(cleaned) and "happy hour" in block.lower():
        return True
    return False


def _signal_name_score(name: str | None, *, raw_text: str | None = None) -> int:
    """Score a name for merge-time quality comparisons."""
    cleaned = _trim_name(name or "")
    if not cleaned:
        return -100

    score = 0
    if any(pattern.search(cleaned) for pattern in _DEAL_LABEL_PATTERNS):
        score += 8
    if _DEAL_NAME_SIGNAL_RE.search(cleaned):
        score += 4

    length = len(cleaned)
    if 4 <= length <= 28:
        score += 4
    elif length <= 48:
        score += 2
    elif length > 60:
        score -= 4

    lowered = cleaned.lower()
    if _GENERIC_PROMO_HEADING_RE.search(cleaned) and not _DEAL_NAME_SIGNAL_RE.search(cleaned):
        score -= 8
    if _PRICE_LADDER_NAME_RE.search(cleaned):
        score -= 6
    if "happy hour at" in lowered:
        score -= 2
    if raw_text and _PRICE_LADDER_NAME_RE.search(cleaned) and "happy hour" in raw_text.lower():
        score -= 2
    return score


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
        h = _finalize_deal_name(fallback_heading, raw_text=block)
        if 3 <= len(h) <= 80 and not _FRAGMENT_MARKERS_RE.search(h) and not _is_generic_fallback_heading(h, block):
            return h

    # 2. Label-pattern search — expand match to nearest clause boundary.
    for pat in _DEAL_LABEL_PATTERNS:
        m = pat.search(block)
        if not m:
            continue
        # Find a reasonable end: prefer a comma or "featuring"/"with" split,
        # fall back to 70 chars past the match start.
        start = m.start()
        stop_search = re.search(
            r"[.!?\n]|\s(?:featuring|including|with|served|after|when|valid|available|starting)\s",
            block[m.end():m.end() + 80],
            re.IGNORECASE,
        )
        end = m.end() + (stop_search.start() if stop_search else min(40, len(block) - m.end()))
        end = min(len(block), end)
        snippet = _finalize_deal_name(block[start:end], raw_text=block)
        if snippet and 3 <= len(snippet) <= 80:
            return snippet
        # Very long — just return the bare match
        bare = _finalize_deal_name(m.group(0), raw_text=block)
        if bare:
            return bare

    # 3. Short-clause scan
    for clause in re.split(r"[.!?\n]", block):
        c = _finalize_deal_name(clause, raw_text=block)
        if not c or not (5 <= len(c) <= 70):
            continue
        if _FRAGMENT_MARKERS_RE.search(c):
            continue
        lower = c.lower()
        if any(kw in lower for kw in (
            "special", "deal", "combo", "happy hour", "bogo",
            "kids eat", "lunch", "dinner", "discount", "free", " off",
        )):
            return c[:80]

    # 4. Last resort: first short clause if it doesn't look like a fragment
    first = _finalize_deal_name(re.split(r"[.!?\n]", block, maxsplit=1)[0], raw_text=block)
    if first and 5 <= len(first) <= 70 and not _FRAGMENT_MARKERS_RE.search(first):
        return first

    return None


_EMBEDDED_APP_CONTENT_KEYS = frozenset([
    "title", "description", "topText", "mainText", "bottomText",
    "legalMessage", "descriptionCTA", "internalTitle",
])
_EMBEDDED_APP_SHAPE_KEYS = frozenset([
    "primaryCTAText", "primaryCTAAction", "mainLinkText", "mainLinkHref",
    "descriptionCTA", "showViewMore", "type",
])
_EMBEDDED_APP_URL_KEYS = ("action", "nameInUrl", "url", "href", "name")


def _load_next_data_payload(html: str) -> Any | None:
    """Return parsed Next.js page data when present."""
    soup = BeautifulSoup(html, "html.parser")
    script = soup.find("script", id=_NEXT_DATA_SCRIPT_ID)
    if script is None:
        return None

    raw = script.string or script.get_text(strip=False)
    if not raw:
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.debug("[WebScraper] Failed to parse %s payload", _NEXT_DATA_SCRIPT_ID)
        return None


def _clean_embedded_internal_title(value: str) -> str:
    """Remove campaign tokens from CMS internal titles before using them."""
    cleaned = re.sub(r"[_-]+", " ", value)
    cleaned = re.sub(r"\b(?:page[_ ]type\d+|type\d+|aw\d+)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b20\d{2}\b", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -–—:,")
    return cleaned


def _embedded_app_text(value: Any, *, clean_internal_title: bool = False) -> str:
    """Extract human-readable text from Next.js / CMS-style nested JSON values."""
    parts: list[str] = []
    seen: set[str] = set()

    def _append(raw: Any, *, internal_title: bool = False) -> None:
        if raw is None:
            return
        if isinstance(raw, (int, float)):
            text = str(raw)
        elif isinstance(raw, str):
            text = unescape(raw)
        else:
            return
        if internal_title or clean_internal_title:
            text = _clean_embedded_internal_title(text)
        text = re.sub(r"\s+", " ", text).strip(" -–—:,\n\t")
        if not text:
            return
        key = text.lower()
        if key in seen:
            return
        seen.add(key)
        parts.append(text)

    def _walk(obj: Any, *, allow_internal_title: bool = False) -> None:
        if obj is None:
            return
        if isinstance(obj, (str, int, float)):
            _append(obj, internal_title=allow_internal_title)
            return
        if isinstance(obj, list):
            for item in obj:
                _walk(item, allow_internal_title=allow_internal_title)
            return
        if not isinstance(obj, dict):
            return

        fields = obj.get("fields")
        if isinstance(fields, dict):
            if "text" in fields:
                _walk(fields.get("text"))
            for key in (
                "title", "topText", "mainText", "bottomText", "description",
                "message", "termsApplyTitle", "viewDetailsTitle", "legalMessage",
                "descriptionCTA",
            ):
                if key in fields:
                    _walk(fields.get(key))
            if "internalTitle" in fields:
                _walk(fields.get("internalTitle"), allow_internal_title=True)

        if "content" in obj and isinstance(obj["content"], list):
            for item in obj["content"]:
                _walk(item)
        if "value" in obj:
            _walk(obj["value"])
        if "text" in obj:
            _walk(obj["text"])
        for key in (
            "title", "topText", "mainText", "bottomText", "description",
            "message", "termsApplyTitle", "viewDetailsTitle", "legalMessage",
            "descriptionCTA",
        ):
            if key in obj:
                _walk(obj[key])
        if "internalTitle" in obj:
            _walk(obj["internalTitle"], allow_internal_title=True)

    _walk(value)
    return " ".join(parts)


def _embedded_app_heading(fields: dict[str, Any]) -> tuple[str | None, str | None]:
    """Pick the best user-facing heading plus a cleaned internal fallback."""
    title = _embedded_app_text(fields.get("title"))
    main_text = _embedded_app_text(fields.get("mainText"))
    internal_title = _embedded_app_text(fields.get("internalTitle"), clean_internal_title=True)
    heading = title or main_text or internal_title or None
    return heading, internal_title or None


def _embedded_app_candidate_block(fields: dict[str, Any]) -> tuple[str | None, str | None]:
    """Build a promo-like text block from a structured app-data card."""
    heading, internal_title = _embedded_app_heading(fields)

    parts: list[str] = []
    seen: set[str] = set()
    for raw in (
        _embedded_app_text(fields.get("topText")),
        _embedded_app_text(fields.get("mainText")),
        _embedded_app_text(fields.get("title")),
        _embedded_app_text(fields.get("description")),
        _embedded_app_text(fields.get("bottomText")),
        _embedded_app_text(fields.get("legalMessage")),
        _embedded_app_text(fields.get("descriptionCTA")),
    ):
        if not raw:
            continue
        key = raw.lower()
        if key in seen:
            continue
        seen.add(key)
        parts.append(raw)

    block = re.sub(r"\s+", " ", " ".join(parts)).strip()
    if internal_title and not _is_valid_deal_block(block):
        block = re.sub(r"\s+", " ", f"{internal_title}. {block}").strip(" .")

    if not block or not _is_valid_deal_block(block):
        return None, heading
    return block, heading


def _embedded_app_candidate_url(value: Any, *, page_url: str) -> str | None:
    """Extract a same-domain detail or menu URL from structured app data."""
    page_host = urlparse(page_url).netloc.lower()
    candidates: list[str] = []

    def _walk(obj: Any) -> None:
        if obj is None:
            return
        if isinstance(obj, str):
            candidates.append(obj)
            return
        if isinstance(obj, list):
            for item in obj:
                _walk(item)
            return
        if not isinstance(obj, dict):
            return

        fields = obj.get("fields")
        if isinstance(fields, dict):
            for key in _EMBEDDED_APP_URL_KEYS:
                if key in fields:
                    _walk(fields[key])
        for key in _EMBEDDED_APP_URL_KEYS:
            if key in obj:
                _walk(obj[key])

    _walk(value)

    for raw in candidates:
        candidate = raw.strip()
        if not candidate:
            continue
        if "/" not in candidate and not candidate.startswith(("http://", "https://", "?")):
            continue
        normalized = urljoin(page_url, candidate)
        parsed = urlparse(normalized)
        if parsed.scheme not in ("http", "https"):
            continue
        if parsed.netloc.lower() != page_host:
            continue
        if any(parsed.path.lower().endswith(ext) for ext in (".jpg", ".png", ".gif", ".svg", ".pdf", ".zip", ".js", ".css")):
            continue
        return normalized
    return None


def _iter_embedded_app_candidates(node: Any, *, page_url: str, path: str = "root") -> Iterable[dict[str, Any]]:
    """Yield promo-card candidates from embedded Next.js app data."""
    if isinstance(node, dict):
        fields = node.get("fields")
        if isinstance(fields, dict):
            has_content = any(key in fields for key in _EMBEDDED_APP_CONTENT_KEYS)
            has_shape = any(key in fields for key in _EMBEDDED_APP_SHAPE_KEYS)
            if has_content and has_shape:
                block, heading = _embedded_app_candidate_block(fields)
                if block:
                    cta_url = None
                    for key in ("mainLinkHref", "primaryCTAAction", "descriptionCTA"):
                        if key not in fields:
                            continue
                        cta_url = _embedded_app_candidate_url(fields.get(key), page_url=page_url)
                        if cta_url:
                            break
                    yield {
                        "block": block,
                        "heading": heading,
                        "cta_url": cta_url,
                        "candidate_path": f"{path}.fields",
                    }

        for key, value in node.items():
            yield from _iter_embedded_app_candidates(value, page_url=page_url, path=f"{path}.{key}")
        return

    if isinstance(node, list):
        for index, value in enumerate(node):
            yield from _iter_embedded_app_candidates(value, page_url=page_url, path=f"{path}[{index}]")


def _extract_embedded_app_deals(
    html: str,
    *,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    page_url: str,
    region: str,
    seen_deals: set[str],
) -> list[DealSignal]:
    """Extract deal signals from structured app data such as Next.js page props."""
    payload = _load_next_data_payload(html)
    if payload is None:
        return []

    signals: list[DealSignal] = []
    seen_blocks: set[str] = set()
    local_seen_deals: set[str] = set()
    for candidate in _iter_embedded_app_candidates(payload, page_url=page_url):
        block = candidate.get("block")
        if not isinstance(block, str):
            continue
        key = block.lower()
        if key in seen_blocks:
            continue
        seen_blocks.add(key)

        candidate_signals = _text_block_to_signals(
            block,
            restaurant_name=restaurant_name,
            local_employer_id=local_employer_id,
            brand_group_id=brand_group_id,
            source_url=page_url,
            region=region,
            seen_deals=local_seen_deals,
            fallback_heading=candidate.get("heading") if isinstance(candidate.get("heading"), str) else None,
        )
        _annotate_signals(candidate_signals, {
            "embedded_app_source": _NEXT_DATA_SCRIPT_ID,
            "embedded_app_path": candidate.get("candidate_path"),
            "embedded_app_heading": candidate.get("heading"),
            "embedded_app_cta_url": candidate.get("cta_url"),
        })
        signals.extend(candidate_signals)
        for signal in candidate_signals:
            if signal.deal_name:
                seen_deals.add(_signal_seen_key(signal))

    return signals


def _discover_embedded_app_pages(html: str, *, page_url: str) -> list[str]:
    """Discover bounded same-domain pages referenced by embedded app promo cards."""
    payload = _load_next_data_payload(html)
    if payload is None:
        return []

    existing_paths = {p.rstrip("/").lower() for p in DEAL_PATHS}
    current_host = urlparse(page_url).netloc.lower()
    discovered: list[str] = []
    seen: set[str] = set()

    for candidate in _iter_embedded_app_candidates(payload, page_url=page_url):
        cta_url = candidate.get("cta_url")
        if not isinstance(cta_url, str) or not cta_url:
            continue
        parsed = urlparse(cta_url)
        if parsed.netloc.lower() != current_host:
            continue
        path = parsed.path.rstrip("/").lower()
        if not path or path in existing_paths:
            continue
        if any(part in _NON_DEAL_URL_KEYWORDS for part in path.strip("/").split("/")):
            continue
        if not any(token in path for token in _RENDER_CRITICAL_PATH_TOKENS):
            continue
        normalized = cta_url.rstrip("/") or cta_url
        if normalized in seen:
            continue
        seen.add(normalized)
        discovered.append(cta_url)

    return discovered[:4]


def _extract_jsonld_deals(
    html: str,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
) -> list[DealSignal]:
    """Extract deal signals from hierarchical JSON-LD structured data."""
    signals: list[DealSignal] = []

    for match in _JSONLD_RE.finditer(html):
        try:
            nodes = _jsonld_top_level_nodes(json.loads(match.group(1)))
            if not nodes:
                continue

            id_index = _jsonld_collect_id_index(nodes)
            for node in nodes:
                _jsonld_traverse_node(
                    node,
                    context_path=[],
                    context_fragments=[],
                    inherited_price=None,
                    inherited_currency=None,
                    id_index=id_index,
                    lineage_keys=set(),
                    restaurant_name=restaurant_name,
                    local_employer_id=local_employer_id,
                    brand_group_id=brand_group_id,
                    source_url=source_url,
                    region=region,
                    seen_deals=seen_deals,
                    signals=signals,
                )

        except (json.JSONDecodeError, KeyError, TypeError):
            continue

    return signals


def _jsonld_append_signal(
    *,
    text: str,
    context_path: list[str],
    primary_name: str | None,
    structured_price: float | None,
    price_currency: str | None,
    calories: int | None,
    metadata: dict[str, Any],
    start_date: datetime | None,
    end_date: datetime | None,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
    signals: list[DealSignal],
) -> None:
    if not text or not _jsonld_has_promo_context(text, context_path, source_url):
        return
    if not _is_valid_deal_block(text):
        return

    fallback_heading = _jsonld_fallback_heading(context_path, primary_name)
    deal_name = _extract_deal_name(text, fallback_heading=fallback_heading)
    if not deal_name or len(deal_name) < 5:
        return

    pricing = _extract_deal_pricing(text)
    if pricing.is_non_food:
        return
    if structured_price is None and pricing.is_addon:
        return

    price = structured_price if structured_price is not None else pricing.price
    price_type = pricing.price_type
    if structured_price is not None and price_type is None and price is not None:
        price_type = "absolute"

    calorie_price_ratio = None
    if calories and price and price > 0:
        calorie_price_ratio = round(calories / price, 1)

    valid_days = _extract_days(text)
    start_time, end_time = _extract_times(text)
    name_key = _deal_seen_key(
        deal_name=deal_name,
        source_url=source_url,
        valid_days=valid_days,
        valid_start_time=start_time,
        valid_end_time=end_time,
        price=price,
    )
    if name_key in seen_deals:
        return

    seen_deals.add(name_key)

    signal_metadata = deepcopy(metadata)
    if price_currency:
        signal_metadata.setdefault("jsonld_price_currency", price_currency)

    signals.append(DealSignal(
        restaurant_name=restaurant_name,
        local_employer_id=local_employer_id,
        brand_group_id=brand_group_id,
        deal_name=deal_name,
        deal_description=text[:500],
        deal_type=_classify_deal_type(text),
        price=price,
        price_type=price_type,
        discount_percentage=pricing.discount_percentage,
        calories=calories,
        calorie_price_ratio=calorie_price_ratio,
        valid_days=valid_days,
        valid_start_time=start_time,
        valid_end_time=end_time,
        start_date=start_date,
        end_date=end_date,
        raw_scraped_text=text[:2000],
        metadata=signal_metadata,
        source="website_scrape",
        source_url=source_url,
        region=region,
        observed_at=datetime.now(timezone.utc),
    ))


def _jsonld_offer_to_signal(
    offer: dict,
    *,
    context_path: list[str],
    context_fragments: list[str],
    inherited_price: float | None,
    inherited_currency: str | None,
    id_index: dict[str, dict[str, Any]],
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
    signals: list[DealSignal],
) -> None:
    """Convert a schema.org Offer to a DealSignal using inherited menu context."""
    name = _jsonld_clean_text(offer.get("name"))
    desc = _jsonld_clean_text(offer.get("description"))
    item_offered = None
    child_items = _jsonld_child_nodes(offer, "itemOffered", id_index)
    if child_items:
        item_offered = child_items[0]

    item_name = _jsonld_clean_text(item_offered.get("name")) if isinstance(item_offered, dict) else ""
    item_desc = _jsonld_clean_text(item_offered.get("description")) if isinstance(item_offered, dict) else ""
    primary_name = name or item_name
    if not primary_name and not context_path:
        return

    price, currency = _jsonld_extract_price_details(offer, id_index)
    if price is None:
        price = inherited_price
    if currency is None:
        currency = inherited_currency

    start_date, end_date = _jsonld_extract_valid_window(offer, id_index)
    calories = _jsonld_extract_calories_from_node(item_offered)
    text = _jsonld_compose_text(
        context_path=context_path,
        context_fragments=[*context_fragments, item_desc],
        primary_name=primary_name,
        description=desc,
        price=price,
    )
    metadata = _jsonld_build_metadata(
        context_path=context_path,
        node_types=_jsonld_node_types(offer) | (_jsonld_node_types(item_offered) if isinstance(item_offered, dict) else set()),
        price=price,
        price_currency=currency,
        primary_name=primary_name,
    )
    if item_name:
        metadata.setdefault("jsonld_item_name", item_name)

    _jsonld_append_signal(
        text=text,
        context_path=context_path,
        primary_name=primary_name,
        structured_price=price,
        price_currency=currency,
        calories=calories,
        metadata=metadata,
        start_date=start_date,
        end_date=end_date,
        restaurant_name=restaurant_name,
        local_employer_id=local_employer_id,
        brand_group_id=brand_group_id,
        source_url=source_url,
        region=region,
        seen_deals=seen_deals,
        signals=signals,
    )


def _jsonld_menuitem_to_signal(
    item: dict,
    *,
    context_path: list[str],
    context_fragments: list[str],
    inherited_price: float | None,
    inherited_currency: str | None,
    id_index: dict[str, dict[str, Any]],
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
    signals: list[DealSignal],
) -> None:
    """Convert a schema.org MenuItem to a DealSignal using inherited menu context."""
    name = _jsonld_clean_text(item.get("name"))
    desc = _jsonld_clean_text(item.get("description"))
    if not name and not desc:
        return

    offers = _jsonld_child_nodes(item, "offers", id_index)
    offer_fragments: list[str] = []
    price = inherited_price
    currency = inherited_currency
    start_date = None
    end_date = None

    for offer in offers:
        offer_name = _jsonld_clean_text(offer.get("name"))
        offer_desc = _jsonld_clean_text(offer.get("description"))
        if offer_name:
            offer_fragments.append(offer_name)
        if offer_desc:
            offer_fragments.append(offer_desc)
        offer_price, offer_currency = _jsonld_extract_price_details(offer, id_index)
        if price is None and offer_price is not None:
            price = offer_price
        if currency is None and offer_currency is not None:
            currency = offer_currency
        if start_date is None and end_date is None:
            start_date, end_date = _jsonld_extract_valid_window(offer, id_index)

    if price is None:
        price = _jsonld_extract_inline_price([*context_fragments, desc])

    calories = _jsonld_extract_calories_from_node(item)
    if calories is None:
        calories = _extract_calories(desc)

    text = _jsonld_compose_text(
        context_path=context_path,
        context_fragments=[*context_fragments, *offer_fragments],
        primary_name=name,
        description=desc,
        price=price,
    )
    metadata = _jsonld_build_metadata(
        context_path=context_path,
        node_types=_jsonld_node_types(item),
        price=price,
        price_currency=currency,
        primary_name=name,
    )
    if offers:
        metadata.setdefault("jsonld_offer_count", len(offers))

    _jsonld_append_signal(
        text=text,
        context_path=context_path,
        primary_name=name,
        structured_price=price,
        price_currency=currency,
        calories=calories,
        metadata=metadata,
        start_date=start_date,
        end_date=end_date,
        restaurant_name=restaurant_name,
        local_employer_id=local_employer_id,
        brand_group_id=brand_group_id,
        source_url=source_url,
        region=region,
        seen_deals=seen_deals,
        signals=signals,
    )


def _jsonld_traverse_node(
    node: dict[str, Any],
    *,
    context_path: list[str],
    context_fragments: list[str],
    inherited_price: float | None,
    inherited_currency: str | None,
    id_index: dict[str, dict[str, Any]],
    lineage_keys: set[str],
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    source_url: str,
    region: str,
    seen_deals: set[str],
    signals: list[DealSignal],
) -> None:
    resolved = _jsonld_resolve_node(node, id_index)
    if not isinstance(resolved, dict):
        return

    node_types = _jsonld_node_types(resolved)
    if not node_types.intersection(_DEAL_SCHEMA_TYPES):
        return

    node_key = resolved.get("@id")
    lineage_key = node_key if isinstance(node_key, str) and node_key else f"anon:{id(resolved)}"
    if lineage_key in lineage_keys:
        return
    next_lineage = set(lineage_keys)
    next_lineage.add(lineage_key)

    name = _jsonld_clean_text(resolved.get("name"))
    desc = _jsonld_clean_text(resolved.get("description"))
    node_price, node_currency = _jsonld_extract_price_details(resolved, id_index)
    if node_price is None:
        node_price = _jsonld_extract_inline_price([desc])
    effective_price = node_price if node_price is not None else inherited_price
    effective_currency = node_currency if node_currency is not None else inherited_currency

    if node_types.intersection({"Restaurant", "FoodEstablishment"}):
        next_fragments = [*context_fragments]
        if name:
            next_fragments.append(name)
        if desc:
            next_fragments.append(desc)

        for offer in _jsonld_child_nodes(resolved, "makesOffer", id_index) + _jsonld_child_nodes(resolved, "offers", id_index):
            _jsonld_offer_to_signal(
                offer,
                context_path=context_path,
                context_fragments=next_fragments,
                inherited_price=effective_price,
                inherited_currency=effective_currency,
                id_index=id_index,
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                source_url=source_url,
                region=region,
                seen_deals=seen_deals,
                signals=signals,
            )
        for menu in _jsonld_child_nodes(resolved, "hasMenu", id_index):
            _jsonld_traverse_node(
                menu,
                context_path=context_path,
                context_fragments=next_fragments,
                inherited_price=effective_price,
                inherited_currency=effective_currency,
                id_index=id_index,
                lineage_keys=next_lineage,
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                source_url=source_url,
                region=region,
                seen_deals=seen_deals,
                signals=signals,
            )
        return

    if "Menu" in node_types or "MenuSection" in node_types:
        next_path = [*context_path]
        if name:
            next_path.append(name)
        next_fragments = [*context_fragments]
        if desc:
            next_fragments.append(desc)

        for offer in _jsonld_child_nodes(resolved, "offers", id_index):
            _jsonld_offer_to_signal(
                offer,
                context_path=next_path,
                context_fragments=next_fragments,
                inherited_price=effective_price,
                inherited_currency=effective_currency,
                id_index=id_index,
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                source_url=source_url,
                region=region,
                seen_deals=seen_deals,
                signals=signals,
            )

        for menu_item in _jsonld_child_nodes(resolved, "hasMenuItem", id_index):
            _jsonld_menuitem_to_signal(
                menu_item,
                context_path=next_path,
                context_fragments=next_fragments,
                inherited_price=effective_price,
                inherited_currency=effective_currency,
                id_index=id_index,
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                source_url=source_url,
                region=region,
                seen_deals=seen_deals,
                signals=signals,
            )

        for section in _jsonld_child_nodes(resolved, "hasMenuSection", id_index):
            _jsonld_traverse_node(
                section,
                context_path=next_path,
                context_fragments=next_fragments,
                inherited_price=effective_price,
                inherited_currency=effective_currency,
                id_index=id_index,
                lineage_keys=next_lineage,
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                source_url=source_url,
                region=region,
                seen_deals=seen_deals,
                signals=signals,
            )
        return

    if "MenuItem" in node_types:
        _jsonld_menuitem_to_signal(
            resolved,
            context_path=context_path,
            context_fragments=context_fragments,
            inherited_price=effective_price,
            inherited_currency=effective_currency,
            id_index=id_index,
            restaurant_name=restaurant_name,
            local_employer_id=local_employer_id,
            brand_group_id=brand_group_id,
            source_url=source_url,
            region=region,
            seen_deals=seen_deals,
            signals=signals,
        )
        return

    if node_types.intersection({"Offer", "AggregateOffer"}):
        _jsonld_offer_to_signal(
            resolved,
            context_path=context_path,
            context_fragments=context_fragments,
            inherited_price=effective_price,
            inherited_currency=effective_currency,
            id_index=id_index,
            restaurant_name=restaurant_name,
            local_employer_id=local_employer_id,
            brand_group_id=brand_group_id,
            source_url=source_url,
            region=region,
            seen_deals=seen_deals,
            signals=signals,
        )


def _discover_deal_pages(soup: BeautifulSoup, base_url: str) -> list[str]:
    """Discover deal-related subpages by scanning homepage links.

    Scores each link by URL path keywords and anchor text keywords.
    Returns up to 5 discovered URLs, excluding those already in DEAL_PATHS.
    """
    return _discover_candidate_pages(soup, base_url, allow_broad_menu_links=False)


def _discover_candidate_pages(
    soup: BeautifulSoup,
    base_url: str,
    *,
    allow_broad_menu_links: bool,
) -> list[str]:
    parsed_base = urlparse(base_url)
    base_domain = parsed_base.netloc.lower()
    context_keywords = (
        _BROAD_MENU_DISCOVERY_CONTEXT_KEYWORDS
        if allow_broad_menu_links
        else _DISCOVERY_CONTEXT_KEYWORDS
    )

    # Normalize hardcoded paths for dedup
    existing_paths = {p.rstrip("/").lower() for p in DEAL_PATHS}

    scored: list[tuple[int, str]] = []

    def _tag_has_footer_context(tag: Tag) -> bool:
        footer_ancestor = tag.find_parent("footer")
        if footer_ancestor is not None:
            return True
        for ancestor in tag.parents:
            if not isinstance(ancestor, Tag):
                continue
            class_str = " ".join(ancestor.get("class", [])).lower()
            id_str = (ancestor.get("id") or "").lower()
            combined = f"{class_str} {id_str}"
            if any(token in combined for token in _DISCOVERY_FOOTER_TOKENS):
                return True
        return False

    def _context_text(tag: Tag) -> str:
        parts: list[str] = []
        anchor_text = tag.get_text(" ", strip=True)
        if anchor_text:
            parts.append(anchor_text)
        for attr in ("title", "aria-label"):
            val = tag.get(attr)
            if isinstance(val, str) and val.strip():
                parts.append(val.strip())
        parent = tag.find_parent(["li", "div", "section", "footer", "article"])
        if parent is not None:
            parent_text = parent.get_text(" ", strip=True)
            if parent_text:
                parts.append(parent_text[:300])
        return " ".join(parts).lower()

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)
        parsed = urlparse(full_url)

        # Same host by default; low-coverage follow-up may also probe same-brand subdomains.
        if not _hosts_share_brand_domain(base_domain, parsed.netloc.lower()):
            continue
        same_host = _normalized_discovery_host(parsed.netloc) == _normalized_discovery_host(base_domain)

        # Skip non-HTTP schemes (mailto:, tel:, javascript:)
        if parsed.scheme not in ("http", "https"):
            continue

        path = parsed.path.rstrip("/").lower()

        # Skip if it's already in our hardcoded paths on the same host.
        if same_host and (path in existing_paths or path == ""):
            continue
        if not same_host and not allow_broad_menu_links and path == "":
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

        if allow_broad_menu_links and not same_host:
            score += 1

        context_text = _context_text(a_tag)
        anchor_text = a_tag.get_text(" ", strip=True).lower()
        has_soft_label = anchor_text in _DISCOVERY_SOFT_LABELS

        for keyword in context_keywords:
            if keyword in anchor_text:
                score += 2
            elif keyword in context_text:
                score += 1

        # Soft-label links like "Learn More" only count when nearby context or
        # the URL path already looks promotional.
        if has_soft_label and score < 2:
            continue

        if _tag_has_footer_context(a_tag) and score > 0:
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


def _normalized_discovery_host(host: str | None) -> str:
    if not host:
        return ""
    return host.casefold().removeprefix("www.")


def _hosts_share_brand_domain(base_host: str | None, candidate_host: str | None) -> bool:
    normalized_base = _normalized_discovery_host(base_host)
    normalized_candidate = _normalized_discovery_host(candidate_host)
    if not normalized_base or not normalized_candidate:
        return False
    return (
        normalized_candidate == normalized_base
        or normalized_candidate.endswith(f".{normalized_base}")
        or normalized_base.endswith(f".{normalized_candidate}")
    )


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
    fallback_heading: str | None = None,
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
        if _looks_like_menu_badge_noise(sub):
            continue
        if _looks_like_menu_item_discount_badge_noise(sub, source_url):
            continue
        deal_name = _extract_deal_name(sub, fallback_heading=fallback_heading)
        if not deal_name or len(deal_name) < 5:
            continue

        pricing = _extract_deal_pricing(sub)
        if pricing.is_addon or pricing.is_non_food:
            continue

        deal_type = _classify_deal_type(sub)
        valid_days = _extract_days(sub)
        start_time, end_time = _extract_times(sub)
        name_key = _deal_seen_key(
            deal_name=deal_name,
            source_url=source_url,
            valid_days=valid_days,
            valid_start_time=start_time,
            valid_end_time=end_time,
            price=pricing.price,
        )
        if name_key in seen_deals:
            continue
        seen_deals.add(name_key)

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


_RENDER_CRITICAL_PATH_TOKENS = (
    "menu", "deal", "offer", "promo", "promotion",
    "special", "happy-hour", "happyhour", "value", "lunch",
)


def _evaluate_render_decision(
    *,
    page_url: str,
    page_signals: list[DealSignal],
    sections_delta: int,
    items_delta: int,
    price_points_delta: int,
    budget: RenderBudget,
    allowlist_domains: Iterable[str] = (),
) -> dict[str, Any]:
    """Derive evidence for this page and ask render_policy whether to escalate.

    No actual rendering happens yet — decisions are logged to the debug
    bundle so we can audit escalation cadence before wiring Playwright.
    """
    parsed = urlparse(page_url)
    host = parsed.netloc.lower()
    path = parsed.path.lower()
    static_html_empty = (
        not page_signals
        and sections_delta == 0
        and items_delta == 0
        and price_points_delta == 0
    )
    menu_critical = any(token in path for token in _RENDER_CRITICAL_PATH_TOKENS) or path in ("", "/")
    # Rough discovery score: path match alone is weak; paired with zero
    # static extraction it reads as "page *should* have had content."
    if any(token in path for token in _RENDER_CRITICAL_PATH_TOKENS):
        score = 0.8 if static_html_empty else 0.4
    else:
        score = 0.3
    evidence = PageEvidence(
        page_url=page_url,
        domain=host,
        static_html_empty=static_html_empty,
        menu_critical=menu_critical,
        discovery_evidence_score=score,
        discovered_via=None,
    )
    decision = should_render(evidence, budget=budget, allowlist_domains=allowlist_domains)
    return {
        "page_url": page_url,
        "should_render": decision.should_render,
        "reason": decision.reason,
        "budget_category": decision.budget_category,
        "static_html_empty": static_html_empty,
        "menu_critical": menu_critical,
        "discovery_evidence_score": score,
    }


_SOURCE_FETCH_TYPE_RANK = {
    "pdf": 4,
    "embedded_action": 3,
    "discovered": 3,
    "locator_hint": 2,
    "hardcoded": 1,
}

_URL_MDY_RE = re.compile(r"(?<!\d)(?P<month>\d{1,2})[._-](?P<day>\d{1,2})[._-](?P<year>20\d{2})(?!\d)")
_URL_YMD_RE = re.compile(r"(?<!\d)(?P<year>20\d{2})[._-](?P<month>\d{1,2})[._-](?P<day>\d{1,2})(?!\d)")
_URL_YEAR_MONTH_RE = re.compile(r"/(?P<year>20\d{2})/(?P<month>0?[1-9]|1[0-2])(?:/|$)")
_URL_YEAR_ONLY_RE = re.compile(r"(?<!\d)(?P<year>20\d{2})(?!\d)")


def _normalize_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _infer_document_date_from_url(url: str | None) -> datetime | None:
    text = (url or "").lower()
    if not text:
        return None

    for pattern in (_URL_YMD_RE, _URL_MDY_RE):
        match = pattern.search(text)
        if not match:
            continue
        try:
            return datetime(
                int(match.group("year")),
                int(match.group("month")),
                int(match.group("day")),
                tzinfo=timezone.utc,
            )
        except ValueError:
            continue

    match = _URL_YEAR_MONTH_RE.search(text)
    if match:
        try:
            return datetime(
                int(match.group("year")),
                int(match.group("month")),
                1,
                tzinfo=timezone.utc,
            )
        except ValueError:
            pass

    match = _URL_YEAR_ONLY_RE.search(text)
    if match:
        try:
            return datetime(int(match.group("year")), 1, 1, tzinfo=timezone.utc)
        except ValueError:
            return None
    return None


def _extract_page_source_metadata(
    soup: BeautifulSoup,
    *,
    page_url: str,
    fetch_type: str | None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"source_content_type": "html"}
    if fetch_type:
        metadata["source_fetch_type"] = fetch_type

    published_at: datetime | None = None
    modified_at: datetime | None = None
    meta_specs = [
        ("published", {"property": "article:published_time"}),
        ("published", {"property": "og:published_time"}),
        ("published", {"name": "article:published_time"}),
        ("published", {"itemprop": "datePublished"}),
        ("modified", {"property": "article:modified_time"}),
        ("modified", {"property": "og:updated_time"}),
        ("modified", {"name": "lastmod"}),
        ("modified", {"itemprop": "dateModified"}),
    ]
    for kind, attrs in meta_specs:
        tag = soup.find("meta", attrs=attrs)
        parsed = _normalize_utc_datetime(_jsonld_parse_datetime(tag.get("content") if tag else None))
        if parsed is None:
            continue
        if kind == "published" and published_at is None:
            published_at = parsed
        if kind == "modified" and modified_at is None:
            modified_at = parsed

    for tag in soup.find_all(attrs={"datetime": True}):
        parsed = _normalize_utc_datetime(_jsonld_parse_datetime(tag.get("datetime")))
        if parsed is None:
            continue
        class_blob = " ".join(tag.get("class", [])).lower()
        itemprop = str(tag.get("itemprop") or "").lower()
        if "updated" in class_blob or "modified" in class_blob or itemprop == "datemodified":
            if modified_at is None:
                modified_at = parsed
            continue
        if published_at is None:
            published_at = parsed

    for tag in soup.find_all(attrs={"title": True}):
        class_blob = " ".join(tag.get("class", [])).lower()
        itemprop = str(tag.get("itemprop") or "").lower()
        if itemprop not in {"datepublished", "datemodified"} and not any(
            token in class_blob for token in ("published", "updated", "modified", "date")
        ):
            continue
        parsed = _normalize_utc_datetime(_jsonld_parse_datetime(tag.get("title")))
        if parsed is None:
            continue
        if "updated" in class_blob or "modified" in class_blob or itemprop == "datemodified":
            if modified_at is None:
                modified_at = parsed
            continue
        if published_at is None:
            published_at = parsed

    if published_at is not None:
        metadata["source_page_published_at"] = published_at.isoformat()
    if modified_at is not None:
        metadata["source_page_modified_at"] = modified_at.isoformat()

    document_date = _infer_document_date_from_url(page_url)
    if document_date is not None:
        metadata["source_document_date"] = document_date.isoformat()
    return metadata


def _extract_page_artifacts(
    html: str,
    *,
    page_url: str,
    fetch_type: str | None,
    restaurant_name: str,
    local_employer_id: int,
    brand_group_id: int | None,
    region: str,
    seen_deals: set[str],
    sidecar: MenuSidecar | None = None,
) -> tuple[BeautifulSoup, list[DealSignal], list[float], list[str]]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = _extract_text_blocks(soup)
    page_prices = _extract_all_prices(blocks)
    page_signals: list[DealSignal] = []

    for block in blocks:
        page_signals.extend(_text_block_to_signals(
            block,
            restaurant_name=restaurant_name,
            local_employer_id=local_employer_id,
            brand_group_id=brand_group_id,
            source_url=page_url,
            region=region,
            seen_deals=seen_deals,
        ))

    page_signals.extend(_extract_jsonld_deals(
        html,
        restaurant_name,
        local_employer_id,
        brand_group_id,
        page_url,
        region,
        seen_deals,
    ))

    page_signals.extend(_extract_embedded_app_deals(
        html,
        restaurant_name=restaurant_name,
        local_employer_id=local_employer_id,
        brand_group_id=brand_group_id,
        page_url=page_url,
        region=region,
        seen_deals=seen_deals,
    ))

    _annotate_signals(
        page_signals,
        _extract_page_source_metadata(
            soup,
            page_url=page_url,
            fetch_type=fetch_type,
        ),
    )

    if sidecar is not None:
        _populate_sidecar_for_page(sidecar, html=html, soup=soup, page_url=page_url)
        _link_signals_to_sidecar(sidecar, page_signals, page_url=page_url)

    pdf_links = _discover_pdf_links(soup, page_url)
    return soup, page_signals, page_prices, pdf_links


def _normalized_signal_text(value: str | None) -> str:
    cleaned = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", value or "")
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _normalized_signal_url(value: str | None) -> str:
    return (value or "").rstrip("/").lower()


def _signal_cta_url(signal: DealSignal) -> str | None:
    metadata = signal.metadata or {}
    cta_url = metadata.get("embedded_app_cta_url")
    if isinstance(cta_url, str) and cta_url:
        return cta_url.rstrip("/")
    return None


def _deal_seen_key(
    *,
    deal_name: str | None,
    source_url: str | None,
    valid_days: str | None,
    valid_start_time: str | None,
    valid_end_time: str | None,
    price: float | None,
) -> str:
    price_key = "" if price is None else f"{price:.2f}"
    return "|".join(
        [
            _normalized_signal_text(deal_name),
            _normalized_signal_url(source_url),
            valid_days or "",
            valid_start_time or "",
            valid_end_time or "",
            price_key,
        ]
    )


def _signal_seen_key(signal: DealSignal) -> str:
    return _deal_seen_key(
        deal_name=signal.deal_name,
        source_url=signal.source_url,
        valid_days=signal.valid_days,
        valid_start_time=signal.valid_start_time,
        valid_end_time=signal.valid_end_time,
        price=signal.price,
    )


def _signal_evidence_datetime(signal: DealSignal) -> datetime | None:
    metadata = signal.metadata or {}
    for key in ("source_page_modified_at", "source_document_date", "source_page_published_at"):
        parsed = _normalize_utc_datetime(_jsonld_parse_datetime(metadata.get(key)))
        if parsed is not None:
            return parsed
    return _infer_document_date_from_url(signal.source_url)


def _signal_source_rank(signal: DealSignal) -> int:
    metadata = signal.metadata or {}
    fetch_type = metadata.get("source_fetch_type")
    if not isinstance(fetch_type, str) or not fetch_type:
        fetch_type = "pdf" if str(signal.source_url or "").lower().endswith(".pdf") else None

    rank = _SOURCE_FETCH_TYPE_RANK.get(fetch_type, 0)
    evidence_dt = _signal_evidence_datetime(signal)
    if fetch_type == "hardcoded" and evidence_dt is not None:
        age_days = max((datetime.now(timezone.utc) - evidence_dt).days, 0)
        if age_days >= 365 * 5:
            rank -= 2
        elif age_days >= 365 * 3:
            rank -= 1
    return rank


def _signal_selection_score(signal: DealSignal) -> tuple[int, float, int, int]:
    raw_text = signal.raw_scraped_text or signal.deal_description or ""
    evidence_dt = _signal_evidence_datetime(signal)
    recency_score = evidence_dt.timestamp() if evidence_dt is not None else 0.0
    return (
        _signal_source_rank(signal),
        recency_score,
        _signal_detail_score(signal),
        _signal_name_score(signal.deal_name, raw_text=raw_text),
    )


def _signal_detail_score(signal: DealSignal) -> int:
    score = 0
    if signal.price is not None:
        score += 4
    if signal.price_type:
        score += 2
    if signal.discount_percentage is not None:
        score += 2
    if signal.valid_days:
        score += 2
    if signal.valid_start_time:
        score += 1
    if signal.valid_end_time:
        score += 1
    if signal.start_date is not None:
        score += 1
    if signal.end_date is not None:
        score += 1
    if _signal_cta_url(signal):
        score += 1
    score += min(len(signal.raw_scraped_text or ""), 240) // 60
    return score


def _signal_has_text_overlap(left: DealSignal, right: DealSignal) -> bool:
    left_text = _normalized_signal_text(left.raw_scraped_text or left.deal_description or left.deal_name)
    right_text = _normalized_signal_text(right.raw_scraped_text or right.deal_description or right.deal_name)
    if not left_text or not right_text:
        return False
    return left_text == right_text or left_text in right_text or right_text in left_text


def _signals_temporally_compatible(left: DealSignal, right: DealSignal) -> bool:
    for attr in ("valid_days", "valid_start_time", "valid_end_time", "start_date", "end_date"):
        left_value = getattr(left, attr)
        right_value = getattr(right, attr)
        if left_value is not None and right_value is not None and left_value != right_value:
            return False
    return True


def _maybe_refine_signal_name(signal: DealSignal) -> DealSignal:
    raw_text = signal.raw_scraped_text or signal.deal_description or ""
    if not raw_text:
        return signal

    current_score = _signal_name_score(signal.deal_name, raw_text=raw_text)
    if current_score > 3:
        return signal

    candidate = _extract_deal_name(raw_text, fallback_heading=None)
    if candidate and _signal_name_score(candidate, raw_text=raw_text) > current_score:
        signal.deal_name = candidate
    return signal


def _can_merge_by_identity(left: DealSignal, right: DealSignal) -> bool:
    if left.deal_type != right.deal_type:
        return False

    same_page = _normalized_signal_url(left.source_url) == _normalized_signal_url(right.source_url)
    left_name = _normalized_signal_text(left.deal_name)
    right_name = _normalized_signal_text(right.deal_name)
    if same_page and left_name and left_name == right_name:
        if not _signals_temporally_compatible(left, right):
            return False
        return True

    if same_page and left.deal_type == "happy_hour" and _signals_temporally_compatible(left, right):
        left_text = _normalized_signal_text(left.raw_scraped_text or left.deal_description or left.deal_name)
        right_text = _normalized_signal_text(right.raw_scraped_text or right.deal_description or right.deal_name)
        if "happy hour" in left_text and "happy hour" in right_text:
            return True

    left_cta = _signal_cta_url(left)
    right_cta = _signal_cta_url(right)
    if left_cta and left_cta == right_cta:
        if not _signals_temporally_compatible(left, right):
            return False
        return True

    if not _signals_temporally_compatible(left, right):
        return False
    return _signal_has_text_overlap(left, right)


def _is_weak_promotional_variant(signal: DealSignal) -> bool:
    raw_text = signal.raw_scraped_text or signal.deal_description or ""
    if _signal_name_score(signal.deal_name, raw_text=raw_text) <= 2:
        return True
    return (
        signal.price is None
        and signal.discount_percentage is None
        and not signal.valid_days
        and not signal.valid_start_time
        and not signal.valid_end_time
        and len(raw_text) <= 100
    )


def _can_absorb_weak_variant(primary: DealSignal, weak: DealSignal) -> bool:
    if _normalized_signal_url(primary.source_url) != _normalized_signal_url(weak.source_url):
        return False
    if primary.deal_type != weak.deal_type:
        return False
    if not _signals_temporally_compatible(primary, weak):
        return False
    if _signal_cta_url(primary) and _signal_cta_url(primary) == _signal_cta_url(weak):
        return True

    primary_text = _normalized_signal_text(primary.raw_scraped_text or primary.deal_description or primary.deal_name)
    weak_name = _normalized_signal_text(weak.deal_name)
    weak_text = _normalized_signal_text(weak.raw_scraped_text or weak.deal_description or weak.deal_name)
    if weak_name and weak_name in primary_text:
        return True
    if weak.deal_type == "happy_hour" and "happy hour" in primary_text and "happy hour" in weak_text:
        return _signal_detail_score(primary) >= _signal_detail_score(weak)
    return False


def _merge_signal_pair(left: DealSignal, right: DealSignal) -> DealSignal:
    left_score = _signal_selection_score(left)
    right_score = _signal_selection_score(right)
    primary = left if left_score >= right_score else right
    secondary = right if primary is left else left
    merged = deepcopy(primary)

    best_name_signal = max(
        (left, right),
        key=lambda signal: (
            _signal_name_score(signal.deal_name, raw_text=signal.raw_scraped_text),
            _signal_selection_score(signal),
            _signal_detail_score(signal),
            -len(_trim_name(signal.deal_name or "")),
        ),
    )
    merged.deal_name = best_name_signal.deal_name

    richest_signal = max(
        (left, right),
        key=lambda signal: (
            _signal_selection_score(signal),
            _signal_detail_score(signal),
            len(signal.raw_scraped_text or signal.deal_description or ""),
        ),
    )
    if richest_signal.raw_scraped_text:
        merged.raw_scraped_text = richest_signal.raw_scraped_text
    if richest_signal.deal_description:
        merged.deal_description = richest_signal.deal_description
    elif richest_signal.raw_scraped_text:
        merged.deal_description = richest_signal.raw_scraped_text[:500]

    for attr in (
        "price",
        "price_type",
        "discount_percentage",
        "original_price",
        "menu_avg_price",
        "calories",
        "calorie_price_ratio",
        "valid_days",
        "valid_start_time",
        "valid_end_time",
        "start_date",
        "end_date",
    ):
        if getattr(merged, attr) is None and getattr(secondary, attr) is not None:
            setattr(merged, attr, getattr(secondary, attr))

    if merged.price is not None and merged.price_type is None and secondary.price_type:
        merged.price_type = secondary.price_type

    if secondary.metadata:
        if merged.metadata is None:
            merged.metadata = {}
        for key, value in secondary.metadata.items():
            merged.metadata.setdefault(key, deepcopy(value))
        primary_target = merged.metadata.get("offer_target")
        secondary_target = secondary.metadata.get("offer_target")
        if (
            isinstance(primary_target, dict)
            and isinstance(secondary_target, dict)
            and primary_target.get("disposition") == "discard"
            and secondary_target.get("disposition") != "discard"
        ):
            merged.metadata["offer_target"] = deepcopy(secondary_target)

    return _maybe_refine_signal_name(merged)


def _consolidate_site_signals(signals: list[DealSignal]) -> list[DealSignal]:
    """Collapse low-quality same-page variants without losing richer facts."""
    if len(signals) < 2:
        return [_maybe_refine_signal_name(signal) for signal in signals]

    merged_by_identity: list[DealSignal] = []
    for signal in signals:
        signal = _maybe_refine_signal_name(signal)
        for index, existing in enumerate(merged_by_identity):
            if _can_merge_by_identity(existing, signal):
                merged_by_identity[index] = _merge_signal_pair(existing, signal)
                break
        else:
            merged_by_identity.append(signal)

    ordered = sorted(
        merged_by_identity,
        key=lambda signal: (
            int(not _is_weak_promotional_variant(signal)),
            *_signal_selection_score(signal),
        ),
        reverse=True,
    )

    consolidated: list[DealSignal] = []
    for signal in ordered:
        if _is_weak_promotional_variant(signal):
            best_index: int | None = None
            best_score: tuple[int, int] | None = None
            for index, existing in enumerate(consolidated):
                if not _can_absorb_weak_variant(existing, signal):
                    continue
                score = (
                    _signal_selection_score(existing),
                    _signal_detail_score(existing),
                    _signal_name_score(existing.deal_name, raw_text=existing.raw_scraped_text),
                )
                if best_score is None or score > best_score:
                    best_index = index
                    best_score = score
            if best_index is not None:
                consolidated[best_index] = _merge_signal_pair(consolidated[best_index], signal)
                continue
        consolidated.append(signal)

    final_signals: list[DealSignal] = []
    for signal in consolidated:
        signal_text = _normalized_signal_text(signal.raw_scraped_text or signal.deal_description or signal.deal_name)
        signal_name = _normalized_signal_text(signal.deal_name)
        for index, existing in enumerate(final_signals):
            if existing.deal_type != signal.deal_type:
                continue
            if _normalized_signal_url(existing.source_url) != _normalized_signal_url(signal.source_url):
                continue
            if not _signals_temporally_compatible(existing, signal):
                continue
            existing_text = _normalized_signal_text(existing.raw_scraped_text or existing.deal_description or existing.deal_name)
            existing_name = _normalized_signal_text(existing.deal_name)
            if (
                _signal_has_text_overlap(existing, signal)
                or (signal_name and signal_name in existing_text)
                or (existing_name and existing_name in signal_text)
            ):
                final_signals[index] = _merge_signal_pair(existing, signal)
                break
        else:
            final_signals.append(signal)

    return sorted(
        final_signals,
        key=lambda signal: (
            int(not _is_weak_promotional_variant(signal)),
            *_signal_selection_score(signal),
        ),
        reverse=True,
    )


def _populate_sidecar_for_page(
    sidecar: MenuSidecar,
    *,
    html: str,
    soup: BeautifulSoup,
    page_url: str,
) -> None:
    """Feed a page's JSON-LD (preferred) and DOM (fallback) into the sidecar."""
    sections_before = len(sidecar.sections)
    items_before = len(sidecar.items)
    price_points_before = len(sidecar.price_points)
    try:
        ingest_jsonld_from_html(html, page_url=page_url, sidecar=sidecar)
    except Exception as exc:  # pragma: no cover — never let sidecar kill the scrape
        logger.debug("[WebScraper] sidecar JSON-LD ingest failed for %s: %s", page_url, exc)

    page_key = next((key for key, page in sidecar.pages.items() if page.url == page_url), None)
    has_unnamed_sections = bool(page_key) and any(
        section.page_key == page_key and section.name in {"(unnamed)", "(unsectioned)"}
        for section in sidecar.sections.values()
    )
    needs_dom_fallback = (
        (len(sidecar.sections) == sections_before and len(sidecar.items) == items_before)
        or (len(sidecar.items) > items_before and len(sidecar.price_points) == price_points_before)
        or has_unnamed_sections
    )

    if needs_dom_fallback:
        try:
            ingest_dom_fallback(soup, page_url=page_url, sidecar=sidecar)
        except Exception as exc:  # pragma: no cover
            logger.debug("[WebScraper] sidecar DOM ingest failed for %s: %s", page_url, exc)


def _link_signals_to_sidecar(
    sidecar: MenuSidecar,
    signals: list[DealSignal],
    *,
    page_url: str,
) -> None:
    """Attach an offer_target metadata entry to each signal when possible."""
    for signal in signals:
        if signal.metadata is None:
            signal.metadata = {}
        if "offer_target" in signal.metadata:
            continue

        jsonld_path = signal.metadata.get("jsonld_path") if isinstance(signal.metadata, dict) else None
        primary_name = signal.metadata.get("jsonld_primary_name") if isinstance(signal.metadata, dict) else None
        service_period = _infer_service_period_from_signal(signal)
        signal_ref = (signal.deal_name or "").lower()[:120]
        target = link_signal_to_target(
            sidecar,
            signal_ref=signal_ref,
            page_url=signal.source_url or page_url,
            context_path=jsonld_path if isinstance(jsonld_path, list) else None,
            primary_name=primary_name if isinstance(primary_name, str) else signal.deal_name,
            service_period=service_period,
        )
        if target is not None:
            signal.metadata["offer_target"] = target


def _infer_service_period_from_signal(signal: DealSignal) -> str | None:
    deal_type = (signal.deal_type or "").lower()
    if deal_type in ("happy_hour", "lunch_special", "daily_special", "kids_eat_free"):
        if deal_type == "happy_hour":
            return "happy_hour"
        if deal_type == "lunch_special":
            return "lunch"
    return None


def _attach_value_profile_from_sidecar(
    signals: list[DealSignal],
    sidecar: MenuSidecar,
) -> None:
    """PRICE-02: attach the specific category baseline + savings to each signal.

    We keep the attachment narrow: only the baseline relevant to the signal's
    offer target ends up on metadata, plus an estimated_savings when the
    signal carries an absolute price. No aggregate map gets broadcast.
    """
    course_baselines = sidecar.course_price_baseline()
    section_baselines = sidecar.section_price_baseline()
    if not course_baselines and not section_baselines:
        return

    for sig in signals:
        if sig.metadata is None:
            sig.metadata = {}
        target = sig.metadata.get("offer_target") or {}
        if not isinstance(target, dict):
            continue

        section_key = target.get("section_key")
        item_key = target.get("item_key")
        course = None
        if item_key and item_key in sidecar.items:
            course = sidecar.items[item_key].course
        if not course and section_key and section_key in sidecar.sections:
            course = sidecar.sections[section_key].course

        value_profile: dict[str, Any] = {}
        if course and course in course_baselines:
            value_profile["course"] = course
            value_profile["course_baseline"] = course_baselines[course]
        if section_key and section_key in section_baselines:
            value_profile["section_baseline"] = section_baselines[section_key]

        baseline_for_savings: float | None = (
            value_profile.get("section_baseline")
            or value_profile.get("course_baseline")
        )
        if (
            sig.price is not None
            and sig.price_type == "absolute"
            and baseline_for_savings is not None
            and baseline_for_savings > sig.price
        ):
            savings = round(baseline_for_savings - sig.price, 2)
            value_profile["estimated_savings"] = savings
            value_profile["estimated_savings_pct"] = round(
                100.0 * savings / baseline_for_savings, 1
            )

        if value_profile:
            sig.metadata.setdefault("value_profile", value_profile)


def _download_pdf_text(pdf_url: str) -> str | None:
    """Download a PDF and extract plain text for later parsing."""
    text, _ = _download_pdf_artifacts(pdf_url)
    return text


def _download_pdf_artifacts(pdf_url: str) -> tuple[str | None, list[list[list[str | None]]]]:
    """Download a PDF and return (text, tables).

    PDF-02: also pulls layout-aware tables via pdfplumber.extract_tables()
    so menu rows keep their item-price pairing instead of being flattened
    into a paragraph. Returns ([], []) on any failure.
    """
    if not _HAS_PDFPLUMBER:
        logger.debug("[WebScraper] pdfplumber not installed — skipping PDF: %s", pdf_url)
        return None, []

    try:
        resp = requests.get(
            pdf_url,
            headers={"User-Agent": _get_user_agent()},
            timeout=20,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return None, []

        # Size guard: skip PDFs larger than 5MB
        if len(resp.content) > 5_000_000:
            logger.debug("[WebScraper] PDF too large (%.1f MB): %s", len(resp.content) / 1e6, pdf_url)
            return None, []

        tables: list[list[list[str | None]]] = []
        with pdfplumber.open(BytesIO(resp.content)) as pdf:
            # Page guard: skip PDFs with more than 20 pages
            if len(pdf.pages) > 20:
                logger.debug("[WebScraper] PDF too many pages (%d): %s", len(pdf.pages), pdf_url)
                return None, []

            full_text = ""
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    full_text += page_text + "\n"
                try:
                    page_tables = page.extract_tables() or []
                except Exception:
                    page_tables = []
                for tbl in page_tables:
                    if tbl and len(tbl) >= 2:
                        tables.append(tbl)

        return (full_text.strip() or None), tables

    except Exception as e:
        logger.debug("[WebScraper] Failed to parse PDF %s: %s", pdf_url, e)
        return None, []


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
    sidecar: MenuSidecar | None = None,
) -> list[DealSignal]:
    """Parse a PDF for deal signals, using local debug cache when requested.

    PDF-02: also pulls extract_tables() into the menu sidecar so menu-PDF
    rows feed the baseline and offer-target graph rather than being lost
    to flat text extraction.
    """
    tables: list[list[list[str | None]]] = []
    if replay_debug_cache:
        full_text = _get_debug_pdf_text(debug_bundle, pdf_url)
        tables = _get_debug_pdf_tables(debug_bundle, pdf_url)
        if full_text is None:
            logger.debug("[WebScraper] No cached PDF text for %s", pdf_url)
            return []
    else:
        full_text, tables = _download_pdf_artifacts(pdf_url)
        if full_text and debug_bundle is not None:
            _record_debug_pdf_text(debug_bundle, pdf_url, full_text=full_text, tables=tables)

    if sidecar is not None and tables:
        try:
            ingest_pdf_tables(
                tables,
                page_url=pdf_url,
                section_hint=_pdf_section_hint(pdf_url),
                sidecar=sidecar,
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("[WebScraper] sidecar PDF ingest failed for %s: %s", pdf_url, exc)

    if not full_text:
        return []

    signals = _pdf_text_to_signals(
        full_text,
        pdf_url=pdf_url,
        restaurant_name=restaurant_name,
        local_employer_id=local_employer_id,
        brand_group_id=brand_group_id,
        region=region,
        seen_deals=seen_deals,
    )
    metadata: dict[str, Any] = {
        "source_fetch_type": "pdf",
        "source_content_type": "pdf",
    }
    document_date = _infer_document_date_from_url(pdf_url)
    if document_date is not None:
        metadata["source_document_date"] = document_date.isoformat()
    _annotate_signals(signals, metadata)
    return signals


def _pdf_section_hint(pdf_url: str) -> str | None:
    """Derive a best-effort section label from the PDF filename or path."""
    try:
        path = urlparse(pdf_url).path
    except Exception:
        return None
    if not path:
        return None
    base = path.rsplit("/", 1)[-1]
    name = base.rsplit(".", 1)[0]
    if not name:
        return None
    cleaned = re.sub(r"[-_]+", " ", name).strip()
    return cleaned[:60] or None


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
    domain_family = classify_domain_family(url)
    debug_bundle = _load_site_debug_bundle(url) if replay_debug_cache else _reset_site_debug_bundle(
        url,
        restaurant_name=restaurant_name,
        region=region,
    )
    if replay_debug_cache and debug_bundle is None:
        logger.warning("[WebScraper] No local debug cache for %s", url)
        return []

    if debug_bundle is not None:
        debug_bundle["domain_family"] = domain_family

    if domain_family in _SKIP_DOMAIN_FAMILIES:
        logger.info(
            "[WebScraper] Skipping obvious non-first-party target %s (%s)",
            url,
            domain_family,
        )
        if debug_bundle is not None:
            debug_bundle["skip_reason"] = "non_first_party_target"
            debug_bundle["completed_at"] = datetime.now(timezone.utc).isoformat()
            _write_site_debug_bundle(debug_bundle)
        return []

    signals: list[DealSignal] = []
    seen_deals: set[str] = set()  # dedup by deal_name
    all_menu_prices: list[float] = []  # collect all prices across pages for avg
    all_pdf_links: list[str] = []  # collect PDF links across all pages
    discovered_pages: list[str] = []  # track link-discovered pages
    hinted_pages: list[dict[str, Any]] = []  # track locator-to-corporate hint probes
    discovered_page_sources: dict[str, str] = {}
    discovered_page_seen: set[str] = set()
    fetched_page_urls: set[str] = set()
    pages_fetched = 0
    sidecar = MenuSidecar()  # STRUCT-01: structured menu artifacts for replay

    # ARCH-03: per-run render budget tracker. The requests-only scraper does
    # not actually escalate to Playwright yet, so decisions are recorded into
    # the debug bundle in audit-only mode — this lets us tune thresholds and
    # allowlists from real traffic before wiring an actual renderer.
    render_budget = RenderBudget()
    render_decisions: list[dict[str, Any]] = []

    # ARCH-04: exploration-only hints, filtered to the site's apex domain so
    # we only probe brand-relevant slugs. Hints are never trusted as evidence.
    try:
        all_hints = load_hints()
    except Exception as exc:  # pragma: no cover — registry bugs must not kill scrapes
        logger.warning("[WebScraper] hint registry load failed: %s", exc)
        all_hints = []
    apex_domain = parsed.netloc.lower().removeprefix("www.").removeprefix("locations.")
    registry_hints = [
        h for h in all_hints
        if h.target_domain and (
            h.target_domain == apex_domain or apex_domain.endswith(f".{h.target_domain}")
        )
    ]

    # --- Phase 1: Hardcoded paths ---
    homepage_soup = None

    for path in DEAL_PATHS:
        if pages_fetched >= MAX_PAGES_PER_SITE:
            break

        full_url = urljoin(base_url, path)

        html = _get_replay_page(debug_bundle, full_url) if replay_debug_cache else _fetch_page(full_url, user_agent)
        if not html:
            continue
        fetched_page_urls.add(full_url.rstrip("/"))
        if not replay_debug_cache and debug_bundle is not None:
            _record_debug_page(debug_bundle, full_url, html=html, fetch_type="hardcoded")

        pages_fetched += 1
        sections_before = len(sidecar.sections)
        items_before = len(sidecar.items)
        pp_before = len(sidecar.price_points)
        soup, page_signals, page_prices, page_pdf_links = _extract_page_artifacts(
            html,
            page_url=full_url,
            fetch_type="hardcoded",
            restaurant_name=restaurant_name,
            local_employer_id=local_employer_id,
            brand_group_id=brand_group_id,
            region=region,
            seen_deals=seen_deals,
            sidecar=sidecar,
        )
        signals.extend(page_signals)
        all_menu_prices.extend(page_prices)
        all_pdf_links.extend(page_pdf_links)
        render_decisions.append(_evaluate_render_decision(
            page_url=full_url,
            page_signals=page_signals,
            sections_delta=len(sidecar.sections) - sections_before,
            items_delta=len(sidecar.items) - items_before,
            price_points_delta=len(sidecar.price_points) - pp_before,
            budget=render_budget,
        ))

        for embedded_url in _discover_embedded_app_pages(html, page_url=full_url):
            normalized = embedded_url.rstrip("/")
            if normalized in fetched_page_urls or normalized in discovered_page_seen:
                continue
            discovered_page_seen.add(normalized)
            discovered_pages.append(embedded_url)
            discovered_page_sources[embedded_url] = "embedded_action"

        # Save homepage soup for link discovery
        if path == "/":
            homepage_soup = soup

        # Rate limit: 1 req/sec between pages
        if not replay_debug_cache:
            time.sleep(1.0)

    # --- Phase 2a: Locator-specific corporate hint routing ---
    if homepage_soup and domain_family == "locator" and pages_fetched < MAX_PAGES_PER_SITE:
        locator_hint_pages = _discover_locator_corporate_pages(
            homepage_soup, url, registry_hints=registry_hints,
        )

        for hint in locator_hint_pages:
            if pages_fetched >= MAX_PAGES_PER_SITE:
                break

            hint_url = str(hint.get("url") or "").strip()
            if not hint_url:
                continue

            hint_entry: dict[str, Any] = {
                "url": hint_url,
                "reason": str(hint.get("reason") or "locator_corporate_hint"),
            }
            if "hint_audit" in hint:
                hint_entry["hint_audit"] = deepcopy(hint["hint_audit"])
            hinted_pages.append(hint_entry)
            html = _get_replay_page(debug_bundle, hint_url) if replay_debug_cache else _fetch_page(hint_url, user_agent)
            if not html:
                continue
            if not replay_debug_cache and debug_bundle is not None:
                _record_debug_page(debug_bundle, hint_url, html=html, fetch_type="locator_hint")

            pages_fetched += 1
            sections_before = len(sidecar.sections)
            items_before = len(sidecar.items)
            pp_before = len(sidecar.price_points)
            _soup, page_signals, page_prices, page_pdf_links = _extract_page_artifacts(
                html,
                page_url=hint_url,
                fetch_type="locator_hint",
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                region=region,
                seen_deals=seen_deals,
                sidecar=sidecar,
            )
            signal_metadata: dict[str, Any] = {
                "locator_hint_source_url": url,
                "locator_hint_reason": str(hint.get("reason") or "locator_corporate_hint"),
            }
            if "hint_audit" in hint:
                # ARCH-04: hint-sourced signals carry exploration-only provenance.
                signal_metadata["hint_audit"] = deepcopy(hint["hint_audit"])
            _annotate_signals(page_signals, signal_metadata)
            signals.extend(page_signals)
            all_menu_prices.extend(page_prices)
            all_pdf_links.extend(page_pdf_links)
            render_decisions.append(_evaluate_render_decision(
                page_url=hint_url,
                page_signals=page_signals,
                sections_delta=len(sidecar.sections) - sections_before,
                items_delta=len(sidecar.items) - items_before,
                price_points_delta=len(sidecar.price_points) - pp_before,
                budget=render_budget,
            ))

            if not replay_debug_cache:
                time.sleep(1.0)

    # --- Phase 2b: Discover additional same-domain deal pages from homepage links ---
    if homepage_soup and pages_fetched < MAX_PAGES_PER_SITE:
        for disc_url in _discover_deal_pages(homepage_soup, base_url):
            normalized = disc_url.rstrip("/")
            if normalized in fetched_page_urls or normalized in discovered_page_seen:
                continue
            discovered_page_seen.add(normalized)
            discovered_pages.append(disc_url)
            discovered_page_sources[disc_url] = "discovered"

        for disc_url in discovered_pages:
            if pages_fetched >= MAX_PAGES_PER_SITE:
                break

            html = _get_replay_page(debug_bundle, disc_url) if replay_debug_cache else _fetch_page(disc_url, user_agent)
            if not html:
                continue
            fetched_page_urls.add(disc_url.rstrip("/"))
            if not replay_debug_cache and debug_bundle is not None:
                _record_debug_page(
                    debug_bundle,
                    disc_url,
                    html=html,
                    fetch_type=discovered_page_sources.get(disc_url, "discovered"),
                )

            pages_fetched += 1
            sections_before = len(sidecar.sections)
            items_before = len(sidecar.items)
            pp_before = len(sidecar.price_points)
            _soup, page_signals, page_prices, page_pdf_links = _extract_page_artifacts(
                html,
                page_url=disc_url,
                fetch_type=discovered_page_sources.get(disc_url, "discovered"),
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                region=region,
                seen_deals=seen_deals,
                sidecar=sidecar,
            )
            signals.extend(page_signals)
            all_menu_prices.extend(page_prices)
            all_pdf_links.extend(page_pdf_links)
            render_decisions.append(_evaluate_render_decision(
                page_url=disc_url,
                page_signals=page_signals,
                sections_delta=len(sidecar.sections) - sections_before,
                items_delta=len(sidecar.items) - items_before,
                price_points_delta=len(sidecar.price_points) - pp_before,
                budget=render_budget,
            ))

            if not replay_debug_cache:
                time.sleep(1.0)

    # --- Phase 2c: Low-coverage menu recovery ---
    if (
        homepage_soup
        and pages_fetched < MAX_PAGES_PER_SITE
        and (
            len(sidecar.items) < _LOW_MENU_COVERAGE_THRESHOLD
            or len(sidecar.price_points) < _LOW_MENU_COVERAGE_THRESHOLD
        )
    ):
        low_coverage_pages: list[str] = []
        for disc_url in _discover_candidate_pages(
            homepage_soup,
            base_url,
            allow_broad_menu_links=True,
        ):
            normalized = disc_url.rstrip("/")
            if normalized in fetched_page_urls or normalized in discovered_page_seen:
                continue
            discovered_page_seen.add(normalized)
            discovered_pages.append(disc_url)
            discovered_page_sources[disc_url] = "low_coverage_menu"
            low_coverage_pages.append(disc_url)

        for disc_url in low_coverage_pages:
            if pages_fetched >= MAX_PAGES_PER_SITE:
                break

            html = _get_replay_page(debug_bundle, disc_url) if replay_debug_cache else _fetch_page(disc_url, user_agent)
            if not html:
                continue
            fetched_page_urls.add(disc_url.rstrip("/"))
            if not replay_debug_cache and debug_bundle is not None:
                _record_debug_page(
                    debug_bundle,
                    disc_url,
                    html=html,
                    fetch_type="low_coverage_menu",
                )

            pages_fetched += 1
            sections_before = len(sidecar.sections)
            items_before = len(sidecar.items)
            pp_before = len(sidecar.price_points)
            _soup, page_signals, page_prices, page_pdf_links = _extract_page_artifacts(
                html,
                page_url=disc_url,
                fetch_type="low_coverage_menu",
                restaurant_name=restaurant_name,
                local_employer_id=local_employer_id,
                brand_group_id=brand_group_id,
                region=region,
                seen_deals=seen_deals,
                sidecar=sidecar,
            )
            signals.extend(page_signals)
            all_menu_prices.extend(page_prices)
            all_pdf_links.extend(page_pdf_links)
            render_decisions.append(_evaluate_render_decision(
                page_url=disc_url,
                page_signals=page_signals,
                sections_delta=len(sidecar.sections) - sections_before,
                items_delta=len(sidecar.items) - items_before,
                price_points_delta=len(sidecar.price_points) - pp_before,
                budget=render_budget,
            ))

            if not replay_debug_cache:
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
            sidecar=sidecar,
        )
        signals.extend(pdf_signals)
        if not replay_debug_cache:
            time.sleep(1.0)

    signals = _consolidate_site_signals(signals)

    # Compute menu average price and attach to each signal
    menu_avg_price = None
    if all_menu_prices and len(all_menu_prices) >= 3:
        menu_avg_price = round(sum(all_menu_prices) / len(all_menu_prices), 2)
        for sig in signals:
            sig.menu_avg_price = menu_avg_price

    # PRICE-02: sidecar-derived category baseline + savings estimate. The
    # existing flat `menu_avg_price` stays unchanged for back-compat; richer
    # evidence goes on signal.metadata without DB schema changes.
    _attach_value_profile_from_sidecar(signals, sidecar)

    _finalize_site_debug_bundle(
        debug_bundle,
        signals=signals,
        discovered_pages=discovered_pages,
        hinted_pages=hinted_pages,
        pdf_links=unique_pdfs,
        menu_avg_price=menu_avg_price,
        sidecar=sidecar,
        render_decisions=render_decisions,
        render_budget=render_budget,
        restaurant_id=str(local_employer_id) if local_employer_id is not None else None,
        source_url=base_url,
    )

    try:
        shape = debug_bundle.get("menu_persistence_shape")
        if shape and local_employer_id is not None:
            session = get_session(get_engine())
            try:
                upsert_menu_shape(session, shape)
                session.commit()
            finally:
                session.close()
    except Exception as exc:
        logger.warning("menu_db_upsert failed for %s: %s", base_url, exc)

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


def load_website_scrape_target_groups(
    session: Any,
    *,
    region: str = "austin_tx",
    max_sites: int = 100,
    skip_checked_days: int | None = 3,
) -> tuple[list[tuple[str, list[tuple[Any, Any]]]], int]:
    """Load the exact deduped target URL groups the website scraper will process."""
    from collections import defaultdict
    from datetime import timedelta

    from core.database import LocalEmployer, RestaurantURL

    url_filters = [
        RestaurantURL.is_active.is_(True),
        LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
        LocalEmployer.region == region,
        LocalEmployer.is_active.is_(True),
    ]
    if skip_checked_days:
        cutoff = datetime.now(timezone.utc) - timedelta(days=skip_checked_days)
        url_filters.append(
            (RestaurantURL.last_checked.is_(None))
            | (RestaurantURL.last_checked < cutoff)
        )
        logger.info(
            "[WebScraper] Skipping sites checked within the last %d day(s)",
            skip_checked_days,
        )

    urls = (
        session.query(RestaurantURL, LocalEmployer)
        .join(LocalEmployer, LocalEmployer.id == RestaurantURL.local_employer_id)
        .filter(*url_filters)
        .order_by(RestaurantURL.last_checked.asc().nullsfirst())
        .all()
    )

    url_groups_raw: dict[str, list[tuple[Any, Any]]] = defaultdict(list)
    skipped_rows = 0
    for rurl, emp in urls:
        if classify_domain_family(rurl.url) in _SKIP_DOMAIN_FAMILIES:
            skipped_rows += 1
            continue
        normalized = rurl.url.rstrip("/").lower()
        url_groups_raw[normalized].append((rurl, emp))

    group_items = list(url_groups_raw.items())[:max_sites]
    total_rows = sum(len(group) for _, group in group_items)
    if skipped_rows:
        logger.info(
            "[WebScraper] Filtered %d obvious non-first-party restaurant_url rows before queueing targets",
            skipped_rows,
        )

    return group_items, total_rows


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
    INGESTS_INLINE = True

    CHUNK_SIZE = 25  # Lower default to keep Orange Pi RAM stable during full re-scrapes.

    def __init__(self, *, chunk_size: int | None = None) -> None:
        self.chunk_size = max(1, chunk_size or self.CHUNK_SIZE)
        self.last_run_stats: dict[str, Any] = {}

    def collect(
        self,
        region: str = "austin_tx",
        max_sites: int = 100,
        dry_run: bool = False,
        skip_checked_days: int | None = 3,
        replay_debug_cache: bool = False,
    ) -> list[DealSignal]:
        """Scrape websites and return DealSignals.

        Processes in chunks of ``self.chunk_size`` unique URLs. After each chunk the
        DB is committed (last_checked updates), signals are ingested, and the
        audit log is flushed to disk.  This means a crash at site #350 still
        keeps the first 300 sites' data.
        """
        from core.database import get_session, init_db

        engine = init_db()
        session = get_session(engine)

        retained_signals: list[DealSignal] = []
        total_signals_found = 0
        total_skipped = 0
        retain_run_signals = dry_run or replay_debug_cache
        group_items: list[tuple[str, list[tuple[Any, Any]]]] = []
        total_unique = 0

        try:
            # ── Build URL list ──────────────────────────────────────────
            group_items, total_rows = load_website_scrape_target_groups(
                session,
                region=region,
                max_sites=max_sites,
                skip_checked_days=skip_checked_days,
            )
            total_unique = len(group_items)
            logger.info(
                "[WebScraper] Scanning %d unique websites (%d restaurant_url rows)",
                total_unique,
                total_rows,
            )

            # ── Process in chunks ───────────────────────────────────────
            # Clear audit log at the start of a fresh run
            if _SCRAPE_AUDIT_PATH.exists():
                _SCRAPE_AUDIT_PATH.unlink()

            total_ingested = 0
            is_first_chunk = True

            for chunk_start in range(0, len(group_items), self.chunk_size):
                chunk = group_items[chunk_start : chunk_start + self.chunk_size]
                chunk_num = chunk_start // self.chunk_size + 1
                chunk_end = min(chunk_start + self.chunk_size, len(group_items))
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
                        "domain_family": classify_domain_family(rurl_rep.url),
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
                        site_audit.update(_site_audit_context_from_debug_bundle(rurl_rep.url))

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
                            if "total_blocks" not in site_audit:
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
                                            site_audit["discovered_page_count"] = len(disc)
                                        site_audit["page_count"] = max(int(site_audit.get("page_count") or 0), 1)
                                        site_audit.setdefault("page_fetch_types", {"hardcoded": 1})
                                        site_audit.setdefault("structured_data_present", "application/ld+json" in html)
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
                    total_skipped += stats.get("skipped", 0)
                    logger.info(
                        "[WebScraper] Chunk %d ingested: %d rows (%d total so far)",
                        chunk_num, stats.get("total_rows", 0), total_ingested,
                    )

                total_signals_found += len(chunk_signals)
                if retain_run_signals:
                    retained_signals.extend(chunk_signals)

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

        self.last_run_stats = {
            "signals_found": total_signals_found,
            "rows_written": total_ingested,
            "skipped": total_skipped,
            "sites_scanned": total_unique,
            "chunk_size": self.chunk_size,
            "dry_run": dry_run,
            "replay_debug_cache": replay_debug_cache,
        }

        logger.info(
            "[WebScraper] Done: %d deal signals from %d unique sites (%d ingested to DB, chunk_size=%d)",
            total_signals_found,
            total_unique,
            total_ingested,
            self.chunk_size,
        )
        return retained_signals


def run_website_scraper(
    region: str = "austin_tx",
    max_sites: int = 100,
    dry_run: bool = False,
    skip_checked_days: int | None = 3,
    replay_debug_cache: bool = False,
    chunk_size: int | None = None,
) -> dict:
    """Run the website scraper.

    Ingestion happens per-chunk inside collect() — no bulk ingest at the end.
    """
    collector = WebsiteDealCollector(chunk_size=chunk_size)
    collector.collect(
        region=region, max_sites=max_sites, dry_run=dry_run,
        skip_checked_days=skip_checked_days,
        replay_debug_cache=replay_debug_cache,
    )

    summary = collector.last_run_stats

    return {
        "signals_found": summary.get("signals_found", 0),
        "rows_written": summary.get("rows_written", 0),
        "skipped": summary.get("skipped", 0),
        "sites_scanned": summary.get("sites_scanned", 0),
        "chunk_size": summary.get("chunk_size", collector.chunk_size),
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
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=WebsiteDealCollector.CHUNK_SIZE,
        help="Unique-site batch size before ingest/audit flush (default: 25)",
    )
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
        chunk_size=args.chunk_size,
        skip_checked_days=args.skip_checked_days,
        replay_debug_cache=args.replay_debug_cache,
    )
    print(f"\n--- Website Scraper Stats ---")
    for k, v in stats.items():
        print(f"  {k}: {v}")
