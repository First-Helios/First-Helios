# ADR-0024: Further menu-page discovery — the page cap and the candidate terms

**Status:** Proposed 2026-10-30 (session P8-21). Not built. Stop for owner review.
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
