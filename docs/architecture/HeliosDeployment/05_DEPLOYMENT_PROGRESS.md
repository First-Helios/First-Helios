# 5. Deployment Progress

> **Last updated:** 2026-04-05
> **Tracking:** FH-0 (Intake Foundation) + FH-1 (Backend Hardening) roadmap execution

---

## Tier Summary

| Tier | Status | Tasks Done | Total |
|------|--------|------------|-------|
| **Tier 1: Minimal Context** | **Complete** | 5/5 | Infrastructure in place |
| **Tier 2: Low Context** | **Complete** | 5/5 | Privacy controls active |
| **Tier 3: Medium Context** | **Complete** | 3/3 | Integration done |
| **Tier 4: High Context** | **Complete** | 2/2 | Validation done |
| **Tier 5: Full Budget** | Not started | 0/3 | Production readiness pending |

---

## Tier 1: Minimal Context (Complete)

Infrastructure tasks. Each self-contained, reading 1–3 files.

### T1.1 — Alembic Migration for New Tables
- **Status:** Done
- **File:** `alembic/versions/ae445d02acad_spiritpool_intake_tables.py`
- **What:** Creates 5 tables: `sp_events`, `quarantine`, `session_epochs`, `burn_pool`, `contributors`
- **Details:** Strictly additive migration. All extraneous index drift on existing tables was removed. Migration applied and verified — all 5 tables exist in database.

### T1.2 — Register New Tables in Metadata
- **Status:** Done
- **File:** `scripts/one_shot/populate_metadata.py`
- **What:** 5 `meta_table_catalog` entries + ~28 `meta_column_catalog` entries covering all columns of all 5 new tables.
- **Verification:** `python scripts/one_shot/populate_metadata.py` ran successfully.

### T1.3 — Create Data Contracts
- **Status:** Done
- **Files:**
  - `docs/contracts/sp_events_contract.md`
  - `docs/contracts/quarantine_contract.md`
  - `docs/contracts/session_epochs_contract.md`
  - `docs/contracts/burn_pool_contract.md`
- **What:** Each contract defines schema, SLAs, consumers, fragility points, fallback strategy.

### T1.4 — Register Data Lineage
- **Status:** Done
- **File:** `scripts/one_shot/populate_metadata.py`
- **What:** 6 `meta_data_lineage` entries:
  - `spiritpool_post → sp_events`
  - `spiritpool_post → quarantine`
  - `sp_events → session_epochs`
  - `session_epochs → contributors`
  - `burn_endpoint → burn_pool`
  - `sp_events → scores`

### T1.5 — ORM Models for New Tables
- **Status:** Done
- **File:** `core/models/spiritpool.py`
- **What:** 5 SQLAlchemy model classes: `SpEvent`, `Quarantine`, `SessionEpoch`, `BurnPool`, `Contributor`
- **Details:** Registered in `core/database.py` (`_import_spiritpool_models()`) and `alembic/env.py`.

---

## Tier 1 Success Criteria

- [x] All 5 tables exist in database
- [x] All tables registered in `meta_table_catalog`
- [x] All columns registered in `meta_column_catalog`
- [x] Data lineage entries exist for all new flows
- [x] Data contracts exist in `docs/contracts/`

---

## Tier 2: Low Context (Complete)

Privacy controls and supporting endpoints. Each task reads a small cluster of related files.

### T2.1 — IP Suppression Middleware
- **Status:** Done
- **File:** `server.py` (lines ~135–170)
- **What:**
  - `_IPSuppressedRequest` — custom Flask request class, `remote_addr` always returns `"0.0.0.0"`
  - `_IPFreeFormatter` — logging formatter that strips IPv4/IPv6 patterns from log output
  - Applied to werkzeug logger for access logs
- **Verification:** `request.remote_addr` returns `"0.0.0.0"` in all handlers.

### T2.2 — Field Stripping Utility
- **Status:** Done
- **File:** `core/privacy.py`
- **Function:** `strip_forbidden_fields(body)`
- **What:** Removes `tabUrl` and `collectedAt` from top-level body and nested `payload` dict. Called immediately after JSON parsing, before validation or storage.
- **Verification:** Tested with payloads containing forbidden fields — all stripped correctly.

