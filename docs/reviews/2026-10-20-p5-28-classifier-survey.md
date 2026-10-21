# Page-classifier replacement survey (ADR-0013 §8, Amendment 23 item 3)

Session P5-28, 2026-10-20. This is the [classifier gap audit](./2026-10-12-p5-classifier-gap-audit.md)'s
step 3, which the [P5-27 check](./2026-10-20-p5-27-classifier-check.md) triggered. It is a
leave-one-set-out comparison of generic candidates to replace `classifier-v2`.

Measured and proposed only:
- no classifier, weights file, R4 or sample is built;
- no pipeline, schema, dependency or `infra/` change;
- no Pi access, and nothing deleted.

The proposal is [ADR-0013 Amendment 24](../adr/0013-phase5-menu-pipeline.md), accepted by the owner (see Owner decisions).

**Result: retraining with the new negatives clears 0.95 as a point estimate; a threshold change
alone does not.** Pooled over the seven held-out draws (450 pages, each scored by a model that
never saw its draw):

| Candidate | Precision [Wilson 95 %] | Stratified | Labelled menus lost (of 413) | Prices on lost menus |
|---|---|---|---|---|
| `classifier-v2` (shipped) | 0.918 [0.889, 0.940] | 0.915 | — | — |
| S4 heuristic | 0.920 [0.891, 0.942] | 0.916 | 9 | — |
| (c) v2, threshold re-picked | 0.936 [0.909, 0.956] | 0.931 | 17 | 25 |
| (a) v2 inputs, retrained | **0.961** [0.937, 0.976] | 0.957 | 22 | 156 |
| (b) (a) + generic page signals | **0.957** [0.932, 0.972] | 0.953 | 17 | 12 |

- **Proposed: (b).** It matches (a) on precision and loses fewer menus. Those menus carry almost
  none of the written prices, and (b) has the better recall on the other two sets.
- **No candidate is shown to clear 0.95.** Every lower bound is below the bar, and small pages
  still read 0.913 under (b).
- **The draws can't see new admissions.** Every drawn page had already passed `classifier-v2`,
  so a page that v2 rejected and a candidate would accept is invisible here. Inside the spike
  set, which looks like discovery's candidate pages, (b) accepts 7 of 131 non-menus against 5
  for v2's configuration.
- The fresh samples (Amendment 23 item 3) therefore have to measure both directions. Two
  constraints shape them: the frame has only 361 unlabelled sites left, and the pass rule needs
  a decision (owner questions below).

## 1. Data

| Set | Pages | Menus | Non-menus | Source |
|---|---|---|---|---|
| `spike` | 188 | 57 | 131 | Spike labels (`git archive origin/spike/menu-model spikes/menu_model/labels`), first and second export, `menu` / `not_menu` only (`js_only` and `empty` excluded, as in S6d) |
| `rendered` | 57 | 32 | 25 | S6f laptop render: probe 46 (23 menus) and held-out 11 (9 menus), `menu` / `not_menu` only |
| P5-5 | 18 | 18 | 0 | Draw labels (frozen blind), bundles from `draw.jsonl` |
| P5-8 | 72 | 66 | 6 | " |
| P5-10 | 72 | 67 | 5 | " |
| P5-12 | 72 | 62 | 10 (2 `empty`) | " |
| P5-14 | 72 | 65 | 7 | " |
| P5-16 | 72 | 70 | 2 | " |
| P5-26 | 72 | 65 | 7 | " |
| **All** | **695** | **502** | **193** | |

- **Draw pages** are read from their bundles exactly as extraction scores them (`page_html`,
  `bundle.url`). Each recomputed `classifier-v2` probability matches P5-27's `pages.jsonl` to
  within 5e-5, so all 450 sit at or above 0.508. `empty` counts as not a menu, as in P5-27.
- **S6f rendered labels.** They are not in `var/archive/2026-10-merged-worktrees/s6f-page-rendering.tar.zst`:
  its manifest lists only the five `potion-base-8M` files. They are on disk at
  `var/archive/worktrees/s6f-page-rendering/render-measure/laptop/`. That copy is byte-identical
  (`diff -r`) to the location the S6f record names
  (`var/spikes/menu-model/render-probe-2026-09-29/s6f/laptop-run2/`). The S6f numbers reproduce:
  probe 21/23 menus accepted with 1 false positive, held-out 8/9.
- **Venues and sites.** No draw venue or site appears in `spike` or `rendered`. 18 rendered
  probe venues are spike venues.
