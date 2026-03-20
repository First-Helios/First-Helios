# CLAUDE_AGENT_HANDOFF.md — ChainStaffingTracker

**Date:** 2026-03-19
**Project root:** `/home/fortune/CodeProjects/First-Helios`
**Venv:** `.venv/` (Python 3.12)

---

## What This Project Is

A public-data intelligence tool that detects **staffing stress at chain employer locations** in Austin, TX and ranks where community job fairs will have maximum labor-market impact. The build spec lives in `.github/agents/AGENT.md` (519 lines, extremely detailed — read it first).

The whole thing was built from scratch in one session. Before I started, the repo had only `README.md` and `.github/agents/AGENT.md`.

---

## What Was Built (3,748 lines of Python + frontend + config)

### Architecture

```
                  ┌──────────────┐
                  │ config/      │  chains.yaml → loader.py
                  │ (all config) │  zero hardcoded values
                  └──────┬───────┘
                         │
    ┌────────────────────┼────────────────────┐
    │                    │                    │
┌───┴────┐  ┌───────────┴──────┐  ┌──────────┴───────┐
│scrapers│  │backend/scoring/  │  │backend/          │
│  6 adapters│  3 sub-scorers  │  │  ingest, target, │
│        │  │  + engine        │  │  scheduler, db   │
└───┬────┘  └───────┬──────────┘  └─────────┬────────┘
    │               │                       │
    └───────────────┴───────────────────────┘
                    │
              ┌─────┴──────┐
              │ server.py  │  Flask on :8765
              │ 6 API      │
              │ endpoints  │
              └─────┬──────┘
                    │
              ┌─────┴──────┐
              │ frontend/  │  Leaflet map (dark theme)
              └────────────┘
```

### Files Created

| File | Lines | What It Does |
|------|-------|-------------|
| `config/chains.yaml` | 186 | ALL config: regions, chains, industries, scoring weights, BLS series, scheduler crons, rate limits |
| `config/loader.py` | 144 | Typed accessor functions for the YAML. Every module imports from here. |
| `scrapers/base.py` | 71 | `ScraperSignal` dataclass + `BaseScraper` ABC. Every scraper produces these. |
| `scrapers/careers_api.py` | 322 | Starbucks Workday API scraper. **Currently blocked by Cloudflare** — returns 422. Fails gracefully. |
| `scrapers/jobspy_adapter.py` | 311 | Wraps `python-jobspy` for Indeed/Glassdoor. **This is the primary working data source.** Two modes: `chain` (Starbucks-specific listings) and `wage` (local employer listings for wage comparison). |
| `scrapers/reddit_adapter.py` | 291 | Reddit JSON API (no auth needed) or PRAW (with creds). Keyword-scans r/starbucks, r/starbucksbaristas, r/Austin for staffing-stress terms. |
| `scrapers/bls_adapter.py` | 175 | BLS Public Data API v1. Series IDs in config were wrong, I fixed them to verified-working ones. Hit the daily rate limit during testing so couldn't run a full live test. |
| `scrapers/reviews_adapter.py` | 188 | Google Maps reviews adapter (uses `google-maps-scraper` library). Written but **not live-tested**. |
| `scrapers/geocoding.py` | 106 | Store number extraction + geocoding stub. **Geocoding not implemented** — all stores have `lat=None, lng=None`. |
| `scraper/scrape.py` | 99 | Legacy CLI wrapper. Preserves `python scraper/scrape.py --location "Austin, TX, US" --radius 25`. Delegates to `scrapers/careers_api.py`. |
| `backend/database.py` | 222 | SQLAlchemy models for 5 tables: `stores`, `signals`, `snapshots`, `scores`, `wage_index`. Uses `data/tracker.db`. |
| `backend/ingest.py` | 169 | Takes `list[ScraperSignal]` → upserts stores, inserts signals, populates wage_index, creates snapshot records. |
| `backend/scoring/engine.py` | 298 | Composite scorer. Gathers signals per store, calls sub-scorers, writes `Score` rows. Redistributes weights proportionally when a source has no data. |
| `backend/scoring/careers.py` | 168 | **The fix for the 87% critical bug.** Age-decay (fresh=7d, stale=90d) + baseline-relative percentile scoring. |
| `backend/scoring/sentiment.py` | 98 | Reddit/review sentiment sub-score. Averages signal values per store. |
| `backend/scoring/wage.py` | 129 | Wage gap sub-score. Compares chain wages to local average. |
| `backend/targeting.py` | 358 | Computes `TargetingScore` per store: staffing_stress (40%) + wage_gap (30%) + isolation (20%) + local_alternatives (10%). Haversine distance for isolation. |
| `backend/scheduler.py` | 210 | APScheduler — 5 jobs: careers daily 3am, jobspy daily 4am, reddit every 6hr, google_maps weekly Mon 5am, bls weekly Mon 6am. |
| `server.py` | 373 | Flask app. Endpoints: `/api/scores`, `/api/targeting`, `/api/wage-index`, `/api/scan/status`, `POST /api/scan`, `/api/scheduler/status`, `/api/spiritpool/stats`. Serves `frontend/` as static. |
| `frontend/index.html` | ~80 | Leaflet map SPA with CARTO dark tiles |
| `frontend/css/style.css` | ~100 | Dark theme, sidebar, cards |
| `frontend/js/app.js` | ~200 | Fetches API, renders map markers + sidebar |
| `RUNBOOK.md` | ~60 | How to install, run, troubleshoot |

