# Extraction gap audit: oracle ceilings, causes and a label check (P8-x)

Session P8-x, 2026-10-26. This record measures how far resolve-v4 is from a perfect
extraction on dev, and explains each gap. It is an audit: nothing was built, and nothing
is proposed as an amendment yet. Section 5 ranks the fixes and asks the owner which to
pursue.

Scope:
- **Dev numbers only.** The pages are P8-13's 746 plus the P8-14 set (793 menu pages; 332
  scorable, with 23,664 gold items and 24,421 gold prices). resolve-v4 was tuned on these
  pages, so every figure here is optimistic compared with a held-out set. None of it is a §8
  result.
- **Data.** Every page came from its stored HTML and every answer from the saved
  production answers (`var/replay/menu-extract/`, extractor
  `qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2`; the P8-14
  set's from `var/p8-14/heldout/extract/prod/`). There were no fetches and no model calls.
- **Code.** The pipeline measured is resolve-v4 as of PR #126's head `ec02992`, which is not
  yet on `main`. It was exported read-only with `git archive`. A re-implementation of
  `page_template.llm_stream` with replaceable stages gives the oracles. It returns
  **exactly** production's verdicts on all 793 pages. The starting point
  `var/p8-15/gap.txt` reproduces byte for byte.
- **Writes:** none to Bronze, identity, Menu or Gold, and no database access at all. No
  schema, migration, dependency, model, prompt, chunker or validator change, and no per-site
  rule or manual entry.
- **Subagents.** Three sonnet subagents label-checked the traced samples against a fixed
  rubric. This session re-checked every label-error verdict and every case left ambiguous
  for lack of context on the full page (section 4).
- **Artefacts:** `var/p8-x/` holds:
  - the scripts (`audit.py`, `cause_v2.py` and the aggregators);
  - `audit4.jsonl`, with one line per page, every lost gold price and its trace;
  - the outputs (`*.txt`);
  - the 70 traced cases with the subagents' answers and the final adjudication
    (`cases/`).

## Result

- **Gap.** resolve-v4 delivers **0.806** of dev gold prices as usable (page-clustered 95 %
  [0.775, 0.834]).
  - The harness's own ceiling is **0.986**: gold rows with a perfect validator. It falls
    336 prices short of 1.0. Of those, 322 are a second price of the same amount on one item
    (usable prices count an (item, amount) pair once). The other 14 are gold rows the
    harness matches to another item, all on one inline page (`var/p8-x/dupamt.py`).
  - So the measured gap is **0.180**.
- **Whose gap.** The model owns most of it; the validator owns most of the rest:

  | Stage made perfect | Usable gain, the other stages as built | Gain once the other stage is perfect |
  |---|---|---|
  | Extractor (gold rows) | +0.084 [+0.071, +0.098] | +0.138 (after a perfect validator) |
  | Validator | +0.040 [+0.031, +0.051] | +0.095 (after a perfect extractor) |
  | [5d] gate off | +0.007 [+0.004, +0.011] | — |

  The two stages compound: each one's errors hide the other's.
  - **Validator.** It accepts only 0.900 of gold rows: gold-row FR 0.1008 [0.077, 0.128].
    That caps usable prices at **0.890**, even with a perfect model.
  - **Model.** It caps item recall at 0.914 and kept-item precision at 0.820. A perfect
    model gives 0.996 and 0.983.
- **Where every lost price goes**, by the first stage that loses it (4,509 lost of 24,421):

  | Stage | Lost | Share of gold prices |
  |---|---|---|
  | [4] model | 3,184 | 13.0 % |
  | [5] validator | 1,031 | 4.2 % |
  | Chunker | 84 | 0.3 % |
  | Repairs | 72, plus 45 out of scope as wine | 0.5 % |
  | [5d] / dedupe | 63 | 0.3 % |
  | Harness name collisions | 30 | 0.1 % |

  - The 72 [5d]-ungated pages lose **33 %** of all lost prices, though they hold 18 % of
    gold prices. Their usable rate is 0.625; the 260 gated pages' is 0.846.
- **Not "the model missed it".** More than half of the model's losses are the model
  emitting the price with the wrong name or layout:
  - a price on a wrong name, such as the dish's heading, option, description or neighbour
    (1,052);
  - a size column dropped (558);
  - a neighbour's price (229).

  A plain miss is 588. An unpriced dish under a **shared section price** (one price printed
  above several dishes) is 411 across all buckets.
- **Labels.** In 70 traced cases across the top causes there are 54 pipeline errors,
  **3 label errors** and 13 ambiguous.
  - Label-error rate **4.3 %**, Wilson 95 % [1.5 %, 11.9 %].
  - Label error or ambiguous: 22.9 % [14.6 %, 34.0 %].

  The labels are not the bottleneck. Most ambiguity sits on one page that prints its prices
  in a separate column (`cfb443e9b654`).
- **Best fixes** (section 5), all generic and all on derived HTML or the validator:
  - in [5], the validator's price scan should not end at a price-less heading, a repeated
    name or an emitted description: **290** prices (379 with every scan stopper), and 10 of
    10 traced cases are pipeline errors;
  - in [5d], RE-NAME and ATTACH driven by the page template: **752 + 413** prices on gated
    pages;
  - shared section prices: **411** prices. Delivering them is an owner fork.

## 1. Oracle ceilings

Each oracle replaces one stage with gold; everything else is production resolve-v4. The
oracles:

- **E0, oracle extractor:** gold rows, one per gold price (an unpriced item is one
  unpriced row). They carry the label's block as the claim and go through [5]+[5b] → [5d]
  → [5]+[5b] → duplicate removal.
  - **E0 no [5d]:** the same rows through [5]+[5b] only.
  - **E1:** gold sent as one model answer and repaired by `rows_of`.
- **V, oracle validator:** model rows. After every [5]+[5b], a gold-matched row at a gold
  amount is accepted (citing the nearest printed token of that amount), and one at another
  amount is not.
- **T, oracle template:** [5d]'s page gate is off (`MIN_SEEDS` 1, `GATE_EXPLAINED` and
  `GATE_AGREE` 0). A pattern still needs `MIN_SUPPORT` seeds, so 316 of the 332 scorable
  pages gate, up from 260.
  - **T best:** per page, the better of gated and forced, a perfect gate. It equals T to
    four decimals: forcing [5d] almost never hurts a page's usable count.
