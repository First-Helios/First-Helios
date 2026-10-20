# P5-19 to P5-22 findings: integration register

Session P5-23, 2026-10-19/20. This turns the model, harness and Pi-cost findings of
P5-19 to P5-22 into actions on the development path, records the owner's decisions on
them, and hands core development (v9, then the §8 draw) to P5-24.
**Register and decisions only:** no pipeline change, no model run, no held-out draw.

Sources, all on `main` at `33f2732` unless noted:
[P5-17 false-reject structure](./2026-10-15-p5-false-reject-structure.md),
[P5-19 model screen](./2026-10-15-p5-model-screen.md),
[P5-20 bracket screen](./2026-10-16-p5-20-bracket-screen.md),
[P5-21 per-model prompts](./2026-10-16-p5-21-per-model-prompts.md),
[P5-21 H4 and TEST3](./2026-10-17-p5-21-harness-h-test3.md),
[P5-21 closeout and Pi cost](./2026-10-18-p5-21-closeout-pi-cost.md),
[ADR-0013](../adr/0013-phase5-menu-pipeline.md) §3, §8, Amendments 6, 8 and 19,
Amendment 20 (Proposed, draft PR #91),
[ADR-0017](../adr/0017-extraction-harness-generalization.md) (Proposed).
P5-18's numbers come from branch `worktree-p5-18-pipeline-v9` (`b4b0e2e`) and its
gitignored scratch `var/menu-eval/p5-18/`, which has no review record yet.

Every number below was checked against its source; the P5-23 session brief's summary
was not trusted on its own. Where they disagree, the source wins and the row says so.

## Drift found while verifying

| | Brief said | Source says | Effect |
|---|---|---|---|
| D1 | `main` = 33c77fb; #90 open | #90 merged 2026-10-20 01:57Z; `main` = `33f2732` | Q1's "merge #90" is moot. #91's base is `main`; its diff against `main` is ADR-0013 only |
| D2 | TEST pages average ~8.3 chunks | The 218 tuning pages average **8.5** (median 5, max 99). The laptop pass's corpus averages **7.0** (below) | F8 and F10 use these |
| D3 | Pi scratch `~/p520-*` ≈ 25 GB | `~/p520-pi` 15 GB, `~/p520-npu` 5.0 GB; also `~/p5-13` 2.6 GB, `~/p5-14` 12 KB, `~/p521-closeout-perf-20261018` 272 KB. Pi disk 38 % used | Pi cleanup is not urgent |
| D4 | C2 (numbers in names): +77 gold, 12 unmatched real | +77 gold, 48 real exact, **12 unmatched and 4 wrong** real rows (`candidates/*.json`, summed) | As measured, C2 fails Amendment 19 item 5 (no rise in accepted-unmatched) |
| D5 | F9: the 9B's numbers are at 6,144 per slot | Also: P5-19 found the **production slot too small for the primary**. Max rendered retry prompt + full token cap = 4,679 tokens (P5-14 page `77796540a06c`) against 4,096 per slot | Q5 is a correctness question, not only a parity one |
| D6 | F12: lower the pause to ~85 °C | P5-21 ran at 86–87 °C under load all session with 0 faults for hours; P5-19's 86/72 guard paused five times in one model run before the airflow stand | An 85 °C pause would fire continuously |
| D7 | F14: ~55 merged worktrees can go | The live tuning corpus is in merged worktrees' gitignored `var/` (below, F18) | Deleting them as-is destroys the tuning labels and the draw's exclusions |
| D8 | Amendment 20 item 6: "At §3's first-pass size (~2,300 menu pages)" | The first pass runs on the laptop (Amendment 8 item 1); the corpus is 886 distinct page texts | Fix in #91 when it is accepted |

## Integration register

Dispositions: **adopt** (take as is), **port** (bring code into the repo), **defer** (keep
the evidence, act later on a named trigger), **drop** (no action, with reason).
"Q" refers to the owner questions below.

| # | Finding (source, section) | Evidence (verified) | Integration action | Owner decision | Disposition |
|---|---|---|---|---|---|
| F1 | Gold-row FR binds §8 and is a validator / [5b] property, not a model property (P5-17 §Findings 1, table "today vs oracle") | 1,465 of 1,523 gold rejects (96 %) are no-price-match downgrades; oracle second pass FR 0.096 → 0.004, usable 0.780 → 0.818; 15,898 gold rows on 218 pages | None new: v9 [5b] (Amendment 19 items 3–5) is the path | none | **Adopt.** No model choice moves FR |
| F2 | Primary stays Qwen3-4B-Instruct-2507 Q4_0 (P5-19 result; P5-20 §B4, §6; P5-21 TEST2; TEST3 table) | P5-19 retains; B4 inconclusive twice; Q4_K_M usable Δ −0.0060…−0.0085, fails S1/S2 on TEST3; NPU W8A8 6.5 vs 10.4 pages/h, raw usable 0.761 vs 0.844 on 3 pages | None. ADR-0013 §3 (CPU only) and Amendment 6 stand | owner 2026-10-19 (P5-22) | **Adopt** (no change). NPU dropped |
| F3 | P5-18's v9 numbers stay valid because the primary is unchanged (P5-18 memory; `score-r3/*.log`) | resolve-v1: P5-16 FR 0.1339 → 0.1255; pooled 1,503 / 15,898 = 0.0946; 0 real accepts by [5b] | Resume v9 on the saved Q4_0 answers (Part 3) | none | **Adopt** |
| F4 | H4: drop a description row when a nearby row names its short title (TEST3 §H4 development acceptance; closeout) | DEV +141 pooled usable over 17 configs, 17/17 gain, accepted-unmatched falls in all 17; all 17 LOMO folds and 9 grouped-model folds pass; FR / catch unchanged (68-page gold pool FR 0.148, catch 0.992); 0 added invariance flips. TEST3 baseline usable 0.7825 → 0.7838 (A), 0.7844 → 0.7849 (B); +2 correct prices for the 9B | Port as one function in `packages/helios_parsing/output.py` with unit tests, from `var/menu-eval/prompt-opt/hh/output.py` (archived in `p5-21-prompt-opt.tar.zst`); run the Amendment 19 keep rule on v9 | Q2 (needs ADR-0017 item 2) | **Port**, if Q2 accepts item 2 |
| F5 | Invariance suite (ADR-0017 item 1; P5-20 §invariance) | Frozen v8 on perfect gold output, 158 pages / 11,149 prices: variant in name −1,583 accepted prices, lower case −339, claim on description / price line −189 / −148, generic section −8 | Port as a harness test (flip counts recorded per harness version) | Q2 | Decided by Q2 |
| F6 | Harness-free raw metrics; per-model configuration menu (ADR-0017 items 3–4) | Only used to compare models | None now | Q2 | **Defer.** Trigger: a new model comparison, which the owner has ruled out for now |
| F7 | Qwen3.5-9B fallback (Amendment 20, #91; TEST3 tables) | 9B on every TEST3 page through H4: usable 0.8201 vs 0.7825 / 0.7844 → +138 / +131 of 3,664, CIs [+0.0075, +0.0702] / [+0.0080, +0.0641], 5/6 sets; S2–S4 pass. Raw accuracy 0.9260 vs 0.9396 / 0.9404 (accepted-row accuracy 0.9880). Routing R1–R3 registered 2026-10-17, `routing.md` sha256 `520be0be…4ada` (re-hashed from the p5-21 worktree; archived), never scored | Scored 2026-10-20 as registered ([record](./2026-10-20-p5-23-fallback-routing.md)): DEV chooses R2 (+2 pooled), VAL fails it (accuracy and wrong-accepted above a zero band) | Q3: accepted, R2 allowed | **Drop: no fallback ships** (Amendment 20 item 5); v9 is primary-only |
| F8 | Pi cost of the 9B (closeout §Pi performance test) | 3 pages / 9 chunks: 4B 17.15 min, 10.49 pages/h, 3.20 GiB, 72.1 °C; 9B 32.06 min, 5.61 pages/h, 5.65 GiB, 88.6 °C; extra 9B pass 1.87×; 30 % share → 6.72 pages/h (same-page-mix projection). Per chunk on 2 slots: 4B 114 s, 9B 214 s. The probe pages have 3 chunks each; tuning pages average 8.5 | Restate cost per chunk in #91 item 6; the first pass is on the laptop GPU (Amendment 8), so Pi cost lands on monthly change-only volumes only | Q3 | **Adopt** as a cost basis (recorded, not gated) |
| F9 | Context drift (Amendment 6 item 6; v8 held-out record; P5-19 §budget; closeout) | Compose `--ctx-size 8192` (4,096 per slot); v4–v8 §8 runs and every saved tuning answer at 8,192. P5-19 to P5-21 and both Pi probes at 12,288. P5-19: max retry prompt + cap 4,679 > 4,096 (D5). Saved tuning answers record 2 `length` finishes in 1,853 chunks (most records keep only `raw`). The Pi 4B probe at 12,288: 10.49 pages/h, 3.20 GiB | Per Q5; any primary change is an Amendment 6 flag change, recorded in Amendment 21 | Q5 | Decided by Q5 |
| F10 | §3's first-pass estimate is stale (§3 "Where it runs"; Amendment 8 item 1) | §3: ≈12 days for ~2,300 pages at 7.8 pages/h (spike). Laptop pass corpus, chunked from the 893 `var/replay/menu-page` bundles: **886 distinct page texts, 6,194 chunks** (mean 7.0, median 5, p90 15, max 99). Extraction answers are cached by text hash, so Versions sharing a text are extracted once. Pi primary at 114 s/chunk ≈ 197 h (≈ 8.2 days) | Docs PR: §3 note and README gate text (first pass on the laptop; Pi cost per chunk) | none (docs drift) | **Adopt** (docs only) |
| F11 | Eval robustness (TEST3 §Recovery incidents) | The P5-21 TEST3 wrapper printed success on a failed job; the 9B hit a llama.cpp grammar-state HTTP 500 at 20/45 pages. In-repo check: `evaluate extract` raises `ChunkFailed` after one retry (non-zero exit) ✓; production `extraction.py` counts `chunk_failed` and skips the page ✓. But `evaluate compare` (and v9's `report`) silently score only pages with output: they print `pages=N (of M gold)` and continue | v9 branch: `compare` / `report` refuse when output pages < gold pages. Fallback client (P5-24): HTTP 5xx or `ChunkFailed` on a routed page keeps the primary page and records the failure (Amendment 20 item 4 already says so) | none | **Adopt** |
| F12 | Laptop GPU faults (P5-19 §Execution notes; P5-20 §thermal; P5-21 §GPU) | Xid 62 + 45 at 89 °C (P5-19, P5-20, full-chip reset, reboot); Xid 13/43 at 86 °C (P5-21, no reset). Guard 93/78 °C: 0 pauses after the airflow stand; P5-21 sat at 86–87 °C; its guard log has only a start line | Per Q8. GPU work left in P5-24: the §8 draw (35 pages, both models if A20 ships) and the laptop first pass (6,194 chunks) | Q8 | Decided by Q8 |
| F13 | Labels: labels-v9 confirmed (P5-18); Amendment 19 item 2 | 107 "+$" rows → modifiers, 6 inferred variants dropped, 3/6 kept; list rule 0 changes | None | owner (P5-18) | **Adopt** (no action) |
| F14 | Housekeeping (P5-22; inventory this session) | 64 worktrees; p5-19 / 20 / 21 = 2.9 + 39 + 15 GB (duplicate GGUFs; reviews uncommitted there are older drafts of what is on `main`); archive re-verified this session (`verify_archive.py`, `sha256sum -c` all 8 OK). Laptop disk 92 %, 79 GB free | Per Q1, after F18 | Q1 | Decided by Q1 |
| F15 | Prompt v2.4 is fitted to Qwen3-4B (ADR-0017 Context; P5-21 VAL) | N1 lowers the baseline FAST 0.757 → 0.730; q9b3c +0.031 raw usable on VAL with accuracy −0.011 | None. Keep v2.4 for both models | owner (no more prompt search) | **Drop** |
| F16 | Gemma-4-E4B (TEST3) | Top H4 usable 0.8256; accepted-unmatched 0.0652 vs 0.0563 / 0.0597, fails S2 | None | owner | **Drop** |
| F17 | #90 merged; #91 stacked on its pre-squash commit (D1) | `origin/main` 33f2732 | Rebase #91 on `main` (a no-op diff) when its status changes | none | **Adopt** |
| F18 | The tuning corpus and the draw's exclusions live only in merged worktrees' gitignored `var/` (D7) | `tune/` (spike, P5-5, P5-8, P5-10, P5-12; 172 MB) in `p5-13-pipeline-v7` (#84); `p5-14/`, `p5-15/`, `p5-16/` (54 MB) in `p5-14-v7-held-out` (#88), including **`next-draw-exclusions-p5-17.json`, sha256 `dd748ff5…`** (the seed-20261015 draw's exclusions, no other copy); labels-v9 in `p5-18-pipeline-v9`; older held-out sets in `p5-8`, `p5-10`, `p5-12`, `p5-7`, `p5-9`, `p5-11` | Consolidate into the main checkout's `var/menu-eval/corpus/` with a manifest and `SHA256SUMS`, repoint the v9 symlinks, verify, then delete | Q1 | **Adopt** before any delete |
| F19 | Leftovers outside the P5-19–21 scratch (inventory) | `p5-6-menu-commit-cost`: a staged, never-merged migration `4b8d2f6a1c93` (the shipped fix is `db40e9424cba`); nested detached worktree `ci` inside the p5-19 scratch; 20 stopped Docker containers (P5-9 to P5-19 runs, 5-month-old `helios-s13-*`) | Remove with Q1's deletes | Q1 | Decided by Q1 |
| F20 | Draw readiness gap (P5-18 `candidates/`; Amendment 19 item 7) | Pooled FR 0.0946. C3 (own-line labels) +123 gold, 2 real exact, 0 junk → **0.087**. C2 +77 → 0.082 if it passed, but it fails item 5 as measured (D4). C1 +126 with 35 unmatched, 38 wrong, 24 corruptions: junk-heavy. 0.05 needs ≈ 795 gold rejects, ≈ 700 fewer than today | Decide the contingency now | Q6 | Decided by Q6 |

## Non-model blockers for the first real extraction

These run in parallel with v9 and are owner-run.

| Blocker | Gates | State | Next owner step |
|---|---|---|---|
| Pi gate 1a corrections and re-audit | Pi runs only (Amendment 8 item 1) | `config/identity_corrections.yaml` has 11 pending entries needing Pi-only GERS ids | `--show-gers` on the Pi, fill entries, authorized corrections run, fresh 100-row re-audit |
| Pi gate 1b render measurement and run authorization | First Pi `resolve_urls` | laptop measurement recorded; Pi measurement not run | Run the [Pi measurement](./2026-09-29-s6f-render-measurement.md#pi-measurement-owner-run), then authorize |
| `llama-server` image Pi check (Amendment 6 item 1) | First Pi extraction | pending | Run the [image check](./2026-09-29-llama-server-pi-check.md) |
| Laptop → Pi data path (Amendment 8 item 1) | Pi serving of the laptop first pass | undecided | Decide before the first pass's results need serving; not a §8 blocker |

None of these gates the laptop first pass; §8 does.

## Owner decisions (2026-10-20)

Asked in two batches after the background above; the recommended option was listed first.

| | Question | Answer | Effect on the register |
|---|---|---|---|
| Q1 | Archive and cleanup (#90 already merged, D1) | **Delete T1, T2, T3; keep T4.** T1: the p5-19 / p5-20 / p5-21 worktrees and the nested `ci` worktree, after an archive re-check. T2: worktrees of merged PRs, only after F18's consolidation is hash-verified. T3: `p5-6-menu-commit-cost` and the 20 stopped containers. T4 (Pi scratch) stays | F14, F18, F19 |
| Q2 | ADR-0017 | **Accept items 1–2; defer items 3–4** | F4 port; F5 port as a harness test; F6 deferred. Item 2's multi-model rule also gates v9's [5b] resolvers (scored on the archived DEV answers, no GPU) |
| Q3 | Amendment 20, and R2 under Amendment 19 item 6 | **Accept, R1–R3 including R2.** R2 is a label-free choice between two pages that the same validator grounds; it is not an acceptance authority. The guards on accepted-unmatched and wrong-accepted rows bind | F7: score as registered (separate record) |
| Q4 | Usable-price bar (Amendment 19 item 1(d)) | **≥ 0.74**, gated from the next §8 evaluation, on the configuration under §8 (routed if a fallback ships). At today's v9 pool (0.780) a 35-page draw clears it ~84 % of the time | Readiness for the draw must account for it |
| Q5 | Context | **Both services at 12,288 (6,144 per slot).** Removes the primary's 4,679-token overflow (D5); the Pi 4B was measured there. An Amendment 6 flag change, built in P5-24 with the fallback's Compose service | F9 |
| Q6 | FR contingency | **Resolvers, budgeted, then re-plan.** Mine more generic [5b] resolvers from the P5-17 / P5-18 class tables, each under Amendment 19 item 5 and ADR-0017 item 2. Stop when the next candidate class gains fewer than 25 gold rows with 0 junk, or at the end of P5-24's resolver block. If pooled FR is then not near 0.05, stop and re-plan with the owner; no early draw | F20 |
| Q7 | Owner-run Pi track | **Image check → gate 1b → gate 1a**, in parallel with P5-24, all before Phase 6. The image check runs with the 12,288 flags | Non-model blockers |
| Q8 | Laptop GPU guard | **Keep 93 / 78 °C.** Runs stay resumable by page | F12 |
