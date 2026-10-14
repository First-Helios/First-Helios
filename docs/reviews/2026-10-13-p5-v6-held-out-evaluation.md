# Held-out evaluation of menu-pipeline v6 (ADR-0013 §8)

Session P5-12, 2026-10-12 to 2026-10-13: the §8 evaluation that
[Amendment 13](../adr/0013-phase5-menu-pipeline.md#amendment-13-2026-10-12-pipeline-version-v6-tuned-on-the-p5-10-pages)
item 5 requires before v6 runs extraction, with the P5-10 procedure (Amendments 10 and 12)
on a fresh draw from the laptop pass. Version (merged in #79 @ `bb72fe6`; main's CI green
after it, run 38325032226):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v6;validator-v6;classifier-v2
```

**Result: v6 fails §8.** Item recall (0.821) and the false-reject rate on gold rows
(0.126) miss their bars; price accuracy (0.991) and corruption catch (0.995) pass. Recall's
Wilson interval lies wholly under its bar; false reject's straddles it. A blinded
adjudication was run because label changes could plausibly have moved the verdict
(finding 3): it upheld the blind label on every row where the two readings differed, and
the owner confirmed its only 2 label changes (two crust upcharges removed); the scores
below use those confirmed labels. Per §8 and the
owner's answer E4, v6 is not cleared for extraction runs, these 35 pages become tuning
pages, and the next version needs another fresh draw.

Measured only: no pipeline, harness, schema, model, dependency or `infra/` change, no Pi
access. Page bodies, labels, outputs, verdicts and worksheets stay in gitignored
`var/menu-eval/p5-12/`; this file keeps counts and rates. Pages are named by an opaque id
(`sha256(record key)[:12]`).

## Owner decisions

The P5-10 answers stand (session brief: "with the P5-10 procedure"; the session assumed them, and the owner did not change them):

| | Question | Answer |
|---|---|---|
| E1 | Sample size | **35 scorable pages** |
| E2 | Stratification | **Quotas by page size** (bundle block count, read before any content): small 14, medium 14, large 7; pass/fail on the pooled set. Cutoffs **fixed** (Amendment 12 item 2: small < 176, large ≥ 500); this draw's own P50 / P90 (172 / 453) are recorded only |
| E3 | Labelling | **Parallel fresh labeller agents** (one batch each, same brief, R1/R2 in the brief from the start), spot-check of 5 pages before freezing |
| E4 | Pass / fail | **Point estimates** on the pooled pages; Wilson intervals recorded, not gated. A fail makes the pages tuning pages |
| E5 | Scale run | **Deferred to the Pi** (Amendment 10 item 5); not run here |
| — | Extraction run | **The session runs it**, as in P5-10: the extract CLI unchanged, on a disposable clone, against the pinned `llama-server` |
| — | Blinded adjudication | **Only if label changes could change the verdict** (Amendment 10 item 2). They could here (finding 3), so it was run; the owner confirmed its label changes (2026-10-13: "confirm all") |

## Procedure

**Draw** (`var/menu-eval/p5-12/draw.py`, P5-10's script with P5-10's exclusion list; seed
**20261012**, recorded at 2026-10-13 00:01:32 UTC, before drawing):

- Pool: the extract CLI's due queue on `helios_laptop` (read-only): 1,632 pages.
- Excluded (pages): P5-5's exclusions (spike venues **77**, spike hosts **234**, spike
  URLs **0**) plus the 162 venues labelled in P5-5, P5-8 and P5-10 (**162**) and their 162
  sites (**276**); the list is P5-10's `next-draw-exclusions-p5-11.json` (= P5-11's
  `var/tune/next-draw-exclusions.json`, sha256
  `224e42243b0f4ace4c9171dd7256a5d62ddc82464f2443b6ffafc369e706002a`, checked by the
  script).
- 882 eligible venues, shuffled with the seed; one page per venue, at most one venue per
  site: an order of **649**. `draw.jsonl` sha256
  `e80981d4ff5f3e401247f2ecee2cb3f94b6ff139f887f699aa59362671312e23`.
- Strata by the bundle's block count over the ordered pages, fixed cutoffs: small < 176
  **328**, medium 176–499 **264**, large ≥ 500 **57**.
- Exported in draw order per stratum (first small 34, medium 26, large 12: 72 pages,
  21,599 blocks); every body re-segments byte-for-byte to the bundle's blocks.

**Blind labels.** Five fresh labeller agents (about 4,320 blocks each) labelled from the
segmented blocks (raw HTML for layout only) with P5-10's brief, which already carries the
owner's rulings R1 and R2, before any model call; no re-check round was needed. Every
label parses with the harness's `gold_page` and names existing blocks. Spot-check (by the
session, as in P5-8 and P5-10): 5 pages across strata and formats, chosen for risk (the
2,944-block card page whose nutrition panels a labeller skimmed, a Wix option-panel page
with R1/R2 copies, a 57-item page printing one price, a group-price page, a price list);
every labelled price checked to be printed beside its item with its variant, every printed
price either labelled or a non-item row (detail-panel copies, an intro sentence repeating a
menu line); all 5 pass.

Of the 72 labelled pages (4,912 items, 4,523 prices): **46 scorable** menus, **16** menus
that print no prices, **10** not menus (8 `not_menu`, 2 `empty`; classifier-v2 precision on
the draw **62/72**, 0.861 [0.763, 0.923]). Held out: the first scorable pages per stratum
in draw order (small 14, medium 14, large 7), positions 1–61. Frozen and hashed at
**2026-10-13 00:13:28 UTC**; extraction started 00:14:02 UTC.

| Label set | Manifest sha256 |
|---|---|
| Blind (72 pages) | `58020fa1fc064289f3c4e7791f0d0028e671d49d9e4c41d8aee0db04a73eab51` |
| Confirmed (blind minus the 2 upcharge rows, owner-confirmed) | `03e6a9926174c03f13a25893186ed9b0786a814e8150deb48e69e5f97bb69383` |

**Extraction.** The real extract CLI on a disposable `TEMPLATE` clone of `helios_laptop`
(`helios_p512_eval`, dropped afterwards), narrowed to the 35 held-out Versions by P5-8's
queue wrapper, against `llama-server` `server-b11176` pinned by digest
(`llama-model-check` exited 0 before each start), reusing P5-10's built Compose project
`helios-p510` (`--no-build`). Claude Code's memory-pressure reaper stopped the run after
the 24th page's answer was saved (the laptop had about 2 GB available, a browser tab
holding 11.6 GB); the owner closed the browser and had it resumed, and the same CLI took
the 11 remaining pages (the other 24 were up to date). Scored with
`python -m apps.menu_pipeline.evaluate compare|loss|corrupt` and the harness's own
functions, as frozen in Amendment 9 (no harness edits).

**Blinded adjudication** (Amendment 8 item 3; run per Amendment 10 item 2, finding 3).
P5-5's packet (A: an accepted row whose price isn't the label's; B: a labelled item the
pipeline never produced; C: an accepted row matching no labelled item) plus a fourth class,
D: a labelled item the pipeline never matched that has an unmatched pipeline row claimed
within 2 blocks with one of its prices, shown as two readings of one dish so naming and
placement choices are judged blind. Readings in random order (seed 20261013); five fresh
adjudicator agents read only the brief, their packet and the page text; the key stayed
outside their folder. 697 rows: A 17, B 242, C 220, D 218.

| Class | Rows | Verdicts mapped back |
|---|---|---|
| A (price) | 17 | label 17 |
| D (two readings of one dish) | 218 | label 218 |
| B (labelled, never produced) | 242 | item 240, not an item 2 (a "+$5" crust upcharge printed inside a pizza's text, twice) |
| C (accepted, unmatched) | 220 | not an item 112, same dish as a recorded one 84, "a real item" 24 |

**2 label changes:** remove the 2 upcharge rows; the owner confirmed them. The 24 C rows
answered "a real item" are not additions: each dish is already labelled at its name block
one or two blocks above (12 numbered curries and drinks, 10 vermouths, beers and dessert
wines on a wine list, one pizza's two sizes). The C packet showed the adjudicator only
what was recorded at the pipeline's claimed block (the price block), so "yes" there meant
"a real priced item", not "missing from the labels"; these are the model naming a dish
from its price block, as in the D rows. A later packet should list what is recorded
within 2 blocks.

## Results (§8)

| Stage | Metric | Bar | v6, 35 pages [Wilson 95 %] | |
|---|---|---|---|---|
| [4]+repairs+[5] | Exact price accuracy, accepted rows | ≥ 0.98 | **0.991** (1939/1956) [0.986, 0.995] | ✔ |
| [4] | Item recall | ≥ 0.85 | **0.821** (2107/2565) [0.806, 0.836] | ✗ |
| [5] | Injected-corruption catch (gold rows, seed 7) | ≥ 0.97 | **0.995** (1506/1514) [0.990, 0.997] | ✔ |
| [5] | False reject, correct (gold) rows | ≤ 0.12 | **0.126** (337/2674) [0.114, 0.139] | ✗ |
| [1] | Classifier precision on the draw | (S6f evaluation stands) | 62/72 menus | — |
| End to end | Usable prices | recorded | 0.702 (1878/2674) [0.685, 0.719] | — |
| [5] on real output | False reject / catch | recorded | 0.080 (169/2108) / 0.466 (354/760) | — |

Scores use the confirmed labels. Blind labels: 0.991 / 0.821 (2107/2567) / 0.994
(1503/1512) / 0.126 (337/2676), usable 0.702: **the same verdict.**

v5 on P5-10's 35 pages for comparison: 0.997 / 0.819 / 0.994 / 0.168, usable 0.663. v6's
tuning numbers on those pages: 0.997 / 0.864 / 0.996 / 0.093.

**Per stratum** (price accuracy / item recall / gold-row FR / usable):

| Stratum | Pages | Gold items / prices | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|---|
| small | 14 | 471 / 494 | 0.992 | 0.860 | 0.115 | 0.767 |
| medium | 14 | 997 / 1,037 | 0.987 | 0.787 | 0.124 | 0.689 |
| large | 7 | 1,097 / 1,143 | 0.995 | 0.836 | 0.132 | 0.687 |

**Per format:**

| Format | Pages | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|
| `html_list` | 29 | 0.992 | 0.816 | 0.130 | 0.698 |
| `html_cards` | 4 | 0.980 (100/102) | 0.850 | 0.135 | 0.631 |
| `price_list` | 2 | 0.989 (93/94) | 0.894 | 0.019 | 0.894 |

No `html_inline` page was drawn.

**Corruption per type** (seed 7):

| Type | n | Caught | Indistinguishable |
|---|---|---|---|
| `invented_item` | 320 | 320 | 0 |
| `mutated_price` | 310 | 309 | 1 |
| `other_section_price` | 290 | 289 | 0 |
| `swapped_prices` | 594 | 588 | 3 |

**False rejects of gold rows by reason** (337 rows; a row can carry several reasons):
`price_not_grounded` 261, `variant_not_grounded` 57, `name_not_grounded` 10,
`price_bound_to_other_item` 9.

**Loss buckets** (every gold price in one bucket, 2,674):

| Bucket | Prices | Share |
|---|---|---|
| `accepted` | 1,881 | 0.703 |
| `item_missed` | 493 | 0.184 |
| `wrong_amount` | 130 | 0.049 |
| `not_accepted:price_not_grounded` | 97 | 0.036 |
| `row_unpriced` | 57 | 0.021 |
| `not_accepted:name_not_grounded` | 9 | 0.003 |
| `not_accepted:price_bound_to_other_item` | 4 | 0.001 |
| `not_accepted:price_belongs_to_other_variant` | 2 | 0.001 |
| `not_accepted:duplicate_row` | 1 | 0.000 |

**Per page** (draw position, stratum, format, gold items / prices, items found, accepted
prices exact, gold rows rejected):

| Page | Pos. | Stratum | Format | Items | Prices | Found | Exact | Gold FR |
|---|---|---|---|---|---|---|---|---|
| 29feb8b32eac | 1 | small | `price_list` | 84 | 84 | 80 | 80/81 | 0/84 |
| f36c29216b02 | 3 | medium | `html_list` | 57 | 1 | 39 | 0/0 | 1/1 |
| 585de0852da3 | 4 | medium | `html_list` | 60 | 60 | 57 | 56/56 | 0/60 |
| 685181b74025 | 5 | medium | `html_list` | 62 | 62 | 57 | 59/59 | 0/62 |
| a282f08c5f3e | 8 | large | `html_list` | 190 | 190 | 155 | 145/145 | 0/190 |
| 6dc4aca75616 | 9 | small | `html_list` | 46 | 43 | 33 | 37/37 | 5/43 |
| 692d01850f97 | 10 | small | `html_list` | 65 | 76 | 64 | 41/41 | 32/76 |
| 7d068fec88e3 | 11 | small | `price_list` | 20 | 20 | 13 | 13/13 | 2/20 |
| 86a32e6109e4 | 12 | medium | `html_list` | 62 | 82 | 49 | 59/59 | 6/82 |
| 4f64792f5b53 | 13 | medium | `html_list` | 77 | 77 | 65 | 71/71 | 0/77 |
| 1bc9710cd463 | 14 | small | `html_list` | 47 | 52 | 35 | 36/36 | 10/52 |
| 089b3b827f0d | 15 | medium | `html_list` | 70 | 82 | 69 | 79/79 | 0/82 |
| 76952f77479c | 17 | small | `html_list` | 44 | 44 | 41 | 40/40 | 0/44 |
| 56870eb6156f | 18 | large | `html_list` | 308 | 315 | 291 | 294/294 | 0/315 |
| 8db407b1e8ef | 19 | large | `html_list` | 122 | 122 | 106 | 112/112 | 0/122 |
| a53961c7d84b | 23 | small | `html_cards` | 28 | 28 | 23 | 26/28 | 0/28 |
| e66ce335637a | 26 | medium | `html_list` | 103 | 115 | 95 | 120/120 | 3/115 |
| 29612ad9e3eb | 29 | medium | `html_cards` | 62 | 81 | 59 | 52/52 | 19/81 |
| e442534a6bed | 30 | small | `html_cards` | 30 | 30 | 16 | 16/16 | 0/30 |
| 10e411124d6d | 31 | small | `html_list` | 15 | 15 | 14 | 14/14 | 0/15 |
| 11d4f5f97057 | 35 | small | `html_list` | 49 | 58 | 44 | 44/44 | 0/58 |
| 242bc3a4971e | 36 | small | `html_list` | 18 | 18 | 17 | 15/15 | 3/18 |
| d7fe468d32c1 | 37 | large | `html_list` | 122 | 162 | 57 | 67/67 | 5/162 |
| a4911b31d522 | 38 | medium | `html_list` | 38 | 59 | 11 | 7/7 | 48/59 |
| 6b5c26f7a809 | 39 | medium | `html_list` | 24 | 37 | 22 | 21/31 | 0/37 |
| 00f349e12f5b | 40 | small | `html_list` | 10 | 13 | 10 | 11/11 | 0/13 |
| 0b3f179d98d6 | 41 | medium | `html_list` | 74 | 74 | 47 | 47/47 | 0/74 |
| cfb443e9b654 | 42 | large | `html_list` | 125 | 146 | 103 | 0/4 | 146/146 |
| bd20094a7804 | 43 | medium | `html_list` | 109 | 111 | 43 | 26/26 | 21/111 |
| 46cc79178877 | 44 | small | `html_list` | 10 | 8 | 10 | 8/8 | 0/8 |
| e71329b769a7 | 49 | small | `html_list` | 5 | 5 | 5 | 4/4 | 5/5 |
| e091ddc3c072 | 51 | medium | `html_list` | 104 | 102 | 86 | 64/64 | 31/102 |
| c8c887a2200a | 52 | medium | `html_list` | 95 | 94 | 86 | 83/83 | 0/94 |
| 46c57749a78b | 57 | large | `html_cards` | 40 | 2 | 38 | 6/6 | 0/2 |
| e26ba1731b6e | 61 | large | `html_list` | 190 | 206 | 167 | 186/186 | 0/206 |

**Promo (recorded, not gated):** 35 promo entries and 43 promo-marked items on the
held-out pages; 60 promo-marked priced rows stored as prices.

**Run report** (35 pages, laptop). The CLI's own report covers only the resumed 11 pages
(the reaper stopped the first run before it printed); the rest is rebuilt from the saved
answers and the clone. 361 chunks, all finished on their own (**0 truncated**); resumed
pages: 1 sparse retry, 0 resent, 0 failed, 1 page flagged. Written to the clone: 3,013
Menu items and 2,359 price observations on 36 Menu pages (35 `llm`, 1 `jsonld`), 152
variants, 468 sections.

**Laptop numbers, not Pi numbers.** Wall clock about 26,100 s (7.3 h: 00:14:02 to the 24th
saved answer at 05:47:01 UTC, plus 6,133 s for the resume; the page in flight when the
reaper struck, about 29 min, was rolled back and redone), **4.8 pages/h** including Menu
writes; **7.6 pages/h** model time only (33,258 chunk-seconds on 2 slots; 2.7 generated
tokens/s per slot, P5-10: 3.1). SoC max **97 °C** (resume report), CPU frequency cap 1.0.
`helios_laptop` is at Alembic revision `7c2e4b9d1f3a`, before ADR-0005 Amendment 1's
`db40e9424cba` (#74; the owner-run re-time RUN-A-01 is pending), so the clone's Menu
commits are still quadratic: two single-page commits ran 32 and 42 min with the model idle.

## Findings

1. **Recall stays where v5 left it.** Item recall is 0.821 (v5 on P5-10: 0.819; v4 on
   P5-8: 0.838), against 0.864 for v6 on its own tuning pages. Small pages pass (0.860);
   medium pages lose most (0.787). Of the 458 labelled items the pipeline never matched,
   218 have a pipeline row with the right price within 2 blocks under another name, and
   the blinded adjudicator gave every one of them to the label: the model's reading names
   the dish by its description, its section heading ("Salad", "Pasta"), an ingredient
   line, a wine's cuvée line instead of its producer, or the previous dish's name read
   from its price block. The other 240 the model never emitted near their place (unpriced
   course dishes, beer lists, sides).
2. **Two-line and description-first layouts.** The recall loss sits on a few pages:
   a wine list printed as producer over cuvée-and-price (43 of 109 items found), a page
   that prints every price above and below the name (57 of 122; the model emits section
   headings and ingredient lists as items), numbered dishes whose price block sits
   between two names (155 of 190), sushi rolls, breakfast tacos and pitas printed as name,
   description, price (the model names each by its description: 47 of 74, 16 of 30).
3. **Adjudication ran, and changes nothing.** P5-10 skipped it because no label change
   could move its verdict. Here the margins were smaller (recall needed 75 more found
   items, gold-row FR 16 fewer rejected rows) and 218 nearby same-price rows under another
   name could, in principle, have been label choices (a wine named by producer or by
   cuvée, a dish number kept or trimmed). The adjudicators upheld the label on all 218 and
   on all 17 price disagreements; their only label changes (2 upcharges removed,
   owner-confirmed) leave both bars failing (0.821, 0.126).
4. **The false-reject fail sits on one page.** A page that prints its prices in a separate
   column beside the names (aligned only by line spacing) has all 146 gold rows rejected
   (`price_not_grounded`) and 0 of 4 accepted rows exact; without it gold-row FR is 0.075
   (191/2530). The other rejected gold rows are bare one-decimal prices on their own line
   ("6.5": an unmarked one-decimal number is not a price since Amendment 11 item 1, and
   v6's bare-page forms read integers only), a one-decimal price glued to the name
   ("Cold Brew4.5 / 6.5"), and a size label over its price several blocks from the base
   price (48 of 59 on one page).
5. **Price accuracy and catch hold.** Accuracy 0.991 on 1,956 accepted rows and catch
   0.995; 10 of the 17 wrong accepts are on one wings page whose "Only" and "Meal" cards
   share names (the adjudicator sided with the label on all 10). On real output the
   validator catches 0.466 of wrong rows (P5-10 v5: 0.693).
6. **Classifier precision on this draw is lower:** 62 of 72 drawn pages are menus
   (0.861 [0.763, 0.923]; P5-8 66/72, P5-10 67/72): 8 not menus (among them menu hubs that
   only link to menus and a custom-cake options page) and 2 empty. Recorded, not gated (§8 keeps the S6f evaluation);
   the classifier audit (#80; draw precision 0.932 over P5-5, P5-8 and P5-10) proposes a
   page-level sample for this.
7. **Many menu pages print no prices**: 16 of 62 drawn menu pages (26 %; P5-10 33 %).
8. **Throughput.** 0 truncated chunks; 2.7 generated tokens/s per slot under thermal load
   (97 °C). Wall time is dominated by the pre-fix Menu commit on the laptop DB, not the
   model (finding in the run report); the reaper stopped the run once with a browser tab
   holding 11.6 GB.

## What this unblocks

Nothing yet. **Extraction runs (laptop or Pi) stay blocked** on a pipeline version that
passes §8 on a fresh held-out draw: these 35 pages are now tuning pages, next to P5-5's 10,
P5-8's 35 and P5-10's 35 (P5-12's 37 labelled but unscored pages stay unseen). Three
held-out evaluations in a row put item recall at 0.82–0.84 while each version's tuning
recall rose (v4 0.887, v5 0.871, v6 0.864 on its newest tuning set); finding 1 places most of
the gap in what the model names, which no validator or repair lever reaches. For the owner
at the next tuning session: whether to keep tuning validator/repair levers (the column
layout, one-decimal bare prices, glued one-decimal prices) or to take up the model side
(prompt or a stronger model: Amendment 9 item 3 says that needs its own amendment).

**Next draw:** seed **20261013**, the P5-5 spike exclusions plus **all 234 venues labelled
so far** (P5-5 18, P5-8 72, P5-10 72, P5-12 72) **and their 234 sites**
(`var/menu-eval/p5-12/next-draw-exclusions-p5-13.json`, sha256
`0c383cac72ea15f72f204077e353d4c05e8de0d8e50bd8e0ca845144b7e435c1`). The pool shrinks:
this draw had 882 eligible venues and 649 ordered pages; the next one has at most 810
eligible venues.

**Scale run: still deferred to the Pi** (Amendment 10 item 5), on the version that
passes §8.
