#!/usr/bin/env python3
"""Build a Spirit Pool dev-user capture queue from scrape denial signals.

Produces a prioritized JSON queue of URLs our first-party scraper couldn't
usefully retrieve. The operator opens these URLs in the enrolled Firefox
profile and lets the browser extension POST the signed full-page capture to
/api/spiritpool/dev/page-capture.

What counts as "scraper denial" here:

  * restaurant_urls.last_http_status IS NULL but last_checked IS NOT NULL
    (fetcher attempted but no status landed — silent failure, typically 403
    / Cloudflare / anti-bot)
  * restaurant_urls.last_http_status NOT IN (200, 201, 202, 204, 304)
  * The URL has zero menu_pages rows AND its brand has no deal_observations

Priority:
  P0: brand has >=20 Austin locations, no observations
  P1: brand has >=5 Austin locations, no observations
  P2: brand has 1-4 Austin locations, no observations
  P3: independent (no brand_group) but active in Austin

The queue is additive to config/spiritpool_capture_manifest.json, which
carries aggregator-level targets (retailmenot/eatdrinkdeals). This script
targets FIRST-PARTY brand websites.

Writes:
  data/cache/spiritpool_dev/capture_queue.json

The queue file is operational state — treat it like a worklist, not a config
artifact. It will change every run.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import os
from datetime import datetime, timezone

from config.paths import CACHE_DIR

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = CACHE_DIR / "spiritpool_dev" / "capture_queue.json"
DEFAULT_CAPTURES_DIR = CACHE_DIR / "spiritpool_dev" / "page_captures"

_OK_STATUSES = {200, 201, 202, 204, 304}


def _connect():
    import psycopg
    dsn = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
    if not dsn:
        raise RuntimeError("DATABASE_URL not set")
    return psycopg.connect(dsn)


def _already_captured_hosts(captures_dir: Path) -> set[str]:
    """Hosts we already have at least one dev-capture bundle for."""
    from urllib.parse import urlparse
    hosts: set[str] = set()
    if not captures_dir.exists():
        return hosts
    for bundle_path in captures_dir.glob("*.json"):
        try:
            data = json.loads(bundle_path.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = data.get("canonical_url") or data.get("url") or ""
        host = urlparse(url).netloc.lower()
        if host:
            hosts.add(host)
    return hosts


def _priority_for(austin_locs: int, has_brand_group: bool) -> str:
    if not has_brand_group:
        return "P3"
    if austin_locs >= 20:
        return "P0"
    if austin_locs >= 5:
        return "P1"
    return "P2"


def build_queue(region: str, already_captured: set[str], limit_per_priority: int) -> dict[str, Any]:
    from urllib.parse import urlparse

    rows: list[dict[str, Any]] = []
    with _connect() as conn, conn.cursor() as cur:
        # URLs that were checked but failed (NULL status AFTER a last_checked
        # timestamp = scrape attempted, no 200 returned).
        cur.execute(
            """
            SELECT
                ru.id, ru.url, ru.last_http_status, ru.last_checked,
                bg.id AS brand_group_id, bg.canonical_name, bg.industry,
                COUNT(DISTINCT le.id) FILTER (WHERE le.region = %s AND le.is_active) AS austin_locs,
                COUNT(DISTINCT mp.id) AS menu_pages,
                COUNT(DISTINCT obs.id) AS deal_obs
            FROM restaurant_urls ru
            LEFT JOIN brand_groups bg ON bg.id = ru.brand_group_id
            LEFT JOIN local_employers le ON le.brand_group_id = bg.id
            LEFT JOIN menu_pages mp ON mp.url = ru.url
            LEFT JOIN site_assignments sa ON sa.brand_group_id = bg.id
            LEFT JOIN deal_observations obs ON obs.site_identity_id = sa.site_identity_id
            WHERE ru.is_active
              AND (
                    (ru.last_checked IS NOT NULL AND ru.last_http_status IS NULL)
                 OR (ru.last_http_status IS NOT NULL AND ru.last_http_status NOT IN (200,201,202,204,304))
              )
            GROUP BY ru.id, ru.url, ru.last_http_status, ru.last_checked,
                     bg.id, bg.canonical_name, bg.industry
            HAVING COUNT(DISTINCT mp.id) = 0 AND COUNT(DISTINCT obs.id) = 0
            ORDER BY austin_locs DESC NULLS LAST, ru.last_checked DESC NULLS LAST
            """,
            (region,),
        )
        for r in cur.fetchall():
            (url_id, url, status, checked, bg_id, canonical, industry,
             austin_locs, _mp, _do) = r
            host = urlparse(url).netloc.lower() if url else ""
            # Skip if we already have a dev capture for this host (one is
            # enough to unblock the adapter; operator can re-capture manually
            # if content shifted).
            if host and host in already_captured:
                continue
            priority = _priority_for(austin_locs or 0, bg_id is not None)
            rows.append({
                "url_id": url_id,
                "url": url,
                "host": host,
                "last_http_status": status,
                "last_checked": checked.isoformat() if checked else None,
                "brand_group_id": bg_id,
                "canonical_name": canonical,
                "industry": industry,
                "austin_locations": austin_locs or 0,
                "priority": priority,
                "recommended_action": "capture_via_spiritpool_dev_browser",
            })

    # Cap per-priority AND dedup by URL (same chain URL often has 100s of
    # location rows behind it; operator only needs to capture it once).
    capped: list[dict[str, Any]] = []
    bucket: dict[str, int] = defaultdict(int)
    seen_urls: set[str] = set()
    for row in rows:
        if row["url"] in seen_urls:
            continue
        seen_urls.add(row["url"])
        if bucket[row["priority"]] < limit_per_priority:
            capped.append(row)
            bucket[row["priority"]] += 1

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "region": region,
        "total_candidates": len(rows),
        "queued": len(capped),
        "skipped_already_captured_hosts": len(already_captured),
        "per_priority": {k: bucket[k] for k in sorted(bucket)},
    }
    return {
        "summary": summary,
        "entries": capped,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="austin_tx")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--captures-dir", type=Path, default=DEFAULT_CAPTURES_DIR)
    parser.add_argument("--limit-per-priority", type=int, default=25)
    args = parser.parse_args()

    already = _already_captured_hosts(args.captures_dir)
    queue = build_queue(args.region, already, args.limit_per_priority)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(queue, indent=2, sort_keys=True, default=str), encoding="utf-8")

    s = queue["summary"]
    logger.info("=" * 72)
    logger.info("SPIRITPOOL DEV CAPTURE QUEUE (first-party scrape denials)")
    logger.info("=" * 72)
    logger.info("Region                       : %s", s["region"])
    logger.info("Candidate URLs               : %d", s["total_candidates"])
    logger.info("Queued (capped)              : %d", s["queued"])
    logger.info("Already captured hosts (skip): %d", s["skipped_already_captured_hosts"])
    logger.info("Per priority                 : %s", s["per_priority"])
    logger.info("")
    for entry in queue["entries"][:20]:
        logger.info("  [%s] %-30s locs=%-4d %s",
                    entry["priority"],
                    (entry["canonical_name"] or "(unbranded)")[:30],
                    entry["austin_locations"],
                    entry["url"][:80])
    logger.info("")
    logger.info("Queue written: %s", args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
