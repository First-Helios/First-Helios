"""
collectors/meal_deals/sub_deals.py — Multi-promo decomposition into sub_deals.

A single happy-hour block like:
    "Happy Hour Mon-Fri 3-6pm. $1 Off Draft Beer. Half off appetizers.
     $5 Frozen Margaritas. $2 Off Wine."
is conceptually five different offers.  The ingest pipeline has long split
these into separate rows (see _split_multi_promo in website_scraper.py),
but that loses the relationship between offers.

`extract_sub_deals()` takes a raw text block and returns a structured list:
    [
      {"item": "draft beer",      "discount_type": "discount_amount",  "discount_value": 1.00},
      {"item": "appetizers",      "discount_type": "percentage_off",   "discount_value": 50.0},
      {"item": "frozen margaritas","discount_type": "absolute",         "discount_value": 5.00},
      {"item": "wine",            "discount_type": "discount_amount",  "discount_value": 2.00},
    ]

Used by:
  - scripts/one_shot/populate_sub_deals.py   (backfill existing rows)
  - collectors/meal_deals/ingest.py  (attach to new signals at ingest)

Heuristic, not perfect.  We only emit sub_deals when the block clearly
contains ≥2 distinct offers.  Conservatism avoids polluting simple deals
("$5 combo meal" → no sub_deals) with false structure.
"""

from __future__ import annotations

import re
from typing import Any

# Splitters between offers in a promo block
_SPLIT_RE = re.compile(r"(?:[.!?;|•·\n]+\s*)|(?:\s{2,})|(?=\s+\$\d)")

# "$X off ITEM" or "ITEM $X off"
_DOLLAR_OFF_ITEM_RE = re.compile(
    r"\$\s*(\d{1,3}(?:\.\d{2})?)\s*off\s+(?:all\s+)?([a-z][a-z\s/&'-]{2,40}?)(?=\s*(?:[.,;]|$|\s+\$|\s+(?:and|plus)\s))",
    re.IGNORECASE,
)
_ITEM_DOLLAR_OFF_RE = re.compile(
    r"\b([a-z][a-z\s/&'-]{2,40}?)\s*[-–—:]*\s*\$\s*(\d{1,3}(?:\.\d{2})?)\s*off\b",
    re.IGNORECASE,
)

# "$X ITEM" (absolute price tied to item) — "$5 Frozen Margaritas", "$2 wells"
_ABSOLUTE_ITEM_RE = re.compile(
    r"\$\s*(\d{1,3}(?:\.\d{2})?)\s+([a-z][a-z\s/&'-]{2,40}?)(?=\s*(?:[.,;]|$|\s+\$|\s+(?:and|plus|or|off)\s))",
    re.IGNORECASE,
)

# "X% off ITEM" / "half off ITEM" / "½ off ITEM"
_PCT_OFF_ITEM_RE = re.compile(
    r"(?:(\d{1,2})\s*%|half|½|1/2)\s*(?:off|price)\s+(?:all\s+)?([a-z][a-z\s/&'-]{2,40}?)(?=\s*(?:[.,;]|$|\s+\$|\s+(?:and|plus|or)\s))",
    re.IGNORECASE,
)
_ITEM_PCT_OFF_RE = re.compile(
    r"\b([a-z][a-z\s/&'-]{2,40}?)\s*[-–—:]*\s*(?:(\d{1,2})\s*%|half|½|1/2)\s*(?:off|price)\b",
    re.IGNORECASE,
)

# Words to strip from item phrases
_ITEM_STOPWORDS = {
    "all", "any", "our", "your", "the", "a", "an", "enjoy", "featuring",
    "special", "specials", "select", "get", "off",
}

# If an item phrase contains any of these, it's parser noise — drop it.
_ITEM_REJECT_RE = re.compile(
    r"\$\d|^\s*$|^(?:off|and|plus|or|for|with)\b",
    re.IGNORECASE,
)


def _clean_item(raw: str) -> str:
    """Lowercase, strip, drop leading stopwords, collapse whitespace."""
    s = re.sub(r"\s+", " ", raw).strip(" -–—:,.").lower()
    # Drop leading stopwords
    tokens = s.split()
    while tokens and tokens[0] in _ITEM_STOPWORDS:
        tokens = tokens[1:]
    # Trim obvious trailing clauses
    joined = " ".join(tokens)
    joined = re.sub(r"\s+(and|plus|or)\s+.*$", "", joined)
    return joined.strip()


def _half_to_50(match_group: str | None) -> float:
    """Convert a percentage match group: None or digit string → float."""
    if match_group and match_group.isdigit():
        return float(match_group)
    return 50.0  # "half off" / "½ off"


def extract_sub_deals(text: str) -> list[dict[str, Any]]:
    """Decompose `text` into a list of structured offer dicts.

    Each dict has:
        item:           short phrase (≤ ~40 chars)
        discount_type:  "absolute" | "discount_amount" | "percentage_off"
        discount_value: float

    Returns [] if no structured offers can be extracted.  Returns a list of
    length ≥ 2 only — single offers stay as the primary deal columns.
    """
    if not text or len(text) < 15:
        return []

    results: list[dict[str, Any]] = []
    seen_items: set[str] = set()

    def _add(item: str, dtype: str, dvalue: float) -> None:
        if not item or len(item) < 3 or len(item) > 50:
            return
        if _ITEM_REJECT_RE.search(item):
            return
        # Dedup on item only — if we've already captured "appetizers" as
        # half-off, don't also add it as $X-off.
        if item in seen_items:
            return
        seen_items.add(item)
        results.append({
            "item": item,
            "discount_type": dtype,
            "discount_value": round(dvalue, 2),
        })

    # Order of extraction matters; more specific patterns first.

    # "$X off ITEM"  (discount amount) — the dominant order in real copy.
    for m in _DOLLAR_OFF_ITEM_RE.finditer(text):
        _add(_clean_item(m.group(2)), "discount_amount", float(m.group(1)))

    # "X% off ITEM" / "half off ITEM"
    for m in _PCT_OFF_ITEM_RE.finditer(text):
        _add(_clean_item(m.group(2)), "percentage_off", _half_to_50(m.group(1)))

    # "ITEM half off" / "ITEM 50% off" — the trailing form is useful for
    # headings like "Appetizers — Half Off".  Discount_amount's trailing form
    # ("Teas $1 off") is too noisy, so we omit it.  Require ≤3 words to avoid
    # sentences like "pull up a chair and enjoy ½ price" sneaking through.
    for m in _ITEM_PCT_OFF_RE.finditer(text):
        item = _clean_item(m.group(1))
        if len(item.split()) > 3:
            continue
        _add(item, "percentage_off", _half_to_50(m.group(2)))

    # "$X ITEM" absolute pricing — only accept if text already has another
    # offer (we don't want to tag every "$5 burger" line as a sub_deal).
    if results:
        for m in _ABSOLUTE_ITEM_RE.finditer(text):
            # Avoid re-capturing "$1 off ITEM" constructs we already handled.
            context = text[max(0, m.start() - 2): m.end() + 6].lower()
            if "off" in context:
                continue
            _add(_clean_item(m.group(2)), "absolute", float(m.group(1)))

    # Only emit when we have 2+ distinct offers — a single hit stays on the
    # primary columns.
    if len(results) < 2:
        return []

    return results
