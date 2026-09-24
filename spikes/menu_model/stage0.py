"""Stage [0]: deterministic structured-data parse (the baseline the models must beat).

Two generic sources, no per-site code:

- **schema.org JSON-LD** — ``Menu`` → ``hasMenuSection`` → ``hasMenuItem`` with
  ``offers.price`` (or ``offers`` lists / ``AggregateOffer.lowPrice``).
- **embedded platform state** — any ``<script>`` whose body is a JSON object
  (``application/json`` payloads, ``window.X = {...}`` bootstraps). A generic
  walker collects dicts that carry a name-like string and a price reachable one
  level down (``price``, ``priceInfo.price``, ``amount``). This is how a site
  builder (e.g. Wix Restaurants) ships its menu to the browser.

``platform_of`` is a fingerprint only, reported so the results can say which
platforms a known-platform parser *would* have to cover; nothing here parses a
platform's DOM.
"""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation

from spikes.menu_model.segment import json_ld_objects

_SCRIPT = re.compile(r"<script([^>]*)>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_ASSIGN = re.compile(r"^\s*(?:window\.)?[\w.$]+\s*=\s*(\{.*\})\s*;?\s*$", re.DOTALL)
_NAME_KEYS = ("name", "title", "itemName", "displayName")
_PRICE_KEYS = ("price", "amount", "basePrice", "displayPrice", "lowPrice")
_PRICE_PARENTS = ("priceInfo", "offers", "pricing", "priceMoney", "price")

PLATFORMS: tuple[tuple[str, str], ...] = (
    ("toast", r"toasttab\.com"),
    ("square", r"square\.site|squareup\.com|Square Online"),
    ("clover", r"clover\.com"),
    ("bentobox", r"getbento\.com|bentobox"),
    ("spothopper", r"spothopper"),
    ("singleplatform", r"singleplatform"),
    ("popmenu", r"popmenu"),
    ("wix", r"wix\.com Website Builder|static\.wixstatic\.com"),
    ("squarespace", r"squarespace"),
    ("wordpress", r"wp-content|WordPress"),
    ("olo", r"olo\.com"),
    ("chownow", r"chownow"),
    ("framer", r"Framer "),
    ("next_js", r"__NEXT_DATA__|self\.__next_f"),
    ("nuxt", r"window\.__NUXT__"),
)


def _amount(value: object) -> str | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        text = str(value)
    elif isinstance(value, str):
        text = value.strip().lstrip("$").replace(",", "")
    else:
        return None
    try:
        amount = Decimal(text)
    except InvalidOperation:
        return None
    return f"{amount:.2f}" if 0 < amount < 1000 else None  # noqa: PLR2004


def _types(obj: dict[str, object]) -> set[str]:
    t = obj.get("@type")
    return {t} if isinstance(t, str) else {str(x) for x in t} if isinstance(t, list) else set()


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else [] if value is None else [value]


def _offer_prices(offers: object) -> list[str]:
    out = []
    for offer in _as_list(offers):
        if isinstance(offer, dict):
            price = _amount(offer.get("price")) or _amount(offer.get("lowPrice"))
            if price:
                out.append(price)
    return out


def _walk_jsonld(obj: object, section: str | None, rows: list[dict[str, object]]) -> None:
    if isinstance(obj, list):
        for v in obj:
            _walk_jsonld(v, section, rows)
        return
    if not isinstance(obj, dict):
        return
    types = _types(obj)
    if "MenuItem" in types:
        rows.append(
            {
                "section": section,
                "name": str(obj.get("name") or "").strip(),
                "description": obj.get("description") or None,
                "prices": _offer_prices(obj.get("offers")),
            }
        )
        return
    if "MenuSection" in types:
        section = str(obj.get("name") or "").strip() or section
    for key, value in obj.items():
        if key != "offers":
            _walk_jsonld(value, section, rows)


def jsonld_menu_items(html: str) -> list[dict[str, object]]:
    """Items from any schema.org ``MenuItem`` in the page's JSON-LD (with or without price)."""
    rows: list[dict[str, object]] = []
    for obj in json_ld_objects(html):
        _walk_jsonld(obj, None, rows)
    return [r for r in rows if r["name"]]


def _embedded_json(html: str) -> list[object]:
    out: list[object] = []
    for m in _SCRIPT.finditer(html):
        attrs, body = m.group(1).lower(), m.group(2).strip()
        if "ld+json" in attrs or len(body) < 200:  # noqa: PLR2004
            continue
        candidate = body if body.startswith("{") else None
        if candidate is None:
            assign = _ASSIGN.match(body)
            candidate = assign.group(1) if assign else None
        if candidate is None:
            continue
        try:
            out.append(json.loads(candidate))
        except ValueError:
            continue
    return out


def _price_near(obj: dict[str, object]) -> str | None:
    for key in _PRICE_KEYS:
        price = _amount(obj.get(key))
        if price:
            return price
    for parent in _PRICE_PARENTS:
        child = obj.get(parent)
        for c in _as_list(child):
            if isinstance(c, dict):
                for key in _PRICE_KEYS:
                    price = _amount(c.get(key))
                    if price:
                        return price
    return None


def _walk_state(obj: object, rows: list[dict[str, object]], depth: int = 0) -> None:
    if depth > 40:  # noqa: PLR2004
        return
    if isinstance(obj, list):
        for v in obj:
            _walk_state(v, rows, depth + 1)
        return
    if not isinstance(obj, dict):
        return
    name = next(
        (obj[k] for k in _NAME_KEYS if isinstance(obj.get(k), str) and obj[k].strip()), None
    )
    price = _price_near(obj) if name else None
    if name and price:
        rows.append(
            {"section": None, "name": str(name).strip(), "description": None, "prices": [price]}
        )
    for value in obj.values():
        _walk_state(value, rows, depth + 1)


def embedded_state_items(html: str) -> list[dict[str, object]]:
    """Priced (name, price) dicts found in embedded JSON app state, deduplicated."""
    rows: list[dict[str, object]] = []
    for obj in _embedded_json(html):
        _walk_state(obj, rows)
    seen: set[tuple[str, str]] = set()
    out = []
    for r in rows:
        key = (str(r["name"]).lower(), str(r["prices"]))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def platform_of(html: str, url: str) -> list[str]:
    hay = f"{url}\n{html}"
    return [name for name, pat in PLATFORMS if re.search(pat, hay, re.IGNORECASE)]
