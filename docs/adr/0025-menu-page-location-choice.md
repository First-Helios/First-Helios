# ADR-0025: Choosing the venue's own location page on multi-location sites

**Status:** Proposed 2026-10-31 (session P8-21). Accepted 2026-10-31 under the owner's delegation (see [Decision](#decision-2026-10-31)). D1 measured 2026-11-01; D2 (address ranking) not built; **D2′ (a URL naming another place) accepted by the owner 2026-11-01** (see [Owner answers](#owner-answers-2026-11-01)), built in a separate PR.
**Date:** 2026-10-31
**Phase:** 6 / 8 (menu coverage; ROADMAP §7 item 7)
**Extends:** [ADR-0022](./0022-several-menu-pages-per-venue.md) (several own-site pages),
[ADR-0015](./0015-menu-url-reverification.md) Amendment 2 (`place-v1`, the wrong-place check),
[ADR-0024](./0024-further-menu-page-discovery.md) (the cap, now 6)
**Depends on:** one universal pipeline (no per-site or per-chain rules), no manual entries,
withdrawals stay reversible
**Record:** [2026-10-28-p8-21-coverage-baseline.md](../reviews/2026-10-28-p8-21-coverage-baseline.md);
sizing script `var/p8-21/adr25/locations.py`

## Context

A group or chain site often has one menu page per location. Today:
- **`place-v1`** (ADR-0015 Amendment 2) rejects a page that names **another metro**. It dropped
  271 pages in P8-20's re-collection. It can't tell **same-metro** locations apart: Roppolo's 6th
  Street and West Campus are both Austin.
- **Platform chain pages** are matched to the venue by its street address
  (`menu_url.address_on_page`, `rank_by_address`; ADR-0015 item 5).
- **Own-site pages** get no location match. Discovery keeps the first-ranked verified pages,
  whichever location they are.

### What is measured

- **Coverage baseline** (29 reviewed sites):
  - 4 of 20 collected pages are another location's;
  - Roppolo's: 3 of the site's pages are collected for a venue the site doesn't serve;
  - the taco food truck's menu is collected for the downtown restaurant.
- **ADR-0024 D1:** 8 of 98 over-cap pages are another location's menu, rising at the 7th page
  and beyond.
- **Population sizing** (`helios_laptop`, read-only; 2,818 stored own-site menu pages):

  | Page prints | Pages | Share |
  |---|---|---|
  | The venue's street address | 143 | 5.1 % |
  | Street addresses, none the venue's | 150 | 5.3 % |
  | No street address | 2,525 | 89.6 % |

  - 56 of the 685 venues with ≥ 2 own-site pages have a page that prints only other addresses.
  - **Reading a 40-page sample** of the 150, this session's own judgement:
    - 21 are detector noise (menu text such as "Street Corn Street");
    - 2 are the venue's own address written another way;
    - 2 are a chain's head office;
    - 4 are a shared chain menu that prints one location's address (Iron Cactus, Uncle Nicky's);
      the menu is the same at every location;
    - **11 are another location's or a moved venue's page**: Roppolo's 6th Street menu stored
      for its West Campus venue, a Chowbus store page of another branch, Asia Cafe, Tokyo
      Steakhouse, and others.
  - That is about 28 % of the 150, roughly 40 pages, about 1.5 % of own-site pages.
- **What can decide.** About 90 % of own-site menu pages print no street address at all. An
  address match helps only where a site prints one, or names the location in the URL or the
  page (`/west-campus`, "6th Street Menu").

### What is not measured

- How often a location-specific page exists on the same site for the venue (the right page to
  take instead).
- How often a shared chain menu is the right answer. It usually is: same items, often the same
  prices.

## Decision (proposed)

### D1. Measure first (no pipeline change)

