# First-Helios Incomplete Feature Audit
_Generated: 2026-03-21 — Full codebase audit_

---

## BROKEN — Crashes at runtime
These cause visible errors in session logs.

- [x] `agent_interface/executor.py:300` — `OvertureLocalAdapter.fetch_local_employers()` does not exist; method is `scrape(region)` _(fixed 2026-03-21)_
- [x] `agent_interface/executor.py:385` — `BLSAdapter.fetch_series()` does not exist; method is `scrape(region)` _(fixed 2026-03-21)_

---

## STUB — Adapters registered but never called by executor

### ReviewsAdapter — `sentiment_check`
- **File:** `pipeline/route_index.py:257`, `backend/endpoint_catalog.py:214` (route_status="unwired")
- **Adapter:** `scrapers/reviews_adapter.py` — complete, scrapes Google Maps / Glassdoor star ratings
- **Gap:** `_execute_sentiment_check()` in `agent_interface/executor.py` only calls `RedditAdapter`. `ReviewsAdapter` is never called.
- **Fix:** Wire `ReviewsAdapter` as a secondary signal source in `_execute_sentiment_check()` alongside Reddit.

### OSMAdapter — `poi_chain_locations` (tertiary fallback)
- **File:** `pipeline/route_index.py:117` (status="unwired")
- **Adapter:** `scrapers/osm_adapter.py` — functional, fetches chain stores via Overpass API
- **Gap:** `_execute_poi_chain()` calls AllThePlaces + Overture but has no OSM fallback when coverage is low.
- **Fix:** Add OSM call in `_execute_poi_chain()` when ATP + Overture return fewer stores than expected.

### OSMAdapter — `poi_local_density` (local fallback)
- **File:** `pipeline/route_index.py:153` (status="unwired")
- **Gap:** `_execute_poi_local()` only calls `OvertureLocalAdapter`. No OSM fallback for local businesses.
- **Fix:** Add OSM amenity query as fallback in `_execute_poi_local()`.

### Pipeline Validation Contracts — never called during ingest
- **File:** `pipeline/validation.py` — `validate_scraper_output()` + `SCRAPER_OUTPUT_CONTRACTS` defined and tested
- **Gap:** `backend/ingest.py` processes signals without calling the validation contracts. Data enters the DB unvalidated.
- **Fix:** Call `validate_scraper_output()` in `ingest_signals()` before committing records.

### Pipeline Tracing — never integrated
- **File:** `pipeline/tracing.py` — `PipelineTrace` and `TraceSpan` dataclasses defined
- **Gap:** `agent_interface/executor.py` never imports or uses tracing. No span-level data is captured during execution.
- **Fix:** Import and instrument each `_execute_*` function with trace spans.

---

## SILENT — Fails without visible error

### Geocoding never writes coordinates to Store table
- **Files:** `scrapers/geocoding.py` (function exists), `backend/database.py:62-63` (Store.lat, Store.lng columns), `backend/ingest.py`
- **Gap:** Geocoding is never called during ingest. All Store records have `lat=None, lng=None`. This breaks any targeting or geographic clustering that depends on store coordinates.
- **Fix:** Call `geocode()` in `ingest_signals()` when lat/lng are missing on a new Store record.

### ImportError handlers silently disable adapters
- **File:** `agent_interface/executor.py` (lines ~224, 308, 395, 483 and others)
- **Gap:** Every adapter import is wrapped in `try/except ImportError` that appends to anomalies and continues. Missing dependencies are never surfaced as hard failures. The system looks like it ran but silently did nothing.
- **Fix:** Log at WARNING level with the specific missing package name; consider a startup import check.

### Reference model import silently skipped
- **File:** `backend/database.py:41`
- **Gap:** `import backend.models.reference` is wrapped in `try/except ImportError` with only `logger.debug`. If it fails, ref tables are never created and no one notices.
- **Fix:** Raise or at minimum log at ERROR level.

