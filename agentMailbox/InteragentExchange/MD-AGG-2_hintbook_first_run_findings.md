# Hintbook First-Run Findings — 2026-04-21

Harvest source: `collectors/hintbook/` (new module, this session).
Report file: [data/cache/hintbook/runs/latest.json](../../data/cache/hintbook/runs/latest.json).

## Legal / architectural posture

This module scrapes competitor aggregator sites **purely to observe the
competitive deal landscape**. Every artifact it produces is one of:

1. A `HintProposal` — a candidate entry for
   `config/meal_deal_hint_registry.json`, the ARCH-04 exploration-only
   registry. Hints only point us at first-party URLs; they never count
   as evidence and require verification against the restaurant's own
   site before they influence ingest.
2. An `ExpectationProposal` — a candidate entry for
   `config/meal_deal_expectation_registry.json`, the quality-check-only
   registry. Expectations encode "brand X *claims* to offer Y" and are
   compared against first-party replay bundles to produce
   `found / missed / not_testable` coverage reports.
3. An `IndustrySample` — a landscape observation (which industries the
   competition covers and whether those industries map to a venue).

No record from this module ever reaches `meal_deals`, `DealSignal`,
`DealMaterialization`, or any customer-facing table. Every deal we
surface to users must come from our own first-party restaurant-site
collection. This is the line that protects us: observing a competitor's
coverage is competitive intelligence; re-serving their data would be
misappropriation.

## Run summary (live fetch, 2026-04-21)

| Adapter | Records | Notes |
|---|---:|---|
| `eatdrinkdeals` | 50 | Cleanest markup; dominant source of outbound first-party links. Two guessed category slugs 404'd — see below. |
| `kcl` | 14 | Homepage listing works; guessed `/topic/…` and `/tips/…/best-food-delivery-deals` 404'd. |
| `fooddealnow` | 12 | Happy-hour + dailies seed worked; category URLs fine. |
| `hip2save` | 3 | `/sales-deals/restaurants/` worked; `/category/*` slugs 404. |
| `dealnews` | 0 | Listing page returned content but our walker found no article cards in their markup — needs site-specific selector. |
| `slickdeals` | 0 | Deals category URLs 404 (guessed slugs wrong). Listings are also JS-rendered. |
| `retailmenot` | 0 | **All URLs returned HTTP 403** to our User-Agent. Needs a different posture (session cookies or partner feed) or skip. |
| `bitehunter` | 0 | Homepage fetched but is a JS SPA — no static article cards. |
| `broader_industries` | 11 samples | DealNews category pages served (3 headlines each via h2/h3 heuristic). Slickdeals + RetailMeNot blocked / 404'd. |

Totals: **79 records, 48 hint proposals, 61 expectation proposals,
11 industry samples, 27 fetch failures**.

## Proof the hint pipeline works

Representative hint proposals actually produced this run (outbound
first-party links extracted from aggregator articles):

| Brand hint | First-party domain | Slug probe |
|---|---|---|
| jimmy johns | `jimmyjohns.com` | `/rewards` |
| starbucks | `starbucks.com` | `/account/create` |
| moes | `moes.com` | `/offers` |
| wendys | `order.wendys.com` | `/rewards-store` |
| applebees | `applebees.com` | `/en/menu/2-for-25/2-for-25` |
| olive garden | `media.olivegarden.com` | `/en_us/pdf/OG_FY26_BOTO_eClub_Early_Access.pdf` |
| mcdonalds | `corporate.mcdonalds.com` | `/corpmcd/our-stories/article/...mcvalue...` |
| smoothieking | `smoothieking.com` | `/healthy-rewards` |

These are **slugs to probe on the restaurant's own site** (or in our
cached replay bundles). They are not evidence. The Olive Garden PDF and
the Applebee's 2-for-25 page are exactly the class of hidden-promo path
the audit spec called out as under-discovered today.

## What the broader-industry scan tells us

From the DealNews category walks (the only generalist aggregator that
answered us cleanly), the competitive landscape splits into two product
shapes that cleanly match our taxonomy in
[collectors/hintbook/industry_taxonomy.py](../../collectors/hintbook/industry_taxonomy.py):

