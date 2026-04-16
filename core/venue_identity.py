from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher
from typing import Callable, Sequence, TypeVar
from urllib.parse import urlparse

from core.normalizer import make_fingerprint

T = TypeVar("T")

_ADDRESS_UNIT_RE = re.compile(
    r",?\s*(?:suite|ste|unit|apt|#|building|bldg)\s*[a-z0-9-]+",
    re.IGNORECASE,
)
_ADDRESS_ZIP_RE = re.compile(r"\b\d{5}(?:-\d{4})?\b")
_ADDRESS_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")

_ADDRESS_PHRASE_REPLACEMENTS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"\branch\s+road\b", re.IGNORECASE), "rr"),
    (re.compile(r"\bcounty\s+road\b", re.IGNORECASE), "cr"),
    (re.compile(r"\bstate\s+highway\b", re.IGNORECASE), "sh"),
)

_ADDRESS_TOKEN_MAP = {
    "street": "st",
    "st.": "st",
    "avenue": "ave",
    "ave.": "ave",
    "boulevard": "blvd",
    "blvd.": "blvd",
    "drive": "dr",
    "dr.": "dr",
    "lane": "ln",
    "ln.": "ln",
    "road": "rd",
    "rd.": "rd",
    "circle": "cir",
    "cir.": "cir",
    "parkway": "pkwy",
    "pkwy.": "pkwy",
    "highway": "hwy",
    "hwy.": "hwy",
    "texas": "tx",
}

_NAME_STOPWORDS = frozenset(
    {
        "and",
        "at",
        "bar",
        "barbecue",
        "bbq",
        "bistro",
        "brewery",
        "burger",
        "burgers",
        "cafe",
        "cantina",
        "chinese",
        "co",
        "coffee",
        "company",
        "deli",
        "diner",
        "downtown",
        "east",
        "eatery",
        "food",
        "foods",
        "grill",
        "house",
        "inc",
        "inn",
        "italian",
        "kitchen",
        "llc",
        "lounge",
        "mall",
        "mexican",
        "north",
        "n",
        "of",
        "pizzeria",
        "pizza",
        "pub",
        "restaurant",
        "restaurants",
        "seafood",
        "shop",
        "south",
        "s",
        "steakhouse",
        "sushi",
        "taco",
        "tacos",
        "tavern",
        "tea",
        "texas",
        "thai",
        "the",
        "tx",
        "west",
        "w",
    }
)

_UNIT_HINT_RE = re.compile(r"\b(?:suite|ste|unit|apt|#|building|bldg)\b", re.IGNORECASE)


def normalize_url_for_identity(raw: str | None) -> str | None:
    """Return a stable URL identity string for matching."""
    if not raw or not raw.strip():
        return None

    candidate = raw.strip()
    if not candidate.startswith(("http://", "https://")):
        candidate = "https://" + candidate

    parsed = urlparse(candidate)
    host = (parsed.netloc or "").lower().removeprefix("www.")
    if not host:
        return None

    path = (parsed.path or "").rstrip("/").lower()
    return f"{host}{path}"


def normalize_address_for_identity(raw: str | None) -> str:
    """Normalize an address enough to compare likely duplicate venues."""
    if not raw or not raw.strip():
        return ""

    address = raw.strip().casefold()
    address = address.replace("&", " and ")
    address = _ADDRESS_ZIP_RE.sub(" ", address)
    address = re.sub(r"\bunited\s+states\b", " ", address)
    address = _ADDRESS_UNIT_RE.sub(" ", address)
    for pattern, replacement in _ADDRESS_PHRASE_REPLACEMENTS:
        address = pattern.sub(replacement, address)
    address = _ADDRESS_NON_ALNUM_RE.sub(" ", address)

    tokens = []
    for token in address.split():
        normalized = _ADDRESS_TOKEN_MAP.get(token, token)
        if normalized:
            tokens.append(normalized)
    return " ".join(tokens)


def significant_name_tokens(name: str | None) -> set[str]:
    """Return name tokens that are useful for venue identity matching."""
    if not name:
        return set()

    return {
        token
        for token in make_fingerprint(name).split()
        if token
        and not token.isdigit()
        and token not in _NAME_STOPWORDS
    }


def _compact_name(name: str | None) -> str:
    if not name:
        return ""
    return re.sub(r"[^a-z0-9]", "", name.casefold())


