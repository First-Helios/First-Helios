# Page-classifier precision check (ADR-0013 §8, stage [1])

Session P5-27, 2026-10-20. The owner opened this check after P5-26 (Q-C): pool every held-out
draw's page labels and test `classifier-v2` against §8's precision bar (≥ 0.95). This is the
[classifier gap audit](./2026-10-12-p5-classifier-gap-audit.md)'s R1 sample, part (a), built from
labels that already exist. Measured and proposed only: no pipeline, harness, schema, model,
dependency or `infra/` change, no Pi access, and nothing deleted.

**Result: `classifier-v2` misses the §8 precision bar on the laptop pass.**
- 413 of the 450 drawn pages are menus: **0.918 [0.889, 0.940]** (Wilson 95 %).
- Weighted by the frame's size strata: **0.915 [0.889, 0.941]**.
- Both upper bounds are below 0.95. That meets the gap audit's trigger for step 3 (a
  replacement survey): "precision whose Wilson upper bound is below 0.95".

The gap is all in **small pages** (fewer than 176 blocks):

| Stratum | Precision |
|---|---|
| Small | 0.855 [0.802, 0.896] |
| Medium | 0.975 [0.938, 0.990] |
| Large | 0.973 [0.908, 0.993] |

Of the 37 non-menu pages:
- 20 are a restaurant's own menu hub or homepage;
- 5 are menu URLs whose menu never reaches the page text;
- 10 are not restaurant pages at all;
- 2 are judgement calls.

Only the 10 off-domain pages wrote prices into Menu (92 prices, 0.40 % of the sample's prices).
Recall is still unmeasured.

## 1. Data

| Draw | Record | Seed | Pages labelled | Labels-blind manifest verified |
|---|---|---|---|---|
| P5-5 | 2026-09-30 held-out | 20260930 | 18 | ✔ |
| P5-8 | v4 held-out | 20261008 | 72 | ✔ |
| P5-10 | v5 held-out | 20261010 | 72 | ✔ |
| P5-12 | v6 held-out | 20261012 | 72 | ✔ |
| P5-14 | v7 held-out | 20261013 | 72 | ✔ |
| P5-16 | v8 held-out | 20261014 | 72 | ✔ |
| P5-26 | v9 held-out | 20261015 | 72 | ✔ |
| **Pooled** | | | **450** | |

Each draw takes one page per venue and site from the laptop pass's due queue, with every
earlier draw's venues and sites excluded. So the 450 pages are 450 distinct venues and sites.

- **Labels:** each draw's frozen blind labels, checked against its `labels-blind.sha256` (450/450
  OK). Fields used: `page_label`, item prices and the labeller's note. P5-8, P5-10 and P5-12 were
  read from the merged-worktree archives (`var/archive/2026-10-merged-worktrees/`); P5-14 and
  P5-16 from `var/menu-eval/corpus/`.
- **Label vocabulary:** the held-out labelling brief's page labels (P5-26 used P5-16's copy): `menu`, `not_menu` (a
  homepage, about, locations or catering-inquiry page, or a hub that only links to menus) and
  `empty` (no usable text). This matches the classifier's training convention (S6f).
- **Classifier probability:** each page's `menu_page.confidence` in `helios_laptop` after the v9
  pass. Extraction recomputes it from the bundle with `classifier-v2`
  (`apps/menu_pipeline/extraction.py:441`). All 450 pages score at or above the threshold
  (0.508), so the queue's fetch-time verdicts reproduce.
- **Strata:** the fixed cutoffs (small < 176 blocks ≤ medium < 500 ≤ large). P5-5's 18 pages
  carry no stratum in their draw, so their block counts were read from the bundles.
- **Frame:** P5-5's site-deduplicated draw order, 811 pages: small 406, medium 322, large 83.
  It is the due queue (1,632 pages) minus the spike's venues and sites, one page per site.
  Precision over the whole queue isn't measured; chain sites with several pages count once here.

## 2. Precision

