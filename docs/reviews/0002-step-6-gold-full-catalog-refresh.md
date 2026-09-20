# Step 6 — Gold full-catalog current-menu refresh — implementation review

**Date:** 2026-09-20. **Owner:** Fortune. **Branch:** `plan-0002-step-06`.
**Base HEAD:** `b8f9150e09432f34584b037a06777bb8eae8b8f6` (`feat(db): gold table
generation`). **Migration head:** `5f3a9c1e7b24` — **unchanged; no new migration**.

**Design authority:** [ADR-0006](../adr/0006-gold-menu-read-models.md), accepted by
the owner on 2026-09-19. Owner decision point 5 (bounded-input amendment) shipped
the first Gold unit over a caller-supplied scope set and **deferred** "enumerating
'all current eligible scopes and targets' across the catalog." This unit is that
deferred enumeration. It reuses the accepted selector and the accepted
`gold.current_menu` table; it changes no accepted Step 5 or Step 6 byte and adds no
migration. **Green CI and this record are not owner acceptance** of the design or
scope (per CLAUDE.md and the ADR-0006 note that the Owner decision "does not
authorize … the full-catalog refresh"): the full-catalog refresh is presented here
for the owner's separate disposition.

## Scope of this unit

The full-catalog refresh: enumerate the current priced catalog from committed
Identity + Menu (+ Bronze provenance) and materialize `gold.current_menu` for the
whole catalog by reusing the accepted `select_price` selector and the accepted
bounded `refresh_current_menu`. No price index, API, geospatial/H3, `h3-pg`/PostGIS
use, cross-venue taxonomy, targeted incremental refresh, scheduler, extraction, ML,
fuzzy matching, matching-policy change, new runtime dependency, or deployment. No
schema change.

## Changes

- **`packages/helios_core/domains/menu/enumeration.py`** (new; Menu domain).
  `enumerate_current_requests(session, *, effective_instant) -> list[SelectionRequest]`.
  Kept in the Menu domain, beside the accepted selector, so there is a **single**
  definition of correspondence, effective-context intersection, and current
  eligibility: it reuses the selector's own helpers (`_stream_heads`, `_graph`,
  `_canonical_native_path`, `_effective_context`, `_contains_instant`,
  `_price_target_column`, `_live_scope`, `_operating_ok`) rather than re-deriving
  native paths or re-implementing selection precedence in SQL. Reads only; no writes.
- **`packages/helios_core/gold/catalog.py`** (new; Gold).
  `refresh_full_catalog(session, *, effective_instant, refreshed_at=None) -> int`
  enumerates, deletes the **whole** projection (whole-table replacement, unlike the
  bounded per-family refresh, so a scope that has left the current catalog loses its
  rows — ADR-0004 §5 retired-predecessor exclusion), then reuses the accepted
  `refresh_current_menu` to record `select_price` per request. Flushes; the caller
  commits. Imports the published Menu enumeration/selector contracts and Gold's own
  refresh/model only.
- **`test/test_gold_catalog.py`** (new). Four focused tests (below).

The accepted Step 6 unit's public surface (`packages/helios_core/gold/__init__.py`)
was **left byte-identical**; the new entrypoint is `gold.catalog.refresh_full_catalog`.
On acceptance it can be re-exported from `gold/__init__.py`.

## Design decisions (owner review surface)

1. **Enumeration lives in the Menu domain, reusing the selector's internals.**
   Building a `TargetRef` requires the selector's canonical native-path logic and
   its applicability intersection; re-deriving them in Gold would create the second
   definition ADR-0006 forbids. The enumeration therefore sits beside the selector
   and reuses it; Gold imports the published `enumerate_current_requests`.
2. **Price-driven grain.** One request per grain-unique `(scope subject, source-local
   family, target, effective context, currency)` that has a live `PriceObservation`
   on a current head page whose effective window contains the refresh instant `E`.
   `gold.current_menu` is a per-`(target, context, currency)` price projection
   (RFC-0001 §D2). **Limit:** a target that carries only inherited content with **no
   local price observation** — and a target whose only price is a shared Organization
   price surfaced as an org claim — is **not** enumerated as its own establishment
   row in this first unit. Shared Organization prices are enumerated as their own
   `organization`-scoped rows. This is a documented, owner-reviewable narrowing, not
   a selector change; the API/price-index unit can widen it if content-only rows are
   wanted.
