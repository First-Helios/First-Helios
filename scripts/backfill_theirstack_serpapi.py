"""
scripts/backfill_theirstack_serpapi.py — Re-ingest cached TheirStack and SerpAPI
data using the fixed adapters so that lat/lng, H3 cells, and address fields
are populated for existing rows.

Safe to run repeatedly — uses the same upsert logic as normal ingest
(ON CONFLICT DO UPDATE), so rows are updated in place.

Usage:
    python scripts/backfill_theirstack_serpapi.py
    python scripts/backfill_theirstack_serpapi.py --dry-run   # preview only
"""

import argparse
import logging
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(_PROJECT_ROOT / ".env")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _preview_signals(signals, label):
    """Print a summary table for dry-run mode."""
    print(f"\n{'='*70}")
    print(f"  {label}: {len(signals)} signals")
    print(f"{'='*70}")
    print(f"  {'Title':<35} | {'Address':<25} | {'Method':<15} | {'Lat':>8}")
    print(f"  {'-'*35}-+-{'-'*25}-+-{'-'*15}-+-{'-'*8}")
    for s in signals:
        m = s.metadata or {}
        addr = str(m.get("address") or "")[:25]
        method = str(m.get("address_method") or "")[:15]
        lat = m.get("lat")
        lat_s = f"{lat:.4f}" if lat else "None"
        print(f"  {(s.role_title or '?')[:35]:<35} | {addr:<25} | {method:<15} | {lat_s:>8}")


def backfill(dry_run: bool = False):
    from collectors.cache import read_cache
    from collectors.job_boards.theirstack_adapter import TheirStackAdapter
    from collectors.job_boards.serpapi_adapter import SerpApiAdapter

    region = "austin_tx"

    # ── TheirStack ─────────────────────────────────────────────────────────
    ts_cached = read_cache("theirstack", ttl_minutes=999999)
    ts_signals = []
    if ts_cached:
        adapter = TheirStackAdapter()
        ts_signals = adapter._jobs_to_signals(ts_cached, region)
        logger.info("[Backfill] TheirStack: %d signals from cache", len(ts_signals))
    else:
        logger.warning("[Backfill] No TheirStack cache found")

    # ── SerpAPI ────────────────────────────────────────────────────────────
    sp_cached = read_cache("serpapi_google_jobs", ttl_minutes=999999)
    sp_signals = []
    if sp_cached:
        adapter = SerpApiAdapter()
        sp_signals = adapter._jobs_to_signals(sp_cached, region)
        logger.info("[Backfill] SerpAPI: %d signals from cache", len(sp_signals))
    else:
        logger.warning("[Backfill] No SerpAPI cache found")

    if dry_run:
        _preview_signals(ts_signals, "TheirStack")
        _preview_signals(sp_signals, "SerpAPI")

        # Count expected coverage
        for label, sigs in [("TheirStack", ts_signals), ("SerpAPI", sp_signals)]:
            has_latlong = sum(1 for s in sigs if s.metadata.get("lat") is not None)
            has_addr = sum(1 for s in sigs if s.metadata.get("address"))
            print(f"\n  {label} coverage: {has_latlong}/{len(sigs)} have lat/lng, {has_addr}/{len(sigs)} have address")
        return

    # ── Ingest ─────────────────────────────────────────────────────────────
    from postings.ingest import ingest_job_posting
    from core.database import get_session, init_db

    engine = init_db()
    session = get_session(engine)
    try:
        for label, sigs in [("TheirStack", ts_signals), ("SerpAPI", sp_signals)]:
            ingested = 0
            for signal in sigs:
                result = ingest_job_posting(signal, region, session=session)
                if result is not None:
                    ingested += 1
            logger.info("[Backfill] %s: ingested %d/%d", label, ingested, len(sigs))
    finally:
        session.close()

    # ── Verify ─────────────────────────────────────────────────────────────
    session2 = get_session(engine)
    try:
        from sqlalchemy import text
        r = session2.execute(text("""
            SELECT source,
                   COUNT(*) total,
                   SUM(CASE WHEN h3_r7 IS NOT NULL THEN 1 ELSE 0 END) has_h3,
                   SUM(CASE WHEN lat IS NOT NULL THEN 1 ELSE 0 END) has_latlong
            FROM job_postings
            WHERE source IN ('theirstack', 'serpapi_google_jobs')
            GROUP BY source
        """))
        print(f"\n{'source':<25} {'total':>6} {'h3':>6} {'lat/lng':>8}")
        print("-" * 50)
        for row in r:
            print(f"{row[0]:<25} {row[1]:>6} {row[2]:>6} {row[3]:>8}")
    finally:
        session2.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill geocoding for TheirStack + SerpAPI rows")
    parser.add_argument("--dry-run", action="store_true", help="Preview signals without writing to DB")
    args = parser.parse_args()
    backfill(dry_run=args.dry_run)
