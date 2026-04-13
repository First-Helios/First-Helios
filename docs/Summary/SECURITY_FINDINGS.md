# Security Findings — First-Helios Audit

**Date:** 2026-04-03  
**Auditor:** Security Testing Agent (database_and_security_agent.md)  
**Scope:** All data exchange points, ingest paths, frontend rendering, DB access

---

## Summary

| ID | Severity | Title | File | Status |
|----|----------|-------|------|--------|
| CRIT-1 | Critical | Unauthenticated unlimited write to `job_postings` — no rate limit, no batch cap | `postings/spiritpool_routes.py:98` | Partially mitigated (batch cap + domain allowlist added) |
| CRIT-2 | Critical | Stored XSS via `innerHTML` without escaping | (frontend, now in separate repo) | Fixed |
| HIGH-1 | High | Internal exception strings leaked in all 500 responses (36 sites) | `server.py`, `events/routes.py`, `spiritpool_routes.py` | Fixed |
| HIGH-2 | High | Wildcard CORS — all origins accepted | `server.py:128` | Accepted risk — documented |
| HIGH-3 | High | Unauthenticated `POST /api/scan` triggers outbound scraping | `server.py:186` | Open |
| HIGH-4 | High | `source_url`/`ticket_url` rendered in `href` without protocol validation | (frontend, now in separate repo) | Fixed |
| HIGH-5 | High | Unauthenticated `POST /api/events/interactions` — unbounded storage | `events/routes.py:257` | Open |
| MED-1 | Medium | Debug mode + `host=0.0.0.0` — `.env.example` defaults to `FLASK_DEBUG=1` | `.env.example:26` | Fixed |
| MED-2 | Medium | Unbounded `sample=0` triggers full table scan | `server.py:490,562` | Fixed |
| MED-3 | Medium | Unbounded `keyword` parameter — full-table sequential scan DoS | `server.py:1581` | Fixed |
| MED-4 | Medium | `time_type` filter not allowlisted | `server.py:1619` | Fixed |
| MED-5 | Medium | IDOR on event interactions via sequential `event_id` | `events/routes.py:276` | Open |
| MED-6 | Medium | No security headers on any response | `server.py` | Fixed |
| MED-7 | Medium | Unsanitized `domain` field stored as `source` tag | `spiritpool_routes.py:57` | Fixed |
| LOW-1 | Low | `contributor_id` silently truncated in audit log | `spiritpool_routes.py:158` | Fixed |
| LOW-2 | Low | User-supplied `location` string drives outbound geocoding with no length cap | `postings/ingest.py:110` | Open |
| LOW-3 | Low | `FLASK_DEBUG=1` as default in `.env.example` | `.env.example:26` | Fixed |
| LOW-4 | Low | Hard-coded `localhost:8765` URL returned to browser extension | `spiritpool_routes.py:331` | Open |

---

## Data Exchange Map

### Write Paths (Inbound — All Unauthenticated)

| ID | Endpoint | Caller | Writes To | Auth |
|----|----------|--------|-----------|------|
| W1 | `POST /api/spiritpool/contribute` | Browser extension (public internet) | `job_postings` | None |
| W2 | `POST /api/scan` | Any HTTP client | `job_postings`, `signals`, `scores` | None |
| W3 | `POST /api/events/interactions` | Any HTTP client | `event_interactions` | None |
| W4 | `ingest_employer()` scripts | Collector scripts (offline) | `local_employers`, `brand_groups` | N/A |
| W5 | `ingest_job_posting()` | Collector scripts (offline) | `job_postings` | N/A |

### Read Paths (Outbound — User Input Reflected in Queries)

| ID | Endpoint | User-Controlled Params |
|----|----------|------------------------|
| R1 | `GET /api/scores` | `region`, `chain` |
| R2 | `GET /api/stores` | `region`, `chain`, `industry` |
| R3 | `GET /api/local-employers` | `region`, `industry`, `sample` |
| R4 | `GET /api/map-employers` | `region`, `chain`, `industry`, `h3_cell`, `resolution` |
| R5 | `GET /api/h3-map` | `resolution`, `region`, `industry`, `chain` |
| R6 | `GET /api/jobs/listings` | `keyword`, `category`, `h3_cell`, `time_type` |
| R7 | `GET /api/spiritpool/insights` | `region`, `industry` |
| R8 | `GET /api/events/*` | `region`, `category`, `h3_cell` |
| R9 | `GET /api/targeting` | `region`, `industry`, `chain`, `limit` |

