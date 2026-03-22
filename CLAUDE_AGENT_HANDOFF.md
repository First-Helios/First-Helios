# Claude Agent Handoff — ChainStaffingTracker

**Date:** 2026-03-22  
**Branch:** `main` (commit `24aa1c8`)  
**Backup branch:** `agent-workflow-backup` (preserves removed OpenClaw agent code)  
**Working directory:** `/home/fortune/CodeProjects/First-Helios`  
**Python venv:** `.venv/` (Python 3, activate via `source .venv/bin/activate`)

---

## 1. What This Project Does

**ChainStaffingTracker** monitors staffing stress at chain store locations (Starbucks, Dutch Bros) in the Austin, TX metro area. It collects data from multiple public APIs and web sources, scores each store location on a composite staffing-stress index, and serves the results via a Flask web app with a Leaflet map frontend.

The system was recently overhauled to use **government labor-market data as ground truth** instead of ad-hoc weighted averages. Scoring now uses real establishment counts (QCEW), turnover rates (JOLTS), occupation wages (OEWS), and unemployment (LAUS) as denominators and benchmarks.

**Core loop:**
1. Scheduled scrapers pull data from Workday careers APIs, job boards, Reddit, Google Maps reviews, BLS, QCEW, Census CBP
2. Raw observations are stored as `Signal` rows in `tracker.db`
3. Scoring engine computes a composite score per store using 4 sub-scores grounded in labor economics
4. Results are served at `http://localhost:8765` on a Leaflet map

---

## 2. Tech Stack

| Component | Technology | Version |
|---|---|---|
| Language | Python 3 | 3.x |
| Web server | Flask | 3.1.3 |
| ORM / DB | SQLAlchemy + SQLite | 2.0.48 |
| Scheduler | APScheduler (BackgroundScheduler) | 3.11.2 |
| HTTP | requests | 2.32.5 |
| Job boards | python-jobspy | 1.1.82 |
| Reddit | PRAW | 7.8.1 |
| Geodata | geopy, overturemaps | 2.4.1, 0.19.0 |
| Browser fallback | Playwright | 1.58.0 |
| Data | pandas, numpy, pyarrow | 2.3.3, 2.4.3, 23.0.1 |
| Frontend | Vanilla JS + Leaflet.js + CSS | — |

**No requirements.txt exists.** Use `pip freeze` to generate one if needed.

---

## 3. Project Structure

```
First-Helios/
├── server.py                      # Flask app, port 8765, all API routes
├── config/
│   ├── chains.yaml                # SINGLE SOURCE OF TRUTH for all config
│   └── loader.py                  # Typed accessor functions for chains.yaml
├── backend/
│   ├── database.py                # SQLAlchemy models (22 tables)
│   ├── baseline.py                # Combines QCEW+JOLTS+OEWS+LAUS → LaborMarketBaseline
│   ├── ingest.py                  # Signal ingestion pipeline
│   ├── scheduler.py               # APScheduler job definitions (12 jobs)
│   ├── targeting.py               # Store targeting/prioritization
│   ├── rate_manager.py            # API rate limit tracking
│   ├── tracked_request.py         # HTTP request wrapper with rate tracking
│   ├── scoring/
│   │   ├── engine.py              # 4-component composite scoring
│   │   ├── careers.py             # Job posting count scoring
│   │   ├── sentiment.py           # Reddit/review sentiment scoring
│   │   └── wage.py                # Wage gap scoring
│   └── models/
│       └── reference.py           # Reference data models (brands, industries, regions)
├── scrapers/
│   ├── base.py                    # BaseScraper + ScraperSignal classes
│   ├── careers_api.py             # Workday careers API (Starbucks)
│   ├── bls_adapter.py             # BLS Public Data API (CES + JOLTS + LAUS)
│   ├── qcew_adapter.py            # BLS QCEW CSV API (county establishments)
│   ├── cbp_adapter.py             # Census CBP API (ZIP-level establishments)
│   ├── jobspy_adapter.py          # python-jobspy multi-board scraper
│   ├── reddit_adapter.py          # PRAW Reddit sentiment
│   ├── reviews_adapter.py         # Google Maps reviews
│   ├── alltheplaces_adapter.py    # AllThePlaces store discovery
│   ├── overture_adapter.py        # Overture Maps (chain + local employers)
│   ├── osm_adapter.py             # OpenStreetMap Overpass fallback
│   ├── geocoding.py               # Geocoding utilities
│   └── playwright_fallback.py     # Browser-based scraping fallback
├── frontend/
│   ├── index.html                 # Main Leaflet map page
│   ├── metrics.html               # API metrics dashboard
│   ├── openclaw.html / openclaw_session.html  # (legacy agent UI)
│   ├── css/                       # Stylesheets
│   └── js/                        # Frontend JS (app.js, metrics.js, nav.js)
├── data/
│   └── tracker.db                 # SQLite database (auto-created)
├── tests/                         # ⚠️ EMPTY — test files were removed, need rewriting
│   ├── conftest.py                # Exists but likely stale
│   └── pytest.ini
├── scripts/
│   ├── backfill_geocoding.py
│   └── populate_reference_data.py
└── pipeline/
    ├── health.py
    ├── route_index.py
    ├── tracing.py
    └── validation.py
```

