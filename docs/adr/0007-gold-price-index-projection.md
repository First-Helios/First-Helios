# ADR-0007: Gold price-index projection — grain, aggregation, and its blocking dependencies

**Status:** Accepted (target shape) — **implementation deferred to ROADMAP
Phase 6/7. No model, migration, or code until the `course` category axis and
real catalog data exist.**
**Date:** 2026-09-20
**Accepted:** 2026-09-20 by project owner Fortune — adopt the shape below
(lat/lon grid geospatial axis), defer the build.
**Extends:** [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md),
[ADR-0005](./0005-immutable-menu-snapshots-and-selection.md),
[ADR-0006](./0006-gold-menu-read-models.md)
**Implements (proposes):** [Plan 0002 Step 6](../plans/0002-identity-foundation-before-menu.md#step-6---featdb-add-gold-menu-read-models),
the price-index portion; [ROADMAP Phase 7](../../ROADMAP.md#phase-7--api-surface-full-including-the-price-index)

> **ADR-number drift (flagged per CLAUDE.md "the code wins").** ROADMAP still
> forward-references "ADR-0006: Scraper framework choice" (Phase 5) and
> "ADR-0007: Prod hosting choice" (Phase 8). Those were placeholders written
> before ADRs were assigned in creation order; **ADR-0006 was actually assigned
> to the Gold menu read models**, so this price-index ADR takes the next free
> number, **0007**. The scraper-framework and prod-hosting ADRs will take the
> next free numbers when written (0008+). This ADR does not renumber anything;
> it records the divergence for the owner to reconcile in ROADMAP.

## Context

The North Star product is "a trustworthy, queryable **price index** of food in
Austin" (ROADMAP §1). RFC-0001 §D2 and ROADMAP Phase 7 describe it concretely:
`GET /price-index?h3=&course=` returning **median / p25 / p75 price by area and
course, with the sample size**, because "an aggregate over four venues is not an
index and the response should admit that."

**What is already settled and must not be reopened here:**

- Gold is the `gold` schema owned by `packages.helios_core.gold`, holding
  rebuildable read models and aggregates, refreshed by an explicit Gold-owned
  task, never an authoritative write target; Identity correctness never depends
  on Gold ([ADR-0004 §1–2, §5](./0004-modular-monolith-identity-and-lifecycle.md)).
- FK direction: `gold → gold/menu/identity/bronze` with `RESTRICT`/`NO ACTION`;
  no authoritative table references `gold`; Gold reads **published contracts**
  only (ADR-0004 §7).
- Derived read models are ordinary refreshed tables, **not** materialized views
  ([ADR-0003](./0003-three-layer-schema.md) reasoning, carried by ADR-0006).
- One definition of "current" is the accepted pure selector `select_price`;
  Gold reuses it and never re-implements selection precedence in SQL
  ([ADR-0006](./0006-gold-menu-read-models.md) points 5, 8).
- The first Gold projection, `gold.current_menu`, and its bounded and
  full-catalog deterministic refreshes are **implemented and owner-accepted
  (2026-09-20)**. Money is integer minor units with a currency FK; no float.
- ADR-0006 already fixed how the price index must attach: **"a dedicated
  `price_index_*` aggregate table that groups `gold.current_menu` … Aggregation
  is an aggregate table over `current_menu`, not a reshaping of its per-target
  grain, so this deferral costs no rework."** ADR-0006 deferred the price index
  to "its own owner-accepted ADR/decision." **This is that ADR.**

**What is not settled, and is why this ADR exists.** ADR-0006 deferred the price
index because both of its grouping axes lack the data and infrastructure to
compute them, and because introducing them touches an expensive-to-reverse path
(identity models, a new extension dependency) that CLAUDE.md requires be proposed
and stopped for review first:

1. **Geospatial axis (`?h3=`) is absent.** `gold.current_menu` carries no
   location. Its scope subject is an Organization or Establishment
   (`subject_id`/`subject_kind`). To place an Establishment on the map the
   refresh must join `identity.establishment → identity.place`, and `place`
   today has `latitude`/`longitude` as `Numeric(9,6)` but **no H3 cell column,
   no spatial index, and no PostGIS `GEOGRAPHY`/`GEOMETRY`**. Computing an H3
   cell from lat/lng needs an H3 function that does not exist in this database:
   the `h3-pg` extension named in ROADMAP §4.3 is **not installed**, and the
   only alternative is a new application-side `h3` runtime dependency. Either is
   a stop-and-ask dependency decision (CLAUDE.md). Organization-scoped priced
   rows (shared chain prices) have **no Place at all** and cannot be geolocated
   without a fan-out that ADR-0005 forbids (copying an org price to every
   location).

2. **Category axis (`?course=`) is absent from Gold.** RFC-0001 §D2 aggregates
   by `course` (+ section heuristics) as the V1-adequate proxy and **defers a
   true cross-venue item taxonomy** ("1/2 lb Angus Burger" ≈ "cheeseburger") to
   a future RFC (D2, D7). But ADR-0006's owner decision **deliberately did not
   project `course`/`dietary_tags` into `gold.current_menu`**, because
   `menu.menu_section.course` and `menu.menu_item.dietary_tags` "are not reliably
   populated yet" — and they cannot be until the extraction ladder (ROADMAP
   Phase 3) exists to fill them. There is therefore no reliable grouping column
   on which a "median entrée price" can be computed today.

3. **No source data to aggregate.** No discovery, scraping, extraction, or
   ingest is built. `gold.current_menu` is exercised only on disposable
   fixture data. An index over an empty or fixture catalog is not a product; it
   is scaffolding — exactly what CLAUDE.md prohibits building "for later."

Concrete decisions with real trade-offs remain open: the aggregate grain and
columns; which statistics and how honestly small samples are reported; how the
area key is defined and computed (and therefore which new dependency, if any, is
accepted); how Organization-scope rows are handled; and — the gating question —
**whether any of it should be implemented before its inputs exist.** Per
CLAUDE.md, this is proposed in an ADR and stopped for owner review before any
model, migration, or code.

## Decision (proposed)

Adopt the **target shape** of the price index now so the future unit is
unambiguous, and **gate its implementation** on the two blocking inputs actually
existing. Concretely: do **not** write the model, migration, or refresh in this
step; fix the contract below, and implement it only after (a) an owner decision
on the geospatial dependency and (b) real extraction populates a category axis
and geocodes Places. The following points are the proposed normative surface for
owner review — accept, amend, or redirect.

1. **A single `gold.price_index` aggregate table over `gold.current_menu`.** It
   reads only the already-accepted projection — never Menu, the selector, or raw
   observations directly — so selection precedence stays defined exactly once
   (ADR-0006 point 5). It is an aggregate **over** `current_menu`, not a
   reshaping of its per-target grain (ADR-0006 deferred-tags note). It is an
   ordinary Gold-owned refreshed table, not a materialized view (ADR-0003).

2. **Grain (review surface).** One row per
   `(area_key, area_kind, category_key, category_kind, currency_code, as_of
   window)`. `area_kind` and `category_kind` name the dimension vocabulary in
   use (e.g. `h3_r8` / `course`) so the table can carry more than one
   resolution or category scheme without a grain change. Only `price_state =
   'priced'` rows of `current_menu` contribute; non-priced states
   (`unknown`/`unavailable`/`absent`/…) are counted separately for honesty but
   never enter a percentile.

3. **Aggregation and money.** Per group: `sample_size` (contributing priced
   targets), `distinct_venue_count` (distinct Establishments), `median_minor`
   (p50), `p25_minor`, `p75_minor`, `min_minor`, `max_minor` — all integer
   currency minor units, computed with Postgres `percentile_cont`/`percentile_disc`
   (**no extension required for percentiles**), plus surfaced freshness
   (`as_of`, and the oldest/most-stale contributing `observed_at`). No float
   anywhere near a price (Phase 1 reviewer's checklist).

4. **Sample-size honesty is part of the contract, not the API layer.** Groups
   below a **minimum sample threshold** (proposed default: `sample_size` and
   `distinct_venue_count` each ≥ a small N, e.g. 5 — the exact number is a
   review surface) are either omitted or flagged `low_confidence`, so "an
   aggregate over four venues" cannot be served as an index (ROADMAP Phase 7).
   The threshold is a stored policy value, not a magic constant.

5. **Geospatial dependency — RESOLVED by owner: lat/lon grid, no H3.** Owner
   Fortune decided (2026-09-20) to drop H3 and use lat/lon directly. This
   collapses the dependency: `identity.place` **already carries**
   `latitude`/`longitude` (`Numeric(9,6)`), so there is **no new runtime
   dependency** (no `h3-pg`, no python `h3`, no PostGIS geometry) and **no
   `identity.place` migration** — the columns exist. Because a percentile
   aggregate must group by an *area bucket* (raw float points never repeat and
   cannot be grouped), `area_key` is a **rounded/truncated lat/lon grid cell**,
   e.g. `area_kind = 'latlon_grid_0p01'` with `area_key` = `"<lat>,<lon>"` at
   ~0.01° (~1.1 km) resolution — pure arithmetic in the refresh, indexable as a
   plain string or two `Numeric` columns, no extension, no PostGIS needed for
   either computing or querying it. **Grid precision is a tunable policy value,
   not a structural decision** (review surface: 0.01° proposed). Query-time
   radius/bbox is still possible later on the same lat/lon without changing this
   table. **Organization scope:** unchanged by this decision — org-scoped rows
   have no Place, so they are excluded from the geo (`latlon_grid_*`) index;
   a non-geo aggregate, if wanted, is a separate `area_kind` (e.g. `all`), never
   a fan-out (ADR-0005 point 11).

6. **Taxonomy dependency (blocking).** The `category_key` is `course` (the
   V1-adequate proxy, RFC-0001 §D2), **not** a cross-venue item taxonomy, which
   stays a future RFC (D2, D7; ADR-0006). Implementing the index therefore
   depends on `course` first being (a) reliably populated in `menu` by real
   extraction and (b) **projected into `gold.current_menu` as an additive
   column** — its own small unit, exactly as ADR-0006's deferred-tags note
   anticipated (a `canonical_tags`/category column plus this aggregate table,
   "no grain rework"). When a real cross-venue taxonomy later exists, it arrives
   as another `category_kind` over the same table, not a redesign.

7. **Ownership, imports, FKs, migration (when implemented).** Schema `gold`;
   package `packages.helios_core.gold`; model registered **only** through
   `packages.helios_core.db.model_registry`; imports published contracts only.
   FKs `gold → gold/menu/identity/bronze` with `RESTRICT`/`NO ACTION`; **no**
   authoritative table references `gold`. Area/category keys are value columns
   (H3 string, course string), not FKs; a currency FK to `menu.currency` is the
   likely only FK. Any schema change is **exactly one forward migration after
   the current gold head `5f3a9c1e7b24`** with hand-reviewed, synchronized
   concrete upgrade/downgrade SQL (no `CASCADE`, dependency order) and focused
   fitness/round-trip/rebuildability tests (Plan §8). Refresh is a full
   deterministic rebuild over `current_menu` (targeted-incremental deferred,
   ADR-0006 point 3).

8. **Recommended disposition: adopt the shape, defer the build.** Because both
   inputs are absent and no catalog data exists, the recommendation is **not to
   implement in this step.** This ADR fixes the shape and the dependency
   contract so the work is de-risked; implementation lands in ROADMAP Phase 6/7
   alongside real ingest and the price-index API, after the owner has decided
   the geospatial dependency and extraction has produced a real `course` axis
   and geocoded Places. Building it now would be speculative scaffolding over
   fixtures and would force a premature extension/dependency decision.

9. **Explicit non-goals of this ADR.** No API, no cross-venue item taxonomy, no
   new runtime dependency **decided here** (the geospatial options are presented
   for the owner to choose, not adopted), no `h3-pg`/PostGIS install, no change
   to `gold.current_menu`, the selector, or any accepted Step 5/Step 6 artifact,
   no extraction, ML, fuzzy matching, matching-policy change, scheduler, or
   deployment.

## Alternatives considered

These explain the proposed direction; they are the owner's to accept or redirect.

| Alternative | Benefit | Reason not proposed / trade-off |
|---|---|---|
| **Implement the price index now** | Matches the product framing; visible progress | Category axis is still absent (no `course` in Gold, extraction unbuilt) and there is no catalog data; it would aggregate fixtures — "for later" scaffolding CLAUDE.md prohibits. |
| **Area key via lat/lon grid — CHOSEN (owner, 2026-09-20)** | No new dependency, no `identity.place` migration (lat/lon exist), no extension/PostGIS; pure arithmetic, indexable | Grid is a coarser area than H3's hierarchy; acceptable — RFC/ROADMAP only need area-bucketed percentiles, and precision is tunable. |
| **Area key via `h3-pg` extension** | H3 cell computed in SQL; matches ROADMAP §4.3 intent | **Not chosen** — owner dropped H3. `h3-pg` is not installed; would be a new service-grade dependency (stop-and-ask) needing a CI-image change. |
| **Area key via python `h3` library at refresh** | No PG extension | **Not chosen** — owner dropped H3. New runtime dependency (stop-and-ask). |
| **Area key via PostGIS `GEOGRAPHY` + `ST_*`** | Radius/polygon queries, richer geo | **Not chosen** — heavier than needed; percentile-by-bucket needs only lat/lon arithmetic + a string/`Numeric` key. |
| **No geospatial axis first (category-only index)** | Avoids the geo dependency entirely | The product is explicitly area × category; a category-only "index" across the whole metro is barely more than `current_menu` and does not answer "78704 prices." Still blocked on `course`. |
| **Aggregate raw `amount_minor` with no category axis** | Trivial to compute today | "Median price of any menu item in an area" mixes entrées with sodas and modifiers — statistically meaningless; violates the sample/honesty intent. |
| **Cross-venue item taxonomy now** (true "cheeseburger" grouping) | The ideal index dimension | Explicitly deferred to a future RFC (RFC-0001 §D2/§D7, ADR-0006); no source data, needs a controlled vocabulary — out of scope. |
| **Materialized view for the aggregate** | Declarative refresh | Same reasons ADR-0003/0006 rejected matviews for Gold: full recompute, `ACCESS EXCLUSIVE` locking, poor Alembic support. |
| **Fan out Organization prices to member Establishments for geo coverage** | More "priced" venues on the map | ADR-0005 point 11 forbids inventing a location price the source did not assert; would pollute the index. |

## Consequences

**Easier**

- The price index has a decided target shape and an explicit dependency
  contract; the future implementation unit is unambiguous and small.
- Adding it later is genuinely additive: an aggregate table over `current_menu`
  plus a `course` column projection, "no grain rework" (ADR-0006).
- No premature extension/dependency decision is forced; the owner chooses the
  geospatial approach deliberately, with the trade-offs written down.

**Harder / accepted costs**

- The flagship product remains unbuilt until discovery and extraction land (to
  populate the `course` axis and geocode Places) — this ADR does not accelerate
  that; it de-risks it. The geospatial dependency is now resolved and adds
  nothing: lat/lon already exists on `identity.place`.
- The lat/lon grid is a coarser, non-hierarchical area than H3 would have been;
  changing resolution later is a policy/refresh change (recompute `area_key`),
  not a schema change, since it stores rounded coordinates, not a fixed cell id.
- Organization-scoped shared prices are excluded from the geo index by the
  proposed policy; if the owner wants them represented, that is an explicit
  additional decision (a non-geo `area_kind`), not a silent fan-out.
- A full-rebuild aggregate over `current_menu` is `O(rows)` per refresh; no
  scale claim is made before measurement (consistent with ADR-0006).

## Owner decision

**Decided (owner Fortune, 2026-09-20): adopt the target shape, defer the build.**

- **Q1 Adopt shape / defer build — DECIDED: adopt the shape, defer the build**
  to ROADMAP Phase 6/7. No `gold.price_index` model, migration, or refresh is
  written now. The shape (Decision points 1–7) is the accepted target so the
  future unit is unambiguous.
- **Q2 Geospatial dependency — DECIDED: use lat/lon, drop H3.** Recorded in
  Decision point 5: `area_key` is a rounded lat/lon grid cell over the existing
  `identity.place` lat/lon; **no new dependency, no `h3-pg`/PostGIS, no
  `identity.place` migration.**

Deferred with the build (settle when implementation is authorized):

- **Q3 Category axis:** `course` is the intended V1 proxy; projecting `course`
  into `gold.current_menu` is a prerequisite unit, itself **blocked on
  extraction** (ROADMAP Phase 3). Cross-venue taxonomy remains a future RFC.
- **Q4 Grain / statistics / minimum sample threshold** (Decision points 2–4,
  incl. grid precision, 0.01° proposed) — confirm at implementation time.
- **Q5 Organization-scope handling** — exclusion from the geo index proposed;
  confirm at implementation time.

These are real supplied decisions, not inferred from tests or this document.
They authorize **no** model, migration, or code — the build stays gated on the
`course` category axis (extraction) and real catalog data. When those inputs
exist, implementation lands under this accepted shape as its own reviewed unit.

## References

- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) — Gold
  lifecycle, ownership, FK direction, retired-predecessor exclusion.
- [ADR-0005](./0005-immutable-menu-snapshots-and-selection.md) — immutable Menu
  snapshots; no-inferred-price rule (point 11) that forbids org→location fan-out.
- [ADR-0006](./0006-gold-menu-read-models.md) — `gold.current_menu`; the
  deferred-tags note fixing the price index as an aggregate table over it; the
  deferral of the price index to this ADR.
- [ADR-0003](./0003-three-layer-schema.md) — why Gold read models are refreshed
  tables, not matviews (superseded, reasoning retained).
- [RFC-0001 §D2/§D6/§D7](../rfc/0001-menu-pricing-first.md) — `price_index_*`
  intent (median by H3/course, sample size), conflict resolution, and the
  deferred cross-venue item taxonomy.
- [Plan 0002 Step 6](../plans/0002-identity-foundation-before-menu.md#step-6---featdb-add-gold-menu-read-models)
  and §8 fitness tests (Gold rebuildability, FK direction, import direction).
- ROADMAP [§4.3](../../ROADMAP.md#43-data-layer) (data layer, names `h3-pg`),
  [Phase 6](../../ROADMAP.md#phase-6--ingest-pipeline--freshness) (materialization
  refresh), [Phase 7](../../ROADMAP.md#phase-7--api-surface-full-including-the-price-index)
  (price-index API).
- `packages/helios_core/gold/models.py` — the `gold.current_menu` shape this
  index aggregates over.
- `packages/helios_core/identity/models.py` — `Place` (lat/lng, no H3/PostGIS),
  `Establishment` (Place/Organization join path).
- `packages/helios_core/domains/menu/selection.py` — the accepted `select_price`
  contract, reused transitively via `current_menu`, never re-implemented.
</content>
</invoke>
