> **ARCHIVED 2026-04-21.** Backend fields (`signal_quality`, `deal_value_score`, `sub_deals`) shipped and consumed by the frontend. Superseded by [FPI-1](../../../agentMailbox/InteragentExchange/FPI-1_food_price_index_tab_handoff.md) for current work.

# FH-4: Meal Deal Data Upgrade — Frontend Handoff

> **Date:** 2026-04-16  
> **Status:** Backend complete — frontend integration required  
> **Prerequisite:** FH-3 (Meal Deal Map Layer) — this document extends it  
> **Author:** Backend pipeline (Fortune_3840)

---

## What Changed and Why

The meal deal pipeline went through a major data quality overhaul (Phases 1–4).  
Three things the frontend needs to respond to:

1. **Two new numeric scores** on every deal — use them for sorting and badge display
2. **Cleaned price classification** — `price_type` is now reliable and should drive how prices are displayed
3. **`sub_deals` JSONB array** — structured breakdown of multi-offer deals (e.g. "½ off appetizers AND $1 off cocktails")

---

## New Fields in the API Response

The `/api/deals` response now includes two additional fields on every deal object:

```json
{
  "id": 10457,
  "deal_name": "Sunday Funday, 2 for 1 Smoothies!!!!",
  "deal_type": "combo",
  "price": 5.00,
  "price_type": "absolute",
  "discount_percentage": null,

  "signal_quality": 0.87,
  "deal_value_score": 0.95,

  "sub_deals": [
    { "item": "appetizers", "discount_type": "percentage_off", "discount_value": 50.0 },
    { "item": "cocktails",  "discount_type": "discount_amount", "discount_value": 1.00 }
  ],

  "valid_days": "Mon-Fri",
  "valid_start_time": "4:00 PM",
  "valid_end_time": "7:00 PM",
  "lat": 30.2672,
  "lng": -97.7431,
  "is_active": true
}
```

### `signal_quality` (existing, now more accurate)

- **Range:** 0.0 – 1.0  
- **Measures:** How complete and trustworthy the *data record* is  
  (does it have a price? a time window? a real description?)
- **Use for:** Showing a "data confidence" indicator, de-emphasizing low-quality listings
- **Do NOT use for:** Ranking deal desirability — that's what `deal_value_score` is for

| Range | Meaning | Suggested UI treatment |
|-------|---------|------------------------|
| ≥ 0.70 | High confidence | Show normally |
| 0.40–0.69 | Medium confidence | Show with subtle dimming or no price badge |
| < 0.40 | Low confidence | Show only if no better deals nearby; add caveat |

### `deal_value_score` ← NEW

- **Range:** 0.0 – 1.0  
- **Measures:** How good the offer is for the consumer  
  (BOGO > half off > $5 off > $1 off)
- **Use for:** Sort order ("Best deals first"), value badges, pin color intensity
- **Completely independent of `signal_quality`** — a deal can have weak data but strong value, or vice versa

#### Value Tiers

| Score | Tier | Label | Example deals | Active count |
|-------|------|-------|---------------|-------------|
| 0.90–1.00 | T5 | Best Value | BOGO, buy-one-get-one, 2-for-1 | 29 |
| 0.70–0.89 | T4 | High Value | ≥40% off; half off; $1–$3 menu items | 304 |
| 0.50–0.69 | T3 | Good Value | 20–39% off; $3–$5 off; $4–$8 items | 781 |
| 0.30–0.49 | T2 | Moderate | 10–19% off; $2–$3 off | 691 |
| 0.10–0.29 | T1 | Weak | <10% off; $1 off generic | 17 |
| 0.00 | T0 | Unknown | No price/offer info extractable | 654 |

**Key rule the product asked for:** `$1 off` (a discount off menu price) must rank below `$1 drinks` (absolute price of $1). The scoring handles this automatically — a $1 absolute-price deal scores 0.88, a $1 discount_amount scores 0.15.

#### Recommended default sort

```
ORDER BY deal_value_score DESC, signal_quality DESC
```

---

## `price_type` — Now Reliable, Use It for Display

Previously ~53% of active deals had `price_type = null` even when a price was present. That's fixed. Use `price_type` to determine how to display the price:

| `price_type` | What it means | Display format |
|---|---|---|
| `absolute` | The item/meal costs this price | `$5.99` |
| `discount_amount` | Saves this amount off the menu price | `$2 off` |
| `percentage_off` | Percentage reduction (use `discount_percentage`) | `50% off` |
| `null` | No price info was extracted | Show deal name only; no price badge |

**Combined display logic:**

```js
function formatPrice(deal) {
  if (deal.price_type === 'absolute' && deal.price) {
    return `$${deal.price.toFixed(2)}`;
  }
  if (deal.price_type === 'discount_amount' && deal.price) {
    return `$${deal.price.toFixed(0)} off`;
  }
  if (deal.price_type === 'percentage_off') {
    const pct = deal.discount_percentage ?? deal.price;
    return pct ? `${pct}% off` : 'Sale';
  }
  return null; // no badge
}
```

**Current price_type distribution (active deals):**

| price_type | Count |
|---|---|
| absolute | 1,331 |
| null | 674 |
| percentage_off | 313 |
| discount_amount | 158 |

---

## `sub_deals` — Multi-Offer Breakdowns

Some happy hour deals have multiple offers in one block:  
*"$2 off drafts, $3 wells, half off appetizers"*

When the pipeline detects ≥ 2 distinct offers, it decomposes them into `sub_deals`:

