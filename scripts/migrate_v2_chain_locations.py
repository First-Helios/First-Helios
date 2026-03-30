#!/usr/bin/env python3
"""
Database Migration: v2 — chain_locations + pseudo-data cleanup.

What this does:
  1. Creates the new `chain_locations` table (via init_db).
  2. Removes ALL pseudo-store records from `stores`
     (store_num prefixed BLS-, QCEW-, CPI-, ECI-, JOLTS-, OEWS-, LAUS-, CBP-).
  3. Migrates any *real* store records from `stores` → `chain_locations`.
  4. Removes pseudo-signals from `signals` (referencing pseudo-stores).
  5. Removes pseudo-scores from `scores` (referencing pseudo-stores).
  6. Removes government macro data from `wage_index` that was incorrectly
     stored as job-level wage observations.
  7. Renames old `stores` table to `stores_deprecated` for safety.

Ground-truth economic tables are UNTOUCHED:
  qcew_data, jolts_data, oews_data, laus_data, cbp_data,
  labor_market_baseline, api_request_log, api_sources, rate_budgets.

Run:  python scripts/migrate_v2_chain_locations.py
      python scripts/migrate_v2_chain_locations.py --dry-run   (preview only)

Prereq: All model changes in backend/database.py must be applied first.
"""

import argparse
import logging
import shutil
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.database import DB_PATH, Base, get_engine, get_session, init_db

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("migrate_v2")

# Prefixes that mark pseudo-store records (economic data, not real locations).
PSEUDO_PREFIXES = ("BLS-", "QCEW-", "CPI-", "ECI-", "JOLTS-", "OEWS-", "LAUS-", "CBP-")

# Wage-index sources that are government macro data, not job-level observations.
MACRO_WAGE_SOURCES = ("qcew",)
MACRO_WAGE_SOURCE_LIKE = "bls_%"  # matches bls_ces_*, bls_cpi_*, etc.


def _backup_db() -> Path:
    """Create a timestamped backup of tracker.db."""
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup = DB_PATH.parent / f"tracker_pre_v2_{ts}.db"
    shutil.copy2(DB_PATH, backup)
    log.info("Backup created: %s", backup)
    return backup


def _count(engine, sql: str) -> int:
    """Execute a COUNT query and return the integer."""
    from sqlalchemy import text
    with engine.connect() as conn:
        return conn.execute(text(sql)).scalar() or 0


def _exec(engine, sql: str, dry_run: bool = False) -> int:
    """Execute a DML statement. Returns rowcount. Skips if dry_run."""
    from sqlalchemy import text
    if dry_run:
        count = _count(engine, sql.replace("DELETE FROM", "SELECT COUNT(*) FROM", 1))
        log.info("  [dry-run] Would affect ~%d rows: %s", count, sql[:120])
        return count
    with engine.begin() as conn:
        result = conn.execute(text(sql))
        return result.rowcount


