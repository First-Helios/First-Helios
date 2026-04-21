# Meal Deal Ingestion

Updated: 2026-04-21
Status: canonical identity, observation/applicability, semantic read-layer, replay bundles, menu-table backfill, and pre-flight tooling are live; active remediation now focuses on target hygiene, current-source precedence, canonical-row selection, and modeled gated offers; runtime renderer escalation is still pending

## Purpose

This document is the working reference for the meal-deal ingestion stack.

Use it when you need to understand or change:

- how collectors produce meal-deal signals
- how those signals are normalized into canonical storage
- how website scraper evidence is cached and replayed
- how consumer-facing deal rows are materialized for the API
- how operators validate, re-audit, and safely resume scraping

This file is intentionally broader than a schema note. It is meant to give a human or agent enough context to work safely in this subsystem without re-deriving the architecture from source every time.

## Roadmap Consolidation

This document now absorbs the still-useful foundation context from the retired meal-deal rollout roadmap.

What is already done and no longer belongs on the active roadmap:

- schema, collector registry, URL resolution, chain collection, website scraping, manual ingest, and deal read APIs all exist
- canonical observations, applicability, and materializations replaced the old mental model of `meal_deals` as the primary semantic source
- replay bundles, audit manifests, menu sidecars, forward-compatible persistence shapes, render-policy decisions, and exploration-only hints are live

What is still active work:

- keeping wrong-target and non-food sites out of the scrape queue
- preferring current and specific evidence over stale pages and summary rows
- using `offer_target` and value-profile metadata in downstream ranking and explanation
- modeling rewards, birthday, loyalty, and app-gated offers explicitly instead of treating them as generic promo chrome
- keeping the map-layer contract downstream of canonical read APIs rather than reviving a separate ingestion-era roadmap for it

Use `docs/guides/MEAL_DEAL_REMEDIATION_TRACKER.md` for the live fix checklist and `docs/guides/MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md` for the broader scraper-task inventory.

## If You Only Remember Five Things

1. The API reads `deal_materializations`, not `meal_deals`.
2. Every collector still emits `DealSignal`; canonical ingest is the shared write contract.
3. The website scraper preserves structured menu evidence in replay bundles via `menu_sidecar` and `menu_persistence_shape`, and that shape can now be backfilled into persistent menu tables for query surfaces such as `/api/price-index`.
4. Replay-first debugging is the default operating mode. Sync cached bundles, run pre-flight, run a small canary, then widen the scrape.
5. `/api/deals/review-queue/actions` now has real write-back behavior for contested sites and venue-alias decisions, and those actions refresh affected canonical rows.

## Read This Before Changing Code

Read these files first when working in this area:

1. `collectors/meal_deals/website_scraper.py`
2. `collectors/meal_deals/menu_sidecar.py`
3. `collectors/meal_deals/menu_persistence_schema.py`
4. `collectors/meal_deals/render_policy.py`
5. `collectors/meal_deals/hint_registry.py`
6. `collectors/meal_deals/ingest.py`
7. `collectors/meal_deals/semantic_layer.py`
8. `collectors/meal_deals/routes.py`
9. `core/database.py`
10. `scripts/check_website_scrape_preflight.py`
11. `scripts/reaudit_deal_observations.py`
12. `docs/guides/MEAL_DEAL_REPLAY_WORKFLOW.md`
13. `docs/guides/MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md`
14. `docs/guides/MEAL_DEAL_REMEDIATION_TRACKER.md`

## System At A Glance

The live runtime looks like this:

```text
collector -> DealSignal
          -> collectors/meal_deals/ingest.py
              -> quality scoring and gate decision
              -> canonical observation upsert
              -> applicability sync
              -> compatibility write to meal_deals
              -> refresh_deal_materializations
          -> /api/deals, /api/deals/stats, /api/deals/brands

website_scraper.py also writes replay artifacts:
  page html + pdf text/tables + extracted signals + menu_sidecar
  + menu_persistence_shape + menu_persistence_summary
  + render_decisions + render_budget + hint provenance
  -> scripts/backfill_menu_tables.py -> menu_pages/menu_sections/menu_items/menu_price_points/menu_modifiers
  -> /api/price-index and /api/price-index/facets
```

The most important architectural split is this:

