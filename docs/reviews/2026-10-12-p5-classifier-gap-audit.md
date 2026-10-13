# Page-classifier gap audit (ADR-0013 §8, stage [1])

Session 2026-10-12: does the page classifier (`classifier-v2`) lose quality that the
menu pipeline's §8 numbers can't see, and does it miss its own §8 bar (precision ≥ 0.95;
recall ≥ the previous verifier's)? Measured and proposed only: no pipeline, harness,
schema, model, dependency or `infra/` change, no Pi access.

**Result: no demonstrated gap against the §8 bar, and no measurement that could show
one.** The extraction queue is gated by `classifier-v2`. The only data on its precision
over the laptop pass is the pages that held-out labellers marked as not menus: 151 of 162
drawn pages were menus, 0.932 [0.883, 0.962]. That point estimate is below 0.95, but the
interval contains the bar. It is also consistent with the classifier's recorded
cross-validation precision (1 false positive in 41, Fisher p = 0.47). Recall over the
laptop pass has never been measured. The allowed tuning labels can't measure either
number, because every one of those pages is a labelled menu with prices. Step 3 (survey
replacements) was not run, and this record proposes no ADR or swap. Instead it asks for
a classifier-specific evaluation sample (recommendation R1) and flags two code paths
where a page the classifier rejects later stays in the extraction queue (finding 2).

**Blindness.** Read: the merged records (classifier v1/S6f, held-out 2026-09-30,
2026-10-09, 2026-10-12 v5, tuning v4–v6). Labels opened: only the tuning pages. These
are the spike's 33 gold pages, P5-5's 10, P5-8's 35 and P5-10's 35 held-out pages, all
already used as tuning pages. Not opened: P5-8's and P5-10's 37 labelled-but-unscored
pages each, anything under P5-12 (the v6 held-out evaluation is unmerged), and the v6
replay outputs. The 11 drawn not-menu pages are among the unscored pages, so this record
cites only their published counts.

## 1. What the classifier gates

`due_pages` itself doesn't call the classifier. The filter is upstream. A `menu-page`
Version exists only for a page that `classifier-v2` accepted at fetch time, and the queue
reads only Versions.

| Step | Code | What the classifier decides |
|---|---|---|
| Discovery (`resolve_urls`) | `apps/discovery/resolve_urls.py:83` loads it; `apps/discovery/web_client.py:819` (own-site candidate), `:875` (rendered candidate), `:731` (platform page), `:653` (ADR-0015 re-verification) | A menu URL is saved only when its page passes |
| Fetch (`menu_pipeline.run`) | `apps/menu_pipeline/page_bronze.py:393` (static), `:420` (rendered) | Pass: `_succeeded` writes a Capture and a Version. Fail: `_skip` (`:443`) writes a **skipped** Capture (`not_menu` / `js_only`) and **no Version** |
| Due queue | `apps/menu_pipeline/menu_writes.py:136–239` | None. It takes the latest Version of every `menu-page` record and drops records not `resolved` (`:205`) or without a bundle (`:208`) |
| Extraction | `apps/menu_pipeline/extraction.py:377` | None. The probability becomes page confidence only, with no threshold |

So the not-menu pages in the draws didn't reach the queue unfiltered. They are pages
that `classifier-v2` accepted, once at discovery and again at fetch. Both checks run the
same deterministic scorer on the same kind of input, so the second check adds nothing
for an unchanged page. On the laptop pass, the fetch skipped only 1 of 894 URLs as
`not_menu` (P5-5 record).

**Two places where a rejected page stays due.** These come from reading the code. The
laptop pass fetched each URL once, so neither path was exercised:

- (a) A re-fetch that fails the classifier writes a skipped Capture and no Version
  (`page_bronze.py:397`). The record's last accepted Version stays its latest one, so
  it stays in `due_pages`.
- (b) An ADR-0015 withdrawal (`apps/discovery/url_pipeline.py:587–636`, `_withdraw_menu`)
  unassigns only the `menu-url-discovery` record. Nothing touches the `menu-page` record,
  which stays `resolved`. Its last Version is therefore re-queued as `reinterpret` on
  every pipeline-version bump.

ADR-0013 §7 says "a verifier failure takes ADR-0015's withdrawal path", and
`page_bronze.py:29` leaves withdrawal to discovery. As built, that path doesn't reach
the extraction queue. This record didn't check what Gold shows for such a page.

## 2. Classifier-originating loss

### 2.1 What the allowed labels can measure

| Set | Pages | `page_label` | Priced items | How the pages were chosen |
|---|---|---|---|---|
| Spike gold (dev 6, ho1 8, ho2 10, ho3 9) | 33 | menu 33 | 33 | Spike gold set. **All 33 are in the classifier's own training labels** (`spike/menu-model`, `labels/pages`), so they are in-sample |
| P5-5 held-out | 10 | menu 10 | 10 | The first scorable pages of a draw from `due_pages` |
| P5-8 held-out | 35 | menu 35 | 35 | The first scorable pages per stratum from `due_pages` |
| P5-10 held-out | 35 | menu 35 | 35 | The first scorable pages per stratum from `due_pages` |

None of the tuning pages is `not_menu`, `empty` or an unpriced menu. Held-out pages were
picked as scorable menus after labelling, and the spike's gold set is scorable menus.
That has two consequences:

- **Precision can't be measured on them**, because no page there is a negative.
- **Recall on them is true by construction.** The 80 laptop pages were drawn from the
  queue the classifier already filtered, and the 33 spike pages are training data.

What re-scoring still shows is whether today's scorer reproduces the queue's verdicts,
and how close those menus sit to the threshold. This audit re-ran `classifier-v2`
(threshold 0.508) on all 113 pages. It accepts all 113. Laptop CPU, including
segmentation: median 41 ms per page, max 201 ms.

| Group | Pages | Rejected | Probability 0.508–0.70 | Min | 10th percentile | Median |
|---|---|---|---|---|---|---|
| Spike 33 (in-sample) | 33 | 0 | 0 | 0.845 | 0.988 | 0.997 |
| P5-5 | 10 | 0 | 1 | 0.634 | 0.888 | 0.997 |
| P5-8 | 35 | 0 | 1 | 0.672 | 0.827 | 0.997 |
| P5-10 | 35 | 0 | 2 | 0.631 | 0.910 | 0.994 |
| Stratum small (P5-8 + P5-10) | 28 | 0 | 2 | 0.631 | 0.770 | 0.992 |
| Stratum medium | 28 | 0 | 0 | 0.893 | 0.954 | 0.997 |
| Stratum large | 14 | 0 | 1 | 0.672 | 0.910 | 0.998 |
| `html_list` | 84 | 0 | 3 | 0.631 | 0.888 | 0.997 |
| `html_cards` | 19 | 0 | 1 | 0.634 | 0.910 | 0.992 |
| `html_inline` | 6 | 0 | 0 | 0.877 | 0.877 | 0.992 |
| `price_list` | 4 | 0 | 0 | 0.980 | 0.980 | 0.996 |

The four pages closest to the threshold:

| Page | Set | Stratum | Format | Labelled items | Probability |
|---|---|---|---|---|---|
| `a95c964df0d3` | P5-10 | small | `html_list` | 2 | 0.631 |
| `e8dcaff697a6` | P5-5 | — | `html_cards` | 5 | 0.634 |
| `78ddbf7ec3f0` | P5-8 | large | `html_list` | 137 | 0.672 |
| `ea20edd6efeb` | P5-10 | small | `html_list` | 1 | 0.675 |

Three of the four print 5 or fewer items. This is a lead, not a measurement: if the
classifier misses menus on the laptop pass, short menus are where to look first.

### 2.2 Precision: published draw counts

The held-out records publish page-level counts for each full labelled draw. Their
"not menus" are the labelling brief's `not_menu` (a homepage, an about, locations or
catering-inquiry page, or a hub that only links to menus) plus `empty` (no usable text).
That definition matches the classifier's own training convention (S6f: hubs, home,
locator and similar pages are `not_menu`), so these pages are more likely classifier
false positives than a mismatch between label conventions. The split between `not_menu`
and `empty` isn't published.

