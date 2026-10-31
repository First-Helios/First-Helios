# ADR-0024: Further menu-page discovery — the page cap and the candidate terms

**Status:** Proposed 2026-10-30 (session P8-21). Accepted 2026-10-31 by the owner: Q1–Q3 (D1 measured
first), then Q4–Q7 as recommended after D1 (cap 6; catering, drinks, beverages and bar as
candidate terms; the page's own menu signal unchanged; no separate cost ceiling).
**Date:** 2026-10-30
**Phase:** 6 / 8 (menu coverage; ROADMAP §7 item 7)
**Amends (if accepted):** [ADR-0022](./0022-several-menu-pages-per-venue.md) points 2–3
(`MAX_MENU_PAGES` 3, `MAX_CANDIDATES` 12, the meal-period lexicon; Q3 left drinks and catering
terms out)
**Depends on:** one universal pipeline (no per-site rules), no manual entries, never lose
Bronze or Menu data
**Record:** [2026-10-28-p8-21-coverage-baseline.md](../reviews/2026-10-28-p8-21-coverage-baseline.md)

## Context

ADR-0022 keeps at most 3 own-site menu pages per venue. Candidates come from well-known paths
and anchors whose text or path holds a menu or meal-period term. Drinks and catering terms were
left out (ADR-0022 Q3).

### What is measured

- **P8-20's re-collection** (`var/laptop-run/p8-20-run.log`, 2026-10-28; whole crawl, 9,996
  venues):
  - 1,547 menu URLs found;
  - **272 verified own-site pages dropped over the 3-page cap** (`menu_pages_over_cap`);
  - 235 dropped as duplicates (`menu_pages_duplicate`);
  - 120 venues whose only menu is a linked PDF (`menu_pdf_only`).