- canonical storage is still deal-centric: `DealSignal -> deal_observations -> deal_applicability -> deal_materializations`
- upstream website extraction is becoming menu-aware: structured menu evidence is preserved in debug bundles and signal metadata so value profiling and target linking can improve without committing to database schema too early

## What Is Authoritative

Use the right layer for the question you are asking.

| Question | Authoritative layer | Notes |
|---|---|---|
| What deals should the API show? | `deal_materializations` | Shared read layer for list, stats, and brands endpoints. |
| Why was a signal accepted, review-banded, or rejected? | `deal_observations` | Check `signal_quality`, `review_state`, `raw_scraped_text`, and `extraction_payload`. |
| Where does an observation apply? | `deal_applicability` | Venue- and brand-scope decisions live here. |
| Which physical venue is canonical? | `canonical_venues` and `canonical_venue_aliases` | `local_employers` is still a source layer, not the meal-deal authority. |
| Which website owns a URL? | `site_identities` and `site_assignments` | Review queue actions write back here. |
| What page or PDF produced a website scrape signal? | `data/cache/website_scrape_debug/*.json` | Replay bundles are the authoritative upstream evidence store. |
| What structured menu graph did the scraper infer? | `menu_sidecar` and `menu_persistence_shape` in debug bundles for replay provenance; `menu_pages`, `menu_sections`, `menu_items`, `menu_price_points`, and `menu_modifiers` for persisted queryable menu data | Replay bundles remain the upstream evidence store; menu tables are the read path. |
| What still exists for compatibility only? | `meal_deals` | Still dual-written, but no longer the primary semantic source. |

## Core Runtime Objects

### `DealSignal`

Defined in `collectors/meal_deals/models.py`.

This is still the collector contract. Every collector emits `DealSignal` objects with:

- venue hints: `restaurant_name`, `address`, `lat`, `lng`, `brand_fingerprint`, `local_employer_id`
- deal fields: `deal_name`, `deal_description`, `deal_type`
- pricing fields: `price`, `price_type`, `discount_percentage`, `original_price`, `menu_avg_price`
- temporal fields: `valid_days`, `valid_start_time`, `valid_end_time`, `start_date`, `end_date`
- provenance: `source`, `source_url`, `collector_run_id`, `raw_scraped_text`
- scoring fields: `signal_quality`, `deal_value_score`, `sub_deals`
- extensibility: `metadata`

Important implementation detail:

- `signal.metadata` is carried into `deal_observations.extraction_payload["metadata"]`
- `signal.sub_deals` is carried into `deal_observations.extraction_payload["sub_deals_hint"]`

That means scraper-side metadata such as offer-target linking, value-profile hints, or hint provenance survives canonical ingest even though the menu graph also has a separate persistent-table path for Price Index and related menu queries.

### `MenuSidecar`

Defined in `collectors/meal_deals/menu_sidecar.py`.

This is the structured upstream menu graph currently preserved in replay bundles. It holds:

- `pages`
- `sections`
- `items`
- `price_points`
- `modifiers`
- `offer_targets`

It also derives:

- course-level price medians
- section-level price medians
- site-level `value_profile`
- offer-target confidence and disposition

### `PersistentShape`

Defined in `collectors/meal_deals/menu_persistence_schema.py`.

This is the row shape used by `menu_db_writer.py` and `scripts/backfill_menu_tables.py` to populate the persistent menu graph. It is not a SQLAlchemy model. It also lets replay bundles lock in a stable schema between scraper extraction and DB writes.

### Persistent menu tables

The menu graph now has a persistent read path alongside the replay corpus:

- `menu_pages`
- `menu_sections`
- `menu_items`
- `menu_price_points`
- `menu_modifiers`

These tables are populated from `menu_persistence_shape` through `collectors/meal_deals/menu_db_writer.py`, either during targeted write paths or via `scripts/backfill_menu_tables.py` when replay bundles need to be materialized after a scraper change.

### `RenderDecision`

Defined in `collectors/meal_deals/render_policy.py`.

This is an audit-only decision record for whether a page should be escalated to a renderer. The current scraper does not call Playwright at runtime yet. It only logs these decisions into the bundle so escalation thresholds can be tuned before runtime wiring.

### `Hint`

Defined in `collectors/meal_deals/hint_registry.py`.

Hints are exploration-only probes for hidden first-party pages. They are never first-party evidence by themselves.

## Canonical Storage Model