| Draw | Pages labelled | Menus | Not menus | Precision [Wilson 95 %] |
|---|---|---|---|---|
| P5-5 (2026-09-30) | 18 | 18 | 0 | 1.000 [0.824, 1.000] |
| P5-8 (2026-10-09) | 72 | 66 | 6 | 0.917 [0.830, 0.961] |
| P5-10 (2026-10-12) | 72 | 67 | 5 | 0.931 [0.848, 0.970] |
| **Pooled** | **162** | **151** | **11** | **0.932 [0.883, 0.962]** |
| *Recorded: spike nested CV (S6d), pages called a menu* | *41* | *40* | *1* | *0.976 [0.874, 0.996]* |

How to read it:

- **Against the bar:** if the true precision were exactly 0.95, a draw of 162 would show
  11 or more not-menus with probability 0.19. The draws don't show a gap below 0.95, and
  they don't clear the bar either.
- **Against the recorded estimate:** a not-menu rate of 11/162 against 1/41 gives Fisher
  p = 0.47 (two-sided). The draws are consistent with the spike-CV number.
- **Not a pool estimate.** Draws take one page per venue and site. P5-8 and P5-10
  exported fixed quotas per size stratum (34 / 26 / 12) from pools split about 50 / 40 /
  10 %. Not-menu counts per stratum aren't published, so the pooled number is unweighted.
