# ADR-0028: Venue categories for browsing without search

**Status:** Proposed — schema and contract awaiting owner review.
**Date:** 2026-11-03
**Extends:** ADR-0004 (ownership), ADR-0006 (Gold projections), ADR-0008
(read API), ADR-0018 (venue filters), ADR-0020 (drawn areas).

## Context

The owner requested browsing restaurants and food without typing an item name,
then authorized the frontend work after the category inventory. The November 1
`helios_laptop-2026-11-01-d2prime.dump` has 110 primary and 263 alternate Overture
category values across 10,014 source records. These are source-record counts,
not counts of distinct current venues. Categories mix cuisines, specialties,
formats, and unrelated businesses. Source menus also have 5,105 distinct section
headings; those are already served, but do not establish cuisine or classify
individual dishes reliably.

The venue API has no category field or filter. Discovery retains the source
categories in immutable Bronze payloads. ADR-0004 says that source payload JSON
is source-faithful evidence, "not as a query-serving domain model". Adding a
Gold projection is preferable to teaching the browser to infer cuisine or making
an API request scan raw JSON on every filter change.

CLAUDE.md requires review before new schema patterns, ORM model changes and
migrations. This proposal specifies that boundary; it does not implement it.
Existing-contract frontend work can proceed independently: suggested literal
food searches and filters over a restaurant's published section headings.

## Proposed decision

### Vocabulary and source selection

Introduce three separate venue-category groups, represented by a reviewed,
versioned mapping of exact Overture values to stable keys and friendly names:

The complete initial allowlist is below. A pair is `stable_key = exact_source_tag`.
Friendly labels use the conventional display spelling, with **places** appended
for every specialty (for example, Pizza places). This deliberately excludes
unmapped source tags; adding them later means a reviewed mapping-version change.

- `cuisine`: `mexican=mexican_restaurant`, `tex_mex=texmex_restaurant`,
  `american=american_restaurant`, `italian=italian_restaurant`,
  `chinese=chinese_restaurant`, `indian=indian_restaurant`,
  `thai=thai_restaurant`, `vietnamese=vietnamese_restaurant`,
  `japanese=japanese_restaurant`, `mediterranean=mediterranean_restaurant`,
  `korean=korean_restaurant`, `greek=greek_restaurant`, `french=french_restaurant`,
  `middle_eastern=middle_eastern_restaurant`, `cajun_creole=cajun_and_creole_restaurant`,
  `southern=southern_restaurant`, `latin_american=latin_american_restaurant`,
  `asian_fusion=asian_fusion_restaurant`.
- `specialty`: `pizza=pizza_restaurant`, `burgers=burger_restaurant`,
  `tacos=taco_restaurant`, `barbecue=barbecue_restaurant`,
  `chicken=chicken_restaurant`, `seafood=seafood_restaurant`,
  `sushi=sushi_restaurant`, `sandwiches=sandwich_shop`,
  `wings=chicken_wings_restaurant`, `noodles=noodles_restaurant`,
  `poke=poke_restaurant`, `hot_dogs=hot_dog_restaurant`.
- `place_type`: `food_truck=food_truck`, `cafe=cafe`,
  `coffee_shop=coffee_shop`, `bakery=bakery`, `bar=bar`, `pub=pub`,
  `brewery=brewery`, `ice_cream_shop=ice_cream_shop`, `diner=diner`,
  `deli=deli`, `bistro=bistro`, `food_court=food_court`,
  `fast_food=fast_food_restaurant`, `juice_bar=smoothie_juice_bar`.
  Also map exact `juice_bar` to `juice_bar`, and `fast_food` to `fast_food`.
  `restaurant` includes exact `restaurant` and every allowlisted source tag
  ending in `_restaurant`; it does not include arbitrary suffix matches.

Use primary and alternate categories from the chosen source record; deduplicate
mapped values. Exclude equipment, wholesale, music venues and all other unmapped
values. A restaurant category may map to `place_type=restaurant` as well as its
explicit cuisine or specialty. Do not turn a taco specialty into Mexican cuisine
without an explicit source cuisine assertion. Dietary positioning is excluded
from this first mapping; it cannot guarantee an individual item's ingredients.

Resolve records through current Identity resolutions, including currentness of
the Establishment, Organization and Place. Reuse the deterministic latest-source
selection rule of discovery's venue-candidate contract: latest observation wins;
a tie prefers the oldest source record, then the latest version for that record.
Restrict candidates to the Overture source namespace. Select the latest version
of each source record before reading categories: a newer missing/empty category
must remove an older claim rather than fall back to it. Exclude unresolved,
retired and closed venue scopes. Do not union stale categories from all past
versions or spread one location's categories to its whole organization.

