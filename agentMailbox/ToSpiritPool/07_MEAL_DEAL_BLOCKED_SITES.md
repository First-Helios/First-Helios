> **Date:** 2026-04-13
> **Scope:** New SpiritPool responsibility — manual deal collection for restaurants that block automated scraping.

---

## Context

First-Helios now runs an automated meal deal scraper (`collectors/meal_deals/website_scraper.py`) that crawls restaurant websites for lunch specials, happy hours, BOGO deals, etc. We've resolved URLs for 1,582 of 5,662 food employers in the Austin metro.

**Problem:** Some restaurant sites block all bots via robots.txt, return 403s, or require JavaScript-heavy interaction beyond what our scraper handles. These sites are automatically flagged and written to:

```
data/cache/spiritpool_blocked_sites.json
```

---

## What SpiritPool Needs To Do

### 1. Monitor the Blocked Sites List

The scraper appends to `spiritpool_blocked_sites.json` each run (Mon/Wed/Fri 2 AM). Each entry looks like:

```json
{
  "name": "Restaurant Name",
  "url": "https://example.com",
  "reason": "robots.txt",
  "employer_id": 12345,
  "flagged_at": "2026-04-13T02:15:00"
}
```

### 2. Manual Deal Collection

For each blocked site, SpiritPool contributors should:

1. Visit the restaurant website in their browser
2. Look for deals on pages like `/specials`, `/deals`, `/menu`, `/happy-hour`
3. Submit deal data via the existing contribute pipeline (`POST /api/spiritpool/contribute`) with:

```json
{
  "event_type": "meal_deal",
  "source": "manual_spiritpool",
  "payload": {
    "restaurant_name": "...",
    "employer_id": 12345,
    "deal_name": "$5.99 Lunch Combo",
    "deal_description": "Any sandwich with drink and side",
    "deal_type": "lunch_special",
    "price": 5.99,
    "valid_days": "Mon-Fri",
    "valid_start_time": "11:00 AM",
    "valid_end_time": "2:00 PM",
    "source_url": "https://example.com/specials"
  }
}
```

Or use the manual ingest CSV format via `collectors/meal_deals/manual_ingest.py`.

### 3. Deal Types

Valid `deal_type` values:
- `lunch_special` — Lunch combos, weekday specials
- `combo` — Meal deals, value meals
- `bogo` — Buy one get one
- `happy_hour` — Drink/food specials during specific hours
- `kids_eat_free` — Kids meal promos
- `daily_special` — Day-of-week specials (Taco Tuesday, etc.)

### 4. Refresh Cadence

- Deals expire after **14 days** without re-verification
- SpiritPool should re-check blocked sites at least every 2 weeks
- If a site unblocks bots later (robots.txt changes), the automated scraper will pick it back up

---

## Priority List (initial)

These chains are JS-heavy SPAs that our scraper may struggle with even via Playwright. If automated collection fails, SpiritPool should cover:

| Chain | Locations | Issue |
|-------|-----------|-------|
| Whataburger | 36 | Deals are app-only (MyWhataburger) — no public web deals |
| Chipotle | 29 | Mostly rewards-based promotions, not traditional deals |

---

## Backend Endpoint

The `POST /api/spiritpool/contribute` endpoint (legacy dual-write path) is the alpha data path for manual submissions. The manual ingest pipeline (`collectors/meal_deals/manual_ingest.py`) can also accept CSV/JSON files directly.

All manually submitted deals get `source = "manual"` and are treated equally alongside automated scrapes for display on the Job Faire map.
