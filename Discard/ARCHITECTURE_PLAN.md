# ARCHITECTURE_PLAN.md — Agent-Driven Collection Platform Restructure

**Created:** 2026-03-20
**Status:** Planning (not yet implemented)
**Project root:** `/home/fortune/CodeProjects/First-Helios`
**Venv:** `.venv/` (Python 3.12)

---

## Purpose

Restructure First-Helios from a cron-scheduled scraper collection into an
**agent-operated research platform** where:

1. An LLM agent **plans** what questions need answering about a local geographic area
2. The system **queues** those as schema-validated collection tasks
3. The agent can **pause, inspect results, re-plan**, and queue more
4. All inputs are **enum-constrained** — no freeform strings hitting APIs
5. Outputs are **concise, machine-readable** corrections the agent can act on

---

## Current State (2026-03-20)

### Database: `data/tracker.db`

| Table | Rows | Purpose |
|-------|------|---------|
| stores | 5,289 | Chain store locations (starbucks:329, mcdonalds:119, dutch_bros:35, local:4806) |
| signals | 5,320 | Raw scraper observations |
| scores | 36 | Composite targeting scores per store |
| snapshots | 12 | Score history snapshots |
| wage_index | 18 | Wage observations |
| local_employers | 4,805 | Non-chain POIs from Overture |
| api_sources | 16 | Registered external API sources with daily limits |
| api_request_log | 3 | Individual request tracking (latency, status, bytes) |
| rate_budgets | 16 | Daily rollup usage per API source |
| ref_brands | 6 | Brand profiles (Starbucks, Dutch Bros, McDonald's, Whataburger, Target, Chipotle) |
| ref_industry | 11 | NAICS industry categories |
| ref_regions | 1 | Region profiles (austin_tx) |
| ref_category_map | 47 | Category → industry mappings |

### Codebase: 32 Python files, ~8,200 lines

```
server.py                          # Flask API, 10+ endpoints, port 8765
backend/
    database.py                    # 15 SQLAlchemy models, init_db, get_session
    ingest.py                      # Signal ingestion pipeline
    scheduler.py                   # APScheduler, 9+ cron jobs
    targeting.py                   # Composite scoring with haversine
    rate_manager.py                # Rate budget tracking + request logging
    tracked_request.py             # Drop-in tracked_get/tracked_post wrappers
    scoring/
        engine.py, careers.py, sentiment.py, wage.py
    models/
        reference.py               # BrandProfile, IndustryCategory, RegionProfile, CategoryMapping
scrapers/
    base.py                        # BaseScraper + ScraperSignal
    alltheplaces_adapter.py        # ATP GeoJSON → chain stores
    overture_adapter.py            # DuckDB S3 parquet → chains + local
    osm_adapter.py                 # Overpass API → cross-reference
    bls_adapter.py                 # BLS wage series
    careers_api.py                 # Workday job postings
    geocoding.py                   # Nominatim geocoder
    jobspy_adapter.py              # Indeed/Glassdoor via JobSpy
    reddit_adapter.py              # Reddit sentiment
    reviews_adapter.py             # Google Maps reviews
    playwright_fallback.py         # Headless browser (Workday + Maps)
scripts/
    populate_reference_data.py     # Seed NAICS, brands, regions, BLS wages
    backfill_geocoding.py          # Fix null coordinates
config/
    loader.py                      # YAML config reader
    chains.yaml                    # Chain/region/industry config
frontend/
    index.html, css/style.css, js/app.js   # Leaflet dark map with filters
```

### 16 Tracked API Sources

| Source Key | Daily Limit | Auth | Notes |
|-----------|-------------|------|-------|
| bls_v1 | 500 | none | Shared limit with bls_v1_post |
| bls_v1_post | 500 | none | POST batch series |
| careers_workday | 10,000 | none | Starbucks Workday API |
| workday_playwright | 10,000 | none | Headless browser fallback |
| nominatim | 10,000 | none | OSM geocoder |
| overpass_api | 10,000 | none | OSM Overpass |
| atp_geojson | 10,000 | none | AllThePlaces GeoJSON |
| atp_parquet | 10,000 | none | ATP via DuckDB httpfs |
| overture_s3 | 10,000 | none | Overture Maps S3 parquet |
| jobspy | 50 | none | Indeed/Glassdoor scraper |
| reddit_json | 100 | none | Public JSON API |
| reddit_oauth | 1,000 | oauth | PRAW authenticated |
| gmaps_scraper | 10,000 | none | google-maps-scraper lib |
| gmaps_playwright | 10,000 | none | Headless browser |
| wikidata_sparql | 10,000 | none | SPARQL endpoint |
| carto_tiles | 10,000 | none | Basemap tiles |

---

## Problems With Current Architecture

| Problem | Symptom |
|---------|---------|
| **Monolithic coupling** | `scheduler.py` imports every scraper directly. Adding a data source means editing scheduler, database, server, and config. |
| **No workflow state machine** | "Collect Austin coffee data" is 6 separate cron jobs with no parent concept. Step 3 fails → steps 4-6 run with stale data. |
| **Scraper logic mixed with storage** | Every adapter has its own `session.add(Store(...))` upsert code. Same pattern copy-pasted 6 times. |
| **No task dependency graph** | Overture local query should run *after* brand profiles load. Currently just staggered by clock offset. |
| **No agent query interface** | An LLM can't ask "what do I need to know about Austin coffee labor?" — it has to know which endpoints to call and in what order. |
| **Rate manager is reactive** | Tracks usage after the fact but doesn't pre-plan budget allocation across a research session. |

---

## Target Architecture: Three Layers

```
┌──────────────────────────────────────────────────────────┐
│  Layer 1: COLLECTORS (stateless, reusable)                │
│  collectors/                                              │
│  Each: takes config dict → returns list[dataclass]        │
│  No database imports. No SQLAlchemy. No side effects.     │
├──────────────────────────────────────────────────────────┤
│  Layer 2: STORAGE (single-point-of-write)                 │
│  storage/                                                 │
│  Accepts typed records → upserts to DB                    │
│  Knows schema. Doesn't know where data came from.         │
├──────────────────────────────────────────────────────────┤
│  Layer 3: AGENT INTERFACE + ORCHESTRATION                 │
│  agent_interface/                                         │
│  Enum-validated queries → queue → execute → results       │
│  The LLM agent talks ONLY to this layer.                  │
└──────────────────────────────────────────────────────────┘
```

### Import Rules (Enforced)

- `collectors/` may NOT import from `backend/`, `storage/`, or `agent_interface/`
- `storage/` imports from `backend/database` and `collectors/schema` only
- `agent_interface/` imports from `collectors/`, `storage/`, and `backend/`
- `scrapers/` (legacy) continues working unchanged — gradual migration

---

## Layer 1: Collectors

New directory: `collectors/`

Stateless pure functions. Take a config dict, return a list of typed dataclasses.
No database contact. Independently testable.

### Files to Create

#### `collectors/__init__.py`

Docstring-only module init.

#### `collectors/schema.py`

Five standardized output dataclasses:

```python
@dataclass POIRecord:       # source, source_id, name, lat, lng, address, brand, is_chain, confidence, ...
@dataclass WageRecord:      # source, source_id, region, brand, hourly_wage, annual_salary, period, ...
@dataclass JobPostingRecord: # source, source_id, brand, job_title, location, salary_min/max, posted_date, ...
@dataclass SentimentRecord:  # source, source_id, brand, text, sentiment_score, rating, topic, ...
@dataclass EconomicIndicatorRecord: # source, source_id, region, indicator_type, value, period, naics_code, ...
```

All have: `source`, `source_id` (unique within source), `raw_properties: dict`, `collected_at: datetime`.

#### `collectors/alltheplaces.py`

```python
def collect(brand: str, bbox: dict, spider_name: str = None, timeout: int = 120) -> list[POIRecord]:
```

- Downloads GeoJSON from `alltheplaces-data.openaddresses.io/runs/latest/output/{spider}.geojson`
- Filters to bbox
- Returns `POIRecord` with `source="alltheplaces"`, `confidence=1.0` (first-party)
- Spider map: starbucks→starbucks_us, dutch_bros→dutch_bros, mcdonalds→mcdonalds, etc.

#### `collectors/overture_places.py`

```python
def collect_chain(brand: str, name_pattern: str, bbox: dict, min_confidence: float = 0.8) -> list[POIRecord]:
def collect_local(bbox: dict, categories: list[str], min_confidence: float = 0.7, exclude_chains: list[str] = None) -> list[POIRecord]:
```

- DuckDB S3 parquet query against Overture Maps release
- Auto-detects latest release from S3
- Installs `spatial` + `httpfs` extensions automatically
- `collect_local` excludes ~40 known chain patterns by default

#### `collectors/osm_overpass.py`

```python
def collect_by_brand_wikidata(brand: str, wikidata_id: str, bbox: dict) -> list[POIRecord]:
def collect_by_amenity(amenity_type: str, bbox: dict, exclude_chains: list[str] = None) -> list[POIRecord]:
```

- Overpass API `[out:json]` queries
- Brand query uses `brand:wikidata` tag
- Amenity query for local POI discovery (cafe, fast_food, restaurant)
- Returns `source="osm"`, `confidence=0.95`

#### `collectors/bls_series.py`

```python
def collect_series(series_ids: list[str], start_year: int, end_year: int, region: str, api_key: str = None) -> list[EconomicIndicatorRecord]:
```

- V1 (no key, 500/day) or V2 (keyed, 10K/day) endpoint
- Classifies series by prefix: LAUS→unemployment, OEU→wage, ENU→employment, CU→cpi
- Returns `EconomicIndicatorRecord` with `source="bls"`

### Migration Path for Existing Scrapers

The `scrapers/` directory stays as-is. Collectors are new parallel implementations.
Once a collector is verified, the corresponding scraper method can delegate to it.
No big-bang rewrite.

---

## Layer 2: Storage

New directory: `storage/`

Single-point-of-write for each data type. Handles deduplication and upsert logic.
Never called by agents directly — only by the orchestration layer.

### Files to Create

#### `storage/__init__.py`

Docstring-only module init.

#### `storage/ingest_poi.py`

```python
def ingest_pois(records: list[POIRecord], region: str, industry_map: dict = None) -> dict:
    # Returns {"inserted": int, "updated": int, "skipped": int, "table": str}
```

- Chain POIs (`is_chain=True`) → `stores` table
- Local POIs → `local_employers` table
- Builds stable `store_num` from `source + source_id`: `ATP-SB-12345678`
- Deduplicates by `store_num` (chains) or `overture_id` (local)
- This is the ONLY place that writes POI data. Scrapers currently each have their own
  upsert code — that duplication gets consolidated here.

#### Future: `storage/ingest_wages.py`, `storage/ingest_jobs.py`, `storage/ingest_sentiment.py`

Same pattern. One file per record type. Each owns its table writes.

---

## Layer 3: Agent Interface

New directory: `agent_interface/`

This is the LLM-facing API. Everything an agent submits goes through schema validation.
Everything it receives back is a concise, structured response.

### Design Principles

1. **Enum-constrained inputs** — agent picks from fixed lists, never constructs freeform API calls
2. **Pre-flight validation** — schema check → budget check → freshness check → dedup check
3. **Concise outputs** — `ConciseResult` with counts, anomalies, and `suggested_next` actions
4. **Pausable queue** — agent (or operator) can pause/resume execution
5. **Self-correcting** — on rejection, response includes `valid_options` so agent can fix and retry

### Files to Create

#### `agent_interface/__init__.py`

Docstring-only module init.

#### `agent_interface/schemas.py`

Constrained enumerations (agent MUST pick from these):

```python
class Intent(Enum):
    POI_CHAIN_LOCATIONS    # Where are all X stores in region?
    POI_LOCAL_DENSITY      # How many local employers near a point?
    WAGE_BASELINE          # What do workers earn in this industry/region?
    JOB_POSTING_VOLUME     # How many open positions for X in region?
    SENTIMENT_CHECK        # What do workers say about X?
    ECONOMIC_CONTEXT       # Unemployment, CPI, cost of living
    SCORE_REFRESH          # Recompute scores with latest data
    DATA_QUALITY_AUDIT     # What's stale, missing, conflicting?
    CAMPAIGN_STATUS        # What's the state of the queue?

class Region(Enum):    AUSTIN_TX = "austin_tx"
class Industry(Enum):  COFFEE_CAFE, FAST_FOOD, FULL_SERVICE_RESTAURANT, RETAIL_GENERAL, ACCOMMODATION
class Brand(Enum):     STARBUCKS, DUTCH_BROS, MCDONALDS, WHATABURGER, CHIPOTLE, TARGET
class DataSource(Enum): AUTO, ALLTHEPLACES, OVERTURE, OSM, BLS, JOBSPY, REDDIT
class QueuePriority(Enum): CRITICAL=10, HIGH=25, NORMAL=50, LOW=75, BACKFILL=90
```

Input dataclass:

```python
@dataclass AgentQuery:
    intent: Intent                    # required
    region: Region                    # required
    priority: QueuePriority = NORMAL
    brand: Optional[Brand]            # required for chain intents
    industry: Optional[Industry]      # required for density/wage intents
    source_preference: DataSource = AUTO
    max_results: int = 500            # cap: 5000
    max_budget_spend: int = 5         # cap: 50 API calls
    known_count: Optional[int]        # what agent already has (for dedup)
    reason: str                       # why (for logging)

    def validate() -> list[str]:      # returns errors or empty list
```

Output dataclass:

```python
@dataclass ConciseResult:
    query_id: str
    status: ResultStatus              # COMPLETED | PARTIAL | QUEUED | REJECTED | DUPLICATE | PAUSED | NO_BUDGET
    intent: Intent
    records_found: int
    records_new: int
    records_updated: int
    staleness_days: Optional[float]   # age of freshest existing data
    coverage_pct: Optional[float]
    source_agreement: Optional[float] # do multiple sources agree? 0-1
    api_calls_used: int
    api_calls_remaining_today: Optional[int]
    estimated_seconds: Optional[float]
    anomalies: list[str]              # things agent should know
    suggested_next: list[dict]        # system recommends what to do next
    errors: list[str]                 # only if rejected/failed
```

Queue status dataclass:

```python
@dataclass QueueStatus:
    is_paused: bool
    total_pending: int
    total_reserved: int
    completed_today: int
    failed_today: int
    budget_summary: dict              # source → {used, remaining, limit}
```

#### `agent_interface/validator.py`

Pre-flight checks before queueing:

```python
def validate_and_check(query: AgentQuery) -> ConciseResult:
```

1. **Schema validation** — intent-specific required fields (chain intents need brand, etc.)
2. **Freshness check** — is there already recent-enough data? (configurable per intent: POI=7d, wages=30d, jobs=1d, sentiment=3d, economic=90d)
3. **Budget check** — can we afford the API calls? Returns `NO_BUDGET` with reset time if not.
4. Returns `REJECTED`, `DUPLICATE`, `NO_BUDGET`, or `QUEUED`.

#### `agent_interface/executor.py`

Translates validated queries into collector calls:

```python
def execute(query: AgentQuery) -> ConciseResult:
```

Intent routing:

| Intent | Collectors Used | Storage Target |
|--------|----------------|----------------|
| `POI_CHAIN_LOCATIONS` | alltheplaces → overture → osm (priority order) | `storage.ingest_poi` → stores |
| `POI_LOCAL_DENSITY` | overture `collect_local` → osm `collect_by_amenity` | `storage.ingest_poi` → local_employers |
| `WAGE_BASELINE` | bls `collect_series` | `storage.ingest_wages` |
| `JOB_POSTING_VOLUME` | jobspy (future) | `storage.ingest_jobs` |
| `SENTIMENT_CHECK` | reddit (future) | `storage.ingest_sentiment` |
| `SCORE_REFRESH` | internal scoring engine | scores table |
| `DATA_QUALITY_AUDIT` | DB queries only (no API calls) | anomalies list |

Each executor:
- Checks per-source budget via `max_budget_spend`
- Runs sources in priority order, stops when budget exhausted
- Computes `source_agreement` when multiple sources return data
- Populates `suggested_next` based on results (e.g., "new stores found → refresh scores")

#### `agent_interface/queue_manager.py`

```python
class AgentQueueManager:
    def submit(query: AgentQuery) -> ConciseResult       # validate + execute
    def submit_batch(queries: list) -> list[ConciseResult]  # dedup across batch
    def pause(reason: str) -> dict
    def resume() -> dict
    def status() -> QueueStatus
    def get_result(query_id: str) -> ConciseResult
```

- Thread-safe singleton
- Pause blocks all new execution (returns `PAUSED` status)
- Batch submission: later queries benefit from earlier ones (freshness dedup)
- Currently synchronous execution; upgrade to async worker pool later

### API Endpoints to Add to `server.py`

```
POST /api/agent/query             Submit one structured query
POST /api/agent/batch             Submit multiple queries
GET  /api/agent/queue/status      Inspect queue state + budget
POST /api/agent/queue/pause       Pause execution
POST /api/agent/queue/resume      Resume execution
GET  /api/agent/options           Return all valid enum values (agent calls first)
```

All return JSON. Invalid enum values return HTTP 422 with `valid_options` dict
so the agent can self-correct.

---

## Framework Assessment

### Workflow Orchestration

| Framework | Verdict | Rationale |
|-----------|---------|-----------|
| **Prefect** | Recommended (optional) | Python-native, task DAGs with retry/timeout, free self-hosted, single-process at our scale. |
| **Apache Airflow** | Overkill | Needs separate scheduler/webserver/Postgres. Built for 1000s of DAGs. |
| **Dagster** | Close second | Asset-oriented (good fit) but heavier infra requirement. |
| **Celery** | Wrong level | Task queue, no DAG dependencies. We'd rebuild Prefect. |
| **APScheduler** (current) | Outgrown | No task deps, no retry backoff, no workflow state. |

**Decision:** Build with plain Python first (the topological-sort executor in `workflows/tasks.py`).
Add Prefect as optional accelerator — everything works without it via fallback decorators.

### Geographic Data Frameworks

| Tool | Status | Keep/Replace |
|------|--------|-------------|
| DuckDB + Overture parquet | In use | Keep — excellent for S3 spatial queries |
| AllThePlaces GeoJSON | In use | Keep — best chain location accuracy |
| OSM Overpass | In use | Keep — cross-reference and fallback |
| geopy/Nominatim | In use | Keep for geocoding |
| osm2pgsql | Not used | Consider if expanding to 10+ metros |
| Kepler.gl / Deck.gl | Not used | Future frontend upgrade from Leaflet |

---

## Campaign Concept (Optional Layer)

Campaigns are pre-built collection plans that answer a specific question:

```python
@dataclass Campaign:
    name: str                        # "austin_coffee_labor"
    question: str                    # "What is the staffing landscape for coffee workers in Austin?"
    region: str
    bbox: dict
    steps: list[CampaignStep]       # ordered, with depends_on
    schedule_cron: Optional[str]     # "0 2 * * 0" = Sunday 2am
```

Each `CampaignStep` maps to a collector invocation with explicit dependencies.
The executor runs a topological sort — steps only run after their dependencies complete.

Pre-built campaigns:
- `austin_coffee_labor` — 9 steps: ATP+Overture+OSM for Starbucks/Dutch Bros, local density, BLS wages, scoring
- `austin_fast_food_labor` — 4 steps: ATP for McDonald's/Whataburger/Chipotle, local density

These are **separate from the agent interface**. An agent could trigger a campaign,
or it could submit individual queries. Campaigns are for scheduled recurring collection.

---

## Agent Workflow Example

```
1. Agent: GET /api/agent/options
    → learns valid intents, regions, brands, industries

2. Agent: POST /api/agent/query
   {"intent": "data_quality_audit", "region": "austin_tx"}
    → anomalies: ["0 local employers indexed", "starbucks: only 35 stores"]
    → suggested_next: [{"action": "collect_local", "query": {...}}]

3. Agent: POST /api/agent/batch
   {"queries": [
     {"intent": "poi_chain_locations", "brand": "starbucks", "region": "austin_tx"},
     {"intent": "poi_local_density", "industry": "coffee_cafe", "region": "austin_tx"},
     {"intent": "wage_baseline", "industry": "coffee_cafe", "region": "austin_tx"}
   ]}
    → result[0]: DUPLICATE — 329 stores already fresh
    → result[1]: COMPLETED — 621 new local employers
    → result[2]: NO_BUDGET — BLS exhausted, resets midnight

4. Agent: POST /api/agent/query
   {"intent": "score_refresh", "region": "austin_tx"}
    → COMPLETED — 35 scores updated

5. Agent: POST /api/agent/queue/pause {"reason": "BLS blocked, resume tomorrow"}
```

---

## Implementation Order

### Phase 1: Collectors + Storage (foundation)

```
mkdir -p collectors storage

1. Create collectors/schema.py          — 5 dataclasses
2. Create collectors/alltheplaces.py    — collect(brand, bbox) → list[POIRecord]
3. Create collectors/overture_places.py — collect_chain + collect_local
4. Create collectors/osm_overpass.py    — collect_by_brand_wikidata + collect_by_amenity
5. Create collectors/bls_series.py      — collect_series → list[EconomicIndicatorRecord]
6. Create storage/ingest_poi.py         — ingest_pois → stores / local_employers
7. Verify: run each collector standalone, check outputs
```

### Phase 2: Agent Interface (the agent-facing layer)

```
mkdir -p agent_interface

1. Create agent_interface/schemas.py     — enums + AgentQuery + ConciseResult
2. Create agent_interface/validator.py   — validate_and_check with freshness/budget checks
3. Create agent_interface/executor.py    — intent → collector routing
4. Create agent_interface/queue_manager.py — submit/pause/resume/status
5. Add /api/agent/* endpoints to server.py
6. Verify: curl test all endpoints with valid and invalid inputs
```

### Phase 3: Wire Rate Tracking Into Collectors

```
1. Add tracked_get/tracked_post calls inside collectors
   (collectors stay "stateless" — rate tracking is a side effect at the HTTP layer)
2. Or: wrap collector calls in the executor with timing + rate_manager.log_request
3. Integrate budget checks into validator pre-flight
```

### Phase 4: Optional Enhancements

```
1. pip install prefect — enable flow decorators if available
2. Async worker pool in queue_manager (replace sync execution)
3. Campaign definitions in workflows/campaigns.py
4. Migrate remaining scrapers (reddit, jobspy, reviews, playwright) to collectors/
5. New storage handlers: ingest_wages, ingest_jobs, ingest_sentiment
```

---

## Files to Create (Summary)

| File | Layer | Lines (est.) | Priority |
|------|-------|-------------|----------|
| `collectors/__init__.py` | 1 | 10 | Phase 1 |
| `collectors/schema.py` | 1 | 120 | Phase 1 |
| `collectors/alltheplaces.py` | 1 | 120 | Phase 1 |
| `collectors/overture_places.py` | 1 | 180 | Phase 1 |
| `collectors/osm_overpass.py` | 1 | 160 | Phase 1 |
| `collectors/bls_series.py` | 1 | 100 | Phase 1 |
| `storage/__init__.py` | 2 | 10 | Phase 1 |
| `storage/ingest_poi.py` | 2 | 120 | Phase 1 |
| `agent_interface/__init__.py` | 3 | 10 | Phase 2 |
| `agent_interface/schemas.py` | 3 | 200 | Phase 2 |
| `agent_interface/validator.py` | 3 | 150 | Phase 2 |
| `agent_interface/executor.py` | 3 | 350 | Phase 2 |
| `agent_interface/queue_manager.py` | 3 | 130 | Phase 2 |
| `workflows/__init__.py` | 3 | 10 | Phase 4 |
| `workflows/campaigns.py` | 3 | 200 | Phase 4 |
| `workflows/tasks.py` | 3 | 200 | Phase 4 |
| `workflows/scheduler.py` | 3 | 100 | Phase 4 |

Estimated new code: ~2,170 lines across 17 files.

---

## What Does NOT Change

- `backend/database.py` — models stay, no new tables needed for Phase 1-2
- `backend/rate_manager.py` — used as-is by agent_interface
- `backend/tracked_request.py` — used as-is
- `backend/scoring/` — called by executor for `SCORE_REFRESH` intent
- `scrapers/` — all existing adapters continue working, gradual migration
- `server.py` — existing endpoints stay, new `/api/agent/*` endpoints added
- `config/` — unchanged
- `frontend/` — unchanged (future: add agent dashboard)
- `data/tracker.db` — schema unchanged for Phase 1-2

---

## Verification Checklist (Next Session)

After building Phase 1 + Phase 2:

```bash
# 1. Collectors work standalone
python3 -c "
from collectors.schema import POIRecord
from collectors.alltheplaces import collect
bbox = {'west': -97.9383, 'east': -97.4104, 'south': 30.0986, 'north': 30.5168}
records = collect('starbucks', bbox)
print(f'ATP: {len(records)} POIRecords')
assert all(isinstance(r, POIRecord) for r in records)
"

# 2. Storage ingest works
python3 -c "
from collectors.schema import POIRecord
from storage.ingest_poi import ingest_pois
# ... create test POIRecord, ingest, verify DB count increases
"

# 3. Agent options endpoint
curl -s http://localhost:8765/api/agent/options | python -m json.tool

# 4. Agent query with valid input
curl -s -X POST http://localhost:8765/api/agent/query \
  -H 'Content-Type: application/json' \
  -d '{"intent":"data_quality_audit","region":"austin_tx"}' | python -m json.tool

# 5. Agent query with INVALID input → gets correction
curl -s -X POST http://localhost:8765/api/agent/query \
  -H 'Content-Type: application/json' \
  -d '{"intent":"bad_intent","region":"austin_tx"}' | python -m json.tool
# Should return 422 with valid_options

# 6. Pause/resume
curl -s -X POST http://localhost:8765/api/agent/queue/pause \
  -H 'Content-Type: application/json' \
  -d '{"reason":"testing"}' | python -m json.tool

curl -s -X POST http://localhost:8765/api/agent/query \
  -H 'Content-Type: application/json' \
  -d '{"intent":"data_quality_audit","region":"austin_tx"}' | python -m json.tool
# Should return status: "paused"

curl -s -X POST http://localhost:8765/api/agent/queue/resume | python -m json.tool
```
