# RUNBOOK — First-Helios

How to start the server, run scrapers, and troubleshoot.

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
            "psycopg[binary]" python-dotenv

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

# Yelp reviews (future)
export YELP_API_KEY="your_key"

# BLS API v2 (higher limits)
export BLS_API_KEY="your_key"
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
```

## Start the Server

```bash
python server.py --debug
# Runs on http://localhost:8765
```

The server will:
1. Connect to PostgreSQL (helios DB) and create any missing tables
2. Start the APScheduler background jobs
3. Serve the Leaflet map frontend at `/`
4. Expose all API endpoints

## Run Individual Scrapers

```bash
# Starbucks Careers API
python scrapers/careers_api.py --region austin_tx

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

## Check Database

```bash
psql -d helios -c "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename;"
```

Row count check:
```bash
psql -d helios -c "
SELECT 'chain_locations' AS tbl, COUNT(*) FROM chain_locations
UNION ALL SELECT 'local_employers', COUNT(*) FROM local_employers
UNION ALL SELECT 'brand_groups', COUNT(*) FROM brand_groups
UNION ALL SELECT 'mob_occupation', COUNT(*) FROM mob_occupation
UNION ALL SELECT 'mob_transition', COUNT(*) FROM mob_transition
UNION ALL SELECT 'ref_occupation_aliases', COUNT(*) FROM ref_occupation_aliases
UNION ALL SELECT 'oews_data', COUNT(*) FROM oews_data;
"
```

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/scan/status` | Last scrape metadata |
| POST | `/api/scan` | Trigger scrape `{chain, region}` |
| GET | `/api/scores?region=austin_tx` | All store scores |
| GET | `/api/targeting?industry=coffee_cafe&region=austin_tx&limit=10` | Ranked targets |
| GET | `/api/wage-index?industry=coffee_cafe&region=austin_tx` | Wage comparison |
| GET | `/api/map-employers?region=austin_tx` | Unified chain + local employer map data |
| GET | `/api/ref/summary?region=austin_tx` | Chains + industries for filter dropdowns |
| GET | `/api/scheduler/status` | Scheduler job status |
| GET | `/api/mobility/occupations` | All 781 SOC occupations (for Pathfinder autocomplete) |
| GET | `/api/mobility/paths?soc=35-3023&wage_filter=up&limit=15` | Career transition recommendations |
| GET | `/api/mobility/employers?soc=35-3023&lat=30.27&lng=-97.74&radius=30` | Nearby employers for dest SOC |

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

### Pathfinder shows no results
- Verify `mob_occupation` and `mob_transition` are populated (should be 781 and 256,831 rows)
- Run `python scripts/populate_mobility_data.py` if tables are empty
- Check that `ref_occupation_aliases` is populated for autocomplete to work

### 87% critical scores
- This is the bug the scoring model fixes. If you see this, the age decay
  and baseline-relative scoring aren't working. Check `backend/scoring/careers.py`.

### JobSpy returns no results
- JobSpy rate limits aggressively. Wait 5 minutes and retry.
- Check the search terms match actual job titles in the region.

### Reddit returns no results
- Without API credentials, falls back to public JSON API (lower limits).
- Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` for better results.
