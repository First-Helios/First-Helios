# Meal Deal Ingestion

Updated: 2026-04-16
Status: canonical identity, observation/applicability, and semantic read-layer are implemented and deployed

## Purpose

This document describes how the meal-deal ingestion system works today, end to end.

It is the operational and architectural reference for:

- humans debugging meal-deal collection or API output
- future agents extending the pipeline
- operators running migrations, backfills, or production deploys

It reflects the live system after the canonical meal-deal rollout that introduced:

- canonical venue identity
- canonical site identity
- canonical deal observations
- resolved deal applicability
- consumer-facing deal materializations

## Executive Summary

The meal-deal system no longer treats raw `meal_deals` rows as the authoritative read model.

The current pipeline is:

1. collector emits `DealSignal`
2. ingest scores and normalizes the signal
3. ingest upserts one `deal_observations` row per underlying source artifact
4. ingest resolves venue or brand targeting into `deal_applicability`
5. ingest refreshes `deal_materializations`, the shared semantic read layer
6. `/api/deals`, `/api/deals/stats`, and `/api/deals/brands` read from `deal_materializations`

`meal_deals` still exists and is still written as a compatibility layer, but it is no longer the primary semantic source for the API.

## Why The Architecture Changed

The original meal-deal design mixed three different concepts in one table and one read path:

- physical venue identity
- observed deal artifact
- consumer-facing venue/deal row

That created duplicate rows when multiple `local_employers` represented one venue, and it pushed dedupe logic into route code.

The canonical rollout split those concerns into explicit storage layers so the system can say:

- which `local_employers` rows are aliases of one physical venue
- which URLs belong to which venue or brand
- which observed deal artifact came from which source page
- where that observed deal actually applies
- which consumer-facing rows should be shown in the API

## Current Storage Model

### Identity tables

#### `canonical_venues`

One row per physical venue used by the meal-deal system.

Key purpose:

- canonical venue identity for dedupe and targeting
- stable address/name/geo layer above raw `local_employers`

#### `canonical_venue_aliases`

Maps `local_employers` rows to canonical venues.

Key purpose:

- collapse alias employers into one venue identity
- preserve provenance via `alias_role`, `match_method`, and confidence

#### `site_identities`

One row per normalized website identity.

Key purpose:

- canonicalize URLs before scraping or observation linking
- separate site ownership from per-employer URL cache rows

#### `site_assignments`

Maps canonical sites to venue or brand scope.

Key purpose:

- declare whether a site belongs to one venue, one brand, or is contested
- support later manual review when site ownership is ambiguous

### Canonical deal tables

#### `deal_observations`

One row per observed meal-deal artifact.

This is the canonical evidence table.

Important fields:

- `source`
- `collector_run_id`
- `site_identity_id`
- `source_url`
- `source_observation_key`
- `deal_name`, `deal_description`, `deal_type`
- pricing and temporal fields
- `raw_scraped_text`
- `extraction_payload`
- `signal_quality`
- `deal_value_score`
- `review_state`

Important rule:

- no per-location duplication belongs here

#### `deal_applicability`

Declares where a canonical observation applies.

Important fields:

- `observation_id`
- `applicability_scope`
- `canonical_venue_id`
- `brand_group_id`
- `confidence`
- `resolver_method`
- `resolver_notes`
- `is_active`

Important rule:

- brand-wide applicability is expressed once here, not by duplicating observations

#### `deal_materializations`

Consumer-facing semantic row set used by the API.

This is a write-through compatibility table derived from:

- `deal_observations`
- `deal_applicability`
- `canonical_venues`
- `canonical_venue_aliases`

It stores one row per consumer-visible venue/deal combination.

Important rule:

- this is the layer all `/api/deals*` endpoints should use

### Compatibility table

#### `meal_deals`

Still written for compatibility and historical continuity.

It contains two legacy semantics:

- location rows for non-chain deals
- chain template rows with `is_chain_template=True`

Important caution:

- do not treat `meal_deals` as the authoritative API read model going forward

## Core Runtime Flow

### Stage 1: URL and site discovery

Relevant sources:

- `osm_url_resolver.py`
- `google_places_resolver.py`
- manual URL rows in `restaurant_urls`

Primary output:

- `restaurant_urls`

Role in the canonical system:

- `restaurant_urls` is now best thought of as an input cache and compatibility table
- canonical website ownership lives in `site_identities` and `site_assignments`

### Stage 2: Collection

Main collectors:

- `chain_deals.py`
- `website_scraper.py`
- `gbp_offers.py`
- `manual_ingest.py`

Common output contract:

- every collector emits `DealSignal`

### Stage 3: Signal ingest

