# SpiritPool — Security Plan

**Date:** 2026-03-17  
**Status:** Planning — none of the below is implemented yet  
**Scope:** Extension (Firefox/Chrome/Safari) + Flask backend + SQLite/future DB

---

## 1. Data Classification

Before designing controls, we need to know exactly what data we handle and how sensitive it is.

### 1.1 What we collect

| Data | Source | Example | Classification |
|------|--------|---------|----------------|
| Job title | DOM scraping | "Shift Supervisor" | **Public** — posted openly on job sites |
| Company name | DOM scraping | "Starbucks" | **Public** |
| Location | DOM scraping | "Seattle, WA" | **Public** |
| Salary range | DOM scraping | "$18-22/hr" | **Public** (when listed) |
| Posting date | DOM scraping | "2026-03-10" | **Public** |
| Applicant count | DOM scraping | "47 applicants" | **Public** (when shown) |
| Badges | DOM scraping | "Easy Apply", "Reposted" | **Public** |
| Job URL | DOM + tab URL | `linkedin.com/jobs/view/4100123456` | **Public** |
| Store rating/reviews | DOM scraping | "4.2 stars, 89 reviews" | **Public** |
| Page URL | `sender.tab.url` | Full URL of tab when signal captured | **Sensitive** — could reveal user's browsing state |
| Contributor UUID | Extension-generated | `crypto.randomUUID()` | **Internal** — pseudonymous identifier |
| Observation timestamps | `new Date().toISOString()` | When user was on a page | **Sensitive** — reveals browsing timing |
| IP address | HTTP connection metadata | Server logs, not stored in DB | **PII** — can identify users |

### 1.2 What we do NOT collect (and must never collect)

- Passwords, cookies, session tokens
- User's name, email, resume, or profile data
- Browsing history beyond the 5 allowed domains
- DOM content outside of job listing elements
- Form field contents
- Authentication headers

### 1.3 Risk assessment

| Risk | Current state | Severity |
|------|--------------|----------|
| Page URL leaks browsing state | Stored in `observations.page_url` | **Medium** — reveals which specific search queries / job views a contributor performed |
| Timestamps enable activity profiling | `observed_at` + `collected_at` per signal | **Medium** — pattern analysis could reveal work hours, job-hunting cadence |
| Contributor UUID is a persistent tracking token | Stored forever, linked to all observations | **Medium** — long-lived pseudonym; becomes PII if correlated with IP logs |
| IP addresses in server logs | Flask default logging includes client IP | **Medium** — direct PII if server is exposed |
| No transport encryption | `http://localhost:8765` — plaintext | **Low** locally, **Critical** if deployed to network |
| No authentication on API | Anyone can POST to `/contribute` | **High** if exposed — data poisoning, DoS |
| No input validation depth | Signals accepted with minimal shape checks | **Medium** — injection via crafted signal payloads |
| CORS set to `origins: "*"` | Any webpage could POST to the API | **High** if exposed — cross-origin data poisoning |
| SQLite DB file on disk unencrypted | `data/spiritpool.db` | **Low** locally, **Medium** in shared environments |
| Extension storage unencrypted | `browser.storage.local` is plaintext on disk | **Low** — browser-level access control applies |

---

## 2. Threat Model

### 2.1 Actors

| Actor | Motivation | Capability |
|-------|-----------|------------|
| **Malicious website** | Inject false data, probe for user info | Can craft requests if CORS allows |
| **Extension store reviewer** | Ensure privacy compliance | Reviews manifest permissions, data practices |
| **Network attacker (MitM)** | Intercept signals in transit | Can read/modify HTTP traffic on shared networks |
| **Rogue contributor** | Poison the database with false listings | Can send arbitrary payloads to `/contribute` |
| **Local attacker** | Access stored data on user's machine | Can read SQLite DB, extension storage, server logs |
| **Insider/operator** | Correlate pseudonymous data with identity | Has DB access + server logs (IP, timestamps) |

### 2.2 Attack surfaces

