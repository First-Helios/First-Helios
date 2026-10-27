# HTML/CSS structure analysis and a structural-signal hierarchy (P8-17)

Session P8-17, 2026-10-26. This is analysis and design only. The pipeline is unchanged, and
nothing was built, fetched or re-extracted. There were no model calls, no database access and
no laptop or Pi writes. The proposal is
[ADR-0021](../adr/0021-page-structure-model-and-signal-hierarchy.md) (Proposed; owner
questions there).

Scope:
- **Code.** `main` at 08bb684: `segment-v2`, `chunk-v2.3`, `repairs-v9`, `validator-v10`
  (#131 merged) and `resolve-v4`.
- **Dev.** P8-16's loader (`var/p8-16/pages.py`, labels-v10.1 overlay) over the 793-page
  gap-audit selection. Only the **420 pages whose labels carry items** (and have saved answers)
  are scored; see the page-count drift in 1.3.
- **Corpus.** P8-11's 863 page texts, with saved production answers.
- **No §8 claim.** Every number is dev or corpus.

Artefacts are untracked, under `var/p8-17/` in this worktree:
- the scripts `trace_santo.py`, `extract.py`, `analyze.py`, `confuse.py`, `records.py` and
  `packets.py`;
- their outputs, as `.txt`, `.jsonl` and `.md` files;
- `packets-judged.md`, the subagent's case judgements.

## Result

- **No stage before [5d] reads any HTML structure beyond the h1–h6 and chrome flags.**
  `Block.tag`, `Block.path` and `Block.classes` are computed and never read. [5c] and [5d]
  re-parse the HTML to get the element stack. "The dish's record" is computed six ways, by five
  block windows (2 to 15 blocks) and one DOM container. "Description line" is computed five
  ways, by five different text rules.
- **The class signature is the strongest structural signal**, used jointly with text shape. An
  oracle per-page majority on dev predicts block roles as follows:
  - class signature + text shape: **0.898** [0.872, 0.918];
  - tag path + text shape: 0.839;
  - class signature alone: 0.823;
  - text shape alone: 0.747;
  - tag path alone: 0.635.

  Where a page-learned class signature and a page-learned tag path both claim a block and
  disagree, the class is right 159 times and the path 0 times. The path is right 6 % of the
  time when it decides where the class is mixed.
- **Learned from the model's accepted rows, structure is not precise enough to mint items.**
  On blocks the model did not accept, a seed-learned "title" is a gold title in only 0.30–0.50
  of cases, depending on the level. The errors are add-on lines, alt-text echoes, and
  descriptions styled like titles. So structure should decide **relations** (which dish a line
  belongs to, which line is the title), not **existence**.
- **Records are mostly one dish each.** A template record whose title is unpriced holds exactly
  its title's dish in **0.871** [0.818, 0.914] of cases (218 pages).
- **What records lose today.** Inside template records, 1,490 gold title amounts are not
  delivered on dev. By cause:
  - 334 (F2): the title was not kept, and rows were kept elsewhere in the record;
  - 238 (F2/F4): the title was kept unpriced, with priced rows in the record;
  - 337 (F4): the title was priced, but amounts are missing;
  - 428: the model missed the record entirely;
  - 153: the title was kept unpriced, and nothing in the record was priced.

  A subagent check of 36 sampled loss records found that anchoring them on the title is right
  in 21 (F2/F4 move 9/12, F4 attach 8/12, F2 rename 4/12). The failures:
  - titles that are section headings;
  - add-on lines;
  - brand or category titles.
- **The santopatio layout is rare.** Choice lines under an unpriced title (≥ 2 "words $price"
  lines with "/", "," or "or") occur in 11 records on 5 dev pages and 12 records on 6 corpus
  texts. Santopatio itself has one: Nachos. Most look-alikes are add-on blocks, catering lists,
  or section cards ("Sauces", "Asian Can Drinks") whose lines are items. Choice lines are best
  treated as one trigger of the general record rewrite (F2/F4), not as a rule of their own.

## 1. How the pipeline reads HTML structure today (from code, main @ 08bb684)

Main runs `segment-v2`, `chunk-v2.3`, `repairs-v9`, `validator-v10` and `resolve-v4`.
`page_template.llm_stream` is the `llm` stream's post-model order:
`rows_of` → [5]+[5b] → [5d] → [5]+[5b] again → duplicate removal → [5c] → `menu_shape`.

### 1.1 Stage by stage

| Stage | Module | Structural signals it reads | What it ignores |
|---|---|---|---|
| [2] segment | `segment.py` | Builds `Block`: `tag` (innermost block ancestor), `path` (last 4 block tags, **no classes**), `heading` (inside h1–h6), `in_chrome` (nav/header/footer/aside/form/button/select), `classes` (innermost block ancestor's class/id tokens, cut to 120 chars). Skips dialogs. `text_hash` covers only heading/chrome flags and text. | Everything above the innermost block ancestor's classes, node identity (which `div` a block is in), inline elements' classes |
| [3] chunking | `chunking.py` | `in_chrome` (drop; v2.3 sends short priced chrome runs), `heading` (soft cut, context line) | tag, path, classes |
| [4] model | `prompt.py` | Only `bNNNN \| text` lines | All structure |
| [4b] `rows_of` repairs | `output.py`, `stitch.py` | `heading` (ends stitch price runs), `in_chrome` (`name_by_title`), block order (MAX_GAP 3, FILL_GAP 4, NAME_ABOVE 8), text shape (`_description_like`, `_is_description_line`, `_is_sentence_line`, `price_only`, lower-case starts), price tokens and labels | tag, path, classes, DOM |
| [5] validator | `validator.py` | `heading` (ends a price scan unless `own_heading`; section-price scope; `section_line`; list prices), `in_chrome` (`unlabeled_price_runs`), block order (SCAN 15, COLUMN_SCAN 200), text shape (`_is_price_only`, `_description`, `_header_cell`, `_NOT_ITEM`, `stacked`), price tokens and labels | tag, path, classes, DOM |
| [5b] resolve | `resolve.py` | `heading` (`_region` stop), block order, price tokens | tag, path, classes, DOM |
| [5d] page template | `page_template.py` | Re-parses the HTML (`dom_sections.placed_blocks`): per block the open-element stack (tag, class/id) and node ids. **Loose path** (last 3 block tags) for patterns; **class signature** (`dom_sections.signature`: last 3 block ancestors, tag + **first** class token, digits/uuids masked) only to admit split-pattern name candidates; record container = the pattern's lowest common block ancestor (node id); `heading` (wine lookback), `in_chrome`, text shape (`_description_like`, `_ADDON_LINE`, `_WORD_START`), price tokens and labels | Class tokens after the first; classes on the price side and on the record container; anything about blocks outside a seed pattern |
| duplicate removal | `page_template.remove_duplicates` | Name evidence block, price spans | All structure |
| [5c] sections | `dom_sections.py` | Same re-parse: heading level (h1–h6), class **words** (`_HEADING_CLASS` "categor/section/group/heading/header/title", `_NOT_HEADING_CLASS`), class signature (section styles), node ids (wrapped = lowest common ancestor) | Item-side classes |
| `menu_shape` | `menu_shape.py` | `heading`, `in_chrome` (`_section_block`), [5c]'s assignment | Everything else |

**What actually reaches a decision.** No stage reads `Block.tag`, `Block.path` or
`Block.classes`: grep over `packages/helios_parsing` finds them only in `segment.py`. The DOM
context [5c] and [5d] use comes from a second parse of the HTML (`_PlacingSegmenter`, a
subclass that records the stack). [5d] and [5c] share one re-parse inside `llm_stream`. Every
stage before [5d] works on block order and text alone, plus the h1–h6 and chrome flags.

### 1.2 One notion, computed several ways

| Notion | Where, and how |
|---|---|
| **Heading** | h1–h6 tag: validator (scan stop, section price, `section_line`), `stitch` (run stop), `resolve._region`, `chunking` (cuts), `menu_shape._section_block`. Class words: [5c] `_candidate`. A short unpriced line of ≤ 4 words: [5d] `under_wine`. The model's section text matched to a block: `menu_shape`. |
| **The dish's record (which lines belong to which dish)** | Validator: name block + up to 15 blocks, to the next item or heading. `stitch`: 1..3 blocks (merge), 4 (fill). `output.printed_name_block`: 8 above. `drop_unprinted_variants`: 2 above to 4 below. `resolve._region`: a scan to an item or heading. [5d]: the DOM container (lowest common block ancestor of the seed pattern), with 8 blocks of lookback. Only [5d] uses the DOM. |
| **Description line** | `output._description_like` (≥ 2 commas, a final period, or ≥ 8 words); `stitch._is_description_line` (lower-case and > 25 chars, or > 40 chars with ≥ 2 commas); `stitch._is_sentence_line` (≥ 7 words, or > 25 chars ending "."); `validator._description` (> 8 words, a final ".", or > 60 chars); `validator._NOT_ITEM` (lower-case start, a trailing ":", nutrition words, a 6+ word sentence). |
| **Price-only line** | `stitch.price_only` and `validator._is_price_only` (both ≤ 12 letters besides prices: the same rule written twice); `validator._cell` (no letter at all). |
| **Add-on line** | `validator.is_addon` ("+" or "add" right before the price); [5d] `_ADDON_LINE` (line starts with +/add/extra/sub/substitute). |
| **Item-title style** | [5d]: seed name blocks' loose path, plus class signature for split patterns. `output.name_by_title`: a short unpriced line of ≤ 6 words, not description-like. [5c]: a dish `h3` is a heading style that encloses no item of another signature. The validator has no notion of style; it grounds name tokens. |
| **Layout signature** | `dom_sections.signature` (3 ancestors, first class token) in [5c] and [5d]; [5d] `_loose` (3 tags); `Block.path` (4 tags, unused); `Block.classes` (all tokens of the innermost ancestor, unused); [5c] `_own_classes` (innermost block plus inline elements, instance ids dropped). |

### 1.3 Drift found
- [5d]'s module docstring says "classes are not trusted, since a site may style an item line
  like a description". The code does use the class signature, to admit split-pattern name
  candidates (`name_classes`). What is untrusted is class *words*; class *identity* is used.
  [5c] does read class words (`_HEADING_CLASS`).
- The task brief says "Block.path carries no class". That is true, but `Block.classes` does
  carry the innermost block ancestor's classes. No stage reads it, and `text_hash` excludes it.
- **Page-count drift.** The P8-x and P8-16 "793 dev pages" are 420 pages whose labels carry
  items, plus 373 menu pages whose labels are classifier-only. The latter come from
  p5-29 r1a, the p5-31 census, p5-30, p5-32 and p5-29 r1b, and have no `items` key.
  `measure.py` scores those 373 as menus with zero gold items. They add nothing to recall or
  usable prices, but they enter kept precision and accepted-unmatched. Section 3 scores only
  the 420.
- **Label drift.** santopatio is on dev as `dev:e6942e6d1e2a` (labels-v9 from p5-26, no v10
  overlay). It labels Nachos with three variants named by the whole line ("Chicken / Bistec /
  Pastor" 14.99, …), not one variant per choice as the owner's choice-list ruling has it.
  Usable prices are scored by (item, amount), so they are unaffected, but variant counts are
  not.

## 2. The santopatio Nachos card through every stage

Corpus text `c80ab7cf…` (600 blocks; the re-parse matches the Version's blocks). Output of
`var/p8-17/trace_santo.py`:

| Stage | What it sees or does for b0168–b0172 | Class information |
|---|---|---|
| HTML | `div.food-item-holder.menu_item_5866946` > `div.food-item-title` "Nachos", then `div.food-item-description` > `p` with three `<br>`-separated price lines and the description. Normal cards also have a `div.food-price` (217 title blocks, 506 holder tokens on the page); Nachos has none. | All present |
| [2] segment | b0168 `div` path `div/div/div/div` classes `food-item-title`; b0169–b0172 `p`, path `div/div/div/p`, classes `''` (the `<p>` has none) | `Block.classes` keeps only the innermost block element's classes: the lines lose `food-item-description` and the holder. Nothing downstream reads it anyway. |
| [3] chunks | `b0168 \| Nachos`, `b0169 \| Chicken / Bistec / Pastor $14.99`, … | Gone (text lines only) |
| [4] model | "Nachos" unpriced; three rows named by the lines at 14.99 / 15.99 / 16.99; "Corn tostadas" unpriced | — |
| [4b] `rows_of` | Unchanged. Stitch has nothing to merge: each line is a priced row with its own words, not a price line (`_is_price_line`) or description line | Not read |
| [5]+[5b] | Nachos downgrade `no_price_extracted`; the three line rows **accept** on their own blocks; "Corn tostadas" downgrade | Not read |
| [5d] | **Gated**: 215 seeds, explained 0.953, agree 0.873. The main pattern (179) is name `div/div/div` → price `div/div/div`, offset 1, LCA `div`. The **second pattern (26) is the choice lines themselves** (same-block `div/div/p`): 29 of the seeds' names have class signature `food-item-holder/food-item-description/p`. The lines are seeds, so no action touches them; DROP removes "Corn tostadas" | Read from the re-parse: the loose path drops classes, and the class signature (first token) only admits split-pattern name candidates. The record container (the holder) is known, but no rule asks "does this line sit in another title's record?" |
| dup removal | Nothing | — |
| [5c] | Gated (assigned 1.0); sections from `h2.menu-section-name` | Class words and signature, sections only |
| final | "Nachos" unpriced; "Chicken / Bistec / Pastor" 14.99, "Birria / Beef Fajita" 15.99, "Shrimp / Combo" 16.99 as three items | — |

**Where it's lost.** The structure that decides the case is that b0169–b0171 sit in the record
(`food-item-holder` node) whose only title-signature block is b0168. It exists in the re-parse
at [5d] and is never consulted. Two parts of the current design block it:
- [5d] learns the lines as a second item pattern, because they are accepted seeds;
- [5d] acts only on rows named inside another candidate's record when they are description-like
  or label-only (ATTACH needs the row's whole name to be a ≤ 4-word price label beside the
  price).

## 3. Measurements (dev, labels-v10.1, 420 item-labelled pages; no model calls)

### 3.1 Block roles

Gold roles are derived from labels-v10.1 per non-chrome block (104,645 blocks):
- **title**: a gold name block (27,040);
- **price**: a price-only block printing a gold amount after the name (17,973);
- **variant**: such a block with words beside the price (883);
- **description**: an unpriced lettered block inside a gold item's span (35,483);
- **section**: the block printing a gold section name (3,348);
- **add-on**: a modifier price, "+"/"add", that is no gold price (477);
- **other**: the rest (19,441).

The 18 dev pages with the spike's hand block roles check the derivation. It agrees for:
- item → title 1,026 / 1,071;
- price 778 / 815;
- description 419 / 470;
- section 109 / 132.

It mostly misses modifiers (9 / 81). Add-on figures below are weak.

Signals per block (from `dom_sections.placed_blocks`):
- **cls**: `dom_sections.signature`, the last 3 block ancestors, tag + first class token,
  masked;
- **cls_all**: the same with all class tokens;
- **path**: the [5d] loose path, 3 tags;
- **depth**: block-level ancestors;
- **sib**: the ordinal among blocks under the same parent;
- **shape**: price-only, priced ≤ 7 words, priced > 7 words, ≤ 3 words, 4–6 words,
  description-like, longer, symbols.

**A. Oracle: what the signal can say on a page.** Each block is predicted by the majority gold
role of the other blocks on its page with the same signal value (leave-one-out; ties and
singletons abstain). Page-clustered 95 %:

| Signal | Accuracy | Coverage | Recall: title / price / variant / description / section |
|---|---|---|---|
| cls + shape | **0.898** [0.872, 0.918] | 0.959 | 0.94 / 0.97 / 0.73 / 0.88 / 0.79 |
| path + shape | 0.839 [0.817, 0.858] | 0.974 | 0.87 / 0.89 / 0.71 / 0.85 / 0.66 |
| cls_all | 0.836 [0.810, 0.860] | 0.951 | 0.89 / 0.84 / 0.31 / 0.81 / 0.74 |
| cls | 0.823 [0.793, 0.850] | 0.964 | 0.85 / 0.82 / 0.38 / 0.84 / 0.81 |
| depth + sib | 0.801 [0.778, 0.825] | 0.957 | 0.86 / 0.79 / 0.36 / 0.78 / 0.71 |
| shape | 0.747 [0.727, 0.769] | 0.986 | 0.74 / 0.89 / 0.72 / 0.82 / 0.04 |
| path | 0.635 [0.603, 0.668] | 0.976 | 0.64 / 0.47 / 0.35 / 0.70 / 0.67 |
| depth | 0.627 [0.598, 0.658] | 0.955 | 0.61 / 0.43 / 0.26 / 0.65 / 0.63 |
| sib | 0.589 [0.560, 0.622] | 0.966 | 0.60 / 0.41 / 0.11 / 0.71 / 0.03 |

The class signature beats the tag path by 0.19 on its own and by 0.06 with text shape. Its
gain is in telling a price block from a title block where both share tags (price recall 0.82
against 0.47). All class tokens (cls_all) add little over the first token.

**B. Learned from seeds: the production-shaped version.** For each page, a value → role map is
learned only from the model's accepted rows:
- **title**: the name blocks of accepted rows that have a price block;
- **price** or **variant**: their price blocks;
- **description**: unpriced lettered blocks inside the seed's name/price lowest common
  ancestor;
- **section**: the block printing a kept row's model section.

A value is trusted with ≥ 3 seed blocks and ≥ 0.8 agreement ([5d]'s `MIN_SUPPORT`,
`GATE_AGREE`). It is scored on the **48,447 non-seed blocks** (the blocks a structural rule
would act on). Seed roles against gold, on the seed blocks themselves:

| Seed role | Gold role |
|---|---|
| title (20,425) | title 0.80, description 0.11 |
| price (17,359) | price 0.91 |
| variant (659) | variant 0.78 |
| description (14,262) | description 0.88 |
| section (3,493) | section 0.54 (noisy) |

| Learned signal (non-seed blocks) | Accuracy | Coverage | Title P / R |
|---|---|---|---|
| cls + shape | 0.423 [0.313, 0.534] | 0.342 | 0.50 / 0.23 |
| cls_all | 0.386 [0.315, 0.464] | 0.318 | 0.47 / 0.24 |
| path + shape | 0.368 [0.277, 0.463] | 0.389 | 0.44 / 0.21 |
| cls | 0.363 [0.286, 0.442] | 0.345 | 0.41 / 0.21 |
| depth + sib | 0.309 [0.243, 0.379] | 0.386 | 0.38 / 0.22 |
| path | 0.230 [0.159, 0.319] | 0.328 | 0.41 / 0.15 |
| shape | 0.219 [0.166, 0.281] | 0.577 | 0.25 / 0.17 |

**C. Hierarchies (first trusted level decides), learned from seeds, on non-seed blocks:**

| Order | Accuracy | Coverage | Title P / R |
|---|---|---|---|
| cls+shape > path+shape > shape | 0.263 [0.208, 0.328] | 0.654 | 0.33 / 0.28 |
| cls_all > cls > path > shape | 0.242 [0.192, 0.300] | 0.722 | 0.32 / 0.29 |
| cls > path > shape | 0.238 [0.188, 0.296] | 0.713 | 0.30 / 0.26 |
| path > cls > shape | 0.233 [0.184, 0.290] | 0.713 | 0.31 / 0.26 |
| cls > path > depth+sib > shape | 0.232 [0.185, 0.287] | 0.753 | 0.31 / 0.29 |
| path > shape | 0.223 [0.174, 0.279] | 0.675 | 0.31 / 0.22 |

**cls against path where both are trusted** (non-seed blocks):
- they disagree on 434 blocks: cls right 159, path right 0;
- cls decides alone on 6,034 blocks, right in 2,567 (0.43);
- path decides alone on 5,197 blocks, right in 319 (0.06).

A tag path that is trusted while the class signature underneath it is mixed or thin is
nearly always wrong. Backing off from class to path adds coverage, not correct answers.

**Why seed-learned precision is low** (`confuse.py`): wrong "title" predictions concentrate on
8 pages (2,031 of them) and are:
- add-on lines sharing the item class ("Add avocado$1", "Extra Spicy$1");
- image alt-text echoes ("Margarita Pizza photo", "Hot & Sour Soup Dish Presentation");
- descriptions with the title's markup (classless `p`, a282f08c5f3e);
- out-of-scope wine lines.

On classless and Wix-style pages (hashed classes masked to one token), name and price blocks
share one class signature, and only text shape separates them. Seed sections (from the model's
section names) are too noisy to learn from: 1,612 gold titles were predicted "section".

### 3.2 Whether a page's class pattern can be trusted, by format

Seeds' name blocks; a page passes with ≥ 5 seeds and ≥ 0.8 of them on one value:

| Format | Pages | ≥ 5 seeds | name cls ≥ 0.8 | name path ≥ 0.8 | (name, price) cls ≥ 0.8 | [5d] gated | names with a class (≥ half) |
|---|---|---|---|---|---|---|---|
| html_list | 307 | 242 | 189 | 221 | 166 | 201 | 240 |
| html_cards | 95 | 55 | 33 | 45 | 31 | 40 | 54 |
| price_list | 11 | 11 | 9 | 11 | 9 | 11 | 9 |
| html_inline | 7 | 7 | 7 | 7 | 7 | 7 | 7 |
| **dev** | 420 | 315 | 238 | 284 | 213 | 259 | 310 |
| **corpus** | 863 | 587 | 435 | 524 | 383 | 478 | 580 |

(Format is from the labels; the 7 html_inline and 11 price_list pages are too few to read.)
- **Classes are present.** Nearly every seeded page (310 / 315, and 580 / 587 on the corpus)
  names its items in classed elements.
- **Class agreement is stricter than path agreement**: 238 dev pages against 284. It is weakest
  on html_cards (33 of 55): cards style title and description blocks in several class
  variants.
- **The class level must therefore fall back.** Where a page's class pattern is mixed, the
  fallback is the record/positional default, not the tag path (3.1 C).

### 3.3 Records

A **template record** is the container of the page's main split title signature (the most
common class signature of seed name blocks whose price is in another block). Its depth is the
seeds' name-to-LCA distance. Dev: 271 pages have one; corpus: 507.

**Purity.** Records whose title block is unpriced, and whose box holds no second title block:
- 12,436 hold exactly the title's dish;
- 142 hold the same dish labelled on another copy of its name;
- 1,573 have no gold dish (out-of-scope wine, add-on headings, sections, model-kept non-items);
- 264 hold other dishes with the title unlabelled;
- 31 hold the title's dish plus others.

One dish per record: **0.871** [0.818, 0.914] (218 pages). Records whose "title" is priced are
mostly price blocks that share the title's signature (classless or masked-hash pages), so they
are excluded.

**Price layouts of template records:**

| Kind | Dev records (pages) | Corpus records (texts) |
|---|---|---|
| single price block | 11,840 (186) | 19,600 (332) |
| title priced (inline, or a price block sharing the signature) | 3,288 (96) | 5,126 (185) |
| several price-only blocks | 2,251 (97) | 4,085 (185) |
| several priced blocks, other shapes | 338 (74) | 570 (138) |
| **choice lines** (≥ 2 "label $price" lines, a "/", "," or "or" in a label) | **11 (5)** | **12 (6)** |
| label lines without choices | 6 (5) | 28 (11) |
| no price | 2,600 (111) | 4,716 (233) |
| box with two or more title blocks (flat list, not a record) | 6,182 (68) | 8,778 (132) |

**Gold title amounts not delivered today, inside template records** (dev, 1,490; upper bounds):

| Cause | Amounts | Pages | Maps to |
|---|---|---|---|
| Title not kept, record empty | 428 | 115 | model miss (ADD territory, not structure's) |
| Title priced, some amounts missing | 337 | 67 | F4 ATTACH |
| Title not kept, rows kept elsewhere in the record | 334 | 73 | F2 RE-NAME |
| Title kept unpriced, priced rows in the record | 238 | 57 | F2 / F4 move |
| Title kept unpriced, nothing priced in the record | 153 | 57 | — |

Corpus, the same buckets as record counts (no gold):
- 4,713 records on 236 texts: title not kept, rows kept in the record;
- 3,300 on 211: the title priced, but the record prints more priced blocks than its accepted rows;
- 420 on 132: the title kept unpriced, rows kept in the record.

**Choice lines on dev today** (11 records):
- 9 titles unpriced, 7 not kept;
- 27 line rows kept as items;
- 2 of the 11 gold title amounts delivered.

Gold reads 4 records as one dish with the lines as variants (santopatio's Nachos among them).
In 7 records the title is no gold dish: add-on blocks, catering trays, a "Sauces" card whose
lines are items.

### 3.4 Label and structure check (sonnet subagent; main session re-checked cases 11, 14, 33)

36 sampled loss records (12 per structural cause, at most 2 per page) plus the 17 choice- and
label-line records were each judged on three questions (`packets-judged.md`):
- A, does the record hold one dish?
- B, is gold right?
- C, would anchoring every kept row in the record on the title be right?

| Bucket | Cases | A one dish | B gold right | C anchoring right |
|---|---|---|---|---|
| Title kept unpriced, priced rows in record | 12 | 12 | 12 | 9 |
| Title priced, amounts missing | 12 | 11 | 9 | 8 |
| Title not kept, rows elsewhere in record | 12 | 10 | 8 | 4 |
| Choice lines | 11 | 4 | 10 | 5 |
| Label lines | 6 | 2 | 4 | 1 |

Failures of C:
- **The title is a section heading** with several dishes as lines ("Asian Can Drinks", "Add-Ons",
  catering trays); 12 cases.
- **Add-on or modifier lines** kept as rows; 7.
- **Brand or category titles** whose description line is the real dish name ("AUSTIN
  EASTCIDERS" / "Pineapple Cider"); 3. RE-NAME would lose the name.
- **The kept price is wrong or unprinted**; 4. Anchoring can't fix these.

Gold problems:
- case 28 is wrong (the category named instead of the dish);
- case 11 is empty while the record prints priced drinks;
- cases 33 and 38 are inconsistent about brand titles;
- four cases are partial.

These are candidates for the next labels pass. They were not changed here.

## 4. Design (proposed in ADR-0021)

The ADR holds the decision. This section records the reasoning from the measurements.

1. **One page-structure model.** It is computed once from the existing re-parse and
   replaces the per-stage windows and re-derived notions of 1.2. It is introduced stage by
   stage, each stage behind its own version bump and measurement. Its contents:
   - per block: node chain, class signature, tag path, text shape;
   - per page: the seed template, the record containers and the record membership of every
     block.
2. **Relations, not existence.** Measured seed-learned title precision on non-seed blocks is
   at most 0.50 (3.1 B), so a block's class never creates an item by itself. Structure decides
   two things:
   - which kept row belongs to which record;
   - within a record, which block is the title and which lines are its prices or variants.

   Every rewritten row is judged again by the unchanged validator and [5b], as [5d] does
   today.
3. **The hierarchy follows the measured order.** Within a gated page:
   - record membership first (purity 0.871);
   - then the class signature jointly with text shape (0.898 oracle);
   - the tag path with text shape only for blocks with no class tokens;
   - position within the record only as a tie-break;
   - text shape as a veto at every level (add-on lead, alt-text echo, description-like,
     price-only).

   Path never overrides a mixed class group (3.1, 0.06).
4. **Section-like titles.** The main residual risk (3.4) is a record whose title is a section
   heading: its lines are items. The page's own template gives a test. A dish record on that
   page normally has a price slot (santopatio: `food-price`). A record that lacks the slot,
   and whose priced lines stand where it would be, is a dish with options. A record whose
   title never takes a price slot on the page is a heading. This is a design fork for the
   owner (ADR-0021 Q3) and is unmeasured here.
5. **The Nachos card under the design.** The page is gated, and the holder record's only title
   block is b0168, kept by the model. The three choice lines are in the record, and the record
   lacks the page's price slot. So the lines' rows move onto "Nachos":
   - each line's label becomes its variant;
   - each choice ("/") becomes one variant at the line's price (the owner's ruling);
   - that gives seven variants, which the validator re-judges against labels printed with each
     price.

   F2 (RE-NAME), F4 (ATTACH) and choice lines are three triggers of one record-anchored
   rewrite. The choice-line trigger alone reaches about 9 gold amounts on dev; F2/F4 reach up to
   909.

## 5. Reproduction

```bash
cd .claude/worktrees/p8-17-html-structure   # needs var/p8-16 (P8-16 worktree) and var/p8-15
PYTHONPATH=. .venv/bin/python var/p8-17/trace_santo.py          # section 2
PYTHONPATH=. .venv/bin/python var/p8-17/extract.py dev > var/p8-17/dev.jsonl
PYTHONPATH=. .venv/bin/python var/p8-17/extract.py corpus > var/p8-17/corpus.jsonl
PYTHONPATH=. .venv/bin/python var/p8-17/analyze.py              # 3.1 A–C
PYTHONPATH=. .venv/bin/python var/p8-17/confuse.py              # 3.1 errors
PYTHONPATH=. .venv/bin/python var/p8-17/records.py              # 3.2, 3.3 layouts
PYTHONPATH=. .venv/bin/python var/p8-17/packets.py > var/p8-17/packets.md   # 3.4 packets
```

`item_pages.json` lists the 420 + 15 item-labelled page ids (the 15 have no saved answers).
`PYTHONPATH=. .venv/bin/python var/p8-17/buckets.py` gives 3.3's purity, loss buckets and corpus
candidates (`buckets.txt`) from `dev.jsonl` and `corpus.jsonl`.