Main write entrypoint:

- `collectors/meal_deals/ingest.py`
- function: `ingest_deal_signals(signals, region)`

This is the canonical write path.

For each signal, ingest performs the following steps:

1. Skip obvious junk deal names.
2. Derive `sub_deals` from text if the collector did not already populate them.
3. Compute `signal_quality`.
4. Compute `deal_value_score`.
5. Convert quality score into one of `accepted`, `review`, or `rejected`.
6. Resolve either `brand_group_id` from `brand_fingerprint` or `local_employer_id` from venue matching logic.
7. Build a stable `source_observation_key`.
8. Upsert one canonical observation row.
9. Build desired applicability rows for venue or brand scope.
10. Continue writing `meal_deals` compatibility rows for accepted or reviewable signals.
11. Synchronize applicability rows.
12. Refresh `deal_materializations` for the affected observations.

### Stage 4: API reads

Read entrypoints:

- `/api/deals`
- `/api/deals/stats`
- `/api/deals/brands`

All three now read from `deal_materializations`.

That means:

- route-level alias collapse is no longer the primary dedupe mechanism
- list, stats, and brands share one semantic base
- counts and cards should agree because they are reading the same row set

## `DealSignal` Contract

`collectors/meal_deals/models.py` defines the shared collector payload.

Important fields:

- venue hints:
        - `restaurant_name`
        - `address`
        - `lat`
        - `lng`
- brand hints:
        - `brand_fingerprint`
        - `brand_group_id`
        - `local_employer_id`
- canonical offer fields:
        - `deal_name`
        - `deal_description`
        - `deal_type`
        - `price`
        - `price_type`
        - `discount_percentage`
        - `original_price`
        - `menu_avg_price`
        - `calories`
        - `calorie_price_ratio`
        - `valid_days`
        - `valid_start_time`
        - `valid_end_time`
- provenance:
        - `source`
        - `source_url`
        - `region`
        - `collector_run_id`
        - `observed_at`
- evidence/refinement:
        - `raw_scraped_text`
        - `signal_quality`
        - `deal_value_score`
        - `sub_deals`
        - `metadata`

## Canonical Identity Flow

### Venue identity

The authoritative venue mapping for meal deals is:

`local_employers` -> `canonical_venue_aliases` -> `canonical_venues`

This is what suppresses alias-venue duplication.

### Site identity

The authoritative site mapping for meal deals is:

normalized URL -> `site_identities` -> `site_assignments`

This is what makes site ownership explicit instead of inferred from repeated `restaurant_urls` rows.

### Observation identity

Observations are deduped by:

- source
- normalized URL when available
- otherwise normalized venue identity fallback
- deal core fields such as deal name, type, valid window, and price hints

This is encoded in `source_observation_key`.

Effect:

- the same shared-site scrape can fan out to multiple applicability targets without creating multiple observations

## Applicability Semantics

### Venue scope

Used when ingest can resolve a specific venue.

Typical resolver method:

- `local_employer_alias`

Path:

- `DealSignal.local_employer_id`
- `canonical_venue_aliases`
- `canonical_venue_id`

### Brand scope

Used when the collector is observing a brand-level offer.

Typical resolver method:

- `brand_fingerprint`

Path:

- `DealSignal.brand_fingerprint`
- `brand_groups`
- `deal_applicability.brand_group_id`
- `deal_materializations` expands this across canonical venues for that brand

## Quality and Gating

Shared quality logic lives in:

- `collectors/meal_deals/quality.py`

Important thresholds:

- score < 0.20 -> reject
- 0.20 <= score < 0.40 -> review
- score >= 0.40 -> accepted

Current ingest behavior:

- rejected signals are skipped for `meal_deals`, but still written to `deal_observations` with `review_state="rejected"`
- review signals are written with inactive compatibility rows and retained canonical evidence
- accepted signals continue through the normal path

Important implication:

- canonical evidence can exist even when no consumer-facing row should be shown

## Semantic Layer Refresh

Shared semantic refresh logic lives in:

- `collectors/meal_deals/semantic_layer.py`

Main function:

- `refresh_deal_materializations(session, observation_ids=None, region=None)`

Behavior:

- deletes prior materializations for the affected observations or region
- loads observations, applicability rows, venues, aliases, and primary employer rows
- expands venue applicability directly
- expands brand applicability across canonical venues in the region
- writes exactly one materialized row per `(observation_id, canonical_venue_id)`

Important design note:

- this is a table refresh, not a PostgreSQL materialized view refresh
- the goal is cross-dialect compatibility and explicit control from ingest/backfill code

## Historical Backfill

Script:

- `scripts/backfill_deal_observation_history.py`