| Draw | Small | Medium | Large | Menus with prices | Menus without prices | `not_menu` | `empty` | Precision [Wilson 95 %] |
|---|---|---|---|---|---|---|---|---|
| P5-5 | 10/10 | 5/5 | 3/3 | 10 | 8 | 0 | 0 | 1.000 [0.824, 1.000] |
| P5-8 | 28/34 | 26/26 | 12/12 | 46 | 20 | 6 | 0 | 0.917 [0.830, 0.961] |
| P5-10 | 31/34 | 25/26 | 11/12 | 45 | 22 | 5 | 0 | 0.931 [0.848, 0.970] |
| P5-12 | 25/34 | 25/26 | 12/12 | 46 | 16 | 8 | 2 | 0.861 [0.763, 0.923] |
| P5-14 | 28/34 | 26/26 | 11/12 | 43 | 22 | 7 | 0 | 0.903 [0.813, 0.952] |
| P5-16 | 33/34 | 25/26 | 12/12 | 48 | 22 | 2 | 0 | 0.972 [0.904, 0.992] |
| P5-26 | 28/34 | 25/26 | 12/12 | 50 | 15 | 7 | 0 | 0.903 [0.813, 0.952] |
| **Pooled** | **183/214** | **157/161** | **73/75** | **288** | **125** | **35** | **2** | **0.918 [0.889, 0.940]** |
| Per stratum | 0.855 [0.802, 0.896] | 0.975 [0.938, 0.990] | 0.973 [0.908, 0.993] | | | | | |

The per-stratum cells are menus out of pages labelled. This table also gives R2's page-level
counts for every draw.

- **Stratified estimate:** 0.915, 95 % [0.889, 0.941]. Weights are the frame's shares: 0.501
  small, 0.397 medium, 0.102 large. Since P5-8, every draw has exported a fixed quota of 34 / 26 /
  12, which oversamples the large stratum relative to the frame. Re-weighting moves the estimate
  by 0.003.
- **Against the bar:** the pooled count would need 6 more menus (419/450) before its Wilson
  upper bound reached 0.95, and 24 more (437/450) before its lower bound did.
- **Against the recorded estimate:** the classifier's spike nested CV read 40/41 = 0.976
  [0.874, 0.996]. That sample was small, and it was the training distribution.
- **Draws vary as sampling would:** 0.861 to 1.000. P5-16's 2 non-menus and P5-12's 10 sit on
  either side of the pool.

## 3. What the 37 non-menu pages are

Every page was sorted from its labeller's note and URL. "Items" and "Prices" are what v9 wrote
into Menu for the page.

| Kind | Pages | Strata (S / M / L) | Items | Prices | Median p | Examples |
|---|---|---|---|---|---|---|
| Restaurant's own menu hub or homepage: category tiles or links, no dishes | 20 | 20 / 0 / 0 | 87 | 0 | 0.72 | `chick-fil-a.com/menu`, `redrobin.com/menu`, `fiveguys.com/menu/`, `steaknshake.com/` |
| Menu URL whose menu never reaches the page text (JS loader, image-only, empty bundle) | 5 | 5 / 0 / 0 | 0 | 0 | 0.66 | `vazquez3.com/en/menu/breakfast` ("Cargando menú..."), `whollycowburgers.com/menu.html`; 2 bundles with 0 blocks |
| Not a restaurant page: retail, grocery, equipment, pet food, tourism, blogs, listicles, an SEO post | 10 | 4 / 4 / 2 | 185 | 92 | 0.78 | `yeti.com/kitchen` (26 prices), `atxrestaurantequipment.com` (19), `gandhi-bazar.com` (10), a McDonald's price post on `frankiespizzaandpasta.com` (36) |
| Labeller's judgement call | 2 | 2 / 0 / 0 | 128 | 0 | 0.99 | An unpriced Thanksgiving catering package list; a custom-cake flavour menu |

Findings from the sort:

1. **Hubs explain the small-stratum gap.** The 20 menu hubs are all small, and most sit in
   the lower half of the accepted range (median p 0.72). They are the S6f convention's own
   negatives ("hubs, home, locator and similar pages are `not_menu`"), so these are classifier
   errors, not a labelling mismatch. They write no prices. The 87 items they write are category
   names and tile captions.
2. **Off-domain pages are the only source of wrong prices.** Ten pages wrote 92 prices. Those
   are 0.40 % of the 22,776 prices v9 wrote for all 450 pages; non-menu pages also wrote 1.05 %
   of the items. One of them, a blog post about another brand's prices, wrote 36 McDonald's prices
   under Frankie's Pizza and Pasta. Retail and grocery pages wrote product prices as menu prices.
3. **Five menu URLs accept a static page that holds no menu.** The fetch accepts the static
   page, so it never reaches the render path, which only a rejected page takes
   (`page_bronze.py:393–399`). These are menus the pipeline loses: a recall loss that shows up as a
   precision error. Two bundles have 0 blocks and still score 0.66 and 0.71. With no text,
   their score comes from the URL and layout features.
