# Data Streams — Sources, Flows, and Silo Assignments

Complete catalog of every data stream entering First-Helios: where it comes from, how it's collected, where raw files land, which DB tables it feeds, and what uses it downstream.

---

## The Three File Silos

```
data/
├── reference/    SILO 1 — Ground-truth downloads (authoritative, periodic)
├── cache/        SILO 2 — API response cache (transient, safe to delete)
├── skimmed/      SILO 3 — Raw internet-collected data (live scrapes, pre-DB)
└── (PostgreSQL)  LIVE   — All processed/derived operational data
```

Data generally flows left to right: reference and skimmed feed PostgreSQL. Cache is an intermediate layer for API-fetched reference data.

---

## Silo 1 — Reference Data

Static, authoritative datasets. Updated on a fixed schedule. Each has a known vintage, a manual download step, and an ingest script that writes to PostgreSQL.

### Stream R1: BLS OEWS — Austin MSA Wages

| Field | Detail |
|-------|--------|
| **Source** | Bureau of Labor Statistics, OEWS program |
| **Collection** | Manual download (ODS spreadsheet) |
| **Raw file** | `data/reference/bls/Occupational Employment and Wage Statistics- Area: Austin-Round Rock-San Marcos, TX.ods` |
| **Ingest script** | `scrapers/oews_manual_ingest.py` |
| **DB table** | `oews_data` |
| **Update cadence** | Annual (May data, released ~April following year) |
| **Used by** | Scoring engine (wage denominators), labor_market_baseline, config generation |
| **Silo** | ✅ reference/ — correct |

---

### Stream R2: BLS OEWS — National Bulk (Industry × Occupation)

| Field | Detail |
|-------|--------|
| **Source** | BLS OEWS research estimates |
| **Collection** | Manual download (ZIP → Excel files) |
| **Raw files** | `data/reference/OEWS_wage_data/oesm24in4/oesm24in4/*.xlsx` |
| **Ingest script** | `scrapers/manual_ingest.py --oews` |
| **DB table** | `oews_data` |
| **Update cadence** | Annual |
| **Used by** | Industry wage benchmarks across non-Austin MSA SOC codes |
| **Silo** | ✅ reference/ — correct |

---

### Stream R3: Revelio Labs — Employment

| Field | Detail |
|-------|--------|
| **Source** | Revelio Labs (premium subscription) |
| **Collection** | Manual download from Revelio dashboard |
| **Raw file** | `data/reference/revelioLabs/Employment — February 2026/employment_all_granularities.csv` (~1.18M rows) |
| **Ingest script** | `scrapers/revelio_ingest.py --employment --region Texas` |
| **DB table** | `revelio_employment` |
| **Update cadence** | Monthly (~6 week lag) |
| **Used by** | Scoring engine `demand_pressure` component (sector employment baseline) |
| **Status** | ⚠️ PENDING INGEST — CSV present, DB table empty |
| **Silo** | ✅ reference/ — correct |

---

### Stream R4: Revelio Labs — Hiring & Attrition

| Field | Detail |
|-------|--------|
| **Source** | Revelio Labs (premium subscription) |
| **Collection** | Manual download |
| **Raw file** | `data/reference/revelioLabs/Hiring and Attrition — February 2026/hiring_and_attrition_by_sector_occupation_state(1).csv` (~1.20M rows) |
| **Ingest script** | `scrapers/revelio_ingest.py --hiring --region Texas` |
| **DB table** | `revelio_hiring` |
| **Update cadence** | Monthly |
| **Used by** | Scoring engine `churn_signal` component (expected turnover rate denominator) |
| **Status** | ⚠️ PENDING INGEST |
| **Silo** | ✅ reference/ — correct |

---

### Stream R5: Revelio Labs — Job Openings

| Field | Detail |
|-------|--------|
| **Source** | Revelio Labs |
| **Collection** | Manual download |
| **Raw file** | `data/reference/revelioLabs/Job Openings — February 2026/postings_by_sector_occupation_state.csv` (~1.06M rows) |
| **Ingest script** | `scrapers/revelio_ingest.py --postings --region Texas` |
| **DB table** | `revelio_postings` |
| **Update cadence** | Monthly |
| **Used by** | Aggregate job opening rate benchmarks by sector |
| **Status** | ⚠️ PENDING INGEST |
| **Silo** | ✅ reference/ — correct |

