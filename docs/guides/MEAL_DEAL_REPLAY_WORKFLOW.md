# Meal Deal Replay Workflow

Updated: 2026-04-17
Scope: replay-first workflow for website scraper audit, manifest generation, and targeted parser iteration

## Purpose

This guide documents the standard local workflow for analyzing and improving the meal-deal website scraper using synced cache artifacts instead of repeated live crawls.

Use this workflow when you need to answer questions like:

- which sites returned zero signals and why
- whether a parser change improves discovery or extraction
- which replay subsets should be handed to another agent
- which bundles should be used for JSON-LD, PDF, discovery, or wrong-target audits

## Required Local Inputs

The replay workflow depends on two synced artifact sets:

- `data/cache/website_scrape_audit.json`
- `data/cache/website_scrape_debug/`

Those artifacts are pulled from the Orange Pi by:

```bash
bash dev/sync_from_opi.sh
```

The sync script now also pulls:

- `data/cache/website_scrape_debug/`
- `data/cache/website_scrape_audit.json`

If you only want the database rows and not the replay cache, use:

```bash
bash dev/sync_from_opi.sh --skip-cache
```

## Step 1: Sync The Replay Corpus

Run:

```bash
bash dev/sync_from_opi.sh
```

Verify the debug bundle count:

```bash
find data/cache/website_scrape_debug -maxdepth 1 -type f | wc -l
```

## Step 2: Build A Baseline Audit Summary

Run:

```bash
python scripts/summarize_website_scrape_audit.py
```

Optional JSON output:

```bash
python scripts/summarize_website_scrape_audit.py --json
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

## Step 3: Build Replay Manifests

Run:

```bash
python scripts/build_website_scrape_replay_manifests.py
```

Optional smaller regression sets:

```bash
python scripts/build_website_scrape_replay_manifests.py --per-set 6
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

## Step 4: Select The Right Replay Set

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

## Step 5: Replay Extraction Locally

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

## Step 6: Compare Before And After

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
- `dev/sync_from_opi.sh`
- `collectors/meal_deals/website_scraper.py`