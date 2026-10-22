# ADR-0019: The path to a public v1 site (frontend, page set, area UX, public deploy)

**Status:** Accepted in part, 2026-10-21 by the owner (session P8-0; see
[Owner decision](#owner-decision)): Q1–Q3, Q6c, Q7 and Q9 as recommended. The public deploy
(§4; Q4, Q5, Q6a, Q6b, Q8) is **deferred**: v1 runs locally first. Proposed 2026-10-21.
Build progress (§5): step 1 done 2026-10-22 (P8-1,
[record](../reviews/2026-10-22-p8-1-gold-fill.md)); step 2 built 2026-10-22 (P8-3,
[ADR-0006 Amendment 1](./0006-gold-menu-read-models.md#amendment-1-2026-10-22-section-names-and-variant-only-item-names)).
Steps 3–8 are not built.
**Date:** 2026-10-21
**Phase:** 8 (operations), plus the frontend that ROADMAP §2 keeps in a separate repo
**Extends:** [ADR-0008](./0008-read-api-conventions.md) (read API; its Unit B staging deploy and
CORS), [ADR-0007](./0007-gold-price-index-projection.md) (price-index grid),
[ADR-0018](./0018-venue-filters-and-item-price-history.md) (venue filters, price history),
[ADR-0002](./0002-containerization.md) (one image, Compose)
**Would amend (if accepted, each in its own reviewed unit):** ADR-0007 (new `area_kind` values and a
cell-listing endpoint), ADR-0006 (ancestor names in `gold.current_menu`), ADR-0008 (a
`rate_limited` error code, an additive `source_url`). It is also the v1 part of the Phase 8
"prod hosting ADR".

## Context

The read API is complete for v1 (`apps/api/openapi_snapshot.json`, `main@9046fe7`):

| Path | Params |
|---|---|
| `GET /v1/venues` | `limit`, `cursor`, `has_menu`, `organization`, `area` |
| `GET /v1/venues/{venue_id}` | |
| `GET /v1/venues/{venue_id}/menu` | |
| `GET /v1/items/{item_id}/price-history` | |
| `GET /v1/price-index` | `lat`, `lon` (required), `category_kind`, `currency` |
| `GET /healthz`, `GET /readyz` | |

Two things have no plan: a frontend that uses this API, and a public deploy. The facts below were
checked in this session, read-only.

### F1. The V1 frontend repo

`/home/fortune/CodeProjects/First-Helios_Frontend` (17 commits, last `909e6e0` on 2026-04-21,
MPL-2.0; this repo is BSL 1.1):

- **Stack.** No build step: `index.html` (395 lines), `css/style.css` (1,582 lines, hard-coded hex
  colours, no tokens), eight vanilla-JS IIFEs on `window` globals in `js/` (3,386 lines), and
  `serve.py` (a stdlib static server on :3000). Leaflet 1.9.4 and h3-js 4.1.0 load from unpkg
  without SRI (`index.html` L7, L384–385). There is no `package.json`, lockfile, router, types,
  tests, lint or CI, and no deploy config. Its README mentions nginx on the Pi, but no config
  for it is checked in.
- **API use.** 17 `fetch` calls, every one to a V1 `/api/*` path (`/api/jobs/*`,
  `/api/events/*`, `/api/mobility/*`, `/api/deals`, `/api/h3-map`, `/api/targeting`,
  `/api/price-index`, `/api/price-index/facets`, ...). There are **no `/v1` calls**. It
  expects `{status: "ok", ...}` bodies, decimal prices and offset paging. The base URL comes
  from `js/config.js` (a `<meta name="api-base">`, defaulting to `:8765`).
- **Views.** Six modes in one page: Job Fair Map, Career Pathfinder, Job Finder, Events, Meal
  Deals and Price Index. Five are out of scope under ROADMAP §2: jobs, mobility, events, and
  deals until Phase 10. The Price Index mode is a list-only search over V1 facets (cuisine,
  dietary, calories, ZIP, radius), and V2 has none of those facets. Every map draws H3 hexes,
  and V2 has no H3 (ADR-0007 point 5).
- **Reusable.** The Leaflet map shell (`js/app.js` L24–39), the `config.js` base-URL pattern,
  the stale-response guard and `_esc` helper (`js/priceindex.js` L12–19, L411–460), the
  opacity-by-value polygon idea from `js/h3map.js` (as rectangles), the restaurant-card layout,
  and the dark theme as a visual starting point. That is roughly 10–15% of the code. The rest is
  V1-only.
- **Basemap.** The V1 site uses CARTO `dark_all` raster tiles with no key (`js/app.js` L35).
  CARTO's current terms ask for a free API key, capped at 5M tile requests a month and meant for
  non-commercial use. A commercial licence is a platform contract
  ([CARTO basemaps](https://www.carto.com/basemaps/apikey/),
  [terms](https://carto.com/legal/basemap-terms/)). Keeping CARTO therefore means a credential
  and a terms decision.

### F2. Data that a v1 site would serve

The only populated database is the owner's laptop `helios_laptop` (alembic head
`db40e9424cba`). It holds 1,766 published `initial` Menu pages (1,765 Organization-scoped),
67,305 `priced` observations and 18,139 sections. The database is 259 MB. The Pi was last
rebuilt on 2026-09-28 and holds no menus (README "Staging (Pi)").

- **Gold has never been refreshed there.** `gold.current_menu` and `gold.price_index` both have
  0 rows. Every endpoint except venues would serve empty answers today.
- **Observation dates.** The captures span 2026-09-30 22:37Z to 2026-10-02 08:47Z. But all 1,766
  pages carry one `observed_at`, 2026-10-02 08:41:41Z, because the fetch CLI stamps each run's
  single `now` (`apps/menu_pipeline/page_bronze.py:599`). So the dates are accurate to the day,
  not to the fetch. Under ROADMAP §2's 45-day target, the whole catalog goes stale on
  **2026-11-16** unless it is re-fetched. This ADR flags that; it does not change it
  (`apps/menu_pipeline/` belongs to P5-33).
- **Menu names.** `gold.current_menu` has no section names, and no item name when only an
  item's variants are priced (ROADMAP Phase 7 G-4; `MenuSectionResponse`/`MenuItemResponse`
  docstrings). Measured in Silver, **0 of 18,139 sections carry a section-level price, so every
  section would serve `name: null`**, and 2,181 of 61,214 priced items (3.6%) would serve
  `name: null`. A menu page without section headings is the main readability gap.
- **No source link.** The menu wire has `source_kind` but no URL for the page the price was read
  from, so a reader cannot check a price against its source. Trustworthiness is the North Star's
  first word. The URL already exists in Bronze (`source_endpoint_for_evidence`).
- **Organizations are 1:1 with venues.** Discovery mints one Organization per Establishment
  (ADR-0007 Amendment 1), so `organization=` returns one venue. A "this chain's other
  locations" view is not possible.

### F3. Area coverage: the measured low-sample share

Gold is empty, so `low_sample` cannot be read from `gold.price_index`. Instead, a read-only
query over Menu Silver reproduces the refresh's placement rule (ADR-0007 Amendment 1 §5;
`packages/helios_core/gold/price_index.py` `_place`, `identity/contracts.py`
`_VENUE_LOCATIONS_SQL`): families with a priced item or variant, placed at the scope's one
current venue, minus Organization families whose menu URL (the capture endpoint's
`canonical_uri`) more than one placed venue shares. The SQL is in the
[appendix](#appendix-the-low-sample-proxy). It runs in a `BEGIN READ ONLY` transaction.

- 981 families (981 distinct scope Subjects) have a priced item or variant. All 981 resolve to
  a single located venue.
- **505 (51%) are dropped as shared menus**, on 134 URLs. The five URLs with ten or more venues
  account for 142 of them (`pterrys.com` 47, `tacobell.com` 40, `chick-fil-a.com` 34,
  `juiceland.com` 27, `tacocabana.com` 25). This is by design: a chain menu is never fanned
  out. Those venues still have a menu page; they are only missing from the area index.
- **475 venues are placed.** The `has_menu` population, which is the 300-venue milestone
  (ROADMAP §2), is about 981.

| Grid | Cells with a venue | `low_sample` cells (< 5 venues) | Share low | Venues in cells with ≥ 5 | Largest cell |
|---|---:|---:|---:|---:|---:|
| 0.01° (built) | 267 | 256 | **95.9%** | 93 (19.6%) | 24 |
| 0.02° | 175 | 156 | 89.1% | 184 (38.7%) | 31 |
| 0.05° | 84 | 59 | 70.2% | 363 (76.4%) | 94 |
| 0.10° | 42 | 26 | 61.9% | 420 (88.4%) | 136 |
| citywide | 1 | 0 | 0% | 475 (100%) | 475 |

What the proxy leaves out: it doesn't run the selector (with one `initial` page per family,
every priced row is a current head); P5-33's R4 withdrawals, still awaiting owner approval, may
remove some pages; and Gold rows with no priced row (all-unpriced cells) aren't counted. Read
these as ±a few percent. The real figure is the first number to record once Gold is refreshed
(build step 1).

### F4. Deploy state

- `infra/docker-compose.yml` binds Postgres and the API to `127.0.0.1` (`5432`, `8000`).
  Nothing in the repo makes the Pi API reachable from the LAN, let alone publicly. ADR-0008
  Unit B (systemd unit, runbook) is not built (README Decisions).
- CORS: `cors_allow_origins` defaults to `["http://localhost:5173"]` and rejects `*`
  (`packages/helios_core/config.py`). The API has no rate limiting, and `ErrorCode` has no
  rate-limit code.
- Backups: on the Pi, custom-format `pg_dump` files with no rehearsed restore (README). On the
  laptop, a 2026-10-20 dump of `helios_laptop` was restored into a scratch database with
  identical row counts (P5-26, before the `db40e9424cba` upgrade).
- ROADMAP Phase 2 put "a public domain, TLS, rate limiting, hosted prod" in Phase 8, and §7 Q2
  ("is the API public, gated, rate-limited?") is open.

## Decision (proposed)

### 1. Frontend: a thin new client in the existing frontend repo

**Do not port the V1 app and do not rebuild it feature-for-feature.** Start a thin new client
in `First-Helios_Frontend`, keeping the frontend as a separate repo (ROADMAP §2):

- **Repo.** Preserve V1 on a `V1-Graveyard` branch there, the same convention as this repo.
  `main` restarts with the V2 client, and the rewrite lands through PRs on `main`.
- **Stack: no build step.** Static HTML, native ES modules (`<script type="module">`), one CSS
  file with colour tokens on `:root`, and Leaflet 1.9.4 **vendored** into the repo (its
  BSD-2-Clause licence file alongside) instead of loaded from unpkg, so the site loads no
  third-party script. No framework, bundler, npm or TypeScript. Four pages and one map don't
  need them, and every added tool is something the one reviewer has to review. h3-js is
  dropped. **Leaflet is the only library**, and it is listed for approval (Q1). It is already
  the V1 site's dependency, but it is new to V2.
- **Consuming `/v1`.** One `api.js` module holds the base URL (same-origin by default, see
  §4), a `getJSON(path, params)` that turns a non-2xx `{detail, code, trace_id}` into a typed
  error and shows `trace_id` to the user, a cursor iterator for `next_cursor`, a money
  formatter (`amount_minor` + `currency_code` → `$12.50`, never through a float) and an age
  formatter ("observed 19 days ago"). The client switches on `code`, never on `detail`
  (ADR-0008 §4).
- **Contract check.** The frontend repo gets one stdlib-Python script (no new dependency) that
  lists every `/v1` path and query parameter the client uses and fails if this repo's
  `apps/api/openapi_snapshot.json` lacks any of them. Breaking API changes already fail this
  repo's CI (`test/test_openapi_contract.py`); the script catches the other direction.
- **Reused from V1:** the Leaflet init, the `config.js` idea, `_esc` and the stale-response
  guard, the card layout, and the colours (turned into tokens). Nothing else is ported.

### 2. Minimal v1 page set

Hash routes (`#/`, `#/venues`, `#/venues/{id}`, `#/items/{item_id}`), so a static host needs no
rewrite rules.

| Page | What it shows | Backing endpoint | Gap |
|---|---|---|---|
| **Area / map** (`#/`) | The citywide headline (median, p25–p75, venue count, as-of), then a grid layer: each cell a rectangle shaded by median. A `low_sample` cell is drawn hatched with its venue count and **no median**. Clicking a cell opens the venue list filtered to it. | **New:** `GET /v1/price-index/cells` (point 3), plus the existing `GET /v1/price-index?lat=&lon=` for the selected cell's detail | The point endpoint returns one cell per request, so a map would need hundreds of calls. ADR-0007 Amendment 2 §1 already calls a listing "a later, additive endpoint". |
| **Venue list** (`#/venues?area=&has_menu=`) | Name, address, status; `has_menu=true` by default; "load more" through `next_cursor` | `GET /v1/venues` (`has_menu`, `area`) | `area` takes only a 0.01° key. A coarser grid needs an `area_kind` parameter (point 3). There is no name search; deferred (Q7). |
| **Venue menu** (`#/venues/{id}`) | Venue header, then menus → sections → items → variants/modifiers with prices, each with `observed_at` / age and `source_kind`; a "source page" link per menu | `GET /v1/venues/{id}`, `GET /v1/venues/{id}/menu` | Section names are all `null` (F2), and so are 3.6% of item names. There is no source URL (F2). |
| **Price trail** (`#/items/{item_id}`) | A small table, not a chart: each point's `known_from`, state, amount, `observed_at`, `source_kind` | `GET /v1/items/{item_id}/price-history` | None. With one capture, a trail has one point until the next fetch (ADR-0018 §C). A chart library is not needed for v1. |

Also a static **About / method** page: what the index is, venue-weighted medians, the 5-venue
rule, chains left out of the area index, the observation date, and how to read the trail. No
endpoint.

### 3. Area UX given thin coverage

At 0.01° the map is 96% low-sample cells, and four of five priced venues sit in a cell too thin
to be an index (F3). Serving that grid alone is honest, but nearly every cell would read "too few
venues".

**Proposed (Q3): citywide plus a 0.05° grid; keep the 0.01° rows.**

- Add two `area_kind` values to `gold.price_index`: `all` (one citywide row per category and
  currency, which ADR-0007 point 5 already foresaw as a non-geo `area_kind`) and
  `latlon_grid_0p05` (~5.5 km). The refresh computes all three kinds in the same rebuild,
  using the same placement and the same `MIN_VENUES = 5`. At 0.05°, 76% of placed venues are in
  a cell that clears the bar, against 20% at 0.01°. Shipping 0.10° instead (88%) is the
  alternative if 0.05° looks too sparse once real Gold rows exist.
- `gold/models.py` `AREA_KINDS` feeds a CHECK constraint, so this is a **Gold migration**
  (CLAUDE.md stop-and-ask). It only widens the CHECK; no rows are rewritten, and the table is
  rebuilt by the next refresh anyway.
- **`GET /v1/price-index/cells?area_kind=&category_kind=&currency=`**: every row of one
  `area_kind`, in `area_key` order, cursor-paginated per ADR-0008 (default 50, cap 200), each
  item in the existing `PriceIndexGroupResponse` shape plus the cell corner and size. It is a
  range scan on `uq_gold_price_index`'s leading `(area_kind, area_key)`, with a no-seq-scan
  test. A full 0.01° map is two pages at `limit=200`. A `bbox` filter is deferred until the
  cell count makes it worth adding.
- `GET /v1/price-index` and `GET /v1/venues` gain an optional `area_kind` (default
  `latlon_grid_0p01`, so nothing changes for current clients). A key like `30.25,-97.75` is
  valid at both 0.01° and 0.05°, so the key alone can't say which grid it means. For `all`, the
  venue filter matches every placed venue.
- **Display rule:** a `low_sample` row shows its venue count and "not enough venues for an
  index", never its median. The API still serves every honesty field, and the hiding is the
  client's choice. Chains left out of the index are counted on the About page.

Alternatives: 0.01° only (no migration; a map of "not enough data"), or citywide only (one
number, no map; it fails "area view"). See the table below.

### 4. Public deploy for v1

**Proposed (Q4): a small hosted ARM64 VPS is v1 prod. The Pi stays staging and is not on the
v1 critical path.**

- **Host.** One Hetzner Cloud CAX-class ARM64 VM (CAX11: 2 vCPU, 4 GB, 40 GB). Hetzner repriced
  on 2026-06-15, and third-party listings put CAX11 at about €5.99/month plus IPv4, though
  they disagree, so check the official page at decision time. ARM64 keeps parity with the Pi
  (ROADMAP §4.2). The 259 MB database and a read-only API with little traffic fit easily.
  Postgres runs in the same Compose stack as dev and staging. The roadmap's "prod Postgres on
  the host" is deferred to the full Phase 8 ADR (ADR-0002 Consequences).
- **Why not the Pi publicly.** Its data is stale (no menus). Exposing it means either a router
  port-forward, which publishes a residential IP, or a tunnel service (Cloudflare Tunnel,
  Tailscale Funnel), which is a new third-party account and token (stop-and-ask). And it shares
  its CPU with the monthly batch runs. The tunnel stays the zero-cost fallback (Q4b).
- **Same origin.** On the VPS, nginx serves the frontend's static files at `/` and proxies
  `/v1`, `/healthz`, `/readyz`, `/docs` and `/openapi.json` to the API container on
  `127.0.0.1:8000`. One origin means CORS never comes into play. `CORS_ALLOW_ORIGINS` is still
  set to `["https://<domain>"]`, so a misrouted cross-origin call fails closed.
- **TLS and domain.** The owner registers a domain (an owner action and account). Certificates
  come from Let's Encrypt via certbot (HTTP-01) with its renewal timer. HTTP redirects to HTTPS.
- **Rate limiting at nginx, not in the app.** `limit_req` per client IP: about 10 r/s with
  burst 20 on `/v1/*`, and about 2 r/s with burst 5 on `/v1/items/*/price-history`, the
  endpoint that isn't Gold-backed and costs a constant number of statements per family page
  (ADR-0018 notes). nginx returns 429 with an ADR-0008-shaped JSON body (`code:
  "rate_limited"`, `trace_id` from nginx's `$request_id`, also sent as `X-Request-ID`), which
  needs `rate_limited` added to `ErrorCode` (Q5). App-level limiting (e.g. `slowapi`) would be a
  new Python dependency and no better behind one proxy.
- **Host hardening (minimal).** SSH keys only, a firewall open on 22/80/443, unattended
  security upgrades, Postgres and the API bound to loopback as Compose already does, and a
  non-default `POSTGRES_PASSWORD` in a host-only `.env` (mode 0600) that never enters the repo or
  the image.
- **How data gets there.** The laptop stays the source of truth for v1 (ADR-0013 Amendment 8).
  A data release is: the owner-approved laptop steps, then `python -m apps.gold.refresh` on
  `helios_laptop`, then a custom-format `pg_dump`, `pg_restore` into a fresh database on the
  VPS, `alembic check`, a smoke `curl` set, and pointing the API at the new database (the
  previous one is kept for rollback). Every publish is therefore also a restore drill. Code
  deploys use the Pi's documented flow: a `git archive` of one merged commit plus
  `DEPLOYED_COMMIT`, built natively on the host. There is no registry yet.
- **Backups (minimal).** Each published dump is the backup of record: keep the last three on
  the VPS and copy each one off the laptop (the owner's external drive). Copy the laptop's
  `var/` replay bundles off-box once, since prices trace to them (ROADMAP §2). Prod writes
  nothing of its own, so a nightly prod `pg_dump` adds nothing until prod is the writer.

**Phase 8 items: v1 blocker or later**

| Phase 8 item (ROADMAP) | v1 | What v1 needs |
|---|---|---|
| Prod hosting ADR | **Blocker** | This ADR's §4 for v1. The full comparison (Fly/Railway/DO; host vs. Compose Postgres; multi-arch buildx) can wait. |
| Public vs. gated (§7 Q2) | **Blocker** | Public, read-only, no auth, rate-limited (Q4). |
| TLS + public domain | **Blocker** | Domain, Let's Encrypt, HTTPS redirect. |
| Rate limiting | **Blocker** | nginx `limit_req` plus the 429 body. |
| Secrets | **Blocker (minimal)** | Non-default DB password; host-only `.env`; SSH keys. Rotation and a secret store wait. |
| Backups | **Blocker (minimal)** | Dumps kept off-box, the bundles copied once, one restore proven. That restore is the first publish. Nightly object-storage automation waits. |
| Runbook | **Blocker (minimal)** | Deploy code, publish data, roll back, restart, read logs, renew TLS. |
| Observability (Prometheus, node-exporter, alerting) | Later | Compose healthchecks and `restart: unless-stopped` exist. An external uptime ping is optional (Q8). |
| Deploy pipeline (tagged releases, registry, 24 h green on staging) | Later | `git archive` deploy. |
| Phase 8 "done when" (wipe the Pi, restore in 30 min) | Later | |
| R116 (image healthcheck; CI amd64 vs. arm64) | Later | The host builds natively on arm64; the Compose healthcheck covers the API. |
| ADR-0008 Unit B (Pi systemd + runbook) | Later | Not on the v1 path. Useful once monthly runs move to the Pi. |

### 5. Ordered build plan to "a working v1 food price index website"

Each step is its own PR or owner action. Steps 2–4 and 7 are expensive-to-reverse paths or
`infra/` paths, so each is proposed and reviewed before code (CLAUDE.md).

1. **Owner data steps on the laptop, then measure.** The P5-33 laptop rescore (already awaiting
   approval), then `python -m apps.gold.refresh` on `helios_laptop`, both owner-authorized. Then
   record the real `low_sample` share at 0.01° next to F3's proxy.
   *Done when:* `gold.price_index` and `gold.current_menu` have rows, and the measured share and
   `has_menu` venue count are written in a review record.
2. **Gold names (ADR-0006 amendment + migration).** Add the ancestor section name, and the item
   name for variant-only items, to `gold.current_menu`, filled by the refresh from Menu.
   *Done when:* after a refresh, the menu endpoint serves a non-null section `name` wherever
   Silver has one, with tests and a regenerated OpenAPI snapshot.
3. **Area kinds and the cell list (ADR-0007 Amendment 3 + migration).** The `all` and
   `latlon_grid_0p05` rows (as Q3 decides), `GET /v1/price-index/cells`, and `area_kind` on
   `price-index` and `venues`.
   *Done when:* `curl /v1/price-index/cells?area_kind=latlon_grid_0p05` pages through every
   cell; the `all` row matches F3's venue count within the stated error; there are no-seq-scan
   tests; and the snapshot is regenerated.
4. **Small wire additions (ADR-0008 Amendment 4).** `source_url` on each `MenuResponse`, read
   through the provenance contract, and `rate_limited` in `ErrorCode`.
   *Done when:* the menu wire carries the page URL, and the snapshot is regenerated.
5. **Client skeleton (frontend repo).** The V1 archive branch, the new `main` tree, `api.js`,
   the map page against a local API serving a restore of `helios_laptop`, and the contract
   check.
   *Done when:* the map renders the citywide headline and every cell from the local API, with
   low-sample cells hatched, at 375 px and desktop widths, and the contract check passes.
6. **The other pages.** Venue list, venue menu, price trail, About.
   *Done when:* clicking a cell → its venues → a menu → a price trail works against real data;
   errors show their `trace_id`; every price shows its observation date.
7. **Prod host (owner provisioning + one `infra/` PR).** The owner creates the VM, the domain and
   SSH access. A PR adds a prod Compose overlay (no published ports beyond loopback), the nginx
   site config (static files, proxy, `limit_req`, 429 body) and `docs/runbooks/prod.md`.
   *Done when:* `https://<domain>/healthz` and `/readyz` answer over valid TLS, a burst gets a
   JSON 429, and the host comes back by itself after a reboot.
8. **First data publish = first restore drill.** Dump, restore, `alembic check`, smoke, switch.
   *Done when:* the public site serves the laptop's data; the row counts match the dump's
   source; `/v1/venues?has_menu=true` pages to at least 300 venues (the ROADMAP §2 milestone,
   measured through the API); and the off-box copies exist.

**v1 is done when** a stranger on a phone can open `https://<domain>`, see a citywide median
and an area map that says plainly where data is too thin, open the venues in an area, read a
venue's menu with section headings, prices, observation dates and a link to the source page,
open a price's trail, and get a JSON 429 instead of an outage when hammered. The data must be
restorable from an off-box dump.

**Explicitly not v1:** courses (ADR-0016 slice 1b waits on labels), name search, chain-wide
views, cross-Version price history, deals, auth, Prometheus, a registry, Pi Unit B, and meeting
the 45-day freshness target (F2). That last one is a Phase 6 deliverable. The site shows every
price's age instead (Q6).

## Alternatives considered

| Option | Pros | Cons / why not proposed |
|---|---|---|
| **Port the V1 app** (keep `index.html` and the modes, re-point the fetches) | Most code kept | About 85% of it is out-of-scope modes; the one price screen is built on V1 facets V2 lacks; H3 geometry, decimal money and offset paging all need rewriting anyway. Porting means deleting most of it and rewriting the rest. |
| **Rebuild with Vite + TypeScript + a framework** (Preact/Svelte; types from `openapi-typescript`) | Types generated from the snapshot, components, unit tests | A Node toolchain, a lockfile and npm supply-chain surface for four pages; more for one reviewer to check. Worth revisiting when the page count or interactivity grows (Q1). |
| **Frontend inside this monorepo** (`apps/web/`) | One PR can change API and client together; one CI | Contradicts ROADMAP §2 ("a separate repo"); mixes a static site into the Python image and gates. The contract check covers the cross-repo risk. |
| **0.01° grid only** | No migration; built today | 96% of cells low-sample; the map says "not enough data" almost everywhere. |
| **Citywide only** | One honest number; trivial | Not an area view; hides the geography the index exists to show. |
| **0.10° grid instead of 0.05°** | 88% of venues in index-grade cells | ~11 km cells average over very different neighbourhoods; the fallback if 0.05° looks too sparse once real Gold rows exist. |
| **Public on the Pi** (port-forward or tunnel) | €0; staging parity | Residential IP or a new third-party account; stale data; CPU shared with batch runs. Fallback Q4b. |
| **PaaS** (Fly.io, Railway) with managed Postgres | No server to patch | Higher cost, a platform-specific deploy model, managed-DB pricing; belongs in the full Phase 8 comparison. |
| **Static host (GitHub/Cloudflare Pages) + API on the VPS** | Free CDN for the static files | Two origins: CORS, and a second account. A small static site served by nginx needs no CDN. |
| **App-level rate limiting** (`slowapi`) | Per-route limits in Python | A new runtime dependency; behind one proxy it is no better than `limit_req`. |
| **Keep CARTO tiles** | The V1 look | Now needs an API key (a credential) and is meant for non-commercial use; commercial means a platform licence. See Q2. |

## Consequences

**Easier**

- The site needs no frontend build, no Node and no third-party script origin. One reviewer can
  read every file.
- The API changes are additive. Every ADR-0008 convention holds, and existing clients see no
  change: `area_kind` defaults to today's grid.
- Every data publish is a restore, so the backup is exercised every time, not assumed.
- The map is honest about thin coverage without hiding it. The honesty fields stay on the wire.

**Harder / accepted costs**

- Two Gold migrations (names; `area_kind` CHECK) and their reviews before the site is useful.
- A hosted server to keep patched, a monthly bill, a domain and SSH keys: the first things in
  this project that cost money or carry public credentials.
- The laptop stays the writer, and prod is a dump of it. A laptop loss before the off-box copies
  exist loses the bundles. Moving the writer (to the Pi or prod) is a later decision.
- A no-build client has no type checking; the contract check is the only guard on the API
  shape. If the client grows, this is the first decision to revisit.
- Chain locations appear in venue lists and menus but not in area medians. The About page has
  to explain this, or the map reads as an undercount.
- The 45-day freshness target lapses on 2026-11-16 without a re-fetch; until Phase 6 runs, the
  site shows ageing prices labelled as such.

## Owner questions

Each has a recommendation. Nothing is built until these are answered.

- **Q1. Frontend approach and its one dependency.** A thin new no-build client in
  `First-Helios_Frontend` (V1 kept on `V1-Graveyard` there), with Leaflet 1.9.4 vendored as the
  only library (recommended)? Or Vite + TypeScript + a framework (adds Node, npm and a
  lockfile), or a new repo? The frontend repo is MPL-2.0 and this one is BSL 1.1. Keep MPL for
  the new client?
- **Q2. Basemap tiles.** Options: (a) OpenStreetMap's standard tiles, which need no key but come
  under the OSMF tile usage policy (attribution, a valid Referer, no heavy use: fine for a small
  site, revisit with traffic); (b) CARTO with its free key (a credential; non-commercial
  terms); (c) self-hosted vector tiles (Protomaps PMTiles: no third party at runtime, but a
  tile extract and a second JS library). Recommended: (a) for v1, (c) if traffic or terms
  require it. Is v1 a non-commercial project? That settles (b).
- **Q3. Area grain.** Citywide `all` plus a 0.05° grid, keeping the 0.01° rows, as one Gold
  `area_kind` migration plus `GET /v1/price-index/cells` (recommended)? Or 0.10° instead of
  0.05°? Or 0.01° only (no migration)? And confirm that a `low_sample` cell shows its venue
  count but no median on the map (the API still serves it).
- **Q4. Where v1 runs.** (a) A Hetzner CAX11-class ARM64 VM, about €6/month plus IPv4 (check the
  price), with nginx, certbot and Compose (recommended); or (b) the Pi behind a Cloudflare
  Tunnel (€0, a new account and token, data moved there first); or (c) a PaaS. Also: the API is
  public, read-only, unauthenticated and rate-limited, which answers ROADMAP §7 Q2. Agreed?
- **Q5. The 429 contract.** nginx returns `429 {detail, code: "rate_limited", trace_id}` at about
  10 r/s per IP (burst 20), and about 2 r/s (burst 5) on price history. `rate_limited` is added
  to `ErrorCode` (ADR-0008 Amendment 4). Agreed, and are the numbers acceptable to start?
- **Q6. Blockers that are data, not code.** (a) Is F2's 45-day lapse on 2026-11-16 acceptable
  for launch, given every price shows its age? Or must a re-fetch run first (Phase 6 work)?
  (b) Pi gate 1a's 2026-09-28 sample (Pi data, the same Overture release the laptop seeded
  from) found 4 of 100 wrong geocodes and 6 of 100 venues with a confirmed duplicate. README
  Gates shows the corrections not yet applied on the Pi, and no record says they were applied
  to `helios_laptop`. Launch with them unapplied and disclosed, or apply them to
  `helios_laptop` before the first publish (an owner-run write)? (c) Approve build step 1's laptop writes (the P5-33 rescore, then a Gold refresh)?
- **Q7. Venue search.** Name search on `/v1/venues` is left out of v1 (navigation is map → area →
  venues). Add it in v1 (a `q` prefix filter; a trigram index would need `pg_trgm`, an
  extension and so a stop-and-ask), or later (recommended)?
- **Q8. Uptime monitoring.** None in v1 beyond Compose restart (recommended), or a free external
  uptime ping (a new account)?
- **Q9. Order.** Build steps 2–4 (API and Gold) before 5–6 (client), as written? Or the client
  first against today's API, accepting null section names and the per-point map lookup until
  2–4 land?

## Owner decision

**Answered by the owner on 2026-10-21**, in session P8-0:

1. **Q1 frontend:** a thin no-build client in `First-Helios_Frontend`. V1 is kept on a
   `V1-Graveyard` branch there. Leaflet 1.9.4, vendored, is approved as the only library. The
   repo stays MPL-2.0.
2. **Q2 tiles:** OpenStreetMap standard tiles with attribution. Revisit if traffic grows.
3. **Q3 area grain:** a citywide `all` row plus a 0.05° grid, keeping the 0.01° rows. A
   `low_sample` cell shows its venue count and no median. The Gold `area_kind` migration and
   `GET /v1/price-index/cells` still go through their own reviewed unit (ADR-0007
   Amendment 3); this answer approves the direction, not unseen migration SQL.
4. **Q4 hosting: deferred.** v1 runs locally first. The owner expects ARM64 or a cloud
   provider later, so the §4 VPS proposal stays on the table as a proposal only. The same
   goes for the decisions that only matter in public: **Q5** (rate limits and
   `rate_limited`), **Q6a** (launching with stale prices), **Q6b** (location corrections
   before a public launch) and **Q8** (uptime monitoring). All are deferred to the hosting
   decision.
5. **Q6c laptop writes: approved.** The next session may take a fresh `pg_dump` of
   `helios_laptop`, run the pending P5-33 rescore (R4 withdrawals), then run
   `python -m apps.gold.refresh` there, and record the real `low_sample` share (build step 1).
6. **Q7 venue search:** later. Not in v1.
7. **Q9 order:** API fixes first: build steps 2–4 before the client pages (5–6).

**What this changes in §5.** The plan splits into two milestones:

- **Local v1 (now): steps 1–6.** It is done when the step-6 click path (map → cell →
  venues → menu with section headings, source link and observation dates → price trail)
  works in a browser against the API running locally over `helios_laptop`, with the
  contract check passing.
- **Public v1 (later): steps 7–8.** They follow the hosting decision. Step 4 ships only
  `source_url`; `rate_limited` moves to step 7 with the rest of Q5.

## Appendix: the low-sample proxy

Read-only, against `helios_laptop` on 2026-10-21 (`BEGIN READ ONLY`; the session was also set
`default_transaction_read_only`). It mirrors `price_index._place` and `_VENUE_LOCATIONS_SQL`
with `now()` as the instant:

```sql
with fam as (  -- (scope subject, source record) families with a priced item/variant
  select p.subject_id, p.subject_kind, p.source_record_id, min(se.canonical_uri) as url
  from menu.menu_page p
  join menu.price_observation o on o.page_id = p.id
  join bronze.source_record_version v on v.id = p.source_record_version_id
  join bronze.capture c on c.id = v.capture_id
  join bronze.source_endpoint se on se.id = c.source_endpoint_id
  where o.price_state = 'priced' and o.modifier_id is null
    and (o.item_id is not null or o.variant_id is not null)
  group by 1, 2, 3
),
live as (  -- as _VENUE_LOCATIONS_SQL
  select f.subject_id, e.subject_id as est, p.latitude, p.longitude
  from (select distinct subject_id from fam) f
  join identity.establishment e on f.subject_id in (e.subject_id, e.organization_subject_id)
  join identity.subject_currentness ec on ec.subject_id = e.subject_id and ec.is_current
  join identity.subject_currentness oc on oc.subject_id = e.organization_subject_id and oc.is_current
  join identity.place p on p.subject_id = e.place_subject_id
  join identity.subject_currentness pc on pc.subject_id = p.subject_id and pc.is_current
  where e.operating_status <> 'closed' and e.valid_from <= now()
    and (e.valid_to is null or e.valid_to > now())
),
loc as (
  select subject_id, min(est) as est, min(latitude) as lat, min(longitude) as lon
  from live group by subject_id having count(*) = 1 and min(latitude) is not null
),
placed as (select f.*, l.est, l.lat, l.lon from fam f join loc l using (subject_id)),
url_venues as (
  select url, count(distinct est) as n from placed where subject_kind = 'organization' group by url
),
kept as (  -- shared menu URLs are left out, never fanned out
  select pl.* from placed pl left join url_venues u on u.url = pl.url
  where pl.subject_kind <> 'organization' or u.n = 1
),
venues as (select distinct est, lat, lon from kept),
grids(step) as (values (0.01::numeric), (0.02), (0.05), (0.10)),
cells as (
  select g.step, floor(v.lat / g.step) * g.step as clat, floor(v.lon / g.step) * g.step as clon,
         count(*) as n
  from venues v cross join grids g group by 1, 2, 3
)
select step, count(*) as cells, sum((n < 5)::int) as low_sample_cells,
       sum(case when n >= 5 then n else 0 end) as venues_in_ok_cells, max(n) as max_cell
from cells group by step order by step;
```

The proxy counts venues per cell. The refresh's `venue_count` is the number of venues with a
priced row in the group, which with `category_kind = 'all'` and USD only is the same count.

## References

- `apps/api/openapi_snapshot.json`, `apps/api/schemas.py` (`MenuSectionResponse`,
  `MenuItemResponse`, `MenuPriceResponse`, `ErrorCode`), `apps/api/routes/`
- `packages/helios_core/gold/price_index.py` (`_place`, `grid_cell`, `MIN_VENUES`),
  `gold/models.py` (`AREA_KINDS`), `identity/contracts.py` (`current_venue_locations`),
  `provenance/contracts.py` (`source_endpoint_for_evidence`), `config.py` (`cors_allow_origins`)
- `infra/docker-compose.yml` (loopback bindings), `infra/Dockerfile`
- ROADMAP §2, §4.2, Phases 2, 6, 7, 8, §7 Q2; README "Staging (Pi)", Decisions
- `First-Helios_Frontend` at `909e6e0`: `index.html`, `js/config.js`, `js/app.js`,
  `js/h3map.js`, `js/priceindex.js`, `README.md`
- Hetzner 2026 repricing: [Northflank](https://northflank.com/blog/hetzner-cloud-server-price-increases),
  [privatedevops](https://privatedevops.com/news/hetzner-june-2026-cloud-price-increase-what-to-do)
  (third-party; check Hetzner's own price list)
- CARTO basemaps: [API key page](https://www.carto.com/basemaps/apikey/),
  [terms](https://carto.com/legal/basemap-terms/)
