# S6f render measurement and classifier-v2 evaluation (ADR-0013 §4, §8)

The measurement ADR-0013 §4 requires before headed rendering is switched on for
Pi runs, and the evaluation (§8) that lets `classifier-v2` replace `classifier-v1`
as ADR-0015's verifier. Session S6f, 2026-09-29. Page bodies, labels and reports
stay in gitignored `var/` (copied to
`var/spikes/menu-model/render-probe-2026-09-29/s6f/` in the owner's checkout); this
file keeps the numbers.

## What was measured

- **URLs (75).** The S6d render probe's 60 URLs (37 platform links, 23 JavaScript-only
  own-site pages from the spike sample), plus a **held-out** set of 15 platform links
  from the 100 venues of the second candidate export that the spike never fetched
  (their homepages were fetched statically this session; 12 Toast, 1 DoorDash, 2 Square).
- **Renderer:** the production `BrowserRenderer` (`apps/menu_pipeline/render.py`):
  headed Chromium 153 (Playwright 1.63.0) under Xvfb, browser UA + Helios token,
  robots.txt read through the browser for the page and every sub-request host,
  3 s per-host pacing. Command: `python -m apps.menu_pipeline.measure_render
  --urls … --classify`. Laptop (x86-64); **the Pi numbers are still to be recorded**
  (below).
- **Two runs.** Run 1 exposed a renderer bug: Chromium fails the navigation on an
  empty `4xx` robots.txt body, and the renderer read that as "unreachable", which
  blocked Square's asset CDN (`cdn5.editmysite.com`, `400`) and every Square menu with
  it. Fixed and regression-tested; the numbers below are run 2.

## Render results (run 2, laptop)

| Host | URLs | Robots-skipped | Rendered: menu / not a menu / empty | Menus accepted by `classifier-v2` | Median / max s |
|---|---|---|---|---|---|
| Toast | 32 | 7 (gift cards, invoice: disallowed by Toast's robots.txt) | 19 / 5 / 1 | **19 / 19** | 13.9 / 36.1 |
| Square | 8 | 1 (gift card) | 4 / 2 / 1 | **4 / 4** | 13.5 / 21.5 |
| Clover | 4 | 0 | 2 / 1 / 1 | **2 / 2** | 15.6 / 25.6 |
| DoorDash | 5 | 0 | 3 / 2 / 0 | 1 / 3 | 37.0 / 65.6 |
| Grubhub | 3 | 0 | 1 / 2 / 0 | 1 / 1 | 48.5 / 53.1 |
| Own-site, JavaScript-only | 23 | 0 | 3 / 13 / 7 (1 image-only) | 2 / 3 | 12.3 / 63.0 |
| **All** | **75** | **8** | **32 / 25 / 10** | **29 / 32** | **13.9 / 65.6** (p90 48.5) |

- **Render success:** 67 of 75 rendered, and the 8 skips are robots.txt refusals.
  **No bot challenge and no `403`**: headed Chromium loads Toast and, unlike the
  S6d probe, DoorDash. The S6d probe had 19 of 37 platform links priced; here the
  platform menus are 29, all but 2 accepted.
- **Peak memory:** 1.25 GB median, 1.79 GB max PSS, measured for the whole
  process tree: Python with the classifier loaded (`--classify`), the Playwright
  driver and every Chromium process. PSS, not RSS: Chromium's processes share
  most pages.
- **Passes:** 133 render passes for 75 URLs. A page is rendered again when a
  sub-request host whose robots.txt was unknown turns out to be allowed. The
  robots.txt cache lasts the run, so a platform's later pages need one pass.
- **Sub-requests:** 6,867 checked, 519 blocked by robots.txt (disallowed or
  unavailable) or a non-public address, 159 aborted before their host's robots.txt
  was read. Images, fonts, media and favicons are never fetched.

### DoorDash and Grubhub: not a robots cost

DoorDash store pages render reviews and "Featured Items", then "Something went wrong"
for the full menu (2 of 3 DoorDash menus score 0.04 and 0.16 and are not saved).
Grubhub restaurant pages render categories without items. Blocked sub-requests looked
like the cause (Grubhub's `featureflags` host answers `525` for robots.txt), so three
changes were tried on two DoorDash stores and one Grubhub page (2026-09-29):

| Variant | DoorDash prices (2 stores) | Grubhub prices |
|---|---|---|
| As built | 8, 6 | 0 |
| Up to 6 render passes (4 requests left unchecked instead of 115) | 8, 6 | 0 |
| Unavailable robots.txt on a sub-request host = allow (explicit `Disallow` still obeyed) | 8, 6 | 0 |
| **Control: plain headed Chromium, no robots checks at all** | 8, 6 | 0 |
| Control, scrolled | 0, 0 (content swapped out) | 0 |

The same result without any checks means the robots rules don't cost these menus.
The sites themselves don't serve their full menus to this browser (possibly
automation detection or a delivery-address prompt). The S6d probe had 11 Grubhub
prices on one page earlier the same day. Getting past that would take per-site
handling or disguising the browser, both excluded (universal pipeline; no stealth). The
rules stay as the owner decided.
Toast gift-card and invoice links are disallowed by Toast's real robots.txt (which
only a browser can read); none of them were menus.

