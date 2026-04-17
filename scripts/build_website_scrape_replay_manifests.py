#!/usr/bin/env python3
"""Build replay manifests from website scrape audit and debug bundles.

This script packages the synced replay corpus into deterministic subsets that
other agents can consume directly instead of hand-picking bundle files.

Outputs under `data/cache/website_scrape_manifests/` by default:
  - `summary.json`
  - `all_sites.json`
  - `regression_sets.json`
  - `by_outcome/*.json`
  - `by_no_deal_stage/*.json`
  - `by_domain_family/*.json`
  - `categories/*.json`
"""

from __future__ import annotations

import argparse
import json
import logging
import re
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
    summarize_debug_bundle,
)

try:
    from bs4 import BeautifulSoup
    from collectors.meal_deals.website_scraper import _extract_text_blocks
    _HAS_BUNDLE_BLOCK_EXTRACTION = True
except ImportError:
    BeautifulSoup = None  # type: ignore[assignment]
    _extract_text_blocks = None  # type: ignore[assignment]
    _HAS_BUNDLE_BLOCK_EXTRACTION = False

DEFAULT_OUTPUT_DIR = Path("data/cache/website_scrape_manifests")

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_") or "unknown"


def _extract_blocks_from_html(html: str) -> list[str]:
    if not _HAS_BUNDLE_BLOCK_EXTRACTION or BeautifulSoup is None or _extract_text_blocks is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    return _extract_text_blocks(soup)


def _manifest_sort_key(entry: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(entry.get("domain_family") or ""),
        str(entry.get("host") or ""),
        str(entry.get("site_url") or entry.get("site_key") or ""),
    )


