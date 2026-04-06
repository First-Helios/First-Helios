# Test Effectiveness Review — HeliosDeployment Suite (T1/T2/T3)

> Manual branch coverage analysis and effectiveness assessment for
> the 124-test suite. Produced after T3 completion.

---

## 1. Suite Summary

| Metric | Value |
|--------|-------|
| Total tests | 124 |
| Test files | 7 |
| Production files exercised | 9 |
| All pass? | Yes (4.47s) |
| Tiers covered | T1 (schema/metadata), T2 (privacy/endpoints), T3 (dashboard/legacy) |

---

## 2. Strengths

### 2.1 Validation Coverage Is Comprehensive

Every input validation branch in `contribute()` has a dedicated test:
session_token (missing, empty, wrong type), epoch_id (missing, zero,
negative, non-integer), event_type (invalid), source (missing, empty),
domain (invalid), payload (missing, empty dict), non-JSON body. This
is 10+ tests covering all 400-return paths. The burn endpoint validation
is similarly covered.

### 2.2 PII Detection Has False Positive Guards

The PII regex tests (P-14 through P-31) cover all 6 patterns and
include **explicit false-positive boundary tests**: salary values,
ZIP codes, integer types, None, and booleans. This is critical because
the credit card regex (`\b\d{13,19}\b`) is the most likely to false-flag
legitimate job data. The tests prove it doesn't.

### 2.3 Privacy Contracts Are Structurally Enforced

- IP suppression is tested at the middleware level (custom Request class)
- Field stripping is tested at the unit level AND at the endpoint level
- tabUrl/collectedAt removal is verified in stored payloads after HTTP round-trip
- Legacy route IP logging fix is verified via source code inspection

### 2.4 Metadata Tests Use Production Seed Script

`test_metadata_quality.py` runs the same `populate_metadata.py` functions as
production. This means metadata drift (adding a column but forgetting to
register it) is caught automatically. Good pattern.

### 2.5 Dashboard Tests Cover All Alert States

The quarantine health dashboard function is tested at all three threshold
levels: HEALTHY (<5%), WARNING (5–15%), CRITICAL (>15%). Empty-state
handling is tested for every dashboard function.

### 2.6 Legacy Non-Fatality Is Explicitly Tested

L-07 patches `session.add` to raise a RuntimeError and verifies the
dual-write doesn't propagate the exception. This directly protects the
legacy ingest path from dual-write regressions.

---

## 3. Coverage Gaps — Untested Branches

These are branches that exist in the production code but are not
exercised by any test. Prioritized by risk.

### HIGH — Error Recovery Paths

| Gap | File | Branch | Risk |
|-----|------|--------|------|
| **contribute() 500 path** | contribute_routes.py:~98 | `except Exception` → rollback → 500 | If rollback fails silently, data corruption. No test verifies the rollback actually runs. |
| **burn() 500 path** | contribute_routes.py:~130 | `except Exception` → rollback → 500 | Same risk as above. |

**Recommendation:** Add tests that mock `db.commit()` to raise
`sqlalchemy.exc.OperationalError`, then assert: (1) response is 500,
(2) session is rolled back, (3) no partial data persists.

### MEDIUM — Branch Logic Gaps

| Gap | File | Branch | Risk |
|-----|------|--------|------|
| **Burn pool increment** | contribute_routes.py:~125 | `if existing_pool: existing_pool.signal_count += ...` | Currently all burn tests create new pool entries. The UPDATE branch (incrementing an existing row) is never tested. |
| **Burn invalid JSON body** | contribute_routes.py:~108 | `body = request.get_json(silent=True)` → None → 400 | The contribute endpoint has A-24 for this, but no analogous test exists for the burn endpoint. |
| **Dashboard STALE/AGING** | system_health_dashboard.py | `if age_days > 7: STALE` / `if age_days > 3: AGING` | Tests only cover FRESH and empty states. Would need events with old `collected_at` timestamps. |

**Recommendation:** For burn pool increment, send two burns in the same
month and assert `signal_count` increments. For STALE/AGING, insert
events with `collected_at = datetime.utcnow() - timedelta(days=8)`.

### LOW — Integration Gaps (Expected at This Stage)

