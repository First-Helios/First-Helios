# P5-21 follow-up — universal description-row repair and TEST3

**Completed:** 2026-10-17T23:37:03+00:00 · **Status:** draft for owner review, committed unchanged in the P5-22 archive

> **Owner closeout direction (2026-10-18):** retain the 4B reference as primary;
> 9B is a fallback candidate. The experiment ends with no PR or held-out draw.
> See [closeout and Pi cost](./2026-10-18-p5-21-closeout-pi-cost.md). The
> standalone TEST3 findings below remain the historical experimental result.

Follows [P5-21 prompt optimisation](./2026-10-16-p5-21-per-model-prompts.md).

## Outcome

H4 passed the pre-registered development checks. TEST3 uses the same fixed prompts
and decoding as P5-20; H4 changes the universal harness using page evidence only.

**Recommended next step: take Qwen3.5-9B g-v24 plus the universal H4 repair to
owner review and an ADR-0013 §8 held-out evaluation. Stop this prompt search.**
Its stored usable-price rate is 0.8201 versus production baseline 0.7825/0.7844
(+138/+131 correct item/price pairs out of 3,664; paired 95% CIs exclude zero).
It passes the pre-registered unmatched, wrong-price-accepted and accuracy bands
against both replicates and improves on five of six sets. This establishes the
stored-data result on TEST3; it does not change the original raw-output verdict.

| Candidate | Stored-data rule, both sides H4 | H4 vs production v8 baseline |
|---|---|---|
| Gemma-4-E4B g-v24 | not established | not established |
| Qwen3.5-9B g-v24 | beats | beats |
| Qwen3-4B-2507 Q4_K_M s-n1 | not established | not established |

The original raw clear-winner rule remains separate:

- B4: inconclusive.
- B8: inconclusive.

## Protocol and data boundary

`var/menu-eval/prompt-opt/protocol-h.md` was recorded before the H scores and TEST3
output inspection. H1–H4 were the four allowed sets; H4 was carried before TEST3
scoring. No further harness or prompt tuning was done in the recovery session.

The earlier 100-row Gemma audit inspected DEV, VAL, TEST and TEST2. Those splits
therefore cannot serve as independent confirmation of the harness repair. TEST3
contains 45 previously unused tuning pages, across six sets (p5-5 had no pages left),
drawn with seed 20261018. Split SHA256:

`17e0965a2b985847dc60915fce978d40e87a680eef78b7c65febc79bdc39843d`

TEST3 is a fresh tuning-page check, not an ADR-0013 §8 held-out evaluation.

## H4 development acceptance

- DEV: 17 configurations, 15 pages each; pooled usable-price gain +141. Every
  configuration improves; accepted-unmatched falls for all 17.
- No regression beyond the DEV baseline band (price accuracy 0.0014376;
  accepted-unmatched 12 rows; wrong-price accepted 1 row).
- All 17 recorded leave-one-configuration-out folds pass. The original script calls
  these LOMO, but configurations sharing a model are separate folds.
  An additional audit holds all configurations/replicates/quants of each checkpoint
  together: all nine model groups pass too (`p0/h4-grouped-model-lomo-recheck.json`).
  This audit was added after TEST3 scoring; it did not retune or replace H4.
- Gold pool: 68 pages; false reject 623/4209 = 0.148016 and corruption catch
  0.991870, unchanged.
- Invariance: full H4 JSON equals frozen v8; 3,705 base accepts, zero added flips.
  Existing frozen-v8 flips remain; this is not a claim of complete invariance.
- Recovery reran all 255 DEV tag/pages and all gold-pool counters; every counter
  reproduced the saved H4 artifact. Fresh invariance also reproduced it exactly.

H4 drops a description row only when another row names its nearby short title.
It protects inline item prices and “Name – note” lines, and requires the title row
to claim a block at or above the description. The rule has no model/site branch.

## TEST3 pooled metrics

Usable = unique correct item/price pairs divided by gold prices. Accuracy = exact
prices divided by matched accepted priced rows. Unmatched/wrong-accepted rates use
each harness’s output-row denominator. Raw metrics are unchanged by H4.

| Configuration | Raw usable | Raw accuracy | Raw unmatched | v8 usable | H4 usable | H4 accuracy | H4 accepted-unmatched/row | H4 wrong-accepted/row |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Baseline Q4_0 A | 0.7928 | 0.9396 | 0.2294 | 0.7825 | 0.7838 | 0.9845 | 0.0563 | 0.0103 |
| Baseline Q4_0 B | 0.7904 | 0.9404 | 0.2344 | 0.7844 | 0.7849 | 0.9884 | 0.0597 | 0.0077 |
| Gemma-4-E4B g-v24 | 0.8442 | 0.9679 | 0.3019 | 0.8144 | 0.8256 | 0.9889 | 0.0652 | 0.0068 |
| Qwen3.5-9B g-v24 | 0.8510 | 0.9260 | 0.1683 | 0.8196 | 0.8201 | 0.9880 | 0.0529 | 0.0086 |
| Qwen3-4B-2507 Q4_K_M s-n1 | 0.7800 | 0.9385 | 0.2779 | 0.7762 | 0.7765 | 0.9865 | 0.0788 | 0.0084 |

