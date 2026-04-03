# First-Helios Developer Playbook

## Overview

First-Helios is a labor market intelligence platform for the Austin, TX MSA. It collects data from job boards, labor statistics APIs, employer databases, and sentiment sources, normalizes it, and surfaces it through a map-based frontend.

The stack is:
- **Backend:** Flask (`server.py`), served by Gunicorn on an OPi5
- **Scheduler:** APScheduler via `collector_main.py` (runs separately from the web server)
- **Database:** PostgreSQL (`helios` DB on localhost:5432, connection via `DATABASE_URL` in `.env`)
- **Frontend:** Plain HTML/CSS/JS — no build step, no npm

---

## Repository Layout

```
server.py                    Flask app (port 8765)
collector_main.py            Standalone scheduler entry point
collectors/
  base.py                    BaseScraper, ScraperSignal dataclass
  cache.py                   File cache utilities
  geocoding.py               Nominatim + facility index overrides
  rotation.py                Industry tag rotation for multi-query scrapers
  job_boards/                jobspy, jobicy, serpapi, usajobs, workday_gov,
                             activejobs, juju, theirstack adapters
  labor_data/                bls, qcew, cbp, nlrb, warn adapters
  employer_data/             overture, alltheplaces, osm adapters
  sentiment/                 reddit, reviews adapters
  events/                    ticketmaster, eventbrite, meetup, do512,
                             austin_city_calendar, austintexas_org
                             + registry.py (decorator-based plugin system)
core/
  database.py                SQLAlchemy models (26+ tables), init, get_engine, get_session
  ingest.py                  ScraperSignal → signals/scores tables
  ingest_layer.py            Employer write path (normalize → fingerprint → upsert)
  normalizer.py              Zero-DB normalization upstream of ingest_layer
  scheduler.py               APScheduler job definitions (29 scheduled jobs)
  rate_manager.py            Centralized API rate tracking
  baseline.py                Labor market baseline computation
  targeting.py               Targeting score computation
  scoring/                   engine.py, careers.py, sentiment.py, wage.py
  models/                    Reference + mobility graph models
postings/
  models.py                  JobPosting SQLAlchemy model
  ingest.py                  Job posting write path (normalize → geocode → H3 → match → upsert)
  matcher.py                 Match posting to LocalEmployer by fingerprint + proximity
  config.py                  TTL, proximity threshold, match confidence settings
events/
  models.py                  Venue, Event, EventInteraction SQLAlchemy models
  ingest.py                  Event write path
  routes.py                  Events API endpoints
config/
  loader.py                  Config loading utilities
  scheduler.yaml             Scheduled job intervals + enabled flags
  event_sources.yaml         Event source catalog (6 live, 14 future)
  search_rotation.yaml       20 industry rotation entries for multi-query scrapers
scripts/                     One-time data population scripts
dev/                         opi5_setup.sh, update.sh, sync_from_opi.sh
frontend/
  index.html
  css/style.css
  js/                        app.js, jobfinder.js, and per-mode modules
```

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

### Four files to touch

**`frontend/index.html`**
- Add `<button id="mode-<name>" class="mode-btn">` in `#mode-switcher`
- Add `<div id="<name>-controls" class="controls-group" style="display:none">` for filters
- Add `<div id="<name>-sidebar" class="sidebar" style="display:none">` in `#right-panel`
- Add `<script src="js/<name>.js">` before `app.js`

**`frontend/js/<name>.js`** — IIFE module:

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

**`frontend/js/app.js`** — add to `switchMode()`:
- Toggle controls/sidebar visibility
- Call `window.myMode.refresh()` on enter
- Call `window.myMode.clear()` on exit
- Add `map.on('zoomend')` handler if needed

**`frontend/css/style.css`** — follow the existing card pattern.

---

## Frontend Conventions

- **No build step** — plain HTML/CSS/JS, no npm, no bundler
- **`var` not `let`/`const`** — codebase convention, stay consistent
- **Function declarations**, not arrow functions
- **`_privateName`** prefix for module-private functions/variables
- **No `console.log`** in committed code
- **Shared map:** `window.sharedMap` — created in `app.js`, accessed by all modules
- **HTML escaping:** always use `_esc()` when inserting API data into `innerHTML`

**H3 resolution by layer:**
- `job_postings`: `h3_r7`, `h3_r8` only — clamp jobfinder resolution to `{7, 8}`
- `local_employers`: `h3_r6` through `h3_r9`

**Color palette:**

| Use | Color |
|---|---|
| Brands / stress | `#f0a500` amber |
| Local employers | `#6c5ce7` purple |
| Job postings | `#4ecca3` teal |
| Links | `#4a9eff` blue |

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
