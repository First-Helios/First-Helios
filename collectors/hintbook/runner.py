"""
Hintbook harvest runner.

Usage (CLI):
    python -m collectors.hintbook.runner

Writes a timestamped JSON report under data/cache/hintbook/runs/ and
a latest.json symlink/copy. Report contains AggregatorRecords,
HintProposals, ExpectationProposals, IndustrySamples, and failure log.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from collectors.hintbook.models import HarvestReport, utcnow
from collectors.hintbook.registry import ALL_ADAPTERS, FOOD_ADAPTERS, BROADER_ADAPTERS

logger = logging.getLogger(__name__)

_RUN_DIR = Path(__file__).parent.parent.parent / "data" / "cache" / "hintbook" / "runs"


def run(
    *,
    food_only: bool = False,
    broader_only: bool = False,
    adapters_filter: list[str] | None = None,
) -> HarvestReport:
    if food_only:
        adapters = list(FOOD_ADAPTERS)
    elif broader_only:
        adapters = list(BROADER_ADAPTERS)
    else:
        adapters = list(ALL_ADAPTERS)

    if adapters_filter:
        adapters = [a for a in adapters if a.NAME in adapters_filter]

    report = HarvestReport()
    for adapter in adapters:
        logger.info("[Hintbook] running adapter: %s", adapter.NAME)
        try:
            adapter.collect(report)
        except Exception as exc:
            logger.exception("[Hintbook] adapter %s crashed", adapter.NAME)
            report.adapters_failed.append({
                "adapter": adapter.NAME,
                "url": None,
                "status": None,
                "error": f"adapter_crash:{type(exc).__name__}:{exc}",
            })
    report.finished_at = utcnow()
    _write_report(report)
    return report


def _write_report(report: HarvestReport) -> Path:
    _RUN_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = _RUN_DIR / f"harvest_{stamp}.json"
    path.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    latest = _RUN_DIR / "latest.json"
    latest.write_text(json.dumps(report.to_json(), indent=2), encoding="utf-8")
    logger.info("[Hintbook] wrote report → %s", path)
    return path


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run the hintbook competitive-intelligence harvest.")
    p.add_argument("--food-only", action="store_true")
    p.add_argument("--broader-only", action="store_true")
    p.add_argument("--adapters", nargs="*", help="Limit to these adapter NAMEs")
    p.add_argument("--verbose", "-v", action="store_true")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    report = run(
        food_only=args.food_only,
        broader_only=args.broader_only,
        adapters_filter=args.adapters,
    )
    summary = report.to_json()["counts"]
    print(json.dumps({
        "adapters_run": report.adapters_run,
        "adapters_failed_count": len(report.adapters_failed),
        **summary,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
