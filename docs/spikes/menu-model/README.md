# Spike: on-device menu model (classify, extract, validate)

**Status:** Done (A–F, H); G (cuisine) not run. Winner: Qwen3-4B-Instruct-2507 Q4_0 on the Pi CPU, process v2.2
**Opened:** 2026-09-23 by the owner
**Feeds:** the Phase 5 menu-extraction ADR (menu-page classifier per
[ADR-0010 Amendment 3](../../adr/0010-website-and-menu-url-resolution.md#amendment-3-2026-09-23-menu-page-verification-and-platform-sites),
D3.4; cuisine tags deferred by
[ADR-0006](../../adr/0006-gold-menu-read-models.md#owner-decision))

This folder tracks a **throwaway evaluation**. It answers whether small models
running on the Orange Pi (RK3588, arm64, 32 GB RAM, CPU first) can replace
per-site parsing code for finding and reading menus, and possibly for cuisine
tagging. It builds nothing that ships. Its output is evidence for an ADR.

## Why

Scraped menus come in endless page formats. Deterministic parsers (JSON-LD,
known platforms) handle only some of them, and custom code per layout doesn't
scale. The idea is to use generic page segmentation, a small classifier for
blocks, and a small LLM for extraction. A **final validation check** must then
prove that every extracted value actually appears on the page before anything
is trusted.

## Pipeline under test

```
page ──► [0] structured? (JSON-LD / known platform) ──yes──► deterministic parse (baseline)
              │ no
              ▼
         [1] menu-page classifier ........ is this page a menu?
              ▼
         [2] generic segmentation ........ DOM/text blocks (no per-site code)
              ▼
         [3] block classifier ............ section | item | price | modifier | noise
              ▼
         [4] LLM extractor ............... blocks → {section, item, description, prices[]} JSON
              ▼
         [5] VALIDATOR (final gate) ...... static grounding checks + optional classifier cross-check
              ▼
         accepted rows (would become the lowest-trust `llm` interpretation, ADR-0005)
```

### [5] Validator: the final check

This stage is deterministic code, optionally backed by a second model. It
decides **accept / downgrade-to-unknown / reject** for each extracted row.

Static checks (required):
- **Price grounding:** the normalized price (`$12.50`, `12.5`, `12,50`,
  `$12`) must occur in the source text of the **same block**, or of an
  adjacent block linked to the item. No price on the page means no priced row;
  at most it becomes `unknown`.
- **Name grounding:** the item name's tokens appear in that block
  (case/whitespace/punctuation-insensitive; a small edit distance is allowed
  only if you measure and report it).
- **Binding:** the price is the nearest one to the item in document order, and
  it isn't already bound to a different item unless it's shared on purpose
  (e.g. a "all tacos $3" section price).
- **Sanity:** currency is consistent within the page; the amount is in a
  plausible range; no duplicate (item, variant, price) rows; the evidence
  locator (block id plus character span) is recorded for each field.

Model cross-check (optional, measured separately): a small NLI or cross-encoder
answers "does this block support *item X costs Y*?". Keep it only if it catches
errors that the static checks miss.

**How the validator is measured:** run it on (a) correct extractions and (b)
deliberately corrupted ones (a mutated price, prices swapped between items, an
invented item, a price from a different section). Report the catch rate and
the false-reject rate.

## Proposed success bars (owner to confirm or adjust)

| Stage | Metric | Proposed bar |
|---|---|---|
| [1] Menu-page classifier | precision / recall vs. S4's cheap pre-filter | precision ≥ 0.95, recall better than the pre-filter |
| [3] Block classifier | item + price F1 | ≥ 0.90 |
| [4] Extractor | exact price accuracy on validator-accepted rows | ≥ 0.98 |
| [4] Extractor | item recall on menu pages | ≥ 0.85 |
| [5] Validator | injected-corruption catch rate | ≥ 0.99 |
| [5] Validator | false-reject rate on correct rows | ≤ 0.10 |
| Pi runtime | median time per menu page (all stages) | ≤ 60 s |
| Pi runtime | peak RAM of the model stack | ≤ 8 GB (leaves room for Helios) |

## Guardrails

- **No Helios writes and no Helios runtime changes.** Spike code lives on the
  branch `spike/menu-model` under `spikes/menu_model/`, outside `packages/` and
  `apps/`, and is never merged. Only findings, metrics and label summaries come
  back to this folder, through a docs PR.
- Raw HTML/PDF snapshots stay in gitignored `var/spikes/menu-model/`; they are
  never committed.
- Fetching uses Helios's `SiteFetcher` (robots.txt, rate limit, size cap),
  identifies itself honestly, and is capped at the sample size.
- On the Pi: work only in `~/menu-model-spike`. Don't touch the Helios
  containers, DB, env files or ports. No sudo. Don't run `resolve_urls`
  (the Pi gate still holds). Bind anything you serve to 127.0.0.1.
- Record each model's licence; prefer Apache-2.0 or MIT. Report every download
  with its size.

## Progress

- [x] A. Sample: owner-exported candidate list; about 60 pages fetched (≈40 real menus in varied formats: HTML list, table, PDF, image-only or JS-only noted; ≈20 non-menus: home, about, catering, ordering platforms)
- [x] B. Labels: page labels, block labels, and gold items + prices for the menu pages; owner spot-checks 20%
- [x] C. Baselines: JSON-LD/platform parse coverage; S4 pre-filter precision/recall
- [x] D. [1]+[3] classifiers: embedding + logistic regression, cross-validated; timed on the Pi
- [x] E. [4] extractor: `llama.cpp` + a small (1.5B–8B) instruct model with a JSON-only grammar; timed on the Pi (plus RK3588 NPU via RKLLM, owner-approved)
- [x] F. [5] validator: static checks + corruption injection, and on real extractor output (optional NLI cross-check not run)
- [ ] G. (Optional) cuisine: not run (time went to the extractor stress test)
- [x] H. Findings written below; recommendation for the ADR

## Results

Sample: 150 candidate venues, 219 fetched pages; 48 menu pages (34 venues), 25 with block labels and
gold items (1,400 items, 1,555 prices; 24 priced). Anonymized counts:
[labels-summary.md](./labels-summary.md). Splits: dev (6 pages) and held-out-1 (8) shaped the
validator and prompts; **held-out-2 (10 pages) is the honest held-out set**. Cross-validation for
[1] and [3] is grouped by venue. Pi = Orange Pi 5 Plus (RK3588, 4×A76 + 4×A55, 31 GB), CPU
inference pinned to the A76 cores.

| Stage | Setup | Result | Meets bar? |
|---|---|---|---|
| [0] Structured parse | schema.org JSON-LD `MenuItem` + generic embedded-state walker | priced structured data on **3/48 menu pages (2/34 venues)**; 0/32 JS-only pages; one site's JSON-LD prices are not on the visible page | baseline only |
| S4 pre-filter (venue) | ADR-0010 Am. 3 verdict vs page labels | precision 0.605, recall 0.676 | baseline |
| S4 pre-filter (page) | `page_menu_signal` on all 179 text pages | precision 0.597, recall 0.833 (priced menus 0.750) | baseline |
| [1] Page classifier | potion-base-8M (MIT, 30 MB) + 7 layout features, LR, nested threshold | **precision 0.976, recall 0.833** (priced menus 0.893); 22 ms/page on the Pi | precision yes; recall ties S4 overall, beats it on priced menus |
| [2] Segmentation | stdlib `html.parser` blocks | 15 ms median/page on the Pi | — |
| [3] Block classifier | bge-small-en-v1.5 (MIT, 67 MB) + layout features, LR | item F1 **0.670**, price F1 **0.859**; 3.1 s median/page on the Pi | **no** (bar 0.90) |
| [4] Extractor, price accuracy | Qwen3-4B-Instruct-2507 Q4_0, process v2.2, validator-accepted rows | **0.990** (24 gold pages); 0.993 held-out-2 | **yes** (≥ 0.98) |
| [4] Extractor, item recall | same | **0.899** (24 gold pages); **0.846** held-out-2; worst format 0.843 | yes overall; held-out-2 just under |
| [4] Usable prices | accepted rows with the exact gold price / all gold prices | 0.643 (24 pages); 0.478 held-out-2 | not a tracker bar (see findings) |
| [5] Validator, corruption catch | v2 (frozen), injected corruptions | 0.983 held-out-2 (0.993 dev, 0.981 ho1) | **no** (bar 0.99; misses are indistinguishable by text) |
| [5] Validator, false rejects | v2 on correct gold rows | 0.112 held-out-2 (0.000 dev/ho1) | **no** (bar 0.10) |
| [5] Validator on real output | stress run, Q4_0 | false-reject 0.082; catch 0.446 (misses: grounded non-items such as headings/descriptions next to a real price) | FR yes; catch n/a |
| Pi runtime | Q4_0, 2 slots, 43 pages, fan on | **median 360 s/page** (p90 1,105, max 1,786); 7.7 pages/h; 0 errors | **no** (bar 60 s); workable as a batch job (findings) |
| Pi RAM | llama-server peak RSS | 9.9 GB with the default host prompt cache; 5.7 GB with it off (Q4_K_M, measured) | owner relaxed the 8 GB bar (2026-09-26) |

Models tried and dropped (all on the Pi): Qwen2.5-1.5B-Instruct Q4_K_M (item recall 0.36-0.46,
runaways); Phi-4-mini-instruct Q4_K_M (item recall 0.64); Qwen3-4B with process v1 (item recall
0.984 on dev but ~30 min/page); NPU Qwen2.5-1.5B w8a8 (decode ~10 tok/s vs 18-22 on CPU);
NPU Qwen3-4B w8a8 (does not load on rknpu 0.9.6); speculative decoding (lossless, 30-40 %
slower). The runner-up, Qwen3-4B Q4_K_M, tied on quality (price recall 0.658, item recall 0.874)
and ran at 7.1 pages/h.

## Findings and recommendation

1. **A small LLM on the Pi CPU can extract menus with trustworthy prices, but slowly.**
   Qwen3-4B-Instruct-2507 (Apache-2.0, 2.4 GB Q4_0) found 90 % of gold items, and 99 % of the
   prices the validator accepted were exactly right, on list, card and inline layouts alike. The
   cost is ~6-8 minutes per menu page (7.7 pages/h): about 12 days of Pi time for a full pass
   over ~2,300 menu pages (estimate from the sample's menu rate), so this only works as a
   background batch job that re-extracts **only pages whose content changed**.
2. **The validator does its main job.** Accepted prices are 99 % exact. It cannot reject a real
   printed price attached to something that is not an item (a heading or description the model
   emitted as an item); static grounding is blind to that by construction.
3. **Usable-price yield is the weak point: 64 % overall, 48 % on held-out-2.** Where gold prices
   go (runner-up, all gold): 12.8 % item found but no price attached (list layouts where the
   price is its own block), 12.7 % item missed, 5.8 % right price rejected by the validator
   (variant/position rules), 3.0 % wrong amount. A deterministic "attach the nearest printed
   price" step recovered only a little (held-out-2 0.480 → 0.503), so it is not a quick fix.
4. **The process mattered more than the model size.** Compact grammar-constrained JSON (no
   pretty-printing), keyed rows, ~1.5k-char chunks with a context line, and a deterministic
   retry for priced-but-empty chunks made the extractor ~2× faster than the first version while
   keeping quality. Each change needed a quality re-check: two of them first broke recall (a
   JSON-schema `pattern` the server silently ignored; a too-strict grammar that pushed prices into
   the wrong field or let the model close the list at once).
5. **The RK3588 NPU is not the answer for this job.** It is correctly set up (numbers match
   independent benchmarks) but runs only W8A8, so it decodes ~2× slower than the CPU on Q4
   weights; it is 4× faster at prompt processing. The 4B model needs a newer kernel driver
   (rknpu ≥ 0.9.7). Running NPU and CPU together costs the CPU ~29 % (shared memory bandwidth).
6. **Deterministic stages carry less than hoped.** Structured data (JSON-LD, embedded state)
   priced 3 of 48 menu pages; 32 of 219 fetched pages (15 %) need JavaScript (not attempted, per
   the brief); the block classifier missed its bar and is not needed in the winning pipeline.
7. **Where the Pi's time goes, and the unused lever.** In the stress run 83 % of LLM time was
   generating output (~5.6 tok/s across 2 slots), 17 % reading input, 2 % on chunks that
   produced nothing. On the gold pages 30 % of generated rows were not menu items
   (descriptions 218, price lines 186, noise/headings 114 of 1,972 rows): wasted time, and the
   validator's blind spot. The block classifier is not used in the winning pipeline (the LLM
   sees plain `bNNNN | text`); feeding its predictions to the LLM as **soft role hints**
   (`[item]`, `[price]`, `[desc]`) is the most promising next experiment, aimed at both the
   non-item rows and the 12.8 % of items found without their price. Untested; the classifier's
   item F1 (0.67) means hints must stay advisory, never a filter.
8. **Operations.** Without airflow the Pi throttled 27 % of the time (SoC ~80 °C, cores to 600
   MHz), yet throughput dropped only ~2 %; with a fan it stays ~70 °C. Greedy decoding was
   byte-identical across runs, slot counts and restarts. llama-server's default host prompt
   cache adds up to 8 GB of RAM (`--cache-ram`).

**Recommendation for the Phase 5 ADR:** adopt the pipeline **[1] page classifier →
[2] segmentation → [4] Qwen3-4B-Instruct-2507 Q4_0 via llama.cpp on the Pi CPU (process v2.2) →
deterministic repairs → [5] validator**, with accepted rows stored as the lowest-trust `llm`
interpretation (ADR-0005), as an **offline batch job that only re-extracts changed pages**.
Keep structured parses (JSON-LD) ahead of it where present. Drop the block classifier, the NPU
path and speculative decoding. Do not treat the extractor as complete coverage: plan for
~64 % usable prices per menu page at first and measure it in production.

### Open questions for the owner (before the Phase 5 ADR)

1. **Is ~64 % usable prices per menu page acceptable to ship**, with unpriced items stored as
   items with unknown price, or is a price-attachment step (and its own held-out test) a
   precondition?
2. **Throughput budget:** is a ~12-day first pass and change-only monthly runs acceptable on the
   staging Pi, alongside Helios? Or should extraction run on other hardware?
3. **Change detection:** what counts as "changed" (content hash of the menu region, fetched
   HTML, ETag)? This decides the monthly cost.
4. **JS-only menus** (32 of 219 pages; Toast, Square, Clover, BentoBox): stay out of scope,
   or does Phase 5 add a headless browser (new runtime dependency, ADR)?
5. **Validator v3:** the frozen v2 misses the 0.99/0.10 bars on held-out-2. Tuning needs a
   fresh labeled set; label more pages now or ship v2 and measure?
6. **Trust level:** should validator-accepted `llm` prices be shown to users directly, or only
   after a second signal (another source, owner confirmation)?
7. **Pi kernel/driver:** keep the stock kernel (NPU path closed), or plan an rknpu ≥ 0.9.7
   upgrade for other NPU uses (e.g. the classifier), with a recovery plan for a headless box?
8. **Cooling:** add a fan/heatsink to the Pi as a deployment requirement?
9. Cuisine tags (step G) were not attempted: still wanted for this ADR, or separate?
10. **Block-role hints A/B before the ADR?** (finding 7) Tune on dev pages, test once on
    held-out-2, ~2 h on the Pi.

## Log

| Date | Session | Branch | What happened | Resume notes |
|---|---|---|---|---|
| 2026-09-23 | setup | docs/menu-model-spike | Tracker and hand-off prompt created | — |
| 2026-09-23 | A-1 | spike/menu-model | Wrote read-only candidate export `spikes/menu_model/sql/export_candidates.sql` (current Overture-seeded Establishments with a website; ≤2 per host, ≤12 per primary category, 150 rows, seeded order). Verified on a throwaway migrated `*_test` DB seeded through the real discovery code (`seed_check.py`), with and without `resolve_urls` records. SSH to the Pi as `fortune@192.168.1.219` is refused (publickey); no `~/.ssh/config`. | Waiting on owner to run the SELECT on the Pi and drop the CSV at `var/spikes/menu-model/candidates.csv` (main checkout, gitignored). Next: stratified ~60-page sample + fetch via `SiteFetcher`. Before stage D: get the Pi SSH user/key from owner. |
| 2026-09-23 | A-2 | spike/menu-model | Pi access: `ssh orangepi@192.168.1.219` (password auth, fish login shell: wrap remote commands in `bash -s`). Pi: aarch64, 8 cores, 31 GB RAM, 192 GB free, Python 3.10, gcc/g++/make/uv present, **cmake missing**, no `ensurepip` (use `uv venv`). Created `~/menu-model-spike/` with `export_candidates.sql`. Helios stack on the Pi was stopped (not touched). Wrote `spikes/menu_model/fetch_sample.py` (stratified pick + SiteFetcher fetch of homepage / S4 verdict / menu anchors / platform link / one non-menu link). | Still waiting on `candidates.csv`. Then: `MENU_SPIKE_DATA=<main checkout>/var/spikes/menu-model uv run python -m spikes.menu_model.fetch_sample`. llama.cpp needs cmake → ask owner before stage E (`uv pip install cmake` in the spike venv is the no-sudo option). |
| 2026-09-23 | B/F-1 | spike/menu-model | Fetch of all 150 candidates via `SiteFetcher` running (≈120/150). Built stage [2] segmenter (stdlib), stage [5] validator + corruption-injection eval, labeling tool with an auditable review file (`spikes/menu_model/labels/review.txt`). 17 pages labeled so far (16 menus). **Validator v1** (frozen at `77aef1d`, dev = first 6 pages): dev FR 0/215, catch 274/276. **v1 held-out** (8 pages, 777 rows): FR 6.7% (48 = one template page whose price sits 9-12 blocks after the name, beyond the fixed 4-block window; 3 = same dish in two sections flagged duplicate; 1 = `Half $20.95/ Whole $41.95` suffix misread), catch 327/334 = 97.9% (6 swaps between unlabeled size prices are indistinguishable by text; 1 = price-only `<h4>` misread as a section heading). | Next: validator v2 (nearest-price-run region, heading-with-words shared price, per-section duplicates, strict `/label` suffix), freeze, evaluate on pages labeled after v2 (held-out-2). |
| 2026-09-24 | B-1 | spike/menu-model | **A done.** 150 candidates exported by owner; all 150 venues fetched via `SiteFetcher` (219 pages with a 200 or labeled; 20 robots-blocked/failed, 10×403). Page labels for all 219 pages: 48 menu, 131 not_menu (incl. menu hubs), 32 js_only, 8 empty; 1 image-only menu; PDF menus linked from ≥6 sites (not fetched: `SiteFetcher` decodes bodies to text). Block + gold labels on 25 menus: 3,548 blocks, 1,400 items, 1,555 prices (review record: `spikes/menu_model/labels/review.txt`). **Validator v2** (frozen `9e6bc87`) on held-out-2 (10 pages, 563 rows): FR 11.2% (bare-number prices "11hh/12", "11 / 44"; heading-only shared prices with two time labels; dietary marks glued to names; one-decimal "$19.5"; mixed variant/add-on price lines), catch 98.3% (all misses indistinguishable). CAVEAT: validator metrics were computed before the owner spot-check; recompute after corrections. | Waiting on owner to review `spikes/menu_model/labels/spotcheck.md` (46 page labels + 5 menus' blocks/items). Then: apply corrections to `review.txt`, `labeltool apply`, re-run `eval_validator --split=ho2` (and dev/ho1), then stage C baselines. |
| 2026-09-24 | B-2 | spike/menu-model | Owner reviewed the spot-check (queried Consuelo's gold: the sample shows 20% of items, full gold has all 7 Breakfast Plates; add-ons are `modifier` by design) and accepted: "okay so it seems to work". No label corrections, so the validator v2 numbers above stand unchanged. | Next session: stage C (JSON-LD/platform baseline; S4 precision/recall against the page labels), then D-E on the Pi, F write-up, H. Data lives in the main checkout's `var/spikes/menu-model/` (`MENU_SPIKE_DATA`). |
| 2026-09-24 | C | spike/menu-model | **C done** (`30ca09b`, `spikes/menu_model/stage0.py`, `baselines.py`). Stage [0] structured prices: schema.org `MenuItem` JSON-LD on 5/48 menu pages (3 venues), priced on 2 pages (1 venue); a generic embedded-state walker found Wix `priceInfo` on 1 more page. Priced structured coverage **3/48 pages, 2/34 venues**; 0/32 `js_only` pages carry priced state (Next.js/Nuxt/Square/BentoBox/Clover bootstraps hold no prices). Smokey Mo's JSON-LD has 40 priced items but none of those prices is on the visible page (validator: 39 downgrade, 1 reject). S4 venue level: 23 menu / 15 not_menu / 10 js_only / 5 not fetched verdicts; precision 0.605, recall 0.676 (23/34 venues with a fetched menu page). False positives: press release, blog post, Toast marketing signup, another city's IHOP, chain location/hub pages, `/menus` landings. S4's page predicate on all 179 text pages: P 0.597, R 0.833. | — |
| 2026-09-24 | D | spike/menu-model | **D done** (`2a82470`, `classify.py`, `bench.py`; own venv `var/spikes/menu-model/.venv-ml`: fastembed 0.8.1 (Apache-2.0) + onnxruntime 1.30 + scikit-learn 1.9.1, no torch, 333 MB). GroupKFold(5) by venue. **[1]** best: `potion-base-8M` (MIT, 30 MB) emb+hand LR, nested threshold for P≥0.95: **P 0.976, R 0.833** (priced-menu R 0.893 vs S4 0.750); bge-small (MIT, 67 MB) P 0.935 R 0.604; MiniLM-L6 (Apache-2.0, 90 MB) P 1.000 R 0.521. Selection over 3 models on the same CV, 48 positives: optimistic and noisy. **[3]** (25 pages, 19 venues, 6,466 blocks): best item F1 **0.670**, price F1 **0.859** (bar 0.90 missed); as a noise filter it keeps 94% of item/price blocks. **Pi** (bench, 24 menu pages): [1]+[2]+[3] median 3.0 s/page (p90 6.9, max 13.2), page classifier 22 ms, peak RSS 558 MB. | Next: E, LLM extractor. Pi venv `~/menu-model-spike/.venv` (py3.12, same versions); data copied to `~/menu-model-spike/data`. |
| 2026-09-25 | E-1 | spike/menu-model | Owner approved ("Pi only") building llama.cpp on the Pi: `uv pip install cmake` (spike venv), CPU build of llama.cpp `84e76d8` (GCC 11.4, `-mcpu=cortex-a76.cortex-a55+dotprod`, no i8mm/SVE) in `~/menu-model-spike/llama.cpp`, `llama-server` on 127.0.0.1 only. GGUF downloads (Q4_K_M): Qwen2.5-1.5B-Instruct 1.12 GB (Apache-2.0), Qwen3-4B-Instruct-2507 2.50 GB (Apache-2.0), Phi-4-mini-instruct 2.49 GB (MIT). Owner also asked to permanently disable the unrelated skimmer project's units on the Pi; with explicit owner approval to use sudo for this one action: `systemctl disable --now skimmer-workflow.service skimmer-backup.timer` (unit files/data untouched; undo with `enable --now`). Stage [1]-[3] Pi bench re-run uncontended: unchanged (median 3.14 s/page). llama-bench 1.5B: pp1024 50 tok/s, tg 22 tok/s at `-t 4` (A76 only; `-t 8` tg 16.8). | 1.5B extraction run over the 24 gold pages in progress on the Pi (`logs/run-qwen25-1.5b.log`). |
| 2026-09-25 | E-2 | spike/menu-model | **CPU Qwen2.5-1.5B (llama.cpp, grammar)**: stopped by owner after 14/24 pages ("we've seen enough"). Item recall 0.355 (0.60 excluding 4 pages lost to runaway generation at the 3,072-token cap); price accuracy on validator-accepted rows 1.000 (110/110, with counted repairs: 91 prices emitted in the variant slot moved, exact duplicates collapsed); median 202 s/page, max 499 s; peak RSS 3.9 GB. Validator on real output: false-reject 0.052, catch 0.742; all 25 misses are headings/descriptions emitted as items next to a real printed price (grounded, so static checks cannot reject them). **RK3588 NPU (owner-approved)**: kernel driver rknpu 0.9.6 (runtime warns 0.9.7 recommended, works), NPU device usable without sudo (ACL). RKLLM runtime v1.2.3 (`librkllmrt.so`, closed binary, Rockchip BSD-3-style licence) + ctypes binding (`npu_extract.py`); models `GatekeeperZA/*-RKLLM-v1.2.3` (Apache-2.0): Qwen2.5-1.5B w8a8 2.06 GB, Qwen3-4B-Instruct-2507 w8a8_g128 5.29 GB (owner allowed >5 GB). No grammar support: JSON by prompt + prefill + lenient parse. Same 1.5B model: NPU prefill 210-230 tok/s vs CPU ~50; NPU decode ~10 tok/s vs CPU ~18-19; NPU RSS 2.0 GB. Output-heavy extraction is slower on the NPU (decode is bandwidth-bound; w8a8 weights are ~2x Q4_K_M); NPU fits prompt-heavy/short-output work. Two prompt tweaks were made on one dev page (`cbcdb04ffbe0`) to get multi-row output. NPU 1.5B run stopped after 2 pages. Added a runaway guard (output cap ≈30 tokens per input line) before the 4B run. | Qwen3-4B CPU (grammar) running on the 10 held-out-2 pages; then NPU 4B speed on 2-3 pages. |
| 2026-09-25 | E-3 | spike/menu-model | **CPU Qwen3-4B-Instruct-2507 Q4_K_M (grammar)** on 5 held-out-2 pages (stopped by owner; largest page skipped): item recall **0.918**, price accuracy on accepted rows **1.000**, but validator false-reject 0.456 (63 `variant_not_grounded`: bare numbers put in the variant slot, and Glass/Bottle labels the v2 position rule rejects), so price recall only 0.426; median 456 s/page, max 665 s; decode 5.6→2.5 tok/s as context grows; **peak RSS 8.1 GB** (8k ctx). Same pages with 1.5B: item recall 0.455. **NPU Qwen3-4B**: `rkllm_init` fails (`failed to malloc npu memory, size: 3633315840`, errno 14) with and without `embed_flash`/`base_domain_id`; needs rknpu ≥0.9.7/0.9.8. rknpu is built into the image's kernel (`CONFIG_ROCKCHIP_RKNPU=y`, kernel packages 1.2.0 `[installed,local]`, no apt upgrade path): updating means a new kernel + reboot of the headless Pi. **Hybrid interference** (NPU 1.5B on A55 + CPU 4B pinned to A76): NPU decode 8.5→7.5 tok/s (−12%), CPU decode 6.2→4.4 tok/s (−29%); prefill barely affected. Estimated gain of a driver upgrade (NPU 4B ≈3 tok/s) + hybrid: ≈+20% aggregate. Recommendation: no driver upgrade now. | Next: CPU optimizations (keyed rows, variant letter pattern, 1.5k chunks, cached system prompt, 2 parallel slots, 4k ctx + q8 KV), A/B on dev pages, then the stress test. |
| 2026-09-25 | E-4 | spike/menu-model | **NPU setup check (owner asked: is it configured right?)**: yes. Our Qwen2.5-1.5B w8a8 numbers (prefill 210-230 tok/s, decode ~10 tok/s) match an independent RK3588 measurement (Turing Pi RK1: 202 / ~9.5 tok/s, RKLLM 1.3.0, driver 0.9.7, pinned clocks) and llama.cpp Q4_K_M CPU decode matches too (22 vs 22.6 tok/s). Rockchip's table (16.7 tok/s) uses a 128-token input / 64-token output. Why the NPU is not faster: decode reads every weight per token (memory-bandwidth bound; NPU and CPU share LPDDR) and the RK3588 NPU runs only W8A8 (W4 is RK3576-only), so it moves ~2x the bytes of a Q4 CPU model. It is 4x faster at prefill. On the Pi, DDR (2112 MHz) and NPU (1 GHz) already sit at max under load; Rockchip's `fix_freq_rk3588.sh` (sudo) would pin them and disable CPU idle states; expected gain small since we already match pinned-clock results. Sources: turingpi.com/rkllm-rk3588-npu-llm-inference-turing-pi-rk1, github.com/airockchip/rknn-llm benchmark.md and scripts/fix_freq_rk3588.sh. | A/B (process v1 vs v2, dev pages, Qwen3-4B CPU) running. |
| 2026-09-25 | E-5 | spike/menu-model | **Process v2 + throughput micro-bench** (Qwen3-4B, 3 dev pages, 8 chunks; owner asked for quality to rank high). v2 first used a JSON schema with `pattern`s that llama-server did not enforce (junk output, one HTTP 500 that killed the run); replaced by a hand-written compact GBNF grammar (no whitespace: v1's pretty-printed JSON spent ~25-30% of tokens on newlines/indentation) + a compact example in the prompt (without it the model closed the list at once), per-chunk error handling. Results (wall for 3 pages): v1 2,509 s; v2 np1 1,136 s; np2 1,076; np4 1,042; np6 1,089 (batching lossless, byte-identical output, but ≤8%: CPU decode here is compute-bound, not bandwidth-bound as first assumed); Q4_0 (ARM repack) np1 951 s, np4 795 s (outputs differ); speculative decoding lossless but slower: n-gram (acceptance 24-29%) 1,548-1,572 s, Qwen3-0.6B draft (acceptance 74-87%) 1,480-1,584 s and RSS 9-10 GB -> dropped. **Quality check caught a v2 regression**: item recall 0.906 vs v1 0.984 (price recall on accepted 0.764 vs 0.833): a 1.5k chunk that began mid-section with no heading came back empty (11 items), and a digits-only price rule pushed `$70.00` into the variant, where a letter-required rule derailed the model. v2.1: optional `$` in price, no variant letter rule (repair drops letterless variants), chunks cut before headings when possible, later chunks open with a context line (last heading + last 3 lines, no block ids). | v2.1 re-check (Q4_K_M and Q4_0, np2) running on the same dev pages; then the stress test per `spikes/menu_model/stress/PLAN.md`. |
| 2026-09-25 | E-6 | spike/menu-model | **v2.1 → v2.2 re-checks** (3 dev pages, 2 slots). v2.1 Q4_K_M still returned `{"sections":[]}` for a mid-section chunk (item recall 0.891), Q4_0 0.953. v2.2 adds a deterministic **sparse-chunk retry** (≥3 printed prices in the chunk but < 1/3 as priced rows → re-ask once, telling the model the price count; counted) and a price-on-next-line hint. v2.2 results (item recall / price recall accepted / price accuracy / catch / wall): **Qwen3-4B Q4_K_M 0.992 / 0.882 / 1.000 / 1.000 / 1,323 s** (1 retry, recovered the page); Q4_0 0.945 / 0.812 / 0.992 / 0.684 / 1,139 s; **Phi-4-mini-instruct 0.641 / 0.479** (fails quality, out); v1 reference 0.984 / 0.833 / 1.000 / 1.000 / 2,509 s. Stress finalists: v2.2 Qwen3-4B Q4_K_M and Q4_0 (2 slots), 43 pages each (41 passed by the out-of-fold page gate + the 2 gold pages it drops), ~8-9 h each; v1 dropped (fails the operational gate at ~30 min/page). | Stress test launched on the Pi (`logs/stress.log`, `logs/stress-monitor.csv`); ~17 h unattended. |
| 2026-09-25 | E-7 | spike/menu-model | **Stress run in progress; environment change noted.** Q4_K_M finished: 43 pages, 278 chunks, 21,832 s (6.1 h), 0 errors, **peak RSS 14.1 GB** (suspected llama-server in-RAM prompt cache, to verify with `--cache-ram 0`). Owner turned on the room's ceiling fan at 07:45 CDT (owner-confirmed; Pi clock is Asia/Shanghai), 1 h 22 min into the Q4_K_M run: its first 11 pages ran without the fan, the 12th straddled it (06:23-12:27 CDT); Q4_0 (12:28 CDT on) ran with the fan throughout. Monitor: before the fan SoC mean 79.4 °C, big cores up to 88 °C, big-core clock below max in 27% of samples (down to 600 MHz: thermal throttling); after the fan SoC mean 70.9 °C, 7%; Q4_0 so far 69.9 °C, 6%. Quality is unaffected (greedy decoding); Q4_K_M throughput is understated for its first ~1.4 h. | After Q4_0 ends: re-run Q4_K_M on the pages it processed before ~07:50 CDT with `--cache-ram 0` (fan-on timing + RAM check + determinism), then the report. |
| 2026-09-26 | E-8 | spike/menu-model | **Stress test done** (power outage mid-Q4_0: Pi rebooted, 33/43 results intact, resumed; Q4_0 throughput stitched around the gap: 43 pages in 13,827 s + 6,191 s). Owner confirmed fan at 07:45 CDT; a fan-on Q4_K_M re-run of its 12 pre-fan pages gave identical outputs, ~2% faster (5,576 s vs ~5,700 s), and 5.7 GB peak RSS with `--cache-ram 0` (the 13.5-14.1 GB peaks were llama-server's host prompt cache, default 8,192 MiB). **Owner decision (2026-09-26): the 8 GB RAM bar is relaxed** (Pi has 31 GB; ~10-14 GB with the default prompt cache is fine). Results on all 24 gold pages (Q4_K_M / Q4_0): item recall 0.874 / 0.899; price recall on accepted rows 0.658 / 0.643; price accuracy on accepted 0.992 / 0.990; worst-format item recall 0.864 / 0.843; held-out-2 item recall 0.794 / 0.846, price recall 0.480 / 0.478; end-to-end item recall through the page gate 0.789 / 0.803; 0 errors, 0 truncations; 7.1 / ~7.7 pages/h; peak RSS 13.5 / 9.9 GB (cache on). **Winner by the pre-registered rule: Qwen3-4B-Instruct-2507 Q4_0**, process v2.2, 2 slots (quality tied within 0.02, faster). Owner agreed from the fan-on runs. Price-loss breakdown (Q4_K_M, all gold prices): accepted 65.8%, item found but unpriced 12.8%, item missed 12.7%, right price not accepted 5.8%, wrong amount 3.0%. | Write-up (H) and docs PR. |
| 2026-09-26 | H | spike/menu-model | Results table, findings, recommendation and open questions written; anonymized `labels-summary.md` added. Step G (cuisine) not run. Spike code stays on `spike/menu-model` (never merged); data stays in `var/spikes/menu-model/` and `~/menu-model-spike/` on the Pi. | Owner: answer the open questions, then write the Phase 5 ADR. Pi cleanup when done: `~/menu-model-spike` (17 GB: models, llama.cpp build, venvs, copied pages, results); skimmer units stay disabled unless re-enabled. |

## Hand-off prompt

Launch from the repo root: `claude --model claude-opus-5-5`, then `/model` →
effort **high**; mode: auto.

```text
Run the menu-model spike tracked in docs/spikes/menu-model/README.md. Read that file,
CLAUDE.md, ADR-0005 (menu interpretation kinds and ranking), ADR-0006 (cuisine/tag
deferral), ADR-0010 Amendment 3 (menu-page verification) and apps/discovery/web_client.py
(SiteFetcher) first.

This is a throwaway evaluation, not a feature. Branch spike/menu-model from main and keep
all spike code in spikes/menu_model/ (never under packages/ or apps/, never merged). Raw
page snapshots go in gitignored var/spikes/menu-model/. Follow the tracker's Guardrails
exactly: no Helios DB writes, nothing touching the Helios stack on the Pi, no sudo, no
resolve_urls, 127.0.0.1 only, and record licences and download sizes.

Work through the tracker's Progress list in order:
A. Don't query the Pi DB yourself. Look at the models and write me a read-only SELECT that
   exports ~150 candidates (venue name, website, resolved menu URL if any, Overture
   category if stored) as CSV. Stop and ask me to run it. Then pick a stratified ~60-page
   sample and fetch it with SiteFetcher. Count JS-only and image-only pages; don't add a
   headless browser.
B. Draft labels yourself (page / block / gold items+prices) in spikes/menu_model/labels/,
   then give me a random 20% to spot-check before you compute any metric.
C–F. Build the stages in the tracker's pipeline diagram. The validator [5] is the priority:
   implement the static grounding checks exactly as the tracker specifies, then measure
   them with corruption injection (mutated price, swapped prices, invented item, price
   from another section). Develop on this machine; run timing and RAM on the Pi over SSH
   (192.168.1.219; check ~/.ssh/config or ask me) in ~/menu-model-spike with its own venv.
   Prefer ONNX Runtime for embeddings (ask before installing torch). Build llama.cpp there
   only if the build tools already exist; otherwise ask.
G. Optional, only if time remains.
H. Fill in the tracker's Results table (against the proposed bars), Findings and
   recommendation, and a Log row.

End state: push spike/menu-model (don't open a PR for it). Open a docs-only PR that updates
docs/spikes/menu-model/README.md (ticks, results, findings, log) plus a small anonymized
labels summary, no raw HTML. Don't write the ADR. Finish with the recommendation and
the open questions I need to answer before the Phase 5 ADR. If the budget runs low, commit,
push, and write resume notes in the tracker's Log.
```
