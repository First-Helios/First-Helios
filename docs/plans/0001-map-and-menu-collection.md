# Plan 0001: Map data + menu collection — implementation spec

**Status:** Approved (owner, 2026-08-01)
**Implements:** [RFC-0001](../rfc/0001-menu-pricing-first.md) work-plan PRs 1–3, 5–8
**Supersedes ordering in:** RFC-0001 work plan (PR 4 deferred — see §0)

This is the handoff spec for the worker agent. RFC-0001 is the *design*; this
document is the *sequence*, with the open questions closed and the
stop-and-ask gates resolved. Where this document and RFC-0001 disagree on
ordering, this document wins. Where they disagree on design, RFC-0001 wins.

---

## 0. Decisions closed by the owner (2026-08-01)

These were listed as unresolved in RFC-0001 §"Unresolved questions" or left
to the worker. They are now settled — do not re-open them.

| # | Question | Decision |
|---|----------|----------|
| D-1 | RFC-0001 PR 4 (venues read API) sits between schema and discovery | **Deferred** until after Overture seeding lands real venues. Serving an empty `venue` table proves nothing; the API is built in step 6 against real rows. |
| D-2 | Overture parquet ingest mechanics (RFC-0001 unresolved #3) | **DuckDB.** Read the remote Overture parquet directly with a SQL bbox predicate. No bulk download, filtering pushed into the query. New runtime dep — approved. |
| D-3 | Austin-metro polygon (RFC-0001 unresolved #2) | **Simple bounding box covering Travis + Williamson counties.** Slightly over-inclusive is acceptable and cheap to tighten later. It lives in config as a parameter, never a constant in code. |

Still open, still gated, **not part of this plan**:

- **ADR-0007 (LLM extraction fallback)** — proposed only after rungs 1–4
  coverage is measured. No LLM code in this train.
- **Cross-venue item canonicalization** — deferred per RFC-0001 §D2.
- **Deals layer** — Phase 10.

---

## 1. Where the code actually is

Stated plainly so the worker doesn't trust the docs over the code
(CLAUDE.md "Ground truth"):

- One table: `Venue` — `id`, `name`, `address`, `created_at`, `updated_at`.
  It lives in `public`. It is a bare scaffold with no production data.
- One migration: `c16e32ee8cd2_create_venue_table.py`.
- `alembic/env.py`'s `include_object` filter is **schema-blind** — it drops
  any reflected object not in `Base.metadata`, which is what currently keeps
  PostGIS/Tiger out of autogenerate.
- `apps/api/main.py` — `healthz` / `readyz` only.
- Runtime deps: `alembic`, `fastapi`, `psycopg[binary]`, `pydantic-settings`,
  `sqlalchemy`, `uvicorn`. **Nothing geospatial, no parquet reader, no HTTP
  client, no HTML parser.**

Everything else described in ROADMAP.md and RFC-0001 is design, not code.

---

## 2. Dependency budget

Each step adds only what that step needs. Anything not on this list is a
fresh stop-and-ask (CLAUDE.md).

| Step | Runtime deps added | Why |
|------|--------------------|-----|
| 3 (seeding) | `duckdb`, `h3`, `httpx` | remote parquet + SQL filter (D-2); H3 cells on every venue; Nominatim/Overpass calls |
| 4 (URL resolution) | — | reuses `httpx` |
| 5 (fetch/replay) | per **ADR-0005** | framework choice is its own decision |
| 6 (extraction) | `selectolax` *or* `beautifulsoup4` + `lxml`; `pdfplumber` | DOM rung; PDF rung |

Deliberately **not** added: any queue, cache, or search-index service.
Scheduling is cron on the staging host (RFC-0001 §D5).

`shapely` is **not** needed — a bounding box is four float comparisons, and
DuckDB can express it in SQL. Only reach for it if D-3 is later tightened
to a real polygon, and say so in the PR body.

---

## 3. The sequence

Each step is one PR unless noted. Every PR: green `make ci`, Conventional
Commit, a real test plan in the body.

### Step 0 — `docs: accept ADR-0003` ✅ *done — this PR*

[ADR-0003](../adr/0003-three-layer-schema.md) was `Proposed`. It gates every
schema PR below, and the `venue`-out-of-`public` move is only free while the
table is empty.

**Done when:** status flipped to `Accepted` with the date, owner merges.
Docs-only — no CI beyond lint.

---

### Step 1 — `feat(db): venue identity schema` (RFC-0001 PR 1)

The single most expensive-to-reverse PR in this train. Keep it readable.

- Create the three Postgres schemas (`raw`, `canonical`, `mart`) — the
  migration must `CREATE SCHEMA IF NOT EXISTS` before the first table in each
  layer and drop them on `downgrade`.
- Make Alembic schema-aware: `include_schemas=True` in **both**
  `context.configure` calls, and extend `include_object` with a schema
  allowlist `{raw, canonical, mart}` + `public` (for `alembic_version` only).
  Without the allowlist, `include_schemas=True` reintroduces exactly the
  PostGIS/Tiger `DROP` problem the current filter exists to prevent. Document
  the footgun in the module docstring.
- Move `venue` from `public` to `canonical`.
- Grow `venue`; add `brand`, `venue_alias`, `venue_source`, `site_identity`
  per RFC-0001 §D2. No food-specific columns on `venue`.
- Every model declares `__table_args__ = {"schema": ...}`. Add a test that
  asserts **every** mapped table has a non-null, allowlisted schema.
- Test fixtures must create all three schemas — `Base.metadata.create_all()`
  fails on a missing schema rather than creating it.

**Done when:** `alembic upgrade head` on an empty DB, then `downgrade base`,
both clean. Every unique constraint, `CHECK`, and FK `ondelete` has a
failing-test case.

### Step 2 — `feat(db): menu graph schema` (RFC-0001 PR 2)

`menu_page`, `menu_section`, `menu_item`, `price_observation`,
`menu_modifier` per RFC-0001 §D2.

Non-negotiables:

- **Money is integer cents.** No float column anywhere near a price.
- **`price_observation` is append-only.** No code path may `UPDATE` a price.
- Deterministic natural keys so re-ingest is idempotent —
  `menu_item(section_id, normalized_name)`,
  `price_observation(menu_item_id, variant, source_kind, observed_at)`.
- Every enum (`source_kind`, `renderer`, `status`, …) gets a Postgres
  `CHECK`, not just a Python `Enum`.

**Done when:** same bar as Step 1.

### Step 3 — `feat(db): raw/mart layers` (RFC-0001 PR 3)

- `raw` capture index (one row per fetch) + `raw.rejected_signals`
  dead-letter. Bytes stay on disk in `var/replay/`; `raw` only indexes.
- `mart.current_menu` — latest accepted price per (item, variant), with
  `as_of` and staleness age. An **ordinary table refreshed by a task**, not a
  materialized view (ADR-0003).
- One price-index aggregate view. One. Add more when an endpoint needs them.
- FK direction is enforced by review: `raw` → `canonical` → `mart`, never
  backwards.

**Done when:** same bar; plus `mart` provably rebuildable from `canonical` in
one command.

---

### Step 4 — `feat(discovery): Overture/OSM venue seeding` (RFC-0001 PR 5)

**This is where map data lands.**

- `config/regions.yaml` (or equivalent) holds the Travis + Williamson
  bounding box per D-3. A parameter, not a constant.
- DuckDB reads the Overture places parquet remotely, filtered to
  `food_and_beverage` within the bbox, in SQL. Do not download the full
  dataset.
- Rows land in `venue_source` with the external record's raw identity
  preserved — that table is the dedup/merge audit trail.
- `packages/helios_core/identity.py` — name fingerprinting, address
  normalization, proximity clustering. Port `core/venue_identity.py` and
  `core/normalizer.py::make_fingerprint` from `V1-Graveyard`.
- `packages/helios_core/geo.py` — Nominatim client, **1 req/sec**,
  disk-cached by normalized query, with V1's Austin-suburb override dict.
- H3 cells (r6–r9) computed on every venue insert.
- No live network calls in CI — Nominatim/Overpass responses replay from
  disk fixtures.

**Done when:** 1,000 Overture rows ingest with **<2% duplicate venues** and
**<1% bad geocodes**, both measured against a hand-labeled 100-row sample.
Report the actual venue count for the metro in the PR body.

### Step 5 — `feat(discovery): website + menu-URL resolution` (RFC-0001 PR 6)

- Overture `websites` field first; Overpass `website` / `contact:website`
  fallback (port `osm_url_resolver.py`); `config/sources.yaml` as the
  human-editable manual registry and chain-anchor seed list.
- URL canonicalization + liveness check → `site_identity`, with the
  resolution method recorded.
- Menu-URL frontier: common paths (`/menu`, `/menus`, `/food`), sitemap
  entries matching menu patterns, on-site anchors hitting a menu lexicon.
  Persist discovered menu URLs on `site_identity` so re-scrapes skip
  discovery.

**Done when:** measured %-website-coverage for the metro is reported in the
PR body. **V1 measured 30–40% from free sources — that is the planning
number, not a failure.** If it lands far below 30%, *stop and report* rather
than scraping around it: that number determines whether 300 venues is
reachable at all.

### Step 6 — `feat(api): venues read endpoints` (RFC-0001 PR 4, moved)

Now that there are real rows. ROADMAP Phase 2 as written: cursor pagination,
**ADR-0004**, staging deploy to the Orange Pi.

---

### Step 7 — ADR-0005, then `feat(scraper): fetch + replay core` (RFC-0001 PR 7)

- **Spikes first, and they are throwaway.** Scrapy vs Crawlee/Playwright on a
  real menu site. Delete the spike code after the decision — do not let a
  spike graduate into production.
- Weigh it for the actual workload: **~1,000+ distinct hosts fetched shallowly
  once a month**, not a few hosts crawled deeply. That favors per-host
  politeness and breadth over crawl-depth machinery.
- Then build: per-host token-bucket rate limiting, replay bundles at
  `var/replay/<source>/<date>/<url-hash>.json`, matching `raw` capture-index
  rows, `config/expectations.yaml` + the expectation-diff audit, and
  `helios scrape <source> --once`.

**Etiquette is a hard requirement:** robots.txt honored, real User-Agent,
per-host rate limits, no paywall/login bypass. No live network calls in CI.

### Step 8 — `feat(extract): JSON-LD + DOM ladder` (RFC-0001 PR 8)

**This is where menu collection lands.**

Port `menu_sidecar.py` rungs 1–2 into `packages/helios_parsing/` as pure
functions:

1. **JSON-LD / schema.org** (`Menu → MenuSection → MenuItem → Offer`) —
   always parsed when present.
2. **DOM heuristics** — heading + list/table item-price pairing, V1's
   service-period/course/modifier regexes, confidence scored.
   Promotional-looking rows are **excluded from menu prices and parked** for
   the future deals layer.

Both rungs emit the **same normalized sidecar structure** → one ingest path
→ `canonical`. Extraction always reads from the stored replay bundle, so it
is re-runnable from disk without re-fetching.

**Done when:** 20+ golden-file fixtures from real Austin sites pass, and
idempotent re-ingest is proven (re-running produces zero new rows).

---

## 4. Not in this train

Steps 9–11 of RFC-0001 (render policy + PDF, scheduling/change detection,
price-index endpoints) follow this train. They are unchanged from RFC-0001
and are not re-specified here.

---

## 5. Milestone

Unchanged from RFC-0001:

> **300+ distinct Austin/Round Rock venues with ≥1 priced menu item each,
> ≥80% observed within 45 days, every price traceable to a replay bundle** —
> measured by a query, stated in the retro.

The first genuinely informative checkpoint is **Step 5's coverage number**,
not the milestone itself. Everything downstream is sized by it.
