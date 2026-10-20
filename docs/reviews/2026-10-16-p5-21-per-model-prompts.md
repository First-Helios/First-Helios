# P5-21 — per-model prompt optimisation for the three kept models

**Date:** 2026-10-16 (session P5-21; the spec suggested 2026-10-17 — the session ran and finished
on 2026-10-16 UTC) · **Status:** draft for owner review, committed unchanged in the P5-22 archive ·
**Follows:** [P5-20 bracket screen](./2026-10-16-p5-20-bracket-screen.md) · **Proposes:** an ADR-0017 amendment (section 9; no ADR file edited)

All numbers are on **tuning pages** (the 218 labelled pages of seven sets); nothing here is a §8
held-out evaluation. Quality runs are laptop-GPU Q4 GGUF (llama.cpp b11176); GPU speed is not
evidence. Scratch, data and scripts: `var/menu-eval/prompt-opt/` (gitignored; `HANDOFF.md`
resumes it; `decisions.md` is the timestamped log).

> **2026-10-17 follow-up:** the completed [H4 / TEST3 evaluation](./2026-10-17-p5-21-harness-h-test3.md)
> finds Qwen3.5-9B g-v24 + H4 beats both baseline replicates under the separately
> pre-registered stored-data rule (+3.5–3.8 percentage points usable prices versus
> production v8). The original raw-output brackets remain inconclusive. The prompt-search
> results below are historical and unchanged.

> **Owner closeout direction (2026-10-18):** the 4B reference stays primary;
> 9B is a fallback candidate. This experiment ends with no PR or held-out draw.
> See the [closeout and Pi cost record](./2026-10-18-p5-21-closeout-pi-cost.md).

## Summary

- **No per-model prompt beat its model's P5-20 prompt.** Four rounds of per-model variants
  (32 on the 8 FAST pages, 19 completed on the 15 DEV pages), each built from that model's own
  diagnosed errors. None met the pre-registered promotion rule, which needs DEV raw usable up by
  more than the 0.024 replicate band, with accuracy and unmatched rows not worse. The final
  configurations are therefore the P5-20 ones:
  - Gemma-4-E4B: greedy, prompt v2.4 (sha256 `34660263…b503`);
  - Qwen3.5-9B: greedy, prompt v2.4;
  - Qwen3-4B-2507 Q4_K_M: seeded card sampling, prompt N1 (sha256 `8c4f2cf3…e246`).

  The per-model refinement rule on TEST2 is not applicable: there is no refined prompt.
- **Prompt effects are model-specific, as the owner expected, but small on DEV.**
  - The same rule moves different models in different directions. Example: the synthetic worked
    example EX2 gave Gemma +0.039 on FAST and Qwen3.5-9B −0.104.
  - Nearest misses on DEV:
    - Qwen3.5-9B q9b3c: +0.030, but accuracy −0.011 and unmatched +0.019.
    - Qwen3.5-9B q9b2b: +0.026, but unmatched +0.033.
    - Q4_K_M qkm2a: +0.027, but accuracy −0.0061 against a 0.0046 band.
  - Several variants raised raw price accuracy by 0.02–0.03 at flat raw usable: Q4_K_M with v2.4's
    split-line paragraph or the name-number rule; Gemma with the multi-price rule.
  - FAST misled more than once (Gemma gem1b: +0.039 on FAST, −0.013 on DEV).
- **TEST2 (45 new pages, scored once), bracket rule unchanged: both brackets inconclusive again.**
  Baseline Q4_0 replicates: raw usable 0.862 / 0.865, band 0.0033.
  - **Gemma-4-E4B** (B4) has raw usable **0.912**:
    - +0.047 / +0.050 vs the baseline replicates, CIs [+0.018, +0.074] / [+0.021, +0.078], 6/6
      sets;
    - +0.048 vs the Q4_K_M;
    - accuracy 0.972 vs 0.962 / 0.965.
    - Unlike on P5-20's TEST, it passes pipeline non-inferiority: frozen v8 usable 0.855 vs
      0.819 / 0.824, CIs > 0.
    - It fails only the unmatched-rows condition: 0.265 vs 0.189 per row (over-extraction).
  - **Qwen3.5-9B** (B8) has raw usable **0.896**:
    - +0.031 / +0.035, CIs > 0, 5/6 sets;
    - pipeline usable 0.849, the fewest unmatched rows (0.113).
    - It fails only raw accuracy, by 0.0002 beyond the band: 0.9619 vs 0.9654 (band 0.0033).
  - **Q4_K_M** (0.864) is level with the baseline (CIs include 0).

  The P5-20 TEST confirmation reproduces P5-20: both brackets inconclusive.
- **VAL (descriptive, after the rounds).** Of the six best DEV variants, one replicated:
  Qwen3.5-9B **q9b3c** (v2.4 + COMPLETE + NOOVER2 + DISHHEAD) has +0.031 raw usable on VAL, as on
  DEV (+0.030), at about −0.01 raw accuracy. The Q4_K_M's DEV near-misses reverse on VAL
  (−0.013, −0.014). q9b3c is the only per-model prompt worth a pre-registered locked-pages check
  later; it was not promoted here and was not run on TEST2.
- **Draft ADR-0017 amendment** (section 9): allow a per-model prompt only behind P5-21's guards.
  Those are a pre-registered diagnosis-driven variant, a DEV promotion rule at the replicate band,
  and a locked-pages refinement check, as part of the versioned model configuration. The evidence
  here says the fixed menu remains the default; no per-model prompt earned its place this time.
- **GPU:** 6.58 h (23,684 s) of the 8 h budget; 0 thermal pauses (guard 93/78). One CUDA process fault
  (Xid 13/43, "illegal instruction", 86 °C) killed the 9B's TEST2 run at page 35. It was not the
  full-chip reset of earlier sessions: no reboot was needed, and the run resumed for its 11
  missing pages.

## 1. Frozen protocol and amendments

`frozen-protocol.md` was written at 16:04Z, before any P5-21 inference or score (sha256 at
freezing `6888a3bf…0ed9`; amendments are appended with timestamps and change the file hash).

