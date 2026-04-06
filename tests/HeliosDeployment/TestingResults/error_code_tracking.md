# Error Code Tracking — HeliosDeployment Test Suite

> Tracks all HTTP status codes exercised by the test suite,
> maps them to validation rules, and logs any regression failures.

---

## 1. HTTP Status Code Catalog

Every status code returned by the SpiritPool endpoints, the validation rule
that triggers it, and the test(s) that verify it.

### POST /api/contribute

| Code | Condition | Validation Rule | Test ID(s) | Dev Req |
|------|-----------|----------------|-----------|---------|
| 200 | Clean signal stored in sp_events | All fields valid, no PII | A-01, A-02 | §4.1 |
| 200 | PII signal quarantined | PII detected, routed to quarantine | A-10, A-12, A-13 | §4.1 |
| 400 | session_token missing or empty | `not session_token or not isinstance(session_token, str)` | A-15 | §5.3 |
| 400 | epoch_id missing | `epoch_id is None` | A-16 | §5.3 |
| 400 | epoch_id = 0 | `epoch_id < 1` | A-17 | §5.3 |
| 400 | epoch_id negative | `epoch_id < 1` | A-18 | §5.3 |
| 400 | epoch_id non-integer | `not isinstance(epoch_id, int)` | A-16 | §5.3 |
| 400 | event_type invalid | `event_type not in _ALLOWED_EVENT_TYPES` | A-19 | §5.3 |
| 400 | source missing or empty | `not source or not isinstance(source, str)` | A-20 | §5.3 |
| 400 | domain invalid | `domain not in _ALLOWED_DOMAINS` | A-21 | §5.3 |
| 400 | payload missing | `not payload` | A-22 | §5.3 |
| 400 | payload empty dict | `not payload` (empty dict is falsy) | A-23 | §5.3 |
| 400 | Non-JSON body | `request.get_json(silent=True)` returns None | A-24 | §5.3 |
| 500 | Database insert failure | `try/except` around db operations | — (not tested) | §4.1 |

### POST /api/burn

| Code | Condition | Validation Rule | Test ID(s) | Dev Req |
|------|-----------|----------------|-----------|---------|
| 200 | Successful burn (token exists) | session_epoch found, updated | A-27 | §4.2 |
| 200 | Token not found (idempotent) | No session_epoch, burn_pool still incremented | A-33 | §4.2 |
| 400 | session_token missing | `not session_token or not isinstance(session_token, str)` | A-32 | §4.2 |
| 400 | Non-JSON body | `request.get_json(silent=True)` returns None | A-32 | §4.2 |
| 500 | Database operation failure | `try/except` around db operations | — (not tested) | §4.2 |

### POST /api/spiritpool/contribute (Legacy — T3.3)

| Code | Condition | Validation Rule | Test ID(s) | Dev Req |
|------|-----------|----------------|-----------|---------|
| 200 | Signals accepted + dual-written | Valid domain, signals list | — (HTTP not tested; unit L-05) | §4.3 |
| 400 | No JSON body | `request.get_json(silent=True)` returns None | — (not tested) | §4.3 |
| 400 | Unrecognised domain | `_normalize_domain()` returns None | — (not tested) | §4.3 |
| 400 | Signals not a list | `not isinstance(signals_raw, list)` | — (not tested) | §4.3 |
| 400 | Batch too large | `len(signals_raw) > MAX_SIGNALS_PER_BATCH` | — (not tested) | §4.3 |
| 500 | General exception | `try/except` around batch processing | — (not tested) | §4.3 |

**Note:** Legacy endpoint HTTP-level tests are deferred to T4.1. Current T3.3 tests
cover the dual-write function and privacy fixes at the unit level (L-01 through L-09).

---

## 2. Allowed Value Enumerations

### event_type (enforced by `_ALLOWED_EVENT_TYPES`)

| Value | Domain | Tested In |
|-------|--------|-----------|
| `job_listing` | jobs | A-26, A-01, multiple |
| `salary_signal` | jobs | A-26 |
| `business_review` | business | A-26 |
| `event_listing` | events | A-26 |

### domain (enforced by `_ALLOWED_DOMAINS`)

| Value | Tested In |
|-------|-----------|
| `jobs` | A-25, A-01, multiple |
| `events` | A-25 |
| `business` | A-25 |

### source (any non-empty string)

No enumeration enforced. Tests use: `indeed`, `test`, various custom strings.

---

## 3. Validation Rule Implementation Reference

All validation lives in `core/contribute_routes.py` → `contribute()` function.

```
Line ~67-82 in contribute_routes.py:

    if not session_token or not isinstance(session_token, str):
        return 400, "session_token required"

    if epoch_id is None or not isinstance(epoch_id, int) or epoch_id < 1:
        return 400, "epoch_id required (integer >= 1)"

    if event_type not in _ALLOWED_EVENT_TYPES:
        return 400, "invalid event_type"

    if not source or not isinstance(source, str):
        return 400, "source required"

    if domain not in _ALLOWED_DOMAINS:
        return 400, "invalid domain"

    if not payload or not isinstance(payload, dict):
        return 400, "payload required (non-empty dict)"
```

Validation order matches the processing order in Dev Req §4.1:
1. Strip (before validation — A-08, A-09 prove this)
2. Validate (return 400 on first failure — tests A-15 through A-24)
3. Server fields (set regardless of PII outcome)
4. PII scan (after validation, before storage)

---

## 4. PII Quarantine Error Codes