### T2.3 — PII Detection Engine
- **Status:** Done
- **File:** `core/privacy.py`
- **Function:** `scan_pii(payload)`
- **What:** Recursively walks JSONB payload, tests all string values against 6 compiled regex patterns (email, 3× phone, SSN, credit card). Returns sorted deduplicated list of matched types.
- **Verification:** Tested with email, phone, SSN, nested PII, clean payloads, and multi-pattern scenarios. All pass.

### T2.4 — Burn Endpoint + Contribute Endpoint
- **Status:** Done
- **File:** `core/contribute_routes.py`
- **Blueprint:** `contribute_bp` (registered in `server.py`)
- **What:**
  - `POST /api/contribute` — full processing pipeline (strip → validate → server fields → PII scan → route → auto-create session_epochs)
  - `POST /api/burn` — sets `contributor_id = NULL`, `burned_at = NOW()`, increments/creates `burn_pool` entry
- **Routes verified:** `/api/contribute` and `/api/burn` both registered in Flask URL map.

### T2.5 — Burn Pool Maintenance Job
- **Status:** Done
- **Files:** `config/scheduler.yaml`, `core/scheduler.py`
- **What:** `burn_pool_cleanup` cron job runs daily at 02:45 UTC. Deletes expired `burn_pool` records (`expires_at < NOW()`).
- **Function:** `core/scheduler.py:_run_burn_pool_cleanup()`

---

## Tier 2 Success Criteria

- [x] IP suppression active — `request.remote_addr` returns `"0.0.0.0"`, logs stripped
- [x] Field stripping tested in isolation
- [x] PII engine tested with all 6 patterns
- [x] Burn endpoint functional (implemented + registered)
- [x] Burn pool cleanup job scheduled

---

## Tier 3: Medium Context (Complete)

Cross-module integration tasks. Depend on Tier 1 + 2 infrastructure.

### T3.1 — POST /api/contribute Full Integration
- **Status:** Done (implemented in T2.4)
- **File:** `core/contribute_routes.py`
- **What:** Full processing pipeline (strip → validate → server fields → PII scan → route → auto-create session_epochs). Built ahead of schedule as part of T2.4.

### T3.2 — Dashboard Updates for New Tables
- **Status:** Done
- **File:** `scripts/system_health_dashboard.py`
- **What:** 6 SpiritPool monitoring functions added:
  - `check_spiritpool_events_freshness()` — sp_events freshness + domain coverage breakdown
  - `check_quarantine_health()` — quarantine size, PII detection hit rate, growth trends, alerting thresholds (§6.2)
  - `check_session_epochs()` — session count, active/burned breakdown, burn rate, recent burn activity
  - `check_burn_pool()` — monthly trends, expiry status
  - `check_contributor_volume()` — contributor count, signal totals, daily event volume

### T3.3 — Legacy SpiritPool Route Compatibility
- **Status:** Done
- **File:** `postings/spiritpool_routes.py`
- **What:** `POST /api/spiritpool/contribute` dual-writes to both `job_postings` (via `ingest_job_posting()`) and `sp_events` (via `_dual_write_to_sp_events()`). Privacy controls applied: field stripping on batch + per-signal, PII scan on dual-write path. Session token preserved from M7 sanitize when present.

---

## Tier 3 Success Criteria

- [x] POST /api/contribute accepts signals and returns 200
- [x] PII-flagged events route to quarantine
- [x] Clean events store in sp_events table
- [x] Session epochs auto-created
- [x] Dashboard shows new table health (6 monitoring functions)
- [x] Legacy SpiritPool endpoint still works with dual-write
- [x] All existing automated collector pipelines unaffected

---

## Tier 4: High Context (Complete)

### T4.1 — Integration Test Suite §8.1–8.5
- **Status:** Done
- **File:** `tests/HeliosDeployment/test_integration_8x.py`
- **What:** 47 integration tests across 5 test classes:
  - `TestEndToEndSignalFlow` (14 tests) — full pipeline: strip, validate, store, IP suppression, server-set fields
  - `TestPIIDefenceInDepth` (12 tests) — all 6 PII patterns, quarantine routing, recursive walk, multi-PII, clean pass-through
  - `TestConfigSigningValidation` (6 tests) — backend resilience to extension fallback selector scenarios
  - `TestTokenRotation` (7 tests) — multi-token, multi-epoch, session epoch auto-creation, no cross-contamination
  - `TestForwardCompatibility` (8 tests) — 64-char hex tokens, large epoch_ids, unknown JSONB fields, Third Helios EDN fields
