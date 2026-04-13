# 3. SpiritPool Intake Pipeline

> **Audience:** Developers and agents working on the contributor data path (FH-0/FH-1).
>
> **Status:** Tables created, endpoints implemented, privacy controls active. Integration tests (T4.1) and legacy compatibility (T3.3) pending.

---

## What Is SpiritPool?

SpiritPool is a **Manifest V3 browser extension** that runs in the user's browser. It extracts structured data from allowlisted sites as the user browses, caches signals locally, and periodically flushes them to First Helios via HTTPS POST.

Contributors participate under explicit consent. They can pause collection, toggle sites on/off, or revoke consent at any time.

**Extension repo:** `ChainStaffingTracker/spiritpool/` (separate repository)

### Supported Sites

| Domain | Sites |
|--------|-------|
| **Jobs** | Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs |
| **Business** | Google Maps (reviews, ratings) |
| **Events** | Eventbrite, Meetup, Do512 (planned) |

---

## Pipeline Architecture

```
Browser Extension
    │
    │  POST /api/contribute
    │  { session_token, epoch_id, event_type, source, domain, payload }
    │
    ▼
┌────────────────────────────────────────────────┐
│  1. IP Suppression (middleware)                 │
│     request.remote_addr → "0.0.0.0"            │
│     Log formatter strips IPv4/IPv6 patterns    │
└──────────────────┬─────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────┐
│  2. Field Stripping                             │
│     Remove: tabUrl, collectedAt                 │
│     From: top-level body AND nested payload     │
└──────────────────┬─────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────┐
│  3. Validate Required Fields                    │
│     session_token (string), epoch_id (int ≥ 1) │
│     event_type ∈ {job_listing, salary_signal,   │
│       business_review, event_listing}           │
│     source (string), domain ∈ {jobs, events,    │
│       business}, payload (non-empty dict)       │
└──────────────────┬─────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────┐
│  4. Server-Side Field Assignment                │
│     event_id = uuid4()                          │
│     collected_at = datetime.utcnow()            │
│     pipeline_version = 1                        │
└──────────────────┬─────────────────────────────┘
                   ▼
┌────────────────────────────────────────────────┐
│  5. PII Scan (payload only)                     │
│     Recursive walk of all string values         │
│     Patterns: email, phone (3), SSN, credit_card│
│     Result: list of matched types or []         │
└──────────┬───────────────────┬─────────────────┘
           │                   │
     PII detected         Clean payload
           │                   │
           ▼                   ▼
┌──────────────────┐ ┌────────────────────┐
│  → quarantine    │ │  → sp_events       │
│  original_payload│ │  event_id          │
│  redaction_types │ │  session_token     │
│  rule_version    │ │  epoch_id          │
└──────────────────┘ │  event_type        │
                     │  payload (JSONB)   │
                     │  source_type       │
                     │  collected_at      │
                     │  pipeline_version  │
                     └────────┬───────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │  6. Auto-Create       │
                  │  session_epochs       │
                  │  (first POST per      │
                  │   session_token)      │
                  └───────────────────────┘
```

---

## The Five Tables

### sp_events (Operational)
Forward-compatible signal storage. Accepts job listings, salary signals, business reviews, and event listings.

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| `event_id` | VARCHAR (UUID) | Server-generated | Primary key, `uuid4()` |
| `session_token` | TEXT | Client | No length/format constraint — accepts 36-char UUID and 64-char hex |
| `epoch_id` | INTEGER | Client | Consent version counter, no upper bound |
| `event_type` | VARCHAR | Client | `job_listing`, `salary_signal`, `business_review`, `event_listing` |
| `payload` | JSONB | Client | Structured extraction data; unknown fields preserved |
| `source_type` | VARCHAR | Server | Default `extension` |
| `collected_at` | DATETIME | Server | `datetime.utcnow()`, never from client |
| `pipeline_version` | INTEGER | Server | PII rule version, starts at 1 |

**Indexes:** `(session_token, epoch_id)`, `(event_type, collected_at)`

### quarantine (Metadata)
PII-flagged payloads held for internal audit. Never queryable by external APIs or dashboards.

| Column | Type | Notes |
|--------|------|-------|
| `quarantine_id` | VARCHAR (UUID) | Primary key |
| `original_payload` | JSONB | Complete original event body |
| `redaction_types` | TEXT | JSON-encoded array, e.g. `["email", "phone"]` |
| `rule_version` | INTEGER | Matches pipeline_version |
| `quarantined_at` | DATETIME | Server-set |

### session_epochs (Operational)
Tracks session token lifecycle. One row per unique `session_token`.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Auto-increment PK |
| `session_token` | TEXT | UNIQUE constraint |
| `epoch_id` | INTEGER | Latest epoch for this token |
| `contributor_id` | INTEGER | FK → contributors.id, nullable (set NULL on burn) |
| `created_at` | DATETIME | First POST timestamp |
| `burned_at` | DATETIME | Nullable — set on burn operation |

