# Meal Deal Foundation Assessment

Date: 2026-04-16

## Scope

This review covers the meal-deals system end to end:

1. Venue identity and URL storage
2. Deal collection and extraction
3. Ingest, dedupe, and quality refinement
4. Read/query surfaces and operational scripts

It is based on the current codebase plus a live database snapshot from the local Postgres copy synced from production.

## Current Live Snapshot

- `meal_deals.total_rows`: 3,392
- `meal_deals.active`: 2,306
- `meal_deals.active_ratio`: 68.0%
- `meal_deals.chain_templates`: 15
- `meal_deals.mean_signal_quality`: 0.634
- `meal_deals.price populated`: 54.0%
- `meal_deals.valid_days populated`: 32.2%
- `meal_deals.valid_start_time populated`: 24.6%
- `meal_deals.raw_scraped_text populated`: 0.0%
- `meal_deals.sub_deals populated`: 3.3%
- `chain_website.mean_signal_quality`: 0.456 (below dashboard threshold)
- food employers with active `restaurant_urls`: 4,241 / 5,662 (74.9%)
- active shared-URL groups: 538
- active cross-brand shared-URL groups: 244
- active `/api/deals` rows before alias collapse: 2,306
- active `/api/deals` rows after alias collapse: 2,098

## What Exists Today

### Storage layers

- `local_employers` stores business locations.
- `brand_groups` stores fingerprint-level brand identity.
- `restaurant_urls` stores one URL per employer per source.
- `meal_deals` stores both location-scoped deals and brand-scoped chain templates.

### Collection layers

- `osm_url_resolver.py` resolves URLs from OSM.
- `google_places_resolver.py` resolves URLs from Google Places.
- `chain_deals.py` extracts chain deals into brand-level `DealSignal`s.
- `website_scraper.py` scrapes site content and fans signals out to URL-sharing locations.
- `gbp_offers.py` exists for Google Business Profile offers.
- `manual_ingest.py` exists for CSV/JSON human input.

### Refinement layers

- `ingest.py` scores and gates signals, then upserts into `meal_deals`.
- `quality.py`, `temporal.py`, and `sub_deals.py` hold shared refinement logic.
- Multiple cleanup/audit scripts attempt to repair bad rows after ingest.

### Read layer

- `/api/deals` returns deal rows.
- `/api/deals/stats` and `/api/deals/brands` compute aggregates directly from `meal_deals`.

## Big-Picture Assessment

The system has useful building blocks, but the architecture is carrying too much state in the wrong places.

The core issue is that the pipeline does not have one stable canonical unit for a physical venue and one stable canonical unit for a deal observation. Instead, the system mixes:

- employer rows that may be aliases of one venue,
- URL rows duplicated per employer,
- deal rows that may represent a location, a brand template, or a fan-out artifact,
- and a growing set of one-off repair scripts to compensate for those ambiguities.

The result is that the pipeline works, but only after layering cleanup, dedupe, backfill, and read-time suppression on top of it.

## Primary Structural Findings

### 1. Venue identity is still the main source of noise

`local_employers` is not canonical enough for meal deals. Minor naming or address variants create separate employer rows, and URL resolution then assigns the same website to those aliases. That produces duplicate website scrapes and duplicate `meal_deals` rows for one physical venue.

Evidence:

- 538 active shared-URL groups
- 244 active cross-brand shared-URL groups
- 208 active deal rows currently need to be hidden at API time by alias collapse

### 2. `restaurant_urls` is storing URL ownership at the wrong level

The table stores one URL per employer per source. That makes sense for lookups, but it also duplicates the same site across alias employers and across brand fan-out. There is no canonical website entity or ownership map.

This creates two problems:

- repeated scraping of the same site under different employer identities
- downstream confusion over whether a URL belongs to one location, one brand, or a bad match

### 3. `meal_deals` mixes two incompatible semantics

The same table stores:

