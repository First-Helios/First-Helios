# Step 5 provider implementation and concrete SQL review

**Date:** 2026-09-18. **Branch:** `Plan-0002-Step-5`.
**Starting HEAD:** `11fad9a`; the working tree was clean.
**Disposition:** One high-priority admission defect reproduced and fixed in the
provider review draft. Final verification is recorded below. Owner acceptance
of the provider implementation and both SQL directions remains **pending**.
No Menu implementation or application-data execution is authorized by this record.

The [preparation record](0002-step-5-provider-prerequisite.md),
[gate history](0002-step-5-provider-prerequisite-gates.md), readiness reassessment,
and design reconciliation retain their historical results unchanged. Fortune's
2026-09-17 acceptance of ADR-0005 and its reconciled proposal is settled.
The prior handoff described uncommitted provider work; this checkout already
tracks it in HEAD. Git tracking is not owner SQL acceptance or deployment.
Only the expressly authorized review-draft revision `b72e6a90c431` is corrected;
all earlier migration files remain byte-identical.

## Finding and correction

**P1 — stale resolution could pass admission at stronger isolation.**
`identity.lock_scope_inputs` locked Subjects, currentness, typed features, and
Source Records, but did not lock the mutable `current_resolution` proofs.
Unassigning or remapping an Establishment changes its resolution projection
without updating its Subject or immutable Source Record. A Repeatable Read or
Serializable transaction with an older snapshot could therefore acquire those
unchanged rows' locks and admit the obsolete event. Removing an Organization's
last proof through raw SQL had the same issue when stored readiness stayed eligible.

An independent probe committed stale admissions after unassign/remap in both
isolation levels. The twelve regression cases then all failed before the fix:
three changes, two isolation levels, and Python/raw-SQL entrypoints.

The narrow fix locks the selected resolution projection rows in Source Record
order, **after** the sorted Source Record locks. Both requested mappings and
Organization readiness proofs are covered. A newer projection now produces
SQLSTATE `40001`; after a whole-transaction rollback, the new transaction rejects
the stale request with `ck_resolved_scope_admission`. Regression marker writes
prove rollback is complete. The existing real deadlock test still verifies a
successful whole-transaction retry for `40P01`.

No readiness or matching policy changes, new function, table, dependency,
automatic retry, or implicit commit were needed. The Python contract documents
the stronger-isolation behavior. Upgrade SQL was regenerated; downgrade SQL is
byte-identical because the same nine functions are removed.

## Review coverage and concrete SQL disposition

| Area | Reviewed result |
|---|---|
| Bronze ownership and canonical keys | Frozen version/Evidence DTOs delegate traversal to Bronze SQL. Exact version or matching non-null Capture support only; source/URL equality cannot substitute. Canonical keys exclude surrogate IDs, use UTC observation/capture times, and represent absent Capture/strings consistently. Existing tests cover duplicate business identities, timezone changes and optional-field ordering. |
| Committed input | Readers remain transaction-visible lookups, not commit certificates or semantic source validators. The consumer must retain already committed Bronze input. Admission rejects an expected resolution event created in its own transaction; forcing deferred constraints does not make it committed. |
| Feature policy and promotion | Compared the SQL predicate with the previous Step 4 Python implementation. Place whitespace/coordinate rules, Organization name/fingerprint plus resolved key, and current eligible Establishment parents remain the same. Promotion works from provisional; admission additionally needs eligible readiness and an exact current record/event. Closure is not retirement. |
| Batch locks and lineage | Complete dependency union, sorted Subjects/currentness/typed features, sorted records and now resolution proofs, maintenance lock, and revalidation remain Identity-owned. Pending input membership includes parents and surviving merge inputs. Both admission/lineage orderings, explicit deferred checks, real commits, reversed batches, FK inserts and rebuild conflicts are covered. |
| Upgrade SQL, reviewed separately | Transactional creation of exactly four Bronze and five Identity functions, then one Alembic revision update. No provider DML, table/column/index/trigger changes, replacement of existing functions, or upward dependencies. The six-line projection-lock correction appears identically in the migration and artifact. |
| Downgrade SQL, reviewed separately | Drops only the same nine signatures, consumers before helpers, without CASCADE; resets Alembic to `91f4c2a7d6e8`. Pair a runtime schema rollback with the previous application code, because current contracts require these functions. No application execution was performed. |
| Preservation | Seeded round trips now execute both Alembic operations and the actual checked-in SQL files. Every row/column in all 21 provider tables, original function definitions, constraint/index/trigger inventories, views, sequences and sequence values/`is_called` survive. Parent inventory and re-upgraded inventory are compared exactly. Both SQL artifacts must match fresh offline generation. |

Concrete artifact SHA-256 values for owner review:

- [Upgrade](sql/0002-step-5-provider-upgrade.sql):
  `1ec770dc0ef22bf936515ab14a54af24f902f3cc36c79271172c35cc9297a7be`.
- [Downgrade](sql/0002-step-5-provider-downgrade.sql):
  `f37fa34c11c1ac07e1e54d5c12648cb60412df6f21617c5d9dc7e8c40747e1cd`.

