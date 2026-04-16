# Meal Deal Signal Quality Overhaul — Plan

## Current State (2026-04-15)

**3,190 rows** in `meal_deals`. Sources: `website_scrape` (2,287), `chain_website` (903).
- **54.6% have NULL price** (1,743 rows) — over half our signals have no price at all
- **Only 0.9% have valid_days populated** (29/3,190) despite many descriptions containing day info
- **773 rows have no/empty description** (<10 chars)
- **140 rows** where the captured price is explicitly a "$X off" discount, not a meal price
- **58x duplication** for McDonald's (same deal copied to every location), 30x Wendy's, 29x Domino's

---

## Issue Catalog

### Issues from MealDeal.MD (user-identified)

#### Issue 1: Address Mismatch Duplicates
**Example:** Yard House at "11800 Domain Blvd" vs "Yardhouse Domain" at "11811 Domain Dr" — same physical location, two employer records, deals duplicated across both.

**Also found in DB:** `The League Kitchen & Tavern` has 3 employer IDs (#32, #966, #3104) with slightly different addresses ("1310 Ranch Road 620 S" vs "1310 RR 620 S, Bldg C-1"). `Barton BBQ` and `The Green Mesquite BBQ & More` and `The Green Mesquite BBQ` all share the same deal text — likely the same business with 3 different employer records.

**Root cause:** `local_employers` dedup is fingerprint-based on (name, address). Minor address variations (Blvd vs Dr, abbreviations, suite numbers) create separate records. No geocoding proximity merge.

#### Issue 2: "$X Off" Captured as Deal Price
**Example:** Jack Allen's Kitchen happy hour: "1/2 priced appetizers and $1 off all drinks" → stored as `price=$1.00`. The $1 is a *discount amount*, not a deal price.

**Scale:** 140 confirmed rows where description contains "$X off/discount" pattern. Many more where the first `$` in the text happens to be a discount amount rather than the deal price.

**Root cause:** `_extract_price()` in website_scraper.py returns the **first** `$X.XX` match in the text block. For happy hours and discounts, the first dollar amount is almost always the discount, not the item price.

#### Issue 3: Add-On Prices Captured as Deals
**Example:** Delaware Sub Shop "Hot Subs — grilled mushrooms & onions included" at `$1.00` — the $1 is an add-on topping price, not a meal deal. Texas Street Grill "Pancakes Add Blueberries for +$1" at `$1.00`.

**Also found:** Thunder Cloud Subs has `$0.35` "Add Ons Veggies" captured as a combo deal.

**Root cause:** The text block contains a deal keyword ("combo") and a price, passing `_is_valid_deal_block()`. No distinction between add-on/modifier prices and actual meal prices.

#### Issue 4: Multi-Promo Deals Crammed into One Record
**Example:** Rumi's Tavern — "Happy Hour MON-FRI 3-6pm $1 Off All Drinks Enjoy $3 off all appetizers" — two separate promos stored as one record with `price=$1.00`.

**Also found in DB:** Casa Moreno's: "$1 Off Bottle Beer $1 Off Draft Beer $5 Frozen Margaritas" — 3 sub-deals in one row. Cain & Abel's: "$4 wells $8 Teas $1 off drafts" — 3 different price points in one record.

**Root cause:** Scraper treats each text block as one deal. Happy hour pages often list multiple concurrent promotions in a single paragraph/section. No logic to split multi-offer text.

#### Issue 5: "Half Off" Not Captured / Loses to Smaller Dollar Amount
**Example:** League Kitchen: "half off Appetizers, $1 off Cocktails, $2 off wine" → stored as `price=$1.00` (happy_hour). The half-off appetizers are the *better* deal but there's no way to represent percentage discounts.

**Scale:** 14 rows explicitly mention "half off" or "½ off". The `deal_type` set has `bogo` (52 rows) but no `half_off` or `percentage_off`.

**Root cause:** No `price_type` field to distinguish absolute price vs discount amount vs percentage. `_extract_price()` grabs the first dollar figure; percentage-based deals have no dollar figure to grab.

#### Issue 6: No Minimum Price Threshold
**Example:** "Twenty Cent Ranch" at `$0.20` (8 duplicates of this). Also 4 rows at `$0.00` ("For orders totaling $0.00 or more...").

**But careful:** "$1 Wings" at Barton BBQ is a valid `$1.00` deal.

**Root cause:** No floor filter on `price`. Sub-$1 amounts are almost always add-ons, modifiers, or parsing artifacts. A threshold of ~$1.50 would catch most junk while preserving legitimate "$1 wings" type deals if we also check for food keywords.

#### Issue 7: Nonsense / No-Signal Chatter
**Example:** Green Mesquite: "Who doesn't love a good deal? Our daily specials are where it's at!" — contains deal keyword "specials" and "deal" but zero actual deal information.

**Also found:** 106 descriptions under 20 characters, 773 with no/empty description. Deals like "Values In Action" (58x) and "Check out how you can save anytime of the day with McValue" (58x) are marketing slogans, not deals.

**Root cause:** `_is_valid_deal_block()` only requires a deal keyword + (price OR self-validating keyword). Marketing copy with "deal"/"special"/"save" passes the keyword check. No semantic content validation.

#### Issue 8: Spam / Non-Food Promotions
**Example:** WhaTaTaco: "$1,500 off when you book a Saturday event" — event venue promo, not a food deal. Also TCBY showing "60% off everything, plus 50-70% off clearance" — this is J.Crew retail data leaking through a shared page or wrong URL.

**Root cause:** No content-type validation distinguishing food deals from event bookings, retail promos, or catering packages. The `$1,500` was parsed as `$1.00` (regex captures `$1` from `$1,500`).

---

### Additional Issues Found from DB Analysis

#### Issue 9: Chain Fan-Out Bloat
**Scale:** McDonald's 11 deals x 58 locations = 638 identical rows. Wendy's 5 deals x 30 locations = 150. Domino's 7 deals x ~29 locations = ~200. Total: **~1,000 rows** (31% of DB) are duplicate chain content.

The unique constraint `(local_employer_id, deal_name, source)` allows this by design — each location gets its own copy. But the data is identical. This inflates counts, makes queries slower, and makes the 58x "Values In Action" noise harder to clean.

**Recommendation:** Store chain deals once at the `brand_group` level, not fanned out to every location. Join at query time. This eliminates ~900 duplicate rows.

#### Issue 10: Garbage Deal Names Still in DB
Despite `_JUNK_DEAL_NAMES` blocklist in ingest.py, the DB still contains:
- "Main navigation" (30x) — Wendy's nav element
- "SELECT A LOCATION Select your nearest Yard House..." (6x)  
- "Values" (30x), "What We Value" (30x) — Wendy's slogans
- "Learn more about The Green Mesquite BBQ..." (6x)

**Root cause:** The junk filter matches exact lowercase strings. "Main navigation" IS in the blocklist but "Main navigation" with different casing or extra whitespace may slip through. More importantly, the longer phrases like "SELECT A LOCATION..." aren't caught because the blocklist uses exact match, not substring.

#### Issue 11: Temporal Data Extraction Almost Entirely Failing
**29 out of 3,190** rows have `valid_days` populated (0.9%). **25** have `valid_start_time`. Yet hundreds of descriptions contain explicit time/day info like "Mon-Fri 3PM-6PM" or "every weekday from 3pm to 6pm".

**Root cause:** `_extract_days()` only captures the *first* day match. "Mon - Fri" is two separate matches but the regex only returns one. Ranges like "Mon-Fri" are in the regex but "Monday - Friday" with spaces isn't. The time extraction `_extract_times()` works but is only called for website_scrape deals — chain_deals.py doesn't extract times at all.

#### Issue 12: Cross-Employer Data Leaks
- `Freddie's Place` has Fresa's happy hour description ("Happy Hour Para Todos At Fresa's...")
- `Barton BBQ` has Green Mesquite BBQ content
- Multiple employer IDs show identical deal text for different businesses

**Root cause:** When multiple `local_employer` records share the same website URL (e.g., same strip mall, same owner), the website scraper fans out all deals from that URL to every employer associated with it. No validation that the deal content matches the restaurant name.

#### Issue 13: The `price` Field Conflates Three Different Concepts
Currently `price` stores:
- **Absolute deal price**: "$5.99 combo meal" → `5.99` (this is what we want)
- **Discount amount**: "$1 off cocktails" → `1.00` (misleading)
- **First-dollar-found noise**: "$0.20 ranch" → `0.20` (garbage)

There is no field to tell them apart. A user looking at `price=$1.00` can't know if it's a $1 wings deal or a $1-off-drinks discount.

#### Issue 14: Deal Name is Often a Text Fragment, Not a Name
`deal_name` is built by `block.split(".")[0].strip()[:80]` — takes everything before the first period, truncated to 80 chars. This produces:
- "A spicy stir-fried dish made with breaded chicken or seasoned beef, celery, bell" (truncated description)
- "Your choice of chicken or tofu, Beef (add $2 extra), Shrimp or Combo Meat (add $" (menu item text)
- "Get 20% off your next order of $50 ($20 max discount) or more when you enter rew" (marketing copy)

These are not deal names. They're scraped text fragments.

#### Issue 15: NULL Price Dominates the Dataset
1,743 rows (54.6%) have `price=NULL`. Breakdown by type:
- combo: 653 NULL out of 1,824 (36%)
- happy_hour: 627 NULL out of 850 (74%)
- daily_special: 383 NULL out of 404 (95%)
- bogo: 50 NULL out of 52 (96%)
- kids_eat_free: 30 NULL out of 33 (91%)

For every type except `combo`, the vast majority of deals have no price. This means most of our "signals" are just text fragments with a deal keyword — they tell you a deal *exists* but not what it costs.

---

## Structural Changes Required

### Schema Changes (migration)

#### A. New `price_type` enum column
```
price_type: "absolute" | "discount_amount" | "percentage_off" | "unknown"
```
Distinguishes "$5.99 combo" from "$1 off" from "50% off". Default: "unknown" for existing rows.

#### B. New `discount_percentage` column
```
discount_percentage: float | null  -- e.g., 50.0 for "half off"
```
Captures percentage-based deals that currently have no numeric representation.

#### C. New `raw_scraped_text` column
```
raw_scraped_text: text | null  -- original text block before any parsing
```
Preserves the source material so deals can be reprocessed when extraction logic improves, without re-scraping.

#### D. New `signal_quality` score column
```
signal_quality: float  -- 0.0 to 1.0, computed at ingest
```
Composite score based on: has price (0.3), has time window (0.2), has description (0.2), name isn't a fragment (0.15), passes content validation (0.15). Allows filtering/sorting by quality without deleting borderline signals.

#### E. New `sub_deals` JSONB column (or separate `deal_items` table)
```
sub_deals: jsonb | null
-- e.g., [{"item": "appetizers", "discount": "half off"}, {"item": "cocktails", "discount": "$1 off"}]
```
Handles Issue 4 (multi-promo happy hours) by decomposing a single promotional block into individual offers.

#### F. Reconsider chain deal storage
Add `is_chain_template` boolean or create a `chain_deal_templates` table that stores the deal once, with a view/join that resolves to locations at query time. Eliminates the 58x McDonald's duplication.

### Extraction Pipeline Changes

#### G. Price extraction overhaul (`_extract_price` → `_extract_deal_pricing`)
Replace the "first dollar amount found" approach with context-aware extraction:

1. **Scan all `$X.XX` occurrences** in the text block, not just the first
2. **Check surrounding words** for each price:
   - "off", "discount", "save" → `price_type = "discount_amount"`
   - "for", "just", "only", "combo", "meal" → `price_type = "absolute"`
   - "add", "extra", "+$" → skip entirely (add-on, not a deal)
3. **Check for percentage patterns**: "half off", "½ off", "50% off", "X% off" → `price_type = "percentage_off"`, `discount_percentage = X`
4. **Prefer absolute prices** over discount amounts when both exist
5. **Apply floor**: skip prices < $1.00 unless preceded by food keywords ("wings", "tacos", "sliders")

#### H. Multi-promo splitter
When a text block contains 3+ distinct `$X` amounts OR multiple "[item] [discount]" patterns:
1. Attempt to split into sub-deals using sentence boundaries and "$" anchors
2. Store the most valuable sub-deal as the primary `price`
3. Store all sub-deals in `sub_deals` JSONB

#### I. Deal name extraction overhaul
Replace `block.split(".")[0][:80]` with:
1. **Prefer heading text** if the deal came from a heading+sibling extraction
2. **Extract a short label**: look for phrases like "Happy Hour", "Lunch Special", "$5 Combo" as the name
3. **Fallback**: first clause up to first comma/period, max 60 chars, but validate it reads like a name (not a sentence fragment)
4. **Blocklist expansion**: add substring matches for "select a location", "learn more about", "check out how", "who doesn't love"

#### J. Temporal extraction fix
1. **Day ranges**: parse "Monday - Friday", "Mon – Fri", "Mon thru Fri", "weekdays", "every day", "daily" (not just single day names)
2. **Time ranges**: handle "3pm to 6pm", "3PM – Close", "3-6:30PM", "11am-1pm"
3. **Apply to chain_deals.py too** — currently only website_scraper.py extracts time/day
4. **"Close" as end_time**: map to null or a sentinel; it's better than losing the start time

#### K. Content validation / signal quality scoring
Before ingest, compute `signal_quality` from:
| Factor | Weight | Criteria |
|--------|--------|----------|
| Has usable price | 0.25 | `price IS NOT NULL AND price >= 1.50 AND price_type != 'unknown'` |
| Has time/day window | 0.20 | `valid_days OR valid_start_time` populated |
| Has meaningful description | 0.15 | description > 30 chars AND not boilerplate |
| Deal name is real | 0.15 | < 60 chars, not a sentence, not nav text |
| Content matches restaurant | 0.10 | restaurant name appears in deal text OR no other restaurant names appear |
| Not an add-on/modifier | 0.15 | no "+$", "add", "extra" context |

Deals scoring < 0.2 are rejected at ingest. Deals 0.2–0.4 are stored but flagged `is_active = false` for manual review. > 0.4 are active.

### Data Cleanup (one-time)

#### L. Purge or reclassify existing bad data
Run against current 3,190 rows:

1. **Delete $0.00 deals** (4 rows) — "For orders totaling $0.00" is not a deal
2. **Delete sub-$1.00 non-food deals** (9 rows) — "$0.20 ranch", "$0.35 add-ons"
3. **Reclassify $X off deals**: set `price_type = 'discount_amount'` for 140 rows where description contains "$X off/discount"
4. **Set `price_type = 'percentage_off'`** for ~14 rows mentioning "half off"/"½ off"
5. **Delete nav/boilerplate** that slipped through: "Main navigation" (30), "Values" (30), "What We Value" (30), "SELECT A LOCATION" (6), "Values In Action" (58), "Wanna save $$?" (58), "Check out how you can save" (58)
6. **Delete TCBY J.Crew data** (10 rows) — retail clearance leak, not food
7. **Delete WhaTaTaco event spam** — "$1,500 off event" is not a meal deal
8. **Fix cross-employer leaks**: identify rows where deal_description mentions a different restaurant name than the employer, flag for review
9. **Deduplicate chain deals**: collapse 58x identical McDonald's rows into either 1 template row or mark extras inactive

#### M. Backfill temporal data
Write a one-time script that re-parses `deal_description` for all existing rows using the improved day/time extraction (change J), updating `valid_days`, `valid_start_time`, `valid_end_time`.

---

## Implementation Priority

### Phase 1 — Stop the bleeding (prevent new bad data) ✅ COMPLETE (2026-04-15)
1. ✅ Schema migration `f7a1b2c3d4e5`: added `price_type`, `discount_percentage`, `raw_scraped_text`, `signal_quality` columns. Backfilled 1,447 existing priced rows with `price_type='unknown'`.
2. ✅ Price extraction overhaul (G) — replaced naive `_extract_price()` with context-aware `_extract_deal_pricing()` in website_scraper.py. Scans all `$X.XX` occurrences, classifies each by surrounding words (off/discount → discount_amount, for/just/only/combo → absolute), prefers absolute prices over discounts.
3. ✅ Minimum price floor $1.00 with food-keyword exception (part of G) — `_FOOD_KEYWORDS_RE` allows "$1 Wings" through while blocking "$0.20 ranch". 
4. ✅ Expanded junk name blocklist (part of I) — added 10+ new substring patterns to `_JUNK_SUBSTRINGS` in ingest.py matching DB-observed junk ("select a location", "learn more about", "check out how you can save", etc.)
5. ✅ Add-on detection and rejection (part of G) — `_ADDON_CONTEXT_RE` catches "+$X", "add ... $X", "extra ... $X", "upgrade ... $X" patterns. Non-food promo detection via `_NON_FOOD_PROMO_RE` catches event bookings/catering/retail.
6. ✅ Updated ingest.py upsert to pass through all new fields
7. ✅ Updated purge_junk_deals.py with aligned blocklists + non-food promo detection
8. ✅ Updated DealSignal dataclass and MealDeal ORM model with new fields

**Verified test results:**
- "$1 off drinks" → `price_type=discount_amount` (was: misclassified as meal price)
- "+$1 add peppers" → rejected as add-on (was: stored as $1 combo)
- "$5.99 combo" → `price_type=absolute` (correct)
- "half off apps, $1 off cocktails" → `pct=50.0, type=percentage_off` (was: $1 only)
- "$0.20 ranch" → rejected by floor (was: stored as $0.20 combo)
- "$1 Wings" → passes floor via food keyword (correct)
- "$1,500 off event booking" → rejected as non-food (was: stored as $1 combo)

### Phase 2 — Recover lost signals ✅ COMPLETE (2026-04-15)
6. ✅ Temporal extraction fix (J) — new shared module [collectors/meal_deals/temporal.py](collectors/meal_deals/temporal.py) handles day ranges ("Mon-Fri", "Monday through Friday", "weekdays"), time ranges ("3-6pm", "11:00 AM – 2:00 PM"), "Close" sentinel, and is wired into both [website_scraper.py](collectors/meal_deals/website_scraper.py) and [chain_deals.py](collectors/meal_deals/chain_deals.py). Also passes `raw_scraped_text` to DealSignal from chain_deals.
7. ✅ Temporal backfill (M) — [scripts/backfill_deal_temporal.py](scripts/backfill_deal_temporal.py) re-parses existing rows. Applied to live DB: 1,220 row updates committed.
8. ✅ Percentage/half-off capture — already covered by Phase 1 `_extract_deal_pricing` (`_PERCENTAGE_RE` captures "half off", "½ off", "X% off").
9. ✅ Multi-promo splitter (H) — `_split_multi_promo` in website_scraper.py splits text blocks with 3+ `$X` amounts into sub-deals, each becoming its own DealSignal with its own name, price, and price_type. Wrapped in helper `_text_block_to_signals`.
10. ✅ Deal name extraction overhaul (I) — `_extract_deal_name` replaces `block.split(".")[0][:80]` in all 3 extraction sites (Phase 1 hardcoded paths, Phase 2 discovered pages, PDF parser). Uses label-pattern matching (Happy Hour, Kids Eat Free, $5 Combo, BOGO, Lunch Special, …) with heading override and fragment-marker rejection.

**Verified test results:**
- "Happy Hour Mon-Fri 3-6pm. $1 Off Bottle Beer. $1 Off Draft Beer. $5 Frozen Margaritas." → 4 split sub-deals with correct names, prices, price_types
- "Monday through Friday 11:00 AM to 2:00 PM" → `days=Mon-Fri, start=11:00 AM, end=2:00 PM`
- "Weekends 10am-2pm" → `days=Sat-Sun, start=10:00 AM, end=2:00 PM`
- "3PM – Close" → `start=3:00 PM, end=Close`
- "A spicy stir-fried dish made with breaded chicken…" → name=None (fragment rejected)
- "$5.99 Combo Meal — burger, fries, drink" → name="$5.99 Combo Meal — burger, fries, drink"

**Metric impact (live DB, 4,317 rows):**
| Metric | Before Phase 2 | After Phase 2 |
|---|---|---|
| Rows with valid_days | 29 (0.9%) | 1,099 (25.5%) |
| Rows with valid_start_time | 25 (0.8%) | 836 (19.4%) |
| Rows with valid_end_time | ~20 (0.6%) | 795 (18.4%) |

### Phase 3 — Structural cleanup
10. Signal quality scoring (K) — gates new data AND lets us triage existing
11. Chain deal deduplication redesign (F)
12. One-time data cleanup script (L)
13. Cross-employer leak detection (L.8)

### Phase 4 — Prevention
14. Add `raw_scraped_text` preservation so future extraction improvements don't require re-scraping
15. `sub_deals` JSONB for multi-promo representation (E)
16. Automated quality dashboards / alerts when signal_quality drops

---

## Example Transformations

### Before (current)
```
Employer: Jack Allen's Kitchen
deal_name: "HAPPY Hour Mon: 3PM – Close Tues – Fri: 3PM – 6:30PM Featuri"
deal_type: happy_hour
price: 1.00          ← this is "$1 off drinks", not a $1 meal
valid_days: NULL     ← "Mon-Fri" is in the text but not extracted  
valid_start_time: NULL ← "3PM" is in the text but not extracted
```

### After (with changes)
```
Employer: Jack Allen's Kitchen  
deal_name: "Happy Hour"
deal_type: happy_hour
price: 1.00
price_type: discount_amount
discount_percentage: 50.0    ← "1/2 priced appetizers"
valid_days: "Mon-Fri"
valid_start_time: "3:00 PM"
valid_end_time: "6:30 PM"
signal_quality: 0.85
sub_deals: [
  {"item": "appetizers", "discount_type": "percentage_off", "discount_value": 50},
  {"item": "drinks", "discount_type": "discount_amount", "discount_value": 1.00}
]
raw_scraped_text: "HAPPY Hour Mon: 3PM – Close Tues – Fri: 3PM – 6:30PM Featuring 1/2 priced appetizers and $1 off all drinks"
```

### Before
```
Employer: League Kitchen
deal_name: "Happy Hour Happy Hour is every weekday from 3pm to 6pm with "
price: 1.00          ← "$1 off Cocktails", but "half off Appetizers" is better
deal_type: happy_hour
```

### After
```
Employer: League Kitchen
deal_name: "Happy Hour"
price: NULL           ← no single absolute price; see sub_deals
price_type: NULL
discount_percentage: 50.0  ← best offer is half-off apps
valid_days: "Mon-Fri"
valid_start_time: "3:00 PM"
valid_end_time: "6:00 PM"
signal_quality: 0.80
sub_deals: [
  {"item": "Appetizers", "discount_type": "percentage_off", "discount_value": 50},
  {"item": "Cocktails", "discount_type": "discount_amount", "discount_value": 1.00},
  {"item": "Wine", "discount_type": "discount_amount", "discount_value": 2.00}
]
```

---

## Key Metrics to Track

| Metric | Current | Target |
|--------|---------|--------|
| Rows with usable price (non-null, correct type) | 45.4% (1,447) | >75% |
| Rows with valid_days populated | 0.9% (29) | >40% |
| Rows with valid_start_time populated | 0.8% (25) | >30% |
| Rows classified as junk/noise | ~15% est | <3% |
| Average signal_quality score | N/A | >0.55 |
| Chain deal duplicate ratio | 31% (~1,000) | <5% |
| Cross-employer content leaks | unknown | 0 |
