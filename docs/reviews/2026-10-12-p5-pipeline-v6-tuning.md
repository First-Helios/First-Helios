# Pipeline version v6: tuning on the P5-10 findings

Session P5-11, 2026-10-12. Follows the failed held-out evaluation of v5
([2026-10-12-p5-v5-held-out-evaluation.md](./2026-10-12-p5-v5-held-out-evaluation.md),
ADR-0013 Amendment 12), with the P5-9 procedure
([2026-10-09-p5-pipeline-v5-tuning.md](./2026-10-09-p5-pipeline-v5-tuning.md),
Amendment 11). **These are tuning numbers, not a §8 evaluation.** Every page scored here
has been seen while tuning; v6 is not cleared for extraction runs until it passes §8 on a
fresh held-out draw (below, "Next held-out evaluation").

Candidate version (model, prompt text, grammar, segmenter and classifier unchanged):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v6;validator-v6;classifier-v2
```

Page bodies, labels, outputs and scratch scripts stay in the worktree's gitignored
`var/tune/` (copies; the originals were not edited). This file keeps counts and rates.

## Tuning data

| Set | Pages | Gold items / prices | Formats | Saved answers |
|---|---|---|---|---|
| Spike gold pages (dev 6, ho1 8, ho2 10, ho3 9) | 33 | 1,843 / 2,050 | `html_list` 22, `html_cards` 6, `html_inline` 4, `price_list` 1 | `v5d` (P5-9's final) |
| P5-5 pages, confirmed labels | 10 | 822 / 778 | `html_list` 8, `html_cards` 2 | `v5d` |
| P5-8 scored pages, blind labels (= confirmed) | 35 | 2,456 / 2,722 | `html_list` 26, `html_cards` 5, `html_inline` 2, `price_list` 2 | `v5d` |
| P5-10 scored pages, blind labels with R1/R2 (= confirmed) | 35 | 2,731 / 2,991 | `html_list` 28, `html_cards` 6, `price_list` 1 | `v5` (P5-10's extract-CLI run) |

The P5-10 pages were copied by their held-out ids only (`held_out.json`: pages, blocks,
blind labels, the `v5` answers); P5-10's 37 labelled but unscored pages were not copied
and not looked at: they stay unseen. L5 (chunk-v2.3) changes the model's input for 2 of
these pages; their answers were regenerated (`v6c`) and the other pages' saved answers
carried over (greedy decoding: unchanged input, unchanged answer).

Scored with the harness's own functions (`score_page`, `loss_page`, `corruption_eval`,
seed 7) as frozen in Amendment 9 (H1a variant-aware matching, H1b strict gold-row false
reject), summed per set and per format. The baseline below reproduces the P5-9 record's
candidate v5 (spike, P5-5, P5-8) and the P5-10 record (bars, per format, loss buckets,
false-reject reasons, corruption per type) exactly.

## Owner decisions (before any tuning)

| | Question | Answer |
|---|---|---|
| T1 levers | Which non-model levers (group and stacked prices; price-reader forms; split a row named by a list; prices at the end of wrapped lines) | **All of them, iterating on each: several implementations, keep the best** |
| T2 card layout | Change the chunker so the model sees the cards' chrome blocks (model input) | **Priced short chrome runs** (`chunk-v2.3`): a run of at most 4 chrome blocks between body blocks is sent when it prints a marked price; the affected pages are re-run with `nohup` |
| T3 line-wrapped | The page that prints every line as a heading (the model takes name lines for sections) | **Not this session**: no line-joining chunk rule |
| T4 versions | Version names | **`validator-v6`, `repairs-v6`, `chunk-v2.3`**: the shared reader is part of the validator and the repairs, as in P5-9's T1 |
| Keep rule | Per lever | As P5-9: **no tuning set gets worse on any of the four bars**; per-format drops reported, a format crossing a bar blocks the lever. Target: the four bars on P5-10 and P5-8, P5-5 and the spike set kept passing |
| — | Who runs the re-run | **The session** (owner, 2026-10-12: "do what you need"). The first try started a new Compose project, whose image rebuild filled the laptop's disk; the owner freed space and the re-run reused P5-10's built images (`helios-p510`, `--no-build`) |

## Baseline (v5, frozen harness)

| Set | Item recall | Usable | Price accuracy | Gold FR | Catch |
|---|---|---|---|---|---|
| Spike 33 | 0.905 (1667/1843) | 0.844 | 0.995 (1746/1754) | 0.037 (75/2050) | 0.987 |
| P5-5 10 | 0.887 (729/822) | 0.753 | 0.990 (595/601) | 0.112 (87/778) | 0.998 |
| P5-8 35 | 0.871 (2139/2456) | 0.742 | 0.983 (2118/2154) | 0.116 (315/2722) | 0.994 |
| P5-10 35 | 0.819 (2238/2731) | 0.663 | 0.997 (2128/2135) | 0.168 (501/2991) | 0.994 |

Where P5-10's 501 rejected gold rows and 493 missed items sat (diagnosis before tuning):
group prices printed once (~150 rows on 4 pages), labels stacked over their prices
(~75 rows on 2 pages, a layout the P5-10 record did not name), prices at the end of
wrapped lines on bare-price pages (~70 rows), an integer glued to a name (45 rows), and
for recall the card page (92 items: each card's name, price and "Ingredients▾" sit in a
button, segmented as chrome, so the chunker never sent them) and lists the model returned
as one item.

## Levers, in order (cumulative; each measured on all four sets, per format)

Columns: item recall / usable / price accuracy / gold FR / catch.

| Lever | Component | Spike 33 | P5-5 10 | P5-8 35 | P5-10 35 | Kept? |
|---|---|---|---|---|---|---|
| Baseline v5 | — | 0.905 / 0.844 / 0.995 / 0.037 / 0.987 | 0.887 / 0.753 / 0.990 / 0.112 / 0.998 | 0.871 / 0.742 / 0.983 / 0.116 / 0.994 | 0.819 / 0.663 / 0.997 / 0.168 / 0.994 | — |
| L1 first form: integers glued to a word ("Cod Cakes16") or after a spaced dash ("feta -13") on every page; fraction labels | prices, validator | unchanged | unchanged | −1 usable (CamelCase "OrangeChicken16.99" now grounded) | 0.150 FR | **no**: also reads tab counts ("Margaritas & Cocktails16") on a card page as prices |
| **L1** the new integer forms only on a page that prints its prices bare (more blocks end in a bare integer than print a marked price, chrome included); a glued integer splits a name only when no decimals follow; a fraction label "$10.95/1/2lb" | prices (`bare_page`), validator | unchanged | unchanged | unchanged | 0.819 / **0.680** / 0.997 / **0.150** / 0.993 | yes, note 1 |
| **L2a** a short label on its own line over its price, in a stack of at least two label / price pairs ("Small" "$6" "Large" "$10"), labels that price and doesn't end the run | validator (`label_tokens`, shared with the repairs) | 0.905 / 0.845 / 0.995 / **0.021** / 0.987 | unchanged | 0.871 / 0.743 / 0.983 / **0.111** / 0.994 | 0.819 / **0.690** / 0.997 / **0.133** / **0.996** | yes: +95 gold rows, every lost real accept replaced by the same row with its printed variant |
| L2b first form: a section's first line under its heading prices every unpriced item below | validator | catch 0.970 | catch 0.986 | catch 0.983 | catch **0.968** | **no**: the first item's own line ("Taco $3") priced the section |
| L2b second form: the line needs two labelled prices and a section that prints no other price | validator | unchanged | unchanged | 1 wrong accept ("grand gold" took the item above's "Blanco 15.95") | 0.103 FR | **no** |
| L2b third form: the item must print inside that section | validator | unchanged | unchanged | — | 1 swap through on a page that prints each list's price above and below | **no** |
| **L2b** a price-less block that lists names ("Potato & Egg \| Bean & Egg", "Dos Equis, Modelo, Pacifico") shares the one price on the line right above ("3.75 EACH:", "$4.50", "6", a ":"-ended line) or the price-only line right below ("Glass \| 6"), and only it; not the line above when the block before it is another item's unpriced name ("El Camino" "$16.00" over its ingredients); a section's price line under its heading as in the third form, variant checked | validator (`list_price`, `section_line`) | unchanged | unchanged | 0.871 / 0.743 / 0.983 / **0.111** (301) / 0.994 | 0.819 / **0.697** / 0.997 / **0.103** / 0.996 | yes: +92 gold rows, no new wrong accept, per-page catch unchanged |
| L3 first form: a row named by a list of names in its block becomes one row per name | repairs | acc 0.994, −10 usable | acc **0.979** | acc 0.981 | 0.839 recall | **no**: description ingredients ("sausage, pork ribs") matched other dishes |
| L3 second form: names capitalized, no parentheses, list block unpriced | repairs | −10 usable | acc 0.987 | — | 0.831 | **no**: names with a comma ("Sausage, Egg & Cheese", "Chardonnay, CA") split |
| **L3** split on "\|" / "•" (two or more names) or commas (three or more), every name capitalized and printed in the block, the block a price-less list with its price printed once beside it (L2b's layout); the price line below has at most one label word ("Glass \| 6", not "FULL POCKET $9 / $11") | repairs (`split_listed`), validator | unchanged | unchanged | **0.871 (2140)** / 0.743 / 0.983 / 0.111 / 0.994 | **0.828 (2261)** / 0.698 / 0.997 / 0.103 / 0.996 | yes: no wrong or junk accept |
| **L4** on a bare-price page a line's last number counts in a price run ("… cotija, pepitas 12": a description wrapped over several lines) | validator (`_run_tokens`) | unchanged | 0.887 / **0.761** / **0.992** / **0.105** / 0.995 | 0.871 / **0.744** / 0.983 / **0.109** / 0.994 | 0.828 / **0.703** / 0.997 / **0.093** / 0.996 | yes: +37 gold rows, one wrong accept removed (P5-5) |
| L3b first form: tags in parentheses allowed when no separator falls inside | repairs | — | — | — | +5 junk rows (a combo's parts "Misir (red lentils), Kik (…)") | **no** |
| **L3b** parentheses allowed only as a short tag ("(NA)", "(GF)", ≤ 4 characters) | repairs | unchanged | unchanged | unchanged | **0.831 (2269)** / **0.706** / 0.997 / 0.093 / 0.996 | yes |
| **L5** chunk-v2.3: a run of at most 4 chrome blocks between body blocks is sent when it prints a marked price (v4 reader, frozen); a heading that names an item heads no section price line | chunker (re-run of 2 pages, `v6c`), validator | **0.907 (1672)** / 0.844 / 0.995 / 0.021 / 0.987 | unchanged | unchanged | **0.864 (2359)** / **0.735** / 0.997 / 0.093 / 0.996 | yes, note 2 |

**Note 1 (L1).** P5-10 catch 0.994 → 0.993 is a draw shift: more accepted gold rows change
which trials the seed-7 stream draws. Scored with one stream per page, the uncaught
corruptions are identical before and after the lever (as P5-9's note 2). The same check
was run after every kept lever; "per-page catch unchanged" below means that. Where a
page's own draw changed (spike page `630e…` after L2a, P5-10 `fe3b…` while tuning L2b),
the same trials were judged by both code versions: the previous code catches no trial the
new one misses.

**Note 2 (L5).** The re-run (2026-10-12, 20:32 to 20:47 UTC, 30 chunks, all stopped on
their own, none recovered or retried) exposes the card page: 249 of 278 P5-10
`html_cards` items found (was 159), 0 → 85 of that page's 92. On the spike page it also
changes (`1b1c…`, 9 chunks) the model now names some cards by their tagline: recall +5
items, usable prices −3 (1733 → 1730; `html_cards` 0.832 → 0.824), no bar moves. One new
wrong accept on the card page ("Chicken Fajitas 62": the previous card's heading read as
a section heading over its "For 1 $32 · For 2 $62" line) was removed by the item-heading
guard, which changes no gold-row verdict.

**Not changed.** The all-heading line-wrapped page (T3; about 20 items); lists of names
printed without any price (a tequila selection, 40 items on one page) and add-on lists
the model skips: the model never emits them, so no repair can find them; a "Single \| 10 •
Double \| 14 • Shot \| 8" line, whose bare integers after "|" stay unread (P5-9 dropped
"|" bare pairs); "$30.00 Per Person" over heading-only catering items (23 rows, one page).

## Candidate v6 (final)

| Set / format | Pages | Item recall | Usable | Price accuracy | Gold FR | Catch | Real-output FR / catch |
|---|---|---|---|---|---|---|---|
| **Spike 33** | 33 | 0.907 (1672/1843) | 0.844 (1730/2050) | 0.995 (1749/1757) | 0.021 (44/2050) | 0.987 | 0.036 / 0.461 |
| `html_list` | 22 | 0.907 | 0.838 | 0.996 | 0.022 | 0.996 | 0.035 / 0.424 |
| `html_cards` | 6 | 0.891 | 0.824 | 0.997 | 0.014 | 0.979 | 0.037 / 0.655 |
| `html_inline` | 4 | 0.927 | 0.890 | 0.994 | 0.027 | 0.965 | 0.043 / 0.400 |
| `price_list` | 1 | 0.750 | 0.714 | 0.909 | 0.000 | 1.000 | — |
| spike 24 | 24 | 0.912 | 0.866 | 0.995 | 0.015 | 0.984 | 0.033 / 0.580 |
| ho3 | 9 | 0.894 | 0.776 | 0.997 | 0.042 | 0.993 | 0.047 / 0.245 |
| **P5-5 10** | 10 | 0.887 (729/822) | 0.761 (592/778) | 0.992 (601/606) | 0.105 (82/778) | 0.995 | 0.054 / 0.712 |
| `html_list` | 8 | 0.889 | 0.780 | 0.992 | 0.092 | 0.997 | 0.050 / 0.710 |
| `html_cards` | 2 | 0.800 | 0.378 | 1.000 | 0.378 | 1.000 | 0.176 / 0.750 |
| **P5-8 35** | 35 | 0.871 (2140/2456) | 0.744 (2025/2722) | 0.983 (2128/2164) | 0.109 (298/2722) | 0.994 | 0.115 / 0.640 |
| `html_list` | 26 | 0.888 | 0.778 | 0.981 | 0.057 | 0.997 | 0.094 / 0.542 |
| `html_cards` | 5 | 0.913 | 0.876 | 0.994 | 0.046 | 0.996 | 0.059 / 0.835 |
| `html_inline` | 2 | 0.638 | 0.215 | 0.958 (46/48) | 0.701 | 0.920 | 0.626 / 0.900 |
| `price_list` | 2 | 0.900 | 0.741 | 1.000 | 0.173 | 1.000 | 0.032 / — |
| **P5-10 35** | 35 | **0.864** (2359/2731) | 0.735 (2198/2991) | 0.997 (2346/2353) | **0.093** (278/2991) | 0.996 | 0.090 / 0.693 |
| `html_list` | 28 | 0.860 | 0.733 | 0.997 | 0.098 | 0.998 | 0.080 / 0.650 |
| `html_cards` | 6 | 0.896 | 0.746 | 1.000 (187/187) | 0.053 | 0.979 | 0.194 / 0.874 |
| `price_list` | 1 | 0.857 | 0.829 | 1.000 | 0.000 | 1.000 | 0.000 / — |

**Against the bars (tuning pages):** all four sets pass all four bars (price accuracy
≥ 0.98, item recall ≥ 0.85, gold-row false reject ≤ 0.12, catch ≥ 0.97). The tightest:
P5-8 price accuracy 0.983 and P5-10 item recall 0.864.

Per format against the baseline: no format crossed a bar. Gold FR went down or stayed on
every format; recall went up or stayed on every format. Usable prices dropped only on
spike `html_cards` (0.832 → 0.824, note 2). The formats under a bar at baseline stay
there unchanged: P5-8 `html_inline` (accuracy 0.958, catch 0.920; P5-9's flag), spike
`price_list` (accuracy 0.909, one page), spike `html_inline` catch 0.965.

**Loss buckets, P5-10** (every gold price in one bucket, 2,991): `accepted` 2,108 →
2,322; `item_missed` 512 → 388; `not_accepted:price_not_grounded` 186 → 125;
`wrong_amount` 89 → 89; `row_unpriced` 49 → 61; `not_accepted:name_not_grounded` 34 → 0;
`not_accepted:price_bound_to_other_item` 8 → 1; `not_accepted:variant_not_grounded` 3 → 3;
`price_belongs_to_other_variant` 1 → 1; `addon_price` 1 → 1.

**Gold-row false rejects by reason:** P5-10 `price_not_grounded` 335 → 187,
`variant_not_grounded` 88 → 72, `name_not_grounded` 38 → 4, `price_bound_to_other_item`
30 → 5, `price_belongs_to_other_variant` 6 → 6, `addon_price` 4 → 4. P5-8
`price_not_grounded` 228 → 219, `variant_not_grounded` 45 → 38, `name_not_grounded` 28 → 28,
`price_belongs_to_other_variant` 7 → 7, `price_bound_to_other_item` 7 → 6. Spike 75 → 44
(mostly `price_not_grounded` 49 → 31 and `variant_not_grounded` 23 → 10: stacked labels).

**Corruption per type** (caught / n, baseline → candidate):

| Set | `invented_item` | `mutated_price` | `other_section_price` | `swapped_prices` |
|---|---|---|---|---|
| Spike 33 | 330/330 → 330/330 | 326/329 → 325/329 | 277/279 → 278/279 | 627/642 → 624/640 |
| P5-5 10 | 100/100 → 100/100 | 88/88 → 87/88 | 71/71 → 71/71 | 163/164 → 169/170 |
| P5-8 35 | 350/350 → 350/350 | 333/333 → 333/333 | 305/306 → 305/306 | 623/632 → 626/634 |
| P5-10 35 | 330/330 → 330/330 | 298/299 → 306/306 | 293/293 → 300/300 | 568/576 → 570/576 |

(The counts move because accepting more gold rows changes the trials drawn; per-page
streams show no trial newly let through, note 1.)

## Next held-out evaluation (needed before any extraction run)

The P5-8 / P5-10 procedure (Amendments 10 and 12): **seed 20261012**, drawing from the
laptop pass (`helios_laptop`) with P5-5's spike exclusions plus **all 162 venues labelled
so far** (P5-5 18, P5-8 72, P5-10 72) **and their 162 sites**
(`var/tune/next-draw-exclusions.json` = P5-10's
`var/menu-eval/p5-10/next-draw-exclusions-p5-11.json`, sha256
`224e42243b0f4ace4c9171dd7256a5d62ddc82464f2443b6ffafc369e706002a`, checked); size strata
with P5-8's fixed cutoffs (small < 176, large ≥ 500), read before content; parallel blind
labellers with the owner's conventions (R1, R2) and spot check, frozen and hashed before
the first model call; the real extract CLI against the pinned `llama-server`; scored with
this harness as frozen; pass/fail on the pooled set. The pool shrinks (at most 956
eligible venues). The label-free scale run stays deferred to the Pi (Amendment 10 item 5).

**Practical (laptop):** a Compose project with a new name rebuilds the worker and
model-check images; on 2026-10-12 that filled the laptop's disk. Reuse a built project
(`-p helios-p510 … up --no-build`) or check free space first.