- **Verification:** All 47 tests pass.

### T4.2 — Full Privacy Audit
- **Status:** Done
- **File:** `docs/SECURITY_FINDINGS.md`
- **What:** Comprehensive audit of entire backend — all endpoint handlers, ORM models, logging configs, JSONB payload paths, database schemas. Audit techniques: grep verification, schema audit (48 tables), logging audit, endpoint audit, JSONB audit, log file check.
- **Findings:**
  1. **FINDING-01 (Medium, RESOLVED):** `consent_state` not stripped from incoming payloads. Fixed: added to `_FORBIDDEN_FIELDS` in `core/privacy.py`.
  2. **FINDING-02 (Low, RESOLVED):** Root logger lacked `_IPFreeFormatter`. Fixed: `server.py` root logger now uses `_IPFreeFormatter`.
- **Verification:** All 173 tests pass. Zero open violations.

## Tier 4 Success Criteria

- [x] All 5 integration tests (§8.1–8.5) pass — 47 tests total
- [x] Privacy audit complete — zero violations (2 found, 2 fixed)

---

## Tier 5: Full Budget (Not Started)

### T5.1 — End-to-End Pipeline Validation
- Production readiness gate. Full flow: extension → contribute → sp_events → scoring → dashboard.

### T5.2 — Performance Optimization & Load Testing
- Query optimization, connection pool tuning, benchmark events/second throughput.

### T5.3 — FH-2 Source Onboarding Framework
- Dedup keys per source, payload shape validation, scoring updates, onboarding template.

---

## Files Changed (Tier 1 + 2 Implementation)

| File | Change Type | What Changed |
|------|------------|-------------|
| `core/models/spiritpool.py` | **Created** | 5 ORM models for SpiritPool tables |
| `core/privacy.py` | **Created** | Field stripping + PII detection engine |
| `core/contribute_routes.py` | **Created** | POST /api/contribute + POST /api/burn endpoints |
| `core/database.py` | Modified | Added `_import_spiritpool_models()` call in `init_db()` |
| `alembic/env.py` | Modified | Added import of `core.models.spiritpool` |
| `server.py` | Modified | IP suppression middleware + contribute_bp registration |
| `config/scheduler.yaml` | Modified | Added `burn_pool_cleanup` job entry |
| `core/scheduler.py` | Modified | Added `_run_burn_pool_cleanup()` function + job registration |
| `scripts/one_shot/populate_metadata.py` | Modified | Added 5 table entries, ~28 column entries, 6 lineage entries |
| `alembic/versions/ae445d02acad_*.py` | **Created** | Migration for 5 SpiritPool tables |
| `docs/contracts/sp_events_contract.md` | **Created** | Data contract |
| `docs/contracts/quarantine_contract.md` | **Created** | Data contract |
| `docs/contracts/session_epochs_contract.md` | **Created** | Data contract |
| `docs/contracts/burn_pool_contract.md` | **Created** | Data contract |

---

## Known Gaps

| Gap | Priority | Status |
|-----|----------|--------|
| ~~No integration tests for contributor pipeline~~ | ~~High~~ | **Resolved** (T4.1 — 47 tests) |
| ~~Dashboard doesn't monitor new tables yet~~ | ~~Medium~~ | **Resolved** (T3.2 — 6 functions) |
| ~~Legacy `/api/spiritpool/contribute` doesn't dual-write~~ | ~~Medium~~ | **Resolved** (T3.3 — dual-write active) |
| ~~`SECURITY_FINDINGS.md` not updated with FH-1 controls~~ | ~~Medium~~ | **Resolved** (T4.2 — full audit) |
| Extension burn URL points to wrong endpoint (`/api/spiritpool/burn` vs `/api/burn`) | High | SpiritPool repo — handoff documented |
| CORS allows all origins (wildcard) | Medium | Fix in progress (Phase 1D) |
| No contributor-facing transparency metrics | Low | T5.1 |
| `meta_column_catalog` coverage may be < 70% for some legacy tables | Low | Ongoing |
