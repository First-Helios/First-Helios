# RUNBOOK — First-Helios

Operational procedures for the First-Helios platform: starting the server, running the OpenClaw agent, using the discovery engine, managing scrapers, and troubleshooting.

---

## Table of Contents

1. [Prerequisites](#prerequisites)
2. [Install Dependencies](#install-dependencies)
3. [Environment Variables](#environment-variables)
4. [Seed Reference Data](#seed-reference-data)
5. [Start the Server](#start-the-server)
6. [OpenClaw Agent](#openclaw-agent)
7. [Discovery Engine](#discovery-engine)
8. [Run Individual Scrapers](#run-individual-scrapers)
9. [Rate Budget Management](#rate-budget-management)
10. [Database Operations](#database-operations)
11. [Scheduler](#scheduler)
12. [API Quick Reference](#api-quick-reference)
13. [Troubleshooting](#troubleshooting)

---

## Prerequisites

```bash
# Python 3.12+
python3 --version

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Ollama (required for OpenClaw agent)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b-instruct
```

---

## Install Dependencies

```bash
pip install flask flask-cors sqlalchemy requests tqdm pyyaml \
            apscheduler python-jobspy praw nltk pandas duckdb \
            playwright google-maps-scraper

# Browser automation (optional — graceful degradation if missing)
playwright install firefox
playwright install chromium --with-deps
```

---

## Environment Variables

```bash
# Higher Reddit rate limits (strongly recommended)
export REDDIT_CLIENT_ID="your_id"
export REDDIT_CLIENT_SECRET="your_secret"

# BLS API v2 (higher limits — 500/day default works without this)
export BLS_API_KEY="your_key"

# Yelp Fusion API (future)
export YELP_API_KEY="your_key"
```

---

## Seed Reference Data

Populates `ref_industry`, `ref_brands`, `ref_regions`, and `ref_category_map` tables with NAICS codes, brand profiles, and category mappings for all 13 industries and 49 mega-corps.

```bash
# Seed everything
python scripts/populate_reference_data.py --all

# Or seed individual sections
python scripts/populate_reference_data.py --industries
python scripts/populate_reference_data.py --brands
python scripts/populate_reference_data.py --regions
python scripts/populate_reference_data.py --categories
```

**Re-run after adding new industries or brands.** The script is idempotent — it upserts, not duplicates.

---

## Start the Server

```bash
python server.py --debug
# → http://localhost:8765           (Leaflet map SPA)
# → http://localhost:8765/openclaw  (OpenClaw agent dashboard)
```

The server will:
1. Auto-create `data/tracker.db` with all 14 tables
2. Start APScheduler with 10 background jobs
3. Serve both frontends via Flask static routes
4. Expose 46 API endpoints

### Background mode

```bash
# Start in background
python server.py --debug &

# Stop
pkill -f "python server.py"
```

---

## OpenClaw Agent

OpenClaw is the LLM-driven research planning agent. It connects to Ollama locally and orchestrates data collection across all 13 industries.

### Check Ollama is ready

```bash
# Verify Ollama is running and model is available
curl -s http://localhost:11434/api/tags | python3 -c "
import json, sys
tags = json.load(sys.stdin)
models = [m['name'] for m in tags.get('models', [])]
print('Available models:', models)
assert any('qwen2.5' in m for m in models), 'qwen2.5:7b-instruct not found!'
print('OK')
"

# Or via the API
curl http://localhost:8765/api/agent/ollama/status
```

### Start an agent session

```bash
# Default: austin_tx, all industries
curl -X POST http://localhost:8765/api/openclaw/run \
  -H "Content-Type: application/json" \
  -d '{"region": "austin_tx", "goal": "initial data collection"}'

# Target specific industries
curl -X POST http://localhost:8765/api/openclaw/run \
  -H "Content-Type: application/json" \
  -d '{"region": "austin_tx", "goal": "explore hair_beauty and auto_repair industries"}'
```

### Watch a live session

Open `http://localhost:8765/openclaw/session` in browser for the terminal-style thought stream.

Or poll the API:

```bash
curl http://localhost:8765/api/openclaw/session/live
```

### Agent session flow

1. **Audit** — `data_quality_audit` runs first (checks DB coverage)
2. **Discovery** — `discovery_scan` finds coverage gaps and prioritised expansion targets
3. **Explore** — agent works through discovery leads: chain locations → local density → wages → jobs → sentiment
4. **Re-discover** — mid-session `discovery_scan` checks for newly exposed gaps
5. **Done** — session summary + wishlist reflection

### Check session results

```bash
# Today's request log (success/fail per intent)
curl http://localhost:8765/api/openclaw/tracker

# Today's wishlist (terms/brands the agent wanted but didn't have)
curl http://localhost:8765/api/openclaw/wishlist

# Source freshness (what's been collected and when)
curl http://localhost:8765/api/openclaw/freshness
```

### Pre-validate a query without executing

```bash
curl -X POST http://localhost:8765/api/openclaw/prevalidate \
  -H "Content-Type: application/json" \
  -d '{"queries": [
    {"intent": "poi_chain_locations", "brand": "great_clips", "industry": "hair_beauty",
     "search_terms": ["hair salon"], "region": "austin_tx"}
  ]}'
```

---

## Discovery Engine

The discovery engine analyses collected data to find where to expand next. It runs 5 strategies and returns prioritised leads that become agent proposals.

### Run a discovery scan

```bash
# Full scan — returns ranked leads
curl "http://localhost:8765/api/discovery/scan?region=austin_tx&max_leads=25"

# Quick dashboard stats (no full scan)
curl "http://localhost:8765/api/discovery/summary?region=austin_tx"

# Just the top leads as agent proposals
curl "http://localhost:8765/api/discovery/leads?region=austin_tx&min_priority=70&limit=10"
```

### Filter by strategy type

```bash
# Only coverage gaps and stale leads
curl "http://localhost:8765/api/discovery/scan?types=coverage_gaps,stale_leads"
```

Valid types: `coverage_gaps`, `data_dimension_gaps`, `stale_leads`, `geographic_clusters`, `local_opportunities`

### Run from Python

```python
from backend.discovery import run_discovery, get_discovery_summary

# Full scan
scan = run_discovery(region="austin_tx", max_leads=25)
for lead in scan.leads[:5]:
    print(f"[{lead.priority}] {lead.lead_type}: {lead.description}")
    # Convert to agent query format
    proposal = lead.to_agent_proposal()

# Quick stats
summary = get_discovery_summary(region="austin_tx")
print(summary["brand_coverage"])   # {'registered': 49, 'with_data': N, 'coverage_pct': X}
print(summary["scoring_coverage"]) # {'total_stores': N, 'scored_stores': N, 'coverage_pct': X}
```

### Discovery strategies

| Strategy | What it finds | Priority range |
|----------|--------------|----------------|
| `coverage_gaps` | Brands/industries with zero or thin store counts | 60–90 |
| `data_dimension_gaps` | Stores missing scores, wages, jobs, or sentiment | 50–80 |
| `stale_leads` | Freshness records past threshold + never-collected combos | 40–95 |
| `geographic_clusters` | Grid-based clusters of high-stress areas with missing industries | 55 |
| `local_opportunities` | Local employer density vs chain tracking gaps | 70–75 |

### Scheduled discovery

The scheduler runs a discovery scan daily at 1am. Results are logged for operator review:

```bash
# Check scheduler status to see next discovery run
curl http://localhost:8765/api/scheduler/status
```

---

## Run Individual Scrapers

### Chain locations (AllThePlaces)

```bash
python -c "
from scrapers.alltheplaces_adapter import AllThePlacesAdapter
from backend.ingest import ingest_signals
adapter = AllThePlacesAdapter()
adapter.chain = 'great_clips'
signals = adapter.scrape('austin_tx')
print(f'{len(signals)} signals')
ingest_signals(signals, region='austin_tx')
"
```

### Job postings (JobSpy)

```bash
# Chain mode — find chain repostings
python scrapers/jobspy_adapter.py --chain starbucks --region austin_tx --mode chain

# Wage mode — find local employer wages
python scrapers/jobspy_adapter.py --industry coffee_cafe --region austin_tx --mode wage
```

### Careers API (Workday)

```bash
python scrapers/careers_api.py --region austin_tx
```

### Reddit sentiment

```bash
python scrapers/reddit_adapter.py --region austin_tx
```

### BLS wage baseline

```bash
python scrapers/bls_adapter.py --region austin_tx
```

### Google Maps reviews (requires Playwright)

```bash
python scrapers/reviews_adapter.py --chain starbucks --region austin_tx
```

### Agent interface (structured query)

```bash
# Submit a single structured query via the agent API
curl -X POST http://localhost:8765/api/agent/query \
  -H "Content-Type: application/json" \
  -d '{"intent": "poi_chain_locations", "brand": "jiffy_lube",
       "industry": "auto_repair", "region": "austin_tx"}'

# Submit a batch
curl -X POST http://localhost:8765/api/agent/batch \
  -H "Content-Type: application/json" \
  -d '{"queries": [
    {"intent": "poi_chain_locations", "brand": "jiffy_lube", "region": "austin_tx"},
    {"intent": "wage_baseline", "industry": "auto_repair", "region": "austin_tx"}
  ]}'
```

---

## Rate Budget Management

Every external API call is tracked. The system blocks requests when daily limits are reached.

```bash
# Today's budget per source
curl http://localhost:8765/api/rate-budget

# Historical usage (last 7 days default)
curl "http://localhost:8765/api/rate-budget/history?days=14"

# Individual request log
curl "http://localhost:8765/api/rate-budget/log?source=jobspy&limit=20"

# Scalability projections
curl http://localhost:8765/api/rate-budget/scalability
```

### Daily limits

| Source | Daily Limit | Auth |
|--------|------------|------|
| `atp_geojson` | 10,000 | None |
| `overture_s3` | 10,000 | None |
| `bls_v1` | 500 | Optional key for v2 |
| `careers_workday` | 10,000 | None |
| `jobspy` | 50 | None |
| `reddit_json` | 100 | None |
| `reddit_oauth` | 1,000 | `REDDIT_CLIENT_ID` + `REDDIT_CLIENT_SECRET` |
| `nominatim` | 10,000 | None |

### Pause/resume agent execution

```bash
# Pause (stops agent from submitting new queries)
curl -X POST http://localhost:8765/api/agent/queue/pause \
  -H "Content-Type: application/json" \
  -d '{"reason": "JobSpy budget exhausted"}'

# Resume
curl -X POST http://localhost:8765/api/agent/queue/resume
```

---

## Database Operations

### Check table counts

```bash
python3 -c "
import sqlite3; conn = sqlite3.connect('data/tracker.db')
for t in ['stores','signals','snapshots','scores','wage_index','local_employers',
          'ref_industry','ref_brands','ref_regions','ref_category_map',
          'api_sources','api_request_log','rate_budgets','source_freshness']:
    try:
        n = conn.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]
        print(f'  {t:25s} {n:>6d}')
    except: print(f'  {t:25s}  (missing)')
conn.close()
"
```

### Reset freshness (force re-collection)

```bash
python3 -c "
import sqlite3; conn = sqlite3.connect('data/tracker.db')
# Reset all freshness — next agent session will re-collect everything
conn.execute('DELETE FROM source_freshness')
conn.commit(); print('Freshness reset'); conn.close()
"
```

### Reset specific freshness (re-collect one intent)

```bash
python3 -c "
import sqlite3; conn = sqlite3.connect('data/tracker.db')
conn.execute(\"DELETE FROM source_freshness WHERE intent_key = 'poi_chain_locations'\")
conn.commit(); print('POI freshness reset'); conn.close()
"
```

### Backfill geocoding for stores missing coordinates

```bash
python scripts/backfill_geocoding.py
```

---

## Scheduler

10 scheduled jobs run automatically when the server is up.

| Job ID | Schedule | What it does |
|--------|----------|-------------|
| `careers_api` | Daily 3am | Starbucks Workday careers scraper |
| `jobspy` | Daily 4am | Indeed/Glassdoor via python-jobspy |
| `reddit` | Every 6 hours | Reddit sentiment scraping |
| `google_maps` | Weekly Mon 5am | Google Maps reviews |
| `bls` | Weekly Mon 6am | BLS wage data |
| `atp_starbucks_austin` | Weekly Sun 2am | AllThePlaces store discovery |
| `overture_starbucks_austin` | Weekly Sun 2:15am | Overture chain cross-validation |
| `osm_starbucks_austin` | Weekly Sun 2:30am | OSM Overpass store fallback |
| `overture_local_austin` | Weekly Sun 3am | Overture local employer discovery |
| `discovery_scan` | Daily 1am | Discovery expansion scan (5 strategies) |

```bash
# Check next run times
curl http://localhost:8765/api/scheduler/status
```

---

## API Quick Reference

### Core Data
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/stores` | All chain stores (filterable by chain, region) |
| `GET` | `/api/local-employers` | Local non-chain employers |
| `GET` | `/api/scores` | Staffing scores for region |
| `GET` | `/api/targeting` | Ranked job fair candidates |
| `GET` | `/api/wage-index` | Local vs chain pay comparison |
| `POST` | `/api/scan` | Trigger manual scrape |
| `GET` | `/api/scan/status` | Last scrape metadata |

### Reference Data
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/ref/brands` | All 49 brand profiles |
| `GET` | `/api/ref/industries` | 13 industry categories |
| `GET` | `/api/ref/regions` | Region profiles |
| `GET` | `/api/ref/categories` | Category mappings |
| `GET` | `/api/ref/summary` | Reference data summary |

### Discovery
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/discovery/scan` | Full discovery scan (region, max_leads, types) |
| `GET` | `/api/discovery/summary` | Quick coverage dashboard |
| `GET` | `/api/discovery/leads` | Ranked leads as agent proposals |

### Rate Budget
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/rate-budget` | Today's budget per source |
| `GET` | `/api/rate-budget/history` | Historical budget usage |
| `GET` | `/api/rate-budget/log` | Individual request log |
| `GET` | `/api/rate-budget/scalability` | Scalability projections |

### Agent Interface
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/agent/options` | All valid enums + thresholds |
| `POST` | `/api/agent/query` | Submit single structured query |
| `POST` | `/api/agent/batch` | Submit batch of queries |
| `GET` | `/api/agent/queue/status` | Queue state |
| `POST` | `/api/agent/queue/pause` | Pause execution |
| `POST` | `/api/agent/queue/resume` | Resume execution |
| `GET` | `/api/agent/history` | Past query results |

### OpenClaw
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/openclaw/status` | Agent status |
| `GET` | `/api/openclaw/industries` | Industry registry |
| `POST` | `/api/openclaw/prevalidate` | Pre-validate query batch |
| `GET` | `/api/openclaw/tracker` | Today's request rollup |
| `GET` | `/api/openclaw/freshness` | Source freshness overview |
| `POST` | `/api/openclaw/freshness/check` | Check specific freshness |
| `GET` | `/api/openclaw/wishlist` | Today's wishlist |
| `POST` | `/api/openclaw/wishlist/review` | Mark wishlist items |
| `POST` | `/api/openclaw/run` | Start agent session |
| `GET` | `/api/openclaw/session/live` | Live thought stream |

---

## Troubleshooting

### Server won't start

- Check Python version: `python3 --version` (need 3.12+)
- Check venv is activated: `which python` should show `.venv/bin/python`
- Check port 8765 is free: `lsof -i :8765`
- Kill stale processes: `pkill -f "python server.py"`

### Ollama not responding

- Check Ollama is running: `curl http://localhost:11434/api/tags`
- Start Ollama: `ollama serve` (or `systemctl start ollama`)
- Pull the model: `ollama pull qwen2.5:7b-instruct`
- Check via API: `curl http://localhost:8765/api/agent/ollama/status`

### OpenClaw session not starting

- Check Ollama first (see above)
- Check server is running: `curl http://localhost:8765/api/openclaw/status`
- Check reference data is seeded: `curl http://localhost:8765/api/ref/summary`
- If ref data is empty: `python scripts/populate_reference_data.py --all`

### Discovery scan returns zero leads

- The DB is likely empty. Run an OpenClaw session first to collect initial data.
- Or seed reference data and the coverage_gaps strategy will identify all missing brands/industries.
- Check: `curl http://localhost:8765/api/discovery/summary`

### No data after scraping

- Check `data/tracker.db` exists and has tables (see Database Operations above)
- Check source freshness — the query may have been skipped as fresh: `curl http://localhost:8765/api/openclaw/freshness`
- Reset freshness if needed (see Database Operations)
- Check scraper logs for API errors

### Agent pre-validation rejects valid queries

- Verify the search term is in the industry's approved pool: `curl http://localhost:8765/api/openclaw/industries`
- Verify brand belongs to the specified industry: `curl http://localhost:8765/api/ref/brands`
- Cross-industry terms are rejected by design (e.g., "barista" in `retail_general`)
- If a term should be valid, add it via `openclaw/industries.py` and restart

### JobSpy returns no results

- JobSpy rate limits aggressively (50/day). Check budget: `curl http://localhost:8765/api/rate-budget`
- Wait for daily reset or check the search terms match actual job titles in the region

### Reddit returns no results

- Without API credentials, falls back to public JSON API (100/day limit)
- Set `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET` for 1,000/day via OAuth

### Scores are all the same or seem wrong

- Check that multiple data sources have been collected (careers + job boards + sentiment)
- If only one source has data, its weight gets redistributed — less signal diversity
- Verify scoring weights in `config/chains.yaml` under `scoring.weights`
- Force recompute: submit a `score_refresh` intent via the agent API

### Scheduler jobs not running

- Check scheduler status: `curl http://localhost:8765/api/scheduler/status`
- The scheduler only runs while the server process is up
- Jobs use UTC times — adjust expectations for your timezone
