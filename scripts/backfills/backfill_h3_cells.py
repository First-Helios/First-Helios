"""
Step 3 — Backfill H3 cell columns for local_employers and chain_locations.

Processes rows in batches of 2000. Safe to re-run: skips rows where h3_r7
is already populated (use --force to recompute everything).

Usage:
  python scripts/backfills/backfill_h3_cells.py           # skip already-filled rows
  python scripts/backfills/backfill_h3_cells.py --force   # recompute all rows
"""

import os
import sys
import time
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
import h3

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])

FORCE = "--force" in sys.argv
BATCH = 2000


def backfill_table(conn, table, id_col, resolutions):
    where = "" if FORCE else f"AND h3_r{resolutions[0]} IS NULL"
    count_sql = f"SELECT COUNT(*) FROM {table} WHERE lat IS NOT NULL AND lng IS NOT NULL {where}"
    total = conn.execute(text(count_sql)).scalar()
    print(f"\n{table}: {total} rows to process")
    if total == 0:
        print("  Nothing to do.")
        return

    processed = 0
    t0 = time.time()

    while True:
        # Always OFFSET 0 — the WHERE clause shrinks as rows are filled,
        # so using a moving offset would skip every other batch.
        rows = conn.execute(text(
            f"SELECT {id_col}, lat, lng FROM {table} "
            f"WHERE lat IS NOT NULL AND lng IS NOT NULL {where} "
            f"ORDER BY {id_col} LIMIT {BATCH}"
        )).fetchall()

        if not rows:
            break

        updates = []
        for row in rows:
            rid, lat, lng = row
            cells = {f"h3_r{r}": h3.latlng_to_cell(lat, lng, r) for r in resolutions}
            cells[id_col] = rid
            updates.append(cells)

        set_clause = ", ".join(f"h3_r{r} = :h3_r{r}" for r in resolutions)
        conn.execute(
            text(f"UPDATE {table} SET {set_clause} WHERE {id_col} = :{id_col}"),
            updates,
        )

        processed += len(rows)
        elapsed = time.time() - t0
        rate = processed / elapsed if elapsed > 0 else 0
        print(f"  {processed}/{total}  ({rate:.0f} rows/s)", end="\r")

    print(f"  {processed}/{total} done in {time.time()-t0:.1f}s          ")


with engine.begin() as conn:
    backfill_table(conn, "local_employers", "id",       resolutions=[6, 7, 8, 9])
    backfill_table(conn, "chain_locations", "store_num", resolutions=[8, 9])

print("\nBackfill complete.")

# Quick sanity check
with engine.connect() as conn:
    r = conn.execute(text(
        "SELECT COUNT(*), COUNT(h3_r7), COUNT(DISTINCT h3_r7), COUNT(DISTINCT h3_r8) "
        "FROM local_employers WHERE lat IS NOT NULL"
    )).fetchone()
    print(f"\nlocal_employers: {r[0]} total | {r[1]} h3_r7 filled | "
          f"{r[2]} distinct r7 cells | {r[3]} distinct r8 cells")

    r = conn.execute(text(
        "SELECT COUNT(*), COUNT(h3_r8), COUNT(DISTINCT h3_r8) FROM chain_locations"
    )).fetchone()
    print(f"chain_locations: {r[0]} total | {r[1]} h3_r8 filled | {r[2]} distinct r8 cells")
