# Menu Sidecar

**Files:** `collectors/meal_deals/menu_sidecar.py` · `collectors/meal_deals/menu_persistence_schema.py`

The menu sidecar is a structured, in-memory snapshot of a restaurant's baseline menu — built during a scrape, attached to the debug bundle, and referenced from `DealSignal.metadata`. It is the upstream evidence layer that deal scoring, signal targeting, and value analysis build on.

It is **not a database table**. It lives in replayable debug bundles until replay coverage is sufficient to justify committing to a DB schema. The target schema (`menu_persistence_schema.py`) is already defined so the sidecar stays forward-compatible.

---

## What's collected

A `MenuSidecar` holds six entity dicts. All keys are deterministic SHA-1 hashes so re-scraping the same site produces the same IDs.

| Entity | Key prefix | What it represents |
|---|---|---|
| `pages` | `p_...` | Each URL that was ingested |
| `sections` | `s_...` | Menu / MenuSection nodes — tagged with `service_period` and `course` |
| `items` | `i_...` | Individual menu items — name, description, calories, dietary tags |
| `price_points` | `pp_...` | Absolute prices tied to an item or section, with `confidence` |
| `modifiers` | `mod_...` | Add-ons / upgrades with price deltas |
| `offer_targets` | `ot_...` | Links from a DealSignal to the item/section/service_period it targets |

### Caps (so bundles stay small)

| Entity | Max per site |
|---|---|
| sections | 80 |
| items | 800 |
| price_points | 1 600 |
| modifiers | 200 |
| offer_targets | 400 |

---

## How data gets in

Three ingesters are used in priority order. The scraper tries JSON-LD first; if nothing was added it falls back to DOM parsing.

| Ingester | Source | Confidence | When used |
|---|---|---|---|
| `ingest_jsonld_from_html` | `<script type="application/ld+json">` schema.org `Menu` / `MenuItem` / `Offer` | 0.95 (items) · 0.85 (sections) | Preferred — most structured sites |
| `ingest_dom_fallback` | Heading → nearest list/table item+price pairs | 0.55 | Fallback when JSON-LD yields nothing |
| `ingest_pdf_tables` | pdfplumber-style cell tables | 0.75 | PDF menus |

### Service period tagging

Section names are matched against rules to set `service_period`:

`happy_hour` · `brunch` · `lunch` · `dinner` · `late_night` · `early_bird` · `kids` · `weekend` · `weekday`

### Course tagging

Items and sections get a `course` value from their name/description:

`appetizer` · `salad_soup` · `entree` · `side` · `dessert` · `drink` · `kids` · `combo`

---

## What you can do with it

### 1. Get price baselines

```python
from collectors.meal_deals.menu_sidecar import MenuSidecar

# Median price per course — answers "is this deal cheap for an entree?"
sidecar.course_price_baseline()
# → {"entree": 18.50, "drink": 9.00, "side": 4.75}

# Median price per menu section key
sidecar.section_price_baseline()

# Full value profile — min/max/median/sample_size per course + service periods
sidecar.value_profile()
```

### 2. Link a DealSignal to a menu entity

```python
from collectors.meal_deals.menu_sidecar import link_signal_to_target

result = link_signal_to_target(
    sidecar,
    signal_ref="happy_hour_margarita_2for1",
    page_url="https://example.com/menu",
    context_path=["Happy Hour"],          # section path from JSON-LD
    primary_name="House Margarita",       # item name from the signal
    service_period="happy_hour",          # optional override
)
```

Returns a dict (and mutates the sidecar with a new `OfferTarget`):

```json
{
  "key": "ot_abc123...",
  "scope": "item",
  "section_key": "s_...",
  "item_key": "i_...",
  "confidence": 0.95,
  "disposition": "auto_accept",
  "match_method": "path_plus_name_item"
}
```

#### Confidence rubric

| Match method | Confidence | Disposition |
|---|---|---|
| `path_plus_name_item` | 0.95 | `auto_accept` |
| `path_only_section` | 0.85 | `auto_accept` |
| `name_only_item` | 0.65 | `review` |
| `service_period_only` | 0.55 | `review` |
| `venue` | 0.25 | `discard` |

### 3. Serialize for replay / future DB

```python
from collectors.meal_deals.menu_persistence_schema import serialize_sidecar, check_foreign_keys, summarize_shape

shape = serialize_sidecar(
    sidecar,
    restaurant_id="local_employer_uuid_here",
    source_url="https://example.com/menu",
    source_bundle="bundle_id_here",
)

# Validate FK consistency before any DB write
violations = check_foreign_keys(shape)

# One-liner sanity summary
print(summarize_shape(shape))
```

`PersistentShape` row IDs equal sidecar keys — upserts from replay bundles are idempotent.

### 4. Inspect from a debug bundle

The scraper attaches the sidecar to bundles at `bundle["menu_sidecar"]` via `sidecar.to_dict()`. That dict has the same structure as `PersistentShape` plus `baselines` and `value_profile` pre-computed:

```json
{
  "pages": [...],
  "sections": [...],
  "items": [...],
  "price_points": [...],
  "modifiers": [...],
  "offer_targets": [...],
  "baselines": {
    "course_price_median": {"entree": 18.50},
    "section_price_median": {"s_abc": 12.00}
  },
  "value_profile": {...},
  "counts": {...}
}
```

---

## Design rules

- **Sidecar-first**: no DB tables until replay coverage justifies it. Evidence accumulates in bundles.
- **Deterministic keys**: same site + same menu → same IDs. Replay bundles stay stable.
- **Never blocks a scrape**: all ingest calls in the scraper are wrapped in `try/except` — a sidecar failure degrades gracefully to no sidecar.
- **Forward-compatible**: column names and FK relationships in `menu_persistence_schema.py` match the sidecar exactly, so a future migration script can lift rows straight from bundles.

---

## Related files

| File | Purpose |
|---|---|
| `collectors/meal_deals/menu_sidecar.py` | All data models, ingesters, classifiers, offer-target linker |
| `collectors/meal_deals/menu_persistence_schema.py` | Target DB row shapes + `serialize_sidecar` + FK checker |
| `collectors/meal_deals/website_scraper.py` | Calls `_populate_sidecar_for_page` and `_link_signals_to_sidecar` per page |
| `tests/HeliosDeployment/test_menu_sidecar.py` | Unit tests — JSON-LD ingest, DOM fallback, signal linking |
| `tests/HeliosDeployment/test_menu_persistence_schema.py` | Serialize + FK check tests |
| `docs/guides/MEAL_DEAL_REPLAY_WORKFLOW.md` | How to replay bundles that contain sidecars |
| `docs/guides/MEAL_DEAL_SCRAPER_SIGNAL_REFINEMENT_ROADMAP.md` | STRUCT-01 / TARGET-01 / PRICE-02 / VALUE-01 roadmap items |
