# PLAYBOOK — First Helios

Development workflows, conventions, and design decisions. Read this before adding new scrapers, map modes, or API endpoints.

---

## Contents

1. [Architecture in One Page](#architecture-in-one-page)
2. [Adding a New Scraper](#adding-a-new-scraper)
3. [Adding a New Job Posting Source](#adding-a-new-job-posting-source)
4. [Adding a New API Endpoint](#adding-a-new-api-endpoint)
5. [Adding a New Map Mode](#adding-a-new-map-mode)
6. [Frontend Conventions](#frontend-conventions)
7. [Database Conventions](#database-conventions)
8. [Rate Manager Protocol](#rate-manager-protocol)
9. [Scheduler Conventions](#scheduler-conventions)
10. [Testing](#testing)
11. [Code Style](#code-style)

---

## Architecture in One Page

```
Scrapers → ScraperSignal → backend/ingest.py → signals / scores / wage_index
                                             ↘
        → JobPosting    → listings/ingest.py → job_postings
                                             ↘
Overture POI            → ingest_layer.py   → local_employers / brand_groups

All employer data: single write path through ingest_layer.py
All job postings:  single write path through listings/ingest.py

server.py exposes Flask API
frontend/ is a static SPA — no build step, plain JS + Leaflet
```

**Key invariants:**
- Never write directly to `local_employers` or `brand_groups` — always go through `backend/ingest_layer.py`
- Never write directly to `job_postings` — always go through `listings/ingest.py`
- Never call external APIs without going through `rate_manager.can_request()` + `rate_manager.log_request()`
- All coordinates produce H3 cells at ingest time — never compute H3 at query time

---

## Adding a New Scraper

### 1. Create the adapter file

Place in `scrapers/your_source_adapter.py`. Extend `BaseScraper` or write a standalone function — both patterns exist:

```python
# scrapers/example_adapter.py
from scrapers.base import BaseScraper, ScraperSignal
from backend.rate_manager import rate_manager
import time, requests, logging

logger = logging.getLogger(__name__)
SOURCE_KEY = "example_api"   # must match an entry in rate_manager.API_SOURCE_REGISTRY


class ExampleAdapter(BaseScraper):
    def scrape(self, region: str) -> list[ScraperSignal]:
        if not rate_manager.can_request(SOURCE_KEY):
            logger.warning("[Example] Daily budget exhausted")
            return []

        t0 = time.time()
        try:
            resp = requests.get("https://example.com/api/data", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            rate_manager.log_request(
                source_key=SOURCE_KEY,
                request_type="data_fetch",
                url=resp.url,
                status_code=resp.status_code,
                success=True,
                latency_ms=int((time.time() - t0) * 1000),
                data_items=len(data.get("items", [])),
            )
            return self._parse(data, region)
        except Exception as exc:
            rate_manager.log_request(
                source_key=SOURCE_KEY, request_type="data_fetch",
                success=False, error_message=str(exc),
                latency_ms=int((time.time() - t0) * 1000),
            )
            logger.error("[Example] Fetch failed: %s", exc)
            return []

    def _parse(self, data, region) -> list[ScraperSignal]:
        signals = []
        for item in data.get("items", []):
            signals.append(ScraperSignal(
                source="example_api",
                signal_type="stress",     # or "listing", "sentiment", "review"
                chain=item.get("brand"),
                region=region,
                # ... other fields
            ))
        return signals
```

### 2. Register the source in rate_manager

Add an entry to `API_SOURCE_REGISTRY` in `backend/rate_manager.py`:

```python
{
    "source_key": "example_api",
    "display_name": "Example Data API",
    "base_url": "https://example.com/api/",
    "auth_type": "none",          # "none" | "api_key" | "oauth" | "browser"
    "daily_limit": 1000,          # hard cap; use 10000 for uncapped sources
    "min_delay_seconds": 1.0,
    "reset_hour_utc": 0,
    "notes": "Brief description of rate limits and data source.",
},
```

The registry is seeded into `api_sources` table on server startup. The `daily_limit` is authoritative for `can_request()` checks.

### 3. Wire into the scheduler

Add a job function and `scheduler.add_job()` call in `backend/scheduler.py` — see existing jobs for the pattern. Add a cron entry to `config/scheduler.yaml` with `enabled: true`, `trigger: cron`, and a `cron:` block. The scheduler reads this file at startup; hardcoded defaults in `add_job()` are only used if your key is absent.

### 4. Ingest the signals

Call `backend.ingest.ingest_signals(signals, region)` — this normalizes and stores to `signals` table and optionally triggers score recompute.

---

## Adding a New Job Posting Source

Job posting sources write to `job_postings` via `listings/ingest.py`, not the `signals` table.

### 1. Produce `ScraperSignal` with `signal_type = "listing"`

Required metadata keys:
```python
ScraperSignal(
    source="your_source",
    signal_type="listing",
    source_url="https://...",          # direct apply link
    role_title="Software Engineer",
    wage_min=80000.0,
    wage_max=120000.0,
    wage_period="yearly",              # "hourly" | "yearly"
    metadata={
        "company": "Acme Corp",        # raw employer name
        "address": "123 Main St, Austin TX",  # or None for remote
        "lat": 30.2672,                # optional; skips geocoding if provided
        "lng": -97.7431,
        "is_remote": False,            # True | False | None
        "posted_date": "2026-03-01",
        "external_path": "unique-id-from-source",  # or "job_url" for JobSpy
    },
)
```

### 2. Call `ingest_job_posting`

```python
from listings.ingest import ingest_job_posting
for signal in signals:
    ingest_job_posting(signal, region="austin_tx")
```

`ingest_job_posting` handles: normalization → geocoding → H3 cells → employer matching → upsert.

### 3. Dedup key

The unique constraint is `(source, external_id)`. `external_id` is derived automatically in `listings/ingest.py`:
- `careers_api` source → uses `metadata["external_path"]`
- `jobspy` source → uses `metadata["job_url"]` (hashed if > 255 chars)
- All others → content hash of employer + title + address + date

### 4. File cache pattern (for rate-limited feeds)

If the source publishes a feed you should not poll more than once per hour, use the Jobicy pattern: write a `_read_cache()` / `_write_cache()` pair that reads/writes `data/<source>_cache.json` with a `fetched_at` timestamp. Check the cache at the top of `scrape()` before any rate-manager logic.

---

## Adding a New API Endpoint

All routes live in `server.py`. The file is organized into sections by feature area. Add your route in the appropriate section, or create a new section with a comment header.

Pattern for a new GET endpoint:

```python
@app.route('/api/your-endpoint')
def your_endpoint():
    region = request.args.get('region', 'austin_tx')
    limit  = min(int(request.args.get('limit', 50)), 200)

    try:
        session = get_session()
        try:
            results = session.query(YourModel).filter(
                YourModel.region == region,
                YourModel.is_active.is_(True),
            ).limit(limit).all()

            return jsonify({
                "status": "ok",
                "count": len(results),
                "items": [r.to_dict() for r in results],
            })
        finally:
            session.close()
    except Exception as exc:
        logger.error("/api/your-endpoint error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 500
```

Conventions:
- Always return `{"status": "ok", ...}` on success
- Always return `{"status": "error", "message": "..."}` with an appropriate HTTP status on failure
- Cap `limit` at a sensible maximum (50–200 depending on endpoint)
- Accept `region` as a query param for all region-scoped endpoints
- Document the endpoint in the API tables in README.md and RUNBOOK.md

---

## Adding a New Map Mode

### Backend
1. Add API endpoints needed by the new mode (see above)
2. If new H3 aggregation is needed, use the same pattern as `/api/jobs/h3-map` or `/api/map-employers`

### Frontend (4 files to touch)

**`frontend/index.html`**
- Add a `<button id="mode-<name>" class="mode-btn">` in `#mode-switcher`
- Add a `<div id="<name>-controls" class="controls-group" style="display:none">` with filter inputs
- Add a `<div id="<name>-sidebar" class="sidebar" style="display:none">` in `#right-panel`
- If the mode has its own map legend, add a `<div id="map-legend-<name>">` in `#map-wrap`
- Add `<script src="js/<name>.js">` before `app.js`

**`frontend/js/<name>.js`**
- Wrap everything in `(function() { 'use strict'; })();`
- Use `window.sharedMap` to access the Leaflet map instance
- Expose a `window.<name>` object with at minimum: `refresh()`, `clear()`, `onZoom()`
- Handle panel switching internally (show/hide sub-panels)

**`frontend/js/app.js`**
- Add `isName = mode === '<name>'` to `switchMode()`
- Toggle controls, sidebar, and legend visibility for the new mode
- Add `document.getElementById('mode-<name>').classList.toggle('active', isName)`
- Handle the mode's entry logic: clear other layers, call your module's `refresh()`
- Add event listeners for any mode-specific filters
- Add `window.jobfinder.onZoom()` pattern to `map.on('zoomend')` if needed

**`frontend/css/style.css`**
- Add styles for any new card/badge types
- Follow the existing card pattern: `.your-card`, `.your-card:hover`
- Active mode button colors: use the mode's accent color as `.mode-btn.active` background
- Color palette: amber `#f0a500` (brands/stress), purple `#6c5ce7` (local), teal `#4ecca3` (jobs), blue `#4a9eff` (links)

---

## Frontend Conventions

**No build step.** Plain HTML/CSS/JS. No TypeScript, no bundler, no npm. Scripts are loaded with `<script>` tags in `index.html`.

**Module pattern.** Each JS file wraps its code in an IIFE:
```javascript
(function () {
    'use strict';
    // ... private state and functions ...
    window.moduleName = { refresh, clear, onZoom }; // public API
})();
```

**Shared Leaflet instance.** `app.js` creates the map and exposes it as `window.sharedMap`. All other modules read `window.sharedMap` — they do not create their own maps.

**HTML escaping.** When building HTML strings with user/API data, always use an `_esc()` function (see `jobfinder.js` for the pattern). Never interpolate raw API values directly into `innerHTML`.

**No frameworks.** DOM manipulation is plain `document.createElement()` + `element.className` + `element.innerHTML`. Keep it simple.

**H3 resolution clamping.** `job_postings` only has `h3_r7` and `h3_r8` — clamp all jobfinder hex requests to `resolution ∈ {7, 8}`. `local_employers` / `chain_locations` support r6–r9.

---

## Database Conventions

**Two write paths; use them:**
- Employer records → `backend/ingest_layer.py:ingest_employer()`
- Job postings → `listings/ingest.py:ingest_job_posting()`

**H3 cells are pre-computed at ingest.** Never call `h3.latlng_to_cell()` in a query. The `h3_r6`/`h3_r7`/`h3_r8`/`h3_r9` columns on `local_employers` and `h3_r7`/`h3_r8` on `job_postings` are always set at write time.

**Upsert, don't insert-then-check.** Use `INSERT ... ON CONFLICT DO UPDATE` (PostgreSQL `pg_insert`) everywhere. The unique constraints are the dedup keys.

**Fingerprinting.** `backend/normalizer.make_fingerprint()` produces a stable lowercase slug from an employer name (strips punctuation, normalizes whitespace). It's the primary dedup key before proximity matching.

**NULL is a valid state.** `local_employer_id = NULL` on a job posting means "unmatched" — it's expected, not an error. `h3_r7 = NULL` on a job posting means "fully remote, no location" — also expected.

**Adding columns.** Add to the SQLAlchemy model in `backend/database.py` (or `listings/models.py`). The server calls `Base.metadata.create_all()` on startup — new columns on existing tables need a manual `ALTER TABLE` or a migration script.

---

## Rate Manager Protocol

Before any external HTTP request:
1. Call `rate_manager.can_request(source_key)` — returns `False` if daily budget is exhausted
2. Make the request
3. Call `rate_manager.log_request(...)` with success/fail status, latency, and data yield

Never skip step 3, even on failure. Failed requests still count against the budget and are valuable for debugging success rates.

If a source has a **minimum delay** (e.g., Nominatim requires ≥1 sec between requests), enforce it in the adapter — the rate manager does not sleep for you.

If a source has a **per-session rate gate** beyond just daily limits (e.g., Jobicy's hourly restriction), enforce it in the adapter with a file-based or database-backed timestamp check before calling `can_request()`.

---

## Scheduler Conventions

- All scheduler job functions live in `backend/scheduler.py`
- Name format: `_run_<source_name>()` (private, prefixed with underscore)
- Each job function wraps its body in `try/except Exception as e: logger.error(...)`
- Jobs that update scores call `compute_all_scores(region)` at the end
- Jobs that are rarely useful (QCEW, CBP) have built-in month-guard `if current_month not in active_months: return`
- Schedule config comes from `config/scheduler.yaml` — each top-level key is a job ID with `enabled`, `trigger`, and `cron`/`interval_hours` fields. Always add a hardcoded fallback default in `add_job()` in case the key is absent from the YAML
- Check `GET /api/scheduler/status` after adding a new job to confirm it's registered

---

## Testing

Tests live in `tests/`. Run with:
```bash
pytest tests/
```

Current test coverage focuses on:
- `tests/test_ingest_layer.py` — employer normalization + fingerprinting
- `tests/test_listings_ingest.py` — job posting ingest pipeline
- `tests/test_scorer.py` — scoring engine output ranges

When adding a new scraper:
- Write a test that parses a fixture response (save a sample API response to `tests/fixtures/`)
- Test that required fields (`source`, `external_id`, `raw_employer_name`) are always populated
- Do not mock the database in integration tests — use a real test DB or an in-memory SQLite for unit tests

---

## Code Style

**Python:**
- Type hints on all function signatures
- Docstrings on public functions (one-liner for simple helpers, full Args/Returns for complex ones)
- `logger = logging.getLogger(__name__)` at module level; use `logger.info/warning/error` not `print`
- `[ClassName]` prefix in log messages for easy grep: `logger.info("[Scheduler] Running JobSpy")`

**JavaScript:**
- `var` not `let/const` — the codebase predates ES6 adoption for compatibility
- Function declarations not arrow functions
- `_privateName` prefix for module-private functions/variables
- No console.log in committed code — use `console.warn` or `console.error` only

**SQL (via SQLAlchemy):**
- Use ORM queries for simple lookups
- Use `text()` or raw SQL only for complex aggregations that would be unreadable in ORM
- Always close sessions in `finally` blocks

**File naming:**
- Scrapers: `<source>_adapter.py`
- Frontend JS modules: `<mode>.js`
- Backend modules: `<function>.py` (no suffix)
