#!/usr/bin/env python3
"""Summarize website scrape audit snapshots and replay bundles.

Reads the synced audit JSON and the replayable debug bundle directory to
produce a repeatable snapshot of what the website scraper is doing well and
where signals are being lost.

Outputs:
  - success rate and outcome counts
  - no-deal failure taxonomy
  - domain-family counts and top hosts
  - shared-URL stats
  - JSON-LD and PDF prevalence
  - page fetch-type counts and page-count histogram

Usage:
  PYTHONPATH=. python scripts/summarize_website_scrape_audit.py
  PYTHONPATH=. python scripts/summarize_website_scrape_audit.py --json
  PYTHONPATH=. python scripts/summarize_website_scrape_audit.py --top-hosts 15
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collectors.meal_deals.website_scrape_audit_utils import (
    DEFAULT_AUDIT_PATH,
    DEFAULT_DEBUG_DIR,
    classify_domain_family,
    classify_no_deal_stage,
    load_audit_entries,
    load_debug_bundles,
    page_has_jsonld,
)

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _safe_percent(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


def build_report(audit_entries: list[dict[str, Any]], debug_bundles: dict[str, dict[str, Any]], invalid_bundle_json: int) -> dict[str, Any]:
    outcome_counts: Counter[str] = Counter()
    no_deal_taxonomy: Counter[str] = Counter()
    family_counts: Counter[str] = Counter()
    family_by_outcome: dict[str, Counter[str]] = defaultdict(Counter)
    host_counts: Counter[str] = Counter()
    host_by_outcome: dict[str, Counter[str]] = defaultdict(Counter)

    shared_url_sites = 0
    shared_url_success = 0
    shared_url_no_deals = 0
    alias_rows_collapsed = 0
    shared_url_group_sizes: list[int] = []

    audit_by_key: dict[str, dict[str, Any]] = {}

    for entry in audit_entries:
        outcome = str(entry.get("outcome") or "missing")
        outcome_counts[outcome] += 1

        url = str(entry.get("url") or "")
        host = urlparse(url).netloc.lower() or "unknown"
        family = classify_domain_family(url)
        family_counts[family] += 1
        family_by_outcome[outcome][family] += 1
        host_counts[host] += 1
        host_by_outcome[outcome][host] += 1

        if outcome == "no_deals":
            no_deal_taxonomy[classify_no_deal_stage(entry)] += 1

        locations_sharing_url = int(entry.get("locations_sharing_url") or 0)
        if locations_sharing_url > 1:
            shared_url_sites += 1
            shared_url_group_sizes.append(locations_sharing_url)
            if outcome == "deals_found":
                shared_url_success += 1
            elif outcome == "no_deals":
                shared_url_no_deals += 1

        if int(entry.get("alias_rows_collapsed") or 0) > 0:
            alias_rows_collapsed += 1

        debug_cache_key = entry.get("debug_cache_key")
        if isinstance(debug_cache_key, str) and debug_cache_key:
            audit_by_key[debug_cache_key] = entry

    bundle_outcome_counts: Counter[str] = Counter()
    bundle_jsonld_site_counts: Counter[str] = Counter()
    bundle_pdf_link_counts: Counter[str] = Counter()
    bundle_pdf_text_counts: Counter[str] = Counter()
    bundle_discovered_page_counts: Counter[str] = Counter()
    bundle_menu_avg_counts: Counter[str] = Counter()
    page_fetch_type_counts: Counter[str] = Counter()
    page_count_histogram: Counter[int] = Counter()

    for site_key, bundle in debug_bundles.items():
        audit_entry = audit_by_key.get(site_key)
        outcome = str((audit_entry or {}).get("outcome") or "not_in_audit")
        bundle_outcome_counts[outcome] += 1

        pages = bundle.get("pages") if isinstance(bundle.get("pages"), dict) else {}
        pdfs = bundle.get("pdfs") if isinstance(bundle.get("pdfs"), dict) else {}
        pdf_links = bundle.get("pdf_links") if isinstance(bundle.get("pdf_links"), list) else []
        discovered_pages = bundle.get("discovered_pages") if isinstance(bundle.get("discovered_pages"), list) else []

        page_count_histogram[len(pages)] += 1

        has_jsonld = False
        for page in pages.values():
            if not isinstance(page, dict):
                continue
            fetch_type = str(page.get("fetch_type") or "unknown")
            page_fetch_type_counts[fetch_type] += 1
            html = page.get("html")
            if page_has_jsonld(html if isinstance(html, str) else None):
                has_jsonld = True

        if has_jsonld:
            bundle_jsonld_site_counts[outcome] += 1
        if pdf_links:
            bundle_pdf_link_counts[outcome] += 1
        if pdfs:
            bundle_pdf_text_counts[outcome] += 1
        if discovered_pages:
            bundle_discovered_page_counts[outcome] += 1
        if bundle.get("menu_avg_price") is not None:
            bundle_menu_avg_counts[outcome] += 1

    deals_found = outcome_counts.get("deals_found", 0)
    no_deals = outcome_counts.get("no_deals", 0)
    total_entries = len(audit_entries)
    shared_url_mean = round(statistics.fmean(shared_url_group_sizes), 2) if shared_url_group_sizes else None

    return {
        "audit_paths": {
            "audit_path": str(DEFAULT_AUDIT_PATH),
            "debug_dir": str(DEFAULT_DEBUG_DIR),
        },
        "audit_snapshot": {
            "entries": total_entries,
            "deals_found": deals_found,
            "no_deals": no_deals,
            "success_rate_pct": _safe_percent(deals_found, total_entries),
            "outcomes": dict(outcome_counts),
            "no_deal_taxonomy": dict(no_deal_taxonomy),
        },
        "domain_families": {
            "all": dict(family_counts),
            "by_outcome": {outcome: dict(counts) for outcome, counts in family_by_outcome.items()},
        },
        "hosts": {
            "all": dict(host_counts),
            "by_outcome": {outcome: dict(counts) for outcome, counts in host_by_outcome.items()},
        },
        "shared_url": {
            "sites": shared_url_sites,
            "sites_with_deals": shared_url_success,
            "sites_with_no_deals": shared_url_no_deals,
            "alias_rows_collapsed": alias_rows_collapsed,
            "mean_locations_per_shared_url": shared_url_mean,
        },
        "debug_bundles": {
            "bundles": len(debug_bundles),
            "invalid_json": invalid_bundle_json,
            "matched_to_audit": sum(1 for key in debug_bundles if key in audit_by_key),
            "not_in_audit": sum(1 for key in debug_bundles if key not in audit_by_key),
            "bundle_outcomes": dict(bundle_outcome_counts),
            "sites_with_jsonld": dict(bundle_jsonld_site_counts),
            "sites_with_pdf_links": dict(bundle_pdf_link_counts),
            "sites_with_parsed_pdf_text": dict(bundle_pdf_text_counts),
            "sites_with_discovered_pages": dict(bundle_discovered_page_counts),
            "sites_with_menu_avg_price": dict(bundle_menu_avg_counts),
            "page_fetch_types": dict(page_fetch_type_counts),
            "page_count_histogram": {str(k): v for k, v in sorted(page_count_histogram.items())},
        },
    }


def _top_counts(counts: dict[str, int], limit: int) -> list[tuple[str, int]]:
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]


def _print_count_section(title: str, counts: dict[str, int], *, limit: int = 20, indent: str = "  ") -> None:
    logger.info("%s", title)
    if not counts:
        logger.info("%s(none)", indent)
        logger.info("")
        return
    for label, count in _top_counts(counts, limit=limit):
        logger.info("%s%-30s %6d", indent, label, count)
    logger.info("")


def print_report(report: dict[str, Any], *, top_hosts: int) -> None:
    audit = report["audit_snapshot"]
    shared = report["shared_url"]
    families = report["domain_families"]
    debug = report["debug_bundles"]
    hosts = report["hosts"]

    logger.info("=" * 72)
    logger.info("WEBSITE SCRAPE AUDIT SUMMARY")
    logger.info("=" * 72)
    logger.info("")

    logger.info("Audit snapshot:")
    logger.info("  entries:        %d", audit["entries"])
    logger.info("  deals_found:    %d (%.1f%%)", audit["deals_found"], audit["success_rate_pct"])
    logger.info("  no_deals:       %d (%.1f%%)", audit["no_deals"], _safe_percent(audit["no_deals"], audit["entries"]))
    logger.info("")

    _print_count_section("Outcomes:", audit["outcomes"])
    _print_count_section("No-deal taxonomy:", audit["no_deal_taxonomy"])
    _print_count_section("Domain families:", families["all"])

    logger.info("Domain families by outcome:")
    for outcome, counts in sorted(families["by_outcome"].items()):
        logger.info("  %s:", outcome)
        for family, count in _top_counts(counts, limit=8):
            logger.info("    %-30s %6d", family, count)
    logger.info("")

    logger.info("Shared URL stats:")
    logger.info("  shared_url_sites:              %d", shared["sites"])
    logger.info("  shared_url_sites_with_deals:   %d", shared["sites_with_deals"])
    logger.info("  shared_url_sites_with_no_deals:%d", shared["sites_with_no_deals"])
    logger.info("  alias_rows_collapsed:          %d", shared["alias_rows_collapsed"])
    if shared["mean_locations_per_shared_url"] is not None:
        logger.info("  mean_locations_per_shared_url: %.2f", shared["mean_locations_per_shared_url"])
    logger.info("")

    logger.info("Replay bundle coverage:")
    logger.info("  bundles:             %d", debug["bundles"])
    logger.info("  invalid_json:        %d", debug["invalid_json"])
    logger.info("  matched_to_audit:    %d", debug["matched_to_audit"])
    logger.info("  not_in_audit:        %d", debug["not_in_audit"])
    logger.info("")

    _print_count_section("JSON-LD site prevalence by bundle outcome:", debug["sites_with_jsonld"])
    _print_count_section("PDF link prevalence by bundle outcome:", debug["sites_with_pdf_links"])
    _print_count_section("Parsed PDF text prevalence by bundle outcome:", debug["sites_with_parsed_pdf_text"])
    _print_count_section("Discovered-page prevalence by bundle outcome:", debug["sites_with_discovered_pages"])
    _print_count_section("Page fetch types:", debug["page_fetch_types"])

    logger.info("Page-count histogram:")
    for page_count, count in sorted(debug["page_count_histogram"].items(), key=lambda item: int(item[0])):
        logger.info("  %-32s %6d", page_count, count)
    logger.info("")

    logger.info("Top hosts overall:")
    for host, count in _top_counts(hosts["all"], limit=top_hosts):
        logger.info("  %-48s %6d", host, count)
    logger.info("")

    logger.info("Top hosts with no deals:")
    for host, count in _top_counts(hosts["by_outcome"].get("no_deals", {}), limit=top_hosts):
        logger.info("  %-48s %6d", host, count)
    logger.info("")

    logger.info("Top hosts with deals:")
    for host, count in _top_counts(hosts["by_outcome"].get("deals_found", {}), limit=top_hosts):
        logger.info("  %-48s %6d", host, count)


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize website scrape audit and replay bundles")
    parser.add_argument("--audit-path", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--debug-dir", type=Path, default=DEFAULT_DEBUG_DIR)
    parser.add_argument("--json", action="store_true", help="Output JSON instead of text")
    parser.add_argument("--top-hosts", type=int, default=15, help="How many top hosts to show in text output")
    args = parser.parse_args()

    audit_entries = load_audit_entries(args.audit_path)
    debug_bundles, invalid_bundle_json = load_debug_bundles(args.debug_dir)
    report = build_report(audit_entries, debug_bundles, invalid_bundle_json)

    report["audit_paths"] = {
        "audit_path": str(args.audit_path),
        "debug_dir": str(args.debug_dir),
    }

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_report(report, top_hosts=args.top_hosts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())