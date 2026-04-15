1# FH-3: Meal Deal Map Layer Integration

> **Date:** 2026-04-13
> **Status:** Backend ready — frontend integration pending
> **Prerequisite:** Meal deal infrastructure (Phase 1-4) is live. API endpoints active.

---

## Objective

Add deal pins/overlay to the Job Faire map so users can see nearby meal deals alongside employer data.

---

## What's Ready (Backend)

### API Endpoints

All endpoints are live at `http://localhost:8765`:

```
GET /api/deals?lat=30.27&lng=-97.74&radius_mi=5
GET /api/deals?lat=30.27&lng=-97.74&deal_type=lunch_special&day=monday&active_only=true
GET /api/deals/stats
GET /api/deals/brands
```

### Response Shape

```json
{
  "deals": [
    {
      "id": 42,
      "restaurant_name": "Subway",
      "address": "123 Congress Ave, Austin, TX",
      "lat": 30.2672,
      "lng": -97.7431,
      "deal_name": "$5.99 Footlong",
      "deal_description": "Any footlong sub for $5.99",
      "deal_type": "combo",
      "price": 5.99,
      "valid_days": "Mon-Fri",
      "valid_start_time": "11:00",
      "valid_end_time": "14:00",
      "source": "chain_website",
      "verified_at": "2026-04-13T06:00:00Z",
      "is_active": true
    }
  ],
  "count": 47,
  "region": "austin_tx"
}
```

### Data Coverage (as of 2026-04-13)

| Metric | Count |
|--------|-------|
| Restaurant URLs resolved | 1,582 / 5,662 (27%) |
| Chain deal signals (dry run) | 151+ across 8 static chains |
| Playwright chains (newly integrated) | 5 more: Subway, Sonic, Jack in the Box, Chipotle, Smoothie King |
| Website scraper schedule | Mon/Wed/Fri 2 AM |
| Deal expiry | 14 days without re-verification |

---

## Frontend TODOs

### 1. Deal Pins on Map (HIGH)

- Add a new map layer for meal deal locations
- Use the `lat`/`lng` from deal responses to place pins
- Color-code by `deal_type` (lunch_special → green, happy_hour → purple, combo → blue, etc.)
- Cluster pins at low zoom levels
- On click: show deal card with name, price, description, valid times

### 2. Deal Filter Controls

- Toggle deal layer on/off
- Filter by `deal_type` (dropdown/chips)
- Filter by day (show deals valid today by default)
- Price range slider
- "Active only" toggle (default: true)

### 3. Deal Cards / Tooltips

On pin click or hover, show:
- Restaurant name
- Deal name + price
- Valid days/times
- "Verified X days ago" based on `verified_at`
- Link to source URL (if available)

### 4. Integration with Employer Pins

When an employer pin already exists on the map:
- Add a small deal badge/indicator to show this location has deals
- Clicking should show both employer info AND deals in the side panel
- Don't create duplicate pins — merge deal data into existing employer pins

---

## Data Refresh

- Deals are refreshed automatically:
  - Chain deals: weekly (Monday 6 AM)
  - Local restaurant websites: Mon/Wed/Fri 2 AM
  - URL resolution: Sunday (OSM) + Tuesday (Google Places)
- Frontend should cache `/api/deals` responses for the viewport with a 1-hour TTL
- Stale deals (>14 days unverified) are auto-deactivated and won't appear in API responses

---

## Future Enhancements (not blocking)

1. **Deal notifications** — "New deals near you" push for saved locations
2. **Deal submission form** — Let users submit deals they find (feeds into SpiritPool manual ingest)
3. **Deal freshness indicator** — Green/yellow/red based on `verified_at` age
4. **"Best deals nearby" widget** — Sorted by price or deal_type for the current map viewport
