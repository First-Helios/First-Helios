# Meal Deal Scraper Signal Refinement Roadmap

Updated: 2026-04-16
Status: active planning document for multi-agent execution
Scope: open refinement work for `collectors/meal_deals/website_scraper.py` and adjacent audit, replay, extraction, and modeling tasks

## Purpose

This roadmap organizes the remaining meal-deal scraper work by implementation complexity and model power.

The goal is to let multiple agents work in parallel without wasting high-reasoning agents on bounded chores, and without giving cross-cutting extraction architecture work to smaller agents that are more likely to produce brittle heuristics.

This document covers the open website-scraper work after the already-completed pricing, temporal extraction, raw text capture, and signal-quality hardening documented elsewhere.

## Current Evidence Snapshot

Synced from the Orange Pi on 2026-04-16 while the long-running website scrape was still in progress.

- Replay corpus synced locally: 1101 site bundles in `data/cache/website_scrape_debug`
- Site audit snapshot synced locally: 725 site entries in `data/cache/website_scrape_audit.json`
- Sites with deals: 106 / 725 = 14.6%
- Sites with no deals: 619 / 725 = 85.4%
- No-deal taxonomy from the audit snapshot:
  - content seen but extraction failed: 301
  - fetch or parse failed: 121
  - empty or unusable page: 107
  - discovery found candidates but no signal: 75
  - PDF present but no signal: 15
- Current canonical `website_scrape` observations in Postgres: 465
- Field coverage in those observations:
  - `raw_scraped_text`: 458 / 465
  - `menu_avg_price`: 324 / 465
  - `price_type`: 264 / 465
  - `price`: 227 / 465
  - `valid_days`: 169 / 465
  - `valid_start_time`: 137 / 465
  - `valid_end_time`: 124 / 465
  - `calories`: 0 / 465

Interpretation:

1. The dominant bottleneck is still recall in discovery and extraction, not downstream scoring.
2. The scraper often fetches useful content but fails to turn it into a structured offer.
3. Structured data and section structure are still being underused.
4. Renderer escalation should not be the first move; discovery and structured extraction should come first.

## Agent Power Tiers

| Tier | Model power | Best fit | Avoid assigning |
|---|---|---|---|
| Tier 1 | Lightweight coding model | deterministic scripts, audit aggregation, manifests, bounded logging changes, fixture curation, simple tests | ambiguous HTML interpretation, schema design, menu graph work, renderer policy |
| Tier 2 | Standard coding model | heuristic changes across 1-3 files, discovery scoring, DOM extraction tweaks, replay-driven parser changes, regression tests | cross-cutting architectural changes, persistent schema design, high-ambiguity structured extraction |
| Tier 3 | High-reasoning model | schema.org hierarchy traversal, structured menu sidecars, offer-target linking, renderer escalation policy, section-aware pricing | simple data summaries, rote manifests, low-risk boilerplate tasks |
| Tier 4 | Human plus Tier 3 | persistence decisions, value-model semantics, review thresholds, long-lived registry policy, budget-sensitive renderer decisions | straightforward implementation-only work |

## Routing Rules

1. Use replay bundles first. Do not make live crawl breadth the default debugging tool.
2. Improve discovery before broad renderer escalation.
3. Fully exploit schema.org structure before adding more regex complexity.
4. Preserve menu structure in sidecar artifacts before committing to persistent menu tables.
5. Every extraction change should come with replay-based tests or at least replay-based before/after metrics.
6. Low-power agents should work from a bounded task ID, target files, and acceptance criteria, not from open-ended HTML interpretation.

## Workstreams

The work naturally falls into five streams:

1. Audit and replay operations
2. Discovery recall
3. Extraction and structure preservation
4. Rendering and document fallback
5. Structured menu and value modeling

## Tier 1 Tasks

These are the best tasks for lightweight agents. They are bounded, measurable, and useful immediately.

- `AUD-01` Build a repeatable audit summarizer script over `data/cache/website_scrape_audit.json` and `data/cache/website_scrape_debug`. Best agent: Tier 1. Complexity: low. Deliverable: a script in `scripts/` that outputs success rate, no-deal taxonomy, domain-family counts, shared-URL counts, JSON-LD prevalence, PDF prevalence, and page-type counts. Why this tier: it is deterministic aggregation over already-synced artifacts.
- `AUD-02` Build replay corpus manifests by failure stage. Best agent: Tier 1. Complexity: low. Deliverable: machine-readable manifests grouping bundles into categories such as discovery miss, locator page, social/non-first-party page, JSON-LD present but zero-signal, PDF present but zero-signal, and content-seen-but-no-signal. Why this tier: it is labeling and packaging, not parser redesign.
- `AUD-03` Add a wrong-target and page-family classifier. Best agent: Tier 1. Complexity: low. Deliverable: a script or config that tags hosts as restaurant first-party, locator, hotel, social, directory, vendor menu host, government, or obviously unrelated. This should feed audit reporting, not yet ingestion. Why now: the synced bundles already show obvious wrong-target families such as Facebook, Instagram, locator pages, and unrelated domains.
- `AUD-04` Expand success-path audit logging so `deals_found` rows record the same context as `no_deals` rows. Best agent: Tier 1. Complexity: low. Deliverable: audit entries that always include block counts, discovered page counts, PDF link counts, and structured-data presence. Why now: current audit JSON is much more informative for failures than successes.
- `OPS-01` Document the replay workflow. Best agent: Tier 1. Complexity: low. Deliverable: a short operator guide covering `dev/sync_from_opi.sh`, replay-cache use, and the expected files under `data/cache/website_scrape_debug`. Why now: the sync script now pulls replay bundles and should be part of the standard debug path.
- `TEST-01` Curate small regression bundle sets for each failure family. Best agent: Tier 1. Complexity: low. Deliverable: named fixture lists for discovery, JSON-LD, PDF, wrong-target, and JS-rendered misses. Why this tier: fixture selection is bounded and supports higher-tier implementation work.

