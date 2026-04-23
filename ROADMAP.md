# Helios V2 — Roadmap

> **Purpose.** Restart the Helios project (meal deals + restaurant menus for Austin) with the rigor of a professional codebase.
> This document distills what is worth keeping from V1, defines the V2 architecture, and sequences the rebuild into phases.
> Every phase is a PR train; every PR passes CI; every architectural decision is recorded in an ADR.
>
> **Companion:** [LEARNING_GUIDE.md](./LEARNING_GUIDE.md) — the skills course. Each V2 phase maps to at least one learning module.
>
> **V1 reference:** the legacy code lives on the [`V1-Graveyard`](https://github.com/4Fortune8/First-Helios/tree/V1-Graveyard) branch of this repository. When this doc says *"port from V1"*, that is where to find the source.

---

## Table of Contents

1. [North Star](#1-north-star)
2. [Scope — V1 of V2](#2-scope--v1-of-v2)
3. [Part A — Distilled Assets](#3-part-a--distilled-assets)
   - 3.1 [Sources (Free & Public Only)](#31-sources-free--public-only)
   - 3.2 [Processes (Reusable Algorithms)](#32-processes-reusable-algorithms)
   - 3.3 [Skills Inventory](#33-skills-inventory)
4. [Part B — Target Architecture](#4-part-b--target-architecture)
5. [Part C — Phased Build Plan](#5-part-c--phased-build-plan)
6. [Engineering Process](#6-engineering-process)
7. [Day-1 Kickoff Checklist](#7-day-1-kickoff-checklist)
8. [Open Questions / Further Considerations](#8-open-questions--further-considerations)

---

## 1. North Star

> **"A trustworthy, queryable map of real food deals in Austin, built from free public data, by a one-person team operating with professional discipline."**

- **Trustworthy** — every price and validity window is traceable to a captured page.
- **Queryable** — a clean HTTP API with pagination, filters, and OpenAPI docs.
- **Real** — each deal passes a signal-quality gate before becoming visible.
- **Free public data** — no paid APIs in the V1 dependency graph.
- **Professional discipline** — PR-gated main, CI, typed code, ADRs for decisions, tests for every non-trivial function.

---

## 2. Scope — V1 of V2

**In scope**

- Restaurant **meal deals** (promotions, limited-time offers, happy hours, combos) for Austin, TX.
- Restaurant **menus** (sections, items, prices, modifiers) — schema now, population later.
- First-party scrapes of 6–10 anchor chains, plus a handful of local independents sourced from Overture / OSM.
- Venue identity (which restaurant is which) and geocoding (lat/lng + H3).
- A read-only public API.
- Replay + audit tooling so every data point is traceable.

**Out of scope**

- Jobs, labor data, events, sentiment, Revelio, SerpAPI, Google Places — all V1 modules that are not meal-deal/menu related.
- Authentication / write API (deferred until a real consumer exists).
- Multi-city coverage (Austin-only until the Austin pipeline is stable).
- The SpiritPool browser extension (separate project; this repo only handles its ingest endpoint if it is ever revisited).

**Success criteria (12-week horizon)**

- Phase 7 complete: a deployed FastAPI endpoint returns paginated, filterable deals.
- ≥ 85% of visible deals pass manual spot-check for "this is real and currently valid."
- Every module in the [Learning Guide](./LEARNING_GUIDE.md) has been completed with a merged capstone PR.

---

## 3. Part A — Distilled Assets

These are the pieces of V1 worth preserving. Everything else either never shipped, depended on a paid API, or was built before the design was understood.

### 3.1 Sources (Free & Public Only)

Eight chain websites scraped directly + three geospatial reference datasets. Zero paid APIs.

| # | Source | URL Pattern | Strategy | What We Get | Constraints |
|---|--------|-------------|----------|-------------|-------------|
| 1 | McDonald's | `mcdonalds.com/us/en-us/deals.html` | `static_html` | Deal names (`h2/h3`), prices inline, app-only deals noted | 1 req/sec; change-rate: weekly |
| 2 | Taco Bell | `tacobell.com/food/deals-and-combos` | `static_html` | Structured product links, price + calorie pairs | 1 req/sec |
| 3 | Domino's | `dominos.com/deals` | `static_html` + reCAPTCHA-aware | Deal sections as uppercase `h2` | reCAPTCHA Enterprise but initial HTML loads |
| 4 | Wendy's | `wendys.com/deals` | `static_html` | Image-heavy; deal names in `alt=` | 1 req/sec |
| 5 | ThunderCloud Subs | `thundercloud.com/main-menu/` | `menu_only` | WordPress static menu; prices as small/large | Local, friendly |
| 6 | Pizza Hut | `pizzahut.com/deals` | `playwright_required` | React SPA; deals in JSON bootstrap | Headless Chromium; 1 req/2s |
| 7 | Subway | `subway.com/en-us/menunutrition/deals` | `playwright_required` | Angular SPA | Headless Chromium; 1 req/2s |
| 8 | Sonic | `sonicdrivein.com/deals` | `app_only` | Most deals require the app; website has a subset | Accept partial coverage |

| # | Reference Source | Endpoint | What We Get | Constraints |
|---|------------------|----------|-------------|-------------|
| R1 | Nominatim (OpenStreetMap) | `nominatim.openstreetmap.org/search` | Free-form address → (lat, lng) | 1 req/sec, user-agent required, viewbox recommended |
| R2 | Overture Maps POI | Parquet downloads on S3 | Business name, address, category, website URL | Download-once, refresh monthly |
| R3 | OpenStreetMap / Overpass | `overpass-api.de` | Business website URL by name + area | 1 req/sec; prefer Overture for bulk |

**Dropped from V1** (either paid, out of scope, or broken as built):

- SerpAPI — paid; jobs are out of scope.
- Google Places API — paid; OSM + Overture + sitemaps cover V1 needs.
- Revelio Labs labor feed — proprietary; out of scope.
- TheirStack, Jobicy, RapidAPI ActiveJobs — jobs; out of scope.
- BLS / QCEW / LAUS / OEWS — labor ground-truth; out of scope for V1.
- Ticketmaster / Eventbrite / Meetup / Do512 / Austin City Calendar — events; out of scope.

**Discovery mechanism for independents.** Instead of paid APIs, V2 uses:

1. Overture Maps filtered to Austin `category = food_and_beverage`.
2. Per-restaurant website resolution via Overture `websites` field → fallback to OSM `contact:website` tag.
3. A registry file (`config/sources.yaml`) that any human can add a known-good site to.

### 3.2 Processes (Reusable Algorithms)

Nine algorithms worth porting. Each has a proven V1 implementation and a clear path to a cleaner V2 version. The **V1 source** column points to the file on the `V1-Graveyard` branch.

| # | Process | V1 Source | Why Keep | V2 Target |
|---|---------|-----------|----------|-----------|
| 1 | Sub-deal decomposition | `collectors/meal_deals/sub_deals.py` | Splits "Mon–Fri 3–6pm. $1 off beer. Half off apps. $5 margs." into 3 offers via an ordered regex chain. Battle-tested. | `packages/parsing/sub_deals.py` — port; add Hypothesis property tests; externalize the pattern list to YAML. |
| 2 | Temporal parsing | `collectors/meal_deals/temporal.py` | Handles 50+ variants: "Mon-Fri", "Monday through Friday", "3pm–close", em/en dashes, 12-hour AM/PM. | `packages/parsing/temporal.py` — port; return a structured `dataclass` (`weekdays: set`, `start: time`, `end: time \| Literal["close"]`). |
| 3 | Signal-quality scoring | `collectors/meal_deals/quality.py` | 6-factor composite (price 25%, time 20%, description 15%, name 15%, restaurant-match 10%, not-addon 15%) with clear `reject < 0.20 < review < 0.40 ≤ accept` gates. | `packages/parsing/quality.py` — port; weights + thresholds in config, not constants. |
| 4 | Venue identity / fingerprinting | `core/venue_identity.py` + `core/normalizer.py::make_fingerprint` | Name canonicalization, address normalization, URL canonicalization, proximity clustering. Core to dedup. | `packages/core/identity.py` — port; split into name/address/url submodules; add a golden-set test fixture. |
| 5 | Replay-manifest pattern | `scripts/build_website_scrape_replay_manifests.py` + `data/cache/website_scrape_debug/*.json` | Every scrape persists raw HTML + fetch metadata + extracted signals in a deterministic bundle. Diff-able across runs. | `apps/scraper/replay/` — port bundle format; move cache root to `var/replay/` (Twelve-Factor) and index in Postgres so queries don't walk the filesystem. |
| 6 | Expectation-vs-capture diffing | `scripts/compare_website_scrape_expectations.py` + `config/meal_deal_expectation_registry.json` | Asserts "we should see $X deal at site Y" against real captures; catches regressions. | `apps/scraper/audit/expectations.py` — port; expectations become YAML per source, versioned alongside the scraper. |
| 7 | Collector registry decorator | `collectors/meal_deals/registry.py` | Self-registration so the scheduler auto-discovers scrapers. | `apps/scraper/registry.py` — port; resolve via `importlib.metadata` entry-points instead of import side-effects. |
| 8 | Config-driven strategy routing | `config/meal_deal_sources.yaml` | One YAML maps domain → strategy (static / playwright / menu_only / app_only) + selectors + rate limit. | `config/sources.yaml` — port; add JSON-Schema validation in CI so misconfigurations break the build, not runtime. |
| 9 | Multi-layer data model (pattern) | `core/database.py` — `DealObservation → DealApplicability → DealMaterialization` | Observation is the canonical atom; applicability fans out to many venues; materialization is the pre-computed consumer view. | `packages/core/models/` — port schema intent; redesign with SQLAlchemy 2.0 typed `Mapped[...]`, enum types, and **only** this pattern (drop the legacy `MealDeal` denormalized table). |

**What we are deliberately *not* porting**

- The legacy `meal_deals` denormalized table (pre-dates the `DealObservation` pattern). Redundant.
- The `employer_data`, `labor_data`, `events`, `job_boards`, `sentiment` collectors. Out of scope.
- `core/baseline.py`, `core/targeting.py`, `core/rate_manager.py`, `core/scheduler.py` — rewrite rather than port. The ideas are sound but the code grew organically; a clean rewrite is faster than a refactor.
- Playwright stealth hackery specific to employer sites we will no longer scrape.

### 3.3 Skills Inventory

What a dev needs to own this codebase professionally. Each skill is expanded into a module in the [Learning Guide](./LEARNING_GUIDE.md).

| Area | Skills |
|------|--------|
| **Python** | Typing (`Mapped`, `TypedDict`, generics), `dataclasses`, `@dataclass(slots=True)`, `pathlib`, packaging with `pyproject.toml`, dependency management with `uv`, virtual envs. |
| **Tooling** | `ruff` (lint + format), `mypy --strict`, `pre-commit`, conventional commits, `commitlint`, semantic versioning. |
| **SQL & data modeling** | Normal forms, primary / foreign keys, unique constraints, partial indexes, JSONB vs columns, transaction isolation, index strategy, migration safety. |
| **ORM** | SQLAlchemy 2.0 declarative typed models, relationships, eager vs lazy loading, session lifecycle, Alembic autogenerate + manual edits, zero-downtime migration patterns. |
| **Web fundamentals** | HTTP semantics, status codes, redirects, caching, cookies, `robots.txt`, sitemaps, DNS, TLS, `User-Agent` etiquette, rate-limit negotiation. |
| **Scraping** | `httpx`, `selectolax`, `BeautifulSoup`, Playwright (sync + async), Scrapy, Crawlee, headless Chromium, JSON-LD extraction, PDF text extraction. |
| **Data engineering** | Idempotency, at-least-once vs exactly-once, raw → canonical → mart layering, lineage, replay, backfill strategy, watermarks, dead-letter queues. |
| **Geospatial** | Lat/lng, geocoding, reverse geocoding, H3 hex grids, PostGIS basics (`GEOGRAPHY(POINT)`, `ST_DWithin`), bounding boxes. |
| **Parsing** | Regex craft, regex debugging, property-based testing with Hypothesis, when rules beat ML (and when they don't). |
| **API design** | REST vs RPC, FastAPI, Pydantic v2, OpenAPI, pagination (cursor vs offset), error shapes, idempotency keys, rate limiting. |
| **Testing** | pytest, fixtures, `parametrize`, factories, property tests, contract tests, golden files, coverage tooling. |
| **Ops** | Docker, docker-compose, systemd, `.env` hygiene, structured logging (structlog), Prometheus metrics, healthchecks, backups, hosted deploys (Fly.io / Railway / Hetzner / DO). |
| **Process** | Git (branches, rebase, worktrees), PR anatomy, code review, ADRs, RFCs, issue templates, CODEOWNERS, branch protection, CI design. |

---

## 4. Part B — Target Architecture

### 4.1 Repo Layout (monorepo)

```
helios-v2/
├── apps/
│   ├── api/              # FastAPI application
│   │   ├── main.py
│   │   ├── routes/
│   │   └── tests/
│   └── scraper/          # Scraping workers + CLI
│       ├── chains/       # one module per chain (mcdonalds.py, tacobell.py, ...)
│       ├── replay/       # replay-manifest builder + diff
│       ├── audit/        # expectation-vs-capture comparator
│       └── tests/
├── packages/
│   ├── core/             # Domain models, DB session, identity
│   │   ├── models/       # SQLAlchemy 2.0 typed models
│   │   ├── db.py
│   │   ├── identity.py   # from V1 core/venue_identity.py
│   │   └── tests/
│   └── parsing/          # Pure-function text parsers, zero I/O
│       ├── sub_deals.py
│       ├── temporal.py
│       ├── quality.py
│       └── tests/
├── infra/
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── alembic/
│   │   ├── env.py
│   │   └── versions/
│   └── systemd/          # staging host (OrangePi) units
├── config/
│   ├── sources.yaml      # scrape strategy per chain
│   └── expectations.yaml # expectation registry
├── docs/
│   ├── adr/              # Architecture Decision Records
│   │   └── 0000-template.md
│   └── rfc/              # Request for Comments (larger proposals)
│       └── 0000-template.md
├── .github/
│   ├── workflows/ci.yml
│   ├── pull_request_template.md
│   ├── ISSUE_TEMPLATE/{bug,feature}.md
│   └── CODEOWNERS
├── scripts/              # Dev-only one-offs (NOT production code)
├── .pre-commit-config.yaml
├── pyproject.toml
├── ruff.toml
├── mypy.ini
├── alembic.ini
├── Makefile
├── ROADMAP.md            # ← this file
├── LEARNING_GUIDE.md
└── README.md
```

### 4.2 Environments (Dev → Staging → Prod)

This is the industry-standard flow. Your Orange Pi becomes the **staging** environment, not production.

```
┌─────────────┐   push    ┌──────────┐   merge    ┌───────────────────┐   promote   ┌─────────────────┐
│  Laptop     │ ────────▶ │  GitHub  │ ─────────▶ │  Orange Pi        │ ──────────▶ │  Hosted Prod    │
│  (dev)      │   + PR    │  (CI)    │            │  (staging, ARM64) │             │  (VPS or PaaS)  │
└─────────────┘           └──────────┘            └───────────────────┘             └─────────────────┘
     │                         │                         │                                  │
     │ run tests locally       │ ruff/mypy/pytest        │ smoke-test on real hardware      │ only deploy
     │ `docker compose up`     │ block merge on red      │ run scrapers against live web    │ artifacts that
     │                         │                         │ observe metrics                  │ passed staging
```

**Why staging on the Orange Pi is the right move**

1. **Arch parity.** Your prod target (see Phase 8) will likely be ARM64 (cheap VPS, Hetzner CAX, or RPi-class). The Orange Pi mirrors that.
2. **Real-world network.** Staging on your LAN means real residential IP, real rate-limit conditions, real DNS — not a sterile CI runner.
3. **Cheap.** The OPi is already running. Zero marginal cost.
4. **Safe blast radius.** If a scraper loops, it consumes *your* bandwidth, not a hosted bill.

**What the staging host runs**

- Docker + docker-compose (same image as prod).
- A systemd unit that pulls `main` on merge, runs migrations, restarts services.
- Postgres 16 with daily `pg_dump` to a local external drive.
- Scrapers on a cron schedule (reduced frequency vs. prod).
- Prometheus node-exporter so you can see it from a dashboard.

**What prod will run (Phase 8)**

- The same Docker image, promoted manually after staging is green for N hours.
- Hosted options ranked by learning value / cost:
  1. **Hetzner Cloud CAX11** (~€4/mo, ARM64) — best $ / learning.
  2. **Fly.io** — free tier, Docker-native, auto-scale, multi-region.
  3. **Railway** — easiest, Procfile-style.
  4. **DigitalOcean Droplet** — classic; most tutorials.

ADR-0004 in Phase 8 will make the call with numbers.

### 4.3 Data Layer

- **Postgres 16** as the only database. Install with **PostGIS** + the **h3-pg** extension for geospatial.
- **Schema split** within a single database (not separate DBs):
  - `raw` — untransformed captures (HTML snapshots indexed, not the HTML itself — that lives on disk in `var/replay/`).
  - `canonical` — the domain model (`deal_observation`, `deal_applicability`, `venue`, `site_identity`, `menu_*`).
  - `mart` — denormalized read-views (`deal_materialization`).
- **Alembic** migrations with autogenerate + hand edits, reviewed in PRs. **No `metadata.create_all()`** in production code, ever.
- **dbt** is *not* in V1 scope. If `mart` gets complex enough (≥ 5 read-views), a learning module + ADR will introduce dbt in a later phase.

### 4.4 API Layer

- **FastAPI** + Pydantic v2.
- Routes: `GET /deals`, `GET /deals/{id}`, `GET /venues`, `GET /venues/{id}`, `GET /venues/{id}/menu`.
- **Cursor-based** pagination (not offset — it's O(1) at any page).
- Uniform error shape (`{detail, code, trace_id}`).
- OpenAPI published at `/docs`; schema tested in CI for breaking changes.
- No auth in V1. CORS locked to the single frontend origin.

### 4.5 Scraper Layer

- **V1 baseline (Phase 4):** `httpx` + `selectolax` for static HTML, `playwright-sync` for SPAs, pure-Python orchestration, cron for scheduling.
- **Phase 5 decision (ADR-0003):** evaluate Scrapy vs Crawlee vs keeping custom. Decided after Learning Module 8.
- **Rate-limit middleware:** one token bucket per host, config-driven.
- **Replay bundle:** every scrape writes `var/replay/<source>/<yyyy-mm-dd>/<site>.json` with `{url, status, html_path, extracted_signals, fetch_type}`.
- **Expectation diff:** nightly CI job runs `compare_expectations_to_bundles` and posts failures to an issue.

### 4.6 Observability

- **Logging:** `structlog` with JSON output in staging/prod, human-readable in dev.
- **Metrics:** `prometheus_client`; counters for `scrapes_total{source,outcome}`, `deal_observations_total{source}`, histograms for scrape latency.
- **Tracing:** not in V1 scope.
- **Healthcheck:** `GET /healthz` (liveness) + `GET /readyz` (DB ping).

---

## 5. Part C — Phased Build Plan

Each phase is 1–3 weeks part-time. Each phase begins with a learning module (see [Learning Guide](./LEARNING_GUIDE.md)) and ends with a demoable artifact on `main`, merged through a PR with green CI.

### Phase 0 — Foundations & Tooling

**Learning modules:** [M1](./LEARNING_GUIDE.md#m1--modern-python-project-hygiene) · [M2](./LEARNING_GUIDE.md#m2--git--team-workflow) · [M3](./LEARNING_GUIDE.md#m3--design-docs-adrs-and-rfcs)

**Goal:** a new-repo skeleton that already has every professional habit baked in, so the first line of feature code is written with the guardrails already up.

**Deliverables**

- `pyproject.toml` (PEP 621) with `uv` for lockfile + install.
- `ruff.toml`, `mypy.ini` (strict), `.pre-commit-config.yaml`.
- `.github/workflows/ci.yml` — ruff, mypy, pytest, Python 3.12 matrix.
- `.github/pull_request_template.md`, `.github/ISSUE_TEMPLATE/{bug,feature}.md`, `CODEOWNERS`.
- `docs/adr/0000-template.md`, `docs/rfc/0000-template.md`.
- **ADR-0001:** "Language, framework, and data stack choices" — ratifies this roadmap.
- `apps/api/main.py` with a single `GET /healthz` route.
- One pytest passing: `assert healthz returns 200`.
- GitHub branch protection on `main`: require PR, require 1 review (self-review OK for solo dev), require CI green, squash-merge only.

**Done when:** `git push` to a feature branch opens a PR, CI runs automatically, merge advances main. No exceptions.

---

### Phase 1 — Domain Model & Migrations

**Learning modules:** [M5](./LEARNING_GUIDE.md#m5--relational-modeling) · [M6](./LEARNING_GUIDE.md#m6--sqlalchemy-20--alembic)

**Goal:** the canonical schema, written fresh from lessons learned, migrated cleanly, tested at the constraint level.

**Deliverables**

- `packages/core/models/deal.py` — `DealObservation`, `DealApplicability`, `DealMaterialization` as typed `Mapped[...]`.
- `packages/core/models/venue.py` — `Venue`, `VenueAlias`, `SiteIdentity`.
- `packages/core/models/menu.py` — `MenuSection`, `MenuItem`, `MenuPricePoint`, `MenuModifier` (schema only; no data yet).
- Postgres `CHECK` constraints for enums; partial unique indexes for chain templates.
- Alembic migration `0001_canonical_schema.py` (autogenerated, hand-reviewed).
- Unit tests asserting each unique constraint, each `CHECK`, each FK cascade rule.
- **ADR-0002:** "Three-layer schema (raw / canonical / mart)."

**Port hints (`V1-Graveyard` branch)**

- `core/database.py::DealObservation` (~L1283) — keep the 41 fields that proved useful, drop the dead ones.
- `core/venue_identity.py` for venue + alias patterns.

**Done when:** `alembic upgrade head` on an empty DB produces the full schema; every constraint has at least one failing-test case.

---

### Phase 2 — Parsing Library

**Learning module:** [M4](./LEARNING_GUIDE.md#m4--testing-pyramid)

**Goal:** the three text-processing algorithms lifted into a pure-function library with exhaustive tests. **No I/O, no DB, no HTTP.**

**Deliverables**

- `packages/parsing/sub_deals.py` — `extract_sub_deals(text: str) → list[SubDeal]` returning a typed dataclass.
- `packages/parsing/temporal.py` — `extract_validity(text: str) → Validity` dataclass.
- `packages/parsing/quality.py` — `score_signal(observation: dict) → SignalQuality` with components + total.
- Coverage ≥ 90% for the package.
- Hypothesis property tests — e.g., "temporal parser is idempotent on its own output", "sub-deal count is ≥ 1 for any non-empty text with a dollar sign".
- 50+ golden-file test cases ported from V1 + 20 new ones from recent scrapes.

**Port hints (`V1-Graveyard` branch)**

- `collectors/meal_deals/sub_deals.py` — regex chain, priority order matters.
- `collectors/meal_deals/temporal.py` — day/time regex with em/en dashes, "close" sentinel.
- `collectors/meal_deals/quality.py` — 6-factor weights (25/20/15/15/10/15).

**Done when:** the parsing package can be published to a private index and pulled into the scraper by version number — no cross-package imports.

---

### Phase 3 — Venue Identity & Geocoding

**Learning module:** [M10](./LEARNING_GUIDE.md#m10--geospatial)

**Goal:** given a restaurant name + address, return a canonical venue ID (or create one). Given an address, return a lat/lng and H3 cell.

**Deliverables**

- `packages/core/identity.py` — name fingerprinting, address normalization, URL canonicalization, proximity clustering.
- `packages/core/geo.py` — Nominatim client with 1-req/sec throttle, manual overrides for ambiguous Austin suburbs, disk-cached responses keyed by normalized query.
- H3 r6–r9 cell computation on every venue insert.
- Unit tests: golden-set fixture of 100 hand-labeled matches with ≥ 95% precision.
- Integration test: Nominatim responses replayed from disk fixtures — no live calls in CI.

**Port hints (`V1-Graveyard` branch)**

- `core/venue_identity.py`, `core/normalizer.py::make_fingerprint`.
- `collectors/geocoding.py` — including the 25-city override dict.
- `scripts/build_facility_index.py` — rate-limit + viewbox patterns.

**Done when:** loading 1000 Overture restaurant rows produces < 2% duplicate venues and < 1% wrong geocodes (both measured against a hand-labeled 100-row sample).

---

### Phase 4 — First Static Scraper

**Learning module:** [M7](./LEARNING_GUIDE.md#m7--http-html--the-real-web)

**Goal:** one chain (recommend **McDonald's** — simplest HTML) scraped end-to-end, producing `DealObservation` rows via the parsing library and writing a replay bundle.

**Deliverables**

- `apps/scraper/chains/mcdonalds.py` — fetch → parse → ingest.
- `apps/scraper/replay/bundle.py` — writes `var/replay/mcdonalds/<date>/<url-hash>.json`.
- `apps/scraper/audit/expectations.py` — compares a YAML expectation file against bundles.
- `config/sources.yaml` entry for McDonald's (strategy, selectors, rate limit).
- `config/expectations.yaml` with 3–5 known-good deals.
- CLI: `helios scrape mcdonalds --once` works locally.
- Integration test: feed a frozen HTML fixture, assert `DealObservation` row count + field values.

**Done when:** the CLI run produces a replay bundle on disk, N new `deal_observation` rows in Postgres, and the expectation diff passes.

---

### Phase 5 — Scraper Framework Decision

**Learning module:** [M8](./LEARNING_GUIDE.md#m8--scraping-fundamentals)

**Goal:** make the framework choice consciously, document it, rewire Phase 4.

**Deliverables**

- A week of hands-on experiments: rebuild McDonald's once in **Scrapy**, once in **Crawlee** (Playwright). Benchmark throughput, ergonomics, output fidelity.
- **ADR-0003:** "Scraper framework choice" — explicit tradeoffs, benchmark numbers, decision, consequences.
- Rewire `apps/scraper/chains/mcdonalds.py` to the chosen framework.
- Add a second chain on the chosen framework: recommend **Subway** (SPA — exercises Playwright integration).

**Done when:** both McDonald's (static) and Subway (SPA) run under one framework, share middleware for rate limiting + replay bundling, and have fixture-based tests.

---

### Phase 6 — Ingest Pipeline

**Learning module:** [M9](./LEARNING_GUIDE.md#m9--data-engineering-patterns)

**Goal:** scraping → parsing → identity → persistence, all idempotent, all re-runnable.

**Deliverables**

- Upsert on `(source, source_observation_key)` — re-running a scrape produces zero duplicates.
- Applicability fan-out: chain-wide deals create N `deal_applicability` rows (one per active venue of that brand).
- Materialization refresh: post-ingest task updates `mart.deal_materialization`.
- Backfill CLI: `helios backfill --source mcdonalds --from 2026-01-01` replays bundles from disk into the DB.
- Metrics: `scrapes_total`, `observations_ingested_total`, `applicability_rows_total`, `materialization_refresh_seconds`.
- Dead-letter: signals that fail quality-gating land in `raw.rejected_signals` with a reason code.

**Done when:** you can drop the entire `canonical` schema and reconstruct it by running `helios backfill --all` against the replay bundles on disk.

---

### Phase 7 — API Surface

**Learning module:** [M11](./LEARNING_GUIDE.md#m11--api-design)

**Goal:** a read-only public API that a frontend or curl user can consume.

**Deliverables**

- `GET /deals?venue_id=&brand=&h3=&valid_at=` — cursor-paginated, filtered.
- `GET /deals/{id}` — single deal with full materialization + source bundle reference.
- `GET /venues` — cursor-paginated.
- `GET /venues/{id}` — single venue + currently-valid deals.
- `GET /venues/{id}/menu` — menu (empty list until menus are populated).
- OpenAPI schema at `/openapi.json`, docs at `/docs`.
- Contract test: OpenAPI schema committed and diffed in CI; breaking changes fail the build.

**Done when:** `curl https://.../deals?h3=872a10075ffffff&valid_at=now` returns a page of real deals with correct pagination and a stable shape.

---

### Phase 8 — Operations: Staging (OPi) → Prod (Hosted)

**Learning module:** [M12](./LEARNING_GUIDE.md#m12--operations)

**Goal:** deployable to the Orange Pi (staging), promotable to a hosted provider (prod), observable, recoverable.

**Deliverables**

- Multi-stage `Dockerfile` for API + scraper workers (single image, different entrypoints).
- `docker-compose.yml` for local dev (Postgres + API + one scraper).
- Orange Pi staging:
  - systemd-timer → `git pull && docker compose pull && docker compose up -d`.
  - Postgres 16 on the host; docker for app layer.
  - Nightly `pg_dump` → external USB drive + Backblaze B2.
  - Node-exporter + a Prometheus scrape endpoint.
- Prod deploy:
  - **ADR-0004:** "Prod hosting choice" — compare Hetzner CAX / Fly.io / Railway / DO by $/learning/ergonomics. Decide.
  - Same Docker image, promoted manually after staging is green for 24h.
  - `.github/workflows/deploy.yml` — tagged releases build + push to registry; prod server pulls.
- Runbook: what to do when a scraper breaks, when Postgres runs out of space, when Nominatim bans us, when prod goes down and staging is still up.

**Done when:** you can wipe the OPi, run a single `make stage`, and have yesterday's data restored within 30 minutes. Prod deploy is one command from a tagged release.

---

### Phase 9 — Harden

**Goal:** paper cuts, polish, a coverage gate on `main`.

**Deliverables**

- Integration test suite spinning up a real Postgres via `testcontainers`.
- Coverage gate: `main` requires ≥ 85% for `packages/` and ≥ 70% for `apps/`.
- Load test: k6 or Locust against a local API; document p95 latency targets.
- Security pass: `pip-audit`, dependency review, secret-scanning.
- Retire the `V1-Graveyard` reference uses — by now V2 is self-sufficient.

**Done when:** you could hand the repo to another developer and they could ship a feature in their first week.

---

## 6. Engineering Process

### 6.1 Branching

- `main` is protected; every change lands via PR.
- Feature branches: `feat/<slug>`, `fix/<slug>`, `chore/<slug>`, `docs/<slug>`.
- No long-lived branches. Rebase onto `main` before merge. Squash-merge by default (one feature = one commit on main).

### 6.2 Commits

- [Conventional Commits](https://www.conventionalcommits.org/): `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`, `build:`, `ci:`.
- Scope when useful: `feat(parsing): add sub-deal priority for half-off trailing form`.
- Imperative mood; ≤ 72 char subject.
- Commitlint enforced via pre-commit + CI.

### 6.3 Pull Requests

- Template requires: *What changed · Why · How I tested · Risk · Rollback plan*.
- One PR = one concern. Split drive-by refactors.
- Every PR runs: ruff, mypy, pytest, coverage diff.
- Self-review before requesting review. Even solo devs benefit from reading their own diff in the PR UI.

### 6.4 Architectural Decision Records (ADRs)

- Every "this vs that" decision affecting more than one file lives in `docs/adr/NNNN-title.md`.
- Statuses: `proposed`, `accepted`, `deprecated`, `superseded-by #NN`.
- Template: Context → Decision → Consequences → Alternatives considered.
- Expected ADRs in Phases 0–5: at least 5.

### 6.5 RFCs

- For changes that need discussion before implementation (e.g., "let's add a write API").
- Longer than an ADR; has a rollout plan.
- Lives in `docs/rfc/NNNN-title.md`.

### 6.6 Issues & Labels

- Issue templates: `bug`, `feature`, `chore`.
- Labels: `area:api`, `area:scraper`, `area:parsing`, `area:db`, `area:ops`, `good-first-issue`, `tech-debt`, `blocked`.

### 6.7 CI Gates

- `ruff check` + `ruff format --check`
- `mypy --strict` for `packages/`, `mypy` (non-strict) for `apps/`
- `pytest` with coverage threshold (enforced in Phase 9)
- `alembic check` (autogenerate diff == empty; schema matches models)
- OpenAPI schema diff

---

## 7. Day-1 Kickoff Checklist

Files to create on the very first commit of V2 (before any feature code):

- [ ] `pyproject.toml` — project metadata, deps via `uv`
- [ ] `uv.lock`
- [ ] `ruff.toml`
- [ ] `mypy.ini`
- [ ] `.pre-commit-config.yaml` (ruff, mypy, commitlint, trailing-whitespace)
- [ ] `.gitignore` — already present; extend for `var/` and `.env`
- [ ] `.env.example`
- [ ] `README.md` — already present; expand in Phase 0
- [ ] `ROADMAP.md` — this file
- [ ] `LEARNING_GUIDE.md`
- [ ] `CONTRIBUTING.md` — how to open a PR, write a commit, write an ADR
- [ ] `.github/workflows/ci.yml`
- [ ] `.github/pull_request_template.md`
- [ ] `.github/ISSUE_TEMPLATE/{bug,feature}.md`
- [ ] `.github/CODEOWNERS`
- [ ] `docs/adr/0000-template.md`
- [ ] `docs/adr/0001-stack-choice.md`  ← first real ADR, ratifying this roadmap
- [ ] `docs/rfc/0000-template.md`
- [ ] `Makefile` — `make install`, `make test`, `make lint`, `make migrate`, `make dev`
- [ ] `infra/docker-compose.yml` (Postgres only for now)
- [ ] `infra/alembic.ini`
- [ ] `infra/alembic/env.py` (empty; first migration lands in Phase 1)
- [ ] GitHub repo settings:
  - [ ] Branch protection on `main`: require PR, require CI, require conversation resolution
  - [ ] Default branch = `main`
  - [ ] Auto-delete head branches after merge
  - [ ] Disable merge commits (squash only)

---

## 8. Open Questions / Further Considerations

1. **Where does V2 live?** — **Decided: this repo.** `main` is V2. `V1-Graveyard` holds the legacy code. History is a feature; having V1 one `git checkout` away is useful during Phases 1–6.

2. **Menus in V1 of V2?** — Schema: yes (Phase 1 includes `menu_*` tables). Population: no (no menu scraper in Phase 4–6). Menus become Phase 10 once deals are solid.

3. **Multi-city?** — Out of scope for this roadmap. When Austin is stable, add an ADR for the multi-tenant approach (single DB with `region` column vs schema-per-region vs DB-per-region).

4. **Write API / contributor endpoint?** — Out of scope. If SpiritPool browser extension is re-integrated, it becomes an RFC.

5. **Frontend?** — This roadmap is backend-only. The frontend is a separate repo and a separate project; it consumes the API defined in Phase 7.

6. **When to re-evaluate this roadmap?** — After Phase 3 (identity + geocoding are the risky bit; if they go sideways, phases 4–6 reshuffle). Write a retrospective in `docs/retro/2026-XX-XX-phase-3.md`.

---

## Appendix A — V1 Reference Map

Quick index to find the most-cited V1 files on the [`V1-Graveyard`](https://github.com/4Fortune8/First-Helios/tree/V1-Graveyard) branch.

| V2 concept | V1 file |
|------------|---------|
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

---

*Last updated: 2026-04-23. This is a living document; update via PR when a phase completes or a decision changes.*
