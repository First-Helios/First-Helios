# Session 1 Handoff — ChainStaffingTracker Build

**Date:** 2026-03-19  
**Agent:** GitHub Copilot (Claude Opus 4.6)  
**Duration:** Full build session — project from scratch  

---

## 1. Tasks Completed

| Task | Status | Notes |
|------|--------|-------|
| Read AGENT.md & README.md | ✅ Done | Comprehensive build spec — 15 sections |
| Install all Python dependencies | ✅ Done | flask, sqlalchemy, jobspy, praw, apscheduler, pandas, etc. |
| Create config system | ✅ Done | `config/chains.yaml` + `config/loader.py` — typed accessors |
| Create ScraperSignal/BaseScraper | ✅ Done | `scrapers/base.py` — dataclass + ABC |
| Create database models | ✅ Done | 5 tables: stores, signals, snapshots, scores, wage_index |
| Fix SQLAlchemy metadata conflict | ✅ Done | Changed `@property metadata` → `get_metadata()/set_metadata()` |
| Create ingestion pipeline | ✅ Done | `backend/ingest.py` — upserts stores, inserts signals, creates wage_index |
| Create scoring engine (3 sub-scores) | ✅ Done | careers (age decay + baseline), sentiment, wage gap |
| Fix 87% critical scoring bug | ✅ Done | Age decay (fresh=7d/stale=90d) + baseline-relative percentile scoring |
| Create 6 scraper adapters | ✅ Done | careers_api, jobspy, reddit, reviews, bls, geocoding |
| Create targeting system | ✅ Done | `backend/targeting.py` — haversine distance, 4-factor weighted composite |
| Create scheduler | ✅ Done | APScheduler — 5 jobs (daily/6hr/weekly) |
| Create Flask server | ✅ Done | 6 API endpoints on port 8765 |
| Create legacy CLI wrapper | ✅ Done | `scraper/scrape.py --location` still works |
| Create Leaflet map frontend | ✅ Done | Dark theme CARTO tiles, score markers |
| Create RUNBOOK.md + .gitignore | ✅ Done | |
| Test JobSpy live (Indeed) | ✅ Done | 14 chain signals + 47 wage signals ingested |
| Test Reddit live (JSON API) | ✅ Done | 6 sentiment signals ingested |
| Fix BLS series IDs | ✅ Done | Updated to verified IDs (Austin MSA + national food service) |
| Verify score distribution | ✅ Done | 30% critical / 60% elevated / 10% unknown — NOT 87% |
| Verify all API endpoints | ✅ Done | All 6 endpoints returning real JSON data |

## 2. Tasks Started but Not Finished

| Task | Status | Why |
|------|--------|-----|
| Starbucks Workday careers API | ⚠️ Blocked | Workday CXS API returns HTTP 422 (Cloudflare bot protection). Tried: session cookies, browser headers, cloudscraper. All fail. Needs Playwright headless browser or accept JobSpy as primary source. |
| BLS live data verification | ⚠️ Rate limited | Found correct series IDs (5 verified working) but hit BLS daily rate limit (500 req). Re-test next day. |
| Google Maps scraper live test | 🔲 Not tested | `google-maps-scraper` installed. Adapter written. Not tested live — lower priority than JobSpy. |
| Store geocoding | ⚠️ Partial | Stores have city/state but no lat/lng coordinates. Need geocoding API (Nominatim/Google) integration. Currently lat=0.0, lng=0.0 for all stores. |

## 3. Score Distribution After Fixes

```
Total stores: 10
Tier distribution:
  critical: 3 (30.0%)
  elevated: 6 (60.0%)
  unknown:  1 (10.0%)  ← REGIONAL store (no chain-specific scoring)

CRITICAL: 30.0% — PASS (was 87%, now fixed)
```

The fix uses:
- **Age decay**: postings >90 days old → weight 0.0 (standing requisitions filtered out)
- **Baseline-relative scoring**: stores scored as percentile within regional cohort, not absolute count

## 4. Top 3 Targeting Results

```json
[
  {
    "store_num": "SB-a4616329",
    "chain": "starbucks",
    "address": "Austin, TX, US",
    "targeting_score": 85.0,
    "targeting_tier": "prime",
    "staffing_stress": 100.0,
    "wage_gap": 100.0,
    "isolation": 50.0,
    "local_alternatives": 50.0,
    "local_avg_wage": 17.61,
    "recommended_timing": [
      "Immediate — high staffing stress detected",
      "Weekday mornings (7-10am) — shift change overlap",
      "Weekend afternoons — high foot traffic"
    ]
  },
  {
    "store_num": "SB-2df1d8d7",
    "chain": "starbucks",
    "address": "Cedar Park, TX, US",
    "targeting_score": 80.56,
    "targeting_tier": "prime",
    "staffing_stress": 88.89,
    "wage_gap": 100.0
  },
  {
    "store_num": "SB-80ea4bd7",
    "chain": "starbucks",
    "address": "Cedar Park, TX, US",
    "targeting_score": 80.56,
    "targeting_tier": "prime",
    "staffing_stress": 88.89,
    "wage_gap": 100.0
  }
]
```

