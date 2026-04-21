# FPI-1: Food Price Index Tab — Implementation Handoff

> **Date:** 2026-04-20
> **Status:** Backend and first frontend pass landed; refinement handoff now focuses on data-quality rollout and frontend adoption of newer menu fields
> **Author:** Claude session (Fortune_3840)
> **Prerequisites:** FH-3 (meal deal map layer) and FH-4 (meal deal data upgrade) — this is an offshoot tab, not a replacement
> **Related docs:** `docs/data/ingestion/MENU_SIDECAR.md`

---

## April 21, 2026 Addendum — Quality Hardening and Orange Pi Drift

The first implementation pass is not the current bottleneck. The active issue is menu-quality drift between local fixes and the Orange Pi deployment.

### Current verified production pattern

- `Chaat Ka Chaskaaa` is the primary severe price-scale failure on the live host.
    - 52 persisted price rows.
    - 7 rows at `0.00`.
    - 45 rows between `0.02` and `0.46`.
    - This is the JSON-LD scale leak the local parser fix now normalizes.
- `La Posada Mexican Restaurant` still has heavy unnamed-section loss.
- `The Rebublic of Sandwich` still has size-label item names instead of variants.

### Important operational conclusion

If the live Price Index still shows `Bhel Puri $0.00`, do not assume the local parser fix failed. First verify whether Orange Pi has the current backend code. The live host was confirmed missing the local `menu_sidecar.py` and `price_index_routes.py` hardening functions during this session.

Fast check:

```bash
ssh orangepi@192.168.1.191
cd ~/First-Helios
grep -n "def _should_exclude_payload\|def _normalize_jsonld_page_prices" \
    collectors/meal_deals/price_index_routes.py \
    collectors/meal_deals/menu_sidecar.py
```

No matches means the live backend is stale.

### New quality controls added after the original handoff

- `collectors/meal_deals/menu_sidecar.py`
    - strips inline pseudo-tags from names
    - extracts dietary tags from inline legend markers
    - rescales obvious subunit JSON-LD menus
    - drops zero/negative JSON-LD price points
    - skips promo-only DOM rows and promo sections
    - keeps size labels as variants instead of item names
- `collectors/meal_deals/price_index_routes.py`
    - excludes non-positive rows at query time
    - rescales suspicious all-subunit bundles on read
    - hides promo leakage from live results
    - normalizes unnamed sections and size/evidence variants for display
    - adds ZIP-driven distance and dietary filters
- `collectors/meal_deals/menu_db_writer.py`
    - now filters non-positive menu price points before persistence so replay/backfill does not reinsert `0.00` rows
- `scripts/audit_menu_price_index.py`
    - audits stores by row count, min/median/max price, zero-price rows, subunit-price clusters, unnamed sections, size-only item names, and promo leakage

### Required rollout after backend deploy

```bash
ssh orangepi@192.168.1.191
cd ~/First-Helios

.venv/bin/alembic upgrade head
PYTHONPATH=. .venv/bin/python scripts/audit_menu_price_index.py --region austin_tx --limit 20 --show-rows 5
PYTHONPATH=. .venv/bin/python collectors/meal_deals/website_scraper.py --replay-debug-cache --all --skip-checked-days 0 --chunk-size 25
PYTHONPATH=. .venv/bin/python scripts/backfill_menu_tables.py
PYTHONPATH=. .venv/bin/python scripts/audit_menu_price_index.py --region austin_tx --limit 20 --show-rows 5
```

### Practical review standard

For the Price Index, treat these as hard audit failures until proven otherwise:

- any baseline menu row with `price <= 0`
- any store where most prices are between `0.01` and `0.99`
- unnamed sections dominating a store
- size-only item names such as `8 Oz`, `Small`, or `Regular`
- promo fragments like `$1 off drafts` persisted as menu items

## April 21, 2026 Addendum — Frontend Adaptation After Backend Hardening

The frontend is no longer starting from zero. The current `priceindex.js` already consumes these backend fields successfully:

- `dietary_tags`
- `variant`
- `section_name`
- `service_period`
- `distance_mi`

The current `mealdeals.js` already consumes these deal-quality fields:

- `deal_value_score`
- `signal_quality`
- `sub_deals`

That means the next frontend work is not “wire the tab up at all.” It is “use more of the structure intentionally.”

