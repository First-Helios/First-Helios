"""
scripts/load_occupation_aliases.py

Loads the Census Bureau "Alphabetical Index of Occupations" (2018 SOC edition)
into the ref_occupation_aliases table.

Source: data/reference/Alphabetical-Index-of-Occupations-December-2019_Final.xlsx
  — 32,673 rows of (job_title_alias → SOC code) mappings
  — 28,666 unique aliases, 864 SOC codes, average 33 aliases per SOC

This enables fuzzy autocomplete in the Career Pathfinder:
  "barista"          → 35-3023 Fast Food and Counter Workers
  "personal trainer" → 39-9031 Exercise Trainers
  "carpenter"        → 47-2031 Carpenters
  ... (18,981 aliases that overlap with mob_occupation SOCs)

Usage:
    python scripts/load_occupation_aliases.py
    python scripts/load_occupation_aliases.py --data-dir /path/to/data --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, ".")

from backend.database import init_db, get_session
from backend.models.reference import OccupationAlias
from config.paths import REFERENCE_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_DATA_DIR = REFERENCE_DIR
EXCEL_FILENAME   = "Alphabetical-Index-of-Occupations-December-2019_Final.xlsx"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _load_excel(path: Path) -> pd.DataFrame:
    logger.info("Reading %s", path)
    df = pd.read_excel(path, header=5)
    df.columns = ["description", "industry_restriction", "census_code", "soc_code"]

    # Drop the residual header row that comes through as data
    df = df[df["soc_code"] != "2018 SOC Code"].copy()
    df = df.dropna(subset=["soc_code", "description"])

    df["soc_code"]             = df["soc_code"].astype(str).str.strip()
    df["description"]          = df["description"].astype(str).str.strip().str.lower()
    df["census_code"]          = df["census_code"].astype(str).str.strip().str.zfill(4)
    df["industry_restriction"] = df["industry_restriction"].where(df["industry_restriction"].notna(), None)
    return df


def _get_mob_socs(session) -> set:
    """Return set of soc_codes that exist in mob_occupation."""
    from backend.models.reference import MobOccupation
    rows = session.query(MobOccupation.soc_code).all()
    return {r[0] for r in rows}


# ── Main ──────────────────────────────────────────────────────────────────────

def run(data_dir: Path, dry_run: bool = False) -> None:
    engine  = init_db()
    session = get_session(engine)
    try:
        xl_path = data_dir / EXCEL_FILENAME
        if not xl_path.exists():
            logger.error("File not found: %s", xl_path)
            sys.exit(1)

        df = _load_excel(xl_path)
        logger.info("Loaded %d alias rows from Excel", len(df))

        mob_socs = _get_mob_socs(session)
        logger.info("mob_occupation has %d SOC codes", len(mob_socs))

        # Only keep aliases whose SOC code is in mob_occupation
        df_mob = df[df["soc_code"].isin(mob_socs)].copy()
        logger.info("%d alias rows map to mob_occupation SOCs", len(df_mob))

        skipped_socs = set(df["soc_code"].unique()) - mob_socs
        logger.info("%d SOC codes in Excel not in mob_occupation (skipped)", len(skipped_socs))

        if dry_run:
            logger.info("[dry-run] Would insert %d alias rows", len(df_mob))
            print(df_mob.head(20).to_string())
            return

        # Truncate and reload
        session.query(OccupationAlias).delete()
        session.commit()
        logger.info("Cleared existing ref_occupation_aliases")

        batch = []
        for _, row in df_mob.iterrows():
            batch.append({
                "alias":                row["description"],
                "soc_code":             row["soc_code"],
                "census_code":          row["census_code"] if row["census_code"] != "nan" else None,
                "industry_restriction": row["industry_restriction"],
            })
            if len(batch) >= 500:
                session.bulk_insert_mappings(OccupationAlias, batch)
                batch = []

        if batch:
            session.bulk_insert_mappings(OccupationAlias, batch)
        session.commit()

        total = session.query(OccupationAlias).count()
        logger.info("ref_occupation_aliases: %d rows loaded", total)
        logger.info("Unique SOCs with aliases: %d",
                    session.query(OccupationAlias.soc_code).distinct().count())

    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    run(Path(args.data_dir), dry_run=args.dry_run)
