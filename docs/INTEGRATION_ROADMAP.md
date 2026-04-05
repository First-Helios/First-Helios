# Integration Roadmap — Context Window Complexity Ranking

> **Date:** 2026-04-05
> **Strategy:** Execute tasks in ascending context-window complexity. Low-token infrastructure and policy work first. Reserve 1M+ token budget for performance-critical integration and testing.

---

## Platform Context

First Helios is a **broad-scope data intelligence platform** that ingests, documents, and serves structured data across every domain relevant to a regional labor market and community — jobs, events, businesses, wages, economic indicators, mobility, and more. All of this feeds into dashboards people actually use.

Data enters from two paths: **automated collectors** (50+ API sources on scheduled jobs) and **SpiritPool contributors** (real people donating signals via a browser extension). The platform earns contributor trust through three commitments:

- **Secure data & profiles** — PII quarantined, IPs never logged, session tokens opaque
- **Transparent systems** — Every table documented, every flow traceable, health metrics visible
- **Broad collection under trust** — Collect widely, govern responsibly, show your work

This roadmap sequences the infrastructure needed to bring the contributor intake pipeline (FH-0/FH-1) to production while maintaining these commitments. The same quality and policy standards apply to all data domains.

---

## How This Roadmap Is Organized

Each task is rated by **context window complexity** — the estimated token budget an AI agent needs to hold the full relevant context in memory to complete the task correctly in a single pass.

| Tier | Token Estimate | Strategy |
|------|---------------|----------|
| **Tier 1: Minimal** | < 50K tokens | Simple, self-contained. One or two files. Do first. |
| **Tier 2: Low** | 50K–150K tokens | Moderate context. A few related files. Do second. |
| **Tier 3: Medium** | 150K–400K tokens | Cross-cutting concerns. Multiple modules. Do after infrastructure is stable. |
| **Tier 4: High** | 400K–800K tokens | Full pipeline understanding required. Deep integration. Allocate dedicated sessions. |
| **Tier 5: Full Budget** | 800K–1M+ tokens | Entire codebase context + handoff docs + test suites. Reserve budget. Performance-critical. |

**Rationale:** By completing Tier 1–2 tasks first, we build the infrastructure that Tier 3–5 tasks depend on. Low-token tasks are also lower risk — mistakes are cheaper to fix and easier to verify.

---

## Tier 1: Minimal Context (< 50K tokens)

These tasks are self-contained. Each can be completed by reading 1–3 files.

### T1.1 — Create Alembic Migration for New Tables
**Files needed:** `core/database.py` (Base class), `alembic/env.py`, latest migration in `alembic/versions/`
**Deliverable:** New migration file creating `events`, `quarantine`, `session_epochs`, `burn_pool`, `contributors` tables with correct column types, indexes, and no foreign keys from events→session_epochs.
**Why first:** Every other task depends on these tables existing.
**Estimate:** ~30K tokens
**Risk:** Low — additive migration, no changes to existing tables

### T1.2 — Register New Tables in Metadata
**Files needed:** `scripts/populate_metadata.py`, `core/metadata.py`
**Deliverable:** Metadata entries (meta_table_catalog, meta_column_catalog) for all 5 new tables.
**Why now:** Policy rule #11 — tables must be registered before data is written.
**Estimate:** ~25K tokens
**Risk:** Low — insert-only, no side effects

### T1.3 — Create Data Contracts
**Files needed:** `agentMailbox/FH-0_intake_foundation.md`, `agentMailbox/FH-1_backend_hardening.md`
**Deliverable:** Four contract files in `docs/contracts/`:
- `events_contract.md`
- `quarantine_contract.md`
- `session_epochs_contract.md`
- `burn_pool_contract.md`
**Why now:** Contracts define the rules before code enforces them.
**Estimate:** ~20K tokens
**Risk:** None — documentation only

### T1.4 — Register Data Lineage for New Tables
**Files needed:** `scripts/populate_metadata.py`, `core/metadata.py`
**Deliverable:** `meta_data_lineage` entries documenting:
- SpiritPool POST → events
- SpiritPool POST → quarantine (PII path)
- events → session_epochs (first-POST auto-creation)
- burn endpoint → burn_pool
- session_epochs → contributors
**Estimate:** ~20K tokens
**Risk:** None — metadata only

