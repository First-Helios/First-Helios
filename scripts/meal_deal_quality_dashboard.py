#!/usr/bin/env python3
"""
scripts/meal_deal_quality_dashboard.py — Health snapshot for meal_deals.

Prints a concise report of signal quality metrics split by source so
regressions are visible:
  - row counts (total / active / inactive / rejected-at-ingest equivalent)
  - signal_quality distribution (mean, median, P25, P75, P90, P10)
  - field-completeness %: price, valid_days, valid_start_time, sub_deals, raw_text
  - top deal_types and sources
  - quality-by-source cross-tab
  - alerts — flags if mean quality drops below threshold per source

Optional JSON output for piping into monitoring.

Usage:
  PYTHONPATH=. python scripts/meal_deal_quality_dashboard.py
  PYTHONPATH=. python scripts/meal_deal_quality_dashboard.py --json
  PYTHONPATH=. python scripts/meal_deal_quality_dashboard.py --alert-threshold 0.45
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
from collections import defaultdict

from sqlalchemy import func

from core.database import MealDeal, init_db, get_session

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# Default alert threshold: if mean signal_quality for any source drops below
# this value, print an ALERT line.  Adjustable via --alert-threshold.
DEFAULT_ALERT_MEAN_QUALITY = 0.50
DEFAULT_ALERT_ACTIVE_RATIO = 0.40  # <40% active means something's wrong


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = max(0, min(len(sorted_vals) - 1, int(round(pct * (len(sorted_vals) - 1)))))
    return sorted_vals[k]


def _stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None,
                "p10": None, "p25": None, "p75": None, "p90": None}
    return {
        "n": len(values),
        "mean": round(statistics.fmean(values), 3),
        "median": round(statistics.median(values), 3),
        "p10": round(_percentile(values, 0.10), 3),
        "p25": round(_percentile(values, 0.25), 3),
        "p75": round(_percentile(values, 0.75), 3),
        "p90": round(_percentile(values, 0.90), 3),
    }


def build_report(session) -> dict:
    total = session.query(func.count(MealDeal.id)).scalar() or 0
    active = session.query(func.count(MealDeal.id)).filter(MealDeal.is_active.is_(True)).scalar() or 0
    inactive = total - active

    # Per-source aggregates
    rows = session.query(
        MealDeal.source,
        MealDeal.is_active,
        MealDeal.signal_quality,
        MealDeal.price,
        MealDeal.valid_days,
        MealDeal.valid_start_time,
        MealDeal.deal_description,
        MealDeal.raw_scraped_text,
        MealDeal.sub_deals,
        MealDeal.deal_type,
        MealDeal.price_type,
        MealDeal.is_chain_template,
    ).all()

    # Buckets
    by_source: dict[str, list] = defaultdict(list)
    by_type: dict[str, int] = defaultdict(int)
    by_price_type: dict[str, int] = defaultdict(int)
    all_quality: list[float] = []
    chain_templates = 0

    field_counts = {
        "price": 0, "valid_days": 0, "valid_start_time": 0,
        "deal_description": 0, "raw_scraped_text": 0,
        "sub_deals": 0, "signal_quality": 0,
    }

    for r in rows:
        by_source[r.source].append(r)
        by_type[r.deal_type or "null"] += 1
        by_price_type[r.price_type or "null"] += 1
        if r.is_chain_template:
            chain_templates += 1

        if r.signal_quality is not None:
            all_quality.append(r.signal_quality)
            field_counts["signal_quality"] += 1

        if r.price is not None:
            field_counts["price"] += 1
        if r.valid_days:
            field_counts["valid_days"] += 1
        if r.valid_start_time:
            field_counts["valid_start_time"] += 1
        if r.deal_description and len(r.deal_description.strip()) >= 10:
            field_counts["deal_description"] += 1
        if r.raw_scraped_text:
            field_counts["raw_scraped_text"] += 1
        if r.sub_deals:
            field_counts["sub_deals"] += 1

    # Per-source stats
    sources_report = {}
    for source, items in sorted(by_source.items()):
        q_vals = [x.signal_quality for x in items if x.signal_quality is not None]
        src_active = sum(1 for x in items if x.is_active)
        sources_report[source] = {
            "total": len(items),
            "active": src_active,
            "active_ratio": round(src_active / len(items), 3) if items else 0.0,
            "quality": _stats(q_vals),
            "with_price": sum(1 for x in items if x.price is not None),
            "with_days": sum(1 for x in items if x.valid_days),
            "with_times": sum(1 for x in items if x.valid_start_time),
            "with_sub_deals": sum(1 for x in items if x.sub_deals),
        }

    return {
        "totals": {
            "total_rows": total,
            "active": active,
            "inactive": inactive,
            "active_ratio": round(active / total, 3) if total else 0.0,
            "chain_templates": chain_templates,
        },
        "field_completeness_pct": {
            k: round(v / total * 100, 1) if total else 0.0
            for k, v in field_counts.items()
        },
        "field_completeness_counts": field_counts,
        "quality_overall": _stats(all_quality),
        "by_source": sources_report,
        "by_deal_type": dict(sorted(by_type.items(), key=lambda x: -x[1])),
        "by_price_type": dict(sorted(by_price_type.items(), key=lambda x: -x[1])),
    }


def check_alerts(report: dict, alert_q: float, alert_active_ratio: float) -> list[str]:
    alerts: list[str] = []
    for source, stats in report["by_source"].items():
        mq = stats["quality"]["mean"]
        if mq is not None and mq < alert_q:
            alerts.append(
                f"ALERT [{source}]: mean signal_quality={mq:.3f} below threshold {alert_q}"
            )
        ar = stats["active_ratio"]
        if ar < alert_active_ratio and stats["total"] >= 20:
            alerts.append(
                f"ALERT [{source}]: active_ratio={ar:.1%} below threshold {alert_active_ratio:.0%}"
            )
    return alerts


def print_report(report: dict, alerts: list[str]) -> None:
    t = report["totals"]
    logger.info("=" * 68)
    logger.info("MEAL DEAL QUALITY DASHBOARD")
    logger.info("=" * 68)
    logger.info("")
    logger.info("Totals:")
    logger.info("  rows:           %d", t["total_rows"])
    logger.info("  active:         %d (%.1f%%)", t["active"], t["active_ratio"] * 100)
    logger.info("  inactive:       %d", t["inactive"])
    logger.info("  chain templates:%d", t["chain_templates"])
    logger.info("")

    q = report["quality_overall"]
    logger.info("Signal quality (all rows):")
    if q["n"] == 0:
        logger.info("  (no scored rows)")
    else:
        logger.info("  n=%d  mean=%.3f  median=%.3f", q["n"], q["mean"], q["median"])
        logger.info("  p10=%.3f  p25=%.3f  p75=%.3f  p90=%.3f",
                    q["p10"], q["p25"], q["p75"], q["p90"])
    logger.info("")

    logger.info("Field completeness:")
    for k, v in report["field_completeness_pct"].items():
        logger.info("  %-25s %.1f%%  (%d rows)", k,
                    v, report["field_completeness_counts"][k])
    logger.info("")

    logger.info("By source:")
    logger.info("  %-20s %-8s %-8s %-8s %-8s", "source", "rows", "active%", "meanQ", "subs")
    for source, s in report["by_source"].items():
        mq = s["quality"]["mean"]
        mq_str = f"{mq:.3f}" if mq is not None else "  —"
        logger.info("  %-20s %-8d %-8.1f %-8s %-8d",
                    source, s["total"], s["active_ratio"] * 100, mq_str, s["with_sub_deals"])
    logger.info("")

    logger.info("By deal_type (top 10):")
    for dt, n in list(report["by_deal_type"].items())[:10]:
        logger.info("  %-25s %d", dt, n)
    logger.info("")

    logger.info("By price_type:")
    for pt, n in report["by_price_type"].items():
        logger.info("  %-25s %d", pt, n)
    logger.info("")

    if alerts:
        logger.info("=" * 68)
        logger.info("ALERTS")
        logger.info("=" * 68)
        for a in alerts:
            logger.info("  %s", a)
    else:
        logger.info("No alerts.  All sources within thresholds.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Meal deal quality dashboard")
    parser.add_argument("--json", action="store_true",
                        help="Output machine-readable JSON instead of text")
    parser.add_argument("--alert-threshold", type=float,
                        default=DEFAULT_ALERT_MEAN_QUALITY,
                        help="Per-source mean-quality alert threshold (default 0.50)")
    parser.add_argument("--alert-active-ratio", type=float,
                        default=DEFAULT_ALERT_ACTIVE_RATIO,
                        help="Per-source active-ratio alert threshold (default 0.40)")
    parser.add_argument("--exit-on-alert", action="store_true",
                        help="Exit 2 if any alert fires (for cron / CI use)")
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    try:
        report = build_report(session)
        alerts = check_alerts(report, args.alert_threshold, args.alert_active_ratio)

        if args.json:
            print(json.dumps({"report": report, "alerts": alerts}, default=str, indent=2))
        else:
            print_report(report, alerts)

        if alerts and args.exit_on_alert:
            return 2
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
