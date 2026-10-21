# `classifier-v3` verdict: R1(a) and R1(b) labelled (ADR-0013 Amendment 24)

Session P5-30, 2026-10-21. This finishes R1(b) under the owner's rulings on the P5-29 record
([2026-10-21-p5-29-classifier-v3-build.md](2026-10-21-p5-29-classifier-v3-build.md), Q1 (a) and
Q2 (a)), labels R1(a) and R1(b) blind, and reaches the verdict that
[ADR-0013 Amendment 24](../adr/0013-phase5-menu-pipeline.md) item 4 asks for. It proposes
Amendment 25.

Scope:
- nothing is built or shipped. `classifier-v2` stays the verifier (`WEIGHTS_PATH` unchanged);
- no schema, migration, ORM model, dependency or `infra/` change, and no Pi access;
- `helios_laptop` was only read (`set transaction read only`). The re-crawl wrote no database
  row;
- no manual, per-page, per-site or per-platform rule.

**Result: `classifier-v3` fails §8 precision. Recall passes.**

| Reading | Precision [Wilson 95 %] | Bar |
|---|---|---|
| R1(a) alone (v3 keeps 345 of 361) | 0.959 [0.933, 0.976] | above 0.95 |
| **Amendment 24 rule:** R1(a)'s kept pages + R1(b)'s v3-only pages, population-weighted | **0.773** [0.711, 0.826] | **fails** |
| The same, one unit per admitting venue | 0.877 [0.827, 0.914] | fails |
| Live replay: discovery keeps the first accepted candidate | 0.884 [0.839, 0.918] | fails |
| Live replay, R1(a) scaled to all 1,632 due pages (sensitivity) | ≈ 0.941 | fails |

- **Recall passes on every reading.** Weighted page-level adds are 49.7 menus, against 5.0
  drops. The live replay gives 20.8 against 5.0.
- **What fails is new admissions.** Among pages v2 rejects on `no_menu_found` sites, v3 accepts
  20 recorded pages, and 4 are menus. The rest are:
  - insurance articles;
  - a slot-gambling spam blog on a lapsed restaurant domain;
  - press releases;
  - shop product pages;
  - a JavaScript product shell.

  Amendment 24 item 3 named this risk: the draws only hold pages v2 accepted.
- **On due pages alone, v3 is better than v2.** v3 reads 0.959 against v2's 0.931 on the same
  361 pages. It rejects 11 of the 25 non-menus and 5 of the 336 menus.

## 1. Step 1: the extra re-crawl (owner Q1, Q2)

### Venues

`var/menu-eval/p5-30/select_p5_30.py` reads `helios_laptop`. It runs P5-29's
`select_venues.py` unchanged, overriding only its pool sizes and output folder, so the
seed-20261022 order is the script's own. The pools are unchanged since P5-29:
- 2,348 `no_menu_found` venues on 1,559 sites;
- 3 resolved venues on 2 sites.

**P5-29's first 100 `no_menu_found` venues reproduce exactly.** The script stops if they don't.

| Stratum | Rule | Venues | Positions |
|---|---|---|---|
| Q1 resolved (`q1_r1a_resolved`) | R1(a)'s 361 venues sorted by GERS id, shuffled with seed **20261023**, first 50 with a website | 50 | 103–152 |
| Q2 `no_menu_found` (`q2_no_menu_found`) | seed-20261022 order, positions 101–300, one per site, P5-29's 102 sites kept out | 200 | 153–352 |

- Every Q1 venue has a website on the same site as its R1(a) page.
- `venues.jsonl` sha256 `1084bf0f…`.

### Crawl

The command is unchanged from P5-29 (`apps.menu_pipeline.record_candidates`): the same
`SiteFetcher`, robots.txt, 1 request per second per host and the Helios User-Agent. It ran as
one sequential process with a fresh cache, from 2026-10-21 04:38:21 to 05:59:19 UTC
(**80 min 58 s** wall time; 4,857 s summed over venues). All 250 venues were recorded, giving
441 candidate checks.

| Venue outcome | Q1 (50) | Q2 (200) |
|---|---|---|
| Enumeration ran, nothing accepted (`no_menu_found`) | 35 | 175 |
| `PlatformAmbiguous` (with or without `MenuPdfLinked`) | 7 | 12 |
| `MenuPdfLinked` only | 2 | 0 |
| **Failed:** `http_403` | 3 | 3 |
| **Failed:** `http_404` | 2 | 1 |
| **Failed:** `http_429` | 1 | 0 |
| **Failed:** `non_public_host` | 0 | 4 |
| **Failed:** `robots_unavailable` | 0 | 3 |
| **Failed:** `network_error` / `redirect_refused` | 0 | 1 / 1 |
| Venues with at least one candidate page | 46 | 108 |