### Identity tables

#### `canonical_venues`

One row per physical venue for meal-deal identity.

Use this when the question is: "Which physical place should this deal attach to?"

Key fields:

- canonical name and normalized name
- normalized address and display address
- lat/lng and region
- optional `brand_group_id`
- `site_status`

#### `canonical_venue_aliases`

Maps `local_employers` rows into canonical venues.

Use this when the question is: "Are these multiple raw employer rows actually one venue?"

Key fields:

- `canonical_venue_id`
- `local_employer_id`
- `alias_role`
- `match_method`
- `match_confidence`

#### `site_identities`

Canonical website identity, separate from raw `restaurant_urls` storage.

Use this when the question is: "What site is this normalized URL, and what is its ownership state?"

Key fields:

- `normalized_url`
- `canonical_url`
- `host`, `path`
- `ownership_scope`
- `conflict_state`

#### `site_assignments`

Maps a canonical site to venue or brand scope.

Use this when the question is: "Does this site belong to one venue, a brand, or is it contested?"

Key fields:

- `site_identity_id`
- `canonical_venue_id`
- `brand_group_id`
- `assignment_scope`
- `match_method`
- `match_confidence`
- `is_primary`

### Canonical deal tables

#### `deal_observations`

One row per observed deal artifact.

This is the canonical evidence table and the first place to look when debugging collector behavior.

Key fields:

- `source`
- `collector_run_id`
- `site_identity_id`
- `source_url`
- `source_observation_key`
- deal detail, pricing, temporal, nutrition, raw text fields
- `extraction_payload`
- `signal_quality`
- `deal_value_score`
- `review_state`

Important rules:

- uniqueness is enforced by `(source, source_observation_key)`
- `review_state` is `accepted`, `review`, or `rejected`
- rejected observations are retained as evidence even when they do not materialize into active consumer rows

`extraction_payload` currently carries the most important non-column data:

- venue hints
- region
- collector metadata
- `sub_deals_hint`

#### `deal_applicability`

Resolved applicability targets for an observation.

This is where the system records whether an observation applies to:

- one venue
- one brand

Key fields:

- `observation_id`
- `applicability_scope`
- `canonical_venue_id`
- `brand_group_id`
- `confidence`
- `resolver_method`
- `resolver_notes`
- `is_active`

#### `deal_materializations`

Consumer-facing rows derived from observations plus applicability.

This is the read layer for:

- `/api/deals`
- `/api/deals/stats`
- `/api/deals/brands`

Important rules:

- one observation can materialize to multiple venues
- review-banded observations can still materialize, but they will not be active
- API consumers should reason about this layer before looking at `meal_deals`

### Compatibility table

#### `meal_deals`

`meal_deals` is still dual-written because the project is still finishing the migration away from legacy semantics and because some operational workflows still depend on it.

Current policy:

- keep it for compatibility and transition
- do not treat it as the primary semantic source
- fix quality problems in canonical layers first

## Migration Chain

Relevant meal-deal migrations:

- `d4c7e2a91f31_add_canonical_meal_deal_identity_tables.py`
- `e82fa4b1c3d9_add_deal_observations_and_applicability.py`
- `9ac3d7b5f112_add_deal_materializations_table.py`
- `c6f1e2a7b934_merge_meal_deal_heads.py`

Operational caveat:

- `init_db()` still calls `Base.metadata.create_all(engine)`
- meal-deal migrations were made idempotent because partially upgraded environments may already have some tables

## Collectors And Their Responsibilities

### `chain_deals.py`

Chain-level first-party collector.

Expected behavior:

- emits brand-scoped `DealSignal`s
- canonical ingest resolves the brand and writes one chain template semantic row set

### `website_scraper.py`

First-party restaurant website scraper.

Expected behavior:

- loads eligible site groups from `restaurant_urls`
- scrapes each unique first-party site once
- extracts flat `DealSignal`s for canonical ingest
- preserves richer menu and page evidence in debug bundles for replay and future schema work

Important naming nuance:

- collector name is `website_scraper`
- emitted `DealSignal.source` is `website_scrape`

### `gbp_offers.py`

Google Business Profile collector.

Important naming nuance:

- collector name is `gbp_offers`
- emitted `DealSignal.source` is `gbp_offer`

### `manual_ingest.py`

Human-entered CSV or JSON input path.