---

### Stream R6: Revelio Labs — Salaries

| Field | Detail |
|-------|--------|
| **Source** | Revelio Labs |
| **Collection** | Manual download |
| **Raw file** | `data/reference/revelioLabs/Salaries — February 2026/salaries_all_granularities.csv` (~1.20M rows) |
| **Ingest script** | `scrapers/revelio_ingest.py --salary --region Texas` |
| **DB table** | `revelio_salaries` |
| **Update cadence** | Monthly |
| **Used by** | Wage competitiveness cross-validation |
| **Status** | ⚠️ PENDING INGEST |
| **Silo** | ✅ reference/ — correct |

---

### Stream R7: Revelio Labs — Mass Layoff Notices (WARN)

| Field | Detail |
|-------|--------|
| **Source** | Revelio Labs |
| **Collection** | Manual download |
| **Raw files** | `data/reference/revelioLabs/Mass-layoff Notices — January 2026/layoffs_by_naics.csv`, `layoffs_by_state.csv`, `total_layoffs.csv` |
| **Ingest script** | `scrapers/revelio_ingest.py --layoffs` |
| **DB table** | `revelio_layoffs` |
| **Update cadence** | Monthly (WARN Act data, 1 month lag) |
| **Used by** | Layoff signal in staffing stress scoring |
| **Status** | ⚠️ PENDING INGEST |
| **Silo** | ✅ reference/ — correct |

---

### Stream R8: TexasWages.com — MSA Wage Benchmarks

| Field | Detail |
|-------|--------|
| **Source** | Texas Workforce Commission via texaswages.com |
| **Collection** | Manual download (4 CSVs) |
| **Raw files** | `data/reference/texaswages/TexasMSAWages*.csv` |
| **Ingest script** | ❌ Not yet built |
| **DB table** | None yet |
| **Update cadence** | Annual |
| **Used by** | Nothing yet — planned: entry-level wage gap in Career Pathfinder |
| **Status** | ⚠️ CSVs present, no ingest path |
| **Silo** | ✅ reference/ — correct |

---

### Stream R9: Census Occupation Aliases

| Field | Detail |
|-------|--------|
| **Source** | U.S. Census Bureau, Alphabetical Index of Occupations (2018 SOC) |
| **Collection** | Manual download (Excel) |
| **Raw file** | `data/reference/Alphabetical-Index-of-Occupations-December-2019_Final.xlsx` |
| **Ingest script** | `scripts/load_occupation_aliases.py` |
| **DB table** | `ref_occupation_aliases` (18,981 rows) |
| **Update cadence** | ~Every 10 years (next SOC revision ~2028) |
| **Used by** | Career Pathfinder autocomplete |
| **Silo** | ✅ reference/ — correct |

---

### Stream R10: Emsi/Lightcast — Career Transitions

| Field | Detail |
|-------|--------|
| **Source** | Emsi (now Lightcast) — PublicPoolData research dataset |
| **Collection** | Manual download (Stata .dta files) |
| **Raw files** | `Emsi-dataset.dta`, `Dashboard-transitions-dataset.dta`, `Dashboard-trajectories-dataset.dta` |
| **Ingest script** | `scripts/populate_mobility_data.py` |
| **DB tables** | `mob_occupation` (781 rows), `mob_transition` (256,831 rows) |
| **Update cadence** | Infrequent (dataset is stable research data, not a live feed) |
| **Used by** | Career Pathfinder — transition graph, wage direction, skill gap scores |
| **Silo** | ❌ **MISPLACED** — files currently in `~/Downloads/PublicPoolData/Employment/`, hardcoded in populate_mobility_data.py as `DEFAULT_DATA_DIR`. Should be in `data/reference/emsi/`. |

---

### Stream R11: Overture Maps — Austin POIs

