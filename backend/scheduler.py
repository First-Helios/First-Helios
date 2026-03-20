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
