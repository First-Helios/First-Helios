# MD-AGG-1 — Deal Aggregator "Cheat Sheet" Harvest & Cross-Reference Plan

> Status: **plan / audit**. No code changes proposed in this doc beyond
> registry entries and a single new collector module. Nothing here may
> be ingested as first-party deal evidence.

---

## 1. Hard architectural constraint (read first)

The meal-deal pipeline already enforces a three-layer separation:

| Layer | File | Role | May it land in `meal_deals` table? |
|---|---|---|---|
| **First-party evidence** | restaurant site + cached replay bundle | ingest source of truth | ✅ yes |
| **Hints** | `config/meal_deal_hint_registry.json` | exploration-only slugs / paths to probe on first-party domains | ❌ never |
| **Expectations** | `config/meal_deal_expectation_registry.json` | published claims, compared to replay bundles to mark coverage `found` / `missed` / `not_testable` | ❌ never |

Every aggregator in the user's list (EatDrinkDeals, BiteHunter, FoodDealNow,
KCL, Hip2Save, Slickdeals, DealNews, Sporked, Groupon, Yipit, LivingSocial,
RetailMeNot, DoorDash/Uber Eats/Grubhub offer pages) is **aggregator content,
not first-party**. Therefore:

* Their output maps into `hint_registry` (slug/path hints) and
  `expectation_registry` (expected label + match terms + `target_domain`).
* Their output **never** writes a `DealSignal`, a `DealMaterialization`,
  or any row in `meal_deals`.
* The value we extract from them is: "what deal *should* exist on
  `brand.com`?" and "what slug or path has recently been linked from an
  aggregator for that brand?" Both are inputs to re-audit and to the
  site-specific probe list in `website_scraper._discover_deal_pages`.

This is the guardrail in `docs/guides/MEAL_DEAL_FOUNDATION_ASSESSMENT.md`
and the ARCH-04 policy in `hint_registry.py`. It is **not** negotiable
by this plan.

---

## 2. Per-aggregator audit

Each row answers four questions:
**(a)** what is extractable, **(b)** how (HTTP, feed, JS render),
**(c)** where it plugs in (hint vs expectation vs brand-gap), and
**(d)** terms-of-service / rate posture.

### 2.1 Dedicated food / restaurant aggregators

#### EatDrinkDeals.com
* **Extractable:** per-brand deal posts with brand name, headline, price,
  valid dates, promo code, and usually a deep link to the brand's own
  promo page. Category tabs (happy hour / kids / lunch / dinner-for-two).
* **How:** static HTML, article-style; WordPress-ish markup. Feasible
  with `requests + bs4`. Listing pages paginate cleanly.
* **Plug-in:**
  - **Expectation** for almost every post — `brand`, `target_domain`,
    `expected_label` (headline), `match_any` (price, promo code), and
    the brand site the article links to becomes `target_domain`.
  - **Hint** when the outbound link is a stable first-party slug
    (e.g. `/deals`, `/promotions`, campaign paths like `/bogo-days`).
  - **Brand-gap input** when the referenced chain is not in
    `config/meal_deal_sources.yaml`.
* **ToS / posture:** personal use + attribution is normal; low rate,
  respect robots. Do not republish their copy.

#### BiteHunter.com
* **Extractable:** structured deal cards with restaurant name, neighborhood,
  deal type (happy hour, daily deal, event), time window.
* **How:** partly JS-rendered. Listing endpoints expose JSON in some
  flows; the rest needs the `collectors/playwright_fallback.py` renderer
  (but only for the index, not for each deal).
* **Plug-in:** mostly **expectations**. They aggregate *local independent*
  venues, not just chains, so output is keyed by venue name + address and
  compared against a resolved canonical venue (via `core/venue_identity`).
* **ToS / posture:** third-party aggregator — treat their data as a
  cross-check, never an ingest.

#### FoodDealNow.com
* **Extractable:** chain happy-hour times and menu specials in tabular
  form; good for **valid_days / valid_start_time / valid_end_time**
  ground truth.