### Key Dependencies (in `.venv/`)

```
Flask 3.1.3, SQLAlchemy 2.0.48, python-jobspy 1.1.82, praw 7.8.1,
APScheduler 3.11.2, pandas 2.3.3, PyYAML 6.0.3, cloudscraper 1.2.71
```

---

## What Works

### Confirmed Working End-to-End

1. **JobSpy scraper (Indeed)** — Primary data source. Ran successfully twice:
   - Chain mode: `python scrapers/jobspy_adapter.py --chain starbucks --region austin_tx --mode chain` → **14 signals for 9 stores**
   - Wage mode: `python scrapers/jobspy_adapter.py --industry coffee_cafe --region austin_tx --mode wage` → **47 signals, 9 wage_index entries**
   - Local avg hourly wage computed: **$17.61/hr** (from Smoothie King, Nordstrom, Eurest, Oakwood, Johnny Beans, Marriott)

2. **Reddit scraper (JSON API, no auth)** — `python scrapers/reddit_adapter.py --region austin_tx` → **6 sentiment signals** from r/starbucks, r/starbucksbaristas, r/Austin. Found keyword matches for "quitting", "overworked", etc.

3. **Scoring engine** — The main deliverable. After running both scrapers + scoring:
   ```
   critical: 3 stores (30%)
   elevated: 6 stores (60%)
   unknown:  1 store  (10%, REGIONAL placeholder)
   ```
   **The 87%-critical bug is fixed.** Age decay zeros out standing requisitions (>90 days). Baseline-relative scoring distributes stores across tiers by comparing listing counts within the regional cohort.

