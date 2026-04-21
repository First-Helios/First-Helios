#!/usr/bin/env python3
"""Extract hintbook proposals from Spirit Pool dev-capture bundles.

Reads the signed page captures written by the /api/spiritpool/dev/page-capture
route (JSON bundles under data/cache/spiritpool_dev/page_captures/) and runs
each one through the matching hintbook aggregator adapter's parse path. No
live HTTP happens here.

Outputs
-------
data/cache/hintbook/spiritpool_runs/<stamp>/harvest_report.json
    Full hintbook HarvestReport JSON (AggregatorRecords + HintProposals +
    ExpectationProposals).

data/cache/hintbook/spiritpool_runs/<stamp>/brand_industry_index.json
    Aggregated index: { industries: {food: [...brands...]},
                        brands: {applebees: {records:N, hosts:[...]}} }.

data/cache/hintbook/spiritpool_runs/<stamp>/expectation_proposals.json
    Minimal, schema-aligned expectation rows ready to be merged into
    config/meal_deal_expectation_registry.json after human review.

data/cache/hintbook/spiritpool_runs/latest/...
    Mirror of the latest run for quick downstream consumption.

This script is replay-only and quality-check-only. Its outputs are never
first-party evidence (per collectors/hintbook/__init__.py).
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

from collectors.hintbook.adapters import (
    bitehunter,
    dealnews,
    eatdrinkdeals,
    fooddealnow,
    hip2save,
    kcl,
    retailmenot,
    slickdeals,
)
from collectors.hintbook.brand_matcher import (
    BrandMatch,
    load_brand_vocab_from_db,
    match_brand_in_text,
)
from collectors.hintbook.listing_walker import (
    derive_proposals_from_record,
    parse_article_html,
)
from collectors.hintbook.models import (
    AggregatorRecord,
    ExpectationProposal,
    HarvestReport,
    HintProposal,
    utcnow,
)
from config.paths import CACHE_DIR

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_BUNDLE_DIR = CACHE_DIR / "spiritpool_dev" / "page_captures"
DEFAULT_OUT_DIR = CACHE_DIR / "hintbook" / "spiritpool_runs"

# Host token → (adapter module, industry). Tokens are matched as substrings
# against the canonical_url host so variants (www., m., regional prefixes)
# all route to the same adapter.
_HOST_ROUTES = [
    ("eatdrinkdeals.com", eatdrinkdeals, "food"),
    ("retailmenot.com", retailmenot, "food"),
    ("slickdeals.net", slickdeals, "food"),
    ("bitehunter.com", bitehunter, "food"),
    ("dealnews.com", dealnews, "broader"),
    ("fooddealnow.com", fooddealnow, "food"),
    ("hip2save.com", hip2save, "food"),
    ("thekrazycouponlady.com", kcl, "broader"),
]


def _route_for(url: str) -> tuple[Any, str, str] | None:
    """Return (adapter_module, host_token, industry) or None for skipped hosts."""
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for token, adapter, industry in _HOST_ROUTES:
        if token in host:
            return adapter, token, industry
    return None


def _load_bundle(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("bad bundle %s: %s", path.name, exc)
        return None


def _promote_record_freshness(rec: AggregatorRecord, captured_at: datetime) -> AggregatorRecord:
    # Keep Spirit Pool capture time so downstream expectations know when we
    # actually observed the claim. fetched_at is what the hintbook walker
    # sets from utcnow(); we overwrite with the bundle's captured_at.
    return replace(rec, fetched_at=captured_at)


def _retighten_brand_hint(rec: AggregatorRecord, match: BrandMatch | None) -> AggregatorRecord:
    if match is None:
        # Strict mode: if the brand vocabulary doesn't recognise it, drop the
        # weak headline-prefix slug so downstream joins don't false-positive.
        if rec.brand_hint is None:
            return rec
        return replace(rec, brand_hint=None)
    return replace(rec, brand_hint=match.slug)


def _aggregator_to_dealsignal_shape(rec: AggregatorRecord) -> dict[str, Any]:
    """Project an AggregatorRecord into the DealSignal field vocabulary.

    This is the cohesion layer between the hint book (what competitors say
    should exist) and our collected deals (DealSignal). It does NOT claim
    the aggregator text IS a deal — it only renders the claim into a shape
    that can be compared field-for-field against deal_observations.
    """
    flags = set(rec.flags or ())
    deal_type: str | None = None
    if "bogo" in flags:
        deal_type = "bogo"
    elif "happy_hour" in flags:
        deal_type = "happy_hour"
    elif "kids_eat_free" in flags or "kids eat free" in (rec.headline + rec.body_excerpt).lower():
        deal_type = "kids_eat_free"
    elif "free_item" in flags:
        deal_type = "daily_special"
    else:
        lower = f"{rec.headline} {rec.body_excerpt}".lower()
        if "lunch" in lower and "special" in lower:
            deal_type = "lunch_special"
        elif "combo" in lower or "bundle" in lower:
            deal_type = "combo"

    price_type: str | None = None
    discount_percentage: float | None = None
    if "percent_off" in flags:
        price_type = "percentage_off"
        import re as _re
        m = _re.search(r"(\d{1,3})\s?%\s?off", f"{rec.headline} {rec.body_excerpt}", _re.IGNORECASE)
        if m:
            try:
                discount_percentage = float(m.group(1))
            except ValueError:
                pass
    elif rec.price_hint is not None:
        price_type = "absolute"

    return {
        "deal_name": rec.headline[:200],
        "deal_description": rec.body_excerpt[:500] if rec.body_excerpt else None,
        "deal_type": deal_type,
        "price": rec.price_hint,
        "price_type": price_type,
        "discount_percentage": discount_percentage,
        "promo_code": rec.promo_code,
        "end_date": rec.valid_through.isoformat() if rec.valid_through else None,
        "source": f"hintbook_{rec.aggregator}",
        "source_url": rec.source_url,
        "raw_flags": sorted(flags),
    }


def harvest(bundle_dir: Path, *, strict_brand: bool = True) -> tuple[HarvestReport, list[dict[str, Any]]]:
    """Parse every bundle; return (report, dealsignal_projections).

    dealsignal_projections[i] matches report.records[i] one-for-one.
    """
    report = HarvestReport(adapters_run=[])
    adapters_seen: set[str] = set()
    skipped: list[dict[str, Any]] = []
    projections: list[dict[str, Any]] = []
    brand_matches: list[BrandMatch | None] = []

    vocab = load_brand_vocab_from_db() if strict_brand else []
    logger.info("Loaded brand vocabulary: %d entries", len(vocab))

    bundles = sorted(bundle_dir.glob("*.json"))
    logger.info("Scanning %d bundles under %s", len(bundles), bundle_dir)

    for path in bundles:
        bundle = _load_bundle(path)
        if not bundle:
            continue

        url = bundle.get("canonical_url") or bundle.get("url")
        html = bundle.get("html")
        if not url or not isinstance(html, str) or not html.strip():
            skipped.append({"bundle": path.name, "reason": "missing_url_or_html"})
            continue

        route = _route_for(url)
        if route is None:
            skipped.append({"bundle": path.name, "reason": f"unrouted_host:{urlparse(url).netloc}"})
            continue
        adapter, host_token, industry = route

        captured_raw = bundle.get("captured_at")
        captured_at = utcnow()
        if isinstance(captured_raw, str):
            try:
                captured_at = datetime.fromisoformat(captured_raw.replace("Z", "+00:00"))
                if captured_at.tzinfo is None:
                    captured_at = captured_at.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        rec = parse_article_html(
            html=html,
            article_url=url,
            aggregator_name=adapter.NAME,
            aggregator_host=host_token,
            industry=industry,
        )
        if rec is None:
            skipped.append({"bundle": path.name, "reason": "parse_returned_none"})
            continue

        rec = _promote_record_freshness(rec, captured_at)

        # Strict brand matching via DB vocabulary overrides the weak
        # headline-prefix slug produced by parsing.normalize_brand_hint.
        match = match_brand_in_text(headline=rec.headline, body=rec.body_excerpt, vocab=vocab) if vocab else None
        rec = _retighten_brand_hint(rec, match)

        if strict_brand and match is None:
            skipped.append({"bundle": path.name, "reason": "no_vocab_brand_match", "headline": rec.headline[:120]})
            continue

        report.records.append(rec)
        brand_matches.append(match)
        projections.append(_aggregator_to_dealsignal_shape(rec))

        hint, expectation = derive_proposals_from_record(rec)
        if hint:
            report.hint_proposals.append(hint)
        if expectation:
            report.expectation_proposals.append(expectation)

        adapters_seen.add(adapter.NAME)

    report.adapters_run = sorted(adapters_seen)
    report.adapters_failed = skipped
    report.finished_at = utcnow()
    return report, projections


def build_brand_industry_index(report: HarvestReport) -> dict[str, Any]:
    industries: dict[str, set[str]] = defaultdict(set)
    brands: dict[str, dict[str, Any]] = {}

    for rec in report.records:
        if rec.brand_hint:
            industries[rec.industry].add(rec.brand_hint)
            entry = brands.setdefault(
                rec.brand_hint,
                {
                    "industry": rec.industry,
                    "record_count": 0,
                    "aggregators": Counter(),
                    "target_domains": set(),
                    "flags": Counter(),
                    "first_seen": rec.fetched_at.isoformat(),
                    "latest_headline": rec.headline,
                    "price_hints": [],
                    "promo_codes": set(),
                },
            )
            entry["record_count"] += 1
            entry["aggregators"][rec.aggregator] += 1
            if rec.target_domain:
                entry["target_domains"].add(rec.target_domain)
            for flag in rec.flags:
                entry["flags"][flag] += 1
            if rec.price_hint is not None:
                entry["price_hints"].append(rec.price_hint)
            if rec.promo_code:
                entry["promo_codes"].add(rec.promo_code)

    serial_brands = {
        brand: {
            "industry": v["industry"],
            "record_count": v["record_count"],
            "aggregators": dict(v["aggregators"]),
            "target_domains": sorted(v["target_domains"]),
            "flags": dict(v["flags"]),
            "first_seen": v["first_seen"],
            "latest_headline": v["latest_headline"][:200],
            "price_hints": sorted(v["price_hints"]),
            "promo_codes": sorted(v["promo_codes"]),
        }
        for brand, v in brands.items()
    }

    return {
        "industries": {k: sorted(v) for k, v in industries.items()},
        "industry_counts": {k: len(v) for k, v in industries.items()},
        "brands": serial_brands,
        "totals": {
            "records": len(report.records),
            "hint_proposals": len(report.hint_proposals),
            "expectation_proposals": len(report.expectation_proposals),
            "brands": len(serial_brands),
            "industries": len(industries),
        },
    }


def build_expectation_rows(report: HarvestReport, *, ttl_days: int) -> list[dict[str, Any]]:
    """Convert ExpectationProposal → registry.v1 row shape (first_seen/last_verified/expires_at)."""
    today = date.today()
    expires = today.replace(year=today.year) + (date(today.year, today.month, today.day) - today)
    # Simple TTL: today + ttl_days via timedelta
    from datetime import timedelta

    expires = today + timedelta(days=ttl_days)

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for proposal in report.expectation_proposals:
        key = (proposal.brand, proposal.target_domain, proposal.expected_label.strip())
        if key in seen:
            continue
        seen.add(key)

        slug = ""
        hint_path = next(iter(proposal.page_path_hints), None)
        if hint_path:
            slug = hint_path.strip("/").replace("/", "_") or "root"
        else:
            slug = "root"
        exp_id = f"spdev_{proposal.source}_{proposal.brand}_{slug}"[:80]

        rows.append(
            {
                "id": exp_id,
                "brand": proposal.brand,
                "target_domain": proposal.target_domain,
                "expected_label": proposal.expected_label,
                "source": proposal.source,
                "source_url": proposal.source_url,
                "first_seen": proposal.first_seen.isoformat(),
                "last_verified": today.isoformat(),
                "expires_at": expires.isoformat(),
                "page_path_hints": list(proposal.page_path_hints),
                "match_any": list(proposal.match_any),
                "notes": proposal.notes,
            }
        )
    return rows


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle-dir", type=Path, default=DEFAULT_BUNDLE_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument(
        "--ttl-days",
        type=int,
        default=90,
        help="Expiration horizon for emitted expectation rows (default: 90d = max_age_days policy)",
    )
    parser.add_argument(
        "--no-strict-brand",
        action="store_true",
        help="Skip DB brand-vocabulary match (keeps headline-slug brands, noisier but tolerant)",
    )
    parser.add_argument("--print-brands", action="store_true")
    args = parser.parse_args()

    if not args.bundle_dir.exists():
        logger.error("Bundle dir not found: %s", args.bundle_dir)
        return 2

    report, projections = harvest(args.bundle_dir, strict_brand=not args.no_strict_brand)
    index = build_brand_industry_index(report)
    expectation_rows = build_expectation_rows(report, ttl_days=args.ttl_days)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.out_dir / stamp
    latest_dir = args.out_dir / "latest"

    for target_dir in (run_dir, latest_dir):
        _write_json(target_dir / "harvest_report.json", report.to_json())
        _write_json(target_dir / "brand_industry_index.json", index)
        _write_json(
            target_dir / "expectation_proposals.json",
            {
                "schema_version": "expectation_registry.v1",
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "source_bundle_dir": str(args.bundle_dir),
                "expectations": expectation_rows,
            },
        )
        _write_json(
            target_dir / "deal_signal_projections.json",
            {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "note": (
                    "One-to-one projection of each AggregatorRecord into the "
                    "DealSignal field vocabulary. Quality-check-only. Never first-party evidence."
                ),
                "projections": [
                    {**proj, "brand_slug": rec.brand_hint, "target_domain": rec.target_domain,
                     "aggregator": rec.aggregator, "industry": rec.industry}
                    for proj, rec in zip(projections, report.records)
                ],
            },
        )

    logger.info("")
    logger.info("=" * 72)
    logger.info("HINTBOOK \u2192 SPIRITPOOL HARVEST")
    logger.info("=" * 72)
    logger.info("Bundle dir      : %s", args.bundle_dir)
    logger.info("Run dir         : %s", run_dir)
    logger.info("Adapters touched: %s", ", ".join(report.adapters_run) or "(none)")
    logger.info("Records         : %d", len(report.records))
    logger.info("Hint proposals  : %d", len(report.hint_proposals))
    logger.info("Expectation rows: %d", len(expectation_rows))
    logger.info("Brands indexed  : %d across %d industries", index["totals"]["brands"], index["totals"]["industries"])
    logger.info("Bundles skipped : %d", len(report.adapters_failed))
    for skip in report.adapters_failed[:10]:
        tail = f" :: {skip['headline']}" if "headline" in skip else ""
        logger.info("  - %s: %s%s", skip["bundle"], skip["reason"], tail)

    if args.print_brands:
        logger.info("")
        logger.info("Brand coverage (from hint book):")
        for brand, data in sorted(index["brands"].items(), key=lambda kv: -kv[1]["record_count"]):
            domains = ",".join(data["target_domains"]) or "-"
            aggs = ",".join(data["aggregators"])
            prices = ",".join(f"${p}" for p in data["price_hints"]) or "-"
            codes = ",".join(data["promo_codes"]) or "-"
            flags = ",".join(sorted(data["flags"])) or "-"
            logger.info(
                "  %-22s ind=%-8s n=%d aggs=%s domains=%s prices=%s codes=%s flags=%s",
                brand, data["industry"], data["record_count"], aggs, domains, prices, codes, flags,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