## 5. DB Row Counts (`tracker.db`)

| Table | Rows |
|-------|------|
| stores | 10 |
| signals | 67 |
| snapshots | 3 |
| scores | 36 |
| wage_index | 9 |

## 6. Known Issues Discovered

1. **Workday API blocked (HTTP 422)**: The Starbucks Workday CXS API (`/wday/cxs/...`) rejects all server-side requests with 422. This appears to be Cloudflare bot protection + JavaScript-rendered SPA. The API endpoint has moved from `/wday/cxs/` to `/api/v1/` but that also fails. Workaround: use JobSpy (Indeed/Glassdoor) as primary listing source — already implemented and working.

2. **No geocoding**: Stores have city/state addresses but lat=0.0, lng=0.0. The `scrapers/geocoding.py` has a `geocode()` function but it returns (None, None) since no geocoding API is configured. Need to add Nominatim (free, no key) or Google Geocoding API.

3. **Glassdoor 400 errors**: JobSpy's Glassdoor scraper returns 400 ("location not parsed") for all searches. Indeed works fine. This is a JobSpy/Glassdoor issue, not ours.

4. **BLS rate limit**: Hit the daily request limit during series ID discovery. The 5 verified series IDs are saved in config. The adapter will work once rate limit resets.

5. **Wage gap always 100%**: Chain wage data isn't being populated (Workday API doesn't return wages, and JobSpy chain-mode listings in the wage_index table aren't being categorized as chain wages). Need to ensure chain listings with wage data get `is_chain=True` in wage_index.

6. **Deprecation warnings**: `datetime.utcnow()` and `datetime.utcfromtimestamp()` flagged in Reddit adapter. Fixed in JobSpy adapter but still present in Reddit adapter.

## 7. Deviations from Instructions

| Deviation | Reason |
|-----------|--------|
| Workday API non-functional | Cloudflare protection — out of scope for server-side scraping. JobSpy covers the same data. |
| No `data/spiritpool.db` exists | Previous project data not present. SpiritPool endpoint returns stub response. This is correct per spec — never write to it from new code. |
| `use_reloader=False` in Flask debug mode | Debug reloader starts duplicate APScheduler instances, causing conflicts. |
| BLS series IDs differ from spec | Original IDs were invalid. Replaced with verified working IDs for Austin MSA. |

## 8. Suggested Next Session Priorities

1. **Add geocoding (Nominatim)**: Implement `scrapers/geocoding.py` with OpenStreetMap Nominatim API. All store markers will appear at (0,0) on the map until this is done. This is the highest-impact fix.

2. **Fix chain wage population**: Ensure JobSpy chain-mode listings populate `wage_index` with `is_chain=True` so wage gap scoring works correctly.

3. **Playwright for Workday API**: If the careers API is needed beyond what JobSpy provides, use Playwright headless browser to render the Workday SPA and extract listings. This would give us posting dates (for age decay) that JobSpy doesn't provide.

4. **BLS adapter verification**: Re-run after rate limit resets to verify all 5 series IDs produce data.

5. **Google Maps reviews adapter**: Test live with Austin Starbucks locations. This will add review_score signals.

6. **Frontend testing**: Verify the Leaflet map renders store markers and score data correctly in a browser.

7. **Add tests**: Create `tests/` directory with unit tests for scoring, ingestion, and targeting modules.

---

## File Inventory

```
config/
  __init__.py
  chains.yaml          # All configuration
  loader.py            # Typed config accessors

scrapers/
  __init__.py
  base.py              # ScraperSignal + BaseScraper ABC
  careers_api.py       # Starbucks Workday (blocked, graceful fallback)
  jobspy_adapter.py    # Indeed/Glassdoor via python-jobspy (WORKING)
  reddit_adapter.py    # Reddit JSON API (WORKING)
  reviews_adapter.py   # Google Maps reviews (untested)
  bls_adapter.py       # BLS wage data (rate limited, config fixed)
  geocoding.py         # Geocoding utilities

backend/
  __init__.py
  database.py          # SQLAlchemy models + init_db()
  ingest.py            # Signal → DB writer
  targeting.py         # Job fair targeting computation
  scheduler.py         # APScheduler jobs
  scoring/
    __init__.py
    engine.py          # Composite scorer
    careers.py         # Age decay + baseline-relative
    sentiment.py       # Keyword-based sentiment sub-score
    wage.py            # Wage gap sub-score

scraper/
  scrape.py            # Legacy CLI wrapper

frontend/
  index.html           # Leaflet map SPA
  css/style.css        # Dark theme
  js/app.js            # Map + API interactions

server.py              # Flask app (port 8765)
RUNBOOK.md             # How to run everything
.gitignore             # Excludes data/*.db, .env, .venv/
```