PII detection does NOT return an error code to the client. They always get 200.
This is by design (§3.3): the extension session continues unaffected regardless
of whether the payload was quarantined.

| PII Pattern | Regex | Quarantine Type | Test ID(s) |
|-------------|-------|----------------|-----------|
| Email | `[^@\s]+@[^@\s]+\.[^@\s]+` | `email` | P-14, P-15, P-16, A-10, A-11 |
| US Phone (dashes/dots) | `\b\d{3}[-.]?\d{3}[-.]?\d{4}\b` | `phone` | P-17, P-18, P-19, A-12 |
| US Phone (parens) | `\(\d{3}\)\s?\d{3}[-.]?\d{4}` | `phone` | P-20 |
| International Phone | `\+\d{7,15}` | `phone` | P-21 |
| US SSN | `\b\d{3}-\d{2}-\d{4}\b` | `ssn` | P-22, A-13 |
| Credit Card | `\b\d{13,19}\b` | `credit_card` | P-23 |

### False Positive Boundaries

| Input | Expected | Reason | Test ID |
|-------|----------|--------|---------|
| `"75000"` (salary) | NOT flagged | 5 digits < 13-digit minimum | P-26 |
| `"78701"` (zip) | NOT flagged | 5 digits < 13-digit minimum | P-27 |
| `5125551234` (integer) | NOT flagged | Non-string values not scanned | P-28 |
| `None` | No error | Gracefully skipped | P-29 |
| `True` / `False` | No error | Gracefully skipped | P-30 |

---

## 5. Database Constraint Error Codes

These are SQLAlchemy-level errors, not HTTP errors. They are raised by the
database engine and caught in tests.

| Constraint | Table | Column(s) | Exception | Test ID |
|-----------|-------|-----------|-----------|---------|
| UNIQUE | session_epochs | session_token | `IntegrityError` | S-06 |
| UNIQUE | contributors | uuid | `IntegrityError` | S-16 |
| NOT NULL | sp_events | payload | `IntegrityError` | — (ORM default prevents) |
| FK | session_epochs | contributor_id → contributors.id | `IntegrityError` | — (nullable, soft reference) |

---

## 6. Regression Failure Log

Track any test failures encountered during development or CI runs.

| Date | Test ID | Status | Error | Root Cause | Resolution |
|------|---------|--------|-------|------------|------------|
| 2026-04-05 | ALL | ERROR | `UnsupportedCompilationError: JSONB` | SQLite cannot render PostgreSQL JSONB type | Added `@compiles(JSONB, "sqlite")` adapter in conftest.py |
| 2026-04-05 | ALL | ERROR | `UnsupportedCompilationError: ARRAY` | SQLite cannot render PostgreSQL ARRAY type (from events/models.py) | Added `@compiles(ARRAY, "sqlite")` adapter in conftest.py |
| 2026-04-05 | M-01,M-04–M-10 | FAIL | Empty result set from meta_table_catalog queries | Test DB had no metadata — `db` fixture creates empty tables | Created `seeded_db` fixture that runs `populate_metadata.py` functions to seed test DB |
| 2026-04-05 | D-01–D-14 | PASS | — | T3.2 dashboard functions added (no regressions) | 14 new tests, all pass on first run |
| 2026-04-05 | L-01–L-09 | PASS | — | T3.3 legacy compat tests added (no regressions) | 9 new tests, all pass on first run |

---

## 7. Untested Error Paths

These error conditions exist in the code but are not exercised by the current
test suite. They are tracked here for future coverage (T4.1 integration tests).

| Condition | Code Path | HTTP Code | Why Not Tested | Roadmap Task |
|-----------|-----------|-----------|---------------|-------------|
| Database connection failure | `init_db()` raises | 500 | Requires mocking DB engine failure | T4.1 |
| Database insert exception | `db.add() + db.commit()` raises | 500 | Requires mocking ORM exception | T4.1 |
| Max content length exceeded | Flask `MAX_CONTENT_LENGTH = 1MB` | 413 | Flask auto-rejects before route | T4.2 |
| CORS preflight | OPTIONS request | 200 (CORS headers) | Flask-CORS handles automatically | T4.2 |
| Concurrent duplicate session_token | Race on session_epochs UNIQUE | 500 (or silent) | Requires concurrent test setup | T5.2 |
| Malformed JSON with valid Content-Type | `get_json(silent=True)` → None | 400 | A-24 covers this partially | — |
| Burn pool increment existing entry | `BurnPool` row already exists for month_key | 200 | Only "create new" branch tested (A-27) | T4.1 |
| Burn endpoint invalid JSON body | Non-JSON to `/api/burn` | 400 | No test sends malformed body to burn | T4.1 |
| Legacy endpoint full HTTP flow | POST `/api/spiritpool/contribute` | 200 | External deps (ingest_job_posting) hard to mock | T4.1 |
| Legacy dual-write + commit failure | `_dual_write_to_sp_events` + DB error | 200 | Only tested via mock, not HTTP | T4.1 |
| Dashboard STALE status | sp_events >7 days old | stdout | Would need old collected_at in test data | T4.1 |
| Dashboard AGING status | sp_events 3–7 days old | stdout | Would need aged collected_at in test data | T4.1 |

---

## 8. Error Response Body Format

All error responses follow the same JSON structure:

```json
{
    "status": "error",
    "message": "<human-readable description>"
}
```

All success responses:

```json
{
    "status": "ok"
}
```

**Security note:** Error messages are intentionally generic. They identify
*which* field is wrong but never expose internal state, stack traces, or
database details. This is per §4.1: "No detailed error bodies for auth failures."