4. **All 6 API endpoints** — Server runs on `:8765`, tested with curl:
   - `GET /api/scores?region=austin_tx&chain=starbucks` → 9 stores with composite scores, sub-scores, tiers
   - `GET /api/targeting?industry=coffee_cafe&region=austin_tx&limit=3` → 3 prime targets with timing recommendations
   - `GET /api/wage-index?industry=coffee_cafe&region=austin_tx` → 9 local wage entries, avg $17.61/hr
   - `GET /api/scan/status` → latest snapshot info
   - `GET /api/scheduler/status` → 5 jobs with next-run times
   - `GET /api/spiritpool/stats` → stub (spiritpool.db doesn't exist, returns empty)

5. **Legacy CLI** — `python scraper/scrape.py --location "Austin, TX, US" --radius 25` runs without crashing (returns 0 signals because Workday API is blocked, but doesn't break)

6. **APScheduler** — 5 background jobs registered and running inside Flask

### Database State Right Now

```
stores:     10 rows (9 Starbucks + 1 REGIONAL)
signals:    67 rows (52 listings + 9 wages + 6 sentiment)
snapshots:   3 rows
scores:     36 rows (9 stores × 4 score types)
wage_index:  9 rows (local employers only)
```

---

## What's Broken / Not Working

### 1. Starbucks Workday API — HTTP 422 (BLOCKED)

The careers API at `https://starbucks.wd1.myworkdayjobs.com/wday/cxs/starbucks/StarbucksExternalCareerSite/jobs` rejects every request with `{"errorCode":"HTTP_422"}`. I tried:
- Plain `requests.post()` with various payloads
- Session-based approach (GET page first to get cookies, then POST)
- Browser-like headers (Origin, Referer, full Chrome UA)
- `cloudscraper` library (Cloudflare bypass)
- Various payload formats (empty facets, location facets, different key names)
- The page itself returns Cloudflare cookies (`__cf_bm`, `_cfuvid`) and HTTP 500

**Root cause:** Cloudflare bot protection + JavaScript-rendered SPA. The site requires a full browser JS runtime. Would need Playwright headless to fix.

**Impact:** The `scrapers/careers_api.py` scraper fails gracefully (logs a warning, returns empty list). JobSpy covers the same job listings via Indeed, so this is not a blocker for data collection. However, the Workday API would give us *posting creation dates* (for age-decay scoring), which Indeed doesn't reliably provide.

### 2. No Geocoding — All Stores Have `lat=None, lng=None`

The `scrapers/geocoding.py` has a `geocode()` function but it's a stub that returns `(None, None)`. Every store in the DB has null coordinates. This means:
- The Leaflet map can't plot markers
- The targeting `isolation` score defaults to 50 (neutral) for all stores
- The `local_alternatives` score also defaults to 50

**Fix needed:** Add Nominatim (free, no key) or Google Geocoding calls. It's ~20 lines of code.

### 3. Chain Wage Data Not Populated

The `wage_index` table has 9 rows, all with `is_chain=False`. No Starbucks-specific wage data exists because:
- Workday API is blocked (would normally provide this)
- JobSpy chain-mode listings go into `signals` as type "listing", not into `wage_index`
- The `ingest.py` logic only writes to `wage_index` when `signal.wage_min` is not None AND the signal is from a wage-type source

**Impact:** The wage gap score defaults to 100 (max stress) for all chain stores since there's no chain baseline to compare against. This inflates targeting scores.

### 4. BLS Adapter — Rate Limited

The BLS Public Data API has a 500-requests/day limit on v1 (no-key). I hit it during session while testing series IDs. The original series IDs in the config were wrong:
- `SMU48121007072200001` → does not exist
- `OEUM003112000000035302603` → does not exist

I found and verified these working IDs (already updated in `config/chains.yaml`):
- `SMU48124207072200001` — Austin Food Services & Drinking Places, All Employees
- `SMU48124207000000001` — Austin Leisure & Hospitality, All Employees
- `SMU48124207072000001` — Austin Accommodation & Food Services, All Employees
- `CEU7072200003` — National Food Services, Avg Hourly Earnings ($21.57/hr)
- `CEU7072200001` — National Food Services, All Employees

**Fix:** Just re-run `python scrapers/bls_adapter.py --region austin_tx` after the rate limit resets (next day).

### 5. Glassdoor Returns 400 in JobSpy

JobSpy's Glassdoor integration returns `400 - location not parsed` for all queries. This is a `python-jobspy` library issue, not our code. Indeed works fine, so data collection isn't blocked.

### 6. Google Maps Reviews Adapter — Not Tested

`scrapers/reviews_adapter.py` is written and follows the spec (uses `google-maps-scraper` library) but was never run live. Lower priority since we have Reddit sentiment data.

---

## Important Bugs I Fixed Along the Way

### SQLAlchemy `metadata` Property Conflict

The `Signal` model originally had a `@property` called `metadata` to JSON-serialize a `_metadata_json` text column. This collided with SQLAlchemy's `Base.metadata` (table metadata object), causing:
```
AttributeError: 'property' object has no attribute 'schema'
```

**Fix:** Renamed to `get_metadata()` / `set_metadata()` methods. Same for `Snapshot.summary` → `get_summary()` / `set_summary()`. Updated all callers in `ingest.py` and `scoring/engine.py`.

### Flask Debug Reloader Starts Duplicate Scheduler

With `debug=True`, Flask's reloader forks the process, causing APScheduler to start twice and fight over jobs.

**Fix:** Added `use_reloader=False` to `app.run()`.

### Extra Parenthesis in `scheduler.py`

A typo `logger.info(...)()` had an extra `()` calling the return value of `logger.info`. Fixed.

### Wage Location Matching

The scoring engine's `_get_local_avg_wage()` used `region.replace("_", " ")` → `"austin tx"` which didn't match wage_index locations like `"Austin, TX, US"`.

**Fix:** Extract state abbreviation from region key and use `ILIKE %TX%` to match all MSA cities (Round Rock, Cedar Park, Pflugerville, etc.).

---

## How to Run It

```bash
cd /home/fortune/CodeProjects/First-Helios
source .venv/bin/activate

# Start server (already has data from my session)
python server.py --debug

# Re-scrape fresh data
python scrapers/jobspy_adapter.py --chain starbucks --region austin_tx --mode chain
python scrapers/jobspy_adapter.py --industry coffee_cafe --region austin_tx --mode wage
python scrapers/reddit_adapter.py --region austin_tx

# Re-score after scraping
python3 -c "
import sys; sys.path.insert(0, '.')
from backend.scoring.engine import compute_all_scores
results = compute_all_scores('austin_tx', chain='starbucks')
print(f'Scored {len(results)} stores')
"

# Check API
curl -s http://localhost:8765/api/scores?region=austin_tx | python3 -m json.tool
curl -s http://localhost:8765/api/targeting?industry=coffee_cafe&region=austin_tx&limit=5 | python3 -m json.tool
```

---

## What to Do Next (Priority Order)

1. **Implement geocoding** — Add Nominatim API calls to `scrapers/geocoding.py`. Without lat/lng, the map is useless and isolation/alternatives scores are meaningless. This is 20 lines of code and unblocks the entire frontend.

2. **Fix chain wage population** — When JobSpy finds a Starbucks listing with wage data, it should go into `wage_index` with `is_chain=True`. Currently wage gap is always 100% (max) because there's no chain baseline.

3. **Playwright for Workday** — If you want posting creation dates for age-decay scoring, use Playwright headless browser to render the Workday SPA. Would also give store-specific data (store numbers) that Indeed doesn't have.

4. **BLS live verification** — Run the BLS adapter after the rate limit resets. Five verified series IDs are already in config.

5. **Test Google Maps reviews adapter** — Run `python scrapers/reviews_adapter.py --chain starbucks --region austin_tx` and see if it produces data.

6. **Frontend testing** — Open `http://localhost:8765` in a browser. The Leaflet map is there but markers won't show without geocoded coordinates.

7. **Write tests** — No `tests/` directory exists yet. The scoring engine and ingestion pipeline are the most critical to test.

---

## Things to NOT Touch

Per the AGENT.md spec:
- `data/spiritpool.db` — never write to it
- `spiritpool/` directory — on hiatus
- Flask port — stays 8765
- Legacy CLI — `python scraper/scrape.py --location "Austin, TX, US"` must keep working
- Frontend CSS/JS — don't modify (though I created them from scratch, so this rule applies going forward)
- No custom Indeed/Glassdoor scrapers — JobSpy handles it
- No ML/NLP — keyword matching only for v1
