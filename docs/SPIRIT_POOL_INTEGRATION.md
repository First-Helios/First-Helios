# Spirit Pool → First-Helios Integration Guide

**For:** Claude agents continuing development on this codebase
**Last updated:** 2026-03-25
**Status:** Backend fully wired. Extension-side scope expansion is the outstanding work.

---

## What is Spirit Pool?

Spirit Pool is a **Manifest V3 browser extension** that lives in a separate repository:
`/home/fortune/CodeProjects/ChainStaffingTracker/spiritpool/`

It runs in the user's browser, passively collects job listing metadata from allowlisted job sites as the user browses, caches signals locally, and periodically flushes them to First-Helios via HTTP POST. The user explicitly consents via a first-run modal. They can pause collection, toggle sites on/off, or revoke consent at any time.

**It is the primary real-time data source for First-Helios's job-first map layer.**

---

## Scope Change: From Starbucks-Only to All Austin Employers

The original Spirit Pool was purpose-built for Starbucks chain staffing research. Every content script had a company filter (`if company !== "starbucks" skip`). **That constraint must be removed.**

First-Helios needs job postings for **all employers in Austin, TX** — any chain, any industry — so the job-first map layer can show hiring activity across the whole labor market, not just one chain.

**What this means for the extension:**
- Remove the `targetCompanies` filter from all content scripts and `selectors.json`
- Remove or widen the company-match guard in `content/indeed.js`, `content/linkedin.js`, `content/glassdoor.js`
- LinkedIn's `content/linkedin.js` already captures all jobs (no filter) — it is the model to follow
- The `background.js` flush destination must point to First-Helios (see Backend URL below)

---

## Extension Architecture (Brief)

```
User browses job site
  → content script extracts job card fields
  → sendMessage({ type: "spiritpool:signal", domain, signal })
  → background.js validates consent + site toggle
  → stores in browser.storage.local under cache:<domain>
  → every 10 min (or 500 signals, or manual flush):
      POST /api/spiritpool/contribute
      { domain, signals: [...], contributorId, region }
  → First-Helios ingests into job_postings table
```

**Key files in ChainStaffingTracker/spiritpool/:**

| File | Role |
|------|------|
| `background.js` | Service worker: consent gate, local cache, flush scheduler |
| `shared/selectors.json` | Externalized CSS selectors for all supported sites |
| `shared/scanner.js` | Generic DOM extraction engine (layout-agnostic) |
| `content/indeed.js` | Indeed.com parser (has Starbucks filter — remove it) |
| `content/linkedin.js` | LinkedIn parser (already captures all jobs) |
| `content/glassdoor.js` | Glassdoor parser (has Starbucks filter — remove it) |
| `content/google-jobs.js` | Google Jobs parser (may exist — verify) |
| `content/starbucks-careers.js` | Starbucks-specific — low priority for expansion |
| `popup/popup.js` | User-facing dashboard + flush controls |
| `manifest.json` | Firefox MV3 source of truth |

---

## Signal Format (Extension → Server)

The extension sends signals as JSON. Each signal in the `signals` array looks like:

```json
{
  "company":        "Whole Foods Market",
  "jobTitle":       "Grocery Team Member",
  "location":       "Austin, TX 78701",
  "salary": {
    "min":    16,
    "max":    20,
    "period": "hourly"
  },
  "postingDate":    "2026-03-23T00:00:00Z",
  "applicantCount": 34,
  "badges":         ["Urgently Hiring"],
  "url":            "https://www.indeed.com/viewjob?jk=abc123",
  "observedAt":     "2026-03-25T10:15:00Z"
}
```

Optional fields that First-Helios also accepts (add these to content scripts if available):
- `description` — full job description text
- `jobType` — "full-time", "part-time", "contract"
- `isRemote` — boolean
- `companyIndustry` — e.g. "Retail", "Food & Beverage"
- `jobLevel` — "entry", "mid", "senior"
- `rating` — employer star rating (from Glassdoor / Google Maps)

**The full POST body:**
```json
{
  "domain":        "indeed.com",
  "signals":       [ ... ],
  "contributorId": "stable-uuid-per-install",
  "region":        "austin_tx"
}
```

---

## Backend URL

The extension's `background.js` currently hardcodes:
```javascript
const BACKEND_URL = "http://localhost:8765/api/spiritpool/contribute";
```

**First-Helios runs on port 5000** (default Flask dev) or port 8765 in production (check `.env`).

When the extension is used for real data collection (not just local testing), this URL must either:
1. Be changed to point to the deployed First-Helios server URL, or
2. Be made configurable via the extension's options page (preferred long-term)

