# P5-24 resolver block: invariance suite, [5b] resolvers, Q6 stop

Session P5-24, 2026-10-20. Plan of record: the
[P5-23 register](./2026-10-20-p5-23-findings-integration.md) (owner decisions Q2, Q5, Q6).
This record covers steps 1–2 (invariance suite, [5b] resolvers under the keep rule) and the
Q6 stop. **No model run, no GPU, no held-out draw.** All numbers are CPU work on the saved
Qwen3-4B Q4_0 answers, under labels-v9 (15,791 gold rows on 218 tuning pages), on branch
`worktree-p5-18-pipeline-v9`. The draw's exclusions (`dd748ff5…`) are untouched.

**Outcome: the Q6 stop is reached at pooled gold-row FR 0.084, not near 0.05.** Per Q6 the
next step is a re-plan with the owner, not a draw. Two measurement questions (below) need the
owner's ruling before any resolver can be called kept.

## 1. Invariance suite (ADR-0017 item 1)

`packages/helios_parsing/invariance.py` and `evaluate invariance [--out] [--baseline]`
(commit `8bdaecf`). It ports P5-20's scratch suite: gold rows written as a perfect model
output, each of 15 meaning-preserving styles applied page-wide, and the gold (item, amount)
pairs whose status (accept / downgrade / reject / absent) changes counted per style.
`--baseline` fails on any page and style that flips more than before.

- **Port check:** on P5-20's 158 pages, same data and code, all per-page counts equal the
  archived map (`invariance-frozen.json`): 0 of 158 pages differ.
- **Baseline debt, v9 on all 218 tuning pages** (15,568 gold prices, 14,420 accepted):

| Style | Flips | Lost accepts | Gained accepts |
|---|---|---|---|
| claim_next | 347 | 313 | 29 |
| claim_price_block | 307 | 267 | 34 |
| case_lower | 451 | 427 | 10 |
| case_upper / case_title | 27 / 25 | 4 / 2 | 12 / 12 |
| variant_in_name (both forms) | 2,736 | 2,261 | 9 |
| section_none / section_generic | 13 / 13 | 13 / 13 | 0 |
| price forms, whitespace, empty `v`, section case | 0 | 0 | 0 |

## 2. Gates used for every lever

Each lever was scored on three gates, each against v9 (resolve-v1):

- **Keep rule** (Amendment 11, Amendment 19 item 5) on the seven tuning sets: no set worse on
  item recall, price accuracy, gold-row FR or catch; no rise in accepted-unmatched; (Amendment
  19 item 7) no rise in wrong-price accepts.
