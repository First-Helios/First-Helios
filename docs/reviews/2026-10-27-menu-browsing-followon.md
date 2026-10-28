# Progressive menu browsing and return navigation — 2026-10-27

Authorization: the owner explicitly authorized the remaining application work,
including commits/pushes on claimed branches, while preserving the first slice.
[ADR-0023](../adr/0023-menu-browsing-and-http-validation.md) and the
[integration boundary](../plans/2026-10-27-menu-browsing-integration.md) apply.

## Repository state and ownership

Verified remote main remained backend `633ac61`, frontend `1c9560f` at continuation.
The original working directories were left unchanged. First-slice staged changes
were preserved in backend commit `e1b76dc` on `feat/menu-cache-validation`, frontend
`3031434` on `feat/menu-cache`; both branches were claimed by creating their
remote branches. Backend origin still redirects its old `4Fortune8` spelling to
`First-Helios/First-Helios`. No deployment or data-update process was invoked.

The extraction session's Claude records and `.claude/worktrees/p8-21-page-structure`
were checked: active changes are PageStructure/page-template parsing and tests.
No new quality/publication API contract was supplied. This session changes no
ingestion, discovery, capture, parsing, validation, source identities, Gold
publishing, models, migrations, infrastructure, credentials or persisted quality.
Backend follow-on changes are documentation; the API body remains compatible.

## Application changes

- The map mounts immediately. Citywide summary, area index, area venue pages and
  priced-item pages load/retry independently; a failed summary never hides a
  useful map or list. Successful prior summary data survives a temporary failure.
- Both venue and item lists request 50 rows initially. Each explicit Load more
  requests one further page, preserves the cursor/rows after failure, prevents
  duplicate clicks and moves keyboard focus to new results. States distinguish
  initial loading, request failure, no matching published results, loaded results
  with more available, updating, and retained results after failed refresh.
  Loaded counts do not claim collection coverage or total restaurant counts.
- Native `pagination.js` and `paged-list.js` share cursor/validation/retry behavior
  across map and venue-list views. Filter/boundary/search changes cancel departed
  subscribers; callbacks/finalizers cannot mutate replacement controls. Repeating
  an unchanged search sends no additional request. The unused exhaustive `pages()`
  helper now rejects cursor cycles before yielding a repeated page; no browsing
  page calls it to enumerate a catalog.
- Return navigation restores opened pages, filters/search/boundary, map viewport,
  scroll and the originating link's focus. Breadcrumbs/main navigation retain the
  prior browsing route. Router state is memory-only: 20 routes, 64 KiB total,
  ten-minute retention, storing small metadata and cache-key/cursor/version
  references. It does not copy responses or retain detached pages. Reload keeps
  shareable hash parameters, not in-memory pagination depth.
- Response-cache eviction/expiry invalidates saved chains and removes expired
  active rows. Each already opened page revalidates while visible and on
  focus/online return. A changed page immediately drops its dependent tail;
  late children started against an older parent cannot reattach. Every newly
  opened dependent page validates against the server, including a previously
  cached URL. Cache generations are client metadata, never publication revisions.
- Older APIs/proxies without ETags remain usable: semantic equality ignores only
  request-relative ages and history's computation clock, preserving unchanged
  pages while still detecting corrections. This compares existing data without
  retaining another serialized payload. With ETags, unchanged validation remains
  bodyless 304. Existing first-slice request sharing/size/retention bounds remain.
- About uses the citywide summary only, removing five venue-page downloads in
  the measured data. It no longer infers why all other venues are outside the
  index from an aggregate count.
- Mobile search now shrinks at 320 px, cards wrap long names, and load/retry
  buttons remain at least 44 px high. Leaflet's existing `zoomAnimation: false`
  option prevents its 1.9.4 zoom-completion timer accessing a destroyed map after
  a rapid route change. Pan/draw/zoom remain available; vendored code is unchanged.

Restaurant/menu/history behavior, source links and observations, opaque node
identities, variants/modifiers and current price contexts from the first slice
are preserved. No dish-name deduplication or completeness inference was added.

## Measured comparison

Cold application caches, same read-only `helios_laptop` and localhost API/proxy,
Chromium 1280×900. Baseline static files were archived from frontend `3031434` on
18081; current client ran on 18080; the same backend on 18000 used PostgreSQL
read-only transactions plus two-second lock/fifteen-second statement timeouts.
OSM tile requests were excluded. No Pi requests or application-data writes.

