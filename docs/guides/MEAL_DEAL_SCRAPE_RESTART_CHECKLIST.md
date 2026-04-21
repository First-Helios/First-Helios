# Meal Deal Scrape Restart Checklist

Updated: 2026-04-21
Scope: short operator-only checklist for resuming or restarting website scraper runs after code, schema, or policy changes

Use this when you need the shortest safe path back to scraping. For the fuller context, use [MEAL_DEAL_SCRAPERS_RUNBOOK.md](MEAL_DEAL_SCRAPERS_RUNBOOK.md), [MEAL_DEAL_REPLAY_WORKFLOW.md](MEAL_DEAL_REPLAY_WORKFLOW.md), and [../data/ingestion/MEAL_DEAL_INGESTION.md](../data/ingestion/MEAL_DEAL_INGESTION.md).

## Standard Restart Order

1. Sync or deploy the current state.

```bash
cd /home/fortune/CodeProjects/First-Helios

# Local validation against production-like data and replay bundles
bash dev/sync_from_opi.sh
```

Remote note:

- if the next run is remote, confirm repo and overlay parity before trusting the host
- SSH reachability alone is not enough if required modules only exist locally

2. Apply migrations.

```bash
cd /home/fortune/CodeProjects/First-Helios
.venv/bin/alembic upgrade head
```

3. Run the pre-flight gate.

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0
```

Remote variant:

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0 --remote-host orangepi@192.168.1.191
```

4. Run a 5-site dry-run canary.

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --max-sites 5 --skip-checked-days 0 --dry-run --region austin_tx
```

5. Run a small targeted refresh when the change is discovery- or parser-only.

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python scripts/refresh_targeted_sites.py --ids 18354 7047 26123 3570 3063
```

Proceed only if the slice is net-positive on item and price-point coverage and shows no genuine regression on a known restaurant.

6. Inspect the newest bundles before any broad live run.

Required on fetched first-party pages:

- `render_decisions`
- `render_budget`

Conditional checks:

- if `menu_persistence_summary` is present, `fk_violations` must be empty
- if hint-driven exploration was used, confirm `hint_audit` is present
- if a known menu-rich canary still lacks structure, treat that as a follow-up before widening the run

7. Prefer a replay-backed full run before a fresh live crawl when cache coverage is already sufficient.

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --replay-debug-cache --all --skip-checked-days 0 --chunk-size 25 --region austin_tx
```

8. Only fall back to a fresh live scrape if replay coverage is too sparse.

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --all --skip-checked-days 0 --chunk-size 25 --region austin_tx
```

9. Re-audit canonical observations only if quality rules or gating logic changed.

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx --apply
```

10. Backfill menu tables and audit the menu read path when Price Index or other menu consumers are in scope.

```bash
cd /home/fortune/CodeProjects/First-Helios
PYTHONPATH=. .venv/bin/python scripts/backfill_menu_tables.py
PYTHONPATH=. .venv/bin/python scripts/audit_menu_price_index.py --region austin_tx --limit 20 --show-rows 5
```

11. Verify the run after it starts or completes.

```bash
curl -k "https://127.0.0.1/api/deals?region=austin_tx&limit=5"
curl -k "https://127.0.0.1/api/deals/stats?region=austin_tx"
curl -k "https://127.0.0.1/api/price-index?region=austin_tx&limit=5"
curl -k "https://127.0.0.1/api/price-index/facets?region=austin_tx"
```

Also inspect:

- the newest `data/cache/website_scrape_debug/*.json` bundles
- `data/cache/website_scrape_audit.json`
- `/api/deals`, `/api/deals/stats`, and `/api/deals/brands`
- `/api/price-index` and `/api/price-index/facets`
- if deployed code changed on Orange Pi, restart both `helios` and `helios-collector`

## Go / No-Go Rules

- Go only if the pre-flight gate has no blocking failures.
- Go only if the canary bundles show `render_decisions` and `render_budget` on fetched first-party pages.
- Go only if any present `menu_persistence_summary` has `fk_violations == []`.
- Go only if `scripts/backfill_menu_tables.py` completes without failures when menu tables are part of the rerun goal.
- No-go if remote code parity is uncertain.
- No-go if the target queue is dominated by wrong-target domains and scrape budget is tight.

## Current Open Caveats

- `RENDER-01` is still open. Render-policy decisions are logged, but runtime Playwright escalation is not wired yet.
- Structured menu artifacts are still sidecar-first. They live in replay bundles and signal metadata, not DB tables.
- Remote parity on Orange Pi is still a manual operational step.