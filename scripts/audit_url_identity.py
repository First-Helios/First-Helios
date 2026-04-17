#!/usr/bin/env python3
"""
scripts/audit_url_identity.py — One-time audit & cleanup for cross-brand URL contamination.

Finds restaurant_url rows where different brand_groups share the same URL,
which causes website_scraper to fan out deals to the wrong businesses.

Example: "Wings N More" and "Wings-N-Things" sharing houstonwings.com — the
website belongs to Wings 'n Things (Houston chain), not Wings N More (Austin).

Usage:
    # Audit only (no changes):
    PYTHONPATH=. python scripts/audit_url_identity.py

    # Apply fixes — deactivate bad URLs and their associated deals:
    PYTHONPATH=. python scripts/audit_url_identity.py --fix

    # On OrangePi production:
    cd /home/orangepi/CodeProjects/First-Helios
    source .venv/bin/activate
    PYTHONPATH=. python scripts/audit_url_identity.py          # audit first
    PYTHONPATH=. python scripts/audit_url_identity.py --fix    # then fix
"""

import argparse
import logging
import re
import sys
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, text

from core.database import (
    BrandGroup,
    LocalEmployer,
    MealDeal,
    RestaurantURL,
    get_engine,
    get_session,
    init_db,
)
from core.normalizer import make_fingerprint

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

_NAME_TOKEN_STOPWORDS = {
    "restaurant", "restaurants", "bar", "grill", "cafe", "coffee",
    "the", "and", "of", "at", "on", "n", "sports", "pub", "lounge",
    "kitchen", "house", "place", "shop", "food", "foods",
    "diner", "eatery", "bistro", "tavern", "inn",
}
_NAME_FRAGMENT_STOPWORDS = _NAME_TOKEN_STOPWORDS | {"s"}
_LOCATION_DESCRIPTOR_TOKENS = {
    "airport", "avenue", "block", "blvd", "boulevard", "building",
    "campus", "center", "centre", "corner", "corners", "crossing",
    "direction", "district", "downtown", "drive", "dr", "east",
    "highway", "hill", "hills", "hwy", "junction", "lane", "ln",
    "mall", "market", "midtown", "north", "northeast", "northwest",
    "park", "parkway", "plaza", "rd", "road", "south", "southeast",
    "southwest", "square", "station", "st", "street", "suite",
    "ste", "terminal", "tower", "town", "uptown", "village", "west",
}

_URL_TOKEN_STOPWORDS = {
    "www", "com", "net", "org", "co", "io", "biz", "info",
    "html", "htm", "php", "asp", "aspx",
    "index", "home", "homepage", "location", "locations",
    "menu", "menus", "static", "page", "pages",
    "official", "site", "visit", "tx", "texas",
}


