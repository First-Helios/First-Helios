# ADR-0026: The homepage as the venue's menu page, as a last resort

**Status:** Accepted 2026-10-31 (session P8-21) under the owner's delegation (see
[Decision](#decision-2026-10-31)). Built in a separate PR.
**Date:** 2026-10-31
**Phase:** 6 / 8 (menu coverage; ROADMAP §7 item 7, ADR (d) of the coverage baseline)
**Extends:** [ADR-0022](./0022-several-menu-pages-per-venue.md) point 7 (the website page itself,
for deep links only)
**Depends on:** one universal pipeline (no per-site or per-platform rules), no manual entries, no
learned classifier for decisions (ADR-0013 Amendment 19), withdrawals stay reversible
**Record:** [2026-10-28-p8-21-coverage-baseline.md](../reviews/2026-10-28-p8-21-coverage-baseline.md)
(the gap); sizing scripts under `var/p8-21/adrd/` in the P8-21 worktree (untracked)

## Context

Discovery checks a site's candidate pages (well-known paths, sitemap and homepage links) and,
for a deep-link website, the website page itself (ADR-0022 point 7). A **root** homepage is never
a candidate. The coverage baseline found menus printed on the homepage on 3 of 23 menu sites:
Tony C's (static), Got Ji's Kitchen and Hasta la Luna (script shells that render into menus).

### What is measured

Read-only `helios_laptop` (2026-10-31, after resolve-v5) and the fetch caches. No live fetch,
except the render sample below.

- **Frame.** 8,085 venues with a website-resolution record. 1,232 have a Gold `current_menu`
  row today.
- **Venues with no menu today, root website** (not a platform host, not a deep link):

  | Cached homepage | Venues |
  |---|---|
  | Passes the production page check statically (`classifier-v2+v3`, `trust_path=False`) | **68** |
  | Fails it | 1,698 |
  | JavaScript-only (`looks_js_only`) | 530 |
  | Not 200 HTML | 873 |
  | No usable cache entry (never fetched, robots, network) | 1,776 |
  | The verifier crashed (a malformed `href`; fixed separately) | 2 |

  The 68 pass at about 3.0 % of the 2,298 readable homepages. Venues that already have a menu
  pass at about 5 % (51 of 954).
- **Labels for the 68** (whole set, not a sample). A Sonnet first pass from offline packets
  (`LABELLING.md`), then this session's re-check. The re-check moved 3 venues to
  `other_place`: Nivi (template placeholder descriptions) and El Rey ×2 (the page is
  Philadelphia's El Rey; its footer prints "Philadelphia, PA 19103"). 68 venues, about 50
  distinct sites, because chains share one homepage (Honest Mary's ×5, MrBeast Burger ×4):

  | Label | Venues | After `place-v1` |
  |---|---|---|
  | `full_menu`: the venue's menu is on the homepage | 32 | 32 |
  | `partial_menu`: featured items, a teaser, a store of the venue's baked goods | 21 | 21 |
  | `not_menu`: coffee-bean or grocery stores, a cutting-board shop, a recipe post, hours | 8 | 8 |
  | `other_place`: another city's venue, a directory, a template, a brand site | 7 | 4 |

  `place-v1` (ADR-0015 Amendment 2) drops 3 of the 7 `other_place` pages: Haru Haru (Auburn) and
  El Rey ×2 (Philadelphia). It drops no `full_menu` page.
- **Precision of the homepage stratum** after `place-v1`, per venue: **0.82** (53 of 65) when
  featured items count as menu content, 0.49 (32 of 65) for a full menu.
- **No generic signal in hand separates the wrong pages.**
  - The verifier's probabilities interleave: the not-menu stores score 0.84–0.99, and the full
    menus 0.54–1.00.
  - A floor on priced blocks keeps the stores, which print prices.
- **Rendering JavaScript-only homepages** (seed 20261031, 40 of the 530; the production
  `BrowserRenderer`, 3 s per host, scratch cache, the ADR-0023 Q5 policy):
  - 34 rendered, 5 `redirect_refused`, 1 `robots_unavailable`;
  - **0 of the 34 pass the page check** (95 % upper bound about 10 %). Most are 12-block
    builder shells;
  - 15.5 s median, 44.3 s max on the laptop.

  The coverage set's two render-revealed homepage menus (Got Ji's, Hasta la Luna) are not
  typical of the population.
- **The coverage set with the rule built** (29 reviewed sites, offline): no site changes, and
  venue coverage stays 0.391.
  - Tony C's prints its menu on the homepage, but its `/menu` and `/concession-menus` pages
    verify (both labelled not the venue's menu), so a last resort never fires there. Only
    option C below would reach it.
  - Got Ji's and Hasta la Luna need a render (D).

  The gain shows in the population, not in this 29-site set.

### What is not measured

- The 1,776 venues with no usable cached homepage. At the same 3 % they would add about 50
  passing homepages at the next live re-collection.
- Item-level extraction quality on homepage pages. They go through the same extraction,
  validator and §8 measurements as any page.

## Decision

1. **The homepage is a last-resort candidate.** In `discover_menu_url`, when a root website
   verifies no own-site page (statically or by the existing render of up to 2 JavaScript-only
   candidates), the homepage is judged with the production page check (`trust_path=False`),
   from the bytes already fetched. If it passes, it is the venue's one own-site page, with the
   signal `"homepage"`.
   - Venues where anything verifies today are untouched. A teaser homepage never sits beside
     the real menu page.
   - No render of the homepage: 0 of 34 sampled renders would have passed.
2. **Same downstream as any own-site page.** `place-v1`, the cross-scope dedupe, the cap,
   R4 withdrawals and re-verification all apply unchanged. Platform links on the homepage are
   still verified separately, as today.
3. **Re-verification.** `_verifies` accepts the website page itself when the saved menu URL
   *is* the website (as for a deep link). A saved `/menu` that now redirects to the homepage
   still fails, so a removed menu page doesn't silently become the homepage.
4. **Reach.** New pages are found at the next `resolve_urls` run that re-discovers a venue
   (no menu today means it is re-tried on the usual schedule). No backfill run is part of this
   ADR.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **A. Status quo** (root homepage never a candidate) | No new wrong pages | 32 venues keep no menu although their homepage prints it (+21 with featured items) |
| **B. Last-resort homepage, static (chosen)** | +32 full menus (+2.6 % of venues with a menu), +21 featured-item pages, no change where a page verifies | 12 wrong pages of 65 kept (0.82 precision in this stratum) |
| **C. Homepage always a candidate** | Also reaches the homepage when a page verifies (Tony C's) | Adds teasers beside real menus (51 such homepages pass among venues with a menu) |
| **D. B plus rendering JS-only homepages** | Reaches script-shell homepages | 0 of 34 sampled pass; about 15 s per render, at most 530 renders on the laptop |
| **E. B with a stricter bar for homepages** | Would cut wrong pages | No generic signal measured separates them (probabilities and price counts interleave) |

## Consequences

- **Coverage.** About 53 venues gain menu content from the cached homepages alone, 32 of them a
  full menu. Expect about 50 more passing homepages from the uncached ones at the next live
  re-collection.
- **Precision.** About 12 wrong pages in this stratum (stores, a directory, a brand site, a
  template). Against about 2,900 own-site pages, page precision falls by about 0.4 points. The
  errors are the verifier's own kind (retail pages), so a later verifier change fixes them here
  too; R4 withdraws them when it does.
- **Price index.** Store prices (coffee bags, groceries) can enter a venue's median for those
  few venues.
- **Cost.** No new request: the homepage is already fetched for candidates.

## Decision (2026-10-31)

The owner delegated questions to the agent session ("answer questions on your own and work
autonomously", 2026-10-31). The session chose:
- **Q1. Build B?** Yes. The coverage gain (32 full menus, 21 more with featured items) outweighs
  about 12 wrong pages, which are the verifier's existing failure kind and reversible by R4.
- **Q2. Render JavaScript-only homepages?** No: 0 of 34 sampled pass.
- **Q3. Backfill?** No dedicated run. The next scheduled re-collection reaches these venues.
- **Q4. The 0.82 precision against §8's 0.95 page-precision bar.** §8 is a population bar, and
  this stratum moves it by about −0.4 points. Record it, and re-measure at the owed §8 held-out
  re-test.

The owner can overturn any of these before the PRs merge.
