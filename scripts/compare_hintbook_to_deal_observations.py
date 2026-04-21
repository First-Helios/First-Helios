#!/usr/bin/env python3
"""Compare hintbook harvest (Spirit Pool bundles) against collected deals.

For each brand the hint book identified, query the local DB and report:

  hint_book_records      : aggregator claims we extracted for this brand
  brand_group_matches    : brand_groups rows resolved by canonical_name
  linked_sites           : site_identities tied to those brand_groups via site_assignments
  deal_observations      : total DealObservation rows for those sites
  website_scrape_obs     : same, filtered to source='website_scrape'
  active_materializations: is_active=true DealMaterialization rows
  coverage_status        : one of {'missing','partial','covered'}

The report also surfaces industries the hint book covers and flags
brands present in the hint book that have no matching brand_group at
all (brand-onboarding gap) versus brands with brand_groups but zero
deals (extraction gap).

Never treats hintbook records as first-party evidence. Output is a JSON
audit artifact and a human-readable summary.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import os

from config.paths import CACHE_DIR

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_HARVEST_PATH = CACHE_DIR / "hintbook" / "spiritpool_runs" / "latest" / "deal_signal_projections.json"
DEFAULT_OUTPUT_PATH = CACHE_DIR / "hintbook" / "spiritpool_runs" / "latest" / "coverage_report.json"
DEFAULT_MANIFEST_PATH = Path(__file__).resolve().parents[1] / "config" / "spiritpool_capture_manifest.json"

_PARTIAL_THRESHOLD = 3


def _connect():
    import psycopg
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    if not dsn:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(dsn)


def _load_projections(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("projections", []))


def _group_by_brand(projections: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Aggregate projections by brand_canonical (falls back to brand_slug)."""
    groups: dict[str, dict[str, Any]] = {}
    for p in projections:
        key = p.get("brand_canonical") or p.get("brand_slug") or "(unknown)"
        bucket = groups.setdefault(
            key,
            {
                "brand_canonical": p.get("brand_canonical"),
                "brand_slug": p.get("brand_slug"),
                "industry_vocab": p.get("brand_industry_vocab"),
                "industry_adapter": p.get("industry"),
                "aggregators": Counter(),
                "record_count": 0,
                "sample_headlines": [],
                "target_domains": set(),
                "flags": Counter(),
                "prices": [],
                "promo_codes": set(),
            },
        )
        bucket["record_count"] += 1
        bucket["aggregators"][p.get("aggregator")] += 1
        if len(bucket["sample_headlines"]) < 3:
            bucket["sample_headlines"].append(p.get("deal_name"))
        if p.get("target_domain"):
            bucket["target_domains"].add(p["target_domain"])
        for flag in p.get("raw_flags") or []:
            bucket["flags"][flag] += 1
        if p.get("price") is not None:
            bucket["prices"].append(p["price"])
        if p.get("promo_code"):
            bucket["promo_codes"].add(p["promo_code"])
    # Finalize sets → sorted lists for JSON
    for bucket in groups.values():
        bucket["aggregators"] = dict(bucket["aggregators"])
        bucket["target_domains"] = sorted(bucket["target_domains"])
        bucket["flags"] = dict(bucket["flags"])
        bucket["promo_codes"] = sorted(bucket["promo_codes"])
    return groups