- Failures: 6 of 50 Q1 venues and 13 of 200 Q2 venues.
- The one `http_429` is a site rate-limiting the crawl. Its failure stands; nothing was retried.

Frozen in `var/menu-eval/p5-30/crawl-manifest.json` (sha256 of every crawl file and page;
`4ffef914…`). P5-29's crawl and queue key were re-checked against their manifests before use.

### Rebuilt R1(b) label set

`var/menu-eval/p5-30/queue_p5_30.py` builds it. Distinct pages per stratum, by verdict pair:

| Stratum (pages) | both reject | v3 only | v2 only | both accept |
|---|---|---|---|---|
| P5-29 `no_menu_found` (131) | 126 | 4 | 0 | 1 |
| P5-29 resolved (4) | 0 | 0 | 1 | 3 |
| Q1 resolved (119) | 38 | 6 | **0** | 75 |
| Q2 `no_menu_found` (312) | 296 | 16 | 0 | 0 |
| Skipped Capture (1) | 1 | 0 | 0 | 0 |

The label set has 130 pages:
- **every disagreement over all strata (27)**, a census;
- P5-29's 100-page both-reject sample, unchanged;
- the skipped Capture;
- **2 `replay_pick` pages.** These are pages both verifiers accept that one of them would pick
  live, at a venue where v2's and v3's live picks differ. Without them, those venues' live
  replay would have an unlabelled side. This is an addition to the plan, and it is small.

Other notes on the set:
- No Q1 page matched its R1(a) page in both URL and body (every body changed), so no R1(a) label
  was reused.
- **None of R1(a)'s 16 v3-rejected venues fell in Q1's 50.** So whether v3 would find another
  menu on those sites is not observed (section 3).

## 2. Step 2: blind labels

All labels were written by Sonnet subagents, at most 5 at a time, to the folder's
`LABELLING.md`. No Haiku was used. Labellers saw only their folder: no score, verdict or
`var/audits/`.

- **R1(a), all 361 pages.** Frozen in `var/menu-eval/p5-29-r1a/labels-manifest.json`
  (`8e53a26f…`):

  | Label | Pages |
  |---|---|
  | menu | 336 |
  | not_menu: hub | 15 |
  | not_menu: other own-site page | 4 |
  | not_menu: menu not in text | 3 |
  | not_menu: off-domain | 3 |

  57 are marked uncertain.
- **A first pass was set aside.** One first-wave labeller (positions 91–120) reported that it
  had read only the heads and tails of long pages. All 150 first-wave labels (positions 1–150,
  written under the looser prompt) were moved aside. Those positions were relabelled under the
  strict prompt: read every line, and report lines read against total lines. So all 361 frozen
  labels come from one protocol.
- **Agreement check.** The set-aside first pass agrees with the frozen labels on menu vs not on
  **149 of 150 pages (κ 0.94)**. The one flip is a single-product page, which the frozen label
  marks uncertain (`var/menu-eval/p5-30/r1a-agreement.json`).
- **R1(b), P5-29's 106 queued pages.** Labelled in P5-29's own blind folder and frozen
  (`ba5ffe00…`): menu 3, not_menu 52, js_only 27, empty 24.
- **R1(b), the 24 new pages.** Labelled in `var/menu-eval/p5-30/r1b-label/` and frozen
  (`559a6713…`): menu 9, not_menu 14, js_only 1.

Every manifest was written before the hidden scores were joined; the verdict script refuses
any label whose sha256 changed.

## 3. Step 3: the verdict

`var/menu-eval/p5-30/verdict_p5_30.py` produces `verdict.json` (sha256 `a93d16a5…`).

**Population weights**, as the brief set them:
- R1(a) is a census of its frame, weight 1.
- R1(b) `no_menu_found`: 1,559 eligible sites / 300 sampled = **5.197** per venue.
- Q1 resolved: 361 / 50 = **7.22**.
- P5-29's resolved stratum: 2 of 2, weight 1.

### Precision

| Cell | Pages | Menus | Precision [Wilson] |
|---|---|---|---|
| R1(a) small (v3 kept) | 179 | 169 | 0.944 [0.900, 0.969] |
| R1(a) medium | 158 | 154 | 0.975 [0.937, 0.990] |
| R1(a) large | 8 | 8 | 1.000 [0.676, 1.000] |
| R1(b) P5-29 `no_menu_found`, v3 only | 4 | 0 | 0.000 [0.000, 0.490] |
| R1(b) Q1 resolved, v3 only | 6 | 4 | 0.667 [0.300, 0.903] |
| R1(b) Q2 `no_menu_found`, v3 only | 16 | 4 | 0.250 [0.102, 0.495] |
| **Weighted, all cells (Amendment 24 rule)** | **371** | **339** | **0.773 [0.711, 0.826]** (Kish n_eff 202) |

