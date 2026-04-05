# SpiritPool — Master Context for First Helios Agents

> **Purpose:** This document gives a First Helios agent everything it needs to know about the SpiritPool browser extension — what it is, what it does, what it sends, what it expects from the backend, and what security contracts it enforces. Read this before processing any FH-* handoff document.

---

## 1. What Is SpiritPool?

SpiritPool is a **browser extension** (Manifest V3) that collects public signals from job boards, business directories, and event sites as the user browses. It has **no backend, no database, and no frontend of its own**. It encrypts signals locally, anonymises them, and POSTs them over HTTPS to First Helios.

**First Helios** owns the API, database, scoring engine, dashboard, and all server-side infrastructure. SpiritPool is exclusively the client-side data collection tool.

**Repo locations:**
- SpiritPool: `/home/fortune/CodeProjects/ChainStaffingTracker/spiritpool/`
- First Helios: `/home/fortune/CodeProjects/First-Helios/`
- Schema docs: `First-Helios/docs/data/dictionary/`

---

## 2. Extension Architecture

```
USER BROWSER                                 FIRST HELIOS (separate repo)
(SpiritPool installed)                       (backend + dashboard)

┌──────────────────────────────────┐         ┌──────────────────────────┐
│ Content Scripts                  │         │                          │
│  indeed.js · linkedin.js         │         │  POST /api/contribute    │
│  google-maps.js · glassdoor.js   │         │     │                    │
│  ziprecruiter.js · google-jobs.js│         │  ┌──▼───────────────┐    │
│  (future: eventbrite, meetup,    │         │  │ Intake endpoint  │    │
│   do512, traffic sources)        │         │  │ IP suppress      │    │
│          │                       │         │  │ Field strip      │    │
│  ┌───────▼────────┐             │         │  │ PII quarantine   │    │
│  │ M3: Encrypt    │             │         │  └──┬───────────────┘    │
│  │ AES-256-GCM    │             │         │     │                    │
│  │ cache to       │             │         │  ┌──▼───────────────┐    │
│  │ storage.local  │             │         │  │ Events table     │    │
│  └───────┬────────┘             │         │  │ Quarantine table │    │
│          │ flush timer           │         │  │ SessionEpoch     │    │
│  ┌───────▼────────┐             │         │  │ BurnPool         │    │
│  │ M3: Decrypt    │             │         │  └──────────────────┘    │
│  └───────┬────────┘             │         │                          │
│  ┌───────▼────────┐             │         │  Scoring · Dashboard     │
│  │ M4: Sanitize   │  HTTPS      │         │  Scheduler · Pipeline    │
│  │ strip/fuzz/    │────────────►│         │                          │
│  │ attach token   │             │         └──────────────────────────┘
│  └───────┬────────┘             │
│          │                       │
│  M5: Signed remote selectors     │
│  M7: Session token + consent     │
│                                  │
│  Popup · Options · Consent UI    │
└──────────────────────────────────┘
```

### Boundary Rule

Everything to the **left** of the HTTPS arrow is SpiritPool. Everything to the **right** is First Helios. When SpiritPool work depends on backend capabilities, it produces a handoff document (FH-*) and drops it in `First-Helios/agentinbox/`.

---

## 3. What SpiritPool Sends

### 3.1 POST Payload Contract

SpiritPool POSTs signals to `POST /api/contribute`:

```json
{
  "session_token": "string (opaque — UUID now, 64-char hex later)",
  "epoch_id": "integer",
  "event_type": "string — one of: 'job_listing', 'salary_signal', 'business_review', 'event_listing'",
  "source": "string — 'indeed', 'linkedin', 'glassdoor', 'ziprecruiter', 'google_maps', 'google_jobs'",
  "domain": "string — 'jobs', 'events', 'business'",
  "payload": { "...structured extraction data — fields vary by source..." }
}
```

### 3.2 Data Classification

