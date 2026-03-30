# H3 Conversion Tracker

Tracks every table with location data and its readiness for H3 geospatial indexing.

**Goal:** Replace zoom-agnostic random sampling with resolution-adaptive hexagonal aggregation.
**Target resolutions:** r6 (city), r7 (neighborhood), r8 (corridor), r9 (block)
**Backend binding:** h3-py | **Frontend binding:** h3-js v4 (CDN)

---

## Zoom-to-Resolution Map

| Leaflet Zoom | H3 Resolution | ~Cells (Austin) | Render Mode |
|---|---|---|---|
| 8–9 | r6 | ~25 | Hex heatmap |
| 10–11 *(default)* | r7 | ~180 | Hex heatmap |
| 12–13 | r8 | ~1,200 | Hex heatmap |
| 14–15 | r9 | ~8,000 | Hex heatmap |
| 16+ | — | raw | `circleMarker` fallback |

---

## Tables with Location Data

### 1. `local_employers`

| Dimension | Detail |
|---|---|
| **What it does** | Primary employer POI layer. Every business in Austin with a name, address, industry, and brand classification. Drives the map's main employer layer and targeting pipeline. |
| **Data source** | Overture Maps (austin_tx GeoParquet), ingested via `backend/ingest_layer.py`. All 45,618 rows have lat/lng. |
| **Geo columns** | `lat FLOAT`, `lng FLOAT`, `region VARCHAR` |
| **Row count** | 45,618 (all geocoded) |
| **H3 value** | **Highest.** This is the map's primary dataset. At default zoom 11 (r7), 45K points collapse to ~180 hex cells — a 250× reduction in payload. Enables instant density heatmaps, brand vs local ratio per hex, and smooth zoom-drill behavior. |
| **Columns to add** | `h3_r6 VARCHAR(15)`, `h3_r7 VARCHAR(15)`, `h3_r8 VARCHAR(15)`, `h3_r9 VARCHAR(15)` |
| **New API endpoint** | `GET /api/h3-map?resolution=7&industry=&region=austin_tx` |
| **Update status** | ⬜ NOT STARTED |

---

### 2. `chain_locations`

| Dimension | Detail |
|---|---|
| **What it does** | Tracked chain store locations (H-E-B, Starbucks, Whataburger, etc.). Used by the pathfinder and targeting scoring as validated ground-truth store positions. |
| **Data source** | Overture Maps via same ingest pipeline as local_employers, filtered to known brand_keys. 283 rows. |
| **Geo columns** | `lat FLOAT`, `lng FLOAT`, `address VARCHAR`, `region VARCHAR` |
| **Row count** | 283 (all geocoded) |
| **H3 value** | **Medium.** Small enough that individual markers are fine at all zooms. Primary H3 value is proximity lookups — e.g. "which H3 cell does this store belong to" for colocation analysis and isolation scoring. Adding `h3_r8` enables fast spatial joins with local_employers. |
| **Columns to add** | `h3_r8 VARCHAR(15)`, `h3_r9 VARCHAR(15)` |
| **Update status** | ⬜ NOT STARTED |

---

### 3. `brand_groups`

| Dimension | Detail |
|---|---|
| **What it does** | Canonical brand name registry. Aggregates local_employer rows by fingerprinted name. Holds `location_count` (how many Austin locations a brand has). Used to classify employers as "brand" vs "local" in the API response. |
| **Data source** | Derived/maintained by `backend/ingest_layer.py` during ingestion. No direct geo. |
| **Geo columns** | None — location data lives in `local_employers.brand_group_id` FK |
| **Row count** | 36,563 |
| **H3 value** | **Indirect.** No H3 columns on this table itself. Value comes from joining to local_employers on `brand_group_id` to get per-hex brand density. No columns to add here. |
| **Columns to add** | None |
| **Update status** | ✅ N/A — no direct geo |

---

### 4. `job_postings`

| Dimension | Detail |
|---|---|
| **What it does** | Job listing records (title, employer, SOC code, salary, posting date). Intended as the primary signal for labor market demand at specific employers and locations. |
| **Data source** | Future: scrapers targeting Indeed / LinkedIn / direct employer sites. Currently 0 rows. Schema has `lat FLOAT`, `lng FLOAT`, `geocode_source VARCHAR`. |
| **Geo columns** | `lat FLOAT`, `lng FLOAT`, `raw_address VARCHAR`, `region VARCHAR`, `geocode_source VARCHAR` |
| **Row count** | 0 (not yet populated) |
| **H3 value** | **High (future).** Once populated, job postings per H3 cell = direct demand signal. Comparing posting density to employer density per hex enables gap analysis (high employers, low postings = stagnant area). |
| **Columns to add** | `h3_r7 VARCHAR(15)`, `h3_r8 VARCHAR(15)`, `h3_r9 VARCHAR(15)` — add at backfill time |
| **Update status** | ⬜ DEFERRED — no data yet |

---

### 5. `cbp_data` *(County Business Patterns)*