### burn_pool (Operational)
Monthly aggregate of burned sessions. 1-year TTL enforced by daily cleanup job.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Auto-increment PK |
| `session_token` | TEXT | The burned token |
| `month_key` | VARCHAR | Format: `YYYY-MM` |
| `signal_count` | INTEGER | Incremented on burn |
| `burned_at` | DATETIME | When the burn occurred |
| `expires_at` | DATETIME | `burned_at + 1 year`, enforced by scheduled cleanup |

### contributors (Operational)
Anonymous contributor volume tracking. No PII stored.

| Column | Type | Notes |
|--------|------|-------|
| `id` | INTEGER | Auto-increment PK |
| `display_name` | VARCHAR | Optional, user-chosen |
| `created_at` | DATETIME | Registration timestamp |
| `is_active` | BOOLEAN | Default true |

---

## Endpoints

### POST /api/contribute
**File:** `core/contribute_routes.py`
**Blueprint:** `contribute_bp`

Accepts a single signal from the SpiritPool extension. Processing order is fixed and non-negotiable (see pipeline diagram above).

**Request body:**
```json
{
  "session_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "epoch_id": 1,
  "event_type": "job_listing",
  "source": "indeed",
  "domain": "jobs",
  "payload": {
    "company": "Whole Foods Market",
    "jobTitle": "Grocery Team Member",
    "location": "Austin, TX 78701",
    "salary": { "min": 16, "max": 20, "period": "hourly" }
  }
}
```

**Responses:**
- `200` — Signal stored in `sp_events` (clean) or `quarantine` (PII detected)
- `400` — Validation error (missing/invalid fields)

### POST /api/burn
**File:** `core/contribute_routes.py`
**Blueprint:** `contribute_bp`

Session burn (anonymization). Severs the link between a session token and its contributor.

**Request body:**
```json
{
  "session_token": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
}
```

**Effects:**
1. Sets `session_epochs.contributor_id = NULL`
2. Sets `session_epochs.burned_at = NOW()`
3. Increments/creates `burn_pool` entry for current month
4. Returns `200`

### POST /api/spiritpool/contribute (Legacy)
**File:** `postings/spiritpool_routes.py`
**Blueprint:** `spiritpool_bp`

Legacy format from the v1 extension. Uses `contributorId`, `domain`, `signals[]` batch format. Writes to `job_postings` table. Will be maintained during transition (T3.3) with optional dual-write to `sp_events`.

---

## Burn Mechanism

The burn operation supports contributor privacy by severing the link between a session token and its contributor identity.

```
Before burn:
  session_epochs: session_token=abc, contributor_id=7, burned_at=NULL

After burn:
  session_epochs: session_token=abc, contributor_id=NULL, burned_at=2026-04-05T...
  burn_pool: session_token=abc, month_key=2026-04, signal_count=+1, expires_at=2027-04-05T...
```

**Burn pool cleanup:** Daily cron job (`burn_pool_cleanup` in `config/scheduler.yaml`) deletes expired records:
```sql
DELETE FROM burn_pool WHERE expires_at < NOW()
```
This runs at 02:45 UTC daily. Implemented in `core/scheduler.py:_run_burn_pool_cleanup()`.

---

## Session Lifecycle

```
First POST per session_token
  → Auto-create session_epochs row (created_at = NOW)

Subsequent POSTs
  → session_epochs.epoch_id updated if higher

Burn request
  → session_epochs.contributor_id = NULL
  → session_epochs.burned_at = NOW()
  → burn_pool entry created/incremented

Burn pool expiry (1 year)
  → burn_pool row deleted by daily cleanup
  → session_epochs row persists (burned_at stays set)
```

---

## Forward Compatibility

The pipeline is designed to survive across Helios eras without schema changes:

| Feature | How It's Handled |
|---------|-----------------|
| **Token format changes** | `session_token` is TEXT with no length/format constraint. Accepts 36-char UUID (First Helios) and 64-char hex (Second Helios). |
| **Epoch growth** | `epoch_id` is INTEGER with no upper bound constraint. |
| **New payload fields** | JSONB `payload` stores unknown fields without error. |
| **New PII patterns** | `pipeline_version` enables re-processing: bump version, re-scan quarantine. |
| **New event types** | `event_type` validation is a server-side allow-list, easily extended. |
| **New domains** | `domain` validation is a server-side allow-list, easily extended. |

---

## Related Files

| File | Purpose |
|------|---------|
| `core/contribute_routes.py` | Endpoint implementations |
| `core/privacy.py` | `strip_forbidden_fields()`, `scan_pii()` |
| `core/models/spiritpool.py` | ORM models for all 5 tables |
| `core/database.py` | Base class, engine setup, model imports |
| `config/scheduler.yaml` | `burn_pool_cleanup` job schedule |
| `core/scheduler.py` | `_run_burn_pool_cleanup()` function |
| `alembic/versions/ae445d02acad_*.py` | Migration creating 5 tables |
| `scripts/populate_metadata.py` | Metadata registration for all 5 tables |
| `docs/contracts/` | SLA contracts for sp_events, quarantine, session_epochs, burn_pool |
