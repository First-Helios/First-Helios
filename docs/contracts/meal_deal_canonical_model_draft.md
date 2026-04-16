# Data Contract Draft: canonical meal-deal model

> **Scope:** Meal deals
> **Created:** 2026-04-16
> **Status:** Draft
> **Purpose:** Replace alias-prone venue identity and mixed deal row semantics with a canonical venue layer plus an observation/applicability split.

---

## Why This Change Exists

The current meal-deal pipeline mixes three concerns in the same write/read path:

1. physical venue identity
2. scraped deal observation
3. per-location deal materialization

That is why the system currently needs:

- URL-level alias collapse in collectors
- read-time dedupe in the API
- chain-template flags inside `meal_deals`
- multiple repair and backfill scripts

This draft separates those concerns into stable contracts.

## Initial Kickoff Status

- Website scrape debug bundles now persist locally under `data/cache/website_scrape_debug` and can be replayed with `collectors/meal_deals/website_scraper.py --replay-debug-cache`.
- Canonical identity scaffolding now exists in the codebase:
	- ORM models in `core/database.py`
	- Alembic migration `d4c7e2a91f31_add_canonical_meal_deal_identity_tables.py`
	- rebuild script `scripts/backfill_meal_deal_identity.py`
- Current dry-run backfill on the local synced database produced:
	- `canonical_venues`: 5,369
	- `venue_aliases`: 5,662
	- `site_identities`: 2,313
	- `site_assignments`: 2,811
	- `shared_url_groups`: 538

## Target Model

### 1. Canonical venue identity

#### Table: `canonical_venues`

One row per physical venue.

| Column | Type | Nullable | Constraint / meaning |
|--------|------|----------|----------------------|
| id | BIGINT / UUID | No | PK |
| canonical_name | TEXT | No | Stable display name for the venue |
| normalized_name | TEXT | No | Search/match key |
| normalized_address | TEXT | Yes | Address identity key |
| address | TEXT | Yes | Best display address |
| lat | DOUBLE | Yes | Canonical venue latitude |
| lng | DOUBLE | Yes | Canonical venue longitude |
| region | TEXT | No | Region scope |
| brand_group_id | INTEGER | Yes | FK to `brand_groups` when known |
| site_status | TEXT | No | `single_site`, `shared_site`, `disputed_site`, `no_site` |
| is_active | BOOLEAN | No | Soft-delete / suppression |
| created_at | DATETIME | No | Server-managed |
| updated_at | DATETIME | No | Server-managed |

#### Table: `canonical_venue_aliases`

Maps existing location rows into canonical venues.

| Column | Type | Nullable | Constraint / meaning |
|--------|------|----------|----------------------|
| id | BIGINT / UUID | No | PK |
| canonical_venue_id | BIGINT / UUID | No | FK to `canonical_venues` |
| local_employer_id | INTEGER | No | FK to `local_employers`, unique |
| alias_role | TEXT | No | `primary`, `alias`, `legacy`, `suspect` |
| match_method | TEXT | No | `manual`, `address_name`, `url_geo`, `brand_override` |
| match_confidence | DOUBLE | Yes | 0.0–1.0 |
| notes | TEXT | Yes | Operator comments |
| created_at | DATETIME | No | Server-managed |
| updated_at | DATETIME | No | Server-managed |

#### Contract rules

- Every location-scoped deal shown to consumers must resolve through `canonical_venues`.
- `local_employers` remains a source/location table, not the canonical venue identity layer.
- Alias collapse logic should write here once, not be reimplemented in API endpoints.

### 2. Canonical site identity

#### Table: `site_identities`

One row per normalized website identity.

| Column | Type | Nullable | Constraint / meaning |
|--------|------|----------|----------------------|
| id | BIGINT / UUID | No | PK |
| normalized_url | TEXT | No | Unique identity key |
| canonical_url | TEXT | No | Best fetch URL |
| host | TEXT | No | Hostname |
| path | TEXT | Yes | Normalized path |
| ownership_scope | TEXT | No | `venue`, `brand`, `mixed`, `unknown` |
| conflict_state | TEXT | No | `clear`, `needs_review`, `blocked` |
| created_at | DATETIME | No | Server-managed |
| updated_at | DATETIME | No | Server-managed |

#### Table: `site_assignments`

Maps sites to venue or brand scope.

