# Qwen3.5-9B fallback routing: DEV choice and VAL confirmation (ADR-0013 Amendment 20)

Session P5-23, 2026-10-20. The owner accepted Amendment 20 (with R2 allowed under
Amendment 19 item 6) and ADR-0017 items 1–2; see the
[findings register](./2026-10-20-p5-23-findings-integration.md). This record scores the
routing policies registered on 2026-10-17, exactly as registered.
**No inference:** saved laptop-GPU answers only, scored on the CPU.

## Result

**R2 is chosen on DEV and fails VAL, so no fallback ships.** Per Amendment 20 item 5, v9
continues primary-only, and no other trigger is designed in its place. There is no
re-selection: R1's better VAL and TEST3 numbers below are descriptive and change nothing.

| Policy | DEV pooled usable gain (A + B) | DEV guards | DEV | VAL (R2 only confirms) |
|---|---:|---|---|---|
| R1 | −3 (−3, 0) | pass | not eligible (gain ≤ 0) | — |
| **R2** | **+2 (+1, +1)** | pass | **chosen** (only eligible policy) | **fails:** both replicates exceed the VAL band on price accuracy and wrong-price-accepted |
| R3 | −4 (−4, 0) | pass | not eligible | — |

## Protocol

- Registration `var/menu-eval/p5-22-heldout/protocol/routing.md`, sha256
  `520be0be8682ca5ef59be0ad84cb9588f282f3595df93821e1dc27648d814ada` (checked by the
  scorer; archived in `p5-21-prompt-opt.tar.zst`). Unchanged.
- Splits: DEV and VAL from `splits-p520.json` (sha256 `5630f78d…23d7`, as registered),
  15 pages each, cap ⌊0.30 × 15⌋ = 4. TEST3 from `splits-p521b.json` (`17e0965a…843d`), 45 pages,
  cap 13.
- Harness: H4 (`HH=H4`) over the P5-21 frozen tracked code (`b4b0e2e`), labels-v9, which is
  the same scorer as the TEST3 record.
- Signals (label-free): printed = `price_tokens` count over the page's blocks;
  accepted = H4 verdicts `accept` with a price; coverage = accepted / printed;
  bad = any kept chunk failing the P5-19 schema check or finishing `length`.
- Two phases. Phase 1 computes every route from signals only and writes `routes.json`.
  Phase 2 then reads labels and scores.
  - A label-free dry run of phase 1 before scoring produced the same `routes.json` hash.
- Scratch, gitignored: `var/menu-eval/p5-23/` with `route_eval.py`, `show_verdict.py` and
  `routing/{routes,verdict}.json`. The hashes are listed under Artifacts.

**Deviation, disclosed before scoring.** Amendment 20 item 5 names the primary replicates
`p521-q3-4b-2507-q40__g-v24` / `__g-v24-b`, but those tags hold only TEST3 answers.
The only saved greedy prompt-v2.4 Q4_0 answers on DEV and VAL are P5-19's
`screen-baseline-a` / `-b`. These are the pair P5-21's `bands.py` uses for the "H4 DEV
A/B band" that the registration's keep rule cites. The fallback on DEV and VAL is
`p520-q35-9b__g-v24`, the only saved 9B g-v24 answers there; TEST3 uses `p521-*`.
This is a data mapping, not a change to any rule.

## DEV (chooses)

Baseline H4: A 766 / 964 (usable 0.7946), B 789 / 964 (0.8185). A/B band: accuracy
0.0015, accepted-unmatched / row 0.0048, wrong-accepted / row 0.0007.

| Policy | Replicate | Routed | Used | Usable gain | Accuracy | Unmatched / row | Wrong / row |
|---|---|---:|---:|---:|---:|---:|---:|
| R1 | A | 4 | 4 | −3 | 0.9898 | 0.0392 | 0.0060 |
| R1 | B | 4 | 4 | 0 | 0.9901 | 0.0409 | 0.0060 |
| R2 | A | 4 | 1 | +1 | 0.9849 | 0.0395 | 0.0086 |
| R2 | B | 4 | 1 | +1 | 0.9865 | 0.0442 | 0.0080 |
| R3 | A | 1 | 1 | −4 | 0.9861 | 0.0408 | 0.0083 |
| R3 | B | 0 | 0 | 0 | 0.9864 | 0.0442 | 0.0081 |

Fallback generated tokens on routed pages, both replicates: R1 / R2 16,064, R3 2,408.

## VAL (confirms R2 once)

Baseline H4: A 852 / 1,129 (0.7547), B 847 / 1,129 (0.7502); accuracy 0.9966 and
wrong-accepted / row 0.0023 on both. The two replicates agree on those metrics, so the
registered band is **0** there, and any regression fails.

| Replicate | Routed | Used | Usable gain | Accuracy | Wrong / row | Unmatched / row | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|
| A | 4 | 3 | +38 | 0.9956 | 0.0030 | 0.0689 | fails accuracy and wrong-accepted |
| B | 4 | 2 | +29 | 0.9956 | 0.0031 | 0.0853 | fails accuracy and wrong-accepted |

R2 raises usable prices on VAL but stores more wrong prices. Under the registered rule
that is a fail. The zero band is strict, and it was the registered rule.

## Descriptive only (no decision rests on these)

| Split | Policy | Gain A / B | Routed A / B | Guards |
|---|---|---|---|---|
| VAL | R1 | +36 / +38 | 4 / 4 | pass |
| TEST3 | R1 | +16 / +23 | 11 / 8 of 45 | pass |
| TEST3 | R2 | +29 / +34 | 11 / 8 (used 6 / 3) | A fails accepted-unmatched (0.0614 vs 0.0563 + 0.0035) |
| TEST3 | R3 | 0 / 0 | 0 / 0 | — |

TEST3 baselines reproduce the TEST3 record: 2,872 and 2,876 of 3,664 (0.7838 / 0.7849).
The routed pages are a small sample on DEV and VAL (≤ 4 per replicate), as Amendment 20
warned. The 9B gain measured with the 9B on every page (+131/+138 on TEST3) did not
survive a label-free trigger on DEV.

## Consequences

- No fallback manifest entry, Compose service or two-phase CLI is built. The P5-24 plan
  drops that step.
- No Pi timing run of routed pages is proposed.
- The 9B GGUF and pins stay recorded in the P5-21 archive manifest. No copy is kept in
  `var/models/`.
- §8 for v9 is primary-only. The context decision (both services at 12,288, owner Q5)
  still applies to the primary: it removes the 4,679-token overflow.
- Reopening a fallback would need a new registration before any score. Under the owner's
  "no more screening" rule there is none.

## Artifacts

| File | sha256 |
|---|---|
| `routing/routes.json` | `e2bb3edac3db46548416c934ea4b7eedcc72a727ea686041e0235aafbc4bab75` |
| `routing/verdict.json` | `3255f2cc901312ce2785d975173571d4e313b8a0b4771e4d266d19f571289a69` |
| `route_eval.py` | `ccd0ef64e034e0be1a1f12db0fe34335366c0aac738e4fdf0c4d202a0ac33668` |