## Verification

The fresh container `helios-provider-review-20260918` used CI image
`imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`,
with PostgreSQL **16.4** and PostGIS **3.4.3**. Docker ran through
`/snap/docker/current/bin/docker` with sandbox escalation. Its only published
port was `127.0.0.1:32769`; no application volume or deployment configuration
was used. All four databases were newly created disposable `*_test` databases.

| Check | Observed result |
|---|---|
| Starting strict CI, fresh `helios_provider_review_test` | **265 passed, 0 failed, 0 skipped**, 79.44s; hooks, types and lockfile passed. |
| New regressions before fix, separate `helios_provider_regression_test` | **12 failed, 27 deselected**, 6.77s: stale admission did not raise `40001`. These are deliberate defect reproductions, not acceptance. |
| Focused checks after fix, fresh `helios_provider_fixed_test` | **42 passed, 0 failed, 0 skipped**, 29.13s: 39 provider concurrency cases, two seeded round-trip paths and offline SQL comparison. |
| Final strict `make ci`, fresh `helios_provider_review_final_test` | **278 passed, 0 failed, 0 skipped**, 88.20s; reported coverage 98%; all hooks, mypy (**44 source files**) and lockfile passed. |
| Included final coverage | **53 concurrency tests** (14 foundation + 39 provider), **three seeded migration round trips** (legacy reset + provider Alembic + concrete SQL), **56 provider contract tests**, and offline SQL artifact equality. Counts overlap the 278 total. |
| Final drift and revision | `alembic check`: **No new upgrade operations detected**, exit 0. Database revision and sole Alembic head both `b72e6a90c431`. |
| Final documentation and hooks | **70 local link targets across three documents**, zero broken; `git diff --check` passed. Explicit hooks covered nine files including the new review and both SQL artifacts; all applicable hooks passed. YAML/TOML had no applicable files in that selection and passed in full CI. No database test was skipped. |
| File preservation | **90 baseline files** checked; exactly seven authorized edits and one new review, no missing files. Protected history and ML notes are byte-identical. |

Reproduction after provisioning a new disposable database and discovering its port:

```bash
export DATABASE_URL='postgresql+psycopg://helios:helios@127.0.0.1:32769/helios_provider_review_final_test'
HELIOS_STRICT_DB_TESTS=1 make ci
uv run alembic check
uv run alembic current
uv run alembic heads
uv run alembic upgrade 91f4c2a7d6e8:b72e6a90c431 --sql
uv run alembic downgrade b72e6a90c431:91f4c2a7d6e8 --sql
```

The earlier preparation run's reused-database failure remains recorded there;
no assertion was weakened. This review also uses fresh databases for each full
CI run. SQL artifacts were reviewed as concrete statements and executed only
on seeded disposable test data. The container was stopped and removed after verification;
temporary databases, scripts and logs are not prerequisites for another session.

All **90** starting tracked/untracked non-ignored files were hashed before edits.
Only seven existing files intentionally change: the draft provider migration,
upgrade SQL, Identity contract documentation, two provider test files, README
and ROADMAP. This review is one new file. The downgrade artifact, provider gate/
preparation records, readiness reassessment, reconciliation, design/acceptance
documents, verification hardening, all earlier migrations, models, matching
commands, dependencies and CI/deployment settings are preserved. ML notes retain
SHA-256 `ac509f8b5db62599fb71db3a8b4681cbde5ba59c51b3240c2cc1eeeb4189db1c`.
No branch switch, reset, clean, discard, commit, push, merge or deployment occurred.

## Limits, next unit, and Step 5 estimate

Technical review does not supply Fortune's owner acceptance. No application
database, deployment, application-image build/smoke, load behavior or future Menu
invariant is accepted by these checks. Bronze readers do not prove semantic
source truth. Arbitrary pre-acquired locks can still deadlock; callers own full
rollback/retry. No mixed Bronze/resolve/Menu orchestration is supported.

Accepted Menu semantics are unchanged: immutable complete aggregates; direct
factual Evidence with explicit structural/inherited support; inherit/full
replacement/suppression; ordinary supersession preserving pins; withdrawal
tombstones and explicit restoration/rebasing; accepted-claim history and K/O/E
cutoffs; revisions surviving remaps; stable correspondence; applicability after
ancestor intersection; USD, exact contexts and individual modifiers. Organization
and sibling prices never supply a missing local price.

**One next work unit:** owner disposition of this corrected provider implementation
and both concrete SQL artifacts. Completion means an explicit owner decision is
recorded against the reviewed artifacts, with any requested provider-only fixes
verified, and a separate bounded Menu implementation handoff prepared if accepted.
No design reapproval, automatic acceptance, Menu implementation, commit, push,
merge or application-data execution is part of that disposition unit.

**Step 5 estimate:** most product implementation remains. After provider acceptance,
budget roughly **three substantial engineering/review units**: (1) the nine-table
Menu schema, single Menu migration, admission/immutable aggregate and lifecycle
writer; (2) replay and pure current/history selection with the documented examples;
(3) integrated M01–M14 concurrency, migration/preservation, strict acceptance and
owner SQL review. This is a scope estimate, not a duration promise; boundaries
may split further for review. Gold/Step 6, extraction, ML and APIs are excluded.

