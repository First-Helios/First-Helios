"""
Shared parsing helpers for hintbook adapters.

Every adapter turns raw HTML into AggregatorRecords via small, testable
primitives. Keeping this lean keeps adapters boring and easy to fix when
aggregator markup changes.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup, Tag

_PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:[.,]\d{2})?)")
_PERCENT_RE = re.compile(r"(\d{1,3})\s?%\s?off", re.IGNORECASE)
_PROMO_CODE_RE = re.compile(
    r"(?:code|promo code|use code|enter code|coupon code|with code)[:\s]+([A-Z0-9][A-Z0-9_-]{2,20})",
    re.IGNORECASE,
)


def text_of(node: Tag | None) -> str:
    return node.get_text(" ", strip=True) if node else ""


def first_price(text: str) -> float | None:
    match = _PRICE_RE.search(text or "")
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", "."))
    except ValueError:
        return None


def first_promo_code(text: str) -> str | None:
    match = _PROMO_CODE_RE.search(text or "")
    return match.group(1).upper() if match else None


def derive_flags(text: str) -> frozenset[str]:
    lower = (text or "").lower()
    flags: set[str] = set()
    if "bogo" in lower or "buy one" in lower or "buy 1" in lower:
        flags.add("bogo")
    if "% off" in lower or _PERCENT_RE.search(text or ""):
        flags.add("percent_off")
    if "free" in lower:
        flags.add("free_item")
    if "happy hour" in lower:
        flags.add("happy_hour")
    if "app only" in lower or "in the app" in lower or "via app" in lower:
        flags.add("app_only")
    if "delivery" in lower and ("only" in lower or "exclusive" in lower):
        flags.add("delivery_only")
    if "new customer" in lower or "first-time" in lower or "first time" in lower:
        flags.add("new_customer")
    if _PROMO_CODE_RE.search(text or ""):
        flags.add("promo_code")
    return frozenset(flags)


def extract_outbound_domain(
    soup: BeautifulSoup,
    aggregator_host: str,
    *,
    brand_hint: str | None = None,
) -> tuple[str | None, str | None]:
    """Find the first outbound link that is NOT the aggregator itself.

    Returns (target_domain, target_first_party_url). Prefers links whose host
    contains brand_hint when supplied.
    """
    candidates: list[tuple[str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        try:
            parsed = urlparse(href)
        except Exception:
            continue
        if not parsed.netloc or not parsed.scheme.startswith("http"):
            continue
        host = parsed.netloc.lower().removeprefix("www.")
        if aggregator_host in host or host in aggregator_host:
            continue
        # skip common social / tracking hosts
        if any(
            skip in host
            for skip in (
                "facebook.com", "twitter.com", "x.com", "instagram.com",
                "tiktok.com", "youtube.com", "pinterest.com", "reddit.com",
                "linkedin.com", "google.com/amp", "bit.ly", "doubleclick.net",
                "googletagmanager.com", "amazon-adsystem.com",
            )
        ):
            continue
        candidates.append((host, href))

    if not candidates:
        return None, None

    if brand_hint:
        brand_hint_lower = brand_hint.lower()
        for host, href in candidates:
            if brand_hint_lower in host.replace("-", "").replace(".", ""):
                return host, href

    host, href = candidates[0]
    return host, href


def parse_valid_through(text: str) -> date | None:
    patterns = [
        (r"(?:ends?|through|thru|until|expires?)\s+([A-Za-z]{3,9}\.?\s+\d{1,2}(?:,\s*\d{4})?)", "%B %d, %Y"),
        (r"(?:ends?|through|thru|until|expires?)\s+(\d{1,2}/\d{1,2}/\d{2,4})", "%m/%d/%Y"),
    ]
    for rx, fmt in patterns:
        m = re.search(rx, text, re.IGNORECASE)
        if not m:
            continue
        raw = m.group(1)
        for candidate_fmt in (fmt, "%b %d, %Y", "%B %d %Y", "%m/%d/%y"):
            try:
                if "," not in raw and ", " in candidate_fmt:
                    continue
                parsed = datetime.strptime(raw, candidate_fmt)
                return parsed.date()
            except ValueError:
                continue
    return None


def normalize_brand_hint(headline: str) -> str | None:
    """Best-effort brand slug from a headline prefix. Not authoritative."""
    if not headline:
        return None
    # Strip quotes and leading/trailing noise
    stripped = re.sub(r"[\"'\u2018\u2019\u201c\u201d]", "", headline).strip()
    # Common aggregator pattern: "Brand: rest of headline"
    match = re.match(r"^([A-Z][A-Za-z0-9&\.\-' ]{1,30})[:\-—]", stripped)
    if match:
        raw = match.group(1).strip()
    else:
        # First 2 tokens heuristic
        tokens = stripped.split()[:3]
        raw = " ".join(tokens)
    slug = re.sub(r"[^a-z0-9]+", "", raw.lower())
    if len(slug) < 3:
        return None
    return slug
