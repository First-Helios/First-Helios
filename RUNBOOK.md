# RUNBOOK — First Helios

How to start the server, run scrapers, understand the scheduler, and troubleshoot.

---

## Prerequisites

```bash
# Python 3.11+
python3 --version

# PostgreSQL must be installed and running
psql --version
# Create the database if it doesn't exist:
createdb helios

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate
```

## Install Dependencies

```bash
pip install flask flask-sqlalchemy flask-cors requests tqdm playwright \
            pyyaml apscheduler python-jobspy praw pandas pyreadstat \
            "psycopg[binary]" python-dotenv h3 pyap python-dateutil

# For Google Maps scraping (optional - graceful degradation if missing)
pip install google-maps-scraper
playwright install firefox
playwright install chromium --with-deps
```

## Environment Variables

```bash
# Copy the template and fill in your values
cp .env.example .env
```

Required:
```bash
DATABASE_URL=postgresql://user:pass@localhost:5432/helios
```

Optional (for higher rate limits / additional scrapers):
```bash
# Higher Reddit rate limits
export REDDIT_CLIENT_ID="your_id"
export REDDIT_CLIENT_SECRET="your_secret"

# BLS API v2 (50 series per call vs 25 for v1)
export BLS_API_KEY="your_key"

# Jobicy file cache TTL override (default: 30 days)
export POSTING_TTL_DAYS=30

# Yelp reviews (future)
export YELP_API_KEY="your_key"
```

## Populate Data (run in order)

Expected row counts shown in parentheses.

```bash
# 1. Reference data — brands, regions, categories, industry taxonomy
python scripts/populate_reference_data.py
python scripts/populate_industry_taxonomy.py       # ref_industry_taxonomy (20 rows)

# 2. Mobility graph — Career Pathfinder data
python scripts/populate_mobility_data.py           # mob_occupation (781), mob_transition (256,831)
python scripts/load_occupation_aliases.py          # ref_occupation_aliases (18,981)

# 3. Employer POI data — local employers + chain locations
#    Download Overture data first (requires overturemaps CLI):
overturemaps download \
  --bbox=-98.0,30.1,-97.4,30.55 \
  -f geojson \
  --type=place \
  -o data/reference/overture/overture_austin_places.geojson

#    Then ingest:
python scrapers/overture_adapter.py --local-file data/reference/overture/overture_austin_places.geojson
#    Result: ~45,618 local_employers, ~36,563 brand_groups

# 4. Post-processing
python scripts/classify_local_employers.py         # backfills location_count + purges chain-like records

# 5. (Optional) Seed remote job postings from Jobicy
python scrapers/jobicy_adapter.py                  # ~100 remote jobs; respects hourly rate gate
```

## Start the Server

```bash
python server.py --debug
# Runs on http://localhost:8765
```

The server will:
1. Connect to PostgreSQL (helios DB) and create any missing tables
2. Seed `api_sources` registry (17 external sources) in rate_manager
3. Start the APScheduler background jobs (17 scheduled jobs)
4. Serve the Leaflet map frontend at `/`
5. Expose all API endpoints

## Run Individual Scrapers

```bash
# Jobicy remote jobs (respects 1hr rate gate + file cache)
python scrapers/jobicy_adapter.py

# USAJobs federal listings (requires USAJOBS_API_KEY + USAJOBS_EMAIL in .env)
python scrapers/usajobs_adapter.py --location "Austin, TX" --max-pages 2

# City of Austin Workday portal (dry run — prints results without DB write)
python scrapers/workday_gov_adapter.py --dry-run

# Job boards via JobSpy (chain mode — find chain repostings)
python scrapers/jobspy_adapter.py --chain starbucks --region austin_tx --mode chain

# Job boards via JobSpy (wage mode — find local employer wages)
python scrapers/jobspy_adapter.py --industry coffee_cafe --region austin_tx --mode wage

# Reddit sentiment
python scrapers/reddit_adapter.py --region austin_tx

# Google Maps reviews
python scrapers/reviews_adapter.py --chain starbucks --region austin_tx

# BLS wage baseline
python scrapers/bls_adapter.py --region austin_tx
```

---

## Scheduler

