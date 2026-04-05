# Test Logic & Intentions — HeliosDeployment Suite

> Reference for auditors reviewing test rationale, fixture design,
> implementation patterns, and the relationship between tests and
> production code.

---

## 1. Suite Architecture

```
tests/HeliosDeployment/
├── conftest.py                  # Shared fixtures (DB, Flask app, payloads)
├── test_schema_storage.py       # §2 — ORM-level table schema validation
├── test_privacy_security.py     # §3 — Privacy controls (unit tests)
├── test_api_contract.py         # §4 — Endpoint behavior (integration tests)
├── test_metadata_quality.py     # §5 — Metadata completeness (seeded DB)
├── test_observability.py        # §6 — Audit trail + scheduled maintenance
└── TestingResults/
    ├── test_audit_log.md        # Per-test status log with cross-references
    ├── test_logic_guide.md      # THIS FILE — rationale and patterns
    └── error_code_tracking.md   # HTTP error code catalog + regression log
```

### Design Principle: One Pillar Per File

Each test file maps to a single pillar from `DEVELOPMENT_REQUIREMENTS_PLAN.md`.
This makes it easy to audit: if §3 (Privacy) has an issue, you look at exactly
one file. Cross-cutting tests (e.g. A-08/A-09 test field stripping at the
endpoint level) are placed in the file for the outer concern (§4 API Contract)
because they test the integration, not the unit.

---

## 2. Fixture Design

All fixtures live in `conftest.py`. The strategy is **complete isolation per test**.

### engine (function-scoped)

```
Purpose: Fresh in-memory SQLite engine for each test
Scope:   function (NOT session) — each test starts with empty tables
Why:     Prevents data leakage between tests. Endpoint tests commit data
         (the contribute route calls db.commit()), so sharing an engine
         across tests would cause cross-contamination.
```

**Key adapters registered at import time:**
- `JSONB → JSON` — PostgreSQL JSONB does not exist in SQLite; the compiler
  adapter renders it as standard JSON
- `ARRAY → TEXT` — PostgreSQL ARRAY (used in events/models.py) rendered as
  TEXT for SQLite

These adapters mean the ORM models run against SQLite in tests without
modifying production model definitions.

### db (function-scoped)

```
Purpose: SQLAlchemy Session for ORM-level tests (schema, observability)
Pattern: Create session → yield → rollback → close
Usage:   test_schema_storage.py, test_observability.py
```

ORM tests use `db.add()` / `db.flush()` directly. They never go through
Flask/HTTP — they test the data layer in isolation.

### seeded_db (function-scoped)

```
Purpose: SQLAlchemy Session pre-loaded with ALL metadata from populate_metadata.py
Pattern: Create session → run populate functions → yield → rollback → close
Usage:   test_metadata_quality.py only
```

This fixture calls the same `populate_table_catalog()`, `populate_column_catalog()`,
and `populate_data_lineage()` functions that production uses. The metadata tests
verify that the *populate script* produces the right entries — not that some
hand-crafted fixture is correct. This is intentional: if someone changes
`populate_metadata.py` and breaks a registration, the tests catch it.

### app / client (function-scoped)

```
Purpose: Flask test application with contribute_bp blueprint registered
Pattern: Create app → monkeypatch init_db/get_session → register blueprint → yield
Usage:   test_api_contract.py, test_privacy_security.py (IP suppression only)
```

**Monkeypatching strategy:**
- `core.contribute_routes.init_db` → returns the test engine
- `core.contribute_routes.get_session` → returns a Session bound to test engine

This means the endpoint code calls `init_db()` and `get_session()` as normal,
but gets the in-memory SQLite engine instead of production PostgreSQL. Data
committed by endpoints is visible to subsequent queries on the same engine.

**IP suppression replication:**
The test app defines `_IPSuppressedRequest` identically to `server.py`. This
validates that the IP suppression pattern works in the Flask request lifecycle,
not just in isolation.

