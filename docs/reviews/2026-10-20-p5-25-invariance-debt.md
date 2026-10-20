# P5-25 invariance debt: R1–R3 applied, repair 4b fixed, C3t back, stop at variant-in-name

Session P5-25, 2026-10-20. Plan of record: the owner's rulings R1–R3 in the
[P5-24 record](./2026-10-20-p5-24-resolver-block.md) §6. **No model run, no GPU, no held-out
draw** (R3; seed 20261015 and its exclusions `dd748ff5…` are untouched). All numbers are CPU
work on the saved Qwen3-4B Q4_0 answers under labels-v9 (15,791 gold rows on 218 tuning
pages, 7 sets) and on the 17 archived DEV configurations, on branch
`worktree-p5-18-pipeline-v9`.

**Outcome.** v9 is now resolve-v2 + repairs-v9: pooled gold-row FR **0.0930 → 0.0842**,
usable prices 0.7837 → 0.7855, no rise in accepted-unmatched or wrong-accepted rows, [5b]
accepts 26 real rows, all exact, and 0 corrupt rows on the paired trials. Invariance goes from
6,655 to 6,638 flips with 0 added. One debt fix was kept (repair 4b reads the printed name).
It let C3t back in under R2. The block stopped at the next class, variant written into the
name, which gains +2 real prices. FR is not near 0.05, and the debt barely explains it
(§2). **The draw decision is the owner's** (§7). Amendment 21 is drafted, not accepted.

## 1. Gates

Each lever was scored against the state before it on:

- **(a) keep rule** (Amendment 11, Amendment 19 items 5 and 7) on the seven tuning sets: no set
  worse on item recall, price accuracy, gold-row FR or catch; no rise in accepted-unmatched or
  wrong-accepted rows;
- **(b) ADR-0017 item 2** on the 17 DEV configurations: pooled usable rises, no configuration
  beyond the A/B band (accuracy 0.0014, unmatched 12, wrong 1), every leave-one-model-out fold
  passes;
- **(c) invariance:** no added page/style flip, gains included; a kept fix must lower the total.

