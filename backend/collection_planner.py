"""
backend/collection_planner.py

Deterministic collection planner — the replacement for AI-driven query planning.

Answers one question: "What needs to be collected right now, and in what order?"

The planner iterates over every (region × industry × data-type) combination,
checks freshness, and returns an ordered list of CollectionTask objects.
The scheduler and any manual trigger execute tasks from this list — no LLM
needed to decide what to collect.

The AI agent (OpenClaw) remains useful for *interpreting* collected data, but
it never plans collection again. This file owns that responsibility.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger(__name__)


# ── Task definition ───────────────────────────────────────────────────────────

@dataclass
class CollectionTask:
    """A single unit of work for a collector."""
    task_id:      str           # unique slug, e.g. "austin_tx:hair_beauty:chain:great_clips"
    region:       str           # e.g. "austin_tx"
    intent:       str           # "poi_chain_locations" | "poi_local_density" | "wage_baseline" | ...
    industry:     Optional[str] # e.g. "hair_beauty"
    brand:        Optional[str] # e.g. "great_clips"  (None for local/wage tasks)
    priority:     int           # lower = higher priority; 0 = critical
    reason:       str           # human-readable explanation of why this task was generated
    age_days:     Optional[float] = None   # how stale the existing data is
    records:      int = 0                  # records currently in DB for this slot


@dataclass
class CollectionPlan:
    """Output of the planner — an ordered list of tasks."""
    generated_at: datetime = field(default_factory=datetime.utcnow)
    region:       str = ""
    tasks:        list[CollectionTask] = field(default_factory=list)
    skipped:      int = 0   # fresh combos that were excluded

    @property
    def total(self) -> int:
        return len(self.tasks)

    def summary(self) -> str:
        lines = [
            f"CollectionPlan for {self.region}  "
            f"tasks={self.total}  skipped_fresh={self.skipped}",
        ]
        for t in self.tasks[:20]:
            age = f"{t.age_days:.0f}d old" if t.age_days is not None else "never"
            lines.append(
                f"  [{t.priority:2d}] {t.intent:<22} "
                f"industry={t.industry or '-':<22} "
                f"brand={t.brand or '-':<18} "
                f"({age}, {t.records} records)"
            )
        if self.total > 20:
            lines.append(f"  ... and {self.total - 20} more")
        return "\n".join(lines)


# ── Planner ───────────────────────────────────────────────────────────────────

def build_plan(
    region: str = "austin_tx",
    industries: Optional[list[str]] = None,
    force_stale: bool = False,
) -> CollectionPlan:
    """Generate a full collection plan for the region.

    Args:
        region:       Region key from config (e.g. "austin_tx").
        industries:   Subset of industry keys to plan for (None = all).
        force_stale:  If True, treat everything as stale regardless of age.

    Returns:
        CollectionPlan with tasks sorted by priority.
    """
    from backend.industries import INDUSTRY_REGISTRY
    from backend.freshness import check_freshness_for_intent
    from backend.freshness import FRESHNESS_THRESHOLDS

    plan = CollectionPlan(region=region)
    tasks: list[CollectionTask] = []

    target_industries = {
        k: v for k, v in INDUSTRY_REGISTRY.items()
        if industries is None or k in industries
    }

    for ind_key, dim in target_industries.items():

        # ── 1. Chain locations — one task per mega-corp brand ─────────
        for mc in dim.mega_corps:
            freshness = check_freshness_for_intent(
                "poi_chain_locations", region, brand=mc.key, industry=ind_key
            )
            age, records, stale = _parse_freshness(
                freshness, "poi_chain_locations", force_stale
            )
            if stale:
                tasks.append(CollectionTask(
                    task_id  = f"{region}:{ind_key}:chain:{mc.key}",
                    region   = region,
                    intent   = "poi_chain_locations",
                    industry = ind_key,
                    brand    = mc.key,
                    priority = _priority("poi_chain_locations", age, records),
                    reason   = _reason(age, records, FRESHNESS_THRESHOLDS["poi_chain_locations"]),
                    age_days = age,
                    records  = records,
                ))
            else:
                plan.skipped += 1

        # ── 2. Local density — one task per industry ──────────────────
        freshness = check_freshness_for_intent(
            "poi_local_density", region, industry=ind_key
        )
        age, records, stale = _parse_freshness(
            freshness, "poi_local_density", force_stale
        )
        if stale:
            tasks.append(CollectionTask(
                task_id  = f"{region}:{ind_key}:local_density",
                region   = region,
                intent   = "poi_local_density",
                industry = ind_key,
                brand    = None,
                priority = _priority("poi_local_density", age, records),
                reason   = _reason(age, records, FRESHNESS_THRESHOLDS["poi_local_density"]),
                age_days = age,
                records  = records,
            ))
        else:
            plan.skipped += 1

        # ── 3. Wage baseline — one task per industry ──────────────────
        freshness = check_freshness_for_intent(
            "wage_baseline", region, industry=ind_key
        )
        age, records, stale = _parse_freshness(
            freshness, "wage_baseline", force_stale
        )
        if stale:
            tasks.append(CollectionTask(
                task_id  = f"{region}:{ind_key}:wage_baseline",
                region   = region,
                intent   = "wage_baseline",
                industry = ind_key,
                brand    = None,
                priority = _priority("wage_baseline", age, records),
                reason   = _reason(age, records, FRESHNESS_THRESHOLDS["wage_baseline"]),
                age_days = age,
                records  = records,
            ))
        else:
            plan.skipped += 1

        # ── 4. Job posting volume — one task per industry ─────────────
        freshness = check_freshness_for_intent(
            "job_posting_volume", region, industry=ind_key
        )
        age, records, stale = _parse_freshness(
            freshness, "job_posting_volume", force_stale
        )
        if stale:
            tasks.append(CollectionTask(
                task_id  = f"{region}:{ind_key}:job_posting_volume",
                region   = region,
                intent   = "job_posting_volume",
                industry = ind_key,
                brand    = None,
                priority = _priority("job_posting_volume", age, records),
                reason   = _reason(age, records, FRESHNESS_THRESHOLDS["job_posting_volume"]),
                age_days = age,
                records  = records,
            ))
        else:
            plan.skipped += 1

        # ── 5. Sentiment — one task per industry ──────────────────────
        freshness = check_freshness_for_intent(
            "sentiment_check", region, industry=ind_key
        )
        age, records, stale = _parse_freshness(
            freshness, "sentiment_check", force_stale
        )
        if stale:
            tasks.append(CollectionTask(
                task_id  = f"{region}:{ind_key}:sentiment",
                region   = region,
                intent   = "sentiment_check",
                industry = ind_key,
                brand    = None,
                priority = _priority("sentiment_check", age, records),
                reason   = _reason(age, records, FRESHNESS_THRESHOLDS["sentiment_check"]),
                age_days = age,
                records  = records,
            ))
        else:
            plan.skipped += 1

    # Sort: lower priority number first, then by staleness (oldest first)
    tasks.sort(key=lambda t: (t.priority, -(t.age_days or 9999)))
    plan.tasks = tasks
    return plan


# ── Runner ────────────────────────────────────────────────────────────────────

@dataclass
class RunResult:
    task_id:      str
    intent:       str
    industry:     Optional[str]
    brand:        Optional[str]
    records_new:  int
    success:      bool
    error:        Optional[str] = None
    duration_s:   float = 0.0


def run_task(task: CollectionTask) -> RunResult:
    """Execute a single CollectionTask and ingest results.

    All exceptions are caught — the runner never crashes the scheduler.
    """
    import time
    from backend.ingest import ingest_signals

    t0 = time.monotonic()
    logger.info(
        "[Planner] Running %s | region=%s industry=%s brand=%s",
        task.intent, task.region, task.industry or "-", task.brand or "-",
    )

    try:
        signals = _collect(task)
        if signals:
            ingest_signals(signals, region=task.region,
                           chain=task.brand or "local",
                           source=task.intent)
        duration = round(time.monotonic() - t0, 2)
        logger.info(
            "[Planner] Done %s → %d signals  (%.1fs)",
            task.task_id, len(signals), duration,
        )
        return RunResult(
            task_id=task.task_id, intent=task.intent,
            industry=task.industry, brand=task.brand,
            records_new=len(signals), success=True, duration_s=duration,
        )

    except Exception as e:
        duration = round(time.monotonic() - t0, 2)
        logger.error("[Planner] Task %s failed: %s", task.task_id, e)
        return RunResult(
            task_id=task.task_id, intent=task.intent,
            industry=task.industry, brand=task.brand,
            records_new=0, success=False, error=str(e), duration_s=duration,
        )


def run_plan(
    plan: CollectionPlan,
    max_tasks: Optional[int] = None,
    dry_run: bool = False,
) -> list[RunResult]:
    """Execute all tasks in the plan in priority order.

    Args:
        plan:      The CollectionPlan to execute.
        max_tasks: Cap on number of tasks to run (None = all).
        dry_run:   If True, log tasks but don't execute.
    """
    tasks = plan.tasks[:max_tasks] if max_tasks else plan.tasks
    results: list[RunResult] = []

    logger.info(
        "[Planner] Executing plan: %d tasks for region=%s%s",
        len(tasks), plan.region, " (DRY RUN)" if dry_run else "",
    )

    for task in tasks:
        if dry_run:
            logger.info("[Planner] DRY RUN would execute: %s", task.task_id)
            results.append(RunResult(
                task_id=task.task_id, intent=task.intent,
                industry=task.industry, brand=task.brand,
                records_new=0, success=True, error="dry_run",
            ))
            continue
        results.append(run_task(task))

    ok = sum(1 for r in results if r.success and r.error != "dry_run")
    new = sum(r.records_new for r in results)
    logger.info(
        "[Planner] Plan complete: %d/%d succeeded, %d new records",
        ok, len(tasks), new,
    )
    return results


# ── Collector dispatch ────────────────────────────────────────────────────────

def _collect(task: CollectionTask):
    """Dispatch a CollectionTask to the right adapter. Returns list[ScraperSignal]."""

    if task.intent == "poi_chain_locations":
        return _collect_chain(task)

    elif task.intent == "poi_local_density":
        return _collect_local(task)

    elif task.intent == "wage_baseline":
        return _collect_wage(task)

    elif task.intent == "job_posting_volume":
        return _collect_jobs(task)

    elif task.intent == "sentiment_check":
        return _collect_sentiment(task)

    else:
        raise ValueError(f"No collector for intent: {task.intent!r}")


def _collect_chain(task: CollectionTask):
    """poi_chain_locations — AllThePlaces → Overture fallback."""
    from scrapers.alltheplaces_adapter import AllThePlacesAdapter, ATP_BRAND_MAP

    signals = []

    # AllThePlaces (primary — first-party, authoritative)
    if task.brand in ATP_BRAND_MAP:
        adapter = AllThePlacesAdapter()
        adapter.chain = task.brand
        signals = adapter.scrape(region=task.region)
        if signals:
            logger.info("[Planner] ATP returned %d signals for %s", len(signals), task.brand)
            return signals

    # Overture chain fallback
    try:
        from scrapers.overture_adapter import OvertureChainAdapter
        adapter = OvertureChainAdapter()
        adapter.chain = task.brand
        signals = adapter.scrape(region=task.region)
        if signals:
            logger.info("[Planner] Overture returned %d signals for %s", len(signals), task.brand)
    except Exception as e:
        logger.warning("[Planner] Overture chain fallback failed for %s: %s", task.brand, e)

    return signals


def _collect_local(task: CollectionTask):
    """poi_local_density — Overture local employers."""
    from scrapers.overture_adapter import OvertureLocalAdapter
    adapter = OvertureLocalAdapter()
    signals = adapter.scrape(region=task.region)

    # Classify newly collected records immediately
    try:
        from backend.category_catalog import discover_from_db
        discover_from_db(source_system="overture")
        logger.info("[Planner] Category discovery ran after local density collection")
    except Exception as e:
        logger.warning("[Planner] Category discovery failed: %s", e)

    return signals


def _collect_wage(task: CollectionTask):
    """wage_baseline — QCEW county data (all industries in one call)."""
    from scrapers.qcew_adapter import QCEWAdapter
    adapter = QCEWAdapter()
    signals = adapter.scrape(region=task.region)

    # Filter to requested industry only
    if task.industry and signals:
        signals = [s for s in signals if s.metadata.get("industry") == task.industry]

    return signals


def _collect_jobs(task: CollectionTask):
    """job_posting_volume — JobSpy."""
    try:
        from scrapers.jobspy_adapter import JobSpyAdapter
        from backend.industries import INDUSTRY_REGISTRY
        dim = INDUSTRY_REGISTRY.get(task.industry or "")
        if not dim:
            return []
        # Use first few job search terms from the industry registry
        terms = list(dim.job_search_terms)[:3]
        adapter = JobSpyAdapter()
        return adapter.scrape(region=task.region, search_terms=terms,
                              industry=task.industry)
    except ImportError:
        logger.warning("[Planner] JobSpy not available")
        return []


def _collect_sentiment(task: CollectionTask):
    """sentiment_check — Reddit."""
    try:
        from scrapers.reddit_adapter import RedditAdapter
        from backend.industries import INDUSTRY_REGISTRY
        dim = INDUSTRY_REGISTRY.get(task.industry or "")
        if not dim:
            return []
        adapter = RedditAdapter()
        return adapter.scrape(region=task.region, industry=task.industry)
    except ImportError:
        logger.warning("[Planner] Reddit adapter not available")
        return []


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_freshness(
    freshness: dict | None,
    intent: str,
    force: bool,
) -> tuple[Optional[float], int, bool]:
    """Return (age_days, records, is_stale) from a freshness dict."""
    from backend.freshness import FRESHNESS_THRESHOLDS

    if force:
        return None, 0, True

    if freshness is None:
        # Freshness check unavailable — assume stale so we don't skip collection
        return None, 0, True

    age     = freshness.get("age_days")
    records = freshness.get("records_collected", 0)
    stale   = freshness.get("is_stale", True)

    # 0-record "fresh" results are still stale — data was never actually collected
    if not stale and records == 0:
        return age, 0, True

    return age, records, stale


def _priority(intent: str, age_days: Optional[float], records: int) -> int:
    """Return a priority integer — lower is higher priority."""
    # Never collected → highest urgency
    if age_days is None or records == 0:
        base = 0
    else:
        # More stale = higher priority
        from backend.freshness import FRESHNESS_THRESHOLDS
        threshold = FRESHNESS_THRESHOLDS.get(intent, 14.0)
        staleness_ratio = age_days / max(threshold, 1.0)
        # 0 = very stale (>2x threshold), 10 = just crossed threshold
        base = max(0, 10 - int(staleness_ratio * 5))

    # Intent tiers: wages and local density are foundation data → lower number
    tier = {
        "wage_baseline":       0,
        "poi_local_density":   1,
        "poi_chain_locations": 2,
        "job_posting_volume":  3,
        "sentiment_check":     4,
    }.get(intent, 5)

    return tier * 10 + base


def _reason(age_days: Optional[float], records: int, threshold: float) -> str:
    if records == 0 and age_days is None:
        return "Never collected"
    if records == 0:
        return f"Collected {age_days:.0f}d ago but returned 0 records"
    return f"{age_days:.0f}d old (threshold: {threshold:.0f}d), {records} records on file"


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    parser = argparse.ArgumentParser(description="Collection planner")
    parser.add_argument("--region",     default="austin_tx")
    parser.add_argument("--industries", default="",    help="Comma-separated industry keys")
    parser.add_argument("--run",        action="store_true", help="Execute the plan")
    parser.add_argument("--dry-run",    action="store_true", help="Show plan without executing")
    parser.add_argument("--max-tasks",  type=int, default=0,  help="Cap number of tasks")
    parser.add_argument("--force",      action="store_true",  help="Treat all data as stale")
    args = parser.parse_args()

    industries = [i.strip() for i in args.industries.split(",") if i.strip()] or None
    plan = build_plan(args.region, industries=industries, force_stale=args.force)

    print(plan.summary())

    if args.run or args.dry_run:
        max_t = args.max_tasks or None
        results = run_plan(plan, max_tasks=max_t, dry_run=args.dry_run)
        ok  = sum(1 for r in results if r.success and r.error != "dry_run")
        new = sum(r.records_new for r in results)
        print(f"\nResults: {ok}/{len(results)} succeeded, {new} new records")
        for r in results:
            status = "OK" if r.success else "FAIL"
            print(f"  [{status}] {r.task_id}  new={r.records_new}  {r.duration_s:.1f}s"
                  + (f"  ERROR: {r.error}" if r.error and r.error != "dry_run" else ""))
