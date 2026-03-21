# First-Helios: Data Collection Pipeline — Tracing, Validation & Route Index

## Handoff Plan for Opus 4.6 Agent

**Problem Statement:** The data collection pipeline lacks observability. When a request enters the system, there is no reliable way to know (1) what format data takes at each stage, (2) which route it traveled through the pipeline, or (3) what routes are even available. This makes debugging, auditing, and extending the system unreliable.

**Three deliverables:**
1. **Tracing** — end-to-end request tracing from intent → executor → scraper → ingest → DB
2. **Validation** — schema enforcement at every boundary crossing
3. **Route Index** — a queryable registry of all data collection routes and their contracts

---

## Phase 1: Build the Route Index (do this FIRST)

**Why first:** You cannot trace or validate what you haven't mapped. The route index is the source of truth that tracing and validation both depend on.

### 1.1 Define what a "route" is

A route is a complete path from an agent intent to a database write. Each route has:

```
intent (enum) → executor handler (function) → scraper adapter (class) → signal type → DB table
```

### 1.2 Audit every route that currently exists

Read these files in order and build the map:

| Step | File | What to extract |
|------|------|-----------------|
| 1 | `agent_interface/schemas.py` | All `intent` enum values — these are the entry points |
| 2 | `agent_interface/executor.py` | The `execute()` dispatch — which intent maps to which `_execute_*` handler |
| 3 | Each `_execute_*` handler in `executor.py` | Which scraper adapter(s) it calls, what args it passes, what it expects back |
| 4 | `scrapers/base.py` | The `ScraperSignal` dataclass — the universal return type from all scrapers |
| 5 | Each adapter in `scrapers/` | What the adapter actually returns (fields populated, fields left empty) |
| 6 | `backend/ingest.py` | How `ScraperSignal` maps to DB writes (which tables, which columns) |
| 7 | `backend/database.py` | The 14 SQLAlchemy models — the final shape of data at rest |

### 1.3 Produce the route index as a Python module

Create `pipeline/route_index.py` with a declarative registry:

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class RouteContract:
    intent: str                          # e.g. "job_posting_volume"
    executor_handler: str                # e.g. "_execute_job_posting_volume"
    scraper_adapter: str                 # e.g. "JobSpyAdapter"
    source_key: str                      # e.g. "jobspy" (matches api_sources table)
    input_schema: dict                   # JSON Schema of what the executor sends to the scraper
    output_fields: list[str]             # Which ScraperSignal fields this route populates
    db_table: str                        # e.g. "signals"
    db_columns_written: list[str]        # Which columns actually get values
    freshness_threshold_days: int        # From schemas.py thresholds
    daily_limit: int                     # From api_sources
    status: str                          # "live" | "unwired" | "suggested"
    fallback_routes: list[str] = field(default_factory=list)  # Alternative source_keys

