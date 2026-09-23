# ADR-0009: Venue discovery — source, ingestion, dedupe/minting, and schedule

**Status:** Accepted
**Date:** 2026-09-20
**Accepted:** 2026-09-20 by project owner Fortune
**Phase:** 4 (Venue Discovery, Identity & Geocoding)

## Context

Phase 2 ("First Light") shipped the venue read API — `GET /v1/venues`,
cursor-paginated ([ADR-0008](./0008-read-api-conventions.md)). It is served
from a fixed **5-venue dev seed** (`apps/api/seed.py`, since removed),
which mints Subjects **directly** via `create_organization` / `create_place` /
`create_establishment` with **no Bronze provenance**. That is deliberate
scaffolding for First Light, not a data path.

Phase 4 is the coverage subsystem: replace the seed with a real discovery
path that lands metro-scale Austin/Round Rock food venues in
`identity.establishment` **through the published Identity commands and Bronze
provenance**, so `/v1/venues` returns discovered venues. RFC-0001 §D3 and
ROADMAP Phase 4 are the accepted product spec (Overture/OSM seeding, website
resolution, `<2%` duplicate venues, `<1%` bad geocodes, measured website
coverage). Discovery unblocks the deferred Phase 7 price index.

This ADR settles the three new architectural choices CLAUDE.md gates on
before implementation: the **data source and ingest mechanics**, the
**dedupe/minting strategy**, and the **refresh schedule**. Owner decisions
made 2026-09-20 are folded in (see "Owner decisions" below); the remaining
open items are listed under **Stop-and-ask**.

### What the current code does and does not do

- `provenance.contracts.persist_source_record_observation` +
  `identity.commands.resolve_source_record_observation` persist a
  source-faithful record, capture, and evidence, then resolve it **only** by
  exact `(source, external_key)` or exact canonical URL. Unmatched records
  stay explicitly `unresolved`. **The resolver never mints Subjects and does
  no fuzzy matching** — minting Organization/Place/Establishment is a caller
  concern.
- `identity.commands` publishes minting (`create_*`), assignment
  (`assign_source_record`), and merge/split/retire (`record_subject_change`).
  These flush but do not commit; the caller owns the transaction so Bronze +
  Identity land atomically.
- `identity.organization.name_fingerprint` exists and is indexed;
  `identity.subject_name` stores aliases with indexed fingerprints. **There
  is no name-normalization / address-normalization / proximity code yet.**
- `identity.place` stores `address`, `latitude`, `longitude`
  (`Numeric(9, 6)`, bounded by CHECK constraints). **Coordinates are already
  the geo grain — no schema change is needed to seed discovered venues.**
- Runtime dependencies are `alembic, fastapi, psycopg, pydantic-settings,
  sqlalchemy, structlog, uvicorn`. There is **no parquet reader**, and
  `httpx` is a **dev-only** dependency.

### Owner decisions (2026-09-20)

1. **No H3.** Geo is **lat/lon only**. This removes the planned `Place`
   migration and the `h3` dependency; discovery is now **additive with zero
   schema change**.
2. **Viewing stage is interactive.** Consumers draw their own map
   boundaries and filter by category / tag / parameter — the ingest polygon
   is a coarse coverage bound, not the query filter (see §5).
3. **Orange Pi is in scope.** Discovery and the API run on the Orange Pi and
   the running service is reachable (viewable) from the dev machine over the
   LAN. This supersedes the earlier "do not touch the Pi" boundary for this
   line of work.
4. **Pure-helper placement is delegated** to the implementer's judgement for
   a well-organized codebase (resolved in §4).
5. **Parquet reader = DuckDB** (new runtime dep approved).
6. **Ingest bbox = Travis + Williamson counties**: lat `30.02 .. 30.85`,
   lon `-98.17 .. -97.37`.
7. **Dedupe auto-merge radius = 50 m** (with a name-fingerprint match).

### A concrete hazard the design must avoid

