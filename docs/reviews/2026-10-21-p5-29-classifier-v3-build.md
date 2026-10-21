# `classifier-v3` build and the R1(a) / R1(b) samples (ADR-0013 Amendment 24)

Session P5-29, 2026-10-21. This carries out [ADR-0013 Amendment 24](../adr/0013-phase5-menu-pipeline.md)
under the owner's rulings Q1–Q5: `classifier-v3` is built but not shipped, and the two
verification samples are collected. Nothing is labelled and no verdict is reached here; that is
P5-30.

Scope:
- no pipeline-version bump, and no change to the live verifier (`WEIGHTS_PATH`,
  `resolve_urls` and `page_bronze` are unchanged; `classifier-v2` stays live);
- no schema, migration, ORM model, dependency or `infra/` change, and no Pi access;
- `helios_laptop` was only read (`set transaction read only`). The re-crawl writes no database
  row;
- nothing was deleted.

**Result:**
- **The build checks pass.** The threshold reproduces the survey's exactly: 0.6737975804204388,
  against the survey's 0.6738. The plain-Python scorer agrees with scikit-learn within
  6.99e-7 on all 695 pages, inside the 1e-6 bound.
- **R1(a) is frozen at 361 pages**, one per site (small 192, medium 161, large 8).
  `classifier-v2` accepts all 361; `classifier-v3` rejects 16 of them.
- **R1(b) is short of the planned resolved stratum.** It re-crawled 102 venues: 100
  `no_menu_found` and 2 resolved, plus the laptop pass's one skipped Capture. Only 3 resolved
  venues (2 sites) are outside every labelled or R1(a) site; the plan had about 50. See Q1.
  - **R1(b) has 102 venues, 136 distinct pages and 5 disagreements.**
  - The re-crawl took **32 min 49 s**, sequential at 1 request per second per host.
  - 6 venues failed at the site level.
  - The label queue is 106 pages: 5 disagreements, 100 of the 126 pages both reject, and the
    skipped Capture.
  - All 4 pages that v3 adds come from one venue's site.

## 1. Part A: `classifier-v3`

### What was built

