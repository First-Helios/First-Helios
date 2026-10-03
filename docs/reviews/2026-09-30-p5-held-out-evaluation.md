# First held-out evaluation of the menu pipeline (ADR-0013 §8)

Session P5-5, 2026-09-30 to 2026-10-03: the §8 evaluation that
[Amendment 7](../adr/0013-phase5-menu-pipeline.md#amendment-7-2026-09-29-extraction-and-menu-writes)
item 8 requires before extraction runs. It is the first one for the slice-5 pipeline version:

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.3;chunk-v2.1;segment-v2;repairs-v3;validator-v3;classifier-v2
```

**Result: the version fails §8.** Price accuracy on accepted rows (0.963), item recall
(0.837) and the false-reject rate on gold rows (0.306) miss their bars; corruption catch
(0.988) passes. Per the owner's answer E4, the version is not cleared for extraction runs,
these 10 pages become tuning pages, and the next version needs a fresh held-out set.

Measured only: no pipeline tuning, schema, model, dependency or `infra/` change, no Pi
access. Page bodies, labels, outputs and worksheets stay in gitignored
`var/menu-eval/p5-5/`; this file keeps counts and rates. Pages are named by an opaque id
(`sha256(record key)[:12]`).

## Owner decisions (before any sampling)

| | Question | Answer |
|---|---|---|
| E1 | Sample source | **Full laptop pass**: seed the whole metro into a persistent laptop DB, resolve URLs and fetch every menu page, then draw from that run (it is the first big run; Amendment 8) |
| E1b | Rendered pages | **Static only** (`--render` off, as Pi runs are today); rendered-page bars stay with slice 6 |
| E2 | Labeller | **A fresh agent** (own context), labels written and hashed before the first model call |
| E3 | Promo labels | **Promo-entry format in the harness** (Amendment 5), kept light: optional, kinds checked, counted only, no pipeline change |
| E4 | Pass / fail | **Point estimates** on the pooled pages; Wilson intervals and usable prices recorded, not gated; classifier-v2 unchanged, so its S6f evaluation stands (precision on the draw recorded). A fail is a finding: the version isn't cleared, the pages become tuning pages, the next version needs a fresh set |
| E5 | Extraction path | **The real extract CLI** (`apps.menu_pipeline.extract`) against the pinned `llama-server` image; its saved raw answers feed `compare` / `loss` / `corrupt` |

Later answers, put when they came up: wait for the full crawl before drawing (it ran
~3× longer than estimated); the remaining 8 pages were extracted from the owner's
terminal (no 2 h job cap) and the slow Menu-write commit left to finish; disagreements
reviewed through a **blinded adjudicator** with the owner confirming every label change
(below); a dish printed in several inline menus is **one gold row per printed placement**;
a printed "Add - Ons" list with its own heading and one priced row each **stays items**.

## Procedure

**Laptop first pass (Amendment 8).** A persistent (not disposable) local PostgreSQL 16
database, `helios_laptop`:

| Step | Result |
|---|---|
| `python -m apps.discovery --no-geocode` (Overture `2026-08-19.0`) | 10,014 POIs, **9,996 venues** minted, 18 deduped, 1 location override applied |
| `python -m apps.discovery.resolve_urls` | 9,996 venues; **8,085** with a website record, 1,911 without a website; **1,635** menu-URL records (16 % of venues), 3,550 venues with no menu URL found, 269 `platform_ambiguous`, 90 `menu_pdf_only` |
| `python -m apps.menu_pipeline.run` (static) | **894** distinct URLs fetched: 892 succeeded, 1 `not_menu`, 1 `network_error`; **1,632** Versions (1,631 Organization scope, 1 Establishment); 42 pages link a menu PDF |

`resolve_urls` ran ~5–9 venues/min (sequential), about a day of crawling over several
launches (it resumes from its last committed batch). One launch crashed on a homepage href that `urllib` can't parse
(`ValueError: Invalid IPv6 URL`); fixed in #67 and resumed. ADR-0013's planning figure was
~2,300 menu pages; this pass has 1,635 records on 894 distinct URLs (chain locations share
a page).

**Draw** (`var/menu-eval/p5-5/draw.py`, seed **20260930**):

- Pool: the extract CLI's own due queue (`due_pages`): 1,632 pages.
- Excluded: pages of a venue the spike saw (GERS ids in the spike's `venues.jsonl`, both
  candidate exports and `pages.jsonl`: 350 ids) **77**; pages whose venue website or
  own-site page host is a host the spike fetched (321 hosts, platforms excepted) **234**;
  page URLs the spike or the S6f render probe fetched (697 URLs) **0**.
- 1,320 eligible venues, sorted by GERS id and shuffled with the seed; one page per venue
  (seeded choice), at most one venue per site: an order of 811.
- Pages exported from their bundles; every body re-segments byte-for-byte to the bundle's
  blocks.
- Labelled in draw order until 10 pages printed prices: positions **1–18** labelled, all
  18 menus (**classifier-v2 precision on the draw 18/18**); 8 are menus that print no
  prices in their static text (not scorable). Held out: positions 4, 5, 7, 8, 10, 12,
  15–18. All 10 are own-site, Organization-scope, static pages.

**Blind labels.** A fresh agent labelled from the segmented blocks (raw HTML for layout
only), in the harness's gold format plus promo marks and promo entries, before any model
call. The label files were frozen and hashed at **2026-10-02 20:15:26 UTC**; the
extraction run started at 20:16:06 UTC.

| Label set | Manifest sha256 (of `sha256sum`-style lines, per file) |
|---|---|
| Blind (18 pages) | `183db92486f904f2a2ed39079dfad112c3a54928994f7e1051dbe222c9900b8c` |
| Confirmed (18 pages) | `78766370aa281aece9c3cc05047adae2d8f8dc76589c9e4b27f0eaa426d9d414` |

**Extraction.** The real extract CLI on a disposable `TEMPLATE` clone of `helios_laptop`,
narrowed to the 10 held-out Versions by a wrapper that filters `due_pages` (nothing else
changed), against `llama-server` `server-b11176` pinned by digest, the manifest's GGUF
(`llama-model-check` passed; `/props`: the manifest file, 2 slots), Compose project
`helios-p55`. Run 1 extracted 2 pages before the 2 h job limit stopped it (its report
was not printed); run 2 extracted the other 8 (report below). Raw answers are kept under
`var/replay/menu-extract/` and copied into the harness layout.

**Disagreements (Amendment 3 item 4, owner-chosen variant).** 237 rows where label and
pipeline disagree on a gated metric: 19 accepted rows whose price isn't the label's (A),
134 labelled items never produced (B), 84 accepted rows matching no labelled item (C). A
second fresh agent judged them from the page text without knowing which reading came from
which side (A readings in random order, seed 20261003): A 8 / 8 / 2 both / 1 neither;
B 129 yes, 5 fix; C 5 yes, 1 same dish, 78 no. Mapped back: 14 of 19 A rows side with
the label; A1–A3 are the pipeline listing a dish's protein choices as items where the
label has them as variants of one item (a harness matching artifact, not a label error).
The owner confirmed **10 label changes** (5 teas take their heading price; 5 priced
packages added) and the two class questions above. Scores below use the confirmed labels;
the blind-label scores are given for comparison.

## Results (§8)

| Stage | Metric | Bar | Confirmed labels [Wilson 95 %] | Blind labels | |
|---|---|---|---|---|---|
| [4]+repairs+[5] | Exact price accuracy, accepted rows | ≥ 0.98 | **0.963** (489/508) [0.942, 0.976] | 0.962 | ✗ |
| [4] | Item recall | ≥ 0.85 | **0.837** (688/822) [0.810, 0.861] | 0.836 | ✗ |
| [5] | Injected-corruption catch (gold rows, seed 7) | ≥ 0.97 | **0.988** (416/421) | 0.984 | ✔ |
| [5] | False reject, correct (gold) rows | ≤ 0.12 | **0.306** (238/778) | 0.297 | ✗ |
| [1] | Classifier precision on the draw | (S6f evaluation stands) | 18/18 menus | | — |
| End to end | Usable prices | recorded | 0.620 (482/778) [0.585, 0.653] | 0.621 | — |
| [5] on real output | False reject / catch | recorded | 0.160 (93/582) / 0.614 (156/254) | 0.161 / 0.602 | — |

Spike comparison (held-out-3, Pi): price accuracy 0.992, item recall 0.888, usable 0.764,
catch 0.971, false reject 0.103.

**Per format** (confirmed labels): `html_list` 8 pages, item recall 0.838, usable 0.633;
`html_cards` 2 pages, item recall 0.800, usable 0.351.

**Corruption per type** (confirmed labels, seed 7):

| Type | n | Caught | Indistinguishable |
|---|---|---|---|
| `invented_item` | 100 | 100 | 0 |
| `mutated_price` | 88 | 88 | 0 |
| `other_section_price` | 71 | 71 | 0 |
| `swapped_prices` | 162 | 157 | 1 |

**False rejects of gold rows by reason** (238): `duplicate_row` 134, `price_not_grounded`
62, `variant_not_grounded` 35, `implausible_amount` 4, `name_not_grounded` 3.

**Loss buckets** (every gold price in one bucket, 778):

| Bucket | Prices | Share |
|---|---|---|
| `accepted` | 486 | 0.625 |
| `item_missed` | 128 | 0.165 |
| `not_accepted:variant_not_grounded` | 59 | 0.076 |
| `wrong_amount` | 52 | 0.067 |
| `not_accepted:price_not_grounded` | 29 | 0.037 |
| `row_unpriced` | 18 | 0.023 |
| `not_accepted:price_bound_to_other_item` | 6 | 0.008 |

**Per page** (draw position, format, gold items / prices, prices lost):

| Page | Pos. | Format | Items | Prices | Lost |
|---|---|---|---|---|---|
| 825659daddd4 | 4 | html_cards | 15 | 32 | 19 |
| 3145210120fa | 5 | html_list | 108 | 133 | 30 |
| 66a3d8e752b9 | 7 | html_list | 15 | 17 | 11 |
| 4b9d6bb201da | 8 | html_list | 413 | 416 | 138 |
| e8dcaff697a6 | 10 | html_cards | 5 | 5 | 1 |
| 63aa447a27c9 | 12 | html_list | 12 | 20 | 0 |
| dab793fcd92e | 15 | html_list | 52 | 83 | 67 |
| f649c257352d | 16 | html_list | 146 | 6 | 1 |
| aded7f07485b | 17 | html_list | 50 | 59 | 23 |
| 4513d1e8a3f7 | 18 | html_list | 6 | 7 | 2 |

**Promo (recorded, not gated):** 15 promo entries on 3 pages (the first set labelled with
the Amendment 5 grain); 5 promo-marked priced rows, all 5 stored as prices
(`promo_rows_stored` 5).

**Run report, run 2** (8 pages, laptop): 40 chunks, 2 sparse retries, 0 truncated, 0
resent, 0 failed; rows accept 215, downgrade 344 (`no_price_extracted` 249,
`price_not_grounded` 83, `price_bound_to_other_item` 6, `variant_not_grounded` 6), reject 7;
3 pages flagged `unlabeled_price_runs`; 513 items and 215 prices written, 14
`unsectioned_items`; JSON-LD pages 0 (run 1's large page wrote a `jsonld` stream too).

**Laptop numbers, not Pi numbers.** 9.0 pages/h model time only over all 10 pages (8,031
chunk-seconds on 2 slots, 3.9 generated tokens/s per slot, consistent with #62's laptop
run); run 2 wall clock 11.2 pages/h including Menu writes (2,567 s for 8 smaller pages).
SoC max **97 °C** (laptop), CPU frequency cap 1.0. `llama-server` 2.6 GiB at one sample
(not a peak measurement). Pi pages/h and peak RAM still come with the owner's Pi check.

## Findings

1. **Price accuracy (0.963) misses on layout, not on the model alone.** 10 of the 19
   accepted wrong prices are one page that prints every price twice (above the name and
   below the description): the model takes the neighbouring item's copy, and the validator
   grounds it because that number is printed nearby. Another 3 are the item-vs-variant
   matching artifact (a dish's protein choices as items). The rest are add-on prices
   accepted as item prices and one two-column grid.
2. **Item recall (0.837)** loses most on the largest page (a five-menu inline layout,
   416 prices, 138 lost) and on a site-builder grid whose text order puts each price before
   the next item's name (83 prices, 67 lost).
3. **Gold-row false rejects (0.306)** are mostly the validator's duplicate rule: its key
   (name, variant, amount, section) has no notion of which of several inline menus a row
   sits in, so a dish repeated at the same price in a second menu is rejected (134). The
   price-before-name grid adds 45 `price_not_grounded`. Without the duplicate rows the rate
   is 0.134 (104/778), or 0.161 with those rows also left out of the denominator.
4. **Menu writes don't scale with page size.** Every Menu table has a deferred constraint
   trigger `ct_menu_integrity` that calls `menu.check_aggregate(page_id)` **once per
   inserted row** at commit, so a page's commit cost grows with the square of its size.
   The largest page's commit (`llm` and `jsonld` streams, over 1,000 rows) ran from 20:51:19
   UTC to between 22:16 and 23:23 UTC: **at least 1 h 25 min**. #62's end-to-end test
   wrote 93 rows and couldn't see it. A fix touches the Menu schema (stop-and-ask); a full
   extraction pass waits for it independently of quality.
5. **Many accepted menu pages print no prices.** 8 of the 18 drawn menu pages show no
   price in their static text (name-only chain menus and similar); they produce items with
   unknown prices only. Usable prices per menu URL will be lower than the spike's sample
   suggested.
6. **Harness limits** found while scoring (not changed here; scores use the harness as
   frozen): rows match gold items by name only, so a dish's options emitted as items match
   a same-named add-on elsewhere; the gold-row false-reject metric counts the validator's
   duplicate rule against rows that are legitimately repeated.

## What this unblocks

Nothing yet. **Extraction runs at scale (laptop or Pi) stay blocked** on (a) a pipeline
version that passes §8 on a fresh held-out set (these 10 pages are now tuning pages) and
(b) a fix for the quadratic Menu-write commit (finding 4). The Pi extraction run also
still waits on the owner-run [llama-server Pi check](./2026-09-29-llama-server-pi-check.md);
Pi gate 1b gates a Pi `resolve_urls` run and Pi gate 1a doesn't gate either. With the
first pass on the laptop (Amendment 8), none of the Pi items blocks the laptop run;
the next held-out draw continues from the same laptop pass with a new seed, excluding
the 18 venues labelled here.
