# Menu section structure: where it is lost, and a post-hoc fix (ADR-0013 Amendment 28)

Session P8-11, 2026-10-24. The owner found six menu-structure misses while exploring the local
site. This record traces each one to the stage that lost it, sizes the problem over the stored
corpus, and proposes [ADR-0013 Amendment 28](../adr/0013-phase5-menu-pipeline.md#amendment-28-2026-10-24-proposed-stage-5c-section-assignment-from-page-structure).

Scope:
- diagnosis and proposal only. No pipeline code changes, no re-extraction, no model call;
- `helios_laptop` (alembic head `13081a087231`) was read only, through `set transaction read
  only` sessions. Nothing was written to Bronze, Menu, Gold or identity;
- no site was re-fetched. Every page was read from its stored bundle. The one page that has no
  bundle (Bottega's image menu) was read from the 7-day discovery cache;
- no schema, migration, dependency, model, Pi or `infra/` change;
- no per-site, per-platform or hand-entered rule. Every rule below is generic.

**Result.** All six losses are confirmed. Four of the five section misses come from one
mechanism: segment-v2 keeps only a yes/no `heading` flag, so a dish name in an `h3` looks like
a section heading. The chunker then names that dish as the "heading" in the next chunk's
context line, and the model files the following dishes under it. The fifth miss (Los Mayas) is
the model ignoring a heading inside a chunk. The page's own DOM assigns the right section in
every reported case.

Over the corpus:
- 38 % of named sections are a dish's name;
- on 714 already-labelled pages, today's section accuracy is **0.438**;
- a post-hoc assignment from the DOM (option b) raises it to **0.704** overall and to
  **0.875** on the 412 pages it applies to (165 pages better, 7 worse);
- it changes no row, price, segmenter output, `text_hash` or Evidence locator, and needs no
  model call.

| # | Case | Stage where it was lost | Fixed by (b) | Fixed by (a) |
|---|---|---|---|---|
| 1 | Los Mayas: Street Taco and 5 other sides under DINNERS; BURRITOS, MEXICAN SPECIALS, KIDS SPECIALS missing (28 of 94 items) | [4] model output: headings inside a chunk ignored; the context line carries the previous heading | yes, all 28 | not reliably (model behaviour) |
| 2 | Veracruz (Toast): "Pineapple" and "Shrimp Taco" as sections | [3] chunk context line, fed by [2] segment-v2's boolean `heading` (item `h3` = heading) | yes (54 of 100 items move) | yes, if the context names the group heading |
| 2b | Veracruz: Cantaloupe and other Aguas Frescas missing | [4] model recall in chunk 0 | no (not a section loss) | no |
| 3 | Vivo: "California Nachos" as a section | [3] chunk context (item `h3`) | yes (69 of 102) | yes |
| 4 | Barstool Bites: "Chicken Caesar*" as a section | [3] chunk context (item `h3`) | yes (10 of 42) | yes |
| 5 | Que Divino: BYO Taco under "Picadillo Con Papa"; options not variants/modifiers | section: [3]. Options: [4] prompt/grammar contract (no modifier slot; "skip add-on lines"), shape and writer have no modifiers | section yes; options no (separate change) | section yes; options no |
| 6 | Bottega: drinks only in images | content in images (§9 out of scope); discovery picked `/plain-text-menu` | n/a (plan only) | n/a |

## 1. Method

Read-only tools (untracked, `var/p8-11/` in the worktree):
- `rich.py` re-runs the production parser (`segment._Segmenter`) on the bundle's HTML and also
  records each block's ancestor stack (tag, class/id), node ids and `h` level. It asserts that
  the blocks are identical to segment-v2's. The assertion held for **all 863 page texts** in
  the corpus.
- `trace.py` takes one page through every stage: blocks, chunks, the saved raw answers
  (`OutputStore` key `qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2`),
  `rows_of`, `judge` and `shape`.
- `domsec.py` is the option (b) prototype (section 4).
- `sweep.py`, `analyse.py`, `audit.py`, `labelled.py`, `mech.py`, `opts.py`, `imgsweep.py` and
  `svc.py` produce the corpus numbers.

**The replay is what production stored.** Replaying saved answers through `rows_of`, `judge`
and `shape` gives **61,644 items, the stored Menu total exactly**. Spot checks against
`menu.menu_item` and `gold.current_menu` agree for every reported item. Examples:
- Los Mayas "Street Taco" → `DINNERS`;
- Veracruz "Orange" → `Pineapple`;
- Barstool "Citrus Kale" → `Chicken Caesar`.

Corpus: the 1,597 published `llm` heads on `helios_laptop`, of which 1,568 have items. They
come from **863 distinct page texts**; 23 of them were rendered. All have bundles.

## 2. The six cases

Block ids are segment-v2 ids in each page's bundle (`var/replay/menu-page/2026/10/<sha>.json.gz`).

### Case 1: Los Mayas Mexican Restaurant (`losmayasmexicanrestaurant.com/menu`, record 21479, bundle `f45c24a4…`)

- **DOM.** Every category is a `div.menuCategory` holding `h3.menuCategroyTitle` and its items
  (`div.menuItemName`). This is a clean, wrapped outline:
  - STARTERS b0017
  - LUNCH SPECIALS b0030
  - DAILY HOUSE SPECIALS b0045
  - BURRITOS b0061
  - MEXICAN SPECIALS b0077
  - FLAUTAS AND SUCH b0113
  - KIDS SPECIALS b0138
  - AMERICAN FOOD b0147
  - DINNERS b0160
  - SIDES b0221
  - DESSERTS b0250
  - DRINKS b0259
- **Segmenter and chunks.** All headings are flagged. Chunk 5 starts at b0221 `SIDES`, with
  the context line `heading: 'DINNERS (Available All Day Served With Beans & Rice)'`.
- **Model output** (chunk 5): section `DINNERS` with Taco b0232, Street Taco b0236, Quesa Birria
  Taco b0243, Birria Taco b0245, Zurachi b0246 and Sopes b0248. Then section `SIDES` with only
  b0222–b0230.
  - Chunk 1 (b0061–b0100) keeps `DAILY HOUSE SPECIALS` for the BURRITOS and MEXICAN SPECIALS
    items.
  - Chunk 3 (b0132–b0179) files the KIDS SPECIALS items (Mini Pollo b0139, Mini Taquitos,
    Nino Quesadilla) under `FLAUTAS AND SUCH`.
- **Shape** grounds `DINNERS` on b0160, so the sides are stored under DINNERS (Gold `s6`).
- **Stage: [4] model output.** The headings are in the chunk, and the model kept the previous
  section. 28 of 94 items are wrong. LUNCH SPECIALS is right (5 items).
- **(b)** puts all 28 under the enclosing `h3` (Street Taco → SIDES, Mini Pollo → KIDS
  SPECIALS, …).

### Case 2: Veracruz Fonda and Bar (Toast, rendered, record 23260, bundle `188863e2…`)

- **DOM.**
  - Menus are `h2`: Juice Bar & Coffee, SWEET BREADS, Breakfast, Tacos Lunch, Lunch & Dinner.
  - Groups are `h3.menuGroup-<uuid>-heading` in `div.headerWrapper`: Aguas Frescas b0043,
    Refrescos b0067, Tacos b0181, Botanas (Copy) b0215, Desserts b0226, ….
  - Dishes are also `h3`, in `li.item > div.itemHeader`: Pineapple b0055, Shrimp Taco b0208.
- **Segmenter.** segment-v2 marks all of these `heading=True`. Level and class are dropped.
- **Chunks.**
  - Chunk 1 starts at b0057 with `heading: 'Pineapple'` (the dish at b0055).
  - Chunk 7 starts at b0211 with `heading: 'Shrimp Taco'` (the dish at b0208).
- **Model.**
  - `SECTION 'Pineapple'`: Orange, Jamaica, Cucumber, Atole Agua Fresca, Limon, Refrescos,
    MEXICAN COKE.
  - `SECTION 'Shrimp Taco'`: Steak Taco, Botanas, Shrimp Ceviche, Totopos ×2, every dessert,
    Quesadillas.
  - Shape grounds both on the dish blocks.
- **Stage: [3] chunk context.** The chunker picks the last block with `heading=True`, which can
  only be wrong because [2] lost the heading level and class.
- **Missing Aguas Frescas items: [4] recall.** Chunk 0 covers b0001–b0056. Its answer holds
  only the Aguas Frescas description row (b0043→b0044). Watermelon b0045, Horchata b0047,
  Strawberry b0049, Mango b0051, Cantaloupe b0053 and Pineapple b0055 were never emitted.
- **(b)** moves 54 of 100 items:
  - Orange … MEXICAN COKE → Aguas Frescas / Refrescos;
  - Steak Taco → Tacos (menu: Tacos Lunch);
  - Shrimp Ceviche and Totopos → Botanas (Copy) (Lunch & Dinner);
  - the desserts → Desserts (Lunch & Dinner).

  The dish "Shrimp Taco" itself sits under Tacos Lunch › Tacos in the DOM. What belongs under
  Lunch & Dinner is the content of the false "Shrimp Taco" section. Cantaloupe stays missing,
  because (b) cannot add an item.

### Case 3: Vivo (`vivoaustin.com/austin-vivo-food-menu`, record 20402, bundle `5c78e296…`)

- **DOM.** Sections are `h2` in `section > div.food-menu-grid-item-content` (Appetizers b0031).
  Dishes are `h3` in `div.food-item-title` (California Nachos b0053, Macho Nachos b0057).
- **Chunks and model.** Chunk 1 starts at b0057 with `heading: 'California Nachos'`. The model
  outputs `SECTION 'California Nachos'` holding Macho Nachos (½ order / Full order), Veggie
  Chalupa, Chalupa Tingas and two descriptions.
- **Stage: [3].** The same mechanism recurs through the page: sections named "Puffy Taco
  Plate", "Beef Enchiladas", "Mole Enchiladas", "Emma's Choice" and so on.
- **(b)** moves 69 of 102 items:
  - Macho Nachos → Appetizers;
  - the taco plates → Tacos;
  - the enchiladas → Mains / Lunch;
  - HH Machos Nachos → Happy Hour (today: Tacos).

### Case 4: Barstool Bites (500 E 51st St, org 20347, record 20334, menu URL `seasideonthepier.com/menu/`, bundle `4797e5cb…`)

- **DOM.** Each section is a `section.wp-block-group` holding an `h2.wp-block-heading`
  (Salads b0038). Dishes are `h3.wp-block-heading` (Chicken Caesar* b0039).
- **Chunks and model.** Chunk 1 starts at b0042 with `heading: 'Chicken Caesar*'`, giving
  `SECTION 'Chicken Caesar*'` = Citrus Kale, Baja Chicken. The same happens for "Lobster BLT"
  (holds Burgers…), "Pepperoni" (Supreme), "Fish Tacos" (Catch of the Day) and "Chicken
  Alfredo".
- **Stage: [3].** (b) moves 10 of 42 items (Citrus Kale, Baja Chicken → Salads, …).
- The page's `jsonld` stream already has Citrus Kale under `Salads`. Gold serves both streams.
- **Side finding, not in scope.** The venue's menu URL is another restaurant's site
  (`seasideonthepier.com`). This looks like a website/identity issue (ADR-0010) to check
  separately.

### Case 5: Que Divino Cocina & Catering (record 20358, bundle `0ceba639…`)

- **DOM.**
  - b0043 `h2` "Build Your Own Taco" (section, `div.food-menu-grid-item-content`);
  - b0044 `h3` "Build Your Own Taco" (dish);
  - b0045 `$2.99/+`;
  - b0046 (description): `BYO Taco - 2 Items $2.99 | BYO Taco -3 Items $3.45 | BYO Taco - 4
    Items $3.95 | BYO Taco - 5 Items $4.40 • BYO items choice: Egg | Refried Beans | Sausage |
    Ham | Sauteed Mushrooms | Bacon | Seasoned Potatos | Chorizo | Pico De Gallo | Cheese.`
- **Section: [3].** Chunk 1 starts at b0043 with `heading: 'Picadillo Con Papa- a La Carta'`
  (a dish). (b) assigns `Build Your Own Taco`.
- **Options: [4] contract.** The model emits one row, b0043 "Build Your Own Taco" 2.99, variant
  "+" (repairs step 2 drops it, since it has no letters). The four count prices in b0046 and the
  choice list are never emitted. Every later stage lacks a place for them:
  - prompt-v2.4 asks for one entry per price but also says "skip … add-on/extra lines";
  - the grammar has no modifier slot;
  - `menu_shape` has no modifier node;
  - **no `menu.menu_modifier` row exists for any page**.

  Section assignment cannot fix this. It needs its own change (section 7).

### Case 6: Bottega (record 20805)

- **What was extracted.** Discovery chose `https://www.bottegaatx.com/plain-text-menu` (found
  via the sitemap). That page prints 7 specialty drinks and 4 foods as `<p>` lines, and all 11
  were extracted.
  - Side defect: the names keep the price ("Salted Caramel Latte — 6.50").
- **`/menu` is not in Bronze.** There is no Capture and no bundle. It was not re-fetched.
- **The discovery cache copy** (`var/site-cache/f13d18fa…`, HTTP 200, 192 KB) segments to one
  body block ("0") plus 6 content images. Two of them are 2304×3456 with alt "Menu with
  various coffee drinks and brea…" and "Coffee shop menu with drinks and prices…".
- The alt text does not reach any block. Why was not investigated; the images likely sit in a
  skipped container.
- **Stage:** content in images (ADR-0013 §9, out of scope). Plan in section 8.

## 3. The mechanism, corpus-wide

Over 863 page texts and 59,289 kept items (counted once per name block):
- **58.1 % of pages (501)** have at least one continuation chunk whose context-line "heading" is
  a dish's name block: 2,359 of 5,417 continuation chunks.
- **3,003 of 7,934 named sections (37.8 %)** are grounded on a dish's name block that is not a
  DOM section heading. They hold 12,382 items on 483 pages.
- 7,278 items on 445 pages are `Unsectioned`, because the model's section name was not printed
  above them.
- `service_period` is null on all 2,142 `menu_applicability` rows. Time-of-day headings exist
  either way: 215 pages by today's sections, 170 by the DOM outline. Examples are "LUNCH
  SPECIALS", "Happy Hour" and Toast's "Tacos Lunch".

## 4. Option (b) prototype: DOM section assignment

`var/p8-11/domsec.py`. It runs per page on the re-parsed DOM and the kept items' name blocks:
1. **Candidate headings.** Non-chrome, unpriced, with letters:
   - the first block of an `h1`–`h6` element (≤160 chars);
   - or a block whose own element classes contain category / section / group / heading /
     header / title, and none of item / product / dish / price / desc / btn / nav / link /
     logo / page / site / hero / banner / footer (≤80 chars). Instance ids such as
     `section-3eeb5dad-…` don't count (r3).
2. **Layout signature.** The last three block-level ancestors (tag + first class, with uuids
   and digits masked).
3. **Section style.** A signature is a section style when at least half its headings, and at
   least two (r2), enclose an extracted item name of another signature before the next heading
   of the same signature.
   - This tells Toast's group `h3` from its dish `h3`.
   - It drops a lone page title, location or welcome heading.
   - It does not depend on which headings the model wrongly emitted as items.
4. **Assignment.** An item's section is the nearest preceding section-style heading. Its
   outline parents are the earlier section-style `h` headings of a lower level, for example
   Toast's "Lunch & Dinner" over "Desserts".
5. **Page gate.** At least 90 % of the page's kept items are assigned, and either at least 95 %
   of assignments are *wrapped* or all assigned headings share one style. *Wrapped* means the
   lowest common ancestor of the heading and the item holds no other heading of that style.
6. Gated pages take the DOM section for every assigned item; unassigned items keep today's.
   Other pages are unchanged.

The rules were tuned on two audit samples and on the labelled pages (section 6), so all three
are now *dev* data for section assignment. Rules tried and dropped:
- tag-only headings (missed Squarespace's `div.menu-section-title`);
- a majority rule for dish signatures (failed when the model emitted most section headings as
  items, as on uchi);
- "heading texts must be distinct" (r4). This hurt, because lunch and dinner tabs legitimately
  repeat "Appetizers".

## 5. How much clean structure exists, and how often today disagrees

Production corpus, class mode with r2 and r3 (`var/p8-11/analyse.txt`):

| Tier | Pages | % | Items | % items |
|---|---|---|---|---|
| A: every item assigned, ≥95 % wrapped | 228 | 26.4 % | 22,386 | 37.8 % |
| B: every item assigned, one heading style | 165 | 19.1 % | 9,473 | 16.0 % |
| C: every item assigned, mixed styles | 75 | 8.7 % | 7,314 | 12.3 % |
| D: ≥90 % assigned | 102 | 11.8 % | 7,968 | 13.4 % |
| E: partly assigned | 38 | 4.4 % | 2,193 | 3.7 % |
| F: no section structure | 255 | 29.5 % | 9,955 | 16.8 % |

- **Unambiguous for every item (A+B):** 393 pages (45.5 %), 31,859 items (53.7 %).
- **The proposed gate (section 4, item 5):** 469 pages (54.3 %), 747 of 1,568 venue records,
  37,988 items (64.1 %). Of those items:
  - 21,635 (57 %) would change section;
  - 16,226 already agree.
- **Disagreements on the A+B pages, by kind:**
  - today's section is a dish's name: 6,152;
  - an earlier sibling heading (missed heading): 5,309;
  - Unsectioned: 2,610;
  - a non-heading line between heading and item (maybe finer): 1,015;
  - a later heading: 175 (17 of the 18 audited are pseudo-items: a heading emitted as an
    item);
  - a coarser outline ancestor: 109;
  - other: 2,090.

**Hand audit** (dev, refined rules, seed 20261024, 8 per kind, 56 items; `audit2.txt`):
- 12 are pseudo-items, where a heading, nav link, icon or non-menu page was emitted as an item.
  Here the section doesn't matter.
- Of the other 44:
  - the DOM section is right in **39 (88.6 %)**;
  - today's is right in 4: Wix note divs and Kona's `p.uppercase` category;
  - both are wrong in 1 ("View All").
- Weighted by kind, about 90 % of non-junk changes improve the section and about 5 % regress.

## 6. Label-based measurement (existing gold labels, dev)

Gold labels already record each item's section as "the nearest section heading the page prints
above the item, as printed" (LABELLING.md). Of the labelled pages:
- 714 menu pages segment to a text hash that production extracted, so they have saved answers;
- 80 have no production answers;
- 513 are not menus.

On those 714 pages, 20,411 gold items match a kept row; 2,585 gold items were not extracted.
Scoring uses normalized tokens: *exact*, or *lenient* (one name's tokens contain the other's,
e.g. "DINNERS" ~ "DINNERS (Available All Day…)"). `var/p8-11/labelled-a90.txt`:

| | Section accuracy, exact | lenient |
|---|---|---|
| Today | 0.405 | 0.438 |
| (b), gated pages only (412 pages, 12,628 items) | 0.869 (today 0.414) | 0.875 (today 0.446) |
| (b) applied: gated pages (b), others today | **0.687** | **0.704** |

- **Gated pages:** 165 better, 7 worse; items +5,512 / −84 (lenient).
- **Ungated pages (302):** today 0.427. (b) used there would reach 0.471 but with more
  regressions, so it isn't applied.
- **Variants of the gate:**
  - strict (every item assigned): 346 pages, applied 0.671, +4,823 / −74;
  - add a corroboration gate (≥25 % of the DOM headings used must also be section names the
    model gave): applied 0.679, 148 better / 4 worse, +4,940 / −27.

These sets tuned extraction versions, not sections, but they are now the dev set for this
stage. Of the 863 production page texts, 149 are neither labelled nor audited; 57 of those
are gated. That is the pool for the held-out draw (Amendment 28 item 6).

## 7. Case 5 sizing: options left in an item's own text

`var/p8-11/opts.py`. An item's *region* is its name block up to the next item, at most 6 blocks:
- 6,024 of 61,644 items (9.8 %, on 498 pages) print at least two prices in their region but
  have fewer extracted (BYO counts, sizes in a description);
- 2,909 (4.7 %) carry a choice or add-on line ("choice of", "choose", "options:", "add-ons").

These are upper bounds: add-on prices are included on purpose (Amendment 19 2(c): a "+$" row is
a modifier). A generic fix belongs in its own amendment. Its parts:
- a deterministic reader for a "label $price | label $price" run inside an item's own region,
  giving variants;
- a modifier slot from the prompt through `menu_shape` and `menu_writes`. The Menu schema
  already has `menu_modifier`.

## 8. Case 6 plan: detecting menu content in images

Nothing is built and OCR stays out of scope. The aim is to count what is missed and say where.
- **Signals.** All generic, and all from the HTML already stored:
  - content images that are not a logo or icon, with a declared size of at least 800 px on a
    side (`width`/`height`, `srcset` `w`, `data-image-dimensions`);
  - whose alt, title or file name contains a menu word (menu, drinks, prices, carta,
    specials, cocktails, happy hour, brunch, lunch, dinner);
  - on a page whose non-chrome blocks print fewer than 5 prices.
- **Where to record them.**
  - (i) At discovery and menu-page fetch: a skipped Capture keeps its reason code. A count
    `image_menu_suspect` goes in the run report, so pages like Bottega's `/menu` are counted,
    not silently passed over.
  - (ii) At extraction: the per-page run report gets `menu_images` (count). Recorded, not
    gated.
- **Today's counts.**
  - 230 of 880 published heads have at least one menu-named content image;
  - 75 of those print fewer than 5 prices.
  - The first examples are mostly dish galleries and unpriced menus (Taco Cabana, First Watch),
    so precision is unknown.
- **Before any rule.** A blind labelled sample of 50 flagged pages ("is menu content only in
  images?") sets the precision, then the threshold.
- The alt text of Bottega's images not reaching blocks is a separate segmenter question.

## 9. Side findings (not proposed here)

- **Pseudo-items.** Section headings, jump-to links (uchi b0071–b0083), diet icons and allergen
  rows are emitted as items. They are 12 of 56 audit items, and nearly every "later heading"
  disagreement.
  - The section-style rule identifies headings, so a later change could stop them becoming
    items.
  - That change touches item recall and the §8 extraction bars, so it belongs in its own
    amendment.
- **Missed dishes in long `h3` lists** (Veracruz chunk 0): a recall question for the
  extraction bars.
- **Barstool Bites' menu URL** is `seasideonthepier.com` (case 4).
- **ADR-0013's Status line** lists amendments only through 19 (doc drift; not changed here).

## 10. Artefacts

All untracked, in `.claude/worktrees/p8-11-menu-structure/var/p8-11/`:
- scripts: `rich.py`, `domsec.py`, `trace.py`, `casecheck.py`, `sweep.py`, `analyse.py`,
  `audit.py`, `labelled.py`, `mech.py`, `opts.py`, `imgsweep.py`, `svc.py`;
- outputs: `t-<case>.txt` (traces), `cc-<case>.txt` (per-item current vs DOM), `sweep.jsonl`,
  `analyse.txt`, `audit.txt`, `audit2.txt`, `labelled-*.txt`, `imgsweep.jsonl`;
- `labelled_text_hashes.json` (exclusions for the held-out draw);
- read-only SQL: `find*.sql`, `corpus.sql`, `gold.sql`, `mod.sql`, `mv.sql`, `bottega.sql`,
  run through `ro.sh`.
