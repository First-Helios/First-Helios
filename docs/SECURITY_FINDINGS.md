# Security & Privacy Audit Findings — T4.2 Full Privacy Audit

> **Date:** 2026-04-05
> **Scope:** Entire First-Helios backend — all endpoint handlers, ORM models, logging configurations, JSONB payload paths, and database schemas
> **Auditor:** Data Engineer (automated codebase sweep + manual review)
> **Status:** All findings resolved. Zero open violations.

---

## Audit Methodology

This audit verifies compliance with the 18 Non-Negotiable Data Policy Rules defined in `CLAUDE_DATA_ENGINEER.agent.md` and the privacy requirements in `DEVELOPMENT_REQUIREMENTS_PLAN.md` §3.

### Techniques Applied

1. **Grep verification** — regex sweep of all `.py` files for IP patterns, `remote_addr`, `tabUrl`, `collectedAt`, `consent_state`, `X-Forwarded-For`, `REMOTE_ADDR`
2. **Schema audit** — review of all `__tablename__` models (48 tables) for IP/PII columns
3. **Logging audit** — review of all `logging.basicConfig`, `getLogger`, `StreamHandler`, and formatter configurations
4. **Endpoint audit** — manual review of all Flask route handlers (`server.py`, `events/routes.py`, `postings/spiritpool_routes.py`, `core/contribute_routes.py`)
5. **JSONB audit** — trace of all paths where client-supplied data reaches JSONB storage (`sp_events.payload`, `quarantine.original_payload`, `bronze_event_payloads.raw_payload`)
6. **Log file check** — scan for any `.log` files or `logs/` directory on disk

---

## Summary

| Category | Result |
|----------|--------|
| IP addresses in production code | **PASS** — zero references to `request.remote_addr` in any handler |
| IP columns in database schemas | **PASS** — no IP column in any of 48 tables |
| IP patterns in log files | **PASS** — no log files exist; `_IPFreeFormatter` covers werkzeug and root loggers |
| `tabUrl` in stored data paths | **PASS** — stripped by `strip_forbidden_fields()` in all intake paths |
| `collectedAt` in stored data paths | **PASS** — stripped by `strip_forbidden_fields()` in all intake paths |
| `consent_state` in stored data | **PASS** — stripped by `strip_forbidden_fields()` (added in this audit) |
| PII quarantine pipeline | **PASS** — 6 regex patterns, recursive scan, quarantine routing works |
| `session_token` opacity | **PASS** — treated as opaque TEXT everywhere, never parsed or validated |
| Forward-compatibility (64-char tokens) | **PASS** — verified by §8.5 integration tests |

---

## Findings (2 Found, 2 Fixed)

### FINDING-01: `consent_state` not stripped from incoming payloads

| Field | Detail |
|-------|--------|
| **Severity** | Medium |
| **Rule violated** | Non-negotiable rule #5: "`consent_state` is never transmitted or stored" |
| **Location** | `core/privacy.py` — `_FORBIDDEN_FIELDS` set |
| **Description** | `strip_forbidden_fields()` only removed `tabUrl` and `collectedAt`. If the SpiritPool extension sent `consent_state` as a top-level field (which `sanitizeForTransmit()` in the handoff doc does), it would pass through to storage. In the quarantine path, the full body is stored as `original_payload` JSONB — `consent_state` would leak there. |
| **Impact** | Consent preferences (which sites are enabled, which categories excluded, whether collection is active) would be stored in JSONB, violating rule #5 and potentially creating a consent-change timeline that could be used for re-identification. |
| **Fix** | Added `"consent_state"` to `_FORBIDDEN_FIELDS` in `core/privacy.py`. Now stripped from both top-level body and nested `payload` dict before any processing. |
| **Verification** | Two new unit tests in `test_privacy_security.py`: `test_strip_top_level_consent_state` and `test_strip_nested_consent_state`. Both pass. |
| **Status** | **RESOLVED** |

