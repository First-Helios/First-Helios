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
import sys
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


def _name_tokens(name: str) -> set[str]:
    """Significant tokens from a name for comparison (mirrors google_places_resolver)."""
    stopwords = {
        "restaurant", "restaurants", "bar", "grill", "cafe", "coffee",
        "the", "and", "of", "at", "n", "sports", "pub", "lounge",
        "kitchen", "house", "place", "shop", "food", "foods",
        "diner", "eatery", "bistro", "tavern", "inn",
    }
    fp = make_fingerprint(name)
    return {t for t in fp.split() if t not in stopwords and len(t) > 1}


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
    from urllib.parse import urlparse

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

        # Different brands sharing a URL — check name overlap
        for rurl, emp in group:
            emp_tokens = _name_tokens(emp.name)
            # Check against other employers' names in the group
            other_names = [e.name for _, e in group if e.id != emp.id]
            for other_name in other_names:
                other_tokens = _name_tokens(other_name)
                overlap = emp_tokens & other_tokens
                if not overlap:
                    mismatches.append({
                        "rurl_id": rurl.id,
                        "emp_id": emp.id,
                        "emp_name": emp.name,
                        "url": rurl.url,
                        "conflicting_name": other_name,
                        "emp_tokens": emp_tokens,
                        "other_tokens": other_tokens,
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


def apply_fixes(session, problems: list[dict], bad_emp_ids: set[int]) -> dict:
    """Deactivate bad URLs and their contaminated deals.

    For cross-brand URL sharing: keeps the URL for the brand group with the
    most employers (likely the rightful owner), deactivates for others.
    """
    stats = {"urls_deactivated": 0, "deals_deactivated": 0}
    now = datetime.now(timezone.utc)

    for problem in problems:
        brands = problem["brands"]
        if len(brands) <= 1:
            continue

        # The brand with the most employers sharing this URL is likely the
        # legitimate owner (chain website). Deactivate for other brands.
        sorted_brands = sorted(brands.items(), key=lambda x: len(x[1]), reverse=True)
        _owner_brand_id, _owner_entries = sorted_brands[0]

        for brand_id, entries in sorted_brands[1:]:
            for entry in entries:
                rurl = session.get(RestaurantURL, entry["rurl_id"])
                if rurl and rurl.is_active:
                    rurl.is_active = False
                    rurl.updated_at = now
                    stats["urls_deactivated"] += 1
                    logger.info(
                        "  Deactivated URL %d: %s → %s (brand_group=%s)",
                        rurl.id, entry["emp_name"], problem["url"], brand_id,
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

    # ── Collect bad employer IDs ─────────────────────────────────────────
    bad_emp_ids: set[int] = set()
    for p in problems:
        brands = p["brands"]
        if len(brands) <= 1:
            continue
        sorted_brands = sorted(brands.items(), key=lambda x: len(x[1]), reverse=True)
        for _, entries in sorted_brands[1:]:
            for entry in entries:
                bad_emp_ids.add(entry["emp_id"])

    # ── Audit 2: Contaminated deals ──────────────────────────────────────
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
    print(f"  Employers with bad URLs:   {len(bad_emp_ids)}")
    print(f"  Contaminated deals:        {len(bad_deals)}")

    if not args.fix:
        if problems or bad_deals:
            print("\n  Run with --fix to deactivate bad URLs and their deals.")
        print()
        session.close()
        return

    # ── Apply fixes ──────────────────────────────────────────────────────
    print("\n── Applying Fixes ──────────────────────────────────────────")
    stats = apply_fixes(session, problems, bad_emp_ids)
    print(f"\n  URLs deactivated:  {stats['urls_deactivated']}")
    print(f"  Deals deactivated: {stats['deals_deactivated']}")
    print("  ✓ Done. Changes committed.\n")

    session.close()


if __name__ == "__main__":
    main()