## Tier 2 Tasks

These tasks still use heuristics, but they touch scraper behavior and require careful replay validation.

- `DISC-01` Expand `_discover_deal_pages` to score footer links, promotions clusters, learn-more clusters, and likely first-party promo slugs. Best agent: Tier 2. Complexity: medium. Targets the `discovery found candidates but no signal` bucket and the hidden-promo-page problem described in the audit instructions.
- `DISC-02` Add locator-to-corporate promo hint routing for common chain patterns. Best agent: Tier 2. Complexity: medium. Deliverable: rules that recognize pages such as `locations.brand.com/...` and probe stable corporate promo pages when appropriate. This directly targets sites like Tropical Smoothie Cafe and Denny's where the location page itself is not the real promo source.
- `DISC-03` Add scoped sitemap and known-slug probing for first-party deal paths. Best agent: Tier 2. Complexity: medium. Deliverable: a narrow, first-party-only discovery layer for paths like `/promotions`, `/offers`, `/bogo-days`, `/happy-hour`, and sitemap-derived candidates. Guardrail: do not broaden into general crawling.
- `DISC-04` Add first-party scope enforcement and obvious wrong-target suppression in the scraper pipeline. Best agent: Tier 2. Complexity: medium. Deliverable: rules that reduce wasted work on social pages, unrelated domains, and clearly non-restaurant pages before extraction spends effort on them.
- `DOM-01` Improve `_extract_text_blocks` so heading, sibling, list, and table relationships survive extraction. Best agent: Tier 2. Complexity: medium. Targets the largest current bucket: `content seen but extraction failed`.
- `NAME-01` Improve `_extract_deal_name` so it preserves the menu target or promo label instead of returning a sentence fragment. Best agent: Tier 2. Complexity: medium. Deliverable: replay-tested improvements that reduce description-like names without regressing short labels such as Happy Hour or Lunch Special.
- `PRICE-01` Tighten `_extract_all_prices` so page-level baseline pricing excludes obvious modifiers, addons, and unrelated numbers. Best agent: Tier 2. Complexity: medium. This is not the full item-aware pricing problem; it is the bounded cleanup needed to make `menu_avg_price` less noisy.
- `PDF-01` Improve `_discover_pdf_links` scoring and classify menu PDFs versus special-offer PDFs. Best agent: Tier 2. Complexity: medium. Deliverable: better PDF prioritization so the scraper spends its small PDF budget on the most relevant assets.
- `TEST-02` Build replay regression tests for discovery and DOM extraction changes. Best agent: Tier 2. Complexity: medium. Deliverable: tests in `tests/HeliosDeployment/` that use synced bundles and lock in the intended before/after behavior.

## Tier 3 Tasks

These tasks should go to a high-reasoning agent. They involve ambiguous structure, cross-cutting extraction logic, or durable output model decisions.

- `JSONLD-01` Rewrite `_extract_jsonld_deals` to traverse full schema.org `FoodEstablishment -> Menu -> MenuSection -> MenuItem -> Offer` hierarchies. Best agent: Tier 3. Complexity: high. Why this tier: it is the highest-leverage structured-data task and requires careful traversal, dedupe, and signal-target logic.
- `STRUCT-01` Emit structured menu sidecar artifacts in debug bundles and signal metadata. Best agent: Tier 3. Complexity: high. Deliverable: sidecar objects for menu pages, sections, items, price points, modifiers, and offer targets. Guardrail: do this in metadata or debug artifacts first, not persistent tables.
- `TARGET-01` Link extracted offers to an item, section, service period, or venue-wide target. Best agent: Tier 3. Complexity: high. This is required before the system can reliably answer what the promotion changes relative to baseline pricing.
- `PRICE-02` Make baseline pricing section-aware or item-aware instead of page-average-only. Best agent: Tier 3. Complexity: high. Deliverable: richer price evidence that distinguishes appetizers, entrees, drinks, desserts, and modifiers when the page structure supports it.
- `RENDER-01` Add targeted Playwright escalation for static-empty but menu-critical pages. Best agent: Tier 3. Complexity: high. Guardrail: this should be targeted to pages that are discovery-valid and structurally empty in static HTML, not used as a blanket fallback.
- `PDF-02` Add layout-aware PDF parsing for menus and specials where plain text extraction loses item-price pairing. Best agent: Tier 3. Complexity: high. This should remain tightly scoped to PDFs that clearly matter in the replay corpus.
- `VALUE-01` Derive category-aware value profiles from the structured menu sidecar. Best agent: Tier 3. Complexity: high. Deliverable: baseline appetizer, entree, and drink signals that can support savings estimation and downstream meal-planning UX.