### clean_signal / pii_signal_email (function-scoped)

```
Purpose: Standard test payloads matching POST /api/contribute schema
Pattern: Return fresh dict each time (no mutation leakage between tests)
```

`clean_signal` passes all validation and PII checks → stored in sp_events.
`pii_signal_email` has `hiring@acme.com` in payload → routed to quarantine.

---

## 3. Test Category Intentions

### test_schema_storage.py — "Can the database hold what we promised?"

**Intent:** Verify that the SQLAlchemy ORM models create tables with the
correct column types, constraints, and behaviors. These are the §2 acceptance
criteria from the dev requirements.

**What it does NOT test:** HTTP behavior, processing logic, or middleware.
These tests interact with the ORM directly.

**Key patterns:**
- `db.flush()` (not `db.commit()`) — tests constraints at the DB level
  without permanently writing data
- `pytest.raises(IntegrityError)` — validates UNIQUE constraints
- JSON round-trip via `json.loads()` — JSONB stored as text in SQLite,
  so we verify the data survives serialize/deserialize

**Critical tests:**
- S-01 (64-char hex token) — forward-compatibility with Second Helios
- S-03 (epoch_id 999999) — no upper bound per spec
- S-04 (unknown JSONB) — payload extensibility is a core contract

### test_privacy_security.py — "Are the privacy walls actually standing?"

**Intent:** Verify the three privacy layers in isolation:
1. IP suppression (middleware level)
2. Field stripping (utility function level)
3. PII detection (regex engine level)

**Why unit-level:** These are defence-in-depth layers. Each must work
independently. If the endpoint breaks, privacy controls must still function
at the unit level. Integration tests in test_api_contract.py verify the
layers work together.

**False positive guards (P-26 through P-31):**
The PII regex for credit cards (`\b\d{13,19}\b`) can match long numbers.
We explicitly test that:
- Salary values ("75000") are NOT flagged
- ZIP codes ("78701") are NOT flagged
- Integer types are not scanned at all (only strings)

This is documented because salary data is the most common legitimate
numeric content in job signals.

**Recursive scan tests (P-15, P-16, P-31):**
SpiritPool payloads have arbitrary nesting. The PII scanner must walk
dicts inside lists inside dicts. These tests verify the recursive walker
(`_scan_value()`) handles all container types.

### test_api_contract.py — "Does the endpoint behave as documented?"

**Intent:** Verify the full HTTP contract for both endpoints:
- POST /api/contribute — validation, processing order, routing
- POST /api/burn — session burn mechanics

**Processing order verification:**
The dev requirements define a strict 7-step processing order. Tests validate
this by checking observable effects:
1. Strip (A-08, A-09 — stored payload has no tabUrl/collectedAt)
2. Validate (A-15 through A-24 — bad input returns 400)
3. Server fields (A-03, A-04, A-05 — event_id/collected_at/pipeline_version)
4. PII scan (A-10 through A-14 — routing to quarantine)
5. Storage (A-02 — clean signal in sp_events)
6. Session epoch (A-06, A-07 — auto-create, no duplicate)
7. Response (A-01 — 200 for clean, A-10 — 200 for quarantined)

**Burn idempotency (A-33):**
Burning a non-existent token returns 200, not 404. This is intentional:
the client doesn't need to know whether the token existed. Idempotency
prevents information leakage about session existence.

### test_metadata_quality.py — "Is the metadata catalog complete?"

**Intent:** Verify that `populate_metadata.py` produces the correct metadata
entries for all 5 SpiritPool tables. This is the §5.1 requirement—tables
must be documented before data is written.

**seeded_db approach:**
These tests use the `seeded_db` fixture which runs the actual populate
functions. This means: if the production populate script is correct, these
tests pass. If someone adds a column to the ORM model but forgets to update
`populate_metadata.py`, these tests catch the drift.

**Column coverage check:**
Tests M-04 through M-08 compare ORM model columns against
`meta_column_catalog` entries. The assertion `orm_columns - documented`
identifies any column that exists in the model but not in the catalog.

