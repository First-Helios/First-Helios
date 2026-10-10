# Pipeline version v5: tuning on the P5-8 findings

Session P5-9, 2026-10-09. Follows the failed held-out evaluation of v4
([2026-10-09-p5-v4-held-out-evaluation.md](./2026-10-09-p5-v4-held-out-evaluation.md),
ADR-0013 Amendment 10). **These are tuning numbers, not a §8 evaluation.** Every page
scored here has been seen while tuning; v5 is not cleared for extraction runs until it
passes §8 on a fresh held-out draw (below, "Next held-out evaluation").

Candidate version (model, prompt and segmenter unchanged):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.3;chunk-v2.2;segment-v2;repairs-v5;validator-v5;classifier-v2
```

Page bodies, labels, outputs and scratch scripts stay in the worktree's gitignored
`var/tune/` (copies; the originals were not edited). This file keeps counts and rates.

## Tuning data

| Set | Pages | Gold items / prices | Formats | Saved answers |
|---|---|---|---|---|
| Spike gold pages (dev 6, ho1 8, ho2 10, ho3 9) | 33 | 1,843 / 2,050 | `html_list` 22, `html_cards` 6, `html_inline` 4, `price_list` 1 | `st-v23` |
| P5-5 pages, confirmed labels | 10 | 822 / 778 | `html_list` 8, `html_cards` 2 | `slice5` |
| P5-8 scored pages, blind labels (= confirmed) | 35 | 2,456 / 2,722 | `html_list` 26, `html_cards` 5, `html_inline` 2, `price_list` 2 | `v4` (P5-8's extract-CLI run) |

P5-8's 37 labelled but unscored pages were not copied and not looked at: they stay
unseen. Scored with the harness's own functions (`score_page`, `loss_page`,
`corruption_eval`, seed 7) as frozen in Amendment 9 (H1a variant-aware matching, H1b
strict gold-row false reject), summed per set and per format. The v4 baseline below
reproduces the v4 tuning record (spike, P5-5) and the P5-8 record exactly.

## Owner decisions (before any tuning)

| | Question | Answer |
|---|---|---|
| T1 where | Where the price-text normalization lives | **One shared reader** in `prices.py` for the validator, stitch, the row repairs and `parse_amount`; the page classifier keeps the v4 tokenizer (its features are frozen with `classifier-v2`) and the prompt's sparse-retry counter is unchanged (part of `prompt-v2.3`) |
| T1 forms | Which printed forms | **Marked forms**: a currency word before or after the amount ("12.5 USD", "USD 12", "7.5 Dollars"), a one-decimal amount only with a mark, "$.40", "¢", a word glued to the price ("From4.5"), an underscore separator ("Patacones_12"), "|" bare pairs. An unmarked one-decimal number ("6.2", "0.5 pounds", "WCAG 2.1") stays unread |
| T1 locators | Evidence span of a new form | **The printed price and its mark** ("12.5 USD", "50¢", "$.40"), as "$12" spans include the "$"; a glued word and the underscore stay outside. Locator format, segmented text and existing spans unchanged |
| T1 version | Version names | **`validator-v5`, `repairs-v5`**: the reader is part of both; no new component in the version string |
| T2 | Card-layout grounding | **A repeated name doesn't end the scan** (the gap was not distance: the name printed twice, plain then as a heading) |
| T3 | Remaining false-reject spread | Try all four (parenthesized labels, column headers, own-line add-ons, joined names), **several implementations each, keep the best** |
| T4 | Inline layouts | **Generic token fixes only** (later revisited for chunking, below) |
| Keep rule | Per lever | **No set gets worse on any of the four bars**; per-format drops reported, a format crossing a bar blocks the lever. Target: the four bars on P5-8 and on P5-5, each scored separately, the spike set kept passing |
| T5 (after L7) | P5-8 recall still short; the chunker cuts blocks at 300 characters | **Build chunk-v2.2; the owner runs the 13 affected pages** with `nohup` |

## Baseline (v4, frozen harness)

| Set | Item recall | Usable | Price accuracy | Gold FR | Catch | FR / catch on real output |
|---|---|---|---|---|---|---|
| Spike 33 | 0.903 (1664/1843) | 0.835 | 0.994 (1729/1740) | 0.038 (78/2050) | 0.987 | 0.045 / 0.482 |
| P5-5 10 | 0.887 (729/822) | 0.747 | 0.990 (590/596) | 0.112 (87/778) | 0.998 | 0.069 / 0.703 |
| P5-8 35 | 0.838 (2059/2456) | 0.647 | 0.983 (1804/1835) | 0.278 (758/2722) | 0.995 | 0.222 / 0.645 |

## Levers, in order (cumulative; each measured on all three sets, per format)

Columns: item recall / usable / price accuracy / gold FR / catch.

| Lever | Component | Spike 33 | P5-5 10 | P5-8 35 | Kept? |
|---|---|---|---|---|---|
| Baseline v4 | — | 0.903 / 0.835 / 0.994 / 0.038 / 0.987 | 0.887 / 0.747 / 0.990 / 0.112 / 0.998 | 0.838 / 0.647 / 0.983 / 0.278 / 0.995 | — |
| L1 price reader v5 with "|" bare pairs | prices (validator, stitch, repairs) | 0.903 / 0.835 / 0.994 / **0.040** / 0.987 | 0.887 / 0.752 / **0.988** / **0.113** / 0.998 | 0.838 / 0.693 / 0.982 / 0.215 / 0.996 | **no** (first form): "5 \| 9" pairs win 5 rows and lose 1 on one P5-5 page that prints each pair above *and* below the name; "add $.95 per cake" now read as a price ended three spike items' runs |
| **L1** reader v5 without "|" pairs; "add $" is a modifier's price and a modifier-only line starts no run (validator, stitch's price fill) | prices, validator, stitch | 0.903 / 0.835 / 0.994 / **0.037** / 0.987 | unchanged | 0.838 / **0.693** / 0.982 / **0.215** / 0.996 | yes, see note 1 |
| L2 method A: a claimed row moves to the last block containing its name | validator | — | — | +85 / −28 gold rows | **no**: "CHICKEN TENDERS BASKET" moved to "KIDS' CHICKEN TENDERS BASKET" |
| L2 method B: a heading repeating the item's name doesn't end the scan | validator | — | — | +85 / 0 gold rows, +147 correct real rows | no (A′ took more real rows) |
| **L2** method A′: a claimed row moves to an exact repeat of its block right below | validator | 0.903 / **0.843** / **0.995** / 0.037 / 0.987 | unchanged | 0.838 / **0.721** / 0.983 / **0.184** / 0.993 | yes, see note 2 |
| L3a first form: a parenthesized label after a price | validator (`price_label`) | — | −5 gold rows ("6” – $65 (8-12 servings)") | +23 gold rows | **no** |
| **L3a** parenthesized label only when nothing is printed before the price | validator | unchanged | unchanged | 0.838 / **0.726** / 0.982 / **0.175** / 0.994 | yes, see note 3 |
| L3b first form: a "16oz / 20oz / Pitcher" header labels the k-th price of each row below | validator, repairs | — | — | +79 gold rows, 1 real row lost | **no**: "Tempranillo \| Rioja, Spain" under one wine read as a header |
| **L3b** column headers that head at least two rows; a "/" or "—" block inside a price run doesn't end it | validator, repairs (`label_tokens`) | unchanged | unchanged | 0.838 / 0.726 / 0.982 / **0.146** / 0.993 | yes |
| L3c first form: a "+" price grounds a row whose name is printed right before it | validator | — | 2 wrong accepts ("Avocado +$1.50 \| Guacamole +$1.50": P5-5 labels them modifiers) | +3 gold rows | **no** |
| **L3c** own-line add-on: also the block's only price ("Add Sauerkraut +1") | validator | unchanged | unchanged | 0.838 / 0.726 / 0.982 / **0.145** / 0.993 | yes |
| **L3d** names joined by "," / "&" in a one-price row share the price ("sidral, sangría, topo chico $3.25"; an "A or B" row is one item) | validator | unchanged | unchanged | 0.838 / 0.726 / 0.982 / **0.142** / 0.993 | yes, see note 4 |
| L4 CamelCase parts ground names ("TonkutsuFriedChicken") | validator | — | — | +4 / −1 gold rows, 1 wrong accept, uncaught swaps on one inline page 1 → 5 | **no** (T4) |
| **L5** an underscore separates words in name grounding ("Patacones_12") | validator (`block_tokens`) | unchanged | unchanged | 0.838 / **0.731** / **0.983** / **0.131** / **0.994** | yes: +34 / −4 gold rows, that page's uncaught swaps 9 → 0 |
| **L6a** column headers reach to the section's heading (was 40 blocks) | validator | unchanged | unchanged | 0.838 / 0.731 / 0.983 / **0.121** / 0.994 | yes: +27 gold rows, 0 lost |
| **L6b** a unit glued to the price is its label ("$9gl \| $32btl") | validator | unchanged | unchanged | 0.838 / **0.734** / 0.983 / **0.116** / 0.994 | yes: +14 gold rows, 0 lost |
| **L7** a short lower-case line ("bottled $2.50", "mojito ‘rita") is an item, not a description to merge | stitch | 0.903 (1665) / 0.843 / 0.995 / 0.037 / 0.987 | unchanged | **0.841** / **0.735** / 0.983 / 0.116 / 0.994 | yes: +6 items on P5-8, +1 on the spike set |
| L8 chunk-v2.2: a block over 300 characters is sent as several lines with its id | chunker (model re-run, 13 pages) | PENDING | PENDING | PENDING | PENDING |

Gold-row counts: P5-8 gold FR 758 → 315 rows over L1–L7; the spike set 78 → 75; P5-5
87 → 87.

**Note 1 (L1).** The P5-8 accuracy point (0.983 → 0.982) is the "12.5 USD" page's lunch
list, printed a second time: the owner's convention counts a copy once, so its rows
match a same-named dinner dish in gold (four rows), and one "Chicken_4.50" add-on the
labels left out (matched to "Rustick Chicken" in the same block). These rows read
the printed price next to their name; the labels were not changed.

**Note 2 (L2).** Catch on P5-8 moves 0.996 → 0.993 because more accepted gold rows
change which trials the seed-7 stream draws: scored with one stream per page, the
uncaught corruptions are identical before and after the lever.

**Note 3 (L3a).** The one new wrong accept on P5-8 ("Vegetable Fajitas 18.95 ½ lb.") is
printed on the page ("31.95 (1 lb.) • 18.95 (½ lb.)"); the gold label lists only the
1 lb. price.

**Note 4 (L3d).** The first implementations lost rows on the jumbled inline page and
let swaps through (P5-8 catch 0.986): a group must be one row with one price and its
price right after the last name, and a row that is in no group keeps v4's region.

**Not changed.** One-label section headers ("Small (4 slices)" over a pizza list, 19 P5-8
rows) can't be told from a sub-heading; a price block above a list of heading-only items
(28 rows on one page) and a size matrix printed in another block (29 rows) were not
tried (catch risk, one page each).

## Candidate v5 (validator/repairs levers; L8 pending)

| Set / format | Pages | Item recall | Usable | Price accuracy | Gold FR | Catch | Real-output FR / catch |
|---|---|---|---|---|---|---|---|
| **Spike 33** | 33 | 0.903 (1665/1843) | 0.843 (1728/2050) | 0.995 (1745/1753) | 0.037 (75/2050) | 0.987 | 0.037 / 0.468 |
| `html_list` | 22 | 0.904 | 0.833 | 0.996 | 0.046 | 0.994 | 0.036 / 0.425 |
| `html_cards` | 6 | 0.878 | 0.835 | 0.997 | 0.014 | 0.979 | 0.037 / 0.704 |
| `html_inline` | 4 | 0.927 | 0.890 | 0.994 | 0.027 | 0.965 | 0.043 / 0.400 |
| `price_list` | 1 | 0.750 | 0.714 | 0.909 | 0.000 | 1.000 | — |
| spike 24 | 24 | 0.909 | 0.864 | 0.995 | 0.015 | 0.984 | 0.033 / 0.580 |
| ho3 | 9 | 0.888 | 0.778 | 0.997 | 0.105 | 0.996 | 0.051 / 0.259 |
| **P5-5 10** | 10 | 0.887 (729/822) | 0.747 (581/778) | 0.990 (590/596) | 0.112 (87/778) | 0.998 | 0.069 / 0.703 |
| `html_list` | 8 | 0.889 | 0.765 | 0.990 | 0.099 | 0.997 | 0.066 / 0.700 |
| `html_cards` | 2 | 0.800 | 0.378 | 1.000 | 0.378 | 1.000 | 0.176 / 0.750 |
| **P5-8 35** | 35 | **0.841** (2065/2456) | 0.735 (2001/2722) | 0.983 (2100/2136) | **0.116** (315/2722) | 0.994 | 0.098 / 0.615 |
| `html_list` | 26 | 0.888 | 0.776 | 0.981 | 0.065 | 0.998 | 0.099 / 0.534 |
| `html_cards` | 5 | 0.913 | 0.876 | 0.994 | 0.046 | 0.996 | 0.059 / 0.835 |
| `html_inline` | 2 | 0.260 | 0.126 | **0.964** (27/28) | 0.701 | 0.920 | 0.426 / 0.870 |
| `price_list` | 2 | 0.900 | 0.741 | 1.000 | 0.173 | 1.000 | 0.032 / — |

Per format against the baseline: no format's recall or usable prices went down on any
set; gold FR went down or stayed on every format. **Flag:** P5-8 `html_inline` price
accuracy 1.000 (8/8) → 0.964 (27/28) crosses 0.98 on one row, the "Chicken_4.50" add-on
of note 1 (a label omission, not a misread); its catch was below 0.97 at baseline
(0.925 → 0.920). Every other per-format catch stays ≥ 0.965 as in v4.

**Loss buckets, P5-8** (every gold price in one bucket): `accepted` 1,769 → 2,008;
`item_missed` 464 → 458; `not_accepted:price_not_grounded` 307 → 103; `wrong_amount`
124 → 124; `not_accepted:variant_not_grounded` 20 → 4; `name_not_grounded` 12 → 3.

**Gold-row false rejects by reason, P5-8:** `price_not_grounded` 516 → 228,
`variant_not_grounded` 134 → 45, `name_not_grounded` 77 → 28,
`price_belongs_to_other_variant` 25 → 7, `price_bound_to_other_item` 3 → 7,
`addon_price` 3 → 0. Without the two inline pages, P5-8 gold FR is 0.066 (165/2508).

**Corruption per type, P5-8** (caught / n): `invented_item` 340/340 → 350/350,
`mutated_price` 313/314 → 333/333, `other_section_price` 283/284 → 305/306,
`swapped_prices` 578/584 → 623/632.

## Recall: the remaining bar

After L7, P5-8 is the only set short of a bar: item recall 0.841 (bar 0.85, 2,088 items
needed). The validator and repairs can't reach it: the raw model rows themselves match
only 0.842. Of the 391 missed items, about 220 were never emitted (many are a dish's
second printed placement), and most of the rest sit on the two inline pages. There the
chunker (chunk-v2.1) sends only the first 300 characters of each block: one page prints
its menu in 2,000-character blocks, the other in image alt text, and **54 gold items lie
past the cut**. Spike and P5-5 pages have no gold item past it.

L8 (chunk-v2.2) sends a long block as several lines with its block id, cut after a
space, comma or "|" (never between "$" and its amount). Pages whose blocks all fit get
byte-identical chunks, so with greedy decoding their saved answers stay valid; the 13
tuning pages with a longer block (spike 5, P5-5 2, P5-8 6: 154 chunks) are re-run by the
owner. PENDING: results.

## Next held-out evaluation (needed before any extraction run)

The P5-8 procedure (Amendments 8 and 10): a **new seed (20261010)**, drawing from the
laptop pass (`helios_laptop`) with P5-5's spike exclusions plus **the 90 venues
labelled in P5-5 (18) and P5-8 (72) and their 90 sites** (`var/tune/next-draw-exclusions.json`,
sha256 `2579afbeecdbb2b0c6b6a1daf35868b29e63aa11b0b1f0e5d2af93787b93b030`); size strata
read before content; parallel blind labellers with the owner's conventions and spot
check, frozen and hashed before the first model call; the real extract CLI against
the pinned `llama-server`; scored with this harness as frozen; pass/fail on the pooled
set. The label-free scale run stays deferred to the Pi (Amendment 10 item 5).
