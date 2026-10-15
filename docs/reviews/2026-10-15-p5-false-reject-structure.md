# False-reject structure assessment (ADR-0013 §8)

Session P5-17, 2026-10-15. Since recall started passing, three held-out evaluations in a row
have failed only on the validator's gold-row false-reject (FR) bar: P5-12 v6 **0.126**, P5-14
v7 **0.153**, P5-16 v8 **0.134** (bar ≤ 0.12). This session asks whether the problem is in the
pipeline's structure, in how §8 measures it, or in the labels, and it proposes a structural
change for the owner to review. **Proposal only:** no pipeline, harness, schema, dependency or
`infra/` change, no model run and no held-out draw. The proposal is
[ADR-0013 Amendment 19](../adr/0013-phase5-menu-pipeline.md#amendment-19-2026-10-15-proposed-false-reject-structure),
marked **Proposed**.

Code under test: `main` at `9f334ae` (PR #87 validator-v8 and PR #88 P5-16 record merged),
pipeline version
`…;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v7;validator-v8;classifier-v2`. Data: the seven
labelled sets, 218 scorable pages, **15,898 gold rows**: spike 33 pages, P5-5 10, P5-8 35,
P5-10 35, P5-12 35 (confirmed labels, laptop CPU answers `v6c` / `v6`), P5-14 35 (Pi answers
`v7`) and P5-16 35 (laptop GPU answers `v8`), the last two with blind labels. Every set except
P5-16 has been tuned on. P5-16 has not been tuned on yet, but it was scored in P5-16, so it is
tuning data from now on. Scratch scripts and outputs are in gitignored
`var/menu-eval/p5-17/` (`p17_rows.py`, `p17_analyse.py`, `p17_rowclf.py`); this file keeps
counts and rates only.

## Owner decisions (asked first)

| | Question | Answer |
|---|---|---|
| S1 | Scope: second pass only, or measurement and labels too | **All three** |
| S2 | When the second pass rejects a row: omit the item or keep it unpriced | **Measure both, decide later** |
| S3 | Runtime for any future evaluation | **Laptop GPU** (the proposal still states Pi cost) |
| S4 | Single-price menus (a taco list printed once at $2.50) | **Measure and compare approaches** |

## Summary

1. **Owner's hypothesis, right target:** 96 % of gold-row rejects (1,465 of 1,523) are "no price
   match" downgrades, and a perfect second pass over them would bring gold-row FR to **0.004**
   and raise usable prices from **0.780 to 0.818**.
2. **The hard part is catch.** The validator catches **7,613 of its 9,744** injected corruptions
   through the same no-match downgrade, and **6,227** of those corrupt amounts are printed
   on the page. On real output, the rows a second pass would see are **787 correct, 587 wrong
   price and 1,123 matching no labelled item**. Rules based on where the amount is printed
   fail: "the amount within 3 blocks" halves FR (0.096 → 0.048) but drops catch to **0.851**
   and price accuracy to **0.974**.
3. **A cheap learned row classifier is promising but not proven.** It uses location
   features only and was tested leave-one-set-out. It cut P5-16 FR from 0.134 to **0.070**
   with catch 0.989 and accuracy 0.989. But its threshold, chosen on the other sets,
   **broke catch on 3 of 7 held-out sets** (0.959–0.968). Gradient boosting broke it on 5 of 7.
4. **Single-price sections (the taco case) are a section-level problem, not a page-level
   one.** 128 rejects (8 %) sit in one-price sections on 21 pages, but only 11 on the 8 pages
   that use one price throughout. A generic section rule grounds 20 rows, including the 6
   breakfast tacos, and costs 17 corruptions. It also prices 101 rows that no label matches.
5. **Measurement can't settle the verdict at 35 pages.** Page-clustered, P5-16's FR is
   **[0.061, 0.235]**, not the row-level Wilson interval [0.121, 0.148]. A version whose true FR
   equals the pooled v8 figure (0.096) fails one 35-page draw in four. To pass reliably, a
   version needs a pooled tuning FR near **0.05**. The large stratum also runs out in about two
   draws.
6. **Label conventions matter at the margin.** Variants read from a dish name ("3/6 Catfish"),
   inferred variants and "+$" add-on rows together hold 79 rejects. Without them P5-16 reads
   **0.119**. That is not a reason to change P5-16's recorded verdict. The conventions need
   settling before the next draw, on their merits.

**Recommendation:** split the change into three decisions, in this order. First, fix the
measurement: page-clustered intervals, a 70-page held-out set, and two new recorded numbers.
Second, decide the label conventions. Third, add a second-pass stage **[5b] price resolution**
that only sees no-match downgrades and keeps rejected rows unpriced. It starts with generic
deterministic resolvers. A learned row classifier is added only after it holds catch ≥ 0.97 on
every tuning set, leave-one-set-out, with real-output wrong rows as negatives. Don't spend the
next draw (seed 20261015) until the tuning sets read near 0.05 pooled.

## 1. Structure: where the rejects are and what a second pass could do

### 1.1 Rejects by reason

Gold-row rejects under validator-v8, all seven sets. "No match" covers `price_not_grounded`,
`variant_not_grounded`, `price_bound_to_other_item`, `price_belongs_to_other_variant` and
`addon_price`.

| Set | Gold rows | FR | No-match share | Top reasons |
|---|---|---|---|---|
| spike | 1,969 | 0.014 (27) | 1.00 | price_not_grounded 22, addon 3 |
| P5-5 | 763 | 0.107 (82) | 0.91 | price_not_grounded 43, variant_not_grounded 31 |
| P5-8 | 2,614 | 0.112 (294) | 0.90 | price_not_grounded 216, variant 38, name_not_grounded 28 |
| P5-10 | 2,933 | 0.087 (256) | 0.98 | price_not_grounded 165, variant 72 |
| P5-12 | 2,459 | 0.115 (284) | 0.96 | price_not_grounded 214, variant 51 |
| P5-14 | 2,777 | 0.094 (261) | 0.97 | price_not_grounded 199, variant 46 |
| P5-16 | 2,383 | 0.134 (319) | 1.00 | price_not_grounded 170, variant 127 |
| **all** | **15,898** | **0.096 (1,523)** | **0.96** | price_not_grounded 1,029, variant 367, name_not_grounded 53, other variant 27, bound to other item 24, addon 18, implausible 5 |

By layout class (P5-16's `fr_classes.py`, a rough automatic class, run under v8): group or section price printed above the item
**227**, amount read nowhere within 12 blocks (unread price text) **223**, a number inside the
name **101**, a column header split over blocks **96**, a label on its own line **48**; unclassified
price 352, variant 223. No named class holds more than 15 % of the rejects. A class is
typically concentrated on 2–10 pages, and in each set the four worst pages hold **50–93 %** of
that set's rejects.

### 1.2 What the second pass would see on real output

Real output = each set's saved answers, repaired and stitched as the pipeline does, validated by
v8 (14,085 priced rows, matched to labels by the frozen harness):

| No-match downgrades | Rows | Exact gold price | Wrong price | No labelled item |
|---|---|---|---|---|
| all sets | 2,497 | 787 (32 %) | 587 (24 %) | 1,123 (45 %) |
| P5-16 | 358 | 118 | 66 | 174 |

Most rows the second pass would see should *not* be accepted. The "no labelled item" rows
are a mix of real dishes under noisy names ("Fish and Chips photo") and descriptions the
model used as names. Accepting them stores priced rows under bad names. §8's price accuracy
can't see these rows: it scores only accepted rows that match a label. **1,189** such
accepted-unmatched rows are already stored today, 8 % of all accepted rows.

On injected corruptions (seed 7, 9,803 trials), the validator catches **9,744**. Of those,
**7,613** are caught as no-match downgrades (swapped 3,790, mutated 1,997, other-section 1,826),
and **6,227** of them carry an amount printed somewhere on the page. A second pass that accepts
a downgrade undoes a catch unless it can tell a correct row from one of these.

### 1.3 Second-pass policies, measured

Each policy re-judges only no-match downgrades. "Keep" means a row the second pass rejects
stays unpriced, as today. All 7 sets pooled; P5-16 in brackets.

| Policy | Gold FR | Catch | Price accuracy | Usable prices | Real-output catch | Accepted, no label |
|---|---|---|---|---|---|---|
| today (v8) | 0.096 [0.134] | 0.994 [0.992] | 0.991 [0.990] | 0.780 [0.790] | 0.595 | 1,189 |
| **oracle** (accept iff exact gold price) | **0.004** [0.000] | 0.994 | 0.992 | **0.818** [0.833] | 0.595 | 1,189 |
| amount anywhere on the page | 0.008 | **0.359** | 0.958 | 0.815 | 0.111 | 2,255 |
| amount within 3 blocks | 0.044 | 0.809 | 0.972 | 0.807 | 0.261 | 1,983 |
| within 3 blocks, no other item crossed | 0.048 [0.036] | 0.851 [0.843] | 0.974 | 0.803 | 0.336 | 1,782 |
| within 12 blocks, no item crossed | 0.039 | 0.833 | 0.972 | 0.805 | 0.306 | 1,848 |
| generic group price above (heading, price-only line, notes) | 0.094 | 0.964 | 0.990 | 0.781 | 0.556 | 1,292 |
| same, whole section otherwise unpriced | 0.095 | 0.993 | 0.991 | 0.781 | 0.565 | 1,284 |
| section prints one amount on its price-only lines | 0.095 [0.128] | 0.992 | 0.991 | 0.781 | 0.563 | 1,290 |

**Budget for a second pass to stay inside the bars**, from these counts:
- **Catch ≥ 0.97** allows 294 uncaught corruptions; 59 are uncaught today. The second pass
  may accept at most **235 of the 7,613** no-match corruptions: it must reject 96.9 % of them.
- **Price accuracy ≥ 0.98**, if it accepts all 787 correct real rows, allows at most **166 of
  the 587** wrong-price rows. It must reject 72 % of them.
- **Reaching the FR bar** on P5-16 needs 38 of its 318 no-match gold rejects, about 12 %.
  Reaching a pooled 0.05 needs about half of the 1,465.

The catch requirement binds. Location alone can't meet it, because a swapped or other-section
corruption puts a real price from the page right next to the item. Telling them apart means
knowing which item owns which printed price, and that is the validator's own job. That is why
each new layout has needed a new validator lever.

### 1.4 A row-level classifier: feasibility on saved data

What the classifier would be: a per-row probability that "this extracted price belongs to this
item". It is applied only to no-match downgrades. Inputs are the row's position relative to the
amount's printed copies (same block, distance above and below, other items crossed), its section
(distinct amounts, price lines, item count, single-price section), the add-on mark, the
variant and the downgrade reason. The existing page classifier (`classifier-v2`) is page-level,
so it can't answer this. A row model needs its own features and its own training rows:

- **positives:** gold rows (15,898; the rejected ones are the target) and real-output rows with
  the exact gold price;
- **negatives:** injected corruptions, plus real-output rows with a wrong price or no labelled
  item (1,710 among no-match downgrades).

Measured leave-one-set-out: train on six sets, choose the threshold on those six (pooled catch
≥ 0.975 and accuracy ≥ 0.985), then score the seventh. scikit-learn 1.9.1 was used ad hoc
(`uv run --with`, as `train_page_classifier` does); there was no project change.

| Held-out set | Today FR / catch / acc | Logistic regression FR / catch / acc | Gradient boosting FR / catch / acc |
|---|---|---|---|
| spike | 0.014 / 0.989 / 0.996 | 0.013 / 0.987 / 0.995 | 0.005 / 0.979 / 0.995 |
| P5-5 | 0.107 / 1.000 / 0.992 | 0.051 / **0.968** / 0.984 | 0.029 / **0.910** / **0.972** |
| P5-8 | 0.112 / 0.996 / 0.983 | 0.091 / 0.981 / 0.981 | 0.056 / **0.928** / **0.978** |
| P5-10 | 0.087 / 0.997 / 0.997 | 0.057 / **0.959** / 0.997 | 0.031 / **0.950** / 0.995 |
| P5-12 | 0.115 / 0.995 / 0.991 | 0.090 / 0.983 / 0.991 | 0.076 / **0.951** / 0.987 |
| P5-14 | 0.094 / 0.993 / 0.990 | 0.062 / **0.962** / 0.989 | 0.051 / **0.963** / 0.986 |
| P5-16 | 0.134 / 0.992 / 0.990 | **0.070 / 0.989 / 0.989** | 0.042 / **0.962** / 0.983 |

Bold misses a bar. Each model also stores more priced rows that match no label: 3–28 per set
(logistic), 22–69 (boosting). Reading the results:
- The signal is real: FR roughly halves on held-out sets.
- The operating point doesn't transfer across sets. A threshold that holds catch on six sets
  lets corruptions through on the seventh's layouts, the same tail problem the validator has.
- Richer inputs would be needed: block text, and the potion-base-8M embedding that already
  ships for `classifier-v2`, so no new runtime dependency. Even then, catch is measured with
  the same corruption generator the model trains on (below).

**Leakage risks and held-out discipline for a trained row model:**
1. *Corruption generator leakage.* §8's catch metric uses the seed-7 generator: price mutations
   (±0.50 / ±1.00 / one digit), swaps within 3 rows, other-section prices and invented names. A
   model trained on those negatives learns their signatures. For example, a mutated amount is
   usually printed nowhere on the page. Its injected catch then overstates real catch. Today the
   validator's catch is 0.994 on injected corruptions but **0.595 on real output**. Training
   negatives must include real-output wrong rows. A trained model should be scored on
   "real-output wrong rows accepted" (a new recorded number), with the corruptions drawn from a
   different seed than training.
2. *Page leakage.* Rows of one page share a layout. Split by set or page, never by row.
3. *Label noise.* "No labelled item" negatives include real items that labellers skipped or the
   model misnamed. That noise makes the model reject more, which is the safe direction.
4. *Held-out discipline.* Training rows and the threshold come from tuning sets only. The
   classifier's weights version joins the pipeline version string, as `classifier-v2` does.
   After a failed draw, retraining on that draw makes it tuning data, the same rule as for
   validator levers. The next draw (seed 20261015) is never read before the version is frozen.

### 1.5 Keep unpriced vs omit

When the second pass rejects a row, "keep" leaves the item stored without a price (today's
downgrade). "Omit" drops the row entirely (all sets):

| Policy | Mode | Item recall (any row) | Items stored | Usable prices | Stored priced / unpriced rows |
|---|---|---|---|---|---|
| today | — | 0.884 | 0.882 | 0.780 | 14,290 / 5,692 |
| oracle | keep | 0.884 | 0.882 | 0.818 | 15,077 / 4,905 |
| oracle | **omit** | 0.884 | **0.867** | 0.818 | 15,077 / 3,195 |
| within 3 blocks, no item crossed | omit | 0.884 | 0.859 | 0.803 | 15,605 / 3,195 |
| group price above | omit | 0.884 | 0.837 | 0.781 | 14,449 / 3,195 |

- **Omit can't improve price accuracy or catch.** Both outcomes store no price, so neither
  can store a wrong one.
- **Omit costs stored items.** Even with a perfect second pass it drops **240 labelled items**
  (0.882 → 0.867): dishes whose only row has the wrong price. It drops 1,710 unpriced rows in
  all, two thirds of them (1,123) not labelled items.
- **§8 would hide the loss.** §8's item recall counts any matched row, including rejected ones,
  so it would read 0.884 either way. If omit is chosen, the recall bar must count items stored
  (`item_recall_kept`) to stay honest.
- **Effect on the Menu tables:** keep stores the item with an unknown price (ADR-0005's derived
  unknown, §6 today). Omit stores nothing for it, and the page aggregate loses the item.

**For the owner (S2):** keep is the quality-first default. It loses no information and still
stores no wrong price. Omit is a cleanliness choice: fewer unpriced rows, some of them junk.
If omit is chosen, the recall bar must move to items stored.

### 1.6 Alternatives compared

| Option | What it is | Measured or estimated effect | Cost and risk |
|---|---|---|---|
| A. More validator levers (status quo) | One layout family per version | v8's lever: P5-14 FR 0.153 → 0.094, but one P5-16 page (0.137 → 0.134). No class over 15 % | Chases each draw's tail. Every lever is generic but rare |
| B. Toolbelt resolvers in a second pass (decision matrix) | Generic resolvers over no-match downgrades only, each guarded by catch, accuracy and priced-junk checks | Section rules: +20 gold rows at −0.002 catch. Location rules fail catch (§1.3) | Same ceiling as A, cleaner structure: resolvers can't disturb rows the validator accepts |
| C. Learned row classifier | §1.4 | FR about halved held-out; catch broke on 3 of 7 sets (logistic) | New trained artifact. Generator leakage. Needs real-wrong negatives and a recorded metric |
| D. Second model call on ungrounded rows | Re-ask Qwen3-4B with the row and nearby blocks | Not measured (no model run this session) | The validator exists to check the model independently; the same 4B model confirming its own reading is correlated evidence, not grounding. About 10 rows/page on P5-16 → ~1 extra call/page (~+14 % calls; the Pi runs 4.8 pages/h) |
| E. Measurement change (§2) | Page-clustered intervals, larger set, new recorded numbers | A version at the pooled 0.096 passes a 35-page draw 74 % of the time | Labelling cost. The bar itself is not relaxed |

## 2. Measurement: is gold-row FR at 0.12 gating the right thing?

**What gold-row FR measures.** The validator runs on the labels' own rows, a perfect
extraction. A reject there loses a correct price; it never stores a wrong one. The real-output
counterpart is 0.078 pooled (P5-16 0.093). FR is the cost side of the validator's trade, and
catch and accuracy are the benefit side. Keeping a bar on it is right: without one, a validator
that refuses everything would pass.

**Its rejects are heavy-tailed by page.** Over the 207 pages with at least 5 gold rows: the
median page FR is 0, p75 0.104, p90 0.343, p95 0.562. 107 pages have no reject, and 13 reject
more than half their rows. Per format (pooled): `html_inline` 0.290 (7 pages), `html_cards`
0.114 (28), `html_list` 0.086 (174), `price_list` 0.052 (9).

**Page-clustered bootstrap** (resampling pages, 4,000 reps) vs. the recorded row-level Wilson
interval:

| Set | FR | Page-clustered 95 % | Resamples ≤ 0.12 |
|---|---|---|---|
| P5-8 | 0.112 | [0.046, 0.203] | 0.59 |
| P5-10 | 0.087 | [0.040, 0.157] | 0.84 |
| P5-12 | 0.115 | [0.028, 0.263] | 0.55 |
| P5-14 (v8, tuned on) | 0.094 | [0.049, 0.163] | 0.81 |
| P5-16 | 0.134 | [0.061, 0.235] (Wilson: [0.121, 0.148]) | 0.41 |
| all 218 pages | 0.096 | [0.068, 0.128] | 0.94 |

**Draw-size curve.** Draws of n pages from the 218 pooled pages. Under v8 that pool reads
0.096, and it is optimistic, because 6 of the 7 sets were tuned on.

| Pages | 95 % of draws | P(draw ≤ 0.12) |
|---|---|---|
| 35 | [0.038, 0.190] | 0.74 |
| 50 | [0.044, 0.172] | 0.78 |
| 70 | [0.050, 0.159] | 0.80 |
| 100 | [0.056, 0.148] | 0.84 |
| 150 | [0.063, 0.137] | 0.89 |

The same curve for policies that lower the pooled FR: at **0.048**, a 35-page draw passes
**97 %** of the time; at 0.094, 76 %. **A larger draw narrows the interval but can't make a
version near the bar pass.** Only a lower true FR does, and a pooled tuning FR near 0.05 is
what makes a pass likely.

**The pool is finite.**
- At most **547** eligible venues remain for the next draw, and each draw labels 72.
- Large pages: P5-14's order held 45 and P5-16's 33; each draw exports 12. That leaves about
  **21** for the next draw, so the fixed 7-large quota lasts about two more draws.
- A 70-page held-out set (about 144 labelled pages) uses about a quarter of the pool per
  evaluation.

**Options for the owner (decide before any next draw; none relaxes the bar):**

| | Option | Effect | Cost |
|---|---|---|---|
| M1 | Report a page-clustered interval beside Wilson in every §8 record; pass/fail stays on the point estimate | Records honestly how much of the verdict is luck | None (script) |
| M2 | Held-out size 70 scorable pages (two draws' labelling, one evaluation) | Interval 28 % narrower ([0.050, 0.159] vs [0.038, 0.190]) | Twice the labelling per evaluation; uses the pool twice as fast; large stratum needs re-planning |
| M3 | Per-format or per-page reporting (share of pages with FR ≤ 0.2) beside the pooled bar | Shows when a fail sits on one layout | Small. Recorded, not gated, unless the owner adds a bar |
| M4 | Also gate usable prices (end to end: the share of gold prices stored exactly). The baseline would be set from tuning data, not chosen so v8 passes | Gates what users get. Catches a validator that rejects safely but too much, and a second pass that accepts junk | Needs a bar decision. The values are 0.749–0.865 by set today |
| M5 | Record two new numbers: **priced rows matching no label** (1,189 today) and **real-output wrong rows accepted** (115) | Makes the cost of any second pass visible: §8 accuracy doesn't count unmatched rows | None (script) |

**Recommendation:** M1 and M5 now, with M3 as a recorded table. M2 if the owner accepts the
labelling cost. M4 as recorded-then-gated: record it for one evaluation, and let the owner set
the bar from tuning data. The 0.12 FR bar stays.

## 3. Labels: conventions that inflate FR

Rejected gold rows under three pending conventions (all sets):

| Convention | Rows | Pages | Where |
|---|---|---|---|
| Variant taken from the dish name ("3/6 Catfish Strips Dinner" → variants "3" / "6" at $9.95 / $17.99) | 33 | 8 | P5-16 25, P5-14 3, P5-10 2, P5-12 2, spike 1 |
| Variant printed nowhere within 40 blocks (inferred) | 6 | 4 | P5-8 4, P5-5 1, P5-12 1 |
| "+$" add-on rows (the labels count own-line add-on lists as items; the validator refuses a "+$" price as an item's price) | 40 | 10 | P5-10 15, P5-16 16, P5-14 6, spike 3 |

Without these rows: P5-16 **0.134 → 0.119**, P5-10 0.087 → 0.082, pooled 0.096 → 0.091.

This is **not** a re-score of P5-16. Its verdict stands as recorded (Amendment 18), and changing
conventions after reading a draw's rejects to make it pass is what §8 forbids. The point is that
each convention is worth about a point of FR, so it should be settled on its merits before the
next draw:

- **"3/6" variants.** The labels' reading is correct data (3 pieces $9.95, 6 pieces $17.99) and
  useful to a price index. Two options. (a) Keep the labels and give the validator one generic
  rule: a slash-joined number pair in a name grounds the same-order price pair. (b) Change the
  convention to "variant only where a label is printed with its price", and label these rows
  with no variant. Recommendation: (a), because the data is right.
- **Inferred variants.** 6 rows; the brief's convention already says variants are printed
  labels. Recommendation: confirm, and correct those rows when the sets are next touched.
- **"+$" add-ons.** Amendments 8 and 10 count add-on rows as items, and v5 accepts "Add X +1"
  in the item's own block. But "+$2" is an upcharge, not a standalone price, and Amendment 14's
  adjudication already reclassified two upcharges as modifiers. Recommendation: label
  "+$"-marked rows as modifiers (not items) from the next draw, matching the validator and the
  price index's meaning. The alternative is to have the validator accept "+$" on own-line
  add-on rows under an add-on heading. That gains up to 40 rows but stores upcharges as item
  prices.

The conventions also conflict on group prices. Amendment 10 says "a priced heading over a
flavour list in another block is one item", while the P5-16 taco labels give each named taco
$3.50 (below). Which applies depends on whether the list names dishes or choices of one dish.
That is a convention the owner should state before a group-price resolver is built.

## 4. Single-price menus (the taco case)

The owner's example: a price list where every taco costs $2.50, possibly printed once. P5-16
has exactly this layout:

```
Breakfast Tacos – TACOTLAN          ← heading
$3.50.                              ← one price for the section
Served daily from 9:00 am …; Substitute organic corn tortilla for $0.95;
Each additional item $0.75          ← modifier lines with their own prices
Noe Taco / Ham, egg & cheese
Hugo Taco / Bacon, egg & cheese     ← six named tacos, none priced
…
Specialty Tacos                     ← next section prices each item ($3.75, $4.75, …)
```

Measured over all 218 pages:
- **Sections** of three or more priced items with one shared price: **138** (766 items, 84
  pages). Most print the price on every item, which grounds today.
- **Gold rejects inside one-price sections:** **128** on 21 pages (8 % of all rejects; 118
  `price_not_grounded`).
- **Whole pages** with one price for every item: **8 of 218**, holding **11** rejects.

| Approach | Grain | Gain | Cost | Trade-off |
|---|---|---|---|---|
| Page-level "single-price menu" classifier | page | at most 11 rejects | A trained model and labels per page | Wrong grain: menus mix sections, and the taco page also prices each specialty taco |
| Section rule: heading, one price-only line, then notes and unpriced items (strict) | section | 12 gold rows | catch −0.001 | Misses the taco page: "Each additional item $0.75" (4 words) is neither a note sentence nor a price line, and every fix drifts toward modifier detection |
| Section rule: the section's price-only lines all print one amount, and it is above the item | section | **20 gold rows**, incl. the 6 breakfast tacos; P5-16 0.134 → 0.128 | catch −0.002 (17 corruptions); **+101 priced unlabelled rows** | Generic, auditable, no training. Narrow. Risks "from $3.50" and "choose 4 for $16" combo prices being spread over every item |
| Section-level learned detector | section | up to the 128 rows | 138 positive sections on 84 pages is little training data; same leakage as §1.4 | Broader, but opaque; would still need "each / from / choose" semantics |
| Feature of the row classifier | row | included in §1.4 (`single_price_section`) | — | The section signal is one input among several, not its own stage |

**Recommendation:** treat single prices at the **section** grain, as one deterministic resolver
in [5b]: the "one amount on the section's price lines" rule, with a wording check that refuses
"from", "starting at", "choose", "any N" and "combo" on the price line or heading. Measure it
under §1.3's guards, with the stored-unlabelled count recorded. A separate single-price
classifier isn't worth its training data at 8 whole-price pages in 218. Before building, the
owner settles the convention conflict (§3) on whether a priced heading over a named list
prices each name.

## 5. Recommendation

1. **Measurement first (owner, before any draw):** M1 page-clustered interval, M5 the two new
   numbers, M3 per-format/per-page tables; M2 (70 pages) and M4 (usable prices) are the owner's
   call. The FR bar stays at 0.12.
2. **Labels (owner):** the three conventions in §3, plus the group-price convention in §4,
   applied from the next draw only.
3. **Structure (proposed, Amendment 19):** a stage **[5b] price resolution** after the validator,
   over no-match downgrades only, with these outcomes:
   - **accept:** the row stores its price; the evidence is the resolver's grounding span;
   - **keep unpriced:** today's downgrade, the default;
   - **omit:** only if the owner chooses it, and then the recall bar moves to items stored.

   Contents, in order:
   - (a) generic deterministic resolvers, the toolbelt chosen per page by measured signals;
     the first candidate is §4's section rule;
   - (b) a learned row classifier, **only after** it holds catch ≥ 0.97 and accuracy ≥ 0.98
     on every tuning set leave-one-set-out, with real-output wrong rows among its negatives
     and both new numbers recorded. Its weights are checked in like `classifier-v2`, with no
     scikit-learn at runtime (logistic scoring in plain Python) and no new model if it
     reuses potion-base-8M.

   D (a second model call) is not proposed as an acceptance authority.
4. **Target before spending a draw:** a pooled tuning FR near **0.05** with catch and accuracy
   held on every set. On the curve above, that passes a 35-page draw about 97 % of the time.
   Below that, another draw mostly measures luck and uses up the pool.

## Doc drift noticed

ROADMAP Phase 5's header says "ADR-0013 … (Amendments 1–13)"; the ADR is at Amendment 18
(19 proposed). Not changed here: no decision is recorded in this session.