```
                   ┌───────────────────┐
                   │ Job Listing Sites  │
                   │ (DOM is untrusted) │
                   └────────┬──────────┘
                            │ Content script reads DOM
                            ▼
   ┌─────────────────────────────────────────┐
   │        Extension (user's browser)        │
   │  ┌─────────────┐  ┌──────────────────┐  │
   │  │Content Script│→→│ Background Worker│  │  ← A: Malicious DOM injection
   │  └─────────────┘  └───────┬──────────┘  │
   │                           │              │
   │  browser.storage.local    │              │  ← B: Local data read
   └───────────────────────────┼──────────────┘
                               │ HTTP POST (plaintext)
                               │                         ← C: Network interception
                               ▼
   ┌─────────────────────────────────────────┐
   │       Flask Backend (server.py)          │
   │  /api/spiritpool/contribute              │  ← D: Unauthenticated POST
   │  /api/spiritpool/stats, /jobs            │  ← E: Data exfiltration (read)
   │                                          │
   │  data/spiritpool.db                      │  ← F: Direct DB file access
   │  Server logs (IP addresses)              │  ← G: Log-based PII leak
   └──────────────────────────────────────────┘
```

---

## 3. Security Controls — Prioritised Implementation Plan

### Priority 1: Critical (implement before any network deployment)

#### 3.1 HTTPS / TLS Transport

**Problem:** `BACKEND_URL = "http://localhost:8765"` — signals travel in plaintext.

**Fix:**
- Local dev: acceptable as-is (loopback only)
- Any network deployment: **mandatory TLS**. Options:
  - Reverse proxy (nginx/Caddy) with Let's Encrypt cert
  - Flask behind gunicorn + SSL context
- Extension must reject non-HTTPS backends when not on localhost

**Implementation:**
```javascript
// background.js — enforce HTTPS for non-local backends
const BACKEND_URL = (() => {
  const url = "http://localhost:8765/api/spiritpool"; // default
  if (!url.startsWith("https://") && !url.includes("localhost") && !url.includes("127.0.0.1")) {
    console.error("[SpiritPool] Refusing non-HTTPS remote backend");
    return null;
  }
  return url;
})();
```

#### 3.2 API Authentication

**Problem:** No auth on `/contribute` — anyone can POST arbitrary signals.

**Recommended approach: API key per contributor**
1. On first flush, extension registers with `POST /api/spiritpool/register` sending its UUID
2. Backend returns a signed API key (HMAC of UUID + server secret)
3. All subsequent requests include `Authorization: Bearer <key>`
4. Backend validates HMAC before accepting signals

**Schema changes:**
```python
# contributors table
api_key_hash = db.Column(db.String(128), nullable=True)  # bcrypt/argon2 hash
api_key_issued_at = db.Column(db.DateTime, nullable=True)
is_banned = db.Column(db.Boolean, default=False)
```

**Why not OAuth:** Overkill for anonymous contributors. The goal is to _authenticate the extension install_, not identify the user.

#### 3.3 CORS Lockdown

**Problem:** `CORS(app, resources={r"/api/spiritpool/*": {"origins": "*"}})` — any website can POST.

**Fix:**
```python
ALLOWED_ORIGINS = [
    "moz-extension://*",           # Firefox
    "chrome-extension://<ext-id>",  # Chrome (use actual extension ID)
    "safari-web-extension://*",     # Safari
]
# Only for local dev:
if app.debug:
    ALLOWED_ORIGINS.append("http://localhost:*")

CORS(app, resources={r"/api/spiritpool/*": {"origins": ALLOWED_ORIGINS}})
```

After publishing to Chrome Web Store, replace `<ext-id>` with the stable extension ID.

### Priority 2: High (implement before user-facing release)

#### 3.4 Input Validation & Sanitisation

**Problem:** Signals are accepted with minimal validation. A crafted `jobTitle` could contain XSS payloads, SQL injection attempts (ORM handles this, but defence-in-depth), or megabytes of text.

**Controls:**

