# Meal Deal Data Quality Issues

> Reviewed: 2026-04-16  
> Dataset: 2,588 active rows, 3,392 total  
> Method: SQL analysis + manual sampling  

Issues are rated by impact (**High / Medium / Low**) and tagged by type.

---

## ISSUE-001 — 1,372 rows with `price_type=NULL` but price set · HIGH

**Rows affected:** 1,372 active (53% of active deals)  
**Root cause:** Pre-Phase-1 rows that `cleanup_meal_deals.py` never classified. The cleanup script only promotes rows to `discount_amount` or `percentage_off` when patterns match; it never falls back to `absolute`.  
**Impact:** These rows get near-zero credit from the `price_type` scoring factor in `compute_signal_quality()`, depressing quality scores across most active listings. The re-audit shows all remaining failures are `price_type_unknown` flags.  
**Price range:** $1.00 – $1,499.00, median $7.00  
**Fix idea:** "Absolute by default" pass — rows where `price IS NOT NULL AND price_type IS NULL` and no discount/percentage text found in `deal_name` → classify as `price_type = 'absolute'`, then re-run backfill.

---

## ISSUE-002 — 133 non-food/non-restaurant deals active · HIGH

**Rows affected:** ~133 active  
**Examples observed:**
- Hotel stay deals: "Save $5 Off Per Night", "20% off your entire stay", "Book four nights or more and get 20% off"
- AARP/AAA membership discounts: "AARP Members Save 15% Get 15% off 2+ consecutive nights"
- SaaS product deals: "Our biggest sale ever 33% Off Linktree Pro Annual"
- Gambling spam: "Get Unlock 15% OFF Instantly When You Buy 5+ WARGATOGEL" (id=8531)

**Root cause:** Scrapers are pulling deals from non-restaurant employers (hotels, coworking spaces) whose Google/Yelp presence lists them alongside restaurant chains. The junk-name filter in `ingest.py` catches navigation elements but not off-topic deal categories.  
**Impact:** Non-food deals pollute the feed and dilute signal quality statistics. Hotels and Linktree are not meal deals.  
**Fix idea:** Add a domain-category filter — if the employer's `occupation_category` or name contains hotel/travel/software keywords, skip or quarantine the deal.

---

## ISSUE-003 — 120 deal names appearing across 4+ unrelated employers · HIGH

**Rows affected:** 120 unique deal names, hundreds of rows  
**Sub-categories:**

| Sub-type | Count | Example |
|----------|-------|---------|
| Legitimate chains (A&W, etc.) | ~9 | "Download the A&W app and get 20% off" across 6 A&W locations |
| Generic chain happy hour text | ~15 | "Best Happy Hour In Town…" across 15 employers |
| Date-specific deal clones | ~14 | "Thursday April 16th All Day Drink Specials" across 4 employers |
| Cross-category leaks (hotels, etc.) | ~82 | "AARP Members Save 15%…" across 8 employers |

**Root cause for generic text:** Multiple restaurants use the same boilerplate happy hour copy. This is legitimate but ranks poorly because it doesn't identify the specific offer.  
**Root cause for date-specific clones:** Scraper is hitting the same venue's event feed under multiple `local_employer_id` records (likely address variations of the same venue).  
**Fix idea:** Flag generic boilerplate text as low-value; deduplicate date-specific deals where `(deal_name, valid_days)` are identical across same `brand_group_id`.

---

## ISSUE-004 — 597 active deals with `signal_quality < 0.5` · HIGH

**Rows affected:** 597 active (23% of active deals)  
**Root cause:** Mix of ISSUE-001 (unclassified price_type) and ISSUE-002 (non-food deals).  
**Impact:** These deals pass the gate (is_active=True) but would ideally be ranked below threshold in query results.  
**Fix idea:** Resolving ISSUE-001 and ISSUE-002 should eliminate most of these. Gate threshold could be raised from 0.35 → 0.40 after fixes.

---

## ISSUE-005 — 55.3% of active deals have no time context · MEDIUM

**Rows affected:** 1,432 active  
**Definition:** `valid_days IS NULL AND valid_start_time IS NULL`  
**Impact:** App cannot show "available now" or "happy hour starts in 2h" for these deals. They can only be shown as "general deals" without time relevance.  
**Examples:**
- Chain website deals (no hours scraped from corporate page)
- App-download discount deals (no time window; always valid)
- Grocery/retail deals (valid by week, not time of day)

