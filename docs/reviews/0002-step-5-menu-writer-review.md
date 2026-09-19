# Step 5 bounded Menu persistence and writer review

**Date:** 2026-09-19. **Branch:** `Plan-0002-Step-5`.
**Base HEAD:** `de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b`, verified without switching.
**Disposition:** implementation and concrete SQL are review drafts; owner Menu
SQL acceptance is not inferred. Final verification is recorded below.

The owner authorized this bounded implementation, its models, contracts,
commands, one Menu migration and disposable-data verification. Fortune's
ADR-0005 acceptance (2026-09-17) and corrected provider/code/SQL acceptance
(2026-09-18) remain settled. The [provider acceptance and handoff](0002-step-5-provider-acceptance-and-menu-handoff.md)
and earlier decisions are unchanged. No new approval of those artifacts is needed.

## Change and review surface

The [Menu package](../../packages/helios_core/domains/menu/) stores complete,
immutable interpretations with explicit initial, observation, correction,
withdrawal and restoration operations. A location can pin shared content and
assert its own price without copying the shared description or claiming a
shared price as local. Exact replay returns original IDs; changing a revision's
payload, membership, base, scope, method or support raises a conflict.

- [Models](../../packages/helios_core/domains/menu/models.py): exactly nine
  typed tables, registered through the existing sole registry and owner map.
  The only seeded currency is USD. Foreign keys are restrictive and point only
  to Menu, Bronze or Identity. Same-page composite relationships, typed base
  references, native parent namespaces and NULL-safe declared contexts remain
  explicit; there is no JSON fact store.
- [Contracts](../../packages/helios_core/domains/menu/contracts.py): frozen
  typed inputs use exact integer money and finite Decimal confidence. Explicit
  inheritance carries references without copied facts; replacements provide
  complete typed content, and optional NULL clears. Modifiers are individual
  requirements, not choice groups.
- [Commands](../../packages/helios_core/domains/menu/commands.py):
  `persist_menu` flushes, validates the complete aggregate and releases its own
  savepoint; it never commits the caller's transaction. A caught Python reference
  error cannot leave a supported prefix behind. Callers own whole-transaction
  rollback/retry for `40001` and `40P01`. `read_aggregate` is inspection of
  transaction-visible accepted claims, not current selection or commit certification.
- [Revision d83f0a21c592](../../alembic/versions/d83f0a21c592_add_immutable_menu_aggregates.py)
  follows accepted `b72e6a90c431`. Its DDL is self-contained; it does not import
  mutable live model definitions. It installs the constraints, functions,
  insertion/immutability triggers and deferred checks atomically.
- Review [concrete upgrade SQL](sql/0002-step-5-menu-upgrade.sql) and
  [concrete downgrade SQL](sql/0002-step-5-menu-downgrade.sql) separately.
  Downgrade removes only Menu-owned objects without CASCADE, deliberately
  destroys Menu history and restores the provider revision. Re-upgrade creates
  empty Menu plus USD; it cannot recover deleted history.

## Integrity and transaction choices

Every page, node, context, price and Evidence-link insert calls the complete
Identity local/base batch before Menu locks. Providers retain readiness policy,
parent expansion, pending-lineage checks and lock ordering. A complete aggregate
admitted before an ordered remap/retirement remains history. A later insert
fails; deferred integrity never repeats live eligibility or base admission.
Closed establishments remain admissible when Identity says they are eligible.

Bronze's published helpers supply immutable version/Evidence ownership and
business keys. They do not certify commits or semantic truth. Menu separately
checks tuple transaction status for its referenced version, Capture and Evidence,
including own savepoint subtransactions; provider rows/functions are untouched.
Expected resolution events and base/predecessor pages must already be committed.
Mixed Bronze-persist/resolve/Menu orchestration remains unsupported.

