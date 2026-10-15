# Held-out evaluation of menu-pipeline v8 (ADR-0013 §8)

Session P5-16, 2026-10-15: the §8 evaluation that
[Amendment 17](../adr/0013-phase5-menu-pipeline.md#amendment-17-2026-10-15-pipeline-version-v8-split-column-headers)
item 4 requires before v8 runs extraction, with the P5-14 procedure on a fresh draw from the
laptop pass, scored with the harness as amended in Amendment 15. Version (branch
`feat/p5-15-validator-v8` @ `43d4482`, PR #87, **not merged**: the owner chose to evaluate that
commit as it stands; the verdict holds for #87 merged unchanged):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v7;validator-v8;classifier-v2
```

**Result: v8 fails §8 on the false-reject bar again, by a smaller margin.** Price accuracy
(0.990), item recall (0.905) and corruption catch (0.992) pass; the false-reject rate on gold
rows is **0.134** (bar ≤ 0.12; Wilson [0.121, 0.148], wholly above it). A blinded
adjudication ran (label changes could have reached the verdict, finding 3); it upheld the
labels and gives the same verdict (0.134). Per §8 and E4, v8 is not cleared for extraction
runs, these 35 pages become tuning pages, and the next version needs another fresh draw.

Measured only: no pipeline, harness, schema, model, dependency or `infra/` change. Page bodies,
labels, outputs and worksheets stay in gitignored `var/menu-eval/p5-16/`; this file keeps
counts and rates. Pages are named by an opaque id (`sha256(record key)[:12]`).

## Owner decisions

The P5-14 answers stand (E1–E5; adjudication only when label changes could reach the
verdict). Asked in this session:

| | Question | Answer |
|---|---|---|
| — | Where the model runs | **The laptop GPU** (owner, at the session's start) |
| G1 | A game held 4.85 GB of the GPU's 8 GB | **Owner closed it** before the extraction |
| G2 | PR #87 unmerged: evaluate `43d4482` or merge first | **Evaluate `43d4482`** |
| G3 | GPU settings | **P5-13's GPU flags with 2 slots** (the extract CLI checks the slot count) |

## Procedure

**Draw** (P5-14's script with P5-14's exclusion list; seed **20261014**, recorded at
2026-10-15 15:08:30 UTC, before drawing):

- Pool: the extract CLI's due queue on `helios_laptop` (read-only): 1,632 pages.
- Excluded (pages): P5-5's exclusions (spike venues 77, spike hosts 234, spike URLs 0) plus
  the 306 venues labelled in P5-5 to P5-14 (306) and their sites (395); the list is P5-14's
  `next-draw-exclusions-p5-15.json` (sha256
  `b4ba244f4abc399d776efc18d527abb643d7aa1da0901abd740b8a401b80b9ab`, checked by the script).
- 619 eligible venues; one page per venue, at most one venue per site: an order of **505**.
  `draw.jsonl` sha256 `8de427f025e472ef151d5821eeef061554630f50a908aaa983bc9c7d8dfa5c20`.
- Strata with the fixed cutoffs: small **260**, medium **212**, large **33** (P50 / P90 171 /
  396, recorded only). The large stratum is thinning (P5-14: 45).
- Exported in draw order per stratum (small 34, medium 26, large 12: 72 pages, 18,280 blocks);
  every body re-segments byte-for-byte to the bundle's blocks.

**Blind labels.** Five fresh labeller agents with P5-14's brief (wine labelled as any drink),
no model call before the freeze; every label parses with `gold_page` and names existing blocks.
Spot-check (session), 5 held-out pages chosen for risk: a cocktail list whose second prices
the labeller had named "Pitcher" from a separate "Pitchers serve 4" note, a 213-item tabbed
menu, a page printing every item three times, a card grid with variant prices split over
blocks, and a page printing an unpriced photo gallery before its priced table. **One
correction before the freeze:** the three "Pitcher" variants set to `null` (the brief's
variant is the label printed with the price); the other 4 pages pass (prices printed by their
items or under their variant lines; uncovered prices are the layout's repeated copies).

Of the 72 labelled pages (4,221 items, 3,551 prices): **48 scorable** menus, **22** menus that
print no prices, **2** not menus (classifier-v2 precision on the draw **70/72**, 0.972 [0.904,
0.992]). Held out: the first scorable pages per stratum in draw order, positions 2–54, 69, 98,
126 and 153. Frozen and hashed at **2026-10-15 15:18:16 UTC**; extraction started 15:18:27 UTC.

| Label set | Held-out manifest sha256 |
|---|---|
| Blind (72 pages, after the spot-check correction) | `d5e49fee2923ad7efc2b6c9ca5209de1ad82d3d6135d1b7de1838ad73dc4ddfa` (all 72) |
| Adjudicated (blind + A2 / A3, awaiting the owner) | `6ea41be0edb483c9606c0c554aee77e460871a8fe27a834d78502339b66a431e` (35 held out) |

**Extraction (owner: the laptop GPU).** The real extract CLI from `43d4482` on a disposable
`TEMPLATE` clone of `helios_laptop` (`helios_p516_eval`, upgraded on the clone only to
`db40e9424cba`, dropped afterwards; `helios_laptop` stays at `7c2e4b9d1f3a`), narrowed to the
35 held-out Versions by the queue wrapper, against the pinned CUDA image `server-cuda-b11176`
(digest `1f4b9cf5…`) with P5-13's GPU flags (all layers on the RTX 3070, flash attention off,
an f16 KV cache) and the CPU service's 2 slots and 8,192-token context; the model file's sha256
was checked and the CLI's `/props` check passed. Answers were written to a separate store.
**This is not the production runtime** (Amendment 15 item 7: the GPU path was a tuning tool),
and its greedy answers are not identical run to run (P5-13: 1 of 5 chunks); item recall and
price accuracy are GPU numbers, comparable neither to P5-14 (Pi) nor to P5-8–P5-12 (laptop
CPU). Gold-row false reject and catch run the validator on the labels' rows and do not depend
on the runtime.

**Blinded adjudication** (Amendment 8 item 3; run per Amendment 10 item 2, finding 3), with
P5-14's packet and its fix (a C row lists what is labelled within 2 blocks of its claimed
block). Readings shuffled with seed 20261015; five fresh adjudicator agents; the key stayed
outside their folder. 389 rows: A 20, B 157, C 153, D 59.

| Class | Rows | Verdicts mapped back |
|---|---|---|
| A (price) | 20 | label 18, pipeline 2 |
| B (labelled, never produced) | 157 | item 157 |
| C (accepted, unmatched) | 153 | not an item 56, same dish as a recorded one 54, "a real item" 43 |
| D (two readings of one dish) | 59 | label 57, neither 2 |

**Label changes proposed: 2** (A2, A3: two "Baked Potato" side rows take the $1 printed as
"(loaded $1)"; a loaded-potato upcharge could equally be read as a modifier, so this is the
owner's call). Not changes: **42 of the 43 C "yes" rows are wines already labelled**, under a
wine section the scope leaves unscored (the packet's "labelled within 2 blocks" list reads the
scored labels, so it showed "nothing"; the model filed those wines under section names the wine
gate doesn't recognise, so its rows weren't dropped); the 43rd is the labelled "PLANT BASED
PATTY" variant of a burger 4 blocks up. The two D "neither" rows name two separate unpriced
items, both already printed readings. A later packet should list out-of-scope labels too.

## Results (§8)

| Stage | Metric | Bar | v8, 35 pages [Wilson 95 %] | |
|---|---|---|---|---|
| [4]+repairs+[5] | Exact price accuracy, accepted rows | ≥ 0.98 | **0.990** (2039/2059) [0.985, 0.994] | ✔ |
| [4] | Item recall | ≥ 0.85 | **0.905** (2063/2279) [0.893, 0.917] | ✔ |
| [5] | Injected-corruption catch (gold rows, seed 7) | ≥ 0.97 | **0.992** (1576/1588) [0.987, 0.996] | ✔ |
| [5] | False reject, correct (gold) rows | ≤ 0.12 | **0.134** (319/2383) [0.121, 0.148] | ✗ |
| [1] | Classifier precision on the draw | (S6f evaluation stands) | 70/72 menus | — |
| End to end | Usable prices | recorded | 0.790 (1883/2383) [0.773, 0.806] | — |
| [5] on real output | False reject / catch | recorded | 0.093 (210/2249) / 0.572 (270/472) | — |

Scores use the blind labels. Adjudicated labels: 0.991 / 0.905 / — / **0.134** (319/2385), usable
0.790: **the same verdict.** v7's validator on these labels: gold-row false reject 0.137
(326/2383); v8's lever changed one page (finding 2).

**Wine scope:** the held-out labels hold 49 items / 78 prices under a wine section on 4 pages,
not scored (72 pages: 73 / 98 on 6). No drawn page loses scorability to it.

**Per stratum** (price accuracy / item recall / gold-row FR / usable):

| Stratum | Pages | Gold items / prices | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|---|
| small | 14 | 337 / 359 | 0.993 | 0.926 | 0.078 | 0.811 |
| medium | 14 | 1,077 / 1,036 | 0.988 | 0.880 | 0.223 | 0.710 |
| large | 7 | 865 / 988 | 0.991 | 0.928 | 0.061 | 0.866 |

**Per format:**

| Format | Pages | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|
| `html_list` | 30 | 0.990 | 0.908 | 0.107 | 0.816 |
| `html_cards` | 3 | 1.000 (138/138) | 0.907 | 0.416 | 0.528 |
| `price_list` | 2 | 0.981 (53/54) | 0.818 | 0.062 | 0.815 |

**Corruption per type** (seed 7): `invented_item` 340/340, `mutated_price` 328/328,
`other_section_price` 295/296, `swapped_prices` 613/624 (2 indistinguishable).

**False rejects of gold rows by reason** (319): `price_not_grounded` 170,
`variant_not_grounded` 127, `price_belongs_to_other_variant` 12, `addon_price` 5,
`price_bound_to_other_item` 4, `implausible_amount` 1.

**Loss buckets** (2,383 gold prices): `accepted` 1,909 (0.801), `item_missed` 226 (0.095),
`wrong_amount` 107 (0.045), `not_accepted:price_not_grounded` 94 (0.039), `row_unpriced` 26
(0.011), `not_accepted:variant_not_grounded` 10, `not_accepted:price_belongs_to_other_variant`
8, and 3 others (1 each).

**Per page** (draw position, stratum, format, gold items / prices, items found, accepted prices
exact, gold rows rejected):

| Page | Pos. | Stratum | Format | Items | Prices | Found | Exact | Gold FR |
|---|---|---|---|---|---|---|---|---|
| f20008cf4b57 | 2 | small | `price_list` | 34 | 33 | 32 | 31/31 | 0/33 |
| d6a88e562d42 | 3 | small | `price_list` | 32 | 32 | 22 | 22/23 | 4/32 |
| 92f24d17fc0b | 6 | medium | `html_list` | 77 | 47 | 73 | 42/44 | 0/47 |
| 84ce0ffac33b | 7 | small | `html_list` | 27 | 40 | 26 | 38/38 | 0/40 |
| 354835a38faf | 8 | small | `html_cards` | 36 | 55 | 35 | 38/38 | 1/55 |
| b7b34a2fc8ae | 11 | small | `html_list` | 16 | 8 | 14 | 8/8 | 2/8 |
| ce95163d1996 | 15 | small | `html_list` | 5 | 6 | 4 | 5/6 | 0/6 |
| 22b9f9dc5dca | 16 | small | `html_list` | 11 | 11 | 11 | 11/11 | 0/11 |
| 59c3349a4141 | 17 | small | `html_list` | 30 | 30 | 27 | 27/27 | 0/30 |
| 9d03d5eb5c01 | 18 | medium | `html_list` | 109 | 133 | 89 | 89/89 | 36/133 |
| 8c9e5f8255f3 | 19 | small | `html_list` | 9 | 9 | 8 | 7/7 | 9/9 |
| b2f05f723b29 | 20 | large | `html_list` | 183 | 183 | 183 | 179/179 | 0/183 |
| 5736c0d83ea9 | 21 | medium | `html_list` | 123 | 123 | 121 | 119/119 | 0/123 |
| 6d5cdfffe336 | 22 | medium | `html_list` | 94 | 101 | 83 | 84/85 | 12/101 |
| d7af03b5ca98 | 23 | medium | `html_list` | 54 | 50 | 44 | 36/36 | 34/50 |
| 590c72ebfeb3 | 24 | medium | `html_list` | 31 | 31 | 31 | 31/31 | 0/31 |
| b51fb0bb44ad | 27 | small | `html_list` | 9 | 9 | 9 | 9/9 | 0/9 |
| f3596d08bc0f | 28 | medium | `html_list` | 51 | 52 | 44 | 46/46 | 0/52 |
| 05273895b4e2 | 30 | medium | `html_cards` | 61 | 105 | 48 | 37/37 | 88/105 |
| f930a5d428a3 | 31 | medium | `html_list` | 132 | 7 | 121 | 7/7 | 0/7 |
| ebb1bcb352e9 | 32 | large | `html_cards` | 54 | 54 | 54 | 63/63 | 0/54 |
| 5f7d7159e1c7 | 34 | small | `html_list` | 26 | 26 | 26 | 24/24 | 0/26 |
| dde4ec968981 | 35 | large | `html_list` | 106 | 106 | 101 | 100/100 | 1/106 |
| 5481f931c214 | 36 | medium | `html_list` | 103 | 109 | 100 | 108/108 | 8/109 |
| fa377c80652b | 40 | medium | `html_list` | 98 | 112 | 76 | 50/56 | 26/112 |
| 62da4ba6c07b | 41 | medium | `html_list` | 38 | 42 | 38 | 40/40 | 1/42 |
| 5766f639d1a2 | 44 | medium | `html_list` | 59 | 59 | 44 | 41/41 | 3/59 |
| 495025db12b0 | 48 | small | `html_list` | 31 | 34 | 31 | 21/21 | 0/34 |
| 5d960df16b84 | 49 | medium | `html_list` | 47 | 65 | 36 | 33/33 | 23/65 |
| 91afcf64ff75 | 51 | small | `html_list` | 32 | 24 | 29 | 25/25 | 0/24 |
| 3195900e6fc7 | 54 | small | `html_list` | 39 | 42 | 38 | 29/29 | 12/42 |
| bb7f2aea0431 | 69 | large | `html_list` | 106 | 105 | 79 | 75/76 | 0/105 |
| 842483d29f5e | 98 | large | `html_list` | 145 | 201 | 124 | 174/176 | 12/201 |
| d7597977b80b | 126 | large | `html_list` | 213 | 252 | 208 | 221/226 | 4/252 |
| 13877d017be9 | 153 | large | `html_list` | 58 | 87 | 54 | 169/170 | 43/87 |

**Promo (recorded, not gated):** 11 promo entries and 7 promo-marked items on the held-out
pages; 8 promo-marked priced rows stored as prices.

**Run report** (35 pages; the CLI, the clone and the GPU server on the laptop): 35 due, 35
extracted, 0 reused answers, 0 failed, 11 pages flagged, 3 `jsonld` pages; 254 chunks (253
finished on their own, **1 truncated**), 6 sparse retries, 0 resent. Written to the clone: 2,918
Menu items and 2,263 price observations on 38 Menu pages, 223 variants, 405 sections, 8,119
Evidence links.

**GPU numbers.** Wall clock **926 s** (15:18:27 to 15:33:53 UTC), **136 pages/h** including Menu
writes; 138 pages/h model time (1,823 chunk-seconds on 2 slots; 47.7 generated tokens/s per
slot). The RTX 3070 ran at its thermal limit: up to 89 °C, its clock down to 555–780 MHz under
load (as in P5-13). The CLI's own `soc_max_temp_c` 100 °C is the laptop CPU's sensor.

## Findings

1. **Recall passes again, false reject misses again, closer.** Item recall 0.905 (P5-14 v7:
   0.883 on the Pi); gold-row false reject 0.134 (P5-14: 0.153 under v7, 0.094 under v8 once
   tuned on those pages). The bar needs 34 fewer rejected rows (38 removed, counting the
   denominator). Medium pages carry it (0.223); small and large pass (0.078, 0.061).
2. **v8's lever recurs once in this draw.** Under v7's validator these labels give 0.137; v8
   grounds 7 more rows on one page (a priced table under an unpriced photo gallery; 41 → 34
   rejected). The split-column layout behind P5-14's four pages is rare.
3. **Adjudication ran and changes nothing material.** 73 rejected gold rows sat on items the
   packet shows, enough in principle to reach the bar (38 needed). The adjudicators upheld every
   B row (157 labelled items the pipeline never produced are real items) and 57 of 59 D rows; the
   only label changes (A2, A3: a "(loaded $1)" price) leave 0.134. 42 C "yes" answers were wines
   already labelled out of scope (a packet gap: the nearby list should include out-of-scope
   labels).
4. **Where the false rejects sit** (a few pages hold most of them):
   - a card grid printing a currency sign in its own block between the name and the price
     ("Shaken Beef" "B1" "$" "15.99"; 88 of 105 on one page, with its variant lines "Chicken -"
     "$" "15.99");
   - "3/6 Catfish Strips Dinner … $9.95/$17.99" rows, labelled with variants "3" and "6" taken
     from the name's "3/6" (42 of 87 on one page): a label convention question;
   - a group price printed once under a section heading over a list of named dishes
     ("Breakfast Tacos" "$3.50." over "Noe Taco", "Hugo Taco" …; 28 on one page);
   - an unpriced gallery before the priced table, whose sizing-column labels the labeller used
     as variants (34 of 50; 7 fewer with v8);
   - a unit printed after its price inside the block ("$6 link / $26 lb"; 23 on one page);
   - on a bare-price page, a line holding two prices ("combo | 13.5 + guacamole & sour cream
     + 3.5": only the last number is read; 26 on one page).
   These match classes left open after P5-14 (group prices, unread price text, own-line and
   after-price labels) plus one new form, a currency sign printed alone in its block.
5. **Price accuracy and catch hold:** 0.990 on 2,059 accepted rows; catch 0.992. On real
   output the validator rejects 0.093 of correct rows and catches 0.572 of wrong ones.
6. **Classifier precision on this draw:** 70 of 72 drawn pages are menus (0.972 [0.904,
   0.992]): a retail product page and one other. Recorded, not gated.
7. **Menus that print no prices:** 22 of 70 drawn menu pages (31 %; P5-14 34 %).
8. **The GPU runtime** finishes 35 pages in 15 minutes (the Pi took 7.4 h for P5-14's), at its
   thermal limit; it is not the production path, and its answers vary run to run.

## What this unblocks

Nothing yet. **Extraction runs stay blocked** on a version that passes §8 on a fresh held-out
draw; these 35 pages are now tuning pages. The false-reject bar has failed on three draws in a
row (P5-12 0.126, P5-14 0.153, P5-16 0.134) while recall now passes; each fail sits on a handful
of pages with layouts the validator can't ground. For the owner at the next tuning session:
which of the open classes to take (finding 4), the "+$" add-on policy, whether the GPU or the
CPU is the evaluated runtime, and the label convention for variants inferred from a name
("3/6 …").

**Next draw:** seed **20261015**, the P5-5 spike exclusions plus **all 378 venues labelled so
far** (P5-5 18, P5-8 72, P5-10 72, P5-12 72, P5-14 72, P5-16 72) **and their 378 sites**
(`var/menu-eval/p5-16/next-draw-exclusions-p5-17.json`, sha256
`dd748ff55c3b2987506997200029d8b6ead8caff92278943081e2c56dd167c9b`). The pool shrinks: this
draw had 619 eligible venues, 505 ordered pages and 33 large ones; the next has at most 547
eligible venues.

**Scale run: still deferred to the Pi** (Amendment 10 item 5), on the version that passes §8.
