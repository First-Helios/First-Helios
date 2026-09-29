# ADR-0013: Phase 5 menu pipeline — page classifier, on-device LLM extraction, validator

**Status:** Proposed, except the page classifier: its parts were accepted
2026-09-29 (owner, session S6d; [Amendment 1](#amendment-1-2026-09-29-page-classifier-accepted-early-rendering-decision)).
The LLM extraction, `llama-server`, validator, Menu writes and the open questions
below remain Proposed.
**Date:** 2026-09-28
**Phase:** 5 (absorbs the menu-reading parts of ROADMAP Phases 3 and 6)
**Decides for:** owner decision G.b ("Phase 5 menu processing uses the spike's
pipeline … replacing ROADMAP's Scrapy-vs-Crawlee framing",
[remediation checklist](../reviews/2026-09-22-remediation-checklist.md) §G); the
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
  assigned to the same Subject as that menu-URL record.
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
  invented location prices). See open question 1.
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
  by hand to catch new layouts (spike finding 9).

### 9. Out of scope

Cuisine or other tags (Q9; ADR-0006 deferral stands, separate ADR), per-platform
parsers, images and OCR, the NPU, and deals/promotions (Phase 10).

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

1. ⚠ Worker image target, `menu` extra, `llama-server` service and model manifest.
2. `packages/helios_parsing`: segmentation, text hash, JSON-LD reader, chunking,
   repairs, validator, with the ported harness and synthetic tests.
3. `menu-page` Bronze writes (Captures, bundles, Versions, locators) and the batch
   CLI, without extraction.
4. Classifier runtime; ADR-0015 verifier bump to `classifier-v1` (after S6d).
5. Extraction and Menu writes; first held-out evaluation recorded.
6. ⚠ Headless render, its measurement on the 32 JS-only pages, then enablement.
7. Owner: rknpu upgrade runbook (independent of 1–6).

## Open questions for the owner

1. **Page scope.** Menu-URL records (and so `menu-page` records) are assigned to the
   Organization, so every extracted price is an Organization claim. For a chain,
   a per-location platform page (`<gers>|<host>`) really describes one location.
   Recommended: Organization scope for v1; per-location scope for platform pages in
   a follow-up once ADR-0015's chain-homepage guard exists.
2. **PDF menus** (linked from ≥ 6 sample sites; `SiteFetcher` decodes bodies to text,
   so the spike never read them): v1 skips them as `pdf` Captures, or add a PDF
   text-layer reader (a new dependency) feeding the same segmentation and LLM path?
3. **Rendered sub-requests.** robots.txt is checked for the page Helios navigates
   to; the requests the page's own scripts make (e.g. a platform's menu API) are not
   checked separately, as in a normal browser. Acceptable, or check robots for each
   sub-request host too?
4. **Spot-check size and owner:** e.g. 5 pages per monthly run, labelled by an agent
   and confirmed by the owner?
5. **Promotional rows** ("BOGO", "half off") in menus: ROADMAP §2 / Phase 5 wants them
   excluded from menu prices; the spike did not measure them. Handle as a generic
   repair now, or leave to Phase 10?

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