- **Coverage baseline** (P8-21, 19 reviewed sites): 33 expected menu pages are not collected.
  Without Chick-fil-A's 17 category pages there are 16 (`var/p8-21/coverage/misses.py`):

  | Cause | All | Without Chick-fil-A |
  |---|---|---|
  | Image or script state (out of this ADR's reach) | 9 | 9 |
  | **Not a candidate:** no candidate term in anchor or path ("Catering", "Trays", "Flavor Options", "Order Online") | 10 | 4 |
  | Verifier rejected (Chick-fil-A's price-less national pages; a kids menu) | 8 | 1 |
  | **Over the cap or candidate limit** (V Cafe's second menu, Café Blue's kids menu) | 5 | 2 |
  | The homepage itself (ADR (d)) | 1 | 1 |

- **Synthetic:** a site with Lunch, Dinner and Drinks pages loses Drinks, because "Drinks" is no
  candidate term.
- **ADR-0022's own sample** (stratum A, 300 venues; candidates up to 12, meal periods):
  - 40.7 % of venues have ≥ 2 verified pages, 13 % have ≥ 3;
  - the extra pages were judged 47 % distinct menus, 20 % overlap, 12 % duplicates, 22 % not
    menus (national-chain product pages).

**What is not measured:** of the 272 over-cap pages, how many are distinct menus, how many are
overlaps or duplicates, and how many are chain product pages. That decides whether a higher cap
adds menus or noise.

## Decision (proposed)

### D1. Measure first (no pipeline change)

1. **The over-cap pages.**
   - Replay P8-20's discovery from `var/site-cache` (read-only; fresh from the re-collection)
     with no cap. That costs no new fetch: the over-cap pages were fetched and verified.
   - Draw a seeded sample of about 60 venues with over-cap pages.
   - A Sonnet subagent judges each extra page against the kept ones (distinct / overlap /
     duplicate / not a menu), as ADR-0022's record did. This session re-checks; the owner
     confirms disagreements.
   - Report the share of distinct menus by page rank (4th, 5th, 6th…).
2. **The candidate terms.** On the same replay, with drinks, beverages, cocktails, wine, bar
   and catering added as candidate terms:
   - count the new candidates and how many verify;
   - judge a sample the same way;
   - new candidates are fetched live, politely, into a scratch cache.
3. **Cost.** Every added page is a page to fetch, render if needed, and extract on the GPU.
   - The re-collection extracted at about 359 pages an hour on the laptop.
   - The Pi runs about 7.8 pages an hour (§8).

### D2. If D1 justifies it (proposed shape, not decided)

- **Cap.** Raise `MAX_MENU_PAGES` to the rank where distinct menus stop outnumbering overlaps
  and duplicates (D1 item 1). The duplicate rule (block-text Jaccard ≥ 0.9) and the
  sticky-first-page keying of ADR-0022 stay as they are.
- **Terms.** Add only the terms whose new candidates are mostly distinct menus (D1 item 2).
  Terms stay candidate terms only: the page check still decides, so a "Catering" link to a
  contact form is not kept.
- **No chain rule.** National-chain product pages (Taco Bell, Chick-fil-A) are a known source of
  "not a menu" extra pages. They are left to the classifier, not to a host list.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **A. Keep cap 3, today's terms** | No cost | 272 verified pages dropped; drinks and catering menus never seen |
| **B. Raise the cap without measuring** | Simple | ADR-0022's sample: about a third of extra pages are overlaps or duplicates, and 22 % are not menus |
| **C. Measure, then raise the cap and add terms where they pay (D1 → D2)** | Decided on data; same page check | A labelling pass first |
| **D. A per-site or host list of extra pages** | Precise | Rejected: manual entries, per-site rules |

## Consequences

- **D1** costs a replay from the cache, a sample's live fetches for the new terms, and a
  labelling pass. It changes no stored data.
- **D2** grows the menu-URL records: path keys `<gers>|<path>` (ADR-0022), several pages per
  venue. It also grows the extraction load and GPU time by the share of pages added.
- `gold.price_index` weighs each venue once (ADR-0022 context). More pages per venue add items,
  not weight.

## Owner questions

- **Q1. Order.** Run D1 before deciding the cap or the terms? *Recommended.* 272 over-cap pages
  is large enough to matter, and ADR-0022's sample says a third of extra pages are overlaps.
- **Q2. Which terms to test in D1.** Drinks, beverages, cocktails, wine, bar, catering? Wine
  lists are out of extraction scope (Amendment 15). *Recommended:* test "wine" anyway, to
  count it, and decide at D2 whether a wine page is worth collecting at all.
- **Q3. Sample size.** About 60 over-cap venues and about 60 new-term candidates? This is
  ADR-0022's 60-judgement scale.
- **Q4. Cost bar.** Should D2 have a cost ceiling, for example at most +20 % pages per
  re-collection? Or is a raise decided on distinct-menu share alone?

## Owner decision

2026-10-31, "accept all recommendations":
- **Q1.** Run D1 (the over-cap pages and the new terms) before deciding the cap or the terms.
- **Q2.** Test drinks, beverages, cocktails, wine, bar and catering. "Wine" is counted even
  though wine lists are out of extraction scope; whether a wine page is worth collecting is
  decided at D2.
- **Q3.** About 60 over-cap venues and about 60 new-term candidates, judged at ADR-0022's scale.
- **Open:** Q4, a cost ceiling for D2. No recommendation was made; it is decided with D1's
  numbers.

## D1 results (2026-10-31)

Scratch: `var/p8-21/adr24/` (`overcap.py`, `judged.jsonl`, `judged-rechecked.jsonl`,
`recheck.py`, `newterms.py`, `newterms.json`). Discovery was replayed with the production
verifier against read-only copies of P8-20's `var/site-cache`. The few misses were fetched
politely into a scratch cache. No render, no database write.

### 1. The over-cap pages

- **Frame and sample.** 222 venues whose own-site records reached the cap in P8-20's
  re-collection; sample of 60 (seed 20261031).
- **Replay with no cap:** 22 venues have exactly 3 verified pages, 38 have more, and there
  are 98 over-cap pages in all.
- **Labels.** A Sonnet judge labelled each over-cap page against the 3 kept pages. This
  session re-checked the labels by the share of each page's priced lines a kept page also
  prints, on the whole cached page. 6 "distinct" pages print many priced lines that a kept
  full-menu page already shows (Manuel's, Black Walnut, Thai Spoon), and became overlap.

| Label | 4th | 5th | 6th | 7th+ | All |
|---|---|---|---|---|---|
| Distinct menu | 23 | 22 | 12 | 7 | **64 (65 %)** |
| Overlap | 9 | 3 | 2 | 2 | 16 |
| Duplicate | 1 | 0 | 0 | 0 | 1 |
| Another location's menu | 1 | 2 | 2 | 3 | 8 |
| Not a menu (chain product pages) | 4 | 4 | 1 | 0 | 9 |
| Distinct share | 0.61 | 0.71 | 0.71 | 0.58 | |

- About two thirds of the pages the cap drops are menus the kept pages don't cover: kids,
  lunch, drinks, desserts, catering, menu sections on their own pages.
- The distinct share holds through rank 6. Other-location pages rise at rank 7+ (3 of 12).
- Ranks 4–6 are 86 of the 98 over-cap pages.

### 2. The tested terms

- **Frame.** 1,134 venues in P8-20's replay link to at least one page that only a tested term
  would make a candidate. Catering has 1,351 such links, bar 184, drinks 103, beverages 65,
  wine 38.
- **Sample of 60.** 81 new-term pages fetched (73 answered 200). **4 pass the production page
  check** (catering 2 of 57, bar 1 of 10, beverages 1 of 4, wine 0 of 5, drinks 0 of 2).
  Judged: 3 distinct (a beer list, two catering menus) and 1 not a menu (a bar's prose page).
- **Why so few verify.** The page check needs a menu word (menu, menus, food, carte, eats) in
  the page's own path, title or first heading. ADR-0022 kept that list as it was, so a
  "Catering" or "Drinks" page rarely passes. The terms add a candidate, not a menu.

### 3. Cost

- The re-collection extracted at about 359 pages an hour on the laptop GPU.
- A cap of 6 would add about 240 pages per re-collection (86 / 98 of the over-cap pages,
  scaled to the 222 capped venues; P8-20 counted 272 over-cap pages). That is about +8 % of
  the 3,104 menu URLs, or about 40 minutes of laptop GPU per re-collection.
- The terms add about 1–2 extra fetches per venue that links one, about 1,500 fetches per
  re-collection, for about 60–75 venues gaining a page.

### Recommendation for D2 (owner questions Q5–Q7)

- **Q5. Raise `MAX_MENU_PAGES` from 3 to 6.** *Recommended:*
  - 61–71 % of ranks 4–6 are distinct menus;
  - about 160 more distinct menu pages per re-collection for about +8 % pages;
  - the existing duplicate rule and sticky keys stay.

  Not higher: at rank 7+ the distinct share falls (0.58) and other-location pages grow.
- **Q6. Add catering, drinks, beverages and bar as candidate terms only.** *Recommended*,
  low cost:
  - about 60–75 venues gain a page, mostly catering menus;
  - wine stays out (0 of 5 verified, and out of extraction scope).
- **Q7. Leave the page's own menu signal unchanged.** *Recommended.*
  - Widening it to the new terms would let catering and drinks pages pass, but every page
    that passes is extracted and stored as a menu.
  - The classifier's precision gap (Amendments 23, 25, 27) makes that a production risk,
    and it would need its own measurement.
- **Q4 (cost ceiling).** With Q5 and Q6, the cost is about +8 % pages and +1,500 fetches per
  re-collection. *Recommended:* accept that, with no separate ceiling.

### D2 decision (owner, 2026-10-31, "approved")

- **Q5.** `MAX_MENU_PAGES` 3 → 6.
- **Q6.** Catering, drinks, beverages and bar (with singular forms) become candidate terms only.
  Wine is not added.
- **Q7.** The page's own menu signal (`page_menu_signal`, `_MENU_TERMS`) is unchanged.
- **Q4.** No separate cost ceiling (about +8 % pages and about 1,500 fetches per re-collection).

The build is an `apps/discovery` change (`url_pipeline.MAX_MENU_PAGES`, `menu_url._CANDIDATE_TERMS`).
It reaches stored data only at the next re-collection, which the owner schedules.
