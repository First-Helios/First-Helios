# Step 5 provider owner-disposition packet

**Date:** 2026-09-18. **Branch:** `Plan-0002-Step-5`, verified without switching.
**Reviewed HEAD:** `de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b`; starting tree clean.
**Owner disposition: pending.** No explicit provider acceptance, rejection, or
requested correction was supplied. The subsequent instruction “Resume” continued
verification; it did not supply acceptance. Technical checks are complete, but
the owner-disposition unit remains open until Fortune supplies a decision.

Fortune's 2026-09-17 acceptance of [ADR-0005](../adr/0005-immutable-menu-snapshots-and-selection.md)
and its [reconciled proposal](../plans/0002-step-5-menu-schema-proposal.md) is
settled. It is not requested again. The [technical review](0002-step-5-provider-review.md),
[preparation](0002-step-5-provider-prerequisite.md), [gate history](0002-step-5-provider-prerequisite-gates.md),
[readiness reassessment](0002-step-5-readiness-reassessment.md), and
[design reconciliation](0002-step-5-menu-design-reconciliation.md) remain unchanged.
Their dated failures and prior next-work prompts retain their historical meaning.

## Concrete decision surface

Recommendation: accept the corrected provider implementation and each SQL
direction below, subject to Fortune's explicit decision. This recommendation
does not record acceptance or authorize Menu implementation or application-data
execution. No new provider defect or code correction was identified in this unit.

| Artifact | Behavior being presented for owner disposition |
|---|---|
| [Bronze contracts](../../packages/helios_core/provenance/contracts.py) | Frozen version/Evidence references and canonical business keys; support requires the exact version or its matching non-null Capture. Readers certify neither commit status nor semantic source truth. Consumers retain the committed-Bronze-input boundary. |
| [Identity contracts](../../packages/helios_core/identity/contracts.py) | One complete batch of local/base scope requests; provider-owned dependencies, locks, pending-lineage checks and unchanged readiness policy. Promotion works from provisional; admission requires eligible readiness and the exact current committed resolution event/record mapping. |
| [Provider revision b72e6a90c431](../../alembic/versions/b72e6a90c431_add_provider_scope_contracts.py) | Adds four Bronze and five Identity functions after `91f4c2a7d6e8`. Locks mutable resolution proofs after sorted Source Records so stale Repeatable Read/Serializable admission aborts with `40001`. Whole-transaction rollback/retry remains the caller's responsibility, including `40P01`. |
| [Concrete upgrade SQL](sql/0002-step-5-provider-upgrade.sql) | Creates exactly those nine functions transactionally and advances Alembic. No provider data, existing functions, tables, columns, indexes or triggers are rewritten. |
| [Concrete downgrade SQL](sql/0002-step-5-provider-downgrade.sql) | Drops exactly those nine signatures in dependency order, without CASCADE, and restores the parent revision. Runtime rollback must pair this with the earlier application version because current contracts require the new functions. |

The correction prevents a consumer from accepting an obsolete assignment after
another transaction remaps or unassigns its source record. Already successful
admission followed by an ordered scope change remains valid history; no live
eligibility check is added at the deferred boundary. Closure remains distinct
from retirement. Matching and readiness policy are unchanged.

SHA-256 binds the exact decision surface; verify again if any artifact changes:

| Artifact | SHA-256 |
|---|---|
| Bronze contracts | `d2f378aab604e05cff10a37d730e655ce90991f9e4441511e067e9d0583a1218` |
| Identity contracts | `12c2af73ac9c057697cf3e159a971e80c9fe84f5891f5e911153f1c7d66fac12` |
| Provider revision | `9295c9ed906ee47fd7bbe3c5ad565ee3a575d0f24a78002b857b79cc494dc1b8` |
| Upgrade SQL | `1ec770dc0ef22bf936515ab14a54af24f902f3cc36c79271172c35cc9297a7be` |
| Downgrade SQL | `f37fa34c11c1ac07e1e54d5c12648cb60412df6f21617c5d9dc7e8c40747e1cd` |