| Dimension | Detail |
|---|---|
| **What it does** | Census ZIP-level establishment counts and employment by NAICS industry code. Ground truth for "how many employers of this type exist in this ZIP." Used for market saturation scoring. |
| **Data source** | U.S. Census Bureau CBP annual release. Ingested via `pipeline/`. Currently 0 rows. |
| **Geo columns** | `zip_code VARCHAR(5)`, `region VARCHAR` |
| **Row count** | 0 (not yet populated) |
| **H3 value** | **Medium (future).** ZIP codes don't align to H3 cells. Value comes from geocoding ZIP centroids → H3 cells, enabling ZIP-based census data to be spatially joined with Overture employer data. Requires a ZIP centroid lookup table. |
| **Columns to add** | `h3_r7 VARCHAR(15)` (ZIP centroid → cell) once data is loaded |
| **Update status** | ⬜ DEFERRED — no data yet |

---

### 6. `qcew_data` *(Quarterly Census of Employment & Wages)*

| Dimension | Detail |
|---|---|
| **What it does** | BLS county-level quarterly employment and wage data by NAICS industry. Used for wage baseline and labor market health metrics. |
| **Data source** | BLS QCEW API / CSV. Currently 0 rows. FIPS-coded to county level. |
| **Geo columns** | `fips_code VARCHAR(5)`, `region VARCHAR` |
| **Row count** | 0 (not yet populated) |
| **H3 value** | **Low — county granularity too coarse.** A Texas county covering all of Travis Co maps to a single large polygon, not meaningful at H3 r7+. More useful as a label/attribute on hex aggregates than as a spatial join. |
| **Columns to add** | None planned |
| **Update status** | ✅ N/A — county granularity too coarse for H3 |

---

### 7. `laus_data` *(Local Area Unemployment Statistics)*

| Dimension | Detail |
|---|---|
| **What it does** | BLS monthly unemployment rate and labor force estimates by county/MSA. Used for macro labor market context in scoring. |
| **Data source** | BLS LAUS API. Currently 0 rows. FIPS-coded. |
| **Geo columns** | `fips_code VARCHAR(5)`, `region VARCHAR` |
| **Row count** | 0 (not yet populated) |
| **H3 value** | **None.** Metro/county level data. No sub-county precision — H3 doesn't help here. |
| **Columns to add** | None |
| **Update status** | ✅ N/A — MSA/county level, not point data |

---

### 8. `wage_index`

| Dimension | Detail |
|---|---|
| **What it does** | ZIP-level wage benchmarks (median wage by occupation and ZIP). Used to compute wage gap scoring for individual employers. |
| **Data source** | BLS OEWS + Census wage estimates. Currently 0 rows. |
| **Geo columns** | `zip_code VARCHAR(5)` |
| **Row count** | 0 (not yet populated) |
| **H3 value** | **Medium (future).** Same as cbp_data — ZIP centroids can be mapped to H3 r7 cells to enable spatial wage surface visualization. Useful for "wage heat map" overlay. |
| **Columns to add** | `h3_r7 VARCHAR(15)` (ZIP centroid) once data is loaded |
| **Update status** | ⬜ DEFERRED — no data yet |

---

### 9. `ref_regions`

| Dimension | Detail |
|---|---|
| **What it does** | Registry of supported metro regions (e.g. austin_tx). Stores center lat/lng, FIPS, population, and bounding box metadata. |
| **Data source** | Manually configured reference table. Currently 0 rows. |
| **Geo columns** | `center_lat FLOAT`, `center_lng FLOAT`, `fips_code VARCHAR` |
| **Row count** | 0 (not yet populated) |
| **H3 value** | **None for H3 indexing.** This is configuration data, not point data. The H3 cell for a region center is not useful. |
| **Columns to add** | None |
| **Update status** | ✅ N/A — config/reference table |

---

## Implementation Sequence

| Step | Task | Affects | Status |
|---|---|---|---|
| 1 | `pip install h3` in `.venv` | backend | ✅ h3-py 4.4.2 |
| 2 | `scripts/add_h3_columns.py` — ALTER TABLE + indexes | `local_employers`, `chain_locations` | ✅ |
| 3 | `scripts/backfill_h3_cells.py` — batch compute r6/r7/r8/r9 | `local_employers` (45,618 rows → 453 r7 cells), `chain_locations` (283 rows → 156 r8 cells) | ✅ |
| 4 | `GET /api/h3-map` endpoint in `server.py` | backend API | ✅ 453 cells @ r7, 200 OK |
| 5 | `frontend/js/h3map.js` — hex render layer | frontend | ✅ |
| 6 | `frontend/index.html` — add h3-js CDN script tag | frontend | ✅ h3-js 4.1.0 |
| 7 | `frontend/js/app.js` — zoom event wiring | frontend | ✅ |
| — | ZIP centroid → H3 lookup (cbp_data, wage_index) | future | ⬜ DEFERRED |
| — | job_postings H3 backfill | future | ⬜ DEFERRED |

---

*Last updated: 2026-03-26 — branch `h3Convert`*