| Column | Type | Nullable | Constraint / meaning |
|--------|------|----------|----------------------|
| id | BIGINT / UUID | No | PK |
| site_identity_id | BIGINT / UUID | No | FK to `site_identities` |
| canonical_venue_id | BIGINT / UUID | Yes | FK when site is venue-scoped |
| brand_group_id | INTEGER | Yes | FK when site is brand-scoped |
| assignment_scope | TEXT | No | `venue`, `brand`, `fallback`, `contested` |
| match_method | TEXT | No | `osm`, `google_places`, `manual`, `audit_fix` |
| match_confidence | DOUBLE | Yes | 0.0–1.0 |
| is_primary | BOOLEAN | No | Primary assignment for reads |
| created_at | DATETIME | No | Server-managed |
| updated_at | DATETIME | No | Server-managed |

#### Contract rules

- `restaurant_urls` becomes an ingestion cache / legacy compatibility layer, not the authoritative ownership table.
- Scrapers should fetch per `site_identities` row, not per employer row.
- Disputed sites should stay queryable but blocked from uncontrolled fan-out.

### 3. Canonical deal observations

#### Table: `deal_observations`

One row per observed deal artifact from a source.

| Column | Type | Nullable | Constraint / meaning |
|--------|------|----------|----------------------|
| id | BIGINT / UUID | No | PK |
| source | TEXT | No | Collector/source key |
| collector_run_id | BIGINT | Yes | FK to collector runs when available |
| site_identity_id | BIGINT / UUID | Yes | FK to `site_identities` |
| source_url | TEXT | Yes | Original fetch URL |
| source_observation_key | TEXT | No | Stable per-source dedupe key |
| observed_at | DATETIME | No | Observation time |
| deal_name | TEXT | No | Extracted title |
| deal_description | TEXT | Yes | Extracted description |
| deal_type | TEXT | No | Normalized deal type |
| price | DOUBLE | Yes | Extracted price |
| price_type | TEXT | Yes | `absolute`, `discount_amount`, `percentage_off`, `unknown` |
| discount_percentage | DOUBLE | Yes | Optional |
| original_price | DOUBLE | Yes | Optional |
| menu_avg_price | DOUBLE | Yes | Optional |
| calories | INTEGER | Yes | Optional |
| calorie_price_ratio | DOUBLE | Yes | Optional |
| valid_days | TEXT | Yes | Optional |
| valid_start_time | TEXT | Yes | Optional |
| valid_end_time | TEXT | Yes | Optional |
| is_recurring | BOOLEAN | No | Default true |
| start_date | DATETIME | Yes | Optional seasonal bound |
| end_date | DATETIME | Yes | Optional seasonal bound |
| raw_scraped_text | TEXT | Yes | Required when source is scrape-based |
| extraction_payload | JSONB | Yes | Parser details / auxiliary metadata |
| signal_quality | DOUBLE | Yes | Quality score |
| deal_value_score | DOUBLE | Yes | Consumer value score |
| review_state | TEXT | No | `accepted`, `review`, `rejected`, `superseded` |
| superseded_by_observation_id | BIGINT / UUID | Yes | Self-FK for dedupe lineage |
| created_at | DATETIME | No | Server-managed |
| updated_at | DATETIME | No | Server-managed |

#### Contract rules

- Observation rows are immutable evidence, except for review-state transitions and supersession.
- No per-location duplication belongs in `deal_observations`.
- A chain page and a venue page can emit the same extracted offer, but that relationship is tracked via dedupe/supersession metadata rather than overwriting raw evidence.

### 4. Deal applicability / targeting

#### Table: `deal_applicability`

Declares where an observation applies.

| Column | Type | Nullable | Constraint / meaning |
|--------|------|----------|----------------------|
| id | BIGINT / UUID | No | PK |
| observation_id | BIGINT / UUID | No | FK to `deal_observations` |
| applicability_scope | TEXT | No | `venue`, `brand`, `venue_group` |
| canonical_venue_id | BIGINT / UUID | Yes | FK when venue-scoped |
| brand_group_id | INTEGER | Yes | FK when brand-scoped |
| confidence | DOUBLE | Yes | Resolver confidence |
| resolver_method | TEXT | No | `direct_site_match`, `brand_page`, `manual`, `inferred` |
| resolver_notes | TEXT | Yes | Optional operator/debug text |
| valid_from | DATETIME | Yes | Applicability start |
| valid_to | DATETIME | Yes | Applicability end |
| is_active | BOOLEAN | No | Soft lifecycle flag |
| created_at | DATETIME | No | Server-managed |
| updated_at | DATETIME | No | Server-managed |