The resolver assigns by exact canonical URL when that URL currently
identifies exactly one Subject. If an Overture POI carried its **brand
website** (e.g. `torchystacos.com`) as the observation's `canonical_url`,
the first Torchy's location would mint a Subject and the second location
sharing that website would exact-URL match and **collapse two distinct
Establishments into one**. Brand-website equality is an Organization-level
signal, never an Establishment identity key. The ingestion grain keeps these
separate.

## Decision

Build discovery as a Bronze-first, idempotent, deterministic-by-default
pipeline that reuses the existing Identity/Bronze contracts and adds a thin
**minting** step and pure **normalization** helpers. No identity/menu/gold
schema changes.

### 1. Data source and ingest mechanics

- **Source:** Overture Maps **Places** theme (GERS), filtered to
  `category` in the `food_and_beverage` family, clipped to a **config-driven
  metro bounding box** — Travis + Williamson counties, lat `30.02 .. 30.85`,
  lon `-98.17 .. -97.37`; a parameter, never a constant.
  A bbox — not a precise polygon — is used at ingest so no geometry library
  is required; over-inclusion at discovery is harmless because viewing filters
  precisely (§5). Overpass/OSM and the `config/sources.yaml` manual registry
  are **follow-on units** (RFC-0001 PR 6, website + menu-URL resolution).
- **Read mechanic (decided):** **DuckDB** with the `httpfs` extension,
  reading the released Overture parquet and pushing the bbox + category
  filter down. Alternative: `pyarrow`. DuckDB is recommended because the
  filter and parquet pruning are one query and it reads the S3-hosted release
  without a full local download. **This is the one new runtime dependency**
  → stop-and-ask.
- **Bronze mapping — one POI → one `BronzeObservation`:**
  - `source_namespace = "overture"`, `source_kind = "poi_snapshot"`,
    `external_key = <GERS id>` — the only deterministic match key, unique per
    POI, so monthly re-ingest is idempotent and no cross-location merge can
    occur.
  - `source_payload` = the source-faithful POI row, **including its
    categories, tags, and attributes** so the viewing stage can filter on
    them later (§5); `content_hash` over that row so an unchanged POI re-uses
    its immutable version.
  - `evidence_locator` / `excerpt_hash` point at the parquet release + row
    (replay-safe); `bundle_path` records the release snapshot.
  - **`canonical_url` is left `None` on the Overture observation.** The
    website is retained in the payload and becomes an Organization-level
    identity signal in the website-resolution unit — never the
    Establishment's URL match key (see hazard above).
- **Geocoding:** Overture POIs already carry lat/lon; use them directly.
  Nominatim (`packages/helios_core/geo.py`) is a **gap-filler only**, at
  1 req/s with a disk cache under `var/` keyed by normalized query. No live
  network in CI (replay from disk fixtures).

### 2. Dedupe and minting strategy

Reuse `resolve_source_record_observation` for exact-key idempotency, then
add a minting step for the `unresolved` tail:

1. Persist + resolve every POI. Exact GERS-key hits return the existing
   Subject (monthly re-run is a no-op on unchanged POIs).
2. For `unresolved` records, run a **conservative deterministic dedupe**
   against current Subjects using typed feature clusters
   ([ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) §3):
   normalized name fingerprint **plus** normalized address / lat-lon
   proximity. Auto-`assign` to an existing Establishment **only on a strong
   composite signal**: matching name fingerprint **and** coordinates within
   **50 m**. Everything below that bar **mints** a
   new Place + Organization + Establishment and `assign`s the source record
   to it, Evidence-backed, `actor_class="rule"`.
3. This is deliberately **duplicate-tolerant**: ADR-0004 states duplicate
   Place/Organization candidates are an expected conservative result until
   evidence supports a later merge, and a name fingerprint alone is never
   proof of identity. Wrong merges are expensive to undo; duplicates are
   cheap and are reconciled by an explicit `record_subject_change` merge
   later. The `<2%` duplicate target is measured against the hand-labeled
   100-row sample and reported; if conservative minting overshoots it, that
   is a merge-policy decision to surface, not a reason to merge aggressively
   at ingest.