The background scheduler (`backend/scheduler.py`) uses APScheduler and runs inside the Flask process. Schedule configuration lives in `config/scheduler.yaml` — edit that file to change times or disable jobs without touching code. The scheduler starts automatically when `server.py` starts.

Check status via API: `GET /api/scheduler/status` — returns next run time for each job.

To disable a job without deleting it, set `enabled: false` in `config/scheduler.yaml`.

### Schedule Table

**Job Postings**

| Job ID | Trigger | Default Schedule | What It Does |
|--------|---------|-----------------|--------------|
| `jobspy` | cron | Daily 4:00 AM | Scrapes Indeed/Glassdoor for chain job postings + local wage data; recomputes all scores |
| `reddit` | interval | Every 6 hours | Fetches r/Austin + chain subreddits for worker sentiment signals; recomputes scores |
| `austin_gov` | cron | Daily 5:30 AM | City of Austin Workday portal — all active municipal postings with salary parsing |
| `usajobs` | cron | Daily 6:00 AM | USAJobs federal listings — Austin TX location filter, up to 1000 results/day |

**Labor Market / Regulatory Data**

| Job ID | Trigger | Default Schedule | What It Does |
|--------|---------|-----------------|--------------|
| `bls` | cron | Monday 6:00 AM | Fetches BLS time-series data (v2 batch if BLS_API_KEY set, else v1 per-series) |
| `qcew` | cron | 1st of month 7:00 AM | County employment + wages; **skips unless month ∈ {Jan, Apr, Jul, Oct}** (quarterly release) |
| `cbp` | cron | Monday 8:00 AM | ZIP-level establishment counts; **skips unless month = April** (annual release) |
| `nlrb` | cron | Wednesday 7:00 AM | Fetches NLRB labor relations cases for tracked chains; recomputes scores if new signals |
| `warn_tx` | cron | Tuesday 7:00 AM | Fetches Texas Workforce Commission WARN Act mass-layoff filings |
| `baseline_recompute` | cron | Sunday 4:00 AM | Recomputes labor market baselines from QCEW + JOLTS + OEWS + LAUS |

**Store / Employer Discovery (Sunday stagger)**

| Job ID | Trigger | Default Schedule | What It Does |
|--------|---------|-----------------|--------------|
| `atp_starbucks_austin` | cron | Sunday 2:00 AM | Downloads AllThePlaces GeoJSON for Starbucks, Dutch Bros, McDonald's in Austin |
| `overture_starbucks_austin` | cron | Sunday 2:15 AM | Cross-validates chain locations against Overture Maps data |
| `osm_starbucks_austin` | cron | Sunday 2:30 AM | OSM Overpass fallback for chain store locations |
| `overture_local_austin` | cron | Sunday 3:00 AM | Refreshes local employer POIs from Overture Maps |

**Maintenance**

| Job ID | Trigger | Default Schedule | What It Does |
|--------|---------|-----------------|--------------|
| `google_maps` | cron | Monday 5:00 AM | Scrapes ratings + reviews for tracked chain locations; recomputes scores |
| `posting_expiry` | cron | Daily 3:00 AM | Marks job postings `is_active=False` when `expires_at` has passed |
| `posting_purge` | cron | Sunday 3:30 AM | Hard-deletes job postings older than `POSTING_PURGE_DAYS` (default 90) |

### Scheduler Design Notes

- **Config file** — `config/scheduler.yaml` is the single source for all schedules. Hardcoded defaults in `scheduler.py` are fallbacks only; the YAML always wins.
- **Enabled flag** — each job has `enabled: true/false`. Set false to pause a job without removing code.
- **Daemon threads** — the scheduler runs as a daemon, so it exits cleanly when the Flask process exits.
- **Skip guards** — QCEW only runs in Jan/Apr/Jul/Oct; CBP only runs in April. Running outside those months is a no-op with a log message.
- **Score recompute** — JobSpy, Reddit, Reviews, and NLRB all call `compute_all_scores(region)` after ingesting signals so scores stay fresh.
- **Store discovery stagger** — AllThePlaces (2:00), Overture chain (2:15), OSM (2:30), Overture local (3:00) run sequentially on Sunday mornings to avoid hitting multiple APIs simultaneously.
- **BLS dual path** — with `BLS_API_KEY`, the scheduler uses the bulk POST endpoint (50 series/call); without it, falls back to v1 GET per-series.
- **Careers API** — intentionally not scheduled. Direct website scraping was moved to `future_plans/web_scraping/`. Use JobSpy instead.

