# ADR-0023: Bounded menu browsing cache and HTTP validation

**Status:** First slice accepted 2026-10-27 by the owner ("approved").
Follow-on pagination/navigation and new collection metadata remain separate slices.
**Date:** 2026-10-27
**Scope:** Frontend data lifecycle and API HTTP validation; no ingestion, schema,
deployment or dependency changes.
**Extends:** ADR-0008, ADR-0018, ADR-0019, ADR-0022.
**Evidence:** [verified audit and baseline](../reviews/2026-10-27-menu-browsing-audit.md).
**Contract boundary:** [integration proposal](../plans/2026-10-27-menu-browsing-integration.md).

## Problem

The client has route cancellation but no request sharing or response reuse. The
measured menu → trail → menu flow makes seven requests and downloads the same
restaurant/menu three times. A menu failure removes a successful restaurant
header. There is no safe publication revision for a server response store today.

## Accepted first slice

1. Keep native modules, hash routing, vendored Leaflet, stdlib proxy and existing
   wire bodies. Add a small memory-only request cache in the existing API module.
   No new library, browser persistence, build step, service worker or cache service.
2. Cache key is API version plus full encoded path and canonical sorted query
   parameters. Include all response-shaping inputs, including area/boundary,
   filters, currency, cursor, limit and future agreed context parameters. Use
   a returned validator as the cached representation's version. Do not invent a
   data-version request parameter before an upstream contract exists.
3. Deduplicate identical in-flight reads. Each subscriber has its own cancellation
   and current-selection guard; aborting one cannot abort a request another still
   needs. Abort transport after the last subscriber leaves; abandoned responses
   must not publish into a replacement request's cache slot. Timeout after 15
   seconds, release all listeners, retry only through a visible action/revalidation.
4. Bound responses to 100 entries, 8 MiB serialized payload total, and ten minutes
   since last successful validation. Evict least recently used; do not retain
   oversized responses. Fresh for 30 seconds. Stale data appears immediately while
   revalidating, with a clear updating state. A refresh failure retains eligible
   data and shows an inline warning/retry. Failure never inserts empty success.
   Failures/404/422/5xx are not reusable response entries. A confirmed successful
   empty publication replaces previous data. Protect against an old refresh
   reviving data after a newer invalidation or withdrawal response.
5. Revalidate active restaurant/history views every 30 seconds and on visibility/
   focus/online return; pause timers when hidden and clean them up on leave.
   Manual refresh bypasses freshness. A ten-minute hard age limit prevents a
   failing refresh from leaving old prices indefinitely. Label client check time
   separately from source observed_at. Compute displayed observation age from
   observed_at, so cached server age_seconds cannot freeze it.
6. Render restaurant header and menu independently. Keep a successful header on
   menu error, and keep a loaded menu on transient refresh error. Render useful
   history before optional restaurant/item names finish; reuse cached context.
   Give loading/status regions and retry buttons accessible names, stable focus,
   a usable touch target and no duplicate click requests.
7. Keep the joined-menu presentation and source boundaries of ADR-0022. Preserve
   node identities, every supplied price context, sizes/variants and additional
   charges. Show source dates/links and “Collection coverage unknown” with current
   wire data. Do not infer completeness or page context. Put technical extraction
   labels behind an optional disclosure, rather than beside every browsing price.
8. Add API HTTP validation for the read endpoints this client uses. Return weak
   content-derived ETags and `Cache-Control: public, no-cache` on successful reads;
   validate against freshly read data. Exclude only age_seconds and history's
   request-time as_of from semantic equality. Preserve menu/index publication
   as_of, source dates, identities, contexts, prices and source links in equality.
   Parse conditional tag lists/weak comparison correctly. Return bodyless 304 on
   match; errors carry no success validator and are `no-store`. Expose the headers
   to API clients and forward If-None-Match/Cache-Control through the existing
   frontend proxy. Preserve current JSON compatibility and request tracing.

The HTTP validator saves JSON transfer and client parsing on unchanged
revalidation; it does **not** promise fewer SQL reads. Resident API response
caching is deferred because neither the measurement nor a cheap revision
covering live provenance, identity, Gold corrections and withdrawals justifies
it yet. No new cache service or dependency is needed.

## Bounded follow-on slice

After the first slice passes, separately review/implement demand-paged area
venues (first 50 immediately; more on explicit request), independently rendered
index/list failures, route-state restoration of loaded pages/cursors, map viewport
and scroll, and cache-cohort reset on a changed head page. State should reference
the bounded response cache, not retain unbounded copied DOM/data. Do not claim
the first slice fixes area paging or all back-navigation behavior.

Future metadata consumption waits for written agreement with the extraction
owner. Official URL, menu/page IDs, known partial coverage and immediate revision
invalidation are follow-ups, not fields to fabricate in the client.

## Verification and acceptance

- Replay the same real-data baseline and report actual before/after request counts,
  JSON/transfer bytes and time to useful content; keep public network timings
  separate. Expected fresh menu → trail → menu: 7 → 3 requests, 32,634 → 11,746
  bytes for the baseline responses. These are targets until measured.
- Deterministic tests: canonical keys and changed filters/cursors; concurrent
  sharing/cancellation; expiry/size eviction; retry and failed refresh; stale
  response rejection; semantic ETags; changed/corrected/withdrawn/empty menus;
  proxy conditional-header propagation. No tests that merely mirror code.
- Browser: rapid switching with slow menu responses; repeated visits; history
  independent of optional context; no-menu versus failure; retained data warning;
  successful empty update removing old prices; manual refresh; multiple pages,
  duplicate-looking dishes and different contexts; variants/modifiers; mobile
  overflow, keyboard focus and retry. Use wire-compatible synthetic fixtures
  separately from real-data counts.
- Frontend contract check and backend `make ci`; disposable `*_test` DB acceptance
  when required by changed tests, never against application data. No publish/deploy.

## Owner decision

The owner answered "approved" after reviewing this proposal. The first slice,
cache bounds/freshness, HTTP validator approach and unknown-coverage wording are
accepted. Follow-on paging/navigation work and new collection metadata stay
distinct reviewable slices. Implementation and measured acceptance are recorded
in [the first-slice record](../reviews/2026-10-27-menu-cache-first-slice.md).
