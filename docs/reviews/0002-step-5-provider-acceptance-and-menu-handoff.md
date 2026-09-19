# Step 5 provider acceptance and bounded Menu handoff

**Date:** 2026-09-18. **Owner:** Fortune. **Branch:** `Plan-0002-Step-5`.
**Reviewed HEAD:** `de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b`.
**Disposition:** Corrected provider implementation and both concrete SQL
directions **accepted**. Provider owner-disposition and handoff unit complete.
Menu implementation remains a separately authorized next unit.

## Owner decision and exact scope

Fortune replied to the explicit request to accept the corrected provider
implementation and both linked SQL artifacts:

> All looks good on the implementation guide, All proposals approved

This records acceptance of all three items presented in the
[owner-disposition packet](0002-step-5-provider-owner-disposition.md): the
corrected provider implementation, concrete upgrade SQL and concrete downgrade
SQL. No correction or condition was requested. ADR-0005 and its reconciled
proposal were already accepted on 2026-09-17; that design acceptance stands.

The prior task explicitly stops at provider acceptance and requests a bounded
Menu handoff for separate authorization. This approval closes that provider
gate; it does not start Menu implementation, authorize application-data SQL,
or approve unseen Menu migration SQL. No additional provider approval is needed
for the unchanged artifacts below. Future changes require review of their own
scope rather than rewriting this decision.

All five SHA-256 values were rechecked against the packet before recording
acceptance. Branch and HEAD still match; code, tests and SQL are unchanged from
the strict CI run.

| Accepted artifact | SHA-256 |
|---|---|
| [Bronze contracts](../../packages/helios_core/provenance/contracts.py) | `d2f378aab604e05cff10a37d730e655ce90991f9e4441511e067e9d0583a1218` |
| [Identity contracts](../../packages/helios_core/identity/contracts.py) | `12c2af73ac9c057697cf3e159a971e80c9fe84f5891f5e911153f1c7d66fac12` |
| [Provider revision b72e6a90c431](../../alembic/versions/b72e6a90c431_add_provider_scope_contracts.py) | `9295c9ed906ee47fd7bbe3c5ad565ee3a575d0f24a78002b857b79cc494dc1b8` |
| [Concrete upgrade SQL](sql/0002-step-5-provider-upgrade.sql) | `1ec770dc0ef22bf936515ab14a54af24f902f3cc36c79271172c35cc9297a7be` |
| [Concrete downgrade SQL](sql/0002-step-5-provider-downgrade.sql) | `f37fa34c11c1ac07e1e54d5c12648cb60412df6f21617c5d9dc7e8c40747e1cd` |

The [technical review](0002-step-5-provider-review.md) explains the corrected
stale Repeatable Read/Serializable admission and twelve regressions. Its
projection locks, unchanged feature policy, promotion from provisional, exact
current committed resolution-event admission, and whole-transaction
`40001`/`40P01` rollback/retry remain part of the accepted implementation.
Bronze readers certify neither commit status nor semantic truth; downstream
consumers must retain already committed Bronze input.

## Verification and preservation

The completed strict CI run immediately preceding this approval remains the
verification evidence for these unchanged artifacts; no new database test run
is claimed for this documentation-only acceptance record.

| Check | Evidence |
|---|---|
| Strict `make ci` | **278 passed, 0 failed, 0 errors, 0 skipped**, **81.97s**, exit 0; all hooks, mypy (**44 source files**) and lockfile check passed; reported coverage **98%**. |
| Included concurrency | **53 passed**: 14 foundation + 39 provider; both race orders, stronger-isolation regressions and whole-transaction retry. |
| Included provider contracts | **56 passed**, including policy parity, pending lineage, provisional promotion, forced deferred checks and real commits. |
| Included seeded migration round trips | **3 passed**: legacy reset, provider Alembic and checked-in concrete SQL. Provider paths preserve all **21 provider tables** and the complete compared object/sequence inventory. |
| Included SQL synchronization | **1 test passed** comparing both artifacts with fresh offline generation, terminal whitespace normalized. |
| Drift and head | **No new upgrade operations detected**; current revision and sole head both **b72e6a90c431**. |
| Approval binding | **5 artifact hashes matched** the exact review packet. |
| Acceptance/handoff documentation checks | **91 local links**, including **31 heading fragments**, across this record, README and ROADMAP; zero broken targets. Applicable explicit hooks passed on all three files, including the new untracked record; `git diff --check` passed. Non-Markdown hooks had no applicable files. |
| File preservation | **92 baseline files** checked: **90 byte-identical**, only README/ROADMAP updated, **0 missing**, and this record is the only newly added file in this approval unit. The pre-existing untracked packet is unchanged. |