ROUTES: dict[str, list[RouteContract]] = {
    # keyed by intent, value is list of routes (primary + fallbacks)
}
```

### 1.4 Expose the route index via API

Add `GET /api/pipeline/routes` to `server.py` that returns the full registry as JSON. This becomes the single source of truth for what the system can do.

Add `GET /api/pipeline/routes/{intent}` for per-intent detail.

### 1.5 Known routes to document (from the architecture)

**LIVE routes (executor currently calls these):**

| Intent | Handler | Adapter | Source Key | DB Target |
|--------|---------|---------|------------|-----------|
| `poi_chain_locations` | `_execute_poi_chain` | `AllThePlacesAdapter` | `atp_geojson` | `stores` |
| `poi_local_density` | `_execute_poi_local` | `OvertureLocalAdapter` | `overture_s3` | `local_employers` |
| `wage_baseline` | `_execute_wage_baseline` | `BLSAdapter` | `bls_v1` | `wage_index` |
| `job_posting_volume` | `_execute_job_posting_volume` | `careers_api` | `careers_workday` | `signals` |
| `job_posting_volume` | `_execute_job_posting_volume` | `JobSpyAdapter` | `jobspy` | `signals` |
| `sentiment_check` | `_execute_sentiment_check` | `RedditAdapter` | `reddit_json` / `reddit_oauth` | `signals` |
| `score_refresh` | `_execute_score_refresh` | *(internal)* | *(none)* | `scores` |
| `data_quality_audit` | `_execute_data_quality_audit` | *(internal)* | *(none)* | *(read-only)* |
| `campaign_status` | `_execute_campaign_status` | *(internal)* | *(none)* | *(read-only)* |
| `discovery_scan` | `_execute_discovery_scan` | *(internal)* | *(none)* | *(read-only)* |

**UNWIRED routes (adapter exists, executor doesn't call it):**

| Intent (would serve) | Adapter | Source Key | What's missing |
|----------------------|---------|------------|----------------|
| `poi_chain_locations` | `OSMAdapter` | `overpass_api` | Not wired as fallback in `_execute_poi_chain` |
| `sentiment_check` | `ReviewsAdapter` | `gmaps_scraper` | Not called in `_execute_sentiment_check` |
| `poi_chain_locations` | `GoogleMapsStoreFinder` | `gmaps_playwright` | Not wired into executor at all |

**MISSING routes (no adapter):**

| Intent (would serve) | Source | Source Key (suggested) |
|----------------------|--------|----------------------|
| `ref_brands` enrichment | Wikidata SPARQL | `wikidata_sparql` |

---

## Phase 2: Add Tracing

**Goal:** Every data collection request gets a trace ID that follows it from intent through to DB write. After execution, you can query "what happened to trace X?" and get the full story.

### 2.1 Create the trace context

Create `pipeline/tracing.py`:

```python
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

@dataclass
class TraceSpan:
    span_id: str
    name: str                            # e.g. "executor._execute_poi_chain"
    started_at: datetime
    ended_at: Optional[datetime] = None
    status: str = "running"              # running | success | failed | skipped
    input_summary: Optional[dict] = None # key fields only, not full payload
    output_summary: Optional[dict] = None
    error: Optional[str] = None
    children: list["TraceSpan"] = field(default_factory=list)

@dataclass
class PipelineTrace:
    trace_id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    intent: str = ""
    brand: str = ""
    region: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    spans: list[TraceSpan] = field(default_factory=list)
    route_taken: Optional[str] = None    # source_key of the route that ran
    records_written: int = 0
    freshness_stamped: bool = False
```

### 2.2 Instrument at four points

Tracing requires instrumentation at exactly four boundaries. No more, no less.

**Boundary 1 — Executor dispatch** (`agent_interface/executor.py`)
- At the top of `execute()`: create `PipelineTrace`, open root span
- At the return: close root span, log trace

**Boundary 2 — Scraper call** (inside each `_execute_*` handler)
- Before calling adapter: open child span, capture input args
- After adapter returns: close span, capture `ScraperSignal` field summary (count of non-null fields, record count — NOT full data)

**Boundary 3 — Ingest** (`backend/ingest.py`)
- Before DB write: open child span
- After commit: close span, capture records_written count

**Boundary 4 — Freshness stamp** (wherever `source_freshness` is updated)
- Log that freshness was stamped for this intent/brand/region combo

### 2.3 Store traces

**Option A (recommended for now):** Append traces as JSON lines to `data/pipeline_traces/{date}.jsonl`. Same pattern as `openclaw_logs/`. Zero DB schema changes.

**Option B (later):** Add a `pipeline_traces` table to `tracker.db`. Only do this if you need to query traces via SQL for debugging.

### 2.4 Expose traces via API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/pipeline/traces?date=YYYY-MM-DD` | All traces for a date |
| `GET /api/pipeline/traces/{trace_id}` | Single trace with full span tree |
| `GET /api/pipeline/traces?intent=X&status=failed` | Filter by intent/status |

### 2.5 What a trace should look like when complete

