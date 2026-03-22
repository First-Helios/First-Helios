"""
APScheduler job definitions for ChainStaffingTracker.

Runs scraping jobs on configurable schedules inside the Flask process.
Schedule configuration comes from config/chains.yaml under 'scheduler'.

Depends on: apscheduler, config.loader, scrapers.*, backend.scoring.engine
Called by: server.py (on startup)
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from config.loader import get_scheduler_config

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    """Return the singleton scheduler instance."""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler(daemon=True)
    return _scheduler


def init_scheduler() -> BackgroundScheduler:
    """Configure and start the background scheduler.

    Adds jobs based on config/chains.yaml scheduler section.
    Safe to call multiple times — skips if already running.
    """
    scheduler = get_scheduler()

    if scheduler.running:
        logger.info("[Scheduler] Already running, skipping init")
        return scheduler

    sched_cfg = get_scheduler_config()

    # ── Careers API — daily at 3am ───────────────────────────────────
    careers_cron = sched_cfg.get("careers_api", {}).get("cron", {})
    scheduler.add_job(
        _run_careers_api,
        "cron",
        hour=careers_cron.get("hour", 3),
        minute=careers_cron.get("minute", 0),
        id="careers_api",
        name="Careers API Scraper",
        replace_existing=True,
    )

    # ── JobSpy — daily at 4am ────────────────────────────────────────
    jobspy_cron = sched_cfg.get("jobspy", {}).get("cron", {})
    scheduler.add_job(
        _run_jobspy,
        "cron",
        hour=jobspy_cron.get("hour", 4),
        minute=jobspy_cron.get("minute", 0),
        id="jobspy",
        name="JobSpy Scraper",
        replace_existing=True,
    )

    # ── Reddit — every 6 hours ───────────────────────────────────────
    reddit_interval = sched_cfg.get("reddit", {}).get("interval_hours", 6)
    scheduler.add_job(
        _run_reddit,
        "interval",
        hours=reddit_interval,
        id="reddit",
        name="Reddit Sentiment Scraper",
        replace_existing=True,
    )

    # ── Google Maps — weekly Monday 5am ──────────────────────────────
    gmaps_cron = sched_cfg.get("google_maps", {}).get("cron", {})
    scheduler.add_job(
        _run_reviews,
        "cron",
        day_of_week=gmaps_cron.get("day_of_week", "mon"),
        hour=gmaps_cron.get("hour", 5),
        minute=gmaps_cron.get("minute", 0),
        id="google_maps",
        name="Google Maps Reviews Scraper",
        replace_existing=True,
    )

    # ── BLS — weekly ─────────────────────────────────────────────────
    bls_cron = sched_cfg.get("bls", {}).get("cron", {})
    scheduler.add_job(
        _run_bls,
        "cron",
        day_of_week=bls_cron.get("day_of_week", "mon"),
        hour=bls_cron.get("hour", 6),
        minute=bls_cron.get("minute", 0),
        id="bls",
        name="BLS Wage Data Fetcher",
        replace_existing=True,
    )

    # ── AllThePlaces store discovery — weekly Sunday 2am ────────────
    scheduler.add_job(
        _run_alltheplaces,
        "cron",
        day_of_week="sun",
        hour=2,
        minute=0,
        id="atp_starbucks_austin",
        name="AllThePlaces Starbucks Austin",
        replace_existing=True,
    )

    # ── Overture chain cross-validation — weekly Sunday 2:15am ────
    scheduler.add_job(
        _run_overture_chain,
        "cron",
        day_of_week="sun",
        hour=2,
        minute=15,
        id="overture_starbucks_austin",
        name="Overture Chain Starbucks Austin",
        replace_existing=True,
    )

    # ── OSM fallback — weekly Sunday 2:30am ──────────────────────
    scheduler.add_job(
        _run_osm,
        "cron",
        day_of_week="sun",
        hour=2,
        minute=30,
        id="osm_starbucks_austin",
        name="OSM Starbucks Austin",
        replace_existing=True,
    )

    # ── Overture local employers — weekly Sunday 3am ─────────────
    scheduler.add_job(
        _run_overture_local,
        "cron",
        day_of_week="sun",
        hour=3,
        minute=0,
        id="overture_local_austin",
        name="Overture Local Employers Austin",
        replace_existing=True,
    )

    # ── Discovery scan — daily at 1am ────────────────────────────
    scheduler.add_job(
        _run_discovery_scan,
        "cron",
        hour=1,
        minute=0,
        id="discovery_scan",
        name="Discovery Expansion Scan",
        replace_existing=True,
    )

    # ── Endpoint health monitor — every 4 hours ───────────────────
    scheduler.add_job(
        _run_endpoint_health_check,
        "interval",
        hours=4,
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
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "trigger": str(job.trigger),
        })
    return {
        "running": scheduler.running,
        "jobs": jobs,
    }


# ── Job functions ────────────────────────────────────────────────────────────

def _run_careers_api() -> None:
    """Scheduled job: Run careers API scraper."""
    try:
        from scrapers.careers_api import scrape_careers_api
        from backend.scoring.engine import compute_all_scores

        logger.info("[Scheduler] Running careers API scraper")
        signals = scrape_careers_api(region="austin_tx", chain="starbucks")
        logger.info("[Scheduler] Careers API: %d signals", len(signals))

        # Recompute scores after new data
        compute_all_scores(region="austin_tx")

    except Exception as e:
        logger.error("[Scheduler] Careers API job failed: %s", e)


def _run_jobspy() -> None:
    """Scheduled job: Run JobSpy scraper (chain + wage modes)."""
    try:
        from scrapers.jobspy_adapter import scrape_jobspy
        from backend.scoring.engine import compute_all_scores

        logger.info("[Scheduler] Running JobSpy scraper")

        # Chain mode
        signals = scrape_jobspy(chain="starbucks", region="austin_tx", mode="chain")
        logger.info("[Scheduler] JobSpy chain: %d signals", len(signals))

        # Wage mode
        signals = scrape_jobspy(industry="coffee_cafe", region="austin_tx", mode="wage")
        logger.info("[Scheduler] JobSpy wage: %d signals", len(signals))

        compute_all_scores(region="austin_tx")

    except Exception as e:
        logger.error("[Scheduler] JobSpy job failed: %s", e)


def _run_reddit() -> None:
    """Scheduled job: Run Reddit sentiment scraper."""
    try:
        from scrapers.reddit_adapter import scrape_reddit
        from backend.scoring.engine import compute_all_scores

        logger.info("[Scheduler] Running Reddit scraper")
        signals = scrape_reddit(region="austin_tx")
        logger.info("[Scheduler] Reddit: %d signals", len(signals))

        compute_all_scores(region="austin_tx")

    except Exception as e:
        logger.error("[Scheduler] Reddit job failed: %s", e)


def _run_reviews() -> None:
    """Scheduled job: Run Google Maps reviews scraper."""
    try:
        from scrapers.reviews_adapter import scrape_reviews
        from backend.scoring.engine import compute_all_scores

        logger.info("[Scheduler] Running reviews scraper")
        signals = scrape_reviews(chain="starbucks", region="austin_tx")
        logger.info("[Scheduler] Reviews: %d signals", len(signals))

        compute_all_scores(region="austin_tx")

    except Exception as e:
        logger.error("[Scheduler] Reviews job failed: %s", e)


def _run_bls() -> None:
    """Scheduled job: Run BLS wage data fetcher."""
    try:
        from scrapers.bls_adapter import scrape_bls

        logger.info("[Scheduler] Running BLS fetcher")
        signals = scrape_bls(region="austin_tx")
        logger.info("[Scheduler] BLS: %d signals", len(signals))

    except Exception as e:
        logger.error("[Scheduler] BLS job failed: %s", e)


def _run_alltheplaces() -> None:
    """Scheduled job: AllThePlaces store discovery."""
    try:
        from scrapers.alltheplaces_adapter import AllThePlacesAdapter
        from backend.ingest import ingest_signals

        logger.info("[Scheduler] Running AllThePlaces discovery")
        for chain_key in ["starbucks", "dutch_bros", "mcdonalds"]:
            adapter = AllThePlacesAdapter()
            adapter.chain = chain_key
            signals = adapter.scrape("austin_tx")
            if signals:
                ingest_signals(signals, region="austin_tx")
            logger.info("[Scheduler] AllThePlaces %s: %d signals", chain_key, len(signals))

    except Exception as e:
        logger.error("[Scheduler] AllThePlaces job failed: %s", e)


def _run_overture_chain() -> None:
    """Scheduled job: Overture chain cross-validation."""
    try:
        from scrapers.overture_adapter import OvertureChainAdapter
        from backend.ingest import ingest_signals

        logger.info("[Scheduler] Running Overture chain discovery")
        for chain_key in ["starbucks", "dutch_bros"]:
            adapter = OvertureChainAdapter()
            adapter.chain = chain_key
            signals = adapter.scrape("austin_tx")
            if signals:
                ingest_signals(signals, region="austin_tx")
            logger.info("[Scheduler] Overture chain %s: %d signals", chain_key, len(signals))

    except Exception as e:
        logger.error("[Scheduler] Overture chain job failed: %s", e)


def _run_overture_local() -> None:
    """Scheduled job: Overture local employers discovery."""
    try:
        from scrapers.overture_adapter import OvertureLocalAdapter
        from backend.ingest import ingest_signals

        logger.info("[Scheduler] Running Overture local employer discovery")
        adapter = OvertureLocalAdapter()
        signals = adapter.scrape("austin_tx")
        if signals:
            ingest_signals(signals, region="austin_tx")
        logger.info("[Scheduler] Overture local: %d signals", len(signals))

    except Exception as e:
        logger.error("[Scheduler] Overture local job failed: %s", e)


def _run_osm() -> None:
    """Scheduled job: OSM Overpass store fallback."""
    try:
        from scrapers.osm_adapter import OSMAdapter
        from backend.ingest import ingest_signals

        logger.info("[Scheduler] Running OSM Overpass discovery")
        for chain_key in ["starbucks", "dutch_bros", "mcdonalds"]:
            adapter = OSMAdapter()
            adapter.chain = chain_key
            signals = adapter.scrape("austin_tx")
            if signals:
                ingest_signals(signals, region="austin_tx")
            logger.info("[Scheduler] OSM %s: %d signals", chain_key, len(signals))

    except Exception as e:
        logger.error("[Scheduler] OSM job failed: %s", e)


def _run_discovery_scan() -> None:
    """Scheduled job: Discovery expansion scan.

    Analyses collected data to find coverage gaps, stale leads, and
    geographic clusters that need attention.  Logs a summary so operators
    can review overnight.
    """
    try:
        from backend.discovery import run_discovery, get_discovery_summary

        logger.info("[Scheduler] Running discovery expansion scan")
        scan = run_discovery(region="austin_tx", max_leads=50)
        summary = get_discovery_summary(region="austin_tx")

        logger.info(
            "[Scheduler] Discovery scan complete: %d leads found "
            "(coverage_gaps=%d, data_gaps=%d, stale=%d, geo=%d, local=%d)",
            len(scan.leads),
            sum(1 for l in scan.leads if l.lead_type == "coverage_gap"),
            sum(1 for l in scan.leads if l.lead_type == "data_dimension_gap"),
            sum(1 for l in scan.leads if l.lead_type == "stale_lead"),
            sum(1 for l in scan.leads if l.lead_type == "geographic_cluster"),
            sum(1 for l in scan.leads if l.lead_type == "local_opportunity"),
        )

        # Log top 5 highest-priority leads for operator review
        for lead in scan.leads[:5]:
            logger.info(
                "[Scheduler] Discovery top lead: [%d] %s — %s",
                lead.priority, lead.lead_type, lead.description,
            )

    except Exception as e:
        logger.error("[Scheduler] Discovery scan failed: %s", e)


def _run_endpoint_health_check() -> None:
    """Scheduled job: Probe all live API endpoints and update health state.

    Runs every 4 hours.  Endpoints that fail ENDPOINT_FAILURE_THRESHOLD
    consecutive probes are marked inactive and excluded from the next
    OpenClaw session prompt.  Recovered endpoints are automatically re-activated.
    """
    try:
        from backend.endpoint_catalog import verify_all_endpoints

        logger.info("[Scheduler] Running endpoint health check")
        results = verify_all_endpoints(skip_recently_verified_hours=4.0)

        for ep in results.get("deactivated", []):
            logger.warning(
                "[Scheduler] Endpoint DEACTIVATED: %s/%s — %s",
                ep["adapter_name"], ep["intent"], ep.get("reason", "?"),
            )
        for ep in results.get("recovered", []):
            logger.info(
                "[Scheduler] Endpoint RECOVERED: %s/%s",
                ep["adapter_name"], ep["intent"],
            )

        logger.info(
            "[Scheduler] Endpoint health check complete: total=%d checked=%d skipped=%d "
            "deactivated=%d recovered=%d",
            results["total"], results["checked"], results["skipped"],
            len(results.get("deactivated", [])), len(results.get("recovered", [])),
        )
    except Exception as e:
        logger.error("[Scheduler] Endpoint health check failed: %s", e)
