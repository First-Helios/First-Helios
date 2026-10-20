# P5-20 — harness-agnostic model bracket screen and harness generalization

**Date:** 2026-10-16 (overnight session P5-20) · **Status:** draft for owner review, committed unchanged in the P5-22 archive ·
**Proposes:** [ADR-0017](../adr/0017-extraction-harness-generalization.md) (Proposed) ·
**Follows:** [P5-19 model screen](./2026-10-15-p5-model-screen.md)

All numbers are on **tuning pages** (the 218 labelled pages of seven sets), never on a held-out
draw; nothing here is a §8 evaluation. Quality runs are laptop-GPU Q4 GGUF (llama.cpp b11176);
GPU speed is not evidence of anything. Scratch, data and scripts: `var/menu-eval/bracket-screen/`
(gitignored; `HANDOFF.md` resumes it).

## Summary

- **B4 (primary extractor): inconclusive** under the frozen clear-winner rule. On TEST (45 pages,
  3,450 gold prices) **Gemma-4-E4B** (greedy, prompt v2.4) has raw usable prices **0.854** against
  the baseline's 0.783 / 0.792 (two replicates): +0.062 to +0.071, every 95 % CI excludes 0, positive
  on 7/7 sets; it also beats the other finalist (Qwen3-4B-2507 Q4_K_M s-n1, +0.055, 6/7 sets). Raw
  price accuracy is level (0.972 vs 0.968 / 0.973). It fails two conditions: more unmatched rows
  (0.272 vs 0.236 / 0.237 per row — over-extraction of descriptions, headings and unlabelled
  page lines, not invented names) and pipeline non-inferiority under the frozen harness (+0.022 /
  +0.035 usable, CI lower bound −0.018 against a −0.014 band; the v8 harness rejects 0.169 of its
  correct rows against 0.070–0.077 for the baseline and accepts 512 unmatched rows against
  267 / 278). The other B4 entries do not separate from the baseline.
- **B8 (escalation only): inconclusive**, but with the strongest result of the screen. The run was
  resumed after the owner rebooted the laptop following a GPU halt.
  - **Against the baseline:** **Qwen3.5-9B** (greedy, prompt v2.4) has raw usable prices
    **0.863**, +0.071 / +0.080 (CIs > 0, 6–7/7 sets). It is also the only entry ahead **under
    today's v8 harness**: pipeline usable 0.837 vs 0.766 / 0.779, +0.058 / +0.072, CIs
    [+0.029, +0.091] / [+0.043, +0.109]. It does this with a lower real-output false-reject rate
    (0.053 vs 0.070–0.077) and fewer accepted rows matching no label (192 vs 267 / 278).
  - **Why it is not a winner:**
    - It does not separate from the other B8 finalist, Qwen3-8B s-n1: +0.028, CI
      [−0.011, +0.068].
    - Its raw price accuracy is lower: 0.957 vs 0.968 / 0.973; wrong-price accepts 35 vs 26 / 27.
  - **Qwen3-8B s-n1** is also ahead of the baseline on raw usable (0.836, CIs > 0) and fails the
    same two conditions.
  - **Cost:** about half the baseline's Pi CPU speed (5.6 vs 10.4 pages/h), so it fits only an
    escalation / fallback role.
- **Harness:** an invariance suite maps where v8 decisions depend on output style rather than the
  page (variant written into the name, lower-cased names, block claims on the description or price
  line). A prototype that removes most of those flips does not pass the multi-model rule on real
  outputs, so **no harness change is accepted**; [ADR-0017](../adr/0017-extraction-harness-generalization.md)
  (Proposed) sets the invariance principle and the multi-model, leave-one-model-out rule. The
  largest fit is the **prompt**: a neutral rewrite (N1) helps other families and hurts the baseline.
- **Pi (context only):** CPU, production runtime: baseline 10.4 pages/h, Gemma-4-E4B 8.8, Qwen3.5-4B
  8.9, Q4_K_M 9.1, Qwen3.5-9B 5.6, Qwen3-8B 5.2 (3 pages). NPU (isolated RKLLM 1.3.1, spike
  W8A8 baseline artifact): ~6.5 pages/h on the same pages, decode 2.5 tok/s, valid JSON 9/9 without a
  grammar.
- **Samples:** FAST 8 pages (28 chunks) ⊂ DEV 15 (82); VAL 15 (120); TEST 45 (375).
- **Thermal guard: 0 pauses** (both runs). GPU halt at 10:00Z at 89 °C (`CUDA error: unspecified
  launch failure`, NVRM full-chip reset); after the owner's reboot B8 TEST resumed and finished.
  GPU time used: 8.8 of 12 h.

## 1. Frozen protocol and amendments

`frozen-protocol.md` was written at 2026-10-16T02:15Z, before any new candidate ran
(sha256 `f1ae806480c2f93759a63791f9e08ddeaccdd20e916a1a4a373bcd7fe2dc5f8d` at freeze; amendments
appended with timestamps). What had been seen before freezing: P5-19's seven configurations, scored
with this protocol's scorer on DEV and FAST to verify it (frozen-harness usable prices reproduced
P5-19's 0.794 / 0.811 / 0.446 / 0.732 exactly) and to choose FAST.

- **Splits** (`splits-p520.json`): DEV = P5-19 screen15 (15 pages, 82 chunks); VAL = screen30 −
  screen15 (15 pages, 120 chunks); TEST = 45 of the remaining 188 pages (seed 20261016, 6–7 per
  set, formats by largest remainder; 375 chunks), locked until stage T and scored once.
  FAST (owner amendment) = 8 DEV pages (28 chunks) for fast exploration.