| File | Change |
|---|---|
| `packages/helios_parsing/page_features.py` | `page_signals(html, url, blocks)` and `PAGE_SIGNAL_NAMES`: the survey's 11 signals, stdlib `html.parser` only, unchanged in behaviour |
| `apps/menu_pipeline/classifier.py` | `ClassifierWeights.features` comes from the weights file: `layout_features`, plus `page_signals` when the file names them (any other list is refused). `page_vector_inputs(html, url, features)` computes the named inputs |
| `apps/menu_pipeline/train_page_classifier.py` | `--draw` (repeatable: a draw's `draw.jsonl` and frozen `labels-blind/`, read from its bundles with `page_html`, as extraction scores them), `--bundle-root`, `--signals`. Groups join venue and site. The shipped fit uses the survey's page order, and the scorer is checked on every page |
| `config/page_classifier_v3.json` | the weights: 256 embedding dimensions + 7 layout features + 11 signals, threshold 0.6737975804204388 |
| `apps/menu_pipeline/record_candidates.py` | Part C's record-only re-crawl (section 3) |
| `test/` | signals on synthetic HTML; v3 loads, keyed on its feature list; v2 stays the live weights; a scorer keyed on a signal; the recorder on a mock transport |

- **No site, platform or brand rule.** The signals are link and markup statistics, schema.org /
  Open Graph types and two shop phrases ("add to cart / bag / basket").
- **No new runtime dependency.** The embedding model (`potion-base-8M`) and the scorer are
  unchanged; scikit-learn 1.9.1 stays ephemeral (`uv run --with`).
- **The live verifier is unchanged.** `WEIGHTS_PATH` still names
  `config/page_classifier_v2.json`. `classifier-v3` is loaded only by path, with
  `load_page_classifier(weights_path=...)`.
- **Groups.** Union-find over venue and site. A group is named by its smallest member key, so
  fold assignment doesn't depend on page order. On the survey's pool this naming gives the same
  threshold as the survey's own labels.

### Build checks

| Check | Required | Result |
|---|---|---|
| Ported signals and inputs reproduce the survey's `pool.jsonl` (sha256 `3695041a…`, 695 pages) | identical | **max \|Δ\| 0.0** for signals, layout features and embedding, all 695 pages |
| Threshold by the precision-0.95 rule on all 695 pages | 0.674 (survey 0.6738) | **0.6737975804204388** ✔ |
| Plain-Python scorer vs scikit-learn's `predict_proba` | within 1e-6 | **max \|Δ\| 6.99e-7** over all 695 pages ✔ |
| Training pool | 695 pages, 502 menus | 695 pages, 502 menus, 531 groups; draws 18 + 6 × 72 |

- The remaining 7e-7 comes from the embedding, not the regression. Training embeds pages in
  batches, while the scorer embeds one text at a time, and the ONNX model's float32 output
  differs slightly between the two. The old check covered 20 pages with the same bound; this
  one covers every page.
- **Page order matters a little.** With the survey's order and naming, the threshold is
  identical. A shuffled page order moves it to 0.67366, which still rounds to 0.674. The
  trainer therefore keeps the survey's order (static pages, rendered pages, then draws).
- **Standardized coefficients of the plain features** (the embedding's 256 are not listed):

  | Feature | Coef | Feature | Coef |
  |---|---|---|---|
  | log_body_blocks | +0.788 | link_text_share | −0.285 |
  | priced_block_share | +0.365 | log_anchors | +0.407 |
  | log_money_tokens | +0.465 | anchors_per_block | −0.136 |
  | log_priced_blocks | +0.387 | chrome_block_share | −0.433 |
  | words_per_block | −0.288 | money_per_100_words | +0.411 |
  | short_block_share | +0.142 | child_link_share | −0.358 |
  | heuristic_menu_signal | +0.617 | log_child_links | −0.333 |
  | | | cart_markup | −0.204 |
  | | | product_markup | −0.123 |
  | | | article_markup | **+0.371** |
  | | | log_article_tags | −0.339 |

  `article_markup` came out positive, although the survey meant it as an off-domain sign. It is
  recorded, not tuned. The P5-28 survey's leave-one-set-out results stand as the selection
  evidence; the trainer's legacy report sections (the spike's first-export nested CV, the S6f
  held-out set) are not a held-out evaluation of v3.

Reproduce (P5-29 worktree, with the spike labels extracted into `var/`):
`bash var/audits/p5-29-classifier-v3/train_v3.sh` and
`PYTHONPATH=. uv run --extra menu python var/audits/p5-29-classifier-v3/check_features.py`.

## 2. Part B: R1(a), the precision sample

- **Frame.** P5-5's site-deduplicated draw order (811 due pages of `helios_laptop`, sha256
  `3f2a3c6d…`). Spike venues, sites and URLs were already out. Then:
  - 355 pages were dropped for a labelled venue and 95 for a labelled site
    (`next-draw-exclusions-p5-27.json`, sha256 `3439a961…`);
  - a re-check against the spike's venues, sites and URLs dropped nothing more.

  **361 sites remain: small 192, medium 161, large 8**, as expected. Each is one venue and
  one site.
- **Still due.** Every frame page is checked against `due_pages` under P5-5's method version: the
  latest Version of a resolved record, with the same Version id and bundle. All 361 match.
- **Order.** Sorted by record key, then shuffled with seed **20261021**. All 361 are taken
  (owner Q2).
- **Export.** Each page's HTML (`pages/`) and blocks (`blocks/`, `bNNNN | text`). For all 361
  pages the HTML (utf-8) segments exactly to the bundle's stored blocks.
- **Hidden scores.** These are kept outside the labeller folder, at
  `var/audits/p5-29-classifier-v3/r1a-scores.jsonl`. Every page is scored from its bundle exactly
  as extraction scores it, with `classifier-v2`, `classifier-v3` and S4 (URL path trusted, as
  the survey did):

  | Stratum | Pages | v2 accepts | v3 accepts | S4 accepts |
  |---|---|---|---|---|
  | Small | 192 | 192 | 179 | 189 |
  | Medium | 161 | 161 | 158 | 160 |
  | Large | 8 | 8 | 8 | 8 |
  | **All** | **361** | **361** | **345** | **357** |

  v2 accepting all 361 is expected, because every due page passed v2 when it was fetched. The 16
  pages v3 rejects are where R1(a) measures menus lost against v2. The 345 it keeps give v3's
  precision.
