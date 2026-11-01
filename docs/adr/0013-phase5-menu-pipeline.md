# ADR-0013: Phase 5 menu pipeline — page classifier, on-device LLM extraction, validator

**Status:** Accepted 2026-09-29 (owner, session P5-0), as amended by Amendments 1–19.
The page classifier parts were accepted earlier the same day (session S6d;
[Amendment 1](#amendment-1-2026-09-29-page-classifier-accepted-early-rendering-decision)).
Rendering for discovery was built in session S6f and open question 3 decided
([Amendment 2](#amendment-2-2026-09-29-rendering-built-open-question-3-decided)).
Open questions 1, 2, 4 and 5 were answered at acceptance
([Amendment 3](#amendment-3-2026-09-29-accepted-open-questions-1-2-4-5-decided)).
Unchanged re-fetches were settled in session P5-2
([Amendment 4](#amendment-4-2026-09-29-unchanged-re-fetches)). Promo labels got their
own grain and the `llama-server` deployment was settled in session P5-3
([Amendment 5](#amendment-5-2026-09-29-promo-label-grain),
[Amendment 6](#amendment-6-2026-09-29-llama-server-deployment)). Extraction and Menu
writes were settled in session P5-4
([Amendment 7](#amendment-7-2026-09-29-extraction-and-menu-writes)). The first held-out
evaluation, the laptop first pass and the disagreement review were settled in session
P5-5 ([Amendment 8](#amendment-8-2026-10-03-laptop-first-pass-first-held-out-evaluation)).
Pipeline version v4 was tuned in P5-7 and failed its held-out evaluation in P5-8
([Amendments 9](#amendment-9-2026-10-03-pipeline-version-v4-tuned-on-the-p5-5-pages)
and [10](#amendment-10-2026-10-09-v4-held-out-evaluation-fails)); v5 was tuned in
P5-9 ([Amendment 11](#amendment-11-2026-10-09-pipeline-version-v5-tuned-on-the-p5-8-pages))
and failed its held-out evaluation in P5-10
([Amendment 12](#amendment-12-2026-10-12-v5-held-out-evaluation-fails)); v6 was tuned in
P5-11 ([Amendment 13](#amendment-13-2026-10-12-pipeline-version-v6-tuned-on-the-p5-10-pages))
and failed its held-out evaluation in P5-12
([Amendment 14](#amendment-14-2026-10-13-v6-held-out-evaluation-fails)); v7 was tuned in
P5-13, with wine lists put out of scope ([Amendment 15](#amendment-15-2026-10-14-pipeline-version-v7-tuned-on-the-p5-12-pages-wine-lists-out-of-scope)),
and failed its held-out evaluation in P5-14 on the false-reject bar
([Amendment 16](#amendment-16-2026-10-15-v7-held-out-evaluation-fails)); v8 was tuned in
P5-15 ([Amendment 17](#amendment-17-2026-10-15-pipeline-version-v8-split-column-headers))
and failed its held-out evaluation in P5-16 on the false-reject bar
([Amendment 18](#amendment-18-2026-10-15-v8-held-out-evaluation-fails)).
The false-reject structure was assessed in P5-17, with production constraints set by the owner
([Amendment 19](#amendment-19-2026-10-15-false-reject-structure-and-production-constraints)).
**Date:** 2026-09-28
**Phase:** 5 (absorbs the menu-reading parts of ROADMAP Phases 3 and 6)
**Decides for:** owner decision G.b ("Phase 5 menu processing uses the spike's
pipeline … replacing ROADMAP's Scrapy-vs-Crawlee framing",
[remediation checklist](https://github.com/First-Helios/First-Helios/blob/b11cf3d084eb9a3ea7c53dfe1fd35cbd32cf5978/docs/reviews/2026-09-22-remediation-checklist.md) §G); the
Capture-targeted Evidence locators that
[ADR-0011 §5](./0011-provenance-endpoints-vs-identity-match-keys.md) left to "the
Phase 5 extraction ADR"; the verifier that
[ADR-0015](./0015-menu-url-reverification.md) option C hands over to.
**Evidence:** [menu-model spike](../spikes/menu-model/README.md) (stages A–F, H and
the usable-price session). Owner answers to its open questions Q2–Q9 are recorded
below (2026-09-28).
**Numbering:** ROADMAP Phase 5 planned a "Scraper framework choice" ADR under the
number 0006, which Gold read models already use. This ADR replaces that plan; S16
rewrote ROADMAP Phases 3, 5 and 6 around it.

## Context

Phase 4 leaves each current venue with a website and zero or more verified menu
URLs in Bronze (`menu-url-discovery` records keyed `<gers>` and
`<gers>|<platform host>`, assigned to the venue's Organization; ADR-0010, ADR-0011
§7). The Menu domain can already store immutable page aggregates with interpretation
kinds `jsonld > dom > pdf > llm` (ADR-0005), and Gold already carries
`price_source_kind` / `content_source_kind`. Nothing reads a menu page yet.

ROADMAP framed Phase 5 as a crawler-framework choice (Scrapy vs Crawlee) followed by
per-rung parsers (ROADMAP Phase 3: JSON-LD, DOM pairing, PDF). The spike showed the
hard part is **reading** pages, not crawling them:

| Finding (spike) | Number |
|---|---|
| Pages with priced structured data (JSON-LD / embedded state) | 3 / 48 menu pages (2 / 34 venues); one site's JSON-LD prices are not on its visible page |
| Pages that need JavaScript to show a menu | 32 / 219 fetched pages (15%) |
| S4 menu-page heuristic (today's verifier) | precision 0.605, recall 0.676 (venue level) |
| [1] Page classifier: potion-base-8M embedding + 7 layout features, logistic regression | precision 0.976, recall 0.833; 22 ms/page on the Pi |
| [4] Qwen3-4B-Instruct-2507 Q4_0, llama.cpp, Pi CPU, prompt v2.3 + repairs v3 + validator v3 | item recall 0.906; price accuracy on accepted rows 0.98–0.99; usable prices 0.84 (tuning pages), 0.74–0.77 (held out) |
| [5] Validator v3 on unseen pages (held-out-3) | corruption catch 0.971, false reject 0.103 |
| Pi throughput / RAM | 7.8 menu pages/h (2 slots, A76 cores); 5.2 GB with `--cache-ram 0` |
| Dropped | block classifier (also as prompt hints), RK3588 NPU, speculative decoding, adaptive Qwen3-8B pass |

Owner decision (spike Q1, 2026-09-27): **one universal process, no per-website
branching.** Allowed: the schema.org JSON-LD reader as a general standard reader,
relational/positional repairs that apply abstractly, and a toolbelt of such generic
fixes chosen per page by a signal (not by site). Gains come from a better model,
classifier or generic data preparation.

## Owner answers to the spike's open questions (2026-09-28)

| Q | Question | Answer |
|---|---|---|
| Q2 | Throughput budget | **Pi batch job.** Accept the ~12-day first pass and change-only monthly runs on the staging Pi, alongside Helios |
| Q3 | Change detection | **Hash of the segmented text** (what the LLM reads), plus the pipeline version. Raw-body hashes and ETags are not the signal |
| Q4 | JS-only menus | **Headless browser in this ADR now** (not deferred to a later ADR) |
| Q5 | Validator bars | **Relax:** catch ≥ 0.97, false reject ≤ 0.12, price accuracy on accepted rows ≥ 0.98; flag pages with unlabeled price runs |
| Q6 | Trust level | **Show accepted `llm` prices, labelled as `llm`**; flagged pages get a lower price confidence |
| Q7 | Pi kernel / NPU | **Plan an rknpu ≥ 0.9.7 upgrade** (with a recovery plan), for other NPU uses |
| Q8 | Cooling | **Recommend** active cooling; not a deployment requirement |
| Q9 | Cuisine tags | **Separate, later ADR** (ADR-0006 deferral stands) |

## Decision

Build Phase 5 as **one generic pipeline** over every verified menu URL, run as an
offline batch job on the Pi that re-extracts only pages whose text changed:

```
menu URL (resolved Bronze record)
  │
  ▼  fetch ─ SiteFetcher (robots, UA, per-host rate limit, 3 MB cap)
  │          └─ static page fails [1]? → headless render once, classify again (§4)
  ▼  [2] segmentation ─ blocks `bNNNN | text`; text hash (§5)
  ▼  [1] page classifier ─ not a menu → skipped Capture; ADR-0015 withdrawal path
  ▼  unchanged text hash and same pipeline version? → stop (no extraction)
  ├─ [0] JSON-LD reader (schema.org Menu/MenuItem/Offer) ──────┐
  ▼  [4] Qwen3-4B-Instruct-2507 Q4_0 via llama-server          │
  │      (prompt v2.3, compact GBNF grammar, ~1.5k-char chunks, │
  │       context line, sparse-chunk retry)                     │
  ▼  repairs toolbelt (stitch v3: generic, positional)          │
  ▼  [5] validator v3 (price/name grounding, binding, sanity) ◄─┘
  ▼  accept / downgrade-to-unknown / reject per row
  ▼  Menu page aggregate (ADR-0005): `llm` (or `jsonld`) interpretation
```

### 1. Stages and what is kept from the spike

- **[1] Page classifier** — `potion-base-8M` static embedding (MIT, 30 MB) plus the
  spike's 7 layout features and a logistic regression. The regression ships as a
  small checked-in weights file (coefficients, threshold, feature list); training
  and threshold selection stay in the evaluation harness (§8), so scikit-learn is
  not a runtime dependency.
- **[2] Segmentation** — stdlib `html.parser` blocks, as in the spike.
- **[0] JSON-LD reader** — a general schema.org reader, kept ahead of the LLM
  (source kind `jsonld`, ranked above `llm` by ADR-0005). Its offers go through the
  same validator: a JSON-LD price that is not on the visible page is downgraded to
  unknown, because the spike found a site whose structured prices differ from its
  page.
- **[4] Extractor** — Qwen3-4B-Instruct-2507 Q4_0 (Apache-2.0, 2.4 GB GGUF) served by
  `llama-server` (llama.cpp, MIT) with greedy decoding, 2 slots, `--cache-ram 0`.
  Process v2.2/v2.3 as measured: compact grammar-constrained JSON, keyed rows,
  ~1.5k-character chunks cut before headings with a context line, one deterministic
  retry for priced-but-empty chunks, runaway cap.
- **Repairs toolbelt** — stitch v3 (description merge, price-echo drop, price fill
  from the price-only line below an unpriced item, labelled-variant completion). A
  repair stays only while it is layout-generic, pays off on a held-out set, and
  still adds something after a model or prompt change; each is re-measured on every
  pipeline version and deleted when the model no longer needs it. New repairs may be
  selected per page by a measured signal (e.g. the label-free coverage signal),
  never by site.
- **[5] Validator** — v3 static checks (price grounding in the same or a linked
  block, name grounding, nearest-price binding, sanity). Outcomes per row:
  **accept**, **downgrade to unknown price** (the item is kept, ADR-0005's derived
  unknown), or **reject** (dropped and counted). It also sets a page flag,
  `unlabeled_price_runs`, when the page prints size-price runs without labels (the
  pattern behind its remaining misses).

Not built: the block classifier (also as prompt hints), per-platform parsers, the
NPU path, speculative decoding, the adaptive Qwen3-8B pass, the ROADMAP Phase 3 DOM
pairing rung (superseded by [4] under the universal-process decision).

### 2. Code layout

- **`packages/helios_parsing/`** (planned by ROADMAP Phase 3; the import-boundary
  test already forbids it from importing SQLAlchemy or `helios_core`): the pure
  stages — segmentation, text hash, JSON-LD reader, chunking and prompt/grammar
  construction, output parsing, repairs, validator. Bytes/text in, plain data out.
- **`apps/menu_pipeline/`**: the I/O — fetch and render, the classifier runtime, the
  `llama-server` HTTP client (`httpx`, already a dependency), Bronze writes, Menu
  writes through `persist_menu`, and a batch CLI (`python -m apps.menu_pipeline.run
  --limit N`) that is resumable and commits one page per transaction.

### 3. Runtime dependencies and Docker/Pi deployment

New runtime dependencies (each needs owner approval by accepting this ADR):

| Component | Licence | Where |
|---|---|---|
| `llama-server` (llama.cpp), pinned build | MIT | own Compose service |
| Qwen3-4B-Instruct-2507 Q4_0 GGUF, 2.4 GB | Apache-2.0 | `var/models/`, not in any image |
| The embedding runtime the spike measured (`fastembed` 0.8.1 on `onnxruntime` 1.30) | Apache-2.0 / MIT | worker image, Python extra `menu` |
| `potion-base-8M`, 30 MB | MIT | `var/models/` |
| Playwright for Python + its Chromium build | Apache-2.0 / BSD-3 | worker image, Python extra `menu` |

- **Images.** The API image stays as it is. The Dockerfile gains a `worker` target
  that installs the `menu` extra and Chromium; discovery and menu-pipeline CLIs run
  from it (the classifier becomes discovery's verifier, §7). `llama-server` runs from
  the upstream llama.cpp server image if its arm64 build matches the spike's
  measured Pi speed; otherwise from a pinned source build of the commit the spike
  used (`infra/llama/Dockerfile`).
- **Compose.** `llama-server` and the worker sit behind a Compose profile (`menu`),
  so `make dev` and CI are unchanged. `llama-server` has no host port (Compose
  network only), `--threads 4 --parallel 2 --cache-ram 0`, and on the Pi a cpuset on
  the four A76 cores; Postgres and the API keep the A55 cores.
- **Model files.** A checked-in manifest lists each model's URL, sha256, size and
  licence; a script downloads into `var/models/` and refuses a checksum mismatch.
  The worker refuses to start if a model's hash differs from the manifest.
- **Where it runs (Q2).** The staging Pi, as a low-priority batch job: first pass
  ≈ 12 days for ~2,300 menu pages (7.8 pages/h), then monthly change-only runs after
  discovery (ADR-0009 cadence). The model call is an HTTP endpoint, so another host
  can run `llama-server` later without code changes.
  *(Drift note, 2026-10-20: the first pass moved to the laptop, Amendment 8 item 1. The
  12-day figure is the spike's estimate. The laptop pass holds 886 distinct page texts in
  6,194 chunks; at the Pi probe's 114 s per chunk on two slots, a Pi primary pass would be
  ~197 h. See the [P5-23 register](../reviews/2026-10-20-p5-23-findings-integration.md),
  F10.)*
- **Pi platform (Q7, Q8).** Phase 5 is CPU-only and must not depend on the NPU. An
  rknpu ≥ 0.9.7 kernel upgrade is planned as a separate owner-run operation with its
  own runbook (backup, recovery path for the headless box, rollback) before any NPU
  use; using the NPU later needs a measured win and an amendment here. Active
  cooling is recommended, not required; each run's report records SoC temperature
  and throttling so a hot box is visible.

### 4. JavaScript-only pages: headless render (Q4)

- **When.** A page is rendered only when its static fetch succeeded (robots allowed)
  and the static segmentation fails the page classifier. It is rendered once,
  segmented and classified again; only the rendered verdict can reject it. This
  keeps render cost on the ~15% of pages that need it and stops ADR-0015 from
  withdrawing a JS-only menu URL that a static check cannot see.
- **How.** One headless Chromium, one page at a time, a fixed navigation timeout,
  images/fonts/media blocked, scripts and the page's own data requests allowed. No
  login, no form submission, no CAPTCHA solving: a bot challenge is a skipped
  Capture (`bot_challenge`). The navigation counts against the host's rate limit and
  uses the Helios User-Agent.
- **Recorded.** The render is its own Capture (`render = headless` in the payload)
  with the serialized DOM in its bundle (§5).
- **Before it is switched on for Pi runs:** measure it on the spike's 32 JS-only
  pages — render success rate, the §8 quality bars on the rendered pages, and Pi
  time and peak RAM per render. Until that measurement is recorded, JS-only pages
  are skipped Captures (`js_only`), counted, and not lost. This is the one part of
  the pipeline the spike did not measure.

### 5. Bronze: change detection, bundles and Evidence locators

- **Namespace.** Menu page content is Bronze source `menu-page`, with the same
  external keys as the menu-URL records (`<gers>`, `<gers>|<platform host>`), and is
  assigned to the same Subject as that menu-URL record. *Amendment 3: a platform
  page (`<gers>|<platform host>`) is assigned to the venue's Establishment instead.*
- **Capture per fetch or render**, with the raw-body `content_hash` and a durable
  **bundle** at `bundle_path` (the replay bundle ADR-0011 §3 reserved the column
  for): `var/replay/menu-page/<yyyy>/<mm>/<sha256>.json.gz` holding the raw body, the
  rendered DOM if any, and the segmented blocks. Not the 7-day discovery cache.
  Non-menu, blocked and failed attempts are Captures with a reason code
  (`not_menu`, `js_only`, `bot_challenge`, …), per ADR-0011 §4.
- **Version payload** = URL, `render`, `segmenter` version and `text_hash` (sha256 of
  the normalized segmented text). Bronze writes a new Version only when the payload
  changes, so **"changed" means a new `menu-page` Version (Q3)**: markup churn, CSRF
  tokens and script bundles do not trigger extraction. ETag / `If-None-Match` may
  skip a fetch; it is never the change signal.
- **What gets extracted.** A current Version without a Menu page for the current
  pipeline version. A text change creates a new Version; a pipeline-version bump
  re-interprets current Versions (ADR-0005 interpretation revision). The queue
  runs new pages first, then changed pages, then re-interpretations.
- **Evidence locators (ADR-0011 §5).** Extracted rows cite the Capture whose bundle
  holds their text, with the Capture-targeted locator
  `blocks:<segmenter version>:b<block>[<start>:<end>]` (a character span in one
  segmented block) and `excerpt_hash = "sha256:" + hexdigest` of that span's text.
  Anyone can check it from the bundle alone, without re-running old code.

### 6. Menu writes and trust (Q5, Q6)

- Accepted rows become a Menu page aggregate through `persist_menu`, with
  `source_kind = "llm"` (or `"jsonld"` for [0]), `method = "menu-pipeline"` and
  `method_version` = the **pipeline version**: model file hash, prompt, repairs,
  validator and segmenter versions. Exact replay of an unchanged aggregate writes
  nothing (ADR-0005 §5).
- **Scope.** The page takes the scope of its `menu-page` record's Subject. Today
  menu-URL records are assigned to the Organization, so pages are Organization
  content and prices (ADR-0005 §11: shared prices are Organization claims, never
  invented location prices). *Open question 1, decided in Amendment 3: platform
  pages take the venue's Establishment scope; own-site pages stay Organization.*
- **Shown to users (Q6).** Accepted `llm` prices flow to Gold and the API like any
  interpretation, ranked lowest, with their kind visible (`price_source_kind`).
  Price confidence is a named constant per outcome, lower on pages flagged
  `unlabeled_price_runs`; page confidence is the classifier probability. Downgraded
  rows are items with unknown price; rejected rows are counted, not stored.

### 7. Relation to ADR-0015: the classifier becomes the menu-URL verifier

ADR-0015 ships first (option B: verifier version in the menu-URL payload,
re-verify instead of reuse, withdraw to `needs_review`, platform content check) and
opens Pi gate 1b without waiting for this ADR's dependencies. This ADR then supplies
option C:

- Page classifier [1] replaces `page_menu_signal` as discovery's own-site verifier
  **and** as the platform-page content check, as verifier `classifier-v1`.
- Bumping the verifier makes ADR-0015's next run re-check every URL saved by the S4
  heuristic, so the first Pi run's errors are corrected, not frozen.
- One fetch serves both: the monthly run fetches each resolved menu URL once; a
  verifier failure takes ADR-0015's withdrawal path, a pass with a changed text hash
  queues extraction.
- Re-verification uses the §4 render-before-reject rule, so JS-only menus are not
  withdrawn for being empty without JavaScript.

### 8. Quality bars and evaluation discipline (Q5)

A pipeline version (model, prompt, repairs, validator, segmenter, classifier) ships
only after one recorded evaluation on a **held-out set not used to tune that
version**:

| Stage | Metric | Bar |
|---|---|---|
| [1] Page classifier | precision / recall | precision ≥ 0.95; recall ≥ the previous verifier's |
| [4]+repairs+[5] | exact price accuracy on accepted rows | ≥ 0.98 |
| [4] | item recall on menu pages | ≥ 0.85 |
| [5] | injected-corruption catch rate | ≥ 0.97 |
| [5] | false-reject rate on correct rows | ≤ 0.12 |
| End to end | usable prices; Pi pages/h; peak RAM | recorded, not gated (spike: 0.74–0.84; 7.8 pages/h; 5.2 GB) |

- The evaluation harness (the spike's `stress/compare.py`, `stress/loss.py`,
  corruption injection, gold-label format) is ported into the repo. Gold labels and
  page bodies stay in gitignored `var/`, as in the spike; CI runs only the
  harness's unit tests on synthetic fixtures (no live network, no real pages).
- A held-out set that was scored and then used for tuning is no longer held out.
- **Monthly spot check:** a small random sample of newly extracted pages is checked
  by hand to catch new layouts (spike finding 9). *Size, labeller and what a failure
  triggers: Amendment 3.*

### 9. Out of scope

Cuisine or other tags (Q9; ADR-0006 deferral stands, separate ADR), per-platform
parsers, images and OCR, the NPU, and deals/promotions (Phase 10). PDF menus are
skipped and counted in v1; promotional rows are deferred to a promo classifier
(Amendment 3).

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| Scrapy or Crawlee + per-rung parsers (ROADMAP Phase 5/3) | Mature crawling; deterministic parsers are cheap | Crawling is not the bottleneck (~1,000 hosts, shallow, monthly; `SiteFetcher` already does etiquette). Structured data priced 3/48 pages; per-layout DOM rules break the universal-process decision |
| **Spike pipeline on the Pi CPU (chosen)** | Measured on real Austin pages; accepted prices 98–99% exact; no external service; model swap is a measured drop-in | ~6–8 min/page, 12-day first pass; 2.4 GB model + new runtime deps; 16–26% of printed prices are not delivered as usable prices |
| Hosted LLM API | Faster, likely higher recall | Paid (sources are "free and public only"), external dependency, page text leaves the box; not measured |
| Qwen3-8B or an adaptive 8B pass | Slightly better on hard pages | ≤ +0.006 usable prices, 4–5× slower on the Pi, a second 5 GB model |
| RK3588 NPU (RKLLM) | 4× faster prefill | Decode ~2× slower (W8A8 only), 4B model does not load on rknpu 0.9.6, closed runtime, hybrid use costs the CPU ~29% |
| Defer the headless browser to its own ADR | Smaller first build | Owner chose to include it (Q4); JS-only pages (15%) would stay skipped longer |
| Keep validator bars at 0.99 / 0.10 | Stricter | Remaining misses are unlabeled size-price swaps that text cannot distinguish; would block Phase 5 or hide most prices |

## Consequences

- **Easier:** one code path for every site; improvements come from swapping the
  model, prompt or a generic repair and re-running the harness. Every accepted price
  points at a stored byte span, so a reader can check it.
- **ADR-0015's re-verification becomes retroactive** for the classifier: no manual
  clean-up of the first Pi run's menu URLs.
- **Harder:** the Pi carries a multi-day batch job; a pipeline-version bump means a
  re-interpretation pass of up to ~12 days, so bumps are batched and deliberate.
- **Heavier images and more to operate:** the worker image grows by Chromium and the
  ONNX runtime (hundreds of MB); a second long-running service (`llama-server`); a
  model manifest with checksums; durable bundles on the Pi disk (backup is Phase 8).
- **Headless rendering is unmeasured** and widens the fetch surface (scripts run,
  the page's own data requests go out); §4 keeps it off until measured.
- **Data loss is accepted:** ~16–26% of printed prices are not delivered as usable
  prices (held-out 0.74–0.77 usable, tuning pages 0.84); the largest share (8–13%)
  belongs to items the model never extracts, closed only by a better model or better
  generic data preparation.
- **Docs:** ROADMAP Phases 3, 5 and 6 were rewritten around this pipeline in S16.

## Implementation slices (after acceptance)

Each slice is a PR; ⚠ slices touch deps or `infra/` and stop for owner review.
State as of 2026-09-29 (Amendment 3):

1. ⚠ Worker image target, `menu` extra, `llama-server` service and model manifest.
   *Built:* the `worker` target, `menu` extra and checksummed manifest came with
   slice 4 (S6d part 2, #52); the `llama-server` Compose service and the Qwen3-4B
   manifest entry in P5-3 (Amendment 6). Remaining: the owner-run Pi check that the
   upstream image matches the spike's speed.
2. `packages/helios_parsing`: segmentation, text hash, JSON-LD reader, chunking,
   repairs, validator, with the ported harness and synthetic tests. *Segmentation
   and the v3 price tokens exist (#52; dialog skip #54).* The harness's gold-label
   format carries the `promo` mark (Amendment 3).
3. `menu-page` Bronze writes (Captures, bundles, Versions, locators) and the batch
   CLI, without extraction. Platform pages are assigned to the Establishment, and
   PDF menu links are counted in discovery and the run report (Amendment 3).
   *Built in P5-2 (Amendment 4).*
4. Classifier runtime; ADR-0015 verifier bump to `classifier-v1` (after S6d).
   *Built:* S6d part 1 (#51, re-verification) and part 2 (#52, `classifier-v1`);
   S6f (#54) bumped the verifier to `classifier-v2`.
5. Extraction and Menu writes; first held-out evaluation recorded.
   *Built in P5-4 (Amendment 7):* the `llama-server` client, extraction over
   `menu-page` Versions and Menu writes (`python -m apps.menu_pipeline.extract`).
   *First held-out evaluation recorded 2026-10-03 (P5-5, Amendment 8): **fails §8***
   (price accuracy 0.963, item recall 0.837, gold-row false reject 0.306; catch 0.988).
   Remaining: a pipeline version that passes on a fresh held-out set; extraction runs
   wait for it. The Menu-write commit cost (Amendment 8 item 6) is fixed by ADR-0005
   Amendment 1 (revision `db40e9424cba`); its laptop re-time (RUN-A-01) is pending.
6. ⚠ Headless render, its measurement on the 32 JS-only pages, then enablement.
   *Built in S6f (#54):* headed Chromium under Xvfb (Amendments 1–2), measured on a
   laptop over 75 URLs, 23 of them the spike's JS-only own-site pages. Remaining: the
   owner-run Pi time and memory measurement (Pi gate 1b), and the §8 quality bars on
   rendered pages, which need slice 5.
7. Owner: rknpu upgrade runbook (independent of 1–6).

## Open questions for the owner

1. **Page scope.** Menu-URL records (and so `menu-page` records) are assigned to the
   Organization, so every extracted price is an Organization claim. For a chain,
   a per-location platform page (`<gers>|<host>`) really describes one location.
   Recommended: Organization scope for v1; per-location scope for platform pages in
   a follow-up once ADR-0015's chain-homepage guard exists. *Decided 2026-09-29:
   platform pages take Establishment scope from v1
   ([Amendment 3](#amendment-3-2026-09-29-accepted-open-questions-1-2-4-5-decided)).*
2. **PDF menus** (linked from ≥ 6 sample sites; `SiteFetcher` decodes bodies to text,
   so the spike never read them): v1 skips them as `pdf` Captures, or add a PDF
   text-layer reader (a new dependency) feeding the same segmentation and LLM path?
   *Decided 2026-09-29: skipped and counted in v1 (Amendment 3).*
3. **Rendered sub-requests.** robots.txt is checked for the page Helios navigates
   to; the requests the page's own scripts make (e.g. a platform's menu API) are not
   checked separately, as in a normal browser. Acceptable, or check robots for each
   sub-request host too? *Decided 2026-09-29: check every sub-request
   ([Amendment 2](#amendment-2-2026-09-29-rendering-built-open-question-3-decided)).*
4. **Spot-check size and owner:** e.g. 5 pages per monthly run, labelled by an agent
   and confirmed by the owner? *Decided 2026-09-29: 10 pages, labelled blind by an
   agent, the owner confirms disagreements (Amendment 3).*
5. **Promotional rows** ("BOGO", "half off") in menus: ROADMAP §2 / Phase 5 wants them
   excluded from menu prices; the spike did not measure them. Handle as a generic
   repair now, or leave to Phase 10? *Decided 2026-09-29: deferred to a promo
   classifier, no rule now; label foundations in Phase 5 (Amendment 3).*

## References

- [Menu-model spike](../spikes/menu-model/README.md) (results, findings,
  recommendation, open questions); spike code on branch `spike/menu-model`
- [ADR-0005](./0005-immutable-menu-snapshots-and-selection.md) (interpretation
  kinds, streams, replay); [ADR-0006](./0006-gold-menu-read-models.md) (tag deferral)
- [ADR-0010 Amendment 3](./0010-website-and-menu-url-resolution.md#amendment-3-2026-09-23-menu-page-verification-and-platform-sites)
  (S4 verifier); [ADR-0011](./0011-provenance-endpoints-vs-identity-match-keys.md)
  §3–§5 (bundles, outcomes, locators); [ADR-0015](./0015-menu-url-reverification.md)
  (re-verification; option C = this classifier)
- [ADR-0002](./0002-containerization.md) (single image, Compose, arm64)
- Code: `apps/discovery/web_client.py` (`SiteFetcher`), `apps/discovery/url_pipeline.py`
  (menu-URL keys and assignment), `packages/helios_core/domains/menu/contracts.py`
  (`PageInput`, `SourceKind`), `test/import_boundaries.py` (`helios_parsing` rule)

## Amendment 1 (2026-09-29): page classifier accepted early; rendering decision

Owner decisions in session S6d (ADR-0015 acceptance):

1. **Accepted now:** stage [1] page classifier (`potion-base-8M` + layout features +
   logistic regression, weights checked in, §1); its runtime dependencies
   (`fastembed` on `onnxruntime`, the `menu` extra, §3); the model manifest and
   checksum-refusing download (§3); the worker image target that discovery runs
   from (§3); and §7, the classifier as ADR-0015's verifier `classifier-v1` for
   own-site **and** platform pages. Slices 1 (without `llama-server`) and 4 are
   pulled forward into S6d, ahead of slices 2–3; the segmentation and price-token
   code the classifier's features need comes with it. Everything else in this
   ADR stays Proposed.
2. **Rendering (§4), for session S6f.** A probe of the spike sample's platform links
   (ADR-0015 Amendment 1 item 8) showed Toast answers `403` to the static fetcher
   and to headless Chromium, but loads for **headed** Chromium; Square, Clover and
   Grubhub render headless. The owner chose: render with headed Chromium under a
   virtual display (Xvfb) in the worker image, the User-Agent always carrying the
   Helios token, robots.txt obeyed and the per-host rate limit applied; never
   stealth plugins, User-Agent spoofing or challenge solving. A page that still
   answers `403` or a bot challenge is a skipped Capture. Consequently §4's trigger
   widens: a platform page is rendered when its static fetch is refused (`403`) or
   fails the classifier, not only after a successful static fetch. Platform terms
   of service may forbid automated access even where robots.txt allows it; the
   owner accepted that risk for robots-allowed pages. The §4 measurement (render
   success, quality bars on rendered pages, Pi time and RAM) still gates enabling
   it on Pi runs.
3. **Built in S6d part 2 (2026-09-29).** `packages/helios_parsing/` (segmentation,
   the validator's v3 price tokens, the classifier's page text and layout features),
   `apps/menu_pipeline/` (`models.py`: manifest `config/models.yaml`, checksum-refusing
   download and verification; `classifier.py`: plain-Python scoring of the checked-in
   weights `config/page_classifier_v1.json`; `train_page_classifier.py`: training and
   the §8 evaluation, run with an ephemeral scikit-learn, never installed), the `menu`
   extra (`fastembed` 0.8.1), the `worker` Dockerfile target and a Compose `worker`
   service behind the `menu` profile (no `llama-server` yet). `resolve_urls` uses
   `classifier-v1`. Evaluation:
   [2026-09-29-classifier-v1-evaluation.md](../reviews/2026-09-29-classifier-v1-evaluation.md)
   (nested CV precision 0.976 / recall 0.833; held-out 9/9 menus, 21/21 accepted pages).
   It rejects every rendered Toast order page, so S6f trains a successor on rendered
   platform pages.

## Amendment 2 (2026-09-29): rendering built; open question 3 decided

Owner decisions in session S6f, and what was built (`apps/menu_pipeline/render.py`,
render triggers in `apps/discovery/web_client.py`):

1. **Open question 3 → check every sub-request.** Each request a rendered page makes
   (scripts, XHR/fetch, frames) is checked against its own host's robots.txt for the
   Helios token and must go to a public address; disallowed or unavailable requests
   are aborted and counted. Googlebot's renderer does the same. Images, fonts, media
   and favicons are never fetched.
2. **robots.txt is read through the browser.** A static fetch of
   `order.toasttab.com/robots.txt` gets a Cloudflare `403` challenge (RFC 9309: allow
   all) while a browser gets the real file (a redirect to `www.toasttab.com`, which
   disallows gift cards, cart and checkout). The renderer loads each host's robots.txt
   in the browser, following up to five redirects: 2xx → its rules; 4xx other than 429
   → allow all; 429, 5xx, unreachable or still challenged → the host is skipped. The
   static fetcher is unchanged, and its robots.txt must allow a page before it is
   rendered at all.
3. **Platform host aliases.** `toast.app` (a Toast link redirected there) and
   `cloveronline.com` (Clover links redirect to `<venue>.cloveronline.com`) are added
   to the ordering-platform list as aliases sharing `toasttab.com` / `clover.com`
   record keys. A render's own navigation may stay on its site or move within one
   platform; any other cross-host redirect is refused (`redirect_refused`).
4. **Interception is Chrome DevTools Protocol `Fetch`, not Playwright routes.** A live
   check showed Playwright's `page.route` is not called for redirect hops, so a
   redirect could leave the site unchecked. `Fetch.requestPaused` pauses every hop.
5. **Sub-request robots.txt is read between passes.** A sub-request to a host whose
   robots.txt isn't known yet is aborted; after the page settles those hosts are read
   and, if any aborted request is allowed, the page is rendered again (at most three
   passes). Reading them inside the interception handler started one read per
   parallel request and stalled the browser on a DoorDash page (hundreds of requests
   to one CDN). The robots.txt cache lasts the run.
6. **Triggers (for discovery).** Rendered only when static robots.txt allows the page
   and the static result can't verify it: a platform page that answers `403` or fails
   the classifier; an own-site candidate that looks JavaScript-only (scripts and
   fewer than 300 characters of segmented text; all 32 spike `js_only` pages qualify),
   at most two per site; re-verification renders before it rejects. A rendered verdict
   can withdraw a URL; a render that fails or meets a challenge keeps it
   (`bot_challenge`, `render_timeout` are not withdrawal reasons). A menu URL verified
   from a render records `render: headed-chromium` in its payload; a later static pass
   drops it.
7. **Worker image.** Playwright 1.63.0 joins the `menu` extra; the `worker` target
   installs its Chromium (`--no-shell`) with system libraries plus Xvfb (image 1.91 GB).
   Compose runs the worker with `init: true` (`xvfb-run` hangs as PID 1) and
   `shm_size: 1gb`. `resolve_urls --render` turns rendering on; it stays off for Pi
   runs until the Pi measurement below is recorded.
8. **Measured (laptop), Pi pending.** On the S6d probe's 60 URLs plus 15 held-out
   platform links: 67/75 rendered, 8 robots.txt refusals, no bot challenge (Toast and
   DoorDash load headed); median 13.9 s, max 65.6 s per render; peak 1.79 GB PSS for
   the whole process tree. DoorDash and Grubhub don't serve their full menus to this
   browser even with no robots checks (a measured control), so that loss is not
   caused by the robots rules. Details and the owner-run Pi steps:
   [S6f render measurement](../reviews/2026-09-29-s6f-render-measurement.md). The
   §4 gate (Pi time and memory) stays open until the Pi numbers are recorded.
9. **`classifier-v2`.** Segmentation (stage [2]) now skips dialogs (`role=dialog`,
   `alertdialog`, `aria-modal`): rendered Toast pages open with a consent dialog
   whose text filled the classifier's input. v2 keeps v1's coefficients; its static
   verdicts equal v1's on every spike page, and on rendered pages it accepts 8/9
   held-out menus (v1: 1/9) with no false positive. Retraining on rendered pages
   gave no gain. The segmenter change also applies to extraction when it is built.

## Amendment 3 (2026-09-29): accepted; open questions 1, 2, 4, 5 decided

Owner decisions in session P5-0, with the code and data facts checked before the
questions were put:

1. **Accepted as a whole.** This approves the remaining runtime dependencies in §3:
   the `llama-server` Compose service (pinned llama.cpp build, `menu` profile) and
   the Qwen3-4B-Instruct-2507 Q4_0 entry in the model manifest. Each ⚠ slice still
   stops for owner review of its diff. Acceptance does not switch anything on: the
   §4 Pi measurement still gates `--render` on Pi runs, and §8's held-out evaluation
   still gates each pipeline version.
2. **Open question 1, page scope: platform pages take Establishment scope.**
   - *Facts.* Discovery mints one Organization per new Establishment
     (`apps/discovery/pipeline.py`, `_mint_establishment`); there is no chain
     Organization, so Organization scope doesn't mix locations today. But
     [ADR-0007](./0007-gold-price-index-projection.md) §5 excludes Organization-scoped
     rows from the lat/lon price index, so Organization scope alone would leave that
     index empty, and switching later would remap every page stream (ADR-0005 §5).
     ADR-0015's chain-homepage guard (Amendment 1 item 6, #51), the stated
     precondition, exists.
   - *Rule.* A `menu-page` record keyed `<gers>|<platform host>` is assigned to the
     Establishment that the Overture record `<gers>` resolves to. An own-site
     `<gers>` page keeps its menu-URL record's Subject, the Organization. When one
     platform URL is the saved menu URL of more than one current venue, nothing ties
     it to one location, so those pages stay Organization. Menu-URL records are
     unchanged (still Organization), which keeps Organization readiness as
     [ADR-0012](./0012-venue-lifecycle.md) §5.2 defines it.
   - *Eligibility.* Menu admission needs an eligible Establishment (ADR-0005 §7);
     ADR-0012 §5.3 promotes one when its Place and Organization are eligible, and the
     Organization is eligible once its website is assigned, before any menu URL. A
     page whose Establishment is not eligible yet keeps its Capture and Version; its
     Menu write is counted (`scope_not_eligible`) and retried next run.
   - *No migration.* `PageInput.subject_kind` and `gold.current_menu`
     (`ck_gold_scope_kind`) already allow `establishment`; `assign_source_record` is
     kind-agnostic.
   - *Selection and Gold.* Establishment prices are local contenders (ADR-0005 §11)
     and enter the ADR-0007 geo index; own-site Organization prices stay separate
     Organization claims, never merged or fanned out. Own-site menus of
     single-location venues therefore stay out of the geo index; that gap belongs to
     the price-index implementation (ADR-0007), not to this ADR.
   - *Residual risk.* A venue whose Overture website is itself a platform page gets
     no address check (the guard reads homepages); only the shared-URL rule above
     covers it.
3. **Open question 2, PDF menus: skipped and counted in v1.**
   - *Facts.* Discovery saves only HTML (`web_client._is_html`; anything else is
     `not_html`, an ADR-0015 withdrawal reason), and `config/sources.yaml` names no
     PDF, so verified menu URLs contain no PDFs by construction. A PDF-only venue
     ends with no menu URL, which Phase 5's "done when" cannot see. Estimate from the
     spike sample (250 venues, `pages.jsonl`, a heuristic over unlabelled pages): 17
     (6.8%) link a menu-named PDF; about 12 of them also have a priced HTML page;
     about 5 (2% of venues) look PDF-only.
   - *Rule.* No PDF reader in v1. A menu fetch that returns a PDF (e.g. after a
     redirect) is a skipped Capture `pdf`. The loss is counted where it is seen:
     discovery counts venues left without a menu URL whose fetched pages link a
     menu-named PDF (`menu_pdf_only`), and the menu-pipeline run report counts
     menu pages that link one. A reader is decided on the first Pi pass's numbers;
     it would be a new dependency (stop-and-ask) and would need discovery to accept
     PDF menu URLs (an ADR-0010/0015 amendment) and a classifier path for PDF text.
     Rows an LLM reads from PDF text are kind `llm`; ADR-0005's `pdf` rank is for a
     deterministic PDF parse.
4. **Open question 4, spot check: 10 pages, agent-labelled, owner confirms
   disagreements.**
   - Each monthly run samples 10 newly extracted pages at random (all of them if
     fewer), with the seed recorded in the run report.
   - An agent labels them blind, in the gold-label format, from the Capture bundles,
     without seeing the pipeline's output. The harness scores the §8 extraction bars
     (price accuracy on accepted rows, item recall; usable prices recorded). The owner
     reviews only the rows where the agent's label and the pipeline disagree; the
     confirmed labels are final.
   - Pass = the §8 bars on the pooled sample. A failure is recorded as a finding in
     `docs/reviews/`, the sampled pages become the next held-out set (scored before
     any tuning on them), and the next pipeline version must pass on them. The run
     and Gold are not blocked.
   - Why labels: spike finding 9's failure (a repair accepting printed but wrong
     prices on an unseen layout) passes the validator, so label-free signals (reject
     rate, coverage) cannot see it. The spike's gold averaged ~65 prices per page, so
     10 pages is ~650 prices.
5. **Open question 5, promotional rows: deferred to a promo classifier; no rule
   now.**
   - The owner's plan is a classifier model for promo detection and parsing, which
     should outperform a generic lexicon rule, so no rule-based flag or repair is
     built now. The promo classifier is planned for ROADMAP Phase 10.
   - *Foundations now (Phase 5).* The gold-label format carries a `promo` mark per
     row, and every set labelled from now on (held-out sets, spot checks) marks promo
     rows, so the future classifier has training and evaluation data. The harness
     reports promo-marked rows that the pipeline stored as prices (recorded, not
     gated). Bundles already keep the segmented blocks and locators (§5), so the
     classifier can re-read stored pages without refetching; it ships as a
     pipeline-version bump, i.e. a re-interpretation (ADR-0005).
   - *Accepted risk.* Until then, a promo row with a printed price may be stored as an
     `llm` price: the validator cannot reject a grounded non-item (spike finding 2),
     ADR-0005 has no recurring schedules (a happy-hour price reads as always-on), and
     the ≥ 0.98 price-accuracy bar does not see promos on sets labelled before this
     amendment.
   - ROADMAP §2 and Phase 10 are amended: promotional rows are not parked during
     Phase 5 extraction; Phase 10 starts with the promo classifier over stored bundles.
6. **Implementation slices updated** to what is built: slice 4 (#51, #52, #54),
   slice 1 except `llama-server` (#52), part of slice 2 (#52, #54) and slice 6 except
   the Pi measurement and the rendered-page quality bars (#54).

## Amendment 4 (2026-09-29): unchanged re-fetches

Owner decisions in session P5-2 (slice 3), before any code:

1. **Unchanged re-fetches.** A `menu-page` fetch or render whose Version payload (URL,
   render, segmenter, text_hash) equals the record's latest Version is a `succeeded`
   Capture with its `content_hash` and bundle, but no Version and no Evidence
   (provenance command `record_unchanged_capture`). This narrows ADR-0011 §4
   ("succeeded → Version") for the `menu-page` namespace only; ADR-0015 Amendment 1
   (menu-URL re-checks append a Version) is unchanged. Evidence locators keep citing
   the Capture that created the Version.
2. **Slice-3 choices** the ADRs left open, all taken as recommended:
   - *Not-a-menu pages* are counted (`skipped/not_menu`); withdrawing the menu URL
     stays with discovery's ADR-0015 re-verification until the Phase 6 monthly run
     wires §7's "one fetch serves both".
   - *Queue and resuming.* The unit of work is one menu URL, with every record that
     saved it written in one transaction. A URL is not fetched again within 20 days
     of its last `menu-page` Capture (`REFETCH_WINDOW`, like `RECRAWL_WINDOW`), unless
     a record saved it after that fetch and has no Version for it. Never-fetched URLs
     go first, then the oldest fetch, ties by record key.
   - *PDF-only venues.* Discovery records `failed/menu_pdf_only` instead of
     `no_menu_found` when no menu page verified but a fetched page links a
     menu-named PDF (a `.pdf` link whose text or path carries a menu-lexicon word),
     and counts it; the menu-page run report counts pages that link one.
   - *Scope changes* between runs (a platform URL becomes shared, or stops being
     shared) remap the `menu-page` record.
   - *Bundles.* Every Capture that read an HTML body has one (succeeded, unchanged,
     `not_menu`, `js_only`; not `pdf` or failed fetches), content-addressed, with no
     pruning before Phase 8 backup. Spike pages average ~39 KB gzipped (p95 134 KB):
     roughly 90 MB a month for ~2,300 pages.
   - Not built: ETag / `If-None-Match` (§5 allows it; the fetcher has no conditional
     GET and a `304` has no body to hash).

## Amendment 5 (2026-09-29): promo label grain

Owner decision in session P5-3 (carried over from P5-2's D1; the text was proposed
in PR #59). It refines Amendment 3 item 5, which put a `promo` mark on each gold row:

- *Promo labels get their own grain.* A promotion is labelled as its own entry, not
  only as a flag on a menu row: its scope (items, sections, or the whole menu), its
  terms (e.g. "half off", "BOGO", a fixed deal price) and its conditions (days,
  hours, channel, minimum spend), each with a Capture-targeted locator. Rows that
  print a promo price keep the item-level `promo` mark so `promo_rows_stored` still
  works. The promo classifier (Phase 10) trains on these entries; whether Menu
  storage gains a matching grain is decided with it (a schema change, stop-and-ask).
- Nothing is built by this amendment. The item-level `promo` flag in the gold-label
  format (#58) stays as the interim mark; the promo-entry label format is added when
  the first set is labelled with it.

## Amendment 6 (2026-09-29): `llama-server` deployment

Owner decisions in session P5-3 (slice 1 remainder), before any code. §3 settled
the threads, slots, host prompt cache, profile, network and model placement; these
settle the rest.

1. **Image: upstream, pinned by digest.** The spike ran llama.cpp `84e76d8`
   (= build `b11173`, a native GCC 11.4 build with
   `-mcpu=cortex-a76.cortex-a55+dotprod`). Upstream publishes server images daily,
   not per build, so none exists at `b11173`. The service uses
   `ghcr.io/ggml-org/llama.cpp:server-b11176` (amd64 + arm64), pinned by its index
   digest: three commits after the spike's (two Hexagon changes, one multi-GPU
   tensor-split fix), none on the CPU path. It is built with GCC 14,
   `GGML_NATIVE=OFF` and `GGML_CPU_ALL_VARIANTS=ON` (the CPU variant is chosen at
   runtime), runs as root, and is ~1.2 GB. §3's condition ("if its arm64 build
   matches the spike's measured Pi speed") is checked by an owner-run Pi bench
   ([runbook](../reviews/2026-09-29-llama-server-pi-check.md)): pass when upstream's
   prompt and generation tokens/s are each ≥ 95% of the spike binary's, same flags,
   same cores, same request. On a fail, a follow-up PR adds `infra/llama/Dockerfile`,
   a pinned source build of `84e76d8`. Greedy output identity between the two builds
   is recorded, not gated.
2. **Model file.** Manifest entry `Qwen3-4B-Instruct-2507-Q4_0`: publisher
   `unsloth/Qwen3-4B-Instruct-2507-GGUF` at revision `a06e946b…`, file
   `Qwen3-4B-Instruct-2507-Q4_0.gguf`, 2,375,773,280 bytes, sha256 `e0ba675d…13be2`,
   Apache-2.0. The size and sha256 match both the publisher's listing and the spike's
   own copy (the spike did not record the publisher; another publisher's Q4_0 has a
   different hash). Downloaded with the existing checksum-refusing downloader into
   `var/models/<name>/`, mounted read-only.
3. **Checksum refusal: an init step.** A one-shot `llama-model-check` service (API
   image, no database) runs `models verify` for the GGUF; `llama-server` starts only
   after it exits 0. §3's "the worker refuses to start" is met for the server this
   way; the slice 5 client may also check the model path `/props` reports. The worker
   image's default command now verifies only the classifier's files.
4. **Pi cores: an override file.** `infra/docker-compose.pi.yml` pins `llama-server`
   to CPUs 4-7 (the A76 cores) and Postgres and the API to 0-3. Other hosts don't
   use it. On the Pi it is passed as a second `-f` (a `COMPOSE_FILE` in `.env` is
   ignored when `-f` is given).
5. **Health.** A Compose healthcheck on `/health` (503 while loading, 200 when ready;
   start period 120 s). The worker does not depend on `llama-server` (every
   `resolve_urls` run would otherwise start a ~5 GB server); slice 5 chooses between a
   client-side wait and a dedicated extraction service.
6. **Flags, limits, restart.** The spike's measured set: `--threads 4 --parallel 2
   --ctx-size 8192` (4,096 tokens per slot) `--flash-attn on --cache-type-k q8_0
   --cache-type-v q8_0 --cache-ram 0`. `mem_limit: 8g` (spike peak RSS 5.2 GB; the
   spike's original RAM bar). `restart: unless-stopped`, so a crash mid-run restarts
   it; the owner stops it after a run. A restart by the restart policy does not re-run
   `llama-model-check`; the model directory is read-only in the container.

## Amendment 7 (2026-09-29): extraction and Menu writes

Owner decisions in session P5-4 (slice 5), before any code; all as recommended.
Code: `apps/menu_pipeline/llama_client.py`, `extraction.py`, `menu_writes.py`,
`extract.py`, `packages/helios_parsing/menu_shape.py`.

1. **Readiness (X1, carried from Amendment 6 item 5): client-side wait.** The CLI
   polls `/health` for up to 300 s, then checks `/props`: the served file must be
   the manifest's GGUF and the server must have 2 slots, else it refuses to run.
   It doesn't re-hash the file (`llama-model-check` does at `up`). No `infra/`
   change and no dedicated extraction service.
2. **Pipeline version (X2).** Each component has a version constant (`prompt-v2.3`
   for the prompt, grammar, token cap and sparse retry; `chunk-v2.1`;
   `repairs-v3` for the output repairs and stitch v3; `validator-v3`;
   `segment-v2`; `jsonld-v1`), and `method_version` is their composite string with
   the model (`<manifest name>@<sha256 prefix>`) and the page classifier's name,
   which gives page confidence. This includes the classifier, as §8 lists it,
   where §6's list did not. `llm`:
   `<model>;prompt-v2.3;chunk-v2.1;segment-v2;repairs-v3;validator-v3;<classifier>`;
   `jsonld`: `jsonld-v1;validator-v3;segment-v2;<classifier>`. A page is up to date
   when its `llm` head is on the record's latest Version with exactly this string.
   **Raw answers are kept** content-addressed by the extractor's inputs (model,
   prompt, chunking, segmenter) and the page's text hash
   (`var/replay/menu-extract/`, in the harness's record format): a repairs,
   validator or classifier bump re-validates saved answers without the model; a
   model, prompt, chunking or segmenter bump runs it again.
3. **Unit of work (X3).** A sibling CLI, `python -m apps.menu_pipeline.extract
   --limit N` (`--limit` counts pages taken), reads each due Version's blocks from
   its Capture's bundle (no refetch; a bundle whose text hash differs from the
   Version's is a failure, `bundle_mismatch`). Due: the latest Version of every
   resolved `menu-page` record without an `llm` page at the current version;
   order new, changed, re-interpretation, then key (§5). Two requests in flight
   over a look-ahead of pages (the spike's measured setup); one page per
   transaction. A request that times out (1800 s), fails in transport or answers
   5xx is sent once more; a chunk that still fails fails its page, which writes
   nothing and stays due; after 3 failed pages in a row the run stops and exits 1.
   Output cut off by the token cap keeps its recovered rows (counted). A page with
   nothing kept writes an empty `llm` page, so it is done at this version.
4. **Menu writes (X4).** `llm` and `jsonld` are separate streams of the record
   (root key `page`); the JSON-LD reader runs on every page and its rows pass the
   same validator. A `jsonld` page is written when the page has JSON-LD items or
   the stream's head still has items (an empty successor, so JSON-LD that
   disappeared stops outranking the LLM). The first page of a stream is
   `initial`, a page on a newer Version an `observation`, a re-interpretation of
   the same Version a `correction`. Downgraded rows are items without a price row;
   rejected rows are counted by reason. Price confidence 0.98 (measured accuracy
   on accepted rows), 0.90 on pages flagged `unlabeled_price_runs`; page
   confidence is the classifier probability recomputed from the bundle. A scope
   that isn't eligible yet is counted `scope_not_eligible` and retried
   (Amendment 3).
5. **Native keys (N1; not settled before).** Gold enumerates only nodes whose path
   carries `source_native_key`s, and the Menu proposal (plans/0002, "Keys") admits
   only genuine source IDs or version-local fallbacks, never name continuity. LLM
   and JSON-LD rows have no source IDs, so nodes carry **version-local** keys
   `v<version id>:<block>:<normalized text>`. Accepted prices reach Gold without
   claiming a dish is the same one across Versions or streams. Consequences: a
   dish's Gold target changes with each new Version; a dish on a JSON-LD page is
   two Gold targets (one per stream). A node needs a stable ancestor path for a
   native key (`ck_menu_graph`), so items under the structural `Unsectioned`
   grouping carry none and are stored but not projected to Gold (counted
   `unsectioned_items`).
6. **Shape (N2).** A section the extractor named is kept when its name is printed
   at or before its first item (a non-chrome block with exactly its words, or a
   heading containing them), with that span as Evidence; otherwise its items go to
   `Unsectioned`. One item per (section, name block, normalized name); a labelled
   price prices a variant of that label, unlabeled extra prices stay separate
   price rows on the item. No descriptions or dietary tags are read
   (`dietary_tags` is the empty list a replacement item requires). The run report
   records SoC temperature and the CPU frequency cap where `/sys` shows them;
   `promo_rows_stored` comes from the evaluation harness (labels only).
7. **Found while building: Evidence is committed first.** Menu admission accepts
   only committed Evidence (ADR-0005 §7), so each page commits its
   Capture-targeted Evidence, then writes its Menu pages in a second transaction.
   Evidence is immutable and reused per locator, so a page whose Menu write then
   fails (e.g. `scope_not_eligible`) leaves nothing to undo. Also, JSON-LD lives
   in scripts, which the text hash excludes (§5), so a JSON-LD-only change makes
   no new Version and isn't re-read until the visible text changes.
8. **First held-out evaluation (X5): follows this slice.** Every scorable gold page
   (33) has been scored, so none is held out for this version. The evaluation uses
   a fresh sample of 10 menu pages from venues the spike never saw (seed
   recorded), labelled blind by an agent in a separate session before any
   extraction, with the owner confirming disagreements (Amendment 3 item 4's
   procedure), scored on a laptop against the pinned `llama-server` image with the
   manifest's GGUF (`python -m apps.menu_pipeline.evaluate extract`, then
   `compare`, `loss`, `corrupt`). Pi pages/hour and peak RAM are recorded with the
   owner's Pi check. Pi extraction runs wait for this evaluation (§8).

## Amendment 8 (2026-10-03): laptop first pass, first held-out evaluation

Owner decisions in session P5-5 (Amendment 7 item 8's evaluation), before any sampling
unless noted. Record:
[2026-09-30-p5-held-out-evaluation.md](../reviews/2026-09-30-p5-held-out-evaluation.md).

1. **The first pass runs on the laptop; the Pi hosts long-term.** This changes §3's
   "Where it runs (Q2)" for the first pass only. The first full pass (Overture seeding,
   `resolve_urls`, the `menu-page` fetch and, once a pipeline version passes §8,
   extraction) runs on the owner's laptop against a persistent local database, for speed
   during development; the staging Pi takes the monthly change-only runs and serving
   afterwards. The Pi gates (README: 1a, 1b, the `llama-server` Pi check) gate Pi runs,
   not the laptop pass. How the laptop pass's data (database, `var/replay/` bundles and
   raw answers) reaches the Pi is not decided here. Done 2026-10-02 up to the fetch:
   9,996 venues, 1,635 menu-URL records on 894 distinct URLs, 1,632 `menu-page`
   Versions (static only); the crawl is sequential (~5–9 venues/min), about a day.
2. **First held-out evaluation: fails.** The slice-5 version
   (`…;prompt-v2.3;chunk-v2.1;segment-v2;repairs-v3;validator-v3;classifier-v2`) on 10
   static own-site pages drawn from the laptop pass (seed 20260930; venues and hosts the
   spike saw excluded; one page per venue and site): price accuracy on accepted rows
   **0.963**, item recall **0.837**, false reject on gold rows **0.306** (bars 0.98,
   0.85, 0.12); corruption catch **0.988** passes; usable prices 0.620. Per §8 the version
   is not cleared for extraction runs; these 10 pages are now tuning pages; the next
   version is scored on a fresh draw from the same laptop pass (new seed, excluding the
   18 venues labelled here). Static only (E1b): the rendered-page bars stay with slice 6.
3. **Disagreement review: a blinded adjudicator, owner confirms label changes.** For
   this evaluation (and available to later ones), Amendment 3 item 4's owner review is
   done in two steps: a fresh agent judges every row where the blind label and the
   pipeline disagree from the page text, without knowing which reading came from which
   side; the owner confirms every label change it proposes and decides class questions.
   Labels it upholds stay as blind-labelled. Both label sets are hashed and both scores
   recorded. Here: 237 rows, 10 label changes confirmed.
4. **Label conventions confirmed by the owner:** a dish printed in several inline menus
   is one gold row per printed placement; an add-on list printed under its own heading
   with one priced row each counts as items.
5. **Promo-entry format added.** Amendment 5's deferred step: the harness's gold format
   takes an optional per-page `promos` list (scope, terms, conditions, Capture-targeted
   locators; kinds checked, counted only). Labels only: no pipeline or storage change,
   no extraction overhead. First set: 15 entries on 3 of the 10 pages.
6. **Found: Menu writes cost grows with the square of page size.** Each Menu table's
   deferred constraint trigger `ct_menu_integrity` runs `menu.check_aggregate(page_id)`
   once per inserted row at commit; one large page (`llm` and `jsonld` streams, over 1,000
   rows) took at least 1 h 25 min to commit on the laptop. A fix changes the Menu schema
   (stop-and-ask, its own PR); a full extraction pass waits for it independently of §8.

## Amendment 9 (2026-10-03): pipeline version v4, tuned on the P5-5 pages

Owner decisions in session P5-7, before any tuning. Record (tuning numbers, not a §8
evaluation): [2026-10-03-p5-pipeline-v4-tuning.md](../reviews/2026-10-03-p5-pipeline-v4-tuning.md).

1. **Harness rules, frozen for every later score.** (a) A row also matches a gold
   item by naming one of its variants (the variant's tokens, or the name's plus the
   variant's) when that item is printed at or before the row's claimed block: a
   dish's options emitted as items are scored against the dish, not a same-named
   dish elsewhere. (b) The gold-row false-reject metric stays strict: a dish printed
   in several inline menus is one gold row per placement (Amendment 8 item 4), and the
   validator, not the metric, handles repeats.
2. **New version: `repairs-v4`, `validator-v4`** (prompt, chunking, segmenter and
   model unchanged, so saved answers are re-validated without the model):
   `…;prompt-v2.3;chunk-v2.1;segment-v2;repairs-v4;validator-v4;classifier-v2`. Every
   change is layout-generic, with no per-site or per-platform branching: the duplicate
   key includes where a row is printed (validator: grounded name block; repairs'
   dedupe: claimed block); a spaced unit suffix ("$18.00 / LB.") is a price label; a
   variant that is no printed price label near its item is dropped (repairs); on pages
   that print each price above the name and again below it, an item's price run is its
   own lower copy; a "+$" price grounds no item price (`addon_price`). Tuning result
   (P5-5 pages / spike pages): price accuracy 0.990 / 0.994, item recall 0.887 /
   0.903, gold-row false reject 0.112 / 0.038, catch 0.998 / 0.987.
3. **Not changed.** No stronger model or GPU serving this session (H3: out of scope;
   a later proposal needs its own amendment). Price-before-name data prep was dropped:
   the page behind it is an absolutely positioned site-builder layout whose grouping
   exists only in CSS coordinates, so a static fix would be per-platform; rendering
   (§4) is the generic route. Large-page chunking was not changed (no measured
   target).
4. **v4 is not cleared for extraction runs** until it passes §8 on a fresh held-out
   draw from the laptop pass (new seed; the P5-5 exclusions plus the 18 venues
   labelled in P5-5), with Amendment 8's blind-label and blinded-adjudicator
   procedure.

## Amendment 10 (2026-10-09): v4 held-out evaluation fails

Owner decisions in session P5-8 (Amendment 9 item 4's evaluation). Record:
[2026-10-09-p5-v4-held-out-evaluation.md](../reviews/2026-10-09-p5-v4-held-out-evaluation.md).

1. **v4 fails §8** on 35 static own-site pages drawn from the laptop pass (seed
   20261008; P5-5's exclusions plus its 18 venues and their sites; quotas by page size:
   14 small, 14 medium, 7 large): price accuracy **0.983**, item recall **0.838**,
   false reject on gold rows **0.278** (bars 0.98, 0.85, 0.12); corruption catch
   **0.995**; usable prices 0.647. Per §8 v4 is not cleared for extraction runs; these
   35 pages are now tuning pages; the next version is scored on another fresh draw
   from the laptop pass, excluding the 90 venues labelled in P5-5 and P5-8 and their
   sites.
2. **Evaluation procedure, available to later evaluations:** size strata from the
   bundle's block count (read before any page content), pass/fail on the pooled set;
   parallel fresh labeller agents on one brief, with an owner spot-check before the
   freeze. Blinded adjudication (Amendment 8 item 3) may be skipped when no label
   change could change the verdict; it was skipped here, so blind labels = confirmed.
3. **Label conventions added by the owner:** a list repeated by a view toggle, tab or
   accidental copy counts once; an add-on on its own line with its own price is an
   item; names joined on one row with one price are one item each, but an "A or B"
   choice row is one item; a priced heading over a flavour list in another block is
   one item; catering service rows are not items.
4. **Direction for the next version (owner):** printed price formats the validator
   can't read ("12.5 USD", currency words, spacing) are fixed by a classical,
   layout-generic normalization of price text as the last step; context collection
   stays dynamic. The card-layout grounding gap (a price several blocks below the
   name) is a separate lever.
5. **The scale run (owner answer E5) is deferred to a Pi run** on the version that
   passes §8, once the laptop pass's pages reach the Pi and the Pi `llama-server`
   check is done; not run on the laptop.

## Amendment 11 (2026-10-09): pipeline version v5, tuned on the P5-8 pages

Owner decisions in session P5-9, before any tuning unless noted. Record (tuning numbers,
not a §8 evaluation): [2026-10-09-p5-pipeline-v5-tuning.md](../reviews/2026-10-09-p5-pipeline-v5-tuning.md).

1. **Price-text normalization (Amendment 10 item 4) is one shared reader.**
   `prices.price_tokens` reads printed price forms the same way for the validator,
   stitch, the row repairs and `parse_amount`: a currency word before or after the
   amount ("12.5 USD", "USD 12", "7.5 Dollars"), a one-decimal amount only with a mark
   ($, a currency word, an underscore), "$.40", "50¢", a word glued to the price
   ("From4.5 USD"), an underscore separator ("Patacones_12"). An unmarked one-decimal
   number ("6.2", "0.5 pounds") is not a price. It reads the original block text:
   Evidence locators keep their format, and a new form's span is the printed price
   with its mark ("12.5 USD"), the glued word and the underscore outside it. The page
   classifier keeps the v4 tokenizer (`price_tokens_v4`; its features are frozen
   with `classifier-v2`), and the prompt's sparse-retry counter (model input) is
   unchanged.
2. **Levers kept** (each layout-generic; keep rule: no tuning set gets worse on any
   of the four bars, a format crossing a bar blocks the lever): a price after "add"
   is a modifier's and a modifier-only line starts no price run; a claimed row is
   grounded at an exact repeat of its name right below (the card gap of Amendment 10
   item 4 was a repeated name, not distance); a label in parentheses after a price,
   when nothing is printed before it, and a unit glued to it ("$9gl") are its label;
   a column header ("16oz / 20oz / Pitcher") heading at least two rows labels each
   price column, to the section's heading, and a "/" or "—" block inside a run
   doesn't end it; an add-on on its own line with the block's only price is an item;
   names joined by "," / "&" in a one-price row share that price ("A or B" stays one
   item); an underscore separates words in name grounding; a short lower-case line is
   an item, not a description to merge (stitch). Dropped: "|" bare pairs and
   CamelCase name splitting (each made a set worse), and keeping a names-and-price line
   as an item in stitch (priced description lines stopped merging).
3. **chunk-v2.2 (decided after the levers, on new evidence).** P5-8 item recall stayed
   at 0.841 with the raw model rows at 0.842; chunk-v2.1 sends only the first 300
   characters of a block, and 54 P5-8 gold items lie past that cut on the two inline
   pages. A longer block is now sent as several lines with its block id, cut after a
   space, comma or "|". Pages whose blocks all fit get the same chunks, so their saved
   answers stay valid (greedy decoding); the owner re-ran the 13 affected tuning pages
   (recall 0.841 → 0.8498).
4. **prompt-v2.4 (decided after chunk-v2.2, on new evidence).** 9 re-run chunks of a
   few long lines stopped at the 40-tokens-per-line cap. The token cap is now at least
   one token per two input characters (prompt text and grammar unchanged); only
   chunks that stopped at the old cap can change, and the owner re-ran their 3 pages.
5. **New version:**
   `…;prompt-v2.4;chunk-v2.2;segment-v2;repairs-v5;validator-v5;classifier-v2`
   (model, prompt text, grammar and segmenter unchanged). Tuning result (spike / P5-5 /
   P5-8): price accuracy 0.995 / 0.990 / 0.983, item recall 0.905 / 0.887 / 0.871,
   gold-row false reject 0.037 / 0.112 / 0.116, catch 0.987 / 0.998 / 0.994: all four
   bars on every tuning set.
6. **v5 is not cleared for extraction runs** until it passes §8 on a fresh held-out
   draw from the laptop pass: new seed 20261010, excluding P5-5's exclusions plus the
   90 venues labelled in P5-5 and P5-8 and their sites, with Amendment 10's
   procedure. The label-free scale run stays deferred to the Pi (Amendment 10 item 5).

## Amendment 12 (2026-10-12): v5 held-out evaluation fails

Owner decisions in session P5-10 (Amendment 11 item 6's evaluation). Record:
[2026-10-12-p5-v5-held-out-evaluation.md](../reviews/2026-10-12-p5-v5-held-out-evaluation.md).

1. **v5 fails §8** on 35 static own-site pages drawn from the laptop pass (seed
   20261010; P5-5's exclusions plus the 90 venues labelled in P5-5 and P5-8 and their
   sites; quotas by page size: 14 small, 14 medium, 7 large): price accuracy **0.997**,
   item recall **0.819**, false reject on gold rows **0.168** (bars 0.98, 0.85, 0.12);
   corruption catch **0.994**; usable prices 0.663. Per §8 v5 is not cleared for
   extraction runs; these 35 pages are now tuning pages; the next version is scored on
   another fresh draw from the laptop pass: seed **20261012**, excluding P5-5's
   exclusions plus **all 162 venues labelled so far** (P5-5 18, P5-8 72, P5-10 72) and
   their sites.
2. **Size strata use fixed cutoffs.** P5-8's block-count cutoffs (small < 176, large ≥
   500) are kept for later draws, so strata compare across evaluations; each draw's own
   P50 / P90 is recorded, not used.
3. **Label conventions added by the owner:** a dish re-listed in another section of the
   same menu ("Popular Items", a "Vegetarian" or filter category, "Related Products")
   with the same name and the same price counts once, at its first printing; a
   re-listing with a different price, or a different product sharing a name, is its own
   item, and genuinely separate menus still count per placement. An identical priced
   option list printed again under several dishes counts once, at its first printing.
4. **Blinded adjudication skipped** (Amendment 10 item 2): both failing bars miss by
   more than any label change could move them (recall needs 84 more found items, gold-row
   false reject 143 fewer rejected rows).
5. **Direction for the next version** (from the findings, for the owner to confirm at
   tuning): group prices printed once over a list of names, line-wrapped layouts (a name
   over two blocks, a price at the end of a wrapped description), a card layout the model
   names by its description, and an integer glued to a name ("Cod Cakes16"); each fix
   layout-generic, under Amendment 11's keep rule. The label-free scale run stays
   deferred to the Pi (Amendment 10 item 5).

## Amendment 13 (2026-10-12): pipeline version v6, tuned on the P5-10 pages

Owner decisions in session P5-11, before any tuning. Record (tuning numbers, not a §8
evaluation): [2026-10-12-p5-pipeline-v6-tuning.md](../reviews/2026-10-12-p5-pipeline-v6-tuning.md).

1. **Levers: all four candidates of Amendment 12 item 5, several implementations each,
   keep the best** under Amendment 11's keep rule (no tuning set worse on any of the four
   bars; a format crossing a bar blocks the lever). Every fix is layout-generic.
2. **Levers kept:** a page that prints its prices bare also reads an integer glued to a
   name ("Cod Cakes16") or after a spaced dash ("feta -13"), never a page that marks its
   prices (a tab's item count stays unread); a fraction label ("$10.95/1/2lb"); a short
   label on its own line over its price, in a stack of label / price pairs, labels that
   price; a price-less block that lists names shares the one price printed right above
   it ("3.75 EACH:", "$4.50") or the price-only line right below ("Glass | 6"), and only
   it, unless that line belongs to the item named just before it; a section's price line
   right under its heading (two labelled prices, nothing else priced in the section, the
   heading no item's name) prices the section's items, label checked; a row the model
   named by a whole priced list becomes one row per name (repairs; capitalized names,
   "|" / "•" or three or more commas; a choice or a name described in parentheses stays
   one row); on a bare-price page a wrapped line's last number ends the price run.
   Dropped forms (each made a set worse or let junk through) are in the record.
3. **chunk-v2.3 (decided before tuning, T2):** a run of at most 4 chrome blocks between
   body blocks is sent to the model when it prints a marked price (read with the frozen
   v4 reader, so a later reader change can't change the chunks): card layouts that wrap
   each card's name and price in a button. It changes 2 tuning pages; their answers were
   regenerated, the others carried over (greedy decoding). The all-heading line-wrapped
   layout is not changed this session (T3).
4. **New version:**
   `…;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v6;validator-v6;classifier-v2`
   (model, prompt text, grammar, segmenter and classifier unchanged). Tuning result
   (spike / P5-5 / P5-8 / P5-10): price accuracy 0.995 / 0.992 / 0.983 / 0.997, item
   recall 0.907 / 0.887 / 0.871 / 0.864, gold-row false reject 0.021 / 0.105 / 0.109 /
   0.093, catch 0.987 / 0.995 / 0.994 / 0.996: all four bars on every tuning set.
5. **v6 is not cleared for extraction runs** until it passes §8 on a fresh held-out draw
   from the laptop pass: seed 20261012, excluding P5-5's exclusions plus all 162 venues
   labelled so far and their sites (Amendment 12 item 1), with Amendment 10's procedure
   and Amendment 12's fixed strata. The label-free scale run stays deferred to the Pi
   (Amendment 10 item 5).

## Amendment 14 (2026-10-13): v6 held-out evaluation fails

Owner decisions in session P5-12 (Amendment 13 item 5's evaluation). Record:
[2026-10-13-p5-v6-held-out-evaluation.md](../reviews/2026-10-13-p5-v6-held-out-evaluation.md).

1. **v6 fails §8** on 35 static own-site pages drawn from the laptop pass (seed
   20261012; P5-5's exclusions plus the 162 venues labelled in P5-5, P5-8 and P5-10 and
   their sites; quotas by page size with the fixed cutoffs: 14 small, 14 medium, 7 large):
   price accuracy **0.991**, item recall **0.821**, false reject on gold rows **0.126**
   (bars 0.98, 0.85, 0.12); corruption catch **0.995**; usable prices 0.702. Per §8 v6 is
   not cleared for extraction runs; these 35 pages are now tuning pages; the next version
   is scored on another fresh draw from the laptop pass: seed **20261013**, excluding
   P5-5's exclusions plus **all 234 venues labelled so far** (P5-5 18, P5-8 72, P5-10 72,
   P5-12 72) and their sites.
2. **Blinded adjudication run** (Amendment 8 item 3), because label changes could have
   moved the verdict (Amendment 10 item 2): recall needed 75 more found items, gold-row
   false reject 16 fewer rejected rows, and 218 unmatched labelled items had a pipeline
   row with one of their prices within 2 blocks under another name. Added to P5-5's packet:
   **D rows**, the label's and the pipeline's reading of one dish in random order, so
   naming and placement are judged blind. The adjudicators upheld the label on all 218 D
   rows and all 17 price disagreements. Their only label changes, 2 upcharges that are
   modifiers, were confirmed by the owner; the scores above use the confirmed labels (the
   blind labels give the same verdict). The 24 C rows answered "a real item" were already
   labelled one or two blocks above: the C packet showed only what was recorded at the
   pipeline's claimed block; a later packet should show what is recorded within 2 blocks.
3. **Direction for the next version** (from the findings, for the owner to decide at
   tuning): most of the recall gap is what the model names (a dish named by its
   description, its section heading, an ingredient line or a wine's cuvée line; a
   numbered dish read from the previous price block), which no validator or repair lever
   reaches; the false-reject fail sits on one page that prints its prices in a separate
   column. Validator-side candidates: column-aligned prices, bare one-decimal prices on
   their own line, one-decimal prices glued to a name. Model-side candidates (prompt, or a
   stronger model under its own amendment, Amendment 9 item 3) are the owner's call. The
   label-free scale run stays deferred to the Pi (Amendment 10 item 5).

## Amendment 15 (2026-10-14): pipeline version v7, tuned on the P5-12 pages; wine lists out of scope

Owner decisions in session P5-13 (Amendment 14 item 3). Record (tuning numbers, not a §8
evaluation): [2026-10-14-p5-pipeline-v7-tuning.md](../reviews/2026-10-14-p5-pipeline-v7-tuning.md).

1. **Overfitting guard:** P5-12's 35 pages are a dev check, scored and never tuned on; the
   levers are designed on the other 113 tuning pages. Layouts printed only on dev pages
   (prices in their own column, one-decimal prices glued to a name) are not built.
2. **Model-input levers rejected.** Naming rules in the prompt (prompt-v2.5, rules only, and
   v2.5b), and, after the miss diagnosis, sending a repeated line once, cutting a long block
   after each printed price (chunk-v2.4) and re-asking a chunk below 2/3 of its printed prices:
   each made a tuning set worse than both of two v6 runs on the same runtime. The prompt stays
   `prompt-v2.4` and the chunker `chunk-v2.3`, so every page's saved answers stay valid.
3. **Levers kept** (layout-generic; keep rule as Amendment 11): on a page that prints its
   prices bare, a block's last one-decimal amount is a price ("6.5", "salsa roja 7.5"),
   not a parenthesized or percent figure nor a ".0" after words (`validator-v7`, the
   shared reader); a row the model named by its description takes the short unpriced
   title line printed right above it, outside chrome and no section name the model gave
   (`repairs-v7`); a diet mark glued to the end of a name is dropped ("Thighgf",
   "PotatoV"). Dropped forms (price-line names, heading-named rows) are in the record.
4. **Wine lists are out of scope** (owner, after the diagnosis: two wine lists hold 99 of
   the dev set's 179 wrongly named items). A section whose heading names wine, or is only
   colour words and their modifiers ("Red", "Italian Reds"), unless it also names another
   dish or drink, is not extracted (`repairs-v7`, `output.wine_section`) and its labels are
   not scored; labellers keep labelling it, so wine can come back by deleting the gate. What
   it needs first is in the record ("Putting wine back later").
5. **Harness amendment** (amends Amendment 9 item 1): a leading menu number or code is not
   part of a name when a row is matched to a label ("13) Aloo Chaat", "H1: Scallop", "1.
   CHEESE"; labels differ on keeping it). The harness is frozen again as amended.
6. **New version:**
   `…;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v7;validator-v7;classifier-v2` (model,
   prompt, grammar, chunker, segmenter and classifier unchanged). Tuning result with the
   scope and harness changes (spike / P5-5 / P5-8 / P5-10): price accuracy 0.996 / 0.992 /
   0.983 / 0.997, item recall 0.914 / 0.886 / 0.879 / 0.868, gold-row false reject 0.014 /
   0.107 / 0.112 / 0.087, catch 0.989 / 1.000 / 0.996 / 0.997. Dev check (P5-12): 0.991 /
   **0.865** / **0.115** / 0.995 (v6: 0.991 / 0.821 / 0.126 / 0.995): all four bars, on a
   holdout weakened by the scope and harness choices made after reading its misses.
7. **Runtimes for tuning.** Model-input versions were screened on the laptop GPU (the same
   llama.cpp build's CUDA image, flash attention off, each compared with two v6 runs on the
   same GPU); a tuning tool, not a production path, and nothing under `infra/` changed. The
   Pi ran the pinned CPU image outside the deployed Compose project. Kept levers are
   measured on the laptop CPU's saved answers.
8. **RUN-A-01 done** (ADR-0005 Amendment 1): on a disposable clone upgraded to
   `db40e9424cba`, the page whose commit took at least 1 h 25 min (993 items, 810 prices,
   `llm` and `jsonld`) extracted in 24.5 s from its saved answers. `helios_laptop` stays at
   `7c2e4b9d1f3a`; eval clones are upgraded instead.
9. **v7 is not cleared for extraction runs** until it passes §8 on a fresh held-out draw
   from the laptop pass, scored with the amended harness and scope: seed 20261013,
   excluding P5-5's exclusions plus all 234 venues labelled so far and their sites
   (Amendment 14 item 1), with Amendment 10's procedure and Amendment 12's fixed strata. A
   model change (another model of this size; a larger one is not feasible on the Pi) needs
   its own amendment (Amendment 9 item 3). The label-free scale run stays deferred to the Pi
   (Amendment 10 item 5).

## Amendment 16 (2026-10-15): v7 held-out evaluation fails

Owner decisions in session P5-14 (Amendment 15 item 9's evaluation). Record:
[2026-10-15-p5-v7-held-out-evaluation.md](../reviews/2026-10-15-p5-v7-held-out-evaluation.md).

1. **v7 fails §8** on 35 static own-site pages drawn from the laptop pass (seed
   20261013; P5-5's exclusions plus the 234 venues labelled in P5-5, P5-8, P5-10 and P5-12
   and their sites; quotas by page size with the fixed cutoffs: 14 small, 14 medium, 7
   large), scored with the harness as amended in Amendment 15: price accuracy **0.990**,
   item recall **0.883** (the first held-out pass of the recall bar), corruption catch
   **0.991**, false reject on gold rows **0.153** (bar ≤ 0.12); usable prices 0.786. The
   wine scope left 140 labelled items (222 prices) on 6 held-out pages unscored. Per §8 v7
   is not cleared for extraction runs; these 35 pages are now tuning pages; the next
   version is scored on another fresh draw from the laptop pass: seed **20261014**,
   excluding P5-5's exclusions plus **all 306 venues labelled so far** (P5-5 18, P5-8 72,
   P5-10 72, P5-12 72, P5-14 72) and their sites (`next-draw-exclusions-p5-15.json`,
   sha256 `b4ba244f4abc399d776efc18d527abb643d7aa1da0901abd740b8a401b80b9ab`).
2. **The model ran on the Pi** (owner, this session): the pinned CPU `llama-server` image
   with the Compose service's flags on the A76 cores, outside the deployed Compose
   project, reached from the laptop's extract CLI over ssh; the disposable clone and the
   laptop pass's bundles stayed on the laptop. Item recall and price accuracy are Pi
   numbers (the Pi's greedy answers differ from the laptop's); gold-row false reject and
   catch do not depend on the host. 4.8 pages/h model time. This is not the pending
   `llama-server` Pi image check (no comparison with the spike's build).
3. **Blinded adjudication skipped** (Amendment 10 item 2; owner: only when margins are
   small): of the 425 rejected gold rows only 75 belong to items the packet would show,
   and removing all of them leaves gold-row false reject at 0.130; label changes can only
   raise recall. The C-row fix Amendment 14 item 2 asked for (list what is labelled within
   2 blocks of the claimed block) is built for the next adjudication.
4. **Direction for the next version** (from the findings, for the owner to decide at
   tuning): the failing bar is validator-side. Half the rejected gold rows (210) are
   variants the validator cannot ground, 174 of them labels printed once as a column or
   table header over the prices ("each" / "doz.", "Sushi · 1 pc" / "Sashimi · 3 pc", a
   size header row); without those rejects gold-row false reject would be 0.077. The rest
   are prices applied from a group heading several blocks up, names that hold a number,
   a bare integer before a mark, pipe-separated inline rows and one price closing a list
   of joined names. Which runtime is the evaluated one from now on (Pi or laptop CPU) is
   also the owner's call. The label-free scale run stays deferred to the Pi (Amendment 10
   item 5).

## Amendment 17 (2026-10-15): pipeline version v8, split column headers

Owner decision in session P5-15 (Amendment 16 item 4). Record (tuning numbers, not a §8
evaluation): [2026-10-15-p5-pipeline-v8-tuning.md](../reviews/2026-10-15-p5-pipeline-v8-tuning.md).

1. **One lever, owner's choice from the P5-14 cause analysis:** a column header printed one
   label per block over rows that print each price in its own block ("each" "doz." over
   "Fruit" "$1.60" "$17.60"; notes such as "(qty. 10)" between the prices) labels each price
   by its column, as v5's header in one block does; the table holds at least two rows; a
   description line is a sentence, not a name. Layout-generic. The repairs' variant check
   reads the same labels.
2. **New version:**
   `…;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v7;validator-v8;classifier-v2` (only the
   validator changes; saved answers stay valid). On the five older sets no row changes; on
   P5-14's 35 pages (now tuning pages) gold-row false reject 0.153 → 0.094 and catch 0.991 →
   0.993, with item recall 0.883 and price accuracy 0.990 unchanged; on the four changed
   pages every seeded corruption is caught and 0 of 230 wrong-column prices are accepted.
3. **Not built:** a one-column label printed over a whole section (the group / header price
   family), a size printed under its price, and the other P5-14 classes; each is the owner's
   call at a later tuning session.
4. **v8 is not cleared for extraction runs** until it passes §8 on a fresh held-out draw
   from the laptop pass: seed 20261014, excluding P5-5's exclusions plus all 306 venues
   labelled so far and their sites (Amendment 16 item 1), with Amendment 10's procedure and
   Amendment 12's fixed strata, scored with the harness as amended in Amendment 15. The
   label-free scale run stays deferred to the Pi (Amendment 10 item 5).

## Amendment 18 (2026-10-15): v8 held-out evaluation fails

Owner decisions in session P5-16 (Amendment 17 item 4's evaluation). Record:
[2026-10-15-p5-v8-held-out-evaluation.md](../reviews/2026-10-15-p5-v8-held-out-evaluation.md).

1. **v8 fails §8** (commit `43d4482`, PR #87 unmerged, evaluated as it stands at the owner's
   choice) on 35 static own-site pages drawn from the laptop pass (seed 20261014; P5-5's
   exclusions plus the 306 venues labelled in P5-5 to P5-14 and their sites; quotas 14 / 14 /
   7 with the fixed cutoffs), scored with the harness as amended in Amendment 15: price
   accuracy **0.990**, item recall **0.905**, corruption catch **0.992**, false reject on gold
   rows **0.134** (bar ≤ 0.12); usable prices 0.790. Per §8 v8 is not cleared for extraction
   runs; these 35 pages are now tuning pages; the next version is scored on another fresh
   draw: seed **20261015**, excluding P5-5's exclusions plus **all 378 venues labelled so far**
   and their sites (`next-draw-exclusions-p5-17.json`, sha256
   `dd748ff55c3b2987506997200029d8b6ead8caff92278943081e2c56dd167c9b`).
2. **The model ran on the laptop GPU** (owner): the pinned CUDA image of the same llama.cpp
   build, P5-13's GPU flags (flash attention off, f16 KV cache) with the CPU service's 2 slots
   and context, 136 pages/h. Not the production runtime (Amendment 15 item 7) and not
   repeatable run to run: item recall and price accuracy are GPU numbers; gold-row false
   reject and catch do not depend on the runtime.
3. **Blinded adjudication run** (Amendment 10 item 2): 73 rejected gold rows sat on items the
   packet shows, enough in principle to reach the bar. The adjudicators upheld the labels (all
   157 B rows, 57 of 59 D rows); their only label changes (2 rows: a "(loaded $1)" price) await
   the owner and leave the verdict unchanged (0.134). 42 C answers named wines already
   labelled out of scope: a later packet lists out-of-scope labels in its nearby list too.
4. **Direction for the next version** (for the owner at tuning): v8's lever changed one page of
   this draw (v7's validator: 0.137). The false rejects sit on layouts left open after P5-14 (a
   group price over a list of dishes, a unit printed after its price, two prices on one
   bare-price line, an unpriced gallery before a priced table) plus a currency sign printed
   alone in its block; one page's labels take variants from a "3/6" in the dish name, a label
   convention to settle. The "+$" add-on policy and the evaluated runtime (GPU or CPU) remain
   open. The label-free scale run stays deferred to the Pi (Amendment 10 item 5).

## Amendment 19 (2026-10-15): false-reject structure and production constraints

Owner decisions in session P5-17, after a production review of the proposals. Record:
[2026-10-15-p5-false-reject-structure.md](../reviews/2026-10-15-p5-false-reject-structure.md).
Asked first: scope = structure, measurement and labels; keep vs omit = measure both, decide
later; future evaluation runtime = the laptop GPU; single-price sections = measure and compare.
**Decided, not built:** every item below that changes the pipeline or the harness is built in a
later session under its own keep rule.

**Why.** Three held-out draws in a row (P5-12 0.126, P5-14 0.153, P5-16 0.134) fail only the
gold-row false-reject bar. Pooled over all 218 labelled pages under validator-v8, 96 % of the
1,523 rejected gold rows are "no price match" downgrades. No layout class holds more than 15 %
of them, and in each set the four worst pages hold 50–93 %. A per-layout lever per version
doesn't carry to the next draw. At 35 pages the page-clustered interval (P5-16: [0.061,
0.235]) is wider than any lever's effect.

**Production constraint (owner).** Production has no labels, so nothing checks a decision the
runtime makes:
- what the validator (or any later stage) accepts is stored as a true price, with §6's
  constant confidence (`PRICE_CONFIDENCE` 0.98, itself a §8 claim);
- an error surfaces only at the monthly spot check, or never.

The validator does run in production, but it can't be leaned on as a safety net. On real
output it catches 0.595 of wrong rows (0.994 of injected ones), and it lets 1,189 priced rows
that match no label through (8 % of accepted rows). Every decision below is therefore judged by
what it stores without labels, not by the gold-row FR alone.

1. **Measurement (§8; the 0.12 FR bar unchanged).**
   - (a) Every §8 record adds a page-clustered bootstrap interval beside Wilson. Pass/fail stays
     on the point estimate.
   - (b) Every §8 record and tuning record adds two numbers: **accepted rows that match no
     label** and **real-output wrong-price rows accepted**.
   - (c) Every §8 record and tuning record adds per-format and per-page FR tables.
   - (d) Usable prices are recorded now. Their bar is set from tuning data at the next tuning
     session, before any next draw, and gated from the next §8 evaluation. They measure what
     production stores.
   - (e) Held-out size stays at 35 scorable pages. A 70-page set is revisited once a version
     reads near the target in item 7.
2. **Labels** (from the next draw; recorded verdicts unchanged; tuning labels corrected when a
   set is next touched):
   - (a) a size count encoded in a dish name ("3/6 Catfish … $9.95/$17.99") stays labelled as
     variants "3" / "6";
   - (b) a variant is a label printed with its price, never inferred;
   - (c) a "+$" row is a modifier, not an item;
   - (d) one price printed over a list of names prices each name when the entries are named
     dishes (distinct names, often with their own description line); when the entries are
     options of one dish (flavours, fillings, under "choose" / "any N"), they are one item.
3. **Stage [5b] price resolution.** It runs after the validator, over its no-match downgrades
   only (`price_not_grounded`, `variant_not_grounded`, `price_bound_to_other_item`,
   `price_belongs_to_other_variant`, `addon_price`). The validator and the rows it accepts are
   unchanged.
   - Production constraints:
     - **no printed price, no accept:** every accept cites the printed span of its price as
       Evidence, as today's accepts do;
     - **its own price confidence**, lower than `PRICE_CONFIDENCE`, and its own reason, so
       downstream can rank or filter it and a later version can re-interpret it;
     - **refuse by default.**
   - When [5b] rejects a row, the item is **kept unpriced** (today's downgrade). Omit is not
     adopted: it would lose items silently in production.
4. **[5b] contents: generic deterministic resolvers only**, chosen per page by measured
   signals, never by site.
   - The first is a section single-price rule:
     - the section's price-only lines all print one amount, above the item;
     - no "from / starting at / choose / any N / combo" wording on that line or the heading;
     - the row's name is a dish title, not a sentence.
   - Item 2(a)'s name-encoded variants are grounded by a generic rule, in the validator or
     [5b]: a slash-joined number pair in a name grounds the same-order price pair.
5. **Keep rule for every [5b] resolver and validator lever:**
   - no tuning set worse on any §8 bar (Amendment 11's rule);
   - **no rise in accepted rows that match no label**, gated, not only recorded.
6. **Not adopted:**
   - a learned row classifier. In production it would fail silently on new layouts, which are
     where the rejects concentrate, with no runtime signal. It is revisited only with a
     label-free drift monitor in place and its own amendment;
   - a second extractor call as an acceptance authority. The same model confirming its own
     reading is not grounding.
7. **Next draw** (seed 20261015, exclusions sha256 `dd748ff5…`) only when the version, on every
   tuning set:
   - reads a pooled gold-row FR near **0.05**;
   - holds price accuracy;
   - shows no rise in wrong rows accepted or in accepted rows matching no label.

   On the measured curve, 0.05 passes a 35-page draw ~97 % of the time, versus 74 % at v8's
   0.096. Lowering FR by accepting more is the production risk, so the other conditions bind
   too.
8. **Production monitoring** (recorded, no new dependency):
   - (a) the monthly spot check (Amendment 3) oversamples [5b] accepts and flagged pages, so
     their production error is measured;
   - (b) each extraction run records per-page shares of downgraded, [5b]-accepted and flagged
     rows, and lists pages outside the tuning sets' range for review.

## Amendment 20 (2026-10-19, accepted 2026-10-20): Qwen3.5-9B fallback on the Pi CPU

**Status: Accepted 2026-10-20 (session P5-23) with the owner rulings below. Scored the
same day as registered: no policy passed, so no fallback ships** (item 5). Proposed in
session P5-22. Nothing was built.

**Owner rulings (2026-10-20, P5-23):**
- **R2 is allowed** under Amendment 19 item 6. It is a label-free choice between two pages
  that the same validator grounds, not an acceptance authority; the registered guards on
  accepted-unmatched and wrong-accepted rows bind.
- **ADR-0017 items 1–2 are accepted** (items 3–4 deferred), so item 8's dependency is met
  and routing used H4 as registered.
- **Context: both services at 12,288 (6,144 per slot).** This replaces item 3's "the
  primary keeps 8,192". The primary's own retry prompt plus token cap reaches 4,679 tokens
  (P5-19), above the 4,096-token slot of Amendment 6 item 6. The primary's flag change is
  built with v9 and recorded in its amendment; the Pi 4B was measured at 12,288 (10.49
  pages/h, 3.20 GiB).
- Item 6's "§3's first-pass size (~2,300 menu pages)" is stale: the first pass runs on the
  laptop (Amendment 8 item 1), and the laptop pass holds 886 distinct page texts (6,194
  chunks).

**Outcome (2026-10-20,
[record](../reviews/2026-10-20-p5-23-fallback-routing.md)).** DEV made R2 the only
eligible policy (+2 usable prices pooled over both primary replicates; R1 −3, R3 −4).
On VAL, R2 raised usable prices (+38 / +29), but both replicates regressed on price
accuracy (0.9956 vs 0.9966) and wrong-price-accepted rows (0.0030 / 0.0031 vs 0.0023),
where the registered A/B band is 0. VAL fails, and there is no re-selection. v9
continues primary-only. Data mapping, disclosed before scoring: item 5's primary tags
hold TEST3 answers only, so DEV and VAL used P5-19's `screen-baseline-a` / `-b` (the pair
behind the registered H4 DEV band) and the fallback's `p520-q35-9b__g-v24`.

Evidence: [P5-20 bracket screen](../reviews/2026-10-16-p5-20-bracket-screen.md),
[P5-21 TEST3](../reviews/2026-10-17-p5-21-harness-h-test3.md),
[P5-21 closeout and Pi cost](../reviews/2026-10-18-p5-21-closeout-pi-cost.md).

**Why.**
- Owner direction (2026-10-19): the NPU is not used, and the default model stays. The NPU
  W8A8 probe was slower than the CPU path (6.5 vs 10.4 pages/h) and lower on raw usable
  prices (0.761 vs 0.844, 3 pages). §3's CPU-only rule and Amendment 6 stand unchanged.
- Qwen3.5-9B Q4_K_M is the only model result that held. On TEST3 (45 fresh tuning pages),
  with the 9B on every page and the H4 repair:
  - +131/+138 correct prices out of 3,664 over both v8 baseline replicates;
  - paired 95 % CIs exclude zero; 5 of 6 sets gain;
  - accepted-unmatched, wrong-accepted and accuracy guards all pass.

  Its raw price accuracy (0.926 vs 0.940) is lower, so the gain depends on the validator.
- On the Pi CPU an extra 9B pass costs 1.87× the primary pass (5.61 vs 10.49 pages/h on
  3 pages, 88.6 °C vs 72.1 °C). Running it on every page is not affordable. It is a
  fallback for some pages only.
- The router is the hard part. P5-19's coverage < 0.70 trigger routed 43 % of pages,
  against a 30 % cap.

**Decided if accepted:**

1. **Primary unchanged.** The primary stays Qwen3-4B-Instruct-2507 Q4_0 under Amendment 6:
   same image, flags, prompt v2.4 and GBNF.
2. **Fallback model.**
   - Manifest entry `Qwen3.5-9B-Q4_K_M`: publisher `unsloth/Qwen3.5-9B-GGUF`, revision
     `3885219b6810b007914f3a7950a8d1b469d598a5`, file `Qwen3.5-9B-Q4_K_M.gguf`.
   - Size 5,680,522,464 bytes, sha256
     `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8`, Apache-2.0.
   - Downloaded and checksum-refused like the primary.
   - Same prompt v2.4, greedy decoding, GBNF, chunking and harness as the primary. No
     model-specific prompt, repair or branch.
3. **Runtime.** The fallback is a second Compose service, `llama-server-fallback`:
   - same pinned image digest as the primary;
   - its own `menu-fallback` profile and its own model-check init step;
   - same cores (CPUs 4–7 on the Pi), `--threads 4 --parallel 2`;
   - `--ctx-size 12288`, the context its quality and Pi cost were measured at (6,144 per
     slot). The primary keeps 8,192;
   - `mem_limit: 8g` (measured peak 5.65–6.38 GiB).

   **Two phases per batch; the services never run together:**
   - phase 1: the primary extracts every page of the batch;
   - the owner stops `llama-server` and starts `llama-server-fallback`;
   - phase 2: the fallback extracts only the routed pages.

   This keeps the owner-run start and stop of Amendment 6 item 6. It needs no orchestration
   code, and the two models never share the CPU or the RAM. A page's Menu write waits until
   its routing decision is final. Each stored extraction records which model produced it,
   as part of the pipeline version.
4. **Routing: the policies registered on 2026-10-17, unchanged.**
   - The registration is `var/menu-eval/p5-22-heldout/protocol/routing.md` (sha256
     `520be0be…4ada`), archived in `p5-21-prompt-opt.tar.zst`. It was registered before
     any routing score, and none has been run since.
   - Signals come from page text and the primary's output only:
     - printed price-token count;
     - H4-accepted count;
     - coverage = accepted / printed;
     - "bad" = a malformed or `length`-finished kept chunk.
   - No labels, site, platform or page-identity lookup. Cap: at most ⌊0.30 × batch pages⌋
     routed per batch.

   | Policy | Eligible | Order | Use of fallback output |
   |---|---|---|---|
   | R1 | printed > 0 and (bad or coverage < 0.70) | bad first, then lowest coverage | the whole fallback page replaces the primary page |
   | R2 | as R1 | as R1 | the fallback page is used only if its H4-accepted count is higher; every attempt is still charged |
   | R3 | printed > 0 and (bad or accepted = 0) | bad first, then most printed tokens | as R1 |

   - Rows are never merged. Every page goes through the same harness. On a fallback
     failure the primary page stays, and the failure is recorded.
   - **R2 needs the owner's explicit ruling against Amendment 19 item 6** ("a second
     extractor call as an acceptance authority").
     - R2 does not let the 9B confirm rows: both pages are grounded by the same validator.
     - But its choice between two pages does depend on a second call.
     - If the owner rules it out, only R1 and R3 are scored.
5. **Selection and confirmation: the registered rule, unchanged.**
   - Data: existing laptop-GPU outputs, which need no new inference:
     - primary Q4_0 replicates A/B `p521-q3-4b-2507-q40__g-v24`, `__g-v24-b`;
     - fallback `p521-q35-9b__g-v24`;
     - splits `splits-p520.json`, sha256 `5630f78d…23d7`.
   - **DEV (15 pages) chooses.** A policy is eligible only if all of these hold:
     - pooled usable prices over both primary replicates rise;
     - neither replicate regresses beyond the H4 DEV A/B band on price accuracy,
       accepted-unmatched per row or wrong-price-accepted per row;
     - routed share ≤ 30 % for each replicate.
   - Choose the eligible policy with the largest pooled gain. Ties go to fewer fallback
     tokens, then to the policy id.
   - **VAL (15 pages) confirms once:**
     - non-negative usable gain on each replicate;
     - guards within the VAL H4 bands;
     - share ≤ 30 %.

     There is no re-selection.
   - **Added before any score, descriptive only:** the chosen policy is also reported on
     TEST3 (45 pages, 13 routable). DEV and VAL route at most 4 pages each, so they are
     thin evidence. TEST3 is not a pass criterion and never changes the choice.
   - **If no policy is eligible or VAL fails, no fallback ships.** v9 continues primary-only,
     and no other trigger is designed in its place (owner: no more screening).
6. **Cost (recorded, not gated, as in §8).**
   - Fallback cost is the primary pass plus every routed attempt, including discarded ones.
   - Projection (3 probe pages, same page mix): 30 % share → 6.72 pages/h, 20 % → 7.64.
   - Routed pages are expected to be harder and longer than average. So after selection,
     one Pi CPU run times both models on the chosen policy's routed DEV+VAL pages, with
     production images and flags, and records pages/h, s/chunk, RAM and SoC temperature.
   - At §3's first-pass size (~2,300 menu pages), the owner sets the acceptable
     wall time from these numbers.
   - A 9B SoC temperature at or above the guard is recorded as throttling, not hidden.
7. **§8.**
   - If a policy ships, the pipeline version under §8 is the routed configuration: primary,
     routing and fallback.
   - Its held-out evaluation runs both models on the laptop GPU (Amendment 19: the same
     llama.cpp runtime; Pi for speed only), at each service's production context.
   - It reports the routed share and the primary-only numbers next to the routed numbers.
   - The §8 bars and Amendment 19 item 7 are unchanged. The fallback raises usable prices;
     it does not move gold-row false reject, which is a validator / [5b] property. The
     gate still depends on v9.
8. **Dependency.** The registered signals use H4-accepted counts, and H4 is accepted only
   under ADR-0017 item 2, which is still Proposed.
   - If the owner accepts ADR-0017 (at least item 2), routing uses H4 as registered.
   - Otherwise this amendment waits. Re-registering on v8 counts would be a new
     registration, so it would be done before any score.

## Amendment 21 (2026-10-20, accepted 2026-10-20): pipeline version v9 — [5b] resolve-v2, repairs-v9, context, usable bar

**Status: Accepted 2026-10-20 as drafted (owner, after session P5-25), with the rulings
below.** Proposed in session P5-25.

**Owner rulings (2026-10-20):**
- **The 25-row budget applies per class.** Claim drift is D5 plus the C3t re-test (99 gold
  rows), so item 3's C3t and item 4's repair stay.
- **Item 6's constants are accepted as drafted**, including `RESOLVED_PRICE_CONFIDENCE`
  0.87.
- **The remaining invariance debt is recorded as risk** (item 5). There is no
  debt-only budget. It is revisited if the model changes.
- **Next draw: 35 pages now** (item 9's option (a)), on seed 20261015.

Built on
branch `worktree-p5-18-pipeline-v9`; numbers are tuning numbers on the saved Qwen3-4B
Q4_0 answers under labels-v9 (218 pages, 15,791 gold rows), not a §8 evaluation. Records:
[P5-24 resolver block](../reviews/2026-10-20-p5-24-resolver-block.md) (owner rulings R1–R3,
its §6) and [P5-25 invariance debt](../reviews/2026-10-20-p5-25-invariance-debt.md).

**Why.** Amendment 19 decided v9's structure ([5b] price resolution, production
constraints, keep rule); P5-18 built the stage with one resolver; P5-24 and P5-25 added
resolvers and harness fixes under the keep rule, ADR-0017 item 2 and the invariance suite.
This amendment records what v9 contains and the rules its levers were judged by.

1. **Context: 6,144 tokens per slot** (`llama-server --ctx-size 12288 --parallel 2`;
   Compose, commit `43bc411`). Replaces Amendment 6 item 6's 8,192 (4,096 per slot) and
   Amendment 20 item 3's "the primary keeps 8,192": the primary's longest rendered retry
   prompt plus its token cap reaches 4,679 tokens (P5-19, P5-14 page `77796540a06c`),
   above a 4,096-token slot. Owner decision Q5 (P5-23). The Pi 4B was measured at this
   context (10.49 pages/h, 3.20 GiB). Saved tuning answers were produced at 8,192; only a
   chunk that overflowed a 4,096 slot can differ, and none is re-run here.
2. **Catch for a [5b] change (owner ruling R1).** `corruption_eval` draws its trials from
   the rows the harness accepts when clean, so a resolver that accepts more gold rows
   reshuffles the seed-7 trials. A [5b] resolver is judged on the **paired trials** (the
   trials seed 7 draws from the baseline's clean accepts): it must accept **0 corrupt
   rows** there, and each tuning set's seed-7 catch must stay **≥ 0.97**. Repair and
   validator changes keep Amendment 11's literal rule (seed-7 catch no worse on any set).
3. **[5b] resolve-v2** (generic, deterministic, refuse by default, each accept citing its
   printed price; Amendment 19 items 3–4):
   - `resolved_name_pair` (P5-18): a "3/6" count pair in a dish's name grounds the
     same-order price pair;
   - `resolved_label_line` (C3t, P5-24): the variant printed on its own line, the nearest
     price-free line above a price at the row's amount, in the item's region;
   - `resolved_name_price` (C4, P5-24): a row without a variant whose name is printed once,
     unglued, with the row's price right after it.

   Owner ruling R2 (ADR-0017 literal: any added invariance flip rejects, gains included)
   removed C3t while repair 4b's claim-relative window let a claim change its decision;
   with item 4's repair it adds 0 flips and returns. Not kept: Amendment 19's section
   single-price rule (P5-18: accepted-unmatched rose), C2 numbers in names (P5-24: +15
   gold rows, 6 junk accepts, below the Q6 budget), C1 (junk-heavy).
4. **repairs-v9: repair 4b reads the printed name, not the claim** (ADR-0017 item 1, claim
   drift). `drop_unprinted_variants` looks for a variant's printed label from 2 blocks
   above to 4 below the block that prints the row's name (the claimed block, else the
   nearest of the 8 blocks above it, else the nearest within 2); above the name only
   price-first lines count. The validator is unchanged (`validator-v8`).
5. **Invariance debt not paid** (measured in P5-25, not kept): the validator's
   claim fallback (accepted-unmatched rose on 5 sets), a variant written into the name
   split back to `v` (+2 real usable prices, below the 25-row budget, and 4 added flips),
   letter case read from the page (31 added flips, item recall down on 4 sets). The saved
   real answers almost never write those styles: 66 rows in another letter case, 413 with
   the variant in the name, of 21,038. The debt stays recorded (6,638 flips) as latent risk
   for the next model (ADR-0017 Consequences); owner: no debt-only budget.
6. **Constants.**
   - `RESOLVED_PRICE_CONFIDENCE` **0.87**: the 95 % Wilson lower bound of [5b]'s
     measured exact-price share on the tuning sets (26 of 26 real accepts exact), rounded
     down, as P5-18 decided. In-sample: the resolvers were built on these sets.
   - Run report tuning range: [5b] share max **0.23** (the tuning maximum, 0.222; was 0.0),
     downgraded share **0.47** (95th percentile 0.462).
   - **Usable prices ≥ 0.74**, gated from the next §8 evaluation (owner, P5-23; Amendment 19
     item 1(d)); `evaluate report` prints it beside the usable-price line.
7. **New version:**
   `…;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v9;validator-v8;resolve-v2;classifier-v2`
   (model, prompt, grammar, chunking and segmenter unchanged).
8. **Tuning result** (v9 resolve-v1 → this version, pooled over the seven tuning sets):
   gold-row FR 0.0930 → **0.0842** (page-clustered 95 % [0.058, 0.116]); usable prices
   0.7837 → 0.7855; price accuracy 0.9911 → 0.9912; item recall 0.8880 =; catch 0.9938 →
   0.9944; accepted rows matching no label 1,207 =; wrong prices accepted 117 → 116; [5b]
   accepts 0 → 26, all exact; 0 corrupt [5b] accepts on the paired trials. DEV (17
   configurations): pooled usable +10, no configuration beyond the band, every
   leave-one-model-out fold passes. Invariance 6,655 → 6,638 flips, 0 added.
9. **Next draw: 35 pages on seed 20261015** (owner, 2026-10-20, after ruling R3).
   Amendment 19 item 7 asks for a pooled gold-row FR near 0.05; this version reads 0.084.
   Resampled 35- and 70-page draws from the tuning pages pass all four gated bars 0.765 /
   0.875 of the time (v9 resolve-v1: 0.714 / 0.815), an upper bound: every past draw read
   worse than its tuning sets. The owner chose 35 pages over item 1(e)'s 70-page set and
   over another `price_not_grounded` block.

## Amendment 22 (2026-10-20, accepted 2026-10-20): v9 held-out evaluation passes

**Status: Accepted 2026-10-20 (owner): PR #93 merged as `75feffb`, with the rulings below.**
Proposed in session P5-26.

**Owner rulings (2026-10-20):**
- The first extraction pass runs on the laptop GPU into `helios_laptop` (Amendment 8 item
  1), with the evaluated flags and the production context. It follows the merge.
- The adjudication's 4 label changes stand, with C3 at its printed block. The confirmed
  set gives the same verdict.
- A classifier precision check is opened (item 4).

Record:
[2026-10-20-p5-26-v9-held-out-evaluation.md](../reviews/2026-10-20-p5-26-v9-held-out-evaluation.md).

1. **v9 passes §8** (commit `07e9b49`, PR #93, merged as `75feffb`; Amendment 21's version string). The
   draw: 35 static own-site pages from the laptop pass (seed 20261015; P5-5's exclusions plus
   the 378 venues labelled in P5-5 to P5-16 and their sites; quotas 14 / 14 / 7 with the fixed
   cutoffs), scored with the v9 harness.

   | Bar | v9 | Bar |
   |---|---|---|
   | Price accuracy | **0.993** | ≥ 0.98 |
   | Item recall | **0.874** | ≥ 0.85 |
   | Corruption catch | **0.996** | ≥ 0.97 |
   | False reject on gold rows | **0.097** (page-clustered [0.050, 0.156]) | ≤ 0.12 |
   | Usable prices (Amendment 21) | **0.755** | ≥ 0.74 |

   It is the first version to pass. Per §8, v9 may ship, and these 35 pages are now tuning
   pages.
2. **The model ran on the laptop GPU** (Amendment 19's evaluation runtime): the pinned CUDA
   image of the same llama.cpp build, P5-13's GPU flags, 2 slots, and the production context
   of Amendment 21 item 1. 117 pages/h. This is not the production runtime (Amendment 15
   item 7): item recall, accuracy and usable prices are GPU numbers. Gold-row false reject
   and catch do not depend on the runtime.
3. **Blinded adjudication ran** (Amendment 10 item 2). The worst case over the packet's
   answers (FR 0.158) could have reached the bar. The adjudicators upheld the labels:
   - of 641 rows, 4 changes apply mechanically;
   - 2 more are left for the owner;
   - the verdict is the same (FR 0.096, usable 0.755).

   The packet now takes its classes from the v9 harness and lists out-of-scope labels too
   (Amendment 18 item 3).
4. **Margins are thin, and they are recorded, not gated.** The FR point estimate sits 70 rows
   inside the bar and usable prices 44 inside theirs. Small and medium pages read FR
   0.138 / 0.141. Classifier-v2 precision on the draw is 0.903 [0.813, 0.952] (§8 judges the
   classifier on its S6f evaluation).
5. **For the owner:** what runs next and where (Amendment 8 item 1's laptop extraction pass;
   Amendment 10 item 5's Pi scale run after the Pi gates); the label changes; whether to
   check the classifier against 0.95. The next held-out draw (for a later version) is seed
   **20261016**, excluding P5-5's exclusions plus all 450 venues labelled so far and their
   sites (`next-draw-exclusions-p5-27.json`, sha256
   `3439a96175c87b03ad1397d6eb9a3207e0a1d064a12be59c8c287bcc7e9a528d`).

## Amendment 23 (2026-10-20, accepted 2026-10-20): classifier-v2 misses §8 precision on the laptop pass — a known gap of v9

**Status: Accepted 2026-10-20 by the owner (session P5-27).** Record:
[2026-10-20-p5-27-classifier-check.md](../reviews/2026-10-20-p5-27-classifier-check.md).

1. **The measurement.** All seven held-out draws (P5-5 to P5-26) had their frozen blind page
   labels pooled: 450 pages, one per venue and site, every manifest verified. 413 are menus,
   so `classifier-v2` precision is **0.918 [0.889, 0.940]**; weighted by the frame's size
   strata, 0.915 [0.889, 0.941]. The bar is precision ≥ 0.95, and both upper bounds sit below
   it. The gap is in small pages (0.855; medium 0.975, large 0.973).

   What the 37 non-menu pages are:
   - 20 of the restaurant's own menu hubs or homepages, which write no prices;
   - 10 off-domain pages, the only ones that write prices: 92, or 0.40 % of the sample's
     prices;
   - 5 menu URLs whose menu never reaches the page text;
   - 2 judgement calls.

   Recall is unmeasured.
2. **A known gap of v9; v9 stays cleared.** §8's classifier bar was judged on the S6f
   evaluation (Amendment 22 item 4). This is the first measurement on the production
   distribution. The laptop pass's writes stay. They were made 2026-10-20 into `helios_laptop`
   at 1,632 pages, 120,816 items and 67,305 prices; one CUDA fault aborted the run after 254
   pages and it resumed without loss. The fix ships as a later pipeline-version bump, which
   re-interprets the stored bundles.
3. **Next: a replacement survey, then a fresh sample.**
   - The gap audit's step 3 runs with leave-one-set-out over these 450 labels and the spike
     labels.
   - Candidates are generic only:
     - `classifier-v2`'s features retrained with the new negatives;
     - added generic page signals, for example link density, price-token density, and cart
       or product markup;
     - a threshold.
   - The chosen classifier is proposed as an amendment before it is built. It is then
     verified on a fresh page-level precision sample (gap audit R1(a), about 260–440 pages)
     and a rejected-page recall sample (R1(b)).
   - A threshold picked on these 450 pages is tuned, not held out.
4. **Accepted static pages with no menu text are rendered, as part of the rendering rollout.**
   A page the classifier accepts but whose static text yields no menu (0 blocks, or no
   extracted items) takes the render path. This is built with the Pi rendering switch-on
   (§4), so its cost is measured once with the rest. It is not built separately now.
5. **Rows from non-menu pages stay until R4 removes them automatically.** Nothing is deleted
   and nothing is entered by hand. A new classifier alone would not remove them: a page
   rejected later stays in the due queue (gap audit finding 2). The gap audit's R4 is built
   together with the classifier fix: a rejected or withdrawn page leaves the queue, and its
   Menu rows are retracted. Cleanup then covers the whole pass, not only the sampled pages.

## Amendment 24 (2026-10-20, accepted 2026-10-20): `classifier-v3` candidate, fresh-sample plan, R4

**Status: Accepted 2026-10-20 by the owner (session P5-28), with the rulings below.** Record:
[2026-10-20-p5-28-classifier-survey.md](../reviews/2026-10-20-p5-28-classifier-survey.md).

**Owner rulings (2026-10-20):**
- **Q1, pass rule:** R1(a) passes on the stratified point estimate ≥ 0.95, with its Wilson
  interval recorded, as the extraction bars are judged.
- **Q2, frame:** R1(a) labels all 361 remaining sites. Page-level classifier labels don't
  exclude a venue from later extraction held-out draws: for those draws, "labelled" means
  item-labelled. Later classifier samples exclude classifier-labelled venues and sites.
- **Q3, candidate:** (b), `classifier-v3` with the generic page signals.
- **Q4, R1(b):** a record-only discovery re-crawl on the laptop, about 150 venues (about 100
  `no_menu_found` and 50 resolved). Every v2/v3 disagreement is labelled, plus about 100 pages
  both reject.
- **Q5, order:** verify first. Build `classifier-v3` unshipped (verifier unchanged), with the
  re-crawl script; label R1(a) and R1(b) against it; reach the verdict. Then, only on a pass,
  one pipeline-version bump ships v3 with R4. Until then v2 stays the verifier and the laptop
  pass's rows stay (Amendment 23 items 2 and 5).

1. **The survey (Amendment 23 item 3).** Leave-one-set-out over nine labelled sets: the spike's
   188 static pages, S6f's 57 rendered pages, and the seven held-out draws (450 pages, each its
   own set). Pages sharing a venue or site with the held-out set leave the training pool, and
   inner folds group by venue and site. Thresholds come from the precision-0.95 rule inside
   each fold. Pooled over the draws:

   | Candidate | Precision [Wilson 95 %] | Stratified | Small pages | Labelled menus lost (of 413) |
   |---|---|---|---|---|
   | `classifier-v2` | 0.918 [0.889, 0.940] | 0.915 | 0.855 | — |
   | Threshold only | 0.936 [0.909, 0.956] | 0.931 | 0.881 | 17 |
   | v2 inputs retrained | 0.961 [0.937, 0.976] | 0.957 | 0.922 | 22 |
   | **v2 inputs + generic page signals** | **0.957 [0.932, 0.972]** | **0.953** | 0.913 | **17** |

   Retraining with the new negatives removes 19 of the 37 drawn non-menus, including 72 of the
   92 wrong prices. A threshold change alone does not reach the bar.
2. **Proposed candidate: `classifier-v3`.**
   - **Inputs:** `classifier-v2`'s inputs, the `potion-base-8M` embedding of `page_text` plus the
     7 layout features. Added to them, 11 generic page signals computed with the standard
     library's `html.parser`:
     - link-text share, the anchor count, and anchors per block;
     - the share of blocks that are chrome;
     - money tokens per 100 words;
     - the share and count of same-host child links;
     - add-to-cart markup;
     - product markup;
     - article markup;
     - the count of `<article>` and `<time>` elements.

     No site, platform or brand rule.
   - **Model:** logistic regression `C = 0.5`, trained on all 695 labelled pages.
   - **Threshold:** the existing rule, the lowest threshold whose venue- and site-grouped
     out-of-fold precision reaches 0.95. On this pool it is **0.674**; the build reproduces it
     with the same rule.
   - **Runtime:** the plain-Python scorer and the pinned embedding are unchanged, with no new
     dependency. scikit-learn stays ephemeral. The signals live beside `layout_features` in
     `packages/helios_parsing/page_features.py`. The weights file already names its feature
     list; the build keys the inputs on it, so `classifier-v2`'s file keeps loading.
3. **Known risks, carried into verification:**
   - Precision's lower bound (0.932) is below 0.95.
   - The candidate drops 4.1 % of v2's accepted menus, which it must win back among pages v2
     rejects to meet §8's recall bar.
   - Inside the spike's candidate pages, it admits 7 of 131 non-menus against 5 for v2's
     configuration. The draws can't see such admissions.
4. **Fresh samples, verified against a built but unshipped `classifier-v3`:**
   - **(a) R1(a) precision.** Due pages of `helios_laptop`, one per site, excluding the spike's
     venues and sites and `next-draw-exclusions-p5-27.json`'s 450 venues and sites. 361 sites
     remain (small 192, medium 161, large 8); all 361 are labelled (Q2). Stratified
     by the fixed cutoffs, fresh seed, page-level labels only. Score `classifier-v2`,
     `classifier-v3` and S4 on every page.
   - **(b) R1(b) recall and admissions.**
     - **Sources:** the laptop pass's one skipped `not_menu` Capture, plus discovery's candidate
       pages re-collected by a record-only re-crawl on the laptop. The re-crawl writes no Bronze
       or Menu rows, and it obeys robots.txt, the rate limit and the Helios User-Agent. Its
       venues are about 150: roughly 100 `no_menu_found` venues and 50 resolved ones, outside
       the excluded venues and sites.
     - **Labels:** every page where v2 and v3 disagree, plus about 100 pages that both reject.
     - **Recall bar:** met when, weighted by population over R1(a) and R1(b), the menus v3 adds
       are at least the menus it drops.
     - **Precision:** combines R1(a)'s kept pages with R1(b)'s new admissions.
   - **Pass rule** for precision (Q1): the stratified point estimate ≥ 0.95, with its Wilson
     interval recorded, as the extraction bars are judged.
5. **R4 is built with `classifier-v3`, in the same pipeline-version bump.**
   - **Leaving the queue.** A `menu-page` record leaves `due_pages` when either:
     - its latest fetch is a classifier rejection (a skipped `not_menu` / `js_only` Capture,
       after the §4 render where it applies); or
     - its menu URL was withdrawn (ADR-0015, `needs_review`).
   - **Retraction.** Each of the record's Menu streams (`llm`, `jsonld`) gets an appended
     `withdrawal` page: the Menu domain's existing tombstone, `state = 'withdrawn'`. No schema
     change and no deletion; Gold reads the tombstone as withdrawn.
   - **Re-checking existing pages.** Bumping the verifier makes ADR-0015 re-verify every saved
     URL. The pipeline-version bump re-scores every stored bundle with `classifier-v3`. Pages it
     rejects are withdrawn the same way, so the cleanup covers the whole laptop pass, not only
     sampled pages.
   - **Restoration.** A page that is accepted again gets a `restoration`.
6. **Deferred: render when accepted but empty** (Amendment 23 item 4). An accepted static page
   with no menu text takes the render path. This is built with the Pi rendering switch-on, not
   here. The survey's two accepted 0-block bundles are its cases.
7. **Not proposed:**
   - a threshold change on `classifier-v2`;
   - a new model or runtime dependency;
   - any per-site, per-platform or hand-entered rule.

   Retraining `classifier-v2`'s inputs alone, without the signals, is the smaller-build
   alternative (Q3).

## Amendment 25 (2026-10-21, accepted 2026-10-21): `classifier-v3` fails §8 precision; `classifier-v2` stays

**Status: Accepted 2026-10-21 by the owner (session P5-30), with the rulings below.** Record:
[2026-10-21-p5-30-classifier-v3-verdict.md](../reviews/2026-10-21-p5-30-classifier-v3-verdict.md).

**Owner rulings (2026-10-21):**
- **Q1, verdict:** the fail is accepted as written. `classifier-v2` stays, with no
  pipeline-version bump, and R4 waits.
- **Q2, lever:** the training mix. The labelled discovery candidates join the pool as a tenth
  set; the survey's leave-one-set-out is re-run with the same candidates and threshold rule; and
  admissions are measured on held-out candidate pages.
- **Q3, fresh sample:**
  - due-page precision comes from new venues (the Pi pass or new discovery runs), outside every
    classifier-labelled venue and site;
  - admissions come from the about 1,259 unlabelled `no_menu_found` sites.
- **Q4, labels:** the frozen blind labels stand, with no hand check.

1. **The samples (Amendment 24 item 4, owner rulings on the P5-29 record).**
   - R1(a): all 361 due pages, labelled blind.
   - R1(b), recorded by the record-only re-crawl:
     - P5-29's 102 venues and skipped Capture;
     - Q1: a seeded 50 of R1(a)'s venues (seed 20261023);
     - Q2: 200 more `no_menu_found` venues (seed-20261022 order, positions 101–300).
   - Labelled in R1(b): every v2/v3 disagreement (27), P5-29's 100-page both-reject sample,
     the skipped Capture and 2 live-replay picks.
   - Weights: `no_menu_found` 1,559 / 300 per venue; Q1 361 / 50; R1(a) a census.
2. **Precision fails.** R1(a)'s kept pages plus R1(b)'s v3-only pages give **0.773
   [0.711, 0.826]**, against the 0.95 bar. Every other reading also falls below it:
   - one unit per admitting venue, 0.877;
   - live replay (first accepted candidate), 0.884;
   - R1(a) scaled to all 1,632 due pages, ≈ 0.941.

   On due pages alone v3 reads 0.959 [0.933, 0.976], against v2's 0.931. The failure is new
   admissions. On `no_menu_found` sites v3 accepts 20 pages v2 rejects, and 4 are menus. The
   rest are off-domain shop, insurance and spam pages, press releases, a hub and app shells.
3. **Recall passes.** Weighted adds against drops: page level 49.7 against 5.0; live replay
   20.8 against 5.0.
4. **Decision: `classifier-v2` stays the verifier.**
   - No pipeline-version bump.
   - R4 waits for a classifier that passes (Amendment 24 Q5).
   - The laptop pass's rows stay, under Amendment 23 items 2 and 5.
5. **Next lever (owner Q2 and Q3):** the training mix (survey §5 risk 4).
   - Add discovery's labelled candidate pages to the pool as their own set.
   - Re-run leave-one-set-out with the same candidates and threshold rule.
   - Measure admissions on held-out candidate pages.
   - Verify on a fresh sample whose source the owner picks; every resolved `helios_laptop`
     site is now classifier-labelled.

   Still not proposed: a per-site, per-platform or hand-entered rule, or a new dependency.

## Amendment 26 (2026-10-21, accepted 2026-10-21): the training mix doesn't pass; next lever two verifiers

**Status: Accepted 2026-10-21 by the owner (session P5-31), with the rulings below.** Record:
[2026-10-21-p5-31-training-mix-survey.md](../reviews/2026-10-21-p5-31-training-mix-survey.md).

**Owner rulings (2026-10-21):**
- **Q1, verdict:** accepted; no training-mix candidate passes. Finding more websites and pages
  (discovery coverage) is a later upgrade, after the pipeline is finished.
- **Q2, lever:** two verifiers, `classifier-v2` AND `classifier-v3`. The recall loss of a verifier
  that only tightens (5 of R1(a)'s 336 menus) is accepted under §8's recall bar.
- **Q3, fresh sample:** re-run discovery on the failed-outcome venues outside the classifier
  exclusions, and sample due-page precision from what newly resolves.
- **Q4, labels:** the census labels stand, with no hand check.

1. **The candidate census (Amendment 25 item 5).** R1(b)'s 567 distinct candidate pages (352
   venues) are all labelled now: the 437 left after P5-29 and P5-30 were labelled blind under
   the strict full-read prompt and frozen before scoring. Totals: menu 97, not_menu 246, empty
   118, `js_only` 106. On `no_menu_found` sites, 18 of 443 candidate pages are menus. The census
   leaves `classifier-v3`'s P5-30 verdict unchanged (0.773).
2. **The survey.** Leave-one-set-out over 11 sets: the spike, S6f, the seven draws, R1(a) and the
   R1(b) census. Groups join venue and site, and R1(a) and R1(b) share Q1's 50 venues. The
   candidates are one family:
   - v2's inputs and the v3 recipe, without and with the candidate set in training;
   - the latter also with R1(b) weighted to its population.

   Thresholds come from the existing precision-0.95 rule inside each fold.
   - **No candidate passes.** The Amendment 24 combined estimate is 0.696–0.776 against the
     0.95 bar, with every upper bound below 0.83. Per-venue and live-replay readings are also
     below the bar.
   - The candidates do lift due-page precision: draws 0.962–0.972, R1(a) 0.959–0.974.
   - The best combined (`a+w`, 0.776) fails recall: it loses 35 R1(a) menus and adds 26.
3. **Why.** Among pages `classifier-v2` rejects on `no_menu_found` sites, every candidate admits
   20–33, and only 5–6 are menus. They are off-domain shop, insurance and spam pages, press posts,
   ordering pages with no menu text, and app shells, all scored 0.93–1.00. At these weights one
   false admission costs about 1.4 points. Oracle removal of every off-domain and every unpriced
   admission still leaves 0.90–0.94, so a further mix of the same page features is not proposed.
4. **Fresh-sample feasibility (owner Q3).**
   - The exclusion list is 1,463 venues and 1,452 sites
     (`var/menu-eval/p5-31/classifier-exclusions.json`).
   - **No resolved `helios_laptop` venue or due page is left outside it.** Due-page precision
     needs new resolved venues: a discovery re-run of the venues whose last outcome was a
     failure (about 2,650 outside the exclusions; yield unmeasured), or a venue-discovery
     refresh.
   - The admissions frame is 1,259 `no_menu_found` sites, ordered with seed 20261025; the first
     630 are proposed for the next admissions sample.
5. **Proposed next lever: two verifiers, `classifier-v2` AND `classifier-v3`** (owner Q2).
   - It is generic and already built, with no new model or dependency.
   - Precision on R1(a), held out from v3's training, is 0.959 [0.933, 0.976]. It admits nothing
     v2 rejects.
   - It drops 5 of R1(a)'s 336 menus and gains none. So it meets §8's recall bar only with an
     owner ruling: either that this loss is accepted, or a restated recall bar for a verifier that
     only tightens.
   - Before any ship, it is verified on a fresh due-page sample from new venues (item 4). R4 is
     built with it in the same pipeline-version bump (Amendment 24 item 5).
   - The alternative is venue-context signals: whether the page is about this venue. That needs
     the venue as a verifier input, and item 3's bound says it alone won't reach the bar.
6. **Unchanged.** `classifier-v2` stays the verifier, R4 waits, and the laptop pass's rows stay
   (Amendment 23 items 2 and 5). Still not proposed: a per-site, per-platform or hand-entered
   rule, or a new dependency.

## Amendment 27 (2026-10-21, accepted 2026-10-21): no fresh sample is reachable; ship v2 AND v3 with R4 under a post-ship check

**Status: Accepted 2026-10-21 by the owner (session P5-32), with the rulings below.** Record:
[2026-10-21-p5-32-two-verifier-verification.md](../reviews/2026-10-21-p5-32-two-verifier-verification.md).

**Owner rulings (2026-10-21):**
- **Q1, ship:** (a). The stage closes on the evidence in hand. Next is one pipeline-version bump
  with the AND verifier, R4 and re-verification of every stored bundle and saved menu URL, then
  the post-ship check (item 5).
- **Q2, redirects:** parked for the discovery-coverage upgrade; adopting a redirect target needs a
  venue-identity check (an ADR-0010 change).
- **Q3, labels:** the 7 labels stand, with no hand check.
- **Q4, new menu URLs:** the 12 stay, except the v2 false accept (a directory's help article),
  which is dropped through the ship's own re-verification and R4, not by hand. No extraction pass
  runs on `helios_laptop` before the ship.

1. **The fresh sample (Amendment 26 Q3).** Discovery was re-run, through its normal write path,
   on the 2,650 venues outside the classifier exclusions whose last outcome was a failure. The
   owner ruled that dev mode may skip the 20-day retry cooldown. **12 venues resolved, on 7 sites.**
   The other 2,638 failed again:
   - dead domains: `non_public_host` is mostly DNS failure;
   - bot blocking (`http_403`);
   - robots.txt that redirects to another host or doesn't answer;
   - redirects to other hosts.

   Resolved menu-URL records went from 1,635 to 1,647. The fresh due-page sample is therefore
   **7 pages** (one per site), against the about 100 the plan needs.
2. **Side evidence, not a verdict.** Labelled blind (strict prompt, every line read) and frozen
   before scoring:
   - `classifier-v2` keeps 7, of which 5 are menus;
   - v2 AND v3 keeps 5, all menus. It removes both v2 false accepts (a directory's help article,
     a menu hub) and loses no menu.

   This agrees with R1(a) (0.959 [0.933, 0.976]), but the Wilson lower bound of 0.566 settles
   nothing.
3. **Other sources measured.**
   - **Following cross-host redirects** (record only, robots.txt redirects followed as RFC 9309
     allows): 434 origins give 56 pages v2 accepts, 39 outside the exclusions. Many are another
     business (a lapsed domain sold on, another city, a new restaurant at the address).
     Adopting a redirect target needs a venue-identity check, which is a later ADR-0010 change.
   - **An ignore-robots mode** would reach about 28 sites. The owner dropped it.
   - **Overture lists a second website** for only 11 of the 2,638.

   A fresh sample of about 100 needs a new website source, which is the discovery-coverage
   upgrade set for after the pipeline (Amendment 26 Q1).
4. **Proposed: close the stage on the evidence in hand.**
   - **Ship v2 AND v3 with R4** in one pipeline-version bump, as in Amendment 24 items 2 and 5:
     - the AND verifier;
     - `due_pages` exclusion and tombstone retraction of rejected and withdrawn pages;
     - restoration of a page that is accepted again;
     - re-verification of every stored bundle and saved menu URL.
   - **The evidence:**
     - R1(a), held out from v3's training: 0.959, small 0.944;
     - P5-31's held-out readings for the v3 recipe;
     - item 2.
   - **Why the residual risk is small:**
     - the AND admits nothing v2 rejects;
     - its recall loss is accepted (Amendment 26 Q2);
     - R4 is reversible by a later version bump.
5. **Post-ship check (replaces the pre-ship fresh sample).** The first about 100 new due pages from
   the next venue source (an Overture refresh or the coverage upgrade), outside the classifier
   exclusions, get the R1(a) blind page-level check. A stratified point estimate below 0.95 opens
   a replacement through the amendment path.
6. **Unchanged until the ship lands.**
   - `classifier-v2` stays the verifier, and R4 is not built.
   - The laptop pass's rows stay (Amendment 23 items 2 and 5), and the 12 new menu URLs stay.
   - Still not proposed:
     - a per-site, per-platform or hand-entered rule;
     - an ignore-robots mode or getting past bot blocking;
     - adopting redirect targets without a venue-identity check;
     - a new dependency.

**Build (P5-33, 2026-10-21; owner questions in its PR).** One pipeline-version bump. Its only
changed component is the classifier name, now `classifier-v2+v3`. No schema, model or Menu
write-contract change.
- **Verifier.** `AllOfClassifiers` accepts a page when both weights files' thresholds pass. It
  segments and embeds the page once. It is discovery's verifier (`resolve_urls`), the
  menu-page classifier (`menu_pipeline.run`) and extraction's scorer. A page's confidence is
  the lower of the two probabilities.
- **Out of `due_pages`:**
  - `menu_url_withdrawn`: the menu-URL record with the same key is in `needs_review`;
  - `fetch_rejected`: the latest Capture that read the page, on its Version's endpoint, its
    URL or the URL saved now, is a skipped `not_menu` / `js_only`. Failed fetches and other
    skips are passed over, as ADR-0015 Amendment 1 item 2 keeps a URL on them. A render is a
    later Capture than its static fetch, so it decides;
  - `withdrawn`: the `llm` head is a withdrawal on the latest Version, and no accepted
    Capture was stored after it.
- **Withdrawals.** Each published stream gets an appended `withdrawal`:
  - on the record's latest Version, citing its Version Evidence;
  - under its current scope, with `method_version` = the stream's pipeline version and
    confidence 1.
  They are written at the start of every extraction run, and by
  `python -m apps.menu_pipeline.rescore` without the model.
- **Re-score.** Every due page's bundle is scored before any model call. After the bump,
  that is every stored page outside the queue rules. A rejected page is withdrawn
  (`rescored`). A rejected page with no published stream (never extracted, or already
  withdrawn) can't take a tombstone. It stays due and is skipped each run
  (`rejected_unwritten`).
- **Restoration.** A withdrawn page becomes due again after a new Version or an accepted
  fetch. Its next pages are written as `restoration`s.

## Amendment 28 (2026-10-24, proposed): stage [5c] section assignment from page structure

**Status: Accepted 2026-10-24 by the owner (session P8-11), with the rulings below. Built in
P8-12 (build note below); §8 held-out check passed. Applied to `helios_laptop` 2026-10-24.**
Record: [2026-10-24-p8-11-menu-structure.md](../reviews/2026-10-24-p8-11-menu-structure.md);
build and evaluation: [2026-10-24-p8-12-section-assignment.md](../reviews/2026-10-24-p8-12-section-assignment.md).

**Owner rulings (2026-10-24):**
- **Q1.** Build (b). Option (a) is dropped: the LLM side is near its limit and GPU
  re-extraction is time-intensive. The classical, structural dimension is undeveloped.
- **Q2.** Page gate: ≥90 % of items assigned, with no corroboration gate.
- **Q3.** Fold [5c] into the post-validator component: `resolve-v2` becomes `resolve-v3`. No
  migration.
- **Q4.** Candidates come from `h1`–`h6` and class words, and layout decides which count. The
  owner's principle: element names can't be trusted, and hierarchy should cluster child items
  under their section.
  - Class words only nominate a candidate. A candidate counts only if its layout signature
    repeats, encloses items of another layout and wraps them, and the page passes the gate.
  - Two name-free variants were measured and rejected (record section 6a):
    - container labels: applied 0.644, 18 pages worse;
    - pure layout: 0.531.
  - Both fail on flat sibling layouts, where nesting doesn't separate sections.
- **Q5.** Leaf sections only in this version.
- **Q6.** The §8 plan and bars as proposed (items 3–4): 35 pages, seed 20261024, 25 gated / 10
  ungated.
- **Q7.** Queue four follow-ons, each with its own amendment and evaluation after [5c] ships:
  - case 5 variants and modifiers;
  - pseudo-item cleanup;
  - outline parents and `service_period`;
  - image-menu signals.

  Barstool Bites' menu URL was not chosen and stays an open side finding.

**Why.** The owner found six menu-structure misses on the local site. All six are traced to a
stage (record section 2):
- **[3] chunk context, fed by [2].** segment-v2 keeps only a yes/no `heading` per block, so a
  dish printed in an `h3` looks like a section heading. The chunker names the last such block
  in the next chunk's context line, and the model files the following dishes under it:
  Veracruz "Pineapple" / "Shrimp Taco", Vivo "California Nachos", Barstool Bites "Chicken
  Caesar*", Que Divino "Picadillo Con Papa".
- **[4] model output.** Inside a chunk, the model sometimes ignores a heading and keeps the
  previous section. On Los Mayas, 28 of 94 items are wrong this way: the sides under DINNERS,
  and BURRITOS, MEXICAN SPECIALS and KIDS SPECIALS missing.
- **Not section losses:**
  - Veracruz's missing Aguas Frescas items are a [4] recall miss;
  - Que Divino's BYO options have no place in the extraction contract (no modifier slot; no
    `menu_modifier` row exists for any page);
  - Bottega's drinks exist only in images (§9).

In every reported case the page's DOM prints the right section. Corpus-wide (863 page texts,
1,568 venue records, read-only):
- **38 % of named sections (3,003 of 7,934) are a dish's name**, not a heading;
- on 58 % of pages (501), some chunk's context names a dish as the heading;
- on 714 pages that already carry gold labels, **today's section accuracy is 0.438**.

### Options

- **(a) Forward: richer segmenter/chunk input.** Give the model heading levels and a context
  line that names the enclosing section heading.
  - It changes the chunker (and the segmenter, if `Block` gains fields), so the extractor key
    changes.
  - Every page is re-extracted on the laptop GPU, and the extraction bars (recall, accuracy,
    catch, FR, usable) need a full held-out §8 evaluation.
  - If the segmenter output changes, `text_hash` and the segmenter tag in every Evidence
    locator change too. Every page then gets a new `menu-page` Version (§5).
  - It can't fix [4]'s in-chunk misses (the Los Mayas kind), because the heading is already
    in the chunk.
- **(b) Reverse: post-hoc section assignment (proposed).** A new pure stage [5c] between [5b]
  and shape. It re-parses the bundle's HTML with the segment-v2 parser and asserts identical
  blocks; any mismatch means no assignment. It then maps each kept item's name block to its
  enclosing section heading when the page's structure is clean, and keeps today's section
  otherwise.
  - The segmenter, `text_hash`, Versions, the extractor key and saved answers are unchanged,
    and every row, verdict and price is unchanged.
  - Item and price Evidence locators are unchanged. A re-assigned section cites its heading
    block's span in the same locator format.
  - No model call is needed: a version bump re-interprets every page from its saved answers
    (replaying all 863 page texts takes 16 s on 8 laptop cores).
- **(c) Not adopted:**
  - per-platform section parsers (Toast, Wix, WordPress), which §9 and the owner rule out;
  - renaming sections in shape alone: it can't see the DOM.

### Proposed: [5c] rules (generic; prototype `var/p8-11/domsec.py`, record section 4)

1. **Candidate headings.** Non-chrome, unpriced blocks with letters:
   - the first block of an `h1`–`h6` element;
   - or a block whose own element classes read as a heading or category title. Instance ids
     such as `section-<uuid>` don't count, and nor do item, price, nav or button classes.
2. **Section style.** Headings are grouped by layout signature (their last three block-level
   ancestors' tag and first class, ids and digits masked). A signature is a section style when
   at least half its headings, and at least two, enclose an extracted item of another
   signature before the next heading of the same signature.
   - This separates Toast's group `h3` from its dish `h3`.
   - It drops a lone page title, location or welcome heading.
3. **Assignment.** An item's section is the nearest preceding section-style heading. Earlier
   section-style `h` headings of a lower level are its outline parents, for example Toast's
   "Lunch & Dinner" over "Desserts".
4. **Page gate.** At least 90 % of the page's kept items are assigned, and either the headings
   wrap their items (each heading's lowest common ancestor with an item holds no other heading
   of its style, for at least 95 % of items) or one heading style serves them all.
   - On a gated page, assigned items take the DOM section; the rest keep today's.
   - Ungated pages are unchanged.
5. **Shape.** A [5c] section is keyed and evidenced on its heading block, as a grounded section
   is today, with the heading's printed text as its name. `Unsectioned` remains for items
   without one.

### Measured (dev, not §8: the rules were tuned on these)

- **Coverage.** The gate applies to 469 of 863 page texts (54.3 %): 747 of 1,568 records and
  37,988 of 59,289 items (64.1 %). Of those items, 21,635 change section. Under the strict
  gate (every item unambiguous), 393 page texts (45.5 %) and 31,859 items qualify. 255 pages
  (29.5 %) have no section structure at all.
- **Label-based** (714 labelled pages, 20,411 gold-matched items, lenient token match):

  | | Today | (b) applied |
  |---|---|---|
  | All 714 pages | 0.438 | **0.704** |
  | 412 gated pages | 0.446 | **0.875** |

  On gated pages, 165 pages get better and 7 worse (+5,512 / −84 items). Exact match: 0.405 →
  0.687.
- **Hand audit** of 56 disagreements: 12 are pseudo-items (headings or nav emitted as items).
  Of the other 44, the DOM is right in 39, today's in 4, both wrong in 1.
- **The six cases:** every reported item gets the section the owner expects. Cantaloupe stays
  missing and BYO options stay unparsed (not section losses).

### Cost and versioning

- **No GPU, model, segmenter, chunker or Bronze change.**
- **Pipeline-version bump.** Every published `llm` page is re-interpreted from its saved
  answers (ADR-0005 interpretation revision): Menu writes for about 1,600 records, then a Gold
  refresh (about 8 min, per the P8-3 record). Both run on `helios_laptop` only with the owner's
  go-ahead.
- **`method_version` is 126 of its 128 characters.** A new `;sections-v1` component doesn't
  fit (`extraction._checked` raises). See Q3.
- **Item ids.** Native keys are version-local (`v<version>:<heading block>:<name>`, N1). A
  re-sectioned item gets a new path, so its `item_id` and price-history trail start at the bump
  inside the current Version. That is the same effect any page-text change has today.
- **Pi.** [5c] adds one stdlib HTML parse per page. Its time is measured on the Pi at build
  (speed test only; the model is unchanged).

### §8 evaluation plan

1. **Metric: section accuracy.**
   - Scope: gold items that a kept row matches, with a non-empty label section outside a wine
     list.
   - An item is correct when its stored section name equals the label's after
     `norm_tokens` (exact). The lenient token-subset match is recorded beside it.
   - Reported per page, with the page-clustered bootstrap (Amendment 19 1(a)).
   - Also recorded:
     - the gated-page share and per-page better/worse counts against today;
     - the `Unsectioned` rate;
     - sections named after a dish.
2. **Labels.** No new field. LABELLING.md already defines `section` as "the nearest section
   heading the page prints above the item, as printed". Labelling is blind: the labeller sees
   neither today's sections nor [5c]'s.
3. **Held-out set.** A fresh draw (seed 20261024) of 35 pages. The pool is the 149 production
   page texts that are neither labelled nor audited (57 of them gated). Stratified 25 gated /
   10 ungated. The exclusions (the 1,287 labelled page text hashes and the audited URLs) are
   frozen with their sha256 before labelling.
4. **Bars (proposed, owner sets them).**
   - On gated pages, section accuracy ≥ 0.85 and at least today's + 0.20 (point estimates).
   - At most 1 gated page in 10 worse than today.
   - Ungated pages identical to today, checked.
5. **Existing §8 bars carry over without a GPU run.** An invariance check runs on every page
   of the dev and held-out sets: [5c] changes no row, verdict, price, item count or Evidence
   other than section keys and section Evidence.

### Not in this amendment (later amendments, if the owner wants them)

- Option (a).
- **Variants and modifiers in an item's own text** (case 5): 6,024 items (9.8 %) print more
  prices in their own region than were extracted, and 2,909 (4.7 %) carry a choice line.
- **Pseudo-item removal** using the section-style rule. It touches item recall and the
  extraction bars.
- **Outline parents into `menu_section.parent_section_id`, and time-of-day sections into
  `service_period`.**
- **Image-menu detection** (case 6). The plan is record-only signals and a 50-page blind
  labelled sample before any rule (record section 8). OCR stays out of scope.

### Owner questions

- **Q1. Build (b) as the next pipeline version?** (Recommended; (a) stays a later candidate,
  measured on the GPU.)
- **Q2. Page gate.** ≥90 % assigned (recommended; applied accuracy 0.704, +5,512 / −84). Or
  every item assigned (0.671, +4,823 / −74). Add a corroboration gate, where ≥25 % of the DOM
  headings used must also be section names the model gave (0.679, +4,940 / −27)? Recommended:
  no corroboration, which keeps [5c] independent of the model.
- **Q3. Version naming within 128 characters.**
  - (i) Fold [5c] into the post-validator component: `resolve-v2` becomes `resolve-v3`, "[5b]
    and [5c]", with no length change. Recommended: no migration.
  - (ii) Widen `menu_page.method_version`. That is a migration on a table with data, so it
    stops for review.
- **Q4. Class-named headings.** Include them (recommended; Squarespace's `menu-section-title`
  and similar), or `h1`–`h6` only? `h1`–`h6` only is safer but covers fewer pages.
- **Q5. Outline parents.** Store them now in `parent_section_id` (shape and writer change, no
  schema change), or keep leaf sections only for this version (recommended)?
- **Q6. §8 bars and draw** as in plan items 3–4, or other values?
- **Q7. Follow-ons.** Which to queue next?
  - case 5 options;
  - pseudo-items;
  - image-menu signals;
  - Barstool Bites' menu URL (`seasideonthepier.com` looks like another restaurant; ADR-0010).

**Build (P8-12, 2026-10-24; record
[2026-10-24-p8-12-section-assignment.md](../reviews/2026-10-24-p8-12-section-assignment.md),
owner questions in its PR).** One pipeline-version bump: `resolve-v2` → `resolve-v3` ([5b] +
[5c]). `method_version` stays 126 characters. No schema, model, prompt, chunker, segmenter or
Menu write-contract change.
- **Stage.** `packages/helios_parsing/dom_sections.assign(html, blocks, verdicts)` (stdlib).
  - It re-parses with a subclass of segment-v2's parser; if the blocks differ, nothing is
    assigned.
  - It then applies rules 1–4 above as ruled (Q2: ≥ 90 % assigned, no corroboration gate;
    Q4: `h1`–`h6` and class words).
  - It returns the assignment for gated pages only.
- **Shape.** `menu_shape.shape(..., headings)` files an assigned item under its heading block:
  - the key is `<heading block>:<normalized heading text>`;
  - the name is the printed heading text;
  - the Evidence is the heading block's span.

  Leaf sections only (Q5). An item whose move would merge two of the page's items (the same
  printed item that the model emitted under two sections) keeps today's section. That keeps
  every row, item, variant, price and their Evidence unchanged. Corpus-wide this holds back
  599 items on 151 of 863 page texts.
- **Run.** `extraction._Run._write` applies [5c] to the `llm` stream only. The `jsonld` stream
  is unchanged.
- **Harness.** `evaluation.section_page` and `apps.menu_pipeline.evaluate sections` report
  plan item 1's metric and the item 4 bars.
- **Dev (714 labelled pages):**
  - applied lenient 0.712, exact 0.695;
  - gated pages 0.887 / 0.882;
  - 166 better / 7 worse (lenient).

  This reproduces the prototype exactly once the prototype's name-fallback scoring is used and
  the merge guard is switched off (0.704; 165 / 7; +5,512 / −84).
- **§8 held-out** (seed 20261024; 149-text pool, 56 gated; 25 gated / 10 ungated drawn; 32 menu
  pages scored):
  - gated pages exact **0.961** [0.946, 0.976] against today's 0.461;
  - 0 of 23 gated pages worse;
  - ungated pages identical;
  - invariance clean on every dev, held-out and production page.

  Every bar passes.
- **Speed.** [5c] takes a median of 14.4 ms per page on one laptop core (p95 53 ms), about 18 s
  for all 863 page texts. The Pi was not timed (it needs the owner's go-ahead).
- **Applied to `helios_laptop`** (owner go-ahead, 2026-10-24; record section 5a): every
  published `llm` page re-interpreted from saved answers (1,597 pages, 0 model calls), then
  a Gold refresh.

## Amendment 29 (2026-10-24, proposed): stage [5d] page template and duplicate emissions

**Status: Accepted 2026-10-25 by the owner, with the rulings below. Built in P8-14 (build note below); the §8 held-out check fails one stage bar and two §8 bars. The owner's P8-14 rulings (note at the end) narrow rule "same", treat the two §8 failures as a known validator gap, and approve applying it after a dev re-check (P8-15).**
Record: [2026-10-24-p8-13-page-template.md](../reviews/2026-10-24-p8-13-page-template.md).

**Owner rulings (2026-10-25):**
- **Q1.** Build (i): [5d] with all four actions (ADD, DROP, RE-NAME, ATTACH) plus duplicate
  removal. Fold them into the post-validator component, so `resolve-v3` becomes `resolve-v4`.
  `method_version` stays 126 characters, so there is no migration.
- **Q2.** Gate: 0.8 explained and 0.8 agreement, with at least 5 seeds. A pattern counts
  with support from at least 3 seeds and at least 10 % of them.
- **Q3.** Duplicate rule "same": remove extra copies only when every copy cites the same
  printed price spans. Removal is at the row level, before shape, so [5c] places the
  survivor.
- **Q4.** The model's variant grouping is dropped as a seed signal. There are no "one seed
  per model item" or "re-attach only where the model grouped variants" options.
- **Q5.** (A) Held-out: all 39 template-gated pool page texts plus 10 ungated texts drawn
  with seed 20261025.
  - The pool is 114 production texts. It excludes labelled text hashes, audited URLs, the
    P8-12 draw, and the P8-11 / P8-12 / P8-13 traced cases.
  - The exclusions and the draw are frozen with sha256 before any labelling.
- **Q6.** The bars are §8's: item recall ≥ 0.85, price accuracy ≥ 0.98, gold-row false
  reject ≤ 0.12, corruption catch ≥ 0.97 and usable prices ≥ 0.74. The stage bars in plan
  item 1 also apply, on template-gated pages against `resolve-v3` on the same pages:
  - item recall and kept-item precision not lower;
  - accepted rows matching no label up by at most 1 % of kept rows;
  - at most 1 gated page in 10 loses a gold item;
  - Amendment 28 section accuracy not lower;
  - ungated pages unchanged by [5d].
- **Q7.** All four follow-ons are queued, each with its own amendment:
  - validator grounding to the print nearest the cited block;
  - the chunk-boundary fix;
  - the case-5 variant reader for ungated pages;
  - wine and fee lines.

  The owner's conditions:
  - **Wine-list specifics:** ask the owner before designing anything.
  - **GPU/LLM-process parts** (chunker, prompt, model, re-extraction): the owner decides. Ask
    before designing.
- **Direction (owner, 2026-10-25).** The main innovation is LLM-first extraction, then HTML
  parsing derived from the LLM's own results, which gives one universal pipeline. The LLM pass
  sorts pages into predictable trends, so no page needs its own case. This work needs human
  guidance: stop and ask at design forks.

**Why.** The owner's second round of findings on the local site ("issues 2"), each confirmed
against stored data (record section 1):
- **Halal Wings** stores ingredient lines as items, five of them priced with Caesar Salad's
  $9.39, and misses Caesar Salad and Jalapeno Salad.
  - [4]: the model named rows by the description under a priced title.
  - Repairs: `split_listed` made one row per ingredient.
  - [5]: the validator accepted the rows with the next line's price.
- **Jarochos** stores "Pequeño / Mediano / Grande" as items. [4] put the size label in the
  name slot.
  - The stored Capture prints the values the owner expects, and no newer Version exists.
  - The $20.99 / $28.49 the owner saw are the next dish's printed prices; the API orders
    items by name.
- **Los Mayas and Vivo** keep one-dish sections.
  - [3]: an item split across a chunk boundary is re-emitted from the next chunk's context
    line.
  - [5]: both copies ground to one name block.
  - [5c]: the merge guard keeps both in place.
  - On Vivo, a dish printed twice also collapses onto its first print.

Corpus-wide (863 page texts, record section 2):
- duplicate emissions on 243 pages (708 item keys, 272 one-dish sections);
- 6,710 pseudo-items on 590 pages (1,731 priced);
- 11,379 printed priced lines that no item cites (6,828 on the page's own item-price path);
- 335 size labels stored as items.

### Options

- **(a) Forward fixes at the source.**
  - A chunker that never splits an item from its price, or no re-emittable context tail.
  - Prompt changes for size labels and descriptions.

  These change the extractor key, so every page is re-extracted on the GPU and a full §8 run
  follows. They do not reach the validator's grounding collapse.
- **(b) Reverse: a page-template stage [5d] plus duplicate removal (proposed).** No model
  call; every page is re-interpreted from its saved answers, as Amendment 28 was. Generic and
  stdlib; no per-site or per-platform rule.
- **(c) Duplicate removal alone.** It fixes the reported one-dish sections and loses no gold
  item, but leaves the pseudo-items, the missed items and the size-label items.
- **(d) Not adopted:**
  - per-site wrappers (ruled out by §9 and the owner);
  - hand-entered fixes;
  - a learned classifier (the owner's Amendment 19 constraint: deterministic only).

### Proposed rules (prototype `var/p8-13/template.py`, record section 3)

1. **[5d] page template**, after [5b] on the `llm` stream.
   - **Seeds:** accepted rows with a name block and a price block.
   - **Record pattern** of a seed:
     - the tag paths of its name and price blocks (last three block-level tags; classes are
       not trusted);
     - their block offset, the common ancestor's tag, and how many levels each sits under it.
   - **Template:** seeds are grouped by exact pattern; a group counts with at least 3 seeds
     and at least 10 % of them.
   - **Page gate:** at least 5 seeds; ≥ 80 % explained; ≥ 80 % of explained seeds on one name
     path. Ungated pages are unchanged.
   - **Name candidates:** a block on a template name path that prints its own price (for a
     same-line pattern) or carries a seed's class signature (for a split pattern). Its record
     runs from it, inside the pattern's container, to the next candidate.
   - **Actions,** on kept rows named inside another candidate's record:
     - **ATTACH:** a size label printed with its price in a run of 2+ labelled prices becomes
       a variant of the record's dish.
     - **RE-NAME:** a row named by the title's words but cited on the description is
       re-grounded on the title. An accepted description row priced inside the record of a
       title kept unpriced takes the title's name.
     - **DROP:** a description-like line (repairs' `_description_like`) with no price of its
       own and not printing the row's amount. A pipe-separated list stays.
     - **ADD:** an uncited template price line becomes an item, its name read from the
       template's name position: one row per printed price, labelled when there are several.
       It is skipped when it is inside a kept item's span, an add-on, description-like or
       price labels only, below a dish kept unpriced, under a wine-list heading, or a name
       and price already on the page.
   - **Safety net:** every added or rewritten row is judged again by the unchanged
     validator.
2. **Duplicate removal** (rule "same"), on every page, after [5d] and before [5c].
   - A printed item (name block, name) the model emitted under two or more of its sections
     keeps the rows of its first section, when every copy cites the same printed price
     spans.
   - [5c]'s merge guard then no longer holds it back, so on a gated page it lands under its
     DOM section.
   - Copies citing different prices (a second printed dish grounded onto the first) are kept.
3. **Evidence.** Nothing new.
   - Added and rewritten rows carry the validator's name and price spans on the Version's
     blocks, in today's locator format.
   - A removed duplicate's price spans are the same spans its kept copy cites.

### Measured (dev, not §8: the rules were tuned on these pages)

294 scorable labelled pages (P8-12's 714 plus its 32 held-out pages; the extraction harness
scores pages with a priced gold item). The template gate covers 223. Changes are on gated
pages, with page-clustered 95 % intervals:

| Measure | Today (resolve-v3) | With [5d] | Change |
|---|---|---|---|
| Item recall | 0.892 | 0.931 | +0.039 [+0.033, +0.046] |
| Kept-item precision | 0.811 | 0.844 | +0.033 [+0.025, +0.042] |
| Usable prices | 0.812 | 0.856 | +0.044 [+0.037, +0.051] |
| Price accuracy (accepted) | 0.9934 | 0.9934 | ±0.001 |

- **By action:**
  - ADD 926: 783 new gold items, 93 match none, 21 rejected by the validator;
  - DROP 853: 754 non-items, 26 lose a gold item;
  - RE-NAME 77: 74 right;
  - ATTACH 29: 24 exact.
- **Pages:** 149 gain gold items and 5 lose some. Accepted rows matching no label +9, wrong
  accepted rows +14, row-level false rejects −16.
- **Validator bars:** gold-row false reject and injected-corruption catch are computed by the
  validator alone on gold rows, so they cannot move.
- **Duplicate removal ("same"):**
  - corpus: 596 copies removed (356 duplicate price rows), 151 fewer one-item sections, no
    printed price Evidence lost;
  - dev: −208 items, 0 gold items and 0 gold prices lost;
  - every reported one-dish section goes.
- **Section accuracy** (Amendment 28 metric, all 746 dev pages): 0.715 → 0.723 exact, with
  both. 154 pages gain exact-section items and 8 lose some.
- **Variants tried:**
  - gate 0.9: fewer pages, slightly cleaner;
  - one seed per model item, and re-attaching only where the model grouped variants: the
    model's own grouping adds nothing measurable;
  - ADD only: recall +0.038 with no page losing a gold item, but precision +0.003.

### Cost and versioning

- **No GPU, model, prompt, chunker, segmenter, validator or Bronze change.** About 38 ms per
  page on one laptop core (p95 242 ms). The Pi is not timed.
- **Version:** fold into the post-validator component, as Amendment 28 did. `resolve-v3` →
  `resolve-v4` = [5b] + [5c] + [5d] + duplicate removal. `method_version` keeps 126 of 128
  characters, so there is no migration.
- **Data:** every published `llm` page is re-interpreted from saved answers, then Gold is
  refreshed. Both run on `helios_laptop` only, with the owner's go-ahead.
  - Item counts change: adds, drops, merged duplicates, size labels folded into variants.
  - An added, re-named or merged item gets a new native key in the current Version.

### §8 evaluation plan

1. **Bars: §8's extraction bars apply**, because items are added and dropped:
   - item recall ≥ 0.85;
   - price accuracy ≥ 0.98;
   - gold-row false reject ≤ 0.12;
   - corruption catch ≥ 0.97;
   - usable prices ≥ 0.74.

   Proposed for this stage, on template-gated pages against resolve-v3 on the same pages
   (point estimates):
   - item recall and kept-item precision not lower;
   - accepted rows matching no label up by at most 1 % of kept rows;
   - at most 1 gated page in 10 loses a gold item;
   - Amendment 28 section accuracy on [5c]-gated pages not lower;
   - ungated pages unchanged by [5d].
2. **Held-out set.** The pool is the production page texts that are neither labelled,
   audited, drawn by P8-12, nor traced in P8-11 / P8-12 / P8-13: **114 page texts, 39 of them
   template-gated**. Plan: all 39 gated pages plus 10 ungated drawn with seed **20261025**.
   The exclusions (labelled text hashes, audited URLs, the P8-12 draw and traced cases) are
   frozen with their sha256 before labelling.
3. **Labels.** Blind, full-item labels per LABELLING.md. Labellers see the page blocks only,
   never the pipeline's output. Each labeller works in its own private scratch folder.
4. **Scoring.** `score_page` and kept-item precision with and without [5d] + duplicate
   removal, per action class, page-clustered; plus `evaluate sections`.

### Not in this amendment (queued if the owner wants them)

- (a) the chunk-boundary root cause (an extractor-key change);
- validator grounding to the print nearest the cited block (Vivo's second Chipotle
  Enchiladas; it moves the false-reject and catch bars);
- the case-5 variant reader for ungated pages (Amendment 28 Q7);
- wine lines the model does not label as wine, and fee / note lines.

### Owner questions

- **Q1. Build which?**
  - (i) [5d] with all four actions plus duplicate removal, as `resolve-v4`. Recommended.
  - (ii) Duplicate removal alone first (no gold loss on dev).
  - (iii) [5d] ADD only plus duplicate removal: no page loses a gold item on dev, but most of
    the precision gain is given up.
- **Q2. Gate.** 0.8 explained / 0.8 agreement (recommended: 223 pages) or 0.9 (177 pages,
  slightly cleaner)?
- **Q3. Duplicate rule.** "same" (recommended: no printed price Evidence lost) or "all" (also
  drops the second printed dish's copy: −104 distinct price spans, −57 dev gold prices)?
- **Q4. Model grouping.** Drop it as a seed signal (recommended; it adds nothing measured)?
- **Q5. Held-out size.** The pool has only 39 template-gated texts.
  - (A) Label all 39 plus 10 ungated now. Recommended.
  - (B) Wait for the next crawl's new pages.
- **Q6. Bars** as in plan item 1?
- **Q7. Follow-ons:** which of the "Not in this amendment" items to queue?

**Build (P8-14, 2026-10-25; record
[2026-10-25-p8-14-page-template-build.md](../reviews/2026-10-25-p8-14-page-template-build.md),
owner questions in its PR).** One pipeline-version bump: `resolve-v3` → `resolve-v4`.
`method_version` stays 126 characters. No schema, model, prompt, chunker, segmenter,
validator or Menu write-contract change.
- **Stage.** `packages/helios_parsing/page_template.py` (stdlib):
  - `induce` is [5d] at the ruled config (Q2), with all four actions (Q1) and no model
    grouping (Q4);
  - `remove_duplicates` is rule "same" (Q3);
  - `llm_stream` is the `llm` stream's interpretation in the ruled order: `rows_of` →
    [5]+[5b] → [5d] → [5]+[5b] on gated pages → duplicate removal → [5c].
  - Ties between equally supported patterns are broken in a fixed order. The prototype's
    hash order changed its output on one corpus page.
- **Run.** `extraction._Run._write` uses `llm_stream`. The run report counts [5d]'s
  actions and the duplicates removed. The `jsonld` stream is unchanged.
- **Harness.** `evaluation.template_page` / `template_bars` and
  `apps.menu_pipeline.evaluate template` report kept-item precision, the per-action checks
  against gold and the Q6 stage bars. `compare`, `loss`, `report` and `sections` now score
  the full `llm` stream.
- **Dev:** the prototype reproduced page by page.
  - On 223 gated pages:
    - recall 0.892 → 0.931;
    - kept-item precision 0.811 → 0.844;
    - usable prices 0.812 → 0.856.
  - Corpus actions: ADD 2,036 rows (1,847 items), DROP 1,813, RE-NAME 186, ATTACH 57.
  - Duplicates: −596 items, with no price Evidence lost.
  - Section exact 0.7151 → 0.7230. That is 0.7228 measured the prototype's way, which
    re-judged after removal.
- **§8 held-out** (seed 20261025: 39 gated + 10 ungated drawn, 38 scorable; frozen sha256s
  in the record):
  - **Pass:** item recall 0.903, usable prices 0.759, catch 1.000. Against resolve-v3 on
    the gated pages:
    - recall +0.063;
    - kept-item precision +0.027;
    - accepted rows matching no label −9;
    - section accuracy +0.009;
    - ungated pages unchanged; no price Evidence lost.
  - **Fail:**
    - 4 of 37 gated pages lose a gold item (at most 1 in 10 allowed);
    - price accuracy 0.916 (resolve-v3 0.908);
    - gold-row FR 0.156, the validator's alone.

  The price-accuracy and FR failures come mostly from one page that prints prices before
  names.
  **Not every bar passes, so it is not applied to `helios_laptop`;** the owner decides.
- **Speed:** a median of +11.9 ms per page on one laptop core (+28.5 ms on gated pages).
  The Pi was not timed.

**Owner rulings after P8-14 (2026-10-25; carried out in P8-15).**
- **Q1. Rule "same" narrowed.** Copies of a printed item are duplicates only when every copy
  cites the same *non-empty* set of printed price spans. Unpriced copies stay.
  - This answers the held-out's two dedupe losses (`79f66c5309ed` "Paloma",
    `ad991b67d739` "Vegetarian Antipasto"): both copies were unpriced, the model's second copy
    was grounded onto the first print, and removal took the gold item at the second print.
  - Re-check it on dev now: the 746 / 294 dev pages and the corpus.
  - The §8 held-out re-test waits for the next crawl, because this pool's 39 gated texts are
    used. **The P8-14 held-out set is now dev.**
- **Q2. Known validator gap.** §8 price accuracy (0.916) and gold-row FR (0.156) on the
  P8-14 set don't block [5d]. They come mostly from the "price printed before its name"
  layout (Dahlia Café, `d57b5b288970`). The gap is recorded and queued with the grounding
  follow-on (Q4).
- **Q3. Apply once the verdict is settled.** Approved:
  - a re-interpretation of every published `llm` page on `helios_laptop` from saved answers,
    then a Gold refresh;
  - a speed-only timing on the Pi.
- **Q4. Next follow-on:** validator grounding to the print nearest the cited block (Q7's
  first item). It is proposed as its own amendment.

**Carried out (P8-15, 2026-10-26; record
[2026-10-26-p8-15-same-narrowed-and-grounding.md](../reviews/2026-10-26-p8-15-same-narrowed-and-grounding.md)).**
- **Rule "same" narrowed** (still `resolve-v4`; #125 was not merged, and PR #126 replaces it).
  - Dev: duplicate rows removed 567 → 349, and nothing else changes except section exact,
    0.7230 → 0.7212.
  - The P8-14 set (now dev): pages losing a gold item 4 → 2, and every stage bar passes.
- **Applied to `helios_laptop`:** 1,597 pages re-interpreted from saved answers (0 model
  calls), then Gold refreshed. Gold has 59,860 `current_menu` rows (from 58,031) and 1,976
  one-item sections (from 2,161).
- **Pi, one core:** a median of +26 ms per page.
- **Q4:** proposed as Amendment 30.

## Amendment 30 (2026-10-26, proposed): validator grounding to the nearest print, and glued names

**Status: Proposed 2026-10-26 (P8-15). Accepted in part 2026-10-26 by the owner: g1f + G3 are built as `validator-v9` (P8-16, build note below); G2 is dropped for now. The build adds 8 invariance-suite page/style pairs (ADR-0017 item 1); the owner accepted them as claim-style invariance debt (Q-A30 (a), 2026-10-26).**
Record: [2026-10-26-p8-15-same-narrowed-and-grounding.md](../reviews/2026-10-26-p8-15-same-narrowed-and-grounding.md),
section 6. Prototype: `var/p8-15/ground.py` (untracked). Build record:
[2026-10-26-p8-16-validator-v9.md](../reviews/2026-10-26-p8-16-validator-v9.md).

**Owner rulings on P8-15 (2026-10-26):**
- **Q1.** Build g1f + G3. G1 stays in its narrow g1f form. G2 is dropped for now, to be
  revisited with the shared-section-price resolver's section bounds (Amendment 32).
- **Q2.** The §8 held-out re-test of resolve-v4 (and of `validator-v9`) waits for the next
  crawl's new page texts.
- **Q3.** Close #125; #126 replaces it. #125 had already been merged before #126; its rule
  "same" is superseded by #126's narrowed one on `main`.
- **Q4.** The two remaining [5d] losses (a dish whose only name line reads like a
  description) are queued under F2 (the gap audit's [5d] RE-NAME fix).
- **Q5.** The owner handles the Pi's `known_hosts` entry and its DHCP reservation.

**Build note (P8-16, 2026-10-26).** `packages/helios_parsing/validator.py` is
`validator-v9`. The string length is unchanged, so `method_version` stays 126 characters and
there is no migration.
- **g1f.** In pass 1, a row whose claimed block does not print its name, with no print at or
  after the cursor, grounds on the print nearest its claim (the cursor when nothing is
  claimed), ties going to the print above, instead of the page's first print.
- **G3.** `grounding_tokens` is a block's `block_tokens` together with the tokens of its text
  with a lowercase letter glued to an uppercase one split. It is used for name grounding in
  [5] only. `output.split_listed` keeps `block_tokens`, so the repairs are unchanged.
- **Checks.**
  - Three tests: a glued name (Paloma); a dish printed twice, its claim under the second
    print and the cursor past both (Vivo); a tie.
  - 4 of 4 mutations killed: G3 off, the first-print fallback back, nearest the cursor, the
    tie flipped.
  - On all 793 dev pages and the 863 corpus page texts, the build's verdicts equal P8-15's
    prototype (`g1f+g3` patched onto `validator-v8`) row for row.
- **Re-measured on dev with labels-v10** (793 pages, `validator-v8` → `validator-v9`;
  page-clustered 95 % intervals):

  | | v8 | v9 |
  |---|---|---|
  | Gold-row FR | 0.0973 [0.074, 0.125] | **0.0958** [0.073, 0.124]; change −0.0015 [−0.0039, −0.0001] |
  | Corruption catch | 0.9951 [0.992, 0.997] | 0.9950 [0.992, 0.997] |
  | Price accuracy | 0.9781 | 0.9781 |
  | Usable prices | 0.8139 | 0.8143; change +0.0004 [+0.0000, +0.0011] |
  | Item recall | 0.9117 | 0.9117; gold items +51, none lost |

  - **Pages worse on catch or price accuracy.** Two:
    - `2f8e9a845c2b` (`html_inline`, run-together text): swapped-price catch falls 17/20 →
      15/20, because G3 lets names ground in glued text;
    - `49b6a15a40ee`: one more wrong-price accept.
  - **The P8-14 set alone:** FR 0.1585 → 0.1451, and 43 more gold items.
  - **Corpus:** 46 page texts change (722 rows), and no price Evidence lies off its blocks.
  - **Amendment 29 Q6 stage bars:** all pass under v9.
    - On P8-13's 746 pages: 9 gated pages lose a gold item, as under v8. Section exact is
      0.7679, against resolve-v3's 0.7620.
    - On the P8-14 set: 2 of 37 gated pages lose a gold item.
    - The bars' figures move by at most 0.0005 from v8's.
  - **Invariance suite (ADR-0017 item 1) fails.** On the 218 tuning pages, v9 adds flips on 8
    page/style pairs, all in the two claim styles: flips go from 6,638 to 6,658.
    - g1f adds 9 per claim style on two pages (`8db407b1e8ef` 8, `4b9d6bb201da` 1). Its own
      choice is right: the row moved off its name takes its own print, not the page's first.
      But the suite orders rows by section, so a lunch and a dinner menu interleave. The
      cursor then sits in the other menu, and the unchanged cursor rule sends later rows
      there too.
    - G3 adds 3 per claim style on two pages (`49b6a15a40ee`, `00f349e12f5b`). A description
      glued to the next dish's name ("…masala sauceKaraikudi Nattu Kozhi Varuval") becomes an
      earlier print of that dish, and a row whose claim misses lands there and binds the
      previous dish's price. It is also the one new wrong accept on dev.
    - A narrower G3, applied only to the claimed block, was measured too: it adds more flips
      (9 pairs, 6,638 → 6,685), so it is not offered.
    - The ADR-0017 rule is that a change adding flips is rejected. The owner's acceptance
      came before the suite was run, so it was put to the owner (Q-A30 in the build record):
      (a) accept the 8 pairs as claim-style invariance debt, (b) build g1f alone, or (c) hold.
    - **Owner ruling (2026-10-26): (a).** The 8 pairs (+20 flips; `p816-v9.json` is the new
      baseline map) are recorded as invariance debt next to the claim styles' existing 637.
      A later change is measured against v9's map.
- **Applied 2026-10-26** (owner go-ahead, after #128 merged):
  - `helios_laptop` re-interpreted from saved answers: 1,597 pages, 0 failed, 0 model calls;
    prices 70,885 → 70,915.
  - Gold refreshed (effective 2026-10-26T23:40Z): `current_menu` 59,860 → 59,894 rows.
  - The Pi (firsthelios.com) restored from that database, with backend `bcd8cd6`.
  - Record: [2026-10-26-p8-16-validator-v10.md](../reviews/2026-10-26-p8-16-validator-v10.md),
    section 3.

**Why.** The owner queued it after P8-14 (Amendment 29, Q4 of the P8-14 rulings and Q7's first
follow-on), with the Q2 gap folded in. The cases, traced on stored pages and saved answers:
- **Vivo, a second printed dish collapses onto the first.** "Chipotle Enchiladas" is printed
  twice (b0136 under Mains, b0286 under Specialty Enchiladas).
  - The chunk-13 row claims b0287, the line under its print, which does not print the name.
  - Pass 1's cursor rule then finds no print at or after the cursor and falls back to the
    page's *first* print, b0136.
  - The second dish is lost, and its row collides with the first.
- **The P8-14 dedupe-collapse pages.** Each has its own cause:
  - **Vegetarian Antipasto** (`ad991b67d739`): the copy claims b0522 ("Pasta Entrees"), two
    blocks past its print b0520. The cursor rule sends it to b0922, the same dish in a later
    menu.
  - **Paloma** (`79f66c5309ed`): the model's claim b0041 is right. But the segmenter glued the
    name to its description ("PalomaHerredura Tequila, …"), so the block doesn't ground
    "paloma". The row falls through to the bar menu's print, b0256.
- **The Q2 gap, price printed before its name** (Dahlia Café `d57b5b288970`). Each price is
  printed in the block just before its dish's name.
  - The validator's after-name scan binds the next dish's price.
  - The model reads the page the same way: it gives "Kettle Chips" the next dish's $14.04
    (gold $5.50), and it names section headings as priced items ("BURGERS $15.01").
  - On the P8-14 set, this page holds 145 of the 320 gold-row false rejects and 105 of the
    accepted wrong-price rows.

### Options (all deterministic and generic; no per-site rule, no model change)

- **G1, nearest print.** A row whose claimed block does not print its name grounds on a print
  near its claim.
  - (g1) Use v9's claim-drift rule, `output.printed_name_block`, before the cursor rule.
  - (g1u) Use the nearest print anywhere.
  - **(g1f) Replace only the cursor rule's first-print fallback.** When the claim does not
    ground and no print lies at or after the cursor, take the print nearest the claim, not
    the page's first. (Recommended.)
- **G2, price before name.** A page-level layout vote at section ends.
  - In a name / description / price layout, a section's last dish is followed by a price,
    and its first dish has none before it. A price-first layout is the other way round.
  - The vote's item names are the blocks in the page's item-name style, the (tag, path) most
    of the rows' name blocks share. The model's rows can't be used directly: they include
    section headings.
  - On a gated page, a row binds the price-only run just above its name, and an acceptance on
    a price after the name becomes `price_not_grounded`.
- **G3, glued words.** A block's grounding tokens also split a lowercase letter glued to an
  uppercase one ("PalomaHerredura" → "Paloma Herredura"). It is a union rule, as v6's
  glued-integer split ("Cod Cakes16") is: it can only add a grounding. (Recommended.)

### Measured (dev, not §8: P8-13's 746 pages plus the P8-14 set, 793 menu pages)

Everything below runs through the production `llm_stream` with saved answers (so [5d], the
re-judge, duplicate removal and [5b] all see the change). Gold-row FR and catch come from the
harness's `corruption_eval`, run per page with seed 20261026. Gold-item counts are against
resolve-v4 with the narrowed rule "same".

| 793 pages | Recall | Price acc | Usable | Gold-row FR | Catch | Gold items | Rows re-claimed |
|---|---|---|---|---|---|---|---|
| resolve-v4 | 0.9061 | 0.9785 | 0.8064 | 0.1008 | 0.9950 | | |
| g1 | 0.9055 | 0.9784 | 0.8055 | 0.1006 | 0.9951 | +6 −15 | 16,079 |
| g1u | 0.9055 | 0.9784 | 0.8052 | 0.1006 | 0.9951 | +9 −20 | 18,028 |
| **g1f** | 0.9061 | 0.9785 | 0.8066 | 0.1007 | 0.9951 | **+2 −0** | 79 |
| G2 | 0.9060 | **0.9832** | 0.8073 | **0.0961** | 0.9948 | +0 −1 | |
| **G3** | 0.9061 | 0.9784 | 0.8067 | 0.0994 | 0.9947 | **+49 −0** | |
| **g1f + G3** (proposed) | 0.9061 | 0.9784 | 0.8068 | 0.0993 | 0.9949 | **+51 −0** | 77 |
| g1 + G2 + G3 | 0.9055 | 0.9831 | 0.8068 | 0.0945 | 0.9947 | +55 −16 | 16,011 |

- **On the P8-14 set** (47 menu pages; resolve-v4 → G2 + G3 + g1):
  - price accuracy 0.872 → 0.924;
  - gold-row FR 0.156 → 0.085 (page-clustered [0.047, 0.129]);
  - usable prices 0.759 → 0.766;
  - catch 1.000.

  Without Dahlia, G3 alone moves FR 0.094 → 0.079.
- **Dahlia under G2:** wrong-price accepts 105 → 4, gold-row FR 145 → 26 of 180. Usable
  prices only go 18 → 25: the model's amounts are wrong too, and the validator can only
  downgrade them, not correct them.
- **Vivo:** g1, g1u and g1f all restore the second Chipotle Enchiladas on b0286 (price on
  b0287).
  - Vegetarian Antipasto: g1 re-grounds the copy on b0520.
  - Paloma: G3 grounds the claim on b0041 (that page's gold-row FR 12 → 11 of 12; the page's
    other rejects are unrelated).
- **Corpus sizing** (863 page texts):
  - g1f changes 36 page texts (85 rows); g1 changes 187 (16,740 rows re-claimed).
  - G3 changes 12 page texts; g1f + G3 together change 46.
  - **G2 gates 8 page texts. At least 2 of them are false gates** (spot-checked):
    - Mom's Special Cooking and Wen's Café print name → price. 17 and 24 rows change.
    - On Wen's, each dish is printed twice (a list block and a heading). The item-name style
      picks the list blocks, so the dish headings become section bounds, and one-dish
      "sections" vote price-first.
    - Neither page is labelled, so the dev table can't see it.
- **Versioning.** G1 and G3 change the validator: `validator-v8` → `validator-v9`. The string
  length is unchanged, so `method_version` stays 126 characters and there is no migration.
  Applying it means one more saved-answer re-interpretation and a Gold refresh.

### Proposal

1. **Build G3 + g1f as validator-v9.** Measured together on dev (793 pages):
   - +51 gold items with none lost; it changes 53 pages, and 46 corpus page texts;
   - gold-row FR 0.1008 → 0.0993, catch 0.9950 → 0.9949 (11,487 / 11,546);
   - price accuracy 0.9785 → 0.9784, usable prices 0.8064 → 0.8068.

   It fixes Vivo and Paloma, but not Vegetarian Antipasto (that needs the broader g1).
2. **G2 is not ready to build.** It removes most of the Q2 gap on Dahlia, but its section bounds
   false-gate normal pages. How to bound sections is a design fork for the owner (Q2 below).
3. **Re-check before applying:** dev in full (the FR and catch bars move with the validator),
   and the §8 held-out at the next crawl, together with resolve-v4's.

### Owner questions

- **Q1. Build G3 + g1f as validator-v9?** Recommended. Or G3 alone, or neither.
- **Q2. G2's section bounds.** Which, if any, should be prototyped next?
  - (a) Move G2 after the validator, where the HTML is, and bound sections with [5c]'s
    DOM section headings. The gold-row FR and catch harness would then need the page HTML,
    which is a harness change.
  - (b) Keep it in the validator, and bound sections only by headings in a style that never
    precedes a price-bearing run of its own. Cheaper, but still a structural guess.
  - (c) Leave the price-first layout as a known gap and accept the data loss on those pages.
    Dahlia is 1 page text in 863.
- **Q3. G1 scope.** g1f only (recommended)? The broader g1 / g1u also fixes Antipasto but
  loses 15 to 20 dev gold items.

## Amendment 31 (2026-10-26, proposed): the validator's price scan continues past the dish's own headings

**Status: Proposed 2026-10-26 (P8-16). Accepted 2026-10-26 by the owner, with the rulings below. Built as `validator-v10` (build note below).**
Record: [2026-10-26-p8-16-amendments-31-32.md](../reviews/2026-10-26-p8-16-amendments-31-32.md),
section 1. Prototype: `var/p8-16/proto/validator_f1.py` (untracked; `validator-v9`, PR #128,
plus the edits marked "(F1)"). Build record:
[2026-10-26-p8-16-validator-v10.md](../reviews/2026-10-26-p8-16-validator-v10.md).

**Owner rulings (2026-10-26), as recommended:**
- **Q1.** Build F1's heading part as `validator-v10`. The row part stays dropped.
- **Q2.** First try one more condition, the row's variant words left out when the heading is
  compared with the row's name. Keep it if it removes the two added invariance pairs
  without losing the gains; otherwise accept the two pairs as invariance debt.
- **Q3.** The bilingual-twin losses go to the queued English-name work (owner Q6 on P8-x);
  they don't block F1.

**Build note (P8-16, 2026-10-26).** `packages/helios_parsing/validator.py` is
`validator-v10`.
- **The rule.** `_price_run` takes the row's name. Before a run starts, a price-less heading
  for which `own_heading(block, name)` holds doesn't end the scan. `own_heading` is true for:
  - the name's words again, item codes aside;
  - an item code alone (`_ITEM_CODE`, which requires a digit);
  - a line of at most `OWN_HEADING_CHARS` (40) characters in the other script.
- **Version and storage.** `method_version` grows from 126 to 127 characters, inside the
  column's 128, so there is no migration, but the next version bump that lengthens it must
  check this. The JSON-LD stream's version names the validator too.
- **Checks.**
  - Two tests: the dish's own headings are passed; a section heading, a heading adding words
    to the name, and a long other-script heading still end the scan.
  - 6 of 6 mutations killed. A seventh, the separate digit check, survived because the
    pattern already requires a digit, so that check was removed.
  - The build's verdicts equal the prototype (`f1h` on `validator-v9`) on all 1,885 page
    texts.
- **Q2's condition, tested before the build.** It can't remove the two pairs. In the normal
  output style F1 now accepts rows such as "Kyay Oh Soup ( Chicken )" at 10.99. In the
  variant-in-name style ("Kyay Oh Soup Chicken") the name grounds on another block before
  the scan is reached, as it did under v9. So per Q2 the two pairs are recorded as
  invariance debt.
- **Measured on dev with labels-v10.1** (793 pages, against `validator-v9`):
  - usable prices 0.8132 → **0.8201** (+0.0069 [+0.0026, +0.0127]);
  - gold-row FR 0.0960 → **0.0880**;
  - catch 0.9949 → 0.9949;
  - price accuracy 0.9779 → 0.9785;
  - gold items −13, through [5d] as in the proposal.
  - Every Amendment 29 Q6 stage bar passes on both sets.
  - Invariance: 6,658 → 6,639 flips, with the two debt pairs.
- **Applied 2026-10-27** (owner go-ahead, after #131 merged):
  - `helios_laptop` re-interpreted from saved answers: 1,597 pages, 0 failed, 0 model calls;
    prices written 70,915 → 71,207.
  - Gold refreshed (effective 2026-10-27T01:10Z): `current_menu` 59,894 → 60,119 rows, 9,404
    sections; the price index has 352 rows.
  - The Pi (firsthelios.com) restored from that database, with backend `08bb684`, after 179 s of
    downtime. Every public endpoint returns 200.
  - Backups: `var/laptop-run/helios_laptop-2026-10-26-pre-v10.dump` (laptop) and
    `~/helios-backups/firsthelios-20261027-v10-bcd8cd6/` (Pi).

**Why.** The P8-x gap audit's fix F1 (owner Q1 and Q3: first, and in its own amendment).
- [5]'s price scan (`_price_run`) ends at the first price-less heading after a dish's name.
- On pages that print each dish's name again as a heading, the scan stops before the dish's
  own price. Some print the name again, some print it in a second language, some print an
  item code: `83b9a566697a` prints `li` name, `li` 中文, `h3` name, `h3` 中文, then the price;
  cards print "C2" between title and price.
- The audit sized it at 290 lost prices: heading 204, emitted description row 49, other-language
  row 37. On gold rows, 268 rejects (1.1 % of gold prices) are heading stops.

### Proposal (`validator-v10`, on top of `validator-v9`)

Before a price run starts, the scan does not end at a price-less heading that is one of:
- **the row's own name again**: its words, item codes aside, are all the row's name words
  ("Kung Pao Chicken", "C2 Crispy Rice");
- **only an item code**: up to three letters, then one to three digits ("C2", "M2", "#12",
  "N1:");
- **a short line (≤ 40 characters) in the other script** from the row's name (CJK against
  Latin): the dish's bilingual twin heading.

Every other heading still ends the scan, a section heading included. Nothing else in [5]
changes.

**Dropped from F1: the row part.** Scanning past an unpriced emitted description row or an
other-language row changes no dev page and one corpus text (two rows). Two things explain it:
- `validator-v6`'s `_NOT_ITEM` already lets description sentences through;
- the other-language rows the audit counted are priced twins, which are no scan stop to
  skip.

### Measured (dev, not §8; labels-v10; against `validator-v9`)

793 dev pages, page-clustered 95 %; corruption seed 20261026:

| | v9 | v9 + F1 | Change |
|---|---|---|---|
| Usable prices | 0.8143 | **0.8212** | +0.0069 [+0.0026, +0.0126]; gold prices +192 −28 |
| Gold-row FR | 0.0958 | **0.0878** [0.067, 0.113] | −0.0080 [−0.0199, −0.0002] |
| Corruption catch | 0.9950 | 0.9950 [0.992, 0.997] | 11,494 / 11,552 |
| Price accuracy | 0.9781 | 0.9787 | wrong-price accepts 453 → 444 |
| Item recall | 0.9117 | 0.9112 | gold items +0 −13 |

- **Where it lands.** 83b9a566697a's gold-row FR goes 122 → 10 (+59 prices) and the item-code
  cards on 05273895b4e2 go 88 → 54 (+23); then fde6a5187560 +15 and 2aa22b5d5dc5 +13. The P8-14
  set gains 12 prices with FR unchanged.
- **Pages worse on catch or price accuracy** (two):
  - held:7f7d7c98ba45: one new wrong accept (a comma-joined row of four cocktail names at
    4.00);
  - ab61da9d75b5: 34 / 34 → 30 / 30 caught (fewer trials drawn, none missed).
- **The 28 lost gold prices.** 16 are on dc55a13f2101: the model emits each dish's Chinese
  line as its own priced row, and F1 lets that twin bind the dish's price first, so the English
  row is downgraded `price_bound_to_other_item`. That belongs with the owner's Q6 ruling
  (bilingual dishes carry their English name; queued).
- **The 13 lost gold items** come through [5d], not [5]. F1 changes the first judge's
  verdicts, which changes the template:
  - held:c1ebd4d32417 (10): the page's gate fails, agreement 0.67 under 0.8, so [5d]'s
    additions there go (they were bare-integer rows);
  - 4723ed747fe3 (2) and 113e4327a7dd (1): RE-NAME / DROP interplay.
- **Amendment 29 Q6 stage bars: all pass** on P8-13's 746 pages and on the P8-14 set. Gated
  pages losing a gold item: 9 of 221 and 2 of 37.
- **Invariance suite** (218 tuning pages, against `validator-v9`):
  - total flips fall 6,658 → 6,639;
  - but one page adds two pairs: 05273895b4e2, `variant_in_name` 16 → 18 in both forms. A
    variant written into the name changes the name's words, so the item-code heading no
    longer reads as the row's own name.
  - ADR-0017 rejects any added pair, so this needs the owner's ruling (Q2 below).
- **Corpus** (863 page texts): 40 change (680 rows). Accepts +267, distinct price spans +267,
  rows −48 ([5d] and duplicate removal), and no price Evidence lies off its blocks.

### Owner questions

- **Q1. Build F1 (heading part only) as `validator-v10`?** *Recommended.* +164 net gold prices
  and FR −0.008 on dev, with catch flat, every stage bar passing, and fewer flips in total.
- **Q2. The two added invariance pairs** (05273895b4e2, variant in the name). Choose one:
  - (a) Accept them as debt, since total flips fall by 19 (*recommended*);
  - (b) also strip the row's variant words before comparing with the heading. That is one
    more condition, to be measured before the build.
- **Q3. The bilingual-twin losses** (dc55a13f2101, 16 prices). Leave them to the queued Q6
  work (English names, twin rows merged), or block F1 until then? *Recommended: leave them
  to Q6.*

## Amendment 32 (2026-10-26, proposed): a shared section price as a [5b]-style resolver

**Status: Proposed 2026-10-26 (P8-16). Not adopted (owner, 2026-10-26): dropped for now, as recommended.**

**Owner rulings (2026-10-26):** Q1, do not build it; F3 stays recorded as measured. Q2,
no limit moves now. Shared section prices are revisited only after F2 and F4 ([5d]) and the
English naming land, and then with section bounds from [5c]'s page structure, together with
G2's revisit (Amendment 30). Q3 falls away with Q1.
Record: [2026-10-26-p8-16-amendments-31-32.md](../reviews/2026-10-26-p8-16-amendments-31-32.md),
section 2. Prototype: `var/p8-16/proto/shared32.py` (untracked).

**Why.** The P8-x gap audit's fix F3, approved by the owner (Q2) with exactly these limits:
- a dish takes a price printed once for its own section, with its Evidence on that line;
- only when the price is printed in the section's heading or on the line right under it, and
  no dish in the section prints its own price;
- a choice list ("Tofu or Paneer $17 | Chicken $17 | Lamb $20") gives one variant per choice;
- charts printed elsewhere, "starting at" prices, add-on surcharges and menu-level prices stay
  out;
- it is built as a [5b]-style resolver, so FR and catch apply.

The audit counted 411 lost prices (407 on labels-v10) whose amount is printed in a line above
the dish with another dish in between.

### The prototype

Tagged `resolved_section_price`:
- **Accept pass, inside [5b]** (`resolve.resolve`, so the gold-row FR and catch see it): a row
  kept unpriced for a no-match reason whose amount, and variant on a choice list, is the
  section's printed price is accepted, citing it.
- **Fill pass, after duplicate removal on the llm stream:** a dish emitted unpriced takes the
  section's price. Under a choice list it becomes one row per choice, the choice's label as its
  variant.

The section:
- its heading is the nearest marked heading above the dish that names no item;
- it ends at the next heading of its level;
- it holds no sub-section;
- its price line is the heading or the line right under it, and nothing else in it prints a
  price;
- the line is no add-on or surcharge, no "starting at" or "from" price, and no menu-level
  title.

Three revisions were measured, each a generic correction to the false fills its predecessor
showed on dev:
- **r1** applied the limits as stated. It also found a section heading as the line printing
  the model's own section name, because many pages head sections with plain paragraphs.
- **r2** added: marked prices only (no bare numbers: "Available September 22", "Choice of
  2"); a heading that names a kept dish heads no section; a dish printed elsewhere with its
  own price is skipped; package, combo and per-person lines count as menu-level ("Pick 2
  Lunch – $13.95", "Premium Package – $19/person/hour").
- **r3** stopped a dish's own heading from ending its section.

### Measured (dev, not §8; labels-v10; against `validator-v9`)

| 793 dev pages | Usable change | Gold prices | FR change | Catch | Wrong-price accepts |
|---|---|---|---|---|---|
| r1 | +0.0010 [+0.0002, +0.0022] | +25 −0 | −0.0039 [−0.0070, −0.0014] | 0.9949 | 453 → **466** |
| r2 | +0.0002 [+0.0000, +0.0006] | +5 −0 | −0.0021 [−0.0040, −0.0007] | 0.9950 | 453 → 454 |
| r3 | +0.0000 [+0.0000, +0.0001] | +1 −0 (−1 gold item) | −0.0023 [−0.0042, −0.0008] | 0.9951 | 453 → 453 |

- **False fills, the owner's kinds** (`var/p8-16/measure/fills32*.txt`):
  - **the dish prints its own price elsewhere:** r1 13, for example "Pick 2 Lunch – $13.95"
    over a Cuban whose own price is $18.95; r2 1 and r3 1 ("17.L House Fried Rice", whose own
    price, 12.25, is printed after its bilingual headings);
  - **a "starting at" line:** none in any revision; the line filter held;
  - **a line outside the section:** none once r2 stops dish headings heading sections. In r1,
    83b9a566697a's dish headings were read as sections (4 wrong fills).
  - **menu-level and package prices:** r1 filled "Pick 2 Lunch – $13.95" over 15 dishes and
    "Premium Package – $19/person/hour" over 6. r2 and r3 still fill "$16.99* Big Yummm
    Deal" over 2 burgers: a word list can't close this kind.
  - Most accepts and fills land on items no label covers (r3: 32 of 33). Examples are
    unlabelled cocktails under "$7 Cocktails" and wing flavours under "Jumbo Wings 5 for
    $9.95". They read as right, but they can't be scored.
- **Why it reaches so little.** Of 676 unpriced kept rows whose gold item is priced, r3 fills
  2. The rest stop at:
  - **no price on the heading or the line right under it: 320** (the owner's limit);
  - another heading between section and dish: 168;
  - a sub-section: 99;
  - another price in the section: 35;
  - no section heading: 23;
  - the rest: 29.

  The audit's 407 counted a shared price printed anywhere above the dish.
- **Invariance suite** (r3, against `validator-v9`): 4 added page/style pairs, 6,658 → 6,686
  flips, in `section_none` and `section_generic`. Finding the heading from the model's
  section label makes the decision depend on the model's output style, which ADR-0017 item 1
  forbids. Only marked or DOM headings (`MODEL_SECTIONS = False`) are admissible. That variant
  matched r1 in reach on dev (s32h: same +25, FR −0.0031).
- **Corpus** (r3): 9 page texts change (67 rows); no price Evidence off its blocks.

### Owner questions

- **Q1. Build it?** Under Q2's limits it delivers about nothing on dev. r1 found +25 gold
  prices only by also accepting 13 wrong prices, and the guards that remove those remove the
  gain. *Recommended: do not build now; record F3 as measured.*
- **Q2. If shared prices are still wanted**, which limit should move?
  - (a) The price line may be any line between the heading and the section's first dish (not
    only the line right under the heading). This reaches part of the 320.
  - (b) Section bounds from [5c]'s DOM sections, which the owner tied to G2's revisit
    (Amendment 30), instead of marked headings.
  - (c) Neither: leave F3 to the model and prompt side, which is the owner's GPU/LLM decision.

  This is a design fork; each needs its own measurement.
- **Q3. Unscorable fills.** Most fills land on items no label covers. Label those pages'
  missing items in a later revision before judging any widened variant?

## Amendment 33 (2026-10-28, proposed): the [5d] record rewrite on the page-structure model (`resolve-v5`)

**Status: Proposed 2026-10-28 (P8-21). Accepted 2026-10-30 by the owner, with the rulings below.
`resolve-v5` is built with R2 (Q1 (b)) and merged (#138). Applied to `helios_laptop` 2026-10-31
(3,056 pages re-interpreted, 0 model calls; Gold 104,764 `current_menu` rows; Pi +4.0 ms/page). The
Pi's restore waits for the owner's go.**
Record: [2026-10-28-p8-21-page-structure.md](../reviews/2026-10-28-p8-21-page-structure.md).
Architecture: [ADR-0021](./0021-page-structure-model-and-signal-hierarchy.md) D1 and D4 step 1
(Q1–Q8 accepted 2026-10-26).

**Owner rulings (2026-10-30, "accept all recommendations"):**
- **Q1 (b).** Build R2: a record's label lines move onto its title only when the record prints
  a choice line. It is built (`page_template._choice_card`), and the build equals the measured
  patch (record section 3).
- **Q2 (a).** The section bar's one page (held:12bf8e6a3406) is a known [5c]-gate interaction,
  revisited in ADR-0021 step 2. It doesn't block v5.
- **Q3.** All-or-nothing per record and no-harm stay part of `resolve-v5`.
- **Q5.** Unlabelled multiple prices stay out (Amendment 19 2(b)).
- **Q4 and Q6 (2026-10-30, after recommendations were given; "accept all"):**
  - **Q4.** No separate amendment for downgraded rows. They come into reach through
    ADR-0021 step 3 (a record-bounded price region in [5]/[5b], measured on FR and catch),
    not through a [5d] rewrite.
  - **Q6.** Apply after #138 merges, in `resolve-v4`'s sequence:
    1. dump `helios_laptop`;
    2. re-interpret every published `llm` page from saved answers (0 model calls);
    3. refresh Gold;
    4. a speed-only timing on the Pi.
  - The Pi's data refresh was to be combined with P8-20's, but P8-20 applied its own on
    2026-10-31 before #138 merged, so `resolve-v5` gets its own Pi restore. The §8 held-out
    re-test owed for `resolve-v4` and `validator-v9`/`v10` is drawn next session from the page
    texts P8-20's re-collection produced, and covers `resolve-v5` too.

**Why.** ADR-0021's step 1: one record notion for [5d], and one rule family for F2 (RE-NAME),
F4 (ATTACH) and choice lines (santopatio's Nachos).

### What was built

- **`packages/helios_parsing/page_structure.py`** (D1). It's stdlib and built from the
  existing re-parse and the first judge's seeds; nothing is stored.
  - Per block: node chain, class signature, tag path, one text shape.
  - Per page:
    - the title signature (≥ 3 split seeds, ≥ 0.8 of its seed-role blocks titles);
    - the record depth;
    - the price slot (the main price signature);
    - records (a title's container holding no second title).
- **The record rewrite** (`page_template`, before [5d]'s per-row actions). On a gated page, an
  accepted row named and priced inside another title's record moves onto the title, when the
  record holds the page's price slot or the page is slotted (Q3 (a)):
  - choice and label lines become the title's variants, one per choice (Q4); their same-block
    seeds stop counting as an item pattern;
  - description and option rows take the title's name; a short non-description line keeps
    its own (Q8);
  - unclaimed labelled prices in the record are attached to the title; add-ons never.
- **Two safety rules added in the build** (not in ADR-0021):
  - all or nothing per record;
  - no harm: a rewritten row the re-judge no longer accepts goes back to the model's row.
- ADD skips only records the rewrite moved rows onto.
- `resolve-v4` → `resolve-v5`; `method_version` stays 127 of 128 characters.

### Measured (dev, labels-v10.2, 331 scorable item-labelled pages; not §8)

| | v5 as ruled | v5 + R2 (choice-line records only) |
|---|---|---|
| Usable prices | +0.0018 [+0.0004, +0.0031] | **+0.0025 [+0.0015, +0.0037]** |
| Gold prices / items | +63 −21 / +8 −18 | **+62 −2 / +8 −0** |
| Kept-item precision | +0.0012 | +0.0014 |
| Price accuracy, FR, catch | unchanged | unchanged |
| Stage bars failing | item recall; section exact | section exact (0.7607 / 0.7617) |
| Gated pages losing a gold item | 2 / 258 | 0 / 258 |
| Invariance (through `llm_stream`) | flips 6,653 → 6,606; 0 added pairs | 6,607; 0 added pairs |
| Corpus (863 texts) | 72 change; accepts +48; 0 Evidence off its blocks | 68 change; accepts +46; 0 off |

- **Q3 (a) can't tell a heading card from a dish card with options.** Both lack the page's
  price slot. As ruled, it anchors santopatio's "A La Carte" taco lists (16 gold items), a
  sauces card and catering trays.
  - **R2** additionally requires a choice line in the record, the text half of Q3 (b). It
    removes those losses and keeps Nachos and Quesadilla.
- **The section bar fails on one page in both variants.** On held:12bf8e6a3406 a correct
  rename tips [5c]'s 90 % gate, and 31 → 13 items keep an exact section. Every other changed
  page gains (R2: +7 on 11 pages).
- **Chunk boundaries** split 2.2 % of records, worth about 28 dev gold prices; chunking is
  unchanged.

### Owner questions

- **Q1. The heading-card guard.** Choose one:
  - (a) Keep Q3 (a) as ruled. Two stage bars fail, and 18 gold items are lost.
  - (b) **Add R2:** label lines move onto the title only when the record holds a choice line
    ("/", "or", ","). Only the section bar fails, and no item is lost. *Recommended.*
  - (c) Drop the label-line trigger; keep RE-NAME and ATTACH only.
- **Q2. The section bar's one page.** It's a correct item gain that tips [5c]'s gate. Choose one:
  - (a) Accept it as a known [5c]-gate interaction, to be revisited in ADR-0021 step 2 ([5c]
    on the same records). *Recommended.*
  - (b) Hold v5 until step 2 is built and measured with it.
- **Q3. The two safety rules** (all-or-nothing, no-harm) added in the build. Keep them as part
  of `resolve-v5`? *Recommended.*
- **Q4. Reach.** v5 moves accepted rows only (+62 dev gold prices, against P8-17's 909-amount
  headroom). Should a later amendment also consider downgraded rows, re-judged with the
  record's slot price? Not built or measured.
- **Q5. Unlabelled multiple prices** ("11.00 | 15.50" in a record's slot). They stay out, since
  a variant is never inferred (Amendment 19 2(b)). Confirm, or label the policy for them?
- **Q6. Apply.** After Q1–Q3, approve the usual sequence?
  - re-interpret `helios_laptop` from saved answers, then refresh Gold;
  - a speed-only timing on the Pi;
  - the §8 held-out re-test at the next crawl's new page texts, as for `resolve-v4`.

**Applied (2026-10-31).**
- `helios_laptop` re-interpreted: 3,056 pages, 0 model calls.
- Gold refreshed with `main` at ab674e5 (#139's cross-scope dedupe included): `current_menu`
  103,563 → **103,683** rows (items −74, variants +194).
  An earlier refresh on 66d4bba, before #139 merged, read 104,764 because P8-20's dedupe was
  missing. It was redone.
- The Pi restored from that database, after coordinating with P8-20, which had already
  deployed backend ab674e5. Downtime was 265 s and `pg_restore` wrote no errors. Every public
  endpoint returns 200 on firsthelios.com and www.
- Backups: laptop `var/laptop-run/helios_laptop-2026-10-31-pre-p8-21.dump`; Pi
  `~/helios-backups/firsthelios-20261031-p8-21/` (pre-dump sha256 `f4e1d27a…`, laptop dump
  `8c10e89c…`).

**A gap found in the applied data: one stored row per printed price.** `menu_shape` keeps one
price row per printed price span per item (`_Item.seen`). A choice line's variants all cite
the line's one printed price, so **only the first choice is stored**. Santopatio's Nachos
are stored as Chicken 14.99, Birria 15.99, Shrimp 16.99; Bistec, Pastor, Beef Fajita and Combo
are not.
- Every printed price is still stored once, so prices and the usable-price measurement are
  right. The harness scores verdicts, not stored shapes, so it didn't see this.
- Fixing it changes storage, so it needs a decision: Q7 below.
- **Q7 (decided 2026-10-31: (b), see [Amendment 34](#amendment-34-2026-10-31-one-stored-variant-per-choice-of-one-printed-price-resolve-v6)).** Choose one:
  - (a) keep one row per printed price, with the first choice's label (today);
  - (b) store one variant per choice, each citing the same printed span. The variant list is
    then complete, but the price index's venue median counts that price once per choice;
  - (c) one row per printed price, labelled with every choice ("Chicken / Bistec / Pastor"),
    which is what labels-v10.1 had.

  *Recommended: (b), with the price index counting each printed price span once.* (b) is
  the owner's Q4 ruling as stored data. Counting each span once keeps the median unchanged.
  It is a `menu_shape` plus Gold change: its own small amendment, with a re-interpretation
  and a Gold refresh.

## Amendment 34 (2026-10-31): one stored variant per choice of one printed price (`resolve-v6`)

**Status: Accepted 2026-10-31 under the owner's delegation** ("answer questions on your own
and work autonomously"). It answers Amendment 33 Q7 with (b), as recommended. Built (PR, not
merged). Not applied to `helios_laptop` or the Pi: that waits for the merge and the owner's
go-ahead.

**The gap (Amendment 33).** `menu_shape` kept one stored price row per printed price span per
item (`_Item.seen`). A choice line's variants all cite the line's one printed price, so only the
first choice was stored. Santopatio's Nachos were stored as Chicken 14.99, Birria 15.99 and
Shrimp 16.99; Bistec, Pastor, Beef Fajita and Combo were missing.

**Decision.**
1. **Storage** (`packages/helios_parsing/menu_shape.py`). A printed price span prices an item
   once without a label, or once per distinct variant label. "Chicken, Bistec or Pastor 14.99"
   is three variants, each citing the line's one span.
   - A span that priced the item without a label prices no labelled variant, and the other
     way round. The validator already downgrades such a row (`price_belongs_to_other_variant`);
     `shape` holds the rule anyway.
   - Verdicts don't change, so the harness and every §8 number are the same.
2. **The price index counts each printed span once** ([ADR-0007 Amendment 4](./0007-gold-price-index-projection.md#amendment-4-2026-10-31-a-printed-price-counts-once-in-a-venues-median)).
   A venue's median is over its printed prices, so a choice line weighs one price, as before
   this amendment.
3. **Version.** `RESOLVER_VERSION` becomes `resolve-v6`, the post-validator component that
   already names [5b]–[5d] and duplicate removal. The method version stays 127 characters.
   Every `llm` page becomes due for re-interpretation from saved answers (no model call).
   - The JSON-LD stream is shaped by the same code and rewritten with its page. Its own
     method version (`jsonld-v1;…`) has no resolver part and doesn't change, as for v5's
     duplicate removal.

**For the read API and the frontend** (owned by another session; no route changes here):
- A venue's menu read now lists every choice as its own variant, each with the shared price
  and the same price Evidence.
- `/v1/price-index/area` items still walk `priced_count` rows (ADR-0020's invariant), since
  `priced_count` counts rows. A choice line is now several rows at one price.
- Medians count each printed price once. A client that computes its own statistics from the
  items walk should group rows by price Evidence to match.

**Measured** (a scratch copy of `helios_laptop`, `helios_p821q7_test`, 2026-10-31; the live
database was not written):
- **Copy.** A fresh `pg_dump` of `helios_laptop` (alembic `13081a087231`, 103,683
  `current_menu` rows), restored as `helios_p821q7_test`.
- **Re-interpretation** from saved answers (`var/q7/q7_reinterp.py` in the PR worktree,
  untracked):
  - 3,056 due pages, all extracted, **0 model calls**, 0 failures, 3,096 pages/h;
  - items written 205,027 (unchanged from resolve-v5's apply);
  - prices written **127,273**, against v5's 127,252: **+21**;
  - empty 59, flagged 541 and JSON-LD pages 348 (all unchanged).
- **Gold refresh** (branch code):
  - `current_menu` 103,683 → **103,697** rows: items 95,877 (unchanged), variants 7,806 →
    7,820;
  - price index 416 rows, same keys, 981 placed;
  - 12 rows change, 4 of them in their statistics. The citywide `all` row's median goes
    1025 → **1016**, `priced_count` 56,678 → 56,690, and p25/p75/min/max are unchanged.
- **Where the median moves.** Rows citing one span: 43 groups, 46 extra rows. That is the 32
  pre-existing groups (one dish under two sections, `llm` + `jsonld` near-duplicates) plus
  choice lines. Counting each span once changes the venue median of **7 of 1,478** subjects.
- **Choice lines are rare** in today's data: +14 stored variants. Santopatio's kind of line is
  the exception, not the rule.

**Apply (after merge, owner's go-ahead):**
1. back up `helios_laptop`;
2. re-interpret from saved answers, as measured here;
3. refresh Gold;
4. coordinate the Pi restore (check `DEPLOYED_COMMIT` first).

The scratch copy is dropped once the PR is reviewed.

**Applied (2026-10-31/11-01, after #148 merged; the owner's "proceed").** The code was `main`
at 3a524d6.
- **`helios_laptop`.**
  - Backup `var/laptop-run/helios_laptop-2026-10-31-pre-resolve-v6.dump` (main checkout,
    85,759,136 bytes, sha256 `b046ea0e…`).
  - Re-interpreted from saved answers, 22:49–23:46Z: 3,056 pages, 0 model calls, 0 failures,
    prices 127,273.
  - Gold refreshed (effective 23:46:05Z): `current_menu` **103,697** rows; 416 price-index
    rows, identical row for row to the scratch copy's. The citywide median is 1016.
  - Post-apply dump: `helios_laptop-2026-11-01-resolve-v6.dump` (sha256 `bf80f534…`).
- **The Pi** (firsthelios.com). The earlier P8-21 session confirmed it had nothing running on
  either machine.
  - Backup `~/helios-backups/firsthelios-20261101-p8-21-v6/`: the database (sha256
    `baa9f420…`, 103,683 rows) and the code. The 2026-10-31 backup is kept.
  - Backend `ab674e5` → `3a524d6` by `git archive` and `rsync --delete`, keeping `.env` and
    `var/`, with `DEPLOYED_COMMIT` written and the API image rebuilt. There was no migration
    (`13081a087231`).
  - The database dropped and restored from the laptop dump (checksum checked on the Pi):
    `pg_restore` exit 0, no errors; 103,697 rows, 416 index rows; `alembic check` clean.
  - Downtime was **307 s**. `/`, `/healthz`, `/readyz`, `/v1/venues` and
    `/v1/price-index/cells` return 200 over HTTPS on `firsthelios.com` and `www`. The public
    `all` row reads 656 venues, 56,690 priced rows, median 1016. The frontend (`774776d`) is
    unchanged.
- The scratch copy `helios_p821q7_test` was dropped.

**§8 held-out (2026-11-01).** The re-test owed since resolve-v4 ran on a fresh draw of 50 of
P8-20's new page texts (34 scorable), with blind labels under the labels-v10.1 conventions.
`resolve-v6` with `validator-v10` **passes every bar**:
- recall 0.895;
- price accuracy 0.995;
- gold-row FR 0.072 [0.038, 0.110];
- catch 0.999;
- usable prices 0.772 [0.670, 0.878];
- [5c] gated section exact 0.940.

The page check's precision on the draw is 0.90 (45 / 50), below its 0.95 bar as a point
estimate. Record:
[2026-11-01-p8-21-resolve-v6-held-out.md](../reviews/2026-11-01-p8-21-resolve-v6-held-out.md).

## Amendment 35 (2026-11-01, proposed): the page check's precision on P8-20's pages, and nutrition tables

**Status: Proposed 2026-11-01 (session P8-21). Measurement only; nothing built.** Owner questions
below. Record:
[2026-11-01-p8-21-page-check-precision.md](../reviews/2026-11-01-p8-21-page-check-precision.md).

**Why.** The §8 held-out of `resolve-v6` measured the page check (`classifier-v2+v3`,
Amendment 27) at 0.90 on 50 pages. The owner asked for a larger sample before any change
(ADR-0025, Owner answers, Q2).

**Measured** (200 of P8-20's new page texts, simple random, seed 20261102; Sonnet first pass,
re-checked by the session):
- **Precision 0.890 (178 / 200), Wilson [0.839, 0.926].** 0.940 [0.898, 0.965] if single-item
  detail pages count as menus. Both below the 0.95 bar.
- Platform pages 46 / 46; own-site pages 132 / 154 (0.857). P8-20's several-pages discovery
  (ADR-0022) reaches deeper own-site pages.
- The 22 false accepts: 10 single-item pages (one dish or product), 4 articles, 3 products
  (pre-orders, tickets, appointments), 3 other, 2 hubs.
- **19 of the 22 put no row in Gold.** They cost extraction time only.
- **One class is harmful: nutrition tables.** The validator reads calories and servings as
  prices: P.F. Chang's Lettuce Wraps at $330.00 (330 calories). Over Gold, pages whose path
  names nutrition carry **1,354 priced rows on 5 records** (one P.F. Chang's table stored for 4
  venues, 317 rows each, and an 86-row table), all false. That is a floor: only paths were
  searched.

**Proposed.**
1. **A nutrition-table guard first** (it is the only class that harms Gold). Measure, then
   build one of:
   - **(a) validator (`validator-v11`, recommended):** a bare number (no currency sign, no
     decimals) that sits in a run of bare-number cells in one row (a numeric table's row) is
     not a price. Generic: it reads the page's shape, not its words or its site. Measure first
     on the labelled dev and held-out sets (no recall loss allowed by the §8 rules) and on Gold
     (the rows it would drop, and a sample of them read);
   - **(b) page check:** reject a page whose body is mostly numeric-table rows. Coarser: it
     also drops a priced menu laid out as a table.
2. **No change for single-item pages, articles, products and hubs.** They add no Gold rows
   today; a rule for them would trade recall for extraction time.
3. **No classifier retrain.** Not proposed (the owner's approval is needed for one, and the
   harm sits in the validator's price reading, not in which pages are read).
4. **The §8 page bar keeps counting single-item pages as `not_menu`**, the stricter reading.

### Owner questions (Amendment 35)

- **Q1. The precision gap.** Accept 0.890 as a known gap (Amendment 23's form: the cost is
  extraction time; the next verifier change re-measures on this draw), and act only on the
  harmful class? *Recommended.*
- **Q2. Nutrition tables.** Measure (a) the validator's numeric-row rule, then build it as
  `validator-v11` if it loses no recall on the labelled sets? *Recommended.* Or (b) the page
  check, or both?
- **Q3. The 1,354 rows already in Gold.** Remove them through the rule (re-interpretation of the
  stored pages with `validator-v11`, no model calls, then a Gold refresh, as `resolve-v6` was
  applied)? *Recommended:* there is no per-record removal (no manual entries).
- **Q4. Single-item pages.** Keep them `not_menu` in the §8 page bar? *Recommended*: a dish's
  detail page is not the venue's menu, even when it prints one price.

### Built: `validator-v11` (2026-11-01, session P8-21)

Built after the owner's answers (Q1–Q4 as recommended). Record:
[2026-11-01-p8-21-validator-v11.md](../reviews/2026-11-01-p8-21-validator-v11.md).
- **Rule** (the shared reader, `prices.table_cells`): a block that prints only an unmarked number
  is a numeric table's cell when it follows one label block in a run of at least 6 such blocks
  (`TABLE_COLUMNS`), in at least 3 consecutive rows (`TABLE_ROWS`). Mark cells ("X", "✓", "-")
  and blank blocks are skipped; a labelled run of a found table's width is one of its rows also
  under another section heading. A cell gives no bare reading and doesn't vote in `bare_page`;
  money (a mark or two decimals) is read as before. The rows requirement is what keeps a price
  column printed after a section's dishes (`dev:cfb443e9b654`, runs of 6–19 gold prices) read:
  a plain "run of K" rule would have lost it at any K up to 19.
- **Measured, no recall or accuracy loss:** of 2,504 labelled or published texts (dev, the P8-21
  §8 held-out, the precision draw, P8-11's corpus) the reader changes one, the precision draw's
  P.F. Chang's nutrition table (`not_menu`). 1,685 measured pages keep every verdict; the P8-21
  held-out's §8 report is identical; the invariance suite has 0 differences on 334 pages.
- **Gold (read-only):** of the 2,039 stored texts behind `helios_laptop`'s Menu pages, it changes
  two, P.F. Chang's and Brio's nutrition tables: the 5 records and 1,354 priced rows above, all
  false. Under `validator-v11` none of their rows keeps a price (the dishes stay in Menu,
  unpriced; Gold stores priced rows only).
- **Versioning:** `validator-v10` → `validator-v11` names the reader change, as Amendment 15 did
  for v7's: the reader is shared with stitch, the repairs, [5b]–[5d] and [5c], whose own rules
  and versions (`repairs-v9`, `resolve-v6`) are unchanged. Every `llm` and `jsonld` page becomes
  due for re-interpretation from saved answers (no model call).
- **Apply (owner, after merge):** laptop backup → re-interpretation → Gold refresh → Pi restore,
  as `resolve-v6` was applied.