- **EV, harness ceiling:** gold rows and the oracle validator.

**All 332 scorable dev pages** (page-clustered 95 % intervals; `var/p8-x/agg4.txt`):

| Variant | Item recall | Usable prices | Price accuracy | Kept-item precision |
|---|---|---|---|---|
| **resolve-v4 (production)** | **0.914** [0.899, 0.927] | **0.806** [0.775, 0.834] | **0.985** [0.973, 0.993] | **0.820** [0.798, 0.841] |
| resolve-v3 (no [5d], no dedupe) | 0.879 [0.864, 0.892] | 0.767 [0.738, 0.793] | 0.985 [0.971, 0.993] | 0.794 [0.774, 0.814] |
| E0 oracle extractor | 0.996 [0.994, 0.999] | 0.890 [0.862, 0.915] | 1.000 | 0.983 [0.977, 0.989] |
| E0, no [5d] | 1.000 | 0.891 [0.863, 0.916] | 1.000 | 1.000 |
| E1 oracle extractor through repairs | 0.994 [0.991, 0.996] | 0.900 [0.873, 0.925] | 0.998 | 0.982 [0.975, 0.988] |
| V oracle validator | 0.913 [0.898, 0.926] | 0.847 [0.819, 0.871] | 1.000 (by construction) | 0.819 [0.798, 0.841] |
| T oracle template (gate off) | 0.919 [0.904, 0.932] | 0.814 [0.784, 0.841] | 0.985 [0.972, 0.992] | 0.821 [0.798, 0.843] |
| V + T | 0.919 [0.904, 0.931] | 0.853 [0.826, 0.876] | 1.000 | 0.822 [0.800, 0.843] |
| EV, through [5d] | 0.997 [0.995, 0.999] | 0.984 [0.971, 0.993] | 1.000 | 0.985 [0.979, 0.991] |
| **EV, [5] only (harness ceiling)** | **1.000** | **0.986** [0.972, 0.995] | **1.000** | **1.000** |

**Paired changes in usable prices** (same pages both sides, page-clustered):