---

## Detailed Findings

---

### CRIT-1: Unauthenticated Unlimited Write to `job_postings`

**Severity:** Critical  
**File:** `postings/spiritpool_routes.py:98–170`  
**Status:** Partially mitigated — batch cap and domain allowlist added; full auth not yet implemented

**Description:**  
`POST /api/spiritpool/contribute` accepts writes from any caller with no authentication, no API key, no IP allowlist, no per-contributor rate limit, and no cap on the `signals` array length. The `contributorId` is entirely self-reported. Any actor can flood `job_postings` with fabricated data, exhaust the PostgreSQL session pool, or trigger unlimited outbound Nominatim geocoding calls.

**Reproduction:**
```bash
# Flood with fabricated signals — no credentials required
python3 -c "
import requests, json
signals = [{'jobTitle': f'Fake Job {i}', 'company': 'Fake Co', 'location': 'Austin, TX'} for i in range(500)]
r = requests.post('http://localhost:8765/api/spiritpool/contribute',
    json={'domain': 'indeed.com', 'signals': signals, 'contributorId': 'attacker-001'})
print(r.status_code, r.json())
"
```

**Remediation:**  
1. Add `MAX_SIGNALS_PER_BATCH = 50` check (done in this session).  
2. Add domain allowlist (done in this session).  
3. Add `SPIRITPOOL_API_KEY` shared-secret auth: check `Authorization: Bearer <key>` header against env var before processing.  
4. Add per-IP rate limiting via `flask-limiter`.

---

### CRIT-2: Stored XSS via `innerHTML` Without Escaping

**Severity:** Critical  
**Files:**  
- `frontend/js/app.js:202–207` — `emp.name`, `emp.address`, `emp.industry`  
- `frontend/js/eventfinder.js:271–278` — `e.title`, `e.category`, `e.raw_venue_name`, `e.description`  
- `frontend/js/pathfinder.js:145` — `occ.title`, `occ.cluster_name`  
**Status:** Fixed

**Description:**  
Server-provided strings are injected directly into `innerHTML` without HTML escaping. The `_esc()` function exists in `jobfinder.js` but is not used in `app.js`, `eventfinder.js`, or `pathfinder.js`. Combined with CRIT-1 (unauthenticated write), an attacker can POST a crafted signal with `company: '<script>...</script>'`, which gets stored, returned by the API, and executed in every user's browser.

**Attack chain:**  
`POST /api/spiritpool/contribute` → stored in `job_postings.raw_employer_name` → returned by `/api/map-employers` → rendered unescaped into `emp.name` in `app.js:203` → executes in browser.

**Reproduction:**
```bash
curl -X POST http://localhost:8765/api/spiritpool/contribute \
  -H "Content-Type: application/json" \
  -d '{"domain":"indeed.com","signals":[{"company":"<img src=x onerror=alert(document.cookie)>","jobTitle":"Test","location":"Austin, TX"}]}'
# Then open the map and click on the hex cell containing "Austin, TX"
```

**Remediation:** Port `_esc()` to a shared utils module; wrap all server-provided strings before `innerHTML` assignment (done in this session).

---

### HIGH-1: Exception Strings Leaked in All 500 Responses

**Severity:** High  
**Files:** `server.py` (29 instances), `events/routes.py` (5 instances), `spiritpool_routes.py` (3 instances)  
**Status:** Fixed

**Description:**  
Every `except` block returns `str(e)` in the JSON body. SQLAlchemy exceptions include table names, column names, and partial SQL. Connection errors leak the DB host. This is free schema reconnaissance for an attacker.

**Reproduction:**
```bash
curl "http://localhost:8765/api/scores?region=%00invalid" | python3 -m json.tool
# Returns: {"message": "invalid byte sequence for encoding UTF8: 0x00 ..."}
```

**Remediation:** Global `@app.errorhandler(Exception)` that logs full traceback server-side and returns a generic `{"status": "error", "message": "An internal error occurred"}` (done in this session).