Source Record locks serialize revisions, and unique stream/version/predecessor
keys prevent forks across remaps. Accepted timestamps are server assigned and
strictly advance by at least one microsecond. They are admission times, not a
commit-time audit log. Ordinary observation uses a previously unused later
Bronze version; correction can explicitly revisit older input. Only restoration
can publish after withdrawal. Withdrawals contain direct page support and no graph.

A Menu advisory lock and one **non-MVCC transaction watermark sequence** close
the stale-snapshot gap for append-only base withdrawals. Merely locking unchanged
provider rows cannot make a Repeatable Read snapshot see a new Menu tombstone.
After the provider batch, Menu checks that the preceding writer's transaction is
visible to its snapshot before updating the watermark. Otherwise it raises
`40001`. This deliberately serializes new Menu writes until transaction end;
it is a correctness-first implementation, not a throughput claim. A rolled-back
watermark can conservatively require retry. No tenth table, mutable aggregate,
provider lock-policy change, background service or dependency is introduced.
Arbitrarily composed/pre-acquired locks can still deadlock; tests prove full retry.

Ordinary shared successors preserve pins, including a new explicit pin to an
older published page. Withdrawal invalidates all earlier pins. Restoration
makes new content pinnable but does not revive old pins; a local successor must
explicitly rebase. Deferred checks retain immutable parent/base correspondence
rather than retroactively rejecting history after a later base change.

Direct nodes, contexts, prices and pages require exact-version or matching-
Capture Evidence. Structural Unsectioned grouping derives support from direct
local items. Inherited references expose the base support path. SQL validates
ownership and structure, never whether an excerpt truly asserts a price.
Suppressed branches cannot receive local children or prices. Context checks
intersect local and base ancestor restrictions, including omitted inherited
base descendants under mapped local ancestors. Unspecified channel remains an
exact distinct context, and empty intersections fail.

Replay compares complete canonical payload and sorted support sets; it excludes
server stamps and generated child IDs. Bronze business-equivalent duplicates
can reuse the old aggregate without new writes. Native IDs have stable typed
parent paths; absent native IDs remain snapshot locators. Cross-page
correspondence/ranking is deliberately left to the selector unit, with no name
matching or implicit continuity promised by stored local keys.

## Enforcement and coverage map

All categories below are bounded persistence obligations. Tests use disposable
`*_test` data, raw SQL and commands; positive aggregates have forced deferred
checks and real outer commits, and negative support tests exercise both boundaries.

| ID | Implemented and tested here | Deferred selection obligation |
|---|---|---|
| M01 | Per-insert provider scope, exact mapping, kind, features, eligibility and pending lineage; provider promotion policy tests retained. | Current-read scope/availability evaluation. |
| M02 | Both scope-change orders; accepted history after remap/retirement; every member rechecks; parent/survivor pending membership. | Historical answer presentation. |
| M03 | Server stamps, late membership, UPDATE/DELETE/TRUNCATE rejection, complete support and rollback of partial writer attempts. | None. |
| M04 | Exact committed support, capture/version ownership, structural and inherited shapes, copied-payload rejection. | Rendering separate factual Evidence paths. |
| M05 | Same-page FKs, cycles, base parent/type mapping, duplicate mappings, deep graphs, variants, both modifier parent shapes, NULL-clearing and suppression. | Overlay presentation and unresolved-base results. |
| M06 | Pin admission through supersession, withdrawal/restoration/rebase, wrong/uncommitted operator base, both withdrawal race orders. | Current/historical pin evaluation at K/O/E. |
| M07 | Committed predecessor chain, global revisions, duplicate/fork/skip rejection, later observation and older correction, remap and successor races. | Stream head at cutoff K. |
| M08 | Tombstone shape and explicit restoration; old pins stay invalid after restoration. | No predecessor resurrection after K/O/context filters. |
| M09 | USD catalog, exact BIGINT DTO validation/storage, confidence, XOR targets, negative modifier delta, zero absolute, explicit unknown/unavailable. | Returning derived unknown for absence. |
| M10 | NULL-safe context uniqueness, finite half-open windows, ancestor/base/implicit-descendant intersections, incompatible channel/period/window rejection. | Equality/ranking of effective tuples and E filtering. |
| M11 | Native parent namespace and path checks; exact/reordered/canonical replay, payload/support conflicts, concurrent replay; base correspondence. | Cross-source native/base equivalence and version-local fallback keys. |
| M12 | Immutable Bronze observation times, server acceptance order, preserved accepted scope/event; separate Organization/local storage. | Kind/recency/confidence/business-key ranking, K/O/E examples, no local fallback results. |
| M13 | Real blocking, both scope/replay/successor/base race orders, stronger-isolation rollback/revalidation, real deadlock retry, Bronze FK compatibility and rebuild exclusion. | Selector snapshot consistency and integrated read/write scenarios. |
| M14 | Active ownership/import/FK checks, both Menu SQL directions, seeded full provider row/object/sequence preservation, SQL-generation equality and drift. | Final integrated acceptance after the selector lands. |