Purpose:

- convert historical `meal_deals` rows into `deal_observations`, `deal_applicability`, and `deal_materializations`

Behavior:

- idempotent by `(source, source_observation_key)`
- reuses existing observations when already present
- rebuilds semantic materializations for the region
- uses historical `MealDeal.is_active` to map old rows into `accepted` vs `review`

Important caution:

- this backfill preserves historical activity state, not recomputed quality truth
- noisy active historical rows can therefore appear as accepted until they are re-audited

## Canonical Identity Rebuild

Script:

- `scripts/backfill_meal_deal_identity.py`

Purpose:

- rebuild canonical venues, aliases, canonical sites, and site assignments from current `local_employers` plus `restaurant_urls`

Important behavior:

- rebuild-oriented: clears canonical identity tables and repopulates them
- uses the shared venue identity helper in `core/venue_identity.py`
- should generally be run before the historical deal backfill if canonical identity is missing or stale

## Runtime And Scheduler Details

Scheduler code:

- `core/scheduler.py`

Important change:

- meal-deal signals now receive `collector_run_id = run.id` before ingest

Effect:

- canonical observations can retain collector lineage in `deal_observations.collector_run_id`

Important quirk:

- `website_scraper.collect()` already has an internal ingest path for its chunked scraping flow
- scheduler-level ingest can therefore process related outputs again
- observation upserts and applicability synchronization must remain idempotent because of this

## Website Debug Cache

Website scraper debug bundle path:

- `data/cache/website_scrape_debug`

Purpose:

- local replayable capture of page content and extraction artifacts
- supports debugging scraper behavior without repeated network requests

Important behavior:

- rerunning the same normalized URL overwrites the previous debug bundle
- replay mode avoids live fetching and uses the cached bundle instead

## API Semantics

### `/api/deals`

Returns paginated materialized rows.

Each row is already:

- venue-scoped
- alias-collapsed
- expanded from brand applicability when needed

### `/api/deals/stats`

Counts materialized rows, grouped by type and source.

Important interpretation:

- `restaurant_count` is now effectively canonical venue count, not raw `local_employer_id` count

### `/api/deals/brands`

Counts brands from materialized rows.

Important effect:

- brand counts and deal counts now share the same semantic row set as `/api/deals`

### `/api/deals/review-queue`

Returns a lightweight operator queue built from canonical conflict data.

Current queue contents:

- contested sites from `site_identities` plus `site_assignments`
- medium-confidence venue aliases from `canonical_venue_aliases`

Important note:

- this is a read-only review surface for triage
- final adjudication is still manual from an operator perspective, but the API now exposes write-back actions so resolution does not require direct SQL

### `/api/deals/review-queue/actions`

Applies manual operator resolutions for review-queue items.

Current action coverage:

- contested-site resolution to a single venue
- contested-site resolution to a brand
- contested-site blocking
- venue-alias confirm
- venue-alias reassign
- venue-alias remove

Important behavior:

- venue-alias write-backs also repair matching `deal_applicability` rows and refresh affected `deal_materializations`
- site-resolution write-backs update canonical site ownership state for future scraping and review workflow

## Operations

### Local validation workflow

Recommended order:

1. Sync production-like data with `bash dev/sync_from_opi.sh`
2. Run migrations
3. Rebuild canonical identity
4. Dry-run or run historical backfill
5. Run focused tests

Useful commands:

```bash
cd /home/fortune/CodeProjects/First-Helios

/home/fortune/CodeProjects/First-Helios/.venv/bin/alembic upgrade head
PYTHONPATH=. /home/fortune/CodeProjects/First-Helios/.venv/bin/python scripts/backfill_meal_deal_identity.py --region austin_tx
PYTHONPATH=. /home/fortune/CodeProjects/First-Helios/.venv/bin/python scripts/backfill_deal_observation_history.py --region austin_tx --dry-run
PYTHONPATH=. /home/fortune/CodeProjects/First-Helios/.venv/bin/python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx
/home/fortune/CodeProjects/First-Helios/.venv/bin/python -m pytest tests/HeliosDeployment/test_meal_deal_observations.py tests/HeliosDeployment/test_meal_deal_first_pass.py tests/HeliosDeployment/test_meal_deal_alias_dedupe.py tests/HeliosDeployment/test_website_scrape_debug_cache.py tests/HeliosDeployment/test_meal_deal_identity_backfill.py
```

### Orange Pi deploy workflow

Required high-level steps:

1. Copy or pull updated runtime files and migrations to the host
2. Run Alembic upgrade
3. Rebuild canonical identity
4. Run historical backfill
5. Restart both `helios` and `helios-collector`
6. Verify `/api/deals`, `/api/deals/stats`, and `/api/deals/brands`

