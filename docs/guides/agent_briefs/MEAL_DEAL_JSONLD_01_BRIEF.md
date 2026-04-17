# JSONLD-01 Agent Brief

Updated: 2026-04-17
Task ID: `JSONLD-01`
Tier: 3
Status: ready

## Objective

Rewrite `_extract_jsonld_deals` so it traverses full schema.org menu hierarchies instead of only harvesting flat `Offer` and `MenuItem` fragments.

## Why This Matters

Structured data is one of the highest-leverage improvements available. The replay corpus already includes zero-signal pages that contain JSON-LD. If menu and offer hierarchies are traversed correctly, the scraper can preserve much richer structure before falling back to brittle text heuristics.

## Prerequisites

- Required: replay bundles with JSON-LD present.
- Soft: use the `AUD-01` baseline to quantify current JSON-LD prevalence.
- Preferred: use an `AUD-02` subset of `JSON-LD present but zero-signal` pages if available.

## Target Files

- `collectors/meal_deals/website_scraper.py`
- `collectors/meal_deals/models.py` if metadata needs extension
- replay tests under `tests/HeliosDeployment/`

## Inputs

- replay bundles whose HTML contains `application/ld+json`
- structured menu pages with `FoodEstablishment`, `Menu`, `MenuSection`, `MenuItem`, and `Offer`

## Deliverable

Traversal and extraction that can handle:

- `FoodEstablishment -> hasMenu`
- `Menu -> hasMenuSection`
- nested `MenuSection -> hasMenuSection`
- `MenuSection -> hasMenuItem`
- `MenuItem -> offers`, `nutrition`, and related fields
- `Offer -> itemOffered`, `priceSpecification`, and time-aware fields when present

## Acceptance Checks

- replay-tested on a named structured-data subset
- preserves dedupe behavior
- does not flatten hierarchy unnecessarily when the structure exists
- records enough evidence to support later sidecar menu artifacts

## Before Metrics

- many synced zero-signal bundles still contain JSON-LD
- current `_extract_jsonld_deals` only partially traverses menu structure

## Non-Goals

- no persistent menu tables in this task
- no renderer escalation
- no broad text-heuristic rewrite outside the JSON-LD path

## Escalate If

- the structured output can no longer fit cleanly in current signal metadata or debug bundle structure
- offer-target linking requires a broader sidecar design decision first