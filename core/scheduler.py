"""
APScheduler job definitions for ChainStaffingTracker.

Runs scraping jobs on configurable schedules inside the Flask process.
Schedule configuration comes from config/scheduler.yaml (loaded via
config.loader.get_scheduler_config). Hardcoded defaults in add_job calls
are used only when a key is absent from scheduler.yaml.

Each job respects an `enabled` flag in scheduler.yaml — set to false to
disable a job without removing it from the code.

Depends on: apscheduler, config.loader, scrapers.*, backend.scoring.engine
Called by: server.py (on startup)
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler

from config.loader import get_scheduler_config

logger = logging.getLogger(__name__)

_scheduler: BackgroundScheduler | None = None


def _job_enabled(sched_cfg: dict, job_id: str) -> bool:
    """Return True if the job is enabled in scheduler.yaml (default: True)."""
    return sched_cfg.get(job_id, {}).get("enabled", True)


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

    # ── Careers API — MOVED to future_plans/web_scraping/ ────────────
    # Direct website scraping is a separate project.

    # ── Job Postings ─────────────────────────────────────────────────

    if _job_enabled(sched_cfg, "jobspy"):
        _c = sched_cfg.get("jobspy", {}).get("cron", {})
        scheduler.add_job(_run_jobspy, "cron",
            hour=_c.get("hour", 4), minute=_c.get("minute", 0),
            id="jobspy", name="JobSpy Scraper", replace_existing=True)

    if _job_enabled(sched_cfg, "reddit"):
        _iv = sched_cfg.get("reddit", {}).get("interval_hours", 6)
        scheduler.add_job(_run_reddit, "interval",
            hours=_iv,
            id="reddit", name="Reddit Sentiment Scraper", replace_existing=True)

    if _job_enabled(sched_cfg, "austin_gov"):
        _c = sched_cfg.get("austin_gov", {}).get("cron", {})
        scheduler.add_job(_run_austin_gov, "cron",
            hour=_c.get("hour", 5), minute=_c.get("minute", 30),
            id="austin_gov", name="Austin City Gov Job Listings", replace_existing=True)

    if _job_enabled(sched_cfg, "usajobs"):
        _c = sched_cfg.get("usajobs", {}).get("cron", {})
        scheduler.add_job(_run_usajobs, "cron",
            hour=_c.get("hour", 6), minute=_c.get("minute", 0),
            id="usajobs", name="USAJobs Federal Listings", replace_existing=True)

    if _job_enabled(sched_cfg, "serpapi_jobs"):
        _c = sched_cfg.get("serpapi_jobs", {}).get("cron", {})
        scheduler.add_job(_run_serpapi_jobs, "cron",
            hour=_c.get("hour", 7), minute=_c.get("minute", 0),
            id="serpapi_jobs", name="SerpAPI Google Jobs", replace_existing=True)

    if _job_enabled(sched_cfg, "rapidapi_activejobs"):
        _c = sched_cfg.get("rapidapi_activejobs", {}).get("cron", {})
        scheduler.add_job(_run_activejobs, "cron",
            hour=_c.get("hour", 8), minute=_c.get("minute", 0),
            id="rapidapi_activejobs", name="Active Jobs DB (RapidAPI)", replace_existing=True)

    if _job_enabled(sched_cfg, "juju"):
        _c = sched_cfg.get("juju", {}).get("cron", {})
        scheduler.add_job(_run_juju, "cron",
            hour=_c.get("hour", 8), minute=_c.get("minute", 30),
            id="juju", name="Juju Job Search", replace_existing=True)

    if _job_enabled(sched_cfg, "theirstack"):
        _c = sched_cfg.get("theirstack", {}).get("cron", {})
        scheduler.add_job(_run_theirstack, "cron",
            hour=_c.get("hour", 9), minute=_c.get("minute", 0),
            id="theirstack", name="TheirStack Jobs & Companies", replace_existing=True)

    if _job_enabled(sched_cfg, "jobicy"):
        scheduler.add_job(_run_jobicy, "interval",
            hours=sched_cfg.get("jobicy", {}).get("interval_hours", 1),
            id="jobicy", name="Jobicy Remote Jobs", replace_existing=True)

    # ── Labor Market / Regulatory Data ───────────────────────────────

    if _job_enabled(sched_cfg, "bls"):
        _c = sched_cfg.get("bls", {}).get("cron", {})
        scheduler.add_job(_run_bls, "cron",
            day_of_week=_c.get("day_of_week", "mon"),
            hour=_c.get("hour", 6), minute=_c.get("minute", 0),
            id="bls", name="BLS Wage Data Fetcher", replace_existing=True)

    if _job_enabled(sched_cfg, "qcew"):
        _c = sched_cfg.get("qcew", {}).get("cron", {})
        scheduler.add_job(_run_qcew, "cron",
            day=_c.get("day", 1),
            hour=_c.get("hour", 7), minute=_c.get("minute", 0),
            id="qcew", name="QCEW Establishment Data", replace_existing=True)

    if _job_enabled(sched_cfg, "cbp"):
        _c = sched_cfg.get("cbp", {}).get("cron", {})
        scheduler.add_job(_run_cbp, "cron",
            day_of_week=_c.get("day_of_week", "mon"),
            hour=_c.get("hour", 8), minute=_c.get("minute", 0),
            id="cbp", name="Census CBP ZIP Establishments", replace_existing=True)

    if _job_enabled(sched_cfg, "nlrb"):
        _c = sched_cfg.get("nlrb", {}).get("cron", {})
        scheduler.add_job(_run_nlrb, "cron",
            day_of_week=_c.get("day_of_week", "wed"),
            hour=_c.get("hour", 7), minute=_c.get("minute", 0),
            id="nlrb", name="NLRB Labor Unrest Cases", replace_existing=True)

    if _job_enabled(sched_cfg, "warn_tx"):
        _c = sched_cfg.get("warn_tx", {}).get("cron", {})
        scheduler.add_job(_run_warn, "cron",
            day_of_week=_c.get("day_of_week", "tue"),
            hour=_c.get("hour", 7), minute=_c.get("minute", 0),
            id="warn_tx", name="Texas WARN Act Filings", replace_existing=True)

    if _job_enabled(sched_cfg, "baseline_recompute"):
        _c = sched_cfg.get("baseline_recompute", {}).get("cron", {})
        scheduler.add_job(_run_baseline_recompute, "cron",
            day_of_week=_c.get("day_of_week", "sun"),
            hour=_c.get("hour", 4), minute=_c.get("minute", 0),
            id="baseline_recompute", name="Labor Market Baseline Recompute",
            replace_existing=True)

    # ── Store / Employer Discovery (Sunday stagger) ──────────────────

    if _job_enabled(sched_cfg, "atp_starbucks_austin"):
        _c = sched_cfg.get("atp_starbucks_austin", {}).get("cron", {})
        scheduler.add_job(_run_alltheplaces, "cron",
            day_of_week=_c.get("day_of_week", "sun"),
            hour=_c.get("hour", 2), minute=_c.get("minute", 0),
            id="atp_starbucks_austin", name="AllThePlaces Starbucks Austin",
            replace_existing=True)

    if _job_enabled(sched_cfg, "overture_starbucks_austin"):
        _c = sched_cfg.get("overture_starbucks_austin", {}).get("cron", {})
        scheduler.add_job(_run_overture_chain, "cron",
            day_of_week=_c.get("day_of_week", "sun"),
            hour=_c.get("hour", 2), minute=_c.get("minute", 15),
            id="overture_starbucks_austin", name="Overture Chain Starbucks Austin",
            replace_existing=True)

    if _job_enabled(sched_cfg, "osm_starbucks_austin"):
        _c = sched_cfg.get("osm_starbucks_austin", {}).get("cron", {})
        scheduler.add_job(_run_osm, "cron",
            day_of_week=_c.get("day_of_week", "sun"),
            hour=_c.get("hour", 2), minute=_c.get("minute", 30),
            id="osm_starbucks_austin", name="OSM Starbucks Austin",
            replace_existing=True)

    if _job_enabled(sched_cfg, "overture_local_austin"):
        _c = sched_cfg.get("overture_local_austin", {}).get("cron", {})
        scheduler.add_job(_run_overture_local, "cron",
            day_of_week=_c.get("day_of_week", "sun"),
            hour=_c.get("hour", 3), minute=_c.get("minute", 0),
            id="overture_local_austin", name="Overture Local Employers Austin",
            replace_existing=True)

    # ── Maintenance ───────────────────────────────────────────────────

    if _job_enabled(sched_cfg, "google_maps"):
        _c = sched_cfg.get("google_maps", {}).get("cron", {})
        scheduler.add_job(_run_reviews, "cron",
            day_of_week=_c.get("day_of_week", "mon"),
            hour=_c.get("hour", 5), minute=_c.get("minute", 0),
            id="google_maps", name="Google Maps Reviews Scraper", replace_existing=True)

    if _job_enabled(sched_cfg, "posting_expiry"):
        _c = sched_cfg.get("posting_expiry", {}).get("cron", {})
        scheduler.add_job(_run_posting_expiry, "cron",
            hour=_c.get("hour", 3), minute=_c.get("minute", 0),
            id="posting_expiry", name="Job Posting Expiry Sweep", replace_existing=True)

    if _job_enabled(sched_cfg, "posting_purge"):
        _c = sched_cfg.get("posting_purge", {}).get("cron", {})
        scheduler.add_job(_run_posting_purge, "cron",
            day_of_week=_c.get("day_of_week", "sun"),
            hour=_c.get("hour", 3), minute=_c.get("minute", 30),
            id="posting_purge", name="Purge Ancient Job Postings", replace_existing=True)

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
    """Scheduled job: DEPRECATED — careers API moved to future_plans/web_scraping/.

    Direct website scraping is a separate project.
    """
    logger.warning(
        "[Scheduler] careers_api job called but this scraper has been moved "
        "to future_plans/web_scraping/. Use JobSpy for job posting signals."
    )


def _run_jobspy() -> None:
    """Scheduled job: Run JobSpy scraper (chain + wage modes)."""
    try:
        from collectors.job_boards.jobspy_adapter import scrape_jobspy
        from core.scoring.engine import compute_all_scores

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
        from collectors.sentiment.reddit_adapter import scrape_reddit
        from core.scoring.engine import compute_all_scores

        logger.info("[Scheduler] Running Reddit scraper")
        signals = scrape_reddit(region="austin_tx")
        logger.info("[Scheduler] Reddit: %d signals", len(signals))

        compute_all_scores(region="austin_tx")

    except Exception as e:
        logger.error("[Scheduler] Reddit job failed: %s", e)


def _run_reviews() -> None:
    """Scheduled job: Run Google Maps reviews scraper."""
    try:
        from collectors.sentiment.reviews_adapter import scrape_reviews
        from core.scoring.engine import compute_all_scores

        logger.info("[Scheduler] Running reviews scraper")
        signals = scrape_reviews(chain="starbucks", region="austin_tx")
        logger.info("[Scheduler] Reviews: %d signals", len(signals))

        compute_all_scores(region="austin_tx")

    except Exception as e:
        logger.error("[Scheduler] Reviews job failed: %s", e)


def _run_bls() -> None:
    """Scheduled job: Run BLS data fetcher.

    Uses the bulk download script when BLS_API_KEY is set (v2, 50 series/call),
    falls back to the legacy per-series adapter otherwise.
    """
    import os
    try:
        if os.environ.get("BLS_API_KEY"):
            # v2 path: batch POST, cache per-series, write to DB
            import sys
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
            from download_bls_bulk import fetch_series, process_and_write
            from config.loader import get_bls_series

            current_year = str(__import__("datetime").datetime.utcnow().year)
            series_config = get_bls_series()
            logger.info("[Scheduler] Running BLS bulk fetch (v2) for %s", current_year)
            series_data = fetch_series(series_config, current_year, current_year, force=True)
            counts = process_and_write(series_data, series_config, "austin_tx")
            logger.info(
                "[Scheduler] BLS bulk: JOLTS=%d LAUS=%d CES=%d CPI/ECI=%d new rows",
                counts["jolts"], counts["laus"], counts["ces"], counts.get("cpi_eci", 0),
            )
        else:
            # Legacy v1 path: per-series GET via bls_adapter
            from collectors.labor_data.bls_adapter import scrape_bls
            logger.info("[Scheduler] Running BLS fetcher (v1 fallback — set BLS_API_KEY for v2)")
            signals = scrape_bls(region="austin_tx")
            logger.info("[Scheduler] BLS: %d signals", len(signals))

    except Exception as e:
        logger.error("[Scheduler] BLS job failed: %s", e)


def _run_alltheplaces() -> None:
    """Scheduled job: AllThePlaces store discovery."""
    try:
        from collectors.employer_data.alltheplaces_adapter import AllThePlacesAdapter
        from core.ingest import ingest_signals

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
        from collectors.employer_data.overture_adapter import OvertureChainAdapter
        from core.ingest import ingest_signals

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
        from collectors.employer_data.overture_adapter import OvertureLocalAdapter
        from core.ingest import ingest_signals

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
        from collectors.employer_data.osm_adapter import OSMAdapter
        from core.ingest import ingest_signals

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


def _run_qcew() -> None:
    """Scheduled job: QCEW county-level establishment & employment data.

    Only fetches in months when new quarterly data is expected
    (Jan, Apr, Jul, Oct — approximately 6 months after the quarter ends).
    """
    try:
        from datetime import datetime
        from collectors.labor_data.qcew_adapter import scrape_qcew

        # Check if this is an active month for QCEW
        active_months = [1, 4, 7, 10]
        current_month = datetime.utcnow().month
        if current_month not in active_months:
            logger.info("[Scheduler] QCEW: skipping (month %d not in active months)", current_month)
            return

        logger.info("[Scheduler] Running QCEW establishment data fetch")
        signals = scrape_qcew(region="austin_tx")
        logger.info("[Scheduler] QCEW: %d signals", len(signals))

        # Recompute baselines after fresh ground-truth data
        if signals:
            _run_baseline_recompute()

    except Exception as e:
        logger.error("[Scheduler] QCEW job failed: %s", e)


def _run_cbp() -> None:
    """Scheduled job: Census CBP ZIP-level establishment data.

    Annual data — only worth checking around April each year.
    """
    try:
        from datetime import datetime
        from collectors.labor_data.cbp_adapter import scrape_cbp

        active_months = [4]
        current_month = datetime.utcnow().month
        if current_month not in active_months:
            logger.info("[Scheduler] CBP: skipping (month %d not in active months)", current_month)
            return

        logger.info("[Scheduler] Running Census CBP fetch")
        signals = scrape_cbp(region="austin_tx")
        logger.info("[Scheduler] CBP: %d signals", len(signals))

    except Exception as e:
        logger.error("[Scheduler] CBP job failed: %s", e)


def _run_baseline_recompute() -> None:
    """Scheduled job: Recompute labor market baselines from ground-truth data."""
    try:
        from core.baseline import compute_baselines

        logger.info("[Scheduler] Recomputing labor market baselines")
        results = compute_baselines(region="austin_tx")
        logger.info(
            "[Scheduler] Baselines: %d NAICS codes computed",
            len(results),
        )

    except Exception as e:
        logger.error("[Scheduler] Baseline recompute failed: %s", e)


def _run_nlrb() -> None:
    """Scheduled job: Fetch NLRB labor unrest cases for tracked chains."""
    try:
        from collectors.labor_data.nlrb_adapter import scrape_nlrb
        from core.scoring.engine import compute_all_scores

        logger.info("[Scheduler] Running NLRB labor unrest fetch")
        signals = scrape_nlrb(region="austin_tx")
        logger.info("[Scheduler] NLRB: %d signals", len(signals))

        if signals:
            compute_all_scores(region="austin_tx")

    except Exception as e:
        logger.error("[Scheduler] NLRB job failed: %s", e)


def _run_warn() -> None:
    """Scheduled job: Fetch Texas WARN Act filings."""
    try:
        from collectors.labor_data.warn_adapter import scrape_warn

        logger.info("[Scheduler] Running Texas WARN Act fetch")
        signals = scrape_warn(region="austin_tx")
        logger.info("[Scheduler] WARN: %d signals", len(signals))

    except Exception as e:
        logger.error("[Scheduler] WARN job failed: %s", e)


def _run_usajobs() -> None:
    """Scheduled job: Fetch federal job listings from USAJobs API."""
    try:
        from collectors.job_boards.usajobs_adapter import scrape_usajobs

        logger.info("[Scheduler] Running USAJobs federal listings fetch")
        signals = scrape_usajobs(region="austin_tx", location="Austin, TX", max_pages=2)
        logger.info("[Scheduler] USAJobs: %d signals", len(signals))

    except Exception as e:
        logger.error("[Scheduler] USAJobs job failed: %s", e)


def _run_austin_gov() -> None:
    """Scheduled job: Fetch City of Austin job listings from Workday portal."""
    try:
        from collectors.job_boards.workday_gov_adapter import scrape_austin_gov

        logger.info("[Scheduler] Running Austin City Gov Workday fetch")
        signals = scrape_austin_gov(region="austin_tx")
        logger.info("[Scheduler] Austin Gov: %d signals", len(signals))

    except Exception as e:
        logger.error("[Scheduler] Austin Gov job failed: %s", e)


def _run_serpapi_jobs() -> None:
    """Scheduled job: Fetch Google Jobs listings via SerpAPI."""
    try:
        from collectors.job_boards.serpapi_adapter import scrape_serpapi
        logger.info("[Scheduler] Running SerpAPI Google Jobs fetch")
        signals = scrape_serpapi(region="austin_tx")
        logger.info("[Scheduler] SerpAPI: %d signals", len(signals))
    except Exception as e:
        logger.error("[Scheduler] SerpAPI job failed: %s", e)


def _run_activejobs() -> None:
    """Scheduled job: Fetch listings from Active Jobs DB (RapidAPI)."""
    try:
        from collectors.job_boards.activejobs_adapter import scrape_activejobs
        logger.info("[Scheduler] Running Active Jobs DB fetch")
        signals = scrape_activejobs(region="austin_tx")
        logger.info("[Scheduler] Active Jobs DB: %d signals", len(signals))
    except Exception as e:
        logger.error("[Scheduler] Active Jobs DB job failed: %s", e)


def _run_juju() -> None:
    """Scheduled job: Fetch listings from Juju XML search API."""
    try:
        from collectors.job_boards.juju_adapter import scrape_juju
        logger.info("[Scheduler] Running Juju job search fetch")
        signals = scrape_juju(region="austin_tx")
        logger.info("[Scheduler] Juju: %d signals", len(signals))
    except Exception as e:
        logger.error("[Scheduler] Juju job failed: %s", e)


def _run_theirstack() -> None:
    """Scheduled job: Fetch Austin-area jobs and company intelligence from TheirStack."""
    try:
        from collectors.job_boards.theirstack_adapter import scrape_theirstack
        logger.info("[Scheduler] Running TheirStack fetch")
        signals = scrape_theirstack(region="austin_tx")
        logger.info("[Scheduler] TheirStack: %d signals", len(signals))
    except Exception as e:
        logger.error("[Scheduler] TheirStack job failed: %s", e)


def _run_jobicy() -> None:
    """Scheduled job: Fetch remote job listings from Jobicy API (hourly)."""
    try:
        from collectors.job_boards.jobicy_adapter import scrape_jobicy
        logger.info("[Scheduler] Running Jobicy fetch")
        signals = scrape_jobicy(region="austin_tx")
        logger.info("[Scheduler] Jobicy: %d signals", len(signals))
    except Exception as e:
        logger.error("[Scheduler] Jobicy job failed: %s", e)


def _run_posting_expiry() -> None:
    """Nightly sweep: mark postings past expires_at as inactive."""
    try:
        from core.database import get_session, init_db
        from postings.ingest import expire_stale_postings

        engine = init_db()
        session = get_session(engine)
        try:
            count = expire_stale_postings("austin_tx", session)
            logger.info("[Scheduler] Expiry sweep: %d postings deactivated", count)
        finally:
            session.close()

    except Exception as e:
        logger.error("[Scheduler] Posting expiry sweep failed: %s", e)


def _run_posting_purge() -> None:
    """Weekly purge: DELETE rows inactive for 90+ days to keep the table lean.

    Timeline rationale:
      - Collection date (scraped_at) anchors the record.
      - posted_date + TTL = expires_at → is_active flipped to False by sweep.
      - After 90 days of is_active=False the row is deleted permanently.
      - Gov postings (45-day TTL) survive ~135 days total from posting.
      - JobSpy postings (30-day TTL) survive ~120 days total from posting.
    """
    try:
        from datetime import datetime, timedelta

        from sqlalchemy import text

        from core.database import get_engine

        cutoff = datetime.utcnow() - timedelta(days=90)
        with get_engine().connect() as conn:
            result = conn.execute(
                text(
                    "DELETE FROM job_postings "
                    "WHERE is_active = FALSE AND expires_at < :cutoff"
                ),
                {"cutoff": cutoff},
            )
            conn.commit()
            logger.info(
                "[Scheduler] Purge: deleted %d ancient postings (expired before %s)",
                result.rowcount, cutoff.date(),
            )

    except Exception as e:
        logger.error("[Scheduler] Posting purge failed: %s", e)
