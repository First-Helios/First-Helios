# Helios V2 — Roadmap

> **Purpose.** Restart the Helios project (meal deals + restaurant menus for Austin) with the rigor of a professional codebase.
> This document distills what is worth keeping from V1, defines the V2 architecture, and sequences the rebuild into phases.
> Every phase is a PR train; every PR passes CI; every architectural decision is recorded in an ADR.
>
> **How it's built.** The implementation is **agent-driven with a human reviewer in the loop** — agents write the code, a human approves the design decisions and the changes that are expensive to reverse. See [CLAUDE.md](./CLAUDE.md) for the working agreement and [CONTRIBUTING.md](./CONTRIBUTING.md) for the review gates.
>
> **Companion:** [LEARNING_GUIDE.md](./LEARNING_GUIDE.md) — the skills course, now serving as the **reviewer's curriculum**: read the module before reviewing the phase it maps to, so you can judge the work rather than just merge it.
>
> **V1 reference:** the legacy code lives on the [`V1-Graveyard`](https://github.com/4Fortune8/First-Helios/tree/V1-Graveyard) branch of this repository. When this doc says *"port from V1"*, that is where to find the source.
>
> **Last revised:** 2026-07-29 — restructured after Phase 0 completed and the build became agent-driven.

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

> **"A trustworthy, queryable map of real food deals in Austin, built from free public data, run as a live service, with professional discipline."**

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

**Success criteria**

- A deployed HTTP endpoint returns paginated, filterable deals for Austin.
- ≥ 85% of visible deals pass manual spot-check for "this is real and currently valid."
- The service survives a reboot of its host and a wipe of its database (restore from backup + replay).
- Every architectural decision that cost more than a day to make is written down as an ADR.

> **On timelines.** The original plan budgeted 1–3 weeks per phase against a
> 12-week horizon, assuming part-time human implementation. Agent-driven
> implementation compresses coding time sharply but *not* review time, and
> review is now the bottleneck. Phases are therefore sequenced but
> deliberately **not** date-estimated — a phase is done when its "Done when"
> clause is true, not when a week elapses.

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
| 1 | Sub-deal decomposition | `collectors/meal_deals/sub_deals.py` | Splits "Mon–Fri 3–6pm. $1 off beer. Half off apps. $5 margs." into 3 offers via an ordered regex chain. Battle-tested. | `packages/helios_parsing/sub_deals.py` — port; add Hypothesis property tests; externalize the pattern list to YAML. |
| 2 | Temporal parsing | `collectors/meal_deals/temporal.py` | Handles 50+ variants: "Mon-Fri", "Monday through Friday", "3pm–close", em/en dashes, 12-hour AM/PM. | `packages/helios_parsing/temporal.py` — port; return a structured `dataclass` (`weekdays: set`, `start: time`, `end: time \| Literal["close"]`). |
| 3 | Signal-quality scoring | `collectors/meal_deals/quality.py` | 6-factor composite (price 25%, time 20%, description 15%, name 15%, restaurant-match 10%, not-addon 15%) with clear `reject < 0.20 < review < 0.40 ≤ accept` gates. | `packages/helios_parsing/quality.py` — port; weights + thresholds in config, not constants. |
| 4 | Venue identity / fingerprinting | `core/venue_identity.py` + `core/normalizer.py::make_fingerprint` | Name canonicalization, address normalization, URL canonicalization, proximity clustering. Core to dedup. | `packages/helios_core/identity.py` — port; split into name/address/url submodules; add a golden-set test fixture. |
| 5 | Replay-manifest pattern | `scripts/build_website_scrape_replay_manifests.py` + `data/cache/website_scrape_debug/*.json` | Every scrape persists raw HTML + fetch metadata + extracted signals in a deterministic bundle. Diff-able across runs. | `apps/scraper/replay/` — port bundle format; move cache root to `var/replay/` (Twelve-Factor) and index in Postgres so queries don't walk the filesystem. |
| 6 | Expectation-vs-capture diffing | `scripts/compare_website_scrape_expectations.py` + `config/meal_deal_expectation_registry.json` | Asserts "we should see $X deal at site Y" against real captures; catches regressions. | `apps/scraper/audit/expectations.py` — port; expectations become YAML per source, versioned alongside the scraper. |
| 7 | Collector registry decorator | `collectors/meal_deals/registry.py` | Self-registration so the scheduler auto-discovers scrapers. | `apps/scraper/registry.py` — port; resolve via `importlib.metadata` entry-points instead of import side-effects. |
| 8 | Config-driven strategy routing | `config/meal_deal_sources.yaml` | One YAML maps domain → strategy (static / playwright / menu_only / app_only) + selectors + rate limit. | `config/sources.yaml` — port; add JSON-Schema validation in CI so misconfigurations break the build, not runtime. |
| 9 | Multi-layer data model (pattern) | `core/database.py` — `DealObservation → DealApplicability → DealMaterialization` | Observation is the canonical atom; applicability fans out to many venues; materialization is the pre-computed consumer view. | `packages/helios_core/db/models/` — port schema intent; redesign with SQLAlchemy 2.0 typed `Mapped[...]`, enum types, and **only** this pattern (drop the legacy `MealDeal` denormalized table). |

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
│   ├── helios_core/      # Domain models, DB session, identity
│   │   ├── db/           # SQLAlchemy 2.0 typed models, session, base
│   │   │   └── models/
│   │   ├── identity.py   # from V1 core/venue_identity.py
│   │   └── tests/
│   └── helios_parsing/   # Pure-function text parsers, zero I/O
│       ├── sub_deals.py
│       ├── temporal.py
│       ├── quality.py
│       └── tests/
├── infra/
│   ├── docker-compose.yml
│   ├── Dockerfile
│   └── systemd/          # staging host (OrangePi) units
├── alembic/
│   ├── env.py
│   └── versions/
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

> **Arch parity is not hypothetical.** The original `postgis/postgis` image
> is amd64-only and could never have run on the Pi at all — the bug sat
> unnoticed for five weeks precisely because nothing had been deployed
> there yet. Running staging on the real target hardware catches this class
> of problem; a laptop and an x86 CI runner do not. See
> [ADR-0002](./docs/adr/0002-containerization.md).

**What the staging host runs**

- Docker + Docker Compose (same image as prod). ✅ *Working today —
  `make dev` brings up Postgres → migrate → API.*
- A systemd unit that starts the stack on boot and restarts on failure,
  pulls `main`, and runs migrations as an explicit step. *(Phase 2)*
- Postgres with daily `pg_dump` to a local external drive. *(Phase 8)*
- Scrapers on a cron schedule, reduced frequency vs. prod. *(Phase 5+)*
- Prometheus node-exporter for dashboards. *(Phase 8)*

> **Note on Postgres topology.** This section originally assumed Postgres
> would run on the staging *host* with only the app layer in Docker. It
> currently runs in Compose alongside the app, which is simpler and fine for
> staging. Prod topology (containerized vs. host-installed vs. managed) is an
> open question for ADR-0006 in Phase 8.

**What prod will run (Phase 8)**

- The same Docker image, promoted manually after staging is green for N hours.
- Hosted options ranked by learning value / cost:
  1. **Hetzner Cloud CAX11** (~€4/mo, ARM64) — best $ / learning.
  2. **Fly.io** — free tier, Docker-native, auto-scale, multi-region.
  3. **Railway** — easiest, Procfile-style.
  4. **DigitalOcean Droplet** — classic; most tutorials.

ADR-0006 in Phase 8 will make the call with numbers.

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

- **V1 baseline:** `httpx` + `selectolax` for static HTML, `playwright-sync` for SPAs, pure-Python orchestration, cron for scheduling.
- **Phase 5 decision (ADR-0005):** evaluate Scrapy vs Crawlee vs keeping custom, on throwaway spikes, *before* writing the real scrapers.
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

Each phase ends with a demoable artifact on `main`, merged through a PR with green CI. Each maps to a learning module (see [Learning Guide](./LEARNING_GUIDE.md)) — read it *before reviewing* that phase's PRs.

**Status at a glance**

| Phase | Name | Status |
|-------|------|--------|
| 0 | Foundations & Tooling | ✅ **Complete** |
| 1 | Domain Model & Migrations | ⬅️ **Next** |
| 2 | First Light — read API + staging deploy | Planned |
| 3 | Parsing Library | Planned |
| 4 | Venue Identity & Geocoding | Planned |
| 5 | Scrapers — decide, then build | Planned |
| 6 | Ingest Pipeline | Planned |
| 7 | API Surface — full | Planned |
| 8 | Operations — prod | Partially done early |
| 9 | Harden | Planned |

**What changed in the 2026-07-29 revision**

- **Phase 2 "First Light" is new.** A thin read API and a real staging
  deployment land immediately after the schema, instead of waiting for the
  old Phase 7. This proves the DB → API → deployed path once, early, so that
  integration and deployment risk isn't all concentrated at the end. Phases
  2–6 of the original plan each shift down by one.
- **The old Phases 4 and 5 merged** into a single Phase 5. The original plan
  had you hand-build a McDonald's scraper, *then* evaluate frameworks, then
  rewire it — deliberate learning-by-doing. With agents writing the code,
  building production code twice is waste; the evaluation now happens as
  throwaway spikes before the real implementation.
- **Docker moved out of Phase 8** to now (see
  [ADR-0002](./docs/adr/0002-containerization.md)), so Phase 8 is reduced to
  prod hosting and operational hardening.

---

### Phase 0 — Foundations & Tooling ✅ COMPLETE

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

**Delivered beyond the original scope** (PRs #3–#5): `CLAUDE.md` (agent
working agreement), `CONTRIBUTING.md`, `LICENSE` (BUSL 1.1), `/readyz`,
`pydantic-settings` config with lazy engine creation, and the containerization
from ADR-0002.

**Done when:** `git push` to a feature branch opens a PR, CI runs automatically, merge advances main. No exceptions.
✅ **Met.** Five required CI checks gate `main`; squash-only; auto-delete branches.

**Post-Phase-0 correction (2026-07-29).** The original branch protection
required 1 approving review, following this document's "(self-review OK for
solo dev)" line. GitHub does not support that — you cannot approve your own
PR — so every merge had to bypass protection, and a bypass skips the CI
checks too. Corrected to 0 required approvals with all five CI checks
required, which is strictly stronger in practice. See §6.0.