**Map-viable (venue-anchored) — adjacent expansions that fit our map UX:**
- `food` (core)
- `grocery` (weekly circulars, chain stores)
- `automotive_service` — oil change, tires, brake work (Valvoline,
  Jiffy Lube, Firestone, Midas). *Structurally identical to restaurant
  chains — same brand/venue pattern, same per-location promo model.*
- `automotive_retail` — AutoZone/O'Reilly/Advance Auto
- `car_wash`
- `gas_fuel` (adjacent — hybrid map + app)
- `fitness_gym`
- `beauty_salon`
- `entertainment_venue`
- `pharmacy_health` (CVS/Walgreens/LensCrafters/Aspen Dental)
- `pet_services`
- `travel_hotel` (hybrid — geo-anchored but booked online)

**Deal-framework only (not map-shaped):**
- `travel_air`, `travel_rental`, `travel_cruise_package`
- `retail_apparel`, `retail_electronics`, `retail_home`
- `subscription_software`
- `financial_signup`

Product implication: the highest-ROI adjacency is **automotive_service**
— same "brand + local venue + recurring promo" shape as food, and a
category where promo codes are genuinely useful to consumers. Every
other map-viable adjacency follows the same template: venue identity
→ first-party site → deals page. The scraper infrastructure we already
built for food transfers directly.

## Concrete gaps this run exposed (scraper work, not data)

1. **RetailMeNot blocks our User-Agent.** Every URL returned 403. Options:
   (a) drop RMN from the harvest, (b) use their partner feed if available,
   (c) rotate through `collectors/rotation.py` UAs. Recommend **drop for
   now** and re-add only if the brand-gap report shows RMN covers brands
   no other aggregator does.
2. **Slickdeals and BiteHunter are JS-rendered.** Static HTML produced
   zero cards. Options: (a) hit their RSS/JSON endpoints directly, or
   (b) wire `collectors/playwright_fallback.py` for these two. Both are
   deferrable — EatDrinkDeals + KCL + FoodDealNow + Hip2Save already
   yielded meaningful proposals.
3. **DealNews category pages** need site-specific card selectors.
   Current walker only found headers inside their nav/chrome, not
   listing cards. Small follow-up.
4. **Several guessed category slugs 404'd** (EatDrinkDeals
   `/happy-hour-deals/`, KCL `/topic/restaurant-coupons`, Hip2Save
   `/category/food-deals/`, Slickdeals `/deals/restaurants/`). They need
   their real current slugs. This is exactly the kind of fact the
   hintbook is *supposed* to discover and correct over time — the
   failures are logged in the report and should drive the next iteration.
5. **EatDrinkDeals brand-hint heuristic** is noisy — it produced
   slugs like `jimmyjohnspromocodes` and `mondayrestaurantdeals`
   because headlines start with multi-word promo phrases rather than the
   pure brand. The hint proposal review step needs to normalize these
   against our existing `brand_groups` table before they become real
   registry entries.

## Cross-reference plan (next work)

These steps turn the harvested proposals into actual upstream wins:

1. **Brand-gap report.** Join proposal `target_domain` against
   `config/meal_deal_sources.yaml` + `brand_groups.canonical_name`. Any
   brand appearing in proposals but missing from our sources is a
   coverage gap. First-run target domains to check against our registry:
   `applebees.com`, `redrobin.com`, `jimmyjohns.com`, `pizzahut.com`,
   `dominos.com`, `starbucks.com`, `sonicdrivein.com`, `wingstop.com`,
   `moes.com`, `noodles.com`, `smoothieking.com`, `shakeshack.com`,
   `krispykreme.com`, `arbys.com`.
2. **Replay coverage join.** For every proposed expectation, if we have
   a cached replay bundle under
   `data/cache/website_scrape_debug/` for that target domain, run the
   expectation's `match_any` terms against the bundle text and emit
   `found / missed / not_testable`. Wire this as a new mode in
   `scripts/reaudit_deal_observations.py`. The Applebee's `2-for-25`
   slug is a good first test case — check whether our cached Applebee's
   bundle contains that string.