| Gap | File | Impact |
|-----|------|--------|
| Legacy endpoint end-to-end | spiritpool_routes.py | Full HTTP path requires mocking `ingest_job_posting`, `normalize_name`, `ScraperSignal` — complex setup. Unit tests cover the critical dual-write logic. |
| Dashboard function integration | system_health_dashboard.py | Functions are tested in isolation with `capsys`. No test calls `main()` to verify the full dashboard output. |

These are acceptable deferred gaps for T4.1 integration testing.

---

## 4. Test Quality Assessment

### 4.1 Test Isolation: GOOD

Every test gets its own in-memory SQLite engine via function-scoped fixtures.
No shared state between tests. The `db` fixture rolls back after each test.
Payload fixtures return fresh dicts. No test can affect another.

### 4.2 Test Specificity: GOOD

Each test asserts on one specific behavior. Test names describe what they
verify. No tests assert on multiple unrelated properties.

### 4.3 Test Maintainability: MODERATE

**Strengths:**
- Shared fixtures avoid duplication
- Test IDs (S-01, A-01, etc.) enable traceability
- Each file maps to one concern

**Concerns:**
- `test_legacy_compat.py` uses `inspect.getsource()` for L-04 and L-09.
  These tests are fragile: renaming variables or reformatting strings in
  the production code could break them without changing behavior. Consider
  replacing with runtime assertions in T4.1.
- Dashboard tests check substring presence in stdout. If output formatting
  changes (e.g., different padding), tests break. Consider capturing
  structured data (return values) instead of stdout strings.

### 4.4 Test Completeness By Dev Req Section

| Dev Req | Section | Tests | Coverage |
|---------|---------|-------|----------|
| §2 | Schema/storage | S-01 to S-16 | Complete — all 5 tables, column types, constraints |
| §3.1 | IP suppression | P-01 to P-13 | Complete — middleware + formatter + Flask integration |
| §3.2 | Field stripping | P-04 to P-09, A-08, A-09 | Complete — unit + integration |
| §3.3 | PII detection | P-14 to P-31 | Complete — all 6 patterns + false positives |
| §4.1 | Contribute endpoint | A-01 to A-26 | Good — all validation paths. Missing: 500 error path. |
| §4.2 | Burn endpoint | A-27 to A-33 | Good — happy path + idempotency. Missing: increment, invalid JSON, 500. |
| §4.3 | Legacy compatibility | L-01 to L-09 | Moderate — privacy fix + dual-write covered. No HTTP-level tests. |
| §5.1 | Table catalog | M-01 to M-03 | Complete |
| §5.2 | Column catalog | M-04 to M-08 | Complete |
| §5.3 | Input validation | A-15 to A-24 | Complete — every validation rule tested |
| §5.4 | Job run logging | — | Not tested — deferred to T4.1 |
| §6.1 | Dashboard monitoring | D-01 to D-14 | Good — all 5 functions. Missing: STALE/AGING thresholds. |
| §6.2 | Alerting thresholds | D-05, D-06, D-07 | Complete for quarantine rates |
| §6.3 | Data contracts | M-11, M-12 | Complete — file existence + non-trivial size |

---

## 5. Recommended T4.1 Test Additions

Priority order for maximum coverage improvement with minimal effort:

1. **Burn pool increment test** — 5 lines of code, covers untested UPDATE branch
2. **Burn invalid JSON test** — 3 lines, mirrors existing A-24
3. **Contribute 500 error test** — mock db.commit() → OperationalError, ~10 lines
4. **Dashboard STALE test** — insert old event, check output, ~8 lines
5. **Dashboard AGING test** — insert 5-day-old event, ~8 lines
6. **Burn 500 error test** — same pattern as contribute 500 test

Estimated addition: ~6 tests, ~50 lines of code, closing all HIGH and MEDIUM gaps.

---

## 6. Conclusion

The 124-test suite provides **strong coverage of the validation, privacy, and
metadata pillars** — which are the highest-risk areas for a data platform handling
contributor signals. The main gaps are in **error recovery paths** (500 responses)
and **state-transition branches** (burn pool increment, dashboard aging thresholds).
These are solvable with ~6 targeted tests in T4.1.

The test architecture (per-concern files, function-scoped isolation, production
seed scripts for metadata) is sound and scales well for additional domains.
