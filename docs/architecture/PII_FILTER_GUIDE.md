# PII Filter Guide — Viewing, Understanding, and Acting on Filtered Data

**Status:** Active  
**Date:** 2026-04-13  
**Relates to:** `core/privacy.py`, `postings/spiritpool_routes.py`, `quarantine` table

---

## Overview

Every SpiritPool signal passes through two server-side privacy gates before reaching `sp_events`:

```
Extension payload
    │
    ▼
strip_forbidden_fields()     ← removes tabUrl, collectedAt, consent_state
    │
    ▼
_sanitize_signal_in_place()  ← drops dead-weight fields, canonicalizes URLs
    │
    ▼
scan_pii(payload)            ← recursive regex scan on non-exempt fields
    │
    ├─ clean ──► sp_events   (queryable, usable data)
    └─ flagged ► quarantine  (held for review, never ingested)
```

`job_postings` is written from the signal regardless of quarantine status — only the `sp_events` dual-write is gated.

---

## 1. Viewing What's Being Filtered

### Live counts

```sql
-- Overall quarantine rate
SELECT
    (SELECT COUNT(*) FROM quarantine)  AS quarantined,
    (SELECT COUNT(*) FROM sp_events)   AS clean,
    ROUND(
        (SELECT COUNT(*) FROM quarantine)::numeric /
        NULLIF((SELECT COUNT(*) FROM quarantine) + (SELECT COUNT(*) FROM sp_events), 0) * 100,
        1
    ) AS quarantine_pct;

-- Breakdown by PII type flagged
SELECT
    redaction_types,
    COUNT(*) AS n,
    MIN(quarantined_at) AS first_seen,
    MAX(quarantined_at) AS last_seen
FROM quarantine
GROUP BY redaction_types
ORDER BY n DESC;
```

### Inspect a quarantined payload

```sql
-- Most recent 10 quarantine entries with their payloads
SELECT
    quarantine_id,
    quarantined_at,
    redaction_types,
    original_payload
FROM quarantine
ORDER BY quarantined_at DESC
LIMIT 10;

-- Show which fields are present in quarantined payloads
SELECT DISTINCT jsonb_object_keys(original_payload) AS field
FROM quarantine
ORDER BY field;
```

### Audit tool

The audit script at `dev/audit_spiritpool_collection.py` gives a full field-level breakdown:

```bash
# Sync live data from OPi first
bash dev/sync_from_opi.sh

# Run audit (normal)
python dev/audit_spiritpool_collection.py

# Verbose: dumps sample payloads and field-by-field PII scan results
python dev/audit_spiritpool_collection.py --verbose
```

The audit classifies every field seen in `sp_events` and `quarantine` into:

| Category | Meaning |
|---|---|
| `CONSUMED_BY_INGEST` | Read by `ingest_job_posting()` → written to `job_postings` |
| `METADATA_ONLY` | Collected but never persisted (applicantCount, rating, badges) |
| `DEAD_WEIGHT` | Extension sends it; backend never reads it (stripped at intake) |
| `ADDED_DOWNSTREAM` | Not from extension; added by server (session_token, epoch_id) |
| `FORBIDDEN` | Must never be stored — stripped immediately at JSON parse |
| `UNKNOWN` | New field not yet classified — needs a decision |

---

## 2. Understanding Why a Field Is Filtered

### The two filter layers

#### Layer 1 — `strip_forbidden_fields()` (`core/privacy.py`)

Hard-stops. Always removed regardless of content:

| Field | Reason |
|---|---|
| `tabUrl` | Full browsing URL — contributor deanonymization risk |
| `collectedAt` | Client-side timestamp — timing fingerprint |
| `consent_state` | Internal extension state — must never leave the browser |

These are dropped from both the top-level body and any nested `payload` dict.

#### Layer 2 — `_sanitize_signal_in_place()` (`postings/spiritpool_routes.py`)

Dead-weight fields the extension sends but no code path reads. Removing them before the PII scan prevents false positives:

| Field | Reason for removal |
|---|---|
| `jobId` | 10-digit platform ID — matches phone regex without separator requirement |
| `source` | Duplicates `body.domain`; backend derives the source tag itself |
| `storeNum` | Always null/synthetic; overwritten by `SP-<chain>` |
| `signalType` | Hardcoded `"listing"` — endpoint already assumes listing |
| `observedAt` | Client timestamp; backend uses `datetime.utcnow()` |
| `_dev_html` | HTML blob containing 13-digit `data-id` attributes — triggers credit card regex |

URL canonicalization also runs here: tracking params (`trackingId`, `refId`, `eBP`, `trk`, `utm_*`) are stripped and only allowlisted job-identifier params are kept (e.g. `currentJobId` for LinkedIn).

#### Layer 3 — `scan_pii()` (`core/privacy.py`)

Regex scan over all remaining string values. Any match sends the full payload to `quarantine`.

**Patterns (intentionally broad — false positives handled by exemptions, not regex weakening):**