Focused sources: [schema](../../test/test_menu_schema.py),
[replay/lifecycle](../../test/test_menu_replay.py),
[concurrency](../../test/test_menu_concurrency.py),
[migration](../../test/test_menu_migration.py), and
[boundaries](../../test/test_menu_boundaries.py).
The existing provider round-trip test now explicitly descends to its own
historical head before testing that boundary; all preservation assertions remain.
No accepted provider implementation, SQL or historical migration is changed.

## Verification

Verification completed 2026-09-19 on fresh disposable CI-image data. An
interrupted 2026-09-18 full run lost its temporary logs and does not establish
acceptance; the stale container from that run was discarded, not reused. Every
count below is from a clean run against a newly provisioned database.

**Drift correction made during verification.** The first `alembic check`
detected one model/migration divergence: the ORM declared index
`ix_menu_evidence_page` on `menu.evidence_link (page_id)` (the leading FK index
required by the ownership boundary test), but revision `d83f0a21c592` never
created it. The revision now issues that `CREATE INDEX`, and the concrete
upgrade SQL artifact was regenerated to match; the downgrade is unaffected
because it removes the table (and thus its indexes). All counts below are from
the re-run on fresh data after this fix.

| Check | Evidence |
|---|---|
| Strict `make ci` | Lint (pre-commit over all tracked files, then an explicit pass over every changed/untracked file), mypy `--strict` **56 source files** success, and `uv lock --check` clean. Tests: **508 passed, 0 failed, 0 errors, 0 skipped**, **272.06s**, exit 0; coverage **98%**. |
| Menu package coverage | `models.py` **100%**, `commands.py` **95%**, `contracts.py` **95%**. |
| Included Menu tests | **229**: schema 145, replay/lifecycle 20, concurrency 48, migration 3, boundaries 13. |
| Included concurrency | **101** total: **48 Menu** + 39 provider + 14 foundation. Both race orders per scenario (replay, successor, scope-change, base withdrawal), stronger-isolation rollback/revalidation, real deadlock retry, and whole-transaction `40001`/`40P01` retry. |
| Included migration round trips | **3**: the seeded Menu/provider preservation test runs the full upgrade→seed→downgrade→re-upgrade cycle over **both** the Alembic path and the checked-in concrete SQL files, plus the SQL-generation equality test. Menu comes up empty-then-USD (9 tables); all **21 provider tables**, sequence state and object signatures are byte-stable across every Menu transition. |
| Included SQL synchronization | Both artifacts equal fresh offline generation (terminal whitespace normalized); no `CASCADE`; upgrade has 9 `CREATE TABLE menu.`, downgrade 9 `DROP TABLE menu.`. |
| Drift and head | **No new upgrade operations detected**; current revision and sole head both **d83f0a21c592**. |
| Provider preservation | Five accepted provider artifact SHA-256 rechecked and **byte-identical** to the acceptance/handoff packet. |
| Whitespace-trim alignment | `menu.whitespace()` lists exactly Python `str.strip()`'s whitespace set (ASCII controls, NEL, NBSP, and the Unicode separators); the parametrized regression rejects leading/trailing `\t`, `\n`, `U+00A0` and `U+3000` at the raw-SQL boundary. |