def _name_identity_score(name_a: str | None, name_b: str | None) -> int:
    """Return 0=no match, 1=weak match, 2=strong match."""
    compact_a = _compact_name(name_a)
    compact_b = _compact_name(name_b)
    if not compact_a or not compact_b:
        return 0

    if compact_a in compact_b or compact_b in compact_a:
        return 2

    tokens_a = significant_name_tokens(name_a)
    tokens_b = significant_name_tokens(name_b)
    if tokens_a and tokens_b:
        overlap = tokens_a & tokens_b
        if overlap:
            overlap_ratio = len(overlap) / min(len(tokens_a), len(tokens_b))
            if overlap_ratio > 0.5:
                return 2
            return 1

    if min(len(compact_a), len(compact_b)) >= 6:
        if SequenceMatcher(None, compact_a, compact_b).ratio() >= 0.82:
            return 2

    return 0


def _distance_miles(
    lat_a: float | None,
    lng_a: float | None,
    lat_b: float | None,
    lng_b: float | None,
) -> float | None:
    if None in (lat_a, lng_a, lat_b, lng_b):
        return None

    lat1 = math.radians(float(lat_a))
    lng1 = math.radians(float(lng_a))
    lat2 = math.radians(float(lat_b))
    lng2 = math.radians(float(lng_b))

    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 3958.7613 * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


def likely_same_venue(
    *,
    name_a: str | None,
    address_a: str | None,
    url_a: str | None,
    lat_a: float | None = None,
    lng_a: float | None = None,
    name_b: str | None,
    address_b: str | None,
    url_b: str | None,
    lat_b: float | None = None,
    lng_b: float | None = None,
) -> bool:
    """Conservatively decide whether two records look like the same venue."""
    name_score = _name_identity_score(name_a, name_b)
    if name_score <= 0:
        return False

    normalized_url_a = normalize_url_for_identity(url_a)
    normalized_url_b = normalize_url_for_identity(url_b)
    same_url = False
    if normalized_url_a and normalized_url_b:
        if normalized_url_a == normalized_url_b:
            same_url = True
        else:
            return False

    normalized_address_a = normalize_address_for_identity(address_a)
    normalized_address_b = normalize_address_for_identity(address_b)
    same_address = bool(
        normalized_address_a
        and normalized_address_b
        and normalized_address_a == normalized_address_b
    )

    distance = _distance_miles(lat_a, lng_a, lat_b, lng_b)
    nearby = distance is not None and distance <= 0.35

    if same_address and name_score >= 2:
        return True

    if same_url and same_address and name_score >= 1:
        return True

    if same_url and nearby and name_score >= 2:
        return True

    return False


def cluster_likely_same_venues(
    items: Sequence[T],
    *,
    get_name: Callable[[T], str | None],
    get_address: Callable[[T], str | None],
    get_url: Callable[[T], str | None],
    get_lat: Callable[[T], float | None] | None = None,
    get_lng: Callable[[T], float | None] | None = None,
) -> list[list[T]]:
    """Group records that likely refer to the same physical venue."""
    if len(items) <= 1:
        return [list(items)] if items else []

    parents = list(range(len(items)))

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        root_left = find(left)
        root_right = find(right)
        if root_left != root_right:
            parents[root_right] = root_left

    for left in range(len(items)):
        for right in range(left + 1, len(items)):
            item_left = items[left]
            item_right = items[right]
            if likely_same_venue(
                name_a=get_name(item_left),
                address_a=get_address(item_left),
                url_a=get_url(item_left),
                lat_a=get_lat(item_left) if get_lat else None,
                lng_a=get_lng(item_left) if get_lng else None,
                name_b=get_name(item_right),
                address_b=get_address(item_right),
                url_b=get_url(item_right),
                lat_b=get_lat(item_right) if get_lat else None,
                lng_b=get_lng(item_right) if get_lng else None,
            ):
                union(left, right)

    grouped: dict[int, list[T]] = {}
    for index, item in enumerate(items):
        root = find(index)
        grouped.setdefault(root, []).append(item)
    return list(grouped.values())


def pick_canonical_item(
    items: Sequence[T],
    *,
    get_id: Callable[[T], int | None],
    get_brand_group_id: Callable[[T], int | None],
    get_address: Callable[[T], str | None],
    extra_rank: Callable[[T], tuple] | None = None,
) -> T:
    """Pick the most stable representative from a duplicate cluster."""
    if not items:
        raise ValueError("pick_canonical_item() requires at least one item")

    brand_counts = Counter(
        brand_group_id
        for brand_group_id in (get_brand_group_id(item) for item in items)
        if brand_group_id is not None
    )

    def rank(item: T) -> tuple:
        address = get_address(item) or ""
        item_id = get_id(item)
        brand_group_id = get_brand_group_id(item)
        extra = extra_rank(item) if extra_rank else ()
        if not isinstance(extra, tuple):
            extra = (extra,)

        return (
            brand_counts.get(brand_group_id, 0),
            int(brand_group_id is not None),
            int(bool(address)),
            int(not _UNIT_HINT_RE.search(address)),
            extra,
            -(item_id or 0),
        )

    return max(items, key=rank)