"""
Manual data ingestion from downloaded datasets.

Ingest OEWS and Revelio Labs data from:
  - data/reference/OEWS_wage_data/
  - data/reference/revelioLabs/

Usage:
  python scrapers/manual_ingest.py --oews
  python scrapers/manual_ingest.py --revelio
  python scrapers/manual_ingest.py --all
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

from backend.database import (
    OEWSRecord,
    get_session,
    init_db,
)
from config.loader import get_region
from config.paths import REFERENCE_DIR, REVELIO_DIR, OEWS_BULK_DIR

logger = logging.getLogger(__name__)

# Data directories — see config/paths.py for all data locations
DATA_DIR = REFERENCE_DIR
OEWS_DIR = OEWS_BULK_DIR / "oesm24in4/oesm24in4"

# ────────────────────────────────────────────────────────────────────────────
# OEWS Data Ingestion
# ────────────────────────────────────────────────────────────────────────────


def ingest_oews_msa(session: Session, region: str = "austin_tx") -> int:
    """
    Ingest OEWS data filtered to Austin MSA (area code 12420).

    The OEWS files are national-level; we filter to the specific area code.
    File structure: nat3d_M2024_dl.xlsx (3-digit NAICS)
                    nat4d_M2024_dl.xlsx (4-digit NAICS)
                    nat5d_6d_M2024_dl.xlsx (5-6 digit NAICS)

    Returns: number of rows inserted
    """

    austin_area_code = "12420"  # Austin-Round Rock-Georgetown MSA
    region_cfg = get_region(region)

    # Find and read the national 3-digit file (most granular for occupation level)
    nat3d_file = OEWS_DIR / "nat3d_M2024_dl.xlsx"

    if not nat3d_file.exists():
        logger.error(f"[OEWS] File not found: {nat3d_file}")
        return 0

    try:
        logger.info(f"[OEWS] Reading {nat3d_file.name}")
        df = pd.read_excel(nat3d_file, sheet_name="National", dtype={"Area Code": str})

        # Filter to Austin MSA
        df_austin = df[df["Area Code"].astype(str) == austin_area_code].copy()

        if df_austin.empty:
            logger.warning(f"[OEWS] No data found for area code {austin_area_code}")
            return 0

        logger.info(f"[OEWS] Found {len(df_austin)} rows for Austin MSA")

        # Map columns (BLS OEWS file format varies; adjust based on actual file)
        # Typical columns: Area Code, Area Title, OCC Code, OCC Title, NAICS Code,
        # Employment, Median Hourly Wage, Mean Hourly Wage, etc.

        inserted = 0
        for _, row in df_austin.iterrows():
            try:
                occ_code = str(row.get("OCC Code", row.get("Occupation Code", ""))).strip()
                occ_title = str(row.get("OCC Title", row.get("Occupation Title", ""))).strip()
                naics_code = str(row.get("NAICS Code", "")).strip() if pd.notna(row.get("NAICS Code")) else None
                employment = int(row.get("Employment", 0)) if pd.notna(row.get("Employment")) else None

                # Wage columns (BLS uses various names)
                wage_median = float(row.get("Median Hourly Wage", row.get("Median Wage", 0))) \
                    if pd.notna(row.get("Median Hourly Wage", row.get("Median Wage"))) else None
                wage_mean = float(row.get("Mean Hourly Wage", row.get("Mean Wage", 0))) \
                    if pd.notna(row.get("Mean Hourly Wage", row.get("Mean Wage"))) else None

                # Percentile wages (if available)
                wage_10 = float(row.get("10th Percentile", 0)) if pd.notna(row.get("10th Percentile")) else None
                wage_25 = float(row.get("25th Percentile", 0)) if pd.notna(row.get("25th Percentile")) else None
                wage_75 = float(row.get("75th Percentile", 0)) if pd.notna(row.get("75th Percentile")) else None
                wage_90 = float(row.get("90th Percentile", 0)) if pd.notna(row.get("90th Percentile")) else None

                if not occ_code:
                    continue  # Skip rows without occupation code

                record = OEWSRecord(
                    area_code=austin_area_code,
                    area_title="Austin-Round Rock-Georgetown MSA",
                    occ_code=occ_code,
                    occ_title=occ_title,
                    naics_code=naics_code,
                    employment=employment,
                    wage_mean_hourly=wage_mean,
                    wage_median_hourly=wage_median,
                    wage_10pct=wage_10,
                    wage_25pct=wage_25,
                    wage_75pct=wage_75,
                    wage_90pct=wage_90,
                    year=2024,
                    region=region,
                    fetched_at=datetime.utcnow(),
                )
                session.add(record)
                inserted += 1

            except Exception as e:
                logger.debug(f"[OEWS] Skipped row due to error: {e}")
                continue

        session.commit()
        logger.info(f"[OEWS] Inserted {inserted} rows into oews_data")
        return inserted

    except Exception as e:
        logger.error(f"[OEWS] Failed to ingest: {e}")
        session.rollback()
        return 0


# ────────────────────────────────────────────────────────────────────────────
# Revelio Labs Data Summary
# ────────────────────────────────────────────────────────────────────────────


def analyze_revelio_data() -> dict:
    """
    Analyze Revelio Labs data and summarize what's available.

    Returns: dict with data characteristics and recommendations
    """

    analysis = {
        "employment_data": None,
        "job_openings_data": None,
        "hiring_attrition_data": None,
        "salary_data": None,
        "layoff_data": None,
    }

    # Employment data
    emp_file = REVELIO_DIR / "Employment — February 2026/employment_all_granularities.csv"
    if emp_file.exists():
        df = pd.read_csv(emp_file)
        analysis["employment_data"] = {
            "rows": len(df),
            "date_range": f"{df['month'].min()} to {df['month'].max()}",
            "states": df['state'].nunique(),
            "occupations": df['soc2d_code'].nunique(),
            "industries": df['naics2d_code'].nunique(),
            "granularities": ["Monthly", "By state", "By occupation (SOC 2-digit)", "By industry (NAICS 2-digit)"],
        }

    # Job openings
    job_file = REVELIO_DIR / "Job Openings — February 2026/postings_by_sector_occupation_state.csv"
    if job_file.exists():
        df = pd.read_csv(job_file)
        analysis["job_openings_data"] = {
            "rows": len(df),
            "date_range": f"{df['month'].min()} to {df['month'].max()}",
            "states": df['state'].nunique(),
            "occupations": df['soc2d_code'].nunique(),
            "industries": df['naics2d_code'].nunique(),
            "columns": ["active_postings_nsa", "active_postings_sa"],
        }

    # Hiring & attrition
    hire_file = REVELIO_DIR / "Hiring and Attrition — February 2026/hiring_and_attrition_by_sector_occupation_state(1).csv"
    if hire_file.exists():
        df = pd.read_csv(hire_file)
        analysis["hiring_attrition_data"] = {
            "rows": len(df),
            "date_range": f"{df['month'].min()} to {df['month'].max()}",
            "metrics": ["rl_hiring_rate_nsa", "rl_attrition_rate_nsa", "rl_hiring_rate", "rl_attrition_rate"],
            "granularities": ["By sector", "By occupation", "By state"],
        }

    # Salaries
    sal_file = REVELIO_DIR / "Salaries — February 2026/salaries_all_granularities.csv"
    if sal_file.exists():
        df = pd.read_csv(sal_file)
        analysis["salary_data"] = {
            "rows": len(df),
            "date_range": f"{df['month'].min()} to {df['month'].max()}",
            "metrics": ["salary_nsa", "salary_sa"],
            "granularities": ["By sector", "By occupation", "By state"],
        }

    # Layoffs
    layoff_file = REVELIO_DIR / "Mass-layoff Notices — January 2026/layoffs_by_state.csv"
    if layoff_file.exists():
        df = pd.read_csv(layoff_file)
        analysis["layoff_data"] = {
            "rows": len(df),
            "date_range": f"{df['month'].min()} to {df['month'].max()}",
            "states": df['state'].nunique(),
            "metrics": ["num_employees_notified", "num_notices_issued", "num_employees_laidoff"],
        }

    return analysis


# ────────────────────────────────────────────────────────────────────────────
# Main
# ────────────────────────────────────────────────────────────────────────────


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser(description="Manually ingest downloaded data")
    parser.add_argument("--oews", action="store_true", help="Ingest OEWS wage data")
    parser.add_argument("--revelio", action="store_true", help="Analyze Revelio Labs data")
    parser.add_argument("--all", action="store_true", help="Ingest all available data")
    parser.add_argument("--region", default="austin_tx", help="Region key")

    args = parser.parse_args()

    if args.all:
        args.oews = True
        args.revelio = True

    if not (args.oews or args.revelio):
        parser.print_help()
        return

    # Initialize database
    engine = init_db()
    session = get_session(engine)

    try:
        if args.oews:
            logger.info("=" * 80)
            logger.info("INGESTING OEWS DATA")
            logger.info("=" * 80)
            count = ingest_oews_msa(session, args.region)
            logger.info(f"✓ OEWS ingestion complete: {count} rows")

        if args.revelio:
            logger.info("=" * 80)
            logger.info("ANALYZING REVELIO LABS DATA")
            logger.info("=" * 80)
            analysis = analyze_revelio_data()

            for key, data in analysis.items():
                if data:
                    logger.info(f"\n{key}:")
                    for k, v in data.items():
                        logger.info(f"  {k}: {v}")

            logger.info("\n💡 Revelio Labs data is suitable for:")
            logger.info("  • Hiring rate benchmarking (compare to JOLTS)")
            logger.info("  • Attrition rate benchmarking (compare to JOLTS quits)")
            logger.info("  • Salary trend analysis (compare to OEWS)")
            logger.info("  • Sector-level hiring intensity")
            logger.info("  • Mass layoff event detection (early warning)")

    finally:
        session.close()


if __name__ == "__main__":
    main()