Treat this as a supported path, but verify venue resolution behavior when extending it. The canonical pipeline is much stronger than it was before, but manual paths still deserve explicit end-to-end checks before relying on them for high-volume operations.

## Website Scraper Deep Dive

This is the most active area of the system and the main place where upstream extraction quality work is happening.

### Scrape target selection

`load_website_scrape_target_groups()`:

- joins `restaurant_urls` to active food and bar employers in a region
- optionally skips sites checked within the configured day window
- groups identical normalized URLs so alias employers do not each trigger a full scrape
- filters obvious non-first-party domain families before they consume queue slots

Current early-skip families:

- `social`
- `government`
- `directory`
- `other_nonrestaurant`

This queue-quality filter matters. It prevents obvious non-first-party rows from consuming `max_sites` budget before the scraper even starts.

### Scrape phases

For one site, `scrape_restaurant_website()` currently does this:

1. Determine the site family and skip obvious non-first-party domains.
2. Load or reset the site's debug bundle.
3. Probe hardcoded first-party paths such as `/`, `/menu`, `/specials`, `/deals`, `/lunch`, `/happy-hour`, `/promotions`, and `/offers`.
4. If the site is a locator host, try locator-to-corporate hint routing.
5. Discover additional same-domain deal pages from homepage links.
6. Discover and parse a bounded number of PDFs.
7. Extract both flat signals and structured menu artifacts.
8. Attach offer-target and value-profile metadata to signals when possible.
9. Record render-policy decisions for structurally empty but menu-critical pages.
10. Finalize the replay bundle.

### Discovery logic

Current discovery sources:

- hardcoded deal paths
- same-domain homepage links
- locator-host rules that jump from location subdomains to corporate pages
- exploration-only registry hints from `config/meal_deal_hint_registry.json`
- PDF discovery from fetched pages

Guardrails:

- the scraper stays scoped to the known restaurant site and clearly related first-party assets
- registry hints can only add candidate probes
- registry hints are never treated as evidence

### Extraction order

For each fetched page, `_extract_page_artifacts()` currently combines several passes:

1. DOM block extraction via `_extract_text_blocks()`
2. flat price extraction via `_extract_all_prices()`
3. text-block to `DealSignal` conversion
4. JSON-LD deal extraction via `_extract_jsonld_deals()`
5. sidecar ingestion from structured data, DOM fallback, and PDF tables

This is important: the output used by canonical ingest is still flat `DealSignal`, but the scraper now also tries to preserve enough structure to reason about item-price pairing, offer targets, and baseline menu pricing.

### `menu_sidecar`

The sidecar is the current upstream menu graph.

Sources:

- schema.org `Menu`, `MenuSection`, `MenuItem`, and `Offer` hierarchies
- DOM heading/list/table fallback extraction
- `pdfplumber` table extraction when a PDF menu is parseable

Artifacts preserved:

- menu pages
- menu sections
- menu items
- price points
- modifiers and add-ons
- offer targets linking promotions to an item, section, service period, or venue

Derived data preserved:

- `baselines.course_price_median`
- `baselines.section_price_median`
- `value_profile.courses`
- `value_profile.service_periods`
- `value_profile.offer_target_scopes`

Why this exists:

- to estimate normal venue spend rather than only recognize deal-like text
- to estimate savings relative to category or section baselines
- to support future meal-planning and explainability work

### Offer-target linking

`_link_signals_to_sidecar()` and `link_signal_to_target()` attach `signal.metadata["offer_target"]` when the scraper can connect a promotion to the menu graph.

Current target scopes:

- `item`
- `section`
- `service_period`
- `venue`

Each target carries:

- `confidence`
- `disposition` (`auto_accept`, `review`, `discard`)
- `match_method`

This metadata is preserved through canonical ingest inside `deal_observations.extraction_payload["metadata"]`.

### Value-profile attachment

`_attach_value_profile_from_sidecar()` narrows the sidecar's baseline knowledge down to the specific signal being emitted.

Current per-signal metadata may include:

- `course`
- `course_baseline`
- `section_baseline`
- `estimated_savings`
- `estimated_savings_pct`

This is deliberately narrower than storing a full aggregate map on every observation.

### `menu_persistence_shape` and `menu_persistence_summary`

When a sidecar actually contains structure, `_finalize_site_debug_bundle()` also writes:

- `menu_persistence_shape`
- `menu_persistence_summary`

`menu_persistence_shape` flattens the sidecar into forward-compatible row sets for:

- pages
- sections
- items
- price points
- modifiers
- offer targets

`menu_persistence_summary` is the quick sanity view. It includes:

- schema version
- row counts by entity type
- `fk_violations`

Treat any non-empty `fk_violations` list as a bug in sidecar or serializer behavior.

When the scraper or menu extraction logic changes, the standard persistence follow-up is:

1. rerun the website scraper in replay or live mode
2. run `scripts/backfill_menu_tables.py`
3. run `scripts/audit_menu_price_index.py`
4. verify `/api/price-index` and `/api/price-index/facets`

### Render policy

`collectors/meal_deals/render_policy.py` is implemented, but runtime rendering is not yet wired.

What exists now:

- `PageEvidence`
- `RenderBudget`
- `RenderDecision`
- deterministic exploration sampling
- bounded main-budget escalation policy

What the scraper currently does:

- evaluate each fetched page after static extraction
- log `render_decisions` and `render_budget` into the debug bundle
- do not actually call Playwright yet

Why this matters:

- it lets the team measure how often static HTML is structurally empty on pages that appear menu-critical
- it keeps the future runtime escalation bounded and auditable

### Hint registry

`collectors/meal_deals/hint_registry.py` plus `config/meal_deal_hint_registry.json` provide a lightweight, exploration-only discovery layer.

Required provenance on each hint:

- `id`
- `brand`
- `hint_type`
- `source`
- `first_seen`
- `last_verified`
- `expires_at`
- `verified_against_url`

Hard rule:

- hints may influence what pages get probed
- hints may not be treated as first-party evidence

Whenever a hint is used, the scraper can attach a `hint_audit` payload so replay bundles distinguish hint-driven exploration from direct first-party discovery.

### Debug bundles

Website scraper debug bundles live under `data/cache/website_scrape_debug/`.

They are not just for ad hoc debugging. They are the replay corpus for upstream extraction work.

Typical bundle contents:

- site metadata
- fetched pages and their HTML
- fetched PDF text and extracted tables
- extracted signals
- discovered pages
- hinted pages
- `menu_avg_price`
- `menu_sidecar`
- `menu_persistence_shape`
- `menu_persistence_summary`
- `render_decisions`
- `render_budget`

Important nuance:

- `render_decisions` and `render_budget` should be present for fetched first-party pages in current canaries
- `menu_sidecar` and `menu_persistence_summary` are conditional and appear only when real structure was materialized
- `hint_audit` is conditional and appears only when hint-driven exploration was actually used

Do not treat the absence of `menu_persistence_summary` on a random site as a crash by itself. Treat it as a structure-coverage question unless the site is known to be menu-rich and static-parsable.

## Ingest And Gating

`collectors/meal_deals/ingest.py` is the shared canonical write path.

### What ingest does

For each `DealSignal`, ingest currently:

1. drops obvious junk deal names
2. derives `sub_deals` if the collector did not already populate them
3. computes `signal_quality`
4. computes `deal_value_score`
5. gates the signal into accepted, review, or rejected state
6. resolves brand scope or single-venue scope
7. builds `source_observation_key`
8. upserts one canonical observation row
9. synchronizes desired applicability rows
10. writes compatibility `meal_deals` rows when appropriate
11. refreshes `deal_materializations`

### Quality thresholds

Defined in `collectors/meal_deals/quality.py`.

| Score band | Decision | Canonical effect | Consumer-facing effect |
|---|---|---|---|
| `< 0.20` | reject | observation kept as evidence with `review_state=rejected` | no active materialization |
| `0.20 <= score < 0.40` | review | observation kept with `review_state=review` | materialization may exist but is not active |
| `>= 0.40` | accepted | observation kept with `review_state=accepted` | active materialization if applicability is active |

Quality factors currently include:

- usable pricing
- temporal information
- description quality
- name quality
- restaurant match heuristic
- add-on avoidance

### Temporal extraction

Defined in `collectors/meal_deals/temporal.py`.

This module normalizes:

- day ranges like `Mon-Fri`
- aliases like `Daily`, `Weekdays`, `Weekends`
- time ranges like `3:00 PM-6:00 PM`
- `Close` as a supported end-of-day sentinel