### T1.5 — Create ORM Models for New Tables
**Files needed:** `core/database.py` (for Base and pattern reference)
**Deliverable:** SQLAlchemy model classes for `Event`, `Quarantine`, `SessionEpoch`, `BurnPool`, `Contributor` — either in a new `core/models/spiritpool.py` or appended to appropriate module.
**Why before endpoints:** Models define the contract that endpoint code will use.
**Estimate:** ~35K tokens
**Risk:** Low — new file, no edits to existing models

---

## Tier 2: Low Context (50K–150K tokens)

These tasks require understanding a small cluster of related files.

### T2.1 — IP Suppression Middleware
**Files needed:** `server.py` (Flask app setup, logging config), Flask docs reference
**Deliverable:**
- Middleware that strips `request.remote_addr` before handlers run
- Custom Flask log formatter that excludes IP
- Werkzeug request handler override
**Why now:** Privacy priority 1. Must be in place before any SpiritPool traffic.
**Estimate:** ~60K tokens
**Risk:** Medium — must override framework defaults without breaking existing endpoints

### T2.2 — Field Stripping Utility
**Files needed:** `agentMailbox/FH-1_backend_hardening.md` (strip spec), `postings/spiritpool_routes.py` (existing pattern)
**Deliverable:** Utility function that strips `tabUrl` and `collectedAt` from top-level body and nested payload dict. Callable from any intake handler.
**Why now:** Defence-in-depth. Must run before any validation or storage.
**Estimate:** ~50K tokens
**Risk:** Low — pure function, no side effects

### T2.3 — PII Detection Engine
**Files needed:** `agentMailbox/FH-1_backend_hardening.md` (regex patterns), `core/metadata.py` (for pipeline_version pattern)
**Deliverable:** Module that:
- Recursively walks JSONB payload
- Tests all string values against PII regex patterns
- Returns list of matched pattern types or empty list
- Stateless, testable in isolation
**Why now:** Required by the intake endpoint but should be built and tested independently.
**Estimate:** ~70K tokens
**Risk:** Medium — regex edge cases (salary numbers vs credit cards, zip codes vs SSN fragments)

### T2.4 — Burn Endpoint
**Files needed:** New ORM models (from T1.5), `server.py` (route registration pattern)
**Deliverable:** `POST /api/burn` endpoint that:
- Sets session_epochs.contributor_id = NULL
- Sets session_epochs.burned_at = NOW()
- Increments burn_pool for current month
- Returns 200
**Estimate:** ~60K tokens
**Risk:** Low — simple write path with clear spec

### T2.5 — Burn Pool Maintenance Job
**Files needed:** `config/scheduler.yaml`, `core/scheduler.py`
**Deliverable:** Scheduled daily job: `DELETE FROM burn_pool WHERE expires_at < NOW()`
**Estimate:** ~50K tokens
**Risk:** Low — single SQL statement on a schedule

---

## Tier 3: Medium Context (150K–400K tokens)

These tasks cross module boundaries and require understanding multiple data flows.

### T3.1 — POST /api/contribute Endpoint
**Files needed:** New ORM models (T1.5), field stripping (T2.2), PII engine (T2.3), `postings/spiritpool_routes.py` (existing pattern), `server.py` (route registration), `agentMailbox/FH-0_intake_foundation.md` (full spec)
**Deliverable:** Complete intake endpoint implementing the full processing order:
1. Strip forbidden fields
2. Validate required fields
3. Set server-side fields (event_id, collected_at, pipeline_version)
4. Run PII scan
5. Route to quarantine or events
6. Auto-create session_epochs on first POST per token
7. Return 200 or 400
**Estimate:** ~250K tokens
**Risk:** Medium — must integrate T2.1, T2.2, T2.3 correctly
**Dependency:** T1.1, T1.5, T2.1, T2.2, T2.3 must be complete

### T3.2 — Dashboard Updates for New Tables
**Files needed:** `scripts/system_health_dashboard.py`, new table models, `core/metadata.py`
**Deliverable:** Add to system_health_dashboard.py:
- Events table freshness monitoring
- Quarantine table size and growth rate
- Session epoch count and burn rate
- PII detection hit rate
**Estimate:** ~150K tokens
**Risk:** Low — read-only queries against existing metadata patterns