| Field | Validation | Max length |
|-------|-----------|------------|
| `jobTitle` | Strip HTML tags, trim whitespace | 500 chars |
| `company` | Strip HTML tags, trim whitespace | 300 chars |
| `location` | Strip HTML tags, trim whitespace | 300 chars |
| `url` | Must match `https://(allowed domains)/*` pattern | 2000 chars |
| `salary.min/max` | Must be numeric, 0–10,000,000 | — |
| `salary.period` | Must be one of: `yearly`, `hourly`, `monthly`, `weekly` | — |
| `applicantCount` | Must be integer, 0–1,000,000 | — |
| `badges` | Must be array of strings, max 20 items, max 100 chars each | — |
| `observedAt` | Must be valid ISO 8601, not more than 24h in the past, not in the future | — |
| `source` | Must be one of known domains | — |
| `contributorId` | Must be valid UUID v4 format | 36 chars |

**Implementation:** Add a `validate_signal(signal)` function in `ingest.py` that returns `(clean_signal, errors)`.

```python
import re, html
UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$', re.I)
ALLOWED_SOURCES = {"indeed.com", "linkedin.com", "glassdoor.com", "google.com/maps", "apply.starbucks.com"}

def sanitise_text(val, max_len=500):
    if not isinstance(val, str): return None
    val = html.escape(val.strip())[:max_len]
    return val or None

def validate_signal(sig):
    errors = []
    if sig.get("source") not in ALLOWED_SOURCES:
        errors.append("invalid source")
    # ... field-by-field checks ...
    return errors
```

#### 3.5 Rate Limiting

**Problem:** No throttling — one client can flood the DB.

**Controls:**
- Per-contributor: max **100 signals per minute**, **2,000 per hour**
- Per-IP: max **10 requests per minute** to `/contribute`
- Batch size already capped at 1,000 signals per request

**Implementation:** Use `flask-limiter` with Redis or in-memory store:
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(get_remote_address, app=app, default_limits=["200/hour"])

@spiritpool_bp.route("/contribute", methods=["POST"])
@limiter.limit("10/minute")
def contribute():
    ...
```

#### 3.6 Minimise Page URL Collection

**Problem:** `page_url` is stored in every observation. A URL like `linkedin.com/jobs/search/?keywords=senior+engineer+remote` reveals the user's job search criteria.

**Options (choose one):**

| Option | Privacy | Data loss |
|--------|---------|-----------|
| **A. Drop page_url entirely** | Best | Lose referrer context |
| **B. Truncate to domain + path** | Good | Lose query params |
| **C. Hash page_url** | Good | Can't reconstruct, but still unique per URL |
| **D. Store only if user opts in** | Flexible | Requires separate consent toggle |

**Recommended: Option B** — strip query parameters:
```javascript
signal.tabUrl = sender.tab?.url
  ? new URL(sender.tab.url).origin + new URL(sender.tab.url).pathname
  : null;