### Backend integration correction

Menu data is no longer bundle-only. The current backend now has persistent menu tables in `core/database.py`, populated from `menu_persistence_shape` through `collectors/meal_deals/menu_db_writer.py` and `scripts/backfill_menu_tables.py`.

Use this mental model:

- replay bundles are still the authoritative provenance and re-extraction layer
- persistent `menu_*` tables are now the query layer for `/api/price-index`

### Frontend changes needed next

1. Add a brand filter to the Price Index tab.
    The backend already returns `brands` from `/api/price-index/facets` and accepts `brand` on `/api/price-index`, but the UI currently has no control for it.
    Target files: `First-Helios_Frontend/index.html`, `First-Helios_Frontend/js/priceindex.js`

2. Add a service-period filter control.
    The backend already accepts `service_period`, and the result cards already render it as a badge, but users cannot filter directly to lunch, brunch, dinner, or similar section scope.
    Target files: `First-Helios_Frontend/index.html`, `First-Helios_Frontend/js/priceindex.js`

3. Make restaurant groups section-aware instead of only flat item lists.
    The UI currently groups by restaurant, but it does not really take advantage of `section_name` plus `variant`. A better next step is nested grouping such as `Restaurant -> Section -> Items`, with `variant` rendered as secondary detail rather than duplicated badge noise.
    Target files: `First-Helios_Frontend/js/priceindex.js`, `First-Helios_Frontend/css/style.css`

4. Surface richer savings context in Meal Deals.
    The deal cards currently show formatted price, value badge, and sub-deals, but they do not use `menu_avg_price` or `original_price` to explain why a deal is strong. Add a secondary savings line such as “vs. $12.50 menu average” or “50% off regular price” when the data exists.
    Target files: `First-Helios_Frontend/js/mealdeals.js`, `First-Helios_Frontend/css/style.css`

5. Decide whether Meal Deals should show item or section targets.
    The scraper now links many offers to structured targets in metadata, but `/api/deals` currently serializes `DealMaterialization.to_dict()` only. If the frontend should show chips like “targets appetizers” or “happy-hour drinks”, the backend route must expose a normalized `offer_target` summary first.
    Target files: `collectors/meal_deals/routes.py`, `First-Helios_Frontend/js/mealdeals.js`

6. Add a stronger explanation layer for dietary tags.
    The Price Index already shows dietary chips and filters, but it still truncates tags visually and treats them as generic badges. If dietary search is part of the product story, filtered tags should be visually promoted in the item card and summary line.
    Target files: `First-Helios_Frontend/js/priceindex.js`, `First-Helios_Frontend/css/style.css`

### Practical priority order

1. Brand filter for Price Index
2. Service-period filter for Price Index
3. Section-aware result grouping
4. Meal Deal savings explanation using existing numeric fields
5. Backend exposure of normalized `offer_target` for frontend use

---

## What We're Building and Why

A new **Food Price Index** tab — separate from Meal Deals. It surfaces **every scraped menu item** (not just discounted ones) so a user can search by keyword, cuisine/brand, course, or price-per-calorie to find the cheapest food nearby.

**Hard gate:** a restaurant only appears in results if its menu has been scraped into a sidecar and then materialized into the persistent menu tables. No menu persistence = not listed.

### Why this is its own tab (not merged into Meal Deals)
- Meal Deals is about *discounts and offers* (DealMaterialization)
- Price Index is about *baseline menu prices* (MenuItem + MenuPricePoint)
- Different query shape, different user intent, different value proposition

---

## Critical Gotchas — Read This First

### 1. **Frontend lives in a sibling repo, NOT in this project**

The frontend is at **`/home/fortune/CodeProjects/First-Helios_Frontend/`** — a separate repo sibling to First-Helios.

Structure:
```
First-Helios_Frontend/
├── index.html
├── js/
│   ├── app.js           ← mode-switcher lives here
│   ├── config.js
│   ├── mealdeals.js     ← meal deals tab already implemented
│   ├── priceindex.js    ← first pass of the Price Index tab already implemented
│   ├── eventfinder.js
│   ├── h3map.js
│   ├── jobfinder.js
│   └── pathfinder.js
├── css/style.css
└── serve.py             ← frontend dev server
```

