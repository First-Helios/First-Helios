# First-Helios

A public data intelligence platform that detects real staffing stress at chain employer locations — and surfaces where community job fairs will have maximum labor market impact. An AI research agent (OpenClaw) orchestrates data collection across 13 industries and 49 mega-corps using local LLMs via Ollama.

**Current focus:** Austin, TX. One city, done right, before scaling.

**What it produces:** A ranked list of chain store locations where local independent employers can show up with a permitted booth, a hiring sign, and a job offer — timed to when workers at that location have the most leverage.

---

## Architecture Overview

The system has four distinct layers. Issues in one layer rarely leak into another. When debugging, identify which layer you're in first.

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LAYER 4: FRONTENDS                                                     │
│  frontend/index.html         — Leaflet map SPA (dark theme)            │
│  frontend/openclaw.html      — OpenClaw dashboard (KPIs, charts, feed) │
│  frontend/session.html       — Live session viewer (terminal-style)    │
│  Port 8765 — all served by Flask static routes                         │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ HTTP (46 endpoints)
┌────────────────────────────────▼────────────────────────────────────────┐
│  LAYER 3: SERVER + AGENT ORCHESTRATION                                  │
│                                                                         │
│  server.py (1400 lines)                                                │
│    ├── /api/scores, /api/targeting, /api/stores      (core data)       │
│    ├── /api/agent/*                                  (agent interface)  │
│    ├── /api/openclaw/*                               (OpenClaw)        │
│    ├── /api/discovery/*                              (discovery engine) │
│    └── /api/rate-budget/*                            (budget tracking)  │
│                                                                         │
│  openclaw/                          agent_interface/                    │
│    orchestrator.py  ← LLM loop       schemas.py     ← enums, types    │
│    prevalidate.py   ← safety gate     executor.py    ← intent dispatch │
│    tracker.py       ← request log     validator.py   ← query checks    │
│    wishlist.py      ← gap tracking    queue_manager  ← pause/resume    │
│    industries.py    ← 13 industries   ollama_agent   ← HTTP to Ollama  │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ Python function calls
┌────────────────────────────────▼────────────────────────────────────────┐
│  LAYER 2: BACKEND (scoring, ingestion, scheduling)                      │
│                                                                         │
│  backend/database.py     — 14 SQLAlchemy models (tracker.db)           │
│  backend/ingest.py       — ScraperSignal → DB writer                   │
│  backend/rate_manager.py — API budget tracking + enforcement           │
│  backend/discovery.py    — Discovery engine (5 expansion strategies)   │
│  backend/scheduler.py    — APScheduler (10 scheduled jobs)             │
│  backend/scoring/        — Composite scoring engine                     │
│    engine.py             — Multi-source weighted scores                │
│    careers.py            — Age-decay + baseline-relative scoring        │
│    sentiment.py          — Reddit + review sentiment sub-score         │
│    wage.py               — Local vs chain wage gap sub-score           │
│  backend/targeting.py    — Job fair site ranking                        │
│  backend/models/reference.py — ref_industry, ref_brands, ref_regions   │
└────────────────────────────────┬────────────────────────────────────────┘
                                 │ HTTP / file reads / SQL
┌────────────────────────────────▼────────────────────────────────────────┐
│  LAYER 1: DATA SOURCES (scrapers + adapters)                            │
│                                                                         │
│  scrapers/                                                              │
│    alltheplaces_adapter.py   — GeoJSON/Parquet chain locations  [LIVE] │
│    overture_adapter.py       — DuckDB S3 Parquet for POI        [LIVE] │
│    osm_adapter.py            — Overpass QL queries               [LIVE] │
│    bls_adapter.py            — BLS API v1 wage time series      [LIVE] │
│    careers_api.py            — Starbucks Workday JSON API       [LIVE] │
│    jobspy_adapter.py         — Indeed/Glassdoor via python-jobspy[LIVE]│
│    reddit_adapter.py         — Reddit JSON + PRAW               [LIVE] │
│    reviews_adapter.py        — Google Maps via Playwright      [UNWIRED]│
│    playwright_fallback.py    — Headless Chromium fallback      [UNWIRED]│
│    geocoding.py              — Nominatim                        [LIVE] │
│                                                                         │
│  External: Ollama (localhost:11434) — qwen2.5:7b-instruct             │
│  External: SQLite (data/tracker.db) — 14 tables                        │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Repository Structure

```
First-Helios/
├── server.py                      ← Flask app (port 8765), 46 API routes
│
├── openclaw/                      ← AI research agent orchestration
│   ├── orchestrator.py            ← Main LLM loop (max 12 iterations)
│   ├── prevalidate.py             ← 4-level safety gate (freshness, terms, geo, budget)
│   ├── tracker.py                 ← Per-request success/fail logging (JSON)
│   ├── wishlist.py                ← Daily gap tracking (5 categories)
│   └── industries.py             ← 13 industries, 49 mega-corps, term pools
│
├── agent_interface/               ← Structured query layer between LLM and backend
│   ├── schemas.py                 ← Enums, dataclasses, freshness thresholds
│   ├── executor.py                ← Intent → scraper dispatch (10 handlers)
│   ├── validator.py               ← Query validation against schemas
│   ├── queue_manager.py           ← Execution queue with pause/resume
│   └── ollama_agent.py            ← HTTP client to Ollama API
│
├── backend/                       ← Core database, scoring, scheduling
│   ├── database.py                ← 14 SQLAlchemy models + freshness helpers
│   ├── ingest.py                  ← ScraperSignal → DB writer
│   ├── rate_manager.py            ← API budget tracking + enforcement
│   ├── discovery.py               ← Discovery engine (5 expansion strategies)
│   ├── scheduler.py               ← APScheduler job definitions (10 jobs)
│   ├── targeting.py               ← Job fair site ranking algorithm
│   ├── scoring/
│   │   ├── engine.py              ← Composite score (multi-source weighted)
│   │   ├── careers.py             ← Age-decay + baseline-relative scoring
│   │   ├── sentiment.py           ← Sentiment sub-score
│   │   └── wage.py                ← Wage gap sub-score
│   └── models/
│       └── reference.py           ← ref_industry, ref_brands, ref_regions, ref_category_map
│
├── scrapers/                      ← Data source adapters
│   ├── base.py                    ← BaseScraper + ScraperSignal dataclass
│   ├── alltheplaces_adapter.py    ← Chain location GeoJSON/Parquet
│   ├── overture_adapter.py        ← Overture Maps S3 (chain + local POI)
│   ├── osm_adapter.py             ← OpenStreetMap Overpass queries
│   ├── bls_adapter.py             ← BLS wage/employment series
│   ├── careers_api.py             ← Starbucks Workday JSON API
│   ├── jobspy_adapter.py          ← Indeed/Glassdoor via python-jobspy
│   ├── reddit_adapter.py          ← Reddit public JSON + PRAW OAuth
│   ├── reviews_adapter.py         ← Google Maps reviews (Playwright)
│   ├── playwright_fallback.py     ← Headless Chromium fallback
│   └── geocoding.py               ← Nominatim geocoding
│
├── config/
│   ├── chains.yaml                ← Chain targets, regions, BLS series, scoring weights
│   └── loader.py                  ← Typed config access
│
├── frontend/
│   ├── index.html                 ← Leaflet map SPA (dark theme)
│   ├── openclaw.html              ← OpenClaw monitoring dashboard
│   ├── session.html               ← Live LLM session viewer
│   ├── css/style.css
│   ├── css/openclaw.css
│   └── js/app.js, openclaw.js
│
├── scripts/
│   ├── populate_reference_data.py ← Seed ref_industry, ref_brands, ref_regions
│   └── backfill_geocoding.py      ← Geocode stores missing coordinates
│
├── pipeline/                      ← Route registry, tracing, validation, health
│   ├── route_index.py             ← RouteContract dataclass + ROUTES registry (intent→adapter→DB)
│   ├── tracing.py                 ← PipelineTrace + TraceSpan structured span recording
│   ├── validation.py              ← Per-intent scraper output contracts + validate_scraper_output()
│   └── health.py                  ← Startup self-check (routes, adapters, thresholds, contracts)
│
├── tests/                         ← Full pytest suite (258 tests, 0 failures)
│   ├── conftest.py                ← In-memory SQLite fixtures (mem_engine, mem_session)
│   ├── pytest.ini
│   ├── unit/                      ← Pure logic, no DB, no external calls
│   │   ├── test_schemas.py        ← AgentQuery.validate(), parse_agent_query(), ModeConfig
│   │   ├── test_database_models.py← SourceFreshness/RateBudget properties, upsert/check
│   │   ├── test_scoring_careers.py← age_weight(), weighted_listing_count(), tiers
│   │   ├── test_scoring_sentiment.py← sentiment inversion, scaling, percentile ranking
│   │   ├── test_scoring_wage.py   ← wage gap, yearly→hourly, tier assignment
│   │   └── test_dedup_helpers.py  ← haversine, normalize, radius checks
│   ├── integration/               ← In-memory SQLite, mocked external deps
│   │   ├── test_ingest.py         ← ingest_signals(): upsert, dedup, geocode, snapshot
│   │   ├── test_validator.py      ← validate_and_check(): freshness, budget, mode
│   │   ├── test_scoring_engine.py ← compute_all_scores(): weights, tiers, DB writes
│   │   └── test_dedup_pipeline.py ← find_existing_match(), resolve_alias()
│   └── pipeline/
│       └── test_pipeline_contracts.py ← Route contracts, tracing, validation, health
│
├── collectors/                    ← WIP — future collector-pattern refactor
├── storage/                       ← WIP — future ingestion pipeline refactor
├── scraper/scrape.py              ← LEGACY CLI (delegates to scrapers/)
│
├── data/
│   ├── tracker.db                 ← Primary SQLite DB (14 tables)
│   ├── openclaw_logs/             ← Daily JSON request logs
│   └── openclaw_wishlists/        ← Daily JSON wishlist files
│
├── RUNBOOK.md                     ← Operational procedures
├── SYSTEM_DESIGN.md               ← Big-picture design rationale, pros/cons, industry standards
└── .venv/                         ← Python 3.12 virtual environment
```

---

## Database Schema (14 tables in tracker.db)

### Core Data
| Table | Model | Purpose |
|-------|-------|---------|
| `stores` | `Store` | Physical chain locations (store_num, chain, lat/lng, region) |
| `signals` | `Signal` | Raw observations from any source (store_num, source, signal_type, value) |
| `snapshots` | `Snapshot` | Periodic scan summaries (region, chain, source, counts) |
| `scores` | `Score` | Computed staffing scores per store (score_type, value, tier) |
| `wage_index` | `WageIndex` | Local vs chain pay comparison data |
| `local_employers` | `LocalEmployer` | Non-chain employers from Overture/OSM |

### Reference Data
| Table | Model | Purpose |
|-------|-------|---------|
| `ref_industry` | `IndustryCategory` | NAICS-based industry hierarchy with wage/employee averages |
| `ref_brands` | `BrandProfile` | Chain metadata (wikidata_id, careers_url, ATP spiders, OSM tags) |
| `ref_regions` | `RegionProfile` | Regional context (population, median income, unemployment) |
| `ref_category_map` | `CategoryMapping` | External taxonomy → internal industry crosswalk |

### Rate Limiting & Freshness
| Table | Model | Purpose |
|-------|-------|---------|
| `api_sources` | `ApiSource` | Registry of every external API (source_key, daily_limit, auth_type) |
| `api_request_log` | `ApiRequestLog` | Every individual HTTP request (latency, status, data yield) |
| `rate_budgets` | `RateBudget` | Daily usage rollup per source (used, remaining, success_rate) |
| `source_freshness` | `SourceFreshness` | When each intent/region/brand combo was last collected |

---

## OpenClaw Agent System

OpenClaw is an LLM-driven research planning agent that orchestrates data collection. It runs locally via Ollama (no cloud API keys required).

### How a Session Works

```
User starts session via POST /api/openclaw/run
│
├─1─ Build system prompt with:
│      • 13 industries + 49 mega-corps (term pools)
│      • Pilot briefing (auto-generated BEFORE the agent loop):
│          - Runs discovery_scan internally
│          - Injects ranked collection agenda (top 10 leads by priority)
│          - Lists already-fresh data the agent must NOT re-collect
│      • Region + goal context
│
├─2─ LLM reads the ranked agenda and generates JSON action
│      (propose / query / wish / status / done)
│      │
│      ├── propose → prevalidation gate:
│      │     1. Industry/brand enum check
│      │     2. Freshness gate (skip if data <threshold days old)
│      │     3. Search term pool validation (job/poi/sentiment)
│      │        └── also checks session-local terms added via wish
│      │     4. Budget dry-run
│      │
│      ├── query → executor.execute():
│      │     Routes to intent handler → calls scraper → DB write
│      │     Auto-stamps source_freshness table on success
│      │     NOTE: score_refresh, data_quality_audit, discovery_scan,
│      │     and campaign_status always execute in analyze mode
│      │     regardless of session mode (they are DB-internal)
│      │
│      ├── wish (new_term) → wishlist manager + session-local term pool
│      │     Term is immediately available in the same session
│      │     without waiting for operator approval
│      ├── status → rate budget summary
│      └── done → session complete
│
├─3─ Result fed back as next user message
│
└─4─ Loop (max 12 iterations) until done or budget exhausted
```

### Discovery Feedback Loop

The discovery engine closes the data collection loop — it analyses what's already in the DB and tells the agent where to look next.

```
  discovery_scan
      │
      ├── coverage_gaps      → brands/industries with zero stores (priority 85-90)
      ├── data_dimension_gaps → stores missing scores, wages, jobs, sentiment (50-80)
      ├── stale_leads         → freshness records past threshold (40-95)
      ├── geographic_clusters → grid-based clustering of high-stress areas (55)
      └── local_opportunities → local employer density vs chain tracking gaps (70-75)
      │
      ▼
  Ranked DiscoveryLeads → to_agent_proposal() → suggested_next queries
      │
      ▼
  Agent executes top leads → scraper writes data → freshness stamped
      │
      ▼
  Next discovery_scan sees progress, surfaces new gaps
```

The agent runs `discovery_scan` after the initial audit, then again mid-session after completing a batch. The scheduler also runs it daily at 1am for overnight operator review.
```

### Freshness System

Every successful execution stamps the `source_freshness` table. Future queries for the same intent/region/brand/industry combo are rejected until data goes stale.

| Intent | Threshold | Rationale |
|--------|-----------|-----------|
| `job_posting_volume` | 14 days | Job boards change biweekly |
| `sentiment_check` | 14 days | Sentiment shifts slowly |
| `poi_chain_locations` | 60 days | Store locations rarely change |
| `poi_local_density` | 60 days | Local employers are stable |
| `wage_baseline` | 90 days | BLS data is quarterly |
| `economic_context` | 90 days | Macro data is quarterly |
| `score_refresh` | 1 day | Recompute is cheap |
| `data_quality_audit` | 0 (always) | Always runs |
| `campaign_status` | 0 (always) | Always runs |
| `discovery_scan` | 0 (always) | Always runs — no external API calls |

### Industry Coverage

13 industries, 49 mega-corps, each with validated term pools:

| Industry | Mega-Corps | NAICS |
|----------|-----------|-------|
| `coffee_cafe` | starbucks, dutch_bros, peets, dunkin | 722515 |
| `fast_food` | mcdonalds, whataburger, chipotle, chickfila, wendys | 722513 |
| `full_service_restaurant` | applebees, chilis, olive_garden, ihop | 722511 |
| `retail_general` | target, walmart, costco | 452210/319 |
| `retail_grocery` | heb, kroger, whole_foods, trader_joes | 445110 |
| `healthcare_clinic` | cvs_minuteclinic, walgreens_clinic, hca, ascension | 621111/493 |
| `pharmacy` | cvs, walgreens | 446110 |
| `accommodation` | marriott, hilton, hyatt | 721110 |
| `fitness_wellness` | planet_fitness, la_fitness, orangetheory | 713940 |
| `childcare` | kindercare, bright_horizons, goddard_school | 624410 |
| `hair_beauty` | great_clips, supercuts, sport_clips, fantastic_sams | 812111/112 |
| `auto_repair` | jiffy_lube, midas, firestone, pep_boys, valvoline | 811111/112/118 |
| `hvac_skilled_trades` | service_experts, aire_serv, one_hour_heating, mr_electric, roto_rooter | 238220/210 |

---

## Data Source Status

### LIVE — Called by executor, producing data
| Source Key | Adapter | Intent(s) | Daily Limit |
|-----------|---------|-----------|-------------|
| `atp_geojson` | `AllThePlacesAdapter` | `poi_chain_locations` | 10,000 |
| `overture_s3` | `OvertureLocalAdapter` | `poi_local_density` | 10,000 |
| `bls_v1` | `BLSAdapter` | `wage_baseline`, `economic_context` | 500 |
| `careers_workday` | `careers_api.py` | `job_posting_volume` | 10,000 |
| `jobspy` | `JobSpyAdapter` | `job_posting_volume` | 50 |
| `reddit_json` | `RedditAdapter` | `sentiment_check` | 100 |
| `reddit_oauth` | `RedditAdapter` (PRAW) | `sentiment_check` | 1,000 |
| `nominatim` | `geocoding.py` | geocoding | 10,000 |

### REGISTERED BUT UNWIRED — Adapter exists, not called by executor
| Source Key | Adapter | Would Serve | Fix Needed |
|-----------|---------|-------------|------------|
| `overpass_api` | `OSMAdapter` | `poi_chain_locations` multi-source | Wire into `_execute_poi_chain` as fallback |
| `gmaps_scraper` | `ReviewsAdapter` | `sentiment_check` multi-source | Wire into `_execute_sentiment_check` |
| `gmaps_playwright` | `GoogleMapsStoreFinder` | `poi_chain_locations` discovery | Wire into executor |
| `wikidata_sparql` | *(not built)* | `ref_brands` enrichment | Build `wikidata_adapter.py` |

### SUGGESTED — Would expand coverage for underserved industries
| Source | Target Industries | Difficulty |
|--------|------------------|-----------|
| Yelp Fusion API | all (reviews, ratings) | Medium — free 5K/day |
| CMS/NPI Registry | healthcare_clinic, pharmacy | Low — public bulk download |
| USDA Food Environment Atlas | retail_grocery | Low — public CSV |
| State childcare licensing DBs | childcare | Medium — varies by state |
| Google Trends (pytrends) | all — "[brand] hiring" signals | Low — no key needed |
| US Census ACS | all — demographics, commute data | Low — public API |

---

## API Endpoints (43 routes)

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
| `GET` | `/api/ref/brands` | All brand profiles |
| `GET` | `/api/ref/industries` | Industry categories |
| `GET` | `/api/ref/regions` | Region profiles |
| `GET` | `/api/ref/categories` | Category mappings |
| `GET` | `/api/ref/summary` | Reference data summary |

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
| `GET` | `/api/agent/ollama/status` | Ollama connection check |
| `GET` | `/api/agent/ollama/models` | Available LLM models |
| `POST` | `/api/agent/ollama/pull` | Pull new model |
| `POST` | `/api/agent/ollama/research` | One-shot research query |

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
| `POST` | `/api/openclaw/run` | Start agent session (background) |
| `GET` | `/api/openclaw/session/live` | Live thought stream |

### Discovery
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/discovery/scan` | Run full discovery scan (region, max_leads, types params) |
| `GET` | `/api/discovery/summary` | Quick coverage dashboard (no full scan) |
| `GET` | `/api/discovery/leads` | Ranked leads with agent proposals (min_priority, limit params) |

### Scheduler & Legacy
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/scheduler/status` | Next scheduled run times |
| `GET` | `/api/spiritpool/stats` | SpiritPool extension stats (legacy) |

---

## Pipeline Package

The `pipeline/` package is the single source of truth for how data moves through the system. Every intent has a registered `RouteContract` that maps it all the way to a DB write.

```python
from pipeline.route_index import ROUTES

routes = ROUTES["poi_chain_locations"]
# [RouteContract(source_key="atp_geojson", scraper_adapter="AllThePlacesAdapter",
#                signal_type="listing", db_table="Store", status="live"),
#  RouteContract(source_key="overture_s3",  ..., status="live"),
#  RouteContract(source_key="overpass_api", ..., status="unwired")]
```

| Module | Purpose |
|--------|---------|
| `route_index.py` | `RouteContract` dataclass + `ROUTES` dict — every intent mapped to source → adapter → DB |
| `tracing.py` | `PipelineTrace` + `TraceSpan` for structured per-stage span recording |
| `validation.py` | `SCRAPER_OUTPUT_CONTRACTS` + `validate_scraper_output()` — catches bad scraper output before it hits the DB |
| `health.py` | `run_startup_check()` — verifies routes, adapter imports, threshold consistency; exposed at `/api/pipeline/health` |

---

## Test Suite

258 tests across three categories, all passing. Run with:

```bash
python -m pytest tests/ -v
python -m pytest tests/unit/ -v        # fast — no DB or external calls
python -m pytest tests/integration/ -v # in-memory SQLite, all deps mocked
python -m pytest tests/pipeline/ -v   # route contracts, tracing, health
python -m pytest tests/ --cov=agent_interface --cov=backend --cov-report=term-missing
```

**Isolation strategy:** Integration tests use in-memory SQLite. External dependencies (`init_db`, `get_session`, `geocode`, `rate_manager`) are patched at the call site so the system under test owns its session lifecycle.

---

## Scoring Model

Every store gets a composite score from 0–100 built from three independent sub-scores:

```
Composite = (careers_weight × careers_score)
          + (job_boards_weight × board_score)
          + (sentiment_weight × sentiment_score)

Weights (configurable in config/chains.yaml):
  careers_api:  40%
  job_boards:   35%
  sentiment:    25%
```

If a source has no data for a store, its weight is redistributed proportionally.

### Careers API Sub-Score

**Age decay:** Fresh postings (< 7 days old) carry full weight. Postings 30–90 days old decay toward zero. Postings > 90 days = standing requisitions = no signal.

**Baseline-relative scoring:** A store's score is its percentile rank within the region — not its absolute listing count.

### Score Tiers

| Tier | Percentile | Meaning |
|------|-----------|---------|
| `critical` | Top 33% | High hiring pressure, maximum job fair ROI |
| `elevated` | Middle 33% | Moderate pressure, good secondary target |
| `adequate` | Bottom 33% | Normal staffing, low priority |

### Targeting Score

```
Targeting = (staffing_stress × 0.40) + (wage_gap × 0.30)
          + (isolation × 0.20) + (local_density × 0.10)
```

- **staffing_stress** — composite score from above
- **wage_gap** — how much more local employers pay for the same role
- **isolation** — distance to nearest same-chain store (isolated = captive labor)
- **local_density** — local non-chain employers within 2 miles hiring in same industry

---

## Quickstart

```bash
# 1. Clone and set up
git clone <your-repo>
cd First-Helios
python3 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install flask flask-cors sqlalchemy requests tqdm pyyaml \
            apscheduler python-jobspy praw nltk pandas duckdb \
            playwright google-maps-scraper

playwright install firefox
playwright install chromium --with-deps

# 3. Install Ollama (for OpenClaw agent)
curl -fsSL https://ollama.com/install.sh | sh
ollama pull qwen2.5:7b-instruct

# 4. (Optional) Set environment variables for higher rate limits
export REDDIT_CLIENT_ID="your_id"
export REDDIT_CLIENT_SECRET="your_secret"

# 5. Seed reference data
python scripts/populate_reference_data.py

# 6. Start the server
python server.py --debug
# → http://localhost:8765         (map)
# → http://localhost:8765/openclaw (agent dashboard)

# 7. Run an OpenClaw session
curl -X POST http://localhost:8765/api/openclaw/run \
  -H "Content-Type: application/json" \
  -d '{"region": "austin_tx", "goal": "initial data collection"}'

# 8. Watch live session
# Open http://localhost:8765/openclaw/session in browser
```

---

## Known Issues & Where They Originate

### Layer 1 (Scrapers)
| Issue | File | Impact | Notes |
|-------|------|--------|-------|
| AllThePlaces only covers brands with ATP spiders | `scrapers/alltheplaces_adapter.py` | Healthcare, childcare, fitness brands have no POI source | Wire OSM + Overture chain as fallbacks |
| JobSpy hard-capped at 50 daily requests | `scrapers/jobspy_adapter.py` | Limits job posting volume to ~50 brand/region combos/day | Sufficient for Austin; will need upgrade for multi-region |
| Reddit JSON fallback returns limited results | `scrapers/reddit_adapter.py` | Without PRAW OAuth, sentiment coverage is thin | Set `REDDIT_CLIENT_ID`/`REDDIT_CLIENT_SECRET` env vars |
| Google Maps reviews adapter exists but never called | `scrapers/reviews_adapter.py` | Sentiment relies solely on Reddit | Wire into `_execute_sentiment_check` |

### Layer 2 (Backend)
| Issue | File | Impact | Notes |
|-------|------|--------|-------|
| Only `coffee_cafe` chains configured in YAML | `config/chains.yaml` | Scheduler only runs jobs for Starbucks | Add chain configs for fast_food, retail mega-corps |
| BLS series IDs only cover food service | `config/chains.yaml` | `wage_baseline` for healthcare, retail returns no data | Add series IDs for each industry's MSA |
| Score computation assumes food service context | `backend/scoring/engine.py` | Scores for non-food industries may need different weights | Make weights per-industry in config |

### Layer 3 (Agent/Orchestration)
| Issue | File | Impact | Notes |
|-------|------|--------|-------|
| LLM may still mix terms across industries | `openclaw/orchestrator.py` | Pre-validation catches it, but wastes an LLM iteration | Improved prompt + wishlist session pool mitigates; 7b model has limits |
| `economic_context` handler is DB-only | `agent_interface/executor.py` | No live economic data collection | Could wire BLS unemployment + CPI series |
| Executor `_execute_poi_chain` only tries AllThePlaces | `agent_interface/executor.py` | No multi-source agreement for POI data | OSM + Overture chain adapters ready to wire |
| `data_quality_audit` hardcodes Starbucks thresholds | `agent_interface/executor.py` | "Expected ~300+" only meaningful for Starbucks Austin | Make brand/region thresholds dynamic |

### Layer 4 (Frontend)
| Issue | File | Impact | Notes |
|-------|------|--------|-------|
| Map only shows `coffee_cafe` stores | `frontend/js/app.js` | Other industries don't appear on map | Extend filter controls to all 13 industries |
| OpenClaw dashboard doesn't show freshness data | `frontend/js/openclaw.js` | Operator can't see what's stale | Add freshness section to dashboard |

---

## Future Development Approach

### Phase 1: Wire What Exists (low effort, high impact)
These adapters are already implemented and tested. They just need to be called by the executor.

1. **Wire OSM + Overture chain into `_execute_poi_chain`** — 3-source agreement across all brands with wikidata IDs
2. **Wire `ReviewsAdapter` into `_execute_sentiment_check`** — doubles sentiment signal coverage
3. **Wire JobSpy `_scrape_wages()` into `_execute_wage_baseline`** — real posted wages complement BLS averages
4. **Add `chains.yaml` configs for fast_food + retail mega-corps** — unlocks scheduler for those industries

### Phase 2: Expand Data Access (medium effort)
5. **Build `wikidata_adapter.py`** — auto-populate `ref_brands` from Wikidata SPARQL (source already registered)
6. **Add Google Trends via `pytrends`** — leading indicator for "[brand] hiring" search volume
7. **Add CMS NPI Registry adapter** — healthcare/pharmacy provider coverage (free public data)
8. **Add USDA Food Environment Atlas** — grocery industry context (free CSV)

### Phase 3: Multi-Region + Scale (high effort)
9. **Add second region** (Dallas, Houston, or San Antonio) — config system supports it, need to verify all adapters handle it
10. **Move from SQLite to PostgreSQL** — when concurrent writes become a bottleneck
11. **Add Yelp Fusion API adapter** — 5K/day free tier, cross-industry review data
12. **Add state childcare licensing DB scraper** — Texas DFPS data for childcare industry

### Phase 4: Production Hardening
13. **Add health checks + alerting** for Ollama/scraper failures
14. **Add request deduplication** in executor (beyond freshness gate)
15. **Add A/B scoring weights** — test different weight configs per industry
16. **Dashboard freshness panel** — show stale sources + next-due dates

---

## Configuration

All chain targets, scoring weights, and region definitions live in `config/chains.yaml`. Key sections:

- `regions:` — geographic targets with center coordinates and bounding box
- `chains:` — chain definitions with careers API endpoints and target keywords
- `industries:` — industry taxonomy with local employer search terms
- `scoring.weights` — composite score weights per source type
- `scoring.posting_age_decay` — fresh/stale thresholds for careers API scoring
- `bls_series` — series IDs for Austin-area wage baseline data
- `scheduler` — cron definitions for automated collection jobs

---

## Important Constraints

**Public data only** — no logins, no paywalls, no bypassing access controls. The legal defensibility of this project depends on this being absolute.

**Austin TX only for now** — build it right for one city before adding regions. The config system supports multi-region; the pipeline focuses on one.

**Do not touch `spiritpool/`** — the browser extension is on hiatus. Preserved for future use once the pipeline proves its value.

**Do not touch `data/spiritpool.db`** — separate from `data/tracker.db`, must stay intact.

---

## Background: Why This Exists

Chain employers capture labor from local communities while wages, benefits, and profits flow out. Local independent employers often pay more and keep money in the community but lack the recruiting infrastructure to compete.

This platform gives community organizers a data-driven way to time and place job fairs — specifically at chain locations where workers have the most leverage and local alternatives pay the most. Everything is public data, all actions are protected commercial speech and labor market competition, and the mission is explicitly constructive (building local employment) rather than punitive.

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.12 |
| Web framework | Flask 3.1 (port 8765) |
| Database | SQLite via SQLAlchemy |
| LLM | Ollama + qwen2.5:7b-instruct (local, 4.7GB, Q4_K_M) |
| Scheduler | APScheduler |
| Spatial queries | DuckDB + httpfs (Overture/ATP Parquet) |
| Geocoding | Nominatim (OSM) |
| Job scraping | python-jobspy |
| Reddit | PRAW + JSON fallback |
| Frontend | Vanilla JS, Leaflet.js, Chart.js |
| Map tiles | CARTO dark basemap |
