#!/usr/bin/env python3
"""
scripts/reaudit_meal_deals.py — Random-sample audit of meal_deals.

Purpose
-------
Periodically verify that the refined signal pipeline is producing clean
data.  Rather than scanning the whole DB, we take a *stratified random
sample*: N rows per (source, deal_type, is_active) stratum — the user's
"random shuffle, 3x per data intake" — so every stratum (each "data
intake") contributes enough samples to spot problems.

For each sampled row, we replay the current quality rules against its
persisted fields and flag any discrepancies:
  * signal_quality score drift  (stored vs recomputed)
  * gate decision drift  (was "active", now scores as "reject")
  * missing sub_deals despite multi-promo text
  * price_type null but dollar/percentage pattern in text
  * other sanity checks

Output:
  - Pass / flag counts per stratum
  - Sample listings (so a human can eyeball the worst offenders)
  - Optional JSON report for ingestion into dashboards

Usage:
  PYTHONPATH=. python scripts/reaudit_meal_deals.py                       # default: 3 per stratum
  PYTHONPATH=. python scripts/reaudit_meal_deals.py --samples 5
  PYTHONPATH=. python scripts/reaudit_meal_deals.py --samples 10 --seed 42
  PYTHONPATH=. python scripts/reaudit_meal_deals.py --json > audit.json
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import sys
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from sqlalchemy import func

from collectors.meal_deals.quality import compute_signal_quality, gate_decision
from collectors.meal_deals.sub_deals import extract_sub_deals
from core.database import LocalEmployer, MealDeal, init_db, get_session

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


# ── Flag codes ─────────────────────────────────────────────────────────────
# Audit flags use short codes so aggregated counts stay readable.
FLAG_QUALITY_DRIFT = "quality_drift"           # stored vs recomputed differ by > 0.1
FLAG_GATE_DRIFT = "gate_drift"                 # active/review/reject changed
FLAG_MISSING_SUB_DEALS = "missing_sub_deals"   # text has multi-promo but column is null
FLAG_PRICE_TYPE_UNKNOWN = "price_type_unknown"  # price set, type null/unknown
FLAG_STALE_ADDON = "stale_addon"               # active row reads like an add-on
FLAG_STALE_NAV = "stale_nav"                   # active row name is nav junk
# Cross-employer leak detection is better-served by
# scripts/detect_cross_employer_leaks.py, which checks against an index of
# other employer names rather than the weak "own-tokens missing" heuristic.


_NAV_JUNK_RE = re.compile(
    r"^\s*(?:main navigation|values|what we value|values in action|"
    r"select a location|learn more|open menu|international sites|"
    r"wanna save|check out how you can save)\b",
    re.IGNORECASE,
)

_ADDON_RE = re.compile(
    r"(?:\+\s*\$|\b(?:add|extra|upgrade|substitut)\s.{0,20}\$)",
    re.IGNORECASE,
)

_DOLLAR_OFF_RE = re.compile(r"\$\s*\d+(?:\.\d{2})?\s*off", re.IGNORECASE)
_PERCENT_RE = re.compile(r"(?:\d{1,2}\s*%\s*off|half\s*(?:off|price)|½\s*(?:off|price))", re.IGNORECASE)


@dataclass
class AuditRow:
    id: int
    employer: str | None
    source: str
    deal_type: str | None
    is_active: bool
    deal_name: str
    price: float | None
    price_type: str | None
    stored_quality: float | None
    recomputed_quality: float
    stored_decision: str
    recomputed_decision: str
    flags: list[str] = field(default_factory=list)

    def failed(self) -> bool:
        return bool(self.flags)


def _sniff_flags(
    deal: MealDeal,
    employer: LocalEmployer | None,
    recomputed_quality: float,
    recomputed_decision: str,
) -> list[str]:
    """Apply audit rules to a single deal row."""
    flags: list[str] = []
    text_parts = [deal.deal_name, deal.deal_description, deal.raw_scraped_text]
    text = " ".join(p for p in text_parts if p)

    # 1. Quality drift
    stored = deal.signal_quality or 0.0
    if abs(stored - recomputed_quality) > 0.10:
        flags.append(FLAG_QUALITY_DRIFT)

    # 2. Gate drift — what decision the row *would* get today
    stored_decision, _ = gate_decision(stored)
    if stored_decision != recomputed_decision:
        flags.append(FLAG_GATE_DRIFT)

    # 3. Missing sub_deals — text decomposes but column is null
    if not deal.sub_deals:
        subs = extract_sub_deals(text)
        if subs:
            flags.append(FLAG_MISSING_SUB_DEALS)

    # 4. Price without type classification
    if deal.price is not None and (deal.price_type is None or deal.price_type == "unknown"):
        flags.append(FLAG_PRICE_TYPE_UNKNOWN)

    # 5. Active row reads like add-on
    if deal.is_active and _ADDON_RE.search(text):
        flags.append(FLAG_STALE_ADDON)

    # 6. Nav junk name in active row
    if deal.is_active and _NAV_JUNK_RE.search(deal.deal_name or ""):
        flags.append(FLAG_STALE_NAV)

    return flags


def _audit_deal(deal: MealDeal, employer: LocalEmployer | None) -> AuditRow:
    """Recompute quality + gate decision; compare against stored values."""
    qscore = compute_signal_quality(
        deal_name=deal.deal_name,
        deal_description=deal.deal_description,
        price=deal.price,
        price_type=deal.price_type,
        discount_percentage=deal.discount_percentage,
        valid_days=deal.valid_days,
        valid_start_time=deal.valid_start_time,
        valid_end_time=deal.valid_end_time,
        restaurant_name=employer.name if employer else None,
        raw_scraped_text=deal.raw_scraped_text,
    )
    recomputed_decision, _ = gate_decision(qscore.total)
    stored_decision, _ = gate_decision(deal.signal_quality or 0.0)

    flags = _sniff_flags(deal, employer, qscore.total, recomputed_decision)

    return AuditRow(
        id=deal.id,
        employer=employer.name if employer else None,
        source=deal.source,
        deal_type=deal.deal_type,
        is_active=bool(deal.is_active),
        deal_name=(deal.deal_name or "")[:80],
        price=deal.price,
        price_type=deal.price_type,
        stored_quality=deal.signal_quality,
        recomputed_quality=qscore.total,
        stored_decision=stored_decision,
        recomputed_decision=recomputed_decision,
        flags=flags,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-audit random samples of meal_deals")
    parser.add_argument("--samples", type=int, default=3,
                        help="Samples per (source, deal_type, is_active) stratum (default: 3)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    parser.add_argument("--include-inactive", action="store_true",
                        help="Sample inactive rows too (default: active only)")
    parser.add_argument("--json", action="store_true",
                        help="Emit JSON report instead of text")
    parser.add_argument("--show-all", action="store_true",
                        help="Print every sampled row (default: only failures + 2 passes per stratum)")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    engine = init_db()
    session = get_session(engine)

    try:
        q = session.query(MealDeal, LocalEmployer).outerjoin(
            LocalEmployer, MealDeal.local_employer_id == LocalEmployer.id
        )
        if not args.include_inactive:
            q = q.filter(MealDeal.is_active.is_(True))
        all_rows = q.all()

        if not all_rows:
            logger.error("No rows to audit.")
            return 1

        # Stratify — "random shuffle, 3x per data intake" means N per stratum.
        # Stratum key = (source, deal_type, is_active) so each source's
        # individual deal-type buckets all contribute samples.
        strata: dict[tuple, list] = defaultdict(list)
        for deal, emp in all_rows:
            key = (deal.source, deal.deal_type, bool(deal.is_active))
            strata[key].append((deal, emp))

        # Shuffle and take N per stratum
        sampled: list[tuple[MealDeal, LocalEmployer | None, tuple]] = []
        for key, items in strata.items():
            random.shuffle(items)
            for pair in items[:args.samples]:
                sampled.append((pair[0], pair[1], key))

        # Run audit
        results: list[AuditRow] = []
        for deal, emp, _key in sampled:
            results.append(_audit_deal(deal, emp))

        # Aggregate
        flag_counts: dict[str, int] = defaultdict(int)
        stratum_summary: dict[str, dict] = {}
        for stratum_key in strata.keys():
            stratum_summary[str(stratum_key)] = {
                "population": len(strata[stratum_key]),
                "sampled": 0, "failed": 0, "flags": defaultdict(int),
            }

        for r, (_d, _e, key) in zip(results, sampled):
            s = stratum_summary[str(key)]
            s["sampled"] += 1
            if r.failed():
                s["failed"] += 1
                for f in r.flags:
                    flag_counts[f] += 1
                    s["flags"][f] += 1

        # Coerce nested defaultdicts for JSON
        for s in stratum_summary.values():
            s["flags"] = dict(s["flags"])

        total = len(results)
        failed = sum(1 for r in results if r.failed())

        report = {
            "samples_per_stratum": args.samples,
            "total_sampled": total,
            "total_failed": failed,
            "pass_rate": round((total - failed) / total, 3) if total else 0.0,
            "flag_counts": dict(flag_counts),
            "strata": stratum_summary,
            "rows": [asdict(r) for r in results],
        }

        if args.json:
            print(json.dumps(report, default=str, indent=2))
            return 2 if failed else 0

        # Text mode
        logger.info("=" * 68)
        logger.info("MEAL DEAL RE-AUDIT  (random sample, stratified)")
        logger.info("=" * 68)
        logger.info("")
        logger.info("Population strata:  %d", len(strata))
        logger.info("Samples per stratum: %d", args.samples)
        logger.info("Total sampled:      %d", total)
        logger.info("Total failed:       %d  (%.1f%% of sample)",
                    failed, (failed / total * 100) if total else 0.0)
        logger.info("Pass rate:          %.1f%%", report["pass_rate"] * 100)
        logger.info("")

        if flag_counts:
            logger.info("Flag frequency (across sampled rows):")
            for f, n in sorted(flag_counts.items(), key=lambda x: -x[1]):
                logger.info("  %-25s %d", f, n)
            logger.info("")

        # Per-stratum summary: sort by failure rate desc, show top 15
        logger.info("Strata with the most failures (top 15):")
        ranked = sorted(
            stratum_summary.items(),
            key=lambda kv: -kv[1]["failed"],
        )[:15]
        logger.info("  %-45s %6s %6s %s",
                    "(source, deal_type, is_active)", "pop", "sampled", "failed")
        for key_str, s in ranked:
            logger.info("  %-45s %6d %6d %d",
                        key_str[:45], s["population"], s["sampled"], s["failed"])
        logger.info("")

        # Row listings
        failures = [r for r in results if r.failed()]
        if failures:
            logger.info("Failed samples (first 20):")
            for r in failures[:20]:
                logger.info(
                    "  id=%d emp=%r source=%s active=%s",
                    r.id, (r.employer or "")[:30], r.source, r.is_active,
                )
                logger.info(
                    "    name=%r price=%s ptype=%s",
                    r.deal_name, r.price, r.price_type,
                )
                logger.info(
                    "    stored_q=%s recomputed_q=%.3f  [%s→%s]",
                    f"{r.stored_quality:.3f}" if r.stored_quality is not None else "—",
                    r.recomputed_quality, r.stored_decision, r.recomputed_decision,
                )
                logger.info("    flags: %s", ", ".join(r.flags))
            logger.info("")

        if args.show_all:
            logger.info("All samples:")
            for r in results:
                status = "FAIL" if r.failed() else "PASS"
                logger.info("  [%s] id=%d q=%.3f  %s",
                            status, r.id, r.recomputed_quality, r.deal_name)

        logger.info("=" * 68)
        return 2 if failed else 0
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