---

## Check Database

```bash
psql -d helios -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
```

Row count check:
```bash
psql -d helios -c "
SELECT 'chain_locations'      AS tbl, COUNT(*) FROM chain_locations
UNION ALL SELECT 'local_employers',   COUNT(*) FROM local_employers
UNION ALL SELECT 'brand_groups',      COUNT(*) FROM brand_groups
UNION ALL SELECT 'job_postings',      COUNT(*) FROM job_postings
UNION ALL SELECT 'mob_occupation',    COUNT(*) FROM mob_occupation
UNION ALL SELECT 'mob_transition',    COUNT(*) FROM mob_transition
UNION ALL SELECT 'ref_occupation_aliases', COUNT(*) FROM ref_occupation_aliases
UNION ALL SELECT 'oews_data',         COUNT(*) FROM oews_data
UNION ALL SELECT 'api_sources',       COUNT(*) FROM api_sources;
"
```

Active job postings by source:
```bash
psql -d helios -c "
SELECT source, is_remote, COUNT(*)
FROM job_postings
WHERE is_active = true
GROUP BY source, is_remote
ORDER BY source;
"
```

---

## API Endpoints

### Map Data
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/map-employers?region=austin_tx` | Unified chain + local employer map data |
| GET | `/api/map-employers?region=austin_tx&h3_cell=<id>&resolution=<n>` | Employers in one H3 hex cell |
| GET | `/api/ref/summary?region=austin_tx` | Chains + industries for filter dropdowns |

### Job Finder
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/jobs/h3-map?region=austin_tx&resolution=7&mode=local` | H3 hex aggregates; mode=local/remote/all |
| GET | `/api/jobs/listings?region=austin_tx&mode=remote&page=1` | Paginated job listing cards |
| GET | `/api/jobs/listings?region=austin_tx&h3_cell=<id>&resolution=7` | Jobs within a specific hex cell |
| GET | `/api/jobs/categories?region=austin_tx` | Job categories with counts |

### Scoring & Targeting
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/scan/status` | Last scrape metadata |
| POST | `/api/scan` | Trigger scrape `{chain, region}` |
| GET | `/api/scores?region=austin_tx` | All store scores |
| GET | `/api/targeting?industry=coffee_cafe&region=austin_tx&limit=10` | Ranked targets |
| GET | `/api/wage-index?industry=coffee_cafe&region=austin_tx` | Wage comparison |

### Career Pathfinder
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/mobility/occupations` | All 781 SOC occupations (for autocomplete) |
| GET | `/api/mobility/paths?soc=35-3023&wage_filter=up&limit=15` | Career transition recommendations |
| GET | `/api/mobility/employers?soc=35-3023&lat=30.27&lng=-97.74&radius=30` | Nearby employers for dest SOC |

### Operations
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/scheduler/status` | Scheduler job status + next run times |
| GET | `/api/rate-budget` | API quota usage (all 17 sources) |

---

## Rate Manager

`backend/rate_manager.py` is a singleton (`rate_manager`) that every scraper uses before and after each external call.

Usage pattern:
```python
from backend.rate_manager import rate_manager

if rate_manager.can_request("jobicy"):
    t0 = time.time()
    resp = requests.get(url)
    rate_manager.log_request(
        source_key="jobicy",
        request_type="remote_jobs_feed",
        url=url,
        status_code=resp.status_code,
        success=resp.ok,
        latency_ms=int((time.time() - t0) * 1000),
        data_items=len(jobs),
    )
