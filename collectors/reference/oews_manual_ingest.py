"""
Ingest Austin MSA OEWS data from manually downloaded ODS file.

This script processes the Austin-Round Rock-San Marcos MSA occupational employment
and wage statistics file from BLS OEWS.

**Important:** This ingests ALL occupations and industries, not just food service.
See DESIGN_FLAW_FOOD_SERVICE_ONLY.md for context on why we were previously
limiting to food service.

File: Occupational Employment and Wage Statistics- Area: Austin-Round Rock-San Marcos, TX.ods
Location: /data/reference/bls/
Source: BLS OEWS, May 2024 data
Coverage: Austin-Round Rock-San Marcos MSA (area code 12420)
Occupations: All 638 occupations across all industries

Depends on: pandas, odfpy, sqlalchemy, config
Called by: CLI or backend/scheduler.py
"""

import argparse
import logging
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from backend.database import OEWSRecord, get_session, init_db
from backend.metadata import MetaJobRun, MetaApiCall
from config.paths import BLS_OEWS_DIR

logger = logging.getLogger(__name__)

# Austin MSA configuration — see config/paths.py for data directory
AUSTIN_MSA = {
    "area_code": "12420",
    "area_name": "Austin-Round Rock-San Marcos, TX",
    "file_path": BLS_OEWS_DIR /
                 "Occupational Employment and Wage Statistics- Area: Austin-Round Rock-San Marcos, TX.ods"
}

# Column mapping from ODS to database
COLUMN_MAPPING = {
    "Occupation (SOC code)": "occupation_title",
    "Employment (1)  ": "employment",
    "Hourly mean wage   ": "wage_hourly_mean",
    "Annual mean wage (2)  ": "wage_annual_mean",
    "Hourly 10th percentile wage   ": "wage_hourly_10pct",
    "Hourly 25th percentile wage   ": "wage_hourly_25pct",
    "Hourly median wage   ": "wage_hourly_median",
    "Hourly 75th percentile wage   ": "wage_hourly_75pct",
    "Hourly 90th percentile wage   ": "wage_hourly_90pct",
    "Annual 10th percentile wage (2)  ": "wage_annual_10pct",
    "Annual 25th percentile wage (2)  ": "wage_annual_25pct",
    "Annual median wage (2)  ": "wage_annual_median",
    "Annual 75th percentile wage (2)  ": "wage_annual_75pct",
    "Annual 90th percentile wage (2)  ": "wage_annual_90pct",
    "Employment per 1,000 jobs   ": "employment_per_1000",
    "Location Quotient   ": "location_quotient",
}


def extract_soc_code(occupation_str: str) -> Optional[str]:
    """Extract SOC code like '35-1012' from 'Food Prep Workers (35-1012)'"""
    match = re.search(r'\((\d{2}-\d{4})\)', str(occupation_str))
    return match.group(1) if match else None


def clean_wage_column(value) -> Optional[float]:
    """
    Convert wage strings to floats.
    Handles: "$16.50", "S" (suppressed), "*" (not available), NaN, etc.
    """
    if pd.isna(value):
        return None

    value_str = str(value).strip()

    # Handle special codes
    if value_str in ["S", "N", "*", "(8)", "N.E.", ""]:
        return None

    # Remove $ and convert
    try:
        clean = value_str.replace("$", "").replace(",", "")
        return float(clean)
    except ValueError:
        return None


def clean_employment_column(value) -> Optional[int]:
    """Convert employment strings to integers."""
    if pd.isna(value):
        return None

    value_str = str(value).strip()

    # Handle special codes
    if value_str in ["S", "N", "*", "(8)", "N.E.", ""]:
        return None

    try:
        clean = value_str.replace(",", "")
        return int(float(clean))
    except ValueError:
        return None


def clean_float_column(value) -> Optional[float]:
    """Convert float strings (LQ, ratios, etc.) to floats."""
    if pd.isna(value):
        return None

    value_str = str(value).strip()

    # Handle special codes
    if value_str in ["S", "N", "*", "(8)", "N.E.", ""]:
        return None

    try:
        return float(value_str)
    except ValueError:
        return None


