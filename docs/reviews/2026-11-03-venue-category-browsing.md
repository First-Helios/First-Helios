# Venue category browsing — 2026-11-03

Implements owner-approved ADR-0028 on backend and frontend `feat/category-browsing`
branches, following the frontend section/search slice (`56dc45a`). No deployment
or application database changes were performed.

## Result

Restaurants can be browsed by Cuisine, Specialty places and Place type. The
versioned mapping has 18 cuisine choices, 12 specialties and 15 place types.
Each mapped claim retains its exact supporting tags, Bronze version and observed
time. Only the latest observation of currently resolved Overture records is
considered; missing/empty tags remove older assertions. Ties prefer the oldest
record and latest version. Unknown/unmapped tags do not become guessed labels.

Gold owns `gold.venue_category` (revision `73b0e3dba421`), rebuilt transactionally
by `apps.gold.refresh` alongside menus and the index. Identity and provenance
contracts supply source links and latest tags; API requests read the projection.

Venue responses expose categories in one batched query per page. Repeatable
`cuisine`, `specialty`, `place_type` parameters work on venues and area price
items, OR within groups and AND across groups. Filters apply before cursor
pagination. Semi-joins preserve each existing item/variant/context price row.
`/v1/venues/category-facets` counts distinct restaurants over the complete
eligible scope, applying the other groups' filters. Static route registration
precedes the venue-id route.

`indexed_only=true` and optional item-name `q` keep the map's filtered restaurant
list, dots, item matches and category counts in the same placed-price scope.
Indexed scope requires a boundary; q requires indexed scope. The standalone
venue list retains its broader published-menu scope. Unknown-category venues
remain in unfiltered browsing. Shared unplaced chain menus retain their existing
index exclusions. The area median remains all indexed items, labelled explicitly.
Specialty categories describe places; they do not classify each dish.

The frontend supports multiple choices, clear/reset, count updates, shared URLs,
Back/reload restoration and complete filter parameters on every cursor request.
Repeated array values are sorted/deduplicated for cache identity. Selection
changes cancel obsolete batches and facet watches; a facet failure cannot hide
independent menu-price results. Menus retain the previously implemented visible
source-section filters and suggested food searches. Map resize handling now
avoids Leaflet's delayed moveend callback after disposal.

## Data measurement

Only a restored copy in `helios_category_benchmark_test` was refreshed; no live
application database was written. Source: November 1
`helios_laptop-2026-11-01-d2prime.dump`.

- 21,467 category rows across 9,723 currently operating, resolved venues.
- Cuisine: 5,136 labels for 4,061 venues.
- Specialty: 3,040 labels for 2,942 venues.
- Place type: 13,291 labels for 9,721 venues.
- Refresh: 1.491 seconds on this laptop. Repeating with the same effective instant
  yielded identical business columns and source supports.
- EXPLAIN used `ix_gold_venue_category_filter` for cuisine selection.
- A read-only browser check of the restored data selected Mexican and Taco places
  in `30.24,-97.80` to `30.32,-97.70`: five restaurants, 148 priced rows, matching
  labels across restaurant cards and item groups, with no browser exceptions or
  mobile overflow.

The machine and backup differ from production; these are measured local results.
Detailed measurement: `2026-11-03-venue-category-benchmark.json`. Reviewed upgrade
and downgrade SQL are under `sql/2026-11-03-venue-categories-*.sql`. The downgrade
removes only the rebuildable category table.

## Validation

- Backend: strict disposable-database full run: 1,883 passed; its only failure
  was the existing exact schema inventory omitting the approved new Gold table.
  That assertion was updated and the schema-layout tests rerun. The final API
  regression run passed 159 tests. Lint, typecheck and lock checks passed;
  `alembic check` found no drift. Full GitHub CI is also required before merge.
- Frontend: 29 Node tests, proxy unittest and nine-endpoint API contract check.
- New browser acceptance: combined category groups and repeated filter values on
  every item/venue cursor; counts; cancellation/failure isolation; clear/reset;
  shared URL, Back/reload; keyboard; 320/390/1100px layouts; resize/disposal.
- Existing menu-section, browsing, and synthetic menu/history browser acceptance
  passed, including options, price contexts, source attribution and refreshes.
- Real restored-data browser acceptance described above passed.

The full backend suite needs a disposable PostgreSQL role allowed to set
`track_functions` for its existing commit-check instrumentation test. Verification
uses an isolated local PostgreSQL 16 instance with PostGIS, not privilege changes
to the application's database role. The existing typed-grain truncation test now
includes CASCADE so Identity's guard rejects truncation after PostgreSQL resolves
the new child FK; it continues to assert the guard's specific failure.

## Release sequence

Apply the backend migration, run the normal Gold refresh, check category facets
and filtered venue/item requests, then publish the compatible frontend. No new
runtime dependency or service is introduced. Refreshes replace removed tags and
closed/retired/remapped venues. The new category table is initially empty after
migration until the refresh runs. Deployment remains a separate action.
