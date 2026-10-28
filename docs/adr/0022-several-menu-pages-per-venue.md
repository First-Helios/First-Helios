# ADR-0022: Several own-site menu pages per venue

**Status:** Accepted 2026-10-27 by the owner, Q1–Q9 all as recommended (see
[Owner decision](#owner-decision)). Proposed 2026-10-27 (session P8-20). Built in P8-20 (see
[Build notes](#build-notes)); the re-collection on `helios_laptop` and the Pi is a separate,
owner-approved step.
**Date:** 2026-10-27
**Phase:** 6 deliverable "Several menu pages per venue, before the next re-collection"
(ROADMAP.md; §7 item 7)
**Amends:** [ADR-0010](./0010-website-and-menu-url-resolution.md) Amendment 3 D3.5 (one menu
URL per venue) and [ADR-0011](./0011-provenance-endpoints-vs-identity-match-keys.md) §7 (the
menu-URL key scheme)
**Extends:** [ADR-0015](./0015-menu-url-reverification.md) (re-verification and withdrawal per
key; Amendment 2 `place-v1`) and [ADR-0006](./0006-gold-menu-read-models.md) Amendment 2
(dish-key precedence in enumeration)
**Depends on:** the owner's standing rules: one universal pipeline (no per-site or per-platform
readers), never lose Bronze or Menu data, withdrawals stay reversible, Gold is rebuildable
**Record:** [2026-10-27-p8-20-several-menu-pages.md](../reviews/2026-10-27-p8-20-several-menu-pages.md)
(method, every count below, the judged pairs and the re-check)

## Context

`SiteFetcher.discover_menu_url` stops at the first own-site candidate that verifies, and the
record is keyed `<gers>` (platform pages `<gers>|<host>`, ADR-0011 §7). A site that splits its
menu over pages keeps one. Tex Mex Joe's (venue 21459) stores `/blank` (drinks, desserts,
kids) and loses `/lunch` and `/services3` (breakfast).

Downstream already takes several sources per venue:
- each menu-URL record becomes its own `menu-page` record and Menu stream;
- `page_bronze`, `place_check` and `place_sweep` take the GERS from `key.split("|", 1)[0]`;
- `gold.current_menu` holds every family, and `GET /v1/venues/{id}/menu` returns `menus: [...]`,
  one per source page with its `source_url` (ADR-0008 Amendment 4);
- the site already renders "N menus", each with its source link;
- `gold.price_index` weighs each venue once (its sample is the median of its priced rows), so a
  repeated dish shifts a venue's median slightly but never its weight.

Only 27 venues hold an own-site and a platform record today, so cross-record duplicates are
rare now. With several own-site pages they become common (below).

### Measurements (helios_laptop, read-only, 2026-10-27)

Method (record §1). The stored discovery was replayed from `var/site-cache` with no first-match
`break`: the same candidate ranking, `classifier-v2`+v3 verifier, homepage comparison and
`place-v1`, in a READ ONLY transaction. Candidates after the first verified page were mostly
never fetched (4,204 of 4,628 were cache misses), because of that `break`. So a seeded sample
(seed 20261027) was topped up live into a scratch cache, never `var/site-cache`:
- stratum A: 300 of the 1,485 readable sites that verify an own-site page today;
- stratum B: 200 of the 3,078 readable sites that verify none.

The replay reproduces the stored own-site URL for 1,370 of the 1,370 venues where both verify
something. 917 homepages had no cache entry and are outside both strata.

**1. Venues with more than one verified page (stratum A, 95 % Wilson intervals).**

| Candidates | Venues with ≥ 2 pages | ≥ 3 pages | Extra pages, cap 2 | Extra pages, cap 3 |
|---|---|---|---|---|
| Today's lexicon, 8 candidates | 105/300 = 35.0 % [29.8, 40.6] → ~520 | 25 (8.3 %) | ~520 | ~644 |
| Today's lexicon, 12 | 118/300 → ~584 | 34 | ~584 | ~752 |
| + meal periods, 8 | 111/300 → ~549 | 29 | ~549 | ~693 |
| **+ meal periods, 12 (proposed)** | **122/300 = 40.7 % → ~604** | **39 (13 %)** | **~604** | **~797** |
| + meal periods, 16 | 124/300 → ~614 | 50 | ~614 | ~861 |

The "meal periods" are breakfast, brunch, lunch, dinner, happy (hour), kids, specials and
dessert(s). They are added to the anchor lexicon, which today is only menu, menus, food, carte
and eats. That is why Tex Mex Joe's `/lunch` ("Lunch") and `/services3` ("Breakfast") were never
candidates. With them, all three of its pages verify (live check: 6,338, 4,325 and 2,761
characters).

Stratum B gains almost nothing: 3 of 200 (1.5 %) find a first menu with the extended lexicon.

**2. What the extra pages are.** All 224 pairs among each stratum-A venue's first three
verified pages were classed by price-line containment. A Sonnet judge then labelled 60 of them
blind (15 per class, stratified). The main session re-checked five; it agreed on four, and the
fifth was a weekday lunch menu the judge called "overlap", where the re-check says distinct.
Weighted back to the 224 pairs:

| Label | Share | Typical |
|---|---|---|
| distinct menu | 47 % | brunch vs dinner, drinks, kids, catering, a second menu page |
| overlap | 20 % | a section page of the full menu, a superset hub, another location's menu |
| duplicate | 12 % | `?menu=…`/`?menu_id=…` variants, `/menu` vs `/menus`, an anchor URL |
| B not a menu / neither | 22 % | chain single-product pages (13 of the 60 judged pairs: Taco Bell, Hawaiian Bros, Chick-fil-A blog), which the classifier accepts |

Price-line containment ≥ 0.8 is a poor duplicate rule: the judge agreed on 8 of 15. Text
identity is better: 6 of the 10 judged duplicates have block-text Jaccard 1.0. A threshold of
≥ 0.9 catches those six with one miss, a page re-served with an added holiday section
(Jaccard 0.96, judged "overlap"). The other four duplicates sit at 0.22–0.79 (tabbed hubs).

**3. Script shells and the Jefes case.** Among saved and withdrawn menu URLs, the stored page
is a static script shell (`looks_js_only`) for 7 resolved own-site records, 1 withdrawn record
and 4 platform records. 35 platform pages are already stored rendered, and none of the 55
wrong-place pages is a shell. Among candidates, 45 of the 300 stratum-A venues (15 %) have
crawled JavaScript-only candidates that only a render could judge (311 candidates).

Jefes (21183): its Overture website is the smorefood deep link itself. Discovery never treats
the website page as a candidate, and the page answers 429 with a Vercel Security Checkpoint
("We're verifying your browser"). The renderer skips 403/429 and challenge pages as
`bot_challenge` by design (ADR-0013 §4). So `--render` does not reach it, and nothing here
should defeat a bot check.

Deep-link websites in general (a non-root path, 1,920 venues, mostly chain location pages): of
1,135 readable ones, the website page itself verifies for 29. For 22 of those, nothing else on
the site does, and one is a printify product page. Checking it costs no request: the homepage
is already fetched.

**4. The 55 rule-withdrawn venues** (P8-18, `wrong_place`), replayed from the cache:
- 43: the only page that verifies on the venue's site is still the other place's page. Their
  Overture website is another place's site; `seasideonthepier.com` alone is the website of
  about 18 Austin venues.
- 3: have unfetched candidates that may recover (abarestaurants `/austin`, Mason's Lobster,
  Brio).
- 6: the homepage fails today (404, 429 or 500), Jefes among them.
- 1 (a menudrive print page) verifies again.
- 2 find nothing.

Several pages per venue will not refill these menus. The other 74 rule-withdrawn own-site
records (62 `no_menu_found`, 12 `http_404`) show 8 with JavaScript-only candidates and 3 with
unfetched ones.

## Decision (proposed)

1. **Record key: sticky first page, path keys for the others.**
   - `<gers>` keeps the venue's first own-site page. While its saved URL verifies, re-discovery
     never moves it, even when another page now ranks first (Tex Mex Joe's `/lunch` outranks
     the stored `/blank`).
   - Each further own-site page is keyed `<gers>|<path>`. `<path>` is the path and query of
     the page's final URL, for example `…|/lunch`. A platform suffix is a host, with no leading
     `/`, so the two never collide, and `split("|", 1)[0]` stays the GERS everywhere.
   - When the `<gers>` URL fails re-verification, re-discovery puts the first-ranked verified
     page that no other key holds there (today's behavior).
   - A path key whose URL fails is withdrawn and never re-pointed. A new page gets its own key.
2. **Cap and ranking.** At most **3 own-site pages** per venue (`MAX_MENU_PAGES = 3`). The
   ranking is unchanged: well-known paths, then sitemap and homepage anchors interleaved.
   - `MAX_CANDIDATES` goes from 8 to **12**.
   - The anchor lexicon gains the **meal periods** above. Drinks and catering terms are not
     added (Q3).
   - Pages already held count first. A newly verified page beyond the cap is ignored until a
     slot frees. Platform records are unchanged (at most `MAX_PLATFORM_CANDIDATES` hosts).
3. **Which pages count; the duplicate rule.**
   - Every page passes the first page's gate: a 200 HTML page off the homepage, with a
     different body, that the verifier accepts and `place-v1` does not reject.
   - A further page is a **duplicate**, and is not stored, when it is the same resource as an
     accepted page (`same_resource`, as today), or when its `segment` block-text set has a
     Jaccard of at least **0.9** with an accepted page's.
   - The rule runs at discovery only. Re-verification never withdraws a page for having become
     a duplicate.
4. **Duplicates across records: dish key plus price set, own-site records only.** ADR-0006
   Amendment 2's enumeration rule is extended across one subject's own-site families, in rank
   order:
   - `<gers>` first, then the path keys in key order.
   - A priced dish on a later family whose `dish_key` **and** price set both equal one already
     enumerated on an earlier family is not enumerated.
   - A same-name dish at another price stays. Lunch and dinner prices are real data.
   - Platform families are not part of the rule (Q4b).
   - Nothing is withdrawn or deleted, there is no migration, and rebuild equality holds.
5. **API and site: one menu per page underneath, joined on the site.**
   - Gold and `GET /v1/venues/{id}/menu` keep `menus: [...]`, one per page with its
     `source_url`: no wire change.
   - The site shows the venue's pages as one menu: one heading, the pages' sections in rank
     order, and each page's source link where its sections start (a frontend-repo change).
6. **Re-verification and withdrawal per key (ADR-0015).**
   - Each key, `<gers>` and each path key, is re-verified on its own schedule: a verifier
     change or 90 days.
   - A failure in `WITHDRAW_REASONS`, including `wrong_place`, withdraws that key alone to
     `needs_review`, with the same Evidence and the same reversibility.
   - R4 withdraws only that key's Menu streams, and the key is re-assigned when its URL
     verifies again.
7. **Rendering and the website page itself.**
   - Own-site rendering is unchanged: at most `MAX_RENDER_CANDIDATES` (2) JavaScript-only
     candidates, and only when no page verified statically. Extra pages are not rendered in v1
     (Q7).
   - A **deep-link website** (a non-root path that is not on a platform host) is itself
     checked as a candidate, ranked first, with `trust_path=False`, from the bytes already
     fetched.
   - Bot challenges stay skipped (ADR-0013 §4). Jefes stays empty until its page is reachable.
8. **Re-collection trigger.** Own-site menu-URL payloads gain `"pages": "pages-v1"`.
   - In the next `resolve_urls` run, a venue whose `<gers>` record lacks it is re-discovered
     once, whatever the 90-day window. That covers resolved records and rule-withdrawn ones,
     so the 55 `wrong_place` venues are retried.
   - A `<gers>` URL that still verifies stays; new pages fill path keys up to the cap; then the
     marker is written.
   - Venues with no saved record keep the 20-day failure cooldown (stratum B's yield is 1.5 %).
   - The re-collection after the build:
     1. `pg_dump`;
     2. `resolve_urls --render` under `xvfb-run`;
     3. menu-page fetch;
     4. extraction of the new pages (about 800);
     5. rescore;
     6. Gold refresh;
     7. the Pi's data refresh.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| Key per rank (`<gers>#2`, `#3`) | Short keys | A page's history moves whenever ranking changes (Tex Mex Joe's `/lunch` now outranks `/blank`) |
| Key by URL hash | Stable | Opaque in Bronze and in review; the path is already a readable stable key |
| Re-key every own-site page by path, `<gers>` retired | One rule | Moves 1,518 records' history; Menu streams follow the record, so every page re-extracts |
| Uncapped pages | Most coverage | 16 candidates already reach 12 pages on one site; chain product pages pass the classifier (22 % of extra pages are not menus) |
| Price-line containment as the duplicate rule | Ignores chrome | 8 of 15 agreement with the judge |
| Merge the menus in Gold or the API | One object on the wire | A wire and possibly a Gold change for what the site can join; loses per-page `source_url` and observation dates |
| Name-only cross-record dedupe (ADR-0006 Am 2 as is) | Same rule as within a page | Hides lunch prices behind dinner prices for the same dish name |
| Follow menu links from a verified page (one hop) | Reaches tabbed hubs | 668 of 1,485 first pages link 11,721 further menu-ish URLs, mostly chain product pages and `?menu_id=` variants |
| Render JavaScript-only candidates for extra pages too | Reaches script-loaded section pages | 15 % of menu venues, browser time per candidate, yield unmeasured |

## Consequences

- About **600 venues** gain a second page and about **800 pages** are added at cap 3, with
  ±5 points of sampling error on the venue share. That is about half again the 1,597 pages
  extracted in P5-33, so the next extraction run is about 50 % longer.
- Re-discovery re-crawls about 1,500 menu sites once: a homepage, sitemaps and up to 12
  candidates each, at the polite per-host rate. Expect an overnight laptop run.
- About a fifth of the extra pages are not menus (chain single-product pages, blog posts) that
  the classifier passes (its known precision gap, ADR-0013 Amendment 23). They cost fetch and
  extraction time; a page with no priced dish adds no Gold row.
- Partial overlaps (20 %) leave some repeated dishes. The cross-record rule hides exact
  name-and-price repeats; a section page repeating the full menu at the same prices is hidden.
  Another location's menu at other prices stays.
- Jefes and the 43 sites whose website is another place's do not get a menu from this. Fixing
  wrong websites is a website-resolution problem (ADR-0010), not a menu-page one.
- No migration and no API change. `place_sweep`, `page_bronze` and Gold read path keys
  unchanged; a test pins the `split("|", 1)[0]` contract.

## Owner questions

- **Q1. Key.** Sticky `<gers>` for the first page and `<gers>|<path>` for the others
  (recommended)? Or re-key all own-site pages by path?
- **Q2. Cap.** 3 own-site pages (recommended: about 800 pages, +193 over a cap of 2 for the 13 %
  of venues with three)? Or 2 (about 600)?
- **Q3. Candidates.** 12 candidates plus the meal-period terms (recommended)? Keep drinks and
  catering out? Drinks pages already verify through today's lexicon (wine lists are out of
  scope, ADR-0013 Amendment 15), and catering is ADR-0016's `other` course.
- **Q4. Duplicates.**
  - (a) Block-text Jaccard ≥ 0.9 against accepted pages, at discovery only (recommended)?
  - (b) Cross-record enumeration rule by dish key **and** price set, own-site families only
    (recommended)? Or also platform families? Or name only, as within a page?
- **Q5. Site.** Join the pages into one menu on the site, with the API unchanged (recommended)?
  Or merge them into one `MenuResponse` (an ADR-0008 amendment)?
- **Q6. Re-verification.** Per key, as in point 6 (recommended)?
- **Q7. Rendering.** Keep own-site rendering for the first page only (recommended)? Or also
  render JavaScript-only candidates for extra slots (15 % of menu venues)? And check a
  deep-link website page itself as the first candidate (recommended: 22 venues, no extra
  request)?
- **Q8. Re-collection.** The `pages-v1` marker forces one re-discovery of every venue with an
  own-site record, including the 55 `wrong_place` ones (recommended)? And leave no-record
  venues on their 20-day cooldown (recommended)?
- **Q9. The 43 wrong websites.** Record them for a later website-resolution unit (recommended)?
  They are out of scope here.

## Owner decision

**Answered by the owner on 2026-10-27: "approved all recs".** Every question is answered as
recommended:

- Q1: sticky `<gers>` for the first page, `<gers>|<path>` for the others.
- Q2: cap 3.
- Q3: 12 candidates plus meal-period terms; drinks and catering terms stay out.
- Q4:
  - (a) block-text Jaccard ≥ 0.9, at discovery only;
  - (b) cross-record enumeration rule by dish key and price set, own-site families only.
- Q5: the site joins the pages into one menu, and the API is unchanged.
- Q6: re-verification and withdrawal per key.
- Q7: no rendering for extra pages; a deep-link website page is checked as the first
  candidate.
- Q8: the `pages-v1` marker forces one re-discovery of every venue with a `<gers>` record,
  rule-withdrawn ones included; venues with no record keep the 20-day cooldown.
- Q9: the 43 wrong websites are left for a later website-resolution unit.

## Build notes

Built 2026-10-27 (P8-20), with no migration and no API change.

- **Candidates** (`apps/discovery/menu_url.py`).
  - `_MEAL_TERMS` (breakfast, brunch, lunch, dinner, happy, happyhour, kids, specials,
    dessert, desserts) extend the anchor and sitemap lexicon (`looks_like_menu`,
    `menu_links_from_sitemap`, and so the menu-PDF links).
  - `page_menu_signal` keeps `_MENU_TERMS`.
  - `MAX_CANDIDATES` is 12.
  - `is_deep_link(url)`: a non-root path off a platform host. `/index.html`, `/home` and
    `/en` are roots.
- **Discovery** (`SiteFetcher.discover_menu_url`).
  - It returns every verified own-site page in rank order, each final page once.
  - A deep-link website whose own page passes the check (`trust_path=False`, the homepage's
    bytes) comes first, with the new signal `"website"`.
  - JavaScript-only candidates are rendered only when no own-site page verified, as before.
  - `_verifies` accepts the website page itself for a deep-link website, so it re-verifies.
- **Records** (`apps/discovery/url_pipeline.py`).
  - `_assign_own_pages` keys the pages. A URL held by an own-site key keeps that key, and
    those pages count first. `<gers>` is free when it has no record, its URL failed its
    re-check, it is rule-withdrawn, or it was saved for another website; a free `<gers>`
    takes the first-ranked other page. The rest take `_path_key` (`<gers>|<path[?query]>`).
  - A page that is the same resource as, or a Jaccard ≥ 0.9 copy of, a taken page is dropped
    (`menu_pages_duplicate`). A new key beyond `MAX_MENU_PAGES` (3) live keys of this website
    is dropped too (`menu_pages_over_cap`).
  - Own-site payloads carry `"pages": "pages-v1"` (`PAGES_VERSION`), and so do withdrawals
    after this discovery. A `<gers>` record without it is re-discovered once: its own-site
    keys are re-checked whatever their window (`_reverify_menus(force_own=True)`), and a
    rule-withdrawn `<gers>` passes the retry gate.
  - A rule-withdrawn `<gers>|<path>` key that is due (`_reverify_due`) also triggers
    re-discovery (`_withdrawn_pages_due`). A retried key that discovery does not re-acquire
    keeps `needs_review` with a marked `rejected/menu_not_verified` observation
    (`_mark_withdrawn_retried`), which restarts its window. That is skipped when the site's
    failure says nothing about its pages (network, robots), so those retry next run.
  - `_key_accepts`: an own-site key takes any own-site re-check URL, and a platform key only
    its own host. This is used by re-verification and the lifecycle transfer.
- **Gold** (`packages/helios_core/domains/menu/enumeration.py`).
  - Families are processed with each venue's own-site `menu-page` families in rank order
    (`_own_site_rank`, from the record key through `get_record_version`).
  - Per scope subject and GERS, a later family's dish whose `dish_key` and price set
    (`(amount_minor, currency)` of its priced observations) equal an earlier family's is
    skipped. Platform families are outside the rule.
- **Site** (frontend repo, branch `p8-20-one-menu`). The venue page renders one "Menu": each
  page's sections follow a line naming its scope, price count and source page (host and
  path), with one table of contents over all sections. The API orders menus by source
  record id, and a venue's `<gers>` record is written first.
- **Tests.**
  - `test/test_several_menu_pages.py`: path keys and the cap; the duplicate rule; the sticky
    first page with one forced re-discovery; per-key withdrawal and its reversal; the
    rule-withdrawn `<gers>` retried once.
  - `test_web_client.py`: every page in rank order (the Tex Mex Joe's shape); one page reached
    twice; the deep-link website page, with its re-check; a root page is never its own menu.
  - `test_menu_url.py`: meal terms are candidates, not page signals; `is_deep_link`.
  - `test_gold_catalog.py`: a later page's dish is hidden only at the same prices, ranked by
    key, with platform pages outside the rule.
- **Known gap.** When a venue's website changes, path keys saved for the old website are not
  re-checked (re-verification skips another website's keys, as for platform keys today).
  They stay resolved until a human or a later unit withdraws them. No path key exists yet.

## References

- [ROADMAP.md](../../ROADMAP.md) Phase 6 "Several menu pages per venue"; §7 item 7 (PR #134)
- [ADR-0010](./0010-website-and-menu-url-resolution.md) Amendment 3 (D3.5);
  [ADR-0011](./0011-provenance-endpoints-vs-identity-match-keys.md) §7;
  [ADR-0015](./0015-menu-url-reverification.md) Amendment 2 (`place-v1`, PR #135);
  [ADR-0006](./0006-gold-menu-read-models.md) Amendment 2;
  [ADR-0008](./0008-read-api-conventions.md) Amendment 4;
  [ADR-0013](./0013-phase5-menu-pipeline.md) §4 (rendering etiquette), Amendments 15 and 23
- Sizing scripts: `var/p8-20/` (untracked, in the main checkout)
