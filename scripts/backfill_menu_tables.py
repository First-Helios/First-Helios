#!/usr/bin/env python3
"""
scripts/backfill_menu_tables.py — Backfill menu graph tables from cached debug bundles.

Reads every bundle under data/cache/website_scrape_debug/, extracts the
menu_persistence_shape, and upserts it into the 5 menu graph DB tables.

Usage
-----
    python scripts/backfill_menu_tables.py
    python scripts/backfill_menu_tables.py --dry-run
    python scripts/backfill_menu_tables.py --limit 10
    python scripts/backfill_menu_tables.py --debug-dir /path/to/bundles
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# ── Project root on path ──────────────────────────────────────────────────────
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from collectors.meal_deals.menu_db_writer import UpsertResult, upsert_menu_shape
from collectors.meal_deals.website_scrape_audit_utils import load_debug_bundles
from config.paths import WEBSITE_SCRAPE_DEBUG_DIR
from core.database import get_engine, get_session

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Backfill menu graph tables from debug bundles.")
    p.add_argument("--debug-dir", type=Path, default=WEBSITE_SCRAPE_DEBUG_DIR,
                   help="Directory containing website_scrape_debug JSON bundles")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse and report what would be written without touching the DB")
    p.add_argument("--limit", type=int, default=None,
                   help="Stop after processing N bundles (useful for smoke tests)")
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    debug_dir: Path = args.debug_dir
    if not debug_dir.exists():
        logger.error("debug-dir not found: %s", debug_dir)
        sys.exit(1)

    logger.info("Loading bundles from %s", debug_dir)
    bundles, invalid = load_debug_bundles(debug_dir)
    logger.info("Loaded %d bundles (%d invalid JSON skipped)", len(bundles), invalid)

    if args.limit:
        keys = list(bundles.keys())[: args.limit]
        bundles = {k: bundles[k] for k in keys}
        logger.info("Limiting to %d bundles", len(bundles))

    # Totals across all bundles
    totals = UpsertResult()
    processed = 0
    skipped_no_shape = 0
    failed = 0

    engine = None if args.dry_run else get_engine()

    for site_key, bundle in bundles.items():
        shape = bundle.get("menu_persistence_shape")
        if not shape:
            skipped_no_shape += 1
            continue

        if args.dry_run:
            pages = len(shape.get("pages") or [])
            sections = len(shape.get("sections") or [])
            items = len(shape.get("items") or [])
            price_points = len(shape.get("price_points") or [])
            modifiers = len(shape.get("modifiers") or [])
            logger.info("[DRY-RUN] %s → pages=%d sections=%d items=%d pp=%d mod=%d",
                        site_key, pages, sections, items, price_points, modifiers)
            totals.pages_written += pages
            totals.sections_written += sections
            totals.items_written += items
            totals.price_points_written += price_points
            totals.modifiers_written += modifiers
            processed += 1
            continue

        try:
            session = get_session(engine)
            result = upsert_menu_shape(session, shape)
            session.commit()
            session.close()
            totals.pages_written += result.pages_written
            totals.sections_written += result.sections_written
            totals.items_written += result.items_written
            totals.price_points_written += result.price_points_written
            totals.modifiers_written += result.modifiers_written
            totals.fk_violations_skipped += result.fk_violations_skipped
            processed += 1
            if result.errors:
                logger.warning("[%s] partial errors: %s", site_key, result.errors)
        except Exception as exc:
            logger.error("[%s] failed: %s", site_key, exc)
            failed += 1

    print()
    print("── Backfill complete ──────────────────────────────────────────")
    print(f"  Bundles processed : {processed}")
    print(f"  No shape (skipped): {skipped_no_shape}")
    print(f"  Failed            : {failed}")
    print(f"  FK violations skip: {totals.fk_violations_skipped}")
    print()
    print(f"  Rows written:")
    print(f"    menu_pages        : {totals.pages_written}")
    print(f"    menu_sections     : {totals.sections_written}")
    print(f"    menu_items        : {totals.items_written}")
    print(f"    menu_price_points : {totals.price_points_written}")
    print(f"    menu_modifiers    : {totals.modifiers_written}")
    print("───────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    main()
