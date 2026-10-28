# Menu browsing audit — 2026-10-27

Status: baseline recorded before implementation. The owner subsequently approved
the first slice; see [its implementation/measurement record](./2026-10-27-menu-cache-first-slice.md).
Decision: [ADR-0023](../adr/0023-menu-browsing-and-http-validation.md).
Cross-session boundary: [integration proposal](../plans/2026-10-27-menu-browsing-integration.md).

## Verified repositories and instructions

- Backend: `https://github.com/First-Helios/First-Helios`, default `main`,
  `633ac617b5e2e63b6fa64846a62ff87cfaa5a63f`. The original checkout's remote
  still spells the old owner `4Fortune8`; GitHub resolves the current organization.
- Frontend: `https://github.com/4Fortune8/First-Helios_Frontend`, default `main`,
  `1c9560f1aaaf35b61f26aae829e72a67441a7a0c`. PR #8, the page-joining change,
  is merged. The original frontend checkout is clean on `p8-20-one-menu`,
  `f37c670`, and its local `main` is older. Neither checkout was switched.
- Working copies: audit documents started on backend branch `docs/menu-browsing-audit`
  in `var/menu-browsing/backend`; fresh source clones for baseline execution are
  `/tmp/helios-menu-browsing/{backend,frontend}` at the commits above.
  The implementation branch is now `feat/menu-cache-validation`, with frontend
  `feat/menu-cache` in `var/menu-browsing/frontend`.
- Backend instructions: `CLAUDE.md`, `CONTRIBUTING.md`, ADR-0006/0008/0018/0019/
  0020/0022. No `AGENTS.md` found in either current source tree or ancestor chain.
  The frontend README supplies the frontend rules. No frontend CLAUDE.md, package
  manifest, build pipeline or test runner exists on this commit.
- Architecture: static HTML/CSS, native ES modules, hash router, vendored Leaflet
  1.9.4, Python standard-library proxy. Preserve these. No framework, build step,
  service worker, browser persistence, or runtime dependency is proposed.
- Deployment documentation is stale: backend README says local-only and frontend
  PRs unmerged; GitHub shows the merges. Claude records describe a Pi/tunnel site,
  but external probes from this environment returned HTTP 403 for `/` and
  `/healthz`. That does not establish its current public availability or deployed
  commit. No deployment was changed. The owner is updating Pi data during this audit.

## Trace and findings

| Flow | Current implementation | Finding |
|---|---|---|
| Initial map | `map.js` awaits citywide `priceIndexCells` before mounting Leaflet | One small request, no full menu catalog; its failure prevents the usable map from mounting |
| Area change | Summary and all boundary venue pages in `Promise.all`; item page beside them | Venue pages use `limit=200` and exhaust the cursor before showing results; one failed venue page discards already fetched pages and the summary |
| Area item search | First page, then explicit load more; boundary/currency/q/limit resent | Correct cursor retry and supersession guard; previous search rows are cleared immediately; stale load-more finalizers can reset newer controls |
| Venues list | 50 summaries, explicit load more; optional index summary awaited alongside list | No menu prefetch; index failure blocks useful venue results; loaded pages/scroll lost on return |
| Restaurant | `Promise.all(venue, venueMenu)` | Fetches only selected details, but a menu failure hides a successful header; no in-place refresh/retry or retained-data state |
| Price trail | History plus venue plus entire current menu for label lookup | Redownloads menu and header just fetched on the previous page; optional names delay the useful history |
| Return navigation | Abort old route, remount and refetch | Boundary/search survive in hash; pagination depth, viewport and scroll do not; no browser back restoration |
| Cancellation | Route AbortController and `ctx.isCurrent()`; per-area/item controllers | Rapid restaurant switching passed; area requests also use identity guards. Preserve these guarantees while sharing requests |
| Caching | Plain fetch; no client response cache or single-flight; API has no HTTP validators or response store | Repeats whole payloads. Proxy does not forward conditional request headers. Discovery disk caches belong to ingestion and are unsuitable for API reuse |
| Price freshness | `formatAge` prefers response `age_seconds` | Reusing a payload would freeze the displayed age unless it is calculated from `observed_at`; client cache age must be separately labelled |
| Menus | API one menu per page, joined under one frontend heading, source link at each boundary | No frontend name merging. Existing source boundaries must remain visible; a page has no stable public ID/title/context of its own |
| Price presentation | Context on individual prices; variants and modifiers separate; modifiers use plus prefix | Synthetic lunch/dinner same-name dishes, full variant prices, add-ons and missing prices render distinctly; do not add name-based resolution |
| Quality | No collection-quality fields; UI says “One menu · current as of …” | `as_of` is a Gold refresh instant, not completeness or observation time. Missing quality should read “Collection coverage unknown”; empty menu gives no reason |
| Sources | Source-page links and per-price observation dates exist | Official restaurant link absent from venue wire model; normal menu UI exposes extraction labels such as LLM; move technical details behind optional disclosure |