**Contract file checks (M-11, M-12):**
These are filesystem checks, not database checks. They verify that
`docs/contracts/` has the expected .md files and they are non-trivial
(> 100 bytes — not just an empty placeholder).

### test_observability.py — "Can we audit and maintain what we built?"

**Intent:** Verify audit trail fields are stored correctly and the
maintenance job infrastructure exists.

**Audit trail tests (O-01 through O-04):**
Every data record must be traceable. `pipeline_version` on sp_events and
`rule_version` on quarantine enable re-processing old data through improved
PII detection in future eras (e.g., NER in Second Helios).

**Maintenance job tests (O-05 through O-08):**
The burn pool cleanup job must exist in scheduler config and be importable.
O-05 and O-06 test the DELETE logic directly against the ORM, simulating
what `_run_burn_pool_cleanup()` does. This validates the SQL without
requiring the scheduler to actually run.

---

## 4. Fixture Dependency Graph

```
engine ◄──── db              (ORM-level tests)
   │
   ├──────── seeded_db       (metadata tests — pre-populated)
   │
   └──── app ◄── client      (HTTP-level tests)
              │
              ├── clean_signal
              └── pii_signal_email
```

All paths start from `engine`. Each test gets its own engine instance,
guaranteeing complete isolation.

---

## 5. Implementation Files Under Test

| Test File | Production Files Exercised |
|-----------|--------------------------|
| test_schema_storage.py | `core/models/spiritpool.py` (SpEvent, SessionEpoch, Quarantine, BurnPool, Contributor) |
| test_privacy_security.py | `core/privacy.py` (strip_forbidden_fields, scan_pii), `server.py` (_IPSuppressedRequest, _IPFreeFormatter) |
| test_api_contract.py | `core/contribute_routes.py` (contribute, burn), `core/privacy.py`, `core/models/spiritpool.py` |
| test_metadata_quality.py | `scripts/populate_metadata.py` (populate_table_catalog, populate_column_catalog, populate_data_lineage) |
| test_observability.py | `core/models/spiritpool.py`, `core/scheduler.py` (_run_burn_pool_cleanup), `config/scheduler.yaml` |

---

## 6. Known Limitations

1. **SQLite vs PostgreSQL**: Tests run against SQLite with type adapters.
   JSONB behavior in SQLite (stored as plain text) may differ from PostgreSQL
   (binary storage). JSON round-trip correctness is validated but JSONB-specific
   operators (e.g., `@>`, `?`) are not exercisable in SQLite.

2. **Metadata tests use populate script**: If `populate_metadata.py` is wrong,
   the metadata tests may pass against wrong data. The tests verify completeness
   (all columns documented) not correctness (descriptions are accurate). Manual
   review of metadata content is still required.

3. **No load/concurrency testing**: All tests are single-threaded, single-request.
   Concurrent write scenarios (e.g., two contributors with same session_token)
   are deferred to T5.2.

4. **No network mocking**: Tests do not simulate actual HTTP connections or
   extension behavior. They use Flask's test_client which bypasses WSGI middleware
   at the socket level.

5. **UTC deprecation warnings**: Tests use `datetime.utcnow()` matching the
   production code. Python 3.12+ emits deprecation warnings for this. The
   warnings are expected and do not indicate a test failure.

---

## 7. Adding New Tests

When adding tests to this suite:

1. **Assign an ID** following the prefix convention: S- (schema), P- (privacy),
   A- (api), M- (metadata), O- (observability)
2. **Write a docstring** on the test method — this becomes the Description in
   the audit log
3. **Map to a Dev Req section** — every test must trace to a §X.Y reference
4. **Update test_audit_log.md** with the new row
5. **Update error_code_tracking.md** if the test validates HTTP status codes
6. **Use the correct fixture** — `db` for ORM, `client` for HTTP, `seeded_db`
   for metadata
