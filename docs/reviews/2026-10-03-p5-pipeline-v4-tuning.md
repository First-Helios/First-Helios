# Pipeline version v4: tuning on the P5-5 findings

Session P5-7, 2026-10-03. Follows the failed first held-out evaluation
([2026-09-30-p5-held-out-evaluation.md](./2026-09-30-p5-held-out-evaluation.md),
ADR-0013 Amendment 8). **These are tuning numbers, not a §8 evaluation.** Every page
scored here has been seen while tuning; the v4 version is not cleared for extraction
runs until it passes §8 on a fresh held-out draw (below, "Next held-out evaluation").

Candidate version (model, prompt, chunking and segmenter unchanged, so saved raw
answers were re-scored without the model):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.3;chunk-v2.1;segment-v2;repairs-v4;validator-v4;classifier-v2
```

Page bodies, labels, outputs and scratch scripts stay in the worktree's gitignored
`var/tune/` (copies; the originals were not edited). This file keeps counts and rates.

## Tuning data

| Set | Pages | Gold items / prices | Formats | Saved answers |
|---|---|---|---|---|
| Spike gold pages (dev 6, ho1 8, ho2 10, ho3 9; splits as the spike used them) | 33 | 1,843 / 2,050 | `html_list` 22, `html_cards` 6, `html_inline` 4, `price_list` 1 | `st-v23` (the spike's Pi run of process v2.3; PR #58 showed the ported repairs and validator reproduce it) |
| P5-5 held-out pages (now tuning pages), confirmed labels | 10 | 822 / 778 | `html_list` 8, `html_cards` 2 | `slice5` (P5-5's extract-CLI run) |

`compare`/`loss`/`corrupt` numbers below come from the harness's own functions
(`score_page`, `loss_page`, `corruption_eval`, seed 7), summed per set and per format.

## Owner decisions (before any tuning)

| | Question | Answer |
|---|---|---|
| H1a | Harness: match a row to a gold *variant* of an item, or name-only | **Variant-aware**, applied to every set and to the baseline |
| H1b | Gold-row false-reject metric vs a dish repeated in several inline menus | **Keep strict**: one gold row per printed placement; the fix belongs in the validator |
| H2a | Deterministic levers | Duplicate key + placement, unit/variant fixes; and free to try others (price printed twice, add-on prices), keeping only what measures well |
| H2b | Model-input levers | Price-before-name data prep; the rest at the session's judgement |
| H3 | Stronger model / GPU serving | **Out of scope** this session; stay on Qwen3-4B Q4_0 |
| H4 | Long model runs | The owner runs them with `nohup`; none turned out to be needed (below) |

**H1a as built** (`evaluation.match`): a row matches an item by the same name tokens,
or by naming one of the item's variants (row tokens = the variant's, or the name's
plus the variant's) when that item is printed at or before the row's claimed block;
the item nearest the claimed block wins. The "at or before" condition was added
during the session after the first implementation matched wine option lines
("bottle $75") to the *next* dish; the baseline and every lever were re-scored under
the corrected rule, and only those numbers are reported here.

## Baseline (slice-5 version, frozen H1a harness)

| Set | Item recall | Usable | Price accuracy | Gold FR | Catch | FR / catch on real output |
|---|---|---|---|---|---|---|
| Spike 33 | 0.903 (1664/1843) | 0.829 | 0.992 (1717/1731) | 0.036 (74/2050) | 0.987 | 0.043 / 0.483 |
| – spike 24 (dev+ho1+ho2) | 0.908 | 0.850 | 0.993 | 0.015 | 0.984 | 0.038 / 0.614 |
| – ho3 | 0.888 | 0.766 | 0.990 | 0.103 | 0.971 | 0.059 / 0.233 |
| P5-5 10 | 0.838 (689/822) | 0.629 | 0.969 (497/513) | 0.306 (238/778) | 0.988 | 0.158 / 0.634 |

Name-only scores of the same outputs (the frozen P5-5 harness) for reference: spike
33 0.901 / 0.819 / 0.993; P5-5 0.837 / 0.620 / 0.963 (the P5-5 record's numbers).

## Levers, in order (cumulative; each measured on both sets, per format)

| Lever | Component | Spike 33: items / usable / acc / gold FR / catch | P5-5: items / usable / acc / gold FR / catch | Kept? |
|---|---|---|---|---|
| Baseline | — | 0.903 / 0.829 / 0.992 / 0.036 / 0.987 | 0.838 / 0.629 / 0.969 / 0.306 / 0.988 | — |
| **L1** duplicate key includes the placement: the validator's key adds the grounded name block, `rows_of`'s dedupe adds the claimed block | validator, repairs | 0.903 / 0.830 / 0.992 / 0.036 / 0.987 | **0.887 / 0.679** / 0.971 / **0.134** / 0.981 | yes |
| **L2** a spaced unit suffix is a price label ("$18.00 / LB.", "$32.00 / 12 pcs") | validator (`price_label`, shared with stitch) | unchanged | 0.887 / **0.699** / 0.972 / **0.112** / 0.981 | yes |
| **L3** a variant that is no printed price label near the item is dropped (a description copied into the variant slot) | repairs | 0.903 / **0.835** / 0.992 / 0.036 / 0.987 | 0.887 / **0.746** / 0.972 / 0.112 / 0.981 | yes |
| L5a price printed twice, first form: cut a run before any price-only block whose text recurs 2–4 blocks later | validator | 0.903 / 0.821 / 0.994 / **0.050** / 0.989 | 0.887 / 0.751 / 0.987 / 0.117 / 0.995 | **no**: spike `html_list` usable 0.832 → 0.810, gold FR 0.048 → 0.070 (uniform size runs "$9" / "$15" repeated under every item look like copies) |
| **L5** price printed twice: when the run's first block repeats the price-only block just above the name, the run is that one block | validator | 0.903 / 0.835 / **0.994** / 0.037 / 0.988 | 0.887 / 0.747 / **0.983** / 0.112 / **0.998** | yes |
| **L4** a price printed with a leading "+" ("+$1.50", "vegan +$1") grounds no item price (`addon_price`) | validator | 0.903 / 0.835 / 0.994 / 0.038 / 0.987 | 0.887 / 0.747 / **0.990** / 0.112 / 0.998 | yes, see note |
| Price-before-name data prep | segmenter/chunker (model re-run) | not built | not built | **dropped**, see below |
| Chunking of very large pages | chunker (model re-run) | not built | not built | **dropped**, see below |

L1 also changed `rows_of`: before, the page's dedupe collapsed a dish repeated in a
second inline menu before the validator saw it, which is why it raised item recall
(on the largest P5-5 page, prices in `item_missed` 89 → 53) as well as cutting false rejects.

**L4 note.** Spike gold FR rises by 3 rows (`html_cards` 0.005 → 0.014): one spike
page prints "pick your protein: … (+$1)" under three smoothies, and the spike's
labeller counted the $1 as an item price, while the P5-5 labels (and this rule) treat
"+$" prices as modifiers. The labels were not changed; the 3 rows are counted as
false rejects. Spike usable and accuracy are unchanged.

**Price-before-name prep, dropped without a model run.** The P5-5 page behind this
finding is a site-builder layout whose components are absolutely positioned: in the
static HTML each name, description and price is its own component, and their document
order is not the visual order (prices sometimes come two at a time after two names).
The grouping exists only in CSS coordinates, so a static fix would mean reading one
builder's position styles: per-platform logic, against the universal-process rule.
Rendering (slice 6) is the generic route. On that page 67 of 83 gold prices are still
lost.

**Large-page chunking, dropped without a model run.** After L1 the largest page's
remaining misses (53 of 413 items) are spread over its sections, not chunk-sized gaps,
and P5-5 item recall (0.887) is above the bar; there was no measured target for a
chunker change worth a ~5 h model run.

No lever changed the prompt, chunking, segmenter or model, so no model re-run was
needed (H4).

## Candidate v4 (final)

| Set / format | Pages | Item recall | Usable | Price accuracy | Gold FR | Catch | Real-output FR / catch |
|---|---|---|---|---|---|---|---|
| **Spike 33** | 33 | 0.903 (1664/1843) | 0.835 (1712/2050) | 0.994 (1729/1740) | 0.038 (78/2050) | 0.987 | 0.045 / 0.482 |
| `html_list` | 22 | 0.903 | 0.832 | 0.996 | 0.049 | 0.994 | 0.036 / 0.450 |
| `html_cards` | 6 | 0.878 | 0.797 | 0.987 | 0.014 | 0.979 | 0.080 / 0.648 |
| `html_inline` | 4 | 0.927 | 0.890 | 0.994 | 0.027 | 0.965 | 0.043 / 0.450 |
| `price_list` | 1 | 0.750 | 0.714 | 0.909 | 0.000 | 1.000 | — |
| spike 24 | 24 | 0.908 | 0.854 | 0.993 | 0.017 | 0.984 | 0.043 / 0.603 |
| ho3 | 9 | 0.888 | 0.776 | 0.997 | 0.105 | 0.996 | 0.054 / 0.259 |
| **P5-5 10** | 10 | 0.887 (729/822) | 0.747 (581/778) | 0.990 (590/596) | 0.112 (87/778) | 0.998 | 0.069 / 0.703 |
| `html_list` | 8 | 0.889 | 0.765 | 0.990 | 0.099 | 0.997 | 0.066 / 0.700 |
| `html_cards` | 2 | 0.800 | 0.378 | 1.000 | 0.378 | 1.000 | 0.176 / 0.750 |

Per format against the baseline: no format's item recall, usable prices or price
accuracy went down on either set; gold FR rose only on spike `html_cards` (L4 note);
catch moved within ±0.01 except `html_cards` on the spike (0.982 → 0.979, fewer
accepted gold rows to corrupt) — every per-format catch stays ≥ 0.965.

**Loss buckets** (every gold price in one bucket):

| Bucket | Spike baseline | Spike v4 | P5-5 baseline | P5-5 v4 |
|---|---|---|---|---|
| `accepted` | 1701 (0.830) | 1713 (0.836) | 494 (0.635) | 587 (0.754) |
| `item_missed` | 167 | 167 | 126 | 89 |
| `wrong_amount` | 87 | 85 | 49 | 47 |
| `not_accepted:price_not_grounded` | 46 | 46 | 29 | 27 |
| `row_unpriced` | 24 | 24 | 15 | 15 |
| `not_accepted:variant_not_grounded` | 14 | 4 | 59 | 7 |
| `not_accepted:price_bound_to_other_item` | 7 | 7 | 6 | 5 |
| `not_accepted:name_not_grounded` | 4 | 4 | 0 | 0 |
| `not_accepted:duplicate_row` | 0 | 0 | 0 | 1 |

**Gold-row false rejects by reason:** spike baseline `price_not_grounded` 52,
`variant_not_grounded` 22 → v4 52, 23, `addon_price` 3. P5-5 baseline
`duplicate_row` 134, `price_not_grounded` 62, `variant_not_grounded` 35,
`implausible_amount` 4, `name_not_grounded` 3 → v4 `duplicate_row` 0,
`price_not_grounded` 62, `variant_not_grounded` 18, 4, 3.

**Corruption per type** (gold rows, seed 7; caught / n, indistinguishable):

| Type | Spike baseline | Spike v4 | P5-5 baseline | P5-5 v4 |
|---|---|---|---|---|
| `invented_item` | 330/330, 0 | 330/330, 0 | 100/100, 0 | 100/100, 0 |
| `mutated_price` | 325/329, 4 | 326/329, 3 | 88/88, 0 | 88/88, 0 |
| `other_section_price` | 279/279, 0 | 277/279, 0 | 71/71, 0 | 71/71, 0 |
| `swapped_prices` | 627/644, 10 | 627/642, 12 | 157/162, 1 | 163/164, 1 |

## What's left (tuning sets, v4)

- P5-5 gold FR 0.112 sits just under the 0.12 bar; 62 of its 87 are
  `price_not_grounded`, mostly on the absolutely positioned grid page.
- The 6 remaining wrong accepted P5-5 prices: three add-on lines printed without a
  "+" ("avocado $2", "Shrimp tempura $3") that the model emitted as items and the
  harness matched to same-named dishes elsewhere, one row on the positioned pizza grid,
  and two rows on the doubled-price page that the new rule doesn't reach (the model
  claimed the price line, not the name, and took the next item's copy).
- `html_cards` usable prices on P5-5 are 0.378: the model emits only the first tier of
  priced packages ("Silver / Gold / Platinum"), and gold FR there is 0.378 (14 rows).
  Two pages, so not tuned on.
- The spike's ho3 gold FR (0.105) is unchanged by v4.

## Next held-out evaluation (needed before any extraction run)

The same procedure as P5-5 ([record](./2026-09-30-p5-held-out-evaluation.md)):

- a **new seed**, drawing from the same laptop first pass (`helios_laptop`) with the
  P5-5 draw's exclusions (spike venues and hosts) plus **the 18 venues labelled in
  P5-5**; one page per venue and per site; static pages;
- **blind labels** by a fresh agent, frozen and hashed before the first model call;
- extraction with the real extract CLI against the pinned `llama-server` image and the
  manifest's GGUF (the saved P5-5-style raw answers feed the harness);
- scored with this harness as frozen here (H1a variant-aware matching, H1b strict
  gold FR);
- disagreements through the **blinded adjudicator**, the owner confirming every label
  change; both label sets hashed and both scores recorded.

The Menu-write commit fix (Amendment 8 item 6, a parallel session) is still needed
before a full extraction pass, independently of quality.