3. **Hint merge CLI.** Small script
   `scripts/review_hintbook_proposals.py` that diffs the proposals
   against the live registry files, lets the operator approve entries
   one at a time, and writes merged entries with required provenance
   (`first_seen`, `last_verified`, `expires_at=today+90d`,
   `verified_against_url` set only after a first-party probe succeeds).
4. **Schedule.** Add to `config/scheduler.yaml` as a weekly job at a
   low-priority slot. The fetcher already caches per URL for 24h so
   re-runs are cheap.
5. **Brand-hint normalization.** Before promoting any hint proposal to
   the live registry, resolve `brand_hint` against
   `core/venue_identity` / `brand_groups`. Reject hints that can't be
   mapped to a known brand.

## What to do about non-food industries

Decision is clean given the data:

- Build **automotive_service** next if we expand. Reuse the whole food
  scraper stack; only the source registry and a lightweight
  "category=auto_service" flag on `meal_deal_sources.yaml` would change.
- Keep the rest of the map-viable categories as *taxonomy only* for now
  — we track what competitors cover so we can size the opportunity, but
  we don't build collectors until food is fully solid.
- For deal-framework-only industries (flights, apparel, electronics,
  SaaS), do **not** build anything that lives alongside the map. If we
  ever want those, they're a separate product surface — a promo feed,
  not a venue map — and should live in a different module.

## Files added this session

| File | Role |
|---|---|
| [collectors/hintbook/__init__.py](../../collectors/hintbook/__init__.py) | Package + legal-scope docstring |
| [collectors/hintbook/models.py](../../collectors/hintbook/models.py) | `AggregatorRecord`, `HintProposal`, `ExpectationProposal`, `IndustrySample`, `HarvestReport` |
| [collectors/hintbook/fetcher.py](../../collectors/hintbook/fetcher.py) | Polite HTTP fetcher with per-URL disk cache |
| [collectors/hintbook/parsing.py](../../collectors/hintbook/parsing.py) | Shared headline/price/promo-code/outbound-link parsers |
| [collectors/hintbook/industry_taxonomy.py](../../collectors/hintbook/industry_taxonomy.py) | Industry → map_viable classification |
| [collectors/hintbook/listing_walker.py](../../collectors/hintbook/listing_walker.py) | Shared article-listing crawl + proposal derivation |
| [collectors/hintbook/registry.py](../../collectors/hintbook/registry.py) | Adapter registry |
| [collectors/hintbook/runner.py](../../collectors/hintbook/runner.py) | `python -m collectors.hintbook.runner` CLI |
| [collectors/hintbook/adapters/eatdrinkdeals.py](../../collectors/hintbook/adapters/eatdrinkdeals.py) | Food: EatDrinkDeals |
| [collectors/hintbook/adapters/dealnews.py](../../collectors/hintbook/adapters/dealnews.py) | Food: DealNews |
| [collectors/hintbook/adapters/fooddealnow.py](../../collectors/hintbook/adapters/fooddealnow.py) | Food: FoodDealNow |
| [collectors/hintbook/adapters/kcl.py](../../collectors/hintbook/adapters/kcl.py) | Food: KCL |
| [collectors/hintbook/adapters/hip2save.py](../../collectors/hintbook/adapters/hip2save.py) | Food: Hip2Save |
| [collectors/hintbook/adapters/slickdeals.py](../../collectors/hintbook/adapters/slickdeals.py) | Food: Slickdeals (JS-rendered, zero yield this run) |
| [collectors/hintbook/adapters/retailmenot.py](../../collectors/hintbook/adapters/retailmenot.py) | Food: RetailMeNot (403'd this run) |
| [collectors/hintbook/adapters/bitehunter.py](../../collectors/hintbook/adapters/bitehunter.py) | Food: BiteHunter (JS-rendered) |
| [collectors/hintbook/adapters/broader_industries.py](../../collectors/hintbook/adapters/broader_industries.py) | Non-food industry landscape sampler |

Report artifacts:
[data/cache/hintbook/runs/](../../data/cache/hintbook/runs/) — one file
per run plus `latest.json`. Per-URL HTML cache under
[data/cache/hintbook/fetch/](../../data/cache/hintbook/fetch/).
