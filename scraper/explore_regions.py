#!/usr/bin/env python3
"""
explore_regions.py — Multi-Region Data Exploration
====================================================
Probes the Starbucks careers API across several major metros to test the
hypothesis that every store lists exactly 2 standing requisitions (1 Barista
+ 1 Shift Supervisor) and that the current "critical" risk score is
therefore meaningless.

Outputs a detailed analysis report to stdout and saves raw data to
  scraper/exploration_results.json

Usage:
    python scraper/explore_regions.py
    python scraper/explore_regions.py --regions "Seattle, WA" "Chicago, IL" "Denver, CO"
"""

import json
import time
import argparse
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from datetime import datetime, timezone

# Reuse the existing scraper infrastructure
from scrape import (
    fetch_all_listings,
    parse_listing,
    aggregate_by_store,
    ROLE_WEIGHTS,
    VACANCY_THRESHOLDS,
    log,
)

# ── Default regions to probe ─────────────────────────────────────
DEFAULT_REGIONS = [
    "Seattle, WA, US",
    "Chicago, IL, US",
    "New York, NY, US",
    "Los Angeles, CA, US",
    "Denver, CO, US",
    "Miami, FL, US",
    "Atlanta, GA, US",
    "Dallas, TX, US",
]

INTER_REGION_DELAY = 3.0  # seconds between regions (be polite)


def analyze_region(location: str, radius: int = 25) -> dict:
    """Scrape one region and return a structured analysis dict."""
    log.info("=" * 60)
    log.info("PROBING: %s (radius %d mi)", location, radius)
    log.info("=" * 60)

    try:
        raw = fetch_all_listings(location, radius)
    except Exception as exc:
        log.error("Failed to fetch %s: %s", location, exc)
        return {"location": location, "error": str(exc)}

    listings = [j for r in raw if (j := parse_listing(r)) is not None]

    if not listings:
        return {
            "location": location,
            "total_raw": len(raw),
            "total_parsed": 0,
            "error": "No store-level listings parsed",
        }

    stores = aggregate_by_store(listings)

    # ── Compute analytics ────────────────────────────────────────
    listing_counts = [s.listing_count for s in stores]
    scores = [s.vacancy_score for s in stores]
    level_counts = Counter(s.vacancy_level for s in stores)

    # Role distribution across entire region
    role_totals = Counter()
    for s in stores:
        for role, count in s.open_roles.items():
            role_totals[role] += count

    # Listing-count distribution (the key question: is it always 2?)
    lc_dist = Counter(listing_counts)

    # Posting age analysis (days since posted)
    now_ts = int(time.time())
    posting_ages_days = []
    for job in listings:
        if job.posted_ts and job.posted_ts > 0:
            age_days = (now_ts - job.posted_ts) / 86400
            posting_ages_days.append(age_days)

    # Stores that deviate from the "standard 2" pattern
    non_standard = [s for s in stores if s.listing_count != 2]
    has_unusual_roles = [
        s for s in stores
        if any(
            role.lower() not in ("barista", "shift supervisor")
            for role in s.open_roles
        )
    ]

    # Role-pair analysis: how many stores have exactly {Barista:1, SS:1}?
    standard_pair_count = sum(
        1 for s in stores
        if (
            s.listing_count == 2
            and s.open_roles.get("Barista", 0) == 1
            and s.open_roles.get("Shift Supervisor", 0) == 1
        )
    )

    result = {
        "location": location,
        "radius": radius,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_raw_positions": len(raw),
        "total_parsed_listings": len(listings),
        "total_stores": len(stores),
        "level_distribution": dict(level_counts),
        "critical_pct": round(level_counts.get("critical", 0) / len(stores) * 100, 1) if stores else 0,
        "listing_count_distribution": {str(k): v for k, v in sorted(lc_dist.items())},
        "listing_count_stats": {
            "min": min(listing_counts),
            "max": max(listing_counts),
            "mean": round(statistics.mean(listing_counts), 2),
            "median": statistics.median(listing_counts),
            "stdev": round(statistics.stdev(listing_counts), 2) if len(listing_counts) > 1 else 0,
        },
        "score_stats": {
            "min": min(scores),
            "max": max(scores),
            "mean": round(statistics.mean(scores), 2),
            "median": statistics.median(scores),
        },
        "role_totals": dict(role_totals.most_common()),
        "unique_roles": sorted(role_totals.keys()),
        "standard_pair_count": standard_pair_count,
        "standard_pair_pct": round(standard_pair_count / len(stores) * 100, 1) if stores else 0,
        "non_standard_stores": [
            {
                "store_num": s.store_num,
                "store_name": s.store_name,
                "listing_count": s.listing_count,
                "open_roles": s.open_roles,
                "vacancy_score": s.vacancy_score,
            }
            for s in non_standard
        ],
        "unusual_role_stores": [
            {
                "store_num": s.store_num,
                "store_name": s.store_name,
                "open_roles": s.open_roles,
            }
            for s in has_unusual_roles
        ],
        "posting_age_stats": {},
    }

    if posting_ages_days:
        result["posting_age_stats"] = {
            "min_days": round(min(posting_ages_days), 1),
            "max_days": round(max(posting_ages_days), 1),
            "mean_days": round(statistics.mean(posting_ages_days), 1),
            "median_days": round(statistics.median(posting_ages_days), 1),
        }

    return result


