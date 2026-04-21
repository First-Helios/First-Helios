"""
Step 2 — Add H3 cell columns and indexes to local_employers and chain_locations.

Safe to re-run: uses IF NOT EXISTS / DO $$ blocks so it won't error on repeat runs.

Tables modified:
  local_employers  — h3_r6, h3_r7, h3_r8, h3_r9  + indexes on r7, r8
  chain_locations  — h3_r8, h3_r9                 + index on r8
"""

import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()
engine = create_engine(os.environ["DATABASE_URL"])

DDL = [
    # local_employers — four resolutions
    "ALTER TABLE local_employers ADD COLUMN IF NOT EXISTS h3_r6 VARCHAR(15)",
    "ALTER TABLE local_employers ADD COLUMN IF NOT EXISTS h3_r7 VARCHAR(15)",
    "ALTER TABLE local_employers ADD COLUMN IF NOT EXISTS h3_r8 VARCHAR(15)",
    "ALTER TABLE local_employers ADD COLUMN IF NOT EXISTS h3_r9 VARCHAR(15)",
    # chain_locations — two resolutions (dataset too small for r6/r7 aggregation)
    "ALTER TABLE chain_locations ADD COLUMN IF NOT EXISTS h3_r8 VARCHAR(15)",
    "ALTER TABLE chain_locations ADD COLUMN IF NOT EXISTS h3_r9 VARCHAR(15)",
    # Indexes — r7 and r8 are the query-hot resolutions
    "CREATE INDEX IF NOT EXISTS idx_le_h3_r6 ON local_employers(h3_r6)",
    "CREATE INDEX IF NOT EXISTS idx_le_h3_r7 ON local_employers(h3_r7)",
    "CREATE INDEX IF NOT EXISTS idx_le_h3_r8 ON local_employers(h3_r8)",
    "CREATE INDEX IF NOT EXISTS idx_le_h3_r9 ON local_employers(h3_r9)",
    "CREATE INDEX IF NOT EXISTS idx_cl_h3_r8 ON chain_locations(h3_r8)",
]

with engine.begin() as conn:
    for stmt in DDL:
        print(f"  {stmt[:80]}...")
        conn.execute(text(stmt))

print("\nDone. Columns and indexes created.")