3. **Current, eligible, operating only.** Each candidate scope is admitted through
   the same live-Identity/operating gate the selector uses (`require_resolved_scopes`
   + operating check). A broken mapping (remap/retire/pending lineage) or a
   not-operating Establishment at `E` yields **no rows** (excluded), so
   retired-predecessor facts never enter the current catalog (ADR-0004 §5).
4. **Whole-table replacement + full rebuild.** Determinism and idempotence hold over
   the whole catalog: enumeration is a pure function of committed Bronze/Identity/
   Menu, so a rebuild over unchanged sources yields byte-identical business columns;
   `refreshed_at` (and `id`) are excluded from rebuild-equality. Targeted incremental
   refresh remains deferred (ROADMAP Phase 6).

## Verification (fresh disposable data, 2026-09-20)

Authoritative run on a **freshly provisioned, pristine** `helios_test` (the earlier
runs were discarded and the database recreated, because a pre-existing suite test
asserts a pristine `Capture` count that only holds on fresh data). Strict mode was
run **once** against these final bytes.

| Check | Evidence |
|---|---|
| Strict `make ci` | Lint (pre-commit) + `mypy --strict` (**67 source files**, no issues) + tests + `uv lock --check` (**56 packages**) all pass. Tests: **543 passed, 0 failed, 0 errors, 0 skipped**, **312.21s**, coverage **98%** (5672 stmts, 120 uncovered). |
| New Gold/enumeration tests | **4** in `test_gold_catalog.py` (100% file coverage): current+operating scope materialized to equal `select_price`; not-operating scope excluded; enumeration deterministic and scoped; whole-catalog rebuild reproduces identical business columns with source layers unchanged; idempotent re-refresh with no duplicate grain. `gold/catalog.py` 100%; `menu/enumeration.py` **88%** (6 uncovered lines are defensive skip guards mirroring the selector's own uncovered guards, `selection.py` 93%). |
| Rebuildability (A11 / Plan §8) | `test_full_catalog_rebuild_reproduces_business_columns`: seed Bronze/Identity/Menu, `refresh_full_catalog`, snapshot the family's business columns and its `menu_page`/`price_observation` counts, `DELETE` the whole projection, `refresh_full_catalog` again → identical business columns (`id`/`refreshed_at` excluded); source-layer counts unchanged. |
| Idempotence | `test_full_catalog_refresh_is_idempotent`: two full refreshes over unchanged sources → identical business columns; exactly one row per grain, no accumulation. |
| Determinism/exclusion | `test_full_catalog_enumeration_is_deterministic_and_scoped`: two enumerations are equal; the open scope's grain is present; the closed scope contributes no request. |
| Drift & head | `alembic check`: **No new upgrade operations detected**. `heads` = **5f3a9c1e7b24** (single head). **9** revision files — **no migration added**. |
| Live FK direction (raw SQL, fresh DB) | `gold` has **6** outbound FK column references, **0** FKs from any schema into `gold`, and **5** FK constraints all `ON DELETE RESTRICT`. Unchanged from the accepted Step 6 migration. |
| Import boundary | `test_foundation_import_boundaries` (scans `helios_core/gold` and `helios_core/domains/menu`, including the two new files) passes: the enumeration reuses only Menu internals; Gold imports the published Menu contracts and its own refresh/model. |
| Untracked-file lint | `pre-commit run --files` on the three new files: all applicable hooks pass (`ruff`, `ruff format`, `mypy`). `git diff --check` exit 0. `pre-commit run --all-files` alone does **not** cover untracked files, so they were linted explicitly. |
| Step 5/6 preservation | All pinned/accepted artifacts byte-identical (hashes below). No accepted byte changed; no historical migration rewritten. |

Environment: `/snap/docker/current/bin/docker` **29.8.0** with sandbox escalation,
image `imresamu/postgis:16-3.4`, digest
`sha256:6da75969915039b7356058b4310d43fde88c275ada982c2dfee29da68445ff4d`,
PostgreSQL **16.4** / PostGIS **3.4.3**, disposable `helios_test` on task-owned
container `helios_gold_catalog_test`, host port **55447**. The container and its
anonymous volume were removed (`docker rm -f -v`); the developer stack container
`helios-postgres` was not touched. No application data was used.

### Preserved (accepted) hashes — unchanged this unit

| Artifact | SHA-256 |
|---|---|
| Revision `d83f0a21c592` (Menu) | `cc5cc345215511687ac16adf6c1a741ba83dff0903ed368f5a03d8ee45f3b153` |
| `domains/menu/selection.py` | `cdd4b62dee22cce62bd5676f6007379ded1d1a17938a5005f9b95c38280ad86d` |
| Revision `5f3a9c1e7b24` (Gold) | `eb0da076e63aa1e40bb79a01da5acba7169a72ad0fb783bcd13fe06a2e63a8ab` |
| `gold/models.py` | `4fcbf01805ace9d5c0bb1cb7465a7cfcb266c727a152b19139afc513b8e61923` |
| `gold/refresh.py` | `b266b102c5a984783c177d0f58e589b425331224461a96c9b18703ec432a393d` |
| `gold/__init__.py` | `4a0c53f7b04eb877ec91a9d6d6e2627e78586b61419d8f938cf1caf3b43825ea` |
| `domains/menu/models.py` | `c99ce3e10654e7799b7d1a3bf63aadf765de90bd86a1f74d2ba411f49e7942c0` |
| `domains/menu/contracts.py` | `64610ca0fa3e1d42921d8981922b4552e72ca0956fbf00bbd0665eecd4ae7227` |
| `domains/menu/commands.py` | `1205ce6ef428a987c8d524572ffbc68fe925663aba2b3d9675faa835d16286ae` |
| `db/model_registry.py` | `e5a5a61983106ee7d1bfdc9337348f20984c5174fc3870026134f9ea8a778d2e` |

### New artifact hashes

| Artifact | SHA-256 |
|---|---|
| `domains/menu/enumeration.py` | `ed6b3132452d2a2b2ccec3a3cd7c52b45790d7165d46884e66c01babc5d5be1e` |
| `gold/catalog.py` | `91ea3dffd4c4c63fd576cc2ba602f37f80bea1910735452a2c7c739e862f2509` |
| `test/test_gold_catalog.py` | `77f3c614f829e31b8f73253d2b1063171f81d87d6bbff5a05c9956730d0b3dc8` |

## Limits

- Correctness on disposable data, **not** a throughput or scale claim. The
  full-catalog refresh calls the selector per enumerated request and the live
  Identity guard per candidate scope — `O(scopes × targets)` — which ADR-0006 named
  as the deferred targeted-incremental optimization (ROADMAP Phase 6).
- Price-driven grain only (decision 2): content-only and shared-price-only targets
  do not get an establishment row in this unit.
- No API, price index, geospatial/H3, cross-venue taxonomy, new dependency,
  deployment, or application-data execution. Constraints guarantee FK direction and
  row shape, not semantic source truth.

## Owner disposition

Presented for the owner's separate review (the full-catalog refresh and its
price-driven scope decision). Green CI and this record are **not** acceptance.

**Accepted "Accept as-is" by project owner Fortune on 2026-09-20.** This is a real
supplied decision, not inferred from tests or this document. It accepts the
full-catalog `refresh_full_catalog` / `enumerate_current_requests` implementation,
its price-driven grain (decision 2) and current-eligible-operating exclusion
(decision 3), and the enumeration's placement in the Menu domain (decision 1). It
does not authorize the price index, an API, or any deployment. **Status: accepted.**

## One next unit and completion criteria

After acceptance: the **price-index projection with its price-index API**
(ROADMAP Phase 7). It needs its **own** owner-accepted ADR/decision — cross-venue
item taxonomy is deferred and the `h3-pg`/PostGIS extension and Place geospatial
columns are absent — so it must be proposed in an ADR and **stopped for human
review** before implementation. Completion of that unit is out of scope here.