Pagination is keyset-based, and cursors do not carry filters. Repeating the same
filters on every page is already implemented. No coherent multi-page publication
snapshot is guaranteed: venue pages have no revision; other pages' minimum `as_of`
is not a content revision. A correction or deletion can leave that minimum
unchanged. An updated first page must restart dependent pagination rather than
append cached pages from a previous fetch.

## Browser baseline

Real data, read-only `helios_laptop`, API from backend `633ac61` on localhost
18000, frontend `1c9560f` on 18080. API process has PostgreSQL
`default_transaction_read_only=on`. No Pi requests, writes, extraction or crawl.
Playwright Chromium; desktop 1280×900, mobile 390×844. OSM tiles aborted so they do
not enter API measurements. Response bodies were uncompressed on this local path.
These are single-run local observations, not public-site latency benchmarks.

| Scenario | API requests | Response body bytes | Content ready (ms) |
|---|---:|---:|---:|
| Cold map | 1 | 560 | 108 |
| First 50 restaurants with menu | 1 | 14,193 | 89 |
| Next 50 | 1 | 14,202 | not timed |
| Open Brack's Backyard (18) | 2 | 10,444 | 30 |
| Open its first price trail | 3 | 11,746 | 80 |
| Return to that restaurant | 2 | 10,444 | 26 |
| Return to restaurant list | 1 | 14,193 | 77 |
| Area, 382 venues | 5 | 131,750 | 208 |
| Search that area's items for taco | 1 | 24,507 | not timed |

The area was `30.20,-97.80;30.35,-97.80;30.35,-97.65;30.20,-97.65`.
Its five requests include citywide, area summary, first 50 items, and two venue
pages. All 382 venue cards are mounted, with no user paging. Returning to the
list after loading 100 gives only 50. The menu → trail → menu segment uses seven
requests and 32,634 body bytes, of which the trail itself is one 1,302-byte body;
the other 31,332 bytes repeat the restaurant and menu three times.

Other browser observations:

- An earlier restaurant menu delayed 600 ms did not overwrite the next selection
  (Vespa Rossa Tx). Four requests started; one was aborted.
- Injected menu HTTP 503 after an earlier successful visit removed the header and
  prices; only the error and map link remained. A user cannot retry the same hash
  by navigating to it again, because it does not change the route.
- Actual small-screen restaurant and synthetic multiple-page menu had no horizontal
  overflow. There were no uncaught application errors in the main baseline.
- Synthetic wire-compatible pages separately exercised two identical dish names
  at lunch/dinner prices, full-priced large variants, +$2 add-ons, missing prices,
  two source links, and an empty `menus` array. All existing distinctions rendered;
  collection coverage was not represented as unknown. These fixtures are not
  evidence of production collection capabilities or extraction accuracy.
- Real venue 21459 still returned only `/blank`, one source page. Venue 21183
  returned `menus: []`. Merged collection support does not imply recollected data.
- Representative API responses had neither ETag nor Cache-Control. The current
  frontend proxy forwards Accept only, so adding API validators alone is insufficient.

Reproduction and raw evidence are in `var/menu-browsing/evidence/` in the original
backend checkout (`baseline.json`, `baseline-fixtures.json`, screenshots,
`audit_browser.py`, `menu_fixture_browser.py`). The browser driver requires the
existing Playwright development environment; it adds no application dependency.
The driver reads the local API and injects failures/fixtures only in its browser.

## First slice and acceptance

See ADR-0023 for the concrete bounded slice. Start with menu → price trail → return:
bounded memory cache, shared in-flight reads, progressive header/menu loading,
refresh failure retention, explicit retry, source dates and coverage unknown,
and HTTP validation. No new wire body fields or ingestion edits.

Targets, not measured improvements: within the freshness window, that seven-request
segment should become three requests total (two initial details plus one history),
11,746 bytes for the same baseline bodies, saving four requests and 20,888 bytes.
An unchanged HTTP validation should transfer no JSON body. Cold first visits still
require their detail requests. API validators initially save transfer rather than
database reads; measure before proposing a server resident response cache.

The next slice addresses progressive/demand-paged area venues, independent summary
failures, list page restoration, map viewport/scroll and changed-filter behavior.
Do not claim those are fixed by the first slice.

Required implementation verification: contract check, backend `make ci`, targeted
HTTP validation/cache tests, and browser scenarios for rapid selection, repeated
visits, aborting one subscriber while another remains, aged cache, manual refresh,
503 with retained data, empty after withdrawal, changed/corrected prices, distinct
contexts and options, and mobile focus/retry. The following slice adds pagination
and filter-change measurements. Strict DB tests must use a separately provisioned
disposable `*_test` DB; application data stays read-only.

Audit-branch checks completed: frontend contract check passed for all eight
endpoints; backend `make ci` passed (lockfile, all pre-commit hooks, mypy over 208
files, 842 tests passed, 962 skipped, one warning). No database acceptance is
claimed: the optional DB tests skipped because this check run had no disposable
DB configured. Browser evidence above is a separate read-only application-data
baseline. No application source changed and no improvements are claimed yet.