> **Do not be misled:** `server.py` in First-Helios still references `static_folder="frontend"` and commit `c2a4225` is titled "deleted frontend". That commit *moved* the frontend to its own repo — it was not deleted. The backend's `static_folder` reference is stale and irrelevant to where frontend changes actually go.

**All frontend changes in this plan target `/home/fortune/CodeProjects/First-Helios_Frontend/`.** Study both `mealdeals.js` and the current `priceindex.js` before extending the tab further.

### 2. **Menu data exists in both replay bundles and persistent tables**
`bundle["menu_persistence_shape"]` is populated on scraper output and remains the replay/debug authority. That shape is now materialized into persistent `menu_pages`, `menu_sections`, `menu_items`, `menu_price_points`, and `menu_modifiers` tables through `collectors/meal_deals/menu_db_writer.py` and `scripts/backfill_menu_tables.py`.

### 3. **Latest alembic head is `c6f1e2a7b934`**
(`alembic/versions/c6f1e2a7b934_merge_meal_deal_heads.py`). Your new migration's `down_revision` must be `"c6f1e2a7b934"`.

### 4. **`restaurant_id` type mismatch**
Sidecar serializes `restaurant_id` as `str` (e.g. `"123"`). `local_employers.id` is `Integer`. The upsert helper must cast `int(shape["restaurant_id"])` and skip rows where it's None.

---

## Critical Files to Read Before Coding