def _ordered_name_fragments(name: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    raw_tokens = [re.sub(r"[^a-z0-9]", "", token) for token in re.findall(r"[a-z0-9']+", normalized.lower())]
    return [token for token in raw_tokens if token and token not in _NAME_FRAGMENT_STOPWORDS and (len(token) > 1 or token == "e")]


def _ordered_name_tokens(name: str) -> list[str]:
    return [token for token in _ordered_name_fragments(name) if len(token) > 1]


def _name_tokens(name: str) -> set[str]:
    """Significant tokens from a name for comparison (mirrors google_places_resolver)."""
    return set(_ordered_name_tokens(name))


def _compact_name_variants(name: str) -> set[str]:
    """Compact adjacent token groups to catch split brand spellings like Chi Lantro."""
    ordered_tokens = _ordered_name_fragments(name)
    variants: set[str] = set()
    for width in (2, 3, 4):
        for idx in range(len(ordered_tokens) - width + 1):
            variant = "".join(ordered_tokens[idx:idx + width])
            if len(variant) > 4:
                variants.add(variant)
    return variants


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        key = make_fingerprint(value)
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _looks_like_location_label(name: str) -> bool:
    lowered = name.lower()
    tokens = [token for token in _ordered_name_tokens(name) if len(token) > 1]
    if not tokens:
        return False

    if "&" in lowered or "+" in lowered:
        return True
    if any(any(ch.isdigit() for ch in token) for token in tokens):
        return True

    descriptor_count = sum(token in _LOCATION_DESCRIPTOR_TOKENS for token in tokens)
    if descriptor_count >= max(1, len(tokens) - 1):
        return True
    if len(tokens) <= 2 and descriptor_count >= 1:
        return True
    return False


def _compact_name(name: str) -> str:
    """Normalize a string for loose containment checks."""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _url_identity_text(url: str) -> str:
    """Extract host + path text from a URL for ownership scoring."""
    from urllib.parse import urlparse

    parsed = urlparse(url)
    host = (parsed.netloc or "").lower()
    host = host.removeprefix("www.")
    path = (parsed.path or "").lower()
    raw_text = f"{host} {path}"
    tokens = re.split(r"[^a-z0-9]+", raw_text)
    filtered = [
        token
        for token in tokens
        if len(token) > 1 and not token.isdigit() and token not in _URL_TOKEN_STOPWORDS
    ]
    return " ".join(filtered)


def _url_match_score(name: str, url: str) -> int:
    """Score how plausibly a URL belongs to a business name.

    Higher is better. We use both token overlap and compact containment so
    domains like wingsnmore-austin.com still match "Wings N More".
    """
    name_tokens = _name_tokens(name)
    ordered_tokens = _ordered_name_tokens(name)
    url_text = _url_identity_text(url)
    url_tokens = _name_tokens(url_text)
    compact_name = _compact_name(name)
    compact_url = _compact_name(url_text)
    compact_variants = _compact_name_variants(name)

    score = 0
    if compact_name and compact_name in compact_url:
        score += 2
    elif any(variant in compact_url for variant in compact_variants):
        score += 2
    elif any(len(token) > 4 and compact_url.startswith(token) for token in ordered_tokens):
        score += 1
    if name_tokens & url_tokens:
        score += 1
    return score


def audit_cross_brand_urls(session) -> list[dict]:
    """Find URLs shared by employers from different brand groups.

    Returns list of problem records with details.
    """
    # PostgreSQL is strict about GROUP BY expressions. Compute the normalized
    # URL once in a subquery, then group by the subquery column.
    normalized_urls = (
        session.query(
            RestaurantURL.id.label("restaurant_url_id"),
            RestaurantURL.local_employer_id.label("local_employer_id"),
            func.lower(func.rtrim(RestaurantURL.url, "/")).label("normalized_url"),
        )
        .filter(RestaurantURL.is_active.is_(True))
        .subquery()
    )

    url_groups = (
        session.query(
            normalized_urls.c.normalized_url,
            func.count(normalized_urls.c.restaurant_url_id),
            func.count(func.distinct(LocalEmployer.brand_group_id)),
        )
        .join(LocalEmployer, LocalEmployer.id == normalized_urls.c.local_employer_id)
        .group_by(normalized_urls.c.normalized_url)
        .having(func.count(func.distinct(LocalEmployer.brand_group_id)) > 1)
        .all()
    )

    problems = []
    for norm_url, url_count, brand_count in url_groups:
        # Get details for each employer sharing this URL
        rows = (
            session.query(RestaurantURL, LocalEmployer)
            .join(LocalEmployer, LocalEmployer.id == RestaurantURL.local_employer_id)
            .filter(
                func.lower(func.rtrim(RestaurantURL.url, "/")) == norm_url,
                RestaurantURL.is_active.is_(True),
            )
            .all()
        )

        # Group by brand_group_id
        by_brand: dict[int | None, list] = defaultdict(list)
        for rurl, emp in rows:
            by_brand[emp.brand_group_id].append({
                "rurl_id": rurl.id,
                "emp_id": emp.id,
                "emp_name": emp.name,
                "brand_group_id": emp.brand_group_id,
                "source": rurl.source,
            })

        problems.append({
            "url": norm_url,
            "total_employers": url_count,
            "distinct_brands": brand_count,
            "brands": dict(by_brand),
        })

    return problems


def audit_name_mismatch_urls(session) -> list[dict]:
    """Find restaurant_url entries where the employer name doesn't match
    any plausible variation of the URL domain."""
    mismatches = []

    rows = (
        session.query(RestaurantURL, LocalEmployer)
        .join(LocalEmployer, LocalEmployer.id == RestaurantURL.local_employer_id)
        .filter(
            RestaurantURL.is_active.is_(True),
            LocalEmployer.industry.in_(["food_full_service", "fast_food", "bar_nightlife"]),
        )
        .all()
    )

    # Group by URL to check if any employer sharing the URL has a matching name
    url_to_employers: dict[str, list] = defaultdict(list)
    for rurl, emp in rows:
        norm = rurl.url.rstrip("/").lower()
        url_to_employers[norm].append((rurl, emp))

    for norm_url, group in url_to_employers.items():
        if len(group) <= 1:
            continue  # single-employer URLs are fine

        # Check if all employers share the same brand group
        brand_ids = {emp.brand_group_id for _, emp in group}
        if len(brand_ids) <= 1:
            continue  # same brand — expected fan-out

        scored_group = []
        for rurl, emp in group:
            score = _url_match_score(emp.name, rurl.url)
            scored_group.append((rurl, emp, score))

        best_score = max(score for _, _, score in scored_group)
        if best_score < 2:
            continue

        likely_owners = _dedupe_preserve_order([emp.name for _, emp, score in scored_group if score == best_score])
        for rurl, emp, score in scored_group:
            if score > 0 or _looks_like_location_label(emp.name):
                continue
            mismatches.append({
                "rurl_id": rurl.id,
                "emp_id": emp.id,
                "emp_name": emp.name,
                "url": rurl.url,
                "likely_owner_names": likely_owners,
                "source": rurl.source,
            })

    return mismatches


def find_contaminated_deals(session, bad_emp_ids: set[int]) -> list[dict]:
    """Find meal_deals linked to employers that have contaminated URLs."""
    if not bad_emp_ids:
        return []

    deals = (
        session.query(MealDeal)
        .filter(
            MealDeal.local_employer_id.in_(bad_emp_ids),
            MealDeal.is_active.is_(True),
            MealDeal.source == "website_scrape",
        )
        .all()
    )

    return [
        {
            "deal_id": d.id,
            "emp_id": d.local_employer_id,
            "deal_name": d.deal_name,
            "source_url": d.source_url,
            "source": d.source,
        }
        for d in deals
    ]


def apply_fixes(session, actionable_mismatches: list[dict], bad_emp_ids: set[int]) -> dict:
    """Deactivate clearly bad URLs and their contaminated deals.

    This intentionally acts only on rows that are both:
      1. Part of a cross-brand shared URL group, and
      2. A clear name mismatch against another employer sharing that URL.

    That keeps the cleanup conservative and avoids deactivating legitimate
    alias/duplicate records that happen to have different brand_group_ids.
    """
    stats = {"urls_deactivated": 0, "deals_deactivated": 0}
    now = datetime.now(timezone.utc)

    seen_rurl_ids: set[int] = set()
    for mismatch in actionable_mismatches:
        rurl_id = mismatch["rurl_id"]
        if rurl_id in seen_rurl_ids:
            continue
        seen_rurl_ids.add(rurl_id)

        rurl = session.get(RestaurantURL, rurl_id)
        if rurl and rurl.is_active:
            rurl.is_active = False
            rurl.updated_at = now
            stats["urls_deactivated"] += 1
            logger.info(
                "  Deactivated URL %d: %s → %s (likely owner: %s)",
                rurl.id,
                mismatch["emp_name"],
                mismatch["url"],
                ", ".join(mismatch["likely_owner_names"]),
            )

    # Deactivate website_scrape deals for the affected employers
    if bad_emp_ids:
        count = (
            session.query(MealDeal)
            .filter(
                MealDeal.local_employer_id.in_(bad_emp_ids),
                MealDeal.is_active.is_(True),
                MealDeal.source == "website_scrape",
            )
            .update(
                {"is_active": False, "updated_at": now},
                synchronize_session=False,
            )
        )
        stats["deals_deactivated"] = count

    session.commit()
    return stats


def main():
    parser = argparse.ArgumentParser(
        description="Audit and clean up cross-brand URL contamination in restaurant_urls"
    )
    parser.add_argument(
        "--fix", action="store_true",
        help="Apply fixes (deactivate bad URLs and their deals). Without this, audit-only.",
    )
    parser.add_argument("--region", default="austin_tx")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    print("\n" + "=" * 70)
    print("  MEAL DEAL URL IDENTITY AUDIT")
    print("=" * 70)

    # ── Audit 1: Cross-brand URL sharing ─────────────────────────────────
    print("\n── Cross-Brand URL Sharing ──────────────────────────────────")
    problems = audit_cross_brand_urls(session)

    if not problems:
        print("  ✓ No cross-brand URL contamination found.")
    else:
        print(f"  ✗ Found {len(problems)} URLs shared across different brands:\n")
        for p in problems:
            print(f"  URL: {p['url']}")
            print(f"  Shared by {p['total_employers']} employers across {p['distinct_brands']} brands:")
            for brand_id, entries in p["brands"].items():
                bg_name = "no brand"
                if brand_id:
                    bg = session.get(BrandGroup, brand_id)
                    bg_name = bg.canonical_name if bg else f"brand#{brand_id}"
                print(f"    Brand: {bg_name} (id={brand_id})")
                for e in entries:
                    print(f"      - {e['emp_name']} (emp_id={e['emp_id']}, source={e['source']})")
            print()

    # ── Audit 2: Actionable name mismatches ──────────────────────────────
    print("\n── Actionable Name Mismatches ───────────────────────────────")
    actionable_mismatches = audit_name_mismatch_urls(session)

    if not actionable_mismatches:
        print("  ✓ No clear name-mismatch URL assignments found.")
    else:
        print(f"  ✗ Found {len(actionable_mismatches)} clear mismatch rows:\n")
        for mismatch in actionable_mismatches[:40]:
            print(f"    URL row #{mismatch['rurl_id']}: {mismatch['emp_name']} → {mismatch['url']}")
            print(f"      likely owner: {', '.join(mismatch['likely_owner_names'])}")
        if len(actionable_mismatches) > 40:
            print(f"    ... and {len(actionable_mismatches) - 40} more")

    # ── Collect bad employer IDs from actionable mismatches ──────────────
    bad_emp_ids: set[int] = set()
    for mismatch in actionable_mismatches:
        bad_emp_ids.add(mismatch["emp_id"])

    # ── Audit 3: Contaminated deals ──────────────────────────────────────
    print("\n── Contaminated Deals (website_scrape) ─────────────────────")
    bad_deals = find_contaminated_deals(session, bad_emp_ids)

    if not bad_deals:
        print("  ✓ No contaminated deals found.")
    else:
        print(f"  ✗ Found {len(bad_deals)} deals linked to mismatched employers:\n")
        for d in bad_deals[:20]:  # show first 20
            print(f"    Deal #{d['deal_id']}: {d['deal_name'][:60]}")
            print(f"      emp_id={d['emp_id']}, source_url={d['source_url']}")
        if len(bad_deals) > 20:
            print(f"    ... and {len(bad_deals) - 20} more")

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n── Summary ─────────────────────────────────────────────────")
    print(f"  Cross-brand URL conflicts: {len(problems)}")
    print(f"  Actionable URL mismatches: {len(actionable_mismatches)}")
    print(f"  Employers with bad URLs:   {len(bad_emp_ids)}")
    print(f"  Contaminated deals:        {len(bad_deals)}")

    if not args.fix:
        if actionable_mismatches or bad_deals:
            print("\n  Run with --fix to deactivate bad URLs and their deals.")
        print()
        session.close()
        return

    # ── Apply fixes ──────────────────────────────────────────────────────
    print("\n── Applying Fixes ──────────────────────────────────────────")
    stats = apply_fixes(session, actionable_mismatches, bad_emp_ids)
    print(f"\n  URLs deactivated:  {stats['urls_deactivated']}")
    print(f"  Deals deactivated: {stats['deals_deactivated']}")
    print("  ✓ Done. Changes committed.\n")

    session.close()


if __name__ == "__main__":
    main()
