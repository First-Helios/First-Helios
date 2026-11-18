# Why 664 websites end at `robots_unavailable` (P8-22, ADR-0027 sizing)

Session P8-22, 2026-11-18. ADR-0027 sized `skipped/robots_unavailable` (736 venues) and left it
out of scope as fetch policy. This record asks whether a fix hides in it before any policy
question: is robots.txt really unreachable, or does the reason code cover something else?
Measurement only: no code, schema, dependency or `infra/` change, no database written.

## Result

**No cheap gain.** The reason code hides two different things, neither fixable by reading
robots.txt differently:

| Cause (80 sites, seeded) | Sites | What it means |
|---|---|---|
| **The website moved to another host** | **34** | robots.txt (and usually the homepage) redirects off-site |
| Unreachable | 32 | TLS failure 17, connect timeout 8, read timeout 3, refused / no route / no address 3, protocol error 1 |
| Server error (5xx) on robots.txt and the homepage | 6 | the site is broken |
| Works now | 8 | a transient failure; 3 serve robots.txt and the homepage cleanly today |

- **The moved websites** are the useful finding: about 10 are the same restaurant on a new
  domain (`jackallenskitchen.net` → `.com`, `fourbrothersatx.com` → `fourbrothersarepas.com`,
  `midorisushiaustin.com` → `midorisushi-austin.com`), 8 are chain store-locator pages that now
  redirect to the chain's homepage (Sonic, Maggiano's, Smashburger, Burger King → `bk.com`), and
  **about 14 are expired or hijacked domains**: gambling spam, `expireddomains.com`, a lawn
  service, a driving school, other restaurants. Following a cross-host website redirect blindly
  would ingest junk at that rate; the place checks (ADR-0025) wouldn't catch an unrelated
  business with no address on its page.
- **TLS failures** don't recover over plain `http://`: 1 of the 17 serves its page that way; the
  rest redirect back to the broken `https://` or answer 404 / 409 (an unconfigured site-builder
  domain).
- RFC 9309 lets a crawler follow a robots.txt redirect across hosts, but here the homepage
  redirects the same way, so reading robots.txt would only move the refusal to the homepage
  fetch (`redirect_refused`).

## Method

- **Population** (`helios_laptop`, read-only): the website endpoints whose latest Capture is
  `skipped/robots_unavailable`: 664 (ADR-0027's 736 counted venues; chains share websites).
- **Draw:** 80 distinct sites (by host, `www.` ignored), shuffled with seed 20261118.
- **Fetch:** the production User-Agent and timeout (15 s), redirects followed by hand up to 5
  hops with every hop recorded, robots.txt then the website URL, 3 s between requests to a site.
  The TLS-failing sites were re-tried once over plain `http://`.
- **Why the code says `robots_unavailable`:** `SiteFetcher._load_robots` sets that reason before
  fetching robots.txt and keeps it whenever the fetch returns nothing: a cross-host redirect
  (`redirect_refused`), any `httpx` error (`network_error`), an oversized body, or a 5xx. A 4xx
  already means "allow all" (RFC 9309), and a dead domain is caught before as `dns_unresolved`
  (ADR-0027 Q4).

## What would help (not built; owner's call)

1. **An honest reason code** (small, generic, as `dns_unresolved` was): when robots.txt can't be
   read, record the underlying cause (`redirect_refused`, `network_error`, `too_large`) and keep
   `robots_unavailable` for a 5xx. It adds no menus, but the next sizing reads the numbers
   directly instead of re-fetching.
2. **Moved websites** are an identity question rather than a fetch one: the venue's Overture
   website is stale. The next Overture release may carry the new domain; a guarded follow (the
   new host's page must name the venue or print its address) would be its own ADR, since about 4
   in 10 cross-host targets are junk.
3. Nothing for the unreachable and 5xx sites: they are retried after `RECRAWL_WINDOW` as today,
   which also picks up the 8 that work now.
