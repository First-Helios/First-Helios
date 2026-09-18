# Step 5 provider prerequisite review

**Date:** 2026-09-18
**Branch:** `Plan-0002-Step-5`; starting HEAD `238627adf5019e9d9b39a33296f22932979028e0`.
**Scope:** Provider contracts and functions only; no Menu implementation.
**Status:** Provider prerequisite prepared and verified for separate owner review;
provider/SQL acceptance is outstanding. Menu implementation has not started.

Owner Fortune accepted [ADR-0005](../adr/0005-immutable-menu-snapshots-and-selection.md)
and the reconciled proposal on 2026-09-17. That approval was not requested again.
The remaining pre-implementation image gate passed before any provider edits:
strict `make ci` on the CI PostGIS image ran **180 passed, zero failures/skips**,
including the existing migration and concurrency tests, and `alembic check`
reported no drift. The [earlier gate record](0002-step-5-provider-prerequisite-gates.md)
retains its access failures and approval history.

## What changed and why

A consumer needs to know both what immutable Bronze input says and whether its
scope can accept a new claim now. A single-subject eligibility check could not
validate a batch of local/base scopes, their exact current resolution events,
or pending lineage that had not yet updated currentness.

Bronze now publishes frozen `RecordVersionReference` and `EvidenceReference`
values through `get_record_version`, `get_evidence`, and
`evidence_supports_version` in its contracts module. Evidence supports exactly
the requested version or that version's non-null Capture. Equal source, URL,
or canonical business key does not substitute for exact ownership. Canonical
keys exclude surrogate IDs, include immutable source/capture/observation data,
use explicit UTC times, and freeze nested arrays into tuples. Absent Capture
is an empty tuple; absent optional strings use an empty string, excluded as an
actual value by the relevant Bronze constraints. These keys can be compared
without mixing None and tuple/string values.

Identity publishes frozen `ResolvedScopeRequest` and `ResolvedScope`, and
`require_resolved_scopes(session, requests)`. Submit the complete local/base
batch together. The SQL entrypoint takes parallel arrays of Subject, Source
Record, and expected resolution-event IDs. It returns scopes in request order,
including Establishment parents, operating state, and effective interval.
Closure is not retirement and does not prevent historical claim admission.