1. Replace the street regex with the stricter one the platform guard already uses (a house
   number then a street name, `address_on_page`'s parts) plus a street-type list.
2. Re-size the 2,818 pages.
3. Judge a seeded sample of about 60 "other address only" pages and about 60 pages from venues
   with ≥ 2 location-like pages, at ADR-0022's scale: a Sonnet first pass, re-checked by this
   session, and the owner on disagreements. Labels:
   - own location;
   - another location (different menu);
   - shared chain menu;
   - moved venue (Overture address stale);
   - not decidable.
4. For each "another location" page, record whether the site has the venue's own location page,
   and whether discovery saw it as a candidate.

### D2. If D1 justifies it (proposed shape)

- **Location ranking among a site's own pages.** When two or more verified own-site pages are
  location-specific (they print different street addresses, or their URLs name different
  locations), order them by the venue's address and locality, as `rank_by_address` does for
  platform chains:
  - keep the venue's own location page;
  - drop pages that print another same-metro address and not the venue's.
- **Shared menus stay.** A page that prints no address, or prints several locations (a chain
  list), is not location-specific and is kept as today.
- **Moved venues are not this rule's.** A page printing one address that is near the venue, or
  the same name at a new address, is a stale-Overture question for discovery's
  website-change handling. It is flagged, not dropped.
- **Reversible.** A page dropped this way is a withdrawal with its own reason
  (`other_location`), restored on re-verification if the page changes, as ADR-0015 withdrawals
  are.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| **A. Status quo** (`place-v1` for other metros only) | No change | Same-metro locations collected for each other (about 1.5 % of own-site pages; Roppolo's) |
| **B. Address ranking among location-specific pages (D2)** | Generic; reuses the platform guard's matching | Decides only where pages print addresses or name locations (about 10 %) |
| **C. Drop every page printing another address** | Simple | Drops shared chain menus and head-office footers (6 of 40 sampled) and moved venues |
| **D. A per-chain location table** | Precise | Rejected: manual entries, per-chain rules |

## Consequences

- **D1** is a read-only sizing and a labelling pass.
- **D2** withdraws a small number of own-site pages (estimated tens, not hundreds) at the next
  re-verification or re-collection, and changes discovery's ordering for multi-location sites.
- A moved-venue flag would surface stale Overture addresses for review, which is useful
  separately.

## Owner questions

- **Q1. Order.** Run D1 before any rule? *Recommended.* The real share is small (about 1.5 % of
  own-site pages) and the detector is noisy, so the rule should be sized on clean labels first.
- **Q2. Shared chain menus.** Keep a menu that's shared by a chain's locations for every venue,
  even when it prints one location's address? *Recommended:* yes, since the items are the same.
- **Q3. Moved venues.** Flag a page that prints a single nearby address for review rather than
  withdraw it? *Recommended:* flag only.
- **Q4. Priority against ADR (d)** (the homepage as a candidate). The coverage baseline shows the
  homepage gap on 3 of 23 menu sites, and this one on 2. Run D1 here first, or (d) first?
  *Recommended:* (d) first. Its gain is coverage (venues with no menu today); this ADR's is
  precision on a small share.

## Decision (2026-10-31)

The owner delegated these questions to the agent session ("answer questions on your own and
work autonomously", 2026-10-31). The session took each recommendation. The owner can overturn
any of them before this PR merges.

- **Q1.** D1 (measure) runs before any rule. No pipeline change until D1's labels are in.
- **Q2.** A chain's shared menu is kept for every venue, even when it prints one location's
  address.
- **Q3.** A page printing a single nearby address is flagged as a possible moved venue, not
  withdrawn.
- **Q4.** ADR (d), the homepage as a menu candidate, runs first. D1 here follows it.

Status after this decision: **Accepted (agent, delegated); D1 not started.**

## D1 results (2026-11-01)

Read-only: `helios_laptop` after resolve-v6 and the stored bundles. Labels are a sonnet first
pass from offline packets (`LABELLING.md`), re-checked by this session. Scripts are untracked:
`var/p8-21/adr25d1/` in worktree `p8-21-q7` (`d1size.py`, `d1url.py`, `sample.json` sha256
`2bcd6e26…`, seed 20261101).

**1–2. Strict re-sizing** (2,818 stored own-site pages). An address is now a house number, an
optional direction, 1–4 name words and a street type from a list, in a block that reads as an
address line (a ZIP, a state, or at most 12 words):

| Page prints | Pages | Share | Loose regex (Context) |
|---|---|---|---|
| The venue's street address | 143 | 5.1 % | 143 |
| Street addresses, none the venue's | **64** | 2.3 % | 150 |
| No street address | 2,611 | 92.7 % | 2,525 |

- The strict form drops most of the detector noise ("Street Corn Street").
- No venue has two own-site pages that print different strict addresses. ADR-0025's
  "location-specific pages printing different addresses" set is empty.

**3. Labels** (120 pages):
- **A:** 60 of the 64 "other address only" pages.
- **B:** 60 pages of the 52 venues with ≥ 2 own-site pages where a page prints a strict address
  or two URLs name different places.

| Label | A (other address only) | B (multi-page, location-like) |
|---|---|---|
| own location | 9 | 29 |
| another location (different menu) | 23 | 13 |
| shared chain menu | 14 | 14 |
| moved venue (Overture stale) | 11 | 1 |
| not decidable | 3 | 3 |

- **The address rule D2 proposed doesn't separate them.** Of the 47 A pages printing exactly
  one address that isn't the venue's, 16 are another location's and 10 moved venues. The
  other 21 are 9 own pages (the venue's address written another way), 9 shared menus and 3
  undecidable. Dropping them would be right about 1 time in 3, and Q3 says moved venues are
  flagged, not dropped.
- **In B, another location's page usually prints no address** (11 of 13). Only the URL or the
  page's words name the location ("San Antonio location only", `/round-rock-menu`).

**4. The venue's own page.**
- Of the 36 other-location pages, the venue's own location page is on the site and was among
  discovery's candidates for 12; for the other 24 it isn't in the packet.
- For most of the rest the site has no page for the venue's location (Tino's: "menus and prices
  vary by location", two locations listed), or Overture's venue is another business (airport
  concessions under Salt Lick).

**A narrower signal: a URL naming another place.** All 45 own-site pages whose URL path names
a gazetteer place other than the venue's locality were labelled (`first-pass-U.json`):

| URL names | another location | own | shared | not decidable |
|---|---|---|---|---|
| only the metro's main city ("austin"), venue in a suburb | 2 | 5 | 0 | 1 |
| another place | **36** | 0 | 1 | 0 |

- Suburb sites call themselves "Austin" (`/austin-westlake-hills…`), so the metro's principal
  city says nothing.
- Without it, the signal is right on **36 of 37** pages (0.97). The one miss is a dish named
  "New York Deli Pizza". That is about 1.3 % of own-site pages: Salt Lick's Round Rock and
  Driftwood menus for its other venues, Texican's Manchaca and Kyle pages, Blue Corn Harvest's
  Round Rock page for its Cedar Park, Leander and Georgetown venues, Uchi Charlotte, Paperboy
  Denver.

## Decision on D2 (2026-11-01, under the owner's delegation)

- **D2 as proposed (address ranking) is not built.** On its own target it is right about 1 time
  in 3.
- **D2′, proposed for build** (next PR): an own-site page whose URL path names a gazetteer place
  that is neither the venue's locality nor the metro's principal city is another location's
  page. Discovery withdraws it with the reason `other_location`, reversibly (restored when a
  re-check no longer finds it), as ADR-0015's withdrawals are.
  - The metro's principal city is the area's most common venue locality, so the rule is generic.
  - Measured on the whole population: 36 of 37 right, about 37 pages reached.
- **Moved venues are not flagged by rule.** A single other address can't tell a move from
  another location: 10 moves and 16 other locations in A. They stay a review question for
  Overture data (Q3's flag has no reliable signal yet).
- **Shared chain menus stay** (Q2).

## Owner answers (2026-11-01)

The owner answered the questions this session raised after D1 (#151, #152):

- **Q1. D2′.** Build it and apply it: the stored-bundle withdrawal on `helios_laptop` (after a
  backup), then the Gold refresh, then the Pi restored from that database.
- **Q2. Page-check precision** (the held-out's finding, 0.90 on 50 pages; ADR-0013's verifier,
  recorded here with the others). Measure a larger sample first, about 200 of P8-20's new page
  texts at page level, before any verifier change. No learned-classifier retrain without the
  owner's approval.
- **Q3. Salt Lick's three airport venues and Thurman's** (a different business at the airport),
  which hold Salt Lick's `/round-rock-menu` and `/driftwood-menu`: withdraw those pages.
  D2′ reaches all of them (D1's `U002`, `U003`, `U009`, `U010`, `U013`, `U014`, `U033`, `U034`),
  so no venue-specific step is needed.
- **Q4. Next.** After D2′, menu coverage: script-shell pages the renderer doesn't reach, and image
  and PDF menus (a new dependency, the owner's decision), measured first with the coverage
  harness.

Status after these answers: **D2′ accepted; build next.** (This section was dropped when #154
merged and is restored here.)

## D2′ build (2026-11-01)

No schema change, no migration, no new dependency. The `verifier` string and the extraction
pipeline version are unchanged, so nothing is re-extracted or forced to refetch.

- **`apps/discovery/place_check.py`.**
  - `PlaceArea.principal`: the metro's principal city, the most common locality of the
    Overture POIs (`austin` on `helios_laptop`), loaded by `load_place_area`.
  - `other_location_places(url, venue, area)` is D1's rule (`d1url.py`): the URL path's runs of
    up to four tokens equal to an area locality or a gazetteer city, at least 4 characters and
    not all digits. Nothing when the URL names the venue's own locality, or only the principal
    city. A venue without an Overture locality is not judged.
  - `place_failure(...)` is the combined check, now `place-v2` (`PLACE_CHECK`, recorded in
    accepted saves): `wrong_place` when `place-v1` reads another metro; otherwise
    `other_location` for an own-site page whose URL names another location. Platform pages keep
    the address match (ADR-0015 item 5).
- **`url_pipeline.py`**, as `wrong_place` (ADR-0015 Amendment 2):
  - `other_location` joins `WITHDRAW_REASONS`: a re-check re-discovers, then withdraws through
    `_withdraw_menu` (`verification_failure: other_location`, `menu-url-reverify`);
  - discovery drops such a page; a site whose every verified page is rejected records
    `failed/other_location` (`failed/wrong_place` when one was another metro's);
  - a lifecycle transfer treats it as absent;
  - the report counts `menu_urls_other_location`. Bronze's `FAILURE_REASONS` gains
    `other_location`.
- **Reversible.** A withdrawn record is retried on ADR-0015's schedule and re-assigned when a
  page verifies again (for example the venue's own location page). R4 restores its streams.
- **`python -m apps.discovery.place_sweep [--dry-run]`** applies `place-v2` to the stored
  bundles, and reports `other_location` beside `wrong_place`.
- **Tests:** `test/test_place_check.py` (the rule, pure) and
  `test/test_menu_url_reverification.py` (a re-check withdraws and the record recovers;
  discovery drops; a suburb venue's "austin" URL is kept; the sweep).

**Measured on `helios_laptop`** (read-only dry run of the sweep, 2026-11-01; scratch
`var/p8-21/d2prime/` in worktree `p8-21-d2prime`):
- 3,190 stored menu pages; 3,036 checked (124 not resolved, 30 a bundle of an older URL).
- **`other_location`: 25 records, all 25 labelled another location's in D1** (`first-pass-U.json`).
  D1's 36 other-location URL pages are these 25, 10 that `place-v1` had already withdrawn, and
  Uchi's Charlotte page, which `place-v1` now rejects itself.
- **`wrong_place`: 3** new `place-v1` flags, because the gazetteer grew from 239 to 303 slugs
  with P8-20's pages: Uchi Charlotte and Mama Bro's Katy store pages on DoorDash and Uber Eats.
  All three are another metro's page.
- The 28 records carry **1,895 of Gold's 103,697 `current_menu` rows**, on 14 subjects; 10 of
  them lose their only menu.

## D2′ applied (2026-11-01)

Owner Q1, after #154 merged (`main` 7b2b9db). No other session was running.

**`helios_laptop`:**
1. **Backup:** `var/laptop-run/helios_laptop-2026-11-01-pre-d2prime.dump` (sha256 `03189176…`).
2. **`python -m apps.discovery.place_sweep`:** the dry run matched the measured sets exactly, then
   the live run withdrew **28 records** (25 `other_location`, 3 `wrong_place`) to
   `needs_review` (`menu-url-reverify`).
3. **`python -m apps.menu_pipeline.rescore`** (R4): withdrew the 28 records' Menu streams
   (28 LLM pages, 2 JSON-LD); nothing due, nothing rescored.
4. **`python -m apps.gold.refresh`:** `current_menu` **103,697 → 101,802** (−1,895, as measured);
   no row left on the 28 records. Price index 417 rows. Citywide median **1016 → 1049** on
   656 → 657 venues; p25 and p75 unchanged (700, 1400). A page shared by several venues no longer
   blocks one venue's own placement, hence +1 venue.
5. **Dump for the Pi:** `var/laptop-run/helios_laptop-2026-11-01-d2prime.dump` (sha256
   `9ce2dc4e…`).

**Pi** (procedure scripts and backups in `~/helios-backups/firsthelios-20261101-p8-21-d2prime/`;
older backups kept):
- Backup of the database (`pi-helios-pre.dump`, sha256 `5e2fc0a7…`) and the `3a524d6` code.
- Backend `3a524d6 → 7b2b9db` (git archive, `rsync --delete` keeping `.env` and `var/`; no infra,
  dependency or migration change), API rebuilt: restart 15 s, migrate exit 0.
- Database dropped, recreated and restored from the laptop dump: `pg_restore` with no stderr,
  309 s downtime, 101,802 Gold rows, median 1049, alembic `13081a087231`, `alembic check` clean.
- HTTPS smoke checks on `firsthelios.com` and `www`: `/`, `/healthz`, `/readyz`, `/v1/venues`,
  `/v1/price-index/cells` all 200.