---

### HIGH-2: Wildcard CORS

**Severity:** High  
**File:** `server.py:128`  
**Status:** Accepted risk — documented

**Description:**  
`CORS(app)` with no `origins=` argument sends `Access-Control-Allow-Origin: *` on every response. Any webpage can make cross-origin requests to all API endpoints including the write endpoints.

**Remediation:**
```python
CORS(app, origins=[
    "moz-extension://*",
    "chrome-extension://*",
    "http://localhost:8765",
    "https://your-production-domain.com"
])
```
This requires knowing the browser extension IDs. Deferred until extension is out of hiatus.

---

### HIGH-3: Unauthenticated `POST /api/scan` Triggers Outbound Scraping

**Severity:** High  
**File:** `server.py:186–214`  
**Status:** Open

**Description:**  
Any caller can invoke unlimited scraping runs against third-party job boards, consuming CPU/memory/network and triggering IP bans on job board APIs.

**Remediation:** Require `SCAN_API_KEY` env var header authentication before executing. Add request deduplication (ignore if a scan is already running for the same chain/region).

---

### HIGH-4: `source_url`/`ticket_url` in `href` Without Protocol Validation

**Severity:** High  
**File:** `frontend/js/eventfinder.js:264–269`  
**Status:** Fixed

**Description:**  
URLs from the database are placed directly into `href` attributes. A stored `javascript:alert(document.cookie)` executes when a user clicks "Details ↗" or "Tickets ↗". The ingest pipeline accepts URLs from untrusted sources with no scheme validation.

**Remediation:** `_safeUrl()` function that returns the URL only if it starts with `http://` or `https://`, otherwise `#` (done in this session).

---

### HIGH-5: Unauthenticated `POST /api/events/interactions`

**Severity:** High  
**File:** `events/routes.py:257–314`  
**Status:** Open

**Description:**  
Any caller can log unlimited fake interactions (views, clicks, ratings) against any event ID. Sequential integer IDs make enumeration trivial. No rate limiting. Can skew all analytics and cause table bloat.

---

### MED-1: Debug Mode + `host=0.0.0.0`

**Severity:** Medium  
**File:** `server.py:1808`, `.env.example:26`  
**Status:** Fixed (`.env.example` corrected)

**Description:**  
`.env.example` sets `FLASK_DEBUG=1`. Developers copying it directly expose the Werkzeug interactive Python REPL in the browser. The server also binds to all interfaces.

---

### MED-2: Unbounded `sample=0` Full Table Scan

**Severity:** Medium  
**File:** `server.py:490,562`  
**Status:** Fixed (capped at 5000)

---

### MED-3: Unbounded `keyword` Parameter — Sequential Scan DoS

**Severity:** Medium  
**File:** `server.py:1581–1586`  
**Status:** Fixed (capped at 100 chars)

---

### MED-4: `time_type` Filter Not Allowlisted

**Severity:** Medium  
**File:** `server.py:1619`  
**Status:** Fixed (allowlisted to known values)

---

### MED-5: IDOR on Event Interactions

**Severity:** Medium  
**File:** `events/routes.py:276`  
**Status:** Open — requires auth design decision

---

### MED-6: No Security Headers

**Severity:** Medium  
**File:** `server.py`  
**Status:** Fixed — `after_request` hook added

---

### MED-7: Unsanitized `domain` Field as `source` Tag

**Severity:** Medium  
**File:** `spiritpool_routes.py:57–59`  
**Status:** Fixed — domain allowlist added

---

### LOW-1 through LOW-4

See summary table above. LOW-2 (geocoding with user address) and LOW-4 (hardcoded localhost URL) remain open.

---

## Open Items Requiring Architecture Decision

These require product/auth decisions before implementation:

| Item | Decision Needed |
|------|----------------|
| CRIT-1 full auth | How should Spirit Pool extensions authenticate? Shared key? OAuth? |
| HIGH-3 scan auth | Should `/api/scan` be removed from public API or require admin key? |
| HIGH-5 interactions auth | Are fake event interactions a real concern, or is this data low-stakes? |
| HIGH-2 CORS | What are the actual browser extension IDs to allowlist? |
| MED-5 IDOR | Is there a concept of "ownership" for events that needs access control? |
