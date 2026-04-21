# Meal Deal Replay Workflow

Updated: 2026-04-21
Scope: replay-first workflow for website scraper audit, manifest generation, and targeted parser iteration

## Purpose

This guide documents the standard local workflow for analyzing and improving the meal-deal website scraper using synced cache artifacts instead of repeated live crawls.

For the short operator-only restart path, use [MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md](MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md). For the wider operations guide, use [MEAL_DEAL_SCRAPERS_RUNBOOK.md](MEAL_DEAL_SCRAPERS_RUNBOOK.md).

Use this workflow when you need to answer questions like:

- which sites returned zero signals and why
- whether a parser change improves discovery or extraction
- which replay subsets should be handed to another agent
- which bundles should be used for JSON-LD, PDF, discovery, or wrong-target audits

## Step 1: Sync The Replay Corpus

The replay workflow depends on two synced artifact sets:

- `data/cache/website_scrape_audit.json`
- `data/cache/website_scrape_debug/`

Sync them first:

```bash
bash dev/sync_from_opi.sh
```

If you only want the database rows and not the replay cache, use:

```bash
bash dev/sync_from_opi.sh --skip-cache
```

Verify the debug bundle count when needed:

```bash
find data/cache/website_scrape_debug -maxdepth 1 -type f | wc -l
```

## Step 2: Run The Pre-flight Gate Before A New Live Scrape

If you are preparing to restart a live website scrape, run:

```bash
PYTHONPATH=. .venv/bin/python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0
```

This validates:

- local scraper imports
- hint-registry load and active-hint count
- website-scrape target query health
- local cache path readiness
- optional remote SSH reachability if you pass `--remote-host`

## Step 3: Run A Dry-Run Canary Before Any Broad Scrape

After the script passes without blocking failures, run:

```bash
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --max-sites 5 --skip-checked-days 0 --dry-run --region austin_tx
```

Inspect the newest debug bundles for:

- `render_decisions` and `render_budget` on fetched first-party pages
- `menu_persistence_summary` when the canary actually materializes sidecar structure
- `hint_audit` when the canary reaches hint-driven exploration paths

If `menu_persistence_summary` is present, confirm `fk_violations == 0`. If a known menu-rich canary site still lacks it, treat that as a structure-coverage follow-up before widening the run.

Only begin a full live scrape after the canary bundles look correct.

## Step 3A: Use Replay As The Full Refresh Driver When Possible

Replay mode is not only for parser debugging. If the local debug corpus already covers the sites you care about, use replay to repopulate the canonical deal layers before you spend live crawl budget.

```bash
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --replay-debug-cache --all --skip-checked-days 0 --chunk-size 25 --region austin_tx
```

Important behavior:

- replay mode still writes through `ingest_deal_signals()` chunk by chunk
- this refreshes `deal_observations`, `deal_applicability`, and `deal_materializations` under current scraper logic
- this does not materialize the persistent menu tables by itself

If the rerun also needs the menu read path refreshed, follow the replay-backed scrape with:

```bash
PYTHONPATH=. .venv/bin/python scripts/backfill_menu_tables.py
PYTHONPATH=. .venv/bin/python scripts/audit_menu_price_index.py --region austin_tx --limit 20 --show-rows 5
```

If signal scoring or gate policy changed, also run:

```bash
PYTHONPATH=. .venv/bin/python scripts/reaudit_deal_observations.py --source website_scrape --backfill-source meal_deals --region austin_tx --apply
```

## Step 4: Build A Baseline Audit Summary

Run:

```bash
PYTHONPATH=. .venv/bin/python scripts/summarize_website_scrape_audit.py
```

Optional JSON output:

```bash
PYTHONPATH=. .venv/bin/python scripts/summarize_website_scrape_audit.py --json
```

What this gives you:

- success rate and outcome counts
- no-deal taxonomy
- domain-family counts
- shared-URL counts
- JSON-LD prevalence
- PDF prevalence
- page fetch-type counts

Use this output as the before-state baseline for any discovery or extraction change.