### ReviewsAdapter returns `[]` and logs "graceful degradation"
- **File:** `scrapers/reviews_adapter.py:77-81`
- **Gap:** When google-maps-scraper library is unavailable, returns empty list logged as "graceful degradation" — indistinguishable from a successful empty result.
- **Fix:** Set a distinct result status or anomaly flag so the caller knows the data source was unavailable, not just empty.

---

## PLANNED — Explicitly future / not yet started

### Reddit OAuth (`reddit_oauth`)
- **File:** `pipeline/route_index.py:243` (status="suggested"), `backend/endpoint_catalog.py:200`
- **Notes:** PRAW support code exists in `scrapers/reddit_adapter.py` (`_get_praw_client()`). Currently only the public JSON API is used. OAuth would allow higher rate limits and more complete data.
- **Requires:** REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET env vars + wiring in executor.

### Targeting → Scheduling integration
- **File:** `backend/targeting.py`
- **Notes:** Targeting algorithm ranks job fair sites but output is never translated into scheduling recommendations (best day/time, co-presence events, local employer fair planning).

### Thin-coverage percentile scoring
- **File:** `backend/scoring/engine.py`
- **Notes:** Scoring model needs ≥3 stores in the same region/industry for statistically meaningful percentiles. HVAC, accommodation, and other sparse industries get scores that are not yet valid.

### Playwright fallback scrapers
- **File:** `scrapers/playwright_fallback.py`
- **Notes:** `WorkdayScraper` and `GoogleMapsStoreFinder` are defined but not auto-scheduled. Intended for manual use or when primary scrapers return 0 signals.

---

## Already Fixed (reference)

| Date | Fix |
|------|-----|
| 2026-03-21 | `OvertureLocalAdapter.fetch_local_employers()` → `scrape(region)` |
| 2026-03-21 | `BLSAdapter.fetch_series()` → `scrape(region)` |
| 2026-03-21 | `AllThePlacesAdapter.fetch_chain_stores()` → `scrape(region)` with `adapter.chain = brand_key` |
| 2026-03-21 | `ATP_SPIDER_MAP` removed from executor; `ATP_BRAND_MAP` in adapter is single source of truth |
| 2026-03-21 | `ATP_BRAND_MAP` expanded: added hair_beauty, fitness, pharmacy, grocery, hospitality brands |
| 2026-03-21 | OvertureChainAdapter added as fallback in `_execute_poi_chain` after ATP |
| 2026-03-21 | `CHAIN_NAME_FILTERS` in OvertureChainAdapter expanded to all brands |
| 2026-03-21 | `CATEGORY_INDUSTRY_MAP` replaced by `backend/category_catalog.py` — programmatic, DB-backed |
| 2026-03-21 | `poi_local_density` `records_found` now shows total region count, not industry-filtered count |
| 2026-03-21 | `poi_local_density` anomaly now reports both industry-specific and total counts |
| 2026-03-21 | `consecutive_freshness_rejections` counter added to ClawSession; injects `session_hint` → `done` |
| 2026-03-21 | SYSTEM_PROMPT: clarified POI terms vs job terms (separate keys, explained difference) |
| 2026-03-21 | SYSTEM_PROMPT: Rule 13 added — follow `session_hint` immediately |
| 2026-03-21 | `priority` + `lead_type` removed from discovery_scan `suggested_next` output |
| 2026-03-21 | Freshness gate: treat `records_collected == 0` as stale |
| 2026-03-21 | `suggested_next` field renamed `action` → `suggested_intent` |
| 2026-03-21 | Wish array form + brace-counting JSON extractor |
| 2026-03-21 | `"discovery"` action alias added; SYSTEM_PROMPT section renamed |
| 2026-03-21 | `data_quality_audit` chain audit excludes `chain='local'` stores |
| 2026-03-21 | Pilot briefing agenda filtered by `focus_industries` |
| 2026-03-21 | ApiEndpoint unique constraint: `(adapter_name, source_key, intent)` |
