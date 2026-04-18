# Meal Deal Remediation Tracker

Updated: 2026-04-18
Status: active tracker for website-scraper and canonical read-path remediation

## Purpose

This document is the live checklist for meal-deal failures that are being corrected now.

Use it to track three things together:

- the failure class being fixed
- the code or schema change intended to fix it
- the evidence used to prove the fix actually worked

Do not mark an item complete only because code merged. A remediation item is complete only when replay evidence, targeted tests, and read-layer behavior all agree.

## Completion Rule

Before closing any item in this tracker, record all of the following:

1. before-state evidence from replay bundles, manifests, or the expectation report
2. the code path changed
3. after-state evidence from the same replay set or expectation report
4. targeted tests added or updated
5. whether API or materialized rows now behave as intended

## Baseline Validation Commands

Run the relevant subset before and after each remediation:

```bash
bash dev/sync_from_opi.sh
PYTHONPATH=. .venv/bin/python scripts/check_website_scrape_preflight.py --region austin_tx --skip-checked-days 0
PYTHONPATH=. .venv/bin/python scripts/build_website_scrape_replay_manifests.py
PYTHONPATH=. .venv/bin/python scripts/compare_website_scrape_expectations.py --max-examples 10
.venv/bin/python -m pytest tests/HeliosDeployment/test_meal_deal_first_pass.py tests/HeliosDeployment/test_website_scrape_debug_cache.py tests/HeliosDeployment/test_meal_deal_quality_and_reaudit.py tests/HeliosDeployment/test_website_scrape_preflight.py tests/HeliosDeployment/test_meal_deal_target_export.py
```

Use additional focused replay tests whenever a fix changes extraction, ranking, or target admission behavior.

## Foundations Already Landed

- [x] Canonical venue and site identity layers exist and are wired into observations, applicability, and materializations.
- [x] Replay-first audit tooling exists: debug bundles, manifests, expectation report, pre-flight gate, and canary workflow.
- [x] Upstream menu structure exists in sidecar form: `menu_sidecar`, `menu_persistence_shape`, `offer_target`, and `value_profile` metadata.
- [x] Review queue write-backs can modify canonical site and alias state and refresh affected materializations.

These are not the active bottlenecks. The active work is correcting what still leaks through or surfaces poorly.

## Phase Board

| Phase | Focus | Status | Exit gate |
|---|---|---|---|
| Phase 1 | Target hygiene and reinfection barriers | Partial | Wrong-target and non-food sites no longer consume scrape budget, and repaired sample employers re-resolve cleanly. |
| Phase 2 | Current-source and canonical-row selection | Open | Current and specific offers outrank stale pages and broad summary rows on replay and API checks. |
| Phase 3 | Value-linked downstream ranking | Partial | `offer_target` and `value_profile` metadata influence ranking or explanation, not just bundle inspection. |
| Phase 4 | Rewards, birthday, loyalty, and app-gated offers | Planned | Gated offers are explicitly modeled and validated without promoting generic account or promo chrome. |

## Latest Validated Progress

- 2026-04-18: `TARGET-01` moved to partial. Hotel-family sites are now skipped before queueing, known non-restaurant hosts such as Circle K and autocare domains classify as `other_nonrestaurant`, and the target-export, audit-tools, and preflight regression tests all pass locally.
- 2026-04-18: `TARGET-01` repair-path wiring landed. `scripts/repair_restaurant_url_mismatches.py` now treats active skip-family restaurant URLs as actionable contamination, feeds them through the existing purge and recollect path, and `tests/HeliosDeployment/test_restaurant_url_repair.py` passes locally.
- 2026-04-18: `SOURCE-01` and `CANON-01` both moved to partial. `website_scraper.py` now annotates page and PDF signals with source provenance and date hints so newer PDF and discovered-page evidence sorts ahead of stale hardcoded HTML, and `routes.py` now orders materialized rows by specificity, `deal_value_score`, `signal_quality`, and recency instead of recency alone. Focused regressions plus `tests/HeliosDeployment/test_website_scrape_audit_tools.py` and `tests/HeliosDeployment/test_meal_deal_first_pass.py` all pass locally.

## Failure Tracker

