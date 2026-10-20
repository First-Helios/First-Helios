# P5-21 closeout — primary model, fallback findings and Pi cost

**Status:** complete; findings and Pi performance recorded. No implementation or PR.
The owner ended the experiment and requested this write-up and a performance test
instead of spending a held-out draw.

> **Owner direction (2026-10-19):** the experiments are done. The NPU is not used: its
> W8A8 probe was slower (6.5 vs 10.4 pages/h) and lower on raw usable prices (0.761 vs
> 0.844, 3 pages; [P5-20 §6](./2026-10-16-p5-20-bracket-screen.md)), so Qwen3-4B-2507
> Q4_0 on the Pi CPU stays the extractor. Qwen3.5-9B on the Pi CPU is the only
> fallback candidate, pending an ADR-0013 amendment. No more prompt search or model
> screening.

## Decision and scope

The intended arrangement is **Qwen3-4B-Instruct-2507 Q4_0 as the common primary
model**, with **Qwen3.5-9B Q4_K_M only as a fallback**. Both use greedy decoding,
prompt v2.4 and the same universal H4 interpretation. This records the direction;
it does not adopt a routing policy or clear a pipeline for production.

No fresh §8 pages were drawn, labeled or scored. No production runtime, model
registry, schema, ADR, deployment or Pi service was changed. No PR is requested.
The proposed routing policies were not executed; the owner closed the experiment
before their first score. They remain scratch drafts, not validated behavior.

## What the experiment found

The [prompt experiment](./2026-10-16-p5-21-per-model-prompts.md) tested 32 variants
on FAST and completed DEV for 19. **None met the pre-registered promotion rule.**
The final configurations stayed at their P5-20 prompts. More prompt iterations
are not supported by this experiment.

The universal **H4 description-row repair** passed all registered development
checks: +141 usable-price pairs pooled over 17 configurations, gains for all 17,
no regression beyond the development bands, unchanged gold-row false rejects and
corruption catch, and zero added invariance flips. Recovery reproduced every
saved DEV/gold counter and the entire invariance artifact. All nine grouped
model hold-outs pass too (an additional audit, not a new fit).

The [TEST3 record](./2026-10-17-p5-21-harness-h-test3.md) is a fresh check within
the tuning corpus: 45 pages from six sets, all five runs complete before scoring.
It is **not** an ADR-0013 §8 held-out evaluation.

| Configuration | H4 usable prices | H4 accepted price accuracy | Accepted unmatched / output row | Stored-data result vs both baselines |
|---|---:|---:|---:|---|
| Baseline Q4_0 A | 0.7838 | 0.9845 | 0.0563 | Reference |
| Baseline Q4_0 B | 0.7849 | 0.9884 | 0.0597 | Reference |
| Gemma-4-E4B g-v24 | 0.8256 | 0.9889 | 0.0652 | Fails unmatched guard |
| Qwen3.5-9B g-v24 | 0.8201 | 0.9880 | 0.0529 | Beats both |
| Qwen3-4B-2507 Q4_K_M s-n1 | 0.7765 | 0.9865 | 0.0788 | Does not establish parity |

The 9B candidate produces **131–138 more correct prices out of 3,664** than the
production v8 baseline replicates: +3.58/+3.77 percentage points, with paired 95%
intervals [+0.80,+6.41] / [+0.75,+7.02] points. Five of six sets improve; all
pre-registered stored-data risk bands pass against both replicates.

The original raw-output brackets remain **inconclusive**. In particular, the
9B's raw price accuracy is 0.9260 versus baseline 0.9396/0.9404. Its accepted-row
accuracy is better after filtering, so raw and stored-data claims must stay
separate. H4 itself adds just two correct prices to the 9B TEST3 output; most of
the gain comes from the model. H4 adds 41 for Gemma, but Gemma still fails its
unmatched-row guard.

These results support **9B as the stronger fallback candidate**, while retaining
the smaller reference as the normal extractor. They do not establish that any
label-free trigger can find the pages where fallback helps.

## Pi performance test

Fresh paired run on the Orange Pi CPU, three pages / nine chunks per model.
The model files, prompt and input-page hashes are saved in `pi-closeout/preflight.json`.
No quality tuning or routing selection was performed.

| Model | Inference time, 3 pages | Pages/hour, inference + H4 | Generated tokens/s, aggregate | Peak Docker memory | Highest SoC sensor | Startup to ready |
|---|---:|---:|---:|---:|---:|---:|
| 4B primary Q4_0 | 17.15 min | 10.49 | 3.84 | 3.20 GiB | 72.1 °C | 6.24 s |
| 9B fallback Q4_K_M | 32.06 min | 5.61 | 2.32 | 5.65 GiB | 88.6 °C | 26.18 s |

Per-page LLM wall time (both models see exactly the same page/chunk order):

