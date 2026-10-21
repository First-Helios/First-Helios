# Page-classifier training-mix survey (ADR-0013 Amendment 25, owner Q2 and Q3)

Session P5-31, 2026-10-21. This carries out the lever the owner picked on the P5-30 record
([2026-10-21-p5-30-classifier-v3-verdict.md](2026-10-21-p5-30-classifier-v3-verdict.md), Q2 (a)).
Discovery's labelled candidate pages join the page-classifier pool as a set of their own, and the
P5-28 leave-one-set-out survey is re-run with the same candidates and threshold rule. It also
measures whether a fresh sample can be drawn (owner Q3), and proposes Amendment 26.

Scope:
- measured and proposed only. No classifier, weights file, R4 or sample is built, and
  `classifier-v2` stays the verifier;
- no schema, migration, ORM model, dependency or `infra/` change, and no Pi access;
- `helios_laptop` was only read (`set transaction read only`), and nothing was crawled;
- no manual, per-page, per-site or per-platform rule. scikit-learn 1.9.1 stays ephemeral
  (`uv run --with`).

**Result: no candidate clears 0.95 on the Amendment 24 combined estimate.** Adding discovery's
candidates to training raises due-page precision (draws 0.962 → 0.972). It doesn't make admissions
on `no_menu_found` sites cleaner: held out, 75–83 % of what any candidate newly admits there is
not a menu.

| Candidate (held-out folds) | Draws (450) | R1(a) kept (361) | R1(a) menus lost | R1(b) admissions: pages / menus | **Combined (Am. 24)** | Recall: adds / drops |
|---|---|---|---|---|---|---|
| `classifier-v2` (shipped) | 0.918 | 0.931 | — | — | 0.931 | — |
| `classifier-v3` (built) | in sample | 0.959 | 5 | 26 / 8 | 0.773 | 49.7 / 5.0 |
| `a`: v2 inputs | 0.962 | 0.965 | 7 | 38 / 9 | 0.696 | 52.8 / 7.0 |
| `b`: v3 recipe | 0.962 | 0.959 | 5 | 36 / 9 | 0.706 | 54.9 / 12.2 |
| `a+`: `a` + candidates | 0.970 | 0.959 | 13 | 26 / 6 | 0.745 | 33.2 / 13.0 |
| `b+`: `b` + candidates | 0.972 | 0.962 | 11 | 31 / 6 | 0.706 | 33.2 / 11.0 |
| `a+w`: `a+`, population-weighted | 0.971 | 0.971 | 35 | 21 / 5 | **0.776** | 26.0 / 42.2 ✗ |
| `b+w`: `b+`, population-weighted | 0.971 | 0.974 | 31 | 27 / 6 | 0.736 | 33.2 / 38.2 ✗ |

- **The false admissions score as confidently as menus** (0.93–1.00 under every candidate). They
  are an Italian skate shop's product pages, a chain's press releases, insurance articles, a spam
  blog on a lapsed restaurant domain, ordering pages whose menu never reaches the text, and app
  shells. No threshold separates them, and the training mix doesn't move them.
- **The rule needs about zero false admissions.** Each false admission on a `no_menu_found` site
  weighs 5.2 pages against R1(a)'s 345. Even an oracle that removed every off-domain and every
  unpriced admission would reach only 0.905–0.935 (section 4). Only a candidate that admits no
  non-menu reaches 0.95 (0.962–0.977).
- **The fresh sample can't be drawn from `helios_laptop` for precision.** No resolved venue is left
  outside the classifier-labelled venues and sites. 1,259 unlabelled `no_menu_found` sites remain
  for admissions (section 5).
- **Next lever, proposed:** two verifiers, `classifier-v2` AND `classifier-v3`. It is the only
  generic option here with a held-out reading at the bar: R1(a) 0.959, and no new admissions by
  construction. It needs an owner ruling on §8's recall bar, because it can only drop menus
  (Q2).

## 1. Step 1: the R1(b) candidate census

The P5-29 and P5-30 re-crawls recorded **567 distinct candidate pages from 352 venues** (201
venues gave at least one page, plus the skipped Capture). P5-29 and P5-30 labelled 130 of them.
This session labelled **every other page, 437**, so the frozen labels are a census of discovery's
candidates on those venues.