```json
{
  "trace_id": "a3f8c1d2e4b7",
  "intent": "job_posting_volume",
  "brand": "starbucks",
  "region": "austin_tx",
  "created_at": "2025-03-20T14:23:01Z",
  "route_taken": "careers_workday",
  "records_written": 47,
  "freshness_stamped": true,
  "spans": [
    {
      "name": "executor.execute",
      "status": "success",
      "started_at": "...",
      "ended_at": "...",
      "children": [
        {
          "name": "prevalidate",
          "status": "success",
          "output_summary": {"passed_gates": ["freshness", "budget", "terms"]}
        },
        {
          "name": "careers_api.scrape",
          "status": "success",
          "input_summary": {"brand": "starbucks", "region": "austin_tx", "keywords": ["barista"]},
          "output_summary": {"signal_count": 47, "fields_populated": ["store_num", "value", "detail"]}
        },
        {
          "name": "ingest.write_signals",
          "status": "success",
          "output_summary": {"rows_inserted": 47, "rows_updated": 0}
        },
        {
          "name": "freshness.stamp",
          "status": "success"
        }
      ]
    }
  ]
}
```

---

## Phase 3: Add Validation

**Goal:** Every boundary crossing enforces a schema. Bad data gets caught at the boundary, not three layers later as a confusing DB error.

### 3.1 Define schemas at three boundaries

**Boundary A — Executor input** (what the LLM/agent sends)
- Already partially covered by `agent_interface/validator.py`
- Audit: does `validator.py` actually enforce types, required fields, and enum membership for every intent?
- Gap likely: validator checks existence but not shape/type of fields

**Boundary B — Scraper output** (what the adapter returns)
- This is the biggest gap. `ScraperSignal` is a loose dataclass — adapters can return any combination of fields
- Create per-intent output schemas that specify which `ScraperSignal` fields must be non-null for that intent
- Example: `poi_chain_locations` MUST return `store_num`, `source`, `signal_type`, and `lat`/`lng` (or geocodable address)

**Boundary C — Ingest input** (what gets written to DB)
- `ingest.py` should validate that the signal maps to a valid DB model before writing
- Check: does the store_num exist in `stores`? Is the signal_type a known enum? Is the value in a sane range?

### 3.2 Implementation approach

Create `pipeline/validation.py`:

```python
from dataclasses import dataclass

@dataclass
class ValidationResult:
    valid: bool
    errors: list[str]
    warnings: list[str]

# Per-intent output contracts
SCRAPER_OUTPUT_CONTRACTS = {
    "poi_chain_locations": {
        "required_fields": ["store_num", "source", "signal_type"],
        "required_geo": True,  # must have lat/lng or address
        "value_type": "location_data",
    },
    "job_posting_volume": {
        "required_fields": ["store_num", "source", "signal_type", "value"],
        "required_geo": False,
        "value_type": "numeric_count",
    },
    "sentiment_check": {
        "required_fields": ["source", "signal_type", "value"],
        "required_geo": False,
        "value_type": "sentiment_score",
    },
    "wage_baseline": {
        "required_fields": ["source", "signal_type", "value"],
        "required_geo": False,
        "value_type": "wage_numeric",
    },
}

def validate_scraper_output(intent: str, signals: list) -> ValidationResult:
    """Validate ScraperSignal list against the contract for this intent."""
    contract = SCRAPER_OUTPUT_CONTRACTS.get(intent)
    if not contract:
        return ValidationResult(valid=False, errors=[f"No contract for intent: {intent}"], warnings=[])
    # ... field checks, type checks, range checks
```

### 3.3 Wire validation into the pipeline

- In each `_execute_*` handler, after the scraper returns and before ingest:
  ```python
  result = validate_scraper_output(intent, signals)
  if not result.valid:
      trace.current_span.status = "failed"
      trace.current_span.error = "; ".join(result.errors)
      return  # don't write bad data
  ```
- Log validation failures to the trace (Phase 2 gives you this for free)
- Validation warnings (non-fatal) also go on the trace

### 3.4 Validate the route index itself

On startup, run a self-check:
- Every intent in `schemas.py` has at least one route in the index
- Every route's `scraper_adapter` class exists and is importable
- Every route's `db_table` exists in the SQLAlchemy metadata
- Every route's `source_key` exists in `api_sources`
- Flag unwired routes that have adapters but no executor handler

Expose: `GET /api/pipeline/health` returns the self-check results.

---

## Phase 4: Integration & Operator Visibility

