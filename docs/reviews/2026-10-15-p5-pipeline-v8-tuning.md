# Pipeline version v8: split column headers (fix 1 from the P5-14 findings)

Session P5-15, 2026-10-15. Follows the failed held-out evaluation of v7
([2026-10-15-p5-v7-held-out-evaluation.md](./2026-10-15-p5-v7-held-out-evaluation.md),
ADR-0013 Amendment 16), whose false-reject fail is validator-side. **These are tuning
numbers, not a §8 evaluation.** v8 is not cleared for extraction runs until it passes §8 on a
fresh held-out draw (seed 20261014, below).

Candidate version (model, prompt, chunker, segmenter, repairs code and classifier unchanged;
only the validator's label reader changes, so every page's saved answers stay valid):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v7;validator-v8;classifier-v2
```

Scratch scripts and outputs stay in the worktree's gitignored `var/menu-eval/p5-15/`; this
file keeps counts and rates.

## Owner decision

After the P5-14 cause analysis (425 rejected gold rows put in layout classes, the classes
counted on all six labelled sets), the owner chose **fix 1 only: column headers printed one
label per block**. The other candidates (labels on their own line, numbers inside names,
price text the reader misses, group and header prices, the add-on policy) are not built here.

## The lever

v5's column rule reads a header printed in one block ("16oz / 20oz / Pitcher") over rows that
join their prices with "/" or "|". On four P5-14 pages the table prints every header label and
every price in its own block, so 174 gold rows' variants could not be grounded
(`variant_not_grounded`):

```
each | doz.                      ← the header: one short label per block
Fruit                            ← a row: its name, any description lines,
Apple, Apricot, Blueberry, …     ←   …
$1.60 | $17.60                   ←   then one price per block ("(qty. 10)" notes may sit between)
Cream Cheese | $1.60 | $17.60
```

`validator-v8` (`split_column_label`, read by `label_tokens`, so the repairs' variant check
reads it too): a price printed alone in its block takes, as its label, the header label in its
column. Walking up from the price's row: each earlier row with as many prices is passed over
(its name and description lines between them); the first row's lines start with the header, as
many short label lines (at most 4 words and 24 characters, no price, no comma) as the row has
prices; a description is a sentence or a long list (over 8 words or 60 characters, or ending in
a period), so names such as "Bacon, Egg & Cheese" and "Omelet (Egg, Cheese, Tomato &
Vegetables)" are names. Lines between two rows holding more than one name start a new table, so
a second table reads its own header. The table must hold at least two rows (as v5's
`_heads_rows`). Labels by position keep swapped prices visible. Layout-generic: no site or
platform branching.

## Results (saved answers, amended harness, frozen)

Baseline v7 reproduces P5-13's final v7 table (spike, P5-5, P5-8, P5-10, P5-12) and P5-14's
held-out numbers exactly.

| Set | Item recall | Usable | Price accuracy | Gold FR | Catch |
|---|---|---|---|---|---|
| Spike 33 | 0.914 | 0.865 | 0.996 | 0.014 | 0.989 |
| P5-5 10 | 0.886 | 0.763 | 0.992 | 0.107 | 1.000 |
| P5-8 35 | 0.879 | 0.755 | 0.983 | 0.112 | 0.996 |
| P5-10 35 | 0.868 | 0.749 | 0.997 | 0.087 | 0.997 |
| P5-12 35 | 0.865 | 0.763 | 0.991 | 0.115 | 0.995 |
| **P5-14 35, v7** | 0.883 (2388/2703) | 0.786 (2182/2777) | 0.990 (2272/2295) | 0.153 (425/2777) | 0.991 |
| **P5-14 35, v8** | 0.883 (2388/2703) | 0.785 (2181/2777) | 0.990 (2271/2294) | **0.094** (261/2777) | **0.993** |

- **The five older sets are unchanged, row by row**: on their 148 pages no repaired row and no
  verdict differs between v7 and v8 (every saved answer re-validated with both).
- **P5-14:** gold-row false reject 0.153 → **0.094** (164 rows: the four table pages go from 84
  to 0, 69 to 7, 12 to 4 and 10 to 0 rejected rows). Per format: `html_list` 0.123 → 0.092,
  `price_list` 0.977 → 0.000; the other formats unchanged.
- **Catch:** 0.991 → 0.993 on P5-14 (uncaught trials 14 → 11; the per-type counts move because
  accepting more gold rows changes the trials drawn). On the four changed pages, page by page,
  every seeded trial is caught, and an exhaustive test gives each accepted labelled row every
  other printed price of its item (the price under another column): **0 of 230 accepted**.
- **Real output:** 35 model rows on the kolache price list keep the "each" / "doz." variant the
  model gave them (v7's repairs dropped it as unprinted). One row is lost: the page prints
  "Ham, Egg & Cheese" in two tables, and the model's $5.00 row carries no variant while its other
  rows of that name do; with the header read, $5.00 is the "each" price, so the row is
  `price_belongs_to_other_variant` (usable 2182 → 2181, accepted exact 2272 → 2271).

## Not covered (left for the owner)

- **One-column labels over a section** ("Small (4 slices)" over a deep-dish list of one-price
  rows; "Full Order" over "CHEESE | 11.50" rows): 19 rows on a P5-8 page and 24 on a P5-10 page.
  That is a section-wide label, the same family as group and header prices (candidate 5 of the
  P5-14 analysis), not a split column header; folding it in would widen this lever.
- A size printed on the line under its price ("$17" "375ml": 6 rows on P5-14's sake list).
- The other P5-14 classes (own-line labels, numbers inside names, unread price text, group
  prices, joined-name lists, the "+$" add-on policy).

## Next held-out evaluation (needed before any extraction run)

The P5-14 procedure: **seed 20261014**, drawing from the laptop pass with P5-5's spike
exclusions plus **all 306 venues labelled so far and their sites**
(`var/menu-eval/p5-14/next-draw-exclusions-p5-15.json` in P5-14's worktree, sha256
`b4ba244f4abc399d776efc18d527abb643d7aa1da0901abd740b8a401b80b9ab`); blind labels frozen and
hashed before the first model call; the real extract CLI on a disposable clone upgraded to
`db40e9424cba`; the runtime (Pi or laptop CPU) for the owner to name; scored with the amended
harness. v8's gain on false reject comes from four P5-14 pages; whether the layout recurs is
what the fresh draw tests.