- **Inputs verified first.** `var/menu-eval/p5-31/verify_inputs.py` checks every copied P5-29 and
  P5-30 artefact against its manifest: R1(a)'s inputs, hidden scores, weights and labels; both
  crawls, queue keys and label folders; `r1b-pages.jsonl` and `r1b-live-picks.json`; the
  P5-28 survey files. It also checks the manifests' own sha256 against the values the records
  print. **0 mismatches over 2,067 files.**
- **Queue.** `census_queue.py` takes every R1(b) page with no queue reason (`r1b-pages.jsonl`), in
  seed-**20261024** order. Each page's HTML segments to its recorded block count. The labeller
  folder (`census-label/`) holds pages, blocks, the unchanged P5-30 brief (with `js_only`) and 22
  page-id batches of at most 25 pages or about 1,500 blocks. Scores, verdicts and samples are in
  the hidden `var/audits/p5-31-training-mix-survey/census-key.jsonl` (`08bf38d7…`).

  | Queued (437) | both reject | both accept |
  |---|---|---|
  | P5-29 `no_menu_found` | 26 | 1 |
  | P5-29 resolved | 0 | 2 |
  | Q1 resolved (R1(a) venues) | 38 | 74 |
  | Q2 `no_menu_found` | 296 | 0 |

  Small 380, medium 54, large 3; 136 pages have no text block.
- **Labellers.** Sonnet subagents, at most 5 at a time, one batch each, working only inside the
  folder. The prompt asks for every line of every blocks file, read to the end, with lines read
  reported against `wc -l`, and the HTML checked for near-empty pages (`js_only` against
  `empty`).
  - **Batch 01 was relabelled.** Its labeller reported that it had cut the display of some long
    lines at 300–400 characters. Its 25 labels were moved to `census-pass-aside/batch-01/` and
    the batch was relabelled with the same prompt plus an explicit no-truncation rule. Every
    later batch got that prompt.
  - The two passes agree on menu against not on **25 of 25** pages, and on label and kind on 20
    (`batch01-agreement.txt`).
  - **Every batch reported lines read equal to total lines on every page.** One labeller (batch 10)
    read only the head of the HTML for three app shells. The brief uses the HTML for layout
    context only.
  - Some labellers wrote their JSON files with a throwaway helper script under `/tmp`. None read
    anything outside the folder.
- **Frozen** with P5-30's validator (`freeze_census.py` runs `freeze_labels.py` unchanged):
  `census-label/labels-manifest.json` (`679c96b1…`). This was done before any label was joined to a
  score.

  | Label | Census (437) | Full R1(b) (567) |
  |---|---|---|
  | menu | 85 | 97 |
  | not_menu | 180 (other own-site 42, `menu_not_in_text` 54, off-domain 35, homepage 31, hub 18) | 246 |
  | empty | 94 | 118 |
  | js_only | 78 | 106 |

  139 census labels are marked uncertain.

  | Full R1(b) by stratum | menu | not_menu | empty | js_only |
  |---|---|---|---|---|
  | `no_menu_found` (P5-29 + Q2: 443 pages, 300 venues) | 18 | 206 | 117 | 102 |
  | Q1 resolved (119) | 77 | 37 | 1 | 4 |
  | P5-29 resolved (4) and skipped Capture (1) | 2 | 3 | 0 | 0 |

  `classifier-v2` accepts 80 R1(b) pages (74 menus). It rejects 23 of the 97 menus, 18 of them
  with priced blocks.
- **The census reproduces P5-30's v3 verdict exactly**: combined 0.773 [0.711, 0.826], live replay
  0.884, production-scaled 0.941, recall 49.7 against 5.0. Every v2/v3 disagreement was already
  labelled; the new labels change no `classifier-v3` reading.

## 2. Step 2: method

`var/menu-eval/p5-31/build_pool.py` adds the two new sets to P5-28's pool (`pool.jsonl`, 695
pages, sha256-checked, read from the main checkout). The new pages get the same fields:
- v2's 263 inputs and the 11 page signals, computed with `page_vector_inputs` and
  `page_signals` as shipped;