Use configured `gpt-6-astra`, high reasoning, Default/implementation mode, one
agent, concise/low verbosity. `.codex/config.toml` confirms those preferences and
disabled agents; it was not changed and no runtime model switch is claimed.
Continue this chat for provider fixes. Prefer a **new session for the distinct
owner-disposition/next-unit handoff**, using the repository records below;
never depend on access to this conversation.

## Copyable next-work prompt

```text
Complete Helios Plan 0002 Step 5's provider owner-disposition and next-unit
handoff. Use configured gpt-6-astra, high reasoning, Default/implementation
mode, one agent, concise reporting. Complete authorized work and verification;
do not stop at a plan. Never rely on prior chat access.

Verify branch Plan-0002-Step-5 and actual HEAD; report mismatch before switching.
Preserve all tracked modifications and untracked files, especially verification
hardening, provider fixes/tests/SQL/review records, Menu design documents,
readiness reassessment and docs/HumanDevNotes/MLDataExtractionPlan.md.
Do not reset, clean, discard, commit, push, merge or deploy.

Read CLAUDE.md, README.md, CONTRIBUTING.md, relevant ROADMAP.md sections,
docs/adr/0004-modular-monolith-identity-and-lifecycle.md,
docs/adr/0005-immutable-menu-snapshots-and-selection.md,
docs/plans/0002-identity-foundation-before-menu.md,
docs/plans/0002-step-5-menu-schema-proposal.md,
docs/reviews/0002-step-5-readiness-reassessment.md,
docs/reviews/0002-step-5-menu-design-reconciliation.md,
docs/reviews/0002-step-5-provider-prerequisite-gates.md,
docs/reviews/0002-step-5-provider-prerequisite.md,
docs/reviews/0002-step-5-provider-review.md, both concrete SQL files under
docs/reviews/sql/0002-step-5-provider-{upgrade,downgrade}.sql, provider contracts,
b72e6a90c431 and focused tests. Treat dated earlier gate failures as history.

Fortune accepted ADR-0005 and its reconciled proposal on 2026-09-17; never
request that design approval again. Provider implementation and concrete SQL
still need a separate explicit owner disposition. The latest review documents
the stale Repeatable Read/Serializable resolution defect, its projection-lock
fix, 278 passing strict CI tests with zero failures/skips (53 concurrency and
three seeded round trips), no drift, SQL hashes and preservation. Do not invent
acceptance. If no explicit owner decision is supplied, present the exact
reviewed artifacts for that decision; no Menu implementation is authorized.

Record any supplied owner decision faithfully. Resolve only authorized
provider findings: Bronze immutable lookups/canonical keys and Identity batch
scope admission, dependency/lock ordering, pending lineage/shared feature
policy, with one provider function revision after 91f4c2a7d6e8. Preserve
promotion from provisional, exact eligible/current committed event mapping,
readiness/matching policy and the committed-Bronze-input boundary. Bronze
readers certify neither commit status nor semantic truth. Never edit applied
historical migrations or acceptance records; the provider revision is still
a review draft despite being tracked. Synchronize SQL for authorized fixes.

For required verification use /snap/docker/current/bin/docker with sandbox
escalation, imresamu/postgis:16-3.4 and a fresh disposable *_test database.
Never assume old containers/databases/scripts remain; do not change Docker
permissions or deployment settings. Strict make ci must have zero failures/
skips; run drift and seeded provider data/object preservation through upgrade,
downgrade/re-upgrade, including both concrete SQL artifacts. Check Python/SQL
parity, both lineage orderings, forced deferred checks and whole-transaction
40001/40P01 retry. Record precise access limits if blocked; skips are not
acceptance. Application-data SQL execution is not authorized.

Preserve immutable Menu snapshots, direct factual/structural/inherited support,
inherit/full replacement/suppression, pins surviving ordinary supersession,
withdrawal tombstones and explicit restoration/rebasing, accepted-claim history
with K/O/E cutoffs, revision uniqueness across remaps, stable correspondence,
applicability after ancestor intersection, USD, exact contexts, individual
modifiers and committed Bronze input. Never infer local prices from Organization
or sibling prices. No Menu implementation, matching-policy changes, Gold, APIs,
extraction, ML, fuzzy matching, Step 6, dependencies or deployment changes.

Stop at the provider acceptance boundary. If accepted, prepare the bounded
Menu implementation handoff for separate authorization rather than starting it.
End with (1) changes and reasons; (2) exact verification counts and limits;
(3) one next work unit and completion criteria; (4) recommended model, reasoning,
mode, agent count and verbosity; (5) explicit same-chat/new-session recommendation
and reason; (6) a self-contained copyable next-work prompt retaining this same
completion-and-handoff requirement; and an updated estimate of Step 5 work left.
Continue the same chat for fixes within a unit; prefer a new session at a
distinct completed boundary. Never rely on prior chat access.
```