Counts overlap the 508 total. The run used `/snap/docker/current/bin/docker`
with sandbox escalation, `imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`,
PostgreSQL **16.4** / PostGIS **3.4.3**, and fresh disposable
`helios_menu_ci_test` data. The container and its anonymous data volume were
removed after the run; the developer stack volume `infra_postgres_data` was
never touched. Future verification must provision fresh data.

Reviewed Menu artifact hashes:

| Artifact | SHA-256 |
|---|---|
| [Revision d83f0a21c592](../../alembic/versions/d83f0a21c592_add_immutable_menu_aggregates.py) | `cc5cc345215511687ac16adf6c1a741ba83dff0903ed368f5a03d8ee45f3b153` |
| [Concrete upgrade SQL](sql/0002-step-5-menu-upgrade.sql) | `55d4c4f36757e8ea188ca968984cdbc4de441f994fe546f6437d7db2c365f097` |
| [Concrete downgrade SQL](sql/0002-step-5-menu-downgrade.sql) | `b3820db752de822ccebb3700b77498aab7f31983e72ca68e8a0a7019a63d6400` |
| [Models](../../packages/helios_core/domains/menu/models.py) | `c99ce3e10654e7799b7d1a3bf63aadf765de90bd86a1f74d2ba411f49e7942c0` |
| [Contracts](../../packages/helios_core/domains/menu/contracts.py) | `64610ca0fa3e1d42921d8981922b4552e72ca0956fbf00bbd0665eecd4ae7227` |
| [Commands](../../packages/helios_core/domains/menu/commands.py) | `1205ce6ef428a987c8d524572ffbc68fe925663aba2b3d9675faa835d16286ae` |

This run verifies the bounded writer, schema and both concrete SQL directions
on disposable data only. It is a correctness result, not a throughput claim:
the transaction watermark deliberately serializes new Menu writes to close the
stale-snapshot base-withdrawal gap. It records no owner acceptance of the Menu
SQL, no application-image build/smoke, no application-data execution, and no
selector, load or semantic source-truth claim.

## Limits, next unit and remaining estimate

No owner acceptance of unseen Menu SQL is recorded. No pure current/history
selector or price ranking, Gold, API, extraction, ML, fuzzy matching, Step 6,
new dependency, application-data execution, deployment or load benchmark is
included. Organization and sibling prices never become inferred local prices.
The selector must retain accepted-claim history with K/O/E and each fact's own
scope/time/Evidence. Runtime inspection does not certify semantic source truth.

**One next unit: review this bounded writer and both concrete Menu SQL artifacts,
resolve Menu-only findings, and record the owner's actual disposition.** Completion
requires any corrections to pass strict fresh CI-image checks, synchronized SQL,
no drift and provider preservation, followed by an explicit disposition against
the reviewed artifact hashes. Do not start selection automatically. Design and
provider acceptance are settled; only this new implementation/SQL is under review.

Step 5 has roughly **two substantial engineering/integration units remaining**
after this writer's review: pure current/accepted-history selection with the
full example matrix and extended replay fixtures; then integrated M01–M14
acceptance and final SQL/owner review. This is a scope estimate, not a duration
promise; review findings can add a bounded correction pass. Most product
collection/API work remains beyond Step 5.

Recommend configured **gpt-6-astra, high reasoning, Default/implementation mode,
one agent, concise/low verbosity**. Configuration is unchanged; no runtime model
switch is claimed. Continue the **same chat for corrections within this unit**.
Prefer a **new session for the distinct Menu technical/SQL review boundary**,
using the repository and self-contained prompt below, never prior-chat access.

## Copyable next prompt

