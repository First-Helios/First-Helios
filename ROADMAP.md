# Helios V2 — Roadmap

> **Purpose.** Restart the Helios project (a food price index for Austin — restaurant menus and item prices, with meal deals layered on top) with the rigor of a professional codebase.
> This document distills what is worth keeping from V1, defines the V2 architecture, and sequences the rebuild into phases.
> Every phase is a PR train; every PR passes CI; every architectural decision is recorded in an ADR.
>
> **Status lives in [README.md → Status](./README.md#status).** This file holds phase definitions and plans only; it does not track what is built.
>
> **How it's built.** The implementation is **agent-driven with a human reviewer in the loop** — agents write the code, a human approves the design decisions and the changes that are expensive to reverse. See [CLAUDE.md](./CLAUDE.md) for the working agreement and [CONTRIBUTING.md](./CONTRIBUTING.md) for the review gates.
>
> **Companion:** [LEARNING_GUIDE.md](./LEARNING_GUIDE.md) — the skills course, now serving as the **reviewer's curriculum**: read the module before reviewing the phase it maps to, so you can judge the work rather than just merge it.
>
> **V1 reference:** the legacy code lives on the [`V1-Graveyard`](https://github.com/First-Helios/First-Helios/tree/V1-Graveyard) branch of this repository. When this doc says *"port from V1"*, that is where to find the source.

---

## Table of Contents

1. [North Star](#1-north-star)
2. [Scope — V1 of V2](#2-scope--v1-of-v2)
3. [Part A — Distilled Assets](#3-part-a--distilled-assets)
4. [Part B — Target Architecture](#4-part-b--target-architecture)
5. [Part C — Phased Build Plan](#5-part-c--phased-build-plan)
6. [Engineering Process](#6-engineering-process)
7. [Open Questions](#7-open-questions)
8. [Appendix A — V1 Reference Map](#appendix-a--v1-reference-map)

---

## 1. North Star

> **"A trustworthy, queryable price index of food in Austin, built from free public data, run as a live service, with professional discipline."**

- **Trustworthy** — every price is traceable to a captured page, and carries the date it was observed.
- **Queryable** — a clean HTTP API with pagination, filters, and OpenAPI docs.
- **Real** — every price is a first-party price a person would actually pay in the restaurant, not a delivery-inflated one.
- **Free public data** — no paid APIs in the V1 dependency graph.
- **Professional discipline** — PR-gated main, CI, typed code, ADRs for decisions, tests for every non-trivial function.

> **Re-scoped 2026-07-31.** The North Star was previously "a map of real
> food *deals*." The product is the **price index**: menus and item prices
> across as many Austin/Round Rock venues as possible. Deals are a layer
> built on top of a populated menu graph, not the foundation. See
> [RFC-0001](./docs/rfc/0001-menu-pricing-first.md).

---

## 2. Scope — V1 of V2

**In scope**

- Restaurant **menus and item prices** (sections, items, prices, variants, modifiers) across the Austin / Round Rock metro — schema *and* population.
- **Venue discovery at metro scale** — Overture seeding, website resolution, menu-URL discovery. Coverage is the product, so discovery is a first-class subsystem, not a helper script.
- Venue identity (which restaurant is which) and geocoding (lat/lon only; no H3, per [ADR-0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md)).
- A read-only public API, including price-index aggregates.
- Replay + audit tooling so every price is traceable to a captured page.

**In scope, but after the coverage milestone**

- Restaurant **meal deals** (promotions, limited-time offers, happy hours, combos). No deal is extracted, scored, or served until the menu graph is populated. Promotional rows are identified later by a promo classifier over the stored page bundles, not during Phase 5 extraction; Phase 5 lays the label foundations ([ADR-0013 Amendment 3](./docs/adr/0013-phase5-menu-pipeline.md#amendment-3-2026-09-29-accepted-open-questions-1-2-4-5-decided)).

**Out of scope**

- Jobs, labor data, events, sentiment, Revelio, SerpAPI, Google Places — all V1 modules that are not menu/price related.
- **Aggregator and delivery-platform scraping** (Yelp, Google Maps, DoorDash, UberEats). Their terms prohibit it, and delivery menus carry a 15–30% markup, so their prices answer a different question than the one this project asks. See [RFC-0001 §D1](./docs/rfc/0001-menu-pricing-first.md).
- Cross-venue item canonicalization (mapping "1/2 lb Angus Burger" ≈ "cheeseburger"). Aggregates are category-level for now; see §7.
- Non-food price verticals (auto repair, plumbing, …). Explicitly a *future* direction — the constraint it imposes today is only that venue identity and the observation pattern stay food-agnostic.
- Authentication / write API (deferred until a real consumer exists).
- Multi-city coverage (Austin/Round Rock only until that pipeline is stable).
- The frontend — a separate repo that consumes this API.
- The SpiritPool browser extension (separate project; if it is revisited, its ingest endpoint becomes an RFC).

**Success criteria**

- **300+ distinct Austin / Round Rock venues with at least one priced menu item each**, served from a deployed HTTP endpoint.
- **≥ 80% of covered venues observed within the last 45 days** — freshness is measured and exposed, never assumed.
- Every price traces to a replay bundle, and re-running any scrape produces zero duplicate rows.
- The service survives a reboot of its host and a wipe of its database (restore from backup + replay).
- Every architectural decision that cost more than a day to make is written down as an ADR.

> **On timelines.** Agent-driven implementation compresses coding time but
> *not* review time, and review is the bottleneck. Phases are sequenced but
> deliberately **not** date-estimated — a phase is done when its "Done when"
> clause is true, not when a week elapses.

---

## 3. Part A — Distilled Assets

These are the pieces of V1 worth preserving. Everything else either never shipped, depended on a paid API, or was built before the design was understood. V1 was deals-first; the notes below say where each asset lands under the menus-first scope.

The most valuable V1 asset for the new scope is `collectors/meal_deals/menu_persistence_schema.py` (with `menu_sidecar.py`): a full menu-graph shape that V1 extracted but never persisted. V2's Menu schema ported that shape ([ADR-0005](./docs/adr/0005-immutable-menu-snapshots-and-selection.md)).

### 3.1 Sources (Free & Public Only)

Zero paid APIs.

| # | Source | What We Get | Constraints |
|---|--------|-------------|-------------|
| R1 | Nominatim (OpenStreetMap) | Free-form address → (lat, lon) | 1 req/sec, user-agent required, viewbox recommended |
| R2 | Overture Maps POI (Parquet) | Business name, address, category, website URL | Download-once, refresh monthly |
| R3 | OpenStreetMap / Overpass | Business website URL by name + area | 1 req/sec; deferred as a website fallback ([ADR-0010](./docs/adr/0010-website-and-menu-url-resolution.md)) |
| — | First-party restaurant websites | Menu pages and prices | robots.txt, real User-Agent, per-host rate limit |

V1's eight chain deal pages (McDonald's, Taco Bell, Domino's, Wendy's, ThunderCloud Subs, Pizza Hut, Subway, Sonic; config in V1's `config/meal_deal_sources.yaml`) are useful anchor sites for validating menu extraction, not the coverage strategy. Coverage comes from metro-wide Overture discovery ([ADR-0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md)) and website / menu-URL resolution with the manual registry in `config/sources.yaml` ([ADR-0010](./docs/adr/0010-website-and-menu-url-resolution.md)).

**Dropped from V1** (either paid, out of scope, or broken as built):

- SerpAPI — paid; jobs are out of scope.
- Google Places API — paid; OSM + Overture + sitemaps cover V1 needs.
- Revelio Labs labor feed — proprietary; out of scope.
- TheirStack, Jobicy, RapidAPI ActiveJobs — jobs; out of scope.
- BLS / QCEW / LAUS / OEWS — labor ground-truth; out of scope for V1.
- Ticketmaster / Eventbrite / Meetup / Do512 / Austin City Calendar — events; out of scope.

### 3.2 Processes (Reusable Algorithms)

The **V1 source** column points to the file on the `V1-Graveyard` branch.

| # | Process | V1 Source | Why Keep | V2 home |
|---|---------|-----------|----------|---------|
| 1 | Sub-deal decomposition | `collectors/meal_deals/sub_deals.py` | Splits "Mon–Fri 3–6pm. $1 off beer. Half off apps. $5 margs." into 3 offers via an ordered regex chain. | Phase 10, `packages/helios_parsing/`. Pattern list in YAML; property tests. |
| 2 | Temporal parsing | `collectors/meal_deals/temporal.py` | Handles 50+ variants: "Mon-Fri", "Monday through Friday", "3pm–close", em/en dashes, 12-hour AM/PM. | Phase 10, `packages/helios_parsing/`. Returns a structured dataclass. |
| 3 | Signal-quality scoring | `collectors/meal_deals/quality.py` | 6-factor composite (price 25%, time 20%, description 15%, name 15%, restaurant-match 10%, not-addon 15%) with `reject < 0.20 < review < 0.40 ≤ accept` gates. | Phase 10. Weights + thresholds in config, not constants. |
| 4 | Venue identity / fingerprinting | `core/venue_identity.py` + `core/normalizer.py::make_fingerprint` | Name canonicalization, address normalization, URL canonicalization, proximity clustering. | `packages/helios_core/identity/normalize.py` ([ADR-0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md) §4); golden set in `test/fixtures/golden_matches.json`. |
| 5 | Replay-manifest pattern | `scripts/build_website_scrape_replay_manifests.py` | Every scrape persists raw HTML + fetch metadata in a deterministic bundle. Diff-able across runs. | Bronze Capture `bundle_path` ([ADR-0011](./docs/adr/0011-provenance-endpoints-vs-identity-match-keys.md) §3); menu-page bundles under `var/replay/` ([ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md) §5). |
| 6 | Expectation-vs-capture diffing | `scripts/compare_website_scrape_expectations.py` | Asserts "we should see $X at site Y" against real captures; catches regressions. | Replaced in Phase 5 by held-out evaluation and a monthly spot check ([ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md) §8). |
| 7 | Collector registry decorator | `collectors/meal_deals/registry.py` | Self-registration so the scheduler auto-discovers scrapers. | Not needed: one universal pipeline, no per-site scrapers ([ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md)). |
| 8 | Config-driven strategy routing | `config/meal_deal_sources.yaml` | One YAML maps domain → strategy + selectors + rate limit. | Only the manual website / menu-URL registry survives, as `config/sources.yaml` ([ADR-0010](./docs/adr/0010-website-and-menu-url-resolution.md) §4); no per-site strategy. |
| 9 | Multi-layer data model (pattern) | `core/database.py` — `DealObservation → DealApplicability → DealMaterialization` | Observation is the canonical atom; applicability fans out to many venues; materialization is the pre-computed consumer view. | Bronze → Menu → Gold ([ADR-0004](./docs/adr/0004-modular-monolith-identity-and-lifecycle.md), [ADR-0005](./docs/adr/0005-immutable-menu-snapshots-and-selection.md), [ADR-0006](./docs/adr/0006-gold-menu-read-models.md)); deal tables in Phase 10. |

**What we are deliberately *not* porting**

- The legacy `meal_deals` denormalized table (pre-dates the `DealObservation` pattern). Redundant.
- The `employer_data`, `labor_data`, `events`, `job_boards`, `sentiment` collectors. Out of scope.
- `core/baseline.py`, `core/targeting.py`, `core/rate_manager.py`, `core/scheduler.py` — rewrite rather than port. The ideas are sound but the code grew organically.
- Playwright stealth hackery specific to employer sites we will no longer scrape.

### 3.3 Skills Inventory

What a dev needs to own this codebase professionally. Each skill is expanded into a module in the [Learning Guide](./LEARNING_GUIDE.md).

| Area | Skills |
|------|--------|
| **Python** | Typing (`Mapped`, `TypedDict`, generics), `dataclasses`, `@dataclass(slots=True)`, `pathlib`, packaging with `pyproject.toml`, dependency management with `uv`, virtual envs. |
| **Tooling** | `ruff` (lint + format), `mypy --strict`, `pre-commit`, Conventional Commits, semantic versioning. |
| **SQL & data modeling** | Normal forms, primary / foreign keys, unique constraints, partial indexes, JSONB vs columns, transaction isolation, index strategy, migration safety. |
| **ORM** | SQLAlchemy 2.0 declarative typed models, relationships, eager vs lazy loading, session lifecycle, Alembic autogenerate + manual edits, zero-downtime migration patterns. |
| **Web fundamentals** | HTTP semantics, status codes, redirects, caching, cookies, `robots.txt`, sitemaps, DNS, TLS, `User-Agent` etiquette, rate-limit negotiation. |
| **Scraping & extraction** | `httpx`, headless Chromium via Playwright, JSON-LD extraction, HTML segmentation, local LLM serving (llama.cpp), grammar-constrained output, held-out evaluation. |
| **Data engineering** | Idempotency, at-least-once vs exactly-once, Bronze → Silver → Gold lifecycle, lineage, replay, backfill strategy, change detection. |
| **Geospatial** | Lat/lon, geocoding, reverse geocoding, haversine distance, bounding boxes, grid bucketing. |
| **Parsing** | Regex craft, regex debugging, property-based testing, when rules beat ML (and when they don't). |
| **API design** | REST vs RPC, FastAPI, Pydantic v2, OpenAPI, pagination (cursor vs offset), error shapes, idempotency keys, rate limiting. |
| **Testing** | pytest, fixtures, `parametrize`, factories, property tests, contract tests, golden files, coverage tooling. |
| **Ops** | Docker, docker-compose, systemd, `.env` hygiene, structured logging (structlog), Prometheus metrics, healthchecks, backups, hosted deploys (Fly.io / Railway / Hetzner / DO). |
| **Process** | Git (branches, rebase, worktrees), PR anatomy, code review, ADRs, RFCs, issue templates, CODEOWNERS, branch protection, CI design. |

---

## 4. Part B — Target Architecture

### 4.1 Repo Layout (monorepo)

```
apps/
  api/                 # FastAPI service; routes/, committed openapi_snapshot.json
  discovery/           # Overture seeding, website/menu-URL resolution, lifecycle, audit CLIs
packages/
  helios_core/
    db/                # Base, schema names, model registry, session
    provenance/        # Bronze (schema `bronze`)
    identity/          # Identity Subjects + pure normalize.py (schema `identity`)
    domains/menu/      # Menu Silver (schema `menu`)
    gold/              # Gold read models (schema `gold`)
    config.py, geo.py  # settings; Nominatim client
alembic/versions/      # hand-reviewed migrations
config/sources.yaml    # manual website / menu-URL registry
infra/                 # Dockerfile, docker-compose.yml
test/                  # all tests, including architecture-fitness tests
docs/                  # adr/, rfc/, plans/, spikes/, reviews/, diagrams/
.github/               # workflows/{ci,pr-title}.yml, PR + issue templates, CODEOWNERS
makefile, pyproject.toml, uv.lock, ruff.toml, mypy.ini, alembic.ini, .pre-commit-config.yaml
```

Per [ADR-0013 §2](./docs/adr/0013-phase5-menu-pipeline.md#2-code-layout): `packages/helios_parsing/` (pure pipeline stages, Phase 3) and `apps/menu_pipeline/` (the pipeline's I/O, Phase 5). Both exist; so far they hold segmentation and the text hash, price tokens, the JSON-LD reader, chunking, the prompt and grammar, output parsing, repairs, the validator, the evaluation harness, the page classifier and the renderer.

### 4.2 Environments (Dev → Staging → Prod)

The Orange Pi is the **staging** environment, not production.

```
┌─────────────┐   push    ┌──────────┐   merge    ┌───────────────────┐   promote   ┌─────────────────┐
│  Laptop     │ ────────▶ │  GitHub  │ ─────────▶ │  Orange Pi        │ ──────────▶ │  Hosted Prod    │
│  (dev)      │   + PR    │  (CI)    │            │  (staging, ARM64) │             │  (VPS or PaaS)  │
└─────────────┘           └──────────┘            └───────────────────┘             └─────────────────┘
     │                         │                         │                                  │
     │ run tests locally       │ five required checks    │ smoke-test on real hardware      │ only deploy
     │ `make dev`              │ block merge on red      │ run batch jobs against live web  │ artifacts that
     │                         │                         │ observe metrics                  │ passed staging
```

**Why staging on the Orange Pi**

1. **Arch parity.** The prod target (Phase 8) is likely ARM64. The Pi mirrors that. This is not hypothetical: the official `postgis/postgis` image is amd64-only and could never have run on the Pi ([ADR-0002](./docs/adr/0002-containerization.md)).
2. **Real-world network.** Real residential IP, real rate-limit conditions, real DNS — not a sterile CI runner.
3. **Cheap.** Zero marginal cost.
4. **Safe blast radius.** If a batch job loops, it consumes *your* bandwidth, not a hosted bill.

**What the staging host runs**

- The Compose stack from `infra/docker-compose.yml` (Postgres → one-shot migrate → API). Postgres runs in Compose alongside the app.
- A systemd unit that starts the stack on boot and restarts on failure; migrations are an explicit deploy step, never on container start. *(Phase 2)*
- Monthly discovery ([ADR-0009 §3](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md)) and the menu pipeline as a low-priority batch job ([ADR-0013 §3](./docs/adr/0013-phase5-menu-pipeline.md#3-runtime-dependencies-and-dockerpi-deployment)). *(Phases 5–6)*
- Daily `pg_dump` to an external drive and Prometheus node-exporter. *(Phase 8)*

**What prod will run (Phase 8)**

- The same Docker image, promoted manually after staging is green.
- Hosted options ranked by learning value / cost: Hetzner Cloud CAX11 (ARM64), Fly.io, Railway, DigitalOcean Droplet.
- Prod hosting and Postgres topology (containerized vs. host-installed vs. managed) are decided in an ADR (next free number), with numbers.

### 4.3 Data Layer

- **Postgres 16** as the only database, on the multi-arch PostGIS image
  ([ADR-0002](./docs/adr/0002-containerization.md)). No geospatial extension
  is used: coordinates are lat/lon columns ([ADR-0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md)),
  and the price index buckets them into a lat/lon grid
  ([ADR-0007](./docs/adr/0007-gold-price-index-projection.md)).
- **Lifecycle and bounded-context schemas** in one database per
  [ADR-0004](./docs/adr/0004-modular-monolith-identity-and-lifecycle.md):
  - `bronze` — durable source claims, captures, record versions, and Evidence;
  - `identity` — durable Silver Subjects, typed identity grains, and
    append-only resolution/lineage decisions;
  - `menu` — typed menu-domain Silver facts ([ADR-0005](./docs/adr/0005-immutable-menu-snapshots-and-selection.md)); and
  - `gold` — rebuildable consumer read models and aggregates ([ADR-0006](./docs/adr/0006-gold-menu-read-models.md)).
- Unresolved identity candidates and provisional Subjects have explicit,
  queryable state and cannot silently flow into vertical facts.
- **Alembic** migrations with autogenerate + hand edits, reviewed in PRs.
  **No `metadata.create_all()`** outside test fixtures.
- Append-only tables have no application-settable bypass. A data-fix
  migration that disables an immutability trigger is a separate owner-review
  gate and must restore every trigger before commit; a
  `session_replication_role` bypass is never allowed. A temporary migration
  schema may be allowlisted only in a named transition set, with a test naming
  the step that removes it.
- **dbt** is *not* in V1 scope. Revisit only if Gold complexity justifies a
  dedicated ADR.

### 4.4 API Layer

- **FastAPI** + Pydantic v2, with conventions fixed by
  [ADR-0008](./docs/adr/0008-read-api-conventions.md): domain routes under
  `/v1`, cursor-based pagination, the uniform error shape
  `{detail, code, trace_id}`, response models separate from ORM models.
- Resources: venues (`/v1/venues`, `/v1/venues/{venue_id}`) from Phase 2;
  menus, price history and the price index in Phase 7; deals in Phase 10.
- OpenAPI at `/openapi.json` and `/docs`; a committed snapshot
  (`apps/api/openapi_snapshot.json`, checked by `test/test_openapi_contract.py`)
  makes breaking changes fail CI.
- No auth in V1. CORS locked to the single frontend origin.

### 4.5 Fetch & Menu Pipeline

- **Fetching:** `SiteFetcher` (`apps/discovery/web_client.py`) — robots.txt on
  every redirect hop, a required User-Agent, per-host rate limit, disk cache.
  No crawler framework: the workload is ~1,000+ distinct hosts fetched
  shallowly once a month, which favours per-host politeness over crawl depth.
- **Menu reading (Phase 5):** one universal pipeline for every site — page
  classifier → segmentation → JSON-LD reader / on-device LLM extraction →
  generic repairs → validator — per
  [ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md) (accepted 2026-09-29), which
  replaces the earlier Scrapy-vs-Crawlee framing (owner decision G.b). No
  per-platform parsers.
- **Replay:** every fetch or render is a Bronze Capture with a durable bundle,
  so every stored price cites a byte span a reader can check
  ([ADR-0013 §5](./docs/adr/0013-phase5-menu-pipeline.md#5-bronze-change-detection-bundles-and-evidence-locators)).

### 4.6 Observability

- **Logging:** `structlog` with per-request IDs; JSON in staging/prod,
  human-readable in dev ([ADR-0008](./docs/adr/0008-read-api-conventions.md)).
- **Healthcheck:** `GET /healthz` (liveness) + `GET /readyz` (DB ping).
- **Metrics:** Prometheus, planned for Phase 8; batch runs write a run report
  (Phase 6).
- **Tracing:** not in V1 scope.

---

## 5. Part C — Phased Build Plan

Each phase ends with a demoable artifact on `main`, merged through a PR with green CI. Each maps to a learning module (see [Learning Guide](./LEARNING_GUIDE.md)) — read it *before reviewing* that phase's PRs. For what is built today, see [README.md → Status](./README.md#status).

Phase *numbers* are stable identifiers (other docs cite them); RFC-0001 changed the build order without renumbering. Build order:

| Order | Phase | Name |
|-------|-------|------|
| 1 | 0 | Foundations & Tooling |
| 2 | 1 | Domain Model & Migrations |
| 3 | 2 | First Light — read API + staging deploy |
| 4 | 4 | Venue Discovery, Identity & Geocoding |
| 5 | 3 + 5 | Parsing library + Menu pipeline (one slice train, [ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md#implementation-slices-after-acceptance)) |
| 6 | 6 | Monthly Runs & Freshness |
| 7 | 7 | API Surface — full, incl. price index |
| 8 | 8 | Operations — prod |
| 9 | 9 | Harden |
| 10 | 10 | Deals layer |

Phases 3 and 5 run after Phase 4 because their fixtures and evaluation sets come from real captured Austin menu pages, which need discovery first.

---

### Phase 0 — Foundations & Tooling

**Learning modules:** [M1](./LEARNING_GUIDE.md#m1--modern-python-project-hygiene) · [M2](./LEARNING_GUIDE.md#m2--git--team-workflow) · [M3](./LEARNING_GUIDE.md#m3--design-docs-adrs-and-rfcs)

**Goal:** a new-repo skeleton that already has every professional habit baked in, so the first line of feature code is written with the guardrails already up.

**Deliverables**

- `pyproject.toml` (PEP 621) with `uv` for lockfile + install; `ruff.toml`, `mypy.ini` (strict), `.pre-commit-config.yaml`.
- `.github/workflows/ci.yml`, PR and issue templates, `CODEOWNERS`.
- `docs/adr/0000-template.md`, `docs/rfc/0000-template.md`, and **ADR-0001** (language, framework, and data stack).
- `apps/api/main.py` with `GET /healthz` and a passing test.
- Branch protection on `main`: PR required, the five CI checks required, 0 approvals (see §6.0).

**Done when:** `git push` to a feature branch opens a PR, CI runs automatically, merge advances main. No exceptions.

---

### Phase 1 — Domain Model & Migrations

**Learning module to review against:** [M5](./LEARNING_GUIDE.md#m5--relational-modeling) · [M6](./LEARNING_GUIDE.md#m6--sqlalchemy-20--alembic)

**Goal:** establish the modular-monolith Bronze and Identity foundations,
remove the superseded scaffold, then add typed Menu Silver and Gold read
models with constraint-level tests.

**Deliverables**

- Bronze sources, endpoints, captures, source records/versions and Evidence,
  with immutable source history ([ADR-0004](./docs/adr/0004-modular-monolith-identity-and-lifecycle.md)).
- Identity Subjects (Place, Organization, Establishment), explicit resolution
  state, append-only decisions and lineage.
- A reviewed clean-reset migration removing the former `brand` / `venue`
  scaffold and the `raw` / `canonical` / `mart` schemas; no legacy data backfilled.
- The typed Menu graph with immutable snapshots and scoped selection
  ([ADR-0005](./docs/adr/0005-immutable-menu-snapshots-and-selection.md);
  normative detail in [docs/plans/0002-step-5-menu-schema-proposal.md](./docs/plans/0002-step-5-menu-schema-proposal.md)).
- Gold `current_menu` with a deterministic full-rebuild refresh
  ([ADR-0006](./docs/adr/0006-gold-menu-read-models.md)). The price-index
  projection's shape is fixed by [ADR-0007](./docs/adr/0007-gold-price-index-projection.md);
  its build is deferred to Phases 6–7.
- Postgres `CHECK` constraints for enums; deterministic natural keys so
  re-ingest is idempotent; money as integer currency minor units, never float.
- Architecture fitness tests for schema/FK/import directions, immutability,
  and deferred constraints.

**Deal models are not in this phase.** `DealObservation` /
`DealApplicability` / `DealMaterialization` move to Phase 10. Building a
schema for data we will not collect for months is the "for later"
scaffolding CLAUDE.md prohibits — and the menu graph is likely to change what
the right deal schema looks like.

**Port hints (`V1-Graveyard` branch)**

- `collectors/meal_deals/menu_persistence_schema.py` — V1's target menu-graph
  shape (`MenuPageRow`, `MenuSectionRow`, `MenuItemRow`, `MenuPricePointRow`,
  `MenuModifierRow`). V2 renames `MenuPricePoint` → `PriceObservation` and
  stores integer currency minor units.
- `core/database.py::DealMaterialization` (~L1395) — the refresh-task
  pattern Gold inherits, not the deal columns themselves.

**Reviewer's checklist** — this is the phase where a bad decision is most
expensive to undo:

- Does every enum have a `CHECK` constraint, not just a Python-side `Enum`?
- Is every FK's `ondelete` behavior deliberate, and does a test prove it?
- Is clean-reset data loss explicit, limited to the superseded scaffold, and
  proven on a seeded disposable database?
- Is `PriceObservation` append-only in practice — is there any code path that
  `UPDATE`s a price rather than inserting a new observation?
- Is money stored as integer currency minor units, with no float column anywhere
  near a price?
- Does every mapped table declare an explicit, owned schema
  ([ADR-0004](./docs/adr/0004-modular-monolith-identity-and-lifecycle.md)),
  and do tests enforce allowed FK/import directions?
- Any column that's nullable — is it nullable because the domain allows
  absence, or because it was easier?

**Done when:** the clean reset and each new schema migration pass
upgrade/downgrade/re-upgrade tests, every accepted invariant has a focused
failing case, and the Menu schema depends only on eligible Identity Subjects
and immutable Bronze Evidence.

---

### Phase 2 — First Light: read API + staging deploy

**Learning modules to review against:** [M11](./LEARNING_GUIDE.md#m11--api-design) · [M12](./LEARNING_GUIDE.md#m12--operations)

**Goal:** the thinnest possible end-to-end slice, running for real. One
resource, read-only, served from Identity/Gold, deployed to the Orange
Pi and reachable. This phase proves the whole path works and establishes the
API conventions everything later inherits.

**Why here and not Phase 7.** Deferring every HTTP concern to the end
concentrates integration and deployment risk into one late phase and means
months of work with nothing observable. Doing it early costs little, and
every later phase gets validated against a real deployment instead of a laptop.

**Deliverables**

- **[ADR-0008](./docs/adr/0008-read-api-conventions.md): read-API conventions** —
  pagination, error shape, versioning, 404 vs. empty list.
- `apps/api/routes/venues.py` — cursor-paginated `GET /v1/venues` and
  `GET /v1/venues/{venue_id}`, reading Identity.
- Pydantic response models, separate from ORM models. The wire format is a
  contract; do not leak SQLAlchemy objects into it.
- Real data from Phase 4 discovery behind the endpoints; there is no separate
  seed path (discovery replaced it, ADR-0009).
- Structured logging (`structlog`) with request IDs, and CORS for the separate
  frontend repo.
- **Staging deploy on the Orange Pi:**
  - systemd unit wrapping `docker compose up`, with restart-on-failure and
    start-on-boot.
  - Migrations run as an explicit deploy step, never on container start.
  - Reachable over the LAN; document the address and how to check health.
  - A short runbook: how to deploy, roll back, read logs, restart.

**Explicitly not in this phase:** authentication, rate limiting, a public
domain, TLS, or a hosted prod environment. Those are Phase 8.

**Done when:** you can `curl` a paginated list of venues from the Orange Pi
over the LAN, the service comes back by itself after a host reboot, and the
OpenAPI schema at `/openapi.json` describes it accurately.

---

### Phase 3 — Parsing Library: pure menu-pipeline stages

> Built inside Phase 5's slice train ([ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md#implementation-slices-after-acceptance)
> slice 2). ADR-0013 was accepted 2026-09-29. Segmentation and the price tokens
> already exist (built with the page classifier, S6d/S6f); the text hash, JSON-LD
> reader and validator came with slice 2's first half (P5-1a); chunking,
> prompt/grammar, output parsing, repairs and the evaluation harness with the
> second half (P5-1b). Every deliverable below exists; nothing calls the stages in
> production until slice 5.

**Learning module to review against:** [M4](./LEARNING_GUIDE.md#m4--testing)

**Goal:** the deterministic, I/O-free half of the menu pipeline as
`packages/helios_parsing/` — bytes/text in, plain data out. **No DB, no HTTP,
no model runtime.** The import-boundary test (`test/import_boundaries.py`)
already forbids it from importing SQLAlchemy or `helios_core`.

**Deliverables** ([ADR-0013 §1–§2](./docs/adr/0013-phase5-menu-pipeline.md#1-stages-and-what-is-kept-from-the-spike))

- Segmentation into numbered text blocks, and the normalized text hash used for change detection.
- The schema.org JSON-LD reader (`Menu → MenuSection → MenuItem → Offer`), a general standard reader, not a per-site parser.
- Chunking and prompt/grammar construction for the extractor, and parsing of its output.
- The generic repairs toolbelt and the validator (per-row accept / downgrade to unknown price / reject, plus the `unlabeled_price_runs` page flag).
- The evaluation harness ported from the spike ([ADR-0013 §8](./docs/adr/0013-phase5-menu-pipeline.md#8-quality-bars-and-evaluation-discipline-q5)). CI runs only its unit tests, on synthetic fixtures; real pages and gold labels stay in gitignored `var/`.

**Port hints:** the spike code on branch `spike/menu-model` (see the [menu-model spike](./docs/spikes/menu-model/README.md)); V1's JSON-LD walk in `collectors/meal_deals/menu_sidecar.py`. V1's per-layout DOM pairing and render policy are superseded by the universal-process decision.

**Deferred to Phase 10** (deals layer): `sub_deals.py`, `temporal.py`, and the 6-factor `quality.py` scorer.

**Done when:** every stage is a pure function with focused tests, the import-boundary test passes, and the harness scores synthetic fixtures in CI in the same format the spike used.

---

### Phase 4 — Venue Discovery, Identity & Geocoding

**Learning module to review against:** [M10](./LEARNING_GUIDE.md#m10--geospatial)

**Goal:** populated Place/Organization/Establishment identities for the
Austin/Round Rock metro, deduplicated, geocoded, and linked through Bronze
provenance to first-party websites and menu URLs.

**Deliverables** ([ADR-0009](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md), [ADR-0010](./docs/adr/0010-website-and-menu-url-resolution.md), [ADR-0011](./docs/adr/0011-provenance-endpoints-vs-identity-match-keys.md), [ADR-0012](./docs/adr/0012-venue-lifecycle.md))

- **Overture seeding** — parquet ingest of food venues within a metro bounding
  box (an Austin default in `apps/discovery/overture.py`, overridable with CLI
  flags), landing in Bronze Source Records and explicit Identity resolution
  state.
- Name fingerprinting, address normalization, URL canonicalization, and
  lat/lon proximity (`packages/helios_core/identity/normalize.py`).
- `packages/helios_core/geo.py` — Nominatim gap-fill with a 1-req/sec throttle
  and disk-cached responses.
- **Website resolution** — Overture `websites` first, plus the
  `config/sources.yaml` manual registry, with Source Endpoint provenance.
- **Menu-URL discovery** — common paths, sitemap entries, and on-site links
  matching a menu lexicon, persisted so re-runs skip discovery.
- **Venue lifecycle** — closure and reappearance across monthly runs
  ([ADR-0012](./docs/adr/0012-venue-lifecycle.md)).
- Golden-set matcher fixture with ≥ 95% precision; Nominatim/Overture
  responses replayed from fixtures — no live calls in CI.

Follow-ups: location overrides ([ADR-0014](./docs/adr/0014-location-overrides.md),
accepted and implemented) and menu-URL re-verification
([ADR-0015](./docs/adr/0015-menu-url-reverification.md), accepted 2026-09-29 and
implemented in S6d/S6f: #51, #52, #54).

**Port hints (`V1-Graveyard` branch):** `core/venue_identity.py`,
`core/normalizer.py::make_fingerprint`, `collectors/geocoding.py` (including the
25-city override dict), `collectors/meal_deals/osm_url_resolver.py`,
`scripts/build_facility_index.py`.

**Done when:** the metro is seeded, < 2% duplicate venues and < 1% wrong
geocodes (both measured against a hand-labeled 100-row sample), and
website/menu-URL coverage is measured and written down. Gate state:
[README.md → Gates](./README.md#gates).

---

### Phase 5 — Menu Pipeline: fetch, classify, extract, validate

> Defined by [ADR-0013](./docs/adr/0013-phase5-menu-pipeline.md), accepted
> 2026-09-29 (Amendments 1–7). It replaces this
> phase's earlier "Scrapy vs Crawlee spikes, then a scraper-framework ADR"
> plan (owner decision G.b), on the evidence of the
> [menu-model spike](./docs/spikes/menu-model/README.md).

**Learning modules to review against:** [M7](./LEARNING_GUIDE.md#m7--http-html--the-real-web) · [M8](./LEARNING_GUIDE.md#m8--scraping--menu-extraction)

**Goal:** turn every verified menu URL into validated Menu page aggregates
with one universal pipeline, run as an offline batch job on the staging Pi.

**Deliverables** (the I/O half, `apps/menu_pipeline/`; ADR-0013 slices 1 and 3–6)

- *Built (S6d/S6f, #51, #52, #54):* the worker image target, `menu` extra and
  model manifest; the page-classifier runtime, now discovery's menu-URL verifier
  `classifier-v2` ([§7](./docs/adr/0013-phase5-menu-pipeline.md#7-relation-to-adr-0015-the-classifier-becomes-the-menu-url-verifier));
  headed-Chromium rendering for discovery (`resolve_urls --render`).
- *Built (P5-3):* the ⚠ `llama-server` Compose service behind the `menu`
  profile (upstream image pinned by digest, the spike's flags, a checksum
  init step, Pi core pinning in `infra/docker-compose.pi.yml`) and the
  extraction model's manifest entry ([§3](./docs/adr/0013-phase5-menu-pipeline.md#3-runtime-dependencies-and-dockerpi-deployment),
  [Amendment 6](./docs/adr/0013-phase5-menu-pipeline.md#amendment-6-2026-09-29-llama-server-deployment)).
  Pending: the owner-run Pi check of the image against the spike's build.
- *Built (P5-2):* `menu-page` Bronze writes — a Capture per fetch or render,
  durable bundles, Versions keyed on the segmented-text hash (an unchanged
  re-read writes no Version, Amendment 4), Capture-targeted Evidence
  locators — and a resumable batch CLI (`python -m apps.menu_pipeline.run`).
  Platform pages (`<gers>|<platform host>`) take the venue's Establishment scope, own-site pages the Organization's; PDF
  menus are skipped and counted ([§5](./docs/adr/0013-phase5-menu-pipeline.md#5-bronze-change-detection-bundles-and-evidence-locators)).
- *Built (P5-4):* LLM extraction and Menu writes through `persist_menu`, with
  `llm`/`jsonld` source kinds and trust labels
  ([§6](./docs/adr/0013-phase5-menu-pipeline.md#6-menu-writes-and-trust-q5-q6),
  [Amendment 7](./docs/adr/0013-phase5-menu-pipeline.md#amendment-7-2026-09-29-extraction-and-menu-writes)):
  the `llama-server` client, a resumable `python -m apps.menu_pipeline.extract`
  over `menu-page` Versions, kept raw answers, and a composite pipeline version.
  Next: the first held-out evaluation (a fresh 10-page set), then the first Pi
  extraction run.
- Rendering for the menu pipeline reuses discovery's renderer. Switching it on
  for Pi runs waits for the owner-run Pi time/memory measurement and the §8 bars
  on rendered pages ([§4](./docs/adr/0013-phase5-menu-pipeline.md#4-javascript-only-pages-headless-render-q4)).

**Scraping etiquette is a hard requirement, not a nicety.** Honor
`robots.txt`, identify with a real User-Agent, respect per-host rate limits,
and never bypass a paywall, login or bot challenge (§2, "public data only").
A fetcher that gets the project IP-banned costs more than the data was worth.

**Promotional rows** ("half off", "BOGO"): deferred to a promo classifier
(Phase 10); no rule-based flag now. Phase 5 lays the foundations: gold labels
mark promo rows, and the harness reports promo rows stored as prices. Until the
classifier exists, a promo row with a printed price may be stored as an `llm`
price ([ADR-0013 Amendment 3](./docs/adr/0013-phase5-menu-pipeline.md#amendment-3-2026-09-29-accepted-open-questions-1-2-4-5-decided)).

**Done when** ([ADR-0013 §8](./docs/adr/0013-phase5-menu-pipeline.md#8-quality-bars-and-evaluation-discipline-q5)):
a pipeline version has one recorded evaluation on a held-out set that meets
classifier precision ≥ 0.95 (recall ≥ the previous verifier's), exact price
accuracy on accepted rows ≥ 0.98, item recall ≥ 0.85, validator corruption
catch ≥ 0.97 and false reject ≤ 0.12, with usable prices, Pi pages/hour and
peak RAM recorded; and a first pass on the Pi has left every verified menu URL
with either a Menu page aggregate or a skipped Capture with a reason code, and
venues whose only menu is a PDF are counted (no menu URL reaches them).

---

### Phase 6 — Monthly Runs & Freshness

**Learning module to review against:** [M9](./LEARNING_GUIDE.md#m9--data-engineering-patterns)

**Goal:** keep the menu graph fresh on a monthly schedule without re-doing
work that hasn't changed, and keep Gold in step — all idempotent, all
re-runnable from stored evidence.

**Deliverables**

- **Scheduling:** a monthly run on the staging Pi after discovery
  ([ADR-0009 §3](./docs/adr/0009-venue-discovery-source-dedupe-and-schedule.md)
  cadence), as a low-priority batch job. No queue service — adding one is a
  stop-and-ask dependency ([CLAUDE.md](./CLAUDE.md)).
- **Change-only runs:** extraction runs only for a new `menu-page` Version (a
  changed hash of the segmented text) or a pipeline-version bump; raw-body
  hashes and ETags are never the change signal. Queue order: new pages, then
  changed pages, then re-interpretations
  ([ADR-0013 §5](./docs/adr/0013-phase5-menu-pipeline.md#5-bronze-change-detection-bundles-and-evidence-locators)).
  Pipeline-version bumps are batched, because each one means a
  re-interpretation pass of up to the full first-pass time.
- **Nothing is deleted:** an item that disappears from a page keeps its history;
  disappearance is information ([RFC-0001 §D5](./docs/rfc/0001-menu-pricing-first.md)).
- **Gold refresh** after each run: `current_menu`
  ([ADR-0006](./docs/adr/0006-gold-menu-read-models.md); targeted refresh only
  once cost justifies it) and the price-index projection
  ([ADR-0007](./docs/adr/0007-gold-price-index-projection.md)); both are built
  as `python -m apps.gold.refresh`, which this phase schedules.
- **Replay:** Menu interpretations can be rebuilt from stored bundles without
  re-fetching.
- **Run report:** pages fetched / changed / extracted, outcomes by reason code,
  SoC temperature and throttling ([ADR-0013 §3](./docs/adr/0013-phase5-menu-pipeline.md#3-runtime-dependencies-and-dockerpi-deployment)),
  and venue freshness against the 45-day target (§2).
- **Monthly spot check:** 10 random newly extracted pages, labelled blind by an
  agent, the owner confirming disagreements; a failure makes them the next
  held-out set ([ADR-0013 §8](./docs/adr/0013-phase5-menu-pipeline.md#8-quality-bars-and-evaluation-discipline-q5), Amendment 3).

**Done when:** Menu Silver and Gold can be reconstructed from replay bundles,
Bronze provenance, and durable Identity decisions without changing those
decisions; a re-run against an unchanged site produces zero new observations
and no extraction; and freshness is measured on every run.

---

### Phase 7 — API Surface: full, including the price index

**Learning module to review against:** [M11](./LEARNING_GUIDE.md#m11--api-design)

**Goal:** grow Phase 2's skeleton into the complete read-only public API — the price index made queryable. Every endpoint follows [ADR-0008](./docs/adr/0008-read-api-conventions.md).

**Deliverables**

- `GET /v1/venues/{venue_id}/menu` — the current menu from Gold, every
  price carrying `observed_at`, a staleness age and its source kind.
- Venue filters (area, organization, has-menu), cursor-paginated.
- `GET /v1/items/{id}/price-history` — the observation trail behind a single price. This is the endpoint that makes "trustworthy" checkable by a user rather than asserted by us.
- `GET /v1/price-index` — median / p25 / p75 by lat/lon grid cell and course, with the sample size ([ADR-0007](./docs/adr/0007-gold-price-index-projection.md)), because an aggregate over four venues is not an index and the response should admit that.
  - *Built (G-1, [ADR-0007 Amendment 1](./docs/adr/0007-gold-price-index-projection.md#amendment-1-2026-09-30-first-slice-built-before-the-course-axis)):* the `gold.price_index` table it reads — venue-weighted percentiles per 0.01° cell, category and currency, with `venue_count` and a `low_sample` flag below 5 venues — and `python -m apps.gold.refresh`, which rebuilds `current_menu` and the index at one instant. Category `all` only.
  - *Next:* a course-label ADR (classifier vs section-name baseline on labelled sections), then the `course` category; scoping own-site menu pages to their Establishment upstream (an ADR-0013 amendment); then the endpoint.
- **Freshness in the wire format, not just the docs.** Every priced response carries `as_of`. A stale price served as though it were current is the failure mode this whole design exists to prevent.
- Keep the committed OpenAPI snapshot accurate.
- Read-path performance: every filter combination above is index-backed. Add
  a test that fails on a sequential scan of the Gold current-menu table.

**Done when:** a `curl` of the price-index endpoint for a real area and course returns a real aggregate with a sample size, and the 300-venue milestone is measurable through the API itself.

---

### Phase 8 — Operations: Prod & Resilience

**Learning module to review against:** [M12](./LEARNING_GUIDE.md#m12--operations)

**Goal:** promote from the Orange Pi to a hosted prod environment; make the
whole thing observable and recoverable. Containerization landed early
([ADR-0002](./docs/adr/0002-containerization.md)); Phase 8 assumes Phase 2's
staging deploy.

**Deliverables**

- **Prod hosting ADR (next free number)** — compare Hetzner CAX / Fly.io /
  Railway / DO by cost, ergonomics, and ARM64 availability, and settle Postgres
  topology. Decide with numbers. If prod is x86, decide multi-arch buildx vs.
  native-only builds.
- **Secrets handling** — dev uses `.env` with throwaway credentials; prod needs
  real secret storage, rotation, and secrets that never reach the image, a log
  line, or the repo.
- **TLS + public domain**, and a decision on whether the API is fully public
  or gated (§7).
- **Rate limiting** on the public API.
- **Backups:** nightly `pg_dump` → off-box (external drive + object storage),
  including the replay bundles. A backup you have never restored is not a
  backup — a restore drill is part of this phase.
- **Observability:** Prometheus scrape endpoint, node-exporter, and alerting
  on the handful of things that actually page (service down, disk full,
  fetch failure rate, a stalled monthly run).
- **Deploy pipeline:** tagged releases build and push to a registry; prod
  pulls. Same image promoted from staging after it's been green for 24h.
  Migrations remain an explicit step.
- **Runbook:** what to do when fetching breaks, Postgres fills the disk,
  Nominatim bans us, or prod is down while staging is fine.

**Done when:** you can wipe the Orange Pi, restore from backup, and be
serving yesterday's data within 30 minutes — demonstrated, not assumed. Prod
deploy is one command from a tagged release.

---

### Phase 9 — Harden

**Goal:** paper cuts and polish.

**Deliverables**

- Load test: k6 or Locust against a local API; document p95 latency targets.
- Security pass: `pip-audit`, dependency review, secret-scanning, and
  automated dependency updates (Dependabot or equivalent).
- Retire the `V1-Graveyard` reference uses — by now V2 is self-sufficient.
- Revisit the `imresamu/postgis` pin from ADR-0002: is it still maintained,
  and does the prod topology chosen in Phase 8 still need it?

**Done when:** you could hand the repo to another developer and they could ship a feature in their first week.

---

### Phase 10 — Deals layer

**Goal:** meal deals, built on top of a populated menu graph — the original
V1 ambition, now with the thing it was always missing underneath it.

**Why last, not first.** A deal is only meaningful relative to a price: "$5
off" and "half price margaritas" are unquantifiable without knowing what the
item normally costs. V1 built deals without a menu graph and could never
answer "is this actually a good deal?" — it could only repeat the claim on
the page. With `price_observation` populated, a deal's value becomes
computable and the [signal-quality gate](#32-processes-reusable-algorithms)
gets a real denominator.

**Deliverables**

- `packages/helios_parsing/` ports of V1's sub-deal regex chain (pattern list in YAML, property tests), temporal parsing (a structured `Validity` dataclass: `weekdays`, `start`, `end | "close"`), and the 6-factor quality scorer (weights + thresholds in config).
- `DealObservation` and `DealApplicability` models, deferred here from Phase 1; placement follows ADR-0004.
- Applicability fan-out: chain-wide deals create N rows, one per active venue of that brand.
- A promo classifier model that finds and parses promotional rows in stored menu-page bundles, trained and evaluated on the `promo` marks that Phase 5's gold labels carry. It ships as a menu pipeline-version bump (a re-interpretation), so the evidence is already captured and replayable ([ADR-0013 Amendment 3](./docs/adr/0013-phase5-menu-pipeline.md#amendment-3-2026-09-29-accepted-open-questions-1-2-4-5-decided)).
- Gold deal materialization + `/v1/deals` endpoints.

**Port hints (`V1-Graveyard` branch):** `collectors/meal_deals/sub_deals.py`, `temporal.py`, `quality.py`, `semantic_layer.py`, `core/database.py` (~L1283, ~L1356, ~L1395).

**Done when:** a deal can be expressed as a discount against a known menu price, and ≥ 85% of visible deals pass manual spot-check for "this is real and currently valid".

---

## 6. Engineering Process

[CLAUDE.md](./CLAUDE.md) is the working agreement (verification commands,
stop-and-ask triggers, what gates a merge); [CONTRIBUTING.md](./CONTRIBUTING.md)
covers the PR workflow. This section records only the process shape.

### 6.0 The agent/human split

The implementation is agent-driven; the judgment is not.

| Agents do | Humans decide |
|-----------|---------------|
| Write code, tests, migrations, docs | Whether the design is right |
| Run `make ci` and report honestly | Whether a tradeoff is acceptable |
| Open PRs with a real test plan | Merge approval |
| Propose ADRs | Accept or reject ADRs |
| Flag drift between docs and code | What to do about it |

**What is mechanized.** A PR is required and the five CI checks (§6.7) must
be green. Branch protection requires **0 approvals**: GitHub does not let a
solo maintainer approve their own PR, and a required approval could only be
cleared by an admin bypass that skips CI too. `CODEOWNERS` flags migrations,
models, and CI/infra files in the UI but cannot block a merge. Writing an ADR
before implementing an architectural choice is convention, not mechanism.

**The consequence:** nothing but CI stands between a schema mistake and
`main`. CI cannot tell you a foreign key's cascade behavior is wrong, so the
Phase 1 reviewer's checklist and small, readable PRs do the work a second
reviewer would otherwise do.

**Review is the bottleneck, so size PRs for review.** Agents can produce a
1,000-line PR quickly; nobody can review one carefully. Prefer several small,
independently-reviewable PRs.

**Drift control.** Return to the owner when a change affects product meaning,
source policy, recurring cost, deployment commitments or data loss; explain
the consequence in product terms and recommend one option. Status lives in
README, decisions in ADRs; don't rewrite old acceptance records to claim
knowledge they didn't have.

### 6.1 Branching

Branch names, squash merging and the PR-title check are in
[CONTRIBUTING.md → Workflow](./CONTRIBUTING.md#workflow).

### 6.2 Commits

[Conventional Commits](https://www.conventionalcommits.org/); how they are
enforced is in [CONTRIBUTING.md → Commit messages](./CONTRIBUTING.md#commit-messages).

### 6.3 Pull Requests

One PR = one concern; split drive-by refactors, and read your own diff before
merging. The template is `.github/pull_request_template.md`.

### 6.4 Architectural Decision Records (ADRs)

- Every "this vs that" decision affecting more than one file lives in `docs/adr/NNNN-title.md`, from `docs/adr/0000-template.md` (Context → Decision → Alternatives considered → Consequences → References).
- Statuses: Proposed, Accepted, Superseded by ADR-NNNN, Deprecated.
- Numbered sequentially as written, never reserved in advance. A future ADR is "an ADR (next free number)" until it exists.
- The index with statuses is README's [Decisions](./README.md#decisions) table; the files are in [docs/adr/](./docs/adr/).

### 6.5 RFCs

- For changes that need discussion before implementation (e.g., "let's add a write API").
- Longer than an ADR; has a rollout plan.
- Lives in [docs/rfc/](./docs/rfc/) as `NNNN-title.md`.

### 6.5.1 Plans

- An RFC says *what and why*; a plan says *in what order, with which open
  questions closed*. A plan may supersede an RFC's **ordering**, never its
  **design**. Lives in `docs/plans/`.
- `docs/plans/` now holds only
  [0002-step-5-menu-schema-proposal.md](./docs/plans/0002-step-5-menu-schema-proposal.md),
  the normative detail behind ADR-0005. Plans 0001 and 0002 are finished and
  removed; see [docs/HISTORY.md](./docs/HISTORY.md).

### 6.6 Issues

- Issue templates: `bug` and `feature` (`.github/ISSUE_TEMPLATE/`), which apply the `bug` and `enhancement` labels.

### 6.7 CI Gates

The five required checks and what each runs are in
[CONTRIBUTING.md → CI](./CONTRIBUTING.md#ci). `make ci` is the local subset;
the strict database run is in
[README.md → Database acceptance](./README.md#database-acceptance).

---

## 7. Open Questions

Phase 5's open questions were answered at ADR-0013's acceptance ([Amendment 3](./docs/adr/0013-phase5-menu-pipeline.md#amendment-3-2026-09-29-accepted-open-questions-1-2-4-5-decided)).

1. **Multi-city?** — Out of scope for this roadmap, but the schema must not
   *prevent* it: nothing hardcodes Austin, venues carry lat/lon, and the
   metro bounding box is a CLI-overridable default. When Austin is stable, add an ADR for the
   multi-tenant approach (single DB with `region` column vs schema-per-region
   vs DB-per-region).

2. **Is the API public, and does it need auth or rate limiting?** — §2 defers
   auth "until a real consumer exists." That holds while it's read-only public
   data, but a public endpoint on a residential connection is a different risk
   profile than a laptop. Settle it in Phase 8 alongside the hosting decision.

3. **Cross-venue item canonicalization.** "What does a cheeseburger cost in
   78704?" needs a mapping from "1/2 lb Angus Burger" to a shared concept.
   Deferred deliberately: Phase 7 aggregates by course, which V1 proved
   adequate. Revisit as its own RFC when category-level aggregates
   demonstrably stop answering the questions people ask — this is a genuinely
   hard problem (fuzzy matching, taxonomy maintenance, possibly embeddings).

4. **Deferred until real correction volume or data size justifies them:**
   operator merge/split/remap commands and a review UI; legal-entity,
   franchise and brand-hierarchy modeling; retention or partitioning of Bronze
   payload versions.

5. **Non-food price verticals** (auto repair, plumbing, home services). A
   plausible future direction, and the reason venue identity and the
   observation pattern are kept food-agnostic. But **no abstraction is built
   for it now** ([CLAUDE.md](./CLAUDE.md): no speculative scaffolding). The
   open question is narrow: when a second vertical becomes real, does it share
   `price_observation` or get its own observation table? Decide then, with a
   concrete second vertical in hand.

6. **Deferred code-review findings.** The owner deferred these from the
   [2026-09-22 review](./docs/reviews/2026-09-22-full-codebase-review.md)
   (details in its §5 table). Pick each up when its trigger happens:

   | Finding | Trigger |
   |---|---|
   | R56 (rest) Direct SQL into `NUMERIC(6,5)` confidence rounds silently; the Python contracts reject first | Anything other than the Python contracts writes confidence (direct SQL, a bulk loader), or the next migration touching those columns |
   | R66 Menu replay keys vs revision key mismatch | Duplicate Bronze versions ever appear |
   | R71 Gold grain unique index could exceed the btree size limit | Phase 5 produces deep or non-ASCII menu paths |
   | R108 Observation-time rank can't decide; `Unsectioned` items unselectable | Phase 5 extraction design |
   | R110 Overture category list and pinned release | Next Overture release run |
   | R111 No review queue for ambiguous venues | A review UI is planned (see item 4) |
   | R116 No image healthcheck; CI builds amd64 while the Pi builds arm64 | Phase 8 deploy work |

---

## Appendix A — V1 Reference Map

Quick index to find the most-cited V1 files on the [`V1-Graveyard`](https://github.com/First-Helios/First-Helios/tree/V1-Graveyard) branch.

| V2 concept | V1 file |
|------------|---------|
| **Menu graph extractor** (JSON-LD + DOM) | `collectors/meal_deals/menu_sidecar.py` |
| **Menu graph target schema** | `collectors/meal_deals/menu_persistence_schema.py` |
| **Price index API** (aggregates, size/variant + promo filters) | `collectors/meal_deals/price_index_routes.py` |
| **Renderer escalation policy** | `collectors/meal_deals/render_policy.py` |
| **Website URL resolution via OSM** | `collectors/meal_deals/osm_url_resolver.py` |
| Menu DB writer | `collectors/meal_deals/menu_db_writer.py` |
| Deal observation schema | `core/database.py` (~L1283) |
| Deal applicability schema | `core/database.py` (~L1356) |
| Deal materialization schema | `core/database.py` (~L1395) + `collectors/meal_deals/semantic_layer.py` |
| Venue identity | `core/venue_identity.py` |
| Name fingerprint | `core/normalizer.py::make_fingerprint` |
| Geocoding client | `collectors/geocoding.py` |
| Facility index builder | `scripts/build_facility_index.py` |
| Sub-deal regex chain | `collectors/meal_deals/sub_deals.py` |
| Temporal parsing | `collectors/meal_deals/temporal.py` |
| Quality scoring | `collectors/meal_deals/quality.py` |
| Collector registry | `collectors/meal_deals/registry.py` |
| Source config | `config/meal_deal_sources.yaml` |
| Expectation registry | `config/meal_deal_expectation_registry.json` |
| Replay manifest builder | `scripts/build_website_scrape_replay_manifests.py` |
| Expectation diff | `scripts/compare_website_scrape_expectations.py` |
| Website scraper | `collectors/meal_deals/website_scraper.py` |
| Chain deals scraper | `collectors/meal_deals/chain_deals.py` |