- **Models and starting configurations** (each model's "own P5-20 configuration"):
  Gemma-4-E4B g-v24 (greedy, prompt v2.4); Qwen3.5-9B g-v24; Qwen3-4B-2507 Q4_K_M s-n1 (model-card
  sampling T0.7 p0.8 k20, seed 20261016, neutral prompt N1). Reference: baseline Qwen3-4B-2507
  Q4_0 g-v24. GGUF SHA256 re-verified against `p520-pins.json` and the LFS hashes in
  `baseline-blobs.json`.
- **Runtime:** exactly P5-20's (image b11176 `1f4b9cf5…0ab6`, `-ngl 99 -fa off -ctk f16 -ctv f16
  -np 2 -c 12288 -t 4 --cache-ram 0 --jinja -lv 4`, thinking off, GBNF on, frozen pipeline
  `b4b0e2e`). Every variant passed the token budget (rendered sparse-retry prompt + cap ≤ 6,144
  per slot on all 218 pages); the longest variant added ~1,100 characters to v2.4.
- **Splits:** FAST (8 ⊂ DEV), DEV (15), VAL (15) and TEST (45) are P5-20's. **TEST2** (new, 45
  pages, seed 20261017, `make_splits2.py`) was drawn from the 143 pages in no P5-20 split.
- **Primary metric:** harness-free raw usable prices (`rawscore.py`, unchanged). Co-primary
  guards: raw price accuracy, unmatched raw rows per row, schema/truncation. Secondary: frozen v8
  pipeline usable, accuracy, false-reject rate, accepted-unmatched, wrong-price accepted.
- **Noise bands** = |baseline rep A − rep B| per split: DEV raw usable 0.0239, accuracy 0.0046,
  unmatched 0.0142; FAST 0.0163 / 0.0032 / 0.0087; VAL 0.0044 / 0.0003 / 0.0214; TEST2 from two
  new baseline runs (section 5).
- **Round rule:** FAST keep if raw usable ≥ round best − FAST band; ≤ 2 kept variants per model
  complete DEV; **promote** only if DEV raw usable − incumbent > DEV band, accuracy ≥ incumbent −
  accuracy band, unmatched ≤ incumbent + unmatched band, schema/truncation ≤ incumbent + 0.02.
- **Per-model refinement rule** (TEST2, final vs own P5-20 config) and **bracket rule** (P5-20's
  clear-winner rule on TEST2) are quoted verbatim in `frozen-protocol.md`; neither was relaxed.

Amendments and deviations (all timestamped in the scratch logs):

- **A1 (16:04Z, at freezing):** p5-5 has no page outside the P5-20 splits, so TEST2 spans 6 sets
  (7–8 pages each, 3 sets drawn by the seed at 8). The set conditions keep "positive on ≥ 5
  sets", which over 6 sets is stricter than P5-20's 5/7.
- **A2 (19:45Z, after round 4, before any VAL run of a variant):** no variant was promoted, so
  the protocol's VAL choice was empty; each model's two best DEV variants ran on VAL
  **descriptively** (spec step 4), without changing the finals or either rule.
- **Deviation — quoted phrases (found 18:05Z):** two short phrases quoted inside rule blocks,
  MULTI's `'$7 / $14'` and NOOVER's `'choose 2'`, occur on DEV pages read during diagnosis. This
  breaks the "examples are synthetic" rule for the eight variants that used them (gem1a, gem1c,
  gem2a, gem2c, q9b1b, qkm1a, qkm1c, qkm2c). None was promoted. From round 3, MULTI2/NOOVER2 use
  phrases absent from every page (`check_phrases.py`). The worked example EX2 and its names occur
  on no page.
- **Deviation — FAST tie (R3):** gem3a and gem3b tied exactly on FAST (258/307); the FAST step
  had no registered tie-break, so the protocol's VAL tie rule (accuracy, then unmatched) was
  applied by analogy (→ gem3a).
- **Order:** the TEST2 runs fixed by the protocol in every outcome (baseline ×2 and the three
  P5-20 configurations) were queued right after round 4's DEV runs; no TEST2 output was opened or
  scored until all TEST2 runs were complete.
- **Timestamps:** some early entries in `decisions.md` were first written with estimated times
  and corrected from file modification times and the GPU log within the hour.

## 2. Diagnosis (CPU only, P5-20 outputs, DEV)

`diagnosis-<model>.md` holds counts and 3–5 raw → gold examples per class from a new raw-row
classifier (`classify_errors.py`: missed price by layout, wrong amount by kind, unmatched by kind,
name rewrites), plus `unmatched_audit.py` and `harness_fit2.py`.

| Failure class (DEV, 964 gold prices) | Gemma-4-E4B g-v24 | Qwen3.5-9B g-v24 | Q4_K_M s-n1 | Baseline Q4_0 rep A |
|---|---:|---:|---:|---:|
| Raw rows | 1,601 | 1,380 | 1,343 | 1,358 |
| Missed prices, multi-price items | 35 | 22 | 68 | 81 |
| Missed prices, price after the name (split line) | 41 | 52 | 68 | 61 |
| Missed prices, inline / cards | 11 / 4 | 23 / 16 | 23 / 17 | 28 / 16 |
| Wrong amount: neighbouring item's price | 20 | 35 | 22 | 27 |
| Wrong amount: related item / variant swap | 18 | 23 | 11 | 19 |
| Wrong amount: other (incl. numbers not printed as the item's price) | 31 | 23 | 41 | 18 |
| Unmatched: printed line with no label | 156 | 117 | 135 | 88 |
| Unmatched: description as name | 57 | 16 | 38 | 41 |
| Unmatched: heading | 55 | 53 | 70 | 102 |

What the examples show:

- **Gemma-4-E4B over-extracts.** Its extra rows are printed page lines: description sentences
  used as names when the price follows the description, `""` names carrying a price line's
  amount, section labels repeated with a price, option lists. It invents no names (3 rows not on
  the page).
- **Qwen3.5-9B misreads card pages.** Many pages print each price twice, above the name and again
  after the description; the 9B takes the next card's top price (most of its 35 neighbouring-price
  errors). It is conservative elsewhere: it skips short card names and items in long lists.
- **The Q4_K_M drops second prices** ("$5.95/11.95", a size pair on one line, two price lines in a
  row) and writes numbers that are not the item's price: "512" from a beer name ("512 IPA")
  copied across a list, "0" on unpriced rows.

## 3. Variants and rounds

Rule blocks (full texts in `prompts21.py`; every id and sha256 in `variants.md`, registered before
each round's first score):

| Block | Content | Built from |
|---|---|---|
| BIND | price from the line after the name; a price just above a name usually belongs to the item above | split-line misses, neighbouring prices |
| BIND2 | cards that print each price twice: never the price just above the next item's name | 9B card errors |
| MULTI / MULTI2 | several prices per item → one entry per price, with its size word | multi-price misses |
| NOOVER / NOOVER2 | every entry needs a real item name: no empty names, descriptions, headings, choice lists | Gemma over-extraction |
| COMPLETE | read to the end; grids, numbered combos and several-per-line items count | 9B misses |
| NOPRICE / NOPRICE2 / NAMENUM | only a printed price; never 0 or a number from a name; (NOPRICE2) add-on prices are not the base item's | Q4_K_M "512"/"0" |
| SPLITLINE | v2.4's multi-line paragraph, verbatim (the part N1 removed) | Q4_K_M accuracy |
| DISHHEAD | a dish name printed as a heading is the name; the description never is | description-as-name |
| EX2 | synthetic worked example: name / description / price items, an inline size pair, two price lines | binding, multi-price |

Variants (32 on FAST in four rounds, 19 completed DEV):

| id | sha256 | composition |
|---|---|---|
| v24 | `34660263ddca5386…` | V24 |
| n1 | `8c4f2cf39bbef175…` | N1 |
| gem1a | `70382a3fe7e75c51…` | V24, NOOVER |
| gem1b | `33628d9df65083d0…` | V24, BIND, + EX2 |
| gem1c | `d3e3d1b40a0efddd…` | N1, NOOVER, BIND |
| q9b1a | `aad91c8b17355a79…` | V24, BIND |
| q9b1b | `f28fe5f595e7bac4…` | V24, MULTI, + EX2 |
| q9b1c | `3ba23251fac1776d…` | V24, COMPLETE |
| qkm1a | `6345c97ff6d47185…` | N1, MULTI |
| qkm1b | `b197957e75ff62b1…` | N1, BIND |
| qkm1c | `ccb85b2ade776823…` | N1, MULTI, + EX2 |
| gem2a | `ee084461f4331220…` | V24, NOOVER, BIND2 |
| gem2b | `5c59f3985b228367…` | V24, BIND2 |
| gem2c | `fcb1d8f61d72ac0d…` | V24, NOOVER, MULTI |
| q9b2a | `5c59f3985b228367…` | V24, BIND2 |
| q9b2b | `a0190deff53f3b5b…` | V24, COMPLETE, BIND2 |
| q9b2c | `0f443121b3f0577d…` | V24, COMPLETE, NOPRICE |
| qkm2a | `3ec12a2f047eff40…` | N1, BIND, NOPRICE |
| qkm2b | `0fecef38fd546742…` | N1, NOPRICE |
| qkm2c | `2bc7f20c2c416536…` | N1, NOOVER, BIND, NOPRICE |
| gem3a | `9d77a8694752b59b…` | V24, MULTI2 |
| gem3b | `6413d34d27ad26b1…` | V24, NOOVER2, MULTI2, DISHHEAD |
| gem3c | `612ed45b99e149cc…` | V24, MULTI2, DISHHEAD |
| q9b3a | `64111adcf432a5bb…` | V24, COMPLETE, BIND2, NOOVER2 |
| q9b3b | `f4eb2c5c4bcb9de9…` | V24, COMPLETE, NOOVER2 |
| q9b3c | `2a0d03410880e1dd…` | V24, COMPLETE, NOOVER2, DISHHEAD |
| qkm3a | `9bded611f6a30751…` | N1, BIND, NOPRICE2 |
| qkm3b | `f06b399c6a394cb0…` | N1, SPLITLINE, BIND, NOPRICE2 |
| qkm3c | `cb80ea447405e06c…` | N1, SPLITLINE, BIND |
| gem4a | `fe8563d427d9d746…` | V24, MULTI2, COMPLETE |
| q9b4a | `c3e456792505eebf…` | V24, COMPLETE, NOOVER2, DISHHEAD, BIND |
| q9b4b | `e46319271951e08e…` | V24, COMPLETE, NOOVER2, DISHHEAD, NAMENUM |
| qkm4a | `6938f4ebda8242a3…` | N1, BIND, NOPRICE, NAMENUM |
| qkm4b | `da74cec201d1f7c7…` | N1, BIND, NOPRICE, NAMENUM, MULTI2 |

### FAST (8 pages)

#### Gemma-4-E4B — FAST (Δ vs P5-20 config)

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row | Δ raw usable | Δ acc. | Δ unmatched |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Gemma-4-E4B P5-20 config (g-v24) | 0.847 | 0.891 | 0.951 | 0.265 | 0.000 | 0.798 | 0.958 | 0.273 | 0.106 | — | — | — |
| Gemma-4-E4B g-gem1a | 0.866 | 0.898 | 0.971 | 0.256 | 0.000 | 0.798 | 1.000 | 0.278 | 0.106 | +0.020 | +0.0202 | -0.0089 |
| Gemma-4-E4B g-gem1b | 0.886 | 0.905 | 0.978 | 0.230 | 0.000 | 0.801 | 1.000 | 0.311 | 0.164 | +0.039 | +0.0273 | -0.0349 |
| Gemma-4-E4B g-gem1c | 0.818 | 0.876 | 0.972 | 0.247 | 0.000 | 0.782 | 1.000 | 0.148 | 0.122 | -0.029 | +0.0213 | -0.0177 |
| Gemma-4-E4B g-gem2a | 0.834 | 0.894 | 0.943 | 0.227 | 0.000 | 0.775 | 0.957 | 0.199 | 0.126 | -0.013 | -0.0078 | -0.0379 |
| Gemma-4-E4B g-gem2b | 0.824 | 0.887 | 0.955 | 0.245 | 0.000 | 0.779 | 0.960 | 0.245 | 0.192 | -0.023 | +0.0038 | -0.0191 |
| Gemma-4-E4B g-gem2c | 0.850 | 0.865 | 0.927 | 0.211 | 0.000 | 0.785 | 0.957 | 0.328 | 0.094 | +0.003 | -0.0237 | -0.0539 |
| Gemma-4-E4B g-gem3a | 0.840 | 0.898 | 0.977 | 0.353 | 0.000 | 0.775 | 1.000 | 0.213 | 0.151 | -0.007 | +0.0262 | +0.0887 |
| Gemma-4-E4B g-gem3b | 0.840 | 0.887 | 0.924 | 0.179 | 0.000 | 0.769 | 0.952 | 0.306 | 0.099 | -0.007 | -0.0267 | -0.0859 |
| Gemma-4-E4B g-gem3c | 0.853 | 0.894 | 0.939 | 0.234 | 0.000 | 0.772 | 0.960 | 0.225 | 0.141 | +0.007 | -0.0118 | -0.0306 |
| Gemma-4-E4B g-gem4a | 0.831 | 0.912 | 0.914 | 0.301 | 0.000 | 0.749 | 0.947 | 0.235 | 0.113 | -0.016 | -0.0366 | +0.0362 |

#### Qwen3.5-9B — FAST (Δ vs P5-20 config)

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row | Δ raw usable | Δ acc. | Δ unmatched |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.5-9B P5-20 config (g-v24) | 0.876 | 0.891 | 0.911 | 0.144 | 0.000 | 0.801 | 0.996 | 0.197 | 0.065 | — | — | — |
| Qwen3.5-9B g-q9b1a | 0.860 | 0.883 | 0.941 | 0.165 | 0.000 | 0.801 | 0.992 | 0.190 | 0.064 | -0.016 | +0.0296 | +0.0206 |
| Qwen3.5-9B g-q9b1b | 0.772 | 0.770 | 0.851 | 0.174 | 0.000 | 0.691 | 0.943 | 0.201 | 0.102 | -0.104 | -0.0605 | +0.0305 |
| Qwen3.5-9B g-q9b1c | 0.876 | 0.891 | 0.894 | 0.140 | 0.000 | 0.798 | 0.946 | 0.249 | 0.056 | +0.000 | -0.0175 | -0.0038 |
| Qwen3.5-9B g-q9b2a | 0.847 | 0.872 | 0.951 | 0.257 | 0.000 | 0.788 | 0.992 | 0.167 | 0.086 | -0.029 | +0.0397 | +0.1131 |
| Qwen3.5-9B g-q9b2b | 0.873 | 0.898 | 0.925 | 0.217 | 0.000 | 0.808 | 0.992 | 0.202 | 0.063 | -0.003 | +0.0139 | +0.0728 |
| Qwen3.5-9B g-q9b2c | 0.870 | 0.891 | 0.935 | 0.216 | 0.000 | 0.795 | 0.992 | 0.223 | 0.079 | -0.007 | +0.0233 | +0.0723 |
| Qwen3.5-9B g-q9b3a | 0.844 | 0.861 | 0.906 | 0.158 | 0.000 | 0.788 | 0.949 | 0.193 | 0.079 | -0.033 | -0.0055 | +0.0142 |
| Qwen3.5-9B g-q9b3b | 0.847 | 0.869 | 0.891 | 0.139 | 0.000 | 0.785 | 0.946 | 0.241 | 0.059 | -0.029 | -0.0205 | -0.0045 |
| Qwen3.5-9B g-q9b3c | 0.873 | 0.898 | 0.884 | 0.110 | 0.000 | 0.808 | 0.943 | 0.210 | 0.049 | -0.003 | -0.0271 | -0.0337 |
| Qwen3.5-9B g-q9b4a | 0.896 | 0.912 | 0.902 | 0.177 | 0.000 | 0.808 | 0.992 | 0.173 | 0.077 | +0.020 | -0.0089 | +0.0332 |
| Qwen3.5-9B g-q9b4b | 0.850 | 0.880 | 0.887 | 0.182 | 0.000 | 0.795 | 0.943 | 0.183 | 0.084 | -0.026 | -0.0240 | +0.0377 |

#### Qwen3-4B-2507 Q4_K_M — FAST (Δ vs P5-20 config)

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row | Δ raw usable | Δ acc. | Δ unmatched |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | 0.756 | 0.807 | 0.917 | 0.201 | 0.000 | 0.713 | 0.983 | 0.161 | 0.092 | — | — | — |
| Qwen3-4B-2507 Q4_K_M s-qkm1a | 0.762 | 0.828 | 0.916 | 0.200 | 0.000 | 0.723 | 0.982 | 0.179 | 0.108 | +0.007 | -0.0003 | -0.0011 |
| Qwen3-4B-2507 Q4_K_M s-qkm1b | 0.782 | 0.847 | 0.919 | 0.163 | 0.000 | 0.743 | 0.983 | 0.224 | 0.082 | +0.026 | +0.0022 | -0.0385 |
| Qwen3-4B-2507 Q4_K_M s-qkm1c | 0.756 | 0.807 | 0.912 | 0.206 | 0.000 | 0.710 | 0.952 | 0.223 | 0.090 | +0.000 | -0.0048 | +0.0053 |
| Qwen3-4B-2507 Q4_K_M s-qkm2a | 0.798 | 0.854 | 0.933 | 0.168 | 0.000 | 0.739 | 0.992 | 0.233 | 0.086 | +0.042 | +0.0158 | -0.0332 |
| Qwen3-4B-2507 Q4_K_M s-qkm2b | 0.739 | 0.803 | 0.915 | 0.152 | 0.000 | 0.704 | 0.978 | 0.229 | 0.093 | -0.016 | -0.0014 | -0.0496 |
| Qwen3-4B-2507 Q4_K_M s-qkm2c | 0.788 | 0.828 | 0.934 | 0.173 | 0.000 | 0.720 | 0.987 | 0.172 | 0.091 | +0.033 | +0.0176 | -0.0280 |
| Qwen3-4B-2507 Q4_K_M s-qkm3a | 0.769 | 0.839 | 0.927 | 0.189 | 0.000 | 0.717 | 0.983 | 0.220 | 0.108 | +0.013 | +0.0100 | -0.0124 |
| Qwen3-4B-2507 Q4_K_M s-qkm3b | 0.717 | 0.777 | 0.923 | 0.157 | 0.000 | 0.678 | 0.986 | 0.246 | 0.098 | -0.039 | +0.0064 | -0.0438 |
| Qwen3-4B-2507 Q4_K_M s-qkm3c | 0.752 | 0.810 | 0.923 | 0.199 | 0.000 | 0.707 | 0.986 | 0.204 | 0.111 | -0.003 | +0.0061 | -0.0022 |
| Qwen3-4B-2507 Q4_K_M s-qkm4a | 0.775 | 0.839 | 0.919 | 0.155 | 0.000 | 0.723 | 0.982 | 0.212 | 0.093 | +0.020 | +0.0028 | -0.0457 |
| Qwen3-4B-2507 Q4_K_M s-qkm4b | 0.762 | 0.821 | 0.923 | 0.157 | 0.000 | 0.710 | 0.987 | 0.167 | 0.090 | +0.007 | +0.0061 | -0.0444 |

Baselines: baseline Q4_0 rep A raw usable 0.765, acc 0.893, unmatched 0.169; baseline Q4_0 rep B raw usable 0.749, acc 0.890, unmatched 0.178.

### DEV (15 pages; only variants kept on FAST)

#### Gemma-4-E4B — DEV (Δ vs P5-20 config)

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row | Δ raw usable | Δ acc. | Δ unmatched |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Gemma-4-E4B P5-20 config (g-v24) | 0.897 | 0.952 | 0.935 | 0.174 | 0.000 | 0.839 | 0.983 | 0.209 | 0.069 | — | — | — |
| Gemma-4-E4B g-gem1b | 0.884 | 0.956 | 0.945 | 0.194 | 0.000 | 0.840 | 0.996 | 0.209 | 0.086 | -0.013 | +0.0101 | +0.0196 |
| Gemma-4-E4B g-gem2a | 0.858 | 0.949 | 0.938 | 0.176 | 0.000 | 0.817 | 0.979 | 0.181 | 0.069 | -0.039 | +0.0034 | +0.0020 |
| Gemma-4-E4B g-gem2c | 0.900 | 0.941 | 0.946 | 0.169 | 0.000 | 0.830 | 0.982 | 0.249 | 0.067 | +0.003 | +0.0110 | -0.0051 |
| Gemma-4-E4B g-gem3a | 0.897 | 0.957 | 0.955 | 0.226 | 0.000 | 0.844 | 0.995 | 0.192 | 0.082 | +0.000 | +0.0203 | +0.0516 |
| Gemma-4-E4B g-gem3c | 0.896 | 0.956 | 0.946 | 0.181 | 0.000 | 0.834 | 0.984 | 0.206 | 0.074 | -0.001 | +0.0112 | +0.0068 |
| Gemma-4-E4B g-gem4a | 0.881 | 0.956 | 0.928 | 0.230 | 0.012 | 0.820 | 0.978 | 0.221 | 0.075 | -0.017 | -0.0064 | +0.0558 |

#### Qwen3.5-9B — DEV (Δ vs P5-20 config)

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row | Δ raw usable | Δ acc. | Δ unmatched |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3.5-9B P5-20 config (g-v24) | 0.874 | 0.887 | 0.918 | 0.138 | 0.000 | 0.820 | 0.989 | 0.144 | 0.042 | — | — | — |
| Qwen3.5-9B g-q9b1a | 0.883 | 0.870 | 0.920 | 0.151 | 0.000 | 0.845 | 0.992 | 0.123 | 0.041 | +0.008 | +0.0018 | +0.0138 |
| Qwen3.5-9B g-q9b1c | 0.889 | 0.871 | 0.922 | 0.142 | 0.000 | 0.842 | 0.976 | 0.174 | 0.038 | +0.015 | +0.0039 | +0.0047 |
| Qwen3.5-9B g-q9b2b | 0.900 | 0.927 | 0.922 | 0.171 | 0.000 | 0.853 | 0.992 | 0.148 | 0.048 | +0.026 | +0.0045 | +0.0329 |
| Qwen3.5-9B g-q9b2c | 0.899 | 0.925 | 0.910 | 0.185 | 0.012 | 0.855 | 0.993 | 0.160 | 0.044 | +0.025 | -0.0075 | +0.0476 |
| Qwen3.5-9B g-q9b3c | 0.905 | 0.925 | 0.907 | 0.157 | 0.012 | 0.858 | 0.977 | 0.160 | 0.036 | +0.030 | -0.0112 | +0.0192 |
| Qwen3.5-9B g-q9b4a | 0.882 | 0.906 | 0.928 | 0.151 | 0.000 | 0.829 | 0.993 | 0.139 | 0.051 | +0.007 | +0.0096 | +0.0129 |

#### Qwen3-4B-2507 Q4_K_M — DEV (Δ vs P5-20 config)

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row | Δ raw usable | Δ acc. | Δ unmatched |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | 0.812 | 0.879 | 0.916 | 0.188 | 0.000 | 0.797 | 0.985 | 0.105 | 0.048 | — | — | — |
| Qwen3-4B-2507 Q4_K_M s-qkm1b | 0.827 | 0.894 | 0.911 | 0.171 | 0.000 | 0.812 | 0.988 | 0.117 | 0.041 | +0.015 | -0.0050 | -0.0173 |
| Qwen3-4B-2507 Q4_K_M s-qkm2a | 0.839 | 0.884 | 0.910 | 0.180 | 0.000 | 0.813 | 0.989 | 0.133 | 0.049 | +0.027 | -0.0061 | -0.0087 |
| Qwen3-4B-2507 Q4_K_M s-qkm2c | 0.811 | 0.890 | 0.946 | 0.201 | 0.024 | 0.788 | 0.986 | 0.094 | 0.048 | -0.001 | +0.0300 | +0.0128 |
| Qwen3-4B-2507 Q4_K_M s-qkm3a | 0.829 | 0.891 | 0.935 | 0.174 | 0.000 | 0.802 | 0.987 | 0.129 | 0.058 | +0.017 | +0.0193 | -0.0141 |
| Qwen3-4B-2507 Q4_K_M s-qkm3c | 0.821 | 0.891 | 0.941 | 0.188 | 0.000 | 0.805 | 0.985 | 0.108 | 0.049 | +0.008 | +0.0247 | -0.0002 |
| Qwen3-4B-2507 Q4_K_M s-qkm4a | 0.810 | 0.874 | 0.941 | 0.178 | 0.000 | 0.803 | 0.987 | 0.135 | 0.051 | -0.002 | +0.0248 | -0.0108 |
| Qwen3-4B-2507 Q4_K_M s-qkm4b | 0.814 | 0.875 | 0.946 | 0.176 | 0.000 | 0.796 | 0.991 | 0.106 | 0.054 | +0.002 | +0.0304 | -0.0129 |

Baselines: baseline Q4_0 rep A raw usable 0.795, acc 0.929, unmatched 0.175; baseline Q4_0 rep B raw usable 0.818, acc 0.933, unmatched 0.189.

### Round outcomes

| Round | Gemma-4-E4B (DEV incumbent 0.897) | Qwen3.5-9B (0.874) | Q4_K_M (0.812) |
|---|---|---|---|
| R1 | gem1b 0.884 (FAST +0.039 misled) | q9b1c 0.889 (+0.015); q9b1a 0.883 | qkm1b 0.827 (+0.015, acc −0.0050) |
| R2 | gem2c 0.900 (+0.003, acc +0.011); gem2a 0.858 | q9b2b 0.900 (+0.026, unm +0.033); q9b2c 0.899 (unm +0.048) | qkm2a 0.839 (+0.027, acc −0.0061); qkm2c 0.811 (acc +0.030) |
| R3 | gem3c 0.896; gem3a 0.897 (acc +0.020, unm +0.052) | q9b3c 0.905 (+0.030, acc −0.011, unm +0.019) | qkm3a 0.829 (acc +0.019); qkm3c 0.821 (acc +0.025) |
| R4 | gem4a 0.881 | q9b4a 0.882 (+0.007) | qkm4a 0.810 (acc +0.025); qkm4b 0.814 (acc +0.030) |
| Promoted | none | none | none |

What the rounds showed, per model:

- **Gemma-4-E4B.** v2.4 is already its best prompt on DEV.
  - MULTI cut its multi-price misses (35 → 24) and NOOVER its "other" wrong amounts (31 → 8), but
    neither moved raw usable.
  - NOOVER cut its unmatched rate on FAST (0.265 → 0.211) but not on DEV, where the extra rows are
    mostly printed list lines the labels leave out.
  - BIND/BIND2 made it worse (gem2a −0.039).
- **Qwen3.5-9B.**
  - COMPLETE is its lever: price-after misses 52 → 34, +0.025 to +0.030 raw usable. Every version
    also added rows: +46 to +185 on DEV (1,380 for v2.4), mostly unlabelled printed lines and headings.
  - NOOVER2 and DISHHEAD reduced that only partly and cost accuracy.
  - BIND2 raised its accuracy on FAST (+0.040) but added rows.
- **Q4_K_M.**
  - BIND + NOPRICE gives raw usable (+0.027); the name-number and split-line rules give accuracy
    (+0.019 to +0.030); not both at once.
  - With seeded sampling, one-sentence edits moved DEV raw usable by ~0.03 (qkm2a vs qkm4a), as
    much as the band.
- **The same rule is not portable.**
  - gem2b and q9b2a are the same text (v2.4 + BIND2): −0.023 for Gemma and −0.029 for the 9B on
    FAST, but +0.004 and +0.040 accuracy.
  - EX2: Gemma +0.039, 9B −0.104, Q4_K_M ±0 on FAST.

### VAL (descriptive, amendment A2)

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline Q4_0 rep A | 0.775 | 0.827 | 0.955 | 0.232 | 0.000 | 0.754 | 0.995 | 0.105 | 0.072 |
| baseline Q4_0 rep B | 0.779 | 0.839 | 0.954 | 0.211 | 0.000 | 0.749 | 0.995 | 0.114 | 0.085 |
| Gemma-4-E4B P5-20 config (g-v24) | 0.880 | 0.949 | 0.928 | 0.311 | 0.008 | 0.800 | 0.995 | 0.141 | 0.098 |
| Qwen3.5-9B P5-20 config (g-v24) | 0.880 | 0.921 | 0.939 | 0.166 | 0.008 | 0.833 | 0.997 | 0.083 | 0.073 |
| Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | 0.833 | 0.871 | 0.973 | 0.216 | 0.000 | 0.781 | 0.996 | 0.092 | 0.084 |
| Gemma-4-E4B g-gem2c | 0.888 | 0.943 | 0.944 | 0.286 | 0.008 | 0.820 | 0.994 | 0.155 | 0.096 |
| Gemma-4-E4B g-gem3a | 0.864 | 0.938 | 0.930 | 0.304 | 0.008 | 0.786 | 0.990 | 0.178 | 0.094 |
| Qwen3.5-9B g-q9b3c | 0.911 | 0.936 | 0.930 | 0.141 | 0.000 | 0.857 | 0.996 | 0.087 | 0.059 |
| Qwen3.5-9B g-q9b2b | 0.880 | 0.931 | 0.950 | 0.164 | 0.008 | 0.814 | 0.994 | 0.119 | 0.071 |
| Qwen3-4B-2507 Q4_K_M s-qkm2a | 0.819 | 0.869 | 0.963 | 0.201 | 0.000 | 0.777 | 0.994 | 0.090 | 0.068 |
| Qwen3-4B-2507 Q4_K_M s-qkm3a | 0.818 | 0.877 | 0.954 | 0.226 | 0.000 | 0.762 | 0.991 | 0.110 | 0.079 |

VAL band: raw usable 0.0044, accuracy 0.0003, unmatched 0.0214 (baseline 0.775 / 0.779).
Δ vs each model's P5-20 configuration on VAL:

| Variant | DEV Δ raw usable / acc. / unmatched | VAL Δ raw usable / acc. / unmatched | Agreement |
|---|---|---|---|
| q9b3c (9B: v2.4 + COMPLETE + NOOVER2 + DISHHEAD) | +0.030 / −0.011 / +0.019 | **+0.031** / −0.008 / −0.024 | raw-usable gain replicates; accuracy cost replicates |
| q9b2b (9B: v2.4 + COMPLETE + BIND2) | +0.026 / +0.005 / +0.033 | −0.001 / +0.011 / −0.002 | DEV gain gone |
| gem2c (Gemma: v2.4 + NOOVER + MULTI) | +0.003 / +0.011 / −0.005 | +0.008 / +0.015 / −0.025 | small, same direction (unmatched ↓) |
| gem3a (Gemma: v2.4 + MULTI2) | +0.000 / +0.020 / +0.052 | −0.016 / +0.002 / −0.008 | disagree |
| qkm2a (Q4_K_M: N1 + BIND + NOPRICE) | +0.027 / −0.006 / −0.009 | −0.013 / −0.009 / −0.015 | **reverses** |
| qkm3a (Q4_K_M: N1 + BIND + NOPRICE2) | +0.017 / +0.019 / −0.014 | −0.014 / −0.019 / +0.011 | **reverses** |

FAST, DEV and VAL disagree as often as they agree:
- The Q4_K_M's two DEV near-misses reverse on VAL; its sampled decoding makes 15-page
  comparisons noisy.
- One variant replicates: **q9b3c** gives Qwen3.5-9B about +0.03 raw usable on both DEV and VAL,
  at about −0.01 raw accuracy. The protocol kept it out because DEV accuracy (−0.011) and DEV
  unmatched (+0.019) were worse than their bands; that rule is not relaxed here.
- q9b3c was not run on TEST2 (locked and scored). If wanted, it is the one per-model prompt worth
  a pre-registered locked-pages check in a later session, with its accuracy cost as the thing to
  watch: wrong-price accepts were already the 9B's weak point.
- gem2c is the only Gemma variant that moves unmatched rows the intended way on both DEV and VAL,
  but its raw-usable change is within noise.

## 4. Cross-check (DEV)

The finals are the P5-20 prompts (v2.4 for Gemma and Qwen3.5-9B, N1 for the Q4_K_M), so the
cross-check matrix is each model on both base prompts (all from existing runs; Qwen3.5-9B N1 and
Q4_K_M v2.4 were completed on DEV this session):

| Model (decoding) | v2.4 | N1 |
|---|---:|---:|
| Gemma-4-E4B (g) | 0.897 / 0.935 / 0.174 | 0.858 / 0.978 / 0.206 |
| Qwen3.5-9B (g) | 0.874 / 0.918 / 0.138 | 0.889 / 0.907 / 0.230 |
| Qwen3-4B-2507 Q4_K_M (s) | 0.812 / 0.954 / 0.208 | 0.812 / 0.916 / 0.188 |

Cells: DEV raw usable / raw accuracy / unmatched per row.

Reading:
- **v2.4 vs N1 helps differently per model on DEV.**
  - Gemma prefers v2.4 (0.897 vs 0.858; N1 has higher accuracy, 0.978).
  - Qwen3.5-9B is +0.015 with N1 but has 0.092 more unmatched rows per row.
  - The Q4_K_M ties on raw usable (0.812) with +0.038 accuracy under v2.4.
- The baseline itself scores 0.795 / 0.818 with v2.4 on DEV.
- No variant prompt was run across models beyond the shared text in gem2b / q9b2a (section 3):
  with no promoted per-model prompt, the spec's "final prompt on the other models" column is the
  base prompts above.
- The evidence that prompts are model-specific comes from the rounds, not this matrix: the same
  rule moved the models in different directions.

## 5. TEST2 (45 new pages, scored once) and P5-20 TEST (confirmation)

### TEST2

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline Q4_0 rep A | 0.862 | 0.911 | 0.962 | 0.189 | 0.007 | 0.819 | 0.992 | 0.076 | 0.056 |
| baseline Q4_0 rep B | 0.865 | 0.913 | 0.965 | 0.189 | 0.002 | 0.824 | 0.993 | 0.076 | 0.057 |
| Gemma-4-E4B g-v24 | 0.912 | 0.968 | 0.972 | 0.265 | 0.000 | 0.855 | 0.997 | 0.175 | 0.081 |
| Qwen3.5-9B g-v24 | 0.896 | 0.923 | 0.962 | 0.113 | 0.007 | 0.849 | 0.993 | 0.068 | 0.044 |
| Qwen3-4B-2507 Q4_K_M s-n1 | 0.864 | 0.918 | 0.965 | 0.186 | 0.000 | 0.829 | 0.995 | 0.068 | 0.068 |

Noise band (|rep A − rep B|): raw usable 0.0033, raw accuracy 0.0033, unmatched 0.0005, pipeline usable 0.0042.

**Refinement rule (final vs own P5-20 configuration).**

| Model | Final | Δ raw usable [95 % CI] | sets + | Δ raw acc. [CI] | Δ unmatched [CI] | Verdict |
|---|---|---:|---:|---:|---:|---|
| gemma4-e4b | Gemma-4-E4B g-v24 | — | — | — | — | n/a (final = P5-20 configuration) |
| q3-4b-2507-qkm | Qwen3-4B-2507 Q4_K_M s-n1 | — | — | — | — | n/a (final = P5-20 configuration) |
| q35-9b | Qwen3.5-9B g-v24 | — | — | — | — | n/a (final = P5-20 configuration) |

**Bracket rule (P5-20 clear-winner rule).**

| Bracket | Entry | vs | Δ raw usable [95 % CI] | sets + | Δ pipeline usable [CI] |
|---|---|---|---:|---:|---:|
| B4 | Gemma-4-E4B g-v24 | Qwen3-4B-2507 Q4_K_M s-n1 | +0.048 [+0.022, +0.077] | 5/6 | — |
| B4 | Gemma-4-E4B g-v24 | baseline Q4_0 rep A | +0.050 [+0.021, +0.078] | 6/6 | +0.035 [+0.012, +0.057] |
| B4 | Gemma-4-E4B g-v24 | baseline Q4_0 rep B | +0.047 [+0.018, +0.074] | 6/6 | +0.031 [+0.007, +0.053] |
| B4 | Qwen3-4B-2507 Q4_K_M s-n1 | Gemma-4-E4B g-v24 | -0.048 [-0.077, -0.022] | 0/6 | — |
| B4 | Qwen3-4B-2507 Q4_K_M s-n1 | baseline Q4_0 rep A | +0.002 [-0.021, +0.022] | 3/6 | +0.010 [-0.011, +0.030] |
| B4 | Qwen3-4B-2507 Q4_K_M s-n1 | baseline Q4_0 rep B | -0.001 [-0.022, +0.016] | 3/6 | +0.006 [-0.015, +0.026] |
| B8 | Qwen3.5-9B g-v24 | baseline Q4_0 rep A | +0.035 [+0.015, +0.057] | 5/6 | +0.030 [+0.004, +0.058] |
| B8 | Qwen3.5-9B g-v24 | baseline Q4_0 rep B | +0.031 [+0.011, +0.055] | 5/6 | +0.025 [-0.002, +0.055] |

| Bracket | Entry | C1 raw usable beats all | C2 acc./unmatched in band | C3 schema/trunc. | C4 pipeline non-inferior | Verdict |
|---|---|---|---|---|---|---|
| B4 | Gemma-4-E4B g-v24 | yes | no | yes | yes | inconclusive |
| B4 | Qwen3-4B-2507 Q4_K_M s-n1 | no | yes | yes | no | inconclusive |
| B8 | Qwen3.5-9B g-v24 | yes | no | yes | yes | inconclusive |

### P5-20 TEST (45 pages; scored in P5-20; confirmation set, not held out)

| Config | Raw usable | Raw recall | Raw acc. | Unmatched/row | Schema/trunc. | Pipe usable | Pipe acc. | Pipe FR | Acc.-unmatched/row |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| baseline Q4_0 rep A | 0.783 | 0.880 | 0.968 | 0.236 | 0.003 | 0.766 | 0.990 | 0.077 | 0.061 |
| baseline Q4_0 rep B | 0.792 | 0.884 | 0.973 | 0.237 | 0.003 | 0.779 | 0.991 | 0.070 | 0.063 |
| Gemma-4-E4B P5-20 config (g-v24) | 0.854 | 0.949 | 0.972 | 0.272 | 0.000 | 0.801 | 0.988 | 0.169 | 0.094 |
| Qwen3.5-9B P5-20 config (g-v24) | 0.863 | 0.944 | 0.957 | 0.150 | 0.000 | 0.837 | 0.989 | 0.053 | 0.045 |
| Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | 0.799 | 0.890 | 0.959 | 0.220 | 0.000 | 0.784 | 0.989 | 0.072 | 0.065 |

Noise band (|rep A − rep B|): raw usable 0.0090, raw accuracy 0.0053, unmatched 0.0004, pipeline usable 0.0136.

**Refinement rule (final vs own P5-20 configuration).**

| Model | Final | Δ raw usable [95 % CI] | sets + | Δ raw acc. [CI] | Δ unmatched [CI] | Verdict |
|---|---|---:|---:|---:|---:|---|
| gemma4-e4b | Gemma-4-E4B P5-20 config (g-v24) | — | — | — | — | n/a (final = P5-20 configuration) |
| q3-4b-2507-qkm | Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | — | — | — | — | n/a (final = P5-20 configuration) |
| q35-9b | Qwen3.5-9B P5-20 config (g-v24) | — | — | — | — | n/a (final = P5-20 configuration) |

**Bracket rule (P5-20 clear-winner rule).**

| Bracket | Entry | vs | Δ raw usable [95 % CI] | sets + | Δ pipeline usable [CI] |
|---|---|---|---:|---:|---:|
| B4 | Gemma-4-E4B P5-20 config (g-v24) | Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | +0.055 [+0.017, +0.098] | 6/7 | — |
| B4 | Gemma-4-E4B P5-20 config (g-v24) | baseline Q4_0 rep A | +0.071 [+0.040, +0.109] | 7/7 | +0.035 [-0.003, +0.077] |
| B4 | Gemma-4-E4B P5-20 config (g-v24) | baseline Q4_0 rep B | +0.062 [+0.031, +0.096] | 7/7 | +0.022 [-0.018, +0.060] |
| B4 | Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | Gemma-4-E4B P5-20 config (g-v24) | -0.055 [-0.098, -0.017] | 1/7 | — |
| B4 | Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | baseline Q4_0 rep A | +0.015 [-0.019, +0.052] | 5/7 | +0.019 [-0.010, +0.055] |
| B4 | Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | baseline Q4_0 rep B | +0.006 [-0.019, +0.033] | 5/7 | +0.005 [-0.019, +0.033] |
| B8 | Qwen3.5-9B P5-20 config (g-v24) | baseline Q4_0 rep A | +0.080 [+0.049, +0.120] | 7/7 | +0.072 [+0.043, +0.111] |
| B8 | Qwen3.5-9B P5-20 config (g-v24) | baseline Q4_0 rep B | +0.071 [+0.039, +0.108] | 6/7 | +0.058 [+0.029, +0.093] |

| Bracket | Entry | C1 raw usable beats all | C2 acc./unmatched in band | C3 schema/trunc. | C4 pipeline non-inferior | Verdict |
|---|---|---|---|---|---|---|
| B4 | Gemma-4-E4B P5-20 config (g-v24) | yes | no | yes | no | inconclusive |
| B4 | Qwen3-4B-2507 Q4_K_M P5-20 config (s-n1) | no | no | yes | no | inconclusive |
| B8 | Qwen3.5-9B P5-20 config (g-v24) | yes | no | yes | yes | inconclusive |

**TEST2 vs TEST.** TEST2's pages are easier for every model: the baseline scores 0.862 / 0.865
raw usable there vs 0.783 / 0.792 on TEST. The gaps between models narrow to:
- Gemma +0.047 to +0.050 (TEST: +0.062 to +0.071);
- Qwen3.5-9B +0.031 to +0.035 (TEST: +0.071 to +0.080).

The rank order is the same on both sets: Gemma-4-E4B ≥ Qwen3.5-9B > Q4_K_M ≈ baseline.

Frozen v8 harness on TEST2 rows:

| | Gemma-4-E4B | Qwen3.5-9B | Q4_K_M | baseline A / B |
|---|---:|---:|---:|---:|
| Pipeline usable | 0.855 | 0.849 | 0.829 | 0.819 / 0.824 |
| False reject on correct rows | 0.175 | 0.068 | 0.068 | 0.076 / 0.076 |
| Accepted rows matching no label, per row | 0.081 | 0.044 | 0.068 | 0.056 / 0.057 |
| Wrong-price accepted, per row | 0.0019 | 0.0051 | 0.0034 | 0.0055 / 0.0046 |

The v8 harness still rejects about one in six of Gemma's correct rows, and Gemma still has the
most accepted-unmatched rows. That is the Amendment 19 production-risk metric: what would be
stored with no label to check it. Its wrong-price accepts are the lowest.

Process note: TEST2 was first scored at 21:40Z, before the 9B run was complete, so a 34-page
partial 9B score (0.909) was seen. The reported 9B numbers are from the completed 45-page run,
scored after the resume. No decision depended on the partial score: the finals were fixed at
19:43Z and both rules are mechanical.

## 6. Verdicts

**Per model** (best prompt; gain over its own P5-20 configuration; standing vs the baseline on
TEST2):

| Model | Best prompt (id, sha256) | Gain over own P5-20 config | vs baseline rep A / rep B, raw usable (95 % CI) |
|---|---|---|---|
| Gemma-4-E4B (g) | v2.4 = its P5-20 prompt, `34660263ddca538688e2fea8f5aeb7da7d826efc52be3ff584b6d7f86618b503` | none: no variant promoted (best DEV: gem2c +0.003, gem3a +0.000; TEST2 refinement n/a) | +0.050 [+0.021, +0.078] / +0.047 [+0.018, +0.074]; 6/6 sets |
| Qwen3.5-9B (g) | v2.4 = its P5-20 prompt, same sha256 | none: no variant promoted (best DEV: q9b3c +0.030, failed accuracy and unmatched; TEST2 refinement n/a) | +0.035 [+0.015, +0.057] / +0.031 [+0.011, +0.055]; 5/6 sets |
| Qwen3-4B-2507 Q4_K_M (s) | N1 = its P5-20 prompt, `8c4f2cf39bbef17523078c172ebb54e2143f6e4df23e4cec7aa54246680fe246` | none: no variant promoted (best DEV: qkm2a +0.027, failed accuracy; TEST2 refinement n/a) | +0.002 [−0.021, +0.022] / −0.001 [−0.022, +0.016]; 3/6 sets |

**Brackets (TEST2, P5-20 clear-winner rule, not relaxed):**

- **B4: inconclusive.** Gemma-4-E4B passes C1, C3 and C4: raw usable beats both replicates and
  the Q4_K_M with CIs > 0, and the pipeline is now non-inferior. It fails C2 on unmatched rows
  (0.265 vs 0.189; band 0.0005). The Q4_K_M fails C1 and C4.
- **B8: inconclusive.** Qwen3.5-9B passes C1, C3 and C4. It fails C2 on raw accuracy by
  0.0002 beyond the band (0.9619 vs rep B 0.9654, band 0.0033); its unmatched rate is the lowest.
- **P5-20 TEST (confirmation):** both brackets inconclusive, as in P5-20. Gemma fails C2 and C4
  there; the 9B fails C2.

**What this means for the owner's question** ("different prompts per model, see which refines
to the best results"):
- On these pages the P5-20 prompts were already at or near each model's best. The refinement
  available from prompt wording is below what 15 DEV pages can detect.
- Gemma-4-E4B remains the strongest B4 extractor on raw output.
- Its one remaining failure is over-extraction. P5-21 shows that prompt rules alone do not remove
  it on DEV, so it points at the harness (ADR-0017 item 2) or at labels for printed list lines,
  not at more prompt iteration.

## 7. Limitations

- **Tuning pages only.** DEV, VAL, TEST and TEST2 are all tuning pages; v8/[5b] were fitted on
  them. Prompts were iterated on DEV (15 pages) with FAST (8) first; FAST misled more than once
  (gem1b: +0.039 on FAST, −0.013 on DEV). VAL is 15 pages.
- **Promotion threshold vs page count.** The DEV band (0.024 raw usable, from two greedy baseline
  replicates) is about the size of the largest prompt effects seen. With 15 DEV pages a real
  +0.02 effect cannot be separated from noise; the protocol chose to protect against prompt
  overfit at that cost.
- **Sampled decoding.** The Q4_K_M runs one seeded sample per configuration; one-sentence prompt
  edits moved its DEV raw usable by ~0.03 (qkm2a vs qkm4a). The greedy-replicate band may
  understate its variance.
- **Quoted phrases from DEV pages** in two rule blocks (section 1; none of those variants was
  promoted).
- **GPU Q4 ≠ production.** Quality is measured on laptop-GPU Q4 GGUF; the Pi NPU runs W8A8 and
  the Pi CPU other quants. Prompt sensitivity can differ per quantisation.
- Labels follow labels-v9; some unmatched rows are printed lines the labels leave out (e.g. list
  entries under one printed price), so "unmatched" over-counts real errors for every model alike.

## 8. Execution notes

- Timeline (UTC, 2026-10-16):
  - setup and protocol 15:55–16:04;
  - diagnosis 16:05–16:09;
  - R1 16:15–17:06, R2 17:08–18:09, R3 18:11–19:03, R4 19:05–19:43;
  - TEST2 19:42–21:40, plus the 9B resume 21:41–21:49;
  - descriptive VAL 21:49–22:43.
- GPU wall time (`logs/gpu-time.log`, container load + budget check + inference): 6.58 h (23,684 s).
  0 thermal pauses (guard 93/78; the owner was asked once at the start about 86/72, and with no
  answer the setting stayed). The guard process was alive at the end (stopped by PID at 22:44Z),
  but its log has only the start line: no pause, no error, and no "guard stopped" line on
  SIGTERM. So its polling all session is not proven by its own log; GPU temperatures sampled
  during the session were 86–87 °C, below the 93 °C pause. GPU temperature sat at 86–87 °C under load all session.
- One CUDA fault (21:39Z, Qwen3.5-9B, TEST2 page 35):
  - `CUDA error: an illegal instruction was encountered` in `launch_mul_mat_q`;
  - kernel `NVRM: Xid 13` (SM warp exception, illegal instruction encoding) and `Xid 43`;
  - `GPU Recovery Action: None`.

  The next container ran normally and the run resumed by page. This differs from P5-19/P5-20's
  full-chip resets at 89 °C, but it is a second hardware-level fault class at the same high
  temperature. Worth a look before long GPU sessions (cooling, or the owner's lower pause).
- Runner: P5-20's `p520.py` copied as `p521.py`. The only changes are the container prefix, the
  split file and the prompt registry. P5-20 outputs were reused for identical configurations
  (`reuse_p520.py`).
- Pi: not touched.
- Hygiene: `pre-commit run --files` on this review passes. No tracked code changed, so
  `make ci` was not run (the spec asks for it only if tracked code changes).

## 9. For the owner: draft ADR-0017 amendment (not applied)

**Tension recorded.** ADR-0017 (Proposed) item 3 says a model is screened with a fixed menu
{v2.4, N1, S1} × {greedy, card sampling}, and "a prompt is never tuned per model beyond this
menu". The owner asked P5-21 to tune prompts per model. P5-21 did so under a pre-registered
guard and found no per-model prompt that beats the menu's choice on DEV beyond the replicate
band in four rounds. The evidence supports allowing per-model prompts only behind a guard at
least as strict as P5-21's, and suggests the menu remains a sensible default. Proposed text for
the owner (not applied to the ADR file):

> **Amendment 1 (draft, P5-21): per-model prompt as part of the model configuration.**
>
> 1. **Scope.** A model's configuration is (weights, quantisation, decoding, system prompt). The
>    system prompt may differ per **model**, never per site, platform or layout class chosen by
>    site (owner rule: one universal pipeline). Grammar, schema, token caps and the sparse-retry
>    nudge are pipeline-wide and never per model.
> 2. **Starting point.** Every model starts from the item 3 menu; a per-model prompt is a
>    variant of the model's best menu prompt.
> 3. **How a per-model prompt is made.** Diagnosis of the model's own raw errors on DEV
>    (classes as in P5-21: missed by layout, wrong amount kind, unmatched kind); variants
>    pre-registered (id, parent, sha256, target, expected direction) before they are scored;
>    rules, wording, ordering and worked examples only; worked examples and quoted phrases
>    synthetic and checked absent from every labelled page; ≤ 3 variants per round, ≤ 4 rounds.
> 4. **Promotion guard (DEV).** A variant replaces the model's prompt only if DEV raw usable
>    rises beyond the DEV replicate band and raw accuracy, unmatched rows and schema/truncation
>    are not worse beyond their bands. FAST subsets screen only; they never promote.
> 5. **Held-out guard.** A promoted prompt is kept only if, on a locked set of pages not used for
>    any prompt decision (P5-21: TEST2), it beats the model's previous configuration (paired
>    page bootstrap CI > 0 on raw usable, positive on ≥ 5 sets; accuracy and unmatched not worse
>    beyond the band; schema/truncation ≤ +2 points). Otherwise the previous configuration stays.
> 6. **Versioning.** The prompt text and its sha256 are part of the pipeline version per model;
>    a prompt change is a pipeline version change and needs a §8 evaluation before it ships.
> 7. **Harness.** Per-model prompts do not license per-model harness rules; harness changes stay
>    under item 2 (multi-model acceptance). Because prompts change output style, the item 1
>    invariance suite is the protection against a prompt change silently changing what the
>    harness accepts.

## Appendix: prompt texts (final configurations and the DEV near-misses)

### `v24` — sha256 `34660263ddca538688e2fea8f5aeb7da7d826efc52be3ff584b6d7f86618b503`

```text
You extract restaurant menus. Input lines are 'BLOCK_ID | text' in page order. Return every menu item that is sold, grouped by the menu section it is under. Each item is {"b": block id where its name appears, "n": item name copied exactly as printed, "p": price copied exactly as printed, digits only (e.g. 12.50), "" if no price is printed for it, "v": size/variant word printed next to that price (e.g. "Large", "Glass"), only if there is one}. An item with several prices gets one entry per price. Many menus print one item over several lines: a short name line, then its price line and/or a description line, in either order. Those lines are ONE item: its name is the short name line (never the description sentence), its price comes from the price line after the name, and a price line or description line is never an item of its own. Do not invent items or prices, do not convert or compute prices, skip section headings, descriptions, navigation, hours, addresses, reviews and add-on/extra lines. If the text contains no menu items, return no sections. Output compact JSON on a single line with no spaces or newlines. Example input:
b0011 | Tacos
b0012 | Carne Asada Taco | $3.50
b0014 | Horchata
b0015 | $2.50/Small
b0016 | $3.50/Large
b0017 | Sides
b0018 | CHIPS AND SALSA
b0019 | $4
b0020 | House-made chips, roasted tomato salsa.
b0021 | Elote
b0022 | Grilled corn, cotija, chile and lime.
b0023 | 5.25
Example output:
{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50","v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},{"b":"b0021","n":"Elote","p":"5.25"}]}]}
```

### `n1` — sha256 `8c4f2cf39bbef17523078c172ebb54e2143f6e4df23e4cec7aa54246680fe246`

```text
You extract restaurant menus. Each input line is 'BLOCK_ID | text', in page order. List every item on sale, grouped under the menu section it appears in. For each item output {"b": the block id of the line with the item's name, "n": the item name exactly as printed, "p": the price exactly as printed, digits only (e.g. 12.50), or "" if no price is printed for it, "v": the size or variant label printed with that price (e.g. "Large", "Glass"), omitted if there is none}. If an item has several prices, output one entry per price. Copy names and prices from the text; never invent, translate, convert or calculate them. Do not output section headings, descriptions, navigation, opening hours, addresses, reviews, or add-on/extra lines as items. If there are no menu items, return no sections. Output compact JSON on one line, without spaces or newlines. Example input:
b0011 | Tacos
b0012 | Carne Asada Taco | $3.50
b0014 | Horchata
b0015 | $2.50/Small
b0016 | $3.50/Large
b0017 | Sides
b0018 | CHIPS AND SALSA
b0019 | $4
b0020 | House-made chips, roasted tomato salsa.
b0021 | Elote
b0022 | Grilled corn, cotija, chile and lime.
b0023 | 5.25
Example output:
{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50","v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},{"b":"b0021","n":"Elote","p":"5.25"}]}]}
```

### `gem2c` — sha256 `fcb1d8f61d72ac0d0c559a8bff5c7a02bd7198d6520724a467e926fec796a773`

```text
You extract restaurant menus. Input lines are 'BLOCK_ID | text' in page order. Return every menu item that is sold, grouped by the menu section it is under. Each item is {"b": block id where its name appears, "n": item name copied exactly as printed, "p": price copied exactly as printed, digits only (e.g. 12.50), "" if no price is printed for it, "v": size/variant word printed next to that price (e.g. "Large", "Glass"), only if there is one}. An item with several prices gets one entry per price. Many menus print one item over several lines: a short name line, then its price line and/or a description line, in either order. Those lines are ONE item: its name is the short name line (never the description sentence), its price comes from the price line after the name, and a price line or description line is never an item of its own. Do not invent items or prices, do not convert or compute prices, skip section headings, descriptions, navigation, hours, addresses, reviews and add-on/extra lines. If the text contains no menu items, return no sections. Every entry needs a real item name: the short title of a dish or drink as printed. Never output an entry with an empty name, a description or ingredient sentence as its name, a section or category heading (even when a price is printed beside it), a list of choices (flavours, sides, toppings), or an instruction such as 'choose 2' or 'served with ...'. When one line prints several prices for one item (e.g. '4.50/8.95', '$7 / $14', 'Cup 4 Bowl 7') or an item's name is followed by several price lines, output one entry per price in printed order, each with the size word printed beside that price as v. Output compact JSON on a single line with no spaces or newlines. Example input:
b0011 | Tacos
b0012 | Carne Asada Taco | $3.50
b0014 | Horchata
b0015 | $2.50/Small
b0016 | $3.50/Large
b0017 | Sides
b0018 | CHIPS AND SALSA
b0019 | $4
b0020 | House-made chips, roasted tomato salsa.
b0021 | Elote
b0022 | Grilled corn, cotija, chile and lime.
b0023 | 5.25
Example output:
{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50","v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},{"b":"b0021","n":"Elote","p":"5.25"}]}]}
```

### `gem3a` — sha256 `9d77a8694752b59b15838cb24f245e357a3ec3bc7b2c4ca02fb24281e886f709`

```text
You extract restaurant menus. Input lines are 'BLOCK_ID | text' in page order. Return every menu item that is sold, grouped by the menu section it is under. Each item is {"b": block id where its name appears, "n": item name copied exactly as printed, "p": price copied exactly as printed, digits only (e.g. 12.50), "" if no price is printed for it, "v": size/variant word printed next to that price (e.g. "Large", "Glass"), only if there is one}. An item with several prices gets one entry per price. Many menus print one item over several lines: a short name line, then its price line and/or a description line, in either order. Those lines are ONE item: its name is the short name line (never the description sentence), its price comes from the price line after the name, and a price line or description line is never an item of its own. Do not invent items or prices, do not convert or compute prices, skip section headings, descriptions, navigation, hours, addresses, reviews and add-on/extra lines. If the text contains no menu items, return no sections. When one line prints several prices for one item (e.g. '4.50/8.95', '$6 / $11', 'Cup 4 Bowl 7') or an item's name is followed by several price lines, output one entry per price in printed order, each with the size word printed beside that price as v. Output compact JSON on a single line with no spaces or newlines. Example input:
b0011 | Tacos
b0012 | Carne Asada Taco | $3.50
b0014 | Horchata
b0015 | $2.50/Small
b0016 | $3.50/Large
b0017 | Sides
b0018 | CHIPS AND SALSA
b0019 | $4
b0020 | House-made chips, roasted tomato salsa.
b0021 | Elote
b0022 | Grilled corn, cotija, chile and lime.
b0023 | 5.25
Example output:
{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50","v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},{"b":"b0021","n":"Elote","p":"5.25"}]}]}
```

### `q9b3c` — sha256 `2a0d03410880e1ddf0f33c87db7d457df294bd2627f9530334d75db72b7a5164`

```text
You extract restaurant menus. Input lines are 'BLOCK_ID | text' in page order. Return every menu item that is sold, grouped by the menu section it is under. Each item is {"b": block id where its name appears, "n": item name copied exactly as printed, "p": price copied exactly as printed, digits only (e.g. 12.50), "" if no price is printed for it, "v": size/variant word printed next to that price (e.g. "Large", "Glass"), only if there is one}. An item with several prices gets one entry per price. Many menus print one item over several lines: a short name line, then its price line and/or a description line, in either order. Those lines are ONE item: its name is the short name line (never the description sentence), its price comes from the price line after the name, and a price line or description line is never an item of its own. Do not invent items or prices, do not convert or compute prices, skip section headings, descriptions, navigation, hours, addresses, reviews and add-on/extra lines. If the text contains no menu items, return no sections. Read the text to its end and list every item in page order: short names in grids or cards, numbered combos and items printed several to a line all count. Do not stop early. Every entry needs a real item name: the short title of a dish or drink as printed. Never output an entry with an empty name, a description or ingredient sentence as its name, a section or category heading (even when a price is printed beside it), a list of choices (flavours, sides, toppings), or an instruction such as 'pick any two' or 'served with ...'. A dish name is often printed as a heading or in capitals, followed by its description and its price: that heading is the item's name, and the description is never the name. Output compact JSON on a single line with no spaces or newlines. Example input:
b0011 | Tacos
b0012 | Carne Asada Taco | $3.50
b0014 | Horchata
b0015 | $2.50/Small
b0016 | $3.50/Large
b0017 | Sides
b0018 | CHIPS AND SALSA
b0019 | $4
b0020 | House-made chips, roasted tomato salsa.
b0021 | Elote
b0022 | Grilled corn, cotija, chile and lime.
b0023 | 5.25
Example output:
{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50","v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},{"b":"b0021","n":"Elote","p":"5.25"}]}]}
```

### `q9b2b` — sha256 `a0190deff53f3b5bed2ed8a093a72c68f8a9eaba04992f16a060c35568d52d2f`

```text
You extract restaurant menus. Input lines are 'BLOCK_ID | text' in page order. Return every menu item that is sold, grouped by the menu section it is under. Each item is {"b": block id where its name appears, "n": item name copied exactly as printed, "p": price copied exactly as printed, digits only (e.g. 12.50), "" if no price is printed for it, "v": size/variant word printed next to that price (e.g. "Large", "Glass"), only if there is one}. An item with several prices gets one entry per price. Many menus print one item over several lines: a short name line, then its price line and/or a description line, in either order. Those lines are ONE item: its name is the short name line (never the description sentence), its price comes from the price line after the name, and a price line or description line is never an item of its own. Do not invent items or prices, do not convert or compute prices, skip section headings, descriptions, navigation, hours, addresses, reviews and add-on/extra lines. If the text contains no menu items, return no sections. Read the text to its end and list every item in page order: short names in grids or cards, numbered combos and items printed several to a line all count. Do not stop early. Some menus print each item's price twice: just above its name and again after its description. An item's price is printed after its name and before the next item's name, or just above its own name; never take the price printed just above the next item's name. The same price printed above and after one item is one entry. Output compact JSON on a single line with no spaces or newlines. Example input:
b0011 | Tacos
b0012 | Carne Asada Taco | $3.50
b0014 | Horchata
b0015 | $2.50/Small
b0016 | $3.50/Large
b0017 | Sides
b0018 | CHIPS AND SALSA
b0019 | $4
b0020 | House-made chips, roasted tomato salsa.
b0021 | Elote
b0022 | Grilled corn, cotija, chile and lime.
b0023 | 5.25
Example output:
{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50","v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},{"b":"b0021","n":"Elote","p":"5.25"}]}]}
```

### `qkm2a` — sha256 `3ec12a2f047eff40dcb77a83b674b8ff8ff36d053fc33f80be312bba017370aa`

```text
You extract restaurant menus. Each input line is 'BLOCK_ID | text', in page order. List every item on sale, grouped under the menu section it appears in. For each item output {"b": the block id of the line with the item's name, "n": the item name exactly as printed, "p": the price exactly as printed, digits only (e.g. 12.50), or "" if no price is printed for it, "v": the size or variant label printed with that price (e.g. "Large", "Glass"), omitted if there is none}. If an item has several prices, output one entry per price. Copy names and prices from the text; never invent, translate, convert or calculate them. Do not output section headings, descriptions, navigation, opening hours, addresses, reviews, or add-on/extra lines as items. If there are no menu items, return no sections. When names and prices are on separate lines, take an item's price from the price line after its name and before the next item's name; a price line just above a name usually belongs to the item above it. Only when every item in a list prints its price first and its name second, take the price above. Never give an item the price of a neighbouring item. Use only a price printed for that item (on its name line, its price line or its size/price line); if none is printed, p is "". Never write 0, and never take a number from a name, date, time, size or phone number as a price. Output compact JSON on one line, without spaces or newlines. Example input:
b0011 | Tacos
b0012 | Carne Asada Taco | $3.50
b0014 | Horchata
b0015 | $2.50/Small
b0016 | $3.50/Large
b0017 | Sides
b0018 | CHIPS AND SALSA
b0019 | $4
b0020 | House-made chips, roasted tomato salsa.
b0021 | Elote
b0022 | Grilled corn, cotija, chile and lime.
b0023 | 5.25
Example output:
{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50","v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},{"b":"b0021","n":"Elote","p":"5.25"}]}]}
```

### `qkm3a` — sha256 `9bded611f6a307511f9a3a257dd2c74a8f0f3192e86b3db8ed1a6a8afb21fc5c`

```text
You extract restaurant menus. Each input line is 'BLOCK_ID | text', in page order. List every item on sale, grouped under the menu section it appears in. For each item output {"b": the block id of the line with the item's name, "n": the item name exactly as printed, "p": the price exactly as printed, digits only (e.g. 12.50), or "" if no price is printed for it, "v": the size or variant label printed with that price (e.g. "Large", "Glass"), omitted if there is none}. If an item has several prices, output one entry per price. Copy names and prices from the text; never invent, translate, convert or calculate them. Do not output section headings, descriptions, navigation, opening hours, addresses, reviews, or add-on/extra lines as items. If there are no menu items, return no sections. When names and prices are on separate lines, take an item's price from the price line after its name and before the next item's name; a price line just above a name usually belongs to the item above it. Only when every item in a list prints its price first and its name second, take the price above. Never give an item the price of a neighbouring item. Use only a price printed for that item (on its name line, its price line or its size/price line); if none is printed, p is "". Never write 0, and never take a number from a name, date, time, size or phone number as a price. A number inside an item or brand name (e.g. '7 Seas Lager', '3 Cheese Pizza') is part of the name, not its price. A price for an add-on, topping or extra is never the price of the item it is added to. Output compact JSON on one line, without spaces or newlines. Example input:
b0011 | Tacos
b0012 | Carne Asada Taco | $3.50
b0014 | Horchata
b0015 | $2.50/Small
b0016 | $3.50/Large
b0017 | Sides
b0018 | CHIPS AND SALSA
b0019 | $4
b0020 | House-made chips, roasted tomato salsa.
b0021 | Elote
b0022 | Grilled corn, cotija, chile and lime.
b0023 | 5.25
Example output:
{"sections":[{"section":"Tacos","items":[{"b":"b0012","n":"Carne Asada Taco","p":"3.50"},{"b":"b0014","n":"Horchata","p":"2.50","v":"Small"},{"b":"b0014","n":"Horchata","p":"3.50","v":"Large"}]},{"section":"Sides","items":[{"b":"b0018","n":"CHIPS AND SALSA","p":"4"},{"b":"b0021","n":"Elote","p":"5.25"}]}]}
```

## Archive (P5-22, 2026-10-19)

The gitignored scratch `var/menu-eval/prompt-opt/` is archived in `var/archive/2026-10-p5-19-21/` (main checkout, gitignored):

- manifest `p5-21-prompt-opt.manifest.json`, sha256 `ed06419d13bf6bcec656ab4d0c276c8112a99161f714be5bded6da14efeb6d97` (path, size and sha256 of every
  archived file; excluded model weights and vendor binaries with their size, sha256 and
  publisher pin; excluded environments and caches with file counts);
- tarball `p5-21-prompt-opt.tar.zst`, sha256 `e5ac73e73b16c43412894106e736df47e3a7f4c8c7bc5ed3500d9e4cf7ee3827`.

Model GGUFs, HF checkpoints, Python environments, caches and RKLLM vendor binaries are not
in the tarball; `SHA256SUMS` in the same directory lists both files and the archiving
scripts.