def _resolve_brand_groups(conn, canonical_name: str) -> list[dict[str, Any]]:
    """Find brand_groups with a canonical_name matching (case-insensitive, strict)."""
    if not canonical_name:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, canonical_name, industry, location_count
            FROM brand_groups
            WHERE lower(canonical_name) = lower(%s)
            """,
            (canonical_name,),
        )
        rows = cur.fetchall()
    return [
        {"id": r[0], "canonical_name": r[1], "industry": r[2], "location_count": r[3]}
        for r in rows
    ]


def _brand_coverage(conn, brand_group_ids: list[int]) -> dict[str, Any]:
    if not brand_group_ids:
        return {
            "linked_sites": 0,
            "deal_observations": 0,
            "website_scrape_obs": 0,
            "active_materializations": 0,
            "sample_observations": [],
        }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COUNT(DISTINCT site_identity_id)
            FROM site_assignments
            WHERE brand_group_id = ANY(%s)
            """,
            (brand_group_ids,),
        )
        linked_sites = cur.fetchone()[0] or 0

        cur.execute(
            """
            SELECT COUNT(*)
            FROM deal_observations obs
            JOIN site_assignments sa ON sa.site_identity_id = obs.site_identity_id
            WHERE sa.brand_group_id = ANY(%s)
            """,
            (brand_group_ids,),
        )
        deal_obs = cur.fetchone()[0] or 0

        cur.execute(
            """
            SELECT COUNT(*)
            FROM deal_observations obs
            JOIN site_assignments sa ON sa.site_identity_id = obs.site_identity_id
            WHERE sa.brand_group_id = ANY(%s)
              AND obs.source = 'website_scrape'
            """,
            (brand_group_ids,),
        )
        ws_obs = cur.fetchone()[0] or 0

        cur.execute(
            """
            SELECT COUNT(*)
            FROM deal_materializations
            WHERE brand_group_id = ANY(%s)
              AND is_active = true
            """,
            (brand_group_ids,),
        )
        active_mat = cur.fetchone()[0] or 0

        cur.execute(
            """
            SELECT obs.deal_name, obs.deal_type, obs.price, obs.price_type,
                   obs.source, obs.review_state, si.host
            FROM deal_observations obs
            JOIN site_assignments sa ON sa.site_identity_id = obs.site_identity_id
            JOIN site_identities si ON si.id = obs.site_identity_id
            WHERE sa.brand_group_id = ANY(%s)
            ORDER BY obs.observed_at DESC NULLS LAST
            LIMIT 5
            """,
            (brand_group_ids,),
        )
        samples = [
            {
                "deal_name": r[0],
                "deal_type": r[1],
                "price": r[2],
                "price_type": r[3],
                "source": r[4],
                "review_state": r[5],
                "host": r[6],
            }
            for r in cur.fetchall()
        ]

    return {
        "linked_sites": linked_sites,
        "deal_observations": deal_obs,
        "website_scrape_obs": ws_obs,
        "active_materializations": active_mat,
        "sample_observations": samples,
    }


def _coverage_status(cov: dict[str, Any]) -> str:
    active = cov["active_materializations"]
    if active == 0:
        return "missing"
    if active < _PARTIAL_THRESHOLD:
        return "partial"
    return "covered"


def _industry_rollup(conn, brand_rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Group coverage by industry and compute match rates at that grain.

    The premise: Austin is a major metro, so every industry the hint book
    touches should have matching brand_groups with Austin employers. A low
    brand-level match rate alongside a high industry-level match rate means
    we're looking at a "brand depth" gap, not a "whole industry is missing"
    gap.
    """
    per_industry: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "hintbook_brand_count": 0,
            "brands_with_brand_group": 0,
            "brands_with_any_deal_observation": 0,
            "brands_with_active_materialization": 0,
            "total_deal_observations": 0,
            "total_active_materializations": 0,
        }
    )
    for row in brand_rows:
        industry = row["industry_from_vocab"] or row["industry_from_adapter"] or "unknown"
        stat = per_industry[industry]
        stat["hintbook_brand_count"] += 1
        if row["collected"]["brand_groups"]:
            stat["brands_with_brand_group"] += 1
        if row["collected"]["deal_observations"] > 0:
            stat["brands_with_any_deal_observation"] += 1
        if row["collected"]["active_materializations"] > 0:
            stat["brands_with_active_materialization"] += 1
        stat["total_deal_observations"] += row["collected"]["deal_observations"]
        stat["total_active_materializations"] += row["collected"]["active_materializations"]

    # Attach Austin infrastructure sizing per industry as a denominator
    # (so the "collected deals per 100 Austin employers" ratio is legible).
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT bg.industry,
                   COUNT(DISTINCT le.id) AS austin_employers,
                   COUNT(DISTINCT bg.id) AS austin_brands
            FROM local_employers le
            JOIN brand_groups bg ON bg.id = le.brand_group_id
            WHERE le.region = 'austin_tx' AND le.is_active IS TRUE
            GROUP BY bg.industry
            """
        )
        austin_stats = {r[0] or "unknown": {"austin_employers": r[1], "austin_brands": r[2]} for r in cur.fetchall()}

    rollup: list[dict[str, Any]] = []
    for industry, stat in sorted(per_industry.items()):
        row = dict(stat)
        row["industry"] = industry
        row.update(austin_stats.get(industry, {"austin_employers": 0, "austin_brands": 0}))
        hb = row["hintbook_brand_count"] or 1
        row["industry_match_rate"] = round(row["brands_with_brand_group"] / hb, 3)
        row["deal_match_rate"] = round(row["brands_with_any_deal_observation"] / hb, 3)
        rollup.append(row)
    return {"per_industry": rollup}