---

## 4. Database Schema (22 tables in `data/tracker.db`)

### Core operational tables (populated):
| Table | Rows | Purpose |
|---|---|---|
| `stores` | 24 | Physical chain locations (Starbucks/Dutch Bros in Austin) |
| `signals` | 24 | Raw observations from all data sources |
| `scores` | 96 | Computed per-store scores (composite + 3 sub-scores × 24 stores) |
| `snapshots` | 1 | Periodic scan summaries |
| `wage_index` | 12 | Local vs chain pay comparison data |
| `local_employers` | 0 | Non-chain POIs from Overture/OSM |

### Reference tables (populated):
| Table | Rows | Purpose |
|---|---|---|
| `ref_brands` | 6 | Brand profiles |
| `ref_industry` | 11 | Industry categories |
| `ref_category_map` | 168 | Category → industry mappings |
| `ref_regions` | 1 | Region definitions (austin_tx) |

### API rate tracking (populated):
| Table | Rows | Purpose |
|---|---|---|
| `api_sources` | 16 | Registered API sources |
| `api_endpoints` | 16 | API endpoint definitions |
| `api_request_log` | 0 | Per-request tracking |
| `rate_budgets` | 0 | Daily usage rollups |
| `source_freshness` | 0 | Data freshness tracking |

### NEW ground-truth tables (empty — need first data fetch):
| Table | Cols | Purpose |
|---|---|---|
| `qcew_data` | 16 | County-level establishments & employment (quarterly, ~6mo lag) |
| `cbp_data` | 10 | ZIP-level establishments (annual, ~18mo lag) |
| `jolts_data` | 9 | National turnover rates by industry (monthly, ~2mo lag) |
| `oews_data` | 16 | MSA occupation wages at percentiles (annual) |
| `laus_data` | 11 | County unemployment rates (monthly, ~2mo lag) |
| `labor_market_baseline` | 18 | Computed baselines combining all ground-truth sources |

---

## 5. Configuration (`config/chains.yaml`)

**Every tunable value lives here.** No hardcoded constants in code. `config/loader.py` provides typed accessor functions.

### Key sections:
- **`regions.austin_tx`** — center lat/lng, radius, location string
- **`industries.coffee_cafe`** — search terms, subreddits, sentiment keywords
- **`chains.starbucks` / `chains.dutch_bros`** — careers API URLs, target roles, standing postings per store
- **`scoring.weights`** — `{demand_pressure: 0.35, wage_competitiveness: 0.25, churn_signal: 0.25, qualitative: 0.15}`
- **`scoring.tiers`** — critical (≥67th pctl), elevated (≥33rd), adequate (<33rd)
- **`scoring.baseline`** — reference period `2025-Q3`, reindex_on_new_qcew
- **`scoring.seasonal`** — enabled, peak months [5,6,7], trough [1,2]
- **`bls_series`** — 12 series IDs categorized as `ces` / `jolts` / `laus` with series_id, description, metric, industry_code, fips_code
- **`qcew`** — 5 county FIPS (Travis/Williamson/Hays/Bastrop/Caldwell), 5 NAICS codes (722515 coffee shops through 72 accommodation & food services), ownership_code 5 (private)
- **`cbp`** — 25 Austin-area ZIP codes, 3 NAICS codes, api_key (null → use `CBP_API_KEY` env var)
- **`oews`** — area_code 12420 (Austin MSA), 5 SOC occupation codes (35-0000 through 35-3021)
- **`scheduler`** — cron definitions for all 12 jobs
- **`rate_limits`** — per-source delay settings
- **`http`** — timeout 30s, retries 3, backoff 2.0, user agent string

