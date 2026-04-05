# Development Requirements Plan — Data Policy & Quality Control

> **Stage:** FH-0 (Intake Foundation) + FH-1 (Backend Hardening)
> **Date:** 2026-04-05
> **Scope:** Secure, transparent data infrastructure for all-domain ingestion and contributor trust

---

## 1. Executive Summary

First Helios is a **broad-scope data intelligence platform** that ingests structured data across every domain relevant to a regional labor market and community — jobs, events, businesses, wages, economic indicators, mobility, and more — and serves it through dashboards people actually use.

Data arrives from two paths: **automated collectors** (APIs, scrapers, BLS feeds) and **SpiritPool contributors** (real people who donate signals via a browser extension as they browse). Contributors participate because the system earns trust through visible privacy controls and honest governance.

The platform operates on three foundational commitments:
- **Secure data & profiles** — Contributor identity is protected by design. PII is quarantined, not stored. IP addresses are never logged. Session tokens are opaque and unrecoverable.
- **Transparent systems** — Every table is documented. Every data flow has lineage. Collection health is visible. Nothing is a black box.
- **Broad collection under trust** — The platform collects widely but responsibly. Contributors see that their data is governed. Quarantine rates and pipeline health are public metrics.

This plan defines every requirement — organized by category — that must be satisfied before the contributor intake pipeline ships to production. These requirements apply equally to automated and contributor data paths.

The requirements are grouped into five pillars:
1. **Schema & Storage** — Forward-compatible tables for all-domain signal intake
2. **Privacy & Security** — IP suppression, field stripping, PII quarantine
3. **Data Quality** — Metadata registration, validation, SLA enforcement
4. **API Contract** — Endpoint behavior, error handling, response codes
5. **Observability** — Job logging, health monitoring, audit trail, transparency metrics

---

## 2. Schema & Storage Requirements

### 2.1 Forward-Compatible Events Table

| Requirement | Detail |
|-------------|--------|
| `event_id` | UUID primary key, server-generated |
| `session_token` | TEXT, no length/format constraints. Must accept 36-char UUID (First Helios) and 64-char hex (Second Helios) |
| `epoch_id` | INTEGER, no upper bound constraint |
| `event_type` | TEXT, one of: `job_listing`, `salary_signal`, `business_review`, `event_listing` |
| `payload` | JSONB, must store unknown fields from future eras without error |
| `source_type` | TEXT, default `extension` |
| `collected_at` | TIMESTAMPTZ, server-set `NOW()`, never from client |
| `pipeline_version` | INTEGER, server-set, starts at 1 |
| **Indexes** | `(session_token, epoch_id)`, `(event_type, collected_at)` |
| **No FK** | No foreign key from events to session_epochs — relationship via text match only |

**Acceptance criteria:**
- [ ] 64-char hex session_token stores without truncation or error
- [ ] epoch_id = 999999 stores without overflow
- [ ] Unknown JSONB fields in payload preserved exactly
- [ ] collected_at always reflects server time, never client

### 2.2 Session Epochs Table

| Requirement | Detail |
|-------------|--------|
| `session_token` | TEXT, UNIQUE |
| `epoch_id` | INTEGER |
| `contributor_id` | FK to contributors, nullable (set to NULL on burn) |
| `created_at` | TIMESTAMPTZ, default NOW() |
| `burned_at` | TIMESTAMPTZ, nullable |

**Acceptance criteria:**
- [ ] Row created on first POST per session_token
- [ ] contributor_id can be set to NULL (burn operation)
- [ ] Multiple tokens can exist for same contributor

### 2.3 Quarantine Table

| Requirement | Detail |
|-------------|--------|
| `quarantine_id` | UUID primary key |
| `original_payload` | JSONB, complete original event |
| `redaction_types` | TEXT array — e.g., `['email']`, `['phone', 'ssn']` |
| `rule_version` | INTEGER, matches pipeline_version logic |
| `quarantined_at` | TIMESTAMPTZ, default NOW() |

