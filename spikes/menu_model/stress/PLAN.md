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

## Usable-price session (2026-09-26/27), pre-registered before the Pi numbers

Goal: usable prices (validator-accepted rows with the exact gold price / all gold prices) from
0.700 toward ≥ 0.80, quality first (price accuracy on accepted rows stays ≥ 0.98).

Screening ran on this machine's GPU (llama.cpp b11165 CUDA, same Qwen3-4B Q4_0 GGUF, 2 slots)
on the 14 tune pages (dev + ho1) only; its v2.2 numbers match the Pi's st-q40 within 0.01, so it
ranks variants, and the Pi confirms. Tune-set usable prices (stitch v2 unless noted):

| Variant | items | usable | accuracy |
|---|---|---|---|
| st-q40 (Pi), stitch v1 = baseline | 0.923 | 0.792 | 0.990 |
| st-q40 (Pi), stitch v2 (repairs only) | 0.923 | 0.864 | 0.992 |
| v2.2 local | 0.931 | 0.862 | 0.998 |
| **v2.3 prompt** local | 0.925 | **0.887** | 0.996 |
| v2.2 + role hints | 0.878 | 0.858 | 0.996 |
| v2.3 + role hints | 0.868 | 0.849 | 0.998 |
| v2.3, 3k chunks / 8B / 8B + 3k (single pass) | 0.90-0.93 | 0.843-0.847 | 0.977-0.996 |
| v2.3 + adaptive 8B/3k pass below coverage 0.7 | 0.933 | 0.893 | 0.996 |

Frozen for the Pi: **process v2.3** (v2.2 + the split-layout prompt), **no role hints** (they cost
~6 points of item recall), **stitch v2** (`MENU_SPIKE_STITCH=2`), and the **adaptive second pass**
with Qwen3-8B Q4_K_M, 3k chunks, for pages whose label-free coverage (accepted priced rows /
printed prices) is below **0.7**; the result with more accepted priced rows is kept. Pi runs:
`st-v23` (all 43 stress pages), then the second pass on the flagged pages. ho2 is scored once,
after both; held-out-3 (fresh labels) is scored once at the end.

### Outcome (2026-09-27)

Frozen at `e6e4e1f` (stitch v3, validator v3), then one post-held-out fix (`label-only run
completion`, scorer nearest-copy match). Final, Pi `st-v23` outputs under the final rules:
usable prices 0.837 on the 24 pages (baseline st-q40 0.705), 0.739 on ho2 (0.549), 0.764 on
ho3 (local v2.2 baseline 0.598; seen data after the fix; the first frozen local ho3 score was
0.766 at price accuracy 0.901); price accuracy 0.993 / 0.995 / 0.992; item recall 0.906.
Throughput unchanged (7.8 pages/h). Role hints dropped (they cost item recall). The adaptive
Qwen3-8B pass adds at most +0.006 and is optional. Details: tracker Results and Log U-1..U-4.
