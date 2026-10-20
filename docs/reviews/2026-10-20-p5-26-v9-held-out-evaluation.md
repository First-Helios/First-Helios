# Held-out evaluation of menu-pipeline v9 (ADR-0013 §8)

Session P5-26, 2026-10-20: the §8 evaluation of v9, run on the owner's decision (Amendment 21
item 9: 35 pages now, on seed 20261015). P5-16's procedure was used on a fresh draw from the
laptop pass, scored with the v9 harness (validator, then [5b]). Version (branch
`worktree-p5-18-pipeline-v9` @ `07e9b49`, PR #93, **not merged**; the code is unchanged since
`c62b7f8`, and `07e9b49` only accepted Amendment 21):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v9;validator-v8;resolve-v2;classifier-v2
```

**Result: v9 passes §8.** This is the first version to pass. All four gated bars pass, and so
does the usable-price bar of Amendment 21:

- price accuracy **0.993**;
- item recall **0.874**;
- corruption catch **0.996**;
- gold-row false reject **0.097** (bar ≤ 0.12; Wilson [0.087, 0.108], wholly below it);
- usable prices **0.755** (bar ≥ 0.74).

A worst-case bound showed that label changes could in principle reach the FR bar, so a blinded
adjudication ran (Amendment 10 item 2). It upheld the labels: 4 mechanical changes out of 641
rows, and the same verdict (FR 0.096, usable 0.755).

The margins are thin:
- FR's page-clustered interval [0.050, 0.156] crosses the bar, and 0.80 of resamples fall
  within it.
- Usable's Wilson lower bound is 0.739.
- The model ran on the laptop GPU, which is not the production runtime.

Measured only: no pipeline, harness, schema, model, dependency or `infra/` change. Page bodies,
labels, outputs and worksheets stay in gitignored `var/menu-eval/p5-26/` (main checkout). This
file keeps only counts and rates. Pages are named by an opaque id (`sha256(record key)[:12]`).

## Owner decisions

| | Question | Answer |
|---|---|---|
| Q1 | The draw (P5-25 §7) | **35 pages now**, seed 20261015 (Amendment 19 item 7's "near 0.05" precondition is not met: tuning FR 0.084; the owner chose to draw) |
| Q2 | Budget reading | per class (D5 and C3t stay in v9) |
| Q3 | Remaining invariance debt | recorded as risk |
| Q4 | Amendment 21 | accepted as drafted |
| — | Where the model runs | the laptop GPU, Amendment 19's evaluation runtime, as in P5-16 |

## Procedure

**Draw.** P5-16's script with P5-16's exclusion list, seed **20261015**, recorded at
2026-10-20 14:18:57 UTC, before the draw.
- Pool: the extract CLI's due queue on `helios_laptop`, read-only: 1,632 pages.
- Excluded pages:
  - P5-5's exclusions: spike venues 77, spike hosts 234, spike URLs 0;
  - the 378 venues labelled in P5-5 to P5-16 (378 pages) and their sites (424 pages);
  - the list is `next-draw-exclusions-p5-17.json` (sha256
    `dd748ff55c3b2987506997200029d8b6ead8caff92278943081e2c56dd167c9b`), checked by the
    script.
- The P5-19 to P5-21 model-screen pages (DEV, VAL, TEST3) all come from those tuning sets, so
  none of them could be drawn.
- 518 eligible venues; one page per venue, at most one venue per site: an order of **433**.
  `draw.jsonl` sha256 `f02113d17dc54f485de3fe7b5b56c2196a4a54c34c3b29f705d454403f189e79`.
- Strata with the fixed cutoffs: small **226**, medium **186**, large **21** (P50 / P90
  170 / 382, recorded only). The large stratum keeps thinning (P5-14 45, P5-16 33): a later
  draw at these quotas may exhaust it.
- Exported in draw order per stratum: small 34, medium 26, large 12, so 72 pages and 21,154
  blocks. Every body re-segments byte for byte to its bundle's blocks.

**Blind labels.**
- Five fresh labeller agents worked to P5-16's brief, plus Amendment 19 item 2's conventions
  (a)–(d) stated first and taking priority, plus a page-level `modifiers` list for "+$" rows.
  No model call ran before the freeze.
- Every label parses with `gold_page` and names existing blocks.
- After the freeze, P5-18's labels-v9 transform (rules 2(b) and 2(c), applied mechanically)
  changed nothing: the labellers had already applied the conventions. labels-v9 = blind
  labels.
- Spot-check (session) of 5 held-out pages chosen for risk, **no corrections**:
  - a heading "Enchilada Plate 2 or 3" over two price columns, labelled variants "2" / "3"
    (a printed column header; rule (b) holds);
  - a row "Chicken | Beef | Fish or Shrimp 14.75 | 16 | 18" under a salads section,
    labelled three own-line priced items;
  - a page whose one price is printed in a dish name ("$10 Burrito Value Meal");
  - a drinks list printed twice, unpriced then priced, labelled per placement (wine-scoped
    anyway);
  - a whole menu printed twice (765 block texts in common; only the footer and contact
    text differ), labelled once.

Of the 72 labelled pages (4,894 items, 4,335 prices): **50 scorable** menus, **15** menus that print no prices
and **7** not menus. Classifier-v2 precision on the draw is **65/72, 0.903 [0.813, 0.952]**; see
Q-C below.

Held out: the first scorable pages per stratum in draw order, 14 / 14 / 7, at positions 1–6,
9–13, 16–21, 23, 24, 26, 28–31, 35, 41, 42, 45, 53, 57, 60, 67, 68, 70 and 219. Frozen and hashed
at **2026-10-20 14:27:38 UTC**; extraction started 14:28:08 UTC.

| Label set | Manifest sha256 |
|---|---|
| Blind, all 72 pages | `50b55afc15d39b984f41668d5b4bb434140796c558cc21d6373c5e05f54f2f52` |
| Blind = labels-v9, 35 held out | `c98d9405444597a3ffcce47109107d02c47cff56498ad322aaa2508b96bdcaf4` |
| Adjudicated (labels-v9 + 4 changes, awaiting the owner), 35 held out | `71ef058273e2a1e23308246b50e881f78ebe541be0b1f06331563ba0f750fd4a` |

**Extraction (the laptop GPU).**
- The real extract CLI from `07e9b49` ran on a disposable `TEMPLATE` clone of `helios_laptop`
  (`helios_p526_eval`). Only the clone was upgraded, to `db40e9424cba`; `helios_laptop` stays
  at `7c2e4b9d1f3a`. The queue wrapper narrowed the run to the 35 held-out Versions.
- Server: the pinned CUDA image `server-cuda-b11176` (digest `1f4b9cf5…`) with P5-13's GPU
  flags (all layers on the RTX 3070, flash attention off, f16 KV cache), 2 slots and **the
  production context of Amendment 21 item 1** (`--ctx-size 12288`, 6,144 per slot; `/props`
  confirmed it).
- The model file's sha256 was checked and the CLI's `/props` check passed. Answers were
  written to a separate store.
- **This is not the production runtime** (Amendment 15 item 7), and its greedy answers are not
  identical run to run (P5-13). Item recall, price accuracy and usable prices are GPU numbers.
  Gold-row false reject and catch run the validator and [5b] on the labels' rows and do not
  depend on the runtime.
- Temperature guard 93/78 °C on the GPU: maximum 87 °C, never tripped. The CLI's run report
  records `soc_max_temp_c` 100.0 for the laptop CPU, with `cpu_freq_cap` 1.0.

**Blinded adjudication.** It was required here because a label change could change the
verdict (Amendment 10 item 2).
- Usable prices, item recall and accuracy can only rise under the packet's answers, so FR is
  the only bar a label change could push the wrong way.
- The worst-case bound applies, row by row, every adverse answer: C "a real item" rows that
  the validator plus [5b] reject as gold rows (+102); B "not an item" removals of accepted
  gold rows (−188 from the denominator); A / D relabels that flip a gold row to rejected
  (+69). That gives (294+102+69)/(3037+102−188) = **0.158**, which could fail.
- P5-16's packet with two fixes:
  - classes from the v9 harness (`judge`, not the v8 validator alone);
  - a C row's nearby list shows out-of-scope (wine) labels too (P5-16 finding: 42 false
    "yes").
- Readings were shuffled with seed 20261020; five fresh adjudicator agents worked from the
  brief; the key stayed outside their folder.
- `apply_verdicts.py` maps the key's scored-item index back to the raw label, since
  `gold_page` drops wine-section items. P5-16's script indexed the raw list; that was harmless
  there, because its 2 changes were applied by hand.

641 rows: A 19, B 201, C 240, D 181.

| Class | Rows | Verdicts mapped back |
|---|---|---|
| A (price) | 19 | label 18, both 1 |
| B (labelled, never produced) | 201 | item 199, not an item 1, fix 1 |
| C (accepted, unmatched) | 240 | not an item 106, same dish as a recorded one 132, a real item 2 |
| D (two readings of one dish) | 181 | label 134, both 46, pipeline 1 |

**Label changes proposed: 4 applied mechanically, 2 not applied** (for the owner, finding 3):
- B13: "CAFFEINE-FREE" is a column heading, not an item.
- C3: "Ground Beef Enchiladas (GF)" $17.99 is a real dish the labels missed. Its name is at
  b0184; the change, as applied, places it at the pipeline's b0187.
- C53: "Add Seaweed" $1 is an own-line add-on with no "+".
- One D row takes the pipeline's reading.
- Not applied: B190 "Soup of the Day" should be 4.49 (Small Bowl) / 8.99 (Large Bowl).
- Not applied: C181's note that "Bruja Finca, Geisha, Lactic Black Honey" at 29 is one coffee,
  not three items under the joined-names rule.

Of the 46 D "both" rows, 43 are one bilingual page that prints each dish as a numbered Chinese
line with the price over an English line. The model named some dishes by the Chinese line, the
labels by the English. The harness scores those readings as misses, so this is a matching
limit, not a label error.

## Results (§8)

| Stage | Metric | Bar | v9, 35 pages [Wilson 95 %] | |
|---|---|---|---|---|
| [4]+repairs+[5]+[5b] | Exact price accuracy, accepted rows | ≥ 0.98 | **0.993** (2553/2572) [0.988, 0.995] | ✔ |
| [4] | Item recall | ≥ 0.85 | **0.874** (2643/3025) [0.861, 0.885] | ✔ |
| [5]+[5b] | Injected-corruption catch (gold rows, seed 7) | ≥ 0.97 | **0.996** (1590/1596) [0.992, 0.998] | ✔ |
| [5]+[5b] | False reject, correct (gold) rows | ≤ 0.12 | **0.097** (294/3037) [0.087, 0.108] | ✔ |
| End to end | Usable prices (Amendment 21) | ≥ 0.74 | **0.755** (2292/3037) [0.739, 0.770] | ✔ |
| [1] | Classifier precision on the draw | (S6f evaluation stands) | 65/72 menus, 0.903 [0.813, 0.952] | — |
| [5] on real output | False reject / catch | recorded | 0.059 (160/2713) / 0.499 (415/832) | — |

Scores use the blind labels (= labels-v9). On the adjudicated labels the results are 0.993
(2556/2575) / 0.874 (2644/3026) / 0.996 (1583/1590) / **0.096** (293/3038), usable 0.755
(2293/3038): **the same verdict.**

**Amendment 19 item 1 records:**

- Page-clustered 95 %:
  - gold-row FR [0.050, 0.156], with 0.802 of resamples ≤ 0.12;
  - usable prices [0.655, 0.833].

  Pass and fail stay on the point estimate (item 1(a)).
- Accepted rows matching no label: **398** (395 adjudicated). Real-output wrong-price rows
  accepted: **19**.
- [5b] on real output accepts 5 rows on 4 pages:
  - 3 match a label, all at the exact price;
  - 2 match no label: one Chinese-line reading of a labelled dish (dish 121 of the bilingual
    page), at its correct price, printed twice. The adjudicators judged that dish "same".

  No [5b] accept stores a wrong price. 3 matched accepts are too few to re-estimate
  `RESOLVED_PRICE_CONFIDENCE` (0.87).
- Tuning (P5-25, pooled over 218 pages) → this draw: FR 0.0842 → 0.097, usable 0.7855 →
  0.755. As in every past draw, the held-out set reads worse than the tuning sets. The
  in-sample all-bar pass rate was 0.765.

**Per stratum** (price accuracy / item recall / gold-row FR / usable):

| Stratum | Pages | Gold items / prices | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|---|
| small | 14 | 419 / 407 | 0.990 | 0.852 | 0.138 | 0.700 |
| medium | 14 | 1,079 / 1,170 | 0.998 | 0.827 | 0.141 | 0.678 |
| large | 7 | 1,527 / 1,460 | 0.990 | 0.913 | 0.050 | 0.832 |

**Per format:**

| Format | Pages | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|
| `html_list` | 26 | 0.993 | 0.853 | 0.126 | 0.713 |
| `html_cards` | 7 | 0.995 | 0.896 | 0.049 | 0.798 |
| `price_list` | 2 | 0.989 | 0.971 | 0.000 | 0.963 |

`html_list` reads above the FR bar on its own (0.126, 2,068 rows). The pooled verdict is what
§8 gates (Amendment 10 item 2), and no format-level bar is pre-registered for a held-out set.

**Corruption per type** (seed 7): `invented_item` 340/340, `mutated_price` 323/326 (3
indistinguishable), `other_section_price` 298/298, `swapped_prices` 629/632 (3
indistinguishable).

**False rejects of gold rows by reason** (294): `price_not_grounded` 198,
`variant_not_grounded` 87, `price_belongs_to_other_variant` 6, `price_bound_to_other_item` 3.
Five pages hold 201 of them (68 %). The largest, 1a9b6f1aba7f, holds 60/145: one protein price
list applied to 10 named curries (rule (d)).

**Loss buckets** (3,037 gold prices):

| Bucket | Prices | Share |
|---|---|---|
| `accepted` | 2,322 | 0.765 |
| `item_missed` | 400 | 0.132 |
| `row_unpriced` | 127 | 0.042 |
| `not_accepted:price_not_grounded` | 109 | 0.036 |
| `wrong_amount` | 66 | 0.022 |
| 4 smaller buckets | 13 | — |

**Wine scope:** the held-out labels hold 134 items / 111 prices under a wine section on 6 pages,
not scored.

**Per page** (draw position, stratum, format, gold items / prices, items found, accepted prices
exact, gold rows rejected):

| Page | Pos. | Stratum | Format | Items | Prices | Found | Exact | Gold FR |
|---|---|---|---|---|---|---|---|---|
| 69aa0e3c417e | 1 | medium | `html_list` | 63 | 67 | 59 | 61/61 | 1/67 |
| ee41b1e15bf0 | 2 | medium | `html_list` | 106 | 110 | 94 | 98/98 | 0/110 |
| 9f4485a31ada | 3 | small | `html_list` | 18 | 30 | 13 | 25/25 | 4/30 |
| 6cc999a4ce88 | 4 | large | `html_list` | 314 | 147 | 279 | 87/95 | 39/147 |
| 6a96f0864389 | 5 | small | `html_list` | 54 | 6 | 48 | 5/6 | 0/6 |
| de49ce954f20 | 6 | large | `html_list` | 177 | 177 | 152 | 147/147 | 0/177 |
| 0de6c65f0718 | 9 | small | `html_list` | 32 | 32 | 32 | 21/21 | 1/32 |
| 7d44d2b6316f | 10 | medium | `html_cards` | 94 | 1 | 78 | 0/0 | 1/1 |
| 113e4327a7dd | 11 | medium | `html_list` | 109 | 127 | 97 | 83/83 | 21/127 |
| ab61da9d75b5 | 12 | medium | `html_list` | 143 | 140 | 46 | 8/8 | 42/140 |
| 7f3af75118d9 | 13 | medium | `html_list` | 101 | 129 | 100 | 129/129 | 5/129 |
| f1a8dce2d9f4 | 16 | medium | `html_cards` | 24 | 24 | 23 | 21/23 | 0/24 |
| 1a9b6f1aba7f | 17 | medium | `html_list` | 75 | 145 | 72 | 71/71 | 60/145 |
| f8be9c6802b2 | 18 | medium | `html_list` | 85 | 88 | 62 | 55/55 | 13/88 |
| 54923b0a9bf4 | 19 | medium | `html_list` | 93 | 90 | 91 | 81/81 | 3/90 |
| d2520524a2a5 | 20 | medium | `html_list` | 38 | 57 | 34 | 50/50 | 1/57 |
| a986b802f24d | 21 | small | `html_list` | 10 | 7 | 4 | 2/2 | 3/7 |
| f1efd73aa123 | 23 | medium | `html_list` | 80 | 96 | 76 | 89/89 | 18/96 |
| 2056d6fe62b5 | 24 | large | `html_cards` | 188 | 191 | 165 | 149/150 | 0/191 |
| e92c411de099 | 26 | medium | `html_list` | 60 | 88 | 52 | 63/63 | 0/88 |
| e6942e6d1e2a | 28 | large | `html_list` | 219 | 221 | 208 | 211/211 | 1/221 |
| 5b29aa09257e | 29 | medium | `html_cards` | 8 | 8 | 8 | 8/8 | 0/8 |
| 888bcb3d80af | 30 | small | `html_cards` | 13 | 13 | 13 | 6/6 | 0/13 |
| 5c102a96768a | 31 | small | `price_list` | 8 | 8 | 7 | 7/7 | 0/8 |
| 1dd41cbb8359 | 35 | large | `price_list` | 264 | 263 | 257 | 445/450 | 0/263 |
| c97e138eb98c | 41 | small | `html_list` | 7 | 14 | 7 | 7/7 | 0/14 |
| a222a96bdb70 | 42 | small | `html_list` | 45 | 47 | 41 | 33/33 | 9/47 |
| 2918c557299f | 45 | small | `html_list` | 43 | 43 | 38 | 54/54 | 0/43 |
| ac5243160a35 | 53 | small | `html_list` | 68 | 76 | 54 | 36/37 | 29/76 |
| 87516f66c6bd | 57 | small | `html_list` | 18 | 20 | 18 | 20/20 | 0/20 |
| 6a3b871708f7 | 60 | large | `html_cards` | 142 | 172 | 132 | 159/159 | 2/172 |
| 381e2b3acd84 | 67 | small | `html_list` | 34 | 34 | 34 | 33/33 | 0/34 |
| c23c9efd5eb3 | 68 | small | `html_list` | 27 | 27 | 6 | 8/9 | 2/27 |
| e861b9e729d2 | 70 | small | `html_list` | 42 | 50 | 42 | 50/50 | 8/50 |
| fde6a5187560 | 219 | large | `html_cards` | 223 | 289 | 201 | 231/231 | 31/289 |

**Promo (recorded, not gated):** 7 promo entries and 67 promo-marked items on the held-out
pages; 57 promo-marked priced rows stored as prices.

**Run report** (35 pages; the CLI, the clone and the GPU server on the laptop):
- 35 due, 35 extracted, 0 reused answers, 0 failed;
- 8 pages flagged, 3 `jsonld` pages;
- 355 chunks, 2 sparse retries, 1 truncated chunk, 0 resent requests;
- 4,327 items and 3,049 prices written;
- 4 pages with [5b] rows;
- 1 page outside the tuning range: downgraded share 0.538 against the 0.47 limit, on 13
  priced rows;
- 1,075 s wall, 117 pages/h, 59.3 generated tokens/s per slot.

GPU throughput is not a Pi number.

## Findings

1. **v9 passes §8 on a fresh draw** after six failing versions (P5-5 to P5-16). The decisive
   change is gold-row FR: 0.134 (v8, P5-16) → 0.097. That is the stage [5b] resolvers plus
   repairs-v9, measured on gold rows, which do not depend on the runtime. The other bars hold
   at earlier levels (accuracy 0.990 → 0.993, catch 0.992 → 0.996). Recall reads 0.874
   against P5-16's 0.905, on different pages and a GPU runtime.
2. **The pass is not robust.**
   - The FR point estimate sits 70 rows inside the bar, the usable estimate 44 prices inside
     it.
   - The page-clustered FR interval reaches 0.156, and one draw in five at this version's
     page mix would read over 0.12.
   - Medium and small pages read 0.141 / 0.138 on their own.

   Amendment 19 item 7's "near 0.05" target, which the owner waived for this draw, is the
   margin this pass lacks. Production stores what it accepts with no label check (Amendment
   19), so the monthly spot check (Amendment 3; Amendment 19 item 8) is what measures v9's
   real error from here.
3. **Labels.** The adjudication upheld the labels. Four changes are mechanical and two are
   left for the owner (B190, C181); none moves a bar by more than 0.001.
4. **Classifier precision on this draw is 0.903** (7 of 72 exported pages are not menus).
   Earlier draws read 0.972 (P5-16) and 0.932 pooled (P5 classifier gap audit). §8 judges the
   classifier on its S6f evaluation, not on the draw, so this does not gate. Two of the 7 are
   judgement calls by the labellers: an SEO post printing another brand's prices, and a
   catering package list with no prices.
5. **The large stratum is thinning:** 21 left after this draw's exclusions, 12 exported, so
   at most 9 remain for a later draw before exclusions grow.

## For the owner

- **Q-A. Clearance.** Per §8, v9 is cleared for extraction runs. Amendment 8 item 1 puts the
  first pass's extraction on the laptop. Amendment 10 item 5 keeps the label-free scale run
  for the Pi, once the pages reach it and the Pi `llama-server` check is done. Choose what
  runs next and where: merge PR #93; the laptop extraction pass at production flags (CPU) or
  on the GPU; the Pi gates.
- **Q-B. Label changes.**
  - Confirm or reject the 4 applied changes (B13, C3, C53, one D row) and the 2 not applied
    (B190, C181).
  - Should C3's added row sit at its printed name block (b0184) rather than the pipeline's
    b0187?
  - None changes the verdict.
- **Q-C. Classifier precision 0.903 on this draw.** Record only, as before, or open a
  classifier check against §8's 0.95 (P5 classifier gap audit, R1)?
- **Q-D. Next draw** (only for the next version): seed 20261016, exclusions
  `next-draw-exclusions-p5-27.json` (450 venues and sites, sha256
  `3439a96175c87b03ad1397d6eb9a3207e0a1d064a12be59c8c287bcc7e9a528d`). These 35 pages are
  now tuning pages (§8).

## Owner decisions after the evaluation (2026-10-20)

| | Answer |
|---|---|
| Q-A | **The owner merges PR #93; then the full laptop extraction pass runs into `helios_laptop` on the laptop GPU.** It uses the evaluated flags, the production context (12,288) and the 93/78 °C guard. Production on the Pi stays the CPU service. |
| Q-B | **The 4 changes stand, with C3 placed at its printed name block b0184** (section "Tacos & Enchiladas"). B190 and C181 stay as labelled. The confirmed set's held-out manifest is `e1309014790701ce9c8995f9f45d44045fad060989e00032d89bef59f45eac24`. It scores as the adjudicated set: 0.993 / 0.874 / 0.996 / FR 0.096 (293/3038), usable 0.755. |
| Q-C | **A classifier check is opened** for a later session: all draws' page labels pooled against classifier-v2, for §8's 0.95 precision bar (the classifier gap audit's R1 sample). |
| Q-D | Seed 20261016 and `next-draw-exclusions-p5-27.json`, as recorded, for the next version's draw. |
| — | The disposable clone `helios_p526_eval` was dropped and the stopped GPU container removed. The answers stay in `var/menu-eval/p5-26/base`. |

## Verification

Measured only; no code changed in this session. `make ci` on the branch is run before the
commit; see the PR. Database tests are skipped here (no PostgreSQL `*_test` database), so
this is not database acceptance.