| Field | Detail |
|-------|--------|
| **Source** | Overture Maps Foundation (Microsoft/Meta/Amazon consortium) |
| **Collection** | S3/DuckDB download or manual GeoJSON |
| **Raw file** | Currently at `data/overture_austin_places.geojson` (~200MB) |
| **Ingest script** | `scrapers/overture_adapter.py --local-file data/overture_austin_places.geojson` |
| **DB tables** | `local_employers` (45,618 rows), `brand_groups` (36,563 rows) |
| **Update cadence** | Quarterly |
| **Used by** | Job Fair Map (employer POIs), Career Pathfinder (nearby employers by SOC) |
| **Silo** | ⚠️ **MISPLACED** — currently at `data/` root instead of `data/reference/overture/`. Path defined in `config/paths.py` → `OVERTURE_GEOJSON` already points to the correct future location. File just hasn't been moved yet. |

---

## Silo 2 — API Response Cache

Intermediate files from live API calls. These aren't raw data in their own right — they're API responses saved to avoid redundant calls during development and re-ingestion. The canonical data is in PostgreSQL; these are just refetch-avoidance.

### Stream C1: BLS Time-Series API (CES / JOLTS / LAUS / CPI)

| Field | Detail |
|-------|--------|
| **Source** | BLS Public Data API v1/v2 |
| **Collection** | `scripts/download_bls_bulk.py` (API calls) |
| **Raw files** | `data/cache/bls/{series_id}.json` (~38 files) |
| **DB tables** | `qcew_data` (CES), `jolts_data` (JOLTS), `laus_data` (LAUS) |
| **Update cadence** | Monthly (via scheduler or manual run) |
| **Used by** | Scoring engine denominators; labor_market_baseline |
| **Silo** | ✅ cache/bls/ — correct |

---

### Stream C2: QCEW County API (BLS CEW)

| Field | Detail |
|-------|--------|
| **Source** | BLS QCEW public data files API (`data.bls.gov/cew/`) |
| **Collection** | `scrapers/qcew_adapter.py` (HTTP fetches county CSVs) |
| **Raw files** | **None currently** — goes straight to DB |
| **DB table** | `qcew_data` |
| **Update cadence** | Quarterly (per BLS release cycle) |
| **Used by** | Scoring engine `demand_pressure` (establishments denominator) |
| **Silo** | ⚠️ **MISSING CACHE** — should write raw CSV responses to `data/cache/qcew/` before DB insert, same pattern as BLS time series. Currently no replay capability if DB is lost. |

---

## Silo 3 — Skimmed Data

Raw data collected from the live internet. This is what gets converted into `ScraperSignal` objects and written to the `signals` table. **Currently none of this has file backing** — the only copy is in PostgreSQL.

Adding file storage here enables: re-processing signals with updated logic, debugging, training data for future ML models, and recovery from DB corruption.

Structure: `data/skimmed/{source}/{YYYY-MM-DD}/`

---

### Stream S1: Job Postings — Indeed / LinkedIn / Glassdoor

| Field | Detail |
|-------|--------|
| **Source** | python-jobspy (scrapes Indeed, LinkedIn, Glassdoor, ZipRecruiter) |
| **Collection** | `scrapers/jobspy_adapter.py` (daily via scheduler) |
| **Raw files** | Currently none — `ScraperSignal` objects go direct to DB |
| **DB tables** | `signals` (signal_type=listing), `wage_index` (wage signals) |
| **Update cadence** | Daily |
| **Used by** | Scoring engine `demand_pressure` (postings/establishment ratio) and `churn_signal` |
| **Silo** | ⚠️ **MISSING** — should land in `data/skimmed/job_postings/YYYY-MM-DD/` as JSON |

---

### Stream S2: Chain Careers APIs — Starbucks / Dutch Bros

| Field | Detail |
|-------|--------|
| **Source** | Workday CXS API (Starbucks), Dutch Bros careers search (Dutch Bros) |
| **Collection** | `scrapers/careers_api.py` (daily via scheduler) |
| **Raw files** | Currently none |
| **DB tables** | `signals` (signal_type=listing), `wage_index` |
| **Update cadence** | Daily |
| **Used by** | Scoring engine `demand_pressure`, store-level job posting velocity |
| **Silo** | ⚠️ **MISSING** — should land in `data/skimmed/careers_api/YYYY-MM-DD/` |

---

### Stream S3: Reddit Sentiment