The unweighted pooled figure is 339/371 = 0.914 [0.881, 0.938]. Every reading is below 0.95.

**Readings of the same data:**
- **The plan's rule** counts every recorded page that v3 alone accepts.
- **Live replay.** Discovery stops at the first accepted candidate, so live v3 would add one
  page per venue. That page is a menu at 4 `no_menu_found` venues (taco and coffee shops). It is
  not a menu at 6 `no_menu_found` venues and at P5-29's amazon venue. Precision over R1(a)'s
  kept pages plus these picks is **0.884 [0.839, 0.918]**.
- **Production-scaled.** R1(a)'s precision is applied to all 1,632 due pages instead of its
  361-site frame. This is a sensitivity of mine, not the rule:
  (1,496.4 + 20.8) / (1,559.7 + 20.8 + 32.2) ≈ **0.941**.
- **Cluster effects.** The 26 v3-only pages come from 14 venues:
  - 4 sites give 14 of them: `friscoshop.it` 4, `royaljellyatx.com` 4, `bennigans.com` 3,
    `nationwide.com` 3;
  - dropping the largest cluster gives 0.807;
  - counting one unit per admitting venue (majority label) gives 0.877.

  No reading rests on a single cluster.

**What v3 admits that isn't a menu (R1(b)):**

| Kind | Pages | Examples |
|---|---|---|
| Off-domain | 11 | an Italian skateboard shop's "menu" products (4); a slot-gambling spam blog on a lapsed restaurant domain, at `/menu`, `/menus`, `/food`, `/our-menu` (4); insurance industry articles (3) |
| Own-site press release | 3 | "Summer Shenanigans menu" posts |
| Menu not in text | 2 | an item page with no dish text; a menu page whose text is only a heading |
| Hub | 1 | a chain's menu landing page |
| JavaScript-only | 1 | a bakery product shell |

These pages say "menu" in the URL and in the text, on food-related pages. Those are the
features the retrain leaned on: `article_markup` came out positive, and the embedding is
topical.

### Recall (§8: "recall ≥ the previous verifier's")

| Reading | Menus v3 adds | Menus v3 drops | Met |
|---|---|---|---|
| Page level (Amendment 24) | 49.7 (8 pages: Q2 4 × 5.197, Q1 4 × 7.22) | 5.0 (R1(a) census) | **yes** |
| Live replay | 20.8 (4 venues × 5.197) | 5.0, with no regain observed | **yes** |

- The 5 R1(a) menus v3 drops, 3 of them marked uncertain:
  - an unpriced café menu;
  - a corporate catering menu;
  - a Wix template whose prices may be placeholders;
  - IKEA's restaurant category page;
  - an unpriced pizza list.
- The page-level adds on Q1 sites overstate. On those sites v3 still accepts the R1(a) page, so
  live discovery would never reach the extra pages.
- R1(b) has no v2-only menu: its only v2-only page is the amazon search page.

### S4 alongside

| Sample | S4 |
|---|---|
| R1(a) | keeps 357: precision 0.930 [0.899, 0.952]; small 0.894 |
| R1(b) labelled pages | accepts 123, of which 14 are menus (weighted 0.14) |

S4 trusts any menu-like URL path, so on discovery's candidates it admits nearly everything.

## 4. Verdict and next lever

