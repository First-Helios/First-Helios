# RUNBOOK — ChainStaffingTracker

How to start the server, run scrapers, and troubleshoot.

---

## Prerequisites

```bash
# Python 3.11+
python3 --version

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate
```

## Install Dependencies

```bash
pip install flask flask-sqlalchemy flask-cors requests tqdm playwright \
            pyyaml apscheduler python-jobspy praw pandas

# For Google Maps scraping (optional - graceful degradation if missing)
pip install google-maps-scraper
playwright install firefox
playwright install chromium --with-deps
```

## Environment Variables (Optional)

```bash
# Higher Reddit rate limits
export REDDIT_CLIENT_ID="your_id"
export REDDIT_CLIENT_SECRET="your_secret"

# Yelp reviews (future)
export YELP_API_KEY="your_key"

# BLS API v2 (higher limits)
export BLS_API_KEY="your_key"
```

## Start the Server

```bash
python server.py --debug
# Runs on http://localhost:8765
```

The server will:
1. Auto-create `data/tracker.db` with all tables
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

## Legacy Scraper CLI (Preserved)

```bash
python scraper/scrape.py --location "Austin, TX, US" --radius 25
```

## Check Database

Download data 
overturemaps download \
  --bbox=-98.0,30.1,-97.4,30.55 \
  -f geojson \
  --type=place \
  -o data/overture_austin_places.geojson

  

```bash
python3 -c "
import sqlite3; conn = sqlite3.connect('data/tracker.db')
for t in ['stores','signals','snapshots','scores','wage_index']:
    print(t, conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0])
conn.close()
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
| GET | `/api/scheduler/status` | Scheduler job status |
| GET | `/api/spiritpool/stats` | Legacy SpiritPool stats |

## Troubleshooting

### Server won't start
- Check Python version: `python3 --version` (need 3.11+)
- Check venv is activated: `which python` should show `.venv/bin/python`
- Check port 8765 is free: `lsof -i :8765`

### No data after scraping
- Check `data/tracker.db` exists and has tables
- Run a scraper with `--no-ingest` to test scraping without DB writes
- Check scraper logs for API errors

### 87% critical scores
- This is the bug the scoring model fixes. If you see this, the age decay
  and baseline-relative scoring aren't working. Check `backend/scoring/careers.py`.

### JobSpy returns no results
- JobSpy rate limits aggressively. Wait 5 minutes and retry.
- Check the search terms match actual job titles in the region.

### Reddit returns no results
- Without API credentials, falls back to public JSON API (lower limits).
- Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` for better results.