Important deployment caveats:

- both `helios` and `helios-collector` must be restarted
- direct script runs need `PYTHONPATH=.` from repo root
- because `init_db()` still calls `Base.metadata.create_all(engine)`, new Alembic migrations must be safe against tables that may already exist on partially-upgraded environments

## Migrations

Relevant meal-deal migration chain:

- `d4c7e2a91f31_add_canonical_meal_deal_identity_tables.py`
- `e82fa4b1c3d9_add_deal_observations_and_applicability.py`
- `9ac3d7b5f112_add_deal_materializations_table.py`
- `c6f1e2a7b934_merge_meal_deal_heads.py`

Important note:

- the canonical meal-deal migrations were made idempotent because tables may already exist from `create_all()` on some environments before Alembic stamping catches up

## Validation Status

Focused test coverage currently includes:

- observation and applicability dual-write
- shared-site fan-out collapsing into one observation
- chain-brand applicability expansion
- rejected observations retained as evidence
- API stats and brands using the shared semantic layer
- website debug-cache replay
- canonical identity backfill behavior

Live production deployment on the Orange Pi completed successfully with:

- canonical identity rebuild:
        - `canonical_venues`: 5,369
        - `venue_aliases`: 5,662
        - `site_identities`: 2,313
        - `site_assignments`: 2,811
- historical backfill:
        - `meal_deals_scanned`: 3,392
        - `observations_inserted`: 1,325
        - `applicability_targets`: 3,116
        - `materializations_inserted`: 3,684
- live stats response after deploy:
        - `total_deals`: 2,230
        - `restaurant_count`: 548
        - `brand_count`: 368

## Known Caveats

1. `meal_deals` is still written and still contains mixed legacy semantics.
2. Historical accepted rows can still be noisy because the backfill preserves old activity state rather than re-auditing every row.
3. A lightweight review queue now exists via `/api/deals/review-queue`, but resolution is still manual and there is no write-back workflow yet.
4. Some legacy dedupe helpers still exist in route code for transition and test coverage, even though the live read path now uses `deal_materializations`.
5. The next quality audit should focus on accepted `website_scrape` observations with sentence-like or review-like deal names.

## Current Recommendation On `meal_deals`

`meal_deals` should remain dual-written for now, but only as a temporary compatibility layer.

Recommended path:

1. Keep dual-write through the current audit and repair cycle while canonical re-audit and operator review workflows stabilize.
2. Make canonical tables plus `deal_materializations` the only semantic source of truth.
3. Once deploys show stable parity, convert `meal_deals` into a fully derived compatibility table or retire it from live writes entirely.

Reasoning:

- the API no longer depends on `meal_deals`
- historical repair now belongs in `deal_observations` and `deal_materializations`
- continuing to treat `meal_deals` as a first-class write target long term keeps the old mixed semantics alive

## Module Map

```text
collectors/meal_deals/
├── models.py                         # DealSignal dataclass
├── ingest.py                         # canonical write path + compatibility write
├── semantic_layer.py                 # refresh_deal_materializations()
├── quality.py                        # signal quality + value scoring
├── sub_deals.py                      # multi-offer decomposition
├── temporal.py                       # temporal parsing/refinement helpers
├── chain_deals.py                    # chain-site collector
├── website_scraper.py                # site scraping + debug cache + replay
├── gbp_offers.py                     # GBP offers collector
├── manual_ingest.py                  # CSV/JSON human input path
└── routes.py                         # /api/deals read layer

scripts/
├── backfill_meal_deal_identity.py    # rebuild canonical venue/site identity
└── backfill_deal_observation_history.py

core/
├── database.py                       # ORM models, init_db, sessions
├── scheduler.py                      # collector runs + meal-deal lineage hookup
└── venue_identity.py                 # shared identity heuristics

alembic/versions/
├── d4c7e2a91f31_add_canonical_meal_deal_identity_tables.py
├── e82fa4b1c3d9_add_deal_observations_and_applicability.py
├── 9ac3d7b5f112_add_deal_materializations_table.py
└── c6f1e2a7b934_merge_meal_deal_heads.py
```

## Bottom Line

The meal-deal ingestion system now has one coherent runtime story:

- collectors emit `DealSignal`
- ingest writes canonical observations and applicability
- semantic rows are materialized explicitly
- API endpoints read one shared deal layer

The major remaining work is no longer schema shape. It is data quality and operator workflow:

- re-auditing noisy accepted observations
- adding review tooling for disputed site or venue mappings
- deciding how far to collapse `meal_deals` once the canonical stack has proven stable