## classifier-v2

**What changed:** segmentation now skips dialogs (`role=dialog|alertdialog` or
`aria-modal=true`, `packages/helios_parsing/segment.py`). Every rendered Toast order
page opens with a cookie-consent dialog whose text filled the 2,000 characters the
classifier embeds, which is why `classifier-v1` rejected all of them (0.004–0.28).
The coefficients and threshold are `classifier-v1`'s. Changing the classifier's
inputs makes it a new version, and the verifier bump makes ADR-0015 re-check every
URL `classifier-v1` saved.

Rejected alternatives, measured:

- **Skipping every hidden element** (`hidden`, `aria-hidden`, inline
  `display:none`): wipes out tabbed menus (one spike menu went from 182 prices to 0).
- **Retraining on the rendered pages** (`train_page_classifier --rendered`,
  `classifier-v2-retrained` in the table): equal on the held-out set, nested CV
  precision 0.952 (just at the bar) vs 0.976; no gain for new weights.

| Set (labelled pages) | classifier-v1 as shipped | **classifier-v2** | retrained | Bar (§8) |
|---|---|---|---|---|
| Static, first export: nested CV (179 pages, 48 menus) | 0.976 / 0.833 | identical verdicts to v1 on all 179 | 0.952 / 0.831 (with rendered probe pages) | P ≥ 0.95; R ≥ previous |
| Static, second export: labelled menus (9) | 9 / 9 | 9 / 9 | 9 / 9 | |
| Static, second export: unlabelled (130) | — | identical verdicts to v1 on all 130 | — | |
| **Rendered held-out** (11 pages, 9 menus) | P 1.0, R 1/9 | **P 1.0, R 8/9** | P 1.0, R 8/9 | P ≥ 0.95 ✔; R ≥ v1 ✔ |
| Rendered probe (46 pages, 23 menus; shaped the dialog rule) | P 0.90, R 9/23 | P 0.955, R 21/23 | (training data) | |

- Precision is precision / recall at the shipped threshold 0.508. Static verdicts of
  v2 and v1 were compared page by page: no page changed, so v1's recorded static
  evaluation ([classifier-v1 evaluation](./2026-09-29-classifier-v1-evaluation.md))
  stands for v2.
- **Errors:** the rendered false positive is Arby's `/menu/` (a category page with
  calorie counts, labelled not-a-menu under the spike's "hubs are not menus" rule).
  The misses are two partial DoorDash stores and Taco Palenque's unpriced menu (0.43).
- **Labels** (agent, this session, spike conventions): `menu` = the page lists menu
  items (a platform store page counts even when only part of its menu loaded);
  hubs, home, locator, job, gift-card, rewards and error pages are `not_menu`;
  pages with under ~150 characters of content, or an image-only menu, are excluded.
- **Reproduce:** `python -m apps.menu_pipeline.evaluate_page_classifier --weights
  config/page_classifier_v2.json --data var/spikes/menu-model --labels
  var/spikes/menu_model/labels/pages --rendered <measure_render dir> --report …`
  (`menu` extra; the rendered directory needs its `labels.json`).

## Pi measurement (owner-run)

Headed rendering stays off for Pi runs (`resolve_urls` without `--render`) until
this is recorded. Agents don't access the Pi. Steps at the merged commit:

```bash
# laptop → Pi: the URL list (gitignored)
scp var/spikes/menu-model/render-probe-2026-09-29/s6f/all-urls.json \
    <pi>:~/First-Helios/var/render-measure/all-urls.json
# on the Pi
docker compose -f infra/docker-compose.yml --profile menu build worker
docker compose -f infra/docker-compose.yml --profile menu run --rm --no-deps worker \
    python -m apps.menu_pipeline.models download        # once, if var/models is empty
docker compose -f infra/docker-compose.yml --profile menu run --rm --no-deps worker \
    xvfb-run -a python -m apps.menu_pipeline.measure_render \
    --urls var/render-measure/all-urls.json --out var/render-measure/pi --classify
```

Record `var/render-measure/pi/summary.json` and the per-host table above (seconds,
peak PSS, outcomes) here. Unverified until then: Playwright's arm64 Chromium running
headed on the Pi's Debian image, and whether Toast treats the Pi the same as the laptop.

| Pi measurement | Result |
|---|---|
| Render success (rendered / robots-skipped / failed) | *pending (owner)* |
| Median / p90 / max seconds per render | *pending* |
| Peak PSS (MB) | *pending* |
| `classifier-v2` menus accepted | *pending* |