| File | Why |
|---|---|
| [collectors/meal_deals/menu_persistence_schema.py](collectors/meal_deals/menu_persistence_schema.py) | Source of truth for all column definitions — `PersistentShape`, `MenuItemRow`, etc. |
| [collectors/meal_deals/menu_sidecar.py](collectors/meal_deals/menu_sidecar.py) | Sidecar internals — understand where keys come from |
| [collectors/meal_deals/website_scraper.py:3730](collectors/meal_deals/website_scraper.py#L3730) | Where live-ingest hook attaches |
| [collectors/meal_deals/routes.py](collectors/meal_deals/routes.py) | Pattern for the new blueprint |
| [core/database.py:640](core/database.py#L640) | `LocalEmployer` model — FK target |
| [server.py:127,204](server.py#L204) | Static folder + blueprint registration |
| [alembic/versions/c412787993e6_add_meal_deals_table.py](alembic/versions/c412787993e6_add_meal_deals_table.py) | Migration pattern to copy |
| [docs/data/ingestion/MENU_SIDECAR.md](docs/data/ingestion/MENU_SIDECAR.md) | Full background on the sidecar data model |

---

## Implementation Plan

### Step 1 — ORM Models

Add 5 SQLAlchemy models to [core/database.py](core/database.py) (near the existing meal deal tables).

**Column contracts come directly from the TypedDicts** in `menu_persistence_schema.py` — do not invent new columns. Only transformation: cast `restaurant_id` from str to Integer FK.

```python
class MenuPage(Base):
    __tablename__ = "menu_pages"
    id            = Column(String, primary_key=True)   # sidecar key p_...
    restaurant_id = Column(Integer, ForeignKey("local_employers.id"), index=True)
    url           = Column(String)
    source        = Column(String)   # jsonld | dom | pdf_table
    renderer      = Column(String)
    source_bundle = Column(String)
    first_seen_at = Column(DateTime(timezone=True))
    last_seen_at  = Column(DateTime(timezone=True))

class MenuSection(Base):
    __tablename__ = "menu_sections"
    id                = Column(String, primary_key=True)  # s_...
    page_id           = Column(String, ForeignKey("menu_pages.id"), index=True)
    parent_section_id = Column(String, ForeignKey("menu_sections.id"))
    restaurant_id     = Column(Integer, ForeignKey("local_employers.id"), index=True)
    name              = Column(String)
    path              = Column(JSON)
    service_period    = Column(String, index=True)
    course            = Column(String)
    source            = Column(String)
    first_seen_at     = Column(DateTime(timezone=True))
    last_seen_at      = Column(DateTime(timezone=True))

class MenuItem(Base):
    __tablename__ = "menu_items"
    id            = Column(String, primary_key=True)  # i_...
    section_id    = Column(String, ForeignKey("menu_sections.id"), index=True)
    restaurant_id = Column(Integer, ForeignKey("local_employers.id"), index=True)
    name          = Column(String, index=True)
    description   = Column(Text)
    course        = Column(String, index=True)
    calories      = Column(Integer)
    dietary_tags  = Column(JSON)
    source        = Column(String)
    first_seen_at = Column(DateTime(timezone=True))
    last_seen_at  = Column(DateTime(timezone=True))

class MenuPricePoint(Base):
    __tablename__ = "menu_price_points"
    id            = Column(String, primary_key=True)  # pp_...
    item_id       = Column(String, ForeignKey("menu_items.id"), index=True)
    section_id    = Column(String, ForeignKey("menu_sections.id"))
    restaurant_id = Column(Integer, ForeignKey("local_employers.id"), index=True)
    price         = Column(Float, index=True)
    currency      = Column(String)
    variant       = Column(String)
    confidence    = Column(Float)
    source        = Column(String)
    evidence      = Column(Text)
    observed_at   = Column(DateTime(timezone=True))

class MenuModifier(Base):
    __tablename__ = "menu_modifiers"
    id            = Column(String, primary_key=True)  # mod_...
    item_id       = Column(String, ForeignKey("menu_items.id"))
    section_id    = Column(String, ForeignKey("menu_sections.id"))
    restaurant_id = Column(Integer, ForeignKey("local_employers.id"), index=True)
    label         = Column(String)
    price_delta   = Column(Float)
    required      = Column(Boolean, default=False)
    source        = Column(String)
    first_seen_at = Column(DateTime(timezone=True))
    last_seen_at  = Column(DateTime(timezone=True))
```

**Indexes to add:**
- `menu_items(restaurant_id, course)` — composite for common filter
- `menu_price_points(restaurant_id, price)` — price-sort + venue filter
- `menu_items.name` — keyword search (consider pg_trgm GIN index if performance demands)

### Step 2 — Alembic Migration

New file: `alembic/versions/{hash}_add_menu_graph_tables.py`

```python
revision = '{new_hash}'
down_revision = 'c6f1e2a7b934'   # current head
```

Copy the column structure exactly from Step 1. Use PostgreSQL `JSONB` for `path` and `dietary_tags` (JSON is fine, JSONB is preferred for indexing). Create all FKs and indexes.

### Step 3 — Upsert Helper

**New file:** `collectors/meal_deals/menu_db_writer.py`

```python
def upsert_menu_shape(session, shape: PersistentShape) -> UpsertResult:
    """Idempotent upsert from PersistentShape into the 5 menu tables.

    - Runs check_foreign_keys() first; returns early if violations
    - Casts restaurant_id str→int; skips if None
    - Uses INSERT ... ON CONFLICT (id) DO UPDATE SET last_seen_at = EXCLUDED.last_seen_at
    - For menu_price_points: ON CONFLICT updates observed_at, price, confidence
    Returns counts of inserted/updated rows per table.
    """
```

Must be transactional — a failed upsert must not leave half the tables populated for that restaurant.

### Step 4 — Backfill Script

**New file:** `scripts/backfill_menu_tables.py`

```
python scripts/backfill_menu_tables.py [--debug-dir PATH] [--dry-run] [--limit N]
```

- Uses `collectors.meal_deals.website_scrape_audit_utils.load_debug_bundles()` to read all bundles
- For each bundle, reads `bundle["menu_persistence_shape"]`
- Calls `upsert_menu_shape()`
- Prints: bundles processed, rows inserted per table, FK violations skipped
- Idempotent — safe to re-run

### Step 5 — Live Ingest Hook

In [website_scraper.py](collectors/meal_deals/website_scraper.py), **immediately after** the `_finalize_site_debug_bundle()` call at line 3730:

```python
# FPI-1: persist menu graph to DB (experimental, non-blocking)
try:
    shape = debug_bundle.get("menu_persistence_shape")
    if shape and local_employer_id:
        with get_session(get_engine()) as session:
            upsert_menu_shape(session, shape)
            session.commit()
except Exception as e:
    logger.warning("menu_db_upsert failed for %s: %s", base_url, e)
    # Never block a scrape on persistence failures
```

The sidecar is already serialized to the bundle — no need to re-serialize.

### Step 6 — API Blueprint

**New file:** `collectors/meal_deals/price_index_routes.py`

```python
price_index_bp = Blueprint("price_index", __name__, url_prefix="/api/price-index")
```

#### `GET /api/price-index`

| Param | Type | Default | Notes |
|---|---|---|---|
| `q` | str | — | ILIKE match on `menu_items.name`, `menu_items.description`, `menu_sections.name` |
| `brand` | str | — | `brand_groups.fingerprint` |
| `cuisine` | str | — | `local_employers.industry` |
| `course` | str | — | entree \| drink \| side \| appetizer \| dessert \| combo \| kids |
| `service_period` | str | — | lunch \| dinner \| happy_hour \| brunch \| etc. |
| `lat`, `lng` | float | — | Required for geo filter |
| `radius_mi` | float | 10 | Max 25 |
| `min_price`, `max_price` | float | — | USD |
| `min_calories`, `max_calories` | int | — | kcal |
| `sort` | str | `price` | price \| price_per_calorie \| calories \| name |
| `limit` | int | 50 | Max 100 (cap hard — this is the page-size gate) |
| `offset` | int | 0 | For pagination |
| `region` | str | — | e.g. `austin_tx` |
| `min_confidence` | float | 0.55 | Price point confidence floor |

**Query skeleton (SQLAlchemy):**
```python
q = (session.query(MenuItem, MenuPricePoint, LocalEmployer, BrandGroup)
     .join(MenuPricePoint, MenuPricePoint.item_id == MenuItem.id)
     .join(LocalEmployer, LocalEmployer.id == MenuItem.restaurant_id)
     .outerjoin(BrandGroup, BrandGroup.id == LocalEmployer.brand_group_id)
     .filter(MenuPricePoint.price.isnot(None))
     .filter(MenuPricePoint.confidence >= min_confidence))
```

**Response row:**
```json
{
  "restaurant_id": 123,
  "restaurant_name": "La Posada South",
  "address": "1200 W Lynn St, Austin TX",
  "lat": 30.27, "lng": -97.74,
  "distance_mi": 0.4,
  "brand_fingerprint": "la_posada",
  "industry": "Mexican",
  "item_id": "i_abc...",
  "item_name": "Fajita Platter",
  "description": "Chicken or Beef Fajitas with sides",
  "course": "entree",
  "calories": 820,
  "dietary_tags": [],
  "price": 18.99,
  "price_per_calorie": 0.023,
  "variant": null,
  "confidence": 0.95,
  "section_name": "Lunch Specials",
  "service_period": "lunch",
  "source_url": "https://laposadasouth.com/menu"
}
```

**Return envelope:** `{"items": [...], "total": N, "limit": L, "offset": O}` so the frontend can render "Showing 1–50 of 312".

#### `GET /api/price-index/facets?region=austin_tx&lat=&lng=&radius_mi=`

Returns lightweight filter population data — **called once per tab load**, cached client-side:
```json
{
  "cuisines": [{"key": "Mexican", "count": 47}, ...],
  "courses": [{"key": "entree", "count": 3200}, ...],
  "brands": [{"fingerprint": "subway", "canonical_name": "Subway", "count": 12}, ...],
  "price_range": {"min": 1.50, "max": 89.99, "p50": 12.99},
  "calorie_range": {"min": 40, "max": 2400, "p50": 650}
}
```

### Step 7 — Register Blueprint

In [server.py](server.py) near line 204:
```python
from collectors.meal_deals.price_index_routes import price_index_bp
app.register_blueprint(price_index_bp)
```

### Step 8 — Frontend (performance-first)

> **Location:** All frontend work happens in `/home/fortune/CodeProjects/First-Helios_Frontend/` (sibling repo). Study the existing `js/mealdeals.js` for the tab pattern before writing new code.

#### Performance strategy (experimental, data-heavy tab)

**Core principle: nothing loads until the user asks.**

1. On tab activation → render filter controls only. **Zero API calls to `/api/price-index`.**
2. Facets endpoint (`/api/price-index/facets`) is called **once** on first tab open, cached in JS module-level variable.
3. On first explicit search (button press or Enter in keyword input) → single request with all filters. Skeleton loader during fetch.
4. Results **replace** previous results entirely on a new search.
5. "Load more" button appends next page but **prunes DOM**: when 3rd page loads, remove the 1st page's nodes. Keep max 100 cards live in DOM.
6. Keyword input debounced 300ms; fires only on blur/Enter — **never on every keystroke**.
7. **No map rendering** in this tab at all — pure list view. Distance is a sortable column, not a visual.

#### Files to create/modify (all paths relative to `/home/fortune/CodeProjects/First-Helios_Frontend/`)

- `index.html` — add mode button `<button id="mode-priceindex" class="mode-btn">Price Index</button>` + `#priceindex-panel` sidebar + `#priceindex-results` main area with placeholder "Search for food prices near you"
- `js/app.js` — add `"priceindex"` case to `switchMode()`; call `initPriceIndex()` (idempotent — only runs once)
- **New:** `js/priceindex.js` — mirror the structure of existing `js/mealdeals.js`
- `js/config.js` — add the API base URL entry if needed (check existing pattern)

#### UI layout (`priceindex.js`)

```
┌─ Filters ───────────────────────────────────────────┐
│  [Keyword input ________] [Search]                  │
│  Cuisine: [dropdown ▾]  Course: [chips]             │
│  Price:   [min]–[max]   Cals: [min]–[max]           │
│  Sort:    [Price ▾]                                 │
└─────────────────────────────────────────────────────┘

Showing 1–50 of 312 results

┌─ Result card ────────────────────────────────────────┐
│ La Posada South                          0.4 mi away │
│ Fajita Platter                               $18.99  │
│ Chicken or Beef Fajitas with sides                   │
│ 820 cal  |  $0.023/cal                               │
│ Lunch Specials › entree         [VeganDiet] [→ Menu] │
└──────────────────────────────────────────────────────┘

           [ Load more ]
```

The `[→ Menu]` link is the **handoff exit** — opens `source_url` in a new tab. This satisfies the user's request that "at the end we can make a handoff from the front end if needed" — the user can always click through to the restaurant's actual page.

---

## Out of Scope (explicit non-goals)

- Map rendering for price index results (list-only)
- Real-time price updates / subscription model
- Ingredient-level nutrition (using `menu_items.calories` only)
- Modifier pricing in search (modifiers stored but not factored into `price_per_calorie`)
- Persisting `menu_offer_targets` to DB (those are deal-linking, not baseline-menu) — can be added later if needed

---

## Verification

Execute in order:

1. **Schema:** `alembic upgrade head` — confirm 5 new tables in psql via `\dt menu_*`
2. **Backfill:** `python scripts/backfill_menu_tables.py --dry-run` first, then without. Expected: row counts > 0 for every table if bundles exist
3. **API basic:** `curl "http://localhost:8765/api/price-index?region=austin_tx&limit=5"` → 5 items with full response shape
4. **API keyword:** `curl "http://localhost:8765/api/price-index?q=taco&region=austin_tx"` → only taco-matching items
5. **API price-per-calorie sort:** `curl "...?sort=price_per_calorie&min_calories=100"` → ascending by $/cal
6. **API facets:** `curl "http://localhost:8765/api/price-index/facets?region=austin_tx"` → populated dropdowns
7. **Live ingest:** Run a website scrape against a test restaurant (see `docs/guides/MEAL_DEAL_SCRAPERS_RUNBOOK.md`). After scrape, query `menu_items` for that `restaurant_id` — rows must exist
8. **Frontend smoke test:** Load the app, click "Price Index" tab, confirm zero API calls until user hits Search. Then confirm single request, results render, "Load more" works, DOM stays ≤100 cards
9. **Regression:** `pytest tests/HeliosDeployment/test_menu_persistence_schema.py tests/HeliosDeployment/test_menu_sidecar.py` must pass unchanged

---

## Open Questions for Implementer

1. **Cuisine taxonomy:** `local_employers.industry` holds raw ingested strings. Do we need a normalization layer or is the set small enough to trust? (Worth a quick `SELECT DISTINCT industry FROM local_employers` before committing.)
2. **Confidence floor:** Default `min_confidence=0.55` matches the DOM-fallback threshold. Should price_index exclude DOM-only prices (keep only JSON-LD ≥0.85)? Could hurt coverage materially.
3. **Keyword search:** Start with `ILIKE '%q%'` or invest in pg_trgm GIN index upfront? Depends on production row counts after backfill — measure first.

---

## Contact / Context

Plan file at `/home/fortune/.claude/plans/we-want-to-make-abstract-lake.md` has the identical content in case this doc is moved.
