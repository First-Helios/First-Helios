# Site data fixes: wrong-place menus and JSON-LD precedence (P8-18)

Session P8-18, 2026-10-27, from the owner's triage of firsthelios.com (venues 21183 Jefes and
8652 Carmen's Hideaway). This record holds the measurements; the proposals are
[ADR-0015 Amendment 2](../adr/0015-menu-url-reverification.md#amendment-2-2026-10-27-proposed-a-wrong-place-page-check)
(wrong-place check) and
[ADR-0006 Amendment 2](../adr/0006-gold-menu-read-models.md#amendment-2-2026-10-27-proposed-json-ld-precedence-per-dish)
(JSON-LD precedence). Both were proposed with owner questions, then **accepted 2026-10-27
with every question as recommended**, built and applied; §3 records the apply.

The measurements in §1 and §2 are read-only. They read `helios_laptop` (Alembic
`13081a087231`) and the stored bundles under the main checkout's `var/replay/menu-page`. For
them nothing was fetched, withdrawn, re-extracted or refreshed, and no model was called. Code:
`main` at bc22af0.

Artefacts are untracked, under `var/p8-18/` in this worktree:
- `dump_pages.py` → `pages.jsonl`: every `menu-page` record, its latest Version's bundle,
  its venue's Overture address and its stream heads;
- `places.py` → `places.jsonl`: every "City, ST [ZIP]" mention per page, with context;
- `check.py` → `flags.json` (rule v2) and `flags-v1.json`; `packets.py`, `packets/` (blind
  packets, `key.json`, the judges' `labels-*.jsonl`), `score.py`, `table.py`;
- `streams.py` → `streams.txt`: llm vs jsonld coverage.

## 1. Wrong-place menus

### 1.1 What the stored data holds

- 1,682 `menu-page` records: 1,597 with a live stream (1,445 llm only, 152 llm + jsonld) and
  85 already withdrawn.
- **Jefes (21183).** Overture gives the venue's own smorefood page as its website
  (`…/jefes-mexican-restaurant-austin-78752-nn19mta8`). Discovery read smorefood's sitemap and
  verified another restaurant's page (`…/best-food-in-town--smithville-galloway-08205/…`,
  `found_via` = the sitemap) with `classifier-v2`. The page text says "in Galloway, NJ" 25
  times. The classifier is right that it is a menu; nothing checks whose.
- **The metro is derivable from data.** The 10,014 Overture POIs in `helios_laptop` give 39
  localities with at least 3 POIs (Austin 6,743, Round Rock 637, Cedar Park 414 … Dale 12) and
  106 postcodes. No hand-made gazetteer is needed for the venue's own side.

### 1.2 The check (rule v2)

A page is **wrong-place** for its venue when it doesn't name the venue's metro and shows
evidence of another place. The full rule is in ADR-0015 Amendment 2. In short:

- **Place mentions** are "City, ST" or "City, ST 12345" (any US state code). A city in
  all-caps counts only with a ZIP ("SEAFOOD, OR EGGS" is not Oregon). A mention followed by "!"
  or a lower-case word ("Aloha, NY! Pizza", "Buffalo, TX hot") is a name, not a place.
- **Foreign**: the ZIP is outside the metro's postcodes; or the state isn't the venue's; or
  the place is in the venue's state but contains no metro locality ("Downtown Austin, TX" is
  metro, "Southlake, TX" is not).
- **Metro named**: the venue's own locality anywhere on the page or in the URL path, a metro
  locality written "City, TX", or a metro ZIP.
- **Evidence:**
  - **E1 `url_place`**: the URL path names a foreign place, i.e. a foreign ZIP closing a slug
    (`galloway-08205/`) or a token run equal to a foreign city from the gazetteer
    (`las-vegas`, `new-york`, `southlake`, `college-station`);
  - **E2 `address`**: a foreign "City, ST 12345" on a page naming at most two foreign places
    with a ZIP. A chain page is exempt: one menu URL saved for at least 2 metro venues whose
    names share their first word. On such a page a lone out-of-town address is the head
    office;
  - **E3 `dominant`**: one foreign place, outside chrome and wine sections, named at least
    twice, on a page with at most two foreign places outside chrome.
- **Decision**: flag when the metro is not named and any evidence holds; or when E1 holds and
  the URL path does not name the metro, even if the page does. The second case is another
  location's page of a chain whose location list includes Austin (archerhotel `/new-york/`,
  roaringfork `/scottsdale-event-menus`, eatpaperboy `/paperboy-denver`).