| ID | Failure | Current root cause | Validation | Status |
|---|---|---|---|---|
| `TARGET-01` | Wrong-target queue contamination on first-party scrape targets such as hotel-family sites, Circle K, and obvious non-food businesses like Auto One Complete Car Care | Queue filtering and skip-family repair cleanup are now wired, but a live repair-and-recollect pass on sample contaminated employers is still pending | Run `scripts/repair_restaurant_url_mismatches.py --fix --recollect` on sample employers, rerun target export and manifests, and keep `tests/HeliosDeployment/test_meal_deal_target_export.py` and `tests/HeliosDeployment/test_restaurant_url_repair.py` green | Partial |
| `SOURCE-01` | Stale HTML pages can beat newer menu or PDF evidence, as seen on Good Luck Grill | Consolidation now prefers PDF and discovered-page provenance plus fresher source dates, but replay confirmation on cached first-party bundles still needs a refreshed bundle where current PDF artifacts are present | Replay the Good Luck Grill bundle after refreshing PDF cache coverage, verify current PDF or current-page evidence wins, and keep `tests/HeliosDeployment/test_website_scrape_source_precedence.py` green | Partial |
| `CANON-01` | Broad summary rows can surface instead of more specific sibling offers, as seen on Dog Haus and Green Mesquite | Materialized deal ordering now favors specificity and value ahead of pure recency, but site-level replay confirmation on known examples is still pending | Verify replay and API output prefer the targeted row on Dog Haus and Green Mesquite, and keep `tests/HeliosDeployment/test_materialized_deal_ordering.py` and `tests/HeliosDeployment/test_meal_deal_first_pass.py` green | Partial |
| `VALUE-01` | Item- or section-aware value evidence exists upstream but is not yet used consistently downstream | `offer_target`, `course_baseline`, and savings hints live in observation metadata, but ranking and explanation do not fully consume them | Confirm metadata survives ingest, verify ranking or explanation uses it, and capture before/after on Green Mesquite-style item offers | Partial |
| `DISC-03` | Hidden first-party promo pages are still under-discovered on footer-only promos, stable slugs, and scoped first-party sitemap paths | Initial promo-card and footer scoring landed, but bounded slug and sitemap probing are still open | Compare replay manifests before and after, especially `discovery_found_candidates_but_zero_signal`, and add focused replay tests | Open |
| `DOM-01` | Pages with useful menu structure still collapse into flat blocks and lose item-price relationships | `_extract_text_blocks()` still drops too much heading, sibling, list, and table context before later parsing stages can use it | Work from `content_seen_but_zero_signal` replay sets, add regression tests, and confirm improved item-price or heading-target pairing | Open |
| `RENDER-01` | JS-rendered menu pages remain static-empty even when discovery indicates the page matters | Render policy exists, but runtime Playwright escalation is not wired into `website_scraper.py` yet | Add bounded renderer integration, confirm `render_decisions` correspond to real escalation behavior, and verify targeted replay/live canaries | Open |
| `LOYALTY-01` | Rewards, birthday, loyalty, and app-only offers are under-modeled or filtered away | Rewards and app language is currently treated as boilerplate or non-deal discovery material, and there is no explicit qualification model | Add explicit gated-offer fields or metadata, validate against expectation cases, and ensure generic sign-in or account pages still fail safely | Planned |

## Core Evidence Set

Use these artifacts repeatedly while working the tracker:

- `data/cache/website_scrape_debug/goodluckgrill_com__293fac5a190c.json`
- `data/cache/website_scrape_debug/fourpoints_doghaus_com__8a4033ad0359.json`
- `data/cache/website_scrape_debug/greenmesquiteatx_com__f2dd30ae95bb.json`
- `data/cache/website_scrape_targets_austin_tx_full.csv`
- `data/cache/website_scrape_manifests/all_sites.json`
- `data/cache/website_scrape_manifests/by_outcome/deals_found.json`

## Update Template

Use this block when an item changes state:

```text
Date:
Remediation ID:
Before evidence:
Code and tests changed:
After evidence:
Residual risk:
Next follow-up:
```

## Current Working Order

1. `TARGET-01` first so the queue stops admitting obviously bad targets.
2. `SOURCE-01` and `CANON-01` next so current and specific offers actually surface.
3. `VALUE-01` after row selection can use the metadata already being preserved.
4. `DISC-03`, `DOM-01`, and `RENDER-01` in parallel where replay data shows the remaining recall gaps.
5. `LOYALTY-01` after the core first-party offer path is stable enough to support a new gated-offer family.