```

This keeps `linkedin.com/jobs/view/4100123456` (useful for dedup) but drops `?keywords=...` (sensitive).

### Priority 3: Medium (implement for production hardening)

#### 3.7 Contributor UUID Rotation

**Problem:** The UUID is permanent — a single token that links every observation forever.

**Fix:** Rotate UUID periodically (every 30 days):
```javascript
async function getContributorId() {
  const { contributorId, contributorIdCreated } = await browser.storage.local.get([
    "contributorId", "contributorIdCreated"
  ]);
  
  const AGE_LIMIT_MS = 30 * 24 * 60 * 60 * 1000; // 30 days
  const expired = !contributorIdCreated || (Date.now() - contributorIdCreated) > AGE_LIMIT_MS;
  
  if (contributorId && !expired) return contributorId;
  
  const newId = crypto.randomUUID();
  await browser.storage.local.set({ 
    contributorId: newId, 
    contributorIdCreated: Date.now() 
  });
  return newId;
}
```

**Trade-off:** Loses ability to count unique long-term contributors. Acceptable — we care about signal volume, not contributor loyalty.

#### 3.8 Observation Timestamp Fuzzing

**Problem:** Exact timestamps (`2026-03-17T14:23:07.412Z`) reveal precisely when the user was browsing a specific job page.

**Fix:** Round to nearest 15 minutes:
```javascript
signal.collectedAt = (() => {
  const d = new Date();
  d.setMinutes(Math.round(d.getMinutes() / 15) * 15, 0, 0);
  return d.toISOString();
})();
```

#### 3.9 Log Hygiene

**Problem:** Flask logs client IP addresses by default. If stored, IPs become PII.

**Controls:**
- Do NOT log IP addresses in production
- If logging is needed for abuse detection, hash IPs with a daily-rotating salt:
  ```python
  import hashlib, os
  daily_salt = os.environ.get("LOG_SALT", "default") + datetime.now().strftime("%Y-%m-%d")
  ip_hash = hashlib.sha256((request.remote_addr + daily_salt).encode()).hexdigest()[:16]
  ```
- Set log retention: auto-delete after 7 days
- Never log the full signal payload (could contain scraped PII from job listings)

#### 3.10 Database Encryption at Rest

**Problem:** `data/spiritpool.db` is a plaintext SQLite file.

**Options:**
- **Local dev:** Acceptable as-is (single-user machine)
- **Shared server:** Use SQLCipher (encrypted SQLite) or migrate to PostgreSQL with disk encryption
- **Cloud deployment:** Use managed DB with encryption at rest (AWS RDS, Azure SQL)

#### 3.11 Content Script DOM Safety

**Problem:** Content scripts read untrusted DOM. A malicious site could craft DOM nodes to inject payloads into signals.

**Controls (already partially in place):**
- `textContent` (not `innerHTML`) for field extraction — prevents HTML injection
- Max field lengths enforced at extraction time, not just on backend
- Never `eval()` or `innerHTML` anything from the DOM into extension UI

**Additional:**
```javascript
// In scanner.js — add extraction-time sanitisation
function safeText(el, maxLen = 500) {
  if (!el) return null;
  return el.textContent.trim().substring(0, maxLen) || null;
}
```

### Priority 4: Low (future hardening)

#### 3.12 Content Security Policy for Extension Pages

Add to manifests:
```json
"content_security_policy": {
  "extension_pages": "script-src 'self'; object-src 'none'; style-src 'self' 'unsafe-inline';"
}
```

Prevents any injected scripts from running in popup/options pages.

#### 3.13 Subresource Integrity for Polyfill

If the browser polyfill is ever loaded from a CDN (currently bundled), add SRI:
```html
<script src="browser-polyfill.js" integrity="sha384-..."></script>
```

Currently not needed since polyfill is bundled.

#### 3.14 Data Retention Policy

**Problem:** Observations accumulate indefinitely.

**Policy:**
- Observations older than 90 days: aggregate into daily summaries, delete raw rows
- Contributor records older than 60 days with no activity: delete
- Implement as a scheduled maintenance task (cron job or Flask CLI command)

```python
# backend/maintenance.py
def purge_old_observations(days=90):
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    Observation.query.filter(Observation.observed_at < cutoff).delete()
    db.session.commit()
