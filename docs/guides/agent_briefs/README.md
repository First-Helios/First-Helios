# Meal Deal Scraper Wave 1 Agent Briefs

Updated: 2026-04-17
Scope: first recommended assignments from the meal-deal scraper signal refinement roadmap

These briefs are the execution pack for Wave 1 of the website-scraper refinement work.

Use them alongside:

- [../MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md](../MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md)

Wave 1 brief set:

- [MEAL_DEAL_AUD_01_BRIEF.md](MEAL_DEAL_AUD_01_BRIEF.md)
- [MEAL_DEAL_AUD_02_BRIEF.md](MEAL_DEAL_AUD_02_BRIEF.md)
- [MEAL_DEAL_AUD_03_BRIEF.md](MEAL_DEAL_AUD_03_BRIEF.md)
- [MEAL_DEAL_DISC_01_BRIEF.md](MEAL_DEAL_DISC_01_BRIEF.md)
- [MEAL_DEAL_DISC_02_BRIEF.md](MEAL_DEAL_DISC_02_BRIEF.md)
- [MEAL_DEAL_JSONLD_01_BRIEF.md](MEAL_DEAL_JSONLD_01_BRIEF.md)

Dependency notes:

1. `AUD-01` has no hard prerequisite beyond the synced audit JSON and replay bundles. It is implemented locally and can be used immediately as a baseline artifact.
2. `AUD-02` and `AUD-03` can run in parallel, but both should reuse the current `AUD-01` terminology where possible so the audit outputs stay comparable.
3. `DISC-01` and `DISC-02` do not have hard code prerequisites, but they should consume the `AUD-01` baseline and preferably the `AUD-02` manifests once they exist.
4. `JSONLD-01` can start immediately, but it benefits from an `AUD-02` subset of `JSON-LD present but zero-signal` pages once that manifest exists.