- **Exclusions, by construction.** A wine list's appellations ("Napa Valley, CA") and a beer
  list's brewery towns are many distinct places, so they fail E2/E3's "at most two". Chain
  location lists sit in chrome, so they are not E3. A location list that includes the metro
  makes the page name the metro.

**Gazetteer for E1.** Two variants were measured:
- `page`: only the foreign places this page itself names;
- `corpus`: the foreign places named on any stored menu page. Most come from chains' chrome
  location lists; 285 slugs.

`corpus` adds 4 URLs, all judged WRONG: tiltedkilt `las-vegas`, firepitatl `atlanta`,
thecheesybite `richmond-tx-…`, haywire `memorial-city-houston` (already withdrawn). `page`
adds none.

### 1.3 Flags

| Rule | Records | URLs | Live records |
|---|---|---|---|
| v1 (before the two refinements) | 79 | 43 | 72 |
| **v2, corpus gazetteer** | **59** | **39** | **54** |
| v2, page gazetteer | 55 | 35 | 51 |

On `helios_laptop`, the 54 live flagged records carry **2,503 of Gold's 60,119
`current_menu` rows** (49 records have rows).

### 1.4 Precision (blind judging)

- **Packets:** every v1-flagged URL (43) plus 60 unflagged live URLs. The unflagged ones were
  30 drawn from the 145 that name some other place and 30 from the 735 that name none (seed
  20261026). All 103 were shuffled into 4 batches.
