"""
Centralized data path constants for First-Helios.

All scripts should import from here instead of hardcoding paths.
Changing directory structure only requires updating this one file.

Two data silos:
  reference/  — static datasets downloaded periodically (BLS, Revelio, TexasWages, Overture)
  cache/      — transient API response caches (BLS JSON, etc.)

Live operational data (signals, scores, postings) lives in PostgreSQL, not in files.
"""

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

# ── Silo 1: Static reference data ────────────────────────────────────────────
# Ground-truth datasets downloaded from authoritative sources.
# Updated monthly, quarterly, or annually. Never auto-generated.
# See data/reference/DataCollectionSources.md for full catalog.

REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"

# Revelio Labs premium data (employment, hiring, postings, salaries, layoffs)
REVELIO_DIR = REFERENCE_DIR / "revelioLabs"

# BLS OEWS area file (Austin MSA .ods spreadsheet)
BLS_OEWS_DIR = REFERENCE_DIR / "bls"

# BLS OEWS bulk national/industry Excel files (oesm24in4/)
OEWS_BULK_DIR = REFERENCE_DIR / "OEWS_wage_data"

# TexasWages.com MSA wage CSVs
TEXASWAGES_DIR = REFERENCE_DIR / "texaswages"

# Emsi/Lightcast career transition .dta files (mob_transition source)
EMSI_DIR = REFERENCE_DIR / "emsi"

# Overture Maps GeoJSON (Austin POIs — large file)
OVERTURE_DIR = REFERENCE_DIR / "overture"
OVERTURE_GEOJSON = OVERTURE_DIR / "overture_austin_places.geojson"

# Census occupation aliases Excel file
OCCUPATION_ALIASES_FILE = (
    REFERENCE_DIR / "Alphabetical-Index-of-Occupations-December-2019_Final.xlsx"
)

# ── Silo 2: API response cache ────────────────────────────────────────────────
# Transient caches from API calls. Safe to delete and re-fetch at any time.
# These are intermediate files — the canonical data is in PostgreSQL.

CACHE_DIR = PROJECT_ROOT / "data" / "cache"
BLS_CACHE_DIR = CACHE_DIR / "bls"       # BLS time-series JSON (download_bls_bulk.py)
QCEW_CACHE_DIR = CACHE_DIR / "qcew"    # QCEW CSV files from BLS CEW API
WEBSITE_SCRAPE_DEBUG_DIR = CACHE_DIR / "website_scrape_debug"

# ── Silo 3: Skimmed data ──────────────────────────────────────────────────────
# Raw internet-collected data from live scrapers, saved before DB processing.
# Enables replay, debugging, and offline model training without re-scraping.
# Organized by source and date: skimmed/{source}/{YYYY-MM-DD}/
#
# Sources that belong here:
#   job_postings/   — raw JSON from JobSpy (Indeed, LinkedIn, Glassdoor)
#   careers_api/    — raw JSON from Starbucks/Dutch Bros Workday APIs
#   reddit/         — raw posts/comments from PRAW
#   reviews/        — raw rating+text from Google Maps / Yelp
#   warn/           — raw WARN Act filings from TX DOL
#   nlrb/           — raw union organizing filings from NLRB

SKIMMED_DIR = PROJECT_ROOT / "data" / "skimmed"