| Type | Pattern | Example match |
|---|---|---|
| `email` | `[^@\s]+@[^@\s]+\.[^@\s]+` | `hr@company.com` |
| `phone` | `\b\d{3}[-.]?\d{3}[-.]?\d{4}\b` | `512-555-1234`, `5125551234` |
| `phone` | `\(\d{3}\)\s?\d{3}[-.]?\d{4}` | `(512) 555-1234` |
| `phone` | `\+\d{7,15}` | `+15125551234` |
| `ssn` | `\b\d{3}-\d{2}-\d{4}\b` | `123-45-6789` |
| `credit_card` | `\b\d{13,19}\b` | any 13-19 digit run |

**Exempt fields — subtrees skipped entirely:**

The scanner is field-aware. When recursing into a dict, if the key is in `_PII_EXEMPT_FIELDS`, the entire subtree (including nested dicts/lists) is skipped. This prevents false positives without weakening the patterns.

Current exempt fields (see `core/privacy.py` for the authoritative list):

| Field(s) | Rationale |
|---|---|
| `url`, `job_url`, `source_url` | Numeric job IDs in query strings match phone regex |
| `session_token`, `epoch_id`, `legacy_contributor_id`, `legacy_domain` | Opaque tokens / short slugs — not PII vectors |
| `postingDate`, `jobType`, `isRemote` | Dates and booleans — no phone-shaped data |
| `salarySource`, `jobLevel`, `companyIndustry` | Short categorical strings |
| `badges` | List of categorical tags |
| `applicantCount`, `rating` | Numeric |
| `salary` | Structured dict `{min, max, period}` — numeric values only |

---

## 3. Determining Next Action for Filtered Data

### Decision tree

```
New field appears in quarantine / unknown classification
│
├─ Is it in _FORBIDDEN_FIELDS?
│   └─ YES → it should never reach quarantine; check strip_forbidden_fields()
│
├─ Does it match a dead-weight pattern (always same value, never read)?
│   └─ YES → add to _SP_DEAD_WEIGHT_FIELDS in spiritpool_routes.py
│
├─ Is the false positive from a known-safe field type?
│   ├─ URL / opaque ID / enum / numeric?
│   │   └─ YES → add to _PII_EXEMPT_FIELDS in core/privacy.py
│   └─ Free-text field that shouldn't have phone numbers?
│       └─ Examine sample payloads — does it ever legitimately contain PII?
│           ├─ Never → add to _PII_EXEMPT_FIELDS
│           └─ Sometimes → leave scanned; accept that PII goes to quarantine
│
└─ Is it genuine PII in a free-text field (description, company)?
    └─ YES → quarantine is correct; DO NOT exempt this field
```

### Adding a new exemption

1. Verify the field is structurally incapable of containing PII (URL, ID, enum, boolean, numeric).
2. Add it to `_PII_EXEMPT_FIELDS` in `core/privacy.py`.
3. Add a comment in the appropriate group (URLs & IDs / Session plumbing / Categorical / Structured numeric).
4. Re-run the test suite: `python3 -c "from core.privacy import scan_pii; ..."` (see examples in this doc).
5. Replay quarantine rows to confirm the exemption resolves the false positive:

```bash
python dev/audit_spiritpool_collection.py --verbose
```

### Adding a new dead-weight field

1. Confirm no code path in `postings/spiritpool_routes.py`, `postings/ingest.py`, or any downstream consumer reads the field.
2. Add it to `_SP_DEAD_WEIGHT_FIELDS` in `postings/spiritpool_routes.py`.
3. Add a comment explaining what the field is and why it's dropped.

### Adding a new URL allowlisted param

If a job board uses a query parameter to identify a specific posting that isn't in the allowlist:

1. Find the minimal URL that opens the job (check it in a private window with no cookies).
2. Add the param name to `_URL_PARAM_ALLOWLIST[domain]` in `postings/spiritpool_routes.py`.
3. Run the canonicalizer manually to confirm:
   ```python
   from postings.spiritpool_routes import _canonicalize_url
   print(_canonicalize_url("https://example.com/jobs?jobId=123&trackingId=abc"))
   ```

---

## 4. Quick Reference — Where Things Live

| Concern | File | Symbol |
|---|---|---|
| Forbidden field stripping | `core/privacy.py` | `_FORBIDDEN_FIELDS`, `strip_forbidden_fields()` |
| PII regex patterns | `core/privacy.py` | `_PII_PATTERNS` |
| Field exemption whitelist | `core/privacy.py` | `_PII_EXEMPT_FIELDS` |
| Dead-weight field stripping | `postings/spiritpool_routes.py` | `_SP_DEAD_WEIGHT_FIELDS`, `_sanitize_signal_in_place()` |
| URL canonicalization | `postings/spiritpool_routes.py` | `_URL_PARAM_ALLOWLIST`, `_canonicalize_url()` |
| Dual-write + quarantine routing | `postings/spiritpool_routes.py` | `_dual_write_to_sp_events()` |
| Quarantine storage | `core/models/spiritpool.py` | `Quarantine` model |
| Dev-mode A/B capture | `core/models/dev_capture.py` | `RawSignalCapture` model |
| Audit tooling | `dev/audit_spiritpool_collection.py` | `audit_production_payloads()`, `audit_dev_capture()` |
| Dev↔OPi sync | `dev/sync_from_opi.sh` | `--dry-run` flag |