* **How:** static HTML. Low-volume site.
* **Plug-in:** primarily **temporal expectations**. Compared against
  `temporal.py` output on replay bundles to catch missed day/time
  extraction, which is one of our known weak spots.

### 2.2 High-volume coupon / deal publishers

#### The Krazy Coupon Lady (`/tips/money/food-deals-near-me`)
* **Extractable:** long rolling lists with brand + promo code + expiry
  + "app-only" flags.
* **How:** static HTML, WordPress. Cheap to poll.
* **Plug-in:** **expectations + hints**. The "app-only" flag is
  especially valuable — it lets us mark brands as `app_only` in
  `meal_deal_sources.yaml` and stop blaming the scraper for legitimate
  coverage gaps.

#### Hip2Save (`/sales-deals/restaurants`)
* **Extractable:** BOGO + free side + app promo posts with headline,
  body, expiry, and the linked promo page.
* **How:** static HTML. Similar shape to KCL.
* **Plug-in:** **expectations + hints**. Their "personally tested" tag
  is a quality filter — prefer their posts over community-sourced ones
  when ranking expectation confidence.

#### Slickdeals (`/deals/restaurant`)
* **Extractable:** community deal listings with upvotes, expiry, and
  outbound brand URL.
* **How:** static HTML listing. There is also an (unofficial) RSS per
  category that is friendlier than HTML scraping.
* **Plug-in:** **hints** (outbound URL → probe slug on first-party) and
  low-weight **expectations**. Upvote count used as a recency/confidence
  tie-breaker only, never as evidence.

#### DealNews (`/c377/Food-Drink/Restaurants`)
* **Extractable:** 200+ deals/day with brand, headline, code, expiry.
* **How:** static HTML; they also expose feed-style endpoints for some
  categories.
* **Plug-in:** **expectations**. Highest volume — use as the primary
  weekly refresh source for the expectation registry.

#### Sporked
* **Extractable:** monthly roundups; editorial format, low volume.
* **How:** static HTML, article format.
* **Plug-in:** low-priority **expectations**. Good sanity checker, not a
  harvest target.

### 2.3 Broad aggregators (food + other)

#### Groupon
* **Extractable:** voucher-style offers keyed by **city + venue name**.
  Contains `original_price`, `discount_price`, `fine_print`.
* **How:** JSON API exists but is rate-limited / geo-gated; HTML is
  JS-rendered. Use Playwright index scrape or their partner feed.
* **Plug-in:** **price-ladder expectation**. Groupon's "original price"
  is an external baseline we can compare to `MenuSidecar`'s inferred
  baseline — a useful cross-check for the value-profile work.
* **Caveat:** Groupon offers are *voucher promotions*, not on-menu deals.
  They go in a separate expectation track so we don't confuse them with
  in-restaurant promos.

#### Yipit
* **Extractable:** aggregated Groupon + LivingSocial feed, newsletter
  digest form.
* **How:** email newsletter is the cleanest format; HTML is messy.
* **Plug-in:** de-duplicates Groupon/LivingSocial — low added value
  beyond Groupon itself. Defer.

#### LivingSocial
* **Extractable:** similar to Groupon, lower volume.
* **How:** static HTML; low traffic site.
* **Plug-in:** same expectation track as Groupon; secondary source.

#### RetailMeNot
* **Extractable:** promo codes by brand, often with "verified" timestamps.
* **How:** static HTML; some anti-bot, but tolerant of polite polling.
* **Plug-in:** **promo-code expectation**. When their code matches one we
  extracted from the brand's own page → coverage `found`. When it doesn't
  appear on the brand's page → `missed` (real gap) or site needs deeper
  probing.

### 2.4 Delivery platforms

These are *distribution* surfaces, not promoters:

* **DoorDash `/offers`**, **Uber Eats "Offers"**, **Grubhub `/promotions`**.
* **Extractable:** per-city offer cards tied to a specific venue.
* **How:** all three are heavily JS-rendered, geofenced, and ToS-hostile.
  DoorDash exposes a `dasher.doordash.com/offers` endpoint that is safer.