def _seed_manifest_gap(conn, manifest_path: Path, projections: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare the seed capture manifest to what the hint-book harvest covered.

    For every brand listed in config/spiritpool_capture_manifest.json, check
    whether the hint-book currently has records for it. This is the
    "what should I capture next?" to-do for the Spirit Pool dev operator.
    """
    if not manifest_path.exists():
        return {"available": False, "manifest_path": str(manifest_path)}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    covered_canonical = {
        (p.get("brand_canonical") or "").strip().lower()
        for p in projections
        if p.get("brand_canonical")
    }

    industries: list[dict[str, Any]] = []
    with conn.cursor() as cur:
        for category in manifest.get("categories", []):
            industry = category.get("industry")
            entries: list[dict[str, Any]] = []
            for target in category.get("targets", []):
                brand = target["brand"]
                # Tolerant match: exact first, then prefix (e.g. "Dunkin'" -> "Dunkin' Donuts",
                # "CVS" -> "CVS Pharmacy"). Only fall back to prefix when exact misses.
                cur.execute(
                    "SELECT id, canonical_name, industry, location_count FROM brand_groups "
                    "WHERE canonical_name ILIKE %s ORDER BY location_count DESC LIMIT 1",
                    (brand,),
                )
                bg = cur.fetchone()
                if not bg:
                    cur.execute(
                        "SELECT id, canonical_name, industry, location_count FROM brand_groups "
                        "WHERE canonical_name ILIKE %s ORDER BY location_count DESC LIMIT 1",
                        (brand + "%",),
                    )
                    bg = cur.fetchone()
                covered = brand.strip().lower() in covered_canonical
                entries.append({
                    "brand": brand,
                    "brand_group_present": bg is not None,
                    "matched_canonical_name": bg[1] if bg else None,
                    "brand_group_industry": bg[2] if bg else None,
                    "brand_group_location_count": bg[3] if bg else 0,
                    "hintbook_covered": covered,
                    "capture_urls": target["urls"],
                    "status": "covered" if covered else ("brand_onboarded_awaiting_capture" if bg else "brand_not_onboarded"),
                })
            industries.append({
                "industry": industry,
                "priority": category.get("priority"),
                "reason": category.get("reason"),
                "brands": entries,
                "covered_count": sum(1 for e in entries if e["hintbook_covered"]),
                "total_count": len(entries),
            })

    total_targets = sum(ind["total_count"] for ind in industries)
    total_covered = sum(ind["covered_count"] for ind in industries)
    return {
        "available": True,
        "manifest_path": str(manifest_path),
        "industries": industries,
        "summary": {
            "total_targets": total_targets,
            "covered": total_covered,
            "remaining": total_targets - total_covered,
        },
    }


def build_report(projections_path: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    projections = _load_projections(projections_path)
    grouped = _group_by_brand(projections)

    brand_rows: list[dict[str, Any]] = []
    with _connect() as conn:
        for key, bucket in sorted(grouped.items()):
            brand_groups = _resolve_brand_groups(conn, bucket["brand_canonical"] or "")
            brand_group_ids = [bg["id"] for bg in brand_groups]
            coverage = _brand_coverage(conn, brand_group_ids)
            status = "unknown_brand" if not brand_group_ids else _coverage_status(coverage)
            brand_rows.append({
                "brand_key": key,
                "brand_canonical": bucket["brand_canonical"],
                "brand_slug": bucket["brand_slug"],
                "industry_from_vocab": bucket["industry_vocab"],
                "industry_from_adapter": bucket["industry_adapter"],
                "hint_book": {
                    "record_count": bucket["record_count"],
                    "aggregators": bucket["aggregators"],
                    "sample_headlines": bucket["sample_headlines"],
                    "target_domains": bucket["target_domains"],
                    "flags": bucket["flags"],
                    "prices": bucket["prices"],
                    "promo_codes": bucket["promo_codes"],
                },
                "collected": {
                    "brand_groups": brand_groups,
                    **coverage,
                },
                "coverage_status": status,
            })

        industry = _industry_rollup(conn, brand_rows)
        seed_gap = _seed_manifest_gap(conn, manifest_path or DEFAULT_MANIFEST_PATH, projections)

    status_counter = Counter(row["coverage_status"] for row in brand_rows)
    industry_counter = Counter(
        row["industry_from_vocab"] or row["industry_from_adapter"] or "unknown"
        for row in brand_rows
    )

    industry_match_overall = None
    if brand_rows:
        industry_match_overall = round(
            sum(1 for r in brand_rows if r["collected"]["brand_groups"]) / len(brand_rows), 3
        )

    return {
        "summary": {
            "hint_book_projections": len(projections),
            "brands_in_hint_book": len(brand_rows),
            "coverage_status_counts": dict(status_counter),
            "industry_counts": dict(industry_counter),
            "industry_match_rate_overall": industry_match_overall,
        },
        "industry_rollup": industry,
        "seed_manifest_gap": seed_gap,
        "brands": brand_rows,
    }


def _print_human_report(report: dict[str, Any]) -> None:
    s = report["summary"]
    logger.info("=" * 72)
    logger.info("HINTBOOK COVERAGE vs COLLECTED DEALS")
    logger.info("=" * 72)
    logger.info("Hint-book projections     : %d", s["hint_book_projections"])
    logger.info("Brands in hint book       : %d", s["brands_in_hint_book"])
    logger.info("Industry match rate (ind) : %s   (share of hint-book brands with a brand_group)",
                s.get("industry_match_rate_overall"))
    logger.info("Status counts             : %s", s["coverage_status_counts"])
    logger.info("Industries touched        : %s", s["industry_counts"])

    logger.info("")
    logger.info("Industry rollup:")
    logger.info("  %-22s %4s %4s %7s %7s %11s %11s",
                "industry", "hb", "bg", "obs_brd", "mat_brd", "ind_match", "deal_match")
    for row in report["industry_rollup"]["per_industry"]:
        logger.info(
            "  %-22s %4d %4d %7d %7d %11s %11s",
            row["industry"][:22],
            row["hintbook_brand_count"],
            row["brands_with_brand_group"],
            row["brands_with_any_deal_observation"],
            row["brands_with_active_materialization"],
            f"{row['industry_match_rate']:.0%}",
            f"{row['deal_match_rate']:.0%}",
        )

    gap = report.get("seed_manifest_gap", {})
    if gap.get("available"):
        g = gap["summary"]
        logger.info("")
        logger.info("Seed manifest gap: %d / %d targets covered; %d remaining",
                    g["covered"], g["total_targets"], g["remaining"])
        for ind in gap["industries"]:
            logger.info("  [%s] %-22s covered=%d/%d",
                        ind.get("priority") or "--",
                        (ind.get("industry") or "")[:22],
                        ind["covered_count"], ind["total_count"])
            for b in ind["brands"]:
                mark = "OK" if b["hintbook_covered"] else ("QUEUED" if b["brand_group_present"] else "NO_BRAND")
                logger.info("      %-8s %-28s bg_loc=%-4d urls=%d  status=%s",
                            mark, b["brand"][:28], b["brand_group_location_count"],
                            len(b["capture_urls"]), b["status"])

    logger.info("")
    logger.info("Per-brand (hint-book present):")
    for row in sorted(
        report["brands"],
        key=lambda r: (r["coverage_status"], -r["hint_book"]["record_count"]),
    ):
        logger.info(
            "  [%-13s] %-28s hintbook=%d aggs=%s | obs=%d ws_obs=%d active_mat=%d sites=%d bgroups=%d",
            row["coverage_status"],
            (row["brand_canonical"] or row["brand_key"])[:28],
            row["hint_book"]["record_count"],
            ",".join(row["hint_book"]["aggregators"]),
            row["collected"]["deal_observations"],
            row["collected"]["website_scrape_obs"],
            row["collected"]["active_materializations"],
            row["collected"]["linked_sites"],
            len(row["collected"]["brand_groups"]),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projections", type=Path, default=DEFAULT_HARVEST_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH,
                        help="Seed capture manifest. Default: config/spiritpool_capture_manifest.json")
    parser.add_argument("--json", action="store_true", help="Print full JSON report to stdout")
    args = parser.parse_args()

    if not args.projections.exists():
        logger.error("Projections not found: %s", args.projections)
        logger.error("Run scripts/harvest_hintbook_from_spiritpool.py first.")
        return 2

    report = build_report(args.projections, manifest_path=args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str), encoding="utf-8")

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, default=str))
    else:
        _print_human_report(report)
    logger.info("")
    logger.info("Report written: %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