| Field | Sent? | Treatment | Backend Stores? |
|---|---|---|---|
| `jobTitle` | Yes | As-is | Yes (indexed) |
| `company` | Yes | As-is | Yes (indexed) |
| `location` | Yes | As-is | Yes (indexed) |
| `salary` | Yes | Fuzzed ±5% per bound | Fuzzed value |
| `postingDate` | Yes | Rounded to nearest day | Day precision |
| `applicantCount` | Yes | Fuzzed ±5%, rounded to int | Fuzzed value |
| `badges` | Yes | As-is | Yes |
| `url` | Yes | As-is (canonical listing URL) | Yes |
| `observedAt` | Yes | Fuzzed ±15 min | Fuzzed value |
| `session_token` | Yes | UUID (30-day rotation) | Yes (index key) |
| `epoch_id` | Yes | Integer counter | Yes (index key) |
| `consent_state` | **No** | Validated locally only | **No** |
| `tabUrl` | **NEVER** | Stripped before POST | **NEVER** |
| `collectedAt` | **NEVER** | Stripped before POST | **NEVER** |
| IP address | Unavoidable (HTTP) | — | **NEVER LOGGED** |

### 3.3 Fields the Backend Sets Server-Side

- `collected_at` — server timestamp (replaces stripped `collectedAt`)
- `event_id` — generated UUID
- `pipeline_version` — integer, starts at 1 (tracks which PII rule version processed the event)

### 3.4 Fields SpiritPool Never Sends (Defence-in-Depth)

The extension already strips these. The backend must **also** strip them before any processing in case of a bug or old extension version:

- `tabUrl` — full browser tab URL containing session state, referral, user context
- `collectedAt` — client-side timestamp
- IP addresses — must never be logged anywhere

---

## 4. Content Scripts — Active Sources

SpiritPool has 6 active content scripts. Each runs on its respective site, extracts structured data from the DOM, and feeds it through the encrypt → sanitize → POST pipeline.

| Script | Site | event_type | domain | Tier |
|---|---|---|---|---|
| `indeed.js` | Indeed.com | `job_listing` | `jobs` | Bronze |
| `linkedin.js` | LinkedIn.com | `job_listing` | `jobs` | Bronze |
| `glassdoor.js` | Glassdoor.com | `job_listing` / `salary_signal` | `jobs` | Bronze |
| `ziprecruiter.js` | ZipRecruiter.com | `job_listing` | `jobs` | Bronze |
| `google-maps.js` | Google Maps | `business_review` | `business` | Bronze |
| `google-jobs.js` | Google Jobs | `job_listing` | `jobs` | Bronze |

**Planned Phase 3 sources:**
- `eventbrite.js` — `event_listing` — `events`
- `meetup.js` — `event_listing` — `events`
- `do512.js` — `event_listing` — `events`

All content scripts produce signals conforming to the canonical field set in §3.2. The `payload` JSONB varies by source but always includes the core fields where available.

---

## 5. Security Missions

SpiritPool defines five security missions (M3–M7). The backend is directly responsible for M6. The other missions run extension-side but define contracts the backend must honour.

### M3 — Local Cache Encryption
Encrypt all signal batches in `browser.storage.local` using AES-256-GCM. Key generated via `crypto.subtle.generateKey`, stored as JWK. Encrypt-on-write (random 12-byte IV), decrypt-on-flush. Cache entries tagged `v:1`.

### M4 — Pre-Transmission Anonymization
`sanitizeForTransmit(signal)` strips `tabUrl` and `collectedAt`, fuzzes salary/applicantCount/observedAt/postingDate, attaches `session_token` and `epoch_id`. Runs before every POST.

### M5 — Remote Config Signing
Ed25519 signature verification for remote selector configs. Configs that fail signature or schema validation are rejected; bundled selectors used as fallback. Size limit: 100KB.

### M6 — Backend Hardening (First Helios Responsibility)
**This is the backend's job.** Detailed in FH-1. Covers:
- IP suppression middleware
- Server-side field stripping (`tabUrl`, `collectedAt`)
- PII quarantine pipeline (regex gate for email, phone, SSN, CC)
- Forward-compatible schema
- Integration tests §8.1–8.5

### M7 — Session Token & Consent State
Full session token lifecycle:
- `session_token`: `crypto.randomUUID()` (UUID v4, 36-char string)
- Auto-rotation: every 30 days OR on consent change
- `epoch_id`: integer counter, increments on every rotation
- Burn mechanism: user can dissociate session from UUID identity
- No token history stored (a stored list would be a behavioural timeline)