### Sub-deal decomposition

Defined in `collectors/meal_deals/sub_deals.py`.

This module decomposes multi-offer blocks into structured `sub_deals` only when it can confidently detect two or more distinct offers. It is deliberately conservative.

## Semantic Materialization Layer

`collectors/meal_deals/semantic_layer.py` builds `deal_materializations`.

What it does:

- loads observations plus applicability rows
- resolves venue context through canonical venues and aliases
- expands brand-scope applicability to the relevant canonical venues
- chooses the best row per `(observation_id, canonical_venue_id)`
- rebuilds `deal_materializations`

Why it matters:

- this is where canonical observations become per-venue consumer rows
- it replaces route-level dedupe hacks with one shared semantic layer
- API consistency depends on this layer being correct

## API And Operator Surfaces

### Read APIs

Current canonical read endpoints:

- `/api/deals`
- `/api/deals/stats`
- `/api/deals/brands`

These endpoints read `deal_materializations`, not `meal_deals`.

### Review queue

`/api/deals/review-queue` surfaces two classes of operator work:

- contested sites
- ambiguous venue aliases

This queue is intentionally lightweight. It is meant to guide manual resolution of the canonical identity layers that affect scraping and materialization.

### Review queue write-backs

`/api/deals/review-queue/actions` now performs real write-back actions.

Current site actions:

- resolve contested site to one venue
- resolve contested site to one brand
- block the site

Current venue-alias actions:

- confirm alias
- reassign alias to another canonical venue
- remove alias

Important behavior:

- site actions update `site_identities` and `site_assignments`
- venue-alias actions update `canonical_venue_aliases`
- venue-alias actions also repair matching `deal_applicability` rows for observations whose `local_employer_id_hint` points at that employer
- those repairs trigger `refresh_deal_materializations()` so API rows update immediately

This is the current authoritative answer to the question "does manual review actually write back into canonical state?" The answer is yes.

## Replay-First Workflow

Replay-first iteration is the expected workflow for website scraper improvements.

### Replay artifacts

Stored locally under:

- `data/cache/website_scrape_debug/`
- `data/cache/website_scrape_audit.json`

### Syncing from Orange Pi

`bash dev/sync_from_opi.sh` now syncs both canonical meal-deal tables and website scrape replay artifacts by default.

It syncs:

- `restaurant_urls`
- `meal_deals`
- `deal_observations`
- `deal_applicability`
- `deal_materializations`
- `data/cache/website_scrape_debug/`
- `data/cache/website_scrape_audit.json`

Flags:

- `--dry-run` compares row counts only
- `--skip-cache` skips replay cache sync

Requirements:

- local schema already migrated
- `ssh`, `psql`, and `tar` available
- remote access to the Orange Pi

### Pre-flight gate

Run this before starting a new live scrape:

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0
```

What it checks:

- imports for scraper-side modules
- replay cache path readiness
- hint-registry load validity
- target query health and family mix
- optional remote SSH reachability

### Canary flow

Recommended canary command:

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --max-sites 5 --skip-checked-days 0 --dry-run --region austin_tx
```

Inspect the newest bundles after the canary.

Expected on fetched first-party pages:

- `render_decisions`
- `render_budget`

Expected only when applicable:

- `menu_persistence_summary`
- `hint_audit`

If `menu_persistence_summary` is present, `fk_violations` should be empty.

For the full replay-first guide, see `docs/guides/MEAL_DEAL_REPLAY_WORKFLOW.md`.

## Local Validation And Rebuild Workflows

### Standard local validation order

```bash
cd /home/fortune/CodeProjects/First-Helios

bash dev/sync_from_opi.sh
.venv/bin/alembic upgrade head
PYTHONPATH=. .venv/bin/python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --max-sites 5 --skip-checked-days 0 --dry-run --region austin_tx
PYTHONPATH=. .venv/bin/python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx
.venv/bin/python -m pytest tests/HeliosDeployment/test_meal_deal_first_pass.py tests/HeliosDeployment/test_website_scrape_debug_cache.py tests/HeliosDeployment/test_website_scrape_sidecar_replay.py tests/HeliosDeployment/test_menu_sidecar.py tests/HeliosDeployment/test_menu_persistence_schema.py tests/HeliosDeployment/test_render_policy.py tests/HeliosDeployment/test_hint_registry.py tests/HeliosDeployment/test_website_scrape_preflight.py tests/HeliosDeployment/test_meal_deal_target_export.py
```