```json
"sub_deals": [
  { "item": "drafts",      "discount_type": "discount_amount",  "discount_value": 2.00 },
  { "item": "wells",       "discount_type": "absolute",         "discount_value": 3.00 },
  { "item": "appetizers",  "discount_type": "percentage_off",   "discount_value": 50.0 }
]
```

**Field reference:**

| Field | Type | Description |
|---|---|---|
| `item` | string | What item the offer applies to |
| `discount_type` | `"discount_amount"` \| `"percentage_off"` \| `"absolute"` | Same vocabulary as `price_type` |
| `discount_value` | number | Dollar amount or percentage depending on type |

**Handling nulls:** `sub_deals` is `null` on ~96% of deals (single-offer deals don't need it). Always check before rendering:

```js
if (deal.sub_deals && deal.sub_deals.length > 0) {
  // render as offer list
} else {
  // render deal_name + formatPrice(deal)
}
```

**Suggested sub_deals display** (deal card expanded view):
```
Happy Hour · Mon–Fri · 4PM–7PM
  • Drafts        $2 off
  • Wells         $3
  • Appetizers    50% off
```

---

## `deal_type` — Tags for Filter Chips and Pin Colors

| `deal_type` | Count | Suggested pin color | Filter chip label |
|---|---|---|---|
| `happy_hour` | 1,114 | Purple | 🍺 Happy Hour |
| `combo` | 1,084 | Blue | 🍽️ Combo Deal |
| `daily_special` | 200 | Teal | 📅 Daily Special |
| `kids_eat_free` | 27 | Green | 👧 Kids Eat Free |
| `lunch_special` | 26 | Yellow | 🥪 Lunch Special |
| `bogo` | 25 | Orange | 🔁 BOGO |

---

## Recommended API Query Patterns

### Default feed — best deals first
```
GET /api/deals?lat=30.27&lng=-97.74&radius_mi=3&active_only=true
```
Then sort client-side: `ORDER BY deal_value_score DESC, signal_quality DESC`

### Filter to high-value only (T4+)
The API doesn't yet accept a `min_value_score` param — filter client-side:
```js
deals.filter(d => (d.deal_value_score ?? 0) >= 0.70)
```
> Backend can add `?min_value_score=0.70` param if client-side filtering becomes a bottleneck.

### Happy hour right now
```
GET /api/deals?lat=...&lng=...&deal_type=happy_hour&day=thursday&active_only=true
```

### Show deals with full offer breakdown
```js
// After fetch, separate deals that have sub_deals
const richDeals = deals.filter(d => d.sub_deals?.length > 0);
const simpleDeals = deals.filter(d => !d.sub_deals?.length);
```

---

## What Was Cleaned Out (Don't Need to Handle These Anymore)

112 non-food deals were deactivated and will no longer appear in API responses:
- Hotel/travel stay discounts ("Save $5 Off Per Night", "20% off your stay")
- AARP/AAA membership hotel deals
- SaaS product discounts ("33% Off Linktree Pro Annual")
- Gambling/spam ("Get Unlock 15% OFF Instantly When You Buy 5+ WARGATOGEL")
- Registration fees mislabeled as deals

These were previously leaking into the active feed. They're now `is_active = false` and filtered out by default.

---

## Suggested UI Changes (Priority Order)

### HIGH — Sort by `deal_value_score`

Replace any current alphabetical or insertion-order sort with:
```
deal_value_score DESC, signal_quality DESC
```
This surfaces BOGO and half-off deals before "$1 off drafts" deals.

### HIGH — Value Badge on Deal Cards

Add a visual tier badge based on `deal_value_score`:

```
T5 (≥0.90) → 🔥 Best Value  (gold/fire badge)
T4 (≥0.70) → ★ Great Deal   (green badge)
T3 (≥0.50) → (no badge — show price normally)
T2 (≥0.30) → (no badge)
T1 (<0.30)  → show "$1 off" label with muted style
T0 (0.00)  → show deal name only, no price badge
```

### HIGH — Fix Price Display Using `price_type`

Currently the frontend may be displaying all prices as plain numbers. Use `price_type` to add context labels: `$5.99` vs `$2 off` vs `50% off`.

### MEDIUM — Sub-deals Expansion

On deal cards for deals where `sub_deals` is non-null, add an "expand" chevron that shows each offer as a line item instead of a raw text dump of `deal_name`.

### MEDIUM — Data Confidence Dimming

Use `signal_quality < 0.40` to subtly dim or de-emphasize low-confidence listings. These are not bad deals — just records where we couldn't fully verify the details. Don't hide them; just make their visual weight lighter.

### LOW — "Verified X days ago" freshness

`verified_at` is already in the response. A green/yellow/red indicator:
- < 3 days → green (fresh)
- 3–10 days → yellow (aging)
- > 10 days → red (stale, deal may have changed)

---

## What's NOT Changing

- API endpoint URLs and auth — unchanged
- `id`, `lat`, `lng`, `deal_name`, `deal_description`, `valid_days`, `valid_start_time`, `valid_end_time`, `source_url`, `is_active`, `verified_at` — all unchanged  
- `is_chain_template` — still present but not relevant to frontend rendering; chain templates resolve to per-location rows before the API returns them
- Deal refresh schedule — unchanged (chain weekly, scraper Mon/Wed/Fri 2 AM)

---

## Questions / Backend Contact

If an endpoint needs a new filter param (e.g. `?min_value_score=`, `?price_type=absolute`) open a request — backend can add query params to the existing `/api/deals` handler without a schema change.