| Scenario | Before | After |
|---|---:|---:|
| About API requests | 6 | 1 |
| About response-body bytes | 254,103 | 560 |
| About HTTP request+response bytes, including headers | 258,144 | 1,241 |
| Initial area API requests | 5 | 4 |
| Initial area response-body bytes | 131,750 | 38,712 |
| Initial area HTTP request+response bytes, including headers | 135,143 | 41,433 |
| Initially rendered area venues | 382 | 50 |
| Area item rows after returning from a restaurant, previously loaded 100 | 50 | 100 |
| Venue-list rows after returning, previously loaded 100 | 50 | 100 |
| Extra API requests on fresh return to either browsing view | 0 (depth lost) | 0 (depth restored) |
| Changed item-name search | 1 request / 24,507 body bytes | 1 / 24,507 |
| Repeating the same search | 0 requests | 0 requests |

About body transfer fell 99.8%; initial area body transfer fell 70.6%. The area
still has more matching venues; the smaller initial response is explicit demand
paging, not a claim that only 50 exist. Full HTTP bytes above include HTTP message
headers and bodies, excluding transport framing/TLS, unlike the body-only figures.

Single-run local time until area summary/items/venues were useful was 1,220 →
244 ms; return to first visible area items was 193 → 45 ms. These are illustrative
local observations under concurrent laptop work, not a public-site benchmark or
a cold-database latency guarantee. API response validation still reads SQL data.

Scroll before/after returning: baseline area 6,372 → 216 px, current 6,604 →
6,604 px; baseline venue list 2,445 → 1,667 px, current 2,465 → 2,465 px. Browser
fixtures separately verified exact viewport restoration and search/filter state.
The first-slice menu → trail → menu regression still passes at three requests.

Reproduce using frontend `tests/measure_browsing.py` against the baseline and
current static clients with separate `--phase before/after --output <directory>`.
Raw JSON, request/transfer records, screenshots and logs are retained locally in
`var/menu-browsing/evidence/` in the original backend checkout. Synthetic acceptance
fixtures are identified separately and are not collection-quality measurements.

## Verification

- Native client unit tests: 24 passed, covering query separation, deduplication,
  cancellation, expiry/eviction/size bounds, legacy/no-ETag compatibility, cursor
  retry/cycle rejection, changed head/middle pages, old-parent late children,
  oversized-page updates/expiry, bounded metadata and fresh restoration.
- Frontend proxy test and eight-endpoint contract check: passed.
- Browser first-slice regression: passed (restaurant/menu/history, source links,
  multiple contexts/options, missing prices, refresh errors, withdrawals, mobile).
- Browser browsing acceptance covers independent/failed summaries, first/later
  page errors and retry, duplicate clicks, search/boundary/finalizer races,
  repeated queries, filter/search/depth/scroll/viewport restoration, confirmed
  empty and corrected updates, failed-refresh retention, hidden-page expiry,
  expired restoration, and 390/320 px controls/overflow: **passed**, no uncaught
  page errors. The first-slice browser regression also passed after the final
  application changes.
- Strict API tests on newly created `helios_browsing_followon_20261027_test`:
  **299 passed**, no skips, one existing TestClient deprecation warning.
  `alembic check`: no new upgrade operations. Application databases remain read-only.
- Full backend `make ci`: **passed**, lockfile, all pre-commit hooks, mypy,
  **856 passed / 962 skipped**, one existing warning. Optional skipped DB tests
  are not full strict-suite acceptance; the separate strict API run supplies
  API database acceptance. No full local strict-suite or Docker claim is made.
- Native syntax checks passed for every application JS module. The dedicated
  test database was removed after validation; application data was not mutated.

## Remaining contract dependencies and practical limits

No official restaurant URL, stable public page ID/label, assessed collection
coverage, last collection-attempt outcome or safe cheap publication revision is
available/agreed in the current API. Those remain the documented integration
follow-ups; the frontend keeps coverage unknown and renders only supplied price
contexts. Reading the other session's instructions is not an acknowledgment of
the proposed future metadata semantics.

There is no atomic multi-page snapshot guarantee, push invalidation or resident
API response store. Opened pages validate individually; a correction can reset
later pages, and cache pressure/expiry can require starting again. The response
cache remains 100 entries/8 MiB/ten minutes. Narrowing an area/filter helps retain
large useful chains; an oversized response is one active page, never a second
navigation cache. Visibility throttling or network failure may delay validation;
eligible stale data stays labelled, and hard expiry removes old prices.

No publishing, deployment, main-branch update or ingestion/data-quality change is
part of this delivery. Commits/pushes are restricted to the two claimed branches.