def print_summary_report(results: list[dict]):
    """Print a human-readable comparison report across all regions."""
    print("\n")
    print("=" * 80)
    print("  MULTI-REGION DATA EXPLORATION REPORT")
    print(f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    print("=" * 80)

    # ── Per-region summary table ─────────────────────────────────
    print("\n── Per-Region Summary ─────────────────────────────────────")
    print(f"{'Region':<25} {'Stores':>6} {'Critical%':>10} {'Std Pair%':>10} "
          f"{'MaxLC':>6} {'Roles':>6}")
    print("─" * 75)

    all_stores = 0
    all_critical = 0
    all_standard = 0
    all_roles = set()
    all_listing_counts = Counter()

    for r in results:
        if "error" in r and r.get("total_stores", 0) == 0:
            print(f"{r['location']:<25} {'ERROR':>6}  {r.get('error', '?')}")
            continue

        total = r["total_stores"]
        crit_pct = r["critical_pct"]
        std_pct = r["standard_pair_pct"]
        max_lc = r["listing_count_stats"]["max"]
        n_roles = len(r["unique_roles"])

        print(f"{r['location']:<25} {total:>6} {crit_pct:>9.1f}% {std_pct:>9.1f}% "
              f"{max_lc:>6} {n_roles:>6}")

        all_stores += total
        all_critical += r["level_distribution"].get("critical", 0)
        all_standard += r["standard_pair_count"]
        all_roles.update(r["unique_roles"])

        for k, v in r["listing_count_distribution"].items():
            all_listing_counts[int(k)] += v

    print("─" * 75)
    if all_stores:
        print(f"{'TOTAL':<25} {all_stores:>6} "
              f"{all_critical/all_stores*100:>9.1f}% "
              f"{all_standard/all_stores*100:>9.1f}%")

    # ── Listing count distribution across all regions ────────────
    print("\n── Listing Count Distribution (all regions combined) ────────")
    print(f"{'Listings/Store':>15} {'Store Count':>12} {'Percentage':>11}")
    print("─" * 42)
    for lc in sorted(all_listing_counts.keys()):
        count = all_listing_counts[lc]
        pct = count / all_stores * 100 if all_stores else 0
        bar = "█" * int(pct / 2)
        print(f"{lc:>15} {count:>12} {pct:>10.1f}%  {bar}")

    # ── All unique roles observed ────────────────────────────────
    print("\n── Unique Roles Observed Across All Regions ────────────────")
    for role in sorted(all_roles):
        total_count = sum(
            r.get("role_totals", {}).get(role, 0) for r in results
        )
        print(f"  {role:<35} {total_count:>6} listings")

    # ── Non-standard stores (deviations from the 2-listing norm) ─
    print("\n── Non-Standard Stores (listing count != 2) ────────────────")
    has_any = False
    for r in results:
        non_std = r.get("non_standard_stores", [])
        if non_std:
            has_any = True
            print(f"\n  {r['location']}:")
            for s in non_std:
                roles_str = ", ".join(f"{k}:{v}" for k, v in s["open_roles"].items())
                print(f"    #{s['store_num']} {s['store_name']:<35} "
                      f"LC={s['listing_count']}  Score={s['vacancy_score']:.1f}  "
                      f"Roles: {roles_str}")
    if not has_any:
        print("  (none found — every store has exactly 2 listings)")

    # ── Unusual roles (not Barista / Shift Supervisor) ───────────
    print("\n── Stores with Unusual Roles (not Barista/Shift Supervisor) ")
    has_unusual = False
    for r in results:
        unusual = r.get("unusual_role_stores", [])
        if unusual:
            has_unusual = True
            print(f"\n  {r['location']}:")
            for s in unusual:
                roles_str = ", ".join(f"{k}:{v}" for k, v in s["open_roles"].items())
                print(f"    #{s['store_num']} {s['store_name']:<35} Roles: {roles_str}")
    if not has_unusual:
        print("  (none found — only Barista and Shift Supervisor across all regions)")

    # ── Posting age analysis ─────────────────────────────────────
    print("\n── Posting Age Analysis ────────────────────────────────────")
    print(f"{'Region':<25} {'Min Days':>9} {'Median':>8} {'Mean':>8} {'Max Days':>9}")
    print("─" * 65)
    for r in results:
        pa = r.get("posting_age_stats", {})
        if pa:
            print(f"{r['location']:<25} {pa['min_days']:>9.1f} {pa['median_days']:>8.1f} "
                  f"{pa['mean_days']:>8.1f} {pa['max_days']:>9.1f}")

    # ── Key findings ─────────────────────────────────────────────
    print("\n── Key Findings ───────────────────────────────────────────")
    if all_stores:
        std_pct = all_standard / all_stores * 100
        crit_pct = all_critical / all_stores * 100
        print(f"  1. {std_pct:.1f}% of stores have the standard pair "
              f"(1 Barista + 1 Shift Supervisor)")
        print(f"  2. {crit_pct:.1f}% of stores score 'critical' under "
              f"the current model")
        print(f"  3. {len(all_roles)} unique role types observed: "
              f"{', '.join(sorted(all_roles))}")

        max_lc_global = max(all_listing_counts.keys()) if all_listing_counts else 0
        if max_lc_global <= 2:
            print(f"  4. CONFIRMED: No store has more than 2 listings. "
                  f"The API caps at 2 per store.")
            print(f"     → The current risk score is binary noise, not a meaningful signal.")
            print(f"     → Scoring must shift to temporal/longitudinal analysis.")
        else:
            stores_gt2 = sum(v for k, v in all_listing_counts.items() if k > 2)
            print(f"  4. {stores_gt2} stores have >2 listings — "
                  f"the cap hypothesis may be WRONG.")
            print(f"     → These deviations could be genuine staffing signals!")

    print("\n" + "=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Multi-region API exploration")
    parser.add_argument(
        "--regions", nargs="+",
        default=DEFAULT_REGIONS,
        help="Regions to probe (default: 8 major US metros)",
    )
    parser.add_argument(
        "--radius", type=int, default=25,
        help="Search radius in miles (default: 25)",
    )
    parser.add_argument(
        "--out", default="scraper/exploration_results.json",
        help="Output file for raw results",
    )
    args = parser.parse_args()

    results = []
    for i, region in enumerate(args.regions):
        if i > 0:
            log.info("Waiting %.0fs between regions…", INTER_REGION_DELAY)
            time.sleep(INTER_REGION_DELAY)
        result = analyze_region(region, args.radius)
        results.append(result)

    # Save raw results
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(results, indent=2))
    log.info("Raw results saved to %s", out_path)

    # Print the summary report
    print_summary_report(results)


if __name__ == "__main__":
    main()