```text
Review Helios Plan 0002 Step 5's bounded Menu persistence, admission and lifecycle
writer and both concrete Menu SQL directions. Resolve Menu-only findings and
finish verification/handoff; do not stop at a plan or rely on prior chat access.
Use configured gpt-6-astra, high reasoning, Default/implementation mode, one
agent and concise reporting. This authorizes corrections to the new Menu draft,
its models/contracts/commands/tests and SQL on disposable data only.

Verify branch Plan-0002-Step-5 and actual HEAD; report mismatch before switching.
The provider acceptance base was de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b.
Preserve every tracked modification and untracked file, especially provider
fixes/tests/SQL, verification hardening, Menu implementation/designs/review,
historical decisions, acceptance/handoff records, readiness reassessment and
docs/HumanDevNotes/MLDataExtractionPlan.md. No reset, clean, discard, commit,
push, merge, deploy or rewriting historical migrations/acceptance records.

Read CLAUDE.md, README.md, CONTRIBUTING.md, relevant ROADMAP.md sections,
docs/reviews/0002-step-5-menu-writer-review.md and all linked implementation,
SQL, tests and handoffs. Read the provider acceptance-and-menu-handoff,
owner-disposition and provider-review records; ADR-0004/0005, Plan 0002, the
reconciled Menu proposal and example matrix. Never rely on earlier chat access.
Fortune accepted ADR-0005/proposal on 2026-09-17 and corrected provider/code/both
SQL directions on 2026-09-18: “All looks good on the implementation guide,
All proposals approved”. Do not request those approvals again. Accepted provider
artifacts remain unchanged. Menu SQL still needs its own explicit disposition;
green tests or this instruction to review are not owner acceptance.

Review the nine-table Menu schema and single draft d83f0a21c592 after
b72e6a90c431; immutable complete writer, read-only exact aggregate replay and
conflicting-payload rejection; explicit initial/observation/correction/withdrawal/
restoration lifecycle; per-insert live admission separate from deferred immutable
integrity. Commands never commit. Providers own readiness/dependency/lock policy;
submit the full local/base batch before Menu locks. Review the Menu transaction
watermark's stale-snapshot safety and conservative serialization/retry cost.
Preserve provisional promotion, exact current committed-event admission,
committed Bronze input, pending lineage and both scope-change orderings.
Readers certify neither commits nor source truth; mixed ingestion is unsupported.

Preserve direct factual/structural/inherited support; inherit/full replacement/
suppression; pins through ordinary supersession; withdrawal tombstones and
explicit restoration/rebasing; accepted-claim history with K/O/E; revisions across
remaps; stable native/base correspondence and version-local fallback locators;
applicability after ancestor intersection; USD, exact contexts and individual
modifiers. Never infer local prices from Organization or sibling prices.
Defer pure current/history selection and ranking to the next implementation unit.
No Gold, APIs, extraction, ML, fuzzy matching, Step 6 or new dependencies.

Use /snap/docker/current/bin/docker with sandbox escalation, imresamu/postgis:16-3.4
and fresh disposable *_test data. Do not assume prior containers/logs remain.
Run strict make ci with zero failures/errors/skips, drift, raw-SQL/Python integrity,
forced deferred checks, real commits, both race orders and whole-transaction
40001/40P01 retry. Execute actual concrete SQL round trips with seeded Menu and
complete provider row/object/sequence preservation. Keep both SQL artifacts
synchronized and explicitly lint untracked files. Skips never establish
acceptance. No Docker permission/deployment changes or application-data execution.
Remove task-owned disposable resources. Record exact counts and limits in the repo.

Stop at this bounded Menu review/disposition. Present concrete artifacts for the
owner; record only an actual supplied decision. Do not begin the selector unit.
End with (1) changes and reasons; (2) exact verification counts and limits;
(3) one next unit and completion criteria; (4) model/reasoning/mode/agent-count/
verbosity recommendation; (5) explicit same-chat/new-session recommendation and
reason; (6) a self-contained copyable next prompt preserving these same completion-
and-handoff requirements; and an updated Step 5 remaining-work estimate.
Continue the same chat for fixes within a unit; prefer a new session at a distinct
completed boundary. Never rely on prior chat access.
```