- **Frozen.** `var/menu-eval/p5-29-r1a/manifest.json` (sha256 `f7106a74…`) lists the sha256 of
  `draw.jsonl` (`d4978f37…`), `draw-summary.json`, `LABELLING.md`, all 361 pages and blocks, both
  weights files and the hidden scores file.
- **Labelling brief** (`var/menu-eval/p5-29-r1a/LABELLING.md`):
  - page labels only: `menu` with `priced` true or false (menu with prices / menu without
    prices), `not_menu` with a `kind`, or `empty`;
  - the S6f convention that hubs which only link to menus are `not_menu`;
  - no item rows;
  - an `uncertain` flag for judgement calls;
  - labellers work only inside the folder and never see a probability or verdict. The folder
    holds none.

  The `not_menu` kinds follow P5-27's sort: `hub`, `homepage`, `other_own_site`, `off_domain`,
  `menu_not_in_text`.

## 3. Part C: R1(b), the record-only re-crawl

### Method

- **Enumeration is discovery's own.** `record_candidates` calls
  `SiteFetcher.discover_menu_attempt` with a `RecordingVerifier` as the page check. The
  verifier keeps every page discovery hands it and accepts none, so discovery goes on through
  every candidate it ranks:
  - its own-site candidates (well-known paths, sitemap and homepage links), up to 8;
  - the homepage's ordering-platform links, up to 3 hosts and 3 chain pages each.

  The live run stops at the first accepted page. Accepting none makes the recorded set a
  superset of what either v2 or v3 would check as the live verifier. Each row keeps the
  candidate's rank, whether it is a platform page, and whether its body equals the homepage's.
  With those, the live behaviour of either verifier can be replayed from the record.
- **No database.** The module opens no session and writes no Bronze, Menu or other row. It
  writes only files under `--out`.
- **Etiquette is discovery's.** It uses the same `SiteFetcher`:
  - robots.txt is checked on every hop, and Crawl-delay is honoured;
  - 1 request per second per host;
  - the Helios User-Agent (`resolve_urls._USER_AGENT`);
  - the 3 MB cap and the same-site redirect and public-address rules.

  It used a fresh cache directory and ran as one sequential process, so the per-host limit
  holds across venues that share a platform host. There was no rendering.
- **Kept per page** (`var/audits/p5-29-classifier-v3/r1b-crawl/`): the body (`pages/`), the
  final URL, and the `classifier-v2` and `classifier-v3` probabilities and verdicts. Also S4,
  both with the URL path trusted and with discovery's own `trust_path`.

### Venues (seed 20261022)

`var/menu-eval/p5-29-r1b/select_venues.py` reads `helios_laptop` and selects from 9,996 current
venues. Excluded are:
- the spike's venues and sites;
- the S6f render set's venues and sites;
- the 450 labelled draw venues and sites;
- R1(a)'s 361 venues and sites.

A venue is out when its website's site or any of its menu URLs' sites is excluded.

| Pool | Before exclusion | Excluded venue / site | Eligible venues (sites) | Taken |
|---|---|---|---|---|
| `no_menu_found` (latest discovery Capture of the website) | 2,798 | 102 / 348 | 2,348 (1,559) | **100** |
| resolved menu URL | 1,634 | 888 / 743 | **3 (2)** | **2** |

- **Why the resolved pool is empty.** Every resolved venue outside the spike shares a site with
  P5-5's 811-page frame: the 811 are one per site over all of them. All 811 sites are now
  either labelled (450) or in R1(a) (361). The two left are `coreanostx.com` and an amazon.com
  grocery page.
- One venue per site, in seeded order. `venues.jsonl` sha256 `30dd6758…`.
- **The skipped Capture.** The laptop pass has exactly one skipped `not_menu` menu-page Capture
  with a bundle: an amazon.com grocery category page. Its blocks match its bundle. v2, v3 and S4
  all reject it. It is the menu URL of resolved venue #102, so the re-crawl may also reach it.
  The queue keeps one copy.

### Crawl

