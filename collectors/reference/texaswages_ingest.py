"""
Texas Wages Ingest — data/reference/texaswages/ → ref_texaswages

Reads the four Texas Workforce Commission MSA wage CSVs and loads them into
the ref_texaswages table.  Each file covers one wage tier (entry_level,
experienced, mean, median) across all 26 Texas MSAs + statewide aggregate,
for all SOC occupations (~835 rows per file).

CSV format (wide):
  Row 0:  Title string, e.g. "2024 Hourly Median MSA Wages"  (vintage year parsed here)
  Row 1:  Column headers — SOC, SOC Title, Statewide, Abilene, Amarillo, ...
  Row 2+: Data rows.  0.0 = suppressed/not available (stored as NULL).

Source files:
  data/reference/texaswages/TexasMSAWagesEntryLevel.csv   → wage_tier = entry_level
  data/reference/texaswages/TexasMSAWagesExperenced.csv   → wage_tier = experienced
  data/reference/texaswages/TexasMSAWagesMean.csv         → wage_tier = mean
  data/reference/texaswages/TexasMSAWagesMedian.csv       → wage_tier = median

Usage:
  python scrapers/texaswages_ingest.py
  python scrapers/texaswages_ingest.py --dry-run
  python scrapers/texaswages_ingest.py --tier median       # single tier only
  python scrapers/texaswages_ingest.py --msa "Austin-Round Rock"  # filter to one MSA
"""

import argparse
import logging
import re
import sys
from pathlib import Path

import pandas as pd

_PROJECT_ROOT = Path(__file__).parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.database import get_session, init_db
from core.models.reference import TexasWages
from config.paths import TEXASWAGES_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# filename → wage_tier label
# Note: "Experenced" is a typo in the source filename — preserved intentionally.
FILE_MAP: dict[str, str] = {
    "TexasMSAWagesEntryLevel.csv": "entry_level",
    "TexasMSAWagesExperenced.csv": "experienced",
    "TexasMSAWagesMean.csv": "mean",
    "TexasMSAWagesMedian.csv": "median",
}

# Values TWC uses for suppressed / not-available cells
_SUPPRESSED_VALUES = {0.0, 0, "0", "0.0", "", "N/A", "*", "#"}


def _parse_vintage_year(csv_path: Path) -> int:
    """Extract 4-digit year from the title row of a TexasWages CSV.

    File structure:
      line 0: blank \\r line
      line 1: title string, e.g. "2024 Hourly Median MSA Wages"
      line 2: SOC column headers
      line 3+: data
    """
    try:
        with open(csv_path, encoding="utf-8", errors="replace") as f:
            f.readline()          # skip blank \r line
            title_text = f.readline().strip()
        match = re.search(r"\b(20\d{2})\b", title_text)
        if match:
            return int(match.group(1))
    except Exception:
        pass
    logger.warning("[TexasWages] Could not parse vintage year from %s — defaulting to 2024", csv_path.name)
    return 2024


def _is_suppressed(value) -> bool:
    """Return True if the value represents suppressed/unavailable TWC data."""
    if pd.isna(value):
        return True
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return str(value).strip() in _SUPPRESSED_VALUES


