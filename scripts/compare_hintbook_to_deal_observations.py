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


def build_report(projections_path: Path) -> dict[str, Any]:
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

    status_counter = Counter(row["coverage_status"] for row in brand_rows)
    industry_counter = Counter(
        row["industry_from_vocab"] or row["industry_from_adapter"] or "unknown"
        for row in brand_rows
    )
    return {
        "summary": {
            "hint_book_projections": len(projections),
            "brands_in_hint_book": len(brand_rows),
            "coverage_status_counts": dict(status_counter),
            "industry_counts": dict(industry_counter),
        },
        "brands": brand_rows,
    }


def _print_human_report(report: dict[str, Any]) -> None:
    s = report["summary"]
    logger.info("=" * 72)
    logger.info("HINTBOOK COVERAGE vs COLLECTED DEALS")
    logger.info("=" * 72)
    logger.info("Hint-book projections: %d", s["hint_book_projections"])
    logger.info("Brands in hint book  : %d", s["brands_in_hint_book"])
    logger.info("Status counts        : %s", s["coverage_status_counts"])
    logger.info("Industries           : %s", s["industry_counts"])
    logger.info("")
    logger.info("Per-brand:")
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
        for sample in row["hint_book"]["sample_headlines"][:1]:
            logger.info("      hint-book: %s", (sample or "")[:120])
        for sample in row["collected"]["sample_observations"][:1]:
            logger.info(
                "      collected: %s [src=%s review=%s]",
                (sample.get("deal_name") or "")[:120],
                sample.get("source"),
                sample.get("review_state"),
            )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projections", type=Path, default=DEFAULT_HARVEST_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--json", action="store_true", help="Print full JSON report to stdout")
    args = parser.parse_args()

    if not args.projections.exists():
        logger.error("Projections not found: %s", args.projections)
        logger.error("Run scripts/harvest_hintbook_from_spiritpool.py first.")
        return 2

    report = build_report(args.projections)
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