- **ADR-0017 item 2** on the 17 archived DEV configurations (15 pages, extracted from
  `p5-21-prompt-opt.tar.zst` into `var/menu-eval/corpus/p5-19-21-dev/`; v9's DEV counts
  reproduce P5-21's for all 17): pooled usable rises, no configuration beyond the baseline A/B
  band (accuracy 0.0014, unmatched 12, wrong 1), every leave-one-model-out fold passes.
- **Invariance:** no added page/style flips against the v9 baseline.

Plus a paired corruption count (P5-18's): on the trials the seed-7 sampler draws from v9's
clean accepts, how many corrupt rows [5b] accepts.

## 3. Resolvers measured

| Lever | Gold rows gained | Real [5b] accepts (exact / unmatched / wrong) | Paired corrupt accepts | Result |
|---|---|---|---|---|
| C3 own-line label (as P5-18's proxy) | 123 | 2 / 0 / 0 | 0 | catch p5-16 worse on seed 7 (worse in 16 of 20 seeds); 4 added invariance pairs |
| C3 + repair 4b reading own-line labels | 123 | 44 / 8 / 1 | — | **rejected**: accuracy down on 4 sets, unmatched up, usable −33, 10 added pairs |
| **C3t** own-line label, nearest label line only | ≈ 99 | 2 / 0 / 0 | 0 | in c34b below |
| C4 first form (variant rows included) | 88 | 27 / 0 / 0 | 0 | **withdrawn**: it accepted a row whose variant the page does not print (unit test), against Amendment 19 item 2(b) |
| **C4** name-adjacent price: a row without a variant, name printed once and unglued, price right after | ≈ 40 | 25 / 0 / 0 | 0 | in c34b below |
| C2 numbers in names, narrowed (name printed as one span) | 15 | 13 / 6 / 0 | — | **below the Q6 budget** (< 25 gold, junk > 0) |
| C1 unread (P5-18 proxy) | 126 | 60 / 35 / 38 | 24 | junk-heavy, not built |

C4's first proxy had 7 unmatched and 3 wrong real accepts and 2 corrupt accepts, all on one
page of glued inline text ("ShuMai(5pcs)9.99", "Chicken" printed under several dishes);
refusing a name printed twice in its block or with glued words removed all of them.

### c34b = resolve-v1 + C3t + C4, per tuning set (v9 → c34b)

| Set | Item recall | Accuracy | Usable | Gold-row FR | Catch | Unmatched | Wrong |
|---|---|---|---|---|---|---|---|
| spike | 0.9143 = | 0.9960 = | 0.8649 → 0.8659 | 0.0137 → 0.0132 | 0.9885 → 0.9892 | 154 = | 7 = |
| P5-5 | 0.8856 = | 0.9916 = | 0.7628 = | 0.1062 = | 1.0000 = | 72 = | 5 = |
| P5-8 | 0.8803 = | 0.9830 → 0.9831 | 0.7560 → 0.7637 | 0.1111 → 0.1011 | 0.9957 → 0.9963 | 166 = | 36 = |
| P5-10 | 0.8769 = | 0.9966 = | 0.7589 = | 0.0841 → 0.0751 | 0.9961 → 0.9967 | 128 = | 8 = |
| P5-12 | 0.8657 = | 0.9913 = | 0.7636 → 0.7644 | 0.1151 → 0.1025 | 0.9947 → **0.9941** | 222 = | 17 = |
| P5-14 | 0.8888 = | 0.9900 = | 0.7904 = | 0.0926 → 0.0817 | 0.9910 → 0.9931 | 271 = | 23 = |
| P5-16 | 0.9121 = | 0.9897 → 0.9898 | 0.7971 → 0.7980 | 0.1232 → 0.1125 | 0.9949 → 0.9956 | 194 = | 21 = |
| pooled | 0.8880 = | 0.9911 = | 0.7837 → 0.7854 | **0.0930 → 0.0842** (1,468 → 1,329) | 0.9938 → 0.9944 | 1,207 = | 117 = |

[5b] accepts 27 real rows, all at an exact gold amount (P5-18's resolve-v1 accepted 0).
ADR-0017 item 2: pooled DEV usable +9, no regression beyond the band, all 17 folds pass.
Invariance: 6,655 → 6,666 flips, 4 added page/style pairs (below). Bold: the one keep-rule
miss (R1).

## 4. Questions for the owner

**R1. Catch under [5b].** `corruption_eval` samples its trials from the rows the harness
accepts when clean, so any resolver that accepts more gold rows reshuffles the trials. On seed
7, c34b's catch is lower on P5-12 (0.9947 → 0.9941: 8 → 9 uncaught of 1,519 → 1,523
trials). Every corrupt row accepted in those trials is a *validator* accept; [5b] accepts
none, and none on the paired trials of any set. Over seeds 1–10 c34b's P5-12 catch is better
on average (+0.0004, better in 7 of 10). The same reshuffle moved P5-8 and P5-14 below v9 in
earlier forms of the block (C4 alone, c34) and P5-16 under C3's first form (worse in 16 of 20
seeds; there one of the extra misses was a corrupt amount equal to the item's other gold price).
Read literally, the keep rule rejects c34b on noise. Options: keep the literal
seed-7 rule; or, for [5b] levers, judge catch on the paired trials (0 corrupt [5b] accepts)
with the seed-7 catch still ≥ 0.97 per set.

**R2. Invariance flips that are gains.** The 4 added pairs are all gains under claim drift
(downgrade → accept), on 2 pages (P5-12 `29612ad9e3eb` sides, P5-14 `de0f1e8f4d75`). Cause:
repair 4b (`drop_unprinted_variants`) looks for a label from 2 blocks above to 4 below the
claimed block, so a claim one block later keeps a variant ("Medium (16oz)" over "$4.50", 5
blocks below the name) that a claim on the name drops, and C3t then grounds it. The repair
fix tried (above) hurt real outputs. Read literally, ADR-0017 rejects C3t; C4 alone adds 0.

**R3. Re-plan (Q6).** With both rulings favourable, the best measured v9 reads FR 0.084.
Simulated draws resampled from the 218 tuning pages (all four gated bars, usable ≥ 0.74):

| Version | 35 pages | 70 pages |
|---|---|---|
| v9 (resolve-v1) | 0.71 | 0.82 |
| c34b | 0.76 | 0.87 |
| c34b, FR bar alone | 0.84 | 0.91 |

These are in-sample: every past draw read worse than its tuning sets (P5-12 0.126, P5-14
0.153, P5-16 0.134), so they are upper bounds. Amendment 19 item 1(e) revisits a 70-page set
"once a version reads near the target in item 7"; item 7's "near 0.05" is not met.

## 5. Also pending

- **Compose `--ctx-size 12288`** (Q5): the diff is prepared, uncommitted, for the owner's
  review (infra).
- **Step 3 constants** (`RESOLVER_VERSION`, usable bar 0.74, confidence for the new
  resolvers) and Amendment 21 wait on R1–R3.
- `make ci` on the branch: 686 passed, 727 skipped (database tests skipped: not database
  acceptance), with the gitignored scratch moved aside.

## 6. Owner rulings (2026-10-20)

- **R1: paired trials.** For a [5b] change, catch is judged on the paired trials (the
  trials seed 7 draws from the baseline's clean accepts): [5b] must accept 0 corrupt rows
  there, and each set's seed-7 catch must still be ≥ 0.97. To be recorded in Amendment 21.
  Repair and validator changes keep the literal seed-7 rule.
- **R2: drop C3t, keep C4.** ADR-0017 applies literally: any added flip rejects, gains
  included. C3t (`resolved_label_line`) comes out of `RESOLVERS`; it may return once the
  repair 4b claim-relative window no longer drifts.
- **R3: fix invariance debt first.** No draw yet. Next block: generic harness work on the
  largest debt classes (claim drift, `case_lower`, variant written into the name), under
  the keep rule, ADR-0017 item 2 and invariance, then re-measure FR and re-decide the draw.
- **Compose `--ctx-size 12288`: approved** and committed on this branch (no deploy, no Pi
  change).
