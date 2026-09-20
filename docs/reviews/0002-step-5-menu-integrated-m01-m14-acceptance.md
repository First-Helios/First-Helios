# Step 5 integrated M01–M14 final acceptance — writer + both Menu SQL + selector

**Date:** 2026-09-19. **Owner:** Fortune. **Branch:** `Plan-0002-Step-5`.
**Reviewed HEAD:** `02549a44f6da051288be3489127ed78d9a62c017` (the writer drift-fix
commit), on the provider acceptance base
`de71d52f1b07ca363cc6cf8aa7a56cd2bc04ab3b`; branch and HEAD verified without
switching.
**Disposition:** the bounded Menu writer (revision `d83f0a21c592`), both concrete
Menu SQL directions, and the read-side selector were each **already accepted** by
Fortune on 2026-09-19 and are **byte-unchanged** here. This unit is the
**integrated** exercise of all three together across the full ADR-0005 example
matrix and the write-side concurrency/replay fixtures on one fresh CI-image
database. Green CI and this record are not acceptance on their own; the integrated
M01–M14 decision was supplied separately by the owner and is recorded below —
**accepted by Fortune on 2026-09-19** (see [§Owner disposition](#owner-disposition)).

## Scope of this unit

No implementation work. This unit runs the accepted **writer** (schema, admission,
lifecycle, immutability, migration, both SQL directions) and the accepted **read**
selector (`select_price`) **together** on one freshly provisioned disposable
database — the writer commits real aggregates and races; the selector reads those
committed aggregates across the ADR-0005 matrix — then reconfirms drift, SQL
synchronization, and byte-preservation of every accepted and provider artifact.

No accepted artifact byte was changed. No migration was added. No Gold, API,
extraction, ML, fuzzy matching, Step 6, new dependency, Docker-permission, or
deployment change. No application data was touched.

## Verification (fresh disposable data, 2026-09-19)

Run on a **freshly provisioned** container — not reused. Every count is from this
run.

| Check | Evidence |
|---|---|
| Strict `make ci` | All pre-commit hooks Passed; `mypy --strict` **Success, 58 source files**; `uv lock --check` clean (**56 packages**). Tests: **530 passed, 0 failed, 0 errors, 0 skipped, 0 xfailed**, **292.85s**, exit 0; coverage **98%** (5256 stmts, 113 uncovered). |
| Integrated Menu suite | **251 Menu tests** run together on one DB: writer **229** (`test_menu_schema` 145, `test_menu_replay` 20, `test_menu_concurrency` 48, `test_menu_migration` 3, `test_menu_boundaries` 13) + selector **22** (`test_menu_precedence`, file coverage 100%). |
| Read/write integration | The 22 `test_menu_precedence` read cases (full ADR-0005 example matrix + applicability/correspondence/cutoff fixtures) and the 20 `test_menu_replay` fixtures execute in the same suite/DB as the writer's committing concurrency races — read side reads what the write side committed. |
| Concurrency | **48 Menu** (+ 39 provider + 14 foundation = 101) with **0 skips**: both race orders, stronger-isolation rollback/revalidation, real deadlock retry, whole-transaction `40001`/`40P01` retry, real commits, forced `SET CONSTRAINTS ALL IMMEDIATE` deferred checks. |
| Migration round trips / SQL sync | **3** `test_menu_migration`: seeded upgrade→seed→downgrade→re-upgrade over both the Alembic path and the checked-in concrete SQL, plus fresh-offline SQL-generation equality (terminal-whitespace normalized). |
| Drift & head | `alembic check`: **No new upgrade operations detected**; `alembic heads`/`current` both **d83f0a21c592** (single head); **8** revision files (no migration added). |
| Live raw-SQL integrity | Fresh DB: **9** `menu` tables; USD `2` seeded; `ix_menu_evidence_page` present; `menu.admission_fence` sequence present; currency `UPDATE` and extra-currency `INSERT` both rejected (`ERROR: Menu aggregates and currency are immutable`); `menu.whitespace()` == Python `str.strip()` (**29** code points). |
| Untracked-file lint | `pre-commit run --files` on both untracked review records: all applicable hooks **Passed** (yaml/toml/python/ruff/mypy report *no files to check* — file-type filters on Markdown, not test skips); `git diff --check` exit 0. |
| Accepted-artifact preservation | All **8** accepted Menu artifacts byte-identical (below); all **5** accepted provider artifacts byte-identical; `docs/HumanDevNotes/MLDataExtractionPlan.md` = `ac509f8b…9db1c` unchanged. `git status` shows only the pre-existing 5 entries — no new tracked modification from the run. |
| Import boundary | `test_import_boundaries` (45) + `test_schema_layout` (26) pass: selector and writer import Identity/Bronze **contracts** only, no provider ORM, no upward/cross-vertical import; registry exception exact. |

Environment: `/snap/docker/current/bin/docker` (**29.8.0**) with sandbox
escalation, image `imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`,
PostgreSQL **16.4** / PostGIS **3.4.3**, disposable `helios_test` on a distinct
task-owned container `helios_int_m01m14_test`, host port **55445**. The task-owned
container and its anonymous volume were removed after the run (`docker rm -f -v`);
the developer stack container `helios-postgres` and volume `infra_postgres_data`
were not touched. One pre-existing dangling anonymous volume (created
2026-09-19T18:33Z, ~6.6h before this run) is **not** task-owned and was left
untouched. No application data was used.

## M01–M14 integrated coverage

Each proposal §9 obligation is exercised by the tests below in this run. This maps
coverage; it is not a claim of semantic source truth (human review owns that).

| ID | Obligation | Exercising tests (this run) |
|---|---|---|
| M01 | Scope, readiness, exact mapping, pending lineage at admission | `test_menu_schema`, `test_provider_contracts` (Python/SQL parity, provisional promotion) |
| M02 | Admission order vs. history; deferred must not repeat live checks | `test_menu_concurrency` (scope change→insert fails; complete insert then remap/retire same txn commits history) |
| M03 | Complete immutable aggregate; no UPDATE/DELETE/TRUNCATE/late child | `test_menu_schema` + live raw-SQL immutability probes |
| M04 | Direct / inherited / structural support | `test_menu_schema` |
| M05 | Same-page graph, cycles, base parents | `test_menu_schema` |
| M06 | Pin validity separate from head | `test_menu_precedence`, `test_menu_concurrency` |
| M07 | One stream across remaps, two revision counters | `test_menu_replay`, `test_menu_concurrency` |
| M08 | Tombstone / restoration; K before/after, O cannot resurrect | `test_menu_precedence`, `test_menu_replay` |
| M09 | Exact money and row shape | `test_menu_schema` |
| M10 | Applicability after ancestor/base intersection | `test_menu_schema`, `test_menu_precedence` |
| M11 | Stable correspondence and exact replay | `test_menu_replay`, `test_menu_precedence` |
| M12 | Time, ranking, no price leakage (§10 examples) | `test_menu_precedence` (all ADR-0005 matrix rows + fixtures) |
| M13 | Race serialization and ownership; whole-txn retry | `test_menu_concurrency` |
| M14 | Migrations and boundaries; two forward revisions | `test_menu_migration`, `test_schema_layout`, `test_import_boundaries` |

### Accepted artifact hashes (unchanged, rechecked before and after this run)

| Artifact | SHA-256 |
|---|---|
| Revision d83f0a21c592 | `cc5cc345215511687ac16adf6c1a741ba83dff0903ed368f5a03d8ee45f3b153` |
| Concrete Menu upgrade SQL | `55d4c4f36757e8ea188ca968984cdbc4de441f994fe546f6437d7db2c365f097` |
| Concrete Menu downgrade SQL | `b3820db752de822ccebb3700b77498aab7f31983e72ca68e8a0a7019a63d6400` |
| Menu models | `c99ce3e10654e7799b7d1a3bf63aadf765de90bd86a1f74d2ba411f49e7942c0` |
| Menu contracts | `64610ca0fa3e1d42921d8981922b4552e72ca0956fbf00bbd0665eecd4ae7227` |
| Menu commands | `1205ce6ef428a987c8d524572ffbc68fe925663aba2b3d9675faa835d16286ae` |
| Selector `selection.py` | `cdd4b62dee22cce62bd5676f6007379ded1d1a17938a5005f9b95c38280ad86d` |
| Selector `test_menu_precedence.py` | `b7dee1785420585ce942cb7f4a5899a6aaa575f3038c9aa8f30e1d96d364836f` |

Provider artifacts (all byte-identical): Bronze contracts
`d2f378aa…a1218`, Identity contracts `12c2af73…6fac12`, revision `b72e6a90c431`
`9295c9ed…4dc1b8`, provider upgrade SQL `1ec770dc…97a7be`, provider downgrade SQL
`f37fa34c…47e1cd`.

## Limits

No Gold, API, extraction, ML, fuzzy matching, Step 6, new dependency,
application-data execution, deployment, or load/scale benchmark. This is a
correctness result on disposable data, not a throughput claim and not proof of
semantic source truth. Mixed Bronze/resolution/Menu ingestion and historical
mutable-Identity reconstruction remain deferred. No bounded read-side correction
was needed: verification was clean and every accepted byte is preserved.

## Owner disposition

The accepted writer, both Menu SQL directions, and the read-side selector,
exercised **together** across the full ADR-0005 matrix and the write-side
concurrency/replay fixtures with the clean fresh-data verification above, are
presented for the single remaining explicit owner decision: the **integrated
M01–M14 final acceptance**. Green CI and this record are **not** that acceptance.

**Status: accepted by owner Fortune on 2026-09-19.** In this session, presented
the accepted writer (revision `d83f0a21c592`), both concrete Menu SQL directions,
and the read-side selector — exercised together across the full ADR-0005 matrix
and the write-side concurrency/replay fixtures, with the clean fresh-CI-image
verification recorded above and all artifact hashes rechecked before and after —
and asked for the single remaining integrated disposition. Fortune's decision:
**"Accept"** — integrated M01–M14 final acceptance. No correction or condition was
requested.

This is a real supplied decision, not inferred from green tests or this review. It
accepts the writer, both Menu SQL directions, and the selector at their recorded
SHA-256 values, exercised together; those bytes are unchanged. It does not
authorize Gold, APIs, extraction, ML, fuzzy matching, Step 6, a new dependency,
application-data execution, or any deployment. It completes the Step 5 Menu
engineering scope; Step 5 remaining work is a doc-only closeout.

## One next unit and completion criteria

If accepted: **close Step 5** (update ROADMAP/README/Plan 0002 Step 5 to
"integrated M01–M14 accepted") and open **Plan 0002 Step 6 — Gold read models**
(RFC-0001 / ROADMAP Phase 1) as a fresh, separately authorized unit. Completion of
that next unit is out of scope here.

If a defect were found on re-review: a bounded, separately scoped correction pass
against the specific artifact, then re-verification — never a silent rewrite of an
accepted artifact.

## Recommendation

Configured **high reasoning, Default/implementation mode, one agent, concise
reporting**. Continue the **same chat** to record the owner's integrated
disposition and, if accepted, the small Step-5-closing doc update. Prefer a **new
session** for the distinct Step 6 (Gold) boundary, using the repository and a
self-contained prompt rather than prior-chat access.

Step 5 remaining-work estimate after this unit: **one decision** (the owner's
integrated M01–M14 disposition) plus, if accepted, a **small doc-only closeout**.
No further Menu engineering unit remains in Step 5. Most product
collection/extraction/API/Gold work remains beyond Step 5.
