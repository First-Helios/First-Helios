"""
Revelio Labs Data Ingestion — Real Database Writes

Ingest premium labor market data from downloaded Revelio Labs CSVs:
  - Employment trends (by state, occupation, industry)
  - Job openings (by postings from 50+ boards)
  - Hiring & attrition rates
  - Salary data (from job postings)
  - Mass layoff notices (WARN Act filings)

Features:
  - Filters to Texas by default (set --region to ingest nationwide)
  - Chunked reads for memory efficiency (~50K rows per chunk)
  - Batch commits every 1000 rows
  - Auto-populates ref_soc_major_groups reference table
  - Uses session.merge() for safe upserts

Usage:
  python scrapers/revelio_ingest.py --all --region Texas    # TX data (default)
  python scrapers/revelio_ingest.py --employment             # Employment only
  python scrapers/revelio_ingest.py --all --region "*"       # Nationwide (all states)
  python scrapers/revelio_ingest.py --layoffs                # Layoffs only
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd
from sqlalchemy.orm import Session

# Ensure project root is on sys.path
_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.database import get_session, init_db
from core.database import (
    RevelioEmployment,
    RevelioHiring,
    RevelioPostings,
    RevelioSalaries,
    RevelioLayoffs,
)
from core.models.reference import SOCMajorGroup
from config.paths import REVELIO_DIR

logger = logging.getLogger(__name__)

# Data directory — see config/paths.py for all data locations
DATA_DIR = REVELIO_DIR

# Default state filter: Texas only
DEFAULT_STATE_FILTER = "Texas"
CHUNK_SIZE = 50_000
COMMIT_INTERVAL = 1_000


def _ensure_soc_group(session: Session, soc2d_code: int, soc2d_name: str) -> None:
    """Ensure SOC major group is in reference table."""
    if soc2d_code is None or soc2d_name is None:
        return

    # Check if already exists
    existing = session.query(SOCMajorGroup).filter_by(soc2d_code=soc2d_code).first()
    if existing:
        return

    # Insert new
    group = SOCMajorGroup(soc2d_code=int(soc2d_code), soc2d_name=str(soc2d_name))
    session.merge(group)


def ingest_employment(state_filter: str, session: Session) -> dict:
    """Ingest employment_all_granularities.csv → revelio_employment table."""
    emp_file = DATA_DIR / "Employment — February 2026/employment_all_granularities.csv"
    if not emp_file.exists():
        logger.error(f"File not found: {emp_file}")
        return {"error": "File not found", "rows_inserted": 0}

    logger.info(f"[Employment] Loading from {emp_file.name}")
    total_rows = 0
    inserted_rows = 0
    batch_count = 0

    for chunk_idx, chunk in enumerate(pd.read_csv(emp_file, chunksize=CHUNK_SIZE)):
        # Filter to state(s)
        if state_filter and state_filter != "*":
            chunk = chunk[chunk["state"] == state_filter]

        if len(chunk) == 0:
            continue

        total_rows += len(chunk)

        for _, row in chunk.iterrows():
            try:
                soc_code = int(row["soc2d_code"]) if pd.notna(row["soc2d_code"]) else None
                soc_name = str(row["soc2d_name"]) if pd.notna(row["soc2d_name"]) else None

                # Handle NAICS code ranges like "31-33" by extracting first code
                naics_code_raw = str(row["naics2d_code"]) if pd.notna(row["naics2d_code"]) else None
                naics_code = None
                if naics_code_raw and "-" not in naics_code_raw:
                    try:
                        naics_code = int(naics_code_raw)
                    except ValueError:
                        pass

                # Ensure SOC reference exists
                if soc_code and soc_name:
                    _ensure_soc_group(session, soc_code, soc_name)

                record = RevelioEmployment(
                    month=str(row["month"]),
                    state=str(row["state"]),
                    naics2d_code=naics_code,
                    naics2d_name=str(row["naics2d_name"]) if pd.notna(row["naics2d_name"]) else None,
                    soc2d_code=soc_code,
                    soc2d_name=soc_name,
                    count_nsa=float(row["count_nsa"]) if pd.notna(row["count_nsa"]) else None,
                    count_sa=float(row["count_sa"]) if pd.notna(row["count_sa"]) else None,
                )
                session.merge(record)
                inserted_rows += 1

                if inserted_rows % COMMIT_INTERVAL == 0:
                    session.commit()
                    logger.debug(f"  Committed {inserted_rows} rows...")

            except Exception as e:
                logger.warning(f"  Error processing row: {e}")
                session.rollback()
                continue

        logger.info(f"  Chunk {chunk_idx + 1}: processed {len(chunk)} rows")

    session.commit()
    logger.info(f"✓ Employment ingestion complete: {inserted_rows} rows inserted")
    return {"rows_inserted": inserted_rows, "total_rows": total_rows}


def ingest_hiring(state_filter: str, session: Session) -> dict:
    """Ingest hiring_and_attrition CSV → revelio_hiring table."""
    hire_file = (
        DATA_DIR
        / "Hiring and Attrition — February 2026/hiring_and_attrition_by_sector_occupation_state(1).csv"
    )
    if not hire_file.exists():
        logger.error(f"File not found: {hire_file}")
        return {"error": "File not found", "rows_inserted": 0}

    logger.info(f"[Hiring] Loading from {hire_file.name}")
    inserted_rows = 0
    batch_count = 0

    for chunk_idx, chunk in enumerate(pd.read_csv(hire_file, chunksize=CHUNK_SIZE)):
        # Filter to state(s)
        if state_filter and state_filter != "*":
            chunk = chunk[chunk["state"] == state_filter]

        if len(chunk) == 0:
            continue

        for _, row in chunk.iterrows():
            try:
                soc_code = int(row["soc2d_code"]) if pd.notna(row["soc2d_code"]) else None
                soc_name = str(row["soc2d_name"]) if pd.notna(row["soc2d_name"]) else None

                # Handle NAICS code ranges like "31-33"
                naics_code_raw = str(row["naics2d_code"]) if pd.notna(row["naics2d_code"]) else None
                naics_code = None
                if naics_code_raw and "-" not in naics_code_raw:
                    try:
                        naics_code = int(naics_code_raw)
                    except ValueError:
                        pass

                # Ensure SOC reference exists
                if soc_code and soc_name:
                    _ensure_soc_group(session, soc_code, soc_name)

                record = RevelioHiring(
                    month=str(row["month"]),
                    state=str(row["state"]),
                    naics2d_code=naics_code,
                    naics2d_name=str(row["naics2d_name"]) if pd.notna(row["naics2d_name"]) else None,
                    soc2d_code=soc_code,
                    soc2d_name=soc_name,
                    hiring_rate_nsa=float(row["rl_hiring_rate_nsa"])
                    if pd.notna(row["rl_hiring_rate_nsa"])
                    else None,
                    hiring_rate_sa=float(row["rl_hiring_rate"]) if pd.notna(row["rl_hiring_rate"]) else None,
                    attrition_rate_nsa=float(row["rl_attrition_rate_nsa"])
                    if pd.notna(row["rl_attrition_rate_nsa"])
                    else None,
                    attrition_rate_sa=float(row["rl_attrition_rate"])
                    if pd.notna(row["rl_attrition_rate"])
                    else None,
                )
                session.merge(record)
                inserted_rows += 1

                if inserted_rows % COMMIT_INTERVAL == 0:
                    session.commit()
                    logger.debug(f"  Committed {inserted_rows} rows...")

            except Exception as e:
                logger.warning(f"  Error processing row: {e}")
                session.rollback()
                continue

        logger.info(f"  Chunk {chunk_idx + 1}: processed {len(chunk)} rows")

    session.commit()
    logger.info(f"✓ Hiring ingestion complete: {inserted_rows} rows inserted")
    return {"rows_inserted": inserted_rows}


def ingest_postings(state_filter: str, session: Session) -> dict:
    """Ingest postings_by_sector_occupation_state.csv → revelio_postings table."""
    postings_file = (
        DATA_DIR / "Job Openings — February 2026/postings_by_sector_occupation_state.csv"
    )
    if not postings_file.exists():
        logger.error(f"File not found: {postings_file}")
        return {"error": "File not found", "rows_inserted": 0}

    logger.info(f"[Postings] Loading from {postings_file.name}")
    inserted_rows = 0

    for chunk_idx, chunk in enumerate(pd.read_csv(postings_file, chunksize=CHUNK_SIZE)):
        # Filter to state(s)
        if state_filter and state_filter != "*":
            chunk = chunk[chunk["state"] == state_filter]

        if len(chunk) == 0:
            continue

        for _, row in chunk.iterrows():
            try:
                soc_code = int(row["soc2d_code"]) if pd.notna(row["soc2d_code"]) else None
                soc_name = str(row["soc2d_name"]) if pd.notna(row["soc2d_name"]) else None

                # Handle NAICS code ranges like "31-33"
                naics_code_raw = str(row["naics2d_code"]) if pd.notna(row["naics2d_code"]) else None
                naics_code = None
                if naics_code_raw and "-" not in naics_code_raw:
                    try:
                        naics_code = int(naics_code_raw)
                    except ValueError:
                        pass

                # Ensure SOC reference exists
                if soc_code and soc_name:
                    _ensure_soc_group(session, soc_code, soc_name)

                record = RevelioPostings(
                    month=str(row["month"]),
                    state=str(row["state"]),
                    naics2d_code=naics_code,
                    naics2d_name=str(row["naics2d_name"]) if pd.notna(row["naics2d_name"]) else None,
                    soc2d_code=soc_code,
                    soc2d_name=soc_name,
                    active_postings_nsa=float(row["active_postings_nsa"])
                    if pd.notna(row["active_postings_nsa"])
                    else None,
                    active_postings_sa=float(row["active_postings_sa"])
                    if pd.notna(row["active_postings_sa"])
                    else None,
                )
                session.merge(record)
                inserted_rows += 1

                if inserted_rows % COMMIT_INTERVAL == 0:
                    session.commit()
                    logger.debug(f"  Committed {inserted_rows} rows...")

            except Exception as e:
                logger.warning(f"  Error processing row: {e}")
                session.rollback()
                continue

        logger.info(f"  Chunk {chunk_idx + 1}: processed {len(chunk)} rows")

    session.commit()
    logger.info(f"✓ Postings ingestion complete: {inserted_rows} rows inserted")
    return {"rows_inserted": inserted_rows}


def ingest_salaries(state_filter: str, session: Session) -> dict:
    """Ingest salaries_all_granularities.csv → revelio_salaries table."""
    sal_file = DATA_DIR / "Salaries — February 2026/salaries_all_granularities.csv"
    if not sal_file.exists():
        logger.error(f"File not found: {sal_file}")
        return {"error": "File not found", "rows_inserted": 0}

    logger.info(f"[Salaries] Loading from {sal_file.name}")
    inserted_rows = 0

    for chunk_idx, chunk in enumerate(pd.read_csv(sal_file, chunksize=CHUNK_SIZE)):
        # Drop unnamed index column if present
        if "Unnamed: 0" in chunk.columns:
            chunk = chunk.drop(columns=["Unnamed: 0"])

        # Filter to state(s)
        if state_filter and state_filter != "*":
            chunk = chunk[chunk["state"] == state_filter]

        if len(chunk) == 0:
            continue

        for _, row in chunk.iterrows():
            try:
                soc_code = int(row["soc2d_code"]) if pd.notna(row["soc2d_code"]) else None
                soc_name = str(row["soc2d_name"]) if pd.notna(row["soc2d_name"]) else None

                # Handle NAICS code ranges like "31-33"
                naics_code_raw = str(row["naics2d_code"]) if pd.notna(row["naics2d_code"]) else None
                naics_code = None
                if naics_code_raw and "-" not in naics_code_raw:
                    try:
                        naics_code = int(naics_code_raw)
                    except ValueError:
                        pass

                # Ensure SOC reference exists
                if soc_code and soc_name:
                    _ensure_soc_group(session, soc_code, soc_name)

                record = RevelioSalaries(
                    month=str(row["month"]),
                    state=str(row["state"]),
                    naics2d_code=naics_code,
                    naics2d_name=str(row["naics2d_name"]) if pd.notna(row["naics2d_name"]) else None,
                    soc2d_code=soc_code,
                    soc2d_name=soc_name,
                    salary_nsa=float(row["salary_nsa"]) if pd.notna(row["salary_nsa"]) else None,
                    salary_sa=float(row["salary_sa"]) if pd.notna(row["salary_sa"]) else None,
                    salary_count=float(row["count"]) if pd.notna(row["count"]) else None,
                )
                session.merge(record)
                inserted_rows += 1

                if inserted_rows % COMMIT_INTERVAL == 0:
                    session.commit()
                    logger.debug(f"  Committed {inserted_rows} rows...")

            except Exception as e:
                logger.warning(f"  Error processing row: {e}")
                session.rollback()
                continue

        logger.info(f"  Chunk {chunk_idx + 1}: processed {len(chunk)} rows")

    session.commit()
    logger.info(f"✓ Salaries ingestion complete: {inserted_rows} rows inserted")
    return {"rows_inserted": inserted_rows}


def ingest_layoffs(session: Session) -> dict:
    """Ingest all layoff CSVs → revelio_layoffs table.

    No state filter: layoff files are small and cover US totals + state breakdown.
    """
    logger.info("[Layoffs] Loading layoff data...")
    inserted_rows = 0

    # 1. Layoffs by state
    layoff_state_file = DATA_DIR / "Mass-layoff Notices — January 2026/layoffs_by_state.csv"
    if layoff_state_file.exists():
        logger.info(f"  Loading {layoff_state_file.name}")
        df = pd.read_csv(layoff_state_file)
        for _, row in df.iterrows():
            try:
                record = RevelioLayoffs(
                    month=str(row["month"]),
                    state=str(row["state"]),
                    layoff_type="by_state",
                    employees_notified=float(row["num_employees_notified"])
                    if pd.notna(row["num_employees_notified"])
                    else None,
                    notices_issued=float(row["num_notices_issued"])
                    if pd.notna(row["num_notices_issued"])
                    else None,
                    employees_laidoff=float(row["num_employees_laidoff"])
                    if pd.notna(row["num_employees_laidoff"])
                    else None,
                )
                session.merge(record)
                inserted_rows += 1
                if inserted_rows % COMMIT_INTERVAL == 0:
                    session.commit()
            except Exception as e:
                logger.warning(f"  Error processing layoff row: {e}")
                continue

    # 2. Layoffs by NAICS
    layoff_naics_file = DATA_DIR / "Mass-layoff Notices — January 2026/layoffs_by_naics.csv"
    if layoff_naics_file.exists():
        logger.info(f"  Loading {layoff_naics_file.name}")
        df = pd.read_csv(layoff_naics_file)
        for _, row in df.iterrows():
            try:
                # Handle NAICS code ranges like "71-72" by extracting the first code
                naics_code_raw = str(row["naics2d_code"]) if pd.notna(row["naics2d_code"]) else None
                naics_code = None
                if naics_code_raw and "-" not in naics_code_raw:
                    try:
                        naics_code = int(naics_code_raw)
                    except ValueError:
                        pass

                record = RevelioLayoffs(
                    month=str(row["month"]),
                    naics2d_code=naics_code,
                    naics2d_name=str(row["naics2d_name"]) if pd.notna(row["naics2d_name"]) else None,
                    layoff_type="by_naics",
                    employees_notified=float(row["num_employees_notified"])
                    if pd.notna(row["num_employees_notified"])
                    else None,
                    notices_issued=float(row["num_notices_issued"])
                    if pd.notna(row["num_notices_issued"])
                    else None,
                    employees_laidoff=float(row["num_employees_laidoff"])
                    if pd.notna(row["num_employees_laidoff"])
                    else None,
                )
                session.merge(record)
                inserted_rows += 1
                if inserted_rows % COMMIT_INTERVAL == 0:
                    session.commit()
            except Exception as e:
                logger.warning(f"  Error processing layoff row: {e}")
                continue

    # 3. Total layoffs (national)
    layoff_total_file = DATA_DIR / "Mass-layoff Notices — January 2026/total_layoffs.csv"
    if layoff_total_file.exists():
        logger.info(f"  Loading {layoff_total_file.name}")
        df = pd.read_csv(layoff_total_file)
        for _, row in df.iterrows():
            try:
                record = RevelioLayoffs(
                    month=str(row["month"]),
                    layoff_type="total",
                    employees_notified=float(row["num_employees_notified"])
                    if pd.notna(row["num_employees_notified"])
                    else None,
                    notices_issued=float(row["num_notices_issued"])
                    if pd.notna(row["num_notices_issued"])
                    else None,
                    employees_laidoff=float(row["num_employees_laidoff"])
                    if pd.notna(row["num_employees_laidoff"])
                    else None,
                )
                session.merge(record)
                inserted_rows += 1
                if inserted_rows % COMMIT_INTERVAL == 0:
                    session.commit()
            except Exception as e:
                logger.warning(f"  Error processing total layoff row: {e}")
                continue

    session.commit()
    logger.info(f"✓ Layoffs ingestion complete: {inserted_rows} rows inserted")
    return {"rows_inserted": inserted_rows}


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s - %(message)s")

    parser = argparse.ArgumentParser(description="Revelio Labs data ingestion — real database writes")
    parser.add_argument(
        "--employment",
        action="store_true",
        help="Ingest employment data only",
    )
    parser.add_argument(
        "--hiring",
        action="store_true",
        help="Ingest hiring & attrition data only",
    )
    parser.add_argument(
        "--postings",
        action="store_true",
        help="Ingest job postings data only",
    )
    parser.add_argument(
        "--salary",
        action="store_true",
        help="Ingest salary data only",
    )
    parser.add_argument(
        "--layoffs",
        action="store_true",
        help="Ingest layoff notices only",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Ingest all datasets",
    )
    parser.add_argument(
        "--region",
        default=DEFAULT_STATE_FILTER,
        help=f"Filter to state (default: {DEFAULT_STATE_FILTER}, use '*' for nationwide)",
    )

    args = parser.parse_args()

    if args.all:
        args.employment = True
        args.hiring = True
        args.postings = True
        args.salary = True
        args.layoffs = True

    if not any([args.employment, args.hiring, args.postings, args.salary, args.layoffs]):
        parser.print_help()
        return

    # Initialize DB
    logger.info("=" * 80)
    logger.info("REVELIO LABS DATA INGESTION")
    logger.info("=" * 80)
    logger.info(f"State filter: {args.region if args.region != '*' else 'NATIONWIDE'}")
    logger.info("=" * 80)

    try:
        engine = init_db()
        session = get_session(engine)
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}", exc_info=True)
        return

    results = {}

    try:
        if args.employment:
            logger.info("\n[1/5] Ingesting Employment Data")
            results["employment"] = ingest_employment(args.region, session)

        if args.hiring:
            logger.info("\n[2/5] Ingesting Hiring & Attrition Data")
            results["hiring"] = ingest_hiring(args.region, session)

        if args.postings:
            logger.info("\n[3/5] Ingesting Job Postings Data")
            results["postings"] = ingest_postings(args.region, session)

        if args.salary:
            logger.info("\n[4/5] Ingesting Salary Data")
            results["salary"] = ingest_salaries(args.region, session)

        if args.layoffs:
            logger.info("\n[5/5] Ingesting Layoff Notices")
            results["layoffs"] = ingest_layoffs(session)

        # Summary
        logger.info("\n" + "=" * 80)
        logger.info("INGESTION SUMMARY")
        logger.info("=" * 80)
        total_inserted = 0
        for dataset, result in results.items():
            rows = result.get("rows_inserted", 0)
            total_inserted += rows
            logger.info(f"  {dataset:15} {rows:>10,} rows")

        logger.info(f"{'TOTAL':15} {total_inserted:>10,} rows")
        logger.info("=" * 80)
        logger.info("✓ Ingestion complete!")

    except Exception as e:
        logger.error(f"Ingestion failed: {e}", exc_info=True)
        session.rollback()
    finally:
        session.close()


if __name__ == "__main__":
    main()
