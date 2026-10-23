# ADR-0007: Gold price-index projection — grain, aggregation, and its blocking dependencies

**Status:** Accepted (target shape), as amended by
[Amendment 1](#amendment-1-2026-09-30-first-slice-built-before-the-course-axis):
the first slice (table, migration, refresh, CLI) is built with an `all` category
only; the `course` axis follows. The API is authorized by
[Amendment 2](#amendment-2-2026-10-01-the-price-index-api).
[Amendment 3](#amendment-3-2026-10-22-area-kinds-and-the-cell-list) (the `all` and 0.05°
area kinds, `GET /v1/price-index/cells`) is **Accepted** (2026-10-22, P8-4), not built yet.
**Date:** 2026-09-20
**Accepted:** 2026-09-20 by project owner Fortune — adopt the shape below
(lat/lon grid geospatial axis), defer the build.
**Extends:** [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md),
[ADR-0005](./0005-immutable-menu-snapshots-and-selection.md),
[ADR-0006](./0006-gold-menu-read-models.md)
**Implements (proposes):** [Plan 0002 Step 6](https://github.com/First-Helios/First-Helios/blob/f77292a0fecfc8f5e100b3705dc0cf9ae4a4d548/docs/plans/0002-identity-foundation-before-menu.md#step-6---featdb-add-gold-menu-read-models),
the price-index portion; [ROADMAP Phase 7](../../ROADMAP.md#phase-7--api-surface-full-including-the-price-index)

> **ADR-number drift (flagged per CLAUDE.md "the code wins").** ROADMAP still
> forward-references "ADR-0006: Scraper framework choice" (Phase 5) and
> "ADR-0007: Prod hosting choice" (Phase 8). Those were placeholders written
> before ADRs were assigned in creation order; **ADR-0006 was actually assigned
> to the Gold menu read models**, so this price-index ADR takes the next free
> number, **0007**. The scraper-framework and prod-hosting ADRs will take the
> next free numbers when written. This ADR does not renumber anything;
> it records the divergence for the owner to reconcile in ROADMAP.
> *Resolved in S16 (2026-09-28): ROADMAP no longer carries planned ADR numbers;
> [README.md](../../README.md#decisions) is the ADR index.*

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

## Implementation notes (2026-09-28)

- Context, alternatives and References cite ROADMAP §4.3 as naming `h3-pg`; §4.3 no longer does
  (H3 dropped per ADR-0009).
- "Extraction ladder (ROADMAP Phase 3)": menu extraction is now ROADMAP Phase 5, per Proposed
  [ADR-0013](./0013-phase5-menu-pipeline.md).

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
- [Plan 0002 Step 6](https://github.com/First-Helios/First-Helios/blob/f77292a0fecfc8f5e100b3705dc0cf9ae4a4d548/docs/plans/0002-identity-foundation-before-menu.md#step-6---featdb-add-gold-menu-read-models)
  and §8 fitness tests (Gold rebuildability, FK direction, import direction).
- ROADMAP [§4.3](../../ROADMAP.md#43-data-layer) (data layer, names `h3-pg`),
  [Phase 6](../../ROADMAP.md#phase-6--monthly-runs--freshness) (materialization
  refresh), [Phase 7](../../ROADMAP.md#phase-7--api-surface-full-including-the-price-index)
  (price-index API).
- `packages/helios_core/gold/models.py` — the `gold.current_menu` shape this
  index aggregates over.
- `packages/helios_core/identity/models.py` — `Place` (lat/lng, no H3/PostGIS),
  `Establishment` (Place/Organization join path).
- `packages/helios_core/domains/menu/selection.py` — the accepted `select_price`
  contract, reused transitively via `current_menu`, never re-implemented.

## Amendment 1 (2026-09-30): first slice built before the course axis

Owner decisions in session G-1, before any code. Facts checked first:
`menu.menu_section.course` is never written (ADR-0013 Amendment 7 item 6 reads no
course or tags); own-site menu pages are Organization-scoped (ADR-0013 Amendment 3);
discovery mints one Organization per Establishment, so chains are several
Organizations whose menu-URL records name the same URL; nothing called
`refresh_full_catalog`. Code: `packages/helios_core/gold/models.py` (`PriceIndex`),
`gold/price_index.py`, `identity/contracts.py` (`current_venue_locations`),
`apps/gold/refresh.py`; migration `7c2e4b9d1f3a`.

1. **Build now, `all` category first (amends point 8 and Q3).** The slice is
   `gold.price_index`, one migration, a full-rebuild refresh and an owner-run CLI;
   no API. `category_kind` is `all` (every priced item and variant in the cell),
   keyed so `course` arrives as another `category_kind` without a grain change.
   The course label is its own follow-up unit: an ADR comparing a classifier (e.g.
   the page classifier's embedding with a logistic regression over section names)
   against a section-name baseline on labelled sections, then a course projection.
   The price-index API (ROADMAP Phase 7) is not authorized by this amendment.
2. **Venue-weighted statistics (amends point 3).** Per group, each venue's sample
   is the median of its priced rows; p25/median/p75/min/max are over those venue
   medians. Both steps use `percentile_disc`, so every value is an observed integer
   amount (the lower middle for an even count). `venue_count` is the sample size;
   `priced_count`/`unpriced_count` record the rows behind it. Duplicate rows of one
   venue (an `llm` and a `jsonld` stream, several platform pages, variants) and
   menu size no longer skew the index.
3. **Grain and inputs (confirms point 2).** One row per `(area_kind, area_key,
   category_kind, category_key, currency_code)`; a current snapshot only, with
   `effective_instant` as its as-of (`current_menu` rejects history requests, so
   there is no as-of history). Only `item` and `variant` targets count: modifiers
   are add-on amounts and section prices are shared.
4. **Grid and threshold (confirms point 4 and Q4).** `area_kind =
   'latlon_grid_0p01'`; a point's cell is floored to its south-west corner, stored
   as `cell_lat`/`cell_lon` and `area_key` `"<lat>,<lon>"` (e.g. `30.26,-97.75`).
   `min_venues = 5`, stored per row. Groups below it are kept with
   `low_sample = true`; a group whose rows are all non-priced is kept with
   `venue_count = 0` and NULL statistics, so coverage gaps stay visible.
5. **Organization scope (amends point 5 and Q5).** An Organization-scoped family
   (scope Subject, source record) is placed at its Organization's only current
   operating Establishment (current Organization and Place, not closed,
   `valid_from <= E < valid_to`) when that Establishment's Place has a point, unless
   the menu URL its price Evidence was read from is also read by another placed
   venue's Organization family. Shared (chain or platform) menus are left out and
   counted (`shared_menu_url`), never fanned out; an Organization with several
   current Establishments is left out (`no_single_venue`). This is index-only
   attribution: `current_menu` and Menu still carry the price as an Organization
   claim (ADR-0005 §11). The URL check sees only families in the current catalog,
   so a chain with one extracted location is placed at that location.
   *Follow-up proposed:* scope own-site pages to the Establishment upstream (the
   platform-page rule of ADR-0013 Amendment 3 applied to `<gers>` records), as an
   ADR-0013 amendment once the open P5-5 branch merges; the Gold rule then finds
   little left to attribute and needs no rework.
6. **Refresh trigger.** `python -m apps.gold.refresh [--as-of ISO-8601]` rebuilds
   `current_menu` (full catalog) and then the index at the same instant with one
   `refreshed_at`, in one transaction. The owner runs it after an extraction run;
   scheduling stays with ROADMAP Phase 6.
7. **Version-local keys (ADR-0013 Amendment 7 item 5).** The index aggregates
   current heads, so a new Version's new targets replace the old ones in the next
   snapshot; nothing double counts. What is lost is dish identity across Versions:
   the index has no dish-level history. `Unsectioned` items never reach Gold, so
   they are not in the index either.
8. **Point 7 updates.** The migration follows the head of the day, `5a91ef3ff9d8`,
   not `5f3a9c1e7b24`. Gold reads Identity through the new read-only
   `current_venue_locations` contract and Bronze through the existing
   `source_endpoint_for_evidence`; the only FK is to `menu.currency`.

## Amendment 2 (2026-10-01): the price-index API

Owner decisions in session G-5, before any code. Amendment 1 §1 did not
authorize the API; this does, for `GET /v1/price-index` (ROADMAP Phase 7) over
the `gold.price_index` table as built. Read path only: no model, migration or
dependency. Code: `packages/helios_core/gold/price_index_read.py`,
`apps/api/routes/price_index.py`, `apps/api/schemas.py`.

1. **Area: a point selects its cell.** `lat` and `lon` are required. The API
   floors them with the refresh's own `grid_cell`, so a point lands in the cell
   the refresh would place a venue at that point in. The query is equality on
   `uq_gold_price_index`'s leading `(area_kind, area_key)`, so it is
   index-backed with no new index. Bounding-box or all-cells listing is a later,
   additive endpoint.
2. **One bounded response, 200 when empty.** The body is the cell (`area_kind`,
   `area_key`, south-west corner `cell_lat`/`cell_lon`, `cell_size_degrees`),
   `as_of` and `items`, one per category and currency the index holds for the
   cell. There is no pagination: a cell has one row today, and about nine once
   courses arrive (ADR-0016 §6). A cell with no row is `200` with `items: []`
   and `as_of: null`. No coverage is an answer, not a missing resource.
3. **Every honesty field is served.** Each item carries `venue_count`,
   `min_venues`, `low_sample`, `organization_venue_count`, `priced_count`,
   `unpriced_count`, the five statistics in integer minor units, and
   `oldest_observed_at`/`newest_observed_at`. Low-sample and all-unpriced rows
   are served with their flags; nothing is hidden. `age_seconds` is the oldest
   observation's age at request time, never negative.
4. **`as_of` is the index's `effective_instant`.** The rebuild writes one
   instant for every row, so this is the cell's as-of.
5. **Optional filters and validation.** `category_kind` (`all` today) and
   `currency` (`USD` today) narrow the items. Both are enums that widen as
   values arrive, starting with `course` (ADR-0016 §6). Response fields stay
   strings, so the new values don't change the response schema. `lat` outside
   [-90, 90], `lon` outside [-180, 180], a missing coordinate, NaN or infinity,
   or an unknown filter value returns `422 validation_error`. The API has no
   Austin bounding box.
6. **Negative zero.** `grid_cell` now maps a `-0` input to `0`. A float query
   parameter can be `-0.0`, and Postgres `numeric` has no negative zero, so the
   API never looks up a `-0.00` key the refresh cannot write.

## Amendment 3 (2026-10-22): area kinds and the cell list

**Status: Accepted 2026-10-22 by the owner, OQ1–OQ5 as recommended (see
[Owner decision](#owner-decision-amendment-3)); not built yet.** Proposed 2026-10-22 (session
P8-4). It is [ADR-0019](./0019-public-v1-site.md) §5 build step 3, which the owner's ADR-0019 Q3
answer approved in direction only ("this answer approves the direction, not unseen migration
SQL"); OQ5 now approves the SQL below.

**Answered before drafting** (owner, 2026-10-22, P8-4 prompt, all as recommended):

- **Q1** `all` row storage: nullable `cell_lat`/`cell_lon`, with a CHECK that they are null if
  and only if `area_kind = 'all'`.
- **Q2** `all` venue set: the same placement as the cells, so the `all` row is the sum of the
  cells.
- **Q3** default `area_kind` on the existing endpoints: `latlon_grid_0p01`, unchanged.
- **Q4** `/v1/venues` with `area_kind=all`: every placed venue.
- **Q5** session scope: this proposal only, then stop for review.
- **Q6** `helios_laptop`: upgrade and refresh in the build session (a `pg_dump` first).

### The gap

`gold.price_index` holds one `area_kind`, `latlon_grid_0p01` (Amendment 1 §4). On
`helios_laptop` 97.0% of its 267 cells are `low_sample`, and only 79 of 472 placed venues sit in
a cell with at least 5 venues (P8-1 record, addendum A.1). The API reads one cell at a time, by
point (Amendment 2 §1). It has no citywide figure and no way to list cells. ADR-0019 §3 (owner
Q3) settles the direction: a citywide `all` row and a 0.05° grid next to the 0.01° rows, a
cell-listing endpoint, and an optional `area_kind` on `/v1/price-index` and `/v1/venues`.

### Proposed shape

1. **Three area kinds.** `AREA_KINDS = ("latlon_grid_0p01", "latlon_grid_0p05", "all")`.
   Each grid kind has a step: 0.01° and 0.05°. `all` has none. The policy stays as Amendment 1
   §4 set it: a grid key is the cell's south-west corner, floored, printed with two decimals
   (`"30.25,-97.75"` at 0.05°). Because 0.05 is a multiple of 0.01 and both grids are floored
   from 0, each 0.01° cell sits inside exactly one 0.05° cell. A key such as `30.25,-97.75` is
   valid at both steps; `30.26,-97.75` is valid only at 0.01°. `area_kind` always says which
   grid a key means.
2. **The `all` row (Q1).** `area_key = 'all'`; `cell_lat` and `cell_lon` are NULL. Both columns
   become nullable. A new CHECK, `ck_gold_price_index_area`, requires null coordinates and the
   `all` key for `all`, and both coordinates for a grid kind. The existing
   `ck_gold_price_index_cell` (coordinate range) stays as it is; a NULL passes it.
3. **Placement and `min_venues` (Q2).** The refresh runs `_place` once, as today. Each kept
   placement counts in three rows: its 0.01° cell, its 0.05° cell and `all`. Venue weighting,
   `percentile_disc`, the item/variant filter and the shared-menu exclusion (Amendment 1 §2, §3,
   §5) are the same for every kind. `min_venues = 5` (`MIN_VENUES`) for every kind, stored per
   row as now. A venue has one location, so it sits in exactly one cell per grid. For each
   category and currency, `venue_count`, `organization_venue_count`, `priced_count` and
   `unpriced_count` of the `all` row equal the sums over either grid's rows, and each 0.05° row's
   counts equal the sums over the 0.01° rows inside it. The statistics are not sums: each row's
   percentiles are over the venue medians of its own venue set. Shared chain menus stay out of
   `all` too (469 families on `helios_laptop`), so `all` is "every placed venue", not every
   priced menu.
4. **One rebuild.** `refresh_price_index` deletes the table and inserts the three kinds in one
   transaction, with one `effective_instant` and one `refreshed_at` (Amendment 1 §6). The
   aggregate SQL runs once per kind over the same placements; only the key, coordinates and
   `area_kind` parameters differ. `grid_cell` takes the step (default 0.01°, so current callers
   are unchanged). `PriceIndexReport.rows` counts the rows of all three kinds.
5. **Read contract.** `price_index_cell` takes an `area_kind` (grid kinds only; default
   0.01°) and floors the point at that kind's step. A new `price_index_cells(session, area_kind,
   *, category_kind, currency_code, after, limit)` returns one page of rows of one kind, each
   with `area_key`, `cell_lat`, `cell_lon` and the group fields of `PriceIndexRow`. No ORM
   object leaves the module, as now.
6. **`GET /v1/price-index/cells`.** It lists every row of one `area_kind`.
   - Params: `area_kind` (`latlon_grid_0p01` default, `latlon_grid_0p05`, `all`),
     `category_kind`, `currency` (as on `/v1/price-index`), `limit` (default 50, cap 200, ADR-0008
     §3) and `cursor`.
   - Order: `(area_key, category_kind, category_key, currency_code)` ascending. Under a fixed
     `area_kind` that is the unique grain, so the order is total. It is text order, not map
     order, and clients must not read geography into it.
   - Cursor: unpadded base64url over compact JSON `[area_key, category_kind, category_key,
     currency_code]` of the page's last row. Only the canonical encoding decodes (as with
     `item_id`, ADR-0018), and each string must fit its column. Anything else is
     `400 invalid_cursor`. The cursor does not carry the filters; a client sends the same
     filters with every page, as on `/v1/venues`. It is a business key, not a row id, so it
     survives a refresh: the next page continues after that key in the new snapshot, and each
     page's `as_of` says which snapshot it came from.
   - Query: `WHERE area_kind = :k AND (area_key, category_kind, category_key, currency_code) >
     (:cursor) [AND category_kind = :c] [AND currency_code = :u] ORDER BY … LIMIT :limit + 1`.
     It is a range scan on `uq_gold_price_index`, whose leading columns are exactly these. On
     `helios_laptop` today, `EXPLAIN` gives an Index Only Scan on `uq_gold_price_index` with the
     row comparison in the Index Cond, with sequential scans on or off. No new index.
   - Response (`PriceIndexCellList`): `area_kind`, `cell_size_degrees` (0.01, 0.05, or null for
     `all`), `as_of` (the earliest `effective_instant` on the page; null when `items` is empty),
     `items` and `next_cursor` (null on the last page). Each item is a `PriceIndexCellResponse`:
     `area_key`, `cell_lat`, `cell_lon` (null for `all`) and every `PriceIndexGroupResponse`
     field, `age_seconds` included. An empty result is `200` with `items: []`. Unknown
     `area_kind`, `category_kind` or `currency`, and `limit` outside 1–200, are
     `422 validation_error`.
   - ADR-0019 §3 put the cell size on each item. It is the same for every item of a page, so it
     moves to the top level next to `area_kind` (open question OQ3).
   - Size today: 267 rows at 0.01° (2 pages at `limit=200`), 83 at 0.05° (1 page), 1 for `all`.
7. **`area_kind` on `GET /v1/price-index` (Q3).** Optional, default `latlon_grid_0p01`, so
   current clients see no change. `latlon_grid_0p05` floors the point at 0.05°, and the response
   carries that kind, key and `cell_size_degrees: 0.05`. `all` is `422` (OQ1): the citywide row
   is read from `/cells?area_kind=all`, and `PriceIndexResponse` keeps non-null cell fields.
8. **`area_kind` on `GET /v1/venues` (Q3, Q4).** Optional, default `latlon_grid_0p01`; it
   says which grid `area` is a key of.
   - A grid kind: `area` must be canonical at that kind's step (it round-trips through
     `grid_cell` at that step); otherwise `422`. `30.26,-97.75` is `422` under
     `latlon_grid_0p05`. The predicate is the half-open cell range at that step on
     `ix_place_latitude_longitude`, as ADR-0018 built it for 0.01°.
   - `all` (Q4): `area` must be `all` (OQ2), and the predicate is "the Place has a point"
     (`latitude` and `longitude` not null). On `helios_laptop` every one of the 9,996 current
     venues has a point, so today this equals the unfiltered list.
   - `area_kind` without `area` is `422` (OQ2): a kind alone names no area.
   - The list is geographic: every current venue whose point is in the area, not the index's
     contributors. The 0.05° cell `30.25,-97.75` lists 1,660 venues (175 with `has_menu`)
     against `venue_count` 95. ADR-0018 already has the same gap at 0.01° (`30.26,-97.75`: 356
     listed, 45 with a menu, 24 in the index).
9. **OpenAPI.** New path, two new schemas, a new `AreaKind` enum (and `GridAreaKind` for
   `/v1/price-index`), and one new optional param on each existing path. Nothing existing is
   removed or narrowed. The snapshot is regenerated.

### Migration

One revision after `c95d883737db`; `gold.price_index` only. No row is rewritten. The upgrade
checks the existing rows (all `latlon_grid_0p01` with coordinates) against the new CHECKs in
one `ACCESS EXCLUSIVE` statement over 267 rows. Hand-written SQL:

```sql
-- upgrade
ALTER TABLE gold.price_index
    DROP CONSTRAINT ck_gold_price_index_area_kind,
    ALTER COLUMN cell_lat DROP NOT NULL,
    ALTER COLUMN cell_lon DROP NOT NULL,
    ADD CONSTRAINT ck_gold_price_index_area_kind
        CHECK (area_kind IN ('latlon_grid_0p01', 'latlon_grid_0p05', 'all')),
    ADD CONSTRAINT ck_gold_price_index_area CHECK (
        (area_kind = 'all' AND area_key = 'all' AND cell_lat IS NULL AND cell_lon IS NULL)
        OR (area_kind <> 'all' AND cell_lat IS NOT NULL AND cell_lon IS NOT NULL)
    );

-- downgrade
DELETE FROM gold.price_index WHERE area_kind <> 'latlon_grid_0p01';
ALTER TABLE gold.price_index
    DROP CONSTRAINT ck_gold_price_index_area,
    DROP CONSTRAINT ck_gold_price_index_area_kind,
    ALTER COLUMN cell_lat SET NOT NULL,
    ALTER COLUMN cell_lon SET NOT NULL,
    ADD CONSTRAINT ck_gold_price_index_area_kind CHECK (area_kind IN ('latlon_grid_0p01'));
```

The downgrade deletes the 0.05° and `all` rows. They are Gold rows that the old code can neither
store nor read, and a refresh under the old code rebuilds the table (ADR-0004 §1; OQ4). The 0.01°
rows stay valid. No `CASCADE`; nothing references `gold.price_index`.

Checked on a disposable `helios_p84_test` (migrated to `c95d883737db`, then dropped). Dropping
and re-adding the same-named constraint in one `ALTER TABLE` works. The new CHECKs accept one
row of each kind, and reject `all` with coordinates, `all` with one coordinate, `all` with key
`x`, a 0.05° row without coordinates, a 0.01° row with one, and an unknown kind
(`latlon_grid_0p10`). After the downgrade, the 0.01° row remains, both columns are NOT NULL again,
and the CHECK reads `area_kind = 'latlon_grid_0p01'`. The model changes to match:
`cell_lat`/`cell_lon` become `Mapped[Decimal | None]`, `AREA_KINDS` widens, and the new
`CheckConstraint` is declared, so `alembic check` stays clean.

### Expected figures (measured read-only, 2026-10-22)

From `helios_laptop` at `c95d883737db`, Gold as of the P8-3 refresh (`effective_instant`
2026-10-22T16:06:20Z; 54,318 `current_menu` rows; 267 `price_index` rows, all 0.01°, `all`, USD,
none all-unpriced). The session ran with `default_transaction_read_only=on` (also in
`PGOPTIONS`), inside `BEGIN READ ONLY`. It ran the refresh's own `_place` at that instant and the
SELECT half of its aggregate SQL, with no INSERT, once per kind. The recomputed 0.01° rows equal
the stored 267 rows field by field, which checks the method. Placement: 946 families, 477
placed (459 via Organization), 469 shared-menu, 0 `no_single_venue`, 0 `no_evidence`.

| Kind | Rows (cells) | `low_sample` | Share low | Venues | Venues in cells with ≥ 5 | Largest cell |
|---|---:|---:|---:|---:|---:|---:|
| `latlon_grid_0p01` (built) | 267 | 259 | 97.0% | 472 | 79 (16.7%) | 24 (`30.26,-97.75`) |
| `latlon_grid_0p05` | 83 | 59 | 71.1% | 472 | 357 (75.6%) | 95 (`30.25,-97.75`) |
| `all` | 1 | 0 | 0% | 472 | 472 (100%) | 472 |

- 0.05° cell sizes: 27 cells hold 1 venue, 13 hold 2, 14 hold 3, 5 hold 4, and 24 clear the bar.
  The next largest after 95 are 37 (`30.30,-97.75`), 20, 20 and 18.
- The densest 0.05° cell, `30.25,-97.75` (18 of its 0.01° cells have a row): 95 venues (92 via
  Organization), 3,641 priced rows; p25/median/p75 649/1040/1400, min/max 100/4500 (USD minor
  units).
- **The `all` row:** `venue_count` 472, `organization_venue_count` 459, `priced_count` 24,879,
  `unpriced_count` 0; p25/median/p75 **700/1100/1425**, min/max 50/46800; observed
  2026-10-02T08:41:41Z to 2026-10-22T05:36:04Z. Min and max are venue medians. The 46,800
  (USD 468.00) is one venue's median and is served as is; the site shows the median only.
- **Against ADR-0019 F3:** F3's proxy had 475 placed venues citywide and 84 cells / 59 low /
  363 venues in OK cells at 0.05°. The `all` row's 472 is 0.6% below 475, inside F3's "±a few
  percent". P8-1 §5.1's earlier Gold gave 82 / 58 / 344 at 0.05°.

A build-session refresh at a later instant should give these numbers unless Menu or Identity
changed on `helios_laptop` in between.

### Tests and done-when

- **Migration:** reviewed SQL snapshots (`docs/reviews/sql/…-p8-4-area-kinds-{upgrade,downgrade}.sql`,
  no `CASCADE`, one `TABLE gold.` each), compared against `alembic upgrade --sql`, as
  `test_gold_price_index_migration.py` does. A populated round trip: one row of each kind at
  head, downgrade → only the 0.01° row is left, every other table's count is unchanged and the
  columns are NOT NULL; upgrade again. One test per CHECK rejection listed above.
- **Refresh** (synthetic fixtures, no network): venues in two 0.01° cells of one 0.05° cell and
  one venue elsewhere. Each kind gets its rows. The count sums hold (`all` = Σ cells, 0.05° =
  Σ nested 0.01°). `all`'s percentiles are over every venue median, not sums. `low_sample`
  differs by kind (e.g. 4 + 1 venues: two low 0.01° cells, one 0.05° cell at the bar). The
  shared-menu exclusion applies to every kind alike. The rebuild is deterministic except for
  `refreshed_at`. `grid_cell` at 0.05°: negative longitudes, `-0`, whole degrees and keys on a
  0.05 boundary.
- **Read and API:** `price_index_cell` at 0.05°. `/cells` shape for each kind (`all` with null
  coordinates and `cell_size_degrees`). A full walk at `limit=1` and `limit=200` visits every row
  once, in order, with `next_cursor` null only at the end. Filters narrow. An empty result is 200.
  A malformed, non-canonical or oversize cursor is 400. An unknown `area_kind` and `limit` 0 or
  201 are 422. `/v1/price-index?area_kind=latlon_grid_0p05` floors at 0.05°; `area_kind=all`
  is 422. `/v1/venues` with `area_kind=latlon_grid_0p05` is half-open at 0.05°; a 0.01°-only key
  under it is 422; `area_kind=all&area=all` lists every current venue with a point (and leaves
  out one without); `area_kind` without `area` is 422.
- **No-seq-scan (`EXPLAIN`, sequential scans priced out, as the existing tests do):** the
  `/cells` query for each kind, with and without filters and a cursor: no Seq Scan on
  `gold.price_index`, and the plan uses `uq_gold_price_index`. `/v1/venues` with a 0.05° `area`:
  no Seq Scan on `identity.place`, and the plan uses `ix_place_latitude_longitude` on the
  synthetic fixtures. With `all`: no Seq Scan on `identity.place`, with no index assertion,
  because "has a point" is not selective. On `helios_laptop` (EXPLAIN only, read-only) the
  densest 0.05° cell plans as an ordered `establishment_pkey` walk with `LIMIT`, not
  `ix_place_latitude_longitude`. 1,660 of 9,996 venues match there, so the walk stops early and
  that plan is reasonable. The fixture test pins the index for a selective cell.
- **OpenAPI** snapshot regenerated. `make ci`; strict DB tests on a new `*_test` database;
  `alembic check`.
- **Done when** (ADR-0019 step 3), on `helios_laptop` under Q6 after a `pg_dump` (sha256 recorded),
  `alembic upgrade head` and `python -m apps.gold.refresh`:
  `curl /v1/price-index/cells?area_kind=latlon_grid_0p05` pages through every cell (83
  expected); the `all` row's `venue_count` matches F3's 475 within its stated error (472
  expected); the no-seq-scan tests pass; and the snapshot is regenerated.

### Alternatives

| Alternative | Why not |
|---|---|
| `all` row with sentinel coordinates (0, 0) or the city centroid | A fake point that a map would draw. Q1 chose NULL. |
| A separate `gold.price_index_citywide` table | A second table with the same grain and columns, and a second read path. `area_kind` was kept for exactly this (point 2, point 5). |
| `all` from every priced family, chains included once | A different venue set from the cells, so `all` is no longer their sum; it also needs a rule for which chain location counts. Q2 chose the same placement. |
| Compute 0.05° and `all` at read time from the 0.01° rows | Counts compose but percentiles don't. The statistics need the venue medians, which only the refresh has. |
| A `bbox` filter on `/cells` | Deferred by ADR-0019 §3 until the cell count needs it. A whole 0.01° map is 2 pages today. |
| Page by cell (each item a cell with its rows) | With one category and currency, the same as paging by row. Once courses land (about nine rows per cell) a cell can split across pages. OQ3 keeps rows, as ADR-0019 §3 wrote. |

### Owner questions (Amendment 3)

Each has a recommendation; the build waits for the answers.

- **OQ1. `area_kind=all` on `GET /v1/price-index`.** (a) `422`; citywide is read from
  `/cells?area_kind=all`, and `PriceIndexResponse` keeps non-null `cell_lat`, `cell_lon` and
  `cell_size_degrees` (recommended). (b) Accept it with `lat`/`lon` omitted. `lat`/`lon` then
  become optional, and the three cell fields become nullable in the response schema. That type
  change would affect clients that assume a number.
- **OQ2. `all` on `GET /v1/venues`.** (a) `area_kind=all&area=all`, the pair a `/cells` row
  carries, with `area_kind` alone being `422` (recommended: one rule, "the pair names an area").
  (b) `area_kind=all` alone, with no `area`. Either way the result is every current venue with a
  point, which on `helios_laptop` is the unfiltered list (9,996).
- **OQ3. `/cells` shape details.** Items are index rows, not cells grouped with their rows;
  `cell_size_degrees` sits at the top level, not on each item; `area_kind` defaults to
  `latlon_grid_0p01`, like the other two endpoints (recommended, all three). Or put the cell size
  on each item as ADR-0019 §3 wrote, or make `area_kind` required on `/cells`.
- **OQ4. Downgrade.** Delete the 0.05° and `all` rows, then restore NOT NULL and the old CHECK
  (recommended; Gold rebuilds). Or refuse to downgrade while such rows exist, which forces a
  manual delete first.
- **OQ5. Migration authorization.** Approve the SQL above as written, for a revision after
  `c95d883737db`? It drops NOT NULL on two columns and replaces one CHECK. ADR-0019 §3 described
  only widening the CHECK; the NULL columns come from Q1.

### Owner decision (Amendment 3)

**Answered by the owner on 2026-10-22**, in session P8-4, all as recommended:

- **OQ1:** `GET /v1/price-index?area_kind=all` is `422`; the citywide row is read from
  `/cells?area_kind=all`. `PriceIndexResponse` keeps non-null cell fields.
- **OQ2:** `/v1/venues` names the citywide area with the pair `area_kind=all&area=all`;
  `area_kind` without `area` is `422`.
- **OQ3:** `/cells` items are index rows; `cell_size_degrees` is at the top level; `area_kind`
  defaults to `latlon_grid_0p01`.
- **OQ4:** the downgrade deletes the 0.05° and `all` rows, then restores NOT NULL and the old
  CHECK.
- **OQ5:** the migration SQL above is approved as written, for one revision after
  `c95d883737db`.

The build (migration, refresh, read contract, `/cells`, `area_kind` params, tests, snapshot) and
the `helios_laptop` upgrade and refresh (Q6, after a `pg_dump`) are the next session's own PR.

### Reproduce

Read-only scripts in this session's worktree under `var/p8-4/` (untracked; `ro.py` and `ro.sh`
are copied from P8-3's `var/p8-3/`). `measure.sql` sums the coarser grids from the stored rows.
`expected.py` recomputes each kind with the refresh's own code. `venues_check.py` counts the
venue lists and EXPLAINs them. `cells_plan.py` EXPLAINs the keyset page. `sql_probe.sql` holds
the migration probes (disposable database only).

    var/p8-4/ro.sh var/p8-4/measure.sql --out var/p8-4/measure.json
    PYTHONPATH=. uv run -q --env-file <main>/.env python <main>/var/menu-eval/p5-26/with_db.py \
        helios_laptop var/p8-4/expected.py --out var/p8-4/expected.json
    … with_db.py helios_laptop var/p8-4/venues_check.py
    … with_db.py helios_laptop var/p8-4/cells_plan.py
