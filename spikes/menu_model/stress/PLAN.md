# Stress test plan (pre-registered before any stress-test result)

Owner's direction (2026-09-25): pick a clear winner for the use case, and **rank quality
high**: the goal is correct items and prices from menu pages of every shape and format; the
speed work must not trade that away.

## What runs

The whole pipeline, per page, unattended on the Pi (Helios postgres keeps running, skimmer
disabled): [1] page classifier (potion-base-8M + LR) → [2] segmentation → [4] extractor →
deterministic repairs (variant→price swap, duplicate collapse) → [5] validator v2 (frozen).

Workload, same for every candidate, same order:

- **Quality set:** all 24 gold menu pages (1,380 items, 1,555 prices; formats: html_list,
  html_cards, html_inline, price_list). Held-out-2 (10 pages) is also reported on its own,
  since dev/ho1 pages shaped the prompts and the validator.
- **Load set:** every other page the page gate passes (18 more menu pages without gold and
  1 not_menu false positive; throughput, stability, RAM only). 43 pages per candidate in all.
- Monitor (`monitor.sh`, 10 s): temperatures, CPU/NPU clocks, free RAM, load.

## Candidates

Updated after the micro-bench and quality re-checks (2026-09-25):

- **v1 baseline dropped from the run:** ~30 min per page (2,509 s for 3 dev pages) means about
  50 days of Pi time for a monthly pass over ~2,300 menu pages, so it fails Gate O outright.
  Its quality on the pages already measured stays the reference (dev 3 pages: item recall
  0.984, price recall 0.833; ho2 5 pages: item recall 0.918).
- **Finalists (two, ~8-9 h each):** picked from the v2.2 re-check on 3 dev pages among
  Qwen3-4B-Instruct-2507 Q4_K_M, Qwen3-4B-Instruct-2507 Q4_0 (ARM repack, 16-30 % faster, outputs
  differ) and Phi-4-mini-instruct Q4_K_M (MIT); all with process v2.2 and 2 slots.
- Dropped by measurement: speculative decoding (lossless but 30-40 % slower on 4 shared cores),
  more than 2 slots (≤ 8 % gain), the NPU (4B does not load on rknpu 0.9.6; 1.5B quality fails).

The page gate uses the stage [1] classifier's **out-of-fold** predictions from step D (potion
emb+hand, nested P≥0.95 threshold): 41 pages pass (40 menu, 1 not_menu); it drops 2 gold pages
(159 of 1,380 gold items). Both views are reported: extractor quality on all 24 gold pages
(Gate Q) and end-to-end quality through the gate.

## Decision rule (quality first)

**Gate Q — quality, on the 24 gold pages, repairs on:**

- exact price accuracy on validator-accepted rows ≥ 0.98 (tracker bar);
- item recall ≥ 0.85 overall (tracker bar) **and** ≥ 0.70 in every format with ≥ 2 pages
  (no layout left behind);
- no chunk lost to a crash or unparseable output; truncated chunks ≤ 2 %.

**Gate O — operational:** peak RSS of the model stack ≤ 8 GB; the run finishes without
manual intervention; thermal throttling is reported, not a gate.

**Choice among candidates that pass both gates:** highest **price recall on accepted rows**
(the share of gold prices that end up as accepted, correct rows: the usable data).
Candidates within 0.02 of the best count as tied on quality; the tie is broken by pages/hour
on the load set, then by lower peak RSS. Throughput never beats a quality lead above 0.02.

If no candidate passes Gate Q, there is no winner: the result names the closest candidate,
which bar it misses and by how much.

Any optimization that changes outputs (quantization, chunk size, batching numerics) is
re-checked for quality; greedy speculative decoding is expected to be output-identical and is
verified with `extract score --ref` against the same config without it.
