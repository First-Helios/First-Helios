# ADR-0010: Website & menu-URL resolution (Phase 4 PR 6)

**Status:** Accepted
**Date:** 2026-09-21
**Accepted:** 2026-09-21 by project owner Fortune
**Amended:** 2026-09-23 — §3 etiquette, see [Amendment 1](#amendment-1-2026-09-23-crawler-etiquette) (review session S2; owner decisions D2)
**Amended:** 2026-09-23 — record grain and re-run rules, see [Amendment 2](#amendment-2-2026-09-23-record-grain-and-re-run-rules) (review session S3; owner decisions D3)
**Amended:** 2026-09-23 — menu-page verification and platform sites, see [Amendment 3](#amendment-3-2026-09-23-menu-page-verification-and-platform-sites) (review session S4; owner decisions D3.4-D3.5)
**Phase:** 4 (Venue Discovery, Identity & Geocoding)

## Context

[ADR-0009](./0009-venue-discovery-source-dedupe-and-schedule.md) shipped the
coverage subsystem: Overture Places → Bronze → conservative mint into
`identity.establishment`, seeded metro-wide (9,996 current venues, precision
gate met — see [retro](../retro/2026-09-21-phase-4.md)). It deliberately left
two Phase 4 deliverables as a follow-on unit (RFC-0001 PR 6): **website
resolution** and **menu-URL discovery**. This ADR settles that unit.

Two facts from the seed reshape the plan the ROADMAP wrote:

- **Website coverage is already 82.1%** (8,217 / 10,014) from Overture's
  published `websites` field — far above ROADMAP's ~30–40% planning number and
  the <30% stop-report floor. The marginal value of an Overpass/OSM website
  *fallback* — the original PR 6 headline, and the reason PR 6 was expected to
  add a new source + the `overpy` dependency — is now small.
- **There is no URL attribute anywhere in the identity schema.** The only URL
  concept is `bronze.SourceEndpoint.canonical_uri`, which is the resolver's
  **exact-match key**. That is the exact chain-collapse hazard ADR-0009 §"A
  concrete hazard" flags: a brand website (`torchystacos.com`) cannot be a
  `canonical_uri` — the resolver requires a canonical URL to identify *exactly
  one* Subject, and 50 Torchy's Organizations share one site. So website and
  menu-URL must persist as **non-identity attributes**, never as a match key.

### What the current code does and does not do

- Overture observations already carry `websites` in `source_payload` with
  `canonical_url = None` (ADR-0009 §1). Website data is therefore *already in
  Bronze* — this unit resolves and exposes it, it does not re-fetch it.
- `identity.commands.assign_source_record` links an additional Bronze source
  record to an existing current Subject, Evidence-backed — the mechanism for
  attaching a second-source attribute (a website, a menu-URL) to a Subject
  minted from Overture.
- Runtime deps after ADR-0009: `alembic, duckdb, fastapi, httpx, psycopg,
  pydantic-settings, sqlalchemy, structlog, uvicorn`. `httpx` is already a
  **runtime** dependency (promoted for Nominatim).
- There is **no `config/sources.yaml`** yet, and **no HTML/sitemap/robots
  handling** anywhere in the tree.

### Owner decisions (2026-09-21)

1. **Defer Overpass.** Given 82.1% coverage, PR 6 is **menu-URL discovery +
   the `config/sources.yaml` manual registry**. The Overpass/OSM website
   fallback (and its `overpy` dependency) is **not built in this unit**; it
   becomes a small later unit only if measured coverage ever needs it.
2. **Bronze payload + Evidence, no schema change.** Resolved website and
   menu-URL persist as Bronze source records + Evidence assigned to the
   Subject. **No identity/menu/gold migration.**
3. **Menu-URL grain is per-site**, keyed to the resolved website: discovery
   crawls whatever website resolved for a Subject, so a chain sharing one brand
   site yields one menu-URL and an independent yields its own. Grain follows
   the website, not a fixed Org-vs-Establishment rule. *(Superseded by
   [Amendment 2](#amendment-2-2026-09-23-record-grain-and-re-run-rules): records
   are per venue, not one per chain.)*
4. **A new dependency is authorized** when it is the optimal fit (owner,
   2026-09-21). Applied here: **PyYAML** for `config/sources.yaml`, so the
   registry keeps the name every doc already uses (ROADMAP §3.2, ADR-0009 §1,
   RFC-0001) and V1's `config/meal_deal_sources.yaml` shape, rather than
   deviating to a stdlib format. No other new dependency: menu-URL discovery
   uses the already-runtime `httpx` plus stdlib `urllib.robotparser`,
   `xml.etree`, and `html.parser`; registry validation is hand-rolled (a
   `jsonschema` dependency buys little for a four-field registry).

## Decision

Build website/menu-URL resolution as an **additive, Bronze-first, idempotent**
unit that reuses the ADR-0009 provenance/identity contracts, adds **no runtime
dependency** and **no schema change**, and keeps every URL out of the
Establishment match key.

### 1. Scope (owner decision 1)

- **In:** promote the Overture-published website to a resolved Org-level
  website attribute; a `config/sources.yaml` manual registry for known-good and
  override sites; menu-URL discovery over the resolved website.
- **Out (deferred):** Overpass/OSM website fallback and the `overpy`
  dependency. Recorded as a follow-on unit, gated on a future coverage need.

### 2. Persistence — Bronze-only, no schema change (owner decision 2)

- A resolved **website** is a Bronze observation
  (`source_namespace = "website-resolution"`, `source_kind = "website"`,
  `external_key = <GERS id>` — per-venue, so a shared brand site never
  collapses to one record), `assign`ed to the **Organization** Subject,
  Evidence-backed, `actor_class="rule"`. The URL and its origin
  (`overture` | `registry`) live in `source_payload`. **`canonical_url` stays
  `None` in this unit** — a website is an attribute here, never a match key
  (§4 hazard). The registry's `location_unique` flag is recorded in the payload
  for a possible future URL-promotion unit; it is not acted on now.
- A resolved **menu-URL** is a Bronze observation
  (`source_kind = "menu_url"`), `assign`ed to the same Subject the website
  resolved for (per-venue records, Amendment 2), Evidence pointing at the
  discovery capture (the fetched page / sitemap that yielded it).
- **Read path:** website is already queryable from `source_payload` today
  (the retro measured 82.1% exactly this way); menu-URL becomes queryable the
  same way. A typed **Gold `venue_url` projection** (subject_id, url_kind,
  url, observed_at) is the forward-looking clean read surface for the API and
  the Phase 5 scraper — noted here, consistent with ADR-0009 §5 (viewing
  filters live in Gold, not on identity tables), **built when first consumed**,
  not in this unit.

### 3. Menu-URL discovery mechanics

Per resolved website, deterministically, honoring etiquette as a hard
requirement (ROADMAP Phase 5 "scraping etiquette"):

- **robots.txt first** — ~~stdlib `urllib.robotparser`~~ `protego` since
  Amendment 1 (the stdlib parser applies the first matching rule and ignores
  wildcards); a disallowed path is never fetched.
- **Candidate paths:** `/menu`, `/menus`, `/food`, `/our-menu` — HEAD/GET with
  a real User-Agent, one host at a time.
- **Sitemap scan:** `sitemap.xml` (stdlib `xml.etree`), URLs matching a menu
  lexicon.
- **On-site anchors:** parse the homepage for `<a>` whose text/href hits a menu
  lexicon (stdlib `html.parser.HTMLParser` — **no HTML-parser dependency**).
- **Rate limit:** one token bucket per host, ~1 req/s; disk-cached replay
  bundles under `var/` keyed by normalized URL. **No live network in CI** —
  integration tests replay fetches/sitemaps/robots from disk fixtures.
- **Persist so re-scrapes skip discovery:** a Subject with a current
  `menu_url` Bronze record is not re-crawled; discovery is idempotent and
  re-runnable. *(Refined by
  [Amendment 2](#amendment-2-2026-09-23-record-grain-and-re-run-rules): the
  registry and a changed website both supersede a saved menu-URL.)*

### 4. `config/sources.yaml` manual registry

- A human-editable YAML registry (PyYAML): per host, a known-good website
  and/or menu-URL, plus a `location_unique: bool` flag recorded for a future
  URL-promotion unit (not acted on now). Ported in spirit from V1's
  `config/meal_deal_sources.yaml` (ROADMAP §3.2 process 8).
- **Structurally validated in code, with a CI test** that a malformed registry
  raises — required fields, types, and HTTP(S) URL well-formedness — so a bad
  registry breaks the build, not runtime. (Hand-rolled rather than a
  `jsonschema` dependency; the schema is four fields.)

### 5. Schedule and where it runs

- A re-runnable, idempotent CLI in `apps/discovery/` (composition root,
  ADR-0004), run on the **Orange Pi** alongside the API (ADR-0009 §3), ~monthly.
  Determinism comes from Bronze idempotency, not run-once side effects.

### 6. Hazard reaffirmed

Website equality is an **Organization-level signal, never an Establishment
identity key** (ADR-0009 §"A concrete hazard"). No code path in this unit sets
a shared brand website as a `canonical_url` or otherwise routes two
Establishments into one on URL equality. The registry `location_unique` flag is
the only path to a URL match key, and it is opt-in per row.

## Alternatives considered

| Axis | Option | Pros | Cons |
|------|--------|------|------|
| Overpass | **Defer (chosen)** | 82.1% already; no new source/dep; smallest diff | No fallback for the ~18% without an Overture site |
| | Include now | Fills some website gaps | New source + `overpy` dep for small marginal gain |
| Persistence | **Bronze payload + Evidence (chosen)** | Zero migration; additive like ADR-0009; provenance-native | Reads go through Bronze/Gold, not a direct column |
| | New identity columns | Direct typed reads | models + alembic = hard stop-and-ask; expensive-to-reverse |
| | New `identity.venue_url` table | Queryable + provenance, existing tables untouched | Still a migration/new model = stop-and-ask |
| Menu-URL grain | **Per-site (chosen; per-venue records, Amendment 2)** | Matches reality; chain→one, independent→own | Chain locations share one menu-URL (correct, but coarse per-location) |
| | Per-Establishment | Explicit per-location menus | Duplicates a shared brand menu across N locations |
| Discovery client | **httpx + stdlib (chosen)** | No new dep; robots/sitemap/anchor all stdlib | Hand-rolled crawl vs. a framework |
| | Scrapy/Crawlee now | Batteries included | Framework choice is Phase 5 / ADR-0006 — premature here |
| Registry format | **YAML / PyYAML (chosen)** | Matches every doc + V1 parity; best human-edit format | One small runtime dep (owner-authorized) |
| | TOML / stdlib tomllib | Zero dep | Deviates from the documented `.yaml` name |
| Registry validation | **Hand-rolled + CI test (chosen)** | No dep; precise errors for four fields | Not a formal schema doc |
| | jsonschema | Formal, declarative | A dependency for a four-field registry |

## Consequences

- **No schema migration**, and the only new dependency is **PyYAML**
  (owner-authorized, optimal fit for the registry) — the migration hard gate is
  fully cleared and the dependency gate is a single, small, well-typed library.
  This unit stays as cheap to review as ADR-0009's additive discovery.
- **Menu-URL coverage becomes measurable** (currently 0). Like website
  coverage, the actual figure is the Phase 4 deliverable to report.
- **Website reads still go through Bronze** until the Gold `venue_url`
  projection lands; acceptable — the retro already read website coverage this
  way. The scraper (Phase 5) will want the Gold projection; that dependency is
  when it gets built.
- **The ~18% of venues without an Overture website** get no website from this
  unit except via the manual registry — an accepted gap, revisitable with
  Overpass later.
- **Outbound crawling of third-party restaurant sites** enters the blast
  radius. Etiquette (robots.txt, UA, per-host rate limit, replay cache) is a
  hard requirement, not a nicety; a scraper that gets the project IP-banned
  costs more than the data.
- Keeping every URL out of the Establishment match key **preserves the
  no-collapse guarantee** ADR-0009 established.

## Stop-and-ask / open items for review

- **`config/sources.yaml` shape** — confirm the fields (host, website,
  menu_url, `location_unique`) and that JSON-Schema validation belongs in CI.
- **Gold `venue_url` projection** — confirm it is deferred to first-consumer
  (Phase 5/7), not built in this unit.
- **`infra/` touch** — a monthly scheduler on the Pi is an ops detail of this
  unit (ADR-0009 §3); any `infra/` change still gets a careful read (CLAUDE.md).

## Amendment 1 (2026-09-23): crawler etiquette

The 2026-09-22 codebase review (R05, R13, R14, R74, R79) found that §3's
etiquette was not delivered: stdlib `RobotFileParser` applies the *first*
matching rule and ignores `*`/`$` (so `Allow: /` + `Disallow: /menu` fetched
`/menu`), an unreachable robots.txt meant "crawl everything", and httpx
followed redirects to any host — past robots, the throttle, and onto private
addresses. Owner decisions D2 (remediation checklist) replace §3's etiquette
bullets with:

- **robots.txt is parsed with [`protego`](https://github.com/scrapy/protego)**
  (Scrapy's parser; BSD-3-Clause, pure Python, no transitive dependencies,
  typed) — RFC 9309 longest match, Allow wins ties, `*`/`$`, per-UA groups,
  `Crawl-delay`, `Sitemap:`. Owner chose a known library over a hand-written
  matcher (D2.1). This supersedes the "httpx + stdlib" row below for robots
  only; everything else stays stdlib.
- **robots.txt outcome** (RFC 9309 §2.3.1): 2xx → its rules; 4xx → allow all;
  5xx, network error, or a refused redirect → skip the whole site this run
  (D2.2). A `Crawl-delay` is honoured; one above 60 s skips the site.
- **Redirects** are followed by hand, max 5 hops, http/https only, same site
  (host, `www.` ignored), host must resolve to public addresses only; every hop
  is robots-checked and throttled (D2.3). Homepage links resolve against the
  post-redirect URL and `<base href>`.
- **Size cap:** bodies are streamed and abandoned past 3 MB (D2.4).
- **Cache:** atomic writes; every entry carries `fetched_at` and expires after
  7 days — robots.txt and failures per D2.5; a Pi run takes a day or two, so
  good pages are "kept for the run" (D2.5) and the next monthly run re-fetches.
- **Out of scope, recorded for later:** a classifier for pages of interest
  (Phase 5; ranks/verifies candidates, never overrides robots), and whether to
  ever override a robots `Disallow` (needs its own ADR, with blocked-site data
  from a Pi run first). See the checklist's D2 notes.

## Amendment 2 (2026-09-23): record grain and re-run rules

The 2026-09-22 codebase review (R04, R07, R15, R16, R32, R57, R73) found that
re-runs were neither safe nor idempotent, and that the "one per chain" wording
above does not match the code. Owner decisions D3 (remediation checklist) settle:

- **Grain is per venue** (D3.6). Website and menu-URL records are keyed by the
  venue's GERS id and assigned to the venue's Organization. Discovery mints one
  Organization per Overture POI today, so chain locations each get their own
  records (usually with the same URL). One-per-chain needs the Organization
  merge work first (venue-lifecycle sessions S12/S13). An Establishment
  deduped from several Overture records is processed once, from its most
  recently observed record (by `observed_at`; ties to the oldest record, so the
  key stays stable).
- **`needs_review` is never overruled** (D3.1). If a website or menu-URL record
  is in `needs_review`, the run counts it and skips it: no write, no assign,
  and no crawl of a disputed website. A venue whose Organization is no longer
  current is counted (`org_not_current`) and skipped instead of failing the run.
- **The registry always wins** (D3.2). A registry `menu_url` that differs from
  the saved one is appended as a new version of the same record; it stays
  assigned. **A changed website re-runs menu discovery**; a new menu-URL is
  appended only when discovery succeeds, otherwise the saved one stays current.
  Superseded values are not deleted: every earlier version stays in Bronze
  (immutable `source_record_version` rows), which is the history of replaced
  URLs.
- **Unchanged values are not re-persisted** (R16). A record whose latest saved
  payload equals the new one writes nothing, so a monthly re-run adds no Bronze
  rows for unchanged venues.
- **Commit every 100** (D3.3). Both discovery CLIs commit every 100 venues/POIs.
  `resolve_urls --limit N` counts only venues that need work (a write or a
  crawl), so chunked runs advance. A venue where no menu was found has nothing
  saved and is re-crawled each run until failed fetches are recorded in Bronze
  (D4.2, session S6).

## Amendment 3 (2026-09-23): menu-page verification and platform sites

The 2026-09-22 codebase review (R08, R33, R34, R75, R76) found that §3's
discovery mechanics accepted "any 200 HTML page" as a verified menu, joined
well-known paths onto shared platform hosts, matched a menu lexicon too
loosely, mishandled sitemap indexes and `.xml.gz`, and "fixed" garbage
website strings into bogus URLs. Owner decisions D3.4-D3.5 (remediation
checklist) settle:

- **A candidate is verified, not just fetched** (D3.4, R08). A candidate that
  is `#`, empty, non-http, or resolves to the homepage itself (directly, or
  via a redirect, or via body content identical to the homepage's) is never a
  menu URL. A candidate that does fetch is accepted only when its own URL
  path, `<title>`, or first heading carries a whole-token menu word and its
  body differs from the homepage's — no HTML-parser dependency, still stdlib
  `html.parser` (`apps/discovery/menu_url.py`). These are cheap, deterministic
  pre-filters; a content classifier that ranks or verifies candidates (never
  overriding robots) is out of scope here and gets its own ADR in Phase 5,
  same as Amendment 1 already recorded.
- **Catch-all / soft-404 hosts are detected, not trusted** (D3.4, R08). The
  first time a well-known path answers 200 on a site, `SiteFetcher` probes one
  random, almost-certainly-nonexistent path there (never otherwise, so most
  sites cost no extra request). If that 200s as HTML, the site
  answers 200 for anything, so a well-known path's own URL (`/menu` always
  contains "menu" by construction) is not evidence of a real menu there — only
  its `<title>`/heading count for those candidates on that site.
- **The menu lexicon is whole-token, with a blocklist** (D3.4, R34). Matching
  was already whole-token (`/menu-of-services` matches "menu" as a token, not
  a substring), so the false positives came from having no veto: a blocklist
  (`services`, `safety`, `careers`, `policy`, `donations`, `bank`, `admin`,
  `wp`, …) now rejects a link or page even when a menu term also matches, so
  `/menu-of-services`, `/wp-admin/nav-menus.php`, `/food-safety-policy`, and
  "Food Bank Donations" are rejected while `/menu`, `/dinner-menu`, and
  "Dinner Menu" still match.
- **Sitemap matches no longer crowd out homepage anchors** (R34). Sitemap and
  anchor candidates are interleaved rather than concatenated before the
  `MAX_CANDIDATES` cap, so a site with many sitemap-matched entries (e.g. a
  blog's tagged posts) cannot fill every candidate slot before a homepage
  anchor is ever tried.
- **Sitemap indexes, robots `Sitemap:` lines, and `.xml.gz` are handled**
  (R75). A sitemap *index*'s `<loc>` children name sitemap documents, never
  page candidates, and are expanded up to `MAX_SITEMAP_CHILDREN` (5); a site's
  robots.txt `Sitemap:` lines (read via `protego`'s parsed rules, same-site
  only) are tried before the `/sitemap.xml` convention; a `.xml.gz` URL whose
  body carries the gzip magic bytes is gunzipped with its own
  decompressed-size cap (independent of the compressed fetch cap) so a small,
  hostile payload can't expand into a memory bomb (one served with
  `Content-Encoding: gzip` is already decoded by httpx and passes through).
- **Shared platform hosts are a fallback, one menu URL per venue** (D3.5,
  R33). A small, explicit host list (Toast, Square, Clover, Facebook,
  Instagram, DoorDash, Uber Eats, Grubhub, Linktree, and alike) is never
  probed at its own well-known root paths — a shared platform's `/menu`
  belongs to the platform, not the venue, and a platform's root
  (`https://www.facebook.com/`) is never a venue's page. When the venue's
  *own* website is a non-root page on one of these hosts, that page is itself
  the menu-URL candidate
  (signal `"platform"`), verified only by fetching it — still through the
  full robots/redirect/public-IP policy, since `SiteFetcher`'s same-site
  check is relative to the URL being fetched, not the venue's original site.
  When the venue's website is its own site, a same-site menu candidate still
  wins; only if none verifies does a homepage link to a venue page on an
  *ordering* platform (e.g. `toasttab.com/<venue>`, a DoorDash store page) get
  accepted, same signal. Social links (Facebook, Instagram, Linktree) are on
  nearly every restaurant homepage and are not a menu, so they never serve as
  that fallback; nor does a platform root such as a "Powered by Toast" footer. Only one menu URL is stored per venue today (D3.5); reconciling a
  site's menu against a platform's when both exist needs a record-contract
  change and is deferred to S5/S6 (D4), same as Amendment 2's grain
  discussion — the owner noted this data should still be collected even where
  it duplicates the site's own menu, since some venues have no menu anywhere
  but a platform.
- **`_coerce_website` no longer "fixes" garbage into a bogus host** (R76). Its
  `https://` retry (for an Overture string missing a scheme) is trusted only
  when the retry parses into a host with a dot: `'http:/site.com'` (a typo'd
  single slash) parsed on the old retry as scheme `https`, host `http` — a
  URL shape, not a website — and was silently turned into
  `https://http/site.com`. That retry is now rejected instead.

## References

- [ROADMAP.md](../../ROADMAP.md) Phase 4; [RFC-0001](../rfc/0001-menu-pricing-first.md) §D3, PR 6
- [ADR-0009](./0009-venue-discovery-source-dedupe-and-schedule.md) (source/dedupe/schedule; the hazard this preserves)
- [ADR-0004](./0004-modular-monolith-identity-and-lifecycle.md) (Gold vs identity placement, composition root)
- [Phase 4 retro](../retro/2026-09-21-phase-4.md) (82.1% website coverage, menu-URL = 0)
- V1 port hints (`V1-Graveyard`): `collectors/meal_deals/osm_url_resolver.py`
  (URL canonicalization), `config/meal_deal_sources.yaml` (registry shape)