**Fail. `classifier-v2` stays the verifier, and R4 is not built** (Amendment 24 Q5, "only on a
pass"). The laptop pass's rows stay, as Amendment 23 items 2 and 5 already rule.

The survey's §5 risk 4 is what happened. The training pool is 72 % menus and has no discovery
candidates v2 rejected. The threshold rule therefore never saw the population v3 is applied to
on `no_menu_found` sites. The next lever the survey named is **the training mix**, not a
per-page rule:
- add discovery's candidate pages, which are mostly non-menus, to the pool;
- re-pick the threshold by the same rule on grouped folds.

The labelled candidates now exist: R1(b)'s 130 and P5-29's crawl. Using them makes them tuning
data, so a third fresh sample would be needed. Questions Q2 and Q3 below are about that.

## 5. Artefacts

All are under this worktree's `var/` (gitignored); copy them into the main checkout before the
worktree is removed:

| Path | What |
|---|---|
| `var/menu-eval/p5-30/` | `select_p5_30.py`, `venues.jsonl` (+ summary), `nmf-order/`, `queue_p5_30.py`, `crawl-manifest.json`, `queue-summary.json`, `r1b-label/` (+ `labels/`, `labels-manifest.json`), `freeze_labels.py`, `agreement.py`, `r1a-agreement.json`, `r1a-labels-pass1/`, `verdict_p5_30.py`, `verdict.json`, `verify_p5_29.py`, `move_pass1.py` |
| `var/menu-eval/p5-29-r1a/labels/` + `labels-manifest.json` | R1(a)'s frozen labels |
| `var/menu-eval/p5-29-r1b/label/labels/` + `labels-manifest.json` | P5-29 R1(b) queue's frozen labels |
| `var/audits/p5-30-classifier-v3/` | hidden: `r1b-crawl/` (pages, candidates, venue outcomes, site cache), `r1b-queue-key.jsonl`, `r1b-pages.jsonl`, `r1b-live-picks.json`, crawl log and times |
| `var/menu-eval/p5-29-r1a/`, `p5-29-r1b/`, `var/audits/p5-29-classifier-v3/` | P5-29's artefacts, copied and checked against their manifests (`verify_p5_29.py`: 0 mismatches) |

Reproduce (this worktree):
`uv run --extra menu --env-file <deploy .env> python <main>/var/menu-eval/p5-26/with_db.py helios_laptop var/menu-eval/p5-30/select_p5_30.py`,
then the crawl command (section 1), then
`PYTHONPATH=. uv run --extra menu python var/menu-eval/p5-30/queue_p5_30.py`,
`python3 -I var/menu-eval/p5-30/freeze_labels.py {r1a,r1b29,r1b}` and
`PYTHONPATH=. uv run --extra menu python var/menu-eval/p5-30/verdict_p5_30.py`.

## Verification

`make ci` (lockfile, lint, strict mypy over the repo including these `var/` scripts, pytest):
pass, with 694 passed and 727 skipped. Database tests are skipped here (no PostgreSQL `*_test`
database), so this is not database acceptance. The change is documents only.

## For the owner

Each question carries the context needed to answer it here.

- **Q1. Accept the fail verdict and Amendment 25?**
  - **Context.** Amendment 24's rule gives 0.773. Every other reading also misses 0.95: per
    venue 0.877, live replay 0.884, production-scaled ≈ 0.941. Recall passes. On due pages alone
    v3 beats v2 (0.959 against 0.931).
  - **Effect.** v2 stays. R4 waits for a classifier that passes. The laptop pass's rows stay
    (Amendment 23).
  - **Options:** (a) accept (recommended); (b) re-weight the rule. Even production weighting
    fails, so (b) changes no verdict.
- **Q2. The next lever: which one?**
  - **Context.** 20 of v3's 26 new admissions are on `no_menu_found` sites, and 4 of those 20
    are menus. The other 6 are on Q1 resolved sites, where live discovery keeps the R1(a) page
    and would never reach them. v3 tops v2 on due pages but over-admits candidates.
  - **Options:**
    - **(a) Training mix (survey §5 risk 4; recommended).** Add the labelled discovery
      candidates (R1(b)'s 130 pages and P5-29's) to the 695-page pool as a tenth set, then re-run
      the survey's leave-one-set-out with the same candidates and threshold rule. The admissions
      bar is then measured on held-out candidate pages. This needs a fresh verification sample
      (Q3).
    - **(b) Two verifiers.** v2 AND v3 (a page must pass both). Generic, with no new model. On
      these samples:
      - precision on due pages is v3's 0.959;
      - it admits nothing v2 wouldn't;
      - but it drops R1(a)'s 5 menus with nothing won back, so it fails §8's "recall ≥ the
        previous verifier's" strictly (5 of 336, 1.5 %). It needs a ruling that this loss is
        acceptable.
    - **(c) Stop the classifier work for now** and keep v2 as a known gap (Amendment 23).
- **Q3. A fresh sample for the next round: from where?**
  - **Context.**
    - Amendment 24 Q2 makes later classifier samples exclude classifier-labelled venues and
      sites.
    - All 811 resolved sites in `helios_laptop` are now labelled: 450 from the draws, 361 in
      R1(a). The 821 other due pages all sit on those sites.
    - About 1,259 unlabelled `no_menu_found` sites remain.
  - **Options:**
    - (a) **Precision from new venues** (the Pi pass, or newly resolved venues), and admissions
      from the remaining `no_menu_found` sites (recommended).
    - (b) Allow a same-site, different-page sample from the 821 due pages, accepting the
      correlation with already-labelled sites.
    - (c) Re-use R1(a) as a held-out precision set, by not training on it in (a). Only R1(b)'s
      candidates would join the pool. R1(a) has been scored against v3, but not tuned on.
- **Q4. Labels by subagent.**
  - **Context.** All labels are Sonnet's, written blind. The first pass agrees with the frozen
    labels on 149 of 150. 57 R1(a) pages and 45 R1(b) pages are marked uncertain; the verdict
    doesn't turn on them (0.773 is far from 0.95).
  - **Ask.** Do you want a hand check of the 26 v3 admissions and the 16 v3 rejections before
    accepting? They are the pages that decide the result.