| Field | Detail |
|-------|--------|
| **Source** | Reddit (PRAW OAuth or public JSON API) — r/Austin, r/jobs, brand subreddits |
| **Collection** | `scrapers/reddit_adapter.py` (daily via scheduler) |
| **Raw files** | Currently none |
| **DB tables** | `signals` (signal_type=sentiment) |
| **Update cadence** | Daily |
| **Used by** | Scoring engine `qualitative` component (15% weight) |
| **Silo** | ⚠️ **MISSING** — should land in `data/skimmed/reddit/YYYY-MM-DD/` |

---

### Stream S4: Reviews — Google Maps / Yelp

| Field | Detail |
|-------|--------|
| **Source** | Google Maps Places API + Yelp Fusion API |
| **Collection** | `scrapers/reviews_adapter.py` (weekly via scheduler) |
| **Raw files** | Currently none |
| **DB tables** | `signals` (signal_type=review_score, signal_type=sentiment) |
| **Update cadence** | Weekly |
| **Used by** | Scoring engine `qualitative` component |
| **Silo** | ⚠️ **MISSING** — should land in `data/skimmed/reviews/YYYY-MM-DD/` |

---

### Stream S5: WARN Act Layoff Notices

| Field | Detail |
|-------|--------|
| **Source** | Texas Workforce Commission WARN Act filings |
| **Collection** | `scrapers/warn_adapter.py` (weekly via scheduler) |
| **Raw files** | Currently none |
| **DB tables** | `signals` (signal_type=warn_notice) |
| **Update cadence** | Weekly |
| **Used by** | Layoff early-warning signal in staffing stress |
| **Silo** | ⚠️ **MISSING** — note: Revelio Labs also provides WARN data (R7 above). The direct scrape is a real-time supplement. Raw filings should go to `data/skimmed/warn/YYYY-MM-DD/` |

---

### Stream S6: NLRB Union Organizing Filings

| Field | Detail |
|-------|--------|
| **Source** | National Labor Relations Board case search |
| **Collection** | `scrapers/nlrb_adapter.py` (weekly via scheduler) |
| **Raw files** | Currently none |
| **DB tables** | `signals` (signal_type=union_activity) |
| **Update cadence** | Weekly |
| **Used by** | Staffing stress qualitative signal |
| **Silo** | ⚠️ **MISSING** — should land in `data/skimmed/nlrb/YYYY-MM-DD/` |

---

### Stream S7: Chain Locations — AllThePlaces

| Field | Detail |
|-------|--------|
| **Source** | AllThePlaces open dataset (web-scraped chain store directories) |
| **Collection** | `scrapers/alltheplaces_adapter.py` (monthly via scheduler) |
| **Raw files** | Currently none |
| **DB table** | `chain_locations` |
| **Update cadence** | Monthly |
| **Used by** | Job Fair Map (chain store locations) |
| **Silo** | ⚠️ **MISSING** — should land in `data/skimmed/alltheplaces/YYYY-MM-DD/` |

---

### Stream S8: Chain Locations — OpenStreetMap

| Field | Detail |
|-------|--------|
| **Source** | OpenStreetMap Overpass API |
| **Collection** | `scrapers/osm_adapter.py` (monthly via scheduler) |
| **Raw files** | Currently none |
| **DB table** | `chain_locations` |
| **Update cadence** | Monthly |
| **Used by** | Cross-reference for chain location verification |
| **Silo** | ⚠️ **MISSING** — should land in `data/skimmed/osm/YYYY-MM-DD/` |

---

## PostgreSQL — Live Operational Data

These tables are always computed or derived. They don't have a file representation; they're rebuilt from reference + skimmed inputs.

