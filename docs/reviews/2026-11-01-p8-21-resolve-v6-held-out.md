# §8 held-out evaluation of resolve-v6 with validator-v10 (P8-21)

Session P8-21, 2026-11-01. The §8 held-out re-test owed since resolve-v4 (P8-14), for
`resolve-v4` → `resolve-v6` and `validator-v9`/`validator-v10`. It used a fresh draw from
P8-20's new page texts.

**Result: every §8 bar passes.** The two bars P8-14's held-out failed (price accuracy and
gold-row FR, under resolve-v4 and validator-v8) both pass now. Separately, the page check's
precision on this draw is 0.90, below the 0.95 bar (see Finding).

Version (`main` at `92c85fb`, the code serving `helios_laptop` and the Pi):

```
qwen3-4b-instruct-2507-q4_0@e0ba675d86ab;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v9;validator-v10;resolve-v6;classifier-v2+v3
```

Measured only: no pipeline, harness, schema, model or `infra/` change, and no database
written. The extraction was not re-run: the extractor version is unchanged since P8-20's
laptop GPU pass, so the production saved answers were scored. Page bodies, labels and
outputs stay untracked in `var/p8-21/heldout/` (worktree `p8-21-q7`). This file keeps only
counts and rates. Pages are named by `text_hash[:12]`.

## Procedure

**Pool** (`hopool.py`, `helios_laptop` read-only):
- Every `menu-page` record's latest Version: 3,190 records, 3,057 live (resolved, not
  rejected, with a bundle).
- Kept only texts first observed in P8-20's re-collection, with no Version of the same text
  before 2026-10-28: 1,879 records. Every dev and earlier held-out text predates that date, so
  this excludes them by construction.
- Minus every text hash in any labelled, traced or measured set, found by a broad scan of
  `var/menu-eval/` and every session worktree's `var/` (9,311 hashes): 1,825 records, 1,029
  distinct texts, all with saved answers.
- Minus pages on the P8-21 coverage-set hosts and Santopatio (46 hosts, 13 texts), and any
  page whose 12-hex id appears in the P8-20/P8-21 scratch files (none): **1,016 texts**.

**Draw** (`hodraw.py`, frozen before labelling):
- Seed **20261101**, shuffled, at most one page per host: 50 pages, 10,519 blocks.
- `draw.json` sha256 `69477dca038abe043dbc623a3288ad294fa338eb932087d06118be862cd09efd`.
- Every page re-segments byte for byte to its bundle's blocks.

**Blind labels.**
- 10 sonnet labellers, each in a private folder with only the brief and its pages' blocks
  (about 1,050 blocks each). None saw pipeline output.
- **The brief** (sha256 `6d18ea5f…`): P8-14's (P5-26's rules), with the owner's labels-v10 and
  v10.1 rulings written in:
  - add-ons (labels-v10 Q4, v10.1 Q1 (a)–(e)) go to an unscored `addons` list, replacing the
    older "add-on on its own line is an item" conventions;
  - coded dish names follow v10.1 Q2.

  The label conventions therefore match the dev labels the versions were tuned on.
- **Completeness check** (`holabelcheck.py`, page text only): 3 pages flagged, all explained
  by the text:
  - option surcharges ("+$1") inside dish names on a page with no item prices;
  - "$39" repeated in promo prose;
  - a blog that repeats "$9.99" and prints "save $5.00" amounts.
- **Session spot-check before the freeze** (page text only), one correction: `8f8d184b3a81`
  gained "Kids entree $6.49" (b0047), a priced choose-one tray (convention (d)) the labeller
  had left out. A soup labelled by its heading ("Sopas / Soups", Cup 8.00 / Bowl 11.00, no
  other name printed) was kept.
- **Frozen:** 50 labels, manifest sha256
  `358f2d71189963b1b50ee0c998da05ecb7b9186b46cfb0823679127de8e47a96`.
- **Pages:** 45 menus and 5 not menus (2,278 items in all); 34 scorable (with a priced gold
  item).

## §8 bars (`evaluate report prod`)

| Bar | Result | |
|---|---|---|
| Item recall ≥ 0.85 | **0.895** (1,600 / 1,787) | pass |
| Price accuracy ≥ 0.98 | **0.995** (1,268 / 1,274) | pass |
| Gold-row FR ≤ 0.12 | **0.072** (115 / 1,606); page-clustered [0.038, 0.110]; 0.992 of resamples ≤ 0.12 | pass |
| Corruption catch ≥ 0.97 | **0.999** (1,362 / 1,364) | pass |
| Usable prices ≥ 0.74 (Amendment 21) | **0.772** (1,240 / 1,606); page-clustered [0.670, 0.878] | pass |

- FR is 0.073 on `html_cards` pages (10) and 0.071 on `html_list` pages (24). The worst page
  is `6a4355546100` at 0.375 (18 / 48); no single page dominates as Dahlia Café did in P8-14.
- Accepted rows matching no label: 243. Real-output wrong-price accepts: 6.
- **[5c] section bar** (`evaluate sections prod`): gated exact **0.940** [0.893, 0.975]
  against 0.85, pass. All pages 0.874. Gated pages: 23 better, 0 worse. Invariance broken on 0
  pages.

**Margins.**
- Usable prices' page-clustered interval crosses its bar: lower bound 0.670 against 0.74.
- 34 scorable pages is slightly under the usual 35.
- The FR interval lies wholly below its bar, so no label adjudication was needed under
  Amendment 10 item 2's trigger.

## Finding: page-check precision on this draw

All 50 drawn pages were accepted by the production verifier (`classifier-v2+v3`). Five are not
menus, so precision is **45 / 50 = 0.90** (Wilson [0.786, 0.957]). That is below §8's 0.95 page
bar as a point estimate; the interval reaches it.
- The five: a coffee brand's recipe article, a chain's press release (dishes only in prose),
  a menu-directory hub, a chain's category-tile hub, and a ticketed beer-dinner product page.
- The classifier's ship check (Amendments 27 and 30) measured its precision on other draws.
  This draw is P8-20's new texts, which reach deeper own-site pages (several pages per venue,
  ADR-0022), so hubs and articles are more common.
- Not acted on here. A verifier change is the owner's call. Rejected pages cost extraction
  time but add no gold prices (four of the five yield no items).

## Artefacts (untracked, `var/p8-21/heldout/` in worktree `p8-21-q7`)

- **Scripts:** `hopool.py`, `hodraw.py`, `holabelcheck.py`, `hofreeze.py`.
- **Pool:** `seen-hashes.txt`, `pool.json`, `pool-kept.json`, `pool-exclusions.json`.
- **Set:** `set/` (`draw.json` + `.sha256`, `pages/`, `blocks/`, `extract/prod/`,
  `labels-blind/`, `labels-blind.sha256`).
- **Labelling:** `label/` (the brief, `deal.json`, L01–L10), `labelcheck.txt`,
  `corrections.txt`, `freeze.txt`.
- **Outputs:** `report.txt`, `sections.txt`.