The shared feature predicate preserves Step 4's policy: a Place has a nonblank
address (including Python's Unicode whitespace semantics) or coordinates; an
Organization has its name/fingerprint pair and a current resolved source key;
an Establishment has current eligible parents meeting those features. The root
need not already be eligible for promotion. Admission additionally requires
stored eligible readiness, allowed scope kind, exact current record/event,
and no pending unapplied lineage input in the full dependency set. An expected
resolution event created in the current transaction is rejected: mixed
resolve/admit orchestration remains unsupported.

Existing readiness/promotion entrypoints delegate to this SQL feature predicate
and lock provider, avoiding a second policy implementation. Matching commands,
thresholds, typed models, and existing database function definitions are unchanged.

## Locks, errors, and transaction contract

Identity takes the maintenance advisory lock, the sorted dependency union of
Subjects and currentness rows, typed feature rows in Subject order, then sorted
Source Records including Organization readiness proofs. Row locks use
`FOR NO KEY UPDATE`; concurrent Bronze FK key-share checks remain compatible.
Dependency/proof discovery is revalidated under lock; an expanded dependency
set causes SQLSTATE `40001`, not extra out-of-order locking. Establishment
parent relationships remain immutable under the existing database trigger.

Pending input membership blocks admission before deferred lineage application,
including surviving merge inputs and ancestors. After application, currentness
and features determine admission; a surviving eligible merge input can pass.
A change without members does not yet name a scope, but incomplete lineage
still cannot commit. A successful earlier admission is not checked again at
commit: an ordered retirement/remap afterward can commit history, while a later
admission using the old scope/event fails. No deferred consumer trigger is added.

Providers never commit or automatically retry. Business admission rejection is
SQLSTATE `23514`, constraint `ck_resolved_scope_admission`; Python translates
only that rejection to `SubjectNotEligibleError`. Roll back the transaction
or caller-owned savepoint after a SQL failure. `40001` and `40P01` propagate;
the caller must retry the entire transaction with fresh state. Arbitrary
pre-acquired locks can still deadlock; the tests deliberately demonstrate one
such conflict and complete rollback/retry without a partial marker write.

Bronze lookup functions are transaction-visible readers of immutable data;
they do not certify commit status or semantic truth of an excerpt. Their
downstream interpretation contract requires already committed Bronze input.
The scope guard enforces a committed expected resolution event. No mixed
Bronze-persist/resolve/consumer orchestration is advertised. Future Menu must
retain its committed-input boundary and separately enforce aggregate admission,
support, stream lifecycle, and immutable integrity.

## Migration and concrete SQL

[Revision b72e6a90c431](../../alembic/versions/b72e6a90c431_add_provider_scope_contracts.py)
follows `91f4c2a7d6e8` and adds exactly these nine functions:

| Owner | Functions |
|---|---|
| Bronze | `capture_business_key`, `record_version_info`, `evidence_info`, `evidence_supports_version` |
| Identity | `scope_dependencies`, `subject_feature_ready`, `has_pending_lineage`, `lock_scope_inputs`, `require_resolved_scopes` |

Review the generated [upgrade SQL](sql/0002-step-5-provider-upgrade.sql) and
[downgrade SQL](sql/0002-step-5-provider-downgrade.sql) separately. Upgrade creates
functions and advances Alembic's revision. Downgrade drops only those functions
in dependency order without CASCADE, then restores the parent revision.
No tables, columns, indexes, triggers, provider rows, or applied migrations are
altered. A runtime rollback must pair the schema downgrade with the earlier
application version, because the new Python contracts require these functions.
No application-data execution or deployment is part of this work.

## Verification and preservation

The exact CI image `imresamu/postgis:16-3.4` was pulled with digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`.
It reports PostgreSQL **16.4** and PostGIS **3.4.3**; the earlier native baseline
was PostgreSQL 16.14. This result does not pretend the image uses 16.14.
The fresh container `helios-provider-6dd8c5m1` exposed only
`127.0.0.1:32768`, with baseline database `helios_provider_test`, then fresh
final acceptance database `helios_provider_final_test`, and test credentials
`helios/helios`. It used no application volume or Compose/deployment settings.
Docker ran through `/snap/docker/current/bin/docker` with allowed sandbox
escalation. No Docker permissions were changed. The disposable container was
stopped after verification; its test databases and temporary scripts are not
prerequisites for the next session.

```bash
export DATABASE_URL='postgresql+psycopg://helios:helios@127.0.0.1:32768/helios_provider_final_test'
HELIOS_STRICT_DB_TESTS=1 make ci
uv run alembic check
uv run alembic upgrade 91f4c2a7d6e8:b72e6a90c431 --sql
uv run alembic downgrade b72e6a90c431:91f4c2a7d6e8 --sql
```

| Verification | Result |
|---|---|
| Pre-implementation strict CI-image baseline | **180 passed, 0 failed, 0 skipped**, 25.82s; lint/types/lockfile passed; drift check clean. |
| First complete provider run | **262 passed, 0 failed, 0 skipped**, 76.47s. |
| Review regression | Optional-Capture ordering reproduced a TypeError in **1** focused test; fixed without changing identity policy. **4** focused tests then passed, covering absent Capture and all three optional capture-key fields. |
| Reused-database attempt | **264 passed, 1 failed, 0 skipped**, 76.68s. An existing retry test expected one Capture but found 178 after earlier committed fixtures. No test assertion was weakened; final acceptance uses a newly created database. |
| Final strict CI-image suite | **265 passed, 0 failed, 0 skipped**, 79.20s, on fresh `helios_provider_final_test`; 98% reported coverage. Lint, mypy (**44 source files**), and lockfile passed. |
| Final drift | **No new upgrade operations detected**, exit 0. |
| SQL artifacts and documentation | Both SQL directions match current offline generation (terminal whitespace normalized); **87** local link targets exist across **6** updated review/status documents; `git diff --check` passed. |
| Explicit hooks including untracked files | Applicable hooks passed across **19** changed/new files after normalizing SQL terminal newlines. YAML/TOML hooks had no applicable files in this explicit selection; full `make ci` checked both. No database tests skipped. |

The **85** added tests comprise **56** provider contract tests, **27**
real-connection concurrency tests, **1** seeded provider migration round trip,
and **1** offline SQL generation test. The full suite includes **41** concurrency
tests and **2** seeded migration round trips. Migration preservation compares every row/column across all **21**
provider tables, all original function definitions, table constraints/indexes,
triggers, views, and sequence inventories. Downgrade exactly restores the parent
inventory; re-upgrade exactly restores the new inventory. The existing legacy
reset test now permits exactly the named new functions while retaining its
original preservation and round-trip assertions.

The initial **82** tracked/untracked files were hashed before edits. Existing
documentation modifications and the untracked gate record were retained.
ADR-0005's acceptance, ADR-0004, readiness reassessment, reconciliation history,
verification hardening, ML notes, models, applied migrations, dependencies,
CI configuration, and deployment settings are preserved. ML notes retain hash
`ac509f8b5db62599fb71db3a8b4681cbde5ba59c51b3240c2cc1eeeb4189db1c`.
No reset, clean, discard, commit, push, merge, or deployment was performed.

## Remaining boundary and next unit

This prepares the provider prerequisite for owner review. It does not implement
or verify Menu snapshots, Evidence support semantics, inheritance, pins,
withdrawal/restoration, accepted-claim selection, K/O/E cutoffs, applicability,
or price ranking. Those accepted requirements remain unchanged. No Organization
or sibling price fallback, Gold, APIs, extraction, ML, fuzzy matching, Step 6,
new runtime dependency, or deployment changes are included. No load/scalability
or application-image build/smoke acceptance is claimed.

**One next work unit:** review this provider diff and both SQL directions,
resolve provider-only findings, and record the review disposition. Completion
means the ownership/policy/locking boundaries and migration preservation have
been reviewed against the concrete artifacts, any fixes pass strict CI-image
checks without database skips, and the owner records provider acceptance before
separate Menu implementation work begins. Do not treat design acceptance as
approval of unseen SQL or application-data execution.

Use configured `gpt-6-astra`, high reasoning, Default/implementation mode, one
agent, concise/low verbosity. Configuration was read, not changed; no runtime
model switch is claimed. Continue this chat for fixes within this provider
unit. Prefer a **new session for the distinct provider review unit** once this
preparation is complete, using the repository and the prompt below.

## Copyable next-work prompt

```text
Review Helios Plan 0002 Step 5's prepared provider prerequisite and concrete
upgrade/downgrade SQL. Use configured gpt-6-astra, high reasoning,
Default/implementation mode, one agent, concise reporting. Complete review,
authorized provider-only fixes and verification; do not stop at a plan.
Never rely on prior chat access.

Verify branch Plan-0002-Step-5; report mismatch before switching. Preserve all
tracked modifications and untracked files, including verification hardening,
Menu design documents, readiness reassessment, provider gate/review records,
SQL artifacts, tests, and docs/HumanDevNotes/MLDataExtractionPlan.md.
Do not reset, clean, discard, commit, push, merge, or deploy.

Read CLAUDE.md, README.md, CONTRIBUTING.md, relevant ROADMAP.md sections,
docs/adr/0004-modular-monolith-identity-and-lifecycle.md,
docs/adr/0005-immutable-menu-snapshots-and-selection.md,
docs/plans/0002-identity-foundation-before-menu.md,
docs/plans/0002-step-5-menu-schema-proposal.md,
docs/reviews/0002-step-5-readiness-reassessment.md,
docs/reviews/0002-step-5-menu-design-reconciliation.md,
docs/reviews/0002-step-5-provider-prerequisite-gates.md,
docs/reviews/0002-step-5-provider-prerequisite.md, and its linked SQL artifacts.
Review the provider contracts, b72e6a90c431 migration, and focused tests.

ADR-0005 and its reconciled proposal were accepted by Fortune on 2026-09-17;
do not request that design approval again or reopen accepted defaults.
The pre-implementation gate passed on CI image imresamu/postgis:16-3.4:
180 tests, zero failures/skips, and no Alembic drift before provider edits.
Final provider strict CI passed 265 tests with zero failures/skips, including
41 concurrency tests and 2 seeded migration round trips; alembic check found
no drift. A reused-database attempt failed an existing empty-database assertion;
final acceptance used a newly created database. See the review record for limits.
Docker access works through /snap/docker/current/bin/docker with sandbox
escalation. Use a fresh disposable *_test database on that image for required
checks; do not assume old containers/databases/scripts remain. Never change
Docker permissions or deployment settings. Skips never establish acceptance.

Review only Bronze-owned immutable version/Evidence lookups and canonical
keys; Identity-owned batch scope admission, dependency expansion, lock order,
pending-lineage checks and shared feature predicate; one forward provider-only
function revision after 91f4c2a7d6e8. Promotion must work from provisional;
admission requires eligible readiness and exact current committed resolution
event/Source Record mapping. Preserve matching/readiness policy and committed
Bronze input. Readers do not certify commit status or semantic source truth.
Check Python/SQL parity, both lineage/admission orderings, forced deferred
checks, real concurrency, whole-transaction retry, and complete provider
row/object preservation through upgrade/downgrade/re-upgrade. Review generated
SQL separately; no application-data execution is authorized.

Preserve immutable snapshots, direct factual Evidence with structural/inherited
support, inherit/full replacement/suppression, pins surviving ordinary
supersession, withdrawal tombstones and explicit restoration/rebasing,
accepted-claim history with K/O/E cutoffs, revision uniqueness across remaps,
stable correspondence, and applicability after ancestor intersection.
Never infer local prices from Organization or sibling-location prices.
Keep USD, exact contexts, individual modifiers, and committed Bronze input.

No Menu implementation, matching-policy changes, Gold, APIs, extraction,
ML, fuzzy matching, Step 6, runtime dependencies, or deployment changes.
Do not modify applied migrations or historical acceptance records. The new
uncommitted provider revision remains a review draft; keep SQL artifacts in
sync with any authorized fixes. Run required make ci and drift/preservation
checks on disposable data. Record findings, fixes, exact verification counts,
remaining limits, and owner review disposition without inventing approval.
Stop at provider review/acceptance; do not start Menu implementation.

End with (1) what changed and why; (2) verification counts and remaining limits;
(3) one next work unit and completion criteria; (4) recommended model,
reasoning, mode, agent count, verbosity; (5) explicit same-chat/new-session
recommendation and reason; (6) a self-contained copyable next-work prompt
preserving this same completion-and-handoff requirement. Continue the same
chat for fixes within a unit; prefer a new session at a distinct completed
boundary. Never rely on prior chat access.
```