| Table | Populated by | Used by |
|-------|-------------|---------|
| `signals` | `backend/ingest.py` ← all scrapers | Scoring engine, wage_index |
| `scores` | `backend/scoring/engine.py` | Frontend map, targeting |
| `wage_index` | `backend/ingest.py` (wage signals) | Scoring `wage_competitiveness` |
| `snapshots` | `backend/ingest.py` | `/api/scan/status` |
| `labor_market_baseline` | `backend/baseline.py` | Scoring denominators |
| `chain_locations` | `backend/ingest_layer.py` ← Overture, ATP, OSM | Frontend chain layer |
| `local_employers` | `backend/ingest_layer.py` ← Overture | Frontend local layer |
| `brand_groups` | `backend/ingest_layer.py` | Deduplication, location_count |
| `oews_data` | R1/R2 ingest scripts | Scoring wages, config generation |
| `qcew_data` | C1/C2 adapters | Scoring `demand_pressure` |
| `jolts_data` | C1 download_bls_bulk.py | Scoring `churn_signal` |
| `laus_data` | C1 download_bls_bulk.py | labor_market_baseline |
| `cbp_data` | `scrapers/cbp_adapter.py` | Establishment density |
| `revelio_employment` | R3 revelio_ingest.py | Scoring `demand_pressure` |
| `revelio_hiring` | R4 revelio_ingest.py | Scoring `churn_signal` |
| `revelio_postings` | R5 revelio_ingest.py | Sector job opening benchmarks |
| `revelio_salaries` | R6 revelio_ingest.py | Wage cross-validation |
| `revelio_layoffs` | R7 revelio_ingest.py | Layoff signal |
| `mob_occupation` | R10 populate_mobility_data.py | Career Pathfinder |
| `mob_transition` | R10 populate_mobility_data.py | Career Pathfinder |
| `ref_occupation_aliases` | R9 load_occupation_aliases.py | Pathfinder autocomplete |
| `ref_brands`, `ref_industry`, etc. | populate_reference_data.py | Reference lookups |

---

## Issues to Fix

### High Priority

| # | Issue | Action |
|---|-------|--------|
| 1 | **Revelio data not ingested** (R3–R7) | `python scrapers/revelio_ingest.py --all --region Texas` |
| 2 | **Emsi .dta files in ~/Downloads** (R10) | Move to `data/reference/emsi/`, update `DEFAULT_DATA_DIR` in `populate_mobility_data.py` |
| 3 | **Overture GeoJSON at data root** (R11) | Move to `data/reference/overture/`, update any callers referencing old path |
| 4 | **QCEW has no raw file cache** (C2) | Add `data/cache/qcew/` write step to `qcew_adapter.py` before DB insert |

### Medium Priority

| # | Issue | Action |
|---|-------|--------|
| 5 | **No skimmed file layer** (S1–S8) | Add raw file dump to each scraper before `ingest_signals()` call |
| 6 | **TexasWages has no ingest script** (R8) | Build `scrapers/texaswages_ingest.py` and DB schema |
| 7 | **Legacy SQLite files** (`data/tracker.db`, `data/tracker_pre_v2_*.db`) | Archive to `data/archive/` or delete; PostgreSQL is now authoritative |

### Low Priority

| # | Issue | Action |
|---|-------|--------|
| 8 | **SpiritPool SQLite outside main DB** (`data/tracker.db` spiritpool reference) | Migrate to PostgreSQL or formally decommission |

---

## Current Directory State (Post-Rename)

```
data/
├── reference/
│   ├── bls/                          ← R1 Austin OEWS .ods
│   ├── OEWS_wage_data/               ← R2 national bulk .xlsx
│   ├── revelioLabs/                  ← R3-R7 Revelio CSVs (PENDING INGEST)
│   ├── texaswages/                   ← R8 TexasWages CSVs (NO INGEST SCRIPT)
│   ├── emsi/                         ← R10 (DOES NOT EXIST YET — files in ~/Downloads)
│   ├── overture/                     ← R11 (DOES NOT EXIST YET — GeoJSON at data root)
│   ├── Alphabetical-Index-of-Occupations-December-2019_Final.xlsx  ← R9
│   └── DataCollectionSources.md
├── cache/
│   ├── bls/                          ← C1 BLS time-series JSON ✅
│   └── qcew/                         ← C2 (DOES NOT EXIST YET — no raw cache)
├── skimmed/                          ← S1-S8 (DOES NOT EXIST YET — all in PostgreSQL only)
│   ├── job_postings/
│   ├── careers_api/
│   ├── reddit/
│   ├── reviews/
│   ├── warn/
│   ├── nlrb/
│   ├── alltheplaces/
│   └── osm/
├── overture_austin_places.geojson    ← SHOULD MOVE to reference/overture/
├── tracker.db                        ← LEGACY SQLite (PostgreSQL is now authoritative)
└── tracker_pre_v2_20260323_023337.db ← LEGACY backup
```