**Acceptance criteria:**
- [ ] PII-flagged events stored here, NOT in events table
- [ ] redaction_types accurately lists all patterns that triggered quarantine
- [ ] Quarantined events never queryable by external APIs or dashboards

### 2.4 Burn Pool Table

| Requirement | Detail |
|-------------|--------|
| `month_key` | TEXT, format `YYYY-MM` |
| `signal_count` | INTEGER, incremented on burn |
| `burned_at` | TIMESTAMPTZ |
| `expires_at` | TIMESTAMPTZ, burned_at + 1 year |

**Acceptance criteria:**
- [ ] Monthly aggregate only — no per-session burn records
- [ ] Maintenance job: `DELETE FROM burn_pool WHERE expires_at < NOW()`
- [ ] expires_at enforced (daily cleanup sufficient)

### 2.5 Contributors Table

| Requirement | Detail |
|-------------|--------|
| `uuid` | TEXT, UNIQUE, per-install anonymous identity |
| `total_signals` | INTEGER, default 0, incremented on ingest |
| `created_at` | TIMESTAMPTZ |

**Acceptance criteria:**
- [ ] No PII stored — uuid is extension-generated, opaque
- [ ] total_signals tracks volume only, not content

### 2.6 Migration Strategy

- All new tables created via Alembic migration
- Migration must be additive — no changes to existing tables
- Existing `job_postings` pipeline continues to function unmodified
- Dual-write period: SpiritPool signals go to both `job_postings` (legacy) and `events` (new) until legacy path is deprecated

---

## 3. Privacy & Security Requirements

### 3.1 IP Suppression (Critical — Priority 1)

| Requirement | Detail |
|-------------|--------|
| Middleware | Strip client IP from request context before any handler runs |
| Flask logging | Override default access log format to exclude IP |
| Error logs | No IP in exception handlers or error responses |
| Database | No IP column in any table, no IP in any JSONB payload |
| **Verification** | `grep -rP '\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}' logs/ data/` returns zero matches |

**Acceptance criteria:**
- [ ] Zero IPv4 patterns in any log file or database row
- [ ] Zero IPv6 patterns in any log file or database row
- [ ] Custom Flask request handler that never accesses `request.remote_addr`

### 3.2 Field Stripping (Defence-in-Depth)

| Requirement | Detail |
|-------------|--------|
| `tabUrl` | Deleted from all payloads before any processing |
| `collectedAt` | Deleted from all payloads before any processing |
| Scope | Strip from top-level body AND from nested `payload` dict |
| Timing | Strip immediately after JSON parsing, before validation or storage |

**Acceptance criteria:**
- [ ] `tabUrl` never appears in events, quarantine, or any log
- [ ] `collectedAt` never appears in events, quarantine, or any log
- [ ] Stripping happens even if extension already stripped them (no-op is fine)

### 3.3 PII Quarantine Pipeline

| Pattern | Regex | Priority |
|---------|-------|----------|
| Email | `[^@\s]+@[^@\s]+\.[^@\s]+` | P1 |
| US phone | `\b\d{3}[-.]?\d{3}[-.]?\d{4}\b` | P1 |
| US phone (parens) | `\(\d{3}\)\s?\d{3}[-.]?\d{4}` | P1 |
| International phone | `\+\d{7,15}` | P1 |
| US SSN | `\b\d{3}-\d{2}-\d{4}\b` | P1 |
| Credit card | `\b\d{13,19}\b` | P2 |

**Processing logic:**
1. Parse `payload` JSONB recursively — check all string values at every nesting level
2. Test each string against all PII patterns
3. If ANY match → quarantine table with redaction_types
4. If no match → events table normally
5. Return 200 to the extension in both cases (session continues unaffected)

**Acceptance criteria:**
- [ ] Email in any nested field → quarantine with `['email']`
- [ ] Phone number → quarantine with `['phone']`
- [ ] SSN pattern → quarantine with `['ssn']`
- [ ] Multiple PII types → quarantine with all matching types
- [ ] Clean payloads flow to events unaffected
- [ ] Extension always receives 200

