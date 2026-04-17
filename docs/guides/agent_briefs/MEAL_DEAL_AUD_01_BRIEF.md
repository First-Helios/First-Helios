# AUD-01 Agent Brief

Updated: 2026-04-17
Task ID: `AUD-01`
Tier: 1
Status: completed locally; use this brief for extension or reruns

## Objective

Build a repeatable audit summarizer over the synced website-scrape audit JSON and replay bundles so the team can measure recall and structure loss without hand-running ad hoc queries.

## Why This Matters

The current scraper bottleneck is not downstream scoring. It is upstream recall and extraction quality. We need one baseline report format so later discovery, DOM, JSON-LD, and renderer changes can be compared against the same categories.

## Prerequisites

- Required: `data/cache/website_scrape_audit.json` exists locally.
- Required: `data/cache/website_scrape_debug/` exists locally.
- Soft: coordinate terminology with `AUD-03` if that task starts at the same time.

## Target Files

- `scripts/summarize_website_scrape_audit.py`

## Inputs

- `data/cache/website_scrape_audit.json`
- `data/cache/website_scrape_debug/`

## Deliverable

A script that outputs:

- success rate and outcome counts
- no-deal taxonomy
- domain-family counts
- shared-URL counts
- JSON-LD prevalence
- PDF prevalence
- page fetch-type counts

## Acceptance Checks

- Runs without database access.
- Supports human-readable text output.
- Supports machine-readable JSON output.
- Handles invalid bundle JSON without crashing.
- Separates audit snapshot counts from replay bundle counts.

## Before Metrics

- audit snapshot entries: 725
- deals_found: 106
- no_deals: 619
- largest no-deal bucket: `content_seen_but_extraction_failed`

## Non-Goals

- no scraper extraction changes
- no DB writes
- no schema changes
- no attempt to solve wrong-target classification exhaustively

## Escalate If

- the synced audit schema differs from expected fields
- the bundle structure differs materially across files
- the output categories need to become canonical shared enums across multiple scripts