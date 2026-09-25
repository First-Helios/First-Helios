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
- **Load set:** the other 24 menu-labeled pages (no gold: throughput, stability, RAM only)
  plus every not_menu page, which the page classifier should stop before the LLM.
- Monitor (`monitor.sh`, 10 s): temperatures, CPU/NPU clocks, free RAM, load.

## Candidates

Fixed after the throughput micro-bench (`throughput.sh`); expected shape:

1. **Baseline:** Qwen3-4B-Instruct-2507 Q4_K_M, process v1 (positional rows, 3k chunks, 1 slot).
2. **Optimized:** same model, process v2 + the best lossless/near-lossless throughput
   settings from the micro-bench (slots, speculative decoding, quant).
3. **Alternative model family** for quality: Phi-4-mini-instruct Q4_K_M (MIT), process v2,
   same throughput settings as 2.

The NPU is out: the 4B does not load on driver 0.9.6, and 1.5B quality failed.

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