- real location-linked deal rows (`local_employer_id` set)
- chain template rows (`is_chain_template=True`, `local_employer_id=NULL`)

That makes the storage cheaper, but it pushes complexity into every read/query surface. The API has to know whether a row is already materialized to a location or still needs expansion. Right now it mostly does not.

### 4. Chain templates are not fully carried through to the query layer

Active `chain_website` rows are currently all chain templates with no location and no geo coordinates:

- active chain rows: 3
- active chain rows without location: 3
- active chain rows with geo: 0

That means the storage model has been updated, but the read layer has not been fully rebuilt around it.

### 5. Website-scrape fan-out is currently lossy

`website_scraper.py` extracts rich deal fields earlier in the pipeline, but the later fan-out path rebuilds `DealSignal` with only a subset of fields. This drops fields such as:

- `price_type`
- `discount_percentage`
- `valid_days`
- `valid_start_time`
- `valid_end_time`
- `raw_scraped_text`
- `sub_deals`

This is a major reason the live DB shows `raw_scraped_text` at 0.0% completeness despite the scraper already extracting it.

### 6. The refinement layer is compensating for weak canonical data flow

The project now has many scripts that exist because the base write path is not self-normalizing enough:

- `cleanup_meal_deals.py`
- `purge_junk_deals.py`
- `dedupe_chain_deals.py`
- `audit_url_identity.py`
- `detect_cross_employer_leaks.py`
- `backfill_signal_quality.py`
- `backfill_deal_temporal.py`
- `populate_sub_deals.py`

These are useful operationally, but architecturally they signal that the main pipeline is still producing too many ambiguous rows that require after-the-fact repair.

### 7. Some collection paths are defined but not foundation-ready

`manual_ingest.py` produces `DealSignal`s with `restaurant_name` and `address`, but `ingest.py` only writes non-chain rows when `signal.local_employer_id` is already set. That means manual ingest is not a true end-to-end path for new human-sourced deals.

This points to a missing foundational step: location resolution for meal deals should exist inside the ingest layer, not be assumed to have happened before it.

### 8. Source naming and job semantics are inconsistent

Examples:

- collector `SOURCE = "website_scraper"` while `MealDeal.source = "website_scrape"`
- collector `SOURCE = "gbp_offers"` while row `source = "gbp_offer"`
- stale sweep handles `chain_website`, `website_scrape`, and `manual`, but not `gbp_offer`

These mismatches make observability and lifecycle management more complex than necessary.

### 9. Docs and implementation have drifted

Examples of drift:

- docs still describe much lower URL coverage than the live system now has
- docs present richer raw-text/refinement availability than the live DB currently shows
- docs describe chain-template behavior more completely than the current API layer implements

This makes the system harder to reason about because the docs overstate how unified the pipeline really is.

## What Should Be Simplified

### Simplify to one canonical venue identity layer

Meal deals should not depend directly on raw `local_employers` identity. Introduce a canonical venue identity layer, or explicitly use an alias table, so the system can say:

- these 2-3 employer rows are one venue
- these URLs belong to that venue
- these deals attach to that venue

This can be done with:

- a dedicated `venue_aliases` or `store_aliases` flow
- or a new canonical venue table/materialized identity map

### Simplify to one canonical deal observation model

Split the current mixed `meal_deals` semantics into two conceptual layers:

1. deal observation/template
2. venue applicability/materialization

That can be modeled as either:

- `deal_observations` + `deal_targets`
- or one canonical deal table plus a materialized view for location rows

The current single-table approach is workable only if all readers consistently expand templates, and that is not true today.

### Simplify shared URL handling

Move away from one `restaurant_urls` row per employer as the only representation. The better pattern is:

- one canonical normalized website record
- a mapping table from site to canonical venue or brand
- match metadata and confidence stored separately

That prevents duplicate scraping and gives a cleaner place to quarantine contested URLs.

