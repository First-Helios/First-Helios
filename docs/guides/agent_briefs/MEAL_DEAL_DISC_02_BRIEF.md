# DISC-02 Agent Brief

Updated: 2026-04-17
Task ID: `DISC-02`
Tier: 2
Status: ready

## Objective

Add locator-to-corporate promo hint routing for common chains so location pages can trigger targeted probes of the corporate promo site when the deal content does not live on the locator page itself.

## Why This Matters

The replay snapshot includes obvious misses on locator pages where the real deal page is on the chain’s main corporate domain or promotions hub. This is likely one of the cheapest recall wins.

## Prerequisites

- Required: replay evidence from locator-style misses.
- Soft: start from the `AUD-01` baseline report.
- Preferred: use `AUD-02` manifests if available for locator pages.

## Target Files

- `collectors/meal_deals/website_scraper.py`
- replay-driven tests under `tests/HeliosDeployment/`

## Inputs

- locator-page misses such as chain location subdomains or `/locations/` page patterns

## Deliverable

Targeted corporate hint rules for locator families, including examples like:

- `locations.brand.com/...` to corporate promotions hub
- obvious locator paths that should probe chain-level deals or offers pages

## Acceptance Checks

- rules are scoped to specific locator patterns
- replay-tested on named chain examples
- does not cause broad off-domain crawling
- clearly records what corporate pages were probed and why

## Before Metrics

- current replay sample shows zero-signal locator patterns in chain domains already known to have corporate promotions

## Non-Goals

- no generic chain crawler
- no renderer fallback work
- no persistent registry design beyond what is needed for the targeted rules

## Escalate If

- the hint layer needs central governance or a long-lived registry
- the same chain requires complex cross-domain mapping that is better treated as architecture work