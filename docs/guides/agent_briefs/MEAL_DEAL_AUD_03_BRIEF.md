# AUD-03 Agent Brief

Updated: 2026-04-17
Task ID: `AUD-03`
Tier: 1
Status: ready

## Objective

Add a wrong-target and page-family classifier so audit and manifest tooling can distinguish restaurant first-party pages from locator pages, social pages, hotel pages, directory pages, vendor menu hosts, government pages, and obviously unrelated targets.

## Why This Matters

The synced replay set already shows obvious wasted targets. A lightweight classifier lets the audit tools quantify that waste explicitly and helps discovery work focus on restaurant-owned evidence instead of noisy domains.

## Prerequisites

- Required: synced audit JSON and replay bundles exist locally.
- Soft: coordinate with `AUD-01` so family labels stay consistent.

## Target Files

- a new or shared audit helper module
- or an update to the `AUD-01` summary script if the shared taxonomy stays small

## Inputs

- `data/cache/website_scrape_audit.json`
- `data/cache/website_scrape_debug/`

## Deliverable

A lightweight, explicit taxonomy for page families such as:

- restaurant first-party
- locator
- social
- hotel
- directory
- vendor menu host
- government
- other non-restaurant

## Acceptance Checks

- the classifier is deterministic and file-based
- the categories appear in summary output or manifest output
- the taxonomy is documented in one place

## Before Metrics

- family counting is currently heuristic and embedded in `AUD-01`
- there is no shared, reusable page-family taxonomy yet

## Non-Goals

- no ingestion gating changes
- no live scrape suppression in this task
- no attempt to resolve every ambiguous host perfectly

## Escalate If

- the classifier needs to become a live scraper guardrail rather than an audit-only tool
- taxonomy disagreements start affecting discovery scope decisions