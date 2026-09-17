# Step 5 readiness reassessment

**Date:** 2026-09-17
**Scope:** Current foundation, technical debt, and the next product checkpoint.
**Branch assessed:** `Plan-0002-Step-5`, code baseline `aafe110`.
**Decision context:** Fortune accepted the preceding technical review's
recommended defaults and delegated routine technical judgment, while retaining
ownership of product goals. This document records that direction and the
recommended execution sequence; it does not approve an unseen schema diff.

## Verification-hardening outcome (2026-09-17)

**Implemented and verified on native PostgreSQL 16.14.** Debt items 1–4 below
are addressed in code/current instructions. The CI PostGIS image remains an
explicit verification limit: Docker daemon access was denied. Menu design
reconciliation can proceed; carry the outstanding image validation into the
pre-implementation gate. No Menu implementation is authorized by this result.

- `HELIOS_STRICT_DB_TESTS=1` now governs all database entrypoints, including
  readiness, savepoint, real-commit concurrency, and destructive migration
  fixtures. CI sets it. Unreachable/invalid/non-PostgreSQL/non-test targets
  fail; any `HELIOS_ALLOW_NONTEST_DB` setting is rejected. SQLAlchemy parses
  the name, and the fixture checks `current_database()` before migration or
  test writes so query parameters cannot redirect an apparently safe URL.
- Optional local tests still skip without a suitable database. Their explicit
  non-test override remains available only for ordinary tests; migration and
  concurrency tests always require a disposable `*_test` database.
- Alembic doubles percent signs only when writing ConfigParser configuration.
  Both online/offline reads preserve the original encoded URL and driver
  connection arguments. Real migrations succeeded with an encoded socket URL.
- One static checker covers ordinary/from/relative imports, aliases, parent
  imports, package initializers, and nested modules. Positive/negative examples
  preserve provider contracts and the exact model-registry exception. Active
  DB/Provenance/Identity and parser boundaries are checked. Dynamic imports
  and arbitrary attribute access are outside this deliberately small check;
  Menu consumer checks must be added when Menu exists.
- CODEOWNERS and current agent/contributor instructions cover module-level
  `models.py` and model directories. Current test/deployment wording is fixed;
  historical ADRs, applied migrations, and acceptance records are unchanged.

### Verification record

The workspace started clean on `Plan-0002-Step-5` at `96fec0d`. The ML notes and existing
reassessment were tracked at this point. No branch switch, reset, cleanup of
existing work, commit, push, merge, or deployment occurred. The ML notes remain
byte-identical (SHA-256
`ac509f8b5db62599fb71db3a8b4681cbde5ba59c51b3240c2cc1eeeb4189db1c`).

A fresh cluster used `/tmp/helios-hardening.M0ITfq`, PostgreSQL user `helios`,
loopback port `55439`, and its private socket directory. No previous-session
cluster/script was assumed. Initial `initdb --no-locale` selected SQL-ASCII;
the first strict full run correctly failed (**89 passed, 88 setup errors,
zero skipped**). Only this new empty test database was recreated using
`createdb --template=template0 --encoding=UTF8 helios_test`; the repeated run
then passed without weakening checks. Use explicit UTF-8 when reproducing.

Final acceptance commands (against that disposable database):

```bash
export DATABASE_URL='postgresql+psycopg://helios@/helios_test?host=%2Ftmp%2Fhelios-hardening.M0ITfq%2Fsocket&port=55439'
HELIOS_STRICT_DB_TESTS=1 make ci
uv run alembic check
```

| Verification | Result |
|---|---|
| Strict `make ci` | **180 passed, 0 failed, 0 skipped** in 24.91s; lint/hooks, mypy (39 files), and lockfile check passed |
| Existing migration/concurrency coverage within that full run | Seeded downgrade/upgrade/re-upgrade: **1 passed**; real-connection concurrency: **14 passed**; no failures/skips |
| `uv run alembic check` with the same encoded URL | Exit 0: **No new upgrade operations detected** |
| `uv run pytest -q test/test_schema_layout.py test/test_import_boundaries.py test/test_database_mode.py` during development | **81 passed**, 0 failed/skipped; the final full suite additionally includes three registry-exception cases |
| `uv run ruff check test alembic/env.py`, format check, and mypy | Passed; explicit lint included new untracked test files that pre-commit's tracked-file scan does not include |
| Strict-mode subprocess regressions | All four DB entrypoints return exit 1 / **4 setup errors, 0 skips** for unreachable, non-test, non-PostgreSQL, malformed URLs, and override values `1`/`0` |
| Optional-mode subprocess regressions | Deliberately assert **4 skips** for absent/non-test databases; these test optional-mode behavior and are **not database acceptance evidence** |
| Docker availability | `docker info --format '{{.ServerVersion}}'` and `/snap/docker/current/bin/docker info --format '{{.ServerVersion}}'`: permission denied on `/var/run/docker.sock`; `sudo -n docker info ...`: password required |