### FINDING-02: Root logger lacked `_IPFreeFormatter`

| Field | Detail |
|-------|--------|
| **Severity** | Low |
| **Rule violated** | Non-negotiable rule #3: "Never log or store IP addresses" (defense-in-depth gap) |
| **Location** | `server.py` line 1867 — `logging.basicConfig()` |
| **Description** | The `_IPFreeFormatter` (which strips IPv4/IPv6 patterns from log messages) was only applied to the werkzeug logger. The root logger used a plain `logging.Formatter`. If any exception traceback or third-party library logged an IP address through the root logger, it would not be scrubbed. |
| **Impact** | Low in practice — the primary control (`_IPSuppressedRequest` overriding `request.remote_addr` to `"0.0.0.0"`) means Flask handler code never sees real IPs. But a network-level exception (e.g., `ConnectionRefusedError` with an IP in the message) could leak through the root logger. |
| **Fix** | Changed `logging.basicConfig()` to use `_IPFreeFormatter` as the handler formatter. All log output now passes through IP scrubbing. |
| **Verification** | Server starts correctly. All 173 tests pass. |
| **Status** | **RESOLVED** |

---

## Detailed Audit Results

### 1. IP Suppression (Rule #3)

**`request.remote_addr` references in production code:** Zero.

| File | References | Purpose |
|------|------------|---------|
| `server.py:135-146` | Definition only | `_IPSuppressedRequest` class — overrides `remote_addr` to return `"0.0.0.0"` |
| `tests/` | Test assertions | Verify suppression works |
| `docs/` | Documentation | Explain the mechanism |

No handler, middleware, error handler, or utility function accesses `request.remote_addr` for logging, storage, or response purposes.

**`X-Forwarded-For` / `X-Real-IP` references in production code:** Zero.

**IP columns in any ORM model:** Zero. Audited all 48 `__tablename__` definitions across `core/database.py`, `core/models/reference.py`, `core/models/spiritpool.py`, `core/metadata.py`, `events/models.py`. No column named `ip`, `ip_address`, `remote_addr`, `client_ip`, or `source_ip` exists.

**Log files on disk:** None. No `logs/` directory, no `*.log` files. All logging goes to stdout/stderr with `_IPFreeFormatter` scrubbing.

**Log format strings:** Audited all `logging.basicConfig()` and `logging.Formatter()` calls. No format string includes `%(client_ip)s`, `%(remote_addr)s`, or similar IP-related fields.

### 2. Field Stripping (Rules #1, #2)

**`tabUrl` stripping:** Applied in three locations:
1. `core/privacy.py:strip_forbidden_fields()` — strips from top-level and nested payload
2. `core/contribute_routes.py:contribute()` — calls `strip_forbidden_fields(body)` as step 1
3. `postings/spiritpool_routes.py:contribute()` — calls `strip_forbidden_fields(body)` on full batch, then `strip_forbidden_fields(raw)` on each individual signal

**`collectedAt` stripping:** Same three locations as `tabUrl`.