For development, ensure First-Helios is running before flushing from the extension.

---

## First-Helios Backend: What Is Already Built

### `listings/` module (complete)

| File | Status | Purpose |
|------|--------|---------|
| `listings/__init__.py` | Done | Package exports |
| `listings/config.py` | Done | TTL (30 days), proximity threshold (150 m) |
| `listings/models.py` | Done | `JobPosting` SQLAlchemy model — 24 columns, 4 indexes |
| `listings/matcher.py` | Done | 2-stage Haversine + fingerprint matching to `local_employers` |
| `listings/ingest.py` | Done | `ingest_job_posting(signal, region, session)` — 8-step pipeline |
| `listings/spiritpool_routes.py` | Done | Flask Blueprint: `POST /api/spiritpool/contribute`, `GET /api/spiritpool/stats` |

### Registration (complete)

In `server.py` (lines 66–68):
```python
from listings.spiritpool_routes import spiritpool_bp
app.register_blueprint(spiritpool_bp)
logger.info("Spirit Pool blueprint registered at /api/spiritpool")
```

### Database (complete)

The `job_postings` table is created automatically by `backend/database.py` via `init_db()`.
It has 24 columns including `source`, `external_id`, `fingerprint`, `local_employer_id` (FK nullable),
`match_confidence`, `match_method`, `expires_at`, `is_active`.

### Ingest contract

`ingest_job_posting()` in `listings/ingest.py` accepts a `ScraperSignal` with `signal_type == "listing"`.
The `spiritpool_routes.py` mapper (`_map_signal()`) translates the raw extension JSON into a `ScraperSignal`.

**Source tag format:** `spiritpool_<domain_slug>` — e.g. `spiritpool_indeed`, `spiritpool_linkedin`.

---

## What Remains To Be Built

### Priority 1 — Extension Scope Expansion (ChainStaffingTracker)

These changes are in `ChainStaffingTracker/spiritpool/`, not in First-Helios:

1. **Remove company filters** from `content/indeed.js` and `content/glassdoor.js`
   Look for `if (!isTargetCompany(company)) continue` or `targetCompanies` checks — delete them.

2. **Update `selectors.json`** — remove or null out `targetCompanies` arrays for all sites.

3. **Add region filter instead** — instead of filtering by company, add a location/region filter
   so the extension only collects Austin-area postings. This prevents flooding the database with
   global jobs. Filter on location text containing "Austin" or "TX" where the site provides it.
   If not determinable from the card, collect everything and let First-Helios's regional scope handle it.

4. **Add Google Jobs** (`content/google-jobs.js`) — Google Jobs (google.com/search?q=jobs) is a
   high-value aggregator that surfaces postings from many employers simultaneously. Add it to the
   manifest host_permissions and write a content script. Key fields: jobTitle, company, location,
   salary, postingDate, job_url (from the posting card). The scanner.js heuristic engine can
   bootstrap this — run `SpiritPoolScanner.diagnose("google.com")` in the browser console first.

5. **Add ZipRecruiter** — another high-volume aggregator. Same approach as Google Jobs.

6. **Update manifest host_permissions** for any new sites.

7. **Update the popup's "Monitored Sites" list** to reflect expanded site coverage and remove
   Starbucks-specific language.

### Priority 2 — Map Endpoint for Active Postings (First-Helios)

File to create: `listings/routes.py` (the job-first map API, separate from spiritpool_routes)

```python
GET /api/map-jobs?region=austin_tx&industry=retail&lat=30.27&lng=-97.74&radius_mi=10
```

Returns `{ jobs: [ { lat, lng, employer_name, role_title, wage_min, wage_max, source_url, ... } ] }`
filtered to `is_active = True`. This powers the "Hiring Now" map mode in the frontend.

Register in `server.py`:
```python
from listings.routes import jobs_bp
app.register_blueprint(jobs_bp)
```

### Priority 3 — Frontend "Hiring Now" Mode

In `frontend/index.html` and `frontend/js/app.js`:
- Add a mode toggle: **Job Fair Map** | **Hiring Now**
- In "Hiring Now" mode: fetch `/api/map-jobs`, plot dots from `job_postings` (not `local_employers`)
- Each dot = an active posting; click → show job title, pay, apply link
- Does NOT replace the existing Job Fair Map — it's an additional mode

### Priority 4 — Scheduler Jobs

File to create: `listings/scheduler_jobs.py`

```python
def register_listings_jobs(scheduler):
    scheduler.add_job(run_expiry_sweep, 'cron', hour=3, minute=30, ...)
```