Catch follows **R1** for a [5b] change (paired trials, the seed-7 trials drawn from the
baseline's clean accepts: 0 corrupt [5b] accepts; seed-7 catch ≥ 0.97 per set), and the
literal seed-7 no-worse rule for a repair or validator change. Scratch:
`var/menu-eval/p5-25/` in the main checkout. `gate.sh NAME BEFORE_TUNE BEFORE_DEV BEFORE_INV
[BASE_RESOLVERS]` runs (a) to (c) plus `p25_paired.py`, with at most 5 workers and the stages run
one after another. `p25_quick.py` is a 1.5-minute pre-screen (real counts, gold-row FR,
invariance), and every lever kept or rejected on it was confirmed with `gate.sh` or rejected on
its own numbers.

## 2. Step 1: R2 applied, C4 alone

`resolved_label_line` (C3t) removed from `RESOLVERS`, `resolved_name_price` (C4) kept.

| Set | Usable | Gold-row FR | Seed-7 catch | Unmatched | Wrong |
|---|---|---|---|---|---|
| spike | 0.8649 → 0.8659 | 0.0137 = | 0.9885 = | 154 = | 7 = |
| P5-5 | 0.7628 = | 0.1062 = | 1.0000 = | 72 = | 5 = |
| P5-8 | 0.7560 → 0.7637 | 0.1111 → 0.1011 | 0.9957 → 0.9963 | 166 = | 36 = |
| P5-10 | 0.7589 = | 0.0841 → 0.0823 | 0.9961 → 0.9967 | 128 = | 8 = |
| P5-12 | 0.7636 = | 0.1151 = | 0.9947 = | 222 = | 17 = |
| P5-14 | 0.7904 = | 0.0926 → 0.0915 | 0.9910 → 0.9890 | 271 = | 23 = |
| P5-16 | 0.7971 → 0.7980 | 0.1232 → 0.1206 | 0.9949 → 0.9962 | 194 = | 21 = |
| pooled | 0.7837 → 0.7853 | **0.0930 → 0.0904** (1,468 → 1,428) | 0.9938 → 0.9939 | 1,207 = | 117 = |

Accuracy and recall are unchanged or up on every set. [5b] accepts 25 real rows, all exact. The
paired trials hold 0 corrupt [5b] accepts. P5-14's seed-7 dip is above 0.97, so R1 passes. DEV:
pooled +2, all folds pass. Invariance 6,655 → 6,653, 0 added. **Kept: the step-2 baseline.**
The brief expected FR ≈ 0.090: most of c34b's 0.084 was C3t's.

## 3. Step 2: debt ranked by real-output impact

For each class: how often the saved real answers write that style (`p25_styles.py`; a raw
row is matched to its gold item), an **oracle bound** on the real gain (only that style's
rows rewritten to the gold style, then the full harness), how many gold-row FR rows it can
explain, and the cause in code.

| Class | Flips (C4) | Real rows in the style (of 21,038) | Oracle Δ usable / unm / wrong | Gold FR rows explained | Cause |
|---|---|---|---|---|---|
| claim drift (`claim_next`, `claim_price_block`) | 345 + 307 | 1,641 next block, 715 price block, 688 elsewhere in the item's span | +13 / −1 / +5, +4 / +1 / −2, +11 / −2 / −19 (+28 / −2 / −16) | ≤ 18 (gold rows whose name grounds off the gold block) | validator pass 1: a claim that does not print the name falls back to the first grounding block at or after the previous row's (254 flips ground a far copy); repair 4b's label window is claim-relative |
| variant written into the name (both forms) | 2,736 × 2 | 378 + 35 | −70 / +11 / 0 and −2 / 0 / 0 | 0 directly. Gold rows carry `v`, and 368 FR rows fail variant grounding in any style | validator name grounding needs every name word in one block: "Antipasto Salad Single" is `name_not_grounded` (2,670 of 2,736) |
| letter case (`case_lower` / upper / title) | 451 / 27 / 25 | 8 / 3 / 37 (+18 mixed) | 0 / 0 / 0 | 0 (case only matters for unpriced rows) | stitch reads the model's casing: `_is_description_line` and the echo rule drop or merge a lower-cased dish (427 accept → absent); `split_listed` and the validator's `_NOT_ITEM` also read it |
| section none / generic | 13 / 13 | 0 / 55 | 0 / 0 / 0 | 0 | row order and the dedupe key follow section grouping |

Gold-row FR under C4 is 1,428 rows: 981 `price_not_grounded`, 341 `variant_not_grounded`,
53 `name_not_grounded`, 27 `price_belongs_to_other_variant`, 17 `price_bound_to_other_item`,
5 implausible amount, 4 add-on. 1,357 of them have the name grounded on its own gold block.
The gold rows go to the validator without repairs, in the gold style. **The invariance debt is
a latent risk for the next model, not the cause of today's FR.** That matches P5-20's finding.

Impact order: claim drift (the only class with real upside), then variant in name, then case,
then section.

## 4. Step 3: levers, one at a time

| Lever | Change | Result | Decision |
|---|---|---|---|
| A | validator: an unprinted claim grounds at the nearest block above it that prints the name (≤ 4) | flips −507 (claim 652 → 145); real usable +16, wrong −6; **accepted-unmatched +9 on 5 sets** ("KIDS' MENU" over "$7", "COFFEE" over "$3.25", wine names); spike gold-row FR +1 (a gold block "." now grounds "Cubano Grilled Cheese"); 1 added pair | rejected (keep rule) |
| A2 | A, only when the claim prints no price | flips −42; usable −2; unmatched +4; 2 added pairs | rejected |
| D | repair 4b anchored on `stitch.name_block` (claim ± 2) | flips −11, usable +2; does not reach a price line 5 blocks down | superseded |
| D3 | 4b anchored on the printed name: the claim, else the nearest of 8 blocks above, else ± 2 | keep rule pass (usable +2, wrong −1), flips −15, 0 added; **DEV pooled −1** (a note above the name, "pizzas listed below are Large (16")…", kept an inferred "Large") | rejected (item 2) |
| **D5** | D3, and above the name only price-first lines count | keep rule pass (usable +3, wrong −1); DEV pooled **+5**, all folds; flips 6,653 → **6,638**, 0 added | **kept** (`7d40388`) |
| **C3t on D5** | `resolved_label_line` back in `RESOLVERS` | FR **0.0904 → 0.0842** (−99 rows); 0 corrupt [5b] accepts on the paired trials; seed-7 catch ≥ 0.97 everywhere (P5-12 0.9947 → 0.9941 and P5-16 0.9962 → 0.9956 are reshuffle dips that R1 admits); DEV +3, all folds; 6,638 → 6,638, 0 added | **kept** (R2's condition met) |
| C | a variant written into the name moves to `v` when the rest of the name is printed near the claim and the moved words are the printed label of a price at the row's amount (Amendment 19 item 2(b)) | flips 6,638 → 3,067 (variant styles −3,577); **real usable +2**; unmatched +2 (2 sets); 4 added pairs (a name wrapped onto its price line, "Karbach Brewing" / "Lovestreet Kolsch $6", reads as name + label) | **stop: below the 25-row budget**, and fails the gates |
| B (measured after the stop, for the record) | case read from the page (`printed_initial`) in stitch, `split_listed` and `_NOT_ITEM` | case flips −501, claim flips +66, **31 added pairs**, item recall down on 4 sets, real usable 0 | not kept |

**Disclosures.**
- D5 was written after reading the DEV page that failed D3. From that point DEV is not an
  independent check of D5's lower window.
- Budget reading. The brief's "gains < 25 gold rows on real outputs" was applied to each class
  as a whole. For claim drift that is D5 plus the C3t re-test the brief asks for: 99 gold-row
  FR rows and +4 real usable, 0 junk. D5 alone gains +3 real usable and 0 gold rows. A reading
  that requires 25 real usable prices per fix would have stopped the block at D5, and C3t would
  stay out. That needs the owner's ruling (Q2 below).
- The variant-in-name oracle bound is negative: rewriting the model's rows to the gold style
  loses 72 usable prices. On these answers the harness reads the model's own style better than
  the gold style.

## 5. Step 4: constants (commit `d5924f4`)

| Constant | Value | Basis |
|---|---|---|
| `RESOLVER_VERSION` | `resolve-v2` | adds C3t, C4 |
| `REPAIRS_VERSION` | `repairs-v9` | D5 |
| `VALIDATOR_VERSION` | `validator-v8` (unchanged) | no validator lever kept |
| `RESOLVED_PRICE_CONFIDENCE` | 0.83 → **0.87** | 95 % Wilson lower bound of 26/26 exact real [5b] accepts (0.871), rounded down: P5-18's rule. In-sample |
| `TUNING_RESOLVED_SHARE_MAX` | 0.0 → **0.23** | the tuning maximum per-page [5b] share (0.222, P5-8 `2f8e9a845c2b`, 20 of 90 rows), rounded up |
| `TUNING_DOWNGRADED_SHARE_MAX` | 0.47 (unchanged) | 95th percentile 0.462 |
| `USABLE_BAR` | **0.74** | owner (P5-23); `evaluate report` prints pass/fail |

Every [5b] accept keeps its own reason and the [5b] confidence, and [5b] still refuses by
default: C4 has no confidence of its own, it uses the [5b] constant. Context: `--ctx-size
12288` (6,144 per slot), committed in P5-24 (`43bc411`). Amendment 21 (drafted in ADR-0013,
**Proposed**) records items 1–9: context and its reason, R1, R2 and resolve-v2, repairs-v9,
the debt not paid, the constants, the version string, the tuning result and the open draw.

## 6. Result: v9 resolve-v1 → resolve-v2 + repairs-v9

| Set | Item recall | Accuracy | Usable | Gold-row FR | Catch (seed 7) | Unmatched | Wrong |
|---|---|---|---|---|---|---|---|
| spike | 0.9143 = | 0.9960 = | 0.8649 → 0.8659 | 0.0137 → 0.0132 | 0.9885 → 0.9892 | 154 = | 7 = |
| P5-5 | 0.8856 = | 0.9916 = | 0.7628 = | 0.1062 = | 1.0000 = | 72 = | 5 = |
| P5-8 | 0.8803 = | 0.9830 → 0.9831 | 0.7560 → 0.7641 | 0.1111 → 0.1011 | 0.9957 → 0.9963 | 166 = | 36 = |
| P5-10 | 0.8769 = | 0.9966 = | 0.7589 = | 0.0841 → 0.0751 | 0.9961 → 0.9967 | 128 = | 8 = |
| P5-12 | 0.8657 = | 0.9913 → 0.9918 | 0.7636 → 0.7640 | 0.1151 → 0.1025 | 0.9947 → **0.9941** | 222 = | 17 → 16 |
| P5-14 | 0.8888 = | 0.9900 = | 0.7904 = | 0.0926 → 0.0817 | 0.9910 → 0.9931 | 271 = | 23 = |
| P5-16 | 0.9121 = | 0.9897 → 0.9898 | 0.7971 → 0.7988 | 0.1232 → 0.1125 | 0.9949 → 0.9956 | 194 = | 21 = |
| **pooled** | 0.8880 = | 0.9911 → 0.9912 | **0.7837 → 0.7855** (12,376 → 12,404) | **0.0930 → 0.0842** (1,468 → 1,329) | **0.9938 → 0.9944** | 1,207 = | 117 → 116 |

- Bold catch: P5-12's seed-7 dip (8 → 9 misses of 1,519 → 1,523 trials), the same reshuffle as
  P5-24's R1 question. On the paired trials drawn from v9's clean accepts, catch is equal on
  every set and [5b] accepts 0 corrupt rows. Read under R1, every set passes; under the literal
  rule, P5-12 fails.
- Gold-row FR page-clustered 95 %: [0.066, 0.127] → [0.058, 0.116]; resamples ≤ 0.12: 0.946 →
  0.986.
- Per format: html_list 0.0833 → 0.0759 (174 pages), html_cards 0.1135 → 0.1033 (28),
  html_inline 0.2848 → 0.2422 (7), price_list 0.0522 = (9).
- [5b] real accepts: 0 → 26, all at an exact gold amount, none unmatched.
- DEV, 17 configurations: pooled usable +10. No configuration is beyond the band (Qwen3.5-9B:
  accuracy −0.0012, wrong +1, inside it). All 17 folds pass.
- **In-sample all-bar pass probability** (`joint_pass.py`, pages resampled from the 218; bars
  accuracy 0.98, recall 0.85, FR 0.12, usable 0.74; catch not simulated):

  | Version | 35 pages | 70 pages | FR bar alone, 35 / 70 |
  |---|---|---|---|
  | v9 (resolve-v1) | 0.714 | 0.815 | 0.775 / 0.840 |
  | resolve-v2 + repairs-v9 | **0.765** | **0.875** | 0.837 / 0.905 |

  These are upper bounds: every past draw read worse than its tuning sets (P5-12 0.126, P5-14
  0.153, P5-16 0.134).
- **Invariance, 218 pages** (flips per style, v9 → now; price forms, whitespace, empty `v` and
  section case stay at 0):

  | claim_next | claim_price_block | case_lower | case_upper / title | variant_in_name (each form) | section_none / generic | total |
  |---|---|---|---|---|---|---|
  | 347 → 340 | 307 → 297 | 451 = | 27 / 25 = | 2,736 = | 13 / 13 = | **6,655 → 6,638**, 0 added |

## 7. For the owner

- **Q1. The draw (R3).** Amendment 19 item 7's "near 0.05" is not met: FR reads 0.084.
  §3 shows the remaining FR is validator grounding coverage (981 `price_not_grounded` rows with
  the name on its own block), not output style. Options:
  - (a) draw now at 35 pages (in-sample pass ≈ 0.77, an upper bound);
  - (b) revisit item 1(e)'s 70-page set (≈ 0.88);
  - (c) another block aimed at the `price_not_grounded` rows, under the same gates.
- **Q2. Budget reading.** Confirm that the 25-row budget applies per class: claim drift
  = D5 + C3t, 99 gold rows. If it applies per fix in real usable prices, D5 (+3) and with it
  C3t come out, and FR returns to 0.0904.
- **Q3. Remaining debt** (6,638 flips; the variant and case classes are 90 % of it): keep it
  recorded as latent risk (ADR-0017 Consequences), or allow a debt-only fix, one that cuts
  flips with no real gain, under a separate budget. C would then need its name-wrap case
  fixed (4 added flips, +2 unmatched).
- **Q4. Amendment 21** (Proposed): accept as drafted, including `RESOLVED_PRICE_CONFIDENCE`
  0.87 (in-sample Wilson; 0.83 was 20/20 under resolve-v1).

## 8. Verification

`make ci` on the branch (the gitignored scratch set aside): see the PR body. Database tests are
skipped here (no PostgreSQL `*_test` database), so this is not database acceptance.