```

Registered sources and their daily limits:

| Source Key | Daily Limit | Notes |
|-----------|------------|-------|
| `bls_v1` | 500 | Shared with `bls_v1_post` |
| `careers_workday` | 10,000 | No known hard cap |
| `nominatim` | 10,000 | Hard limit 1 req/sec |
| `overpass_api` | 10,000 | Fair-use global cap |
| `atp_geojson` | 10,000 | Static file, no limit |
| `overture_s3` | 10,000 | Public S3, no limit |
| `jobspy` | 50 | Aggressive job board rate limits |
| `jobicy` | 24 | Once per hour per ToS; hourly gate in `jobicy_adapter.py` |
| `reddit_json` | 100 | No-auth fallback |
| `reddit_oauth` | 1,000 | Requires REDDIT_CLIENT_ID + SECRET |
| `gmaps_scraper` | 10,000 | Via google-maps-scraper library |
| `wikidata_sparql` | 10,000 | CC-0, soft limit via query timeout |

View live usage: `GET /api/rate-budget`

---

## Jobicy Cache

The Jobicy adapter (`scrapers/jobicy_adapter.py`) enforces a 60-minute minimum interval between API calls. The last successful response is cached to `data/jobicy_cache.json`:

```json
{"fetched_at": "2026-03-27T14:00:00+00:00", "jobs": [...]}
```

If the cache is younger than 60 minutes, the adapter skips the API call entirely and reprocesses the cached jobs list. This check runs before rate-manager and budget checks. To force a fresh fetch, delete `data/jobicy_cache.json`.

---

## Job Postings TTL

Job postings in `job_postings` expire automatically:

- **Default TTL:** 30 days (configurable via `POSTING_TTL_DAYS` env var)
- **`expires_at`** is set at ingest to `posted_date + TTL_DAYS`
- **Re-scraping** a listing that's still in the feed rolls `expires_at` forward to `now + TTL_DAYS`
- **Listings that disappear** from the feed stop getting refreshed and naturally expire
- **Nightly sweep** (future scheduler job) calls `listings.ingest.expire_stale_postings()` to flip `is_active = False` — rows are not deleted, just deactivated

To run the expiry sweep manually:
```python
from listings.ingest import expire_stale_postings
from backend.database import get_session, init_db
engine = init_db()
session = get_session(engine)
count = expire_stale_postings("austin_tx", session)
print(f"Expired {count} stale postings")
session.close()
```

---

## Troubleshooting

### Server won't start
- Check Python version: `python3 --version` (need 3.11+)
- Check venv is activated: `which python` should show `.venv/bin/python`
- Check port 8765 is free: `lsof -i :8765`
- Check PostgreSQL is running: `pg_isready -d helios`
- Check `DATABASE_URL` is set in `.env`

### No data after scraping
- Check PostgreSQL tables exist: `psql -d helios -c "\dt"`
- Run a scraper with `--no-ingest` to test scraping without DB writes
- Check scraper logs for API errors

### Job Finder shows no jobs
- Check `job_postings` table has active rows: `SELECT COUNT(*) FROM job_postings WHERE is_active = true`
- Run `python scrapers/jobicy_adapter.py` to ingest remote jobs
- Verify H3 cells: remote Jobicy jobs have NULL `h3_r7`/`h3_r8` — they appear only in Remote/All mode sidebar, not on the hex map
- For local jobs to appear on the hex map, `h3_r7`/`h3_r8` must be non-NULL (requires lat/lng at ingest)

### Jobicy cache is stale
- Delete `data/jobicy_cache.json` to force a fresh API call on next run
- The cache file location: `data/jobicy_cache.json` relative to project root

### Pathfinder shows no results
- Verify `mob_occupation` and `mob_transition` are populated (should be 781 and 256,831 rows)
- Run `python scripts/populate_mobility_data.py` if tables are empty
- Check that `ref_occupation_aliases` is populated for autocomplete to work

### Rate budget exhausted
- Check `/api/rate-budget` to see which source is at limit
- JobSpy: wait 24 hours for reset; set `--no-ingest` flag to test without counting against budget
- Jobicy: wait for the hourly gate to pass, or delete the cache file

### Scheduler jobs not running
- Check `GET /api/scheduler/status` — look for `"running": true` and next run times
- QCEW and CBP have built-in skip guards — they only run in specific months, this is expected
- Check server logs for `[Scheduler]` lines at startup to confirm jobs were registered

### 87% critical scores
- This is the bug the scoring model fixes. If you see this, the age decay
  and baseline-relative scoring aren't working. Check `backend/scoring/careers.py`.

### JobSpy returns no results
- JobSpy rate limits aggressively. Wait 5 minutes and retry.
- Check the search terms match actual job titles in the region.

### Reddit returns no results
- Without API credentials, falls back to public JSON API (lower limits).
- Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` for better results.
