# SpiritPool — Handoff Document

**Date:** 2026-03-16  
**Author:** Agent session #2 (SQL backend implementation)  
**Focus:** Getting local SQL DB data collection working and tested end-to-end

---

## 1. What Was Done This Session

| Task | Status | Notes |
|------|--------|-------|
| SQL schema design (5 normalised tables) | ✅ Done | `backend/models.py` |
| Ingestion service (dedup on write) | ✅ Done | `backend/ingest.py` |
| REST API endpoints (contribute, stats, jobs) | ✅ Done | `backend/api.py` |
| Server integration (SQLAlchemy, CORS, blueprint) | ✅ Done | `server.py` updated |
| **Dedup bug fix** in linkedin.js | ✅ Done | Two-phase: `thisScanKeys` + `sentHashes` |
| Extension flush wired to backend | ✅ Done | `background.js` POSTs to `localhost:8765` |
| Manifest updated with localhost permission | ✅ Done | `host_permissions` in manifest.json |
| Simulated API test (Flask test client) | ✅ **Passed** | 3 signals → 2 jobs, 0 errors |
| **Live end-to-end test** (extension → server) | ⬜ NOT DONE | The critical remaining gap |

---

## 2. Architecture — Data Flow

```
LinkedIn page (DOM)
     │
     ▼
linkedin.js (content script)
  ├── 3 extraction strategies (cards, detail panel, job links)
  ├── djb2 hash for dedup
  └── browser.runtime.sendMessage({action:"signal", ...})
     │
     ▼
background.js (service worker)
  ├── Caches signal in browser.storage.local under "cache:linkedin.com"
  ├── Rescan every 15s, flush alarm every 15 min
  └── flushDomain() → POST /api/spiritpool/contribute
     │
     ▼
server.py (Flask, port 8765)
  └── /api/spiritpool/contribute
       │
       ▼
  backend/ingest.py
  ├── Normalise company name (lowercase, strip suffixes)
  ├── Parse location (city, state, country, is_remote)
  ├── Dedup job by (source + source_job_id), fallback by (source + title_norm + company_id)
  ├── Create observation row (point-in-time snapshot)
  └── Update contributor signal count
       │
       ▼
  data/spiritpool.db (SQLite)
```

---

## 3. What Works (Verified)

