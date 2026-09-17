# Step 5 readiness reassessment

**Date:** 2026-09-17
**Scope:** Current foundation, technical debt, and the next product checkpoint.
**Branch assessed:** `Plan-0002-Step-5`, code baseline `aafe110`.
**Decision context:** Fortune accepted the preceding technical review's
recommended defaults and delegated routine technical judgment, while retaining
ownership of product goals. This document records that direction and the
recommended execution sequence; it does not approve an unseen schema diff.

## Recommendation in product terms

Keep the existing modular monolith and PostgreSQL foundation. Complete a small
verification-hardening change, reconcile the Menu design, then demonstrate a
real menu history before expanding collection. A broad rewrite or speculative
scaling project is not justified by the evidence collected here.

The product goal remains 300+ Austin/Round Rock establishments with observed,
traceable prices, with at least 80% observed within 45 days. The immediate
checkpoint is smaller: demonstrate that a price belongs to the right location,
can be traced to its source, can be replayed without duplication, and can be
corrected without losing history. Infrastructure completion alone does not
establish that product behavior.

## What exists and what was verified

- Bronze has six provenance tables and a replay-safe observation command.
- Identity has fifteen tables, typed identity grains, append-only decisions,
  internal current-state projections, deterministic resolution, and readiness
  guards. Its migration head is `91f4c2a7d6e8`.
- The API exposes `/healthz` and `/readyz` only. Menu, Gold, discovery ingestion,
  extraction, and a price-index API are not implemented.
- A fresh, isolated PostgreSQL 16 cluster passed `make ci`: **121 passed,
  zero skipped**. The existing migration downgrade/re-upgrade and concurrency
  tests ran. `alembic check` reported no new upgrade operations.
- The cluster used temporary storage and a separate loopback port, and was
  stopped after validation. Application data and deployment config were not
  changed. This was native PostgreSQL, not a Docker/PostGIS image validation,
  deployment test, load test, or proof of future Menu invariants.
- The earlier 34-passed/87-skipped result remains an accurate record of the
  earlier local run, but no longer describes the extent of foundation testing.

The first isolated attempt used a percent-encoded Unix-socket URL and failed
before migrations: `alembic/env.py:16` passes the URL into ConfigParser without
escaping literal percent signs. The repeated setup failures had one shared
cause; they were not 87 independent schema defects. Switching the temporary
test connection to TCP allowed all existing tests to run without code changes.

## Debt worth paying before Menu

| Order | Evidence | Action and exit condition |
|---|---|---|
| 1 | `test/conftest.py`, `test/test_identity_concurrency.py`, and `test/test_legacy_identity_reset.py` skip when the database cannot be reached. CI provisions Postgres but does not require these tests to execute. | Add an explicit strict database-test mode shared by those fixtures and CI. In that mode, unavailable or non-disposable databases fail immediately; never permit the non-test override. Prove an unreachable database fails and the disposable full suite passes without database skips. |
| 2 | `alembic/env.py:16` rejected a valid percent-encoded connection URL during this assessment. | Correct Alembic configuration escaping, preserving the exact URL received by the database driver. Add a focused regression and verify migrations with an encoded socket URL. No schema revision is needed. |
| 3 | Import checks in `test/test_schema_layout.py` mostly inspect absolute `ImportFrom` nodes. `.github/CODEOWNERS` names the old `packages/**/db/models/` layout. | Cover ordinary and relative imports with small failing fixtures; align model review markers and working instructions with the current module model paths. Preserve the registry exception and provider-contract boundaries. |
| 4 | README described the removed Venue stub; the roadmap called implemented foundations pending and staging completed. | Correct present-tense status and test instructions. The current docs change handles the principal status errors; make the remaining checklist/path corrections with the hardening change. Preserve historical ADRs as historical records. |
| 5 | Step 5's original text conflicts with the reviewed defaults and mixes admission, current selection, and history. | Reconcile the proposal and record the accepted architectural choices before implementing Menu. Use the examples below as the review surface. |

Keep the hardening work small: test execution, URL handling, boundary checks,
and their documentation. Do not refactor the entire Identity module, rewrite
applied migrations, redesign resolution, or add runtime dependencies merely
to tidy the code. Address any newly demonstrated correctness defect before
Menu relies on it, with a focused regression and a separate forward migration
if a database change is actually necessary.

## Accepted review defaults and remaining technical work

Fortune accepted these defaults in the current discussion. They should not be
reopened as repeated approval questions merely because their implementation
requires routine technical choices.

