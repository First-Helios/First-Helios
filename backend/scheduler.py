"""
backend/scheduler.py

APScheduler job definitions for First-Helios.

Architecture: deterministic planner → adapters → ingest → score.
The collection planner (backend/collection_planner.py) decides what to collect
based on freshness state.  No AI agent is involved in collection scheduling.

Schedule (all times local server time / UTC):
  01:00  daily    — QCEW wage baseline (all industries, one HTTP call)
  02:00  Sunday   — AllThePlaces chain locations (all registered brands)
  03:00  Sunday   — Overture local density (all industries)
  04:00  daily    — Job posting volume (stale industries only)
  05:00  daily    — Sentiment / Reddit (stale industries only)
  06:00  daily    — Discovery scan + score refresh
  every 4h        — API endpoint health check

Depends on: apscheduler, backend.collection_planner, backend.scoring.engine
Called by: server.py on startup
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True)
    return _scheduler


def init_scheduler() -> BackgroundScheduler:
    """Configure and start the background scheduler.  Safe to call multiple times."""
    scheduler = get_scheduler()

    if scheduler.running:
        logger.info("[Scheduler] Already running, skipping init")
        return scheduler

    # ── QCEW wage baseline — daily 01:00 ─────────────────────────────
    # One HTTP call covers all 13 industries for the county.
    # Runs daily so any newly published quarter is picked up promptly.
    scheduler.add_job(
        _job_wage_baseline,
        "cron", hour=1, minute=0,
        id="qcew_wage_baseline",
        name="QCEW Wage Baseline (all industries)",
        replace_existing=True,
    )

    # ── AllThePlaces chain locations — weekly Sunday 02:00 ────────────
    # Covers every brand registered in INDUSTRY_REGISTRY.mega_corps.
    # Downloads prebuilt GeoJSON — no per-brand API calls.
    scheduler.add_job(
        _job_chain_locations,
        "cron", day_of_week="sun", hour=2, minute=0,
        id="atp_chain_locations",
        name="AllThePlaces Chain Locations (all brands)",
        replace_existing=True,
    )

    # ── Overture local density — weekly Sunday 03:00 ──────────────────
    # One DuckDB Parquet query covers all local employers in the region bbox.
    # Runs after chain locations so dedup has chain data to compare against.
    scheduler.add_job(
        _job_local_density,
        "cron", day_of_week="sun", hour=3, minute=0,
        id="overture_local_density",
        name="Overture Local Employer Density (all industries)",
        replace_existing=True,
    )

    # ── Job postings — daily 04:00 ────────────────────────────────────
    # Planner filters to only stale industries (threshold: 14 days).
    scheduler.add_job(
        _job_postings,
        "cron", hour=4, minute=0,
        id="job_posting_volume",
        name="Job Posting Volume (stale industries)",
        replace_existing=True,
    )

    # ── Sentiment / Reddit — daily 05:00 ─────────────────────────────
    # Planner filters to only stale industries (threshold: 14 days).
    scheduler.add_job(
        _job_sentiment,
        "cron", hour=5, minute=0,
        id="sentiment_check",
        name="Reddit Sentiment (stale industries)",
        replace_existing=True,
    )

    # ── Discovery scan + score refresh — daily 06:00 ──────────────────
    # Runs after all collectors so it sees the freshest data.
    scheduler.add_job(
        _job_discovery_and_score,
        "cron", hour=6, minute=0,
        id="discovery_and_score",
        name="Discovery Scan + Score Refresh",
        replace_existing=True,
    )

    # ── API endpoint health check — every 4 hours ─────────────────────
    scheduler.add_job(
        _job_endpoint_health,
        "interval", hours=4,
        id="endpoint_health_check",
        name="API Endpoint Health Monitor",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] Started with %d jobs", len(scheduler.get_jobs()))
    return scheduler


def get_scheduler_status() -> dict:
    """Return status of all scheduled jobs."""
    scheduler = get_scheduler()
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id":       job.id,
            "name":     job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger":  str(job.trigger),
        })
    return {"running": scheduler.running, "jobs": jobs}


# ── Job implementations ───────────────────────────────────────────────────────

def _job_wage_baseline() -> None:
    """Daily: fetch QCEW county wage + establishment data for all industries.

    One HTTP GET per region — no per-industry calls needed.
    QCEW returns all NAICS codes in a single ~400 KB CSV.
    """
    try:
        from scrapers.qcew_adapter import QCEWAdapter
        from backend.ingest import ingest_signals

        logger.info("[Scheduler] Running QCEW wage baseline")
        adapter = QCEWAdapter()
        signals = adapter.scrape(region="austin_tx")

        if signals:
            n = ingest_signals(signals, region="austin_tx", chain="qcew", source="qcew")
            wage_count  = sum(1 for s in signals if s.signal_type == "wage")
            estab_count = sum(1 for s in signals if s.signal_type == "establishment_count")
            logger.info(
                "[Scheduler] QCEW: ingested %d signals "
                "(%d wage, %d establishment_count)",
                n, wage_count, estab_count,
            )
        else:
            logger.warning("[Scheduler] QCEW returned no signals")

    except Exception as e:
        logger.error("[Scheduler] QCEW wage baseline failed: %s", e)


def _job_chain_locations() -> None:
    """Weekly Sunday: collect chain store locations for every registered brand.

    Uses AllThePlaces (primary) → Overture fallback per brand.
    The planner handles which brands are stale.
    """
    try:
        from backend.collection_planner import build_plan, run_plan

        logger.info("[Scheduler] Running chain location collection")
        plan = build_plan(
            region="austin_tx",
            # wage_baseline and local_density have their own jobs; exclude here
        )
        chain_tasks = [t for t in plan.tasks if t.intent == "poi_chain_locations"]

        if not chain_tasks:
            logger.info("[Scheduler] All chain locations are fresh — nothing to collect")
            return

        logger.info("[Scheduler] %d stale brand(s) to collect", len(chain_tasks))
        results = run_plan(plan.__class__(
            region=plan.region,
            tasks=chain_tasks,
        ))

        ok  = sum(1 for r in results if r.success)
        new = sum(r.records_new for r in results)
        logger.info("[Scheduler] Chain locations: %d/%d OK, %d new records",
                    ok, len(results), new)

    except Exception as e:
        logger.error("[Scheduler] Chain location job failed: %s", e)


def _job_local_density() -> None:
    """Weekly Sunday: collect local employer density via Overture."""
    try:
        from scrapers.overture_adapter import OvertureLocalAdapter
        from backend.ingest import ingest_signals
        from backend.category_catalog import discover_from_db

        logger.info("[Scheduler] Running Overture local density collection")
        adapter = OvertureLocalAdapter()
        signals = adapter.scrape(region="austin_tx")

        if signals:
            n = ingest_signals(signals, region="austin_tx", chain="local", source="overture")
            logger.info("[Scheduler] Overture local: ingested %d signals", n)
        else:
            logger.warning("[Scheduler] Overture local returned no signals")

        # Classify all newly collected records immediately
        logger.info("[Scheduler] Running category discovery after local density")
        discover_from_db(source_system="overture")

    except Exception as e:
        logger.error("[Scheduler] Local density job failed: %s", e)


def _job_postings() -> None:
    """Daily: collect job posting volume for stale industries."""
    try:
        from backend.collection_planner import build_plan, run_plan

        plan = build_plan(region="austin_tx")
        posting_tasks = [t for t in plan.tasks if t.intent == "job_posting_volume"]

        if not posting_tasks:
            logger.info("[Scheduler] All job posting data is fresh")
            return

        logger.info("[Scheduler] %d industry/industries need job posting refresh",
                    len(posting_tasks))
        from backend.collection_planner import CollectionPlan
        results = run_plan(CollectionPlan(region="austin_tx", tasks=posting_tasks))
        ok  = sum(1 for r in results if r.success)
        new = sum(r.records_new for r in results)
        logger.info("[Scheduler] Job postings: %d/%d OK, %d new records",
                    ok, len(results), new)

    except Exception as e:
        logger.error("[Scheduler] Job posting job failed: %s", e)


def _job_sentiment() -> None:
    """Daily: collect Reddit sentiment for stale industries."""
    try:
        from backend.collection_planner import build_plan, run_plan, CollectionPlan

        plan = build_plan(region="austin_tx")
        sentiment_tasks = [t for t in plan.tasks if t.intent == "sentiment_check"]

        if not sentiment_tasks:
            logger.info("[Scheduler] All sentiment data is fresh")
            return

        logger.info("[Scheduler] %d industry/industries need sentiment refresh",
                    len(sentiment_tasks))
        results = run_plan(CollectionPlan(region="austin_tx", tasks=sentiment_tasks))
        ok  = sum(1 for r in results if r.success)
        new = sum(r.records_new for r in results)
        logger.info("[Scheduler] Sentiment: %d/%d OK, %d new records",
                    ok, len(results), new)

    except Exception as e:
        logger.error("[Scheduler] Sentiment job failed: %s", e)


def _job_discovery_and_score() -> None:
    """Daily: run discovery scan then refresh all scores."""
    try:
        from backend.discovery import run_discovery
        from backend.scoring.engine import compute_all_scores

        logger.info("[Scheduler] Running discovery scan")
        scan = run_discovery(region="austin_tx", max_leads=50)
        logger.info("[Scheduler] Discovery: %d leads", len(scan.leads))

        logger.info("[Scheduler] Running score refresh")
        compute_all_scores(region="austin_tx")
        logger.info("[Scheduler] Score refresh complete")

    except Exception as e:
        logger.error("[Scheduler] Discovery + score job failed: %s", e)


def _job_endpoint_health() -> None:
    """Every 4h: probe API endpoints and update health state."""
    try:
        from backend.endpoint_catalog import verify_all_endpoints

        logger.info("[Scheduler] Running endpoint health check")
        results = verify_all_endpoints(skip_recently_verified_hours=4.0)

        for ep in results.get("deactivated", []):
            logger.warning("[Scheduler] Endpoint DEACTIVATED: %s/%s — %s",
                           ep["adapter_name"], ep["intent"], ep.get("reason", "?"))
        for ep in results.get("recovered", []):
            logger.info("[Scheduler] Endpoint RECOVERED: %s/%s",
                        ep["adapter_name"], ep["intent"])

        logger.info(
            "[Scheduler] Health check: total=%d checked=%d "
            "deactivated=%d recovered=%d",
            results["total"], results["checked"],
            len(results.get("deactivated", [])), len(results.get("recovered", [])),
        )
    except Exception as e:
        logger.error("[Scheduler] Endpoint health check failed: %s", e)