## Tier 4 Tasks

These tasks should be held for human review plus a high-reasoning implementation agent.

- `ARCH-01` Decide whether the menu graph stays in sidecar artifacts or gets persistent tables. Best agent: Tier 4. Complexity: very high. Recommendation: defer persistent tables until the sidecar has been replay-tested across a larger corpus.
- `ARCH-02` Set confidence and review policy for offer-target links. Best agent: Tier 4. Complexity: very high. This defines when an item-level link is accepted, review-only, or discarded.
- `ARCH-03` Set renderer budget and allowlist policy. Best agent: Tier 4. Complexity: very high. This is an operational and cost decision, not just a coding task.
- `ARCH-04` Decide hint-registry governance. Best agent: Tier 4. Complexity: very high. This covers where brand-specific promo slugs, footer labels, and locator-to-corporate mappings live and how they are maintained.

## Recommended Parallel Execution Plan

### Wave 1

Start immediately.

- Assign Tier 1 agents to `AUD-01`, `AUD-02`, `AUD-03`, and `OPS-01`.
- Assign Tier 2 agents to `DISC-01`, `DISC-02`, and `AUD-04`.
- Assign one Tier 3 agent to `JSONLD-01` as a focused design-and-implementation spike over a small replay set.

Expected output:

- better measurement
- better failure-family manifests
- improved discovery on hidden promo pages
- a concrete structured-data extraction direction

### Wave 2

Start after Wave 1 manifests and logging improvements are merged.

- Assign Tier 2 agents to `DISC-03`, `DISC-04`, `DOM-01`, `NAME-01`, and `TEST-02`.
- Assign the Tier 3 agent to `STRUCT-01` and the design portion of `TARGET-01`.

Expected output:

- lower wrong-target waste
- better text-block extraction from pages that already contain useful content
- sidecar structure available for inspection and replay

### Wave 3

Start after sidecar structure exists and is being populated reliably.

- Assign Tier 3 agents to `TARGET-01`, `PRICE-02`, `RENDER-01`, and `PDF-02`.
- Keep Tier 2 agents on focused replay tests and bounded parser support work.

Expected output:

- stronger offer-to-target semantics
- better baseline pricing
- targeted renderer and PDF improvements where static HTML is insufficient

### Wave 4

Start only after Waves 1-3 are stable on replay.

- Assign a Tier 3 agent to `VALUE-01`.
- Hold `ARCH-01` through `ARCH-04` for human review plus a Tier 3 implementation pass.

Expected output:

- spend and savings estimation inputs
- a stable basis for deciding whether to persist menu graph data

## Sequencing Constraints

1. Do not start `VALUE-01` before `STRUCT-01` and `TARGET-01` exist.
2. Do not start persistent schema work before sidecar artifacts have been replay-tested.
3. Do not treat renderer escalation as a substitute for discovery and structured-data work.
4. Do not broaden crawling scope beyond the known restaurant site and clearly linked first-party assets.

## Success Metrics By Milestone

### Milestone A: Measurement complete

- every synced audit run produces a reproducible summary
- every replay bundle belongs to a failure-family manifest
- success-path audit entries record enough context to compare with no-deal entries

### Milestone B: Discovery and extraction improved

- reduce the `content seen but extraction failed` bucket materially on the replay corpus
- reduce the `discovery found candidates but no signal` bucket materially on the replay corpus
- keep mean accepted signal quality at or above the current baseline
- keep `raw_scraped_text` coverage above 95%

### Milestone C: Structure preserved

- JSON-LD menus and offers are traversed hierarchically when present
- sidecar artifacts preserve menu pages, sections, items, and price evidence
- extracted offers can be linked to at least an item, section, service period, or venue-wide target

### Milestone D: Product unlocks enabled

- the system can estimate a plausible baseline spend for the relevant category
- the system can explain what the promotion changes relative to that baseline
- the value profile is evidence-backed rather than inferred from flat text alone

## Agent Handoff Template

Every delegated task should include:

1. task ID
2. target files
3. replay bundle manifest or audit subset
4. acceptance checks
5. before and after metrics
6. explicit non-goals

Recommended handoff format:

```text
Task ID:
Target files:
Replay set:
Acceptance checks:
Before metrics:
Non-goals:
Escalate if:
```

## Recommended First Assignments

If work starts immediately, the best first distribution is:

1. Tier 1 agent: `AUD-01`
2. Tier 1 agent: `AUD-02`
3. Tier 1 agent: `AUD-03`
4. Tier 2 agent: `DISC-01`
5. Tier 2 agent: `DISC-02`
6. Tier 3 agent: `JSONLD-01`

That mix attacks the three biggest current needs at once:

1. better measurement
2. better discovery recall
3. better structured extraction