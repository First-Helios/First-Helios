# Page template and duplicate removal built as resolve-v4 (ADR-0013 Amendment 29, P8-14)

Session P8-14, 2026-10-25. It builds [ADR-0013 Amendment 29](../adr/0013-phase5-menu-pipeline.md#amendment-29-2026-10-24-proposed-stage-5d-page-template-and-duplicate-emissions)
as the owner ruled it on 2026-10-25. It then reproduces the P8-13 dev numbers and runs the
§8 held-out check. It stops before any laptop re-interpretation or Gold refresh, which need
the owner's go-ahead.

Scope:
- `helios_laptop` (alembic `13081a087231`, resolve-v3) was **not touched**, not even read. Every
  page came from its stored bundle and every answer from the saved production answers
  (`var/replay/menu-extract/`, extractor
  `qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2`).
- There were no fetches, no model calls and no Pi access. Nothing was written to Bronze,
  Menu, identity or Gold.
- No schema, migration, dependency, model, prompt, chunker, segmenter or validator change. No
  per-site, per-platform or hand-entered rule.
- The planned disposable test DB `helios_p814_test` was **not created**. The local PostgreSQL
  needs a password that only `.env` holds, and reading `.env` was refused this session. The
  database tests, including the new end-to-end extraction test, skip locally. CI runs them in
  strict mode on its own PostgreSQL. See section 6.

**Result.**
- **Built:** [5d] and duplicate removal (rule "same") as `resolve-v4`.
  - The build matches the prototype page by page on all 863 corpus page texts and all 746
    dev pages, and every P8-13 dev number reproduces.
  - The one exception is a prototype defect: its output depends on Python's string-hash
    order on one page. The build fixes the order.
  - Switching off each of 27 rules fails a test.
- **§8 held-out** (49 pages drawn and frozen as ruled; 38 scorable, 37 of them
  template-gated): **not every bar passes.**
  - **Three stage bars pass:** item recall +0.063, kept-item precision +0.027 and section
    accuracy +0.009, each against resolve-v3 on the same pages.
  - **Four stage bars fail:** 4 of 37 gated pages lose a gold item (the bar allows 1 in 10).
  - **Two §8 bars fail on this set:** price accuracy 0.916 (bar 0.98) and gold-row FR
    0.156 (bar 0.12). They fail just as much under resolve-v3: [5d] doesn't change the
    validator, and it raises price accuracy slightly.
- Owner questions are in section 8.

## 1. Owner rulings recorded

Amendment 29's status is now "Accepted 2026-10-25" with the rulings Q1–Q7, the follow-on
conditions and the direction note (commit `dabe47d`). This branch also carries the re-land of
#123 (`04e261c`, identical to #123's merge `db35639`), which is PR #124.

## 2. What was built

- **`packages/helios_parsing/page_template.py`** (new, stdlib):
  - `induce(blocks, placed, rows, verdicts, sections)` is [5d], ported from
    `var/p8-13/template.py` at its base Config:
    - gate: 5 seeds, 0.8 explained, 0.8 agreement;
    - pattern support: 3 seeds and 10 %;
    - all four actions, every ADD skip rule.
  - `remove_duplicates(verdicts)` is rule "same", a pure function on verdicts.
  - `llm_stream(blocks, outputs, html)` is the `llm` stream's whole post-model interpretation,
    in the ruled order: `rows_of` → judge → [5d] → judge again (gated pages) → duplicate
    removal → [5c] `assign`.
- **Differences from the prototype.** None changes an output, except the tie order on the one
  page in section 3.
  - Dropped (Q4): `per_item_seeds`, `grouped_variants`, the `drop_borrowed` variant and the
    `do_*` switches. Also dropped are the diagnostics only the prototype read (`skips`,
    `candidates`, `anchors`, `template`).
  - **Ties in a fixed order.** The prototype sorted a set of string tuples by support alone,
    so equal-support patterns came out in hash order. The build breaks ties on the pattern
    itself.
  - **One unreachable check removed.** The ADD skip "a kept row cites this price" can never
    fire. Every cited price block lies inside some kept item's name-to-price span, so the
    "inside a kept item" skip just before it always fires first. P8-13's sizing also counts
    0 such skips.
- **Wiring:**
  - `apps/menu_pipeline/extraction._Run._write` calls `llm_stream` for the `llm` stream
    only. The `jsonld` stream is unchanged.
  - `dom_sections.assign` takes the already-parsed `placed` blocks, so the page is parsed
    once for [5d] and [5c].
  - The run report gains `template`: pages gated, rows added, dropped, re-named and attached,
    and duplicate rows removed.
- **Version:** `RESOLVER_VERSION = "resolve-v4"`. `method_version` stays 126 characters, so
  there is no migration.
- **Harness:**
  - `evaluation.score_verdicts`, `loss_verdicts` and `section_counts` score verdicts
    already interpreted. `score_page`, `loss_page` and `section_page` keep their behaviour.
  - Kept-item precision: `kept_items`, `kept_matched`, `found_items` and the
    `kept_item_precision` metric.
  - `page_clustered_change` is a paired page-clustered interval of one change.
  - `template_page` scores one page under resolve-v3 and resolve-v4, with every action
    checked against gold.
  - `template_bars` applies the Q6 stage bars.
  - `apps.menu_pipeline.evaluate`: `compare`, `loss`, `report` and `sections` now score the
    full `llm` stream as production stores it. A new `template` command prints the [5d]
    record and its bars.
- **Tests** (synthetic fixtures only):
  - `test/test_parsing_page_template.py`, 20 tests:
    - a same-line template (ADD the missed dish, DROP an ingredient row priced from the dish
      line above it);
    - a split-card template (ATTACH both size labels, RE-NAME in both forms, ADD a missed
      card);
    - RE-NAME dropping a copy its title already holds;
    - the DROP guards (a printed list, a line printing its own price);
    - blocks off the template (another class signature, another relation, outside the
      record);
    - each of the 9 ADD skip rules, including the model's wine section;
    - three gate failures, each byte-identical (fewer than 5 seeds, agreement, nothing
      explained);
    - rule "same" against differing prices and against one-section copies;
    - the survivor placed by [5c].
  - Harness tests in `test/test_parsing_evaluation.py`: `template_page`, `template_bars`,
    `print_template` and `page_clustered_change`.
  - An end-to-end extraction run in `test/test_menu_extraction.py` (a database test): a
    card page where the model misses one dish.
    - The dish is added and accepted on re-judge, and written with its name and price
      Evidence on its own card.
    - The run report's `template` counter is checked.
- **Mutation check** (`var/p8-14/mutate.py`): each of 27 rules is switched off in turn, and
  every one fails a test.
  - The gate's three parts, pattern support, the class-signature and record-container
    tests.
  - ATTACH, both RE-NAMEs, the title-holds-the-copy drop, DROP and both DROP guards.
  - ADD, and each of its 10 skips.
  - Rule "same", removal, and the re-judge and dedupe steps of `llm_stream`.

## 3. The prototype reproduced (dev; the rules were tuned on these pages)

**Page by page** (`var/p8-14/equiv.py`): prototype and build were compared on all 863 corpus
page texts and all 746 dev pages. They match on:
- rows, gate statistics, dropped, attached, re-named and added rows;
- rule "same"'s verdicts, before and after [5d].

The only exception is the prototype's own hash dependence:
- **The page:** `mansionatjudgeshill.com/bar_menu`, which has three patterns with 7, 3 and 3
  seeds.
- **When it differs:** under `PYTHONHASHSEED` 5 and 6 (and one unseeded run), the
  prototype's ADD rows there differ from the build's.
- **When it matches:** under seeds 0–4, it agrees with the build on every page.

**Corpus** (863 page texts; ruled figures in brackets):

| | Build | P8-13 |
|---|---|---|
| [5d]-gated page texts | 481 | 481 |
| ADD rows (items) | 2,036 (1,847) | 2,036 (1,847) |
| DROP | 1,813 | 1,813 |
| RE-NAME | 186 | 186 |
| ATTACH | 57 | 57 |
| Duplicate removal alone on resolve-v3: items | −596 | −596 |
| … one-item sections, prices, distinct price Evidence | −151, −356, 0 | −151, −356, 0 |
| … sections | −217 | −218 |

The section gap is one page text, `83a53654`. It has no item stored under two sections, so
P8-13's `dedupe.py` skipped it. Removing one copy row there moves the block where a model
section is grounded, which adds a section: −218 + 1 = −217.

**Dev metrics** (294 scorable pages, 223 gated; `var/p8-14/devrepro.txt`, through the build's
own harness, `evaluation.template_page`):

| On gated pages | Before | After | Change [paired page-clustered 95 %] | P8-13 |
|---|---|---|---|---|
| Item recall (kept items) | 0.8918 | 0.9310 | +0.0392 [+0.0330, +0.0460] | +0.0392 [+0.0331, +0.0460] |
| Kept-item precision | 0.8106 | 0.8436 | +0.0329 [+0.0249, +0.0421] | +0.0329 [+0.0249, +0.0421] |
| Usable prices | 0.8119 | 0.8555 | +0.0436 [+0.0369, +0.0508] | +0.0436 [+0.0370, +0.0508] |
| Price accuracy | 0.9934 | 0.9934 | −0.0000 [−0.0012, +0.0011] | +0.0000 [−0.0012, +0.0012] |

- The interval ends differ by at most 0.0001. Both use 2,000 resamples and seed 20261024;
  they pick the percentile index differently:
  - the build uses `page_clustered`'s convention, `int(0.025·(n−1))` and `ceil(0.975·(n−1))`;
  - `report.py` used `int(0.025·n)` and `int(0.975·n)`.
- **Per action, the counts are identical:**
  - ADD 926: 783 new gold items (771 at a gold price), 29 already found, 93 match no item,
    21 rejected;
  - DROP 853: 754 non-items, 73 redundant, 26 lose a gold item;
  - RE-NAME 77: 74 right;
  - ATTACH 29: 24 exact, 1 item only, 4 unmatched.
- The per-format table is identical.
- **Accepted rows matching no label:** +9 from the template alone (P8-13's figure). With
  duplicate removal it is −3, because removal also takes 12 unmatched copies.
- **Pages losing a gold item:**
  - P8-13 counted 5, by found-count going down.
  - The stage bar counts by set (any gold item resolve-v3 found that resolve-v4 doesn't):
    10 pages (27 items), which is 4.5 % of 223 and passes.
- **Section accuracy** (Amendment 28 metric, all 746 dev pages):
  - The build, in production order, gives 0.7151 → **0.7230** exact: 16,533 exact items,
    155 pages better and 7 worse, dish-named sections 734 → 654.
  - P8-13's measurement on the build's functions gives exactly **0.7228**: 16,527 items,
    154 / 8, and 658. That measurement re-judged the deduplicated rows, with the rejected
    rows appended.
  - So the +6 items come from the build's not re-judging after removal, which is the
    ruled order.

**Invariance** (corpus, `var/p8-14/corpusrepro.txt`):
- **Pages [5d] doesn't gate** (382 page texts): price Evidence is identical to resolve-v3.
  - The distinct stored items differ on 8 page texts, and only by the spelling of a removed
    copy: the same key, Evidence, prices and variants, with a name spelled differently.
  - No name appears that resolve-v3 did not store.
- **Duplicate removal** drops no distinct printed price Evidence on any page.
- **Every stored resolve-v4 price** cites a span on one of the Version's blocks.
- **On gated pages,** 31,134 of resolve-v3's 31,211 accepted price spans are still cited. The
  other 77 belonged to dropped rows.
- **Corpus totals, v3 → v4:**
  - items 61,644 → 60,992;
  - priced items 35,109 → 36,357;
  - prices 37,809 → 39,154;
  - distinct price Evidence 36,908 → 38,658;
  - sections 8,472 → 8,284;
  - one-item sections 1,740 → 1,540.

## 4. §8 held-out

**Draw** (`var/p8-14/draw.py`, frozen before any labelling):
- **Pool: 114 page texts, 39 of them gated by the built [5d],** as ruled. It is the 863
  production texts minus:
  - P8-12's 1,287 labelled text hashes;
  - P8-12's 35 drawn pages;
  - the 16 traced cases (P8-11's 8 and P8-13's 8);
  - P8-12's 93 audited URLs.
- **Drawn:** all 39 gated texts, plus 10 of the 75 ungated drawn with seed 20261025.
- **Frozen:**
  - `exclusions.json` sha256 `93108f37f0382f9465228032d673c3c241022b6393ace3d9da63d4833d62d3b5`;
  - `draw.json` sha256 `1369d98505f42b513c5240a61a07c67493494e2dee1bde9f35a8141b61bb81ac`.

**Labels:**
- **Labellers:** blind full-item labels by 10 Sonnet subagents. Pages were dealt by block
  count, about 1,300 blocks each.
- **What they saw:** each worked in its own private folder (`var/p8-14/label/L01`–`L10`)
  holding only the brief and its pages' block files. None saw pipeline output.
- **The brief:** P5-26's, with its rules unchanged (sha256 `ada4e519…`). Only the header
  changed: it names the folder and says items, prices and sections are all scored.
- **Completeness check:** `labelcheck.py`, before the freeze, compares each label's prices
  with the price tokens the page text prints. It never reads pipeline output. Every flagged
  page was explained by the page text:
  - item numbers ("Sauce-Steamed Abalone 01") and image alt text ("Hat Creek 12 09 21 Big
    Hat 001") read as price tokens;
  - a page that prints every price twice;
  - catering rows that are excluded.
- **Frozen:** manifest sha256
  `9daf0784b108888575c5f7500c1b87c87b6514c4a2d5820eb1d071f16757b239`.
- **Pages:**
  - 2 pages are `not_menu` (a restaurant-equipment shop and a Grubhub "menu unavailable"
    page), which leaves 47 menu pages;
  - 38 of the 47 are scorable (a priced gold item): 37 gated and 1 ungated;
  - one gated page (UMI Buffet) prints no prices.

**§8 bars** (`evaluate report prod`; resolve-v4):

| Bar | Result | |
|---|---|---|
| Item recall ≥ 0.85 | 0.903 (2,142 / 2,373); resolve-v3 0.841 | pass |
| Price accuracy ≥ 0.98 | **0.916** (1,602 / 1,748); resolve-v3 0.908 | **FAIL** (both) |
| Gold-row FR ≤ 0.12 | **0.156** (320 / 2,050) [0.057, 0.302]; validator only | **FAIL** (unchanged by [5d]) |
| Corruption catch ≥ 0.97 | 1.000 (1,580 / 1,580) | pass |
| Usable prices ≥ 0.74 | 0.759 (1,555 / 2,050) [0.616, 0.854]; resolve-v3 0.676 | pass |

- **One page dominates both failures:** `d57b5b288970` (Dahlia Café), where each price is
  printed before its item's name.
  - It holds 145 of the 320 gold-row false rejects (0.806 on the page), and 105 of the 146
    accepted wrong-price rows (110 under resolve-v3).
  - Without it, price accuracy is 0.975 under both resolve-v3 and resolve-v4. That is
    still under 0.98.
  - Gold-row FR is 0.188 on `html_list` pages and 0.006 on `html_cards` pages.
- These are validator results on this set; [5d] neither causes nor fixes them. The v9
  held-out passed both bars (Amendment 22). This set was drawn from production texts that no
  earlier set had labelled.

**Stage bars** (`evaluate template prod`; the 37 template-gated scorable pages against
resolve-v3 on the same pages; point estimates):

| Bar | Result | |
|---|---|---|
| Item recall not lower | 0.8197 → 0.8826 (+0.0629 [+0.0331, +0.1004]) | pass |
| Kept-item precision not lower | 0.8031 → 0.8301 (+0.0270 [+0.0112, +0.0511]) | pass |
| Accepted rows matching no label up ≤ 1 % of kept rows | −9 (of 2,727 kept rows) | pass |
| ≤ 1 gated page in 10 loses a gold item | **4 of 37** (7 items); at most 3.7 allowed | **FAIL** |
| Amendment 28 section accuracy not lower | 0.6906 → 0.6998 exact | pass |
| Ungated pages unchanged by [5d] | 0 changed | pass |
| No price Evidence lost to duplicate removal | 0 | pass |

**Other results:**
- Usable prices on gated pages: 0.677 → 0.760 (+0.083 [+0.049, +0.120]).
- Price accuracy on gated pages: 0.908 → 0.917 (+0.009 [−0.002, +0.024]).
- Duplicate rows removed: 33.
- `evaluate sections` on resolve-v4: on the 17 [5c]-gated pages, exact 0.954
  [0.918, 0.984] against 0.545 without [5c], with 0 pages worse. Every Amendment 28 bar still
  passes.

**Per action class** (gated scorable pages; share right, page-clustered 95 %):

| Action | n | Right | Detail |
|---|---|---|---|
| ADD | 189 | 0.894 [0.76, 0.98] | 163 new gold items (161 at a gold price), 6 already found, 20 match no item; 185 accepted, 4 downgraded, 0 rejected |
| DROP | 80 | 0.912 [0.78, 0.99] | 68 non-items, 5 redundant, 7 lose a gold item |
| RE-NAME | 18 | 1.0 | all 18 match a gold item |
| ATTACH | 6 | 1.0 | all exact (gold item, variant label and amount) |

**The 4 pages that lose a gold item** (`var/p8-14/heldout-losses.txt`; analysed after the
freeze, and no rule was changed from it):
- **DROP of a dish's title line**, on 2 pages (5 items):
  - Dale's Essenhaus (`98eb9a11564d`): 4 dishes whose only name line reads "Chicken &
    Dumplings - Served with two sides" (unpriced). The line is description-like, so the DROP
    rule takes it.
  - `bb9c743f965e`: "Quinoa Bowl" printed in one block with its whole description.

  P8-13 named this loss type on dev: "a dish whose only printed name is inside its
  description".
- **Duplicate removal of unpriced copies**, on 2 pages (2 items):
  - `79f66c5309ed` "Paloma" and `ad991b67d739` "Vegetarian Antipasto". Each dish is printed
    twice, and the model's second copy is grounded onto the first print: the grounding
    collapse of P8-13 §1, row 4.
  - Both copies are unpriced, so rule "same" sees two empty price-span sets as the same
    and removes one. The gold item at the second placement then has no row.
  - This loss type never showed on dev (0 gold items lost). A rule "same" that required
    non-empty, identical spans would keep both copies here.

## 5. Speed (laptop, one core, sequential; `var/p8-14/timing.txt`)

All 863 page texts from saved answers, each timed best of 3 (no model, no DB):

| | Median | p95 | Max | Total |
|---|---|---|---|---|
| resolve-v3 (`rows_of` → judge → [5c]) | 57.0 ms | 265 ms | 1.59 s | 79 s |
| resolve-v4 (`llm_stream`) | 72.6 ms | 383 ms | 1.94 s | 107 s |
| Added by resolve-v4 | 11.9 ms | 133 ms | 0.83 s | 28 s |

- On the 481 [5d]-gated texts, the median added time is 28.5 ms (p95 170 ms).
- The added time covers the induction, the second judge on gated pages and duplicate
  removal. [5c] now reuses [5d]'s parse.
- This is small beside a model call per chunk.
- The Pi was not timed; that needs the owner's go-ahead.

## 6. Verification

- **`make ci`** (lockfile, lint, typecheck, tests), run with `var/` Python files parked
  outside the worktree: **pass**, with 808 passed and 948 skipped. The skipped tests are the
  database tests, since no database was available.
- **Database tests:** not run locally. The local PostgreSQL needs a password that only
  `.env` holds, and reading `.env` was refused this session. So `helios_p814_test` was not
  created, and the new end-to-end test `test_5d_adds_the_template_line_the_model_missed`
  and the other database tests skipped here. CI runs them in strict mode, with
  `alembic check`.
- **The end-to-end test's page was dry-run without a database** (`var/p8-14/e2e_dry.py`):
  - its scripted answers through `llm_stream` gate the page;
  - the missing dish is added at $8.99, with Evidence on its own price block;
  - all 7 rows are accepted, filed under "Platos".

## 7. Side findings (not acted on)

- **Price tokens that are not prices:** UMI Buffet's item numbers ("… Abalone 01") and Hat
  Creek's image alt text ("Hat Creek 12 09 21 Big Hat 001"). UMI Buffet is template-gated.
  This is a `prices.price_tokens` false positive, so the validator sees a price that the page
  doesn't print.
- **Price printed before its name** (Dahlia Café): this layout breaks the validator's price
  binding. It is the whole of this set's price-accuracy and FR gap.

## 8. Owner questions

In the PR.

## 9. Artefacts (untracked, `var/p8-14/` in the worktree)

- **Build checks:** `equiv.py` / `.txt`, `equiv_page.py`, `equiv_seeds.txt` (the hash
  dependence), `devrepro.py` / `.txt` / `.json`, `corpusrepro.py` / `.txt`,
  `ungated_diff.py` / `.txt`, `mutate.py` / `.txt`, `e2e_dry.py`, `fixtures*.py`,
  `timing.py` / `.txt`.
- **Held-out:** `draw.py` / `.txt`, `heldout/` (`exclusions.json`, `draw.json` with their
  `.sha256`, `pages/`, `blocks/`, `extract/prod/`, `labels-blind/` and
  `labels-blind.sha256`), `label/` (the brief and the 10 labeller folders),
  `label_setup.py` / `.txt`, `labelcheck.py`, `freeze.py` / `.txt`,
  `heldout-template.txt`, `heldout-report.txt`, `heldout-sections.txt`,
  `heldout_losses.py`, `heldout-losses.txt`.
- **Copied from P8-13:** `template.py`, `dedupe.py`, `lib.py`, `devtpl.py`, `report.py`,
  `secacc.py`, `sizing.py` and their outputs.
