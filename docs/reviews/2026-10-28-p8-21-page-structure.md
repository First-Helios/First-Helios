# The page-structure model and the [5d] record rewrite (P8-21, ADR-0021 step 1)

Session P8-21, 2026-10-27/28. ADR-0021 step 1, built on the branch and measured; **not applied**
to `helios_laptop` or the Pi. The proposal is ADR-0013
[Amendment 33](../adr/0013-phase5-menu-pipeline.md) (owner questions there).

Scope:
- **Code.** `main` at 633ac61 (after #136): `segment-v2`, `chunk-v2.3`, `repairs-v9`,
  `validator-v10`, `resolve-v4`. The build is `resolve-v5` (commits 290aabf, 1a3077d).
- **Dev.** The gap audit's 793 pages (P8-16's loader). Results are reported on the 420
  item-labelled pages (ADR-0021 Q6); the 331 of them with a priced gold item are scored.
  After P8-20's re-collection (2026-10-28/29), 29 more labelled page texts gained saved
  answers (P5-31's census set, 3 of them scorable), so a fresh run loads 822. Every comparison
  here uses the pages present in both runs, which is the original 793.
- **Build check (2026-10-30).** After the owner's ruling, R2 is built into `resolve-v5`. Its
  verdicts equal the measured R2 patch on every page (0 of 1,656 differ), and so does
  invariance. The "v5 + R2" column below is the build.
- **Labels.** labels-v10.2 (section 1), confirmed by the owner before measuring.
- **Corpus.** P8-11's 863 page texts, with saved production answers.
- **No model calls, no database, no fetch.** No §8 claim: every number is dev or corpus.

Scripts and outputs are untracked, under `var/p8-21/` in this worktree.

## Result

- **labels-v10.2** (owner, 2026-10-28, all as recommended): 30 changes on 5 pages.
- **`resolve-v5` as ruled** (ADR-0021 Q3 (a)):
  - usable prices **+0.0018** [+0.0004, +0.0031];
  - gold prices +63 −21, gold items +8 −18;
  - **two stage bars fail**: item recall (0.9339 against 0.9345) and section exact.
  - The 18 lost items are heading cards. Santopatio's "A La Carte" taco lists (16) lack the
    page's price slot exactly as a dish with options does. The slot test can't tell them apart.
- **With R2** (label lines move only in a record that holds a choice line; part of Q3 (b);
  measured as a patch, not built):
  - usable prices **+0.0025** [+0.0015, +0.0037];
  - gold prices **+62 −2**, gold items **+8 −0**;
  - no page loses a gold item;
  - kept-item precision +0.0014;
  - **one stage bar fails**: section exact, 0.7607 against 0.7617, from a single page whose
    [5c] gate tips (section 3.3).
- **Unchanged** in both variants: price accuracy, gold-row FR, catch (that harness runs
  without [5d]), ungated pages (0 of 73 change).
- **Invariance** through `llm_stream`: total flips fall 6,653 → 6,606 (R2: 6,607). No pair is
  added, after the fix in section 2.4.
- **Chunk boundaries** split 2.2 % of records. At most about 28 dev gold prices hang on it, and
  a chunker change is an extractor-key change, so chunking is unchanged (section 4).
- **Reach is far below P8-17's headroom** (+62 gold prices against up to 909). By design, the
  rewrite moves only accepted rows and attaches only labelled prices.
- **Santopatio:** Nachos 7 variants, Quesadilla 6, all accepted.

## 1. labels-v10.2

The overlay is `var/menu-eval/labels-v10.2/dev/<page>.json` (main checkout), built from
labels-v10.1 by `var/p8-21/build_v10_2.py` (diff: `labels-v10.2-diff.jsonl`). The owner reviewed
the review page and accepted every recommendation.

| Page | Change | Count |
|---|---|---|
| `e6942e6d1e2a` (santopatio) | Nachos and Quesadilla: one variant per choice (Q4) | 2 items, 13 variants |
| `86a32e6109e4` (case 28) | the 7 chakra smoothies take the dish line's name ("I LOVE" → "GO GREEN- HEART CHAKRA", cited on that line) | 7 |
| `bb7f2aea0431` (case 33) | a brewery or cidery title over a product line: the label names the product line ("AUSTIN EASTCIDERS" → "Pineapple Cider"); style-only seconds and MODELO keep the title | 12 |
| `e084e3998df8` (case 38) | "Pinthouse Brewery Electric Jellyfish IPA" → "Electric Jellyfish IPA", and 5 more (Karbach / "Light Lager" included) | 6 |
| `2a1dd2be611f` (case 11) | the product-list cards (Asian Can Drinks, Bottled Drinks, Energy Drink) become one item per product; Peace Iced Tea's flavours stay variants | 3 cards → 14 items |

- **Finding:** P8-17's "case 11 gold is empty" was wrong. The label sits on the card's
  alt-text echo (b1048), one block before the record.
- **Not swept** (owner, D): other dev pages with producer cards. They wait for the next labels
  pass.

## 2. What was built

### 2.1 `packages/helios_parsing/page_structure.py` (ADR-0021 D1)

Stdlib. It's built from `dom_sections.placed_blocks` (the re-parse [5c] and [5d] share) and from
the first judge's seeds. Nothing is stored.
- **Per block:** node chain, class signature (unchanged `dom_sections.signature`), tag path,
  one text shape:
  - `price` (nothing printed before the price);
  - `addon`, `label` (≤ 8 words), `priced`;
  - `title` (≤ 6 words), `description` (`output._description_like`), `text`, `symbols`.
- **Title signature:** the most common class signature of split seeds' name blocks, with
  ≥ 3 seeds and ≥ 0.8 of its seed-role blocks titles. Ties are broken by value, not seed order.
- **Records:** each unpriced, non-chrome, non-description block of the title signature. The
  record is its container at the seeds' depth, holding no second title block; a flat list is
  no record.
- **Price slot:** the most common class signature of those seeds' price blocks. A record
  holds it through a block of that signature that prints a price alone. The page is
  *slotted* when ≥ 0.8 of its priced records hold the slot.

### 2.2 The record rewrite (`page_template`, before [5d]'s per-row actions)

On a gated page, an accepted row named and priced inside another title's record moves onto the
title, when the record passes the slot test: it holds the slot, or the page is slotted.
- **Choice and label lines** ("Chicken / Bistec / Pastor $14.99", "BOWL $9.95"): the title's
  variants, one row per choice. Such same-block seeds no longer count as an item pattern.
- **RE-NAME:** a row whose name is a description or an option list takes the title's name.
  - A row named by a short line that is no description keeps its name (Q8).
  - A row the title already holds at its amount is dropped.
- **ATTACH:** a labelled price in the record that no accepted row cites gives the title one row
  per choice. Add-on prices are never attached.
- The title's own unaccepted, unpriced copy is dropped once a moved row carries its price.

### 2.3 Two safety rules added in the build (not in ADR-0021)

- **All or nothing per record.** When one accepted label line of a record stays an item, none
  of its lines moves. A half-moved record lost the moved rows too, because the validator's
  scan from the title stops at the line left behind. Dev: 5791fcd7156e's catering trays.
- **No harm** (`llm_stream`). After the re-judge, a rewritten row the validator no longer
  accepts goes back to the model's row, and an attached price it doesn't accept is not
  attached; then one more judge. This is D2 level 0, "structure never overrides a seed's
  grounding". Dev: "fried egg $1" on 35fde4822b24.

### 2.4 One fix found by the invariance suite

ADD skipped every block inside a record that passed the slot test. On 29612ad9e3eb that
suppressed 18 correct ADD rows: 77 → 62 accepted gold pairs, and two added style pairs
(`variant_in_name`). ADD now skips only records the rewrite moved rows onto (1a3077d). The pairs
are gone, and the page is back to 77 of 77.

### 2.5 Version, tests

- `resolve-v4` → `resolve-v5`. `method_version` stays 127 of 128 characters, so no migration.
- New tests: `test/test_parsing_page_structure.py`, covering shapes, records, flat lists,
  choice lines, slot test, Q8, ATTACH, ungated identity.
- `test_parsing_page_template.py`'s split-card case now reads the size labels from `anchored`:
  the same rows, through the rewrite.

## 3. Measurements (labels-v10.2; 331 scorable item-labelled pages; page-clustered 95 %)

### 3.1 Before / after

| Measure | resolve-v4 | v5 as ruled | v5 + R2 |
|---|---|---|---|
| Item recall | 0.9204 | 0.9199 (−0.0004 [−0.0020, +0.0005]) | **0.9207** (+0.0003 [+0.0001, +0.0006]) |
| Kept-item precision | 0.8068 | 0.8080 (+0.0012) | **0.8081** (+0.0014 [+0.0005, +0.0025]) |
| Usable prices | 0.8210 | 0.8228 (+0.0018 [+0.0004, +0.0031]) | **0.8235** (+0.0025 [+0.0015, +0.0037]) |
| Price accuracy | 0.9851 | 0.9850 | 0.9851 |
| Gold-row FR | 0.0877 | 0.0877 | 0.0877 |
| Corruption catch | 0.9950 | 0.9950 | 0.9950 |
| Section exact | 0.7350 | 0.7347 | 0.7342 |
| Accepted rows matching no label | 2,465 | 2,451 | 2,433 |
| Wrong-price accepts | 308 | 311 | 309 |
| Gold prices delivered | | +63 −21 | +62 −2 |
| Gold items found | | +8 −18 | +8 −0 |

### 3.2 Amendment 29 Q6 stage bars (gated pages, against resolve-v4)

| Bar | v5 as ruled | v5 + R2 |
|---|---|---|
| Item recall not lower | **FAIL** 0.9339 / 0.9345 | pass 0.9349 |
| Kept-item precision not lower | pass 0.8301 / 0.8285 | pass 0.8302 |
| Accepted rows matching no label ≤ +1 % of kept rows | pass −14 | pass −32 |
| ≤ 1 gated page in 10 loses a gold item | pass 2 / 258 | pass 0 / 258 |
| Section exact not lower | **FAIL** 0.7614 / 0.7617 | **FAIL** 0.7607 / 0.7617 |
| Ungated pages unchanged | pass (0 / 73) | pass |

### 3.3 Where the losses are

- **Heading cards (v5 as ruled):**
  - santopatio's two "A La Carte" cards (16 taco items: "• Al Pastor $3.75" …);
  - a sauces card (p814:45562bdfb769, 5);
  - catering trays (5791fcd7156e, 2);
  - two add-on-like lines.

  All lack the page's price slot. So do Nachos and Quesadilla, which is the case Q3 (a) exists
  for. The difference is wording: dish-with-options cards print choice lists ("/", "or", ",");
  heading cards print one dish name per line. R2 adds exactly that condition, and the
  heading-card losses go.
- **Section exact.** One page decides it in both variants: held:12bf8e6a3406.
  - v5 renames an accepted description row onto its card title "Sausage and Pepperoncini",
    which is a gold item: right.
  - [5c]'s page gate (≥ 90 % of kept items assigned) then fails, and the page's 34 scored items
    lose their DOM sections (31 → 13 exact).
  - Every other changed page gains exact sections (R2: +7 on 11 pages).
  - ADR-0021 step 2 ([5c] takes its records from the same model) is where that gate would be
    revisited.

### 3.4 Invariance (ADR-0017 item 1, through `llm_stream`, with HTML)

The invariance suite and `corruption_eval` call `judge` without HTML, so they can't see [5d].
This session ran `invariance.invariance_page` with `llm_stream` as the harness on the 331 pages:
- resolve-v4: 6,653 flips;
- v5: 6,606, R2 6,607;
- **0 added page/style pairs.**

### 3.5 Corpus (863 texts)

| | v5 as ruled | v5 + R2 |
|---|---|---|
| Texts changed | 72 | 68 |
| Accepted rows | +48 | +46 |
| Distinct price spans | +37 | +35 |
| Kept items | −102 | −56 (variants folded onto titles) |
| Variants | +159 | +103 |
| Price Evidence off its blocks | 0 | 0 |

Actions on the corpus (R2): 81 rows anchored (90 rows out), 57 attached [5d]-style, 81 labelled
prices attached, 174 renamed.

### 3.6 Reach

P8-17 counted 1,490 gold title amounts lost inside records, and up to 909 within F2/F4's reach.
v5 delivers +62. The ruled design stops short of the rest:
- it moves only accepted rows (a downgraded row's price isn't grounded);
- it attaches only prices printed with a label (a variant is never inferred: "11.00 | 15.50"
  stays out);
- the title signature must be trusted (≥ 0.8 titles), which excludes many classless and
  hashed-class pages.

Owner questions Q4 and Q5 in the amendment.

## 4. Do chunk boundaries split records?

`var/p8-21/chunksplit.py`: for each record, whether its title and member blocks fall in more
than one `chunking.chunks` chunk.

| | Records | Split | Gold title prices delivered (split / whole) | Title unkept (split / whole) |
|---|---|---|---|---|
| Dev (420 pages) | 15,638 | 348 (2.2 %, 87 pages) | 0.814 / 0.903 | 0.144 / 0.089 |
| Corpus | 25,397 | 551 (2.2 %, 153 texts) | — | 0.113 / 0.086 |

At the unsplit rate, split records would deliver about 28 more dev gold prices, 0.12 % of
23,749. A chunker change alters the extractor key and needs GPU re-extraction, which is the
owner's call (Amendment 29 Q7). **Chunking is unchanged.**

## 5. Reproduction

```bash
cd .claude/worktrees/p8-21-page-structure
P821_OUT=/home/fortune/CodeProjects/First-Helios/var/menu-eval/labels-v10.2 P821_CASE11=items \
  PYTHONPATH=. .venv/bin/python var/p8-21/build_v10_2.py
# baseline (main) and candidate (this tree); P821_PATCH=choice measures R2
P821_LABELS=v10.2 P821_INV=1 PYTHONPATH=/home/fortune/CodeProjects/First-Helios .venv/bin/python var/p8-21/measure.py v4 dev > var/p8-21/measure/v4-l102.jsonl
P821_LABELS=v10.2 P821_INV=1 PYTHONPATH=. .venv/bin/python var/p8-21/measure.py v5 all > var/p8-21/measure/v5e-l102.jsonl
PYTHONPATH=. .venv/bin/python var/p8-21/compare.py var/p8-21/measure/v4-final.jsonl var/p8-21/measure/v5e-l102.jsonl
PYTHONPATH=. .venv/bin/python var/p8-21/losses.py BEFORE AFTER     # per-page losses
PYTHONPATH=. .venv/bin/python var/p8-21/chunksplit.py              # section 4
PYTHONPATH=. .venv/bin/python var/p8-21/trace.py e6942e6d1e2a 165 178   # santopatio
```

`v4-final.jsonl` is `v4-l102.jsonl` plus the corpus lines of `v4-l101.jsonl` (labels don't
touch the corpus).
