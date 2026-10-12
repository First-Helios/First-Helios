# Held-out evaluation of menu-pipeline v5 (ADR-0013 §8)

Session P5-10, 2026-10-10 to 2026-10-12: the §8 evaluation that
[Amendment 11](../adr/0013-phase5-menu-pipeline.md#amendment-11-2026-10-09-pipeline-version-v5-tuned-on-the-p5-8-pages)
item 6 requires before v5 runs extraction, with the P5-8 procedure (Amendment 10 item 2)
on a fresh draw from the laptop pass. Version (merged in #77 @ `0c160ae`):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.2;segment-v2;repairs-v5;validator-v5;classifier-v2
```

**Result: v5 fails §8.** Item recall (0.819) and the false-reject rate on gold rows
(0.168) miss their bars, and both Wilson intervals lie wholly on the wrong side; price
accuracy (0.997) and corruption catch (0.994) pass. Per §8 and the owner's answer E4, v5
is not cleared for extraction runs, these 35 pages become tuning pages, and the next
version needs another fresh draw.

Measured only: no pipeline, harness, schema, model, dependency or `infra/` change, no Pi
access. Page bodies, labels, outputs and worksheets stay in gitignored
`var/menu-eval/p5-10/`; this file keeps counts and rates. Pages are named by an opaque id
(`sha256(record key)[:12]`).

## Owner decisions

The P5-8 answers stand (session brief: "with the P5-8 procedure"):

| | Question | Answer |
|---|---|---|
| E1 | Sample size | **35 scorable pages** |
| E2 | Stratification | **Quotas by page size** (bundle block count, read before any content): small 14, medium 14, large 7; pass/fail on the pooled set. The cutoffs are **P5-8's, fixed** (small < 176, large ≥ 500) so strata compare across evaluations; this draw's own P50 / P90 (173 / 476) are recorded only |
| E3 | Labelling | **Parallel fresh labeller agents** (one batch each, same brief), spot-check of 5 pages before freezing |
| E4 | Pass / fail | **Point estimates** on the pooled pages; Wilson intervals recorded, not gated. A fail makes the pages tuning pages |
| E5 | Scale run | **Deferred to the Pi** (Amendment 10 item 5); not run here |
| — | Extraction run | **The session runs it** (owner, 2026-10-10): the extract CLI unchanged, on a disposable clone, against the pinned `llama-server`; the idle P5-9 server was stopped to free the port and memory |

Label conventions the owner ruled on before the freeze (labellers disagreed on them;
every batch was brought in line by fresh agents, and the brief records them):

- **R1, re-listings.** A section that re-lists dishes already printed elsewhere on the
  same menu ("Popular Items", a "Vegetarian" or "Gluten-Free" section, tab or filter
  category, "Related Products", a dish under two categories) is a copy: a dish with the
  same name and the same price counts **once, at its first printing**. A re-listed dish
  with a different price is its own item; genuinely separate menus (lunch, dinner,
  brunch, happy hour, catering) still count per placement.
- **R2, repeated option lists.** Own-line priced add-ons stay items (P5-8), but an
  identical option list printed again under several dishes (a per-dish "Options" / "Add
  Ons" / "choose from the following for $X" list) counts **once, at its first printing**;
  a list that differs is labelled where it is printed.

The session applied R1 as written to a re-listing, not to a different product sharing a
name: 7 rows the re-check had removed on 3 pages were restored (a kids' meal, a side
tier, a custom bowl, a dish with other ingredients).

After scoring: **no blinded adjudication.** Both failing bars miss by more than a label
change could move them (finding 7), so blind labels with the rulings applied = confirmed.

## Procedure

**Draw** (`var/menu-eval/p5-10/draw.py`, P5-8's script with P5-9's exclusion list; seed
**20261010**, recorded before drawing):

- Pool: the extract CLI's due queue on `helios_laptop` (read-only): 1,632 pages.
- Excluded (pages): P5-5's exclusions (spike venues **77**, spike hosts **234**, spike
  URLs **0**) plus the 90 venues labelled in P5-5 and P5-8 (**90**) and their 90 sites
  (**202**); the list is P5-9's `next-draw-exclusions.json` (sha256
  `2579afbeecdbb2b0c6b6a1daf35868b29e63aa11b0b1f0e5d2af93787b93b030`, checked by the
  script).
- 1,028 eligible venues, shuffled with the seed; one page per venue, at most one venue
  per site: an order of **721**. `draw.jsonl` sha256
  `92590a797f7ffc7e8ea9caf16cda797ed88513ca8d627cf8cbbb7a8bd6f3eab9`.
- Strata by the bundle's block count over the ordered pages, P5-8's cutoffs: small < 176
  **362**, medium 176–499 **290**, large ≥ 500 **69**.
- Exported in draw order per stratum (first small 34, medium 26, large 12: 72 pages,
  19,844 blocks); every body re-segments byte-for-byte to the bundle's blocks.

**Blind labels.** Five fresh labeller agents (about 3,970 blocks each) labelled from the
segmented blocks (raw HTML for layout only) with P5-8's brief, before any model call.
The owner's rulings R1/R2 were then applied by five fresh re-check agents that changed
only affected rows (13 pages; all 72: 5,111 → 4,931 items, 4,231 → 4,057 prices), and
the session restored 7 rows (above). Spot-check (by the session, as in P5-8): 5 pages
across strata and formats, including R1/R2-edited ones; every labelled price checked to
be printed beside its item with its variant, every printed price either labelled or a
non-item row (a cart widget, a promo line); all 5 pass.

Of the 72 labelled pages: **45 scorable** menus, **22** menus that print no prices,
**5** not menus (classifier-v2 precision on the draw **67/72**). Held out: the first
scorable pages per stratum in draw order (small 14, medium 14, large 7), positions 2–79.
Frozen and hashed at **2026-10-11 16:48:44 UTC**; extraction started 16:48:52 UTC.

| Label set | Manifest sha256 |
|---|---|
| Blind with R1/R2 (72 pages; = confirmed) | `187d88c0608a96098ef0fedff69d98a57d6e6de6548bab941ff73d026940b9d2` |

**Extraction.** The real extract CLI on a disposable `TEMPLATE` clone of `helios_laptop`
(`helios_p510_eval`), narrowed to the 35 held-out Versions by P5-8's queue wrapper,
against `llama-server` `server-b11176` pinned by digest (`llama-model-check` passed;
`/props`: the manifest GGUF, 2 slots), Compose project `helios-p510`. Claude Code's
memory-pressure reaper stopped the run after the 33rd page's answer was saved (the
laptop had about 1 GB free; the run itself was healthy); the owner had it resumed, and
the same CLI took the 2 remaining pages (the other 33 were up to date). Scored with
`python -m apps.menu_pipeline.evaluate compare|loss|corrupt` and the harness's own
functions, as frozen in Amendment 9 (no harness edits).

## Results (§8)

| Stage | Metric | Bar | v5, 35 pages [Wilson 95 %] | |
|---|---|---|---|---|
| [4]+repairs+[5] | Exact price accuracy, accepted rows | ≥ 0.98 | **0.997** (2128/2135) [0.993, 0.998] | ✔ |
| [4] | Item recall | ≥ 0.85 | **0.819** (2238/2731) [0.805, 0.833] | ✗ |
| [5] | Injected-corruption catch (gold rows, seed 7) | ≥ 0.97 | **0.994** (1489/1498) | ✔ |
| [5] | False reject, correct (gold) rows | ≤ 0.12 | **0.168** (501/2991) [0.155, 0.181] | ✗ |
| [1] | Classifier precision on the draw | (S6f evaluation stands) | 67/72 menus | — |
| End to end | Usable prices | recorded | 0.663 (1984/2991) [0.646, 0.680] | — |
| [5] on real output | False reject / catch | recorded | 0.133 (327/2455) / 0.693 (341/492) | — |

v4 on P5-8's 35 pages for comparison: 0.983 / 0.838 / 0.995 / 0.278, usable 0.647. v5's
tuning numbers on those pages: 0.983 / 0.871 / 0.994 / 0.116.

**Per stratum** (price accuracy / item recall / gold-row FR / usable):

| Stratum | Pages | Gold items / prices | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|---|
| small | 14 | 311 / 324 | 0.982 | 0.756 | 0.185 | 0.648 |
| medium | 14 | 1,251 / 1,308 | 0.999 | 0.835 | 0.281 | 0.634 |
| large | 7 | 1,169 / 1,359 | 0.998 | 0.820 | 0.054 | 0.695 |

**Per format:**

| Format | Pages | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|
| `html_list` | 28 | 0.997 | 0.847 | 0.177 | 0.688 |
| `html_cards` | 6 | 1.000 (98/98) | 0.572 | 0.053 | 0.393 |
| `price_list` | 1 | 1.000 (21/21) | 0.857 | 0.229 | 0.600 |

No `html_inline` page was drawn.

**Corruption per type** (seed 7):

| Type | n | Caught | Indistinguishable |
|---|---|---|---|
| `invented_item` | 330 | 330 | 0 |
| `mutated_price` | 299 | 298 | 0 |
| `other_section_price` | 293 | 293 | 0 |
| `swapped_prices` | 576 | 568 | 4 |

**False rejects of gold rows by reason** (501 rows; a row can carry several reasons):
`price_not_grounded` 335, `variant_not_grounded` 88, `name_not_grounded` 38,
`price_bound_to_other_item` 30, `price_belongs_to_other_variant` 6, `addon_price` 4.

**Loss buckets** (every gold price in one bucket, 2,991):

| Bucket | Prices | Share |
|---|---|---|
| `accepted` | 2,108 | 0.705 |
| `item_missed` | 512 | 0.171 |
| `not_accepted:price_not_grounded` | 186 | 0.062 |
| `wrong_amount` | 89 | 0.030 |
| `row_unpriced` | 49 | 0.016 |
| `not_accepted:name_not_grounded` | 34 | 0.011 |
| `not_accepted:price_bound_to_other_item` | 8 | 0.003 |
| `not_accepted:variant_not_grounded` | 3 | 0.001 |
| `not_accepted:price_belongs_to_other_variant` | 1 | 0.000 |
| `not_accepted:addon_price` | 1 | 0.000 |

**Per page** (draw position, stratum, format, gold items / prices, items found, accepted
prices exact, gold rows rejected):

| Page | Pos. | Stratum | Format | Items | Prices | Found | Exact | Gold FR |
|---|---|---|---|---|---|---|---|---|
| 3a1d6a1f9437 | 2 | medium | html_list | 55 | 3 | 52 | 0/0 | 0/3 |
| d9126c519b73 | 3 | medium | html_list | 69 | 93 | 57 | 70/70 | 36/93 |
| 02f54e001405 | 5 | medium | html_list | 85 | 113 | 76 | 72/72 | 42/113 |
| 3a630628e2bf | 9 | medium | html_list | 71 | 74 | 56 | 55/55 | 10/74 |
| 10efc28c8411 | 10 | large | html_cards | 92 | 96 | 0 | 0/0 | 0/96 |
| 3a2e1e53ade0 | 12 | small | html_list | 34 | 30 | 21 | 3/6 | 27/30 |
| 53b6d87ed985 | 14 | medium | html_list | 64 | 64 | 60 | 18/18 | 45/64 |
| 3e035f21ac55 | 15 | small | html_list | 30 | 30 | 10 | 3/3 | 17/30 |
| c287b352073c | 16 | small | price_list | 35 | 35 | 30 | 21/21 | 8/35 |
| 4f3b96ce9823 | 17 | medium | html_list | 100 | 79 | 94 | 58/58 | 0/79 |
| 90e5d887db0d | 19 | medium | html_cards | 60 | 67 | 51 | 51/51 | 6/67 |
| 2a5c2532e610 | 20 | medium | html_list | 274 | 290 | 191 | 163/164 | 144/290 |
| 2a1dd2be611f | 22 | large | html_list | 211 | 401 | 191 | 347/347 | 0/401 |
| 2aa22b5d5dc5 | 23 | medium | html_cards | 47 | 52 | 44 | 27/27 | 6/52 |
| 018fe254a06d | 25 | medium | html_list | 100 | 124 | 85 | 92/92 | 6/124 |
| 32d06a43c4c8 | 27 | medium | html_list | 70 | 81 | 65 | 50/50 | 7/81 |
| b77c9d2e7c89 | 28 | large | html_list | 195 | 201 | 186 | 163/163 | 25/201 |
| eb600e755fcd | 29 | small | html_list | 32 | 32 | 32 | 29/29 | 0/32 |
| e5a79b3760fd | 30 | medium | html_list | 82 | 84 | 58 | 21/21 | 48/84 |
| 99b3fcdf58f4 | 31 | small | html_list | 18 | 18 | 5 | 5/5 | 3/18 |
| 4414de65ba3f | 32 | small | html_list | 13 | 19 | 12 | 19/19 | 0/19 |
| 8d6e20477ec6 | 33 | medium | html_list | 62 | 72 | 49 | 51/51 | 17/72 |
| 5799e2ad3411 | 34 | medium | html_list | 112 | 112 | 107 | 107/107 | 0/112 |
| fe3b808baa39 | 36 | large | html_list | 199 | 225 | 147 | 158/159 | 28/225 |
| 2a73ae62e8b1 | 40 | small | html_list | 27 | 35 | 25 | 29/29 | 2/35 |
| a63c26dfb471 | 42 | small | html_list | 3 | 3 | 0 | 0/0 | 3/3 |
| 027d4ba84c46 | 44 | small | html_list | 57 | 60 | 48 | 51/52 | 0/60 |
| 5fab93c1d42c | 46 | small | html_cards | 10 | 10 | 3 | 3/3 | 0/10 |
| ea20edd6efeb | 48 | small | html_list | 1 | 1 | 1 | 1/1 | 0/1 |
| 4b6ab8a2bf24 | 51 | large | html_cards | 51 | 1 | 45 | 0/0 | 1/1 |
| 1c0ce12a7681 | 52 | small | html_list | 31 | 31 | 30 | 32/32 | 0/31 |
| 2dc7746c4fee | 53 | large | html_list | 219 | 219 | 202 | 205/206 | 0/219 |
| a95c964df0d3 | 58 | small | html_list | 2 | 2 | 2 | 2/2 | 0/2 |
| fa464d0f6071 | 61 | small | html_cards | 18 | 18 | 16 | 17/17 | 0/18 |
| 6aa82abb0924 | 79 | large | html_list | 202 | 216 | 187 | 205/205 | 20/216 |

**Promo (recorded, not gated):** 13 promo entries and 57 promo-marked items on the
held-out pages; 51 promo-marked priced rows stored as prices.

**Run report** (35 pages, laptop). The CLI's own report covers only the resumed 2 pages
(the reaper stopped the first run before it printed); the rest is rebuilt from the saved
answers and the clone. 311 chunks, all finished on their own (**0 truncated**); resumed
pages: 0 sparse retries, 0 resent, 0 failed. Written to the clone: 3,503 Menu items and
2,684 price observations on 39 Menu pages (4 pages also have a `jsonld` stream), 189
variants, 473 sections.

**Laptop numbers, not Pi numbers.** Wall clock about 38,070 s (10.6 h: 16:48:52 to the
33rd saved answer at 03:00:00 UTC, plus 1,402 s for the resume), **3.3 pages/h**
including Menu writes; **8.1 pages/h** model time only (30,988 chunk-seconds on 2 slots;
3.1 generated tokens/s per slot, P5-8: 2.8). SoC max **94 °C** (sampled; resume report),
CPU frequency cap 1.0.

## Findings

1. **Recall falls on layouts the tuning sets barely had.** Item recall is 0.819 against
   0.871 on the P5-8 tuning pages. The misses concentrate on a few pages (finding 2–4);
   on `html_list` pages recall is 0.847, on `html_cards` 0.572.
2. **One card layout the model can't read.** A large cards page prints each card as
   image alt text, name, "$18", "Ingredients▾", description: the model names every item
   by its description and drops the price (0 of 92 items, 96 prices). Without it item
   recall is 0.848 (2238/2639): still under the bar.
3. **Line-wrapped layouts.** Pages that print each line as its own block, with a dish name
   split over two blocks ("SPICY CHICKEN" / "BACON RANCH"), the description wrapped one
   line per block, and the price at the end of the last line, lose both ways: the model
   takes a name line for a section and a description line for the name (one small page
   finds 10 of 30 items), and the validator doesn't ground a price several blocks below
   the name (one medium page: 48 of 84 gold rows `price_not_grounded`). The model also
   emitted a non-Latin token inside a description on one such page ("red洋葱").
4. **Group prices printed once for a list.** "3.75 EACH:" printed over a row of
   "|"-joined names, and a section-level "Small $1.99 | Medium $2.29 | Large 2.69" line
   over a drink list: the gold rows carry the shared price (the brief's group-price
   convention), and the validator grounds almost none of them (2 pages: 144 of 290 and 27
   of 30 gold rows rejected, mostly `price_not_grounded`).
5. **An integer glued to the name.** "New England Style Cod Cakes16": v5's price reader
   (Amendment 11 item 1) reads a glued word only before a marked price ("From4.5 USD"),
   so the block has neither the name's last token nor a price token (one page: 34 `name_not_grounded`, 10
   `price_not_grounded` of 64 gold rows).
6. **The false-reject fail sits on three pages.** Without the two group-price pages and
   the glued-integer page, gold-row FR is 0.109 (285/2607); without only the two
   group-price pages it is 0.124 (330/2671). Large pages reject 0.054 of gold rows,
   medium 0.281.
7. **No label change could pass v5.** Recall needs 84 more found items (2,322), or 99
   fewer gold items, and gold-row FR needs 143 fewer rejected rows; the rejected rows
   sampled on the four worst pages are printed as labelled, and both Wilson intervals
   exclude their bars. Blinded adjudication was skipped (Amendment 10 item 2).
8. **Price accuracy and catch hold.** Accuracy 0.997 on 2,135 accepted rows (P5-8 v4:
   0.983) and catch 0.994: what the validator accepts is right; the loss is in what it
   rejects and what the model misses.
9. **Many menu pages print no prices**: 22 of 67 drawn menu pages (33 %), as in P5-5
   (8 of 18) and P5-8 (20 of 66).
10. **Throughput.** 0 truncated chunks (P5-8 v4: 4) with prompt-v2.4's character-aware
    cap; 3.1 generated tokens/s per slot under thermal load. The laptop was short of
    memory (about 1 GB free) with a browser open beside the run.

## What this unblocks

Nothing yet. **Extraction runs (laptop or Pi) stay blocked** on a pipeline version that
passes §8 on a fresh held-out draw: these 35 pages are now tuning pages, next to P5-5's 10
and P5-8's 35 (P5-10's 37 labelled but unscored pages stay unseen, as P5-8's did). The
next tuning session should target, by gold rows at stake: group prices printed once for
a list (finding 4), line-wrapped layouts (finding 3), the card layout the model misreads
(finding 2), and integers glued to a name (finding 5); every fix layout-generic, kept only
if no tuning set gets worse on a bar.

**Next draw:** seed **20261012**, the P5-5 spike exclusions plus **all 162 venues labelled
so far** (P5-5 18, P5-8 72, P5-10 72) **and their 162 sites**
(`var/menu-eval/p5-10/next-draw-exclusions-p5-11.json`, sha256
`224e42243b0f4ace4c9171dd7256a5d62ddc82464f2443b6ffafc369e706002a`). The pool shrinks:
this draw had 1,028 eligible venues and 721 ordered pages; the next one has at most 956
eligible venues.

**Scale run: still deferred to the Pi** (Amendment 10 item 5), on the version that
passes §8.