### T3.3 — Legacy SpiritPool Route Compatibility Layer
**Files needed:** `postings/spiritpool_routes.py`, new `/api/contribute` endpoint (T3.1), `postings/ingest.py`
**Deliverable:** Ensure old-format `POST /api/spiritpool/contribute` (with `contributorId`, `domain`, `signals[]` batch format) continues to work during transition. Optionally dual-write to both `job_postings` and `events` tables.
**Estimate:** ~200K tokens
**Risk:** Medium — must not break existing extension versions

---

## Tier 4: High Context (400K–800K tokens)

These tasks require deep understanding of the full pipeline.

### T4.1 — Integration Test Suite §8.1–8.5
**Files needed:** All new endpoint code (T3.1), PII engine (T2.3), field stripping (T2.2), IP suppression (T2.1), ORM models (T1.5), all handoff docs (FH-0, FH-1, SPIRITPOOL_CONTEXT), existing test patterns in `tests/`
**Deliverable:** Five integration tests:
- §8.1: End-to-end signal flow (store, strip, timestamp, no IP)
- §8.2: PII defence-in-depth (email/phone/SSN → quarantine)
- §8.3: Config signing validation (no crash on fallback selectors)
- §8.4: Token rotation (multi-token, multi-epoch)
- §8.5: Forward-compatibility (64-char hex, large epoch, unknown JSONB)
**Estimate:** ~500K tokens
**Risk:** High — must validate entire pipeline end-to-end
**Dependency:** All Tier 1–3 tasks complete

### T4.2 — Full Privacy Audit
**Files needed:** Entire codebase grep for IP patterns, log configurations, database schemas, all endpoint handlers, all middleware
**Deliverable:**
- Grep verification: zero IP matches in all logs and DB
- Grep verification: zero tabUrl/collectedAt in stored data
- Review all `request.remote_addr` references
- Review all logging configurations
- Document findings in `SECURITY_FINDINGS.md`
**Estimate:** ~600K tokens
**Risk:** Medium — may uncover issues in existing code that need careful fixes

---

## Tier 5: Full Budget (800K–1M+ tokens)

Reserve budget for these. They require holding the entire system context simultaneously.

### T5.1 — End-to-End Pipeline Validation
**Files needed:** All source files, all configs, all handoff docs, all test results, database state
**Deliverable:** Full validation that:
- SpiritPool extension → POST /api/contribute → events table → scoring pipeline → dashboard
- All privacy controls active at every stage
- All metadata registered and lineage documented
- All SLAs satisfiable
- All integration tests passing
- System health dashboard accurate
- Contributor transparency metrics visible (collection volume, quarantine rate, domain coverage)
**Estimate:** ~900K tokens
**Risk:** High — this is the production readiness gate

### T5.2 — Performance Optimization & Load Testing
**Files needed:** Full codebase + database schema + query plans + rate management + scheduler config
**Deliverable:**
- Query optimization for events table at scale
- Connection pool tuning for concurrent SpiritPool writes alongside automated collector load
- Rate limit strategy under load
- Index optimization based on actual query patterns across all domains
- Benchmark results: events/second throughput, P95 latency
- Dashboard query performance under realistic multi-domain data volume
**Estimate:** ~1M tokens
**Risk:** Medium — performance work requires understanding the full system to avoid bottlenecks

### T5.3 — FH-2 Source Onboarding Framework
**Files needed:** Full codebase + all 6 content script payload shapes + dedup key docs + scoring queries
**Deliverable:**
- Documented dedup keys per source (Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Maps, Google Jobs)
- Payload shape validation per source (what fields each content script sends)
- Scoring query updates to consume events table alongside existing automated data
- Data contracts per source-specific payload shape
- Template for onboarding new domains beyond jobs/events/business
**Estimate:** ~800K tokens
**Risk:** Medium — requires understanding both SpiritPool extension and First Helios backend

---

## Execution Schedule