Run 2026-10-21 01:21:40 → 01:54:29 UTC (**32 min 49 s** wall time; 1,969 s summed over
venues), laptop, one process:

    PYTHONPATH=. uv run --extra menu python -m apps.menu_pipeline.record_candidates \
        --venues var/menu-eval/p5-29-r1b/venues.jsonl --out var/audits/p5-29-classifier-v3/r1b-crawl \
        --weights config/page_classifier_v2.json --weights config/page_classifier_v3.json \
        --model-root /home/fortune/CodeProjects/First-Helios/var/models

| Venue outcome (discovery's own reason) | Venues |
|---|---|
| Enumeration ran; no page accepted (`no_menu_found`, by construction) | 90 |
| Enumeration ran; a chain homepage's platform links matched no single address (`PlatformAmbiguous`) | 6 |
| **Failed: `non_public_host`** (website resolves to a non-public address) | 2 |
| **Failed: `robots_unavailable`** (robots.txt 5xx or unreachable: site skipped) | 2 |
| **Failed: `http_403`** | 1 |
| **Failed: `network_error`** | 1 |
| **All** | **102** |

- **Failures by reason:** 6 of 102 venues: `non_public_host` 2, `robots_unavailable` 2,
  `http_403` 1, `network_error` 1. No robots-disallowed site, and no crash.
- **Pages.** 47 venues gave at least one candidate page (a 200 HTML page distinct from the
  homepage). In the rest, every candidate was missing or not HTML, which is why discovery
  found nothing there before. The 139 checks are 136 distinct pages: one venue's `/menu/`
  was reached twice.

| Pages by verdict | v2 rejects | v2 accepts |
|---|---|---|
| **v3 rejects** | 127 (126 `no_menu_found`, 1 skipped Capture) | **1** (resolved, large) |
| **v3 accepts** | **4** (`no_menu_found`, medium) | 4 (3 resolved, 1 `no_menu_found`) |

- **Disagreements (5), as URLs only (no labels yet):**
  - **v3 adds 4.** All four are from one venue (#11). They are product pages on one Italian
    shop's site (`friscoshop.it/products/…-menu-…`), with v3 at 0.88–0.94 and v2 at 0.05–0.09.
    The product names contain "menu".
  - **v3 drops 1.** It is an amazon.com search page (`/s?srs=…`, v2 0.928, v3 0.505) reached
    from resolved venue #102.
- **Both accept (4, not labelled under the plan):**
  - `coreanostx.com/menu/`;
  - amazon.com's grocery category page, re-fetched now (v2 0.969, v3 0.725). The skipped
    Capture's 2026-10-02 body scores below both thresholds. The bodies differ, so both stay;
  - `zorbagreekrestaurant.com/menu`. Discovery recorded `no_menu_found` for this venue in the
    laptop pass, but both verifiers accept the page now.

### Label queue

| Queue part | Pages | Verdict pair | Pool and stratum |
|---|---|---|---|
| Disagreement census | 5 | v2 0 / v3 1: 4; v2 1 / v3 0: 1 | `no_menu_found` medium 4; resolved large 1 |
| Skipped `not_menu` Capture | 1 | v2 0 / v3 0 | `skipped_capture`, medium |
| Both reject, random 100 of 126 (seed 20261022) | 100 | v2 0 / v3 0 | `no_menu_found`: small 94, medium 6 |
| **Queue** | **106** | 0/0: 101; 0/1: 4; 1/0: 1 | small 94, medium 11, large 1 |

- The both-reject population is only 126 pages, so the 100-page sample covers 79 % of it.
- **Weights for P5-30.** The `no_menu_found` stratum sampled 100 of 1,559 eligible sites, a
  weight of about 15.6 per site. The resolved stratum sampled 2 of 2. Under the Amendment 24
  recall rule, v3's 4 added pages count for about 62 in the population. They come from a
  single site, so that estimate rests on one cluster.

Frozen: `var/menu-eval/p5-29-r1b/crawl-manifest.json` (sha256 of every crawl file and page),
`queue-summary.json` (counts, the labeller folder's manifest and the hidden key's sha256). The
labeller folder `var/menu-eval/p5-29-r1b/label/` holds `queue.jsonl` (in shuffled order), pages,
blocks and `LABELLING.md`. That is R1(a)'s brief plus `js_only` (survey §6). The key (pool,
stratum, verdicts) is in the hidden `var/audits/p5-29-classifier-v3/r1b-queue-key.jsonl`.

## 4. Where the artefacts are

Everything under `var/` is gitignored. It sits in this session's worktree
(`.claude/worktrees/p5-29-classifier-v3-build/var/`), because this session could not write into
the main checkout:

| Path | What |
|---|---|
| `var/menu-eval/p5-29-r1a/` | R1(a): `r1a.py`, `draw.jsonl`, `draw-summary.json`, `LABELLING.md`, `pages/`, `blocks/`, `manifest.json` |
| `var/menu-eval/p5-29-r1b/` | R1(b): `select_venues.py`, `venues.jsonl`, `venues-summary.json`, `skipped_capture.py`, `queue.py`, `LABELLING.md`, `crawl-manifest.json`, `queue-summary.json`, `label/` |
| `var/audits/p5-29-classifier-v3/` | hidden from labellers: `train_v3.sh`, `check_features.py`(`.json`), `classifier-v3-report.json`, `r1a-scores.jsonl`, `r1b-crawl/`, `r1b-queue-key.jsonl` |

Before the worktree is removed, copy them to the main checkout:
`cp -a .claude/worktrees/p5-29-classifier-v3-build/var/{menu-eval/p5-29-r1a,menu-eval/p5-29-r1b,audits/p5-29-classifier-v3} …`.
The R1(b) crawl cache (`r1b-crawl/site-cache/`) can stay behind.

## Verification

`make ci` (lockfile, lint, strict mypy over the repo including these `var/` scripts, pytest):
pass (lockfile, lint, typecheck; pytest 694 passed, 727 skipped). Database tests are skipped here (no PostgreSQL `*_test` database), so this is not
database acceptance.

## For the owner

Each question carries the context needed to answer it here.

- **Q1. R1(b)'s resolved stratum has 2 venues, not about 50. Fill it from R1(a)'s venues?**
  - **Context.**
    - Amendment 24 (owner Q4) asked for about 50 resolved venues outside every labelled venue
      and site and outside R1(a)'s 361 sites.
    - Every resolved venue outside the spike shares a site with P5-5's 811-page frame, which
      takes one page per site over all of them. Those 811 sites are now either labelled (450)
      or in R1(a) (361). So only 3 venues (2 sites) qualify, and both were taken.
    - The resolved stratum is where the recall rule's other side lives. Among resolved sites,
      v3 can reject the page v2 accepted (R1(a) finds 16 such pages) but then accept another
      candidate on the same site, a page v2's run never reached.
    - The `no_menu_found` stratum can't show that: v2 found nothing on those sites.
  - **Options:**
    - (a) **Add a resolved stratum from R1(a)'s venues.** Re-crawl a seeded random 50 of the
      361 R1(a) venues, record-only, with the same script; it takes about 15 minutes. Label
      their v2/v3 disagreements and a both-reject sample. A page already in R1(a) is not
      labelled twice. Q2's rule makes classifier labels exclude venues from later *classifier*
      samples, so sharing sites between R1(a) and R1(b) breaks no rule; it only means the
      labels for those sites come from both samples. (Recommended.)
    - (b) Re-crawl all 361 R1(a) venues: a census, about 1 h 50 min of crawl, and more
      disagreements to label.
    - (c) Keep R1(b) as collected. The recall bar is then judged on the `no_menu_found`
      stratum and 2 resolved venues only.
- **Q2. R1(b)'s new admissions come from a single site. Widen the `no_menu_found` stratum?**
  - **Context.**
    - 100 venues gave 136 pages. Only 47 venues had any candidate page: discovery's
      `no_menu_found` sites mostly 404 on every candidate.
    - v3's only 4 additions are 4 product pages of one shop. Weighted to the population (about
      15.6 per site), that is about 62 pages, from one cluster.
    - The recall rule ("menus v3 adds ≥ menus it drops") and the precision of v3's admissions
      both rest on this.
  - **Options:**
    - (a) **Re-crawl about 200 more `no_menu_found` venues** (seed order continued from
      `select_venues.py`, about 65 minutes). Label only their v2/v3 disagreements; the
      both-reject sample is already 100 pages. (Recommended.)
    - (b) Keep 100 venues and judge on what they show.
