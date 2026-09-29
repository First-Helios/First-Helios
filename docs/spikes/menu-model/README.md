# Spike: on-device menu model (classify, extract, validate)

**Status:** Done, 2026-09-23 to 2026-09-27: stages A–F and H plus a usable-price session; G
(cuisine) not run. Winner: Qwen3-4B-Instruct-2507 Q4_0 on the Pi CPU, process v2.3 + stitch v3 +
validator v3. This is the evidence for
[ADR-0013](../../adr/0013-phase5-menu-pipeline.md) (Accepted). Project status lives in the
[README](../../../README.md#status).
**Opened:** 2026-09-23 by the owner
**Fed:** the menu-page classifier per
[ADR-0010 Amendment 3](../../adr/0010-website-and-menu-url-resolution.md#amendment-3-2026-09-23-menu-page-verification-and-platform-sites),
D3.4; cuisine tags deferred by
[ADR-0006](../../adr/0006-gold-menu-read-models.md#owner-decision)

This folder records a **throwaway evaluation**. It answers whether small models
running on the Orange Pi (RK3588, arm64, 32 GB RAM, CPU first) can replace
per-site parsing code for finding and reading menus, and possibly for cuisine
tagging. It built nothing that ships. Its output is evidence for an ADR.

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
errors that the static checks miss. (Not run.)

**How the validator is measured:** run it on (a) correct extractions and (b)
deliberately corrupted ones (a mutated price, prices swapped between items, an
invented item, a price from a different section). Report the catch rate and
the false-reject rate.

## Success bars (proposed at the start)

The owner later relaxed the RAM bar (2026-09-26) and the validator bars (Q5 below).
ADR-0013 holds the adopted bars.

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
  containers, DB, env files or ports. No sudo. Don't run `resolve_urls`.
  Bind anything you serve to 127.0.0.1.
- Record each model's licence; prefer Apache-2.0 or MIT. Report every download
  with its size.

## Setup: what was measured

Stages (ADRs and the checklist cite them by letter): **A** sample, **B** labels, **C**
baselines (JSON-LD/platform parse coverage; the S4 pre-filter rows in Results), **D**
classifiers, **E** extractor, **F** validator, **G** cuisine (not run), **H** findings.

- **Sample.** The owner ran a read-only candidate export (`sql/export_candidates.sql`:
  current Overture-seeded Establishments with a website, ≤ 2 per host, ≤ 12 per primary
  category, 150 venues). All 150 were fetched with `SiteFetcher`: 219 pages with a 200 or a
  label (20 robots-blocked or failed). Page labels: 48 menu (34 venues), 131 not a menu
  (including menu hubs), 32 JS-only, 8 empty; 1 menu was image-only; PDF menus were linked from
  ≥ 6 sites but not read (`SiteFetcher` decodes bodies to text).
- **Labels.** Block labels and gold items + prices on 25 menu pages (1,400 items, 1,555
  prices; 24 pages priced). A second read-only export (`sql/export_candidates_2.sql`, ranks
  151+, no overlap) supplied **held-out-3**: 9 new venues, 463 items, 495 prices. The owner
  spot-checked a random 20 % of each batch's labels; neither check needed corrections. Anonymized counts:
  [labels-summary.md](./labels-summary.md).
- **Splits.** dev (6 pages) and held-out-1 (8) shaped the validator and prompts. held-out-2
  (10) was the honest set until it was scored and then used for tuning; held-out-3 replaced it.
  Cross-validation for [1] and [3] is GroupKFold(5), grouped by venue.
- **Hardware.** Pi = Orange Pi 5 Plus (RK3588, 4×A76 + 4×A55, 31 GB), CPU inference pinned to
  the A76 cores (`-t 4`). Usable-price variants were screened on a local GPU with the same
  GGUF (its v2.2 numbers match the Pi's within 0.01); the chosen configuration was re-run on
  the Pi. Decisions were pre-registered in `spikes/menu_model/stress/PLAN.md`.
- **Stress run.** 43 pages (41 passed by the out-of-fold page gate plus the 2 gold pages it
  drops), 2 llama-server slots.

## Results

Final configuration: Qwen3-4B-Instruct-2507 Q4_0, process v2.3 + stitch v3 + validator v3,
on the Pi (`st-v23`) unless noted.

| Stage | Setup | Result | Meets bar? |
|---|---|---|---|
| [0] Structured parse | schema.org JSON-LD `MenuItem` + generic embedded-state walker | priced structured data on **3/48 menu pages (2/34 venues)**; 0/32 JS-only pages carry priced state; one site's JSON-LD has 40 priced items, none of them on the visible page (validator: 39 downgrade, 1 reject) | baseline only |
| S4 pre-filter (venue) | ADR-0010 Am. 3 verdict vs page labels | precision 0.605, recall 0.676. False positives: a press release, a blog post, a platform marketing signup, another city's location page, chain location/hub pages, `/menus` landing pages | baseline |
| S4 pre-filter (page) | `page_menu_signal` on all 179 text pages | precision 0.597, recall 0.833 (priced menus 0.750) | baseline |
| [1] Page classifier | potion-base-8M (MIT, 30 MB) + 7 layout features, LR, nested threshold for precision ≥ 0.95 | **precision 0.976, recall 0.833** (priced menus 0.893); 22 ms/page on the Pi. Others: bge-small precision 0.935 / recall 0.604; MiniLM-L6 1.000 / 0.521. Picked from 3 models on 48 positives, so optimistic | precision yes; recall ties S4 overall, beats it on priced menus |
| [2] Segmentation | stdlib `html.parser` blocks | 15 ms median/page on the Pi | — |
| [3] Block classifier | bge-small-en-v1.5 (MIT, 67 MB) + layout features, LR | item F1 **0.670**, price F1 **0.859**; [1]+[2]+[3] 3.0 s median/page, peak RSS 558 MB on the Pi | **no** (bar 0.90); not used in the winner |
| [4] Price accuracy | validator-accepted rows | **0.993** (24 gold pages); held-out-3: 0.901 at the first frozen score, 0.980 after a fix (seen data, local), 0.992 on the Pi | yes (≥ 0.98), with the held-out-3 caveat |
| [4] Item recall | gold items on menu pages | **0.906** (24 pages); held-out-3 0.888 | yes (≥ 0.85) |
| [4] Usable prices | accepted rows with the exact gold price / all gold prices | **0.837** (24 pages); 0.739 held-out-2 (later tuned on); held-out-3 0.766 first frozen score (local), 0.764 on the Pi after the fix | not a tracker bar (finding 3) |
| [5] Validator v3, corruption catch | injected corruptions | 0.984 (24 pages); **0.971 held-out-3** | **no** (bar 0.99; swaps of unlabeled prices are indistinguishable by text) |
| [5] Validator v3, false rejects | correct gold rows | 0.015 (24 pages); **0.103 held-out-3** | tuning yes; held-out-3 just over (bar 0.10) |
| [5] Validator on real output | v2.2 stress run | false-reject 0.082; catch 0.446 (misses: grounded non-items such as headings/descriptions next to a real price) | FR yes; catch n/a |
| Pi runtime | 43 stress pages, 2 slots | **7.8 pages/h** (19,907 s; v2.2: 7.7, median 360 s/page, p90 1,105, max 1,786); 0 errors | **no** (bar 60 s); workable as a batch job |
| Pi RAM | llama-server peak RSS | **5.2 GB with the host prompt cache off** (`--cache-ram 0`, measured on v2.2; outputs identical); 13.8 GB with the default cache | yes with the cache off; owner relaxed the 8 GB bar |

Winner by the pre-registered rule: Q4_0 over Q4_K_M (quality tied within 0.02, faster: 7.7 vs
7.1 pages/h at v2.2). Where the remaining gold prices go (24 pages): accepted 83.7 %, item
missed 7.9 %, right item but a different amount 3.8 %, right amount rejected by the validator
3.3 %, item found without a price 1.2 %.

### Usable-price levers

Goal (open question 1): raise usable prices from the v2.2 baseline toward 0.80+, price
accuracy first.

| Configuration (Qwen3-4B Q4_0, Pi unless noted) | Usable, 24 pages | Usable, ho2 | Usable, ho3 | Price accuracy (24 / ho3) | Item recall (24) |
|---|---|---|---|---|---|
| Baseline: v2.2 + row stitching v1 + validator v2 (`st-q40`) | 0.705 | 0.549 | 0.598 (local) | 0.991 / 0.997 | 0.897 |
| **v2.3 prompt + stitch v3 + validator v3** (`st-v23`) | **0.837** | **0.739** | 0.764 (after the fix: seen data) | 0.993 / 0.992 | 0.906 |
| + adaptive Qwen3-8B pass (coverage < 0.7), local | +0.000 to +0.006 | +0.000 | +0.000 | unchanged | — |

What each lever did (local screening on dev + ho1, 14 pages, 992 gold prices; usable prices):

| Lever | Result | Kept? |
|---|---|---|
| **Stitch v2** (deterministic, saved outputs): a description line under a heading item merges into it; a price echoed as its own "item" is dropped; an unpriced item takes the price-only line(s) printed 1-4 blocks below it; a variant copied from the name ("(L)") is dropped | 0.792 → 0.864 on the stress outputs, accuracy 0.992 | yes |
| **Prompt v2.3**: "a name line, then its price and/or description lines are ONE item; the name is the short line, never the description", with a worked example in that layout | 0.862 → 0.887, 13 % fewer generated tokens | yes |
| **Block-role hints** (`[item]`/`[price]`/`[desc]` tags from the stage [3] classifier, out-of-fold by venue, LOVO item F1 0.70) | item recall 0.93 → 0.87; usable 0.887 → 0.849 | **no** |
| **Stitch v3**: variant completion restricted to labeled price lines (an item keeps its first price but drops the second: "Glass $7" / "Bottle $26", "Americano $2/$3") and description rows echoing the item's price dropped | all 24: 0.800 → 0.841 | yes |
| **Validator v3**: "$19.5" one-decimal prices, bare "11 / 44" glass/bottle pairs, dietary marks glued to names ("Eggplantv"), unpriced description/nutrition rows no longer end a price scan | false rejects on correct gold rows 0.041 → 0.015 (24 pages); corruption catch 0.986 → 0.984 | yes |
| **Adaptive second pass** (label-free coverage = accepted priced rows / printed prices; below 0.7 re-extract with Qwen3-8B Q4_K_M, 3k chunks; keep the result with more accepted priced rows) | +0.006 on dev+ho1, 0 on ho2 and ho3; single-pass 8B and 3k chunks were each worse than v2.3; on the Pi the 8B decodes 0.56-0.71 tok/s per slot (4B: ~2.8), 4-5× slower | **no** |

Models tried and dropped (all on the Pi): Qwen2.5-1.5B-Instruct Q4_K_M (item recall 0.36-0.46,
runaways); Phi-4-mini-instruct Q4_K_M (item recall 0.64); Qwen3-4B with process v1 (item recall
0.984 on dev but ~30 min/page); NPU Qwen2.5-1.5B w8a8 (decode ~10 tok/s vs 18-22 on CPU);
NPU Qwen3-4B w8a8 (does not load on rknpu 0.9.6); speculative decoding (lossless, 30-40 %
slower). The runner-up, Qwen3-4B Q4_K_M, tied on quality at v2.2 (price recall 0.658, item
recall 0.874) and ran at 7.1 pages/h.

## Findings and recommendation

1. **A small LLM on the Pi CPU can extract menus with trustworthy prices, but slowly.**
   Qwen3-4B-Instruct-2507 (Apache-2.0, 2.4 GB Q4_0) found 91 % of gold items, and 99 % of the
   prices the validator accepted were exactly right, on list, card and inline layouts alike. The
   cost is ~7-8 minutes per menu page (7.8 pages/h): about 12 days of Pi time for a full pass
   over ~2,300 menu pages (estimate from the sample's menu rate), so this only works as a
   background batch job that re-extracts **only pages whose content changed**.
2. **The validator does its main job.** Accepted prices are 99 % exact. It cannot reject a real
   printed price attached to something that is not an item (a heading or description the model
   emitted as an item); static grounding is blind to that by construction.
3. **Usable-price yield is the weak point: 0.84 on the tuning pages, 0.74-0.77 held out.** The
   main loss at v2.2 was layouts that print the price on its own line: the model transcribed
   line by line, so the item came back unpriced and "$7.50/Medium" came back as its own "item".
   Three cheap levers fixed most of it (Results, "Usable-price levers"): prompt v2.3 (a name
   line and the price/description lines after it are one item), deterministic repairs on the
   model's rows (stitch v3), and validator v3. On held-out-3 the first frozen score showed a
   repair taking the *next* item's leading copy of its price on pages that print every price
   twice (accuracy 0.901); restricting it to labeled price lines fixed it, but that number is
   on seen data. The remaining wrong prices on held-out-3 are the model itself picking the next
   item's copy; the validator cannot tell them apart without also rejecting legitimate
   unlabeled size lines. **Ceiling:** the largest remaining loss is items the model never
   extracts (7.9 % on the 24 pages, 13 % on held-out-2/3); with this model on the Pi,
   ~0.85-0.90 is a realistic target, not 1.0.
4. **The process mattered more than the model size.** Compact grammar-constrained JSON (no
   pretty-printing), keyed rows, ~1.5k-char chunks with a context line, and a deterministic
   retry for priced-but-empty chunks made the extractor ~2× faster than the first version while
   keeping quality. Each change needed a quality re-check: two of them first broke recall (a
   JSON-schema `pattern` the server silently ignored; a too-strict grammar that pushed prices into
   the wrong field or let the model close the list at once). Parallel slots are lossless
   (byte-identical output) but gain ≤ 8 %.
5. **The RK3588 NPU is not the answer for this job.** It is correctly set up (numbers match
   independent benchmarks) but runs only W8A8, so it decodes ~2× slower than the CPU on Q4
   weights; it is 4× faster at prompt processing. The 4B model needs a newer kernel driver
   (rknpu ≥ 0.9.7); rknpu is built into the Pi image's kernel, so upgrading means a new kernel
   and a reboot of the headless box. Running NPU and CPU together costs the CPU ~29 % (shared
   memory bandwidth).
6. **Deterministic stages carry less than hoped.** Structured data (JSON-LD, embedded state)
   priced 3 of 48 menu pages; 32 of 219 fetched pages (15 %) need JavaScript (not attempted, per
   the brief); the block classifier missed its bar and is not needed in the winning pipeline.
7. **Where the Pi's time goes; block-role hints hurt.** In the stress run 83 % of LLM time was
   generating output (~5.6 tok/s across 2 slots), 17 % reading input, 2 % on chunks that
   produced nothing. At v2.2, 30 % of generated rows on the gold pages were not menu items.
   Feeding the block classifier's predictions to the LLM as soft role hints (`[item]`,
   `[price]`, `[desc]`, out-of-fold by venue) lowered item recall 0.93 → 0.87 and usable prices
   0.887 → 0.849 on dev + ho1: the model drops lines the classifier mislabels. The prompt fix
   (v2.3) reduced the non-item rows and unpriced items without them. Keep the block classifier
   out.
8. **Operations.** Without airflow the Pi throttled 27 % of the time (SoC ~80 °C, cores to 600
   MHz), yet throughput dropped only ~2 %; with a fan it stays ~70 °C. Greedy decoding was
   byte-identical across runs, slot counts and restarts. llama-server's default host prompt
   cache adds up to 8 GB of RAM (`--cache-ram`).
9. **A held-out set caught what the tuning pages could not.** Every lever looked safe on the 24
   pages it was tuned on (accuracy ≥ 0.993); the first held-out-3 score showed one repair
   accepting wrong prices on an unseen layout (0.901). Deterministic repairs need the same
   held-out discipline as the model, and production should keep sampling pages for spot checks
   (a few per month) to catch new layouts.

**Recommendation for the Phase 5 ADR:** adopt the pipeline **[1] page classifier →
[2] segmentation → [4] Qwen3-4B-Instruct-2507 Q4_0 via llama.cpp on the Pi CPU (process v2.3) →
deterministic repairs (stitch v3) → [5] validator v3**, with accepted rows stored as the
lowest-trust `llm` interpretation (ADR-0005), as an **offline batch job that only re-extracts
changed pages**. Keep structured parses (JSON-LD) ahead of it where present. Drop the block
classifier (also as prompt hints), the NPU path, speculative decoding and the adaptive Qwen3-8B
second pass (≤ +0.006, 4-5× slower on the Pi, a second 5 GB model). Plan for **~75-84 % usable prices
per readable menu page** (held-out 0.74-0.77, tuning pages 0.84) with price accuracy ~0.98-0.99,
store the rest as items with unknown price, and keep a small monthly spot-check sample, since
unseen layouts can still fool the repairs (finding 9).

## Open questions for the owner (all answered)

**Q1. Is ~70 % usable prices acceptable?** The owner chose all three levers (2026-09-26), which
gave the numbers above. **Owner decision (2026-09-27): one universal process, no per-platform
parsers** (Wix, Square, BentoBox, ...): "we are willing to lose data for the benefit of a
universal process." Per-site code needs re-aligning for every page that does not play nice;
future gains should come from upgrading the model, the classifier or the generic data
preparation. Consequences: (a) the remaining loss (items never extracted, 8-13 %) is closed only
by a better model or better generic data prep, not by site code; (b) the deterministic repairs
stay only while they are layout-generic, pay off on a held-out set, and still add something when
the model changes (re-measure each on every model/prompt change; delete what the model no longer
needs); (c) the evaluation harness (gold labels, held-out discipline, `stress/compare.py`,
`stress/loss.py`) is what makes a model swap a measured drop-in.
**Owner clarification (same day):** the line is *per-website branching* ("for website 1 do X,
website 2 do Y"), not custom logic as such. Allowed: (i) the schema.org JSON-LD parse, as long
as it stays a general-purpose standard reader; (ii) relational/positional repairs (a price is
printed close to its item, so the rule space is small and applies abstractly); (iii) a
**toolbelt** of such generic fixes that catches most problems, chosen per page by a decision
matrix or classifier (e.g. the label-free coverage signal, a layout detector), which also
lowers the overfitting risk seen on held-out-3.

**Q2–Q9, answered 2026-09-28 (session S13b) and recorded in
[ADR-0013](../../adr/0013-phase5-menu-pipeline.md):**

| Q | Question | Answer |
|---|---|---|
| 2 | Throughput: a ~12-day first pass and change-only monthly runs on the staging Pi, or other hardware? | Pi batch job |
| 3 | Change detection: what counts as "changed"? | hash of the segmented text plus the pipeline version |
| 4 | JS-only menus (32 of 219 pages): out of scope, or a headless browser? | headless browser in ADR-0013 now, measured before it is switched on |
| 5 | Validator bars: v3 misses 0.99 / 0.10 on unseen pages; relax, or require a second signal? | catch ≥ 0.97, false reject ≤ 0.12, price accuracy ≥ 0.98 |
| 6 | Trust level: show validator-accepted `llm` prices directly? | yes, labelled as `llm` |
| 7 | Pi kernel/driver: keep the stock kernel, or plan an rknpu ≥ 0.9.7 upgrade? | plan the upgrade separately |
| 8 | Cooling: a fan as a deployment requirement? | recommended, not required |
| 9 | Cuisine tags (step G): in this ADR or separate? | separate, later ADR |

**Q10. Block-role hints A/B before the ADR?** Done: they hurt (finding 7); dropped.

Questions the spike did not settle (PDF menus, page scope, promotional rows) are ADR-0013's own
open questions.

## Reproduce

- **Code:** branch `spike/menu-model`, folder `spikes/menu_model/` (never merged). Candidate
  exports `sql/export_candidates.sql` and `sql/export_candidates_2.sql` (read-only SELECTs);
  fetch `fetch_sample.py`; stage [0] `stage0.py`, S4 baselines `baselines.py`; [1]/[3]
  `classify.py`, Pi timing `bench.py`; NPU binding `npu_extract.py`; repairs `stitch.py`;
  label summary `labels_summary.py`; evaluation `stress/compare.py`, `stress/loss.py`,
  `stress/coverage.py`; pre-registration `stress/PLAN.md`. Labels: `labels/review.txt`
  (auditable record), `labels/ho3/`.
- **Data:** the main checkout's gitignored `var/spikes/menu-model/` (`MENU_SPIKE_DATA`), and
  `~/menu-model-spike/` on the Pi (models incl. Qwen3-8B, llama.cpp build, venvs, copied pages,
  results; about 22 GB).
- **Final numbers:** `MENU_SPIKE_PROCESS=v2 MENU_SPIKE_PROMPT=v23 MENU_SPIKE_STITCH=3
  MENU_SPIKE_VALIDATOR=v3` with `stress/compare.py`, `stress/loss.py`, `stress/coverage.py`.
  Stitch v3 and validator v3 were frozen at `e6e4e1f` on the spike branch.
- **Classifier stack:** fastembed 0.8.1 (Apache-2.0) + onnxruntime 1.30 + scikit-learn 1.9.1,
  no torch (333 MB venv).
- **Extractor stack:** llama.cpp `84e76d8`, CPU build on the Pi (GCC 11.4,
  `-mcpu=cortex-a76.cortex-a55+dotprod`), `llama-server` on 127.0.0.1, 2 slots, compact GBNF
  grammar. GGUF downloads: Qwen3-4B-Instruct-2507 (Apache-2.0; Q4_K_M 2.50 GB, Q4_0 2.4 GB),
  Qwen3-8B Q4_K_M 5.03 GB (Apache-2.0), Qwen2.5-1.5B-Instruct Q4_K_M 1.12 GB (Apache-2.0),
  Phi-4-mini-instruct Q4_K_M 2.49 GB (MIT).
- **NPU (dropped):** RKLLM runtime v1.2.3 (closed binary, Rockchip BSD-3-style licence);
  `GatekeeperZA/*-RKLLM-v1.2.3` models (Apache-2.0): Qwen2.5-1.5B w8a8 2.06 GB,
  Qwen3-4B-Instruct-2507 w8a8_g128 5.29 GB.