| Accepted direction | Meaning for the product |
|---|---|
| Immutable snapshots; direct factual Evidence with explicit structural/inherited support | Preserve what was accepted and its source. Synthetic grouping and inherited references do not pretend to be new source assertions. |
| Explicit `inherit`, full replacement, and suppression | A local source can change only a price without falsely claiming that it supplied the chain's description or nutrition facts. |
| Ordinary supersession preserves existing pins | A new chain menu does not silently change an already interpreted local menu. Withdrawal or invalid scope blocks inherited current content. |
| Withdrawal is a stream tombstone; restoration is explicit | Withdrawing the latest interpretation must not accidentally reveal an older price as current. |
| Accepted-claim history; historical Identity-state reconstruction deferred | Old observations remain explainable without promising to reconstruct every past readiness or operating-state edit. |
| USD initially, exact contexts, individual modifiers, already-persisted Bronze input | Finish the required product behavior without currency conversion, recurring schedules, choice groups, or mixed ingest orchestration in Step 5. |

Retain Organization/local separation: a shared price is not a verified price
at every location. There is no sibling-location price fallback.

Before implementation, close the technical details identified in the review:

1. Put live scope/eligibility checks at admission, including pending lineage;
   reserve deferred checks for immutable correspondence and aggregate integrity.
2. Define the inherited-node shape, support rules, parent mapping, and behavior
   when a base is superseded, withdrawn, or no longer mapped to its scope.
3. Define stream identity, correction revision uniqueness across remaps,
   withdrawal/restoration, and observation/acceptance/effective-time cutoffs.
4. Define correspondence using stable native IDs or explicit links; keep
   positional fallback locators version-local. Rank effective applicability
   after ancestor intersection.
5. Keep dependency expansion, batch lock ordering, and eligibility policy in
   Identity. Keep immutable provenance lookups in Bronze. A promotion predicate
   must still allow a provisional Subject to become eligible; it cannot simply
   call a guard that already requires eligibility.

Use the existing narrow provider revision followed by one Menu revision;
no additional framework, shared offering model, or Gold implementation is
needed. The reconciled specification and ADR should record the accepted
defaults faithfully. Escalate only a newly discovered material tradeoff;
the concrete schema and generated SQL still receive their existing review.

## Smallest sequence and exit gates

1. **Harden foundation verification.** Finish debt items 1–4, using the actual
   CI PostGIS image for acceptance as well as the available native Postgres
   test path. Require full database execution, clean migration round trips,
   and no Alembic metadata drift. Publish the command and results.
2. **Finish the Menu decision record.** Reconcile the existing proposal and
   architectural record using the accepted defaults. Supply a small set of
   human-readable input/output examples, with each expensive invariant mapped
   to its enforcing constraint/trigger and focused test. Avoid another general
   architecture redesign.
3. **Implement only Plan 0002 Step 5.** Provider contracts/guards first, then
   Menu persistence, replay, correction, and pure precedence. Prove both race
   orderings against remap, retirement, and readiness edits on real connections.
   Show upgrade/downgrade SQL and provider-data preservation. No extraction,
   Gold, API, fuzzy matching, or training work belongs in this step.
4. **Demonstrate the product incrementally.** First use curated fixtures for
   an independent restaurant and two locations sharing an Organization menu.
   Exercise persistence and a readable inspection of the selected facts.
   Then follow Plan 0001's unaffected discovery, capture/replay, and extraction
   sequence; add Gold/read APIs at their separate gates. Aim for a small
   verified real-source sample before broadening to the 300-location milestone.

The Step 5 examples must show: different prices at sibling locations; an
unknown local price without shared-price fallback; inherited content with a
local price only; exact replay; a later observation; a correction; withdrawal
without resurrection; restoration; and source remap/retirement with preserved
history. Show the selected value, scope, observation time, and Evidence path.

## Maintaining understanding and controlling drift

For each change, the agent supplies a short explanation: the user-visible
problem, an example before/after, the technical choice and cost, the evidence
that it works, and any remaining limit. Technical appendices support the
explanation; understanding lock syntax is not the owner's acceptance test.

Routine technical decisions remain the agent's responsibility within the
accepted design. Return to the owner when a change affects product meaning,
source policy, recurring cost, deployment commitments, data loss, or another
explicit review gate. Explain the consequence in product terms and recommend
one choice; do not hand over an unexplained menu of technical options.

Keep current status in README, execution order in the plans, and architectural
decisions in ADRs. Update affected current-state documentation with the change
that invalidates it. Do not rewrite old acceptance records to imply knowledge
or verification that did not exist at the time.

Scalability remains unmeasured. After a small real-source sample exists,
measure rows/storage per capture, ingestion time, inspection/query latency,
and replay cost; use that evidence to choose indexes or change snapshot
granularity. Do not add brokers, caches, partitions, or services in advance.

The owner's untracked `docs/HumanDevNotes/MLDataExtractionPlan.md` was read and
left unchanged. Its extraction-dataset/feedback direction remains deferred:
preserve source artifacts during capture design, separate model predictions
from reviewed labels during extraction design, and benchmark before training.
No ML tables or dependencies are needed for this stabilization or Step 5.
