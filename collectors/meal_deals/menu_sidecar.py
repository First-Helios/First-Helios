"""
collectors/meal_deals/menu_sidecar.py — Structured menu sidecar artifacts.

STRUCT-01 (roadmap: docs/guides/MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md).

Emits a `menu_sidecar` dict attached to debug bundles (and referenced from
DealSignal metadata). The sidecar is the upstream menu graph — pages,
sections, items, price points, modifiers, offer targets — derived from:
  1. schema.org Menu / MenuSection / MenuItem / Offer hierarchies (preferred).
  2. DOM heading + list/table item-price pairing (fallback).

The sidecar is NOT a persistent table. It lives in replayable debug bundles
and signal metadata so TARGET-01, PRICE-02, and VALUE-01 have evidence to
build on without committing to schema yet.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import deque
from dataclasses import dataclass, field
from html import unescape
from statistics import median
from typing import Any, Iterable
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

# Bounded caps so sidecar JSON stays small even on very large menus.
_MAX_SECTIONS_PER_SITE = 80
_MAX_ITEMS_PER_SITE = 800
_MAX_PRICE_POINTS_PER_SITE = 1600
_MAX_MODIFIERS_PER_SITE = 200
_MAX_OFFER_TARGETS_PER_SITE = 400
_MAX_EVIDENCE_LEN = 280

# Service-period tagging — cheap section-name heuristic.
_SERVICE_PERIOD_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bhappy[\s\-_]*hour\b", re.IGNORECASE), "happy_hour"),
    (re.compile(r"\bbrunch\b", re.IGNORECASE), "brunch"),
    (re.compile(r"\blunch\b", re.IGNORECASE), "lunch"),
    (re.compile(r"\bdinner\b", re.IGNORECASE), "dinner"),
    (re.compile(r"\blate[\s\-_]*night\b", re.IGNORECASE), "late_night"),
    (re.compile(r"\bearly[\s\-_]*bird\b", re.IGNORECASE), "early_bird"),
    (re.compile(r"\bkids\b", re.IGNORECASE), "kids"),
    (re.compile(r"\bweekend\b", re.IGNORECASE), "weekend"),
    (re.compile(r"\bweekday\b", re.IGNORECASE), "weekday"),
)

# Course tagging — also section-name driven, falls back to lexical.
_COURSE_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bappetizer|starter|small\s*plate|shareable|snack", re.IGNORECASE), "appetizer"),
    (re.compile(r"\bsoup|salad\b", re.IGNORECASE), "salad_soup"),
    (re.compile(r"\bentr[eé]e|main|specialt|burger|sandwich|pasta|pizza|taco|plate|platter", re.IGNORECASE), "entree"),
    (re.compile(r"\bside|add\s*on|upgrade|rice|beans|fries|chips|salsa|guacamole", re.IGNORECASE), "side"),
    (re.compile(r"\bdessert|sweet", re.IGNORECASE), "dessert"),
    (re.compile(r"\bdrink|beverage|cocktail|beer|wine|margarita|bar", re.IGNORECASE), "drink"),
    (re.compile(r"\bkids?\s*menu|kids?\s*meal", re.IGNORECASE), "kids"),
    (re.compile(r"\bcombo|bundle|meal\s*deal|family\s*pack", re.IGNORECASE), "combo"),
)

_SCHEMA_MENU_TYPES = frozenset({"Menu", "MenuSection"})

_JSONLD_SCRIPT_RE = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# Compact DOM price pattern — kept local so this module has no circular
# dependency on website_scraper.
_DOM_PRICE_RE = re.compile(r"\$\s*(\d{1,3}(?:\.\d{1,2})?)")

# Modifier patterns in DOM text ("add avocado +$2", "extra protein $3").
_DOM_MODIFIER_RE = re.compile(
    r"(?:\b(?:add|extra|upgrade|substitute|sub)\b[^$]{0,30})(\+?\$\s*\d{1,3}(?:\.\d{1,2})?)",
    re.IGNORECASE,
)
_INLINE_DIETARY_BLOCK_RE = re.compile(
    r"<\s*([a-z][a-z0-9_-]*)\b[^>]*>(.*?)<\s*/\s*\1\s*>",
    re.IGNORECASE | re.DOTALL,
)
_INLINE_HTML_TAG_RE = re.compile(r"<[^>]+>")
_PROMOTIONAL_DOM_SECTION_RE = re.compile(
    r"\b(?:happy\s*hour|daily\s+specials?|deals?|offers?|promotions?)\b",
    re.IGNORECASE,
)
_MEAL_PERIOD_SECTION_RE = re.compile(r"\b(?:breakfast|brunch|lunch|dinner)\b", re.IGNORECASE)
_PROMOTIONAL_DOM_ROW_RE = re.compile(
    r"\b(?:\d{1,2}\s*%\s*off|half\s+off|bogo|buy\s+one|get\s+one|"
    r"\$\s*\d{1,3}(?:\.\d{1,2})?\s*off|all\s+day|open\s+to\s+close|"
    r"until\s+\d|monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b",
    re.IGNORECASE,
)
_SIZE_LABEL_RE = re.compile(
    r"^\s*(?:"
    r"\d+(?:\.\d+)?\s*(?:oz|ounce|ounces|lb|lbs|gal|gallon|qt|quart|pt|pint|cup|cups|liter|liters|l|ml)"
    r"|small|regular|large|x-large|xl|double|triple|single"
    r")\.?\s*$",
    re.IGNORECASE,
)
_DIETARY_TOKEN_MAP: dict[str, str] = {
    "v": "vegetarian",
    "veg": "vegetarian",
    "veggie": "vegetarian",
    "vegetarian": "vegetarian",
    "vegeterian": "vegetarian",
    "vegetariandiet": "vegetarian",
    "vg": "vegan",
    "vegan": "vegan",
    "vegandiet": "vegan",
    "gluten": "gluten_free",
    "glutenfree": "gluten_free",
    "gluten-free": "gluten_free",
    "gf": "gluten_free",
    "glutenfreediet": "gluten_free",
    "halal": "halal",
    "halaldiet": "halal",
    "kosher": "kosher",
    "kosherstyle": "kosher",
    "kosherdiet": "kosher",
    "df": "dairy_free",
    "dairyfree": "dairy_free",
    "dairy-free": "dairy_free",
    "dairyfreediet": "dairy_free",
    "n": "contains_nuts",
    "nut": "contains_nuts",
    "nuts": "contains_nuts",
    "seed": "contains_nuts",
    "seeds": "contains_nuts",
}
_TEXTUAL_DIETARY_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\bvegan\b|\bvg\b", re.IGNORECASE), "vegan"),
    (re.compile(r"\bvegetarian\b|\bveggie\b", re.IGNORECASE), "vegetarian"),
    (re.compile(r"\bgluten[\s-]*free\b|\bgf\b", re.IGNORECASE), "gluten_free"),
    (re.compile(r"\bhalal\b", re.IGNORECASE), "halal"),
    (re.compile(r"\bkosher\b", re.IGNORECASE), "kosher"),
    (re.compile(r"\bdairy[\s-]*free\b|\bdf\b", re.IGNORECASE), "dairy_free"),
    (re.compile(r"\bcontains?\s+nuts?(?:/seeds?)?\b|\bnuts?/seeds?\b", re.IGNORECASE), "contains_nuts"),
)


# ── Data model ──────────────────────────────────────────────────────────────


@dataclass
class MenuPage:
    key: str
    url: str
    source: str  # "jsonld" | "dom"
    renderer: str = "static_html"


@dataclass
class MenuSection:
    key: str
    page_key: str
    name: str
    parent_key: str | None = None
    path: list[str] = field(default_factory=list)
    service_period: str | None = None
    course: str | None = None
    source: str = "jsonld"


@dataclass
class MenuItem:
    key: str
    section_key: str
    name: str
    description: str | None = None
    course: str | None = None
    calories: int | None = None
    dietary_tags: list[str] = field(default_factory=list)
    source: str = "jsonld"


@dataclass
class PricePoint:
    key: str
    item_key: str | None
    section_key: str | None
    price: float
    currency: str | None = None
    variant: str | None = None
    confidence: float = 1.0
    source: str = "jsonld"
    evidence: str | None = None


@dataclass
class Modifier:
    key: str
    item_key: str | None
    section_key: str | None
    label: str
    price_delta: float | None = None
    required: bool = False
    source: str = "dom"


@dataclass
class OfferTarget:
    """Links a promotion/signal to a baseline menu entity.

    ARCH-02: confidence + disposition encode how strong the evidence is so
    downstream consumers (scoring, review tooling) can route auto-accept
    links straight into evidence and ambiguous links into review. The
    match_method is kept for post-hoc auditing of false positives/negatives.
    """
    key: str
    scope: str  # "item" | "section" | "service_period" | "venue"
    section_key: str | None = None
    item_key: str | None = None
    service_period: str | None = None
    signal_ref: str | None = None  # seen-deals name key
    confidence: float | None = None
    disposition: str | None = None  # "auto_accept" | "review" | "discard"
    match_method: str | None = None


# ── Offer-target confidence rubric (ARCH-02) ────────────────────────────────
# Lead with the match method observed at link time — confidence follows from
# that, and disposition follows from confidence. Keeping this as data rather
# than branching keeps the rubric easy to tune from replay metrics.
_OFFER_TARGET_CONFIDENCE_BY_METHOD: dict[str, float] = {
    "path_plus_name_item": 0.95,   # full schema-path match AND item match
    "path_only_section": 0.85,     # schema-path match, section scope only
    "name_only_item": 0.65,        # name scan hit, no schema path → review
    "service_period_only": 0.55,   # inferred service period, no entity match → review
    "venue": 0.25,                 # nothing matched; venue-wide fallback → discard
}

_OFFER_TARGET_DISPOSITION_THRESHOLDS: tuple[tuple[float, str], ...] = (
    (0.85, "auto_accept"),
    (0.50, "review"),
)


def classify_offer_target_disposition(confidence: float | None) -> str:
    """Thresholded routing rule for ARCH-02."""
    if confidence is None:
        return "discard"
    for threshold, label in _OFFER_TARGET_DISPOSITION_THRESHOLDS:
        if confidence >= threshold:
            return label
    return "discard"


# ── Sidecar container ───────────────────────────────────────────────────────


@dataclass
class MenuSidecar:
    pages: dict[str, MenuPage] = field(default_factory=dict)
    sections: dict[str, MenuSection] = field(default_factory=dict)
    items: dict[str, MenuItem] = field(default_factory=dict)
    price_points: dict[str, PricePoint] = field(default_factory=dict)
    modifiers: dict[str, Modifier] = field(default_factory=dict)
    offer_targets: dict[str, OfferTarget] = field(default_factory=dict)

    # ── Mutators ────────────────────────────────────────────────────────
    def add_page(self, page: MenuPage) -> None:
        self.pages.setdefault(page.key, page)

    def add_section(self, section: MenuSection) -> None:
        if len(self.sections) >= _MAX_SECTIONS_PER_SITE:
            return
        self.sections.setdefault(section.key, section)

    def add_item(self, item: MenuItem) -> None:
        if len(self.items) >= _MAX_ITEMS_PER_SITE:
            return
        self.items.setdefault(item.key, item)

    def add_price_point(self, pp: PricePoint) -> None:
        if len(self.price_points) >= _MAX_PRICE_POINTS_PER_SITE:
            return
        self.price_points.setdefault(pp.key, pp)

    def add_modifier(self, mod: Modifier) -> None:
        if len(self.modifiers) >= _MAX_MODIFIERS_PER_SITE:
            return
        self.modifiers.setdefault(mod.key, mod)

    def add_offer_target(self, target: OfferTarget) -> None:
        if len(self.offer_targets) >= _MAX_OFFER_TARGETS_PER_SITE:
            return
        self.offer_targets.setdefault(target.key, target)

    # ── Derived metrics ─────────────────────────────────────────────────
    def course_price_baseline(self) -> dict[str, float]:
        """Median absolute price by derived course. Drives PRICE-02 / VALUE-01."""
        buckets: dict[str, list[float]] = {}
        for pp in self.price_points.values():
            if pp.price is None or pp.price <= 0:
                continue
            course = None
            if pp.item_key and pp.item_key in self.items:
                course = self.items[pp.item_key].course
            if not course and pp.section_key and pp.section_key in self.sections:
                course = self.sections[pp.section_key].course
            if not course:
                continue
            buckets.setdefault(course, []).append(pp.price)

        out: dict[str, float] = {}
        for course, prices in buckets.items():
            if len(prices) >= 2:
                out[course] = round(float(median(prices)), 2)
        return out

    def section_price_baseline(self) -> dict[str, float]:
        """Median price per section key — useful for section-scoped offers."""
        by_section: dict[str, list[float]] = {}
        for pp in self.price_points.values():
            if pp.price is None or pp.price <= 0:
                continue
            if pp.section_key:
                by_section.setdefault(pp.section_key, []).append(pp.price)
            elif pp.item_key and pp.item_key in self.items:
                sk = self.items[pp.item_key].section_key
                if sk:
                    by_section.setdefault(sk, []).append(pp.price)
        return {sk: round(float(median(v)), 2) for sk, v in by_section.items() if len(v) >= 2}

    def value_profile(self) -> dict[str, Any]:
        """VALUE-01: site-level value profile derived from sidecar evidence.

        Summarizes what the restaurant normally charges by category so
        downstream scoring and UX can answer "is this deal strong?" without
        re-computing from raw price points.
        """
        course_prices: dict[str, list[float]] = {}
        section_by_course: dict[str, set[str]] = {}
        for pp in self.price_points.values():
            if pp.price is None or pp.price <= 0:
                continue
            course = None
            if pp.item_key and pp.item_key in self.items:
                course = self.items[pp.item_key].course
            if not course and pp.section_key and pp.section_key in self.sections:
                course = self.sections[pp.section_key].course
            if not course:
                continue
            course_prices.setdefault(course, []).append(pp.price)
            if pp.section_key:
                section_by_course.setdefault(course, set()).add(pp.section_key)

        courses: dict[str, dict[str, Any]] = {}
        for course, prices in course_prices.items():
            if len(prices) < 2:
                continue
            courses[course] = {
                "sample_size": len(prices),
                "median": round(float(median(prices)), 2),
                "min": round(min(prices), 2),
                "max": round(max(prices), 2),
                "section_count": len(section_by_course.get(course, set())),
            }

        service_periods = sorted({
            s.service_period for s in self.sections.values() if s.service_period
        })
        offer_target_scopes: dict[str, int] = {}
        for ot in self.offer_targets.values():
            offer_target_scopes[ot.scope] = offer_target_scopes.get(ot.scope, 0) + 1

        return {
            "courses": courses,
            "service_periods": service_periods,
            "offer_target_scopes": offer_target_scopes,
            "has_structured_menu": bool(self.price_points),
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "pages": [_asdict(p) for p in self.pages.values()],
            "sections": [_asdict(s) for s in self.sections.values()],
            "items": [_asdict(i) for i in self.items.values()],
            "price_points": [_asdict(pp) for pp in self.price_points.values()],
            "modifiers": [_asdict(m) for m in self.modifiers.values()],
            "offer_targets": [_asdict(t) for t in self.offer_targets.values()],
            "baselines": {
                "course_price_median": self.course_price_baseline(),
                "section_price_median": self.section_price_baseline(),
            },
            "value_profile": self.value_profile(),
            "counts": {
                "pages": len(self.pages),
                "sections": len(self.sections),
                "items": len(self.items),
                "price_points": len(self.price_points),
                "modifiers": len(self.modifiers),
                "offer_targets": len(self.offer_targets),
            },
        }


def _asdict(obj: Any) -> dict[str, Any]:
    return {k: v for k, v in obj.__dict__.items()}


# ── Keys ────────────────────────────────────────────────────────────────────


def _hash_key(prefix: str, *parts: str) -> str:
    h = hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{h}"


def _domain(url: str) -> str:
    try:
        return (urlparse(url).netloc or "").lower()
    except Exception:
        return ""


def _page_key(url: str) -> str:
    return _hash_key("p", url)


def _section_key(domain: str, path: list[str]) -> str:
    return _hash_key("s", domain, "/".join(p.lower() for p in path if p))


def _item_key(section_key: str, name: str, variant: str | None = None) -> str:
    return _hash_key("i", section_key, name.lower(), variant or "")


def _price_point_key(item_key: str | None, section_key: str | None, price: float, variant: str | None) -> str:
    return _hash_key("pp", item_key or "", section_key or "", f"{price:.2f}", variant or "")


def _modifier_key(item_key: str | None, section_key: str | None, label: str) -> str:
    return _hash_key("mod", item_key or "", section_key or "", label.lower())


def _offer_target_key(scope: str, section_key: str | None, item_key: str | None, signal_ref: str | None) -> str:
    return _hash_key("ot", scope, section_key or "", item_key or "", signal_ref or "")


# ── Course / service period tagging ─────────────────────────────────────────


def classify_service_period(*texts: str | None) -> str | None:
    joined = " ".join(t for t in texts if t).strip()
    if not joined:
        return None
    for pattern, label in _SERVICE_PERIOD_RULES:
        if pattern.search(joined):
            return label
    return None


def classify_course(*texts: str | None) -> str | None:
    joined = " ".join(t for t in texts if t).strip()
    if not joined:
        return None
    for pattern, label in _COURSE_RULES:
        if pattern.search(joined):
            return label
    return None


def _dedupe_tags(tags: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for tag in tags:
        cleaned = (tag or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _canonicalize_dietary_token(token: str | None) -> str | None:
    if not token:
        return None
    token = token.rsplit("/", 1)[-1].rsplit(":", 1)[-1]
    cleaned = re.sub(r"[^a-z]+", "", token.casefold())
    if not cleaned:
        return None
    return _DIETARY_TOKEN_MAP.get(cleaned)


def _extract_inline_dietary_tags_from_text(value: Any) -> list[str]:
    if not isinstance(value, str) or not value:
        return []

    text = unescape(value)
    tags: list[str] = []
    for match in _INLINE_DIETARY_BLOCK_RE.finditer(text):
        for raw in (match.group(1), match.group(2)):
            tag = _canonicalize_dietary_token(raw)
            if tag:
                tags.append(tag)

    cleaned = re.sub(r"\s+", " ", _INLINE_HTML_TAG_RE.sub(" ", text)).strip()
    for pattern, label in _TEXTUAL_DIETARY_PATTERNS:
        if pattern.search(cleaned):
            tags.append(label)
    return _dedupe_tags(tags)


def _looks_like_variant_label(value: str | None) -> bool:
    if not value:
        return False
    return _SIZE_LABEL_RE.match(value.strip()) is not None


def _normalize_variant_label(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip(" .-–—")
    if not cleaned or not _looks_like_variant_label(cleaned):
        return None
    return cleaned


def _price_point_page_matches(sidecar: MenuSidecar, pp: PricePoint, page_key: str) -> bool:
    section_key = pp.section_key
    if not section_key and pp.item_key and pp.item_key in sidecar.items:
        section_key = sidecar.items[pp.item_key].section_key
    if not section_key or section_key not in sidecar.sections:
        return False
    return sidecar.sections[section_key].page_key == page_key


def _normalize_jsonld_page_prices(sidecar: MenuSidecar, *, page_key: str) -> None:
    page_price_keys = [
        key for key, pp in list(sidecar.price_points.items())
        if pp.source == "jsonld" and _price_point_page_matches(sidecar, pp, page_key)
    ]
    if not page_price_keys:
        return

    positive_prices: list[float] = []
    for key in page_price_keys:
        pp = sidecar.price_points.get(key)
        if pp is None:
            continue
        if pp.price is None or pp.price <= 0:
            sidecar.price_points.pop(key, None)
            continue
        positive_prices.append(pp.price)

    if len(positive_prices) < 6:
        return

    subunit_prices = [price for price in positive_prices if 0 < price < 1]
    if not subunit_prices:
        return
    if max(positive_prices) > 1:
        return
    if len(subunit_prices) < max(4, int(len(positive_prices) * 0.6)):
        return

    replacements: dict[str, PricePoint] = {}
    for key in list(sidecar.price_points.keys()):
        pp = sidecar.price_points.get(key)
        if pp is None or pp.source != "jsonld" or not _price_point_page_matches(sidecar, pp, page_key):
            continue
        if pp.price is None or pp.price <= 0:
            sidecar.price_points.pop(key, None)
            continue
        sidecar.price_points.pop(key, None)
        pp.price = round(pp.price * 100.0, 2)
        pp.key = _price_point_key(pp.item_key, pp.section_key, pp.price, pp.variant)
        replacements.setdefault(pp.key, pp)

    sidecar.price_points.update(replacements)


# ── JSON-LD builder ─────────────────────────────────────────────────────────


def _clean(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        return str(value)
    if not isinstance(value, str):
        return ""
    text = unescape(value)
    text = _INLINE_DIETARY_BLOCK_RE.sub(" ", text)
    text = _INLINE_HTML_TAG_RE.sub(" ", text)
    return re.sub(r"\s+", " ", text).strip()


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _jsonld_types(node: dict[str, Any]) -> set[str]:
    raw = node.get("@type")
    if isinstance(raw, str):
        return {raw}
    if isinstance(raw, list):
        return {x for x in raw if isinstance(x, str)}
    return set()


def _collect_nodes(payload: Any) -> list[dict[str, Any]]:
    items = payload if isinstance(payload, list) else [payload]
    nodes: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        graph = item.get("@graph")
        if isinstance(graph, list):
            nodes.extend(n for n in graph if isinstance(n, dict))
            continue
        nodes.append(item)
    return nodes


def _build_id_index(nodes: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    queue: deque[Any] = deque(nodes)
    seen: set[int] = set()
    while queue:
        val = queue.popleft()
        if isinstance(val, list):
            queue.extend(val)
            continue
        if not isinstance(val, dict):
            continue
        oid = id(val)
        if oid in seen:
            continue
        seen.add(oid)
        nid = val.get("@id")
        if isinstance(nid, str) and nid and nid not in index:
            index[nid] = val
        for child in val.values():
            if isinstance(child, (dict, list)):
                queue.append(child)
    return index


def _resolve(value: Any, idx: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if isinstance(value, str):
        return idx.get(value)
    if not isinstance(value, dict):
        return None
    ref_id = value.get("@id")
    if isinstance(ref_id, str) and ref_id and len(value) == 1 and ref_id in idx:
        return idx[ref_id]
    return value


def _child_nodes(node: dict[str, Any], key: str, idx: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for val in _as_list(node.get(key)):
        resolved = _resolve(val, idx)
        if isinstance(resolved, dict):
            out.append(resolved)
    return out


def _parse_price(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    cleaned = re.sub(r"[^0-9.]+", "", value.strip())
    if not cleaned or cleaned.count(".") > 1:
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_price_from_offer(offer: dict[str, Any], idx: dict[str, dict[str, Any]]) -> tuple[float | None, str | None]:
    price = _parse_price(offer.get("price"))
    if price is None:
        price = _parse_price(offer.get("minPrice"))
    if price is None:
        price = _parse_price(offer.get("maxPrice"))
    currency = _clean(offer.get("priceCurrency")) or None
    for spec in _child_nodes(offer, "priceSpecification", idx):
        if price is None:
            p, c = _extract_price_from_offer(spec, idx)
            if p is not None:
                price = p
            if currency is None and c:
                currency = c
    return price, currency


def _extract_calories(node: dict[str, Any]) -> int | None:
    nutrition = node.get("nutrition")
    if not isinstance(nutrition, dict):
        return None
    raw = nutrition.get("calories")
    if raw is None:
        return None
    try:
        val = int(re.sub(r"[^\d]", "", str(raw)) or "0")
    except ValueError:
        return None
    if 20 <= val <= 6000:
        return val
    return None


def _extract_dietary_tags(item: dict[str, Any]) -> list[str]:
    tags: list[str] = []
    for raw in _as_list(item.get("suitableForDiet")):
        cleaned = _clean(raw)
        if cleaned:
            tags.append(cleaned.split("/")[-1])
    tags.extend(_extract_inline_dietary_tags_from_text(item.get("name")))
    tags.extend(_extract_inline_dietary_tags_from_text(item.get("description")))
    return _dedupe_tags(tags)


def _traverse_menu(
    node: dict[str, Any],
    *,
    parent_section_key: str | None,
    path: list[str],
    domain: str,
    page_key: str,
    sidecar: MenuSidecar,
    idx: dict[str, dict[str, Any]],
    lineage: set[str],
) -> None:
    resolved = _resolve(node, idx)
    if not isinstance(resolved, dict):
        return

    types = _jsonld_types(resolved)
    lineage_key = resolved.get("@id") or f"anon:{id(resolved)}"
    if lineage_key in lineage:
        return
    lineage = lineage | {lineage_key}

    # FoodEstablishment/Restaurant: descend into hasMenu / makesOffer; do NOT
    # create a menu section for the establishment itself.
    if types.intersection({"Restaurant", "FoodEstablishment"}):
        for menu in _child_nodes(resolved, "hasMenu", idx):
            _traverse_menu(
                menu,
                parent_section_key=None,
                path=path,
                domain=domain,
                page_key=page_key,
                sidecar=sidecar,
                idx=idx,
                lineage=lineage,
            )
        return

    # Menu or MenuSection -> record a section.
    if types.intersection(_SCHEMA_MENU_TYPES):
        name = _clean(resolved.get("name")) or "(unnamed)"
        new_path = [*path, name]
        skey = _section_key(domain, new_path)
        service_period = classify_service_period(name, _clean(resolved.get("description")))
        course = classify_course(name)
        sidecar.add_section(MenuSection(
            key=skey,
            page_key=page_key,
            name=name,
            parent_key=parent_section_key,
            path=new_path,
            service_period=service_period,
            course=course,
            source="jsonld",
        ))

        # Any section-level Offer maps to a section-scoped price point + offer target.
        for offer in _child_nodes(resolved, "offers", idx):
            price, currency = _extract_price_from_offer(offer, idx)
            if price is not None:
                pp_key = _price_point_key(None, skey, price, None)
                sidecar.add_price_point(PricePoint(
                    key=pp_key,
                    item_key=None,
                    section_key=skey,
                    price=price,
                    currency=currency,
                    variant=None,
                    confidence=0.85,
                    source="jsonld",
                    evidence=_clip(_clean(offer.get("name")) or _clean(offer.get("description"))),
                ))

        # Direct menu items.
        for mi in _child_nodes(resolved, "hasMenuItem", idx):
            _record_menu_item(
                mi,
                section_key=skey,
                domain=domain,
                page_key=page_key,
                idx=idx,
                sidecar=sidecar,
                inherited_currency=None,
            )

        # Nested sections.
        for sub in _child_nodes(resolved, "hasMenuSection", idx):
            _traverse_menu(
                sub,
                parent_section_key=skey,
                path=new_path,
                domain=domain,
                page_key=page_key,
                sidecar=sidecar,
                idx=idx,
                lineage=lineage,
            )
        return

    # Plain MenuItem at top-level (rare but we accept it).
    if "MenuItem" in types:
        # Place under an implicit unknown section so the item is still reachable.
        skey = _section_key(domain, [*path, "(unsectioned)"])
        sidecar.add_section(MenuSection(
            key=skey,
            page_key=page_key,
            name="(unsectioned)",
            parent_key=parent_section_key,
            path=[*path, "(unsectioned)"],
            source="jsonld",
        ))
        _record_menu_item(
            resolved,
            section_key=skey,
            domain=domain,
            page_key=page_key,
            idx=idx,
            sidecar=sidecar,
            inherited_currency=None,
        )


def _record_menu_item(
    item: dict[str, Any],
    *,
    section_key: str,
    domain: str,
    page_key: str,
    idx: dict[str, dict[str, Any]],
    sidecar: MenuSidecar,
    inherited_currency: str | None,
) -> None:
    name = _clean(item.get("name"))
    if not name:
        return
    desc = _clean(item.get("description")) or None
    section = sidecar.sections.get(section_key)
    course = classify_course(name, desc, section.name if section else None)
    calories = _extract_calories(item)
    ikey = _item_key(section_key, name)
    sidecar.add_item(MenuItem(
        key=ikey,
        section_key=section_key,
        name=name,
        description=_clip(desc) if desc else None,
        course=course,
        calories=calories,
        dietary_tags=_extract_dietary_tags(item),
        source="jsonld",
    ))

    # Offers -> price points.
    offers = _child_nodes(item, "offers", idx)
    if not offers:
        return
    for offer in offers:
        price, currency = _extract_price_from_offer(offer, idx)
        if price is None:
            continue
        variant = _clean(offer.get("name")) or _normalize_variant_label(_clean(offer.get("description")))
        pp_key = _price_point_key(ikey, section_key, price, variant)
        sidecar.add_price_point(PricePoint(
            key=pp_key,
            item_key=ikey,
            section_key=section_key,
            price=price,
            currency=currency or inherited_currency,
            variant=variant,
            confidence=0.95,
            source="jsonld",
            evidence=_clip(_clean(offer.get("description")) or name),
        ))

    # menuAddOn / addOn -> modifiers.
    for addon_key in ("menuAddOn", "addOn"):
        for mod in _child_nodes(item, addon_key, idx):
            mod_name = _clean(mod.get("name"))
            if not mod_name:
                continue
            mod_price, _cur = _extract_price_from_offer(mod, idx) if _jsonld_types(mod) else (None, None)
            sidecar.add_modifier(Modifier(
                key=_modifier_key(ikey, section_key, mod_name),
                item_key=ikey,
                section_key=section_key,
                label=mod_name,
                price_delta=mod_price,
                required=False,
                source="jsonld",
            ))


def ingest_jsonld_payload(
    payload: Any,
    *,
    page_url: str,
    sidecar: MenuSidecar,
) -> None:
    """Walk schema.org nodes into the sidecar. Safe on arbitrary payloads."""
    nodes = _collect_nodes(payload)
    if not nodes:
        return
    idx = _build_id_index(nodes)
    page_key = _page_key(page_url)
    sidecar.add_page(MenuPage(key=page_key, url=page_url, source="jsonld"))
    domain = _domain(page_url)
    for node in nodes:
        _traverse_menu(
            node,
            parent_section_key=None,
            path=[],
            domain=domain,
            page_key=page_key,
            sidecar=sidecar,
            idx=idx,
            lineage=set(),
        )
    _normalize_jsonld_page_prices(sidecar, page_key=page_key)


def ingest_jsonld_from_html(html: str, *, page_url: str, sidecar: MenuSidecar) -> None:
    """Extract and ingest all JSON-LD scripts found in the HTML."""
    for match in _JSONLD_SCRIPT_RE.finditer(html):
        raw = match.group(1).strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        ingest_jsonld_payload(payload, page_url=page_url, sidecar=sidecar)


# ── DOM fallback builder ────────────────────────────────────────────────────

_MENU_HEADING_TAGS = ("h1", "h2", "h3", "h4")
_MENU_HEADING_HINT_RE = re.compile(
    r"\b(menu|appetizer|entr[eé]e|starter|special|dessert|drink|cocktail|happy\s*hour|lunch|dinner|brunch|side|kids)",
    re.IGNORECASE,
)


def ingest_dom_fallback(soup: BeautifulSoup, *, page_url: str, sidecar: MenuSidecar) -> None:
    """Heuristic DOM-only extraction for pages lacking useful JSON-LD.

    Pulls heading -> following-list/table item+price pairs, scoped to blocks
    whose heading looks menu-like. Bounded to avoid contaminating the sidecar
    on non-menu pages.
    """
    if not isinstance(soup, BeautifulSoup) and not hasattr(soup, "find_all"):
        return

    page_key = _page_key(page_url)
    domain = _domain(page_url)
    sidecar.add_page(MenuPage(key=page_key, url=page_url, source="dom"))
    section_count = 0

    for heading in soup.find_all(_MENU_HEADING_TAGS):
        if not isinstance(heading, Tag):
            continue
        heading_text = heading.get_text(" ", strip=True)
        if not heading_text or len(heading_text) > 80:
            continue
        if not _MENU_HEADING_HINT_RE.search(heading_text):
            continue
        if _PROMOTIONAL_DOM_SECTION_RE.search(heading_text) and not _MEAL_PERIOD_SECTION_RE.search(heading_text):
            continue

        items_container = _next_items_container(heading)
        if items_container is None:
            continue

        pairs = _extract_pairs_from_container(items_container, section_name=heading_text)
        if not pairs:
            continue

        section_count += 1
        if section_count > _MAX_SECTIONS_PER_SITE:
            return

        skey = _section_key(domain, [heading_text])
        service_period = classify_service_period(heading_text)
        course = classify_course(heading_text)
        sidecar.add_section(MenuSection(
            key=skey,
            page_key=page_key,
            name=heading_text,
            path=[heading_text],
            service_period=service_period,
            course=course,
            source="dom",
        ))

        for name, price, evidence, variant in pairs:
            ikey = _item_key(skey, name)
            sidecar.add_item(MenuItem(
                key=ikey,
                section_key=skey,
                name=name,
                description=None,
                course=course or classify_course(name),
                source="dom",
            ))
            sidecar.add_price_point(PricePoint(
                key=_price_point_key(ikey, skey, price, variant),
                item_key=ikey,
                section_key=skey,
                price=price,
                currency="USD",
                variant=variant,
                confidence=0.55,
                source="dom",
                evidence=_clip(evidence),
            ))

        # Modifiers within the same container.
        container_text = items_container.get_text(" ", strip=True)
        for mod_match in _DOM_MODIFIER_RE.finditer(container_text):
            mod_price = _parse_price(mod_match.group(1))
            label = container_text[max(0, mod_match.start() - 30): mod_match.start()].strip() or "modifier"
            sidecar.add_modifier(Modifier(
                key=_modifier_key(None, skey, label[:50]),
                item_key=None,
                section_key=skey,
                label=label[:50],
                price_delta=mod_price,
                required=False,
                source="dom",
            ))


def _next_items_container(heading: Tag) -> Tag | None:
    """Find the nearest following sibling container that looks like a list/table."""
    sibling = heading.find_next_sibling()
    hops = 0
    while sibling is not None and hops < 4:
        if isinstance(sibling, Tag):
            if sibling.name in ("ul", "ol", "table", "div", "section"):
                if sibling.find(["li", "tr"]) is not None:
                    return sibling
        sibling = sibling.find_next_sibling()
        hops += 1
    return None


def _extract_pairs_from_container(container: Tag, *, section_name: str | None = None) -> list[tuple[str, float, str, str | None]]:
    """Pull (name, price, evidence, variant) tuples from li/tr rows in the container."""
    pairs: list[tuple[str, float, str, str | None]] = []
    rows = container.find_all(["li", "tr"])
    for row in rows:
        text = row.get_text(" ", strip=True)
        if not text or len(text) < 4 or len(text) > 250:
            continue
        if _PROMOTIONAL_DOM_ROW_RE.search(text):
            continue
        price_match = _DOM_PRICE_RE.search(text)
        if not price_match:
            continue
        price = _parse_price(price_match.group(0))
        if price is None or price <= 0 or price > 500:
            continue
        name = _DOM_PRICE_RE.sub("", text).strip(" -–—.·•\t")
        if not name or len(name) < 2 or len(name) > 120:
            continue
        variant = _normalize_variant_label(name)
        if variant and section_name and section_name not in {"(unnamed)", "(unsectioned)"}:
            name = section_name
        pairs.append((name, price, text, variant))
        if len(pairs) >= 40:
            break
    return pairs


# ── PDF table ingest (PDF-02) ───────────────────────────────────────────────


def ingest_pdf_tables(
    tables: list[list[list[str | None]]],
    *,
    page_url: str,
    section_hint: str | None = None,
    sidecar: MenuSidecar,
) -> None:
    """Ingest pdfplumber-style tables ([[row, [cells]]) into the sidecar.

    PDF-02: layout-aware extraction. We expect two-column patterns (name, price)
    or multi-column patterns with a recognizable price column. Tables that
    don't yield at least 2 valid (name, price) pairs are discarded — they are
    almost always nutritional footers, allergy grids, or hours-of-operation.
    """
    if not tables:
        return

    page_key = _page_key(page_url)
    sidecar.add_page(MenuPage(key=page_key, url=page_url, source="pdf_table"))
    domain = _domain(page_url)

    for t_idx, table in enumerate(tables):
        rows = _normalize_table_rows(table)
        if len(rows) < 2:
            continue
        price_col = _detect_price_column(rows)
        if price_col is None:
            continue
        name_col = _detect_name_column(rows, price_col)
        if name_col is None:
            continue

        pairs: list[tuple[str, float, str]] = []
        for row in rows:
            if max(price_col, name_col) >= len(row):
                continue
            raw_price = row[price_col] or ""
            raw_name = row[name_col] or ""
            price = _parse_price(raw_price)
            if price is None or price <= 0 or price > 500:
                continue
            name = re.sub(r"\s+", " ", raw_name).strip(" -–—.·•\t:")
            if not name or len(name) < 2 or len(name) > 120:
                continue
            pairs.append((name, price, " | ".join(c or "" for c in row)[:_MAX_EVIDENCE_LEN]))
        if len(pairs) < 2:
            continue

        section_name = section_hint or f"PDF table {t_idx + 1}"
        skey = _section_key(domain, [section_name])
        sidecar.add_section(MenuSection(
            key=skey,
            page_key=page_key,
            name=section_name,
            path=[section_name],
            service_period=classify_service_period(section_name),
            course=classify_course(section_name),
            source="pdf_table",
        ))
        for name, price, evidence in pairs:
            ikey = _item_key(skey, name)
            sidecar.add_item(MenuItem(
                key=ikey,
                section_key=skey,
                name=name,
                description=None,
                course=classify_course(name),
                source="pdf_table",
            ))
            sidecar.add_price_point(PricePoint(
                key=_price_point_key(ikey, skey, price, None),
                item_key=ikey,
                section_key=skey,
                price=price,
                currency="USD",
                variant=None,
                confidence=0.75,
                source="pdf_table",
                evidence=_clip(evidence),
            ))


def _normalize_table_rows(table: list[list[str | None]]) -> list[list[str]]:
    out: list[list[str]] = []
    for row in table or []:
        if not row:
            continue
        cleaned = [(cell or "").strip() for cell in row]
        if any(cleaned):
            out.append(cleaned)
    return out


_PRICE_CELL_RE = re.compile(r"^\s*\$?\s*\d{1,3}(?:\.\d{1,2})\s*\$?\s*$")


def _looks_like_price_cell(cell: str) -> bool:
    """A cell looks like a price if it's a dollar-marked or decimal-numeric value."""
    if not cell:
        return False
    s = cell.strip()
    if "$" in s:
        return _parse_price(s) is not None
    return bool(_PRICE_CELL_RE.match(s))


def _detect_price_column(rows: list[list[str]]) -> int | None:
    """Pick the column with the highest hit rate on a dollar-ish value."""
    if not rows:
        return None
    col_count = max(len(r) for r in rows)
    best_col = None
    best_hits = 0
    for col in range(col_count):
        hits = 0
        for row in rows:
            if col >= len(row):
                continue
            if _looks_like_price_cell(row[col]):
                hits += 1
        if hits > best_hits and hits >= max(2, len(rows) // 3):
            best_hits = hits
            best_col = col
    return best_col


def _detect_name_column(rows: list[list[str]], price_col: int) -> int | None:
    """Pick the column most likely to carry the item name (longest text, non-price)."""
    if not rows:
        return None
    col_count = max(len(r) for r in rows)
    best_col = None
    best_score = 0.0
    for col in range(col_count):
        if col == price_col:
            continue
        total_len = 0
        non_empty = 0
        for row in rows:
            if col >= len(row):
                continue
            cell = row[col]
            if not cell:
                continue
            if _parse_price(cell) is not None:
                continue
            non_empty += 1
            total_len += min(len(cell), 80)
        if non_empty == 0:
            continue
        avg = total_len / non_empty
        if avg > best_score and avg >= 3:
            best_score = avg
            best_col = col
    return best_col


# ── Signal linking (TARGET-01 groundwork) ───────────────────────────────────


def link_signal_to_target(
    sidecar: MenuSidecar,
    *,
    signal_ref: str,
    page_url: str,
    context_path: Iterable[str] | None = None,
    primary_name: str | None = None,
    service_period: str | None = None,
) -> dict[str, Any] | None:
    """Best-effort link from a DealSignal to a sidecar entity.

    Returns a dict suitable for stashing on signal.metadata["offer_target"],
    or None if no linkage could be found. Mutates the sidecar by adding an
    OfferTarget record so the linkage is replay-visible.
    """
    domain = _domain(page_url)
    path_list = [p for p in (context_path or []) if p]

    target_section_key: str | None = None
    target_item_key: str | None = None
    scope = "venue"
    match_method: str | None = None

    if path_list:
        candidate = _section_key(domain, path_list)
        if candidate in sidecar.sections:
            target_section_key = candidate
            scope = "section"
            match_method = "path_only_section"

    if target_section_key and primary_name:
        candidate_item = _item_key(target_section_key, primary_name)
        if candidate_item in sidecar.items:
            target_item_key = candidate_item
            scope = "item"
            match_method = "path_plus_name_item"

    # Fallback: scan items by name when no section path was provided.
    if target_item_key is None and primary_name:
        lowered = primary_name.lower()
        for item in sidecar.items.values():
            if item.name.lower() == lowered:
                target_item_key = item.key
                target_section_key = item.section_key
                scope = "item"
                match_method = "name_only_item"
                break

    # Fallback: service period inferred from context path.
    if target_section_key is None and service_period is None and path_list:
        service_period = classify_service_period(*path_list)

    if target_section_key is None and target_item_key is None and service_period:
        scope = "service_period"
        match_method = "service_period_only"

    if target_section_key is None and target_item_key is None and scope == "venue":
        # Only record venue-wide targets when they carry meaningful evidence.
        if not primary_name and not path_list and not service_period:
            return None
        match_method = "venue"

    confidence = _OFFER_TARGET_CONFIDENCE_BY_METHOD.get(match_method or "venue", 0.25)
    disposition = classify_offer_target_disposition(confidence)

    ot_key = _offer_target_key(scope, target_section_key, target_item_key, signal_ref)
    sidecar.add_offer_target(OfferTarget(
        key=ot_key,
        scope=scope,
        section_key=target_section_key,
        item_key=target_item_key,
        service_period=service_period,
        signal_ref=signal_ref,
        confidence=confidence,
        disposition=disposition,
        match_method=match_method,
    ))
    return {
        "key": ot_key,
        "scope": scope,
        "section_key": target_section_key,
        "item_key": target_item_key,
        "service_period": service_period,
        "confidence": confidence,
        "disposition": disposition,
        "match_method": match_method,
    }


# ── Utilities ───────────────────────────────────────────────────────────────


def _clip(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) <= _MAX_EVIDENCE_LEN:
        return value
    return value[:_MAX_EVIDENCE_LEN].rstrip() + "…"
