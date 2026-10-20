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

## Amendment 21 (2026-10-20, proposed): pipeline version v9 — [5b] resolve-v2, repairs-v9, context, usable bar

**Status: Proposed 2026-10-20 (session P5-25) for owner review. Not accepted.** Built on
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
   the variant in the name, of 21,038. The debt stays recorded (6,638 flips).
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
9. **Next draw: not decided** (owner ruling R3). Amendment 19 item 7 asks for a pooled
   gold-row FR near 0.05; this version reads 0.084. Resampled 35- and 70-page draws from the
   tuning pages pass all four gated bars 0.765 / 0.875 of the time (v9 resolve-v1: 0.714 /
   0.815), an upper bound: every past draw read worse than its tuning sets.
