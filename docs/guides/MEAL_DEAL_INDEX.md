# Meal Deal System — Navigator

Role-based entry points into the 8 meal-deal documents. Use this page to pick the right doc for your task rather than reading everything.

## By Role

| Role / Task | Start Here |
|---|---|
| **Operator** — run scrapers, troubleshoot a job, recover a failed scan | [MEAL_DEAL_SCRAPERS_RUNBOOK.md](MEAL_DEAL_SCRAPERS_RUNBOOK.md) |
| **Operator** — replay a site locally to debug extraction | [MEAL_DEAL_REPLAY_WORKFLOW.md](MEAL_DEAL_REPLAY_WORKFLOW.md) |
| **Operator** — pre-scrape go/no-go quick check | [MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md](MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md) |
| **Developer** — understand the canonical pipeline (signal → observation → applicability → materialization) | [../data/ingestion/MEAL_DEAL_INGESTION.md](../data/ingestion/MEAL_DEAL_INGESTION.md) |
| **Developer** — work on refinement logic (quality scoring, sub-deal decomposition, cleanup) | [MEAL_DEAL_SIGNAL_REFINEMENT.md](MEAL_DEAL_SIGNAL_REFINEMENT.md) |
| **Developer** — look up the menu-persistence shape and tables | [../data/ingestion/MENU_SIDECAR.md](../data/ingestion/MENU_SIDECAR.md) |
| **Architect** — review structural decisions and known gaps | [MEAL_DEAL_FOUNDATION_ASSESSMENT.md](MEAL_DEAL_FOUNDATION_ASSESSMENT.md) |
| **Agent** — find active work and open tasks | [MEAL_DEAL_REMEDIATION_TRACKER.md](MEAL_DEAL_REMEDIATION_TRACKER.md) + [MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md](MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md) |
| **Frontend / integrator** — current handoff notes | [../../agentMailbox/InteragentExchange/FPI-1_food_price_index_tab_handoff.md](../../agentMailbox/InteragentExchange/FPI-1_food_price_index_tab_handoff.md) |

## Canonical vs Active vs Archived

- **Canonical architecture:** [MEAL_DEAL_INGESTION.md](../data/ingestion/MEAL_DEAL_INGESTION.md) — single source of truth for the data model.
- **Active task trackers:** [MEAL_DEAL_REMEDIATION_TRACKER.md](MEAL_DEAL_REMEDIATION_TRACKER.md) and [MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md](MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md).
- **Archived:** [../archive/strategy-docs/MEAL_DEAL_ROADMAP.md](../archive/strategy-docs/MEAL_DEAL_ROADMAP.md) (phases 1-4 complete), [../archive/handoffs/FH-3_meal_deal_map_layer.md](../archive/handoffs/FH-3_meal_deal_map_layer.md), [../archive/handoffs/FH-4_meal_deal_data_upgrade_handoff.md](../archive/handoffs/FH-4_meal_deal_data_upgrade_handoff.md), [../archive/plans/plan-mealDealSignalQualityOverhaul.prompt.md](../archive/plans/plan-mealDealSignalQualityOverhaul.prompt.md).

## Script references (post-cleanup layout)

- Operational, kept at top level: `scripts/backfill_menu_tables.py`, `scripts/audit_menu_price_index.py`, `scripts/reaudit_deal_observations.py`, `scripts/reaudit_meal_deals.py`, `scripts/check_website_scrape_preflight.py`, `scripts/build_website_scrape_replay_manifests.py`, `scripts/summarize_website_scrape_audit.py`, `scripts/meal_deal_quality_dashboard.py`, `scripts/refresh_targeted_sites.py`, `scripts/compare_hintbook_to_deal_observations.py`, `scripts/compare_website_scrape_expectations.py`, `scripts/harvest_hintbook_from_spiritpool.py`.
- Completed migrations / backfills: `scripts/backfills/` (11 files).
- Destructive or source-initial-load only: `scripts/one_shot/` (15 files, including `reset_meal_deal_dataset.py`, `purge_junk_deals.py`, `cleanup_meal_deals.py`, `dedupe_chain_deals.py`).