**Note:** Not all of these are bugs — some deals genuinely have no time window (app discounts, military discounts). But happy hour deals missing times are a gap.  
**Fix idea:** Flag happy-hour deals (where `deal_name` contains "happy hour") with no time context for re-scraping.

---

## ISSUE-006 — Fragment / truncated deal names · MEDIUM

**Rows affected:** 47 active (names < 15 chars)  
**Examples:**
- `"Chuck E"` (4 rows) — truncated from "Chuck E. Cheese" — scraper cut the name at an apostrophe
- `"Specials $2"` (4 rows) — no description of what $2 gets you
- `"Offer Details"` — completely uninformative
- `"*Dine-in only"` — a modifier, not a deal name
- `"to register"` (2 rows, price=$500) — registration fee, not a deal
- `"Half $9"` (3 rows) — fragment with no item
- `"Soda $2"` (3 rows) — ambiguous (absolute price or discount?)
- `"Does Chuck E"` — clearly truncated

**Root cause:** Scraper is capturing partial text nodes. The junk-name filter's 5-character minimum doesn't catch 8–14 char fragments.  
**Fix idea:** Raise junk-name minimum length to 20 chars, or add a fragment detector (no verb, no noun identifiable = skip).

---

## ISSUE-007 — `$1 off` deals ranked same as `$5 off` or BOGO · MEDIUM

**Rows affected:** 91 active deals with `price_type=discount_amount AND price <= 2.0`  
**Problem:** The quality scoring system gives equal credit to "$1 off drafts" and "$5 off any entrée" — both are `discount_amount` with a price set. But $1 off is a much weaker offer.  
**Severity tiers observed in data:**
1. BOGO (buy one get one) — highest value; found 18 rows
2. Half off / 50% off — very high value
3. Absolute low prices ($1 drinks, $2 tacos, $3 beers) — high value
4. $5+ off — moderate-high value
5. 20–49% off — moderate value
6. 10–19% off — lower-moderate value
7. $1–$2 off — low value (weakest meaningful discount)

**Fix idea:** Add a `deal_value_score` field (separate from signal quality) that ranks the *strength* of the offer, not just how complete the data is. See ISSUE-007-ranking-proposal below.

---

## ISSUE-008 — `$1 off` misclassified as `discount_amount` when text means absolute price · MEDIUM

**Rows affected:** Estimated ~30–50  
**Examples of confusion:**
- "Happy Hour – $1 off Cocktails, $3 Wells, $5 Margs" — the $3 and $5 are absolute prices, but scraper stores only the $1 figure as `price`
- Deal says "$3 happy hour beers" but `price_type=discount_amount, price=3.0` — it's actually the absolute price of the beer, not a $3 discount

**Root cause:** The price extractor pulls the first dollar amount found. "$3 wells" could be absolute ($3 per well drink) or a $3 discount.  
**Impact:** Misclassification affects both display logic and value ranking.  
**Fix idea:** Context-sensitive price type: if `$X [item]` pattern (no "off" keyword), treat as absolute; only use `discount_amount` when "off" keyword follows.

---

## ISSUE-009 — `price_type=None` rows with implausibly high prices · LOW

**Rows affected:** Several  
**Examples observed:**
- id=7579: `"to register" price=500.0` — conference/event registration fee, not a meal deal
- id=9200: hotel "Save $5 Off Per Night" — hotel stay, not food
- Large price values ($1,499) appearing in the NULL price_type bucket

**Root cause:** Scraper captures price fields from the employer's page without verifying they are meal-deal prices.  
**Fix idea:** Prices > $150 on a deal with no `menu_avg_price` context should be quarantined or rejected at ingest.

---

## ISSUE-010 — "Best Happy Hour In Town" generic text across 15 employers · LOW

**Rows affected:** 15 active  
**Deal name:** `"Best Happy Hour In Town Monday — Thursday from 3 to 6pm Cocktails, beer, wine & sliders are ½ off during happy hour"`  
**Problem:** This is a marketing slogan used as a deal name. It appears to be a template inserted by the Happy Hour Finder scraper across many venues. The offer text is actually useful ("½ off cocktails, beer, wine & sliders") but the framing pollutes the name field.  
**Fix idea:** Detect template slogans via exact-text match across >5 employers and flag for review.