- **By format:** undefined, because a not-menu page has no format. **By stratum:** not
  available without opening the unscored labels.
- The brief's P5-12 count (62/72) is not used, because that record isn't merged.

### 2.3 Recall

Recall over the laptop pass can't be measured with these labels. It needs labelled
pages that the classifier *rejected*, and no labelled set contains any. The evidence on
record is still the S6d/S6f numbers: nested CV 40/48 = 0.833 [0.704, 0.913], equal to the
S4 heuristic; the second export 9/9; rendered held-out pages 8/9.

For scale: the laptop pass has 8,085 venues with a website, but only 1,635 menu-URL
records. Discovery found no menu URL for 3,550 venues (P5-5 record). Classifier
rejections are one cause among several (no candidate link, fetch failures, PDFs), and
nothing here separates them.

### 2.4 Effect on the §8 extraction numbers

By construction, **none.** Each held-out set is the first scorable menus per stratum in
draw order, so the selection skipped not-menu and unpriced pages before scoring. Pages
the classifier rejects never enter the pool. So item recall, usable prices, gold-row
false reject, price accuracy and catch are untouched by classifier errors in all three
failed evaluations. Those misses are model, repair and validator losses.

What §8 can't see:

- §8 scores a population the classifier has already filtered. If the classifier misses
  certain layouts, they are missing from every evaluation. The size of that effect is
  unknown.
- In production, a false-positive page would be extracted and written, with the
  classifier's probability as its page confidence. What v6 writes for a not-menu page is
  unmeasured.
- 11 of 162 labelled draw pages (6.8 %) were not menus, which is labelling effort the
  draws spent on pages they couldn't score.

### 2.5 Menus that print no prices (not classifier errors)