---

## 6. Scoring Engine Architecture

### Previous approach (replaced):
Arbitrary weighted average: `0.40 × careers_api + 0.35 × job_boards + 0.25 × sentiment`

### Current approach (economically grounded):
```
Composite = w₁·demand_pressure + w₂·wage_competitiveness + w₃·churn_signal + w₄·qualitative
```

Each component has an economic interpretation:

| Component | Weight | Formula | Data Source | Meaning |
|---|---|---|---|---|
| demand_pressure | 35% | `(postings/establishment) / regional_norm × 50` | QCEW establishments | How many postings vs. what's normal for this many locations |
| wage_competitiveness | 25% | `50 + gap_pct` where gap = (market - chain)/market | OEWS median or local avg | How far below market the chain pays |
| churn_signal | 25% | `(listing_velocity / expected_separations) × 50` | JOLTS quits rate | Are postings above what normal turnover explains? |
| qualitative | 15% | Sentiment score from Reddit + Google Reviews | Reddit, Google Maps | Customer/employee observation of staffing problems |

**Scale:** 0-100 for each sub-score. 50 = normal/at-market. 100 = 2× worse than normal.

**Fallback behavior:** When ground-truth tables are empty (no QCEW/JOLTS data yet), the engine automatically falls back to percentile-based ranking within the region. This is the current state — the ground-truth tables need their first data fetch.

**Seasonal adjustment:** When enabled, divides final composite by seasonal_index (>1 during summer hiring surge deflates the score, <1 during winter inflates it).

**Weight redistribution:** If a sub-score can't be computed (missing data), its weight is redistributed proportionally to the remaining components.

---

## 7. Scheduler (12 Jobs)

| Job ID | Schedule | Function | What it does |
|---|---|---|---|
| `careers_api` | Daily 3am | `_run_careers_api()` | Starbucks Workday careers API → signals → rescore |
| `jobspy` | Daily 4am | `_run_jobspy()` | python-jobspy chain + wage modes → signals → rescore |
| `reddit` | Every 6h | `_run_reddit()` | PRAW subreddit sentiment → signals → rescore |
| `google_maps` | Mon 5am | `_run_reviews()` | Google Maps review scraping → signals → rescore |
| `bls` | Mon 6am | `_run_bls()` | BLS CES + JOLTS + LAUS → wage_index + jolts_data + laus_data |
| `atp_starbucks_austin` | Sun 2am | `_run_alltheplaces()` | AllThePlaces store discovery |
| `overture_starbucks_austin` | Sun 2:15am | `_run_overture_chain()` | Overture chain cross-validation |
| `osm_starbucks_austin` | Sun 2:30am | `_run_osm()` | OSM Overpass store fallback |
| `overture_local_austin` | Sun 3am | `_run_overture_local()` | Overture local employer discovery |
| `qcew` | 1st of month 7am | `_run_qcew()` | QCEW county establishments (active months: Jan/Apr/Jul/Oct) |
| `cbp` | Mon 8am | `_run_cbp()` | Census CBP ZIP establishments (active month: Apr only) |
| `baseline_recompute` | Sun 4am | `_run_baseline_recompute()` | Recompute LaborMarketBaseline from all ground-truth |

---

## 8. Data Source Details

### External APIs:

| Source | Auth | Rate Limit | Adapter | DB Target |
|---|---|---|---|---|
| BLS Public Data API v1 | None (no key) | 500 req/day | `scrapers/bls_adapter.py` | `wage_index`, `jolts_data`, `laus_data` |
| BLS QCEW CSV API | None | Undocumented (pace 1/sec) | `scrapers/qcew_adapter.py` | `qcew_data` |
| Census CBP API | API key required | Generous | `scrapers/cbp_adapter.py` | `cbp_data` |
| Starbucks Workday | None (public) | Paced 1/sec | `scrapers/careers_api.py` | `signals` (listing) |
| python-jobspy | None | Paced | `scrapers/jobspy_adapter.py` | `signals` (listing) + `wage_index` |
| Reddit (PRAW) | OAuth | 2/sec | `scrapers/reddit_adapter.py` | `signals` (sentiment) |
| Google Maps | Browser-based | Paced 3-5s | `scrapers/reviews_adapter.py` | `signals` (review_score) |
| AllThePlaces | None (static files) | N/A | `scrapers/alltheplaces_adapter.py` | `stores` |
| Overture Maps | None (public) | N/A | `scrapers/overture_adapter.py` | `stores`, `local_employers` |
| OSM Overpass | None | Paced | `scrapers/osm_adapter.py` | `stores` |

### Government data release cadence:
- **QCEW**: Quarterly, ~6 month lag. As of 2026-03, latest available is **2025-Q3**.
- **CBP**: Annual, ~18 month lag. Latest available is **2024**.
- **JOLTS**: Monthly, ~2 month lag.
- **LAUS**: Monthly, ~2 month lag.
- **OEWS**: Annual, published May each year.
- **CES**: Monthly, ~1 month lag.

---

## 9. How to Run

```bash
cd /home/fortune/CodeProjects/First-Helios
source .venv/bin/activate
python server.py           # Starts Flask on port 8765, auto-starts scheduler
python server.py --debug   # Debug mode with hot reload
```

Browse to `http://localhost:8765/`.

### Run individual adapters from CLI:
```bash
python scrapers/qcew_adapter.py --region austin_tx
python scrapers/cbp_adapter.py --region austin_tx
python scrapers/bls_adapter.py --region austin_tx
```

---

## 10. Outstanding Work (Priority Order)

### 10.1 — First Live Data Fetch (HIGH PRIORITY)
The 6 new ground-truth tables are **empty**. The scoring engine currently runs in fallback mode (percentile ranking). To activate economically-grounded scoring:

1. **Run QCEW adapter:** `python scrapers/qcew_adapter.py --region austin_tx`
   - Fetches 2025-Q3 data for 5 counties × 5 NAICS codes from BLS CSV API
   - No API key needed

2. **Run BLS adapter** (JOLTS + LAUS): `python scrapers/bls_adapter.py --region austin_tx`
   - Fetches 4 JOLTS series + 3 LAUS series from BLS Public Data API
   - No API key needed, but 500 requests/day limit

3. **Run baseline computation:** 
   ```python
   from backend.baseline import compute_baselines
   compute_baselines(region="austin_tx")
   ```

4. **Rescore all stores:**
   ```python
   from backend.scoring.engine import compute_all_scores
   compute_all_scores(region="austin_tx")
   ```

After this, scoring will use real establishment counts, turnover rates, and unemployment data.

### 10.2 — Census CBP API Key
The CBP adapter requires a free API key from https://api.census.gov/data/key_signup.html. Set it via:
- Environment variable: `export CBP_API_KEY=your_key_here`
- Or in `config/chains.yaml` under `cbp.api_key`

### 10.3 — Build OEWS Adapter (MEDIUM PRIORITY)
The `oews_data` table and config exist (5 SOC occupations for Austin MSA area code 12420), but **no adapter fetches the data**. BLS OEWS uses a separate flat-file download, not the standard Public Data API:
- Download from: https://www.bls.gov/oes/tables.htm
- Format: Excel/CSV flat files by MSA
- Need: Parse the Austin-Round Rock-Georgetown MSA (area code 12420) rows for SOC codes 35-0000, 35-3023, 35-2021, 35-1012, 35-3021
- Write to `oews_data` table fields: area_code, occ_code, occ_title, employment, wage_mean_hourly, wage_median_hourly, wage_10pct/25pct/75pct/90pct, year
- Alternative: BLS OEWS has an API option at `https://api.bls.gov/publicAPI/v2/timeseries/data/` with series IDs like `OEUM001242000000035302103` but this requires constructing series IDs per occupation/area

