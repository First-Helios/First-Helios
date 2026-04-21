# First-Helios Developer Playbook

## Overview


First-Helios is now a **backend-only** data and API platform for labor market intelligence in Austin, TX. It collects, normalizes, and serves data via a documented API. The frontend and host management are now in separate repositories.

**Stack:**
- **Backend:** Flask (`server.py`), Gunicorn (any Linux host)
- **Scheduler:** APScheduler via `collector_main.py` (runs separately from the web server)
- **Database:** PostgreSQL (`helios` DB on localhost:5432, connection via `DATABASE_URL` in `.env`)

**Frontend:** See [First-Helios_Frontend](https://github.com/4Fortune8/First-Helios_Frontend)
**Host/infra:** See [First-Helios_Orangepi_Host](https://github.com/4Fortune8/First-Helios_Orangepi_Host)

---


## Repository Layout

```
server.py                    Flask app (API server)
collector_main.py            Standalone scheduler entry point
collectors/                  Data collection adapters
core/                        Core pipeline, scoring, scheduler
postings/                    Job posting models + ingest pipeline
events/                      Events hub
config/                      Config files (YAML)
scripts/                     One-time data population scripts
notebooks/                   Data exploration notebooks
data/                        Data caches, reference, and state
```

**Frontend and host management have moved to their own repositories:**
- UI: [First-Helios_Frontend](https://github.com/4Fortune8/First-Helios_Frontend)
- Host/infra: [First-Helios_Orangepi_Host](https://github.com/4Fortune8/First-Helios_Orangepi_Host)

---


## The Three Write Paths

These are the only sanctioned paths for writing employer, posting, and event records. Never insert directly into the underlying tables.

### 1. Employer records

```
core/ingest_layer.py:ingest_employer(signal, region)
```

Pipeline: normalize → fingerprint → upsert `brand_groups` → upsert `local_employers`

Call this from any adapter that collects employer/facility data (overture, alltheplaces, osm, etc.).

### 2. Job postings

```
postings/ingest.py:ingest_job_posting(signal, region)
```

Pipeline: normalize → geocode → compute H3 → match to LocalEmployer → upsert `job_postings`

Required fields on the `ScraperSignal`:

| Field | Notes |
|---|---|
| `signal_type` | Must be `"listing"` |
| `company` | Employer name string |
| `address` | Street address (used for geocoding) |
| `is_remote` | Boolean |
| `posted_date` | datetime |
| `external_path` or `job_url` | Source URL |

Dedup key: `(source, external_id)` — unique constraint enforced in DB.

Unmatched postings have `local_employer_id=NULL`. Fully remote postings have `h3_r7=NULL`. Both are valid states.

### 3. Events

```
events/ingest.py
```

Pipeline: normalize → resolve venue → compute H3 → upsert `venues` → upsert `events`

Event collectors live in `collectors/events/` and are auto-discovered via the `@event_collector` decorator in `collectors/events/registry.py`. The scheduler imports all modules in that directory at startup and registers their cron schedules.

Dedup key: `(source, external_id)` — unique constraint enforced in DB.

---

## Rate Manager Protocol

Every external HTTP request must be gated through `core/rate_manager.py`.

```python
from core.rate_manager import rate_manager

if not rate_manager.can_request(source_key):
    return []

try:
    response = requests.get(url, ...)
    rate_manager.log_request(source_key, success=True)
except Exception as e:
    rate_manager.log_request(source_key, success=False)
    raise
```

`log_request()` must be called even on failure. New sources must be registered in `API_SOURCE_REGISTRY` inside `core/rate_manager.py`.

---

## Industry Rotation

`serpapi_jobs` and `jobicy` rotate through `config/search_rotation.yaml` (20 industry entries). Each entry has:

```yaml
- key: healthcare
  serpapi_query: "healthcare jobs Austin TX"
  jobicy_tag: healthcare
```

In your adapter:

```python
from collectors.rotation import next_entry

entry = next_entry(source_key, industries)
```

This advances the rotation slot and returns the next entry. State is file-persisted so it survives restarts.

---

## Adding a New Scraper

### 1. Create the adapter file

Place at `collectors/<subcategory>/<source>_adapter.py`.

Subcategories: `job_boards`, `labor_data`, `employer_data`, `sentiment`, `events`

```python
from collectors.base import BaseScraper, ScraperSignal
from core.rate_manager import rate_manager
import logging, requests, time

logger = logging.getLogger(__name__)
SOURCE_KEY = "mysource"

class MySourceAdapter(BaseScraper):
    def scrape(self, region: str) -> list[ScraperSignal]:
        if not rate_manager.can_request(SOURCE_KEY):
            logger.warning("[MySource] Daily budget exhausted")
            return []

        t0 = time.time()
        try:
            resp = requests.get("https://api.example.com/data", timeout=10)
            resp.raise_for_status()
            rate_manager.log_request(
                source_key=SOURCE_KEY,
                request_type="data_fetch",
                url=resp.url,
                status_code=resp.status_code,
                success=True,
                latency_ms=int((time.time() - t0) * 1000),
                data_items=len(resp.json().get("items", [])),
            )
            return self._parse(resp.json(), region)
        except Exception as exc:
            rate_manager.log_request(
                source_key=SOURCE_KEY, request_type="data_fetch",
                success=False, error_message=str(exc),
                latency_ms=int((time.time() - t0) * 1000),
            )
            logger.error("[MySource] Fetch failed: %s", exc)
            return []
```

### 2. Register the source

Add an entry to `API_SOURCE_REGISTRY` in `core/rate_manager.py`:

```python
{
    "source_key": "mysource",
    "display_name": "My Source",
    "base_url": "https://api.example.com/",
    "auth_type": "api_key",
    "daily_limit": 500,
    "min_delay_seconds": 1.0,
    "reset_hour_utc": 0,
},
```

### 3. Wire up signal routing

- Labor/scoring data → `core.ingest.ingest_signals(signals, region)`
- Employer records → `core.ingest_layer.ingest_employer(signal, region)`
- Job postings → `postings.ingest.ingest_job_posting(signal, region="austin_tx")`

### 4. Add a scheduler job

In `core/scheduler.py`:

```python
def _run_mysource() -> None:
    try:
        from collectors.job_boards.mysource_adapter import MySourceAdapter
        logger.info("[Scheduler] Running MySource fetch")
        signals = MySourceAdapter().scrape("austin_tx")
        logger.info("[Scheduler] MySource: %d signals", len(signals))
    except Exception as e:
        logger.error("[Scheduler] MySource job failed: %s", e)
```

Then wire it with `scheduler.add_job(_run_mysource, ...)` and add a YAML entry in `config/scheduler.yaml`:

```yaml
mysource:
  enabled: true
  trigger: cron
  cron:
    hour: 10
    minute: 0
```

---

## Adding a New Event Collector

Event collectors use a decorator-based plugin system and are auto-discovered by the scheduler at startup.

### 1. Create the collector file

Place at `collectors/events/<source>.py`:

```python
from collectors.events.registry import event_collector
import logging, requests

logger = logging.getLogger(__name__)

@event_collector("mysource", schedule="0 */6 * * *")
class MySourceCollector:
    """Collects events from MySource."""

    def collect(self, region: str = "austin_tx") -> list[dict]:
        # Fetch and return list of event dicts with keys:
        # source, external_id, title, description, start_time, end_time,
        # lat, lng, raw_venue_name, raw_address, category, region, ...
        return events

    def run(self, region: str = "austin_tx") -> int:
        events = self.collect(region)
        # Ingest via events/ingest.py
        return len(events)
```

The `schedule` parameter is a 5-field cron string: `"minute hour dom month dow"`.

### 2. Register in the event sources catalog

Add an entry to `config/event_sources.yaml` under the appropriate tier.

### 3. That's it

No manual scheduler wiring needed. The `@event_collector` decorator registers the class automatically, and `core/scheduler.py` auto-discovers all modules in `collectors/events/` at startup and creates scheduler jobs from their declared schedules.

---

## Adding a Flask Endpoint

All routes live in `server.py`. Pattern:

```python
@app.route('/api/my-endpoint')
def my_endpoint():
    region = request.args.get('region', 'austin_tx')
    limit  = min(int(request.args.get('limit', 50)), 200)

    session = get_session()
    try:
        results = session.execute(
            text("SELECT ... FROM ... WHERE region = :region LIMIT :limit"),
            {"region": region, "limit": limit}
        ).fetchall()
        return jsonify({"status": "ok", "count": len(results), "items": [dict(r) for r in results]})
    except Exception as exc:
        logger.error("/api/my-endpoint error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
    finally:
        session.close()
```

Always return `{"status": "ok", ...}` on success and `{"status": "error", "message": "..."}` with an HTTP error code on failure.

---

## Adding a Map Mode (Frontend)

> **⚠️ Frontend lives in a sibling repo:** `/home/fortune/CodeProjects/First-Helios_Frontend/`
> (GitHub: [First-Helios_Frontend](https://github.com/4Fortune8/First-Helios_Frontend))
> All paths below are **relative to that repo**, NOT this one. This repo is backend-only.

### Four files to touch (in First-Helios_Frontend)

**`index.html`**
- Add `<button id="mode-<name>" class="mode-btn">` in `#mode-switcher`
- Add `<div id="<name>-controls" class="controls-group" style="display:none">` for filters
- Add `<div id="<name>-sidebar" class="sidebar" style="display:none">` in `#right-panel`
- Add `<script src="js/<name>.js">` before `app.js`

**`js/<name>.js`** — IIFE module:

```javascript
(function () {
    'use strict';

    var _layer = null;

    function refresh() { ... }
    function clear() { ... }
    function onZoom() { ... }

    window.myMode = { refresh: refresh, clear: clear, onZoom: onZoom };
})();
```

**`js/app.js`** — add to `switchMode()`:
- Toggle controls/sidebar visibility
- Call `window.myMode.refresh()` on enter
- Call `window.myMode.clear()` on exit
- Add `map.on('zoomend')` handler if needed

**`css/style.css`** — follow the existing card pattern.

---



## Database Conventions

**Session management** — always close in `finally`:

```python
session = get_session()
try:
    ...
finally:
    session.close()
```

**Upsert everywhere** — `INSERT ... ON CONFLICT DO UPDATE`, never check-then-insert.

**H3 cells** — pre-computed at ingest, never at query time. Never call `h3.latlng_to_cell()` outside the ingest pipeline.

**Fingerprinting** — use `core.normalizer.make_fingerprint()`. Stable lowercase slug derived from employer name. The primary dedup key across `brand_groups` and the matching key between postings and employers.

**NULL is valid:**
- `local_employer_id=NULL` on a posting → unmatched (not an error)
- `h3_r7=NULL` on a posting → fully remote (not an error)

**Schema changes** — `create_all()` does not add columns to existing tables. Write an explicit `ALTER TABLE` or a migration script in `scripts/`.

**ORM vs raw SQL** — use ORM for simple lookups; `text()` or raw SQL for complex aggregations.

---

## Testing

```bash
pytest tests/
```

Key test files:
- `tests/test_ingest_layer.py` — employer write path
- `tests/test_listings_ingest.py` — job posting write path (postings layer)
- `tests/test_scorer.py` — scoring engine

Use a real test DB or in-memory SQLite. Do not mock the database in integration tests. Fixture responses live in `tests/fixtures/`.

---

## Code Style

**Python:**
- Type hints on all function signatures
- `logger = logging.getLogger(__name__)` at module level
- `[ClassName]` prefix in all log messages: `logger.info("[MySource] fetched %d signals", n)`
- Docstrings on public functions

**JavaScript:**
- `var` not `let`/`const`
- Function declarations not arrow functions
- `_privateName` prefix for private scope
- No `console.log` in committed code

**File naming:**
- Collectors: `<source>_adapter.py`
- Frontend JS modules: `<mode>.js`

---


## Key Invariants — Never Violate These

1. All employer writes go through `core/ingest_layer.py:ingest_employer()`
2. All job posting writes go through `postings/ingest.py:ingest_job_posting()`
3. All external HTTP requests must call `rate_manager.can_request()` before and `rate_manager.log_request()` after (even on failure)
4. H3 cells are computed at ingest — never at query time
5. Fingerprints come from `core.normalizer.make_fingerprint()` — never roll your own slug
6. Scheduler jobs wrap their body in `try/except Exception` — uncaught exceptions silently kill the job
7. Jobs that update scores must call `compute_all_scores(region)` at the end of the job function

---

## Cross-Repo Architecture

This repository is now **backend-only**. For the full platform:

- **Frontend:** [First-Helios_Frontend](https://github.com/4Fortune8/First-Helios_Frontend)
- **Host/infra:** [First-Helios_Orangepi_Host](https://github.com/4Fortune8/First-Helios_Orangepi_Host)

See those repos for UI, deployment, and systemd/nginx configuration.