- **Judging:** 4 Sonnet subagents, flag hidden. Each packet gives the venue's name and
  address, the saved menu URL and the page text (chrome and heading marks; place, phone and
  ZIP lines with neighbours). Labels: `RIGHT` (the venue's own menu, or a chain-wide menu that
  applies), `WRONG` (another business, or another location's page), `UNSURE`, `NOT_MENU`.
- **Main-session re-check:** I re-read every disagreement and the doubtful WRONGs against the
  bundles. I agree with all of them. Jerusalem Grill is the Stone Oak, San Antonio page.
  Little Woodrow's "Buffalo, TX hot" is a wing flavour. Fabaceae's footer says Houston 77025
  with a 512 phone. Cane Rosso lists only Dallas-area neighbourhoods.

**v1 → v2.** The 7 RIGHT among v1's flags were:
- Krispy Krunchy (9 records), Zenshi (8), Sarpino's (2 URLs), Twin Peaks (2): head-office
  addresses on chain pages;
- Grimaldi's "Aloha, NY! Pizza" and Little Woodrow's: dish and flavour names.

The two v2 refinements remove Krispy Krunchy, Zenshi, Grimaldi's and Little Woodrow's, and add
nothing. v2 is therefore tuned on these labels. Every v2 flag was judged, so its precision
below is a census of this corpus, not an estimate for new pages.

| v2 flags (corpus gazetteer) | WRONG | UNSURE | NOT_MENU | RIGHT | Precision |
|---|---|---|---|---|---|
| URLs (39) | 34 | 1 | 1 | 3 | 0.872 (0.919 without UNSURE/NOT_MENU) |
| Live records (54) | 52 | 1 | 0 | 1 | **0.963** |

The remaining non-WRONG flags:
- Sarpino's `…/new-york-deli-pizza`, live, RIGHT: a dish page whose URL names New York, with
  the Lincolnshire, IL head office. It is a separate URL from Sarpino's `/menu`, so the chain
  exemption doesn't apply;
- Fabaceae, live, UNSURE;
- Sarpino's `/menu` and Twin Peaks (RIGHT) and Woof Gang (NOT_MENU): already withdrawn.

**Recall.** Of the 60 unflagged, 1 is WRONG (canerosso.com/menu). Its location list names
Dallas neighbourhoods ("North Dallas") and no "City, ST", so the rule cannot see it. By
stratum:
- 1/30 of the 145 URLs naming another place, i.e. about 5 missed;
- 0/30 of the 735 naming none. The 95 % upper bound by the rule of three is about 10 %
  (≤ 73), a weak bound.

Two unflagged packets were judged NOT_MENU. They are a classifier matter, outside this check.

**Not caught, by design.** Paul Martin's `holiday-menu-2015` is a stale seasonal menu: its
place is right, its date is wrong. This check doesn't look at dates.

### 1.5 The flagged list (v2, corpus gazetteer)

"Live" is records with a live stream over records flagged. Evidence names are §1.2's; "+ metro
named" means E1 alone flagged a page that names Austin.

| Menu URL | Venues (ids) | Live | Evidence | Judge | Place on page |
|---|---|---|---|---|---|
| `http://places.singleplatform.com/food/menu` | Be More Pacific (25182, 8322, 420) | 3/3 | address; dominant | WRONG | Los Angeles, CA |
| `https://abarestaurants.com/nashville/menus` | Aba Austin (7458) | 1/1 | address; url_place | WRONG | Nashville, TN |
| `https://archerhotel.com/new-york/menus/lunch-special` | Second Bar and Kitchen (24018) | 1/1 | address; url_place + metro named | WRONG | New York, NY |
| `https://firepitatl.com/atlanta-grant-park-firepit-pizza-tavern-menus` | Firepit Inc (21162) | 1/1 | url_place | WRONG | Atlanta, GA |
| `https://laspalmasep.com/food_menus/breakfast-menu/` | Las Palmas Mexican Restaurant (8880) | 1/1 | address | WRONG | El Paso, TX |
| `https://napaflats.com/college-station-menu` | Napa Flats Wood-Fired Kitchen (17940) | 1/1 | url_place | WRONG | College Station, TX |
| `https://order.menudrive.com/storefront/menus?template=print` | Sun City Flauta (20163) | 1/1 | address | WRONG | Allen, TX (another restaurant) |
| `https://seasideonthepier.com/menu/` | Barstool Bites and 17 other virtual brands (1347, 22380, 12324, 2619 +14) | 18/18 | address | WRONG | Santa Monica, CA |
| `https://thecheesybite.com/richmond-tx-near-grand-pkwy-99-hwy-90/menu/shawarma` | Cheesy Bite Austin (26268) | 1/1 | url_place | WRONG | Richmond, TX |
| `https://tiltedkilt.com/menu/las-vegas-menuxx` | Tilted Kilt (29520) | 1/1 | url_place | WRONG | Las Vegas, NV |
| `https://tokyosteakhouseinc.com/happy-hour-menu.php` | Tokyo Steak House and Sushi Bar (26334) | 1/1 | address | WRONG | Sacramento, CA |
| `https://www.arthuravepizza.com/menu/` | Bsdb Restaurant Llc (1290) | 1/1 | address | WRONG | Milford, PA |
| `https://www.brioitalian.com/menu/dinner/southlake` | Brio Tuscan Grille (18993) | 1/1 | url_place | WRONG | Southlake, TX |
| `https://www.chinaonelivingston.com/nnv2mta8/restaurant/menu` | China One (28878) | 1/1 | address; dominant | WRONG | Livingston, LA |
| `https://www.cielitolindo.org/menu` | Cielito Lindo Austin (9414) | 1/1 | address | WRONG | Los Angeles, CA |
| `https://www.eatpaperboy.com/paperboy-denver` | Paperboy East (11079) | 1/1 | address; url_place + metro named | WRONG | Denver, CO |
| `https://www.elpaisa.com/menus` | El Paisa (5883) | 1/1 | address | WRONG | Central Falls, RI |
| `https://www.eltapatiotaqueria.com/menu-hunter` | El Tapatio (5730) | 1/1 | address | WRONG | Houston, TX |
| `https://www.foodistaan.us/aubrey/menu` | Foodistaan (16371) | 1/1 | address; url_place | WRONG | Aubrey, TX |
| `https://www.ginoseast.com/comedy-bar-menu/` | Gino's East (10116) | 1/1 | address | WRONG | Chicago, IL |
| `https://www.haywirerestaurant.com/menu/memorial-city-houston/lunch` | Haywire (23691) | 0/1 | url_place | WRONG | Houston, TX |
| `https://www.hongkongharvard.com/new-page-1` | Hong Kong Restaurant (20076) | 1/1 | address | WRONG | Cambridge, MA |
| `https://www.jds-smokehouse.com/menu` | J C's Smokehouse (14976) | 1/1 | address | WRONG | Lenoir, NC |
| `https://www.jerusalemgrill.net/menu/` | Jerusalem Grill (18528) | 1/1 | address | WRONG | San Antonio, TX |
| `https://www.losmayasmexicanrestaurant.com/menu` | Amayas Mexican Restaurant (20766) | 1/1 | address; dominant | WRONG | Billings, MT |
| `https://www.magicwok.com/menu` | Magic Wok (14241) | 1/1 | address | WRONG | Toledo, OH |
| `https://www.majortomato.com/menu-1` | Mr. Tomato (17619) | 1/1 | address | WRONG | Allen Park, MI |
| `https://www.markerthirtyseven.com/menu/` | Marker 37 Llc (3501) | 1/1 | address | WRONG | Chester, CT |
| `https://www.masonslobster.com/locations/rehoboth-food-truck/` | Mason's Famous Lobster Rolls (9681) | 1/1 | address | WRONG | Rehoboth Beach, DE |
| `https://www.paparazzi-pizza.com/menu/` | Papparazzi Pizzaria (9135) | 1/1 | address | WRONG | Carrollton, TX |
| `https://www.phovanrestaurant.com/menu` | Pho Van (22407) | 1/1 | address | WRONG | Beaverton, OR |
| `https://www.roaringfork.com/scottsdale-event-menus` | Roaring Fork (10242) | 1/1 | address; url_place + metro named | WRONG | Scottsdale, AZ |
| `https://www.smorefood.com/mo0r1opc/best-food-in-town--smithville-galloway-08205/order-online` | Jefes (21183) | 1/1 | address; dominant; url_place | WRONG | Galloway, NJ |
| `https://www.thewildtaco.com/menu` | Wild Taco (11664) | 1/1 | address | WRONG | Newport Beach, CA |
| `https://www.fabaceaecuisine.com/menu` | Fabaceae African Cuisine (25329) | 1/1 | address | UNSURE | Houston 77025 footer, 512 phone |
| `https://woofgangbakery.com/pages/nutritious-pet-food` | Urban Dog Home Grooming (11721) | 0/1 | address | NOT_MENU | (a pet-food page) |
| `https://twinpeaksrestaurant.com/menu` | Twin Peaks (4821, 2334) | 0/2 | address | RIGHT | chain-wide |
| `https://www.gosarpinos.com/menu` | Sarpino's Austin - Pflugerville (24576) | 0/1 | address | RIGHT | chain-wide |
| `https://www.gosarpinos.com/menu/sarpinos-specialty-pizza/new-york-deli-pizza` | Sarpinos Pizza (24555) | 1/1 | address; url_place | RIGHT | chain-wide |

P8-17's sweep named seven examples beside smorefood. Six are flagged: archerhotel,
tiltedkilt, roaringfork, chinaonelivingston, phovan and losmayas. The seventh,
paulmartinsamericangrill `holiday-menu-2015`, is right-place and stale (§1.4).

## 2. JSON-LD precedence

### 2.1 Why Carmen's Hideaway shows dishes twice

Both streams of one page share one family (`root_key = page`; all 152 two-stream records).
In current mode every live stream head of the subject is enumerated. The selector's
`jsonld > dom > pdf > llm` rank only decides between claims on the **same target path**, and
the two streams key their dishes differently (jsonld native keys vs llm block keys). So both
are enumerated, and Gold holds a jsonld row and an llm row for the same dish.

Carmen's Hideaway (record 21443, `tamalehouseeast.com/menu/`, Organization 8650): llm 87 items
(85 priced), jsonld 75 (73 priced). In Gold that is 50 llm rows and 73 jsonld rows. The 16
priced llm items with no jsonld name ("Egg", "Potato", "Bacon & Avocado" …) are mostly
`split_listed` fragments of "Egg, Bacon, Cheese & Ranchera" (P8-19's title-slot veto).

### 2.2 Coverage on `helios_laptop`

The 152 records with both live streams are on 90 distinct URLs. Items are `replace` items. An
item is "priced" when it or one of its variants has an observed amount. Names are matched on
the validator's `norm_tokens` set: NFKC, lower case, "&" → "and", words, order-free.

| | llm | jsonld |
|---|---|---|
| Items | 15,043 | 8,617 |
| Priced items | 8,914 | 5,421 |
| Items with no same-name item in the other stream | 7,948 (3,953 priced) | 1,616 |
| Gold `current_menu` rows | 5,543 | 4,601 |

- **JSON-LD covers less than the LLM on 73 of 152 records** (fewer priced items), and 66
  records' jsonld stream has **no price at all**. Kerbey Lane Cafe (10 records): jsonld 2
  items and 0 prices, llm 156 priced. So the fork applies.
- **The duplicates are real.** Of 4,118 dish names priced in both streams, 4,031 (97.9 %)
  carry the same price set, 74 overlap and 13 disagree.

### 2.3 Options, sized

Priced item rows shown on the 152 records. Gold enumerates priced targets only, so this is
the Gold-row proxy.

| Option | Priced rows | Notes |
|---|---|---|
| Today (every stream head) | 14,335 | 4,701 of them llm duplicates of a priced jsonld dish |
| (a) Whole page: jsonld wins whenever its head is live | 5,421 | 36 records lose every price |
| **(b) Per dish: a priced jsonld dish wins; llm's other dishes stay** | **9,634** | about 326 near-duplicates remain (same price, name overlap ≥ 0.5, not equal) |
| (c) jsonld when it has at least as many priced dishes, else llm | 8,972 | jsonld on 79 records |
| (d) Whole page when jsonld has any price, else llm | 7,840 | jsonld on 86 records; loses 1,794 llm-only priced dishes there |

For Carmen's, (a)/(d) show the clean 73 jsonld rows; (b) shows 73 + the 16 llm fragments
until P8-19 lands; (c) shows llm (85) with the fragments.

## 3. Owner decision, build and apply (2026-10-27)

The owner accepted both amendments with every question as recommended. Both are built, in
the same PR (build notes in the ADRs).

**Applied to `helios_laptop`:**
- **Backup:** `pg_dump` `var/laptop-run/helios_laptop-2026-10-27-pre-p8-18.dump` (main
  checkout; sha256 67b43b27…).
- **Sweep:** `python -m apps.discovery.place_sweep`. The dry run and the live run flagged the
  same 55 keys, and the live run withdrew all 55:
  - menu-URL `needs_review` went 74 → 129;
  - 1,602 pages were checked; 74 not resolved and 6 older-URL bundles were skipped.
- **Rescore:** `python -m apps.menu_pipeline.rescore` (R4) withdrew the streams of 54 records
  (`menu_url_withdrawn`): 54 llm and 21 jsonld pages. Sarpino's `/menu` was already withdrawn.
  No page was due.
- **Gold:** `python -m apps.gold.refresh` (7 m 54 s, effective 2026-10-27T03:38:50Z):

  | | Before | After |
  |---|---|---|
  | `current_menu` rows | 60,119 | **56,194** |
  | `price_index` rows | 352 | 341 |

  - The flagged records now carry 0 rows; before, 2,503. So about 1,422 rows went to the
    per-dish rule. That is derived, since nothing else changed in the run.
  - On the 131 two-stream records still live: 4,101 llm and 3,811 jsonld rows.
  - Carmen's Hideaway: 73 jsonld rows plus 18 llm rows. The llm rows are the `split_listed`
    fragments ("Egg", "Potato" …) and four dishes its JSON-LD lacks (Enchiladas, Tamales,
    Chips & Guacamole, Veggie Compuesto).

**Pi.**
- **Backup:** `~/helios-backups/firsthelios-20261027-p8-18-08bb684/`
  (`pi-helios-pre.dump` sha256 ecbd3a25…, code tgz).
- **Restore:** the database was restored from the laptop dump (sha256 f52fc41c…). Backend code
  is unchanged at 08bb684, since nothing in the build touches the schema (13081a087231). The
  restore was clean, with 56,194 / 341 rows and 178 s of downtime. `/healthz`, `/readyz` and
  `/v1/venues` all return 200.

**firsthelios.com, checked publicly.**
- `GET /v1/venues/21183/menu` (Jefes) returns `menus: []`: the Galloway, NJ menu is gone.
- `GET /v1/venues/8652/menu` (Carmen's) returns one menu of 91 items, with no cross-stream
  duplicates. Some names still repeat:
  - "Egg" ×3 and "Potato" ×2 are the llm `split_listed` fragments (P8-19);
  - "Sliced Avocado" and "Tiny Guacamole" are listed by the page's own JSON-LD under both
    Breakfast Sides and Lunch & Dinner Sides.

## 4. Doc drift noticed

- The P8-18 brief says PR #134 is merged; it is **open** (as is #133).
- README's ADR table still says ADR-0021 is "Proposed (P8-17; owner Q1–Q7 open)". It was
  accepted (Q1–Q8), with the decisions in #134.