- block count and stratum;
- v2, v3 and S4 (URL path trusted).

Every recomputed probability is checked against the frozen hidden scores:
- v2 matches exactly on all 928 pages;
- v3 matches within 2.8e-5. Two R1(b) pages are above 1e-6;
- every v2, v3 and S4 verdict matches.

No label is read there (`pool-new.jsonl`, `d0ca7051…`).

`survey_p5_31.py` joins the frozen labels (every manifest re-checked) and runs the survey:

- **Sets (11):** spike 188, rendered 57, the seven draws (450), **R1(a)** 361 and **R1(b)** 567.
  R1(b)'s `js_only` and `empty` pages are left out of training, as the spike's were. When
  scored they count as not menus, as in P5-30.
- **Groups:** union of venue and site, named by the smallest key (P5-29's trainer). A candidate
  page's own host joins its venue's site. Holding a set out removes from training every page that
  shares a venue or a site with it. R1(a) and R1(b) share Q1's 50 venues: holding out R1(a)
  drops 119 R1(b) pages from training, and holding out R1(b) drops 53 pages.
- **Candidates**, one family (standardized logistic regression, `C = 0.5`):
  - `a`: v2's inputs;
  - `b`: the v3 recipe (v2's inputs + 11 signals);
  - both trained on every set but R1(b);
  - `a+` / `b+`: the same with R1(b) in training. With R1(b) held out, R1(b) is split into 5
    venue-and-site groups. Each fold trains on everything outside its venues and sites,
    including the other four R1(b) folds;
  - `a+w` / `b+w`: `a+` / `b+` with each R1(b) page weighted by its population weight, both in the
    fit and in the threshold rule's precision. This is the optional sampling weight, so the
    pool's candidate share matches the population discovery verifies.
- **Threshold:** the existing rule inside each fold: the lowest threshold whose grouped
  out-of-fold precision (5-fold `GroupKFold` over the fold's training pool) reaches 0.95.
- **Readings:** P5-30's definitions and weights:
  - `no_menu_found` sites: 1,559 / 300;
  - Q1 venues: 361 / 50;
  - R1(a) is a census.

  The combined estimate is R1(a)'s kept pages plus R1(b)'s candidate-only pages, weighted, with a
  Kish n_eff Wilson interval.
- **Sanity check.** Held out on R1(a), `b` trains on exactly the 695-page pool. It reproduces
  `classifier-v3`: threshold 0.6738, R1(a) 0.959 with 5 menus lost.

The run takes about 10 s and is byte-reproducible (`survey.json` `1a72040a…`, `verdicts.jsonl`
`d5b32fc4…`).

## 3. Step 2: results per held-out set

### Precision (menus accepted / accepted) and recall

| Held-out | `v2` | `a` | `b` | `a+` | `b+` | `a+w` | `b+w` |
|---|---|---|---|---|---|---|---|
| `spike` ¹ | 1.000 (57/57) | 0.651 (54/83) | 0.659 (54/82) | 0.881 (52/59) | 0.911 (51/56) | 0.922 (47/51) | 0.927 (51/55) |
| `rendered` | 0.967 (29/30) | 0.914 | 0.842 | 0.968 | 0.938 | 0.968 | 0.964 |
| P5-5 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 |
| P5-8 | 0.917 | 0.925 | 0.926 | 0.923 | 0.937 | 0.934 | 0.934 |
| P5-10 | 0.931 | 0.985 | 0.985 | 0.985 | 0.984 | 0.984 | 0.984 |
| P5-12 | 0.861 | 0.923 | 0.909 | 0.937 | 0.938 | 0.934 | 0.934 |
| P5-14 | 0.903 | 0.970 | 0.970 | 1.000 | 1.000 | 1.000 | 1.000 |
| P5-16 | 0.972 | 0.986 | 0.986 | 0.985 | 0.985 | 0.985 | 0.984 |
| P5-26 | 0.903 | 0.970 | 0.984 | 0.984 | 0.984 | 0.984 | 0.984 |
| **Draws pooled** | 0.918 [0.889, 0.940] | 0.962 [0.939, 0.976] | 0.962 [0.939, 0.976] | 0.970 [0.947, 0.982] | **0.972** [0.950, 0.984] | 0.971 [0.949, 0.984] | 0.971 [0.949, 0.984] |
| Draws stratified | 0.915 | 0.959 | 0.958 | 0.966 | 0.969 | 0.968 | 0.968 |
| Draws: menus lost of 413 | — | 11 | 12 | 32 | 32 | 40 | 43 |
| **R1(a)** (361) | 0.931 (336/361) | 0.965 (329/341) | 0.959 (331/345) | 0.959 (323/337) | 0.962 (325/338) | 0.971 (301/310) | 0.974 (305/313) |
| R1(a) menus lost of 336 | — | 7 | 5 | 13 | 11 | 35 | 31 |
| **R1(b)**, all accepted | 0.925 (74/80) | 0.703 (83/118) | 0.713 (82/115) | 0.784 (80/102) | 0.748 (80/107) | 0.821 (78/95) | 0.772 (78/101) |
| R1(b) recall (of 97) | 0.763 | 0.856 | 0.845 | 0.825 | 0.825 | 0.804 | 0.804 |

¹ `v2` was fit on the spike, so it is in sample there. Without the candidate set (`a`, `b`), the spike
fold has no discovery-like negatives in training. With it (`a+` … `b+w`), the spike row recovers
from 0.65 to 0.88–0.93. This is the one place the training mix shows what Amendment 25 hoped for.

`classifier-v3` is in sample on the nine P5-28 sets. On R1(a) and R1(b) it reads as in P5-30:
0.959 (331/345) and 0.781 (82/105).

### Per size stratum (draws pooled, precision [Wilson], menus lost)

| Stratum | `v2` | `b` | `b+` | `a+w` |
|---|---|---|---|---|
| Small | 0.855 [0.802, 0.896] | 0.925 [0.878, 0.955], 11 | 0.946 [0.901, 0.971], 25 | 0.945 [0.899, 0.971], 28 |
| Medium | 0.975 | 0.994, 1 | 0.994, 4 | 0.993, 7 |
| Large | 0.973 | 0.987, 0 | 0.986, 3 | 0.986, 5 |

R1(a) small pages: v2 0.896, `b` 0.944, `b+` 0.948, `a+w` 0.961, `b+w` 0.968. The weighted
candidates buy their small-page precision with 31–35 lost menus.

### The Amendment 24 readings

| Candidate | Combined [Wilson, n_eff] | One unit per admitting venue | Without largest cluster | Live replay | Production-scaled (1,632) | Recall page level: adds / drops | Live: adds / drops ² |
|---|---|---|---|---|---|---|---|
| `v3` | 0.773 [0.711, 0.826] | 0.877 | 0.807 | 0.884 | 0.941 | 49.7 / 5.0 | 20.8 / 5.0 |
| `a` | 0.696 [0.629, 0.755] | 0.843 | 0.746 | 0.849 | 0.935 | 52.8 / 7.0 | 31.2 / 7.0 |
| `b` | 0.706 [0.640, 0.765] | 0.821 | 0.757 | 0.855 | 0.933 | 54.9 / 12.2 | 26.0 / 5.0 |
| `a+` | 0.745 [0.681, 0.800] | 0.846 | 0.779 | 0.872 | 0.937 | 33.2 / 13.0 | 26.0 / 5.8–13.0 |
| `b+` | 0.706 [0.640, 0.765] | 0.796 | 0.736 | 0.833 | 0.928 | 33.2 / 11.0 | 26.0 / 3.8–11.0 |
| `a+w` | **0.776** [0.713, 0.829] | 0.873 | 0.817 | **0.891** | **0.951** | 26.0 / 42.2 ✗ | 26.0 / 13.3–35.0 |
| `b+w` | 0.736 [0.669, 0.794] | 0.841 | 0.771 | 0.870 | 0.948 | 33.2 / 38.2 ✗ | 26.0 / 16.6–31.0 |

² The range is with and without the menus Q1's re-crawl regains on the R1(a) pages a candidate
rejects.

- **Every combined estimate is below 0.95**, and so is every upper Wilson bound. Every per-venue
  and live-replay reading is too.
- `a+w`'s production-scaled 0.951 is the only figure above 0.95, and that is a sensitivity, not
  the rule. The same candidate fails recall: it loses 35 R1(a) menus and adds 26.
- **Admissions on `no_menu_found` sites,** held out: `a` 33 pages (6 menus), `b` 29 (5), `a+` 23 (5),
  `b+` 27 (5), `a+w` 20 (5), `b+w` 24 (5), against `v3`'s 20 (4). They come from 12–20 admitting
  venues. The largest cluster is 4–7 pages, and dropping it leaves every reading below 0.82.
- **Recall.** Page-level adds exceed drops for every unweighted candidate. The population-weighted
  ones fail.
- **S4 alongside:** R1(a) 0.930 (4 menus lost). It accepts 456 R1(b) pages v2 rejects, 21 of them
  menus, for a combined 0.161. On candidates S4 trusts any menu-like path.

**What the false admissions are** (R1(b), v2 rejects, the candidate accepts, not a menu):

| Candidate | off-domain | `menu_not_in_text` | own-site other | hub | `js_only` | empty |
|---|---|---|---|---|---|---|
| `v3` | 11 | 2 | 3 | 1 | 1 | 0 |
| `b` | 17 | 2 | 3 | 1 | 4 | 0 |
| `a+` | 10 | 5 | 3 | 2 | 0 | 0 |
| `b+` | 7 | 6 | 3 | 2 | 7 | 0 |
| `a+w` | 7 | 4 | 3 | 2 | 0 | 0 |
| `b+w` | 6 | 6 | 3 | 2 | 4 | 0 |

Training on the candidates halves the off-domain admissions, but `menu_not_in_text` pages and
app shells take their place. For example, `b+` admits four `js_only` pages of one pho restaurant
(`/menu`, `/menus`, `/our-menu`, `/food`) and three Papa John's order pages.

## 4. Why the training mix can't reach the bar here

`var/menu-eval/p5-31/priced_diag.py` (descriptive; it uses the labels, so it tunes nothing and
selects nothing) asks how far other generic signals could go. It recomputes the combined estimate
with oracle removals of admissions:

| Candidate | As measured | Off-domain removed | Unpriced removed (menus too) | Both removed | No false admission |
|---|---|---|---|---|---|
| `v3` | 0.773 | 0.875 | 0.875 | 0.933 | 0.965 |
| `b` | 0.706 | 0.846 | 0.878 | 0.935 | 0.965 |
| `b+` | 0.706 | 0.764 | 0.840 | 0.895 | 0.965 |
| `a+w` | 0.776 | 0.850 | 0.873 | 0.911 | 0.973 |
| `b+w` | 0.736 | 0.790 | 0.842 | 0.902 | 0.977 |

- A perfect off-domain detector plus a priced-content gate for new admissions would still leave
  every candidate below 0.95.
- Under the Amendment 24 weights, one false admission on a `no_menu_found` site costs about 1.4
  points of the combined estimate. At these sample sizes the bar is met only by a verifier that
  admits **no** non-menu among discovery's candidates there.
- Among admitted non-menus, 7–10 print prices: shop products, ordering pages, a hotel take-out
  page. So "has prices" doesn't separate them either.
- The pages are confidently menu-like by text, layout and URL. Those are the only inputs this
  family has.

So the lever that is left is not another mix of the same features. It is either (i) not
admitting beyond `classifier-v2` at all, or (ii) evidence the page classifier doesn't have today,
such as whether the page is about this venue. Q2 has both.

## 5. Step 3: fresh-sample feasibility (owner Q3)

`var/menu-eval/p5-31/fresh_sample.py` (read-only against `helios_laptop`) writes the exclusion list
and counts the frames. It reuses P5-29's `select_venues.py` exclusions unchanged and adds R1(b).

- **Exclusion list:** `var/menu-eval/p5-31/classifier-exclusions.json` (`ebca288b…`), **1,463 venues
  and 1,452 sites**. It is the union of:
  - the spike's and S6f's venues and sites;
  - the 450 draw venues and sites;
  - R1(a)'s 361;
  - R1(b)'s 352 venues, with their website sites, menu-URL sites and every candidate page's host.

  A later classifier sample excludes a venue when its GERS id, website site or any menu-URL site
  is listed.
- **Precision from new venues: none available.**
  - All 1,634 resolved venues in `helios_laptop` are excluded (890 by venue, 744 by site), so
    **0 resolved venues and 0 due pages** remain.
  - The Pi's venues are the same 9,996, so a Pi pass adds fresh due pages only where it resolves
    a venue the laptop didn't.

  The new data needed is one of:
  - **(a)** a discovery run that reaches venues whose last outcome was a failure. Outside the
    exclusions these are:
    - `non_public_host` 899;
    - `robots_unavailable` 676;
    - `http_403` 592;
    - `redirect_refused` 224;
    - `http_404` 207;
    - other 4xx / 5xx and network errors 52.

    (Plus `menu_pdf_only` 142, `social_link` 80 and `platform_root` 68. `robots_disallowed` 153
    must stay out.) How many would resolve on a re-run is not measured;
  - **(b)** new venues from a later venue-discovery refresh (ADR-0009);
  - 1,911 current venues have no website at all.
- **Admissions from unlabelled `no_menu_found` sites:**
  - **1,559 venues on 1,259 sites** remain outside the exclusions, matching the owner's ~1,259;
  - the order, one venue per site, sorted by GERS id and shuffled with seed **20261025**, is
    written to `nmf-fresh-order.jsonl` (`6e3c1bfd…`). Nothing was crawled;
  - **proposed size:** the first **630 sites** (half), about 3 h 25 min of record-only crawl at
    P5-29/P5-30's 19.4 s per venue. Positions 631–1,259 are kept for one later round;
  - at the admission rates seen here (12–20 admitting venues per 350), 630 sites give about
    25–35 admitting venues. A candidate that admits **no** non-menu would show 0 false
    admissions; with one or two it fails, as above.
  - **Only needed for a candidate that admits beyond v2.** Under the proposed lever (two verifiers)
    there are no new admissions, so only due-page precision needs a fresh sample.

## 6. Artefacts

All are under this worktree's gitignored `var/`. Copy them into the main checkout before the
worktree is removed. P5-29 and P5-30's artefacts were copied here and verified; P5-28's are read
in place from the main checkout.

| Path | What |
|---|---|
| `var/menu-eval/p5-31/` | `verify_inputs.py`, `census_queue.py`, `census-summary.json` (`0fb95703…`), `census-label/` (+ `labels/`, `labels-manifest.json` `679c96b1…`), `census-pass-aside/batch-01/`, `batch01-agreement.txt`, `freeze_census.py`, `build_pool.py`, `survey_p5_31.py`, `tables.py`, `priced_diag.py`, `fresh_sample.py`, `classifier-exclusions.json`, `nmf-fresh-order.jsonl`, `fresh-sample-summary.json` |
| `var/audits/p5-31-training-mix-survey/` | hidden: `census-key.jsonl`, `pool-new.jsonl`, `survey.json`, `verdicts.jsonl`, `priced-diagnostic.json` |
| `var/menu-eval/p5-29-r1a/`, `p5-29-r1b/`, `p5-30/`, `var/audits/p5-29-classifier-v3/`, `p5-30-classifier-v3/` | P5-29/P5-30's artefacts, copied from the P5-30 worktree and checked against their manifests |

Reproduce (this worktree):

    python3 -I var/menu-eval/p5-31/verify_inputs.py
    PYTHONPATH=. uv run --extra menu python var/menu-eval/p5-31/census_queue.py   # refuses to overwrite labels
    python3 -I var/menu-eval/p5-31/freeze_census.py
    PYTHONPATH=. uv run --extra menu python var/menu-eval/p5-31/build_pool.py     # about 65 s
    PYTHONPATH=. uv run --no-project --with scikit-learn==1.9.1 --with numpy \
        python var/menu-eval/p5-31/survey_p5_31.py                                # about 10 s
    python3 -I var/menu-eval/p5-31/tables.py; python3 -I var/menu-eval/p5-31/priced_diag.py
    uv run --extra menu --env-file <deploy .env> python <main>/var/menu-eval/p5-26/with_db.py \
        helios_laptop var/menu-eval/p5-31/fresh_sample.py

## Verification

`make ci` (lockfile, lint, strict mypy over the repo including these `var/` scripts, pytest):
pass, with 694 passed and 727 skipped. Database tests are skipped here (no PostgreSQL `*_test`
database), so this is not database acceptance. The change is documents only. The survey re-runs
byte-identically, and `verify_inputs.py` reports 0 mismatches.

## For the owner

Each question carries the context needed to answer it here.

- **Q1. Accept "no candidate" and Amendment 26?**
  - **Context.**
    - Over 11 held-out sets, adding discovery's candidates lifts the draws to 0.970–0.972, the
      spike fold to 0.88–0.93 and R1(a) to 0.959–0.974.
    - The Amendment 24 combined estimate stays at 0.70–0.78. The cause is admissions on
      `no_menu_found` sites: 20–33 pages, 5–6 of them menus.
    - The best candidate on the rule (`a+w`, 0.776) also fails recall.
  - **Effect.** `classifier-v2` stays, R4 waits, and no fresh sample is drawn yet.
  - **Options:** (a) accept (recommended); (b) try another mix within the same family. Section 4
    bounds what that could reach.
- **Q2. Which lever next?**
  - **Context.** Section 4 shows the rule is met only by a verifier that admits no non-menu on
    `no_menu_found` sites. The false admissions score 0.93–1.00 on every input this family has.
  - **Options:**
    - **(a) Two verifiers: `classifier-v2` AND `classifier-v3` (recommended).** A page must pass
      both. It is generic, already built (`config/page_classifier_v3.json`), and needs no new
      model or dependency.
      - **Precision.** On R1(a), held out from v3's training, it reads 0.959 [0.933, 0.976],
        small 0.944. It admits nothing v2 rejects, so the combined estimate equals that.
      - **Recall.** It drops 5 of R1(a)'s 336 menus (1.5 %, 3 of them marked uncertain: an
        unpriced café menu, a catering menu, a Wix template with possible placeholder prices,
        IKEA's restaurant category page, an unpriced pizza list). It gains none. So it fails §8's
        "recall ≥ the previous verifier's" read strictly, and **needs your ruling that this loss
        is acceptable**, or a restatement of the recall bar for a verifier that only tightens.
        The held-out recipe `b` loses 12 of 413 draw menus.
      - **Caveat.** This option was first raised in P5-30 after R1(a) was scored, so R1(a)
        informed it. A fresh due-page sample is still wanted before a ship (Q3).
    - **(b) Venue-context signals for admissions.** For example, whether the page names the
      venue, its address or its phone, and whether its host is the venue's website host. These
      are generic, but the verifier would take the venue as an input: an interface change and an
      ADR amendment. Section 4's oracle bound (off-domain and unpriced removed, 0.90–0.94) says
      this alone won't reach 0.95.
    - **(c) Stop the classifier work** and keep v2 as a known gap (Amendment 23).
- **Q3. The fresh sample: where do due pages come from?**
  - **Context.** No resolved `helios_laptop` venue is outside the 1,463 classifier-labelled venues
    and 1,452 sites. A Pi pass covers the same venues. About 2,650 venues outside the exclusions
    last failed discovery, and their yield on a re-run is unknown. The admissions frame
    (1,259 sites, seed-20261025 order, 630 proposed) is ready, but (a) doesn't need it.
  - **Options:**
    - (a) **A discovery re-run of the failed-outcome venues** (laptop or Pi), then due-page
      precision from whatever newly resolves (recommended once Q2 is decided);
    - (b) wait for a venue-discovery refresh;
    - (c) accept R1(a) as the precision evidence for Q2 (a). R1(a) was not used to tune v3, but it
      did inform the choice.
- **Q4. Census labels.**
  - **Context.** All 437 labels are Sonnet's, written blind under the strict prompt; batch 01 was
    relabelled (25/25 agreement on menu vs not). 139 are marked uncertain, mostly redirect stubs
    called `empty` and `menu_not_in_text` against hub. No reading turns on them: the closest
    candidate is 0.17 below the bar.
  - **Ask.** Do the labels stand without a hand check, as in P5-30 Q4?