def ingest_oews_from_file(file_path: Path, session, verbose: bool = False) -> tuple[int, int]:
    """
    Read OEWS ODS file and ingest into database.

    Returns: (rows_processed, rows_inserted)
    """

    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    logger.info(f"Reading OEWS file: {file_path}")
    df = pd.read_excel(str(file_path), engine='odf', sheet_name=0)

    # Extract SOC codes
    df['soc_code'] = df['Occupation (SOC code)'].apply(extract_soc_code)

    # Filter out header/footer rows (rows without SOC codes)
    df_valid = df[df['soc_code'].notna()].copy()

    logger.info(f"Total rows: {len(df)}, Valid occupations: {len(df_valid)}")

    if verbose:
        print(f"\nIndustry breakdown:")
        soc_prefixes = df_valid['soc_code'].str[:2].value_counts()
        for soc_prefix, count in soc_prefixes.items():
            print(f"  SOC {soc_prefix}-xxxx: {count} occupations")

    # Ingest to database
    rows_inserted = 0

    for idx, row in df_valid.iterrows():
        try:
            # Create OEWS record
            oews_record = OEWSRecord(
                area_code=AUSTIN_MSA["area_code"],
                area_title=AUSTIN_MSA["area_name"],
                occ_code=row['soc_code'],
                occ_title=row['Occupation (SOC code)'],
                employment=clean_employment_column(row.get('Employment (1)  ')),
                wage_mean_hourly=clean_wage_column(row.get('Hourly mean wage   ')),
                wage_median_hourly=clean_wage_column(row.get('Hourly median wage   ')),
                wage_10pct=clean_wage_column(row.get('Hourly 10th percentile wage   ')),
                wage_25pct=clean_wage_column(row.get('Hourly 25th percentile wage   ')),
                wage_75pct=clean_wage_column(row.get('Hourly 75th percentile wage   ')),
                wage_90pct=clean_wage_column(row.get('Hourly 90th percentile wage   ')),
                year=2024,
                region='Austin, TX',
                fetched_at=datetime.utcnow(),
            )

            session.add(oews_record)
            rows_inserted += 1

            if verbose and rows_inserted % 50 == 0:
                print(f"  Processed {rows_inserted}/{len(df_valid)} records...")

        except Exception as e:
            logger.warning(f"Failed to ingest row {idx}: {e}")
            continue

    session.commit()
    return len(df_valid), rows_inserted


def log_job_run(session, rows_processed: int, rows_inserted: int, error: Optional[str] = None):
    """Log job execution to metadata system."""

    job_run = MetaJobRun(
        job_id='oews_manual_ingest',
        job_type='manual_data_import',
        status='success' if not error else 'failed',
        rows_processed=rows_processed,
        rows_inserted=rows_inserted,
        rows_skipped=rows_processed - rows_inserted,
        error_message=error,
        started_at=datetime.utcnow(),
        completed_at=datetime.utcnow(),
        duration_seconds=0,
        triggered_by='cli',
    )
    session.add(job_run)

    # Log API call (even though this is a file, treat as data source)
    api_call = MetaApiCall(
        api_source='bls_oews_manual',
        endpoint='local_file_ingest',
        status_code=200 if not error else 500,
        success=not bool(error),
        rows_returned=rows_inserted,
        latency_ms=0,
        error_message=error,
        rate_limit_remaining=None,
        job_run_id=job_run.id,
    )
    session.add(api_call)
    session.commit()


def main():
    parser = argparse.ArgumentParser(
        description='Ingest Austin MSA OEWS data from manually downloaded ODS file'
    )
    parser.add_argument(
        '--file',
        type=Path,
        default=AUSTIN_MSA['file_path'],
        help=f'Path to ODS file (default: {AUSTIN_MSA["file_path"]})'
    )
    parser.add_argument(
        '--verbose', '-v',
        action='store_true',
        help='Verbose output showing progress'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Read file but do not insert into database'
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s'
    )

    try:
        # Initialize database
        engine = init_db()
        session = get_session(engine)

        # Read and validate file
        file_path = args.file
        logger.info(f"Ingesting from: {file_path}")

        if not file_path.exists():
            logger.error(f"File not found: {file_path}")
            return 1

        # Ingest
        rows_processed, rows_inserted = ingest_oews_from_file(
            file_path, session, verbose=args.verbose
        )

        if args.dry_run:
            logger.info(f"[DRY RUN] Would insert {rows_inserted} records")
            session.rollback()
        else:
            # Log to metadata
            log_job_run(session, rows_processed, rows_inserted)
            logger.info(f"✓ Inserted {rows_inserted}/{rows_processed} OEWS records into oews_data table")

        session.close()
        return 0

    except Exception as e:
        logger.error(f"Failed: {e}", exc_info=True)

        # Try to log failure
        try:
            engine = init_db()
            session = get_session(engine)
            log_job_run(session, 0, 0, str(e))
            session.close()
        except:
            pass

        return 1


if __name__ == '__main__':
    sys.exit(main())