Docker image `imresamu/postgis:16-3.4`, application image build/smoke, deployment,
load behavior, and future Menu invariants were **not verified**. No container
was started and no Docker permission/configuration was changed. The isolated
native cluster is stopped after verification; future work must provision its
own disposable database. Temporary logs are diagnostic only; this repository
content is the durable command/result record (the work itself remains uncommitted).

### Next work unit and continuing handoff

**Next: reconcile the Menu design and decision record, documentation only.**
Completion means one internally consistent specification reflecting the accepted
defaults, explicit provider ownership and admission/history/current-selection
rules, concrete input/output examples, and each expensive invariant mapped to
its enforcing constraint/trigger and focused test. Record newly discovered
material tradeoffs instead of silently changing product meaning. Keep schema
implementation and SQL approval separate. PostGIS acceptance remains outstanding.

Use the configured `gpt-6-astra`, high reasoning, Default/implementation mode,
one agent, concise reporting. The local config already specifies that model,
reasoning, low verbosity, and disabled agents; it was not changed. Start a new
chat for design reconciliation because this is a distinct completed-work
boundary. Continue this chat for any hardening fixes or verification follow-up.

Copyable next-work prompt:

```text
Reconcile Helios Plan 0002 Step 5's Menu design and architectural decision
record, documentation only. Use configured gpt-6-astra, high reasoning,
Default/implementation mode, one agent, concise reporting. Complete the
repository edits and verification, not just a plan.

Verify branch Plan-0002-Step-5; report any difference before switching.
Preserve all tracked modifications and untracked files, especially the
verification-hardening work, readiness reassessment, and
docs/HumanDevNotes/MLDataExtractionPlan.md. Do not reset, clean, discard,
commit, push, merge, or deploy.

Read CLAUDE.md, README.md, relevant ROADMAP.md sections, CONTRIBUTING.md,
ADR-0004, Plan-0002, docs/reviews/0002-step-5-readiness-reassessment.md,
and docs/plans/0002-step-5-menu-schema-proposal.md. The reassessment contains
accepted defaults and the durable hardening/handoff record. Baseline:
strict native PostgreSQL 16.14 make ci passed 180 tests with zero failures
or skips, including migration/concurrency; encoded socket URL worked and
alembic check found no drift. Docker/PostGIS remains unverified because
Docker socket access was denied. Temporary databases/scripts do not persist
as prerequisites.

Reconcile the proposal and prepare a concrete Menu ADR for review without
rewriting historical acceptance records. Preserve accepted immutable
snapshots, direct factual Evidence plus explicit structural/inherited
support, inherit/full replacement/suppression, pins surviving ordinary
supersession, stream withdrawal tombstones and explicit restoration,
accepted-claim history, USD/exact contexts/individual modifiers, and
already-persisted Bronze input. Never infer a local price from Organization
or sibling-location prices. Do not reopen these defaults.

Resolve the documented details: admission vs deferred integrity checks,
pending lineage, inherited-node shape and parent mapping, base validity,
stream identity and revision uniqueness across remaps, temporal cutoffs,
stable correspondence vs version-local locators, and effective applicability
after ancestor intersection. Keep dependency expansion, lock ordering, and
eligibility policy in Identity; immutable provenance lookups in Bronze.
Map expensive invariants to enforcing constraints/triggers and focused tests.
Show selected value, scope, observation time, and Evidence path in examples
for sibling prices, unknown local price, local-price-only inheritance,
replay, later observation, correction, withdrawal, restoration, and
remap/retirement with preserved history.

No models, contracts, migrations, Identity matching-policy changes, Menu
implementation, Gold, APIs, extraction, ML, fuzzy matching, Step 6, runtime
dependencies, or deployment changes. Own routine decisions; ask only about
missing information or newly discovered material tradeoffs. Verify document
consistency/links and run required checks; skipped database tests never count
as acceptance. Carry forward the outstanding CI PostGIS image validation.
Stop after the reconciled design and reviewable ADR; do not start implementation.

Before handoff, record decisions, results, and unresolved work in the repo.
End with (1) what changed and why in plain language; (2) verification counts
and limits; (3) one next work unit and completion criteria; (4) recommended
model/reasoning/mode/agent count/verbosity; (5) explicitly recommend same chat
or new session with a reason; (6) a self-contained copyable next-work prompt.
That prompt must preserve this same completion-and-handoff requirement.
Continue the same chat for fixes within a work unit; prefer a new session at
a distinct completed-work boundary. Never rely on prior conversation access.
```

## Recommendation in product terms

Keep the existing modular monolith and PostgreSQL foundation. With verification
hardening implemented and native validation recorded above, reconcile the Menu
design, then demonstrate a real menu history before expanding collection. A broad rewrite or speculative
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

## Debt identified before hardening

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

1. **Harden foundation verification.** Items 1–4 are implemented and native
   validation passed as recorded above. CI PostGIS image validation remains
   outstanding until Docker is accessible; it is not implied by native success.
   Require full execution, clean migration round trips, and no metadata drift
   for that image before treating its database behavior as accepted.
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