## Stored-data rule

Paired whole-page bootstrap: 10,000 resamples, seed 20261018, pooled ratios.
S1 “as good” requires the 95% CI lower bound > −usable band; “beats” requires
lower > 0 and a positive difference on at least five of six sets. S2/S3 require
accepted-unmatched and wrong-price-accepted rates ≤ baseline + their bands;
S4 requires accuracy ≥ baseline − its band. Every condition must hold against
both baseline replicates. Bands are absolute A/B differences.

| Metric | H4 baseline band | Frozen v8 baseline band |
|---|---:|---:|
| usable_prices | 0.001092 | 0.001910 |
| accepted_unmatched_per_row | 0.003484 | 0.003610 |
| wrong_accepted_price_per_row | 0.002598 | 0.002773 |
| price_accuracy | 0.003841 | 0.004171 |

### Both sides through H4

The production comparison uses the frozen-v8 baseline pair’s bands;
the comparison with both sides through H4 uses the H4 pair’s bands.

| Candidate | Baseline | Usable Δ [95% CI] | Positive sets | S1 as good | S1 beats | S2 | S3 | S4 |
|---|---|---|---:|---|---|---|---|---|
| Gemma-4-E4B g-v24 | Baseline Q4_0 A | +0.0418 [+0.0051, +0.0778] | 5/6 | pass | pass | fail | pass | pass |
| Gemma-4-E4B g-v24 | Baseline Q4_0 B | +0.0407 [+0.0053, +0.0751] | 5/6 | pass | pass | fail | pass | pass |
| Qwen3.5-9B g-v24 | Baseline Q4_0 A | +0.0363 [+0.0078, +0.0670] | 5/6 | pass | pass | pass | pass | pass |
| Qwen3.5-9B g-v24 | Baseline Q4_0 B | +0.0352 [+0.0088, +0.0626] | 5/6 | pass | pass | pass | pass | pass |
| Qwen3-4B-2507 Q4_K_M s-n1 | Baseline Q4_0 A | -0.0074 [-0.0287, +0.0164] | 2/6 | fail | fail | fail | pass | pass |
| Qwen3-4B-2507 Q4_K_M s-n1 | Baseline Q4_0 B | -0.0085 [-0.0327, +0.0197] | 2/6 | fail | fail | fail | pass | pass |

### H4 candidate vs production v8 baseline

The production comparison uses the frozen-v8 baseline pair’s bands;
the comparison with both sides through H4 uses the H4 pair’s bands.

| Candidate | Baseline | Usable Δ [95% CI] | Positive sets | S1 as good | S1 beats | S2 | S3 | S4 |
|---|---|---|---:|---|---|---|---|---|
| Gemma-4-E4B g-v24 | Baseline Q4_0 A | +0.0431 [+0.0054, +0.0799] | 5/6 | pass | pass | fail | pass | pass |
| Gemma-4-E4B g-v24 | Baseline Q4_0 B | +0.0412 [+0.0052, +0.0763] | 5/6 | pass | pass | pass | pass | pass |
| Qwen3.5-9B g-v24 | Baseline Q4_0 A | +0.0377 [+0.0075, +0.0702] | 5/6 | pass | pass | pass | pass | pass |
| Qwen3.5-9B g-v24 | Baseline Q4_0 B | +0.0358 [+0.0080, +0.0641] | 5/6 | pass | pass | pass | pass | pass |
| Qwen3-4B-2507 Q4_K_M s-n1 | Baseline Q4_0 A | -0.0060 [-0.0294, +0.0196] | 3/6 | fail | fail | fail | pass | pass |
| Qwen3-4B-2507 Q4_K_M s-n1 | Baseline Q4_0 B | -0.0079 [-0.0331, +0.0209] | 2/6 | fail | fail | fail | pass | pass |

## Original raw clear-winner rule

C1 = raw usable beats each other bracket finalist and both baselines (CI lower
> 0, positive on ≥5 sets); C2 = raw accuracy/unmatched within baseline bands;
C3 = schema/truncation ≤ baseline mean +0.02; C4 = carried-H4 pipeline usable
noninferior (CI lower > −band).

| Bracket | Candidate | C1 | C2 | C3 | C4 | Winner |
|---|---|---|---|---|---|---|
| B4 | Gemma-4-E4B g-v24 | fail | fail | pass | pass | no |
| B4 | Qwen3-4B-2507 Q4_K_M s-n1 | fail | fail | pass | fail | no |
| B8 | Qwen3.5-9B g-v24 | pass | fail | pass | pass | no |

Raw usable differences against each baseline:

| Candidate | Baseline | Raw usable Δ [95% CI] | Positive sets |
|---|---|---|---:|
| Gemma-4-E4B g-v24 | Baseline Q4_0 A | +0.0513 [+0.0178, +0.0884] | 5/6 |
| Gemma-4-E4B g-v24 | Baseline Q4_0 B | +0.0538 [+0.0198, +0.0882] | 4/6 |
| Qwen3-4B-2507 Q4_K_M s-n1 | Baseline Q4_0 A | -0.0128 [-0.0335, +0.0090] | 0/6 |
| Qwen3-4B-2507 Q4_K_M s-n1 | Baseline Q4_0 B | -0.0104 [-0.0326, +0.0157] | 1/6 |
| Qwen3.5-9B g-v24 | Baseline Q4_0 A | +0.0581 [+0.0313, +0.0896] | 6/6 |
| Qwen3.5-9B g-v24 | Baseline Q4_0 B | +0.0606 [+0.0324, +0.0930] | 6/6 |

Sensitivity with original frozen-v8 secondary C4:

- B4: inconclusive.
- B8: inconclusive.

## Recovery incidents, verification and resources

The original TEST3 wrapper printed success despite a failed Python job.
The 9B stopped at 20/45 pages on a llama.cpp grammar-state HTTP 500; Q4_K_M
never started. The failure log was preserved. Saved complete pages were kept,
and the missing pages were resumed with identical runtime/quality settings.
An initial recovery attempt failed to load both models while CS2 occupied GPU
memory. After the owner closed it, the authorized GPU work resumed. No partial
TEST3 quality scores were computed.

The scratch wrapper now propagates errors, and the runner rejects incomplete
jobs even when startup returns an exclusion record. The scorer refuses any
missing/misaligned page before scoring. All input output-files have SHA256
hashes in `test3-h4-verdict.json`; scoring code hashes were saved before scoring.

Nine synthetic scorer tests pass. All 225 saved-output hashes and every
score’s pooled counters were checked after scoring. The in-worktree `make ci` reached a mypy
duplicate-module error caused by the gitignored copied `frozen/` tree; checks
were also run on an isolated snapshot of unchanged tracked code. See
`var/menu-eval/prompt-opt/verification-test3.md` for details. The clean snapshot
passed `make ci`: 668 tests passed, 726 skipped; mypy checked 176 source files.
Database tests skipped, so this is not database acceptance.

Total P5-21 queue wall time: **32,178 s = 8.94 h**, including TEST3 **8,494 s =
2.36 h** and this recovery’s successful inference queue **3,108 s = 0.86 h**.
These include loading/failed startup time and are not speed evidence.
The earlier 8-hour prompt-search budget was exceeded during the subsequent
harness follow-up under the later owner instruction recorded in protocol-h
to reach a decisive conclusion. Thermal pauses: **0**. Containers and guard
stopped cleanly after the final queue.

No tracked runtime code, labels, model registry, ADR files, production data,
deployment or Pi was changed. No commits or pushes.

## Limitations and next decision

The formal stored-data and original raw verdicts above are distinct. A better
point estimate does not override a failing guard or inconclusive interval.
The 9B’s raw price accuracy is 0.9260 versus baseline 0.9396/0.9404, so it
fails original C2 even though accepted-row accuracy is 0.9880. The filtering
step matters to this recommendation. S2–S4 use the pre-registered point-estimate
bands; their bootstrap intervals are saved but are not additional pass criteria.

Gemma has the highest stored usable point estimate (0.8256), but its accepted
unmatched rate (0.0652) exceeds both H4 baseline rates beyond their band.
Q4_K_M is lower on usable prices and fails unmatched as well. Neither qualifies
for replacement under the stored-data rule. No further prompt or harness variants
are justified within this completed experiment.

Most of the 9B’s gain comes from the model: H4 itself adds only two correct
prices to its frozen-v8 TEST3 output (3,003 → 3,005). H4 adds 41 for Gemma,
but that does not remove Gemma’s remaining unmatched-row problem.

The check uses tuning pages and laptop Q4 GGUF outputs, not Pi W8A8 quality
or speed. Before shipping any selected model/harness combination, obtain owner
review of the existing ADR proposal and run its required §8 held-out evaluation.
H4 remains a scratch prototype pending that review and production implementation.

## Archive (P5-22, 2026-10-19)

The gitignored scratch `var/menu-eval/prompt-opt/` (with H4 in `hh/`) is archived in
`var/archive/2026-10-p5-19-21/` (main checkout, gitignored):

- manifest `p5-21-prompt-opt.manifest.json`, sha256 `ed06419d13bf6bcec656ab4d0c276c8112a99161f714be5bded6da14efeb6d97` (path, size and sha256 of every
  archived file; excluded model weights and vendor binaries with their size, sha256 and
  publisher pin; excluded environments and caches with file counts);
- tarball `p5-21-prompt-opt.tar.zst`, sha256 `e5ac73e73b16c43412894106e736df47e3a7f4c8c7bc5ed3500d9e4cf7ee3827`.

Model GGUFs, HF checkpoints, Python environments, caches and RKLLM vendor binaries are not
in the tarball; `SHA256SUMS` in the same directory lists both files and the archiving
scripts.
