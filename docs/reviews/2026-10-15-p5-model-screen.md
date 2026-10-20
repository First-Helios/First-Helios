# P5-19 GPU extraction-model quality screen — draft

**Current scope: the owner revised this to a15-page triage screen with a nested30-page
follow-up before any candidate scoring. See the protocol amendment below. The original
218-page plan is retained as superseded history; no full-cohort result is claimed.**

Owner review draft; committed unchanged in the P5-22 archive. This is tuning evidence, not a held-out verdict,
NPU compatibility result, W8A8 quality result, or production speed measurement.

## Frozen protocol and criterion (written before extraction or candidate scoring)

Frozen 2026-10-15. Worktree `worktree-p5-19-model-screen`, pipeline commit
`b4b0e2e`. Every run uses
`<checkpoint+quant>;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`.
No pipeline, manifest, deployment, infrastructure or Pi changes. No held-out draw
or held-out label access. The seven previously scored sets are tuning data.

Reuse P5-18 `p18_common.py` and `splits.json`: spike 33, P5-5 10, P5-8 35,
P5-10 35, P5-12 35, P5-14 35, P5-16 35 = 218 pages. Primary labels are
owner-confirmed `labels-v9` (107 modifiers, six inferred variants removed);
original labels are reported separately. Inputs and both label versions are copied
under `var/menu-eval/model-screen/`, with a SHA256 cohort manifest. No saved
v6c/v6/v7/v8 extraction is a baseline.

Identical across models: page input, segmentation, prompt content, chunking,
GBNF grammar, sparse retries, output-budget policy, repair/stitch, validator+[5b],
matching rules and scorer. Use the unmodified `evaluate extract` client with two
requests in flight. It serves whatever GGUF the server loads; identify it independently.
Greedy `temperature=0`, each model's embedded Jinja chat template with
`enable_thinking=false`. Preserve each rendered prompt and inspect raw outputs:
no generated thinking, duplicated answer or incomplete JSON in the three-page smoke.
Qwen3.5's recommended sampling is deliberately not adopted in this fixed greedy screen.
Record template hashes and full rendering, checkpoint/GGUF revision, file SHA256,
quant, backend build/digest, context, slots and pipeline commit in run metadata.

Pinned CUDA image `ghcr.io/ggml-org/llama.cpp:server-cuda-b11176`, digest
`sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`,
llama.cpp build 11176 / `f805c57a2`. All layers on GPU (`-ngl 99`), flash attention
OFF, f16 K/V, `-np 2 -c 12288` (6144 per slot), four CPU threads, RAM prompt cache
disabled. Never shrink context or output budget. Check actual tokenizer counts
against each rendered request plus its full output cap; the existing cap's
characters/2 rule is a heuristic, not a tokenizer. Prove `qwen35` loads before
planning around that architecture. Measure total/free/peak VRAM including KV and
runtime; keep unrelated GPU processes. Four-billion and larger models run sequentially.
Smaller concurrent workers only if measured headroom supports them; retry OOM sequentially.

Smoke pages, chosen by sorted IDs without candidate scores: spike `04cea9ccc03e`,
P5-12 `00f349e12f5b`, P5-16 `05273895b4e2`. Measure pages/hour and project full-plan
GPU hours after smoke, before full extraction; these are scheduling estimates only.
Baseline Qwen3-4B-Instruct-2507 Q4_0 runs twice over all 218 pages. Also screen
its Q4_K_M quant, Qwen3.5-2B Q4_K_M and Qwen3.5-4B Q4_K_M. Optional 1.7B
control omitted. Baseline attribution on all sets must finish before any candidate
quality score is inspected. Only if no <=4B configuration clears the criterion,
continue to Qwen3-8B non-thinking and Qwen2.5-7B-Instruct; Qwen3.5-9B requires a
primary-source RK3588 conversion path. Any CPU offload is explicit.

Worthwhile gain (pre-registered):

1. Pooled usable prices OR kept item recall must improve beyond the absolute
   baseline A/B gap for that metric, with a paired page-clustered bootstrap 95%
   interval excluding zero, and positive gains on at least five of seven sets.
   Compare to baseline A, confirm against baseline B; report both and their gap.
   Bootstrap 10,000 paired page resamples, seed 20261015, difference of pooled
   ratios, preserving all rows of each sampled page. Show per-set intervals too.
2. Raw item recall >=0.85 and accepted price accuracy >=0.98; accuracy cannot
   deteriorate beyond its baseline A/B gap. Report per-set bars and regressions;
   a previously passing set must not cross a §8 bar.
3. No increase in pooled accepted priced rows matching no label or matched real
   wrong-price rows accepted, against either baseline replicate; report counts,
   rates and per-set changes. Unmatched does not automatically mean hallucinated.
4. No worse exact-name copy fidelity: raw pre-repair name strings that occur
   verbatim in their claimed input block / all raw rows (strict case and punctuation),
   and report occurrence anywhere on the page as a diagnostic. No matching-rule changes.
5. Real-output false rejects and catch cannot worsen beyond their respective
   baseline A/B gaps. Report truncation, pre-repair schema failure and retry rates.

Inconclusive is allowed. Gold-row FR and injected-corruption catch run on the same
gold rows and are invariant across models; record them without claiming model gain.
The pooled gold-row FR near 0.095 versus the next-draw target near 0.05 remains an
independent blocker. GPU speed has no place in acceptance.

If Stage 2 is required, simulate routing without new model calls. Pre-set label-free
router: coverage (baseline accepted priced rows / printed prices) <0.7; report
alternative fixed flags (downgrade share >0.30, unpriced share >0.50, any sparse
retry, chunk count >=10) diagnostically, without tuning thresholds against labels.
For the pre-set router report both unconditional substitution and the historical
rule keeping the answer with more accepted priced rows (ties retain baseline).
Oracle routing is a labelled ceiling only: choose the higher per-page usable-price
count, ties by kept recall then baseline. Report routed share, tokens generated on
routed pages and projected Pi decode hours = tokens / 1.8 / 3600, excluding prefill,
conversion, contention and overhead. Escalation must meet the same quality criterion
and route roughly <=20–30% of pages; the second extractor is never acceptance authority.

Pre-extraction budget check found the production-sized 4096-token slot too small:
maximum rendered retry prompt plus full cap = 4679 tokens (P5-14 `77796540a06c`).
Before any generation, expand every model to 6144 tokens per slot, identically;
retain every chunk and full cap. Initial 8192-total context made no extractions.

## Inventory and results

GPU inventory at start: NVIDIA GeForce RTX 3070 Laptop GPU, 8192 MiB total,
328 MiB used and 7513 MiB free (driver-reserved memory accounts for the remainder),
NVIDIA driver 580.159.03 / CUDA 13.0. Existing processes were Steam (5 MiB), two
Steam web helpers (40/64 MiB) and cosmic-monitor (156 MiB); retained. No existing
model containers. Runtime image/build/digest as above.

The baseline's 3-page smoke completed in 48.03 s: **224.86 pages/hour**. All 17
chunks complete JSON, no generated thinking or duplicate JSON answer. Log proves
37/37 GPU layers, flash attention disabled, CUDA model 2260 MiB + KV 1728 MiB +
compute 426 MiB; observed total GPU use 4962 MiB including desktop and overhead.
1853 chunks in full cohort versus 17 in smoke. Initial Stage 1 projection, BEFORE
full runs: five full218-page passes = **4.85 GPU hours** by page count or **7.27
GPU hours** by chunk count, plus smoke/setup/scoring; thermals and difficult-page
mix can change this. Stage 2, if needed, adds at least two full passes and is
re-estimated after its own smoke. No throughput acceptance bar.

Qwen3.5-2B successfully loads `qwen35` in the pinned build: 25/25 layers on GPU,
flash attention disabled, model1211 MiB + KV144 MiB + recurrent state38.53 MiB +
compute130 MiB; observed GPU use2056 MiB. Its three-page smoke took70.39 s,
153.43 pages/hour (1.42 hours/pass by pages,2.13 by chunks). Rendered prompt
ends with the closed empty thinking block. Raw completion envelopes are retained;
no generated thinking observed. **Smoke schema check found output-budget truncation**,
so complete JSON cannot be confirmed for this candidate. This is a quality outcome:
keep the frozen budget, retain truncated-row recovery, evaluate the entire cohort,
and report schema/truncation rates. No template/prompt/decoding tuning follows it.

Scratch and resumable outputs:
`var/menu-eval/model-screen/`. The recommendation is in the results and reviewer
sections below (provisional: retain the baseline).

## Pinned artifact inventory

| Run | GGUF repo | Revision | File | SHA256 |
|---|---|---|---|---|
| baseline-a | unsloth/Qwen3-4B-Instruct-2507-GGUF | a06e946bb6b655725eafa393f4a9745d460374c9 | Qwen3-4B-Instruct-2507-Q4_0.gguf | e0ba675d86ab277c61701c6793659b2ae801d95e3be791464c321e6fbf613be2 |
| baseline-qkm | unsloth/Qwen3-4B-Instruct-2507-GGUF | a06e946bb6b655725eafa393f4a9745d460374c9 | Qwen3-4B-Instruct-2507-Q4_K_M.gguf | 3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597 |
| q35-2b | unsloth/Qwen3.5-2B-GGUF | f6d5376be1edb4d416d56da11e5397a961aca8ae | Qwen3.5-2B-Q4_K_M.gguf | aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223 |
| q35-4b | unsloth/Qwen3.5-4B-GGUF | e87f176479d0855a907a41277aca2f8ee7a09523 | Qwen3.5-4B-Q4_K_M.gguf | 00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4 |

Existing spike8B file: `Qwen3-8B-Q4_K_M.gguf`,5027783488 bytes,
SHA256 `d98cdcbd03e17ce47681435b5150e34c1417f50b5c0019dd560e4882c5745785`.
Its publisher/revision must be verified before use; current unsloth bytes differ.

Official checkpoint revisions observed (these are reference pins; the GGUF publisher
does not pin its source checkpoint commit, so source-weight identity is unverified):

| Checkpoint | Observed revision |
|---|---|
| Qwen/Qwen2.5-7B-Instruct | a09a35458c702b33eeacc393d103063234e8bc28 |
| Qwen/Qwen3-4B-Instruct-2507 | cdbee75f17c01a7cc42f958dc650907174af0554 |
| Qwen/Qwen3-8B | b968826d9c46dd6066d109eabc6255188de91218 |
| Qwen/Qwen3.5-2B | 15852e8c16360a2fea060d615a32b45270f8a8fc |
| Qwen/Qwen3.5-4B | 851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a |

## Primary-source NPU compatibility review

Verified 2026-10-15. Research only; no Pi, deployment, infra, or held-out labels accessed.

## Release history and family support

The owner's release dates are correct. GitHub release API timestamps downloaded to `/tmp/p519-rkllm-releases.json` are:

| Release | Published UTC | Relevant addition |
|---|---|---|
| [1.2.1](https://github.com/airockchip/rknn-llm/releases/tag/release-v1.2.1) | 2025-06-25 12:40:29 | Qwen3; thinking-mode template selection |
| [1.2.3](https://github.com/airockchip/rknn-llm/releases/tag/release-v1.2.3) | 2025-11-24 07:04:28 | Existing owner's runtime |
| [1.3.0](https://github.com/airockchip/rknn-llm/releases/tag/release-v1.3.0) | 2026-06-17 09:43:42 | Qwen3.5; callback/interface changes |
| [1.3.1](https://github.com/airockchip/rknn-llm/releases/tag/release-v1.3.1) | 2026-09-29 06:44:17 | Latest; linear-attention cache reuse and fixes |

The [official supported-model list](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/README.md) lists Qwen2/Qwen2.5/Qwen3/Qwen3.5 and RK3588. The [official benchmark](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/benchmark.md) includes Qwen2.5-1.5B W8A8 on RK3588, so Qwen2.5 family support is explicit. This establishes a family conversion path for Qwen2.5-7B-Instruct; it does not validate that checkpoint's resulting W8A8 extraction quality.

## Minimum driver and RK3588 quantization

The [official English SDK 1.3.1 guide](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/doc/Rockchip_RKLLM_SDK_EN_1.3.1.pdf), PDF page 14, instructs upgrading when rknpu is below 0.9.8. The owner's reported rknpu 0.9.8 therefore meets the documented minimum; The owner subsequently authorized runtime upgrades in an isolated test directory; production remains unchanged. An actual compatibility check is still required. The guide is downloaded at `/tmp/p519-rkllm-guide.pdf`, text at `/tmp/p519-rkllm-guide.txt`.

PDF page 19 restricts RK3588 to W8A8 and grouped W8A8 g128/g256/g512. W4A16 examples for other Rockchip chips must not be described as RK3588 support. GPU Q4_K_M is a separate artifact and cannot establish W8A8 quality.

## Qwen3.5 conversion path

The [official pinned benchmark](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/benchmark.md) lists Qwen3.5-0.8B, -2B and -4B with W8A8 on RK3588. This is strong primary evidence for a real 2B/4B conversion-and-runtime path on the correct SoC. Its short-context speed numbers are not the owner's menu prompt speed and are not acceptance evidence.

The [official exporter](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/examples/multimodal_model_demo/export/export_rkllm.py) accepts a Hugging Face model path, target rk3588, 3 NPU cores, W8A8, then load_huggingface/build/export_rkllm. The [text API exporter](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/examples/rkllm_api_demo/export/export_rkllm.py) shows W8A8 normal-algorithm calibration. Text-only menu extraction should validate the language branch and its chat template; a vision encoder is not needed by this workload.

No checkpoint-specific primary RKLLM/RK3588 evidence for Qwen3.5-9B was found. The family support and generic exporter give a plausible inferred path, not a demonstrated 9B path. Do not include 9B in a strict shortlist requiring positive checkpoint-level RK3588 evidence. Search also finds an [official Qwen3.5-9B multi-card example](https://github.com/airockchip/rknn3-model-zoo/blob/main/examples/multicard/README.md), but that is RKNN3 with two RK182X accelerator cards, not the RK3588 integrated NPU. Its host build flag `-t rk3588` is not evidence that the RK3588 NPU runs that model. Third-party 9B and runtime-1.2.3 claims are unverified and were not relied on.

## ABI / ctypes upgrade review

Compared official [1.2.3 rkllm.h](https://github.com/airockchip/rknn-llm/blob/release-v1.2.3/rkllm-runtime/Linux/librkllm_api/include/rkllm.h), [1.3.0 rkllm.h](https://github.com/airockchip/rknn-llm/blob/release-v1.3.0/rkllm-runtime/Linux/librkllm_api/include/rkllm.h), and [1.3.1 rkllm.h](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/rkllm-runtime/Linux/librkllm_api/include/rkllm.h). Local copies of old/new are `/tmp/p519-rkllm123.h` and `/tmp/p519-rkllm131.h`. A library-only swap with old ctypes definitions is unsafe; this is a concrete ABI change, including text-only calls:

- `rkllm_init` third argument changes from result callback function to pointer to new `RKLLMCallback` struct, holding result/tokenizer/embedding callbacks and userdata.
- `RKLLMParam` adds `ignore_eos_token`, removes `img_start`, `img_end`, `img_content`. That shifts `is_async` and `extend_param`; returning this struct by value from `rkllm_createDefaultParam` also requires a correct restype/layout.
- `RKLLMInferParam` inserts `sampling_params` before `keep_history` and adds `max_new_tokens`.
- `RKLLMMultiModalInput` changes from flat image data to nested image/video structs in 1.3.0 and adds audio in 1.3.1. The enclosing `RKLLMInput` union grows even when passing text.
- `RKLLMSamplingParam`, tokenizer and embedding callback types are new. Review widths, bools, size_t, alignment, callback lifetime, argtypes/restype; validate sizes and offsets against a compiled C/C++ helper using the exact selected header.
- `rkllm_is_running` documentation changes its running result to 1; review any wrapper expectation.

These are future NPU validation prerequisites. No repository ctypes wrapper or Pi artifact was changed.

## Official Qwen3.5 behavior

The [official 4B model card](https://huggingface.co/Qwen/Qwen3.5-4B) identifies a causal language model with a vision encoder, 32 language layers, and a layout of eight groups, each containing three Gated DeltaNet blocks followed by one Gated Attention block: 24 linear-attention layers and 8 gated full-attention layers. Thus “8 of 32” describes full-attention layers, not linear-attention layers. The [official config](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/config.json) makes the layer types inspectable.

The same card says thinking is the default and recommends sampling. For general non-thinking tasks, it recommends temperature0.7, top_p0.8, top_k20, min_p0, presence_penalty1.5, repetition_penalty1.0. P5-19's temperature0 greedy protocol deliberately deviates; record that deviation without adopting different candidate-specific decoding.

The [official chat template](https://huggingface.co/Qwen/Qwen3.5-4B/blob/main/chat_template.jinja), final lines, explicitly checks `enable_thinking is false`: generation prefix becomes `<|im_start|>assistant\n<think>\n\n</think>\n\n`; otherwise it ends with an open thinking tag. Qwen3.5 does not officially support Qwen3's `/think` and `/nothink` soft switches. The rendered prompt can correctly contain a closed empty thinking block; generated raw output should contain no new thinking content or duplicated answer. Inspect prompt and raw continuation separately.

## Next Pi checks after any quality winner

Convert the pinned official checkpoint with the selected, pinned matching toolkit/runtime; retain artifact SHA256, quantization and calibration metadata. For Qwen3.5 use the authorized isolated test runtime, matching ABI wrapper, and verify rknpu>=0.9.8. Then check W8A8 menu quality against GPU answers, template behavior and no-grammar schema failure/truncation rate, CPU+NPU contention, and tokens/second on the frozen v8 prompt. GPU quality evidence establishes none of these outcomes.

## Execution notes

After measuring each worker, concurrent baseline4B + Qwen3.5-2B workers
used4652 MiB and1712 MiB respectively (weights, KV, recurrent state and runtime
included); total6766 MiB,1075 MiB free. The small worker uses8092; sequential
4B+ workers use8091. Each worker keeps two requests in flight. Concurrency changes
wall scheduling and can change GPU numerics; both baseline replicates retain the
same backend/flags, and the measured gap is used as the empirical noise band.
GPU samples are recorded per process. No unrelated process is stopped.

The old8B file has embedded model name `Qwen3 8B Awq Compatible Instruct` and
finetune `awq-compatible-Instruct`, with no publisher/source/revision metadata.
It will not be used as the official Qwen3-8B candidate.

## Verification

`make ci` passed on a clean detached checkout of `b4b0e2e` at
`var/menu-eval/model-screen/ci/` (no experiment scratch or data symlinks in its
mypy scan): lockfile, lint/format and strict mypy passed;676 tests passed,727
skipped,1 warning. Database tests skipped where optional prerequisites were absent;
this is not database acceptance. Pipeline code is unchanged. The final draft gets
a separate file-hygiene check. Scratch analysis guards were checked against the
three baseline smoke records and synthetic bootstrap/router cases.

## Owner protocol amendment:15-page triage,30-page follow-up

Before any candidate score, the owner asked whether35pages or even30/15were enough
for this quality screen. Adopted:15shared representative pages for initial triage;
expand promising or close candidates to the nested30page set. The recommendation
is provisional and concerns whether Pi artifact validation is worthwhile. The
original218-page protocol above is superseded for this session's screen size and
all218/page acceptance language. It remains recorded as the original plan.

All full-cohort jobs were stopped;68baselineA and35Qwen3.5-2B outputs remain
archived and are not used as full-cohort evidence. Fresh screening baselineA/B
answers use the same15then30pages and the same pinned backend and flags. All
other input/prompt/chunk/budget/grammar/repair/validator/matching rules stay frozen.
No candidate scores informed subset selection. All seven prior sets remain represented.

Selection seed20261015. Each set contributes a page near3input chunks and a page
near7chunks; a fifteenth page broadens scarce-format coverage. The nested30adds
pages near5and11chunks per set plus another scarce-format page. Seed breaks ties.
The15page set has82chunks and covers html_list,html_cards,html_inline,price_list;
the30page set has202chunks. Selection manifests are saved before scoring under
`var/menu-eval/model-screen/screen{15,30}/`. These are purposefully selected diagnostic
pages, not a random population sample. Confidence intervals describe these selected
pages and do not establish full-cohort or held-out acceptance.

At15pages, a candidate is an obvious loser if pooled price accuracy<0.97, or BOTH
usable prices and kept recall trail BOTH baselines by more than0.03. Other candidates
continue to30when the15page comparison is positive or inconclusive. The original
worthwhile-gain/safety criteria are evaluated on each declared subset, with paired
page bootstrap and the baselineA/B gap; any 'clear' result is explicitly a reduced-screen
result. An unproven gain remains inconclusive. No full218page gain or production claim
will be inferred. Baseline error attribution still precedes candidate scoring and
covers all seven sets, using their selected pages.

The fixed15-page sample includes5pages with price-before-name layouts,12with multiple
prices,10with structural FR, and2with rare formats under the full-cohort format
frequencies. The30-page sample has8/24/19/3respectively. These overlapping slices
were computed from input and label metadata before candidate scores. Fresh baseline
smoke:34.23s for3selected pages (315.55pages/hour);82selected input chunks
suggest roughly26minutes for five15-page passes by chunk count, excluding setup
and scoring;30-page follow-up and conditional larger models add work as needed.
GPU timing remains scheduling context only.

Copy-fidelity definition finalized after baseline attribution and before any candidate
score: primary exact-name copy means the raw name occurs verbatim somewhere on the
input page (`copy_anywhere`, strict case/punctuation). Claimed-block fidelity remains
a separate anchor diagnostic. BaselineA has1364/1380verbatim page copies but only
1091/1380passes of the claimed-block copy check; treating all289check failures as spelling/copy
errors would conflate two mechanisms. The reduced-screen no-worse-copy gate applies
to page-verbatim copying, against both baseline runs, with no noise allowance.
Matching and validator behavior remain unchanged.

Baseline inspection decomposes those289claimed-block failures into273names that
occur verbatim elsewhere and16page-verbatim failures. The latter include case
changes, an empty name, multi-block concatenations, and genuine transcription
errors. Imported P5-18 structural classes remain heuristic proxies: `name_number`
can also flag a local price mismatch, and `header` can find a same-size label on
an earlier item even when the actual label sits below. Counts are not manual
causal adjudication; inspected examples and these ambiguities accompany the tables.

<!-- MODEL_SCREEN_RESULTS -->

## Amended15/30-page screen results — provisional

Owner-review draft generated 2026-10-16T01:35:32+00:00. The original218-page protocol above is retained for history and superseded in workload by the owner’s pre-score15/30-page amendment. Numerical safety/gain checks remain visible, but every result below is a reduced tuning screen. Pipeline remains `b4b0e2e`; no model-specific prompt/downstream tuning, held-out draw, Pi test or deployment change.

| Configuration | Latest evaluated phase | Pages | Numerical subset decision | Subset gates clear | Evidence |
| --- | --- | --- | --- | --- | --- |
| screen-baseline-qkm | screen30 | 30 | fails_criterion | False | [evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-q25-7b | screen30 | 30 | fails_criterion | False | [evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q3-8b | screen30 | 30 | fails_criterion | False | [evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q35-2b | screen15 | 15 | fails_criterion | False | [evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-4b | screen15 | 15 | fails_criterion | False | [evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |

Each model is summarized at its largest completed phase. A15-page elimination is a provisional screen-out under the pre-set obvious-loser rule; non-expansion is not a measured30-page result. Models at different phase sizes are not directly compared; their common phase tables remain separate below. GPU throughput is never an acceptance criterion.

## screen15: provisional 15-page quality screen

This phase contains **15 selected tuning pages and 82 input chunks**, with every one of the seven sets represented. It is neither the original full218-page protocol nor held-out or production acceptance. The owner amended the workload before candidate scores; archived partial full-cohort outputs are excluded. The frozen numerical quality checks are applied to this reduced phase only. A subset gate pass is provisional evidence for NPU validation, not proof that the full-cohort criterion clears.

Selection seed `20261015`; candidate scores used: `False`. Each set: near3 and7 inputchunks;15th scarceformat.30 adds near5 and11 chunks/set plus scarceformat. Seed breaks ties;nested;no candidate outputs inspected. The30-page expansion is nested. Candidates expanded after a positive/inconclusive15-page signal are adaptively selected; screen30 is not an independent confirmation. The15-page obvious-loser rule is price accuracy<0.97 OR both usable and kept recall trailing both baselines by>0.03; all other positive/inconclusive contenders may proceed to30. No threshold or page subset is tuned per model.

| Set | Pages | Input chunks | Formats | Page IDs |
| --- | --- | --- | --- | --- |
| spike | 3 | 22 | html_inline, html_list | 0824dfcdd900, 630ef18b78a3, 6a788f7d3b50 |
| p5-5 | 2 | 10 | html_list | 66a3d8e752b9, f649c257352d |
| p5-8 | 2 | 10 | html_cards, price_list | a8684c49dfa1, ddb652ccea54 |
| p5-10 | 2 | 10 | html_list | 3e035f21ac55, d9126c519b73 |
| p5-12 | 2 | 10 | html_cards, html_list | 1bc9710cd463, 29612ad9e3eb |
| p5-14 | 2 | 10 | html_list | e845388448b9, f204b5c8375f |
| p5-16 | 2 | 10 | html_list | 5d960df16b84, 6d5cdfffe336 |

Selection manifest: [selection.json](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/selection.json); [splits.json](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/splits.json).

### Phase runtime and artifact identity

| Run | Model configuration | GGUF file | Smoke pages/h | Latest invocation wall h | Slot context | Slots | GPU layers | CUDA MiB model/KV/compute | Isolated-worker observed peak MiB | Whole-GPU peak MiB | Provenance | Runtime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| screen-baseline-a | Qwen3-4B-Instruct-2507 Q4_0 A | Qwen3-4B-Instruct-2507-Q4_0.gguf | 315.55 | 0.109 | 6144 | 2 | 37/37 | 2260.0/1728.0/426.0 | 4660 | 4996 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/full.json) |
| screen-baseline-b | Qwen3-4B-Instruct-2507 Q4_0 B | Qwen3-4B-Instruct-2507-Q4_0.gguf | 301.98 | 0.113 | 6144 | 2 | 37/37 | 2260.0/1728.0/426.0 | 4660 | 5124 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/full.json) |
| screen-baseline-qkm | Qwen3-4B-Instruct-2507 Q4_K_M | Qwen3-4B-Instruct-2507-Q4_K_M.gguf | 276.15 | 0.118 | 6144 | 2 | 37/37 | 2375.9/1728.0/426.0 | 4774 | 5220 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/full.json) |
| screen-q25-7b | Qwen2.5-7B-Instruct Q4_K_M | qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf | 173.18 | 0.156 | 6144 | 2 | 29/29 | 4168.1/672.0/378.0 | 5448 | 5627 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/full.json) |
| screen-q3-8b | Qwen3-8B Q4_K_M | Qwen3-8B-Q4_K_M.gguf | 68.54 | 0.186 | 6144 | 2 | 37/37 | 4455.3/1728.0/432.0 | 6860 | 7039 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/full.json) |
| screen-q35-2b | Qwen3.5-2B Q4_K_M | Qwen3.5-2B-Q4_K_M.gguf | 244.99 | 0.087 | 6144 | 2 | 25/25 | 1211.0/144.0/130.0 | 1724 | 2128 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-2b/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-2b/full.json) |
| screen-q35-4b | Qwen3.5-4B Q4_K_M | Qwen3.5-4B-Q4_K_M.gguf | 246.76 | 0.046 | 6144 | 2 | 33/33 | 2603.5/384.0/242.0 | 3548 | 3971 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-4b/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-4b/full.json) |

Every model uses the same frozen context, output budget, prompt and downstream pipeline. The amended screen runs GPU models sequentially and exclusively. GPU throughput is scheduling metadata, never an acceptance bar. A runtime record may describe the latest15→30 extension and reuse completed pages; it is not necessarily an independent phase timing. Whole-GPU peaks include desktop/runtime overhead; isolated-worker peaks require unambiguous single-worker process samples. CUDA buffer sums exclude additional runtime allocations. Missing measurements stay n/a, and missing offload proof stays unproven. Full-offload proof and process measurements are preserved in [server/process logs](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/logs). Archived partial218-page jobs were stopped before candidate scoring and are not used by these phase scores.

- **screen-baseline-a**: checkpoint `Qwen/Qwen3-4B-Instruct-2507@cdbee75f17c01a7cc42f958dc650907174af0554` observed; GGUF `unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9`; SHA256 `e0ba675d86ab277c61701c6793659b2ae801d95e3be791464c321e6fbf613be2`; 2375773280 bytes; `Qwen3-4B-Instruct-2507;Q4_0;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `c979e0e71a3e21b8f208e6ab120d5cb29327885f29d2a8b18fda67a723798e18`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/server-command.json).
- **screen-baseline-b**: checkpoint `Qwen/Qwen3-4B-Instruct-2507@cdbee75f17c01a7cc42f958dc650907174af0554` observed; GGUF `unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9`; SHA256 `e0ba675d86ab277c61701c6793659b2ae801d95e3be791464c321e6fbf613be2`; 2375773280 bytes; `Qwen3-4B-Instruct-2507;Q4_0;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `c979e0e71a3e21b8f208e6ab120d5cb29327885f29d2a8b18fda67a723798e18`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/server-command.json).
- **screen-baseline-qkm**: checkpoint `Qwen/Qwen3-4B-Instruct-2507@cdbee75f17c01a7cc42f958dc650907174af0554` observed; GGUF `unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9`; SHA256 `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`; 2497281120 bytes; `Qwen3-4B-Instruct-2507;Q4_K_M;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `c979e0e71a3e21b8f208e6ab120d5cb29327885f29d2a8b18fda67a723798e18`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/server-command.json).
- **screen-q25-7b**: checkpoint `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28` observed; GGUF `Qwen/Qwen2.5-7B-Instruct-GGUF@bb5d59e06d9551d752d08b292a50eb208b07ab1f`; SHA256 `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db`; additional shard `qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf` SHA256 `539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a`; 4683073632 bytes; `Qwen2.5-7B-Instruct;Q4_K_M;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `4e9918361c284a93880606d182d64da6a9fe97cdc1f5c5a78c1c8840444246fc`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/server-command.json).
- **screen-q3-8b**: checkpoint `Qwen/Qwen3-8B@b968826d9c46dd6066d109eabc6255188de91218` observed; GGUF `unsloth/Qwen3-8B-GGUF@a6adef130ffb23ddaf1a62fec9dced968c9bc482`; SHA256 `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4`; 5027784512 bytes; `Qwen3-8B;Q4_K_M;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `5da44855ab7e0641774d5ed0ff0b4f89671d01df7d316e54d06557a962211cb4`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/server-command.json).
- **screen-q35-2b**: checkpoint `Qwen/Qwen3.5-2B@15852e8c16360a2fea060d615a32b45270f8a8fc` observed; GGUF `unsloth/Qwen3.5-2B-GGUF@f6d5376be1edb4d416d56da11e5397a961aca8ae`; SHA256 `aaf42c8b7c3cab2bf3d69c355048d4a0ee9973d48f16c731c0520ee914699223`; 1280835840 bytes; `Qwen3.5-2B;Q4_K_M;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `7f0e529032c25183bcd66c7f238da2d377f43be754a94e2725a58c4e16d2ed67`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-2b/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-2b/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-2b/server-command.json).
- **screen-q35-4b**: checkpoint `Qwen/Qwen3.5-4B@851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a` observed; GGUF `unsloth/Qwen3.5-4B-GGUF@e87f176479d0855a907a41277aca2f8ee7a09523`; SHA256 `00fe7986ff5f6b463e62455821146049db6f9313603938a70800d1fb69ef11a4`; 2740937888 bytes; `Qwen3.5-4B;Q4_K_M;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `7f0e529032c25183bcd66c7f238da2d377f43be754a94e2725a58c4e16d2ed67`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-4b/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-4b/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q35-4b/server-command.json).

### Primary v9 labels: metrics and exact denominators

Usable-price numerator counts distinct(item,amount), while its denominator counts every labelled price row. Repeated equal-amount variants create a model-invariant denominator gap and are isolated below with zero gain ceiling. Accepted-price accuracy conditions on matched rows; unsafe unmatched rows are reported separately.

| Set | Run | Gold items | Gold price rows | Raw recall n/d | Kept recall n/d | Usable n/d | Price accuracy n/d |
| --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 335 | 299 | 305/335 (0.9104) | 304/335 (0.9075) | 268/299 (0.8963) | 269/273 (0.9853) |
| spike | screen-baseline-b | 335 | 299 | 304/335 (0.9075) | 304/335 (0.9075) | 270/299 (0.9030) | 271/275 (0.9855) |
| spike | screen-baseline-qkm | 335 | 299 | 309/335 (0.9224) | 309/335 (0.9224) | 273/299 (0.9130) | 280/287 (0.9756) |
| spike | screen-q25-7b | 335 | 299 | 284/335 (0.8478) | 273/335 (0.8149) | 276/299 (0.9231) | 278/283 (0.9823) |
| spike | screen-q3-8b | 335 | 299 | 318/335 (0.9493) | 290/335 (0.8657) | 281/299 (0.9398) | 281/293 (0.9590) |
| spike | screen-q35-2b | 335 | 299 | 199/335 (0.5940) | 199/335 (0.5940) | 182/299 (0.6087) | 182/188 (0.9681) |
| spike | screen-q35-4b | 335 | 299 | 300/335 (0.8955) | 300/335 (0.8955) | 257/299 (0.8595) | 259/262 (0.9885) |
| p5-5 | screen-baseline-a | 155 | 23 | 150/155 (0.9677) | 150/155 (0.9677) | 17/23 (0.7391) | 18/20 (0.9000) |
| p5-5 | screen-baseline-b | 155 | 23 | 146/155 (0.9419) | 146/155 (0.9419) | 16/23 (0.6957) | 16/18 (0.8889) |
| p5-5 | screen-baseline-qkm | 155 | 23 | 144/155 (0.9290) | 144/155 (0.9290) | 18/23 (0.7826) | 18/18 (1.0000) |
| p5-5 | screen-q25-7b | 155 | 23 | 77/155 (0.4968) | 65/155 (0.4194) | 15/23 (0.6522) | 15/17 (0.8824) |
| p5-5 | screen-q3-8b | 155 | 23 | 131/155 (0.8452) | 102/155 (0.6581) | 13/23 (0.5652) | 13/13 (1.0000) |
| p5-5 | screen-q35-2b | 155 | 23 | 151/155 (0.9742) | 125/155 (0.8065) | 6/23 (0.2609) | 6/6 (1.0000) |
| p5-5 | screen-q35-4b | 155 | 23 | 103/155 (0.6645) | 103/155 (0.6645) | 11/23 (0.4783) | 11/11 (1.0000) |
| p5-8 | screen-baseline-a | 97 | 114 | 85/97 (0.8763) | 85/97 (0.8763) | 96/114 (0.8421) | 97/98 (0.9898) |
| p5-8 | screen-baseline-b | 97 | 114 | 87/97 (0.8969) | 87/97 (0.8969) | 99/114 (0.8684) | 99/100 (0.9900) |
| p5-8 | screen-baseline-qkm | 97 | 114 | 79/97 (0.8144) | 79/97 (0.8144) | 91/114 (0.7982) | 91/91 (1.0000) |
| p5-8 | screen-q25-7b | 97 | 114 | 83/97 (0.8557) | 83/97 (0.8557) | 99/114 (0.8684) | 101/101 (1.0000) |
| p5-8 | screen-q3-8b | 97 | 114 | 76/97 (0.7835) | 76/97 (0.7835) | 77/114 (0.6754) | 79/80 (0.9875) |
| p5-8 | screen-q35-2b | 97 | 114 | 72/97 (0.7423) | 72/97 (0.7423) | 64/114 (0.5614) | 64/67 (0.9552) |
| p5-8 | screen-q35-4b | 97 | 114 | 77/97 (0.7938) | 77/97 (0.7938) | 84/114 (0.7368) | 84/84 (1.0000) |
| p5-10 | screen-baseline-a | 99 | 123 | 68/99 (0.6869) | 68/99 (0.6869) | 79/123 (0.6423) | 82/82 (1.0000) |
| p5-10 | screen-baseline-b | 99 | 123 | 71/99 (0.7172) | 71/99 (0.7172) | 85/123 (0.6911) | 87/87 (1.0000) |
| p5-10 | screen-baseline-qkm | 99 | 123 | 81/99 (0.8182) | 80/99 (0.8081) | 80/123 (0.6504) | 80/80 (1.0000) |
| p5-10 | screen-q25-7b | 99 | 123 | 79/99 (0.7980) | 76/99 (0.7677) | 82/123 (0.6667) | 83/83 (1.0000) |
| p5-10 | screen-q3-8b | 99 | 123 | 79/99 (0.7980) | 79/99 (0.7980) | 86/123 (0.6992) | 89/89 (1.0000) |
| p5-10 | screen-q35-2b | 99 | 123 | 56/99 (0.5657) | 56/99 (0.5657) | 27/123 (0.2195) | 27/27 (1.0000) |
| p5-10 | screen-q35-4b | 99 | 123 | 69/99 (0.6970) | 68/99 (0.6869) | 69/123 (0.5610) | 69/69 (1.0000) |
| p5-12 | screen-baseline-a | 109 | 133 | 91/109 (0.8349) | 91/109 (0.8349) | 82/133 (0.6165) | 89/89 (1.0000) |
| p5-12 | screen-baseline-b | 109 | 133 | 92/109 (0.8440) | 92/109 (0.8440) | 84/133 (0.6316) | 90/90 (1.0000) |
| p5-12 | screen-baseline-qkm | 109 | 133 | 91/109 (0.8349) | 91/109 (0.8349) | 84/133 (0.6316) | 99/100 (0.9900) |
| p5-12 | screen-q25-7b | 109 | 133 | 96/109 (0.8807) | 96/109 (0.8807) | 94/133 (0.7068) | 99/100 (0.9900) |
| p5-12 | screen-q3-8b | 109 | 133 | 102/109 (0.9358) | 102/109 (0.9358) | 91/133 (0.6842) | 104/104 (1.0000) |
| p5-12 | screen-q35-2b | 109 | 133 | 53/109 (0.4862) | 44/109 (0.4037) | 26/133 (0.1955) | 26/27 (0.9630) |
| p5-12 | screen-q35-4b | 109 | 133 | 89/109 (0.8165) | 89/109 (0.8165) | 81/133 (0.6090) | 83/85 (0.9765) |
| p5-14 | screen-baseline-a | 88 | 106 | 81/88 (0.9205) | 81/88 (0.9205) | 92/106 (0.8679) | 94/97 (0.9691) |
| p5-14 | screen-baseline-b | 88 | 106 | 81/88 (0.9205) | 81/88 (0.9205) | 95/106 (0.8962) | 96/98 (0.9796) |
| p5-14 | screen-baseline-qkm | 88 | 106 | 80/88 (0.9091) | 80/88 (0.9091) | 94/106 (0.8868) | 96/99 (0.9697) |
| p5-14 | screen-q25-7b | 88 | 106 | 78/88 (0.8864) | 78/88 (0.8864) | 90/106 (0.8491) | 93/98 (0.9490) |
| p5-14 | screen-q3-8b | 88 | 106 | 85/88 (0.9659) | 85/88 (0.9659) | 97/106 (0.9151) | 99/101 (0.9802) |
| p5-14 | screen-q35-2b | 88 | 106 | 70/88 (0.7955) | 70/88 (0.7955) | 63/106 (0.5943) | 66/68 (0.9706) |
| p5-14 | screen-q35-4b | 88 | 106 | 81/88 (0.9205) | 81/88 (0.9205) | 93/106 (0.8774) | 94/96 (0.9792) |
| p5-16 | screen-baseline-a | 141 | 166 | 127/141 (0.9007) | 127/141 (0.9007) | 131/166 (0.7892) | 131/132 (0.9924) |
| p5-16 | screen-baseline-b | 141 | 166 | 130/141 (0.9220) | 130/141 (0.9220) | 133/166 (0.8012) | 133/134 (0.9925) |
| p5-16 | screen-baseline-qkm | 141 | 166 | 121/141 (0.8582) | 121/141 (0.8582) | 111/166 (0.6687) | 111/113 (0.9823) |
| p5-16 | screen-q25-7b | 141 | 166 | 102/141 (0.7234) | 99/141 (0.7021) | 97/166 (0.5843) | 99/99 (1.0000) |
| p5-16 | screen-q3-8b | 141 | 166 | 124/141 (0.8794) | 124/141 (0.8794) | 115/166 (0.6928) | 115/117 (0.9829) |
| p5-16 | screen-q35-2b | 141 | 166 | 55/141 (0.3901) | 55/141 (0.3901) | 62/166 (0.3735) | 62/63 (0.9841) |
| p5-16 | screen-q35-4b | 141 | 166 | 111/141 (0.7872) | 111/141 (0.7872) | 111/166 (0.6687) | 112/113 (0.9912) |
| pooled | screen-baseline-a | 1024 | 964 | 907/1024 (0.8857) | 906/1024 (0.8848) | 765/964 (0.7936) | 780/791 (0.9861) |
| pooled | screen-baseline-b | 1024 | 964 | 911/1024 (0.8896) | 911/1024 (0.8896) | 782/964 (0.8112) | 792/802 (0.9875) |
| pooled | screen-baseline-qkm | 1024 | 964 | 905/1024 (0.8838) | 904/1024 (0.8828) | 751/964 (0.7790) | 775/788 (0.9835) |
| pooled | screen-q25-7b | 1024 | 964 | 799/1024 (0.7803) | 770/1024 (0.7520) | 753/964 (0.7811) | 768/781 (0.9834) |
| pooled | screen-q3-8b | 1024 | 964 | 915/1024 (0.8936) | 858/1024 (0.8379) | 760/964 (0.7884) | 780/797 (0.9787) |
| pooled | screen-q35-2b | 1024 | 964 | 656/1024 (0.6406) | 621/1024 (0.6064) | 430/964 (0.4461) | 433/446 (0.9709) |
| pooled | screen-q35-4b | 1024 | 964 | 830/1024 (0.8105) | 829/1024 (0.8096) | 706/964 (0.7324) | 712/720 (0.9889) |

### Baseline A/B gap bands on this subset

Only the pooled absolute A/B gap is the criterion band; per-set gaps provide context. Two runs do not bound model variance. With only2–5 pages per set, per-set intervals are especially unstable.

| Set | Metric | Baseline A | Baseline B | Absolute A/B gap |
| --- | --- | --- | --- | --- |
| spike | usable_prices | 0.8963 | 0.9030 | 0.0067 |
| spike | item_recall_kept | 0.9075 | 0.9075 | 0.0000 |
| spike | item_recall | 0.9104 | 0.9075 | 0.0030 |
| spike | price_accuracy | 0.9853 | 0.9855 | 0.0001 |
| spike | copy_claimed | 0.9200 | 0.9207 | 0.0007 |
| spike | copy_anywhere | 0.9857 | 0.9915 | 0.0058 |
| spike | validator_false_reject | 0.0110 | 0.0073 | 0.0037 |
| spike | validator_catch | 0.5882 | 0.5526 | 0.0356 |
| p5-5 | usable_prices | 0.7391 | 0.6957 | 0.0435 |
| p5-5 | item_recall_kept | 0.9677 | 0.9419 | 0.0258 |
| p5-5 | item_recall | 0.9677 | 0.9419 | 0.0258 |
| p5-5 | price_accuracy | 0.9000 | 0.8889 | 0.0111 |
| p5-5 | copy_claimed | 0.9190 | 0.9404 | 0.0214 |
| p5-5 | copy_anywhere | 0.9960 | 0.9915 | 0.0045 |
| p5-5 | validator_false_reject | 0.2800 | 0.3043 | 0.0243 |
| p5-5 | validator_catch | 0.6429 | 0.6296 | 0.0132 |
| p5-8 | usable_prices | 0.8421 | 0.8684 | 0.0263 |
| p5-8 | item_recall_kept | 0.8763 | 0.8969 | 0.0206 |
| p5-8 | item_recall | 0.8763 | 0.8969 | 0.0206 |
| p5-8 | price_accuracy | 0.9898 | 0.9900 | 0.0002 |
| p5-8 | copy_claimed | 0.7211 | 0.8144 | 0.0933 |
| p5-8 | copy_anywhere | 0.9842 | 0.9701 | 0.0142 |
| p5-8 | validator_false_reject | 0.1709 | 0.0198 | 0.1511 |
| p5-8 | validator_catch | 0.8194 | 0.8143 | 0.0052 |
| p5-10 | usable_prices | 0.6423 | 0.6911 | 0.0488 |
| p5-10 | item_recall_kept | 0.6869 | 0.7172 | 0.0303 |
| p5-10 | item_recall | 0.6869 | 0.7172 | 0.0303 |
| p5-10 | price_accuracy | 1.0000 | 1.0000 | 0.0000 |
| p5-10 | copy_claimed | 0.7578 | 0.8041 | 0.0462 |
| p5-10 | copy_anywhere | 0.9531 | 0.9459 | 0.0072 |
| p5-10 | validator_false_reject | 0.0353 | 0.1031 | 0.0678 |
| p5-10 | validator_catch | 0.9231 | 0.7879 | 0.1352 |
| p5-12 | usable_prices | 0.6165 | 0.6316 | 0.0150 |
| p5-12 | item_recall_kept | 0.8349 | 0.8440 | 0.0092 |
| p5-12 | item_recall | 0.8349 | 0.8440 | 0.0092 |
| p5-12 | price_accuracy | 1.0000 | 1.0000 | 0.0000 |
| p5-12 | copy_claimed | 0.8243 | 0.8344 | 0.0101 |
| p5-12 | copy_anywhere | 0.9932 | 1.0000 | 0.0068 |
| p5-12 | validator_false_reject | 0.2764 | 0.2683 | 0.0081 |
| p5-12 | validator_catch | 0.5882 | 0.5000 | 0.0882 |
| p5-14 | usable_prices | 0.8679 | 0.8962 | 0.0283 |
| p5-14 | item_recall_kept | 0.9205 | 0.9205 | 0.0000 |
| p5-14 | item_recall | 0.9205 | 0.9205 | 0.0000 |
| p5-14 | price_accuracy | 0.9691 | 0.9796 | 0.0105 |
| p5-14 | copy_claimed | 0.6250 | 0.6792 | 0.0542 |
| p5-14 | copy_anywhere | 1.0000 | 0.9811 | 0.0189 |
| p5-14 | validator_false_reject | 0.0962 | 0.0400 | 0.0562 |
| p5-14 | validator_catch | 0.5714 | 0.4000 | 0.1714 |
| p5-16 | usable_prices | 0.7892 | 0.8012 | 0.0120 |
| p5-16 | item_recall_kept | 0.9007 | 0.9220 | 0.0213 |
| p5-16 | item_recall | 0.9007 | 0.9220 | 0.0213 |
| p5-16 | price_accuracy | 0.9924 | 0.9925 | 0.0001 |
| p5-16 | copy_claimed | 0.5659 | 0.5577 | 0.0082 |
| p5-16 | copy_anywhere | 1.0000 | 1.0000 | 0.0000 |
| p5-16 | validator_false_reject | 0.2557 | 0.2528 | 0.0029 |
| p5-16 | validator_catch | 0.5000 | 0.5294 | 0.0294 |
| pooled | usable_prices | 0.7936 | 0.8112 | 0.0176 |
| pooled | item_recall_kept | 0.8848 | 0.8896 | 0.0049 |
| pooled | item_recall | 0.8857 | 0.8896 | 0.0039 |
| pooled | price_accuracy | 0.9861 | 0.9875 | 0.0014 |
| pooled | copy_claimed | 0.7906 | 0.8151 | 0.0246 |
| pooled | copy_anywhere | 0.9884 | 0.9854 | 0.0030 |
| pooled | validator_false_reject | 0.1353 | 0.1151 | 0.0202 |
| pooled | validator_catch | 0.6972 | 0.6638 | 0.0335 |

### Baseline attribution on the identical selected pages

Exclusive gold-price losses and ceilings are separate from overlapping row diagnostics. Perfect-row-pass ceilings assume the ideal labelled representation; no bucket predicts an achievable model gain. P18 layout classes are unchanged. Unmatched rows are not proven hallucinations; description/noise, association and grounding diagnostics are heuristic. Strict raw copy failures have no separately additive recoverable-gold ceiling.

| Set | Exclusive gold-price loss | N | Δusable absolute ceiling | Perfect-row-pass N | Δusable perfect-row ceiling |
| --- | --- | --- | --- | --- | --- |
| spike | MODEL_READING:item_missed | 28 | 0.09365 | 28 | 0.09365 |
| spike | MODEL_READING:row_unpriced | 2 | 0.00669 | 2 | 0.00669 |
| spike | MODEL_REPRESENTATION_VALIDATOR:name_not_grounded | 1 | 0.00334 | 1 | 0.00334 |
| p5-5 | MODEL_REPRESENTATION_VALIDATOR:p_other | 6 | 0.26087 | 6 | 0.26087 |
| p5-8 | MODEL_READING:item_missed | 14 | 0.12281 | 12 | 0.10526 |
| p5-8 | MODEL_READING:wrong_amount_printed_nearby_proxy | 3 | 0.02632 | 3 | 0.02632 |
| p5-8 | MODEL_REPRESENTATION_VALIDATOR:v_other | 1 | 0.00877 | 1 | 0.00877 |
| p5-10 | MODEL_READING:item_missed | 32 | 0.26016 | 23 | 0.18699 |
| p5-10 | MODEL_READING:wrong_amount_printed_nearby_proxy | 9 | 0.07317 | 0 | 0.00000 |
| p5-10 | STRUCTURAL_VALIDATOR:p_other | 3 | 0.02439 | 0 | 0.00000 |
| p5-12 | LABEL_CONVENTION:duplicate_gold_amount | 4 | 0.00000 | 0 | 0.00000 |
| p5-12 | MODEL_READING:item_missed | 22 | 0.16541 | 12 | 0.09023 |
| p5-12 | MODEL_READING:row_unpriced | 1 | 0.00752 | 1 | 0.00752 |
| p5-12 | MODEL_READING:wrong_amount_printed_nearby_proxy | 13 | 0.09774 | 2 | 0.01504 |
| p5-12 | MODEL_REPRESENTATION_VALIDATOR:p_other | 4 | 0.03008 | 4 | 0.03008 |
| p5-12 | MODEL_REPRESENTATION_VALIDATOR:unread | 3 | 0.02256 | 3 | 0.02256 |
| p5-12 | STRUCTURAL_VALIDATOR:p_other | 4 | 0.03008 | 0 | 0.00000 |
| p5-14 | MODEL_READING:item_missed | 10 | 0.09434 | 10 | 0.09434 |
| p5-14 | STRUCTURAL_VALIDATOR:p_other | 1 | 0.00943 | 0 | 0.00000 |
| p5-14 | STRUCTURAL_VALIDATOR:same_block | 3 | 0.02830 | 0 | 0.00000 |
| p5-16 | LABEL_CONVENTION:duplicate_gold_amount | 1 | 0.00000 | 0 | 0.00000 |
| p5-16 | MODEL_READING:item_missed | 17 | 0.10241 | 14 | 0.08434 |
| p5-16 | MODEL_READING:wrong_amount_printed_nearby_proxy | 5 | 0.03012 | 0 | 0.00000 |
| p5-16 | MODEL_REPRESENTATION_VALIDATOR:above | 1 | 0.00602 | 1 | 0.00602 |
| p5-16 | STRUCTURAL_VALIDATOR:price_belongs_to_other_variant | 6 | 0.03614 | 0 | 0.00000 |
| p5-16 | STRUCTURAL_VALIDATOR:v_other | 5 | 0.03012 | 0 | 0.00000 |
| pooled | LABEL_CONVENTION:duplicate_gold_amount | 5 | 0.00000 | 0 | 0.00000 |
| pooled | MODEL_READING:item_missed | 123 | 0.12759 | 99 | 0.10270 |
| pooled | MODEL_READING:row_unpriced | 3 | 0.00311 | 3 | 0.00311 |
| pooled | MODEL_READING:wrong_amount_printed_nearby_proxy | 30 | 0.03112 | 5 | 0.00519 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:above | 1 | 0.00104 | 1 | 0.00104 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:name_not_grounded | 1 | 0.00104 | 1 | 0.00104 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:p_other | 10 | 0.01037 | 10 | 0.01037 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:unread | 3 | 0.00311 | 3 | 0.00311 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:v_other | 1 | 0.00104 | 1 | 0.00104 |
| pooled | STRUCTURAL_VALIDATOR:p_other | 8 | 0.00830 | 0 | 0.00000 |
| pooled | STRUCTURAL_VALIDATOR:price_belongs_to_other_variant | 6 | 0.00622 | 0 | 0.00000 |
| pooled | STRUCTURAL_VALIDATOR:same_block | 3 | 0.00311 | 0 | 0.00000 |
| pooled | STRUCTURAL_VALIDATOR:v_other | 5 | 0.00519 | 0 | 0.00000 |

| Set | Missed gold items | Gold items | Δraw/kept recall ceiling | Raw but all rejected | Additional Δkept ceiling |
| --- | --- | --- | --- | --- | --- |
| spike | 30 | 335 | 0.0896 | 1 | 0.0030 |
| p5-5 | 5 | 155 | 0.0323 | 0 | 0.0000 |
| p5-8 | 12 | 97 | 0.1237 | 0 | 0.0000 |
| p5-10 | 31 | 99 | 0.3131 | 0 | 0.0000 |
| p5-12 | 18 | 109 | 0.1651 | 0 | 0.0000 |
| p5-14 | 7 | 88 | 0.0795 | 0 | 0.0000 |
| p5-16 | 14 | 141 | 0.0993 | 0 | 0.0000 |
| pooled | 117 | 1024 | 0.1143 | 1 | 0.0010 |

#### Gold-row structural classes: invariant

| Diagnostic | spike | p5-5 | p5-8 | p5-10 | p5-12 | p5-14 | p5-16 | pooled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| header | 0 | 0 | 0 | 7 | 1 | 0 | 0 | 8 |
| name_not_grounded | 0 | 0 | 0 | 3 | 0 | 0 | 0 | 3 |
| name_number | 0 | 0 | 0 | 1 | 0 | 0 | 0 | 1 |
| own_line | 1 | 0 | 0 | 1 | 4 | 4 | 0 | 10 |
| p_other | 0 | 0 | 2 | 23 | 23 | 6 | 10 | 64 |
| price_belongs_to_other_variant | 0 | 0 | 0 | 0 | 0 | 0 | 8 | 8 |
| unread | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 2 |
| v_other | 0 | 4 | 1 | 0 | 1 | 0 | 16 | 22 |

#### Real downgrade classes, exact/wrong/unmatched status

| Diagnostic | spike | p5-5 | p5-8 | p5-10 | p5-12 | p5-14 | p5-16 | pooled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact:above | 0 | 0 | 0 | 0 | 9 | 0 | 1 | 10 |
| exact:p_other | 0 | 6 | 0 | 3 | 14 | 1 | 0 | 24 |
| exact:price_belongs_to_other_variant | 0 | 0 | 0 | 0 | 0 | 0 | 6 | 6 |
| exact:same_block | 0 | 0 | 0 | 0 | 1 | 3 | 1 | 5 |
| exact:unread | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 3 |
| exact:v_other | 0 | 0 | 1 | 0 | 0 | 0 | 5 | 6 |
| unmatched:above | 0 | 0 | 36 | 0 | 0 | 0 | 0 | 36 |
| unmatched:name_number | 0 | 0 | 0 | 13 | 0 | 0 | 0 | 13 |
| unmatched:no_price_extracted | 4 | 41 | 3 | 16 | 3 | 3 | 1 | 71 |
| unmatched:p_other | 1 | 2 | 0 | 4 | 6 | 0 | 0 | 13 |
| unmatched:same_block | 2 | 4 | 0 | 0 | 0 | 0 | 0 | 6 |
| unmatched:unread | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 3 |
| unmatched:v_other | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| wrong:above | 0 | 0 | 10 | 0 | 1 | 0 | 1 | 12 |
| wrong:addon_price | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| wrong:name_number | 3 | 4 | 0 | 1 | 0 | 0 | 5 | 13 |
| wrong:no_price_extracted | 35 | 134 | 0 | 0 | 4 | 1 | 9 | 183 |
| wrong:p_other | 6 | 3 | 2 | 0 | 3 | 1 | 3 | 18 |
| wrong:same_block | 1 | 2 | 6 | 0 | 0 | 0 | 5 | 14 |
| wrong:unread | 5 | 1 | 0 | 0 | 0 | 0 | 0 | 6 |

#### Overlapping diagnostic counts; not additive recall ceilings

| Diagnostic | spike | p5-5 | p5-8 | p5-10 | p5-12 | p5-14 | p5-16 | pooled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| attempts:kept | 22 | 10 | 10 | 10 | 10 | 10 | 10 | 82 |
| chunks | 22 | 10 | 10 | 10 | 10 | 10 | 10 | 82 |
| duplicate_gold_item_amount_pairs | 0 | 0 | 0 | 0 | 4 | 0 | 1 | 5 |
| final_name_not_grounded | 3 | 0 | 0 | 6 | 1 | 0 | 0 | 10 |
| final_unmatched:accept | 10 | 8 | 12 | 2 | 7 | 0 | 16 | 55 |
| final_unmatched:downgrade | 7 | 47 | 39 | 33 | 9 | 6 | 2 | 143 |
| final_unmatched:reject | 2 | 0 | 8 | 6 | 1 | 0 | 2 | 19 |
| gold_items_raw_but_not_kept | 1 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| gold_price_loss_upper_bound | 31 | 6 | 18 | 44 | 51 | 14 | 35 | 199 |
| missed_gold_items | 30 | 5 | 12 | 31 | 18 | 7 | 14 | 117 |
| no_labelled_item_no_match_downgrades | 3 | 6 | 36 | 17 | 6 | 3 | 1 | 72 |
| no_match_downgrade:exact | 0 | 6 | 1 | 3 | 27 | 4 | 13 | 54 |
| no_match_downgrade:unmatched | 3 | 6 | 36 | 17 | 6 | 3 | 1 | 72 |
| no_match_downgrade:wrong | 15 | 12 | 18 | 1 | 4 | 1 | 14 | 65 |
| pre_repair_schema_failure:kept | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| raw_name_exact_anywhere | 345 | 246 | 187 | 122 | 147 | 112 | 205 | 1364 |
| raw_name_exact_claimed | 322 | 227 | 137 | 97 | 122 | 70 | 116 | 1091 |
| raw_name_not_exact_anywhere | 5 | 1 | 3 | 6 | 1 | 0 | 0 | 16 |
| raw_name_not_exact_claimed | 28 | 20 | 53 | 31 | 26 | 42 | 89 | 289 |
| raw_name_tokens_ungrounded | 3 | 0 | 0 | 6 | 1 | 0 | 0 | 10 |
| raw_rows | 350 | 247 | 190 | 128 | 148 | 112 | 205 | 1380 |
| truncation:kept | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| unmatched_description_or_noise_name_proxy | 7 | 0 | 2 | 20 | 1 | 2 | 0 | 32 |
| wrong_price_association_proxy | 14 | 13 | 16 | 0 | 3 | 4 | 15 | 65 |
| wrong_price_nowhere_nearby_proxy | 5 | 1 | 3 | 1 | 1 | 0 | 0 | 11 |

Full raw/final/source baseline evidence: [baseline-attribution.json](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/baseline-attribution.json); [baseline-attribution.md](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/baseline-attribution.md).

Source-reviewed baseline caveats and concrete cross-set cases: [baseline-inspection.md](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/baseline-inspection.md).

| Baseline proxy class | Page | Raw names | Final rows/decisions | Printed input snippet | Interpretation |
| --- | --- | --- | --- | --- | --- |
| missed_item | spike/0824dfcdd900 | no parsed nearby raw row | no nearby final row | b0023: $10 / $17; b0024: chef's choice | n/a |
| description_noise_proxy | spike/0824dfcdd900 | bigeye tuna | bigeye tuna accept | b0024: chef's choice; b0025: MAGURO* | Heuristic: overlaps label description, starts lowercase/nutrition word, or long sentence. Not manual adjudication. |
| exact_copy_not_anywhere | spike/6a788f7d3b50 | Chicken w/ Broccoli 芤蘭鸡片 | Chicken w/ Broccoli 芤蘭鸡片 reject | b0132: Ta Chien Chicken 大千鸡 – Sliced chicken with vegetables sautéed in hot ginger sauce – $16.95; b0133: Moo Goo Gai Pan – $16.95 | n/a |
| final_name_not_grounded | spike/6a788f7d3b50 | Chicken w/ Broccoli 芤蘭鸡片 | Chicken w/ Broccoli 芤蘭鸡片 reject | b0132: Ta Chien Chicken 大千鸡 – Sliced chicken with vegetables sautéed in hot ginger sauce – $16.95; b0133: Moo Goo Gai Pan – $16.95 | n/a |
| wrong_price_association_proxy | spike/630ef18b78a3 | FISH & CHIPS; FISH & CHIPS | FISH & CHIPS accept; FISH & CHIPS downgrade | b0074: Beer Battered Pollock with Crisp Potatoes and Goat Cheese Tarter Sauce; b0075: $18 | Near = amount in frozen price tokens within +/-12 blocks. Presence cannot establish ownership; absence may be structural unread price text. |
| wrong_price_nowhere_nearby_proxy | spike/630ef18b78a3 | School House Old Fashioned | School House Old Fashioned downgrade | b0115: drink-07.jpg; b0116: Cocktails | Near = amount in frozen price tokens within +/-12 blocks. Presence cannot establish ownership; absence may be structural unread price text. |
| truncation | p5-8/ddb652ccea54 | no parsed nearby raw row | no nearby final row | b0001: 0; b0002: Skip to Content | kept |
| pre_repair_schema_failure | p5-8/ddb652ccea54 | no parsed nearby raw row | no nearby final row | b0001: 0; b0002: Skip to Content | kept |
| gold_fr:header | p5-10/d9126c519b73 | no parsed nearby raw row | no nearby final row | b0125: 14"; b0126: $31 | Perfect label row also fails; this gold-row FR count cannot be changed by a model. |
| gold_fr:own_line | spike/630ef18b78a3 | East Cider Dry | East Cider Dry accept | b0152: $5; b0153: $5 | Perfect label row also fails; this gold-row FR count cannot be changed by a model. |
| gold_fr:name_number | p5-10/3e035f21ac55 | no parsed nearby raw row | no nearby final row | b0051: chiptole mayo; b0052: on jalapeno cheese bread 13 | Perfect label row also fails; this gold-row FR count cannot be changed by a model. |

### Visible paired differences against both fresh subset baselines

Differences of ratios under10,000 paired page-clustered resamples, seed20261015. Each resampled page carries all its rows. Small-cohort intervals describe these selected pages and exclude run-to-run model randomness; they do not establish full-cohort generalization.

| Run | Set | Metric | Δ [95% CI] vsA | Δ [95% CI] vsB |
| --- | --- | --- | --- | --- |
| screen-baseline-qkm | spike | usable_prices | 0.0167 [-0.0400, 0.1176] | 0.0100 [-0.0400, 0.1176] |
| screen-baseline-qkm | spike | item_recall_kept | 0.0149 [0.0000, 0.0667] | 0.0149 [0.0000, 0.0667] |
| screen-baseline-qkm | p5-5 | usable_prices | 0.0435 [-0.1667, 0.1176] | 0.0870 [0.0000, 0.1176] |
| screen-baseline-qkm | p5-5 | item_recall_kept | -0.0387 [-0.0667, -0.0357] | -0.0129 [-0.0667, -0.0071] |
| screen-baseline-qkm | p5-8 | usable_prices | -0.0439 [-0.1579, 0.0702] | -0.0702 [-0.1404, 0.0000] |
| screen-baseline-qkm | p5-8 | item_recall_kept | -0.0619 [-0.1633, 0.0417] | -0.0825 [-0.1633, 0.0000] |
| screen-baseline-qkm | p5-10 | usable_prices | 0.0081 [0.0000, 0.0333] | -0.0407 [-0.0645, 0.0333] |
| screen-baseline-qkm | p5-10 | item_recall_kept | 0.1212 [0.1159, 0.1333] | 0.0909 [0.0725, 0.1333] |
| screen-baseline-qkm | p5-12 | usable_prices | 0.0150 [0.0123, 0.0192] | 0.0000 [-0.0123, 0.0192] |
| screen-baseline-qkm | p5-12 | item_recall_kept | 0.0000 [0.0000, 0.0000] | -0.0092 [-0.0161, 0.0000] |
| screen-baseline-qkm | p5-14 | usable_prices | 0.0189 [0.0127, 0.0370] | -0.0094 [-0.0253, 0.0370] |
| screen-baseline-qkm | p5-14 | item_recall_kept | -0.0114 [-0.0299, 0.0476] | -0.0114 [-0.0299, 0.0476] |
| screen-baseline-qkm | p5-16 | usable_prices | -0.1205 [-0.2000, -0.0693] | -0.1325 [-0.2000, -0.0891] |
| screen-baseline-qkm | p5-16 | item_recall_kept | -0.0426 [-0.0851, -0.0213] | -0.0638 [-0.0851, -0.0532] |
| screen-baseline-qkm | pooled | usable_prices | -0.0145 [-0.0588, 0.0205] | -0.0322 [-0.0721, 0.0013] |
| screen-baseline-qkm | pooled | item_recall_kept | -0.0020 [-0.0330, 0.0281] | -0.0068 [-0.0374, 0.0171] |
| screen-q35-2b | spike | usable_prices | -0.2876 [-0.6800, -0.2000] | -0.2943 [-0.6800, -0.2083] |
| screen-q35-2b | spike | item_recall_kept | -0.3134 [-0.6667, -0.1714] | -0.3134 [-0.6667, -0.1714] |
| screen-q35-2b | p5-5 | usable_prices | -0.4783 [-0.5294, -0.3333] | -0.4348 [-0.5294, -0.1667] |
| screen-q35-2b | p5-5 | item_recall_kept | -0.1613 [-0.1786, 0.0000] | -0.1355 [-0.1500, 0.0000] |
| screen-q35-2b | p5-8 | usable_prices | -0.2807 [-0.3158, -0.2456] | -0.3070 [-0.3860, -0.2281] |
| screen-q35-2b | p5-8 | item_recall_kept | -0.1340 [-0.1633, -0.1042] | -0.1546 [-0.1633, -0.1458] |
| screen-q35-2b | p5-10 | usable_prices | -0.4228 [-0.5806, 0.0667] | -0.4715 [-0.6452, 0.0667] |
| screen-q35-2b | p5-10 | item_recall_kept | -0.1212 [-0.4203, 0.5667] | -0.1515 [-0.4638, 0.5667] |
| screen-q35-2b | p5-12 | usable_prices | -0.4211 [-0.4231, -0.4198] | -0.4361 [-0.4444, -0.4231] |
| screen-q35-2b | p5-12 | item_recall_kept | -0.4312 [-0.4468, -0.4194] | -0.4404 [-0.4468, -0.4355] |
| screen-q35-2b | p5-14 | usable_prices | -0.2736 [-0.6296, -0.1519] | -0.3019 [-0.6296, -0.1899] |
| screen-q35-2b | p5-14 | item_recall_kept | -0.1250 [-0.2857, -0.0746] | -0.1250 [-0.2857, -0.0746] |
| screen-q35-2b | p5-16 | usable_prices | -0.4157 [-0.6931, 0.0154] | -0.4277 [-0.7129, 0.0154] |
| screen-q35-2b | p5-16 | item_recall_kept | -0.5106 [-0.7660, 0.0000] | -0.5319 [-0.7979, 0.0000] |
| screen-q35-2b | pooled | usable_prices | -0.3475 [-0.4961, -0.2339] | -0.3651 [-0.5193, -0.2450] |
| screen-q35-2b | pooled | item_recall_kept | -0.2783 [-0.4046, -0.1493] | -0.2832 [-0.4171, -0.1506] |
| screen-q35-4b | spike | usable_prices | -0.0368 [-0.0667, 0.1765] | -0.0435 [-0.0750, 0.1765] |
| screen-q35-4b | spike | item_recall_kept | -0.0119 [-0.0333, 0.1667] | -0.0119 [-0.0333, 0.1667] |
| screen-q35-4b | p5-5 | usable_prices | -0.2609 [-0.3333, -0.2353] | -0.2174 [-0.2353, -0.1667] |
| screen-q35-4b | p5-5 | item_recall_kept | -0.3032 [-0.5333, -0.2786] | -0.2774 [-0.5333, -0.2500] |
| screen-q35-4b | p5-8 | usable_prices | -0.1053 [-0.2105, 0.0000] | -0.1316 [-0.2807, 0.0175] |
| screen-q35-4b | p5-8 | item_recall_kept | -0.0825 [-0.1667, 0.0000] | -0.1031 [-0.2083, 0.0000] |
| screen-q35-4b | p5-10 | usable_prices | -0.0813 [-0.1505, 0.1333] | -0.1301 [-0.2151, 0.1333] |
| screen-q35-4b | p5-10 | item_recall_kept | 0.0000 [-0.0870, 0.2000] | -0.0303 [-0.1304, 0.2000] |
| screen-q35-4b | p5-12 | usable_prices | -0.0075 [-0.0494, 0.0577] | -0.0226 [-0.0741, 0.0577] |
| screen-q35-4b | p5-12 | item_recall_kept | -0.0183 [-0.0968, 0.0851] | -0.0275 [-0.1129, 0.0851] |
| screen-q35-4b | p5-14 | usable_prices | 0.0094 [-0.2593, 0.1013] | -0.0189 [-0.2593, 0.0633] |
| screen-q35-4b | p5-14 | item_recall_kept | 0.0000 [-0.2381, 0.0746] | 0.0000 [-0.2381, 0.0746] |
| screen-q35-4b | p5-16 | usable_prices | -0.1205 [-0.1287, -0.1077] | -0.1325 [-0.1485, -0.1077] |
| screen-q35-4b | p5-16 | item_recall_kept | -0.1135 [-0.1489, -0.0957] | -0.1348 [-0.1489, -0.1277] |
| screen-q35-4b | pooled | usable_prices | -0.0612 [-0.1089, -0.0053] | -0.0788 [-0.1351, -0.0181] |
| screen-q35-4b | pooled | item_recall_kept | -0.0752 [-0.1500, -0.0104] | -0.0801 [-0.1501, -0.0168] |
| screen-q3-8b | spike | usable_prices | 0.0435 [-0.1200, 0.1765] | 0.0368 [-0.1200, 0.1765] |
| screen-q3-8b | spike | item_recall_kept | -0.0418 [-0.0857, 0.1667] | -0.0418 [-0.0857, 0.1667] |
| screen-q3-8b | p5-5 | usable_prices | -0.1739 [-0.8333, 0.0588] | -0.1304 [-0.6667, 0.0588] |
| screen-q3-8b | p5-5 | item_recall_kept | -0.3097 [-0.3357, -0.0667] | -0.2839 [-0.3071, -0.0667] |
| screen-q3-8b | p5-8 | usable_prices | -0.1667 [-0.2456, -0.0877] | -0.1930 [-0.2281, -0.1579] |
| screen-q3-8b | p5-8 | item_recall_kept | -0.0928 [-0.1042, -0.0816] | -0.1134 [-0.1458, -0.0816] |
| screen-q3-8b | p5-10 | usable_prices | 0.0569 [0.0108, 0.2000] | 0.0081 [-0.0538, 0.2000] |
| screen-q3-8b | p5-10 | item_recall_kept | 0.1111 [0.0145, 0.3333] | 0.0808 [-0.0290, 0.3333] |
| screen-q3-8b | p5-12 | usable_prices | 0.0677 [0.0247, 0.1346] | 0.0526 [0.0000, 0.1346] |
| screen-q3-8b | p5-12 | item_recall_kept | 0.1009 [0.0645, 0.1489] | 0.0917 [0.0484, 0.1489] |
| screen-q3-8b | p5-14 | usable_prices | 0.0472 [0.0000, 0.0633] | 0.0189 [0.0000, 0.0253] |
| screen-q3-8b | p5-14 | item_recall_kept | 0.0455 [0.0448, 0.0476] | 0.0455 [0.0448, 0.0476] |
| screen-q3-8b | p5-16 | usable_prices | -0.0964 [-0.2154, -0.0198] | -0.1084 [-0.2154, -0.0396] |
| screen-q3-8b | p5-16 | item_recall_kept | -0.0213 [-0.1702, 0.0532] | -0.0426 [-0.1702, 0.0213] |
| screen-q3-8b | pooled | usable_prices | -0.0052 [-0.0733, 0.0435] | -0.0228 [-0.0878, 0.0273] |
| screen-q3-8b | pooled | item_recall_kept | -0.0469 [-0.1371, 0.0478] | -0.0518 [-0.1323, 0.0347] |
| screen-q25-7b | spike | usable_prices | 0.0268 [-0.2000, 0.2353] | 0.0201 [-0.2000, 0.2353] |
| screen-q25-7b | spike | item_recall_kept | -0.0925 [-0.2571, 0.2000] | -0.0925 [-0.2571, 0.2000] |
| screen-q25-7b | p5-5 | usable_prices | -0.0870 [-0.6667, 0.1176] | -0.0435 [-0.5000, 0.1176] |
| screen-q25-7b | p5-5 | item_recall_kept | -0.5484 [-0.6071, 0.0000] | -0.5226 [-0.5786, 0.0000] |
| screen-q25-7b | p5-8 | usable_prices | 0.0263 [0.0175, 0.0351] | 0.0000 [-0.0351, 0.0351] |
| screen-q25-7b | p5-8 | item_recall_kept | -0.0206 [-0.0417, 0.0000] | -0.0412 [-0.0833, 0.0000] |
| screen-q25-7b | p5-10 | usable_prices | 0.0244 [-0.1000, 0.0645] | -0.0244 [-0.1000, 0.0000] |
| screen-q25-7b | p5-10 | item_recall_kept | 0.0808 [0.0000, 0.1159] | 0.0505 [0.0000, 0.0725] |
| screen-q25-7b | p5-12 | usable_prices | 0.0902 [0.0741, 0.1154] | 0.0752 [0.0494, 0.1154] |
| screen-q25-7b | p5-12 | item_recall_kept | 0.0459 [0.0000, 0.1064] | 0.0367 [-0.0161, 0.1064] |
| screen-q25-7b | p5-14 | usable_prices | -0.0189 [-0.0506, 0.0741] | -0.0472 [-0.0886, 0.0741] |
| screen-q25-7b | p5-14 | item_recall_kept | -0.0341 [-0.0746, 0.0952] | -0.0341 [-0.0746, 0.0952] |
| screen-q25-7b | p5-16 | usable_prices | -0.2048 [-0.2376, -0.1538] | -0.2169 [-0.2574, -0.1538] |
| screen-q25-7b | p5-16 | item_recall_kept | -0.1986 [-0.2447, -0.1064] | -0.2199 [-0.2766, -0.1064] |
| screen-q25-7b | pooled | usable_prices | -0.0124 [-0.0841, 0.0450] | -0.0301 [-0.1006, 0.0272] |
| screen-q25-7b | pooled | item_recall_kept | -0.1328 [-0.2785, 0.0010] | -0.1377 [-0.2753, -0.0119] |

### Real-output safety and [5b]

| Set | Run | Accepted unmatched | Wrong price accepted | Claimed-block anchor n/d | Page-verbatim copy n/d | Real FR n/d | Real catch n/d | [5b] accepts | [5b] exact n/d | [5b] unmatched |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 10 | 4 | 322/350 (0.9200) | 345/350 (0.9857) | 3/272 (0.0110) | 20/34 (0.5882) | 0 | 0/0 (n/a) | 0 |
| spike | screen-baseline-b | 13 | 4 | 325/353 (0.9207) | 350/353 (0.9915) | 2/273 (0.0073) | 21/38 (0.5526) | 0 | 0/0 (n/a) | 0 |
| spike | screen-baseline-qkm | 10 | 7 | 301/356 (0.8455) | 349/356 (0.9803) | 11/291 (0.0378) | 14/31 (0.4516) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q25-7b | 11 | 5 | 247/452 (0.5465) | 433/452 (0.9580) | 3/281 (0.0107) | 42/58 (0.7241) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q3-8b | 26 | 12 | 344/394 (0.8731) | 394/394 (1.0000) | 12/293 (0.0410) | 54/92 (0.5870) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q35-2b | 45 | 6 | 278/375 (0.7413) | 363/375 (0.9680) | 11/193 (0.0570) | 137/188 (0.7287) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q35-4b | 19 | 3 | 318/349 (0.9112) | 325/349 (0.9312) | 0/259 (0.0000) | 10/32 (0.3125) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-a | 8 | 2 | 227/247 (0.9190) | 246/247 (0.9960) | 7/25 (0.2800) | 18/28 (0.6429) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-b | 8 | 2 | 221/235 (0.9404) | 233/235 (0.9915) | 7/23 (0.3043) | 17/27 (0.6296) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-qkm | 5 | 0 | 226/240 (0.9417) | 238/240 (0.9917) | 7/25 (0.2800) | 18/23 (0.7826) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q25-7b | 3 | 2 | 39/137 (0.2847) | 101/137 (0.7372) | 0/15 (0.0000) | 63/68 (0.9265) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q3-8b | 24 | 0 | 160/208 (0.7692) | 208/208 (1.0000) | 7/20 (0.3500) | 112/136 (0.8235) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q35-2b | 16 | 0 | 264/266 (0.9925) | 264/266 (0.9925) | 13/19 (0.6842) | 171/187 (0.9144) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q35-4b | 7 | 0 | 161/163 (0.9877) | 163/163 (1.0000) | 0/11 (0.0000) | 55/62 (0.8871) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-a | 12 | 1 | 137/190 (0.7211) | 187/190 (0.9842) | 20/117 (0.1709) | 59/72 (0.8194) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-b | 12 | 1 | 136/167 (0.8144) | 162/167 (0.9701) | 2/101 (0.0198) | 57/70 (0.8143) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-qkm | 12 | 0 | 143/169 (0.8462) | 169/169 (1.0000) | 3/94 (0.0319) | 65/77 (0.8442) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q25-7b | 10 | 0 | 110/194 (0.5670) | 178/194 (0.9175) | 24/125 (0.1920) | 55/65 (0.8462) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q3-8b | 14 | 1 | 93/190 (0.4895) | 185/190 (0.9737) | 14/93 (0.1505) | 84/99 (0.8485) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q35-2b | 26 | 3 | 233/279 (0.8351) | 275/279 (0.9857) | 38/102 (0.3725) | 129/158 (0.8165) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q35-4b | 20 | 0 | 97/156 (0.6218) | 151/156 (0.9679) | 18/102 (0.1765) | 29/49 (0.5918) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-a | 2 | 0 | 97/128 (0.7578) | 122/128 (0.9531) | 3/85 (0.0353) | 24/26 (0.9231) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-b | 7 | 0 | 119/148 (0.8041) | 140/148 (0.9459) | 10/97 (0.1031) | 26/33 (0.7879) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-qkm | 5 | 0 | 104/138 (0.7536) | 133/138 (0.9638) | 8/88 (0.0909) | 42/47 (0.8936) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q25-7b | 2 | 0 | 144/228 (0.6316) | 190/228 (0.8333) | 26/109 (0.2385) | 66/68 (0.9706) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q3-8b | 10 | 0 | 169/188 (0.8989) | 188/188 (1.0000) | 16/105 (0.1524) | 62/72 (0.8611) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q35-2b | 18 | 0 | 236/282 (0.8369) | 257/282 (0.9113) | 17/44 (0.3864) | 53/71 (0.7465) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q35-4b | 9 | 0 | 98/118 (0.8305) | 115/118 (0.9746) | 11/80 (0.1375) | 27/36 (0.7500) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-a | 7 | 0 | 122/148 (0.8243) | 147/148 (0.9932) | 34/123 (0.2764) | 10/17 (0.5882) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-b | 11 | 0 | 131/157 (0.8344) | 157/157 (1.0000) | 33/123 (0.2683) | 11/22 (0.5000) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-qkm | 14 | 1 | 147/163 (0.9018) | 163/163 (1.0000) | 36/135 (0.2667) | 2/17 (0.1176) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q25-7b | 10 | 1 | 104/183 (0.5683) | 183/183 (1.0000) | 41/140 (0.2929) | 28/39 (0.7179) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q3-8b | 28 | 0 | 164/215 (0.7628) | 215/215 (1.0000) | 55/159 (0.3459) | 26/54 (0.4815) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q35-2b | 14 | 1 | 139/267 (0.5206) | 267/267 (1.0000) | 54/80 (0.6750) | 128/143 (0.8951) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q35-4b | 12 | 2 | 145/165 (0.8788) | 165/165 (1.0000) | 46/129 (0.3566) | 11/25 (0.4400) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-a | 0 | 3 | 70/112 (0.6250) | 112/112 (1.0000) | 10/104 (0.0962) | 4/7 (0.5714) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-b | 1 | 2 | 72/106 (0.6792) | 104/106 (0.9811) | 4/100 (0.0400) | 2/5 (0.4000) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-qkm | 4 | 3 | 75/106 (0.7075) | 106/106 (1.0000) | 5/101 (0.0495) | 0/7 (0.0000) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q25-7b | 5 | 5 | 77/120 (0.6417) | 111/120 (0.9250) | 9/102 (0.0882) | 9/19 (0.4737) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q3-8b | 2 | 2 | 94/113 (0.8319) | 113/113 (1.0000) | 7/106 (0.0660) | 5/9 (0.5556) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q35-2b | 15 | 2 | 125/235 (0.5319) | 235/235 (1.0000) | 60/126 (0.4762) | 34/51 (0.6667) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q35-4b | 8 | 2 | 84/112 (0.7500) | 112/112 (1.0000) | 11/105 (0.1048) | 0/10 (0.0000) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-a | 16 | 1 | 116/205 (0.5659) | 205/205 (1.0000) | 45/176 (0.2557) | 17/34 (0.5000) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-b | 15 | 1 | 116/208 (0.5577) | 208/208 (1.0000) | 45/178 (0.2528) | 18/34 (0.5294) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-qkm | 22 | 2 | 166/202 (0.8218) | 196/202 (0.9703) | 27/138 (0.1957) | 23/47 (0.4894) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q25-7b | 9 | 0 | 76/215 (0.3535) | 206/215 (0.9581) | 80/179 (0.4469) | 28/37 (0.7568) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q3-8b | 25 | 2 | 148/224 (0.6607) | 224/224 (1.0000) | 37/152 (0.2434) | 57/84 (0.6786) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q35-2b | 24 | 1 | 126/246 (0.5122) | 240/246 (0.9756) | 62/124 (0.5000) | 95/120 (0.7917) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q35-4b | 19 | 1 | 126/228 (0.5526) | 184/228 (0.8070) | 23/135 (0.1704) | 27/47 (0.5745) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-a | 55 | 11 | 1091/1380 (0.7906) | 1364/1380 (0.9884) | 122/902 (0.1353) | 152/218 (0.6972) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-b | 67 | 10 | 1120/1374 (0.8151) | 1354/1374 (0.9854) | 103/895 (0.1151) | 152/229 (0.6638) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-qkm | 72 | 13 | 1162/1374 (0.8457) | 1354/1374 (0.9854) | 97/872 (0.1112) | 164/249 (0.6586) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q25-7b | 50 | 13 | 797/1529 (0.5213) | 1402/1529 (0.9169) | 183/951 (0.1924) | 291/354 (0.8220) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q3-8b | 129 | 17 | 1172/1532 (0.7650) | 1527/1532 (0.9967) | 148/928 (0.1595) | 400/546 (0.7326) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q35-2b | 158 | 13 | 1401/1950 (0.7185) | 1901/1950 (0.9749) | 255/688 (0.3706) | 747/918 (0.8137) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q35-4b | 94 | 8 | 1029/1291 (0.7971) | 1215/1291 (0.9411) | 109/821 (0.1328) | 159/261 (0.6092) | 0 | 0/0 (n/a) | 0 |

**The amended reduced-screen copy gate is page-verbatim copy (`copy_anywhere`):** case/punctuation-sensitive substring occurrence anywhere on the printed page among complete parsed raw rows of selected attempts. Claimed-block substring fidelity is separately reported as an anchor diagnostic, not the primary copy gate. Incomplete rows are outside that denominator; truncation/schema rates are separately preserved in score JSON. No rise in accepted unmatched or matched wrong-price rows is allowed by the numerical gates. The original218-page claimed-block gate remains historical; reduced decision JSON implements the pre-candidate amendment.

| Set | Run | Chunks | Selected schema failures n/d | Selected truncations n/d | Sparse retries n/d | All-attempt schema failures | All-attempt truncations | Generated thinking-marker attempts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 22 | 0/22 (0.0000) | 0/22 (0.0000) | 0/22 (0.0000) | 0 | 0 | 0 |
| spike | screen-baseline-b | 22 | 0/22 (0.0000) | 0/22 (0.0000) | 0/22 (0.0000) | 0 | 0 | 0 |
| spike | screen-baseline-qkm | 22 | 0/22 (0.0000) | 0/22 (0.0000) | 0/22 (0.0000) | 0 | 0 | 0 |
| spike | screen-q25-7b | 22 | 2/22 (0.0909) | 2/22 (0.0909) | 0/22 (0.0000) | 2 | 2 | 0 |
| spike | screen-q3-8b | 22 | 0/22 (0.0000) | 0/22 (0.0000) | 0/22 (0.0000) | 0 | 0 | 0 |
| spike | screen-q35-2b | 22 | 0/22 (0.0000) | 0/22 (0.0000) | 5/22 (0.2273) | 0 | 0 | 0 |
| spike | screen-q35-4b | 22 | 0/22 (0.0000) | 0/22 (0.0000) | 0/22 (0.0000) | 0 | 0 | 0 |
| p5-5 | screen-baseline-a | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-5 | screen-baseline-b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-5 | screen-baseline-qkm | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-5 | screen-q25-7b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 1/10 (0.1000) | 0 | 0 | 0 |
| p5-5 | screen-q3-8b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-5 | screen-q35-2b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 1/10 (0.1000) | 0 | 0 | 0 |
| p5-5 | screen-q35-4b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 1/10 (0.1000) | 0 | 0 | 0 |
| p5-8 | screen-baseline-a | 10 | 1/10 (0.1000) | 1/10 (0.1000) | 0/10 (0.0000) | 1 | 1 | 0 |
| p5-8 | screen-baseline-b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-8 | screen-baseline-qkm | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-8 | screen-q25-7b | 10 | 1/10 (0.1000) | 1/10 (0.1000) | 0/10 (0.0000) | 1 | 1 | 0 |
| p5-8 | screen-q3-8b | 10 | 1/10 (0.1000) | 1/10 (0.1000) | 0/10 (0.0000) | 1 | 1 | 0 |
| p5-8 | screen-q35-2b | 10 | 1/10 (0.1000) | 1/10 (0.1000) | 2/10 (0.2000) | 1 | 1 | 0 |
| p5-8 | screen-q35-4b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 1/10 (0.1000) | 0 | 0 | 0 |
| p5-10 | screen-baseline-a | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-10 | screen-baseline-b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-10 | screen-baseline-qkm | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-10 | screen-q25-7b | 10 | 1/10 (0.1000) | 1/10 (0.1000) | 0/10 (0.0000) | 1 | 1 | 0 |
| p5-10 | screen-q3-8b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-10 | screen-q35-2b | 10 | 1/10 (0.1000) | 1/10 (0.1000) | 3/10 (0.3000) | 1 | 1 | 0 |
| p5-10 | screen-q35-4b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-baseline-a | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-baseline-b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-baseline-qkm | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-q25-7b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-q3-8b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-q35-2b | 10 | 1/10 (0.1000) | 1/10 (0.1000) | 4/10 (0.4000) | 1 | 1 | 0 |
| p5-12 | screen-q35-4b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 2/10 (0.2000) | 0 | 0 | 0 |
| p5-14 | screen-baseline-a | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-14 | screen-baseline-b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-14 | screen-baseline-qkm | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-14 | screen-q25-7b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-14 | screen-q3-8b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-14 | screen-q35-2b | 10 | 1/10 (0.1000) | 1/10 (0.1000) | 0/10 (0.0000) | 1 | 1 | 0 |
| p5-14 | screen-q35-4b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-baseline-a | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-baseline-b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-baseline-qkm | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-q25-7b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-q3-8b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 0/10 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-q35-2b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 5/10 (0.5000) | 0 | 0 | 0 |
| p5-16 | screen-q35-4b | 10 | 0/10 (0.0000) | 0/10 (0.0000) | 1/10 (0.1000) | 0 | 0 | 0 |
| pooled | screen-baseline-a | 82 | 1/82 (0.0122) | 1/82 (0.0122) | 0/82 (0.0000) | 1 | 1 | 0 |
| pooled | screen-baseline-b | 82 | 0/82 (0.0000) | 0/82 (0.0000) | 0/82 (0.0000) | 0 | 0 | 0 |
| pooled | screen-baseline-qkm | 82 | 0/82 (0.0000) | 0/82 (0.0000) | 0/82 (0.0000) | 0 | 0 | 0 |
| pooled | screen-q25-7b | 82 | 4/82 (0.0488) | 4/82 (0.0488) | 1/82 (0.0122) | 4 | 4 | 0 |
| pooled | screen-q3-8b | 82 | 1/82 (0.0122) | 1/82 (0.0122) | 0/82 (0.0000) | 1 | 1 | 0 |
| pooled | screen-q35-2b | 82 | 4/82 (0.0488) | 4/82 (0.0488) | 20/82 (0.2439) | 4 | 4 | 0 |
| pooled | screen-q35-4b | 82 | 0/82 (0.0000) | 0/82 (0.0000) | 5/82 (0.0610) | 0 | 0 | 0 |

### Model-invariant validator evidence

| Set | Gold-row FR, model invariant | Injected-corruption catch, model invariant |
| --- | --- | --- |
| spike | 1/299 (0.0033) | 133/138 (0.9638) |
| p5-5 | 4/23 (0.1739) | 80/80 (1.0000) |
| p5-8 | 3/114 (0.0263) | 100/100 (1.0000) |
| p5-10 | 36/123 (0.2927) | 98/98 (1.0000) |
| p5-12 | 29/133 (0.2180) | 100/100 (1.0000) |
| p5-14 | 10/106 (0.0943) | 99/100 (0.9900) |
| p5-16 | 35/166 (0.2108) | 96/96 (1.0000) |
| pooled | 118/964 (0.1224) | 706/712 (0.9916) (sum of per-set trials) |

Gold-row FR and injected-corruption catch do not vary with the extraction model. They cannot be counted as a model benefit. The original next-draw pooled gold-FR blocker near0.095 versus target near0.05 is unaffected; a reduced phase does not authorize the next held-out draw.

### Subset numerical gate outcomes

| Run | Frozen criterion gate | Result | Reason | Evidence |
| --- | --- | --- | --- | --- |
| screen-baseline-qkm | worthwhile_gain | inconclusive | Usable prices OR kept item recall must clear against BOTH baseline replicates; gains cannot mix metrics across baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | pooled_raw_recall | pass | Frozen §8 raw item recall bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | pooled_price_accuracy | pass | Frozen §8 accepted matched price accuracy bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | price_accuracy_noninferiority | fail | Price accuracy safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | previously_passing_sets | fail | No previously passing tuning-set raw-recall or accuracy bar may be crossed. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | accepted_unmatched | fail | Absolute count must be no greater than either baseline for accepted_unmatched. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | wrong_accepted_price | fail | Absolute count must be no greater than either baseline for wrong_accepted_price. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | exact_name_copy | fail | No worse exact-name copy fidelity against either baseline. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | validator_false_reject | pass | Real-output validator_false_reject safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | validator_catch | fail | Real-output validator_catch safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json) |
| screen-q25-7b | worthwhile_gain | inconclusive | Usable prices OR kept item recall must clear against BOTH baseline replicates; gains cannot mix metrics across baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | pooled_raw_recall | fail | Frozen §8 raw item recall bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | pooled_price_accuracy | pass | Frozen §8 accepted matched price accuracy bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | price_accuracy_noninferiority | fail | Price accuracy safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | previously_passing_sets | fail | No previously passing tuning-set raw-recall or accuracy bar may be crossed. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | accepted_unmatched | pass | Absolute count must be no greater than either baseline for accepted_unmatched. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | wrong_accepted_price | fail | Absolute count must be no greater than either baseline for wrong_accepted_price. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | exact_name_copy | fail | No worse exact-name copy fidelity against either baseline. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | validator_false_reject | fail | Real-output validator_false_reject safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | validator_catch | pass | Real-output validator_catch safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json) |
| screen-q3-8b | worthwhile_gain | inconclusive | Usable prices OR kept item recall must clear against BOTH baseline replicates; gains cannot mix metrics across baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | pooled_raw_recall | pass | Frozen §8 raw item recall bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | pooled_price_accuracy | fail | Frozen §8 accepted matched price accuracy bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | price_accuracy_noninferiority | fail | Price accuracy safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | previously_passing_sets | fail | No previously passing tuning-set raw-recall or accuracy bar may be crossed. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | accepted_unmatched | fail | Absolute count must be no greater than either baseline for accepted_unmatched. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | wrong_accepted_price | fail | Absolute count must be no greater than either baseline for wrong_accepted_price. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | exact_name_copy | pass | No worse exact-name copy fidelity against either baseline. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | validator_false_reject | fail | Real-output validator_false_reject safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | validator_catch | pass | Real-output validator_catch safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json) |
| screen-q35-2b | worthwhile_gain | fail | Usable prices OR kept item recall must clear against BOTH baseline replicates; gains cannot mix metrics across baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | pooled_raw_recall | fail | Frozen §8 raw item recall bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | pooled_price_accuracy | fail | Frozen §8 accepted matched price accuracy bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | price_accuracy_noninferiority | fail | Price accuracy safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | previously_passing_sets | fail | No previously passing tuning-set raw-recall or accuracy bar may be crossed. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | accepted_unmatched | fail | Absolute count must be no greater than either baseline for accepted_unmatched. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | wrong_accepted_price | fail | Absolute count must be no greater than either baseline for wrong_accepted_price. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | exact_name_copy | fail | No worse exact-name copy fidelity against either baseline. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | validator_false_reject | fail | Real-output validator_false_reject safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-2b | validator_catch | pass | Real-output validator_catch safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json) |
| screen-q35-4b | worthwhile_gain | fail | Usable prices OR kept item recall must clear against BOTH baseline replicates; gains cannot mix metrics across baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | pooled_raw_recall | fail | Frozen §8 raw item recall bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | pooled_price_accuracy | pass | Frozen §8 accepted matched price accuracy bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | price_accuracy_noninferiority | pass | Price accuracy safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | previously_passing_sets | fail | No previously passing tuning-set raw-recall or accuracy bar may be crossed. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | accepted_unmatched | fail | Absolute count must be no greater than either baseline for accepted_unmatched. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | wrong_accepted_price | pass | Absolute count must be no greater than either baseline for wrong_accepted_price. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | exact_name_copy | fail | No worse exact-name copy fidelity against either baseline. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | validator_false_reject | pass | Real-output validator_false_reject safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |
| screen-q35-4b | validator_catch | fail | Real-output validator_catch safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json) |

**screen-baseline-qkm: fails_criterion on 15 selected pages only.** Subset checks clear=False; full218-page acceptance is untested. [all gate evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/decision-v9.json).

**screen-q25-7b: fails_criterion on 15 selected pages only.** Subset checks clear=False; full218-page acceptance is untested. [all gate evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/decision-v9.json).

**screen-q3-8b: fails_criterion on 15 selected pages only.** Subset checks clear=False; full218-page acceptance is untested. [all gate evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/decision-v9.json).

**screen-q35-2b: fails_criterion on 15 selected pages only.** Subset checks clear=False; full218-page acceptance is untested. [all gate evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/decision-v9.json).

**screen-q35-4b: fails_criterion on 15 selected pages only.** Subset checks clear=False; full218-page acceptance is untested. [all gate evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/decision-v9.json).

### Fixed difficult-page slices and proxy regressions

| Run | Fixed overlapping slice | Pages | Baseline A usable | Candidate usable | Δusable [paired95% CI] vsA | Kept recall A→candidate |
| --- | --- | --- | --- | --- | --- | --- |
| screen-baseline-qkm | rare_formats | 2 | 0.9057 | 0.8822 | -0.0236 [-0.1579, 0.0083] | 0.9091 → 0.8934 |
| screen-baseline-qkm | price_before_name | 5 | 0.6928 | 0.6807 | -0.0120 [-0.0473, 0.0256] | 0.8152 → 0.8551 |
| screen-baseline-qkm | multiple_prices | 12 | 0.8062 | 0.7918 | -0.0144 [-0.0620, 0.0233] | 0.8877 → 0.8864 |
| screen-baseline-qkm | structural_fr | 10 | 0.7281 | 0.6843 | -0.0438 [-0.0991, 0.0092] | 0.8486 → 0.8443 |
| screen-q25-7b | rare_formats | 2 | 0.9057 | 0.9259 | 0.0202 [0.0175, 0.0208] | 0.9091 → 0.8213 |
| screen-q25-7b | price_before_name | 5 | 0.6928 | 0.6536 | -0.0392 [-0.1799, 0.0712] | 0.8152 → 0.7681 |
| screen-q25-7b | multiple_prices | 12 | 0.8062 | 0.8062 | 0.0000 [-0.0730, 0.0644] | 0.8877 → 0.8364 |
| screen-q25-7b | structural_fr | 10 | 0.7281 | 0.6934 | -0.0347 [-0.1333, 0.0561] | 0.8486 → 0.8017 |
| screen-q3-8b | rare_formats | 2 | 0.9057 | 0.8923 | -0.0135 [-0.2456, 0.0417] | 0.9091 → 0.8464 |
| screen-q3-8b | price_before_name | 5 | 0.6928 | 0.7139 | 0.0211 [-0.0097, 0.0873] | 0.8152 → 0.8913 |
| screen-q3-8b | multiple_prices | 12 | 0.8062 | 0.8029 | -0.0033 [-0.0738, 0.0446] | 0.8877 → 0.8779 |
| screen-q3-8b | structural_fr | 10 | 0.7281 | 0.6989 | -0.0292 [-0.1109, 0.0470] | 0.8486 → 0.8742 |
| screen-q35-2b | rare_formats | 2 | 0.9057 | 0.6970 | -0.2088 [-0.2456, -0.2000] | 0.9091 → 0.6364 |
| screen-q35-2b | price_before_name | 5 | 0.6928 | 0.1717 | -0.5211 [-0.6533, -0.3095] | 0.8152 → 0.3949 |
| screen-q35-2b | multiple_prices | 12 | 0.8062 | 0.4540 | -0.3522 [-0.5119, -0.2349] | 0.8877 → 0.5568 |
| screen-q35-2b | structural_fr | 10 | 0.7281 | 0.3011 | -0.4270 [-0.5771, -0.2373] | 0.8486 → 0.5267 |
| screen-q35-4b | rare_formats | 2 | 0.9057 | 0.8519 | -0.0539 [-0.0667, 0.0000] | 0.9091 → 0.8809 |
| screen-q35-4b | price_before_name | 5 | 0.6928 | 0.5904 | -0.1024 [-0.1613, -0.0184] | 0.8152 → 0.7428 |
| screen-q35-4b | multiple_prices | 12 | 0.8062 | 0.7398 | -0.0664 [-0.1172, -0.0102] | 0.8877 → 0.8339 |
| screen-q35-4b | structural_fr | 10 | 0.7281 | 0.6496 | -0.0785 [-0.1276, -0.0164] | 0.8486 → 0.7825 |

Slices select whole pages and overlap; their metrics include every row on the selected page. Rare format means <=10 cohort pages; price-before-name uses fixed nearby token geometry; multiple-prices and structural-FR flags derive from frozen labels/validator. These are tuning diagnostics, not independent tests or item-level subgroup estimates.

| Run | Proxy class/direction | Page | Proxy A→candidate | Δusable numerator | Changed final rows | Printed source snippet | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| screen-baseline-qkm | misses fix | p5-8/ddb652ccea54 | 7.0000 → 5.0000 | 4 | baseline: Whole Pizza 15.99 accept; Whole Pizza 17.99 accept; candidate: WHOLE PIZZA 15.99 accept; WHOLE PIZZA 17.99 accept | b0028: WHOLE PIZZA | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/difficult.json) |
| screen-baseline-qkm | misses regression | p5-16/5d960df16b84 | 2.0000 → 6.0000 | -13 | baseline: By the Pound 42 accept; Brisket 42 accept; candidate: Brisket 42 accept; Brisket 42 reject | b0049: $42 / lb | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/difficult.json) |
| screen-baseline-qkm | names_unmatched_proxy regression | p5-8/a8684c49dfa1 | 2.0000 → 3.0000 | -9 | baseline: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept; candidate: Super-Bert Half Pounder 6.34 accept; Hot Ham & Swiss 5.19 accept | b0009: $4.99; b0010: Super-Bert Half Pounder | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/difficult.json) |
| screen-baseline-qkm | price_association_proxy regression | p5-16/5d960df16b84 | 2.0000 → 5.0000 | -13 | baseline: By the Pound 42 accept; Brisket 42 accept; candidate: Brisket 42 accept; Brisket 42 reject | b0049: $42 / lb | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/difficult.json) |
| screen-baseline-qkm | copy regression | p5-16/6d5cdfffe336 | 0.0891 → 0.0943 | -7 | baseline: Fajita Nachos 2.08 accept; Nachos 7.99 accept; candidate: Fajita 2.08 accept; Quesadillas 7.99 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/difficult.json) |
| screen-q25-7b | misses fix | spike/0824dfcdd900 | 6.0000 → 0.0000 | 8 | baseline: MARKET FISH SELECTION* 10 accept; MARKET FISH SELECTION* 17 accept; candidate: MARKET FISH SELECTION* 10 accept; MARKET FISH SELECTION* 17 accept | b0022: MARKET FISH SELECTION* | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | misses regression | p5-16/6d5cdfffe336 | 12.0000 → 32.0000 | -24 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | names_unmatched_proxy regression | p5-16/6d5cdfffe336 | 2.0000 → 5.0000 | -24 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | price_association_proxy regression | p5-16/6d5cdfffe336 | 4.0000 → 11.0000 | -24 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | copy regression | p5-16/6d5cdfffe336 | 0.0891 → 0.4176 | -24 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | schema regression | spike/630ef18b78a3 | 0.0000 → 1.0000 | -5 | baseline: MONTREAL FRIES 15 accept; ASIAN CRUNCH SALAD 13 accept; candidate: Montreal Fries 15 accept; Montreal Fries 13 downgrade | b0036: MONTREAL FRIES; b0035: $15 | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | truncation regression | spike/630ef18b78a3 | 0.0000 → 1.0000 | -5 | baseline: MONTREAL FRIES 15 accept; ASIAN CRUNCH SALAD 13 accept; candidate: Montreal Fries 15 accept; Montreal Fries 13 downgrade | b0036: MONTREAL FRIES; b0035: $15 | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/difficult.json) |
| screen-q3-8b | misses fix | spike/6a788f7d3b50 | 23.0000 → 12.0000 | 10 | baseline: Barbecued Spareribs 排骨 15.50 accept; Beef Teriyaki 牛串 13.50 accept; candidate: Barbecued Spareribs 排骨 15.50 accept; Beef Teriyaki 牛串 13.50 accept | b0022: Barbecued Spareribs 排骨 – $15.50 | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | misses regression | p5-16/5d960df16b84 | 2.0000 → 10.0000 | -14 | baseline: By the Pound 42 accept; Brisket 42 accept; candidate: By the Pound 42 accept; Brisket 42 accept | b0049: $42 / lb | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | names_unmatched_proxy regression | p5-8/a8684c49dfa1 | 2.0000 → 4.0000 | -14 | baseline: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept; candidate: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept | b0009: $4.99; b0007: Super-Bert Quarter Pounder | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | price_association_proxy regression | p5-8/a8684c49dfa1 | 1.0000 → 11.0000 | -14 | baseline: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept; candidate: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept | b0009: $4.99; b0007: Super-Bert Quarter Pounder | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | copy regression | p5-8/a8684c49dfa1 | 0.3393 → 0.4340 | -14 | baseline: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept; candidate: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept | b0009: $4.99; b0007: Super-Bert Quarter Pounder | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/difficult.json) |
| screen-q35-2b | misses fix | p5-10/3e035f21ac55 | 20.0000 → 3.0000 | 2 | baseline: sub home fries 3 3 accept; sub side salad 3.5 3.5 accept; candidate: WEEKEND n/a downgrade; TAKE OUT n/a downgrade | b0020: sub home fries 3; b0012: WEEKEND | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/difficult.json) |
| screen-q35-2b | misses regression | p5-16/6d5cdfffe336 | 12.0000 → 84.0000 | -70 | baseline: Nachos Compuestos 13.53 accept; Fajita Nachos 2.08 accept; candidate: My New Option 11.97 downgrade; Small $11.97 11.97 accept | b0017: Nachos Compuestos; b0060: My New Option | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/difficult.json) |
| screen-q35-2b | names_unmatched_proxy regression | p5-10/d9126c519b73 | 0.0000 → 9.0000 | -54 | baseline: Fried Pickles & Jalapeños 10 accept; Guacamole Bowl 12 accept; candidate: Starters 10 accept; Breads: Brioche 2.5 downgrade | b0022: Fried Pickles & Jalapeños; b0021: Starters | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/difficult.json) |
| screen-q35-2b | price_association_proxy regression | spike/6a788f7d3b50 | 2.0000 → 6.0000 | -48 | baseline: Barbecued Spareribs 排骨 15.50 accept; Beef Teriyaki 牛串 13.50 accept; candidate: Barbecued Spareribs 排骨 – $15.50 15.50 accept; Beef Teriyaki 牛串 – $13.50 13.50 accept | b0022: Barbecued Spareribs 排骨 – $15.50 | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/difficult.json) |
| screen-q35-2b | copy regression | p5-16/6d5cdfffe336 | 0.0891 → 0.3704 | -70 | baseline: Nachos Compuestos 13.53 accept; Fajita Nachos 2.08 accept; candidate: My New Option 11.97 downgrade; Small $11.97 11.97 accept | b0017: Nachos Compuestos; b0060: My New Option | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/difficult.json) |
| screen-q35-2b | schema regression | p5-10/d9126c519b73 | 0.0000 → 1.0000 | -54 | baseline: Fried Pickles & Jalapeños 10 accept; Guacamole Bowl 12 accept; candidate: Starters 10 accept; Breads: Brioche 2.5 downgrade | b0022: Fried Pickles & Jalapeños; b0021: Starters | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/difficult.json) |
| screen-q35-2b | truncation regression | p5-10/d9126c519b73 | 0.0000 → 1.0000 | -54 | baseline: Fried Pickles & Jalapeños 10 accept; Guacamole Bowl 12 accept; candidate: Starters 10 accept; Breads: Brioche 2.5 downgrade | b0022: Fried Pickles & Jalapeños; b0021: Starters | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/difficult.json) |
| screen-q35-4b | misses fix | p5-14/e845388448b9 | 5.0000 → 0.0000 | 8 | baseline: Housemade Granola 5.00 accept; Bowl 7.50 accept; candidate: Housemade Granola 5.00 accept; Housemade Granola 7.50 accept | b0043: Housemade Granola | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/difficult.json) |
| screen-q35-4b | misses regression | spike/6a788f7d3b50 | 23.0000 → 33.0000 | -16 | baseline: Barbecued Spareribs 排骨 15.50 accept; Beef Teriyaki 牛串 13.50 accept; candidate: Barbecued Spareribs 排骨 15.50 accept; Beef Teriyaki 牛串 13.50 accept | b0022: Barbecued Spareribs 排骨 – $15.50 | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/difficult.json) |
| screen-q35-4b | names_unmatched_proxy regression | p5-10/d9126c519b73 | 0.0000 → 8.0000 | -14 | baseline: Akaushi Wagyu 17 accept; Folsom Bleus 16 accept; candidate: Seared Ahi Tuna 18 accept; Gliders 19 accept | b0052: Akaushi Wagyu; b0033: Seared Ahi Tuna | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/difficult.json) |
| screen-q35-4b | price_association_proxy regression | p5-16/6d5cdfffe336 | 4.0000 → 8.0000 | -13 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/difficult.json) |
| screen-q35-4b | copy regression | spike/6a788f7d3b50 | 0.0195 → 0.0735 | -16 | baseline: Barbecued Spareribs 排骨 15.50 accept; Beef Teriyaki 牛串 13.50 accept; candidate: Barbecued Spareribs 排骨 15.50 accept; Beef Teriyaki 牛串 13.50 accept | b0022: Barbecued Spareribs 排骨 – $15.50 | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/difficult.json) |

Examples are automatically selected proxy changes, not manually adjudicated fixes, hallucinations or price-ownership errors. Names shown are final rows; linked evidence contains pre-repair raw rows and generated continuations alongside final verdicts. A proxy improvement can accompany a usable-price regression. Full slice membership and original-label slice results are preserved in each run’s difficult.json/difficult.md.

### Original-label continuity on the same selected pages

| Set | Run | Gold items | Gold price rows | Raw recall n/d | Kept recall n/d | Usable n/d | Price accuracy n/d |
| --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 335 | 299 | 305/335 (0.9104) | 304/335 (0.9075) | 268/299 (0.8963) | 269/273 (0.9853) |
| spike | screen-baseline-b | 335 | 299 | 304/335 (0.9075) | 304/335 (0.9075) | 270/299 (0.9030) | 271/275 (0.9855) |
| spike | screen-baseline-qkm | 335 | 299 | 309/335 (0.9224) | 309/335 (0.9224) | 273/299 (0.9130) | 280/287 (0.9756) |
| spike | screen-q25-7b | 335 | 299 | 284/335 (0.8478) | 273/335 (0.8149) | 276/299 (0.9231) | 278/283 (0.9823) |
| spike | screen-q3-8b | 335 | 299 | 318/335 (0.9493) | 290/335 (0.8657) | 281/299 (0.9398) | 281/293 (0.9590) |
| spike | screen-q35-2b | 335 | 299 | 199/335 (0.5940) | 199/335 (0.5940) | 182/299 (0.6087) | 182/188 (0.9681) |
| spike | screen-q35-4b | 335 | 299 | 300/335 (0.8955) | 300/335 (0.8955) | 257/299 (0.8595) | 259/262 (0.9885) |
| p5-5 | screen-baseline-a | 155 | 23 | 150/155 (0.9677) | 150/155 (0.9677) | 17/23 (0.7391) | 18/20 (0.9000) |
| p5-5 | screen-baseline-b | 155 | 23 | 146/155 (0.9419) | 146/155 (0.9419) | 16/23 (0.6957) | 16/18 (0.8889) |
| p5-5 | screen-baseline-qkm | 155 | 23 | 144/155 (0.9290) | 144/155 (0.9290) | 18/23 (0.7826) | 18/18 (1.0000) |
| p5-5 | screen-q25-7b | 155 | 23 | 77/155 (0.4968) | 65/155 (0.4194) | 15/23 (0.6522) | 15/17 (0.8824) |
| p5-5 | screen-q3-8b | 155 | 23 | 131/155 (0.8452) | 102/155 (0.6581) | 13/23 (0.5652) | 13/13 (1.0000) |
| p5-5 | screen-q35-2b | 155 | 23 | 151/155 (0.9742) | 125/155 (0.8065) | 6/23 (0.2609) | 6/6 (1.0000) |
| p5-5 | screen-q35-4b | 155 | 23 | 103/155 (0.6645) | 103/155 (0.6645) | 11/23 (0.4783) | 11/11 (1.0000) |
| p5-8 | screen-baseline-a | 97 | 114 | 85/97 (0.8763) | 85/97 (0.8763) | 96/114 (0.8421) | 97/98 (0.9898) |
| p5-8 | screen-baseline-b | 97 | 114 | 87/97 (0.8969) | 87/97 (0.8969) | 99/114 (0.8684) | 99/100 (0.9900) |
| p5-8 | screen-baseline-qkm | 97 | 114 | 79/97 (0.8144) | 79/97 (0.8144) | 91/114 (0.7982) | 91/91 (1.0000) |
| p5-8 | screen-q25-7b | 97 | 114 | 83/97 (0.8557) | 83/97 (0.8557) | 99/114 (0.8684) | 101/101 (1.0000) |
| p5-8 | screen-q3-8b | 97 | 114 | 76/97 (0.7835) | 76/97 (0.7835) | 77/114 (0.6754) | 79/80 (0.9875) |
| p5-8 | screen-q35-2b | 97 | 114 | 72/97 (0.7423) | 72/97 (0.7423) | 64/114 (0.5614) | 64/67 (0.9552) |
| p5-8 | screen-q35-4b | 97 | 114 | 77/97 (0.7938) | 77/97 (0.7938) | 84/114 (0.7368) | 84/84 (1.0000) |
| p5-10 | screen-baseline-a | 99 | 123 | 68/99 (0.6869) | 68/99 (0.6869) | 79/123 (0.6423) | 82/82 (1.0000) |
| p5-10 | screen-baseline-b | 99 | 123 | 71/99 (0.7172) | 71/99 (0.7172) | 85/123 (0.6911) | 87/87 (1.0000) |
| p5-10 | screen-baseline-qkm | 99 | 123 | 81/99 (0.8182) | 80/99 (0.8081) | 80/123 (0.6504) | 80/80 (1.0000) |
| p5-10 | screen-q25-7b | 99 | 123 | 79/99 (0.7980) | 76/99 (0.7677) | 82/123 (0.6667) | 83/83 (1.0000) |
| p5-10 | screen-q3-8b | 99 | 123 | 79/99 (0.7980) | 79/99 (0.7980) | 86/123 (0.6992) | 89/89 (1.0000) |
| p5-10 | screen-q35-2b | 99 | 123 | 56/99 (0.5657) | 56/99 (0.5657) | 27/123 (0.2195) | 27/27 (1.0000) |
| p5-10 | screen-q35-4b | 99 | 123 | 69/99 (0.6970) | 68/99 (0.6869) | 69/123 (0.5610) | 69/69 (1.0000) |
| p5-12 | screen-baseline-a | 109 | 133 | 91/109 (0.8349) | 91/109 (0.8349) | 82/133 (0.6165) | 89/89 (1.0000) |
| p5-12 | screen-baseline-b | 109 | 133 | 92/109 (0.8440) | 92/109 (0.8440) | 84/133 (0.6316) | 90/90 (1.0000) |
| p5-12 | screen-baseline-qkm | 109 | 133 | 91/109 (0.8349) | 91/109 (0.8349) | 84/133 (0.6316) | 99/100 (0.9900) |
| p5-12 | screen-q25-7b | 109 | 133 | 96/109 (0.8807) | 96/109 (0.8807) | 94/133 (0.7068) | 99/100 (0.9900) |
| p5-12 | screen-q3-8b | 109 | 133 | 102/109 (0.9358) | 102/109 (0.9358) | 91/133 (0.6842) | 104/104 (1.0000) |
| p5-12 | screen-q35-2b | 109 | 133 | 53/109 (0.4862) | 44/109 (0.4037) | 26/133 (0.1955) | 26/27 (0.9630) |
| p5-12 | screen-q35-4b | 109 | 133 | 89/109 (0.8165) | 89/109 (0.8165) | 81/133 (0.6090) | 83/85 (0.9765) |
| p5-14 | screen-baseline-a | 88 | 106 | 81/88 (0.9205) | 81/88 (0.9205) | 92/106 (0.8679) | 94/97 (0.9691) |
| p5-14 | screen-baseline-b | 88 | 106 | 81/88 (0.9205) | 81/88 (0.9205) | 95/106 (0.8962) | 96/98 (0.9796) |
| p5-14 | screen-baseline-qkm | 88 | 106 | 80/88 (0.9091) | 80/88 (0.9091) | 94/106 (0.8868) | 96/99 (0.9697) |
| p5-14 | screen-q25-7b | 88 | 106 | 78/88 (0.8864) | 78/88 (0.8864) | 90/106 (0.8491) | 93/98 (0.9490) |
| p5-14 | screen-q3-8b | 88 | 106 | 85/88 (0.9659) | 85/88 (0.9659) | 97/106 (0.9151) | 99/101 (0.9802) |
| p5-14 | screen-q35-2b | 88 | 106 | 70/88 (0.7955) | 70/88 (0.7955) | 63/106 (0.5943) | 66/68 (0.9706) |
| p5-14 | screen-q35-4b | 88 | 106 | 81/88 (0.9205) | 81/88 (0.9205) | 93/106 (0.8774) | 94/96 (0.9792) |
| p5-16 | screen-baseline-a | 141 | 166 | 127/141 (0.9007) | 127/141 (0.9007) | 131/166 (0.7892) | 131/132 (0.9924) |
| p5-16 | screen-baseline-b | 141 | 166 | 130/141 (0.9220) | 130/141 (0.9220) | 133/166 (0.8012) | 133/134 (0.9925) |
| p5-16 | screen-baseline-qkm | 141 | 166 | 121/141 (0.8582) | 121/141 (0.8582) | 111/166 (0.6687) | 111/113 (0.9823) |
| p5-16 | screen-q25-7b | 141 | 166 | 102/141 (0.7234) | 99/141 (0.7021) | 97/166 (0.5843) | 99/99 (1.0000) |
| p5-16 | screen-q3-8b | 141 | 166 | 124/141 (0.8794) | 124/141 (0.8794) | 115/166 (0.6928) | 115/117 (0.9829) |
| p5-16 | screen-q35-2b | 141 | 166 | 55/141 (0.3901) | 55/141 (0.3901) | 62/166 (0.3735) | 62/63 (0.9841) |
| p5-16 | screen-q35-4b | 141 | 166 | 111/141 (0.7872) | 111/141 (0.7872) | 111/166 (0.6687) | 112/113 (0.9912) |
| pooled | screen-baseline-a | 1024 | 964 | 907/1024 (0.8857) | 906/1024 (0.8848) | 765/964 (0.7936) | 780/791 (0.9861) |
| pooled | screen-baseline-b | 1024 | 964 | 911/1024 (0.8896) | 911/1024 (0.8896) | 782/964 (0.8112) | 792/802 (0.9875) |
| pooled | screen-baseline-qkm | 1024 | 964 | 905/1024 (0.8838) | 904/1024 (0.8828) | 751/964 (0.7790) | 775/788 (0.9835) |
| pooled | screen-q25-7b | 1024 | 964 | 799/1024 (0.7803) | 770/1024 (0.7520) | 753/964 (0.7811) | 768/781 (0.9834) |
| pooled | screen-q3-8b | 1024 | 964 | 915/1024 (0.8936) | 858/1024 (0.8379) | 760/964 (0.7884) | 780/797 (0.9787) |
| pooled | screen-q35-2b | 1024 | 964 | 656/1024 (0.6406) | 621/1024 (0.6064) | 430/964 (0.4461) | 433/446 (0.9709) |
| pooled | screen-q35-4b | 1024 | 964 | 830/1024 (0.8105) | 829/1024 (0.8096) | 706/964 (0.7324) | 712/720 (0.9889) |

Original-label safety and [5b]:

| Set | Run | Accepted unmatched | Wrong price accepted | Claimed-block anchor n/d | Page-verbatim copy n/d | Real FR n/d | Real catch n/d | [5b] accepts | [5b] exact n/d | [5b] unmatched |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 10 | 4 | 322/350 (0.9200) | 345/350 (0.9857) | 3/272 (0.0110) | 20/34 (0.5882) | 0 | 0/0 (n/a) | 0 |
| spike | screen-baseline-b | 13 | 4 | 325/353 (0.9207) | 350/353 (0.9915) | 2/273 (0.0073) | 21/38 (0.5526) | 0 | 0/0 (n/a) | 0 |
| spike | screen-baseline-qkm | 10 | 7 | 301/356 (0.8455) | 349/356 (0.9803) | 11/291 (0.0378) | 14/31 (0.4516) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q25-7b | 11 | 5 | 247/452 (0.5465) | 433/452 (0.9580) | 3/281 (0.0107) | 42/58 (0.7241) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q3-8b | 26 | 12 | 344/394 (0.8731) | 394/394 (1.0000) | 12/293 (0.0410) | 54/92 (0.5870) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q35-2b | 45 | 6 | 278/375 (0.7413) | 363/375 (0.9680) | 11/193 (0.0570) | 137/188 (0.7287) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q35-4b | 19 | 3 | 318/349 (0.9112) | 325/349 (0.9312) | 0/259 (0.0000) | 10/32 (0.3125) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-a | 8 | 2 | 227/247 (0.9190) | 246/247 (0.9960) | 7/25 (0.2800) | 18/28 (0.6429) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-b | 8 | 2 | 221/235 (0.9404) | 233/235 (0.9915) | 7/23 (0.3043) | 17/27 (0.6296) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-qkm | 5 | 0 | 226/240 (0.9417) | 238/240 (0.9917) | 7/25 (0.2800) | 18/23 (0.7826) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q25-7b | 3 | 2 | 39/137 (0.2847) | 101/137 (0.7372) | 0/15 (0.0000) | 63/68 (0.9265) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q3-8b | 24 | 0 | 160/208 (0.7692) | 208/208 (1.0000) | 7/20 (0.3500) | 112/136 (0.8235) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q35-2b | 16 | 0 | 264/266 (0.9925) | 264/266 (0.9925) | 13/19 (0.6842) | 171/187 (0.9144) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q35-4b | 7 | 0 | 161/163 (0.9877) | 163/163 (1.0000) | 0/11 (0.0000) | 55/62 (0.8871) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-a | 12 | 1 | 137/190 (0.7211) | 187/190 (0.9842) | 20/117 (0.1709) | 59/72 (0.8194) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-b | 12 | 1 | 136/167 (0.8144) | 162/167 (0.9701) | 2/101 (0.0198) | 57/70 (0.8143) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-qkm | 12 | 0 | 143/169 (0.8462) | 169/169 (1.0000) | 3/94 (0.0319) | 65/77 (0.8442) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q25-7b | 10 | 0 | 110/194 (0.5670) | 178/194 (0.9175) | 24/125 (0.1920) | 55/65 (0.8462) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q3-8b | 14 | 1 | 93/190 (0.4895) | 185/190 (0.9737) | 14/93 (0.1505) | 84/99 (0.8485) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q35-2b | 26 | 3 | 233/279 (0.8351) | 275/279 (0.9857) | 38/102 (0.3725) | 129/158 (0.8165) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q35-4b | 20 | 0 | 97/156 (0.6218) | 151/156 (0.9679) | 18/102 (0.1765) | 29/49 (0.5918) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-a | 2 | 0 | 97/128 (0.7578) | 122/128 (0.9531) | 3/85 (0.0353) | 24/26 (0.9231) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-b | 7 | 0 | 119/148 (0.8041) | 140/148 (0.9459) | 10/97 (0.1031) | 26/33 (0.7879) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-qkm | 5 | 0 | 104/138 (0.7536) | 133/138 (0.9638) | 8/88 (0.0909) | 42/47 (0.8936) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q25-7b | 2 | 0 | 144/228 (0.6316) | 190/228 (0.8333) | 26/109 (0.2385) | 66/68 (0.9706) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q3-8b | 10 | 0 | 169/188 (0.8989) | 188/188 (1.0000) | 16/105 (0.1524) | 62/72 (0.8611) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q35-2b | 18 | 0 | 236/282 (0.8369) | 257/282 (0.9113) | 17/44 (0.3864) | 53/71 (0.7465) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q35-4b | 9 | 0 | 98/118 (0.8305) | 115/118 (0.9746) | 11/80 (0.1375) | 27/36 (0.7500) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-a | 7 | 0 | 122/148 (0.8243) | 147/148 (0.9932) | 34/123 (0.2764) | 10/17 (0.5882) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-b | 11 | 0 | 131/157 (0.8344) | 157/157 (1.0000) | 33/123 (0.2683) | 11/22 (0.5000) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-qkm | 14 | 1 | 147/163 (0.9018) | 163/163 (1.0000) | 36/135 (0.2667) | 2/17 (0.1176) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q25-7b | 10 | 1 | 104/183 (0.5683) | 183/183 (1.0000) | 41/140 (0.2929) | 28/39 (0.7179) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q3-8b | 28 | 0 | 164/215 (0.7628) | 215/215 (1.0000) | 55/159 (0.3459) | 26/54 (0.4815) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q35-2b | 14 | 1 | 139/267 (0.5206) | 267/267 (1.0000) | 54/80 (0.6750) | 128/143 (0.8951) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q35-4b | 12 | 2 | 145/165 (0.8788) | 165/165 (1.0000) | 46/129 (0.3566) | 11/25 (0.4400) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-a | 0 | 3 | 70/112 (0.6250) | 112/112 (1.0000) | 10/104 (0.0962) | 4/7 (0.5714) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-b | 1 | 2 | 72/106 (0.6792) | 104/106 (0.9811) | 4/100 (0.0400) | 2/5 (0.4000) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-qkm | 4 | 3 | 75/106 (0.7075) | 106/106 (1.0000) | 5/101 (0.0495) | 0/7 (0.0000) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q25-7b | 5 | 5 | 77/120 (0.6417) | 111/120 (0.9250) | 9/102 (0.0882) | 9/19 (0.4737) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q3-8b | 2 | 2 | 94/113 (0.8319) | 113/113 (1.0000) | 7/106 (0.0660) | 5/9 (0.5556) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q35-2b | 15 | 2 | 125/235 (0.5319) | 235/235 (1.0000) | 60/126 (0.4762) | 34/51 (0.6667) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q35-4b | 8 | 2 | 84/112 (0.7500) | 112/112 (1.0000) | 11/105 (0.1048) | 0/10 (0.0000) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-a | 16 | 1 | 116/205 (0.5659) | 205/205 (1.0000) | 45/176 (0.2557) | 17/34 (0.5000) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-b | 15 | 1 | 116/208 (0.5577) | 208/208 (1.0000) | 45/178 (0.2528) | 18/34 (0.5294) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-qkm | 22 | 2 | 166/202 (0.8218) | 196/202 (0.9703) | 27/138 (0.1957) | 23/47 (0.4894) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q25-7b | 9 | 0 | 76/215 (0.3535) | 206/215 (0.9581) | 80/179 (0.4469) | 28/37 (0.7568) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q3-8b | 25 | 2 | 148/224 (0.6607) | 224/224 (1.0000) | 37/152 (0.2434) | 57/84 (0.6786) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q35-2b | 24 | 1 | 126/246 (0.5122) | 240/246 (0.9756) | 62/124 (0.5000) | 95/120 (0.7917) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q35-4b | 19 | 1 | 126/228 (0.5526) | 184/228 (0.8070) | 23/135 (0.1704) | 27/47 (0.5745) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-a | 55 | 11 | 1091/1380 (0.7906) | 1364/1380 (0.9884) | 122/902 (0.1353) | 152/218 (0.6972) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-b | 67 | 10 | 1120/1374 (0.8151) | 1354/1374 (0.9854) | 103/895 (0.1151) | 152/229 (0.6638) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-qkm | 72 | 13 | 1162/1374 (0.8457) | 1354/1374 (0.9854) | 97/872 (0.1112) | 164/249 (0.6586) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q25-7b | 50 | 13 | 797/1529 (0.5213) | 1402/1529 (0.9169) | 183/951 (0.1924) | 291/354 (0.8220) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q3-8b | 129 | 17 | 1172/1532 (0.7650) | 1527/1532 (0.9967) | 148/928 (0.1595) | 400/546 (0.7326) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q35-2b | 158 | 13 | 1401/1950 (0.7185) | 1901/1950 (0.9749) | 255/688 (0.3706) | 747/918 (0.8137) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q35-4b | 94 | 8 | 1029/1291 (0.7971) | 1215/1291 (0.9411) | 109/821 (0.1328) | 159/261 (0.6092) | 0 | 0/0 (n/a) | 0 |

Original-label baseline gaps:

| Set | Metric | Baseline A | Baseline B | Absolute A/B gap |
| --- | --- | --- | --- | --- |
| spike | usable_prices | 0.8963 | 0.9030 | 0.0067 |
| spike | item_recall_kept | 0.9075 | 0.9075 | 0.0000 |
| spike | item_recall | 0.9104 | 0.9075 | 0.0030 |
| spike | price_accuracy | 0.9853 | 0.9855 | 0.0001 |
| spike | copy_claimed | 0.9200 | 0.9207 | 0.0007 |
| spike | copy_anywhere | 0.9857 | 0.9915 | 0.0058 |
| spike | validator_false_reject | 0.0110 | 0.0073 | 0.0037 |
| spike | validator_catch | 0.5882 | 0.5526 | 0.0356 |
| p5-5 | usable_prices | 0.7391 | 0.6957 | 0.0435 |
| p5-5 | item_recall_kept | 0.9677 | 0.9419 | 0.0258 |
| p5-5 | item_recall | 0.9677 | 0.9419 | 0.0258 |
| p5-5 | price_accuracy | 0.9000 | 0.8889 | 0.0111 |
| p5-5 | copy_claimed | 0.9190 | 0.9404 | 0.0214 |
| p5-5 | copy_anywhere | 0.9960 | 0.9915 | 0.0045 |
| p5-5 | validator_false_reject | 0.2800 | 0.3043 | 0.0243 |
| p5-5 | validator_catch | 0.6429 | 0.6296 | 0.0132 |
| p5-8 | usable_prices | 0.8421 | 0.8684 | 0.0263 |
| p5-8 | item_recall_kept | 0.8763 | 0.8969 | 0.0206 |
| p5-8 | item_recall | 0.8763 | 0.8969 | 0.0206 |
| p5-8 | price_accuracy | 0.9898 | 0.9900 | 0.0002 |
| p5-8 | copy_claimed | 0.7211 | 0.8144 | 0.0933 |
| p5-8 | copy_anywhere | 0.9842 | 0.9701 | 0.0142 |
| p5-8 | validator_false_reject | 0.1709 | 0.0198 | 0.1511 |
| p5-8 | validator_catch | 0.8194 | 0.8143 | 0.0052 |
| p5-10 | usable_prices | 0.6423 | 0.6911 | 0.0488 |
| p5-10 | item_recall_kept | 0.6869 | 0.7172 | 0.0303 |
| p5-10 | item_recall | 0.6869 | 0.7172 | 0.0303 |
| p5-10 | price_accuracy | 1.0000 | 1.0000 | 0.0000 |
| p5-10 | copy_claimed | 0.7578 | 0.8041 | 0.0462 |
| p5-10 | copy_anywhere | 0.9531 | 0.9459 | 0.0072 |
| p5-10 | validator_false_reject | 0.0353 | 0.1031 | 0.0678 |
| p5-10 | validator_catch | 0.9231 | 0.7879 | 0.1352 |
| p5-12 | usable_prices | 0.6165 | 0.6316 | 0.0150 |
| p5-12 | item_recall_kept | 0.8349 | 0.8440 | 0.0092 |
| p5-12 | item_recall | 0.8349 | 0.8440 | 0.0092 |
| p5-12 | price_accuracy | 1.0000 | 1.0000 | 0.0000 |
| p5-12 | copy_claimed | 0.8243 | 0.8344 | 0.0101 |
| p5-12 | copy_anywhere | 0.9932 | 1.0000 | 0.0068 |
| p5-12 | validator_false_reject | 0.2764 | 0.2683 | 0.0081 |
| p5-12 | validator_catch | 0.5882 | 0.5000 | 0.0882 |
| p5-14 | usable_prices | 0.8679 | 0.8962 | 0.0283 |
| p5-14 | item_recall_kept | 0.9205 | 0.9205 | 0.0000 |
| p5-14 | item_recall | 0.9205 | 0.9205 | 0.0000 |
| p5-14 | price_accuracy | 0.9691 | 0.9796 | 0.0105 |
| p5-14 | copy_claimed | 0.6250 | 0.6792 | 0.0542 |
| p5-14 | copy_anywhere | 1.0000 | 0.9811 | 0.0189 |
| p5-14 | validator_false_reject | 0.0962 | 0.0400 | 0.0562 |
| p5-14 | validator_catch | 0.5714 | 0.4000 | 0.1714 |
| p5-16 | usable_prices | 0.7892 | 0.8012 | 0.0120 |
| p5-16 | item_recall_kept | 0.9007 | 0.9220 | 0.0213 |
| p5-16 | item_recall | 0.9007 | 0.9220 | 0.0213 |
| p5-16 | price_accuracy | 0.9924 | 0.9925 | 0.0001 |
| p5-16 | copy_claimed | 0.5659 | 0.5577 | 0.0082 |
| p5-16 | copy_anywhere | 1.0000 | 1.0000 | 0.0000 |
| p5-16 | validator_false_reject | 0.2557 | 0.2528 | 0.0029 |
| p5-16 | validator_catch | 0.5000 | 0.5294 | 0.0294 |
| pooled | usable_prices | 0.7936 | 0.8112 | 0.0176 |
| pooled | item_recall_kept | 0.8848 | 0.8896 | 0.0049 |
| pooled | item_recall | 0.8857 | 0.8896 | 0.0039 |
| pooled | price_accuracy | 0.9861 | 0.9875 | 0.0014 |
| pooled | copy_claimed | 0.7906 | 0.8151 | 0.0246 |
| pooled | copy_anywhere | 0.9884 | 0.9854 | 0.0030 |
| pooled | validator_false_reject | 0.1353 | 0.1151 | 0.0202 |
| pooled | validator_catch | 0.6972 | 0.6638 | 0.0335 |

screen-baseline-a: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-a/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-a/reports).

screen-baseline-b: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-b/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-b/reports).

screen-baseline-qkm: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/reports); [original-label paired differences](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-baseline-qkm/comparisons-original.json).

screen-q25-7b: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/reports); [original-label paired differences](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q25-7b/comparisons-original.json).

screen-q3-8b: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/reports); [original-label paired differences](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q3-8b/comparisons-original.json).

screen-q35-2b: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/reports); [original-label paired differences](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-2b/comparisons-original.json).

screen-q35-4b: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/reports); [original-label paired differences](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/runs/screen-q35-4b/comparisons-original.json).

## screen30: provisional 30-page quality screen

This phase contains **30 selected tuning pages and 202 input chunks**, with every one of the seven sets represented. It is neither the original full218-page protocol nor held-out or production acceptance. The owner amended the workload before candidate scores; archived partial full-cohort outputs are excluded. The frozen numerical quality checks are applied to this reduced phase only. A subset gate pass is provisional evidence for NPU validation, not proof that the full-cohort criterion clears.

Selection seed `20261015`; candidate scores used: `False`. Each set: near3 and7 inputchunks;15th scarceformat.30 adds near5 and11 chunks/set plus scarceformat. Seed breaks ties;nested;no candidate outputs inspected. The30-page expansion is nested. Candidates expanded after a positive/inconclusive15-page signal are adaptively selected; screen30 is not an independent confirmation. The15-page obvious-loser rule is price accuracy<0.97 OR both usable and kept recall trailing both baselines by>0.03; all other positive/inconclusive contenders may proceed to30. No threshold or page subset is tuned per model.

| Set | Pages | Input chunks | Formats | Page IDs |
| --- | --- | --- | --- | --- |
| spike | 5 | 38 | html_inline, html_list | 0824dfcdd900, 53172819459a, 630ef18b78a3, 6a788f7d3b50, abefb3029e57 |
| p5-5 | 4 | 27 | html_list | 3145210120fa, 66a3d8e752b9, aded7f07485b, f649c257352d |
| p5-8 | 5 | 33 | html_cards, html_inline, html_list, price_list | a8684c49dfa1, b208f79d3315, b641af8c7059, ddb652ccea54, f2f4666c11f4 |
| p5-10 | 4 | 26 | html_list | 3a630628e2bf, 3e035f21ac55, 8d6e20477ec6, d9126c519b73 |
| p5-12 | 4 | 26 | html_cards, html_list | 1bc9710cd463, 29612ad9e3eb, e442534a6bed, e66ce335637a |
| p5-14 | 4 | 26 | html_list | 35fde4822b24, 70ab184b5a86, e845388448b9, f204b5c8375f |
| p5-16 | 4 | 26 | html_list | 590c72ebfeb3, 5d960df16b84, 6d5cdfffe336, bb7f2aea0431 |

Selection manifest: [selection.json](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/selection.json); [splits.json](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/splits.json).

### Phase runtime and artifact identity

| Run | Model configuration | GGUF file | Smoke pages/h | Latest invocation wall h | Slot context | Slots | GPU layers | CUDA MiB model/KV/compute | Isolated-worker observed peak MiB | Whole-GPU peak MiB | Provenance | Runtime |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| screen-baseline-a | Qwen3-4B-Instruct-2507 Q4_0 A | Qwen3-4B-Instruct-2507-Q4_0.gguf | 315.55 | 0.109 | 6144 | 2 | 37/37 | 2260.0/1728.0/426.0 | 4660 | 4996 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/full.json) |
| screen-baseline-b | Qwen3-4B-Instruct-2507 Q4_0 B | Qwen3-4B-Instruct-2507-Q4_0.gguf | 301.98 | 0.113 | 6144 | 2 | 37/37 | 2260.0/1728.0/426.0 | 4660 | 5124 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/full.json) |
| screen-baseline-qkm | Qwen3-4B-Instruct-2507 Q4_K_M | Qwen3-4B-Instruct-2507-Q4_K_M.gguf | 276.15 | 0.118 | 6144 | 2 | 37/37 | 2375.9/1728.0/426.0 | 4774 | 5220 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/full.json) |
| screen-q25-7b | Qwen2.5-7B-Instruct Q4_K_M | qwen2.5-7b-instruct-q4_k_m-00001-of-00002.gguf | 173.18 | 0.156 | 6144 | 2 | 29/29 | 4168.1/672.0/378.0 | 5448 | 5627 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/full.json) |
| screen-q3-8b | Qwen3-8B Q4_K_M | Qwen3-8B-Q4_K_M.gguf | 68.54 | 0.186 | 6144 | 2 | 37/37 | 4455.3/1728.0/432.0 | 6860 | 7039 | [identity](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/provenance.json) | [latest run record](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/full.json) |

Every model uses the same frozen context, output budget, prompt and downstream pipeline. The amended screen runs GPU models sequentially and exclusively. GPU throughput is scheduling metadata, never an acceptance bar. A runtime record may describe the latest15→30 extension and reuse completed pages; it is not necessarily an independent phase timing. Whole-GPU peaks include desktop/runtime overhead; isolated-worker peaks require unambiguous single-worker process samples. CUDA buffer sums exclude additional runtime allocations. Missing measurements stay n/a, and missing offload proof stays unproven. Full-offload proof and process measurements are preserved in [server/process logs](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/logs). Archived partial218-page jobs were stopped before candidate scoring and are not used by these phase scores.

- **screen-baseline-a**: checkpoint `Qwen/Qwen3-4B-Instruct-2507@cdbee75f17c01a7cc42f958dc650907174af0554` observed; GGUF `unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9`; SHA256 `e0ba675d86ab277c61701c6793659b2ae801d95e3be791464c321e6fbf613be2`; 2375773280 bytes; `Qwen3-4B-Instruct-2507;Q4_0;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `c979e0e71a3e21b8f208e6ab120d5cb29327885f29d2a8b18fda67a723798e18`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-a/server-command.json).
- **screen-baseline-b**: checkpoint `Qwen/Qwen3-4B-Instruct-2507@cdbee75f17c01a7cc42f958dc650907174af0554` observed; GGUF `unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9`; SHA256 `e0ba675d86ab277c61701c6793659b2ae801d95e3be791464c321e6fbf613be2`; 2375773280 bytes; `Qwen3-4B-Instruct-2507;Q4_0;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `c979e0e71a3e21b8f208e6ab120d5cb29327885f29d2a8b18fda67a723798e18`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-b/server-command.json).
- **screen-baseline-qkm**: checkpoint `Qwen/Qwen3-4B-Instruct-2507@cdbee75f17c01a7cc42f958dc650907174af0554` observed; GGUF `unsloth/Qwen3-4B-Instruct-2507-GGUF@a06e946bb6b655725eafa393f4a9745d460374c9`; SHA256 `3605803b982cb64aead44f6c1b2ae36e3acdb41d8e46c8a94c6533bc4c67e597`; 2497281120 bytes; `Qwen3-4B-Instruct-2507;Q4_K_M;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `c979e0e71a3e21b8f208e6ab120d5cb29327885f29d2a8b18fda67a723798e18`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-baseline-qkm/server-command.json).
- **screen-q25-7b**: checkpoint `Qwen/Qwen2.5-7B-Instruct@a09a35458c702b33eeacc393d103063234e8bc28` observed; GGUF `Qwen/Qwen2.5-7B-Instruct-GGUF@bb5d59e06d9551d752d08b292a50eb208b07ab1f`; SHA256 `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db`; additional shard `qwen2.5-7b-instruct-q4_k_m-00002-of-00002.gguf` SHA256 `539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a`; 4683073632 bytes; `Qwen2.5-7B-Instruct;Q4_K_M;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `4e9918361c284a93880606d182d64da6a9fe97cdc1f5c5a78c1c8840444246fc`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q25-7b/server-command.json).
- **screen-q3-8b**: checkpoint `Qwen/Qwen3-8B@b968826d9c46dd6066d109eabc6255188de91218` observed; GGUF `unsloth/Qwen3-8B-GGUF@a6adef130ffb23ddaf1a62fec9dced968c9bc482`; SHA256 `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4`; 5027784512 bytes; `Qwen3-8B;Q4_K_M;prompt-v2.4;chunk-v2.3;segment-v2;repairs-v8;validator-v8;resolve-v1;classifier-v2`; `llama.cpp b11176 f805c57a2`; image `ghcr.io/ggml-org/llama.cpp@sha256:1f4b9cf58982dd4d7cc497aea31b1a456ca9a3a1f94f527d317d3fdee0d60ab6`. Latest rendered-template SHA256 `5da44855ab7e0641774d5ed0ff0b4f89671d01df7d316e54d06557a962211cb4`; temperature `0`, thinking `False`; context `12288` total/`6144` per slot. Checkpoint revision is current official revision; GGUF publisher does not assert source checkpoint commit. GGUF revision and bytes are pinned. [rendered non-thinking prompt](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/rendered-actual-prompt.txt); [all frozen-input token budgets](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/token-budget.json); [server flags](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/runs/screen-q3-8b/server-command.json).

### Primary v9 labels: metrics and exact denominators

Usable-price numerator counts distinct(item,amount), while its denominator counts every labelled price row. Repeated equal-amount variants create a model-invariant denominator gap and are isolated below with zero gain ceiling. Accepted-price accuracy conditions on matched rows; unsafe unmatched rows are reported separately.

| Set | Run | Gold items | Gold price rows | Raw recall n/d | Kept recall n/d | Usable n/d | Price accuracy n/d |
| --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 491 | 477 | 451/491 (0.9185) | 449/491 (0.9145) | 434/477 (0.9099) | 436/440 (0.9909) |
| spike | screen-baseline-b | 491 | 477 | 457/491 (0.9308) | 456/491 (0.9287) | 443/477 (0.9287) | 445/449 (0.9911) |
| spike | screen-baseline-qkm | 491 | 477 | 458/491 (0.9328) | 458/491 (0.9328) | 443/477 (0.9287) | 451/458 (0.9847) |
| spike | screen-q25-7b | 491 | 477 | 430/491 (0.8758) | 419/491 (0.8534) | 429/477 (0.8994) | 439/444 (0.9887) |
| spike | screen-q3-8b | 491 | 477 | 473/491 (0.9633) | 445/491 (0.9063) | 458/477 (0.9602) | 459/471 (0.9745) |
| p5-5 | screen-baseline-a | 307 | 209 | 285/307 (0.9283) | 285/307 (0.9283) | 180/209 (0.8612) | 181/183 (0.9891) |
| p5-5 | screen-baseline-b | 307 | 209 | 277/307 (0.9023) | 277/307 (0.9023) | 167/209 (0.7990) | 168/170 (0.9882) |
| p5-5 | screen-baseline-qkm | 307 | 209 | 277/307 (0.9023) | 277/307 (0.9023) | 171/209 (0.8182) | 172/172 (1.0000) |
| p5-5 | screen-q25-7b | 307 | 209 | 209/307 (0.6808) | 196/307 (0.6384) | 169/209 (0.8086) | 179/182 (0.9835) |
| p5-5 | screen-q3-8b | 307 | 209 | 267/307 (0.8697) | 237/307 (0.7720) | 170/209 (0.8134) | 178/178 (1.0000) |
| p5-8 | screen-baseline-a | 314 | 361 | 255/314 (0.8121) | 255/314 (0.8121) | 209/361 (0.5789) | 212/213 (0.9953) |
| p5-8 | screen-baseline-b | 314 | 361 | 260/314 (0.8280) | 260/314 (0.8280) | 212/361 (0.5873) | 214/215 (0.9953) |
| p5-8 | screen-baseline-qkm | 314 | 361 | 261/314 (0.8312) | 261/314 (0.8312) | 216/361 (0.5983) | 218/219 (0.9954) |
| p5-8 | screen-q25-7b | 314 | 361 | 250/314 (0.7962) | 247/314 (0.7866) | 206/361 (0.5706) | 214/217 (0.9862) |
| p5-8 | screen-q3-8b | 314 | 361 | 273/314 (0.8694) | 270/314 (0.8599) | 241/361 (0.6676) | 246/249 (0.9880) |
| p5-10 | screen-baseline-a | 230 | 267 | 177/230 (0.7696) | 177/230 (0.7696) | 187/267 (0.7004) | 191/191 (1.0000) |
| p5-10 | screen-baseline-b | 230 | 267 | 180/230 (0.7826) | 180/230 (0.7826) | 193/267 (0.7228) | 196/196 (1.0000) |
| p5-10 | screen-baseline-qkm | 230 | 267 | 194/230 (0.8435) | 193/230 (0.8391) | 178/267 (0.6667) | 180/180 (1.0000) |
| p5-10 | screen-q25-7b | 230 | 267 | 190/230 (0.8261) | 187/230 (0.8130) | 179/267 (0.6704) | 183/184 (0.9946) |
| p5-10 | screen-q3-8b | 230 | 267 | 193/230 (0.8391) | 193/230 (0.8391) | 192/267 (0.7191) | 197/197 (1.0000) |
| p5-12 | screen-baseline-a | 241 | 277 | 187/241 (0.7759) | 187/241 (0.7759) | 188/277 (0.6787) | 210/210 (1.0000) |
| p5-12 | screen-baseline-b | 241 | 277 | 188/241 (0.7801) | 188/241 (0.7801) | 190/277 (0.6859) | 210/210 (1.0000) |
| p5-12 | screen-baseline-qkm | 241 | 277 | 200/241 (0.8299) | 200/241 (0.8299) | 202/277 (0.7292) | 223/224 (0.9955) |
| p5-12 | screen-q25-7b | 241 | 277 | 201/241 (0.8340) | 201/241 (0.8340) | 210/277 (0.7581) | 230/232 (0.9914) |
| p5-12 | screen-q3-8b | 241 | 277 | 227/241 (0.9419) | 227/241 (0.9419) | 224/277 (0.8087) | 248/248 (1.0000) |
| p5-14 | screen-baseline-a | 190 | 200 | 176/190 (0.9263) | 176/190 (0.9263) | 178/200 (0.8900) | 181/187 (0.9679) |
| p5-14 | screen-baseline-b | 190 | 200 | 177/190 (0.9316) | 177/190 (0.9316) | 183/200 (0.9150) | 185/190 (0.9737) |
| p5-14 | screen-baseline-qkm | 190 | 200 | 173/190 (0.9105) | 173/190 (0.9105) | 178/200 (0.8900) | 181/184 (0.9837) |
| p5-14 | screen-q25-7b | 190 | 200 | 173/190 (0.9105) | 169/190 (0.8895) | 169/200 (0.8450) | 176/184 (0.9565) |
| p5-14 | screen-q3-8b | 190 | 200 | 175/190 (0.9211) | 171/190 (0.9000) | 178/200 (0.8900) | 184/189 (0.9735) |
| p5-16 | screen-baseline-a | 278 | 302 | 241/278 (0.8669) | 241/278 (0.8669) | 240/302 (0.7947) | 243/245 (0.9918) |
| p5-16 | screen-baseline-b | 278 | 302 | 243/278 (0.8741) | 243/278 (0.8741) | 240/302 (0.7947) | 244/246 (0.9919) |
| p5-16 | screen-baseline-qkm | 278 | 302 | 242/278 (0.8705) | 242/278 (0.8705) | 230/302 (0.7616) | 237/240 (0.9875) |
| p5-16 | screen-q25-7b | 278 | 302 | 212/278 (0.7626) | 209/278 (0.7518) | 190/302 (0.6291) | 192/193 (0.9948) |
| p5-16 | screen-q3-8b | 278 | 302 | 242/278 (0.8705) | 241/278 (0.8669) | 231/302 (0.7649) | 319/321 (0.9938) |
| pooled | screen-baseline-a | 2051 | 2093 | 1772/2051 (0.8640) | 1770/2051 (0.8630) | 1616/2093 (0.7721) | 1654/1669 (0.9910) |
| pooled | screen-baseline-b | 2051 | 2093 | 1782/2051 (0.8688) | 1781/2051 (0.8684) | 1628/2093 (0.7778) | 1662/1676 (0.9916) |
| pooled | screen-baseline-qkm | 2051 | 2093 | 1805/2051 (0.8801) | 1804/2051 (0.8796) | 1618/2093 (0.7731) | 1662/1677 (0.9911) |
| pooled | screen-q25-7b | 2051 | 2093 | 1665/2051 (0.8118) | 1628/2051 (0.7938) | 1552/2093 (0.7415) | 1613/1636 (0.9859) |
| pooled | screen-q3-8b | 2051 | 2093 | 1850/2051 (0.9020) | 1784/2051 (0.8698) | 1694/2093 (0.8094) | 1831/1853 (0.9881) |

### Baseline A/B gap bands on this subset

Only the pooled absolute A/B gap is the criterion band; per-set gaps provide context. Two runs do not bound model variance. With only2–5 pages per set, per-set intervals are especially unstable.

| Set | Metric | Baseline A | Baseline B | Absolute A/B gap |
| --- | --- | --- | --- | --- |
| spike | usable_prices | 0.9099 | 0.9287 | 0.0189 |
| spike | item_recall_kept | 0.9145 | 0.9287 | 0.0143 |
| spike | item_recall | 0.9185 | 0.9308 | 0.0122 |
| spike | price_accuracy | 0.9909 | 0.9911 | 0.0002 |
| spike | copy_claimed | 0.9030 | 0.9028 | 0.0002 |
| spike | copy_anywhere | 0.9867 | 0.9907 | 0.0040 |
| spike | validator_false_reject | 0.0136 | 0.0111 | 0.0025 |
| spike | validator_catch | 0.6410 | 0.5854 | 0.0557 |
| p5-5 | usable_prices | 0.8612 | 0.7990 | 0.0622 |
| p5-5 | item_recall_kept | 0.9283 | 0.9023 | 0.0261 |
| p5-5 | item_recall | 0.9283 | 0.9023 | 0.0261 |
| p5-5 | price_accuracy | 0.9891 | 0.9882 | 0.0008 |
| p5-5 | copy_claimed | 0.8497 | 0.8675 | 0.0179 |
| p5-5 | copy_anywhere | 0.9896 | 0.9890 | 0.0006 |
| p5-5 | validator_false_reject | 0.0573 | 0.0820 | 0.0247 |
| p5-5 | validator_catch | 0.7027 | 0.7027 | 0.0000 |
| p5-8 | usable_prices | 0.5789 | 0.5873 | 0.0083 |
| p5-8 | item_recall_kept | 0.8121 | 0.8280 | 0.0159 |
| p5-8 | item_recall | 0.8121 | 0.8280 | 0.0159 |
| p5-8 | price_accuracy | 0.9953 | 0.9953 | 0.0000 |
| p5-8 | copy_claimed | 0.8156 | 0.8594 | 0.0439 |
| p5-8 | copy_anywhere | 0.9867 | 0.9793 | 0.0074 |
| p5-8 | validator_false_reject | 0.2482 | 0.2045 | 0.0438 |
| p5-8 | validator_catch | 0.8190 | 0.7863 | 0.0326 |
| p5-10 | usable_prices | 0.7004 | 0.7228 | 0.0225 |
| p5-10 | item_recall_kept | 0.7696 | 0.7826 | 0.0130 |
| p5-10 | item_recall | 0.7696 | 0.7826 | 0.0130 |
| p5-10 | price_accuracy | 1.0000 | 1.0000 | 0.0000 |
| p5-10 | copy_claimed | 0.8130 | 0.7852 | 0.0278 |
| p5-10 | copy_anywhere | 0.9771 | 0.9718 | 0.0053 |
| p5-10 | validator_false_reject | 0.0402 | 0.0711 | 0.0309 |
| p5-10 | validator_catch | 0.8919 | 0.8000 | 0.0919 |
| p5-12 | usable_prices | 0.6787 | 0.6859 | 0.0072 |
| p5-12 | item_recall_kept | 0.7759 | 0.7801 | 0.0041 |
| p5-12 | item_recall | 0.7759 | 0.7801 | 0.0041 |
| p5-12 | price_accuracy | 1.0000 | 1.0000 | 0.0000 |
| p5-12 | copy_claimed | 0.8194 | 0.8241 | 0.0047 |
| p5-12 | copy_anywhere | 0.9933 | 0.9967 | 0.0034 |
| p5-12 | validator_false_reject | 0.1633 | 0.1600 | 0.0033 |
| p5-12 | validator_catch | 0.6216 | 0.5263 | 0.0953 |
| p5-14 | usable_prices | 0.8900 | 0.9150 | 0.0250 |
| p5-14 | item_recall_kept | 0.9263 | 0.9316 | 0.0053 |
| p5-14 | item_recall | 0.9263 | 0.9316 | 0.0053 |
| p5-14 | price_accuracy | 0.9679 | 0.9737 | 0.0058 |
| p5-14 | copy_claimed | 0.7078 | 0.7542 | 0.0464 |
| p5-14 | copy_anywhere | 0.9877 | 0.9873 | 0.0004 |
| p5-14 | validator_false_reject | 0.1084 | 0.0842 | 0.0242 |
| p5-14 | validator_catch | 0.5000 | 0.2667 | 0.2333 |
| p5-16 | usable_prices | 0.7947 | 0.7947 | 0.0000 |
| p5-16 | item_recall_kept | 0.8669 | 0.8741 | 0.0072 |
| p5-16 | item_recall | 0.8669 | 0.8741 | 0.0072 |
| p5-16 | price_accuracy | 0.9918 | 0.9919 | 0.0000 |
| p5-16 | copy_claimed | 0.6362 | 0.5863 | 0.0498 |
| p5-16 | copy_anywhere | 1.0000 | 0.9920 | 0.0080 |
| p5-16 | validator_false_reject | 0.2136 | 0.2179 | 0.0044 |
| p5-16 | validator_catch | 0.4315 | 0.3699 | 0.0616 |
| pooled | usable_prices | 0.7721 | 0.7778 | 0.0057 |
| pooled | item_recall_kept | 0.8630 | 0.8684 | 0.0054 |
| pooled | item_recall | 0.8640 | 0.8688 | 0.0049 |
| pooled | price_accuracy | 0.9910 | 0.9916 | 0.0006 |
| pooled | copy_claimed | 0.7968 | 0.7991 | 0.0023 |
| pooled | copy_anywhere | 0.9895 | 0.9873 | 0.0022 |
| pooled | validator_false_reject | 0.1193 | 0.1145 | 0.0047 |
| pooled | validator_catch | 0.6430 | 0.5924 | 0.0506 |

### Baseline attribution on the identical selected pages

Exclusive gold-price losses and ceilings are separate from overlapping row diagnostics. Perfect-row-pass ceilings assume the ideal labelled representation; no bucket predicts an achievable model gain. P18 layout classes are unchanged. Unmatched rows are not proven hallucinations; description/noise, association and grounding diagnostics are heuristic. Strict raw copy failures have no separately additive recoverable-gold ceiling.

| Set | Exclusive gold-price loss | N | Δusable absolute ceiling | Perfect-row-pass N | Δusable perfect-row ceiling |
| --- | --- | --- | --- | --- | --- |
| spike | MODEL_READING:item_missed | 38 | 0.07966 | 38 | 0.07966 |
| spike | MODEL_READING:row_unpriced | 2 | 0.00419 | 2 | 0.00419 |
| spike | MODEL_REPRESENTATION_VALIDATOR:name_not_grounded | 3 | 0.00629 | 3 | 0.00629 |
| p5-5 | LABEL_CONVENTION:duplicate_gold_amount | 1 | 0.00000 | 0 | 0.00000 |
| p5-5 | MODEL_READING:item_missed | 17 | 0.08134 | 14 | 0.06699 |
| p5-5 | MODEL_READING:row_unpriced | 2 | 0.00957 | 0 | 0.00000 |
| p5-5 | MODEL_READING:wrong_amount_printed_nearby_proxy | 2 | 0.00957 | 2 | 0.00957 |
| p5-5 | MODEL_REPRESENTATION_VALIDATOR:p_other | 6 | 0.02871 | 6 | 0.02871 |
| p5-5 | STRUCTURAL_VALIDATOR:same_block | 1 | 0.00478 | 0 | 0.00000 |
| p5-8 | MODEL_READING:item_missed | 82 | 0.22715 | 60 | 0.16620 |
| p5-8 | MODEL_READING:row_unpriced | 5 | 0.01385 | 4 | 0.01108 |
| p5-8 | MODEL_READING:wrong_amount_nowhere_nearby_proxy | 13 | 0.03601 | 13 | 0.03601 |
| p5-8 | MODEL_READING:wrong_amount_printed_nearby_proxy | 9 | 0.02493 | 6 | 0.01662 |
| p5-8 | MODEL_REPRESENTATION_VALIDATOR:p_other | 5 | 0.01385 | 5 | 0.01385 |
| p5-8 | MODEL_REPRESENTATION_VALIDATOR:same_block | 5 | 0.01385 | 5 | 0.01385 |
| p5-8 | MODEL_REPRESENTATION_VALIDATOR:v_other | 1 | 0.00277 | 1 | 0.00277 |
| p5-8 | STRUCTURAL_VALIDATOR:above | 1 | 0.00277 | 0 | 0.00000 |
| p5-8 | STRUCTURAL_VALIDATOR:name_number | 6 | 0.01662 | 0 | 0.00000 |
| p5-8 | STRUCTURAL_VALIDATOR:p_other | 1 | 0.00277 | 0 | 0.00000 |
| p5-8 | STRUCTURAL_VALIDATOR:same_block | 24 | 0.06648 | 0 | 0.00000 |
| p5-10 | LABEL_CONVENTION:duplicate_gold_amount | 2 | 0.00000 | 0 | 0.00000 |
| p5-10 | MODEL_READING:item_missed | 57 | 0.21348 | 34 | 0.12734 |
| p5-10 | MODEL_READING:wrong_amount_printed_nearby_proxy | 15 | 0.05618 | 2 | 0.00749 |
| p5-10 | STRUCTURAL_VALIDATOR:above | 2 | 0.00749 | 0 | 0.00000 |
| p5-10 | STRUCTURAL_VALIDATOR:p_other | 4 | 0.01498 | 0 | 0.00000 |
| p5-12 | LABEL_CONVENTION:duplicate_gold_amount | 4 | 0.00000 | 0 | 0.00000 |
| p5-12 | MODEL_READING:item_missed | 58 | 0.20939 | 45 | 0.16245 |
| p5-12 | MODEL_READING:row_unpriced | 1 | 0.00361 | 1 | 0.00361 |
| p5-12 | MODEL_READING:wrong_amount_printed_nearby_proxy | 14 | 0.05054 | 3 | 0.01083 |
| p5-12 | MODEL_REPRESENTATION_VALIDATOR:p_other | 4 | 0.01444 | 4 | 0.01444 |
| p5-12 | MODEL_REPRESENTATION_VALIDATOR:price_belongs_to_other_variant | 1 | 0.00361 | 1 | 0.00361 |
| p5-12 | MODEL_REPRESENTATION_VALIDATOR:unread | 3 | 0.01083 | 3 | 0.01083 |
| p5-12 | STRUCTURAL_VALIDATOR:p_other | 4 | 0.01444 | 0 | 0.00000 |
| p5-14 | MODEL_READING:item_missed | 17 | 0.08500 | 15 | 0.07500 |
| p5-14 | MODEL_REPRESENTATION_VALIDATOR:p_other | 1 | 0.00500 | 1 | 0.00500 |
| p5-14 | STRUCTURAL_VALIDATOR:p_other | 1 | 0.00500 | 0 | 0.00000 |
| p5-14 | STRUCTURAL_VALIDATOR:same_block | 3 | 0.01500 | 0 | 0.00000 |
| p5-16 | LABEL_CONVENTION:duplicate_gold_amount | 1 | 0.00000 | 0 | 0.00000 |
| p5-16 | MODEL_READING:item_missed | 39 | 0.12914 | 36 | 0.11921 |
| p5-16 | MODEL_READING:wrong_amount_printed_nearby_proxy | 9 | 0.02980 | 4 | 0.01325 |
| p5-16 | MODEL_REPRESENTATION_VALIDATOR:above | 1 | 0.00331 | 1 | 0.00331 |
| p5-16 | MODEL_REPRESENTATION_VALIDATOR:p_other | 1 | 0.00331 | 1 | 0.00331 |
| p5-16 | STRUCTURAL_VALIDATOR:price_belongs_to_other_variant | 6 | 0.01987 | 0 | 0.00000 |
| p5-16 | STRUCTURAL_VALIDATOR:v_other | 5 | 0.01656 | 0 | 0.00000 |
| pooled | LABEL_CONVENTION:duplicate_gold_amount | 8 | 0.00000 | 0 | 0.00000 |
| pooled | MODEL_READING:item_missed | 308 | 0.14716 | 242 | 0.11562 |
| pooled | MODEL_READING:row_unpriced | 10 | 0.00478 | 7 | 0.00334 |
| pooled | MODEL_READING:wrong_amount_nowhere_nearby_proxy | 13 | 0.00621 | 13 | 0.00621 |
| pooled | MODEL_READING:wrong_amount_printed_nearby_proxy | 49 | 0.02341 | 17 | 0.00812 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:above | 1 | 0.00048 | 1 | 0.00048 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:name_not_grounded | 3 | 0.00143 | 3 | 0.00143 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:p_other | 17 | 0.00812 | 17 | 0.00812 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:price_belongs_to_other_variant | 1 | 0.00048 | 1 | 0.00048 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:same_block | 5 | 0.00239 | 5 | 0.00239 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:unread | 3 | 0.00143 | 3 | 0.00143 |
| pooled | MODEL_REPRESENTATION_VALIDATOR:v_other | 1 | 0.00048 | 1 | 0.00048 |
| pooled | STRUCTURAL_VALIDATOR:above | 3 | 0.00143 | 0 | 0.00000 |
| pooled | STRUCTURAL_VALIDATOR:name_number | 6 | 0.00287 | 0 | 0.00000 |
| pooled | STRUCTURAL_VALIDATOR:p_other | 10 | 0.00478 | 0 | 0.00000 |
| pooled | STRUCTURAL_VALIDATOR:price_belongs_to_other_variant | 6 | 0.00287 | 0 | 0.00000 |
| pooled | STRUCTURAL_VALIDATOR:same_block | 28 | 0.01338 | 0 | 0.00000 |
| pooled | STRUCTURAL_VALIDATOR:v_other | 5 | 0.00239 | 0 | 0.00000 |

| Set | Missed gold items | Gold items | Δraw/kept recall ceiling | Raw but all rejected | Additional Δkept ceiling |
| --- | --- | --- | --- | --- | --- |
| spike | 40 | 491 | 0.0815 | 2 | 0.0041 |
| p5-5 | 22 | 307 | 0.0717 | 0 | 0.0000 |
| p5-8 | 59 | 314 | 0.1879 | 0 | 0.0000 |
| p5-10 | 53 | 230 | 0.2304 | 0 | 0.0000 |
| p5-12 | 54 | 241 | 0.2241 | 0 | 0.0000 |
| p5-14 | 14 | 190 | 0.0737 | 0 | 0.0000 |
| p5-16 | 37 | 278 | 0.1331 | 0 | 0.0000 |
| pooled | 279 | 2051 | 0.1360 | 2 | 0.0010 |

#### Gold-row structural classes: invariant

| Diagnostic | spike | p5-5 | p5-8 | p5-10 | p5-12 | p5-14 | p5-16 | pooled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| above | 0 | 0 | 0 | 2 | 0 | 0 | 0 | 2 |
| header | 0 | 0 | 0 | 8 | 1 | 0 | 0 | 9 |
| implausible_amount | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| name_not_grounded | 0 | 1 | 0 | 3 | 0 | 0 | 0 | 4 |
| name_number | 0 | 1 | 13 | 1 | 0 | 0 | 0 | 15 |
| own_line | 1 | 0 | 0 | 4 | 4 | 4 | 0 | 13 |
| p_other | 0 | 3 | 8 | 36 | 23 | 6 | 10 | 86 |
| price_belongs_to_other_variant | 0 | 0 | 0 | 3 | 0 | 0 | 8 | 11 |
| same_block | 0 | 0 | 41 | 0 | 3 | 2 | 0 | 46 |
| unread | 0 | 0 | 0 | 1 | 0 | 0 | 1 | 2 |
| v_other | 0 | 4 | 1 | 5 | 1 | 2 | 16 | 29 |

#### Real downgrade classes, exact/wrong/unmatched status

| Diagnostic | spike | p5-5 | p5-8 | p5-10 | p5-12 | p5-14 | p5-16 | pooled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| exact:above | 0 | 0 | 1 | 2 | 9 | 0 | 1 | 13 |
| exact:name_number | 0 | 0 | 13 | 0 | 0 | 1 | 0 | 14 |
| exact:p_other | 1 | 6 | 6 | 4 | 17 | 2 | 2 | 38 |
| exact:price_belongs_to_other_variant | 0 | 0 | 0 | 0 | 1 | 0 | 6 | 7 |
| exact:same_block | 0 | 1 | 29 | 1 | 1 | 3 | 1 | 36 |
| exact:unread | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 3 |
| exact:v_other | 0 | 0 | 1 | 0 | 0 | 0 | 5 | 6 |
| unmatched:above | 2 | 7 | 37 | 3 | 1 | 0 | 1 | 51 |
| unmatched:name_number | 0 | 0 | 1 | 13 | 1 | 0 | 0 | 15 |
| unmatched:no_price_extracted | 5 | 65 | 33 | 22 | 5 | 6 | 2 | 138 |
| unmatched:p_other | 3 | 14 | 2 | 9 | 14 | 1 | 16 | 59 |
| unmatched:same_block | 3 | 12 | 6 | 0 | 2 | 1 | 10 | 34 |
| unmatched:unread | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 3 |
| unmatched:v_other | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 1 |
| wrong:above | 0 | 0 | 10 | 0 | 1 | 1 | 3 | 15 |
| wrong:addon_price | 0 | 2 | 0 | 0 | 0 | 0 | 0 | 2 |
| wrong:name_number | 3 | 7 | 0 | 1 | 0 | 0 | 5 | 16 |
| wrong:no_price_extracted | 35 | 136 | 11 | 3 | 5 | 16 | 10 | 216 |
| wrong:p_other | 6 | 4 | 8 | 1 | 3 | 1 | 13 | 36 |
| wrong:same_block | 1 | 2 | 13 | 0 | 0 | 0 | 10 | 26 |
| wrong:unread | 5 | 1 | 9 | 0 | 0 | 0 | 0 | 15 |

#### Overlapping diagnostic counts; not additive recall ceilings

| Diagnostic | spike | p5-5 | p5-8 | p5-10 | p5-12 | p5-14 | p5-16 | pooled |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| attempts:kept | 38 | 27 | 33 | 26 | 26 | 26 | 26 | 202 |
| attempts:retry_first | 0 | 1 | 0 | 1 | 1 | 1 | 0 | 4 |
| chunks | 38 | 27 | 33 | 26 | 26 | 26 | 26 | 202 |
| duplicate_gold_item_amount_pairs | 0 | 1 | 0 | 2 | 4 | 0 | 1 | 8 |
| final_name_not_grounded | 5 | 2 | 2 | 6 | 2 | 1 | 0 | 18 |
| final_unmatched:accept | 10 | 20 | 20 | 4 | 14 | 2 | 81 | 151 |
| final_unmatched:downgrade | 13 | 98 | 79 | 47 | 23 | 11 | 30 | 301 |
| final_unmatched:reject | 2 | 4 | 13 | 6 | 2 | 1 | 4 | 32 |
| gold_items_raw_but_not_kept | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| gold_price_loss_upper_bound | 43 | 29 | 152 | 80 | 89 | 22 | 62 | 477 |
| missed_gold_items | 40 | 22 | 59 | 53 | 54 | 14 | 37 | 279 |
| no_labelled_item_no_match_downgrades | 8 | 33 | 46 | 25 | 18 | 5 | 28 | 163 |
| no_match_downgrade:exact | 1 | 7 | 50 | 7 | 31 | 6 | 15 | 117 |
| no_match_downgrade:unmatched | 8 | 33 | 46 | 25 | 18 | 5 | 28 | 163 |
| no_match_downgrade:wrong | 15 | 16 | 40 | 2 | 4 | 2 | 31 | 110 |
| pre_repair_schema_failure:kept | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| raw_name_exact_anywhere | 519 | 474 | 444 | 256 | 297 | 240 | 492 | 2722 |
| raw_name_exact_claimed | 475 | 407 | 367 | 213 | 245 | 172 | 313 | 2192 |
| raw_name_not_exact_anywhere | 7 | 5 | 6 | 6 | 2 | 3 | 0 | 29 |
| raw_name_not_exact_claimed | 51 | 72 | 83 | 49 | 54 | 71 | 179 | 559 |
| raw_name_tokens_ungrounded | 5 | 2 | 2 | 6 | 2 | 2 | 0 | 19 |
| raw_rows | 526 | 479 | 450 | 262 | 299 | 243 | 492 | 2751 |
| sparse_retries | 0 | 1 | 0 | 1 | 1 | 1 | 0 | 4 |
| truncation:kept | 0 | 0 | 1 | 0 | 0 | 0 | 0 | 1 |
| unmatched_description_or_noise_name_proxy | 9 | 2 | 7 | 21 | 12 | 3 | 12 | 66 |
| wrong_price_association_proxy | 14 | 14 | 29 | 1 | 3 | 7 | 33 | 101 |
| wrong_price_nowhere_nearby_proxy | 5 | 4 | 12 | 1 | 1 | 1 | 0 | 24 |

Full raw/final/source baseline evidence: [baseline-attribution.json](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/baseline-attribution.json); [baseline-attribution.md](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/baseline-attribution.md).

No separate source-reviewed baseline inspection note is attached to this phase.

| Baseline proxy class | Page | Raw names | Final rows/decisions | Printed input snippet | Interpretation |
| --- | --- | --- | --- | --- | --- |
| missed_item | spike/0824dfcdd900 | no parsed nearby raw row | no nearby final row | b0023: $10 / $17; b0024: chef's choice | n/a |
| description_noise_proxy | spike/0824dfcdd900 | bigeye tuna | bigeye tuna accept | b0024: chef's choice; b0025: MAGURO* | Heuristic: overlaps label description, starts lowercase/nutrition word, or long sentence. Not manual adjudication. |
| exact_copy_not_anywhere | spike/53172819459a | Potak (Cup) | Potak (Cup) reject | b0163: Thai coconut milk soup with lemongrass flavor, chicken, mushrooms, onions, lime juice and scallions.; b0164: Potak | n/a |
| final_name_not_grounded | spike/53172819459a | Potak (Cup) | Potak (Cup) reject | b0163: Thai coconut milk soup with lemongrass flavor, chicken, mushrooms, onions, lime juice and scallions.; b0164: Potak | n/a |
| wrong_price_association_proxy | spike/630ef18b78a3 | FISH & CHIPS; FISH & CHIPS | FISH & CHIPS accept; FISH & CHIPS downgrade | b0074: Beer Battered Pollock with Crisp Potatoes and Goat Cheese Tarter Sauce; b0075: $18 | Near = amount in frozen price tokens within +/-12 blocks. Presence cannot establish ownership; absence may be structural unread price text. |
| wrong_price_nowhere_nearby_proxy | spike/630ef18b78a3 | School House Old Fashioned | School House Old Fashioned downgrade | b0115: drink-07.jpg; b0116: Cocktails | Near = amount in frozen price tokens within +/-12 blocks. Presence cannot establish ownership; absence may be structural unread price text. |
| truncation | p5-8/ddb652ccea54 | no parsed nearby raw row | no nearby final row | b0001: 0; b0002: Skip to Content | kept |
| pre_repair_schema_failure | p5-8/ddb652ccea54 | no parsed nearby raw row | no nearby final row | b0001: 0; b0002: Skip to Content | kept |
| gold_fr:above | p5-10/8d6e20477ec6 | no parsed nearby raw row | no nearby final row | b0121: CHOOSE FROM THE FOLLOWING FOR JUST $.99; b0122: -AMERICAN CHEESE | Perfect label row also fails; this gold-row FR count cannot be changed by a model. |
| gold_fr:header | p5-10/3a630628e2bf | no parsed nearby raw row | no nearby final row | b0164: $24.95; b0165: 2 Ribs | Perfect label row also fails; this gold-row FR count cannot be changed by a model. |
| gold_fr:own_line | spike/630ef18b78a3 | East Cider Dry | East Cider Dry accept | b0152: $5; b0153: $5 | Perfect label row also fails; this gold-row FR count cannot be changed by a model. |
| gold_fr:name_number | p5-5/aded7f07485b | HOT WINGS | HOT WINGS accept | b0075: SHA-BANG BANG SHRIMP(1080 cal)$14.00; b0076: SHA-BANG BANG SCALLOPS(900 cal)$17.00 | Perfect label row also fails; this gold-row FR count cannot be changed by a model. |

### Visible paired differences against both fresh subset baselines

Differences of ratios under10,000 paired page-clustered resamples, seed20261015. Each resampled page carries all its rows. Small-cohort intervals describe these selected pages and exclude run-to-run model randomness; they do not establish full-cohort generalization.

| Run | Set | Metric | Δ [95% CI] vsA | Δ [95% CI] vsB |
| --- | --- | --- | --- | --- |
| screen-baseline-qkm | spike | usable_prices | 0.0189 [0.0000, 0.0571] | 0.0000 [-0.0252, 0.0369] |
| screen-baseline-qkm | spike | item_recall_kept | 0.0183 [0.0060, 0.0478] | 0.0041 [-0.0231, 0.0228] |
| screen-baseline-qkm | p5-5 | usable_prices | -0.0431 [-0.0677, 0.0435] | 0.0191 [-0.0308, 0.0870] |
| screen-baseline-qkm | p5-5 | item_recall_kept | -0.0261 [-0.0421, -0.0125] | 0.0000 [-0.0308, 0.0225] |
| screen-baseline-qkm | p5-8 | usable_prices | 0.0194 [-0.0774, 0.0714] | 0.0111 [-0.0669, 0.0535] |
| screen-baseline-qkm | p5-8 | item_recall_kept | 0.0191 [-0.0800, 0.0948] | 0.0032 [-0.0819, 0.0698] |
| screen-baseline-qkm | p5-10 | usable_prices | -0.0337 [-0.1042, 0.0164] | -0.0562 [-0.1165, 0.0098] |
| screen-baseline-qkm | p5-10 | item_recall_kept | 0.0696 [-0.0362, 0.1522] | 0.0565 [-0.0471, 0.1522] |
| screen-baseline-qkm | p5-12 | usable_prices | 0.0505 [0.0150, 0.0833] | 0.0433 [-0.0037, 0.0833] |
| screen-baseline-qkm | p5-12 | item_recall_kept | 0.0539 [0.0000, 0.0985] | 0.0498 [-0.0092, 0.0985] |
| screen-baseline-qkm | p5-14 | usable_prices | 0.0000 [-0.0370, 0.0213] | -0.0250 [-0.0442, 0.0071] |
| screen-baseline-qkm | p5-14 | item_recall_kept | -0.0158 [-0.0286, 0.0157] | -0.0211 [-0.0305, 0.0079] |
| screen-baseline-qkm | p5-16 | usable_prices | -0.0331 [-0.1554, 0.0735] | -0.0331 [-0.1622, 0.0882] |
| screen-baseline-qkm | p5-16 | item_recall_kept | 0.0036 [-0.0641, 0.0548] | -0.0036 [-0.0723, 0.0630] |
| screen-baseline-qkm | pooled | usable_prices | 0.0010 [-0.0275, 0.0269] | -0.0048 [-0.0333, 0.0214] |
| screen-baseline-qkm | pooled | item_recall_kept | 0.0166 [-0.0070, 0.0418] | 0.0112 [-0.0118, 0.0343] |
| screen-q3-8b | spike | usable_prices | 0.0503 [0.0118, 0.0930] | 0.0314 [-0.0198, 0.0786] |
| screen-q3-8b | spike | item_recall_kept | -0.0081 [-0.0516, 0.0887] | -0.0224 [-0.0567, 0.0732] |
| screen-q3-8b | p5-5 | usable_prices | -0.0478 [-0.3636, 0.0556] | 0.0144 [-0.3143, 0.1389] |
| screen-q3-8b | p5-5 | item_recall_kept | -0.1564 [-0.3149, 0.0513] | -0.1303 [-0.2894, 0.0855] |
| screen-q3-8b | p5-8 | usable_prices | 0.0886 [-0.1321, 0.2916] | 0.0803 [-0.1450, 0.2819] |
| screen-q3-8b | p5-8 | item_recall_kept | 0.0478 [-0.0582, 0.1543] | 0.0318 [-0.0825, 0.1266] |
| screen-q3-8b | p5-10 | usable_prices | 0.0187 [-0.0162, 0.1038] | -0.0037 [-0.0427, 0.0988] |
| screen-q3-8b | p5-10 | item_recall_kept | 0.0696 [0.0000, 0.1950] | 0.0565 [-0.0217, 0.1824] |
| screen-q3-8b | p5-12 | usable_prices | 0.1300 [0.0616, 0.2402] | 0.1227 [0.0403, 0.2402] |
| screen-q3-8b | p5-12 | item_recall_kept | 0.1660 [0.0938, 0.3026] | 0.1618 [0.0833, 0.2969] |
| screen-q3-8b | p5-14 | usable_prices | 0.0000 [-0.1173, 0.0568] | -0.0250 [-0.1296, 0.0202] |
| screen-q3-8b | p5-14 | item_recall_kept | -0.0263 [-0.1037, 0.0455] | -0.0316 [-0.1037, 0.0455] |
| screen-q3-8b | p5-16 | usable_prices | -0.0298 [-0.1562, 0.0529] | -0.0298 [-0.1562, 0.0662] |
| screen-q3-8b | p5-16 | item_recall_kept | 0.0000 [-0.1154, 0.0450] | -0.0072 [-0.1154, 0.0401] |
| screen-q3-8b | pooled | usable_prices | 0.0373 [-0.0107, 0.0896] | 0.0315 [-0.0196, 0.0858] |
| screen-q3-8b | pooled | item_recall_kept | 0.0068 [-0.0522, 0.0645] | 0.0015 [-0.0531, 0.0568] |
| screen-q25-7b | spike | usable_prices | -0.0105 [-0.1132, 0.0674] | -0.0294 [-0.1697, 0.0628] |
| screen-q25-7b | spike | item_recall_kept | -0.0611 [-0.1170, 0.0542] | -0.0754 [-0.1362, 0.0488] |
| screen-q25-7b | p5-5 | usable_prices | -0.0526 [-0.1818, 0.0351] | 0.0096 [-0.1429, 0.0526] |
| screen-q25-7b | p5-5 | item_recall_kept | -0.2899 [-0.5484, 0.0000] | -0.2638 [-0.5226, 0.0000] |
| screen-q25-7b | p5-8 | usable_prices | -0.0083 [-0.0867, 0.0720] | -0.0166 [-0.1084, 0.0682] |
| screen-q25-7b | p5-8 | item_recall_kept | -0.0255 [-0.1246, 0.0653] | -0.0414 [-0.1553, 0.0605] |
| screen-q25-7b | p5-10 | usable_prices | -0.0300 [-0.1275, 0.0484] | -0.0524 [-0.1275, -0.0061] |
| screen-q25-7b | p5-10 | item_recall_kept | 0.0435 [-0.0808, 0.1389] | 0.0304 [-0.0808, 0.1373] |
| screen-q25-7b | p5-12 | usable_prices | 0.0794 [0.0305, 0.1754] | 0.0722 [0.0305, 0.1707] |
| screen-q25-7b | p5-12 | item_recall_kept | 0.0581 [0.0000, 0.1818] | 0.0539 [-0.0061, 0.1818] |
| screen-q25-7b | p5-14 | usable_prices | -0.0450 [-0.1075, 0.0492] | -0.0700 [-0.1355, 0.0492] |
| screen-q25-7b | p5-14 | item_recall_kept | -0.0368 [-0.0763, 0.0508] | -0.0421 [-0.0840, 0.0508] |
| screen-q25-7b | p5-16 | usable_prices | -0.1656 [-0.2157, -0.0808] | -0.1656 [-0.2335, -0.0707] |
| screen-q25-7b | p5-16 | item_recall_kept | -0.1151 [-0.2204, -0.0292] | -0.1223 [-0.2492, -0.0219] |
| screen-q25-7b | pooled | usable_prices | -0.0306 [-0.0697, 0.0080] | -0.0363 [-0.0792, 0.0034] |
| screen-q25-7b | pooled | item_recall_kept | -0.0692 [-0.1531, 0.0019] | -0.0746 [-0.1551, -0.0050] |

### Real-output safety and [5b]

| Set | Run | Accepted unmatched | Wrong price accepted | Claimed-block anchor n/d | Page-verbatim copy n/d | Real FR n/d | Real catch n/d | [5b] accepts | [5b] exact n/d | [5b] unmatched |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 10 | 4 | 475/526 (0.9030) | 519/526 (0.9867) | 6/442 (0.0136) | 25/39 (0.6410) | 0 | 0/0 (n/a) | 0 |
| spike | screen-baseline-b | 13 | 4 | 483/535 (0.9028) | 530/535 (0.9907) | 5/450 (0.0111) | 24/41 (0.5854) | 0 | 0/0 (n/a) | 0 |
| spike | screen-baseline-qkm | 10 | 7 | 459/540 (0.8500) | 533/540 (0.9870) | 15/466 (0.0322) | 17/34 (0.5000) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q25-7b | 13 | 5 | 362/655 (0.5527) | 635/655 (0.9695) | 18/457 (0.0394) | 63/81 (0.7778) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q3-8b | 27 | 12 | 508/578 (0.8789) | 578/578 (1.0000) | 12/471 (0.0255) | 59/98 (0.6020) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-a | 20 | 2 | 407/479 (0.8497) | 474/479 (0.9896) | 11/192 (0.0573) | 52/74 (0.7027) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-b | 20 | 2 | 393/453 (0.8675) | 448/453 (0.9890) | 15/183 (0.0820) | 52/74 (0.7027) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-qkm | 26 | 0 | 421/477 (0.8826) | 469/477 (0.9832) | 15/187 (0.0802) | 55/81 (0.6790) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q25-7b | 33 | 3 | 201/375 (0.5360) | 338/375 (0.9013) | 8/187 (0.0428) | 102/138 (0.7391) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q3-8b | 38 | 0 | 385/458 (0.8406) | 458/458 (1.0000) | 12/190 (0.0632) | 178/216 (0.8241) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-a | 20 | 1 | 367/450 (0.8156) | 444/450 (0.9867) | 70/282 (0.2482) | 95/116 (0.8190) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-b | 24 | 1 | 373/434 (0.8594) | 425/434 (0.9793) | 55/269 (0.2045) | 92/117 (0.7863) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-qkm | 38 | 1 | 413/451 (0.9157) | 448/451 (0.9933) | 47/265 (0.1774) | 91/130 (0.7000) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q25-7b | 24 | 3 | 318/474 (0.6709) | 457/474 (0.9641) | 79/293 (0.2696) | 124/151 (0.8212) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q3-8b | 23 | 3 | 382/562 (0.6797) | 556/562 (0.9893) | 65/311 (0.2090) | 208/234 (0.8889) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-a | 4 | 0 | 213/262 (0.8130) | 256/262 (0.9771) | 8/199 (0.0402) | 33/37 (0.8919) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-b | 9 | 0 | 223/284 (0.7852) | 276/284 (0.9718) | 15/211 (0.0711) | 36/45 (0.8000) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-qkm | 6 | 0 | 224/291 (0.7698) | 286/291 (0.9828) | 48/228 (0.2105) | 50/56 (0.8929) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q25-7b | 4 | 1 | 214/373 (0.5737) | 331/373 (0.8874) | 47/230 (0.2043) | 86/91 (0.9451) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q3-8b | 12 | 0 | 302/337 (0.8961) | 337/337 (1.0000) | 35/232 (0.1509) | 82/94 (0.8723) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-a | 14 | 0 | 245/299 (0.8194) | 297/299 (0.9933) | 41/251 (0.1633) | 23/37 (0.6216) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-b | 18 | 0 | 253/307 (0.8241) | 306/307 (0.9967) | 40/250 (0.1600) | 20/38 (0.5263) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-qkm | 28 | 1 | 278/319 (0.8715) | 318/319 (0.9969) | 39/262 (0.1489) | 12/41 (0.2927) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q25-7b | 26 | 2 | 200/360 (0.5556) | 359/360 (0.9972) | 55/285 (0.1930) | 44/72 (0.6111) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q3-8b | 36 | 0 | 316/393 (0.8041) | 393/393 (1.0000) | 67/315 (0.2127) | 39/75 (0.5200) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-a | 2 | 6 | 172/243 (0.7078) | 240/243 (0.9877) | 22/203 (0.1084) | 8/16 (0.5000) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-b | 6 | 5 | 178/236 (0.7542) | 233/236 (0.9873) | 17/202 (0.0842) | 4/15 (0.2667) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-qkm | 10 | 3 | 168/218 (0.7706) | 213/218 (0.9771) | 8/189 (0.0423) | 24/37 (0.6486) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q25-7b | 11 | 8 | 171/265 (0.6453) | 255/265 (0.9623) | 35/211 (0.1659) | 33/52 (0.6346) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q3-8b | 5 | 5 | 213/252 (0.8452) | 252/252 (1.0000) | 11/195 (0.0564) | 39/49 (0.7959) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-a | 81 | 2 | 313/492 (0.6362) | 492/492 (1.0000) | 66/309 (0.2136) | 63/146 (0.4315) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-b | 90 | 2 | 292/498 (0.5863) | 494/498 (0.9920) | 68/312 (0.2179) | 54/146 (0.3699) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-qkm | 90 | 3 | 322/433 (0.7436) | 423/433 (0.9769) | 39/276 (0.1413) | 49/142 (0.3451) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q25-7b | 68 | 1 | 218/482 (0.4523) | 465/482 (0.9647) | 89/281 (0.3167) | 98/167 (0.5868) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q3-8b | 84 | 2 | 339/698 (0.4857) | 697/698 (0.9986) | 53/372 (0.1425) | 115/201 (0.5721) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-a | 151 | 15 | 2192/2751 (0.7968) | 2722/2751 (0.9895) | 224/1878 (0.1193) | 299/465 (0.6430) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-b | 180 | 14 | 2195/2747 (0.7991) | 2712/2747 (0.9873) | 215/1877 (0.1145) | 282/476 (0.5924) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-qkm | 208 | 15 | 2285/2729 (0.8373) | 2690/2729 (0.9857) | 211/1873 (0.1127) | 298/521 (0.5720) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q25-7b | 179 | 23 | 1684/2984 (0.5643) | 2840/2984 (0.9517) | 331/1944 (0.1703) | 550/752 (0.7314) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q3-8b | 225 | 22 | 2445/3278 (0.7459) | 3271/3278 (0.9979) | 255/2086 (0.1222) | 720/967 (0.7446) | 0 | 0/0 (n/a) | 0 |

**The amended reduced-screen copy gate is page-verbatim copy (`copy_anywhere`):** case/punctuation-sensitive substring occurrence anywhere on the printed page among complete parsed raw rows of selected attempts. Claimed-block substring fidelity is separately reported as an anchor diagnostic, not the primary copy gate. Incomplete rows are outside that denominator; truncation/schema rates are separately preserved in score JSON. No rise in accepted unmatched or matched wrong-price rows is allowed by the numerical gates. The original218-page claimed-block gate remains historical; reduced decision JSON implements the pre-candidate amendment.

| Set | Run | Chunks | Selected schema failures n/d | Selected truncations n/d | Sparse retries n/d | All-attempt schema failures | All-attempt truncations | Generated thinking-marker attempts |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 38 | 0/38 (0.0000) | 0/38 (0.0000) | 0/38 (0.0000) | 0 | 0 | 0 |
| spike | screen-baseline-b | 38 | 0/38 (0.0000) | 0/38 (0.0000) | 0/38 (0.0000) | 0 | 0 | 0 |
| spike | screen-baseline-qkm | 38 | 0/38 (0.0000) | 0/38 (0.0000) | 0/38 (0.0000) | 0 | 0 | 0 |
| spike | screen-q25-7b | 38 | 2/38 (0.0526) | 2/38 (0.0526) | 0/38 (0.0000) | 2 | 2 | 0 |
| spike | screen-q3-8b | 38 | 0/38 (0.0000) | 0/38 (0.0000) | 0/38 (0.0000) | 0 | 0 | 0 |
| p5-5 | screen-baseline-a | 27 | 0/27 (0.0000) | 0/27 (0.0000) | 1/27 (0.0370) | 0 | 0 | 0 |
| p5-5 | screen-baseline-b | 27 | 0/27 (0.0000) | 0/27 (0.0000) | 1/27 (0.0370) | 0 | 0 | 0 |
| p5-5 | screen-baseline-qkm | 27 | 0/27 (0.0000) | 0/27 (0.0000) | 0/27 (0.0000) | 0 | 0 | 0 |
| p5-5 | screen-q25-7b | 27 | 0/27 (0.0000) | 0/27 (0.0000) | 2/27 (0.0741) | 0 | 0 | 0 |
| p5-5 | screen-q3-8b | 27 | 0/27 (0.0000) | 0/27 (0.0000) | 0/27 (0.0000) | 0 | 0 | 0 |
| p5-8 | screen-baseline-a | 33 | 1/33 (0.0303) | 1/33 (0.0303) | 0/33 (0.0000) | 1 | 1 | 0 |
| p5-8 | screen-baseline-b | 33 | 0/33 (0.0000) | 0/33 (0.0000) | 0/33 (0.0000) | 0 | 0 | 0 |
| p5-8 | screen-baseline-qkm | 33 | 0/33 (0.0000) | 0/33 (0.0000) | 0/33 (0.0000) | 0 | 0 | 0 |
| p5-8 | screen-q25-7b | 33 | 3/33 (0.0909) | 3/33 (0.0909) | 0/33 (0.0000) | 3 | 3 | 0 |
| p5-8 | screen-q3-8b | 33 | 4/33 (0.1212) | 4/33 (0.1212) | 1/33 (0.0303) | 4 | 4 | 0 |
| p5-10 | screen-baseline-a | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-10 | screen-baseline-b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-10 | screen-baseline-qkm | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-10 | screen-q25-7b | 26 | 1/26 (0.0385) | 1/26 (0.0385) | 0/26 (0.0000) | 1 | 1 | 0 |
| p5-10 | screen-q3-8b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 0/26 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-baseline-a | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-12 | screen-baseline-b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-12 | screen-baseline-qkm | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 0/26 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-q25-7b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 0/26 (0.0000) | 0 | 0 | 0 |
| p5-12 | screen-q3-8b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 0/26 (0.0000) | 0 | 0 | 0 |
| p5-14 | screen-baseline-a | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-14 | screen-baseline-b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-14 | screen-baseline-qkm | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-14 | screen-q25-7b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 1/26 (0.0385) | 0 | 0 | 0 |
| p5-14 | screen-q3-8b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 0/26 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-baseline-a | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 0/26 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-baseline-b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 0/26 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-baseline-qkm | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 0/26 (0.0000) | 0 | 0 | 0 |
| p5-16 | screen-q25-7b | 26 | 0/26 (0.0000) | 0/26 (0.0000) | 2/26 (0.0769) | 0 | 0 | 0 |
| p5-16 | screen-q3-8b | 26 | 3/26 (0.1154) | 3/26 (0.1154) | 0/26 (0.0000) | 3 | 3 | 0 |
| pooled | screen-baseline-a | 202 | 1/202 (0.0050) | 1/202 (0.0050) | 4/202 (0.0198) | 1 | 1 | 0 |
| pooled | screen-baseline-b | 202 | 0/202 (0.0000) | 0/202 (0.0000) | 4/202 (0.0198) | 0 | 0 | 0 |
| pooled | screen-baseline-qkm | 202 | 0/202 (0.0000) | 0/202 (0.0000) | 2/202 (0.0099) | 0 | 0 | 0 |
| pooled | screen-q25-7b | 202 | 6/202 (0.0297) | 6/202 (0.0297) | 5/202 (0.0248) | 6 | 6 | 0 |
| pooled | screen-q3-8b | 202 | 7/202 (0.0347) | 7/202 (0.0347) | 1/202 (0.0050) | 7 | 7 | 0 |

### Model-invariant validator evidence

| Set | Gold-row FR, model invariant | Injected-corruption catch, model invariant |
| --- | --- | --- |
| spike | 1/477 (0.0021) | 226/236 (0.9576) |
| p5-5 | 11/209 (0.0526) | 184/184 (1.0000) |
| p5-8 | 63/361 (0.1745) | 244/246 (0.9919) |
| p5-10 | 63/267 (0.2360) | 197/198 (0.9949) |
| p5-12 | 32/277 (0.1155) | 200/200 (1.0000) |
| p5-14 | 14/200 (0.0700) | 199/200 (0.9950) |
| p5-16 | 35/302 (0.1159) | 176/176 (1.0000) |
| pooled | 219/2093 (0.1046) | 1426/1440 (0.9903) (sum of per-set trials) |

Gold-row FR and injected-corruption catch do not vary with the extraction model. They cannot be counted as a model benefit. The original next-draw pooled gold-FR blocker near0.095 versus target near0.05 is unaffected; a reduced phase does not authorize the next held-out draw.

### Subset numerical gate outcomes

| Run | Frozen criterion gate | Result | Reason | Evidence |
| --- | --- | --- | --- | --- |
| screen-baseline-qkm | worthwhile_gain | inconclusive | Usable prices OR kept item recall must clear against BOTH baseline replicates; gains cannot mix metrics across baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | pooled_raw_recall | pass | Frozen §8 raw item recall bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | pooled_price_accuracy | pass | Frozen §8 accepted matched price accuracy bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | price_accuracy_noninferiority | pass | Price accuracy safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | previously_passing_sets | pass | No previously passing tuning-set raw-recall or accuracy bar may be crossed. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | accepted_unmatched | fail | Absolute count must be no greater than either baseline for accepted_unmatched. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | wrong_accepted_price | fail | Absolute count must be no greater than either baseline for wrong_accepted_price. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | exact_name_copy | fail | No worse exact-name copy fidelity against either baseline. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | validator_false_reject | pass | Real-output validator_false_reject safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-baseline-qkm | validator_catch | fail | Real-output validator_catch safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json) |
| screen-q25-7b | worthwhile_gain | inconclusive | Usable prices OR kept item recall must clear against BOTH baseline replicates; gains cannot mix metrics across baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | pooled_raw_recall | fail | Frozen §8 raw item recall bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | pooled_price_accuracy | pass | Frozen §8 accepted matched price accuracy bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | price_accuracy_noninferiority | fail | Price accuracy safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | previously_passing_sets | fail | No previously passing tuning-set raw-recall or accuracy bar may be crossed. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | accepted_unmatched | fail | Absolute count must be no greater than either baseline for accepted_unmatched. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | wrong_accepted_price | fail | Absolute count must be no greater than either baseline for wrong_accepted_price. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | exact_name_copy | fail | No worse exact-name copy fidelity against either baseline. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | validator_false_reject | fail | Real-output validator_false_reject safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q25-7b | validator_catch | pass | Real-output validator_catch safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json) |
| screen-q3-8b | worthwhile_gain | inconclusive | Usable prices OR kept item recall must clear against BOTH baseline replicates; gains cannot mix metrics across baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | pooled_raw_recall | pass | Frozen §8 raw item recall bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | pooled_price_accuracy | pass | Frozen §8 accepted matched price accuracy bar. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | price_accuracy_noninferiority | fail | Price accuracy safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | previously_passing_sets | fail | No previously passing tuning-set raw-recall or accuracy bar may be crossed. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | accepted_unmatched | fail | Absolute count must be no greater than either baseline for accepted_unmatched. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | wrong_accepted_price | fail | Absolute count must be no greater than either baseline for wrong_accepted_price. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | exact_name_copy | pass | No worse exact-name copy fidelity against either baseline. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | validator_false_reject | fail | Real-output validator_false_reject safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |
| screen-q3-8b | validator_catch | pass | Real-output validator_catch safety against both baselines. | [all numerical subchecks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json) |

**screen-baseline-qkm: fails_criterion on 30 selected pages only.** Subset checks clear=False; full218-page acceptance is untested. [all gate evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/decision-v9.json).

**screen-q25-7b: fails_criterion on 30 selected pages only.** Subset checks clear=False; full218-page acceptance is untested. [all gate evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-v9.json).

**screen-q3-8b: fails_criterion on 30 selected pages only.** Subset checks clear=False; full218-page acceptance is untested. [all gate evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-v9.json).

### Fixed difficult-page slices and proxy regressions

| Run | Fixed overlapping slice | Pages | Baseline A usable | Candidate usable | Δusable [paired95% CI] vsA | Kept recall A→candidate |
| --- | --- | --- | --- | --- | --- | --- |
| screen-baseline-qkm | rare_formats | 3 | 0.7537 | 0.7438 | -0.0100 [-0.1579, 0.0286] | 0.8729 → 0.8609 |
| screen-baseline-qkm | price_before_name | 8 | 0.5916 | 0.6045 | 0.0130 [-0.0234, 0.0474] | 0.8023 → 0.8656 |
| screen-baseline-qkm | multiple_prices | 24 | 0.7785 | 0.7790 | 0.0005 [-0.0307, 0.0286] | 0.8675 → 0.8869 |
| screen-baseline-qkm | structural_fr | 19 | 0.7190 | 0.7005 | -0.0185 [-0.0582, 0.0182] | 0.8446 → 0.8630 |
| screen-q25-7b | rare_formats | 3 | 0.7537 | 0.7761 | 0.0224 [0.0175, 0.0286] | 0.8729 → 0.8153 |
| screen-q25-7b | price_before_name | 8 | 0.5916 | 0.5511 | -0.0405 [-0.1292, 0.0407] | 0.8023 → 0.7754 |
| screen-q25-7b | multiple_prices | 24 | 0.7785 | 0.7450 | -0.0336 [-0.0751, 0.0049] | 0.8675 → 0.8321 |
| screen-q25-7b | structural_fr | 19 | 0.7190 | 0.6767 | -0.0423 [-0.0918, 0.0053] | 0.8446 → 0.8104 |
| screen-q3-8b | rare_formats | 3 | 0.7537 | 0.7512 | -0.0025 [-0.2456, 0.0417] | 0.8729 → 0.8273 |
| screen-q3-8b | price_before_name | 8 | 0.5916 | 0.6759 | 0.0843 [0.0030, 0.2097] | 0.8023 → 0.8887 |
| screen-q3-8b | multiple_prices | 24 | 0.7785 | 0.8116 | 0.0330 [-0.0187, 0.0869] | 0.8675 → 0.8875 |
| screen-q3-8b | structural_fr | 19 | 0.7190 | 0.7436 | 0.0246 [-0.0532, 0.1029] | 0.8446 → 0.8806 |

Slices select whole pages and overlap; their metrics include every row on the selected page. Rare format means <=10 cohort pages; price-before-name uses fixed nearby token geometry; multiple-prices and structural-FR flags derive from frozen labels/validator. These are tuning diagnostics, not independent tests or item-level subgroup estimates.

| Run | Proxy class/direction | Page | Proxy A→candidate | Δusable numerator | Changed final rows | Printed source snippet | Evidence |
| --- | --- | --- | --- | --- | --- | --- | --- |
| screen-baseline-qkm | misses fix | p5-12/e66ce335637a | 19.0000 → 8.0000 | 10 | baseline: Nachos n/a downgrade; Nachos 10.99 downgrade; candidate: Nachos 10.99 accept; Pulled Pork Nachos 10.99 accept | b0107: Nachos; b0109: Half $10.99 \\| Full $15.99 • Beef picadillo or fajita chicken with refried beans \\| Sub for Marinated Steak +$2.… | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/difficult.json) |
| screen-baseline-qkm | misses regression | p5-16/5d960df16b84 | 2.0000 → 6.0000 | -13 | baseline: By the Pound 42 accept; Brisket 42 accept; candidate: Brisket 42 accept; Brisket 42 reject | b0049: $42 / lb | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/difficult.json) |
| screen-baseline-qkm | names_unmatched_proxy regression | p5-8/a8684c49dfa1 | 2.0000 → 3.0000 | -9 | baseline: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept; candidate: Super-Bert Half Pounder 6.34 accept; Hot Ham & Swiss 5.19 accept | b0009: $4.99; b0010: Super-Bert Half Pounder | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/difficult.json) |
| screen-baseline-qkm | price_association_proxy regression | p5-16/5d960df16b84 | 2.0000 → 5.0000 | -13 | baseline: By the Pound 42 accept; Brisket 42 accept; candidate: Brisket 42 accept; Brisket 42 reject | b0049: $42 / lb | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/difficult.json) |
| screen-baseline-qkm | copy regression | p5-10/3a630628e2bf | 0.0909 → 0.1774 | -10 | baseline: Plates n/a downgrade; Cole Slaw, Beans and Potato Salad 5.95 downgrade; candidate: Brisket 23.95 accept; Pork Ribs 18.95 accept | b0068: Plates; b0070: Brisket | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/difficult.json) |
| screen-q25-7b | misses fix | p5-12/e442534a6bed | 17.0000 → 8.0000 | 8 | baseline: A Pita Fusion gyro wrap cut in half, packed with meat, lettuce, … 11.95 downgrade; Enjoy our bowl with grilled chicken, rice, veggies, and hummus a… 11.95 accept; candidate: Build Your Own Pita 11.95 downgrade; Build Your Own Bowl 11.95 accept | b0022: A Pita Fusion gyro wrap cut in half, packed with meat, lettuce, tomato, and sauce.; b0021: Build your own Pita, Bowl or Salad | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | misses regression | p5-16/6d5cdfffe336 | 12.0000 → 32.0000 | -24 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | names_unmatched_proxy regression | p5-16/6d5cdfffe336 | 2.0000 → 5.0000 | -24 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | price_association_proxy regression | p5-16/6d5cdfffe336 | 4.0000 → 11.0000 | -24 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | copy regression | p5-16/6d5cdfffe336 | 0.0891 → 0.4176 | -24 | baseline: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept; candidate: Fajita Nachos 2.08 accept; Quesadillas 13.53 accept | b0021: Fajita Nachos$2.08; b0020: Fajita | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | schema regression | spike/630ef18b78a3 | 0.0000 → 1.0000 | -5 | baseline: MONTREAL FRIES 15 accept; ASIAN CRUNCH SALAD 13 accept; candidate: Montreal Fries 15 accept; Montreal Fries 13 downgrade | b0036: MONTREAL FRIES; b0035: $15 | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/difficult.json) |
| screen-q25-7b | truncation regression | spike/630ef18b78a3 | 0.0000 → 1.0000 | -5 | baseline: MONTREAL FRIES 15 accept; ASIAN CRUNCH SALAD 13 accept; candidate: Montreal Fries 15 accept; Montreal Fries 13 downgrade | b0036: MONTREAL FRIES; b0035: $15 | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/difficult.json) |
| screen-q3-8b | misses fix | p5-8/f2f4666c11f4 | 17.0000 → 0.0000 | 42 | baseline: Vacancy Pilsner 5 downgrade; Bratwurst 19 downgrade; candidate: The Prince’s Faves 5 downgrade; Vacancy Pilsner 5 downgrade | b0034: Vacancy Pilsner; b0032: The Prince’s Faves | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | misses regression | p5-16/5d960df16b84 | 2.0000 → 10.0000 | -14 | baseline: By the Pound 42 accept; Brisket 42 accept; candidate: By the Pound 42 accept; Brisket 42 accept | b0049: $42 / lb | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | names_unmatched_proxy regression | p5-8/a8684c49dfa1 | 2.0000 → 4.0000 | -14 | baseline: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept; candidate: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept | b0009: $4.99; b0007: Super-Bert Quarter Pounder | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | price_association_proxy regression | p5-8/a8684c49dfa1 | 1.0000 → 11.0000 | -14 | baseline: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept; candidate: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept | b0009: $4.99; b0007: Super-Bert Quarter Pounder | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | copy regression | p5-8/a8684c49dfa1 | 0.3393 → 0.4340 | -14 | baseline: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept; candidate: Super-Bert Quarter Pounder 4.99 accept; Super-Bert Half Pounder 6.34 accept | b0009: $4.99; b0007: Super-Bert Quarter Pounder | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | schema regression | p5-8/b208f79d3315 | 0.0000 → 3.0000 | 3 | baseline: Fried green plantain with lettuce, tomato, fresh cheese, avocado… n/a downgrade; Patacones 12 downgrade; candidate: Fried green plantain with lettuce, tomato, fresh cheese, avocado… 12 reject; Fried arepitas (corn dough) with cheese and venezuelan cream (6 … 8 reject | b0037: Fried green plantain with lettuce, tomato, fresh cheese, avocado, garlic sauce, shredded beef and shredded chick… | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/difficult.json) |
| screen-q3-8b | truncation regression | p5-8/b208f79d3315 | 0.0000 → 3.0000 | 3 | baseline: Fried green plantain with lettuce, tomato, fresh cheese, avocado… n/a downgrade; Patacones 12 downgrade; candidate: Fried green plantain with lettuce, tomato, fresh cheese, avocado… 12 reject; Fried arepitas (corn dough) with cheese and venezuelan cream (6 … 8 reject | b0037: Fried green plantain with lettuce, tomato, fresh cheese, avocado, garlic sauce, shredded beef and shredded chick… | [full raw/final/source evidence](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/difficult.json) |

Examples are automatically selected proxy changes, not manually adjudicated fixes, hallucinations or price-ownership errors. Names shown are final rows; linked evidence contains pre-repair raw rows and generated continuations alongside final verdicts. A proxy improvement can accompany a usable-price regression. Full slice membership and original-label slice results are preserved in each run’s difficult.json/difficult.md.

### Reduced-phase routing simulations

| Run | Policy | Meaning | Routed pages/share | Candidate answers kept | Usable | Kept recall | Accuracy | Unmatched accepted | Wrong price accepted | Generated routed tokens | Pi1.8tok/s decode proxy h | Subset criterion |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| screen-q25-7b | coverage_unconditional | label-free realized | 13/30 (0.4333) | 13 | 0.7578 | 0.8113 | 0.9872 | 146 | 21 | 37307 | 5.757 | fails_criterion |
| screen-q25-7b | coverage_keep_more_accepted | label-free realized | 13/30 (0.4333) | 6 | 0.7817 | 0.8688 | 0.9894 | 173 | 18 | 37307 | 5.757 | fails_criterion |
| screen-q25-7b | oracle_labelled_ceiling | unrealizable labelled ceiling | 15/30 (0.5000) | 15 | 0.7993 | 0.8688 | 0.9902 | 169 | 17 | 41404 | 6.390 | not_assessable_oracle |
| screen-q3-8b | coverage_unconditional | label-free realized | 13/30 (0.4333) | 13 | 0.7903 | 0.8532 | 0.9867 | 205 | 24 | 42240 | 6.519 | fails_criterion |
| screen-q3-8b | coverage_keep_more_accepted | label-free realized | 13/30 (0.4333) | 10 | 0.8027 | 0.8620 | 0.9869 | 205 | 24 | 42240 | 6.519 | fails_criterion |
| screen-q3-8b | oracle_labelled_ceiling | unrealizable labelled ceiling | 20/30 (0.6667) | 20 | 0.8409 | 0.9069 | 0.9942 | 174 | 11 | 61830 | 9.542 | not_assessable_oracle |

Routing is simulated on the same reduced pages without new model calls. Oracle routing uses labels and is not realizable. The fixed realized coverage rule and keep-more-accepted alternative use baseline output only; all candidate rows still pass the identical validator+[5b]. Any provisional escalation requires the same subset quality checks and <=30% routed pages. Decode proxy = every routed candidate generated token, including discarded attempts, /1.8/3600. It excludes prefill, dispatch, conversion, contention and overhead, and does not predict another model’s actual NPU speed. The small routed-page denominator makes this screening estimate particularly uncertain.

[screen-q25-7b/coverage_unconditional full gate checks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-coverage_unconditional-v9.json); [screen-q25-7b/coverage_keep_more_accepted full gate checks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-coverage_keep_more_accepted-v9.json); [screen-q25-7b/oracle_labelled_ceiling full gate checks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/decision-oracle_labelled_ceiling-v9.json); [screen-q3-8b/coverage_unconditional full gate checks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-coverage_unconditional-v9.json); [screen-q3-8b/coverage_keep_more_accepted full gate checks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-coverage_keep_more_accepted-v9.json); [screen-q3-8b/oracle_labelled_ceiling full gate checks](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/decision-oracle_labelled_ceiling-v9.json)

### Original-label continuity on the same selected pages

| Set | Run | Gold items | Gold price rows | Raw recall n/d | Kept recall n/d | Usable n/d | Price accuracy n/d |
| --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 491 | 477 | 451/491 (0.9185) | 449/491 (0.9145) | 434/477 (0.9099) | 436/440 (0.9909) |
| spike | screen-baseline-b | 491 | 477 | 457/491 (0.9308) | 456/491 (0.9287) | 443/477 (0.9287) | 445/449 (0.9911) |
| spike | screen-baseline-qkm | 491 | 477 | 458/491 (0.9328) | 458/491 (0.9328) | 443/477 (0.9287) | 451/458 (0.9847) |
| spike | screen-q25-7b | 491 | 477 | 430/491 (0.8758) | 419/491 (0.8534) | 429/477 (0.8994) | 439/444 (0.9887) |
| spike | screen-q3-8b | 491 | 477 | 473/491 (0.9633) | 445/491 (0.9063) | 458/477 (0.9602) | 459/471 (0.9745) |
| p5-5 | screen-baseline-a | 307 | 209 | 285/307 (0.9283) | 285/307 (0.9283) | 180/209 (0.8612) | 181/183 (0.9891) |
| p5-5 | screen-baseline-b | 307 | 209 | 277/307 (0.9023) | 277/307 (0.9023) | 167/209 (0.7990) | 168/170 (0.9882) |
| p5-5 | screen-baseline-qkm | 307 | 209 | 277/307 (0.9023) | 277/307 (0.9023) | 171/209 (0.8182) | 172/172 (1.0000) |
| p5-5 | screen-q25-7b | 307 | 209 | 209/307 (0.6808) | 196/307 (0.6384) | 169/209 (0.8086) | 179/182 (0.9835) |
| p5-5 | screen-q3-8b | 307 | 209 | 267/307 (0.8697) | 237/307 (0.7720) | 170/209 (0.8134) | 178/178 (1.0000) |
| p5-8 | screen-baseline-a | 317 | 364 | 255/317 (0.8044) | 255/317 (0.8044) | 209/364 (0.5742) | 212/213 (0.9953) |
| p5-8 | screen-baseline-b | 317 | 364 | 260/317 (0.8202) | 260/317 (0.8202) | 212/364 (0.5824) | 214/215 (0.9953) |
| p5-8 | screen-baseline-qkm | 317 | 364 | 261/317 (0.8233) | 261/317 (0.8233) | 216/364 (0.5934) | 218/219 (0.9954) |
| p5-8 | screen-q25-7b | 317 | 364 | 250/317 (0.7886) | 247/317 (0.7792) | 206/364 (0.5659) | 214/217 (0.9862) |
| p5-8 | screen-q3-8b | 317 | 364 | 273/317 (0.8612) | 270/317 (0.8517) | 241/364 (0.6621) | 246/249 (0.9880) |
| p5-10 | screen-baseline-a | 232 | 269 | 178/232 (0.7672) | 178/232 (0.7672) | 188/269 (0.6989) | 192/192 (1.0000) |
| p5-10 | screen-baseline-b | 232 | 269 | 181/232 (0.7802) | 181/232 (0.7802) | 194/269 (0.7212) | 197/197 (1.0000) |
| p5-10 | screen-baseline-qkm | 232 | 269 | 194/232 (0.8362) | 193/232 (0.8319) | 178/269 (0.6617) | 180/180 (1.0000) |
| p5-10 | screen-q25-7b | 232 | 269 | 190/232 (0.8190) | 187/232 (0.8060) | 179/269 (0.6654) | 183/184 (0.9946) |
| p5-10 | screen-q3-8b | 232 | 269 | 193/232 (0.8319) | 193/232 (0.8319) | 192/269 (0.7138) | 197/197 (1.0000) |
| p5-12 | screen-baseline-a | 242 | 278 | 187/242 (0.7727) | 187/242 (0.7727) | 188/278 (0.6763) | 210/210 (1.0000) |
| p5-12 | screen-baseline-b | 242 | 278 | 188/242 (0.7769) | 188/242 (0.7769) | 190/278 (0.6835) | 210/210 (1.0000) |
| p5-12 | screen-baseline-qkm | 242 | 278 | 200/242 (0.8264) | 200/242 (0.8264) | 202/278 (0.7266) | 223/224 (0.9955) |
| p5-12 | screen-q25-7b | 242 | 278 | 201/242 (0.8306) | 201/242 (0.8306) | 210/278 (0.7554) | 230/232 (0.9914) |
| p5-12 | screen-q3-8b | 242 | 278 | 227/242 (0.9380) | 227/242 (0.9380) | 224/278 (0.8058) | 248/248 (1.0000) |
| p5-14 | screen-baseline-a | 196 | 206 | 176/196 (0.8980) | 176/196 (0.8980) | 178/206 (0.8641) | 181/187 (0.9679) |
| p5-14 | screen-baseline-b | 196 | 206 | 177/196 (0.9031) | 177/196 (0.9031) | 183/206 (0.8883) | 185/190 (0.9737) |
| p5-14 | screen-baseline-qkm | 196 | 206 | 173/196 (0.8827) | 173/196 (0.8827) | 178/206 (0.8641) | 181/184 (0.9837) |
| p5-14 | screen-q25-7b | 196 | 206 | 173/196 (0.8827) | 169/196 (0.8622) | 169/206 (0.8204) | 176/184 (0.9565) |
| p5-14 | screen-q3-8b | 196 | 206 | 181/196 (0.9235) | 177/196 (0.9031) | 178/206 (0.8641) | 184/189 (0.9735) |
| p5-16 | screen-baseline-a | 278 | 302 | 241/278 (0.8669) | 241/278 (0.8669) | 240/302 (0.7947) | 243/245 (0.9918) |
| p5-16 | screen-baseline-b | 278 | 302 | 243/278 (0.8741) | 243/278 (0.8741) | 240/302 (0.7947) | 244/246 (0.9919) |
| p5-16 | screen-baseline-qkm | 278 | 302 | 242/278 (0.8705) | 242/278 (0.8705) | 230/302 (0.7616) | 237/240 (0.9875) |
| p5-16 | screen-q25-7b | 278 | 302 | 212/278 (0.7626) | 209/278 (0.7518) | 190/302 (0.6291) | 192/193 (0.9948) |
| p5-16 | screen-q3-8b | 278 | 302 | 242/278 (0.8705) | 241/278 (0.8669) | 231/302 (0.7649) | 319/321 (0.9938) |
| pooled | screen-baseline-a | 2063 | 2105 | 1773/2063 (0.8594) | 1771/2063 (0.8585) | 1617/2105 (0.7682) | 1655/1670 (0.9910) |
| pooled | screen-baseline-b | 2063 | 2105 | 1783/2063 (0.8643) | 1782/2063 (0.8638) | 1629/2105 (0.7739) | 1663/1677 (0.9917) |
| pooled | screen-baseline-qkm | 2063 | 2105 | 1805/2063 (0.8749) | 1804/2063 (0.8745) | 1618/2105 (0.7686) | 1662/1677 (0.9911) |
| pooled | screen-q25-7b | 2063 | 2105 | 1665/2063 (0.8071) | 1628/2063 (0.7891) | 1552/2105 (0.7373) | 1613/1636 (0.9859) |
| pooled | screen-q3-8b | 2063 | 2105 | 1856/2063 (0.8997) | 1790/2063 (0.8677) | 1694/2105 (0.8048) | 1831/1853 (0.9881) |

Original-label safety and [5b]:

| Set | Run | Accepted unmatched | Wrong price accepted | Claimed-block anchor n/d | Page-verbatim copy n/d | Real FR n/d | Real catch n/d | [5b] accepts | [5b] exact n/d | [5b] unmatched |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| spike | screen-baseline-a | 10 | 4 | 475/526 (0.9030) | 519/526 (0.9867) | 6/442 (0.0136) | 25/39 (0.6410) | 0 | 0/0 (n/a) | 0 |
| spike | screen-baseline-b | 13 | 4 | 483/535 (0.9028) | 530/535 (0.9907) | 5/450 (0.0111) | 24/41 (0.5854) | 0 | 0/0 (n/a) | 0 |
| spike | screen-baseline-qkm | 10 | 7 | 459/540 (0.8500) | 533/540 (0.9870) | 15/466 (0.0322) | 17/34 (0.5000) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q25-7b | 13 | 5 | 362/655 (0.5527) | 635/655 (0.9695) | 18/457 (0.0394) | 63/81 (0.7778) | 0 | 0/0 (n/a) | 0 |
| spike | screen-q3-8b | 27 | 12 | 508/578 (0.8789) | 578/578 (1.0000) | 12/471 (0.0255) | 59/98 (0.6020) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-a | 20 | 2 | 407/479 (0.8497) | 474/479 (0.9896) | 11/192 (0.0573) | 52/74 (0.7027) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-b | 20 | 2 | 393/453 (0.8675) | 448/453 (0.9890) | 15/183 (0.0820) | 52/74 (0.7027) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-baseline-qkm | 26 | 0 | 421/477 (0.8826) | 469/477 (0.9832) | 15/187 (0.0802) | 55/81 (0.6790) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q25-7b | 33 | 3 | 201/375 (0.5360) | 338/375 (0.9013) | 8/187 (0.0428) | 102/138 (0.7391) | 0 | 0/0 (n/a) | 0 |
| p5-5 | screen-q3-8b | 38 | 0 | 385/458 (0.8406) | 458/458 (1.0000) | 12/190 (0.0632) | 178/216 (0.8241) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-a | 20 | 1 | 367/450 (0.8156) | 444/450 (0.9867) | 70/282 (0.2482) | 95/116 (0.8190) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-b | 24 | 1 | 373/434 (0.8594) | 425/434 (0.9793) | 55/269 (0.2045) | 92/117 (0.7863) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-baseline-qkm | 38 | 1 | 413/451 (0.9157) | 448/451 (0.9933) | 47/265 (0.1774) | 91/130 (0.7000) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q25-7b | 24 | 3 | 318/474 (0.6709) | 457/474 (0.9641) | 79/293 (0.2696) | 124/151 (0.8212) | 0 | 0/0 (n/a) | 0 |
| p5-8 | screen-q3-8b | 23 | 3 | 382/562 (0.6797) | 556/562 (0.9893) | 65/311 (0.2090) | 208/234 (0.8889) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-a | 3 | 0 | 213/262 (0.8130) | 256/262 (0.9771) | 8/200 (0.0400) | 33/36 (0.9167) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-b | 8 | 0 | 223/284 (0.7852) | 276/284 (0.9718) | 15/212 (0.0708) | 36/44 (0.8182) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-baseline-qkm | 6 | 0 | 224/291 (0.7698) | 286/291 (0.9828) | 48/228 (0.2105) | 50/56 (0.8929) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q25-7b | 4 | 1 | 214/373 (0.5737) | 331/373 (0.8874) | 47/230 (0.2043) | 86/91 (0.9451) | 0 | 0/0 (n/a) | 0 |
| p5-10 | screen-q3-8b | 12 | 0 | 302/337 (0.8961) | 337/337 (1.0000) | 35/232 (0.1509) | 82/94 (0.8723) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-a | 14 | 0 | 245/299 (0.8194) | 297/299 (0.9933) | 41/251 (0.1633) | 23/37 (0.6216) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-b | 18 | 0 | 253/307 (0.8241) | 306/307 (0.9967) | 40/250 (0.1600) | 20/38 (0.5263) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-baseline-qkm | 28 | 1 | 278/319 (0.8715) | 318/319 (0.9969) | 39/262 (0.1489) | 12/41 (0.2927) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q25-7b | 26 | 2 | 200/360 (0.5556) | 359/360 (0.9972) | 55/285 (0.1930) | 44/72 (0.6111) | 0 | 0/0 (n/a) | 0 |
| p5-12 | screen-q3-8b | 36 | 0 | 316/393 (0.8041) | 393/393 (1.0000) | 67/315 (0.2127) | 39/75 (0.5200) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-a | 2 | 6 | 172/243 (0.7078) | 240/243 (0.9877) | 22/203 (0.1084) | 8/16 (0.5000) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-b | 6 | 5 | 178/236 (0.7542) | 233/236 (0.9873) | 17/202 (0.0842) | 4/15 (0.2667) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-baseline-qkm | 10 | 3 | 168/218 (0.7706) | 213/218 (0.9771) | 8/189 (0.0423) | 24/37 (0.6486) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q25-7b | 11 | 8 | 171/265 (0.6453) | 255/265 (0.9623) | 35/211 (0.1659) | 33/52 (0.6346) | 0 | 0/0 (n/a) | 0 |
| p5-14 | screen-q3-8b | 5 | 5 | 213/252 (0.8452) | 252/252 (1.0000) | 17/201 (0.0846) | 33/43 (0.7674) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-a | 81 | 2 | 313/492 (0.6362) | 492/492 (1.0000) | 66/309 (0.2136) | 63/146 (0.4315) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-b | 90 | 2 | 292/498 (0.5863) | 494/498 (0.9920) | 68/312 (0.2179) | 54/146 (0.3699) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-baseline-qkm | 90 | 3 | 322/433 (0.7436) | 423/433 (0.9769) | 39/276 (0.1413) | 49/142 (0.3451) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q25-7b | 68 | 1 | 218/482 (0.4523) | 465/482 (0.9647) | 89/281 (0.3167) | 98/167 (0.5868) | 0 | 0/0 (n/a) | 0 |
| p5-16 | screen-q3-8b | 84 | 2 | 339/698 (0.4857) | 697/698 (0.9986) | 53/372 (0.1425) | 115/201 (0.5721) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-a | 150 | 15 | 2192/2751 (0.7968) | 2722/2751 (0.9895) | 224/1879 (0.1192) | 299/464 (0.6444) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-b | 179 | 14 | 2195/2747 (0.7991) | 2712/2747 (0.9873) | 215/1878 (0.1145) | 282/475 (0.5937) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-baseline-qkm | 208 | 15 | 2285/2729 (0.8373) | 2690/2729 (0.9857) | 211/1873 (0.1127) | 298/521 (0.5720) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q25-7b | 179 | 23 | 1684/2984 (0.5643) | 2840/2984 (0.9517) | 331/1944 (0.1703) | 550/752 (0.7314) | 0 | 0/0 (n/a) | 0 |
| pooled | screen-q3-8b | 225 | 22 | 2445/3278 (0.7459) | 3271/3278 (0.9979) | 261/2092 (0.1248) | 714/961 (0.7430) | 0 | 0/0 (n/a) | 0 |

Original-label baseline gaps:

| Set | Metric | Baseline A | Baseline B | Absolute A/B gap |
| --- | --- | --- | --- | --- |
| spike | usable_prices | 0.9099 | 0.9287 | 0.0189 |
| spike | item_recall_kept | 0.9145 | 0.9287 | 0.0143 |
| spike | item_recall | 0.9185 | 0.9308 | 0.0122 |
| spike | price_accuracy | 0.9909 | 0.9911 | 0.0002 |
| spike | copy_claimed | 0.9030 | 0.9028 | 0.0002 |
| spike | copy_anywhere | 0.9867 | 0.9907 | 0.0040 |
| spike | validator_false_reject | 0.0136 | 0.0111 | 0.0025 |
| spike | validator_catch | 0.6410 | 0.5854 | 0.0557 |
| p5-5 | usable_prices | 0.8612 | 0.7990 | 0.0622 |
| p5-5 | item_recall_kept | 0.9283 | 0.9023 | 0.0261 |
| p5-5 | item_recall | 0.9283 | 0.9023 | 0.0261 |
| p5-5 | price_accuracy | 0.9891 | 0.9882 | 0.0008 |
| p5-5 | copy_claimed | 0.8497 | 0.8675 | 0.0179 |
| p5-5 | copy_anywhere | 0.9896 | 0.9890 | 0.0006 |
| p5-5 | validator_false_reject | 0.0573 | 0.0820 | 0.0247 |
| p5-5 | validator_catch | 0.7027 | 0.7027 | 0.0000 |
| p5-8 | usable_prices | 0.5742 | 0.5824 | 0.0082 |
| p5-8 | item_recall_kept | 0.8044 | 0.8202 | 0.0158 |
| p5-8 | item_recall | 0.8044 | 0.8202 | 0.0158 |
| p5-8 | price_accuracy | 0.9953 | 0.9953 | 0.0000 |
| p5-8 | copy_claimed | 0.8156 | 0.8594 | 0.0439 |
| p5-8 | copy_anywhere | 0.9867 | 0.9793 | 0.0074 |
| p5-8 | validator_false_reject | 0.2482 | 0.2045 | 0.0438 |
| p5-8 | validator_catch | 0.8190 | 0.7863 | 0.0326 |
| p5-10 | usable_prices | 0.6989 | 0.7212 | 0.0223 |
| p5-10 | item_recall_kept | 0.7672 | 0.7802 | 0.0129 |
| p5-10 | item_recall | 0.7672 | 0.7802 | 0.0129 |
| p5-10 | price_accuracy | 1.0000 | 1.0000 | 0.0000 |
| p5-10 | copy_claimed | 0.8130 | 0.7852 | 0.0278 |
| p5-10 | copy_anywhere | 0.9771 | 0.9718 | 0.0053 |
| p5-10 | validator_false_reject | 0.0400 | 0.0708 | 0.0308 |
| p5-10 | validator_catch | 0.9167 | 0.8182 | 0.0985 |
| p5-12 | usable_prices | 0.6763 | 0.6835 | 0.0072 |
| p5-12 | item_recall_kept | 0.7727 | 0.7769 | 0.0041 |
| p5-12 | item_recall | 0.7727 | 0.7769 | 0.0041 |
| p5-12 | price_accuracy | 1.0000 | 1.0000 | 0.0000 |
| p5-12 | copy_claimed | 0.8194 | 0.8241 | 0.0047 |
| p5-12 | copy_anywhere | 0.9933 | 0.9967 | 0.0034 |
| p5-12 | validator_false_reject | 0.1633 | 0.1600 | 0.0033 |
| p5-12 | validator_catch | 0.6216 | 0.5263 | 0.0953 |
| p5-14 | usable_prices | 0.8641 | 0.8883 | 0.0243 |
| p5-14 | item_recall_kept | 0.8980 | 0.9031 | 0.0051 |
| p5-14 | item_recall | 0.8980 | 0.9031 | 0.0051 |
| p5-14 | price_accuracy | 0.9679 | 0.9737 | 0.0058 |
| p5-14 | copy_claimed | 0.7078 | 0.7542 | 0.0464 |
| p5-14 | copy_anywhere | 0.9877 | 0.9873 | 0.0004 |
| p5-14 | validator_false_reject | 0.1084 | 0.0842 | 0.0242 |
| p5-14 | validator_catch | 0.5000 | 0.2667 | 0.2333 |
| p5-16 | usable_prices | 0.7947 | 0.7947 | 0.0000 |
| p5-16 | item_recall_kept | 0.8669 | 0.8741 | 0.0072 |
| p5-16 | item_recall | 0.8669 | 0.8741 | 0.0072 |
| p5-16 | price_accuracy | 0.9918 | 0.9919 | 0.0000 |
| p5-16 | copy_claimed | 0.6362 | 0.5863 | 0.0498 |
| p5-16 | copy_anywhere | 1.0000 | 0.9920 | 0.0080 |
| p5-16 | validator_false_reject | 0.2136 | 0.2179 | 0.0044 |
| p5-16 | validator_catch | 0.4315 | 0.3699 | 0.0616 |
| pooled | usable_prices | 0.7682 | 0.7739 | 0.0057 |
| pooled | item_recall_kept | 0.8585 | 0.8638 | 0.0053 |
| pooled | item_recall | 0.8594 | 0.8643 | 0.0048 |
| pooled | price_accuracy | 0.9910 | 0.9917 | 0.0006 |
| pooled | copy_claimed | 0.7968 | 0.7991 | 0.0023 |
| pooled | copy_anywhere | 0.9895 | 0.9873 | 0.0022 |
| pooled | validator_false_reject | 0.1192 | 0.1145 | 0.0047 |
| pooled | validator_catch | 0.6444 | 0.5937 | 0.0507 |

screen-baseline-a: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-a/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-a/reports).

screen-baseline-b: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-b/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-b/reports).

screen-baseline-qkm: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/reports); [original-label paired differences](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-baseline-qkm/comparisons-original.json).

screen-q25-7b: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/reports); [original-label paired differences](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q25-7b/comparisons-original.json).

screen-q3-8b: [original-label per-page counts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/scores-original.json); [unaltered evaluate report transcripts](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/reports); [original-label paired differences](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen30/runs/screen-q3-8b/comparisons-original.json).

## Provisional NPU validation shortlist and owner decision

**No replacement clears every numerical check on its latest evaluated subset. Retain the baseline provisionally.** This does not prove that no model could improve the full cohort. Small-page inconclusive results are preserved as such; no point estimate alone establishes a winner.

NPU family/path evidence: [RKLLM releases](https://github.com/airockchip/rknn-llm/releases/tag/release-v1.3.1), [official RK3588 benchmark](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/benchmark.md), [SDK driver/quantization guide](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/doc/Rockchip_RKLLM_SDK_EN_1.3.1.pdf), and [matching header](https://github.com/airockchip/rknn-llm/blob/release-v1.3.1/rkllm-runtime/Linux/librkllm_api/include/rkllm.h). Qwen3.5-2B/4B have primary RK3588 W8A8 evidence and require an isolated>=1.3.0 runtime/toolkit path, documented rknpu>=0.9.8 and a matching ctypes wrapper. The installed1.2.3 wrapper is not ABI-compatible with a library-only1.3.x swap. Qwen3 family is supported from1.2.1 and the owner has measured4B/8B loading on1.2.3. Qwen2.5 family support is official; selected7B artifact conversion/load remains unverified. Qwen3.5-9B stays outside the shortlist absent checkpoint-specific RKLLM/RK3588 evidence; RK182X examples do not qualify.

For any owner-selected provisional candidate: pin official checkpoint, toolkit/runtime and W8A8 calibration; hash and load the converted artifact; rescore extraction quality; check rendered non-thinking prompt, no duplicated answer, schema failures/truncations without GPU GBNF, unchanged full context/output budget, validator+[5b] evidence, CPU+NPU contention, tokens/s and end-to-end cost on the frozen v8 prompt. Runtime changes remain isolated under the granted test scope; production upgrades require owner approval. GPU Q4 evidence establishes no W8A8 quality or NPU performance.

After the model choice, P5-18 resumes on that model’s answers using labels-v9: rescore, recompute RESOLVED_PRICE_CONFIDENCE/report thresholds, set the usable bar(proposal>=0.70), build C3, then draft the tuning record, Amendment20 and PR. No such downstream tuning is part of this screen.

## Limitations and draft ADR correction for owner review

These are intentionally small, selected tuning subsets, not random held-out draws. Nested/adaptive expansion is not independent confirmation. Two baseline replicates supply a gap, not a variance bound; page bootstrap intervals omit model-run randomness. Rows cluster within few pages and sets, so passing a bar can be fragile. The exact-copy denominator contains complete parsed selected raw rows only; truncation failures are separate. Heuristic taxonomy and automatically chosen examples are not manual adjudication. Unmatched rows may be real unlabelled items. GPU quantization/runtime, W8A8 and NPU schema/speed remain separate. Qwen3.5 sampling recommendations were deliberately replaced by identical greedy decoding. The full-cohort gold-FR blocker is model invariant and unchanged.

**Draft only; no ADR file changed.** Amendment15 item9’s blanket statement that a larger model is infeasible on the Pi should be replaced, subject to owner review: “A model change requires its own amendment. Larger models may be screened for isolated validation or label-free escalation, conditional on converted-artifact quality, full-context schema behavior, contention and measured end-to-end cost. GPU quality and reduced-subset screening do not authorize deployment or make the second extractor an acceptance authority.” The owner’s measured8B W8A8 load/decode result motivates this narrow correction; it does not establish any model’s quality superiority. Stop for owner review before adoption.

<!-- /MODEL_SCREEN_RESULTS -->

## Reviewer notes on the completed screen (written after all automated runs)

Hand-written after inspecting scores, raw envelopes and raw → final rows. It does not
alter any generated table above.

### Outcome

**Provisional recommendation: retain Qwen3-4B-Instruct-2507 Q4_0. The NPU validation
shortlist is empty.** No configuration, standalone or routed, clears the frozen criterion
on its latest subset. Stage 2 opened because no ≤4B configuration cleared it. Sample:
the shared 15-page screen (82 input chunks, all seven sets), with the nested 30-page set
(202 chunks) for qkm, Qwen3-8B and Qwen2.5-7B. These are selected tuning pages, not a
held-out or full-cohort result.

| Configuration (labels-v9) | Pages | Raw recall | Kept recall | Usable | Accuracy | Accepted unmatched | Wrong price accepted | Outcome |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| baseline-a / baseline-b | 15 | 0.886 / 0.890 | 0.885 / 0.890 | 0.794 / 0.811 | 0.986 / 0.988 | 55 / 67 | 11 / 10 | reference |
| Qwen3.5-2B Q4_K_M | 15 | 0.641 | 0.606 | 0.446 | 0.971 | 158 | 13 | screened out at 15 |
| Qwen3.5-4B Q4_K_M | 15 | 0.811 | 0.810 | 0.732 | 0.989 | 94 | 8 | screened out at 15 |
| baseline-a / baseline-b | 30 | 0.864 / 0.869 | 0.863 / 0.868 | 0.772 / 0.778 | 0.991 / 0.992 | 151 / 180 | 15 / 14 | reference |
| Qwen3-4B-2507 Q4_K_M | 30 | 0.880 | 0.880 | 0.773 | 0.991 | 208 | 15 | fails: safety gates; gain inconclusive |
| Qwen3-8B Q4_K_M | 30 | 0.902 | 0.870 | 0.809 | 0.988 | 225 | 22 | fails: safety gates; gain inconclusive |
| Qwen2.5-7B-Instruct Q4_K_M | 30 | 0.812 | 0.794 | 0.742 | 0.986 | 179 | 23 | fails: raw-recall bar and safety gates |

Qwen3-8B's usable-price lead (+0.037 against A, +0.032 against B) exceeds the A/B gap
(0.006), but both paired 95% intervals include zero ([−0.011, 0.090] and
[−0.020, 0.086]) and the gain appears on only 4 of 7 sets. It also accepts more unmatched
and wrong-price rows. Its result stays **inconclusive**, not a win.

### Realized router policies against the criterion

The frozen criterion was applied to each label-free router with copy_anywhere and the
≤0.30 routed-share gate (`decision-<policy>-v9.json` under `screen30/runs/<tag>/`).
The baseline-coverage<0.70 rule routes 13/30 pages (0.433) whichever candidate is
used, so every realized policy fails the share gate before quality is considered.

| Candidate | Policy | Failed gates | Gain |
|---|---|---|---|
| Qwen3-8B | unconditional substitution | price-accuracy non-inferiority, previously passing sets, accepted unmatched, wrong price accepted, real-output FR, routed share | inconclusive |
| Qwen3-8B | keep more accepted | same six | inconclusive |
| Qwen2.5-7B | unconditional substitution | raw recall, price-accuracy non-inferiority, previously passing sets, wrong price accepted, copy, real-output FR, routed share | inconclusive |
| Qwen2.5-7B | keep more accepted | price-accuracy non-inferiority, accepted unmatched, wrong price accepted, copy, real-output FR, routed share | inconclusive |

The labelled oracle (Qwen3-8B: usable 0.841 on 20/30 routed pages) is a ceiling only
and is never recommendable.

Pi cost context: since the kernel 6.1.99 / rknpu 0.9.8 upgrade, Qwen3-8B W8A8 loads
and runs on the Pi NPU. The owner's Pi bench measured decode at 4B ~3.0 vs 8B ~1.8 tok/s
and prefill at ~34 vs ~20 tok/s (about 1.7× slower per token). Combined with this screen's
GPU token counts (on the 30-page set, ~3,700 prompt tokens per page for both;
Qwen3-8B generates 20% more, 86,135 vs 72,068 tokens in total, partly from repeated
rows), the **estimated** Pi time per page is about 2× a 4B: roughly 30 vs 15 minutes.
This is an estimate, not a Pi measurement of the frozen v8 prompt. The router table's
decode-only proxy hours leave out prefill. 8B is feasible on the Pi; whether its quality
justifies about 2× extraction time remains unanswered by this screen.

### Inspected mechanisms (raw → final)

- **Qwen3.5-4B:** drops whole sections while still emitting complete JSON. On
  spike/6a788f7d3b50 chunk 0 it omits the 11-item soup section (blocks b0040–b0050);
  every chunk finishes `stop`. Zero truncation, schema failure or generated thinking on
  the 15 pages. It regresses on every fixed difficult slice, e.g. price-before-name
  −0.102 [−0.161, −0.018].
- **Qwen3-8B:** highest raw recall. On spike/630ef18b78a3 it repeats each dish on 2–3
  adjacent description blocks (88 raw rows against baseline A's 66), inflating unmatched
  and wrong-price accepts. On p5-5/f649c257352d it fills the variant field that the
  baseline leaves empty, and the validator rejects 38 rows (baseline: 0). 3.4% of
  30-page chunks hit the output cap; no generated thinking.
- **Qwen2.5-7B:** low recall. Copy failures are mostly rewrites: recasing (MONTREAL
  FRIES → "Montreal Fries"), sizes folded into names, merged alternatives. 2.9% of
  30-page chunks hit the output cap.
- **Qwen3-4B-2507 Q4_K_M:** the same model as the baseline at a different quant; kept
  recall rises at 30 pages but accepted-unmatched (208 against 151/180), copy and catch
  worsen.

### Harness fit: why the result does not show the larger models are worse

Prompt v2.4, repairs/validator v8 and [5b] were tuned on baseline outputs from these
same seven sets, so candidates are scored by a harness fitted to another model. A
diagnostic tally (no inference; unmodified judge; `screen30/harness-fit.json`, script
`harness_fit.py`) of decisions on rows that are correct against labels-v9 (30 pages):

| Correct rows | baseline-a | baseline-b | Qwen3-8B | Qwen2.5-7B |
|---|---:|---:|---:|---:|
| downgraded `price_not_grounded` | 96 | 108 | 146 | 141 |
| rejected `duplicate_row` | 106 | 84 | 80 | 146 |
| downgraded `no_price_extracted` | 190 | 180 | 45 | 50 |

Qwen3-8B leads by +0.033–0.038 raw recall before repairs and the validator, but by only
+0.001–0.007 kept recall after them. The extra `price_not_grounded` downgrades cluster
on layouts where the name block and the price block differ (p5-12/29612ad9e3eb: 45
against 26). Not all loss is harness fit: Qwen3-8B also has 117 `implausible_amount`
rejections of wrong or unmatched rows (baselines: 4 each), which the validator rightly
catches. So the screen answers "which model is the best drop-in replacement for today's
tuned pipeline" (the baseline), not "which model is intrinsically best". A
harness-independent comparison and harness generalization are proposed as follow-up
P5-20 (scratch spec `var/menu-eval/model-screen/NEXT-SESSION-P5-20.md`); they are not
part of this screen.

### Execution notes and deviations

- **GPU fault:** at 18:52 on 2026-10-15 the llama-server running Qwen3.5-4B aborted with
  `CUDA error: unspecified launch failure` (kernel Xid 62 + 45, GPU at 89 °C under thermal
  slowdown). This was an infrastructure fault, not a model result. After a reboot the
  run resumed. Completed page files were kept and the remaining 11 pages were extracted;
  the score covers all 15 pages.
- **Thermal guard (infrastructure only):** from Stage 2 onward, a guard froze the
  llama container (`docker pause`) when the GPU got hot and resumed it after cooling.
  Freezing does not change greedy outputs; the 1800 s request timeout was never reached
  and no request failed. Thresholds started at pause ≥86 °C / resume ≤72 °C (five pauses
  during Qwen3-8B). The owner changed them to 93/78 at 00:52 UTC on 2026-10-16 and moved
  the laptop to an airflow stand at 00:56 UTC. **Zero pauses after that point** through
  the end of the screen. Log: `logs/thermal-guard.log`.
- **Qwen2.5-7B source (decided before any Stage 2 score):** unsloth publishes no
  Qwen2.5-7B-Instruct GGUF, so the pre-planned path would have failed. Used the checkpoint
  author's two-shard GGUF `Qwen/Qwen2.5-7B-Instruct-GGUF@bb5d59e06d9551d752d08b292a50eb208b07ab1f`,
  shards SHA256 `dfce12e3862a5283ccfb88221b48480e58745165de856439950d0f22590580db` and
  `539cf93f78e887edea1c04e2d7d8cdaca9d01dae9c9025bcb8accbe29df3d72a`. Qwen3-8B:
  `unsloth/Qwen3-8B-GGUF@a6adef130ffb23ddaf1a62fec9dced968c9bc482`, SHA256
  `120307ba529eb2439d6c430d94104dabd578497bc7bfe7e322b5d9933b449bd4`. Both fit fully on
  the GPU at the frozen context (Qwen3-8B: 37/37 layers, 6851 MiB used).
- No pipeline code, `config/models.yaml`, labels, held-out data, Pi, infra or deployment
  was touched. Scratch helper changes were limited to split-GGUF identity and quant
  labelling (control.py) and printing additional shard hashes (render_results.py).

## Manual baseline source inspection

# Baseline15 source inspection before candidate scoring

Agent source review for the owner; not owner adjudication. I inspected **only `screen-baseline-a`** attribution, segmented input, selected raw continuations and repaired/final verdicts. No candidate outputs or scores were read. This covers examples from all seven selected sets: spike has three pages; the other sets have two each. Counts use owner-confirmed labels-v9 and the unchanged `b4b0e2e` pipeline.

The attribution supports a real model-reading opportunity, particularly omitted items and descriptions substituted for titles. Its automatic class names need care: a missing additional amount is not necessarily a misread amount; a grounding failure is not necessarily invented text; and some structural subclasses do not describe the nearest printed geometry precisely.

## Counts and ceilings checked

“Missed prices” below means gold prices of an item with no matching final row. The second number retains only amounts at which an ideal gold representation passes the frozen validator. These are optimistic ceilings, not forecast gains. “Wrong amount” is the frozen loss bucket: no extracted row has this particular gold amount, even when another legitimate amount was extracted.

| Set | Pages | Gold items / price rows | Missed prices / perfect-pass subset | Wrong-amount losses / perfect-pass subset | Accepted unmatched | Matched wrong price accepted | Gold-row FR count | Page-verbatim copy | Claimed-block anchor |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| spike | 3 | 335 / 299 | 28 / 28 | 0 / 0 | 10 | 4 | 1 | 345/350 | 322/350 |
| P5-5 | 2 | 155 / 23 | 0 / 0 | 0 / 0 | 8 | 2 | 4 | 246/247 | 227/247 |
| P5-8 | 2 | 97 / 114 | 14 / 12 | 3 / 3 | 12 | 1 | 3 | 187/190 | 137/190 |
| P5-10 | 2 | 99 / 123 | 32 / 23 | 9 / 0 | 2 | 0 | 36 | 122/128 | 97/128 |
| P5-12 | 2 | 109 / 133 | 22 / 12 | 13 / 2 | 7 | 0 | 29 | 147/148 | 122/148 |
| P5-14 | 2 | 88 / 106 | 10 / 10 | 0 / 0 | 0 | 3 | 10 | 112/112 | 70/112 |
| P5-16 | 2 | 141 / 166 | 17 / 14 | 5 / 0 | 16 | 1 | 35 | 205/205 | 116/205 |
| **Pooled** | **15** | **1,024 / 964** | **123 / 99** | **30 / 5** | **55** | **11** | **118** | **1,364/1,380** | **1,091/1,380** |

Usable prices are 765/964. Recovering the 123 missed-price entries has an absolute ceiling of +0.12759; only 99 currently pass as ideal gold rows, corresponding to +0.10270. The 30 wrong-amount losses have an absolute ceiling of +0.03112, but only five ideal representations pass, +0.00519. Three unpriced losses all pass as ideal rows, +0.00311. These exclusive losses differ from overlapping counts of wrong extracted rows.

There are five repeated gold `(item, amount)` pairs. The frozen numerator deduplicates them while the denominator counts labelled variants. Their model-gain ceiling is **zero**; no label or scoring change is proposed.

## Concrete raw → final cases

| Error/diagnostic | Inspected source and baseline behavior | Assessment |
|---|---|---|
| Missed title and description used as name | spike `0824dfcdd900`: `b0025 MAGURO*`, `b0026 $8 / $15`, `b0027 bigeye tuna`. No final row matches MAGURO. Raw instead names `bigeye tuna`, price8, variant`$8`, claimed block`b0026`; repair drops the variant and the final row is accepted using name evidence`b0027` and price`b0026`. | Clear model-reading/title-selection problem that the frozen validator does not catch as a bad item name. The accepted unmatched row and missed gold item are overlapping manifestations; do not add their counts. |
| Omitted sold modifier | P5-8 `a8684c49dfa1`: `b0043 Add Bacon`, `b0044 $1.69`. No matching raw/final row is present in the inspected evidence. | A straightforward omission under the owner-confirmed sold-modifier labels. It is not a new modifier-policy proposal. |
| Accepted descriptive text | P5-5 `66a3d8e752b9`: `PASTRAMI HASH*`, its ingredient description, `$11.50`, then `$12` before `THE LONGHORN*`. Raw names the complete ingredient description at12; the final row is accepted and matches no label. | Clear description-as-name plus suspicious price association. The automatic description proxy misses this uppercase-starting example, so its32-row count is incomplete, not an adjudicated census. |
| Wrong association, caught | spike `630ef18b78a3`: FISH & CHIPS prints18;16 begins the following Beyond Meat Burger placement. Raw emits both FISH & CHIPS18 and16; final accepts18 and downgrades16 as`price_not_grounded`. P5-8 `ddb652ccea54` similarly emits Plain Cheese15.99/17.99/19.99 and additional-topping3.00/3.25/3.50; the latter are downgraded. | Source-supported association errors. Correct outputs already exist, so removing these extra wrong rows does not automatically recover a gold price. |
| Wrong association accepted; correct row blocked in the real extraction | P5-5 `66a3d8e752b9`: flavored-cream-cheese bagel prints4.00, followed by20 belonging to NEW YORK DOZEN. Raw emits bagel4.00 and bagel20. Final downgrades4.00 as`price_bound_to_other_item` and accepts20. The ideal bagel4.00 gold row passes. | A model-output interaction with frozen binding rules, appropriately separated as model-representation/validator loss. A better extraction could improve both precision and usability without changing validator code. |
| “Nowhere nearby” amount | spike `630ef18b78a3`: raw invents a local5.50 association for School House Old Fashioned at`b0117`; final downgrades it. The5.50 amount is printed later at`b0138`/`b0140` in Bottles and Cans. | Not a made-up numeric value or proof of whole-page absence. It is absent in the fixed±12-block window and belongs to another section. |
| Wrong-amount loss that is an omitted second price | P5-12 `1bc9710cd463`: the five-name side list at`b0097` has Single Serving3.49 and Pint5.99 at`b0098–101`. Raw emits the whole list at3.49 and final accepts it. The5.99 gold price is absent. | The frozen `wrong_amount` label here means missing a legitimate additional amount, not an incorrect3.49 transcription. Name splitting/matching and shared-price structure also affect the result. |
| Label/repair convention counted as wrong price | P5-14 `e845388448b9`: raw Berry Lemonade3.25 becomes final Berry Lemonade3.25 plus a Refill1.50 variant row. Source explicitly prints `Refill $1.50`; labels model Refill as its own item. | The variant row is accepted but counted as a matched wrong Berry Lemonade price. This is a real frozen safety-counter event, not evidence that1.50 was misread or invented. Repairs and item/variant convention contribute. |
| Section heading accepted as item | P5-16 `5d960df16b84`: `By the Pound` precedes42/lb and Brisket. Raw names By the Pound42 at the price block; final accepts it, unmatched. | A clear section-heading/name-selection problem in this inspected placement. This one is not a real labelled dish; that conclusion does not generalize to every unmatched row. |

## Copy fidelity and hallucination proxies

The amended reduced-screen primary copy gate is **page-verbatim copy**, with claimed-block fidelity retained as an anchor diagnostic. The original218-page claimed-block gate remains historical.

Of289 claimed-block failures, **273 names occur verbatim somewhere else on the same page**, and16 fail page-verbatim copy. Thus94.5% of claimed-block failures are relocation-only under these string checks. P5-14 Organic Eggs is raw-claimed at`b0053 $8.00`, while the name appears exactly at`b0051`; the final row is accepted. All112 raw names on that set occur verbatim somewhere, despite42 claimed-block failures. P5-16 likewise has205/205 page copies but89 claimed-block failures.

The16 page-copy failures are heterogeneous. Inspected examples include three case-only `WHOLE PIZZA`→`Whole Pizza` rows, concatenated multi-block descriptions, a bilingual name with omitted intervening description, and one empty raw name under Corona NA. Genuine transcription changes include `芥蘭鸡片`→`芤蘭鸡片` in Chicken w/ Broccoli (spike `6a788f7d3b50`) and `2 quails and one side`→`2 quills and one side` (P5-12 `29612ad9e3eb`); both fail final name grounding.

The10 raw token-ungrounded/final-name-not-grounded diagnostics are **not ten established hallucinated items**. P5-10 `3e035f21ac55` concatenates “eggs scrambled with” / “sausage, cheddar jack” / “& pico de gallo14” into a descriptive name; every phrase is printed, but no single block grounds the combined name. Conversely, the Dallas Wings10.69 accepted-unmatched example on P5-8 is printed above separately labelled9-piece/12-piece names. That is a granularity/matching case, not fabricated text. The55 accepted-unmatched rows require this source distinction; their count remains the unchanged safety metric.

## Structural classes and output completeness

Gold-row FR is118/964=0.12241 on these selected pages: `p_other64`, `v_other22`, `own_line10`, `header8`, `price_belongs_to_other_variant8`, `name_not_grounded3`, `unread2`, `name_number1`. This is a selected-subset validator diagnostic, not the full-cohort FR estimate, and cannot improve through a model change.

- **Own-line label:** P5-12 Sodas/Tea has “Any Size” on its own block before2.89; the perfect Sodas2.89/Any Size row is downgraded. P5-14 Green salad3.50/Small also fails as a perfect labelled row, while the raw Small variant is removed by repairs and the final unlabelled3.50 row is accepted. This demonstrates why gold-row FR and real usable output are different measurements.
- **Header proxy ambiguity:** P5-10 Buffalo Chicken16/7-inch is classified`header` because an earlier7-inch line exists. Its own7-inch line is actually below the name at`b0129`, followed by16 at`b0130`. Do not interpret all eight header counts as confirmed split-column-header cases.
- **Name-number proxy ambiguity:** the sole case is “add fried egg2 or avocado3.” The gold name “add fried egg” contains no number; P18's broad condition assigns`name_number` because the target2 is not recognized among its block's parsed prices. This is a parser/add-on geometry proxy, not a confirmed number inside the name.
- **Residual/variant structure:** P5-16 Small Chile con Queso has base7.46 and “With Taco Meat11.81” nearby; the ideal11.81 variant is downgraded while the base row is accepted. Sausage26/lb is downgraded as another-variant binding despite repeated6/link and26/lb lines. These support structural complexity, but`p_other` remains a residual class rather than one physical format.
- **Truncation/schema:** P5-8 `ddb652ccea54`, chunk0, ends with an incomplete Mediterranean Pizza name at1,744 generated tokens. `parse_output` recovers56 complete rows. This single event is both the one selected truncation and one pre-repair schema failure among82 chunks; it must not be counted as two independent failures. The failed JSON is truncation-associated, not evidence of an additional unconstrained-schema defect.

Full source/raw/final records remain in [baseline-attribution.json](/home/fortune/CodeProjects/First-Helios/.claude/worktrees/p5-19-model-screen/var/menu-eval/model-screen/screen15/baseline-attribution.json) and the `screen-baseline-a` extraction files. These inspected cases support the high-level split and its caveats; they are examples, not a row-by-row adjudication of all losses or unmatched outputs. No pipeline, labels, matching rules or thresholds were changed during this review.

## Archive (P5-22, 2026-10-19)

The gitignored scratch `var/menu-eval/model-screen/` is archived in `var/archive/2026-10-p5-19-21/` (main checkout, gitignored):

- manifest `p5-19-model-screen.manifest.json`, sha256 `d2023bca9fbf3de4c01bd695bb749d4192e8722d97f17ca22d908f4409db57ff` (path, size and sha256 of every
  archived file; excluded model weights and vendor binaries with their size, sha256 and
  publisher pin; excluded environments and caches with file counts);
- tarball `p5-19-model-screen.tar.zst`, sha256 `8f424c663e127638e35557c2e4d0c3eaed6faa53f91e9ea29346dfe8c002ef18`.

Model GGUFs, HF checkpoints, Python environments, caches and RKLLM vendor binaries are not
in the tarball; `SHA256SUMS` in the same directory lists both files and the archiving
scripts.

The absolute `/home/…/p5-19-model-screen/var/menu-eval/model-screen/…` links above point
at the worktree; once it is removed, the same files are at `model-screen/…` in the
tarball.