| Step | Change |
|---|---|
| resolve-v4 → oracle extractor | +0.0835 [+0.0706, +0.0981] |
| resolve-v4 → oracle validator | +0.0403 [+0.0309, +0.0511] |
| resolve-v4 → oracle template | +0.0074 [+0.0044, +0.0106] |
| oracle validator → both oracles | +0.1378 [+0.1173, +0.1631] |
| oracle extractor → both oracles | +0.0946 [+0.0720, +0.1209] |
| oracle extractor: no [5d] → [5d] | −0.0008 [−0.0023, +0.0006] |
| oracle extractor: no repairs → repairs | +0.0104 [+0.0047, +0.0164] |
| resolve-v3 → resolve-v4 | +0.0391 [+0.0325, +0.0462] |

**By slice** (usable prices; point estimates):

| Slice | Pages | v4 | v3 | Oracle extractor | Oracle validator | Oracle template | Harness ceiling |
|---|---|---|---|---|---|---|---|
| `html_cards` | 58 | 0.792 | 0.763 | 0.914 | 0.855 | 0.819 | 0.979 |
| `html_inline` | 7 | 0.654 | 0.639 | 0.733 | 0.753 | 0.654 | 0.976 |
| `html_list` | 256 | 0.810 | 0.769 | 0.889 | 0.847 | 0.815 | 0.987 |
| `price_list` | 11 | 0.884 | 0.859 | 0.969 | 0.888 | 0.884 | 1.000 |
| [5d] gated | 260 | 0.846 | 0.798 | 0.910 | 0.875 | 0.846 | 0.994 |
| [5d] ungated | 72 | 0.625 | 0.625 | 0.795 | 0.716 | 0.666 | 0.949 |

What the ceilings say:
- **Validator.** It is the cap on a perfect model. With gold rows, usable is 0.890: one
  correct printed price in ten is not accepted. Section 2's breakdown of the validator's
  losses on gold rows is this cap.
- **[5d] on a perfect answer.**
  - It drops 0.3 % of gold items: recall 1.000 → 0.996, mostly the description-like DROP.
  - It adds rows that match no label: kept precision 1.000 → 0.983. Some may be real items
    the labels leave out; this audit did not check them.
  - On model output, [5d] adds +0.039 usable, so its net is strongly positive.
- **Repairs.** On a perfect answer they help usable (+0.010; unprinted variants dropped, so
  rows ground) and cost a little recall (−0.003; renames).
- **Wider [5d] coverage.** It is worth at most +0.007 usable over all pages, and +0.041 on
  the ungated ones. There, price accuracy falls from 0.983 to 0.977.
- **`html_inline`** (7 pages) is the weakest format.
  - Even a perfect extractor reaches only 0.733 usable there: the validator grounds poorly
    in run-together blocks.
  - A perfect validator alone reaches 0.753.
- **Sections** (all 793 pages; 27,768 gold items with a labelled section; the same
  scoring as `evaluation.section_counts`):

  | Labelled-section items | Share |
  |---|---|
  | Not extracted (no kept row) | 8.8 % |
  | Right section, [5c]-gated page | 52.0 % (28.2 points of it [5c] fixed) |
  | Wrong section, [5c]-gated page | 4.8 % (0.6 of it [5c] broke) |
  | Right section, [5c]-ungated page | 13.4 % |
  | Wrong section, [5c]-ungated page | 21.0 % (6.2 points of it unsectioned) |

  - Gold sections reach **0.912** of all labelled-section items: everything extracted. [5c]
    reaches 0.654.
  - Of the 0.258 between them, **0.210 is on pages [5c] doesn't gate**, where the model's
    own section stands.
  - [5c]'s own errors on gated pages are 0.048. So section loss is mostly [5c]'s
    **coverage**, not its accuracy.

## 2. Every lost gold price, by cause

`cause_v2.py` buckets each gold price deterministically by following it through the stages:
- raw model rows;
- `rows_of`;
- the first [5]+[5b];
- [5d]'s rows, re-judged;
- duplicate removal.

The cause is the first stage that loses the price; only a price the model never emitted is
the model's. The four families (item missed, wrong amount, not grounded, unpriced) are
`evaluation.loss_verdicts`'s buckets on the final verdicts. They are asserted equal to
`gap.txt`'s per price.

Two checks on the classifier came from reading traces (section 4):
- **"Missed" needs care.**
  - Most items the first classifier called missed were emitted under another name, a
    description, or another language. These rows name no gold item, so they look absent.
  - A row on a shared inline block matching *another* item printed in that block is a model
    miss, not a harness collision.
