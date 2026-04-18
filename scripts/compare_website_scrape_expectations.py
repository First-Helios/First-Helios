#!/usr/bin/env python3
"""Compare external replay expectations against website scrape debug bundles.

This script turns an expectation registry into a concrete replay report showing
which expected offers were found, missed, or are not currently testable from
the synced first-party bundle corpus.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from collectors.meal_deals.expectation_registry import (
    DEFAULT_REGISTRY_PATH,
    build_expectation_report,
    load_expectations,
)
from collectors.meal_deals.website_scrape_audit_utils import DEFAULT_DEBUG_DIR, load_debug_bundles
from config.paths import CACHE_DIR

DEFAULT_OUTPUT_PATH = CACHE_DIR / "website_scrape_expectation_report.json"

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def print_report(report: dict[str, Any], *, max_examples: int) -> None:
    summary = report["summary"]
    results = report["results"]

    logger.info("=" * 72)
    logger.info("WEBSITE SCRAPE EXPECTATION REPORT")
    logger.info("=" * 72)
    logger.info("")
    logger.info("Registry:      %s", report["registry_path"])
    logger.info("Debug dir:     %s", report["debug_dir"])
    logger.info("Output path:   %s", report["output_path"])
    logger.info("Bundles:       %d", summary["debug_bundles"])
    logger.info("Invalid JSON:  %d", report["invalid_bundle_json"])
    logger.info("Expectations:  %d", summary["expectations"])
    logger.info("")

    logger.info("Status counts:")
    for label, count in sorted(summary["status_counts"].items()):
        logger.info("  %-16s %6d", label, count)
    logger.info("")

    logger.info("Reason counts:")
    for label, count in sorted(summary["reason_counts"].items(), key=lambda item: (-item[1], item[0])):
        logger.info("  %-36s %6d", label, count)
    logger.info("")

    grouped: dict[str, list[dict[str, Any]]] = {"found": [], "missed": [], "not_testable": []}
    for result in results:
        grouped.setdefault(str(result["status"]), []).append(result)

    for status in ("found", "missed", "not_testable"):
        logger.info("%s:", status.replace("_", " ").title())
        items = grouped.get(status, [])
        if not items:
            logger.info("  (none)")
            logger.info("")
            continue
        for result in items[:max_examples]:
            logger.info(
                "  %-24s -> %-36s [%s]",
                result["expectation_id"],
                result["expected_label"][:36],
                result["reason"],
            )
        if len(items) > max_examples:
            logger.info("  ... %d more", len(items) - max_examples)
        logger.info("")


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare replay expectations against synced debug bundles")
    parser.add_argument("--registry-path", type=Path, default=DEFAULT_REGISTRY_PATH)
    parser.add_argument("--debug-dir", type=Path, default=DEFAULT_DEBUG_DIR)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--include-expired", action="store_true", help="Include expired expectations in the report")
    parser.add_argument("--json", action="store_true", help="Print the full JSON report to stdout")
    parser.add_argument("--max-examples", type=int, default=8)
    args = parser.parse_args()

    expectations = load_expectations(path=args.registry_path, include_expired=args.include_expired)
    debug_bundles, invalid_bundle_json = load_debug_bundles(args.debug_dir)
    report = build_expectation_report(expectations, debug_bundles)
    report["registry_path"] = str(args.registry_path)
    report["debug_dir"] = str(args.debug_dir)
    report["output_path"] = str(args.output_path)
    report["invalid_bundle_json"] = invalid_bundle_json

    _write_json(args.output_path, report)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print_report(report, max_examples=max(1, args.max_examples))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())