---

## ISSUE-011 — Only 112/2,588 active deals have `sub_deals` populated (4.3%) · LOW

**Rows affected:** 2,476 active  
**Root cause:** The `sub_deals` JSONB column was added in Phase 4. `populate_sub_deals.py` only decomposes text with ≥2 detected offers. Most deals have single-offer text, or the regex doesn't match the text format.  
**Impact:** The query layer can't show "Offer 1: $3 wells, Offer 2: $2 domestics" breakdowns for most deals.  
**Fix idea:** Improve `extract_sub_deals()` to handle more pattern types (e.g., comma-separated absolute prices, newline-separated offer blocks).

---

## ISSUE-012 — Active deals from chain scraper with no `local_employer_id` score poorly · LOW

**Rows affected:** All `chain_website` source rows (templates)  
**Root cause:** Chain templates have `local_employer_id=NULL` by design (Phase 3 change). The `_score_restaurant_match` factor in quality scoring returns ~0.05 credit when it can't check employer name against deal text.  
**Impact:** All `chain_website` rows have mean quality ~0.37 (below the 0.50 alert threshold) despite being legitimate data.  
**Fix idea:** Pass `brand_name` from the `BrandGroup` table during quality scoring for chain templates, so the match factor has something to evaluate against.

---

## Summary Table

| # | Issue | Affected Rows | Priority | Quick Fix? |
|---|-------|--------------|----------|------------|
| 001 | price_type=NULL despite price set | 1,372 | HIGH | Yes — "absolute by default" pass |
| 002 | Non-food deals active (hotels, SaaS, spam) | ~133 | HIGH | Partial — add category filter |
| 003 | Same deal name across 4+ unrelated employers | ~hundreds | HIGH | Partial — chain dedup handles some |
| 004 | Active deals quality < 0.5 | 597 | HIGH | Resolves with 001+002 fixes |
| 005 | No time context | 1,432 | MEDIUM | Flag, not auto-fix |
| 006 | Fragment/truncated deal names | 47 | MEDIUM | Raise junk-name length threshold |
| 007 | $1 off ranks same as BOGO | 91 | MEDIUM | Add deal_value_score field |
| 008 | discount_amount/absolute price confusion | ~30–50 | MEDIUM | Context-sensitive price extractor |
| 009 | Implausibly high prices in NULL bucket | Several | LOW | Reject price > $150 at ingest |
| 010 | Generic slogans as deal names | 15 | LOW | Slogan blocklist |
| 011 | sub_deals sparsely populated | 2,476 | LOW | Expand regex patterns |
| 012 | Chain templates score poorly (no emp match) | all chain_website | LOW | Pass brand_name to scorer |

---

## ISSUE-007 Ranking Proposal — Deal Value Score

A separate `deal_value_score` field (0.0 – 1.0) that captures *offer strength*, independent of data completeness. Proposed tiers:

| Tier | Score | Criteria |
|------|-------|----------|
| 5 — Best value | 0.90–1.0 | BOGO, buy-1-get-1-free, 2-for-1 |
| 4 — High value | 0.70–0.89 | 40–75% off; half off food/drinks; absolute ≤$3 drinks/tacos |
| 3 — Good value | 0.50–0.69 | 20–39% off; $3–$5 off; absolute $4–$8 items |
| 2 — Moderate | 0.30–0.49 | 10–19% off; $2–$3 off specific items |
| 1 — Weak | 0.10–0.29 | ≤10% off or $1 off (generic); "specials" with no amount |
| 0 — Unknown | 0.0 | No price/percentage info extractable |

**Ranking rules:**
- `$1 off` any item → Tier 1 (weak) — scrutinize heavily
- `$1 [item]` absolute (e.g., "$1 tacos") → Tier 4 (high) — the item costs $1, that's great value
- `half off` → Tier 4; `50% off` → Tier 4
- BOGO / buy one get one free → Tier 5
- App download discount (10–20% off first order) → Tier 2 (moderate, one-time use)
- `discount_percentage >= 40` → Tier 4+
- `discount_percentage 20–39` → Tier 3
- `discount_percentage 10–19` → Tier 2
- `discount_percentage < 10` → Tier 1

**Key insight from user:** "$1 off" should rank lower than "$1 drinks." The former saves $1 on a menu-price item; the latter gives you a full drink for $1.