- **Strata:** the fixed cutoffs (small < 176 blocks ≤ medium < 500 ≤ large), on all segmented
  blocks.

## 2. Method

- **Folds.** Nine sets; each is held out once. The training pool is the other eight sets, minus
  any page sharing a venue or a site with the held-out set (19 pages drop when `spike` is held
  out, 41 for `rendered`, none for a draw). Inner cross-validation is a 5-fold `GroupKFold`.
  Groups join pages that share a venue or a site.
- **Configuration**, from `train_page_classifier.py` unchanged: `StandardScaler`, logistic
  regression with `C = 0.5`. The threshold is the lowest whose out-of-fold precision over the
  training pool reaches 0.95, picked inside each fold and never on the held-out set.
  scikit-learn 1.9.1 is ephemeral (`uv run --with`), as in the training script.
- **Candidates:**
  - **`v2`:** `config/page_classifier_v2.json` as shipped, threshold 0.508.
  - **S4:** `page_menu_signal(html, url)` with the URL path trusted, as the classifier's feature
    uses it.
  - **(c):** v2's weights, with the threshold re-picked by the rule on the training pool's v2
    probabilities.
  - **(a):** v2's 263 inputs, the `potion-base-8M` embedding of `page_text` plus the 7 layout
    features, retrained.
  - **(b):** (a) plus 11 generic page signals, all computed with the standard library's
    `html.parser`:
    - link text as a share of visible text;
    - the log of the anchor count;
    - anchors per body block;
    - the share of blocks that are chrome;
    - money tokens per 100 words;
    - the share and log count of same-host links one level below the page's path;
    - add-to-cart / add-to-bag text or attributes;
    - schema.org Product markup or `og:type` product;
    - Article / BlogPosting markup, `og:type` article or `rel=author`;
    - the log count of `<article>` and `<time>` elements.

  None of these names a site, a platform or a brand.
- **Runtime.** Every candidate is a logistic regression over plain features. The scorer stays the
  plain-Python one in `classifier.py`, on the same pinned embedding model, with no new
  dependency.

## 3. Results per held-out set

Precision (menus accepted / pages accepted):

| Held-out set | `v2` | S4 | (c) | (a) | (b) |
|---|---|---|---|---|---|
| `spike` ¹ | 1.000 (57/57) | 0.640 (48/75) | 1.000 (57/57) | 0.694 (50/72) | 0.703 (52/74) |
| `rendered` | 0.967 (29/30) | 0.615 (8/13) | 0.964 (27/28) | 0.967 (29/30) | 0.909 (30/33) |
| P5-5 | 1.000 (18/18) | 1.000 (18/18) | 1.000 (16/16) | 1.000 (17/17) | 1.000 (18/18) |
| P5-8 | 0.917 (66/72) | 0.915 (65/71) | 0.917 (66/72) | 0.912 (62/68) | 0.914 (64/70) |
| P5-10 | 0.931 (67/72) | 0.930 (66/71) | 0.939 (62/66) | 0.970 (65/67) | 0.969 (63/65) |
| P5-12 | 0.861 (62/72) | 0.861 (62/72) | 0.857 (60/70) | 0.935 (58/62) | 0.923 (60/65) |
| P5-14 | 0.903 (65/72) | 0.913 (63/69) | 0.968 (60/62) | 0.984 (62/63) | 0.969 (62/64) |
| P5-16 | 0.972 (70/72) | 0.985 (67/68) | 0.986 (68/69) | 0.984 (63/64) | 0.985 (67/68) |
| P5-26 | 0.903 (65/72) | 0.900 (63/70) | 0.941 (64/68) | 0.970 (64/66) | 0.969 (62/64) |
| **Draws pooled** | 0.918 [0.889, 0.940] | 0.920 [0.891, 0.942] | 0.936 [0.909, 0.956] | **0.961** [0.937, 0.976] | **0.957** [0.932, 0.972] |

Recall (menus accepted / labelled menus), with labelled menus lost against `v2`:

| Held-out set | `v2` | S4 | (c) | (a) | (b) |
|---|---|---|---|---|---|
| `spike` ¹ | 1.000 (57/57) | 0.842, −9 | 1.000, −0 | 0.877, −7 | 0.912, −5 |
| `rendered` | 0.906 (29/32) | 0.250, −24 | 0.844, −2 | 0.906, −1 | **0.938**, −1 |
| P5-5 | 1 ² | 1.000, −0 | 0.889, −2 | 0.944, −1 | 1.000, −0 |
| P5-8 | 1 ² | 0.985, −1 | 1.000, −0 | 0.939, −4 | 0.970, −2 |
| P5-10 | 1 ² | 0.985, −1 | 0.925, −5 | 0.970, −2 | 0.940, −4 |
| P5-12 | 1 ² | 1.000, −0 | 0.968, −2 | 0.935, −4 | 0.968, −2 |
| P5-14 | 1 ² | 0.969, −2 | 0.923, −5 | 0.954, −3 | 0.954, −3 |
| P5-16 | 1 ² | 0.957, −3 | 0.971, −2 | 0.900, −7 | 0.957, −3 |
| P5-26 | 1 ² | 0.969, −2 | 0.985, −1 | 0.985, −1 | 0.954, −3 |
| **Draws pooled** | 1 ² | 0.978, −9 | 0.959, −17 | 0.947, −22 | 0.959, −17 |

Labelled menus lost against S4 (menus S4 accepts that the candidate rejects), pooled over the
draws: `v2` 0, (c) 16, (a) 20, (b) 16; on `rendered`: `v2` 3, (c) 4, (a) 3, (b) 2.

¹ **The `spike` row compares nothing fairly.** `v2` and (c) were fit on the spike, so they are
in sample. (a) and (b) are trained here without any of the spike's 131 easy negatives
(homepages, about pages, locators): the draws hold only pages v2 already accepted. A shipped
candidate trains on the spike too. The supplement below is the fair reading.

² **Recall on the draws is 1 by construction.** Every drawn page passed `classifier-v2`, so a
draw measures only the menus a candidate *loses* against v2.

**Supplement: the spike set inside its own 5-fold group split, with every other set always in
training.** `v2cfg` is v2's configuration refit on the spike's training folds only.

| | Precision [Wilson 95 %] | Recall | Non-menus accepted (of 131) |
|---|---|---|---|
| `v2cfg` | 0.911 [0.807, 0.961] | 0.895 (51/57) | 5 |
| (a) | 0.852 [0.743, 0.920] | 0.912 (52/57) | 9 |
| (b) | 0.883 [0.778, 0.942] | 0.930 (53/57) | 7 |

