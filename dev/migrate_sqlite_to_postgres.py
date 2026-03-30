"""
dev_toolkit/migrate_sqlite_to_postgres.py

One-shot migration of all non-employer tables from SQLite → PostgreSQL.

local_employers is intentionally excluded — it will be rebuilt fresh from the
Overture GeoJSON through the new ingest layer (run rebuild_local_employers.sh
after this script).

Tables migrated:
  chain_locations, signals, snapshots, scores, wage_index
  qcew_data, cbp_data, revelio_*, labor_baseline, api_sources,
  api_request_log, rate_budgets, ref_brands, ref_industries,
  ref_employer_name_index (deprecated — brand_groups replaces this)

Usage:
    python dev_toolkit/migrate_sqlite_to_postgres.py
    python dev_toolkit/migrate_sqlite_to_postgres.py --sqlite data/tracker.db
    python dev_toolkit/migrate_sqlite_to_postgres.py --dry-run
"""

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# Tables to migrate in dependency order (parents before children).
# local_employers is excluded — rebuilt fresh via ingest layer.
MIGRATE_TABLES = [
    "ref_brands",
    "ref_industries",
    "ref_employer_name_index",
    "chain_locations",
    "signals",
    "snapshots",
    "scores",
    "wage_index",
    "qcew_data",
    "cbp_data",
    "labor_baseline",
    "api_sources",
    "api_request_log",
    "rate_budgets",
    "revelio_employment",
    "revelio_hiring",
    "revelio_postings",
    "revelio_salaries",
    "revelio_layoffs",
]

SKIP_TABLES = {"local_employers", "brand_groups"}


def migrate(sqlite_path: Path, pg_url: str, dry_run: bool = False) -> None:
    import sqlalchemy as sa
    from sqlalchemy import inspect, text

    logger.info("Source : sqlite:///%s", sqlite_path)
    logger.info("Target : %s", pg_url)
    if dry_run:
        logger.info("[dry-run] No data will be written.")

    sqlite_engine = sa.create_engine(f"sqlite:///{sqlite_path}")
    pg_engine = sa.create_engine(pg_url, pool_pre_ping=True)

    # Init all ORM models on Postgres so tables exist
    logger.info("Creating schema on Postgres…")
    if not dry_run:
        from backend.database import Base, init_db
        import backend.models.reference  # noqa: F401 — registers reference models
        import backend.metadata          # noqa: F401 — registers metadata models
        os.environ["DATABASE_URL"] = pg_url
        init_db()

    sqlite_inspector = inspect(sqlite_engine)
    pg_inspector = inspect(pg_engine)
    existing_sqlite = set(sqlite_inspector.get_table_names())
    existing_pg = set(pg_inspector.get_table_names())

    total_rows = 0

    # Detect boolean columns per table in Postgres so we can cast SQLite 0/1 → True/False
    def _bool_cols(inspector, table_name: str) -> set[str]:
        return {
            c["name"]
            for c in inspector.get_columns(table_name)
            if str(c["type"]).upper().startswith("BOOL")
        }

    with sqlite_engine.connect() as src, pg_engine.connect() as dst:
        for table_name in MIGRATE_TABLES:
            if table_name in SKIP_TABLES:
                logger.info("  %-35s SKIPPED (excluded)", table_name)
                continue
            if table_name not in existing_sqlite:
                logger.info("  %-35s SKIPPED (not in SQLite)", table_name)
                continue
            if table_name not in existing_pg:
                logger.warning("  %-35s SKIPPED (not in Postgres — schema mismatch?)", table_name)
                continue

            rows = src.execute(text(f"SELECT * FROM {table_name}")).fetchall()
            result_proxy = src.execute(text(f"SELECT * FROM {table_name} LIMIT 0"))
            col_list = list(result_proxy.keys())

            if not rows:
                logger.info("  %-35s 0 rows (empty)", table_name)
                continue

            logger.info("  %-35s %d rows", table_name, len(rows))

            if not dry_run:
                bool_columns = _bool_cols(pg_inspector, table_name)

                # Truncate destination before insert to avoid duplicate key errors
                dst.execute(text(f"TRUNCATE TABLE {table_name} CASCADE"))
                dst.commit()

                batch = []
                for row in rows:
                    record = dict(zip(col_list, row))
                    # Cast SQLite 0/1 integers to Python bool for Postgres boolean columns
                    for col in bool_columns:
                        if col in record and record[col] is not None:
                            record[col] = bool(record[col])
                    batch.append(record)

                dst.execute(
                    text(
                        f"INSERT INTO {table_name} ({', '.join(col_list)}) "
                        f"VALUES ({', '.join(':' + c for c in col_list)})"
                    ),
                    batch,
                )
                dst.commit()
                total_rows += len(rows)

    if dry_run:
        logger.info("[dry-run] Would migrate ~%d rows across %d tables.", total_rows, len(MIGRATE_TABLES))
    else:
        logger.info("Migration complete. %d rows written to Postgres.", total_rows)
        logger.info("")
        logger.info("Next step — rebuild local_employers against Postgres:")
        logger.info("  ./dev_toolkit/rebuild_local_employers.sh")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sqlite", type=Path,
        default=Path(__file__).parent.parent / "data" / "tracker.db",
        help="Path to source SQLite file (default: data/tracker.db)",
    )
    parser.add_argument(
        "--pg-url", type=str,
        default=os.environ.get("DATABASE_URL"),
        help="Postgres URL (default: DATABASE_URL env var)",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.pg_url:
        print("ERROR: DATABASE_URL env var not set and --pg-url not provided.")
        sys.exit(1)
    if not args.sqlite.exists():
        print(f"ERROR: SQLite file not found: {args.sqlite}")
        sys.exit(1)

    migrate(args.sqlite, args.pg_url, dry_run=args.dry_run)
