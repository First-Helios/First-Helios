# SpiritPool Dev Capture → Hintbook → Coverage Pipeline

Updated: 2026-04-21
Audience: operators and agents working on first-party deal coverage,
SpiritPool dev-user captures, or the hintbook comparator.

This guide documents the staged pipeline that turns signed SpiritPool
dev-capture bundles into hintbook records and a coverage report, plus the
scrape-denial queue that tells the operator which first-party URLs are
worth capturing next.

---

## 1. Why this pipeline exists

Two different gaps push data through SpiritPool instead of the automated
scrapers:

1. **Anti-bot denial.** `collectors/meal_deals/website_scraper.py` fetches
   `restaurant_urls.url` on a schedule. Major chains (McDonald's, Starbucks,
   IHOP, Dunkin', Dutch Bros, Krispy Krunchy, ...) respond with Cloudflare
   challenges, 403s, or empty bodies. `restaurant_urls.last_http_status`
   ends up NULL even though `last_checked` is set — a silent failure.

2. **Aggregator JS apps.** Sites like Slickdeals and BiteHunter ship empty
   HTML shells and fetch deal content client-side. A server-side request
   gets a useless "File Not Found - Slickdeals.net" title.

Both classes of page render fine in a real browser. SpiritPool's dev-capture
route lets an enrolled Firefox profile POST a signed full-page DOM snapshot
to the backend, which we then parse offline.

---

## 2. Capture lifecycle (the staging gate)

```
POST /api/spiritpool/dev/page-capture     (signed, HMAC-verified)
        |
        v
data/cache/spiritpool_dev/page_captures/  (raw, as-posted, signed)
        |
        v   scripts/validate_spiritpool_capture.py
        v
        +--> data/cache/spiritpool_dev/validated/
        |       (ready for harvest / adapter parsing)
        |
        +--> data/cache/spiritpool_dev/quarantine/<reason>/
                (empty_body, suspected_denial, site_error_or_denial,
                 too_small, too_large, quarantine_host, bad_captured_at,
                 missing_html, unparseable_json)
```

**Nothing parses `page_captures/` directly.** The harvester reads
`validated/` only. This is enforced in
[scripts/harvest_hintbook_from_spiritpool.py](../../scripts/harvest_hintbook_from_spiritpool.py)
via `DEFAULT_BUNDLE_DIR`.

### 2.1 Validation rules (per bundle)

Each rule's failure quarantines the bundle with a per-reason subdirectory:

| Rule | Quarantine reason |
|---|---|
| JSON parseable | `unparseable_json` |
| `html` field non-empty string | `missing_html` |
| `captured_at` valid ISO timestamp (if present) | `bad_captured_at` |
| Host not in test blocklist (example.com, localhost) | `quarantine_host` |
| HTML size within 2 KB – 10 MB | `too_small` / `too_large` |
| Rendering classifier == `content_ok` | `empty_body` / `suspected_denial` / `site_error_or_denial` |

The rendering classifier lives in
[scripts/harvest_hintbook_from_spiritpool.py](../../scripts/harvest_hintbook_from_spiritpool.py)
as `classify_bundle_rendering(html, title)`. It measures visible text
length after stripping `script`/`style`, then matches a short set of title
and body regex fingerprints for denial / 404 / empty-DOM states.

### 2.2 Running the gate

```bash
cd /home/fortune/CodeProjects/First-Helios
source .venv/bin/activate

# After a fresh rsync of bundles from the Pi, or after local captures:
python scripts/validate_spiritpool_capture.py

# Optional flags:
#   --input       data/cache/spiritpool_dev/page_captures
#   --validated   data/cache/spiritpool_dev/validated
#   --quarantine  data/cache/spiritpool_dev/quarantine
#   --remove-source-on-pass    (delete raw after successful hardlink)
#   --json                     (machine-readable output)
```

Bundles that pass are **hard-linked** into `validated/` (copy fallback on
cross-filesystem failure). Raw bundles stay in `page_captures/` unless
`--remove-source-on-pass` is passed, so the signed original is always
recoverable.

---

## 3. Harvest (hintbook adapters)

[scripts/harvest_hintbook_from_spiritpool.py](../../scripts/harvest_hintbook_from_spiritpool.py)
walks `validated/`, matches each bundle to one of the hintbook adapters
(`eatdrinkdeals`, `retailmenot`, ...) using canonical URL host, and produces:

- Per-run hintbook records and DealSignal projections
- Updated rows in `config/meal_deal_expectation_registry.json`
- A `denial_queue` listing bundles that were `validated/`-passable but
  still produced no brand match or unusable text

Brand resolution uses `collectors/hintbook/brand_matcher.py`, which pulls
its vocabulary (~994 entries) from `brand_groups.canonical_name` in the
database. Smart quotes are normalized and matches require `\b` word
boundaries.

Output:

```
data/cache/hintbook/spiritpool_runs/<TIMESTAMP>/
    hintbook_records.json
    hint_proposals.json
    expectation_rows.json
    denial_queue.json
    coverage_report.json        (written by compare step)
data/cache/hintbook/spiritpool_runs/latest/     (symlink)
```

Run:
```bash
python scripts/harvest_hintbook_from_spiritpool.py
# --bundle-dir override supported for ad-hoc runs
```

---

## 4. Compare (hintbook vs collected deals)

[scripts/compare_hintbook_to_deal_observations.py](../../scripts/compare_hintbook_to_deal_observations.py)
joins the harvest output against the live database
(`deal_observations`, `brand_groups`, `site_assignments`,
`active_restaurant_materializations`) and writes a coverage report.

It produces three views:

1. **Per-brand status** — for every brand in the hint book, does it have a
   `brand_group`, live observations, materializations, site assignments?
2. **Industry rollup** — per industry: hint-book count, brand-group count,
   observed brands, matched brands, percentages.
3. **Seed manifest gap** — compares against
   `config/spiritpool_capture_manifest.json`, the operator's prioritized
   aggregator capture targets. Uses a tolerant `ILIKE brand || '%'` lookup
   so "Dunkin'" matches "Dunkin' Donuts" etc.

Sample output tail:
```
Seed manifest gap: 0 / 21 targets covered; 21 remaining
  [P1] food_full_service      covered=0/3
      QUEUED   Chili's                      bg_loc=20   urls=2   status=brand_onboarded_awaiting_capture
      NO_BRAND Olive Garden                 bg_loc=0    urls=1   status=brand_not_onboarded
      NO_BRAND Red Lobster                  bg_loc=0    urls=1   status=brand_not_onboarded
```

Run:
```bash
python scripts/compare_hintbook_to_deal_observations.py
# Reads latest run at data/cache/hintbook/spiritpool_runs/latest/
```

---

## 5. Denial queue (first-party capture worklist)

[scripts/build_scrape_denial_queue.py](../../scripts/build_scrape_denial_queue.py)
is independent of the hintbook flow. It queries `restaurant_urls` directly
to find URLs the scraper cannot use:

```sql
(last_checked IS NOT NULL AND last_http_status IS NULL)
OR (last_http_status NOT IN (200, 201, 202, 204, 304))
```

...filtered to URLs whose brand has zero `deal_observations` and zero
`menu_pages`. Rows are deduplicated by URL (one capture unblocks the
adapter for every location sharing that chain URL) and capped per
priority bucket:

| Priority | Rule |
|---|---|
| P0 | Brand has ≥20 active Austin locations |
| P1 | Brand has 5–19 active Austin locations |
| P2 | Brand has 1–4 active Austin locations |
| P3 | Unbranded / independent |

Hosts already covered by a bundle in `page_captures/` are skipped.

Output: `data/cache/spiritpool_dev/capture_queue.json`.

Run:
```bash
python scripts/build_scrape_denial_queue.py
# --region austin_tx   --limit-per-priority 25
```

First-run snapshot (2026-04-21): 153 candidates → 9 distinct chain URLs
queued — Starbucks, McDonald's (P0); Dutch Bros, Krispy Krunchy (P1);
Dunkin' Cedar Park, Scooter's, Corner Bakery, IHOP, Shipley Do-Nuts (P2).

---

## 6. Two worklists, different roles

| File | Produced by | Targets | Lifecycle |
|---|---|---|---|
| `config/spiritpool_capture_manifest.json` | hand-curated | Aggregator pages (retailmenot, eatdrinkdeals, ...) for top 21 brands | Versioned config; changes via PR |
| `data/cache/spiritpool_dev/capture_queue.json` | `build_scrape_denial_queue.py` | First-party chain websites the scraper can't fetch | Regenerated every run; operational, not checked in |

The operator opens each URL in the enrolled Firefox profile (the
[Spiritpool_User](https://github.com/4Fortune8/Spiritpool_User) launcher),
lets the extension POST a capture, then re-runs:

```bash
python scripts/validate_spiritpool_capture.py
python scripts/harvest_hintbook_from_spiritpool.py
python scripts/compare_hintbook_to_deal_observations.py
```

Coverage goes up; the next `build_scrape_denial_queue.py` run skips hosts
now captured.

---

## 7. Known brand-onboarding gap (not solved by this pipeline)

As of 2026-04-21, every row in `local_employers` for `region='austin_tx'
AND is_active` has `source='overture'` (45,616 rows, one source). Darden
chains (Olive Garden, Red Lobster, LongHorn, Bahama Breeze) are absent
from the Overture extract. They appear as `NO_BRAND` in the seed manifest
gap regardless of how many captures are done, because no `brand_group`
or `local_employer` exists to hang observations on.

**Fix belongs elsewhere.** Candidates, in rough priority order:
1. Supplemental brand-seed ingest from Yelp Fusion / Google Places / a
   hand-maintained Darden chains list.
2. A second `local_employers.source` populated by a chain-store-locator
   crawl (each brand's own locations API).

Do not add a hintbook or SpiritPool-side workaround; that only masks the
upstream gap.

---

## 8. File reference

| Path | Role |
|---|---|
| `scripts/validate_spiritpool_capture.py` | Staging gate: raw → validated/quarantine |
| `scripts/harvest_hintbook_from_spiritpool.py` | Hintbook adapter run over validated bundles |
| `scripts/compare_hintbook_to_deal_observations.py` | Coverage report + seed manifest gap |
| `scripts/build_scrape_denial_queue.py` | Operator worklist from `restaurant_urls` |
| `collectors/hintbook/brand_matcher.py` | DB-backed brand vocab, smart-quote + `\b` matching |
| `collectors/hintbook/listing_walker.py` | Per-aggregator listing parser (public `parse_article_html`, `derive_proposals_from_record`) |
| `config/spiritpool_capture_manifest.json` | Aggregator-level capture priorities (versioned) |
| `data/cache/spiritpool_dev/page_captures/` | Raw signed bundles (from dev route) |
| `data/cache/spiritpool_dev/validated/` | Passed the staging gate |
| `data/cache/spiritpool_dev/quarantine/<reason>/` | Failed the staging gate |
| `data/cache/spiritpool_dev/capture_queue.json` | Current operator worklist |
| `data/cache/hintbook/spiritpool_runs/latest/` | Latest harvest + coverage output |