### 10.4 — Register `census_cbp` in API Sources (LOW)
The CBP adapter uses `source_key="census_cbp"` for rate tracking via `tracked_request`, but this source isn't registered in the `api_sources` table yet. Run:
```python
from backend.database import ApiSource, get_session, init_db
engine = init_db()
session = get_session(engine)
session.add(ApiSource(
    source_key="census_cbp",
    display_name="Census County Business Patterns",
    base_url="https://api.census.gov/data",
    auth_type="api_key",
    daily_limit=10000,
    min_delay_seconds=1.0,
))
session.commit()
```
Also register `bls_qcew`:
```python
session.add(ApiSource(
    source_key="bls_qcew",
    display_name="BLS QCEW CSV API",
    base_url="https://data.bls.gov/cew/data/api",
    auth_type="none",
    daily_limit=10000,
    min_delay_seconds=1.0,
))
session.commit()
```

### 10.5 — Write Tests (MEDIUM PRIORITY)
The `tests/` directory is empty — all prior test files were removed during the branch cleanup. Tests needed:

**Unit tests:**
- `test_config_loader.py` — verify all `get_*` functions return expected types/keys
- `test_database_models.py` — verify all 22 tables create, computed properties work (QCEWRecord.avg_employment, etc.)
- `test_baseline.py` — mock QCEW/JOLTS/OEWS/LAUS rows, verify `compute_baselines()` produces correct output
- `test_scoring_engine.py` — test all 4 sub-score functions with and without baseline data, verify fallback behavior
- `test_qcew_adapter.py` — mock HTTP responses, verify CSV parsing and DB writes
- `test_cbp_adapter.py` — mock Census API JSON responses, verify DB writes
- `test_bls_adapter.py` — test CES/JOLTS/LAUS fetch paths separately with mocked API

**Integration tests:**
- Full pipeline: QCEW fetch → baseline compute → scoring → verify scores change
- Scheduler init: verify all 12 jobs register with correct triggers

**Testing infrastructure:**
- `conftest.py` should provide a temporary in-memory SQLite DB and session fixture
- `pytest.ini` exists at `tests/pytest.ini`

### 10.6 — Git Housekeeping
- Generate `requirements.txt` from current venv: `pip freeze > requirements.txt`
- Consider `.env` file for CBP_API_KEY and any Reddit PRAW credentials
- The `Discard/` folder contains old handoff docs from previous sessions — can be cleaned up

---

## 11. Key Formulas Reference

### Demand Pressure (ground-truth mode):
```
regional_per_establishment = total_weighted_listings / QCEW_establishment_count
ratio = store_weighted_listings / regional_per_establishment
score = min(100, ratio × 50)    # 1× normal = 50, 2× = 100
```

### Wage Competitiveness:
```
gap_pct = (market_median − chain_wage) / market_median × 100
score = max(0, min(100, 50 + gap_pct))    # 50 = at market, 100 = 50% below
```

### Churn Signal (ground-truth mode):
```
expected_monthly_separations = QCEW_employment × JOLTS_quits_rate / 100
per_store_expected = expected_monthly_separations / n_active_stores
ratio = store_weighted_listings / per_store_expected
score = min(100, ratio × 50)    # 1× expected = 50, 2× = 100
```

### Seasonal Adjustment:
```
seasonal_index = current_quarter_QCEW_employment / trailing_4Q_average
adjusted_score = composite / seasonal_index
```

### Weighted Listing Count (from careers.py):
Listings are weighted by age: fresh (<7 days) = full weight, stale (>90 days) = 0, linear decay between.

---

## 12. Austin MSA Geographic Reference

**Counties covered (QCEW):**
- Travis (48453) — Austin core
- Williamson (48491) — Round Rock, Cedar Park, Georgetown
- Hays (48209) — San Marcos, Kyle, Buda
- Bastrop (48021) — Bastrop, Elgin
- Caldwell (48055) — Lockhart, Luling

**ZIP codes covered (CBP):** 25 ZIPs spanning Downtown Austin → Round Rock → Georgetown → Pflugerville → Cedar Park → Leander → Hutto

**MSA code:** 12420 (Austin-Round Rock-Georgetown, TX)

