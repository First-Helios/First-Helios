# Pipeline version v7: tuning on the P5-12 findings

Session P5-13, 2026-10-13/14. Follows the failed held-out evaluation of v6
([2026-10-13-p5-v6-held-out-evaluation.md](./2026-10-13-p5-v6-held-out-evaluation.md),
ADR-0013 Amendment 14), with the P5-9 / P5-11 procedure
([2026-10-12-p5-pipeline-v6-tuning.md](./2026-10-12-p5-pipeline-v6-tuning.md),
Amendment 13). **These are tuning numbers, not a §8 evaluation.** v7 is not cleared for
extraction runs until it passes §8 on a fresh held-out draw (below, "Next held-out
evaluation").

Candidate version (model, prompt, grammar, chunker, segmenter and classifier unchanged: the
prompt levers tried here were rejected, so every page's saved answers stay valid):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v7;validator-v7;classifier-v2
```

Page bodies, labels, outputs and scratch scripts stay in the worktree's gitignored
`var/tune/` (copies; the originals were not edited). This file keeps counts and rates.

## Owner decisions (before any tuning)

| | Question | Answer |
|---|---|---|
| Q1 overfitting guard | Tune on all 148 pages, or hold P5-12's 35 as a dev check? | **Hold P5-12 as a dev check**: scored, never tuned on. Its misses were read in P5-12's findings (and diagnosed below), so it is a weaker holdout than a fresh draw |
| Q2 lever order | Prompt and validator levers together, or the prompt alone first? | **The prompt alone, then the validator levers** (re-validating the prompt's saved answers) |
| Q3 prompt form | Rules only, or rules plus worked examples? | **Rules only** (v2.3's one worked example stays as it is) |
| Q4 re-run scope | All 148 pages at once, or staged? | **Staged, dev set first, run on the Orange Pi** (then the laptop GPU too: Q8) |
| Q5 stronger model | What ends prompt tuning? | A larger model is not feasible on the Pi (the long-term host) at today's speed; other models of this size may be tried. **If dev recall stays under 0.85, keep working the problem** (any model change still needs its own amendment, Amendment 9 item 3) |
| Q6 who runs | Session or owner? | **The session**, over ssh on the Pi |
| Q7a RUN-A-01 | Who re-times the slow Menu commit? | **The session** (below) |
| Q7b laptop DB | Upgrade `helios_laptop` to `db40e9424cba`? | **No: disposable clones only** |
| Q8 (during the session) run split | The Pi is ~2× slower than the laptop and gives different greedy answers | **The laptop is free to use, and its GPU** ("Where the model runs") |
| Q9 (during the session) dev-only layouts | The price-column page and glued one-decimal prices exist only on dev pages | **Skip them this session**: the dev check stays clean |

## Tuning data

| Set | Pages | Gold items / prices | Saved answers (laptop CPU) |
|---|---|---|---|
| Spike gold pages (dev 6, ho1 8, ho2 10, ho3 9) | 33 | 1,843 / 2,050 | `v6c` (P5-11's final) |
| P5-5 pages, confirmed labels | 10 | 822 / 778 | `v6c` |
| P5-8 scored pages | 35 | 2,456 / 2,722 | `v6c` |
| P5-10 scored pages | 35 | 2,731 / 2,991 | `v6c` |
| **P5-12 scored pages, confirmed labels: dev check** | 35 | 2,565 / 2,674 | `v6` (P5-12's extract-CLI run) |

The P5-12 pages were copied by their held-out ids only (`held_out.json`: pages, blocks,
confirmed labels, the `v6` answers); its 37 labelled but unscored pages were not copied
and not looked at. The next draw's exclusions file was copied and checked (sha256
`0c383cac72ea15f72f204077e353d4c05e8de0d8e50bd8e0ca845144b7e435c1`).

Scored with the harness's own functions (`score_page`, `loss_page`, `corruption_eval`,
seed 7) as frozen in Amendment 9, summed per set and per format.

## Baseline (v6, frozen harness)

Reproduces the P5-11 record's candidate v6 (spike, P5-5, P5-8, P5-10: bars, per format,
loss buckets, false-reject reasons, corruption per type) and the P5-12 record's
confirmed-label numbers (bars, per format, per stratum totals, loss buckets, corruption
per type, real-output FR / catch 0.080 / 0.466) exactly.

| Set | Item recall | Usable | Price accuracy | Gold FR | Catch |
|---|---|---|---|---|---|
| Spike 33 | 0.907 (1672/1843) | 0.844 | 0.995 (1749/1757) | 0.021 (44/2050) | 0.987 |
| P5-5 10 | 0.887 (729/822) | 0.761 | 0.992 (601/606) | 0.105 (82/778) | 0.995 |
| P5-8 35 | 0.871 (2140/2456) | 0.744 | 0.983 (2128/2164) | 0.109 (298/2722) | 0.994 |
| P5-10 35 | 0.864 (2359/2731) | 0.735 | 0.997 (2346/2353) | 0.093 (278/2991) | 0.996 |
| P5-12 35 (dev) | 0.821 (2107/2565) | 0.702 | 0.991 (1939/1956) | 0.126 (337/2674) | 0.995 |

## Diagnosis (before any change)

P5-12's 458 labelled items the pipeline never matched, from its blinded adjudication key:

- **218 D rows** (a pipeline row with one of the item's prices within 2 blocks, under
  another name): the model named the dish by its **description or ingredient line** (121;
  sushi rolls, breakfast tacos, smoothies, pitas printed title / description / price, and
  a wine's cuvée line), by an **adjacent line** (45: a region line "Sicily" or "London,
  England", the previous wine's price line), by its **section heading** (23), or kept a
  **menu number** and claimed the price block ("13) Aloo Tikki Chana Chaat" at the "9 USD"
  block, 17); 12 other. Three pages hold 139 of them (a producer-over-cuvée wine list 60,
  a price-above-and-below wine list 46, a numbered menu 33).
- **242 B rows** (no pipeline row nearby): 195 priced, 47 unpriced, spread over 28 pages.

Validator-side layouts named in Amendment 14 item 3, searched for on all 148 pages: bare
one-decimal prices on their own line or ending a line ("6.5", "salsa roja 7.5") occur on
two tuning pages (P5-8 1, P5-10 1; the P5-8 one prints ABV figures "( 6.2 % ABV)", a
negative case) and two dev pages; **the price column (prices in their own run of blocks,
separated by blank spacers, matched to names by order) and glued one-decimal prices
("Cold Brew4.5") occur only on dev pages** (Q9: not built this session).

## Where the model runs

The prompt lever changes the model's input, so its pages had to be re-run. Three runtimes,
one model file (`Qwen3-4B-Instruct-2507-Q4_0.gguf`, sha256 `e0ba675d…` checked on each
host against `config/models.yaml`):

| Runtime | Use | Speed | Notes |
|---|---|---|---|
| Orange Pi 5 Plus, the pinned CPU image (`server-b11176` by digest), the Compose service's flags, A76 cores 4–7, `127.0.0.1:8081`, in `~/p5-13` outside the deployed `helios` project (untouched) | prompt-v2.5 on the dev set | ~4.4 pages/h (prefill ~20 tokens/s, generation 2–7 tokens/s per slot; SoC ≤ 68 °C) | Greedy answers differ from the laptop CPU's on the same input (1 of 5 test chunks): Pi answers compare cleanly only to Pi answers. This run is also a first Pi run of the pinned image (the 2026-09-29 Pi check stays open: no timing comparison with the spike binary was made) |
| Laptop CPU (the saved answers) | every validator and repair lever | — (no model calls) | — |
| Laptop GPU (RTX 3070 8 GB), `server-cuda-b11176` (digest `1f4b9cf5…`), same flags except **flash attention off and an f16 KV cache**, 6 slots, `127.0.0.1:8082` | screening prompt versions on all 148 pages | ~3 pages/min (thermally capped at 780 of 2,100 MHz, 89 °C) | **Tuning tool only, not the production path** (nothing under `infra/`). Flash attention crashed this CUDA build twice ("CUDA error: an illegal instruction", with q8_0 and with f16 KV). Not repeatable run to run (1 of 5 chunks differs between identical runs, with 1 or 2 slots), so every prompt is compared with two v6 runs on the GPU: their gap is the noise band |

The GPU's v6 numbers sit close to the laptop CPU's (spike recall 0.903 vs 0.907, P5-10
0.876 vs 0.864, dev 0.821 vs 0.821), so it screens prompts; the kept levers are measured on
the laptop CPU answers, the production-like path.

## Prompt lever (Q2: alone, with v6's validator and repairs)

**prompt-v2.5** (rules only, Q3): name each item by its title line even when a description
sits between title and price; never take a name from a description or ingredient list, a
section heading, a place / region line, a size line or a wine's second line; leave out a
menu number before the name; `b` is the title line's block. **prompt-v2.5b**: the same
without the menu-number rule, "copy the line as printed, without adding words from a
heading or description", and the heading clause narrowed to headings printed without a
price.

Item recall (all 148 pages, GPU; v6 scoring code):

| Set | v6 run A | v6 run B | v2.5 | v2.5b |
|---|---|---|---|---|
| Spike 33 | 0.903 | 0.903 | 0.886 | 0.882 |
| P5-5 10 | 0.877 | 0.855 | 0.894 | 0.884 |
| P5-8 35 | 0.877 | 0.871 | 0.879 | 0.867 |
| P5-10 35 | 0.876 | 0.870 | 0.855 | 0.858 |
| P5-12 dev 35 | 0.821 | 0.815 | 0.825 | 0.827 |

Price accuracy, gold-row FR and catch did not move; usable prices stayed within noise. On
the Pi (CPU), prompt-v2.5 on the dev set: item recall 0.820 (2104/2565), usable 0.700,
against the laptop's v6 answers 0.821 / 0.702.

**Both rejected** (keep rule): spike and P5-10 lose items beyond the noise band, and the
dev gain is inside it. The rules fix the layouts they target (sushi rolls and tacos named
by their description) but the 4B model over-applies them elsewhere: coded names
("H1: Scallop" became "Scallop Handroll": number dropped, section word added), a whole
brunch section skipped, a wine named by its style line ("Prosecco" for "La Marca"),
single-item sections ("Floats $8.50") dropped as headings. The prompt stays v2.4.

## Validator and repair levers (on v6's saved CPU answers, prompt unchanged)

Columns: item recall / usable / price accuracy / gold FR / catch. Each lever is designed on
the 113 tuning pages and scored on the dev set.

| Lever | Component | Spike 33 | P5-5 10 | P5-8 35 | P5-10 35 | P5-12 dev | Kept? |
|---|---|---|---|---|---|---|---|
| Baseline v6 | — | 0.907 / 0.844 / 0.995 / 0.021 / 0.987 | 0.887 / 0.761 / 0.992 / 0.105 / 0.995 | 0.871 / 0.744 / 0.983 / 0.109 / 0.994 | 0.864 / 0.735 / 0.997 / 0.093 / 0.996 | 0.821 / 0.702 / 0.991 / 0.126 / 0.995 | — |
| V1 first form: on a bare-price page a block's last one-decimal amount ("6.5", "salsa roja 7.5") is a price, unless parenthesized or a percent ("( 6.2 % ABV)" over three blocks) | prices (`bare_page`), validator | unchanged | −1 usable ("HAWAII 5.0" read as a price) | unchanged | — | — | **no** |
| V1 second form: … and not when the next line is a sole price | prices | unchanged | −1 usable (the name / description / price layout) | — | — | — | **no** |
| **V1c** … and a ".0" after words is part of a name ("HAWAII 5.0") | prices, validator | unchanged | unchanged | unchanged | 0.864 / **0.739** / 0.997 / **0.086** / 0.996 | 0.821 / 0.707 / 0.991 / 0.118 / 0.994 | yes: +41 gold rows, no new wrong accept; dev catch is a draw shift (per-page uncaught identical, as P5-11's note 1) |
| R1 first form: a row named by its description (two commas, a final period or eight words) that is its block's text takes the short unpriced title line above it | repairs (`name_by_title`) | 0.906 (−2) | unchanged | 0.874 | 0.870 | 0.834 | **no**: section headings and chrome taken as titles ("Desserts", "Set Plates", "Show More") |
| **R1b** … the title outside page chrome and no section name the model gave | repairs | **0.908** / 0.845 / 0.995 / 0.021 / 0.987 | 0.887 / **0.762** / 0.992 / 0.105 / 0.995 | **0.874** / 0.745 / 0.983 / 0.109 / 0.994 | **0.869** / **0.743** / 0.997 / 0.086 / 0.996 | **0.834** / **0.716** / 0.991 / 0.118 / 0.994 | yes, note 1 |
| R2: … also a row named by its price line ("$3.00", "16″ — $17.00") | repairs | −1 | unchanged | −1 | −4 | unchanged | **no**: names that hold a number ("Don Julio 70", "Chicken 65") read as price lines |
| R3: a row named by a heading (an h1–h6, or a section name the model gave) takes the title line below | repairs | −5 | +6 | −10 | −4 | +2 | **no**: dish titles printed in h3 |
| R3b: … a section name the model gave only | repairs | +3 | +4 | −7 | unchanged | +1 | **no**: card pages where the model names each one-dish section after its dish |
| **R4b** a diet mark glued to the end of a name is dropped ("Spiced Chicken Thighgf", "Puffy PotatoV", "Applev, gf"); a lone lowercase "v" stays ("Molotov") | repairs (`strip_diet_marks`) | **0.910** (1677) / **0.847** / 0.995 / 0.021 / 0.987 | unchanged | unchanged | **0.871** (2378) / **0.744** / 0.997 / 0.086 / 0.996 | unchanged | yes: +10 rows matched, no metric worse in any set or format |

**Note 1 (R1b).** 67 renamed rows now match their dish, 9 matched rows lost (a title above
that is another dish, a "Serves 10-12" line, a "FAMILY ORDERS" heading the model didn't use
as a section); no set's bar gets worse. Per-format drops, none crossing a bar: spike
`html_cards` recall 0.891 → 0.888, spike `html_inline` 0.927 → 0.925, P5-8 `price_list`
0.900 → 0.886.

**Not built (Q9):** the price-column layout and glued one-decimal prices ("Cold
Brew4.5"): only dev pages print them. **Not changed:** wine lists printed producer over
cuvée-and-price (labels name a wine by its producer on one page and by its whole line on
another), lines collapsed by image alt text ("WalnutShrimp"), the model's skipped lists.

## Candidate v7 (final)

| Set / format | Pages | Item recall | Usable | Price accuracy | Gold FR | Catch | Real-output FR / catch |
|---|---|---|---|---|---|---|---|
| **Spike 33** | 33 | 0.910 (1677/1843) | 0.847 (1737/2050) | 0.995 (1756/1764) | 0.021 (44/2050) | 0.987 | 0.036 / 0.472 |
| `html_list` | 22 | 0.913 | 0.844 | 0.996 | 0.022 | 0.996 | 0.034 / 0.441 |
| `html_cards` | 6 | 0.888 | 0.822 | 0.997 | 0.014 | 0.979 | 0.037 / 0.644 |
| `html_inline` | 4 | 0.925 | 0.890 | 0.994 | 0.027 | 0.965 | 0.043 / 0.400 |
| `price_list` | 1 | 0.750 | 0.714 | 0.909 | 0.000 | 1.000 | — |
| **P5-5 10** | 10 | 0.887 (729/822) | 0.762 (593/778) | 0.992 (602/607) | 0.105 (82/778) | 0.995 | 0.053 / 0.719 |
| `html_list` | 8 | 0.889 | 0.781 | 0.992 | 0.092 | 0.997 | 0.050 / 0.717 |
| `html_cards` | 2 | 0.800 | 0.378 | 1.000 | 0.378 | 1.000 | 0.176 / 0.750 |
| **P5-8 35** | 35 | 0.874 (2147/2456) | 0.745 (2027/2722) | 0.983 (2130/2166) | 0.109 (298/2722) | 0.994 | 0.115 / 0.644 |
| `html_list` | 26 | 0.892 | 0.780 | 0.981 | 0.057 | 0.997 | 0.094 / 0.549 |
| `html_cards` | 5 | 0.913 | 0.876 | 0.994 | 0.046 | 0.996 | 0.059 / 0.835 |
| `html_inline` | 2 | 0.638 | 0.215 | 0.958 (46/48) | 0.701 | 0.920 | 0.626 / 0.900 |
| `price_list` | 2 | 0.886 | 0.728 | 1.000 | 0.173 | 1.000 | 0.033 / — |
| **P5-10 35** | 35 | 0.871 (2378/2731) | 0.744 (2226/2991) | 0.997 (2378/2385) | 0.086 (258/2991) | 0.996 | 0.085 / 0.724 |
| `html_list` | 28 | 0.867 | 0.742 | 0.997 | 0.090 | 0.998 | 0.075 / 0.679 |
| `html_cards` | 6 | 0.906 | 0.758 | 1.000 (191/191) | 0.053 | 0.979 | 0.191 / 0.912 |
| `price_list` | 1 | 0.857 | 0.829 | 1.000 | 0.000 | 1.000 | 0.000 / — |
| **P5-12 dev 35** | 35 | 0.834 (2139/2565) | 0.716 (1915/2674) | 0.991 (1976/1993) | 0.118 (316/2674) | 0.994 | 0.080 / 0.467 |
| `html_list` | 29 | 0.830 | 0.713 | 0.992 | 0.121 | 0.998 | 0.069 / 0.468 |
| `html_cards` | 4 | 0.856 | 0.638 | 0.981 | 0.135 | 0.981 | 0.273 / 0.457 |
| `price_list` | 2 | 0.885 | 0.885 | 0.989 | 0.019 | 1.000 | 0.000 / 0.462 |

**Against the bars (tuning pages):** all four tuning sets pass all four bars, as with v6.
No tuning set got worse on any bar; per-format drops are listed in note 1; no format
crossed a bar. The formats under a bar at baseline stay there unchanged (P5-8
`html_inline`, spike `price_list`, spike `html_inline` catch).

**Dev check (P5-12, never tuned on):** item recall 0.821 → **0.834**, gold-row FR 0.126 →
**0.118**; price accuracy 0.991 and catch 0.994 pass. Recall stays **under the 0.85 bar**;
FR now passes (0.118 ≤ 0.12, a margin of 4 rows). The dev set is a weaker holdout than a
fresh draw (its misses were diagnosed before tuning), so v7 is expected to fall short on
recall at §8 unless the next draw's pages are easier.

**Loss buckets, P5-12 dev** (2,674 gold prices): `accepted` 1,881 → 1,918; `item_missed`
493 → 447; `wrong_amount` 130 → 141; `not_accepted:price_not_grounded` 97 → 96;
`row_unpriced` 57 → 56; the rest unchanged. P5-10: `accepted` 2,322 → 2,350, `item_missed`
388 → 370, `price_not_grounded` 125 → 114, `wrong_amount` 89 → 91.

**Gold-row false rejects by reason:** P5-10 `price_not_grounded` 187 → 167; P5-12 dev 261
→ 239; the other sets unchanged.

**Corruption per type** (caught / n, baseline → candidate): spike, P5-5 and P5-8
unchanged; P5-10 `swapped_prices` 570/576 → 578/584; P5-12 dev `other_section_price`
289/290 → 288/290, `swapped_prices` 588/594 → 584/590. The counts move because accepting
more gold rows changes the trials drawn; per-page streams show no trial newly let through
(the repairs change no gold row).

## RUN-A-01 (Q7a): the Menu-write commit, re-timed

The owner-run checklist in
[2026-10-03-menu-write-commit-cost.md](./2026-10-03-menu-write-commit-cost.md#owner-run-checklist-run-a-01-after-the-migration-merges),
run by the session on the laptop (2026-10-14, 01:58 UTC):

1. Code at `f146dbd2bb4c4d4bc5e12e81b14d3cc304370f0c` (#74's merge: the migration, and
   still `prompt-v2.3;chunk-v2.1`, the extractor the page's saved answers were written
   with).
2. `helios_a1_retime` cloned from `helios_laptop` (`CREATE DATABASE … TEMPLATE`; 72 MB).
3. Clone only: `alembic upgrade head` ran `7c2e4b9d1f3a -> db40e9424cba`; `alembic
   current` = `db40e9424cba (head)`. `helios_laptop` stays at `7c2e4b9d1f3a` (Q7b) with 0
   Menu rows, checked after the run.
4. The extract CLI on the one Version (P5-5's largest page, `4b9d6bb201da`, Version 20561;
   the queue narrowed to it as P5-12's `extract_sample.py` does), its raw answers replayed
   from `var/replay/menu-extract/` (`reused_outputs` 1, 0 chunks sent).
5. `extraction run complete`: 1 extracted, 1 `jsonld` page, 401 `llm` accepts and 409
   `jsonld` accepts among 1,018 rows judged, **993 items and 810 prices written, `wall_s`
   24.5** (01:58:20 to 01:58:44 UTC). The clone held 2 Menu pages, 76 sections, 993
   items, 23 variants, 810 price observations and 2,714 Evidence links. The same page took
   **at least 1 h 25 min** before the migration (P5-5).
6. `helios_a1_retime` dropped.

## Next held-out evaluation (needed before any extraction run)

The P5-8 / P5-10 / P5-12 procedure: **seed 20261013**, drawing from the laptop pass with
P5-5's spike exclusions plus **all 234 venues labelled so far** (P5-5 18, P5-8 72, P5-10
72, P5-12 72) **and their 234 sites** (`var/menu-eval/p5-12/next-draw-exclusions-p5-13.json`
in P5-12's worktree, copied here as `var/tune/next-draw-exclusions.json`, sha256
`0c383cac72ea15f72f204077e353d4c05e8de0d8e50bd8e0ca845144b7e435c1`, checked); size strata
with the fixed cutoffs; blind labellers, frozen and hashed before the first model call; the
real extract CLI against the pinned CPU `llama-server` (the GPU path above is not it);
scored with this harness as frozen. For that session: the adjudication packet's C rows
should list what is labelled within 2 blocks, not only at the claimed block (P5-12's 24
false "missing item" answers). The label-free scale run stays deferred to the Pi.

**If v7 fails on recall again,** the remaining gap is the model's naming and skipped
lists, which neither prompt rules (this record) nor further repairs reach safely. Per the
owner (Q5), a larger model is not feasible on the Pi; a screen of other models of this
size would change the model and needs its own ADR-0013 amendment first (Amendment 9
item 3). The laptop GPU path makes such a screen cheap (~45 min per model over 148 pages).