50 of the 151 drawn menus (0.331 [0.261, 0.410]) print no prices in their static text:
P5-5 8/18, P5-8 20/66, P5-10 22/67. The classifier's training convention counts an
unpriced menu as a menu (S6f lists Taco Palenque's unpriced menu as a *miss*), so
accepting these pages is correct. They don't count against the classifier. They do mean
the share of usable prices across the whole corpus will be well below the §8 "usable
prices" figure, which only counts scorable menus.

## 3. Replacement survey: not run

Step 3 depends on a real gap against the bar, and §2.2 doesn't show one. The survey also
couldn't run on these labels. All 113 tuning pages are positives that every candidate
would accept, so leave-one-set-out would rank nothing on precision and measure no
recall. Without a negative or rejected page among them, any comparison would just reuse
the spike training set. For the same reason, this record drafts no ADR or ADR-0013
amendment.

## 4. Findings

1. **The classifier gates the queue upstream.** Every due page is a Version that
   `classifier-v2` accepted at fetch (`page_bronze.py:393`, `:420`). `due_pages`
   (`menu_writes.py:136`) and extraction (`extraction.py:377`) don't filter again.
2. **Two paths keep a later-rejected page due:** a re-fetch that fails the classifier,
   and an ADR-0015 withdrawal. Neither retires the `menu-page` record, so its last
   accepted Version keeps being extracted. Neither path has been exercised yet, because
   the laptop pass fetched each URL once. Monthly Pi runs will exercise both.
3. **Precision over the laptop pass is unproven both ways:** 0.932 [0.883, 0.962] on the
   162 drawn pages. That is below the bar as a point estimate but not significantly, and
   consistent with the recorded 0.976.
4. **Recall over the laptop pass has never been measured.** The §8 recall bar ("≥ the
   previous verifier's") rests on the spike sample alone.
5. **Classifier errors move none of the §8 extraction numbers.** By construction,
   classifier errors don't cause the three failed held-out evaluations.
6. **A third of accepted menus print no prices.** That isn't a classifier error.
7. **Short menus score lowest.** Of the four tuning menus closest to the threshold,
   three print 5 or fewer items. This is a lead for where misses would be.

## 5. Recommendations (owner decisions; nothing implemented)

- **R1. A classifier evaluation sample, labelled at page level only.** Each page gets
  menu with prices / menu without prices / `not_menu` / `empty`, with no item rows, so
  labelling takes minutes per page. Draw from the laptop pass with every labelled venue
  and site excluded:
  - (a) **Precision:** random pages from `due_pages`, stratified by the fixed size
    cutoffs, with counts recorded per stratum. To get a Wilson lower bound at or above
    0.95, about 260 pages are needed if observed precision is 0.975, about 440 if it is
    0.97.
  - (b) **Recall:** random pages the classifier rejected: skipped `not_menu` / `js_only`
    Captures (bundles are kept) and discovery's rejected candidates, re-fetched where no
    body was kept.

  Score `classifier-v2` and the S4 heuristic on the same pages. A real gap here is the
  trigger for step 3: precision whose Wilson upper bound is below 0.95, or recall below
  S4's. Run step 3 with leave-one-set-out over this sample and the spike labels.
- **R2. Record page-level counts in every held-out record**, per stratum: menu with
  prices, menu without prices, `not_menu`, `empty`. Draws then add up to a running
  precision check without anyone opening unscored labels later.
- **R3. Optionally, open P5-8's 6 not-menu pages** to sort out what they are (homepage,
  hub, catering page, empty shell). Their venues are already excluded from every future
  draw. This audit didn't open them, because the brief allowed only tuning-page labels.
  P5-10's 5 stay unseen.
- **R4. Close finding 2 before the Pi monthly runs.** Decide whether a fetch-time
  classifier failure or a menu-URL withdrawal should take the `menu-page` record out of
  `due_pages`, and what Gold should then show. This is a pipeline change for its own PR.
  It doesn't block v6, because the laptop pass fetched each URL once.

## Reproduce

The scorer and its output are in gitignored `var/audits/p5-classifier-gap/` in the main
checkout (`score_tuning.py`; `scores.jsonl`, sha256
`c4a150cef81bb33a00e13e3d51a82034f1e617b5b1deab259861fda7388acc10`). Run it from the main
checkout, with the `menu` extra and the pinned `potion-base-8M` under `var/models/`:

    PYTHONPATH=. uv run --extra menu python var/audits/p5-classifier-gap/score_tuning.py \
        > scores.jsonl

The script reads page HTML, the URL (from each draw's `draw.jsonl`, matched by Version
id) and `page_label` / `format` for tuning page ids only. It reads them from the session
worktrees' gitignored directories, at absolute paths under `.claude/worktrees/`:
`p5-5-held-out-eval/var/menu-eval/p5-5`, `p5-8-v4-held-out/var/menu-eval/p5-8`,
`p5-10-v5-held-out/var/menu-eval/p5-10` and `p5-11-pipeline-v6/var/tune` (spike 33). If
those worktrees are removed, the script can't be re-run until the directories are
copied elsewhere and its paths updated.