---

## 4. API Contract Requirements

### 4.1 POST /api/contribute (New Intake Endpoint)

**Request body:**
```json
{
  "session_token": "string (opaque TEXT)",
  "epoch_id": "integer",
  "event_type": "string",
  "source": "string",
  "domain": "string",
  "payload": { "...structured extraction data..." }
}
```

**Processing order:**
1. Strip `tabUrl` and `collectedAt` from body and body.payload
2. Validate required fields: session_token, epoch_id, event_type, source, domain, payload
3. Set server-side fields: event_id (UUID), collected_at (NOW), pipeline_version (1)
4. Run PII scan on all string values in payload
5. If PII detected → insert into quarantine, return 200
6. If clean → insert into events, return 200
7. On first POST for a given session_token → create session_epochs row

**Response codes:**
| Code | Condition |
|------|-----------|
| 200 | Success (event stored or quarantined) |
| 400 | session_token or epoch_id missing |
| 400 | event_type, source, domain, or payload missing |

**Constraints:**
- No detailed error bodies for auth failures
- No IP in response headers or logs
- Max request body: 1 MB (consistent with existing server.py limit)

### 4.2 POST /api/burn (Burn Endpoint)

**Request body:**
```json
{
  "session_token": "string",
  "burned_at": "ISO 8601 timestamp"
}
```

**Processing:**
1. Set `session_epochs.contributor_id = NULL` for matching token
2. Set `session_epochs.burned_at = NOW()`
3. Increment `burn_pool` for current month_key (YYYY-MM)
4. Return 200

### 4.3 Backward Compatibility

- `POST /api/spiritpool/contribute` continues to work for existing extension versions
- `GET /api/spiritpool/stats` and `/insights` continue to query `job_postings`
- No existing endpoint behavior changes
- All existing automated collector pipelines (jobs, events, labor market, business) continue unmodified
- The `/api/contribute` endpoint is the new universal contributor intake — it accepts all domains (`jobs`, `events`, `business`) through one path

---

## 5. Data Quality Requirements

### 5.1 Metadata Registration

Before any new table is populated, these metadata entries MUST exist:

| Table | meta_table_catalog | meta_column_catalog | meta_data_lineage |
|-------|-------|-------|-------|
| events | Required | Required (all columns) | Required (→ scoring, → dashboards) |
| quarantine | Required | Required (all columns) | Required (← events intake) |
| session_epochs | Required | Required (all columns) | Required (← events intake) |
| burn_pool | Required | Required (all columns) | Required (← burn endpoint) |
| contributors | Required | Required (all columns) | Required (← session_epochs) |

### 5.2 Data Contracts

Create data contracts in `docs/contracts/` for:

- [ ] `events_contract.md` — Accuracy, freshness SLA, coverage, what can break, fallback
- [ ] `quarantine_contract.md` — Access restrictions, audit procedures, re-processing rules
- [ ] `session_epochs_contract.md` — Burn semantics, contributor linkage rules
- [ ] `burn_pool_contract.md` — Expiry rules, aggregation semantics

### 5.3 Validation Rules

| Field | Validation | Action on Failure |
|-------|-----------|-------------------|
| session_token | Non-empty string | 400 reject |
| epoch_id | Integer ≥ 1 | 400 reject |
| event_type | One of allowed values | 400 reject |
| source | Non-empty string | 400 reject |
| domain | One of: `jobs`, `events`, `business` | 400 reject |
| payload | Non-empty dict | 400 reject |
| payload string values | No PII patterns | Quarantine (200 to client) |

### 5.4 Job Run Logging

Every invocation of the contribute endpoint that results in a database write must be trackable:
- Batch-level MetaJobRun entries (not per-event — that would be too granular)
- Periodic rollup: events received, events stored, events quarantined per hour/day
- Error tracking: failed inserts, validation rejections, rate limit hits

---

## 6. Observability Requirements