This is the population discovery verifies: candidate pages from a venue's site, about two-thirds
of them not menus. Adding the draw pages makes both retrained candidates more accepting there.
The training pool becomes 72 % menus, and the precision-0.95 rule picks its threshold on that
mix. The counts are small (5, 7 and 9 of 131, inside each other's intervals), but every
difference points the same way.

### Per size stratum

Pooled over the draws, precision [Wilson 95 %]:

| Stratum | `v2` | S4 | (c) | (a) | (b) |
|---|---|---|---|---|---|
| Small | 0.855 (183/214) [0.802, 0.896] | 0.855 (177/207) | 0.881 (170/193) | 0.922 (165/179) [0.873, 0.953] | 0.913 (168/184) [0.863, 0.946] |
| Medium | 0.975 (157/161) [0.938, 0.990] | 0.975 (155/159) | 0.981 (154/157) | 0.994 (155/156) | 0.994 (155/156) |
| Large | 0.973 (73/75) [0.908, 0.993] | 0.986 (72/73) | 0.986 (72/73) | 0.986 (71/72) | 0.986 (73/74) |

Menus lost (small / medium / large): (c) 13 / 3 / 1, (a) 18 / 2 / 2, (b) 15 / 2 / 0.

Per held-out set for (b) (precision `v2` → (b), then (b)'s recall):

| Set | Small | Medium | Large |
|---|---|---|---|
| `rendered` | 0.857 → 0.875, R 7/8 | 1.000 → 0.909, R 20/21 | 1.000 → 1.000, R 3/3 |
| P5-5 | 1.000 → 1.000, R 10/10 | 1.000 → 1.000, R 5/5 | 1.000 → 1.000, R 3/3 |
| P5-8 | 0.824 → 0.812, R 26/28 | 1.000 → 1.000, R 26/26 | 1.000 → 1.000, R 12/12 |
| P5-10 | 0.912 → 0.964, R 27/31 | 0.962 → 1.000, R 25/25 | 0.917 → 0.917, R 11/11 |
| P5-12 | 0.735 → 0.821, R 23/25 | 0.962 → 1.000, R 25/25 | 1.000 → 1.000, R 12/12 |
| P5-14 | 0.824 → 0.929, R 26/28 | 1.000 → 1.000, R 25/26 | 0.917 → 1.000, R 11/11 |
| P5-16 | 0.971 → 1.000, R 30/33 | 0.962 → 0.962, R 25/25 | 1.000 → 1.000, R 12/12 |
| P5-26 | 0.824 → 0.929, R 26/28 | 0.962 → 1.000, R 24/25 | 1.000 → 1.000, R 12/12 |

All candidates and all cells are in `survey.json` (see Reproduce).

### Thresholds picked inside the folds

| Held-out | (c) | (a) | (b) |
|---|---|---|---|
| `spike` | 0.714 | 0.592 | 0.368 |
| `rendered` | 0.707 | 0.712 | 0.406 |
| P5-5 | 0.699 | 0.803 | 0.603 |
| P5-8 … P5-26 | 0.606–0.708 | 0.658–0.716 | 0.624–0.766 |
| **All 695 pages** (the value a build would ship) | 0.682 | 0.694 | **0.674** |

The low (b) thresholds in the `spike` and `rendered` folds come from training pools without the
spike's easy negatives.

## 4. What changes on the 37 drawn non-menus

The kinds are P5-27's sort, from the labellers' notes:

| Kind (P5-27) | Pages | Still accepted by (c) | (a) | (b) | Prices written (v9) still accepted, (a) / (b) |
|---|---|---|---|---|---|
| Menu hub, homepage, or menu URL whose menu never reaches the text | 25 | 18 | 10 | 12 | 0 / 0 |
| Off-domain (retail, grocery, blog, listicle, tourism) | 10 | 7 | 4 | 4 | 20 / 20 (of 92) |
| Judgement call | 2 | 2 | 2 | 2 | 0 / 0 |
| **Total** | 37 | 27 | 16 | 18 | |

- **Hubs.** The retrained candidates drop about half of the hubs: Culver's, Five Guys, Rosa's,
  Steak 'n Shake, Veracruz, Carillon. Chain hubs with category tiles and teaser copy stay at about
  0.88 or above: Chick-fil-A, Red Robin, True Food, PJ's, 7 Brew, Marco's, Golden Chick. Neither the
  child-link signals nor link density separates them from short menus.
- **Off-domain pages.** Both (a) and (b) drop the McDonald's blog post (36 prices), Yeti (26),
  Gandhi Bazar (10), the POS-vendor and Freddy's blog posts, and the pet-food page. That removes
  72 of the 92 wrong prices. Four stay accepted:
  - the restaurant-equipment shop (19 prices);
  - PureWow's listicle;
  - the tourism directory;
  - El Arroyo's retail salsa product page (1 price). `v2` scored it 0.60; (a) and (b) score it
    0.997.

  The cart and product signals carry small weights and don't remove the shop.
- **Empty bundles.** Of the two 0-block bundles, (b) keeps both (0.99 and 0.89) and (a) keeps one.
  With no text, the URL and layout features decide. Amendment 23 item 4 (render an accepted page
  with no menu text) covers them.

**The menus (b) loses** (17 of 413) are mostly small, unpriced chain or category pages:
Krispy Krunchy, NY Pizzeria, Freshii smoothies, Kung Fu Tea, Taco Bueno, Lucky Duck and Scooter's.
Four print prices, and v9 wrote 12 prices for them. (a) loses 22, among them Salt Traders (94
prices written) and Meridian Buda (40), for 156 prices. Under R4, a page the new classifier
rejects has its Menu rows retracted, so these lost prices are a real cost.

## 5. Choice and its risks

**Proposed: (b) as `classifier-v3`, threshold by the existing rule on all 695 labelled pages
(0.674 here).** Against (a):
- equal precision within noise: 0.957 against 0.961, 2 pages apart;
- 5 fewer menus lost, and 12 lost prices against 156;
- better recall on `rendered` (30/32 against 29/32) and inside the spike (53/57 against 52/57);
- fewer spike non-menus admitted (7 against 9).

It costs a stdlib feature function, 11 more features, and 2 more rendered non-menus accepted
(Starbucks' rendered menu hub, a DoorDash business page).

Risks to state before any build:

1. **Precision is not shown to clear 0.95.** The point estimate does; the Wilson lower bound
   (0.932) does not. The small stratum stays at 0.913.
2. **Recall against v2 may fail the §8 bar** ("recall ≥ the previous verifier's"). (b) gives up
   4.1 % of v2's accepted menus (17/413). It has to win at least as many back among pages v2
   rejects. On `rendered` it wins 1 net, and inside the spike 2. On the production distribution
   that is unmeasured.
3. **New admissions are unmeasured** (the spike supplement). The draws only contain pages v2
   accepted.
4. **The training mix sets the threshold.** The pool is 72 % menus, while discovery's candidates
   are mostly non-menus. The rule is unchanged here, as the brief asks. If the fresh samples show
   too many admissions, the next lever is the rule's training mix, not a per-page rule.

A threshold alone, (c), stays below the bar (0.936) and loses as many menus as (b). It is not
proposed.

## 6. Fresh-sample plan (for Amendment 24)

### R1(a): precision on due pages

- **Frame:** `helios_laptop`'s due pages, one page per site in P5-5's draw order, minus the spike's
  venues and sites and `next-draw-exclusions-p5-27.json`'s 450 venues and sites. That leaves
  **361 sites: small 192, medium 161, large 8.**
- **The constraint.** Amendment 23 asked for about 260–440 pages, but only 361 sites remain, and
  any page labelled now is lost to future extraction draws (35 pages each) under the current
  exclusion rule. Options are in Q2.
- **Design:** stratified by the fixed cutoffs with a fresh seed, page-level labels only (menu with
  prices / menu without prices / `not_menu` / `empty`), no item rows. Score `classifier-v2`,
  `classifier-v3` and S4 on every page.
  - Precision is (b)'s accepted pages that are menus, weighted by the frame's strata.
  - The pages (b) rejects give the menus lost against v2.
- **Power.** If (b)'s true precision is 0.957, a Wilson lower bound ≥ 0.95 is reached with
  probability 0.07 at 260 pages and 0.10 at 440, and about 3,700 pages would be needed. A point
  estimate ≥ 0.95 is reached with probability 0.74–0.80 (260–440 pages). If true precision is
  0.93, a point estimate reaches 0.95 with probability 0.06–0.12. The pass rule is Q1.

### R1(b): recall and new admissions among rejected pages

- **Population.** The laptop pass kept almost no rejected bodies. It has 1 skipped `not_menu`
  menu-page Capture (with bundle), and 2,425 venues whose discovery ended `no_menu_found`, with
  no candidate bodies kept.
- **Collection.** R1(b) needs discovery's candidate enumeration re-run in a record-only mode:
  - on the laptop, with the Helios User-Agent, robots.txt and the per-host rate limit;
  - no Bronze or Menu writes;
  - keep each candidate's body, URL and the `classifier-v2`, `classifier-v3` and S4 verdicts;
  - a random sample of `no_menu_found` venues and of venues with a resolved menu URL, both
    outside the excluded venues and sites;
  - plus the skipped Capture.
- **Labels:** page level, as R1(a), plus `js_only`.
  - Every page where v2 and v3 disagree is labelled (a census). Those pages alone decide the
    recall difference and measure the precision of v3's new admissions.
  - A random sample of pages both reject is labelled too, for absolute recall.
- **Recall rule (§8).** v3's recall is at least v2's when, over R1(a) and R1(b) weighted by their
  populations, the menus v3 adds (v2 rejects, v3 accepts) are at least the menus it drops (v2
  accepts, v3 rejects).
- **Precision.** v3's overall precision weights R1(a)'s kept pages and R1(b)'s new admissions by
  their population counts.
- **Venues.** The re-crawl's venues are new to every labelled set. They are excluded from later
  classifier samples.

## For the owner

Each question has the context needed to answer it here; the amendment repeats the decisions.

- **Q1. What does the fresh sample have to show for precision?**
  - **Context.**
    - §8 says "precision ≥ 0.95".
    - P5-27 called v2's miss when the Wilson *upper* bound fell below 0.95.
    - The extraction bars are judged on point estimates with intervals recorded. For example,
      v9's FR passed at 0.097 with a [0.050, 0.156] interval.
    - Section 6's power numbers: a lower-bound rule fails a 0.957 classifier about 90 % of the
      time at any feasible size. A point-estimate rule passes it 74–80 % of the time and
      fails a 0.93 one 88–94 % of the time.
  - **Options:**
    - (a) **The stratified point estimate ≥ 0.95, with its interval recorded.** This matches the
      extraction bars. (Recommended.)
    - (b) The Wilson lower bound ≥ 0.95, which needs about 1,500–3,700 pages at this precision
      and a larger frame.
    - (c) Point ≥ 0.95 and lower bound ≥ 0.90.
- **Q2. Where do the R1(a) pages come from?**
  - **Context.** 361 unlabelled sites remain in the laptop pass (8 large). Future extraction
    held-out draws need about 35 fresh pages each, from the same frame, under the rule that
    excludes every labelled venue.
  - **Options:**
    - (a) **Page-level classifier labels don't exclude a venue from later extraction draws.**
      They hold no item rows, so they can't tune the extractor. R1(a) then takes all 361 sites,
      or a 260-site stratified subset. (Recommended: all 361; at about 330 accepted pages the
      point estimate's standard error is 0.011.)
    - (b) Keep the exclusion rule, label about 260 sites, and leave about 100 sites (about three
      draws) for extraction.
    - (c) Wait for the first Pi monthly run, to widen the frame.
- **Q3. (b) or (a)?**
  - **Context.** They are equal on precision (0.957 against 0.961).
    - (b) loses fewer menus (17 against 22) and far fewer written prices (12 against 156). It
      admits fewer spike non-menus (7 against 9), but 2 more rendered ones.
    - (a) needs no new feature code: only a new weights file.
  - (b) is proposed. (a) is the smaller build.
- **Q4. R1(b) needs a record-only discovery re-crawl.** This is new code in a later session: a
  flag or script that enumerates candidates without writing, run on the laptop. Approve the
  collection method and a size? The proposal: about 150 venues (roughly 100 `no_menu_found`
  and 50 resolved), all disagreement pages labelled, plus 100 pages that both versions reject.
- **Q5. Order of the build.** The proposed order:
  1. R1(a) and R1(b) are labelled against a *built but unshipped* `classifier-v3` (weights in a
     branch, verifier unchanged);
  2. then the verdict;
  3. then the pipeline-version bump that ships v3 with R4.

  The alternative ships v3 and R4 first and verifies afterwards. That retracts rows before the
  bar is known.

## Owner decisions (2026-10-20)

Recorded as [ADR-0013 Amendment 24](../adr/0013-phase5-menu-pipeline.md) (accepted).

| | Answer |
|---|---|
| Q1 | **Point estimate.** R1(a) passes on the stratified point estimate ≥ 0.95, with its Wilson interval recorded. |
| Q2 | **All 361 sites.** Page-level classifier labels don't exclude a venue from later extraction draws. Classifier samples exclude classifier-labelled venues. |
| Q3 | **(b)**, `classifier-v3` with the generic page signals. |
| Q4 | **Record-only re-crawl**, about 150 venues (about 100 `no_menu_found`, 50 resolved). Every v2/v3 disagreement is labelled, plus about 100 pages both reject. |
| Q5 | **Verify first.** Build v3 unshipped with the re-crawl script, label R1(a) and R1(b), reach the verdict, then ship v3 with R4 in one pipeline-version bump. |

## Reproduce

The scripts and outputs are in the main checkout's gitignored `var/audits/p5-28-classifier-survey/`:

| File | sha256 |
|---|---|
| `build.py` (labelled pool, v2 probabilities, S4, v2 inputs, signals) | `b21c0a488f514f8f499692b59604090ffe2997f640fe9e5415a45e3280b3e6fb` |
| `signals.py` (the 11 generic signals, stdlib only) | `7f047076b4ef5728a6c33aa0377820960ed1c3eed9fc9164aae4c4cae341d376` |
| `survey.py` (leave-one-set-out, the spike supplement, full-pool thresholds) | `205e2925513584f180001a70449a4befcb08ac826623068ab646249333e477de` |
| `pool.jsonl` (695 pages) | `3695041a9f46a7d3a88c3dece5736aa1cd0a8da52268c6b09e3f992f50f886da` |
| `survey.json` | `c5d9e65a250888fc7efbbbd18b2fadd326fc1cee504a9ec6124e8ef020e22382` |
| `verdicts.jsonl` (per page: probabilities and each candidate's verdict) | `8ebc182a2032a7770951e0597c8896889f9640181b70aa2c1372375754f1b547` |

Run from the session worktree (it holds the extracted spike labels), with the `menu` extra and
the pinned `potion-base-8M` under the main checkout's `var/models/`. No database is used:

    S=/home/fortune/CodeProjects/First-Helios/var/audits/p5-28-classifier-survey
    PYTHONPATH=. uv run --extra menu python $S/build.py                         # about 70 s
    PYTHONPATH=.:$S uv run --with scikit-learn==1.9.1 python $S/survey.py       # about 3 s

## Verification

Measured only; no code changed. `make ci` runs on the branch before the commit; see the PR.
Database tests are skipped here (no PostgreSQL `*_test` database), so this is not database
acceptance.