## Step 5: Build Replay Manifests

Run:

```bash
PYTHONPATH=. .venv/bin/python scripts/build_website_scrape_replay_manifests.py
```

Optional smaller regression sets:

```bash
PYTHONPATH=. .venv/bin/python scripts/build_website_scrape_replay_manifests.py --per-set 6
```

Generated outputs land in:

- `data/cache/website_scrape_manifests/summary.json`
- `data/cache/website_scrape_manifests/all_sites.json`
- `data/cache/website_scrape_manifests/regression_sets.json`
- `data/cache/website_scrape_manifests/by_outcome/`
- `data/cache/website_scrape_manifests/by_no_deal_stage/`
- `data/cache/website_scrape_manifests/by_domain_family/`
- `data/cache/website_scrape_manifests/categories/`

Important category files include:

- `categories/jsonld_present_but_zero_signal.json`
- `categories/pdf_present_but_zero_signal.json`
- `categories/content_seen_but_zero_signal.json`
- `categories/discovery_found_candidates_but_zero_signal.json`
- `categories/locator_page.json`
- `categories/social_or_non_first_party.json`
- `categories/static_empty_candidate.json`

## Step 6: Select The Right Replay Set

Use the manifests to match the task to the right subset.

Examples:

- `DISC-01`: start from `discovery_found_candidates_but_zero_signal`
- `DISC-02`: start from `locator_page`
- `JSONLD-01`: start from `jsonld_present_but_zero_signal`
- PDF improvements: start from `pdf_present_but_zero_signal`
- wrong-target audits: start from `social_or_non_first_party`
- renderer candidates: start from `static_empty_candidate`

For a smaller deterministic working set, use:

- `data/cache/website_scrape_manifests/regression_sets.json`

## Step 7: Replay Extraction Locally

Use replay mode instead of live fetches whenever possible.

At the Python level, replay uses the cached bundle for a site:

```python
from collectors.meal_deals.website_scraper import scrape_restaurant_website

signals = scrape_restaurant_website(
    url="https://example.com",
    restaurant_name="Example Bistro",
    local_employer_id=1,
    brand_group_id=None,
    region="austin_tx",
    replay_debug_cache=True,
)
```

This lets you iterate on parsing logic without re-hitting the live site.

## Step 8: Compare Before And After

After parser or discovery changes:

1. rerun the target replay subset
2. rerun the audit summary
3. compare category counts, discovered page counts, and signal counts
4. keep notes on which categories improved versus regressed

## Recommended Workflow By Task Type

### Discovery work

1. sync cache
2. summarize audit
3. generate manifests
4. work from `discovery_found_candidates_but_zero_signal` and `locator_page`
5. replay targeted bundles

### JSON-LD work

1. sync cache
2. summarize audit
3. generate manifests
4. work from `jsonld_present_but_zero_signal`
5. replay only structured-data bundles first

### PDF work

1. sync cache
2. generate manifests
3. work from `pdf_present_but_zero_signal`
4. keep scope limited to PDFs that are clearly relevant

### Wrong-target audits

1. sync cache
2. summarize audit
3. generate manifests
4. work from `social_or_non_first_party`

## Guardrails

1. Prefer replay bundles over live crawls.
2. Do not treat a cached locator page as proof that a site has no deals.
3. Do not broaden crawling scope beyond first-party restaurant assets without a scoped task.
4. Keep before-and-after counts for every discovery or extraction change.
5. Preserve the raw bundle evidence when adding new inferred structure.

## Related Tools

- `scripts/summarize_website_scrape_audit.py`
- `scripts/build_website_scrape_replay_manifests.py`
- `scripts/check_website_scrape_preflight.py`
- `dev/sync_from_opi.sh`
- `collectors/meal_deals/website_scraper.py`
- [MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md](MEAL_DEAL_SCRAPE_RESTART_CHECKLIST.md)
- [MEAL_DEAL_SCRAPERS_RUNBOOK.md](MEAL_DEAL_SCRAPERS_RUNBOOK.md)