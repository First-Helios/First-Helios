# Step 6 — Gold current-menu read model — implementation review

**Date:** 2026-09-19. **Owner:** Fortune. **Branch:** `plan-0002-step-06`.
**Base HEAD:** `dde2dc31ea18585d3559f6e8741c10af260761fc` (Plan 0002 Step 5 merge).
**New migration head:** `5f3a9c1e7b24` (Revises `d83f0a21c592`); single head.

**Design authority:** [ADR-0006](../adr/0006-gold-menu-read-models.md), accepted by
the owner on 2026-09-19 with the bounded-input amendment (the first unit projects a
caller-supplied bounded scope set; full-catalog enumeration is deferred). This
record presents the concrete implementation for the separate migration/models
review that CLAUDE.md requires. **Green CI and this record are not owner
acceptance of the migration SQL or models.**

## Scope of this unit

The first `gold` projection: schema `gold`, table `gold.current_menu`, package
`packages.helios_core.gold`, and a Gold-owned full-rebuild refresh that reuses the
accepted Menu selector (`select_price`) as the single definition of "current". One
row per `(scope subject, target native path, effective context, currency)` records
the selector's local price and selected content plus surfaced freshness (`as_of`,
`staleness_seconds`). No price index, API, geospatial/H3, `h3-pg`/PostGIS use,
cross-venue taxonomy, targeted incremental refresh, extraction, ML, fuzzy matching,
matching-policy change, new runtime dependency, or deployment. No accepted Step 5
artifact byte was changed; no historical migration was rewritten.

## Changes

- `packages/helios_core/gold/{__init__,models,refresh}.py` — `CurrentMenu` model and
  `refresh_current_menu`. Imports only Menu (`selection`) plus Gold's own model;
  reuses the selector, never re-implements precedence. Refresh flushes; caller
  commits.
- `alembic/versions/5f3a9c1e7b24_add_gold_menu_read_models.py` — one forward
  migration after `d83f0a21c592`: `CREATE SCHEMA gold` + `gold.current_menu` with
  five `RESTRICT` FKs to `identity.subject`, `bronze.source_record`, `menu.currency`
  and `menu.menu_page` (×2), a NULLS-NOT-DISTINCT grain unique constraint, five FK
  indexes and ten CHECKs. Downgrade drops the table then the schema in dependency
  order, no `CASCADE`.
- `docs/reviews/sql/0002-step-6-gold-{upgrade,downgrade}.sql` — concrete SQL,
  synchronized with the migration (verified against fresh `--sql` generation).
- `packages/helios_core/db/base.py`, `db/model_registry.py` — register `gold` in the
  sole schema-owner map and model registry.
- `test/test_gold_refresh.py`, `test/test_gold_migration.py` — focused tests.
- `test/test_schema_layout.py` — schema-ownership assertion updated for `gold`; new
  gold-owns-exactly, Gold FK-direction, no-authoritative-FK-into-Gold, and
  gold import-boundary checks.
- `docs/adr/0006-gold-menu-read-models.md`, ROADMAP ADR ledger — design record.

## Verification (fresh disposable data, 2026-09-19)

Run on a **freshly provisioned** container — the earlier reused-container run was
discarded (a pre-existing suite test asserts a pristine `Capture` count and only
holds on fresh data). Every count is from the clean run.

