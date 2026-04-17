"""Shared helpers for website scrape audit and replay analysis.

These functions are intentionally side-effect free so they can be reused by
scripts, tests, and audit-only paths without requiring database access.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse

from config.paths import CACHE_DIR, WEBSITE_SCRAPE_DEBUG_DIR

DEFAULT_AUDIT_PATH = CACHE_DIR / "website_scrape_audit.json"
DEFAULT_DEBUG_DIR = WEBSITE_SCRAPE_DEBUG_DIR

_SOCIAL_DOMAINS = (
    "facebook.com",
    "instagram.com",
    "x.com",
    "twitter.com",
    "tiktok.com",
    "youtube.com",
)

_DIRECTORY_HOST_TOKENS = (
    "tripadvisor",
    "yelp",
    "austintexas.org",
    "texasbob",
    "usmapiz",
    "opentable",
    "findmeglutenfree",
)

_HOTEL_HOST_TOKENS = (
    "hilton.com",
    "marriott.com",
    "hyatt.com",
    "ihg.com",
    "fairmont",
    "embassysuites",
    "hotel",
    "resort",
)

_VENDOR_MENU_HOST_TOKENS = (
    "toasttab.com",
    "square.site",
    "smartonlineorder.com",
    "s4shops.com",
    "menufy.com",
    "grubhub.com",
    "doordash.com",
    "ubereats.com",
    "order.online",
    "ezcater.com",
)

_OTHER_NON_RESTAURANT_HOST_TOKENS = (
    "labcorp",
    "aaa.com",
    "amli.com",
    "canva.site",
    "linktr.ee",
    "mailchi.mp",
    "law",
    "seminary",
    "juniors",
    "apartments",
    "school",
    "church",
)

_LOCATOR_PATH_TOKENS = (
    "/locations/",
    "/location/",
    "/restaurants/",
    "/store-locator",
    "/stores/",
    "/store/",
)


def classify_domain_family(url: str) -> str:
    parsed = urlparse(url or "")
    host = parsed.netloc.lower()
    path = parsed.path.lower()

    if not host:
        return "unknown"
    if any(host == domain or host.endswith(f".{domain}") for domain in _SOCIAL_DOMAINS):
        return "social"
    if host.endswith(".gov"):
        return "government"
    if any(token in host for token in _DIRECTORY_HOST_TOKENS):
        return "directory"
    if any(token in host for token in _HOTEL_HOST_TOKENS):
        return "hotel"
    if any(token in host for token in _VENDOR_MENU_HOST_TOKENS):
        return "vendor_menu_host"
    if host.startswith("locations.") or any(token in path for token in _LOCATOR_PATH_TOKENS):
        return "locator"
    if any(token in host for token in _OTHER_NON_RESTAURANT_HOST_TOKENS):
        return "other_nonrestaurant"
    return "restaurant_or_first_party"


def classify_no_deal_stage(entry: dict[str, Any]) -> str:
    total_blocks = entry.get("total_blocks")
    sample_blocks = entry.get("sample_blocks") or []
    discovered_pages = entry.get("discovered_pages") or []
    pdf_links = entry.get("pdf_links") or []

    if total_blocks is None and not sample_blocks and not discovered_pages and not pdf_links:
        return "fetch_or_parse_failed"
    if discovered_pages:
        return "discovery_found_candidates_but_no_signal"
    if pdf_links:
        return "pdf_present_but_no_signal"
    if (total_blocks or 0) > 0 or sample_blocks:
        return "content_seen_but_extraction_failed"
    return "empty_or_unusable_page"


def page_has_jsonld(html: str | None) -> bool:
    return bool(html and "application/ld+json" in html)


def load_audit_entries(path: Path = DEFAULT_AUDIT_PATH) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"Audit file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Audit file is not valid JSON: {path}") from exc

    if not isinstance(payload, list):
        raise SystemExit(f"Audit file must contain a JSON list: {path}")
    return [entry for entry in payload if isinstance(entry, dict)]


def load_debug_bundles(debug_dir: Path = DEFAULT_DEBUG_DIR) -> tuple[dict[str, dict[str, Any]], int]:
    bundles: dict[str, dict[str, Any]] = {}
    invalid_json = 0

    if not debug_dir.exists():
        return bundles, invalid_json

    for path in sorted(debug_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            invalid_json += 1
            continue
        if not isinstance(payload, dict):
            invalid_json += 1
            continue
        site_key = payload.get("site_key")
        if isinstance(site_key, str) and site_key:
            bundles[site_key] = payload

    return bundles, invalid_json


def summarize_debug_bundle(
    bundle: dict[str, Any] | None,
    *,
    extract_text_blocks: Callable[[str], list[str]] | None = None,
    block_sample_limit: int = 10,
) -> dict[str, Any]:
    if not isinstance(bundle, dict):
        return {
            "page_count": 0,
            "page_fetch_types": {},
            "has_jsonld": False,
            "total_blocks": None,
            "sample_blocks": [],
            "discovered_pages": [],
            "hinted_pages": [],
            "pdf_links": [],
            "parsed_pdf_count": 0,
            "menu_avg_price": None,
            "signal_count": 0,
        }

    pages = bundle.get("pages") if isinstance(bundle.get("pages"), dict) else {}
    pdfs = bundle.get("pdfs") if isinstance(bundle.get("pdfs"), dict) else {}
    discovered_pages = bundle.get("discovered_pages") if isinstance(bundle.get("discovered_pages"), list) else []
    hinted_pages = bundle.get("hinted_pages") if isinstance(bundle.get("hinted_pages"), list) else []
    pdf_links = bundle.get("pdf_links") if isinstance(bundle.get("pdf_links"), list) else []
    signals = bundle.get("signals") if isinstance(bundle.get("signals"), list) else []

    fetch_type_counts: Counter[str] = Counter()
    has_jsonld = False
    total_blocks = 0 if extract_text_blocks else None
    sample_blocks: list[str] = []

    for page in pages.values():
        if not isinstance(page, dict):
            continue
        fetch_type = str(page.get("fetch_type") or "unknown")
        fetch_type_counts[fetch_type] += 1

        html = page.get("html")
        if isinstance(html, str):
            if page_has_jsonld(html):
                has_jsonld = True
            if extract_text_blocks is not None:
                blocks = extract_text_blocks(html)
                total_blocks += len(blocks)
                remaining = max(0, block_sample_limit - len(sample_blocks))
                if remaining:
                    sample_blocks.extend(block[:200] for block in blocks[:remaining])

    return {
        "page_count": len(pages),
        "page_fetch_types": dict(fetch_type_counts),
        "has_jsonld": has_jsonld,
        "total_blocks": total_blocks,
        "sample_blocks": sample_blocks,
        "discovered_pages": list(discovered_pages),
        "hinted_pages": list(hinted_pages),
        "pdf_links": list(pdf_links),
        "parsed_pdf_count": len(pdfs),
        "menu_avg_price": bundle.get("menu_avg_price"),
        "signal_count": len(signals),
    }