Counts overlap the 278 total. The run used `/snap/docker/current/bin/docker`
with sandbox escalation, `imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`,
PostgreSQL **16.4** / PostGIS **3.4.3**, and fresh disposable
`helios_provider_owner_test` data. The container/database were removed; future
verification must provision fresh data. The transient approval-review usage-limit
rejection of drift checking was resolved before the prior handoff.

This unit adds this decision/handoff record and updates current README/ROADMAP
status. The existing README edits and untracked owner-disposition packet were
retained. Earlier records, including their pending-acceptance statements and
prompts, remain unchanged as history; this dated decision supplies the current
disposition. No provider, SQL, test, dependency, configuration, design, applied
migration or ML-note changes are made. No branch switch, reset, clean, discard,
commit, push, merge or deployment occurs.

No Menu behavior, application-image build/smoke, application-data execution,
deployment, load/scalability or semantic source-truth claim is established by
provider acceptance. The existing suite does not test future Menu tables.

## One next unit: Menu persistence, admission and lifecycle writer

**Authorization boundary:** this is a concrete handoff, not an instruction to
start implementation in the provider-disposition unit. The owner can authorize
the bounded unit with the prompt below. Do not ask again for the settled design
or provider acceptance.

Use [ADR-0004](../adr/0004-modular-monolith-identity-and-lifecycle.md),
[ADR-0005](../adr/0005-immutable-menu-snapshots-and-selection.md),
[Plan 0002 Step 5](../plans/0002-identity-foundation-before-menu.md#step-5---featdb-add-menu-graph-against-identity-contracts),
the [reconciled specification](../plans/0002-step-5-menu-schema-proposal.md),
and the [example matrix](0002-step-5-menu-design-reconciliation.md#input-and-selection-examples).
The specification's older provider-parent notation names the prior provider
boundary: the new Menu revision must follow **b72e6a90c431**. Historical gate
failures and prompts do not reopen completed gates.

Deliver a reviewable persistence increment:

1. Create `packages.helios_core.domains.menu`, its typed contracts/commands/models,
   and exactly one forward Menu migration after the accepted provider revision.
   Create the `menu` schema with its nine tables: `currency`, `menu_page`,
   `menu_section`, `menu_item`, `menu_variant`, `menu_modifier`,
   `menu_applicability`, `price_observation`, `evidence_link`. Seed USD only.
   Add required constraints, indexes, functions and triggers in that revision;
   register ownership/models through the existing owner map and sole registry.
2. Implement complete immutable aggregate insertion and explicit initial,
   observation, correction, withdrawal and restoration successors. Commands
   flush without committing. Enforce direct/inherited/structural support,
   same-page/base-parent integrity, exact integer money, applicability
   intersections, stable typed correspondence and committed predecessors/bases.
   Make exact aggregate replay safe and reject conflicting payload/support;
   do not defer writer integrity or idempotency to the later selection unit.
3. Enforce live Identity and base admission at every inserted member/link,
   separate from deferred immutable integrity. Use the published provider
   contracts and one complete dependency batch before Menu stream locks.
   Earlier complete acceptance followed by ordered remap/retirement remains
   history; subsequent inserts fail. Preserve pin validity through ordinary
   supersession and explicit withdrawal/restoration/rebasing semantics.
4. Supply focused Python/raw-SQL tests, including forced deferred checks, real
   commits, both race orderings, conflict/retry rollback and seeded provider
   preservation. Cover all persistence/admission obligations in M01–M11 and
   relevant M12–M14 obligations now; map each covered or deferred obligation
   explicitly. Defer pure current/history selection and ranking to the next
   unit, not the storage invariants that make them possible.
5. Supply synchronized concrete Menu upgrade/downgrade SQL and a durable review
   record. Downgrade removes only Menu-owned objects in dependency order without
   CASCADE; it deletes Menu history and does not promise recovery. Re-upgrade
   recreates empty Menu plus USD. Provider rows, functions and objects must
   survive unchanged. Execute only on disposable test data.

**Completion criteria:** the bounded writer/schema exists with its required
integrity and concurrency tests passing; strict `make ci` has zero failures or
skips on fresh CI-image data; drift is clean; actual SQL round trips and provider
preservation pass; import/FK ownership checks pass; exact counts, remaining
selection work and concrete SQL are presented for separate owner review.
Stop there. Menu SQL acceptance must not be inferred from the accepted design
or provider SQL. No pure selector, Gold, API, extraction, ML, fuzzy matching,
Step 6, new dependency, deployment or application-data execution belongs here.

Retain the full accepted Menu contract even where behavior is implemented in a
later unit: immutable snapshots; direct factual Evidence with structural/inherited
support; inherit/full replacement/suppression; pins through ordinary supersession;
withdrawal tombstones and explicit restoration/rebasing; accepted-claim history
with knowledge/observation/effective cutoffs K/O/E; stream/version revisions
surviving remaps; stable correspondence; applicability after ancestor intersection;
USD, exact contexts and individual modifiers. Never infer local prices from
Organization or sibling prices. Mixed persist/resolve/Menu ingestion stays
unsupported; readers are not commit certificates or semantic validators.

## Remaining work and session recommendation

Provider preparation, technical review, verification, owner acceptance and this
handoff are complete. Step 5 still needs roughly **three substantial Menu
engineering/review units**: (1) the bounded persistence/writer unit above;
(2) extended replay scenarios and pure current/accepted-history selection,
including the documented price/scope/time/Evidence examples; (3) integrated
M01–M14 acceptance, remaining concurrency/preservation coverage and owner review
of the final SQL. Relevant checks accompany every unit; integration is not a
reason to postpone correctness tests. Most product implementation remains.
This is a scope estimate, not a duration promise; boundaries may split further.

Recommend **gpt-6-astra, high reasoning, Default/implementation mode, one agent,
concise/low verbosity**. The local configuration is unchanged; no runtime model
switch is claimed. Prefer a **new session for the separately authorized Menu
unit** because provider acceptance is now a completed boundary. Continue this
chat for corrections to this acceptance/handoff only. Every continuation must
use repository records and a self-contained prompt, never prior-chat access.

## Copyable next prompt for separate implementation authorization

Sending the following prompt authorizes only the bounded Menu unit it names:

```text
Implement Helios Plan 0002 Step 5's bounded Menu persistence, admission and
lifecycle-writer unit for review. This prompt authorizes its Menu models,
contracts, commands, one new migration after b72e6a90c431, concrete SQL and tests
on disposable data only. Use configured gpt-6-astra, high reasoning,
Default/implementation mode, one agent, concise reporting. Complete authorized
work and verification; do not stop at a plan or rely on prior chat access.

Verify branch Plan-0002-Step-5 and actual HEAD; report mismatch before switching.
The provider acceptance reviewed de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b.
Preserve all tracked modifications and untracked files, including provider
fixes/tests/SQL, verification hardening, Menu designs, historical reviews,
acceptance/handoff records, readiness reassessment and
docs/HumanDevNotes/MLDataExtractionPlan.md. No reset, clean, discard, commit,
push, merge or deployment; no rewriting applied migrations or acceptance history.

Read CLAUDE.md, README.md, CONTRIBUTING.md, relevant ROADMAP.md sections,
docs/reviews/0002-step-5-provider-acceptance-and-menu-handoff.md,
docs/reviews/0002-step-5-provider-owner-disposition.md,
docs/reviews/0002-step-5-provider-review.md and its full handoff references,
docs/adr/0004-modular-monolith-identity-and-lifecycle.md,
docs/adr/0005-immutable-menu-snapshots-and-selection.md,
docs/plans/0002-identity-foundation-before-menu.md,
docs/plans/0002-step-5-menu-schema-proposal.md,
docs/reviews/0002-step-5-readiness-reassessment.md and
docs/reviews/0002-step-5-menu-design-reconciliation.md. Read provider contracts,
the accepted migration, both provider SQL artifacts and focused tests.

Fortune accepted ADR-0005 and its reconciled proposal on 2026-09-17, and the
corrected provider implementation and both SQL directions on 2026-09-18:
“All looks good on the implementation guide, All proposals approved”. Hashes
and exact scope are recorded in the acceptance/handoff. Do not request those
approvals again. Prior pending/gate records are history. Accepted provider
code and SQL stay unchanged; newly demonstrated provider defects need a
separately scoped correction, not a silent rewrite of accepted artifacts.

Latest strict provider CI: 278 passed, zero failures/errors/skips, including
53 concurrency tests, 56 provider contracts, three seeded migration round trips
including concrete SQL, SQL-generation equality, and no drift at b72e6a90c431.
Counts overlap. This verifies providers, not future Menu. Containers/data were
removed; never assume old test infrastructure remains.

Implement exactly the nine Menu tables, immutable complete aggregate writer,
explicit stream lifecycle and required support/graph/money/context/revision
integrity described in the bounded handoff. Include safe exact aggregate replay
and conflicting-payload rejection. Commands never commit. Keep live per-insert
admission separate from deferred immutable integrity. Use one complete provider
batch before Menu locks; test pending lineage and both scope-change orderings.
Defer the pure current/history selector and ranking to a later unit.

Preserve matching/readiness policy, provisional promotion, exact current
committed-event admission and committed Bronze input. Readers certify neither
commit status nor semantic truth. Preserve immutable Menu snapshots, direct
factual/structural/inherited support, inherit/full replacement/suppression,
pins through ordinary supersession, tombstones and explicit restoration/rebasing,
accepted-claim history with K/O/E cutoffs, revisions across remaps, stable
correspondence, applicability after ancestor intersection, USD, exact contexts
and individual modifiers. Never infer local prices from Organization or sibling
prices. No mixed persist/resolve/Menu orchestration.

Use /snap/docker/current/bin/docker with sandbox escalation,
imresamu/postgis:16-3.4 and fresh disposable *_test data. Run strict make ci,
drift, focused raw-SQL/Python integrity, forced deferred checks, real commits,
both race orders and whole-transaction 40001/40P01 retry. Execute seeded Menu
and provider-preservation upgrade/downgrade/re-upgrade checks, including actual
concrete SQL files, with SQL synchronized. Skips never establish acceptance.
Never weaken existing preservation tests. No Docker permission or deployment
changes, application-data SQL or new dependencies. Remove task-owned test data.

No Gold, APIs, extraction, ML, fuzzy matching, matching-policy changes, Step 6
or deployment. Preserve historical migrations and decisions. Stop with the
bounded Menu increment and concrete SQL ready for owner review; do not infer
acceptance of unseen Menu SQL or start the next unit automatically.

Record decisions, results and unresolved work in the repository. End with
(1) changes and reasons; (2) exact verification counts and limits; (3) one next
unit and completion criteria; (4) model/reasoning/mode/agent-count/verbosity
recommendation; (5) explicit same-chat/new-session recommendation and reason;
(6) a self-contained copyable next prompt preserving these same completion-and-
handoff requirements; and an updated Step 5 remaining-work estimate. Continue
the same chat for fixes within a unit; prefer a new session at a distinct
completed boundary. Never rely on prior chat access.
```
