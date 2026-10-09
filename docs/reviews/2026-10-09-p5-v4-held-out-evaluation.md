# Held-out evaluation of menu-pipeline v4 (ADR-0013 §8)

Session P5-8, 2026-10-03 to 2026-10-09: the §8 evaluation that
[Amendment 9](../adr/0013-phase5-menu-pipeline.md#amendment-9-2026-10-03-pipeline-version-v4-tuned-on-the-p5-5-pages)
item 4 requires before v4 runs extraction, on a larger sample than P5-5's (35 scorable
pages, not 10). Version:

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.3;chunk-v2.1;segment-v2;repairs-v4;validator-v4;classifier-v2
```

**Result: v4 fails §8.** Item recall (0.838) and the false-reject rate on gold rows
(0.278) miss their bars; price accuracy (0.983) and corruption catch (0.995) pass. Per
the owner's answer E4, v4 is not cleared for extraction runs, these 35 pages become
tuning pages, and the next version needs another fresh draw.

Measured only: no pipeline, harness, schema, model, dependency or `infra/` change, no Pi
access. Page bodies, labels, outputs and worksheets stay in gitignored
`var/menu-eval/p5-8/`; this file keeps counts and rates. Pages are named by an opaque id
(`sha256(record key)[:12]`).

## Owner decisions

Before any sampling:

| | Question | Answer |
|---|---|---|
| E1 | Sample size | **35 scorable pages** (P5-5: 10) |
| E2 | Stratification | **Quotas by page size** (bundle block count, read before any content): small 14, medium 14, large 7. Layout family can't be known without reading the page, so it is recorded after labelling, not stratified. Pass/fail on the pooled set |
| E3 | Labelling | **Parallel fresh labeller agents** (one batch each, same brief), owner spot-check of 5 pages before freezing |
| E4 | Pass / fail | **Point estimates** on the pooled pages, as in P5-5; Wilson intervals recorded, not gated. A fail makes the pages tuning pages |
| E5 | Scale run beyond §8 | **100 unlabelled pages after §8** (later deferred: below) |
| — | Slow Menu commits (P5-6 fix not merged) | **Let them run**: the extract CLI unchanged; scoring reads the saved raw answers |

Label conventions the owner ruled on before the freeze (labellers disagreed on them;
every batch was brought in line, and the brief records them):

- The same list printed twice by a view toggle or tab, or an accidental copy ("Lunch
  (Copy)"), counts **once**. Genuinely separate menus (lunch and dinner) still count once
  per placement (Amendment 8 item 4).
- Any add-on printed on its own line with its own price is an **item**; "+$2" inside
  another item's text is a modifier.
- Several names joined on one row with one price ("A, B, C $3") are **one item per
  name**; an "A or B" choice row is **one item**.
- A priced heading with its flavour list in another block stays one item; catering
  service rows (cups, plates, delivery) are not items.

After scoring: **no blinded adjudication.** The false-reject fail comes from correct gold
rows the validator can't ground (findings 1–2), so no label change can bring it under
0.12; the scores below use the blind labels (the owner's convention rulings were applied
before the freeze, so blind = confirmed). The E5 scale run is **deferred to a Pi run** (below).

## Procedure

**Draw** (`var/menu-eval/p5-8/draw.py`, P5-5's script plus the P5-5 exclusions and size
strata; seed **20261008**, recorded before drawing):

- Pool: the extract CLI's due queue on `helios_laptop` (read-only): 1,632 pages.
- Excluded: P5-5's exclusions (spike venues **77**, spike hosts **234**, spike URLs **0**)
  plus the 18 venues P5-5 labelled (**18**) and their sites (**51**).
- 1,251 eligible venues, shuffled with the seed; one page per venue, at most one venue
  per site: an order of **793**. `draw.jsonl` sha256
  `68a06cdd86b9288b74950cd950a23db9863e55e2901b3ae6298b099f332445cb`.
- Strata by the bundle's block count over the ordered pages: small < 176 (P50) **396**,
  medium 176–499 **317**, large ≥ 500 (P90) **80**.
- Exported in draw order per stratum (first small 34, medium 26, large 12: 72 pages);
  every body re-segments byte-for-byte to the bundle's blocks.

**Blind labels.** Four fresh labeller agents (about 4,850 blocks each) and a fifth for
8 more small pages, labelled from the segmented blocks (raw HTML for layout only) with
the P5-5 brief plus the owner's rulings, before any model call. A first labelling round
was re-checked against the rulings by fresh agents (only affected rows changed). Owner
spot-check (done by the session at the owner's request): 5 pages, every labelled price
checked to be printed beside its item and every printed price either labelled or an
owner-excluded row; all 5 pass (one garbled image-alt page has one ambiguous row).

Of the 72 labelled pages: **46 scorable** menus, **20** menus that print no prices,
**6** not menus (classifier-v2 precision on the draw **66/72**). Held out: the first
scorable pages per stratum in draw order (small 14, medium 14, large 7), positions 1–101.
Frozen and hashed at **2026-10-09 00:55:15 UTC**; extraction started 01:04:53 UTC.

| Label set | Manifest sha256 |
|---|---|
| Blind (72 pages; = confirmed) | `da1cb6df0288e017e2a9698210ce40ce894d327f8bf40778ab74f0048e64fb01` |

**Extraction.** The real extract CLI on a disposable `TEMPLATE` clone of `helios_laptop`
(`helios_p58_eval`), narrowed to the 35 held-out Versions by P5-5's queue wrapper,
against `llama-server` `server-b11176` pinned by digest (`llama-model-check` passed;
`/props`: the manifest GGUF, 2 slots), Compose project `helios-p58`, run from the owner's
terminal. Scored with `python -m apps.menu_pipeline.evaluate compare|loss|corrupt` as
frozen in Amendment 9 (no harness edits).

## Results (§8)

| Stage | Metric | Bar | v4, 35 pages [Wilson 95 %] | |
|---|---|---|---|---|
| [4]+repairs+[5] | Exact price accuracy, accepted rows | ≥ 0.98 | **0.983** (1804/1835) [0.976, 0.988] | ✔ |
| [4] | Item recall | ≥ 0.85 | **0.838** (2059/2456) [0.823, 0.852] | ✗ |
| [5] | Injected-corruption catch (gold rows, seed 7) | ≥ 0.97 | **0.995** (1514/1522) | ✔ |
| [5] | False reject, correct (gold) rows | ≤ 0.12 | **0.278** (758/2722) [0.262, 0.296] | ✗ |
| [1] | Classifier precision on the draw | (S6f evaluation stands) | 66/72 menus | — |
| End to end | Usable prices | recorded | 0.647 (1762/2722) [0.629, 0.665] | — |
| [5] on real output | False reject / catch | recorded | 0.222 (516/2320) / 0.645 (320/496) | — |

P5-5 (slice-5 version, 10 pages) for comparison: 0.963 / 0.837 / 0.988 / 0.306, usable
0.620. v4's tuning numbers on P5-5's pages: 0.990 / 0.887 / 0.998 / 0.112.

**Per stratum** (price accuracy / item recall / gold-row FR / usable):

| Stratum | Pages | Gold items / prices | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|---|
| small | 14 | 505 / 486 | 0.991 | 0.638 | 0.463 | 0.447 |
| medium | 14 | 967 / 1,210 | 0.985 | 0.855 | 0.194 | 0.732 |
| large | 7 | 984 / 1,026 | 0.978 | 0.925 | 0.290 | 0.642 |

**Per format:**

| Format | Pages | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|
| `html_list` | 26 | 0.981 | 0.884 | 0.207 | 0.700 |
| `html_cards` | 5 | 0.991 | 0.913 | 0.356 | 0.690 |
| `html_inline` | 2 | 1.000 (8/8) | 0.260 | 0.916 | 0.037 |
| `price_list` | 2 | 1.000 | 0.900 | 0.185 | 0.728 |

**Corruption per type** (seed 7):

| Type | n | Caught | Indistinguishable |
|---|---|---|---|
| `invented_item` | 340 | 340 | 0 |
| `mutated_price` | 314 | 313 | 0 |
| `other_section_price` | 284 | 283 | 0 |
| `swapped_prices` | 584 | 578 | 1 |

**False rejects of gold rows by reason** (758 rows; a row can carry several reasons):
`price_not_grounded` 516, `variant_not_grounded` 134, `name_not_grounded` 77,
`price_belongs_to_other_variant` 25, `price_bound_to_other_item` 3, `addon_price` 3.

**Loss buckets** (every gold price in one bucket, 2,722):

| Bucket | Prices | Share |
|---|---|---|
| `accepted` | 1,769 | 0.650 |
| `item_missed` | 464 | 0.170 |
| `not_accepted:price_not_grounded` | 307 | 0.113 |
| `wrong_amount` | 124 | 0.046 |
| `not_accepted:variant_not_grounded` | 20 | 0.007 |
| `row_unpriced` | 12 | 0.004 |
| `not_accepted:name_not_grounded` | 12 | 0.004 |
| `not_accepted:price_belongs_to_other_variant` | 9 | 0.003 |
| `not_accepted:price_bound_to_other_item` | 5 | 0.002 |

**Per page** (draw position, stratum, format, gold items / prices, items found, accepted
prices exact, gold rows rejected):

| Page | Pos. | Stratum | Format | Items | Prices | Found | Exact | Gold FR |
|---|---|---|---|---|---|---|---|---|
| c8973625f332 | 1 | medium | html_list | 18 | 22 | 7 | 6/8 | 12/22 |
| 647e79a96085 | 2 | medium | html_list | 92 | 103 | 67 | 71/72 | 17/103 |
| 01b2062b3149 | 3 | medium | html_list | 85 | 87 | 82 | 78/78 | 3/87 |
| d89d0907aa58 | 5 | medium | html_list | 94 | 94 | 90 | 94/94 | 0/94 |
| 3ba44cb71a99 | 7 | medium | html_list | 61 | 144 | 49 | 124/125 | 3/144 |
| 9fe45eda57cd | 8 | small | price_list | 21 | 24 | 21 | 13/13 | 11/24 |
| ddb652ccea54 | 9 | medium | html_cards | 48 | 57 | 43 | 42/43 | 10/57 |
| 0d9246cc5dfd | 11 | medium | html_list | 79 | 107 | 71 | 99/99 | 69/107 |
| 3371ed6768f4 | 12 | medium | html_list | 42 | 50 | 40 | 42/43 | 0/50 |
| 827c3fa69905 | 14 | small | html_list | 31 | 7 | 29 | 5/5 | 0/7 |
| f2f4666c11f4 | 16 | medium | html_list | 97 | 129 | 78 | 66/66 | 64/129 |
| c5596aebdcb4 | 17 | medium | html_list | 55 | 63 | 40 | 26/33 | 29/63 |
| 70f3cffc05be | 18 | small | html_list | 43 | 43 | 40 | 40/40 | 1/43 |
| 0e13fe6de82b | 22 | medium | html_list | 123 | 148 | 103 | 83/84 | 18/148 |
| 646bed68940a | 24 | small | html_cards | 29 | 17 | 27 | 19/19 | 3/17 |
| 2f8e9a845c2b | 25 | small | html_inline | 95 | 106 | 14 | 7/7 | 89/106 |
| b78f8c753015 | 29 | medium | html_list | 40 | 41 | 39 | 39/39 | 1/41 |
| 3568b374910c | 30 | small | html_list | 1 | 1 | 0 | 0/0 | 0/1 |
| b641af8c7059 | 32 | medium | html_list | 34 | 34 | 25 | 25/25 | 0/34 |
| f6876e4077e3 | 33 | medium | html_cards | 99 | 131 | 93 | 117/117 | 9/131 |
| 066e674fdbc7 | 37 | small | html_list | 21 | 27 | 18 | 21/22 | 10/27 |
| 8120eb028ecc | 41 | small | html_list | 38 | 12 | 36 | 10/10 | 0/12 |
| a91592612a02 | 43 | small | html_list | 5 | 5 | 5 | 5/5 | 0/5 |
| 2b5ed16cc9ef | 44 | small | html_list | 45 | 53 | 36 | 39/39 | 0/53 |
| 58a3a119e755 | 46 | large | html_list | 162 | 157 | 153 | 141/141 | 3/157 |
| c6b7ec71d75e | 47 | small | html_list | 12 | 12 | 12 | 12/12 | 0/12 |
| 1338c160b655 | 50 | large | html_list | 195 | 226 | 185 | 182/184 | 28/226 |
| b208f79d3315 | 52 | small | html_inline | 101 | 108 | 37 | 1/1 | 107/108 |
| 46437f3dea40 | 55 | small | html_cards | 14 | 14 | 5 | 7/8 | 0/14 |
| a8684c49dfa1 | 57 | small | price_list | 49 | 57 | 42 | 46/46 | 4/57 |
| 40be9b8269ff | 62 | large | html_list | 42 | 42 | 42 | 34/34 | 0/42 |
| dae1118c1788 | 86 | large | html_list | 158 | 177 | 132 | 130/132 | 23/177 |
| 87ef1c007879 | 88 | large | html_cards | 87 | 87 | 85 | 35/35 | 87/87 |
| 78ddbf7ec3f0 | 100 | large | html_list | 137 | 134 | 123 | 92/92 | 11/134 |
| d48fc260652f | 101 | large | html_list | 203 | 203 | 190 | 53/64 | 146/203 |

**Promo (recorded, not gated):** 8 promo entries and 29 promo-marked items on the held-out
pages; 27 promo-marked priced rows stored as prices.

**Run report** (35 pages, laptop): 280 chunks, 3 sparse retries, **4 truncated**, 0
resent, 0 failed; 13 pages flagged `unlabeled_price_runs`; 6 pages with a `jsonld` stream.
LLM rows: accept 1,980; downgrade 1,182 (`price_not_grounded` 689, `no_price_extracted`
446, `variant_not_grounded` 24, `price_belongs_to_other_variant` 13,
`price_bound_to_other_item` 10); reject 117 (`duplicate_row` 72, `name_not_grounded` 40,
`implausible_amount` 5). 3,003 items and 2,091 prices written; 456 `unsectioned_items`.

**Laptop numbers, not Pi numbers.** Wall clock 24,693 s (6.9 h), **5.1 pages/h** including
Menu writes; **7.7 pages/h** model time only (32,596 chunk-seconds on 2 slots; 2.8
generated tokens/s per slot, below P5-5's 3.9, on larger pages under thermal load). SoC
max **98 °C**, CPU frequency cap 1.0.

## Findings

1. **Price text the validator can't read.** One large page prints "12.5 USD": a
   one-decimal price without `$`. The price tokenizer reads one decimal digit only after
   `$`, and its bare-integer rule skips "12.5", so the block has no price token and 146
   of the page's 203 gold rows are `price_not_grounded`. The owner's direction for the
   next version: a classical, layout-generic normalization of printed price text
   (currency words, spacing, one-decimal amounts) as the last step, leaving context
   collection dynamic.
2. **Card prices far from the name.** A cards page prints name, name again, category,
   description, then "Select options $ 5.99" four blocks below; the token exists but the
   validator doesn't ground a price that far from the item's name block: all 87 gold
   rows are rejected. This is a grounding-window question, not formatting.
3. **The false-reject fail is broad, not two pages.** Without both pages above and the
   two `html_inline` pages, gold-row FR is still 0.148 (329/2218); `variant_not_grounded`
   (134) is concentrated on one page (69/107) that prints sizes as column headers.
4. **Inline pages are nearly lost.** The two `html_inline` pages (one site that prints
   its whole menu in jumbled run-together blocks, one menu inside garbled image alt
   text) score item recall 0.260 and usable 0.037. Without them item recall is 0.888
   (2008/2260) and gold FR 0.224.
5. **Small pages score worst** (recall 0.638, gold FR 0.463): both inline pages are
   small, and short pages have fewer rows to dilute one layout gap. Large pages
   recall well (0.925) but lose prices to findings 1–2.
6. **Price accuracy holds** at scale (0.983, 1,835 accepted rows), and corruption catch
   rises to 0.995: what the validator accepts is right; the loss is in what it rejects
   and what the model misses.
7. **Many menu pages print no prices**: 20 of 66 drawn menu pages (30 %), as P5-5 found
   (8 of 18).
8. **Throughput under load.** 4 chunks truncated (P5-5: 0) and generation slowed to
   2.8 tokens/s per slot at 98 °C; the 7 large pages dominate model time.

## What this unblocks

Nothing yet. **Extraction runs (laptop or Pi) stay blocked** on (a) a pipeline version
that passes §8 on a fresh held-out draw (these 35 pages are now tuning pages, next to
P5-5's 10), and (b) the Menu-write commit fix (Amendment 8 item 6). The next tuning
session should target, in order: price-text normalization (finding 1), the
price-grounding window on card layouts (finding 2), the remaining `price_not_grounded` /
`variant_not_grounded` spread (finding 3), and inline layouts (finding 4); the next
evaluation needs another fresh draw from the laptop pass, excluding the 90 venues
labelled in P5-5 and P5-8 (18 + 72) and their sites.

**E5 scale run: deferred to a Pi run.** The owner would rather run the 100-page,
label-free scale check on the Pi in parallel than tie up the laptop. It is not run
here: this session has no Pi access, the laptop pass's pages and bundles are not on
the Pi (Amendment 8 item 1 leaves that open), and the Pi `llama-server` image check is
still pending. Re-evaluate it once those hold, on the version that passes §8 (v4's
numbers would be stale): throughput, chunk retries and truncations, the
accept/downgrade mix, `unlabeled_price_runs` and empty-page rates, and the label-free
coverage signal (accepted priced rows / printed prices) per page.