---

## 6. Session Token & Consent Architecture

### 6.1 Session Token Lifecycle

```
Generation:  crypto.randomUUID()  →  36-char UUID v4
Storage:     localStorage (session_token, session_token_created, consent_version)
Rotation:    30-day cycle OR immediate on consent change
On rotate:   New UUID generated, epoch_id incremented, old token discarded (no history)
On burn:     POST to backend burn endpoint → contributor_id set to NULL → new token
```

### 6.2 Consent State Shape

```js
{
  sites_enabled:        string[],   // domain list the user has enabled
  categories_excluded:  string[],   // signal categories excluded
  collection_active:    boolean,    // master on/off switch
  consent_version:      integer     // always equals epoch_id
}
```

**Rules:**
- `consent_state` is **never transmitted** in payloads (linkability risk)
- Any change to consent state → immediate `session_token` rotation
- `consent_version` must always equal `epoch_id` at every observable point in time
- This shape persists through all eras (Second Helios adds signature, Third adds EDN fields)

### 6.3 Burn Mechanism

1. User initiates burn for current session
2. Extension POSTs `{ session_token, burned_at }` to backend burn endpoint
3. Backend: set `session_epochs.contributor_id = NULL` (dissociate from UUID parent)
4. Backend: increment `burn_pool` for current month
5. Extension: rotate to new token immediately
6. `burn_pool` entry auto-deleted after 1 year

Result: burned sessions still exist as anonymous observations, but cannot be attributed to any identity.

---

## 7. Three-Era Upgrade Path

SpiritPool and First Helios evolve through three eras. The schema is designed for forward-compatibility across all three — **no migrations required**.

### First Helios (Now)

| Component | Implementation |
|---|---|
| Cache encryption | AES-256-GCM, random key stored as JWK, `v:1` |
| `session_token` | UUID v4 string (36 chars) |
| Transit security | Strip fields, fuzz values, attach token |
| Backend storage | TEXT columns, JSONB payload, regex PII gate |

### Second Helios (Future)

| Component | Upgrade |
|---|---|
| Cache encryption | HKDF-derived key from root key, non-extractable, `v:2` |
| `session_token` | HMAC-SHA256 hex (64 chars) — deterministic, verifiable |
| Transit security | Certificate-gated transmission, signed consent state |
| Backend storage | NER (Presidio) as Stage 2 PII, cert-gated writes, behavioural index |

### Third Helios (Future)

| Component | Upgrade |
|---|---|
| Cache encryption | Two HKDF-derived keys (user + EDN), `v:3` |
| `session_token` | VOPRF-blinded token (64 chars) — server signs without seeing it |
| Transit security | Blind signatures, EDN cache ingestion |
| Backend storage | Combinability analysis, re-id game, synthetic replacement |

### Critical Invariant

`session_token` is always **TEXT** with **no length or format constraints**. The backend must:
- Never parse, validate, or assume the internal format of `session_token`
- Accept both 36-char UUID and 64-char hex without error
- Index on `(session_token, epoch_id)` — index structure never changes

---

## 8. Backend Schema (Reference)

These tables live in First Helios. Full DDL is in the FH-0 handoff document.

| Table | Purpose |
|---|---|
| `events` | Stored signals: session_token, epoch_id, payload (JSONB), pipeline_version, collected_at |
| `quarantine` | PII-flagged events — never queryable externally |
| `session_epochs` | Links session_token → contributor UUID (nullable on burn) |
| `burn_pool` | Monthly aggregate tombstone for burned sessions, auto-expires after 1 year |
| `contributors` | Per-install anonymous UUID identity |

---

## 9. Integration Test Criteria (§8.1–8.5)

These tests must pass before the backend ships. They validate the contract between SpiritPool and First Helios.

### 8.1 End-to-End Signal Flow
- **Input:** Signal with salary 75000, exact timestamp, `tabUrl`, `collectedAt`
- **Expected:** Event in `events` table — no `tabUrl`, no `collectedAt`, server timestamp, no IP in any log, `session_token`/`epoch_id` match, `pipeline_version = 1`