```
Week 1: Tier 1 (Infrastructure)
├── T1.1  Alembic migration for new tables
├── T1.5  ORM models for new tables
├── T1.2  Register new tables in metadata
├── T1.4  Register data lineage
└── T1.3  Create data contracts

Week 2: Tier 2 (Privacy Controls)
├── T2.1  IP suppression middleware
├── T2.2  Field stripping utility
├── T2.3  PII detection engine
├── T2.4  Burn endpoint
└── T2.5  Burn pool maintenance job

Week 3: Tier 3 (Integration)
├── T3.1  POST /api/contribute endpoint
├── T3.2  Dashboard updates
└── T3.3  Legacy compatibility layer

Week 4: Tier 4 (Validation)
├── T4.1  Integration test suite §8.1–8.5
└── T4.2  Full privacy audit

Week 5+: Tier 5 (Performance & Production)
├── T5.1  End-to-end pipeline validation
├── T5.2  Performance optimization
└── T5.3  FH-2 source onboarding framework
```

---

## Dependency Graph

```
T1.1 (Migration) ──────────────────────────────────────────────┐
T1.5 (ORM Models) ─────────────────┐                          │
T1.2 (Metadata Registration) ──┐   │                          │
T1.3 (Data Contracts) ─────────┤   │                          │
T1.4 (Lineage Registration) ───┘   │                          │
                                    │                          │
                          ┌─────────┴──────────┐               │
                          ▼                    ▼               │
                   T2.1 (IP Suppress)    T2.2 (Strip)          │
                          │              T2.3 (PII Engine)     │
                          │                    │               │
                          │              T2.4 (Burn EP) ◄──────┤
                          │              T2.5 (Burn Job) ◄─────┘
                          │                    │
                          └───────┬────────────┘
                                  ▼
                           T3.1 (/api/contribute)
                           T3.2 (Dashboard)
                           T3.3 (Legacy Compat)
                                  │
                                  ▼
                           T4.1 (Integration Tests)
                           T4.2 (Privacy Audit)
                                  │
                                  ▼
                           T5.1 (E2E Validation)
                           T5.2 (Performance)
                           T5.3 (FH-2 Onboarding)
```

---

## Budget Allocation Summary

| Tier | Tasks | Combined Token Estimate | % of 1M Budget |
|------|-------|------------------------|----------------|
| Tier 1 | 5 tasks | ~130K | 13% |
| Tier 2 | 5 tasks | ~290K | 29% |
| Tier 3 | 3 tasks | ~600K | 60% |
| Tier 4 | 2 tasks | ~1.1M | 110% (2 sessions) |
| Tier 5 | 3 tasks | ~2.7M | 270% (3+ sessions) |

**Key insight:** Tiers 1–3 fit comfortably within budget and deliver a working, policy-compliant intake pipeline across all domains. Tiers 4–5 require dedicated sessions with full context loaded, and should be scheduled after the foundational infrastructure is stable and verified manually. The budget allocation prioritizes getting the trust infrastructure right before optimizing for scale.

---

## Success Criteria (Per Tier)

### After Tier 1
- [ ] All 5 tables exist in database
- [ ] All tables registered in meta_table_catalog
- [ ] All columns registered in meta_column_catalog
- [ ] Data lineage entries exist for all new flows
- [ ] Data contracts exist in docs/contracts/

### After Tier 2
- [ ] IP suppression active — grep test passes
- [ ] Field stripping tested in isolation
- [ ] PII engine tested with all 6 patterns
- [ ] Burn endpoint functional
- [ ] Burn pool cleanup job scheduled

### After Tier 3
- [ ] POST /api/contribute accepts signals and returns 200
- [ ] PII-flagged events route to quarantine
- [ ] Clean events store in events table
- [ ] Session epochs auto-created
- [ ] Dashboard shows new table health
- [ ] Legacy SpiritPool endpoint still works
- [ ] All existing automated collector pipelines unaffected

### After Tier 4
- [ ] All 5 integration tests (§8.1–8.5) pass
- [ ] Privacy audit complete — zero violations

### After Tier 5
- [ ] Production deployment cleared
- [ ] Performance benchmarks meet SLA under multi-domain load
- [ ] FH-2 onboarding framework ready for new content scripts and domains
- [ ] Contributor transparency metrics visible in dashboard