```

#### 3.15 Extension Permissions Audit

Current permissions are minimal and correct:

| Permission | Justification | Overprivileged? |
|-----------|---------------|-----------------|
| `storage` | Signal cache, consent, stats | No |
| `alarms` | Periodic flush timer | No |
| `host_permissions` (5 job sites) | Content script injection | No — site-specific, not `<all_urls>` |
| `host_permissions` (localhost) | Flush to backend | No — needed for API calls |

**If moving to remote selectors:** would need `<all_urls>` or a broader pattern. This is a significant permission escalation — document justification in store listing.

---

## 4. Privacy Compliance Considerations

### 4.1 Does SpiritPool handle "personal data"?

Under GDPR, personal data is _any information relating to an identified or identifiable natural person_.

| Data point | Personal data? | Reasoning |
|-----------|---------------|-----------|
| Job title, company, location, salary | **No** | Publicly posted, not linked to a person |
| Contributor UUID | **Possibly** | Pseudonymous identifier — can become personal data if linked to other data (e.g., IP logs) |
| Observation timestamps | **Possibly** | Combined with UUID, reveals behavioural pattern of an identifiable person |
| IP address | **Yes** | Directly identifiable |
| Page URL with search queries | **Possibly** | May reveal personal intent |

**Conclusion:** SpiritPool handles **pseudonymous data** (UUID + timestamps) that qualifies as personal data under GDPR if combined with IP addresses or other identifiers. Treat it accordingly.

### 4.2 Required privacy controls

| Requirement | Status | Implementation |
|------------|--------|----------------|
| **Lawful basis** | ✅ Consent | Consent gate in popup before any collection |
| **Purpose limitation** | ✅ Done | Consent modal explicitly describes what is collected and why |
| **Data minimisation** | ⚠️ Partial | Page URLs include query params; timestamps are exact |
| **Right to erasure** | ⚠️ Partial | Revoke consent clears local cache but NOT server-side data |
| **Right of access** | ❌ Missing | No way for a contributor to see their data on the server |
| **Data retention** | ❌ Missing | Data stored indefinitely |
| **Privacy policy** | ❌ Missing | No written privacy policy document |
| **Data processing record** | ❌ Missing | Required under GDPR Art. 30 |

### 4.3 Action items for compliance

1. **Write a privacy policy** — must cover: what data, why, how long, who has access, rights
2. **Server-side deletion endpoint** — `DELETE /api/spiritpool/contributor/<uuid>` that purges all observations for that UUID
3. **Link privacy policy** in consent modal and options page
4. **Wire revoke consent to server-side deletion** — when user revokes, also call the delete endpoint
5. **Implement data retention** — auto-purge observations older than 90 days
6. **Strip query parameters from page URLs** (§3.6 Option B)
7. **Add IP address note** to privacy policy (logged transiently, not stored in DB)

---

## 5. Implementation Roadmap

### Phase 1 — Before network deployment (immediate)

| Task | Effort | Files affected |
|------|--------|---------------|
| Lock down CORS to extension origins | 30 min | `server.py` |
| Add input validation to `ingest.py` | 2 hr | `backend/ingest.py` |
| Strip query params from page URL | 15 min | `background.js` |
| Enforce HTTPS for non-localhost backends | 15 min | `background.js` |
| Add CSP to manifests | 15 min | `manifest*.json` |

### Phase 2 — Before user-facing release

| Task | Effort | Files affected |
|------|--------|---------------|
| API key authentication | 4 hr | `backend/api.py`, `backend/models.py`, `background.js` |
| Rate limiting with flask-limiter | 1 hr | `server.py`, `requirements.txt` |
| Write privacy policy | 2 hr | New: `PRIVACY_POLICY.md`, link in popup |
| Server-side contributor deletion endpoint | 2 hr | `backend/api.py` |
| Wire revoke consent to server-side delete | 1 hr | `background.js`, `popup/popup.js` |
| Timestamp fuzzing (15-min rounding) | 30 min | `background.js` |

### Phase 3 — Production hardening

| Task | Effort | Files affected |
|------|--------|---------------|
| Contributor UUID rotation (30-day) | 1 hr | `background.js` |
| Data retention + auto-purge | 2 hr | New: `backend/maintenance.py`, cron setup |
| Log hygiene (IP hashing, rotation) | 1 hr | `server.py` |
| DB encryption at rest | Varies | Deployment config |
| Security headers (HSTS, X-Content-Type, etc.) | 30 min | `server.py` |

---

## 6. Security Checklist (pre-release gate)

- [ ] CORS restricted to known extension origins
- [ ] API key authentication on `/contribute`
- [ ] Rate limiting active (10 req/min per IP, 100 signals/min per contributor)
- [ ] All signal fields validated and length-capped
- [ ] Page URLs stripped of query parameters
- [ ] HTTPS enforced for all non-localhost backend communication
- [ ] Contributor UUID rotates every 30 days
- [ ] Observation timestamps rounded to 15-minute intervals
- [ ] Server-side contributor deletion endpoint working
- [ ] Privacy policy written and linked in extension
- [ ] Data retention policy (90-day purge) implemented
- [ ] No IP addresses stored in database or persistent logs
- [ ] CSP set for extension pages
- [ ] Console debug logging removed from production builds
- [ ] Extension permissions are minimal (no `<all_urls>`)