---

### Phase 1 — Domain Model & Migrations ⬅️ NEXT

**Learning module to review against:** [M5](./LEARNING_GUIDE.md#m5--relational-modeling) · [M6](./LEARNING_GUIDE.md#m6--sqlalchemy-20--alembic)

**Goal:** the canonical schema, written fresh from lessons learned, migrated cleanly, tested at the constraint level.

**Deliverables**

- `packages/helios_core/db/models/deal.py` — `DealObservation`, `DealApplicability`, `DealMaterialization` as typed `Mapped[...]`.
- `packages/helios_core/db/models/venue.py` — grow the existing `Venue` stub; add `VenueAlias`, `SiteIdentity`.
- `packages/helios_core/db/models/menu.py` — `MenuSection`, `MenuItem`, `MenuPricePoint`, `MenuModifier` (schema only; no data yet).
- The `raw` / `canonical` / `mart` schema split (see §4.3), including the
  `include_schemas` + schema-allowlist change to `alembic/env.py` that the
  split requires — its current `include_object` filter is schema-blind.
- Postgres `CHECK` constraints for enums; partial unique indexes for chain templates.
- Alembic migration(s) for the canonical schema — autogenerated, then hand-reviewed.
- Unit tests asserting each unique constraint, each `CHECK`, each FK cascade rule.
- **ADR-0003:** "Three-layer schema (raw / canonical / mart)."

**Port hints (`V1-Graveyard` branch)**

- `core/database.py::DealObservation` (~L1283) — keep the 41 fields that proved useful, drop the dead ones.
- `core/venue_identity.py` for venue + alias patterns.

**Sequencing note.** This is a large phase; split it across several PRs
(venue/identity models, deal models, menu models, schema split) rather than
one. A 900-line schema PR cannot be meaningfully reviewed in one sitting, and
with no second reviewer (§6.0) your own careful read is the only review this
gets — so make it a readable one.

**Reviewer's checklist** — what to actually look for, since this is the phase
where a bad decision is most expensive to undo:

- Does every enum have a `CHECK` constraint, not just a Python-side `Enum`?
- Is every FK's `ondelete` behavior deliberate, and does a test prove it?
- Do the migrations run **and** roll back cleanly on a non-empty database?
- Is `DealObservation` the only write path for observations, per §4.3?
- Any column that's nullable — is it nullable because the domain allows
  absence, or because it was easier?

**Done when:** `alembic upgrade head` on an empty DB produces the full schema; `downgrade` returns it to empty; every constraint has at least one failing-test case.

---

### Phase 2 — First Light: read API + staging deploy

**Learning modules to review against:** [M11](./LEARNING_GUIDE.md#m11--api-design) · [M12](./LEARNING_GUIDE.md#m12--operations)

**Goal:** the thinnest possible end-to-end slice, running for real. One
resource, read-only, served from the canonical schema, deployed to the Orange
Pi and reachable. Nothing about deals yet — this phase exists to prove the
whole path works and to establish the API conventions everything later
inherits.

**Why here and not Phase 7.** The original plan deferred every HTTP concern
to the end. That concentrates integration and deployment risk into one late
phase, and it means months of work with nothing observable. Doing it now
costs little — the container stack already runs — and every later phase gets
validated against a real deployment instead of a laptop.

**Deliverables**

- `apps/api/routes/venues.py` — `GET /venues` (cursor-paginated) and
  `GET /venues/{id}`, reading the Phase 1 schema.
- Pydantic response models, separate from ORM models. The wire format is a
  contract; do not leak SQLAlchemy objects into it.
- A seed/fixture command so the endpoints return something real in dev.
- Structured logging (`structlog`) with request IDs — cheap now, painful to
  retrofit once there's traffic.
- CORS configuration — the frontend is a separate repo and will need it.
- **ADR-0004:** "API conventions" — cursor vs. offset pagination, error
  shape, versioning strategy, what a 404 vs. an empty list means. Small ADR,
  but every later endpoint inherits it, so it's worth settling once.
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

### Phase 3 — Parsing Library

**Learning module to review against:** [M4](./LEARNING_GUIDE.md#m4--testing-pyramid)

**Goal:** the three text-processing algorithms lifted into a pure-function library with exhaustive tests. **No I/O, no DB, no HTTP.**

**Deliverables**

- `packages/helios_parsing/sub_deals.py` — `extract_sub_deals(text: str) → list[SubDeal]` returning a typed dataclass.
- `packages/helios_parsing/temporal.py` — `extract_validity(text: str) → Validity` dataclass.
- `packages/helios_parsing/quality.py` — `score_signal(observation: dict) → SignalQuality` with components + total.
- Coverage ≥ 90% for the package.
- Hypothesis property tests — e.g., "temporal parser is idempotent on its own output", "sub-deal count is ≥ 1 for any non-empty text with a dollar sign".
- 50+ golden-file test cases ported from V1 + 20 new ones from recent scrapes.

**Port hints (`V1-Graveyard` branch)**

- `collectors/meal_deals/sub_deals.py` — regex chain, priority order matters.
- `collectors/meal_deals/temporal.py` — day/time regex with em/en dashes, "close" sentinel.
- `collectors/meal_deals/quality.py` — 6-factor weights (25/20/15/15/10/15).

**Done when:** the parsing package can be published to a private index and pulled into the scraper by version number — no cross-package imports.

---

### Phase 4 — Venue Identity & Geocoding

**Learning module to review against:** [M10](./LEARNING_GUIDE.md#m10--geospatial)

**Goal:** given a restaurant name + address, return a canonical venue ID (or create one). Given an address, return a lat/lng and H3 cell.

**Deliverables**

- `packages/helios_core/identity.py` — name fingerprinting, address normalization, URL canonicalization, proximity clustering.
- `packages/helios_core/geo.py` — Nominatim client with 1-req/sec throttle, manual overrides for ambiguous Austin suburbs, disk-cached responses keyed by normalized query.
- H3 r6–r9 cell computation on every venue insert.
- Unit tests: golden-set fixture of 100 hand-labeled matches with ≥ 95% precision.
- Integration test: Nominatim responses replayed from disk fixtures — no live calls in CI.

**Port hints (`V1-Graveyard` branch)**

- `core/venue_identity.py`, `core/normalizer.py::make_fingerprint`.
- `collectors/geocoding.py` — including the 25-city override dict.
- `scripts/build_facility_index.py` — rate-limit + viewbox patterns.

**Done when:** loading 1000 Overture restaurant rows produces < 2% duplicate venues and < 1% wrong geocodes (both measured against a hand-labeled 100-row sample).

---

### Phase 5 — Scrapers: decide, then build

**Learning modules to review against:** [M7](./LEARNING_GUIDE.md#m7--http-html--the-real-web) · [M8](./LEARNING_GUIDE.md#m8--scraping-fundamentals)

**Goal:** pick the scraping framework on evidence, then build two chains on
it — one static, one SPA — sharing rate-limiting and replay middleware.

> **Merged from the original Phases 4 and 5.** The old plan had you
> hand-build McDonald's, *then* evaluate frameworks, then rewire the working
> scraper. That sequence taught by doing, which was right for a human
> learner. With agents writing the implementation, building production code
> twice is waste — so the evaluation happens first, as throwaway spikes, and
> the real implementation is written once.

**Deliverables**

- **Spikes first, and they are throwaway.** Scrape McDonald's in Scrapy and
  in Crawlee/Playwright. Benchmark throughput, ergonomics, output fidelity.
  This code is deleted after the decision — do not let a spike graduate into
  production by accident.
- **ADR-0005:** "Scraper framework choice" — explicit tradeoffs, benchmark
  numbers, decision, consequences.
- `apps/scraper/chains/mcdonalds.py` — static HTML; fetch → parse → ingest.
- `apps/scraper/chains/subway.py` — SPA; exercises the Playwright path.
- `apps/scraper/replay/bundle.py` — writes `var/replay/<chain>/<date>/<url-hash>.json`.
- `apps/scraper/audit/expectations.py` — compares a YAML expectation file against bundles.
- `config/sources.yaml` — strategy, selectors, rate limit per chain, JSON-Schema validated in CI.
- `config/expectations.yaml` — 3–5 known-good deals per chain.
- CLI: `helios scrape mcdonalds --once`.
- Integration tests: frozen HTML fixtures → assert `DealObservation` row counts + field values. **No live network calls in CI.**

**Scraping etiquette is a hard requirement, not a nicety.** Honor
`robots.txt`, identify with a real User-Agent, respect the per-source rate
limits in `config/sources.yaml`, and never bypass a paywall or login (§2,
"public data only"). A scraper that gets the project IP-banned costs more
than the data was worth.

**Done when:** both chains run under one framework, share middleware for rate limiting + replay bundling, have fixture-based tests, and the expectation diff passes.

---

### Phase 6 — Ingest Pipeline

**Learning module to review against:** [M9](./LEARNING_GUIDE.md#m9--data-engineering-patterns)

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

### Phase 7 — API Surface: full

**Learning module to review against:** [M11](./LEARNING_GUIDE.md#m11--api-design)

**Goal:** grow Phase 2's skeleton into the complete read-only public API.

**Deliverables**

- `GET /deals?venue_id=&brand=&h3=&valid_at=` — cursor-paginated, filtered.
- `GET /deals/{id}` — single deal with full materialization + source bundle reference.
- `GET /venues/{id}` — extend Phase 2's endpoint with currently-valid deals.
- `GET /venues/{id}/menu` — menu (empty list until menus are populated).
- OpenAPI schema at `/openapi.json`, docs at `/docs` — already live from Phase 2; keep accurate.
- Contract test: OpenAPI schema committed and diffed in CI; breaking changes fail the build.
- Read-path performance: every filter combination above is index-backed. Add
  a test that fails on a sequential scan of `deal_materialization`.

**Done when:** `curl https://.../deals?h3=872a10075ffffff&valid_at=now` returns a page of real deals with correct pagination and a stable shape.

---

### Phase 8 — Operations: Prod & Resilience

**Learning module to review against:** [M12](./LEARNING_GUIDE.md#m12--operations)

**Goal:** promote from the Orange Pi to a hosted prod environment; make the
whole thing observable and recoverable.

> **Reduced scope.** Containerization landed early
> ([ADR-0002](./docs/adr/0002-containerization.md)) and staging on the Pi
> landed in Phase 2. What remains here is genuinely production-only concerns.

**Already done** (kept for the record)

- ~~Multi-stage `Dockerfile`~~ — done, ADR-0002. Scraper entrypoint still
  pending; needs Phase 5's scraper to exist.
- ~~`docker-compose.yml` for local dev~~ — done (Postgres → migrate → API).
- ~~Orange Pi staging with systemd~~ — done in Phase 2.

**Deliverables**

- **ADR-0006:** "Prod hosting choice" — compare Hetzner CAX / Fly.io /
  Railway / DO by cost, ergonomics, and ARM64 availability. Decide with
  numbers. Note the architecture question this settles: today's Dockerfile is
  arch-agnostic and builds natively wherever it runs; if prod is ARM64 this
  stays simple, if it's x86 decide multi-arch buildx vs. native-only builds.
- **Secrets handling** — the one genuinely new production concern. Dev uses
  `.env` with throwaway credentials; prod needs real secret storage, rotation,
  and secrets that never reach the image, a log line, or the repo.
- **TLS + public domain**, and a decision on whether the API is fully public
  or gated. Note §2 defers auth — revisit if that still holds under real traffic.
- **Rate limiting** on the public API. It's read-only, but it will be on the
  open internet.
- **Backups:** nightly `pg_dump` → off-box (external drive + object storage).
  A backup you have never restored is not a backup — a restore drill is part
  of this phase, not an afterthought.
- **Observability:** Prometheus scrape endpoint, node-exporter, and alerting
  on the handful of things that actually page (service down, disk full,
  scrape failure rate, replication of the ingest pipeline stalling).
- **Deploy pipeline:** `.github/workflows/deploy.yml` — tagged releases build
  and push to a registry; prod pulls. Same image promoted from staging after
  it's been green for 24h. Migrations remain an explicit step.
- **Runbook:** what to do when a scraper breaks, Postgres fills the disk,
  Nominatim bans us, or prod is down while staging is fine.

**Done when:** you can wipe the Orange Pi, restore from backup, and be
serving yesterday's data within 30 minutes — demonstrated, not assumed. Prod
deploy is one command from a tagged release.

---

### Phase 9 — Harden

**Goal:** paper cuts, polish, a coverage gate on `main`.

**Deliverables**

- Integration test suite spinning up a real Postgres via `testcontainers`.
- Coverage gate: `main` requires ≥ 85% for `packages/` and ≥ 70% for `apps/`.
- Load test: k6 or Locust against a local API; document p95 latency targets.
- Security pass: `pip-audit`, dependency review, secret-scanning, and
  automated dependency updates (Dependabot or equivalent).
- Retire the `V1-Graveyard` reference uses — by now V2 is self-sufficient.
- Revisit the `imresamu/postgis` pin from ADR-0002: is it still maintained,
  and does the prod topology chosen in Phase 8 still need it?

**Done when:** you could hand the repo to another developer and they could ship a feature in their first week.

---

## 6. Engineering Process

### 6.0 The agent/human split

The implementation is agent-driven; the judgment is not. Where the line sits:

| Agents do | Humans decide |
|-----------|---------------|
| Write code, tests, migrations, docs | Whether the design is right |
| Run `make ci` and report honestly | Whether a tradeoff is acceptable |
| Open PRs with a real test plan | Merge approval |
| Propose ADRs | Accept or reject ADRs |
| Flag drift between docs and code | What to do about it |

**What is actually mechanized — and what isn't.** Good intentions don't
scale, so it matters to be precise about which gates are real:

| Gate | Enforced? |
|------|-----------|
| Five required CI checks | ✅ Yes — a red build cannot merge |
| PR required (no direct push to `main`) | ✅ Yes |
| Conversation resolution | ✅ Yes |
| ADR before implementing an architectural decision | ⚠️ Convention — see [CLAUDE.md](./CLAUDE.md) |
| `CODEOWNERS` review on migrations/models | ❌ **Cannot be, solo** — see below |

**The solo-maintainer constraint.** GitHub does not permit approving your own
pull request, so a required approval count of 1 is *unsatisfiable* for a
single maintainer — it can only be cleared by an admin bypass, and a bypass
skips every rule including CI. Branch protection therefore requires **0
approvals**, which makes the CI checks a real gate rather than a formality
waived on every merge. A lower nominal bar that actually holds beats a higher
one that forces a total bypass.

`CODEOWNERS` is kept as a **signal**: it flags PRs touching
`alembic/versions/**` and `packages/**/db/models/**` in the UI so the
expensive-to-reverse changes are visible, but it cannot block a merge with
one human. Copilot's review does not help here either — it leaves
`COMMENTED`, never `APPROVED`.

**The consequence for Phase 1:** nothing but CI stands between a schema
mistake and `main`. Since CI cannot tell you a foreign key's cascade
behavior is wrong, the reviewer's checklist in Phase 1 and small,
readable PRs are doing the work that a second reviewer would otherwise do.

**An ADR is the checkpoint.** When an agent hits a genuinely new
architectural choice, the correct move is to write the ADR and stop — not to
implement and document afterward. See [CLAUDE.md](./CLAUDE.md) for the full
list of stop-and-ask triggers.

**Review is the bottleneck, so size PRs for review.** Agents can produce a
1,000-line PR quickly; nobody can review one carefully. Prefer several small,
independently-reviewable PRs — this matters most in Phase 1, where the schema
decisions are hardest to reverse.

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
- Numbered sequentially as written, not reserved in advance.

**ADR ledger**

| # | Title | Status | Phase |
|---|-------|--------|-------|
| [0001](./docs/adr/0001-stack-choice.md) | Language, framework, and data stack | Accepted | 0 |
| [0002](./docs/adr/0002-containerization.md) | Containerization, pulled forward from Phase 8 | Accepted | 0 |
| 0003 | Three-layer schema (raw / canonical / mart) | Planned | 1 |
| 0004 | API conventions (pagination, errors, versioning) | Planned | 2 |
| 0005 | Scraper framework choice | Planned | 5 |
| 0006 | Prod hosting choice | Planned | 8 |

### 6.5 RFCs

- For changes that need discussion before implementation (e.g., "let's add a write API").
- Longer than an ADR; has a rollout plan.
- Lives in `docs/rfc/NNNN-title.md`.

### 6.6 Issues & Labels

- Issue templates: `bug`, `feature`, `chore`.
- Labels: `area:api`, `area:scraper`, `area:parsing`, `area:db`, `area:ops`, `good-first-issue`, `tech-debt`, `blocked`.

### 6.7 CI Gates

**Live today** (all five are required checks on `main`):

- `Lint & format` — `ruff check` + `ruff format --check` via pre-commit
- `Type check` — `mypy --strict`
- `Tests` — `pytest` against a real Postgres service
- `Lockfile up to date` — `uv lock --check`
- `Docker image` — builds the image and smoke-tests `/healthz`

**Planned**

- Coverage threshold (Phase 9)
- `alembic check` — autogenerate diff is empty; schema matches models (Phase 1,
  once there's a schema worth guarding)
- OpenAPI schema diff — breaking changes fail the build (Phase 7)

---

## 7. Day-1 Kickoff Checklist

Files to create on the very first commit of V2 (before any feature code):

- [x] `pyproject.toml` — project metadata, deps via `uv`
- [x] `uv.lock`
- [x] `ruff.toml`
- [x] `mypy.ini`
- [x] `.pre-commit-config.yaml` (ruff, mypy, commitlint, trailing-whitespace)
- [x] `.gitignore` — already present; extend for `var/` and `.env`
- [x] `.env.example`
- [x] `README.md` — already present; expand in Phase 0
- [x] `ROADMAP.md` — this file
- [x] `LEARNING_GUIDE.md`
- [x] `CLAUDE.md` — agent working instructions (not in the original plan; added once the build became agent-driven)
- [x] `LICENSE` — Business Source License 1.1 (not in the original plan; source-visible, non-commercial until the Change Date — see the [LICENSE](../LICENSE) file itself for the current parameters)
- [x] `CONTRIBUTING.md` — how to open a PR, write a commit, write an ADR
- [x] `.github/workflows/ci.yml`
- [x] `.github/pull_request_template.md`
- [x] `.github/ISSUE_TEMPLATE/{bug,feature}.md`
- [x] `.github/CODEOWNERS`
- [x] `docs/adr/0000-template.md`
- [x] `docs/adr/0001-stack-choice.md`  ← first real ADR, ratifying this roadmap
- [x] `docs/rfc/0000-template.md`
- [x] `Makefile` — has `install`, `lint`, `typecheck`, `test`, `ci`, `clean`; `migrate` and `dev` targets land with Docker (Phase 8 groundwork, pulled earlier — see §4.2)
- [x] `infra/docker-compose.yml` (Postgres only for now)
- [x] `alembic.ini` — lives at repo root, not `infra/` as originally sketched (matches `pyproject.toml`'s `pythonpath` setup)
- [x] `alembic/env.py` — also repo root; no longer empty, the initial `venue` migration landed in PR #2
- [x] GitHub repo settings:
  - [x] Branch protection on `main`: require PR, require CI (all 4 jobs as required status checks), require conversation resolution
  - [x] Default branch = `main`
  - [x] Auto-delete head branches after merge
  - [x] Squash-only merges (merge commit and rebase-merge disabled)
  - [ ] Disable merge commits (squash only)

---

## 8. Open Questions / Further Considerations

1. **Where does V2 live?** — **Decided: this repo.** `main` is V2. `V1-Graveyard` holds the legacy code. History is a feature; having V1 one `git checkout` away is useful during Phases 1–6.

2. **Menus in V1 of V2?** — Schema: yes (Phase 1 includes `menu_*` tables). Population: no (no menu scraper through Phase 6). Menus become Phase 10 once deals are solid.

3. **Multi-city?** — Out of scope for this roadmap. When Austin is stable, add an ADR for the multi-tenant approach (single DB with `region` column vs schema-per-region vs DB-per-region).

4. **Write API / contributor endpoint?** — Out of scope. If SpiritPool browser extension is re-integrated, it becomes an RFC.

5. **Frontend?** — This roadmap is backend-only. The frontend is a separate repo and a separate project; it consumes this API. Phase 2 adds CORS so it can.

6. **When to re-evaluate this roadmap?** — After **Phase 4** (identity + geocoding are the risky bit; if they go sideways, the scraper and ingest phases reshuffle). Write a retrospective in `docs/retro/YYYY-MM-DD-phase-4.md`.

7. **Is the API public, and does it need auth or rate limiting?** — §2 defers
   auth "until a real consumer exists." That holds while it's read-only public
   data, but a public endpoint on a residential connection is a different risk
   profile than a laptop. Settle it in Phase 8 alongside the hosting decision,
   not by drifting into it.

8. **How much does the agent-driven model change the review burden?** — Open,
   and worth watching. Coding time compresses; review time doesn't. If review
   becomes the bottleneck (it likely will in Phase 1), the fix is smaller PRs
   and tighter ADR gates, not faster reading.

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