4. **Sensitivity to label calls.** Counting the 2 judgement calls as menus gives
   0.922 [0.894, 0.944]. Adding the 5 unrendered pages gives 0.933 [0.906, 0.953]. Even on that
   most generous reading, the lower bound stays below 0.95, and precision isn't shown to clear
   the bar.

## 4. Threshold alone (in sample, not a result)

A higher threshold over these 450 pages:

| Threshold | Pages kept | Precision [Wilson 95 %] | Labelled menus dropped (of 413) |
|---|---|---|---|
| 0.508 (shipped) | 450 | 0.918 [0.889, 0.940] | 0 |
| 0.6 | 439 | 0.929 [0.902, 0.950] | 5 |
| 0.7 | 415 | 0.947 [0.921, 0.965] | 20 |
| 0.8 | 385 | 0.966 [0.943, 0.980] | 41 |
| 0.9 | 352 | 0.972 [0.949, 0.985] | 71 |
| 0.95 | 324 | 0.991 [0.973, 0.997] | 92 |

- **Cost:** 41 of the labelled menus score below 0.8: 28 small, 8 medium and 5 large; 16 of them
  print prices.
- **Not a fair test:** a threshold picked on this table is tuned on it, so it would need a fresh
  sample (§8: "a held-out set … used for tuning is no longer held out").
- **Recall:** dropping menus that are already accepted is a recall cost, and the size of the
  classifier's existing recall loss is still unknown (§5).

## 5. What this check can't measure

- **Recall.** Every page here passed the classifier. Recall needs pages the classifier
  *rejected*: the gap audit's R1(b) sample, from skipped `not_menu` / `js_only` Captures and
  discovery's rejected candidates. No such labels exist.
- **The whole queue.** The frame excludes the spike's venues and sites, and keeps one page per
  site.
- **Effect on §8 extraction numbers: none, by construction.** Held-out sets are the first
  scorable menus per stratum (gap audit §2.4). v9's pass is unaffected.

## For the owner

- **Q1. Record the miss.**
  - §8 judges the classifier on its S6f evaluation (P5-26 finding 4). This check is the first
    measurement on the production distribution, and it shows the bar is not met.
  - Options:
    - (a) Record it as a known gap of v9. The data written stays, and a classifier fix ships as
      a later pipeline-version bump.
    - (b) Treat v9's Menu writes as provisional until a classifier that clears the bar
      re-interprets the pages.
- **Q2. Next step for the classifier.** The gap audit's step 3 replacement survey, now
  triggered:
  - leave-one-set-out over these 450 pages plus the spike labels;
  - candidates: retrained `classifier-v2` features with the new negatives, other generic
    features, a threshold;
  - followed by a fresh page-level sample (R1(a) size: about 260–440 pages) to verify;
  - the same session would label R1(b) rejected pages, for recall.

  A new classifier or feature set is an ADR-0013 amendment, proposed before any build.
- **Q3. Unrendered menu URLs (finding 3).** Should an accepted static page with no menu text
  still trigger the render? That is a fetch change (§4) for its own PR, with Pi render cost to
  measure.
- **Q4. Rows already written.** Nothing is deleted or withdrawn here.
  - The 10 off-domain pages' 92 prices are in `helios_laptop`, each with its page confidence.
  - Across the whole pass, the non-menu pages aren't identified; only the sampled ones are.

## Reproduce

The script and its outputs are in the main checkout's gitignored
`var/audits/p5-27-classifier-check/`:

| File | sha256 |
|---|---|
| `check.py` | `358f19f3ecdb31edd436abd6e091ecfe53ac7c4121c65d0a9b65b2c00ceecf90` |
| `pages.jsonl` (one row per page: draw, URL, stratum, label, note, p, rows written) | `c5b00f31e2916093ac7b21cf7311055fae84af9e3e9c2a24d6d993e8fffe4715` |
| `summary.json` | `5876b3a948d3c82a337d24352e7b90c6a405e2ba6c06cfb28669c646b07187e9` |

The archived draws are unpacked under `src/` in that folder. Run from the main checkout, with
the `menu` extra:

    uv run --extra menu --env-file .env python var/menu-eval/p5-26/with_db.py helios_laptop \
        var/audits/p5-27-classifier-check/check.py

## Verification

Measured only; no code changed. `make ci` runs on the branch before the commit; see the PR.
Database tests are skipped here (no PostgreSQL `*_test` database), so this is not database
acceptance.