- **Primary metrics (harness-free, `rawscore.py`, 4 synthetic unit tests):** on each chunk's kept
  answer, parsed rows before `rows_of` repairs, validator and [5b], matched with the unmodified
  `evaluation.match`: raw recall, **raw usable prices** (gold (item, amount) pairs found / gold
  prices), raw price accuracy on matched priced rows, unmatched rows per row, page-verbatim copy,
  schema/truncation. Only filter: wine-list sections (the labels' scope rule).
- **Secondary:** the frozen v8 pipeline (`evaluation.score_page`), and the refit harness.
- **Noise band:** |baseline rep A − rep B| per split and metric.
- **Clear-winner rule (per bracket, TEST):** (1) raw usable prices beat every other finalist and
  each baseline replicate — paired page bootstrap, 10,000 resamples, seed 20261016, 95 % CI of the
  difference excludes 0 and the difference is positive on ≥ 5 of 7 sets; (2) raw accuracy and
  unmatched rate not worse than either replicate beyond the band; (3) schema/truncation ≤ baseline
  + 2 points; (4) refit-harness pipeline usable prices: CI lower bound > −band. Else
  **inconclusive**.

Amendments (all in `frozen-protocol.md`):

| # | When (UTC) | By | Change |
|---|---|---|---|
| A1 | 02:00 | owner | GPU budget 12 h (spec ~8 h) |
| A2 | 02:05 | owner | Start with a small fast set (easy / medium / hard-but-feasible pages), go wide fast, then narrow; candidate list widened |
| A3 | 02:15 | agent, before any new score | P2 drop "raw accuracy < 0.95" replaced by "< mean baseline raw accuracy − 0.15": the baseline's own raw accuracy is 0.89–0.93 (raw rows precede the validator). Chosen after seeing P5-19 configs' raw accuracy (disclosed) |
| A4 | 02:10 | owner | Projection stage after the first run; finish around GPU hour 10–11; subagents on cheaper models (none were used) |
| — | 05:40–07:10 | owner | Orange Pi may be used; RKLLM runtime may be updated in its own environment; NPU only for NPU-specific models, Pi CPU for the rest |

Stage plan as run: **F1** (FAST, every candidate, greedy + prompt v2.4) → **F2** (FAST, survivors
× {greedy, model-card sampling seed 20261016} × {v2.4, N1, S1}) → **D** (DEV) → **V** (VAL) →
**T** (TEST, once). Decisions with timestamps: `decisions.md`. No iteration round was needed (VAL
separated the candidates), so `iterations.md` is empty.

## 2. Candidate inventory

Eligibility: family on the official RKLLM release-v1.3.1 supported list for RK3588 with a W8A8
path ([README](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/README.md) sha256
`b1f258d9…e0d8`, [benchmark](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/benchmark.md)
`b328808a…6b52a`, [SDK guide 1.3.1](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/doc/Rockchip_RKLLM_SDK_EN_1.3.1.pdf)
`61ed7267…0da6`: "RK3588 platform supports four quantization types: w8a8, w8a8_g128, w8a8_g256,
w8a8_g512"; supported models "LLaMA, Qwen…Qwen3, Phi-2, Phi-3, ChatGLM3, Gemma, Gemma2, Gemma3,
Gemma3n, Gemma4, InternLM2, … MiniCPM3, MiniCPM4, … Qwen3.5, SmolLM3"), instruct-tuned and usable
text-only, licence permits the use, non-thinking template. Every model loaded fully on the GPU at the
frozen flags unless noted; every token budget (rendered retry prompt + full cap, all 218 pages) fit
6,144 per slot.

### Candidate inventory (GGUF Q4_K_M unless noted; pins = repo@revision, file SHA256)

| Model | Bracket | Params | Publisher repo @ revision | File | SHA256 | RKLLM 1.3.1 evidence | Licence | Outcome |
|---|---|---|---|---|---|---|---|---|
| q3-4b-2507-q40 | B4 | 4.02 B | unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b6 | Qwen3-4B-Instruct-2507-Q4_0.gguf | `e0ba675d86ab277c61701c6793659b2ae801d95e3be791464c321e6fbf613be2` | Qwen3 listed; RK3588 W8A8 benchmark Qwen3-0.6B; owner-measured on NPU | Apache-2.0 | baseline |
| q3-4b-2507-qkm | B4 | 4.02 B | unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b6 | Qwen3-4B-Instruct-2507-Q4_K_M.gguf | `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597` | as above | Apache-2.0 | F1 survivor |
| q3-4b-hybrid | B4 | 4.02 B | Qwen/Qwen3-4B-GGUF@bc640142c66e | Qwen3-4B-Q4_K_M.gguf | `7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5` | Qwen3 listed | Apache-2.0 | out at F1 |
| q35-4b | B4 | 4.21 B | unsloth/Qwen3.5-4B-GGUF@e87f176479d0 | Qwen3.5-4B-Q4_K_M.gguf | `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4` | Qwen3.5 listed; RK3588 W8A8 benchmark 4B | Apache-2.0 | F1 survivor, out at D |
| q35-2b | B4 | 1.88 B | unsloth/Qwen3.5-2B-GGUF@f6d5376be1ed | Qwen3.5-2B-Q4_K_M.gguf | `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223` | Qwen3.5 listed; RK3588 W8A8 benchmark 2B | Apache-2.0 | out at F1 |
| phi35-mini | B4 | 3.82 B | bartowski/Phi-3.5-mini-instruct-GGUF@6d70da17e749 | Phi-3.5-mini-instruct-Q4_K_M.gguf | `e4165e3a71af97f1b4820da61079826d8752a2088e313af0c7d346796c38eff5` | Phi3 listed; RK3588 W8A8 benchmark Phi3 3.8B | MIT | out at F1 |
| gemma3-4b | B4 | 3.88 B | ggml-org/gemma-3-4b-it-GGUF@d09762237476 | gemma-3-4b-it-Q4_K_M.gguf | `882e8d2db44dc554fb0ea5077cb7e4bc49e7342a1f0da57901c0802ea21a0863` | Gemma3 listed | Gemma terms | out at F1 |
| gemma3n-e4b | B4* | 6.87 B total (E4B) | unsloth/gemma-3n-E4B-it-GGUF@90fa8b0e431f | gemma-3n-E4B-it-Q4_K_M.gguf | `43b489bb77a81bda85180e7c490d40ad7f1d5c2ce654c9b05e15e104bd3c777e` | Gemma3n listed; RK3588 W8A8 benchmark E2B-class 2B | Gemma terms | F1 survivor, out at V |
| gemma4-e2b | B4* | 4.65 B total (E2B) | unsloth/gemma-4-E2B-it-GGUF@0314792d7f1f | gemma-4-E2B-it-Q4_K_M.gguf | `740185b21d22ceb83a11c3aa62ad5842ef32c70f6096d756bbee85a1e4ec34b8` | Gemma4 listed; RK3588 W8A8 benchmark E2B | Apache-2.0 | out at F1 |
| gemma4-e4b | B4* | 7.52 B total (E4B) | unsloth/gemma-4-E4B-it-GGUF@bfc15c382204 | gemma-4-E4B-it-Q4_K_M.gguf | `85a896a047553e842f25297ee5b031d64ff30147d9c4af17b1e4b394cd1fab87` | Gemma4 listed (E4B not benchmarked) | Apache-2.0 | B4 finalist |
| llama32-3b | B4 | 3.21 B | unsloth/Llama-3.2-3B-Instruct-GGUF@e7d0997e49c9 | Llama-3.2-3B-Instruct-Q4_K_M.gguf | `6c99cc00ae910f6a532a80022cb4bc1939094527a089c29294b841c0bd87f74d` | LLaMA listed | Llama 3.2 community | out at F1 |
| smollm3-3b | B4 | 3.08 B | unsloth/SmolLM3-3B-GGUF@a7bc17204c8a | SmolLM3-3B-Q4_K_M.gguf | `4de907d2d388a5508fb7cb443a06effe14cce3518b0a78d3bdd9e74d9edce989` | SmolLM3 listed (SDK guide) | Apache-2.0 | dropped: schema/trunc 39 % |
| q3-8b | B8 | 8.19 B | unsloth/Qwen3-8B-GGUF@a6adef130ffb | Qwen3-8B-Q4_K_M.gguf | `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4` | Qwen3 listed; owner-measured 8B on NPU | Apache-2.0 | B8 finalist |
| q25-7b | B8 | 7.62 B | Qwen/Qwen2.5-7B-Instruct-GGUF@bb5d59e06d95 | qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf | `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db` | Qwen2.5 listed; RK3588 W8A8 benchmark 1.5B | Apache-2.0 | dropped: raw acc. 0.670 |
| llama31-8b | B8 | 8.03 B | unsloth/Llama-3.1-8B-Instruct-GGUF@600b0020115f | Llama-3.1-8B-Instruct-Q4_K_M.gguf | `b3bdbf23b47d7e6bb791c99b206deb169cd5a96362a9e3399028df2faacdc506` | LLaMA listed | Llama 3.1 community | F1 survivor, out at V |
| q35-9b | B8 | 8.95 B | unsloth/Qwen3.5-9B-GGUF@3885219b6810 | Qwen3.5-9B-Q4_K_M.gguf | `03b74727a860a56338e042c4420bb3f04b2fec5734175f4cb9fa853daf52b7e8` | Qwen3.5 listed (9B not benchmarked) | Apache-2.0 | B8 finalist |
| gemma2-9b | B8 | 9.24 B | bartowski/gemma-2-9b-it-GGUF@d731033f3dc4 | gemma-2-9b-it-Q4_K_M.gguf | `13b2a7b4115bbd0900162edcebe476da1ba1fc24e718e8b40d32f6e300f56dfe` | Gemma2 listed | Gemma terms | excluded: KV cache does not fit at 12,288 |

\* "E" models placed in B4 by effective parameters (pre-registered); total parameters are larger. Qwen2.5-7B is the official two-shard GGUF (second shard `539cf93f…d72a`).

**Excluded before inference:** InternLM3-8B (RKLLM lists InternLM2 only); GLM-4-9B-chat (only
ChatGLM3-6B listed); Phi-4-mini (Phi-2/Phi-3 listed; its RKLLM path is unverified; Phi-3.5-mini
screened instead); MiniCPM3-4B (weights need a registration questionnaire for commercial use —
**needs owner**); DeepSeek-R1-Distill (thinking-only). **Excluded at load:** Gemma-2-9B (KV cache
does not fit 8 GB at the frozen 12,288 context; no shrinking). Publisher preference: checkpoint
author's GGUF, else ggml-org, unsloth, bartowski (Phi-3.5 has no author/ggml-org/unsloth GGUF;
Llama has none from Meta or ggml-org at Q4_K_M; Gemma's author GGUFs are gated or QAT Q4_0 only).

## 3. Harness audit and generalization prototype (P0)

### Overfit map (invariance suite)

`invariance.py`: each tuning page outside VAL and TEST has its gold rows written as a perfect
model answer, then one meaning-preserving change is applied page-wide (a model's consistent style)
and the page goes through repairs + validator + [5b]. A flip is a gold price whose decision changes.

### Invariance suite (158 pages, 11,149 gold prices; perfect-output accepts: frozen 10,236, harness-g 10,238)

| Perturbation (page-wide) | Frozen v8: accepts lost / gained (pages) | harness-g G1+G2+G3: lost / gained (pages) |
|---|---:|---:|
| claim_next | 189 / 23 (46) | 74 / 19 (21) |
| claim_price_block | 148 / 26 (42) | 49 / 36 (19) |
| price_short | 0 / 0 (0) | 0 / 0 (0) |
| price_two | 0 / 0 (0) | 0 / 0 (0) |
| price_dollar | 0 / 0 (0) | 0 / 0 (0) |
| case_lower | 339 / 4 (59) | 1 / 2 (1) |
| case_upper | 4 / 8 (1) | 2 / 0 (1) |
| case_title | 2 / 8 (1) | 0 / 0 (0) |
| whitespace | 0 / 0 (0) | 0 / 0 (0) |
| variant_in_name | 1583 / 8 (82) | 275 / 8 (25) |
| variant_in_name_paren | 1583 / 8 (82) | 274 / 8 (25) |
| empty_v | 0 / 0 (0) | 0 / 0 (0) |
| section_upper | 0 / 0 (0) | 0 / 0 (0) |
| section_none | 8 / 0 (6) | 8 / 0 (6) |
| section_generic | 8 / 0 (6) | 8 / 0 (6) |
| dup_next_block | 20 / 18 (8) | 14 / 19 (6) |

Mechanisms behind the flips (frozen v8):

- **Variant in the name → `name_not_grounded`.** Grounding needs every name token in one block;
  "Horchata Large" fails when "Large" is printed beside the price, not the name. The matcher
  (H1a) already treats both forms as the same item, so this is a harness-only loss.
- **Lower-cased name → dropped in `stitch`.** `_is_description_line` and the echo rule read the
  *model's* first letter (`row.item[0].islower()`) to recognise description lines, so a model that
  lower-cases names has its rows merged away (one spike page: 100 prices).
- **Claim on the description or price line → `price_not_grounded`.** When the claimed block does
  not ground the name, the validator takes the first grounding block after a cursor and walks
  forward while the next block also grounds — into the description and the next item.

### What the fit costs real models

### Harness fit on DEV: correct raw (item, amount) pairs through the frozen v8 harness

| Config | raw_correct | kept | gained_not_in_raw | ↓price_not_grounded | ↓price_belongs_to_other_variant | ↓variant_not_grounded | ↓price_bound_to_other_item | ✗name_not_grounded | ✗duplicate_row | repairs | accepted_unmatched | wrong_accepted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline Q4_0 rep A (g-v24) | 766 | 727 | 38 | 20 | 6 | 6 | 5 | 1 | 0 | 1 | 55 | 11 |
| baseline Q4_0 rep B (g-v24) | 789 | 746 | 36 | 24 | 6 | 6 | 6 | 0 | 0 | 1 | 67 | 10 |
| q3-4b-2507-qkm g-v24 | 761 | 718 | 33 | 25 | 6 | 10 | 1 | 1 | 0 | 0 | 72 | 13 |
| q35-4b | 752 | 701 | 5 | 37 | 6 | 3 | 2 | 1 | 0 | 2 | 94 | 8 |
| q35-2b | 495 | 418 | 12 | 76 | 0 | 0 | 1 | 0 | 0 | 0 | 158 | 13 |
| q3-8b | 799 | 750 | 10 | 29 | 8 | 7 | 1 | 0 | 0 | 4 | 129 | 17 |
| q25-7b | 785 | 735 | 18 | 32 | 6 | 5 | 0 | 7 | 0 | 0 | 50 | 13 |

### Harness fit on FAST: correct raw (item, amount) pairs through the frozen v8 harness

| Config | raw_correct | kept | gained_not_in_raw | ↓price_not_grounded | ↓price_belongs_to_other_variant | ↓variant_not_grounded | ↓price_bound_to_other_item | ✗name_not_grounded | ✗duplicate_row | repairs | accepted_unmatched | wrong_accepted |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline Q4_0 rep A (g-v24) | 235 | 211 | 12 | 8 | 6 | 5 | 5 | 0 | 0 | 0 | 35 | 4 |
| baseline Q4_0 rep B (g-v24) | 230 | 206 | 16 | 8 | 6 | 5 | 5 | 0 | 0 | 0 | 36 | 4 |
| q3-4b-2507-qkm g-v24 | 221 | 194 | 15 | 12 | 6 | 8 | 0 | 1 | 0 | 0 | 29 | 3 |
| q35-4b | 239 | 217 | 0 | 12 | 6 | 3 | 0 | 1 | 0 | 0 | 47 | 2 |
| q3-8b | 234 | 205 | 7 | 13 | 8 | 7 | 0 | 0 | 0 | 1 | 63 | 12 |
| q25-7b | 230 | 211 | 13 | 9 | 6 | 3 | 0 | 1 | 0 | 0 | 14 | 7 |
| gemma4-e4b g-v24 | 260 | 237 | 8 | 10 | 6 | 5 | 1 | 1 | 0 | 0 | 51 | 11 |
| gemma3n-e4b g-v24 | 237 | 192 | 10 | 25 | 1 | 7 | 8 | 1 | 3 | 0 | 111 | 11 |
| q35-9b g-v24 | 269 | 245 | 1 | 10 | 8 | 5 | 0 | 1 | 0 | 0 | 26 | 1 |
| llama31-8b g-v24 | 217 | 189 | 2 | 18 | 2 | 4 | 3 | 0 | 0 | 1 | 101 | 0 |
| gemma3-4b g-v24 | 205 | 183 | 7 | 11 | 6 | 4 | 0 | 1 | 0 | 0 | 81 | 1 |
| phi35-mini g-v24 | 196 | 168 | 8 | 17 | 1 | 1 | 5 | 2 | 2 | 0 | 82 | 1 |

Loss shares are similar across models (about 9–10 % of raw-correct pairs on FAST for the baseline,
Gemma-4-E4B and Qwen3.5-9B; 19 % for Gemma-3n). The asymmetry is in **gains**: repairs add 36–38
pairs on DEV for the baseline (33 for its Q4_K_M) and 5–18 for P5-19's other families — the repairs
fix the baseline's own split-line habit.

### Prototype harness-g and its acceptance

Scratch copies of `output.py`, `stitch.py`, `validator.py`, `resolve.py` in `hg/` (diff against
`frozen/packages/helios_parsing/`), toggled by `HG`, verified identical to frozen with all changes
off. Changes, each aimed only at a mapped flip and decided by page evidence:

- **G1** — a claim that does not ground the name picks the nearest grounding block within 3 before
  / 1 after the claim, then only exact repeats (no forward walk);
- **G2** — stitch's lower-case test reads the page's printed casing of the name;
- **G3** — a name that grounds nowhere near its claim but whose head does, with the tail (1–6
  words, not starting/ending in a joiner) printed in a block of the item's window, gets the tail as
  its variant. A first version split ingredient lists ("sausage, cheddar jack & | pico de gallo")
  and was tightened before the final runs; both versions are in `decisions.md`.

Acceptance (pre-registered): invariance suite passes; pooled usable prices rise; no configuration
regresses beyond the band on accuracy / accepted-unmatched / wrong-accepted; every
leave-one-model-out fold ≥ 0; gold-row FR and injected catch not worse.

### harness-g acceptance on DEV (pooled usable-pair change; regressions beyond the band; LOMO)

| Change set | Pooled Δ usable pairs | Configs regressing | LOMO folds failing |
|---|---:|---|---|
| G1 | +1 | q25-7b ('acc', 'wrong'); gemma4-e4b g-v24 ('acc', 'wrong'); q3-8b s-n1 ('acc', 'wrong') | none |
| G2 | +0 | none | q3-8b (-1) |
| G3 | +12 | none | q35-9b g-v24 (-1); q3-8b s-n1 (-1) |
| G1G2G3 | +12 | q25-7b ('acc', 'wrong'); gemma4-e4b g-v24 ('acc', 'wrong'); q3-8b s-n1 ('acc', 'wrong') | none |

### harness-g acceptance on FAST (pooled usable-pair change; regressions beyond the band; LOMO)

| Change set | Pooled Δ usable pairs | Configs regressing | LOMO folds failing |
|---|---:|---|---|
| G1 | +3 | gemma4-e4b s-s1 ('acc'); llama31-8b g-s1 ('unm'); llama31-8b g-v24 ('unm'); llama31-8b s-s1 ('unm'); llama31-8b s-v24 ('unm'); baseline Q4_0 g-s1 ('unm'); baseline Q4_0 s-s1 ('unm'); q3-4b-2507-qkm g-n1 ('unm'); q3-4b-2507-qkm g-s1 ('unm'); q3-4b-2507-qkm s-n1 ('unm'); q3-4b-2507-qkm s-s1 ('unm'); q3-4b-2507-qkm s-v24 ('unm'); q35-9b g-s1 ('acc'); q3-4b-2507-qkm g-v24 ('unm'); q3-8b ('unm') | none |
| G2 | +0 | baseline Q4_0 g-s1 ('acc'); baseline Q4_0 s-s1 ('acc') | none |
| G3 | -5 | phi35-mini g-v24 ('unm'); q3-8b g-n1 ('acc'); q3-8b s-n1 ('acc'); q25-7b ('acc', 'unm') | none |
| G1G2G3 | -2 | gemma3n-e4b s-n1 ('unm'); gemma4-e4b s-s1 ('acc'); llama31-8b g-s1 ('unm'); llama31-8b g-v24 ('unm'); llama31-8b s-s1 ('unm'); llama31-8b s-v24 ('unm'); phi35-mini g-v24 ('unm'); baseline Q4_0 g-s1 ('acc', 'unm'); baseline Q4_0 s-s1 ('acc', 'unm'); q3-4b-2507-qkm g-n1 ('unm'); q3-4b-2507-qkm g-s1 ('unm'); q3-4b-2507-qkm s-n1 ('unm'); q3-4b-2507-qkm s-s1 ('unm'); q3-4b-2507-qkm s-v24 ('unm'); q35-9b g-s1 ('acc'); q3-4b-2507-qkm g-v24 ('unm'); q25-7b ('acc', 'unm'); q3-8b ('unm') | none |

**Result: no change is accepted; the refit harness for TEST is the frozen v8 harness.** G3 came
closest (DEV +12 pairs, no regression, FR and catch unchanged) but two leave-one-model-out folds
were −1 pair; it was not iterated again against the same DEV guard. Gold-row FR on the 158-page pool:
1,180 / 11,212 frozen and under G2/G3 (G1: 1,181); injected catch 0.992 throughout. ADR-0017
proposes the invariance principle and this multi-model rule for future harness work; the map above
is the debt list.

## 4. Rounds

### F1: every candidate, default config (greedy, prompt v2.4), FAST (8 pages)

| Config | Pages | Raw usable | Raw recall | Raw price acc. | Unmatched/row | Copy | Schema/trunc. | Pipeline usable (v8) | Pipeline acc. (v8) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| q35-9b g-v24 | 8 | 0.876 | 0.891 | 0.911 | 0.144 | 0.980 | 0.000 | 0.801 | 0.996 |
| gemma4-e4b g-v24 | 8 | 0.847 | 0.891 | 0.951 | 0.265 | 0.946 | 0.000 | 0.798 | 0.958 |
| q35-4b | 8 | 0.779 | 0.810 | 0.947 | 0.279 | 0.870 | 0.000 | 0.707 | 0.991 |
| gemma3n-e4b g-v24 | 8 | 0.772 | 0.916 | 0.919 | 0.438 | 0.957 | 0.000 | 0.658 | 0.953 |
| baseline Q4_0 rep A (g-v24) | 8 | 0.765 | 0.825 | 0.893 | 0.169 | 0.984 | 0.000 | 0.726 | 0.982 |
| q3-8b | 8 | 0.762 | 0.854 | 0.873 | 0.323 | 1.000 | 0.000 | 0.691 | 0.947 |
| baseline Q4_0 rep B (g-v24) | 8 | 0.749 | 0.825 | 0.890 | 0.178 | 0.984 | 0.000 | 0.723 | 0.982 |
| q25-7b | 8 | 0.749 | 0.825 | 0.670 | 0.225 | 0.859 | 0.071 | 0.730 | 0.970 |
| q3-4b-2507-qkm g-v24 | 8 | 0.720 | 0.785 | 0.937 | 0.235 | 0.972 | 0.000 | 0.681 | 0.986 |
| llama31-8b g-v24 | 8 | 0.707 | 0.788 | 0.966 | 0.552 | 0.906 | 0.036 | 0.622 | 1.000 |
| gemma3-4b g-v24 | 8 | 0.668 | 0.785 | 0.924 | 0.460 | 0.951 | 0.000 | 0.619 | 0.995 |
| smollm3-3b g-v24 | 8 | 0.658 | 0.755 | 0.883 | 0.374 | 0.746 | 0.393 | 0.622 | 0.992 |
| phi35-mini g-v24 | 8 | 0.638 | 0.752 | 0.897 | 0.431 | 0.794 | 0.000 | 0.573 | 0.994 |
| q3-4b-hybrid g-v24 | 8 | 0.625 | 0.712 | 0.854 | 0.525 | 0.987 | 0.000 | 0.596 | 0.989 |
| q35-2b | 8 | 0.534 | 0.661 | 0.817 | 0.548 | 0.988 | 0.000 | 0.410 | 0.992 |
| llama32-3b g-v24 | 8 | 0.502 | 0.639 | 0.839 | 0.582 | 0.827 | 0.000 | 0.495 | 0.931 |
| gemma4-e2b g-v24 | 8 | 0.436 | 0.821 | 0.820 | 0.552 | 0.856 | 0.000 | 0.573 | 0.978 |

### F2 configuration menu (FAST, raw usable prices; best per model in bold)

| Model | g-v24 | g-n1 | g-s1 | s-v24 | s-n1 | s-s1 |
|---|---:|---:|---:|---:|---:|---:|
| baseline Q4_0 | 0.757 | 0.730 | 0.655 | **0.762** | 0.736 | 0.691 |
| gemma4-e4b | 0.847 | **0.876** | 0.853 | 0.863 | 0.808 | 0.857 |
| q35-4b | 0.779 | **0.857** | 0.749 | 0.739 | 0.808 | 0.668 |
| gemma3n-e4b | **0.772** | 0.739 | 0.717 | 0.759 | 0.759 | 0.743 |
| q3-4b-2507-qkm | 0.720 | 0.743 | 0.733 | 0.730 | **0.756** | 0.752 |
| q35-9b | **0.876** | 0.866 | 0.837 | 0.811 | 0.801 | 0.827 |
| q3-8b | 0.762 | 0.824 | 0.821 | 0.792 | **0.844** | 0.765 |
| llama31-8b | 0.707 | 0.655† | 0.723† | 0.664 | 0.746 | **0.749** |

† schema/truncation > 10 % (config invalid). Baseline g-v24 = mean of replicates A 0.765 and B 0.749.

N1 (neutral prompt) lifts other families and lowers the baseline: prompt v2.4 is fitted to Qwen3-4B
(the single largest harness-fit effect found). FAST's 8 pages are too few to pick configurations
alone — DEV reversed Gemma-4-E4B's FAST choice (g-n1 → g-v24).

### D: DEV (15 pages)

| Config | Pages | Raw usable | Raw recall | Raw price acc. | Unmatched/row | Copy | Schema/trunc. | Pipeline usable (v8) | Pipeline acc. (v8) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gemma4-e4b g-v24 | 15 | 0.897 | 0.952 | 0.935 | 0.174 | 0.979 | 0.000 | 0.839 | 0.983 |
| q35-9b g-v24 | 15 | 0.874 | 0.887 | 0.918 | 0.138 | 0.989 | 0.000 | 0.820 | 0.989 |
| gemma4-e4b g-n1 | 15 | 0.858 | 0.916 | 0.978 | 0.206 | 0.970 | 0.000 | 0.844 | 0.994 |
| q3-8b s-n1 | 15 | 0.855 | 0.931 | 0.813 | 0.228 | 0.976 | 0.012 | 0.814 | 0.989 |
| q3-8b | 15 | 0.829 | 0.896 | 0.820 | 0.237 | 0.997 | 0.012 | 0.788 | 0.979 |
| baseline Q4_0 s-v24 | 15 | 0.821 | 0.883 | 0.935 | 0.191 | 0.981 | 0.000 | 0.815 | 0.988 |
| baseline Q4_0 rep B (g-v24) | 15 | 0.818 | 0.882 | 0.933 | 0.189 | 0.985 | 0.000 | 0.811 | 0.988 |
| q25-7b | 15 | 0.814 | 0.779 | 0.798 | 0.188 | 0.917 | 0.049 | 0.781 | 0.983 |
| q3-4b-2507-qkm s-n1 | 15 | 0.812 | 0.879 | 0.916 | 0.188 | 0.984 | 0.000 | 0.797 | 0.985 |
| gemma3n-e4b g-v24 | 15 | 0.806 | 0.916 | 0.896 | 0.352 | 0.961 | 0.000 | 0.743 | 0.978 |
| baseline Q4_0 rep A (g-v24) | 15 | 0.795 | 0.879 | 0.929 | 0.175 | 0.988 | 0.012 | 0.794 | 0.986 |
| llama31-8b s-s1 | 15 | 0.794 | 0.884 | 0.911 | 0.258 | 0.981 | 0.012 | 0.746 | 0.984 |
| q3-4b-2507-qkm g-v24 | 15 | 0.789 | 0.875 | 0.940 | 0.196 | 0.985 | 0.000 | 0.779 | 0.984 |
| llama31-8b g-v24 | 15 | 0.784 | 0.855 | 0.840 | 0.353 | 0.937 | 0.085 | 0.749 | 0.977 |
| q35-4b | 15 | 0.780 | 0.812 | 0.910 | 0.211 | 0.941 | 0.000 | 0.732 | 0.989 |
| q35-4b g-n1 | 15 | 0.776 | 0.752 | 0.948 | 0.174 | 0.985 | 0.000 | 0.750 | 0.987 |
| q35-2b | 15 | 0.513 | 0.637 | 0.703 | 0.431 | 0.975 | 0.049 | 0.446 | 0.971 |

### V: VAL (15 pages)

| Config | Pages | Raw usable | Raw recall | Raw price acc. | Unmatched/row | Copy | Schema/trunc. | Pipeline usable (v8) | Pipeline acc. (v8) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| q3-8b | 15 | 0.890 | 0.907 | 0.913 | 0.199 | 0.999 | 0.050 | 0.827 | 0.995 |
| q35-9b g-v24 | 15 | 0.880 | 0.921 | 0.939 | 0.166 | 0.982 | 0.008 | 0.833 | 0.997 |
| gemma4-e4b g-v24 | 15 | 0.880 | 0.949 | 0.928 | 0.311 | 0.931 | 0.008 | 0.800 | 0.995 |
| q3-8b s-n1 | 15 | 0.870 | 0.888 | 0.938 | 0.259 | 0.998 | 0.008 | 0.804 | 0.997 |
| q3-4b-2507-qkm s-n1 | 15 | 0.833 | 0.871 | 0.973 | 0.216 | 0.983 | 0.000 | 0.781 | 0.996 |
| llama31-8b s-s1 | 15 | 0.829 | 0.894 | 0.927 | 0.255 | 0.968 | 0.033 | 0.752 | 0.988 |
| gemma3n-e4b g-v24 | 15 | 0.802 | 0.892 | 0.918 | 0.425 | 0.980 | 0.008 | 0.719 | 0.990 |
| q3-4b-2507-qkm g-v24 | 15 | 0.800 | 0.865 | 0.962 | 0.218 | 0.986 | 0.000 | 0.768 | 0.998 |
| baseline Q4_0 rep B (g-v24) | 15 | 0.779 | 0.839 | 0.954 | 0.211 | 0.989 | 0.000 | 0.749 | 0.995 |
| baseline Q4_0 rep A (g-v24) | 15 | 0.775 | 0.827 | 0.955 | 0.232 | 0.990 | 0.000 | 0.754 | 0.995 |
| baseline Q4_0 s-v24 | 15 | 0.770 | 0.844 | 0.959 | 0.239 | 0.995 | 0.000 | 0.747 | 0.995 |
| q25-7b | 15 | 0.769 | 0.845 | 0.918 | 0.228 | 0.988 | 0.017 | 0.708 | 0.988 |

Finalists: **B4** Gemma-4-E4B g-v24 and Qwen3-4B-2507 Q4_K_M s-n1 (plus the baseline twice and its
best DEV configuration s-v24); **B8** Qwen3.5-9B g-v24 and Qwen3-8B s-n1. Pruned at D: Qwen3.5-4B
(best 0.780). Out at V: Gemma-3n-E4B (0.802), Llama-3.1-8B (0.829).

## 5. TEST (45 pages, scored once)

### TEST clear-winner rule (45 pages; baselines baseline Q4_0 g-v24, baseline Q4_0 g-v24-b)

Noise band (|rep A − rep B|): raw_accuracy 0.0053, raw_unmatched_rate 0.0004, pipe:usable_prices 0.0136, raw_usable 0.0090

**B4: inconclusive**

| Entry | Raw usable | Raw acc. | Unmatched | Schema/trunc. | Pipeline usable | Pipeline acc. | Pipeline FR | C1 | C2 | C3 | C4 |
|---|---:|---:|---:|---:|---:|---:|---:|:-:|:-:|:-:|:-:|
| gemma4-e4b g-v24 | 0.854 | 0.972 | 0.272 | 0.000 | 0.801 | 0.988 | 0.169 | ✓ | ✗ | ✓ | ✗ |
| q3-4b-2507-qkm s-n1 | 0.799 | 0.959 | 0.220 | 0.000 | 0.784 | 0.989 | 0.072 | ✗ | ✗ | ✓ | ✗ |
| baseline Q4_0 s-v24 | 0.786 | 0.968 | 0.235 | 0.003 | 0.778 | 0.991 | 0.078 | ✗ | ✓ | ✓ | ✗ |

Paired raw-usable differences (entry − comparator), 95 % page-bootstrap CI, sets with a positive difference:

| Entry | Comparator | Δ | 95 % CI | Sets + |
|---|---|---:|---|---:|
| gemma4-e4b g-v24 | q3-4b-2507-qkm s-n1 | +0.055 | [+0.017, +0.098] | 6/7 |
| gemma4-e4b g-v24 | baseline Q4_0 s-v24 | +0.068 | [+0.035, +0.099] | 7/7 |
| gemma4-e4b g-v24 | baseline Q4_0 g-v24 | +0.071 | [+0.040, +0.108] | 7/7 |
| gemma4-e4b g-v24 | baseline Q4_0 g-v24-b | +0.062 | [+0.030, +0.095] | 7/7 |
| q3-4b-2507-qkm s-n1 | gemma4-e4b g-v24 | -0.055 | [-0.098, -0.017] | 1/7 |
| q3-4b-2507-qkm s-n1 | baseline Q4_0 s-v24 | +0.012 | [-0.020, +0.042] | 5/7 |
| q3-4b-2507-qkm s-n1 | baseline Q4_0 g-v24 | +0.015 | [-0.018, +0.052] | 5/7 |
| q3-4b-2507-qkm s-n1 | baseline Q4_0 g-v24-b | +0.006 | [-0.019, +0.033] | 5/7 |
| baseline Q4_0 s-v24 | gemma4-e4b g-v24 | -0.068 | [-0.099, -0.035] | 0/7 |
| baseline Q4_0 s-v24 | q3-4b-2507-qkm s-n1 | -0.012 | [-0.042, +0.020] | 2/7 |
| baseline Q4_0 s-v24 | baseline Q4_0 g-v24 | +0.003 | [-0.011, +0.024] | 4/7 |
| baseline Q4_0 s-v24 | baseline Q4_0 g-v24-b | -0.006 | [-0.020, +0.011] | 4/7 |

Pipeline (refit = frozen v8) usable vs baselines:

| Entry | Baseline | Δ | 95 % CI |
|---|---|---:|---|
| gemma4-e4b g-v24 | baseline Q4_0 g-v24 | +0.035 | [-0.004, +0.077] |
| gemma4-e4b g-v24 | baseline Q4_0 g-v24-b | +0.022 | [-0.018, +0.059] |
| q3-4b-2507-qkm s-n1 | baseline Q4_0 g-v24 | +0.019 | [-0.010, +0.055] |
| q3-4b-2507-qkm s-n1 | baseline Q4_0 g-v24-b | +0.005 | [-0.018, +0.033] |
| baseline Q4_0 s-v24 | baseline Q4_0 g-v24 | +0.013 | [-0.005, +0.037] |
| baseline Q4_0 s-v24 | baseline Q4_0 g-v24-b | -0.001 | [-0.020, +0.023] |

**B8: inconclusive**

| Entry | Raw usable | Raw acc. | Unmatched | Schema/trunc. | Pipeline usable | Pipeline acc. | Pipeline FR | C1 | C2 | C3 | C4 |
|---|---:|---:|---:|---:|---:|---:|---:|:-:|:-:|:-:|:-:|
| q35-9b g-v24 | 0.863 | 0.957 | 0.150 | 0.000 | 0.837 | 0.989 | 0.053 | ✗ | ✗ | ✓ | ✓ |
| q3-8b s-n1 | 0.836 | 0.905 | 0.244 | 0.005 | 0.806 | 0.988 | 0.105 | ✗ | ✗ | ✓ | ✓ |

Paired raw-usable differences (entry − comparator), 95 % page-bootstrap CI, sets with a positive difference:

| Entry | Comparator | Δ | 95 % CI | Sets + |
|---|---|---:|---|---:|
| q35-9b g-v24 | q3-8b s-n1 | +0.028 | [-0.011, +0.068] | 4/7 |
| q35-9b g-v24 | baseline Q4_0 g-v24 | +0.080 | [+0.049, +0.117] | 7/7 |
| q35-9b g-v24 | baseline Q4_0 g-v24-b | +0.071 | [+0.039, +0.107] | 6/7 |
| q3-8b s-n1 | q35-9b g-v24 | -0.028 | [-0.068, +0.011] | 3/7 |
| q3-8b s-n1 | baseline Q4_0 g-v24 | +0.053 | [+0.020, +0.096] | 6/7 |
| q3-8b s-n1 | baseline Q4_0 g-v24-b | +0.044 | [+0.019, +0.077] | 6/7 |

Pipeline (refit = frozen v8) usable vs baselines:

| Entry | Baseline | Δ | 95 % CI |
|---|---|---:|---|
| q35-9b g-v24 | baseline Q4_0 g-v24 | +0.072 | [+0.043, +0.109] |
| q35-9b g-v24 | baseline Q4_0 g-v24-b | +0.058 | [+0.029, +0.091] |
| q3-8b s-n1 | baseline Q4_0 g-v24 | +0.040 | [+0.002, +0.084] |
| q3-8b s-n1 | baseline Q4_0 g-v24-b | +0.026 | [-0.005, +0.061] |

**Reading B4.** Gemma-4-E4B is the only entry that separates (condition 1 holds against all four
comparators). It fails condition 2 on the unmatched rate: the band is the gap between two greedy
runs of the same model (0.0004), so any model with a different extraction style fails it unless
it emits no more unmatched rows than the baseline. It fails condition 4 narrowly. Both failures sit
where the harness matters: the frozen harness loses 183 of Gemma's 2,946 correct raw pairs (the
baseline loses 45–61) and accepts 512 rows matching no label. A VAL diagnostic
(`p0/unmatched-audit-val.txt`; TEST was not re-read) puts Gemma's extra unmatched rows on
page-printed names that match no label (248 vs 128–157), description-length names (107 vs 50–56)
and priced heading-like rows (77 vs 26–27), with 0 names absent from the page. The rule is not
relaxed: **inconclusive**, ranking Gemma-4-E4B > Q4_K_M s-n1 > baseline s-v24 ≈ baseline.

**Reading B8.** The GPU halted during Qwen3.5-9B's TEST pass (7 of 45 pages saved). After the owner
rebooted, the run resumed from page 8 (saved pages are skipped, nothing was rescored), and both B8
finalists completed all 45 pages before any B8 score was computed. B4 was evaluated again in the
same call and reproduced exactly.

Both 8B-class models are ahead of the baseline on raw usable prices, but neither beats the other,
so condition 1 fails. Both are also below the baseline on raw price accuracy (condition 2).

Qwen3.5-9B is the one entry in this screen that is ahead of the baseline through the frozen v8
pipeline as well (condition 4, both CIs above 0). The harness treats its output better than the
4B candidates': lower false-reject rate (0.053), fewer accepted rows matching no label (192).
Its cost is 8–9 more wrong-price accepts out of ~5,000 rows.

The rule is not relaxed: **inconclusive**, ranking Qwen3.5-9B > Qwen3-8B s-n1 > baseline.

## 6. Orange Pi: CPU speed and an NPU probe (context, not acceptance)

Owner-authorized during the session. Nothing in the deployed Compose project, `/usr/lib`, the
spike directory or production changed: CPU runs used isolated containers `p520-pi-*` (production
image `6257697a…`, production flags, context 12,288, A76 cores 4–7, loopback port behind an SSH
tunnel); the NPU used an isolated RKLLM **1.3.1** runtime in `~/p520-npu` (librkllmrt sha256
`f25e9b09…eb32c`) and a C++ probe compiled against the release header (`npu/probe.cpp`), which
sidesteps the 1.2.3 → 1.3.x ctypes ABI changes. Speed on 3 pages is indicative only.

### Orange Pi CPU speed context (3 pages / 9 chunks; production CPU image and flags, context 12,288)

| Model / config | Pages/h | Generated tok/s (2 slots) | Peak memory GiB | Wall s |
|---|---:|---:|---:|---:|
| gemma4-e4b g-n1 | 8.78 | 3.64 | 3.52 | 1229.9 |
| baseline Q4_0 g-v24 | 10.42 | 3.82 | 3.21 | 1036.1 |
| q3-4b-2507-qkm s-n1 | 9.11 | 3.33 | 3.6 | 1185.3 |
| q3-8b s-n1 | 5.21 | 2.23 | 6.42 | 2073.2 |
| q35-4b g-n1 | 8.89 | 4.26 | 3.79 | 1214.9 |
| q35-9b g-v24 | 5.59 | 2.23 | 6.38 | 1932.2 |

### NPU probe (baseline, runtime 1.3.1 isolated, spike W8A8_G128 artifact, single stream, greedy, no grammar)

Chunks 9; prefill 5491 tokens at 31.3 tok/s; decode 3678 tokens at 2.49 tok/s; wall 1652 s (6.5 pages/h on these 3 pages); peak RSS 6090 MB; truncated 0/9.

### NPU3: NPU W8A8 baseline vs GPU Q4 on the 3 probe pages

| Config | Pages | Raw usable | Raw recall | Raw price acc. | Unmatched/row | Copy | Schema/trunc. | Pipeline usable (v8) | Pipeline acc. (v8) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| gemma4-e4b g-v24 | 3 | 0.890 | 0.928 | 0.965 | 0.338 | 0.981 | 0.000 | 0.789 | 1.000 |
| baseline Q4_0 rep B (g-v24) | 3 | 0.844 | 0.952 | 0.887 | 0.135 | 1.000 | 0.000 | 0.734 | 0.976 |
| baseline Q4_0 rep A (g-v24) | 3 | 0.844 | 0.952 | 0.887 | 0.135 | 1.000 | 0.000 | 0.734 | 0.976 |
| npu-q3-4b-2507-spike v24 | 3 | 0.761 | 0.831 | 0.897 | 0.213 | 1.000 | 0.000 | 0.624 | 0.986 |
| q3-4b-2507-qkm g-v24 | 3 | 0.761 | 0.843 | 0.924 | 0.303 | 0.961 | 0.000 | 0.642 | 1.000 |

The NPU probe used the spike's existing Qwen3-4B-2507 W8A8_G128 artifact (toolkit 1.2.1); runtime
1.3.1 loads it. Without a grammar it produced valid JSON on 9/9 chunks; on these 3 pages its raw
usable prices were 0.761 against GPU Q4_0's 0.844 — a hint of a W8A8 quality cost to measure
properly. A fresh 1.3.1 W8A8 conversion (`npu/convert.py`, official generic calibration set, bf16
load, 15 GB cgroup cap) ran at ~6 min per layer on this laptop (~3.7 h for a 4B) and slowed the
GPU screen, so it was stopped; per the owner, the NPU is only worth it for an NPU-specific model,
and the Pi CPU is the comparison for the rest.

## 7. Limitations

- **TEST pages were in v8/[5b] tuning data.** The harness-free primary metrics are the mitigation;
  the secondary (pipeline) numbers on TEST favour the baseline the harness was tuned on.
- **Prompt fit.** v2.4 was written against the baseline's errors; the menu (N1, S1) only partly
  neutralises that, and only three prompts were tried.
- **Small DEV/VAL** (15 pages each) and an 8-page FAST tier; configuration choices made on them are
  noisy (FAST and DEV disagreed for Gemma-4-E4B). TEST (45 pages) is the only larger sample.
- **GPU Q4 is not W8A8**, and GPU speed says nothing about the Pi. The one NPU data point (3 pages)
  suggests W8A8 costs quality; it is not a measurement.
- **Sampling configurations** (s-*) are seeded but not bit-reproducible across batch compositions.
- **"E" models** sit in B4 by effective parameters; their RKLLM memory/speed on RK3588 is
  benchmarked only for E2B. Gemma-4-E4B's Pi CPU speed (8.8 pages/h vs 10.4) is the only direct
  evidence of its cost.
- **Unmatched rows are not proven hallucinations** (some are real items missing from labels, or
  headings emitted as items).

## 8. Execution notes

- GPU: RTX 3070 Laptop 8 GB, pinned image b11176, flags identical for every model (plus `-lv 4`
  log verbosity as in P5-19). GPU time 02:16–10:00Z = 7.7 h of the 12 h budget (projection:
`projection.md`). **Thermal guard (93/78 °C): 0 pauses.** At 10:00Z llama-server aborted during
the Qwen3.5-9B TEST pass with `CUDA error: unspecified launch failure`; the kernel logged NVRM
`NV_ERR_GPU_IN_FULLCHIP_RESET` assertions and nvidia-smi reports `GPU Recovery Action: Reset` —
the P5-19 failure mode, again at 89 °C, below the guard's pause threshold. Work stopped, the guard
was stopped by PID, no container was left paused or running. The owner rebooted; the GPU came
back healthy (Recovery Action None). B8 TEST resumed at 14:43Z with the guard restarted (0
pauses) and finished at 15:51Z. Total GPU time 8.8 h.
- A first F1 launch excluded every model because the offload check needs `-lv 4`; those 4 records
  are kept in `runs/ledger-offload-regex-bug.jsonl` and were re-run. The Gemma-2-9B load failure
  first waited the full 600 s readiness timeout; the runner now stops waiting when the container
  exits.
- No tracked pipeline code, `config/models.yaml`, labels, held-out data, migrations, infra or
  deployment changed. Only these two documents are repo files; both are uncommitted.

## 9. For the owner

1. **B4 decision.** The frozen rule says inconclusive, so the baseline stays. Recommendation:
   treat Gemma-4-E4B as the lead candidate for a targeted follow-up rather than adopting it.
   The follow-up would cover:
   - why its unmatched rows are unlabelled (an options / add-on label convention, or over-extraction to curb with a generic rule);
   - harness work under ADR-0017 aimed at its 0.169 real-output false-reject rate;
   - an RK3588 check of the E4B variant;
   - then a fresh §8 held-out draw.
2. **B8 / escalation.** Qwen3.5-9B is the best-supported candidate for a stronger fallback model
   on hard pages: ahead of the baseline even through today's harness, and with fewer unmatched
   accepts. It has three open issues:
   - It does not separate from Qwen3-8B.
   - Its raw accuracy is lower, which shows up as more wrong-price accepts.
   - It costs about 2× on the Pi CPU. On the NPU, the 9B checkpoint has no RK3588 benchmark;
     Qwen3.5 is supported from RKLLM 1.3.0.

   P5-19 showed the label-free router is the hard part: its baseline-coverage < 0.70 trigger routed
   43 % of pages, against a 30 % cap. Recommendation for the next session:
   - design and freeze a label-free escalation trigger on the tuning splits;
   - measure routed share and the gain on routed pages for Qwen3.5-9B;
   - only then a held-out §8 check.

   Thermal: both GPU halts (P5-19, P5-20) happened at 89 °C, below the 93 °C pause, so consider
   a lower pause threshold for future runs.
3. **Review ADR-0017** (Proposed). Nothing is built.
4. **Prompt.** N1 lowers the baseline (FAST 0.730 vs 0.757), so v2.4 stays for Qwen3-4B. For
   other models, N1 or S1 is a per-model configuration choice under ADR-0017 item 3.
5. **Ordering against P5-18** (paused v9 [5b] tuning). Its constants depend on the chosen model.
   Recommendation: settle item 1 first.
6. **Licence:** MiniCPM3/4 needs a registration questionnaire before it can be screened.
7. **NPU prerequisites for any winner:**
   - a pinned W8A8 conversion with toolkit 1.3.1 (calibration-set choice recorded; about 3.7 h for a 4B on this laptop's CPU, so a free machine is better);
   - the 1.3.x ABI, with `npu/probe.cpp` as the reference (callback struct, `RKLLMParam`, input union, per-run `max_new_tokens`);
   - schema and truncation without GBNF (baseline: 0/9);
   - tokens/s on the frozen prompt (baseline: prefill ~33 tok/s, decode ~2.5 tok/s);
   - CPU+NPU contention (not measured);
   - W8A8 quality against GPU Q4 on a real sample (the 3-page hint: 0.761 vs 0.844).

   Per the owner, the NPU only pays off with an NPU-specific model; the Pi CPU numbers above are the comparison for the rest.
8. **Pi cleanup** when done: `ssh orangepi@192.168.1.219 'rm -rf ~/p520-pi ~/p520-npu'`. These
   hold ~25 GB of model copies and the isolated runtime; nothing else on the Pi changed.

## Archive (P5-22, 2026-10-19)

The gitignored scratch `var/menu-eval/bracket-screen/` is archived in `var/archive/2026-10-p5-19-21/` (main checkout, gitignored):

- manifest `p5-20-bracket-screen.manifest.json`, sha256 `84dd2649f7592a3064a012d0d609fb53974cb7dfa0dc83072966d97990509d08` (path, size and sha256 of every
  archived file; excluded model weights and vendor binaries with their size, sha256 and
  publisher pin; excluded environments and caches with file counts);
- tarball `p5-20-bracket-screen.tar.zst`, sha256 `5f8632b39d2615206d353e1378c07e919cf161c10a5fd145b95ba748d1d7f2a2`.

Model GGUFs, HF checkpoints, Python environments, caches and RKLLM vendor binaries are not
in the tarball; `SHA256SUMS` in the same directory lists both files and the archiving
scripts.

The NPU `.rkllm` artifacts were only on the Pi (`~/p520-npu`), not in this scratch.
