# Held-out evaluation of menu-pipeline v7 (ADR-0013 §8)

Session P5-14, 2026-10-14 to 2026-10-15: the §8 evaluation that
[Amendment 15](../adr/0013-phase5-menu-pipeline.md#amendment-15-2026-10-14-pipeline-version-v7-tuned-on-the-p5-12-pages-wine-lists-out-of-scope)
item 9 requires before v7 runs extraction, with the P5-12 procedure (Amendments 10, 12
and 14) on a fresh draw from the laptop pass, scored with the harness as amended in
Amendment 15 (wine sections out of scope, leading menu numbers ignored). Version (merged
in #84 / #85 @ `f3e1e14`; main's CI green after it, run 38664703963):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v7;validator-v7;classifier-v2
```

**Result: v7 fails §8 on the false-reject bar.** Price accuracy (0.990), item recall
(**0.883**, the first held-out pass of the recall bar) and corruption catch (0.991) pass;
the false-reject rate on gold rows (**0.153**) misses its bar (≤ 0.12), with its Wilson
interval wholly above it. Blinded adjudication was not run: no label change it could
make reaches the false-reject verdict (finding 3), and label changes can only raise
recall. Per §8 and the owner's answer E4, v7 is not cleared for extraction runs, these 35
pages become tuning pages, and the next version needs another fresh draw.

Measured only: no pipeline, harness, schema, model, dependency or `infra/` change. Page
bodies, labels, outputs and worksheets stay in gitignored `var/menu-eval/p5-14/`; this
file keeps counts and rates. Pages are named by an opaque id (`sha256(record key)[:12]`).

## Owner decisions

The P5-12 answers stand (E1 35 scorable pages; E2 size quotas 14 / 14 / 7 with the fixed
cutoffs small < 176, large ≥ 500; E3 parallel fresh labeller agents, spot-check before
the freeze; E4 point estimates on the pooled pages, Wilson intervals recorded; E5 the
label-free scale run deferred to the Pi). Asked at the start of this session:

| | Question | Answer |
|---|---|---|
| Q1 | Where the extraction runs: the laptop CPU (as P5-8 / P5-10 / P5-12; recommended for comparability) or the Pi | **The Pi** (production host) |
| Q2 | Blinded adjudication: only when label changes could move the verdict, or always | **Only when margins are small** (Amendment 10 item 2) |
| Q3 | If v7 fails on recall again: stop at the record, or draft a model-screen amendment | **Stop at the record** (recall passed; the fail is on false reject) |

## Procedure

**Draw** (`var/menu-eval/p5-14/draw.py`, P5-12's script with P5-12's exclusion list; seed
**20261013**, recorded at 2026-10-15 01:20:42 UTC, before drawing):

- Pool: the extract CLI's due queue on `helios_laptop` (read-only): 1,632 pages.
- Excluded (pages): P5-5's exclusions (spike venues **77**, spike hosts **234**, spike
  URLs **0**) plus the 234 venues labelled in P5-5, P5-8, P5-10 and P5-12 (**234**) and
  their 234 sites (**349**); the list is P5-12's `next-draw-exclusions-p5-13.json`
  (sha256 `0c383cac72ea15f72f204077e353d4c05e8de0d8e50bd8e0ca845144b7e435c1`, checked by
  the script).
- 737 eligible venues, shuffled with the seed; one page per venue, at most one venue per
  site: an order of **577**. `draw.jsonl` sha256
  `7582d7e9e68b50b32dc89b6fc416515fbbcd243e380bae515b87629c48796209`.
- Strata by the bundle's block count over the ordered pages, fixed cutoffs: small < 176
  **294**, medium 176–499 **238**, large ≥ 500 **45**; this draw's own P50 / P90 (171 /
  425) are recorded only.
- Exported in draw order per stratum (first small 34, medium 26, large 12: 72 pages,
  19,678 blocks); every body re-segments byte-for-byte to the bundle's blocks.

**Blind labels.** Five fresh labeller agents (about 3,930 blocks each) labelled from the
segmented blocks (raw HTML for layout only) with P5-12's brief (R1 and R2 included), with
one sentence added: wine, beer and spirits lists are labelled like any other drinks (the
wine scope is applied at scoring, Amendment 15 item 4, so the labels stay usable if wine
comes back). No model call before the freeze. Every label parses with the harness's
`gold_page` and names existing blocks. Spot-check (by the session, as in P5-8 to P5-12),
5 pages across strata and formats, chosen for risk: a 344-item drinks page (wine, beer,
spirits; repeats), the only `html_inline` page (pipe-separated rows, an add-on line), a
bakery page with group prices, a 166-item sushi page with a gluten-free re-listing, and a
36-card page printing one price. Every labelled price is printed by its item (or under
the group heading that prices it), and every printed price outside the labels is an R1 /
R2 copy; all 5 pass. One page is a convention risk, recorded and not changed: the bakery
page applies a "Cupcakes are $6 each" heading and a "Starting at $85 (6") / $115 (8")"
line to the flavour cards below them (the brief's group-price rule), where the P5-8 rule
"a priced heading over a flavour list stays one item" could also be read to apply
(finding 4 shows it doesn't decide the verdict).

Of the 72 labelled pages (4,971 items, 3,610 prices): **42 scorable** menus, **22**
menus that print no prices, **1** menu whose only prices are on its wine list (not
scorable under the wine scope; without it, the page would have been held out instead of
the 7th large page), **7** not menus (all `not_menu`; classifier-v2 precision on the draw
**65/72**, 0.903 [0.813, 0.952]). Held out: the first scorable pages per stratum in draw
order (small 14, medium 14, large 7), positions 1–50, 184, 201 and 220 (this draw has only
45 large pages). Frozen and hashed at **2026-10-15 01:31:11 UTC**; extraction started
01:36:03 UTC.

| Label set | Manifest sha256 |
|---|---|
| Blind (72 pages; no adjudication, so blind = confirmed) | `f684316cf8ded2c238e644603b27234bcad0f6d60c7f5f7e29f7bfb0dc263d5c` |

**Extraction (owner Q1: the Pi).** The real extract CLI on a disposable `TEMPLATE` clone
of `helios_laptop` (`helios_p514_eval`, upgraded on the clone only to `db40e9424cba`,
dropped afterwards; `helios_laptop` stays at `7c2e4b9d1f3a`, owner Q7b), narrowed to the
35 held-out Versions by P5-12's queue wrapper, run from the merged code on the laptop. The
model ran on the **Orange Pi 5 Plus**: the pinned CPU `llama-server` image (`server-b11176`
by digest) with the Compose service's flags, on the Pi override's A76 cores (4–7), as a
container outside the deployed `helios` project (untouched), its model file sha256-checked
before each start; the laptop reached it through an ssh tunnel, and the CLI's own `/props`
check (model file, 2 slots) passed. The laptop pass's data stayed on the laptop (how it
reaches the Pi is still undecided, Amendment 8 item 1): bundles were read from the deploy
directory, raw answers written to a separate store (`var/menu-eval/p5-14/base/`), apart
from the laptop's saved answers of the same extractor version. A first launch was stopped
by a Claude Code restart after the Pi server started and before any model request; the
relaunch ran start to end without a failure. Scored with
`python -m apps.menu_pipeline.evaluate compare|loss|corrupt` and the harness's own
functions, as amended in Amendment 15 and frozen (no harness edits).

**What the Pi changes.** The Pi's greedy answers differ from the laptop CPU's on the same
input (P5-13: 1 of 5 test chunks), so item recall and price accuracy here are Pi numbers
and do not compare one to one with P5-8 / P5-10 / P5-12 (laptop). The failing bar does
not depend on the host: gold-row false reject and corruption catch run the validator on
the labels' own rows, not on model output.

## Results (§8)

| Stage | Metric | Bar | v7, 35 pages [Wilson 95 %] | |
|---|---|---|---|---|
| [4]+repairs+[5] | Exact price accuracy, accepted rows | ≥ 0.98 | **0.990** (2272/2295) [0.985, 0.993] | ✔ |
| [4] | Item recall | ≥ 0.85 | **0.883** (2388/2703) [0.871, 0.895] | ✔ |
| [5] | Injected-corruption catch (gold rows, seed 7) | ≥ 0.97 | **0.991** (1483/1497) [0.984, 0.994] | ✔ |
| [5] | False reject, correct (gold) rows | ≤ 0.12 | **0.153** (425/2777) [0.140, 0.167] | ✗ |
| [1] | Classifier precision on the draw | (S6f evaluation stands) | 65/72 menus | — |
| End to end | Usable prices | recorded | 0.786 (2182/2777) [0.770, 0.801] | — |
| [5] on real output | False reject / catch | recorded | 0.068 (166/2438) / 0.537 (335/624) | — |

v6 on P5-12's 35 pages (laptop, frozen harness, confirmed labels) for comparison: 0.991 /
0.821 / 0.995 / 0.126, usable 0.702; v7's tuning numbers on those pages (laptop, amended
harness): 0.991 / 0.865 / 0.995 / 0.115, usable 0.763.

**Wine scope** (Amendment 15 item 4): the held-out labels hold **140 items / 222
prices** under a wine section on 6 pages, not scored (72 pages: 205 items / 337 prices on
9 pages). One drawn page's only priced section is a wine list, so it is not scorable.

**Per stratum** (price accuracy / item recall / gold-row FR / usable):

| Stratum | Pages | Gold items / prices | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|---|
| small | 14 | 422 / 478 | 0.994 | 0.872 | 0.345 | 0.715 |
| medium | 14 | 925 / 846 | 0.983 | 0.840 | 0.155 | 0.745 |
| large | 7 | 1,356 / 1,453 | 0.992 | 0.917 | 0.089 | 0.833 |

**Per format:**

| Format | Pages | Accuracy | Recall | Gold FR | Usable |
|---|---|---|---|---|---|
| `html_list` | 31 | 0.991 | 0.889 | 0.123 | 0.791 |
| `html_cards` | 2 | 0.939 (46/49) | 0.781 | 0.048 | 0.714 |
| `html_inline` | 1 | 1.000 (6/6) | 0.645 | 0.679 | 0.214 |
| `price_list` | 1 | 0.987 (77/78) | 0.977 | 0.977 | 0.860 |

**Corruption per type** (seed 7):

| Type | n | Caught | Indistinguishable |
|---|---|---|---|
| `invented_item` | 330 | 330 | 0 |
| `mutated_price` | 299 | 298 | 0 |
| `other_section_price` | 292 | 290 | 0 |
| `swapped_prices` | 576 | 565 | 1 |

**False rejects of gold rows by reason** (425 rows, one reason each):
`variant_not_grounded` 210, `price_not_grounded` 199, `name_not_grounded` 8,
`addon_price` 6, `price_bound_to_other_item` 1, `price_belongs_to_other_variant` 1.

**Loss buckets** (every gold price in one bucket, 2,777):

| Bucket | Prices | Share |
|---|---|---|
| `accepted` | 2,183 | 0.786 |
| `item_missed` | 292 | 0.105 |
| `wrong_amount` | 106 | 0.038 |
| `not_accepted:price_not_grounded` | 99 | 0.036 |
| `row_unpriced` | 90 | 0.032 |
| `not_accepted:price_bound_to_other_item` | 3 | 0.001 |
| `not_accepted:name_not_grounded` | 3 | 0.001 |
| `not_accepted:price_belongs_to_other_variant` | 1 | 0.000 |

**Per page** (draw position, stratum, format, gold items / prices, items found, accepted
prices exact, gold rows rejected):

| Page | Pos. | Stratum | Format | Items | Prices | Found | Exact | Gold FR |
|---|---|---|---|---|---|---|---|---|
| 2c17688e7f8c | 1 | small | `html_cards` | 36 | 1 | 27 | 0/0 | 0/1 |
| 49b6a15a40ee | 3 | large | `html_list` | 184 | 184 | 174 | 131/137 | 30/184 |
| 35fde4822b24 | 4 | medium | `html_list` | 38 | 34 | 31 | 27/30 | 2/34 |
| 7356d7ed9c41 | 5 | small | `html_list` | 20 | 12 | 20 | 11/11 | 12/12 |
| 70ab184b5a86 | 8 | medium | `html_list` | 70 | 66 | 62 | 59/59 | 8/66 |
| ff560060a56e | 12 | large | `html_list` | 53 | 66 | 50 | 53/53 | 11/66 |
| 08252ddddbaa | 15 | medium | `html_list` | 55 | 12 | 36 | 2/2 | 12/12 |
| e519479a23b5 | 16 | medium | `html_cards` | 60 | 62 | 48 | 46/49 | 3/62 |
| 4d4f5a0a16cf | 17 | medium | `html_list` | 24 | 4 | 21 | 0/0 | 1/4 |
| ac6a458487e4 | 19 | small | `html_list` | 41 | 45 | 36 | 23/23 | 16/45 |
| 3117830345c5 | 21 | small | `html_list` | 29 | 32 | 28 | 26/26 | 0/32 |
| 4d180e041c68 | 22 | small | `html_inline` | 31 | 28 | 20 | 6/6 | 19/28 |
| 660553fbce60 | 23 | small | `html_list` | 40 | 48 | 36 | 28/29 | 14/48 |
| 3c0cd41446bc | 25 | large | `html_list` | 143 | 173 | 110 | 126/126 | 18/173 |
| 625d957a151c | 26 | medium | `html_list` | 48 | 76 | 39 | 25/25 | 55/76 |
| e845388448b9 | 27 | medium | `html_list` | 67 | 79 | 62 | 71/73 | 0/79 |
| c568b57b5a8d | 28 | small | `html_list` | 31 | 31 | 26 | 26/26 | 0/31 |
| cc66dace4481 | 29 | medium | `html_list` | 66 | 12 | 48 | 12/12 | 0/12 |
| 7882f0804e54 | 30 | small | `html_list` | 32 | 61 | 26 | 43/43 | 10/61 |
| 709f6d9391f4 | 31 | small | `html_list` | 4 | 4 | 4 | 4/4 | 0/4 |
| d27b92a13b76 | 32 | small | `html_list` | 44 | 46 | 42 | 44/44 | 0/46 |
| e084e3998df8 | 33 | medium | `html_list` | 79 | 80 | 70 | 70/70 | 6/80 |
| 8c1055178e09 | 34 | large | `html_list` | 155 | 156 | 130 | 127/129 | 1/156 |
| 7a42a8c2ae51 | 35 | medium | `html_list` | 191 | 172 | 163 | 126/126 | 27/172 |
| 77796540a06c | 36 | small | `html_list` | 28 | 29 | 21 | 19/19 | 0/29 |
| f204b5c8375f | 37 | small | `html_list` | 21 | 27 | 19 | 21/21 | 10/27 |
| 93257cd8584e | 38 | medium | `html_list` | 42 | 47 | 34 | 40/40 | 0/47 |
| 49ed54625592 | 39 | medium | `html_list` | 70 | 70 | 57 | 66/69 | 0/70 |
| c8b69d045b58 | 41 | small | `html_list` | 21 | 28 | 20 | 18/18 | 0/28 |
| 9d810b0b995b | 42 | small | `price_list` | 44 | 86 | 43 | 77/78 | 84/86 |
| de0f1e8f4d75 | 47 | medium | `html_list` | 79 | 88 | 74 | 82/82 | 9/88 |
| d340cd0e443b | 50 | medium | `html_list` | 36 | 44 | 32 | 28/28 | 8/44 |
| 9338a31005b5 | 184 | large | `html_list` | 153 | 185 | 129 | 158/158 | 69/185 |
| b6f269a79d76 | 201 | large | `html_list` | 380 | 402 | 364 | 391/391 | 0/402 |
| e3d80d67c253 | 220 | large | `html_list` | 288 | 287 | 286 | 286/288 | 0/287 |

**Promo (recorded, not gated):** 12 promo entries and 2 promo-marked items on the
held-out pages; 2 promo-marked priced rows stored as prices.

**Run report** (35 pages; the model on the Pi, the CLI and the clone on the laptop):
`extraction run complete`: 35 due, 35 extracted, 0 reused answers, 0 failed, 12 pages
flagged, 3 `jsonld` pages; 314 chunks (313 finished on their own, **1 truncated**), 5
sparse retries, 0 resent. Rows judged: `llm` 2,561 accepted, 542 downgraded unpriced, 420
`price_not_grounded`, 55 duplicate rejects; `jsonld` 163 accepted. Written to the clone:
3,482 Menu items and 2,724 price observations on 38 Menu pages, 241 variants, 459
sections, 9,677 Evidence links.

**Pi numbers.** Wall clock **26,606 s** (7.4 h: 01:36:03 to 08:59:29 UTC), **4.74
pages/h** including Menu writes; **4.8 pages/h** model time only (52,687 chunk-seconds on
2 slots; **1.92** generated tokens/s per slot). Menu writes no longer show in the wall
time (the clone is at `db40e9424cba`). Pi SoC at most **77 °C** (sampled as each page
saved); the CLI's own `soc_max_temp_c` 99 °C is the laptop's sensor, where the CLI ran.
This is not the README's pending `llama-server` Pi check (that compares the image's
tokens/s with the spike's own build; no such comparison was made).

## Findings

1. **Recall passes for the first time on a held-out draw.** Item recall 0.883 [0.871,
   0.895] (v6 on P5-12: 0.821; v5 on P5-10: 0.819; v4 on P5-8: 0.838). Three things moved
   at once and are not separated here: v7's repairs, the scope and harness changes (wine
   lists out, menu numbers ignored: 140 wine items left the denominator), and the Pi's
   greedy answers in place of the laptop's. Medium pages stay under the bar (0.840).
2. **The false-reject fail is the validator reading labelled rows, mostly variants
   printed as column headers.** 210 of the 425 rejected gold rows are
   `variant_not_grounded`, and 174 of those sit on 4 pages that print their variant labels
   once, as a column or table header over the prices: a price list headed "each" /
   "doz." (84 of 86 rows), a sushi table headed "Sushi · 1 pc" / "Sashimi · 3 pc" (68), a
   "PIZZA SIZE" header row (12) and an "Item / Half Tray / Full Tray" header (10); another
   10 are a size line printed on its own between a dish's description and its price
   ("Full Tray (4 - 5 ppl)" over "$27"). Without the
   `variant_not_grounded` rejects, gold-row FR would be 0.077 (215/2777). The labels follow
   the brief (a variant is the printed label that goes with the price), so this is a
   grounding gap, not a labelling slip.
3. **Adjudication skipped (owner Q2; Amendment 10 item 2).** The packet reviews only
   rows where labels and pipeline disagree. Of the 425 rejected gold rows, 75 belong to
   items it would show (69 never matched, 6 with a disputed price); even if every one were
   relabelled away, gold-row FR would be 350/2702 = 0.130, still over 0.12 (it needs 92
   fewer rejected rows). Label changes can only raise item recall (best case 0.918: B rows
   that are not items leave the denominator, C rows that are items join it as found).
   The C-row packet fix (labels within 2 blocks of the claimed block) is built in
   `adjudicate_packet.py` for the next session that needs it.
4. **`price_not_grounded` (199 rows) is spread over layouts already named in earlier
   records:** prices applied from a group heading or a line several blocks above the item
   (the bakery page, 47; it is a labelling-convention risk, but without the page FR is
   0.137, still failing), names that hold a number ("GOBI 65", "SAMBAR VADAI (2 PCS)"), a
   bare integer ending a description line before a mark ("… oregano 16 *"), pipe-separated
   inline rows ("Drip 3.5 / 4.25 | Iced Coffee 4.5 / 5.25"), "each / any three" pairs, and
   one price closing a long list of joined names.
5. **Price accuracy and catch hold.** Accuracy 0.990 on 2,295 accepted rows; catch 0.991
   on gold rows. On real output the validator catches 0.537 of wrong rows (P5-12 v6:
   0.466) and rejects 0.068 of correct ones.
6. **Classifier precision on this draw:** 65 of 72 drawn pages are menus (0.903 [0.813,
   0.952]; P5-12 62/72, P5-10 67/72, P5-8 66/72): 7 not menus (among them a "loading menu"
   shell, menu hubs of category tiles or tab names, a nutrition-header page). Recorded, not
   gated.
7. **Many menu pages print no prices:** 22 of 65 drawn menu pages (34 %; P5-12 26 %,
   P5-10 33 %).
8. **Throughput on the Pi:** 4.8 pages/h model time (P5-13's Pi run: ~4.4), 1 truncated
   chunk, SoC ≤ 77 °C, no run failures; Menu writes are linear on the upgraded clone.

## What this unblocks

Nothing yet. **Extraction runs (laptop or Pi) stay blocked** on a pipeline version that
passes §8 on a fresh held-out draw: these 35 pages are now tuning pages, next to the
spike's 33, P5-5's 10, P5-8's 35, P5-10's 35 and P5-12's 35 (P5-14's 37 labelled but
unscored pages stay unseen). For the owner at the next tuning session: the failing bar is
validator-side (variants printed as column headers above all; then the `price_not_grounded` layouts
in finding 4), the side earlier sessions could tune without re-running the model; and
whether the Pi or the laptop CPU is the evaluated runtime from now on (this draw's recall
is a Pi number).

**Next draw:** seed **20261014**, the P5-5 spike exclusions plus **all 306 venues
labelled so far** (P5-5 18, P5-8 72, P5-10 72, P5-12 72, P5-14 72) **and their 306 sites**
(`var/menu-eval/p5-14/next-draw-exclusions-p5-15.json`, sha256
`b4ba244f4abc399d776efc18d527abb643d7aa1da0901abd740b8a401b80b9ab`). The pool shrinks:
this draw had 737 eligible venues and 577 ordered pages (45 large); the next one has at
most 665 eligible venues.

**Scale run: still deferred to the Pi** (Amendment 10 item 5), on the version that
passes §8.