* **Plug-in:** **delivery-channel expectation only**. Gated behind a
  separate collector and its own feature flag. Treat as a distinct
  `source_channel` — a DoorDash offer is not evidence that the *venue*
  offers that deal; it is evidence that DoorDash offers that deal for
  that venue.
* **Recommend:** defer implementation. Out of scope for the first cheat-
  sheet pass.

---

## 3. What each aggregator harvest actually unlocks

Mapped to the audit spec's "final standard" — baseline spend + savings:

| Use | Aggregators that feed it |
|---|---|
| **Find missing brands** (chains not in `meal_deal_sources.yaml`) | EatDrinkDeals, KCL, Hip2Save, DealNews |
| **Find hidden first-party slugs** (ARCH-04 hints) | EatDrinkDeals, Slickdeals, Hip2Save — all three preserve outbound links to the brand's real promo page |
| **Temporal coverage gaps** (`valid_days`, `valid_start_time`) | FoodDealNow, EatDrinkDeals happy-hour tab |
| **Promo-code coverage** | RetailMeNot, DealNews, KCL |
| **App-only / delivery-only classification** | KCL flags, DoorDash/UE/GH |
| **External baseline price for savings calc** | Groupon's `original_price`, EatDrinkDeals posts with "reg. $X" |
| **Replay-based quality gates** (found / missed / not_testable) | every aggregator feeds the expectation registry |

---

## 4. Proposed collector: `collectors/meal_deals/aggregator_harvester.py`

A single new module, aligned with existing patterns:

```
collectors/meal_deals/
  aggregator_harvester.py          # NEW — crawls aggregators, emits
                                   # registry candidates (never DealSignals)
  aggregator_sources/              # NEW — per-aggregator adapters
    __init__.py
    eatdrinkdeals.py
    foodedealnow.py
    kcl.py
    hip2save.py
    slickdeals.py
    dealnews.py
    retailmenot.py
    sporked.py
    groupon.py                     # stub; gated
```

### Contract

Each adapter returns a list of `AggregatorRecord`:

```python
@dataclass(frozen=True)
class AggregatorRecord:
    aggregator: str                # e.g. "eatdrinkdeals"
    fetched_at: datetime
    source_url: str                # the aggregator article URL
    brand_hint: str | None         # e.g. "dennys"
    target_domain: str | None      # from outbound link, if first-party
    target_first_party_url: str | None
    headline: str                  # e.g. "$6.99 Value Slam"
    body_excerpt: str              # short, attribution-safe
    price_hint: float | None
    promo_code: str | None
    valid_through: date | None
    flags: frozenset[str]          # {"app_only", "delivery_only", "bogo", ...}
```

`aggregator_harvester.harvest_all()` then does two things, both idempotent:

1. **Write-to-hint-registry candidates.** For each record with a stable
   first-party slug, emit a `Hint` proposal JSON file into
   `data/cache/aggregator_hints/<date>/`. A human (or a follow-up task)
   reviews it before it lands in `config/meal_deal_hint_registry.json`,
   because the hint registry's contract requires verification against a
   first-party bundle.
2. **Write-to-expectation-registry candidates.** Same pattern: emit
   `Expectation` proposals into `data/cache/aggregator_expectations/<date>/`
   with `expected_label`, `match_any`, `target_domain`, `source`,
   `source_url`, `first_seen`, `last_verified=today`, `expires_at=today+90d`.
   The existing `expectation_registry.load_expectations()` already
   enforces schema + expiry, so the review step only needs to approve
   and `jq`-merge.

The harvester **never** touches `meal_deals`, `DealSignal`, `DealMaterialization`,
`brand_groups`, or `canonical_venues`. Its only side effects are JSON
proposal files and a run report.

### Scheduling

Add to `config/scheduler.yaml` as a weekly job, offset from
`chain_deals` so we don't stack outbound load. Polite rate: 1 req/s per
aggregator, with `collectors/cache.py` HTTP caching.

---

## 5. Cross-reference design