**NAICS codes tracked:**
- 722515 — Snack and Nonalcoholic Beverage Bars (coffee shops)
- 722513 — Limited-Service Restaurants
- 722511 — Full-Service Restaurants
- 7225 — Restaurants and Other Eating Places
- 72 — Accommodation and Food Services

---

## 13. Known Quirks / Gotchas

1. **`config/chains.yaml` has TWO `scoring:` sections.** The second one (with `demand_pressure` etc.) overrides the first (with `careers_api` etc.) at YAML load time. The first is effectively dead code but remains for reference. Only the second section's weights are used.

2. **Starbucks Workday API** sometimes requires specific JSON payload structure. See `scrapers/careers_api.py` for the exact request format.

3. **`data/tracker.db` is auto-created** by `init_db()` on first Flask startup. Delete it to reset; all tables recreate automatically.

4. **Port 8765 is hardcoded** in `server.py` argument defaults. Don't change it — the frontend references it.

5. **AllThePlaces store discovery** downloads large GeoJSON files. The adapter filters by chain brand name and geographic bounding box.

6. **BLS API v1 (no key)** has a 500 request/day limit. v2 (with key) allows 500/day but with longer series. Current code uses v1.

7. **The `agent-workflow-backup` branch** contains OpenClaw AI agent code (LLM-driven data collection planning). It was removed from `main` intentionally. Don't merge it back unless specifically asked.

8. **`scraper/scrape.py`** (note: singular `scraper/`, not `scrapers/`) is a legacy file, separate from the main scraper framework.

---

## 14. Quick Validation Commands

```bash
# Verify config loads
python -c "from config.loader import *; print(f'Series: {len(get_bls_series())}, ZIPs: {len(get_cbp_zip_codes())}, Counties: {len(get_qcew_county_fips())}')"

# Verify DB tables
python -c "from backend.database import init_db; import sqlite3; init_db(); conn = sqlite3.connect('data/tracker.db'); print([t[0] for t in conn.execute(\"SELECT name FROM sqlite_master WHERE type='table'\").fetchall()])"

# Verify scheduler registers all jobs
python -c "from backend.scheduler import init_scheduler; s = init_scheduler(); print(f'{len(s.get_jobs())} jobs: {[j.id for j in s.get_jobs()]}'); s.shutdown()"

# Verify scoring runs (fallback mode)
python -c "from backend.scoring.engine import compute_all_scores; r = compute_all_scores('austin_tx'); print(f'{len(r)} stores scored')"

# Start server
python server.py
curl -s http://localhost:8765/ | head -3
```

---

## 15. File-Level Change Log (Most Recent Session)

### Modified files:
| File | Lines | What changed |
|---|---|---|
| `backend/database.py` | 714 | Added 7 new model classes (QCEWRecord, CBPRecord, JOLTSRecord, OEWSRecord, LAUSRecord, LaborMarketBaseline, LocalEmployer), added Index import |
| `backend/scoring/engine.py` | 552 | Complete rewrite: 4-component grounded scoring with ground-truth baselines and percentile fallback |
| `backend/scheduler.py` | 440 | Added 3 new scheduled jobs (qcew, cbp, baseline_recompute) and their runner functions |
| `config/chains.yaml` | 375 | Added bls_series categories (jolts/laus), qcew section, cbp section, oews section, new scoring weights/baseline/seasonal, new scheduler entries |
| `config/loader.py` | 216 | Added 10 new accessor functions for QCEW, CBP, OEWS, baseline, seasonal config; added `os` import |
| `scrapers/bls_adapter.py` | 429 | Extended to handle JOLTS and LAUS series in addition to CES; new `_fetch_jolts_series()` and `_fetch_laus_series()` methods |

### New files:
| File | Lines | Purpose |
|---|---|---|
| `backend/baseline.py` | 333 | Labor market baseline computation: combines QCEW+JOLTS+OEWS+LAUS into LaborMarketBaseline table |
| `scrapers/qcew_adapter.py` | 347 | BLS QCEW CSV API adapter for county-level establishment/employment data |
| `scrapers/cbp_adapter.py` | 316 | Census CBP API adapter for ZIP-level establishment data |