def migrate(dry_run: bool = False):
    """Run the full migration."""

    if not DB_PATH.exists():
        log.error("Database not found at %s — run init_db first.", DB_PATH)
        sys.exit(1)

    # ── 0. Backup ────────────────────────────────────────────────────────
    if not dry_run:
        _backup_db()

    # ── 1. Create new tables (chain_locations + any other new models) ────
    log.info("Step 1: Creating new tables via init_db...")
    engine = init_db()
    log.info("  chain_locations table created (or already exists).")

    # ── 2. Assess pseudo-store contamination ─────────────────────────────
    log.info("Step 2: Assessing pseudo-store contamination...")
    from sqlalchemy import text, inspect

    inspector = inspect(engine)
    if "stores" not in inspector.get_table_names():
        log.info("  Old 'stores' table not found — nothing to migrate.")
    else:
        pseudo_where = " OR ".join(
            f"store_num LIKE '{p}%'" for p in PSEUDO_PREFIXES
        )
        real_where = " AND ".join(
            f"store_num NOT LIKE '{p}%'" for p in PSEUDO_PREFIXES
        )

        total_stores = _count(engine, "SELECT COUNT(*) FROM stores")
        pseudo_stores = _count(engine, f"SELECT COUNT(*) FROM stores WHERE {pseudo_where}")
        real_stores = _count(engine, f"SELECT COUNT(*) FROM stores WHERE {real_where}")

        log.info("  Total stores: %d  (pseudo: %d, real: %d)", total_stores, pseudo_stores, real_stores)

        # ── 3. Migrate real stores to chain_locations ────────────────────
        if real_stores > 0:
            log.info("Step 3: Migrating %d real stores to chain_locations...", real_stores)
            if not dry_run:
                with engine.begin() as conn:
                    conn.execute(text(f"""
                        INSERT OR IGNORE INTO chain_locations
                            (store_num, chain, industry, store_name, address,
                             lat, lng, region, first_seen, last_seen, is_active)
                        SELECT
                            store_num, chain, industry, store_name, address,
                            lat, lng, region, first_seen, last_seen, is_active
                        FROM stores
                        WHERE {real_where}
                    """))
                log.info("  Migrated %d real stores.", real_stores)
            else:
                log.info("  [dry-run] Would migrate %d real stores.", real_stores)
        else:
            log.info("Step 3: No real stores to migrate (all %d are pseudo-data).", total_stores)

        # ── 4. Clean pseudo-signals ──────────────────────────────────────
        log.info("Step 4: Cleaning pseudo-signals...")
        n = _exec(engine, f"DELETE FROM signals WHERE {pseudo_where.replace('store_num', 'store_num')}", dry_run)
        log.info("  Removed %d pseudo-signals.", n)

        # ── 5. Clean pseudo-scores ───────────────────────────────────────
        log.info("Step 5: Cleaning pseudo-scores...")
        n = _exec(engine, f"DELETE FROM scores WHERE {pseudo_where}", dry_run)
        log.info("  Removed %d pseudo-scores.", n)

        # ── 6. Clean pseudo-snapshots ────────────────────────────────────
        log.info("Step 6: Cleaning pseudo-snapshots referencing macro sources...")
        n_snap = _count(engine, "SELECT COUNT(*) FROM snapshots WHERE source IN ('bls_cpi','qcew','bls_eci')")
        if n_snap > 0:
            _exec(engine, "DELETE FROM snapshots WHERE source IN ('bls_cpi','qcew','bls_eci')", dry_run)
            log.info("  Removed %d pseudo-snapshots.", n_snap)
        else:
            log.info("  No pseudo-snapshots found.")

        # ── 7. Clean macro data from wage_index ──────────────────────────
        log.info("Step 7: Cleaning government macro data from wage_index...")
        wage_total = _count(engine, "SELECT COUNT(*) FROM wage_index")
        wage_macro = _count(engine,
            "SELECT COUNT(*) FROM wage_index WHERE source LIKE 'bls_%' OR source = 'qcew'"
        )
        wage_real = wage_total - wage_macro
        log.info("  wage_index: %d total, %d macro (will remove), %d real (will keep)",
                 wage_total, wage_macro, wage_real)
        _exec(engine, "DELETE FROM wage_index WHERE source LIKE 'bls_%' OR source = 'qcew'", dry_run)
        log.info("  Cleaned %d macro entries from wage_index.", wage_macro)

        # ── 8. Rename old stores table ───────────────────────────────────
        log.info("Step 8: Deprecating old 'stores' table...")
        if not dry_run:
            if "stores_deprecated" in inspector.get_table_names():
                with engine.begin() as conn:
                    conn.execute(text("DROP TABLE stores_deprecated"))
            with engine.begin() as conn:
                conn.execute(text("ALTER TABLE stores RENAME TO stores_deprecated"))
            log.info("  Renamed 'stores' → 'stores_deprecated'.")
        else:
            log.info("  [dry-run] Would rename 'stores' → 'stores_deprecated'.")

    # ── Summary ──────────────────────────────────────────────────────────
    log.info("")
    log.info("═══ Migration Summary ═══")
    cl_count = _count(engine, "SELECT COUNT(*) FROM chain_locations") if not dry_run else 0
    sig_count = _count(engine, "SELECT COUNT(*) FROM signals")
    score_count = _count(engine, "SELECT COUNT(*) FROM scores")
    wage_count = _count(engine, "SELECT COUNT(*) FROM wage_index")
    log.info("  chain_locations : %d rows", cl_count)
    log.info("  signals         : %d rows", sig_count)
    log.info("  scores          : %d rows", score_count)
    log.info("  wage_index      : %d rows", wage_count)
    log.info("")

    # Ground-truth tables (unchanged)
    for tbl in ("qcew_data", "jolts_data", "oews_data", "laus_data", "cbp_data", "labor_market_baseline"):
        c = _count(engine, f"SELECT COUNT(*) FROM {tbl}")
        log.info("  %s : %d rows (unchanged)", tbl, c)

    log.info("")
    if dry_run:
        log.info("DRY RUN — no changes were made. Run without --dry-run to apply.")
    else:
        log.info("Migration complete. Backup stored alongside tracker.db.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate tracker.db to v2 schema")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without modifying the database")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)