| Check | Evidence |
|---|---|
| Strict `make ci` | Lint + `mypy --strict` (**64 source files**) + tests + `uv lock --check` (**56 packages**) all pass. Tests: **539 passed, 0 failed, 0 errors, 0 skipped**, **333.01s**, coverage **98%** (5494 stmts, 114 uncovered). |
| New Gold tests | **5**: `test_gold_refresh` **3** (selector fidelity, full-rebuild business-column equality, idempotence) at 100% file coverage; `test_gold_migration` **2** (concrete SQL artifact match, Menu preservation across the boundary) at 100%. `gold/models.py` 100%, `gold/refresh.py` 100%. |
| Rebuildability (Plan §8) | `test_full_rebuild_reproduces_business_columns`: seed Bronze/Identity/Menu, refresh, delete the projection, refresh again → identical business columns (`refreshed_at` and `id` excluded); source layers unchanged. |
| Drift & head | `alembic check`: **No new upgrade operations detected**; `heads`/`current` both **5f3a9c1e7b24** (single head); **9** revision files (one added). |
| Concrete SQL sync | Both artifacts equal fresh `alembic --sql` generation (terminal-whitespace normalized); **no `CASCADE`**; exactly **1** `CREATE TABLE gold.` and **1** `DROP TABLE gold.`. |
| Live raw-SQL integrity | Fresh DB: `gold.current_menu` has 5 FKs to `identity`/`bronze`/`menu` only, all `ON DELETE RESTRICT`; **no FK from any schema into `gold`**; unique NULLS-NOT-DISTINCT grain + 5 indexes + 10 CHECKs present. |
| Import boundary | `test_foundation_import_boundaries` (now including `helios_core/gold`) and registry-export tests pass: Gold imports Menu/Identity/Bronze contracts only via the selector; registry exception exact. |
| Untracked-file lint | `pre-commit run --files` on every new/changed file: all applicable hooks Passed (end-of-file-fixer added trailing newlines to the two SQL artifacts; the artifact-match test rstrips, still equal). `git diff --check` exit 0. |
| Step 5 preservation | All accepted Step 5 artifacts byte-identical: revision `d83f0a21c592` `cc5cc345…`, Menu up/down SQL `55d4c4f3…`/`b3820db7…`, selector `cdd4b62d…`, Menu models/contracts/commands `c99ce3e1…`/`64610ca0…`/`1205ce6e…`, `test_menu_precedence` `b7dee178…`, `MLDataExtractionPlan.md` `ac509f8b…`. |

Environment: `/snap/docker/current/bin/docker` (**29.8.0**) with sandbox
escalation, image `imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`,
PostgreSQL **16.4** / PostGIS **3.4.3**, disposable `helios_test` on task-owned
container `helios_gold_step6_test`, host port **55446**. The container and its
anonymous volume were removed (`docker rm -f -v`); the developer stack container
`helios-postgres` was not touched. No application data was used.

### New artifact hashes

| Artifact | SHA-256 |
|---|---|
| Revision `5f3a9c1e7b24` | `eb0da076e63aa1e40bb79a01da5acba7169a72ad0fb783bcd13fe06a2e63a8ab` |
| Concrete upgrade SQL | `0511402ddad2c301074e52fa099b5aa965b156a49ea1d5e8174f15e4229d0159` |
| Concrete downgrade SQL | `cca7181a6c7196e75c5622acd00b1977ec4228727f2f0f6b3eb9a2d9ee29814b` |
| `gold/models.py` | `4fcbf01805ace9d5c0bb1cb7465a7cfcb266c727a152b19139afc513b8e61923` |
| `gold/refresh.py` | `b266b102c5a984783c177d0f58e589b425331224461a96c9b18703ec432a393d` |

## Limits

Correctness on disposable data, not a throughput or scale claim (the full-rebuild
calls the selector per request — `O(scopes × targets)` — deferred as an
optimization). Bounded input only; the full current-catalog enumeration and the
price index remain deferred (ADR-0006). No API, geospatial, extraction, ML, new
dependency, deployment, or application-data execution. Constraints guarantee FK
direction and row shape, not semantic source truth.

## Owner disposition

Presented for the owner's separate review of the concrete migration SQL and models
(CLAUDE.md expensive-to-reverse path). Green CI and this record are **not**
acceptance. **Status: pending owner disposition.**

## One next unit and completion criteria

After acceptance: the deferred **full-catalog refresh** (enumerate current eligible
scopes/targets from Identity + Menu) and/or the **price-index projection** with the
price-index API (ROADMAP Phase 7). Completion of either is out of scope here.
</content>