### 8.2 PII Defence-in-Depth
- **Input:** Signal with `test@example.com` in payload
- **Expected:** Extension does NOT catch (not its job). Backend PII engine catches → `quarantine` record with `redaction_types: ['email']`. Event does NOT appear in `events`.

### 8.3 Config Signing Attack
- Extension-only test. Backend validates it doesn't crash on signals from extension using fallback selectors.

### 8.4 Token Rotation
- **Input:** 30+ day old token → auto-rotated
- **Expected:** Old token absent from all storage/logs. New token/epoch in subsequent POSTs.

### 8.5 Forward-Compatibility
- **Input:** `session_token` = 64-char hex; `epoch_id` = large int; unknown `consent_state` fields
- **Expected:** All stored successfully in JSONB. No errors. Failure = forward-compat bug that must be fixed before ship.

---

## 10. Extension File Index

```
spiritpool/
├── manifest.json             # Firefox (MV3, load directly)
├── manifest.chrome.json      # Chrome (copied by build.sh)
├── manifest.safari.json      # Safari (xcrun conversion)
├── background.js             # Service worker: queue, encrypt, flush
├── build.sh                  # → dist/chrome/ and dist/safari/
├── agent.md                  # Mission specs, security rules, test criteria
│
├── content/                  # One script per site
│   ├── indeed.js
│   ├── linkedin.js
│   ├── glassdoor.js
│   ├── ziprecruiter.js
│   ├── google-maps.js
│   └── google-jobs.js
│
├── shared/
│   ├── api.js                # POST to /api/contribute
│   ├── consent.js            # Consent state management (wraps M7)
│   ├── parser.js             # DOM extraction utilities
│   ├── scanner.js            # DOMScanner, remote config loading
│   ├── highlight.js          # Visual feedback on collected elements
│   ├── selectors.json        # Bundled selectors (primary path)
│   ├── crypto.js             # (M3) AES-256-GCM — not yet created
│   ├── sanitize.js           # (M4) anonymization — not yet created
│   ├── config-verify.js      # (M5) Ed25519 verify — not yet created
│   └── session.js            # (M7) token lifecycle — not yet created
│
├── popup/                    # Contribution stats, site toggles
├── options/                  # Privacy settings, per-site consent
├── compat/browser-polyfill.js
└── icons/
```

**Mission files not yet created:** `crypto.js` (M3), `sanitize.js` (M4), `config-verify.js` (M5), `session.js` (M7). These are specified in `spiritpool/agent.md` and will be implemented in SpiritPool phases.

---

## 11. What First Helios Must Build (Summary)

1. **FH-0: Intake Foundation** — `POST /api/contribute` endpoint + `events`, `session_epochs`, `burn_pool`, `contributors` tables. This is the minimum viable backend for SpiritPool to start flushing signals.

2. **FH-1: Backend Hardening (M6)** — IP suppression, field stripping, PII quarantine pipeline, quarantine table. Security gate — nothing ships to users until this passes.

3. **FH-2: Source Onboarding** — For each new content script, accept new `event_type`/`source` values and document dedup keys. No code changes needed (JSONB is flexible), but dedup keys must be documented for scoring queries.

See the individual FH-* documents for full implementation specs.

---

## 12. Key Rules for Backend Implementation

1. **Never log IP addresses.** Override framework defaults. Grep test: zero IPv4/IPv6 matches in all logs and DB.
2. **Never store `tabUrl` or `collectedAt`.** Strip server-side even if the extension already stripped them.
3. **`session_token` is TEXT, no constraints.** Must accept UUID (36 chars) and hex (64 chars) without error.
4. **`payload` is JSONB.** Store unknown fields from future eras without error.
5. **PII → quarantine, not drop.** Events matching PII patterns go to quarantine table with `redaction_types` array.
6. **`pipeline_version` tracks rule version.** Enables re-processing old events through future NER pipeline.
7. **`consent_state` is never stored.** It exists only in the extension. Do not create a consent column.
8. **forward-compat test (§8.5) must pass before ship.** 64-char hex token, large epoch_id, unknown JSONB fields — all must store without error.