### Storage and refresh

Add a rebuildable table owned by Gold, working name `gold.venue_category`:

| Column | Contract |
|---|---|
| `venue_id` | FK to `identity.establishment.subject_id`, RESTRICT |
| `category_group` | Checked enum `cuisine`, `specialty`, `place_type` |
| `category_key` | Stable reviewed mapping key, max 128 characters |
| `source_record_version_id` | FK to the chosen Bronze version, RESTRICT |
| `source_categories` | Nonempty array of exact raw tags supporting this mapped row |
| `mapping_version` | Version of the checked-in mapping |
| `observed_at` | Source version observation instant |
| `refreshed_at` | Projection refresh instant |

Unique grain: `(venue_id, category_group, category_key)`. Add an index on
`(category_group, category_key, venue_id)`; the unique key serves a venue's labels.
Unknown categories mean no rows, never an invented cuisine.

Build a Gold-owned refresh using contracts for provenance and identity reads,
not consumer imports of another module's ORM. Run as part of `apps.gold.refresh`
with one effective instant and transactional publication. A refresh replaces
stale labels, including removals, closures, corrected resolutions and mapping
changes. No new runtime dependency, external service, ingestion model call, or
canonical food-item schema is required. Measure the refresh on a restored
backup before rollout; live application data is not a test fixture.

### Read API

Add `categories` to venue responses, an array of `{group, key, label}` in stable
order. Batch-read them for a page to avoid one query per venue. Unknowns return
an empty array.

Add repeatable `cuisine`, `specialty`, and `place_type` filters to `GET /v1/venues`
and `/v1/price-index/area/items`. Values are validated mapping keys, capped at
20 per group; unknown or blank keys return the existing 422 envelope. OR within
a group, AND across groups; combine with existing boundary, menu-availability,
organization and optional item-name query. Filter before ordering, limit and
cursor comparison. Existing cursors continue to carry business ordering only;
every request must resend its complete filter set. Existence/semi-joins prevent
multiple category labels from multiplying price rows or venues.

Add `GET /v1/venues/category-facets` accepting the same venue scope and category
filters. Return `{as_of, groups}`. Each group contains available keys, labels
and distinct `venue_count`, calculated over the complete eligible set with all
other group filters applied; pagination of the restaurant list must not change
facet counts. For map item filtering, facet scope also needs `indexed_only=true`
and optional `q` to match the placed priced-item set. The default venue facet
scope remains venues, including those excluded from the price index. Bound the
response by the versioned mapping vocabulary. Register the static route before
`/venues/{venue_id}`. ETags use the existing validation mechanism.

The existing area median remains explicitly all indexed items in the boundary.
Changing its semantics requires a separately reviewed price-index extension.

### Frontend behavior

Display **Cuisine**, **Place type**, and **Specialty places** controls. Use the
specialty wording until item-level classification exists. Selected keys persist
in the route URL, request/cache identity, navigation restoration, and every
cursor request. Reset pagination and abort old batches on a filter change.
Map dots, restaurant list and item matches must all apply the active scope;
retain explicit coverage text for shared chain menus excluded from index items.

Keep original menu headings and inferred/normalized venue categories separate.
Do not present Suggested food searches as category classification. Individual
food-type labels and course classification stay under RFC-0001 D7 and ADR-0016,
respectively; this table labels places only.

## Acceptance before implementation is considered complete

- Reviewed full source-to-group mapping, including mixed primary/alternate tags.
- Hand-reviewed migration SQL and `alembic check` on a disposable database.
- Fixtures for latest empty-category removal, late backfills, merges, unresolved
  records, closures, unknown/unmapped tags, and one-location/chain isolation.
- Filter combinations and cursor pages return no duplicates or missed matches;
  facets count the complete eligible set with the documented group semantics.
- EXPLAIN confirms category and placement indexes serve the new predicates.
- Recorded backup comparison with source timestamps, venue coverage and refresh
  cost; strict database `make ci`, contract check and browser acceptance pass.
- Keyboard/mobile controls, empty states, pending requests, refresh removals and
  Back/share restoration work. Existing all-item price summaries remain clear.

## Alternatives

- Reading Bronze JSON per API filter avoids a migration, but promotes raw payloads
  into a query model and bypasses the existing projection ownership decision.
- Guessing categories from restaurant names or keywords in the browser would
  create unreviewed classifications and inconsistent paginated results.
- Training a new item classifier now would conflate restaurant labels with the
  separate dish-taxonomy decision and exceed this first browsing slice.