### Simplify the refinement stack by centralizing heuristics

Name normalization, URL normalization, alias matching, and junk detection are currently split across multiple modules and repair scripts. These rules should live in shared utilities, then be reused everywhere.

That means fewer one-off regex copies and fewer cases where the cleanup rules and the live-ingest rules diverge.

## What Is Redundant Or Overlapping

### URL normalization logic

Normalization and ownership heuristics are currently spread across:

- `google_places_resolver.py`
- `osm_url_resolver.py`
- `audit_url_identity.py`
- `core/venue_identity.py`

This should be one shared URL identity utility.

### Post-ingest cleanup scripts

Several scripts overlap around junk removal and row deactivation. They exist for good reasons, but too many of them are compensating for the same root issues:

- add-on misclassification
- nav text leakage
- cross-employer URL contamination
- chain duplication

These should be reduced over time by hardening the base extraction and identity layers.

### Separate source metadata names

Collector names, `CollectorRun.source`, and `MealDeal.source` are not aligned. That creates redundant translation work in dashboards, stale sweeps, and operator reasoning.

## What Should Be Aggregated

### `/api/deals/stats` and `/api/deals/brands`

These endpoints should use the same deduped semantics as `/api/deals`. Right now the list route has alias collapse, but aggregate endpoints still work off raw rows.

That means the UI can show cleaned cards while counts remain inflated.

### Chain-template expansion

Chain templates should be expanded through one explicit query/view path, not left to ad hoc handling in different endpoints.

### Raw extraction artifacts

If `raw_scraped_text`, parsed segments, and source-level matches are kept, they should be treated as first-class observation artifacts rather than optional denormalized leftovers. Right now the schema wants them, but the write path does not preserve them reliably.

## What Needs Updating First

### Immediate correctness fixes

1. Preserve all extracted fields when `website_scraper.py` fans out signals.
2. Make `/api/deals/stats` and `/api/deals/brands` operate on deduped deal semantics.
3. Add explicit chain-template expansion in the read layer.
4. Align source naming across collectors, `CollectorRun`, `MealDeal.source`, and stale sweep logic.
5. Make manual ingest resolve `local_employer_id` instead of assuming it already exists.

### Foundation rework

1. Add canonical venue alias resolution upstream of meal-deal ingestion.
2. Rework `restaurant_urls` into canonical site identity plus mapping records.
3. Separate canonical deal observations from location materialization.

### Cleanup of operational surface area

1. Consolidate repeated URL/name normalization helpers.
2. Consolidate junk/leak classification into one shared refinement module.
3. Update docs so they describe the current system rather than the intended one.

## Recommended Target Architecture

### Layer 1: Canonical venue identity

- Canonical venue record
- Alias mapping from `local_employers` rows into canonical venue
- Match provenance and confidence retained

### Layer 2: Canonical site identity

- Normalized site URL record
- Mapping from site to canonical venue or brand
- Conflict state for disputed URLs

### Layer 3: Deal observations

- One row per observed deal artifact
- Always keep raw text, normalized text, extracted pricing, extracted temporal fields, source URL, and extraction metadata

### Layer 4: Deal applicability

- Link observation to canonical venue(s) or brand
- Materialize per-location views in query code or a view, not by duplicating the observation row unless necessary

### Layer 5: Consumer API view

- One deduped semantic contract for cards, counts, brands, and map layers
- No endpoint should have to guess whether rows are aliases, templates, or fan-out artifacts

## Bottom Line

The meal-deals system is already collecting meaningful data, and URL coverage is much better than the original docs imply. The problem is not lack of data anymore. The problem is that identity, materialization, and cleanup responsibilities are split across too many places.

The highest-value simplification is not another cleanup rule. It is introducing one canonical venue identity layer and one canonical deal observation model, then making every collector and every endpoint go through those same abstractions.

Until that happens, the system will keep accumulating repair scripts and endpoint-specific dedupe logic.