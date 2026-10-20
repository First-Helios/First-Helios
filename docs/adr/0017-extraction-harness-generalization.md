# ADR-0017: Extraction harness generalization — invariance, multi-model acceptance, per-model configuration

**Status:** Proposed 2026-10-16 (session P5-20, for owner review). Nothing is built: no
tracked code changes until the owner accepts this ADR.
**Date:** 2026-10-16
**Phase:** 5 (menu pipeline)
**Extends:** [ADR-0013](./0013-phase5-menu-pipeline.md) §8 and Amendments 11 (keep rule),
15 (overfitting guard), 19 (production constraints, [5b], keep rule item 5)
**Evidence:** [P5-20 bracket screen](../reviews/2026-10-16-p5-20-bracket-screen.md)

## Context

Every part of the extraction harness was tuned on one model's answers: prompt v2.4, the
repairs (`rows_of`: stitch, variant cleanup, `split_listed`, `name_by_title`, diet marks),
validator v8 and [5b] `resolve-v1` were all fitted to Qwen3-4B-Instruct-2507 Q4_0 outputs on
the same seven tuning sets (ADR-0013 Amendments 9–19). P5-19 found that larger models lead on
raw recall but lose the lead after the harness. P5-20 measured where the fit sits:

- **Prompt fit is the largest effect.** A neutral rewrite of v2.4 (N1: same task spec,
  schema and example, minus the paragraph written against Qwen3-4B's multi-line errors) raised
  Qwen3.5-4B's raw usable prices on the FAST pages from 0.779 to 0.857 and Gemma-4-E4B's from
  0.847 to 0.876, and lowered the baseline from 0.757 to 0.730.
- **Repairs help the model they were written for.** On DEV, repairs added 36–38 correct
  (item, amount) pairs for the baseline (33 for its Q4_K_M quant) and 5–18 for other model
  families (P5-19's configurations) (they fix the baseline's own
  split-line errors; nothing is taken from other models).
- **Some decisions depend on output style, not page evidence.** An invariance suite (below)
  applied meaning-preserving changes to perfect gold output on 158 tuning pages (11,149 gold
  prices). Under the frozen v8 harness, writing the variant into the name lost 1,583 accepted
  prices, lower-casing names 339 (stitch reads the model's casing to spot description lines),
  claiming the description or price line instead of the name line 189 / 148 (the validator's
  fallback grounding walks forward into the next item), a generic or missing section label 8.
  Price forms (18.5 / 18.50 / $18.50), whitespace, empty vs missing variant and section
  casing were invariant.
- **Fixing the style dependence did not move real outputs.** A scratch prototype removed most
  flips (variant-in-name 1,583 → 275, lower case 339 → 1, claims 189/148 → 74/49) but changed
  real DEV usable prices by at most +12 pairs pooled over 17 model configurations and failed
  the acceptance rule below (leave-one-model-out folds at −1, or accuracy / wrong-accepted
  regressions). Today's models rarely write those styles; the rules are latent risk for the
  next model, not the cause of the measured gap.

Production has no labels (Amendment 19): a harness that silently depends on one model's
style turns a model upgrade into an unmeasured change in what gets stored.

## Decision

1. **Invariance principle.** Every repair, validator and [5b] decision depends on page
   evidence (block text, positions, printed prices and labels), never on a model's output
   style. Meaning-preserving variants of a correct row must reach the same decision:
   - block claim on any block of the item's span (name, description, price line);
   - price written 18.5 / 18.50 / $18.50;
   - letter case and whitespace of the name;
   - variant in the name ("Horchata Large", "Horchata (Large)") vs in `v`;
   - empty vs missing `v`;
   - section label casing, a generic label, or none.

   The invariance suite (perfect gold output, each variant applied page-wide, flips counted per
   rule) becomes a harness test run on the tuning pages. Its flip counts are recorded with
   every harness version; a change that adds flips is rejected; the current map (Context) is
   tracked as debt to pay down under item 2.
2. **Multi-model acceptance rule for harness changes** (adds to Amendment 11 and Amendment 19
   item 5). A repair, validator or [5b] change is kept only if, on the DEV pages:
   - pooled over the answers of every model configuration on record, usable prices rise;
   - no configuration regresses beyond the baseline's two-replicate noise band on price
     accuracy, accepted rows matching no label, or real wrong prices accepted;
   - leave-one-model-out: the change, decided on N−1 configurations, does not lower the
     held-out configuration's usable prices (every fold ≥ 0);
   - gold-row false reject and injected-corruption catch do not worsen;
   - the invariance suite gains no flips.

   No per-model or per-platform branches (owner rule).
3. **Per-model configuration menu.** A model is screened with a fixed, model-independent
   menu: decoding {greedy, the model card's recommended sampling with a fixed seed} × prompt
   {v2.4, N1, S1 = v2.4 + one generic worked example}. The configuration is chosen on DEV and
   confirmed on VAL. The prompt is part of the model's configuration (and of the pipeline
   version), not of the harness; a prompt is never tuned per model beyond this menu.
4. **Harness-free primary metrics for model choice.** Model comparisons are made on raw model
   rows before repairs, validator and [5b] (raw item recall, raw usable prices, raw price
   accuracy, unmatched rows per row, page-verbatim copy, schema/truncation), with the full
   pipeline numbers as secondary. §8 bars are unchanged and still gate a pipeline version.

## Alternatives considered

| Option | Pros | Cons |
|---|---|---|
| Keep single-model tuning (status quo) | No new process | A model change silently changes stored data; P5-19/P5-20 show the comparison is tilted |
| Adopt the P5-20 prototype changes now | Fewer style flips | Failed the multi-model rule on real outputs; no measured gain |
| Per-model repair branches | Fits each model | Forbidden (universal pipeline); multiplies production paths |
| Learned row classifier | Could absorb styles | Rejected by Amendment 19 item 6 (silent failure on new layouts) |

## Consequences

- Easier: model upgrades are judged on harness-free numbers; harness changes must hold across
  models, so the next model is not penalised for the last one's habits.
- Harder: every harness change needs answers from several models on DEV (GPU time) and a
  noise band; small wins that help one model and cost another are refused.
- Open: the invariance debt (variant in name, claim drift, casing) stays until a change passes
  item 2; whether to re-tune prompt v2.4 → N1 for the baseline is a model-configuration
  decision for the next tuning session, not part of this ADR.

## References

- [P5-20 review](../reviews/2026-10-16-p5-20-bracket-screen.md): protocol, invariance map,
  prototype results, leave-one-model-out folds, bracket screen.
- [P5-19 model screen](../reviews/2026-10-15-p5-model-screen.md) (formerly uncommitted in worktree
  `p5-19-model-screen`): harness-fit diagnostic.
- [ADR-0013](./0013-phase5-menu-pipeline.md) Amendments 11, 15, 19.