- **Newly minted Subjects start `provisional`** (ADR-0004). `/v1/venues`
  already serves any *current* Establishment regardless of readiness, so
  discovered venues surface immediately; menu writers still gate on
  `eligible`.
- **Proximity uses lat/lon distance** (haversine in a pure helper), not H3
  bucketing.

### 3. Schedule and where it runs

- Discovery is a **re-runnable, idempotent CLI** (e.g.
  `python -m apps.discovery.overture --config <cfg>`), safe to run any number
  of times; determinism comes from the GERS external key, not from run-once
  side effects.
- **Runs on the Orange Pi** alongside the API (owner decision). The API
  binds so the service is reachable from the dev machine over the LAN
  (bind `0.0.0.0` on the compose/API port, reached at the Pi's LAN address,
  or an SSH tunnel — settled at implementation, verified by a `curl` of
  `/v1/venues` from the dev machine).
- **Cadence:** ~monthly, per RFC-0001 §D5, run by a scheduler on the Pi.
  Migrations remain an explicit deploy step, never on container start
  (ROADMAP Phase 2). The scheduler/systemd specifics are an ops detail of
  this same unit now that the Pi is in scope; `infra/` changes still get a
  careful read (CLAUDE.md).

### 4. Code placement (decided)

- `apps/discovery/` — orchestration entrypoint and CLI (composes provenance
  + identity; owns no schema), per ADR-0004's `apps/*` composition root.
- `packages/helios_core/identity/normalize.py` — **pure** name/address
  normalization, fingerprinting, and haversine proximity. Placed under the
  identity module because it is shared-identity matching logic (the same
  concern as `organization.name_fingerprint`); it has no ORM/DB/HTTP imports,
  so it is unit-testable standalone. `helios_parsing` is reserved for
  ORM-free *menu/text* extraction (ADR-0004) and is not the right home for
  venue identity.
- `packages/helios_core/geo.py` — the Nominatim gap-fill client (I/O + disk
  cache), a shared service module in `helios_core`.

### 5. Viewing stage (forward-looking; not built in this unit)

Owner decision: at the viewing stage consumers **draw their own map
boundaries** and **filter by category / tag / parameter**. Implications the
discovery design must respect now so viewing is not blocked later:

- **Retain Overture categories/tags/attributes** in the Bronze payload
  (done in §1) — nothing is discarded at ingest, so viewing can filter on
  anything the source published.
- **Category/tag filters must not add food-specific columns to
  identity/place tables** (ADR-0004 §D1.4, RFC-0001): the viewing filter set
  is projected in a **Gold** read model (or derived from Bronze), not stored
  on `venue`/`place`/`organization`.
- **Map-boundary draw is a query-time geospatial filter** over lat/lon. A
  bbox filter is trivial with the existing columns; arbitrary drawn polygons
  can use PostGIS point-in-polygon (the DB image already ships PostGIS) at
  the viewing layer. No geometry column is added now.
- The concrete viewing API/endpoints (bbox/polygon param shape, filterable
  attribute list) are **Phase 7** and get their own small ADR; this section
  only records the constraints, not the endpoint design.

## Alternatives considered

| Axis | Option | Pros | Cons |
|------|--------|------|------|
| Parquet read | **DuckDB (rec.)** | Pushdown filter in one query; reads remote release; no full download | New runtime dep |
| | pyarrow | Lighter; well-known | Manual filtering; more code |
| Fetch model | **Remote query (rec.)** | No large local artifact | Depends on release availability at run time |
| | Download-once, refresh monthly | Fully local, replayable offline | Storage + a fetch/versioning step |
| Dedupe | **Conservative mint, deferred merge (rec.)** | Matches ADR-0004; avoids irreversible wrong merges | May exceed 2% dup until merge policy tunes |
| | Aggressive auto-merge on fingerprint | Fewer duplicates immediately | Wrong merges expensive and hard to detect; violates ADR-0004 |
| Website as match key | **Org-level signal only (rec.)** | Avoids collapsing co-branded locations | Website resolution is a separate unit |
| | Establishment `canonical_url` | Reuses resolver URL path | **Merges distinct locations that share a brand site** |
| Ingest boundary | **bbox (rec.)** | No geometry lib; harmless over-inclusion | Slightly wider candidate set |
| | Precise polygon | Tighter candidate set | Needs shapely/PostGIS at ingest |