### Full dataset rebuild

Use this when extractor behavior or canonical meal-deal semantics changed enough that existing rows are no longer trustworthy.

```bash
cd /home/fortune/CodeProjects/First-Helios

PYTHONPATH=. .venv/bin/python scripts/reset_meal_deal_dataset.py --apply --reset-url-state --clear-debug-cache
PYTHONPATH=. .venv/bin/python scripts/backfill_meal_deal_identity.py --region austin_tx
PYTHONPATH=. .venv/bin/python collectors/meal_deals/chain_deals.py --region austin_tx
PYTHONPATH=. .venv/bin/python -m collectors.meal_deals.gbp_offers --region austin_tx
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0 --chunk-size 25 --region austin_tx
```

### Re-auditing canonical observations

Use this when quality rules changed and you need the canonical layer to match current rules.

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx
PYTHONPATH=. .venv/bin/python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx --apply
```

Important behavior:

- by default the script does not promote previously reviewed or rejected observations back to accepted state unless `--allow-promotions` is supplied
- when observations change, the script refreshes affected `deal_materializations`

## Orange Pi Runtime And Deploy Notes

Current remote host details:

- host: `orangepi@192.168.1.191`
- repo: `/home/orangepi/First-Helios`
- overlay path used during recent dry-run canaries: `/home/orangepi/helios-overlay-website-targets`

Current remote command pattern:

```bash
ssh orangepi@192.168.1.191 '
  cd /home/orangepi/First-Helios &&
  set -a && source .env && set +a &&
  PYTHONPATH=/home/orangepi/helios-overlay-website-targets:/home/orangepi/First-Helios \
  /home/orangepi/First-Helios/.venv/bin/python \
  /home/orangepi/helios-overlay-website-targets/collectors/meal_deals/website_scraper.py \
  --max-sites 5 --skip-checked-days 0 --dry-run --region austin_tx
