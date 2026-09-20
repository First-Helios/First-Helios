# ADR-0006: Gold menu read models — shape, materialization, and refresh

**Status:** Accepted
**Date:** 2026-09-19
**Accepted:** 2026-09-19 by project owner Fortune. Proposed defaults accepted;
the first unit materializes a **bounded input set** (full-catalog enumeration
deferred). See [Owner decision](#owner-decision).
**Extends:** [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md),
[ADR-0005](./0005-immutable-menu-snapshots-and-selection.md)
**Implements:** [Plan 0002 Step 6](../plans/0002-identity-foundation-before-menu.md#step-6---featdb-add-gold-menu-read-models)

## Context

Step 5 is complete. The immutable Menu writer (revision `d83f0a21c592`), both
concrete Menu SQL directions, and the pure read-side selector
(`packages/helios_core/domains/menu/selection.py`) received integrated M01–M14
final acceptance from the owner on 2026-09-19
([record](../reviews/0002-step-5-menu-integrated-m01-m14-acceptance.md)). Step 6
adds the first `gold` projection over accepted Menu/Identity/Bronze.

**What is already settled at the ADR level** (do not reopen):

- Gold is the `gold` schema, owned by `packages.helios_core.gold`, holding
  "rebuildable consumer read models and aggregates"
  ([ADR-0004 §1–2](./0004-modular-monolith-identity-and-lifecycle.md)).
- Gold is rebuildable from Bronze and Silver, may be truncated or replaced by
  its owning refresh task, and is never an authoritative write target
  (ADR-0004 §1). Identity correctness never depends on Gold (ADR-0004 §5).
- FK direction: `gold` may reference `gold`, `menu`, `identity`, `bronze`; no
  authoritative table references `gold`; observation/history FKs use
  `RESTRICT`/`NO ACTION` (ADR-0004 §7). Gold reads **published contracts**
  only.
- Gold excludes facts scoped only to a retired ambiguous predecessor from
  current views, while historical queries retain them (ADR-0004 §5).
- Derived read models are ordinary tables refreshed by an explicit task, **not
  materialized views** — the reasoning ADR-0003 recorded for `mart` and
  ADR-0004 carried forward as "truncated or replaced by its owning refresh
  task." Postgres cannot incrementally refresh a matview, and Alembic manages
  matviews poorly ([ADR-0003](./0003-three-layer-schema.md)).

**What is *not* settled, and is why this ADR exists.** No ADR fixes the concrete
Gold read-model shape or refresh contract:

- ADR-0005 explicitly excludes Gold: "No models, contracts, migrations,
  extraction, ML, Gold, API, runtime dependency or deployment changes are part
  of this decision-record work."
- Plan 0002 §4 lists "Gold menu projections and API-specific indexes" as
  explicitly deferred work, and Step 6 gives only a two-line sketch
  (current-menu and price-index tables, a proven full rebuild, refresh owned by
  the Gold module).
- RFC-0001 §D2 describes `current_menu` (latest accepted price per
  `(item, variant)`) and `price_index_*` (median entrée price per H3
  cell/course), but those columns predate ADR-0004/0005: they assume
  `venue_id`/`menu_item_id` in a `canonical`/`mart` split that no longer
  exists. The current model is immutable Menu **aggregates**, Subject-scoped
  content, and the accepted per-`(family, target)` `select_price` selector.
  RFC-0001's Gold columns do not map onto it unchanged.

Concrete decisions with real trade-offs remain open: the grain and columns of
the current-menu table; whether the first unit ships a price index at all (its
by-H3/course aggregation needs the deferred cross-venue item taxonomy per
RFC-0001 §D2/§D7, the `h3-pg`/PostGIS extension per ROADMAP §4.3, and Place
geospatial columns that do not exist yet); whether refresh is a full rebuild or
targeted-incremental (Plan Step 6 / scenario A11 / §8 fitness test require a
proven **full rebuild**, while ROADMAP Phase 6 wants refresh **targeted to the
Establishments that changed**); and whether Gold reuses the accepted pure
selector or reimplements selection precedence in SQL. Per CLAUDE.md, a new
schema pattern on the expensive-to-reverse models/migration path is proposed in
an ADR and stopped for owner review before implementation.

## Decision (proposed)

Ship the first `gold` projection as **current-menu only**, materialized as
ordinary Gold-owned tables that record the accepted `select_price` result for
each current eligible scope and target, rebuilt by a full deterministic refresh
that reads Bronze/Identity/Menu without mutating them. Defer the price index.

The following points are the proposed normative surface for owner review:

1. **First projection is current-menu only; the price index is deferred.**
   RFC-0001 §D2 says start with one view and add aggregates only when an API
   endpoint needs them; Plan Step 6 says Gold "can land with the API work that
   first consumes it." A price index by H3/course additionally depends on the
   deferred cross-venue item taxonomy, the `h3-pg`/PostGIS extension, and Place
   geospatial columns — none present. Introducing them here would be
   "for later" scaffolding and a new-extension dependency decision. The price
   index gets its own unit alongside the price-index API (ROADMAP Phase 7).

2. **Materialization is ordinary `gold` tables refreshed by a Gold-owned task,
   not materialized views** (ADR-0003 reasoning; ADR-0004 refresh ownership).

3. **The refresh contract is a full, deterministic rebuild.** Refresh recomputes
   the projection from Identity + Menu (+ Bronze for provenance columns) and
   replaces the Gold rows; it never writes to or changes an authoritative row.
   A full rebuild after deleting Gold reproduces identical business columns
   (Plan Step 6, scenario A11, §8 "Gold rebuildability"). **Targeted
   incremental refresh is deferred** as an optimization until freshness volume
   justifies it (ROADMAP Phase 6); it is not a correctness requirement and
   ships with the ingest pipeline, not here.

4. **Grain and columns of `gold.current_menu` (review surface).** One row per
   resolved current selection: `(scope_subject_id, scope_subject_kind, target
   identity, effective context, currency)`, carrying the selector's output —
   `amount_minor`, `currency_code`, `price_state` (`priced`/`unknown`/
   `unavailable`), local vs organization `scope`, `source_kind`, `observed_at`,
   `price_confidence`, `evidence_ids`, and the selected content
   (`name`, `description`, content `source_kind`/`observed_at`/`evidence_ids`),
   plus surfaced freshness (`as_of` and a staleness age derived from
   `observed_at`). Money stays integer minor units with a currency FK; no float.
   Facts scoped only to a retired ambiguous predecessor are excluded from the
   current table (ADR-0004 §5). The exact column list, keys, and whether
   separate Organization shared-price claims get their own rows are the owner
   review surface, not settled by this text.

5. **Gold reuses the accepted pure selector as the single definition of
   "current."** The refresh enumerates current eligible scopes and their targets
   and records the deterministic `select_price` result. Selection precedence,
   applicability intersection, tombstone/pin lifecycle, and no-inferred-price
   rules are **not** reimplemented in Gold SQL — one definition of precedence,
   already accepted and tested, avoids a second copy that can drift. Gold
   imports Menu/Identity/Bronze **contracts** only.

6. **Determinism and idempotence.** The business columns in point 4 are
   deterministic functions of committed Bronze/Identity/Menu; a refresh over
   unchanged sources yields byte-identical business columns. Refresh-run
   metadata (`refreshed_at`, any refresh-run surrogate id) is excluded from the
   rebuild-equality comparison (Plan Step 6).

7. **Ownership, imports, FKs, migration.** Schema `gold`; package
   `packages.helios_core.gold`; models registered **only** through
   `packages.helios_core.db.model_registry`; imports published contracts only,
   never provider or vertical ORM. FKs `gold → gold/menu/identity/bronze` with
   `RESTRICT`/`NO ACTION`; no authoritative table references `gold`. When
   implemented, exactly one forward migration after `d83f0a21c592` with
   hand-reviewed, synchronized concrete upgrade/downgrade SQL (no `CASCADE`,
   dependency order) and focused fitness/round-trip tests, per Plan §8.

8. **Explicit non-goals of this ADR and Step 6's first unit.** No API, no price
   index, no H3/geospatial, no `h3-pg`/PostGIS extension use, no cross-venue
   item taxonomy, no targeted incremental refresh, no scheduler, no extraction,
   ML, fuzzy matching, matching-policy change, new runtime dependency, or
   deployment. No change to any accepted Step 5 artifact.

## Alternatives considered

These explain the proposed direction; they are the owner's to accept or redirect.

| Alternative | Benefit | Reason not proposed |
|---|---|---|
| Materialized views for Gold | Declarative refresh, no refresh code | Full recompute per refresh, `ACCESS EXCLUSIVE` locking without `CONCURRENTLY` (which needs a unique index per view), and Alembic manages matviews poorly (ADR-0003). |
| Reimplement selection precedence in Gold SQL | Refresh is one set-based query; no per-target Python loop | Creates a second definition of "current" that can drift from the accepted, tested `select_price`; ADR-0005's precedence/lifecycle rules are intricate and were accepted as the read contract. |
| Ship the price index now | Matches RFC-0001's product framing | Needs deferred cross-venue taxonomy, the `h3-pg`/PostGIS extension, and Place geospatial columns; premature "for later" scaffolding and a separate dependency decision. |
| Targeted incremental refresh as the first contract | Cheaper steady-state refresh | Correctness contract is a proven full rebuild (Plan Step 6 / A11 / §8); targeted refresh is an optimization better sized with real ingest volume (ROADMAP Phase 6). |
| Keep current-menu as a Silver internal projection | No new schema | ADR-0004 reserves consumer-facing read models for Gold; Silver internal projections are implementation details of the authoritative module, and this table exists to serve the API. |

## Consequences

**Easier**

- One accepted definition of "current" (the selector) drives both ad-hoc reads
  and the materialized table.
- "Drop Gold, refresh" is a literal, testable operation; the rebuild-equality
  fitness test (Plan §8) has a clear business-column contract.
- Step 6 lands with no new extension or runtime dependency and no geospatial
  surface to review.

**Harder / accepted costs**

- A full rebuild that calls the pure selector per current scope/target is
  `O(scopes × targets)` selector calls. This is correctness-first; no scale
  claim is made before measurement on real samples. Targeted refresh is the
  named later optimization.
- The first unit refreshes a **bounded, caller-supplied input set** of scopes;
  enumerating "all current eligible scopes and targets" across the catalog is a
  deferred follow-up (see Owner decision), so this unit does not own that query.
- The retired-predecessor exclusion needs a join to Identity lineage/currentness
  at refresh time.
- Staleness is surfaced in the table (`as_of`), not hidden; the API contract for
  it lands with Phase 7.

## Owner decision

Owner Fortune accepted the proposed defaults on 2026-09-19 and answered the five
open questions:

1. **Current-menu only** — accepted; price index deferred to its own unit
   alongside the price-index API.
2. **Full deterministic rebuild** refresh — accepted; targeted incremental
   deferred.
3. **Selector reuse** over SQL reprojection — accepted.
4. `gold.current_menu` **grain/columns** as proposed in Decision point 4 —
   accepted; Organization shared-price claims are materialized in the same table
   with an explicit `scope` (`local`/`organization`), mirroring the selector's
   result (no separate table).
5. **Scope of enumeration — bounded input set (amendment).** The first unit
   projects a caller-supplied bounded input (one or more explicit scopes,
   e.g. an Establishment or Organization); enumerating the full current catalog
   from Identity + Menu is **deferred** to a follow-up alongside the ingest
   materialization refresh (ROADMAP Phase 6). Full-rebuild determinism and
   idempotence (points 3, 6) are proven over that bounded input.

Owner also confirmed (2026-09-19) that the superseded RFC-0001 §D2 Gold column
shape is **disposable** and must not be ported; the new iteration is designed
directly on immutable Menu aggregates and the accepted selector.

This is a real supplied decision, not inferred from tests or this document. It
authorizes the bounded Gold current-menu implementation unit; it does not
authorize the price index, the full-catalog refresh, an API, or any deployment.

## References

- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) — Gold
  lifecycle, ownership, FK direction, retired-predecessor exclusion.
- [ADR-0005](./0005-immutable-menu-snapshots-and-selection.md) — immutable Menu
  snapshots and the selection semantics Gold projects.
- [ADR-0003](./0003-three-layer-schema.md) — why derived read models are
  refreshed tables, not matviews (superseded, reasoning retained).
- [Plan 0002 Step 6](../plans/0002-identity-foundation-before-menu.md#step-6---featdb-add-gold-menu-read-models)
  and §8 Gold rebuildability fitness test.
- [RFC-0001 §D2/§D6/§D7](../rfc/0001-menu-pricing-first.md) — current-menu and
  price-index intent, conflict resolution, deferred item taxonomy.
- ROADMAP §4.3 (data layer), Phase 6 (materialization refresh), Phase 7
  (price-index API).
- `packages/helios_core/domains/menu/selection.py` — the accepted `select_price`
  contract Gold reuses.
- [Integrated M01–M14 acceptance](../reviews/0002-step-5-menu-integrated-m01-m14-acceptance.md).
</content>
</invoke>
