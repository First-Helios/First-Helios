# Several menu pages per venue: sizing (P8-20)

Session P8-20, 2026-10-27. This is the ROADMAP Phase 6 deliverable "Several menu pages per
venue, before the next re-collection" (owner, 2026-10-27). The record holds the measurements;
the proposal is [ADR-0022](../adr/0022-several-menu-pages-per-venue.md).

Everything here is read-only with respect to the databases. It reads `helios_laptop` in READ
ONLY transactions, `var/site-cache` and the stored `menu-page` bundles. Nothing was withdrawn,
re-extracted or refreshed, and no LLM extraction ran. Live fetches were confined to the sample
in §1.2, went through the same `SiteFetcher` (robots.txt, per-host rate limit, public-address
and redirect policy, the discovery User-Agent), and wrote only to a scratch cache, never
`var/site-cache`. Code: `main` at cbb5e2f (#135 merged: `place-v1`, JSON-LD precedence).

Artefacts are untracked, under the main checkout's `var/p8-20/`:
- `common.py`: the layered fetcher (`var/site-cache`, then the scratch cache; misses go live
  only when `P820_LIVE=1`) and the extended lexicons;
- `size.py` → `replay.jsonl`: all 9,996 venues, cache only, with no first-match `break`;
- `crawl.py`: fetch-only top-up for the sample → `scratch-cache/`;
- `verify.py` → `verify-sample.jsonl` (the sample, 16 candidates, every lexicon group) and
  `verify-deep.jsonl` (deep-link websites); verified pages' text → `pages2/`;
- `shells.py` → `shells.jsonl`: every menu-URL record's stored page, `looks_js_only`;
- `hub.py`: links from first menu pages; `overlap.py` → `pairs.json`;
- `mkjudge.py` → `judge/` (60 blind pairs, `manifest.json`, the judge's `judgments.json`),
  `judge-key.json`;
- `an1.py`–`an10.py`: the tables below; `texmex.py`, `jefes.py`: the two named cases.

## 1. Method

### 1.1 The replay

For every current venue with a resolved own website that is not on a platform host (7,882),
`size.py` re-runs `discover_menu_url`'s own-site loop against the cache:
- the same `ordered_menu_candidates`, sitemap matching, homepage comparison and catch-all rule;
- the live verifier (`load_verifier()`) and `place-v1`, with the area loaded as `resolve_urls`
  loads it;
- one change: it keeps going past the first verified candidate.

Each candidate gets a verdict: `verified`, `wrong_place`, `not_menu`, `js_only`,
`same_as_home`, `home_redirect`, an HTTP status, or `miss` (not in the cache).

Results:
- **Agreement:** the first verified page equals the stored own-site URL for all 1,370 venues
  where both exist.
- **Missing homepages:** 917 homepages have no cache entry.
- **Unfetched candidates:** after the first verified page, 4,204 of 4,628 candidates are
  misses. Today's `break` means they were never fetched, so the cache alone cannot size
  several pages.

### 1.2 The sample and the live top-up

Seed 20261027, among sites whose homepage is cached and readable (4,563):
- **Stratum A:** 300 of the 1,485 that verify an own-site page.
- **Stratum B:** 200 of the 3,078 that verify none.

Candidates were built with every term group, so smaller settings could be simulated:
- today's lexicon;
- plus meal periods: breakfast, brunch, lunch, dinner, happy, happyhour, kids, specials,
  dessert, desserts;
- plus drinks: drinks, cocktails, beverages;
- plus catering.

`MAX_CANDIDATES` was 16. `crawl.py` fetched the misses with 32 workers partitioned by host, so
each host's rate limit stayed in one process. 136 candidates are still misses (timeouts and
refusals), recorded as unknown.

The deterministic catch-all probe used a fixed token (`helios-probe-p820probe`). An earlier,
broader lexicon try (with pizza, tacos, takeout and others) produced 19,901 new candidates on
2,308 sites and was dropped as unsizeable.

## 2. Figures

### 2.1 Pages per venue (stratum A, distinct final URLs, `an3.py`, `an7.py`, `an8.py`)

| Setting | 0 | 1 | 2 | 3 | 4 | 5+ |
|---|---|---|---|---|---|---|
| Today's lexicon, 8 candidates | 0 | 195 | 80 | 15 | 4 | 6 |
| Today's lexicon, 16 | 0 | 180 | 76 | 20 | 8 | 16 |
| + meal, 16 | 0 | 176 | 74 | 23 | 10 | 17 |
| + meal + drinks, 16 | 0 | 176 | 73 | 23 | 11 | 17 |
| + meal + drinks + catering, 16 | 0 | 168 | 78 | 26 | 11 | 17 |

At 12 candidates: today's lexicon gives 118 venues with ≥ 2 pages (34 with ≥ 3); with meal
periods, 122 (39). Extrapolations to the 1,485 sites are in ADR-0022's table, and the Wilson
interval for 105/300 is [29.8 %, 40.6 %].

Stratum B, + meal: 197 none, 3 one. Its candidates are mostly 404 (534), `not_menu` (324) and
`js_only` (178).

Candidate verdicts in stratum A (all groups, 16):

| Verdict | Count |
|---|---|
| http_404 | 837 |
| not_menu | 814 |
| verified | 581 |
| js_only | 350 |
| http_403 | 136 |
| miss | 66 |
| home_redirect | 13 |
| wrong_place | 13 |

Of the 13 `wrong_place` candidates, 7 venues' sites hold another place's page beside their
own.

### 2.2 Overlap between a venue's pages (`overlap.py`, `an4.py`, `an9.py`, `an10.py`)

For the first two or three verified pages per stratum-A venue (today's lexicon plus meal
periods), each pair was classed by **price-line containment**. A priced line is a segmented
line with a price token; chrome lines common to every page of the venue were removed. Classes:
- duplicate: ≥ 0.8;
- partial: 0.3–0.8;
- distinct: < 0.3;
- unpriced: either page has fewer than 3 priced lines.

| Cap | Duplicate | Partial | Distinct | Unpriced |
|---|---|---|---|---|
| 2 (124 pairs) | 16 | 15 | 31 | 62 |
| 3 (224 pairs) | 23 | 35 | 55 | 111 |

The unpriced share was too large to leave to a regex. So 60 pairs, 15 per class, seed
20261027, were labelled blind by a Sonnet subagent (`judge/`):
- page text was cut at 3,500 characters per page;
- the labels were `duplicate`, `overlap`, `distinct_menu`, `b_not_menu`, `a_not_menu` and
  `neither_menu`;
- the judge did not see the metric classes.

Agreement with the metric:

| Metric class | Judge's labels |
|---|---|
| duplicate ≥ 0.8 (15) | duplicate 8, overlap 5, distinct 2 |
| partial (15) | distinct 7, neither 5, overlap 3 |
| distinct (15) | distinct 9, B not menu 5, neither 1 |
| unpriced (15) | distinct 7, overlap 4, duplicate 2, B not menu 2 |

Weighted to the 224 pairs by class size: distinct 47 %, overlap 20 %, not a menu (B, or
neither) 22 %, duplicate 12 %.

Symmetric Jaccard per judged label (`an10.py`):
- **Duplicates:** text Jaccard 1.0 for 6 of 10 (`?menu=` and `?menu_id=` variants, an anchor
  URL, an ordering page reached by two paths); 0.79, 0.60, 0.58 and 0.22 for the rest. The rest
  are tabbed hubs (`/menu` vs `/menus` on BentoBox) and a hub whose first tab differs.
- **Overlap:** the highest is 0.96 (First Watch, the same page plus a holiday section); then
  0.81 and below.
- **Distinct:** at most 0.61.

So text Jaccard ≥ 0.9 marks 6 of 10 duplicates and one near-duplicate, and no distinct menu.

**Main-session re-check** of five pairs. The main session agreed with the judge on four:
- P03 (Black Walnut brunch vs dinner): distinct. Agree.
- P27 (Carve `/menu` vs `/menus`): duplicate. Agree; it is a superset hub, so duplicate or
  overlap.
- P48 (Brewtorium `/menu` vs `/food`): distinct. Agree on the first 3,500 characters (beer vs
  food). The full pages carry the same priced lines (price Jaccard 1.0): both URLs serve both
  menus with a different first tab. This is a limit of the cut.
- P50 (Michelle's Patisserie `/menu/` vs `/menus/`): duplicate. Agree.
- P57 (Roxie's full menu vs weekday lunch menu): overlap. Disagree: the lunch menu has its own
  items and prices, so it is distinct.

Chain single-product pages are 13 of the 60 judged pairs: Taco Bell `/food/featured/…`,
Hawaiian Bros `/food/…`, and a Chick-fil-A blog post. The judge called them not menus; the
classifier accepted them.

### 2.3 Links from a verified page (`hub.py`)

Of 1,485 first verified pages, 668 link same-site menu-ish URLs that are not homepage
candidates (11,721 links). The examples are mostly:
- chain product pages (Starbucks `/menu/product/…`, Taco Bueno `/food/…`);
- `?menu_id=` tab variants;
- category sub-pages (Hat Creek `/full-menu/chicken`).

A one-hop follow is not proposed.

### 2.4 Script shells (`shells.py`, `an6.py`)

Every menu-URL record's latest page (the stored bundle, else the cache), by state, key kind,
source and `looks_js_only`:

| Records | State | Kind | Failure | Source | Shell |
|---|---|---|---|---|---|
| 1,504 | resolved | own | | bundle | no |
| 7 | resolved | own | | bundle | **yes** |
| 5 | resolved | own | | cache | no |
| 2 | resolved | own | | none | |
| 35 | resolved | platform | | bundle (rendered) | |
| 4 | resolved | platform | | cache | **yes** |
| 7 | resolved | platform | | none | |
| 1 | resolved | platform | | bundle | no |
| 55 | needs_review | own | wrong_place | bundle | no |
| 61 | needs_review | own | no_menu_found | bundle | no |
| 1 | needs_review | own | no_menu_found | bundle | **yes** |
| 12 | needs_review | own | http_404 | bundle | no |

JavaScript-only candidates in the sample (today's lexicon plus meal periods):
- **Stratum A:** 311 crawled and 34 well-known, on 50 venues; 45 of them have crawled ones.
- **Stratum B:** 69 crawled and 104 well-known, on 39 venues.

### 2.5 Deep-link websites (`verify.py deep`)

1,920 replayed venues have a website with a non-root path. The top hosts are chain locators:
starbucks.com 102, locations.whataburger.com 76, mcdonalds.com 69, locations.pizzahut.com 48.

Of the 1,135 with a readable cached page, the page itself, judged with `trust_path=False`:

| Verdict | No other menu on the site | Another page verifies |
|---|---|---|
| not_menu | 664 | 213 |
| js_only | 123 | 105 |
| **verified** | **22** | 7 |
| http_200, not HTML | 1 | |

The 22 include two singleplatform pages, two chowbus and spoton ordering pages, Eggs Up Grill
and Flower Child location pages, and one printify product page (a false positive).

### 2.6 The named cases

- **Tex Mex Joe's (21459, `texmex.py`, two live fetches).** The homepage anchors are "Lunch" →
  `/lunch`, "Breakfast" → `/services3`, and "Drinks/Desserts/Starters/Kid's Menu" → `/blank`.
  Only `/blank` matched today's lexicon. With meal periods and 12 candidates, all three verify:
  6,338, 4,325 and 2,761 characters of text. `/lunch` ranks first.
  - The ChowNow link (`ordering.chownow.com/order/10074/locations`) is a platform page and
    unchanged.
- **Jefes (21183, `jefes.py`, one live fetch).** The website is
  `smorefood.com/order-online/jefes-mexican-restaurant-austin-78752-nn19mta8`.
  - It answers **429** with a 136-character Vercel Security Checkpoint ("We're verifying your
    browser").
  - The cached homepage outcome is also 429. The renderer skips 403/429 and challenge pages
    (`bot_challenge`).
  - The two other GERS records named Jefes use `jefesmex.com`, whose `/menu`, `/menus`,
    `/food` and `/our-menu` answer but do not verify.

### 2.7 The rule-withdrawn records (`an5.py`)

| Failure | Replay state | Records |
|---|---|---|
| wrong_place | only the wrong-place page verifies | 43 |
| wrong_place | homepage 404 / 429 / 500 | 3 / 2 / 1 |
| wrong_place | unfetched candidates | 3 |
| wrong_place | nothing verifies | 2 |
| wrong_place | the same URL verifies now (menudrive print page) | 1 |
| no_menu_found | nothing | 47 (+4 with a platform record) |
| no_menu_found | JavaScript-only candidates | 8 |
| no_menu_found | unfetched candidates | 3 |
| http_404 | homepage 404 / nothing | 9 / 3 |

Among the 43, `seasideonthepier.com` is the website of about 18 venues. Others are
another-city pages of a chain site that the Overture website points at the root of (Roaring
Fork Scottsdale, Paperboy Denver, Napa Flats College Station, Foodistaan Aubrey).

### 2.8 Cross-record baseline

Resolved menu-URL records per venue today:

| Own-site | Platform | Venues |
|---|---|---|
| — | 0 | 8,474 |
| — | 1 | 4 |
| yes | 0 | 1,491 |
| yes | 1 | 15 |
| yes | 2 | 8 |
| yes | 3 | 4 |

## 3. Limits

- Stratum A excludes the 917 venues whose homepage is not cached, and sites cached unreadable.
  The extrapolation assumes they behave like the readable ones.
- Verdicts use today's cached bytes for most first pages (fetched in October) and live bytes
  for the top-up (2026-10-27).
- The judge saw at most 3,500 characters per page (P48 shows the effect). Its sample is
  stratified by the metric, not uniform, hence the weighting.
- `place-v1` ran on every verified candidate. The 13 `wrong_place` candidates were not
  re-judged.

## Appendix: the 60 judged pairs

| Id | Metric class | Judge | B is | A → B |
|---|---|---|---|---|
| P00 | unpriced | overlap | same First Watch menu page with holiday seasonal section | `https://firstwatch.com/menu` → `firstwatch.com/menu?corp_id=7594&verison=core` |
| P01 | distinct<.3 | distinct_menu | family meals and to-go trays | `https://www.rosascafe.com/menu-dinner#Dinner` → `https://www.rosascafe.com/menu-family-meals` |
| P02 | dup>=.8 | overlap | Dayton location drinks menu with full drafts list | `https://www.pinsbar.com/menu` → `https://www.pinsbar.com/locations/dayton/menu` |
| P03 | dup>=.8 | distinct_menu | dinner menu | `www.blackwalnutcafe.com/menus/weekend-brunch/` → `https://www.blackwalnutcafe.com/menus/dinner/` |
| P04 | unpriced | overlap | burgers and sandwiches section of full menu | `https://hatcreekburgers.com/menu` → `https://hatcreekburgers.com/full-menu/burgers` |
| P05 | dup>=.8 | overlap | same coffee menu variant with chai, Dirty Harry, Mexican chocolate milk | `https://www.pepperboxcoffee.com/menu` → `epperboxcoffee.com/menu?menu=pepperbox-coffee` |
| P06 | partial.3-.8 | neither_menu | single product detail page (Milk Bar Birthday Cake Empanada) | `m/food/featured/steak-double-dipping-burritos` → `food/featured/milk-bar-birthday-cake-empanada` |
| P07 | partial.3-.8 | distinct_menu | drinks list | `https://amyschinacuisine.com/food-menu` → `https://amyschinacuisine.com/drink-menu` |
| P08 | partial.3-.8 | neither_menu | single product detail page (Milk Bar Birthday Cake Empanada) | `m/food/featured/steak-double-dipping-burritos` → `food/featured/milk-bar-birthday-cake-empanada` |
| P09 | partial.3-.8 | distinct_menu | brunch menu | `https://www.luckyrobotatx.com/drinks/` → `https://www.luckyrobotatx.com/brunch/` |
| P10 | distinct<.3 | b_not_menu | single product page (Steak Double Dipping Burritos) | `://www.tacobell.com/food/cantina-chicken-menu` → `m/food/featured/steak-double-dipping-burritos` |
| P11 | partial.3-.8 | neither_menu | single product detail page (empanada) | `m/food/featured/steak-double-dipping-burritos` → `food/featured/milk-bar-birthday-cake-empanada` |
| P12 | distinct<.3 | distinct_menu | rotating specials list | `https://moutonsbistro.com/breakfast-brunch/` → `https://moutonsbistro.com/specials/` |
| P13 | unpriced | overlap | meal plan menu (salads, wraps, bowls) | `https://www.musclemakergrill.com/menu` → `tps://www.musclemakergrill.com/meal-plan-menu` |
| P14 | distinct<.3 | b_not_menu | single product page (empanada) | `://www.tacobell.com/food/cantina-chicken-menu` → `food/featured/milk-bar-birthday-cake-empanada` |
| P15 | distinct<.3 | distinct_menu | catering menu | `ttps://hechoenmexico-restaurant.com/food-menu` → `https://hechoenmexico-restaurant.com/cater` |
| P16 | partial.3-.8 | overlap | Dallas location menu with different prices | `https://ishogun.com/menu` → `https://ishogun.com/menu-2` |
| P17 | unpriced | distinct_menu | drinks, beer, wine and cocktails | `n.com/kyle-steeple-chase-pizza-leon-food-menu` → `.com/kyle-steeple-chase-pizza-leon-drink-menu` |
| P18 | unpriced | duplicate | same full menu page via anchor URL | `https://hatcreekburgers.com/menu` → `://hatcreekburgers.com/full-menu#feed-a-crowd` |
| P19 | dup>=.8 | duplicate | same Saffron South menu without query string | `th.com/menus-1?menu=saffron-south-bee-cave-rd` → `https://www.saffronsouth.com/menus-1` |
| P20 | distinct<.3 | b_not_menu | single product page (Steak Double Dipping Burritos) | `://www.tacobell.com/food/cantina-chicken-menu` → `m/food/featured/steak-double-dipping-burritos` |
| P21 | distinct<.3 | b_not_menu | single product page (empanada) | `://www.tacobell.com/food/cantina-chicken-menu` → `food/featured/milk-bar-birthday-cake-empanada` |
| P22 | unpriced | b_not_menu | blog article on nutritious picks | `https://www.chick-fil-a.com/menu/breakfast` → `m/stories/9-nutritious-chick-fil-a-menu-picks` |
| P23 | partial.3-.8 | distinct_menu | drinks menu with frozens, margaritas, spirits | `https://conejostx.com/brunch-menu` → `https://conejostx.com/drink-menu` |
| P24 | distinct<.3 | distinct_menu | wine list | `r.com/leander-bella-sera-of-leander-food-menu` → `.com/leander-bella-sera-of-leander-drink-menu` |
| P25 | dup>=.8 | duplicate | same bakery menu via query-string URL | `https://www.bentobakes.com/menu` → `https://www.bentobakes.com/menu?menu=menu` |
| P26 | unpriced | distinct_menu | kids meals | `https://www.rosascafe.com/menu-dinner#Dinner` → `https://www.rosascafe.com/menu-kids` |
| P27 | dup>=.8 | duplicate | same Lunch/Dinner menu with section tabs | `https://www.carveamericangrille.com/menu/` → `https://www.carveamericangrille.com/menus/` |
| P28 | dup>=.8 | duplicate | same online ordering page (specialty entrees URL) | `ps://www.rice2goroundrock.com/order/main/menu` → `com/order/main/specialty-entrees/happy-family` |
| P29 | distinct<.3 | distinct_menu | Kyle bar menu (drinks) | `fe.com/austin-texican-cafe-manchaca-food-menu` → `fe.com/austin-texican-cafe-manchaca-menu-kyle` |
| P30 | partial.3-.8 | distinct_menu | drinks menu | `https://remedyaustin.com/food-menu` → `https://remedyaustin.com/drink-menu` |
| P31 | distinct<.3 | neither_menu | single dish detail page (Kalua Pork with Cabbage) | `s://www.hawaiianbarbecue.com/food/spam-saimin` → `iianbarbecue.com/food/kalua-pork-with-cabbage` |
| P32 | distinct<.3 | distinct_menu | food menu | `austin.com/austin-egg-roll-express-drink-menu` → `saustin.com/austin-egg-roll-express-food-menu` |
| P33 | unpriced | distinct_menu | brick oven pizza menu | `www.macaronigrill.com/menus/menu/dine-in/main` → `ww.macaronigrill.com/menus/menu/dine-in/pizza` |
| P34 | partial.3-.8 | distinct_menu | drinks menu | `ttps://hechoenmexico-restaurant.com/food-menu` → `tps://hechoenmexico-restaurant.com/drink-menu` |
| P35 | partial.3-.8 | neither_menu | single product detail page (empanada) | `m/food/featured/steak-double-dipping-burritos` → `food/featured/milk-bar-birthday-cake-empanada` |
| P36 | distinct<.3 | distinct_menu | drinks menu | `austin-dk-maria-s-legendary-tex-mex-food-menu` → `ustin-dk-maria-s-legendary-tex-mex-drink-menu` |
| P37 | distinct<.3 | distinct_menu | lunch and dinner menu | `https://moutonsbistro.com/breakfast-brunch/` → `https://moutonsbistro.com/lunch-dinner/` |
| P38 | dup>=.8 | overlap | daily smoothie specials and bundle deals | `https://www.juiceland.com/full-menu/` → `https://www.juiceland.com/specials/` |
| P39 | dup>=.8 | overlap | Dayton location menu with different beer list | `https://www.pinsbar.com/locations/austin/menu` → `https://www.pinsbar.com/locations/dayton/menu` |
| P40 | partial.3-.8 | overlap | online-ordering page with starters plus the same taco list | `brazastacohouseaustin.com/menu?menu=main-menu` → `www.brazastacohouseaustin.com/online-ordering` |
| P41 | unpriced | distinct_menu | hot drinks list | `tps://www.scooterscoffee.com/menu/iced-drinks` → `ttps://www.scooterscoffee.com/menu/hot-drinks` |
| P42 | dup>=.8 | overlap | daily smoothie specials and bundle deals | `https://www.juiceland.com/full-menu/` → `https://www.juiceland.com/specials/` |
| P43 | distinct<.3 | distinct_menu | cookies and pastries menu | `https://www.trckatreats.com/menu` → `https://www.trckatreats.com/copy-of-menu` |
| P44 | distinct<.3 | b_not_menu | single product page (Steak Double Dipping Burritos) | `://www.tacobell.com/food/cantina-chicken-menu` → `m/food/featured/steak-double-dipping-burritos` |
| P45 | unpriced | distinct_menu | regular food menu without prices | `00312&destination=catering&promotion=catering` → `https://dosbatos.com/food-menu` |
| P46 | dup>=.8 | duplicate | same food menu on menus hub with tabs | `https://www.pizzeriavetri.com/menu/` → `https://www.pizzeriavetri.com/menus/` |
| P47 | unpriced | b_not_menu | blog article of nutritious menu picks | `https://www.chick-fil-a.com/menu/breakfast` → `m/stories/9-nutritious-chick-fil-a-menu-picks` |
| P48 | dup>=.8 | distinct_menu | food menu | `https://thebrewtorium.com/menu` → `https://thebrewtorium.com/food` |
| P49 | dup>=.8 | duplicate | same menu via menu_id query | `https://rollinsmokeatxbbq.com/food-menu` → `llinsmokeatxbbq.com/food-menu?menu_id=1141354` |
| P50 | dup>=.8 | duplicate | same Halloween menu inside menus hub | `https://www.michellespatisserie.com/menu/` → `https://www.michellespatisserie.com/menus/` |
| P51 | unpriced | overlap | appetizers section of full menu | `https://www.manuels.com/menu` → `https://www.manuels.com/menu/appetizers` |
| P52 | partial.3-.8 | distinct_menu | full drinks menu | `https://www.luckyrobotatx.com/happy-hour/` → `https://www.luckyrobotatx.com/drinks/` |
| P53 | unpriced | duplicate | same menu, alternate rico-menu page | `https://www.pollosricos.com/menu` → `https://www.pollosricos.com/rico-menu` |
| P54 | partial.3-.8 | neither_menu | single product detail page (empanada) | `m/food/featured/steak-double-dipping-burritos` → `food/featured/milk-bar-birthday-cake-empanada` |
| P55 | unpriced | distinct_menu | happy hour offers | `https://www.pfchangs.com/menu` → `https://www.pfchangs.com/menu/happy-hour` |
| P56 | unpriced | distinct_menu | dinner menu | `://www.blackwalnutcafe.com/menus/spirit-menu/` → `https://www.blackwalnutcafe.com/menus/dinner/` |
| P57 | partial.3-.8 | overlap | weekday lunch menu | `https://www.roxiesbuda.com/menu` → `https://www.roxiesbuda.com/lunch-menu` |
| P58 | partial.3-.8 | distinct_menu | cold menu (sashimi, salads) | `https://tomosushiaustin.com/hot-menu/` → `https://tomosushiaustin.com/cold-menu/` |
| P59 | dup>=.8 | duplicate | same menu page without query string | `ceanaustin.com/menu-2?menu=pick-up-order-only` → `https://www.sushioceanaustin.com/menu-2` |
