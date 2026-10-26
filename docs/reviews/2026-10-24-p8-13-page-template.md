# Page templates from accepted items, and duplicate emissions (ADR-0013 Amendment 29, proposed)

Session P8-13, 2026-10-24. The owner reported four more menu-structure problems on the local
site ("issues 2"). This record traces each one to the stage that lost it and sizes each
mechanism over the stored corpus. It then measures two generic fixes on dev:
- a **page template** stage that learns each page's own item layout from the items the
  pipeline already accepted (the owner's "HTML reverse consensus");
- **duplicate removal** for the merge-guard leftovers.

It proposes [ADR-0013 Amendment 29](../adr/0013-phase5-menu-pipeline.md#amendment-29-2026-10-24-proposed-stage-5d-page-template-and-duplicate-emissions).

Scope:
- diagnosis, prototype and proposal only. No pipeline code changed, nothing was built into
  `packages/`, nothing was re-interpreted and Gold was not refreshed;
- `helios_laptop` (alembic head `13081a087231`, resolve-v3) was read only, through `set
  transaction read only` sessions. Nothing was written to Bronze, Menu, identity or Gold;
- every page came from its stored bundle and every answer from the saved production answers
  (`var/replay/menu-extract/`, extractor
  `qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2`). There were no
  fetches, no model calls and no Pi access;
- no schema, migration, dependency, model, prompt or `infra/` change; no per-site,
  per-platform or hand-entered rule.

**Result.**
- All four findings are confirmed against stored data. They come from four mechanisms:
  - a [4] model miss amplified by a repair and the validator (Halal Wings);
  - size labels emitted as item names (Jarochos);
  - a chunk-boundary re-emission that [5c]'s merge guard holds in place (Los Mayas, Vivo);
  - a validator grounding collapse of a dish printed twice (Vivo).
- **Page template (dev, 223 of 294 scorable labelled pages gated):**

  | | Before | After |
  |---|---|---|
  | Item recall | 0.892 | 0.931 |
  | Kept-item precision | 0.811 | 0.844 |
  | Usable prices | 0.812 | 0.856 |
  | Price accuracy | 0.993 | 0.993 (unchanged) |

  Every gain's page-clustered 95 % interval excludes zero. 149 pages gain gold items and 5 pages lose some.
- **Duplicate removal** (copies that cite the same printed prices): 596 duplicate items go on
  243 page texts. Every one of the owner's one-dish sections disappears. No printed price
  Evidence is lost, and no gold item or gold price is lost on dev.
- Section accuracy (Amendment 28's metric) rises slightly, 0.715 → 0.723 exact.
- Both fixes change item counts, so the §8 extraction bars apply. They are proposed, not
  built.

## 1. Trace

Read-only replays: `var/p8-13/trace.py` (every stage, resolve-v3 included, with each block's
open-element path), `dupcase.py`, `tplcase.py`, `dedupecase.py`; SQL `venues.sql`,
`jarochos.sql` through `ro.sh`. Notes: `var/p8-13/notes-trace.md`.

| # | Finding | Losing stage | Mechanism | Fix family |
|---|---|---|---|---|
| 1 | Halal Wings 19884: ingredient lines stored as items | [4] model + repairs `split_listed` (v6) + [5] validator | The model named rows by the ingredient line under a priced title ("Lettuce, Crouton, Parmesan Cheese, Taziki" at $9.39). `split_listed` turned each comma list into one row per ingredient. The validator accepted the b0098/b0100 rows with the price printed on Caesar's own line (b0099); the b0097 rows were downgraded and kept unpriced. | Template DROP (description-position rows) |
| 1 | Halal Wings: "Caesar Salad ….. $9.39" and "Jalapeno Salad ….. $9.39" missing | [4] model | Chunk 3 (b0077–b0101) never emits b0099 or b0101. Jalapeno Salad is the chunk's last block; the model cites b0101 for "Veggie Supreme (V)", which the validator re-grounds to b0091. | Template ADD |
| 2 | Jarochos 21987: "Pequeño / Mediano / Grande" as separate items | [4] model → [5] → shape | The model put the size label in the name slot (`n: "Pequeño", v: ""`). The validator accepts (label and price share b0064), and shape stores three items. The dish row "Coctel de Camaron (Shrimp)" is downgraded and unpriced. | Template ATTACH (variants of the card's dish) |
| 2 | Jarochos: $28.49 / $20.99 instead of $28.99 / $21.99 | none (display) | The stored Capture prints Camaron's sizes at $12.49 / $21.99 / $28.99 (b0064), as the owner saw. $20.99 / $28.49 are Coctel de **Pulpo**'s printed line (b0066). The API orders a section's items by name, so every dish's "Grande" sits together. | Same as above |
| 2 | Jarochos: a newer Version never extracted? | none | Record 21109 has one Version (srv 21109, observed 2026-10-02 03:41 CDT) from one Capture (26897, fetched 2026-10-01 23:58 CDT), and no other Capture exists on that endpoint. Menu pages 900 (initial), 2881 (classifier-v2+v3) and 4561 (resolve-v3) are re-interpretations of that one Version, with the same prices. | — |
| 3 | Los Mayas 20766: second "MEXICAN SPECIALS" holding only Steak Picado | [3] chunk boundary → [4] re-emission → [5] → [5c] merge guard | "Steak Picado" (b0099) and its description end chunk 1, and its price (b0101) opens chunk 2. Chunk 2's context repeats "it ended with … Steak Picado …". The model emits the dish in both chunks, under DAILY HOUSE SPECIALS and MEXICAN SPECIALS, and the validator grounds both to b0099. That gives one item key in two sections, so the guard keeps both where they were. | Duplicate removal |
| 4 | Vivo 20844: one-dish Enchiladas sections | same as 3; plus a [5] grounding collapse | Spinach & Mushroom Enchiladas is re-emitted across the chunk 12/13 boundary. Chipotle Enchiladas is **printed twice** (b0136 under Mains, b0286 under Specialty Enchiladas). The c13 row cites b0287, but b0286 was taken by a mis-cited row, so it grounds to b0136. The second printed dish is lost, and its row collides with the first. | Duplicate removal; grounding stays a separate fix |

Owner's element patterns, checked:
- **Halal Wings.** The owner's path `/html/body/div/div[2]/div/div[4]/p[N]/span/span/span` is
  shared by items and ingredient lines. They usually differ only by class (`p.wse-txt-bm`
  item lines, `p.wse-txt-bs` descriptions), and not reliably: "P2-White Sauce", "P20-…" and
  "Loaded Chicken" item lines are `p.wse-txt-bs` too.
  - So a template cannot trust classes here. What separates an item line is that it prints
    its own price.
- **Jarochos.** Every dish is a `div.food-item-holder.menu_item_<n>` card holding
  `div.food-item-title/h3` (name). The price sits in `div.food-price` for one-price dishes,
  and in `div.food-item-description` ("Pequeño $12.49 | …") for sized dishes.

The leftovers named in P8-12 §5a are confirmed the same way (`dupcase.py`):
- Veracruz 23260: 16 duplicated keys, among them 8 desserts under "Shrimp Taco", 7 sweet
  breads also under "Coffee", and El Furioso under "Cochinita Pibil Taco";
- Barstool Bites 20334: Chicken Alfredo;
- Que Divino 20358: Queso Flamiado Con Chorizo;
- Jarochos: 3 more ("Choriqueso" / "Sides").

## 2. Corpus sizing (863 published page texts, saved answers; `var/p8-13/sizing.txt`)

The replay holds 61,644 items, the stored Menu total. 35,109 of them are priced.

- **(a) Duplicate emissions.** One printed item (name block and name) is stored under two or
  more sections on **243 page texts** (28 %). That is 708 item keys, 717 extra copies and 272
  one-dish sections.
  - Cause, from the model's own emissions of the name:
    - 333 within one chunk;
    - **260 in adjacent chunks** (the boundary re-emission above);
    - 115 in chunks far apart (often a menu printed twice).
  - In 603 keys every copy states the same prices. In 105 the copies differ: these are
    grounding collapses, a second printed dish merged onto the first.
- **(b) Pseudo-items.** A kept item named on a line that prints no price of its own and reads
  like a description (repairs' `_description_like`: two or more commas, a final period, or
  eight or more words): **6,710 items on 590 pages** (10.9 % of items).
  - 1,731 of them are priced, so they reach Gold and the price index.
  - 4,979 are unpriced: they are stored in Menu, but Gold and the API hide them.
- **(c) Printed priced lines no kept row cites** (outside page chrome): 11,379.
  - 598 are add-on lines and 2,949 sit on pages the template does not gate.
  - **6,828 sit on the page template's price path** and 1,004 off it.
  - Of the 6,828 the template adds 1,847 items. The rest are not added because:

    | Reason | Lines |
    |---|---|
    | No name block in the template position (lone second prices, combo lines) | 2,912 |
    | Inside a kept item's span | 467 |
    | Same name and price already held | 335 |
    | The dish right above is kept unpriced | 285 |
    | Add-on | 241 |
    | The name reads like a description | 215 |
    | Wine list | 213 |
    | Relation differs | 197 |
- **(d) Size labels stored as items.** A kept, priced item named by the label printed with its
  price, in a run of two or more labelled prices ("Pequeño" from "Pequeño $12.49 | Mediano
  $21.99"): **335 items on 72 pages**. The template re-attaches 57 rows; the rest are on
  ungated pages or off-template.

## 3. The page template prototype (`var/p8-13/template.py`)

Generic, stdlib only, built on [5c]'s `placed_blocks`. It runs after [5b] and returns a new
row list, which the same validator judges again. A row the template adds or rewrites must
still ground its name and price in the page's blocks.

1. **Seeds.** Accepted rows with a name block and a price block.
2. **Record pattern.** Each seed gives:
   - the tag path of its name block and of its price block (last three block-level tags;
     classes are not trusted, see Halal Wings);
   - their relation: the block offset, the common ancestor's tag, and how many levels each
     block sits under it.
3. **Clustering.** Seeds are grouped by exact pattern. The template is every group with at
   least 3 seeds and at least 10 % of them.
4. **Gate.** At least 5 seeds; the template explains ≥ 80 % of them; and ≥ 80 % of the
   explained seeds share the main name path. Ungated pages get their rows back unchanged.
5. **Name candidates and records.**
   - A candidate is a block on a template name path:
     - for a same-line pattern it must print a price after some text;
     - for a split pattern its class signature must be one the seeds use.
   - A candidate's record is its container (the pattern's common ancestor, or for a
     same-line pattern the line's parent), up to the next candidate.
6. **Actions**, on kept rows named inside another candidate's record:
   - **ATTACH.** The row's name is the label printed with its price in a run of two or more
     labelled prices. It becomes a variant of the record's dish.
   - **RE-NAME.** One of two cases:
     - the row's name is the record title's words, but the model cited the description: the
       row is re-grounded on the title, or dropped if the title already holds it;
     - the row is an accepted description line priced inside the record, and another row
       keeps the title unpriced: the row takes the title's name, so the dish keeps its
       price.
   - **DROP.** The row's line prints no price of its own (and does not print the row's own
     amount) and reads like a description. A pipe-separated list of names is kept.
   - **ADD.** A template price line that no kept row cites, whose name block sits in the
     pattern's position, becomes an item: one row per printed price, labelled when there
     are several. It is skipped when:
     - it is inside a kept item's span;
     - it is an add-on;
     - the name reads like a description or is only price labels;
     - the dish right above is kept unpriced;
     - it is under a wine-list heading;
     - the same name and price are already on the page.

The owner's cases with the template (`var/p8-13/tplcase.py`):

| Page | Template | Effect |
|---|---|---|
| Halal Wings | one same-line pattern, 80 of 86 seeds | ADD Caesar Salad $9.39 and Jalapeno Salad $9.39 (both accepted on re-judge); DROP the 5 ingredient rows priced from Caesar's line and 46 unpriced ingredient rows; "P2/P20" item lines kept |
| Jarochos | `h3` title over a price `div` in one card, 213 of 234 seeds | ATTACH 15 rows: Pequeño / Mediano / Grande become variants of Coctel de Camaron, Coctel de Pulpo, Campechana, Coctel Mixto, Ceviche de Jaiva, Coctel de Ostiones and Vuelve A La Vida; ADD 3 (Costillas de Puerco, 4 and 8 Pieces; Ropa Vieja) |
| Vivo | the same card layout, 90 of 102 seeds | ADD Chalupa Compuesta and Flautas; DROP 4 downgraded description rows. The accepted description row b0288 ($17) stays: its line holds "|" separators, which the list guard keeps |
| Los Mayas | two patterns (name → price, name → description → price) | ADD 4 (Mexican Pizza, Steak Ranchero, Guacamole, Flour / Corn Tortillas). RE-NAME 4: the $19.50 on three description rows moves to their kept, unpriced titles (#7 Huevos Rancheros, #9 Polo Asado, #14 Enchiladas Rancheras), and Fried Ice Cream moves to its title. DROP 1 description row |

### 3a. Dev measurement (`var/p8-13/devtpl.txt`, `report-base.txt`)

- **Pages.** The §8 extraction harness scores reviewed menu pages with a priced gold item.
  - Of the 746 dev pages (P8-12's 714 plus its 32 held-out pages, now dev), 294 are
    scorable; 21 of them are P8-12 held-out pages.
  - The base gate covers 223 of them. The 71 ungated pages are 32 below 80 % explained, 21
    below 80 % agreement, and 18 with fewer than 5 seeds.
- **Scoring.**
  - `evaluation.score_page` before and after;
  - item precision: kept items (name block, name) that match a gold item;
  - a per-action check of every add, drop, attach and re-name against gold.

On the 223 gated pages, change with a page-clustered 95 % interval (2,000 resamples):

| Measure | Before | After | Change |
|---|---|---|---|
| Item recall (gold items found by a kept row) | 0.8918 | 0.9310 | **+0.0392** [+0.0331, +0.0460] |
| Item precision (kept items matching a gold item) | 0.8106 | 0.8436 | **+0.0329** [+0.0249, +0.0421] |
| Usable prices (gold prices found exactly) | 0.8119 | 0.8555 | **+0.0436** [+0.0370, +0.0508] |
| Price accuracy (accepted matched rows, exact) | 0.9934 | 0.9934 | +0.0000 [−0.0012, +0.0012] |

- **Counts:**
  - gold items found 15,393 → 16,070 (+677);
  - gold prices found 14,634 → 15,419 (+785);
  - kept items 20,287 → 20,263;
  - accepted rows matching no gold item 1,343 → 1,352 (+9);
  - wrong rows accepted 1,445 → 1,459 (+14);
  - row-level false rejects 946 → 930 (−16).
  - rows the validator rejects 551 → 590 (+39), mostly adds and moved rows it does not
    ground.
- **Pages.** Recall goes up on 149 pages and down on 5, and is unchanged on 69.
- **By action:**

| Action | Count | Right | Wrong |
|---|---|---|---|
| ADD | 926 | 783 new gold items (771 at a gold price); 29 a gold item already found (a menu printed twice) | 93 match no gold item; 21 rejected by the validator |
| DROP | 853 | 754 match no gold item; 73 duplicate a kept match | 26 lose a gold item nothing else holds |
| RE-NAME | 77 | 74 match a gold item | 3 |
| ATTACH | 29 | 24 exact (gold item, variant label and price) | 1 item only; 4 unmatched |

- **By layout (gold `format`):**

  | Format | Pages (gated) | Recall | Precision |
  |---|---|---|---|
  | html_list | 236 (183) | 0.893 → 0.934 | 0.811 → 0.845 |
  | html_cards | 41 (23) | 0.915 → 0.955 | 0.834 → 0.852 |
  | price_list | 11 (11) | 0.920 → 0.942 | 0.734 → 0.776 |
  | html_inline | 6 (6) | 0.783 → 0.793 | 0.866 → 0.890 |

- **Variants measured** (all on the same 294 pages):

  | Variant | Gated | Recall | Precision | Pages losing items |
  |---|---|---|---|---|
  | Base (gate 0.8 / 0.8) | 223 | 0.892 → 0.931 | 0.811 → 0.844 | 5 |
  | Gate 0.9 | 177 | 0.901 → 0.938 | 0.828 → 0.864 | 5 |
  | Gate 0.7 | 241 | 0.888 → 0.927 | 0.808 → 0.842 | 6 |
  | Gate 0.6 | 249 | 0.888 → 0.926 | 0.804 → 0.836 | 6 |
  | One seed per model item (model grouping) | 228 | 0.891 → 0.930 | 0.811 → 0.842 | 7 |
  | ATTACH only where the model grouped variants | 223 | as base | as base | 5 (ATTACH 24, not 29) |
  | Also DROP rows priced from their record's dish | 223 | 0.892 → 0.932 | 0.811 → 0.845 | 5 |
  | ADD only | 223 | 0.892 → 0.930 | 0.811 → 0.814 | **0** |
  | DROP only | 223 | 0.892 → 0.890 | 0.811 → 0.842 | 18 |

  - The model's own grouping (an item and its variants in one output) adds nothing
    measurable. The saved answers rarely group variants, and the grouped rows the
    template can use are few.
  - ADD carries the recall gain without losing anything. DROP carries the precision gain
    and costs a little recall, which the other actions make good.
- **What the remaining errors are** (seeded samples, `sample-add.txt`, `sample-drop.txt`):
  - unmatched adds: wine lines the model did not label as wine, fees and notes ("Corkage
    Fee", "*Preparation…SPICE+SERVICE CHARGE"), and description lines in two-line records;
  - lossy drops: a dish whose only printed name is inside its description ("Grilled Shishito
    Peppers tossed…"), wine lines, and blocks holding several items.
- **Invariants.**
  - The validator is unchanged. Gold-row false reject and injected-corruption catch (the §8
    validator bars) are computed on gold rows by the validator alone, so they cannot move.
  - Price accuracy is unchanged.
- **Cost.** 38 ms median per page on one laptop core (p95 242 ms), about 60 s of CPU for all
  863 page texts. That covers the re-parse, induction, re-judge and duplicate removal
  (`timing.txt`). The Pi is not timed.

## 4. Duplicate removal (`var/p8-13/dedupe.py`, `dedupe.txt`, `dedupecase.py`)

Removal works on rows, before shape:
1. The rows of a printed item's first section (reading order) are kept, and the rows the
   model emitted under its other sections are dropped.
2. Shape then runs with [5c] as today. With no clash left, the merge guard no longer holds
   the survivor back, so on a gated page it lands under its DOM section.

Two rules:

| | Corpus: item copies removed | Duplicate price rows | Sections | One-item sections | Distinct printed price Evidence | Dev: gold items / gold prices lost |
|---|---|---|---|---|---|---|
| **same** (copies cite the same printed prices) | 596 | −356 | −218 | −151 | **unchanged** | **0 / 0** (−208 items) |
| all | 717 | −475 | −305 | −230 | −104 | 0 / −57 |

- Under "same", 121 keys stay duplicated. Their copies cite different printed prices: a
  second printed dish grounded onto the first. Fixing those is a validator grounding change
  (prefer the print nearest the cited block), not removal.
- **The owner's pages under "same":** every one-dish section goes, and the dish lands in its
  DOM section.

  | Page | Dish | Lands under |
  |---|---|---|
  | Los Mayas | Steak Picado | "MEXICAN SPECIALS (All Specials Served With Rice And Beans, Flour Or Corn Tortillas)" |
  | Vivo | Spinach & Mushroom Enchiladas | "Specialty Enchiladas" |
  | Vivo | Chipotle Enchiladas | "Mains" (the second printed copy stays lost) |
  | Veracruz | 16 keys | their sections; 116 → 100 items, all 88 price Evidence spans kept |
  | Barstool Bites | Chicken Alfredo | "Specialties" |
  | Que Divino | Queso Flamiado Con Chorizo | "Appetizers" |

## 5. Section accuracy with both changes (all 746 dev pages; `var/p8-13/secacc.txt`)

Amendment 28's metric (judge → [5c] → shape on each row set):

| Rows | Scored items | Exact | Lenient | Exact items | Dish-named sections |
|---|---|---|---|---|---|
| Today (resolve-v3) | 22,252 | 0.7151 [0.664, 0.762] | 0.7307 | 15,912 | 734 |
| Duplicate removal only | 22,252 | 0.7199 | 0.7353 | 16,020 | 669 |
| Template only | 22,866 | 0.7178 | 0.7332 | 16,414 | 728 |
| Template + duplicate removal | 22,866 | 0.7228 [0.671, 0.772] | 0.7380 | 16,527 | 658 |

- With both changes, 154 pages gain exact-section items and 8 lose some.
- [5c] invariance holds on every page. Three pages leave the [5c] gate, because the template
  changed their item set.

## 6. Mechanism → size → fix → expected gain → risk

| Mechanism | Size (corpus) | Fix | Expected gain (dev) | Risk |
|---|---|---|---|---|
| (a) Duplicate emissions (merge-guard leftovers) | 243 pages, 708 keys, 717 extra copies, 272 one-dish sections | Duplicate removal, rule "same" | −596 items; −151 one-item sections; section accuracy +0.005; no gold loss | Low: copies citing different prices stay; item counts change, so §8 applies |
| (a′) Chunk-boundary re-emission (root of 260 keys) | 260 keys | Forward: the chunker does not split an item's name from its price, or the context tail is not re-emittable | Removes the cause | Extractor key changes; GPU re-extraction and a full §8 run |
| (a″) Grounding collapse of a dish printed twice | 105–121 keys | Validator: ground to the print nearest the cited block | Restores the second dish (Vivo) | Validator change: the FR and catch bars move |
| (b) Pseudo-items (ingredient and description lines) | 6,710 items on 590 pages (1,731 priced) | Template DROP / RE-NAME (gated pages; corpus 1,813 drops, 186 re-names) | 754 dropped correctly, 74 re-named correctly; precision +0.033 (with ADD) | 26 lost gold items per 223 pages; ungated pages untouched |
| (c) Printed priced lines no item cites | 11,379 lines; 6,828 on a template price path | Template ADD (corpus 1,847 items) | 783 new gold items, 771 at a gold price; recall +0.039, usable +0.044 | 93 unmatched adds (10 %): wine lines, fees, notes |
| (d) Size labels stored as items | 335 items on 72 pages | Template ATTACH; the queued case-5 variant reader for ungated pages | 24 of 29 exact | Small volume; wrong attaches merge two dishes' prices |

## 7. How to describe this (plain language)

The standard name is **wrapper induction**, also called template induction. Each step below
gives the data-science framing first, then what it means here.

1. **Seeds.** *Self-training* (also *distant supervision*): the model's own accepted output
   is used as training labels. They are noisy, but mostly right.
   - Here: every accepted row whose name and price are both found on the page.
2. **Features.** *Feature engineering*: each seed is described by where it sits, not by what
   it says.
   - The tag path to the name and the tag path to the price.
   - How the two relate: the same line, the next line, or the same card.
   - Classes are left out on purpose. A site may style a real item like a description (Halal
     Wings).
3. **Clustering.** *Grouping by a shared key* (the simplest clustering, finding the
   distribution's modes): seeds with the same features form a group.
   - One big group means one clean layout.
   - Several groups mean several layouts on the page, such as dishes with and without a
     description line.
   - A group needs *support* (3 seeds and 10 % of them) to count.
4. **Gate.** *Abstention*, or selective prediction: act only when confident.
   - The template must explain ≥ 80 % of the seeds, and its groups must agree on where names
     sit.
   - Otherwise the page is left exactly as it was. This is [5c]'s idea of a page gate.
5. **Applying the template.** *Classification* of every block against the learned pattern:
   - a block that fits but has no item is a *candidate the model missed*: a recall gain;
   - a kept item that sits where descriptions sit is a *suspect*: a precision gain;
   - a size row inside a dish's card is a *variant* of that dish.
6. **Safety net.** Every added or rewritten row is judged again by the unchanged validator,
   so nothing is stored that the page does not print.
7. **Measuring.** Ask for both numbers, per page, before and after:
   - **precision**: of what we add or keep, how much is right;
   - **recall**: of what the page prints, how much we get.

   Ask for them per action, because adding and dropping fail in different ways. Use the
   *page-clustered bootstrap*: items on one page succeed or fail together, so resample whole
   pages to get honest error bars.
8. **Dev vs held out.** Every rule here was tuned on the dev pages, so the dev numbers are
   optimistic. Only a fresh, blind-labelled set drawn after the rules are frozen says how
   well it generalises. Labelling it after the rules are frozen avoids *tuning on the test
   set*.

Useful phrases when guiding this kind of work:
- "Use the accepted items as seeds; what fraction of seeds does the template explain?"
- "Show me 20 random adds that match no label, and 20 random drops that lose a label"
  (*error analysis*).
- "What does the gate abstain on, and why?"
- "Per action: how many right, how many wrong?"
- "Freeze the held-out set and its exclusions before anyone looks at the output."

## 8. Owner questions

In the PR and in Amendment 29.

## 9. Artefacts (untracked, `var/p8-13/` in the worktree)

- **Scripts:**
  - `lib.py` (corpus and one-page replay), `trace.py`, `dupcase.py`, `sigs.py`;
  - `template.py` (the prototype), `tplcase.py`, `devtpl.py`, `devcase.py`, `report.py`,
    `sample_unmatched.py`;
  - `sizing.py`, `dedupe.py`, `dedupecase.py`, `secacc.py`, `timing.py`, `pool.py`;
  - `patch_*.py` (prototype edits);
  - read-only SQL `venues.sql`, `jarochos.sql` with `ro.sh` / `ro.py`.
- **Outputs:**
  - `t-<rec>.txt` (traces), `notes-trace.md`, `venues.json`, `jarochos.json`, `api-21987.json`;
  - `devtpl.txt` / `.jsonl`, `report-base.txt`, `sample-add.txt`, `sample-drop.txt`;
  - `sizing.txt` / `.jsonl`, `dedupe.txt`, `secacc.txt` / `.jsonl`, `timing.txt`.
