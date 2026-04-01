"""
collector_main.py — Standalone data collection process for First-Helios.

Runs independently of the Flask web server. Both processes connect to the
same PostgreSQL database; neither depends on the other being alive.

Usage:
    python collector_main.py              # start scheduler, block until Ctrl-C
    python collector_main.py --run-now    # fire all enabled jobs once, then exit
    python collector_main.py --job jobspy # fire one specific job by ID, then exit

The --run-now flag is designed for first-run testing and catch-up after
the server has been down. Jobs run sequentially so logs are easy to read.
"""

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_PROJECT_ROOT = Path(__file__).parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("collector_main")


# ── Job registry — maps scheduler job IDs to their run functions ──────────────
# Keep in sync with core/scheduler.py.  The order here is the execution order
# used by --run-now (long-running scrapes first, maintenance last).

def _get_job_registry() -> dict:
    """Import and return all job functions keyed by scheduler job ID."""
    from core.scheduler import (
        _run_jobspy,
        _run_reddit,
        _run_austin_gov,
        _run_usajobs,
        _run_serpapi_jobs,
        _run_theirstack,
        _run_jobicy,
        _run_activejobs,
        _run_juju,
        _run_bls,
        _run_qcew,
        _run_cbp,
        _run_nlrb,
        _run_warn,
        _run_baseline_recompute,
        _run_alltheplaces,
        _run_overture_chain,
        _run_osm,
        _run_overture_local,
        _run_reviews,
        _run_posting_expiry,
        _run_posting_purge,
    )
    return {
        # ── Job postings (run daily) ──────────────────────────────────────────
        "austin_gov":       _run_austin_gov,
        "usajobs":          _run_usajobs,
        "jobicy":           _run_jobicy,
        "serpapi_jobs":     _run_serpapi_jobs,
        "theirstack":       _run_theirstack,
        "jobspy":           _run_jobspy,
        "activejobs":       _run_activejobs,
        "juju":             _run_juju,
        "reddit":           _run_reddit,
        # ── Labor market (weekly/monthly — skip guards inside each fn) ────────
        "bls":              _run_bls,
        "qcew":             _run_qcew,
        "cbp":              _run_cbp,
        "nlrb":             _run_nlrb,
        "warn_tx":          _run_warn,
        "baseline_recompute": _run_baseline_recompute,
        # ── Employer discovery (Sunday-only in scheduler; always runs here) ───
        "atp_starbucks_austin":      _run_alltheplaces,
        "overture_starbucks_austin": _run_overture_chain,
        "osm_starbucks_austin":      _run_osm,
        "overture_local_austin":     _run_overture_local,
        # ── Sentiment ─────────────────────────────────────────────────────────
        "google_maps":      _run_reviews,
        # ── Maintenance ───────────────────────────────────────────────────────
        "posting_expiry":   _run_posting_expiry,
        "posting_purge":    _run_posting_purge,
    }


# ── Daily job IDs — the ones that make sense to fire on --run-now ─────────────
# Excludes weekly/monthly labor-market jobs whose skip guards will say "no data".
DAILY_JOB_IDS = [
    "austin_gov",
    "usajobs",
    "jobicy",
    "serpapi_jobs",
    "theirstack",
    "jobspy",
    "activejobs",
    "juju",
    "reddit",
    "posting_expiry",
]


def run_jobs_now(job_ids: list[str], registry: dict) -> None:
    """Run the given job IDs sequentially and report results."""
    total = len(job_ids)
    passed, failed = 0, 0

    for i, job_id in enumerate(job_ids, 1):
        fn = registry.get(job_id)
        if fn is None:
            logger.warning("[%d/%d] Unknown job ID: %s — skipping", i, total, job_id)
            continue

        logger.info("=" * 60)
        logger.info("[%d/%d] Starting job: %s", i, total, job_id)
        logger.info("=" * 60)
        t0 = time.time()
        try:
            fn()
            elapsed = time.time() - t0
            logger.info("[%d/%d] ✓ %s finished in %.1fs", i, total, job_id, elapsed)
            passed += 1
        except Exception as exc:
            elapsed = time.time() - t0
            logger.error("[%d/%d] ✗ %s FAILED after %.1fs: %s", i, total, job_id, elapsed, exc)
            failed += 1

    logger.info("=" * 60)
    logger.info("Done. %d passed, %d failed (of %d jobs)", passed, failed, total)


def run_scheduler() -> None:
    """Start APScheduler and block until SIGTERM or KeyboardInterrupt."""
    from core.database import init_db
    from core.scheduler import init_scheduler

    logger.info("[collector_main] Initializing database …")
    init_db()

    logger.info("[collector_main] Starting scheduler …")
    scheduler = init_scheduler()

    def _shutdown(signum, frame):
        logger.info("[collector_main] Signal %d received — shutting down …", signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("[collector_main] Scheduler running with %d jobs. Press Ctrl-C to stop.",
                len(scheduler.get_jobs()))

    for job in scheduler.get_jobs():
        logger.info("  %-35s next: %s", job.id,
                    job.next_run_time.strftime("%Y-%m-%d %H:%M:%S") if job.next_run_time else "—")

    while scheduler.running:
        time.sleep(30)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="First-Helios data collector — scheduler or one-shot runner"
    )
    parser.add_argument(
        "--run-now",
        action="store_true",
        help="Fire all daily collection jobs once in sequence, then exit",
    )
    parser.add_argument(
        "--run-all",
        action="store_true",
        help="Fire every registered job (including weekly/monthly), then exit",
    )
    parser.add_argument(
        "--job",
        metavar="JOB_ID",
        help="Fire a single job by its scheduler ID, then exit",
    )
    parser.add_argument(
        "--list-jobs",
        action="store_true",
        help="Print all registered job IDs and exit",
    )
    args = parser.parse_args()

    from core.database import init_db
    logger.info("[collector_main] Initializing database …")
    init_db()

    registry = _get_job_registry()

    if args.list_jobs:
        print("\nRegistered job IDs:")
        for job_id in registry:
            marker = "*" if job_id in DAILY_JOB_IDS else " "
            print(f"  {marker} {job_id}")
        print("\n* = included in --run-now")
        return

    if args.job:
        if args.job not in registry:
            logger.error("Unknown job ID: %s. Use --list-jobs to see all IDs.", args.job)
            sys.exit(1)
        logger.info("[collector_main] Running single job: %s", args.job)
        run_jobs_now([args.job], registry)
        return

    if args.run_all:
        logger.info("[collector_main] --run-all: firing all %d registered jobs", len(registry))
        run_jobs_now(list(registry.keys()), registry)
        return

    if args.run_now:
        logger.info("[collector_main] --run-now: firing %d daily jobs", len(DAILY_JOB_IDS))
        run_jobs_now(DAILY_JOB_IDS, registry)
        return

    # Default: run as persistent scheduler process
    run_scheduler()


if __name__ == "__main__":
    main()