| Tuning page | 4B | 9B additional pass | 9B / 4B |
|---|---:|---:|---:|
| p5-14/f204b5c8375f | 217.7 s | 476.0 s | 2.19× |
| p5-5/66a3d8e752b9 | 227.4 s | 394.7 s | 1.74× |
| p5-16/5d960df16b84 | 583.8 s | 1052.7 s | 1.80× |

H4 interpretation was timed on the Pi itself (segmentation, output parsing,
repairs, validator and [5b]); every Pi verdict hash matched the laptop for
that same raw output. Median across 20 repetitions per page:

| Model outputs | Sum of page-median H4 times, 3 pages | Largest first-call H4 time |
|---|---:|---:|
| 4B | 0.3174 s | 0.1815 s |
| 9B | 0.3288 s | 0.1868 s |

On this sample, an additional 9B pass costs **1.87× the primary pass**.
The following projections include a primary pass on every page and an extra
9B pass on the stated fraction, even if its answer is later discarded:

| Fallback share | Projected pages/hour | Extra inference work | Projected hours / 100 pages |
|---|---:|---:|---:|
| 0% | 10.49 | +0.0% | 9.53 |
| 5% | 9.60 | +9.3% | 10.42 |
| 10% | 8.84 | +18.7% | 11.31 |
| 20% | 7.64 | +37.4% | 13.09 |
| 30% | 6.72 | +56.1% | 14.87 |
| 100% | 3.66 | +186.9% | 27.34 |

These are **same-page-mix projections, not measured routing throughput**.
A hard-page-biased fallback policy can cost more. Model reloads, routing and
database writes are excluded. Startup was measured after model checksum
verification warmed the filesystem cache; it is not cold-boot loading.
Memory is the maximum sampled Docker working usage at about 10-second intervals,
not a guaranteed instantaneous peak. Models ran separately, so simultaneous
residency and CPU/NPU contention were not measured.

The benchmark used A76 cores 4–7, four threads, two slots, the pinned ARM
llama.cpp image `6257697a…`, greedy prompt v2.4 and GBNF, 12,288 total context
(6,144 per slot), q8_0 KV and flash attention. This matches the earlier Pi
probe; it differs from laptop GPU f16/no-flash settings. No equality of
model answers across runtimes is assumed. This is a small tuning-page cost
probe, not a representative throughput study or §8 quality acceptance.

Both models were checksum-verified and mounted read-only. Only isolated
benchmark containers were created, and all were removed. The deployed API
and PostgreSQL container IDs were unchanged and remained healthy. No NPU
conversion or production service/configuration change was performed.

## What remains unproven

- A production fallback trigger, its routed share, and quality on the routed pages.
  The prior screen's coverage <0.70 rule routed 43% of pages, over its 30% cap.
- §8 acceptance. H4's 68-page development gold-row FR is 0.148, above the 0.12
  pass bar and far from Amendment 19's roughly 0.05 draw-readiness target.
- Quality of the complete primary/fallback configuration on the Pi runtime.
  Laptop Q4 quality, Pi CPU speed and an NPU probe are different measurements.

If work resumes, freeze a label-free fallback policy and cost budget on tuning
data, address §8 readiness, and only then spend a fresh draw. Keep the same H4
grounding for both models. No model-specific acceptance shortcut is justified.

## Artifacts and closeout

The complete prompt, H4 and TEST3 records remain linked above. Scratch artifacts,
hashes, logs and the handoff are in `var/menu-eval/prompt-opt/`; performance
artifacts are in its `pi-closeout/` subdirectory. The brief held-out preparation
under `var/menu-eval/p5-22-heldout/` was superseded without a draw or routing score.

Verification: scorer synthetic tests pass; clean tracked-code snapshot `make ci`
passed (668 tests passed, 726 skipped; no database acceptance). The experimental
worktree's copied frozen source tree causes duplicate modules in mypy. Fresh Pi measurements and cleanup passed; review file hygiene is checked at closeout.

Branch work ends with documentation only. No PR, merge, deployment, commit or
push is performed; the review files are retained uncommitted in this worktree.

## Archive (P5-22, 2026-10-19)

The gitignored scratch `var/menu-eval/prompt-opt/` (Pi run in `pi-closeout/`) and the
superseded `var/menu-eval/p5-22-heldout/` (with the unscored routing registration) are
archived in `var/archive/2026-10-p5-19-21/` (main checkout, gitignored):

- manifest `p5-21-prompt-opt.manifest.json`, sha256
  `ed06419d13bf6bcec656ab4d0c276c8112a99161f714be5bded6da14efeb6d97` (path, size and sha256 of every
  archived file; excluded model weights and vendor binaries with their size, sha256 and
  publisher pin; excluded environments and caches with file counts);
- tarball `p5-21-prompt-opt.tar.zst`, sha256 `e5ac73e73b16c43412894106e736df47e3a7f4c8c7bc5ed3500d9e4cf7ee3827`.

Model GGUFs, HF checkpoints, Python environments, caches and RKLLM vendor binaries are not
in the tarball; `SHA256SUMS` in the same directory lists both files and the archiving
scripts.
