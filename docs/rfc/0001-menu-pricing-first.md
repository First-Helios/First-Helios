# RFC-0001: Menu-and-pricing-first data collection

**Status:** Accepted
**Date:** 2026-07-31
**Accepted:** 2026-07-31 by the project owner
**Author(s):** Claude (agent), decisions ratified by project owner

## Summary

Re-scope V2 so that **menu and item-price coverage across Austin/Round Rock
is the primary deliverable**, with meal deals becoming a later layer on top
of the menu graph. This RFC is the implementation guide for the data
collection stage: what data we need, where it comes from, how it is modeled
so the project can later scale to all of Texas/USA and to non-food price
verticals, how freshness is maintained, and how conflicting sources are
reconciled. It is written to be handed to a worker agent as the spec for the
next PR train.

## Motivation

The current ROADMAP is deals-first ("menus: schema now, population Phase
10"). The owner has inverted that priority (2026-07-31): the product is a
**price index of food in the Austin/Round Rock area** — as many venues as
possible with menu items and prices — with deals as a derived layer later,
and other service verticals (auto repair, plumbing, …) as a possible future
extension of the same machinery.

This is the right time to decide: Phase 1 (domain model) is next, and schema
is the expensive-to-reverse part. The schema must serve the menu/price-index
product from day one.

V1 already validated most of this direction before the reset: it had a menu
graph (`MenuPage/Section/Item/PricePoint/Modifier/OfferTarget`), a JSON-LD +
DOM extraction pipeline (`menu_sidecar.py`), a Food Price Index API
(`price_index_routes.py`), and free-data venue discovery (Overture + OSM).
V2 ports those patterns onto a clean, normalized, provenance-first schema.

## Decisions already ratified by the owner (2026-07-31)

These are settled; the worker agent should not re-open them.

1. **Menus first.** Menu + pricing coverage is the V2 product. Deals become
   a later layer on the menu graph (V1's `MenuOfferTarget` pattern).
2. **Source policy: first-party + structured public data.** Restaurant-owned
   websites and their linked menus (HTML, PDF), plus schema.org/JSON-LD
   structured data any site publishes for machine consumption. **No
   scraping of aggregators or delivery platforms** (Yelp, Google, DoorDash,
   UberEats) — ToS-prohibited, and delivery prices don't reflect in-store
   prices anyway.
3. **Extraction: rules first, LLM fallback.** JSON-LD and DOM heuristics
   handle the easy majority for free. An LLM extraction pass runs **only**
   on pages that fail rule-based extraction. This adds a runtime dependency
   and API cost → **requires ADR-0007 with a budget cap before any LLM code
   is written** (see Unresolved questions).
4. **Freshness/scale target:** ~monthly re-scrape cadence with change
   detection. First milestone: **300+ Austin/Round Rock venues with priced
   menu items.**

## Detailed design

### D1. Guiding principles

These principles are what make the design scale beyond Austin and beyond
food. Every schema and pipeline decision below follows from them.

1. **Prices are observations, not attributes.** A price is never a mutable
   column on an item; it is an append-only `price_observation` row with
   `observed_at`, source, and confidence. "Current price" is a *derived*
   view (most recent accepted observation). This gives freshness
   measurement, conflict resolution, and price history for free.
2. **Provenance on everything.** Every row traces to a captured page
   (replay bundle) via `first_seen_at` / `last_seen_at` / `observed_at` and
   a source reference. This is the roadmap's "trustworthy" North Star made
   mechanical.
3. **Region-agnostic schema.** Nothing hardcodes Austin. Venues carry
   lat/lng + H3 cells; "Austin/Round Rock" is a query-time filter (H3
   cells / bounding region), plus a `region` scoping concept on crawl
   config only. Scaling to Texas/USA is a data problem, not a schema
   migration.
4. **Vertical-agnostic core.** `venue` and the observation pattern are not
   food-specific. The menu graph *is* food-specific and lives in its own
   tables. A future "services price index" (plumbers, mechanics) adds a
   parallel offering-graph without touching venue identity, discovery, or
   the observation machinery. Do **not** build the generic abstraction now
   (CLAUDE.md: no "for later" scaffolding) — just don't put food-specific
   columns on `venue`.
5. **Idempotent by construction.** Deterministic natural keys everywhere
   (V1's sidecar-key pattern) so re-running any scrape or replaying any
   bundle produces zero duplicates.

### D2. Data model (canonical schema)

Three-layer split per ROADMAP §4.3 (`raw` / `canonical` / `mart` — see
[ADR-0003](../adr/0003-three-layer-schema.md), **Accepted** 2026-08-01).

**`canonical` — venue identity** (Phase 1a; grows the existing `Venue` stub)

- `venue` — canonical physical location. `name`, `brand_id?`, normalized
  address fields, `lat`, `lng`, `h3_r8` (+ r6/r9 as needed), `status`
  (open/closed/unknown), timestamps. No food-specific columns.
- `brand` — chain identity ("McDonald's") so chain-wide facts fan out.
  Independent venues simply have no brand.
- `venue_alias` — alternate names/spellings feeding the fingerprint matcher.
- `venue_source` — where we know this venue from (Overture ID, OSM ID,
  manual registry entry), one row per (venue, external source), with the
  external record's raw identity. This is the dedup/merge audit trail.
- `site_identity` — resolved website URL(s) per venue, with resolution
  method (`overture_website` | `osm_tag` | `manual`), canonicalized URL,
  `last_verified_at`, and liveness status. A venue may have 0..n sites;
  a site may serve many venues (chain sites).

**`canonical` — menu graph** (Phase 1b; port of V1
`menu_persistence_schema.py`, redesigned as SQLAlchemy 2.0 typed models)

- `menu_page` — a scraped page/document that contained menu content:
  `venue_id?` (nullable until identity resolution), `site_identity_id`,
  `url`, `source_kind` (`jsonld` | `dom` | `pdf` | `llm`), `renderer`
  (`static` | `playwright`), `first_seen_at`, `last_seen_at`,
  `content_hash`, `replay_bundle_ref`.
- `menu_section` — hierarchy under a page: `name`, `parent_section_id?`,
  `path`, `service_period?` (happy_hour/brunch/lunch/dinner/…), `course?`.
- `menu_item` — `section_id`, `name`, `description?`, `calories?`,
  `dietary_tags`, `first_seen_at` / `last_seen_at`.
- `price_observation` — **the atom of the whole system.** `menu_item_id`
  (or `section_id` for section-level pricing), `price_cents` (integer —
  never float money), `currency`, `variant?` (size/portion label),
  `source_kind`, `confidence` (0–1), `evidence` (short text excerpt),
  `observed_at`, `replay_bundle_ref`. **Append-only.** Note: V1 named this
  `MenuPricePoint`; renamed to make the observation semantics explicit and
  to leave room for non-menu verticals to share the naming convention.
- `menu_modifier` — "add avocado +$2": `label`, `price_delta_cents?`,
  `required`, scoped to item or section.

Constraints (Phase 1 reviewer's checklist applies): every enum a Postgres
`CHECK`; deterministic unique keys, e.g.
`menu_item(section_id, normalized_name)` and
`price_observation(menu_item_id, variant, source_kind, observed_at)`;
deliberate `ondelete` everywhere; a test per constraint.

**`raw`** — capture index: one row per fetch (`url`, `status`,
`content_hash`, `fetched_at`, `bundle_path`, `outcome`), pointing at HTML/PDF
bytes on disk in `var/replay/` (ROADMAP §4.5 replay-bundle pattern —
unchanged). Plus `raw.rejected_signals` (dead-letter with reason codes).

**`mart`** — derived read models, rebuildable at any time:

- `current_menu` — latest accepted price per (item, variant), with
  `as_of` and staleness age. This is what the API serves.
- `price_index_*` — aggregates for the price-index product (e.g., median
  entrée price per H3 cell / category), ported conceptually from V1's
  `price_index_routes.py`. Start with one view; add more only when an API
  endpoint needs them.

**Item canonicalization across venues** (needed for "cheeseburger price in
78704" queries) is **deliberately deferred**: V1 of the price index
aggregates by `course` + section heuristics, which V1 proved adequate. A
cross-venue item taxonomy (mapping "1/2 lb Angus Burger" ≈ "cheeseburger")
is its own hard problem — future RFC when aggregate queries prove
insufficient.

### D3. Discovery pipeline (coverage is the product)

Determines the coverage ceiling; runs before any menu scraping.

1. **Seed venues:** Overture Maps POI parquet, filtered to
   `food_and_beverage` within the Austin metro bounding box (config-driven
   polygon covering Austin + Round Rock; trivially extendable to other
   regions later). Refresh monthly. Expected thousands of candidate venues.
2. **Resolve websites:** Overture `websites` field first; fallback Overpass
   query for `website`/`contact:website` tags (port
   `osm_url_resolver.py` — V1 measured **~30–40% URL coverage** from free
   sources; treat that as the planning number, not a failure).
3. **Registry file:** `config/sources.yaml` remains the human-editable
   escape hatch — any known-good venue/site can be added by hand. Chain
   anchor sites (menu-bearing, per V1's `meal_deal_sources.yaml` analysis)
   are seeded here.
4. **Identity resolution:** every candidate passes through the Phase 4
   fingerprint/dedup machinery (name fingerprint + address normalization +
   proximity clustering; port `core/venue_identity.py`,
   `core/normalizer.py::make_fingerprint`). Geocode gaps via Nominatim
   (1 req/s, disk-cached).
5. **Crawl frontier:** for each live `site_identity`, locate menu-bearing
   URLs: try common paths (`/menu`, `/food`, `/menus`), sitemap entries
   matching menu patterns, and on-site links whose anchor text matches
   menu lexicon. Persist the discovered menu URL(s) on `site_identity` so
   re-scrapes skip discovery.

**Coverage math for the 300-venue milestone:** if Overture yields ~3–4k
food venues in the metro and ~35% have resolvable first-party sites, that's
~1,000–1,400 candidate sites; extracting priced menus from ~25–30% of those
clears 300. These are planning estimates to validate in the first spike —
record actuals in the phase retro.

### D4. Extraction ladder

Cheapest adequate method wins; each rung is attempted only if the previous
one failed to produce structured menu content. Port V1 `menu_sidecar.py` as
the core of rungs 1–2.

1. **JSON-LD / schema.org** (`Menu → MenuSection → MenuItem → Offer`).
   Highest fidelity, zero fragility. Always parsed when present.
2. **DOM heuristics** — heading + list/table item-price pairing, V1's
   service-period/course/modifier regexes, promotional-row filtering
   (deal-looking rows are *excluded* from menu prices and parked for the
   future deals layer). Confidence scored.
3. **Playwright rendering** — only per V1's `render_policy.py` escalation
   rules: static HTML structurally empty + evidence the page is
   menu-critical + per-run render budget. Deterministic URL-hash sampling
   for exploration. Port this policy; it is the thing that keeps a
   residential-bandwidth crawl affordable.
4. **PDF menus** — text-layer extraction (e.g. `pdfplumber`) feeding the
   same item-price pairing rules. Image-only PDFs fall through to rung 5.
5. **LLM fallback** — **gated on ADR-0007** (model choice, prompt contract,
   per-run budget cap, output schema = the same sidecar shape as rungs
   1–4, confidence marking `source_kind='llm'`). Runs only on pages where
   rungs 1–4 produced nothing but menu-lexicon evidence says a menu is
   present. Not in the first PR train.

All rungs emit the **same normalized sidecar structure** (V1's proven
bundle shape) → one ingest path → `canonical` tables. Every extraction
stores its replay bundle first; extraction is re-runnable from disk without
re-fetching (`helios backfill` pattern, ROADMAP Phase 6).

Scraping etiquette per ROADMAP Phase 5 is unchanged and non-negotiable:
robots.txt honored, real User-Agent, per-host token bucket, no
paywall/login bypass.

### D5. Freshness

- **Cadence:** default 30-day re-scrape per site, config-overridable
  per-source (chains change more often than the taco truck's WordPress
  site). Scheduler is cron-driven on the staging host (no queue service —
  adding one would be a stop-and-ask dependency).
- **Change detection:** re-fetch → compare `content_hash` against last
  capture. Unchanged → touch `last_seen_at` on surviving rows, record a
  cheap "confirmed" capture, skip extraction. Changed → full extraction;
  items no longer present get `last_seen_at` frozen (never deleted —
  disappearance is information).
- **Staleness is surfaced, not hidden:** `current_menu` carries
  `as_of`/staleness; the API exposes it; a Prometheus gauge tracks
  staleness distribution and scrape failure rate. Freshness SLO for the
  milestone: **≥80% of covered venues observed within 45 days.**
- **Adaptive cadence** (later, not first train): per-source change-rate
  informs re-scrape priority — sites that never change drift toward the
  cadence floor, volatile ones toward the ceiling.

### D6. Conflict resolution

When two sources disagree about the same fact (e.g., JSON-LD says $9.99,
DOM parse says $12 for the same item):

1. Nothing is overwritten — both become `price_observation` rows.
2. `current_menu` resolution order: **(a)** source-kind trust ranking
   `jsonld > dom > pdf > llm`, **(b)** recency within the same rank,
   **(c)** confidence score as tie-breaker.
3. Contradictions within a short window (same item, same variant, price
   delta > threshold, < 7 days apart) are flagged to a review queue
   (`mart` view + reason code), not silently resolved — V1's
   expectation-diff pattern generalized.
4. First-party beats everything by policy — moot today (first-party only)
   but the ranking column is why adding a source class later is a config
   change, not a migration.

### D7. What this deliberately does not build yet

- Cross-venue item taxonomy (see D2).
- Deals/offers extraction (parked rows only; the `MenuOfferTarget` pattern
  ports later, on top of a populated menu graph).
- Non-food verticals — validated only in the negative: no food-specific
  columns on `venue`/identity tables.
- Multi-region crawl config beyond a parameterized bounding polygon.
- Any queue/cache/search-index service.

## Work plan (PR train for the worker agent)

Sequenced, review-sized PRs. Every PR: green `make ci`, conventional
commit, real test plan in the body. Stop-and-ask triggers from CLAUDE.md
apply throughout — **all schema PRs (1–3) touch
`packages/**/db/models/**` and `alembic/versions/**` and therefore get the
owner's careful read.**

| # | PR | Contents | Done when |
|---|----|----------|-----------|
| 0 | `docs: adopt RFC-0001` | This RFC accepted; ROADMAP amended (see below); ADR-0003 (three-layer schema) written | Owner merges |
| 1 | `feat(db): venue identity schema` | `brand`, grown `venue`, `venue_alias`, `venue_source`, `site_identity` + migration + constraint tests | `alembic upgrade head`/`downgrade` clean; every constraint has a failing test |
| 2 | `feat(db): menu graph schema` | `menu_page`, `menu_section`, `menu_item`, `price_observation`, `menu_modifier` + migration + tests | Same bar |
| 3 | `feat(db): raw/mart layers` | Schema split (incl. `alembic/env.py` schema-allowlist fix), capture index, `current_menu` + first price-index view | Same bar; mart rebuildable from canonical |
| 4 | `feat(api): venues read endpoints` | ROADMAP Phase 2 as written (First Light: cursor pagination, ADR-0004, staging deploy) | Phase 2 "Done when" |
| 5 | `feat(discovery): Overture/OSM venue seeding` | Parquet ingest → `venue_source` → identity resolution (ports Phase 4 fingerprinting) → Nominatim geocode → H3 | 1000 Overture rows → <2% dup venues, <1% bad geocodes (hand-labeled 100-sample) |
| 6 | `feat(discovery): website + menu-URL resolution` | Overture/OSM URL resolver, canonicalization, liveness check, menu-URL frontier | Measured %-coverage reported for the metro |
| 7 | `feat(scraper): fetch + replay core` | ADR-0005 spike/decision first (ROADMAP Phase 5), then: rate-limited fetcher, replay bundles, capture index writes | Fixture-tested; no live calls in CI |
| 8 | `feat(extract): JSON-LD + DOM ladder` | Port `menu_sidecar.py` rungs 1–2 into `packages/helios_parsing/` (pure functions) + ingest to canonical | 20+ golden-file fixtures from real Austin sites; idempotent re-ingest proven |
| 9 | `feat(extract): render policy + PDF` | Port `render_policy.py`; Playwright path; pdfplumber rung | Escalation budget respected in tests |
| 10 | `feat(sched): monthly cadence + change detection` | Cron scheduling, content-hash skip, `last_seen_at` semantics, staleness metrics | Re-run on unchanged site produces 0 new canonical rows |
| 11 | `feat(api): price index endpoints` | `current_menu`-backed venue menu + first aggregate endpoint | Milestone measurable via the API itself |
| — | `docs(adr): 0007 LLM extraction fallback` | Proposed **only after** rungs 1–4 yield measured coverage; includes budget cap | Owner accepts before any implementation |

Milestone exit: **300+ distinct Austin/Round Rock venues with ≥1 priced
menu item each, ≥80% observed within 45 days, every price traceable to a
replay bundle** — measured by a query, stated in the retro.

## Roadmap amendments required (PR 0)

- §1 North Star: "meal deals" → "menu prices and meal deals", price index
  named as the product.
- §2 Scope: menus move from "schema now, population later" to primary;
  deals move to post-milestone; success criteria replaced with the
  milestone above.
- Phase table: Phase 3 (parsing) refocuses on menu extraction (sub-deal /
  temporal parsers deferred with the deals layer); Phase 5–6 refocus per
  the work plan; Phase 10 "menus" becomes "deals layer".
- §8 Open Questions: add item-canonicalization and non-food verticals.

## Drawbacks

- First-party-only caps coverage; many independents have no usable site.
  Accepted: trustworthy in-store prices > inflated delivery prices.
- Monthly cadence means up to ~6 weeks of staleness worst-case. Accepted
  for V1; staleness is exposed, not hidden.
- Deferring item canonicalization limits price-index queries to
  category-level aggregates initially.
- The pivot re-orders roadmap phases again, one revision after the last
  restructure. Mitigated by PR 0 making the doc match reality before code.

## Alternatives

- **Deals-first (status quo):** rejected by owner — the product is the
  price index.
- **Aggregator/delivery scraping for coverage:** rejected — ToS, ban risk,
  and wrong prices.
- **LLM-primary extraction:** rejected — recurring cost multiplies with
  re-scrapes; rules handle the majority free.
- **Mutable `current_price` column:** rejected — loses history, freshness,
  and conflict-resolution capability that observations give for free.

## Unresolved questions

1. **ADR-0007 (LLM fallback):** model, prompt contract, budget cap —
   proposed only after rung 1–4 coverage is measured. Owner accepts.
2. **Austin-metro polygon definition** (which counties/H3 set) — small,
   but settle in PR 5 config with owner sign-off.
3. **Overture ingest mechanics** (DuckDB vs pyarrow for parquet filtering)
   — worker decides in PR 5; new dependency → note in PR body.
4. **Whether `price_observation` also serves the future services vertical
   or that vertical gets its own observation table** — decide when that
   vertical becomes real, not now.
