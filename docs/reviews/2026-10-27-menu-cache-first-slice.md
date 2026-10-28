# Menu loading/cache first slice — 2026-10-27

Approved scope: [ADR-0023](../adr/0023-menu-browsing-and-http-validation.md).
Baseline: [verified audit](./2026-10-27-menu-browsing-audit.md).
Contract boundary: [integration note](../plans/2026-10-27-menu-browsing-integration.md).

## Implemented

Frontend branch `feat/menu-cache` in `var/menu-browsing/frontend`, based on
frontend `main@1c9560f`. Backend branch `feat/menu-cache-validation` in
`var/menu-browsing/backend`, based on backend `main@633ac61`. Original checkouts
remain on their existing branches. No commit, push, deployment, ingestion change,
application-data write, model/migration change or new dependency/service.

- Memory-only client response reuse: canonical versioned URL keys, 30-second
  freshness, ten-minute hard expiry, LRU bounds of 100 entries/8 MiB serialized
  data. Identical concurrent requests share one transport. Each subscriber can
  cancel independently; the final departure cancels transport. Abandoned late
  responses cannot overwrite a replacement request. Fifteen-second timeout.
- Existing paged callers retain their explicit await/retry behavior and gain
  fresh reuse. Active restaurant/menu/history views render eligible stale data
  while updating, check every 30 seconds when visible, revalidate on focus/online
  return, and have stable explicit refresh controls. Hidden views do not poll.
  Timers/listeners/subscribers are released on route departure.
- Restaurant details and menu load independently. A menu failure retains a
  successful header, and a transient refresh failure retains eligible prices
  with an inline warning. Empty successful publication removes old prices;
  missing resources invalidate old entries. Ten-minute hard expiry removes
  retained prices after repeated failures. Failures never become empty success.
- Price history renders independently of optional restaurant/item names, reusing
  cached context when available. Dates on prices remain source observation dates;
  client checked time is separate. Cached server `age_seconds` cannot freeze
  observation age. Unchanged revalidation preserves menu DOM and keyboard focus.
- Source-page boundaries/links, opaque node identities, price contexts, full
  variants and additional-charge modifiers remain distinct. No name merging or
  price conflict heuristic. Coverage is explicitly unknown with today's API.
  Extraction-kind labels are behind optional disclosure in ordinary menu views.
- Backend HTTP validation reads current data before hashing every stable response
  field and the path/query. Only request-relative ages and history's computation
  timestamp are excluded. Weak ETags, conditional list/wildcard handling,
  bodyless 304s, `public, no-cache` success headers, `no-store` errors, CORS-visible
  validators and preserved request tracing. Proxy forwards conditional/cache
  headers and does not manufacture a zero Content-Length on a 304.

There is no resident API response store: validators save transfer and client
parsing, not SQL reads or route serialization. No safe cheap publication token
covering Gold, live provenance and identity/quality updates exists yet. This
avoids adding a cache invalidation hook in another session's publishing code.

## Measured browser comparison

Same restaurant (18), its first priced node, same local read-only database and
representative area as the baseline. Response bodies and transferred JSON bytes
match because the local proxy path does not compress them. Chromium desktop
1280×900/mobile 390×844; OSM tiles excluded. Cold/fresh application caches only;
single-run local timings are illustrative, not public performance benchmarks.

| Scenario | Before requests / bytes | After requests / bytes |
|---|---:|---:|
| First restaurant/menu | 2 / 10,444 | 2 / 10,444 |
| Its price trail | 3 / 11,746 | 1 / 1,302 |
| Return to restaurant/menu | 2 / 10,444 | 0 / 0 |
| Combined menu → trail → menu | **7 / 32,634** | **3 / 11,746** |
| Return to venue list | 1 / 14,193 | 0 / 0 |
| Area load after earlier map visit | 5 / 131,750 | 4 / 131,190 |
| Area item search, taco | 1 / 24,507 | 1 / 24,507 |
| Unchanged explicit menu check | 2xx full menu | **1 / 0 (304)** |

The combined flow saves four requests (57%) and 20,888 bytes (64%). Fresh menu
return was 26 → 7 ms; fresh venue-list return 77 → 7 ms. First restaurant/menu
was 30 → 33 ms, history 80 → 80 ms, cold map 108 → 118 ms, area 208 → 206 ms.
No cold-load latency improvement is claimed. The area saving is reuse of the
560-byte citywide response, not a pagination improvement.

Raw `baseline.json`, `after.json`, fixture results, desktop/mobile screenshots
and check logs are in the original checkout's `var/menu-browsing/evidence/`.
Reproduction: frontend `tests/browser_check.py --output <evidence-directory>`
with the local dev proxy/API on 18080/18000. The API process uses PostgreSQL
read-only transactions, a two-second lock timeout and fifteen-second statement
timeout against `helios_laptop`; nothing queries or changes the Pi.

## Verification

- Client deterministic cache tests: 10 passed. Includes query/cursor/identity
  separation, single-flight cancellation, late abandoned responses, semantic
  validation, empty updates, failure retry, malformed JSON, size/LRU/age bounds,
  timeout and advancing observation age.
- Python proxy test: passed; conditional headers and 304 entity semantics.
- Frontend contract check: eight endpoints covered; no new body fields consumed.
- Backend focused HTTP/error/OpenAPI tests: 25 passed, existing TestClient
  deprecation warning. No OpenAPI schema change.
- Strict API acceptance on dedicated `helios_browsing_20261027_test`: **299 passed**,
  no skips, one existing TestClient deprecation warning. Test database was created
  for this slice; no application data used by mutation tests.
- Browser real-data replay passed. Separate synthetic wire-compatible scenarios
  passed: two same-name dishes in lunch/dinner contexts, variants/add-ons, missing
  prices, source links, unknown coverage, collapsed technical details, retained
  data/focus after 503, stale-while-revalidate, confirmed empty update, corrected
  price, online revalidation, hidden pause, hard expiry, cold failure/retry,
  history before optional context, rapid selection with late responses, and
  small-screen overflow. No uncaught page errors.
- Full backend `make ci`: **passed**, including lockfile, all pre-commit hooks,
  strict mypy (210 files), **856 passed / 962 skipped**, one existing warning.
  This run had no DB configured; skipped tests are not database acceptance.
  The separate strict API run above supplies API database acceptance.
- `alembic check` against the dedicated test DB: **passed**, no new upgrade
  operations. The focused strict API run is not a claim of full strict-suite or
  Docker acceptance. The disposable test DB was removed after validation.

## Remaining work and boundaries

The venue list still remounts only its first 50 entries after having loaded 100,
although fresh pages no longer require network downloads. Area venues still
exhaust their cursors and mount all 382 cards in the representative area. Map
viewport/scroll restoration and progressive independent summary/list failures
remain for the follow-on slice. Inspection during verification also found that
About exhausts venue pages just to compute its headline count; remove that
full-catalog download in the same follow-on slice, using available summaries
rather than inventing a total-count field.

Collection completeness, last collection-attempt outcome, official restaurant
URL, stable page ID/label and cheap publication revision are unavailable today.
Their proposed semantics await extraction-owner acknowledgment and backend
implementation. Do not infer completeness from counts, scores or empty menus.
Current price contexts are rendered as supplied; unlabeled pages cannot become
a reliable lunch/dinner selector without backend metadata.

Fresh client data can lag published changes by up to 30 seconds while active;
background throttling/network failures can delay checking. Previously loaded
data stays explicitly labelled after refresh failure for no more than ten
minutes since successful validation. Manual refresh forces a check. This is not
push invalidation. HTTP validators always read current published data.