#### Optional compatibility table or view: `deal_materializations`

Consumer-facing materialized rows, generated from `deal_observations` + `deal_applicability` + `canonical_venue_aliases`.

This can be:

- a materialized view if query cost is acceptable
- or a write-through table if mobile/API latency requires precomputation

#### Contract rules

- Brand-wide applicability is expressed once, not by duplicating the observation row into every location during ingest.
- Venue-specific applicability resolves to one `canonical_venue_id`, then optionally fans out to `local_employers` only in compatibility views.

## Interface Changes

### Collector output interface

Replace the current implicit mixed-scope `DealSignal` contract with two explicit phases.

#### `DealObservationSignal`

Collector-owned payload.

| Field | Meaning |
|------|---------|
| `restaurant_name` | Human-visible source label |
| `address` / `lat` / `lng` | Optional venue hints |
| `brand_fingerprint` | Optional brand hint |
| `source` / `source_url` | Provenance |
| `observed_at` | Observation time |
| extracted pricing / temporal / text fields | Canonical observation payload |
| `site_hint` | Optional normalized site identity hint |
| `applicability_hint` | `venue`, `brand`, or `unknown` |
| `metadata` | Parser-specific details |

#### `DealApplicabilitySignal`

Resolver-owned payload.

| Field | Meaning |
|------|---------|
| `observation_key` | Links to observation write |
| `canonical_venue_id` | Optional direct venue target |
| `brand_group_id` | Optional brand target |
| `scope` | `venue` or `brand` |
| `confidence` | Resolution confidence |
| `resolver_method` | Why this mapping exists |

### Ingest responsibilities

#### `ingest_deal_observations(signals)`

- writes one row per observation
- computes quality/value
- stores raw extraction evidence
- does not fan out to multiple employers

#### `resolve_deal_applicability(observation_ids)`

- resolves observation target to canonical venue or brand
- uses canonical site mappings first
- uses name/address fallback second
- records confidence and method

#### `build_deal_materializations()`

- expands applicability into consumer-ready rows or refreshes a view
- is the only place where per-location duplication is allowed

### API read contract

All `/api/deals*` endpoints should read from one semantic layer:

- `v_deal_cards_active`
- or `deal_materializations`

That layer must guarantee:

1. one row per consumer-visible venue/deal combination
2. no alias duplicates
3. chain applicability already expanded consistently
4. stats, brands, map cards, and detail views all share the same semantic base

## Migration Plan

### Phase 1: Identity scaffolding

1. Create `canonical_venues` and `canonical_venue_aliases`.
2. Backfill from current alias clustering logic.
3. Create `site_identities` and `site_assignments` from `restaurant_urls`.

### Phase 2: Dual-write observations

1. Keep current `meal_deals` writes active.
2. Add `deal_observations` writes from collectors.
3. Preserve `raw_scraped_text`, `metadata`, and parser artifacts in the new table.

### Phase 3: Applicability resolution

1. Resolve observations into `deal_applicability`.
2. Add manual review hooks for disputed sites and ambiguous venue matches.
3. Verify chain-page vs venue-page targeting.

### Phase 4: Read cutover

1. Build `deal_materializations` or `v_deal_cards_active`.
2. Move `/api/deals`, `/api/deals/stats`, `/api/deals/brands`, and map reads onto that layer.
3. Compare output parity against the current API.

### Phase 5: Legacy collapse

1. Stop writing new logic into `meal_deals` as the canonical source of truth.
2. Keep `meal_deals` only as a compatibility view/table during migration.
3. Remove endpoint-specific alias collapse once the semantic layer is authoritative.

## Non-Goals

- Replacing `local_employers` as the system-of-record for source business locations
- Rebuilding brand-group logic in this first migration
- Solving every historical duplicate automatically without review tooling

## Immediate Implementation Order

1. Build `canonical_venue_aliases` using the current venue-identity helper and audit outputs.
2. Introduce `site_identities` so website scraping operates once per normalized site.
3. Add `deal_observations` dual-write from `website_scraper`, `chain_deals`, `gbp_offers`, and `manual_ingest`.
4. Move the API to a shared materialized semantic layer before deeper collector expansion.