The point of harvesting is that expectations + hints become *cross-references*
against our first-party data. Three concrete joins, all reuse existing tables:

### 5.1 Brand-gap join
```
expectations.brand  LEFT JOIN  chain_deal_sources.keys
```
Any expectation whose `brand` has no entry in `meal_deal_sources.yaml`
is a coverage gap. Report once per harvest run into
`data/cache/aggregator_hints/<date>/_brand_gaps.json`.

### 5.2 Replay-coverage join (already partially designed)
For every expectation whose `target_domain` matches a cached replay
bundle in `data/cache/website_scrape_debug/`:
* run `expectation_registry.match_terms` against the bundle text
* emit one of `found` / `missed` / `not_testable`
Wire this into `scripts/reaudit_deal_observations.py` under a new
`--source expectations` mode. No new script.

### 5.3 Baseline-price cross-check
Where the aggregator captured an `original_price` (Groupon, "reg. $X"
phrasing on EatDrinkDeals), compare to `MenuSidecar.price_points` median
for the same brand. Discrepancies > 25% get queued for operator review.
This is the first concrete win for the savings-estimation goal called
out in the audit spec's "final standard."

---

## 6. Holistic sequencing

Do these in order. Each step is a self-contained, replayable PR.

1. **Stub the adapter package** (`aggregator_sources/__init__.py`
   + `AggregatorRecord` dataclass + harvester skeleton). No network
   calls; just the contract.
2. **Implement EatDrinkDeals + DealNews adapters first.** They have the
   broadest brand coverage and cleanest markup, so they produce the
   largest hint + expectation diff per run.
3. **Wire proposals → review step.** A small CLI
   (`scripts/review_aggregator_proposals.py`) that diffs proposal JSON
   against the live registry files and applies approved entries.
4. **Extend `reaudit_deal_observations.py`** with the replay-coverage
   join from §5.2, so harvested expectations immediately produce a
   `found / missed / not_testable` report on existing replay bundles.
   This is the feedback loop that makes the cheat sheet actually
   improve extraction.
5. **Add Hip2Save, KCL, Slickdeals, RetailMeNot, FoodDealNow adapters.**
   Order by brand-gap value per page fetched.
6. **Baseline-price cross-check** (§5.3). Requires `MenuSidecar`
   persistence (`menu_db_writer.py`) to be landed — already done per
   the tests listed in context. Deliverable: operator-review queue
   items when aggregator baseline disagrees with our inferred baseline.
7. **Groupon / delivery-platform adapters.** Gated, off by default,
   separate `source_channel`. Only after 1–6 are stable.
8. **Sporked / LivingSocial / Yipit.** Nice-to-have; low ROI.

---

## 7. Guardrails to re-state in PR descriptions

* No aggregator page content writes to `meal_deals`, `DealSignal`, or
  materialization tables. Ever.
* Every proposed hint carries `source`, `first_seen`, `last_verified`,
  `expires_at` (≤ 90 days), and `verified_against_url`. Proposals without
  a verifiable first-party URL are discarded, not merged.
* Every proposed expectation carries the same provenance + `match_any`
  terms. Expired entries auto-filter via the existing loader.
* Review step is mandatory before either registry file is updated. The
  harvester itself has *no write access* to `config/meal_deal_*.json`.
* Attribution + polite rate-limits per aggregator. Use
  `collectors/cache.py` to avoid re-fetching the same article inside a
  run window.

---

## 8. What this unlocks (tie-back to the audit spec "final standard")

* "**What does the restaurant normally charge?**" — Groupon's `original_price`
  and EatDrinkDeals "reg." prices provide an external baseline that
  cross-references `MenuSidecar.price_points`.
* "**What is the promotion changing relative to that baseline?**" —
  expectations carry the aggregator's claimed promo price; the replay
  join turns that into a savings delta per brand, testable on every
  future scrape.
* **Category-aware planning**, **temporal windows**, **app-only
  classification**, and **brand-coverage gaps** all get a durable,
  auditable input that today depends on chat-level intuition.

That is the minimum bar for calling the cheat-sheet integration
"complete."