def build_manifest_entries(
    audit_entries: list[dict[str, Any]],
    debug_bundles: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    audit_by_key: dict[str, dict[str, Any]] = {}
    for entry in audit_entries:
        key = entry.get("debug_cache_key")
        if isinstance(key, str) and key:
            audit_by_key[key] = entry

    all_keys = sorted(set(audit_by_key) | set(debug_bundles))
    manifests: list[dict[str, Any]] = []

    for site_key in all_keys:
        audit_entry = audit_by_key.get(site_key, {})
        bundle = debug_bundles.get(site_key)
        bundle_summary = summarize_debug_bundle(
            bundle,
            extract_text_blocks=_extract_blocks_from_html if _HAS_BUNDLE_BLOCK_EXTRACTION else None,
        )

        site_url = str(
            audit_entry.get("url")
            or (bundle or {}).get("site_url")
            or ""
        )
        host = urlparse(site_url).netloc.lower() or "unknown"
        outcome = str(audit_entry.get("outcome") or ("not_in_audit" if bundle else "missing"))
        domain_family = classify_domain_family(site_url)
        no_deal_stage = classify_no_deal_stage(audit_entry) if outcome == "no_deals" else None

        entry = {
            "site_key": site_key,
            "site_url": site_url,
            "host": host,
            "restaurant_name": audit_entry.get("name") or (bundle or {}).get("restaurant_name"),
            "domain_family": domain_family,
            "outcome": outcome,
            "no_deal_stage": no_deal_stage,
            "in_audit": bool(audit_entry),
            "in_bundle": bundle is not None,
            "deals_found": int(audit_entry.get("deals_found") or 0),
            "locations_sharing_url": int(audit_entry.get("locations_sharing_url") or 0),
            "canonical_locations": int(audit_entry.get("canonical_locations") or 0),
            "alias_rows_collapsed": int(audit_entry.get("alias_rows_collapsed") or 0),
            "page_count": bundle_summary["page_count"],
            "page_fetch_types": bundle_summary["page_fetch_types"],
            "total_blocks": bundle_summary["total_blocks"] if bundle_summary["total_blocks"] is not None else audit_entry.get("total_blocks"),
            "sample_blocks": bundle_summary["sample_blocks"] or list(audit_entry.get("sample_blocks") or []),
            "has_jsonld": bundle_summary["has_jsonld"],
            "has_pdf_links": bool(bundle_summary["pdf_links"]),
            "has_parsed_pdf_text": bundle_summary["parsed_pdf_count"] > 0,
            "has_discovered_pages": bool(bundle_summary["discovered_pages"]),
            "discovered_pages": bundle_summary["discovered_pages"],
            "pdf_links": bundle_summary["pdf_links"],
            "parsed_pdf_count": bundle_summary["parsed_pdf_count"],
            "menu_avg_price": bundle_summary["menu_avg_price"],
            "signal_count": bundle_summary["signal_count"],
            "tags": [],
        }

        if outcome == "no_deals" and entry["has_jsonld"]:
            entry["tags"].append("jsonld_present_but_zero_signal")
        if outcome == "no_deals" and entry["has_pdf_links"]:
            entry["tags"].append("pdf_present_but_zero_signal")
        if outcome == "no_deals" and no_deal_stage == "content_seen_but_extraction_failed":
            entry["tags"].append("content_seen_but_zero_signal")
        if outcome == "no_deals" and no_deal_stage == "discovery_found_candidates_but_no_signal":
            entry["tags"].append("discovery_found_candidates_but_zero_signal")
        if domain_family == "locator":
            entry["tags"].append("locator_page")
        if domain_family in {"social", "directory", "government", "other_nonrestaurant", "vendor_menu_host"}:
            entry["tags"].append("social_or_non_first_party")
        if (
            outcome == "no_deals"
            and domain_family in {"restaurant_or_first_party", "hotel", "locator"}
            and entry["page_count"] > 0
            and (entry["total_blocks"] or 0) == 0
        ):
            entry["tags"].append("static_empty_candidate")

        manifests.append(entry)

    return sorted(manifests, key=_manifest_sort_key)


def build_regression_sets(entries: list[dict[str, Any]], *, per_set: int = 8) -> dict[str, list[dict[str, Any]]]:
    def pick(filtered: list[dict[str, Any]]) -> list[dict[str, Any]]:
        chosen = sorted(filtered, key=_manifest_sort_key)[:per_set]
        return [
            {
                "site_key": item["site_key"],
                "site_url": item["site_url"],
                "restaurant_name": item.get("restaurant_name"),
                "host": item.get("host"),
                "outcome": item.get("outcome"),
                "domain_family": item.get("domain_family"),
                "no_deal_stage": item.get("no_deal_stage"),
            }
            for item in chosen
        ]

    return {
        "discovery": pick([e for e in entries if "discovery_found_candidates_but_zero_signal" in e["tags"]]),
        "jsonld_zero_signal": pick([e for e in entries if "jsonld_present_but_zero_signal" in e["tags"]]),
        "pdf_zero_signal": pick([e for e in entries if "pdf_present_but_zero_signal" in e["tags"]]),
        "wrong_target": pick([e for e in entries if "social_or_non_first_party" in e["tags"]]),
        "locator": pick([e for e in entries if "locator_page" in e["tags"]]),
        "static_empty_candidate": pick([e for e in entries if "static_empty_candidate" in e["tags"]]),
    }


def build_summary(entries: list[dict[str, Any]]) -> dict[str, Any]:
    by_outcome = Counter(str(entry.get("outcome") or "missing") for entry in entries)
    by_no_deal_stage = Counter(str(entry.get("no_deal_stage")) for entry in entries if entry.get("no_deal_stage"))
    by_domain_family = Counter(str(entry.get("domain_family") or "unknown") for entry in entries)
    tag_counts = Counter(tag for entry in entries for tag in entry.get("tags", []))

    return {
        "entries": len(entries),
        "by_outcome": dict(by_outcome),
        "by_no_deal_stage": dict(by_no_deal_stage),
        "by_domain_family": dict(by_domain_family),
        "tag_counts": dict(tag_counts),
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_manifests(output_dir: Path, entries: list[dict[str, Any]], regression_sets: dict[str, list[dict[str, Any]]]) -> None:
    summary = build_summary(entries)
    _write_json(output_dir / "summary.json", summary)
    _write_json(output_dir / "all_sites.json", entries)
    _write_json(output_dir / "regression_sets.json", regression_sets)

    by_outcome: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_no_deal_stage: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_domain_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_tag: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for entry in entries:
        by_outcome[str(entry.get("outcome") or "missing")].append(entry)
        if entry.get("no_deal_stage"):
            by_no_deal_stage[str(entry["no_deal_stage"])].append(entry)
        by_domain_family[str(entry.get("domain_family") or "unknown")].append(entry)
        for tag in entry.get("tags", []):
            by_tag[str(tag)].append(entry)

    for label, payload in by_outcome.items():
        _write_json(output_dir / "by_outcome" / f"{_slugify(label)}.json", payload)
    for label, payload in by_no_deal_stage.items():
        _write_json(output_dir / "by_no_deal_stage" / f"{_slugify(label)}.json", payload)
    for label, payload in by_domain_family.items():
        _write_json(output_dir / "by_domain_family" / f"{_slugify(label)}.json", payload)
    for label, payload in by_tag.items():
        _write_json(output_dir / "categories" / f"{_slugify(label)}.json", payload)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build website scrape replay manifests")
    parser.add_argument("--audit-path", type=Path, default=DEFAULT_AUDIT_PATH)
    parser.add_argument("--debug-dir", type=Path, default=DEFAULT_DEBUG_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--per-set", type=int, default=8, help="Entries per regression set")
    args = parser.parse_args()

    audit_entries = load_audit_entries(args.audit_path)
    debug_bundles, invalid_json = load_debug_bundles(args.debug_dir)
    entries = build_manifest_entries(audit_entries, debug_bundles)
    regression_sets = build_regression_sets(entries, per_set=max(1, args.per_set))
    write_manifests(args.output_dir, entries, regression_sets)

    logger.info("Wrote replay manifests to %s", args.output_dir)
    logger.info("  entries:        %d", len(entries))
    logger.info("  invalid_bundles:%d", invalid_json)
    for label, items in regression_sets.items():
        logger.info("  regression %-18s %d", label, len(items))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())