- **The harness's `match`.** An exact name match anywhere on the page wins over the
  claimed block, which mis-pairs a dish that shares a name ("Chicken" under CONGEE). A
  claimed-block-first rule changes 31 rows on 14 pages and moves usable **0.8064 →
  0.8062** (`var/p8-x/alt_match.txt`). The harness is not a material source of the gap.

**Causes, all scorable pages** (share of the 24,421 gold prices; `var/p8-x/stages.txt`):

| Stage | Cause | Lost | Share | Pages | What it is |
|---|---|---|---|---|---|
| [4] model | `missed:model` | 588 | 2.4 % | 134 | No row anywhere near the dish |
| [4] model | `missed:emitted_other_name` | 573 | 2.3 % | 127 | A row on the dish's record names a heading, option, neighbour's title or alt text |
| [4] model | `wrong:size_column` | 558 | 2.3 % | 104 | The dish's other printed size or column price only |
| [4] model | `wrong:neighbour_price` | 229 | 0.9 % | 76 | A gold price of an item within three |
| [4] model | `missed:named_by_description` | 228 | 0.9 % | 75 | The row is named by the dish's description, often with the right price |
| [4] model | `unpriced:price_not_printed_near` | 228 | 0.9 % | 18 | Mostly a shared section price, printed away from the dish (section 4) |
| [5] validator | `ground:run_stopped_by_heading` | 204 | 0.8 % | 20 | A price-less heading (item code, repeated or bilingual name) between name and price ends the scan |
| [5] validator | `ground:region_other` | 196 | 0.8 % | 46 | Price after the name, not reached for another reason |
| [4] model | `unpriced:model_omitted_printed` | 139 | 0.6 % | 31 | Dish emitted unpriced; its price is printed after it |
| [4] model | `missed:neighbour_row_in_record` | 125 | 0.5 % | 43 | Only the next dish's row claims this dish's record |
| [4] model | `missed:emitted_other_language` | 124 | 0.5 % | 6 | Bilingual dish emitted under its other-language name |
| [4] model | `wrong:price_before_name` | 105 | 0.4 % | 9 | Price-first layout, the next dish's price (Dahlia Café 92) |
| [5] validator | `ground:glued_price` | 99 | 0.4 % | 20 | Amount printed glued to text, not read as a price |
| [5] validator | `ground:run_stopped_by_other_row` | 89 | 0.4 % | 37 | Another row's name block between name and price |
| [4] model | `unpriced:priced_sibling_row` | 89 | 0.4 % | 40 | The price went on a neighbouring line's row |
| [5] validator | `ground:claim_drift` | 84 | 0.3 % | 45 | Name grounded on another print of it (Amendment 30's g1f) |
| [5] validator | `ground:variant_label` | 63 | 0.3 % | 30 | The size label isn't grounded with the price |
| repairs | `missed:repairs` | 64 | 0.3 % | 32 | The raw row named the dish; `rows_of` lost it |
| chunker | `missed:chunk_boundary` | 54 | 0.2 % | 26 | Name or price at a chunk edge |
| [5] validator | `ground:region_same_block` | 53 | 0.2 % | 14 | Price in the name's block, cut by another name |
| [4] model | `wrong:other_price_on_page` | 53 | 0.2 % | 17 | Another printed price |
| [5] validator | `ground:price_far` | 50 | 0.2 % | 9 | Price over 15 blocks away (price columns) |
| [5] validator | `ground:run_stopped_by_description_row` | 49 | 0.2 % | 25 | An emitted description row ends the scan |
| repairs (wine) | `missed:repairs_wine` | 45 | 0.2 % | 8 | The model's section names wine; the label's doesn't (Amendment 15 scope) |
| [5d]/dedupe | `missed:5d_drop` | 42 | 0.2 % | 11 | [5d] DROP (Dale's 12, P8-14's title-line case) |
| [4] model | `unpriced:price_before_name` | 41 | 0.2 % | 14 | |
| [5] validator | `ground:run_stopped_by_other_language_row` | 37 | 0.2 % | 3 | |
| [4] model | `unpriced:priced_description_row` | 37 | 0.2 % | 22 | |
| [5] validator | `ground:shared_price` | 32 | 0.1 % | 13 | `price_bound_to_other_item` |
| chunker | `missed:not_sent` | 30 | 0.1 % | 1 | Dish and price blocks inside chrome (`a4911b31d522`) |
| harness | `missed:harness_collision` | 30 | 0.1 % | 14 | |
| [5] validator | `ground:price_before_name` | 29 | 0.1 % | 16 | |
| others | 12 smaller causes | 142 | 0.6 % | | `var/p8-x/stages.txt` lists them |

**Families by format and [5d] gate** (share of each slice's gold prices):

| Slice | Gold prices | Item missed | Wrong amount | Not grounded | Unpriced |
|---|---|---|---|---|---|
| All | 24,421 | 7.8 % | 4.1 % | 4.3 % | 2.3 % |
| `html_cards` | 2,624 | 8.1 % | 2.7 % | 7.0 % | 1.7 % |
| `html_inline` | 587 | 20.3 % | 2.0 % | 9.9 % | 2.4 % |
| `html_list` | 20,556 | 7.5 % | 4.2 % | 3.9 % | 2.5 % |
| `price_list` | 654 | 5.0 % | 5.4 % | 0.5 % | 0.8 % |
| [5d] gated | 20,069 | 6.2 % | 3.8 % | 3.2 % | 2.0 % |
| [5d] ungated | 4,352 | 15.3 % | 5.2 % | 9.3 % | 3.9 % |

Notes:
- **Format.** `html_cards` loses most to the validator: 95 of its 183 not-grounded prices
  are `run_stopped_by_heading`, a card's item-code heading ("C2") between its title and
  its price (36 on `05273895b4e2`).
- **`html_inline`.** It is the one format where "emitted under another name" dominates
  (58 of 119 missed), all on page `2f8e9a845c2b`.
- **Gate.** Ungated pages carry most of the run-stopper and model-miss losses. Of the
  379 run-stopper prices, 252 are on 27 ungated pages.

**The validator on a perfect answer** (gold rows, [5]+[5b] only; `var/p8-x/gold_fr.txt`):
it accepts 21,985 of 24,421 (0.900). Its losses are where its FR comes from:

| Cause on gold rows | Prices | Share | Pages |
|---|---|---|---|
| Price over 15 blocks away or a column layout | 490 | 2.0 % | 36 (`cfb443e9b654` 127) |
| Size label not grounded with the price | 466 | 1.9 % | 58 |
| Price printed before the name | 291 | 1.2 % | 41 (Dahlia Café 106) |
| Price-less heading between name and price | 268 | 1.1 % | 19 |
| Amount glued to text | 207 | 0.8 % | 29 |
| Another item's name block between name and price | 206 | 0.8 % | 38 |
| Region, other | 192 | 0.8 % | 45 |
| Price in the name's block, cut by another name | 106 | 0.4 % | 19 |
| The rest | 210 | 0.9 % | |

**Shared section prices** (`var/p8-x/shared.py`). A lost price counts as shared when the
nearest price-printing block above the dish prints the gold amount, and another labelled
dish lies between them. Examples:
- a heading such as "After 2PM - 13.99";
- a line under a heading: "$15 each", "Tofu or Paneer $17 | Chicken $17 | …", "Add an
  additional side for 3.79";
- a size chart ("6" Round-12-16 servings-$80").

That holds for **411** lost prices: 189 of the 568 unpriced, 106 missed, 72 wrong and 44
not grounded. It spans buckets, so it is a cause of its own (section 5, F3).

## 3. Mechanisms seen in the traces

These surfaced while reading the traced cases. Each is generic, with no site rule implied:
1. **The price on a wrong name.** The model emits the right price and block but names the
   row after something else on the record:
   - the section heading ("JUmbo tenders", "Thali");
   - an option ("Unsweet");
   - a description ("Hibiscus-Lemon-Rosewater mixed …");
   - the previous card's title;
   - an image's alt-text filename ("Pubs Classic Pies Cannonball").

   This is 1,052 prices, 752 of them on [5d]-gated pages, where the template knows which
   block holds the dish's name.
2. **One size of several.** A dish prints two or more prices: "Single $3.99 | Pint $6.99 |
   Quart $11.99", "$17.99 | $20.99", each and dozen columns, sushi and sashimi columns.
   The model emits the first, or puts the second in the variant slot ("v": "17.99"),
   which `rows_of` then drops as a bare number.
3. **Price scans that end too early.** Headings with no price end the validator's scan:
   - a dish's own repeated or bilingual heading (`83b9a566697a` prints each dish as
     `li`, `li` 中文, `h3`, `h3` 中文, then the price);
   - an item code ("C2", "M2").

   The scan also stops at a description the model emitted as an item.
4. **Shared section prices** (section 2). The model emits every dish of the section
   unpriced.
5. **Bilingual pages.** The model names a dish by its Chinese line (炒乌冬) while the
   label uses the English line, or prices the Chinese line and leaves the English one
   unpriced (`ab61da9d75b5`). This is 142 prices on 7 pages.
6. **A nameless price row.** The model emits the price as its own row with an empty name
   (`n='' p='11.99'`), and `rows_of` drops rows with no name. Rare: 5 prices.

## 4. Traced samples and the label check

The top five causes were sampled, along with `unpriced:price_not_printed_near` (tied
fifth) and the largest validator cause, `ground:run_stopped_by_heading`. Each sample is 10
cases, seed 20261026, at most 2 per page (`var/p8-x/sample.py`; the traces are in
`var/p8-x/cases/case-*.md`). Each trace gives:
- the page id;
- the gold item (name, block, section, amount, variant);
- the model's raw rows for it and those claiming nearby blocks;
- the final rows (decision, reasons, name and price Evidence);
- the segmented blocks around it.

Three sonnet subagents judged each case against `cases/rubric.md`: pipeline error, label
error or ambiguous. This session then made two passes:
- it re-checked **all four** label-error verdicts: two were confirmed and two overturned;
- it opened the full page for every case left ambiguous because the window didn't show the
  price, 19 cases. Eleven were resolved.

Final adjudication (`cases/labels-final.jsonl`):

| Cause | Pipeline error | Label error | Ambiguous | Notes |
|---|---|---|---|---|
| `missed:model` | 7 | 0 | 3 | One case is really an unsplit add-on list ("Mushrooms: $5, Sausage $7, …" emitted as one name). Ambiguous: an add-on, a topping list, a price-column page |
| `missed:emitted_other_name` | 8 | 1 | 1 | Two cases are image-alt names on a page whose dishes sit in chrome (`a4911b31d522`). The label error: "H16: Yellowtail" over "Yellowtail Handroll", which the model delivered correctly |
| `wrong:size_column` | 9 | 0 | 1 | One case is a shared protein line ("Chicken $18"). Ambiguous: a dal labelled with a lamb variant |
| `wrong:neighbour_price` | 6 | 1 | 3 | Two cases the subagent called label errors are Dahlia Café, which prints each price above its name (P8-15), so the labels are right. Two are shared section prices. Ambiguous: two on the price-column page and one where the label names the beer style |
| `missed:named_by_description` | 8 | 0 | 2 | One case is the price string emitted as the name ("14.95") |
| `unpriced:price_not_printed_near` | 6 | 1 | 3 | All six pipeline errors are shared section prices or size charts, a long way above the dish. The label error: "Mother Lode" copies another pizza's size prices |
| `ground:run_stopped_by_heading` | 10 | 0 | 0 | The model's amount is right in all ten; the validator's scan ends early |
| **All 70** | **54** | **3** | **13** | |

- **Label-error rate: 3 / 70 = 4.3 %, Wilson 95 % [1.5 %, 11.9 %].** Counting ambiguous
  too, 16 / 70 = 22.9 % [14.6 %, 34.0 %].
- **Clustering.** Cases cluster by page, so the true interval is somewhat wider. Four of
  the 13 ambiguous cases are one page, `cfb443e9b654`, which prints names and prices in
  separate column blocks.
- **A second draw** of `price_not_printed_near` (fresh seed, checked by this session on
  full pages) gives 6 / 2 / 2. Both of its label errors are one more pizza on that page
  (Marye's).
- **Applying the rate.** At the point estimate, about 190 of the 4,509 lost prices (0.8
  points of usable prices; interval roughly 70–540) are label errors, and up to about 1,000
  are open to argument.
- **Labels are not the bottleneck.** Pages whose pizzas borrow another pizza's size chart,
  and `cfb443e9b654`'s columns, are where an adjudication pass would pay (Q5).
- **Classifier vs traces.** The deterministic cause fits the trace in 50 of the 70 cases.
  - The 20 that don't fit are mostly shared section prices filed under another bucket
    (the reason section 2 measures them separately), plus the price-column page.
  - The two Dahlia cases belong under `price_before_name`: the amount is also printed
    again within the scan.
  - Two image-alt rows on a chrome page belong under `not_sent`.
  - The bucket counts are right to within these refilings; the mechanisms in section 3
    and the fixes don't depend on them.

## 5. Ranked fixes

Headroom is the dev gold prices lost to the cause. It is an upper bound: a fix recovers
only part of it, and dev is optimistic. "Pipeline share" is the sample's pipeline-error
share. Bars:
- a validator or [5b] change moves gold-row **FR** and corruption **catch**, and price
  accuracy;
- a [5d] change moves the Amendment 29 Q6 stage bars;
- a model, prompt or chunker change moves the **extractor key** and needs re-extraction and
  a held-out check.

| # | Fix | Stage | Generic | Headroom (gated / ungated) | Pipeline share | Bars it moves | Risk |
|---|---|---|---|---|---|---|---|
| F1 | **Price scan continues past** a price-less heading that repeats the row's own name or prints a short code, and past an emitted description row | [5] validator | Yes, layout only | 290 (heading 204, description row 49, other-language row 37): 1.2 %; 379 (127 / 252) with every scan stopper. On gold rows, 280 of the 2,436 not accepted | 10/10 | FR down (at most −0.011 on dev), catch, price accuracy | **Medium.** A heading ends a scan to stop it binding the next dish's price when that dish wasn't extracted; catch must be re-measured. Concentrated: 20 pages for the heading part |
| F2 | **[5d] RE-NAME from the template's name path.** On a gated page, a kept row named by its record's heading, option, description or alt text takes the record's title | [5d] | Yes, derived HTML | 1,052 (752 / 300): 4.3 % | 8/10 and 8/10 | Q6 stage bars, kept precision, recall | **Medium.** P8-14's DROP-of-the-title cases show title choice can lose items; needs the losing-pages bar |
| F3 | **Shared section prices.** An unpriced row under a heading, or a heading's price line, that prints one price (or a labelled set) for the section takes it, citing that line | [5b] resolver or [5d] | Yes | 411 (spread over buckets): 1.7 % | 6/10 in the bucket; 2 of the overturned neighbour cases | FR and catch if [5b]; resolver version | **Design fork (Q2):** an inferred item price from a section line. The labels treat it inconsistently (3 of the 5 label errors found copy another dish's size chart) |
| F4 | **[5d] ATTACH beyond labelled runs.** A template price block printing two or more prices with column headers or size labels gives each its row; a bare second price in the variant slot is kept as a price | [5d], plus one `rows_of` repair | Yes, derived HTML | 558 (413 / 145): 2.3 % | 9/10 | Q6 bars, price accuracy (variant labels), FR | **Medium.** Unlabelled price pairs are where swaps hide (§8's catch note) |
| F5 | **Amendment 30 as proposed** (g1f+G3, G2), already prototyped in P8-15 | [5] validator | Yes | claim drift + glued name 97; price-first layout 175 (Dahlia mostly) | — | FR, catch | G2's corpus false-gates: owner fork Q2 of Amendment 30 |
| F6 | **[5d] gate widening** | [5d] gate | Yes | +0.007 usable at most (oracle T) | — | Q6 bars, price accuracy on ungated pages (−0.005) | Low gain; not recommended now |
| F7 | **Model, prompt or chunker** (plain misses 588, chunk edges and chrome 84, bilingual 142) | [4] | Yes | Ceiling +0.084 usable (oracle extractor) | 7/10 | Extractor key, re-extraction | **The owner's GPU/LLM decision.** Derived fixes F2–F4 take the model-side losses they can reach first |
| F8 | **Repairs:** keep a nameless price row as the previous unpriced row's price; wine-scope misses | Repairs | Yes | 72 + 45 (wine is in scope by design) | — | Repairs version, recall | Low gain; wine scope is the owner's |
| F9 | **Labels:** fix the 3 confirmed label errors and the borrowed size charts; adjudicate the price-column page | Labels | — | About 190 (0.8 %) at the measured rate | — | All dev figures move a little | No pipeline risk; label changes are the owner's |

**Recommended order.** All three first steps are generic, derived from the page and the
model's own accepted output, with no per-page cases (the owner's direction):
1. **F1:** validator-only, cheap, measurable against FR and catch on the same harness. It
   could join Amendment 30 or be its own amendment (Q3).
2. **F2:** the largest reachable headroom, on derived HTML.
3. **F4:** its natural companion.

F3 needs Q2 answered first. F7 is the owner's.

## Owner questions

- **Q1. Order.** Pursue F1, then F2 and F4 (validator, then derived-HTML [5d] extensions)
  before any model or prompt work? *Recommended: yes. Together they address up to 1,989
  lost prices, 8.1 % of dev gold, as an upper bound. The extractor key stays the same, so no GPU re-extraction is
  needed.*
- **Q2. Shared section prices (F3).** Should Helios deliver an item's price when the page
  prints it once for the section (a heading or a line under it, a size chart), with
  Evidence on that line? If yes:
  - as a [5b]-style resolver, so validator bars apply;
  - or in [5d], on gated pages only.

  *Recommended: a [5b] resolver limited to a heading or the line right under it. Size
  charts more than one section away stay out.* This is a design fork.
- **Q3. F1's home.** Add the scan-continuation rules to proposed Amendment 30, which
  already changes [5]'s grounding, or make them Amendment 31? *Recommended: Amendment 31,
  so Amendment 30's measured result stays as it is.*
- **Q4. Add-ons.** The labels count some add-ons as items ("Add 2 Eggs $2.99", "add
  avocado 3", "Papas $2.95" in an add-on list) and not others. Should add-ons count as items
  for recall? *This changes recall's denominator, so it is the owner's call.*
- **Q5. Labels.** Correct the confirmed label errors (section 4) in a new labels revision.
  Also adjudicate the price-column page `cfb443e9b654` and the pizza pages that borrow a
  size chart (`3f54728f8c97`). *Recommended: yes, in their own PR, before the next dev
  measurement.*
- **Q6. Bilingual pages** (142 prices, 7 pages). When a page prints a dish in two
  languages, which name should the item carry? The labels use the English line. *It changes
  matching, the prompt or [5d], so the owner should decide.*

### Owner answers (2026-10-26)

- **Q1: yes.** F1 first, then F2 and F4, before any model or prompt work.
- **Q2: open.** The owner asked what "a whole section" means. The explanation is in the PR
  thread; the answer will be recorded here.
- **Q3: yes.** F1 becomes its own amendment (Amendment 31). Amendment 30 stays as P8-15
  proposed it.
- **Q4: add-ons are not items.** An add-on belongs to the item it modifies, listed under it,
  when the page's order makes that item clear. Otherwise it is dropped, or kept in an add-on
  section. Labels that count a bare add-on as an item ("Add 2 Eggs $2.99", "add avocado
  3") are to be corrected in the labels revision (Q5), and recall is measured without them.
- **Q5: yes.** A labels revision corrects the confirmed label errors and adjudicates
  `cfb443e9b654` (price columns) and `3f54728f8c97` (borrowed size charts) before the next
  dev measurement.
- **Q6: English.** A dish printed in two languages carries its English name.

PR #126 check (2026-10-26): P8-15's work is in draft PR #126. Its head moved from `ec02992`
(measured here) to `8ef07fa`. The two new commits add the Amendment 30 proposal, the P8-15
record and a README note, and change docs only. So this audit's figures hold for #126's head.

## Reproduction

`var/p8-x/run.sh` runs a script with `PYTHONPATH` pointing at the exported `ec02992` tree,
using the project's venv. The scripts carry this session's scratch paths, so re-point them
before re-running.

```
bash var/p8-x/run.sh var/p8-x/audit.py > audit4.jsonl     # oracles + causes, 793 pages, 14 workers
bash var/p8-x/run.sh var/p8-x/agg.py audit4.jsonl         # ceilings, buckets, sections
bash var/p8-x/run.sh var/p8-x/compact.py audit4.jsonl     # slice tables and paired changes
bash var/p8-x/run.sh var/p8-x/stages.py audit4.jsonl      # by stage
bash var/p8-x/run.sh var/p8-x/gold_fr.py                  # the validator on gold rows
bash var/p8-x/run.sh var/p8-x/shared.py audit4.jsonl      # shared section prices, label-error interval
bash var/p8-x/run.sh var/p8-x/alt_match.py                # harness match sensitivity
```

Checks:
- `same_as_prod` is true on all 793 pages: the re-implemented stream equals
  `llm_stream`;
- `var/p8-15/gap.py` re-run on the export equals `gap.txt` byte for byte;
- every lost price's family equals `loss_verdicts`'s (asserted);
- base gold-row FR 0.1008 and catch 0.9950 match P8-15's dev figures.