'
```

Important caveats:

- remote parity is currently operational but still manual
- overlay-only sync is not enough if imports resolve against the repo tree and required modules are missing there
- pre-flight can verify SSH reachability, but it does not guarantee remote file parity by itself

When deploying real changes remotely:

1. sync or pull runtime files and migrations
2. run Alembic upgrade
3. rebuild or re-audit if needed
4. restart both `helios` and `helios-collector`
5. verify `/api/deals`, `/api/deals/stats`, and `/api/deals/brands`

## Common Debugging Questions

### A signal is in the debug bundle but not in the API

Check, in order:

1. `deal_observations.review_state`
2. `deal_observations.signal_quality`
3. `deal_applicability` rows and `is_active`
4. `deal_materializations` rebuild state
5. whether the run was `--dry-run`

### A bundle has no `menu_persistence_summary`

This is only a problem if the page was expected to yield structured menu evidence. Otherwise it may simply mean the site had no parseable JSON-LD, DOM structure, or PDF table extraction worth persisting.

### `fk_violations` is non-empty in `menu_persistence_summary`

Treat this as a structural bug. The serializer or sidecar builder produced an internally inconsistent graph.

### A site scraped the wrong domain or a social URL

Check:

- `restaurant_urls`
- target-group filtering behavior
- `_SKIP_DOMAIN_FAMILIES`
- `classify_domain_family()`
- `site_identities` and `site_assignments`

### A deal name looks like a sentence or marketing copy

Check:

- bundle `raw_scraped_text`
- `_extract_deal_name()` in `website_scraper.py`
- quality penalties in `quality.py`

## Test Coverage That Matters

The most important regression tests in this area currently include:

- `tests/HeliosDeployment/test_meal_deal_first_pass.py`
- `tests/HeliosDeployment/test_website_scrape_debug_cache.py`
- `tests/HeliosDeployment/test_meal_deal_quality_and_reaudit.py`
- `tests/HeliosDeployment/test_website_scrape_sidecar_replay.py`
- `tests/HeliosDeployment/test_menu_sidecar.py`
- `tests/HeliosDeployment/test_menu_persistence_schema.py`
- `tests/HeliosDeployment/test_render_policy.py`
- `tests/HeliosDeployment/test_hint_registry.py`
- `tests/HeliosDeployment/test_website_scrape_preflight.py`
- `tests/HeliosDeployment/test_meal_deal_target_export.py`

When changing scraper discovery, DOM extraction, sidecar logic, hint handling, render policy, or pre-flight behavior, update or add replay-based tests before widening live crawl breadth.

## Known Caveats And Remaining Work

These are the current meaningful caveats, not historical ones.

1. `RENDER-01` is still open. Render policy exists, but runtime Playwright escalation is not wired into `website_scraper.py` yet.
2. Wrong-target ingress is still not fully blocked. Hotel-family hosts, clearly unrelated businesses, and isolated bad URL assignments can still survive into the website scrape queue unless they are purged or filtered earlier.
3. Stale-source precedence and canonical row ranking still need work. Older HTML or broad summary rows can beat newer PDFs or more specific sibling offers because read-path ranking still leans too heavily on `signal_quality` and recency.
4. The menu graph is replay-first, not table-first. Persistent menu tables now exist, but replay bundles remain the authoritative upstream evidence and the place where full sidecar provenance lives.
5. Remaining open Tier 2 scraper tasks still matter: `DISC-03`, `DOM-01`, `NAME-01`, `PRICE-01`, `PDF-01`, and `TEST-02`.
6. Rewards, birthday, loyalty, and app-gated offers are not explicitly modeled yet. Current boilerplate and non-deal filters suppress much of that family by design.
7. Remote Orange Pi parity is still maintained manually. That is workable, but brittle.
8. `meal_deals` is still dual-written and still contains legacy semantics. Do not use it as the primary read model.
9. Source naming is still inconsistent in a few places, for example `website_scraper` versus `website_scrape` and `gbp_offers` versus `gbp_offer`.
10. Some module docstrings and older docs still reflect the pre-canonical or pre-sidecar model. Prefer this document, the remediation tracker, the roadmap, and the replay guide when they disagree.

For the active implementation queue, use both `docs/guides/MEAL_DEAL_REMEDIATION_TRACKER.md` and `docs/guides/MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md`.

## Module Map

```text
collectors/meal_deals/
├── models.py                         # DealSignal contract
├── ingest.py                         # canonical write path + compatibility write
├── semantic_layer.py                 # rebuilds deal_materializations
├── quality.py                        # signal-quality and value scoring
├── temporal.py                       # day/time extraction helpers
├── sub_deals.py                      # multi-offer decomposition
├── website_scraper.py                # first-party website scraping + replay bundle writing
├── menu_sidecar.py                   # structured menu graph extraction and offer-target linking
├── menu_persistence_schema.py        # forward-compatible row shape + FK checks
├── menu_db_writer.py                 # persistent menu-table upsert from menu_persistence_shape
├── render_policy.py                  # audit-only render escalation policy
├── hint_registry.py                  # exploration-only hidden-page hint layer
├── chain_deals.py                    # chain collector
├── gbp_offers.py                     # Google Business Profile collector
├── manual_ingest.py                  # human-entered input path
├── routes.py                         # /api/deals read APIs + review queue actions
└── price_index_routes.py             # /api/price-index read APIs over persisted menu tables

scripts/
├── check_website_scrape_preflight.py # scrape-readiness gate
├── reaudit_deal_observations.py      # canonical quality re-audit
├── backfill_menu_tables.py           # materialize persistent menu tables from replay bundles
├── audit_menu_price_index.py         # audit persisted menu quality before or after a rerun
├── backfill_meal_deal_identity.py    # rebuild canonical venue/site identity
├── backfill_deal_observation_history.py
└── reset_meal_deal_dataset.py

core/
└── database.py                       # ORM models, sessions, init_db

data/cache/
├── website_scrape_debug/             # replayable per-site bundles
└── website_scrape_audit.json         # audit snapshot
```

## Bottom Line

The meal-deal system now has a coherent canonical runtime model and a separate replay-first upstream evidence model.

The canonical runtime answers:

- what was observed
- where it applies
- what the API should show

The website scraper replay layer preserves the harder upstream questions the canonical schema does not yet store directly:

- what menu structure was found
- what normal category pricing looks like
- what a promotion appears to target
- whether a page should have escalated to rendering

If you are changing this subsystem, keep those two responsibilities separate:

- canonical tables must stay stable, explicit, and reviewable
- upstream scraper evidence should get richer without flattening back into unstructured text