# ADR-0020: Drawn areas in the read API (price summary and items inside a boundary)

**Status:** Accepted 2026-10-23 by the owner, OQ1–OQ6 and OQ8 as recommended and OQ7 changed
(the `boundary` filter on `GET /v1/venues` is built now; see [Owner decision](#owner-decision)).
Proposed 2026-10-23 (session P8-8). Not built yet.
**Date:** 2026-10-23
**Phase:** 8 (public v1 site, an [ADR-0019](./0019-public-v1-site.md) follow-up)
**Extends:** [ADR-0007](./0007-gold-price-index-projection.md) (price index: placement,
venue weighting, `MIN_VENUES`, Amendments 1–3), [ADR-0008](./0008-read-api-conventions.md)
(GET-only conventions, error envelope, cursors, 404 vs. empty list),
[ADR-0018](./0018-venue-filters-and-item-price-history.md) (venue filters, `item_id`)
**Depends on:** [ADR-0002](./0002-containerization.md) and ADR-0007 §5 (no PostGIS; lat/lon on
`identity.place`), [ADR-0019](./0019-public-v1-site.md) owner decisions Q1–Q3 and Q7

## Context

### What changed on the client (P8-8 Part A)

The map page no longer shows 0.05° grid squares (First-Helios_Frontend PR #5, stacked on #4).
The reader draws a boundary (3–50 corners, written to the hash as
`#/?area=lat,lon;lat,lon;…` at 5 decimals), and the page lists **the venues with a menu**
inside it. To do that it reads `GET /v1/venues?has_menu=true&limit=200` to the end (941 venues,
5 requests) and runs even-odd ray casting in the browser. It shows **no price** for the drawn
area, because the browser can't compute one honestly:

- **Placement isn't on the wire.** The index places each `(scope subject, source record)`
  family at one venue's point, or leaves it out (ADR-0007 Amendment 1 §5): shared chain or
  platform menus are left out (`shared_menu_url`), and so are Organizations with several
  current venues. The rule runs in Python during the refresh (`gold.price_index._place`) and its
  result isn't stored anywhere.
- **Venue medians aren't on the wire either.** The index is venue-weighted: first each venue's
  median, then `percentile_disc` over those medians (Amendment 1 §2). Reproducing it in the
  browser would take 941 menu fetches and the placement rule above.
- **"Venues with a menu" is not the index's venue set.** Downtown (the Part A hexagon) has
  78 `has_menu` venues, but only 42 placed index venues.

### Facts measured read-only on `helios_laptop` (2026-10-23)

Alembic head `d978bedc2523`. Every connection ran with `default_transaction_read_only=on`.
Timings are warm, 20 runs (5 for `_place`), p50/p95, measured on the laptop with no other load.
Scripts are untracked under `var/p8-8/` in the session worktree (`measure_b.py`,
`measure_v.py`, `measure_q.py`, `polycount.py`).

| Fact | Value |
|---|---|
| `gold.current_menu` | 54,318 rows (75 MB), all priced item/variant rows |
| `identity.place` | 9,996 rows, `ix_place_latitude_longitude` btree on `(latitude, longitude)` |
| Placed families / venues (the index's input) | 477 / 472 |
| `has_menu` venues | 941 |
| Extensions available on the server | `pg_trgm`, `cube`, `earthdistance`, `btree_gist` (none installed); **no PostGIS** |

Polygons:

- **downtown**: the 6-corner hexagon drawn with real clicks in Part A, about 3 km across.
- **citywide**: an octagon around every Place.
- **cell**: the 0.05° cell `30.25,-97.75` drawn as a rectangle.

| Option, per request | downtown | citywide | cell |
|---|---|---|---|
| **R** Re-run `_place`, then the refresh's aggregate SQL | 626 ms (`_place` alone 624 / 685 ms p95) | 639 ms | 627 ms |
| **R′** Given stored placements: bbox + ray casting in Python, then the aggregate SQL over `current_menu` | 1.8 / 2.9 ms | 14.4 / 17.4 ms | 2.6 / 3.3 ms |
| **G** Given stored per-venue medians: bbox + ray casting + `percentile_disc` over ≤ 472 rows | 3.1 / 3.5 ms | 6.3 / 6.9 ms | 3.1 / 3.7 ms |
| Placed venues inside (R = R′ = G) | 42 | 471 | 95 |
| Items page (51 rows) of the placed families inside, no name filter | 1.4 / 1.6 ms (1,324 rows) | 16.4 / 18.0 ms (24,799 rows) | — |
| Same, with an unindexed `ILIKE '%taco%'` on item, variant and section names | 2.2 / 2.7 ms (62 rows) | 34.9 / 36.9 ms (809 rows) | — |
| `has_menu` venue page, bbox (index) + ray casting **in SQL** (a `jsonb` edge list joined per row) | 397 / 403 ms | 5,912 / 6,381 ms | 797 / 814 ms |
| `has_menu` venue page, bbox in SQL, then ray casting **in Python** | 8.6 / 8.9 ms | 40.9 / 44.0 ms | — |
| `has_menu` venue page today, no area | 18.0 / 22.4 ms | | |

**Correctness checks.** These are what the proposal relies on.

1. **R, R′ and G agree exactly** on every polygon: `venue_count`, `organization_venue_count`,
   `priced_count`, p25, median, p75, min and max.
2. **The cell drawn as a rectangle reproduces its Gold row** (95 venues, p25/median/p75
   649/1040/1400, 3,641 priced rows). Even-odd ray casting on an axis-aligned rectangle is
   exactly the half-open range `[south, north) × [west, east)` that `grid_cell` floors into.
3. **A whole-world rectangle reproduces the `all` row** (472 venues, 700/1100/1425, 24,879 priced
   rows). The citywide octagon gives 471 because one placed venue (4407, at
   30.109673,-97.399422) lies outside it.
4. **The SQL ray casting matches the browser's.** Run over the API's own `has_menu` set, it
   returns the same venues the Part A page lists: 78 and 77 (the same id set), 673, 573 and 0.

What the table shows:

- **Placement is the cost**, not aggregation. Once placement is stored, any polygon costs
  2–18 ms.
- **Ray casting belongs in Python**, after an index-backed bbox. The SQL `jsonb` version
  scans badly (5.9 s citywide).
- **At 9,996 places the planner often prefers a sequential scan for a bbox this wide.** The
  `EXPLAIN` of the downtown query uses `ix_place_latitude_longitude`; the citywide one does
  not. ADR-0018's tests already force the index with `enable_seqscan = off`.

## Decision (proposed)

### 1. A drawn area reaches the API as a GET parameter: `boundary=lat,lon;lat,lon;…`

The same text the client already writes into its hash. GET keeps ADR-0008's read-only, cacheable,
shareable shape: a link to a drawn area's figures is a URL.

- **Form:** 3–50 corners, `;`-separated. Each corner is `lat,lon` in plain decimal (no
  exponent, at most 6 decimals, the precision of `Numeric(9, 6)`), with `lat` in [-90, 90] and
  `lon` in [-180, 180]. A final corner equal to the first is dropped (closed-ring input
  is accepted). The order and orientation of the corners don't matter.
- **Size:** at most 1,200 characters (50 × `-90.123456,-180.123456;`). Well inside URL limits.
- **Extent:** the bounding box may span at most 2° of latitude and 2° of longitude (OQ2).
  Austin's Places span 0.83° × 0.80°, and the client's "Use the visible map area" at zoom 10 on
  a wide screen is about 1.5° wide.
- **Semantics:** a venue's Place point is inside when even-odd ray casting says so, with
  longitude as x and **exact decimal arithmetic**. A boundary that crosses itself is
  accepted; a point inside it counts where it is wrapped an odd number of times. A zero-area
  boundary is valid and matches nothing.
- **Errors:** anything else is `422 validation_error` (ADR-0008 §4), with a `detail` naming the
  rule it broke. An area that matches nothing is `200` with empty or zero results, never 404.
- **Evaluation:** an index-backed bbox prefilter (`latitude BETWEEN :s AND :n AND longitude
  BETWEEN :w AND :e`), then exact ray casting in Python over the candidates. One pure
  function in `packages/helios_core` (beside `grid_cell`) does the ray casting for every
  caller and for the tests. No PostGIS, no extension.

### 2. Placements are stored by the refresh: one new Gold table (a migration; OQ3)

`gold.price_index_placement`: one row per **kept** placement (ADR-0007 Amendment 1 §5), written
by `refresh_price_index` in the same transaction and at the same `effective_instant` as
`gold.price_index`. Sketch for review; the exact DDL comes with the build:

| Column | Type | Notes |
|---|---|---|
| `subject_id`, `subject_kind`, `source_record_id` | as in `gold.current_menu` | the family; unique together |
| `venue_id` | bigint | the Establishment the family is placed at |
| `latitude`, `longitude` | `Numeric(9, 6)` | that Establishment's Place point at `E` |
| `via_organization` | boolean | placed through its Organization |
| `effective_instant`, `refreshed_at` | timestamptz | as on `gold.price_index` |

- Indexes: a unique index on the family, and a btree on `(latitude, longitude)` for the bbox.
- It is an additive Gold table: no FK into it, no existing table changed, and it is rebuilt in
  full each refresh, so no row is ever migrated.
- 477 rows today.
- The aggregate SQL in `price_index._INSERT_SQL` is split, so cells and drawn areas run the same
  venue-median → percentile query. The query reads `gold.current_menu` joined to the stored
  placements; it doesn't re-run the placement.

Why a placement table and not per-venue medians (**G**): G is 2–3× faster here, but it stores
only statistics. The items list (point 4) needs the families themselves, so G would need the
placement table too, or a second copy of the placement rule. R′ is already 2–18 ms, and it
keeps one source of truth for "which rows are behind this area".

### 3. `GET /v1/price-index/area?boundary=…&category_kind=…&currency=…`

The index's own statistic for the placed venues inside the boundary.

- **Body:**
  - `boundary`, the normalized corners as `[[lat, lon], …]`;
  - `as_of`, the placements' `effective_instant`; null when `items` is empty;
  - `items`, one per category and currency, exactly the `PriceIndexGroupResponse` fields
    (`venue_count`, `min_venues`, `low_sample`, `organization_venue_count`, `priced_count`,
    `unpriced_count`, p25/median/p75/min/max in integer minor units, `oldest_observed_at`,
    `newest_observed_at`, `age_seconds`).
- **No pagination.** The response is bounded, as on `/v1/price-index`: one item today, about nine
  once courses arrive (ADR-0016).
- **The same rules as every Gold row:**
  - venue-weighted `percentile_disc`;
  - item and variant targets only;
  - shared menus and multi-venue Organizations are left out by the stored placement;
  - `MIN_VENUES = 5` (`low_sample` below it; every honesty field still served).
- **The client keeps ADR-0019 Q3:** a `low_sample` area shows its venue count and no median.
- A boundary with no placed venue is `200`, with `items: []` and `as_of: null`. A boundary whose
  venues have only non-priced rows gets an item with `venue_count` 0 and null statistics, as in
  the refresh.
- **Index-backed:** a bbox range on the placement table's `(latitude, longitude)` btree.
  `gold.current_menu` is reached through the existing `uq_gold_current_menu` leading
  `(subject_id, subject_kind, source_record_id)`. There is a no-seq-scan test for each table
  (`enable_seqscan = off`, as in ADR-0018).
- **Tests:**
  - a rectangle equal to any 0.05° or 0.01° cell returns that cell's row field for field;
  - a rectangle around every placement returns the `all` row.

### 4. `GET /v1/price-index/area/items?boundary=…&currency=…&q=…&limit=…&cursor=…`

The priced rows **behind that summary**: the item and variant rows of the placed families
inside the boundary, so the list and the median always describe the same data (OQ5).

- **Each item:**
  - `venue_id` and venue `name`;
  - `item_id` (ADR-0018 §B4; it links to the price trail);
  - `section_name`, `item_name`, and the variant `name` when the row is a variant;
  - `amount_minor` and `currency_code`;
  - `channel` and `service_period`;
  - `observed_at`, `age_seconds` and `source_kind`.
- **Order:** `amount_minor` ascending (cheapest first), then the business grain
  (`subject_id, subject_kind, source_record_id, root_key, target_path, channel, service_period,
  valid_from, valid_to, currency_code`), which is unique (`uq_gold_current_menu`).
- **Cursor:** unpadded base64url compact JSON of the last row's `[amount_minor, …grain]`.
  - Only the canonical encoding decodes, as with the cells cursor (ADR-0007 Amendment 3 §6);
    anything else is `400 invalid_cursor`.
  - It is a business key, not `current_menu.id` (which each refresh replaces, ADR-0018 fact 4),
    so it survives a refresh.
  - It doesn't carry the filters.
  - `limit` defaults to 50, cap 200 (ADR-0008 §3).
- **Cost:** the candidate set is bounded by the placements inside the boundary (24,799 rows
  citywide today), so a page is an in-memory sort: 1.4–18 ms measured. No new index.
- **`q` (OQ6):** an optional case-insensitive substring match on the item and variant names
  (`ILIKE '%' || q || '%'`, with `%`, `_` and `\` escaped), 2–100 characters, no index and no
  extension. It is bounded the same way: 2.2 ms downtown, 34.9 / 36.9 ms citywide. Section
  names are **not** matched: in the measurement, matching them pulled in "Kids Mac & Cheese"
  for `burger` (it sits in a "Burger" section).

### 5. Not proposed

- *(Withdrawn by owner decision 7: the filter is built now.)* **A `boundary` filter on
  `GET /v1/venues` (OQ7).** The client already filters the 941
  `has_menu` venues itself (5 requests per page load). If the list grows tenfold, the same
  validator and bbox-then-Python evaluation would add it in about 40 ms citywide.
- **Name search on venues** (ADR-0019 Q7 stays "later"). **`pg_trgm`** (an extension).
  **A cap on the polygon's area** beyond the 2° bbox.
- **Caching or HTTP cache headers.** They are a hosting-time question (ADR-0019 Q4).

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **Transport: GET `boundary=` polygon** (proposed) | GET-only like every endpoint; a URL is shareable and cacheable; same text as the client hash; 1,200-char cap | Long URLs in logs; a custom text form rather than a standard one |
| Transport: GET bounding box only | Trivial to validate; one index range, no ray casting | Not what the reader drew: a diagonal street or a river bend becomes a rectangle with up to twice the venues; the client would show one area and price another |
| Transport: POST GeoJSON | A standard shape; no URL length limit | Breaks ADR-0008's GET-only reads; not cacheable or linkable; a JSON body triggers a CORS preflight once public; GeoJSON is `[lon, lat]` while every Helios field is lat-first; needs a request-body schema |
| **Placements: Gold placement table** (proposed) | Stores the 0.6 s step once per refresh; 2–18 ms per area; one source for summary and items; additive | A Gold migration (stop-and-ask); one more table each refresh rewrites |
| Placements: per-venue medians table | Fastest summary (3–7 ms) | Items still need the families, so it means two tables or a second placement rule; stores derived statistics that the next category kind multiplies |
| Placements: request time (`_place` per request) | No migration | 0.6–0.7 s per request, growing with families; repeats per-family provenance reads on every hit |
| Placements: memoized in the API process, keyed by `effective_instant` | No migration; 2–18 ms after the first request | Process state in the API (each worker pays 0.6 s once per refresh; invalidation by polling `effective_instant`); placement logic would run inside a request (ADR-0008 §9) |
| Ray casting in SQL | One round trip | Measured 397 ms downtown and 5.9 s citywide with a `jsonb` edge list; without PostGIS, SQL has no polygon type to index |
| PostGIS `ST_Contains` | Real geometry, GiST index | ADR-0007 §5 (owner): no PostGIS; not available on the `helios_laptop` server |

## Consequences

- One Gold migration (a new table only), two new GET paths, new schemas (`PriceIndexAreaResponse`,
  `AreaItemList`, `AreaItemResponse`), a regenerated OpenAPI snapshot, and two new
  `js/endpoints.js` entries in the client (the contract check covers them).
- The refresh writes about 477 more rows. Cells and drawn areas share one aggregate query, so
  they can't drift. Rebuilding the cell rows from the placement table is possible later; it is
  not part of this proposal.
- A drawn area shows two counts that differ on purpose: venues with a menu (the client's list)
  and placed index venues (the summary). The client must label both. Downtown: 78 and 42.
- The items list is honest but long without `q`: 1,324 rows downtown, 24,799 citywide.
- Exact-decimal ray casting on the server and float ray casting in the browser can disagree only
  for a Place point lying on a non-axis-aligned edge to within float error. Such a venue shows
  up in one list and not the other. On an axis-aligned edge both follow the half-open rule.

## Tests and done-when (for the build, after acceptance)

- **Boundary parser:** every accept and reject rule in point 1, the closing-corner drop, the
  2° bbox, `422` bodies with `trace_id`.
- **Ray casting:** the half-open property on rectangles (south and west edges in, north and
  east out), even-odd on a self-crossing boundary, a zero-area boundary.
- **Placement table:** written in the same transaction as `gold.price_index`, at the same
  `effective_instant`; row count equals `PriceIndexReport.placed`; a migration round-trip test.
- **Summary:** every 0.05° and 0.01° cell drawn as a rectangle equals its Gold row, and a
  rectangle around every placement equals the `all` row (run on fixtures in CI and once
  read-only on `helios_laptop`). `low_sample` below 5. `200 items: []` for an empty boundary.
  No sequential scan.
- **Items:** keyset order is total; the cursor survives a refresh (same business key, next
  snapshot); `q` escapes `%`, `_` and `\`; `400` on a non-canonical cursor; the page count
  matches `priced_count` of the summary when `q` is absent.
- `make ci`, the strict DB tests, `alembic check` and the Docker build, as always.

## Owner questions

Each has a recommendation. Nothing in this ADR is built until these are answered.

- **OQ1. Transport.** GET with `boundary=lat,lon;…` (recommended)? Or a bounding box only, or
  POST with GeoJSON (see Alternatives)?
- **OQ2. Limits.** 3–50 corners, at most 6 decimals, at most 1,200 characters, a bbox of at most
  2° × 2°, self-crossing boundaries accepted under even-odd (recommended)? Or reject
  self-crossing boundaries (an O(n²) check, at most 1,225 edge pairs), or a tighter extent?
- **OQ3. Where per-venue figures come from.** The Gold migration: a new
  `gold.price_index_placement` table written by the refresh (recommended; 2–18 ms per area,
  sketch in point 2, exact DDL reviewed with the build). Or a per-venue medians table (3–7 ms,
  items still need placements), request-time placement (~0.63 s per request, no migration),
  or an in-process memo (no migration, process state in the API)?
- **OQ4. Summary endpoint.** `GET /v1/price-index/area` as in point 3: unpaginated, the same
  honesty fields, `MIN_VENUES = 5`, the same placement and shared-menu exclusion, and
  `as_of` from the placements (recommended)? Also confirm the client shows "N venues with a
  menu; M in the index" with the median only when `low_sample` is false.
- **OQ5. Which rows the items list holds.** The rows behind the summary (placed families only,
  so chain menus shared across locations are left out, as in the median; recommended)? Or every
  priced row of every `has_menu` venue inside (it matches the venue list, but it would include
  shared chain menus the median leaves out)?
- **OQ6. Item name filter (reopens ADR-0019 Q7, for items only).** (a) No filter in v1: a
  cheapest-first list paginated to the end. (b) **Recommended:** `q`, an unindexed
  case-insensitive substring on item and variant names, bounded by the boundary's placed rows
  (measured 2.2 ms downtown, 34.9 / 36.9 ms citywide; no extension, no migration).
  (c) `pg_trgm` with a GIN index: an extension and a migration, not justified at 54k rows.
  Venue name search stays deferred as Q7 decided.
- **OQ7. `boundary` on `GET /v1/venues`.** Defer it (recommended): the client filters 941
  `has_menu` venues itself. Or add it now with the same validator?
- **OQ8. Order of work.** After acceptance: one build PR for the migration, refresh, endpoints
  and tests, then a refresh on `helios_laptop` (an owner-approved write, after a `pg_dump`),
  then the client PR (the summary under the count, the items list with `q`). Agreed?

## Owner decision

**Answered by the owner on 2026-10-23**, in session P8-8:

1. **OQ1 transport:** GET with `boundary=lat,lon;…`, as in point 1.
2. **OQ2 limits:** as proposed: 3–50 corners, at most 6 decimals, at most 1,200 characters, a
   bbox of at most 2° × 2°, self-crossing boundaries accepted under even-odd.
3. **OQ3 placements:** the Gold migration, a new `gold.price_index_placement` table written by
   the refresh (point 2). This approves the direction. The exact DDL and migration SQL are
   reviewed in the build PR, as with ADR-0007 Amendment 3.
4. **OQ4 summary:** `GET /v1/price-index/area` as in point 3. The client shows "N venues with a
   menu; M in the index", with the median only when `low_sample` is false.
5. **OQ5 item rows:** the rows behind the summary (placed families only, so shared chain menus
   are left out).
6. **OQ6 name filter:** `q`, an unindexed case-insensitive substring on item and variant names
   (not section names). No extension. Venue name search stays deferred (ADR-0019 Q7).
7. **OQ7 changed: add `boundary` to `GET /v1/venues` now.** It uses the same parser and the same
   exact ray casting as the price-index endpoints. The bbox prefilter runs on
   `ix_place_latitude_longitude`, and ray casting runs in Python. It is ANDed with the
   existing filters. `boundary` together with `area` or `area_kind` is `422`: one geographic
   filter at a time. Paging stays keyset on the Establishment `subject_id`. A page fills from
   bbox candidates in id order after the cursor, until `limit + 1` venues pass the ray cast or
   the candidates run out. The list stays geographic (every current venue whose point is
   inside), as ADR-0018 §A3 defines `area`. Point 5's first bullet is withdrawn.
8. **OQ8 order:** one First-Helios build PR (migration, refresh, the three endpoint changes,
   tests). Then a `pg_dump` of `helios_laptop`, `alembic upgrade head` and a Gold refresh there
   (approved owner writes). Then the frontend PR.

## References

- First-Helios_Frontend PR #5 (P8-8 Part A, the drawn boundary; stacked on #4, the step 5–6
  re-land) and PR #4.
- `packages/helios_core/gold/price_index.py` (`_place`, `_INSERT_SQL`, `grid_cell`),
  `apps/api/routes/venues.py` (`_has_menu`, `_in_area`), `apps/api/routes/price_index.py`.
- ADR-0007 Amendments 1–3, ADR-0008 §3–§4 and §9, ADR-0018 §A and §B4, ADR-0019 §3 and owner
  decisions.
- Session measurements: `var/p8-8/measure_b.json`, `measure_v.json`, `measure_q.json`,
  `polycount-375.jsonl` (untracked, in the P8-8 worktree).
