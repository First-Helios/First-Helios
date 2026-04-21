# Meal Deal Signal Refinement — Process Guide

> Audience: data engineers and operators who run, monitor, and improve
> the meal-deal quality pipeline.  Complements
> [MEAL_DEAL_SCRAPERS_RUNBOOK.md](MEAL_DEAL_SCRAPERS_RUNBOOK.md) (which
> focuses on *collection*).  This guide focuses on *refinement*: turning
> noisy scrape output into trustworthy signals.

---

## Contents
- [Why this exists](#why-this-exists)
- [The refinement pipeline at a glance](#the-refinement-pipeline-at-a-glance)
- [Schema fields the pipeline writes](#schema-fields-the-pipeline-writes)
- [Tool reference](#tool-reference)
  - [1. Quality scoring (live)](#1-quality-scoring-live)
  - [2. Sub-deal decomposition](#2-sub-deal-decomposition)
  - [3. Temporal backfill](#3-temporal-backfill)
  - [4. One-time cleanup](#4-one-time-cleanup)
  - [5. Chain dedup](#5-chain-dedup)
  - [6. Cross-employer leak detection](#6-cross-employer-leak-detection)
  - [7. Quality dashboard](#7-quality-dashboard)
  - [8. Re-audit sampler](#8-re-audit-sampler)
- [Recommended operating cadence](#recommended-operating-cadence)
- [Reading the audit output](#reading-the-audit-output)
- [When thresholds fire — what to do](#when-thresholds-fire--what-to-do)
- [Known findings and open work](#known-findings-and-open-work)

---

## Why this exists

Meal deals arrive from open-web scrapers, chain deal pages, and Google
Business Profile posts.  None of those sources is authoritative — menus
contain add-on prices, happy-hour blocks contain three different promos
in one paragraph, navigation elements pass as deal headings, and chain
content gets copied across N locations.

The refinement pipeline catches and corrects these issues in layers:

1. **At ingest** — scoring gates bad data before it lands.
2. **Periodic sweeps** — backfills fix legacy rows as rules improve.
3. **Continuous audit** — sampling surfaces drift before it spreads.

Each tool has a narrow job.  Run them in order and the DB converges on
high-quality rows.

---

## The refinement pipeline at a glance

```
            ┌─────────────────────────────────────────────────────────┐
            │                    NEW SIGNALS                          │
            │  (website_scraper, chain_deals, gbp_offers → DealSignal)│
            └──────────────────────┬──────────────────────────────────┘
                                   ▼
          ┌──────────────────────────────────────────────────────┐
          │  collectors/meal_deals/ingest.py                      │
          │  ┌────────────────────────────────────────────────┐   │
          │  │ 1. Brand resolution  → brand_group_id?          │   │
          │  │ 2. Location resolution → local_employer_id?     │   │
          │  │ 3. sub_deals decomposition                      │   │
          │  │ 4. signal_quality scoring                       │   │
          │  │ 5. Gate decision  reject | review | active      │   │
          │  └────────────────────────────────────────────────┘   │
          └───────────────┬──────────────────────────────────────┘
                          ▼
                ┌───────────────────┐
                │   meal_deals      │
                │   (postgres)      │
                └────┬──────┬───────┘
                     │      │
         ┌───────────┘      └─────────────┐
         ▼                                ▼
   DASHBOARD                          RE-AUDIT
  (aggregate)                   (stratified random sample)
```

All refinement logic lives in these modules:

| Module | Role |
|---|---|
| [`collectors/meal_deals/quality.py`](../../collectors/meal_deals/quality.py) | `compute_signal_quality()` and `gate_decision()` |
| [`collectors/meal_deals/sub_deals.py`](../../collectors/meal_deals/sub_deals.py) | `extract_sub_deals()` — multi-promo decomposition |
| [`collectors/meal_deals/temporal.py`](../../collectors/meal_deals/temporal.py) | Day/time extraction (shared by scrapers + backfill) |
| [`collectors/meal_deals/ingest.py`](../../collectors/meal_deals/ingest.py) | Orchestrates the whole live pipeline |

---

## Schema fields the pipeline writes

| Column | Type | Filled by | Notes |
|---|---|---|---|
| `price` | float | scraper | absolute or discount amount |
| `price_type` | enum string | scraper + cleanup | `absolute` \| `discount_amount` \| `percentage_off` \| `unknown` |
| `discount_percentage` | float | scraper + cleanup | e.g. `50.0` for half off |
| `raw_scraped_text` | text | scraper | preserves source for future re-parsing |
| `valid_days` | string | temporal extraction | `Mon-Fri`, `Sat-Sun` … |
| `valid_start_time`, `valid_end_time` | string | temporal extraction | `3:00 PM`, `Close` |
| `signal_quality` | float 0–1 | ingest + backfill | composite of 6 factors |
| `sub_deals` | jsonb | ingest + populator | `[{item,discount_type,discount_value}, …]` |
| `is_chain_template` | bool | chain dedup | template rows have `local_employer_id=NULL` |
| `is_active` | bool | gate decision + sweeps | visibility gate |

---

## Tool reference

### 1. Quality scoring (live)

**Where:** [`collectors/meal_deals/quality.py`](../../collectors/meal_deals/quality.py)

**What it does.**  Produces a `QualityScore` with six weighted factors
(see the table below).  Runs on every new `DealSignal` in `ingest.py`
and on every row when `backfill_signal_quality.py --apply` runs.

| Factor | Weight | Full credit when… |
|---|---:|---|
| Price | 0.25 | `price_type` is `absolute`, `discount_amount`, or `percentage_off` |
| Time/day | 0.20 | `valid_days` + (`valid_start_time` or `valid_end_time`) populated |
| Description | 0.15 | `len(description) ≥ 30` and not boilerplate |
| Name | 0.15 | 5–60 chars, not a sentence fragment |
| Restaurant match | 0.10 | restaurant-name token appears in content |
| Not an add-on | 0.15 | no `+$` / `add … $` / `extra … $` pattern |

**Gating (`gate_decision`):**
- `score < 0.20` → `reject` (not written)
- `0.20 ≤ score < 0.40` → `review` (written, `is_active=False`)
- `score ≥ 0.40` → `active` (written, `is_active=True`)

**Add-on cap.**  If the text looks like a modifier (`+$1 add bacon`) and
no absolute price ≥ $2 is present, the total is capped at 0.25 so it
lands in the reject band.  This prevents borderline "Add X for +$1" rows
from sneaking past the default 0.20 threshold.

**Re-run the backfill whenever the scoring rules change:**

```bash
# Dry-run
PYTHONPATH=. python scripts/backfills/backfill_signal_quality.py

# Commit
PYTHONPATH=. python scripts/backfills/backfill_signal_quality.py --apply

# Also deactivate the review band (0.20–0.40):
PYTHONPATH=. python scripts/backfills/backfill_signal_quality.py --apply --deactivate-review
```

The script is idempotent.  Running it twice in a row writes zero changes.

---

### 2. Sub-deal decomposition

**Where:**
[`collectors/meal_deals/sub_deals.py`](../../collectors/meal_deals/sub_deals.py)
— extractor.
[`scripts/one_shot/populate_sub_deals.py`](../../scripts/one_shot/populate_sub_deals.py)
— backfill.

**What it does.**  When a single text block contains multiple offers
("Happy Hour … $1 Off Draft Beer, Half Off Appetizers, $5 Frozen
Margaritas"), `extract_sub_deals()` produces a list like:

```json
[
  {"item": "draft beer",      "discount_type": "discount_amount", "discount_value": 1.0},
  {"item": "appetizers",      "discount_type": "percentage_off",  "discount_value": 50.0},
  {"item": "frozen margaritas","discount_type": "absolute",        "discount_value": 5.0}
]
```

The extractor is conservative: it only emits `sub_deals` when it finds
≥2 distinct offers.  Simple deals like "$5 combo" stay with sub_deals
`NULL` and rely on the primary `price` / `price_type` columns.

**Backfill existing rows** (one-time or after extractor updates):

```bash
PYTHONPATH=. python scripts/one_shot/populate_sub_deals.py              # dry-run
PYTHONPATH=. python scripts/one_shot/populate_sub_deals.py --apply
PYTHONPATH=. python scripts/one_shot/populate_sub_deals.py --apply --all  # include inactive rows
```

**At ingest,** `sub_deals` is computed automatically inside
`collectors/meal_deals/ingest.py` whenever the collector hasn't already
filled it and the signal has any text to decompose.

---

### 3. Temporal backfill

**Where:** [`scripts/backfills/backfill_deal_temporal.py`](../../scripts/backfills/backfill_deal_temporal.py)

Re-parses `deal_description` / `raw_scraped_text` for existing rows and
fills in `valid_days`, `valid_start_time`, `valid_end_time` using the
shared temporal extractor.  Live scrapers already call the same code, so
this script is only needed to lift pre-Phase-2 rows.

```bash
PYTHONPATH=. python scripts/backfills/backfill_deal_temporal.py           # dry-run
PYTHONPATH=. python scripts/backfills/backfill_deal_temporal.py --apply
```

---

### 4. One-time cleanup

**Where:** [`scripts/one_shot/cleanup_meal_deals.py`](../../scripts/one_shot/cleanup_meal_deals.py)

Removes known-junk rows that slipped past the live filters, and
reclassifies `price_type` for rows whose text reveals a
`discount_amount` / `percentage_off` pattern.

What it does:
- **Deletes** `$0.00` deals, sub-$1 non-food rows, nav/boilerplate
  names, known retail leaks (e.g. TCBY/J.Crew), and event-booking spam.
- **Reclassifies** `$X off ...` → `discount_amount`, `half off` /
  `X% off` → `percentage_off` (setting `discount_percentage`).

```bash
PYTHONPATH=. python scripts/one_shot/cleanup_meal_deals.py           # dry-run
PYTHONPATH=. python scripts/one_shot/cleanup_meal_deals.py --apply
```

Re-run this after any rule update in `_RETAIL_KW_RE` / `_EVENT_SPAM_RE`
/ nav junk patterns.  It is idempotent.

---

### 5. Chain dedup

**Where:** [`scripts/one_shot/dedupe_chain_deals.py`](../../scripts/one_shot/dedupe_chain_deals.py)

Chain deal content (McDonald's, Wendy's, Domino's, …) used to be copied
to every physical location, producing 58× / 30× / 29× duplicates.  The
dedupe script keeps the highest-quality row per
`(brand_group_id, deal_name, source)`, promotes it to
`is_chain_template=True` with `local_employer_id=NULL`, and deletes the
rest.  Downstream queries reconstruct per-location views by joining on
`brand_group_id`.

```bash
PYTHONPATH=. python scripts/one_shot/dedupe_chain_deals.py           # dry-run
PYTHONPATH=. python scripts/one_shot/dedupe_chain_deals.py --apply
```

The live ingest path also writes chain deals as templates — this script
only exists for the initial collapse.  After Phase 3 it should be a
no-op unless the chain collector is rewritten.

---

### 6. Cross-employer leak detection

**Where:** [`scripts/detect_cross_employer_leaks.py`](../../scripts/detect_cross_employer_leaks.py)

When several employers share a landing page, or OSM/Google Places maps
two businesses to the same URL, one restaurant's deals can be attributed
to another.  The leak detector builds an index of employer name phrases
(≥2 words, ≥5 chars, non-generic) restricted to *employers that actually
have deals*, then flags rows whose text contains a foreign employer's
name while missing their own.

```bash
PYTHONPATH=. python scripts/detect_cross_employer_leaks.py          # dry-run
PYTHONPATH=. python scripts/detect_cross_employer_leaks.py --apply  # deactivate high-confidence
```

Only high-confidence matches are auto-deactivated.  Medium-confidence
matches (both names present) are listed for manual review.

---

### 7. Quality dashboard

**Where:** [`scripts/meal_deal_quality_dashboard.py`](../../scripts/meal_deal_quality_dashboard.py)

One-shot health snapshot of `meal_deals`.  Prints:
- Row totals and active ratio
- `signal_quality` distribution (mean, median, P10/25/75/90)
- Field completeness percentages
- Per-source breakdown (rows, active %, mean quality, sub_deals count)
- Top deal types and price_type distribution
- **Alerts** when any source drops below configurable thresholds

```bash
# Text report
PYTHONPATH=. python scripts/meal_deal_quality_dashboard.py

# Machine-readable JSON for logging / dashboards
PYTHONPATH=. python scripts/meal_deal_quality_dashboard.py --json

# CI / cron usage — exits with code 2 if any alert fires
PYTHONPATH=. python scripts/meal_deal_quality_dashboard.py \
    --alert-threshold 0.50 \
    --alert-active-ratio 0.40 \
    --exit-on-alert
```

Defaults: per-source mean quality floor of 0.50, active-ratio floor of
0.40.  Tune as the DB matures.

---

### 8. Re-audit sampler

**Where:** [`scripts/reaudit_meal_deals.py`](../../scripts/reaudit_meal_deals.py)

The dashboard gives you aggregate health, but aggregates hide broken
strata.  The re-audit takes a **stratified random sample** — N rows per
`(source, deal_type, is_active)` triple — and replays today's rules
against each one, flagging discrepancies.

Default is **3 samples per stratum**, matching the "random shuffle, 3×
per data intake" convention.  Bump `--samples 10` for deeper runs.

```bash
# 3 per stratum (default)
PYTHONPATH=. python scripts/reaudit_meal_deals.py

# Reproducible run (for CI / comparison over time)
PYTHONPATH=. python scripts/reaudit_meal_deals.py --samples 5 --seed 42

# Include inactive rows (for triaging the review band)
PYTHONPATH=. python scripts/reaudit_meal_deals.py --include-inactive

# JSON output for logging
PYTHONPATH=. python scripts/reaudit_meal_deals.py --json > audit.json
```

**Flag codes** the audit emits:

| Flag | Meaning | How to fix |
|---|---|---|
| `quality_drift` | stored `signal_quality` differs from recomputed by >0.10 | run `backfill_signal_quality.py --apply` |
| `gate_drift` | row's active/review/reject status would change today | same as above |
| `missing_sub_deals` | text decomposes but `sub_deals` is NULL | run `populate_sub_deals.py --apply` |
| `price_type_unknown` | `price` is set but `price_type` is NULL/unknown | re-run `cleanup_meal_deals.py` or add a dedicated absolute-price classifier |
| `stale_addon` | active row's text reads like an add-on | tighten `_ADDON_CONTEXT_RE`; purge via `cleanup_meal_deals.py` |
| `stale_nav` | active row's name matches nav junk patterns | extend `_NAV_JUNK_RE`; rerun cleanup |

Exit codes: `0` = all pass, `2` = at least one failure (CI-friendly).

---

## Recommended operating cadence

| Cadence | Command | Purpose |
|---|---|---|
| On every scrape | (automatic — `ingest.py`) | Live scoring + sub_deal decomposition + gating |
| Daily | `meal_deal_quality_dashboard.py --exit-on-alert` | Watch for regressions; page on threshold breach |
| Weekly | `reaudit_meal_deals.py --samples 5` | Catch drift + flag rows for refinement |
| After any rule change in `quality.py` | `backfill_signal_quality.py --apply` | Re-align stored scores with current rules |
| After any rule change in `sub_deals.py` | `populate_sub_deals.py --apply` | Re-decompose multi-promo rows |
| After any rule change in `cleanup_meal_deals.py` | `cleanup_meal_deals.py --apply` | Retire newly-recognized junk |
| Monthly / on demand | `detect_cross_employer_leaks.py --apply` | Sweep for content leaks |

Run them in that order — each later step reads state the earlier step wrote.

---

## Reading the audit output

```
Population strata:   7
Samples per stratum: 3
Total sampled:       21
Total failed:        8   (38.1%)
Pass rate:           61.9%

Flag frequency:
  price_type_unknown        8

Strata with the most failures (top 15):
  (source, deal_type, is_active)          pop sampled failed
  ('website_scrape', 'combo', True)      1146      3 3
  ('website_scrape', 'lunch_special',...)  26      3 3
  ('chain_website', 'combo', True)          4      3 2
```

Interpretation:

- **Stratum failure rate** extrapolates: if 3 of 3 sampled `combo` rows
  failed, the population of 1,146 likely has a *majority* of failures.
- **Flag distribution** tells you what kind of fix is needed.  One
  dominant flag → one script to re-run.  Multiple flags → investigate
  root cause (usually an out-of-date rule).
- Compare runs over time with a fixed `--seed` to isolate genuine drift
  from sampling noise.

---

## When thresholds fire — what to do

| Dashboard alert | First response |
|---|---|
| `mean signal_quality < 0.50` for a source | Re-run `backfill_signal_quality.py --apply`; if persists, inspect that source's extractor. |
| `active_ratio < 0.40` for a source | Many rows stuck in review.  Inspect sample via `reaudit_meal_deals.py --include-inactive`. |
| `price_type_unknown` flag dominant in audit | The collector or cleanup script needs a new classifier path. |
| `gate_drift` spike after a rule change | Expected — run the quality backfill. |
| `missing_sub_deals` spike | Run the sub_deals populator. |

If a rule is wrong (audit flags a genuinely good row as failed), fix
the rule in `quality.py` / `sub_deals.py` first — do *not* patch the
data to match a broken rule.

---

## Known findings and open work

Documented from the first full re-audit on 2026-04-16.  Treat these as
rolling backlog items — each one is a rule gap the refinement pipeline
has surfaced.

1. **1,577 rows have `price` set but `price_type` NULL/unknown.**  These
   are pre-Phase-1 rows where the text is a clean absolute price
   ("Lunch Special $13") that didn't match any discount pattern.  The
   cleanup script only promotes rows to `discount_amount` /
   `percentage_off`; a dedicated "absolute by default" pass would close
   the gap.

2. **chain_website mean quality is 0.37** — below the dashboard alert
   threshold.  Chain templates lost `restaurant_match` credit when
   Phase 3 set `local_employer_id=NULL`.  Scoring should optionally
   accept a `brand_name` for templates.

3. **sub_deals coverage is 3.3%.**  That matches the share of rows with
   genuine multi-promo text.  Growth will come mostly from richer
   `raw_scraped_text` as new scrapes land (currently only 0% of legacy
   rows have it populated).

4. **website_scrape mean quality is 0.499** — just below the default
   0.50 threshold.  Dominated by rows missing time/day windows.
   Further temporal-extraction improvements (chain landing pages, PDF
   menus) remain the cheapest way to raise the floor.

Log new findings here as the audit uncovers them.  A finding is
"resolved" when the rule is updated *and* the appropriate backfill
script has been re-run.
