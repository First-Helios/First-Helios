# DISC-01 Agent Brief

Updated: 2026-04-17
Task ID: `DISC-01`
Tier: 2
Status: ready

## Objective

Expand `_discover_deal_pages` to score footer links, promotions clusters, learn-more clusters, and likely first-party promo slugs so the scraper can reach hidden promo pages that are currently missed by shallow discovery.

## Why This Matters

The audit snapshot already shows a `discovery found candidates but no signal` bucket, and the broader review identified hidden first-party promo pages as an important missed-path class.

## Prerequisites

- Required: use replay bundles, not only live sites.
- Soft: start from the `AUD-01` baseline report.
- Preferred: use `AUD-02` manifests if available for discovery-miss bundles.

## Target Files

- `collectors/meal_deals/website_scraper.py`
- `tests/HeliosDeployment/` replay-driven tests

## Inputs

- replay bundles with zero-signal pages that still contain footer clusters or obvious promo-link patterns

## Deliverable

Improved discovery scoring for:

- footer promo links
- learn-more promo links
- promotions or offers nav clusters
- first-party stable promo slugs

## Acceptance Checks

- replay-tested on a named bundle set
- does not broaden into general crawling
- does not increase obviously wrong-target fetches
- surfaces before and after counts for discovered pages on the replay set

## Before Metrics

- no-deal sites with discovered pages in the current snapshot: 75
- successful sites with discovered pages are under-instrumented in the current audit JSON

## Non-Goals

- no renderer escalation
- no persistent menu graph work
- no broad sitemap crawler

## Escalate If

- correct discovery requires chain-specific hint rules better handled by `DISC-02`
- correct discovery appears blocked by JS rendering rather than missing links