def ingest_file(
    csv_path: Path,
    wage_tier: str,
    session,
    msa_filter: str | None = None,
    dry_run: bool = False,
) -> dict:
    """Load one TexasWages CSV into ref_texaswages.

    Args:
        csv_path:   Path to the CSV file.
        wage_tier:  One of entry_level / experienced / mean / median.
        session:    SQLAlchemy session.
        msa_filter: If set, only ingest rows for this MSA name.
        dry_run:    If True, parse and report but don't write to DB.

    Returns:
        {"rows_processed": int, "rows_inserted": int, "rows_suppressed": int}
    """
    if not csv_path.exists():
        logger.error("[TexasWages] File not found: %s", csv_path)
        return {"error": "file not found", "rows_processed": 0, "rows_inserted": 0}

    vintage_year = _parse_vintage_year(csv_path)
    logger.info("[TexasWages] Loading %s (vintage=%d, tier=%s)", csv_path.name, vintage_year, wage_tier)

    # File structure: line 0 = blank \r, line 1 = title, line 2 = SOC headers, line 3+ = data
    # skiprows=2 skips the blank line and the title row so the SOC header row becomes columns.
    df = pd.read_csv(csv_path, skiprows=2)

    # Strip whitespace from column names and SOC values
    df.columns = [c.strip() for c in df.columns]
    df["SOC"] = df["SOC"].astype(str).str.strip()
    df["SOC Title"] = df["SOC Title"].astype(str).str.strip()

    # MSA columns: everything except SOC and SOC Title
    msa_columns = [c for c in df.columns if c not in ("SOC", "SOC Title")]

    if msa_filter:
        if msa_filter not in msa_columns:
            logger.warning(
                "[TexasWages] MSA '%s' not found in %s. Available: %s",
                msa_filter, csv_path.name, msa_columns,
            )
            return {"rows_processed": 0, "rows_inserted": 0, "rows_suppressed": 0}
        msa_columns = [msa_filter]

    # Melt wide → long
    df_long = df.melt(
        id_vars=["SOC", "SOC Title"],
        value_vars=msa_columns,
        var_name="msa_name",
        value_name="hourly_wage",
    )

    rows_processed = 0
    rows_inserted = 0
    rows_suppressed = 0

    for _, row in df_long.iterrows():
        rows_processed += 1

        soc_code = str(row["SOC"]).strip()
        soc_title = str(row["SOC Title"]).strip()
        msa_name = str(row["msa_name"]).strip()
        raw_wage = row["hourly_wage"]

        # Store suppressed values as NULL
        if _is_suppressed(raw_wage):
            hourly_wage = None
            rows_suppressed += 1
        else:
            try:
                hourly_wage = float(raw_wage)
            except (TypeError, ValueError):
                hourly_wage = None
                rows_suppressed += 1

        if dry_run:
            rows_inserted += 1
            continue

        record = TexasWages(
            soc_code=soc_code,
            soc_title=soc_title,
            msa_name=msa_name,
            wage_tier=wage_tier,
            hourly_wage=hourly_wage,
            vintage_year=vintage_year,
        )
        session.merge(record)
        rows_inserted += 1

        if rows_inserted % 2000 == 0:
            session.commit()
            logger.debug("[TexasWages]   %d rows committed...", rows_inserted)

    if not dry_run:
        session.commit()

    logger.info(
        "[TexasWages] %s complete: %d inserted, %d suppressed (NULL)",
        wage_tier, rows_inserted, rows_suppressed,
    )
    return {
        "rows_processed": rows_processed,
        "rows_inserted": rows_inserted,
        "rows_suppressed": rows_suppressed,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest TexasWages MSA wage CSVs into ref_texaswages")
    parser.add_argument(
        "--tier",
        choices=list(FILE_MAP.values()),
        default=None,
        help="Ingest only this wage tier (default: all four)",
    )
    parser.add_argument(
        "--msa",
        default=None,
        help='Filter to a single MSA, e.g. "Austin-Round Rock" (default: all MSAs)',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and count rows without writing to database",
    )
    args = parser.parse_args()

    engine = init_db()
    session = get_session(engine)

    total_inserted = 0
    total_suppressed = 0

    try:
        for filename, wage_tier in FILE_MAP.items():
            if args.tier and wage_tier != args.tier:
                continue

            csv_path = TEXASWAGES_DIR / filename
            result = ingest_file(
                csv_path=csv_path,
                wage_tier=wage_tier,
                session=session,
                msa_filter=args.msa,
                dry_run=args.dry_run,
            )
            total_inserted += result.get("rows_inserted", 0)
            total_suppressed += result.get("rows_suppressed", 0)

    except Exception as e:
        logger.error("[TexasWages] Ingestion failed: %s", e, exc_info=True)
        session.rollback()
    finally:
        session.close()

    prefix = "[DRY RUN] " if args.dry_run else ""
    logger.info(
        "%s--- TexasWages ingest complete: %d rows, %d suppressed (NULL) ---",
        prefix, total_inserted, total_suppressed,
    )


if __name__ == "__main__":
    main()