### 4.1 Add a pipeline status panel to the OpenClaw dashboard

The `frontend/openclaw.html` dashboard currently lacks freshness visibility (noted in known issues). The pipeline tracing system gives you the data to fix this:

- **Route coverage table:** For each intent × brand × region, show: last trace ID, last status, last run time, freshness state
- **Failed traces feed:** Most recent failures with one-click to full trace
- **Route index browser:** Expandable list of all routes, their contracts, and their status (live/unwired/suggested)

### 4.2 Add trace context to OpenClaw sessions

When the orchestrator runs a session, each `query` action should include the trace_id in its result fed back to the LLM. This lets the session log link directly to pipeline traces.

### 4.3 Add a CLI debug command

```bash
python -m pipeline.debug trace <trace_id>     # Pretty-print a trace
python -m pipeline.debug routes                # Print route index
python -m pipeline.debug routes --intent X     # Detail for one intent
python -m pipeline.debug validate              # Run startup self-check
python -m pipeline.debug dry-run --intent X --brand Y --region Z  # Simulate without writing
```

---

## Execution Order for the Opus 4.6 Agent

**Step 1: Read the code.** Before writing anything, read these files end-to-end:
1. `agent_interface/schemas.py` — all enums and types
2. `agent_interface/executor.py` — the full dispatch logic
3. `scrapers/base.py` — the ScraperSignal dataclass
4. `backend/ingest.py` — how signals become DB rows
5. `backend/database.py` — all 14 models
6. `agent_interface/validator.py` — existing validation
7. `openclaw/prevalidate.py` — existing pre-validation gates

**Step 2: Build the route index** (Phase 1). This is pure documentation-as-code. No existing behavior changes. Verify it by cross-referencing every `_execute_*` handler against the index.

**Step 3: Add tracing** (Phase 2). Instrument the four boundaries. Use JSONL storage. Add the API endpoints. Test with a single `job_posting_volume` run and verify the trace captures the full path.

**Step 4: Add validation schemas** (Phase 3). Start with the three highest-traffic intents (`poi_chain_locations`, `job_posting_volume`, `sentiment_check`). Wire validation into the executor between scraper return and ingest. Verify that intentionally bad data gets caught.

**Step 5: Self-check and dashboard** (Phase 4). Add startup validation. Add the pipeline panel to `openclaw.html`. Wire trace IDs into session results.

---

## Files to Create

| File | Purpose |
|------|---------|
| `pipeline/__init__.py` | Package init |
| `pipeline/route_index.py` | Declarative route registry |
| `pipeline/tracing.py` | Trace and span dataclasses + context manager |
| `pipeline/validation.py` | Per-boundary schema validation |
| `pipeline/health.py` | Startup self-check |
| `pipeline/debug.py` | CLI debugging tool |

## Files to Modify

| File | Change |
|------|--------|
| `agent_interface/executor.py` | Instrument with tracing at dispatch + per-handler level |
| `backend/ingest.py` | Instrument with tracing at write boundary |
| `server.py` | Add `/api/pipeline/*` endpoints (routes, traces, health) |
| `frontend/js/openclaw.js` | Add pipeline status panel |
| `frontend/openclaw.html` | Add pipeline section to dashboard layout |

## Files NOT to Touch

| File | Reason |
|------|--------|
| `scrapers/*` | Adapters are fine — the problem is the pipeline around them, not the adapters themselves |
| `openclaw/orchestrator.py` | Agent loop works — we're adding visibility, not changing behavior |
| `backend/scoring/*` | Scoring is downstream of collection, out of scope |
| `spiritpool/` | Explicitly out of scope per project constraints |

---

## Success Criteria

The pipeline fix is done when:

1. **Any operator can answer "what routes exist?"** by hitting `GET /api/pipeline/routes` and getting a complete, machine-readable registry
2. **Any failed collection can be debugged** by looking up its trace ID and seeing exactly where in the pipeline it failed and why
3. **Bad data cannot silently enter the DB** — validation at the scraper→ingest boundary catches malformed signals before they're written
4. **The system knows what it doesn't know** — the startup self-check flags intents with no routes, routes with missing adapters, and source keys with no executor handler