**`consent_state` stripping (rule #5):** Now stripped in `strip_forbidden_fields()` alongside `tabUrl` and `collectedAt`.

**Defense-in-depth:** Both the extension (`sanitizeForTransmit()`) and the backend (`strip_forbidden_fields()`) remove these fields independently. Even if the extension fails to strip, the backend catches it.

### 3. PII Quarantine Pipeline (Rule #6)

**Patterns implemented:** 6 compiled regexes covering email, phone (3 formats), SSN, credit card.

**Recursive scan:** `scan_pii()` walks dicts, lists, and tuples. Only tests string values. Integer salary values (e.g., `75000`) are below the 13-digit credit card threshold.

**Routing:** PII-flagged events go to `quarantine` table with `redaction_types` listing all matched patterns. Clean events go to `sp_events`. Client always gets 200 in both cases.

**Coverage:** Verified by §8.2 integration tests (email, phone, SSN, multi-PII, nested PII, clean pass-through).

### 4. Schema Integrity (Rules #7–10)

| Rule | Status | Evidence |
|------|--------|----------|
| #7: `session_token` is TEXT, no length/format constraints | **PASS** | `SpEvent.session_token = Column(Text, nullable=False)` — accepts UUID (36 chars) and hex (64 chars) |
| #8: `payload` JSONB accepts unknown fields | **PASS** | Verified by §8.5 test — Third Helios EDN fields stored and retrieved |
| #9: `pipeline_version` server-side only | **PASS** | Set to `_CURRENT_PIPELINE_VERSION = 1` in handler, never from client |
| #10: `epoch_id` no upper bound | **PASS** | `Column(Integer)` — §8.5 test stores `2147483647` successfully |

### 5. `session_token` Opacity (Rule from Handoff §3.1)

No code parses, validates format, or makes assumptions about `session_token` internal structure. Grep for `session_token` shows it is:
- Stored as `Text` column
- Used as filter key (`filter_by(session_token=...)`)
- Never regex-matched, length-checked, or UUID-parsed
- Never used for reverse identity lookup

### 6. Endpoint Privacy Compliance

| Endpoint | Field stripping | PII scan | IP suppressed | consent_state stripped |
|----------|----------------|----------|---------------|----------------------|
| POST /api/contribute | Yes | Yes | Yes | Yes |
| POST /api/burn | N/A (no payload storage) | N/A | Yes | N/A |
| POST /api/spiritpool/contribute | Yes (batch + per-signal) | Yes (dual-write) | Yes | Yes |
| GET /api/spiritpool/stats | N/A (read-only) | N/A | Yes | N/A |
| GET /api/spiritpool/insights | N/A (read-only) | N/A | Yes | N/A |
| POST /api/events/interactions | N/A (no contributor data) | N/A | Yes | N/A |
| GET /api/events/* | N/A (read-only) | N/A | Yes | N/A |
| All other GET endpoints in server.py | N/A (read-only) | N/A | Yes | N/A |

### 7. Error Handler Review

`server.py:199` — Global error handler logs `request.method` and `request.path` only. Does NOT log `request.remote_addr`, headers, or body. Exception details go to server logs (covered by `_IPFreeFormatter`), not to client responses (generic "An internal error occurred").

---

## Verification Commands

```bash
# Verify no IP patterns in Python source (excluding test assertions and docs)
grep -rP '\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}' --include='*.py' \
  --exclude-dir=tests --exclude-dir=docs \
  core/ postings/ events/ server.py
# Expected: only "0.0.0.0" in _IPSuppressedRequest

# Verify no remote_addr usage in handlers
grep -rn 'request\.remote_addr' --include='*.py' \
  --exclude-dir=tests --exclude-dir=docs
# Expected: only server.py _IPSuppressedRequest definition

# Verify forbidden fields in strip set
python -c "from core.privacy import _FORBIDDEN_FIELDS; print(_FORBIDDEN_FIELDS)"
# Expected: {'tabUrl', 'collectedAt', 'consent_state'}

# Run full integration test suite
python -m pytest tests/HeliosDeployment/ -v
# Expected: 173 passed
```

---

## Conclusion

The First-Helios backend meets all 18 non-negotiable data policy rules. Two defense-in-depth gaps were found and fixed during this audit:

1. `consent_state` is now stripped from all incoming payloads (rule #5)
2. The root logger now uses `_IPFreeFormatter` for complete IP scrubbing coverage (rule #3)

The primary IP suppression mechanism (`_IPSuppressedRequest`) is structural — it prevents any handler from accessing real client IPs. The field stripping and PII quarantine pipelines apply defense-in-depth across both the new `/api/contribute` and legacy `/api/spiritpool/contribute` paths.

All 173 tests pass, including the §8.1–8.5 integration test suite.