### Extension — LinkedIn extraction
- Content script loads on `linkedin.com/jobs/*`
- All 3 strategies fire: cards (`.job-card-container`), detail panel (`.jobs-details`), job links (`a[href*="/jobs/view/"]`)
- Dedup works correctly: within-scan cross-strategy dedup via `thisScanKeys`, across-scan dedup via `sentHashes`
- Signals are sent to background.js cache via `browser.runtime.sendMessage`
- 15-second rescan with SPA navigation detection (URL change → full rescan)
- Confirmed working on live LinkedIn pages (session #1 testing)

### Backend — SQL ingestion
- `server.py` starts cleanly, auto-creates `data/spiritpool.db` and all 5 tables
- `POST /api/spiritpool/contribute` accepts batch payloads, caps at 1000 signals
- Company dedup by `name_normalised`
- Location dedup by `normalised` string
- Job dedup by `source + source_job_id` (primary) or `source + title_norm + company_id` (fallback)
- Re-observations of the same job create additional observation rows (time-series snapshots)
- Contributor UUID generated and tracked
- **Test result** (simulated via Flask test client):
  ```
  Input:  3 signals (2 unique jobs, 1 re-observation of job #1)
  Output: accepted=3, new_jobs=2, errors=0
  Stats:  2 jobs, 3 observations, 2 companies, 1 contributor
  ```

### API — All endpoints responding
- `GET /stats` → aggregate counts by source
- `GET /jobs?page=1&per_page=50&source=linkedin.com` → paginated listing
- `GET /jobs/<id>` → full detail with observation array
- CORS enabled for `moz-extension://*`

---

## 4. What Has NOT Been Tested

### 🔴 Critical — Live end-to-end (extension → server → DB)
The simulated test used Flask's test client to post a payload directly. **Nobody has yet:**
1. Started `server.py`
2. Loaded the extension in Firefox
3. Navigated to LinkedIn Jobs
4. Waited for data to flush from extension cache → backend API → SQLite

This is the #1 priority for the next agent.

**Why it might fail:**
- CORS headers may not match the specific `moz-extension://` origin Firefox assigns
- `browser.runtime.sendMessage` in content → background signaling may have timing issues after Ember hydration
- `fetch()` from background.js to localhost may be blocked by Firefox extension sandbox
- The flush alarm (15 min) could be too slow for testing — may need to trigger `flushAllDomains()` manually from the extension console

### 🟡 Medium — Observation-level dedup
Currently there's no guard against creating duplicate observation rows for the same (job, contributor, timestamp) tuple. If a flush is retried, it could create duplicate observations. There should be either:
- A unique constraint on `(job_id, contributor_id, observed_at)`, or
- A check in `ingest_signal()` before inserting

### 🟡 Medium — Other content scripts
Only `linkedin.js` has been tested live. The other scrapers are scaffolds:
- `indeed.js` (251 lines) — has `TARGET_COMPANIES = ["starbucks"]` filter
- `glassdoor.js` (163 lines)  
- `google-maps.js` (194 lines)
- `starbucks-careers.js` (182 lines)

These send signals in the same format but haven't been validated against live DOM.

### 🟢 Low — MS SQL Server / PostgreSQL
`DATABASE_URL` env var is plumbed through to SQLAlchemy, but only SQLite has been tested. Switching to MS SQL will require `pyodbc` and may surface dialect differences in the ORM calls.

---

## 5. Key Code Entry Points

### Backend

| File | Key function/class | What it does |
|------|--------------------|--------------|
| `server.py` lines 1-30 | `create_app()` equivalent | SQLAlchemy init, CORS, blueprint registration |
| `backend/models.py` lines 1-148 | `Company`, `Location`, `Job`, `Observation`, `Contributor` | ORM models, normalise class methods |
| `backend/ingest.py` lines 210-256 | `ingest_batch(data, db)` | Main entry: loops signals, calls `ingest_signal()`, commits |
| `backend/ingest.py` lines 100-140 | `get_or_create_job()` | Two-tier job dedup (source_job_id, then title+company) |
| `backend/api.py` lines 20-70 | `contribute()` | POST handler: validates payload, calls `ingest_batch()` |

### Extension

| File | Key function | What it does |
|------|--------------|--------------|
| `spiritpool/background.js` line 270 | `flushDomain(domain)` | POST cached signals to backend API |
| `spiritpool/background.js` line 240 | `getContributorId()` | Get/create persistent UUID |
| `spiritpool/content/linkedin.js` line 100 | `extractFromCards()` | Strategy #1: parse `.job-card-container` nodes |
| `spiritpool/content/linkedin.js` line 250 | `extractFromDetailPanel()` | Strategy #2: parse `.jobs-details` panel |
| `spiritpool/content/linkedin.js` line 370 | `extractFromJobLinks()` | Strategy #3: parse `a[href*="/jobs/view/"]` |
| `spiritpool/content/linkedin.js` line 500 | `runScan()` | Orchestrates all 3 strategies, dedup, send |

---

## 6. Suggested Next Steps (Ordered)

1. **Run the live end-to-end test**
   - Start server: `.venv/bin/python server.py --debug`
   - Load extension in Firefox
   - Navigate to LinkedIn Jobs, wait for extraction (check extension console for `[SP/LI]` logs)
   - Trigger manual flush: run `flushAllDomains()` in extension console
   - Verify: `curl http://localhost:8765/api/spiritpool/stats`
   - Debug any CORS, fetch, or payload format issues

2. **Add observation dedup guard**
   - In `ingest_signal()`, before creating an Observation, check if one already exists with same `job_id + contributor_id + observed_at` (within a tolerance window like 60 seconds)
   - Or add a UniqueConstraint to the model

3. **Add a manual "Flush Now" button to the popup**
   - `spiritpool/popup/popup.html` and `popup.js` exist but have no flush trigger
   - Wire a button to send `{action: "flushAll"}` message to background.js

4. **Add DB record count to popup**
   - Popup could fetch `GET /api/spiritpool/stats` and display counts
   - Gives immediate visual feedback that the pipeline works

5. **Write automated integration test**
   - Script that starts server, posts a known payload, asserts DB state
   - Can live in `backend/test_ingest.py` or similar

6. **Test other content scripts** (indeed.js, etc.)
   - One at a time on live pages
   - Verify signal format matches what `ingest.py` expects

7. **Switch to MS SQL Server** (when ready for prod)
   - Install `pyodbc`: `.venv/bin/pip install pyodbc`
   - Set `DATABASE_URL=mssql+pyodbc://...`
   - Test table creation and ingestion

---

## 7. Known Issues / Gotchas

| Issue | Details |
|-------|---------|
| **linkedin.js is a TEST BUILD** | Heavy `console.log` output, diagnostic counters — not production-ready |
| **No rate limiting** on contribute endpoint | Any caller can POST unlimited batches |
| **No auth** on API | Contributor UUID is self-generated, trivially spoofable |
| **SQLite concurrency** | SQLite handles one writer at a time — fine for local dev, not for multi-user |
| **linkedin.js captures ALL jobs** | Unlike other scripts, it has no `TARGET_COMPANIES` filter |
| **Alarm API** | `browser.alarms.create("spiritpool-queue", {periodInMinutes: 15})` — Firefox may enforce a minimum of 1 minute in MV3 |
| **Empty `backend/__init__.py`** | It only exists as a package marker — all init happens in `server.py` |

---

## 8. Environment State

```
Python: 3.12.3 (.venv/)
Packages: flask==3.1.3, flask-sqlalchemy, flask-cors, requests, tqdm, playwright
DB: SQLite at data/spiritpool.db (currently empty — test DB was cleaned up)
Extension: spiritpool/ — ready to load as temporary add-on
Server: server.py on port 8765
```

The database is clean (empty). Starting the server will recreate all tables. The next agent should start from step 1 of the suggested next steps above.
