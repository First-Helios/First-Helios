# AUD-02 Agent Brief

Updated: 2026-04-17
Task ID: `AUD-02`
Tier: 1
Status: ready

## Objective

Build replay corpus manifests by failure stage so later agents can work from stable subsets instead of hand-picking bundle files.

## Why This Matters

The replay corpus is already large enough to support parallel work, but it is not yet packaged into stable subsets like `JSON-LD present but zero-signal`, `locator page`, or `PDF present but zero-signal`. That packaging is the handoff layer for later discovery and extraction tasks.

## Prerequisites

- Required: synced replay bundles exist locally.
- Soft: reuse terminology and family labels from `AUD-01` if available.
- Soft: coordinate with `AUD-03` so host-family tags are not duplicated in incompatible ways.

## Target Files

- new manifest builder script in `scripts/`
- new manifest outputs under `data/cache/` or another clearly documented local cache path

## Inputs

- `data/cache/website_scrape_audit.json`
- `data/cache/website_scrape_debug/`

## Deliverable

Machine-readable manifests for categories such as:

- discovery miss
- locator page
- social or non-first-party page
- JSON-LD present but zero-signal
- PDF present but zero-signal
- content seen but zero-signal

## Acceptance Checks

- every manifest is reproducible from the synced cache
- each manifest entry points back to a concrete bundle or audit row
- manifests can be filtered by outcome and failure family
- output location and schema are documented

## Before Metrics

- no durable replay manifests exist yet
- failure-family grouping is currently ad hoc

## Non-Goals

- no scraper behavior changes
- no renderer changes
- no persistent database writes

## Escalate If

- the team wants the manifest schema to become a longer-lived contract shared by multiple tools
- the desired failure families require classifier work beyond simple packaging