## Consequences

- **No schema migration.** Discovery reuses existing `Place` lat/lon,
  `Organization` fingerprint, and Bronze — the expensive-to-reverse
  models/alembic path is untouched, so this unit is far cheaper to review
  than a schema PR.
- **Coverage ceiling becomes measurable.** RFC-0001 plans ~3–4k metro food
  venues and ~30–40% free website coverage; the actual figure is a Phase 4
  deliverable and, per ROADMAP, a **stop-and-report** number if it lands far
  below 30%.
- **One new runtime dependency** (DuckDB) plus promoting `httpx` to runtime
  for Nominatim; both enlarge the Docker image — a CLAUDE.md stop-and-ask.
- Conservative minting means **`/v1/venues` may show near-duplicates** until
  a later merge unit lands; an accepted, reversible state, and the API
  already exposes only current Subjects.
- Reusing the existing Bronze/Identity contracts means **no changes to the
  resolver or its concurrency model** — discovery is additive.
- Keeping websites out of the Establishment match key removes the
  location-collapse failure mode entirely.
- Running on the Orange Pi with LAN-reachable serving gives a real
  end-to-end demo (`curl /v1/venues` from the dev machine returns discovered
  venues) but brings `infra/`/staging back into this unit's blast radius.

## Owner decisions — all resolved (2026-09-20)

1. **No H3 / lat-lon only** — removed the `Place` migration ask; discovery is
   additive with zero schema change.
2. **Interactive viewing filters** — map-draw boundaries + category / tag /
   parameter filtering (§5).
3. **Orange Pi in scope** — discovery + API run on the Pi, LAN-reachable from
   the dev machine; Pi infra config authorized for this unit.
4. **Helper placement** — delegated; resolved in §4.
5. **Parquet reader = DuckDB**; `httpx` promoted to a runtime dep.
6. **Ingest bbox = Travis + Williamson** (lat `30.02 .. 30.85`,
   lon `-98.17 .. -97.37`).
7. **Dedupe auto-merge = name fingerprint match + coordinates within 50 m.**

## References

- [ROADMAP.md](../../ROADMAP.md) Phase 4; [RFC-0001](../rfc/0001-menu-pricing-first.md) §D3–D6, PRs 5–6
- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) (identity grains, dedupe philosophy, composition root)
- [ADR-0008](./0008-read-api-conventions.md) (venue read contract this feeds)
- Code: `apps/api/seed.py` (removed after discovery replaced it),
  [identity/commands.py](../../packages/helios_core/identity/commands.py),
  [provenance/contracts.py](../../packages/helios_core/provenance/contracts.py),
  [identity/models.py](../../packages/helios_core/identity/models.py)
- V1 port hints (`V1-Graveyard`): `core/venue_identity.py`,
  `core/normalizer.py::make_fingerprint`, `collectors/geocoding.py`,
  `collectors/meal_deals/osm_url_resolver.py`, `scripts/build_facility_index.py`

## Doc drift noted (not fixed here)

ROADMAP §6.4's ADR ledger is stale: it lists 0007 = "Prod hosting" and
0008 = "LLM extraction fallback" (both *Planned*), but the actual files are
`0007-gold-price-index-projection.md` and `0008-read-api-conventions.md`
(both Accepted). RFC-0001 §D4 also still refers to the LLM-fallback ADR as
"ADR-0008". Flagging per CLAUDE.md; a docs-only PR should renumber/realign
the ledger.