### 6.1 System Health Dashboard Integration

`system_health_dashboard.py` must be updated to include:
- [ ] Events table freshness (FRESH/AGING/STALE based on last event collected_at)
- [ ] Quarantine table size and growth rate
- [ ] Session epoch count and burn rate
- [ ] PII detection hit rate (quarantined / total events)
- [ ] Burn pool monthly trends
- [ ] Contributor volume trends (signals per day/week across all domains)
- [ ] Domain coverage breakdown (what % of events are jobs vs events vs business)

These metrics serve double duty: internal ops AND contributor transparency. Contributors should be able to see that the system is working and their data is handled correctly.

### 6.2 Alerting Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Events table freshness | > 3 days since last event | > 7 days |
| Quarantine rate | > 5% of events quarantined | > 15% |
| Job run failures | > 2 consecutive failures | > 5 |
| API error rate | > 10% of requests failing | > 25% |

### 6.3 Audit Trail Requirements

- Every event has `pipeline_version` tracking which PII rule version processed it
- Quarantine records include `rule_version` for re-processing
- Session epochs track `created_at` and `burned_at` timestamps
- All Alembic migrations are versioned and reversible

---

## 7. Integration Test Requirements (§8.1–8.5)

All five tests must pass before production deployment.

### §8.1 End-to-End Signal Flow
- Input: Signal with salary, observedAt, tabUrl, collectedAt
- Assert: Event in events table, no tabUrl, no collectedAt, server timestamp, no IP in logs, pipeline_version = 1

### §8.2 PII Defence-in-Depth
- Input: Signal with `test@example.com` in payload
- Assert: Goes to quarantine with `['email']`, NOT to events, client gets 200
- Variants: phone, SSN, multi-PII

### §8.3 Config Signing Validation
- Assert: Backend does not crash on signals from extension using fallback selectors

### §8.4 Token Rotation
- Input: POST with token A, then POST with token B + incremented epoch_id
- Assert: Both events stored, session_epochs has rows for both, no cross-contamination

### §8.5 Forward-Compatibility
- Input: 64-char hex session_token, large epoch_id, unknown JSONB fields
- Assert: All stored successfully without error or truncation

---

## 8. Dependencies & Ordering

```
[Schema Migration]
    ├── events table
    ├── quarantine table
    ├── session_epochs table
    ├── burn_pool table
    └── contributors table
           │
           ▼
[Metadata Registration]
    ├── meta_table_catalog entries
    ├── meta_column_catalog entries
    └── meta_data_lineage entries
           │
           ▼
[Privacy Controls]
    ├── IP suppression middleware
    ├── Field stripping (tabUrl, collectedAt)
    └── PII quarantine pipeline
           │
           ▼
[Endpoint Implementation]
    ├── POST /api/contribute
    ├── POST /api/burn
    └── Session epoch auto-creation
           │
           ▼
[Data Contracts]
    ├── docs/contracts/events_contract.md
    ├── docs/contracts/quarantine_contract.md
    ├── docs/contracts/session_epochs_contract.md
    └── docs/contracts/burn_pool_contract.md
           │
           ▼
[Integration Tests §8.1–8.5]
           │
           ▼
[Dashboard Updates]
    └── system_health_dashboard.py additions
           │
           ▼
[Production Deployment Cleared]
```

---

## 9. Out of Scope (Deferred to FH-2+)

- Content script dedup keys and payload shapes for new sources (FH-2)
- NER-based PII detection (Second Helios — Presidio integration)
- Certificate-gated writes (Second Helios)
- Behavioral index with aggregation floor (Second Helios)
- VOPRF blind token signing (Third Helios)
- Synthetic data generation (Third Helios)
- Remote selector signing infrastructure (SpiritPool Phase 2 — extension-side)
- New domain onboarding beyond jobs/events/business (e.g., housing, transit — future phases)
- Public contributor transparency dashboard (requires frontend work — separate repo)
- Cross-domain scoring that combines contributor signals with automated collector data (requires scoring engine updates)