Fortune may accept these three review items (implementation, upgrade SQL,
downgrade SQL), request specific provider corrections, or defer/reject any item.
Record the actual decision, its date, scope and artifact hashes in a dated
addendum; do not infer acceptance from silence, green tests, tracking in Git,
design approval, or an instruction to resume. Partial acceptance leaves the
remaining items pending. This explicit owner gate comes from the task request
and the [technical review's completion boundary](0002-step-5-provider-review.md#limits-next-unit-and-step-5-estimate).

## Fresh verification

Docker used `/snap/docker/current/bin/docker` with sandbox escalation, image
`imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`.
The fresh container `helios-provider-owner-20260918` used temporary memory-backed
database storage, PostgreSQL **16.4**, PostGIS **3.4.3**, and only localhost port
`127.0.0.1:32770`. Its fresh database was `helios_provider_owner_test`.
No application volume, Compose environment, Docker permission or deployment
setting was changed. The container and its test data were removed after checks;
an empty `docker ps --all` name-filter result confirmed removal.

| Check | Observed result |
|---|---|
| Strict `make ci` | **278 passed, 0 failed, 0 errors, 0 skipped**, pytest **81.97s**, exit 0. All lint/hygiene hooks, mypy (**44 source files**) and lockfile check passed; reported coverage **98%**. |
| Concurrency/retry included in CI | **53 passed**: 14 foundation and 39 provider. Includes both race orderings, reversed batches, FK compatibility, rebuild conflicts, full `40P01` retry and `40001` rollback/revalidation. The 12 stale-resolution cases cover Python/raw SQL, both stronger isolation levels, and unassign/remap/raw readiness-proof removal. |
| Provider contracts included in CI | **56 passed**, including Python/SQL parity, provisional promotion, exact-event admission, pending lineage/parent/survivor membership, both insertion orders, forced deferred checks and real commits. |
| Seeded migration round trips included in CI | **3 passed**: legacy reset, provider Alembic, and actual checked-in provider SQL. Provider paths preserve every row/column of all **21 provider tables**, existing function definitions, constraints/indexes/triggers, views, sequences and sequence values/`is_called`; parent and re-upgraded inventories compare exactly. |
| Offline SQL synchronization included in CI | **1 passed**, checking both artifacts against fresh offline generation with terminal whitespace normalized. Checked-in SQL hashes also match the prior technical review exactly. |
| Drift and revision | `alembic check`: **No new upgrade operations detected**, exit 0. Database current revision and sole Alembic head both **b72e6a90c431**. |
| Final documentation checks | **31 local links**, including **3 heading fragments**, across README and this packet; zero broken targets. Applicable explicit hooks passed on both files, including this untracked packet; `git diff --check` passed. Hooks for non-Markdown file types had no applicable files; all hooks passed in full CI. |
| Final file preservation | **91 baseline files** checked: **90 byte-identical**, README alone updated, **0 missing**, and this packet is the only new non-ignored file. Branch and HEAD are unchanged. |

Category counts overlap the **278** total; they are not additional test runs.
JUnit recorded zero top-level skips/errors/failures. Tests of optional-mode skip
behavior in child processes are not database acceptance evidence. No additional
full suite was needed after the subsequent documentation-only edits; final
documentation hooks, link and preservation checks are recorded below.

The first escalated drift-check request was rejected by automatic approval
review because of a usage limit, before execution. After the explicit “Resume”
instruction, the read-only check was retried successfully without a workaround
or permission change. Reflection emitted a warning for unmanaged PostGIS
`geometry`; the managed-schema comparison completed with no new operations.
There is no remaining access blocker from that rejection.

Reproduce using a newly provisioned disposable database and its actual port:

```bash
export DATABASE_URL='postgresql+psycopg://helios:helios@127.0.0.1:32770/helios_provider_owner_test'
env -u HELIOS_ALLOW_NONTEST_DB HELIOS_STRICT_DB_TESTS=1 make ci
uv run alembic check
uv run alembic current
uv run alembic heads
```

The displayed port/database describe this completed run, not a still-running
service. Temporary logs, JUnit output, container and scripts are not prerequisites
for resumption. Required migrations and concrete SQL ran only on disposable data.

## Changes, preservation and limits

This new packet and a README pointer make the exact review surface and fresh
verification discoverable without rewriting past acceptance or review records.
No implementation or SQL change was necessary. All **91** initial tracked and
untracked non-ignored files were hashed before work. README is the only intended
edit to those files; provider fixes/tests/SQL, verification hardening, Menu
designs, historical reviews, readiness reassessment, configuration and applied
historical migrations remain byte-identical. The ML notes retain SHA-256
`ac509f8b5db62599fb71db3a8b4681cbde5ba59c51b3240c2cc1eeeb4189db1c`.
No reset, clean, discard, commit, push, merge or deployment occurred.

These checks establish provider behavior on seeded disposable CI-image data.
They do not establish owner acceptance, semantic source truth, production/load
behavior, application-image build/smoke, deployment or any future Menu invariant.
Arbitrary pre-acquired locks may deadlock; callers own complete rollback/retry.
Mixed Bronze-persist/resolve/Menu orchestration remains unsupported.

## One next unit and remaining Step 5 work

**Next unit: finish provider owner disposition against the exact artifacts above.**
Completion requires an explicit owner decision covering the implementation and
each SQL direction, faithfully recorded, with any authorized provider-only
corrections verified and SQL synchronized. If all are accepted, prepare a bounded
Menu implementation handoff for separate authorization and stop; do not implement
Menu in the disposition unit. No Menu implementation handoff is activated here.

**Updated Step 5 estimate:** the technical provider preparation/review and fresh
verification are complete; owner disposition remains open. After acceptance,
roughly **three substantial engineering/review units** remain: nine-table Menu
persistence with one Menu revision, admission/immutable aggregate and lifecycle
writer; replay and pure current/accepted-history selection with the documented
examples; and integrated M01–M14 concurrency, migration/preservation, strict
verification and owner SQL review. Each implementation unit needs its relevant
checks before completion; the integration unit must not postpone essential
integrity tests. Most product implementation remains. These are scope estimates,
not time promises, and may split further. Gold/Step 6, APIs, extraction and ML
are excluded.

Retain immutable complete aggregates; direct factual Evidence plus explicit
structural/inherited support; inherit/full replacement/suppression; pins through
ordinary supersession; withdrawal tombstones and explicit restoration/rebasing;
accepted-claim history with K/O/E cutoffs; revisions surviving remaps; stable
correspondence; applicability after ancestor intersection; USD, exact contexts
and individual modifiers. Organization and sibling prices never supply a
missing local price. Providers own locks/policy; Bronze input remains committed.

Recommendation: configured `gpt-6-astra`, high reasoning, Default/implementation
mode, one agent, concise/low verbosity. Local configuration was verified and
left unchanged; no runtime model switch is claimed. **Continue this chat** for
the pending owner decision and any provider corrections, because this unit is
still open. Prefer a **new session after explicit provider acceptance and its
handoff**, at the distinct Menu boundary, with separate authorization. Always
carry repository records and a self-contained prompt, never prior-chat access.

## Copyable continuation prompt

```text
Finish Helios Plan 0002 Step 5 provider owner disposition and next-unit handoff.
Use configured gpt-6-astra, high reasoning, Default/implementation mode, one
agent, concise reporting. Complete authorized work and verification; do not
stop at a plan or rely on prior chat access.

Owner decision: [paste Fortune's explicit decision verbatim, or leave pending].
Never treat this placeholder or the instruction to continue as acceptance.

Verify branch Plan-0002-Step-5 and actual HEAD; report mismatch before switching.
Reviewed HEAD was de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b. Preserve tracked
modifications and untracked files, especially provider fixes/tests/SQL,
verification hardening, Menu designs, historical reviews, readiness reassessment
and docs/HumanDevNotes/MLDataExtractionPlan.md. Do not reset, clean, discard,
commit, push, merge or deploy; never edit applied historical migrations or
historical acceptance records.

Read CLAUDE.md, README.md, CONTRIBUTING.md, relevant ROADMAP.md sections,
docs/reviews/0002-step-5-provider-owner-disposition.md and
docs/reviews/0002-step-5-provider-review.md, including every ADR, plan, review,
contract, migration, SQL artifact and focused test named in the full handoff.
ADR-0005 and the reconciled proposal were accepted by Fortune on 2026-09-17;
do not request design approval again. Provider acceptance remains pending unless
an explicit owner decision is supplied. Record its actual scope faithfully;
partial acceptance does not close the other items. If absent, present corrected
implementation and both SQL artifacts with verified hashes for that decision.

Fresh strict CI passed 278 tests, zero failures/errors/skips, including 53
concurrency tests, 56 provider contracts and three seeded migration round trips
(legacy, provider Alembic and actual concrete SQL); both SQL artifacts match
offline generation, and drift is clean at b72e6a90c431. Counts overlap 278.
PostgreSQL 16.4/PostGIS 3.4.3 used imresamu/postgis:16-3.4. A temporary automatic
approval-review usage-limit rejection of drift checking was resolved after
Resume. The disposable container/data were removed; provision fresh data.

Resolve only authorized provider findings. Preserve matching/readiness policy,
promotion from provisional, exact eligible/current committed resolution-event
admission and committed Bronze input. Readers certify neither commit status nor
semantic truth. Keep the Repeatable Read/Serializable projection-lock fix,
provider-owned batch dependency/lock ordering and pending-lineage checks.
The provider revision b72e6a90c431 remains a review draft despite tracking;
synchronize both concrete SQL artifacts for authorized changes.

For required verification use /snap/docker/current/bin/docker with sandbox
escalation, imresamu/postgis:16-3.4 and fresh disposable *_test data. Run strict
make ci with zero failures/skips, drift, concurrency/retry, Python/SQL parity,
both lineage orderings/forced deferred checks and seeded provider preservation
through upgrade/downgrade/re-upgrade including concrete SQL. Prove whole-
transaction 40001/40P01 retry. Skips never establish acceptance. Record exact
limits if blocked; never change Docker permissions/deployment settings or run
SQL on application data. Remove only this task's temporary database/container.

Preserve immutable Menu snapshots, direct factual plus structural/inherited
support, inherit/full replacement/suppression, pins through ordinary supersession,
withdrawal tombstones and explicit restoration/rebasing, accepted-claim history
with K/O/E cutoffs, revisions across remaps, stable correspondence, applicability
after ancestor intersection, USD, exact contexts and individual modifiers.
Never infer local prices from Organization or sibling prices.

Stop at provider acceptance. If accepted, prepare a bounded Menu implementation
handoff for separate authorization; do not implement Menu, Gold, APIs, extraction,
ML, fuzzy matching, Step 6 or new dependencies. Step 5 still has roughly three
substantial Menu engineering/review units after provider acceptance.

End with (1) changes and reasons; (2) exact verification counts and limits;
(3) one next unit and completion criteria; (4) model/reasoning/mode/agent-count/
verbosity recommendation; (5) explicit same-chat/new-session recommendation and
reason; (6) a self-contained copyable next prompt preserving these same
completion-and-handoff requirements; and an updated Step 5 remaining-work
estimate. Continue the same chat for fixes within a unit; prefer a new session
at a distinct completed boundary. Never rely on prior chat access.
```