In `backend/scheduler.py`, add (with ImportError guard):
```python
try:
    from listings.scheduler_jobs import register_listings_jobs
    register_listings_jobs(scheduler)
except ImportError:
    pass
```

### Priority 5 — Match Validation Script

File to create: `scripts/check_job_matching.py`

Diagnostic: queries `job_postings`, reports total / matched / unmatched counts,
match method distribution, sample 20 unmatched rows. Used to tune `PROXIMITY_THRESHOLD_M`
in `listings/config.py` toward a target of ≥60% match rate for chain-brand postings.

---

## Data Flow: End to End

```
User opens Indeed in browser with Spirit Pool installed
  ↓
Content script scans job cards, extracts fields
  ↓
Signals buffered in browser.storage.local
  ↓
Every 10 min: POST http://localhost:5000/api/spiritpool/contribute
  {
    domain: "indeed.com",
    signals: [ { company, jobTitle, location, salary, url, ... } ],
    contributorId: "abc-uuid",
    region: "austin_tx"
  }
  ↓
listings/spiritpool_routes.py:
  _map_signal() converts to ScraperSignal (source = "spiritpool_indeed")
  ↓
listings/ingest.py:
  ingest_job_posting(signal, region="austin_tx", session)
    1. Extract employer name, address, salary, date
    2. Dedup by (source, external_id) — skip active, reactivate expired
    3. normalize_name() + make_fingerprint() via backend/normalizer.py
    4. Geocode if no lat/lng via scrapers/geocoding.py (Nominatim)
    5. match_posting_to_employer() — fingerprint + Haversine ≤150m
    6. Compute expires_at = posted_date + 30 days
    7. Upsert via pg_insert ON CONFLICT DO UPDATE
  ↓
job_postings table row with:
  local_employer_id (FK → local_employers if matched, NULL if not)
  match_confidence, match_method, is_active=True
  ↓
listings/routes.py (to be built):
  GET /api/map-jobs → frontend "Hiring Now" map
```

---

## Key Design Decisions to Preserve

1. **`local_employer_id` is nullable.** Unmatched postings are valid and still appear on the map
   using the posting's own geocoded lat/lng. Do not discard postings that don't match a `local_employers` row.

2. **Spirit Pool signals use `source = "spiritpool_<domain>"`** (e.g. `spiritpool_indeed`).
   First-Helios's existing `careers_api` and `jobspy` scrapers use `source = "careers_api"` / `"jobspy"`.
   These are separate source namespaces in `job_postings` — Spirit Pool data does not overwrite server-scraped data.

3. **`contributorId`** is stored in the signal metadata but is not surfaced publicly anywhere.
   It is used only for rate-limiting and dedup if needed in the future.

4. **The extension does not do any authentication.** The `/contribute` endpoint is unauthenticated
   but rate-limited by IP. If the endpoint becomes public-facing, add a shared secret or token header.

5. **TTL is 30 days** (`POSTING_TTL_DAYS`). Stale postings are not deleted — `is_active` is set to
   False by the nightly expiry sweep. Historical data is preserved for trend analysis.

6. **`selectors.json` drives the DOM extraction** — do not hardcode selectors in content script JS.
   When a site redesigns its job card HTML, update `selectors.json` only; no code change needed.

---

## Testing the Integration

### Smoke test (backend only)
```bash
cd /home/fortune/CodeProjects/First-Helios
python -c "from listings.spiritpool_routes import spiritpool_bp; print('Blueprint OK')"
```

### Manual POST test
```bash
curl -X POST http://localhost:5000/api/spiritpool/contribute \
  -H "Content-Type: application/json" \
  -d '{
    "domain": "indeed.com",
    "signals": [{
      "company": "H-E-B",
      "jobTitle": "Cashier",
      "location": "Austin, TX 78701",
      "salary": {"min": 15, "max": 18, "period": "hourly"},
      "url": "https://www.indeed.com/viewjob?jk=test123",
      "postingDate": "2026-03-24T00:00:00Z"
    }],
    "contributorId": "test-agent",
    "region": "austin_tx"
  }'
```

Expected response: `{"accepted": 1, "new_jobs": 1, "failed": 0}`

### Stats check
```bash
curl http://localhost:5000/api/spiritpool/stats
```

---

## Files Agent Should NOT Modify

- `listings/models.py` — table schema is stable; changes require a migration
- `listings/ingest.py` — the 8-step pipeline is complete; extend via `metadata` fields, don't restructure
- `listings/matcher.py` — tuning is done via `listings/config.py` env vars, not code changes
- `backend/database.py` — `_import_listings_models()` is already registered; don't re-add it
